"""v0.16.0 ④ 삼각형 재메시(esl_compare_mesh_options.md §4 R1~R8, C2-D-11~14, V-C2-1·2·4). gmsh 없으면 skip.

합성 형상: ``synth_complex.complex_plate_step``(띠·쐐기 면·구 캡·Ø2 구멍), ``synth_compare.bead_with_features_step``(비드·딤플·
구멍·버링 — 필렛 없이는 재메시 성공, 필렛 연쇄(접선 연속)는 면 분류가 한 패치로 묶어 매개변수화가 실패 → REMESH_CLASSIFY_FAILED,
리스크 R-C2-2 를 시험으로 고정)."""
import json

import numpy as np
import pytest

import synth_compare as scmp
import synth_complex as scx
from esl.doe import DEFAULTS, settings
from esl.doe import mesh_gmsh as mg
from esl.doe import mesh_input as mi
from esl.doe import mesh_quality as mq
from esl.doe import mesh_remesh as mr
from esl.doe import scenario as sc
from esl.errors import EslError

needs_remesh = pytest.mark.skipif(not mr.available()[0], reason="gmsh importStl 없음")
PROPS = {"t": 1.0, "E": 205000.0, "nu": 0.3}
H = 3.0
CURVE = {"curve_angle_deg": 60.0}         # 판 모서리 꼭짓점 유지(180 이면 바깥 경계가 곡선 1개 → 모서리 깎임 0.8 mm)


def _cfg(remesh=None, **mesh):
    c = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                              "compare": {"remesh": dict(CURVE, **(remesh or {}))}}}))
    c["mesh"].update(mesh)
    return c


def _code(fn, *a, **k):
    with pytest.raises(EslError) as ei:
        fn(*a, **k)
    return ei.value


# ---------------------------------------------------------------- 단위
def test_point_triangle_distance():
    A, B, C = np.array([0.0, 0, 0]), np.array([4.0, 0, 0]), np.array([0.0, 3, 0])
    P = np.array([[1.0, 1, 2], [-1, -1, 0], [2, -2, 0], [3, 3, 0], [5, 0, 1], [-2, 1.5, 0], [0, 0, 0]])
    d = mr.point_tri_dist(P, A, B, C)
    assert d[0] == pytest.approx(2.0)                                   # 내부 위
    assert d[1] == pytest.approx(np.sqrt(2)) and d[4] == pytest.approx(np.sqrt(2))   # 꼭짓점 A·B 바깥
    assert d[2] == pytest.approx(2.0) and d[5] == pytest.approx(2.0)    # 변 A-B·C-A 바깥
    assert d[3] == pytest.approx(abs(np.array([3.0 - 4.0, 3.0]) @ np.array([3.0, 4.0]) / 5.0))    # 변 B-C 바깥(법선 성분)
    assert d[6] == 0.0
    rng = np.random.default_rng(0)                                     # 무작위: 조밀 표본 최솟값 이하·근사
    T = rng.normal(size=(3, 3))
    Q = rng.normal(size=(50, 3)) * 2
    u, v = np.meshgrid(np.linspace(0, 1, 201), np.linspace(0, 1, 201))
    ok = u + v <= 1
    S = T[0] + u[ok][:, None] * (T[1] - T[0]) + v[ok][:, None] * (T[2] - T[0])
    brute = np.min(np.linalg.norm(Q[:, None, :] - S[None], axis=2), axis=1)
    dd = mr.point_tri_dist(Q, T[0], T[1], T[2])
    assert np.all(dd <= brute + 1e-12) and np.allclose(dd, brute, atol=0.02)


def test_merge_and_subdivide():
    X = np.array([[0.0, 0, 0], [10, 0, 0], [0, 10, 0], [10, 0, 0.0005], [10, 10, 0]])
    T = np.array([[0, 1, 2], [3, 4, 2], [0, 0, 1]])
    X2, T2, n = mr.merge_nodes(X, T, 0.001)
    assert n == 1 and X2.shape[0] == 4 and T2.shape[0] == 2                 # 노드 3→1 병합, 퇴화 삼각형 제거
    sx, st = mr.subdivide(X2, T2, 3.0)
    L = np.linalg.norm(sx[st[:, [1, 2, 0]]] - sx[st], axis=2)
    assert L.max() <= 3.0 and abs(mr._tri_area(sx, st) - mr._tri_area(X2, T2)) < 1e-9


def test_run_isolated_kind_checked(tmp_path):
    with pytest.raises(EslError) as ei:
        mg.run_isolated("x.step", str(tmp_path), H, _cfg(), PROPS, kind="bad")
    assert ei.value.code == "INPUT_INVALID"


# ---------------------------------------------------------------- V-C2-1·2
@needs_remesh
def test_complex_plate_remesh_isolated_and_deterministic(tmp_path):
    """V-C2-1 합성 복잡 STEP → remesh 성공(quad ≥ 0.9, 모서리 중앙값 h ± 15 %, 품질 over_limit false, hausdorff < warn),
    작은 구멍(Ø2) 메움. V-C2-2 같은 STEP 을 spawn 2회 → mesh.npz 바이트 동일, mesh.json(시간 제외) 동일."""
    src = scx.complex_plate_step(tmp_path / "c.step")
    cfg = _cfg()
    m, meta = mg.run_isolated(src, str(tmp_path / "a"), H, cfg, PROPS, kind="remesh")
    mg.run_isolated(src, str(tmp_path / "b"), H, cfg, PROPS, kind="remesh")
    assert meta["method"] == "remesh" and meta["gmsh_version"] and meta["occ_version"]
    assert meta["quad_frac"] >= 0.9 and not meta["errors"]
    assert abs(mi.edge_median(m) - H) <= 0.15 * H
    assert mq.summarize(m, DEFAULTS["compare"]["quality"])["over_limit"] is False
    f = meta["fidelity"]
    assert f["hausdorff_mm"] < f["warn_mm"] and not f["over_warn"] and abs(f["area_ratio"] - 1.0) < 1e-3
    assert meta["defeature"]["filled"] == 1 and meta["remesh"]["resewn"] is True
    assert any(i["code"] == "REMESH_HOLE_SIZING_SKIPPED" for i in meta["infos"])
    assert mi.n_components(m) == 1
    assert (tmp_path / "a" / mg.MESH_NPZ).read_bytes() == (tmp_path / "b" / mg.MESH_NPZ).read_bytes()
    ja, jb = (json.loads((tmp_path / d / mg.MESH_JSON).read_text(encoding="utf-8")) for d in ("a", "b"))
    ja.pop("seconds"), jb.pop("seconds")
    assert ja == jb
    assert not (tmp_path / "a" / mr.STL_NPZ).exists()                  # keep_stl false


@needs_remesh
def test_bead_features_remesh_and_fillet_limit(tmp_path):
    """bead_with_features(필렛 없음): 딤플 3·Ø5 메움·Ø10·버링 → 재메시 성공, 한 덩어리(메움 뒤 봉합). 필렛 있음 → 비드 벽·필렛·판이
    접선 연속이라 한 패치 → 매개변수화 실패 REMESH_CLASSIFY_FAILED(R-C2-2 — 실패 문구로 메시 입력 안내)."""
    src = scmp.bead_with_features_step(tmp_path / "b.step", {"bead_fillet": 0, "dimple_fillet": 0})
    m, meta = mr.remesh_file(src, H, _cfg(remesh={"keep_stl": True}), PROPS, out_dir=str(tmp_path / "o"))
    assert meta["quad_frac"] >= 0.9 and mi.n_components(m) == 1 and meta["defeature"]["filled"] == 1
    assert (tmp_path / "o" / mr.STL_NPZ).is_file()
    assert np.isclose(m["x0"][:, 2].min(), -28.0, atol=0.1)             # 깊은 반구 바닥·버링 끝 유지
    filleted = scmp.bead_with_features_step(tmp_path / "f.step")
    e = _code(mr.remesh_file, filleted, H, _cfg(), PROPS)
    assert e.code == "REMESH_CLASSIFY_FAILED" and "특징각" in e.message


# ---------------------------------------------------------------- V-C2-4 충실도
@needs_remesh
def test_fidelity_thresholds(tmp_path):
    """특징각 89°(구 캡 테두리 43° 가 특징이 아님 → 둥글어짐)·편차 2 mm 로 거칠게: hausdorff 가 warn 을 넘어 REMESH_FIDELITY_WARN,
    fail_mm 를 그 값 아래로 → REMESH_FIDELITY(mesh.json 은 남음), fail_mm null → 실패 없음. 구멍 메움 영역은 S·M 둘 다 메운 형상이라
    지표에 안 들어감(정상 설정 hausdorff < warn — test_complex_plate…)."""
    src = scx.complex_plate_step(tmp_path / "c.step")
    rough = {"feature_angle_deg": 89.0, "linear_deflection_mm": 2.0, "fidelity": {"warn_mm": 0.05, "fail_mm": None}}
    _m, meta = mr.remesh_file(src, H, _cfg(remesh=rough), PROPS)
    hd = meta["fidelity"]["hausdorff_mm"]
    assert hd > 0.05 and meta["fidelity"]["over_warn"] and meta["fidelity"]["fail_mm"] is None
    assert any(w["code"] == "REMESH_FIDELITY_WARN" for w in meta["warnings"])
    bad = dict(rough, fidelity={"warn_mm": 0.05, "fail_mm": round(hd * 0.5, 6)})
    e = _code(mr.remesh_file, src, H, _cfg(remesh=bad), PROPS, out_dir=str(tmp_path / "f"))
    assert e.code == "REMESH_FIDELITY"
    mj = json.loads((tmp_path / "f" / mg.MESH_JSON).read_text(encoding="utf-8"))
    assert mj["errors"][0]["code"] == "REMESH_FIDELITY"
    ok = dict(rough, fidelity={"warn_mm": 0.05, "fail_mm": round(hd * 2.0, 6)})
    assert mr.remesh_file(src, H, _cfg(remesh=ok), PROPS)[1]["fidelity"]["hausdorff_mm"] == pytest.approx(hd)


@needs_remesh
def test_stl_limit_and_too_large(tmp_path):
    src = scx.complex_plate_step(tmp_path / "c.step")
    e = _code(mr.remesh_file, src, H, _cfg(remesh={"stl_max_tris": 10}), PROPS)
    assert e.code == "REMESH_FAILED" and "stl_max_tris" in e.message
    e = _code(mr.remesh_file, src, H, _cfg(max_elems=100), PROPS)
    assert e.code == "MESH_TOO_LARGE"
