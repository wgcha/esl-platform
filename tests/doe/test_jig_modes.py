"""v0.24.5 #88 후속 — 강성 스터디의 모든 모드에서 지그 변위(jig_disp)·지그 스프링(jig_spring)이 계산 → 사이드카까지 가는지(코어 층).

사용자 요구(2026-11-24 13:23): "스터디의 모든 모드에서도 해당 지그 esl 버그가 없어야해". 모드 = 하중 전달 계획 표(transfer_plan.PLANS)
행. 계획 열 sm_jig = base 인 모드마다 새 스냅샷 기본값(v0.24.5 — 방식 [prescribed, spring], fixed 제외)으로 BD_PREP → BD_EVAL → BD_POST 를
끝까지 돌려 prep/<src>.json·per_esl C_jd·C_js·post/jig_view.json rank_views(jig_disp·jig_spring·full)를 단언하고, 경계 조건(이전·고정 출처
tie 노드, 낙하 순수 변위 강제값, 스프링 k·바닥, 법선, 3-2-1 면내 행, 면내 반력 0 등식)을 다시 계산해 대조한다. sm_jig = none 모드는
지그 미계산(블록 unsupported·사이드카 없음·순위 solve)을 단언한다(그 두 모드의 전체 파이프라인은 gmsh 가 필요 — 이 층은 계획·BD_POST 함수).

- ① case_once(같은 모델): tie = prep/fixed, 다른 부품 deck = 원 Case(이웃 쉘·솔리드 → 접촉 영역).
- ② bmesh_once(B 메시 업로드): tie = prep/fixed, deck = input/mesh 사본(업로드 rad 에 이웃 부품 → 접촉 영역).
- 새 ③ step_once(select + STEP): gmsh 대신 BD_MESH0 의 사다리 메시 함수를 합성 판(구멍 6개·리브 비드 2줄)으로 바꿈. tie = A Case
  fixed-scan(prep/a_fixed, 구멍 둘레 RBE2 6묶음)을 실제 fixed_transfer(구멍 frame 판정 → xyz_nearest)로 B 에 이전한 노드, deck 없음(패치).

``JIG_MODES_DUMP=<경로>`` 이면 모드별 실제 코어 산출(post/result.json·post/jig_view.json — sm_jig none 모드는 그 계획의 BD_POST 지그·지표
블록)을 백엔드 시험 픽스처로 저장(backend/tests/fixtures/jig_modes_v0245.json). 픽스처가 있으면 구조 서명(보기 키·지표·방식 상태)이 지금
코어와 같은지 대조한다(낡은 픽스처 방지).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys

import numpy as np
import pytest
import synth_doe as sd
import test_jig_methods as JM
import test_jig_stages as T

from esl.doe import DEFAULTS
from esl.doe import paicad_io as pio
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.library import _util as U
from esl.mech import jig_bc

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "packages", "beadgraph", "src")
if PKG not in sys.path:                                       # 새 ③ 분류 그래프(beadgraph — _bg_util 과 같은 경로)
    sys.path.insert(0, PKG)
FIXTURE = os.path.join(ROOT, "backend", "tests", "fixtures", "jig_modes_v0245.json")
SOURCES = ("jig_disp", "jig_spring")                          # 새 스냅샷 기본 방식의 출처(DEFAULTS rank.jig.methods → METHODS.src)
HOLES = [(2, 3, 1, 2), (11, 12, 1, 2), (21, 22, 1, 2), (3, 4, 14, 15), (12, 13, 14, 15), (20, 21, 14, 15)]
STEP_SP = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 3.0, "hi": 7.0}]}


def snap() -> dict:
    """새 스터디 스냅샷 doe.rank(백엔드 rank_snapshot 과 같은 키 — 설정 기본값 그대로)."""
    r = DEFAULTS["rank"]
    return {"metric": r["metric"], "lin_form": r["lin_form"], "lin_valid": float(r["lin_valid"]),
            "imbalance_warn": float(r["imbalance_warn"]), "schema": 2, "jig": copy.deepcopy(r["jig"]),
            "eval_region": {"mode": "part", "free_edge_mm": 10.0, "boxes": []}}


def test_default_methods_are_the_two_sources():
    assert tuple(jig_bc.METHODS[m]["src"] for m in DEFAULTS["rank"]["jig"]["methods"]) == SOURCES


# ---------------------------------------------------------------- 모드별 합성 세계(시험 쪽 — 코어는 계획 열만 읽음)
def _same(root, mp):
    mesh, doe = T.build_same(root)
    out, post, ids = T.run(str(root / "o"), doe, mesh, rank=snap(), groups=JM.tie_groups())
    return out, doe


def _mesh(root, mp):
    a = sd.plate(nx=30, ny=20, Lx=T.LX, Lz=T.LZ)               # A(라이브러리 엔트리) 먼저 — 마지막 plate = 모핑 기준(B)
    b = sd.plate(nx=T.NX, ny=T.NY, Lx=T.LX, Lz=T.LZ)
    lib = root / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    up = root / "up"
    up.mkdir()
    sd.write_mesh_rad(str(up / "b.rad"), b)
    T.add_neighbors(str(up / "b.rad"))                        # 업로드 사본 deck 의 다른 부품 → 접촉 영역(jig_ctx mesh)
    (up / "b.step").write_text("ISO-10303-21;\n")
    doe = {"id": "S2", "scenario": "mesh", "cfg": T.CFG_FULL, "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "mesh": {"path": str(up / "b.rad"), "upload_root": str(up), "part_title": sd.PART_TITLE},
           "step": {"path": str(up / "b.step"), "file_name": "b.step"}, "inch": 75, "load_transfer": T.LT}
    out, post, ids = T.run(str(root / "o"), doe, b, rank=snap(), rel="b.rad", groups=JM.tie_groups())
    return out, doe


def _holed():
    m = JM.PLATE0(nx=24, ny=16, Lx=300.0, Lz=200.0, holes=HOLES)
    m["x0"] = JM.bead(np.asarray(m["x0"], float), JM.D0)
    return m


def _hole_groups(mesh):
    X = np.asarray(mesh["x0"])
    dx, dz = 300.0 / 24, 200.0 / 16
    return [[int(np.argmin((X[:, 0] - i * dx) ** 2 + (X[:, 2] - j * dz) ** 2)) for i in (i0, i1) for j in (j0, j1)]
            for i0, i1, j0, j1 in HOLES]


def _select_step(root, mp):
    from esl.doe import bead_auto as ba
    from esl.doe import mesh_gmsh as mg
    b = _holed()
    mp.setattr(mg, "available", lambda: (True, "synthetic"))

    def ladder(c, row, h, ccfg, props, mode, lad, remesh_ok, avail, mesh_dir=None):   # ④ 사다리 대신 합성 판(gmsh 없이)
        os.makedirs(mesh_dir, exist_ok=True)
        mg.save_npz_det(os.path.join(mesh_dir, mg.MESH_NPZ), {k: np.asarray(b[k]) for k in mg.MESH_KEYS})
        return {"status": "READY", "mesh_method": "cad"}
    mp.setattr(stg, "_cmp_mesh_shape", ladder)
    a = _holed()
    dirs = [sd.save_entry(str(root / "lib"), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "dent"))]
    (root / "up").mkdir()
    (root / "up" / "b.step").write_text("ISO-10303-21;\nsynthetic\n")
    doe = {"id": "S3", "scenario": "select", "select_base": "step", "select_schema": 2, "bead_source": "auto",
           "cfg": {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 12.5}}},
                   "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "step": {"path": str(root / "up" / "b.step"), "file_name": "b.step"}, "inch": 75,
           "props": {"t": 1.5, "E": 210000.0, "nu": 0.3}, "load_transfer": T.LT, "rank": snap()}
    out = str(root / "_doe")

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, lambda s: None)
    run("bd_input")
    run("bd_mesh0")
    sd.write_fixed(os.path.join(out, "prep", "a_fixed"), a, _hole_groups(a), kinds=("RBE2",))   # 워커의 A Case fixed-scan
    run("bd_loads")
    auto = U.read_json(os.path.join(out, "prep", "select", ba.AUTO_SELECTION_JSON))
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": auto["selection"]}
    run("bd_matrix", rev=1, spec=STEP_SP)
    for x in U.read_json(os.path.join(out, "doe", "1", "matrix.json"))["designs"]:
        assert run("bd_eval", rev=1, design=x["id"])["status"] == "OK"
    run("bd_post", rev=1)
    return out, doe


WORLDS = {("same", None): _same, ("mesh", None): _mesh, ("select", "step"): _select_step}
BASE_KEYS = [k for k, pid in tp.PLAN_OF.items() if tp.PLANS[pid]["sm_jig"] == "base" and k in WORLDS]
NONE_KEYS = [k for k, pid in tp.PLAN_OF.items() if tp.PLANS[pid]["sm_jig"] == "none"]


def _pid(key) -> str:
    return tp.PLAN_OF[key]


def test_every_jig_plan_has_an_e2e_world():
    """계획 표의 sm_jig = base 행마다 e2e 세계가 하나 이상(새 base 계획을 더하면 여기서 실패 — 세계를 더할 것)."""
    base_plans = {pid for pid, row in tp.PLANS.items() if row["sm_jig"] == "base"}
    assert base_plans == {_pid(k) for k in BASE_KEYS}
    assert {_pid(k) for k in NONE_KEYS} == {pid for pid, row in tp.PLANS.items() if row["sm_jig"] == "none"}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    res = {}
    try:
        JM._bead_world(mp)                                     # 비드 기준 판·가짜 모핑(①②) — 새 ③ 은 기저 모핑
        for key in BASE_KEYS:
            root = tmp_path_factory.mktemp(_pid(key))
            res[key] = WORLDS[key](root, mp)
    finally:
        mp.undo()
    return res


def _ctx(out, doe):
    return stg.Ctx({"stage": "bd_post", "out": out, "doe": doe})


# ---------------------------------------------------------------- sm_jig = base: 계산 → 사이드카
@pytest.mark.parametrize("key", BASE_KEYS, ids=_pid)
def test_base_modes_compute_and_sidecar(runs, key):
    out, doe = runs[key]
    plan = tp.PLANS[_pid(key)]
    post = U.read_json(os.path.join(out, "post", "result.json"))
    for src in SOURCES:
        d = U.read_json(os.path.join(out, "prep", f"{src}.json"))
        assert d["status"] == "ok" and d["code"] is None, (src, d.get("code"), d.get("detail"))
        assert d["fix"]["source"] == plan["jig_fix"] and d["fix"]["n_jig"] > 0
        if plan["jig_ctx"] == "none":                         # 패치(deck 없음)
            assert d["surf"] is None and d["regions_from"] == "patch" and d["n_patch"] > 0
        else:                                                 # deck 출처 = 계획 열(원 Case | 업로드 사본) → 이웃 부품 접촉
            assert d["surf"]["source"] == plan["jig_ctx"] and d["regions_from"] == "contact" and d["n_contact"] > 0
        assert post["jig"]["methods"][src]["status"] == "ok"
    assert not os.path.exists(os.path.join(out, "prep", "jig.json"))            # fixed 제외(v0.24.5 기본)
    designs = U.read_json(os.path.join(out, "post", "designs.json"))["designs"]
    assert designs and all(x["status"] == "OK" for x in designs)
    for x in designs:
        per = U.read_json(os.path.join(out, "run", "designs", x["id"], "result.json"))["per_esl"]
        assert all(p["C_jd"] is not None and p["C_js"] is not None and p.get("C_jig") is None for p in per), x["id"]
    assert post["metric_effective"] == stg._jig_src_row(SOURCES[0])["metric"]  # 순위 = 첫 방식(jd)
    side = U.read_json(os.path.join(out, "post", "jig_view.json"))
    views = side["rank_views"]
    assert {s: views[s]["metric"] for s in SOURCES} == {s: stg._jig_src_row(s)["metric"] for s in SOURCES}
    assert views["full"]["metric"] == "solve"                 # 전 노드 보기(need_rank 열 — fixed 꺼도 생김)
    assert side["warnings"] == []
    for s in SOURCES:                                         # 보기 순위 = 그 출처 C 로 매긴 순위(행 = OK 안 전부)
        assert {r["id"] for r in views[s]["ranking"]} == {x["id"] for x in designs if x["id"] != stg.BASELINE}


@pytest.mark.parametrize("key", BASE_KEYS, ids=_pid)
def test_base_modes_boundary_conditions(runs, key):
    """tie 노드 = 계획 jig_fix 출처, 강제값 = 낙하 순수 변위(sm_ref 파트 Kabsch)의 법선 성분, 스프링 = 같은 행·바닥 + k = α·d̂ᵀK₀d̂,
    3-2-1 면내 3행(법선에 수직), 면내 반력 0 등식 적용(반력비 ≈ 0)."""
    out, doe = runs[key]
    plan = tp.PLANS[_pid(key)]
    c = _ctx(out, doe)
    J = DEFAULTS["rank"]["jig"]
    t, _ = sc.load_base(c.p("prep"))
    X = np.asarray(t.mesh["x0"], dtype=np.float64)
    nid = np.asarray(t.mesh["node_id"], dtype=np.int64)
    src_ids = {"fixed": lambda: np.load(os.path.join(out, "prep", "fixed", "fixed_nodes.npz"))["node_id"],
               "xfer": lambda: U.read_json(os.path.join(out, "prep", "select", "fixed_transfer.json"))["node_id"]}
    want = set(int(v) for v in src_ids[plan["jig_fix"]]())
    z0 = U.load_npz(c.p("prep", stg.SM_REF_NPZ))
    ref_e = [str(e) for e in z0["entry_ids"].tolist()]
    pos = {int(v): i for i, v in enumerate(np.asarray(z0["node_id"]).tolist())}
    order = np.asarray([pos[int(v)] for v in nid])
    zd, zs = (U.load_npz(c.p("prep", f"{s}.npz")) for s in SOURCES)
    dd, ds = (U.read_json(c.p("prep", f"{s}.json")) for s in SOURCES)
    assert np.array_equal(np.asarray(zd["node_id"]), nid)
    tie = np.asarray(zd["bc_kind"]) == jig_bc.KIND_TIE
    aux = np.asarray(zd["bc_kind"]) == jig_bc.KIND_AUX
    tn, td = np.asarray(zd["bc_node"])[tie], np.asarray(zd["bc_dir"])[tie]
    assert {int(nid[i]) for i in tn} == want and tn.size == len(want)          # 법선 1행/노드(rank 1)
    nrm = np.asarray(dd["aux321"]["plane"]["n"], dtype=np.float64)
    assert np.all(np.abs(td @ nrm) > 0.99)                                       # tie 행 = 판 법선(tie_dofs normal)
    assert dd["bc"]["tie_dofs"] == "normal" and dd["normals"]["rank_counts"]["1"] == len(want)
    ad = np.asarray(zd["bc_dir"])[aux]
    assert aux.sum() == 3 and np.all(np.abs(ad @ nrm) < 1e-9)                    # 3-2-1 면내(n₁ e₁·e₂, n₂ ê)
    eids = [str(e) for e in zd["entry_ids"].tolist()]
    for k, e in enumerate(eids):
        u_ref = np.asarray(z0["u"][ref_e.index(e)], dtype=np.float64)[order][:, :3]
        u_tgt = jig_bc.target("part", X, jig_bc.kabsch_part(X, u_ref), tn, np.ones(nid.size, bool))["u_tgt"]
        val = np.asarray(zd["bc_val"][k])
        want_v = np.einsum("ri,ri->r", np.asarray(zd["bc_dir"]), u_tgt[np.asarray(zd["bc_node"])])
        assert np.allclose(val, want_v, rtol=1e-10, atol=1e-12 * np.abs(u_tgt).max())   # 강제값 = 낙하 순수 변위 성분
        assert np.abs(val[tie]).max() > 0                                        # 값 0 이 아님(fixed 와 다름)
        sg_ = np.asarray(zs["sp_g"][k])
        assert np.allclose(sg_, val[tie], rtol=1e-12, atol=0)                    # 스프링 바닥 = 같은 강제값
        for doc in (dd, ds):
            ent = doc["entries"][k]
            assert ent["aux_eq"]["applied"] and ent["energy"]["aux_reaction_rel"] < 1e-8, (doc["method"], ent["aux_eq"])
    assert np.array_equal(np.asarray(zs["sp_node"]), tn) and np.allclose(np.asarray(zs["sp_dir"]), td)
    assert np.asarray(zs["bc_node"]).size == aux.sum()                           # 스프링 방식 = 구속은 면내 3행만
    k_want = jig_bc.spring_k(stg._jig_sm(t.mesh, c.solver_cfg()), {"node": tn, "dir": td}, mode=J["spring_k_mode"],
                             alpha=J["spring_alpha"])
    assert np.allclose(np.asarray(zs["sp_k"]), k_want, rtol=1e-12) and np.all(k_want > 0)
    assert ds["spring"]["alpha"] == J["spring_alpha"] and not ds["bc"]["shared_factor"] and dd["bc"]["shared_factor"]
    if plan["jig_fix"] == "xfer":                             # 이전 노드는 종류 거름 없음(정보)
        assert any(str(i).startswith("JIG_FIX_UNFILTERED") for i in dd["info"])


# ---------------------------------------------------------------- sm_jig = none: 지그 미계산(계획 열)
def _none_ctx(tmp_path, key):
    scn, sb = key
    doe = {"id": "N", "scenario": scn, "cfg": T.CFG_FULL, "entries": [], "rank": snap(), "load_transfer": T.LT,
           **({"select_base": sb} if sb else {})}
    return stg.Ctx({"stage": "bd_post", "out": str(tmp_path / "_doe"), "doe": doe})


@pytest.mark.parametrize("key", NONE_KEYS, ids=_pid)
def test_none_modes_do_not_compute_jig(tmp_path, key):
    c = _none_ctx(tmp_path, key)
    S_ = stg._sm_post(c)
    assert stg._jig(c) is None and S_["metric_effective"] == "solve" and S_["cross_mesh"] is True
    blk, warns = stg._jig_post(c, S_, {})
    assert blk["status"] == "unsupported" and blk["code"] == "JIG_UNSUPPORTED" and blk["entries"] == []
    assert set(blk["methods"]) == set(SOURCES)
    assert stg._jig_extras(c, None, {}, [], None, S_, shown=[], v3_jig=None, source="bd_post") is None   # 사이드카 없음
    assert not os.path.exists(c.p("post", stg.JIG_VIEW_JSON))


# ---------------------------------------------------------------- 백엔드 픽스처(실제 코어 산출) — 생성·낡음 대조
def _sig(result: dict, side: dict | None) -> dict:
    jig = result.get("jig") or {}
    return {"metric_effective": result.get("metric_effective"), "cross_mesh": result.get("cross_mesh"),
            "jig": [jig.get("status"), jig.get("code"), sorted((k, v["status"]) for k, v in (jig.get("methods") or {}).items())],
            "views": sorted((k, v["metric"]) for k, v in ((side or {}).get("rank_views") or {}).items())}


def _docs(runs, tmp_path) -> dict:
    modes = {}
    for key in BASE_KEYS:
        out, doe = runs[key]
        modes[_pid(key)] = {"scenario": key[0], "inputs": {"select_base": key[1]} if key[1] else {}, "sm_jig": "base",
                            "result": U.read_json(os.path.join(out, "post", "result.json")),
                            "side": U.read_json(os.path.join(out, "post", "jig_view.json"))}
    base = modes[_pid(BASE_KEYS[0])]["result"]
    for key in NONE_KEYS:                                     # 전체 파이프라인은 gmsh — 결과 = ① 결과 + 이 계획의 BD_POST 지그·지표 블록
        c = _none_ctx(tmp_path / _pid(key), key)
        S_ = stg._sm_post(c)
        blk, warns = stg._jig_post(c, S_, {})
        r = {**base, "scenario": key[0], "jig": blk, "metric": S_["metric"], "metric_effective": S_["metric_effective"],
             "cross_mesh": S_["cross_mesh"], "warnings": list(base.get("warnings") or []) + warns + stg._sm_post_warn(S_)}
        modes[_pid(key)] = {"scenario": key[0], "inputs": {"select_base": key[1]} if key[1] else {}, "sm_jig": "none",
                            "result": U.jsonable(r), "side": None}
    return {"schema": 1, "made_by": "tests/doe/test_jig_modes.py (JIG_MODES_DUMP)", "modes": modes}


def test_backend_fixture_matches_core(runs, tmp_path):
    doc = _docs(runs, tmp_path)
    dump = os.environ.get("JIG_MODES_DUMP")
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    if not os.path.isfile(FIXTURE):
        pytest.skip("백엔드 픽스처 없음 — JIG_MODES_DUMP 로 생성")
    with open(FIXTURE, encoding="utf-8") as fh:
        fx = json.load(fh)["modes"]
    now = {pid: _sig(m["result"], m["side"]) for pid, m in doc["modes"].items()}
    old = {pid: _sig(m["result"], m["side"]) for pid, m in fx.items()}
    assert now == old, "코어 산출 구조가 백엔드 픽스처와 다름 — JIG_MODES_DUMP=backend/tests/fixtures/jig_modes_v0245.json 로 다시 생성"
    shutil.rmtree(tmp_path, ignore_errors=True)
