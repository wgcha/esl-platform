"""v0.16.0 ④ 세분화 폴백 Core(esl_compare_mesh_options.md C2-D-18~22, §4A, V-C2-13·14·15).

사다리 실행(시도 폴더·성공본 교체·경고)은 워커 몫이라, 여기서는 Core 조각을 워커 순서대로 이어 붙여 확인한다:
cad 실패(면 기록 ``_fail_info``) → ``plan`` → ``attempt_cfg`` → ``mesh_file``(size_fields). 고장 주입은 monkeypatch 로만."""
import json

import numpy as np
import pytest

import synth_compare as scmp
from esl.doe import mesh_gmsh as mg
from esl.doe import mesh_refine as mr
from esl.doe import scenario as sc
from esl.doe import settings
from esl.errors import EslError

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
PROPS = {"t": 1.0, "E": 205000.0, "nu": 0.3}
H = 3.0
LIMIT = 2.5                                   # 주입: 이 크기보다 큰 요소로는 대상 면이 메시되지 않음


def _cfg(refine=None, fallback=None, **mesh):
    c = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                              "compare": {"refine": refine or {}}}}))
    if fallback is not None:
        c["mesh"]["fallback"] = dict(c["mesh"]["fallback"], **fallback)
    c["mesh"].update(mesh)
    return c


def _inject(monkeypatch):
    """원통 벽(대상 면)은 그 면 크기(Constant Field VIn 또는 MeshSizeMax)가 LIMIT 보다 크면 실패."""
    import gmsh
    real = gmsh.model.mesh.generate
    fld = gmsh.model.mesh.field

    def fake(dim=3):
        for _d, t in gmsh.model.getEntities(2):
            if gmsh.model.getType(2, t) != "Cylinder":
                continue
            size = gmsh.option.getNumber("Mesh.MeshSizeMax")
            for f in fld.list():
                if fld.getType(f) == "Constant" and t in [int(x) for x in fld.getNumbers(f, "SurfacesList")]:
                    size = min(size, fld.getNumber(f, "VIn"))
            if size > LIMIT:
                raise RuntimeError(f"Impossible to mesh periodic surface {t}")
        return real(dim)
    monkeypatch.setattr(gmsh.model.mesh, "generate", fake)


def _cad_fail(src, cfg):
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, H, cfg, PROPS)
    return dict({"code": ei.value.code, "message": ei.value.message},
                **mg._fail_info(ei.value, {"src": src, "cfg": cfg}))


# ---------------------------------------------------------------- V-C2-13
@needs_gmsh
def test_refine_local_then_global(tmp_path, monkeypatch):
    src = scmp.boss_plate_step(tmp_path / "b.step", [(5.0, 5.0, 5.0, 0.0, 0.0)])
    _inject(monkeypatch)
    g1 = _cad_fail(src, _cfg(fallback={"enabled": False}))["geom"]          # 기본 이웃 1고리 = 원통 + 판(면 전부)
    assert g1["local_faces"] == 2 and g1["local_area_mm2"] == pytest.approx(g1["area_mm2"])
    cfg = _cfg(refine={"local": {"neighbor_rings": 0}}, fallback={"enabled": False})   # 이 형상은 고리 0 이어야 국부가 작음
    prev = _cad_fail(src, cfg)
    assert prev["code"] == "FAILED_MESH" and prev["face"]["type"] == "Cylinder" and len(prev["face"]["key"]) == 6
    g = prev["geom"]
    assert g["area_mm2"] > 300 * 160 * 0.9 and g["local_faces"] == 1
    assert g["local_area_mm2"] == pytest.approx(2 * np.pi * 5.0 * 5.0, rel=1e-3)
    att = mr.plan("refine_local", prev, H, cfg, None)
    assert [a["factor"] for a in att] == [0.75, 0.5, 0.33] and [a["h_mm"] for a in att] == pytest.approx([2.25, 1.5, 0.99])
    assert all(not a["skipped"] and a["n_est"] > 0 for a in att)
    a = att[0]
    ac = mr.attempt_cfg(cfg, a)
    assert "size_fields" not in cfg["mesh"] and ac["mesh"]["max_elems"] == 600000 and ac["mesh"]["size_min_mm"] == 0.5
    m_l, meta_l = mg.mesh_file(src, a["mesh_h"], ac, PROPS, out_dir=str(tmp_path / "l"))
    sf = meta_l["size_fields"]
    assert sf["mesh_size_min"] == pytest.approx(2.25 * 0.8)
    faces = sf["entries"][0]["faces"]
    assert [f["ring"] for f in faces] == [0]
    assert next(f for f in faces if f["ring"] == 0)["type"] == "Cylinder"
    n_l = meta_l["n_elems"]
    assert abs(n_l - a["n_est"]) / n_l < 0.5                            # 예측이 크기 차수는 맞음
    # 국부를 끄면(사다리에서 refine_local 뺌) 전역 2.4 mm
    ga = mr.plan("refine_global", prev, H, cfg, None)
    assert [x["h_mm"] for x in ga] == pytest.approx([2.4, 2.001])
    m_g, meta_g = mg.mesh_file(src, ga[0]["mesh_h"], mr.attempt_cfg(cfg, ga[0]), PROPS)
    assert "size_fields" not in meta_g and meta_g["h"] == pytest.approx(2.4)
    assert n_l < meta_g["n_elems"]                                      # 국부 성공의 요소 수 < 전역


@needs_gmsh
def test_refine_local_no_face_and_ladder():
    att = mr.plan("refine_local", {"code": "FAILED_MESH", "message": "timeout"}, H, _cfg(), None)
    assert len(att) == 1 and att[0]["skipped"] and att[0]["reason"] == "no_face" and att[0]["info"] == "REFINE_LOCAL_NO_FACE"
    assert mr.plan("cad", None, H, _cfg(), None)[0]["mesh_h"] == H
    assert mr.plan("refine_global", None, H, _cfg(refine={"enabled": False}), None) == []
    c = _cfg()
    assert mr.ladder(c) == ["cad", "refine_local", "refine_global", "defeature", "remesh"]   # v0.16.1 SR-D-16
    assert mr.ladder(c, "cad") == ["cad"] and mr.ladder(c, "remesh") == ["remesh"]
    c["compare"] = dict(c["compare"], mesh=dict(c["compare"]["mesh"], ladder=["cad", "cad"]))
    with pytest.raises(EslError):
        mr.ladder(c)


# ---------------------------------------------------------------- V-C2-14
def test_estimate_and_limits():
    assert mr.estimate_elems(400 * 300, 3.0) == int(np.ceil(400 * 300 / 9.0))
    areas = {(0, 0, 0, 1, 1, 0): 100.0, (5, 5, 0, 6, 6, 0): 50.0}
    n_h = mr.estimate_elems(areas, 2.0)
    assert n_h == 38 and mr.estimate_elems(areas, 2.0, [(5, 5, 0, 6, 6, 0)], 1.0) == int(np.ceil(37.5 + 50 * (1 - 0.25)))
    assert mr.estimate_elems(150.0, 2.0, 50.0, 1.0, elem_per_h2=2.0) == int(np.ceil(2 * (37.5 + 37.5)))
    prev = {"face": {"key": [0, 0, 0, 1, 1, 1], "type": "Plane"},
            "geom": {"area_mm2": 400 * 300.0, "local_area_mm2": 200.0}, "wall_seconds": 10.0}
    big = mr.plan("refine_global", prev, H, _cfg(refine={"max_elems": 15000}), None)
    assert [(a["skipped"], a["reason"]) for a in big] == [(True, "elems"), (True, "elems")]
    assert all(a["info"] == "REFINE_SKIPPED_LIMIT" and a["n_est"] > 15000 for a in big)
    loc = mr.plan("refine_local", prev, H, _cfg(refine={"max_elems": 15000}), None)
    assert not any(a["skipped"] for a in loc)                          # 국부는 증가가 작아 상한 안
    mem = mr.plan("refine_global", prev, H, _cfg(), 1000)
    assert all(a["reason"] == "memory" and a["bytes_est"] > 1000 for a in mem)
    t = mr.plan("refine_global", prev, H, _cfg(refine={"total_timeout_s": 30}), None, elapsed_s=25.0)
    assert all(a["reason"] == "time" for a in t)
    assert not any(a["skipped"] for a in mr.plan("refine_global", prev, H, _cfg(), None, elapsed_s=0.0))
    assert mr.check_limits({"n_est": None}, _cfg(), 1) is None         # 넓이 모름 → 판정 생략
    assert [f["key"] for f in mr.failed_faces({"faces": [{"key": [1, 2, 3, 4, 5, 6]}],
                                                "face": {"key": [1, 2, 3, 4, 5, 6.0000001]},
                                                "errors": [{"face": {"key": [0, 0, 0, 1, 1, 1]}}]})] == \
        [[1, 2, 3, 4, 5, 6], [0, 0, 0, 1, 1, 1]]


# ---------------------------------------------------------------- V-C2-15
@needs_gmsh
def test_normal_shape_bytes_and_refine_deterministic(tmp_path):
    """정상 형상: size_fields 없음 → mesh.json 에 키 없음, run_isolated 기본 인자 = kind cad 명시(바이트 동일, job 에 새 키 없음).
    세분화 시도 2회(spawn) → 바이트 동일."""
    src = scmp.boss_plate_step(tmp_path / "b.step", [(5.0, 5.0, 5.0, 0.0, 0.0)])
    cfg = _cfg()
    _m, ma = mg.run_isolated(src, str(tmp_path / "a"), H, cfg, PROPS)
    mg.run_isolated(src, str(tmp_path / "b"), H, cfg, PROPS, kind="cad", max_elems=None, fail_info=False)
    assert "size_fields" not in ma
    assert (tmp_path / "a" / mg.MESH_NPZ).read_bytes() == (tmp_path / "b" / mg.MESH_NPZ).read_bytes()
    job = json.loads((tmp_path / "a" / "mesh_job.json").read_text(encoding="utf-8"))
    assert "kind" not in job and "fail_info" not in job and "size_fields" not in job["cfg"]["mesh"]
    with mg_session() as gmsh:                                          # 실제 면 bbox 키로 세분화 시도
        gmsh.model.occ.importShapes(src)
        gmsh.model.occ.synchronize()
        cyl = next(t for _d, t in gmsh.model.getEntities(2) if gmsh.model.getType(2, t) == "Cylinder")
        key = list(mg._bbox_key(gmsh, 2, cyl))
    att = mr.plan("refine_local", {"face": {"key": key}}, H, cfg, None)[0]
    ac = mr.attempt_cfg(cfg, att)
    _m, mc = mg.run_isolated(src, str(tmp_path / "c"), H, ac, PROPS, max_elems=att["max_elems"])
    mg.run_isolated(src, str(tmp_path / "d"), H, ac, PROPS, max_elems=att["max_elems"])
    assert mc["size_fields"]["entries"][0]["faces"]
    assert (tmp_path / "c" / mg.MESH_NPZ).read_bytes() == (tmp_path / "d" / mg.MESH_NPZ).read_bytes()
    assert mc["n_elems"] > ma["n_elems"]


@needs_gmsh
def test_fail_info_written_by_child(tmp_path):
    """run_isolated(fail_info=True) 의 cad 실패 → mesh_error.json 에 face·geom(워커가 read_attempt 로 읽음)."""
    src = scmp.dimple_plate_step(tmp_path / "d.step", [(100.0, 75.0, 20.0, 5.0)])
    cfg = _cfg(fallback={"enabled": False})
    with pytest.raises(EslError):
        mg.run_isolated(src, str(tmp_path / "t"), H, cfg, PROPS, fail_info=True)
    rec = mr.read_attempt(str(tmp_path / "t"))
    assert rec["code"] == "FAILED_MESH" and rec["face"]["type"] == "Sphere" and rec["geom"]["area_mm2"] > 0
    assert mr.failed_faces(rec)[0]["key"] == [round(v, 6) for v in rec["face"]["key"]]


class mg_session:                                                       # noqa: N801 - 시험 도우미
    def __enter__(self):
        import gmsh
        gmsh.initialize(["-noenv"], readConfigFiles=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        for k, v in mg.geometry_options(_cfg()["mesh"]).items():
            gmsh.option.setNumber(k, v)
        return gmsh

    def __exit__(self, *a):
        import gmsh
        gmsh.finalize()


# ---------------------------------------------------------------- v0.16.1 V-SR-20 사다리 defeature 단계(esl_select_relax.md §5A.1)
def test_ladder_defeature_config():
    c = _cfg()
    lad = lambda x: mr.ladder(dict(c, compare=dict(c["compare"], mesh=dict(c["compare"]["mesh"], ladder=x))))  # noqa: E731
    assert lad(["cad", "refine_local", "refine_global", "remesh"]) == ["cad", "refine_local", "refine_global", "remesh"]
    assert lad(["cad", "defeature", "refine_local", "remesh"]) == ["cad", "defeature", "refine_local", "remesh"]
    for bad in (["defeature", "cad"], ["cad", "defeature", "defeature"], ["cad", "simplify"]):
        with pytest.raises(EslError) as ei:
            lad(bad)
        assert ei.value.code == "CONFIG_INVALID"


def test_plan_defeature_attempts():
    c = _cfg()
    att = mr.plan("defeature", {"geom": {"area_mm2": 3e4}}, H, c, None)
    assert [(a["stage"], a["compound"], a.get("only_if"), a["mesh_h"], a["factor"]) for a in att] == \
        [("defeature", True, None, H, None), ("defeature", False, "compound_failed", H, None)]
    assert att[0]["n_est"] == mr.estimate_elems(3e4, H)
    c2 = _cfg()
    c2["compare"] = dict(c2["compare"], defeature=dict(c2["compare"]["defeature"], kinds=["hole", "bead"]))
    assert len(mr.plan("defeature", None, H, c2, None)) == 1                  # compound 대상 종류 없음 → 2번째 없음
    c3 = _cfg()
    c3["compare"] = dict(c3["compare"], defeature=dict(c3["compare"]["defeature"], compound=False))
    assert len(mr.plan("defeature", None, H, c3, None)) == 1
    t = mr.plan("defeature", None, H, _cfg(refine={"total_timeout_s": 5}), None, elapsed_s=9.0)
    assert all(a["skipped"] and a["reason"] == "time" for a in t)
    ac = mr.attempt_cfg(c, att[1])
    assert ac["mesh"]["defeature_stage"]["compound"] is False and ac["mesh"]["defeature_stage"]["crit"]["hole_max_d"] == 8.0
    assert "defeature_stage" not in mr.attempt_cfg(ac, {"stage": "remesh", "mesh_h": H})["mesh"]   # 다른 단계 = 키 없음


def test_compound_failed():
    k = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert mr.compound_failed({"compound_keys": [k], "face": {"key": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0000001]}})
    assert not mr.compound_failed({"compound_keys": [k], "face": {"key": [0, 0, 0, 1, 1, 1]}})
    assert mr.compound_failed({"compound_keys": [k]})                        # 면을 특정 못 함 = compound 탓
    assert not mr.compound_failed({"face": {"key": k}}) and not mr.compound_failed(None)
