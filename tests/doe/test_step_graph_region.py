"""V-SG-4b 평가 영역(esl_step_graph.md SG-D-19·20): H6 시트 + 주 시트와 이어진 추가 형상(메시 수준, 노드 공유) →
auto = 주 시트, largest·all = 전체, frame·3-2-1 = 추가 형상 없는 판과 같음, 하중 영역 밖 0, 영역 밖 세그먼트 = seed 제외,
정보·경고, region 인자 없음 = 바이트 불변."""
import numpy as np
import pytest
import synth_doe as sd
import synth_step_graph as ssg

from esl.doe import bead_graph as bgr
from esl.doe import evaluate as ev
from esl.doe import opt_settings, settings
from esl.doe import scenario as sc
from esl.doe import step_graph as sg
from esl.opt import target as tg

CFG = settings({"bead_doe": {"enabled": True}})
H = 3.0
TIGHT = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"region": {"pad_mm": 0.5}}}}})


@pytest.fixture(scope="module")
def M():
    mesh, fx = ssg.h6_fixture_mesh()
    return mesh, fx, ssg.add_extra(mesh)


def test_modes(M):
    mesh, fx, big = M
    n0 = mesh["elem_type"].size
    r, info = sg.region_mask(big, mesh["x0"], TIGHT, H)                # (a) auto = 주 시트(추가 형상 0 %)
    assert info["rule"] == "a_bbox" and r[:n0].all() and not r[n0:].any()
    assert info["n_out"] == big["elem_type"].size - n0 and info["out_bbox"][3] > 1220.0
    for mode in ("largest", "all"):                                    # 이어져 있으므로 최대 성분 = 전체
        cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"region": {"mode": mode}}}}})
        r2, i2 = sg.region_mask(big, mesh["x0"], cfg, H)
        assert r2.all() and i2["n_out"] == 0
    r3, i3 = sg.region_mask(big, None, CFG, H)                         # A 정보 없음 → 최대 연결 성분
    assert i3["rule"] == "largest" and r3.all()
    w, inf = sg.region_messages(info, CFG)                              # (f)
    assert [x["code"] for x in inf] == ["STEP_GRAPH_REGION"] and not w
    small = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"region": {"min_frac": 0.9999}}}}})
    w2, _ = sg.region_messages(info, small)
    assert [x["code"] for x in w2] == ["STEP_GRAPH_REGION_SMALL"]


def test_template_and_loads(M):
    """(b) frame·L·3-2-1 = 추가 형상 없는 판 ± 1e-9, (c) 하중 영역 밖 노드 0, (g) region None = 기존 template 바이트."""
    mesh, fx, big = M
    n0, nn0 = mesh["elem_type"].size, mesh["x0"].shape[0]
    r, _ = sg.region_mask(big, mesh["x0"], TIGHT, H)
    size = opt_settings()["size"]
    e = ssg.LightEntry("E0", mesh)
    t0, _ = sc.template_base(mesh, [e], size, inch=55)
    t1, _ = sc.template_base(big, [e], size, inch=55, region=r)
    for k in ("origin", "e_xi", "e_eta", "n"):
        assert np.allclose(t0.frame[k], t1.frame[k], atol=1e-9), k
    for k in ("L_xi", "L_eta"):
        assert abs(t0.frame[k] - t1.frame[k]) < 1e-9
    assert t0.supports == t1.supports
    assert t1.n_elems == big["elem_type"].size                         # 해석 메시는 전체
    a0, m0 = tg.build_template(mesh, (e.meta["frame"] or {}).get("axis_ref"))     # (g) region 없음 = 이전 경로
    assert np.array_equal(a0["conn"], t0.mesh["conn"]) and m0["frame"] == t0.frame
    loads, info = sg.region_loads(t1, [e], r, None, None, None)
    F = loads[0][1]
    rn = sg.region_nodes(t1.mesh, r)
    assert F.shape[0] == big["x0"].shape[0] and np.abs(F[~rn]).max() == 0.0 and np.abs(F[rn]).max() > 0
    l0, _ = sg.region_loads(t0, [e], None, None, None, None)           # 영역 하중 = 추가 형상 없는 판의 하중
    assert np.allclose(F[:nn0], l0[0][1], atol=1e-9)


def test_graph_marks(M, tmp_path):
    """(d) 추가 형상 세그먼트 out_of_region → seed 제외, (e) 영역 안 세그먼트·접합 수 = 추가 형상 없는 분류."""
    mesh, fx, big = M
    n0 = mesh["elem_type"].size
    r, _ = sg.region_mask(big, mesh["x0"], TIGHT, H)
    F = np.asarray(fx["fixed"]) + 1
    d0, d1 = tmp_path / "g0", tmp_path / "g1"
    d0.mkdir()
    d1.mkdir()
    s0 = bgr.prep_graph(mesh, F, CFG, str(d0))
    s1 = bgr.prep_graph(big, F, CFG, str(d1))
    assert s0["ok"] and s1["ok"]
    g0, l0 = bgr.load_graph(str(d0))
    g1, l1 = bgr.load_graph(str(d1))
    mk = bgr.region_marks(g1, l1, r)
    seg_in = [s for s in g1["segments"] if s["id"] not in mk["segments"]]
    assert len(seg_in) == len(g0["segments"])
    assert len(g1["junction_zones"]) >= len(g0["junction_zones"])
    sel, _sym, _w = bgr.auto_seed(g1, l1, CFG, exclude_segs=mk["segments"])
    anchors = {s["anchor"] for b in sel["beads"] for s in b["segs"]}
    assert not any(a >= n0 for a in anchors)                          # 추가 형상 요소가 seed 에 없음
    out_ids = set(mk["segments"])
    assert all(s["id"] not in out_ids for s in g1["segments"] if s["anchor"] in anchors)
    sel0, _, _ = bgr.auto_seed(g1, l1, CFG)                            # 인자 없음 = 이전과 같음
    assert sel0 == bgr.auto_seed(g1, l1, CFG, exclude_segs=None)[0]


def test_evaluate_region():
    """(e) umax·epsmax = 영역만, C 같음; region None = 이전 결과 그대로."""
    m = sd.plate(nx=12, ny=8)
    sup = [(int(n), d) for n, d in __import__("synth_opt").supports_321(m)]
    F = np.zeros((m["x0"].shape[0], 3))
    F[:, 1] = 1.0
    F -= F.mean(axis=0)
    scfg = opt_settings()["solver"]
    scfg = dict(scfg, backend="superlu")
    r0 = ev.evaluate(m, sup, [("E", F)], scfg, reaction_warn=1.0)
    reg = np.zeros(m["elem_type"].size, bool)
    reg[: reg.size // 2] = True
    r1 = ev.evaluate(m, sup, [("E", F)], scfg, reaction_warn=1.0, region=reg)
    a, b = r0["per_esl"][0], r1["per_esl"][0]
    assert a["C"] == b["C"] and b["umax"] <= a["umax"] and b["epsmax"] <= a["epsmax"]
    rall = ev.evaluate(m, sup, [("E", F)], scfg, reaction_warn=1.0, region=np.ones(reg.size, bool))
    assert rall["per_esl"][0]["umax"] == a["umax"] and rall["per_esl"][0]["epsmax"] == a["epsmax"]
