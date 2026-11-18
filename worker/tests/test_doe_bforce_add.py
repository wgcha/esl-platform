"""v0.24.0 경계력 ESL 추가 계산(esl_bforce.md §6, V-0240-k): DOE_RUN · params kind BFORCE 의 BD_REGISTER = DB 무변경."""

from __future__ import annotations

import json
from pathlib import Path


def test_register_bforce_keeps_study(engine, tmp_path):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_worker import register as rg

    sid = "s-bf-add"
    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario="same", title="t", entry_ids=["e1"], inputs={},
                              phase="DONE", dir_rel=f"_doe/{sid}", created_by="u-power", created_by_name="파워",
                              base={"entry_id": "e1"}, result={"ranking": [], "n_ok": 3, "job_id": "j-run"})
    with engine.connect() as c:
        before = doe_repo.get_study(c, sid)
    (tmp_path / "post").mkdir()
    (tmp_path / "post" / "bforce_view.json").write_text(json.dumps({"schema": "esl/doe_bforce_view/1"}), encoding="utf-8")
    job = {"bead_doe_id": sid, "job_type": "DOE_RUN", "id": "j-bf", "params": {"kind": "BFORCE"}}
    with engine.begin() as c:
        out = rg.register_doe_view3d(c, job, None, str(tmp_path))
    assert out["bead_doe_id"] == sid and out["phase"] == "DONE"
    with engine.connect() as c:
        assert doe_repo.get_study(c, sid) == before                  # DB 무변경(phase·result·version)


def test_run_step_dispatches_bforce_register():
    src = Path(__file__).resolve().parents[1].joinpath("esl_worker", "doe_jobs.py").read_text(encoding="utf-8")
    assert 'get("kind") == "BFORCE"' in src


def test_bforce_request_keys():
    from esl_worker import h3d

    r = h3d.bforce_request({})
    assert r["bf_on"] == "1" and r["bf_names_cont"].split("|")[0] == "Contact Forces"
    assert r["bf_names_acc"].split("|")[0] == "Acceleration" and r["bf_vec_comps"] == "X Y Z"
    r2 = h3d.bforce_request({"bforce": {"enabled": False, "result_names": {"cont": ["KF", "Contact Forces"]},
                                        "vec_comps": ["X|x", "Y|y", "Z|z"]}})
    assert r2["bf_on"] == "0" and r2["bf_names_cont"] == "KF|Contact Forces" and r2["bf_vec_comps"] == "X|x Y|y Z|z"
    assert r2["bf_names_acc"] == "Acceleration|ACC"                 # 부분 지정 = 그 키만
