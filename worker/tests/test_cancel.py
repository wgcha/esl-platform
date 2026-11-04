"""V-P1B-2: RUNNING 작업 취소 → 코어 자식 프로세스 종료, CANCELED, 출력 폴더 일관(재실행 시 _backup/)."""

from __future__ import annotations

import os
import threading

import pytest
from esl_test_support import API, H, create_case, past_ttl_s, wait_for

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


@pytest.mark.short_lease
def test_tick_error_during_inproc_waits_for_thread_and_blocks_same_case(client, synth_inputs, worker_factory, engine,
                                                                       monkeypatch, loaded_config):
    """v0.12.3(Verifier): inproc.call 중 tick(취소 확인)이 DB 오류를 던져도 작업 스레드(산출물 sha256)가 끝날 때까지
    기다린 뒤에야 실패로 끝난다. 그동안 lease 를 갱신해 작업은 RUNNING — 같은 Case 새 작업은 claim 되지 않는다."""
    import time

    from esl_platform.core.repositories import jobs as jobs_repo
    from esl_worker import executor as ex_mod
    from esl_worker import register

    cid = create_case(client, synth_inputs).json()["id"]
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    started = threading.Event()
    marks: dict = {}
    real = register.artifact_shas
    beyond = past_ttl_s(loaded_config)

    def slow_shas(cdir, rels):                     # stop 을 보지 않는 함수 — 설정 lease_ttl_s 보다 길게
        started.set()
        time.sleep(beyond)
        marks["done_at"] = time.monotonic()
        return real(cdir, rels)

    real_cancel = ex_mod.Executor._cancel_requested

    def flaky_cancel(self):
        if started.is_set():
            raise RuntimeError("tick 중 DB 오류(주입)")
        return real_cancel(self)

    monkeypatch.setattr(register, "artifact_shas", slow_shas)
    monkeypatch.setattr(ex_mod.Executor, "_cancel_requested", flaky_cancel)
    worker = worker_factory()
    out: dict = {}

    def run() -> None:
        out["state"] = worker.run_once("SLOT")
        out["end"] = time.monotonic()

    t = threading.Thread(target=run)
    t.start()
    assert started.wait(120)
    with engine.begin() as conn:                   # 같은 Case 의 다른 종류 작업(대기)
        other = jobs_repo.insert_job(conn, case_id=cid, project_id="p-1", job_type="ESL_SOLVE", params={},
                                     created_by="u", created_by_name="u")
    other_worker = worker_factory()
    end = time.monotonic() + past_ttl_s(loaded_config, 1.2)
    while time.monotonic() < end:                  # 설정 lease_ttl_s 넘게
        time.sleep(0.3)
        if not t.is_alive():
            break
        assert other_worker.run_once("SLOT") is None            # 리퍼가 가로채지 않고, 같은 Case 라 claim 안 됨
        assert client.get(f"{API}/jobs/{job['id']}", headers=R).json()["state"] == "RUNNING"
    t.join(60)
    assert not t.is_alive() and out["state"] == "FAILED"
    assert out["end"] >= marks["done_at"]                     # 작업 스레드가 끝난 뒤에야 반환
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert j["state"] == "FAILED" and j["failure_code"] == "INTERNAL_ERROR"
    assert client.get(f"{API}/jobs/{other['id']}", headers=R).json()["state"] == "QUEUED"
