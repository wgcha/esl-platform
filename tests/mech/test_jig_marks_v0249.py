"""V-0249-BM-1·2(계약 esl_bead_pos_u.md §10.4): 지그 3D 지지 표식 일반형 [(노드, kind, dirs, val)] — 세 방식 × tie_dofs ×
꺾임 노드에서 kind·dirs·val 이 BC 배열과 일치, 옛 2튜플 어댑터 = v0.24.8 규칙(바이트), 사이드카 행에 kind·dirs·val 추가·dof 불변."""
from __future__ import annotations

import json

import numpy as np
import pytest

from esl.doe import jig
from esl.mech import jig_bc


def _world():
    rng = np.random.default_rng(3)
    X = np.c_[rng.uniform(0, 300, 60), rng.uniform(0, 200, 60), np.zeros(60)]
    tn = np.array([3, 7, 11, 11, 20, 31])               # 11 = 꺾임 노드(방향 2개)
    td = np.array([[0, 0, 1.0], [0, 0, 1.0], [0, 0, 1.0], [0.6, 0, 0.8], [0, 0, 1.0], [0, 0, 1.0]])
    td /= np.linalg.norm(td, axis=1)[:, None]
    an = np.array([40, 40, 41])
    ad = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0]])
    u = rng.normal(size=(60, 3))
    return X, {"node": tn, "dir": td}, {"node": an, "dir": ad}, u


def _old_support_marks(bc_node, bc_kind, sp_node, x0, smax):
    """v0.24.8 support_marks 본문(시험 쪽 사본 — 어댑터 바이트 대조)."""
    n = int(np.asarray(x0).shape[0])
    bn = np.asarray(bc_node, dtype=np.int64).reshape(-1)
    bk = np.asarray(bc_kind).astype(np.int64).reshape(-1)
    sp = np.asarray(sp_node, dtype=np.int64).reshape(-1)
    ok = (bn >= 0) & (bn < n)
    tie = jig.support_sample(x0, np.unique(np.r_[bn[ok & (bk == jig_bc.KIND_TIE)], sp[(sp >= 0) & (sp < n)]]), int(smax))
    shown = set(int(i) for i in tie.tolist())
    aux = [int(i) for i in np.unique(bn[ok & (bk == jig_bc.KIND_AUX)]).tolist() if int(i) not in shown]
    return [(int(i), "123") for i in tie.tolist()] + [(i, "ij") for i in aux]


@pytest.mark.parametrize("method", sorted(jig_bc.METHODS))
@pytest.mark.parametrize("smax", [64, 3])
def test_marks_full_match_bc(method, smax):
    X, tie, aux, u = _world()
    row = jig_bc.METHODS[method]
    k = np.full(tie["node"].size, 5.0) if row["tie_stiff"] == "spring" else None
    BC = jig_bc.build_bc(row, tie, aux, u, k=k)
    full = jig_bc.support_marks_full(BC, X, smax, row)
    old = jig_bc.support_marks(BC["bc_node"], BC["bc_kind"], BC["sp_node"], X, smax)
    assert old == _old_support_marks(BC["bc_node"], BC["bc_kind"], BC["sp_node"], X, smax)   # 어댑터 = v0.24.8
    assert [(i, jig_bc.mark_dof(kd)) for i, kd, _d, _v in full] == old                          # 노드·순서·dof 같음
    want = "tie_spring" if row["tie_stiff"] == "spring" else ("tie_fixed" if row["tie_value"] == "zero" else "tie_disp")
    for i, kd, dirs, val in full:
        if kd == "aux_inplane":
            r = np.flatnonzero((BC["bc_node"] == i) & (BC["bc_kind"] == jig_bc.KIND_AUX))
            assert np.allclose(dirs, BC["bc_dir"][r], atol=1e-6) and np.allclose(val, BC["bc_val"][r], atol=1e-6)
            continue
        assert kd == want
        if kd == "tie_spring":
            r = np.flatnonzero(BC["sp_node"] == i)
            assert np.allclose(dirs, BC["sp_dir"][r], atol=1e-6)
            assert np.allclose(val["k"], BC["sp_k"][r]) and np.allclose(val["g"], BC["sp_g"][r], atol=1e-6)
        else:
            r = np.flatnonzero((BC["bc_node"] == i) & (BC["bc_kind"] == jig_bc.KIND_TIE))
            assert np.allclose(dirs, BC["bc_dir"][r], atol=1e-6)
            if kd == "tie_fixed":
                assert val == 0.0
            else:
                assert np.allclose(val, BC["bc_val"][r], atol=1e-6)
        if i == 11:
            assert len(dirs) == 2                                                           # 꺾임 노드 = 방향 2개
    json.dumps(full)                                                                        # JSON 직렬화 가능
    kw = jig_bc.support_marks(BC["bc_node"], BC["bc_kind"], BC["sp_node"], X, smax, bc_dir=BC["bc_dir"],
                              bc_val=BC["bc_val"], sp_dir=BC["sp_dir"], sp_k=BC["sp_k"], sp_g=BC["sp_g"], method_row=row)
    assert kw == full                                                                       # 키워드 일반형 = full(백엔드 경로)
    if row["tie_value"] == "zero" or row["tie_stiff"] == "spring":
        nr = jig_bc.support_marks(BC["bc_node"], BC["bc_kind"], BC["sp_node"], X, smax, bc_dir=BC["bc_dir"],
                                  bc_val=BC["bc_val"], sp_dir=BC["sp_dir"], sp_k=BC["sp_k"], sp_g=BC["sp_g"])
        assert nr == full                                                                   # method 없이도(값 0 = 고정)


@pytest.mark.parametrize("dofs", sorted(jig_bc.TIE_DOFS))
def test_marks_tie_dofs(dofs):
    """tie_dofs normal(법선 1행) · translation(xyz 3행) — dirs 개수 = 그 노드 행 수."""
    X, tie, aux, u = _world()
    if dofs == "translation":
        tn = np.repeat(tie["node"][:3], 3)
        td = np.tile(np.eye(3), (3, 1))
        tie = {"node": tn, "dir": td}
        aux = {"node": np.zeros(0, np.int64), "dir": np.zeros((0, 3))}
    BC = jig_bc.build_bc(jig_bc.METHODS["fixed"], tie, aux, u)
    full = jig_bc.support_marks_full(BC, X, 64, jig_bc.METHODS["fixed"])
    for i, _kd, dirs, _v in full:
        assert len(dirs) == int(((BC["bc_node"] == i) & (BC["bc_kind"] == jig_bc.KIND_TIE)).sum()) or _kd == "aux_inplane"


def test_mark_rows_and_view3d_fields(tmp_path):
    """V-0249-BM-2: 사이드카 행 = 기존 dof + kind·dirs·val, build_view manifest supports 에 그대로(옛 행 = 키 없음)."""
    from esl.view3d import build_view
    X, tie, aux, u = _world()
    BC = jig_bc.build_bc(jig_bc.METHODS["spring"], tie, aux, u, k=np.full(tie["node"].size, 2.0))
    nid = np.arange(101, 161)
    rows = jig_bc.mark_rows(jig_bc.support_marks_full(BC, X, 64, jig_bc.METHODS["spring"]), nid)
    assert {r["dof"] for r in rows} <= {"123", "ij"} and all({"kind", "dirs", "val"} <= set(r) for r in rows)
    conn = np.array([[0, 1, 2, -1], [2, 3, 4, -1]])
    old = [{"node_id": int(nid[i]), "dof": d} for i, d in jig_bc.support_marks(BC["bc_node"], BC["bc_kind"],
                                                                               BC["sp_node"], X, 64)]
    m_new = build_view(str(tmp_path / "n"), node_id=nid, x0=X, conn=conn, elem_type=np.array([3, 3]),
                       f=np.zeros((60, 3)), u_rel=np.zeros((60, 3)), supports=rows, created_at="x")
    m_old = build_view(str(tmp_path / "o"), node_id=nid, x0=X, conn=conn, elem_type=np.array([3, 3]),
                       f=np.zeros((60, 3)), u_rel=np.zeros((60, 3)), supports=old, created_at="x")
    strip = [{k: v for k, v in r.items() if k not in ("kind", "dirs", "val")} for r in m_new["supports"]]
    assert strip == m_old["supports"]                                                       # 기존 필드·수·순서 불변
    assert all("kind" not in r for r in m_old["supports"])
    assert {r["kind"] for r in m_new["supports"]} <= set(jig_bc.MARK_KINDS)


def test_support321_rows():
    r = jig_bc.support321_rows([{"node_id": 5, "dof": "123"}])
    assert r == [{"node_id": 5, "dof": "123", "kind": "support321", "dirs": None, "val": None}]
