"""PC 연결 코드·토큰(계약 esl_p3_ux.md §9.1).

- 코드: 6자리 숫자, `client_token.code_ttl_min`(기본 15분) 유효, 1회용, 발급한 사용자·현재 프로젝트·역할(power 이상)에 묶임.
  DB 에는 sha256 만 저장.
- 교환: 코드 → 토큰 `esl_ct_<random>`(원문은 교환 응답에 한 번만, DB 는 sha256), 기본 30일(`client_token.ttl_days`).
  실패(없음·만료·사용됨·형식 오류) 잠금(계약 §10): 출발지를 구분할 수 있으면(peer 가 루프백이 아님, 또는 peer 가
  `client_token.trusted_proxies` 이고 그 프록시가 붙인 X-Forwarded-For 가 있음) 출발지별 `lock_per_source`(기본 5)회,
  구분할 수 없으면(신뢰하지 않는 루프백 프록시 뒤 등) 서버 전체 키 하나로 `lock_global`(기본 30)회 — 넘으면
  `lock_minutes`(기본 15분) 동안 그 키의 교환을 거부(429 `CLIENT_CODE_LOCKED`). 전체 키는 구분 불가 요청만 센다.
- 토큰 인증: 해시 조회 → 만료·폐기면 401 `CLIENT_TOKEN_INVALID`(PC 도구는 코드를 다시 묻는다). 주체 = 토큰 사용자,
  역할 = 발급 시점 역할(그 프로젝트만). 범위 = 그 프로젝트의 `/uploads*` 와 `GET /version`(그 밖 403 `CLIENT_TOKEN_SCOPE`).
- 목록·폐기: 내 토큰(전역 관리자는 폐기만 남의 것도). 폐기는 삭제 없이 revoked_at.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, case, func, insert, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core.auth import Principal
from ...core.db.tables import client_code_failures, client_codes, client_tokens
from ...core.errors import DomainError, not_found
from ..context import AppContext
from ..deps import CLIENT_TOKEN_PREFIX
from .common import require_execute

CODE_DIGITS = 6
_CODE_RE = re.compile(r"^\d{6}$")


def secret_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ttl(minutes: float):
    return func.now() + literal(timedelta(minutes=float(minutes)))


def _project_name(projects: list[dict[str, Any]], pid: str) -> str | None:
    return next((p.get("name") for p in projects if p["id"] == pid), None)


# ---------------------------------------------------------------- 코드
def create_code(ctx: AppContext, principal: Principal, projects: list[dict[str, Any]], project_id: str) -> dict:
    if project_id not in {p["id"] for p in projects}:
        raise not_found("PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다")
    require_execute(principal, project_id)
    role = principal.role(project_id)
    cfg = ctx.settings.client_token
    with ctx.engine.begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("esl-client-code"))))
        for _ in range(50):
            code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
            h = secret_hash(code)
            busy = conn.execute(select(client_codes.c.id).where(and_(
                client_codes.c.code_hash == h, client_codes.c.used_at.is_(None),
                client_codes.c.expires_at > func.now()))).first()
            if busy is None:
                break
        else:  # pragma: no cover - 사실상 불가(동시 유효 코드 수 ≪ 10^6)
            raise DomainError("CLIENT_CODE_BUSY", "연결 코드를 만들 수 없습니다. 잠시 뒤 다시 시도하세요", status=503)
        cid = str(uuid.uuid4())
        conn.execute(insert(client_codes).values(
            id=cid, code_hash=h, project_id=project_id, project_name=_project_name(projects, project_id),
            user_id=principal.user_id, username=principal.username, display_name=principal.display_name,
            role="admin" if role == "admin" else "power", expires_at=_ttl(cfg.code_ttl_min)))
        exp = conn.execute(select(client_codes.c.expires_at).where(client_codes.c.id == cid)).scalar_one()
    return {"code": code, "project_id": project_id, "expires_at": exp}


GLOBAL_SOURCE = "*global*"   # 출발지 구분 불가 요청의 공용 잠금 키(IP 와 겹치지 않음)


def _trusted(peer: str, proxies: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer in proxies
    for p in proxies:
        try:
            if ip in ipaddress.ip_network(p, strict=False):
                return True
        except ValueError:
            continue
    return False


def _loopback(peer: str) -> bool:
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return peer in ("", "unknown", "localhost", "testclient")


def request_source(peer: str | None, xff: str | None, trusted_proxies: list[str] | tuple[str, ...] = ()) -> str | None:
    """잠금 키가 될 출발지. 구분할 수 없으면 None(→ 서버 전체 키).

    - peer 가 신뢰 프록시면 X-Forwarded-For 를 오른쪽부터 읽어 신뢰 프록시가 아닌 첫 값(= 프록시가 붙인 클라이언트 주소).
      XFF 가 없거나 모두 신뢰 프록시면 None.
    - peer 가 신뢰하지 않는 루프백(또는 알 수 없음)이면 None — XFF 는 위조할 수 있으므로 쓰지 않는다.
    - 그 밖(비루프백 peer) = peer.
    """
    proxies = list(trusted_proxies or ())
    peer = (peer or "unknown").strip()[:100]
    if proxies and _trusted(peer, proxies):
        for hop in reversed([h.strip() for h in (xff or "").split(",")]):
            if not hop:
                continue
            if _trusted(hop, proxies):
                continue
            return hop[:100]
        return None
    if _loopback(peer):
        return None
    return peer


def _limit(source: str, cfg) -> int:
    return int(cfg.lock_global if source == GLOBAL_SOURCE else cfg.lock_per_source)


def _failure(conn, source: str, cfg) -> tuple[int, bool]:
    """실패 1회 기록 → (누적, 잠김 여부). 창(lock_minutes)이 지난 기록은 새로 센다."""
    window = literal(timedelta(minutes=float(cfg.lock_minutes)))
    stmt = pg_insert(client_code_failures).values(source=source, failures=1, window_started_at=func.now())
    stmt = stmt.on_conflict_do_update(index_elements=["source"], set_={
        "failures": case((client_code_failures.c.window_started_at < func.now() - window, 1),
                              else_=client_code_failures.c.failures + 1),
        "window_started_at": case((client_code_failures.c.window_started_at < func.now() - window, func.now()),
                                       else_=client_code_failures.c.window_started_at),
    })
    conn.execute(stmt)
    n = int(conn.execute(select(client_code_failures.c.failures)
                         .where(client_code_failures.c.source == source)).scalar_one())
    locked = n >= _limit(source, cfg)
    if locked:
        conn.execute(update(client_code_failures).where(client_code_failures.c.source == source)
                     .values(locked_until=_ttl(cfg.lock_minutes)))
    return n, locked


def _locked(conn, source: str) -> bool:
    return conn.execute(select(client_code_failures.c.source).where(and_(
        client_code_failures.c.source == source, client_code_failures.c.locked_until > func.now()))).first() is not None


def _locked_error(source: str, cfg) -> DomainError:
    who = "이 서버 전체에서" if source == GLOBAL_SOURCE else "이 PC(주소)에서"
    return DomainError("CLIENT_CODE_LOCKED", f"연결 코드를 {who} {_limit(source, cfg)}회 잘못 입력해 {cfg.lock_minutes:g}분 "
                       "동안 잠겼습니다. 잠시 뒤 ESL 화면에서 새 코드를 만들어 다시 시도하세요", status=429)


def exchange(ctx: AppContext, source: str | None, code: str, device_name: str) -> dict[str, Any]:
    cfg = ctx.settings.client_token
    source = source or GLOBAL_SOURCE
    norm = re.sub(r"[\s\-]", "", code or "")
    err: DomainError | None = None
    with ctx.engine.begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("esl-client-src:" + source))))
        if _locked(conn, source):
            raise _locked_error(source, cfg)
        row = None
        if _CODE_RE.match(norm):
            row = conn.execute(select(client_codes).where(and_(
                client_codes.c.code_hash == secret_hash(norm), client_codes.c.used_at.is_(None),
                client_codes.c.expires_at > func.now())).with_for_update()).mappings().first()
        if row is None:
            n, locked = _failure(conn, source, cfg)
            left = max(0, _limit(source, cfg) - n)
            if locked:
                err = _locked_error(source, cfg)
            else:
                err = DomainError("CLIENT_CODE_INVALID", "연결 코드가 맞지 않거나 만료되었습니다(이미 쓴 코드는 다시 쓸 수 "
                                  f"없음). 남은 시도 {left}회", status=401, remaining=left)
        else:
            raw = CLIENT_TOKEN_PREFIX + secrets.token_urlsafe(32)
            tid = str(uuid.uuid4())
            conn.execute(insert(client_tokens).values(
                id=tid, token_hash=secret_hash(raw), token_prefix=raw[:12], project_id=row["project_id"],
                project_name=row["project_name"], user_id=row["user_id"], username=row["username"],
                display_name=row["display_name"], role=row["role"], device_name=device_name.strip()[:100] or "PC",
                expires_at=func.now() + literal(timedelta(days=float(cfg.ttl_days)))))
            conn.execute(update(client_codes).where(client_codes.c.id == row["id"])
                         .values(used_at=func.now(), token_id=tid))
            if source != GLOBAL_SOURCE:   # 전체 키는 성공으로 지우지 않는다(남의 실패 기록)
                conn.execute(update(client_code_failures).where(client_code_failures.c.source == source)
                             .values(failures=0, locked_until=None, window_started_at=func.now()))
            exp = conn.execute(select(client_tokens.c.expires_at).where(client_tokens.c.id == tid)).scalar_one()
    if err is not None:
        raise err   # 실패 기록은 위 트랜잭션에서 이미 커밋
    return {"token": raw, "token_id": tid,
            "user": {"user_id": row["user_id"], "username": row["username"], "display_name": row["display_name"]},
            "project": {"id": row["project_id"], "name": row["project_name"]}, "expires_at": exp}


# ---------------------------------------------------------------- 인증·범위
def _invalid() -> DomainError:
    return DomainError("CLIENT_TOKEN_INVALID", "PC 연결 토큰이 만료되었거나 폐기되었습니다. ESL 화면에서 새 연결 코드를 만드세요",
                       status=401)


def authenticate(ctx: AppContext, raw: str) -> Principal:
    if len(raw) > 200:
        raise _invalid()
    with ctx.engine.begin() as conn:
        row = conn.execute(select(client_tokens).where(and_(
            client_tokens.c.token_hash == secret_hash(raw), client_tokens.c.revoked_at.is_(None),
            client_tokens.c.expires_at > func.now()))).mappings().first()
        if row is None:
            raise _invalid()
        conn.execute(update(client_tokens).where(client_tokens.c.id == row["id"]).values(last_used_at=func.now()))
    return Principal(row["user_id"], row["username"], row["display_name"], False, {row["project_id"]: row["role"]},
                     client_token_id=row["id"], token_project_id=row["project_id"])


def check_scope(ctx: AppContext, method: str, path: str) -> None:
    prefix = ctx.settings.api_prefix
    rel = path[len(prefix):] if path.startswith(prefix) else None
    ok = rel is not None and ((rel == "/version" and method in ("GET", "HEAD"))
                              or rel == "/uploads" or rel.startswith("/uploads/"))
    if not ok:
        raise DomainError("CLIENT_TOKEN_SCOPE", "PC 연결 토큰으로는 업로드(/uploads)와 버전(/version)만 쓸 수 있습니다",
                          status=403)


# ---------------------------------------------------------------- 목록·폐기
def _out(r: dict[str, Any]) -> dict[str, Any]:
    state = "REVOKED" if r["revoked_at"] else ("EXPIRED" if r["expired"] else "ACTIVE")
    keys = ("id", "token_prefix", "project_id", "project_name", "device_name", "user_id", "username", "created_at",
            "expires_at", "last_used_at", "revoked_at")
    return {**{k: r[k] for k in keys}, "state": state}


def _cols():
    return [client_tokens, (client_tokens.c.expires_at <= func.now()).label("expired")]


def list_tokens(ctx: AppContext, principal: Principal, project_id: str | None) -> list[dict[str, Any]]:
    q = select(*_cols()).where(client_tokens.c.user_id == principal.user_id)
    if project_id:
        q = q.where(client_tokens.c.project_id == project_id)
    with ctx.engine.connect() as conn:
        rows = conn.execute(q.order_by(client_tokens.c.created_at.desc()).limit(100)).mappings().all()
    return [_out(dict(r)) for r in rows]


def revoke(ctx: AppContext, principal: Principal, token_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        r = conn.execute(select(*_cols()).where(client_tokens.c.id == token_id).with_for_update(of=client_tokens)
                         ).mappings().first()
        if r is None or (r["user_id"] != principal.user_id and not principal.is_global_admin):
            raise not_found("CLIENT_TOKEN_NOT_FOUND", "연결된 PC 토큰을 찾을 수 없습니다")
        if r["revoked_at"] is None:
            conn.execute(update(client_tokens).where(client_tokens.c.id == token_id)
                         .values(revoked_at=func.now(), revoked_by=principal.user_id))
        r = conn.execute(select(*_cols()).where(client_tokens.c.id == token_id)).mappings().first()
    return _out(dict(r))
