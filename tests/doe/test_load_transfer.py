"""v0.20.0 ④ 하중 전달 코어(계약 esl_load_transfer.md V-LT-1~7·12 코어 부분).

- V-LT-1 같은 메시 W = ①: 빠른 경로 하중 = direct_nodal 비트 동일, 일반 사영 경로 1e-9, 진단 상관·MAC·배율 = 1.
- V-LT-2 재메시(h 2.5·3.5)에서 W 가 셀보다 A 직접(①) 에 가까움 — 매끈한 잡음(smooth)·노드 단위 잡음(node, 이슈 #63 증상).
- V-LT-3 합력·합모멘트 보존(W·새 C·legacy C), 셀 일괄 풀이 = lstsq, V-LT-4 공정성·지지 이전, V-LT-5 먼 노드,
  V-LT-6 평가 영역, V-LT-7 진단 파일·함수(상관·MAC), V-LT-12 legacy 스냅샷 = 지금 경로(파일·키·열 없음).
파이프라인 시험은 gmsh 가 없으면 skip."""
import inspect
import json
import os
import re

import numpy as np
import pytest

import synth_compare as scmp
import synth_doe as sd
from esl.doe import DEFAULTS
from esl.doe import evaluate as ev
from esl.doe import load_transfer as ltm
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U
from esl.library import entry as en
from esl.library import mapping as mp
from esl.opt import target as tg

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
SC = {"backend": "superlu", "drill_factor": 1e-4}
LT = ltm.resolve({"schema": 1, "method": "work"})
LX, LZ, H0 = 240.0, 180.0, 3.0


def _entry(root, mesh, f, eid="E0"):
    return en.load(scmp.lt_save_entry(root, eid, mesh, f), raw=True)


def _solve(tgt, loads, region=None, keep=()):
    return ev.evaluate(tgt.mesh, list(tgt.supports), loads, SC, reaction_warn=1.0, keep_u=list(keep), region=region)


def _loads(tgt, e, variant=None, region=None, h=H0):
    return ltm.shape_loads(tgt, [e], LT, ltm.Ctx(region, h, 0.005, None), variant)


@pytest.fixture(scope="module")
def bead_a(tmp_path_factory):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=(80.0, 110.0, 5.0))
    out = {}
    for rg in ("smooth", "node"):
        f = scmp.lt_esl_case(A, rg)
        out[rg] = (f, _entry(tmp_path_factory.mktemp(rg), A, f))
    return A, out


# ---------------------------------------------------------------- 설정
def test_defaults_and_resolve():
    d = DEFAULTS["compare"]["load_transfer"]
    assert (d["method"], d["support"], d["region"]["mode"], d["diag"]["enabled"]) == ("work", "transfer", "auto", True)
    assert ltm.resolve(None) is None
    r = ltm.resolve({"schema": 1, "method": "work", "cell_size_mm": 5.0})
    assert r["cell_size_mm"] is None                                     # work 의 해석값 = null
    assert ltm.resolve({"method": "cell", "cell_size_mm": 3.0})["cell_size_mm"] == 3.0
    for bad in ({"method": "cell", "cell_size_mm": 2.0}, {"method": "cell", "cell_size_mm": 201.0}):
        with pytest.raises(EslError) as ei:
            ltm.resolve(bad)
        assert ei.value.code == "LOAD_TRANSFER_INVALID"
    with pytest.raises(EslError):
        ltm.resolve({"method": "nope"})
    assert ltm.variant_label("work", None) == "work" and ltm.variant_label("cell", None) == "cell:legacy"
    assert ltm.variant_label("cell", 3.0) == "cell:3"
    assert [ltm.variant_label(*v) for v in ltm.sweep_variants(LT)] == ["work", "cell:3", "cell:legacy", "cell:10", "cell:5"]
    off = ltm.resolve({"method": "cell", "diag": {"alt": False, "cell_sweep_mm": []}})
    assert ltm.alt_variant(off) is None and ltm.sweep_variants(off) == [("cell", None)]
    assert ltm.alt_variant(ltm.resolve({"method": "cell", "cell_size_mm": 5.0})) == ("work", None)
    assert set(ltm.hash_view(LT)) == {"method", "cell_size_mm", "work", "support", "support_tol_mm", "region"}


# ---------------------------------------------------------------- V-LT-1 같은 메시 W = ①
def test_same_mesh_fast_path_bit_identical(bead_a):
    A, cases = bead_a
    f, e = cases["smooth"]
    a = np.linalg.norm(f, axis=1)
    assert a.sum() / np.linalg.norm(f.sum(axis=0)) > 1e3                # 이웃 상쇄(자기평형) ESL
    tgt = sc.compare_target(A, e.meta["frame"])
    loads, info = _loads(tgt, e)
    fd, _ = tg.entry_load(tg.Target("S1", tgt.mesh, e.meta["frame"], []), e.raw)
    assert info["fast_path"] == "identity" and info["per_esl"][0]["fast_path"] == "identity"
    assert np.array_equal(loads[0][1], fd)                              # (a) 비트 동일
    # (b) 빠른 경로를 끈 일반 사영(노드 ID 만 바꿈): 1e-9
    B = dict(A)
    B["node_id"] = A["node_id"] + 10 ** 6
    tb = sc.compare_target(B, e.meta["frame"])
    lb, ib = _loads(tb, e)
    assert ib["fast_path"] is None
    assert float(np.abs(lb[0][1] - fd).max()) <= 1e-9 * float(a.max())
    r0, r1 = _solve(tgt, loads), _solve(tb, lb)
    for k in ("umax", "C"):
        assert abs(r1["per_esl"][0][k] / r0["per_esl"][0][k] - 1) <= 1e-9
    # (c) 진단 정의: 상관·MAC·배율 = 1
    rk = _solve(tgt, loads + [("E0|t", fd)], keep=("E0", "E0|t"))
    rows = ltm.diag_rows([{"variant": "work", "entry_id": "E0", "f": loads[0][1], "C": rk["per_esl"][0]["C"],
                           "umax": rk["per_esl"][0]["umax"], "u": rk["u"]["E0"]}],
                         {"E0": {"kind": "direct_nodal", "f": fd, "C": rk["per_esl"][1]["C"],
                                 "umax": rk["per_esl"][1]["umax"], "u": rk["u"]["E0|t"]}}, {"E0": "씬"})
    for k in ("load_corr", "mac", "umax_ratio", "C_ratio", "sum_abs_ratio", "max_abs_ratio"):
        assert rows[0][k] == pytest.approx(1.0, abs=1e-9), k


# ---------------------------------------------------------------- V-LT-2 재메시
def _remesh_ratios(A, f, e):
    supA = ltm.auto_supports(A, None)
    ta = sc.compare_target(A, e.meta["frame"], supports=supA)
    ra = _solve(ta, [("E0", f)], keep=("E0",))
    ua, Ca = ra["per_esl"][0]["umax"], ra["per_esl"][0]["C"]
    out = {}
    ident = {}
    for v in (("work", None), ("cell", None), ("cell", 3.0)):
        lv, _ = _loads(ta, e, v)
        r = _solve(ta, lv, keep=("E0",))
        ident[ltm.variant_label(*v)] = {"umax": r["per_esl"][0]["umax"] / ua, "C": r["per_esl"][0]["C"] / Ca,
                                        "mac": ltm.mac(r["u"]["E0"], ra["u"]["E0"]),
                                        "corr": ltm.load_corr(lv[0][1], f)}
    for h in (2.5, 3.5):
        T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=h, bead=(80.0, 110.0, 5.0), node_base=500001)
        sup, si = ltm.transfer_supports(ltm.support_xyz(A, supA), T, None, 2 * h)
        assert si["mode"] == "transfer"
        tgt = sc.compare_target(T, e.meta["frame"], supports=sup)
        for v in (("work", None), ("cell", None), ("cell", 3.0)):
            lv, iv = _loads(tgt, e, v, h=h)
            assert iv["per_esl"][0]["dF_rel"] <= 1e-10
            r = _solve(tgt, lv)
            out[(h, ltm.variant_label(*v))] = (r["per_esl"][0]["umax"] / ua, r["per_esl"][0]["C"] / Ca)
    return ident, out


def test_remesh_work_closer_than_cell_smooth(bead_a):
    A, cases = bead_a
    ident, out = _remesh_ratios(A, *cases["smooth"])
    assert ident["work"]["mac"] == pytest.approx(1.0, abs=1e-9) and ident["work"]["corr"] == pytest.approx(1.0, abs=1e-12)
    assert ident["cell:legacy"]["mac"] < ident["work"]["mac"] and ident["cell:legacy"]["corr"] < 0.5
    for h in (2.5, 3.5):
        uw, cw = out[(h, "work")]
        ul, cl = out[(h, "cell:legacy")]
        u3, c3 = out[(h, "cell:3")]
        assert 0.7 <= uw <= 1.3 and 0.7 <= cw <= 1.3, (h, uw, cw)
        assert abs(np.log(cw)) < abs(np.log(cl)), (h, cw, cl)               # C: W 가 legacy 보다 ① 에 가까움
        assert abs(np.log(c3)) <= abs(np.log(cl)) + 1e-12                    # 셀 3 mm 는 W 와 legacy 사이(또는 W 쪽)


def test_remesh_node_noise_issue63(bead_a):
    """노드 단위 잡음(#63 증상): legacy 셀은 d000(= A) 에서도 umax 수 배·상관 낮음, W 는 d000 에서 ① 과 같고 재메시에서도
    legacy 보다 umax·C 가 ① 에 훨씬 가깝다(재메시 W 의 umax 는 노드 단위 잡음을 옮길 수 없어 [0.7, 1.3] 밖일 수 있음 — 진단에 드러남)."""
    A, cases = bead_a
    ident, out = _remesh_ratios(A, *cases["node"])
    assert ident["work"]["umax"] == pytest.approx(1.0, abs=1e-9) and ident["work"]["mac"] == pytest.approx(1.0, abs=1e-9)
    assert ident["cell:legacy"]["umax"] > 3 and ident["cell:legacy"]["C"] > 2
    assert ident["cell:legacy"]["corr"] < 0.5 and ident["cell:legacy"]["mac"] < 0.9
    for h in (2.5, 3.5):
        uw, cw = out[(h, "work")]
        ul, cl = out[(h, "cell:legacy")]
        assert ul > 3
        assert abs(np.log(uw)) < abs(np.log(ul)), (h, uw, ul)
        assert cw < 1.0 < cl, (h, cw, cl)       # 노드 단위 잡음 에너지: W 는 옮기지 못해 작게, legacy 는 크게(진단 C 배율에 드러남)


# ---------------------------------------------------------------- V-LT-3 보존
def test_conservation_work_and_cells(tmp_path, monkeypatch):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None)
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=2.5, bead=None, offset=(1.0, 0.5, 0.0), node_base=900001)
    tgt = sc.compare_target(T, e.meta["frame"])
    b = ltm.balance(A["x0"], f)
    W = ltm.build_work(A["x0"], tgt.mesh, None, LT["work"], H0)
    f0 = ltm.apply_work(W, f, T["x0"].shape[0])
    assert np.linalg.norm(f0.sum(axis=0) - f.sum(axis=0)) <= 1e-12 * b["sabs"]        # 분할 1 → 합력 보존(보정 전)
    xh = A["x0"].copy()                                                              # 해석 최근접점: 면 y = 0.5, x ≥ 1
    xh[:, 0] = np.maximum(xh[:, 0], 1.0)
    xh[:, 1] = 0.5
    dM = np.linalg.norm(np.cross(xh - A["x0"], f).sum(axis=0)) / (b["sabs"] * b["Lb"])
    lw, iw = _loads(tgt, e)
    p = iw["per_esl"][0]
    assert p["dM_rel_before"] == pytest.approx(dM, rel=1e-9)
    assert p["dF_rel"] <= 1e-10 and p["dM_rel"] <= 1e-10 and p["far_frac"] == 0.0
    for s in (10.0, 3.0):
        fc, ci = ltm.cell_loads(e.raw, e.meta["frame"], tgt.mesh, tgt.frame, np.arange(T["x0"].shape[0]), s,
                                lambda: W)
        assert np.linalg.norm(fc.sum(axis=0) - f.sum(axis=0)) <= 1e-9 * b["sabs"]
        if s == 3.0:
            assert ci["n_cells_small"] > 0 and ci["small_frac"] > 0
        monkeypatch.setattr(ltm, "BATCH_MIN_CELLS", 1)                          # 일괄 6×6 = lstsq(1e-10)
        fb, bi = ltm.cell_loads(e.raw, e.meta["frame"], tgt.mesh, tgt.frame, np.arange(T["x0"].shape[0]), s,
                                lambda: W)
        monkeypatch.setattr(ltm, "BATCH_MIN_CELLS", 10000)
        assert bi["batched"] and bi["n_cells_small"] == ci["n_cells_small"]
        assert float(np.abs(fb - fc).max()) <= 1e-10 * float(np.abs(fc).max())
        lc, ic = _loads(tgt, e, ("cell", s))
        q = ic["per_esl"][0]
        assert q["dF_rel"] <= 1e-10 and q["dM_rel"] <= 1e-10
    # legacy C = 지금 to_target(셀 24×14 병합·합 0 보정) 비트 동일
    ll, _ = _loads(tgt, e, ("cell", None))
    fl, _ = tg.entry_load(tgt, None, e.summary_for_mapping(), None)
    assert np.array_equal(ll[0][1], fl)


# ---------------------------------------------------------------- V-LT-4 공정성·지지
def test_fairness_same_rule_and_support_transfer(tmp_path):
    src = inspect.getsource(stg)
    calls = re.findall(r"ltm\.shape_loads\(([^)]*)\)", src)
    assert calls and all("did" not in c and "BASELINE" not in c for c in calls)     # (b) d000 만 다른 규칙 없음
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=(80.0, 110.0, 5.0))
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    fr = e.meta["frame"]
    t0 = sc.compare_target(A, fr, region=None)
    t1 = sc.compare_target(dict(A), fr, supports=t0.supports)
    l0, _ = _loads(t0, e)
    l1, _ = _loads(t1, e)
    r0, r1 = _solve(t0, l0), _solve(t1, l1)
    assert r1["per_esl"][0]["C"] / r0["per_esl"][0]["C"] == 1.0                       # (a) 같은 메시 = score 1
    # (d) 0.4 mm 평행 이동 → 이전 노드 = 최근접, C 는 지지와 무관(자기평형)
    S = scmp.lt_plate_mesh(Lx=LX + 6.0, Lz=LZ, h=H0, bead=(80.0, 110.0, 5.0), offset=(0.4, 0.0, 0.0), node_base=700001)
    ref = ltm.support_xyz(t0.mesh, t0.supports)
    sup, si = ltm.transfer_supports(ref, S, None, 2 * H0)
    assert si["mode"] == "transfer" and si["max_dist_mm"] == pytest.approx(0.4, abs=1e-9)
    ta = sc.compare_target(S, fr)                                                   # auto(형상마다 PCA)
    tt = sc.compare_target(S, fr, supports=sup)
    la, _ = _loads(ta, e)
    ra, rt = _solve(ta, la), _solve(tt, la)
    assert abs(rt["per_esl"][0]["C"] / ra["per_esl"][0]["C"] - 1) <= 1e-9
    _, sf = ltm.transfer_supports(ref, S, None, 0.1)
    assert sf["mode"] == "fallback" and "distance" in sf["reason"]


# ---------------------------------------------------------------- V-LT-5 먼 노드
def test_far_nodes_boss_and_thresholds(tmp_path):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None, boss=(150.0, 90.0, 18.0, 9.0))
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None, node_base=800001)
    tgt = sc.compare_target(T, e.meta["frame"])
    lw, iw = _loads(tgt, e)
    p = iw["per_esl"][0]
    assert iw["transfer"]["far_n"] > 0 and iw["transfer"]["max_dist_mm"] > 3.0 and p["far_frac"] > 0
    assert np.linalg.norm(lw[0][1].sum(axis=0) - f.sum(axis=0)) <= 1e-9 * p["sum_abs_f"]   # 버리지 않음(합력 보존)
    wc = LT["work"]
    for ff, want in ((0.0099, None), (0.0101, "LT_FAR_NODES"), (0.199, "LT_FAR_NODES"), (0.201, "LT_TRANSFER_FAILED")):
        assert ltm.far_state({"per_esl": [{"far_frac": ff}]}, wc)[0] == want, ff


# ---------------------------------------------------------------- V-LT-6 평가 영역
def _with_wall(m, h=H0, height=24.0):
    """주 시트(z = LZ 가장자리)에 이어진 세로 벽(y 0..height) — 주 시트 밖 추가 형상."""
    X = m["x0"]
    edge = np.flatnonzero(np.isclose(X[:, 2], LZ))
    edge = edge[np.argsort(X[edge, 0])]
    ny = round(height / h)
    rows = [edge]
    newx = []
    base = X.shape[0]
    for k in range(1, ny + 1):
        p = X[edge].copy()
        p[:, 1] = k * h
        rows.append(base + np.arange(edge.size))
        base += edge.size
        newx.append(p)
    conn = [m["conn"]]
    for k in range(ny):
        a, b = rows[k], rows[k + 1]
        conn.append(np.stack([a[:-1], a[1:], b[1:], b[:-1]], axis=1))
    C = np.concatenate(conn)
    ne = C.shape[0]
    x0 = np.concatenate([X] + newx)
    out = {"node_id": 1 + np.arange(x0.shape[0], dtype=np.int64), "x0": x0, "elem_id": 1 + np.arange(ne, dtype=np.int64),
           "elem_type": np.concatenate([m["elem_type"], np.full(ne - m["conn"].shape[0], 4, np.int8)]), "conn": C}
    for k in ("elem_pid", "elem_mid", "thickness", "E", "nu"):
        out[k] = np.full(ne, m[k][0])
    return out, m["conn"].shape[0]


def test_region_main_sheet(tmp_path):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None)
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    M, ne_main = _with_wall(scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None))
    rc = {**LT["region"], "pad_mm": 1.0}                                            # 벽 첫 줄 중심 y 1.5 > pad
    reg, info = ltm.region_of(M, A["x0"], rc, H0)
    assert reg is not None and int(reg.sum()) == ne_main and info["n_out"] == M["conn"].shape[0] - ne_main
    w, inf = ltm.region_messages(info, rc)
    assert [x["code"] for x in inf] == ["COMPARE_REGION"] and not w
    fr = e.meta["frame"]
    ck = sc.shape_check(M, fr, [e], stg.opt_settings()["size"], DEFAULTS["compare"], inch=75, region=reg)
    c0 = sc.shape_check(A, fr, [e], stg.opt_settings()["size"], DEFAULTS["compare"], inch=75)
    assert ck["size"]["L_xi"] == pytest.approx(c0["size"]["L_xi"], rel=1e-9)
    assert ck["size"]["L_eta"] == pytest.approx(c0["size"]["L_eta"], rel=1e-9)
    tgt = sc.compare_target(M, fr, region=reg)
    rn = ltm.region_nodes(M, reg)
    pos = {int(v): i for i, v in enumerate(M["node_id"].tolist())}
    assert all(rn[pos[n]] for n, _ in tgt.supports)
    for v in (("work", None), ("cell", 10.0), ("cell", None)):
        lv, _ = _loads(tgt, e, v, region=reg)
        assert float(np.abs(lv[0][1][~rn]).max()) == 0.0, v                           # 영역 밖 하중 0
    r = _solve(tgt, lv, region=reg, keep=("E0",))
    assert r["per_esl"][0]["umax"] == pytest.approx(float(np.linalg.norm(r["u"]["E0"][rn], axis=1).max()))
    ra, ia = ltm.region_of(M, A["x0"], {**LT["region"], "mode": "all"}, H0)
    assert ra is None and ia["n_out"] == 0


# ---------------------------------------------------------------- V-LT-7 진단 함수
def test_diag_functions():
    a = np.array([[1.0, 0, 0], [0, 2.0, 0]])
    assert ltm.load_corr(a, 2 * a) == pytest.approx(1.0) and ltm.load_corr(a, -a) == pytest.approx(-1.0)
    assert ltm.load_corr(a, np.zeros_like(a)) is None
    b = np.array([[0.0, 1, 0], [1.0, 0, 0]])
    assert ltm.mac(a, b) == pytest.approx(0.0) and ltm.mac(a, 3 * a) == pytest.approx(1.0)
    rows = ltm.diag_rows([{"variant": "cell:3", "entry_id": "E0", "f": a, "C": 2.0, "umax": 3.0, "u": None}],
                         {"E0": {"kind": "a_direct", "f": None, "C": 1.0, "umax": 1.5, "sum_abs_f": 1.5, "max_abs_f": 2.0}},
                         {})
    assert rows[0]["load_corr"] is None and rows[0]["mac"] is None and rows[0]["C_ratio"] == 2.0
    assert rows[0]["umax_ratio"] == 2.0 and rows[0]["sum_abs_ratio"] == 2.0 and rows[0]["max_abs_ratio"] == 1.0
    s = ltm.summary(rows + [dict(rows[0], C_ratio=4.0)], ["work", "cell:3"])
    assert s == [{"variant": "cell:3", "umax_ratio": [2.0, 2.0], "C_ratio": [2.0, 4.0], "mac_min": None,
                  "load_corr_min": None}]


# ---------------------------------------------------------------- 파이프라인 (V-LT-1c·4c·5·7·8 코어·12)
def _study(root, ref="case", lt=None, n_shapes=3):
    A = scmp.lt_plate_mesh(Lx=200.0, Lz=150.0, h=5.0, bead=None, n_tria_cols=2,
                           props={"t": 2.0, "E": 205000.0, "nu": 0.3})
    ents = []
    for k, (b, loc) in enumerate(((1.0, 0.3), (0.3, 1.0))):
        f = scmp.lt_esl_forces(A, scmp.lt_u_drop(A, bend=b, local=loc, sigma=8.0, at=(0.3 + 0.3 * k, 0.5)))
        ents.append({"id": f"E{k}", "dir": scmp.lt_save_entry(os.path.join(root, "lib"), f"E{k}", A, f),
                     "label": f"씬 {k}"})
    os.makedirs(os.path.join(root, "case"), exist_ok=True)
    rad = os.path.join(root, "case", "model_0000.rad")
    sd.write_mesh_rad(rad, A)
    paths = [scmp.plate_step(os.path.join(root, "up", f"u{k}", f"p{k}.step"), k, Lx=200.0, Lz=150.0, depth=5.0)
             for k in range(n_shapes)]
    cfg = {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 5.0}}},
           "opt_run": {"solver": {"backend": "superlu"}}}
    if ref == "case":
        shapes = [{"id": f"d{k:03d}", "name": f"s{k}", "file_name": os.path.basename(p), "path": p, "reference": False}
                  for k, p in enumerate(paths) if k > 0]
        extra = {"base": {"entry_id": "E0", "case_id": "c1", "rad_path": rad, "part_title": sd.PART_TITLE,
                          "case_dir": os.path.dirname(rad)}}
    else:
        shapes = [{"id": f"d{k:03d}", "name": f"s{k}", "file_name": os.path.basename(p), "path": p, "reference": k == 0,
                   "sha256": U.sha256_file(p)} for k, p in enumerate(paths)]
        extra = {}
    doe = {"id": "R1", "scenario": "compare", "title": "lt", "cfg": cfg, "entries": ents, "shapes": shapes,
           "reference_source": ref, "inch": 75, "props": {"t": 2.0, "E": 205000.0, "nu": 0.3}, **extra}
    if lt is not None:
        doe["load_transfer"] = lt
    out = os.path.join(root, "run")

    def spec(stage, **kw):
        return {"stage": stage, "out": out, "doe": {**doe, **kw}}
    for s in ("bd_input", "bd_mesh0", "bd_loads"):
        stg.run_stage(spec(s), lambda m: None)
    cmp_ = U.read_json(os.path.join(out, "prep", "compare.json"))
    for x in cmp_["shapes"]:
        if x["status"] == "READY":
            stg.run_stage(spec("bd_eval", design=x["id"]), lambda m: None)
    post = stg.run_stage(spec("bd_post"), lambda m: None)
    return out, post, spec, A, ents


@needs_gmsh
def test_pipeline_case_reference_work(tmp_path, monkeypatch):
    out, post, spec, A, ents = _study(str(tmp_path), "case", {"schema": 1, "method": "work"})
    P = lambda *a: os.path.join(out, *a)   # noqa: E731
    prep = U.read_json(P("prep", "load_transfer.json"))
    rows = {r["id"]: r for r in prep["shapes"]}
    assert rows["d000"]["fast_path"] == "identity" and rows["d000"]["supports"]["mode"] == "auto"
    assert isinstance(prep["warnings"], list) and all(isinstance(r["warnings"], list) for r in prep["shapes"])
    # (V-LT-1a) prep/loads.npz = ① direct_nodal 비트 동일
    nid, loads = sc.load_loads(P("prep"))
    t, _ = sc.load_base(P("prep"))
    for (eid, F), ent in zip(loads, ents):
        e = en.load(ent["dir"], raw=True)
        fd, _ = tg.entry_load(tg.Target("S1", t.mesh, t.frame, []), e.raw)
        assert np.array_equal(F, fd)
    # (V-LT-5) 비드 깊이 5 mm > proj_tol 3 mm 위 하중 비 > 0.2 → FAILED_SIZE LT_TRANSFER_FAILED, 아니면 경고·지지 이전
    cmp_ = {r["id"]: r for r in U.read_json(P("prep", "compare.json"))["shapes"]}
    assert cmp_["d001"]["status"] == "FAILED_SIZE" and cmp_["d001"]["code"] == "LT_TRANSFER_FAILED"
    assert cmp_["d002"]["status"] == "READY" and "LT_FAR_NODES" in cmp_["d002"]["warnings"]
    assert rows["d002"]["supports"]["mode"] == "transfer" and rows["d002"]["supports"]["max_dist_mm"] == 0.0
    assert os.path.isfile(P("prep", "shapes", "d002", "transfer.npz"))
    assert not os.path.isfile(P("prep", "shapes", "d000", "transfer.npz"))           # 빠른 경로 = W 없음
    # (V-LT-1c·7) d000 진단: work 행 상관·MAC·배율 = 1, 셀 훑기 variant 전부
    d0 = U.read_json(P("run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "direct_nodal" and d0["d000"]["identity"] is True
    vs = {(r["variant"], r["entry_id"]): r for r in d0["d000"]["rows"]}
    assert {v for v, _ in vs} == {"work", "cell:3", "cell:legacy", "cell:10", "cell:5"}
    for eid in ("E0", "E1"):
        for k in ("load_corr", "mac", "umax_ratio", "C_ratio"):
            assert vs[("work", eid)][k] == pytest.approx(1.0, abs=1e-9)
    res = post["result"]
    lt = res["load_transfer"]
    assert (lt["method"], lt["cell_size_mm"], lt["support"], lt["region_mode"]) == ("work", None, "transfer", "auto")
    assert lt["alt"] == {"method": "cell", "cell_size_mm": 3.0} and lt["truth"] == "direct_nodal"
    assert lt["summary"][0]["variant"] == "work" and lt["summary"][0]["mac_min"] == pytest.approx(1.0, abs=1e-9)
    assert res["view3d"] == ["d000"] + [x["id"] for x in res["ranking"]][:len(res["view3d"]) - 1]   # 목록 불변
    assert set(res["view3d_esl"]) == set(res["view3d"])
    for eid, name in res["view3d_ref"].items():                                     # LT-9 d000_e<kk>
        assert re.fullmatch(r"d000_e\d\d", name) and name not in res["view3d"]
        man = json.load(open(P("post", "view3d", name, "manifest.json"), encoding="utf-8"))
        assert man["esl_run_id"] == eid
    diag = U.read_json(P("post", "load_transfer_diag.json"))
    assert diag["schema"] == ltm.DIAG_SCHEMA and diag["reference"]["identity"] is True
    ds = {x["id"]: x for x in diag["shapes"]}
    assert ds["d002"]["score_alt"] > 0 and ds["d000"]["score_alt"] == pytest.approx(1.0)
    head = open(P("post", "ranking.csv"), encoding="utf-8").readline().strip().split(",")
    assert head[-4:] == ltm_cols()
    rows_csv = [ln.split(",") for ln in open(P("post", "ranking.csv"), encoding="utf-8").read().splitlines()[1:]]
    assert {r[0]: r[-4] for r in rows_csv}["d002"] == "work"
    assert "하중 전달" in open(P("report.html"), encoding="utf-8").read()
    # (V-LT-7) 진단 단계 예외 → LT_DIAG_SKIPPED, 주 결과(per_esl) 불변
    before = U.read_json(P("run", "designs", "d002", "result.json"))["per_esl"]
    os.remove(P("run", "designs", "d002", "done.json"))
    real = ltm.shape_loads

    def boom(target, entries, lt_, ctx, variant=None):
        if variant is not None:
            raise EslError("MAPPING_DEGENERATE", "시험")
        return real(target, entries, lt_, ctx, variant)
    monkeypatch.setattr(ltm, "shape_loads", boom)
    stg.run_stage(spec("bd_eval", design="d002"), lambda m: None)
    after = U.read_json(P("run", "designs", "d002", "result.json"))["per_esl"]
    assert [(p["entry_id"], p["C"], p["umax"]) for p in after] == [(p["entry_id"], p["C"], p["umax"]) for p in before]
    dd = U.read_json(P("run", "designs", "d002", "load_transfer.json"))
    assert any(str(w).startswith("LT_DIAG_SKIPPED") for w in dd["warnings"]) and "alt" not in dd["per_esl"][0]


def ltm_cols():
    return ["lt_method", "lt_far_frac", "lt_dM_rel", "score_alt"]


@needs_gmsh
def test_pipeline_step_reference_cell_no_alt(tmp_path):
    lt = {"schema": 1, "method": "cell", "cell_size_mm": 10.0, "work": {"far_fail_frac": 1.0},
          "diag": {"alt": False, "cell_sweep_mm": []}}
    out, post, spec, A, ents = _study(str(tmp_path), "step", lt, n_shapes=2)
    d0 = U.read_json(os.path.join(out, "run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "a_direct" and d0["d000"]["identity"] is False
    assert [r["variant"] for r in d0["d000"]["rows"]] == ["cell:10", "cell:10"]
    assert all(r["load_corr"] is None and r["mac"] is None and r["C_ratio"] > 0 for r in d0["d000"]["rows"])
    res = post["result"]
    assert res["load_transfer"]["alt"] is None and res["load_transfer"]["rank_alt_same"] is None
    diag = U.read_json(os.path.join(out, "post", "load_transfer_diag.json"))
    assert all("score_alt" not in x for x in diag["shapes"])
    rows = [ln.split(",") for ln in open(os.path.join(out, "post", "ranking.csv"), encoding="utf-8").read().splitlines()]
    assert rows[0][-4:] == ltm_cols() and {r[0]: r[-4] for r in rows[1:]}["d001"] == "cell:10"
    assert {r[0]: r[-1] for r in rows[1:]}["d001"] == ""


@needs_gmsh
def test_pipeline_legacy_snapshot_unchanged(tmp_path):
    """V-LT-12: 스냅샷에 load_transfer 없음 = 지금 경로(새 파일·키·CSV 열 없음, 하중 = 셀 매핑)."""
    out, post, spec, A, ents = _study(str(tmp_path), "case", None, n_shapes=2)
    assert not os.path.exists(os.path.join(out, "prep", "load_transfer.json"))
    assert not os.path.exists(os.path.join(out, "post", "load_transfer_diag.json"))
    assert not os.path.exists(os.path.join(out, "run", "designs", "d000", "load_transfer.json"))
    res = post["result"]
    assert "load_transfer" not in res and "view3d_ref" not in res and "view3d_esl" not in res
    head = open(os.path.join(out, "post", "ranking.csv"), encoding="utf-8").readline().strip().split(",")
    assert head[-1] == "elem_ratio_ref"
    assert U.read_json(os.path.join(out, "prep", "compare.json"))["loads"]["method"] == "cell_mapping"
    assert "하중 전달" not in open(os.path.join(out, "report.html"), encoding="utf-8").read()


def test_min_norm_batch_matches_mapping():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(40, 3)) * [10, 10, 1]
    F, M, ref = rng.normal(size=3), rng.normal(size=3), np.array([0.5, -0.2, 0.1])
    f1, _ = mp.min_norm_forces(X, F, M, ref)
    f2, ok = ltm._batch_min_norm(X, np.arange(40), np.zeros(40, np.int64), [0], F[None], M[None], ref[None], 0.0)
    assert ok[0] and float(np.abs(f2 - f1).max()) <= 1e-10 * float(np.abs(f1).max())
