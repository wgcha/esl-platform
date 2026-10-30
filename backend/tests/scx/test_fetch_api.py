"""V-SR-5·V-SR-7 `POST /scx/fetches` + 업로드 서비스 연결(계약 esl_scx_relay.md SR-D-6·§7·§9.1): 업로드 행 + SCX_FETCH 작업 한
트랜잭션, 이름 규칙, 확장자, 없는 파일, 크기 상한(422), 여유 공간(507), 사용자당 동시 업로드(429), 권한(general·비멤버 403, PC 토큰
범위 밖), 진행 중 세션 잠금(파일 추가·complete·취소 409 UPLOAD_SCX_BUSY), stale 정리 제외(활성 작업), 남의 세션 404."""

from __future__ import annotations

import datetime as dt

import pytest
from esl_test_support import API, H
from scx_support import build_model
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")


def _code(r):
    return r.json()["detail"]["code"]


def fetch(client, model, name="SCX 모델", token="tok-power", **over):
    body = {"project_id": "p-1", "name": name, "root": "drop", "rad_rel": model["rad"], "h3d_rel": model["h3d"], **over}
    return client.post(f"{API}/scx/fetches", json=body, headers=H(token, True))


def _counts(client):
    with client.app.state.ctx.engine.connect() as conn:
        return (conn.execute(text("SELECT count(*) FROM uploads")).scalar_one(),
                conn.execute(text("SELECT count(*) FROM jobs")).scalar_one())


def test_fetch_creates_upload_and_job_together(client, fake_relay, settings_dict):
    model = build_model(fake_relay)
    r = fetch(client, model)
    assert r.status_code == 202, r.text
    uid, jid = r.json()["upload_id"], r.json()["job_id"]
    with client.app.state.ctx.engine.connect() as conn:
        row = conn.execute(text("SELECT u.state, u.files, u.dir_path, j.state, j.lane, j.upload_id, j.case_id, j.params "
                                "FROM uploads u JOIN jobs j ON j.upload_id = u.id WHERE u.id = :u"), {"u": uid}).one()
    assert row[0] == "OPEN" and row[1] == [] and row[3] == "QUEUED" and row[4] == "XFER" and row[5] == uid and row[6] is None
    assert "_SCX_모델" in row[2] and row[7]["rad_rel"] == "share/drop/A/model/ref_0000.rad" and "secret" not in str(row[7])
    j = client.get(f"{API}/jobs/{jid}", headers=R).json()
    assert j["upload_id"] == uid and j["params"]["root"] == "drop"
    # 남의 작업·세션: 비멤버는 작업 조회 403, 다른 사용자는 세션 404
    assert client.get(f"{API}/jobs/{jid}", headers=H("tok-nonmember")).status_code == 403
    assert client.get(f"{API}/uploads/{uid}", headers=H("tok-power2")).status_code == 404


def test_fetch_transaction_rollback_moves_folder(client, fake_relay, monkeypatch, settings_dict):
    from esl_platform.core.repositories import jobs as jobs_repo

    model = build_model(fake_relay)

    def boom(*a, **k):
        raise RuntimeError("시험: 작업 만들기 실패")

    monkeypatch.setattr(jobs_repo, "insert_job", boom)
    with pytest.raises(RuntimeError):
        fetch(client, model)
    assert _counts(client) == (0, 0)


@pytest.mark.parametrize("over, status, code", [
    ({"name": "../x"}, 422, "UPLOAD_NAME_INVALID"),
    ({"name": "CON"}, 422, "UPLOAD_NAME_INVALID"),
    ({"rad_rel": "A/res/ref.h3d"}, 422, "SCX_NOT_RAD"),
    ({"h3d_rel": "A/model/ref_0000.rad"}, 422, "SCX_NOT_H3D"),
    ({"rad_rel": "A/model/none_0000.rad"}, 404, "SCX_PATH_NOT_FOUND"),
    ({"rad_rel": "../other/x_0000.rad"}, 422, "SCX_PATH_NOT_ALLOWED"),
    ({"root": "p2only"}, 404, "SCX_ROOT_NOT_FOUND"),
])
def test_fetch_input_errors(client, fake_relay, over, status, code):
    model = build_model(fake_relay)
    r = fetch(client, model, **over)
    assert r.status_code == status and _code(r) == code, r.text
    assert _counts(client) == (0, 0)


def test_fetch_size_free_space_and_limit(client, fake_relay, monkeypatch):
    model = build_model(fake_relay)
    fake_relay.max_download_bytes = 1000                                 # 대시보드 상한 < h3d
    r = fetch(client, model)
    assert r.status_code == 422 and _code(r) == "SCX_FILE_TOO_LARGE" and r.json()["detail"]["limit"] == 1000
    fake_relay.max_download_bytes = 20 * 1024 ** 3
    from esl_platform.api.services import uploads as up_svc

    monkeypatch.setattr(up_svc, "disk_free", lambda root: 10)
    r = fetch(client, model)
    assert r.status_code == 507 and _code(r) == "INSUFFICIENT_STORAGE"
    monkeypatch.undo()
    for i in range(4):                                                   # max_concurrent_per_user = 4
        assert fetch(client, model, name=f"m{i}").status_code == 202
    r = fetch(client, model, name="m5")
    assert r.status_code == 429 and _code(r) == "UPLOAD_LIMIT"
    assert _counts(client) == (4, 4)


def test_fetch_permissions_and_disabled(client, fake_relay, settings_dict):
    model = build_model(fake_relay)
    assert fetch(client, model, token="tok-general").status_code == 403
    assert fetch(client, model, token="tok-nonmember").status_code == 403
    r = client.post(f"{API}/scx/fetches", json={"project_id": "p-1", "name": "x", "root": "drop", "rad_rel": model["rad"],
                                                "h3d_rel": model["h3d"]}, headers=H("tok-power"))   # CSRF 헤더 없음
    assert r.status_code == 403 and _code(r) == "CSRF_HEADER_REQUIRED"
    fake_relay.job_api = False                                           # A 는 job_api 와 무관
    assert fetch(client, model).status_code == 202
    fake_relay.stop()
    from esl_platform.core.scx import gateway

    gateway.reset()
    r = fetch(client, model, name="down")
    assert r.status_code == 503 and _code(r) == "SCX_UNAVAILABLE" and r.json()["detail"]["reason_code"] == "SCX_RELAY_UNREACHABLE"


def test_session_locked_while_fetching_and_stale_skip(client, fake_relay, app_ctx):
    model = build_model(fake_relay)
    j = fetch(client, model).json()
    uid = j["upload_id"]
    sp = [{"rel": "rad/extra.inc", "size": 2}]
    r = client.post(f"{API}/uploads/{uid}/files", json={"files": sp}, headers=W)
    assert r.status_code == 409 and _code(r) == "UPLOAD_SCX_BUSY"
    assert _code(client.post(f"{API}/uploads/{uid}/complete", headers=W)) == "UPLOAD_SCX_BUSY"
    assert _code(client.delete(f"{API}/uploads/{uid}", headers=W)) == "UPLOAD_SCX_BUSY"
    # stale 정리: 오래된 OPEN 세션이라도 비종료 SCX_FETCH 가 있으면 건너뜀
    from esl_platform.api.services import uploads as up_svc

    with app_ctx.engine.begin() as conn:
        conn.execute(text("UPDATE uploads SET updated_at = now() - interval '200 hours'"))
    assert up_svc.cleanup_stale(app_ctx) == []
    # 작업 취소(대기 중 → 즉시 CANCELED) → 이제 정리 대상
    assert client.post(f"{API}/jobs/{j['job_id']}/cancel", headers=W).json()["state"] == "CANCELED"
    assert up_svc.cleanup_stale(app_ctx, now=dt.datetime.now(dt.timezone.utc)) == [uid]


def test_pc_token_cannot_use_scx(client, fake_relay):
    r = client.get(f"{API}/scx/status", params={"project_id": "p-1"}, headers={"Authorization": "Bearer esl_ct_bogus"})
    assert r.status_code in (401, 403)
