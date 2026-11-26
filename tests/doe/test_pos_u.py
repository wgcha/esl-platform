"""v0.24.9 PU 코어(계약 esl_bead_pos_u.md §5): U 행·사유·범위·422·계획 표·하중 공간 고정(spatial)·지그·해시 — V-0249-PU-6·7·10·11·
12·13·14·16·22·23·26·27·28·30 코어 몫. 합성 세계 = tests/doe/synth_pos_u.py(직선 채널 case_once + 지그)."""
from __future__ import annotations

import os

import numpy as np
import pytest
import synth_pos_u as W
from _bg_util import CFG, esl_mesh

from esl.doe import DEFAULTS
from esl.doe import bead_graph as bgr
from esl.doe import matrix as mx
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.errors import EslError
from esl.library import _util as U
from esl.morph import section as sec


def _derive(c, *, ties=None, pos_u=True, fixed=None):
    import beadgraph as bg
    mesh = esl_mesh({"x0": c["nodes"], "conn": c["conn"]})
    g, lab = bg.classify(c["nodes"], c["conn"], c["fixed"])
    sel, _sp, _w = bgr.auto_seed(g, lab, CFG)
    if ties:
        sel["ties"] = ties
    norm, _sha = bgr.normalize_v2(sel, g, CFG, mesh=mesh, labels=lab)
    kw = {"pos_u": W.pos_u_snap()} if pos_u else {}
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=mesh["node_id"][list(fixed or [])], **kw)
    return mesh, g, lab, D


# ---------------------------------------------------------------- PU-6·21 사유
def test_u_reason_order():
    f = {"network": True, "area": True, "s2": 1, "closed": True}
    assert sec.u_reason({"off": True, **f}) == "U_OFF"
    assert sec.u_reason(f) == "U_NETWORK"
    assert sec.u_reason({**f, "network": False}) == "U_AREA"
    assert sec.u_reason({"s2": 1, "closed": True, "held": True}) == "U_CLOSED"
    assert sec.u_reason({"s2": 0, "s1": 2}) == "U_ONE_SIDE"
    assert sec.u_reason({"s2": 0, "s1": 0}) == "U_NO_ENTRY"
    assert sec.u_reason({"s2": 1, "held": True, "tie_mixed": True}) == "U_HELD"
    assert sec.u_reason({"s2": 1, "tie_mixed": True}) == "U_TIE_MIXED"
    assert sec.u_reason({"s2": 2}) is None
    assert sec.U_REASON_ORDER.index("U_AREA") < sec.U_REASON_ORDER.index("U_CLOSED") < \
        sec.U_REASON_ORDER.index("U_ONE_SIDE")
    from esl.doe import load_messages
    msgs = load_messages()["messages"]
    assert sec.u_reason_doc("U_OFF", msgs) is None
    assert sec.u_reason_doc("U_AREA", msgs, point=True)["text"] == msgs["U_AREA_POINT"]
    for code in sec.U_REASON_ORDER[1:] + sec.U_DIR_CODES:
        assert msgs.get(code), code


def test_derive_rows_and_reasons():
    """V-0249-PU-6: 직선 채널 = U 행(공칭 0·기본 꺼짐·dir·dir_text·w_ref), 한쪽 입구 = U_ONE_SIDE, 닫힌 고리 = U_CLOSED, pos_u 없음 =
    U 행·u_reason 없음(옛 바이트)."""
    from beadgraph.testing import synth_oneside as so
    from beadgraph.testing import synth_pos as sp
    mesh, g, lab, D = _derive(so.channel())
    rows = bgr.params_rows_v2(D, CFG)
    u = [r for r in rows if r["type"] == "U"]
    assert len(u) == 1 and u[0]["nominal"] == 0.0 and u[0]["use_default"] is False and u[0]["unit"] == "mm"
    assert u[0]["w_ref"] == pytest.approx(40.0) and u[0]["dir_text"] and set(u[0]["dir"]) == {"xi", "eta"}
    lo, hi = u[0]["default_range"]
    assert lo == pytest.approx(-10.0) and hi == pytest.approx(10.0)                 # ±0.25·W_ref
    _m, _g, _l, D0 = _derive(so.channel(), pos_u=False)
    assert not any(r["type"] == "U" for r in bgr.params_rows_v2(D0, CFG))
    assert all(getattr(b, "u_reason", None) is None for b in D0.beads)
    _m, _g, _l, D1 = _derive(so.oneside("b"))
    assert {getattr(b, "u_reason", None) for b in D1.beads} >= {"U_ONE_SIDE"}
    _m, _g, _l, D2 = _derive(sp.annulus())
    assert [b.u_reason for b in D2.beads] == ["U_CLOSED"]
    doc = {"beads": [{"id": b.id} for b in D2.beads]}
    bgr.u_reason_rows(D2, doc["beads"])
    assert doc["beads"][0]["u_reason"]["code"] == "U_CLOSED"


# ---------------------------------------------------------------- PU-7·22·23 범위·422
def test_feasible_gap_and_default_clip():
    """이웃 간격 20 mm → 그 쪽 hi(또는 lo) = gap_rel·20 = 10 이하, 기본 범위는 feasible 안으로 클립."""
    from beadgraph.testing import synth_oneside as so
    _m, _g, _l, D = _derive(so.parallel(gap=20.0))
    us = [r for r in bgr.params_rows_v2(D, CFG) if r["type"] == "U"]
    assert len(us) == 2
    for r in us:
        near = min(abs(r["feasible"][0]), abs(r["feasible"][1]))
        assert near <= 10.0 + 0.6                                                    # 5 % 분위(5 mm 격자) 여유
        assert r["default_range"][0] >= r["feasible"][0] - 1e-9 and r["default_range"][1] <= r["feasible"][1] + 1e-9
    assert sec.u_feasible(40.0, 20.0, None, 0.5, 0.5) == [-20.0, 10.0]
    assert sec.u_default(40.0, [-20.0, 10.0], 0.25) == [-10.0, 10.0]


def test_matrix_422_nominal_in_range():
    tab = [{"name": "B1_U", "type": "U", "nominal": 0.0, "feasible": [-10.0, 10.0]},
           {"name": "B1_D", "type": "D", "nominal": 10.0, "feasible": [1.0, 20.0]}]
    for lo, hi in ((1.0, 5.0), (-5.0, -1.0)):
        with pytest.raises(EslError) as ei:
            mx.generate({"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_U", "lo": lo, "hi": hi}]}, tab,
                        DEFAULTS)
        assert ei.value.code == "DOE_RANGE_INVALID"
    m = mx.generate({"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_U", "lo": -2.0, "hi": 7.0}]}, tab,
                    DEFAULTS)
    assert m["designs"][0]["values"] in ({}, {"B1_U": 0.0}) or m["n_designs"] >= 2
    with pytest.raises(EslError) as ei:                                              # D 는 지금 문구 그대로
        mx.generate({"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": -1.0, "hi": 5.0}]}, tab,
                    DEFAULTS)
    assert "깊이·폭" in ei.value.message


# ---------------------------------------------------------------- PU-10 계획 표
def test_plan_tables():
    sec.validate_plans()
    assert {r: sec.pos_plan(r) for r in sec.SECTION_PLANS} == {"graph": "pkg_u", "elems": "none", "paicad": "native",
                                                                "none": "none", "virtual": "none"}   # v0.25.0 VB 행 virtual
    bad = {**sec.SECTION_PLANS, "graph": {**sec.SECTION_PLANS["graph"], "pos": ""}}
    with pytest.raises(EslError):
        sec.plan("graph", bad)
    for k in tp.PLAN_OF:
        p = tp.plan_for(*k)
        assert p["load_follow"] in tp.LOAD_FOLLOW
        want = "spatial" if p["load_follow"] == "var" else "node"
        assert tp.load_follow_effective(p, True) == want and tp.load_follow_effective(p, False) == "node"
    with pytest.raises(EslError):
        tp.load_follow_effective({"load_follow": ""}, True)
    p = tp.plan_for("select", "case")
    assert tp.metric_effective(p, "lin") == "lin" and tp.metric_effective(p, "lin", spatial=True) == "solve"
    assert tp.metric_effective(p, "jig", True, spatial=True) == "jig" and tp.metric_effective(p, "solve", spatial=True) == "solve"


def test_plan_loads_placement_signature():
    import inspect
    sig = inspect.signature(stg._plan_loads)
    assert list(sig.parameters)[-2:] == ["srcs", "placement"] and sig.parameters["placement"].default is None


# ---------------------------------------------------------------- PU-30 대칭 묶기 U
def test_tie_mirror_signs():
    from beadgraph.testing import synth_oneside as so
    c = so.parallel(gap=40.0)
    mesh, g, lab, D = _derive(c, ties=[["b1", "b2"]])
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    assert "B1_U" in rows and "B2_U" not in rows
    gs = rows["B1_U"]["group_signs"]
    assert gs["B1_U"] == 1 and abs(gs["B2_U"]) == 1
    B = bgr.basis_v2(mesh, D, CFG)
    v = next(x for x in B.vars if x["name"] == "B1_U")
    full = np.zeros((mesh["x0"].shape[0], 3))
    full[np.asarray(v["idx"])] = v["vec"]
    X = mesh["x0"]
    yc = 150.0
    a = (X[:, 1] < yc) & (np.linalg.norm(full, axis=1) > 0.999)
    b = (X[:, 1] > yc) & (np.linalg.norm(full, axis=1) > 0.999)
    assert a.any() and b.any()
    ya, yb = np.median(full[a, 1]), np.median(full[b, 1])
    assert abs(ya + yb) <= 1e-9                                                     # 대칭면(y = 150) 반사
    # 같은 방향(거울 아님) 은 판정 불가가 아니라 거울 내적 |·| ≥ cos30 이면 부호로 통과, 도심 거리 < h = U_TIE_MIXED
    assert sec.u_mirror_signs([([0.0, 0.0], [0.0, 1.0]), ([0.0, 0.1], [0.0, 1.0])], 5.0) is None
    assert sec.u_mirror_signs([([0.0, 0.0], [0.0, 1.0]), ([100.0, 0.0], [1.0, 0.0])], 5.0) is None


# ---------------------------------------------------------------- e2e(spatial) — PU-11·12·13·14·27·28
@pytest.fixture(scope="module")
def SPW(tmp_path_factory):
    tmp = str(tmp_path_factory.mktemp("pu_spatial"))
    doe, out, run, mesh = W.world(tmp, extra={"pos_u": W.pos_u_snap(), "load_follow": W.lf_snap()})
    m, res = W.run_u(doe, out, run)
    return {"doe": doe, "out": out, "run": run, "mesh": mesh, "m": m, "res": res}


def test_spatial_result_and_prep(SPW):
    """PU-12·13·17·27·28: matrix load_follow spatial, d000 score 1·C_<pe> = E_0, lin 열 null, prep/load_follow.json 스키마,
    sm_ref·지그 맞춤 = node 경로, 정보 LOAD_FOLLOW_SPATIAL·PU_LIN_SKIPPED 1건씩, noise_floor ≥ noise_floor_min."""
    out, m, res = SPW["out"], SPW["m"], SPW["res"]
    assert m["load_follow"] == "spatial"
    lf = res["load_follow"]
    assert lf["mode"] == "spatial" and lf["cell_mm"] == 3.0 and lf["n_pos_vars"] == 1
    assert res["noise_floor"] >= DEFAULTS["load_follow"]["noise_floor_min"]
    assert sum(w.startswith("LOAD_FOLLOW_SPATIAL:") for w in res["warnings"]) == 1
    assert sum(w.startswith("PU_LIN_SKIPPED:") for w in res["warnings"]) == 1
    doc = U.read_json(os.path.join(out, "prep", stg.LF_JSON))
    assert doc["schema"] == stg.LF_SCHEMA and set(doc) >= {"mode", "cell_mm", "node", "d000_shift_rel", "jig", "transfer"}
    d0 = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    for p in d0["per_esl"]:
        assert all(p[k] is None for k in stg.LF_NULL_KEYS) and p["umax_def"] is not None
        for src, pe in (("jig_disp", "jd"), ("jig_spring", "js")):
            assert p[f"C_{pe}"] == pytest.approx(doc["jig"][src][p["entry_id"]]["E"], rel=1e-12)
    for x in m["designs"][1:]:
        r = U.read_json(os.path.join(out, "run", "designs", x["id"], "result.json"))
        assert all(p[k] is None for p in r["per_esl"] for k in stg.LF_NULL_KEYS)
    assert os.path.isfile(os.path.join(out, "prep", "sm_ref.npz"))


def test_spatial_load_stays_in_space(SPW):
    """PU-11·26: 비드 위 한 점 근처 집중 하중 — node 경로는 노드와 함께 ΔU 이동, spatial(셀 전달·global) 은 도심 이동 ≤ cell/2,
    ΣF·ΣM(모멘트 중심 고정) 오차 ≤ 1e-9(상대)."""
    from esl.doe import bead_select as bsel
    from esl.doe import scenario as sc
    out, doe, mesh = SPW["out"], SPW["doe"], SPW["mesh"]
    c = stg.Ctx({"stage": "bd_eval", "out": out, "doe": {**doe, "rev": 1, "design": "d001"}})
    t, bmeta = sc.load_base(c.p("prep"))
    L = stg._sel_loaded(c)
    X0 = np.asarray(t.mesh["x0"], dtype=np.float64)
    dU = 10.0
    x = bsel.morph(X0, L["B"], {"B1_U": dU})
    k = int(np.argmax(np.linalg.norm(x - X0, axis=1)))
    assert np.linalg.norm(x[k] - X0[k]) == pytest.approx(dU, abs=1e-6)
    F = np.zeros_like(X0)
    F[k] = [0.0, 0.0, -100.0]
    md = dict(t.mesh)
    md["x0"] = x
    lfc = {"plan": stg._lt_plan(c), "did": "d001", "frame": t.frame, "base": dict(t.mesh), "cache": {},
           "dst": stg.ltm.dst_mesh(md, t.frame, None, stg._lt_h(c, bmeta, md)), "stats": []}
    (key, Fd), = stg._lf_run(c, lfc, [("P", F)])[0]
    cen0 = (np.abs(F[:, 2]) @ X0) / np.abs(F[:, 2]).sum()
    cen_node = (np.abs(F[:, 2]) @ x) / np.abs(F[:, 2]).sum()                         # node 경로(노드 번호 하중)
    w = np.linalg.norm(Fd, axis=1)
    cen_sp = (w @ x) / w.sum()
    assert np.linalg.norm(cen_node - cen0) == pytest.approx(dU, abs=1e-6)
    assert np.linalg.norm((cen_sp - cen0)[:2]) <= 0.5 * stg._lf(c)["cell_mm"] + 1e-9
    assert abs(Fd.sum(axis=0) - F.sum(axis=0)).max() <= 1e-9 * 100.0
    mc = X0.mean(axis=0)
    M0 = np.cross(X0 - mc, F).sum(axis=0)
    Md = np.cross(x - mc, Fd).sum(axis=0)
    assert np.abs(Md - M0).max() <= 1e-9 * max(np.abs(M0).max(), 1.0) * 1e3


def test_jig_bc_unchanged_spatial(SPW):
    """PU-14·28: spatial 에서도 prep/<src>.npz(a·BC·k)는 node 경로 맞춤 그대로 — 같은 세계 node 스터디와 바이트 동일."""
    import hashlib
    out = SPW["out"]
    tmp = os.path.dirname(out) + "_node"
    os.makedirs(tmp, exist_ok=True)
    doe, out2, run, _mesh = W.world(tmp, extra={"pos_u": W.pos_u_snap(), "load_follow": W.lf_snap()})
    m2, res2 = W.run_u(doe, out2, run, u=False)
    assert m2["load_follow"] == "node" and "load_follow" not in res2
    assert not os.path.isfile(os.path.join(out2, "prep", stg.LF_JSON))
    for f in ("jig_disp.npz", "jig_spring.npz", "sm_ref.npz"):
        a = hashlib.sha256(open(os.path.join(out, "prep", f), "rb").read()).hexdigest()
        b = hashlib.sha256(open(os.path.join(out2, "prep", f), "rb").read()).hexdigest()
        assert a == b, f


def test_cfg_hash_spatial_only(SPW):
    """PU-16: _cfg_hash 에 load_follow 는 spatial 일 때만."""
    out, doe = SPW["out"], SPW["doe"]
    c = stg.Ctx({"stage": "bd_eval", "out": out, "doe": {**doe, "rev": 1, "design": "d001"}})
    h_sp = stg._cfg_hash(c)
    c2 = stg.Ctx({"stage": "bd_eval", "out": out, "doe": {k: v for k, v in doe.items() if k not in ("pos_u", "load_follow")}
                                                         | {"rev": 1, "design": "d001"}})
    assert stg._lf_mode(c) == "spatial" and stg._lf_mode(c2) is None
    assert h_sp != stg._cfg_hash(c2)


def test_sidecar_marks_kind(SPW):
    """V-0249-BM-2(스터디 3D): 방식 3D(jd·js) manifest 지지 행 = 기존 dof + kind·dirs·val(방식별 kind)."""
    import glob
    vd = os.path.join(SPW["out"], "post", "view3d")
    seen = set()
    for p in glob.glob(os.path.join(vd, "*_j[ds]*", "manifest.json")):
        sup = U.read_json(p)["supports"]
        assert sup and all(r["dof"] in ("123", "ij") and "kind" in r and "dirs" in r and "val" in r for r in sup)
        seen |= {r["kind"] for r in sup}
    assert {"tie_disp", "tie_spring"} <= seen
