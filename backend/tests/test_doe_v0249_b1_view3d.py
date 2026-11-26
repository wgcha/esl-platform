"""v0.24.9 B1 — Case 3D 지그 경계조건 표식 방식별 자료(계약 esl_bead_pos_u.md §10.2·§10.4-1~3, V-0249-BM-1~3의 백엔드 부분).

- 어댑터 ``view3d.jig_marks_general`` : 세 방식(fixed·prescribed·spring) × tie_dofs(normal·translation) × 꺾임 노드 → kind·dirs·val 이
  BC 배열(`esl.mech.jig_bc.build_bc` 결과)과 일치, 샘플·순서 = 옛 2튜플 규칙(코어 `support_marks`) 그대로.
- 코어 ``support_marks`` 일반형이 생기면(4튜플) 어댑터와 같은 결과 — 옛 2튜플이면 (노드, dof) 가 어댑터와 같음(어댑터가 대체).
- Case 3D 엔드포인트: manifest.supports 에 kind·dirs·val 실재, 기존 ``dof`` 값·표식 수·샘플 순서 불변, 옛 npz(bc_dir 없음) = kind 없음.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from esl_test_support import API  # noqa: F401
from test_jig_case_api import (  # noqa: F401 - 픽스처·도우미 재사용
    JIG_KEYS,
    R,
    _esl,
    add_jig,
    jig_plan,
    mk,
    seed,
    set_forces,
    world,
)

KIND_TIE, KIND_AUX = 1, 2


def _plate(n=10):
    """n×n 격자 x0(판 z=0) — 최원점 샘플이 의미 있게."""
    g = np.stack(np.meshgrid(np.arange(n, dtype=float), np.arange(n, dtype=float)), -1).reshape(-1, 2)
    return np.c_[g * 10.0, np.zeros(g.shape[0])]


def _bc(method: str, tie_dofs: str):
    """방식 × tie_dofs 합성 BC — tie 노드 0..11 중 3 개는 꺾임(법선 2개 = 행 2개), aux 노드 3 개(면내 2·1·1 방향 → 행 4개)."""
    from esl.mech import jig_bc as jb

    nodes = list(range(0, 12))
    kink = {2, 5, 9}
    tn, td = [], []
    nz = np.array([0.0, 0.0, 1.0])
    tilt = np.array([np.sin(0.4), 0.0, np.cos(0.4)])
    for i in nodes:
        if tie_dofs == "translation":
            for d in np.eye(3):
                tn.append(i)
                td.append(d)
        else:
            tn.append(i)
            td.append(nz)
            if i in kink:
                tn.append(i)
                td.append(tilt)
    an = [40, 40, 55, 77]
    ad = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])]
    rng = np.random.default_rng(3)
    u_tgt = rng.normal(size=(100, 3)) * 0.1
    row = jb.METHODS[method]
    k = None if row["tie_stiff"] == "hard" else np.full(len(tn), 12.5)
    bc = jb.build_bc(row, {"node": np.array(tn), "dir": np.array(td)}, {"node": np.array(an), "dir": np.array(ad)}, u_tgt, k=k)
    return bc, u_tgt


@pytest.mark.parametrize("method", ["fixed", "prescribed", "spring"])
@pytest.mark.parametrize("tie_dofs", ["normal", "translation"])
def test_marks_general_matches_bc_arrays(method, tie_dofs):
    from esl_platform.api.services import view3d as v

    x0 = _plate()
    bc, _ = _bc(method, tie_dofs)
    marks = v.jig_marks_general(bc, x0, 64)
    old = _old_marks(bc, x0, 64)
    assert [(i, "123" if k != "aux_inplane" else "ij") for i, k, _d, _v in marks] == old        # 표식 수·샘플 순서·dof 옛 규칙 그대로
    bn, bd, bv, bk = bc["bc_node"], bc["bc_dir"], bc["bc_val"], bc["bc_kind"]
    for i, kind, dirs, val in marks:
        if kind == "aux_inplane":
            rows = np.flatnonzero((bn == i) & (bk == KIND_AUX))
            assert dirs == [bd[r].tolist() for r in rows] and val == [float(bv[r]) for r in rows]
            continue
        if method == "spring":
            rows = np.flatnonzero(bc["sp_node"] == i)
            assert kind == "tie_spring" and dirs == [bc["sp_dir"][r].tolist() for r in rows]
            assert val == {"k": [float(bc["sp_k"][r]) for r in rows], "g": [float(bc["sp_g"][r]) for r in rows]}
        else:
            rows = np.flatnonzero((bn == i) & (bk == KIND_TIE))
            assert dirs == [bd[r].tolist() for r in rows]
            if method == "fixed":
                assert kind == "tie_fixed" and val == 0.0
            else:
                assert kind == "tie_disp" and val == [float(bv[r]) for r in rows]
    # 꺾임 노드(normal) = 법선 2개, translation = 방향 3개
    by = {i: d for i, k, d, _ in marks if k != "aux_inplane"}
    if tie_dofs == "normal":
        assert {len(by[i]) for i in (2, 5, 9)} == {2} and {len(by[i]) for i in (0, 1, 3)} == {1}
    else:
        assert {len(d) for d in by.values()} == {3}
    aux = {i: d for i, k, d, _ in marks if k == "aux_inplane"}
    assert sorted(aux) == [40, 55, 77] and len(aux[40]) == 2 and len(aux[55]) == 1               # 면내 방향 2 또는 1


def _old_marks(bc, x0, smax):
    """옛 2튜플 [(노드, dof)] — 코어 함수가 옛 2튜플이면 그 결과, 일반형이면 같은 의미로 환산(표식 수·순서·dof 비교용)."""
    from esl.mech import jig_bc as jb

    r = jb.support_marks(bc["bc_node"], bc["bc_kind"], bc["sp_node"], x0, smax)
    return [(int(t[0]), t[1] if len(t) == 2 else ("ij" if t[1] == "aux_inplane" else "123")) for t in r]


@pytest.mark.parametrize("method", ["fixed", "prescribed", "spring"])
def test_marks_sampling_capped_and_deterministic(method):
    from esl_platform.api.services import view3d as v

    x0 = _plate(14)
    from esl.mech import jig_bc as jb

    tn = np.arange(0, 100)
    nz = np.tile([0.0, 0.0, 1.0], (tn.size, 1))
    row = jb.METHODS[method]
    bc = jb.build_bc(row, {"node": tn, "dir": nz}, {"node": np.array([150, 151, 160]), "dir": np.array([[1.0, 0, 0], [0, 1.0, 0], [1.0, 0, 0]])},
                     np.zeros((200, 3)), k=None if row["tie_stiff"] == "hard" else np.full(tn.size, 3.0))
    a = v.jig_marks_general(bc, x0, 20)
    assert a == v.jig_marks_general(bc, x0, 20)
    ties = [m for m in a if m[1] != "aux_inplane"]
    assert len(ties) == 20 and len([m for m in a if m[1] == "aux_inplane"]) == 3
    # 최원점 샘플 = 백엔드 샘플 함수(= 코어 support_sample) 결과 순서
    assert [m[0] for m in ties] == v.jig_support_sample(x0, tn, 20).tolist()
    # 샘플된 tie 와 겹치는 면내 노드는 tie 만
    bc2 = dict(bc)
    bc2["bc_node"] = np.r_[bc["bc_node"], [0]].astype(np.int64)
    bc2["bc_kind"] = np.r_[bc["bc_kind"], [KIND_AUX]].astype(np.int8)
    bc2["bc_dir"] = np.r_[bc["bc_dir"], [[1.0, 0.0, 0.0]]]
    bc2["bc_val"] = np.r_[bc["bc_val"], [0.0]]
    b = v.jig_marks_general(bc2, x0, 20)
    assert sum(1 for m in b if m[0] == 0) == 1 and [m for m in b if m[0] == 0][0][1] != "aux_inplane"
    # 범위 밖 인덱스는 무시
    bc3 = dict(bc)
    bc3["bc_node"] = np.r_[bc["bc_node"], [10 ** 9, -1]].astype(np.int64)
    bc3["bc_kind"] = np.r_[bc["bc_kind"], [KIND_TIE, KIND_AUX]].astype(np.int8)
    bc3["bc_dir"] = np.r_[bc["bc_dir"], [[0, 0, 1.0], [0, 0, 1.0]]]
    bc3["bc_val"] = np.r_[bc["bc_val"], [0.0, 0.0]]
    assert v.jig_marks_general(bc3, x0, 20) == a


@pytest.mark.parametrize("method", ["fixed", "prescribed", "spring"])
@pytest.mark.parametrize("tie_dofs", ["normal", "translation"])
def test_backend_marks_equal_core_function(method, tie_dofs):
    """V-0249-BM-3: 백엔드 표식 = 코어 ``support_marks`` 결과. 코어가 일반형(4튜플)이면 같은 값, 옛 2튜플이면 (노드, dof) 가 같음."""
    from esl.mech import jig_bc as jb
    from esl_platform.api.services import view3d as v

    x0 = _plate()
    bc, _ = _bc(method, tie_dofs)
    got = v.jig_support_marks(bc, x0, 64)
    import inspect

    ps = inspect.signature(jb.support_marks).parameters
    kw = {k: bc[k] for k in ("bc_node", "bc_kind", "sp_node", "bc_dir", "bc_val", "sp_dir", "sp_k", "sp_g") if k in ps}
    core = list(jb.support_marks(x0=x0, smax=64, **kw))
    if core and len(core[0]) == 4:                     # 코어 일반형 — 어댑터 대신 코어 결과를 그대로 부름
        assert [(i, k) for i, k, _d, _v in got] == [(int(c[0]), str(c[1])) for c in core]
        assert [np.asarray(d).tolist() for _i, _k, d, _v in got] == [np.asarray(c[2]).tolist() for c in core]
    else:                                              # 옛 2튜플 — 어댑터가 대체, 표식 노드·dof 는 코어와 같음
        assert all(len(c) == 2 for c in core)
        assert [(i, "ij" if k == "aux_inplane" else "123") for i, k, _d, _v in got] == [(int(c[0]), c[1]) for c in core]
        assert [m[:2] for m in got] == [m[:2] for m in v.jig_marks_general(bc, x0, 64)]


def test_core_generalized_function_is_called_when_present(monkeypatch):
    """코어 함수가 4튜플을 돌려주면 어댑터가 아닌 그 결과를 쓴다(합성 대역)."""
    from esl.mech import jig_bc as jb
    from esl_platform.api.services import view3d as v

    x0 = _plate()
    bc, _ = _bc("fixed", "normal")
    called = {}

    def fake(bc_node, bc_kind, sp_node, x0, smax, bc_dir=None, bc_val=None, sp_dir=None, sp_k=None, sp_g=None):
        called["n"] = called.get("n", 0) + 1
        return [(3, "tie_fixed", [[0.0, 0.0, 1.0]], 0), (7, "aux_inplane", [[1.0, 0.0, 0.0]], [0.25])]

    monkeypatch.setattr(jb, "support_marks", fake)
    assert v.jig_support_marks(bc, x0, 64) == [(3, "tie_fixed", [[0.0, 0.0, 1.0]], 0), (7, "aux_inplane", [[1.0, 0.0, 0.0]], [0.25])]
    assert called["n"] == 1
    monkeypatch.setattr(jb, "support_marks", lambda *a, **k: [(1, "123"), (2, "ij")])             # 옛 2튜플 → 어댑터
    assert v.jig_support_marks(bc, x0, 64) == v.jig_marks_general(bc, x0, 64)
    monkeypatch.setattr(jb, "support_marks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))   # 오류 → 어댑터
    assert v.jig_support_marks(bc, x0, 64) == v.jig_marks_general(bc, x0, 64)


# ================================================================ 엔드포인트 (V-0249-BM-2)
def _write_bc(seed_, key, bc, *, with_dir=True):
    """04_esl/<key>.npz 의 BC 배열을 합성 BC 로 바꿈(add_jig 가 쓴 나머지 배열은 유지)."""
    z = dict(np.load(_esl(seed_) / f"{key}.npz"))
    z.update({k: np.asarray(v) for k, v in bc.items()})
    if not with_dir:
        for k in ("bc_dir", "bc_val", "sp_dir", "sp_k", "sp_g"):
            z.pop(k, None)
    np.savez_compressed(_esl(seed_) / f"{key}.npz", **z)


def test_case_3d_supports_have_kind_dirs_val_and_dof_unchanged(mk, seed, engine, jig_plan):  # noqa: F811
    import shutil

    c = mk()
    nid = seed.m["node_id"]
    tie = np.arange(0, 30, dtype=np.int64)
    aux = np.array([90, 91, 95], dtype=np.int64)
    for i, k in enumerate(JIG_KEYS):
        add_jig(seed, k, tie=tie, aux=aux, scale=1.1 + 0.1 * i, seed_=7 + i)
    set_forces(engine, seed, **{k: {"status": "ok", "method": k} for k in JIG_KEYS})
    from esl.mech import jig_bc as jb

    meth = {"jig": "fixed", "jig_disp": "prescribed", "jig_spring": "spring"}
    nz = np.tile([0.0, 0.0, 1.0], (tie.size, 1))
    ad = np.array([[1.0, 0, 0], [0, 1.0, 0], [1.0, 0, 0]])
    rng = np.random.default_rng(5)
    for k in JIG_KEYS:
        row = jb.METHODS[meth[k]]
        bc = jb.build_bc(row, {"node": tie, "dir": nz}, {"node": aux, "dir": ad}, rng.normal(size=(nid.size, 3)) * 0.05,
                         k=None if row["tie_stiff"] == "hard" else np.full(tie.size, 7.0))
        _write_bc(seed, k, bc)
        shutil.rmtree(seed.dir / "runs" / seed.run_id / f"view3d_{k}", ignore_errors=True)
        r = c.get(seed.url(), params={"src": k}, headers=R)
        assert r.status_code == 200, r.text
        sup = r.json()["supports"]
        assert len(sup) == tie.size + aux.size
        kinds = {s["kind"] for s in sup if s["dof"] == "123"}
        assert kinds == {{"jig": "tie_fixed", "jig_disp": "tie_disp", "jig_spring": "tie_spring"}[k]}, k
        assert {s["kind"] for s in sup if s["dof"] == "ij"} == {"aux_inplane"}
        assert sorted(s["node_id"] for s in sup if s["dof"] == "ij") == sorted(int(nid[i]) for i in aux)
        for s_ in sup:
            assert isinstance(s_["dirs"], list) and s_["dirs"] and all(len(d) == 3 for d in s_["dirs"])
            if s_["kind"] == "tie_fixed":
                assert s_["val"] == 0.0
            elif s_["kind"] == "tie_spring":
                assert s_["val"] == {"k": [7.0], "g": s_["val"]["g"]} and len(s_["val"]["g"]) == 1
            else:
                assert isinstance(s_["val"], list) and len(s_["val"]) == len(s_["dirs"])
        # manifest.json 파일에도 같은 값(파일 = 응답)
        man = json.loads((seed.dir / "runs" / seed.run_id / f"view3d_{k}" / "manifest.json").read_text(encoding="utf-8"))
        assert [{kk: s_[kk] for kk in ("node_id", "dof", "kind", "dirs", "val")} for s_ in man["supports"]] == \
            [{kk: s_[kk] for kk in ("node_id", "dof", "kind", "dirs", "val")} for s_ in sup]


def test_case_3d_old_npz_without_bc_dir_has_no_kind(mk, seed, engine, jig_plan):  # noqa: F811
    import shutil

    c = mk()
    tie = np.arange(0, 70, dtype=np.int64)
    aux = np.array([85], dtype=np.int64)
    add_jig(seed, "jig", tie=tie, aux=aux)
    set_forces(engine, seed, jig={"status": "ok", "method": "jig"})
    new = c.get(seed.url(), params={"src": "jig"}, headers=R).json()["supports"]
    z = dict(np.load(_esl(seed) / "jig.npz"))
    for k in ("bc_dir", "bc_val", "sp_dir", "sp_k", "sp_g"):
        z.pop(k)
    np.savez_compressed(_esl(seed) / "jig.npz", **z)
    shutil.rmtree(seed.dir / "runs" / seed.run_id / "view3d_jig")
    old = c.get(seed.url(), params={"src": "jig"}, headers=R).json()["supports"]
    assert [(s["node_id"], s["dof"]) for s in old] == [(s["node_id"], s["dof"]) for s in new]      # 표식 수·샘플 순서·dof 불변
    assert all(s["kind"] is None and s["dirs"] is None and s["val"] is None for s in old)
    assert all(s["kind"] for s in new)


def test_non_jig_supports_unchanged(mk, seed, jig_plan):  # noqa: F811
    """03_bc/support.json 출처(지그 아님)의 표식 = 지금 그대로(kind 없음 — 코어가 support321 로 줄 때까지 백엔드는 만들지 않음)."""
    c = mk()
    d = c.get(seed.url(), headers=R).json()
    assert all(s["kind"] is None and s["dirs"] is None and s["val"] is None for s in d["supports"])
