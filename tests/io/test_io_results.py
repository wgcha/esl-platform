"""T-IO-1 (esl_core.md §3.2·§3.3·§6)."""
import json
import os

import numpy as np
import pytest

import esl.io.results_csv as RC
from esl.errors import EslError
from esl.io import pack_results, write_results_csv
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
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 3e-3, F)
    u = rng.normal(size=(F, m.node_id.size, 3))
    eps = rng.normal(size=(F, m.elem_id.size, 2, 3)) * 1e-3
    return t, u, eps


def _code(fn, *a, **k):
    with pytest.raises(EslError) as ei:
        fn(*a, **k)
    return ei.value.code


def _load(p):
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def test_pack_roundtrip_shapes_dtypes(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps,
                           frame_index=[10, 11, 12, 13], extra_nodes=[900, 901], extra_elems=[800])
    # 다른 파트 행 + mid layer 섞기
    with open(os.path.join(rd, "strain.csv"), "a") as fh:
        fh.write(f"10,{m.elem_id[0]},mid,9,9,9\n")
    out = tmp_path / "out"
    r = pack_results(rd, m, out)
    assert (r["n_frames"], r["n_elems"], r["n_nodes"]) == (4, 2, 6)
    s = _load(out / "strain_tensor.npz")
    d = _load(out / "disp.npz")
    assert set(s) == {"time", "frame_index", "elem_id", "eps"}
    assert set(d) == {"time", "frame_index", "node_id", "u"}
    assert s["eps"].shape == (4, 2, 2, 3) and s["eps"].dtype == np.float32
    assert s["frame_index"].dtype == np.int32 and s["frame_index"].tolist() == [10, 11, 12, 13]
    assert s["time"].dtype == np.float64 and np.allclose(s["time"], t)
    assert s["elem_id"].dtype == np.int64 and s["elem_id"].tolist() == m.elem_id.tolist() == [3, 7]
    assert np.allclose(s["eps"], eps.astype(np.float32))
    assert d["u"].shape == (4, 6, 3) and d["u"].dtype == np.float64
    assert d["node_id"].tolist() == m.node_id.tolist()
    assert np.array_equal(d["u"], u)
    meta = json.loads((out / "frames.json").read_text(encoding="utf-8"))
    assert meta["frame_index"] == [10, 11, 12, 13] and meta["n_frames"] == 4


def test_csv_row_order_irrelevant(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m, F=3)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps)
    for name in ("strain.csv", "disp.csv", "model.csv"):
        p = os.path.join(rd, name)
        lines = open(p).read().splitlines()
        body = lines[1:][::-1]
        open(p, "w").write("\n".join([lines[0]] + body) + "\n")
    pack_results(rd, m, tmp_path / "o")
    s = _load(tmp_path / "o" / "strain_tensor.npz")
    assert np.allclose(s["eps"], eps.astype(np.float32))


def test_chunked_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(RC, "CHUNK_ROWS", 3)
    m = _model(tmp_path)
    t, u, eps = _data(m, F=5)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, extra_elems=[99])
    pack_results(rd, m, tmp_path / "o")
    d = _load(tmp_path / "o" / "disp.npz")
    assert np.array_equal(d["u"], u)


def test_frame_stride(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m, F=5)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps)
    r = pack_results(rd, m, tmp_path / "o", frame_stride=2)
    assert r["n_frames"] == 3
    d = _load(tmp_path / "o" / "disp.npz")
    assert d["frame_index"].tolist() == [0, 2, 4] and np.array_equal(d["u"], u[::2])


def test_done_missing_and_failed(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, write_done=False)
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_OUTPUT_MISSING"
    with open(os.path.join(rd, "done.json"), "w") as fh:
        json.dump({"ok": False, "code": "H3D_MISSING_RESULT", "error": "no Strain"}, fh)
    assert _code(pack_results, rd, m, tmp_path / "o") == "H3D_MISSING_RESULT"
    with open(os.path.join(rd, "done.json"), "w") as fh:
        json.dump({"ok": False, "error": "boom"}, fh)
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_LOG_ERROR"


def test_missing_rows_id_mismatch(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps)

    def drop(name, pred):
        p = os.path.join(rd, name)
        lines = open(p).read().splitlines()
        open(p, "w").write("\n".join([lines[0]] + [l for l in lines[1:] if not pred(l)]) + "\n")

    # 요소 하나의 top layer 한 프레임 누락
    drop("strain.csv", lambda l: l.startswith(f"2,{m.elem_id[1]},top,"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"

    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps)
    drop("disp.csv", lambda l: l.split(",")[1] == str(m.node_id[3]))
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"

    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps)
    drop("model.csv", lambda l: l.split(",")[0] == str(m.node_id[0]))
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_coordinate_mismatch(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m)
    x_bad = m.x0.copy()
    bbox = np.linalg.norm(m.x0.max(0) - m.x0.min(0))
    x_ok = m.x0.copy()
    x_ok[2, 0] += 0.5e-6 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_ok, u, m.elem_id, eps)
    pack_results(rd, m, tmp_path / "o")
    x_bad[2, 0] += 2e-6 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_bad, u, m.elem_id, eps)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"



def test_coordinate_float32_far_from_origin(tmp_path):
    # 원점에서 ~2000 mm 떨어진 1 mm 소형 파트: float32 좌표 반올림(~1e-4)은 1e-6·bbox 보다 크다
    nid = np.array([1, 2, 3, 4], dtype=np.int64)
    off = np.array([2000.123456789, -1500.987654321, 800.5555555])
    x0 = off + np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    p = write_rad(tmp_path / "f_0000.rad", nid, x0, np.array([1]), [4], np.array([[1, 2, 3, 4]]),
                  1, "tiny", 1, 1.0, 1, 2e5, 0.3)
    m = parse_rad(p, "tiny")
    t, u, eps = _data(m)
    x32 = m.x0.astype(np.float32).astype(np.float64)
    assert np.linalg.norm(x32 - m.x0, axis=1).max() > 1e-6 * np.sqrt(2)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x32, u, m.elem_id, eps)
    pack_results(rd, m, tmp_path / "o")
    # 실제 불일치(1e-3)는 여전히 검출
    xb = m.x0.copy()
    xb[1, 1] += 1e-3
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, xb, u, m.elem_id, eps)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_layer_required_and_missing_files(tmp_path):
    m = _model(tmp_path)
    t, u, eps = _data(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps,
                           layer_names=("bottom", "mid"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "H3D_MISSING_RESULT"
    rd = write_results_csv(tmp_path / "csv2", t, m.node_id, m.x0, u, m.elem_id, eps)
    os.remove(os.path.join(rd, "disp.csv"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "H3D_MISSING_RESULT"
    os.remove(os.path.join(rd, "frames.csv"))
    assert _code(pack_results, rd, m, tmp_path / "o") == "TOOL_OUTPUT_MISSING"


def test_no_pickle_in_sources():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "esl")
    for sub in ("rad", "io"):
        for f in os.listdir(os.path.join(root, sub)):
            if f.endswith(".py"):
                src = open(os.path.join(root, sub, f), encoding="utf-8").read()
                assert "import pickle" not in src and "allow_pickle=True" not in src
