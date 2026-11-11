"""v0.17.4 ④ cad 단계 메싱(계약 esl_compare_mesh_options.md C2-D-32~36, V-C2-32~36) — 실제 Ch/R(면 약 2800, periodic Sphere
면 2824)가 ③ 에서는 되고 ④ 에서는 실패·지연되던 문제.

- cad_relaxed: OCC 정리(occ_fix_small 1)가 Sphere 딤플 면을 깨면 면 폴백 전에 모델 전체를 ③ 옵션으로 1세션 → 채택(MESH_CAD_RELAXED)
- 자식 제한: spawn 제한보다 먼저 끝나 mesh_error.json 에 실패 면(로그 마지막 면)을 남김 → 면 실패 → 세분화 건너뜀
- 대형 모델: 면 폴백 세션 상한·cad 몫 줄임
gmsh 가 없으면 skip."""
import os

import pytest

import synth_compare as scmp
import synth_many as smany
import test_step_compare as tsc
from esl.doe import DEFAULTS
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import settings
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")


def _ccfg(**mesh):
    """④ 프로필(h 3 mm, 기본 occ_fix_small 1·곡률 0·최소 0.8 h) + 시험 덮어쓰기."""
    c = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "compare": {"mesh": {"size_mm": 3.0, **mesh}}}}))
    return c


def _doe(tmp_path, sid, p1, *, mesh=None, base_mesh=None, **kw):
    _a, ents = tsc._lib(tmp_path / "lib")
    p0 = scmp.dimple_plate_step(tmp_path / "up" / "u0" / "flat.step", [], Lx=tsc.LX, Lz=tsc.LZ)
    shapes = [{"id": f"d{k:03d}", "name": n, "file_name": os.path.basename(str(p)), "path": str(p), "reference": k == 0,
               "sha256": U.sha256_file(str(p))} for k, (n, p) in enumerate(zip(("평판", "딤플 판"), (p0, p1)))]
    cfg = {"bead_doe": {"enabled": True, "mesh": dict(base_mesh or {}),
                        "compare": {"mesh": {"size_mm": 3.0, "fallback": {"enabled": False}, **(mesh or {})}}},
           "opt_run": {"solver": {"backend": "superlu"}}}
    doe = {"id": sid, "scenario": "compare", "title": "④ cad_relaxed", "cfg": cfg, "entries": ents, "shapes": shapes,
           "reference_source": "step", "inch": 75, "props": tsc.PROPS, "mesh_mode": "auto"}
    doe.update(kw)
    return doe


# ---------------------------------------------------------------- 코어(V-C2-32·33)
@needs_gmsh
def test_step_scan_and_large(tmp_path):
    """STEP 본문 세기(면·Sphere) = gmsh 가져오기 면 수, 대형 판정(면 > large_faces 또는 Sphere), ③ 프로필(키 없음)은 항상 아님."""
    p = smany.many_dimple_step(tmp_path / "m.step", nx=12, ny=9, Lx=200.0, Ly=150.0, panels=(4, 3))
    s = mg.step_scan(p, ["Sphere"])
    assert s["n_faces"] == 105 and s["periodic"] == {"Sphere": 93}
    assert mg.large_model(p, _ccfg()["mesh"]) == {"large": True, "reason": ["periodic"], **s}
    flat = scmp.dimple_plate_step(tmp_path / "f.step", [])
    assert mg.large_model(flat, _ccfg()["mesh"])["large"] is False
    assert mg.large_model(flat, _ccfg(large_faces=0)["mesh"])["reason"] == ["faces"]
    assert mg.large_model(p, settings({"bead_doe": {"enabled": True}})["mesh"]) == {"large": False}   # ③
    assert mg.step_scan(str(tmp_path / "x.brep"))["n_faces"] is None


@needs_gmsh
def test_cad_relaxed_in_child_real_occfix(tmp_path):
    """실제 gmsh: 면 공유 다딤플 판은 OCC 정리 1 로 Sphere 면 2D 실패 → cad_relaxed(정리 끔·곡률 12·최소 0.2 h) 1세션 성공,
    품질 오류 없음·충실도 ≤ fail_mm, MESH_CAD_RELAXED, options 에 OCCFix 없음. cad_relaxed 끔 → FAILED_MESH(예전 그대로)."""
    p = smany.many_dimple_solid_step(tmp_path / "s.step")
    cfg = _ccfg(fallback={"enabled": False})
    m, meta = mg.mesh_file(p, 3.0, cfg, tsc.PROPS)
    rx = meta["cad_relaxed"]
    assert rx["ok"] and rx["overrides"] == {"occ_fix_small": 0, "curvature_n": 12, "min_size_factor": 0.2,
                                            "defeature": False}
    assert rx["face"]["type"] == "Sphere" and "closed loop" in rx["first_error"]
    assert rx["fidelity"]["hausdorff_mm"] <= rx["fidelity"]["fail_mm"] and not meta["errors"]
    assert "Geometry.OCCFixDegenerated" not in meta["options"] and meta["options"]["Mesh.MeshSizeFromCurvature"] == 12
    assert [w["code"] for w in meta["warnings"]].count("MESH_CAD_RELAXED") == 1 and "mesh_fallback" not in meta
    off = _ccfg(fallback={"enabled": False}, cad_relaxed={"enabled": False})
    with pytest.raises(EslError) as ei:
        mg.mesh_file(p, 3.0, off, tsc.PROPS)
    assert "closed loop" in ei.value.message


@needs_gmsh
def test_cad_relaxed_rejects_disconnected(tmp_path):
    """면을 공유하지 않는 다딤플 판(synth_many): 정리 끔 메시가 여러 성분(MESH_DISCONNECTED) → 채택하지 않고 면 폴백으로."""
    p = smany.many_dimple_step(tmp_path / "m.step", nx=6, ny=4, Lx=200.0, Ly=150.0, panels=(2, 2), holes_every=0)
    with pytest.raises(EslError):
        mg.mesh_file(p, 3.0, _ccfg(fallback={"enabled": False}), tsc.PROPS)
    assert mg._RUN["relaxed"]["ok"] is False and "MESH_DISCONNECTED" in mg._RUN["relaxed"]["error"]


@needs_gmsh
def test_large_model_caps_fallback_sessions(tmp_path):
    """대형 모델: 면 폴백 세션(STEP 재가져오기) ≤ large.fallback_sessions → 그 뒤 FAILED_MESH(실패 면 기록 — 사다리 face_fail).
    대형 아님 = 상한 없음(예전 — 면마다 12단계)."""
    p = smany.many_dimple_step(tmp_path / "m.step", nx=6, ny=4, Lx=200.0, Ly=150.0, panels=(2, 2), holes_every=0)
    cfg = _ccfg(cad_relaxed={"enabled": False}, large={"fallback_sessions": 2})
    with pytest.raises(EslError) as ei:
        mg.mesh_file(p, 3.0, cfg, tsc.PROPS, large=True)
    assert "세션 2회 상한" in ei.value.message and mg._RUN["sessions"] == 3
    with pytest.raises(EslError) as ei:
        mg.mesh_file(p, 3.0, dict(cfg, mesh=dict(cfg["mesh"], timeout_s=60)), tsc.PROPS)
    assert "fallback_sessions" not in ei.value.message and mg._RUN["sessions"] > 3


def test_large_model_cad_share(tmp_path, monkeypatch):
    """대형 모델 auto: cad 제한 = min(기존 cad 몫, large.cad_share × total_timeout_s), large 인자 전달. 대형 아님 = 예전 그대로."""
    seen = []

    def fake(c, row, h, ccfg, props, *, fail_info=False, timeout_s=None, large=False):
        seen.append((timeout_s, large))
        return {"id": row["id"], "status": "READY", "code": None, "message": None}
    monkeypatch.setattr(stg, "_cmp_mesh_one", fake)
    monkeypatch.setattr(stg, "_cmp_mesh_dir", lambda c, did: str(tmp_path / did))
    big = smany.many_dimple_step(tmp_path / "m.step", nx=3, ny=2, Lx=60.0, Ly=40.0, panels=(1, 1), holes_every=0)
    flat = scmp.dimple_plate_step(tmp_path / "f.step", [])

    class C:
        def p(self, rel):
            return rel
    lad = ["cad", "refine_local", "refine_global", "freeform", "defeature", "tria"]
    cc = _ccfg()
    for src in (big, flat):
        stg._cmp_mesh_shape(C(), {"id": "d001", "rel": src}, 3.0, cc, tsc.PROPS, "auto", lad, True, None)
    assert seen[0] == (pytest.approx(0.15 * 3600), True)
    assert seen[1] == (pytest.approx(3600 * 0.3), False)          # 기존 몫(뒤 단계 몫 0.7 예약)


# ---------------------------------------------------------------- 사다리(워커 단계) V-C2-32·34·35
@needs_gmsh
def test_pipeline_cad_relaxed_ready(tmp_path):
    """④ auto: d001(면 공유 다딤플) cad 첫 세션 실패 → 자식 안 cad_relaxed 성공 = READY, mesh_method cad, mesh_path cad_relaxed,
    stage_times cad 실패 → cad_relaxed 성공, 경고 MESH_CAD_RELAXED(단계별 초), 사다리 미진입. d000 은 키 없음(바이트 불변 경로)."""
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step")
    doe = _doe(tmp_path, "RX", p1)
    out = tmp_path / "_doe" / "RX"
    r, _spec = tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "cad" and s["mesh_path"] == "cad_relaxed", s
    assert [(x["stage"], x["outcome"]) for x in s["stage_times"]] == [("cad", "FAILED_MESH"), ("cad_relaxed", "READY")]
    assert s["large"]["reason"] == ["periodic"] and "cad_error" not in s
    ws = r["bd_mesh0"]["warnings"]
    assert any(w.startswith("MESH_CAD_RELAXED: d001") and "[단계별: cad 실패" in w for w in ws), ws
    d0 = tsc._shape(out, "d000")
    assert not {"cad_relaxed", "mesh_path", "stage_times", "large"} & set(d0)
    mj = U.read_json(str(out / "prep" / "shapes" / "d001" / "mesh" / "mesh.json"))
    assert mj["cad_relaxed"]["ok"] and not os.path.exists(out / "prep" / "shapes" / "d001" / "mesh" / "try_1")


@needs_gmsh
def test_child_timeout_record_face_fail(tmp_path, monkeypatch):
    """gmsh 2D 가 Sphere 면에서 멈춤(시험 주입 hang): 자식 감시 타이머가 spawn 제한 전에 mesh_error.json(시간 초과 + 로그 마지막
    면 Sphere·bbox key) → 면 실패(C2-D-35) → refine_local·refine_global 건너뜀 → 부모 cad_relaxed(direct) 성공."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "hang")
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step", nx=3, ny=2)
    doe = _doe(tmp_path, "TO", p1, base_mesh={"timeout_s": 20}, mesh={"child_margin_s": 4.0},
               mesh_ladder=["cad", "refine_local", "refine_global", "freeform"])
    out = tmp_path / "_doe" / "TO"
    r, _spec = tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    st = [(a["stage"], a["status"], a.get("reason"), bool(a.get("timed_out"))) for a in s["attempts"]]
    assert st[0] == ("cad", "FAILED_MESH", None, True) and st[1][:2] == ("cad_relaxed", "READY"), st
    assert s["status"] == "READY" and s["mesh_path"] == "cad_relaxed" and s["cad_relaxed"]["after_timeout"]
    assert s["attempts"][0]["seconds"] < 20.0                     # 자식이 먼저 끝남(spawn 20 s 전)
    assert any(i.startswith("MESH_FACE_FAIL") and "Sphere" in i for i in r["bd_mesh0"]["info"])


@needs_gmsh
def test_child_timeout_skips_refine_without_relaxed(tmp_path, monkeypatch):
    """cad_relaxed 끔: 시간 초과 cad 기록 = 면 실패 → 세분화 두 단계 건너뜀(예전: 면 기록이 없어 refine_global 이 몫을 다 씀)."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "hang")
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step", nx=3, ny=2)
    doe = _doe(tmp_path, "TS", p1, base_mesh={"timeout_s": 20},
               mesh={"child_margin_s": 4.0, "heartbeat_s": 5.0, "cad_relaxed": {"enabled": False}},
               mesh_ladder=["cad", "refine_local", "refine_global", "freeform"])
    doe["cfg"]["bead_doe"]["compare"]["min_ready_shapes"] = 0
    out = tmp_path / "_doe" / "TS"
    log: list = []
    for st in ("bd_input", "bd_mesh0"):
        stg.run_stage({"stage": st, "out": str(out), "doe": doe}, log.append)
    s = tsc._shape(out, "d001")
    # C2-D-39 진행 줄: cad 대기 중 heartbeat, 사다리 단계 시작·건너뜀 / C2-D-40 cad 로그 보관
    assert any("] cad 진행 중" in m for m in log) and any("사다리 refine_local 건너뜀(면 실패)" in m for m in log), log
    assert (out / "prep" / "shapes" / "d001" / "mesh" / "attempt_logs" / "cad.mesh_error.json").is_file()
    st = [(a["stage"], a["status"], a.get("reason")) for a in s["attempts"]]
    assert st[:3] == [("cad", "FAILED_MESH", None), ("refine_local", "SKIPPED", "face_fail"),
                      ("refine_global", "SKIPPED", "face_fail")], st
    assert st[3][0] == "freeform"


def test_log_face_parse(tmp_path):
    """mesh.log 끝: periodic 문구 > [mesh_fallback] > gmsh 'Meshing surface N (종류' — faces 가 있으면 key·중심."""
    lp = tmp_path / "mesh.log"
    lp.write_text("Info    : [ 10%] Meshing surface 3 (Plane, Frontal-Delaunay for Quads)\n"
                  "Info    : [ 20%] Meshing surface 7 (Sphere, Frontal-Delaunay for Quads)\n", encoding="utf-8")
    f = mg.log_face(str(lp), {7: {"type": "Sphere", "key": (0, 0, -2, 2, 2, 0)}})
    assert f == {"id": 7, "type": "Sphere", "key": [0.0, 0.0, -2.0, 2.0, 2.0, 0.0], "center": [1.0, 1.0, -1.0]}
    lp.write_text("x Impossible to mesh periodic surface 9\n", encoding="utf-8")
    assert mg.log_face(str(lp)) == {"id": 9, "type": None, "error": "Impossible to mesh periodic surface 9"}
    assert mg.log_face(str(tmp_path / "none.log")) is None
    m = {"face_fail": DEFAULTS["compare"]["mesh"]["face_fail"], "fallback": {"periodic_types": ["Sphere"]}}
    assert stg._cmp_timeout_face(str(tmp_path), {"log_face": {"id": 7, "type": "Sphere"}}, {"mesh": m})["match"] == "Sphere"
    assert stg._cmp_timeout_face(str(tmp_path), {"log_face": {"id": 3, "type": "Plane"}}, {"mesh": m}) is None


# ---------------------------------------------------------------- 현장 진단(이슈 #63) 반영 V-C2-37~41
def test_pick_grown_face_and_hint():
    """C2-D-38 OCC 정리가 조각(0.08 mm²)을 완전한 구(63.53 mm²)로 키운 면: 엄격 대응 0개 → bbox 안·넓이 축소 후보 1개.
    C2-D-37 MESH_DISCONNECTED 안내 = 실제 원인(구멍 메움 실패 / OCC 정리 / 봉합)."""
    key = (29.23, 441.0, -4.25, 33.73, 445.5, 0.25)                    # 완전한 구(r 2.25) bbox
    cands = [(11, "Sphere", 0.08, (31.0, 443.0, -2.1, 31.6, 443.5, -1.9)),
             (12, "Plane", 0.05, (31.0, 443.0, -2.1, 31.6, 443.5, -1.9)),
             (13, "Sphere", 0.08, (90.0, 443.0, -2.1, 91.6, 443.5, -1.9))]
    with pytest.raises(mg._GeomSkip):
        mg._pick_same_face(cands, key, "Sphere", 63.53, 1e-2, 1e-2)
    assert mg._pick_grown_face(cands, key, "Sphere", 63.53, 1e-2, 1000.0) == 11
    with pytest.raises(mg._GeomSkip):
        mg._pick_grown_face(cands, key, "Sphere", 63.53, 1e-2, 100.0)      # 0.08 < 63.53 / 100
    e = [{"code": "MESH_DISCONNECTED", "message": "메시 연결 성분 4개 — 면이 서로 붙어 있지 않은 형상(설정 bead_doe.mesh.occ_sew_faces 1 검토)"}]
    m_fix = _ccfg()["mesh"]
    assert "defeature.enabled false" in mg.disconnected_hint(e, {"warnings": ["DEFEATURE_SKIPPED: x"]}, m_fix)[0]["message"]
    assert "occ_fix_small 0" in mg.disconnected_hint(e, None, m_fix)[0]["message"]
    assert "occ_sew_faces 1" in mg.disconnected_hint(e, None, dict(m_fix, occ_fix_small=0))[0]["message"]
    assert DEFAULTS["select"]["graph"]["limits"]["max_elems"] == 600000              # 현장 ① 메시 267,470 요소


@needs_gmsh
def test_defeature_failure_reverted(tmp_path, monkeypatch):
    """C2-D-37 구멍 메움이 형상을 바꾼 뒤 실패(DEFEATURE_SKIPPED)하면 재가져오기로 되돌림 → 연결 1성분 메시, DEFEATURE_REVERTED."""
    p = scmp.dimple_plate_step(tmp_path / "f.step", [], Lx=60.0, Lz=40.0)
    real = mg.defeature

    def broken(gmsh, df, h, skip_keys=()):
        out = real(gmsh, df, h, skip_keys)
        s0 = gmsh.model.occ.getEntities(2)[0]
        gmsh.model.occ.translate([s0], 0.0, 0.0, 50.0)                       # 형상을 바꾼 뒤
        gmsh.model.occ.synchronize()
        out["warnings"].append("DEFEATURE_SKIPPED: 작은 형상 처리 실패 — Curve loop is not closed")
        return out
    monkeypatch.setattr(mg, "defeature", broken)
    m, meta = mg.mesh_file(p, 3.0, _ccfg(occ_fix_small=0, fallback={"enabled": False}), tsc.PROPS)
    assert meta["defeature"]["reverted"] and any(w.startswith("DEFEATURE_REVERTED") for w in meta["defeature"]["warnings"])
    assert float(m["x0"][:, 2].max()) < 1.0 and not meta["errors"]


@needs_gmsh
def test_all_shapes_failed_fails_step(tmp_path):
    """C2-D-41 비교 형상이 모두 메시 실패 → BD_MESH0 실패(COMPARE_NO_SHAPES), min_ready_shapes 0 → READY + 맨 앞 경고
    COMPARE_SHAPES_FAILED(실패 형상 목록)."""
    p1 = smany.many_dimple_step(tmp_path / "up" / "u1" / "m.step", nx=3, ny=2, Lx=60.0, Ly=40.0, panels=(1, 1),
                                holes_every=0)
    doe = _doe(tmp_path, "NF", p1, mesh={"cad_relaxed": {"enabled": False}}, mesh_mode="cad")
    out = tmp_path / "_doe" / "NF"
    with pytest.raises(EslError) as ei:
        tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    assert ei.value.code == "COMPARE_NO_SHAPES"
    assert tsc._shape(out, "d001")["status"] == "FAILED_MESH"                      # compare.json 은 남음
    doe["cfg"]["bead_doe"]["compare"]["min_ready_shapes"] = 0
    out2 = tmp_path / "_doe" / "NF2"
    r, _spec = tsc._run(out2, doe, stages=("bd_input", "bd_mesh0"))
    assert r["bd_mesh0"]["warnings"][0].startswith("COMPARE_SHAPES_FAILED: 비교 형상 1/1개") and "d001" in r["bd_mesh0"]["warnings"][0]


# ---------------------------------------------------------------- v0.17.4 Verifier 수정
def test_nofix_ambiguous_strict_no_grown_pick():
    """엄격 대응 후보가 2개 이상(같은 bbox 구 2개, 63.50·63.70 mm² ↔ 63.55)이면 모호 → 고르지 않음. 키운 면 찾기
    (_pick_grown_face)는 엄격 후보 0개일 때만 — 혼자 돌리면 63.50 을 골랐을 것."""
    key = (29.23, 441.0, -4.25, 33.73, 445.5, 0.25)
    cands = [(21, "Sphere", 63.50, key), (22, "Sphere", 63.70, key)]
    assert mg._pick_grown_face(cands, key, "Sphere", 63.55, 1e-2, 1000.0) == 21     # 예전 경로의 잘못된 고르기
    f, why = mg._pick_nofix_face(cands, key, "Sphere", 63.55, 1e-2, 1e-2, 1000.0)
    assert f is None and "후보 2개" in why and "넓이가 줄어든" not in why
    one = [(21, "Sphere", 63.50, key)]
    assert mg._pick_nofix_face(one, key, "Sphere", 63.55, 1e-2, 1e-2, 1000.0) == (21, None)
    grown = [(11, "Sphere", 0.08, (31.0, 443.0, -2.1, 31.6, 443.5, -1.9))]                # 엄격 0개 → 키운 면
    assert mg._pick_nofix_face(grown, key, "Sphere", 63.53, 1e-2, 1e-2, 1000.0) == (11, None)
    f, why = mg._pick_nofix_face(grown, key, "Sphere", 63.53, 1e-2, 1e-2, 0.0)          # grow 끔
    assert f is None and "후보 0개" in why


def test_relaxed_fidelity_reference_freeform_angle(monkeypatch):
    """cad_relaxed 충실도 기준 삼각화 = compare.freeform.angular_deflection_deg(20°), 선 편차는 remesh 절대값 0.05 mm 그대로
    (실측 102 면·구 96: 5° 247,500 삼각형 → 20° 38,988, cad_relaxed 23.2 s → 12.1 s)."""
    import numpy as np

    from esl.doe import mesh_remesh as mrm
    from esl.geom import defeature as gdf
    seen = []

    class _G:
        class option:
            setNumber = staticmethod(lambda *a: None)
        initialize = staticmethod(lambda *a, **k: None)
        finalize = staticmethod(lambda: None)

    def ref(_g, _src, _mc, rc):
        seen.append(dict(rc))
        return np.zeros((3, 3)), np.zeros((1, 3), dtype=int)
    monkeypatch.setattr(gdf, "reference_tris", ref)
    monkeypatch.setattr(mrm, "fidelity", lambda S_X, S_T, mesh, h, rc: {"hausdorff_mm": 0.1, "fail_mm": 1.5,
                                                                         "angular_deflection_deg": rc["angular_deflection_deg"]})
    cfg = _ccfg()
    mg._relaxed_fidelity(_G, "x.step", cfg["mesh"], {}, 3.0, cfg)
    assert seen[-1]["angular_deflection_deg"] == 20.0 and seen[-1]["linear_deflection_mm"] == 0.05
    assert DEFAULTS["compare"]["remesh"]["angular_deflection_deg"] == 5.0                # remesh 자체는 그대로
    cfg2 = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "compare": {"mesh": {"size_mm": 3.0},
                                                                              "freeform": {"angular_deflection_deg": 12.0}}}}))
    mg._relaxed_fidelity(_G, "x.step", cfg2["mesh"], {}, 3.0, cfg2)
    assert seen[-1]["angular_deflection_deg"] == 12.0 and seen[-1]["linear_deflection_mm"] == 0.05


_WATCH = """
import os, sys, time
sys.path[:0] = [{root!r}]
from esl.doe import mesh_gmsh as mg
out = {out!r}
mg._arm_deadline({{"child_timeout_s": 0.3, "out_dir": out}}, os.path.join(out, "mesh_error.json"))
if {mark!r}:
    mg.mark_success_write()
time.sleep(1.5)
print("alive")
"""


@pytest.mark.parametrize("mark", [True, False])
def test_watchdog_quiet_after_success_write(tmp_path, mark):
    """감시 타이머: 성공 결과 쓰기 시작(mark_success_write) 뒤에는 mesh_error.json 을 쓰지 않고 자식을 끝내지 않음.
    표시가 없으면(대조) 예전처럼 기록 + 종료코드 3."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run([sys.executable, "-c", _WATCH.format(root=root, out=str(tmp_path), mark=mark)],
                       capture_output=True, text=True, timeout=60, check=False)
    err = tmp_path / "mesh_error.json"
    if mark:
        assert r.returncode == 0 and "alive" in r.stdout and not err.exists()
    else:
        assert r.returncode == 3 and "alive" not in r.stdout and err.exists()
