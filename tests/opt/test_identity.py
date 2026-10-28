"""V-OR-2 (코어): topo_sha256 · S1 동일성 — 같음 / 노드 ID 다름 / 연결 다름 / 회전·반전 동치 / 좌표 큰 이동,
CaseTarget 의 MODEL_MISMATCH·PREREQUISITE_MISSING, 등록 메타 topo_sha256(지연 백필과 같은 함수)."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.opt import identity
from esl.opt import target as tg
from esl.rad import write_rad

TOL = 0.005


def test_topo_same_and_order_invariant():
    m = so.plate(6, 4)
    h = identity.topo_sha256(m)
    # 노드·요소 순서를 섞고 쿼드 연결을 회전·반전해도 같은 topo
    rng = np.random.default_rng(1)
    pn = rng.permutation(m["node_id"].size)
    inv = np.argsort(pn)
    pe = rng.permutation(m["elem_id"].size)
    c = inv[m["conn"]]
    c[:, :] = c[:, [1, 2, 3, 0]]
    c[::2] = c[::2][:, [0, 3, 2, 1]]
    m2 = {**m, "node_id": m["node_id"][pn], "x0": m["x0"][pn] + 0.3, "elem_id": m["elem_id"][pe], "conn": c[pe],
          "elem_type": m["elem_type"][pe]}
    assert identity.topo_sha256(m2) == h                  # 좌표 제외
    r = identity.same_model(m, m2, TOL)
    assert r["same"] and r["topo_equal"]


def test_node_ids_connectivity_coords_mismatch():
    m = so.plate(6, 4)
    other = so.plate(6, 4, node_base=1000)
    r = identity.same_model(m, other, TOL)
    assert not r["same"] and r["reason"] == "NODE_IDS"
    c = m["conn"].copy()
    c[0, :] = c[1, :]
    r = identity.same_model(m, {**m, "conn": c}, TOL)
    assert r["reason"] == "CONNECTIVITY"
    assert identity.topo_sha256({**m, "conn": c}) != identity.topo_sha256(m)
    # 강체 운동은 같음, 큰 형상 변화는 COORDS
    th = np.radians(30)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    assert identity.same_model(m, {**m, "x0": m["x0"] @ R.T + 50}, TOL)["same"]
    X = m["x0"].copy()
    X[:, 1] += 20.0 * np.sin(np.pi * X[:, 0] / 300.0)     # 휨(강체 아님)
    r = identity.same_model(m, {**m, "x0": X}, TOL)
    assert r["reason"] == "COORDS"
    rows = identity.check_entries(m, [("E1", m), ("E2", other)], TOL)
    with pytest.raises(EslError) as ei:
        identity.assert_same(rows)
    assert ei.value.code == "MODEL_MISMATCH" and "E2" in ei.value.message


def _rad(tmp_path, m):
    ids = np.where(m["conn"] >= 0, m["node_id"][np.maximum(m["conn"], 0)], 0)
    p = str(tmp_path / "case.rad")
    write_rad(p, m["node_id"], m["x0"], m["elem_id"], m["elem_type"], ids, 7, "chassis_rear", 10, 1.5, 1,
              so.E_STEEL, so.NU, extra_parts=1)
    return p


def test_case_target_reads_rad_in_place(tmp_path):
    m = so.plate(8, 5)
    sup = so.supports_321(m)
    e = so.FakeEntry("E1", m, so.load(m), sup)
    p = _rad(tmp_path, m)
    before = sorted(x.name for x in tmp_path.iterdir())
    st = (tmp_path / "case.rad").stat().st_mtime_ns
    t = tg.case_target(p, "chassis_rear", e.meta, e.raw, coord_tol_rel=TOL)
    assert t.scenario == "S1" and t.n_elems == m["elem_id"].size and t.supports == sup
    assert t.topo_sha256 == identity.topo_sha256(m)
    assert t.source["rad"]["sha256"] and t.source["identity"][0]["same_model"]
    assert sorted(x.name for x in tmp_path.iterdir()) == before and (tmp_path / "case.rad").stat().st_mtime_ns == st
    # 다른 모델 ESL → MODEL_MISMATCH
    other = so.FakeEntry("E9", so.plate(8, 5, node_base=500), so.load(so.plate(8, 5, node_base=500)),
                         so.supports_321(so.plate(8, 5, node_base=500)))
    with pytest.raises(EslError) as ei:
        tg.case_target(p, "chassis_rear", e.meta, e.raw, coord_tol_rel=TOL, others=[("E9", other.raw)])
    assert ei.value.code == "MODEL_MISMATCH"
    with pytest.raises(EslError) as ei:
        tg.case_target(str(tmp_path / "nope.rad"), "chassis_rear", e.meta, e.raw, coord_tol_rel=TOL)
    assert ei.value.code == "PREREQUISITE_MISSING"


def test_case_target_opposite_normals_warn_only(tmp_path):
    m = so.plate(8, 5)
    c = m["conn"].copy()
    c[:3] = c[:3][:, [0, 3, 2, 1]]
    m2 = {**m, "conn": c}
    sup = so.supports_321(m2)
    e = so.FakeEntry("E1", m2, so.load(m2), sup)
    t = tg.case_target(_rad(tmp_path, m2), "chassis_rear", e.meta, e.raw, coord_tol_rel=TOL)
    assert t.normals["normals_opposite"] == 3 and t.normals["mode"] == "kept"
    assert any("반대" in w for w in t.warnings)
    # 원 연결 유지
    assert np.array_equal(identity.conn_ids(t.mesh)[:3], identity.conn_ids(m2)[:3])


def test_entry_meta_topo_and_mode_same_function():
    from esl.library.entry import opt_meta
    m = so.plate(8, 5)
    e = so.FakeEntry("E1", m, so.load(m, "bend"), so.supports_321(m))
    topo, dm = opt_meta(e.raw, e.meta["frame"])
    assert topo == identity.topo_sha256(m)
    assert dm["auto"] == "bend" and dm["user"] is None and dm["rule_version"] == 1
