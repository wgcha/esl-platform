"""하중 전달 공용 모듈 단위 시험 — 모드 개념 없음(계약 esl_load_transfer.md V-LT-13, V-LT-1·2·3·5 모듈 부분).

esl.doe 시나리오·stages·계획 모듈을 import 하지 않는다(해석 확인용 ``evaluate`` 만). 합성 = 판 + 비드, ESL f_A = K_A u.
- V-LT-13 (a) 모듈 import 경계(AST), (b) 전략 등록, (c) identity 키·비트 동일, (d) 배치 global·rigid·frame.
- V-LT-1 같은 메시 work = identity(비트 동일)·일반 사영 경로 1e-9·진단 1, V-LT-2 재메시 W vs 셀(smooth·node 잡음),
  V-LT-3 합력·합모멘트 보존·셀 일괄 = lstsq·legacy 셀 비트 동일, V-LT-5 먼 노드, 진단 함수."""
import ast
import inspect

import numpy as np
import pytest
import synth_compare as scmp

from esl.doe import evaluate as ev
from esl.doe import load_transfer as ltm
from esl.errors import EslError
from esl.library import entry as en
from esl.library import mapping as mp
from esl.library import normalize as nz
from esl.opt import target as tg

SC = {"backend": "superlu", "drill_factor": 1e-4}
WORK = {"knn": 8, "proj_tol_mm": 3.0, "newton_iter": 10, "far_warn_frac": 0.01, "far_fail_frac": 0.2}
LX, LZ, H0 = 240.0, 180.0, 3.0
BEAD = (80.0, 110.0, 5.0)


def _entry(root, mesh, f, eid="E0"):
    return en.load(scmp.lt_save_entry(root, eid, mesh, f), raw=True)


def _src(e):
    return ltm.src_load(e.meta["entry_id"], e.raw, e.raw["f"], e.meta["frame"], e.summary_for_mapping())


def _method(name="work", s=None):
    return {"name": name, "cell_size_mm": s, "work": WORK, "mapping_opts": None, "cell_min_mm": 3.0}


def _go(mesh, e, name="work", s=None, mask=None, h=H0, key="topo+coords", placement=None, cache=None):
    dst = ltm.dst_mesh(mesh, e.meta["frame"], mask, h)
    plan = {"identity": {"key": key, "coord_tol_rel": 0.005}, "placement": placement}
    return ltm.run_transfer_plan(plan, [_src(e)], dst, _method(name, s), {} if cache is None else cache)


def _solve(mesh, sup, loads, keep=(), region=None):
    return ev.evaluate(mesh, list(sup), loads, SC, reaction_warn=1.0, keep_u=list(keep), region=region)


@pytest.fixture(scope="module")
def bead_a(tmp_path_factory):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=BEAD)
    out = {}
    for rg in ("smooth", "node"):
        f = scmp.lt_esl_case(A, rg)
        out[rg] = (f, _entry(tmp_path_factory.mktemp(rg), A, f))
    return A, out


# ---------------------------------------------------------------- V-LT-13 모듈 경계·전략·identity·배치
def test_module_imports_only_allowed():
    tree = ast.parse(inspect.getsource(ltm))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert not [m for m in mods if m.startswith("esl.doe")], mods                   # 시나리오·stages·DEFAULTS 금지
    assert mods <= {"__future__", "hashlib", "time", "numpy", "scipy.spatial", "esl.errors", "esl.library",
                    "esl.opt", "esl.opt.target"}, mods
    src = inspect.getsource(ltm)
    assert "open(" not in src and "zipfile" not in src and "os." not in src         # 파일 IO 없음
    assert set(ltm.STRATEGIES) >= {"identity", "work", "cell"}


def test_register_dummy_strategy(bead_a):
    A, cases = bead_a
    f, e = cases["smooth"]

    def dummy(src, dst, method, cache):
        out = np.zeros_like(dst["mesh"]["x0"])
        out[dst["nodes"][0]] = src["f"].sum(axis=0)                                # 합력만 한 노드에
        return out, {"dummy": True}
    ltm.register("dummy", dummy)
    try:
        loads, info = _go(A, e, "dummy", key="none")
        p = info["per_esl"][0]
        assert p["strategy"] == "dummy" and p["dummy"] is True and info["variant"] == "dummy"
        assert p["dF_rel"] <= 1e-10 and p["dM_rel"] <= 1e-10                       # 실행기 공통 LT-4 보정
    finally:
        ltm.STRATEGIES.pop("dummy")
    with pytest.raises(EslError):
        _go(A, e, "nope")


def test_identity_keys(bead_a):
    A, cases = bead_a
    f, e = cases["smooth"]
    B = dict(A)
    B["x0"] = A["x0"] + np.array([0.0, 0.0, 50.0])                                   # 같은 ID, 좌표 다름
    assert ltm.same_mesh(A, B, "topo") and not ltm.same_mesh(A, B, "topo+coords")
    assert ltm.same_mesh(A, A, "topo+coords") and not ltm.same_mesh(A, A, "none")
    C = dict(A)
    C["node_id"] = A["node_id"] + 10 ** 6
    assert not ltm.same_mesh(A, C, "topo")
    fd, _ = tg.entry_load(tg.Target("S1", A, e.meta["frame"], []), e.raw)
    for key, mesh in (("topo", A), ("topo+coords", A), ("topo", B)):
        loads, info = _go(mesh, e, key=key)
        assert info["fast_path"] == "identity" and np.array_equal(loads[0][1], fd), key
    _, i_none = _go(A, e, key="none")
    _, i_cell = _go(A, e, "cell", 10.0, key="topo+coords")                         # LT-22: 셀은 같은 메시여도 셀
    _, i_mask = _go(A, e, mask=np.ones(A["conn"].shape[0], bool), key="topo+coords")
    assert i_none["per_esl"][0]["strategy"] == "work" and i_cell["per_esl"][0]["strategy"] == "cell"
    assert i_mask["per_esl"][0]["strategy"] == "work"                               # 활성 마스크 = identity 아님


def test_placement_global_rigid_frame(bead_a):
    A, cases = bead_a
    f, e = cases["smooth"]
    th = np.radians(3.0)
    R = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0], [-np.sin(th), 0, np.cos(th)]])
    t = np.array([2.0, 0.5, -1.0])
    xg, fg = ltm.place(A["x0"], f, None)
    assert xg is not None and np.array_equal(fg, f)
    xr, fr = ltm.place(A["x0"], f, {"kind": "rigid", "R": R, "t": t})
    assert np.allclose(fr.sum(axis=0), R @ f.sum(axis=0), rtol=0, atol=1e-12 * np.abs(f).sum())
    xb, fb = ltm.place(xr, fr, {"kind": "rigid", "R": R.T, "t": -R.T @ t})
    assert np.abs(xb - A["x0"]).max() <= 1e-12 * 1e3 and np.abs(fb - f).max() <= 1e-12 * np.abs(f).max()
    B = scmp.lt_plate_mesh(Lx=LX * 1.03, Lz=LZ * 1.03, h=H0, bead=None)              # 면내 1.03 배
    fs = e.meta["frame"]
    fd = nz.frame(B["x0"], None, B["conn"], B["elem_type"])
    cs = nz.cell_centers(fs, 6, 4).reshape(-1, 3)
    xp, _ = ltm.place(cs, np.zeros_like(cs), {"kind": "frame", "src_frame": fs, "dst_frame": fd})
    assert np.abs(xp - nz.cell_centers(fd, 6, 4).reshape(-1, 3)).max() <= 1e-9
    _, fp = ltm.place(A["x0"], f, {"kind": "frame", "src_frame": fs, "dst_frame": fd})
    assert np.allclose(fp.sum(axis=0), (nz.rotation(fd).T @ nz.rotation(fs)) @ f.sum(axis=0), rtol=0,
                       atol=1e-12 * np.abs(f).sum())
    loads, info = _go(B, e, placement={"kind": "frame"}, key="none")               # 실행기: frame 배치 → 합력 보존
    assert info["per_esl"][0]["dF_rel"] <= 1e-10


# ---------------------------------------------------------------- V-LT-1 같은 메시 = ①
def test_same_mesh_identity_and_general_path(bead_a):
    A, cases = bead_a
    f, e = cases["smooth"]
    a = np.linalg.norm(f, axis=1)
    assert a.sum() / np.linalg.norm(f.sum(axis=0)) > 1e3                            # 이웃 상쇄(자기평형) ESL
    loads, info = _go(A, e)
    fd, _ = tg.entry_load(tg.Target("S1", A, e.meta["frame"], []), e.raw)
    assert info["fast_path"] == "identity" and np.array_equal(loads[0][1], fd)      # (a) 비트 동일
    B = dict(A)
    B["node_id"] = A["node_id"] + 10 ** 6                                           # (b) 일반 사영 경로
    lb, ib = _go(B, e)
    assert ib["fast_path"] is None and ib["per_esl"][0]["strategy"] == "work"
    assert float(np.abs(lb[0][1] - fd).max()) <= 1e-9 * float(a.max())
    sup = tg.auto_supports(A)
    r0 = _solve(A, sup, loads + [("E0|t", fd)], keep=("E0", "E0|t"))
    supb = [(n + 10 ** 6, d) for n, d in sup]
    r1 = _solve(B, supb, lb)
    for k in ("umax", "C"):
        assert abs(r1["per_esl"][0][k] / r0["per_esl"][0][k] - 1) <= 1e-9
    rows = ltm.diag_rows([{"variant": "work", "entry_id": "E0", "f": loads[0][1], "C": r0["per_esl"][0]["C"],
                           "umax": r0["per_esl"][0]["umax"], "u": r0["u"]["E0"]}],
                         {"E0": {"kind": "direct_nodal", "f": fd, "C": r0["per_esl"][1]["C"],
                                 "umax": r0["per_esl"][1]["umax"], "u": r0["u"]["E0|t"]}}, {"E0": "씬"})
    for k in ("load_corr", "mac", "umax_ratio", "C_ratio", "sum_abs_ratio", "max_abs_ratio"):
        assert rows[0][k] == pytest.approx(1.0, abs=1e-9), k


# ---------------------------------------------------------------- V-LT-2 재메시
def _remesh_ratios(A, f, e):
    supA = tg.auto_supports(A)
    ra = _solve(A, supA, [("E0", f)], keep=("E0",))
    ua, Ca = ra["per_esl"][0]["umax"], ra["per_esl"][0]["C"]
    ident, out = {}, {}
    for v in (("work", None), ("cell", None), ("cell", 3.0)):
        lv, _ = _go(A, e, *v)
        r = _solve(A, supA, lv, keep=("E0",))
        ident[ltm.variant_label(*v)] = {"umax": r["per_esl"][0]["umax"] / ua, "C": r["per_esl"][0]["C"] / Ca,
                                        "mac": ltm.mac(r["u"]["E0"], ra["u"]["E0"]),
                                        "corr": ltm.load_corr(lv[0][1], f)}
    X = A["x0"]
    pos = {int(n): i for i, n in enumerate(A["node_id"].tolist())}
    for h in (2.5, 3.5):
        T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=h, bead=BEAD, node_base=500001)
        XT = T["x0"]                                                               # 지지 = A 지지점 최근접(같은 기준점)
        sup = [(int(T["node_id"][np.argmin(np.linalg.norm(XT - X[pos[n]], axis=1))]), d) for n, d in supA]
        for v in (("work", None), ("cell", None), ("cell", 3.0)):
            lv, iv = _go(T, e, *v, h=h)
            assert iv["per_esl"][0]["dF_rel"] <= 1e-10
            r = _solve(T, sup, lv)
            out[(h, ltm.variant_label(*v))] = (r["per_esl"][0]["umax"] / ua, r["per_esl"][0]["C"] / Ca)
    return ident, out


def test_remesh_work_closer_than_cell_smooth(bead_a):
    A, cases = bead_a
    ident, out = _remesh_ratios(A, *cases["smooth"])
    assert ident["work"]["mac"] == pytest.approx(1.0, abs=1e-9) and ident["work"]["corr"] == pytest.approx(1.0, abs=1e-12)
    assert ident["cell:legacy"]["mac"] < ident["work"]["mac"] and ident["cell:legacy"]["corr"] < 0.5
    for h in (2.5, 3.5):
        uw, cw = out[(h, "work")]
        _ul, cl = out[(h, "cell:legacy")]
        _u3, c3 = out[(h, "cell:3")]
        assert 0.7 <= uw <= 1.3 and 0.7 <= cw <= 1.3, (h, uw, cw)
        assert abs(np.log(cw)) < abs(np.log(cl)), (h, cw, cl)                       # C: W 가 legacy 보다 ① 에 가까움
        assert abs(np.log(c3)) <= abs(np.log(cl)) + 1e-12                           # 셀 3 mm 는 W 와 legacy 사이(또는 W 쪽)


def test_remesh_node_noise_issue63(bead_a):
    """노드 단위 잡음(#63 증상): legacy 셀은 d000(= A) 에서도 umax 수 배·상관 낮음, W 는 d000 에서 ① 과 같고 재메시에서도
    umax 가 legacy 보다 ① 에 훨씬 가깝다(C 는 노드 단위 잡음 에너지를 W 는 옮기지 못해 작게, legacy 는 크게)."""
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
        assert cw < 1.0 < cl, (h, cw, cl)


# ---------------------------------------------------------------- V-LT-3 보존
def test_conservation_work_and_cells(tmp_path, monkeypatch):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None)
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=2.5, bead=None, offset=(1.0, 0.5, 0.0), node_base=900001)
    b = ltm.balance(A["x0"], f)
    W = ltm.build_work(A["x0"], T, None, WORK, H0)
    f0 = ltm.apply_work(W, f, T["x0"].shape[0])
    assert np.linalg.norm(f0.sum(axis=0) - f.sum(axis=0)) <= 1e-12 * b["sabs"]     # 분할 1 → 합력 보존(보정 전)
    xh = A["x0"].copy()                                                            # 해석 최근접점: 면 y = 0.5, x ≥ 1
    xh[:, 0] = np.maximum(xh[:, 0], 1.0)
    xh[:, 1] = 0.5
    dM = np.linalg.norm(np.cross(xh - A["x0"], f).sum(axis=0)) / (b["sabs"] * b["Lb"])
    _, iw = _go(T, e)
    p = iw["per_esl"][0]
    assert p["dM_rel_before"] == pytest.approx(dM, rel=1e-9)
    assert p["dF_rel"] <= 1e-10 and p["dM_rel"] <= 1e-10 and p["far_frac"] == 0.0
    nodes = np.arange(T["x0"].shape[0])
    for s in (10.0, 3.0):
        fc, ci = ltm.cell_loads(e.raw, e.meta["frame"], T, e.meta["frame"], nodes, s, lambda: W)
        assert np.linalg.norm(fc.sum(axis=0) - f.sum(axis=0)) <= 1e-9 * b["sabs"]
        if s == 3.0:
            assert ci["n_cells_small"] > 0 and ci["small_frac"] > 0
        monkeypatch.setattr(ltm, "BATCH_MIN_CELLS", 1)                              # 일괄 6×6 = lstsq(1e-10)
        fb, bi = ltm.cell_loads(e.raw, e.meta["frame"], T, e.meta["frame"], nodes, s, lambda: W)
        monkeypatch.setattr(ltm, "BATCH_MIN_CELLS", 10000)
        assert bi["batched"] and bi["n_cells_small"] == ci["n_cells_small"]
        assert float(np.abs(fb - fc).max()) <= 1e-10 * float(np.abs(fc).max())
        _, ic = _go(T, e, "cell", s)
        q = ic["per_esl"][0]
        assert q["dF_rel"] <= 1e-10 and q["dM_rel"] <= 1e-10
    ll, _ = _go(T, e, "cell", None)                                                 # legacy 셀 = target.entry_load S2 비트 동일
    fl, _ = tg.entry_load(tg.Target("S2", T, e.meta["frame"], []), None, e.summary_for_mapping(), None)
    assert np.array_equal(ll[0][1], fl)


def test_min_norm_batch_matches_mapping():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(40, 3)) * [10, 10, 1]
    F, M, ref = rng.normal(size=3), rng.normal(size=3), np.array([0.5, -0.2, 0.1])
    f1, _ = mp.min_norm_forces(X, F, M, ref)
    f2, ok = ltm._batch_min_norm(X, np.arange(40), np.zeros(40, np.int64), [0], F[None], M[None], ref[None], 0.0)
    assert ok[0] and float(np.abs(f2 - f1).max()) <= 1e-10 * float(np.abs(f1).max())


# ---------------------------------------------------------------- V-LT-5 먼 노드
def test_far_nodes_boss_and_thresholds(tmp_path):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None, boss=(150.0, 90.0, 18.0, 9.0))
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    T = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None, node_base=800001)
    lw, iw = _go(T, e)
    p = iw["per_esl"][0]
    assert iw["transfer"]["far_n"] > 0 and iw["transfer"]["max_dist_mm"] > 3.0 and p["far_frac"] > 0
    assert np.linalg.norm(lw[0][1].sum(axis=0) - f.sum(axis=0)) <= 1e-9 * p["sum_abs_f"]   # 버리지 않음(합력 보존)
    for ff, want in ((0.0099, None), (0.0101, "LT_FAR_NODES"), (0.199, "LT_FAR_NODES"), (0.201, "LT_TRANSFER_FAILED")):
        assert ltm.far_state({"per_esl": [{"far_frac": ff}]}, WORK)[0] == want, ff


# ---------------------------------------------------------------- 진단 함수(모드 무관 스키마)
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
    assert ltm.variant_label("work", None) == "work" and ltm.variant_label("cell", None) == "cell:legacy"
    assert ltm.variant_label("cell", 3.0) == "cell:3"
