"""v0.13.0 일괄 실행(계약 esl_run_all.md §4·§6·§8): V-RA-1(evaluate 표, DB 없음)·V-RA-2(새 Case run_all)·V-RA-11(동시 시작)·
V-RA-12(RA-D-7 409)·V-RA-13(권한). 워커 연쇄는 worker/tests/test_run_all_chain.py."""

from __future__ import annotations

import threading

import pytest
from esl_test_support import API, H, create_case

from esl_platform.core import run_all as ra

W = H("tok-power", True)
R = H("tok-power")


# ---------------------------------------------------------------- V-RA-1 evaluate(순수 규칙)
class F:
    def __init__(self, guards=(), g4=(), problems=(), verdict=None):
        self._g, self._g4, self._p, self._v = list(guards), list(g4), list(problems), verdict
        self.calls: list[str] = []

    def guard_reasons(self):
        self.calls.append("guard")
        return self._g + self._g4

    def g4_reasons(self):
        self.calls.append("g4")
        return self._g4

    def blocked_problems(self):
        return self._p

    def verdict(self):
        self.calls.append("verdict")
        return self._v


def ss(**kw):
    base = {s: {"state": "done", "job_id": None} for s in ra.STEPS}
    for k, v in kw.items():
        base[k] = v if isinstance(v, dict) else {"state": v, "job_id": "j-" + k if v == "running" else None}
    return base


NC = {"state": "none", "job_id": None, "reason": {"code": "TSTAR_NOT_CONFIRMED"}}
BL = {"state": "failed", "job_id": None, "reason": {"code": "SUPPORT_AUTO_BLOCKED"}}
G4 = [ra.reason("USER_TSTAR_CHANGED", prev=3, cur=5)]


@pytest.mark.parametrize("step", ["input", "esl"])
@pytest.mark.parametrize("state,kind", [("done", "skip"), ("running", "adopt"), ("none", "create"), ("failed", "create"),
                                        ("stale", "create")])
def test_v_ra_1_job_steps(step, state, kind):
    a = ra.evaluate(ss(**{step: state}), step, F())
    assert a.kind == kind and a.step == step
    if kind == "adopt":
        assert a.job_id == "j-" + step and a.job_type == ra.STEP_JOB[step]
    if kind == "create":
        assert a.job_type == {"input": "CASE_EXTRACT", "esl": "ESL_SOLVE"}[step]


@pytest.mark.parametrize("st,facts,kind,code,key", [
    ("done", F(), "skip", None, None),
    ("done", F(g4=G4), "stop", "TSTAR_REVIEW_REQUIRED", "reasons"),
    (BL, F(problems=[{"code": "SUPPORT_TOO_CLOSE", "message": "가까움"}]), "stop", "SUPPORT_AUTO_BLOCKED", "problems"),
    (NC, F(), "confirm", None, None),
    (NC, F(guards=[ra.reason("TSTAR_ADJUSTED")]), "stop", "TSTAR_REVIEW_REQUIRED", "reasons"),
    (NC, F(guards=[ra.reason("TSTAR_METRIC_ERROR")]), "stop", "TSTAR_REVIEW_REQUIRED", "reasons"),
    (NC, F(guards=[ra.reason("FRAME_NOT_CANDIDATE")]), "stop", "TSTAR_REVIEW_REQUIRED", "reasons"),
    (NC, F(g4=G4), "stop", "TSTAR_REVIEW_REQUIRED", "reasons"),
    ("none", F(), "stop", "PREREQUISITE_MISSING", "missing"),
    ("stale", F(), "stop", "PREREQUISITE_MISSING", "missing"),
    ("running", F(), "stop", "PREREQUISITE_MISSING", "missing"),
    ({"state": "failed", "job_id": "x"}, F(), "stop", "PREREQUISITE_MISSING", "missing"),
])
def test_v_ra_1_tstar(st, facts, kind, code, key):
    a = ra.evaluate(ss(tstar=st), "tstar", facts)
    assert (a.kind, a.code) == (kind, code)
    if key:
        assert a.detail[key]
    if st == "done":
        assert facts.calls == ["g4"]                         # done 은 G4 만


@pytest.mark.parametrize("st,verdict,kind,code", [
    ("done", {"verdict": "PASS", "validation_id": "v1"}, "done", None),
    ("done", {"verdict": "FAIL", "validation_id": "v1", "fail_reasons": ["DISP"]}, "stop", "VALIDATION_FAIL"),
    ("done", {"verdict": "UNDETERMINED", "validation_id": "v1", "undetermined_reason": "NOISE"}, "stop",
     "VALIDATION_UNDETERMINED"),
    ("running", None, "adopt", None), ("none", None, "create", None), ("failed", None, "create", None),
    ("stale", None, "create", None),
])
def test_v_ra_1_validate(st, verdict, kind, code):
    a = ra.evaluate(ss(validate=st), "validate", F(verdict=verdict))
    assert (a.kind, a.code) == (kind, code)
    if kind == "done":
        assert a.verdict == "PASS" and a.detail["validation_id"] == "v1"
    if code:
        assert a.detail["verdict"] == verdict["verdict"] and a.detail["validation_id"] == "v1"


def test_v_ra_1_messages():
    m = ra.stop_message("TSTAR_REVIEW_REQUIRED", "tstar", {"reasons": [ra.reason("TSTAR_ADJUSTED"), *G4]})
    assert m.splitlines() == ["t* 확인이 필요합니다 — ②에서 후보를 보고 [t* 확정]",
                              "1순위 시점이 변위 추출 프레임에 없어 다른 후보로 바뀌었습니다",
                              "직접 고른 t*(frame 3)와 새 자동 t*(frame 5)가 다릅니다"]
    assert ra.stop_message("STEP_FAILED", "esl", {"failure_code": "CORE_X", "failure_message": "boom"}) == \
        "③ ESL 작업 실패: CORE_X boom"
    assert ra.stop_message("PREREQUISITE_MISSING", "esl", {"missing": ["support_set"]}) == "앞 단계가 필요합니다: ② 지지점"
    assert ra.stop_message("VALIDATION_UNDETERMINED", "validate", {"undetermined_reason": "NOISE_FLOOR"}) == \
        "검증 판정 불가 — NOISE_FLOOR"
    assert ra.stop_message("SUPPORT_AUTO_ERROR", "tstar", {"code": "E", "message": "m"}) == "지지점 자동 선택 중 오류: E m"
    assert ra.stop_message("STEP_INTERRUPTED", "input", {}) == "워커가 끊겨 작업이 중단되었습니다"


# ---------------------------------------------------------------- API
def _new(client, mini, folder="ra01", **extra):
    r = create_case(client, mini, folder=folder, title=folder, **extra)
    assert r.status_code == 201, r.text
    return r.json()


def _job(engine, jid):
    from esl_platform.core.repositories import jobs as jobs_repo

    with engine.connect() as c:
        return jobs_repo.get_job(c, jid)


def test_v_ra_2_new_case_run_all(client, mini_inputs, engine):
    c = _new(client, mini_inputs, run_all=True)
    ra_ = c["run_all"]
    assert ra_["status"] == "RUNNING" and ra_["cur_step"] == "input" and ra_["from_step"] == "input"
    assert ra_["cur_job_state"] == "QUEUED" and ra_["job_ids"] == [{"step": "input", "job_id": ra_["cur_job_id"],
                                                                    "adopted": False}]
    assert c.get("run_all_error") is None and ra_["can_resume"] is False and ra_["superseded"] is False
    assert ra_["created_by"] == "u-power" and ra_["created_by_name"] == "파워"
    j = client.get(f"{API}/jobs/{ra_['cur_job_id']}", headers=R).json()
    assert j["job_type"] == "CASE_EXTRACT" and j["run_all_id"] == ra_["id"] and j["created_by"] == "u-power"
    full = client.get(f"{API}/cases/{c['id']}", headers=R).json()
    assert full["run_all"]["id"] == ra_["id"] and full["input_fingerprint"]
    assert client.get(f"{API}/cases/{c['id']}/run-all", headers=R).json()["id"] == ra_["id"]
    lst = client.get(f"{API}/cases/{c['id']}/run-all", params={"all": 1}, headers=R).json()
    assert [x["id"] for x in lst] == [ra_["id"]]
    hist = client.get(f"{API}/history", params={"project_id": "p-1", "case_id": c["id"]}, headers=R).json()
    assert hist["items"][0]["run_all_id"] == ra_["id"]
    rv = client.get(f"{API}/jobs/{ra_['cur_job_id']}/review", headers=R)
    assert rv.status_code == 200 and rv.json()["job"]["run_all_id"] == ra_["id"]
    # 기본(run_all 생략) = 시작 안 함
    c2 = _new(client, mini_inputs, folder="ra02")
    assert c2["run_all"] is None and client.get(f"{API}/cases/{c2['id']}/run-all", headers=R).json() is None


def test_v_ra_2_run_all_error_keeps_case(client, mini_inputs, monkeypatch):
    from esl_platform.api.services import run_all as svc
    from esl_platform.core.errors import conflict

    def boom(*a, **k):
        raise conflict("RUN_ALL_ACTIVE", "x")
    monkeypatch.setattr(svc, "start", boom)
    c = _new(client, mini_inputs, run_all=True)
    assert c["run_all"] is None and c["run_all_error"] == {"code": "RUN_ALL_ACTIVE", "message": "x"}
    assert client.get(f"{API}/cases/{c['id']}", headers=R).status_code == 200


def test_v_ra_start_validation(client, mini_inputs):
    c = _new(client, mini_inputs)
    r = client.post(f"{API}/cases/{c['id']}/run-all", json={"from": "esl"}, headers=W)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "PREREQUISITE_MISSING" and d["missing"] == ["input", "tstar"]
    assert client.post(f"{API}/cases/{c['id']}/run-all", json={"from": "export"}, headers=W).status_code == 422
    assert client.post(f"{API}/cases/nope/run-all", json={}, headers=W).status_code == 404
    assert client.post(f"{API}/cases/{c['id']}/run-all/cancel", headers=W).json()["detail"]["code"] == \
        "RUN_ALL_NOT_RUNNING"
    r = client.post(f"{API}/cases/{c['id']}/run-all", headers=W)          # body 없음 = from input
    assert r.status_code == 201 and r.json()["status"] == "RUNNING"


def test_v_ra_11_concurrent_start(client, mini_inputs, engine):
    c = _new(client, mini_inputs)
    out: list = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        r = client.post(f"{API}/cases/{c['id']}/run-all", json={}, headers=W)
        out.append((r.status_code, r.json()))
    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    codes = sorted(s for s, _ in out)
    assert codes == [201, 409], out
    assert next(b for s, b in out if s == 409)["detail"]["code"] == "RUN_ALL_ACTIVE"
    jobs = client.get(f"{API}/cases/{c['id']}/jobs", headers=R).json()
    assert len(jobs) == 1 and jobs[0]["job_type"] == "CASE_EXTRACT"
    # DB 최종 보장: RUNNING 2행 금지
    from sqlalchemy.exc import IntegrityError

    from esl_platform.core.repositories import run_all as repo
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            repo.insert_run(conn, case_id=c["id"], project_id="p-1", from_step="input", core_settings={},
                            created_by="u", created_by_name="u")


def test_v_ra_12_guard_409(client, mini_inputs, engine, worker_factory):
    from esl_platform.core.repositories import jobs as jobs_repo

    c = _new(client, mini_inputs)
    cid = c["id"]
    # 실패한 CASE_EXTRACT 1개(재시도 대상) — 가짜 워커가 claim 후 FAILED
    j = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    w = worker_factory()
    got = w.claim("SLOT")
    with engine.begin() as conn:
        jobs_repo.release(conn, got["id"], got["lease_token"], "FAILED", failure_code="X", failure_message="x")
    run = client.post(f"{API}/cases/{cid}/run-all", json={}, headers=W).json()
    assert run["status"] == "RUNNING"
    ver = client.get(f"{API}/cases/{cid}", headers=R).json()["version"]

    def code(r):
        return r.status_code, (r.json().get("detail") or {}).get("code") if r.status_code >= 400 else None
    assert code(client.put(f"{API}/cases/{cid}/tstar", json={"version": ver, "metric": "max_strain", "frame_index": 1},
                           headers=W)) == (409, "RUN_ALL_ACTIVE")
    for jt in ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE"):
        assert code(client.post(f"{API}/cases/{cid}/jobs", json={"job_type": jt, "params": {}}, headers=W)) == \
            (409, "RUN_ALL_ACTIVE"), jt
    assert code(client.post(f"{API}/cases/{cid}/archive", headers=W)) == (409, "RUN_ALL_ACTIVE")
    assert code(client.post(f"{API}/jobs/{j['id']}/retry", headers=W)) == (409, "RUN_ALL_ACTIVE")
    assert code(client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": [1, 2, 3]}, headers=W)) == \
        (409, "RUN_ALL_ACTIVE")
    assert code(client.patch(f"{API}/cases/{cid}", json={"version": ver, "part_title": "다른 파트"}, headers=W)) == \
        (409, "RUN_ALL_ACTIVE")
    assert code(client.post(f"{API}/cases/{cid}/run-all", json={}, headers=W)) == (409, "RUN_ALL_ACTIVE")
    # 허용: 제목 변경·보고서(사전조건 409 는 RUN_ALL_ACTIVE 아님)·조회
    r = client.patch(f"{API}/cases/{cid}", json={"version": ver, "title": "새 제목"}, headers=W)
    assert r.status_code == 200, r.text
    assert code(client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_REPORT", "params": {}}, headers=W)) == \
        (409, "PREREQUISITE_MISSING")
    assert client.get(f"{API}/cases/{cid}/artifacts", headers=R).status_code == 200
    # 취소 뒤에는 다시 가능
    assert client.post(f"{API}/cases/{cid}/run-all/cancel", headers=W).json()["status"] == "CANCELED"
    assert client.post(f"{API}/jobs/{j['id']}/retry", headers=W).status_code == 201


def test_v_ra_13_permissions(client, mini_inputs):
    c = _new(client, mini_inputs)
    cid = c["id"]
    r = client.post(f"{API}/cases/{cid}/run-all", json={}, headers=H("tok-general", True))
    assert r.status_code == 403
    assert client.post(f"{API}/cases/{cid}/run-all", json={}, headers=W).status_code == 201
    assert client.get(f"{API}/cases/{cid}/run-all", headers=H("tok-general")).status_code == 200
    assert client.post(f"{API}/cases/{cid}/run-all/cancel", headers=H("tok-power2", True)).status_code == 403
    assert client.post(f"{API}/cases/{cid}/run-all/cancel", headers=H("tok-general", True)).status_code == 403
    r = client.post(f"{API}/cases/{cid}/run-all/cancel", headers=H("tok-admin", True))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "CANCELED" and d["canceled_by"] == "u-admin" and d["stop_code"] == "RUN_ALL_CANCELED"
    assert d["stop_step"] == "input" and d["stop_reason"]["message"] == "일괄 실행을 취소했습니다"
    assert d["cur_job_state"] == "CANCELED"                     # 체인이 만든 QUEUED 작업 → 즉시 CANCELED
