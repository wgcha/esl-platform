"""V-SR-9·10·14 검증 낙하 워커(계약 esl_scx_relay.md §9.2·§9.3·SR-D-11~16) — 가짜 릴레이 + 실제 PostgreSQL·워커·가짜 hw:
B 전체 흐름(계획 → 제출 → 폴링 → 회수 → 추출 → 비교 → 등록), 원본 불변(sha·mtime)·드라이브 쓰기 = 새 잡 폴더만, 제출 replay(어댑터
호출 1회), UNKNOWN → FAILED·재시도 409·[잡 ID 연결] → 폴링부터·[포기] → 새 attempt, SUBMITTING 잔존 → 같은 request_id 재전송,
취소 = SCX 잡 terminate 1회, SCX_JOB_LOST, Radioss 실패(마스킹), 대기열 CONFLICT, output_rel 없음, h3d 0개, out 판정, 대용량 거부,
입력 바뀜(INPUT_CHANGED), VERIFY_DROP 동시 수(max_running)."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import numpy as np
import pytest
from esl_test_support import API, H, create_case, wait_for
from h3d_support import write_fake_hw
from sqlalchemy import text
from verify_support import seed_case, seed_entry_for, seed_study, verify_settings

W = H("tok-power", True)
R = H("tok-power")
OK_OUT = b"RADIOSS ENGINE\n ** NORMAL TERMINATION\n"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")


@pytest.fixture()
def fake_relay(tmp_path):
    from scx_support import start_relay

    f = start_relay(tmp_path / "drive")
    f.outputs = {"model.h3d": b"HYPER3D verify result" + b"\x00" * 64, "model_0000.out": OK_OUT,
                 "model_0001.out": OK_OUT}
    try:
        yield f
    finally:
        f.stop()


@pytest.fixture()
def settings_dict(tmp_path, fake_relay):
    d = verify_settings(tmp_path, fake_relay)
    d["altair"] = {"hw_exe_path": str(write_fake_hw(tmp_path)), "max_concurrent_hw": 1}
    return d


@pytest.fixture(autouse=True)
def _scx_reset():
    from esl_platform.core.scx import gateway

    gateway.reset()
    yield
    gateway.reset()


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def job(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def drop(client, did):
    return client.get(f"{API}/verify-drops/{did}", headers=R).json()


def create(client, sid, **kw):
    r = client.post(f"{API}/verify-drops", json={"bead_doe_id": sid, "design_id": "d007", "mode": "all", **kw}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()["drops"]


def mini_world(engine, esl_root, inputs_root, n=1):
    cs = [seed_case(engine, esl_root, inputs_root, f"s{i}") for i in range(n)]
    ents = [seed_entry_for(engine, c["id"]) for c in cs]
    sid = seed_study(engine, esl_root, ents, ratios={e: 1.1 - 0.01 * i for i, e in enumerate(ents)})
    return cs, sid


def drive_files(relay) -> set[str]:
    return {str(p.relative_to(relay.drive)).replace(os.sep, "/") for p in relay.drive.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- 전체 흐름(실제 추출 Case)
def test_full_flow_plan_submit_poll_fetch_compare(client, engine, fake_relay, worker_factory, synth_inputs, esl_root,
                                                  monkeypatch):
    rad = Path(synth_inputs["rad"])
    (rad.parent / "model_0001.rad").write_bytes(b"/RUN/model/1\n0.001\n/END\n")
    r = create_case(client, synth_inputs, folder="vdreal", title="원 낙하")
    assert r.status_code == 201, r.text
    case = r.json()
    rj = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    w = worker_factory()
    assert w.run_once("SLOT") == "SUCCEEDED", job(client, rj["id"])
    z = np.load(esl_root / "vdreal" / "01_extract" / "model.npz")
    nid, x0 = z["node_id"], z["x0"]
    k = int(np.argmax(x0[:, 0] + x0[:, 1]))                     # 모핑으로 움직일 대상 파트 노드 1개
    moved = {int(nid[k]): (float(x0[k, 0]), float(x0[k, 1]), float(x0[k, 2]) + 1.5)}
    fd = int(np.load(esl_root / "vdreal" / "01_extract" / "strain_frames.npz")["frame_index"][-1])
    with engine.begin() as c:                                   # 원 Case 확정 t*(DB, 후보 프레임 D) — 비교 t* 행
        c.execute(text("UPDATE cases SET tstar = jsonb_build_object('frame_index', CAST(:f AS int), 'metric', "
                       "'max_strain', 'source', 'auto') WHERE id = :i"), {"i": case["id"], "f": fd})
    ent = seed_entry_for(engine, case["id"])
    sid = seed_study(engine, esl_root, [ent], ratios={ent: 0.85}, best_nodes=moved)
    before = {p: (_sha(p), os.stat(p).st_mtime_ns) for p in rad.parent.iterdir() if p.is_file()}
    best = esl_root / "_doe" / sid / "best"
    best_before = {p: _sha(p) for p in best.rglob("*") if p.is_file()}
    plan = client.post(f"{API}/verify-drops/plan", json={"bead_doe_id": sid, "design_id": "d007", "mode": "worst"},
                       headers=W).json()
    assert plan["designs"] == [{"id": "d007", "rank": 1}] and plan["default_n"] == 2
    assert plan["hpc_default"] == {"version": "2026.1", "ncpu": 16}
    [d] = create(client, sid, hpc={"ncpu": 4})
    did, jid = d["id"], d["job"]["id"]
    assert w.run_once("SLOT") is None and w.run_once("LIGHT") is None
    assert w.run_once("XFER") == "SUCCEEDED", job(client, jid)
    j = job(client, jid)
    assert [s["state"] for s in j["steps"]] == ["SUCCEEDED"] * 5 and j["progress_pct"] == 100.0
    dd = drop(client, did)
    assert dd["phase"] == "POST" and dd["scx_job_id"] and dd["submission"]["state"] == "SUBMITTED"
    assert dd["submission"]["request_id"] == f"esl-vd-{did}-a1"
    assert dd["drive_dir_display"].startswith("/Users/vd.dashboard/esl/p-1/VD1_")
    assert dd["files_n"] == 2 and dd["files_bytes"] > 0
    with engine.connect() as c:
        files = c.execute(text("SELECT files FROM verify_drops WHERE id=:i"), {"i": did}).scalar_one()
    assert {f["rel"]: f["source"] for f in files} == {"model_0000.rad": "patched", "model_0001.rad": "orig"}
    # 드라이브: 새 잡 폴더에만(패치한 starter·엔진 원본), 제출 본문(엔진·버전·ncpu·client_ref)
    ddir = dd["drive_dir_display"].replace("/Users/vd.dashboard/", "")
    assert {x for x in drive_files(fake_relay) if x.endswith(".rad")} == {f"{ddir}/model_0000.rad", f"{ddir}/model_0001.rad"}
    up = fake_relay.drive_file(f"{ddir}/model_0000.rad").read_bytes()
    assert up != rad.read_bytes() and hashlib.sha256(up).hexdigest() == files[0]["sha256"]
    assert fake_relay.drive_file(f"{ddir}/model_0001.rad").read_bytes() == (rad.parent / "model_0001.rad").read_bytes()
    [call] = fake_relay.adapter_calls
    assert call["input_path"] == f"{ddir}/model_0000.rad" and call["engine_paths"] == [f"{ddir}/model_0001.rad"]
    assert call["additional_paths"] == [] and call["resources"]["ncpu"] == 4 and call["version"] == "2026.1"
    assert call["client_ref"] == {"app": "esl", "verify_drop_id": did, "design_id": "d007", "case_id": case["id"]}
    assert all(h.get("x-scx-relay-client") == "esl" for h in fake_relay.headers_seen)
    # 원본 불변(Case 입력·DOE best), 결과 회수
    assert {p: (_sha(p), os.stat(p).st_mtime_ns) for p in rad.parent.iterdir() if p.is_file()} == before
    assert {p: _sha(p) for p in best.rglob("*") if p.is_file()} == best_before
    vdir = esl_root / "_verify" / did
    assert sorted(p.name for p in (vdir / "result").iterdir()) == ["model.h3d", "model_0000.out", "model_0001.out"]
    assert (vdir / "stage.json").is_file() and str(rad.parent) not in (vdir / "stage.json").read_text()
    # VERIFY_POST(SLOT): 가짜 hw(같은 CSV) → 추출 → 비교 → 등록
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    pj = drop(client, did)["job"]
    assert pj["job_type"] == "VERIFY_POST" and pj["lane"] == "SLOT" and pj["retry_of_job_id"] is None
    assert [s["step_key"] for s in pj["steps"]] == ["H3D_EXTRACT", "VD_EXTRACT", "VD_COMPARE", "VD_REGISTER"]
    assert w.run_once("SLOT") == "SUCCEEDED", job(client, pj["id"])
    dd = drop(client, did)
    assert dd["phase"] == "DONE" and dd["job_ids"] == [jid, pj["id"]]
    rows = {x["key"]: x for x in dd["result"]["rows"]}
    assert set(rows) == {"eps_peak", "eps_hot", "disp_peak", "eps_tstar", "disp_tstar"}
    assert rows["eps_peak"]["ratio"] == pytest.approx(1.0) and rows["eps_peak"]["verdict"] == "same"
    assert rows["eps_peak"]["predicted"] == pytest.approx(0.85 * 1.1) and rows["eps_peak"]["agree"] is False
    assert dd["result"]["tstar"]["orig_time"] is not None
    csv = client.get(f"{API}/verify-drops/{did}/compare.csv", headers=R)
    assert csv.status_code == 200 and csv.text.startswith("key,label,orig,verify,ratio,predicted,verdict,agree")
    assert client.get(f"{API}/verify-drops/{did}/files/model_0001.out", headers=R).content == OK_OUT
    assert client.get(f"{API}/verify-drops/{did}/files/..%2Fstage.json", headers=R).status_code == 404
    lg = client.get(f"{API}/jobs/{jid}/log", params={"step": 1}, headers=R).json()
    assert any("vd_patch" in ln for ln in lg["lines"]) and not any(str(esl_root) in ln for ln in lg["lines"])
    # Case 폴더 쓰기 없음(검증 산출물은 _verify 에만), artifacts 없음
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM artifacts WHERE job_id IN (:a, :b)"),
                         {"a": jid, "b": pj["id"]}).scalar_one() == 0


# ---------------------------------------------------------------- 제출 replay·UNKNOWN·연결·포기·SUBMITTING
def test_submit_replay_unknown_attach_and_abandon(client, engine, fake_relay, worker_factory, esl_root, inputs_root):
    from esl_fake_scx_relay import add_remote_job

    cs, sid = mini_world(engine, esl_root, inputs_root, n=2)
    d1, d2 = create(client, sid)
    w = worker_factory()
    # d1: 응답 없이 끊김 1회 → 같은 request_id replay, 어댑터 호출 1회
    fake_relay.drop_submit = 1
    assert w.run_once("XFER") == "SUCCEEDED", job(client, d1["job"]["id"])
    assert len(fake_relay.adapter_calls) == 1 and drop(client, d1["id"])["submission"]["state"] == "SUBMITTED"
    # d2: 결과 모름 → FAILED SCX_SUBMISSION_UNKNOWN, 재시도 409
    fake_relay.submit_mode = "unknown"
    assert w.run_once("XFER") == "FAILED"
    j2 = job(client, d2["job"]["id"])
    assert j2["failure_code"] == "SCX_SUBMISSION_UNKNOWN" and "[잡 ID 연결]" in j2["failure_message"]
    dd = drop(client, d2["id"])
    assert dd["phase"] == "FAILED" and dd["submission"]["state"] == "UNKNOWN"
    r = client.post(f"{API}/jobs/{j2['id']}/retry", headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SCX_SUBMISSION_UNKNOWN"
    # 잘못된 연결: 없는 잡 404, 이미 쓰인 잡 409, 버전 충돌 409
    used = drop(client, d1["id"])["scx_job_id"]
    rv = lambda **b: client.post(f"{API}/verify-drops/{d2['id']}/resolve", json={"version": dd["version"], **b}, headers=W)
    assert rv(action="link", scx_job_id="scx-nope").status_code == 404
    assert rv(action="attach", scx_job_id=used).json()["detail"]["code"] == "SCX_JOB_ID_IN_USE"
    assert client.post(f"{API}/verify-drops/{d2['id']}/resolve", json={"version": 1, "action": "abandon"},
                       headers=W).json()["detail"]["code"] == "VERSION_CONFLICT"
    # [잡 ID 연결](link) → 폴링부터 새 작업(VD_PREP~SUBMIT SKIPPED)
    ddir = dd["drive_dir_display"].replace("/Users/vd.dashboard/", "")
    remote = add_remote_job(fake_relay, ddir)
    r = rv(action="link", scx_job_id=remote)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["phase"] == "SUBMITTED" and out["scx_job_id"] == remote and out["submission"]["state"] == "ATTACHED"
    nj = out["job"]
    assert nj["retry_of_job_id"] == j2["id"] and nj["resume_from_step"] == 4
    assert rv(action="abandon").json()["detail"]["code"] in ("VERSION_CONFLICT", "VD_NOT_UNKNOWN")
    fake_relay.submit_mode = "ok"
    assert w.run_once("XFER") == "SUCCEEDED", job(client, nj["id"])
    assert [s["state"] for s in job(client, nj["id"])["steps"]] == ["SKIPPED"] * 3 + ["SUCCEEDED"] * 2
    assert len(fake_relay.adapter_calls) == 2 and drop(client, d2["id"])["phase"] == "POST"


def test_abandon_then_retry_new_attempt_and_submitting_resend(client, engine, fake_relay, worker_factory, esl_root,
                                                              inputs_root, monkeypatch):
    cs, sid = mini_world(engine, esl_root, inputs_root)
    [d] = create(client, sid)
    w = worker_factory()
    fake_relay.submit_mode = "unknown"
    assert w.run_once("XFER") == "FAILED"
    dd = drop(client, d["id"])
    r = client.post(f"{API}/verify-drops/{d['id']}/resolve", json={"version": dd["version"], "action": "abandon"},
                    headers=W)
    assert r.status_code == 200 and r.json()["submission"]["state"] == "ABANDONED" and r.json()["phase"] == "FAILED"
    assert fake_relay.resolves[-1] == {"request_id": f"esl-vd-{d['id']}-a1", "action": "abandon"}
    # 포기 뒤 재시도 = VD_SUBMIT 부터 새 attempt(새 request_id) — 그 전에 제출 직전 죽음(SUBMITTING 잔존) 흉내
    from esl_platform.core.scx import gateway

    real = gateway.radioss_request
    boom = {"n": 1}

    def flaky(body):
        if boom["n"]:
            boom["n"] -= 1
            raise RuntimeError("워커가 제출 직전에 죽음")
        return real(body)

    monkeypatch.setattr(gateway, "radioss_request", flaky)
    fake_relay.submit_mode = "ok"
    r = client.post(f"{API}/jobs/{d['job']['id']}/retry", headers=W)
    assert r.status_code == 201 and r.json()["resume_from_step"] == 3, r.text
    assert w.run_once("XFER") == "FAILED"
    with engine.connect() as c:
        subs = c.execute(text("SELECT request_id, state FROM scx_submissions WHERE verify_drop_id=:i ORDER BY attempt"),
                         {"i": d["id"]}).all()
    assert [tuple(x) for x in subs] == [(f"esl-vd-{d['id']}-a1", "ABANDONED"), (f"esl-vd-{d['id']}-a2", "SUBMITTING")]
    n_calls = len(fake_relay.adapter_calls)
    r = client.post(f"{API}/jobs/{r.json()['id']}/retry", headers=W)
    assert r.status_code == 201
    assert w.run_once("XFER") == "SUCCEEDED", job(client, r.json()["id"])
    with engine.connect() as c:
        subs = c.execute(text("SELECT request_id, state FROM scx_submissions WHERE verify_drop_id=:i ORDER BY attempt"),
                         {"i": d["id"]}).all()
    assert [tuple(x) for x in subs][-1] == (f"esl-vd-{d['id']}-a2", "SUBMITTED")     # 같은 request_id 재전송
    assert len(fake_relay.adapter_calls) == n_calls + 1


# ---------------------------------------------------------------- 취소(SCX 잡 terminate 1회)·대기 실패
def test_cancel_during_wait_terminates_once(client, engine, fake_relay, worker_factory, esl_root, inputs_root):
    cs, sid = mini_world(engine, esl_root, inputs_root)
    fake_relay.status_seq = ["Queued"] + ["Running"] * 100000
    [d] = create(client, sid)
    w = worker_factory()
    res = {}
    t = threading.Thread(target=lambda: res.update(st=w.run_once("XFER")), daemon=True)
    t.start()
    wait_for(lambda: drop(client, d["id"])["phase"] == "RUNNING", timeout=30)
    assert client.post(f"{API}/jobs/{d['job']['id']}/cancel", headers=W).status_code == 200
    t.join(30)
    assert res["st"] == "CANCELED"
    jid = drop(client, d["id"])["scx_job_id"]
    assert fake_relay.terminated == [jid]
    j = job(client, d["job"]["id"])
    assert j["result"]["scx_terminated"] == jid and "종료 요청" in j["failure_message"]
    assert drop(client, d["id"])["phase"] == "CANCELED"
    # 다시 재시도해도 같은 잡 ID 로 폴링(terminate 더 없음 — SCX 상태 Aborted → CANCELED)
    r = client.post(f"{API}/jobs/{d['job']['id']}/retry", headers=W)
    assert r.status_code == 201 and r.json()["resume_from_step"] == 4
    assert w.run_once("XFER") == "CANCELED" and fake_relay.terminated == [jid]


@pytest.mark.parametrize("setup, code", [
    ({"status_seq": ["Queued"] + ["__SCX_NOT_FOUND__"] * 10}, "SCX_JOB_LOST"),
    ({"status_seq": ["Queued", "Failed"]}, "SCX_RADIOSS_FAILED"),
    ({"batch_steps": ["CONFLICT"]}, "SCX_STAGE_CONFLICT"),
    ({"output_mode": "none"}, "SCX_OUTPUT_UNRESOLVED"),
    ({"outputs": {"model_0000.out": OK_OUT}}, "VD_RESULT_MISSING"),
    ({"outputs": {"model.h3d": b"H", "model_0000.out": b" ERROR TERMINATION\n", "model_0001.out": OK_OUT}},
     "VD_RADIOSS_ABNORMAL"),
    ({"outputs": {"model.h3d": b"H", "model_0000.out": b"no end\n"}}, "VD_RADIOSS_ABNORMAL"),
    ({"submit_mode": "fail:SCX_ADAPTER_ERROR"}, "SCX_SUBMIT_FAILED"),
])
def test_failures(client, engine, fake_relay, worker_factory, esl_root, inputs_root, setup, code):
    cs, sid = mini_world(engine, esl_root, inputs_root)
    for k, v in setup.items():
        setattr(fake_relay, k, v)
    [d] = create(client, sid)
    assert worker_factory().run_once("XFER") == "FAILED"
    j = job(client, d["job"]["id"])
    assert j["failure_code"] == code, j
    assert "Bearer abc" not in (j["failure_message"] or "") and str(esl_root) not in (j["failure_message"] or "")
    assert drop(client, d["id"])["phase"] == "FAILED"


def test_too_large_result_and_input_changed(client, engine, fake_relay, worker_factory, esl_root, inputs_root,
                                            settings_dict):
    cs, sid = mini_world(engine, esl_root, inputs_root, n=2)
    d1, d2 = create(client, sid)
    w = worker_factory()
    fake_relay.outputs = {"model.h3d": b"H" * 4096, "model_0000.out": OK_OUT}
    fake_relay.max_download_bytes = 1024                                    # 대시보드 상한 < h3d
    assert w.run_once("XFER") == "FAILED"
    j = job(client, d1["job"]["id"])
    assert j["failure_code"] == "SCX_FILE_TOO_LARGE" and "SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES" in j["failure_message"]
    # 원 Case 입력이 바뀜 → INPUT_CHANGED(재시도 409)
    rad = Path(cs[1]["rad"])
    rad.write_bytes(rad.read_bytes() + b"\n")
    assert w.run_once("XFER") == "FAILED"
    j2 = job(client, d2["job"]["id"])
    assert j2["failure_code"] == "INPUT_CHANGED"
    assert client.post(f"{API}/jobs/{j2['id']}/retry", headers=W).json()["detail"]["code"] == "INPUT_CHANGED"
    assert not (esl_root / "_verify" / d2["id"] / "stage").exists()


def test_max_running_claim(client, engine, fake_relay, worker_factory, esl_root, inputs_root, loaded_config):
    from esl_platform.core.repositories import jobs as jobs_repo

    cs, sid = mini_world(engine, esl_root, inputs_root, n=2)
    d1, d2 = create(client, sid)
    with engine.begin() as c:
        a = jobs_repo.claim_xfer(c, "w1", 30, lanes=4, verify_max_running=1)
        b = jobs_repo.claim_xfer(c, "w2", 30, lanes=4, verify_max_running=1)
    assert a["id"] == d1["job"]["id"] and b is None
    with engine.begin() as c:
        b = jobs_repo.claim_xfer(c, "w2", 30, lanes=4, verify_max_running=2)
    assert b["id"] == d2["job"]["id"] and a["holds_slot"] is False
