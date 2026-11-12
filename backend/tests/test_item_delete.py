"""v0.19.0 목록 항목 삭제(계약 esl_item_delete.md): V-DEL-1~13·17·(+) — 스터디·비드 최적화·종합 분석·버전 비교.

DB·폴더를 직접 심는다(계산 없이). 삭제는 `<esl_root>/_trash` 로 이동만(영구 삭제는 워커 리퍼 — worker/tests/test_trash_purge.py).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from esl_test_support import API, H, make_settings_dict
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")
ADMIN = H("tok-admin", True)
OTHER = H("tok-power2", True)
GENERAL = H("tok-general", True)
KINDS = ("DOE", "OPT", "ANALYSIS", "COMPARE")
URL = {"DOE": "doe/studies", "OPT": "opt/runs", "ANALYSIS": "library/analyses", "COMPARE": "library/comparisons"}
NOT_FOUND = {"DOE": "DOE_NOT_FOUND", "OPT": "OPT_RUN_NOT_FOUND", "ANALYSIS": "ANALYSIS_NOT_FOUND",
             "COMPARE": "COMPARISON_NOT_FOUND"}
KDIR = {"DOE": "_doe", "OPT": "_opt", "ANALYSIS": "_analysis", "COMPARE": "_compare", "VERIFY": "_verify"}
TABLE = {"DOE": "bead_does", "OPT": "opt_runs", "ANALYSIS": "analysis_runs", "COMPARE": "comparisons",
         "VERIFY": "verify_drops"}
SUBJ_COL = {"DOE": "bead_doe_id", "OPT": "opt_run_id", "ANALYSIS": "analysis_id", "COMPARE": "comparison_id",
            "VERIFY": "verify_drop_id"}
JOB_TYPE = {"DOE": "DOE_PREP", "OPT": "OPT_RUN", "ANALYSIS": "LIB_ANALYZE", "COMPARE": "LIB_COMPARE",
            "VERIFY": "VERIFY_DROP"}


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path)
    d["worker"]["fs_retry"] = {"attempts": 3, "max_wait_s": 0.5, "base_s": 0.001}      # 잠금 재시도 시험을 빠르게
    return d


# ---------------------------------------------------------------- 심기
def _put_folder(esl_root: Path, kind: str, item_id: str) -> Path:
    d = esl_root / KDIR[kind] / item_id
    (d / "sub").mkdir(parents=True)
    (d / "report.html").write_text("<html/>", encoding="utf-8")
    (d / "sub" / "data.bin").write_bytes(b"x" * 100)
    return d


def seed_item(engine, esl_root: Path, kind: str, *, created_by: str = "u-power", name: str = "파워", project: str = "p-1",
              folder: bool = True, phase: str = "DONE", item_id: str | None = None) -> str:
    from esl_platform.core.repositories import doe as doe_repo
    from esl_platform.core.repositories import library as lib_repo
    from esl_platform.core.repositories import opt as opt_repo

    iid = item_id or str(uuid.uuid4())
    rel = f"{KDIR[kind]}/{iid}"
    who = dict(created_by=created_by, created_by_name=name)
    with engine.begin() as c:
        if kind == "DOE":
            doe_repo.insert_study(c, id=iid, project_id=project, scenario="same", title="스터디", entry_ids=["e1"],
                                  base={"entry_id": "e1"}, inputs={}, phase=phase, dir_rel=rel, **who)
        elif kind == "OPT":
            opt_repo.insert_run(c, id=iid, project_id=project, scenario="S1", title="최적화", entry_ids=["e1"],
                                base={"entry_id": "e1"}, design={}, options={}, dir_rel=rel, **who)
        elif kind == "ANALYSIS":
            lib_repo.insert_analysis(c, id=iid, project_id=project, title="분석", filters={}, options={},
                                     entry_ids=["e1"], dir_rel=rel, **who)
        else:
            lib_repo.insert_comparison(c, id=iid, project_id=project, title="비교", model="55QX10A", base_version="v1",
                                       new_version="v2", filters={}, options={}, base_entry_ids=["a"],
                                       new_entry_ids=["b"], n_paired=1, dir_rel=rel, **who)
    if folder:
        _put_folder(esl_root, kind, iid)
    return iid


def seed_job(engine, kind: str, item_id: str, state: str = "SUCCEEDED", *, with_note: bool = True,
             project: str = "p-1") -> str:
    """항목의 작업 1건(job_steps 포함) + 알림. 비종료는 QUEUED·RUNNING(cancel_requested 는 호출자가 켬)."""
    from esl_platform.core.repositories import jobs as jobs_repo

    with engine.begin() as c:
        job = jobs_repo.insert_job(c, case_id=None, project_id=project, job_type=JOB_TYPE[kind], params={},
                                   created_by="u-power", created_by_name="파워", **{SUBJ_COL[kind]: item_id})
        if state != "QUEUED":
            c.execute(text("UPDATE jobs SET state=CAST(:s AS varchar), queue_seq=NULL,"
                           " holds_slot=(CAST(:s AS varchar)='RUNNING' AND lane='SLOT'),"
                           " started_at=now(), finished_at=CASE WHEN CAST(:s AS varchar)='RUNNING' THEN NULL ELSE now() END,"
                           " failure_code=CASE WHEN CAST(:s AS varchar) IN ('FAILED','INTERRUPTED') THEN 'X' END WHERE id=:i"),
                      {"s": state, "i": job["id"]})
        if with_note:
            jobs_repo.notify(c, job, "JOB_SUCCEEDED")
    return job["id"]


def seed_drop(engine, esl_root: Path, inputs_root: Path, sid: str, *, phase: str = "DONE", sub_state: str | None = "FAILED",
              job_state: str | None = "SUCCEEDED", n: int = 0) -> str:
    from esl_platform.core.repositories import verify as verify_repo
    from verify_support import seed_case, seed_entry_for

    case = seed_case(engine, esl_root, inputs_root, f"c{n}{uuid.uuid4().hex[:4]}")
    eid = seed_entry_for(engine, case["id"])
    did = str(uuid.uuid4())
    with engine.begin() as c:
        verify_repo.insert_drop(c, id=did, batch_id=str(uuid.uuid4()), project_id="p-1", bead_doe_id=sid, design_id="d007",
                                case_id=case["id"], entry_id=eid, title="검증", phase=phase, drive_dir_rel="share/drop/x",
                                dir_rel=f"_verify/{did}", created_by="u-power", created_by_name="파워")
        if sub_state:
            verify_repo.insert_submission(c, verify_drop_id=did, attempt=1, request_sha256="0" * 64)
            c.execute(text("UPDATE scx_submissions SET state=:s WHERE verify_drop_id=:d"), {"s": sub_state, "d": did})
    _put_folder(esl_root, "VERIFY", did)
    if job_state:
        seed_job(engine, "VERIFY", did, job_state)
    return did


def count(engine, table: str, where: str = "true", **p: Any) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), p).scalar_one())


def trash_names(esl_root: Path) -> list[str]:
    t = esl_root / "_trash"
    return sorted(os.listdir(t)) if t.is_dir() else []


def deletion_row(engine, kind: str, iid: str) -> dict[str, Any] | None:
    from esl_platform.core.repositories import deletions as del_repo

    with engine.connect() as c:
        return del_repo.get_by_item(c, kind, iid)


def delete(client, kind: str, iid: str, headers=W):
    return client.delete(f"{API}/{URL[kind]}/{iid}", headers=headers)


def sha_tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------- V-DEL-1
def test_v1_study_done_delete_moves_folders_and_rows(client, engine, esl_root, inputs_root):
    sid = seed_item(engine, esl_root, "DOE")
    j_study = seed_job(engine, "DOE", sid, "FAILED")
    j_study2 = seed_job(engine, "DOE", sid, "SUCCEEDED")
    d1 = seed_drop(engine, esl_root, inputs_root, sid, phase="DONE", sub_state="ATTACHED", n=1)
    d2 = seed_drop(engine, esl_root, inputs_root, sid, phase="FAILED", sub_state="FAILED", n=2)
    other = seed_item(engine, esl_root, "DOE")           # 다른 스터디는 그대로
    seed_job(engine, "DOE", other)
    n_jobs = 4
    assert count(engine, "job_steps", "job_id IN (SELECT id FROM jobs WHERE bead_doe_id=:s OR verify_drop_id IN (:a,:b))",
                 s=sid, a=d1, b=d2) > 0
    r = delete(client, "DOE", sid)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["deleted"] is True and b["kind"] == "DOE" and b["id"] == sid and b["purge"] == "PENDING"
    assert (b["n_jobs"], b["n_verify_drops"], b["n_opt_unlinked"]) == (n_jobs, 2, 0)
    assert count(engine, "bead_does", "id=:i", i=sid) == 0 and count(engine, "verify_drops", "bead_doe_id=:i", i=sid) == 0
    assert count(engine, "scx_submissions", "verify_drop_id IN (:a,:b)", a=d1, b=d2) == 0
    assert count(engine, "jobs", "id IN (:a,:b)", a=j_study, b=j_study2) == 0
    assert count(engine, "jobs", "verify_drop_id IN (:a,:b)", a=d1, b=d2) == 0
    assert count(engine, "notifications", "job_id IN (:a,:b)", a=j_study, b=j_study2) == 0
    assert count(engine, "job_steps", "job_id IN (:a,:b)", a=j_study, b=j_study2) == 0
    # 폴더: 원래 자리 없음, _trash 로 이동(내용 보존), 다른 스터디는 그대로
    assert not (esl_root / "_doe" / sid).exists() and not (esl_root / "_verify" / d1).exists()
    names = trash_names(esl_root)
    assert len(names) == 3 and sorted(n.split("_", 1)[1] for n in names) == sorted(
        [f"DOE_{sid}", f"VERIFY_{d1}", f"VERIFY_{d2}"])
    moved = next(n for n in names if n.endswith(f"DOE_{sid}"))
    assert (esl_root / "_trash" / moved / "sub" / "data.bin").read_bytes() == b"x" * 100
    assert (esl_root / "_doe" / other).is_dir() and count(engine, "bead_does", "id=:i", i=other) == 1
    # 삭제 기록
    row = deletion_row(engine, "DOE", sid)
    assert row["purge_state"] == "PENDING" and row["purge_attempts"] == 0 and row["id"] == b["deletion_id"]
    assert row["project_id"] == "p-1" and row["title"] == "스터디" and row["deleted_by"] == "u-power"
    assert row["deleted_by_name"] == "파워" and row["item_created_by_name"] == "파워"
    assert row["summary"]["n_jobs"] == n_jobs and row["summary"]["n_verify_drops"] == 2
    assert row["summary"]["scenario"] == "same" and row["summary"]["phase"] == "DONE"
    assert {j_study, j_study2} <= set(row["summary"]["job_ids"]) and len(row["summary"]["job_ids"]) == n_jobs
    assert {e["rel"] for e in row["dirs"]} == {f"_doe/{sid}", f"_verify/{d1}", f"_verify/{d2}"}
    assert {e["trash_name"] for e in row["dirs"]} == set(names)


def test_v1_summary_job_ids_capped_by_setting(client, engine, esl_root, app_ctx):
    iid = seed_item(engine, esl_root, "OPT")
    ids = [seed_job(engine, "OPT", iid, "SUCCEEDED") for _ in range(3)]
    s = app_ctx.config.settings
    app_ctx.config.settings = s.model_copy(update={"item_delete": s.item_delete.model_copy(update={"summary_job_ids_max": 2})})
    assert delete(client, "OPT", iid).status_code == 200
    row = deletion_row(engine, "OPT", iid)
    assert row["summary"]["n_jobs"] == 3 and len(row["summary"]["job_ids"]) == 2 and set(row["summary"]["job_ids"]) <= set(ids)


# ---------------------------------------------------------------- V-DEL-2
@pytest.mark.parametrize("kind", ["OPT", "ANALYSIS", "COMPARE"])
def test_v2_other_kinds_delete(client, engine, esl_root, kind):
    iid = seed_item(engine, esl_root, kind)
    seed_job(engine, kind, iid, "SUCCEEDED")
    seed_job(engine, kind, iid, "FAILED")
    r = delete(client, kind, iid)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["kind"] == kind and b["purge"] == "PENDING" and b["n_jobs"] == 2 and b["n_verify_drops"] == 0
    assert count(engine, TABLE[kind], "id=:i", i=iid) == 0 and count(engine, "jobs", f"{SUBJ_COL[kind]}=:i", i=iid) == 0
    assert not (esl_root / KDIR[kind] / iid).exists()
    assert trash_names(esl_root) and trash_names(esl_root)[0].endswith(f"_{kind}_{iid}")
    assert deletion_row(engine, kind, iid)["purge_state"] == "PENDING"


def test_v2_analysis_delete_sets_null_on_opt_runs_keeps_runs(client, engine, esl_root):
    aid = seed_item(engine, esl_root, "ANALYSIS")
    seed_job(engine, "ANALYSIS", aid)
    runs = []
    for _ in range(2):
        rid = seed_item(engine, esl_root, "OPT")
        with engine.begin() as c:
            c.execute(text("UPDATE opt_runs SET analysis_id=:a WHERE id=:r"), {"a": aid, "r": rid})
        runs.append(rid)
    chk = client.get(f"{API}/library/analyses/{aid}/delete-check", headers=R)
    assert chk.status_code == 200 and chk.json()["n_opt_unlinked"] == 2
    r = delete(client, "ANALYSIS", aid)
    assert r.status_code == 200 and r.json()["n_opt_unlinked"] == 2 and r.json()["n_jobs"] == 1
    for rid in runs:
        assert count(engine, "opt_runs", "id=:i AND analysis_id IS NULL", i=rid) == 1       # 최적화 행 유지, 연결만 끊김
        assert (esl_root / "_opt" / rid).is_dir()                                            # 폴더도 그대로
        g = client.get(f"{API}/opt/runs/{rid}", headers=R)
        assert g.status_code == 200 and g.json()["analysis_id"] is None
    assert deletion_row(engine, "ANALYSIS", aid)["summary"]["n_opt_unlinked"] == 2


# ---------------------------------------------------------------- V-DEL-3
def _snapshot(engine, esl_root, kind, iid):
    return (count(engine, TABLE[kind], "id=:i", i=iid), count(engine, "jobs", f"{SUBJ_COL[kind]}=:i", i=iid),
            sorted(os.listdir(esl_root / KDIR[kind] / iid)), trash_names(esl_root))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_v3_active_job_blocks(client, engine, esl_root, kind, state):
    iid = seed_item(engine, esl_root, kind)
    jid = seed_job(engine, kind, iid, state)
    before = _snapshot(engine, esl_root, kind, iid)
    r = delete(client, kind, iid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ITEM_BUSY", r.text
    blk = r.json()["detail"]["blocked"]
    assert r.json()["detail"]["details"]["blocked"] == blk                      # 계약 §1 details.blocked[] 도 같은 값
    assert len(blk) == 1 and blk[0]["code"] == "JOB_ACTIVE" and blk[0]["job_id"] == jid
    assert blk[0]["state"] == state and blk[0]["job_type"] == JOB_TYPE[kind] and blk[0]["verify_drop_id"] is None
    assert _snapshot(engine, esl_root, kind, iid) == before and deletion_row(engine, kind, iid) is None


def test_v3_cancel_requested_running_still_blocks(client, engine, esl_root):
    iid = seed_item(engine, esl_root, "OPT")
    jid = seed_job(engine, "OPT", iid, "RUNNING")
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET cancel_requested_at=now(), cancel_requested_by='u-power' WHERE id=:i"), {"i": jid})
    r = delete(client, "OPT", iid)
    assert r.status_code == 409 and r.json()["detail"]["blocked"][0]["state"] == "RUNNING"
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1 and (esl_root / "_opt" / iid).is_dir()
    with engine.begin() as c:                                    # 워커가 종료시킨 뒤에는 삭제 가능
        c.execute(text("UPDATE jobs SET state='CANCELED', holds_slot=false, finished_at=now() WHERE id=:i"), {"i": jid})
    assert delete(client, "OPT", iid).status_code == 200


def test_v3_list_flags_and_delete_check(client, engine, esl_root):
    ids = {k: seed_item(engine, esl_root, k) for k in KINDS}
    busy = {k: seed_item(engine, esl_root, k) for k in KINDS}
    for k in KINDS:
        seed_job(engine, k, ids[k], "SUCCEEDED")
        seed_job(engine, k, busy[k], "RUNNING")
    for k in KINDS:
        lst = client.get(f"{API}/{URL[k]}?project_id=p-1", headers=R)
        assert lst.status_code == 200, lst.text
        by = {x["id"]: x for x in lst.json()}
        assert by[ids[k]]["can_delete"] is True and by[ids[k]]["delete_blocked"] is None
        assert by[busy[k]]["can_delete"] is True and by[busy[k]]["delete_blocked"]
        one = client.get(f"{API}/{URL[k]}/{busy[k]}", headers=R).json()
        assert one["delete_blocked"] == by[busy[k]]["delete_blocked"]
        # 권한이 없는 사용자: can_delete false(막힘 사유는 그대로)
        o = client.get(f"{API}/{URL[k]}?project_id=p-1", headers=H("tok-power2")).json()
        assert {x["id"]: x["can_delete"] for x in o}[ids[k]] is False
        adm = client.get(f"{API}/{URL[k]}?project_id=p-1", headers=H("tok-admin")).json()
        assert {x["id"]: x["can_delete"] for x in adm}[ids[k]] is True
        # delete-check
        c1 = client.get(f"{API}/{URL[k]}/{ids[k]}/delete-check", headers=R)
        assert c1.status_code == 200, c1.text
        b = c1.json()
        assert b["kind"] == k and b["id"] == ids[k] and b["can_delete"] is True and b["blocked"] == [] and b["n_jobs"] == 1
        assert b["folders"] == [{"rel": f"{KDIR[k]}/{ids[k]}", "exists": True}] and b["title"]
        c2 = client.get(f"{API}/{URL[k]}/{busy[k]}/delete-check", headers=R).json()
        assert c2["can_delete"] is False and c2["blocked"][0]["code"] == "JOB_ACTIVE"
        assert client.get(f"{API}/{URL[k]}/{ids[k]}/delete-check", headers=H("tok-power2")).status_code == 403
        assert client.get(f"{API}/{URL[k]}/{uuid.uuid4()}/delete-check", headers=R).json()["detail"]["code"] == NOT_FOUND[k]
    assert count(engine, "bead_does") == 2 and count(engine, "jobs") == 8        # delete-check 는 아무것도 바꾸지 않음


# ---------------------------------------------------------------- V-DEL-4
def test_v4_verify_drop_and_scx_submission_block_study(client, engine, esl_root, inputs_root):
    sid = seed_item(engine, esl_root, "DOE")
    seed_job(engine, "DOE", sid, "SUCCEEDED")
    d_run = seed_drop(engine, esl_root, inputs_root, sid, phase="RUNNING", sub_state=None, job_state=None, n=1)
    r = delete(client, "DOE", sid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ITEM_BUSY"
    blk = r.json()["detail"]["blocked"]
    assert [b["code"] for b in blk] == ["VERIFY_DROP_ACTIVE"] and blk[0]["verify_drop_id"] == d_run
    # 검증 낙하가 종료돼도 그 낙하의 작업이 비종료면 막힘
    with engine.begin() as c:
        c.execute(text("UPDATE verify_drops SET phase='CANCELED' WHERE id=:i"), {"i": d_run})
    j = seed_job(engine, "VERIFY", d_run, "RUNNING")
    blk = delete(client, "DOE", sid).json()["detail"]["blocked"]
    assert [b["code"] for b in blk] == ["VERIFY_JOB_ACTIVE"] and blk[0]["job_id"] == j and blk[0]["verify_drop_id"] == d_run
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='CANCELED', holds_slot=false, finished_at=now() WHERE id=:i"), {"i": j})
    # SCX 제출 UNKNOWN(원격 SCX 잡 고아 방지) — drop 은 종료여도 막힘
    d_unk = seed_drop(engine, esl_root, inputs_root, sid, phase="FAILED", sub_state="UNKNOWN", job_state=None, n=2)
    r = delete(client, "DOE", sid)
    assert r.status_code == 409
    blk = r.json()["detail"]["blocked"]
    assert [b["code"] for b in blk] == ["SCX_SUBMISSION_ACTIVE"] and blk[0]["verify_drop_id"] == d_unk
    chk = client.get(f"{API}/doe/studies/{sid}/delete-check", headers=R).json()
    assert chk["can_delete"] is False and chk["n_verify_drops"] == 2
    lst = {x["id"]: x for x in client.get(f"{API}/doe/studies?project_id=p-1", headers=R).json()}
    assert "SCX" in lst[sid]["delete_blocked"]
    for state in ("SUBMITTING", "SUBMITTED"):
        with engine.begin() as c:
            c.execute(text("UPDATE scx_submissions SET state=:s WHERE verify_drop_id=:d"), {"s": state, "d": d_unk})
        assert delete(client, "DOE", sid).status_code == 409
    assert count(engine, "bead_does", "id=:i", i=sid) == 1 and (esl_root / "_doe" / sid).is_dir() and not trash_names(esl_root)
    with engine.begin() as c:                                     # 제출이 정리(ABANDONED)되면 삭제 가능
        c.execute(text("UPDATE scx_submissions SET state='ABANDONED' WHERE verify_drop_id=:d"), {"d": d_unk})
    assert delete(client, "DOE", sid).status_code == 200


# ---------------------------------------------------------------- V-DEL-5
def test_v5_race_fk_violation_is_busy_and_restores_folder(client, engine, esl_root, monkeypatch):
    """job 목록을 읽은 뒤 늦게 끼어든(종료 상태라 차단 검사엔 안 걸린) job → ⑦ 항목 행 삭제의 FK 위반 = 409 ITEM_BUSY, 폴더 restore."""
    from esl_platform.api.services import item_delete as svc

    iid = seed_item(engine, esl_root, "OPT")
    seed_job(engine, "OPT", iid, "SUCCEEDED")
    late = seed_job(engine, "OPT", iid, "SUCCEEDED")
    real = svc._job_ids
    monkeypatch.setattr(svc, "_job_ids", lambda *a, **k: [j for j in real(*a, **k) if j != late])   # 늦게 생긴 job 을 못 본 것처럼
    r = delete(client, "OPT", iid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ITEM_BUSY", r.text
    assert "blocked" in r.json()["detail"]
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1 and count(engine, "jobs", "opt_run_id=:i", i=iid) == 2
    assert (esl_root / "_opt" / iid / "report.html").is_file()           # restore 로 원래 자리
    assert trash_names(esl_root) == [] and deletion_row(engine, "OPT", iid) is None
    monkeypatch.undo()
    assert delete(client, "OPT", iid).status_code == 200                 # 경합이 사라지면 정상 삭제


def test_v5_deadlock_is_busy(client, engine, esl_root, monkeypatch):
    from esl_platform.api.services import item_delete as svc
    from sqlalchemy.exc import OperationalError

    class Orig(Exception):
        sqlstate = "40P01"

    iid = seed_item(engine, esl_root, "COMPARE")

    def boom(*a, **k):
        raise OperationalError("DELETE", {}, Orig("deadlock detected"))

    monkeypatch.setattr(svc, "_job_ids", boom)
    r = delete(client, "COMPARE", iid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ITEM_BUSY"
    assert count(engine, "comparisons", "id=:i", i=iid) == 1 and (esl_root / "_compare" / iid).is_dir()


def test_v5_commit_failure_restores_folders(client, engine, esl_root, monkeypatch):
    from esl_platform.api.services import item_delete as svc

    iid = seed_item(engine, esl_root, "ANALYSIS")

    def boom(*a, **k):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(svc.del_repo, "insert_deletion", boom)
    with pytest.raises(RuntimeError):
        delete(client, "ANALYSIS", iid)
    assert count(engine, "analysis_runs", "id=:i", i=iid) == 1 and (esl_root / "_analysis" / iid / "report.html").is_file()
    assert trash_names(esl_root) == []


# ---------------------------------------------------------------- V-DEL-6
@pytest.mark.parametrize("kind", KINDS)
def test_v6_permissions(client, engine, esl_root, kind):
    iid = seed_item(engine, esl_root, kind)
    r = delete(client, kind, iid, OTHER)                                 # 같은 프로젝트 power 지만 등록자 아님
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NOT_ITEM_OWNER"
    r = delete(client, kind, iid, GENERAL)                               # viewer·general: 실행 권한 없음
    assert r.status_code == 403 and r.json()["detail"]["code"] != "NOT_ITEM_OWNER"
    assert delete(client, kind, iid, H("tok-nonmember", True)).status_code == 403
    assert client.delete(f"{API}/{URL[kind]}/{iid}", headers=R).json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    assert client.delete(f"{API}/{URL[kind]}/{iid}").status_code == 401
    assert count(engine, TABLE[kind], "id=:i", i=iid) == 1 and not trash_names(esl_root)
    r = delete(client, kind, iid, ADMIN)                                 # 전역 관리자
    assert r.status_code == 200
    mine = seed_item(engine, esl_root, kind)
    assert delete(client, kind, mine, W).status_code == 200              # 등록자 본인


# ---------------------------------------------------------------- V-DEL-7
@pytest.mark.parametrize("kind", KINDS)
def test_v7_idempotent_and_not_found(client, engine, esl_root, kind):
    iid = seed_item(engine, esl_root, kind)
    assert delete(client, kind, iid).status_code == 200
    r = delete(client, kind, iid)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "ITEM_DELETED"
    assert client.get(f"{API}/{URL[kind]}/{iid}/delete-check", headers=R).json()["detail"]["code"] == "ITEM_DELETED"
    assert client.get(f"{API}/{URL[kind]}/{iid}", headers=R).json()["detail"]["code"] == NOT_FOUND[kind]
    r = delete(client, kind, str(uuid.uuid4()))
    assert r.status_code == 404 and r.json()["detail"]["code"] == NOT_FOUND[kind]
    assert count(engine, "deletions", "kind=:k AND item_id=:i", k=kind, i=iid) == 1


# ---------------------------------------------------------------- V-DEL-8
def test_v8_dir_rel_tamper_is_path_unsafe(client, engine, esl_root):
    from esl_platform.core import trash

    sid = seed_item(engine, esl_root, "DOE")
    victim = esl_root / "_doe" / str(uuid.uuid4())
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("k")
    for bad in (f"_doe/{victim.name}", f"_opt/{sid}", f"_doe/{sid}/x", f"x/{sid}", f"_doe//{sid}"):
        with engine.begin() as c:
            c.execute(text("UPDATE bead_does SET dir_rel=:d WHERE id=:i"), {"d": bad, "i": sid})
        r = delete(client, "DOE", sid)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE", (bad, r.text)
    assert count(engine, "bead_does", "id=:i", i=sid) == 1 and (victim / "keep.txt").is_file()
    assert (esl_root / "_doe" / sid / "report.html").is_file() and not trash_names(esl_root)
    # 함수 수준: `..`·절대경로·형식이 다른 id·알 수 없는 종류
    s = client.app.state.ctx.settings
    ok = str(uuid.uuid4())
    for kind, iid, rel in [("DOE", ok, "_doe/../x"), ("DOE", ok, f"_doe/../{ok}"), ("DOE", "..", None),
                           ("DOE", "../" + ok, None), ("DOE", ok.upper(), None), ("DOE", ok + "/x", None),
                           ("DOE", "", None), ("NOPE", ok, None), ("DOE", ok, "/abs/path"), ("OPT", ok, f"_doe/{ok}")]:
        with pytest.raises(trash.PathUnsafe):
            trash.item_dir(s, kind, iid, rel)
        with pytest.raises(trash.PathUnsafe):
            trash.move_to_trash(s, kind, iid, rel)
    assert trash.item_dir(s, "DOE", ok, f"_doe/{ok}") == str(esl_root / "_doe" / ok)


# ---------------------------------------------------------------- V-DEL-9
def test_v9_item_folder_symlink_rejected(client, engine, esl_root, tmp_path):
    iid = seed_item(engine, esl_root, "OPT", folder=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("p")
    (esl_root / "_opt").mkdir(exist_ok=True)
    os.symlink(outside, esl_root / "_opt" / iid, target_is_directory=True)
    r = delete(client, "OPT", iid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    assert (outside / "precious.txt").read_text() == "p" and (esl_root / "_opt" / iid).is_symlink()
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1 and not trash_names(esl_root)
    assert client.get(f"{API}/opt/runs/{iid}/delete-check", headers=R).status_code == 422


def test_v9_kind_dir_symlink_rejected(client, engine, esl_root, tmp_path):
    sid = str(uuid.uuid4())
    real = tmp_path / "real_doe"
    (real / sid).mkdir(parents=True)
    (real / sid / "precious.txt").write_text("p")
    os.symlink(real, esl_root / "_doe", target_is_directory=True)
    seed_item(engine, esl_root, "DOE", folder=False, item_id=sid)
    r = delete(client, "DOE", sid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    assert (real / sid / "precious.txt").read_text() == "p" and count(engine, "bead_does", "id=:i", i=sid) == 1


def test_v9_trash_dir_symlink_rejected(client, engine, esl_root, tmp_path):
    iid = seed_item(engine, esl_root, "COMPARE")
    outside = tmp_path / "somewhere"
    outside.mkdir()
    os.symlink(outside, esl_root / "_trash", target_is_directory=True)
    r = delete(client, "COMPARE", iid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    assert os.listdir(outside) == [] and (esl_root / "_compare" / iid / "report.html").is_file()
    assert count(engine, "comparisons", "id=:i", i=iid) == 1


@pytest.mark.parametrize("which", ["item", "kind", "trash"])
def test_v9_junction_mock_rejected(client, engine, esl_root, monkeypatch, which):
    """Windows junction·reparse point(is_link_like 모의) — 심링크가 아니어도 같은 거부."""
    from esl_platform.core import trash

    iid = seed_item(engine, esl_root, "ANALYSIS")
    (esl_root / "_trash").mkdir(exist_ok=True)
    target = {"item": esl_root / "_analysis" / iid, "kind": esl_root / "_analysis", "trash": esl_root / "_trash"}[which]
    real = trash.is_link_like
    monkeypatch.setattr(trash, "is_link_like", lambda p: os.path.normpath(p) == os.path.normpath(target) or real(p))
    r = delete(client, "ANALYSIS", iid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    assert (target / "report.html").is_file() if which == "item" else (esl_root / "_analysis" / iid / "report.html").is_file()
    assert count(engine, "analysis_runs", "id=:i", i=iid) == 1 and trash_names(esl_root) == []


def test_v9_study_second_folder_symlink_rejects_before_any_move(client, engine, esl_root, inputs_root, tmp_path):
    sid = seed_item(engine, esl_root, "DOE")
    did = seed_drop(engine, esl_root, inputs_root, sid, n=1)
    import shutil

    outside = tmp_path / "out2"
    outside.mkdir()
    shutil.rmtree(esl_root / "_verify" / did)
    os.symlink(outside, esl_root / "_verify" / did, target_is_directory=True)
    r = delete(client, "DOE", sid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE"
    assert (esl_root / "_doe" / sid / "report.html").is_file() and not trash_names(esl_root)   # 아무것도 옮기지 않음
    assert count(engine, "bead_does", "id=:i", i=sid) == 1


# ---------------------------------------------------------------- V-DEL-10
@pytest.mark.parametrize("root", ["input_roots", "upload_root", "spdm_roots"])
@pytest.mark.parametrize("level", ["item", "parent"])
def test_v10_overlap_with_protected_roots(client, engine, esl_root, app_ctx, root, level):
    iid = seed_item(engine, esl_root, "DOE")
    s = app_ctx.config.settings
    bad = str(esl_root / "_doe" / iid) if level == "item" else str(esl_root / "_doe")
    st = s.storage
    upd = {"input_roots": {"input_roots": [*st.input_roots, bad]}, "upload_root": {"upload_root": bad},
           "spdm_roots": {"spdm_roots": [*st.spdm_roots, bad]}}[root]
    app_ctx.config.settings = s.model_copy(update={"storage": st.model_copy(update=upd)})
    r = delete(client, "DOE", iid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE", r.text
    assert (esl_root / "_doe" / iid / "report.html").is_file() and count(engine, "bead_does", "id=:i", i=iid) == 1
    assert not trash_names(esl_root)


# ---------------------------------------------------------------- V-DEL-11
def _lock_error():
    e = PermissionError(13, "sharing violation")
    e.winerror = 32                     # Windows WinError 32 모의(POSIX 에서도 속성만 있으면 is_lock_error)
    return e


def _flaky_replace(monkeypatch, esl_root: Path, n_fail: int):
    real = os.replace
    calls = {"n": 0}

    def rep(src, dst, *a, **k):
        if os.path.normpath(str(src)).startswith(os.path.normpath(str(esl_root))) and os.path.basename(str(dst)).count("_") >= 2:
            calls["n"] += 1
            if calls["n"] <= n_fail:
                raise _lock_error()
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", rep)
    return calls


def test_v11_lock_retries_then_succeeds(client, engine, esl_root, monkeypatch):
    iid = seed_item(engine, esl_root, "OPT")
    calls = _flaky_replace(monkeypatch, esl_root, 2)             # attempts=3 → n−1 번 실패 뒤 성공
    r = delete(client, "OPT", iid)
    assert r.status_code == 200, r.text
    assert calls["n"] == 3 and count(engine, "opt_runs", "id=:i", i=iid) == 0 and len(trash_names(esl_root)) == 1


def test_v11_lock_exhausted_is_file_locked_and_rolls_back(client, engine, esl_root, monkeypatch):
    iid = seed_item(engine, esl_root, "OPT")
    seed_job(engine, "OPT", iid, "SUCCEEDED")
    calls = _flaky_replace(monkeypatch, esl_root, 99)
    r = delete(client, "OPT", iid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FILE_LOCKED", r.text
    d = r.json()["detail"]
    assert d["path"] == d["details"]["path"] == f"_opt/{iid}" and str(esl_root) not in r.text          # 마스킹한 표시 경로
    assert calls["n"] == 3
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1 and count(engine, "jobs", "opt_run_id=:i", i=iid) == 1
    assert (esl_root / "_opt" / iid / "report.html").is_file() and trash_names(esl_root) == []
    assert deletion_row(engine, "OPT", iid) is None
    monkeypatch.undo()
    assert delete(client, "OPT", iid).status_code == 200


# ---------------------------------------------------------------- V-DEL-12
def test_v12_second_folder_move_fails_restores_first(client, engine, esl_root, inputs_root, monkeypatch):
    sid = seed_item(engine, esl_root, "DOE")
    seed_job(engine, "DOE", sid, "SUCCEEDED")
    d1 = seed_drop(engine, esl_root, inputs_root, sid, n=1)
    d2 = seed_drop(engine, esl_root, inputs_root, sid, n=2)
    real = os.replace

    def rep(src, dst, *a, **k):
        if os.path.basename(str(src)) == d2 and "_trash" in str(dst):
            raise _lock_error()                       # 두 번째(또는 세 번째) 폴더 이동이 끝까지 잠김
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", rep)
    r = delete(client, "DOE", sid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FILE_LOCKED"
    assert r.json()["detail"]["path"] == f"_verify/{d2}"
    for kind, i in (("DOE", sid), ("VERIFY", d1), ("VERIFY", d2)):                  # 이미 옮긴 것은 역순 restore
        assert (esl_root / KDIR[kind] / i / "report.html").is_file(), (kind, i)
    assert trash_names(esl_root) == []
    assert count(engine, "bead_does", "id=:i", i=sid) == 1 and count(engine, "verify_drops", "bead_doe_id=:i", i=sid) == 2
    assert count(engine, "jobs", "bead_doe_id=:i", i=sid) == 1 and deletion_row(engine, "DOE", sid) is None


# ---------------------------------------------------------------- V-DEL-13
@pytest.mark.parametrize("kind", KINDS)
def test_v13_no_folder_is_absent(client, engine, esl_root, kind):
    iid = seed_item(engine, esl_root, kind, folder=False, phase="FAILED")
    seed_job(engine, kind, iid, "FAILED")
    r = delete(client, kind, iid)
    assert r.status_code == 200, r.text
    assert r.json()["purge"] == "ABSENT" and r.json()["n_jobs"] == 1
    row = deletion_row(engine, kind, iid)
    assert row["purge_state"] == "ABSENT" and row["dirs"] == [] and not trash_names(esl_root)
    assert count(engine, TABLE[kind], "id=:i", i=iid) == 0


def test_v13_delete_check_reports_missing_folder(client, engine, esl_root):
    iid = seed_item(engine, esl_root, "COMPARE", folder=False)
    c = client.get(f"{API}/library/comparisons/{iid}/delete-check", headers=R).json()
    assert c["folders"] == [{"rel": f"_compare/{iid}", "exists": False}] and c["can_delete"] is True


# ---------------------------------------------------------------- V-DEL-17 (+)
def test_v17_inputs_untouched_and_no_relay_calls(tmp_path, engine, fake_dashboard, clock):
    """업로드 파일·Case 폴더·SPDM 폴더의 sha256 이 삭제 전후 같고, 삭제 흐름은 SCX 릴레이를 호출하지 않는다."""
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient
    from scx_support import start_relay
    from verify_support import seed_case, seed_entry_for, verify_settings

    relay = start_relay(tmp_path / "drive")
    sd = verify_settings(tmp_path, relay)
    sd["worker"]["fs_retry"] = {"attempts": 3, "max_wait_s": 0.5, "base_s": 0.001}
    lc = load_config_dict(sd, environ={})
    assert lc.ok, lc.errors()
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock)
    esl_root = Path(sd["storage"]["esl_root"])
    inputs_root = Path(sd["storage"]["input_roots"][0])
    upload_root = Path(sd["storage"]["upload_root"])
    spdm = Path(sd["storage"]["spdm_roots"][0])
    (upload_root / "power" / "20261112-000000_x" / "rad").mkdir(parents=True)
    (upload_root / "power" / "20261112-000000_x" / "rad" / "a_0000.rad").write_bytes(b"/BEGIN\n" * 100)
    spdm.mkdir(parents=True, exist_ok=True)
    (spdm / "model.dat").write_bytes(b"spdm")
    sid = seed_item(engine, esl_root, "DOE")
    seed_job(engine, "DOE", sid, "SUCCEEDED")
    case = seed_case(engine, esl_root, inputs_root, "k1")
    eid = seed_entry_for(engine, case["id"])
    did = str(uuid.uuid4())
    from esl_platform.core.repositories import verify as verify_repo

    with engine.begin() as c:
        verify_repo.insert_drop(c, id=did, batch_id=str(uuid.uuid4()), project_id="p-1", bead_doe_id=sid, design_id="d007",
                                case_id=case["id"], entry_id=eid, phase="DONE", drive_dir_rel="share/drop/x",
                                dir_rel=f"_verify/{did}", created_by="u-power", created_by_name="파워")
    _put_folder(esl_root, "VERIFY", did)
    before = {n: sha_tree(p) for n, p in (("inputs", inputs_root), ("upload", upload_root), ("spdm", spdm),
                                          ("case", esl_root / case["folder"]))}
    assert before["inputs"] and before["upload"] and before["spdm"] and before["case"]
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as cl:
        n_req = len(relay.requests)
        r = cl.delete(f"{API}/doe/studies/{sid}", headers=W)
        assert r.status_code == 200, r.text
        assert r.json()["n_verify_drops"] == 1
        assert len(relay.requests) == n_req and not relay.adapter_calls            # 릴레이 호출 0회
    after = {n: sha_tree(p) for n, p in (("inputs", inputs_root), ("upload", upload_root), ("spdm", spdm),
                                         ("case", esl_root / case["folder"]))}
    assert after == before
    assert (esl_root / case["folder"]).is_dir()                                    # Case 는 삭제 대상이 아님
    assert count(engine, "cases", "id=:i", i=case["id"]) == 1 and count(engine, "library_entries", "id=:i", i=eid) == 1


def test_plus_history_notifications_and_job_gone(client, engine, esl_root):
    iid = seed_item(engine, esl_root, "OPT")
    j = seed_job(engine, "OPT", iid, "SUCCEEDED")
    other = seed_item(engine, esl_root, "OPT")
    j2 = seed_job(engine, "OPT", other, "SUCCEEDED")
    before = client.get(f"{API}/history?project_id=p-1", headers=R)
    assert before.status_code == 200
    assert j in str(before.json()) and j2 in str(before.json())
    assert delete(client, "OPT", iid).status_code == 200
    after = client.get(f"{API}/history?project_id=p-1", headers=R)
    assert after.status_code == 200 and j not in str(after.json()) and j2 in str(after.json())
    assert client.get(f"{API}/jobs/{j}", headers=R).json()["detail"]["code"] == "JOB_NOT_FOUND"
    assert count(engine, "notifications", "job_id=:i", i=j) == 0 and count(engine, "notifications", "job_id=:i", i=j2) == 1


def test_plus_item_delete_cfg_defaults_equal_trash_defaults_and_yaml():
    import yaml
    from esl_platform.core import trash
    from esl_platform.core.config import ItemDeleteCfg, load_config_dict
    from esl_test_support import PLATFORM_EXAMPLE, REPO

    assert ItemDeleteCfg().model_dump() == trash.DEFAULTS
    assert set(trash.DEFAULTS) == {"enabled", "purge_interval_s", "purge_batch", "purge_max_attempts", "summary_job_ids_max"}
    for f in (PLATFORM_EXAMPLE, REPO / "config" / "esl_platform.prod.example.yaml"):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert d["item_delete"] == trash.DEFAULTS, f
    d = yaml.safe_load(PLATFORM_EXAMPLE.read_text(encoding="utf-8"))
    d.pop("item_delete")                                                  # 섹션 없으면 기본값
    # 키 오타·범위 밖은 거부
    for bad in ({"enabled": True, "purge_interval_s": 0}, {"purge_batch": 0}, {"purge_max_attempts": 0}, {"bogus": 1},
                {"summary_job_ids_max": -1}):
        lc = load_config_dict({**d, "item_delete": bad}, environ={})
        assert any(k.startswith("item_delete") for k in lc.error_keys()), bad


def test_plus_disabled_returns_503_and_can_delete_false(client, engine, esl_root, app_ctx):
    iid = seed_item(engine, esl_root, "DOE")
    s = app_ctx.config.settings
    app_ctx.config.settings = s.model_copy(update={"item_delete": s.item_delete.model_copy(update={"enabled": False})})
    r = delete(client, "DOE", iid)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ITEM_DELETE_DISABLED"
    assert client.get(f"{API}/doe/studies/{iid}/delete-check", headers=R).json()["detail"]["code"] == "ITEM_DELETE_DISABLED"
    lst = client.get(f"{API}/doe/studies?project_id=p-1", headers=R).json()
    assert lst[0]["can_delete"] is False
    assert count(engine, "bead_does", "id=:i", i=iid) == 1 and (esl_root / "_doe" / iid).is_dir()


def test_plus_config_invalid_blocks_delete(client, engine, esl_root, app_ctx):
    iid = seed_item(engine, esl_root, "OPT")
    from esl_platform.core.config import Issue

    app_ctx.config.issues.append(Issue("x", "broken"))
    r = delete(client, "OPT", iid)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "CONFIG_INVALID"
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1


def test_plus_same_second_trash_name_collision(client, engine, esl_root):
    """같은 항목이 같은 초에 두 번 휴지통에 들어오는 극단 경우에도 이름이 겹치지 않는다."""
    from esl_platform.core import trash

    s = client.app.state.ctx.settings
    iid = str(uuid.uuid4())
    names = []
    for _ in range(2):
        _put_folder(esl_root, "OPT", iid)
        mv = trash.move_to_trash(s, "OPT", iid)
        names.append(mv.trash_name)
        assert trash.parse_trash_name(mv.trash_name)[1:] == ("OPT", iid)
    assert len(set(names)) == 2 and sorted(trash_names(esl_root)) == sorted(names)
    assert trash.move_to_trash(s, "OPT", iid) is None                   # 폴더 없음 → None


def test_plus_trash_restore_function(client, esl_root):
    from esl_platform.core import trash

    s = client.app.state.ctx.settings
    iid = str(uuid.uuid4())
    _put_folder(esl_root, "COMPARE", iid)
    mv = trash.move_to_trash(s, "COMPARE", iid)
    assert not (esl_root / "_compare" / iid).exists() and (esl_root / "_trash" / mv.trash_name).is_dir()
    (esl_root / "_compare" / iid).mkdir()                               # 원래 자리가 차 있으면 되돌리지 않음
    assert trash.restore(s, mv) is False and (esl_root / "_trash" / mv.trash_name).is_dir()
    (esl_root / "_compare" / iid).rmdir()
    assert trash.restore(s, mv) is True and (esl_root / "_compare" / iid / "report.html").is_file()
    assert trash.restore(s, mv) is False                                # 이미 되돌림
    bad = trash.TrashMove(src=mv.src, dst=mv.dst, kind="OPT", item_id=mv.item_id, trash_name=mv.trash_name)
    assert trash.restore(s, bad) is False                               # 이름·종류 불일치


def test_plus_parse_trash_name():
    from esl_platform.core import trash

    u = str(uuid.uuid4())
    assert trash.parse_trash_name(f"20261112-153045_DOE_{u}") == ("20261112-153045", "DOE", u)
    assert trash.parse_trash_name(f"20261112-153045_VERIFY_{u}")[1] == "VERIFY"
    for bad in ("", "x", f"20261112-153045_DOE_{u}x", f"20261112-153045_NOPE_{u}", f"20261340-153045_DOE_{u}",
                f"20261112-153045_DOE_{u.upper()}", f"2026111-153045_DOE_{u}", f"20261112-153045_DOE_not-a-uuid",
                f"20261112-153045_DOE_{u}/x", f"../20261112-153045_DOE_{u}"):
        assert trash.parse_trash_name(bad) is None, bad
    assert trash.parse_trash_name(None) is None


# ---------------------------------------------------------------- 마이그레이션·점검
def test_plus_migration_0016_from_0015(engine, db_url):
    from alembic import command
    from alembic.config import Config
    from esl_test_support import REPO

    def cfg():
        c = Config(str(REPO / "alembic.ini"))
        c.attributes["url"] = db_url
        return c

    with engine.begin() as c:
        c.execute(text("DROP TABLE deletions"))
        c.execute(text("UPDATE alembic_version SET version_num='0015'"))
    command.upgrade(cfg(), "head")
    command.upgrade(cfg(), "head")                                       # 멱등
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
        idx = {r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='deletions'"))}
        cons = {r[0] for r in c.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='deletions'::regclass"))}
    assert {"ix_deletions_project", "ux_deletions_kind_item", "ix_deletions_purge"} <= idx
    assert {"ck_deletions_kind", "ck_deletions_purge_state", "ck_deletions_purge_attempts"} <= cons
    with engine.begin() as c:
        ins = ("INSERT INTO deletions (id, kind, item_id, project_id, deleted_by, deleted_by_name, purge_state)"
               " VALUES (:i,:k,:t,'p-1','u','u',:s)")
        c.execute(text(ins), {"i": "a", "k": "DOE", "t": "x1", "s": "PENDING"})
    for k, s in (("BAD", "PENDING"), ("DOE", "BAD")):
        with pytest.raises(Exception), engine.begin() as c:
            c.execute(text(ins), {"i": "b", "k": k, "t": "x2", "s": s})
    with pytest.raises(Exception), engine.begin() as c:                  # (kind, item_id) UNIQUE
        c.execute(text(ins), {"i": "c", "k": "DOE", "t": "x1", "s": "PENDING"})
    with pytest.raises(Exception):
        command.downgrade(cfg(), "0015")                                 # downgrade 미지원(데이터 보호)


def test_plus_no_cascade_fks(engine):
    """ON DELETE CASCADE 를 추가하지 않는다(명시적 연쇄) — 항목·job 을 가리키는 FK 에 CASCADE 없음."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT conrelid::regclass::text, conname, confdeltype FROM pg_constraint WHERE contype='f' AND confrelid IN"
            " ('bead_does'::regclass,'opt_runs'::regclass,'analysis_runs'::regclass,'comparisons'::regclass,"
            "'verify_drops'::regclass,'jobs'::regclass)")).all()
    assert rows and all(r[2] != "c" for r in rows if r[0] != "opt_keepouts"), rows


def test_plus_check_orphans_and_trash(client, engine, esl_root, app_ctx):
    from esl_platform import check

    s = app_ctx.settings
    iid = seed_item(engine, esl_root, "DOE")                              # 행 있음 → 고아 아님
    orphan = esl_root / "_opt" / str(uuid.uuid4())
    (orphan / "d").mkdir(parents=True)
    (orphan / "d" / "f.bin").write_bytes(b"y" * 2048)
    (esl_root / "_opt" / "not-a-uuid").mkdir()                            # uuid 형식이 아니면 세지 않음
    (esl_root / "_verify").mkdir(exist_ok=True)
    os.symlink(orphan, esl_root / "_verify" / str(uuid.uuid4()), target_is_directory=True)   # 링크는 세지 않음
    with engine.connect() as c:
        items = {i.key: i for i in check.check_deletions(c, s)}
    assert items["storage.orphans"].status == check.WARN
    assert "1개" in items["storage.orphans"].detail and "_opt 1" in items["storage.orphans"].detail
    assert "KB" in items["storage.orphans"].detail or "2.0" in items["storage.orphans"].detail
    assert items["storage.trash"].status == check.OK
    assert orphan.is_dir() and (orphan / "d" / "f.bin").is_file()         # 자동 삭제하지 않음
    import shutil

    shutil.rmtree(orphan)
    with engine.connect() as c:
        assert {i.key: i for i in check.check_deletions(c, s)}["storage.orphans"].status == check.OK
    # 휴지통: FAILED 가 재시도 상한에 닿으면 WARN
    with engine.begin() as c:
        c.execute(text("INSERT INTO deletions (id, kind, item_id, project_id, deleted_by, deleted_by_name, purge_state,"
                       " purge_attempts, purge_error) VALUES ('d1','OPT','x','p-1','u','u','FAILED',:n,'PermissionError')"),
                  {"n": s.item_delete.purge_max_attempts})
    with engine.connect() as c:
        it = {i.key: i for i in check.check_deletions(c, s)}["storage.trash"]
    assert it.status == check.WARN and "FAILED 1" in it.detail and iid
    with engine.begin() as c:
        c.execute(text("UPDATE deletions SET purge_attempts = purge_attempts - 1"))
    with engine.connect() as c:
        assert {i.key: i for i in check.check_deletions(c, s)}["storage.trash"].status == check.OK


def test_plus_check_cli_includes_storage_orphans(tmp_path, settings_dict, engine, db_url, esl_root):
    """check.py 전체 실행(run_checks)에 storage.orphans·storage.trash 가 나온다."""
    import yaml
    from esl_platform import check

    cfgp = tmp_path / "c.yaml"
    cfgp.write_text(yaml.safe_dump(settings_dict), encoding="utf-8")
    orphan = esl_root / "_doe" / str(uuid.uuid4())
    orphan.mkdir(parents=True)
    (orphan / "a").write_bytes(b"1")
    items = check.run_checks(str(cfgp), environ={"ESL_DATABASE_URL": db_url}, min_free_gb=0)
    by = {i.key: i for i in items}
    assert by["storage.orphans"].status == check.WARN and by["storage.trash"].status == check.OK
    items = check.run_checks(str(cfgp), environ={"ESL_DATABASE_URL": db_url}, min_free_gb=0, use_db=False)
    assert "storage.orphans" not in {i.key for i in items}
