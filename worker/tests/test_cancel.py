"""V-P1B-2: RUNNING 작업 취소 → 코어 자식 프로세스 종료, CANCELED, 출력 폴더 일관(재실행 시 _backup/)."""

from __future__ import annotations

import os
import threading

from esl_test_support import API, H, create_case, wait_for

W = H("tok-power", True)
R = H("tok-power")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # 좀비면 종료된 것으로 본다
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return "zombie" not in fh.read()
    except OSError:
        return False


def test_cancel_kills_core_process(client, mini_inputs, worker_factory, esl_root):
    cid = create_case(client, mini_inputs).json()["id"]
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    worker = worker_factory(core_target="slow_core:run")
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("state", worker.run_once("SLOT")))
    t.start()
    pid_path = os.path.join(str(esl_root), "case01", "logs", job["id"], "slow_core.pid")
    wait_for(lambda: os.path.isfile(pid_path) and open(pid_path).read().strip())
    pid = int(open(pid_path).read())
    assert _alive(pid)
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert j["state"] == "RUNNING" and j["steps"][0]["state"] == "RUNNING"
    assert not any(k.startswith("lease_") for k in j)
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=W)
    assert r.status_code == 200 and r.json()["cancel_requested"] is True
    t.join(30)
    assert not t.is_alive() and out["state"] == "CANCELED"
    assert not _alive(pid)
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert j["state"] == "CANCELED" and j["failure_code"] == "CANCELED"
    assert [s["state"] for s in j["steps"]] == ["CANCELED", "CANCELED", "CANCELED"]
    # 슬롯 해제 → 다음 작업 실행 가능, 종료 작업 취소 409
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_TERMINAL"
    log = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()
    assert any("slow_core" in ln for ln in log["lines"])


def test_rerun_after_partial_output_moves_to_backup(client, synth_inputs, worker_factory, esl_root):
    """부분/이전 산출물이 있으면 코어가 _backup/<ts>/ 로 옮기고 새로 쓴다(삭제 안 함)."""
    cid = create_case(client, synth_inputs).json()["id"]
    cdir = os.path.join(str(esl_root), "case01")
    os.makedirs(os.path.join(cdir, "01_extract"))
    with open(os.path.join(cdir, "01_extract", "partial.npz"), "wb") as fh:
        fh.write(b"partial")
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    assert worker_factory().run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert not os.path.exists(os.path.join(cdir, "01_extract", "partial.npz"))
    backups = []
    for root, _, files in os.walk(os.path.join(cdir, "_backup")):
        backups += [f for f in files if f == "partial.npz"]
    assert backups == ["partial.npz"]


def test_cancel_queued_and_retry(client, mini_inputs, worker_factory):
    cid = create_case(client, mini_inputs).json()["id"]
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    assert job["state"] == "QUEUED" and job["queue_position"] == 1
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=W)
    assert r.json()["state"] == "CANCELED"
    assert worker_factory().run_once("SLOT") is None
    r = client.post(f"{API}/jobs/{job['id']}/retry", headers=W)
    assert r.status_code == 201, r.text
    nj = r.json()
    assert nj["retry_of_job_id"] == job["id"] and nj["state"] == "QUEUED"
    r = client.post(f"{API}/jobs/{nj['id']}/retry", headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_NOT_TERMINAL"


def test_input_changed_fails_job(client, mini_inputs, worker_factory):
    cid = create_case(client, mini_inputs).json()["id"]
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    st = os.stat(mini_inputs["rad"])
    os.utime(mini_inputs["rad"], (st.st_atime, st.st_mtime + 10))
    assert worker_factory().run_once("SLOT") == "FAILED"
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert j["failure_code"] == "INPUT_CHANGED"
    assert [s["state"] for s in j["steps"]] == ["SKIPPED"] * 3
