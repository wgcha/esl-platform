"""v0.25.1 C1 — 낙하 씬별 3D 묶음 + C 기여도·차이·umax 핀 (계약 docs/contracts/esl_view3d_scene_legend.md §2·§3·§7·§9.1,
V-0251-1~15).

세계 = golden_v0251_c1.golden_vl(기존 시험 세계 재사용): ① same(지그 3방식 + 경계력·내력 + 평가 영역 = 출처 6행, 옛 지그 고정 npz),
옛 ③ step, ④ 형상 비교(LT)·격자 지그. 순수 함수 시험은 합성 판(synth_jig_grid·synth_doe).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "golden_v0251_c1"))
import golden_vl as GV  # noqa: E402
import synth_doe as sd  # noqa: E402
import synth_jig_grid as SG  # noqa: E402

from esl.doe import DEFAULTS, settings  # noqa: E402
from esl.doe import evaluate as ev  # noqa: E402
from esl.doe import stages as stg  # noqa: E402
from esl.errors import EslError  # noqa: E402
from esl.library import _util as U  # noqa: E402
from esl.mech import cfield as cf  # noqa: E402
from esl.mech import grid_map as gm  # noqa: E402
from esl.mech import jig_bc  # noqa: E402
from esl import view3d as v3  # noqa: E402

REL = 1e-9
ROOT = os.path.dirname(os.path.dirname(HERE))


# ---------------------------------------------------------------- 세계(모듈 1회)
def _world(tmp_path_factory, case: str, cfg_over=None) -> str:
    t = str(tmp_path_factory.mktemp(case))
    with pytest.MonkeyPatch.context() as mp:
        return GV.compute_out(case, t, mp, cfg_over)


@pytest.fixture(scope="module")
def w_all6(tmp_path_factory):
    return _world(tmp_path_factory, "same_all6")


@pytest.fixture(scope="module")
def w_legacy(tmp_path_factory):
    """옛 지그 고정(translation — BC 배열 없는 jig.npz) + 경계력·내력, 평가 영역 없음(핀 = 출처 umax: mask·all)."""
    t = str(tmp_path_factory.mktemp("legacy"))
    import test_jig_stages as T
    doe, _rank, mesh = GV.same_world(t, kind="legacy")
    out, _p, _i = T.run(os.path.join(t, "o"), doe, mesh, rank=T.rank_snap())
    return out


@pytest.fixture(scope="module")
def w_cmp_grid(tmp_path_factory):
    return _world(tmp_path_factory, "cmp_grid")


@pytest.fixture(scope="module")
def w_cmp_lt(tmp_path_factory):
    return _world(tmp_path_factory, "cmp_lt")


def _side(out):
    return U.read_json(os.path.join(out, "post", stg.SCENE_VIEW_JSON))


def _per(out, did, row):
    """출처 행 row 의 안 did per_esl {entry: 행} — 실행기와 같은 읽기(열 values)."""
    by = {did: U.read_json(os.path.join(out, "run", "designs", did, "result.json"))}

    class _C:
        def p(self, *a):
            return os.path.join(out, *a)
    c = _C()
    if row["values"] == "nodal":
        ns = stg.NODAL_BY_KEY[row["key"]]
        doc = U.read_json(os.path.join(out, "run", "designs", did, stg._nf(ns, "design")))
        return {p["entry_id"]: p for p in doc["per_esl"]}
    _ = c
    return {p["entry_id"]: p for p in by[did]["per_esl"]}


def _scenes(out):
    """[(row, did, entry_id, manifest, pack_dir)] 사이드카의 모든 씬."""
    side = _side(out)
    rows = {r["key"]: r for r in stg.SCENE_SOURCES}
    got = []
    for key, pk in side["packs"].items():
        for did, d in pk["designs"].items():
            od = os.path.join(out, "post", stg.SCENE_DIR, d["dir"])
            pack = U.read_json(os.path.join(od, v3.PACK_JSON))
            for s in pack["scenes"]:
                got.append((rows[key], did, s["entry_id"], U.read_json(os.path.join(od, s["manifest"])), od))
    return got


# ---------------------------------------------------------------- V-0251-1 fu: 합성 판 + 3-2-1, 여러 씬
def test_v0251_1_nodal_c_fu_equals_evaluate(tmp_path):
    mesh = sd.plate(nx=10, ny=6, Lx=200.0, Lz=120.0)
    sup = sd.so.supports_321(mesh)
    rng = np.random.default_rng(3)
    loads = [(f"E{k}", rng.normal(size=(mesh["node_id"].size, 3)) * (k + 1)) for k in range(3)]
    r = ev.evaluate(mesh, sup, loads, {"drill_factor": 1e-4, "backend": "superlu"}, reaction_warn=1.0,
                    keep_u=[e for e, _ in loads])
    for (e, F), p in zip(loads, r["per_esl"]):
        nc = cf.nodal_c(F, r["u"][e])
        assert abs(nc["sum"] - p["C"]) <= REL * abs(p["C"])
        assert abs(nc["W_F"] - p["C"]) <= REL * abs(p["C"]) and nc["W_v"] == 0.0 and nc["W_g"] == 0.0
        assert nc["c"].shape == (mesh["node_id"].size,)


def test_v0251_1_study_fu_sum_equals_table(w_all6, w_legacy):
    """전 노드·경계력·내력(fu): 묶음 manifest c.sum(양자화 전 float64) = per_esl C(1e-9), offset 0."""
    n = 0
    for out in (w_all6, w_legacy):
        for row, did, e, man, _od in _scenes(out):
            if row["c_kind"] != "fu":
                continue
            C = float(_per(out, did, row)[e][row["c_key"]])
            assert man["c"]["kind"] == "fu" and man["c"]["offset"] == 0.0 and man["c"]["value"] == C
            assert abs(man["c"]["sum"] - C) <= REL * abs(C), (row["key"], did, e)
            assert man["c"]["unit"] == "N·mm" and set(man["c"]["parts"]) == {"W_F", "W_v", "W_g"}
            n += 1
    assert n >= 2 * 3 * 3 * 2


# ---------------------------------------------------------------- V-0251-2·3 mixed: 지정 변위·스프링(바닥 g ≠ 0)
@pytest.mark.parametrize("method", ["prescribed", "spring", "fixed"])
def test_v0251_2_3_nodal_c_mixed_equals_mixed_compliance(method):
    mesh = SG.plate(5.0)
    u = SG.u_drop(mesh)
    F = SG.forces(mesh, u)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    J = SG.tie_idx(mesh)
    tie = jig_bc.tie_rows(mesh, J, "normal", kink_deg=45.0)
    aux = jig_bc.aux_rows(X, SG.sup321(mesh), tie, "normal", dup_deg=10.0)
    sm = SG.shell(mesh)
    row = jig_bc.METHODS[method]
    tg = jig_bc.target(row["frame"], X, u, J, np.ones(X.shape[0], bool))
    k = None if row["tie_stiff"] == "hard" else jig_bc.spring_k(sm, tie, mode="auto", alpha=0.01)
    BC = jig_bc.build_bc(row, tie, aux, tg["u_tgt"], k=k)
    r = jig_bc.respond(jig_bc.factorize(sm, BC), F, BC)
    nc = cf.nodal_c(F, r["u"], BC, r["rc"], r["fs"])
    en = r["energy"]
    if method == "spring":
        assert np.abs(BC["sp_g"]).max() > 0 and nc["W_g"] != 0.0        # 바닥 g ≠ 0
    if method == "prescribed":
        assert np.abs(BC["bc_val"]).max() > 0 and nc["W_v"] != 0.0
    assert abs(nc["sum"] - en["C_mix"]) <= REL * max(abs(en["W_F"]), abs(en["W_g"]))
    assert abs(nc["W_v"] + nc["W_g"] - en["W_g"]) <= REL * max(abs(en["W_g"]), 1e-300)
    E0, Cm0 = 1.7 * abs(en["C_mix"]) + 1.0, 0.9 * en["C_mix"]
    C_pe = jig_bc.per_esl_C(en["C_mix"], Cm0, E0)
    assert abs(nc["sum"] + (E0 - Cm0) - C_pe) <= REL * abs(C_pe)


def test_v0251_2_3_study_mixed_sum_equals_table(w_all6, w_cmp_grid):
    """지그 고정(BC)·변위·스프링(같은 메시) + 격자 지그(④): Σc + offset = per_esl C_<pe>(1e-9), offset = E_0 − C_mix,0."""
    seen = set()
    for out in (w_all6, w_cmp_grid):
        for row, did, e, man, _od in _scenes(out):
            if row["c_kind"] == "fu":
                continue
            assert man["c"]["kind"] == "mixed"
            C = float(_per(out, did, row)[e][row["c_key"]])
            assert man["c"]["value"] == C
            assert abs(man["c"]["sum"] + man["c"]["offset"] - C) <= REL * abs(C), (row["key"], did, e)
            p = man["c"]["parts"]
            assert abs(man["c"]["sum"] - (p["W_F"] - p["W_v"] - p["W_g"])) <= REL * max(abs(p["W_F"]), abs(p["W_g"]), 1.0)
            seen.add((out == w_cmp_grid, row["key"]))
    assert {(False, "jig"), (False, "jig_disp"), (False, "jig_spring"), (True, "jig_disp"), (True, "jig_spring")} <= seen


# ---------------------------------------------------------------- V-0251-4 옛 지그 고정(BC 배열 없는 npz)
def test_v0251_4_legacy_jig_fu(w_legacy):
    z = U.load_npz(os.path.join(w_legacy, "prep", "jig.npz"))
    assert "bc_node" not in z
    rows = [x for x in _scenes(w_legacy) if x[0]["key"] == "jig"]
    assert rows
    for row, did, e, man, _od in rows:
        C = float(_per(w_legacy, did, row)[e]["C_jig"])
        assert man["c"]["kind"] == "fu" and man["c"]["offset"] == 0.0
        assert abs(man["c"]["sum"] - C) <= REL * abs(C)
    assert _side(w_legacy)["packs"]["jig"]["c_kind"] == "fu"


# ---------------------------------------------------------------- V-0251-5 차이 같은 메시
def test_v0251_5_diff_identity_bitwise():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=500), rng.normal(size=500)
    d = cf.diff(a, b)
    assert np.array_equal(d, a - b)
    with pytest.raises(EslError):
        cf.diff(a, b[:-1])


def test_v0251_5_study_diff_sum_equals_delta_c(w_all6):
    n = {"fu": 0, "mixed": 0}
    sc = _scenes(w_all6)
    base = {(r["key"], e): m for r, d, e, m, _o in sc if d == stg.BASELINE}
    for row, did, e, man, _od in sc:
        if did == stg.BASELINE:
            assert man["dc"] is None and man["ranges"]["dc"] is None
            assert [a["key"] for a in man["values"]["arrays"]] == ["pa", "fn", "fmag", "u", "c"]
            continue
        b = base[(row["key"], e)]
        dc = man["dc"]
        assert dc["map"] == "identity" and dc["base_sum"] == b["c"]["sum"]
        assert abs(dc["sum"] - (man["c"]["sum"] - b["c"]["sum"])) <= REL * max(abs(man["c"]["sum"]), abs(b["c"]["sum"]))
        dC = man["c"]["value"] - b["c"]["value"]                  # 표의 ΔC(mixed 도 offset 상쇄)
        assert abs(dc["sum"] - dC) <= REL * max(abs(man["c"]["value"]), abs(b["c"]["value"]))
        assert [a["key"] for a in man["values"]["arrays"]] == ["pa", "fn", "fmag", "u", "c", "dc"]
        n[man["c"]["kind"]] += 1
    assert n["fu"] and n["mixed"]


# ---------------------------------------------------------------- V-0251-6 차이 다른 메시(conserve_map)
def _gf(mesh, cell=3.0):
    fr = SG.frame_of(mesh)
    return gm.grid_frame(fr, cell)


def test_v0251_6_conserve_map_unit():
    A = SG.plate(5.0)
    B = SG.plate(4.0, tri_cols=6, node_base=100001)
    rng = np.random.default_rng(5)
    c0 = rng.normal(size=A["node_id"].size)
    GF = _gf(A, 6.0)
    m1, info = cf.conserve_map(c0, A["x0"], B["x0"], GF)
    assert abs(m1.sum() - c0.sum()) <= 1e-12 * np.abs(c0).sum()
    assert info["sum_src"] == float(c0.sum()) and abs(info["sum_dst"] - info["sum_src"]) <= 1e-12 * np.abs(c0).sum()
    m2, _ = cf.conserve_map(c0, A["x0"], B["x0"], GF)
    assert m1.tobytes() == m2.tobytes()                            # 결정적
    same, _ = cf.conserve_map(c0, A["x0"], A["x0"], GF)            # 같은 메시 = 항등과 같은 합
    assert abs(same.sum() - c0.sum()) <= 1e-12 * np.abs(c0).sum()
    cd = rng.normal(size=B["node_id"].size)
    dc = cf.diff(cd, m1)
    assert abs(dc.sum() - (cd.sum() - c0.sum())) <= REL * max(abs(cd.sum()), abs(c0.sum()), np.abs(c0).sum())
    # 빈 셀(대상 노드가 없는 영역) → 가장 가까운 대상 노드, moved_rel 기록
    keep = np.asarray(B["x0"])[:, 0] < 120.0
    Xd = np.asarray(B["x0"])[keep]
    m3, info3 = cf.conserve_map(c0, A["x0"], Xd, GF)
    assert info3["n_empty"] > 0 and 0.0 < info3["moved_rel"] <= 1.0
    assert abs(m3.sum() - c0.sum()) <= 1e-12 * np.abs(c0).sum()
    far = np.asarray(A["x0"])[:, 0] >= 125.0                       # 오른쪽 기준 값은 x < 120 끝 열 노드로 옮겨짐
    assert abs(m3[Xd[:, 0] >= Xd[:, 0].max() - 1e-9].sum()) > 0 and far.any()


def test_v0251_6_study_grid_diff(w_cmp_lt, w_cmp_grid):
    """④(다른 메시): 차이 map grid, Σdc = ΔC(표) 1e-9, cell_mm ≥ rank.jig_grid.cell_mm, moved_rel 기록."""
    n = 0
    for out in (w_cmp_lt, w_cmp_grid):
        sc = _scenes(out)
        base = {(r["key"], e): m for r, d, e, m, _o in sc if d == stg.BASELINE}

        def nid(od):
            js, b = v3.read_glb(os.path.join(od, v3.GEOMETRY))
            a = js["accessors"][1]
            return np.frombuffer(b, "<u4", count=a["count"], offset=js["bufferViews"][1]["byteOffset"])
        n0 = {r["key"]: nid(o) for r, d, e, m, o in sc if d == stg.BASELINE}
        for row, did, e, man, od in sc:
            if did == stg.BASELINE:
                continue
            b = base[(row["key"], e)]
            dc = man["dc"]
            same = np.array_equal(nid(od), n0[row["key"]])         # 판정 = 노드 ID 배열 같음(모드 이름 분기 없음)
            if same:
                assert dc["map"] == "identity"
            else:
                assert dc["map"] == "grid" and dc["cell_mm"] >= DEFAULTS["rank"]["jig_grid"]["cell_mm"]
                assert 0.0 <= dc["moved_rel"] <= 1.0
                n += 1
            dC = man["c"]["value"] - b["c"]["value"]
            assert abs(dc["sum"] - dC) <= REL * max(abs(man["c"]["value"]), abs(b["c"]["value"])), (row["key"], did, e)
    assert n >= 4


# ---------------------------------------------------------------- V-0251-7 umax 핀
def test_v0251_7_umax_pin_unit_ties_and_mask():
    u = np.zeros((6, 3))
    u[2] = [3.0, 4.0, 0.0]
    u[4] = [0.0, 0.0, 5.0]                                          # 동률(‖u‖ = 5) → 작은 인덱스
    assert cf.umax_pin(u) == {"index": 2, "value": 5.0}
    mk = np.array([0, 0, 0, 1, 1, 0], bool)
    assert cf.umax_pin(u, mk) == {"index": 4, "value": 5.0}
    assert cf.umax_pin(u, np.zeros(6, bool)) == {"index": 2, "value": 5.0}       # 빈 영역 = 전 노드(umax_in 규칙)
    assert cf.umax_pin(u, mk)["value"] == ev.umax_in(u, mk)


def test_v0251_7_study_pins_equal_table(w_all6, w_legacy, w_cmp_grid, w_cmp_lt):
    """핀 값 == per_esl(umax_ev 우선, 없으면 그 출처 umax) — 같은 값(==), 핀 노드 ∈ 평가 영역, 출처 6행 모두."""
    kinds = {}
    for out in (w_all6, w_legacy, w_cmp_grid, w_cmp_lt):
        for row, did, e, man, od in _scenes(out):
            p = _per(out, did, row)[e]
            k_ev, k_b = row["pin"]
            pin = man["pins"]["umax"]
            want = p[k_ev] if p.get(k_ev) is not None else p[k_b]
            assert pin["value"] == want, (row["key"], did, e, pin, want)
            assert (pin["kind"] == "ev") == (p.get(k_ev) is not None)
            assert man["top"] is not None and 0 <= pin["vertex"] < man["n_nodes"]
            kinds.setdefault(row["key"], set()).add(pin["kind"])
    assert set(kinds) == {r["key"] for r in stg.SCENE_SOURCES}
    assert {"ev"} <= kinds["full"] and "mask" in kinds["jig"] and "all" in kinds["bforce"]


def test_v0251_7_pin_inside_eval_region(w_all6):
    from esl.doe import eval_region as evr
    m = U.load_npz(os.path.join(w_all6, "prep", "base_mesh.npz"))
    mk = evr.eval_mask(m["x0"], m["conn"], m["elem_type"], GV.EV["mode"], GV.EV["free_edge_mm"], [])
    assert mk.any() and not mk.all()
    nid = np.asarray(m["node_id"])
    for row, did, e, man, _od in _scenes(w_all6):
        pin = man["pins"]["umax"]
        if pin["kind"] == "ev":
            assert mk[int(np.searchsorted(nid, pin["node_id"]))], (row["key"], did, e)


# ---------------------------------------------------------------- V-0251-8 양자화 · V-0251-9 build_view 불변
def test_v0251_8_quantization_and_float_sum(tmp_path):
    rng = np.random.default_rng(9)
    m = sd.plate(nx=8, ny=5, Lx=160.0, Lz=100.0)
    n = m["node_id"].size
    c = rng.normal(size=n) * 1e3
    dc = rng.normal(size=n)
    f = rng.normal(size=(n, 3))
    u = rng.normal(size=(n, 3))
    scn = [{"entry_id": "E0", "kk": 0, "f": f, "u": u, "supports": [], "c": c,
            "c_meta": {"kind": "fu", "sum": float(c.sum()), "offset": 0.0, "value": float(c.sum()),
                       "parts": {"W_F": 1.0, "W_v": 0.0, "W_g": 0.0}},
            "dc": dc, "dc_meta": {"sum": float(dc.sum()), "base_sum": 0.0, "map": "identity"},
            "pins": {"umax": {"node_id": int(m["node_id"][0]), "vertex": 0, "value": 1.0, "kind": "all"}}}]
    od = str(tmp_path / "p")
    pk = v3.build_scene_pack(od, node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], scenes=iter(scn),
                             key="k", src="full", did="d000")
    man = U.read_json(os.path.join(od, "e00.json"))
    assert man["c"]["sum"] == float(c.sum())
    buf = open(os.path.join(od, "e00.bin"), "rb").read()
    got = v3.unpack_values(buf, man["values"]["arrays"], n)
    for k, v in (("c", c), ("dc", dc)):
        s = next(a["scale"] for a in man["values"]["arrays"] if a["key"] == k)
        assert np.abs(got[k] - v).max() <= s / 2 + 1e-12 * s
    vb, _ = v3.pack_values(*v3.face_values(f, v3.node_geometry(m["x0"], m["conn"], m["elem_type"]))[::-1],
                           np.linalg.norm(f, axis=1), u)
    assert buf[:len(vb)] == vb                                     # 기존 values.bin 배열 그대로 앞에
    assert pk["schema"] == v3.SCENE_SCHEMA and pk["scenes"] == [{"entry_id": "E0", "kk": 0, "manifest": "e00.json",
                                                                  "values": "e00.bin"}]
    assert man["ranges"]["c"]["p01"] <= man["ranges"]["c"]["p99"] and man["ranges"]["dc"]["abs_max"] == float(np.abs(dc).max())


def test_v0251_9_pack_glb_equals_build_view(w_all6, w_cmp_lt):
    for out in (w_all6, w_cmp_lt):
        a = open(os.path.join(out, "post", "view3d", "d000", "part.glb"), "rb").read()
        b = open(os.path.join(out, "post", stg.SCENE_DIR, "sv", "d000", "part.glb"), "rb").read()
        assert a == b


def test_v0251_9_lod_pack(tmp_path):
    m = sd.plate(nx=14, ny=9, Lx=200.0, Lz=120.0)
    n = m["node_id"].size
    rng = np.random.default_rng(1)
    scn = [{"entry_id": f"E{k}", "kk": k, "f": rng.normal(size=(n, 3)), "u": rng.normal(size=(n, 3)), "supports": [],
            "c": rng.normal(size=n), "c_meta": {"kind": "fu", "sum": 0.0, "offset": 0.0, "value": 0.0,
                                                "parts": {"W_F": 0.0, "W_v": 0.0, "W_g": 0.0}},
            "dc": None, "dc_meta": None, "pins": {"umax": None}} for k in range(2)]
    od = str(tmp_path / "l")
    pk = v3.build_scene_pack(od, node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], scenes=scn,
                             cfg={"lod_min_nodes": 0, "lod_target_vertices": 30})
    assert pk["lod"]["name"] == v3.GEOMETRY_LOD and os.path.isfile(os.path.join(od, v3.GEOMETRY_LOD))
    assert U.read_json(os.path.join(od, "e01.json"))["lod"] == pk["lod"]


# ---------------------------------------------------------------- V-0251-10·13 기존 파일 바이트 불변 · enabled false
@pytest.mark.parametrize("case", GV.CASES)
def test_v0251_10_existing_files_bytes(tmp_path, monkeypatch, case):
    gold = GV.load()
    exp = gold["cases"][case]
    got = GV.compute(case, str(tmp_path), monkeypatch)
    for k in gold["unstable"].get(case, []):
        got.pop(k, None)
    old, new = GV.split_new(got)
    assert sorted(old) == sorted(exp)
    diff = [k for k in exp if old[k] != exp[k]]
    assert not diff, diff
    assert "post/scene_view.json" in new and all(k.startswith(GV.NEW_PREFIX) for k in new)
    assert any(k.startswith("post/view3d_scene/sv/d000/") for k in new)


@pytest.mark.parametrize("case", ["same_all6", "cmp_grid"])
def test_v0251_13_disabled_file_set_equals_main(tmp_path, monkeypatch, case):
    gold = GV.load()
    got = GV.compute(case, str(tmp_path), monkeypatch, cfg_over={"view3d": {"scene": {"enabled": False}}})
    for k in gold["unstable"].get(case, []):
        got.pop(k, None)
    assert sorted(got) == sorted(gold["cases"][case])
    assert not [k for k in got if got[k] != gold["cases"][case][k]]


# ---------------------------------------------------------------- V-0251-11 한도
def _many_world(tmp, max_mb):
    """① same 판 + 엔트리 4개(C 크기 다름), 순위 스냅샷 없음(전 노드 출처만)."""
    import pathlib

    import test_jig_stages as T
    t = pathlib.Path(tmp)
    mesh, doe = T.build_same(t)
    lib = t / "lib4"
    kinds = (("bend", 1.0), ("dent", 3.0), ("twist", 2.0), ("bend", 0.5))
    dirs = [sd.save_entry(str(lib), f"F{k}", mesh, kd, a, seed=k)[0] for k, (kd, a) in enumerate(kinds)]
    doe = {**doe, "entries": [{"id": f"F{k}", "dir": d} for k, d in enumerate(dirs)], "base": {**doe["base"], "entry_id": "F0"}}
    bd = copy.deepcopy(doe["cfg"]["bead_doe"])
    bd["view3d"] = {"scene": {"enabled": True, "max_mb": max_mb, "diff_cell_h_mult": 2.0}}
    doe["cfg"] = {**doe["cfg"], "bead_doe": bd}
    out, post, _ids = T.run(str(t / "o"), doe, mesh)
    return out, post


def test_v0251_11_budget(tmp_path):
    out, post = _many_world(str(tmp_path / "a"), 0.0001)
    side = _side(out)
    pk = side["packs"]["full"]
    shown = post["view3d"]
    per = {d: {p["entry_id"]: p for p in U.read_json(os.path.join(out, "run", "designs", d, "result.json"))["per_esl"]}
           for d in shown}
    worst = {max(per[d], key=lambda e: (per[d][e]["C"], -int(e[1:]))) for d in shown}
    got = set().union(*[set(v["scenes"]) for v in pk["designs"].values()])
    assert got == worst                                            # 한도가 아주 작으면 각 안의 최악만
    sk = [x for x in pk["skipped"] if x["code"] == "SCENE_BUDGET"]
    assert {x["entry_id"] for x in sk} == {f"F{k}" for k in range(4)} - worst
    b = side["budget"]
    assert b["max_mb"] == 0.0001 and b["est_mb"] > b["max_mb"] and b["n_scenes"] == 4 * len(shown)
    assert b["n_written"] == len(got) * len(shown)
    # 한도 = 최악 + 1씬 → 다음 씬 = 베이스라인 C 큰 순
    c0 = per["d000"]
    order = sorted(c0, key=lambda e: (-c0[e]["C"], int(e[1:])))
    nxt = next(e for e in order if e not in worst)
    n_nodes = len(U.load_npz(os.path.join(out, "prep", "base_mesh.npz"))["node_id"])
    E_ = stg.SCENE_EST
    need = len(shown) * E_["geom_b"] * n_nodes + sum(
        (E_["val_b_base"] if d == "d000" else E_["val_b"]) * n_nodes + E_["manifest_b"] for d in shown) * (len(worst) + 1)
    out2, _p = _many_world(str(tmp_path / "b"), (need + 10) / E_["mb"])
    got2 = set().union(*[set(v["scenes"]) for v in _side(out2)["packs"]["full"]["designs"].values()])
    assert got2 == worst | {nxt}


# ---------------------------------------------------------------- V-0251-12 보충 실행(post_mode scene)
def _tree(out):
    from golden_pu import tree_sha
    return tree_sha(out, os.path.dirname(out), scene=True)


def test_v0251_12_supplement_old_study(tmp_path, monkeypatch):
    import test_jig_stages as T
    t = str(tmp_path)
    doe, rank, mesh = GV.same_world(t, kind="all6")
    bd = copy.deepcopy(doe["cfg"]["bead_doe"])
    bd["view3d"] = {"scene": {"enabled": False, "max_mb": 1024, "diff_cell_h_mult": 2.0}}      # v0.25.0 와 같은 파일 집합
    old_doe = {**doe, "cfg": {**doe["cfg"], "bead_doe": bd}}
    out, _post, ids = T.run(os.path.join(t, "o"), old_doe, mesh, rank=rank)
    assert not os.path.exists(os.path.join(out, "post", stg.SCENE_VIEW_JSON))
    before = _tree(out)
    snap = {**doe, "rank": rank, "rev": 1}
    sha0 = {d: stg.design_sha(stg.Ctx({"stage": "bd_eval", "out": out, "doe": {**snap, "design": d}}), d) for d in ids}
    r = stg.run_stage({"stage": "bd_post", "out": out, "doe": {**snap, "post_mode": "scene"}}, lambda s: None)
    assert r["files"] == ["post/" + stg.SCENE_VIEW_JSON] and r["result"] is None
    after = _tree(out)
    new = sorted(set(after) - set(before))
    assert new and all(k.startswith(GV.NEW_PREFIX) for k in new)
    assert {k: after[k] for k in before} == before                 # 기존 파일 바이트 불변
    side = _side(out)
    assert side["source"] == "regen" and set(side["packs"]) == {r_["key"] for r_ in stg.SCENE_SOURCES}
    # 두 번째 실행 = 다시 쓰지 않음(파일·바이트·mtime 그대로)
    mt = {k: os.stat(os.path.join(out, k)).st_mtime_ns for k in new}
    r2 = stg.run_stage({"stage": "bd_post", "out": out, "doe": {**snap, "post_mode": "scene"}}, lambda s: None)
    assert r2["files"] == []
    assert _tree(out) == after and {k: os.stat(os.path.join(out, k)).st_mtime_ns for k in new} == mt
    # input_sha256·이어하기 캐시 불변(설정 view3d.scene 은 해시 밖)
    for d in ids:
        c2 = stg.Ctx({"stage": "bd_eval", "out": out, "doe": {**snap, "design": d}})
        assert stg.design_sha(c2, d) == sha0[d]
        assert U.read_json(os.path.join(out, "run", "designs", d, "done.json"))["input_sha256"] == sha0[d]
        assert stg.run_stage({"stage": "bd_eval", "out": out, "doe": {**snap, "rev": 1, "design": d}},
                             lambda s: None)["reused"]
    # 빠진 씬 1개(묶음 폴더 삭제) → 기존 post_mode view3d(3D 다시 만들기)도 같은 함수로 채움
    shutil.rmtree(os.path.join(out, "post", stg.SCENE_DIR, "jd", ids[1]))
    r3 = stg.run_stage({"stage": "bd_post", "out": out, "doe": {**snap, "post_mode": "view3d"}}, lambda s: None)
    assert "post/" + stg.SCENE_VIEW_JSON in r3["files"]
    assert os.path.isfile(os.path.join(out, "post", stg.SCENE_DIR, "jd", ids[1], v3.PACK_JSON))
    assert set(_side(out)["packs"]["jig_disp"]["designs"]) == set(side["packs"]["jig_disp"]["designs"])


def test_v0251_12_supplement_needs_result(tmp_path):
    import test_jig_stages as T
    mesh, doe = T.build_same(tmp_path)
    out = str(tmp_path / "x")
    stg.run_stage({"stage": "bd_input", "out": out, "doe": doe}, lambda s: None)
    with pytest.raises(EslError) as ei:
        stg.run_stage({"stage": "bd_post", "out": out, "doe": {**doe, "rev": 1, "post_mode": "scene"}}, lambda s: None)
    assert ei.value.code == "RESULT_NOT_READY"


# ---------------------------------------------------------------- V-0251-14 독립성(정적)
def test_v0251_14_cfield_imports_and_io():
    src = open(inspect.getsourcefile(cf), encoding="utf-8").read()
    tree = ast.parse(src)
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module)
    assert mods <= {"__future__", "numpy", "esl.mech.grid_map", "esl.errors"}, mods
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "esl.mech.grid_map":
            assert {a.name for a in n.names} <= {"grid_frame", "vox_key"}
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "open" not in calls and not ({"load", "save", "savez", "savez_compressed", "loadtxt", "fromfile", "tofile"} & attrs)
    v3tree = ast.parse(open(inspect.getsourcefile(v3), encoding="utf-8").read())
    v3mods = {n.module or "" for n in ast.walk(v3tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(v3tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in v3mods if m.startswith("esl.doe") or m.endswith("doe")], v3mods


def test_v0251_14_scene_sources_table_and_no_name_branch():
    keys = [r["key"] for r in stg.SCENE_SOURCES]
    assert len(set(keys)) == len(keys) and set(keys) == {r["key"] for r in stg.RANK_SOURCES}
    for r in stg.SCENE_SOURCES:
        assert set(r) == set(stg.SCENE_COLS)
        for k in stg.SCENE_COLS:
            assert r[k] not in (None, "", ()), (r["key"], k)
        assert callable(getattr(stg, r["provider"])) and callable(getattr(stg, r["ready"]))
        assert r["c_kind"] in stg.SCENE_C_KINDS and r["values"] in stg.SCENE_VALUES and len(r["pin"]) == 2
    tags = [r["tag"] for r in stg.SCENE_SOURCES]
    assert len(set(tags)) == len(tags)
    for r in stg.RANK_SOURCES:                                      # 폴더 꼬리표 = 기존 v3d_tag(전 노드 = sv)
        s = next(x for x in stg.SCENE_SOURCES if x["key"] == r["key"])
        assert s["tag"] == (r["v3d_tag"] or "sv")
    names = {r["key"] for r in stg.SCENE_SOURCES} | {r["tag"] for r in stg.SCENE_SOURCES}
    for fn in (stg._scene_post, stg._scn_plan, stg._scn_scenes, stg._scn_sidecar, stg._post_scene):
        code = inspect.getsource(fn)
        lits = set(re.findall(r'"([a-z_]+)"', code))
        assert not (lits & names), (fn.__name__, lits & names)


# ---------------------------------------------------------------- V-0251-15 설정
def test_v0251_15_settings_defaults_and_ranges():
    assert DEFAULTS["view3d"]["scene"] == {"enabled": True, "max_mb": 1024, "diff_cell_h_mult": 2.0}
    assert settings({"bead_doe": {}})["view3d"]["scene"] == DEFAULTS["view3d"]["scene"]
    for bad in ({"max_mb": -1}, {"max_mb": 65537}, {"diff_cell_h_mult": 0.4}, {"diff_cell_h_mult": 8.5},
                {"enabled": "yes"}, {"max_mb": "1"}, {"diff_cell_h_mult": float("nan")}):
        with pytest.raises(EslError) as ei:
            settings({"bead_doe": {"view3d": {"scene": bad}}})
        assert ei.value.code == "CONFIG_INVALID"
    ok = settings({"bead_doe": {"view3d": {"scene": {"max_mb": 0, "diff_cell_h_mult": 8}}}})["view3d"]["scene"]
    assert ok["max_mb"] == 0 and ok["enabled"] is True


def test_v0251_15_settings_mirrors():
    """pydantic·yaml 2개 거울(B1 소유) — 있으면 이름·기본값이 같아야 함(없으면 B1 통합 전 — 건너뜀)."""
    exp = DEFAULTS["view3d"]["scene"]
    try:
        from esl_platform.core import config as bcfg
    except Exception:                                               # noqa: BLE001
        pytest.skip("backend 없음")
    cls = getattr(bcfg, "BeadDoeView3dSceneCfg", None)
    if cls is None:
        pytest.skip("BeadDoeView3dSceneCfg 없음(B1 통합 전)")
    assert cls().model_dump() == exp
    import yaml
    for name in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        p = os.path.join(ROOT, "config", name)
        doc = yaml.safe_load(open(p, encoding="utf-8"))
        sc_ = (((doc or {}).get("bead_doe") or {}).get("view3d") or {}).get("scene")
        assert sc_ == exp, name


def test_v0251_hash_outside_view3d_scene(tmp_path):
    """설정 view3d.scene 은 _cfg_hash 밖(V-0251-12 보조 — 값만 바꾼 Ctx 의 해시 같음)."""
    import test_jig_stages as T
    mesh, doe = T.build_same(tmp_path)
    a = stg.Ctx({"stage": "bd_eval", "out": str(tmp_path / "o"), "doe": doe})
    bd = copy.deepcopy(doe["cfg"]["bead_doe"])
    bd["view3d"] = {"scene": {"enabled": False, "max_mb": 5, "diff_cell_h_mult": 3.0}}
    b = stg.Ctx({"stage": "bd_eval", "out": str(tmp_path / "o"), "doe": {**doe, "cfg": {**doe["cfg"], "bead_doe": bd}}})
    assert stg._cfg_hash(a) == stg._cfg_hash(b)
    _ = (hashlib, json)


# ---------------------------------------------------------------- V-0251(§2.1 VL-1) 인수분해 재사용 — 씬 추가 = 후진대입만
def test_v0251_factorization_reused(tmp_path):
    """같은 스터디 BD_POST 를 씬 끔·켬으로: 분해 횟수 같음(기존 3D 의 분해를 씬 묶음이 이어 씀), 풀이 횟수만 늘어남."""
    import test_jig_stages as T
    from esl.mech import shell as msh
    t = str(tmp_path)
    doe, rank, mesh = GV.same_world(t, kind="all6")
    out, _post, _ids = T.run(os.path.join(t, "o"), doe, mesh, rank=rank)
    cnt = {"f": 0}
    of, ob = msh.ShellModel.factorize, msh.ShellModel.factorize_bc

    def f1(self, *a, **k):
        cnt["f"] += 1
        return of(self, *a, **k)

    def f2(self, *a, **k):
        cnt["f"] += 1
        return ob(self, *a, **k)
    got = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(msh.ShellModel, "factorize", f1)
        mp.setattr(msh.ShellModel, "factorize_bc", f2)
        for en in (False, True):
            bd = copy.deepcopy(doe["cfg"]["bead_doe"])
            bd["view3d"] = {"scene": {"enabled": en}}
            cnt["f"] = 0
            stg.run_stage({"stage": "bd_post", "out": out, "doe": {**doe, "cfg": {**doe["cfg"], "bead_doe": bd}, "rank": rank,
                                                                     "rev": 1}}, lambda s: None)
            got[en] = cnt["f"]
    assert got[True] == got[False] > 0, got
    side = _side(out)
    assert set(side["packs"]) == {r["key"] for r in stg.SCENE_SOURCES} and not side["warnings"]
    assert 0.0 <= side["seconds"]
