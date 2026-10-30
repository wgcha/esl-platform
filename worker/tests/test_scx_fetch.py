"""V-SR-6·V-SR-13 SCX_FETCH 워커(계약 esl_scx_relay.md §9.1·SR-D-6·7·8·9) — 가짜 릴레이 + 실제 PostgreSQL·워커:
탐색 → 선택 → 내려받기 → Case 생성 전체 흐름, include 폐포(상대·`../`·하위 폴더·참조한 파일 폴더 기준·상태 파일·절대경로·루트 밖·
확장자 밖), 엔진 rad, 공통 조상 배치, 릴레이 다운·인증 실패·해시 불일치·중간 끊김·재시도(확인 파일 건너뜀)·취소, `.part` 링크 거부,
세션 폴더 밖 쓰기 0, XFER 레인(SLOT·LIGHT 와 독립 claim·holds_slot false·xfer_lanes 수·리퍼)."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import pytest
from esl_test_support import API, H, create_case, wait_for
from scx_support import ROOT_REL, H3D_BYTES, build_model, mini_rad, put, scx_settings, start_relay
from sqlalchemy import select, text

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def fake_relay(tmp_path):
    f = start_relay(tmp_path / "drive")
    try:
        yield f
    finally:
        f.stop()


@pytest.fixture()
def settings_dict(tmp_path, fake_relay):
    return scx_settings(tmp_path, fake_relay)


@pytest.fixture(autouse=True)
def _scx_reset():
    from esl_platform.core.scx import gateway

    gateway.reset()
    yield
    gateway.reset()


@pytest.fixture()
def upload_root(settings_dict) -> Path:
    return Path(settings_dict["storage"]["upload_root"])


def _code(r):
    return r.json()["detail"]["code"]


def fetch(client, model, name="SCX 모델", token="tok-power", **over):
    body = {"project_id": "p-1", "name": name, "root": "drop", "rad_rel": model["rad"], "h3d_rel": model["h3d"], **over}
    return client.post(f"{API}/scx/fetches", json=body, headers=H(token, True))


def job(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def upload(client, uid):
    return client.get(f"{API}/uploads/{uid}", headers=R).json()


def files_under(root: Path) -> set[str]:
    return {str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*") if p.is_file()}


def drive_writes(relay) -> int:
    return len([r for r in relay.requests if r["method"] == "POST"])


# ---------------------------------------------------------------- 전체 흐름(탐색 → 선택 → 내려받기 → Case)
def test_full_flow_browse_fetch_case(client, fake_relay, worker_factory, upload_root, esl_root, tmp_path):
    model = build_model(fake_relay)
    b = client.get(f"{API}/scx/browse", params={"project_id": "p-1", "root": "drop", "path": "A/model"}, headers=R).json()
    picked = next(e for e in b["entries"] if e["hint"] == "rad")
    assert picked["name"] == "ref_0000.rad"
    r = fetch(client, model)
    assert r.status_code == 202, r.text
    uid, jid = r.json()["upload_id"], r.json()["job_id"]
    j = job(client, jid)
    assert j["job_type"] == "SCX_FETCH" and j["lane"] == "XFER" and j["stage"] == 12 and j["upload_id"] == uid
    assert [s["step_key"] for s in j["steps"]] == ["SF_RAD", "SF_H3D", "SF_REGISTER"]
    up = upload(client, uid)
    assert up["state"] == "OPEN" and up["files"] == []
    before_esl = files_under(esl_root)
    w = worker_factory()
    assert w.run_once("SLOT") is None and w.run_once("LIGHT") is None      # XFER 작업은 다른 레인이 가져가지 않음
    assert w.run_once("XFER") == "SUCCEEDED"
    j = job(client, jid)
    assert j["state"] == "SUCCEEDED" and j["progress_pct"] == 100.0 and j["result"]["upload_ok"] is True
    up = upload(client, uid)
    assert up["state"] == "COMPLETED", up["result"]
    d = Path(up["dir_path"])
    got = {f["rel"]: f for f in up["files"]}
    assert set(got) == {"rad/model/ref_0000.rad", "rad/model/ref_0001.rad", "rad/model/sub/b.inc", "rad/inc/part.inc",
                        "rad/inc/deep.inc", "h3d/ref.h3d"}
    for rel, f in got.items():
        assert f["source"] == "scx" and f["done"] and f["received"] == f["size"]
        drive = f"{ROOT_REL}/{f['drive_rel']}"
        assert f["sha256"] == model["sha"][drive] == hashlib.sha256((d / rel).read_bytes()).hexdigest()
    assert got["rad/inc/part.inc"]["drive_rel"] == "A/inc/part.inc"
    assert up["client"] == {"name": "scx-relay", "version": "a363a89e8f93"}
    res = up["result"]
    assert res["ok"] and res["missing_includes"] == [] and res["rad_path"] == str(d / "rad" / "model" / "ref_0000.rad")
    assert res["h3d_path"] == str(d / "h3d" / "ref.h3d") and [p["title"] for p in res["parts"]] == ["Chassis rear"]
    assert res["scx"] == {"root": "drop", "rad_rel": "A/model/ref_0000.rad", "h3d_rel": "A/res/ref.h3d", "missing_specs": []}
    # 쓰기는 세션 폴더뿐(업로드 루트의 다른 곳·esl_root·드라이브 쓰기 0), .part 없음
    assert {p.relative_to(upload_root).parts[:2] for p in upload_root.rglob("*") if p.is_file()} == {("power", d.name)}
    assert files_under(esl_root) == before_esl and drive_writes(fake_relay) == 0
    assert not list(d.rglob("*.part"))
    assert (d / "_scx" / "fetch.json").is_file() and list((d / "_scx" / "logs" / jid).glob("step_*.log"))
    # 로그(서버 경로 가림 — 일반 사용자)
    lg = client.get(f"{API}/jobs/{jid}/log", params={"step": 1}, headers=R).json()
    assert any("include" in ln for ln in lg["lines"]) and not any(str(upload_root) in ln for ln in lg["lines"])
    # 기존 Case 생성 그대로(h3d 입력)
    r = create_case(client, {"rad": res["rad_path"], "csv": None}, folder="scxcase", results_dir=None,
                    h3d_path=res["h3d_path"], part_title="Chassis rear")
    assert r.status_code == 201, r.text
    assert r.json()["input_kind"] == "H3D"


# ---------------------------------------------------------------- include 폐포·누락 → 같은 세션에 추가
def test_include_closure_missing_then_add(client, fake_relay, worker_factory):
    model = build_model(fake_relay, engine=False, extra_includes=[
        "state.sta", "C:\\abs\\x.inc", "../../../../outside.inc", "gone.inc", "data.xyz", "../inc/../inc/part.inc"])
    put(fake_relay, f"{ROOT_REL}/A/model/state.sta", b"#RADIOSS STATE FILE\n/NODE\n")
    put(fake_relay, f"{ROOT_REL}/A/model/data.xyz", b"x")
    put(fake_relay, "outside.inc", b"# outside root\n")
    uid, jid = (lambda j: (j["upload_id"], j["job_id"]))(fetch(client, model).json())
    w = worker_factory()
    assert w.run_once("XFER") == "SUCCEEDED"
    j = job(client, jid)
    assert any("받지 못한 include" in x for x in j["warnings"]) and j["result"]["upload_ok"] is False
    up = upload(client, uid)
    assert up["state"] == "OPEN"
    rels = {f["rel"] for f in up["files"]}
    assert "rad/model/state.sta" in rels and "rad/model/ref_0001.rad" not in rels       # 상태 파일 받음, 엔진 없음
    assert not any("outside" in r or "xyz" in r or "gone" in r for r in rels)
    ms = {m["spec"]: m["reason"] for m in up["result"]["scx"]["missing_specs"]}
    assert "절대경로" in ms["C:\\abs\\x.inc"] and "루트 밖" in ms["../../../../outside.inc"]
    assert "드라이브에 없음" in ms["gone.inc"] and "확장자" in ms["data.xyz"]
    assert "rad/model/gone.inc" in up["result"]["missing_includes"]
    assert [s for s in up["result"]["state_includes"] if s["rel"] == "rad/model/state.sta"]
    assert "outside.inc" not in fake_relay.files_served                # 루트 밖은 요청조차 안 함
    # 업로드 서비스: scx 항목 PUT 거부, 누락 include·확장자 밖 include 를 브라우저로 같은 세션에 추가
    idx = next(f["index"] for f in up["files"] if f["source"] == "scx")
    r = client.put(f"{API}/uploads/{uid}/files/{idx}", params={"offset": 0}, content=b"x",
                   headers={**W, "Content-Type": "application/octet-stream"})
    assert r.status_code == 409 and _code(r) == "UPLOAD_SCX_MANAGED"
    add = {"rad/model/gone.inc": b"# gone\n"}
    r = client.post(f"{API}/uploads/{uid}/files", headers=W,
                    json={"files": [{"rel": k, "size": len(v), "sha256": hashlib.sha256(v).hexdigest()} for k, v in add.items()]})
    assert r.status_code == 200, r.text
    ni = r.json()["files"][-1]["index"]
    r = client.put(f"{API}/uploads/{uid}/files/{ni}", params={"offset": 0}, content=add["rad/model/gone.inc"],
                   headers={**W, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200 and r.json()["done"]
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert c["missing_includes"] == ["rad/model/data.xyz"] and c["scx"]["root"] == "drop"   # 출처 유지, 확장자 밖은 그대로 누락
    assert any("업로드에 포함되지 않은 include" in p for p in c["problems"])          # 절대·루트 밖은 그대로 문제


# ---------------------------------------------------------------- 오류·재시도
def test_relay_down_then_retry_with_mid_transfer_drop(client, fake_relay, worker_factory):
    model = build_model(fake_relay)
    r = fetch(client, model).json()
    uid, jid = r["upload_id"], r["job_id"]
    w = worker_factory()
    fake_relay.drop_all = True                                         # 대시보드가 응답 없이 끊음(다운)
    assert w.run_once("XFER") == "FAILED"
    j = job(client, jid)
    assert j["failure_code"] == "SCX_RELAY_UNREACHABLE" and "대시보드" in j["failure_message"]
    assert upload(client, uid)["state"] == "OPEN"
    fake_relay.drop_all = False
    fake_relay.drop_download = 1                                       # 첫 파일 중간 끊김(1회) → 파일 단위 재시도
    r2 = client.post(f"{API}/jobs/{jid}/retry", headers=W)
    assert r2.status_code == 201, r2.text
    assert r2.json()["upload_id"] == uid and r2.json()["retry_of_job_id"] == jid
    assert w.run_once("XFER") == "SUCCEEDED"
    assert upload(client, uid)["state"] == "COMPLETED"
    rad = f"{ROOT_REL}/{model['rad']}"
    assert fake_relay.files_served.count(rad) == 2                     # 끊긴 1회 + 다시 1회(.part 덮어 새로 받음)
    assert client.post(f"{API}/jobs/{jid}/retry", headers=W).status_code == 409


def test_hash_mismatch_retry_and_fail_then_resume_from_h3d(client, fake_relay, worker_factory, settings_dict):
    model = build_model(fake_relay)
    w = worker_factory()
    r = fetch(client, model).json()
    uid, jid = r["upload_id"], r["job_id"]
    n_rad = 5                                                          # rad·engine·include 3
    fake_relay.hash_mismatch = 1                                       # 첫 파일 1회 → 재시도로 성공
    # h3d 는 계속 틀림: rad 단계가 끝난 뒤 큰 수로

    class Arm(threading.Thread):
        def run(self):
            wait_for(lambda: len(fake_relay.files_served) >= n_rad + 1, timeout=30)
            fake_relay.hash_mismatch = 100

    Arm(daemon=True).start()
    assert w.run_once("XFER") == "FAILED"
    j = job(client, jid)
    assert j["failure_code"] == "SCX_HASH_MISMATCH", j
    steps = {s["step_key"]: s["state"] for s in j["steps"]}
    assert steps == {"SF_RAD": "SUCCEEDED", "SF_H3D": "FAILED", "SF_REGISTER": "SKIPPED"}
    up = upload(client, uid)
    assert up["state"] == "OPEN" and not any(f["rel"].startswith("h3d/") for f in up["files"])
    served_before = list(fake_relay.files_served)
    fake_relay.hash_mismatch = 0
    r2 = client.post(f"{API}/jobs/{jid}/retry", headers=W).json()
    assert r2["resume_from_step"] == 2 and [s["state"] for s in r2["steps"]] == ["SKIPPED", "PENDING", "PENDING"]
    assert w.run_once("XFER") == "SUCCEEDED"
    new = fake_relay.files_served[len(served_before):]
    assert new == [f"{ROOT_REL}/{model['h3d']}"]                        # 확인된 rad·include 는 다시 받지 않음
    assert upload(client, uid)["state"] == "COMPLETED"


def test_auth_failure_not_retried(client, fake_relay, worker_factory):
    model = build_model(fake_relay)
    jid = fetch(client, model).json()["job_id"]
    n0 = len(fake_relay.requests)
    fake_relay.secret = "Q" * 43                                       # 대시보드 비밀이 바뀜
    w = worker_factory()
    assert w.run_once("XFER") == "FAILED"
    j = job(client, jid)
    assert j["failure_code"] == "SCX_RELAY_UNAUTHORIZED" and "비밀" in j["failure_message"]
    assert len(fake_relay.requests) - n0 == 1                          # health 1회(재시도 없음)


def test_cancel_during_dashboard_staging(client, fake_relay, worker_factory):
    model = build_model(fake_relay, h3d=H3D_BYTES + b"x")
    r = fetch(client, model).json()
    uid, jid = r["upload_id"], r["job_id"]
    gate = threading.Event()
    fake_relay.download_gate = None
    w = worker_factory()
    out: dict = {}

    def arm():
        wait_for(lambda: len(fake_relay.files_served) >= 5, timeout=30)
        fake_relay.download_gate = gate                                # 다음(h3d) 요청: 첫 바이트 전 대기

    threading.Thread(target=arm, daemon=True).start()
    t = threading.Thread(target=lambda: out.setdefault("st", w.run_once("XFER")), daemon=True)
    t.start()

    def staging():
        j = job(client, jid)
        return j if "대시보드가 SCX에서 받는 중" in (j.get("progress_label") or "") and j["current_step_no"] == 2 else None

    j = wait_for(staging, timeout=30)
    assert j["state"] == "RUNNING"
    assert client.post(f"{API}/jobs/{jid}/cancel", headers=W).status_code == 200
    t.join(20)
    gate.set()
    assert out.get("st") == "CANCELED"
    up = upload(client, uid)
    assert up["state"] == "OPEN" and not any(f["rel"].startswith("h3d/") for f in up["files"])
    # 진행 중에는 세션 취소·파일 추가가 막혔고, 끝난 뒤(취소)에는 기존 [취소]로 정리 가능
    assert client.delete(f"{API}/uploads/{uid}", headers=W).status_code == 200


def test_part_symlink_rejected(client, fake_relay, worker_factory, tmp_path):
    model = build_model(fake_relay)
    r = fetch(client, model).json()
    uid, jid = r["upload_id"], r["job_id"]
    d = Path(upload(client, uid)["dir_path"])
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"keep")
    (d / "h3d").mkdir(parents=True, exist_ok=True)
    os.symlink(victim, d / "h3d" / "ref.h3d.part")
    w = worker_factory()
    assert w.run_once("XFER") == "FAILED"
    assert job(client, jid)["failure_code"] == "PATH_UNSAFE"
    assert victim.read_bytes() == b"keep"


def test_scope_rechecked_at_worker_start(client, fake_relay, worker_factory, loaded_config):
    model = build_model(fake_relay)
    jid = fetch(client, model).json()["job_id"]
    s = loaded_config.settings
    roots = s.scx_drive.roots
    object.__setattr__(s.scx_drive, "roots", [x for x in roots if x.key != "drop"])
    try:
        w = worker_factory()
        assert w.run_once("XFER") == "FAILED"
    finally:
        object.__setattr__(s.scx_drive, "roots", roots)
    j = job(client, jid)
    assert j["failure_code"] in ("SCX_PATH_NOT_ALLOWED", "SCX_NO_ROOTS")


def test_spdm_root_and_prefix_rejected(client, fake_relay, worker_factory, loaded_config, upload_root):
    """SPDM 마스터 루트(health forbidden_prefixes, 대소문자 무시) 안이거나 그 상위인 루트는 요청 단계에서 422, 아무것도 만들지 않음."""
    model = build_model(fake_relay)
    put(fake_relay, "spdm/proj/ref_0000.rad", mini_rad())
    put(fake_relay, "spdm/proj/ref.h3d", H3D_BYTES)
    s = loaded_config.settings
    roots = s.scx_drive.roots
    from esl_platform.core.config import ScxDriveRootCfg

    object.__setattr__(s.scx_drive, "roots", [*roots, ScxDriveRootCfg(key="spdm", label="SPDM", rel="spdm/proj")])
    try:
        r = fetch(client, {"rad": "ref_0000.rad", "h3d": "ref.h3d"}, root="spdm")
        assert r.status_code == 422 and _code(r) == "SCX_PATH_NOT_ALLOWED" and "SPDM" in r.json()["detail"]["message"]
        fake_relay.forbidden_prefixes = ["SPDM", f"{ROOT_REL}/A"]        # 프로젝트 폴더(share)가 금지 접두의 상위
        r = fetch(client, model)
        assert r.status_code == 422 and _code(r) == "SCX_PATH_NOT_ALLOWED"
    finally:
        object.__setattr__(s.scx_drive, "roots", roots)
    assert not upload_root.exists() or not any(upload_root.rglob("*_0000.rad"))
    with client.app.state.ctx.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM uploads")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
    assert "spdm/proj/ref_0000.rad" not in fake_relay.files_served and drive_writes(fake_relay) == 0


# ---------------------------------------------------------------- XFER 레인(V-SR-13)
def test_xfer_lane_claim_independent(client, fake_relay, worker_factory, engine, settings_dict):
    from esl_platform.core.db.tables import jobs, worker_slot
    from esl_platform.core.repositories import jobs as jobs_repo

    model = build_model(fake_relay)
    ids = [fetch(client, model, name=f"m{i}").json()["job_id"] for i in range(3)]
    with engine.begin() as conn:
        a = jobs_repo.claim_xfer(conn, "w-1", 30, 2)
        b = jobs_repo.claim_xfer(conn, "w-1", 30, 2)
        c = jobs_repo.claim_xfer(conn, "w-1", 30, 2)                  # xfer_lanes 2 → 셋째 없음
        assert jobs_repo.claim_slot(conn, "w-1", 30, 2) is None and jobs_repo.claim_light(conn, "w-1", 30) is None
    assert a["id"] == ids[0] and b["id"] == ids[1] and c is None
    assert a["holds_slot"] is False and a["lane"] == "XFER"
    with engine.connect() as conn:
        assert conn.execute(select(worker_slot.c.id).where(worker_slot.c.lease_token.isnot(None))).first() is None
    with engine.begin() as conn:                                       # lease 만료 → 리퍼 INTERRUPTED
        conn.execute(text("UPDATE jobs SET lease_expires_at = now() - interval '1 second', "
                          "lease_acquired_at = now() - interval '2 second' WHERE id = :i"), {"i": a["id"]})
        assert jobs_repo.reap_expired(conn) == [a["id"]]
        st = conn.execute(select(jobs.c.state).where(jobs.c.id == a["id"])).scalar_one()
    assert st == "INTERRUPTED"
    with engine.begin() as conn:
        assert jobs_repo.claim_xfer(conn, "w-1", 30, 2)["id"] == ids[2]


def test_worker_starts_xfer_loops(worker_factory, settings_dict, fake_relay):
    w = worker_factory()
    w.heartbeat_once()
    from esl_platform.core.repositories import workers as workers_repo

    with w.engine.connect() as conn:
        rows = conn.execute(text("SELECT info FROM worker_heartbeats")).all()
    info = rows[-1][0]
    assert info["xfer_lanes"] == 2 and info["scx"]["ok"] is True and info["scx"]["commit"] == "a363a89e8f93"
    del workers_repo


def test_mini_rad_helpers_sane():
    assert b"#include a.inc" in mini_rad(["a.inc"]) and H3D_BYTES.startswith(b"HYPER3D")
    assert time.time() > 0


def test_include_name_case_insensitive_on_drive(client, fake_relay, worker_factory):
    """SCX 드라이브는 대소문자 구분 없음: include 원문 'sub/B.INC' → 드라이브 sub/b.inc 를 실제 이름으로 요청, 원문 이름으로 배치."""
    model = build_model(fake_relay, extra_includes=["sub/B2.INC"])
    put(fake_relay, f"{ROOT_REL}/A/model/sub/b2.inc", b"# b2\n")
    uid = fetch(client, model).json()["upload_id"]
    w = worker_factory()
    assert w.run_once("XFER") == "SUCCEEDED"
    up = upload(client, uid)
    assert up["state"] == "COMPLETED", up["result"]
    f = next(x for x in up["files"] if x["rel"] == "rad/model/sub/B2.INC")
    assert f["source"] == "scx" and f"{ROOT_REL}/A/model/sub/b2.inc" in fake_relay.files_served
