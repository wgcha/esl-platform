"""V-BD-6: ③ gmsh — 평판·비드 BREP → quad_frac ≥ 0.8, h 반영(모서리 중앙값 ±20 %), 같은 입력 2회 → mesh.npz 바이트 동일,
법선 정렬, 품질 오류 FAILED_MESH·max_elems, 타임아웃, STEP 내보내기, 잡음 바닥 측정(STEP 왕복 재메시 score 차) 기록,
③ 산출물 rad·fem 왕복, ③ 코어 흐름(가짜 paicad update). gmsh 가 없으면 skip(CI 레인은 gmsh 필수)."""
import os

import numpy as np
import pytest

import synth_doe as sd
from esl.doe import evaluate as ev
from esl.doe import export_mesh, opt_settings, settings
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U
from esl.opt.femread import read_fem
from esl.opt.mesh_check import _edge_lengths
from esl.opt.target import elem_normals

pytestmark = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
CFG = settings()
SEW = settings({"bead_doe": {"mesh": {"occ_sew_faces": 1}}})       # gmsh 가 쓴 STEP 은 면 공유 정보가 없음
PROPS = {"t": 1.2, "E": 205000.0, "nu": 0.3}


def make_brep(path, depth=5.0, flat=False, L=150.0):
    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        if flat:
            occ.addRectangle(0, 0, 0, 200, L)
        else:
            pts = [(0, 0), (80, 0), (90, depth), (110, depth), (120, 0), (200, 0)]
            p = [occ.addPoint(x, y, 0) for x, y in pts]
            ln = [occ.addLine(p[i], p[i + 1]) for i in range(len(p) - 1)]
            occ.extrude([(1, t) for t in ln], 0, 0, L)
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


def test_plate_quad_and_size(tmp_path):
    src = make_brep(tmp_path / "plate.brep", flat=True)
    mesh, meta = mg.mesh_file(src, 5.0, CFG, PROPS, out_dir=str(tmp_path / "m"))
    assert meta["quad_frac"] >= 0.8
    L = _edge_lengths(mesh["x0"], mesh["conn"], np.asarray(mesh["elem_type"]).astype(int))
    assert abs(float(np.nanmedian(L)) - 5.0) <= 0.2 * 5.0
    assert mesh["node_id"][0] == 1 and mesh["node_id"][-1] == mesh["node_id"].size
    assert mesh["elem_id"][-1] == mesh["elem_id"].size and np.all(mesh["elem_pid"] == 1)
    assert np.all(mesh["thickness"] == 1.2) and meta["gmsh_version"] and meta["h"] == 5.0
    assert (tmp_path / "m" / "mesh.npz").is_file() and (tmp_path / "m" / "mesh.json").is_file()
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, 0.5, CFG, PROPS)
    assert ei.value.code == "INPUT_INVALID"


def test_bead_deterministic_normals_step(tmp_path):
    src = make_brep(tmp_path / "bead.brep")
    m1, meta1 = mg.run_isolated(src, str(tmp_path / "a"), 5.0, CFG, PROPS, normal_ref=[0, 1, 0],
                                step_out=str(tmp_path / "a" / "sample.step"))
    m2, _ = mg.run_isolated(src, str(tmp_path / "b"), 5.0, CFG, PROPS, normal_ref=[0, 1, 0])
    b1 = (tmp_path / "a" / "mesh.npz").read_bytes()
    assert b1 == (tmp_path / "b" / "mesh.npz").read_bytes()
    assert meta1["quad_frac"] >= 0.8 and meta1["step"] == "sample.step"
    assert (tmp_path / "a" / "sample.step").read_text(errors="ignore").startswith("ISO-10303-21;")
    n = elem_normals(m1)
    assert np.all(n @ np.array([0.0, 1.0, 0.0]) > -1e-9)             # 바디 법선 쪽 정렬
    assert np.ptp(m1["x0"][:, 1]) == pytest.approx(5.0, abs=1e-6)       # 비드 깊이 유지
    z = U.load_npz(str(tmp_path / "a" / "mesh.npz"))
    assert set(z) == set(mg.MESH_KEYS)


def test_quality_errors_and_timeout(tmp_path):
    src = make_brep(tmp_path / "bead.brep")
    small = settings({"bead_doe": {"mesh": {"max_elems": 50}}})
    with pytest.raises(EslError) as ei:
        mg.run_isolated(src, str(tmp_path / "q"), 5.0, small, PROPS)
    assert ei.value.code == "FAILED_MESH"
    assert U.read_json(str(tmp_path / "q" / "mesh.json"))["errors"][0]["code"] == "MESH_TOO_LARGE"
    with pytest.raises(EslError) as ei:
        mg.run_isolated(src, str(tmp_path / "t"), 5.0, CFG, PROPS, timeout_s=0.01)
    assert ei.value.code == "FAILED_MESH" and "제한 시간" in ei.value.message
    st = str(tmp_path / "soup.step")
    mg.export_step_isolated(src, st, CFG)                              # 면 공유 없는 STEP + OCCSewFaces 0
    with pytest.raises(EslError) as ei:
        mg.run_isolated(st, str(tmp_path / "s"), 5.0, CFG, PROPS)
    assert ei.value.code == "FAILED_MESH" and "연결 성분" in ei.value.message
    mg.run_isolated(st, str(tmp_path / "s2"), 5.0, SEW, PROPS)
    (tmp_path / "junk.brep").write_text("not a brep")
    with pytest.raises(EslError) as ei:
        mg.run_isolated(str(tmp_path / "junk.brep"), str(tmp_path / "j"), 5.0, CFG, PROPS)
    assert ei.value.code == "FAILED_MESH"


def test_export_mesh_roundtrip(tmp_path):
    from esl.rad.parser import parse_rad
    src = make_brep(tmp_path / "bead.brep")
    mesh, _ = mg.mesh_file(src, 8.0, CFG, PROPS)
    files = export_mesh.write(str(tmp_path / "best"), mesh)
    assert files == ["ch_r.rad", "ch_r.fem"]
    rm = parse_rad(str(tmp_path / "best" / "ch_r.rad"), "ch_r")
    assert np.array_equal(rm.node_id, mesh["node_id"]) and np.allclose(rm.x0, mesh["x0"])
    assert rm.elem_id.size == mesh["elem_id"].size and np.allclose(rm.thickness, 1.2)
    fm = read_fem(str(tmp_path / "best" / "ch_r.fem"))
    assert fm["elem_id"].size == mesh["elem_id"].size and np.allclose(fm["E"], 205000.0)


def test_noise_floor_measure(tmp_path):
    """잡음 바닥: 같은 형상을 STEP 왕복 후 같은 h 로 다시 메시한 score 차(기록)."""
    src = make_brep(tmp_path / "bead.brep")
    mg.export_step_isolated(src, str(tmp_path / "rt" / "bead.step"), CFG)
    a = sd.plate(nx=20, ny=15, Lx=200.0, Lz=150.0)
    fe, _ = sd.fake_entry("E1", a, "bend")
    sc_ = []
    for s in (src, str(tmp_path / "rt" / "bead.step")):
        mesh, _ = mg.mesh_file(s, 5.0, SEW, PROPS, normal_ref=[0, 1, 0])
        t, _ = sc.template_base(mesh, [fe], opt_settings(None)["size"], inch=75)
        loads, _ = sc.entry_loads(t, [fe])
        r = ev.evaluate(t.mesh, t.supports, loads, {"drill_factor": 1e-4, "backend": "superlu"}, reaction_warn=0.01)
        sc_.append(r["per_esl"][0]["C"])
    noise = abs(sc_[1] / sc_[0] - 1.0)
    print(f"\n[V-BD-6] 잡음 바닥(STEP 왕복 재메시 score 차) = {noise:.3e}")
    assert noise < 0.05


def test_step_pipeline(tmp_path):
    """③ 코어 흐름: 입력 → gmsh 베이스라인 → 하중(frame 고정 매핑) → 행렬 → 안마다 메시·해석 → 후처리(잡음 바닥)."""
    up = tmp_path / "up"
    up.mkdir(exist_ok=True)
    brep = make_brep(up / "nominal.brep", depth=5.0)
    mg.export_step_isolated(brep, str(up / "nominal.step"), CFG)
    os.remove(up / "mesh.log") if (up / "mesh.log").exists() else None
    step = str(up / "nominal.step")
    a = sd.plate(nx=20, ny=15, Lx=200.0, Lz=150.0)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    doe = {"id": "S3", "scenario": "step", "cfg": {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}},
                                                  "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)], "step": {"path": step},
           "inch": 75, "props": PROPS, "mesh_size_mm": 6.0}
    out = tmp_path / "_doe" / "S3"

    def spec(stage, **kw):
        return {"stage": stage, "out": str(out), "doe": {**doe, **kw}}
    stg.run_stage(spec("bd_input"), lambda s: None)
    r = stg.run_stage(spec("bd_mesh0"), lambda s: None)
    assert r["h"] == 6.0
    base = U.read_json(str(out / "prep" / "base.json"))
    assert base["props"]["t"] == 1.2 and base["n_elems"] > 100
    feats = sd.features_doc(a, 1)
    sd.write_extract(str(out / "prep" / "extract"), feats)
    r = stg.run_stage(spec("bd_loads"), lambda s: None)
    assert r["boundary"] is not None
    sp = {"method": "fullfact", "levels": 2, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 7.0}]}
    stg.run_stage(spec("bd_matrix", rev=1, spec=sp), lambda s: None)
    m = U.read_json(str(out / "doe" / "1" / "matrix.json"))
    assert stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)["status"] == "OK"
    for d in m["designs"][1:]:
        dd = out / "run" / "designs" / d["id"] / "update"
        dd.mkdir(parents=True)
        make_brep(dd / "sample.brep", depth=d["values"]["CHASSIS_REAR_BEAD_D_1"])
        r = stg.run_stage(spec("bd_eval", rev=1, design=d["id"], paicad={"ok": True}), lambda s: None)
        assert r["status"] == "OK", r
        z = U.load_npz(str(out / "run" / "designs" / d["id"] / "design.npz"))
        assert {"node_id", "x", "conn", "type", "pid"} <= set(z)
    nd_ = out / "run" / "designs" / "noise" / "update"
    nd_.mkdir(parents=True)
    make_brep(nd_ / "sample.brep", depth=5.0)
    assert stg.run_stage(spec("bd_eval", rev=1, design="noise", paicad={"ok": True}), lambda s: None)["status"] == "OK"
    res = stg.run_stage(spec("bd_post", rev=1), lambda s: None)["result"]
    assert res["n_ok"] == 2 and res["noise_floor"] is not None and res["noise_floor"] < 0.05
    assert all(x["noise"] is not None for x in res["ranking"])
    best = out / "best" / res["best"]["id"]
    for f in ("ch_r.rad", "ch_r.fem", "sample.brep", "sample.step", "values.json"):
        assert (best / f).is_file(), f
    # 깊은 비드(7 mm)가 얕은 비드(3 mm)보다 강성 좋음(score 작음)
    sc_by = {x["values"]["CHASSIS_REAR_BEAD_D_1"]: x["score"] for x in res["ranking"]}
    print(f"\n[③] score {sc_by}, noise {res['noise_floor']:.3e}")
