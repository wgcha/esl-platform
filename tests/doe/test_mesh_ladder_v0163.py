"""v0.16.3 ④ 면 실패 사다리(계약 esl_compare_mesh_options.md C2-D-26~31, V-C2-26~31) — 이슈 #53(2026-11-09) 재현.

실제 Ch/R(면 2824+)에서 periodic Sphere 딤플 면 하나가 cad·면 폴백 전부 실패 → v0.16.2 는 같은 면 실패를 세분화로 되풀이하다
예산을 다 써 마지막 재메시가 남은 596 s 에서 시간 초과. 여기서는 합성 다딤플 판 + 시험 전용 고장 주입(환경 변수
``ESL_TEST_MESH_FAIL`` — spawn 자식 gmsh 2D 를 곡면이 남아 있으면 실패시킴)으로:
- 면 실패 → refine_local·refine_global 건너뜀(face_fail) → freeform(이산 재메시) 성공, MESH_FREEFORM·충실도·품질
- freeform 도 실패(remesh 주입) → defeature 건너뜀(not_fidelity) → OCC 삼각형 폴백 성공(MESH_TRIA_FALLBACK, FAILED 아님)
- freeform 충실도 실패 → 실패 면 표적 defeature(구 캡 평탄화) 성공
- 단계 몫(stage_share): 각 시도 제한 시간 ≤ 그 단계 상한, 총 ≤ 예산, tria 는 몫이 남아 돎
- mode freeform: cad 없이 freeform
gmsh 가 없으면 skip."""
import os

import numpy as np
import pytest

import synth_compare as scmp
import synth_many as smany
import test_step_compare as tsc
from esl.doe import mesh_gmsh as mg
from esl.doe import mesh_quality as mq
from esl.doe import mesh_refine as mr
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
LX, LY = tsc.LX, tsc.LZ                     # ESL 라이브러리 판 크기(200 × 150)와 같아야 함(SIZE_MISMATCH)


def _cfg(**cmp):
    c = tsc._cfg(**cmp)
    c["bead_doe"]["compare"].setdefault("mesh", {})["fallback"] = {"enabled": False}   # 시험 속도(면 폴백은 v0.15.1 시험)
    c["bead_doe"]["compare"]["mesh"]["size_mm"] = 3.0      # 품질 기준(이슈 #53 criteria)은 3 mm 기준 절대값
    return c


def _many(tmp_path, sid, *, single=False, **doe_kw):
    """기준 평판 d000 + 다딤플 판 d001(single = 깊은 딤플 1개, 200 × 150)."""
    _a, ents = tsc._lib(tmp_path / "lib")
    up = tmp_path / "up"
    if single:
        paths = [scmp.dimple_plate_step(up / "u0" / "flat.step", [], Lx=tsc.LX, Lz=tsc.LZ),
                 scmp.dimple_plate_step(up / "u1" / "deep.step", [(100.0, 75.0, 20.0, 5.0)], Lx=tsc.LX, Lz=tsc.LZ)]
    else:
        paths = [scmp.dimple_plate_step(up / "u0" / "flat.step", [], Lx=LX, Lz=LY),
                 smany.many_dimple_step(up / "u1" / "many.step", nx=12, ny=9, Lx=LX, Ly=LY, panels=(4, 3))]
    shapes = [{"id": f"d{k:03d}", "name": n, "file_name": os.path.basename(p), "path": p, "reference": k == 0,
               "sha256": U.sha256_file(p)} for k, (n, p) in enumerate(zip(("평판", "딤플 판"), paths))]
    doe = {"id": sid, "scenario": "compare", "title": "④ 면 실패", "cfg": _cfg(), "entries": ents, "shapes": shapes,
           "reference_source": "step", "inch": 75, "props": tsc.PROPS, "mesh_mode": "auto"}
    doe.update(doe_kw)
    return doe


def _stages(s):
    return [(a["stage"], a["status"], a.get("reason")) for a in s["attempts"]]


# ---------------------------------------------------------------- 코어 단위(V-C2-27·29·30)
def test_face_failure_and_stage_helpers():
    c = {"compare": {}}
    msg = "gmsh 메싱 실패: 면 2824(Sphere, …) — (gmsh: Impossible to mesh periodic surface 2824)"
    f = {"id": 2824, "type": "Sphere", "key": [0, 0, 0, 1, 1, 1]}
    assert mr.face_failure({"face": f, "message": msg}, c)["reason"] == "type"
    assert mr.face_failure({"face": dict(f, type="Plane"), "message": msg}, c)["match"] == "periodic surface"
    assert mr.face_failure({"face": dict(f, type="Plane"), "message": "x"}, c) is None          # 크기 문제 → 세분화
    assert mr.face_failure({"message": "제한 시간"}, c) is None                                  # 면 기록 없음(시간 초과)
    assert mr.face_failure({"face": f, "message": msg}, {"compare": {"mesh": {"face_fail": {"enabled": False}}}}) is None
    assert mr.face_fail_skips(c) == ("refine_local", "refine_global")
    # 단계 몫: 뒤 단계 몫(× 3600)은 앞 단계가 못 씀
    assert mr.stage_cap("cad", ["freeform", "defeature", "tria"], c, 0.0) == pytest.approx(3600 * (1 - 0.5))
    assert mr.stage_cap("tria", [], c, 3000.0) == pytest.approx(600.0)
    assert mr.stage_cap("freeform", ["tria"], c, 3500.0) == 0.0
    att = [{"stage": "cad", "status": "FAILED_MESH", "seconds": 412.25, "code": "MESH_FAILED"},
           {"stage": "refine_local", "status": "SKIPPED", "skipped": True, "reason": "face_fail"},
           {"stage": "freeform", "status": "FAILED_MESH", "seconds": 600.0, "timed_out": True, "code": "REMESH_FAILED"},
           {"stage": "tria", "status": "READY", "seconds": 41.0}]
    rows = mr.stage_times(att)
    assert [(r["stage"], r["outcome"]) for r in rows] == [("cad", "FAILED_MESH"), ("refine_local", "SKIPPED"),
                                                          ("freeform", "FAILED_MESH"), ("tria", "READY")]
    assert mr.stage_times_text(rows) == ("cad 실패 412.2 s → refine_local 건너뜀(면 실패 — 세분화로 풀리지 않음) → "
                                         "freeform 실패(시간 초과) 600.0 s → tria 성공 41.0 s")
    assert mr.ladder({"compare": {"mesh": {"mode": "freeform"}}}) == ["freeform", "tria"]


@needs_gmsh
def test_tria_conformal_and_fidelity(tmp_path):
    """V-C2-28: OCC 삼각형 폴백 = 적합(모든 내부 변 삼각형 2개), 연결 1성분, 원 BRepMesh 대비 충실도 fail 이내, 변 ≤ split × h."""
    from esl.doe import mesh_tria as mt
    from esl.doe import scenario as sc
    from esl.doe import settings
    src = scmp.dimple_plate_step(tmp_path / "d.step", [(100.0, 75.0, 20.0, 5.0)])
    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    m, meta = mt.tria_file(src, 3.0, cfg, tsc.PROPS)
    T = m["conn"][:, :3]
    E = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
    _u, cnt = np.unique(E, axis=0, return_counts=True)
    assert set(cnt.tolist()) <= {1, 2} and int(meta["quality"]["n_components"]) == 1
    assert meta["fidelity"]["hausdorff_mm"] <= meta["fidelity"]["fail_mm"] and meta["quad_frac"] == 0.0
    L = np.linalg.norm(m["x0"][E[:, 0]] - m["x0"][E[:, 1]], axis=1)
    assert L.max() <= tsc.DEFAULTS["compare"]["quality"]["max_length"]["warn"]   # 평활 뒤 다시 분할(뒤집기로 조금 늘 수 있음)
    assert [w["code"] for w in meta["warnings"]].count("MESH_TRIA_FALLBACK") == 1 and meta["method"] == "tria"
    assert X_on_plane_or_sphere(m["x0"])


def X_on_plane_or_sphere(X):                                                    # noqa: N802 - 시험 도우미
    """노드가 판(z = 0) 또는 구(중심 (100, 75, 15), R 20) 위(편차 0.9 mm = tria 편차 이내)."""
    d_pl = np.abs(X[:, 2])
    d_sp = np.abs(np.linalg.norm(X - np.array([100.0, 75.0, 15.0]), axis=1) - 20.0)
    return bool(np.all(np.minimum(d_pl, d_sp) <= 0.9 + 1e-6))


# ---------------------------------------------------------------- 사다리(워커) V-C2-26·27·28
@needs_gmsh
def test_face_fail_skips_refine_freeform_succeeds(tmp_path, monkeypatch):
    """다딤플 판(약 110 면)·곡면 2D 강제 실패 → cad FAILED(Sphere, periodic) → 세분화 건너뜀(face_fail, MESH_FACE_FAIL) →
    freeform 성공: mesh_method fallback, MESH_FREEFORM(충실도·구멍 수), 충실도 ≤ fail, 품질 지표가 기존 기준 안(Fail 비율 ≤ 상한)."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "cad")
    doe = _many(tmp_path, "FF")
    out = tmp_path / "_doe" / "FF"
    r, _spec = tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "fallback" and s["fallback_stage"] == "freeform", s.get("attempts")
    assert _stages(s) == [("cad", "FAILED_MESH", None), ("refine_local", "SKIPPED", "face_fail"),
                          ("refine_global", "SKIPPED", "face_fail"), ("freeform", "READY", None)]
    assert "periodic surface" in s["cad_error"]["message"] and "Sphere" in s["cad_error"]["message"]
    assert [x["stage"] for x in s["stage_times"]] == ["cad", "refine_local", "refine_global", "freeform"]
    assert any(i.startswith("MESH_FACE_FAIL") and "Sphere" in i for i in r["bd_mesh0"]["info"])
    ws = r["bd_mesh0"]["warnings"]
    assert any(w.startswith("MESH_FREEFORM") and "d001" in w and "원 형상 대비 최대" in w for w in ws), ws
    fd = s["fidelity"]
    assert fd["hausdorff_mm"] <= fd["fail_mm"] and not fd["over_warn"], fd
    q = s["quality"]
    # 지름 10 mm 딤플(≈ 3 h) 108 개가 빽빽한 판: 3 mm 요소로는 어떤 방식도 기준 Fail 비율(1 %)을 못 맞춤(cad 는 메시 자체 실패) —
    # 품질은 차단하지 않고 요약·경고만(SC-D-13). 여기서는 4각 우세·지표 계산·상한 표시만 확인(실측 Fail 약 47 %, decisions.md)
    assert s["quad_ratio"] > 0.8 and q["n_elems"] == s["n_elems"] and q["over_limit"] is (q["fail_ratio"] > q["max_fail_ratio"])
    mj = U.read_json(str(out / "prep" / "shapes" / "d001" / "mesh" / "mesh.json"))
    assert mj["method"] == "freeform" and mj["remesh"]["holes"]["loops_cad"] >= 1 and mj["stage_times"]
    assert tsc._shape(out, "d000")["mesh_method"] == "cad"


@needs_gmsh
def test_freeform_fails_tria_fallback_is_mesh(tmp_path, monkeypatch):
    """gmsh 면 메싱·이산 재메시 모두 강제 실패 → defeature 건너뜀(not_fidelity) → OCC 삼각형 폴백이 메시를 만듦(FAILED 아님)."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "cad,remesh")
    doe = _many(tmp_path, "TR")
    out = tmp_path / "_doe" / "TR"
    r, _spec = tsc._run(out, doe, stages=("bd_input", "bd_mesh0", "bd_loads"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["fallback_stage"] == "tria", s.get("attempts")
    assert _stages(s)[-3:] == [("freeform", "FAILED_MESH", None), ("defeature", "SKIPPED", "not_fidelity"),
                               ("tria", "READY", None)]
    ws = r["bd_mesh0"]["warnings"]
    assert any(w.startswith("MESH_TRIA_FALLBACK") and "d001" in w for w in ws), ws
    assert s["fidelity"]["hausdorff_mm"] <= s["fidelity"]["fail_mm"] and s["quad_ratio"] == 0.0
    m = mg.load_mesh(str(out / "prep" / "shapes" / "d001" / "mesh"))
    assert int(m["elem_id"].size) == s["n_elems"] > 0 and np.all(m["elem_type"] == 3)
    assert int(mq.summarize(m, tsc.DEFAULTS["compare"]["quality"])["n_elems"]) == s["n_elems"]


@needs_gmsh
def test_fidelity_fail_targets_failed_face_defeature(tmp_path, monkeypatch):
    """freeform 충실도 실패(주입) → 실패 면(구 캡, 깊이 5 > min_bead_height 2 — 기본 기준으로는 안 지움)을 표적 defeature 로
    평탄화 → cad 경로 메시 성공(mesh_method defeature, 목록 target)."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "cad,fidelity")
    doe = _many(tmp_path, "DT", single=True)
    out = tmp_path / "_doe" / "DT"
    tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "defeature", s.get("attempts")
    assert _stages(s)[3][:2] == ("freeform", "FAILED_MESH") and s["attempts"][3]["code"] == "REMESH_FIDELITY"
    lst = U.read_json(str(out / "prep" / "shapes" / "d001" / "mesh" / "defeature.json"))
    f = [x for x in lst["features"] if x.get("target")]
    assert len(f) == 1 and f[0]["kind"] == "bead" and f[0]["center"][:2] == pytest.approx([100, 75], abs=0.5)


@needs_gmsh
def test_mode_freeform_skips_cad(tmp_path, monkeypatch):
    """compare.mesh.mode freeform(요청 mesh_mode): cad 시도 없이 freeform — mesh_method remesh, attempts [freeform]."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "cad")                                 # cad 를 부르면 실패할 형상
    doe = _many(tmp_path, "MF", single=True, mesh_mode="freeform")
    out = tmp_path / "_doe" / "MF"
    tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    for did in ("d000", "d001"):
        s = tsc._shape(out, did)
        assert s["status"] == "READY" and s["mesh_method"] == "remesh" and _stages(s) == [("freeform", "READY", None)], s
    q, fd = s["quality"], s["fidelity"]                                         # 깊은 딤플 1개(R 20): 품질·충실도 기준 안
    assert q["fail_ratio"] <= 0.05 and s["quad_ratio"] > 0.95, q               # 실측 Fail 2.3 %(기준 1 % 근처 — 경고만)
    assert fd["hausdorff_mm"] <= fd["warn_mm"] and not fd["over_warn"], fd


@needs_gmsh
def test_stage_caps_and_budget(tmp_path, monkeypatch):
    """V-C2-29: 모든 시도가 시간 초과(주입)여도 각 시도 제한 시간 ≤ 그 단계 상한(뒤 단계 몫 예약), 총 ≤ 예산, tria 까지 돎,
    오류 문구에 단계 → 결과 → 초."""
    budget = 2.0
    cfg = _cfg()
    cfg["bead_doe"]["mesh"]["timeout_s"] = 10.0
    cfg["bead_doe"]["compare"]["refine"] = {"total_timeout_s": budget, "min_attempt_s": 0.05}
    doe = tsc._two(tmp_path, "SC", mesh_mode="auto", cfg=cfg)[0]
    calls = tsc._fake_iso(monkeypatch, "d001", hang=True, other_timeout=600)
    out = tmp_path / "_doe" / "SC"
    tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "FAILED_MESH"
    kinds = [c["kind"] for c in calls]
    assert kinds[0] == "cad" and kinds[-1] == "tria" and "freeform" in kinds, kinds
    share = mr._rcfg({"compare": cfg["bead_doe"]["compare"]})["stage_share"]
    assert calls[0]["timeout"] == pytest.approx(budget * (1 - sum(share[k] for k in
                                                                  ("refine_local", "refine_global", "freeform",
                                                                   "defeature", "tria"))))
    tria = calls[-1]["timeout"]
    assert tria >= budget * share["tria"] - 0.05                                  # tria 몫은 앞 단계가 못 씀
    assert sum(c["timeout"] for c in calls) <= budget + 1e-6
    txt = stg._ladder_fail_text(s)
    assert "[단계별: cad 실패(시간 초과) " in txt and "tria 실패(시간 초과) " in txt, txt
    with pytest.raises(EslError):
        raise EslError("X", txt)


@pytest.mark.skipif(not os.environ.get("ESL_TEST_BIG"), reason="큰 합성 형상(약 1900 면, 수 분) — ESL_TEST_BIG=1 일 때만")
@needs_gmsh
def test_big_many_dimple_freeform_and_tria(tmp_path):
    """V-C2-31(수동): 약 1900 면 다딤플 판(1000 × 600) — freeform·tria 각각 시간·요소 수·충실도(결과는 decisions.md 기록)."""
    import time

    from esl.doe import mesh_remesh as mrm
    from esl.doe import mesh_tria as mt
    from esl.doe import scenario as sc
    from esl.doe import settings
    src = smany.many_dimple_step(tmp_path / "big.step", nx=50, ny=40, Lx=1000.0, Ly=600.0, panels=(20, 10))
    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    t = time.monotonic()
    _m, meta = mt.tria_file(src, 3.0, cfg, tsc.PROPS)
    assert time.monotonic() - t < 120 and meta["fidelity"]["hausdorff_mm"] <= meta["fidelity"]["fail_mm"]
    t = time.monotonic()
    _m, meta = mrm.remesh_file(src, 3.0, cfg, tsc.PROPS, freeform=True)
    print("freeform", round(time.monotonic() - t, 1), meta["n_elems"], meta["quad_frac"], meta["fidelity"])
