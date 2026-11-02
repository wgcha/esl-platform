"""#49 Case 목록 진행 — GET /cases 가 step_status{input,tstar,esl,validate}·library 를 묶음 조회로 함께 준다.

목록 step_status = 상세(GET /cases/{id}) step_status(같은 규칙), 쿼리 수는 Case 수와 무관(상한), 라이브러리 등록 현황
(ACTIVE 항목 수·최신 항목 판정). 계산 없이 DB 행을 심어 시험.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid

from esl_platform.core.db.tables import jobs
from esl_test_support import API, H, create_case
from p2_support import seed_entry, seed_run
from sqlalchemy import event, insert, text

R = H("tok-power")
TS = {"metric": "max_strain", "frame_index": 1, "time": 0.001, "elem_id": 101, "value": 0.01, "source": "user"}


def _job(engine, case_id, job_type, state, *, stage=1, params=None, code=None, msg=None, ago_s=0):
    jid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(insert(jobs).values(
            id=jid, case_id=case_id, project_id="p-1", job_type=job_type, stage=stage, lane="LIGHT", state=state,
            queue_seq=1 if state == "QUEUED" else None, params=params or {}, failure_code=code, failure_message=msg,
            created_by="u-power", created_by_name="파워",
            created_at=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=ago_s)))
    return jid


def _set(engine, case_id, **cols):
    sets = ", ".join(f"{k}=CAST(:{k} AS jsonb)" if k in ("tstar", "extract_summary") else f"{k}=:{k}" for k in cols)
    vals = {k: (json.dumps(v) if k in ("tstar", "extract_summary") else v) for k, v in cols.items()}
    with engine.begin() as c:
        c.execute(text(f"UPDATE cases SET {sets} WHERE id=:id"), {**vals, "id": case_id})


def _done_case(engine, esl_root, c, *, entry=True, **entry_kw):
    s = seed_run(engine, c["id"], verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    _set(engine, c["id"], extract_summary={"job_id": "x", "requested_part_title": c["part_title"]},
         tstar={**TS, "support_auto": {"status": "OK"}}, current_support_set_id=s["support_set_id"],
         current_esl_run_id=s["run_id"])
    from esl_platform.core.inputs import case_inputs_hash
    from esl_platform.core.repositories import cases as cases_repo

    with engine.begin() as conn:                                     # run 이 현재 입력과 일치(stale 아님)
        h = case_inputs_hash(cases_repo.get_case(conn, c["id"]))
        conn.execute(text("UPDATE esl_runs SET inputs_hash=:h WHERE id=:i"), {"h": h, "i": s["run_id"]})
    _job(engine, c["id"], "CASE_EXTRACT", "SUCCEEDED", ago_s=60)
    _job(engine, c["id"], "VALIDATE", "SUCCEEDED", stage=5)
    if entry:
        seed_entry(engine, c["id"], s["run_id"], esl_root=str(esl_root), **entry_kw)
    return s


def _list(client):
    r = client.get(f"{API}/cases", params={"project_id": "p-1"}, headers=R)
    assert r.status_code == 200, r.text
    return {c["id"]: c for c in r.json()}


def test_list_step_status_matches_detail_and_library(client, engine, esl_root, mini_inputs):
    cs = []
    for k in range(5):
        r = create_case(client, mini_inputs, folder=f"lp{k}", title=f"목록 {k}")
        assert r.status_code == 201, r.text
        cs.append(r.json())
    c_done, c_fail, c_run, c_blocked, c_new = cs
    s = _done_case(engine, esl_root, c_done)
    # 라이브러리 묶음 내보내기(origin=library)는 ⑥에도, 목록에도 영향 없음 + 같은 Case 에서 둘째 등록·폐기 항목
    _job(engine, c_done["id"], "EXPORT", "FAILED", stage=6, params={"origin": "library"}, code="EXPORT_FAILED",
         msg="x")
    later = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=1)
    s2 = seed_run(engine, c_done["id"], verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    seed_entry(engine, c_done["id"], s2["run_id"], esl_root=str(esl_root), scene_no=2, scheme=None,
               registered_at=later)
    seed_entry(engine, c_done["id"], s["run_id"], esl_root=str(esl_root), scene_no=3, status="RETIRED")
    # 추출 실패(사유 포함) — 이전 성공보다 최신
    _job(engine, c_fail["id"], "CASE_EXTRACT", "SUCCEEDED", ago_s=120)
    _job(engine, c_fail["id"], "CASE_EXTRACT", "FAILED", code="PART_NOT_FOUND", msg="파트를 찾을 수 없습니다")
    # ESL 실행 중
    _set(engine, c_run["id"], extract_summary={"job_id": "x", "requested_part_title": c_run["part_title"]}, tstar=TS)
    _job(engine, c_run["id"], "ESL_SOLVE", "RUNNING", stage=4)
    # 지지점 자동 선택 실패
    _set(engine, c_blocked["id"], extract_summary={"job_id": "x", "requested_part_title": "다른 파트"},
         tstar={**TS, "support_auto": {"status": "BLOCKED"}})

    lst = _list(client)
    for c in cs:
        det = client.get(f"{API}/cases/{c['id']}", headers=R).json()
        assert lst[c["id"]]["step_status"] == det["step_status"], c["title"]
    st = lambda c: {k: v["state"] for k, v in lst[c["id"]]["step_status"].items()}  # noqa: E731
    assert st(c_done) == {"input": "done", "tstar": "done", "esl": "done", "validate": "done"}
    assert st(c_fail)["input"] == "failed"
    assert lst[c_fail["id"]]["step_status"]["input"]["reason"] == {"code": "PART_NOT_FOUND",
                                                                  "message": "파트를 찾을 수 없습니다"}
    assert st(c_run)["esl"] == "running"
    assert st(c_blocked)["input"] == "stale" and st(c_blocked)["tstar"] == "stale"
    assert st(c_new) == {"input": "none", "tstar": "none", "esl": "none", "validate": "none"}

    lib = lst[c_done["id"]]["library"]
    assert lib["count"] == 2 and lib["latest_status"] == "LEGACY"      # 최신 = 둘째(LEGACY), 폐기 항목 제외
    assert lst[c_new["id"]]["library"] == {"count": 0, "latest_entry_id": None, "latest_status": None,
                                           "latest_registered_at": None}


def test_list_query_count_constant(client, engine, esl_root, mini_inputs):
    def count():
        n = [0]

        def cb(*_a, **_k):
            n[0] += 1

        event.listen(engine, "before_cursor_execute", cb)
        try:
            out = _list(client)
        finally:
            event.remove(engine, "before_cursor_execute", cb)
        return n[0], len(out)

    k = [0]

    def add(n):
        for _ in range(n):
            r = create_case(client, mini_inputs, folder=f"q{k[0]}", title=f"쿼리 {k[0]}")
            k[0] += 1
            assert r.status_code == 201, r.text
            _done_case(engine, esl_root, r.json())

    add(1)
    q1, n1 = count()
    add(6)
    q2, n2 = count()
    assert n2 == n1 + 6 and q1 == q2, (q1, q2)
    assert q1 <= 12, q1
