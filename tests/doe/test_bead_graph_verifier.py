"""v0.17.0 Verifier fixes (esl part — contract §12 "Verifier fixes"): permanent forms of the Verifier probes
(vprobe/outside.py · shared.py · mixed.py · the split-coordinate finding · the BG-X-1 first-matrix finding).

1. outside-zero: H6 ring left / right D through the esl pipeline (derive -> Basis -> design_checks -> design_state) —
   READY and every node of an element outside A_v (graph labels) unmoved; the BG-D-34 check uses the label-based set.
2. mixed selection: a graph bead + an elems bead changed together -> READY (no spurious BG_OUTSIDE_MOVED) and the
   movement is exactly the sum of the two single-variable designs.
3. split coordinates: the frontend planXY formula (incl. frame.origin) gives the Core plane coordinates and the split
   lands at the clicked point (round trip); the old formula without the origin does not.
4. BG-X-1: on H6 the first matrix built from the API default ranges has no inverting W design.
"""
import copy
import json
import os
import sys
import tempfile

import numpy as np
import pytest
from _bg_util import CFG, bgr, bs, prepared

from esl.errors import EslError

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _sel(g, beads, **kw):
    return {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": 1}, "beads": beads, **kw}


@pytest.fixture(scope="module")
def h6():
    return prepared("h6")


# ---------------------------------------------------------------- 1. outside-zero (High 1)
@pytest.mark.parametrize("side", ["left", "right"])
def test_h6_ring_side_d_outside_zero_esl(h6, side):
    from beadgraph.checks import allowed_elements
    mesh, g, lab, fixed, _d = h6
    s = next(x for x in g["segments"] if x["type"] == "ring" and x["side"] == side)
    norm, _ = bs.normalize(_sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": s["anchor"]}]}]), CFG,
                           mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    B = bs.basis(mesh, D, CFG)
    chk = bs.design_checks(D, B)
    x0 = mesh["x0"]
    C = mesh["conn"]
    A = allowed_elements(g, lab, x0, C, [s["id"]], (), "D")
    out_nodes = np.zeros(x0.shape[0], bool)
    out_nodes[np.unique(C[~A][C[~A] >= 0])] = True
    row = next(r for r in bs.params_table(D, CFG) if r["name"] == "B1_D")
    for v in (*row["default_range"], row["nominal"] + 2.0, row["nominal"] - 2.0):
        vals = {"B1_D": float(v)}
        x = bs.morph(x0, B, vals)
        assert float(np.linalg.norm(x - x0, axis=1)[out_nodes].max()) <= 1e-6, (side, v)
        st = bs.design_state(mesh, x0, x, D.fixed_mask, CFG, checks=chk, values=vals)
        assert st["state"] == "READY", (side, v, st["code"], st["warnings"])
    # the design check's allowed set is the label-based one: a 0.1 mm move of a shared-child wall node that the basis
    # zone covers but that belongs to the neighbouring segment's wall is caught
    zone = np.zeros(x0.shape[0], bool)
    zone[next(v for v in B.vars if v["name"] == "B1_D")["zone"]] = True
    k = int(np.flatnonzero(zone & out_nodes)[0])
    vals = {"B1_D": row["nominal"] + 1.0}
    x = bs.morph(x0, B, vals)
    x[k, 2] += 0.1
    st = bs.design_state(mesh, x0, x, D.fixed_mask, CFG, checks=chk, values=vals)
    assert st["state"] == "FAILED_MESH" and st["code"] == "BG_OUTSIDE_MOVED" and st["warnings"][0]["n"] == 1


def test_basis_leak_uses_label_based_set(h6, monkeypatch):
    """BD_MATRIX BG_BASIS_LEAK is judged on the label-based allowed set: a basis vector put on a node of an outside
    element raises it even when the basis zone claims the node."""
    import beadgraph
    mesh, g, lab, fixed, _d = h6
    s = next(x for x in g["segments"] if x["type"] == "ring" and x["side"] == "left")
    norm, _ = bs.normalize(_sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": s["anchor"]}]}]), CFG,
                           mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    real = beadgraph.basis

    def leaky(*a, **kw):
        out = real(*a, **kw)
        v = out[0]
        zone = np.asarray(v["zone"])
        C = np.asarray(kw["elems"])
        pocket = next(x for x in g["segments"] if x["type"] == "pocket")
        far = int(C[np.flatnonzero(lab["segment"] == pocket["id"])[0], 0])   # a pocket node (outside the ring side)
        v["idx"] = np.r_[v["idx"], far].astype(np.int64)
        v["vec"] = np.r_[v["vec"], [[0.0, 0.0, 0.5]]]
        v["zone"] = np.union1d(zone, [far])                          # the zone "agrees" — the label check must not
        return out
    monkeypatch.setattr(beadgraph, "basis", leaky)
    with pytest.raises(EslError) as e:
        bs.basis(mesh, D, CFG)
    assert e.value.code == "BG_BASIS_LEAK"


# ---------------------------------------------------------------- 2. mixed graph + elems (High 2)
def test_mixed_graph_and_elems_selection():
    import synth_bead as sb
    g0 = sb.generate()
    sel1 = sb.selection(g0)
    mesh = g0["mesh"]
    d = tempfile.mkdtemp(prefix="bg_mx_")
    st = bgr.prep_graph(mesh, g0.get("fixed_ids", ()), CFG, d)
    assert st["ok"], st
    gr, lab = bgr.load_graph(d)
    eb = dict(sel1["beads"][1], src="elems", id="b2")
    found = None
    for s in gr["segments"]:
        if s["type"] == "base":
            continue
        sel = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(gr), "rules": 1},
               "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": s["anchor"]}]}, eb]}
        try:
            n2, _ = bs.normalize(sel, CFG, mesh=mesh, graph=gr, labels=lab)
        except EslError:
            continue
        found = n2
        break
    assert found is not None
    D = bgr.derive_obj_v2(mesh, found, CFG, gr, lab, fixed_node_ids=g0.get("fixed_ids", ()))
    B = bs.basis(mesh, D, CFG)
    chk = bs.design_checks(D, B)
    assert {o["var"] for o in chk["outside"]} >= {"B1_D", "B2_D1"}       # elems variables carry their support
    tab = {r["name"]: r for r in bs.params_table(D, CFG)}
    gv, ev = tab["B1_D"], tab["B2_D1"]
    x0 = mesh["x0"]
    vg = {gv["name"]: gv["default_range"][1]}
    ve = {ev["name"]: ev["default_range"][1]}
    both = {**vg, **ve}
    xg, xe, xb = bs.morph(x0, B, vg), bs.morph(x0, B, ve), bs.morph(x0, B, both)
    for vals, x in ((vg, xg), (ve, xe), (both, xb)):
        st = bs.design_state(mesh, x0, x, D.fixed_mask, CFG, checks=chk, values=vals)
        assert st["state"] == "READY" and st["code"] is None, (sorted(vals), st["code"], st["warnings"])
        assert not any(w["code"] == "BG_OUTSIDE_MOVED" for w in st["warnings"])
    assert np.abs(xb - (xg + xe - x0)).max() <= 1e-12                      # combined = sum of the two moves
    ug, ue = np.linalg.norm(xg - x0, axis=1), np.linalg.norm(xe - x0, axis=1)
    assert ug.max() > 0.5 and ue.max() > 0.5
    still = (ug == 0) & (ue == 0)
    assert np.all(np.linalg.norm(xb - x0, axis=1)[still] == 0.0)
    # a node outside both variables' sets moved -> still caught on the mixed design
    allowed = np.zeros(x0.shape[0], bool)
    for o in chk["outside"]:
        if o["var"] in both:
            allowed[o["zone"]] = True
    k = int(np.flatnonzero(~allowed)[0])
    xx = xb.copy()
    xx[k, 2] += 1e-3
    st = bs.design_state(mesh, x0, xx, D.fixed_mask, CFG, checks=chk, values=both)
    assert st["code"] == "BG_OUTSIDE_MOVED" and sorted(st["warnings"][0]["vars"]) == sorted(both)


# ---------------------------------------------------------------- 3. split coordinates (High 3)
def _plan_xy_frontend(graph, p):
    """frontend ``planXY`` (src/view3d/select/graph.ts) — same formula: (p·e1 − origin[0], p·e2 − origin[1]), 1e-3."""
    fr = graph["frame"]
    o = fr.get("origin", [0.0, 0.0])
    r = lambda v: round(v * 1000) / 1000  # noqa: E731 — Math.round(v·1000)/1000 for these magnitudes
    return [r(float(np.dot(p, fr["e1"])) - o[0]), r(float(np.dot(p, fr["e2"])) - o[1])]


def test_split_plane_matches_vitest_constants(h6):
    """the constants of the vitest (select_graph_bin.test.ts, 'frame.origin 포함') = the Core plane of node 44235 on
    the frozen H6 fixture (same frame), and the frontend formula reproduces it."""
    from beadgraph.testing import conformance as cf
    from beadgraph.zones import Mesh
    g, lab, _ = cf.classified("h6")
    fx = cf.load_fixture("h6")
    M = Mesh(g, lab, fx["x0"], fx["conn"])
    assert g["frame"]["origin"] == [599.748, 340.874]
    assert [round(float(v), 3) for v in M.P[44235]] == [-512.896, -269.696]
    assert _plan_xy_frontend(g, fx["x0"][44235]) == [-512.896, -269.696]


def test_split_round_trip(h6):
    """3D click on a channel element -> frontend plane coordinates -> selection edit split{anchor, at} -> core
    ``edited_graph``: the new split zone sits at the clicked point (<= one skeleton step + h). The old formula without
    frame.origin sends a point ~690 mm away -> BG_EDIT_INVALID (segment end) or a split far from the click."""
    mesh, g, lab, fixed, _d = h6
    ch = next(s for s in g["segments"] if s["type"] == "channel")
    sk = np.asarray(ch["skeleton"], float)
    mid = sk[len(sk) // 2]
    C = mesh["conn"]
    el = np.flatnonzero(lab["segment"] == ch["id"])
    cen = np.array([mesh["x0"][C[e][C[e] >= 0]].mean(axis=0) for e in el])
    fr = g["frame"]
    P = np.c_[cen @ fr["e1"], cen @ fr["e2"]] - fr["origin"]
    pick = int(np.argmin(np.hypot(*(P - mid).T)))
    click = cen[pick]
    at = _plan_xy_frontend(g, click)
    assert np.hypot(*(np.asarray(at) - P[pick])) < 2e-3
    sel = _sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]}]}])
    sel["graph"]["edits"] = {"split": [{"anchor": ch["anchor"], "at": at}]}
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    g2, l2 = bgr.edited_graph(g, lab, norm["graph"]["edits"], mesh)
    new_z = [z for z in g2["junction_zones"] if z["reason"] == "split"]
    assert len(new_z) == 1
    j = next(jj for jj in g2["junctions"] if jj["zone"] == new_z[0]["id"])
    step = float(np.median(np.hypot(*np.diff(sk, axis=0).T)))
    assert np.hypot(*(np.asarray(j["plan"]) - np.asarray(at))) <= step + fr["h_mm"]
    assert len([s for s in g2["segments"] if s["floor"] == ch["floor"]]) == \
        len([s for s in g["segments"] if s["floor"] == ch["floor"]]) + 1
    # old frontend formula (no origin)
    old = [round(float(np.dot(click, fr["e1"])), 3), round(float(np.dot(click, fr["e2"])), 3)]
    assert np.hypot(*(np.asarray(old) - np.asarray(at))) > 100.0
    sel_old = copy.deepcopy(sel)
    sel_old["graph"]["edits"] = {"split": [{"anchor": ch["anchor"], "at": old}]}
    try:
        n_old, _ = bs.normalize(sel_old, CFG, mesh=mesh, graph=g, labels=lab)
        g3, _l3 = bgr.edited_graph(g, lab, n_old["graph"]["edits"], mesh)
    except EslError as exc:
        assert exc.code == "BG_EDIT_INVALID"
    else:
        j3 = next(jj for jj in g3["junctions"] if jj["zone"] == [z for z in g3["junction_zones"]
                                                                  if z["reason"] == "split"][0]["id"])
        assert np.hypot(*(np.asarray(j3["plan"]) - np.asarray(at))) > 10.0 * fr["h_mm"]


# ---------------------------------------------------------------- 4. BG-X-1 first matrix (Med 4)
@pytest.mark.slow
def test_h6_first_matrix_has_no_inverting_w_design(h6, tmp_path):
    """BD_LOADS writes the W clamp table; derive (API and BD_MATRIX alike) applies it, so the params the API shows
    before any BD_MATRIX already carry the clamped default range and feasible (+ BG_RANGE_CLAMPED). The first matrix
    built from those default ranges (W variables, default method / n / seed) has no inverting design; without the
    table it has. Schema 1 untouched (no table, no key)."""
    from esl.doe import matrix as mx
    mesh, g, lab, fixed, d = h6
    wc = bgr.w_clamp_table(mesh, g, lab, fixed, CFG)
    assert wc["entries"] and wc["graph_sha256"] == bgr.graph_sha_of(g)
    p = os.path.join(str(tmp_path), bgr.W_CLAMP_JSON)
    bgr.write_w_clamp(p, wc)
    assert bgr.load_w_clamp(str(tmp_path)) is None                       # needs graph.json next to it
    with open(os.path.join(d, bgr.W_CLAMP_JSON), "wb") as fh:
        fh.write(json.dumps(wc, sort_keys=True, separators=(",", ":")).encode("ascii"))
    assert bgr.load_w_clamp(d) == wc
    sel, _sym, _aw = bgr.auto_seed(g, lab, CFG)
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    x0 = mesh["x0"]
    res = {}
    for use in (None, wc):
        api = bgr.derive_v2(mesh, norm, CFG, g, lab, fixed_scan=fixed, w_clamp=use)   # what the API returns
        D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed, w_clamp=use)
        tab = bs.params_table(D, CFG)
        assert [r for r in api["params"]] == tab                              # API params = BD_MATRIX params
        B = bs.basis(mesh, D, CFG)
        chk = bs.design_checks(D, B)
        spec = {"method": CFG["doe"]["default_method"], "seed": int(CFG["doe"]["seed"]),
                "n": int(CFG["doe"]["default_n"]),
                "params": [{"name": r["name"], "lo": r["default_range"][0], "hi": r["default_range"][1]}
                           for r in tab if r["type"] == "W" and r["use_default"]]}
        m = mx.generate(spec, tab, CFG)
        inv = 0
        for dsg in m["designs"]:
            if not dsg["values"]:
                continue
            st = bs.design_state(mesh, x0, bs.morph(x0, B, dsg["values"]), D.fixed_mask, CFG, checks=chk,
                                 values=dsg["values"])
            inv += st["code"] == "SELECT_MORPH_INVERTED"
        res[use is not None] = (inv, len(m["designs"]), D, tab, B)
    assert res[False][0] > 0                                                 # the finding: unclamped first matrix
    assert res[True][0] == 0, res[True][:2]
    D, tab, B = res[True][2], res[True][3], res[True][4]
    clamped = [w for b in D.beads for w in b.warnings if w["code"] == "BG_RANGE_CLAMPED"]
    assert clamped and all(w["level"] == "info" for w in clamped)
    rows = {r["name"]: r for r in tab}
    for w in clamped:
        r = rows[w["var"]]
        assert r["default_range"] == w["to"] and r["default_range"] != w["from"]
        lo, hi = r["feasible"]
        assert (not w["inverted"][0] or lo == r["default_range"][0]) and (not w["inverted"][1] or hi == r["default_range"][1])
    # BD_MATRIX range_check on the clamped ranges: no W end inverts any more (nothing left for clamp_w_ranges)
    rc = bs.range_check(mesh, D, B, CFG)
    assert not any(w.get("code") == "SELECT_RANGE_INVERTS" and w["var"].endswith("_W") for w in rc), rc
    # the basis ramp stays frozen at the original default range (BG-D-24): same vectors with and without the table
    B0 = res[False][4]
    for v in B.vars:
        v0 = next(x for x in B0.vars if x["name"] == v["name"])
        assert np.array_equal(v["idx"], v0["idx"]) and np.array_equal(v["vec"], v0["vec"])


def test_w_clamp_not_applied_when_it_does_not_match(h6):
    """stale graph sha / other select settings / toggle edit / fixed_user -> no derive-time clamp (BD_MATRIX still
    clamps)."""
    mesh, g, lab, fixed, _d = h6
    wc = {"schema": bgr.W_CLAMP_SCHEMA, "graph_sha256": bgr.graph_sha_of(g), "cfg_sha256": bgr._cfg_key(CFG),
          "hold": 1, "entries": []}
    ch = next(s for s in g["segments"] if s["type"] == "pocket" and s["entry_width"] is not None)
    norm, _ = bs.normalize(_sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]}]}]), CFG,
                           mesh=mesh, graph=g, labels=lab)
    D0 = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    frm = D0.beads[0].range_default["W"]
    Wn = D0.beads[0].W_nom
    wc["entries"] = [{"segs": [[ch["anchor"], ch["n_elems"]]], "from": frm, "usable": [frm[0], (Wn + frm[1]) / 2],
                      "inverted": [0, 7]}]
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed, w_clamp=wc)
    assert D.beads[0].range_default["W"][1] < frm[1] and D.beads[0].range_basis["W"] == frm
    for bad in ({"graph_sha256": "0" * 64}, {"cfg_sha256": "0" * 64}, {"hold": 0}):
        D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed, w_clamp={**wc, **bad})
        assert D.beads[0].range_default["W"] == frm, bad
    other = copy.deepcopy(CFG)
    other["select"]["range"]["width_rel"] = 0.25
    D = bgr.derive_obj_v2(mesh, norm, other, g, lab, fixed_node_ids=fixed, w_clamp=wc)
    assert not any(w["code"] == "BG_RANGE_CLAMPED" for w in D.beads[0].warnings)


# ---------------------------------------------------------------- v0.19.1 BG-D-47 (issue #63 B10_D·B11_D)
def test_step_straddling_boss_no_leak(monkeypatch):
    """a single-segment channel D bead whose end step (junction-zone walls) carries two straddling bosses: BD_MATRIX
    basis passes the label-based BG_BASIS_LEAK check (pre-fix node rule -> BG_BASIS_LEAK), designs at nominal ± 1 mm are
    READY and the step walls do not move."""
    import importlib
    mesh, g, lab, fixed, _d = prepared("stepboss")
    floors = {f["id"]: f for f in g["floors"]}
    ch = max((s for s in g["segments"] if s["type"] != "base"),
             key=lambda s: (float(floors[s["floor"]]["rel_height"]), -s["id"]))
    norm, _ = bs.normalize(_sel(g, [{"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]}]}]), CFG,
                           mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    B = bs.basis(mesh, D, CFG)
    chk = bs.design_checks(D, B)
    x0, C = mesh["x0"], mesh["conn"]
    jz, cls = np.asarray(lab["junction_zone"]), np.asarray(lab["cls"])
    zw = np.unique(C[(jz >= 0) & (cls == 1)])
    zw = zw[zw >= 0]
    row = next(r for r in bs.params_table(D, CFG) if r["name"] == "B1_D")
    for v in (row["nominal"] - 1.0, row["nominal"] + 1.0):
        vals = {"B1_D": float(v)}
        x = bs.morph(x0, B, vals)
        assert float(np.abs(x[zw] - x0[zw]).max()) == 0.0
        st = bs.design_state(mesh, x0, x, D.fixed_mask, CFG, checks=chk, values=vals)
        assert st["state"] == "READY", (v, st["code"], st["warnings"])
    mo = importlib.import_module("beadgraph.morph")
    monkeypatch.setattr(mo, "movable_nodes", lambda conn, allowed_el: np.ones(conn.n, bool))
    with pytest.raises(EslError) as e:
        bs.basis(mesh, D, CFG)
    assert e.value.code == "BG_BASIS_LEAK"
