"""v0.20.0 ④ 하중 전달 워커(계약 esl_load_transfer.md §2·§5·§6, V-LT-7·8·9 의 워커 부분).

- 단위: spec 은 작업 params.doe.load_transfer 로 코어에 그대로 전달(워커가 읽거나 바꾸지 않음), BD_PREP_REGISTER 가
  prep/load_transfer.json 의 경고·형상 행 lt 를 준비 요약에 합침(옛 스터디 = 파일 없음 → 요약 불변), BD_REGISTER 가
  result.json 의 load_transfer·view3d_ref·view3d_esl 을 DB result 에 통과(진단 파일 형식은 코어 소유).
- E2E(합성 STEP 3 + 합성 ESL 2, 방식 work·cell, 이어하기 해시, 진단 실패 → LT_DIAG_SKIPPED, 3D 같은 ESL)는 코어
  esl.doe.load_transfer(v200-core) 병합 후.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

def _w(p: Path, name: str, doc: Any) -> None:
    (p / "prep").mkdir(parents=True, exist_ok=True)
    (p / "prep" / name).write_text(json.dumps(doc), encoding="utf-8")


# ================================================================ 준비 요약 단위
def test_lt_prep_absent_is_noop(tmp_path):
    """옛 스터디(prep/load_transfer.json 없음): 경고·형상 행 불변(키 주입 없음)."""
    from esl_worker import register as rg

    shapes = [{"id": "d000", "status": "READY"}]
    warns = [{"code": "X", "message": "m"}]
    rg._compare_lt_prep(str(tmp_path), shapes, warns, {})
    assert shapes == [{"id": "d000", "status": "READY"}] and warns == [{"code": "X", "message": "m"}]
    _w(tmp_path, "load_transfer.json", ["not", "a", "dict"])
    rg._compare_lt_prep(str(tmp_path), shapes, warns, {})
    assert shapes == [{"id": "d000", "status": "READY"}]


def test_lt_prep_merges_rows_and_warnings(tmp_path):
    from esl_worker import register as rg

    _w(tmp_path, "load_transfer.json", {
        "warnings": ["LT_ESL_UNBALANCED: ESL 불평형", {"code": "COMPARE_REGION", "message": "영역 n_out 70000"}],
        "shapes": [
            {"id": "d000", "supports": {"mode": "auto", "max_dist_mm": 0.0}, "region": {"mode": "auto", "n_in": 10, "n_out": 0},
             "transfer": {"max_dist_mm": 0.0, "far_n": 0}, "per_esl": [{"big": "x" * 10}]},
            {"id": "d001", "supports": {"mode": "fallback", "max_dist_mm": 9.0, "reason": "DIST"},
             "region": {"mode": "auto", "n_in": 8, "n_out": 2}, "transfer": {"max_dist_mm": 4.0, "far_n": 3},
             "warnings": [{"code": "LT_FAR_NODES", "message": "먼 노드 3개"}, "LT_SUPPORT_FALLBACK: 지지 이전 실패"]},
            {"id": "d009", "supports": {"mode": "transfer"}}]})                   # 준비 요약에 없는 형상 — 무시
    shapes = [{"id": "d000", "status": "READY"}, {"id": "d001", "status": "READY"}, {"id": "d002", "status": "FAILED_SIZE"}]
    warns = [{"code": "LT_FAR_NODES", "message": "먼 노드 3개"}]                  # 이미 있는 경고는 중복 없음
    rg._compare_lt_prep(str(tmp_path), shapes, warns, {"LT_SUPPORT_FALLBACK": "fallback"})
    assert shapes[0]["lt"] == {"supports": {"mode": "auto", "max_dist_mm": 0.0},
                               "region": {"mode": "auto", "n_in": 10, "n_out": 0},
                               "transfer": {"max_dist_mm": 0.0, "far_n": 0}, "warnings": []}    # per_esl 은 싣지 않음
    assert shapes[1]["lt"]["supports"]["mode"] == "fallback" and shapes[1]["lt"]["transfer"]["far_n"] == 3
    assert [w["code"] for w in shapes[1]["lt"]["warnings"]] == ["LT_FAR_NODES", "LT_SUPPORT_FALLBACK"]
    assert "lt" not in shapes[2]
    assert [w["code"] for w in warns] == ["LT_FAR_NODES", "LT_ESL_UNBALANCED", "COMPARE_REGION", "LT_SUPPORT_FALLBACK"]


# ================================================================ 등록(DB)
def _study_row(engine, sid: str, **v: Any) -> None:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario="compare", title="t", entry_ids=["e1"], inputs={},
                              phase=v.pop("phase", "PREP"), dir_rel=f"_doe/{sid}", created_by="u-power",
                              created_by_name="파워", **v)


def _get(engine, sid: str) -> dict[str, Any]:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.connect() as c:
        return doe_repo.get_study(c, sid)


def test_register_prep_compare_with_lt(engine, tmp_path):
    from esl_worker import register as rg

    _study_row(engine, "s-lt-prep")
    _w(tmp_path, "input.json", {"warnings": [], "info": []})
    _w(tmp_path, "compare.json", {"reference_source": "step", "profile": {"size_mm": 3.0}, "gmsh_version": "4.13.1",
                                  "shapes": [{"id": "d000", "name": "A", "status": "READY"},
                                             {"id": "d001", "name": "B", "status": "READY"}]})
    _w(tmp_path, "load_transfer.json", {"warnings": [{"code": "LT_FAR_NODES", "message": "x"}],
                                        "shapes": [{"id": "d001", "supports": {"mode": "fallback"},
                                                    "warnings": [{"code": "LT_SUPPORT_FALLBACK", "message": "y"}]}]})
    job = {"bead_doe_id": "s-lt-prep", "job_type": "DOE_PREP"}
    with engine.begin() as c:
        out = rg.register_doe_prep(c, job, None, str(tmp_path))
    assert out["phase"] == "READY"
    p = _get(engine, "s-lt-prep")["prep"]
    assert "lt" not in p["shapes"][0] and p["shapes"][1]["lt"]["supports"] == {"mode": "fallback"}
    assert {w["code"] for w in p["warnings"]} == {"LT_FAR_NODES", "LT_SUPPORT_FALLBACK"}
    # 옛 스터디: 파일 없음 → lt 키·LT 경고 없음
    _study_row(engine, "s-lt-old")
    os.remove(tmp_path / "prep" / "load_transfer.json")
    with engine.begin() as c:
        rg.register_doe_prep(c, {"bead_doe_id": "s-lt-old", "job_type": "DOE_PREP"}, None, str(tmp_path))
    p = _get(engine, "s-lt-old")["prep"]
    assert all("lt" not in x for x in p["shapes"]) and p["warnings"] == []


def test_register_run_passes_diag_summary(engine, tmp_path):
    from esl_worker import register as rg

    diag = {"method": "work", "cell_size_mm": None, "support": "transfer", "region_mode": "auto",
            "alt": {"method": "cell", "cell_size_mm": 3.0}, "truth": "direct_nodal",
            "summary": [{"variant": "work", "umax_ratio": [1.0, 1.0], "C_ratio": [1.0, 1.0], "mac_min": 1.0,
                         "load_corr_min": 1.0}], "rank_alt_same": True, "warnings_n": 0}
    _study_row(engine, "s-lt-run", phase="RUN")
    (tmp_path / "post").mkdir()
    res = {"ranking": [], "n_ok": 0, "view3d": ["d000"], "load_transfer": diag,
           "view3d_ref": {"e1": "d000_e00"}, "view3d_esl": {"d001": "e1"}, "best_all": [1]}
    (tmp_path / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    with engine.begin() as c:
        rg.register_doe_run(c, {"bead_doe_id": "s-lt-run", "job_type": "DOE_RUN", "id": "j-1"}, None, str(tmp_path))
    r = _get(engine, "s-lt-run")["result"]
    assert r["load_transfer"] == diag and r["view3d_ref"] == {"e1": "d000_e00"} and r["view3d_esl"] == {"d001": "e1"}
    assert r["view3d"] == ["d000"] and "best_all" not in r


def test_worker_does_not_touch_spec():
    """워커는 params.doe 를 dict 로 복사해 코어 lib 로 넘길 뿐 — load_transfer 를 읽거나 바꾸는 코드가 없음(주입·하드코딩 없음)."""
    src = Path(__file__).resolve().parents[1].joinpath("esl_worker", "doe_jobs.py").read_text(encoding="utf-8")
    assert "load_transfer" not in src
