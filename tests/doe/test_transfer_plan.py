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
    assert DEFAULTS["rank"]["metric"] == "solve" and DEFAULTS["rank"]["lin_form"] == "ritz"   # SM-11 기본 재풀이 C
    assert DEFAULTS["rank"]["lin_valid"] == 0.3 and DEFAULTS["rank"]["imbalance_warn"] == 0.02
    w = DEFAULTS["load_transfer"]["work"]
    assert (w["fail_dist_mm"], w["fail_frac"]) == (20.0, 0.2)
    src = inspect.getsource(stg._sm_eval)
    assert "c.scn" not in src and "BASELINE" in src                                # 계획 열만 — did 분기는 참조 생성 1회뿐
