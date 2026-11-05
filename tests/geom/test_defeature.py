"""V-SR-16·17·19 CAD 공통 모듈 esl.geom.defeature (계약 esl_select_relax.md §5B.1·§5A.3·§5A.4, SR-D-17~22).

V-SR-16 래퍼·이동 무변경: ``mg.defeature`` = ``gdf.holes``(dict 동일), ``collect=None`` 이면 결과 불변, 재노출 이름,
④(compare_cfg)·③(bead_doe.mesh) 합성 STEP cad 메시 mesh.npz·mesh.json 이 v0.16.0 기대값(``tests/fixtures/bead_select/
v0160_golden.json``)과 바이트 동일. bead_with_features 는 v0.16.0 에서도 메시 바이트가 실행마다 달라(nofix_face 폴백 3면)
구조(노드 수·defeature 기록)만 비교."""
import hashlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "doe"))

import synth_compare as scmp  # noqa: E402
from esl.doe import mesh_gmsh as mg  # noqa: E402
from esl.doe import scenario as sc  # noqa: E402
from esl.doe import settings  # noqa: E402
from esl.geom import defeature as gdf  # noqa: E402

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
GOLD = json.load(open(os.path.join(HERE, "..", "fixtures", "bead_select", "v0160_golden.json"), encoding="utf-8"))
PROPS = {"t": 2.0, "E": 205000.0, "nu": 0.3}
STEPS = {
    "plate": lambda p: scmp.plate_step(p, 1, Lx=200.0, Lz=150.0),
    "plate_hole": lambda p: scmp.plate_step(p, Lx=200.0, Lz=150.0, hole=(100.0, 75.0, 2.0)),
    "boss": lambda p: scmp.boss_plate_step(p, [(10.0, 8.0, 6.0, 3.0, 0.0), (8.0, 8.0, 5.0, 0.0, 2.0)],
                                           holes=[(200.0, 80.0, 2.0)]),
    "dimple": lambda p: scmp.dimple_plate_step(p, [(60.0, 75.0, 15.0, 4.0)]),
    "bwf": lambda p: scmp.bead_with_features_step(p),
    "fillet_corner": lambda p: scmp.fillet_corner_step(p),
}


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _c4(**cmp):
    return sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                                 "compare": {"mesh": {"size_mm": 5.0}, **cmp}}}))


def _c3():
    return settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}})


@pytest.fixture(scope="module")
def steps(tmp_path_factory):
    d = tmp_path_factory.mktemp("steps")
    return {k: f(str(d / f"{k}.step")) for k, f in STEPS.items()}


def _mesh(src, cfg, out):
    try:
        mg.mesh_file(src, 5.0, cfg, PROPS, out_dir=str(out))
        err = None
    except Exception as exc:                    # noqa: BLE001
        err = getattr(exc, "code", type(exc).__name__)
    mj = out / "mesh.json"
    d = json.loads(mj.read_text(encoding="utf-8")) if mj.is_file() else None
    if d is not None:
        d.pop("seconds", None)
    npz = out / "mesh.npz"
    return {"npz": _h(npz.read_bytes()) if npz.is_file() else None,
            "json": _h(json.dumps(d, sort_keys=True).encode()) if d is not None else None, "err": err,
            "defeature": (d or {}).get("defeature"), "doc": d}


def test_reexported_names():
    for a, b in (("_loop_info", "loop_length"), ("_face_loops", "face_loops"), ("_curve_points", "curve_points"),
                 ("_seam_points", "seam_points"), ("_is_hole", "is_hole"), ("_bbox_key", "bbox_key"),
                 ("_key_near", "key_near")):
        assert getattr(mg, a) is getattr(gdf, b)
    assert callable(mg.defeature) and callable(mg._key_in)


@needs_gmsh
@pytest.mark.parametrize("tag", ["c4", "c3"])
def test_cad_mesh_bytes_v0160(steps, tmp_path, tag):
    """V-SR-16: ④ cad·③ 메시 바이트 = v0.16.0 기대값."""
    cfg = _c4() if tag == "c4" else _c3()
    for name, src in steps.items():
        got = _mesh(src, cfg, tmp_path / f"{tag}_{name}")
        key = f"{tag}/{name}"
        if key in GOLD["mesh"]:
            exp = GOLD["mesh"][key]
            assert (got["npz"], got["json"], got["err"], got["defeature"]) == \
                (exp["npz"], exp["json"], exp["err"], exp["defeature"]), key
        else:
            exp = GOLD["mesh_nondeterministic"][key]
            assert got["doc"]["n_nodes"] == exp["n_nodes"] and got["defeature"] == exp["defeature"], key


@needs_gmsh
def test_wrapper_equals_holes_and_collect(steps):
    """mg.defeature(gmsh, df, h[, skip_keys]) = gdf.holes(...) (같은 세션 입력 → 같은 dict), collect 목록은 반환을 바꾸지 않음."""
    import gmsh
    df = _c4()["mesh"]["defeature"]
    res = []
    for mode in ("wrap", "holes", "collect"):
        gmsh.initialize(["-noenv"], readConfigFiles=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.occ.importShapes(steps["boss"])
            gmsh.model.occ.synchronize()
            feats: list = []
            if mode == "wrap":
                r = mg.defeature(gmsh, df, 5.0)
            elif mode == "holes":
                r = gdf.holes(gmsh, df, 5.0)
            else:
                r = gdf.holes(gmsh, df, 5.0, collect=feats)
            res.append((r, feats, sorted(gdf.bbox_key(gmsh, 2, t) for _d, t in gmsh.model.getEntities(2))))
        finally:
            gmsh.finalize()
    assert res[0][0] == res[1][0] == res[2][0] and res[0][2] == res[1][2] == res[2][2]
    assert res[0][1] == [] and len(res[2][1]) == res[2][0]["filled"] == 3
    f = res[2][1][0]
    assert f["kind"] == "hole" and f["method"] == "holes_v0141" and f["size"]["d_mm"] > 0 and len(f["center"]) == 3


# ---------------------------------------------------------------- V-SR-17 인식 · V-SR-19 편차 (FEAT_SPEC, §11)
FEAT_SPEC = {"dimples": scmp.BEAD_FEATURES["dimples"] + [(120.0, 130.0, 10.0, 1.5)]}
H3 = 3.0
# 보스 판(실제 Ch/R 사진 7: 높이 3~5 mm 보스 + 가운데 Ø≤8 구멍, 낮은 1 mm 보스 1개, 판 구멍 1개)
BOSSES = [(8.0, 7.0, 4.0, 3.0, 0.0), (10.0, 9.0, 3.0, 4.0, 0.0), (6.0, 6.0, 5.0, 2.5, 0.0), (9.0, 9.0, 1.0, 4.0, 0.0)]


@pytest.fixture(scope="module")
def feat_steps(tmp_path_factory):
    d = tmp_path_factory.mktemp("feat")
    return {"feat": scmp.bead_with_features_step(str(d / "feat.step"), FEAT_SPEC),
            "boss": scmp.boss_plate_step(str(d / "boss.step"), BOSSES, holes=[(250.0, 40.0, 3.0)])}


def _ccfg(df=None, **cmp):
    return sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                                 "compare": {"defeature": df or {}, **cmp}}}))


def _recognize(src, df=None, *, with_holes=False):
    """④ 정리 옵션으로 가져와(cad 세션과 같음) find_features → (특징, 전후 면 수·넓이 합)."""
    import gmsh
    cfg = _ccfg(df)
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        for k, v in mg.geometry_options(cfg["mesh"]).items():
            gmsh.option.setNumber(k, v)
        gmsh.model.occ.importShapes(src)
        gmsh.model.occ.synchronize()
        if with_holes:
            gdf.holes(gmsh, cfg["mesh"]["defeature"], H3, collect=[])

        def state():
            fs = [t for _d, t in gmsh.model.getEntities(2)]
            return len(fs), round(sum(gmsh.model.occ.getMass(2, t) for t in fs), 6)
        s0 = state()
        ff = gdf.find_features(gmsh, gdf.criteria(cfg["compare"]["defeature"], H3))
        return ff, (s0, state())
    finally:
        gmsh.finalize()


def _kinds(ff):
    out: dict = {}
    for f in ff:
        out[f["kind"]] = out.get(f["kind"], 0) + 1
    return out


@needs_gmsh
def test_find_features_feat_spec(feat_steps):
    """V-SR-17: 기본 기준 정답 = cad holes 가 Ø5 를 먼저 메운 뒤 bead 1(딤플 1.5 — 둘레 필렛 포함) + fillet 3(깊이 2·5·8 딤플
    둘레 r 1.5). Ø10(> 8)·버링(8 > 1.5)·딤플 2(경계값)·5·8·비드 필렛 3·비드 자체는 억제 안 함. 형상 불변. 경계값 설정 변경."""
    src = feat_steps["feat"]
    ff, (s0, s1) = _recognize(src, with_holes=True)
    assert s0 == s1                                                   # 인식만 — 면 수·넓이 불변
    assert _kinds(ff) == {"bead": 1, "fillet": 3}
    b = next(f for f in ff if f["kind"] == "bead")
    assert b["center"][:2] == pytest.approx([120.0, 130.0], abs=0.01) and b["size"]["h_mm"] == pytest.approx(1.5, abs=0.05)
    assert len(b["faces"]) == 2                                       # 구면 + 둘레 필렛 = 한 특징
    fl = sorted((f for f in ff if f["kind"] == "fillet"), key=lambda f: f["center"][0])
    assert [round(f["center"][0], 2) for f in fl] == [100.0, 150.0, 200.0]
    assert all(f["size"]["r_mm"] == pytest.approx(1.5, abs=0.05) for f in fl)
    assert [f["id"] for f in ff] == [f"f{i + 1:04d}" for i in range(len(ff))]   # 결정적 번호(kind 순 → 중심)
    assert ff == _recognize(src, with_holes=True)[0]                  # 두 번 = 같은 결과
    # holes 없이: Ø5 도 find_features 가 hole 로(등가 지름 4A/P)
    ff0, _ = _recognize(src)
    h = [f for f in ff0 if f["kind"] == "hole"]
    assert len(h) == 1 and h[0]["center"][:2] == pytest.approx([90.0, 70.0], abs=0.01)
    assert h[0]["size"]["d_mm"] == pytest.approx(5.0, abs=0.05)
    # 경계값·종류 끔
    assert "fillet" not in _kinds(_recognize(src, {"kinds": ["flange", "hole", "slot", "bead", "narrow"]}, with_holes=True)[0])
    k21 = _recognize(src, {"min_bead_height_mm": 2.1}, with_holes=True)[0]
    assert _kinds(k21) == {"bead": 2, "fillet": 2}                    # 깊이 2 딤플도 bead(그 둘레 필렛은 bead 의 일부)
    assert sorted(round(f["center"][0]) for f in k21 if f["kind"] == "bead") == [100, 120]
    h12 = [f for f in _recognize(src, {"hole_max_d_mm": 12.0}, with_holes=True)[0] if f["kind"] == "hole"]
    assert len(h12) == 1 and h12[0]["size"]["d_mm"] == pytest.approx(10.0, abs=0.05)
    assert "bead" not in _kinds(_recognize(src, {"feature_max_mm": 10.0}, with_holes=True)[0])


@needs_gmsh
def test_find_features_boss_keeps_tall_boss_holes(feat_steps):
    """실제 Ch/R 7: 높이 3~5 mm 보스(원뿔·원통 벽 + 바닥 고리)는 특징 아님, 보스 가운데 Ø5~8 구멍은 hole(자유 고리가 평면 위 —
    버링 관 끝과 구분), 1 mm 낮은 보스(가운데 구멍 포함)는 flange(벽 + 고리 제거 → 둘레를 메움). 판 구멍 Ø6 hole."""
    ff, _ = _recognize(feat_steps["boss"])
    holes = sorted((f["center"][0], round(f["size"]["d_mm"], 1)) for f in ff if f["kind"] == "hole")
    assert holes == [(40.0, 6.0), (100.0, 8.0), (160.0, 5.0), (250.0, 6.0)]
    fl = [f for f in ff if f["kind"] == "flange"]
    assert len(fl) == 1 and fl[0]["center"][0] == pytest.approx(220.0) and fl[0]["size"]["h_mm"] == pytest.approx(1.0, abs=0.05)
    assert _kinds(ff) == {"hole": 4, "flange": 1}


def test_criteria_validation():
    c = gdf.criteria({}, 3.0)
    assert c["narrow_w"] == pytest.approx(1.2) and c["region_pad"] == pytest.approx(3.0) and c["kinds"][0] == "flange"
    assert c["hole_max_d"] == 8.0 and c["fillet_max_r"] == 1.5 and c["bead_min_h"] == 2.0 and c["compound"] is True
    from esl.errors import EslError
    for bad in ({"kinds": ["hole", "hole"]}, {"kinds": ["logo"]}, {"hole_max_d_mm": 0}, {"narrow_w_factor": 1.5},
                {"region_pad_factor": -1}, {"max_features": 0}, {"slot_max_w_mm": "x"}):
        with pytest.raises(EslError) as ei:
            gdf.criteria(bad, 3.0)
        assert ei.value.code == "CONFIG_INVALID", bad


def _stage_cfg(df=None, **cmp):
    from esl.doe import mesh_refine as mr
    cfg = _ccfg(df, **cmp)
    a = mr.plan("defeature", {}, H3, cfg, None)
    return cfg, a, mr.attempt_cfg(cfg, a[0])


@needs_gmsh
def test_stage_mesh_feat_spec_fidelity_and_list(feat_steps, tmp_path):
    """V-SR-18·19(코어): defeature 시도 = 하위 프로세스 2회 → mesh.json.defeature_stage counts{hole 1 bead 1 fillet 3}, compound
    3 묶음, defeature.json 결정적(바이트 동일)·순서 kind → 중심, 억제 영역 편차(딤플 ≈ 1.5, 구멍 0.4r..r), 바깥 Hausdorff =
    cad 메시의 원 이산화 수준(비드 필렛 r 3 의 h 3 현 처짐 ≈ 0.88 mm — 억제가 바깥을 더 나쁘게 하지 않음)."""
    cfg, att, ac = _stage_cfg()
    assert [(a["compound"], a.get("only_if")) for a in att] == [(True, None), (False, "compound_failed")]
    assert ac["mesh"]["defeature_stage"]["compound"] is True and "defeature_stage" not in cfg["mesh"]
    outs = []
    for k in range(2):
        od = tmp_path / f"r{k}"
        _m, meta = mg.run_isolated(feat_steps["feat"], str(od), H3, ac, {"t": 1.0, "E": 205000.0, "nu": 0.3})
        outs.append((meta, (od / mg.DEFEAT_LIST).read_bytes(), (od / mg.MESH_NPZ).read_bytes()))
    (meta, lst, _npz), (meta2, lst2, _npz2) = outs
    assert lst == lst2
    ds = meta["defeature_stage"]
    assert ds == meta2["defeature_stage"]
    assert ds["counts"] == {"bead": 1, "fillet": 3, "hole": 1} and ds["n"] == 5 and ds["skipped_n"] == 0
    assert len(ds["compound"]) == 3 and ds["list_file"] == "defeature.json" and not ds["fidelity"]["fail"]
    doc = json.loads(lst)
    assert doc["schema"] == "esl/defeature/1" and doc["n"] == 5 and doc["truncated"] is False
    assert doc["counts"] == ds["counts"]
    assert [f["kind"] for f in doc["features"]] == ["bead", "fillet", "fillet", "fillet", "hole"]
    by = {f["kind"]: f for f in doc["features"]}
    assert by["bead"]["dev_mm"] == pytest.approx(1.5, abs=0.15) and by["bead"]["method"] == "plane"
    assert 0.4 * 2.5 <= by["hole"]["dev_mm"] <= 2.5 + 0.15 and by["hole"]["method"] == "holes_v0141"
    assert all(f["method"] == "compound" and f["dev_mm"] is None for f in doc["features"] if f["kind"] == "fillet")
    fd = ds["fidelity"]
    assert fd["suppressed_max_mm"] == pytest.approx(max(by["bead"]["dev_mm"], by["hole"]["dev_mm"]))
    assert fd["outside"]["hausdorff_mm"] <= 1.0 and fd["outside"]["over_warn"]
    assert "REMESH_FIDELITY_WARN" in [w["code"] for w in meta["warnings"]]
    # 원 형상(구면 딤플 1.5 그대로)과 메시 사이 거리가 큰 곳은 억제 영역 안뿐: 같은 메시·같은 S0 로 Ω 없이 재면 더 큼
    assert fd["outside"]["hausdorff_mm"] < fd["suppressed_max_mm"]


@needs_gmsh
def test_stage_boss_plate_keeps_bosses(feat_steps, tmp_path):
    """실제 Ch/R 7(④ defeature): 높이 3·4·5 mm 보스는 메시에 남고(보스 바닥 z = −3·−4·−5 노드), 가운데 구멍(Ø5·6·8)과 판 구멍
    Ø6 은 메움(holes_v0141 이 먼저), 1 mm 낮은 보스는 가운데 구멍을 메운 뒤 bead(< 2)로 평탄화."""
    import numpy as np
    _cfg, _a, ac = _stage_cfg()
    m, meta = mg.mesh_file(feat_steps["boss"], H3, ac, {"t": 1.0, "E": 205000.0, "nu": 0.3}, out_dir=str(tmp_path / "b"))
    ds = meta["defeature_stage"]
    assert ds["counts"] == {"bead": 1, "hole": 5}
    doc = json.loads((tmp_path / "b" / mg.DEFEAT_LIST).read_text(encoding="utf-8"))
    hs = sorted((f["center"][0], round(f["size"]["d_mm"], 1)) for f in doc["features"] if f["kind"] == "hole")
    assert hs == [(40.0, 6.0), (100.0, 8.0), (160.0, 5.0), (220.0, 8.0), (250.0, 6.0)]
    X = np.asarray(m["x0"])
    for x, z in ((40.0, -4.0), (100.0, -3.0), (160.0, -5.0)):              # 보스 바닥(가운데 메움 면 포함)이 남음
        near = (np.abs(X[:, 0] - x) < 3.0) & (np.abs(X[:, 1] - 80.0) < 3.0)
        assert near.any() and np.allclose(X[near, 2], z, atol=1e-6), x
    low = (np.abs(X[:, 0] - 220.0) < 12.0) & (np.abs(X[:, 1] - 80.0) < 12.0)
    assert np.allclose(X[low, 2], 0.0, atol=1e-6)                          # 1 mm 보스 평탄화


@needs_gmsh
def test_stage_fidelity_fail(feat_steps, tmp_path):
    """V-SR-19: 바깥 편차 > remesh.fidelity.fail_mm → DEFEATURE_FIDELITY(시도 실패 — 사다리는 다음 단계)."""
    from esl.errors import EslError
    _cfg, _a, ac = _stage_cfg(remesh={"fidelity": {"fail_mm": 1e-4}})
    with pytest.raises(EslError) as ei:
        mg.mesh_file(feat_steps["boss"], H3, ac, {"t": 1.0, "E": 205000.0, "nu": 0.3})
    assert ei.value.code == "DEFEATURE_FIDELITY"


@needs_gmsh
def test_stage_no_feature(tmp_path):
    """억제 대상 0 → DEFEATURE_NO_FEATURE(메싱 안 함)."""
    from esl.errors import EslError
    src = scmp.plate_step(str(tmp_path / "p.step"), 0, Lx=200.0, Lz=150.0)
    _cfg, _a, ac = _stage_cfg()
    with pytest.raises(EslError) as ei:
        mg.mesh_file(src, H3, ac, {"t": 1.0, "E": 205000.0, "nu": 0.3})
    assert ei.value.code == "DEFEATURE_NO_FEATURE"


def test_list_doc_truncated_and_order():
    fs = [{"id": f"f{i}", "kind": k, "center": [float(9 - i), 0.0, 0.0], "bbox": [0] * 6, "size": {}, "area_mm2": 1.0,
           "faces": [1], "action": "suppressed" if i % 3 else "skipped", "method": "plane", "reason": None if i % 3 else "x"}
          for i, k in enumerate(["hole", "bead", "hole", "fillet", "bead", "hole"])]
    d = gdf.list_doc(fs, 4)
    assert d["n"] == 6 and d["truncated"] is True and len(d["features"]) == 4
    assert [f["kind"] for f in d["features"]] == ["bead", "bead", "fillet", "hole"]
    assert [f["center"][0] for f in d["features"][:2]] == [5.0, 8.0]
    assert d["counts"] == {"bead": 2, "hole": 2} and d["features"][0].get("reason") is None
