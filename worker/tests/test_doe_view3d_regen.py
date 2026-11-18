"""v0.23.3 3D 다시 만들기(esl_jig_view.md §3, V-0233-6): DOE_RUN · params kind VIEW3D 의 BD_REGISTER = DB 무변경."""

from __future__ import annotations

import json
from pathlib import Path


def test_register_view3d_keeps_study(engine, tmp_path):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_worker import register as rg

    sid = "s-v3d-regen"
    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario="same", title="t", entry_ids=["e1"], inputs={},
                              phase="DONE", dir_rel=f"_doe/{sid}", created_by="u-power", created_by_name="파워",
                              base={"entry_id": "e1"}, result={"ranking": [], "n_ok": 3, "job_id": "j-run"})
    with engine.connect() as c:
        before = doe_repo.get_study(c, sid)
    (tmp_path / "post").mkdir()
    (tmp_path / "post" / "jig_view.json").write_text(json.dumps({"schema": "esl/doe_jig_view/1"}), encoding="utf-8")
    job = {"bead_doe_id": sid, "job_type": "DOE_RUN", "id": "j-v3d", "params": {"kind": "VIEW3D"}}
    with engine.begin() as c:
        out = rg.register_doe_view3d(c, job, None, str(tmp_path))
    assert out == {"bead_doe_id": sid, "phase": "DONE", "view3d": True, "sidecar": True}
    with engine.connect() as c:
        after = doe_repo.get_study(c, sid)
    assert after == before                                         # DB 무변경(phase·result·version)
    # 일반 실행 등록은 DONE 스터디를 거부(DOE_PHASE_STALE) — 그래서 VIEW3D 는 별도 함수
    try:
        with engine.begin() as c:
            rg.register_doe_run(c, {**job, "params": {}}, None, str(tmp_path))
        raise AssertionError("expected RegisterError")
    except rg.RegisterError as exc:
        assert exc.code == "DOE_PHASE_STALE"


def test_run_step_dispatches_view3d_register():
    src = Path(__file__).resolve().parents[1].joinpath("esl_worker", "doe_jobs.py").read_text(encoding="utf-8")
    assert 'get("kind") == "VIEW3D"' in src and "register.register_doe_view3d" in src
