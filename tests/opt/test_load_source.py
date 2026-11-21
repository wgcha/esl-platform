"""v0.24.4 P3 A3 코어 — 하중 출처 찾기·비드 최적화 주입 (계약 docs/contracts/esl_jig_case.md §9, V-0244-JIG-14 코어 부분).

합성: 판(synth_opt.plate) 엔트리 raw + 손으로 만든 Case 폴더(04_esl: u_rel·지그 3방식·경계력 npz/json, 엔트리 스냅샷·runs/* 후보).
- ``source_load.find``: 출처별 하중·bc(노드 ID)·사유, 탐색 순서(스냅샷 → runs 최근 → Case), u_rel 불일치 후보 무시.
- 스터디 ``stages._ns_find`` = find(load=False) 와 같은 값·같은 문구(스터디 바이트 동일 근거 — 골든은 tests/doe).
- 비드 최적화: 출처 하중 주입(S1 노드 직접 — entry_load 와 같은 재배열), 지그 지지 = translation·fixed 만 J 123(선정 컴플라이언스·덱
  SPC1 이 같은 지지), 그 밖 LOAD_SOURCE_UNSUPPORTED·구속 없음 LOAD_SOURCE_UNAVAILABLE, load_source 없음 = 지금 경로 그대로.
"""
from __future__ import annotations

import os
import time

import numpy as np
import pytest
import synth_opt as so

from esl.errors import EslError
from esl.library import _util as U
from esl.library import source_load as srcl
from esl.mech import jig_bc
from esl.opt import select as sl
from esl.opt import settings
from esl.opt import target as tg


def _wj(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    U.write_json(p, d)


def _ties(mesh):
    X = mesh["x0"]
    return np.array(sorted({int(np.argmin(np.linalg.norm(X - c, axis=1))) for c in
                            (X.min(0), np.array([X[:, 0].max(), 0.0, X[:, 2].min()]),
                             np.array([X[:, 0].min(), 0.0, X[:, 2].max()]), X.max(0))}), dtype=np.int64)


def write_esl(d, mesh, u_rel, *, scale=1.0, methods=("fixed", "prescribed", "spring"), tie_dofs="translation",
              bforce_grade="A"):
    """Case 04_esl 흉내: u_rel.npz + 방식마다 <src>.json·npz(f = scale·방식 번호, bc 배열 = 노드 인덱스) + bforce.json·npz."""
    os.makedirs(d, exist_ok=True)
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    N = nid.size
    np.savez(os.path.join(d, "u_rel.npz"), node_id=nid, u_rel=u_rel)
    J = _ties(mesh)
    tie = jig_bc.tie_rows(mesh, J, tie_dofs, kink_deg=45.0)
    aux = jig_bc.aux_rows(mesh["x0"], _sup_idx(mesh), tie, tie_dofs, dup_deg=10.0)
    for k, m in enumerate(methods):
        row = jig_bc.METHODS[m]
        kk = np.full(np.asarray(tie["node"]).size, 50.0) if row["tie_stiff"] != "hard" else None
        BC = jig_bc.build_bc(row, tie, aux, u_rel, k=kk)
        f = np.full((N, 3), scale * (k + 1.0))
        np.savez(os.path.join(d, f"{row['src']}.npz"), node_id=nid, f=f, u_val=u_rel, **jig_bc.save_bc(BC),
                 jig_idx=J)
        _wj(os.path.join(d, f"{row['src']}.json"), {"schema": "esl/case_jig/1", "source": row["src"], "method": m,
                                                     "tie_dofs": tie_dofs, "status": "ok", "code": None})
    np.savez(os.path.join(d, "bforce.npz"), node_id=nid, f=np.full((N, 3), scale * 7.0), u_val=u_rel)
    _wj(os.path.join(d, "bforce.json"), {"grade": bforce_grade, "code": None if bforce_grade != "none" else "BF_NO_MASS",
                                          "reason": None if bforce_grade != "none" else "질량 없음"})
    return J


def _sup_idx(mesh):
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    return [(pos[int(n)], d) for n, d in so.supports_321(mesh)]


@pytest.fixture()
def world(tmp_path):
    mesh = so.plate()
    fe = so.FakeEntry("E0", mesh, so.load(mesh, "bend", 1.0, 0), so.supports_321(mesh))
    raw = dict(fe.raw)
    ur = np.asarray(raw["u_rel"], dtype=np.float64)
    case = tmp_path / "case"
    J = write_esl(str(case / "04_esl"), mesh, ur, scale=1.0)
    meta = {"entry_id": "E0", "source": {"case_dir": str(case)}, "frame": fe.meta["frame"]}
    return {"mesh": mesh, "raw": raw, "meta": meta, "case": case, "J": J, "fe": fe}


# ---------------------------------------------------------------- find
def test_find_each_source(world):
    mesh, raw, meta = world["mesh"], world["raw"], world["meta"]
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    d, doc, f, bc, why = srcl.find("full", meta, raw)
    assert d is None and doc is None and bc is None and why == "" and np.array_equal(f, raw["f"])
    d, doc, f, bc, why = srcl.find("bforce", meta, raw)
    assert d == os.path.join(str(world["case"]), "04_esl") and doc["grade"] == "A" and bc is None and why == ""
    assert np.all(f == 7.0) and f.shape == (nid.size, 3)
    for k, m in enumerate(jig_bc.METHODS):
        src = jig_bc.METHODS[m]["src"]
        d, doc, f, bc, why = srcl.find(src, meta, raw)
        assert doc["method"] == m and np.all(f == k + 1.0) and why == ""
        z = np.load(os.path.join(d, f"{src}.npz"))
        assert np.array_equal(bc["bc_node"], nid[z["bc_node"]]) and np.array_equal(bc["sp_node"], nid[z["sp_node"]])
        assert np.array_equal(bc["bc_val"], z["bc_val"]) and bc["bc_dir"].shape[1] == 3
    with pytest.raises(EslError):
        srcl.find("nope", meta, raw)


def test_find_order_mismatch_and_reasons(world, tmp_path):
    mesh, raw, meta = world["mesh"], world["raw"], world["meta"]
    case = world["case"]
    snap = tmp_path / "snap"
    write_esl(str(snap / "04_esl"), mesh, raw["u_rel"], scale=3.0)                 # 엔트리 스냅샷 = 첫 후보
    bad = case / "runs" / "r1" / "04_esl"
    write_esl(str(bad), mesh, raw["u_rel"] * 2.0, scale=5.0)                         # u_rel 다름 = 무시
    m2 = {**meta, "source": {**meta["source"], "snapshot_dir": str(snap)}}
    d, _doc, f, _bc, _w = srcl.find("jig", m2, raw)
    assert d == str(snap / "04_esl") and np.all(f == 3.0)
    d, _doc, f, _bc, _w = srcl.find("jig", meta, raw)
    assert d == str(case / "04_esl") and np.all(f == 1.0)
    os.remove(os.path.join(str(case / "04_esl"), "jig_disp.npz"))
    _wj(os.path.join(str(case / "04_esl"), "jig_disp.json"), {"status": "unavailable", "code": "JIG_FIXED_SKIPPED",
                                                              "reason": "paicad 없음"})
    d, doc, f, bc, why = srcl.find("jig_disp", meta, raw)
    assert d is None and f is None and bc is None and doc["code"] == "JIG_FIXED_SKIPPED"
    assert why == "JIG_FIXED_SKIPPED: paicad 없음"
    os.remove(os.path.join(str(case / "04_esl"), "jig_disp.json"))
    d, doc, f, bc, why = srcl.find("jig_disp", meta, raw)
    assert doc is None and why.startswith("JIG_NOT_FOUND: Case 에 지그 변위 결과가 없음")


def test_study_ns_find_same_values_and_text(world):
    """스터디 _ns_find = source_load.find(load=False) — 찾음·없음 모두 같은 (dir, json, 사유)·옛 문구 그대로."""
    from esl.doe import stages as stg
    ns = stg.NODAL_BY_KEY["bforce"]
    raw, meta = world["raw"], world["meta"]
    d, jd, why = stg._ns_find(ns, meta, raw)
    assert d == os.path.join(str(world["case"]), "04_esl") and jd["grade"] == "A" and why == ""
    os.remove(os.path.join(d, "bforce.npz"))
    os.remove(os.path.join(d, "bforce.json"))
    d, jd, why = stg._ns_find(ns, meta, raw)
    assert (d, jd) == (None, None)
    assert why == "BF_NOT_FOUND: Case 에 경계력 ESL 결과가 없음 — Case 에서 h3d 추출(v0.24.0)·ESL 을 다시 실행"
    ns = stg.NODAL_BY_KEY["fint"]
    assert stg._ns_find(ns, meta, raw)[2].startswith("FINT_NOT_FOUND: Case 에 내력 ESL 결과가 없음")


def test_plan_table_matches_source_keys():
    from esl import view3d_src as v3s
    from esl.doe import stages as stg
    assert tuple(srcl.SOURCES) == v3s.KEYS == tuple(s_["key"] for s_ in stg.RANK_SOURCES)
    for k in srcl.SOURCES:
        r = srcl.row(k)
        assert r["npz"].endswith(".npz") and (r["json"] is None) == (r["accept"] == "raw")


# ---------------------------------------------------------------- 비드 최적화 주입
def _target(mesh, sup):
    return tg.Target("S1", {k: np.asarray(v) for k, v in mesh.items() if k in tg.MESH_KEYS}, {"n": [0, 1, 0]}, list(sup))


def test_opt_load_injection_and_none_path(world):
    mesh, raw, meta = world["mesh"], world["raw"], world["meta"]
    t = _target(mesh, so.supports_321(mesh))
    F0, i0 = tg.entry_load(t, raw)                                                  # load_source 없음 = 지금 경로
    _d, _doc, f, _bc, _w = srcl.find("full", meta, raw)
    Ff, _ = tg.source_entry_load(t, raw, f)
    assert np.array_equal(Ff, F0) and i0["method"] == "direct_nodal"
    _d, _doc, f, _bc, _w = srcl.find("bforce", meta, raw)
    Fb, info = tg.source_entry_load(t, raw, f)
    assert np.all(Fb == 7.0) and info["source"] == "load_source"


def test_jig_supports_translation_fixed_only(world):
    mesh, raw, meta = world["mesh"], world["raw"], world["meta"]
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    _d, doc, _f, bc, _w = srcl.find("jig", meta, raw)
    sup = tg.jig_supports(doc, bc)
    assert sup == [(int(n), "123") for n in sorted(nid[world["J"]].tolist())]
    for src in ("jig_disp", "jig_spring"):
        _d, doc, _f, bc, _w = srcl.find(src, meta, raw)
        with pytest.raises(EslError) as ei:
            tg.jig_supports(doc, bc)
        assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED"
    with pytest.raises(EslError) as ei:
        tg.jig_supports({"method": "fixed", "tie_dofs": "normal"}, bc)
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED" and "tie 면외" in ei.value.message
    _d, doc, _f, bc, _w = srcl.find("jig", meta, raw)
    with pytest.raises(EslError) as ei:
        tg.jig_supports(doc, None)
    assert ei.value.code == "LOAD_SOURCE_UNAVAILABLE"
    with pytest.raises(EslError) as ei:
        tg.jig_supports(doc, {**bc, "bc_val": np.full(bc["bc_val"].size, 0.1)})
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED"


def test_jig_supports_drive_selection_and_deck(world, tmp_path):
    """J 123 지지 → 선정 컴플라이언스(자체 쉘 솔버)와 덱 SPC1 이 같은 지지: C = F·u(J 고정 독립 풀이)·SPC1 노드 = J."""
    from esl.library import optdeck as od
    from esl.mech.shell import ShellModel
    mesh, raw, meta = world["mesh"], world["raw"], world["meta"]
    _d, doc, _f, bc, _w = srcl.find("jig", meta, raw)
    t = _target(mesh, so.supports_321(mesh))
    t.supports = tg.source_supports(t, {"E0": tg.jig_supports(doc, bc), "E1": tg.jig_supports(doc, bc)})
    F, _ = tg.source_entry_load(t, raw, np.asarray(raw["f"], dtype=np.float64))
    cfg = settings()
    sel, forces, comp = sl.run(t, [{"entry_id": "E0", "mode": "bend", "scene": "s"}], lambda e: F, strategy="B",
                               objective_norm="abs", k=None, cfg=cfg)
    sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], backend="superlu")
    u, _ = sm.solve(F, [(int(i), "123") for i in world["J"]])
    assert comp["C"][0] == pytest.approx(float(np.sum(F * u[:, :3])), rel=1e-8)
    lcs = tg.deck_load_cases(sel, forces)
    summ = od.write(t.mesh, lcs, t.supports, None, str(tmp_path / "deck"))
    with open(os.path.join(str(tmp_path / "deck"), summ["deck"]), encoding="utf-8") as fh:
        txt = fh.read()
    spc = [ln.split(",") for ln in txt.splitlines() if ln.startswith("SPC1,")]
    assert len(spc) == len(t.supports) == world["J"].size and {r[2] for r in spc} == {"123"}
    with pytest.raises(EslError) as ei:
        tg.source_supports(t, {"E0": t.supports, "E1": t.supports[:-1]})
    assert ei.value.code == "LOAD_SOURCE_UNSUPPORTED"


def test_find_speed_small(world):
    t0 = time.monotonic()
    for _ in range(5):
        srcl.find("jig_spring", world["meta"], world["raw"])
    assert time.monotonic() - t0 < 5.0
