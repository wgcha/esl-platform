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


# ---------------------------------------------------------------- v0.24.9 통합 INT-1(계약 §10.2 통합 보정): 한 함수 support_rows
@pytest.mark.parametrize("method", sorted(jig_bc.METHODS))
def test_support_rows_is_the_one_format(method):
    """백엔드 Case 3D·스터디 사이드카 공통 행 = support_rows(npz 배열 매핑, 출처 키). 방식별 kind 가 BC 배열과 맞고(스프링 tie = 법선
    스프링 {k[], g[]}·구속 행 없음, 받침점 = 면내 1·2 방향), 모든 방식이 tie '123' 세 방향 고정으로 보이던 v0.24.8 표식으로 돌아가지 않음."""
    X, tie, aux, u = _world()
    row = jig_bc.METHODS[method]
    BC = jig_bc.build_bc(row, tie, aux, u, k=np.full(tie["node"].size, 5.0) if row["tie_stiff"] == "spring" else None)
    z = {k: np.asarray(v) for k, v in jig_bc.save_bc(BC).items()}
    nid = np.arange(1000, 1060)
    rows = jig_bc.support_rows(z, X, 64, nid, row["src"])
    assert rows == jig_bc.mark_rows(jig_bc.support_marks_full(BC, X, 64, row), nid)
    assert jig_bc.method_row_of(row["src"]) is row and jig_bc.method_row_of(None) is None and jig_bc.method_row_of("full") is None
    json.dumps(rows)
    ties = [r for r in rows if r["kind"] != "aux_inplane"]
    want = {"fixed": "tie_fixed", "prescribed": "tie_disp", "spring": "tie_spring"}[method]
    assert {r["kind"] for r in ties} == {want}
    for r in ties:
        assert 1 <= len(r["dirs"]) <= 2                                            # normal: 법선 1(꺾임 2) — 세 축 고정 아님
        if want == "tie_spring":
            assert set(r["val"]) == {"k", "g"} and len(r["val"]["k"]) == len(r["val"]["g"]) == len(r["dirs"])
            i = int(r["node_id"]) - 1000
            assert not np.any((BC["bc_node"] == i) & (BC["bc_kind"] == jig_bc.KIND_TIE))
        elif want == "tie_fixed":
            assert r["val"] == 0.0
        else:
            assert isinstance(r["val"], list) and len(r["val"]) == len(r["dirs"])
    for r in (r for r in rows if r["kind"] == "aux_inplane"):
        assert len(r["dirs"]) in (1, 2) and all(abs(d[2]) < 1e-9 for d in r["dirs"])  # 면내(판 z = 0)
    # 옛 npz(bc_dir·bc_val 없음) = 옛 {node_id, dof} 만(바이트 불변)
    old = {k: z[k] for k in ("bc_node", "bc_kind", "sp_node")}
    assert jig_bc.support_rows(old, X, 64, nid, row["src"]) == \
        [{"node_id": int(nid[i]), "dof": d} for i, d in _old_support_marks(z["bc_node"], z["bc_kind"], z["sp_node"], X, 64)]
