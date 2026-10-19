"""strain.eps_eq, T-TS-1 (esl.md V-TS-1), first-reach t* (esl_core.md §7.1·§7.4)."""
import numpy as np
import pytest

from esl.errors import EslError
from esl.mech import strain, tstar


def test_eps_eq_formula():
    # 단축 비압축: exx=e, eyy=−e/2 → ε_eq = e
    e = 0.02
    assert strain.eps_eq(np.array([e, -e / 2, 0.0])) == pytest.approx(e)
    # 순수 전단 텐서 exy=g → (2/√3) g
    assert strain.eps_eq(np.array([0, 0, 0.01])) == pytest.approx(0.02 / np.sqrt(3))
    eps = np.random.default_rng(0).normal(size=(4, 5, 2, 3))
    v = strain.eps_eq(eps)
    xx, yy, xy = eps[..., 0], eps[..., 1], eps[..., 2]
    zz = -(xx + yy)
    ref = np.sqrt(2 / 3 * (xx ** 2 + yy ** 2 + zz ** 2 + 2 * xy ** 2))
    assert np.allclose(v, ref)
    assert np.allclose(strain.eps_eq_max_layer(eps), ref.max(-1))


def _synthetic():
    F, E = 12, 8
    time = np.linspace(0, 1.1, F)
    eps = np.full((F, E), 0.001)
    # 요소 위치: 일직선, 간격 10
    C = np.c_[np.arange(E) * 10.0, np.zeros(E), np.zeros(E)]
    m = np.array([1, 2, 5, 3, 2, 4, 4, 1, 6, 2, 3, 9], float) * 0.01   # 마지막 프레임이 전역 최대
    for f in range(F):
        eps[f, f % E] = m[f]
    # t*=frame 11 (elem 3). 그 프레임 hotspot 구성
    eps[11] = [0.05, 0.06, 0.02, 0.09, 0.085, 0.01, 0.07, 0.03]
    return time, eps, C, m


def test_tstar_scan():
    time, eps, C, m = _synthetic()
    r = tstar.scan(time, eps, C, top_n=3, top_k=3, min_dist=15.0)
    assert r["tstar"]["frame_pos"] == 11 and r["tstar"]["elem_pos"] == 3
    assert r["tstar"]["eps_eq"] == pytest.approx(0.09)
    # 국소 최대: f2(5), f5(4, plateau 5-6 첫 프레임), f8(6), f11(9) → 순위 11, 8, 2
    assert [c["frame_pos"] for c in r["candidates"]] == [11, 8, 2]
    assert [c["rank"] for c in r["candidates"]] == [1, 2, 3]
    # hotspot: 3(0.09) → 4(0.085, 거리 10 < 15 제외) → 6(0.07) → 1(0.06, 3과 거리 20 OK)
    assert [h["elem_pos"] for h in r["hotspots"]] == [3, 6, 1]
    assert np.allclose(r["history"]["eps_max"], eps.max(1))
    assert np.allclose(r["history"]["eps_hotspot1"], eps[:, 3])


def test_tstar_window_exclude_ties():
    time, eps, C, m = _synthetic()
    r = tstar.scan(time, eps, C, 5, 2, 0.0, time_window=(None, 0.85))
    assert r["tstar"]["frame_pos"] == 8
    assert [c["frame_pos"] for c in r["candidates"]] == [8, 2, 5]
    ex = np.zeros(8, bool)
    ex[3] = True
    r = tstar.scan(time, eps, C, 2, 2, 0.0, exclude_mask=ex)
    assert r["tstar"]["elem_pos"] == 4
    # 동률 → 이른 프레임
    e2 = np.zeros((4, 2))
    e2[1, 0] = e2[3, 1] = 1.0
    r = tstar.scan(np.arange(4.0), e2, np.zeros((2, 3)), 3, 1, 0.0)
    assert r["tstar"]["frame_pos"] == 1
    assert [c["frame_pos"] for c in r["candidates"]] == [1, 3]
    with pytest.raises(EslError):
        tstar.scan(time, eps, C, 1, 1, 0.0, time_window=(5.0, 6.0))


# ---------------------------------------------------------------- first-reach (§7)
def _hold(inst):
    return np.maximum.accumulate(np.asarray(inst, float), axis=0)


def test_first_reach_rtol_and_negative():
    v = _hold([[0.0, 1.0, -1.0], [0.5, 1.0, -1.0], [0.999999, 2.0, -1.0], [1.0, 2.0, -1.0]])
    assert tstar.first_reach(v, 1e-6).tolist() == [2, 2, 3]        # 0.999999 ≥ 1·(1−1e-6), 음수 최종값 → F−1
    assert tstar.first_reach(v, 0.0).tolist() == [3, 2, 0]          # rtol 0: 음수도 v ≥ v_final 이면 도달
    assert tstar.first_reach(v, 0.6).tolist() == [1, 0, 3]


def test_scan_reach_candidates_hotspots_history():
    # 요소 0: frame 2 에 최종 9 도달(1위), 요소 1: frame 4 에 최종 7, 요소 2: frame 2 에 5(중복 프레임),
    # 요소 3: frame 1 에 3, 요소 4: 상승 중(frame 2 에서 4 → 이후 6) — first-reach 는 5
    inst = np.array([[0, 0, 0, 0, 0],
                     [1, 1, 1, 3, 1],
                     [9, 2, 5, 1, 4],
                     [3, 6, 2, 2, 5],
                     [2, 7, 1, 1, 5.5],
                     [1, 1, 1, 1, 6]], float)
    v = _hold(inst)
    t = np.arange(6) * 0.1
    C = np.c_[np.arange(5) * 10.0, np.zeros(5), np.zeros(5)]
    r = tstar.scan_reach(t, v, C, top_n=3, top_k=5, min_dist=0.0, rtol=1e-6)
    assert r["tstar"]["frame_pos"] == 2 and r["tstar"]["elem_pos"] == 0 and r["tstar"]["value"] == 9
    assert [(c["frame_pos"], c["elem_pos"]) for c in r["candidates"]] == [(2, 0), (4, 1), (5, 4)]
    # frame 2 에서 상승 중: 0(9>1), 1(2>1), 2(5>1), 4(4>1); 3 은 3→3 정체 → 제외. 값 내림차순, rank1 = 요소 0
    assert [h["elem_pos"] for h in r["hotspots"]] == [0, 2, 4, 1]
    assert all(h["rising"] for h in r["hotspots"])
    assert np.allclose(r["history"]["m"], v.max(axis=1))
    # 거리 필터·top_k
    r = tstar.scan_reach(t, v, C, 3, 2, 15.0, 1e-6)
    assert [h["elem_pos"] for h in r["hotspots"]] == [0, 2]
    # 창: t ≤ 0.35 → 창의 마지막(frame 3) 값이 최종 → 요소 0 (frame 2), 요소 1 (frame 3)
    r = tstar.scan_reach(t, v, C, 3, 2, 0.0, 1e-6, time_window=(None, 0.35))
    assert [c["frame_pos"] for c in r["candidates"]] == [2, 3, 1]
    # 제외 → 다음 순위가 t*
    ex = np.array([True, False, False, False, False])
    r = tstar.scan_reach(t, v, C, 3, 2, 0.0, 1e-6, exclude_mask=ex)
    assert r["tstar"]["elem_pos"] == 1 and r["tstar"]["frame_pos"] == 4
    assert 0 not in [h["elem_pos"] for h in r["hotspots"]]
    with pytest.raises(EslError):
        tstar.scan_reach(t, np.zeros((6, 5)), C, 3, 2, 0.0, 1e-6)      # 양수 최종값 없음
    with pytest.raises(EslError):
        tstar.scan_reach(t, v, C, 3, 2, 0.0, 1e-6, time_window=(5.0, 6.0))


def test_rising_hotspots_frame0_and_first_forced():
    v = _hold([[0.0, 2.0, 1.0], [0.0, 2.0, 3.0]])
    C = np.zeros((3, 3))
    h = tstar.rising_hotspots(v, 0, C, 5, 0.0, 1e-6)
    assert [x["elem_pos"] for x in h] == [1, 2]                       # frame 0: v > 0
    h = tstar.rising_hotspots(v, 1, C, 5, 0.0, 1e-6, first=1)
    assert [x["elem_pos"] for x in h] == [1, 2] and h[0]["rising"] is False and h[1]["rising"] is True
