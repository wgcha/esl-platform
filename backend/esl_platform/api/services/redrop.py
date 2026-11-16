"""재낙하 입력 묶음 받기(계약 esl_redrop_bundle.md, v0.22.0 REDROP) — 설계안 1개·엔트리 1개의 Radioss 입력 zip.

`GET /doe/studies/{sid}/designs/{did}/redrop?entry_id=` — 검증 낙하와 같은 원본 입력 폐포(`verify_drop.input_set`)·같은 노드 패치
(`esl.verify.patch.patch_design`)를 쓰되 좌표 출처는 `run/designs/<did>/design.npz`, 제출은 하지 않는다(zip 만).

- 동기 스트리밍 + 임시 폴더 `<esl_root>/_redrop/<token>/`(바뀐 파일 `input/<rel>` + manifest + README). 정리: 스트림 끝 `finally`,
  요청마다 시작 시 ttl 지난 잔여, 4xx 로 끝나면 즉시. SPDM·입력 폴더·`_doe/<sid>` 에는 쓰지 않는다(I-6).
- 허용 판정 = 계획 표 열 `redrop`(`opt_core.doe_transfer_plan`) — 시나리오 이름으로 분기하지 않는다.
- 응답이 시작되기 전에 모든 검사·패치가 끝난다(스트리밍 도중 오류 코드 없음).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from typing import Any

from ...core.auth import Principal
from ...core.config import bead_doe_settings
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.opt_core import doe_transfer_plan, verify_redrop, verify_stages
from ...core.paths import REDROP_DIR, esl_subdir
from ...core.repositories import cases as cases_repo
from ...core.repositories import library as lib_repo
from ...core.scx.mask import mask_text
from ..context import AppContext
from . import bundle as bundle_svc
from . import verify_drop
from .pathmask import masks_paths

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_SLUG_BAD = re.compile(r'[\\/:*?"<>|\s]+')

MSG_UNSUPPORTED = "이 모드는 원 Case 노드 번호를 쓰지 않아 재낙하 입력을 만들 수 없습니다(① 같은 Case 기준만)"
MSG_DISABLED = "재낙하 입력 받기가 꺼져 있습니다"
MSG_NO_ENTRY = "재낙하 입력을 만들 수 있는 엔트리가 없습니다"
R_NO_ENTRY = "엔트리가 없습니다"
R_NO_CASE = "원 Case 가 없거나 보관됨"
R_CUMULATIVE = "누적 Case — 재낙하 입력 불가"
# 코어 오류 코드 → HTTP (표에 없는 코어 오류는 422)
_CORE_STATUS = {"REDROP_NODESET_MISMATCH": 409, "REDROP_BASE_CHANGED": 409}


def rcfg(ctx: AppContext) -> dict[str, Any]:
    return bead_doe_settings(ctx.settings)["redrop"]


def _mask(text: Any) -> str:
    return mask_text(text, 400)


# ---------------------------------------------------------------- 계획 열
def plan_of(s: dict[str, Any]) -> dict[str, Any] | None:
    """스터디 → 하중 전달 계획 행(+id). 알 수 없는 조합 = None. select_base 는 계획 표가 select 에서만 읽는다(① = 키 없음 = case)."""
    sb = (s.get("inputs") or {}).get("select_base") or "case"
    try:
        return doe_transfer_plan.plan_for(s["scenario"], sb)
    except Exception:       # EslError CONFIG_INVALID — 계획 없음 = 불가
        return None


def flags(ctx: AppContext, s: dict[str, Any], entries: list[dict[str, Any]] | None = None) -> tuple[bool, str | None]:
    """(redrop_ok, redrop_blocked). entries 가 None 이면(목록 응답) 설정·계획 열만 본다."""
    if not rcfg(ctx)["enabled"]:
        return False, MSG_DISABLED
    p = plan_of(s)
    if p is None or p["redrop"] != "node_id":
        return False, MSG_UNSUPPORTED
    if entries is not None and not any(e["ok"] for e in entries):
        return False, MSG_NO_ENTRY
    return True, None


def entries(ctx: AppContext, conn, s: dict[str, Any]) -> list[dict[str, Any]]:
    """`redrop_entries`: `s["entry_ids"]` 순서 그대로. 판정은 DB 만(엔트리·Case·누적) — input_set 은 요청 때."""
    from .doe import _entry_label

    ok0, why0 = flags(ctx, s)
    base_eid = (s.get("base") or {}).get("entry_id")
    out = []
    for eid in s["entry_ids"]:
        e = lib_repo.get_entry(conn, eid)
        label, case_id, case_title, blocked = eid, None, None, None
        if e is None or e["project_id"] != s["project_id"]:
            blocked = R_NO_ENTRY
        else:
            label, case_id = _entry_label(e), e["case_id"]
            case = cases_repo.get_case(conn, case_id)
            if case is None or case["project_id"] != s["project_id"] or case.get("status") != "ACTIVE":
                blocked = R_NO_CASE
            else:
                case_title = case["title"]
                if (case.get("extract_summary") or {}).get("cumulative"):
                    blocked = R_CUMULATIVE
        if not ok0:
            blocked = why0
        out.append({"entry_id": eid, "label": label, "case_id": case_id, "case_title": case_title,
                    "is_base": eid == base_eid, "ok": blocked is None, "blocked": blocked})
    return out


# ---------------------------------------------------------------- 이름·정리
def slug(label: str, entry_id: str, max_chars: int) -> str:
    s = _SLUG_BAD.sub("_", unicodedata.normalize("NFC", label or "")).strip("_.")
    s = s[:max_chars].strip("_.")
    return s or str(entry_id)[:8]


def content_disposition(filename: str) -> str:
    from urllib.parse import quote

    ascii_name = re.sub(r"[^\x20-\x7e]", "_", filename).replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _root(ctx: AppContext) -> str:
    return esl_subdir(ctx.settings, REDROP_DIR)


def sweep(ctx: AppContext) -> None:
    """ttl 지난 `_redrop/<32-hex>` 잔여 폴더 정리(링크·hex 아닌 이름은 건드리지 않음). 실패는 무시."""
    try:
        root = _root(ctx)
        if os.path.islink(root) or not os.path.isdir(root):
            return
        ttl = float(rcfg(ctx)["tmp_ttl_s"])
        now = time.time()
        for name in os.listdir(root):
            if not TOKEN_RE.match(name):
                continue
            p = os.path.join(root, name)
            try:
                if os.path.islink(p) or not os.path.isdir(p):
                    continue
                if now - os.lstat(p).st_mtime > ttl:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                continue
    except (DomainError, OSError):
        return


def _rm(ctx: AppContext, token: str) -> None:
    """임시 폴더 삭제 — esl_subdir 로 다시 확인한 경로만, 링크는 따라가지 않음."""
    try:
        p = esl_subdir(ctx.settings, REDROP_DIR, token)
    except DomainError:
        return
    if os.path.islink(p):
        return
    shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------- 받기
def _json(path: str) -> Any:
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _core_error(exc: Exception) -> DomainError:
    code = getattr(exc, "code", "INPUT_INVALID")
    return DomainError(code, _mask(getattr(exc, "message", str(exc))), status=_CORE_STATUS.get(code, 422),
                       **(getattr(exc, "detail", None) or {}))


def _not_ready(message: str, did: str, dres: dict[str, Any]) -> DomainError:
    """409 REDROP_DESIGN_NOT_READY — detail 에 `status`(result.json 의 status)를 싣는다(DomainError.status 와 이름이 겹쳐 직접 넣음)."""
    exc = conflict("REDROP_DESIGN_NOT_READY", message, design_id=did)
    exc.extra["status"] = dres.get("status")
    return exc


@masks_paths
def bundle(ctx: AppContext, principal: Principal, sid: str, did: str, entry_id: str | None) -> dict[str, Any]:
    """검사 → 임시 폴더에 패치 → {files[(abs, rel)], prefix, filename, size, cleanup}. 오류면 임시 폴더를 지우고 DomainError."""
    from .doe import DID_RE, _entry_label, _result_doc, _viewable, cfg as doe_cfg, study_dir

    s, _job = _viewable(ctx, principal, sid)
    sweep(ctx)
    rc = rcfg(ctx)
    if not rc["enabled"]:
        raise DomainError("REDROP_DISABLED", MSG_DISABLED, status=503)
    if not DID_RE.match(did or ""):
        raise unprocessable("INVALID_PARAMS", "안 id 형식이 올바르지 않습니다")
    plan = plan_of(s)
    if plan is None or plan["redrop"] != "node_id":
        raise unprocessable("REDROP_UNSUPPORTED", MSG_UNSUPPORTED, plan=plan["id"] if plan else None)
    if entry_id is not None:
        try:
            entry_id = str(uuid.UUID(str(entry_id)))
        except ValueError:
            raise unprocessable("INVALID_PARAMS", "entry_id 형식이 올바르지 않습니다") from None
    else:
        entry_id = (s.get("base") or {}).get("entry_id")
        if not entry_id:
            raise unprocessable("INVALID_PARAMS", "기본 엔트리(스터디 기준)가 없어 entry_id 가 필요합니다")
    base = study_dir(ctx, s)
    ddir = os.path.join(base, "run", "designs", did)
    if os.path.islink(ddir) or not os.path.isdir(ddir):
        raise not_found("REDROP_DESIGN_NOT_FOUND", "그런 안이 없습니다")
    dres = _json(os.path.join(ddir, "result.json")) or {}
    dnpz = os.path.join(ddir, "design.npz")
    if os.path.islink(dnpz) or not os.path.isfile(dnpz):
        raise _not_ready("안의 좌표(design.npz)가 없습니다 — 평가 실패·미평가", did, dres)
    bnpz = os.path.join(base, "prep", "base_mesh.npz")
    if os.path.islink(bnpz) or not os.path.isfile(bnpz):
        raise _not_ready("스터디 기준 메시(prep/base_mesh.npz)가 없습니다", did, dres)
    if entry_id not in s["entry_ids"]:
        raise unprocessable("REDROP_ENTRY_NOT_IN_STUDY", "이 스터디의 엔트리가 아닙니다", entry_id=entry_id)
    with ctx.engine.connect() as conn:
        e = lib_repo.get_entry(conn, entry_id)
        if e is None or e["project_id"] != s["project_id"]:
            raise conflict("REDROP_ENTRY_NOT_READY", "엔트리를 찾을 수 없습니다", entry_id=entry_id)
        case = cases_repo.get_case(conn, e["case_id"])
    if case is None or case["project_id"] != s["project_id"] or case.get("status") != "ACTIVE" \
            or not os.path.isfile(str(case.get("rad_path") or "")):
        raise conflict("REDROP_CASE_NOT_READY", R_NO_CASE + " 또는 rad 파일이 없습니다", entry_id=entry_id,
                       case_id=e["case_id"])
    core = ctx.config.core or {}
    info = verify_drop.input_set(ctx.settings, core, case)
    if info["problems"]:
        raise unprocessable(info["problems"][0][0], _mask(info["problems"][0][1]),
                            problems=[{"code": c, "reason": _mask(r)} for c, r in info["problems"]])
    abs_files = [(p, rel) for rel, p in info["files"]]
    bundle_svc._check_size(ctx, abs_files, info["rad_dir"])

    token = uuid.uuid4().hex
    tmp = esl_subdir(ctx.settings, REDROP_DIR, token)
    os.makedirs(tmp)
    try:
        label = _entry_label(e)
        rdoc = _result_doc(ctx, s, doe_cfg(ctx)) or {}
        row = next((x for x in rdoc.get("ranking") or [] if isinstance(x, dict) and x.get("id") == did), None)
        sb = (s.get("inputs") or {}).get("select_base")
        from ... import __version__

        extra = {"platform_version": __version__,
                 "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "study": {"id": s["id"], "title": s["title"], "scenario": s["scenario"],
                           "select_base": sb, "plan": plan["id"]},
                 "design": {"id": did, "rank": int(row["rank"]) if row and row.get("rank") is not None else None,
                            "status": dres.get("status"), "values": dres.get("values") or {}},
                 "entry": {"id": entry_id, "label": label, "is_base": entry_id == (s.get("base") or {}).get("entry_id")},
                 "case": {"id": case["id"], "title": case["title"], "part_title": case.get("part_title"),
                          "rad_file_name": os.path.basename(case["rad_path"])}}
        kb = verify_drop.core_case_cfg(core)["rad_max_line_kb"]
        spec = {"base_npz": bnpz, "design_npz": dnpz, "files": info["files"], "out": os.path.join(tmp, "input"),
                "meta_out": tmp, "max_line": int(kb) * 1024 if kb else None,
                "base_coord_tol_mm": float(rc["base_coord_tol_mm"]), "manifest_extra": extra}
        try:
            m = verify_stages.rd_prepare(spec, echo=lambda *_a: None)
        except DomainError:
            raise
        except Exception as exc:        # EslError(코어) · 손상된 npz 등
            if hasattr(exc, "code"):
                raise _core_error(exc) from None
            raise unprocessable("INPUT_INVALID", _mask(f"재낙하 입력 만들기 실패: {exc}")) from None
        changed = set(m["changed"])
        files: list[tuple[str, str]] = []
        for rel, p in info["files"]:
            files.append((os.path.join(spec["out"], *rel.split("/")) if rel in changed else p, f"{verify_redrop.INPUT_DIR}/{rel}"))
        files.append((os.path.join(tmp, verify_redrop.README_NAME), verify_redrop.README_NAME))
        files.append((os.path.join(tmp, verify_redrop.MANIFEST_NAME), verify_redrop.MANIFEST_NAME))
        files.sort(key=lambda x: (x[1] not in (verify_redrop.README_NAME, verify_redrop.MANIFEST_NAME), x[1]))
        size = sum(os.path.getsize(p) for p, _ in files)
    except BaseException:
        _rm(ctx, token)
        raise
    prefix = f"redrop_{did}_{slug(label, entry_id, int(rc['name_max_chars']))}_{sid[:8]}"
    return {"files": files, "prefix": prefix, "filename": f"{prefix}.zip", "size": size,
            "cleanup": lambda: _rm(ctx, token)}


__all__ = ["bundle", "entries", "flags", "sweep", "slug", "content_disposition", "plan_of"]
