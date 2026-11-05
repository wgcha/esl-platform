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
