"""v0.24.9 B1 — Case 3D 지그 경계조건 표식 방식별 자료(계약 esl_bead_pos_u.md §10.2·§10.4-1~3, V-0249-BM-1~3의 백엔드 부분).

- 표식 행 = 코어 ``esl.mech.jig_bc.support_rows``(어댑터 ``core_adapter.jig_support_rows`` 경유 — 통합 INT-1, 백엔드 자체 계산 없음): 세 방식 ×
  tie_dofs(normal·translation) × 꺾임 노드 → kind·dirs·val 이 BC 배열(`build_bc` 결과)과 일치, 샘플·순서·dof = 옛 2튜플 규칙 그대로.
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


def _r6(x):
    return float(round(float(x), 6)) + 0.0


def _rows(bc, x0, smax, src):
    """백엔드가 부르는 코어 함수(어댑터 경유 — Case 3D·스터디 사이드카 공통, 통합 INT-1)."""
    from esl_worker import core_adapter

    return core_adapter.jig_support_rows(bc, x0, smax, np.arange(x0.shape[0]), src)


SRC = {"fixed": "jig", "prescribed": "jig_disp", "spring": "jig_spring"}


@pytest.mark.parametrize("method", ["fixed", "prescribed", "spring"])
@pytest.mark.parametrize("tie_dofs", ["normal", "translation"])
def test_marks_match_bc_arrays(method, tie_dofs):
    """V-0249-BM-1·3(통합 INT-1): 표식 행 kind·dirs·val = BC 배열(build_bc) — 방식별. 스프링 방식 tie = 스프링 행 방향만(법선 1, 꺾임 2,
    translation 3)·{k[], g[]}, 받침점(aux) = 면내 1·2 방향(법선 성분 0) — 옛 "모든 방식 tie = 123 세 방향 고정" 재발 방지."""
    x0 = _plate()
    bc, _ = _bc(method, tie_dofs)
    rows = _rows(bc, x0, 64, SRC[method])
    old = _old_marks(bc, x0, 64)
    assert [(r["node_id"], r["dof"]) for r in rows] == old        # 표식 수·샘플 순서·dof 옛 규칙 그대로
    bn, bd, bv, bk = bc["bc_node"], bc["bc_dir"], bc["bc_val"], bc["bc_kind"]
    for r in rows:
        i, kind, dirs, val = r["node_id"], r["kind"], r["dirs"], r["val"]
        if kind == "aux_inplane":
            ix = np.flatnonzero((bn == i) & (bk == KIND_AUX))
            assert dirs == [[_r6(x) for x in bd[j]] for j in ix] and val == [_r6(bv[j]) for j in ix]
            assert all(abs(d[2]) < 1e-12 for d in dirs)                                   # 면내(판 z = 0 법선 성분 없음)
            continue
        if method == "spring":
            ix = np.flatnonzero(bc["sp_node"] == i)
            assert kind == "tie_spring" and dirs == [[_r6(x) for x in bc["sp_dir"][j]] for j in ix]
            assert val == {"k": [_r6(bc["sp_k"][j]) for j in ix], "g": [_r6(bc["sp_g"][j]) for j in ix]}
            assert not np.any((bn == i) & (bk == KIND_TIE))                               # 스프링 tie 는 구속 행 없음(면내 자유)
        else:
            ix = np.flatnonzero((bn == i) & (bk == KIND_TIE))
            assert dirs == [[_r6(x) for x in bd[j]] for j in ix]
            if method == "fixed":
                assert kind == "tie_fixed" and val == 0.0
            else:
                assert kind == "tie_disp" and val == [_r6(bv[j]) for j in ix]
    by = {r["node_id"]: r["dirs"] for r in rows if r["kind"] != "aux_inplane"}
    if tie_dofs == "normal":                                       # 꺾임 노드 = 법선 2개, 평평한 노드 = 법선 1개(세 방향 아님)
        assert {len(by[i]) for i in (2, 5, 9)} == {2} and {len(by[i]) for i in (0, 1, 3)} == {1}
    else:
        assert {len(d) for d in by.values()} == {3}
    aux = {r["node_id"]: r["dirs"] for r in rows if r["kind"] == "aux_inplane"}
    if tie_dofs == "normal":
        assert sorted(aux) == [40, 55, 77] and len(aux[40]) == 2 and len(aux[55]) == 1        # 면내 방향 2 또는 1


def _old_marks(bc, x0, smax):
    """옛 2튜플 [(노드, dof)] — 코어 옛 호출(키워드 없음 = v0.24.8 바이트)."""
    from esl.mech import jig_bc as jb

    return [(int(i), d) for i, d in jb.support_marks(bc["bc_node"], bc["bc_kind"], bc["sp_node"], x0, smax)]


@pytest.mark.parametrize("method", ["fixed", "prescribed", "spring"])
def test_marks_sampling_capped_and_deterministic(method):
    from esl.mech import jig_bc as jb
    from esl_platform.api.services import view3d as v

    x0 = _plate(14)
    tn = np.arange(0, 100)
    nz = np.tile([0.0, 0.0, 1.0], (tn.size, 1))
    row = jb.METHODS[method]
    bc = jb.build_bc(row, {"node": tn, "dir": nz}, {"node": np.array([150, 151, 160]), "dir": np.array([[1.0, 0, 0], [0, 1.0, 0], [1.0, 0, 0]])},
                     np.zeros((200, 3)), k=None if row["tie_stiff"] == "hard" else np.full(tn.size, 3.0))
    a = _rows(bc, x0, 20, SRC[method])
    assert a == _rows(bc, x0, 20, SRC[method])
    ties = [m for m in a if m["kind"] != "aux_inplane"]
    assert len(ties) == 20 and len([m for m in a if m["kind"] == "aux_inplane"]) == 3
    assert [m["node_id"] for m in ties] == v.jig_support_sample(x0, tn, 20).tolist()   # 최원점 샘플 = 백엔드 샘플 함수(= 코어)
    bc2 = {k: np.asarray(x) for k, x in bc.items()}                # 샘플된 tie 와 겹치는 면내 노드는 tie 만
    bc2["bc_node"] = np.r_[bc2["bc_node"], [0]].astype(np.int64)
    bc2["bc_kind"] = np.r_[bc2["bc_kind"], [KIND_AUX]].astype(np.int8)
    bc2["bc_dir"] = np.r_[bc2["bc_dir"], [[1.0, 0.0, 0.0]]]
    bc2["bc_val"] = np.r_[bc2["bc_val"], [0.0]]
    b = _rows(bc2, x0, 20, SRC[method])
    assert sum(1 for m in b if m["node_id"] == 0) == 1 and [m for m in b if m["node_id"] == 0][0]["kind"] != "aux_inplane"


def test_backend_has_no_own_mark_computation(monkeypatch, tmp_path):
    """V-0249-BM-3(통합 INT-1): Case 3D 표식 = 코어 함수 호출 결과 그대로(백엔드 어댑터 계산 없음 — 출처 키를 src 로 넘김)."""
    from types import SimpleNamespace

    from esl_platform.api.services import view3d as v
    from esl_worker import core_adapter

    for name in ("jig_marks_general", "_core_marks_general", "jig_support_marks", "_enrich_manifest_supports"):
        assert not hasattr(v, name), name
    x0 = _plate()
    bc, _ = _bc("spring", "normal")
    p = tmp_path / "jig_spring.npz"
    np.savez(p, **{k: np.asarray(x) for k, x in bc.items()})
    seen = {}

    def fake(bc_, x0_, smax, node_id, src):
        seen.update(keys=sorted(bc_), smax=smax, src=src, n=len(node_id))
        return [{"node_id": 1, "dof": "123", "kind": "tie_spring", "dirs": [[0.0, 0.0, 1.0]], "val": {"k": [1.0], "g": [0.0]}}]

    monkeypatch.setattr(core_adapter, "jig_support_rows", fake)
    view3d_cfg = SimpleNamespace(jig_support_max=17)
    inp = SimpleNamespace(support_npz=str(p), row={"key": "jig_spring"},
                          ctx=SimpleNamespace(settings=SimpleNamespace(bead_doe=SimpleNamespace(view3d=view3d_cfg))))
    out = v._jig_supports(inp, np.arange(x0.shape[0]), x0)
    assert out == fake(bc, x0, 17, np.arange(x0.shape[0]), "jig_spring")
    assert seen["src"] == "jig_spring" and seen["smax"] == 17 and "sp_k" in seen["keys"] and "bc_dir" in seen["keys"]


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
        # 응답 = 코어 함수 결과 그대로(V-0249-BM-3 — 같은 npz·같은 출처 키)
        with np.load(_esl(seed) / f"{k}.npz") as z:
            bcz = {kk: z[kk] for kk in jb.BC_KEYS if kk in z.files}
        core = jb.support_rows(bcz, np.asarray(seed.m["x0"], dtype=float), 10 ** 6, nid, k)
        assert [{kk: s_[kk] for kk in ("node_id", "dof", "kind", "dirs", "val")} for s_ in sup] == core


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
    assert all("kind" not in s and "dirs" not in s and "val" not in s for s in old)      # 값 없으면 키 없음(옛 바이트)
    assert all(s["kind"] for s in new)


def test_non_jig_supports_unchanged(mk, seed, jig_plan):  # noqa: F811
    """03_bc/support.json 출처(지그 아님)의 표식 = 지금 그대로(kind 없음 — 코어가 support321 로 줄 때까지 백엔드는 만들지 않음)."""
    c = mk()
    d = c.get(seed.url(), headers=R).json()
    assert all("kind" not in s and "dirs" not in s and "val" not in s for s in d["supports"])
