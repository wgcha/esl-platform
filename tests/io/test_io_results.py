"""T-IO-1 (esl_core.md §7.2·§7.3, 검사 규칙 §3.3·§6): TCL 3패스 CSV → npz."""
import json
import os
import tracemalloc
from types import SimpleNamespace

import numpy as np
import pytest

import esl.io.results_csv as RC
from esl.errors import EslError
from esl.io import decide_shear, max_hold, pack_results, write_results_csv
from esl.mech import strain, tstar
from esl.rad import parse_rad, write_rad


def _model(tmp_path):
    nid = np.array([2, 5, 9, 11, 14, 30], dtype=np.int64)
    x0 = np.array([[0, 0, 0], [10, 0, 0], [20, 0, 0], [0, 10, 0], [10, 10, 0], [20, 10, 0.5]], float)
    eid = np.array([7, 3])
    conn = np.array([[2, 5, 14, 11], [5, 9, 30, 14]])
    p = write_rad(tmp_path / "m_0000.rad", nid, x0, eid, [4, 4], conn, 1, "plate", 1, 1.0, 1, 2e5, 0.3,
                  extra_parts=1)
    return parse_rad(p, "plate")


def _data(m, F=4, seed=1):
    """max-hold 시계열: (t, u, eps(F,E,3) hold 텐서, vm(F,E), epsp(F,E))."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 3e-3, F)
    u = rng.normal(size=(F, m.node_id.size, 3))
    inst = rng.normal(size=(F, m.elem_id.size, 3)) * 1e-3 * np.linspace(0.3, 1, F)[:, None, None]
    eq, eps = max_hold(strain.eps_eq(inst), inst)
    epsp = np.maximum.accumulate(np.maximum(eq - 0.5 * eq.max(), 0), axis=0)
    return t, u, eps, eq, epsp


def _write(m, d, F=4, seed=1, **kw):
    t, u, eps, vm, ep = _data(m, F, seed)
    rd = write_results_csv(d, t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, epsp=ep, **kw)
    return rd, (t, u, eps, vm, ep)


def _code(fn, *a, **k):
    with pytest.raises(EslError) as ei:
        fn(*a, **k)
    return ei.value.code


def _load(p):
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _drop(rd, name, pred):
    p = os.path.join(rd, name)
    lines = open(p).read().splitlines()
    open(p, "w").write("\n".join([lines[0]] + [l for l in lines[1:] if not pred(l)]) + "\n")


def test_pack_roundtrip_shapes_dtypes(tmp_path):
    m = _model(tmp_path)
    fi = [10, 11, 12, 13]
    rd, (t, u, eps, vm, ep) = _write(m, tmp_path / "csv", frame_index=fi, extra_nodes=[900, 901],
                                     extra_elems=[800])
    done = json.load(open(os.path.join(rd, "done.json")))
    D = sorted(set(done["candidate_frames"]["max_strain"]) | set(done["candidate_frames"]["plastic_strain"]))
    dpos = [fi.index(f) for f in D]
    out = tmp_path / "out"
    r = pack_results(rd, m, out)
    assert (r["n_frames"], r["n_elems"], r["n_nodes"], r["n_hot"]) == (4, 2, 6, 2)
    assert r["frames_D"] == D and r["candidate_frames"] == done["candidate_frames"]
    f, h, s, d = (_load(out / n) for n in ("final.npz", "history.npz", "strain_frames.npz", "disp.npz"))
    assert set(f) == {"elem_id", "vm_hv", "eps", "ezz", "epsp"}
    assert set(h) == {"time", "frame_index", "elem_id", "vm_hv", "eps", "ezz", "epsp"}
    assert set(s) == {"time", "frame_index", "elem_id", "vm_hv", "eps", "ezz", "epsp", "prev_frame_index",
                      "prev_vm_hv", "prev_eps", "prev_epsp", "prev_available"}
    assert set(d) == {"time", "frame_index", "node_id", "u"}
    assert f["elem_id"].tolist() == m.elem_id.tolist() == [3, 7] and f["elem_id"].dtype == np.int64
    for z in (f, h, s):
        assert all(z[k].dtype == np.float32 for k in ("vm_hv", "eps", "ezz", "epsp"))
    assert np.array_equal(f["eps"], eps[-1].astype(np.float32)) and np.array_equal(f["vm_hv"], vm[-1].astype(np.float32))
    assert np.array_equal(f["ezz"], (-(eps[-1, :, 0] + eps[-1, :, 1])).astype(np.float32))
    assert h["eps"].shape == (4, 2, 3) and h["frame_index"].dtype == np.int32 and h["frame_index"].tolist() == fi
    assert np.allclose(h["time"], t) and np.array_equal(h["epsp"], ep.astype(np.float32))
    assert s["vm_hv"].shape == (len(D), 2) and s["frame_index"].tolist() == D
    assert np.array_equal(s["eps"], eps[dpos].astype(np.float32))
    # 직전 프레임(§P2 7.1): frames 순서의 바로 앞 프레임, 첫 프레임이면 −1·값 0
    assert s["prev_frame_index"].dtype == np.int32 and s["prev_available"].all()
    assert s["prev_eps"].shape == (len(D), 2, 3) and s["prev_vm_hv"].shape == s["prev_epsp"].shape == (len(D), 2)
    for i, k in enumerate(dpos):
        if k == 0:
            assert s["prev_frame_index"][i] == -1 and not s["prev_eps"][i].any() and not s["prev_vm_hv"][i].any()
        else:
            assert s["prev_frame_index"][i] == fi[k - 1]
            assert np.array_equal(s["prev_eps"][i], eps[k - 1].astype(np.float32))
            assert np.array_equal(s["prev_vm_hv"][i], vm[k - 1].astype(np.float32))
            assert np.array_equal(s["prev_epsp"][i], ep[k - 1].astype(np.float32))
    assert d["u"].shape == (len(D), 6, 3) and d["u"].dtype == np.float64 and np.array_equal(d["u"], u[dpos])
    assert d["node_id"].tolist() == m.node_id.tolist() and np.allclose(d["time"], t[dpos])
    meta = json.loads((out / "frames.json").read_text(encoding="utf-8"))
    assert meta["frame_index"] == fi and meta["frames_D"] == D and meta["schema"] == "esl/frames/2"
    assert meta["n_hot"] == 2 and meta["hot_k"] == 200


def test_csv_row_order_irrelevant(tmp_path):
    m = _model(tmp_path)
    rd, (t, u, eps, vm, ep) = _write(m, tmp_path / "csv", F=3)
    pack_results(rd, m, tmp_path / "a")
    for name in ("final.csv", "history.csv", "strain_frames.csv", "disp.csv", "model.csv", "frames.csv"):
        p = os.path.join(rd, name)
        lines = open(p).read().splitlines()
        open(p, "w").write("\n".join([lines[0]] + lines[1:][::-1]) + "\n\n")
    pack_results(rd, m, tmp_path / "b")
    for n in ("final.npz", "history.npz", "strain_frames.npz", "disp.npz"):
        za, zb = _load(tmp_path / "a" / n), _load(tmp_path / "b" / n)
        assert all(np.array_equal(za[k], zb[k]) for k in za), n


def test_chunked_reading(tmp_path, monkeypatch):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv", F=5, extra_elems=[99])
    pack_results(rd, m, tmp_path / "a")
    monkeypatch.setattr(RC, "CHUNK_ROWS", 3)
    pack_results(rd, m, tmp_path / "b")
    for n in ("final.npz", "history.npz", "strain_frames.npz", "disp.npz"):
        za, zb = _load(tmp_path / "a" / n), _load(tmp_path / "b" / n)
        assert all(np.array_equal(za[k], zb[k]) for k in za), n


def test_frame_stride_keeps_candidate_frames(tmp_path):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv", F=7, frames_D=[3])
    r = pack_results(rd, m, tmp_path / "o", frame_stride=3)
    h = _load(tmp_path / "o" / "history.npz")
    assert h["frame_index"].tolist() == [0, 3, 6] and r["frames_D"] == sorted(set(r["frames_D"]))
    rd, _ = _write(m, tmp_path / "csv2", F=7, frames_D=[4])
    r = pack_results(rd, m, tmp_path / "o2", frame_stride=3)
    assert _load(tmp_path / "o2" / "history.npz")["frame_index"].tolist() == [0, 3, 4, 6]   # D ∪ 마지막
    assert 4 in r["frames_D"]


def test_done_missing_and_failed(tmp_path):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv", write_done=False)
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_OUTPUT_MISSING"
    with open(os.path.join(rd, "done.json"), "w") as fh:
        json.dump({"ok": False, "code": "H3D_MISSING_RESULT", "error": "no Max_Strain"}, fh)
    assert _code(pack_results, rd, m, tmp_path / "o") == "H3D_MISSING_RESULT"
    with open(os.path.join(rd, "done.json"), "w") as fh:
        json.dump({"ok": False, "error": "boom"}, fh)
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_LOG_ERROR"


def test_missing_rows_id_mismatch(tmp_path):
    m = _model(tmp_path)
    e1, n3 = str(m.elem_id[1]), str(m.node_id[3])
    cases = [("strain_frames.csv", lambda l: l.split(",")[1] == e1 and l.startswith(l.split(",")[0] + ",") and
              l.split(",")[0] == str(json.load(open(rd0 + "/done.json"))["frames_D"][0])),
             ("final.csv", lambda l: l.split(",")[0] == e1),
             ("history.csv", lambda l: l.startswith(f"2,{e1},")),
             ("disp.csv", lambda l: l.split(",")[1] == n3),
             ("model.csv", lambda l: l.split(",")[0] == str(m.node_id[0]))]
    for i, (name, pred) in enumerate(cases):
        rd0, _ = _write(m, tmp_path / f"csv{i}")
        rd0 = str(rd0)
        _drop(rd0, name, pred)
        assert _code(pack_results, rd0, m, tmp_path / "o") == "ID_MISMATCH", name


def test_bad_values_and_d_not_in_frames(tmp_path):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv")
    p = os.path.join(rd, "final.csv")
    lines = open(p).read().splitlines()
    lines[1] = lines[1].rsplit(",", 1)[0] + ",N/A"
    open(p, "w").write("\n".join(lines) + "\n")
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_OUTPUT_MISSING"
    rd, _ = _write(m, tmp_path / "csv2")
    dj = json.load(open(os.path.join(rd, "done.json")))
    dj["candidate_frames"]["max_strain"].append(99)
    json.dump(dj, open(os.path.join(rd, "done.json"), "w"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_coordinate_mismatch(tmp_path):
    m = _model(tmp_path)
    t, u, eps, vm, ep = _data(m)
    bbox = np.linalg.norm(m.x0.max(0) - m.x0.min(0))
    x_ok = m.x0.copy()
    x_ok[2, 0] += 0.5e-6 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_ok, u, m.elem_id, eps, vm_hv=vm)
    pack_results(rd, m, tmp_path / "o")
    x_bad = m.x0.copy()
    x_bad[2, 0] += 2e-6 * bbox          # tol 초과지만 1 노드·작은 이동 → 0.5.3: 경고만
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_bad, u, m.elem_id, eps, vm_hv=vm)
    assert any(w.startswith("COORD_DEVIATION") for w in pack_results(rd, m, tmp_path / "o")["warnings"])
    x_bad[2, 0] += 0.02 * bbox          # 최대 편차 > 1%·bbox → 실패
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_bad, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_coordinate_float32_far_from_origin(tmp_path):
    # 원점에서 ~2000 mm 떨어진 1 mm 소형 파트: float32 좌표 반올림(~1e-4)은 1e-6·bbox 보다 크다
    nid = np.array([1, 2, 3, 4], dtype=np.int64)
    off = np.array([2000.123456789, -1500.987654321, 800.5555555])
    x0 = off + np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    p = write_rad(tmp_path / "f_0000.rad", nid, x0, np.array([1]), [4], np.array([[1, 2, 3, 4]]),
                  1, "tiny", 1, 1.0, 1, 2e5, 0.3)
    m = parse_rad(p, "tiny")
    t, u, eps, vm, ep = _data(m)
    x32 = m.x0.astype(np.float32).astype(np.float64)
    assert np.linalg.norm(x32 - m.x0, axis=1).max() > 1e-6 * np.sqrt(2)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x32, u, m.elem_id, eps, vm_hv=vm)
    pack_results(rd, m, tmp_path / "o")
    xb = m.x0.copy()
    xb[1, 1] += 1e-3
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, xb, u, m.elem_id, eps, vm_hv=vm)
    assert pack_results(rd, m, tmp_path / "o")["coord_deviation"]["n_dev"] == 1     # 경고
    xb[1, 1] += 0.1
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, xb, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def _big_plate(tmp_path, n=20):
    """n×n 노드 격자 판(요소 (n-1)²) — 노드 수가 충분해 비율 판정을 시험할 수 있음."""
    xs, ys = np.meshgrid(np.arange(n, dtype=float) * 10, np.arange(n, dtype=float) * 10)
    x0 = np.c_[xs.ravel(), ys.ravel(), np.zeros(n * n)]
    nid = np.arange(1, n * n + 1, dtype=np.int64)
    ids = nid.reshape(n, n)
    conn = np.array([[ids[i, j], ids[i, j + 1], ids[i + 1, j + 1], ids[i + 1, j]]
                     for i in range(n - 1) for j in range(n - 1)])
    ne = conn.shape[0]
    p = write_rad(tmp_path / "b_0000.rad", nid, x0, np.arange(1, ne + 1), [4] * ne, conn, 1, "plate", 1, 1.0, 1,
                  2e5, 0.3)
    return parse_rad(p, "plate")


def _pack_shifted(tmp_path, m, shifts, **kw):
    t, u, eps, vm, ep = _data(m, F=3)
    x = m.x0.copy()
    for i, d in shifts.items():
        x[i, 0] += d
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    return pack_results(rd, m, tmp_path / "o", **kw), tmp_path / "o"


def test_coord_deviation_few_nodes_warns(tmp_path):
    m = _big_plate(tmp_path)                      # N=400, bbox≈269
    info, od = _pack_shifted(tmp_path, m, {3: 0.386, 10: 0.1, 11: 0.05})
    w = [x for x in info["warnings"] if x.startswith("COORD_DEVIATION")]
    assert len(w) == 1 and "3개" in w[0] and "rad 좌표 사용" in w[0]
    cd = info["coord_deviation"]
    assert cd["n_dev"] == 3 and cd["n_nodes"] == 400 and abs(cd["max_dev"] - 0.386) < 1e-9
    assert [t["node_id"] for t in cd["top"]] == [int(m.node_id[3]), int(m.node_id[10]), int(m.node_id[11])]
    assert f"{int(m.node_id[3])}(" in w[0]
    assert json.load(open(od / "frames.json"))["coord_deviation"]["n_dev"] == 3


def test_coord_deviation_top10_and_rounding_only_no_warning(tmp_path):
    m = _big_plate(tmp_path)
    info, _ = _pack_shifted(tmp_path, m, {i: 0.1 + i * 0.01 for i in range(4)})  # 4 = 1% of 400 → 경계 포함
    assert info["coord_deviation"]["n_dev"] == 4
    # float32 반올림만 → 경고·기록 없음
    t, u, eps, vm, ep = _data(m, F=3)
    x32 = m.x0.astype(np.float32).astype(np.float64)
    rd = write_results_csv(tmp_path / "csv2", t, m.node_id, x32, u, m.elem_id, eps, vm_hv=vm)
    info = pack_results(rd, m, tmp_path / "o2")
    assert info["coord_deviation"] is None and not any("COORD_DEVIATION" in x for x in info["warnings"])


def test_coord_deviation_many_nodes_or_large_shift_fails(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    # 5개(>1% of 400) 이동 → 실패, 메시지에 비율
    x = m.x0.copy(); x[:5, 0] += 0.1
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o")
    assert ei.value.code == "ID_MISMATCH" and "5/400" in ei.value.message and "최대" in ei.value.message
    # 소수 노드지만 최대 편차 > 1%·bbox → 실패
    bbox = np.linalg.norm(m.x0.max(0) - m.x0.min(0))
    x = m.x0.copy(); x[3, 0] += 0.011 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"
    # ID 뒤섞임(좌표 순서 교환) → 실패
    x = m.x0[::-1].copy()
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_coord_deviation_threshold_from_config(tmp_path):
    m = _big_plate(tmp_path)
    shifts = {i: 0.1 for i in range(5)}
    info, _ = _pack_shifted(tmp_path, m, shifts, coord_check={"warn_max_frac": 0.0125, "warn_max_rel": 0.01})
    assert info["coord_deviation"]["n_dev"] == 5          # 5 ≤ 0.0125·400
    t, u, eps, vm, ep = _data(m, F=3)
    x = m.x0.copy(); x[2, 0] += 0.4
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o", coord_check={"warn_max_frac": 0.01, "warn_max_rel": 1e-4}) \
        == "ID_MISMATCH"                                  # 0.4 > 1e-4·bbox


@pytest.mark.parametrize("name", ["final.csv", "history.csv", "strain_frames.csv", "disp.csv"])
def test_missing_result_files(tmp_path, name):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv")
    os.remove(os.path.join(rd, name))
    assert _code(pack_results, rd, m, tmp_path / "o") == "H3D_MISSING_RESULT"


def test_missing_frames_csv(tmp_path):
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv")
    os.remove(os.path.join(rd, "frames.csv"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_OUTPUT_MISSING"


def test_generator_matches_tstar_rules():
    """write_results_csv 의 H·D = tstar.hot_set·candidate_frames (TCL 과 같은 규칙)."""
    vm = np.array([[0, 0, 0], [1, 2, 0], [3, 2, 1], [3, 5, 1]], float)
    assert tstar.first_reach(vm, 1e-6).tolist() == [2, 3, 2]
    assert tstar.candidate_frames(vm, 1e-6, 5) == [(3, 1), (2, 0)]        # 같은 프레임(2) 중복 제거
    assert tstar.hot_set(vm[-1], np.zeros(3), 2).tolist() == [0, 1]
    assert tstar.hot_set(vm[-1], np.array([0, 0, 0.1]), 1).tolist() == [1, 2]
    assert tstar.hot_set(vm[-1], vm[-1], 300).tolist() == [0, 1, 2]           # |H| 상한 없음


def test_max_hold_and_decide_shear():
    eq = np.array([[1, 0], [3, 1], [2, 5], [4, 5]], float)
    x = np.arange(8.0).reshape(4, 2)
    h, xh = max_hold(eq, x)
    assert h.tolist() == [[1, 0], [3, 1], [3, 5], [4, 5]] and xh[:, 1].tolist() == [1, 3, 5, 5]
    rng = np.random.default_rng(0)
    e = rng.normal(size=(50, 3)) * 1e-3
    vm = strain.eps_eq(e)
    eng = e.copy()
    eng[:, 2] *= 2
    a = decide_shear(vm, eng, "auto")
    assert a["convention"] == "engineering" and a["factor"] == 0.5 and a["max_rel_mismatch"] < 1e-12
    b = decide_shear(vm, e, "auto")
    assert b["convention"] == "tensor" and b["factor"] == 1.0
    assert decide_shear(vm, e, "engineering")["convention"] == "engineering"
    assert decide_shear(np.zeros(3), np.zeros((3, 3)))["max_rel_mismatch"] is None


def test_memory_peak_streaming(tmp_path, monkeypatch):
    """대용량 대비: 메모리 피크 ≤ 결과 배열 바이트 × 1.5 (청크 파싱 + 사전할당, 저장 시 복사 없음)."""
    E = N = 60000
    F = 4
    ids = np.arange(1, E + 1, dtype=np.int64)
    x0 = np.c_[np.arange(N, dtype=float), np.zeros(N), np.zeros(N)]
    m = SimpleNamespace(node_id=ids, elem_id=ids, x0=x0, units_label="")
    rng = np.random.default_rng(0)
    eps = np.abs(rng.normal(size=(F, E, 3))) * np.arange(1, F + 1)[:, None, None]
    u = rng.normal(size=(F, N, 3))
    rd = write_results_csv(tmp_path / "csv", np.arange(F) * 1e-3, ids, x0, u, ids, eps, frames_D=[1, 3], hot_k=5)
    monkeypatch.setattr(RC, "CHUNK_ROWS", 2000)
    pack_results(rd, m, tmp_path / "warm")          # 지연 import·캐시는 측정에서 뺌
    tracemalloc.start()
    try:
        pack_results(rd, m, tmp_path / "o")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    res = sum(a.nbytes for n in ("final.npz", "history.npz", "strain_frames.npz", "disp.npz")
              for a in _load(tmp_path / "o" / n).values())
    assert peak <= 1.5 * res, (peak, res)


def test_no_pickle_in_sources():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "esl")
    for sub in ("rad", "io"):
        for f in os.listdir(os.path.join(root, sub)):
            if f.endswith(".py"):
                src = open(os.path.join(root, sub, f), encoding="utf-8").read()
                assert "import pickle" not in src and "allow_pickle=True" not in src


# ---------------- 직전 프레임(prev, 계약 esl_p2_library.md §7.1)

def test_prev_frames_written_and_packed(tmp_path):
    """D 의 각 f 에 대해 f−1 프레임 전 요소 행(D 에 이미 있으면 중복 없음), done.json prev_frames·strain_frames."""
    m = _model(tmp_path)
    rd, (t, u, eps, vm, ep) = _write(m, tmp_path / "csv", F=7, frames_D=[0, 3, 4])
    done = json.load(open(os.path.join(rd, "done.json")))
    assert done["frames_D"] == [0, 3, 4] and done["prev_frames"] == [2, 3] and done["strain_frames"] == [0, 2, 3, 4]
    rows = [l.split(",")[0] for l in open(os.path.join(rd, "strain_frames.csv")).read().splitlines()[1:]]
    assert sorted(set(rows)) == ["0", "2", "3", "4"] and len(rows) == 4 * 2          # 프레임 3 은 한 번만
    r = pack_results(rd, m, tmp_path / "o")
    assert r["prev_frames"] == [2, 3] and r["prev_available"] is True
    s = _load(tmp_path / "o" / "strain_frames.npz")
    assert s["frame_index"].tolist() == [0, 3, 4] and s["prev_frame_index"].tolist() == [-1, 2, 3]
    assert not s["prev_eps"][0].any() and not s["prev_vm_hv"][0].any()            # f=0 → 0 배열
    assert np.array_equal(s["prev_eps"][1], eps[2].astype(np.float32))
    assert np.array_equal(s["prev_eps"][2], s["eps"][1])                           # prev(4)=3 = D 의 3
    meta = json.loads((tmp_path / "o" / "frames.json").read_text(encoding="utf-8"))
    assert meta["prev_frame_index"] == [-1, 2, 3] and meta["prev_available"] == [True, True, True]


def test_prev_frames_missing_old_tcl_output(tmp_path):
    """예전 TCL 출력(직전 프레임 행 없음) → 경고 + prev_available=False, 일부만 있으면 ID_MISMATCH."""
    m = _model(tmp_path)
    rd, _ = _write(m, tmp_path / "csv", F=7, frames_D=[3, 5], write_prev=False)
    r = pack_results(rd, m, tmp_path / "o")
    assert r["prev_available"] is False and any("직전 프레임" in w for w in r["warnings"])
    s = _load(tmp_path / "o" / "strain_frames.npz")
    assert s["prev_available"].tolist() == [False, False] and s["prev_frame_index"].tolist() == [2, 4]
    assert not s["prev_eps"].any()
    rd, _ = _write(m, tmp_path / "csv2", F=7, frames_D=[3, 5])
    _drop(rd, "strain_frames.csv", lambda l: l.startswith(f"2,{m.elem_id[0]},"))   # 프레임 2 일부 요소만 남김
    assert _code(pack_results, rd, m, tmp_path / "o2") == "ID_MISMATCH"
