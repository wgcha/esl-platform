"""V-OR-6: 비드 금지 영역 — 구멍 루프 검출(구멍 2개·결함 루프 무시), 반경·띠 경계, 사각형 4 기준 모서리, 잘림·이탈,
합집합·사유 우선순위, KEEPOUT_ALL, 평면도 자료 = 워커 마스크(같은 함수), 드래그 역변환, frame 변경 경고."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.library import normalize as nz
from esl.opt import keepout as ko
from esl.opt import settings
from esl.opt import target as tg

KC = settings()["keepout"]
H = 12.5                                                     # 격자 간격 (300/24, 200/16)


@pytest.fixture(scope="module")
def holed():
    # 구멍 2개(2×2 셀 = 둘레 100 mm), 결함 구멍 1개(1×1 셀 = 둘레 50 mm)
    m = so.plate(24, 16, holes=[(4, 6, 4, 6), (16, 18, 9, 11), (11, 12, 2, 3)])
    fr = nz.frame(m["x0"], None, m["conn"], m["elem_type"])
    return m, fr


def brute(m, seeds, r):
    X = m["x0"]
    d = np.min(np.linalg.norm(X[:, None, :] - X[None, seeds, :], axis=2), axis=1)
    near = d <= r + 1e-9
    c, et = m["conn"], m["elem_type"]
    return np.array([near[c[e, :et[e]]].any() for e in range(c.shape[0])])


def test_hole_loops_and_defect_ignored(holed):
    m, fr = holed
    loops = ko.boundary_loops(m, 60.0)                       # 50 mm 루프 = 결함
    assert len(loops["holes"]) == 2 and len(loops["ignored"]) == 1
    assert abs(loops["perimeters"]["outer"] - 1000.0) < 1e-6
    assert sorted(loops["perimeters"]["holes"]) == [100.0, 100.0]
    res = ko.compute(m, fr, {"auto": {"hole": True, "edge": False}}, {**KC, "hole_min_perimeter_mm": 60.0})
    assert res["warnings"] and res["counts"]["n_holes"] == 2


@pytest.mark.parametrize("r", [H, H - 1e-3])
def test_radius_and_band_boundary(holed, r):
    m, fr = holed
    kc = {**KC, "hole_radius_mm": r, "edge_band_mm": r, "hole_min_perimeter_mm": 60.0}
    loops = ko.boundary_loops(m, 60.0)
    res = ko.compute(m, fr, {"auto": {"hole": True, "edge": False}}, kc)
    want = brute(m, [n for lp in loops["holes"] for n in lp], r)
    assert np.array_equal(res["mask"], want)
    res_e = ko.compute(m, fr, {"auto": {"hole": False, "edge": True}}, kc)
    assert np.array_equal(res_e["mask"], brute(m, loops["outer"], r))
    # r = H 이면 이웃 노드 줄까지 포함(경계 포함), H−ε 이면 루프 노드만
    if r == H:
        assert res_e["counts"]["n_elems_auto_edge"] > ko.compute(m, fr, {"auto": {"hole": False, "edge": True}},
                                                                 {**kc, "edge_band_mm": H - 1e-3})["counts"]["n_elems_auto_edge"]


def test_rect_corners_and_clip(holed):
    m, fr = holed
    a0, a1 = fr["a_range"]
    b0, b1 = fr["b_range"]
    r = {"name": "PCB", "x_mm": 20.0, "y_mm": 30.0, "w_mm": 50.0, "h_mm": 40.0}
    exp = {"a0b0": ([a0 + 20, a0 + 70], [b0 + 30, b0 + 70]), "a1b0": ([a1 - 70, a1 - 20], [b0 + 30, b0 + 70]),
           "a0b1": ([a0 + 20, a0 + 70], [b1 - 70, b1 - 30]), "a1b1": ([a1 - 70, a1 - 20], [b1 - 70, b1 - 30])}
    for c, (ea, eb) in exp.items():
        bb = ko.rect_bounds({**r, "corner": c}, fr)
        assert np.allclose(bb["a"], ea) and np.allclose(bb["b"], eb) and not bb["clipped"]
        back = ko.rect_from_bounds(bb["a"][0], bb["b"][0], 50.0, 40.0, c, fr, "PCB")
        assert np.allclose([back["x_mm"], back["y_mm"]], [20.0, 30.0])           # 드래그 ↔ 숫자 동기화 식
        res = ko.compute(m, fr, {"rects": [{**r, "corner": c}], "auto": {"hole": False, "edge": False}}, KC)
        ab = ko.project_ab(fr, ko.centroids(m))
        inside = (ab[:, 0] >= ea[0]) & (ab[:, 0] <= ea[1]) & (ab[:, 1] >= eb[0]) & (ab[:, 1] <= eb[1])
        assert np.array_equal(res["mask"], inside) and inside.any()
    clip = ko.compute(m, fr, {"rects": [{**r, "corner": "a0b0", "x_mm": 280.0}], "auto": {"hole": False,
                                                                                         "edge": False}}, KC)
    assert clip["rects"][0]["clipped"] and any("잘라서" in w for w in clip["warnings"])
    with pytest.raises(EslError) as ei:
        ko.compute(m, fr, {"rects": [{**r, "corner": "a0b0", "x_mm": 400.0}]}, KC)
    assert ei.value.code == "KEEPOUT_INVALID"


@pytest.mark.parametrize("bad", [{"w_mm": 0}, {"x_mm": -1}, {"corner": "zz"}, {"h_mm": "x"}, {"name": "n" * 41}])
def test_rect_validation(bad):
    r = {"name": "R", "corner": "a0b0", "x_mm": 1.0, "y_mm": 1.0, "w_mm": 5.0, "h_mm": 5.0, **bad}
    with pytest.raises(EslError) as ei:
        ko.validate_rects([r], KC)
    assert ei.value.code == "KEEPOUT_INVALID"
    with pytest.raises(EslError):
        ko.validate_rects([{"corner": "a0b0", "x_mm": 0, "y_mm": 0, "w_mm": 1, "h_mm": 1}] * 21, KC)


def test_union_reasons_and_keepout_all(holed):
    m, fr = holed
    kc = {**KC, "hole_min_perimeter_mm": 60.0}
    rect = {"name": "A", "corner": "a0b0", "x_mm": 0.0, "y_mm": 0.0, "w_mm": 120.0, "h_mm": 120.0}
    full = ko.compute(m, fr, {"rects": [rect]}, kc)
    h = ko.compute(m, fr, {"auto": {"hole": True, "edge": False}}, kc)["mask"]
    e = ko.compute(m, fr, {"auto": {"hole": False, "edge": True}}, kc)["mask"]
    rr = ko.compute(m, fr, {"rects": [rect], "auto": {"hole": False, "edge": False}}, kc)["mask"]
    assert np.array_equal(full["mask"], h | e | rr)
    assert np.all(full["reason"][h] == ko.REASON_HOLE)
    assert np.all(full["reason"][e & ~h] == ko.REASON_EDGE)
    assert np.all(full["reason"][rr & ~h & ~e] == ko.REASON_RECT)
    c = full["counts"]
    assert c["n_elems_auto_hole"] + c["n_elems_auto_edge"] + c["n_elems_rects"] == c["n_keepout"] == int(full["mask"].sum())
    t = tg.Target("S2", m, fr, so.supports_321(m))
    des, info = tg.design_mask(t, [], full["mask"])
    assert info["n_design_elems"] == int((~full["mask"]).sum())
    big = {"name": "ALL", "corner": "a0b0", "x_mm": 0.0, "y_mm": 0.0, "w_mm": 400.0, "h_mm": 300.0}
    allm = ko.compute(m, fr, {"rects": [big]}, kc)["mask"]
    with pytest.raises(EslError) as ei:
        tg.design_mask(t, [], allm)
    assert ei.value.code == "KEEPOUT_ALL"
    with pytest.raises(EslError) as ei:
        tg.design_mask(t, [10], None)                        # 비설계 PID 로 전부
    assert ei.value.code == "KEEPOUT_ALL"


def test_plan_view_same_function_as_worker(holed):
    m, fr = holed
    pv = ko.plan_view(m, fr, KC, max_points=100)
    worker = ko.compute(m, fr, {"rects": [], "auto": {"hole": True, "edge": True}}, KC)
    assert pv["auto_keepout"]["counts"] == worker["counts"]
    assert pv["elems"]["decimated"] and len(pv["elems"]["points"]) <= 100 and pv["elems"]["n_total"] == m["conn"].shape[0]
    assert len(pv["holes"]) == 3 and len(pv["outline"]) == 24 * 2 + 16 * 2
    # 자동 영역 외곽 = 마스크 요소 영역의 경계(짝홀): 링 노드가 모두 마스크 요소의 노드
    rings = pv["auto_keepout"]["polygons"]
    assert rings
    ab = ko.project_ab(fr, m["x0"])
    used = np.unique(m["conn"][worker["mask"]][m["conn"][worker["mask"]] >= 0])
    pts = {(round(a, 3), round(b, 3)) for a, b in ab[used]}
    assert all((p[0], p[1]) in pts for r in rings for p in r)
    # v0.7.0 통합: 종류(구멍/가장자리) — polygons 와 같은 길이, 구멍 링이 먼저
    kinds = pv["auto_keepout"]["kinds"]
    assert len(kinds) == len(rings) and set(kinds) == {"hole", "edge"}
    assert kinds == sorted(kinds, key=lambda k: k != "hole")
    only_edge = ko.plan_view(m, fr, KC, max_points=100, keepout={"auto": {"hole": False, "edge": True}})
    assert set(only_edge["auto_keepout"]["kinds"]) == {"edge"}


def test_frame_shift_warning(holed):
    _, fr = holed
    assert ko.frame_shift_warning(None, fr, KC) is None
    assert ko.frame_shift_warning({"a_range": fr["a_range"], "b_range": fr["b_range"]}, fr, KC) is None
    moved = {"a_range": [fr["a_range"][0] + 1.0, fr["a_range"][1]], "b_range": fr["b_range"]}
    assert "경계" in ko.frame_shift_warning(moved, fr, KC)
