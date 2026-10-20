"""V-LS-1~3: lease 만료 → INTERRUPTED(WORKER_LOST)·슬롯 회수, 동시 claim 승자 1, lease_token 비노출.
LIGHT 레인은 슬롯과 무관하게 동시 1개."""

from __future__ import annotations

import threading
import time

from esl_test_support import API, H, create_case
from sqlalchemy import select

from esl_platform.core.db.tables import notifications, worker_slot
from esl_platform.core.repositories import jobs as jobs_repo


def _queue_extract(client, mini_inputs, folder="c1", title="t1"):
    cid = create_case(client, mini_inputs, folder=folder, title=title).json()["id"]
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}},
                    headers=H("tok-power", True))
    assert r.status_code == 201, r.text
    return r.json()


def test_v_ls_1_lease_expiry(client, engine, mini_inputs):
    job = _queue_extract(client, mini_inputs)
    with engine.begin() as c:
        claimed = jobs_repo.claim_slot(c, "w-test", 0.2)
    assert claimed["id"] == job["id"] and claimed["state"] == "RUNNING" and claimed["holds_slot"]
    time.sleep(0.4)
    with engine.begin() as c:
        reaped = jobs_repo.reap_expired(c)
    assert reaped == [job["id"]]
    j = client.get(f"{API}/jobs/{job['id']}", headers=H("tok-power")).json()
    assert j["state"] == "INTERRUPTED" and j["failure_code"] == "WORKER_LOST"
    assert [s["state"] for s in j["steps"]] == ["SKIPPED"] * 3
    with engine.connect() as c:
        slot = c.execute(select(worker_slot).where(worker_slot.c.id == 1)).one()
        assert slot.holder_job_id is None and slot.lease_token is None
        ev = [r.event for r in c.execute(select(notifications).where(notifications.c.job_id == job["id"]))]
    assert "JOB_INTERRUPTED" in ev
    # 잃은 lease 로는 상태를 쓸 수 없다
    import pytest

    from esl_platform.core.errors import LeaseLost

    with pytest.raises(LeaseLost), engine.begin() as c:
        jobs_repo.release(c, job["id"], claimed["lease_token"], "SUCCEEDED")
    with engine.begin() as c:
        assert not jobs_repo.renew(c, job["id"], claimed["lease_token"], 5, slot=True)


def test_v_ls_2_concurrent_claim_one_winner(client, engine, mini_inputs):
    _queue_extract(client, mini_inputs)
    barrier = threading.Barrier(4)
    won = []

    def go(i):
        barrier.wait()
        try:
            with engine.begin() as c:
                j = jobs_repo.claim_slot(c, f"w{i}", 30)
        except Exception:  # noqa: BLE001 - 직렬화 충돌도 패배로 본다
            j = None
        if j:
            won.append(j["id"])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(won) == 1
    # 슬롯이 잡혀 있으면 다음 SLOT 작업은 claim 안 됨
    _queue_extract(client, mini_inputs, folder="c2", title="t2")
    with engine.begin() as c:
        assert jobs_repo.claim_slot(c, "w9", 30) is None


def test_v_ls_3_no_lease_in_responses(client, engine, mini_inputs, worker_factory):
    job = _queue_extract(client, mini_inputs)
    with engine.begin() as c:
        jobs_repo.claim_slot(c, "w-test", 30)
    w = worker_factory()
    w.heartbeat_once()
    for url in (f"/jobs/{job['id']}", f"/cases/{job['case_id']}/jobs", "/queue", f"/cases/{job['case_id']}", "/status"):
        r = client.get(API + url, headers=H("tok-admin"))
        assert r.status_code == 200, url
        assert "\"lease_" not in r.text, url
    q = client.get(f"{API}/queue", headers=H("tok-admin")).json()
    assert q["running"]["id"] == job["id"] and q["light"]["running"] is None
    st = client.get(f"{API}/status", headers=H("tok-admin")).json()
    assert st["worker"]["online"] is True
    assert set(st["tools"]) == {"solver_backend", "solver_backends_available"}
    from esl.mech.shell import available_backends, resolve_backend
    assert st["tools"]["solver_backends_available"] == [*available_backends(), "iterative"]
    assert st["tools"]["solver_backend"] == resolve_backend("auto")          # 설정 auto → ShellModel.stats.backend 와 같음


def test_light_lane_independent_of_slot(client, engine, mini_inputs):
    j1 = _queue_extract(client, mini_inputs)
    j2 = _queue_extract(client, mini_inputs, folder="c2", title="t2")
    with engine.begin() as c:
        jobs_repo.claim_slot(c, "w", 30)
        for j in (j1, j2):  # 사전조건을 우회해 LIGHT 작업을 직접 넣는다
            jobs_repo.insert_job(c, case_id=j["case_id"], project_id="p-1", job_type="EXPORT", params={},
                                 created_by="u", created_by_name="u")
    with engine.begin() as c:
        a = jobs_repo.claim_light(c, "w", 30)
    with engine.begin() as c:
        b = jobs_repo.claim_light(c, "w", 30)
    assert a is not None and a["lane"] == "LIGHT" and not a["holds_slot"] and b is None
