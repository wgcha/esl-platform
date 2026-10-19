"""V-DB-1~3: alembic upgrade, CHECK·부분 unique 위반 거부, 같은 Case·job_type 비종료 2개 → 409."""

from __future__ import annotations

import uuid

import pytest
from esl_test_support import API, REPO, H, create_case
from sqlalchemy import insert, inspect, text, update
from sqlalchemy.exc import IntegrityError

from esl_platform.core.db.tables import cases, jobs, support_sets, worker_slot
from esl_platform.core.repositories import cases as cases_repo


def test_v_db_1_upgrade_and_no_downgrade(engine, db_url):
    names = set(inspect(engine).get_table_names())
    assert {"cases", "jobs", "job_steps", "support_sets", "esl_runs", "validations", "artifacts", "notifications",
            "worker_slot", "worker_heartbeats", "alembic_version"} <= names
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM worker_slot")).scalar_one() == 1
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, "base")


def _case_row(**kw):
    d = dict(id=str(uuid.uuid4()), project_id="p-1", folder_name="f" + uuid.uuid4().hex[:8], title="t" + uuid.uuid4().hex,
             rad_path="/x", results_dir="/y", input_fingerprint={}, part_title="chassis rear", created_by="u",
             created_by_name="u")
    d.update(kw)
    return d


@pytest.mark.parametrize("stmt_fn", [
    lambda cid: insert(cases).values(**_case_row(folder_name="../bad")),
    lambda cid: insert(cases).values(**_case_row(status="DELETED")),
    lambda cid: insert(cases).values(**_case_row(tstar={"frame_index": 1, "metric": "m", "source": "x"})),
    lambda cid: insert(worker_slot).values(id=2),
    lambda cid: update(worker_slot).values(lease_token="t"),
    lambda cid: insert(support_sets).values(id="s", case_id=cid, node_ids=[1, 2], dofs=["123", "12", "3"],
                                            source="auto", created_by="u"),
    lambda cid: insert(jobs).values(id="j", case_id=cid, project_id="p", job_type="CASE_EXTRACT", stage=1, lane="SLOT",
                                    state="RUNNING", holds_slot=False, params={}, created_by="u", created_by_name="u"),
    lambda cid: insert(jobs).values(id="j", case_id=cid, project_id="p", job_type="CASE_EXTRACT", stage=1, lane="SLOT",
                                    state="QUEUED", queue_seq=None, params={}, created_by="u", created_by_name="u"),
    lambda cid: insert(jobs).values(id="j", case_id=cid, project_id="p", job_type="CASE_EXTRACT", stage=7, lane="SLOT",
                                    state="QUEUED", queue_seq=1, params={}, created_by="u", created_by_name="u"),
    lambda cid: insert(jobs).values(id="j", case_id=cid, project_id="p", job_type="CASE_EXTRACT", stage=1, lane="SLOT",
                                    state="FAILED", params={}, created_by="u", created_by_name="u"),
    lambda cid: insert(jobs).values(id="j", case_id=cid, project_id="p", job_type="CASE_EXTRACT", stage=1, lane="SLOT",
                                    state="QUEUED", queue_seq=1, params={}, created_by="u", created_by_name="u",
                                    lease_token="t"),
])
def test_v_db_2_checks(engine, stmt_fn):
    row = _case_row()
    with engine.begin() as c:
        c.execute(insert(cases).values(**row))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(stmt_fn(row["id"]))


def test_optimistic_version(engine):
    row = _case_row()
    with engine.begin() as c:
        c.execute(insert(cases).values(**row))
        cases_repo.update_case(c, row["id"], 1, title="a")
        with pytest.raises(cases_repo.VersionConflict):
            cases_repo.update_case(c, row["id"], 1, title="b")
        assert cases_repo.get_case(c, row["id"])["version"] == 2


def test_v_db_3_case_job_busy(client, mini_inputs):
    cid = create_case(client, mini_inputs).json()["id"]
    body = {"job_type": "CASE_EXTRACT", "params": {}}
    assert client.post(f"{API}/cases/{cid}/jobs", json=body, headers=H("tok-power", True)).status_code == 201
    r = client.post(f"{API}/cases/{cid}/jobs", json=body, headers=H("tok-power", True))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_JOB_BUSY"
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "NOPE", "params": {}}, headers=H("tok-power", True))
    assert r.status_code == 422
