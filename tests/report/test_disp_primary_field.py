"""변위 주지표 판정의 순수 함수(esl.report.field, 계약 esl_disp_primary.md §3.4·§3.5·§14·§15).

V-DP-7(strain_reference) · V-DP-8(disp_analysis) · V-DP-16(ceil2·robust_range) · V-DP-21(section_stats)
· V-DP-22(section_line·normalized_point).
"""
import numpy as np
import pytest

from esl.report import field as F


# ---------------------------------------------------------------- V-DP-16 ceil2·robust_range
def test_ceil2_two_significant_digits_up():
    assert F.ceil2(263.4) == 270.0
    assert F.ceil2(0.01234) == 0.013
    assert F.ceil2(270.0) == 270.0                       # 이미 2자리면 그대로(부동소수 잡음에 올리지 않음)
    assert F.ceil2(1.0) == 1.0 and F.ceil2(99.5) == 100.0 and F.ceil2(1e-9) == 1e-9
    assert F.ceil2(0.1 + 0.2) == 0.3 and F.ceil2(0.3001) == 0.31      # 부동소수 잡음(1e-12 상대)은 올리지 않음
    for bad in (0.0, -1.0, float("nan"), float("inf"), None, "x"):
        assert F.ceil2(bad) is None


def test_robust_range_sym_zero_minmax_formulas():
    rng = np.random.default_rng(0)
    base = rng.uniform(-10, 10, 1000)
    v = np.concatenate([base, [5000.0, -4000.0, 3000.0, 9000.0, -7000.0]])      # 이상치 5/1005 = 0.5 % < 1 %
    a = np.abs(v)
    p99 = float(np.percentile(a, 99))
    s = F.robust_range(v, "sym")
    assert s["basis"] == "p99" and s["raw"] == pytest.approx(p99)
    assert s["max"] == F.ceil2(p99) == -s["min"] and s["max"] < 20.0 < float(a.max()) / 100      # R ≪ max
    z = F.robust_range(np.abs(v), "zero")
    assert z["min"] == 0.0 and z["max"] == F.ceil2(float(np.percentile(np.abs(v), 99)))
    w = v + 100.0
    m = F.robust_range(w, "minmax")
    assert m["min"] == float(w.min()) and m["max"] == F.ceil2(float(np.percentile(w, 99))) and m["raw"] == pytest.approx(
        float(np.percentile(w, 99)))
    # 비유한은 걸러냄
    assert F.robust_range(np.r_[v, np.nan, np.inf], "sym")["max"] == s["max"]


def test_robust_range_empty_and_nonfinite_are_null():
    for kind in ("sym", "zero", "minmax"):
        for x in ([], [np.nan, np.inf], [0.0, 0.0]):
            r = F.robust_range(np.asarray(x, float), kind)
            assert r["min"] is None and r["max"] is None and r["basis"] == "p99"
    assert F.robust_range([], "sym")["raw"] is None
    with pytest.raises(Exception):
        F.robust_range([1.0], "bad")


# ---------------------------------------------------------------- V-DP-7 strain_reference
def test_strain_reference_counts_and_denominators():
    E = 10
    rel = np.array([0.01, 0.2, -0.3, 0.05, np.nan, 0.5, -0.02, 0.11, 0.0, 0.4])
    valid = np.array([1, 1, 1, 1, 0, 0, 1, 1, 1, 1], bool)          # 5 번째 NaN, 6 번째 (초과지만) valid 아님
    epsp = np.array([0, 0.1, 0, 0, 0.2, 0.3, 0, 1e-12, 0, np.nan])
    out = F.strain_reference(rel, valid, epsp, E, 10.0)
    ex = out["exceed"]
    assert ex.tolist() == [False, True, True, False, False, False, False, True, False, True]
    ref = out["ref"]
    assert ref["n_exceed"] == 4 and ref["n_valid"] == 8 and ref["n_elems"] == E
    assert ref["frac_exceed"] == pytest.approx(4 / 10) and ref["frac_exceed_valid"] == pytest.approx(4 / 8)
    a = 100 * np.abs(rel[valid])
    assert ref["p99_err_pct"] == pytest.approx(float(np.percentile(a, 99)))
    # 소성: 엄격 부등호(epsp > 0), NaN 은 아님
    assert out["plastic"].tolist() == [False, True, False, False, True, True, False, True, False, False]
    assert ref["plastic"] == {"n_plastic": 4, "frac_plastic": pytest.approx(0.4), "n_exceed_plastic": 2}
    # epsp 없음 → plastic null
    none = F.strain_reference(rel, valid, None, E, 10.0)
    assert none["plastic"] is None and none["ref"]["plastic"] is None and none["ref"]["n_exceed"] == 4
    # valid 없음
    nv = F.strain_reference(rel, np.zeros(E, bool), None, E, 10.0)
    assert nv["ref"]["n_exceed"] == 0 and nv["ref"]["p99_err_pct"] is None and nv["ref"]["frac_exceed_valid"] is None


def test_summarize_has_p99():
    E = 300
    er = np.linspace(1.0, 2.0, E)
    rel = np.where(np.arange(E) % 100 == 0, 0.9, 0.01)
    valid, reason, mx, imax = F.classify(er, np.ones(E, bool), 0.1)
    s = F.summarize(np.arange(E), er, er * (1 + rel), rel, valid, reason, np.ones(E, bool), imax, 5, 10)
    assert s["abs_err_pct"]["p99"] == pytest.approx(float(np.percentile(np.abs(100 * rel[valid]), 99)))


# ---------------------------------------------------------------- V-DP-8 disp_analysis
def _plate(nx=7, ny=5, Lx=60.0, Ly=20.0):
    xs, ys = np.meshgrid(np.linspace(0, Lx, nx), np.linspace(0, Ly, ny), indexing="ij")
    return np.column_stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)])


def test_disp_analysis_summary_hist_top_arrays():
    x0 = _plate()
    N = len(x0)
    nid = np.arange(1000, 1000 + N)
    rng = np.random.default_rng(1)
    d_rel = rng.normal(size=(N, 3))
    delta = np.zeros((N, 3))
    delta[:, 2] = 10.0 ** rng.uniform(-8, -3, N)
    delta[[3, 11]] = 0.0                                            # r = 0 노드 2개
    delta[5, 2] = 2e-2                                              # 최대
    delta[20, 2] = 1e-2
    d_val = d_rel + delta
    sup = np.zeros(N, bool)
    sup[[5, 0, 34]] = True
    U = 7.5
    out = F.disp_analysis(nid, x0, d_rel, d_val, U, sup, top_n=4, hist_bins=10)
    s, a = out["summary"], out["arrays"]
    e = np.linalg.norm(delta, axis=1)
    r = e / U
    assert s["U"] == U and s["n_nodes"] == N and s["n_support"] == 3
    assert s["rms_rel"] == pytest.approx(np.sqrt(np.mean(e ** 2)) / U, rel=1e-12)
    assert s["max_rel"] == pytest.approx(r.max(), rel=1e-12) and s["max_node_id"] == int(nid[5])
    for k, q in (("p50", 50), ("p90", 90), ("p99", 99)):
        assert s[k] == pytest.approx(np.percentile(r, q)) and s["max"] == pytest.approx(r.max())
    # 히스토그램: log10 균등 bin, 범위 [floor(log10 min r>0), ceil(log10 max r)], r=0 은 n_zero
    h = s["hist"]
    pos = r[r > 0]
    assert h["n_zero"] == 2 and h["n"] == N and len(h["edges_log10"]) == 11 and len(h["counts"]) == 10
    assert h["edges_log10"][0] == np.floor(np.log10(pos.min())) and h["edges_log10"][-1] == np.ceil(np.log10(pos.max()))
    assert sum(h["counts"]) == pos.size
    # 상위 노드: r 내림차순(동률 node_id 오름차순), 지지 표시
    top = s["top"]
    assert [t["node_id"] for t in top][:2] == [int(nid[5]), int(nid[20])] and len(top) == 4
    assert [t["r"] for t in top] == sorted((t["r"] for t in top), reverse=True)
    assert top[0]["is_support"] is True and top[1]["is_support"] is False
    assert top[0]["e"] == pytest.approx(2e-2) and top[0]["u_rel_mag"] == pytest.approx(np.linalg.norm(d_rel[5]))
    assert {x["node_id"] for x in s["support"]} == {int(nid[i]) for i in (5, 0, 34)}
    # 2D 좌표 = PCA 평면(e1 = 길이 방향 = x)
    assert abs(a["plane_e1"][0]) == pytest.approx(1.0) and abs(a["plane_e2"][1]) == pytest.approx(1.0)
    assert np.ptp(a["ab"][:, 0]) == pytest.approx(60.0) and np.ptp(a["ab"][:, 1]) == pytest.approx(20.0)
    # npz 배열 키·dtype
    assert a["node_id"].dtype == np.int64 and a["ab"].shape == (N, 2) and a["d_rel"].shape == (N, 3)
    assert a["e"].dtype == np.float64 and a["is_support"].dtype == bool and float(a["U"]) == U
    assert np.allclose(a["e"], e)


def test_disp_analysis_all_zero_difference():
    x0 = _plate(3, 3)
    d = np.random.default_rng(2).normal(size=(9, 3))
    s = F.disp_analysis(np.arange(9), x0, d, d, 1.0, np.zeros(9, bool), 3, 5)["summary"]
    assert s["rms_rel"] == 0.0 and s["max_rel"] == 0.0 and s["hist"]["n_zero"] == 9 and s["hist"]["counts"] == []


# ---------------------------------------------------------------- V-DP-21 section_stats
def test_section_stats_values():
    s = np.linspace(0, 10, 6)
    w_rel = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0]) * 1e-3
    dw_true = np.array([1e-6, -3e-6, 2e-6, 8e-6, -9e-6, 0.0])
    w_val = w_rel + dw_true
    U = 0.5
    r = F.section_stats(s, w_rel, w_val, U)
    assert np.allclose(r["dw"], dw_true, atol=1e-18)
    st = r["stats"]
    assert st["dw_max_abs"] == pytest.approx(9e-6) and st["s_at_dw_max"] == 8.0
    assert st["dw_rms"] == pytest.approx(np.sqrt(np.mean(dw_true ** 2)))
    assert st["U"] == U and st["dw_max_rel"] == pytest.approx(9e-6 / U) and st["dw_rms_rel"] == pytest.approx(st["dw_rms"] / U)
    assert st["w_max_abs"] == pytest.approx(max(abs(w_rel).max(), abs(w_val).max()))
    # 전체 해 없음 → dw 빈 배열, dw 관련 null, w_max_abs 만 값
    nv = F.section_stats(s, w_rel, None, None)
    assert nv["dw"] == [] and nv["stats"]["w_max_abs"] == pytest.approx(5e-3)
    assert all(nv["stats"][k] is None for k in ("dw_max_abs", "s_at_dw_max", "dw_rms", "U", "dw_max_rel", "dw_rms_rel"))
    # 빈 단면 → 전부 null
    em = F.section_stats(np.zeros(0), np.zeros(0), np.zeros(0), 1.0)
    assert em["dw"] == [] and all(v is None for v in em["stats"].values())
    # U 가 0/None 이면 *_rel null
    z = F.section_stats(s, w_rel, w_val, 0.0)["stats"]
    assert z["dw_max_rel"] is None and z["dw_max_abs"] == pytest.approx(9e-6)


# ---------------------------------------------------------------- V-DP-22 section_line·normalized_point
def _rotated_plate():
    P = _plate(9, 5, 300.0, 100.0)
    ang = np.deg2rad(37.0)
    c, s = np.cos(ang), np.sin(ang)
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    t = np.deg2rad(20.0)
    Rx = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
    return (P - P.mean(0)) @ (Rx @ Rz).T + np.array([500.0, -200.0, 80.0])


def test_section_line_and_normalized_point_on_rotated_plate():
    x0 = _rotated_plate()
    pl = F.plane_coords(x0, x0)
    xr, er = pl["xi_range"], pl["eta_range"]
    assert (xr[1] - xr[0]) == pytest.approx(300.0) and (er[1] - er[0]) == pytest.approx(100.0)   # 길이 > 폭 (회전과 무관)
    # 길이 방향 단면(axis=eta): η 고정, ξ 는 파트 범위 양 끝
    ln = F.section_line(pl, xr, er, "eta", 0.25, 0.02)
    assert (ln["a0"], ln["a1"]) == (xr[0], xr[1]) and ln["b0"] == ln["b1"] == pytest.approx(er[0] + 0.25 * 100.0)
    assert ln["band_abs"] == pytest.approx(0.02 * 100.0)
    # 폭 방향 단면(axis=xi): ξ 고정, η 는 양 끝
    lx = F.section_line(pl, xr, er, "xi", 0.8, 0.03)
    assert (lx["b0"], lx["b1"]) == (er[0], er[1]) and lx["a0"] == lx["a1"] == pytest.approx(xr[0] + 0.8 * 300.0)
    assert lx["band_abs"] == pytest.approx(0.03 * 300.0)
    # 선 끝점의 실좌표 → 3D 복원 시 파트 노드 범위 양 끝(회전판에서도)
    P = pl["origin"] + ln["a0"] * pl["e1"] + ln["b0"] * pl["e2"]
    Q = pl["origin"] + ln["a1"] * pl["e1"] + ln["b1"] * pl["e2"]
    assert np.linalg.norm(Q - P) == pytest.approx(300.0)
    # 정규화 왕복·자름
    for u, v in ((0.0, 0.0), (0.3, 0.9), (1.0, 1.0), (0.5, 0.12)):
        ab = (xr[0] + u * (xr[1] - xr[0]), er[0] + v * (er[1] - er[0]))
        assert F.normalized_point(ab, xr, er) == pytest.approx((u, v))
    assert F.normalized_point((xr[0] - 50.0, er[1] + 50.0), xr, er) == (0.0, 1.0)
    assert F.normalized_point((1.0, 1.0), (2.0, 2.0), (3.0, 3.0)) == (0.0, 0.0)           # 퇴화 범위
    # section 의 정규화와 같은 규약
    c2 = np.column_stack([pl["xi"], pl["eta"]])
    nx = F.normalize(c2[:, 0], xr)
    assert nx.min() == pytest.approx(0.0) and nx.max() == pytest.approx(1.0)
    with pytest.raises(Exception):
        F.section_line(pl, xr, er, "z", 0.5, 0.02)
