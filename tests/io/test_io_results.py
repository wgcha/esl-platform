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
    """0.5.5: 좌표는 강체 정합 후 잔차 ≤ max_rel(0.005)·bbox 개략 확인만 — 작은 편차는 경고 없이 정보 기록."""
    m = _model(tmp_path)
    t, u, eps, vm, ep = _data(m)
    bbox = np.linalg.norm(m.x0.max(0) - m.x0.min(0))
    x_ok = m.x0.copy()
    x_ok[2, 0] += 0.5e-6 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_ok, u, m.elem_id, eps, vm_hv=vm)
    assert pack_results(rd, m, tmp_path / "o")["coord_deviation"] is None
    x_bad = m.x0.copy()
    x_bad[2, 0] += 2e-6 * bbox          # 반올림 수준 초과지만 작음 → 통과 + 정보 기록(경고 아님)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x_bad, u, m.elem_id, eps, vm_hv=vm)
    info = pack_results(rd, m, tmp_path / "o")
    assert info["coord_deviation"]["n_dev"] == 1 and not any("COORD" in w for w in info["warnings"])
    x_bad[2, 0] += 0.02 * bbox          # 한 노드가 2%·bbox → 정합 후 잔차 > 0.5%·bbox → 실패
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


def _pack_shifted(tmp_path, m, shifts, conn=True, **kw):
    t, u, eps, vm, ep = _data(m, F=3)
    x = m.x0.copy()
    for i, d in shifts.items():
        x[i, 0] += d
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm,
                           elem_nodes=_conn_ids(m) if conn else None)
    return pack_results(rd, m, tmp_path / "o", **kw), tmp_path / "o"


def _conn_ids(m):
    return np.where(m.conn >= 0, m.node_id[np.maximum(m.conn, 0)], 0)


def test_coord_small_deviation_few_nodes_passes_as_info(tmp_path):
    m = _big_plate(tmp_path)                      # N=400, bbox≈269
    info, od = _pack_shifted(tmp_path, m, {3: 0.386, 10: 0.1, 11: 0.05})
    assert not any("COORD" in w or "CONN_CHECK" in w for w in info["warnings"]), info["warnings"]
    cd = info["coord_deviation"]
    assert cd["n_dev"] == 3 and cd["n_nodes"] == 400 and abs(cd["max_dev"] - 0.386) < 1e-9
    assert [t["node_id"] for t in cd["top"]] == [int(m.node_id[3]), int(m.node_id[10]), int(m.node_id[11])]
    assert cd["max_rel"] == 0.005 and abs(cd["threshold"] - 0.005 * cd["bbox"]) < 1e-12
    fj = json.load(open(od / "frames.json"))
    assert fj["coord_deviation"]["n_dev"] == 3 and fj["conn_check"] == {"checked": True, "reason": None,
                                                                        "n_elems": 361, "n_mismatch": 0}


def test_coord_all_nodes_0p4_deviation_passes(tmp_path):
    """실서버 사례(압축 h3d 등): 전 노드가 rad 와 최대 ~0.4 다름(bbox 대비 작음) → 통과, 편차는 정보로 기록."""
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    rng = np.random.default_rng(4)
    d = rng.uniform(-1, 1, size=m.x0.shape)
    d *= 0.386 / np.linalg.norm(d, axis=1).max()
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0 + d, u, m.elem_id, eps, vm_hv=vm,
                           elem_nodes=_conn_ids(m))
    info = pack_results(rd, m, tmp_path / "o")
    cd = info["coord_deviation"]
    assert cd["n_dev"] == 400 and abs(cd["max_dev"] - 0.386) < 1e-9 and cd["rigid_residual_max"] < cd["threshold"]
    assert not any("COORD" in w for w in info["warnings"]) and info["conn_check"]["checked"]
    # 계산 좌표는 rad: disp.npz 변위는 h3d 그대로
    assert np.array_equal(_load(tmp_path / "o" / "disp.npz")["u"].shape, (len(info["frames_D"]), 400, 3))


def test_coord_large_rigid_motion_passes(tmp_path):
    """강체 이동·회전이 커도(bbox 의 수십 %) 정합 후 잔차가 작으면 통과."""
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    th = np.radians(30.0)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    xs = m.x0 @ R.T + np.array([150.0, -80.0, 40.0])
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, xs, u, m.elem_id, eps, vm_hv=vm, elem_nodes=_conn_ids(m))
    info = pack_results(rd, m, tmp_path / "o")
    cd = info["coord_deviation"]
    assert cd["rigid"] and cd["rigid_residual_max"] < 1e-9 and abs(cd["rigid_rotation_deg"] - 30.0) < 1e-9
    assert cd["max_dev"] > 100


def test_coord_different_shape_fails(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    bbox = np.linalg.norm(m.x0.max(0) - m.x0.min(0))
    x = m.x0.copy()
    x[:, 2] += 0.1 * bbox * (x[:, 0] / x[:, 0].max()) ** 2        # 휜 판(비강체) → 정합 후 잔차 > 0.5%·bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm, elem_nodes=_conn_ids(m))
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o")
    msg = ei.value.message
    assert ei.value.code == "ID_MISMATCH" and "강체 정합 후 잔차 최대" in msg and "max_rel 0.005" in msg
    assert "잔차 상위 노드" in msg and "평균 편차 [" in msg
    # 한 노드만 크게(1.1%·bbox) → 실패
    x = m.x0.copy(); x[3, 0] += 0.011 * bbox
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"
    # 노드 ID 뒤섞임(좌표 순서 무작위 교환) → 실패. (역순은 대칭 격자의 180° 회전 = 강체라 좌표로는 통과)
    x = m.x0[np.random.default_rng(1).permutation(m.node_id.size)]
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"


def test_coord_node_missing_fails(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, elem_nodes=_conn_ids(m))
    _drop(rd, "model.csv", lambda l: l.split(",")[0] == str(m.node_id[7]))
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o")
    assert ei.value.code == "ID_MISMATCH" and "노드 1개가 없음" in ei.value.message


def test_coord_threshold_from_config_and_legacy_keys_ignored(tmp_path):
    m = _big_plate(tmp_path)
    info, _ = _pack_shifted(tmp_path, m, {2: 0.4}, coord_check={"warn_max_frac": 0.0, "warn_max_rel": 0.0})
    assert info["coord_deviation"]["n_dev"] == 1 and info["coord_deviation"]["max_rel"] == 0.005   # 이전 키 무시
    t, u, eps, vm, ep = _data(m, F=3)
    x = m.x0.copy(); x[2, 0] += 0.4
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    assert _code(pack_results, rd, m, tmp_path / "o", coord_check={"max_rel": 1e-4}) == "ID_MISMATCH"  # 0.4 > 1e-4·bbox


# ---- 0.5.5: 요소 연결(elems.csv) 동일성
def test_canon_conn_rotation_reflection_triangles():
    q = np.array([[1, 2, 3, 4], [3, 4, 1, 2], [4, 3, 2, 1], [2, 1, 4, 3], [1, 3, 2, 4]])
    c = RC.canon_conn(q)
    assert all(np.array_equal(c[i], c[0]) for i in range(4)) and not np.array_equal(c[4], c[0])
    t = np.array([[5, 6, 7, 0], [7, 5, 6, 0], [6, 5, 7, -1], [5, 6, 7, 7], [5, 5, 6, 7], [7, 6, 5, 5]])
    ct = RC.canon_conn(t)
    assert all(np.array_equal(ct[i], [5, 6, 7, 0]) for i in range(len(t)))
    assert not np.array_equal(RC.canon_conn([[5, 6, 8, 0]])[0], ct[0])


def test_conn_check_match_rotated_reversed(tmp_path):
    m = _big_plate(tmp_path, n=6)
    t, u, eps, vm, ep = _data(m, F=3)
    ids = _conn_ids(m).copy()
    ids[0] = np.roll(ids[0], 1)
    ids[1] = ids[1][::-1]
    ids[2] = np.roll(ids[2][::-1], 2)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, elem_nodes=ids)
    info = pack_results(rd, m, tmp_path / "o")
    assert info["conn_check"] == {"checked": True, "reason": None, "n_elems": 25, "n_mismatch": 0}
    assert not any("CONN_CHECK" in w for w in info["warnings"])
    assert json.load(open(os.path.join(rd, "done.json")))["elems_ok"] is True
    # 행 순서 무관 + n4 빈칸(삼각형 표현) 허용
    p = os.path.join(rd, "elems.csv")
    lines = open(p).read().splitlines()
    open(p, "w").write("\n".join([lines[0]] + lines[1:][::-1]) + "\n")
    assert pack_results(rd, m, tmp_path / "o2")["conn_check"]["checked"]


def test_conn_check_one_element_node_changed_fails(tmp_path):
    m = _big_plate(tmp_path, n=6)
    t, u, eps, vm, ep = _data(m, F=3)
    ids = _conn_ids(m).copy()
    ids[4, 2] = ids[10, 2]                         # 요소 1개의 노드 1개가 다름(좌표는 그대로 → 좌표만으론 못 잡음)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, elem_nodes=ids)
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o")
    msg = ei.value.message
    assert ei.value.code == "ID_MISMATCH" and "요소 1/25개" in msg and f"{int(m.elem_id[4])}: rad " in msg
    # 대상 파트 요소 행이 elems.csv 에 없음 → 실패(h3d 없음)
    rd = write_results_csv(tmp_path / "csv2", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm,
                           elem_nodes=_conn_ids(m))
    _drop(rd, "elems.csv", lambda l: l.split(",")[0] == str(m.elem_id[3]))
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o2")
    assert ei.value.code == "ID_MISMATCH" and "h3d 없음" in ei.value.message


def test_conn_check_triangles(tmp_path):
    nid = np.array([1, 2, 3, 4, 5], dtype=np.int64)
    x0 = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [20, 5, 0]], float)
    conn = np.array([[1, 2, 3, 4], [2, 5, 3, 0]])
    p = write_rad(tmp_path / "t_0000.rad", nid, x0, np.array([1, 2]), [4, 3], conn, 1, "tri", 1, 1.0, 1, 2e5, 0.3)
    m = parse_rad(p, "tri")
    t, u, eps, vm, ep = _data(m, F=3)
    for k, h3d in enumerate(([[4, 1, 2, 3], [3, 2, 5, 5]], [[1, 2, 3, 4], [5, 3, 2, 0]])):   # 중복 노드·n4=0 표현
        rd = write_results_csv(tmp_path / f"c{k}", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, elem_nodes=h3d)
        assert pack_results(rd, m, tmp_path / f"o{k}")["conn_check"]["checked"]
    rd = write_results_csv(tmp_path / "bad", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm,
                           elem_nodes=[[1, 2, 3, 4], [2, 5, 4, 0]])
    assert _code(pack_results, rd, m, tmp_path / "ob") == "ID_MISMATCH"


def test_conn_check_skipped_without_elems_csv(tmp_path):
    m = _big_plate(tmp_path, n=6)
    info, od = _pack_shifted(tmp_path, m, {}, conn=False)
    w = [x for x in info["warnings"] if x.startswith("CONN_CHECK_SKIPPED")]
    assert len(w) == 1 and "elems.csv 없음" in w[0]
    assert info["conn_check"]["checked"] is False and json.load(open(od / "frames.json"))["conn_check"]["checked"] is False
    # elems.csv 가 있어도 done.json elems_ok=false 면 생략
    t, u, eps, vm, ep = _data(m, F=3)
    bad = _conn_ids(m).copy(); bad[0, 0] = bad[5, 2]
    rd = write_results_csv(tmp_path / "csv2", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, elem_nodes=bad)
    dj = json.load(open(os.path.join(rd, "done.json")))
    dj["elems_ok"] = False
    json.dump(dj, open(os.path.join(rd, "done.json"), "w"))
    info = pack_results(rd, m, tmp_path / "o2")
    assert any(x.startswith("CONN_CHECK_SKIPPED") and "elems_ok=false" in x for x in info["warnings"])


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


# ---- 0.5.4: model.csv 초기 좌표 = 프레임 0 node.coords − 프레임 0 변위 (낙하 해석의 강체 이동)
def _drop_u(m, F=3, v=(0.0, 0.0, -4.5), dt=0.08, seed=7):
    """프레임 0 에 0 이 아닌 변위: 강체 이동 v·dt + 작은 변형(편차 tol 수준 아님)."""
    t, u, eps, vm, ep = _data(m, F=F)
    rng = np.random.default_rng(seed)
    u = u.copy()
    u[0] = np.asarray(v) * dt + rng.normal(size=u[0].shape) * 1e-3
    return t, u, eps, vm


def test_frame0_displacement_corrected_passes(tmp_path):
    m = _big_plate(tmp_path)                       # N=400
    t, u, eps, vm = _drop_u(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm)
    hdr = open(os.path.join(rd, "model.csv")).readline().strip()
    assert hdr == "node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz"
    info = pack_results(rd, m, tmp_path / "o")
    assert info["coord_deviation"] is None and not any("COORD_DEVIATION" in w for w in info["warnings"])
    fj = json.load(open(tmp_path / "o" / "frames.json"))
    assert fj["model_coords"] == "coords_minus_disp_frame0" and fj["frame0_time"] == float(t[0])
    # 예전 TCL 처럼 변형 좌표(x0+u0)를 x0 로 쓴 구형 model.csv → 0.5.5: 강체 이동 + 작은 변형이라 통과(정보 기록)
    rd2 = write_results_csv(tmp_path / "csv2", t, m.node_id, m.x0 + u[0], u, m.elem_id, eps, vm_hv=vm,
                            legacy_model=True)
    info = pack_results(rd2, m, tmp_path / "o2")
    cd = info["coord_deviation"]
    assert cd["n_dev"] == 400 and abs(cd["mean_dev"][2] + 0.36) < 1e-3 and cd["rigid_residual_max"] < 0.01
    assert cd["coord_source"].startswith("x0 (구형") and not any("COORD" in w for w in info["warnings"])


def test_rigid_shift_passes_with_diagnostics(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm, ep = _data(m, F=3)
    th = np.radians(0.5)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    xs = m.x0 @ R.T + np.array([0.0, 0.0, -0.386])
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, xs, u, m.elem_id, eps, vm_hv=vm, legacy_model=True)
    cd = pack_results(rd, m, tmp_path / "o")["coord_deviation"]
    assert cd["rigid"] and abs(cd["rigid_rotation_deg"] - 0.5) < 1e-6
    g = RC.coord_diagnostics(xs, m.x0, 1e-6)
    assert g["rigid"] and g["rigid_residual_max"] < 1e-9 and abs(g["rigid_rotation_deg"] - 0.5) < 1e-9
    assert abs(g["std_dev"][2]) < 1e-12 and abs(g["mean_dev"][2] + 0.386) < 1e-12


def test_legacy_model_csv_still_read(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm = _drop_u(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm, legacy_model=True)
    assert open(os.path.join(rd, "model.csv")).readline().strip() == "node_id,x0,y0,z0"
    info = pack_results(rd, m, tmp_path / "o")
    assert info["coord_deviation"] is None
    assert json.load(open(tmp_path / "o" / "frames.json"))["model_coords"] == "legacy"
    x = m.x0.copy(); x[3, 0] += 0.2
    rd = write_results_csv(tmp_path / "csv2", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm, legacy_model=True)
    info = pack_results(rd, m, tmp_path / "o2")
    assert info["coord_deviation"]["n_dev"] == 1 and not any("COORD" in w for w in info["warnings"])


def test_coords_already_initial_falls_back_to_raw(tmp_path):
    """node.coords 가 이미 변형 전 좌표인 h3d: cx = x0, x0열 = cx − d → 원값 비교로 통과 + 경고."""
    m = _big_plate(tmp_path)
    t, u, eps, vm = _drop_u(m)
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, m.x0, u, m.elem_id, eps, vm_hv=vm)
    p = os.path.join(rd, "model.csv")
    g = "{:.17g}".format
    rows = ["node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz"]
    for k in range(m.node_id.size):
        c, d = m.x0[k], u[0, k]
        rows.append(",".join([str(int(m.node_id[k]))] + [g(v) for v in (*(c - d), *c, *d)]))
    open(p, "w").write("\n".join(rows) + "\n")
    info = pack_results(rd, m, tmp_path / "o")
    assert info["coord_deviation"] is None and any("원값(cx,cy,cz)으로 비교" in w for w in info["warnings"])


def test_real_mesh_mismatch_still_fails_after_correction(tmp_path):
    m = _big_plate(tmp_path)
    t, u, eps, vm = _drop_u(m)
    rng = np.random.default_rng(3)
    x = m.x0 + rng.normal(size=m.x0.shape) * 3.0     # 다른 형상(비강체, bbox 의 ~1%) — 변위 보정 후에도 다름
    rd = write_results_csv(tmp_path / "csv", t, m.node_id, x, u, m.elem_id, eps, vm_hv=vm)
    with pytest.raises(EslError) as ei:
        pack_results(rd, m, tmp_path / "o")
    assert ei.value.code == "ID_MISMATCH" and "강체 정합 후 잔차 최대" in ei.value.message
    assert "frame 0 변위 최대" in ei.value.message


# ====================================================================== dump 모드(v0.12.1 esl_strain_fallback.md §4 C1·C2)
def _dump_series(m, F=9, L=3, seed=4):
    """진동하는 층별 순간 텐서(마지막 프레임 < 최대). 반환 t, u, inst(F,E,L,3) 텐서 규약."""
    rng = np.random.default_rng(seed)
    t = np.arange(F) * 1e-3
    u = rng.normal(size=(F, m.node_id.size, 3)) * 0.01
    env = np.abs(np.sin(np.linspace(0.0, 2.5 * np.pi, F)))[:, None, None, None]
    inst = rng.normal(size=(F, m.elem_id.size, L, 3)) * 1e-3 * (0.2 + env)
    return t, u, inst


@pytest.mark.parametrize("eng", [False, True])
def test_c1_c2_dump_time_max_and_shear(tmp_path, eng):
    """C1: 시간 누적 최대 M = max_g≤f max_l ε_eq, t* = 최대 첫 도달, eps_eq(텐서열) == M == vm_hv, 층 최대.
    C2: 공학 전단 저장 → decide_shear factor 0.5, 공식 일치."""
    from esl.io import write_dump_csv
    m = _model(tmp_path)
    t, u, inst = _dump_series(m)
    st = inst.copy()
    if eng:
        st[..., 2] *= 2.0
    q = strain.eps_eq(inst)                                        # (F,E,L) 순간·층별
    lay_max = q.max(axis=2)
    M = np.maximum.accumulate(lay_max, axis=0)
    assert np.any(lay_max[-1] < M[-1])                             # 마지막 프레임 < 최대(순간값 가정 깨짐)
    rd = write_dump_csv(tmp_path / "d", t, m.node_id, m.x0, u, m.elem_id, st, vm_hv=q, hot_k=10, top_n=5,
                        layers=("Layer 1", "Layer 2", "Layer 3"))
    info = pack_results(rd, m, tmp_path / "o")
    sf = info["strain_fallback"]
    assert info["strain_source"] == "strain_tensor" and sf["mode"] == "dump"
    assert sf["shear"]["factor"] == (0.5 if eng else 1.0) and sf["esl_layers"] == ["bottom", "top"]
    assert any(w.startswith("STRAIN_TMAX_SAMPLED") for w in info["warnings"])
    assert any(w.startswith("H3D_NO_EPSP") for w in info["warnings"])
    h = _load(tmp_path / "o" / "history.npz")
    fac = 0.5 if eng else 1.0
    assert h["vm_hv"].shape == (9, 2)
    assert np.allclose(h["vm_hv"], M, rtol=1e-6)
    assert np.allclose(strain.eps_eq(RC.tensor_eps(h["eps"], fac)), M, rtol=1e-5)
    f = _load(tmp_path / "o" / "final.npz")
    assert np.allclose(f["vm_hv"], M[-1], rtol=1e-6)
    # t* = first-reach(M), D 의 첫 원소
    fr = tstar.first_reach(M, 1e-6)
    order = np.lexsort((np.arange(2), -M[-1]))
    assert info["candidate_frames"]["max_strain"][0] == int(fr[order[0]])
    s = _load(tmp_path / "o" / "strain_frames.npz")
    for i, fi in enumerate(s["frame_index"].tolist()):
        assert np.allclose(s["vm_hv"][i], M[fi], rtol=1e-6)
        assert np.allclose(s["prev_vm_hv"][i], M[fi - 1] if fi > 0 else 0, rtol=1e-6)
    # 같은 데이터를 max-hold 로 직접 준 경우(Python 3패스 생성기)와 D·H 가 같음
    src_l = q.argmax(axis=2)
    held_l = np.take_along_axis(st, src_l[..., None, None], 2)[:, :, 0]
    eqh, eph = max_hold(lay_max, held_l)
    d2 = write_results_csv(tmp_path / "m", t, m.node_id, m.x0, u, m.elem_id, eph, vm_hv=eqh, hot_k=10, top_n=5)
    info2 = pack_results(d2, m, tmp_path / "o2")
    assert info2["frames_D"] == info["frames_D"] and info2["candidate_frames"] == info["candidate_frames"]
    for fn in ("final.npz", "history.npz", "disp.npz"):
        a, b = _load(tmp_path / "o" / fn), _load(tmp_path / "o2" / fn)
        for k in a:
            assert np.array_equal(a[k], b[k]), (fn, k)


def test_dump_missing_rows_and_bad_layer(tmp_path):
    from esl.io import write_dump_csv
    m = _model(tmp_path)
    t, u, inst = _dump_series(m, F=4, L=2)
    rd = write_dump_csv(tmp_path / "d", t, m.node_id, m.x0, u, m.elem_id, inst)
    _drop(rd, "strain_raw.csv", lambda l: l.startswith("2,3,"))      # frame 2, 요소 3 의 두 층 모두 없음
    assert _code(pack_results, rd, m, tmp_path / "o") == "ID_MISMATCH"
    rd = write_dump_csv(tmp_path / "d2", t, m.node_id, m.x0, u, m.elem_id, inst)
    p = os.path.join(rd, "done.json")
    dj = json.load(open(p))
    dj["strain_layers"] = ["Lower"]
    json.dump(dj, open(p, "w"))
    assert _code(pack_results, rd, m, tmp_path / "o2") == "TOOL_OUTPUT_MISSING"
    # 옛 done.json(키 없음) = max_strain
    assert RC.strain_source_of({}) == "max_strain" and RC.strain_source_of({"strain_fallback": {"source": "x"}}) == "max_strain"
