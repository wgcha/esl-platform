"""v0.20.0 강성 지표 워커(계약 esl_stiffness_metric.md §6, V-SM-7 의 워커 부분): 워커는 doe.rank 스냅샷을 읽거나 바꾸지 않고(코어가 읽음),
BD_REGISTER 가 post/result.json 의 metric·lin_form·순위 행 보조 필드·SM 경고를 DB result 에 통과. E2E(①②③④ 실제 지표 계산)는
코어(core-sm·core-geom) 병합 후 통합 단계."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _study(engine, sid: str, scenario: str, **v) -> None:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario=scenario, title="t", entry_ids=["e1"], inputs={},
                              phase="RUN", dir_rel=f"_doe/{sid}", created_by="u-power", created_by_name="파워", **v)


@pytest.mark.parametrize("scenario", ["same", "mesh", "select", "compare"])
def test_register_run_passes_metric_fields(engine, tmp_path, scenario):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_worker import register as rg

    sid = f"s-sm-{scenario}"
    _study(engine, sid, scenario, **({"base": {"entry_id": "e1"}} if scenario == "same" else {}))
    row = {"id": "d001", "score": 0.9, "score_solve": 1.4, "imbalance_max": 0.27, "rho_min": 0.9, "rho_max": 1.1, "umax_def": 2.5}
    warns = [{"code": "SM_LIN_RANGE", "message": "m"}, {"code": "SM_IMBALANCE", "message": "n"}]
    res = {"ranking": [row], "n_ok": 1, "metric": "lin", "lin_form": "ritz", "warnings": warns}
    (tmp_path / "post").mkdir()
    (tmp_path / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    with engine.begin() as c:
        rg.register_doe_run(c, {"bead_doe_id": sid, "job_type": "DOE_RUN", "id": "j-1"}, None, str(tmp_path))
    with engine.connect() as c:
        r = doe_repo.get_study(c, sid)["result"]
    assert r["metric"] == "lin" and r["lin_form"] == "ritz" and r["ranking"] == [row] and r["warnings"] == warns


def test_worker_does_not_touch_rank_spec():
    src = Path(__file__).resolve().parents[1].joinpath("esl_worker", "doe_jobs.py").read_text(encoding="utf-8")
    assert '"rank"' not in src and "rank_metric" not in src
