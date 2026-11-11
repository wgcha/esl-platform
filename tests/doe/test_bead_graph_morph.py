"""V-BG-5 (esl part: Basis + design_state), V-BG-7 outside-zero, V-BG-8 frozen ramp / BG_RAMP_SHORT / BG_SEGMENT_SHORT."""
import numpy as np
import pytest
from _bg_util import CFG, bgr, bs, prepared, seg_x

from esl.errors import EslError


def _sel(g, beads, **kw):
    return {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": 1}, "beads": beads, **kw}


@pytest.fixture(scope="module")
def h5():
    mesh, g, lab, fixed, _d = prepared("h5")
    v = sorted([s for s in g["segments"] if s["type"] == "channel"], key=lambda s: seg_x(mesh, lab, s["id"]))
    norm, _ = bs.normalize(_sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": v[0]["anchor"]}]}]), CFG,
                           mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    B = bs.basis(mesh, D, CFG)
    return mesh, g, lab, D, B


def test_h5_v1_design_states(h5):
    mesh, g, lab, D, B = h5
    chk = bs.design_checks(D, B)
    assert chk["outside"] and {o["var"] for o in chk["outside"]} == {"B1_D", "B1_W"}
    x0 = mesh["x0"]
    for name, v in (("B1_D", 10.0), ("B1_D", 6.0), ("B1_W", 34.0), ("B1_D", 10.4), ("B1_D", 5.6)):
        vals = {name: v}
        x = bs.morph(x0, B, vals)
        st = bs.design_state(mesh, x0, x, D.fixed_mask, CFG, checks=chk, values=vals)
        assert st["state"] == "READY" and st["quality"]["inverted"] == 0, (name, v, st)
    # checks survive the derived.npz round trip (chk_o*)
    arr = bs.checks_arrays(chk)
    assert any(k.startswith("chk_o") for k in arr)
    back = bs.checks_from_arrays(arr)
    assert [o["var"] for o in back["outside"]] == [o["var"] for o in chk["outside"]]
    assert all(np.array_equal(a["zone"], b["zone"]) for a, b in zip(back["outside"], chk["outside"]))


def test_outside_injection(h5):
    """V-BG-7: a node outside the changed variable's zone moved 1e-3 -> FAILED_MESH BG_OUTSIDE_MOVED (after the
    inversion check); 1e-7 -> passes."""
    mesh, g, lab, D, B = h5
    chk = bs.design_checks(D, B)
    x0 = mesh["x0"]
    vals = {"B1_D": 9.0}
    x = bs.morph(x0, B, vals)
    zone = set(chk["outside"][0]["zone"].tolist())
    far = next(i for i in range(x0.shape[0]) if i not in zone)
    for amp, ok in ((1e-3, False), (1e-7, True)):
        xx = x.copy()
        xx[far, 2] += amp
        st = bs.design_state(mesh, x0, xx, D.fixed_mask, CFG, checks=chk, values=vals)
        if ok:
            assert st["state"] == "READY"
        else:
            assert st["state"] == "FAILED_MESH" and st["code"] == "BG_OUTSIDE_MOVED"
            assert st["warnings"][0]["n"] == 1 and st["warnings"][0]["vars"] == ["B1_D"]


def test_basis_leak(h5, monkeypatch):
    """V-BG-7: an injected leak in the package basis -> BD_MATRIX error BG_BASIS_LEAK."""
    mesh, g, lab, D, _B = h5
    import sys
    bm = sys.modules["beadgraph.morph"]
    orig = bm._one

    def leaky(M, b, ranges, cfg, fixed_mask):
        v = orig(M, b, ranges, cfg, fixed_mask)
        out = np.setdiff1d(np.arange(M.n), v["zone"])[:1]
        v["idx"] = np.r_[v["idx"], out]
        v["vec"] = np.r_[v["vec"], [[0.0, 0.0, 1e-3]]]
        return v
    monkeypatch.setattr(bm, "_one", leaky)
    with pytest.raises(EslError) as e:
        bs.basis(mesh, D, CFG)
    assert e.value.code == "BG_BASIS_LEAK"


def test_ramp_short_and_segment_short(h5):
    """V-BG-8: user range beyond the default -> BG_RAMP_SHORT; a segment shorter than 2L -> BG_SEGMENT_SHORT and
    use_default false (H6 legs, W)."""
    mesh, g, lab, D, B = h5
    gv = [{"name": v["name"], "kind": v["kind"], "nominal": float(v["nominal"]), "ramp_mm": float(v["info"]["ramp_mm"])}
          for v in D.graph_basis]
    assert bgr.ramp_short(gv, [{"name": "B1_D", "lo": 5.6, "hi": 10.4}], CFG) == []
    w = bgr.ramp_short(gv, [{"name": "B1_D", "lo": 2.0, "hi": 14.0}], CFG)
    assert w and w[0]["code"] == "BG_RAMP_SHORT" and w[0]["need_mm"] > w[0]["L_mm"]
    mesh6, g6, lab6, fixed6, _d = prepared("h6")
    leg = [s for s in g6["segments"] if s["type"] == "leg" and s["entry_width"]][0]
    n, _ = bs.normalize(_sel(g6, [{"id": "b1", "src": "graph", "segs": [{"anchor": leg["anchor"]}]}]), CFG, mesh=mesh6,
                        graph=g6, labels=lab6)
    D6 = bgr.derive_obj_v2(mesh6, n, CFG, g6, lab6, fixed_node_ids=fixed6)
    bs.basis(mesh6, D6, CFG)
    rows = {r["name"]: r for r in bs.params_table(D6, CFG)}
    assert rows["B1_W"]["use_default"] is False
    assert any(w["code"] == "BG_SEGMENT_SHORT" for w in D6.beads[0].warnings)


def test_linear_frozen(h5):
    """V-BG-8: inside the default range the morph is linear (x(v) - x0 = (v - v_nom) B)."""
    mesh, g, lab, D, B = h5
    x0 = mesh["x0"]
    a = bs.morph(x0, B, {"B1_D": 9.0}) - x0
    b = bs.morph(x0, B, {"B1_D": 10.0}) - x0
    assert np.abs(2.0 * a - b).max() <= 1e-12


@pytest.mark.slow
@pytest.mark.parametrize("key", ["b", "d", "f"])
def test_h6_recipes_through_esl(key):
    """V-BG-5 (esl): selected H6 recipes through bead_select.basis / design_state -> READY, no inversion."""
    from beadgraph.testing import conformance as cf
    mesh, g, lab, fixed, _d = prepared("h6")
    rec = cf.h6_recipes(g, lab, cf.load_fixture("h6"))[key][0]
    _n, kind, segs, zones, dv = rec
    beads = [{"id": "b1", "src": "graph", "segs": [{"anchor": g["segments"][s]["anchor"]} for s in segs]}]
    norm, _ = bs.normalize(_sel(g, beads), CFG, mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    B = bs.basis(mesh, D, CFG)
    chk = bs.design_checks(D, B)
    v = B.by_name()[f"B1_{kind}"]
    row = {r["name"]: r for r in bs.params_table(D, CFG)}[v["name"]]
    ext = max(abs(x - v["nominal"]) for x in row["default_range"])      # guard / ramp frozen at the default range end
    vals = {v["name"]: v["nominal"] + np.sign(dv) * min(abs(dv), ext)}
    x = bs.morph(mesh["x0"], B, vals)
    st = bs.design_state(mesh, mesh["x0"], x, D.fixed_mask, CFG, checks=chk, values=vals)
    assert st["state"] == "READY" and st["quality"]["inverted"] == 0, st
    if key == "f":
        assert any(w["code"] == "BG_SHARED_CHILD" for w in D.beads[0].warnings)
    if key == "d":
        assert any(w["code"] == "BG_CORNER_GUARD" for w in D.beads[0].warnings)


@pytest.mark.slow
def test_h6_default_w_range_clamped_to_usable():
    """통합 v0.17.0(계약 §12 BG-X-1): H6 auto seed — W 기본 범위 끝 뒤집힘(포켓 ±15 mm 위 끝, 채널 −20 %)은 range_check usable 로
    줄이고 정보 BG_RANGE_CLAMPED(SELECT_RANGE_INVERTS 대신), 줄인 범위로 다시 점검하면 그래프 W 뒤집힘 없음, D 범위·기저는 그대로."""
    import copy

    mesh, g, lab, fixed, _d = prepared("h6")
    sel, _sym, _aw = bgr.auto_seed(g, lab, CFG)
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    B = bs.basis(mesh, D, CFG)
    before = {r["name"]: r for r in copy.deepcopy(bs.params_table(D, CFG))}
    rc = bs.range_check(mesh, D, B, CFG)
    inv = {w["var"]: w for w in rc if w["code"] == "SELECT_RANGE_INVERTS"}
    assert inv and all(v.endswith("_W") for v in inv)                     # H6: only W ends invert
    cl = bgr.clamp_w_ranges(D, rc)
    assert {c["var"] for c in cl} == set(inv)
    assert not any(w["code"] == "SELECT_RANGE_INVERTS" for w in rc)
    after = {r["name"]: r for r in bs.params_table(D, CFG)}
    for c in cl:
        assert c["level"] == "info" and c["from"] == before[c["var"]]["default_range"]
        assert after[c["var"]]["default_range"] == c["to"] == inv[c["var"]]["usable"]
        lo, hi = c["to"]
        assert lo < after[c["var"]]["nominal"] < hi
        assert after[c["var"]]["feasible"] == before[c["var"]]["feasible"]
        b = next(x for x in D.beads if x.id == c["bead"])
        assert [w["code"] for w in b.warnings].count("BG_RANGE_CLAMPED") == 1
        assert not any(w["code"] == "SELECT_RANGE_INVERTS" for w in b.warnings)
    for k, r in after.items():
        if k not in inv:
            assert r["default_range"] == before[k]["default_range"], k
    rc2 = bs.range_check(mesh, D, B, CFG)
    assert not any(w["code"] == "SELECT_RANGE_INVERTS" for w in rc2), rc2


def test_clamp_keeps_degenerate_and_non_graph():
    """usable 이 공칭을 품지 못하면(끝이 공칭에 붙음) 줄이지 않음, 그래프 W 가 아닌 변수(elems·D)는 손대지 않음."""
    class _B:
        def __init__(self, bid, src="graph"):
            self.id, self.src, self.vars, self.W_nom = bid, src, ["D", "W"], 10.0
            self.range_default = {"D": [1.0, 2.0], "W": [8.0, 12.0]}
            self.warnings = []

    class _D:
        norm = {"ties": []}
        beads = [_B("b1"), _B("b2"), _B("b3", src="elems")]
    d = _D()
    rc = [{"code": "SELECT_RANGE_INVERTS", "var": "B1_W", "usable": [10.0, 11.0], "inverted": [3, 0]},
          {"code": "SELECT_RANGE_INVERTS", "var": "B2_D", "usable": [1.2, 1.8], "inverted": [1, 1]},
          {"code": "SELECT_RANGE_INVERTS", "var": "B3_W", "usable": [9.0, 11.0], "inverted": [1, 1]},
          {"code": "SELECT_RANGE_INVERTS", "var": "B2_W", "usable": [9.0, 11.5], "inverted": [2, 1]}]
    out = bgr.clamp_w_ranges(d, rc)
    assert [c["var"] for c in out] == ["B2_W"] and d.beads[1].range_default["W"] == [9.0, 11.5]
    assert d.beads[0].range_default["W"] == [8.0, 12.0] and d.beads[1].range_default["D"] == [1.0, 2.0]
    assert [w["var"] for w in rc] == ["B1_W", "B2_D", "B3_W", "B2_W"] and rc[-1]["code"] == "BG_RANGE_CLAMPED"
