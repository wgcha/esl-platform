"""v0.15.1 ④ Sphere 면 메싱 실패(이슈 #53 실제 Ch/R 중립면 STEP — v0.14.1 뒤에도 'Impossible to mesh periodic surface 2824').

원인(합성 재현): 구면 딤플·필렛 코너 패치 같은 OCC Sphere 면은 극점에 길이 0 퇴화 모서리가 있다. ④ 프로필의 OCC 정리
(Geometry.OCCFixDegenerated·SmallEdges·SmallFaces = occ_fix_small 1, 또는 OCCSewFaces 1)가 그 모서리를 지워 매개변수 공간 경계
고리가 극점에서 끊기고, gmsh periodic 면 메셔가 그 면에서 실패한다(gmsh 4.13.1 문구 'The 1D mesh seems not to be forming a closed
loop' — 판 따라 'Impossible to mesh periodic surface N'). 2D 알고리즘·제약 해제로는 안 됨(같은 경계).
수정: 실패 면에만 형상 폴백 — nofix(OCC 정리 없이: 그 면만 다시 가져와 대체 → 세션 전체) → split(bbox 중심 평면으로 나눔) →
fill(경계 고리 BSpline 채움, 원 면 대비 편차 ≤ 0.5 h) → small(작은 면 경계만 채움). 설정 ``mesh.fallback.order``·
``periodic_order``·``nofix.scopes``. gmsh 가 없으면 skip."""
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
    """재현: 구면 딤플 판 — v0.14.1 폴백(알고리즘 6→5→1·제약 해제)은 모두 실패(FAILED_MESH, Sphere 면). nofix 를 빼고
    split → fill 이면: 분할은 정리된 면에 불리언이 안 돼 건너뛰고 채움 면으로 메시. 원본 STEP 불변."""
    src = scmp.dimple_plate_step(tmp_path / "dimple.step", DIMPLES)
    sha0 = _sha(src)
    old = _ccfg()
    old["mesh"]["fallback"] = dict(LEGACY_FB)
    with pytest.raises(EslError) as ei:                                          # 수정 전(형상 단계 없음) = 이슈 증상
        mg.mesh_file(src, 3.0, old, PROPS)
    assert ei.value.code == "FAILED_MESH" and "Sphere" in ei.value.message and "메시하지 못했습니다" in ei.value.message
    m, meta = mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_order": ["split", "fill", "small"]}), PROPS,
                           out_dir=str(tmp_path / "m"))
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


def _nofix_ok(meta, scope="face"):
    fb = meta["mesh_fallback"]
    assert fb["n_faces"] >= 1 and all(f["type"] == "Sphere" and f["stage"] == "nofix" and f["scope"] == scope
                                      and f["deviation_mm"] == 0.0 for f in fb["faces"]), fb
    w = next(x for x in meta["warnings"] if x["code"] == "MESH_FACE_FALLBACK")["message"]
    assert f"OCC 정리 끔({'그 면만' if scope == 'face' else '전체'})" in w
    assert not meta["errors"] and int(meta["quality"].get("n_components") or 1) == 1


@needs_gmsh
@pytest.mark.parametrize("name,dimples", [("dimple", DIMPLES), ("deep", [(100.0, 75.0, 20.0, 19.0)])])
def test_nofix_face_dimple_and_deep_hemisphere(tmp_path, name, dimples):
    """기본 설정(periodic_order 맨 앞 nofix, scopes face → all): 구면 딤플·깊은 반구(R 20·깊이 19 — 채움 편차 5.8 mm 로 fill 은
    안 됨)가 그 면만 정리 없이 다시 가져온 면으로 메시(편차 0, 깊이 그대로). 원본 STEP 불변."""
    src = scmp.dimple_plate_step(tmp_path / f"{name}.step", dimples)
    sha0 = _sha(src)
    m, meta = mg.mesh_file(src, 3.0, _ccfg(), PROPS)
    _nofix_ok(meta)
    assert len(meta["mesh_fallback"]["faces"][0]["errors"]) == 1                  # 첫 단계로 해결
    assert np.isclose(m["x0"][:, 2].min(), -dimples[0][3], atol=0.05)             # 딤플 바닥까지(형상 편차 없음)
    assert _sha(src) == sha0


@needs_gmsh
def test_nofix_face_fillet_corner(tmp_path):
    """세 필렛 코너 구면 패치: OCCSewFaces 1 + 정리 끔(occ_fix_small 0)에서 v0.14.1 폴백은 실패, nofix(그 면만)로 메시."""
    src = scmp.fillet_corner_step(tmp_path / "corner.step", 5.0)
    old = _ccfg(occ_fix_small=0)
    old["mesh"]["fallback"] = dict(LEGACY_FB)
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, 3.0, old, PROPS)
    assert "Sphere" in ei.value.message
    _m, meta = mg.mesh_file(src, 3.0, _ccfg(occ_fix_small=0), PROPS)
    _nofix_ok(meta)


@needs_gmsh
def test_nofix_all_scope(tmp_path):
    """nofix(전체): 고체 STEP(면 공유가 STEP 안 — OCCSewFaces 0) 딤플은 세션 전체를 정리 없이 다시 열어 메시. 면 공유가 없는
    STEP(봉합 필요)은 전체 정리 끔 → 연결 성분 2(MESH_DISCONNECTED) = 새 실패 → 그 결과는 버리고 다음 단계(fill)로."""
    src = scmp.dimple_plate_step(tmp_path / "solid.step", DIMPLES, solid=10.0)
    old = _ccfg(occ_sew_faces=0)
    old["mesh"]["fallback"] = dict(LEGACY_FB)
    with pytest.raises(EslError):
        mg.mesh_file(src, 3.0, old, PROPS)
    _m, meta = mg.mesh_file(src, 3.0, _ccfg(occ_sew_faces=0, fallback={"nofix": {"scopes": ["all"]}}), PROPS)
    _nofix_ok(meta, "all")
    src2 = scmp.dimple_plate_step(tmp_path / "shell.step", DIMPLES)
    _m, meta = mg.mesh_file(src2, 3.0, _ccfg(fallback={"nofix": {"scopes": ["all"]},
                                                       "periodic_order": ["nofix", "fill"]}), PROPS)
    f = meta["mesh_fallback"]["faces"][0]
    assert f["stage"] == "fill" and any("OCC 정리 끔(전체) 뒤 품질 오류 MESH_DISCONNECTED" in e for e in f["errors"])
    assert not meta["errors"]


@needs_gmsh
def test_bead_with_features(tmp_path):
    """비드 바닥 형상(이슈 #53 면 2824 추정 — 사각 비드 깊이 20, 바닥에 딤플 3·Ø5·Ø10·버링, 필렛): v0.14.1 은 딤플에서 실패,
    기본 설정은 nofix 로 딤플 3개 메시. 작은 구멍 메움: Ø5(19.6 mm²) 메움·Ø10 남음(둘레 분할), 버링·딤플 둘레 원은 구멍 아님."""
    src = scmp.bead_with_features_step(tmp_path / "bead.step")
    old = _ccfg()
    old["mesh"]["fallback"] = dict(LEGACY_FB)
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, 3.0, old, PROPS)
    assert "Sphere" in ei.value.message
    m, meta = mg.mesh_file(src, 3.0, _ccfg(), PROPS)
    _nofix_ok(meta)
    assert meta["mesh_fallback"]["n_faces"] == 3                                   # 딤플 3개(얕은·중간·깊은 반구)
    df = meta["defeature"]
    assert df["filled"] == 1 and abs(df["filled_area_max"] - np.pi * 2.5 ** 2) < 0.1 and df["hole_sized"] == 1
    assert df.get("not_hole", 0) >= 4                                              # 버링 1 + 딤플 둘레 3(+ 비드 테두리)
    X = m["x0"]
    on_floor = np.abs(X[:, 2] + 20.0) < 1e-6
    r5 = np.hypot(X[:, 0] - 90.0, X[:, 1] - 70.0)
    r10 = np.hypot(X[:, 0] - 210.0, X[:, 1] - 70.0)
    assert (on_floor & (r5 < 2.0)).any()                                           # Ø5 메움(구멍 안에 노드)
    assert not (on_floor & (r10 < 4.9)).any()                                      # Ø10 남음
    assert np.isclose(X[:, 2].min(), -28.0, atol=0.05)                             # 버링 끝(−28)·깊은 반구 바닥(−28)
    for x, d in ((100.0, 2.0), (150.0, 5.0), (200.0, 8.0)):                        # 딤플 바닥 깊이 유지
        near = np.hypot(X[:, 0] - x, X[:, 1] - 100.0) < 1.5
        assert np.isclose(X[near, 2].min(), -20.0 - d, atol=0.1), x


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
    m, meta = mg.mesh_file(src, 3.0, _ccfg(fallback={"periodic_types": ["Cylinder"],
                                                       "periodic_order": ["split", "fill", "algorithms"]}), PROPS)
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
    assert d["periodic_order"][:3] == ["nofix", "split", "fill"] and d["order"][:2] == ["algorithms", "relax"]
