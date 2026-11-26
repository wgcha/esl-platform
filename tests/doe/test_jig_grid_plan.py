"""v0.24.8 격자 지그 — 계획 표·지그 종류·지표·설정·해시·문구(계약 esl_jig_grid_map.md §2.2·§7 — V-0248-JG-1·12·14·15 코어 몫)."""
import copy
import inspect
import re

import pytest
import synth_jig_grid as G

from esl.doe import DEFAULTS, load_messages
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.errors import EslError
from esl.mech import grid_map as gm

KEYS = [("same", None), ("mesh", None), ("select", "case"), ("select", "mesh"), ("select", "step"), ("step", None),
        ("compare", None)]


# ---------------------------------------------------------------- V-0248-JG-1 계획 표
def test_plan_rows_values_and_invariants():
    for pid, row in tp.PLANS.items():
        assert all(row.get(k) not in (None, "", ()) for k in tp.PLAN_COLS), pid
    assert "grid" in tp.JIG_VALUES["jig_fix"] and "shape" in tp.JIG_VALUES["jig_ctx"]
    assert {pid for pid, r in tp.PLANS.items() if r["jig_fix"] == "grid"} == {"step_per_design", "compare_per_shape"}
    for k in KEYS:
        tp.plan_for(k[0], k[1])
    bad = [("compare_per_shape", {"jig_ctx": "none"}), ("compare_per_shape", {"sm_ref": "base"}),
           ("compare_per_shape", {"sm_jig": "base"}), ("step_per_design", {"jig_fix": "none"}),
           ("case_once", {"jig_fix": "grid", "jig_ctx": "shape"}), ("compare_per_shape", {"dst": "baseline"})]
    key_of = {"compare_per_shape": ("compare", None), "step_per_design": ("step", None), "case_once": ("same", None)}
    for pid, over in bad:
        saved = copy.deepcopy(tp.PLANS[pid])
        try:
            tp.PLANS[pid].update(over)
            with pytest.raises(EslError) as ei:
                tp.plan_for(*key_of[pid])
            assert ei.value.code == "CONFIG_INVALID", (pid, over)
        finally:
            tp.PLANS[pid].clear()
            tp.PLANS[pid].update(saved)


def test_jig_kind_truth_table_and_metric_effective():
    for k in KEYS:
        p = tp.plan_for(*k)
        for snap in (True, False):
            exp = "base" if p["sm_jig"] == "base" else ("grid" if snap and p["jig_fix"] == "grid" else "none")
            assert tp.jig_kind(p, snap) == exp
        for ok in (True, False):                                   # 기존 호출(kind None) = 지금 식 그대로
            assert tp.metric_effective(p, "jig", ok) == tp.metric_effective(p, "jig", ok, kind=None)
            assert tp.metric_effective(p, "jig", ok, kind="base") == tp.metric_effective(p, "jig", ok)
        if p["jig_fix"] == "grid":
            assert tp.metric_effective(p, "jig", True, kind="grid") == "jig"
            assert tp.metric_effective(p, "jig", False, kind="grid") == "solve"
            assert tp.metric_effective(p, "lin", True, kind="grid") == "solve"
            assert tp.cross_mesh(p) is True
    assert tp.PLAN_VERSION == 1 and tp.hash_view({"method": "work", "cell_size_mm": None, "work": {}}) == \
        {"method": "work", "cell_size_mm": None, "work": {}, "plan_version": 1}


def test_callers_read_columns_not_scenario_names():
    """격자 지그 호출부(_jg_*)는 계획 열·지그 종류 값만 읽음 — 시나리오·계획 이름 문자열 비교 없음(정적)."""
    names = ("same", "mesh", "step", "compare", "select", "case_once", "bmesh_once", "step_once", "step_per_design",
             "compare_per_shape")
    for nm, fn in inspect.getmembers(stg, inspect.isfunction):
        if not nm.startswith("_jg_"):
            continue
        src = inspect.getsource(fn)
        assert "c.scn" not in src, nm
        for n in names:
            assert not re.search(rf"==\s*[\"']{n}[\"']", src), (nm, n)


# ---------------------------------------------------------------- V-0248-JG-15 설정 범위(코어 CONFIG_INVALID — 백엔드 422 는 B1)
def _ctx(grid=None, scn="compare", **doe):
    d = {"id": "P", "scenario": scn, "cfg": copy.deepcopy(G.CFG_FULL), "entries": [], "rank": G.rank_snap(grid=grid),
         "load_transfer": dict(G.LT), **doe}
    return stg.Ctx({"stage": "bd_post", "out": "/tmp/_jg_plan_unused", "doe": d})


@pytest.mark.parametrize("key,val", [("cell_mm", 1.0), ("cell_mm", 500.0), ("conv_mm", [3.0]), ("conv_mm", [5.0, 6.0, 7.0, 8.0]),
                                     ("tie_capture_rel", 0.0), ("tie_snap_rel", 0.1), ("tie_normal_deg", 90.0),
                                     ("tie_miss_frac_max", 1.5), ("sample_nbr", 4), ("sample_normal_deg", 0.0),
                                     ("area_ratio_warn", 1.0), ("conv_warn", 0.0), ("frame_shift_warn", 0.0),
                                     ("load_resid_warn", 0.0), ("noise_floor_min", 0.3)])
def test_cfg_ranges(key, val):
    g = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    g[key] = val
    with pytest.raises(EslError) as ei:
        stg._jg_cfg(_ctx(grid=g))
    assert ei.value.code == "CONFIG_INVALID"


def test_defaults_keys_match_contract():
    assert DEFAULTS["rank"]["jig_grid"] == {"enabled": True, "cell_mm": 3.0, "conv_mm": [5.0, 10.0], "tie_capture_rel": 0.25,
                                            "tie_snap_rel": 0.75, "tie_normal_deg": 30.0, "tie_miss_frac_max": 0.1,
                                            "sample_nbr": 1, "sample_normal_deg": 45.0, "area_ratio_warn": 2.0,
                                            "conv_warn": 0.02, "frame_shift_warn": 0.5, "load_resid_warn": 1.0e-6,
                                            "noise_floor_min": 0.01}
    assert set(gm.HASH_EXCLUDE) <= set(DEFAULTS["rank"]["jig_grid"])
    assert stg._jg_cfg(_ctx(grid=True))["cell_mm"] == 3.0


# ---------------------------------------------------------------- V-0248-JG-12 해시 · V-11 base 모드 해시 불변
def test_hash_view_excludes_and_base_mode_ignores_grid(tmp_path):
    raw = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    hv = gm.hash_view(raw)
    for k in gm.HASH_EXCLUDE:
        r2 = dict(raw)
        r2[k] = (raw[k] * 2 if not isinstance(raw[k], list) else [7.0])
        assert gm.hash_view(r2) == hv, k                           # 해시 밖 키 변경 = 불변
    r3 = dict(raw, tie_capture_rel=0.3)
    assert gm.hash_view(r3) != hv
    assert gm.hash_view({k: v for k, v in raw.items() if k != "conv_mm"}) == hv   # 스냅샷 원본(설정에 키 추가해도 불변)
    for scn, sb in KEYS:
        if tp.plan_for(scn, sb)["sm_jig"] != "base":
            continue
        kw = {"select_base": sb} if sb else {}
        a = stg._cfg_hash(_ctx(grid=None, scn=scn, **kw))
        b = stg._cfg_hash(_ctx(grid=True, scn=scn, **kw))
        assert a == b and stg._jg_kind(_ctx(grid=True, scn=scn, **kw)) == "base", (scn, sb)


def test_grid_hash_changes_with_raw_and_prep(tmp_path):
    out = tmp_path / "o"
    (out / "prep").mkdir(parents=True)

    def h(grid, prep=None):
        d = {"id": "P", "scenario": "compare", "cfg": copy.deepcopy(G.CFG_FULL), "entries": [], "rank": G.rank_snap(grid=grid),
             "load_transfer": dict(G.LT)}
        if prep is not None:
            import json
            (out / "prep" / stg.JG_JSON).write_text(json.dumps(prep))
        return stg._cfg_hash(stg.Ctx({"stage": "bd_eval", "out": str(out), "doe": d}))
    old = h(None)
    g = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    h0 = h(g, {"status": "ok", "groups": [{"sha256": "a"}], "seconds": 1.0})
    assert h0 != old
    assert h(dict(g, conv_warn=0.5, noise_floor_min=0.05), {"status": "ok", "groups": [{"sha256": "a"}], "seconds": 9.0}) == h0
    assert h(g, {"status": "ok", "groups": [{"sha256": "b"}], "seconds": 1.0}) != h0          # Case 지그 npz 교체 = 변함
    assert h(dict(g, tie_snap_rel=1.0), {"status": "ok", "groups": [{"sha256": "a"}], "seconds": 1.0}) != h0


# ---------------------------------------------------------------- V-0248-JG-14 문구(코어 원본)
def test_messages_have_new_codes():
    msgs = load_messages()["messages"]
    for c in ("JIG_GRID_SOURCE_MISSING", "JIG_GRID_TIE_MISS", "JIG_GRID_OUTSIDE", "JIG_GRID_LOAD_RESID", "JIG_GRID_AREA_RATIO",
              "JIG_GRID_FRAME_SHIFT", "JIG_GRID_CONV", "JIG_GRID_NO_REF", "JIG_GRID_RANK"):
        assert msgs.get(c), c
    assert "다시 실행" in msgs["JIG_GRID_SOURCE_MISSING"] and "복제" in msgs["JIG_GRID_SOURCE_MISSING"]
    assert "{cell_mm}" in msgs["JIG_GRID_RANK"]


def test_jig_kind_accepts_snapshot_block_and_schema_hash():
    """백엔드는 grid_snap 에 스냅샷 rank.jig_grid 블록(dict) | None 을 넘김 — dict = 참, 블록 enabled 거짓 = none. 블록 안 schema 1 = 해시 고정."""
    p = tp.plan_for("compare")
    blk = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    assert tp.jig_kind(p, blk) == "grid" and tp.jig_kind(p, None) == "none"
    assert tp.jig_kind(p, {**blk, "enabled": False}) == "none" and tp.jig_kind(tp.plan_for("same"), None) == "base"
    assert gm.hash_view({**blk, "schema": 1}) == gm.hash_view(blk)
