"""P1b 검증 결함 회귀 시험(Verifier 재현 시나리오 이식).

1 작업 실행 시점 재검증·Case 단위 직렬화·ESL 실행 스냅샷, 2 EXPORT targets, 3 input_roots 밖 include,
4 Case 폴더명(Windows 예약어·대소문자 무시 UNIQUE), 6 INPUT_CHANGED 재시도, 7 고아 자식·run() 예외 FAILED.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import numpy as np
import pytest
from esl_test_support import API, REPO, H, create_case, wait_for
from sqlalchemy import insert, text, update
from sqlalchemy.exc import IntegrityError

W = H("tok-power", True)
R = H("tok-power")
HERE = os.path.dirname(os.path.abspath(__file__))


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def _run(client, worker, job, lane="SLOT"):
    st = worker.run_once(lane)
    j = _get(client, job["id"])
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _full(client, worker, synth, folder="case01"):
    r = create_case(client, synth, folder=folder, title=folder)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    s = client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    assert s.status_code == 201, s.text
    _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    return cid, client.get(f"{API}/cases/{cid}", headers=R).json(), sug


def _tag(cdir):
    with open(os.path.join(cdir, "04_esl", "esl_summary.json"), encoding="utf-8") as fh:
        return json.load(fh).get("tag")


# ---------------------------------------------------------------- 1. 재검증·직렬화·스냅샷
def test_export_of_old_run_after_new_esl_fails_stale(client, synth_inputs, worker_factory, esl_root):
    """(Verifier test_validate_queued_behind_esl) EXPORT(A) 가 ESL B 뒤에 실행되면 B 의 F_eq 를 쓰지 않고 FAILED."""
    w = worker_factory()
    cid, case, sug = _full(client, w, synth_inputs)
    rid_a = case["current_esl_run_id"]
    cdir = os.path.join(str(esl_root), "case01")
    s = client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": list(reversed(sug["node_ids"]))}, headers=W)
    assert s.status_code == 201
    jb = _job(client, cid, "ESL_SOLVE")
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "VALIDATE", "params": {"esl_run_id": rid_a}},
                    headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    je = _job(client, cid, "EXPORT", {"esl_run_id": rid_a, "targets": ["csv"]})
    _run(client, w, jb)
    rid_b = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    assert rid_b != rid_a
    assert w.run_once("LIGHT") == "FAILED"
    ej = _get(client, je["id"])
    assert ej["failure_code"] == "PREREQUISITE_MISSING"
    assert not os.path.isdir(os.path.join(cdir, "06_export"))
    # 두 실행 모두 스냅샷 보존, 하중표는 각 실행 자신의 F_eq
    run_a = client.get(f"{API}/esl-runs/{rid_a}", headers=R).json()
    run_b = client.get(f"{API}/esl-runs/{rid_b}", headers=R).json()
    assert run_a["dir_rel"] == f"runs/{rid_a}" and run_b["dir_rel"] == f"runs/{rid_b}"
    fa = np.load(os.path.join(cdir, "runs", rid_a, "04_esl", "f_eq.npz"))["f"]
    fb = np.load(os.path.join(cdir, "runs", rid_b, "04_esl", "f_eq.npz"))["f"]
    top_a = client.get(f"{API}/esl-runs/{rid_a}/forces", params={"top": 1}, headers=R)
    assert top_a.status_code == 200, top_a.text
    assert top_a.json()["rows"][0]["mag"] == pytest.approx(float(np.linalg.norm(fa, axis=1).max()))
    assert _tag(os.path.join(cdir, "runs", rid_b)) != _tag(os.path.join(cdir, "runs", rid_a))
    assert fa.shape == fb.shape


def test_validate_queued_behind_new_esl_fails_stale(client, synth_inputs, worker_factory, esl_root):
    """(Verifier test_validate_race_same_tstar) VALIDATE(A) 가 ESL B 뒤에 실행되면 FAILED, A 검증 행 없음."""
    w = worker_factory()
    cid, case, _ = _full(client, w, synth_inputs)
    rid_a = case["current_esl_run_id"]
    jb = _job(client, cid, "ESL_SOLVE", {"material_override": {"700": {"E": 1.0e5, "nu": 0.3}}})
    jv = _job(client, cid, "VALIDATE", {"esl_run_id": rid_a})
    _run(client, w, jb)
    assert w.run_once("SLOT") == "FAILED"
    v = _get(client, jv["id"])
    assert v["failure_code"] == "PREREQUISITE_MISSING"
    assert client.get(f"{API}/cases/{cid}/validations", headers=R).json() == []
    assert client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"] != rid_a


def test_validate_rechecks_stale_at_start(client, synth_inputs, worker_factory):
    """VALIDATE 대기 중 t* 변경 → 실행 시점에 stale → FAILED PREREQUISITE_MISSING."""
    w = worker_factory()
    cid, case, _ = _full(client, w, synth_inputs)
    jv = _job(client, cid, "VALIDATE", {"esl_run_id": case["current_esl_run_id"]})
    tj = client.get(f"{API}/cases/{cid}/tstar", headers=R).json()
    metric = tj["selected"]["metric"]
    other = next(c["frame_index"] for c in tj["metrics"][metric]["candidates"]
                 if c["frame_index"] != tj["selected"]["frame_index"] and c.get("in_D") is not False)
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": metric,
                                                     "frame_index": other}, headers=W)
    assert r.status_code == 200, r.text
    assert w.run_once("SLOT") == "FAILED"
    assert _get(client, jv["id"])["failure_code"] == "PREREQUISITE_MISSING"


def test_validate_restores_run_snapshot(client, synth_inputs, worker_factory, esl_root):
    """디스크 04_esl 이 다른 실행 것으로 바뀜(예: 취소·등록 실패한 ESL) → 스냅샷에서 되돌려 A 의 F_eq 로 검증·내보내기."""
    w = worker_factory()
    cid, case, _ = _full(client, w, synth_inputs)
    rid = case["current_esl_run_id"]
    cdir = os.path.join(str(esl_root), "case01")
    tag_a = _tag(cdir)
    run = client.get(f"{API}/esl-runs/{rid}", headers=R).json()
    assert tag_a == run["job_id"]
    f_a = np.load(os.path.join(cdir, "04_esl", "f_eq.npz"))["f"]
    os.replace(os.path.join(cdir, "04_esl"), os.path.join(cdir, "04_esl_other"))
    os.makedirs(os.path.join(cdir, "04_esl"))
    with open(os.path.join(cdir, "04_esl", "esl_summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"tag": "other-esl-job"}, fh)
    np.savez(os.path.join(cdir, "04_esl", "f_eq.npz"), f=np.zeros_like(f_a))
    jv = _run(client, w, _job(client, cid, "VALIDATE", {"esl_run_id": rid}))
    assert any("스냅샷에서 되돌림" in x for x in jv["warnings"])
    assert _tag(cdir) == tag_a
    np.testing.assert_array_equal(np.load(os.path.join(cdir, "04_esl", "f_eq.npz"))["f"], f_a)
    assert client.get(f"{API}/cases/{cid}/validations", headers=R).json()[0]["verdict"] == "PASS"
    moved = [d for d, _, fs in os.walk(os.path.join(cdir, "_backup")) if "esl_summary.json" in fs]
    assert any(json.load(open(os.path.join(d, "esl_summary.json")))["tag"] == "other-esl-job" for d in moved)
    # 스냅샷도 없으면 → FAILED PREREQUISITE_MISSING
    with open(os.path.join(cdir, "04_esl", "esl_summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"tag": "other-esl-job"}, fh)
    os.rename(os.path.join(cdir, "runs", rid), os.path.join(cdir, "runs_gone"))
    je = _job(client, cid, "EXPORT", {"esl_run_id": rid, "targets": ["csv"]})
    assert w.run_once("LIGHT") == "FAILED"
    assert _get(client, je["id"])["failure_code"] == "PREREQUISITE_MISSING"


def test_case_jobs_serialized_across_lanes(client, mini_inputs, app_ctx, worker_factory):
    """같은 Case 의 작업은 lane 과 무관하게 RUNNING 1개(claim 조건 + DB 부분 unique)."""
    from esl_platform.core.db.tables import jobs
    from esl_platform.core.repositories import jobs as jobs_repo

    cid = create_case(client, mini_inputs).json()["id"]
    cid2 = create_case(client, mini_inputs, folder="case02", title="둘째").json()["id"]
    _job(client, cid, "CASE_EXTRACT")
    with app_ctx.engine.begin() as conn:
        e1 = jobs_repo.insert_job(conn, case_id=cid, project_id="p-1", job_type="EXPORT", params={},
                                  created_by="u-power", created_by_name="파워")
        e2 = jobs_repo.insert_job(conn, case_id=cid2, project_id="p-1", job_type="EXPORT", params={},
                                  created_by="u-power", created_by_name="파워")
    w = worker_factory()
    slot = w.claim("SLOT")
    assert slot is not None and slot["case_id"] == cid and slot["state"] == "RUNNING"
    light = w.claim("LIGHT")
    assert light is not None and light["id"] == e2["id"]          # 같은 Case(e1)는 건너뜀
    assert _get(client, e1["id"])["state"] == "QUEUED"
    # DB 보장: 같은 Case 에 RUNNING 두 번째 → IntegrityError
    with pytest.raises(IntegrityError):
        with app_ctx.engine.begin() as conn:
            conn.execute(update(jobs).where(jobs.c.id == e1["id"]).values(
                state="RUNNING", queue_seq=None, holds_slot=False))
    # 앞 작업이 끝나면 claim 가능
    with app_ctx.engine.begin() as conn:
        jobs_repo.release(conn, slot["id"], slot["lease_token"], "FAILED", failure_code="X")
        jobs_repo.release(conn, light["id"], light["lease_token"], "FAILED", failure_code="X")
    nxt = w.claim("LIGHT")
    assert nxt is not None and nxt["id"] == e1["id"]


def test_migration_0002_on_pre_0002_db(engine, db_url):
    """0001 시점 DB(새 제약 없음)에 0002 적용 → 부분 unique·대소문자 무시 UNIQUE·예약어 CHECK 생성."""
    from alembic import command
    from alembic.config import Config

    with engine.begin() as c:
        c.execute(text("DROP INDEX ux_jobs_case_running"))
        c.execute(text("DROP INDEX ux_cases_folder_lower"))
        c.execute(text("ALTER TABLE cases DROP CONSTRAINT ck_cases_folder_reserved"))
        c.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        idx = {r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes WHERE tablename IN ('jobs','cases')"))}
        cons = {r[0] for r in c.execute(text("SELECT conname FROM pg_constraint"))}
        ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert {"ux_jobs_case_running", "ux_cases_folder_lower"} <= idx and "ck_cases_folder_reserved" in cons
    assert ver == "0012"  # head(0012 SCX 릴레이)


# ---------------------------------------------------------------- 2. EXPORT targets
def test_export_targets_only_selected_files(client, synth_inputs, worker_factory, esl_root):
    w = worker_factory()
    cid, case, _ = _full(client, w, synth_inputs)
    rid = case["current_esl_run_id"]
    cdir = os.path.join(str(esl_root), "case01")
    j = _run(client, w, _job(client, cid, "EXPORT", {"esl_run_id": rid, "targets": ["csv"]}), "LIGHT")
    files = sorted(os.listdir(os.path.join(cdir, "06_export")))
    assert files == ["f_eq.csv", "hotspots.csv", "tstar_candidates.csv", "u_rel.csv"]
    assert j["result"]["registered"]["targets"] == ["csv"]
    assert sorted(j["result"]["registered"]["files"]) == files
    _run(client, w, _job(client, cid, "EXPORT", {"esl_run_id": rid, "targets": ["radioss_inc", "fem"]}), "LIGHT")
    assert sorted(os.listdir(os.path.join(cdir, "06_export"))) == ["esl_bcs.inc", "esl_cload.inc", "esl_force.fem"]


# ---------------------------------------------------------------- 3. include 가 input_roots 밖
def _rad_with_include(inputs_root, mini_inputs, inc_path, name="mini2_0000.rad"):
    txt = open(mini_inputs["rad"], encoding="utf-8").read()
    rad2 = inputs_root / "mini" / name
    line = f"#include {inc_path}\n"
    rad2.write_text(txt.replace("/END", line + "/END", 1) if "/END" in txt else txt + "\n" + line, encoding="utf-8")
    return str(rad2)


def test_include_outside_input_roots_rejected(client, mini_inputs, inputs_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.inc"
    secret.write_text("/PART/99\nSECRET TITLE\n         1         1\n", encoding="utf-8")
    rad2 = _rad_with_include(inputs_root, mini_inputs, secret)
    r = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": rad2}, headers=W)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    # v0.12.0 L1: 일반 사용자에게는 서버 절대경로를 가림(파일 이름만 — 전역 관리자는 원문)
    assert d["code"] == "PATH_OUTSIDE_ROOT" and d["include"].endswith("secret.inc") and str(outside) not in r.text
    assert "SECRET" not in r.text
    body = {"project_id": "p-1", "folder_name": "inc01", "title": "inc", "rad_path": rad2,
            "results_dir": mini_inputs["csv"]}
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT" and "SECRET" not in r.text
    # 심링크 include(입력 루트 안 링크 → 밖 파일)도 거부
    link = inputs_root / "mini" / "lnk.inc"
    os.symlink(str(secret), str(link))
    rad3 = _rad_with_include(inputs_root, mini_inputs, link, "mini3_0000.rad")
    r = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": rad3}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT" and "SECRET" not in r.text
    # 입력 루트 안 include 는 허용
    inside = inputs_root / "mini" / "ok.inc"
    inside.write_text("# nothing\n", encoding="utf-8")
    rad4 = _rad_with_include(inputs_root, mini_inputs, inside, "mini4_0000.rad")
    r = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": rad4}, headers=W)
    assert r.status_code == 200 and str(inside) in [i["path"] for i in r.json()["includes"]]


def test_extract_rejects_include_added_outside(client, mini_inputs, inputs_root, tmp_path):
    cid = create_case(client, mini_inputs).json()["id"]
    secret = tmp_path / "secret.inc"
    secret.write_text("/PART/99\nSECRET TITLE\n", encoding="utf-8")
    txt = open(mini_inputs["rad"], encoding="utf-8").read()
    with open(mini_inputs["rad"], "w", encoding="utf-8") as fh:
        fh.write(txt.replace("/END", f"#include {secret}\n/END", 1) if "/END" in txt else txt + f"\n#include {secret}\n")
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    assert "SECRET" not in r.text


# ---------------------------------------------------------------- 4. 폴더명
@pytest.mark.parametrize("name", ["CON", "nul", "Aux", "PRN", "com1", "COM9", "lpt1", "LPT9", "a/b", "..", "-x",
                                  "a" * 65, "x.", "x ", "con.txt"])
def test_folder_name_rejected(client, mini_inputs, name):
    r = create_case(client, mini_inputs, folder=name, title="t-" + name)
    assert r.status_code == 422, (name, r.text)


def test_folder_name_case_insensitive_unique(client, mini_inputs, app_ctx, esl_root):
    assert create_case(client, mini_inputs, folder="case01", title="a").status_code == 201
    r = create_case(client, mini_inputs, folder="Case01", title="b")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FOLDER_EXISTS"
    assert not os.path.exists(os.path.join(str(esl_root), "Case01"))
    assert create_case(client, mini_inputs, folder="COM10", title="c").status_code == 201   # 예약어 아님
    from esl_platform.core.db.tables import cases

    def row(folder):
        return dict(id=str(uuid.uuid4()), project_id="p-1", folder_name=folder, title=uuid.uuid4().hex,
                    rad_path="/x", results_dir="/y", input_fingerprint={}, part_title="p", created_by="u",
                    created_by_name="u")
    for bad in ("CASE01", "Con", "lpt3"):
        with pytest.raises(IntegrityError):
            with app_ctx.engine.begin() as c:
                c.execute(insert(cases).values(**row(bad)))


# ---------------------------------------------------------------- 6. INPUT_CHANGED 재시도
def test_retry_after_input_change_uses_current_fingerprint(client, synth_inputs, worker_factory):
    w = worker_factory()
    cid = create_case(client, synth_inputs).json()["id"]
    j = _job(client, cid, "CASE_EXTRACT")
    p = os.path.join(synth_inputs["csv"], "frames.csv")
    os.utime(p, (os.path.getatime(p), os.path.getmtime(p) + 10))
    assert w.run_once("SLOT") == "FAILED"
    assert _get(client, j["id"])["failure_code"] == "INPUT_CHANGED"
    r = client.post(f"{API}/jobs/{j['id']}/retry", headers=W)
    assert r.status_code == 201, r.text
    assert w.run_once("SLOT") == "SUCCEEDED", _get(client, r.json()["id"])
    # 추출 이후 입력 변경 → ESL_SOLVE INPUT_CHANGED → 재시도 거부(추출부터)
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    je = _job(client, cid, "ESL_SOLVE")
    os.utime(p, (os.path.getatime(p), os.path.getmtime(p) + 10))
    assert w.run_once("SLOT") == "FAILED"
    assert _get(client, je["id"])["failure_code"] == "INPUT_CHANGED"
    r = client.post(f"{API}/jobs/{je['id']}/retry", headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INPUT_CHANGED"


# ---------------------------------------------------------------- 7. run() 예외·고아 자식
def test_unexpected_exception_fails_immediately(client, mini_inputs, worker_factory, monkeypatch):
    from esl_worker import executor

    def boom(self, st):
        raise RuntimeError("boom")

    monkeypatch.setattr(executor.Executor, "_run_step", boom)
    cid = create_case(client, mini_inputs).json()["id"]
    j = _job(client, cid, "CASE_EXTRACT")
    assert worker_factory().run_once("SLOT") == "FAILED"
    jj = _get(client, j["id"])
    assert jj["state"] == "FAILED" and jj["failure_code"] == "INTERNAL_ERROR" and "boom" in jj["failure_message"]
    assert worker_factory().claim("SLOT") is None          # 슬롯 해제됨(대기 작업 없음)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return "zombie" not in fh.read()
    except OSError:
        return False


def test_child_exits_when_worker_dies(tmp_path):
    """워커(부모)가 kill 되면 코어 자식이 스스로 끝난다(고아 방지)."""
    log = tmp_path / "step_01_X.log"
    script = tmp_path / "parent.py"
    script.write_text(f"""
import multiprocessing, os, sys, time
sys.path[:0] = {[str(REPO / 'worker'), str(REPO / 'backend'), str(REPO), HERE]!r}
from esl_worker.child import child_entry
if __name__ == "__main__":
    spec = {{"log_path": {str(log)!r}, "result_path": {str(log) + '.result.json'!r}, "target": "slow_core:run",
            "stage": "extract", "parent_pid": os.getpid()}}
    p = multiprocessing.get_context("spawn").Process(target=child_entry, args=(spec,))
    p.start()
    print(p.pid, flush=True)
    time.sleep(600)
""", encoding="utf-8")
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    pid_file = tmp_path / "slow_core.pid"
    wait_for(lambda: pid_file.is_file() and pid_file.read_text().strip())
    assert _alive(child_pid)
    parent.kill()
    parent.wait(10)
    t0 = time.time()
    while _alive(child_pid) and time.time() - t0 < 10:
        time.sleep(0.1)
    assert not _alive(child_pid), "부모가 죽은 뒤에도 코어 자식이 남아 있음"
    assert "부모 워커 프로세스가 사라져" in log.read_text(encoding="utf-8")
