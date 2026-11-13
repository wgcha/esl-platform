"""v0.20.0 하중 전달 전 모드 확장(계약 esl_load_transfer.md §13, V-LT-18·19 의 워커 부분): 준비 등록이 ①②③ 에서도 코어가 쓴
prep/load_transfer.json 의 경고(LT_PLACEMENT 등)와 prep/input.json.load_transfer{plan, placement, fast_path} 를 준비 요약에 싣고,
옛 스터디(파일·키 없음)는 요약 불변. 결과 등록은 모든 시나리오에서 result.json 의 load_transfer·view3d_* 를 통과.
E2E(①②③ 실제 전달·진단 비용)는 코어(v200-core) 병합 후 통합 단계."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _w(p: Path, name: str, doc: Any) -> None:
    (p / "prep").mkdir(parents=True, exist_ok=True)
    (p / "prep" / name).write_text(json.dumps(doc), encoding="utf-8")


def _study(engine, sid: str, scenario: str, **v: Any) -> None:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario=scenario, title="t", entry_ids=["e1"],
                              inputs=v.pop("inputs", {}), phase=v.pop("phase", "PREP"), dir_rel=f"_doe/{sid}",
                              created_by="u-power", created_by_name="파워", **v)


def _get(engine, sid: str) -> dict[str, Any]:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.connect() as c:
        return doe_repo.get_study(c, sid)


def _prep_files(d: Path, *, lt: bool, plan: bool) -> None:
    _w(d, "input.json", {"warnings": [], "info": [], **({"load_transfer": {
        "plan": {"id": "bmesh_once", "reuse": "once"}, "placement": {"kind": "rigid", "resid_med_mm": 0.2},
        "fast_path": None}} if plan else {})})
    _w(d, "params.json", {"beads": [], "params": []})
    if lt:
        _w(d, "load_transfer.json", {"warnings": [{"code": "LT_PLACEMENT", "message": "frame 정규화 사상(잔차 중앙값 0.2 mm)"}],
                                     "shapes": [{"id": "d000", "transfer": {"max_dist_mm": 0.1, "far_n": 0}}]})


@pytest.mark.parametrize("scenario, extra", [("same", {}), ("mesh", {}), ("select", {})])
def test_prep_register_lt_for_non_compare(engine, tmp_path, scenario, extra):
    from esl_worker import register as rg

    sid = f"s-lm-{scenario}"
    _study(engine, sid, scenario, **({"base": {"entry_id": "e1"}} if scenario == "same" else {}))
    _prep_files(tmp_path, lt=True, plan=True)
    with engine.begin() as c:
        out = rg.register_doe_prep(c, {"bead_doe_id": sid, "job_type": "DOE_PREP"}, None, str(tmp_path))
    assert out["phase"] == "READY"
    p = _get(engine, sid)["prep"]
    assert [w["code"] for w in p["warnings"]] == ["LT_PLACEMENT"]
    assert p["load_transfer"] == {"plan": {"id": "bmesh_once", "reuse": "once"},
                                  "placement": {"kind": "rigid", "resid_med_mm": 0.2}, "fast_path": None}


@pytest.mark.parametrize("scenario", ["same", "select"])
def test_prep_register_legacy_unchanged(engine, tmp_path, scenario):
    """옛 스터디: 파일·키 없음 → 경고·prep.load_transfer 키 없음(주입 없음)."""
    from esl_worker import register as rg

    sid = f"s-lm-old-{scenario}"
    _study(engine, sid, scenario, **({"base": {"entry_id": "e1"}} if scenario == "same" else {}))
    _prep_files(tmp_path, lt=False, plan=False)
    with engine.begin() as c:
        rg.register_doe_prep(c, {"bead_doe_id": sid, "job_type": "DOE_PREP"}, None, str(tmp_path))
    p = _get(engine, sid)["prep"]
    assert p["warnings"] == [] and "load_transfer" not in p


def test_plan_info_helper():
    from esl_worker import register as rg

    assert rg._lt_plan_info({}) is None and rg._lt_plan_info({"load_transfer": 3}) is None
    assert rg._lt_plan_info({"load_transfer": {"plan": {"id": "x"}, "extra": 1}}) == {"plan": {"id": "x"}}


@pytest.mark.parametrize("scenario", ["same", "mesh", "select"])
def test_run_register_passes_diag_all_scenarios(engine, tmp_path, scenario):
    from esl_worker import register as rg

    diag = {"method": "work", "cell_size_mm": None, "alt": None, "truth": "a_direct",
            "summary": [{"variant": "work", "umax_ratio": [0.9, 1.1], "C_ratio": [0.9, 1.1], "mac_min": None,
                         "load_corr_min": None}], "rank_alt_same": None, "warnings_n": 0}
    sid = f"s-lm-run-{scenario}"
    _study(engine, sid, scenario, phase="RUN", **({"base": {"entry_id": "e1"}} if scenario == "same" else {}))
    (tmp_path / "post").mkdir()
    (tmp_path / "post" / "result.json").write_text(json.dumps({"ranking": [], "n_ok": 0, "load_transfer": diag}), encoding="utf-8")
    with engine.begin() as c:
        rg.register_doe_run(c, {"bead_doe_id": sid, "job_type": "DOE_RUN", "id": "j-1"}, None, str(tmp_path))
    assert _get(engine, sid)["result"]["load_transfer"] == diag
