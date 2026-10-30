"""P3-이력 백엔드 시험(계약 esl_p3_history.md §6 V-H-1~11 중 백엔드): 목록·커서·필터·시간·결과 상태·diff·상세·권한·
`_backup` 표식 탐색·보존 파일 API·migration 0007·성능(10만 행). 작업·Case 는 DB 에 직접 심는다(계산 없음)."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from esl_test_support import API, REPO, H
from p2_support import write_compare_field
from sqlalchemy import event, insert, null, text, update

from esl_platform.core.db.tables import (
    analysis_runs,
    cases,
    comparisons,
    esl_runs,
    job_steps,
    jobs,
    support_sets,
    validations,
)
from esl_platform.core.inputs import inputs_hash
from esl_platform.core.job_types import JOB_TYPES

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
R = H("tok-general")            # 일반 사용자(p-1 general) — 조회는 누구나
RA = H("tok-admin")
RP = H("tok-power")
RN = H("tok-nonmember")         # 다른 프로젝트 멤버


def ts(n: float) -> dt.datetime:
    return T0 + dt.timedelta(seconds=n)


def code(r) -> str:
    return r.json()["detail"]["code"]


# ---------------------------------------------------------------- 시드
class World:
    """DB 에 직접 Case·작업·ESL 실행·검증을 심는 도우미."""

    def __init__(self, engine, esl_root: Path) -> None:
        self.engine, self.root = engine, esl_root
        self._seq = 0

    def case(self, folder: str, *, title: str | None = None, project_id: str = "p-1", part_title: str = "chassis rear",
             **kw: Any) -> dict[str, Any]:
        cid = str(uuid.uuid4())
        row = dict(id=cid, project_id=project_id, folder_name=folder, title=title or f"Case {folder}",
                   rad_path="/x/a.rad", results_dir="/x/csv", input_fingerprint={}, part_title=part_title,
                   created_by="u-power", created_by_name="파워")
        row.update(kw)
        with self.engine.begin() as c:
            c.execute(insert(cases).values(**row))
        (self.root / folder).mkdir(parents=True, exist_ok=True)
        return {"id": cid, "folder": folder, "dir": self.root / folder, "project_id": project_id}

    def job(self, *, case_id: str | None = None, job_type: str = "CASE_EXTRACT", state: str = "SUCCEEDED",
            created: float = 0, queued: float | None = None, started: float | None = None,
            finished: float | None = None, params: dict | None = None, result: dict | None = None,
            retry_of: str | None = None, created_by: str = "u-power", jid: str | None = None,
            project_id: str = "p-1", analysis_id: str | None = None, comparison_id: str | None = None,
            failure_code: str | None = None, failure_message: str | None = None, warnings: list | None = None,
            steps: list[dict] | None = None, created_at: dt.datetime | None = None) -> str:
        jid = jid or str(uuid.uuid4())
        d = JOB_TYPES[job_type]
        self._seq += 1
        row: dict[str, Any] = dict(
            id=jid, case_id=case_id, analysis_id=analysis_id, comparison_id=comparison_id, project_id=project_id,
            job_type=job_type, stage=d.stage, lane=d.lane, state=state, holds_slot=state == "RUNNING" and d.lane == "SLOT",
            params=params if params is not None else {}, result=result, warnings=warnings or [],
            created_by=created_by, created_by_name=created_by, created_at=created_at or ts(created),
            queued_at=ts(queued) if queued is not None else None, started_at=ts(started) if started is not None else None,
            finished_at=ts(finished) if finished is not None else None, retry_of_job_id=retry_of,
            failure_code=failure_code or ("X_FAIL" if state in ("FAILED", "INTERRUPTED") else None),
            failure_message=failure_message)
        if state == "QUEUED":
            row["queue_seq"] = 1000 + self._seq
        with self.engine.begin() as c:
            c.execute(insert(jobs).values(**row))
            for i, s in enumerate(steps or [], 1):
                c.execute(insert(job_steps).values(
                    id=str(uuid.uuid4()), job_id=jid, step_no=i, step_key=s.get("key", f"S{i}"), kind="INTERNAL",
                    core_stage=s.get("stage"), state=s.get("state", "SUCCEEDED"),
                    started_at=ts(s["started"]) if "started" in s else None,
                    finished_at=ts(s["finished"]) if "finished" in s else None, exit_code=s.get("exit_code"),
                    log_rel=s.get("log_rel"), failure_code=s.get("failure_code"),
                    failure_message=s.get("failure_message"), command=s.get("command")))
        return jid

    def support(self, case_id: str, nodes=(1, 2, 3)) -> str:
        sid = str(uuid.uuid4())
        with self.engine.begin() as c:
            c.execute(insert(support_sets).values(id=sid, case_id=case_id, node_ids=list(nodes),
                                                  dofs=["123", "13", "1"], source="auto", created_by="u-power"))
        return sid

    def set_case(self, case_id: str, **vals: Any) -> None:
        vals = {k: (null() if v is None else v) for k, v in vals.items()}
        with self.engine.begin() as c:
            c.execute(update(cases).where(cases.c.id == case_id).values(**vals))

    def extract(self, case: dict, *, created: float = 10, part_title: str = "chassis rear", n_elems: int = 100,
                make_current: bool = True, tstar: dict | None = None) -> str:
        ex = {"part_title": part_title, "n_elems": n_elems, "n_frames": 10}
        ts_ = tstar or {"metric": "max_strain", "frame_index": 5, "time": 0.005, "elem_id": 3, "value": 0.01,
                        "source": "auto"}
        jid = self.job(case_id=case["id"], job_type="CASE_EXTRACT", created=created, queued=created, started=created + 1,
                       finished=created + 5, params={"part_title": part_title},
                       result={"registered": {"extract": ex, "tstar": ts_}},
                       steps=[{"key": "EXTRACT", "started": created + 1, "finished": created + 3}])
        if make_current:
            self.set_case(case["id"], extract_summary={"job_id": jid, "requested_part_title": part_title, **ex},
                          tstar=ts_)
        return jid

    def esl(self, case: dict, extract_job_id: str, support_id: str, *, created: float = 20, part_title="chassis rear",
            frame: int = 5, metric: str = "max_strain", make_current: bool = True, forces: dict | None = None,
            kabsch: dict | None = None) -> dict[str, str]:
        h = inputs_hash(extract_job_id=extract_job_id, part_title=part_title,
                        tstar={"frame_index": frame, "metric": metric}, support_set_id=support_id)
        jid = self.job(case_id=case["id"], job_type="ESL_SOLVE", created=created, queued=created, started=created + 1,
                       finished=created + 9, params={"settings": {"case": {"part_title": part_title},
                                                                 "tstar": {"metric": metric}}, "frame_index": frame,
                                                    "metric": metric, "support_set_id": support_id, "inputs_hash": h})
        rid = str(uuid.uuid4())
        with self.engine.begin() as c:
            c.execute(insert(esl_runs).values(
                id=rid, case_id=case["id"], job_id=jid, frame_index=frame, metric=metric, support_set_id=support_id,
                kabsch=kabsch or {"rot_deg": 0.1, "rms_def": 1e-4, "max_def": 2e-4},
                forces=forces or {"sum_abs_f": 123.0}, supports=[], dir_rel=f"runs/{rid}", status="READY",
                inputs_hash=h, created_at=ts(created + 9)))
            if make_current:
                c.execute(update(cases).where(cases.c.id == case["id"]).values(current_esl_run_id=rid))
        return {"job_id": jid, "run_id": rid}

    def validate(self, case: dict, run_id: str, *, created: float = 30, verdict: str = "PASS",
                 disp: float = 0.002, hotspots: list | None = None, criteria: dict | None = None) -> dict[str, str]:
        jid = self.job(case_id=case["id"], job_type="VALIDATE", created=created, queued=created, started=created + 1,
                       finished=created + 9, params={"esl_run_id": run_id})
        vid = str(uuid.uuid4())
        with self.engine.begin() as c:
            c.execute(insert(validations).values(
                id=vid, esl_run_id=run_id, case_id=case["id"], job_id=jid, disp_rms_rel=disp, reaction_rel=1e-9,
                hotspots=hotspots if hotspots is not None else [{"elem_id": 1, "rel_err": -0.04},
                                                                {"elem_id": 2, "rel_err": 0.02}],
                verdict=verdict, criteria=criteria or {"disp_rms_rel_max": 0.01}, dir_rel="05_val",
                created_at=ts(created + 9)))
        return {"job_id": jid, "validation_id": vid}

    def export(self, case: dict, run_id: str, *, created: float = 40, targets=("radioss_inc",), files=("a.inc", "b.inc"),
               verdict: str | None = "PASS", id_range=(9000000, 9000100)) -> str:
        return self.job(case_id=case["id"], job_type="EXPORT", created=created, queued=created, started=created + 1,
                        finished=created + 4, params={"esl_run_id": run_id, "targets": list(targets)},
                        result={"registered": {"export_dir": "06_export", "files": list(files),
                                               "targets": list(targets), "id_range": list(id_range),
                                               "validation_verdict": verdict, "warnings": ["w1"]}})

    def report(self, case: dict, run_id: str | None, *, created: float = 50) -> str:
        return self.job(case_id=case["id"], job_type="CASE_REPORT", created=created, queued=created, started=created + 1,
                        finished=created + 2, params={"esl_run_id": run_id, "validation_id": None},
                        result={"registered": {"report_rel": "07_report/report.html", "bytes": 4321, "verdict": "PASS"}})


@pytest.fixture()
def world(engine, esl_root):
    return World(engine, esl_root)


def hist(client, hdr=R, **params):
    params.setdefault("project_id", "p-1")
    return client.get(f"{API}/history", params=params, headers=hdr)


def by_id(r) -> dict[str, dict]:
    assert r.status_code == 200, r.text
    return {i["id"]: i for i in r.json()["items"]}


def baseline(world: World, folder: str = "c1"):
    """추출 E1 → 지지점 S1 → ESL → 검증 → 내보내기 → 보고서, 모두 현재."""
    c = world.case(folder)
    sid = world.support(c["id"])
    world.set_case(c["id"], current_support_set_id=sid)
    e1 = world.extract(c)
    esl = world.esl(c, e1, sid)
    val = world.validate(c, esl["run_id"])
    ex = world.export(c, esl["run_id"])
    rep = world.report(c, esl["run_id"])
    return c, dict(sid=sid, e1=e1, esl=esl, val=val, ex=ex, rep=rep)


# ================================================================ V-H-1 범위·정렬·커서
def test_h1_scope_order_cursor(client, world):
    c1 = world.case("c1")
    c2 = world.case("c2")
    other = world.case("o1", project_id="p-2")
    ids_c1 = [world.job(case_id=c1["id"], created=i) for i in range(5)]
    ids_c2 = [world.job(case_id=c2["id"], job_type="CASE_REPORT", created=i + 0.5) for i in range(3)]
    world.job(case_id=other["id"], project_id="p-2", created=1)
    # 프로젝트 범위 + 정렬(created_at desc)
    r = hist(client)
    assert r.status_code == 200
    got = [i["id"] for i in r.json()["items"]]
    assert set(got) == set(ids_c1 + ids_c2) and len(got) == 8
    created = [i["created_at"] for i in r.json()["items"]]
    assert created == sorted(created, reverse=True)
    assert r.json()["has_more"] is False and r.json()["next_cursor"] is None
    # case_id 범위, 다른 프로젝트의 case_id 는 404 CASE_NOT_FOUND
    assert {i["id"] for i in hist(client, case_id=c1["id"]).json()["items"]} == set(ids_c1)
    r = hist(client, case_id=other["id"])
    assert r.status_code == 404 and code(r) == "CASE_NOT_FOUND"
    assert hist(client, case_id=str(uuid.uuid4())).status_code == 404
    assert {i["id"] for i in hist(client, project_id="p-2").json()["items"]} != set()
    assert hist(client, project_id="").status_code == 422
    # project_id 필수
    assert client.get(f"{API}/history", headers=R).status_code == 422
    # 항목 필드
    it = hist(client, case_id=c1["id"]).json()["items"][0]
    assert it["case_title"] == "Case c1" and it["case_folder"] == "c1" and it["subject_title"] == "Case c1"
    assert it["created_by_name"] and "params" not in it and "result" not in it and "steps" not in it


def test_h1_cursor_no_gap_no_dup_same_created_at(client, world):
    c = world.case("c1")
    same = dt.datetime(2026, 10, 2, tzinfo=UTC)
    all_ids = []
    for i in range(23):             # 같은 created_at 이 한 페이지(7) 이상
        all_ids.append(world.job(case_id=c["id"], job_type="CASE_REPORT", state="FAILED", created_at=same))
    for i in range(9):
        all_ids.append(world.job(case_id=c["id"], job_type="EXPORT", state="CANCELED", created_at=same + dt.timedelta(
            seconds=i % 3)))
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 7}
        if cursor:
            params["cursor"] = cursor
        r = hist(client, **params)
        assert r.status_code == 200, r.text
        body = r.json()
        seen += [i["id"] for i in body["items"]]
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        assert body["next_cursor"] and len(body["items"]) == 7
        cursor = body["next_cursor"]
    assert pages == 5 and len(seen) == len(set(seen)) == len(all_ids) and set(seen) == set(all_ids)
    # 전체 순서 = (created_at desc, id desc)
    full = hist(client, limit=200).json()["items"]
    keys = [(i["created_at"], i["id"]) for i in full]
    assert keys == sorted(keys, reverse=True)
    assert [i["id"] for i in full] == seen


# ================================================================ V-H-2 필터·오류
def test_h2_filters_and_errors(client, world):
    c1 = world.case("alpha", title="낙하 시험 A")
    c2 = world.case("beta_case", title="Bracket")
    a = world.job(case_id=c1["id"], job_type="CASE_EXTRACT", state="SUCCEEDED", created=10, created_by="u-power")
    b = world.job(case_id=c1["id"], job_type="ESL_SOLVE", state="FAILED", created=20, created_by="u-power2")
    c = world.job(case_id=c2["id"], job_type="EXPORT", state="CANCELED", created=30, created_by="u-power")
    d = world.job(case_id=c2["id"], job_type="CASE_REPORT", state="INTERRUPTED", created=40, created_by="u-admin")
    # 라이브러리 작업
    an = str(uuid.uuid4())
    cm = str(uuid.uuid4())
    with world.engine.begin() as cn:
        cn.execute(insert(analysis_runs).values(id=an, project_id="p-1", title="종합분석 가을", filters={}, options={},
                                                entry_ids=["e1"], dir_rel=f"_analysis/{an}", created_by="u-power",
                                                created_by_name="p"))
        cn.execute(insert(comparisons).values(id=cm, project_id="p-1", title="비교 v1-v2", model="M", base_version="v1",
                                              new_version="v2", filters={}, options={}, base_entry_ids=["e1"],
                                              new_entry_ids=["e2"], n_paired=1, dir_rel=f"_compare/{cm}",
                                              created_by="u-power", created_by_name="p"))
    e = world.job(job_type="LIB_ANALYZE", analysis_id=an, created=50)
    f = world.job(job_type="LIB_COMPARE", comparison_id=cm, created=60)

    def ids(hdr=R, **p):
        r = hist(client, hdr, **p)
        assert r.status_code == 200, (p, r.text)
        return {i["id"] for i in r.json()["items"]}

    assert ids(job_type="CASE_EXTRACT,EXPORT") == {a, c}
    assert ids(job_type="LIB_ANALYZE,LIB_COMPARE") == {e, f}
    assert ids(state="FAILED,INTERRUPTED") == {b, d}
    assert ids(state="SUCCEEDED") == {a, e, f}
    assert ids(job_type="ESL_SOLVE", state="FAILED") == {b}
    # mine: 요청자 본인 작업만(tok-power = u-power)
    assert ids(RP, mine="true") == {a, c, e, f} and ids(RA, mine="true") == {d} and ids(R, mine="true") == set()
    r = client.get(f"{API}/history", params={"project_id": "p-1", "mine": "true"}, headers=H("tok-power2"))
    assert {i["id"] for i in r.json()["items"]} == {b}
    # q: Case 제목·폴더명 부분 일치(대소문자 무시), 분석·비교 제목, 작업 id 접두 8자 이상
    assert ids(q="낙하") == {a, b}
    assert ids(q="BETA") == {c, d}
    assert ids(q="brack") == {c, d}
    assert ids(q="종합분석") == {e}
    assert ids(q="v1-v2") == {f}
    assert ids(q=a[:8]) == {a} and ids(q=a[:12].upper()) == {a}
    assert ids(q=a[:7]) == set()                                   # 7자는 id 접두로 보지 않음
    assert ids(q="%") == set() and ids(q="b_t") == set() and ids(q="_") == {c, d}   # LIKE 와일드카드는 문자로
    assert ids(q="x" * 100) == set()
    # from/to (created_at)
    assert ids(**{"from": ts(25).isoformat(), "to": ts(45).isoformat()}) == {c, d}
    assert ids(**{"from": ts(35).isoformat()}) == {d, e, f}
    assert ids(to=ts(10).isoformat()) == {a}
    # 잘못된 값
    for bad in ({"job_type": "NOPE"}, {"state": "DONE"}, {"state": "FAILED,NOPE"}, {"q": "x" * 101},
                {"from": "yesterday"}, {"limit": 0}, {"limit": 201}, {"limit": "x"}, {"mine": "maybe"}):
        r = hist(client, **bad)
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", (bad, r.status_code, r.text)
    assert len(hist(client, limit=200).json()["items"]) == 6
    assert hist(client, limit=1).json()["has_more"] is True


def test_h2_cursor_forged(client, world):
    import base64

    c = world.case("c1")
    for i in range(5):
        world.job(case_id=c["id"], created=i)
    good = hist(client, limit=2).json()["next_cursor"]
    assert hist(client, limit=2, cursor=good).status_code == 200
    forged = [
        "garbage", "", "!!!", good[:-3] + "AAA", good + "x",
        base64.urlsafe_b64encode(b'{"t":"2026-10-01T00:00:00+00:00","i":"abc"}').decode().rstrip("="),
        base64.urlsafe_b64encode(b"deadbeef.{}").decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps({"t": "x", "i": 1}).encode()).decode(),
        "A" * 600,
    ]
    for cur in forged:
        r = hist(client, cursor=cur)
        if cur == "":      # 빈 값은 커서 없음과 같다
            assert r.status_code == 200
            continue
        assert r.status_code == 422 and code(r) == "INVALID_CURSOR", (cur[:30], r.status_code, r.text)


# ================================================================ V-H-3 시간·재시도 연결
def test_h3_durations_and_retry_links(client, world):
    c = world.case("c1")
    queued = world.job(case_id=c["id"], job_type="EXPORT", state="QUEUED", created=1, queued=2)
    running = world.job(case_id=c["id"], job_type="CASE_EXTRACT", state="RUNNING", created=3, queued=4, started=5)
    done = world.job(case_id=c["id"], job_type="ESL_SOLVE", created=6, queued=7, started=10, finished=25.5)
    canceled = world.job(case_id=c["id"], job_type="VALIDATE", state="CANCELED", created=8, queued=8, finished=9)
    bare = world.job(case_id=c["id"], job_type="CASE_REPORT", state="FAILED", created=9)
    items = by_id(hist(client))
    assert items[queued]["duration_s"] is None and items[queued]["wait_s"] is None
    assert items[done]["wait_s"] == 3.0 and items[done]["duration_s"] == 15.5
    assert items[canceled]["duration_s"] is None and items[canceled]["wait_s"] is None
    assert items[bare]["duration_s"] is None and items[bare]["wait_s"] is None and items[bare]["queued_at"] is None
    # 실행 중: duration = DB now − started (T0 는 과거라 양수·큼), wait = started − queued
    assert items[running]["wait_s"] == 1.0 and items[running]["duration_s"] > 1e6 and items[running]["finished_at"] is None
    # 재시도 연결(가장 최근 재시도), 원본 연결
    r1 = world.job(case_id=c["id"], job_type="CASE_REPORT", state="FAILED", created=100, retry_of=bare)
    r2 = world.job(case_id=c["id"], job_type="CASE_REPORT", state="FAILED", created=110, retry_of=bare)
    r3 = world.job(case_id=c["id"], job_type="CASE_REPORT", state="SUCCEEDED", created=120, retry_of=r2,
                   result={"registered": {}})
    items = by_id(hist(client))
    assert items[bare]["retried_by_job_id"] == r2 and items[bare]["retry_of_job_id"] is None
    assert items[r1]["retry_of_job_id"] == bare and items[r1]["retried_by_job_id"] is None
    assert items[r2]["retried_by_job_id"] == r3 and items[r3]["retry_of_job_id"] == r2
    assert items[done]["retried_by_job_id"] is None
    # 진행 표시
    assert items[running]["current_step_no"] is None and items[running]["failure_code"] is None
    assert items[bare]["failure_code"] == "X_FAIL"


# ================================================================ V-H-4 result_state · stale_reasons
def reasons(client, jid) -> list[str]:
    r = client.get(f"{API}/jobs/{jid}/review", headers=R)
    assert r.status_code == 200, r.text
    return r.json()["result"]["stale_reasons"]


def test_h4_all_current(client, world):
    c, ids = baseline(world)
    items = by_id(hist(client, case_id=c["id"]))
    for k in ("e1",):
        it = items[ids[k]]
        assert it["result_state"] == "current" and it["stale"] is False and it["result_ref"] == {
            "kind": "extract", "id": ids["e1"]}
    assert items[ids["esl"]["job_id"]]["result_ref"] == {"kind": "esl_run", "id": ids["esl"]["run_id"]}
    assert items[ids["val"]["job_id"]]["result_ref"] == {"kind": "validation", "id": ids["val"]["validation_id"]}
    assert items[ids["ex"]]["result_ref"] == {"kind": "export", "id": ids["ex"]}
    assert items[ids["rep"]]["result_ref"] == {"kind": "report", "id": ids["rep"]}
    for it in items.values():
        assert it["result_state"] == "current" and it["stale"] is False, it
    # 요약 한 줄
    assert items[ids["e1"]]["summary"] == {"n_elems": 100, "tstar_frame": 5, "tstar_value": 0.01}
    assert items[ids["esl"]["job_id"]]["summary"] == {"frame_index": 5, "metric": "max_strain"}
    assert items[ids["val"]["job_id"]]["summary"] == {"status": "LEGACY", "verdict": "PASS", "disp_rms_rel": 0.002,
                                                       "disp_max_rel": None}
    assert items[ids["ex"]]["summary"] == {"targets": ["radioss_inc"], "n_files": 2}
    assert items[ids["rep"]]["summary"] is None


def test_h4_reextract(client, world):
    c, ids = baseline(world)
    e2 = world.extract(c, created=60, n_elems=120)          # 재추출 → 현재 추출 = e2
    items = by_id(hist(client, case_id=c["id"]))
    assert items[e2]["result_state"] == "current" and items[e2]["stale"] is False
    assert items[ids["e1"]]["result_state"] == "past" and items[ids["e1"]]["stale"] is True
    for jid in (ids["esl"]["job_id"], ids["val"]["job_id"], ids["ex"], ids["rep"]):
        assert "extract" in reasons(client, jid), jid
    assert reasons(client, ids["e1"]) == ["extract"]
    assert items[ids["esl"]["job_id"]]["result_state"] == "past" and items[ids["esl"]["job_id"]]["stale"] is True


def test_h4_part_title(client, world):
    c, ids = baseline(world)
    world.set_case(c["id"], part_title="chassis front")
    assert reasons(client, ids["esl"]["job_id"]) == ["part_title"]
    assert reasons(client, ids["e1"]) == ["part_title"]
    assert reasons(client, ids["ex"]) == ["part_title"]
    items = by_id(hist(client, case_id=c["id"]))
    assert items[ids["esl"]["job_id"]]["result_state"] == "past" and items[ids["esl"]["job_id"]]["stale"] is True
    # 검증은 "현재 run 의 최신 검증"이라 state 는 current, 입력 바뀜 칩만
    assert items[ids["val"]["job_id"]]["result_state"] == "current" and items[ids["val"]["job_id"]]["stale"] is True


def test_h4_tstar_change(client, world):
    c, ids = baseline(world)
    world.set_case(c["id"], tstar={"metric": "max_strain", "frame_index": 7, "value": 0.02, "source": "user"})
    assert reasons(client, ids["esl"]["job_id"]) == ["tstar"]
    assert reasons(client, ids["val"]["job_id"]) == ["tstar"]
    assert reasons(client, ids["e1"]) == []                      # 추출 자체는 t* 확정과 무관
    world.set_case(c["id"], tstar={"metric": "plastic_strain", "frame_index": 5, "value": 0.02, "source": "user"})
    assert reasons(client, ids["esl"]["job_id"]) == ["tstar"]
    world.set_case(c["id"], tstar=None)
    assert reasons(client, ids["esl"]["job_id"]) == ["tstar"]


def test_h4_support_set_change(client, world):
    c, ids = baseline(world)
    s2 = world.support(c["id"], (4, 5, 6))
    world.set_case(c["id"], current_support_set_id=s2)
    assert reasons(client, ids["esl"]["job_id"]) == ["support_set"]
    assert reasons(client, ids["ex"]) == ["support_set"]
    assert reasons(client, ids["e1"]) == []


def test_h4_input_files_change(client, world, tmp_path):
    c, ids = baseline(world)
    f = tmp_path / "in.rad"
    f.write_text("abc")
    st = f.stat()
    world.set_case(c["id"], input_fingerprint={"rad": {"path": str(f), "size": st.st_size, "mtime": st.st_mtime},
                                               "includes": [], "results": None})
    assert reasons(client, ids["esl"]["job_id"]) == [] and reasons(client, ids["e1"]) == []
    f.write_text("abcdef")                                         # 입력 파일이 바뀜
    for jid in (ids["e1"], ids["esl"]["job_id"], ids["val"]["job_id"], ids["ex"], ids["rep"]):
        assert reasons(client, jid) == ["input_files"], jid
    it = by_id(hist(client, case_id=c["id"]))[ids["e1"]]
    assert it["stale"] is True and it["result_state"] == "current"
    f.unlink()                                                     # 사라져도 바뀜
    assert reasons(client, ids["esl"]["job_id"]) == ["input_files"]


def test_h4_past_runs_and_non_results(client, world):
    c, ids = baseline(world)
    # 새 ESL 실행이 현재가 되면 이전 ESL·검증·내보내기는 past
    esl2 = world.esl(c, ids["e1"], ids["sid"], created=70, frame=5)
    val2 = world.validate(c, esl2["run_id"], created=80)
    ex2 = world.export(c, esl2["run_id"], created=90)
    items = by_id(hist(client, case_id=c["id"]))
    assert items[ids["esl"]["job_id"]]["result_state"] == "past" and items[esl2["job_id"]]["result_state"] == "current"
    assert items[ids["val"]["job_id"]]["result_state"] == "past" and items[val2["job_id"]]["result_state"] == "current"
    assert items[ids["ex"]]["result_state"] == "past" and items[ex2]["result_state"] == "current"
    # 같은 run 의 새 검증이 생기면 이전 검증은 past
    val3 = world.validate(c, esl2["run_id"], created=100)
    items = by_id(hist(client, case_id=c["id"]))
    assert items[val2["job_id"]]["result_state"] == "past" and items[val3["job_id"]]["result_state"] == "current"
    # 실패·취소·대기·실행 중은 결과 없음
    failed = world.job(case_id=c["id"], job_type="ESL_SOLVE", state="FAILED", created=110)
    running = world.job(case_id=c["id"], job_type="VALIDATE", state="RUNNING", created=111, started=112)
    items = by_id(hist(client, case_id=c["id"]))
    for j in (failed, running):
        assert items[j]["result_ref"] is None and items[j]["result_state"] is None and items[j]["stale"] is False
        assert items[j]["summary"] is None


def test_h4_library_jobs(client, world):
    an = str(uuid.uuid4())
    with world.engine.begin() as cn:
        cn.execute(insert(analysis_runs).values(id=an, project_id="p-1", title="A", filters={}, options={},
                                                entry_ids=["e"], dir_rel=f"_analysis/{an}", created_by="u",
                                                created_by_name="u"))
    j1 = world.job(job_type="LIB_ANALYZE", analysis_id=an, created=10, result={"registered": {"n_cases": 3}})
    with world.engine.begin() as cn:
        cn.execute(update(analysis_runs).where(analysis_runs.c.id == an).values(job_id=j1))
    j2 = world.job(job_type="LIB_ANALYZE", analysis_id=an, created=20, result={"registered": {"n_cases": 4}})
    with world.engine.begin() as cn:
        cn.execute(update(analysis_runs).where(analysis_runs.c.id == an).values(job_id=j2))
    items = by_id(hist(client))
    assert items[j1]["result_ref"] == {"kind": "analysis", "id": an} and items[j1]["result_state"] == "past"
    assert items[j2]["result_state"] == "current" and items[j2]["case_id"] is None
    assert items[j2]["subject_title"] == "A"


# ================================================================ V-H-5 diff
def diff_of(client, jid) -> dict[str, dict]:
    r = client.get(f"{API}/jobs/{jid}/review", headers=R)
    assert r.status_code == 200, r.text
    return {d["key"]: d for d in r.json()["result"]["diff"]}


def test_h5_diff_extract_same_and_changed(client, world):
    c, ids = baseline(world)
    assert diff_of(client, ids["e1"]) == {}                         # 현재와 같으면 생략
    e2 = world.extract(c, created=60, n_elems=120, tstar={"metric": "plastic_strain", "frame_index": 8, "value": 0.03,
                                                         "source": "auto"})
    d = diff_of(client, ids["e1"])
    assert set(d) == {"n_elems", "tstar.frame_index", "tstar.metric", "tstar.value"}
    assert d["n_elems"]["past"] == 100 and d["n_elems"]["current"] == 120 and d["n_elems"]["label"]
    assert d["tstar.frame_index"]["past"] == 5 and d["tstar.frame_index"]["current"] == 8
    assert "part_title" not in d and "n_frames" not in d
    assert diff_of(client, e2) == {}


def test_h5_diff_no_current_and_cap(client, world):
    c = world.case("c1")
    e = world.extract(c, make_current=False)
    d = diff_of(client, e)                                          # 현재 추출 없음 → current: null
    assert set(d) == {"part_title", "n_elems", "n_frames", "tstar.frame_index", "tstar.metric", "tstar.value"}
    assert all(x["current"] is None for x in d.values()) and d["n_elems"]["past"] == 100
    # ESL: 현재 실행 없음
    sid = world.support(c["id"])
    esl = world.esl(c, e, sid, make_current=False)
    d = diff_of(client, esl["job_id"])
    assert set(d) == {"frame_index", "metric", "support_node_ids", "kabsch.bc_residual", "forces.total_norm"}
    assert all(x["current"] is None for x in d.values()) and d["support_node_ids"]["past"] == [1, 2, 3]
    assert d["kabsch.bc_residual"]["past"] == 1e-4 and d["forces.total_norm"]["past"] == 123.0
    # 상한 12
    for jid in (e, esl["job_id"]):
        r = client.get(f"{API}/jobs/{jid}/review", headers=R)
        assert len(r.json()["result"]["diff"]) <= 12


def test_h5_diff_esl_validation_export(client, world):
    c, ids = baseline(world)
    s2 = world.support(c["id"], (7, 8, 9))
    esl2 = world.esl(c, ids["e1"], s2, created=70, frame=6, forces={"sum_abs_f": 200.0},
                     kabsch={"rms_def": 3e-4})
    world.set_case(c["id"], current_support_set_id=s2,
                   tstar={"metric": "max_strain", "frame_index": 6, "value": 0.01, "source": "auto"})
    d = diff_of(client, ids["esl"]["job_id"])
    assert set(d) == {"frame_index", "support_node_ids", "kabsch.bc_residual", "forces.total_norm"}
    assert d["frame_index"] == {"key": "frame_index", "label": d["frame_index"]["label"], "past": 5, "current": 6}
    assert d["support_node_ids"]["current"] == [7, 8, 9] and d["forces.total_norm"]["current"] == 200.0
    # 검증: 현재 run 의 최신 검증과 비교
    val2 = world.validate(c, esl2["run_id"], created=80, verdict="FAIL", disp=0.5,
                          hotspots=[{"elem_id": 1, "rel_err": 0.3}], criteria={"disp_rms_rel_max": 0.02})
    d = diff_of(client, ids["val"]["job_id"])
    assert set(d) == {"verdict", "disp_rms_rel", "hotspot_max_err", "criteria"}
    assert d["verdict"]["past"] == "LEGACY(PASS)" and d["verdict"]["current"] == "LEGACY(FAIL)"   # 시드 검증은 scheme NULL = 이전 판정 체계
    assert d["hotspot_max_err"]["past"] == 0.04 and d["hotspot_max_err"]["current"] == 0.3
    assert d["criteria"]["current"] == {"disp_rms_rel_max": 0.02}
    assert diff_of(client, val2["job_id"]) == {}
    # 내보내기: 최신 성공 내보내기와 비교
    ex2 = world.export(c, esl2["run_id"], created=90, targets=("csv", "fem"), files=("x.csv",), verdict="FAIL",
                       id_range=(1, 2))
    d = diff_of(client, ids["ex"])
    assert set(d) == {"targets", "id_range", "files", "validation_verdict"}
    assert d["files"]["past"] == 2 and d["files"]["current"] == 1 and d["targets"]["current"] == ["csv", "fem"]
    assert diff_of(client, ex2) == {}
    # 보고서 diff 는 비어 있다
    assert diff_of(client, ids["rep"]) == {}


# ================================================================ V-H-6 review
def review(client, jid, hdr=R):
    r = client.get(f"{API}/jobs/{jid}/review", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def test_h6_review_extract(client, world, esl_root):
    c = world.case("c1")
    fp = {"rad": {"path": "/x/a.rad", "size": 10, "mtime": 1.5, "sha256": "abc"},
          "includes": [{"path": "/x/b.inc", "size": 3, "mtime": 2.5}],
          "results": {"path": "/x/csv", "done_json_sha256": None, "files": {"model.csv": {"size": 7, "mtime": 3.5}}}}
    e = world.extract(c)
    with world.engine.begin() as cn:
        cn.execute(update(jobs).where(jobs.c.id == e).values(params={
            "part_title": "chassis rear", "input_fingerprint": fp,
            "settings": {"validation": {"disp_rms_rel_max": 0.01, "hotspot_strain_rel_err_max": 0.1,
                                        "reaction_rel_max": 1e-6}, "compare": {"max_err_pct_max": 10.0},
                         "tstar": {"metric": "max_strain"}, "case": {"material_override": {"7": {"E": 2e5}}}}}))
    rv = review(client, e)
    assert set(rv) == {"job", "timing", "input", "error", "logs", "result"}
    assert rv["job"]["id"] == e and rv["job"]["steps"][0]["step_key"] == "EXTRACT"
    assert "settings" not in rv["input"]["params"] and rv["input"]["params"]["part_title"] == "chassis rear"
    ss = rv["input"]["settings_summary"]
    assert ss["criteria"]["disp_rms_rel_max"] == 0.01 and ss["tstar_metric"] == "max_strain"
    assert ss["material_override"] == {"7": {"E": 2e5}}
    kinds = [(f["kind"], f["path"]) for f in rv["input"]["input_fingerprint"]]
    assert kinds == [("rad", "/x/a.rad"), ("include", "/x/b.inc"), ("result", "/x/csv/model.csv")]
    assert rv["timing"]["wait_s"] == 1.0 and rv["timing"]["duration_s"] == 4.0
    assert rv["timing"]["steps"][0]["duration_s"] == 2.0
    assert rv["error"] == {"warnings": []}
    r = rv["result"]
    assert r["ref"] == {"kind": "extract", "id": e} and r["state"] == "current" and r["availability"] == "full"
    assert r["files_note"] is None and r["past"]["extract"]["n_elems"] == 100 and r["past"]["tstar"]["frame_index"] == 5
    assert r["links"] == {"stage": 1}
    # 이후 재추출 → 과거: summary + 안내 문구
    world.extract(c, created=60)
    r = review(client, e)["result"]
    assert r["state"] == "past" and r["availability"] == "summary" and "파일 보존 안 됨" in r["files_note"]
    assert r["stale_reasons"] == ["extract"]


def test_h6_review_esl_validation_export_report(client, world, esl_root):
    c, ids = baseline(world)
    cdir = c["dir"]
    # ESL: 스냅샷이 없으면 summary, 있으면 full
    r = review(client, ids["esl"]["job_id"])["result"]
    assert r["availability"] == "summary" and r["past"]["id"] == ids["esl"]["run_id"]
    assert r["past"]["is_current"] is True and r["past"]["stale"] is False and r["links"] == {
        "stage": 4, "query": {"run": ids["esl"]["run_id"]}}
    snap = cdir / "runs" / ids["esl"]["run_id"] / "04_esl"
    snap.mkdir(parents=True)
    (snap / "esl_summary.json").write_text(json.dumps({"tag": ids["esl"]["job_id"]}))
    r = review(client, ids["esl"]["job_id"])["result"]
    assert r["availability"] == "full" and r["files_note"] is None
    # 검증: 파일 없음 → summary + has_field false
    r = review(client, ids["val"]["job_id"])["result"]
    assert r["availability"] == "summary" and r["past"]["has_field"] is False and r["past"]["verdict"] == "PASS"
    assert r["links"] == {"stage": 5, "query": {"val": ids["val"]["validation_id"]}}
    write_compare_field(str(cdir / "05_val"), 50)                  # Case 05_val(최신 검증) → 찾음
    r = review(client, ids["val"]["job_id"])["result"]
    assert r["availability"] == "full" and r["past"]["has_field"] is True
    # 내보내기: history 없음 → summary(파일 이름만), 있으면 full
    r = review(client, ids["ex"])["result"]
    assert r["availability"] == "summary" and r["past"]["targets"] == ["radioss_inc"]
    assert r["past"]["files"] == [{"name": "a.inc", "size": None, "downloadable": False},
                                  {"name": "b.inc", "size": None, "downloadable": False}]
    assert r["past"]["id_range"] == [9000000, 9000100] and r["past"]["validation_verdict"] == "PASS"
    assert r["past"]["warnings"] == ["w1"]
    hd = cdir / "history" / ids["ex"] / "06_export"
    hd.mkdir(parents=True)
    (hd / "a.inc").write_text("12345")
    (hd / "b.inc").write_text("1")
    r = review(client, ids["ex"])["result"]
    assert r["availability"] == "full"
    assert r["past"]["files"] == [{"name": "a.inc", "size": 5, "downloadable": True},
                                  {"name": "b.inc", "size": 1, "downloadable": True}]
    # 보고서
    r = review(client, ids["rep"])["result"]
    assert r["availability"] == "summary" and r["past"] == {"verdict": "PASS", "bytes": 4321}
    hr = cdir / "history" / ids["rep"]
    hr.mkdir(parents=True)
    (hr / "report.html").write_text("<html></html>")
    assert review(client, ids["rep"])["result"]["availability"] == "full"


def test_h6_review_failed_canceled_queued_library(client, world):
    c = world.case("c1")
    log_dir = c["dir"] / "logs"
    failed = world.job(case_id=c["id"], job_type="ESL_SOLVE", state="FAILED", created=5, queued=5, started=6,
                       finished=9, failure_code="SOLVER_SINGULAR", failure_message="특이 행렬", warnings=["경고1"],
                       steps=[{"key": "ESL", "stage": "esl", "state": "FAILED", "started": 6, "finished": 9,
                               "exit_code": 3, "failure_code": "SOLVER_SINGULAR", "failure_message": "특이 행렬",
                               "log_rel": "logs/x/step_01_ESL.log"},
                              {"key": "ESL_REGISTER", "state": "SKIPPED"}])
    (log_dir / "x").mkdir(parents=True)
    (log_dir / "x" / "step_01_ESL.log").write_text("hello\nworld\n")
    rv = review(client, failed)
    assert rv["error"] == {"failure_code": "SOLVER_SINGULAR", "failure_message": "특이 행렬", "warnings": ["경고1"],
                           "failed_step": {"step_no": 1, "step_key": "ESL", "exit_code": 3,
                                           "failure_code": "SOLVER_SINGULAR", "failure_message": "특이 행렬"}}
    assert rv["result"]["availability"] == "none" and rv["result"]["ref"] is None and rv["result"]["state"] is None
    assert rv["result"]["past"] == {} and rv["result"]["diff"] == [] and rv["result"]["stale_reasons"] == []
    assert rv["logs"] == [{"step_no": 1, "step_key": "ESL", "state": "FAILED", "has_log": True, "size": 12},
                          {"step_no": 2, "step_key": "ESL_REGISTER", "state": "SKIPPED", "has_log": False, "size": 0}]
    intr = world.job(case_id=c["id"], job_type="EXPORT", state="INTERRUPTED", created=6, failure_code="WORKER_LOST",
                     failure_message="워커 중단", steps=[{"key": "EXPORT", "state": "FAILED", "failure_code": "WORKER_LOST"}])
    assert review(client, intr)["error"]["failed_step"]["failure_code"] == "WORKER_LOST"
    canceled = world.job(case_id=c["id"], job_type="VALIDATE", state="CANCELED", created=7, failure_code="CANCELED",
                         failure_message="사용자 취소")
    rv = review(client, canceled)
    assert rv["error"] == {"warnings": []} and rv["result"]["availability"] == "none"
    queued = world.job(case_id=c["id"], job_type="CASE_REPORT", state="QUEUED", created=8, queued=8)
    rv = review(client, queued)
    assert rv["result"]["availability"] == "none" and rv["timing"]["duration_s"] is None
    # 라이브러리 작업
    an = str(uuid.uuid4())
    with world.engine.begin() as cn:
        cn.execute(insert(analysis_runs).values(id=an, project_id="p-1", title="A", filters={}, options={},
                                                entry_ids=["e"], dir_rel=f"_analysis/{an}", created_by="u",
                                                created_by_name="u"))
    j = world.job(job_type="LIB_ANALYZE", analysis_id=an, created=10, result={"registered": {"n_cases": 3}})
    with world.engine.begin() as cn:
        cn.execute(update(analysis_runs).where(analysis_runs.c.id == an).values(job_id=j))
    r = review(client, j)["result"]
    assert r["availability"] == "summary" and r["state"] == "current" and r["past"] == {"n_cases": 3}
    assert r["ref"] == {"kind": "analysis", "id": an} and r["links"] == {"stage": 8, "query": {"analysis": an}}
    assert client.get(f"{API}/jobs/{uuid.uuid4()}/review", headers=R).status_code == 404
    assert code(client.get(f"{API}/jobs/{uuid.uuid4()}/review", headers=R)) == "JOB_NOT_FOUND"


# ================================================================ V-H-7 권한
def test_h7_permissions(client, world, fake_dashboard):
    c, ids = baseline(world)
    jid = world.job(case_id=c["id"], job_type="CASE_EXTRACT", state="FAILED", created=200, steps=[
        {"key": "H3D_EXTRACT", "state": "FAILED", "failure_code": "H3D_EXTRACT_FAILED",
         "command": ["C:/hw.exe", "-tcl", "x.tcl"]}])
    # 인증 필요 / 비활성 계정
    assert client.get(f"{API}/history", params={"project_id": "p-1"}).status_code == 401
    assert client.get(f"{API}/jobs/{jid}/review").status_code == 401
    for path in (f"/history?project_id=p-1", f"/jobs/{jid}/review", f"/jobs/{jid}/files", f"/jobs/{jid}/report"):
        r = client.get(f"{API}{path}", headers=H("tok-pending"))
        assert r.status_code == 403 and code(r) == "ACCOUNT_NOT_ACTIVE", path
    # ACTIVE 사용자는 프로젝트 역할과 무관하게 조회(일반·power·프로젝트 외 멤버·전역 관리자)
    for hdr in (H("tok-general"), H("tok-power"), H("tok-nonmember"), H("tok-admin")):
        assert client.get(f"{API}/history", params={"project_id": "p-1"}, headers=hdr).status_code == 200
        assert client.get(f"{API}/jobs/{jid}/review", headers=hdr).status_code == 200
    # command: 전역 관리자에게만 키가 존재
    for hdr in (H("tok-general"), H("tok-power"), H("tok-nonmember")):
        st = client.get(f"{API}/jobs/{jid}/review", headers=hdr).json()["job"]["steps"][0]
        assert "command" not in st, st
    st = client.get(f"{API}/jobs/{jid}/review", headers=RA).json()["job"]["steps"][0]
    assert st["command"] == ["C:/hw.exe", "-tcl", "x.tcl"]
    # 기존 API 에는 여전히 command 없음
    assert "command" not in client.get(f"{API}/jobs/{jid}", headers=RA).json()["steps"][0]
    # 이력 목록·상세에 lease/토큰 노출 없음
    body = json.dumps(client.get(f"{API}/jobs/{jid}/review", headers=RA).json())
    assert "lease_" not in body and "env_snapshot" not in body and "queue_seq" not in body
    # PC 연결 토큰은 범위 밖(/uploads* · /version 만)
    # 로그 마스킹은 기존 /jobs/{id}/log 를 그대로 쓴다(review 는 본문을 주지 않음)
    assert "lines" not in json.dumps(client.get(f"{API}/jobs/{jid}/review", headers=RA).json()["logs"])


def test_h7_log_masking_kept(client, world):
    c = world.case("c1")
    (c["dir"] / "logs" / "j1").mkdir(parents=True)
    (c["dir"] / "logs" / "j1" / "step_01_EXTRACT.log").write_text("ok\npassword = hunter2\n")
    jid = world.job(case_id=c["id"], created=1, steps=[{"key": "EXTRACT", "log_rel": "logs/j1/step_01_EXTRACT.log"}])
    r = client.get(f"{API}/jobs/{jid}/log", params={"step": 1}, headers=R)
    assert r.status_code == 200 and "hunter2" not in json.dumps(r.json()) and "***" in json.dumps(r.json())
    assert review(client, jid)["logs"][0]["has_log"] is True


# ================================================================ V-H-8 _backup 표식 탐색
def _val_dir(base: Path, ts_name: str, run_id: str, vid: str | None, n=40, marker: str | None = None) -> Path:
    d = base / "_backup" / ts_name / "runs" / run_id / "05_val"
    write_compare_field(str(d), n)
    if vid is not None:
        (d / "platform_validation_id.txt").write_text(marker if marker is not None else vid)
    return d


def test_h8_backup_marker_search(client, world, app_ctx):
    c, ids = baseline(world)
    cdir = c["dir"]
    run_id, vid = ids["esl"]["run_id"], ids["val"]["validation_id"]
    # 같은 run 의 새 검증(최신)이 생김 → 이전 검증의 field 는 파일이 없어 409
    val2 = world.validate(c, run_id, created=100)
    write_compare_field(str(cdir / "runs" / run_id / "05_val"), 40)
    (cdir / "runs" / run_id / "05_val" / "platform_validation_id.txt").write_text(val2["validation_id"])
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409 and code(r) == "VALIDATION_FILES_GONE"
    assert client.get(f"{API}/validations/{val2['validation_id']}/field", headers=R).status_code == 200
    # 표식이 같은 _backup 폴더 → 읽기 전용으로 200 (field·section 둘 다)
    _val_dir(cdir, "20261001T000000_000000Z", run_id, vid, n=60)
    r = client.get(f"{API}/validations/{vid}/field", params={"layer": "err"}, headers=R)
    assert r.status_code == 200 and r.json()["validation_id"] == vid and r.json()["n_total"] == 60
    assert client.get(f"{API}/validations/{vid}/section", headers=R).status_code == 200
    assert review(client, ids["val"]["job_id"])["result"]["past"]["has_field"] is True
    assert review(client, ids["val"]["job_id"])["result"]["availability"] == "full"
    # 표식 불일치(다른 검증 id)·표식 없음 → 409
    other = str(uuid.uuid4())
    shutil_rm(cdir / "_backup")
    _val_dir(cdir, "20261001T000000_000000Z", run_id, other)
    _val_dir(cdir, "20261002T000000_000000Z", run_id, None)
    _val_dir(cdir, "20261003T000000_000000Z", run_id, vid, marker=vid + "x")          # 정확 일치 아님
    _val_dir(cdir, "20261004T000000_000000Z", "other-run", vid)                       # 다른 run 폴더
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409 and code(r) == "VALIDATION_FILES_GONE"
    assert review(client, ids["val"]["job_id"])["result"]["availability"] == "summary"
    # 폴더 밖 심링크(05_val 이 Case 밖을 가리킴, 표식 일치) → 무시
    outside = world.root.parent / "outside_val"
    write_compare_field(str(outside), 40)
    (outside / "platform_validation_id.txt").write_text(vid)
    link_parent = cdir / "_backup" / "20261005T000000_000000Z" / "runs" / run_id
    link_parent.mkdir(parents=True)
    os.symlink(outside, link_parent / "05_val")
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409
    # 표식 파일 자체가 심링크 → 무시
    d = _val_dir(cdir, "20261006T000000_000000Z", run_id, None)
    secret = world.root.parent / "marker_src.txt"
    secret.write_text(vid)
    os.symlink(secret, d / "platform_validation_id.txt")
    assert client.get(f"{API}/validations/{vid}/field", headers=R).status_code == 409
    # compare_field.npz 가 심링크(밖)인 정상 표식 폴더 → 409 (밖 파일을 읽지 않음)
    shutil_rm(cdir / "_backup")
    d = _val_dir(cdir, "20261007T000000_000000Z", run_id, vid)
    (d / "compare_field.npz").unlink()
    write_compare_field(str(outside / "n"), 40)
    os.symlink(outside / "n" / "compare_field.npz", d / "compare_field.npz")
    assert client.get(f"{API}/validations/{vid}/field", headers=R).status_code == 409
    # 탐색 상한: 최신 순 history.backup_scan_max 개 폴더만 연다
    shutil_rm(cdir / "_backup")
    for i in range(5):
        (cdir / "_backup" / f"2026100{i + 1}T000000_000000Z").mkdir(parents=True)        # 표식 없는 최신 폴더들
    _val_dir(cdir, "20260901T000000_000000Z", run_id, vid)                             # 가장 오래된 것에 표식
    object.__setattr__(app_ctx.settings.history, "backup_scan_max", 6)
    assert client.get(f"{API}/validations/{vid}/field", headers=R).status_code == 200
    object.__setattr__(app_ctx.settings.history, "backup_scan_max", 5)
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409 and code(r) == "VALIDATION_FILES_GONE"


def shutil_rm(p: Path) -> None:
    import shutil

    shutil.rmtree(p, ignore_errors=True)


def test_h8_backup_never_listed(client, world):
    c, ids = baseline(world)
    _val_dir(c["dir"], "20261001T000000_000000Z", ids["esl"]["run_id"], ids["val"]["validation_id"])
    (c["dir"] / "_backup" / "20261001T000000_000000Z" / "06_export").mkdir(parents=True)
    (c["dir"] / "_backup" / "20261001T000000_000000Z" / "06_export" / "old.inc").write_text("x")
    # artifacts·history 파일 목록·다운로드·리뷰 어디에도 _backup 경로가 나오지 않는다
    assert "_backup" not in json.dumps(client.get(f"{API}/cases/{c['id']}/artifacts", headers=R).json())
    for jid in (ids["ex"], ids["val"]["job_id"], ids["esl"]["job_id"], ids["e1"]):
        assert "_backup" not in json.dumps(review(client, jid))
    assert client.get(f"{API}/jobs/{ids['ex']}/files", headers=R).status_code == 404
    assert client.get(f"{API}/jobs/{ids['ex']}/files/old.inc/download", headers=R).status_code in (404, 422)
    assert client.get(f"{API}/jobs/{ids['ex']}/files/_backup/download", headers=R).status_code in (404, 422)


# ================================================================ V-H-9 보존 파일 API
def test_h9_files_api(client, world, app_ctx):
    c, ids = baseline(world)
    ex = ids["ex"]
    assert client.get(f"{API}/jobs/{ex}/files", headers=R).status_code == 404
    assert code(client.get(f"{API}/jobs/{ex}/files", headers=R)) == "HISTORY_FILES_GONE"
    hd = c["dir"] / "history" / ex / "06_export"
    hd.mkdir(parents=True)
    (hd / "esl_cload.inc").write_bytes(b"A" * 100)
    (hd / "f_eq.csv").write_bytes(b"B" * 7)
    (hd / "sub").mkdir()
    (hd / "sub" / "deep.txt").write_text("x")
    os.symlink(world.root.parent / "marker_src.txt" if (world.root.parent / "marker_src.txt").exists() else hd / "f_eq.csv",
               hd / "link.csv")
    r = client.get(f"{API}/jobs/{ex}/files", headers=R)
    assert r.status_code == 200
    assert r.json() == [{"name": "esl_cload.inc", "size": 100, "downloadable": True},
                        {"name": "f_eq.csv", "size": 7, "downloadable": True}]
    d = client.get(f"{API}/jobs/{ex}/files/esl_cload.inc/download", headers=R)
    assert d.status_code == 200 and d.content == b"A" * 100
    assert "esl_cload.inc" in d.headers["content-disposition"]
    # 이름 공격 / 목록 밖
    for name, codes in (("..", (404, 422)), ("%2e%2e", (404, 422)), ("sub", (404,)), ("deep.txt", (404,)), ("link.csv", (404,)),
                        ("nope.inc", (404,)), ("..%2F..%2Fcase.json", (404, 422)), ("a%5Cb", (422,)),
                        ("%2e%2e%2f%2e%2e%2fcase.json", (404, 422)), ("report.html", (404,))):
        r = client.get(f"{API}/jobs/{ex}/files/{name}/download", headers=R)
        assert r.status_code in codes, (name, r.status_code, r.text)
    # 크기 상한 초과 → 413 ARTIFACT_TOO_LARGE, 목록은 downloadable false
    object.__setattr__(app_ctx.settings.ui, "max_artifact_bytes", 50)
    assert client.get(f"{API}/jobs/{ex}/files", headers=R).json()[0] == {"name": "esl_cload.inc", "size": 100,
                                                                         "downloadable": False}
    r = client.get(f"{API}/jobs/{ex}/files/esl_cload.inc/download", headers=R)
    assert r.status_code == 413 and code(r) == "ARTIFACT_TOO_LARGE"
    assert client.get(f"{API}/jobs/{ex}/files/f_eq.csv/download", headers=R).status_code == 200
    # EXPORT·CASE_REPORT 가 아닌 작업은 404
    assert client.get(f"{API}/jobs/{ids['e1']}/files", headers=R).status_code == 404
    assert client.get(f"{API}/jobs/{ids['esl']['job_id']}/files/x/download", headers=R).status_code == 404
    assert client.get(f"{API}/jobs/{ids['ex']}/report", headers=R).status_code == 404
    assert client.get(f"{API}/jobs/{uuid.uuid4()}/files", headers=R).status_code == 404


def test_h9_report_api(client, world):
    c, ids = baseline(world)
    rep = ids["rep"]
    assert client.get(f"{API}/jobs/{rep}/report", headers=R).status_code == 404
    hr = c["dir"] / "history" / rep
    hr.mkdir(parents=True)
    (hr / "report.html").write_text("<!doctype html><html><body>이전 보고서</body></html>", encoding="utf-8")
    r = client.get(f"{API}/jobs/{rep}/report", headers=R)
    assert r.status_code == 200 and "이전 보고서" in r.text
    assert r.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; " \
                                                   "script-src 'unsafe-inline'; img-src data:"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert "attachment" in client.get(f"{API}/jobs/{rep}/report", params={"download": "1"}, headers=R).headers[
        "content-disposition"]
    fl = client.get(f"{API}/jobs/{rep}/files", headers=R).json()
    assert [f["name"] for f in fl] == ["report.html"]
    assert client.get(f"{API}/jobs/{rep}/files/report.html/download", headers=R).status_code == 200
    # 현재 보고서 API 와 같은 응답 헤더
    (c["dir"] / "07_report").mkdir()
    (c["dir"] / "07_report" / "report.html").write_text("<html>cur</html>")
    cur = client.get(f"{API}/cases/{c['id']}/report", headers=R)
    for h in ("content-security-policy", "x-content-type-options", "referrer-policy", "cache-control", "content-type"):
        assert cur.headers[h] == r.headers[h]
    # history 폴더가 Case 밖 심링크면 사용하지 않는다
    import shutil

    shutil.rmtree(c["dir"] / "history")
    outside = world.root.parent / "evil"
    (outside / rep).mkdir(parents=True)
    (outside / rep / "report.html").write_text("evil")
    os.symlink(outside, c["dir"] / "history")
    assert client.get(f"{API}/jobs/{rep}/report", headers=R).status_code == 404
    assert client.get(f"{API}/jobs/{rep}/files", headers=R).status_code == 404


def test_h9_history_not_in_artifacts_or_bundle(client, world):
    c, ids = baseline(world)
    hd = c["dir"] / "history" / ids["ex"] / "06_export"
    hd.mkdir(parents=True)
    (hd / "esl_cload.inc").write_text("x")
    (c["dir"] / "06_export").mkdir()
    (c["dir"] / "06_export" / "esl_cload.inc").write_text("x")      # 현재 내보내기는 zip 에 들어간다
    assert all(not a["rel"].startswith("history/") for a in client.get(
        f"{API}/cases/{c['id']}/artifacts", headers=R).json())
    r = client.get(f"{API}/cases/{c['id']}/bundle", headers=R)
    assert r.status_code == 200, r.text
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names and not any("/history/" in n for n in names)
    from esl_platform.core.core_outputs import HISTORY_DIR, STAGE_DIRS

    assert HISTORY_DIR not in STAGE_DIRS.values() and HISTORY_DIR not in (
        "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report", "runs", "logs", "_backup")


# ================================================================ V-H-10 migration 0007
HIST_INDEXES = ("ix_jobs_project_created", "ix_jobs_project_creator_created", "ix_jobs_retry_of", "ix_esl_runs_job",
                "ix_validations_job")


def _indexdefs(engine) -> dict[str, str]:
    with engine.connect() as c:
        return {r[0]: r[1] for r in c.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(:n)"), {"n": list(HIST_INDEXES)})}


def test_h10_migration_0007_up_down_idempotent(engine, db_url):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    created_by_create_all = _indexdefs(engine)                  # 새 DB(0001 create_all + 0007)
    assert set(created_by_create_all) == set(HIST_INDEXES)
    d = created_by_create_all
    assert "(project_id, created_at DESC, id DESC)" in d["ix_jobs_project_created"]
    assert "(project_id, created_by, created_at DESC)" in d["ix_jobs_project_creator_created"]
    assert "(retry_of_job_id)" in d["ix_jobs_retry_of"] and "WHERE (retry_of_job_id IS NOT NULL)" in d["ix_jobs_retry_of"]
    assert "(job_id)" in d["ix_esl_runs_job"] and "(job_id)" in d["ix_validations_job"]
    # downgrade: 인덱스만 제거(테이블·데이터 유지)
    with engine.begin() as c:
        c.execute(text("INSERT INTO cases (id, project_id, folder_name, title, rad_path, results_dir, input_fingerprint,"
                       " part_title, created_by, created_by_name) VALUES ('c1','p','f1','t','/r','/s','{}','x','u','u')"))
    command.stamp(cfg, "0008")                                 # 0010 은 downgrade 미지원 — 표시만 0008 로
    command.downgrade(cfg, "0006")
    assert _indexdefs(engine) == {}
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0006"
        assert c.execute(text("SELECT count(*) FROM cases")).scalar_one() == 1
        cols = c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name='jobs'")).scalar_one()
    command.upgrade(cfg, "head")
    assert _indexdefs(engine) == created_by_create_all          # 마이그레이션이 만든 정의 = tables.py(create_all) 정의
    command.upgrade(cfg, "head")                                # 재실행 멱등
    command.stamp(cfg, "0008")
    command.downgrade(cfg, "0006")
    command.upgrade(cfg, "head")
    assert _indexdefs(engine) == created_by_create_all
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name='jobs'")
                         ).scalar_one() == cols
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012"


def test_h10_tables_match_alembic_metadata(engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from esl_platform.core.db.tables import metadata

    with engine.connect() as c:
        diffs = compare_metadata(MigrationContext.configure(c), metadata)
    flat = repr(diffs)
    assert not [n for n in HIST_INDEXES if n in flat], flat      # tables.py Index 선언 = DB 인덱스


# ================================================================ V-H-11 성능
def test_h11_performance_100k(client, world, engine):
    pids = ["p-1", "p-2", "p-3"]
    case_ids = {}
    for p in pids:
        for i in range(10):
            case_ids[(p, i)] = world.case(f"{p.replace('-', '')}x{i}", project_id=p)["id"]
    with engine.begin() as c:
        c.execute(text("CREATE TEMP TABLE _cs AS SELECT id, project_id, row_number() OVER (ORDER BY id) AS rn FROM cases"))
        c.execute(text("""
            INSERT INTO jobs (id, case_id, project_id, job_type, stage, lane, state, holds_slot, params, created_by,
                              created_by_name, created_at, queued_at, started_at, finished_at)
            SELECT gen_random_uuid()::text, cs.id, cs.project_id,
                   (ARRAY['CASE_EXTRACT','ESL_SOLVE','VALIDATE','EXPORT','CASE_REPORT'])[1 + g % 5],
                   (ARRAY[1,4,5,6,7])[1 + g % 5],
                   (ARRAY['SLOT','SLOT','SLOT','LIGHT','LIGHT'])[1 + g % 5],
                   (ARRAY['SUCCEEDED','CANCELED'])[1 + g % 2], false, '{}'::jsonb,
                   (ARRAY['u-power','u-power2','u-admin'])[1 + g % 3], 'x',
                   timestamptz '2026-01-01' + (g * 7 || ' seconds')::interval,
                   timestamptz '2026-01-01' + (g * 7 || ' seconds')::interval,
                   timestamptz '2026-01-01' + (g * 7 + 1 || ' seconds')::interval,
                   timestamptz '2026-01-01' + (g * 7 + 3 || ' seconds')::interval
            FROM generate_series(1, 100000) g JOIN _cs cs ON cs.rn = 1 + (g % 30)
        """))
        c.execute(text("ANALYZE jobs"))
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 100000
    # 첫 페이지·5번째 페이지(limit 50) p95 < 300 ms
    first = hist(client, limit=50)
    assert first.status_code == 200 and len(first.json()["items"]) == 50
    cursor, pages = first.json()["next_cursor"], [first]
    for _ in range(4):
        r = hist(client, limit=50, cursor=cursor)
        cursor = r.json()["next_cursor"]
        pages.append(r)
    fifth_cursor = pages[3].json()["next_cursor"]
    for name, params in (("first", {"limit": 50}), ("fifth", {"limit": 50, "cursor": fifth_cursor}),
                         ("mine", {"limit": 50, "mine": "true"}), ("case", {"limit": 50, "case_id": case_ids[("p-1", 3)]})):
        lat = []
        for _ in range(20):
            t = time.perf_counter()
            r = hist(client, RP, **params)
            lat.append(time.perf_counter() - t)
            assert r.status_code == 200 and len(r.json()["items"]) == 50
        p95 = sorted(lat)[int(0.95 * len(lat)) - 1]
        assert p95 < 0.3, (name, p95)
    # EXPLAIN: 프로젝트 목록 쿼리가 ix_jobs_project_created 를 쓴다
    from sqlalchemy.dialects import postgresql

    from esl_platform.core.repositories import history as repo

    captured: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cursor_, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.startswith("SELECT jobs.id, jobs.case_id") and "WHERE jobs.project_id = " in statement:
            captured.append((statement, parameters))

    hist(client, limit=50)
    hist(client, limit=50, cursor=fifth_cursor)
    event.remove(engine, "before_cursor_execute", _cap)
    assert len(captured) == 2
    with engine.connect() as c:
        for stmt, params in captured:
            plan = "\n".join(r[0] for r in c.exec_driver_sql("EXPLAIN " + stmt, params))
            assert "ix_jobs_project_created" in plan, plan
    # 쿼리 수 일정(N+1 없음): limit 에 관계없이 같고 작다
    counts = {}
    for lim in (5, 50, 200):
        n = [0]

        def _cnt(conn, cursor_, statement, parameters, context, executemany):  # noqa: ANN001
            n[0] += 1

        event.listen(engine, "before_cursor_execute", _cnt)
        r = hist(client, limit=lim)
        event.remove(engine, "before_cursor_execute", _cnt)
        assert r.status_code == 200 and len(r.json()["items"]) == lim
        counts[lim] = n[0]
    assert counts[50] == counts[200] and counts[5] <= counts[50], counts      # 비는 조회는 생략(구성에 따라 ±1)
    assert counts[200] <= 14, counts
