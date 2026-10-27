"""P3-UX §6: 서버 h3d 추출(H3D_EXTRACT, 가짜 hw 로 E2E)·워커 동시 실행(worker.slots, altair.max_concurrent_hw).

- h3d 입력 Case → CASE_EXTRACT 첫 step H3D_EXTRACT(LOCAL) → pack(EXTRACT) → TSTAR_SCAN → 등록. argv 템플릿(argv[0]=hw,
  공백 경로 허용, shell 없음), 출력 <esl_root>/_h3d/<폴더>/raw, done.json 실패 → H3D_EXTRACT_FAILED(errorInfo 는 step 로그).
- 취소 → hw 프로세스 트리(손자 포함) 종료, CANCELED.
- 결과 폴더 입력이면 H3D_EXTRACT step 없음(기존 step 번호 그대로).
- SLOT 2개 동시 claim(다른 Case), 같은 Case 직렬, hw 세마포어(DB) 한도·해제, 작업별 자원 분배.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
import synth_case
from esl_test_support import API, H, create_case, make_settings_dict, wait_for
from h3d_support import alive, write_fake_hw, write_h3d

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")


@pytest.fixture()
def fake_hw(tmp_path) -> Path:
    return write_fake_hw(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, fake_hw):
    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(fake_hw), "max_concurrent_hw": 1}
    d["worker"]["slots"] = 2
    return d


def _h3d_case(client, synth, folder="case01", title="h3d Case", **extra):
    h3d = write_h3d(Path(synth["rad"]).parent / f"{folder}_drop.h3d")
    body = {"project_id": "p-1", "folder_name": folder, "title": title, "rad_path": synth["rad"],
            "h3d_path": str(h3d), **extra}
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _job(client, cid, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def test_h3d_extract_e2e(client, synth_inputs, worker_factory, esl_root, monkeypatch, engine):
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    case = _h3d_case(client, synth_inputs)
    raw = os.path.join(str(esl_root), "_h3d", "case01", "raw")
    assert case["input_kind"] == "H3D" and case["results_dir"] == raw and case["h3d_path"].endswith(".h3d")
    assert case["input_fingerprint"]["h3d"]["path"] == case["h3d_path"] and case["input_fingerprint"]["results"] is None
    job = _job(client, case["id"], {"hot_k": 150, "top_n": 4})
    assert [s["step_key"] for s in job["steps"]] == ["H3D_EXTRACT", "EXTRACT", "TSTAR_SCAN", "EXTRACT_REGISTER"]
    assert job["steps"][0]["kind"] == "LOCAL" and "command" not in job["steps"][0]
    assert job["params"]["h3d"] == {"h3d_path": case["h3d_path"], "out_dir": raw, "part": "chassis rear",
                                    "hot_k": 150, "top_n": 4}
    st = worker_factory().run_once("SLOT")
    j = _get(client, job["id"])
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", j
    assert [s["state"] for s in j["steps"]] == ["SUCCEEDED"] * 4
    assert j["result"]["h3d_extract"]["ok"] is True and j["result"]["h3d_extract"]["hot_k"] == 150
    # argv: argv[0] = 공백 있는 hw 경로, TCL = 코드 스냅샷 resources/tcl, 출력·request·part·옵션
    argv_files = list(Path(raw).parent.glob("argv_*.json"))
    rec = json.loads(argv_files[0].read_text())
    argv = rec["argv"]
    assert " " in argv[0] and argv[0].endswith("/hw")
    assert argv[argv.index("-tcl") + 1].endswith("resources/tcl/esl_h3d_extract.tcl")
    assert argv[argv.index("-output") + 1] == raw and argv[argv.index("-part") + 1] == "chassis rear"
    assert argv[argv.index("-hot_k") + 1] == "150" and argv[argv.index("-top_n") + 1] == "4"
    assert rec["cwd"] == str(Path(raw).parent) and rec["env_input"] == case["h3d_path"]
    req = (Path(raw).parent / "request.txt").read_text()
    assert "part_title\tchassis rear" in req and "hot_k\t150" in req
    from sqlalchemy import text

    with engine.connect() as c:
        cmd = c.execute(text("SELECT command FROM job_steps WHERE job_id = :j AND step_no = 1"), {"j": job["id"]}
                        ).scalar_one()
    assert cmd == argv
    # 이후 기존 pack → tstar 결과(합성 Case)
    c = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    assert c["extract_summary"]["part_id"] == synth_case.PART_ID
    # 0.5.5: 가짜 hw 도 elems.csv(요소 연결)를 내고 pack 이 노드 ID + 요소 연결로 같은 모델임을 확인
    assert (Path(raw) / "elems.csv").is_file()
    assert not any("CONN_CHECK_SKIPPED" in w for w in c["extract_summary"]["warnings"]), c["extract_summary"]["warnings"]
    assert c["stage_status"]["1"]["state"] == "done" and c["stage_status"]["2"]["state"] == "done"
    t = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()
    assert t["selected"]["frame_index"] == synth_case.T_STAR_FRAME
    log = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()
    assert any("fake hw start" in ln for ln in log["lines"]) and any("hw 종료코드 0" in ln for ln in log["lines"])
    # h3d 가 바뀌면 입력 지문이 감지(다음 작업 INPUT_CHANGED)
    from esl_platform.core.inputs import changed_inputs

    h = Path(case["h3d_path"])
    assert changed_inputs(c["input_fingerprint"]) == []
    os.utime(h, (h.stat().st_atime, h.stat().st_mtime + 5))
    assert changed_inputs(c["input_fingerprint"]) == [str(h)]


def test_h3d_extract_failure_reports_done_json(client, synth_inputs, worker_factory, monkeypatch):
    monkeypatch.setenv("FAKE_HW_MODE", "fail")
    case = _h3d_case(client, synth_inputs)
    job = _job(client, case["id"])
    assert worker_factory().run_once("SLOT") == "FAILED"
    j = _get(client, job["id"])
    assert j["failure_code"] == "H3D_EXTRACT_FAILED"
    assert "failed_step=GetResultCtrlHandle" in j["failure_message"] and "H3D_MISSING_RESULT" in j["failure_message"]
    s1 = j["steps"][0]
    assert s1["state"] == "FAILED" and s1["failure_code"] == "H3D_EXTRACT_FAILED" and s1["exit_code"] == 1
    assert [s["state"] for s in j["steps"][1:]] == ["SKIPPED"] * 3
    log = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()["lines"]
    assert any("errorInfo" in ln for ln in log) and any("while executing" in ln for ln in log)
    # done.json 없음 → 같은 실패 코드(종료코드 표시)
    monkeypatch.setenv("FAKE_HW_MODE", "nodone")
    r = client.post(f"{API}/jobs/{job['id']}/retry", headers=W)
    assert r.status_code == 201 and r.json()["steps"][0]["state"] == "PENDING"
    assert worker_factory().run_once("SLOT") == "FAILED"
    j2 = _get(client, r.json()["id"])
    assert j2["failure_code"] == "H3D_EXTRACT_FAILED" and "종료코드 3" in j2["failure_message"]


def test_h3d_missing_hw(client, synth_inputs, worker_factory, tmp_path):
    case = _h3d_case(client, synth_inputs)
    job = _job(client, case["id"])
    w = worker_factory()
    object.__setattr__(w.settings.altair, "hw_exe_path", str(tmp_path / "nohw"))
    assert w.run_once("SLOT") == "FAILED"
    j = _get(client, job["id"])
    assert j["failure_code"] == "H3D_EXTRACT_FAILED" and "hw 실행 파일이 없습니다" in j["failure_message"]


def test_h3d_cancel_kills_process_tree(client, synth_inputs, worker_factory, tmp_path, monkeypatch):
    pids_file = tmp_path / "hw.pids"
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(pids_file))
    case = _h3d_case(client, synth_inputs)
    job = _job(client, case["id"])
    worker = worker_factory()
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("state", worker.run_once("SLOT")))
    t.start()
    wait_for(lambda: pids_file.is_file() and len(pids_file.read_text().split()) == 2)
    hw_pid, child_pid = map(int, pids_file.read_text().split())
    assert alive(hw_pid) and alive(child_pid)
    j = _get(client, job["id"])
    assert j["state"] == "RUNNING" and j["steps"][0]["state"] == "RUNNING"
    assert client.post(f"{API}/jobs/{job['id']}/cancel", headers=W).status_code == 200
    t.join(30)
    assert not t.is_alive() and out["state"] == "CANCELED"
    wait_for(lambda: not alive(hw_pid) and not alive(child_pid), timeout=10)
    j = _get(client, job["id"])
    assert j["state"] == "CANCELED" and [s["state"] for s in j["steps"]] == ["CANCELED"] * 4


def test_results_case_has_no_h3d_step(client, mini_inputs):
    cid = create_case(client, mini_inputs).json()["id"]
    c = client.get(f"{API}/cases/{cid}", headers=R).json()
    assert c["input_kind"] == "RESULTS"
    job = _job(client, cid)
    assert [s["step_key"] for s in job["steps"]] == ["EXTRACT", "TSTAR_SCAN", "EXTRACT_REGISTER"]
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {"hot_k": 5}}, headers=W)
    assert r.status_code in (409, 422)


# ---------------------------------------------------------------- 동시 실행
def test_two_slots_run_concurrently_hw_semaphore(client, synth_inputs, worker_factory, monkeypatch, esl_root):
    """slots=2: 다른 Case 두 추출이 동시에 RUNNING. max_concurrent_hw=1 → 두 번째 hw 는 첫 hw 가 끝날 때까지 대기."""
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    monkeypatch.setenv("FAKE_HW_DELAY", "1.5")
    c1 = _h3d_case(client, synth_inputs, "case01", "A")
    c2 = _h3d_case(client, synth_inputs, "case02", "B")
    j1, j2 = _job(client, c1["id"]), _job(client, c2["id"])
    w = worker_factory()
    res: dict = {}
    ts = [threading.Thread(target=lambda k=k: res.setdefault(k, w.run_once("SLOT"))) for k in (1, 2)]
    for t in ts:
        t.start()
    wait_for(lambda: all(_get(client, j["id"])["state"] == "RUNNING" for j in (j1, j2)), timeout=20)
    q = client.get(f"{API}/queue", headers=R).json()
    assert q["slots"] == 2 and {x["id"] for x in q["running_all"]} == {j1["id"], j2["id"]}
    for t in ts:
        t.join(120)
    assert sorted(res.values()) == ["SUCCEEDED", "SUCCEEDED"], (_get(client, j1["id"]), _get(client, j2["id"]))
    logs = [client.get(f"{API}/jobs/{j['id']}/log", params={"step": 1}, headers=R).json()["lines"] for j in (j1, j2)]
    waited = [any("동시 실행 한도 1개" in ln for ln in lg) for lg in logs]
    assert waited.count(True) == 1, logs


def test_claim_slots_and_case_serialization(client, engine, mini_inputs):
    from esl_platform.core.repositories import jobs as jobs_repo

    ids = []
    for i in range(3):
        cid = create_case(client, mini_inputs, folder=f"c{i}", title=f"t{i}").json()["id"]
        ids.append(_job(client, cid)["id"])
    won = []

    def go(i):
        try:
            with engine.begin() as c:
                j = jobs_repo.claim_slot(c, f"w{i}", 30, 2)
        except Exception:  # noqa: BLE001 - 경합 패배
            j = None
        if j:
            won.append((j["id"], j["slot_id"]))

    barrier = threading.Barrier(5)
    ts = [threading.Thread(target=lambda i=i: (barrier.wait(), go(i))) for i in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(won) == 2 and sorted(s for _, s in won) == [1, 2] and len({j for j, _ in won}) == 2
    with engine.begin() as c:
        assert jobs_repo.claim_slot(c, "w9", 30, 2) is None          # 2개 다 참
        assert jobs_repo.running_slot_count(c) == 2
        third = jobs_repo.claim_slot(c, "w9", 30, 3)                  # slots 3 이면 세 번째
    assert third is not None and third["slot_id"] == 3
    # 끝나면 슬롯 반환
    with engine.begin() as c:
        jobs_repo.release(c, third["id"], third["lease_token"], "FAILED", failure_code="X")
        assert jobs_repo.running_slot_count(c) == 2


def test_hw_semaphore_db(client, engine, mini_inputs):
    from esl_platform.core.repositories import jobs as jobs_repo
    from esl_platform.core.db.tables import job_steps
    from sqlalchemy import update

    cl = []
    for i in range(2):
        cid = create_case(client, mini_inputs, folder=f"h{i}", title=f"h{i}").json()["id"]
        _job(client, cid)
        with engine.begin() as c:
            cl.append(jobs_repo.claim_slot(c, "w", 30, 2))
    for j in cl:      # H3D step 이 실행 중인 것처럼(step 1 을 H3D_EXTRACT RUNNING 으로)
        with engine.begin() as c:
            c.execute(update(job_steps).where(job_steps.c.job_id == j["id"]).where(job_steps.c.step_no == 1)
                      .values(step_key="H3D_EXTRACT", state="RUNNING"))
    with engine.begin() as c:
        assert jobs_repo.acquire_hw(c, cl[0]["id"], cl[0]["lease_token"], 1, 1)
        assert jobs_repo.acquire_hw(c, cl[0]["id"], cl[0]["lease_token"], 1, 1)        # 이미 잡음
    with engine.begin() as c:
        assert not jobs_repo.acquire_hw(c, cl[1]["id"], cl[1]["lease_token"], 1, 1)
        assert jobs_repo.acquire_hw(c, cl[1]["id"], cl[1]["lease_token"], 1, 2)        # 한도 2
        assert jobs_repo.hw_in_use(c) == 2
    with engine.begin() as c:   # 첫 작업 중단(리퍼·실패) → 자동 해제
        jobs_repo.release(c, cl[0]["id"], cl[0]["lease_token"], "FAILED", failure_code="X")
        assert jobs_repo.hw_in_use(c) == 1


def test_per_job_limits(loaded_config):
    from esl_worker import limiter

    wc = loaded_config.settings.worker
    lim = limiter.job_limits(wc, 2)
    assert lim.max_memory_gb == pytest.approx(wc.max_memory_gb / 2) and lim.max_logical_cores == wc.max_logical_cores // 2
    assert lim.cpu_offset == wc.max_logical_cores // 2
    lim2 = limiter.job_limits(wc.model_copy(update={"per_job_memory_gb": 5.0}), 1)
    assert lim2.max_memory_gb == 5.0 and lim2.cpu_offset == 0


def test_build_argv_rules():
    from esl_worker import h3d

    tpl = ["{hw}", "-tcl", "{extract_tcl_fwd}", "-input", "{h3d_fwd}", "-part", "{part}", "-output", "{out_dir}"]
    vals = h3d.values_for(hw="C:/Program Files/Altair/hw.exe", tcl="D:\\app\\r.tcl", h3d="E:\\in\\a.h3d",
                          request="E:/w/request.txt", out_dir="E:/o", part="chassis rear", hot_k=200, top_n=5)
    argv = h3d.build_argv(tpl, vals)
    assert argv[0] == "C:/Program Files/Altair/hw.exe" and argv[2] == "D:/app/r.tcl" and argv[4] == "E:/in/a.h3d"
    assert argv[6] == "chassis rear"
    for bad in ("a&b", "x|y", "p%PATH%", 'q"', "z!", "line\nbreak"):
        with pytest.raises(h3d.H3dError) as ei:
            h3d.build_argv(tpl, {**vals, "part": bad})
        assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(h3d.H3dError):
        h3d.build_argv(["cmd", "{h3d}"], vals)
    bat = {**vals, "hw": "C:/x/hw.bat", "part": "a(b)"}
    with pytest.raises(h3d.H3dError):
        h3d.build_argv(tpl, bat)
    assert h3d.build_argv(tpl, {**vals, "part": "a(b)"})[6] == "a(b)"


def test_reaper_releases_slot_and_hw(client, engine, mini_inputs):
    """lease 만료 → 리퍼가 작업 INTERRUPTED·슬롯 회수(여러 슬롯 중 해당 행만)."""
    from esl_platform.core.repositories import jobs as jobs_repo

    a = create_case(client, mini_inputs, folder="r1", title="r1").json()["id"]
    b = create_case(client, mini_inputs, folder="r2", title="r2").json()["id"]
    _job(client, a)
    _job(client, b)
    with engine.begin() as c:
        ja = jobs_repo.claim_slot(c, "w", 0.2, 2)
    with engine.begin() as c:
        jb = jobs_repo.claim_slot(c, "w", 30, 2)
    time.sleep(0.4)
    with engine.begin() as c:
        assert jobs_repo.reap_expired(c) == [ja["id"]]
        assert jobs_repo.running_slot_count(c) == 1
        assert jobs_repo.renew(c, jb["id"], jb["lease_token"], 30, slot=True)
