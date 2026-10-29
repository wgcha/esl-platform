"""누적 씬 변형률 규칙 (계약 esl_cumulative_input.md §6, V-CI-S1·S2·S3)."""
import numpy as np
import pytest

from esl import cumulative as cu
from esl.errors import EslError
from esl.mech import tstar

DET = {"prev_floor": 1e-6, "min_elems": 10, "rel_tol": 0.05, "mono_frac": 0.99}


def _prev(n=50, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(0.01, 0.1, n)


# ------------------------------------------------------------------ V-CI-S1 진단
def test_s1_cumulative_incremental_ambiguous_trivial_and_forced():
    p = _prev()
    inc = np.linspace(0, 0.02, p.size)
    d = cu.diagnose(p, p.copy(), p + inc, DET)                 # frame0 = prev, 최종 ≥ prev
    assert d["mode"] == d["detected"] == "cumulative" and d["r0"] == pytest.approx(1.0) and d["mono"] == 1.0
    d = cu.diagnose(p, np.zeros_like(p), inc, DET)             # frame0 = 0
    assert d["mode"] == d["detected"] == "incremental" and d["r0"] == 0.0
    d = cu.diagnose(p, 0.5 * p, p + inc, DET)                  # r0 = 0.5
    assert d["detected"] == "ambiguous" and d["mode"] == "incremental" and d["ambiguous"]
    d = cu.diagnose(np.zeros(50), np.zeros(50), inc, DET)      # 이전 소성 없음
    assert d["mode"] == "trivial" and d["n_S"] == 0
    d = cu.diagnose(p, np.zeros_like(p), inc, DET, forced="cumulative")
    assert d["mode"] == "cumulative" and d["detected"] == "incremental" and d["forced"]
    # frame0 값 없는 요소(NaN)는 S 에서 제외 → S 부족 = trivial
    h0 = np.full(p.size, np.nan)
    h0[:5] = p[:5]
    assert cu.diagnose(p, h0, p + inc, DET)["mode"] == "trivial"
    # 단조성 부족(최종 < 이전): cumulative 아님
    d = cu.diagnose(p, p.copy(), 0.5 * p, DET)
    assert d["detected"] == "ambiguous"


def test_s1_series():
    raw = np.array([[0.0, 0.1], [0.2, 0.3]])
    prev = np.array([0.05, 0.1])
    c, i = cu.series(raw, prev, "incremental")
    assert np.allclose(c, raw + prev) and np.allclose(i, raw)
    c, i = cu.series(raw, prev, "cumulative")
    assert np.allclose(c, raw) and np.allclose(i, raw - prev)
    c, i = cu.series(raw, prev, "trivial")
    assert c is raw or np.array_equal(c, raw)
    with pytest.raises(EslError):
        cu.series(raw, prev, "x")


# ------------------------------------------------------------------ V-CI-S2 auto 집계
@pytest.mark.parametrize("pick", ["mid_mean", "max"])
def test_s2_auto_aggregation_picks_best_match(pick):
    rng = np.random.default_rng(1)
    n = 40
    mid = rng.uniform(0.01, 0.05, n)
    aggs = {"mid_mean": mid, "mid_max": mid * 1.1, "max": mid * 1.5, "mean": mid * 0.8}
    h0 = aggs[pick].copy()
    a, d = cu.choose(aggs, h0, h0 + 0.01, DET, "auto")
    assert a == pick and d["mode"] == "cumulative"
    # 누적 판정 안 되면 mid_mean
    a, d = cu.choose(aggs, np.zeros(n), np.full(n, 0.01), DET, "auto")
    assert a == "mid_mean" and d["mode"] == "incremental"
    a, _ = cu.choose(aggs, h0, h0, DET, "mean")
    assert a == "mean"


# ------------------------------------------------------------------ V-CI-S3 t* (누적 순위 · 증분 first-reach)
def test_s3_big_prev_small_increment_uses_increment_first_reach():
    F = 8
    t = np.arange(F) * 1e-3
    # 요소 0: 이전 0.5, 증분 작게 frame 2 에서 최종 도달. 요소 1: 이전 0, 증분 크게 frame 6.
    # 요소 2: 이전 0.6, 이번 증가 0 (제외). 요소 3: 이전 0, 증분 frame 4.
    inc = np.zeros((F, 4))
    inc[2:, 0] = 0.01
    inc[:, 1] = np.minimum(np.arange(F) * 0.05, 0.3)
    inc[4:, 3] = 0.2
    prev = np.array([0.5, 0.0, 0.6, 0.0])
    cum, _ = cu.series(inc, prev, "incremental")
    C = np.c_[np.arange(4) * 100.0, np.zeros(4), np.zeros(4)]
    r = tstar.scan_reach_cum(t, cum, inc, C, 5, 10, 1.0, 1e-6, min_increment=1e-5)
    assert r["tstar"]["elem_pos"] == 0 and r["tstar"]["frame_pos"] == 2
    assert r["tstar"]["value"] == pytest.approx(0.51) and r["tstar"]["value_inc"] == pytest.approx(0.01)
    assert r["tstar"]["value_prev"] == pytest.approx(0.5)
    assert r["n_excluded_no_increment"] == 1
    assert [c["frame_pos"] for c in r["candidates"]] == [2, 6, 4]
    assert all(h["elem_pos"] != 2 for h in r["hotspots"])
    assert np.allclose(r["history"]["m_inc"], inc[:, [0, 1, 3]].max(axis=1))
    # 같은 cum 에 rtol 을 걸면(비누적 규칙) 큰 prev 가 증분을 가려 first-reach 가 앞당겨짐 → 다른 결과
    r0 = tstar.scan_reach(t, cum, C, 5, 10, 1.0, 0.05)
    assert r0["tstar"]["frame_pos"] != 2 or r0["tstar"]["elem_pos"] != 0


def test_s3_no_increment_anywhere_raises():
    F = 3
    inc = np.zeros((F, 2))
    cum = inc + np.array([0.1, 0.2])
    with pytest.raises(EslError):
        tstar.scan_reach_cum(np.arange(F) * 1.0, cum, inc, np.zeros((2, 3)), 3, 3, 0.0, 1e-6)
