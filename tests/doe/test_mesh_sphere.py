"""v0.15.1 ④ Sphere 면 메싱 실패(이슈 #53 실제 Ch/R 중립면 STEP — v0.14.1 뒤에도 'Impossible to mesh periodic surface 2824').

원인(합성 재현): 구면 딤플·필렛 코너 패치 같은 OCC Sphere 면은 극점에 길이 0 퇴화 모서리가 있다. ④ 프로필의 OCC 정리
(Geometry.OCCFixDegenerated·SmallEdges·SmallFaces = occ_fix_small 1, 또는 OCCSewFaces 1)가 그 모서리를 지워 매개변수 공간 경계
고리가 극점에서 끊기고, gmsh periodic 면 메셔가 그 면에서 실패한다(gmsh 4.13.1 문구 'The 1D mesh seems not to be forming a closed
loop' — 판 따라 'Impossible to mesh periodic surface N'). 2D 알고리즘·제약 해제로는 안 됨(같은 경계).
수정: 실패 면에만 형상 폴백 — split(bbox 중심 평면으로 나눔) → fill(경계 고리 BSpline 채움, 원 면 대비 편차 ≤ 0.5 h) →
small(작은 면 경계만 채움). 설정 ``mesh.fallback.order``·``periodic_order``. gmsh 가 없으면 skip."""
import hashlib
import json

import numpy as np
import pytest

import synth_compare as scmp
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import settings
from esl.errors import EslError

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
PROPS = {"t": 1.0, "E": 205000.0, "nu": 0.3}
DIMPLES = [(100.0, 75.0, 20.0, 5.0)]                 # 구 R 20·깊이 5(극점 = 딤플 바닥, 면 안)
LEGACY_FB = {"enabled": True, "algorithms": [6, 5, 1], "relax": True, "max_faces": 20}   # v0.14.1 설정(형상 단계 없음)


def _ccfg(fallback=None, **mesh):
    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    cfg["mesh"].update(mesh)
    if fallback is not None:
        fb = dict(cfg["mesh"]["fallback"])
        fb.update(fallback)
        cfg["mesh"]["fallback"] = fb
    return cfg


def _sha(p) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


@needs_gmsh
def test_sphere_dimple_reproduces_and_fill_fixes(tmp_path):
    """재현: 구면 딤플 판 — v0.14.1 폴백(알고리즘 6→5→1·제약 해제)은 모두 실패(FAILED_MESH, Sphere 면). 수정 후 기본 설정 =
    Sphere 면 periodic_order(split → fill …): 분할은 정리된 면에 불리언이 안 돼 건너뛰고 채움 면으로 메시. 원본 STEP 불변."""
    src = scmp.dimple_plate_step(tmp_path / "dimple.step", DIMPLES)
    sha0 = _sha(src)
    old = _ccfg()
    old["mesh"]["fallback"] = dict(LEGACY_FB)
    with pytest.raises(EslError) as ei:                                          # 수정 전(형상 단계 없음) = 이슈 증상
        mg.mesh_file(src, 3.0, old, PROPS)
    assert ei.value.code == "FAILED_MESH" and "Sphere" in ei.value.message and "메시하지 못했습니다" in ei.value.message
    m, meta = mg.mesh_file(src, 3.0, _ccfg(), PROPS, out_dir=str(tmp_path / "m"))
    assert _sha(src) == sha0                                                    # 원본 STEP 은 읽기만
    fb = meta["mesh_fallback"]
    assert fb["n_faces"] == 1
    f = fb["faces"][0]
    assert f["type"] == "Sphere" and f["stage"] == "fill" and f["stage_name"] == "채움 면 대체"
    assert 0.0 < f["deviation_mm"] <= 0.5 * 3.0 and f["new_ids"]
    assert any("면 분할 적용 안 됨" in e for e in f["errors"])                  # split 먼저 시도 → 건너뜀
    w = [x for x in meta["warnings"] if x["code"] == "MESH_FACE_FALLBACK"]
    assert len(w) == 1 and "채움 면 대체(편차" in w[0]["message"] and "Sphere" in w[0]["message"]
    assert not meta["errors"] and int(meta["quality"].get("n_components") or 1) == 1
    X = m["x0"]                                                                  # 딤플이 메워지지 않고 깊이 유지(편차 안)
    assert X[:, 2].min() < -5.0 + 0.5 * 3.0
    mj = json.loads((tmp_path / "m" / mg.MESH_JSON).read_text(encoding="utf-8"))
    assert mj["mesh_fallback"]["faces"][0]["stage"] == "fill"


@needs_gmsh
def test_sphere_fill_rejected_by_deviation_then_fails_with_stage_list(tmp_path):
    """채움 편차 허용(fill.tol_factor × h)을 넘으면 채움 면을 쓰지 않음 → 끝내 실패 문구에 면 id·종류·위치·새 단계 포함."""
    src = scmp.dimple_plate_step(tmp_path / "dimple.step", DIMPLES)
    cfg = _ccfg(fallback={"fill": {"tol_factor": 0.01, "points": 8, "samples": 10},
                          "periodic_order": ["split", "fill", "small", "algorithms"]})
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, 3.0, cfg, PROPS)
    msg = ei.value.message
    assert ei.value.code == "FAILED_MESH" and "Sphere, 위치 x 100" in msg
    assert "면 분할 → 채움 면 대체 → 작은 면 평면 채움 → Frontal-Delaunay" in msg
    with pytest.raises(EslError) as ei:                                          # 형상 단계를 order 에서 빼면 끔
        mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_order": ["algorithms"]}), PROPS)
    assert "채움" not in ei.value.message and "Frontal-Delaunay → Delaunay → MeshAdapt" in ei.value.message


@needs_gmsh
def test_small_sphere_face_small_stage(tmp_path):
    """small: 넓이 < small.area_mm2 Sphere 면(R 5·깊이 1 → 31 mm²)은 경계만으로 채움(편차 ≤ small.tol_factor × h)."""
    src = scmp.dimple_plate_step(tmp_path / "s.step", [(100.0, 75.0, 5.0, 1.0)])
    _m, meta = mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_order": ["small"]}), PROPS)
    f = meta["mesh_fallback"]["faces"][0]
    assert f["stage"] == "small" and f["type"] == "Sphere" and f["deviation_mm"] <= 3.0
    assert not meta["errors"]
    with pytest.raises(EslError):                                                # 기준보다 크면 안 씀
        mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_order": ["small"], "small": {"area_mm2": 10.0}}), PROPS)


@needs_gmsh
def test_split_stage_forced_periodic_failure(tmp_path, monkeypatch):
    """강제 실패 주입: 원통 벽 1개가 'Impossible to mesh periodic surface N'(이슈 문구 그대로)으로 실패하게 하면 — 그 면만
    bbox 중심 평면 2개로 나눠(조각 4) 공유 경계를 유지해 메시(연결 성분 1), mesh_fallback stage split·편차 0."""
    import gmsh
    src = scmp.boss_plate_step(tmp_path / "boss.step", [(5.0, 5.0, 5.0, 0.0, 0.0)])
    real = gmsh.model.mesh.generate
    target: dict = {}

    def fake(dim=3):
        cyl = [t for _d, t in gmsh.model.getEntities(2) if gmsh.model.getType(2, t) == "Cylinder"]
        if not target and cyl:
            target["key"] = mg._bbox_key(gmsh, 2, cyl[0])
        for t in cyl:
            if mg._key_near(mg._bbox_key(gmsh, 2, t), target["key"]):
                raise RuntimeError(f"Impossible to mesh periodic surface {t}")
        return real(dim)
    monkeypatch.setattr(gmsh.model.mesh, "generate", fake)
    m, meta = mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_types": ["Cylinder"]}), PROPS)
    f = meta["mesh_fallback"]["faces"][0]
    assert f["type"] == "Cylinder" and f["stage"] == "split" and f["deviation_mm"] == 0.0
    assert len(f["new_ids"]) == 4 and f["errors"] == [f"Impossible to mesh periodic surface {f['failed_id']}"]
    assert not meta["errors"] and int(meta["quality"].get("n_components") or 1) == 1
    assert "면 분할" in next(x for x in meta["warnings"] if x["code"] == "MESH_FACE_FALLBACK")["message"]
    X = m["x0"]                                                                  # 벽 바닥(z = -5)까지 메시됨
    assert np.isclose(X[:, 2].min(), -5.0, atol=1e-6)


@needs_gmsh
def test_normal_step_bytes_unchanged_by_geometry_stages(tmp_path):
    """정상 STEP: 형상 폴백 키가 있어도 폴백이 안 돌아 mesh.npz·mesh.json 이 v0.14.1 설정과 바이트 동일(seconds 제외)."""
    src = scmp.boss_plate_step(tmp_path / "b.step", [(5.0, 5.0, 5.0, 4.5, 0.0)], holes=[(270.0, 30.0, 2.0)])
    a, b = tmp_path / "a", tmp_path / "b"
    _m, ma = mg.mesh_file(src, 3.0, _ccfg(), PROPS, out_dir=str(a))
    cfg_old = _ccfg()
    cfg_old["mesh"]["fallback"] = dict(LEGACY_FB)
    mg.mesh_file(src, 3.0, cfg_old, PROPS, out_dir=str(b))
    assert "mesh_fallback" not in ma
    assert _sha(a / mg.MESH_NPZ) == _sha(b / mg.MESH_NPZ)
    ja, jb = (json.loads((d / mg.MESH_JSON).read_text(encoding="utf-8")) for d in (a, b))
    ja.pop("seconds"), jb.pop("seconds")
    assert ja == jb


def test_ladder_order_from_config():
    """단계 순서·on/off 는 설정에서(하드코딩 없음): order 없음 = v0.14.1, periodic_types 면은 periodic_order."""
    mc = {"algorithm": 8}
    assert mg._ladder(mc, LEGACY_FB, "Sphere") == [(6, False, None), (5, False, None), (1, False, None),
                                                   (8, True, None), (6, True, None), (5, True, None), (1, True, None)]
    fb = dict(LEGACY_FB, order=["fill", "algorithms"], periodic_types=["Sphere"], periodic_order=["split"])
    assert mg._ladder(mc, fb, "Plane") == [(8, False, "fill"), (6, False, None), (5, False, None), (1, False, None)]
    assert mg._ladder(mc, fb, "Sphere") == [(8, False, "split")]
    d = settings({"bead_doe": {"enabled": True}})["compare"]["mesh"]["fallback"]
    assert d["periodic_order"][:2] == ["split", "fill"] and d["order"][:2] == ["algorithms", "relax"]
