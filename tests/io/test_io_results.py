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
    assert set(s) == {"time", "frame_index", "elem_id", "vm_hv", "eps", "ezz", "epsp"}
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
    x_bad[2, 0] += 2e-6 * bbox
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
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


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
