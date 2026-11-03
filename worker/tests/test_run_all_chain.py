"""v0.13.0 일괄 실행 워커 연쇄(계약 esl_run_all.md §4·§5·§6): 코어 합성 Case(실제 워커) + 가짜 워커(claim 후 바로 종료 전이).

V-RA-3(①→④ 자동·DONE·라이브러리 0)·V-RA-4(가드)·V-RA-5(BLOCKED → 고급 지정 → 이어서)·V-RA-6(건너뜀·③④만)·V-RA-7(입양)·
V-RA-8(실패·중단·재시도 뒤 이어서)·V-RA-9(FAIL·UNDETERMINED)·V-RA-10(취소)·V-RA-11(훅 2회·IntegrityError 입양)·V-RA-15(끊김 복구).
"""

from __future__ import annotations

import pytest
from esl_test_support import API, H, create_case
from sqlalchemy import text

from esl_platform.core import run_all as ra
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import run_all as repo

W = H("tok-power", True)
R = H("tok-power")


def _case(client, cid):
    return client.get(f"{API}/cases/{cid}", headers=R).json()


def _ra(client, cid):
    return client.get(f"{API}/cases/{cid}/run-all", headers=R).json()


def _jobs(client, cid):
    return client.get(f"{API}/cases/{cid}/jobs", headers=R).json()


def _start(client, cid, frm=None, token="tok-power"):
    r = client.post(f"{API}/cases/{cid}/run-all", json={"from": frm} if frm else {}, headers=H(token, True))
    assert r.status_code == 201, r.text
    return r.json()


def _step(worker, expect="SUCCEEDED"):
    st = worker.run_once("SLOT")
    assert st == expect, st
    return st


def _fake_end(engine, worker, state, esl_root, code="CORE_FAILED", msg="가짜 실패"):
    """가짜 워커: 다음 SLOT 작업을 claim 하고 코어 없이 바로 종료 전이(훅 포함)."""
    job = worker.claim("SLOT")
    assert job is not None
    with engine.begin() as conn:
        jobs_repo.release(conn, job["id"], job["lease_token"], state, failure_code=code if state != "SUCCEEDED" else None,
                          failure_message=msg, run_all_prep=ra.WorkerPrep(esl_root=str(esl_root)))
    return job


def _library_count(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM library_entries")).scalar_one()


def _new_chain(client, synth, folder):
    r = create_case(client, synth, folder=folder, title=folder, run_all=True)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["run_all"]["status"] == "RUNNING" and c["run_all"]["cur_step"] == "input"
    return c


# ---------------------------------------------------------------- V-RA-3·6·9·11
def test_v_ra_3_full_chain_then_skip_stale_fail(client, synth_inputs, worker_factory, engine, esl_root, app_ctx):
    worker = worker_factory()
    c = _new_chain(client, synth_inputs, "ra01")
    cid = c["id"]
    _step(worker)                                                  # ① → 훅: ② 자동 확정 + ③ 생성
    case = _case(client, cid)
    ts = case["tstar"]
    assert ts["source"] == "auto" and ts["confirmed"]["by"] == "run_all"
    assert ts["confirmed"]["run_all_id"] == c["run_all"]["id"] and ts["confirmed"]["user_id"] == "u-power"
    assert ts["support_auto"]["status"] == "OK" and case["current_support_set_id"]
    sets = client.get(f"{API}/cases/{cid}/support-sets", headers=R).json()
    assert len(sets) == 1 and sets[0]["source"] == "auto"
    run = case["run_all"]
    assert run["status"] == "RUNNING" and run["cur_step"] == "esl" and run["cur_job_state"] == "QUEUED"
    assert run["skipped"] == [{"step": "tstar", "state": "auto_confirmed", "metric": ts["metric"],
                               "frame_index": ts["frame_index"], "support": "OK"}]
    _step(worker)                                                  # ③ → ④ 생성
    assert _ra(client, cid)["cur_step"] == "validate"
    _step(worker)                                                  # ④ PASS → DONE
    run = _ra(client, cid)
    assert run["status"] == "DONE" and run["verdict"] == "PASS" and run["stop_code"] is None
    assert run["stop_reason"]["message"].startswith("④ 검증 PASS")
    assert [(j["step"], j["adopted"]) for j in run["job_ids"]] == [("input", False), ("esl", False), ("validate", False)]
    jobs = _jobs(client, cid)
    assert {j["job_type"] for j in jobs} == {"CASE_EXTRACT", "ESL_SOLVE", "VALIDATE"}
    assert all(j["run_all_id"] == run["id"] and j["state"] == "SUCCEEDED" for j in jobs)
    assert _library_count(engine) == 0                             # RA-D-8 라이브러리 등록 안 함
    assert worker.run_once("SLOT") is None                         # 다음 작업 없음
    st = _case(client, cid)["step_status"]
    assert all(st[s]["state"] == "done" for s in ra.STEPS)

    # V-RA-6 전부 done + PASS → 201 DONE, 작업 0개
    n0 = len(_jobs(client, cid))
    r2 = _start(client, cid)
    assert r2["status"] == "DONE" and r2["job_ids"] == [] and [s["step"] for s in r2["skipped"]] == ["input", "tstar", "esl"]
    assert len(_jobs(client, cid)) == n0 and r2["resumed_from_id"] is None and r2["superseded"] is False

    # V-RA-6 t* 변경(사람 확정, 다른 후보) → ESL stale → ③④ 만
    tj = client.get(f"{API}/cases/{cid}/tstar", headers=R).json()
    other = next(x["frame_index"] for x in tj["metrics"][ts["metric"]]["candidates"]
                 if x["frame_index"] != ts["frame_index"] and x.get("in_D") is not False)
    case = _case(client, cid)
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": ts["metric"],
                                                     "frame_index": other}, headers=W)
    assert r.status_code == 200, r.text
    assert r.json()["step_status"]["esl"]["state"] == "stale"
    r3 = _start(client, cid)
    assert r3["status"] == "RUNNING" and r3["cur_step"] == "esl" and [s["step"] for s in r3["skipped"]] == ["input", "tstar"]
    assert _ra(client, cid)["id"] == r3["id"]
    old = client.get(f"{API}/cases/{cid}/run-all", params={"all": 1}, headers=R).json()
    assert [x["id"] for x in old][:2] == [r3["id"], r2["id"]]
    _step(worker)
    _step(worker)
    run = _ra(client, cid)
    assert run["status"] == "DONE" and [j["step"] for j in run["job_ids"]] == ["esl", "validate"]

    # V-RA-11 같은 작업 훅 2회 → 2번째는 아무것도 안 함
    last = run["job_ids"][-1]["job_id"]
    with engine.begin() as conn:
        assert ra.on_job_end(conn, jobs_repo.get_job(conn, last), ra.WorkerPrep(str(esl_root))) is None

    # V-RA-11 IntegrityError → 입양: 같은 종류 비종료 작업이 이미 있으면 그 작업을 기다린다
    with engine.begin() as conn:
        case = _case(client, cid)
        manual = jobs_repo.insert_job(conn, case_id=cid, project_id="p-1", job_type="ESL_SOLVE", params={},
                                      created_by="u-power2", created_by_name="파워2")
        row = repo.insert_run(conn, case_id=cid, project_id="p-1", from_step="esl", core_settings={},
                              created_by="u-power", created_by_name="파워")
        out = ra._create(conn, row, case, ra.Env(esl_root=str(esl_root)), "esl", "ESL_SOLVE")
        assert out["cur_job_id"] == manual["id"] and out["job_ids"] == [{"step": "esl", "job_id": manual["id"],
                                                                          "adopted": True}]
        conn.rollback()

    # V-RA-9 ④ FAIL·UNDETERMINED(그대로 [이어서 실행] → 같은 사유, 작업 0개)
    vid = run["stop_reason"]["detail"]["validation_id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE validations SET verdict='FAIL', fail_reasons='[\"DISP_RMS\"]' WHERE id=:v"), {"v": vid})
    n0 = len(_jobs(client, cid))
    for _ in range(2):
        s = _start(client, cid)
        assert s["status"] == "STOPPED" and s["stop_step"] == "validate" and s["stop_code"] == "VALIDATION_FAIL"
        assert s["verdict"] == "FAIL" and s["stop_reason"]["detail"]["fail_reasons"] == ["DISP_RMS"]
        assert s["can_resume"] is True and s["stop_reason"]["message"].startswith("검증 FAIL")
    assert s["resumed_from_id"] is not None and len(_jobs(client, cid)) == n0
    with engine.begin() as conn:
        conn.execute(text("UPDATE validations SET verdict='UNDETERMINED', scheme='disp_primary/1', "
                          "undetermined_reason='DISP_BELOW_NOISE' WHERE id=:v"), {"v": vid})
    s = _start(client, cid, "validate")
    assert s["stop_code"] == "VALIDATION_UNDETERMINED" and s["verdict"] == "UNDETERMINED"
    assert s["stop_reason"]["message"] == "검증 판정 불가 — DISP_BELOW_NOISE"

    # superseded: 종료 뒤 체인과 무관한 ①③④ 작업이 생김
    j = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "VALIDATE",
                                                     "params": {"esl_run_id": _case(client, cid)["current_esl_run_id"]}},
                    headers=W)
    assert j.status_code == 201, j.text
    assert _ra(client, cid)["superseded"] is True


# ---------------------------------------------------------------- V-RA-4 가드
def test_v_ra_4_guard_adjusted_stops(client, synth_inputs, worker_factory, monkeypatch):
    """1순위 후보가 D 밖(코어가 다른 후보로 바꿈 = adjusted) → ② STOPPED TSTAR_REVIEW_REQUIRED/TSTAR_ADJUSTED, ③ 작업 없음."""
    from esl_platform.core import core_outputs as co

    orig = co.tstar_info

    def adjusted(cdir):
        info = orig(cdir)
        for blk in info["metrics"].values():
            blk["candidates"] = [{"rank": 0, "frame_index": 9999, "time": 9.9, "elem_id": 1, "value": 1.0,
                                  "in_D": False}] + list(blk["candidates"])
        return info
    monkeypatch.setattr(co, "tstar_info", adjusted)
    worker = worker_factory()
    c = _new_chain(client, synth_inputs, "ra04")
    _step(worker)
    run = _ra(client, c["id"])
    assert run["status"] == "STOPPED" and run["stop_step"] == "tstar" and run["stop_code"] == "TSTAR_REVIEW_REQUIRED"
    assert [r["code"] for r in run["stop_reason"]["detail"]["reasons"]] == ["TSTAR_ADJUSTED"]
    assert "1순위 시점이 변위 추출 프레임에 없어" in run["stop_reason"]["message"] and run["can_resume"]
    case = _case(client, c["id"])
    assert case["current_support_set_id"] is None and "confirmed" not in case["tstar"]
    assert [j["job_type"] for j in _jobs(client, c["id"])] == ["CASE_EXTRACT"]
    # 사람이 [t* 확정] → [이어서 실행](from = stop_step) → ③ 부터
    monkeypatch.setattr(co, "tstar_info", orig)
    r = client.put(f"{API}/cases/{c['id']}/tstar", json={"version": case["version"], "metric": case["tstar"]["metric"],
                                                        "frame_index": case["tstar"]["frame_index"]}, headers=W)
    assert r.status_code == 200, r.text
    s = _start(client, c["id"], run["stop_step"])
    assert s["status"] == "RUNNING" and s["cur_step"] == "esl" and s["resumed_from_id"] == run["id"]
    assert _ra(client, c["id"])["id"] == s["id"]
    hist = client.get(f"{API}/cases/{c['id']}/run-all", params={"all": 1}, headers=R).json()
    assert hist[1]["id"] == run["id"] and hist[1]["can_resume"] is False      # 이후 RUNNING 행 있음


def test_v_ra_4_user_tstar_changed_and_adopt(client, synth_inputs, worker_factory):
    """사람이 고른 t*(다른 후보)를 체인 중 재추출이 auto 로 덮어씀 → USER_TSTAR_CHANGED. 같으면 통과. (V-RA-7 ① 입양 포함)"""
    worker = worker_factory()
    r = create_case(client, synth_inputs, folder="ra05", title="ra05")
    cid = r.json()["id"]
    j = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    _step(worker)
    case = _case(client, cid)
    auto = case["tstar"]
    tj = client.get(f"{API}/cases/{cid}/tstar", headers=R).json()
    other = next(x["frame_index"] for x in tj["metrics"][auto["metric"]]["candidates"]
                 if x["frame_index"] != auto["frame_index"] and x.get("in_D") is not False)
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": auto["metric"],
                                                     "frame_index": other}, headers=W)
    assert r.status_code == 200 and r.json()["tstar"]["source"] == "user" and r.json()["current_support_set_id"]
    # 수동 재추출(QUEUED) 상태에서 시작 → 새 작업 없이 입양
    j2 = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    s = _start(client, cid)
    assert s["status"] == "RUNNING" and s["cur_job_id"] == j2["id"] and s["job_ids"] == [
        {"step": "input", "job_id": j2["id"], "adopted": True}]
    assert client.get(f"{API}/jobs/{j2['id']}", headers=R).json()["run_all_id"] is None    # 입양 작업은 배지 없음
    _step(worker)                                                  # 재추출 → t* auto(지지 세트 유지) → G4 실패
    run = _ra(client, cid)
    assert run["status"] == "STOPPED" and run["stop_code"] == "TSTAR_REVIEW_REQUIRED"
    assert run["stop_reason"]["detail"]["reasons"][0]["code"] == "USER_TSTAR_CHANGED"
    assert f"frame {other}" in run["stop_reason"]["message"] and f"frame {auto['frame_index']}" in run["stop_reason"]["message"]
    assert len(_jobs(client, cid)) == 2 and j["id"] != j2["id"]
    # 사람이 현재 auto 값을 확정(source user, 같은 frame) → 이어서 → G4 통과 → ③
    case = _case(client, cid)
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": auto["metric"],
                                                     "frame_index": case["tstar"]["frame_index"]}, headers=W)
    assert r.status_code == 200
    s = _start(client, cid, "tstar")
    assert s["status"] == "RUNNING" and s["cur_step"] == "esl" and [(x["step"], x["state"]) for x in s["skipped"]] == [
        ("tstar", "done")]


# ---------------------------------------------------------------- V-RA-5 BLOCKED
def test_v_ra_5_blocked_then_manual_resume(client, synth_inputs, worker_factory, app_ctx):
    worker = worker_factory()
    ac = app_ctx.config.core["support"]
    ac["auto_check"] = {"min_dist_rel": 0.99}                      # 시작 시 스냅샷(RA-D-6) → 자동 선택 BLOCKED
    try:
        c = _new_chain(client, synth_inputs, "ra06")
    finally:
        ac.pop("auto_check", None)
    cid = c["id"]
    _step(worker)
    run = _ra(client, cid)
    assert run["status"] == "STOPPED" and run["stop_step"] == "tstar" and run["stop_code"] == "SUPPORT_AUTO_BLOCKED"
    probs = run["stop_reason"]["detail"]["problems"]
    assert probs and probs[-1]["code"] == "SUPPORT_NO_VALID_CANDIDATE"
    assert run["stop_reason"]["message"].startswith("지지점을 자동으로 정하지 못했습니다")
    case = _case(client, cid)
    assert case["tstar"]["support_auto"]["status"] == "BLOCKED" and case["tstar"]["confirmed"]["by"] == "run_all"
    assert case["step_status"]["tstar"]["state"] == "failed" and case["current_support_set_id"] is None
    # 그대로 [이어서 실행] → 같은 사유(재시도 안 함)
    s = _start(client, cid, "tstar")
    assert s["stop_code"] == "SUPPORT_AUTO_BLOCKED" and len(_jobs(client, cid)) == 1
    # 고급 지정(수동 지지점) → 이어서 → ③ 부터 → DONE
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    s = _start(client, cid, "tstar")
    assert s["status"] == "RUNNING" and s["cur_step"] == "esl"
    _step(worker)
    _step(worker)
    assert _ra(client, cid)["status"] == "DONE"


# ---------------------------------------------------------------- V-RA-7·8 입양·실패·중단·재시도
def test_v_ra_8_fail_interrupt_retry_resume(client, synth_inputs, worker_factory, engine, esl_root):
    worker = worker_factory()
    c = _new_chain(client, synth_inputs, "ra08")
    cid = c["id"]
    _step(worker)                                                  # ① → ② → ③ QUEUED
    run = _ra(client, cid)
    esl_job = run["cur_job_id"]
    _fake_end(engine, worker, "FAILED", esl_root, code="CORE_X", msg="가짜 ESL 실패")
    run = _ra(client, cid)
    assert run["status"] == "STOPPED" and run["stop_step"] == "esl" and run["stop_code"] == "STEP_FAILED"
    d = run["stop_reason"]["detail"]
    assert d["job_id"] == esl_job and d["failure_code"] == "CORE_X" and d["job_type"] == "ESL_SOLVE"
    assert run["stop_reason"]["message"] == "③ ESL 작업 실패: CORE_X 가짜 ESL 실패"
    assert worker.run_once("SLOT") is None                         # 다음 작업 안 생김
    # 이어서 → ③ 새로 생성 → 워커 끊김(lease 만료) → 리퍼 → STEP_INTERRUPTED
    s = _start(client, cid, "esl")
    assert s["status"] == "RUNNING" and s["cur_step"] == "esl"
    got = worker.claim("SLOT")
    assert got["id"] == s["cur_job_id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET lease_expires_at = lease_acquired_at + interval '1 millisecond' WHERE id=:j"),
                     {"j": got["id"]})
        conn.execute(text("UPDATE worker_slot SET lease_expires_at = lease_acquired_at + interval '1 millisecond'"))
    worker.reap_once()
    run = _ra(client, cid)
    assert run["status"] == "STOPPED" and run["stop_code"] == "STEP_INTERRUPTED"
    assert run["stop_reason"]["message"] == "워커가 끊겨 작업이 중단되었습니다"
    # 사람이 [재시도](원래 작업) → 성공 → [이어서 실행] → ③ done 건너뜀 → ④
    rr = client.post(f"{API}/jobs/{got['id']}/retry", headers=W)
    assert rr.status_code == 201, rr.text
    _step(worker)
    s = _start(client, cid, "esl")
    assert s["cur_step"] == "validate" and [x["step"] for x in s["skipped"]] == ["esl"]
    _step(worker)
    assert _ra(client, cid)["status"] == "DONE"


def test_v_ra_7_adopt_manual_esl(client, synth_inputs, worker_factory):
    worker = worker_factory()
    r = create_case(client, synth_inputs, folder="ra07", title="ra07")
    cid = r.json()["id"]
    client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W)
    _step(worker)
    case = _case(client, cid)
    assert client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": case["tstar"]["metric"],
                                                        "frame_index": case["tstar"]["frame_index"]},
                      headers=W).status_code == 200
    m = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "ESL_SOLVE", "params": {}},
                    headers=H("tok-power2", True)).json()
    s = _start(client, cid)
    assert s["cur_job_id"] == m["id"] and s["job_ids"] == [{"step": "esl", "job_id": m["id"], "adopted": True}]
    assert len(_jobs(client, cid)) == 2
    _step(worker)                                                  # 입양 작업이 끝나면 ④ 진행
    run = _ra(client, cid)
    assert run["cur_step"] == "validate" and run["job_ids"][-1]["adopted"] is False
    v = client.get(f"{API}/jobs/{run['cur_job_id']}", headers=R).json()
    assert v["job_type"] == "VALIDATE" and v["created_by"] == "u-power" and v["run_all_id"] == run["id"]


# ---------------------------------------------------------------- V-RA-10 취소
def test_v_ra_10_cancel(client, synth_inputs, worker_factory, engine, esl_root):
    worker = worker_factory()
    # QUEUED 작업 → 즉시 CANCELED, 체인 CANCELED
    c = _new_chain(client, synth_inputs, "ra10")
    cid = c["id"]
    r = client.post(f"{API}/cases/{cid}/run-all/cancel", headers=W).json()
    assert r["status"] == "CANCELED" and r["stop_code"] == "RUN_ALL_CANCELED" and r["cur_job_state"] == "CANCELED"
    assert worker.run_once("SLOT") is None
    # RUNNING 작업 → 플래그 → 워커 E7(CANCELED) 뒤 다음 작업 안 생김
    s = _start(client, cid)
    got = worker.claim("SLOT")
    assert got["id"] == s["cur_job_id"]
    r = client.post(f"{API}/cases/{cid}/run-all/cancel", headers=W).json()
    assert r["status"] == "CANCELED" and r["cur_job_state"] == "RUNNING"
    j = client.get(f"{API}/jobs/{got['id']}", headers=R).json()
    assert j["cancel_requested"] is True
    with engine.begin() as conn:
        jobs_repo.release(conn, got["id"], got["lease_token"], "CANCELED", failure_code="CANCELED",
                          run_all_prep=ra.WorkerPrep(str(esl_root)))
    assert worker.run_once("SLOT") is None and _ra(client, cid)["status"] == "CANCELED"
    # 작업만 취소 → 체인 CANCELED JOB_CANCELED
    s = _start(client, cid)
    assert client.post(f"{API}/jobs/{s['cur_job_id']}/cancel", headers=W).status_code == 200
    run = _ra(client, cid)
    assert run["status"] == "CANCELED" and run["stop_code"] == "JOB_CANCELED" and run["canceled_by"] is None
    assert run["stop_reason"]["message"] == "작업이 취소되었습니다"
    # 입양 작업은 취소하지 않음
    m = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    s = _start(client, cid)
    assert s["cur_job_id"] == m["id"] and s["job_ids"][0]["adopted"] is True
    r = client.post(f"{API}/cases/{cid}/run-all/cancel", headers=W).json()
    assert r["status"] == "CANCELED"
    assert client.get(f"{API}/jobs/{m['id']}", headers=R).json()["state"] == "QUEUED"


# ---------------------------------------------------------------- V-RA-15 끊김 복구
def test_v_ra_15_recover_orphaned(client, synth_inputs, worker_factory, engine, monkeypatch):
    from esl_worker import executor

    worker = worker_factory()
    c = _new_chain(client, synth_inputs, "ra15")
    cid = c["id"]
    monkeypatch.setattr(executor.Executor, "_run_all_prep", lambda self, state: None)   # 훅이 진행하지 못한 상황
    st = worker.run_once("SLOT")
    assert st == "SUCCEEDED"
    with engine.connect() as conn:
        assert [r["id"] for r in repo.orphaned(conn)] == [c["run_all"]["id"]]
    run = _ra(client, cid)
    assert run["status"] == "RUNNING" and run["cur_job_state"] == "SUCCEEDED"
    monkeypatch.undo()
    assert worker.recover_run_alls() == [c["run_all"]["id"]]       # 리퍼 1주기
    run = _ra(client, cid)
    assert run["status"] == "RUNNING" and run["cur_step"] == "esl" and run["cur_job_state"] == "QUEUED"
    assert worker.recover_run_alls() == []                         # 행 잠금·cur_job_id 갱신 → 중복 없음
    # 커밋된 종료(FAILED)인데 훅이 없었던 경우도 복구
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state='FAILED', failure_code='X', queue_seq=NULL, finished_at=now() "
                          "WHERE id=:j"), {"j": run["cur_job_id"]})
    worker.reap_once()
    run = _ra(client, cid)
    assert run["status"] == "STOPPED" and run["stop_code"] == "STEP_FAILED"


def test_v_ra_case_changed_and_archived(client, synth_inputs, worker_factory, engine, esl_root):
    """① 성공 훅에서 추출 등록이 그 작업이 아니면 CASE_CHANGED(②)."""
    worker = worker_factory()
    c = _new_chain(client, synth_inputs, "ra16")
    _fake_end(engine, worker, "SUCCEEDED", esl_root)              # 등록 없이 SUCCEEDED(가짜) → extract_summary 없음
    run = _ra(client, c["id"])
    assert run["status"] == "STOPPED" and run["stop_code"] == "CASE_CHANGED" and run["stop_step"] == "tstar"


@pytest.mark.parametrize("bad", ["export"])
def test_v_ra_start_invalid_from(client, synth_inputs, bad):
    r = create_case(client, synth_inputs, folder="ra17", title="ra17")
    assert client.post(f"{API}/cases/{r.json()['id']}/run-all", json={"from": bad}, headers=W).status_code == 422
