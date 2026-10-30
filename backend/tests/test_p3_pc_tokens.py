"""P3-UX §9.3(백엔드): PC 연결 코드·토큰 — 발급·교환·만료·1회용·잠금·폐기·범위(다른 API 403)·다른 프로젝트 업로드 거부·
토큰 해시 저장, Bearer 업로드(CSRF 면제, 소유자 = 토큰 사용자). §6: 업로드 complete 의 h3d_path 로 Case 생성, 입력 택일.
마이그레이션 0006(이전 DB 에 적용)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from esl_test_support import API, REPO, H, make_settings_dict
from h3d_support import H3D_BYTES, write_fake_hw
from sqlalchemy import text
from test_p3_ux import mini_rad_text, send_all, spec

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path)
    d["storage"]["upload_root"] = str(tmp_path / "esl-input")
    d["upload"] = {"chunk_mb": 1, "max_file_bytes": 3_000_000, "max_upload_bytes": 5_000_000, "min_free_gb": 0}
    d["altair"] = {"hw_exe_path": str(write_fake_hw(tmp_path))}
    # 시험 클라이언트 peer 이름 "testclient" 를 신뢰 프록시로 → X-Forwarded-For 로 출발지 구분(출발지별 3회),
    # XFF 가 없으면 구분 불가 → 서버 전체(5회)
    d["client_token"] = {"lock_per_source": 3, "lock_global": 5, "lock_minutes": 15, "trusted_proxies": ["testclient"]}
    return d


def _code(r):
    return r.json()["detail"]["code"]


def _new_code(client, project="p-1", token="tok-power"):
    r = client.post(f"{API}/client-tokens/codes", json={"project_id": project}, headers=H(token, True))
    assert r.status_code == 201, r.text
    return r.json()


def _exchange(client, code, device="PC-1", **hdr):
    return client.post(f"{API}/client-tokens/exchange", json={"code": code, "device_name": device}, headers=hdr)


def _bearer(tok, csrf=False):
    h = {"Authorization": f"Bearer {tok}"}
    if csrf:
        h["X-ESL-Request"] = "1"
    return h


def test_code_exchange_and_bearer_upload(client, engine):
    c = _new_code(client)
    assert re.fullmatch(r"\d{6}", c["code"]) and c["project_id"] == "p-1"
    r = _exchange(client, c["code"])
    assert r.status_code == 200, r.text
    ex = r.json()
    tok = ex["token"]
    assert tok.startswith("esl_ct_") and len(tok) > 30
    assert ex["user"]["user_id"] == "u-power" and ex["project"] == {"id": "p-1", "name": "포장 낙하"}
    # 해시만 저장(원문·코드 원문 없음)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM client_tokens")).mappings().one()
        codes = conn.execute(text("SELECT code_hash, used_at FROM client_codes")).all()
    assert row["token_hash"] == hashlib.sha256(tok.encode()).hexdigest() and tok not in str(dict(row))
    assert codes[0][0] == hashlib.sha256(c["code"].encode()).hexdigest() and codes[0][1] is not None
    # 1회용
    assert _code(_exchange(client, c["code"])) == "CLIENT_CODE_INVALID"
    # /version 허용, 업로드는 CSRF 헤더 없이(Bearer) — 소유자 = 토큰 사용자
    assert client.get(f"{API}/version", headers=_bearer(tok)).status_code == 200
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/run.h3d": H3D_BYTES}
    up = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "PC 업로드", "files": spec(files)},
                     headers=_bearer(tok))
    assert up.status_code == 201, up.text
    up = up.json()
    assert "/power/" in up["dir_path"].replace("\\", "/")
    for f in up["files"]:
        data = files[f["rel"]]
        h = {**_bearer(tok), "Content-Type": "application/octet-stream",
             "X-Chunk-Sha256": hashlib.sha256(data).hexdigest()}
        rr = client.put(f"{API}/uploads/{up['upload_id']}/files/{f['index']}", params={"offset": 0}, content=data,
                        headers=h)
        assert rr.status_code == 200 and rr.json()["done"], rr.text
    comp = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=_bearer(tok))
    assert comp.status_code == 200 and comp.json()["ok"], comp.text
    assert comp.json()["h3d_path"].endswith("run.h3d")
    # 같은 사용자의 브라우저 세션에서도 보임(소유자 같음)
    assert client.get(f"{API}/uploads/{up['upload_id']}", headers=R).status_code == 200
    with engine.connect() as conn:
        assert conn.execute(text("SELECT user_id FROM uploads")).scalar_one() == "u-power"
        assert conn.execute(text("SELECT last_used_at FROM client_tokens")).scalar_one() is not None


def test_token_scope_and_project(client):
    tok = _exchange(client, _new_code(client)["code"]).json()["token"]
    for method, url in (("GET", "/me"), ("GET", "/cases"), ("GET", "/projects"), ("GET", "/client-tokens"),
                        ("POST", "/client-tokens/codes"), ("GET", "/queue"), ("GET", "/changelog")):
        r = client.request(method, API + url, headers=_bearer(tok, True), json={"project_id": "p-1"})
        assert r.status_code == 403 and _code(r) == "CLIENT_TOKEN_SCOPE", (url, r.text)
    files = {"rad/m_0000.rad": mini_rad_text()}
    r = client.post(f"{API}/uploads", json={"project_id": "p-2", "name": "x", "files": spec(files)}, headers=_bearer(tok))
    assert r.status_code == 403
    # 브라우저(세션)로 만든 다른 프로젝트 업로드는 토큰으로 안 보임
    sess = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "s", "files": spec(files)}, headers=W).json()
    assert client.get(f"{API}/uploads/{sess['upload_id']}", headers=_bearer(tok)).status_code == 200
    bad = client.get(f"{API}/uploads/{sess['upload_id']}", headers=_bearer("esl_ct_" + "x" * 40))
    assert bad.status_code == 401 and _code(bad) == "CLIENT_TOKEN_INVALID"


def test_general_cannot_create_code_and_project_check(client):
    r = client.post(f"{API}/client-tokens/codes", json={"project_id": "p-1"}, headers=H("tok-general", True))
    assert r.status_code == 403
    r = client.post(f"{API}/client-tokens/codes", json={"project_id": "nope"}, headers=W)
    assert r.status_code == 404 and _code(r) == "PROJECT_NOT_FOUND"
    r = client.post(f"{API}/client-tokens/codes", json={"project_id": "p-1"}, headers=R)     # CSRF 헤더 없음
    assert r.status_code == 403 and _code(r) == "CSRF_HEADER_REQUIRED"


def test_code_expiry_lock_and_revoke(client, engine):
    A = {"X-Forwarded-For": "10.9.9.9"}
    c = _new_code(client)
    with engine.begin() as conn:
        conn.execute(text("UPDATE client_codes SET created_at = now() - interval '20 minutes', "
                          "expires_at = now() - interval '5 minutes'"))
    r = _exchange(client, c["code"], **A)
    assert _code(r) == "CLIENT_CODE_INVALID" and r.json()["detail"].get("remaining") == 2   # 만료(실패 1)
    assert _code(_exchange(client, "12", **A)) == "CLIENT_CODE_INVALID"                     # 형식 오류(실패 2)
    r = _exchange(client, "000000" if c["code"] != "000000" else "111111", **A)              # 실패 3 → 잠금
    assert r.status_code == 429 and _code(r) == "CLIENT_CODE_LOCKED"
    good = _new_code(client)
    r = _exchange(client, good["code"], **A)
    assert r.status_code == 429                                                  # 잠긴 동안 맞는 코드도 거부
    # 다른 출발지(신뢰 프록시가 붙인 X-Forwarded-For)는 별개 — 오른쪽(프록시가 붙인 값)을 쓴다(왼쪽은 위조 가능)
    r = _exchange(client, good["code"], **{"X-Forwarded-For": "10.9.9.9, 10.1.2.3"})
    assert r.status_code == 200, r.text
    tok = r.json()
    with engine.connect() as conn:
        srcs = {r[0] for r in conn.execute(text("SELECT source FROM client_code_failures"))}
    assert srcs == {"10.9.9.9"}                                                  # 구분 가능 → 전체 키 안 씀
    lst = client.get(f"{API}/client-tokens", headers=R).json()
    assert [t["id"] for t in lst] == [tok["token_id"]] and lst[0]["state"] == "ACTIVE"
    assert lst[0]["device_name"] == "PC-1" and "token" not in lst[0]
    # 다른 사용자는 폐기 못 함(404), 본인 폐기 → 이후 401
    assert client.delete(f"{API}/client-tokens/{tok['token_id']}", headers=H("tok-power2", True)).status_code == 404
    r = client.delete(f"{API}/client-tokens/{tok['token_id']}", headers=W)
    assert r.status_code == 200 and r.json()["state"] == "REVOKED"
    r = client.get(f"{API}/version", headers=_bearer(tok["token"]))
    assert r.status_code == 401 and _code(r) == "CLIENT_TOKEN_INVALID"
    # 만료 토큰도 401
    tok2 = _exchange(client, _new_code(client)["code"], **{"X-Forwarded-For": "10.1.2.3"}).json()
    with engine.begin() as conn:
        conn.execute(text("UPDATE client_tokens SET created_at = now() - interval '40 days', "
                          "expires_at = now() - interval '1 day' WHERE id = :i"), {"i": tok2["token_id"]})
    assert client.get(f"{API}/version", headers=_bearer(tok2["token"])).status_code == 401
    assert {t["state"] for t in client.get(f"{API}/client-tokens", headers=R).json()} == {"REVOKED", "EXPIRED"}


def test_lock_global_when_source_unknown(client, app_ctx, engine):
    """계약 §10: 출발지를 구분할 수 없으면(신뢰하지 않는 루프백 프록시 뒤 — XFF 는 위조 가능해 무시) 서버 전체 키로 센다."""
    object.__setattr__(app_ctx.settings.client_token, "trusted_proxies", [])
    for i in range(4):                                                         # 실패 1..4: XFF 를 바꿔도 같은 키
        r = _exchange(client, "000000", **{"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 401 and r.json()["detail"]["remaining"] == 4 - i, r.text
    r = _exchange(client, "000000")                                             # 실패 5 → 서버 전체 잠금
    assert r.status_code == 429 and "서버 전체" in r.json()["detail"]["message"]
    good = _new_code(client)
    assert _exchange(client, good["code"], **{"X-Forwarded-For": "10.7.7.7"}).status_code == 429
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT source, failures FROM client_code_failures")).all()
    assert rows == [("*global*", 5)]
    # 신뢰 프록시를 다시 켜면 출발지별(전체 잠금과 별개)
    object.__setattr__(app_ctx.settings.client_token, "trusted_proxies", ["testclient"])
    assert _exchange(client, good["code"], **{"X-Forwarded-For": "10.7.7.7"}).status_code == 200


def test_request_source_rules():
    from esl_platform.api.services.client_tokens import request_source as rs

    trusted = ["127.0.0.1", "::1", "10.20.0.0/16"]
    assert rs("192.168.1.5", "1.2.3.4", []) == "192.168.1.5"                   # 비루프백 peer = 출발지(XFF 무시)
    assert rs("192.168.1.5", "1.2.3.4", trusted) == "192.168.1.5"
    assert rs("127.0.0.1", "1.2.3.4", []) is None                              # 신뢰 안 하는 루프백 → 구분 불가
    assert rs("127.0.0.1", None, trusted) is None                              # 신뢰 프록시인데 XFF 없음
    assert rs("127.0.0.1", "6.6.6.6, 192.168.1.5", trusted) == "192.168.1.5"     # 프록시가 붙인 오른쪽 값
    assert rs("127.0.0.1", "192.168.1.5, 10.20.3.4", trusted) == "192.168.1.5"   # 신뢰 프록시 홉은 건너뜀
    assert rs("::1", "10.20.0.9, 127.0.0.1", trusted) is None                  # 모두 신뢰 프록시
    assert rs(None, "1.2.3.4", trusted) is None


def test_client_token_config_keys():
    from esl_platform.core.config import ClientTokenCfg

    d = ClientTokenCfg()
    assert (d.lock_per_source, d.lock_global, d.lock_minutes, d.trusted_proxies) == (5, 30, 15, [])
    old = ClientTokenCfg.model_validate({"max_failures": 4, "lock_min": 10})          # 이전 키 호환
    assert (old.lock_per_source, old.lock_minutes) == (4, 10)
    with pytest.raises(Exception):
        ClientTokenCfg.model_validate({"trusted_proxies": ["10.0.0.0/33"]})


# ---------------------------------------------------------------- §6: h3d 입력 Case
def test_case_from_upload_h3d(client, esl_root):
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/run.h3d": H3D_BYTES}
    up = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "h3d", "files": spec(files)}, headers=W)
    up = up.json()
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert c["ok"] and c["h3d_path"] and c["results_dir"] is None
    base = {"project_id": "p-1", "folder_name": "h3dcase", "title": "h3d", "rad_path": c["rad_path"]}
    r = client.post(f"{API}/cases", json={**base, "h3d_path": c["h3d_path"], "results_dir": "/x"}, headers=W)
    assert r.status_code == 422                                                   # 택일
    assert client.post(f"{API}/cases", json=base, headers=W).status_code == 422
    r = client.post(f"{API}/cases", json={**base, "h3d_path": c["rad_path"]}, headers=W)
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE"                      # .h3d 아님
    r = client.post(f"{API}/cases", json={**base, "h3d_path": c["h3d_path"]}, headers=W)
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["input_kind"] == "H3D" and case["h3d_path"] == c["h3d_path"]
    assert Path(case["results_dir"]) == Path(esl_root) / "_h3d" / "h3dcase" / "raw"
    ins = client.post(f"{API}/paths/inspect", json={"purpose": "H3D", "path": c["h3d_path"]}, headers=W).json()
    assert ins["ok"] and ins["size"] == len(H3D_BYTES)


def test_case_h3d_bad_header_and_disabled(client, app_ctx, inputs_root):
    from test_p3_ux import mini_rad_text as rad_text

    rad = inputs_root / "m" / "m_0000.rad"
    rad.parent.mkdir()
    rad.write_bytes(rad_text())
    bad = inputs_root / "m" / "bad.h3d"
    bad.write_bytes(b"not an h3d")
    body = {"project_id": "p-1", "folder_name": "bad", "title": "bad", "rad_path": str(rad), "h3d_path": str(bad)}
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 422 and _code(r) == "INPUT_INVALID"
    object.__setattr__(app_ctx.settings.altair, "hw_exe_path", None)
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 503 and _code(r) == "H3D_EXTRACT_UNAVAILABLE"


def test_migration_0006_on_pre_0006_db(engine, db_url):
    from alembic import command
    from alembic.config import Config

    with engine.begin() as c:
        for t in ("client_codes", "client_tokens", "client_code_failures"):
            c.execute(text(f"DROP TABLE {t}"))
        c.execute(text("ALTER TABLE cases DROP CONSTRAINT ck_cases_input_kind"))
        c.execute(text("ALTER TABLE cases DROP COLUMN input_kind"))
        c.execute(text("ALTER TABLE job_steps DROP COLUMN command"))
        c.execute(text("ALTER TABLE job_steps DROP CONSTRAINT ck_job_steps_kind"))
        c.execute(text("ALTER TABLE job_steps ADD CONSTRAINT ck_job_steps_kind CHECK (kind IN ('INTERNAL'))"))
        c.execute(text("DELETE FROM worker_slot WHERE id > 1"))
        c.execute(text("ALTER TABLE worker_slot DROP CONSTRAINT ck_worker_slot_range"))
        c.execute(text("ALTER TABLE worker_slot ADD CONSTRAINT ck_worker_slot_single CHECK (id = 1)"))
        c.execute(text("UPDATE alembic_version SET version_num = '0005'"))
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM worker_slot")).scalar_one() == 16
        cons = {r[0] for r in c.execute(text("SELECT conname FROM pg_constraint"))}
        tabs = {r[0] for r in c.execute(text("SELECT tablename FROM pg_tables"))}
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012"
    assert {"ck_worker_slot_range", "ck_cases_input_kind"} <= cons and "ck_worker_slot_single" not in cons
    assert {"client_codes", "client_tokens", "client_code_failures"} <= tabs
