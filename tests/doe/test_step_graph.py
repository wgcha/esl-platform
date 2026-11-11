"""V-SG-1~3·5 (esl_step_graph.md): 새 ③ = select + select_base step.

- 단계 흐름(작은 판 STEP — 빠름): BD_INPUT·BD_MESH0(④ 사다리 → prep/mesh0)·BD_LOADS(분류·이전·seed)·행렬·평가·받기(메시만).
- V-SG-5 하중·지지 = 같은 메시를 ② select(B 메시 rad)로 넣은 값과 같음.
- V-SG-3 삼각형: 주입 ESL_TEST_MESH_FAIL=cad,remesh → 사다리 tria → STEP_GRAPH_TRIA(경고) / tria_policy block.
- (slow) V-SG-1·2·3b·3c H6 STEP → 사다리 cad 메시 → 분류 V-BG-1 기준·모핑 레시피, 삼각형 대리.
"""
import json
import os

import numpy as np
import pytest
import synth_compare as scmp
import synth_doe as sd
import synth_step_graph as ssg

from esl.doe import bead_auto as ba
from esl.doe import bead_graph as bgr
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import settings
from esl.doe import stages as stg
from esl.doe import step_graph as sg
from esl.errors import EslError

pytestmark = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
LX, LZ = 200.0, 150.0
PROPS = {"t": 2.0, "E": 205000.0, "nu": 0.3}


def _bd(**extra):
    b = {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 5.0}}}
    for k, v in extra.items():
        b[k] = v
    return b


def _study(tmp_path, step_path, a_mesh, *, bead_source="auto", bead_doe=None, **kw):
    d0 = sd.save_entry(str(tmp_path / "lib"), "E0", a_mesh, "bend", 1.0, seed=0)[0]
    return {"id": "S1", "scenario": "select", "select_base": "step", "select_schema": 2, "bead_source": bead_source,
            "cfg": {"bead_doe": bead_doe or _bd(), "opt_run": {"solver": {"backend": "superlu"}}},
            "entries": [{"id": "E0", "dir": d0}], "step": {"path": step_path, "file_name": os.path.basename(step_path)},
            "inch": 75, "props": PROPS, **kw}


def _runner(out, doe, log=None):
    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, (log or []).append)
    return run


@pytest.fixture(scope="module")
def plate(tmp_path_factory):
    d = tmp_path_factory.mktemp("sgp")
    a = sd.plate(nx=20, ny=15, Lx=LX, Lz=LZ)
    step = scmp.plate_step(str(d / "b.step"), 2, Lx=LX, Lz=LZ, depth=5.0)
    X = a["x0"]
    groups = [list(np.argsort(np.linalg.norm(X - X[i], axis=1))[:3]) for i in (0, len(X) - 1)]
    return a, step, groups


def test_stages_auto(plate, tmp_path):
    a, step, groups = plate
    doe = _study(tmp_path, step, a)
    out = tmp_path / "_doe" / "S1"
    run = _runner(out, doe)
    r = run("bd_input")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["select_base"] == "step" and inp["select_schema"] == 2 and inp["props"] == PROPS and r["part_id"] is None
    assert stg.select_prep_info(str(out))["step_rel"] == inp["step"]["rel"]
    m0 = run("bd_mesh0")
    assert m0["mesh"]["method"] == "cad" and (out / "prep" / "mesh0" / "mesh.npz").is_file()
    assert not (out / "prep" / "shapes").exists()                                   # ④ 폴더 안 씀(mesh_dir)
    bj = json.loads((out / "prep" / "base.json").read_text(encoding="utf-8"))
    assert bj["scenario"] == "select" and bj["mesh_method"] == "cad" and bj["h"] == 5.0 and bj["region"]["n_out"] == 0
    assert sg.load_region(str(out / "prep")) is None                                # 영역 = 전체 → 키 없음
    sd.write_fixed(str(out / "prep" / "a_fixed"), a, groups)
    r = run("bd_loads")
    assert r["fixed"]["source"] == "a_transfer" and r["fixed"]["xfer"]["method"] == "xyz_nearest"
    assert r["fixed"]["xfer"]["frame_ok"] is True and r["graph"]["ok"] and r["auto"]["source"] == "graph"
    sdir = out / "prep" / "select"
    xb = (sdir / sg.XFER_JSON).read_bytes()
    auto = json.loads((sdir / ba.AUTO_SELECTION_JSON).read_bytes())
    assert auto["fixed"] == {"source": "a_transfer", "method": "xyz_nearest", "n_nodes": 6}
    assert auto["selection"]["fixed_user"]["q"]                                      # seed 고정 층(편집 가능)
    man = json.loads((sdir / "select_manifest.json").read_text(encoding="utf-8"))
    assert man["fixed"]["source"] == "a_transfer" and man["fixed"]["scan_n"] == 0 and man["fixed"]["xfer_n"] == 6
    run("bd_loads")                                                                  # 결정적·중복 없음
    assert (sdir / sg.XFER_JSON).read_bytes() == xb
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["fixed"]["xfer"]["matched"] == 2 and inp["mesh"]["method"] == "cad"
    assert not any(isinstance(w, str) and w.startswith("FIXED_INFO_MISSING") for w in inp["warnings"])
    sel = auto["selection"]
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": sel}
    run("bd_matrix", rev=1, spec={"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 3.0, "hi": 7.0}]})
    bjs = json.loads(next((out / "select").glob("*/basis.json")).read_text(encoding="utf-8"))
    assert bjs["graph_algo"] == bgr.GRAPH_ALGO
    m = json.loads((out / "doe" / "1" / "matrix.json").read_text(encoding="utf-8"))
    for x in m["designs"]:
        e = run("bd_eval", rev=1, design=x["id"])
        assert e["status"] in ("OK", "FAILED_SOLVE", "FAILED_MESH", "SKIPPED_FIXED")
    post = run("bd_post", rev=1)["result"]
    assert post.get("noise_floor") is None                                           # 같은 메시(SG-D-10 — ② 와 같음)
    rep = (out / "report.html").read_text(encoding="utf-8")
    assert "③ 그래프(기준 메시 기저 모핑, 메시 방식 cad)" in rep                    # SG-D-11 방법 1줄
    for did in os.listdir(out / "best"):
        names = set(os.listdir(out / "best" / did))
        assert {"ch_r.rad", "ch_r.fem", "values.json"} <= names
        assert not names & {"sample.step", "sample.brep", "include"}                  # D2 메시만
        rad = (out / "best" / did / "ch_r.rad").read_text(encoding="ascii", errors="replace")
        assert "/PART" in rad and "/SHELL" in rad                                    # 기저 모핑 좌표 export_mesh


def test_manual_seed_and_no_a_case(plate, tmp_path):
    """manual 도 seed(빈 비드 + fixed_user, source fixed_transfer), A Case 없음 = FIXED_XFER_NONE{A_CASE_MISSING}."""
    a, step, _groups = plate
    doe = _study(tmp_path, step, a, bead_source="manual")
    out = tmp_path / "_doe" / "S1"
    run = _runner(out, doe)
    run("bd_input")
    run("bd_mesh0")
    r = run("bd_loads")
    assert r["fixed"] == {"source": "none", "n": 0, "xfer": {"method": "none", "matched": 0, "unmatched": 0,
                                                              "frame_ok": True}}
    assert any(s.startswith("FIXED_XFER_NONE") for s in r["info"])
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert {"code": "FIXED_XFER_NONE", "reason": "A_CASE_MISSING"} in inp["info"]
    auto = json.loads((out / "prep" / "select" / ba.AUTO_SELECTION_JSON).read_bytes())
    assert auto["source"] == "fixed_transfer" and auto["selection"]["beads"] == []
    assert auto["selection"]["fixed_user"] == {"q": [], "t": []} and auto["graph_sha256"] == r["graph"]["sha256"]
    assert ba.read_auto_selection(str(out / "prep" / "select" / ba.AUTO_SELECTION_JSON)) == auto
    off = _bd(select={"step_graph": {"fixed_transfer": {"enabled": False}}})
    doe2 = _study(tmp_path / "x", step, a, bead_source="manual", bead_doe=off)
    run2 = _runner(tmp_path / "x" / "o", doe2)
    run2("bd_input")
    run2("bd_mesh0")
    r2 = run2("bd_loads")
    assert not (tmp_path / "x" / "o" / "prep" / "select" / sg.XFER_JSON).exists()
    assert any("DISABLED" in s for s in r2["info"])


def test_schema1_rejected(plate, tmp_path):
    a, step, _ = plate
    doe = _study(tmp_path, step, a)
    doe["select_schema"] = 1
    with pytest.raises(EslError) as ei:
        _runner(tmp_path / "o", doe)("bd_input")
    assert ei.value.code == "INVALID_PARAMS"


def test_loads_equal_mesh_base(plate, tmp_path):
    """V-SG-5: step 기준 하중·지지 = 같은 메시를 ② select(select_base mesh, rad 왕복)로 넣은 값(노드별 ± 1e-12)."""
    a, step, _ = plate
    doe = _study(tmp_path, step, a, bead_source="manual")
    out = tmp_path / "_doe" / "S1"
    run = _runner(out, doe)
    run("bd_input")
    run("bd_mesh0")
    run("bd_loads")
    t, _ = sc.load_base(str(out / "prep"))
    _, l1 = sc.load_loads(str(out / "prep"))
    mesh = mg.load_mesh(str(out / "prep" / "mesh0"))
    up = tmp_path / "up"
    up.mkdir()
    rad = sd.write_mesh_rad(str(up / "b.rad"), mesh)
    doe2 = {k: v for k, v in doe.items() if k not in ("step", "select_base", "props")}
    doe2.update(select_base="mesh", mesh={"path": rad, "upload_root": str(up), "part_title": sd.PART_TITLE})
    out2 = tmp_path / "_doe" / "S2"
    run2 = _runner(out2, doe2)
    run2("bd_input")
    run2("bd_loads")
    t2, _ = sc.load_base(str(out2 / "prep"))
    _, l2 = sc.load_loads(str(out2 / "prep"))
    assert t.supports == t2.supports
    assert np.array_equal(t.mesh["node_id"], t2.mesh["node_id"])
    for (e1, f1), (e2, f2) in zip(l1, l2):
        assert e1 == e2 and np.abs(f1 - f2).max() <= 1e-12 * max(1.0, np.abs(f1).max())


def _plate_xy(nx=20, ny=15, Lx=200.0, Ly=150.0):
    xs, ys = np.linspace(0, Lx, nx + 1), np.linspace(0, Ly, ny + 1)
    X = np.array([[x, y, 0.0] for y in ys for x in xs])
    C = np.array([[j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i]
                  for j in range(ny) for i in range(nx)])
    m = ssg.esl_mesh(X, C)
    m["thickness"] = np.full(C.shape[0], 2.0)
    return m


def test_tria_injection(tmp_path, monkeypatch):
    """V-SG-3a·d: cad·재메시 실패 주입 → 사다리 tria → 준비 계속 + STEP_GRAPH_TRIA·MESH_TRIA_FALLBACK, 그래프 생성;
    tria_policy block → STEP_GRAPH_TRIA_BLOCKED."""
    step = scmp.dimple_plate_step(str(tmp_path / "up" / "d.step"), [(100.0, 75.0, 30.0, 4.0)])
    a = _plate_xy()
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "cad,remesh")
    doe = _study(tmp_path, step, a, bead_source="manual", mesh_mode="auto",
                 mesh_ladder=["cad", "freeform", "tria"])
    out = tmp_path / "_doe" / "S1"
    run = _runner(out, doe)
    run("bd_input")
    m0 = run("bd_mesh0")
    assert m0["mesh"]["method"] == "tria" and m0["mesh"]["tri_frac"] > 0.5
    assert any(w.startswith("STEP_GRAPH_TRIA") for w in m0["warnings"])
    assert any(w.startswith("MESH_TRIA_FALLBACK") for w in m0["warnings"])
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    tw = [w for w in inp["warnings"] if isinstance(w, dict) and w.get("code") == "STEP_GRAPH_TRIA"]
    assert tw and tw[0]["mesh_method"] == "tria"
    r = run("bd_loads")
    assert r["graph"]["ok"]
    blk = _bd(select={"step_graph": {"tria_policy": "block"}})
    doe2 = _study(tmp_path / "b", step, a, bead_source="manual", bead_doe=blk, mesh_mode="auto",
                  mesh_ladder=["cad", "freeform", "tria"])
    run2 = _runner(tmp_path / "b" / "o", doe2)
    run2("bd_input")
    with pytest.raises(EslError) as ei:
        run2("bd_mesh0")
    assert ei.value.code == "STEP_GRAPH_TRIA_BLOCKED"


def test_tria_check_unit():
    m = _plate_xy(4, 3)
    assert sg.tria_check(m, "cad", None) is None
    assert sg.tria_check(m, "tria", None)["code"] == "STEP_GRAPH_TRIA"
    t = ssg.tri_split(m)
    assert sg.tria_check(t, "cad", None)["tri_frac"] == 1.0


# ====================================================================== slow: H6 STEP (V-SG-1·2·3b·3c)
def _cache_dir():
    d = os.environ.get("ESL_SG_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "esl_step_graph")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture(scope="module")
def h6(tmp_path_factory):
    """H6 STEP(캐시) → 단계 BD_MESH0(④ 사다리, h 3 mm 기본 프로필) → 기준 메시 + 분류(classify_full, step 상한)."""
    import gmsh
    step = os.path.join(_cache_dir(), f"h6_sheet_gmsh{gmsh.__version__}.step")
    if not os.path.isfile(step):
        ssg.h6_step(step)
    a_mesh, fx0 = ssg.h6_fixture_mesh()
    d = tmp_path_factory.mktemp("sgh6")
    ent = d / "lib"
    from esl.library import entry as en
    e = ssg.LightEntry("E0", a_mesh, inch=55)
    raw = dict(e.raw)
    raw["elem_mid"] = np.ones(a_mesh["elem_type"].size, np.int64)
    meta = dict(e.meta)
    meta["model"] = {"inch": 55, "part_id": 7, "part_title": "chassis rear", "max_ids": {}}
    raw["is_bc"] = np.zeros(raw["node_id"].size, bool)
    raw["support_node_id"] = np.zeros(0, np.int64)
    raw["support_dof"] = np.zeros(0, dtype="<U3")
    raw["u_rel"] = np.zeros_like(raw["f"])
    en.save(en.LibraryEntry(meta=meta, summary=e.summary, raw=raw), str(ent / "E0"))
    doe = {"id": "H6", "scenario": "select", "select_base": "step", "select_schema": 2, "bead_source": "auto",
           "cfg": {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}, "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": "E0", "dir": str(ent / "E0")}], "step": {"path": step, "file_name": "h6_sheet.step"},
           "inch": 55, "props": PROPS}
    out = d / "_doe" / "H6"
    run = _runner(out, doe)
    run("bd_input")
    m0 = run("bd_mesh0")
    t, _ = sc.load_base(str(out / "prep"))
    return {"mesh": dict(t.mesh), "m0": m0, "out": out, "a": a_mesh, "fx0": fx0, "run": run}


def _classify(mesh, fixed_idx):
    import beadgraph
    from beadgraph.classify import classify_full
    from esl.doe import bead_graph as bg_
    gc = bg_.graph_cfg(settings({"bead_doe": {"enabled": True}}))
    gc["limits"] = dict(gc["limits"], max_elems=600000, timeout_s=300)
    C = bg_._conn(mesh)
    _ = beadgraph
    return classify_full(np.asarray(mesh["x0"]), C, np.asarray(fixed_idx, np.int64), gc)


@pytest.mark.slow
def test_h6_step_classify(h6):
    """V-SG-1: H6 STEP → cad 메시 → 분류 = V-BG-1 기준(정답 = 형상 기준 라벨)."""
    from beadgraph.testing import conformance as cf
    from beadgraph.testing.evaluate import evaluate_h6
    mesh = h6["mesh"]
    assert h6["m0"]["mesh"]["method"] in ("cad", "cad_relaxed", "refine")
    fx = ssg.h6_truth(mesh)
    g, lab, aux = _classify(mesh, fx["fixed"])
    r = evaluate_h6(g, lab, fx, aux["seg_raw"])
    print("H6-STEP", json.dumps({k: r[k] for k in ("n_elems", "class_acc", "floor_piece_acc", "wall_owner_acc",
                                                     "tier_acc", "segment_elem_acc")}),
          r["segments"]["found_iou50"], r["junctions"], r["islands"], r["holes"])
    bad = [b for b in cf.check_h6(r) if not b.startswith("extra segments")]
    assert not bad, bad


@pytest.mark.slow
def test_h6_step_morph(h6):
    """V-SG-2: V-BG-5 레시피 (a)~(g) 를 사다리 cad 메시에서 — 뒤집힘 0·바깥 ≤ 1e-9·달성·섬 잔차·고정 이동."""
    from beadgraph.testing import conformance as cf
    mesh = h6["mesh"]
    fx = ssg.h6_truth(mesh)
    g, lab, _aux = _classify(mesh, fx["fixed"])
    fxm = {"x0": np.asarray(mesh["x0"]), "conn": np.asarray(bgr._conn(mesh)), "fixed": fx["fixed"]}
    bad = []
    for name, beads in cf.h6_recipes(g, lab, fxm).items():
        r = cf.run_recipe(g, lab, fxm, beads)
        bad += cf.check_h6_morph(name, r, g, lab, fxm)
    assert not bad, bad


@pytest.mark.slow
def test_h6_step_tria_proxy(h6):
    """V-SG-3b·c: 사다리 메시 짧은 대각선 분할 → class ≥ 99 %·벽 소유 ≥ 97.5 %, 수 같음; 레시피 a·d·f·g 통과,
    b·c·e 는 판정이 잡음(바깥 이동·뒤집힘 — 조용한 오류 없음)."""
    from beadgraph.testing import conformance as cf
    from beadgraph.testing.evaluate import evaluate_h6
    t = ssg.tri_split(h6["mesh"])
    fx = ssg.h6_truth(t)
    g, lab, aux = _classify(t, fx["fixed"])
    r = evaluate_h6(g, lab, fx, aux["seg_raw"])
    print("H6-STEP-TRIA", r["class_acc"], r["wall_owner_acc"], r["segments"]["found_iou50"])
    assert r["class_acc"] >= 0.99 and r["wall_owner_acc"] >= 0.975
    fxm = {"x0": np.asarray(t["x0"]), "conn": np.asarray(bgr._conn(t)), "fixed": fx["fixed"]}
    for name, beads in cf.h6_recipes(g, lab, fxm).items():
        rr = cf.run_recipe(g, lab, fxm, beads)
        bad = cf.check_h6_morph(name, rr, g, lab, fxm)
        if name in ("a", "d", "f", "g"):
            assert not [b for b in bad if "inverted" in b or "outside" in b], (name, bad)
        else:
            caught = rr["inverted"] or rr["outside"]["max_mm"] > 1e-9
            assert caught or not bad, (name, bad)                      # 실패하면 판정이 반드시 잡음


@pytest.mark.slow
def test_h6_step_loads_transfer(h6):
    """BD_LOADS on the H6 STEP mesh: frame 일치 → xyz_nearest, 고정 구멍 노드 이전, 그래프·seed."""
    out, a, fx0 = h6["out"], h6["a"], h6["fx0"]
    sd.write_fixed(str(out / "prep" / "a_fixed"), a, [list(map(int, g)) for g in ssg.h6_clusters(a, fx0)])
    r = h6["run"]("bd_loads")
    print("H6-STEP-LOADS", r["graph"], r["fixed"])
    assert r["graph"]["ok"] and r["fixed"]["xfer"]["frame_ok"] and r["fixed"]["xfer"]["method"] == "xyz_nearest"
    assert r["fixed"]["xfer"]["unmatched"] == 0 and r["auto"]["n_beads"] > 0
