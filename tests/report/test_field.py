"""전 요소 재현 정확도 비교 순수 함수(esl.report.field, 계약 esl_p2_library.md §7.1·§7.2)."""
import numpy as np
import pytest

from esl.report import field as F


def test_rising_mask_rule():
    v = np.array([1.0, 1.0, 2.0, 0.0, np.nan, 1.0 + 5e-7])
    prev = np.array([0.5, 1.0, 1.0, 0.0, 0.1, 1.0])
    r = F.rising_mask(v, prev, rtol=1e-6)
    # 상승 = v > prev·(1+rtol): 같음(hold)·rtol 이내 증가는 상승 아님, NaN 은 False
    assert r.tolist() == [True, False, True, False, False, False]
    assert F.rising_mask(v, prev, rtol=0.0).tolist() == [True, False, True, False, False, True]
    # t* = 첫 프레임: v > 0
    assert F.rising_mask(v, None).tolist() == [True, True, True, False, False, True]
    with pytest.raises(Exception):
        F.rising_mask(v, prev[:2])


def test_classify_reasons_and_max():
    er = np.array([10.0, 5.0, 0.5, 8.0, 12.0, 9.0, 0.0])
    rising = np.array([True, True, True, False, True, True, True])
    ex = np.array([False, False, False, False, True, False, False])
    known = np.array([True, True, True, True, True, False, True])
    valid, reason, mx, imax = F.classify(er, rising, 0.1, exclude=ex, known=known)
    assert mx == 10.0 and imax == 0                          # 제외(12)·NO_PREV(9)·hold(8)는 최대 후보 아님
    assert [F.REASONS[int(c)] for c in reason] == ["OK", "OK", "LOW", "HOLD", "EXCLUDED", "NO_PREV", "LOW"]
    assert valid.tolist() == [True, True, False, False, False, False, False]
    v2, r2, m2, i2 = F.classify(er, np.zeros(7, bool), 0.1)
    assert m2 is None and i2 is None and not v2.any() and np.all(r2 == F.R_HOLD)


def test_summarize_errors_quantiles_hist():
    E = 200
    er = np.linspace(1.0, 2.0, E)
    rel_true = np.where(np.arange(E) % 10 == 0, 0.15, 0.02)        # 10% 요소 15%, 나머지 2%
    ee = er * (1 + rel_true)
    rising = np.ones(E, bool)
    valid, reason, mx, imax = F.classify(er, rising, 0.1)
    rel = F.rel_error(ee, er)
    s = F.summarize(np.arange(E) + 100, er, ee, rel, valid, reason, rising, imax, top_n=5, hist_bins=20)
    assert s["max"]["elem_id"] == 100 + E - 1 and s["max"]["err_pct"] == pytest.approx(2.0)
    assert s["max"]["eps_esl_max_elem_id"] == 100 + E - 1 - 9          # 마지막 15% 요소(190)가 ESL 최대
    a = s["abs_err_pct"]
    assert a["p50"] == pytest.approx(2.0) and a["max"] == pytest.approx(15.0)
    assert a["p90"] == pytest.approx(np.percentile(np.abs(100 * rel), 90))
    assert s["frac_within"] == {"5": pytest.approx(0.9), "10": pytest.approx(0.9), "20": 1.0}
    assert [r["elem_id"] for r in s["top"]] == [299, 298, 297, 296, 295]
    assert s["worst"][0]["err_pct"] == pytest.approx(15.0)
    h = s["hist"]
    assert len(h["counts"]) == 20 and sum(h["counts"]) == E and h["range_pct"] == 20.0
    assert F.rel_error([1.0], [0.0])[0] != F.rel_error([1.0], [0.0])[0]       # ε_rad=0 → NaN


def test_downsample_grid_and_priority():
    rng = np.random.default_rng(0)
    n = 5000
    x = rng.uniform(0, 300, n)
    y = rng.uniform(0, 100, n)
    er = rng.uniform(0, 1, n)
    valid = rng.uniform(size=n) > 0.3
    idx, cell = F.downsample(x, y, er, valid, 10_000)
    assert cell is None and idx.size == n
    idx, cell = F.downsample(x, y, er, valid, 500)
    assert idx.size <= 500 and cell[0] == pytest.approx(cell[1], rel=0.2)     # 종횡비 유지 정사각 셀
    assert np.all(np.diff(idx) > 0)
    # 전역 최대 ε_rad 인 valid 요소는 반드시 대표로 남음
    top = int(np.flatnonzero(valid)[np.argmax(er[valid])])
    assert top in set(idx.tolist())


def test_section_binning_and_band():
    xi_n = np.array([0.49, 0.5, 0.51, 0.9, 0.5])
    along = np.array([3.0, 1.0, 2.0, 0.0, 1.0])
    s = F.section(xi_n, along, np.zeros(5), along * 10, along * 11, 0.5, 0.02)
    assert s["n_elems"] == 4 and np.all(np.diff(s["s"]) > 0)
    assert np.allclose(s["w_rel"], s["s"] * 10) and np.allclose(s["w_val"], s["s"] * 11)
    assert F.section(xi_n, along, xi_n, xi_n, xi_n, 0.2, 0.01)["n_elems"] == 0
    bx, by = F.section_band(0.02, np.full(10, 10.0), [0, 100], [0, 1000])
    assert bx == pytest.approx(0.075) and by == 0.02


def test_plane_coords_axes():
    X = np.array([[0, 0, 5.0], [300, 0, 5], [300, 100, 5], [0, 100, 5], [150, 50, 5]])
    C = np.array([[150.0, 50.0, 5.0], [300.0, 50.0, 5.0]])
    pl = F.plane_coords(X, C)
    assert abs(pl["e1"] @ [1, 0, 0]) == pytest.approx(1.0) and abs(pl["n"] @ [0, 0, 1]) == pytest.approx(1.0)
    assert pl["xi_range"][1] - pl["xi_range"][0] == pytest.approx(300.0)
    assert abs(pl["xi"][1] - pl["xi"][0]) == pytest.approx(150.0) and np.allclose(pl["n0"], 0.0, atol=1e-9)
