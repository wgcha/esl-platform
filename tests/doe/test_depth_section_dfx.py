"""v0.24.7 DF 현장 보강(D-0.24.7-DM-33~36, 계약 esl_bead_depth_mode §1.2.1·§2.3·§2.6·§8-3): H6 ch1 floor_fixed D 의 range guard
사용 범위(기본 범위 끝), DF 항목 입구 가드 품질 기준 전달(range guard 켬일 때만), basis.json section 진단 키(§2.6 표)."""
import synth_guard as sg
from _bg_util import CFG, cf, prepared

from esl.doe import DEFAULTS
from esl.doe import bead_graph as bgr
from esl.doe import stages as stg

FF = {"depth_section": "floor_fixed", "section_rules": dict(DEFAULTS["depth_section_rules"])}


def _ch1_guard(ds_kw):
    mesh, g, lab, fx = prepared("h6")[:4]
    segs = cf.h6_recipes(g, lab, cf.load_fixture("h6"))["b"][0][2]
    seed = {"beads": [{"id": "b1", "name": "B1", "src": "graph", "vars": ["D"],
                       "segs": [{"anchor": g["segments"][s]["anchor"]} for s in segs]}]}
    t = bgr.range_guard_table(mesh, g, lab, fx, CFG, sg.rules(), seed=seed,
                              exclude_segs=[s["id"] for s in g["segments"] if s["id"] not in segs], **ds_kw)
    return next(e for e in t["entries"] if e["var"] == "B1_D")


def test_h6_ch1_floor_fixed_range_guard_v3():
    """§8-3(기본 범위 끝): H6 ch1 floor_fixed D(DF) 사용 범위가 blocked 아님, 아래 한계 ≤ entry_fixed 아래 한계 + 0.5 mm."""
    ent = _ch1_guard({})
    flo = _ch1_guard(FF)
    assert flo["key"].get("ds") == "floor_fixed" and "ds" not in ent["key"]
    assert flo["from"] == ent["from"] == [5.6, 10.4]
    assert flo["state"] != "blocked"
    assert flo["usable"][0] <= ent["usable"][0] + 0.5
    print(f"\n[V-0247-DM-3 rg] ch1 entry_fixed {ent['usable']} {ent['state']} / floor_fixed {flo['usable']} {flo['state']}")


def test_df_item_guard_quality_only_with_range_guard():
    """DM-35: DF 항목 guard_jac_min·guard_tri_angle_min_deg = range guard(켬) 기준, 꺼짐 = 키 없음. W1·D·W 항목엔 없음."""
    rg = sg.rules()["range_guard"]
    assert bgr._df_guard_q(rg) == {"guard_jac_min": float(rg["jac_min"]),
                                   "guard_tri_angle_min_deg": float(rg["tria_angle_min_deg"])}
    assert bgr._df_guard_q(None) is None
    assert bgr._df_guard_q({**rg, "jac_min": None, "tria_angle_min_deg": None}) is None

    class _B:
        id, zone_ids, hold_fixed, depth_kind, w_side = "b1", [], 1, "DF", None
        segs = []

    class _D:
        section_rules = dict(DEFAULTS["depth_section_rules"])
        df_guard_q = bgr._df_guard_q(rg)
    old = bgr._var_segs
    bgr._var_segs = lambda b, typ: [1]
    try:
        pk = bgr._pkg_item(_D, _B, "D")
        assert pk["kind"] == "DF" and pk["guard_jac_min"] == float(rg["jac_min"])
        _D.df_guard_q = None
        pk = bgr._pkg_item(_D, _B, "D")
        assert "guard_jac_min" not in pk and "guard_tri_angle_min_deg" not in pk
    finally:
        bgr._var_segs = old


def test_sec_diag_keys_v26():
    """§2.6 표: DF section 키 전부(entry_guard_n·entry_guard_left 포함), W1 one_side.steep_deg(같은 비드 DF)·center_shift_mm."""
    df = {"name": "B1_D", "kind": "DF",
          "info": {"cot_min": 0.5, "cot_med": 1.0, "cot_max": 2.0, "floor_plan_max_mm": 0.0, "angle_dev_mm": 0.1,
                   "entry_clipped_n": 3, "entry_guard_n": 7, "entry_guard_left": 0, "wall_no_entry_n": 0,
                   "steep_deg": [45.0, 52.1], "warnings": [{"code": "SELECT_BLEND_CLIPPED"}]}}
    w1 = {"name": "B1_W", "kind": "W1",
          "info": {"ext": 6.0, "floor_nominal": 20.0,
                   "one_side": {"3": {"fixed": {"child": 0, "shared": 1, "junction": 0, "edge": 0, "own_wall": 0}}}}}
    s = stg._sec_diag(df, [df, w1])
    assert {"mode", "cot_min_deg", "cot_med_deg", "cot_max_deg", "floor_plan_max_mm", "angle_dev_mm", "entry_clipped_n",
            "entry_guard_n", "entry_guard_left", "band_clipped", "wall_no_entry_n"} <= set(s)
    assert s["entry_guard_n"] == 7 and s["entry_guard_left"] == 0 and s["band_clipped"] is True
    o = stg._sec_diag(w1, [df, w1])["one_side"]
    assert {"segs", "fixed", "steep_deg", "center_shift_mm"} <= set(o)
    assert o["steep_deg"] == [45.0, 52.1] and o["center_shift_mm"] == 3.0
    assert stg._sec_diag(w1, [w1])["one_side"]["steep_deg"] is None
