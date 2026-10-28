"""V-OR-16 migration 0010_opt_runs(계약 esl_opt_run.md §12, OR-D-22): 빈 DB·0008 DB 업그레이드, 멱등, tables.py 일치,
기존 행과 새 CHECK, 0009(MCP 예약) 존재/부재 두 체인."""

from __future__ import annotations

import shutil
import uuid

import pytest
from esl_test_support import REPO, with_db
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

OPT_TABLES = {"opt_templates", "opt_keepouts", "opt_runs"}
OPT_INDEXES = {"ix_opt_templates_status", "ux_opt_keepouts_template", "ux_opt_keepouts_topo", "ix_opt_runs_project",
               "ix_opt_runs_template", "ix_library_entries_topo", "ix_jobs_opt_run", "ux_jobs_opt_run_active"}


def _cfg(db_url, script_location: str | None = None):
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    if script_location:
        cfg.set_main_option("script_location", script_location)
    return cfg


def _state(engine):
    with engine.connect() as c:
        tabs = {r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
        idx = {r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public'"))}
        cons = {r[0]: r[1] for r in c.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"))}
        cols = {(r[0], r[1]) for r in c.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"))}
        ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    return tabs, idx, cons, cols, ver


def _to_0008(engine):
    """0010 이전(0008) 스키마로: 비드 최적화 테이블·열·인덱스 제거, 옛 CHECK(0004 정의) 복원."""
    from esl_platform.core.db import tables

    old_types = ",".join(f"'{t}'" for t in tables.JOB_TYPES if t != "OPT_RUN")
    old_kinds = ",".join(f"'{k}'" for k in tables.ARTIFACT_KINDS if not k.startswith("OPT_"))
    with engine.begin() as c:
        c.execute(text("ALTER TABLE jobs DROP CONSTRAINT ck_jobs_subject"))
        c.execute(text("ALTER TABLE jobs DROP COLUMN opt_run_id"))
        c.execute(text("DROP TABLE opt_runs, opt_keepouts, opt_templates"))
        c.execute(text("ALTER TABLE library_entries DROP COLUMN topo_sha256, DROP COLUMN deform_mode"))
        c.execute(text("ALTER TABLE jobs ADD CONSTRAINT ck_jobs_subject CHECK ("
                       "(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL AND comparison_id IS NULL)"
                       " OR (job_type = 'LIB_COMPARE' AND case_id IS NULL AND analysis_id IS NULL AND comparison_id IS NOT NULL)"
                       " OR (job_type NOT IN ('LIB_ANALYZE','LIB_COMPARE') AND case_id IS NOT NULL AND analysis_id IS NULL"
                       " AND comparison_id IS NULL))"))
        for t, n, sql in (("jobs", "ck_jobs_job_type", f"job_type IN ({old_types})"),
                          ("jobs", "ck_jobs_stage", "stage BETWEEN 1 AND 9"),
                          ("artifacts", "ck_artifacts_kind", f"kind IN ({old_kinds})")):
            c.execute(text(f"ALTER TABLE {t} DROP CONSTRAINT {n}"))
            c.execute(text(f"ALTER TABLE {t} ADD CONSTRAINT {n} CHECK ({sql})"))
        c.execute(text("UPDATE alembic_version SET version_num = '0008'"))


def _seed_old_rows(engine):
    with engine.begin() as c:
        c.execute(text("INSERT INTO cases (id, project_id, folder_name, title, rad_path, results_dir, input_fingerprint,"
                       " part_title, created_by, created_by_name) VALUES ('c1','p-1','f1','t','/r','/s','{}','x','u','u')"))
        c.execute(text("INSERT INTO jobs (id, case_id, project_id, job_type, stage, lane, state, holds_slot, params, "
                       "created_by, created_by_name) VALUES ('j1','c1','p-1','CASE_EXTRACT',1,'SLOT','SUCCEEDED',false,"
                       "'{}','u','u')"))


def test_empty_db_head_and_tables_match(engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from esl_platform.core.db.tables import metadata

    tabs, idx, cons, cols, ver = _state(engine)
    assert ver == "0010" and OPT_TABLES <= tabs and OPT_INDEXES <= idx
    assert {("jobs", "opt_run_id"), ("library_entries", "topo_sha256"), ("library_entries", "deform_mode")} <= cols
    assert "OPT_RUN" in cons["ck_jobs_job_type"] and "10" in cons["ck_jobs_stage"]
    assert "opt_run_id" in cons["ck_jobs_subject"] and "OPT_RESULT" in cons["ck_artifacts_kind"]
    for n in ("ck_opt_runs_subject", "ck_opt_runs_load_strategy", "ck_opt_runs_objective_norm", "ck_opt_runs_k",
              "ck_opt_keepouts_key", "ck_opt_templates_archived", "fk_jobs_opt_run_id_opt_runs"):
        assert n in cons, n
    with engine.connect() as c:
        diffs = compare_metadata(MigrationContext.configure(c), metadata)
    flat = repr(diffs)
    for name in (*OPT_TABLES, *OPT_INDEXES, "opt_run_id", "topo_sha256", "deform_mode"):
        assert name not in flat, (name, flat)


def test_upgrade_from_0008_db_idempotent_existing_rows(engine, db_url):
    from alembic import command

    full = _state(engine)
    _seed_old_rows(engine)
    _to_0008(engine)
    tabs, _, _, cols, ver = _state(engine)
    assert ver == "0008" and not (OPT_TABLES & tabs) and ("jobs", "opt_run_id") not in cols
    command.upgrade(_cfg(db_url), "head")
    after = _state(engine)
    assert after[4] == "0010" and after[0] == full[0] and after[1] == full[1] and after[3] == full[3]
    for n in ("ck_jobs_job_type", "ck_jobs_stage", "ck_jobs_subject", "ck_artifacts_kind", "ck_opt_runs_subject"):
        assert after[2][n] == full[2][n], n                                  # 같은 정의(create_all = migration)
    # 멱등: 0008 로 표시만 되돌려 다시 적용, head 재실행
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '0008'"))
    command.upgrade(_cfg(db_url), "head")
    command.upgrade(_cfg(db_url), "head")
    assert _state(engine)[1:] == after[1:]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs WHERE id='j1' AND opt_run_id IS NULL")).scalar_one() == 1
    with pytest.raises(Exception, match="downgrade"):
        command.downgrade(_cfg(db_url), "0008")


def test_new_constraints(engine):
    _seed_old_rows(engine)
    run = ("INSERT INTO opt_runs (id, project_id, scenario, entry_ids, base, template_id, design, options, "
           "load_strategy, objective_norm, k, dir_rel, created_by, created_by_name) VALUES "
           "(:id, 'p-1', :sc, CAST(:e AS jsonb), CAST(:base AS jsonb), :tid, '{}', '{}', :ls, :on, :k, :d, 'u', 'u')")

    def ins(**kw):
        v = {"id": str(uuid.uuid4()), "sc": "S1", "e": '["e1"]', "base": '{"entry_id": "e1"}', "tid": None,
             "ls": "A", "on": "abs", "k": None}
        v.update(kw)
        v["d"] = f"_opt/{v['id']}"
        with engine.begin() as c:
            c.execute(text(run), v)
        return v["id"]

    rid = ins()
    for bad in ({"sc": "S3"}, {"base": None}, {"e": "[]"}, {"ls": "D"}, {"on": "max"}, {"ls": "C", "k": None},
                {"ls": "C", "k": 0}, {"sc": "S2"}):
        with pytest.raises(DBAPIError):
            ins(**bad)
    assert ins(ls="C", k=3)
    with engine.begin() as c:
        c.execute(text("INSERT INTO opt_templates (id, title, format, file_name, sha256, n_nodes, n_elems, \"L_xi\", "
                       "\"L_eta\", z_range, pids, quality, dir_rel, created_by, created_by_name) VALUES ('t1','평판',"
                       "'fem','a.fem',:s,1,1,1,1,'[0,0]','[]','{}','_templates/t1','u','u')"), {"s": "0" * 64})
    assert ins(sc="S2", base=None, tid="t1")
    with pytest.raises(DBAPIError):                                        # 보관 짝
        with engine.begin() as c:
            c.execute(text("UPDATE opt_templates SET status='ARCHIVED' WHERE id='t1'"))
    ko = ("INSERT INTO opt_keepouts (id, template_id, topo_sha256, rects, auto, frame, updated_by, updated_by_name) "
          "VALUES (:i, :t, :h, '[]', '{}', '{}', 'u', 'u')")
    with engine.begin() as c:
        c.execute(text(ko), {"i": "k1", "t": "t1", "h": None})
        c.execute(text(ko), {"i": "k2", "t": None, "h": "a" * 64})
    for t, h in (("t1", None), (None, "a" * 64), (None, None), ("t1", "b" * 64)):
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                c.execute(text(ko), {"i": str(uuid.uuid4()), "t": t, "h": h})
    # 작업 대상: OPT_RUN 은 opt_run_id 만, 다른 작업은 opt_run_id 없음
    job = ("INSERT INTO jobs (id, case_id, opt_run_id, project_id, job_type, stage, lane, state, holds_slot, params, "
           "created_by, created_by_name) VALUES (:i, :c, :r, 'p-1', :jt, :st, 'SLOT', 'SUCCEEDED', false, '{}', 'u', 'u')")
    with engine.begin() as c:
        c.execute(text(job), {"i": "j2", "c": None, "r": rid, "jt": "OPT_RUN", "st": 10})
    for c_, r_, jt in (("c1", rid, "OPT_RUN"), (None, None, "OPT_RUN"), ("c1", rid, "CASE_EXTRACT")):
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                c.execute(text(job), {"i": str(uuid.uuid4()), "c": c_, "r": r_, "jt": jt, "st": 10 if jt == "OPT_RUN" else 1})
    # 템플릿 행 삭제 → 세트 함께 삭제(CASCADE)
    with engine.begin() as c:
        c.execute(text("DELETE FROM opt_runs WHERE template_id='t1'"))
        c.execute(text("DELETE FROM opt_templates WHERE id='t1'"))
        assert c.execute(text("SELECT count(*) FROM opt_keepouts")).scalar_one() == 1


def test_chain_without_0009():
    from alembic.script import ScriptDirectory

    sd = ScriptDirectory(str(REPO / "migrations"))
    assert sd.get_current_head() == "0010"
    assert sd.get_revision("0010").down_revision == "0008"
    assert "0009" not in {r.revision for r in sd.walk_revisions()}


MCP_0009 = '''"""MCP 예약 migration 대역(시험): revision 0009, down_revision 0010."""
from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(text("CREATE TABLE IF NOT EXISTS mcp_probe (id int)"))


def downgrade() -> None:
    raise RuntimeError("no")
'''


def test_chain_with_0009_after_0010(pg_server, tmp_path):
    """0009(MCP)가 나중에 revision 0009·down_revision 0010 으로 붙어도 0008 DB → 0010 → 0009 순서로 올라간다."""
    from alembic import command
    from alembic.script import ScriptDirectory

    mig = tmp_path / "migrations"
    shutil.copytree(REPO / "migrations", mig, ignore=shutil.ignore_patterns("__pycache__"))
    (mig / "versions" / "0009_mcp_probe.py").write_text(MCP_0009, encoding="utf-8")
    sd = ScriptDirectory(str(mig))
    assert sd.get_current_head() == "0009"
    assert [r.revision for r in sd.walk_revisions()][:3] == ["0009", "0010", "0008"]
    name = f"esl_chain_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = with_db(pg_server["admin_url"], name)
    try:
        command.upgrade(_cfg(url, str(mig)), "head")
        eng = create_engine(url)
        try:
            tabs, _, _, _, ver = _state(eng)
            assert ver == "0009" and OPT_TABLES <= tabs and "mcp_probe" in tabs
            _to_0008(eng)
            with eng.begin() as c:
                c.execute(text("DROP TABLE mcp_probe"))
            command.upgrade(_cfg(url, str(mig)), "head")
            tabs, _, _, _, ver = _state(eng)
            assert ver == "0009" and OPT_TABLES <= tabs and "mcp_probe" in tabs
        finally:
            eng.dispose()
    finally:
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
