"""④ 3D 하중 보기 파생 자료(esl/view3d.py) 단위 시험 — 계약 esl_3d_load.md V-L3-1~7·14 (코어 쪽).

V-L3-1 법선·Fn·면압 / V-L3-2 상위 행 / V-L3-3 군집 결정성 / V-L3-4 군집 불변식 / V-L3-5 GLB / V-L3-6 values.bin /
V-L3-7 LOD / V-L3-14 성능(perf).
"""

from __future__ import annotations

import json
import os
import struct
import sys
import time
import warnings

import numpy as np
import pytest

from esl import view3d

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from gen_view3d_fixture import FIX_CFG, OUT as FIXTURE_DIR, generate, synth_mesh  # noqa: E402


def build(tmp_path, m, name="v", **kw):
    d = str(tmp_path / name)
    cfg = {**FIX_CFG, "lod_min_nodes": 10 ** 9, **kw.pop("cfg", {})}
    man = view3d.build_view(d, node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], f=m["f"],
                            u_rel=m["u_rel"], supports=kw.pop("supports", ()), cfg=cfg, key="k", esl_run_id="r",
                            created_at="2026-01-01T00:00:00Z", **kw)
    return d, man


def brute_area(x0, conn, et):
    """느린 기준 구현: 노드 대표 면적 = Σ 요소 면적 / 절점 수."""
    a = np.zeros(x0.shape[0])
    for c, t in zip(conn, et):
        if t == 4:
            ar = 0.5 * np.linalg.norm(np.cross(x0[c[2]] - x0[c[0]], x0[c[3]] - x0[c[1]]))
            for v in c:
                a[v] += ar / 4
        else:
            ar = 0.5 * np.linalg.norm(np.cross(x0[c[1]] - x0[c[0]], x0[c[2]] - x0[c[0]]))
            for v in c[:3]:
                a[v] += ar / 3
    return a


# ---------------------------------------------------------------- V-L3-1
def test_normal_fn_pressure_flat_plate_and_flipped_elements():
    m = synth_mesh(6, 5, h=2.0, tri_every=5)
    g = view3d.node_geometry(m["x0"], m["conn"], m["elem_type"])
    assert np.allclose(g.n_p, [0, 0, 1])
    assert np.abs(g.n - [0, 0, 1]).max() < 1e-12
    fn, p = view3d.face_values(m["f"], g)
    assert np.abs(fn - m["f"][:, 2]).max() < 1e-12                   # 평판: Fn = F_z
    area = brute_area(m["x0"], m["conn"], m["elem_type"])
    assert np.abs(g.area - area).max() < 1e-12
    assert np.abs(p - np.abs(m["f"][:, 2]) / area).max() < 1e-12     # 면압 = |Fn| / A
    conn = m["conn"].copy()
    conn2 = conn.copy()
    quad = np.flatnonzero(m["elem_type"] == 4)
    for k in quad[::3]:
        conn2[k] = conn[k][::-1]                                      # 일부 요소 연결 순서 반전
    tri = np.flatnonzero(m["elem_type"] == 3)
    for k in tri[::2]:
        conn2[k, :3] = conn[k, :3][::-1]
        conn2[k, 3] = conn2[k, 2]
    g2 = view3d.node_geometry(m["x0"], conn2, m["elem_type"])
    assert np.abs(g2.n - g.n).max() < 1e-12
    assert np.abs(g2.area - g.area).max() < 1e-12
    mq = synth_mesh(6, 5, h=2.0)                                      # 사각형만: 안쪽 노드 A = h²
    gq = view3d.node_geometry(mq["x0"], mq["conn"], mq["elem_type"])
    inner = (mq["x0"][:, 0] > 0) & (mq["x0"][:, 0] < 12) & (mq["x0"][:, 1] > 0) & (mq["x0"][:, 1] < 10)
    assert np.allclose(gq.area[inner], 4.0)


def test_isolated_node_uses_plate_normal_and_zero_pressure():
    m = synth_mesh(3, 3)
    x0 = np.vstack([m["x0"], [[100.0, 100.0, 0.0]]])                  # 어떤 요소에도 안 쓰이는 노드
    g = view3d.node_geometry(x0, m["conn"], m["elem_type"], n_p=np.array([0.0, 0.0, 1.0]))
    assert np.allclose(g.n[-1], [0, 0, 1]) and g.area[-1] == 0.0
    f = np.vstack([m["f"], [[1.0, 2.0, 3.0]]])
    fn, p = view3d.face_values(f, g)
    assert fn[-1] == 3.0 and p[-1] == 0.0


def test_folded_flange_normals_and_plate_normal_sign():
    m = synth_mesh(8, 4, bend=1.0)                                    # x > 중앙: 45도 접힘
    g = view3d.node_geometry(m["x0"], m["conn"], m["elem_type"])
    far = m["x0"][:, 0] > 10
    s = 1 / np.sqrt(2)
    assert np.allclose(g.n[far], [-s, 0, s], atol=1e-9)
    assert g.n_p[int(np.argmax(np.abs(g.n_p)))] > 0                   # 부호: 최대 절대 성분이 +


# ---------------------------------------------------------------- V-L3-2
def test_top_rows_order_matches_forces_endpoint_rule_with_ties():
    m = synth_mesh(5, 5)
    f = m["f"] * 0.01
    f[3] = f[10] = f[20] = [3.0, 4.0, 0.0]                             # |F| = 5 동률
    f[7] = [0.0, 0.0, 9.0]
    g = view3d.node_geometry(m["x0"], m["conn"], m["elem_type"])
    fn, p = view3d.face_values(f, g)
    nid = m["node_id"]
    sup = [int(nid[3]), int(nid[7])]
    rows = view3d.top_rows(nid, m["x0"], f, fn, p, sup, 8)
    mag = np.linalg.norm(f, axis=1)
    order = np.lexsort((nid, -mag))[:8]                                # /forces 와 같은 정렬
    assert [r["node_id"] for r in rows] == nid[order].tolist()
    assert [r["vertex"] for r in rows] == order.tolist() and [r["rank"] for r in rows] == list(range(1, 9))
    r0 = rows[0]
    assert r0["node_id"] == int(nid[7]) and r0["is_support"] is True and r0["mag"] == 9.0
    assert r0["fn"] == float(fn[7]) and r0["pa"] == float(p[7]) and r0["x"] == float(m["x0"][7, 0])
    five = [r for r in rows if r["mag"] == 5.0]
    assert [r["node_id"] for r in five] == sorted(r["node_id"] for r in five)   # 동률 node_id 오름차순
    assert sum(r["is_support"] for r in rows) == 2


# ---------------------------------------------------------------- V-L3-3
def test_clusters_deterministic_bytes_and_order_independent():
    m = synth_mesh(20, 12, seed=3, load_frac=0.7)
    a = view3d.clusters(m["node_id"], m["x0"], m["f"], m["u_rel"], 5, 50)
    b = view3d.clusters(m["node_id"], m["x0"], m["f"], m["u_rel"], 5, 50)
    assert json.dumps(a) == json.dumps(b)
    perm = np.random.default_rng(9).permutation(m["node_id"].size)
    c = view3d.clusters(m["node_id"][perm], m["x0"][perm], m["f"][perm], m["u_rel"][perm], 5, 50)
    assert json.dumps(a) == json.dumps(c)                              # 노드 순서와 무관(node_id 기준)
    assert set(a) == {"2", "3", "4", "5"}
    for k, blk in a.items():
        assert blk["k_actual"] == int(k) and [r["label"] for r in blk["rows"]] == [f"C{i + 1}" for i in range(int(k))]
        rm = [r["r_mag"] for r in blk["rows"]]
        assert rm == sorted(rm, reverse=True)                          # ‖R‖ 내림차순


def test_two_separated_blobs_split_by_blob_and_fewer_loaded_nodes():
    rng = np.random.default_rng(0)
    xa = rng.normal(size=(40, 3)) + [0, 0, 0]
    xb = rng.normal(size=(60, 3)) + [500, 0, 0]
    x = np.vstack([xa, xb])
    f = rng.normal(size=(100, 3))
    nid = np.arange(1, 101)
    cl = view3d.clusters(nid, x, f, np.zeros((100, 3)), 2, 50)["2"]
    assert cl["k_actual"] == 2
    assert sorted(r["n_nodes"] for r in cl["rows"]) == [40, 60]
    assert sorted(r["min_node_id"] for r in cl["rows"]) == [1, 41]
    # 하중 노드 < K → k_actual 감소
    f2 = np.zeros((100, 3))
    f2[[4, 70, 71]] = rng.normal(size=(3, 3))
    c5 = view3d.clusters(nid, x, f2, np.zeros((100, 3)), 5, 50)
    assert [c5[k]["k_actual"] for k in "2345"] == [2, 3, 3, 3]
    f3 = np.zeros((100, 3))
    f3[5] = [1, 0, 0]
    c1 = view3d.clusters(nid, x, f3, np.zeros((100, 3)), 3, 50)
    assert c1["2"]["k_actual"] == 1 and c1["2"]["rows"][0]["cancel"] == 0.0
    cz = view3d.clusters(nid, x, np.zeros((100, 3)), np.zeros((100, 3)), 3, 50)
    assert cz["2"] == {"k_actual": 0, "rows": []}


def test_kmeans_reseeds_empty_cluster_and_coincident_points_reduce_k():
    rng = np.random.default_rng(2)
    x = np.vstack([rng.normal(size=(30, 3)), rng.normal(size=(30, 3)) + [100, 0, 0]])
    w = rng.random(60) + 0.5
    init = np.array([[0.0, 0, 0], [100.0, 0, 0], [1e6, 1e6, 1e6]])      # 세 번째 중심은 아무도 안 가짐 → 빈 군집
    labels, centers, ka = view3d.kmeans_weighted(x, w, 3, 50, init=init)
    assert ka == 3 and np.bincount(labels, minlength=3).min() > 0      # 재심기로 채움
    xs = np.vstack([np.zeros((5, 3)), np.ones((5, 3))])
    labels, centers, ka = view3d.kmeans_weighted(xs, np.ones(10), 4, 50)
    assert ka == 2                                                     # 서로 다른 점이 2곳뿐 → 군집 수 감소


# ---------------------------------------------------------------- V-L3-4
@pytest.mark.parametrize("load_frac", [1.0, 0.4])
def test_cluster_invariants(load_frac):
    m = synth_mesh(18, 11, bend=0.3, tri_every=6, seed=5, load_frac=load_frac)
    nid, x, f, u = m["node_id"], m["x0"], m["f"], m["u_rel"]
    c0 = x.mean(axis=0)
    sum_f = f.sum(axis=0)
    sum_m = np.cross(x - c0, f).sum(axis=0)
    mag = np.linalg.norm(f, axis=1)
    cl = view3d.clusters(nid, x, f, u, 5, 50)
    for k, blk in cl.items():
        rows = blk["rows"]
        R = np.array([r["r"] for r in rows])
        assert np.abs(R.sum(axis=0) - sum_f).max() <= 1e-9 * max(1.0, np.abs(sum_f).max(), mag.sum())
        tot = sum(np.cross(np.array(r["center"]) - c0, r["r"]) + np.array(r["m"]) for r in rows)
        assert np.abs(tot - sum_m).max() <= 1e-9 * max(1.0, mag.sum() * 50)
        assert sum(r["n_nodes"] for r in rows) == int(np.count_nonzero(mag))
        for r in rows:
            assert 0.0 <= r["cancel"] <= 1.0 + 1e-12
            assert r["r_mag"] <= r["sum_abs"] + 1e-9
    # c_k = |F| 가중 하중 중심 (K=2 표 확인): 전체 가중 중심 = 군집 가중 중심의 Σ|F| 가중 평균
    rows = cl["2"]["rows"]
    wc = sum(np.array(r["center"]) * r["sum_abs"] for r in rows) / sum(r["sum_abs"] for r in rows)
    assert np.allclose(wc, (mag[:, None] * x).sum(axis=0) / mag.sum(), atol=1e-9)


# ---------------------------------------------------------------- V-L3-5
def test_glb_structure_quantization_and_node_id(tmp_path):
    m = synth_mesh(9, 6, bend=0.5, tri_every=4, seed=11)
    d, man = build(tmp_path, m)
    path = os.path.join(d, "part.glb")
    raw = open(path, "rb").read()
    magic, ver, total = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF" and ver == 2 and total == len(raw) == man["geometry"]["bytes"]
    jl, jt = struct.unpack_from("<I4s", raw, 12)
    assert jt == b"JSON" and jl % 4 == 0 and total % 4 == 0
    bl, bt = struct.unpack_from("<I4s", raw, 20 + jl)
    assert bt == b"BIN\x00" and bl % 4 == 0 and 20 + jl + 8 + bl == total
    js, binb = view3d.read_glb(path)
    assert js["asset"]["version"] == "2.0" and js["asset"]["extras"]["units"] == "mm" and js["asset"]["extras"]["up"] == "Z"
    assert js["extensionsRequired"] == ["KHR_mesh_quantization"] == js["extensionsUsed"]
    assert js["buffers"][0]["byteLength"] == len(binb) or js["buffers"][0]["byteLength"] <= len(binb)
    n = m["node_id"].size
    n_tris = 2 * int((m["elem_type"] == 4).sum()) + int((m["elem_type"] == 3).sum())
    assert man["n_tris"] == n_tris and man["n_elems"] == m["conn"].shape[0]
    pa, ia = js["accessors"][0], js["accessors"][2]
    assert pa["componentType"] == 5122 and pa["normalized"] is True and pa["count"] == n and pa["type"] == "VEC3"
    assert ia["count"] == 3 * n_tris and ia["componentType"] == 5125
    bv = js["bufferViews"]
    assert bv[0]["byteStride"] == 8 and all(b["byteOffset"] % 4 == 0 for b in bv)
    pos = np.frombuffer(binb, "<i2", count=n * 4).reshape(n, 4)
    assert (pos[:, 3] == 0).all()
    assert pa["min"] == pos[:, :3].min(axis=0).tolist() and pa["max"] == pos[:, :3].max(axis=0).tolist()
    node = js["nodes"][0]
    lo, hi = m["x0"].min(axis=0), m["x0"].max(axis=0)
    assert np.allclose(node["translation"], (lo + hi) / 2) and np.allclose(node["scale"], (hi - lo) / 2)
    xr = np.asarray(node["translation"]) + np.asarray(node["scale"]) * pos[:, :3] / 32767.0
    bound = (hi - lo) / 65534.0 / 2 + 1e-12                             # 축별 bbox 길이/65534/2
    assert (np.abs(xr - m["x0"]) <= bound).all()
    off = bv[1]["byteOffset"]
    nids = np.frombuffer(binb, "<u4", count=n, offset=off)
    assert np.array_equal(nids, m["node_id"].astype(np.uint32))        # _NODE_ID 왕복, 정점 i = 노드 i
    assert js["meshes"][0]["primitives"][0]["attributes"] == {"POSITION": 0, "_NODE_ID": 1}
    tris = np.frombuffer(binb, "<u4", count=3 * n_tris, offset=bv[2]["byteOffset"]).reshape(-1, 3)
    assert tris.max() < n
    assert tris[0].tolist() == m["conn"][0, :3].tolist()                  # 요소 순서 유지


def test_glb_triangulation_order_quad_and_tri():
    conn = np.array([[0, 1, 2, 3], [1, 4, 2, 2], [4, 5, 2, 2]])
    et = np.array([4, 3, 3])
    t = view3d.triangulate(conn, et)
    assert t.tolist() == [[0, 1, 2], [0, 2, 3], [1, 4, 2], [4, 5, 2]] and t.dtype == np.uint32


def test_glb_degenerate_axis_scale_one(tmp_path):
    m = synth_mesh(3, 3)                                               # 평판: z 반축 = 0
    d, man = build(tmp_path, m)
    js, binb = view3d.read_glb(os.path.join(d, "part.glb"))
    assert js["nodes"][0]["scale"][2] == 1.0
    pos = np.frombuffer(binb, "<i2", count=m["node_id"].size * 4).reshape(-1, 4)
    assert (pos[:, 2] == 0).all()


# ---------------------------------------------------------------- V-L3-6
def test_values_bin_alignment_error_and_zero_arrays(tmp_path):
    m = synth_mesh(10, 8, bend=0.2, seed=4)
    d, man = build(tmp_path, m)
    buf = open(os.path.join(d, "values.bin"), "rb").read()
    arrays = man["values"]["arrays"]
    assert [a["key"] for a in arrays] == ["pa", "fn", "fmag", "u"] and len(buf) == man["values"]["bytes"]
    assert all(a["offset"] % 4 == 0 for a in arrays) and len(buf) % 4 == 0
    n = m["node_id"].size
    v = view3d.unpack_values(buf, arrays, n)
    g = view3d.node_geometry(m["x0"], m["conn"], m["elem_type"])
    fn, p = view3d.face_values(m["f"], g)
    mag = np.linalg.norm(m["f"], axis=1)
    sc = {a["key"]: np.asarray(a["scale"]) for a in arrays}
    assert np.all(np.abs(v["pa"] - p) <= sc["pa"] / 2 + 1e-15)
    assert np.all(np.abs(v["fn"] - fn) <= sc["fn"] / 2 + 1e-15)
    assert np.all(np.abs(v["fmag"] - mag) <= sc["fmag"] / 2 + 1e-15)
    assert np.all(np.abs(v["u"] - m["u_rel"]) <= sc["u"] / 2 + 1e-15)  # 성분별 s_c/2
    assert sc["pa"] == p.max() / 65535 and sc["fn"] == np.abs(fn).max() / 32767
    assert [a["comps"] for a in arrays] == [1, 1, 1, 3] and [a["dtype"] for a in arrays] == ["uint16", "int16", "uint16", "int16"]
    # 전부 0
    m0 = dict(m, f=np.zeros_like(m["f"]), u_rel=np.zeros_like(m["u_rel"]))
    d0, man0 = build(tmp_path, m0, name="zero")
    a0 = man0["values"]["arrays"]
    assert all(np.all(np.asarray(a["scale"]) == 0) for a in a0)
    z = view3d.unpack_values(open(os.path.join(d0, "values.bin"), "rb").read(), a0, n)
    assert all(not np.any(x) for x in z.values())
    assert man0["ranges"]["pa"]["p99"] is None and man0["top"][0]["mag"] == 0.0


def test_fixture_is_current_and_small():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        generate(td)
        for name in sorted(os.listdir(td)):
            assert open(os.path.join(td, name), "rb").read() == open(os.path.join(FIXTURE_DIR, name), "rb").read(), name
    assert sum(os.path.getsize(os.path.join(FIXTURE_DIR, f)) for f in os.listdir(FIXTURE_DIR)) < 100_000


# ---------------------------------------------------------------- V-L3-7
def test_lod_grid_invariants(tmp_path):
    m = synth_mesh(60, 40, bend=0.3, seed=8)
    tris = view3d.triangulate(m["conn"], m["elem_type"])
    g = view3d.node_geometry(m["x0"], m["conn"], m["elem_type"])
    _, p = view3d.face_values(m["f"], g)
    target = 300
    src, lt = view3d.lod_grid(m["x0"], tris, p, target)
    assert 0 < src.size <= 1.2 * target
    assert src.min() >= 0 and src.max() < m["x0"].shape[0] and np.unique(src).size == src.size
    assert lt.max() < src.size and lt.dtype == np.uint32
    t = lt.astype(np.int64)
    assert ((t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])).all()      # 퇴화 없음
    assert np.unique(np.sort(t, axis=1), axis=0).shape[0] == t.shape[0]                       # 중복 없음
    src2, lt2 = view3d.lod_grid(m["x0"], tris, p, target)
    assert np.array_equal(src, src2) and np.array_equal(lt, lt2)                              # 결정적
    # 셀 대표 = 면압 최대: 각 대표는 자기 셀 최댓값(셀을 다시 계산)
    lo = m["x0"].min(axis=0)
    ext = float((m["x0"].max(axis=0) - lo).max())
    found = False
    for h in np.geomspace(ext / 4096, ext, 400):
        cell = view3d._cells(m["x0"], lo, float(h))
        if np.unique(cell).size == src.size and np.unique(cell[src]).size == src.size:
            for s_ in src:
                mem = np.flatnonzero(cell == cell[s_])
                assert p[s_] == p[mem].max()
            found = True
            break
    assert found


def test_build_lod_only_above_threshold_and_src_valid(tmp_path):
    m = synth_mesh(30, 20, seed=2)
    n = m["node_id"].size
    d, man = build(tmp_path, m, name="nolod", cfg={"lod_min_nodes": n})            # N ≤ min → 없음
    assert man["lod"] is None and not os.path.exists(os.path.join(d, "part_lod.glb"))
    d, man = build(tmp_path, m, name="lod", cfg={"lod_min_nodes": n - 1, "lod_target_vertices": 100})
    lod = man["lod"]
    assert lod["name"] == "part_lod.glb" and lod["bytes"] == os.path.getsize(os.path.join(d, "part_lod.glb"))
    js, binb = view3d.read_glb(os.path.join(d, "part_lod.glb"))
    mcount = lod["n_vertices"]
    assert js["meshes"][0]["primitives"][0]["attributes"] == {"POSITION": 0, "_SRC": 1} and mcount <= 120
    off = js["bufferViews"][1]["byteOffset"]
    s = np.frombuffer(binb, "<u4", count=mcount, offset=off)
    assert s.max() < n and np.unique(s).size == mcount
    pos = np.frombuffer(binb, "<i2", count=mcount * 4).reshape(-1, 4)[:, :3]
    pos_full = np.frombuffer(view3d.read_glb(os.path.join(d, "part.glb"))[1], "<i2", count=n * 4).reshape(-1, 4)[:, :3]
    assert np.array_equal(pos, pos_full[s])                                          # 양자화·좌표 동일(원 노드 위치)


# ---------------------------------------------------------------- manifest 전체
def test_manifest_contents_and_determinism(tmp_path):
    m = synth_mesh(14, 9, bend=0.3, tri_every=5, seed=6)
    sup = [{"node_id": int(m["node_id"][2]), "dof": "123"}, {"node_id": int(m["node_id"][9]), "dof": "13"},
           {"node_id": 99999999, "dof": "3"}]                                       # 모델에 없는 지지 노드는 건너뜀
    d1, a = build(tmp_path, m, name="a", supports=sup)
    d2, b = build(tmp_path, m, name="b", supports=sup)
    assert open(os.path.join(d1, "manifest.json"), "rb").read() == open(os.path.join(d2, "manifest.json"), "rb").read()
    for f in ("part.glb", "values.bin"):
        assert open(os.path.join(d1, f), "rb").read() == open(os.path.join(d2, f), "rb").read()
    assert a["schema"] == "esl/view3d/1" and a["builder_version"] == view3d.BUILDER_VERSION == 1
    assert a["units"] == "mm" and a["pressure_unit"] == "MPa" and a["up"] == "Z" and a["lod"] is None
    assert [s["node_id"] for s in a["supports"]] == [int(m["node_id"][2]), int(m["node_id"][9])]
    assert [s["vertex"] for s in a["supports"]] == [2, 9] and a["supports"][1]["dof"] == "13"
    assert len(a["top"]) == 100 or len(a["top"]) == m["node_id"].size
    assert np.allclose(a["sum_f"], m["f"].sum(axis=0))
    c0 = m["x0"].mean(axis=0)
    assert np.allclose(a["sum_m"], np.cross(m["x0"] - c0, m["f"]).sum(axis=0)) and np.allclose(a["moment_center"], c0)
    pr = a["ranges"]["pa"]
    assert 0 < pr["p99"] <= pr["max"] * 1.1 and a["ranges"]["u_max"] == float(np.linalg.norm(m["u_rel"], axis=1).max())
    assert a["bbox"]["diag"] == pytest.approx(float(np.linalg.norm(m["x0"].max(0) - m["x0"].min(0))))
    json.dumps(a, allow_nan=False)


def test_build_rejects_inconsistent_or_nonfinite(tmp_path):
    from esl.errors import EslError

    m = synth_mesh(3, 3)
    bad = dict(m, f=m["f"][:-1])
    with pytest.raises(EslError):
        build(tmp_path, bad)
    f = m["f"].copy()
    f[0, 0] = np.nan
    with pytest.raises(EslError):
        build(tmp_path, dict(m, f=f), name="nan")


# ---------------------------------------------------------------- V-L3-14
@pytest.mark.perf
def test_perf_300k_nodes(tmp_path):
    m = synth_mesh(547, 547, seed=1)                                               # 548² = 300,304 노드
    assert m["node_id"].size > 300_000
    t = time.perf_counter()
    d, man = build(tmp_path, m, cfg={"lod_min_nodes": 500_000})
    dt = time.perf_counter() - t
    sizes = {f: os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)}
    print(f"[perf] view3d 300k nodes: {dt:.2f}s, bytes {sizes}")
    if dt > 3.0:
        warnings.warn(f"view3d 30만 노드 생성 {dt:.2f}s > 목표 3 s (이 환경 측정값, 기록용)", stacklevel=1)
    assert dt < 12.0
    assert sizes["part.glb"] < 14_000_000
