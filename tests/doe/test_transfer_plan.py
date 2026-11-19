"""하중 전달 계획 표(계약 esl_load_transfer.md §13.3 V-LT-14): plan_for 7 조합, 해석(resolve)·alt_designs·PLAN_VERSION,
stages 하중 자리가 ``_plan_loads`` 하나만 부르고 그 안에 시나리오 분기가 없음(코드 검사)."""
import inspect
import re

import pytest

from esl.doe import DEFAULTS
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.errors import EslError


def test_plan_table():
    want = {("same", None): ("case_once", "baseline", "once", "topo", "global", "none"),
            ("select", "case"): ("case_once", "baseline", "once", "topo", "global", "none"),
            ("mesh", None): ("bmesh_once", "baseline", "once", "none", "auto", "none"),
            ("select", "mesh"): ("bmesh_once", "baseline", "once", "none", "auto", "none"),
            ("select", "step"): ("step_once", "baseline", "once", "none", "auto", "step_region"),
            ("step", None): ("step_per_design", "design", "per_target", "none", "auto", "none"),
            ("compare", None): ("compare_per_shape", "shape", "per_target", "topo+coords", "global", "compare_region")}
    for (scn, base), row in want.items():
        p = tp.plan_for(scn, base)
        assert (p["id"], p["dst"], p["reuse"], p["identity"], p["placement"], p["mask"]) == row, (scn, base)
    assert tp.plan_for("compare", "step")["id"] == "compare_per_shape"             # select_base 는 select 만
    for bad in (("select", None), ("nope", None), ("select", "x")):
        with pytest.raises(EslError) as ei:
            tp.plan_for(*bad)
        assert ei.value.code == "CONFIG_INVALID"
    assert tp.PLANS["compare_per_shape"]["alt_designs"] and not any(
        tp.PLANS[k]["alt_designs"] for k in ("case_once", "bmesh_once", "step_once", "step_per_design"))


def test_resolve_and_defaults():
    d = DEFAULTS["load_transfer"]
    assert (d["method"], d["cell_size_mm"], d["diag"]["alt_designs"]) == ("work", None, "auto")
    assert set(DEFAULTS["compare"]["load_transfer"]) == {"support", "support_tol_mm", "region"}
    assert tp.resolve(None, "mesh") is None
    m = tp.resolve({"schema": 1, "method": "cell", "cell_size_mm": 5.0}, "mesh")
    assert m["cell_size_mm"] == 5.0 and "support" not in m and m["work"] == d["work"]
    c = tp.resolve({"schema": 1, "method": "work", "cell_size_mm": 5.0}, "compare")
    assert c["cell_size_mm"] is None and c["support"] == "transfer" and c["region"]["mode"] == "auto"
    for bad in ({"method": "cell", "cell_size_mm": 2.0}, {"method": "cell", "cell_size_mm": 201.0}):
        with pytest.raises(EslError) as ei:
            tp.resolve(bad, "same")
        assert ei.value.code == "LOAD_TRANSFER_INVALID"
    for bad in ({"method": "nope"}, {"diag": {"alt_designs": "x"}}):
        with pytest.raises(EslError):
            tp.resolve(bad, "step")
    with pytest.raises(EslError):
        tp.resolve({"support": "x"}, "compare")
    # alt_designs: auto = 계획 표 열(④ 켬, ①②③ 끔), on/off 강제, alt 없음 = 끔
    for scn, auto in (("compare", True), ("mesh", False), ("same", False), ("step", False)):
        p = tp.plan_for(scn)
        lt = tp.resolve({"method": "work"}, scn)
        assert tp.alt_designs(lt, p) is auto
        assert tp.alt_designs(tp.resolve({"diag": {"alt_designs": "on"}}, scn), p) is True
        assert tp.alt_designs(tp.resolve({"diag": {"alt_designs": "off"}}, scn), p) is False
        assert tp.alt_designs(tp.resolve({"diag": {"alt": False, "alt_designs": "on"}}, scn), p) is False
    hv = tp.hash_view(tp.resolve({"method": "work"}, "mesh"))
    assert hv["plan_version"] == tp.PLAN_VERSION and "diag" not in hv and "support" not in hv
    assert "support" in tp.hash_view(tp.resolve({"method": "work"}, "compare"))
    lt = tp.resolve({"method": "work"}, "same")
    assert [tp.variant_label(*v) for v in tp.sweep_variants(lt)] == ["work", "cell:3", "cell:legacy", "cell:10",
                                                                      "cell:5"]
    assert tp.method_of(lt, ("cell", 5.0))["cell_size_mm"] == 5.0 and tp.method_of(lt)["cell_size_mm"] is None


def test_stages_single_load_site():
    src = inspect.getsource(stg._plan_loads)
    assert "c.scn" not in src and "scenario" not in src                            # 계획 필드만 읽음
    whole = inspect.getsource(stg)
    calls = re.findall(r"run_transfer_plan\(", whole)
    assert len(calls) == 1                                                         # 공용 실행기 호출 = _plan_loads 안 1곳
    for fn in (stg._lt_base_loads, stg._lt_design, stg._lt_target_loads, stg._lt_mesh_loads, stg._cmp_loads_lt,
               stg._lt_eval):
        assert "_plan_loads(" in inspect.getsource(fn), fn.__name__
    for name in ("bd_loads", "_sel_loads", "_design_mesh", "_view3d", "_cmp_design_mesh", "_cmp_refine_bias"):
        s = inspect.getsource(getattr(stg, name))
        assert re.search(r"_lt_(base_loads|target_loads|design|mesh_loads)\(|_cmp_loads_lt\(", s) or \
            name == "_cmp_design_mesh" and "_lt_design(" in s, name
    calls_lt = re.findall(r"_plan_loads\(([^)]*)\)", whole)
    assert all("c.scn" not in a for a in calls_lt)


def test_plan_sm_columns():
    """V-SM-6(결정 A): 계획 열 sm_ref·sm_disp·sm_omega·sm_rank = esl_stiffness_metric.md §4 표 — 같은 메시(once)만 지표,
    다른 메시(per_target)는 지표 없음·순위 solve. interp(build_disp)는 어느 계획에도 없음. 빈 칸 = CONFIG_INVALID."""
    want = {"case_once": ("base", ("I", "I"), "all", "metric"), "bmesh_once": ("base", ("I", "I"), "all", "metric"),
            "step_once": ("base", ("I", "I"), "step_region", "metric"),
            "step_per_design": ("none", ("none", "none"), "all", "solve"),
            "compare_per_shape": ("none", ("none", "none"), "compare_region", "solve")}
    for pid, row in want.items():
        p = tp.PLANS[pid]
        assert (p["sm_ref"], p["sm_disp"], p["sm_omega"], p["sm_rank"]) == row, pid
        assert "interp" not in p["sm_disp"]
        assert (p["sm_rank"] == "metric") == (p["reuse"] == "once")       # 같은 위상 = 베이스라인 모핑(once)
        assert tp.metric_effective(p, "lin") == ("lin" if p["sm_rank"] == "metric" else "solve")
        assert tp.metric_effective(p, "solve") == "solve" and tp.cross_mesh(p) == (p["sm_rank"] == "solve")
    saved = dict(tp.PLANS["bmesh_once"])
    try:
        tp.PLANS["bmesh_once"]["sm_ref"] = ""
        with pytest.raises(EslError) as ei:
            tp.plan_for("mesh")
        assert ei.value.code == "CONFIG_INVALID"
    finally:
        tp.PLANS["bmesh_once"] = saved
    assert DEFAULTS["rank"]["metric"] == "jig" and DEFAULTS["rank"]["lin_form"] == "ritz"    # v0.23.0 새 스터디 기본 지그(옛 = 스냅샷 값)
    assert DEFAULTS["rank"]["lin_valid"] == 0.3 and DEFAULTS["rank"]["imbalance_warn"] == 0.02
    w = DEFAULTS["load_transfer"]["work"]
    assert (w["fail_dist_mm"], w["fail_frac"]) == (20.0, 0.2)
    src = inspect.getsource(stg._sm_eval)
    assert "c.scn" not in src and "BASELINE" in src                                # 계획 열만 — did 분기는 참조 생성 1회뿐


# ---------------------------------------------------------------- v0.21.0 BEAD_SHAPE(esl_bead_shape_v021.md V-SH-11)
def test_shape_plan_columns_and_resolve():
    """V-SH-11: 5행의 bs_wpart·bs_guard·bs_route·bs_mq = §2.2 표, 빈 칸·잘못된 값 → CONFIG_INVALID, PLAN_VERSION 1 그대로·hash_view
    불변, resolve_shape(None) = None, 잘못된 블록 → CONFIG_INVALID, shape_hash_view 에 budget 없음, stages 는 열만(시나리오 분기 없음)."""
    want = {"case_once": ("graph", "basis", "none", "none"), "bmesh_once": ("graph", "basis", "none", "none"),
            "step_once": ("graph", "basis", "base", "base"), "step_per_design": ("none", "none", "none", "none"),
            "compare_per_shape": ("none", "none", "shapes", "shapes")}
    for pid, row in want.items():
        assert tuple(tp.PLANS[pid][k] for k in ("bs_wpart", "bs_guard", "bs_route", "bs_mq")) == row, pid
    assert tp.plan_for("select", "case")["bs_guard"] == "basis" and tp.plan_for("compare")["bs_route"] == "shapes"
    assert tp.PLAN_COLS[-8:-4] == ("bs_wpart", "bs_guard", "bs_route", "bs_mq")
    for col in ("bs_wpart", "bs_guard", "bs_route", "bs_mq"):
        saved = dict(tp.PLANS["step_once"])
        try:
            tp.PLANS["step_once"][col] = ""
            with pytest.raises(EslError) as ei:
                tp.plan_for("select", "step")
            assert ei.value.code == "CONFIG_INVALID"
            tp.PLANS["step_once"][col] = "bogus"
            with pytest.raises(EslError) as ei:
                tp.plan_for("select", "step")
            assert ei.value.code == "CONFIG_INVALID"
        finally:
            tp.PLANS["step_once"] = saved
    # PLAN_VERSION·hash_view 불변(하중 전달 해시 — 옛 스냅샷 해시가 바뀌지 않음)
    assert tp.PLAN_VERSION == 1
    lt = tp.resolve({"method": "work"}, "select")
    assert tp.hash_view(lt)["plan_version"] == 1 and set(tp.hash_view(lt)) == {"method", "cell_size_mm", "work", "plan_version"}
    # resolve_shape
    assert tp.resolve_shape(None) is None
    r = tp.resolve_shape({"schema": 1})
    assert r["schema"] == 1 and r["w_partial"] is True and r["range_guard"]["flip_deg"] == DEFAULTS["select"]["quality"]["flip_deg"]
    assert r["mesh_route"]["rank_quality"]["tria_pct"] == DEFAULTS["compare"]["quality"]["tria_pct"]["fail"]   # null → 15
    assert tp.resolve_shape(r) == r                                                 # 스냅샷 재해석 = 같은 값(멱등)
    assert tp.resolve_shape(dict(DEFAULTS["shape_rules"], enabled=False)) is None    # 설정 꺼짐 = 키 없음
    off = tp.resolve_shape({"range_guard": {"enabled": False}})
    assert off["range_guard"] is None and tp.shape_hash_view(off)["range_guard"] is None
    assert tp.resolve_shape({"range_guard": None})["range_guard"] is None             # 스냅샷의 꺼진 guard
    f = tp.resolve_shape({}, flip_deg=45.0)
    assert f["range_guard"]["flip_deg"] == 45.0
    for bad in ({"w_partial": 1}, {"range_guard": {"jac_min": 1.0}}, {"range_guard": {"jac_min": 0}},
                {"range_guard": {"tria_angle_min_deg": 60}}, {"range_guard": {"area_ratio_min": 1}},
                {"range_guard": {"max_new_fail_ratio": 0}}, {"range_guard": {"steps": 0}}, {"range_guard": {"steps": 21}},
                {"range_guard": {"min_keep_frac": 1.0}}, {"range_guard": {"combo": {"full_max_vars": 9}}},
                {"range_guard": {"combo": {"samples": 0}}}, {"range_guard": {"combo": {"max_group": 1}}},
                {"range_guard": {"budget": {"prep_timeout_s": 0}}}, {"range_guard": {"budget": {"max_evals": 0}}},
                {"range_guard": {"budget": {"max_vars": 2001}}},
                {"mesh_route": {"relaxed_direct": {"min_faces": 0}}}, {"mesh_route": {"relaxed_direct": {"min_step_mb": 0}}},
                {"mesh_route": {"rank_quality": {"fail_ratio": 0}}}, {"mesh_route": {"rank_quality": {"tria_pct": 101}}}, "x"):
        with pytest.raises(EslError) as ei:
            tp.resolve_shape(bad)
        assert ei.value.code == "CONFIG_INVALID", bad
    ok = tp.resolve_shape({"mesh_route": {"relaxed_direct": {"min_faces": None, "min_step_mb": 5.5},
                                          "rank_quality": {"tria_pct": 20}}})
    assert ok["mesh_route"]["relaxed_direct"] == {"enabled": True, "min_faces": None, "min_step_mb": 5.5}
    assert ok["mesh_route"]["rank_quality"]["tria_pct"] == 20
    # shape_hash_view: budget 제외, 다른 판정 기준은 포함
    hv = tp.shape_hash_view(r)
    assert "budget" not in hv["range_guard"] and hv["range_guard"]["jac_min"] == 0.3 and hv["schema"] == 1
    r2 = tp.resolve_shape({"range_guard": {"budget": {"prep_timeout_s": 5}}})
    assert tp.shape_hash_view(r2) == hv
    r3 = tp.resolve_shape({"range_guard": {"jac_min": 0.5}})
    assert tp.shape_hash_view(r3) != hv and tp.shape_hash_view(None) is None


def test_stages_read_shape_columns_only():
    """SH-2: 형상 규칙 호출 쪽(stages·step_graph)은 계획 열 값만 읽고 시나리오 이름으로 분기하지 않는다(코드 검사)."""
    for fn in (stg._route_of, stg._bs, stg._cmp_mq_flags, stg._cmp_mq_rank, stg._sel_mq_base, stg._sel_range_guard,
               stg._sel_guard_selection, stg._guard_rows):
        src = inspect.getsource(fn)
        assert not re.search(r"c\.scn\b|scenario\s*==|select_base\(", src), fn.__name__
    assert "bs_route" in inspect.getsource(stg._route_of) and "bs_mq" in inspect.getsource(stg._cmp_mq_rank)
    assert 'bs_guard' in inspect.getsource(stg._sel_prepare) and 'bs_guard' in inspect.getsource(stg._sel_loads)


def test_redrop_column():
    """V-RD-7: 모든 PLANS 행에 redrop 열 + 값 ∈ RD_VALUES, case_once 만 node_id, 열 지우면 CONFIG_INVALID."""
    assert tp.RD_VALUES == ("node_id", "none") and "redrop" in tp.PLAN_COLS
    for pid, row in tp.PLANS.items():
        assert row["redrop"] in tp.RD_VALUES, pid
    assert [k for k, r in tp.PLANS.items() if r["redrop"] == "node_id"] == ["case_once"]
    for key in tp.PLAN_OF:
        p = tp.plan_for(*key)
        assert p["redrop"] == ("node_id" if p["id"] == "case_once" else "none")
    saved = tp.PLANS["step_once"].pop("redrop")
    try:
        with pytest.raises(EslError) as ei:
            tp.plan_for("select", "step")
        assert ei.value.code == "CONFIG_INVALID"
        tp.PLANS["step_once"]["redrop"] = "bogus"
        with pytest.raises(EslError) as ei:
            tp.plan_for("select", "step")
        assert ei.value.code == "CONFIG_INVALID"
    finally:
        tp.PLANS["step_once"]["redrop"] = saved


# ---------------------------------------------------------------- v0.23.0 JIG(esl_jig_rank.md V-JIG-10)
def test_jig_plan_columns():
    """V-JIG-10: 5행 sm_jig·jig_fix·jig_ctx = §5.2 표, 값 ∈ JIG_VALUES, 열 지우면 CONFIG_INVALID, 불변식, metric_effective 4조합."""
    want = {"case_once": ("base", "fixed", "case"), "bmesh_once": ("base", "fixed", "mesh"),
            "step_once": ("base", "xfer", "none"), "step_per_design": ("none", "none", "none"),
            "compare_per_shape": ("none", "none", "none")}
    assert tp.PLAN_COLS[-4:-1] == ("sm_jig", "jig_fix", "jig_ctx") and tp.PLAN_COLS[-1] == "bf"
    for pid, row in want.items():
        p = tp.PLANS[pid]
        assert (p["sm_jig"], p["jig_fix"], p["jig_ctx"]) == row, pid
        for k, vs in tp.JIG_VALUES.items():
            assert p[k] in vs
        if p["sm_jig"] == "base":                  # 불변식
            assert p["sm_ref"] == "base" and p["sm_disp"][1] == "I" and p["sm_rank"] == "metric"
        for ok in (True, False):
            exp = "jig" if (p["sm_jig"] == "base" and p["sm_rank"] == "metric" and ok) else "solve"
            assert tp.metric_effective(p, "jig", ok) == exp
        assert tp.metric_effective(p, "lin") == ("lin" if p["sm_rank"] == "metric" else "solve")   # 기존 호출 불변
        assert tp.metric_effective(p, "solve") == "solve"
    for col in ("sm_jig", "jig_fix", "jig_ctx"):
        for bad in ("", "bogus"):
            saved = dict(tp.PLANS["case_once"])
            try:
                tp.PLANS["case_once"][col] = bad
                with pytest.raises(EslError) as ei:
                    tp.plan_for("same")
                assert ei.value.code == "CONFIG_INVALID"
            finally:
                tp.PLANS["case_once"] = saved
