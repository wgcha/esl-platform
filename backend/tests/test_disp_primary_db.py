"""변위 주지표 판정(계약 esl_disp_primary.md, v0.5.7) — DB·API 시험(계산 없이 행을 직접 심음).

V-DP-9 migration 0008 · V-DP-11 status(LEGACY/PASS/UNDETERMINED) · V-DP-12 라이브러리 필터.
실제 파이프라인 산출물로 보는 시험(register·disp-field·section·등록 규칙)은 worker/tests/test_disp_primary_e2e.py.
"""

from __future__ import annotations

import pytest
from esl_test_support import API, REPO, H
from p2_support import seed_entry, seed_run
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

R = H("tok-power")
HEAD = "0011"      # migration head(0011 비드 DOE, downgrade 미지원)

NEW_COLS = ("scheme", "disp_max_rel", "disp_noise_rel", "undetermined_reason", "disp", "strain_ref")
NEW_CKS = ("ck_validations_scheme", "ck_validations_undetermined")


def _cfg(db_url):
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    return cfg


def _case(engine, cid="c1"):
    with engine.begin() as c:
        c.execute(text("INSERT INTO cases (id, project_id, folder_name, title, rad_path, results_dir, "
                       "input_fingerprint, part_title, created_by, created_by_name) VALUES "
                       f"('{cid}','p-1','f_{cid}','t','/r','/s','{{}}','x','u','u')"))


def _cols(engine):
    with engine.connect() as c:
        return {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='validations'"))}


def _cons(engine):
    with engine.connect() as c:
        return {r[0]: r[1] for r in c.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'validations'::regclass"))}


def _ver(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _to_0007_state(engine):
    """0008 이전(0007) 스키마로 되돌린다: 새 CHECK·컬럼 제거, verdict CHECK 복원, alembic_version = 0007."""
    with engine.begin() as c:
        for n in NEW_CKS + ("ck_validations_verdict",):
            c.execute(text(f"ALTER TABLE validations DROP CONSTRAINT {n}"))
        c.execute(text("ALTER TABLE validations ADD CONSTRAINT ck_validations_verdict "
                       "CHECK (verdict IN ('PASS','FAIL'))"))
        for n in NEW_COLS:
            c.execute(text(f"ALTER TABLE validations DROP COLUMN {n}"))
        c.execute(text("UPDATE alembic_version SET version_num = '0007'"))


# ================================================================ V-DP-9 migration 0008
def test_dp9_upgrade_from_0007_keeps_existing_rows_as_legacy(engine, db_url):
    from alembic import command

    _case(engine)
    r1 = seed_run(engine, "c1", verdict="PASS")
    r2 = seed_run(engine, "c1", verdict="FAIL")
    _to_0007_state(engine)
    assert _ver(engine) == "0007" and not (set(NEW_COLS) & _cols(engine))
    command.upgrade(_cfg(db_url), "head")
    assert _ver(engine) == HEAD and set(NEW_COLS) <= _cols(engine)
    cons = _cons(engine)
    assert "UNDETERMINED" in cons["ck_validations_verdict"] and "disp_primary/1" in cons["ck_validations_scheme"]
    assert "undetermined_reason" in cons["ck_validations_undetermined"]
    with engine.connect() as c:
        rows = {r.id: r for r in c.execute(text("SELECT id, verdict, scheme, disp_max_rel, disp_noise_rel, "
                                                "undetermined_reason, disp, strain_ref FROM validations"))}
    assert rows[r1["validation_id"]].verdict == "PASS" and rows[r2["validation_id"]].verdict == "FAIL"
    for r in rows.values():                                      # 백필 없음: 기존 행은 scheme NULL = LEGACY
        assert r.scheme is None and r.disp_max_rel is None and r.disp is None and r.strain_ref is None
        assert r.undetermined_reason is None and r.disp_noise_rel is None


def test_dp9_idempotent_on_create_all_db(engine, db_url):
    """0001 이 create_all 로 이미 새 컬럼·CHECK 를 만든 DB 에서 0008 을 (다시) 적용해도 오류 없음."""
    from alembic import command

    before = (_cols(engine), _cons(engine))
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '0007'"))
    command.upgrade(_cfg(db_url), "head")
    command.upgrade(_cfg(db_url), "head")
    assert _ver(engine) == HEAD and (_cols(engine), _cons(engine)) == before


def test_dp9_check_constraints_reject_inconsistent_rows(engine):
    _case(engine)
    ok = seed_run(engine, "c1", verdict="UNDETERMINED",
                  val_extra={"scheme": "disp_primary/1", "undetermined_reason": "NO_FULL_SOLVE"})
    assert ok["validation_id"]
    for verdict, extra in (("UNDETERMINED", {}),                                          # scheme NULL
                           ("UNDETERMINED", {"scheme": "disp_primary/1"}),                # 사유 없음
                           ("UNDETERMINED", {"undetermined_reason": "NO_FULL_SOLVE"}),   # scheme NULL
                           ("PASS", {"scheme": "other/9"}),                               # 알 수 없는 scheme
                           ("BOGUS", {"scheme": "disp_primary/1"})):
        with pytest.raises(DBAPIError):
            seed_run(engine, "c1", verdict=verdict, val_extra=extra)
    # PASS/FAIL 은 scheme 유무와 무관하게 허용(LEGACY 행 포함)
    seed_run(engine, "c1", verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    seed_run(engine, "c1", verdict="FAIL")


def test_dp9_downgrade_blocked_by_undetermined_rows_then_ok(engine, db_url):
    from alembic import command

    _case(engine)
    seed_run(engine, "c1", verdict="PASS", val_extra={"scheme": "disp_primary/1", "disp_max_rel": 0.01})
    u = seed_run(engine, "c1", verdict="UNDETERMINED",
                 val_extra={"scheme": "disp_primary/1", "undetermined_reason": "ZERO_DISP"})
    command.stamp(_cfg(db_url), "0008")        # 0010(비드 최적화)은 downgrade 미지원 — 0008 시점으로 표시만 옮겨 0008 downgrade 시험
    with pytest.raises(Exception) as ei:
        command.downgrade(_cfg(db_url), "0007")
    assert "UNDETERMINED" in str(ei.value)
    assert _ver(engine) == "0008" and set(NEW_COLS) <= _cols(engine)              # 데이터·스키마 그대로
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM validations WHERE verdict='UNDETERMINED'")).scalar_one() == 1
    with engine.begin() as c:
        c.execute(text("DELETE FROM validations WHERE id = :i"), {"i": u["validation_id"]})
    command.downgrade(_cfg(db_url), "0007")
    assert _ver(engine) == "0007" and not (set(NEW_COLS) & _cols(engine))
    cons = _cons(engine)
    assert "UNDETERMINED" not in cons["ck_validations_verdict"] and not (set(NEW_CKS) & set(cons))
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM validations")).scalar_one() == 1            # PASS 행 보존
    with pytest.raises(DBAPIError):                                                 # 옛 CHECK 복원
        with engine.begin() as c:
            c.execute(text("UPDATE validations SET verdict = 'UNDETERMINED'"))
    command.upgrade(_cfg(db_url), "head")
    assert _ver(engine) == HEAD


def test_dp9_tables_py_matches_migrated_schema(engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from esl_platform.core.db.tables import metadata

    with engine.connect() as c:
        diffs = compare_metadata(MigrationContext.configure(c), metadata)
    assert "validations" not in repr(diffs), repr(diffs)


# ================================================================ V-DP-11 status
def test_dp11_validation_status_legacy_pass_undetermined(client, engine):
    _case(engine)
    legacy = seed_run(engine, "c1", verdict="PASS")                                   # scheme NULL
    passed = seed_run(engine, "c1", verdict="PASS", val_extra={"scheme": "disp_primary/1", "disp_max_rel": 0.002,
                                                                "disp_noise_rel": 1e-6,
                                                                "strain_ref": {"n_exceed": 3, "exceeded": True}})
    undet = seed_run(engine, "c1", verdict="UNDETERMINED", val_extra={
        "scheme": "disp_primary/1", "undetermined_reason": "NO_FULL_SOLVE"})
    failed_legacy = seed_run(engine, "c1", verdict="FAIL")
    got = {}
    for k, r in (("legacy", legacy), ("pass", passed), ("undet", undet), ("fail_legacy", failed_legacy)):
        resp = client.get(f"{API}/validations/{r['validation_id']}", headers=R)
        assert resp.status_code == 200, resp.text
        got[k] = resp.json()
    assert (got["legacy"]["status"], got["legacy"]["scheme"], got["legacy"]["verdict"]) == ("LEGACY", None, "PASS")
    assert (got["fail_legacy"]["status"], got["fail_legacy"]["verdict"]) == ("LEGACY", "FAIL")
    assert (got["pass"]["status"], got["pass"]["scheme"]) == ("PASS", "disp_primary/1")
    assert got["pass"]["disp_max_rel"] == 0.002 and got["pass"]["disp_noise_rel"] == 1e-6
    assert got["pass"]["strain_ref"] == {"n_exceed": 3, "exceeded": True} and got["pass"]["disp"] is None
    assert (got["undet"]["status"], got["undet"]["verdict"], got["undet"]["undetermined_reason"]) == (
        "UNDETERMINED", "UNDETERMINED", "NO_FULL_SOLVE")
    assert got["undet"]["fail_reasons"] == [] and got["undet"]["disp_rms_rel"] is None
    # Case 의 검증 목록에도 status
    lst = client.get(f"{API}/cases/c1/validations", headers=R).json()
    assert {v["id"]: v["status"] for v in lst} == {legacy["validation_id"]: "LEGACY", passed["validation_id"]: "PASS",
                                                   undet["validation_id"]: "UNDETERMINED",
                                                   failed_legacy["validation_id"]: "LEGACY"}


# ================================================================ V-DP-12 라이브러리 목록 필터
def test_dp12_library_verdict_filter_legacy_status_and_fallback(client, engine, esl_root):
    _case(engine)
    runs = [seed_run(engine, "c1", verdict="PASS") for _ in range(6)]
    mk = lambda i, **kw: seed_entry(engine, "c1", runs[i]["run_id"], esl_root=str(esl_root), scene_no=i + 1, **kw)  # noqa: E731
    pass_new = mk(0, verdict="PASS", quality_extra={"status": "PASS", "scheme": "disp_primary/1"})
    fail_new = mk(1, verdict="FAIL", quality_extra={"status": "FAIL", "scheme": "disp_primary/1"})
    und_new = mk(2, verdict="UNDETERMINED", quality_extra={"status": "UNDETERMINED", "scheme": "disp_primary/1",
                                                           "undetermined_reason": "NO_FULL_SOLVE",
                                                           "confirmed_undetermined": {"reason": "r", "by": "u", "at": "t"}})
    old_pass = mk(3, verdict="PASS")                                          # 0.5.7 이전 등록: status·scheme 없음
    old_fail = mk(4, verdict="FAIL")
    legacy_new = mk(5, verdict="PASS", quality_extra={"status": "LEGACY"})    # 0.5.7 이후 이전 판정 체계 검증으로 등록

    def ids(v):
        r = client.get(f"{API}/library/entries", params={"project_id": "p-1", "verdict": v}, headers=R)
        assert r.status_code == 200, r.text
        return {e["id"] for e in r.json()}

    assert ids("UNDETERMINED") == {und_new}
    assert ids("LEGACY") == {old_pass, old_fail, legacy_new}                  # scheme 없음 전부
    # PASS/FAIL = quality.status, 없으면 quality.verdict (계약 §7)
    assert ids("PASS") == {pass_new, old_pass} and ids("FAIL") == {fail_new, old_fail}
    assert ids("pass") == {pass_new, old_pass}
    e = client.get(f"{API}/library/entries/{und_new}", headers=R).json()
    q = e["quality"]
    assert q["status"] == "UNDETERMINED" and q["scheme"] == "disp_primary/1" and q["undetermined_reason"] == "NO_FULL_SOLVE"
    assert q["confirmed_undetermined"]["reason"] == "r"
    old = client.get(f"{API}/library/entries/{old_pass}", headers=R).json()["quality"]
    assert old["status"] is None and old["scheme"] is None and old["disp_max_rel"] is None
