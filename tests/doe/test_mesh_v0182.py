"""v0.18.2 이슈 #63(2026-11-12 진단) ④/③ 메시 사다리 — 계약 esl_compare_mesh_options.md C2-D-44·45, V-C2-42~46.

- cad_relaxed 분리(isolate): cad 자식은 cad_relaxed 를 돌리지 않고(deferred) 부모가 자기 하위 프로세스·cad_relaxed.timeout_s 로
- 자식 감시 타이머가 cad_relaxed 후처리(충실도)를 끊은 경우: '0.0 s 실패' 대신 시간 초과·실제 초 기록 + 부모 재실행
- freeform OCC 면별 이산 면(면 분류 없음): 비다양체 모서리(한 모서리를 세 면이 공유) 형상
gmsh 가 없으면 skip."""
import json
import math
import os
import subprocess
import sys

import pytest

import synth_many as smany
import test_mesh_relaxed_v0174 as trx
import test_step_compare as tsc
from esl.doe import DEFAULTS
from esl.doe import mesh_gmsh as mg
from esl.doe import mesh_refine as mr
from esl.doe import scenario as sc
from esl.doe import settings
from esl.doe import stages as stg
from esl.errors import EslError

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- 설정·순수 함수(V-C2-42)
def test_defaults_relaxed_isolate_and_freeform_surfaces():
    """새 키는 DEFAULTS 에(백엔드·yaml 거울은 test_config 계열이 대조): isolate·timeout_s·fidelity_samples, freeform.surfaces."""
    rx = DEFAULTS["compare"]["mesh"]["cad_relaxed"]
    assert rx["isolate"] is True and rx["timeout_s"] == 900.0 and rx["fidelity_samples"] == 20000
    assert DEFAULTS["compare"]["freeform"]["surfaces"] == "occ_faces"
    c = sc.compare_cfg(settings({"bead_doe": {"enabled": True}}))
    d = stg._relaxed_defer_cfg(c)
    assert d["mesh"]["cad_relaxed"]["defer"] is True and "defer" not in c["mesh"]["cad_relaxed"]     # 사본만
    off = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "compare": {"mesh": {"cad_relaxed": {"isolate": False}}}}}))
    assert stg._relaxed_defer_cfg(off) is off


def test_interrupted_relaxed_attempt_not_zero_seconds():
    """cad 자식 안 cad_relaxed 가 감시 타이머에 끊긴 기록(tried·interrupted·seconds) → cad_relaxed 시간 초과 실패 + 실제 초,
    cad 행 초 = 전체 − cad_relaxed 초(시간 초과 표시는 cad_relaxed 에만). seconds 가 없는 v0.18.1 기록(tried 만)이면
    전체 − 첫 세션 초. 끝까지 간 실패(error·seconds)는 예전 그대로."""
    r0 = {"code": "MESH_FAILED", "message": "gmsh 메싱 실패: 자식 제한 시간 510 s 초과(시간 초과)"}
    pm = {"cad_relaxed": {"tried": True, "ok": False, "overrides": {}, "interrupted": True, "seconds": 290.4,
                          "cad_seconds": 219.0}}
    a = stg._relaxed_cad_attempts(pm, r0, 3.0, 515.9)
    assert stg._relaxed_state(pm) == "interrupted"
    assert [(x["stage"], x["seconds"], bool(x.get("timed_out"))) for x in a] == [("cad", 225.5, False),
                                                                                 ("cad_relaxed", 290.4, True)]
    txt = mr.stage_times_text(mr.stage_times(a))
    assert "cad_relaxed 실패(시간 초과) 290.4 s" in txt and "0.0 s" not in txt, txt
    old = {"cad_relaxed": {"tried": True, "ok": False, "overrides": {}, "cad_seconds": 219.0}}   # v0.18.1 형식(끊김)
    a = stg._relaxed_cad_attempts(old, r0, 3.0, 515.9)
    assert stg._relaxed_state(old) == "interrupted" and a[1]["seconds"] == pytest.approx(296.9) and a[1]["timed_out"]
    done = {"cad_relaxed": {"tried": True, "ok": False, "error": "품질 오류", "seconds": 12.5}}
    a = stg._relaxed_cad_attempts(done, r0, 3.0, 100.0)
    assert stg._relaxed_state(done) == "done" and a[1]["seconds"] == 12.5 and "timed_out" not in a[1]
    assert stg._relaxed_state({"cad_relaxed": {"deferred": True}}) == "deferred" and stg._relaxed_state({}) is None


_WATCH_RX = """
import json, os, sys, time
sys.path[:0] = [{root!r}]
from esl.doe import mesh_gmsh as mg
out = {out!r}
mg._RUN.update(track=True, relaxed={{"tried": True, "ok": False, "overrides": {{"occ_fix_small": 0}}}},
               relaxed_t1=time.monotonic(), relaxed_cad_s=1.25)
mg._arm_deadline({{"child_timeout_s": 0.4, "out_dir": out}}, os.path.join(out, "mesh_error.json"))
time.sleep(5)
print("alive")
"""


def test_watchdog_records_interrupted_relaxed(tmp_path):
    """감시 타이머가 cad_relaxed 후처리 중 자식을 끝냄(모의): mesh_error.json cad_relaxed = interrupted·seconds(끊길 때까지)·
    cad_seconds(첫 세션) + timed_out — 부모가 '0.0 s' 대신 시간 초과로 적고 다시 돌릴 근거."""
    r = subprocess.run([sys.executable, "-c", _WATCH_RX.format(root=ROOT, out=str(tmp_path))], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 3 and "alive" not in r.stdout
    e = json.loads((tmp_path / "mesh_error.json").read_text(encoding="utf-8"))
    rx = e["cad_relaxed"]
    assert e["timed_out"] and rx["interrupted"] and rx["cad_seconds"] == 1.25 and 0.3 <= rx["seconds"] < 5.0, e


# ---------------------------------------------------------------- 사다리(워커 단계) V-C2-43·44
@needs_gmsh
def test_pipeline_relaxed_isolated_record(tmp_path):
    """isolate(기본): cad 자식 기록 = cad_relaxed.deferred(첫 실패 면) → 부모 cad_relaxed 성공(자기 시도 폴더) — 행 cad_relaxed
    isolated·after_timeout false, mesh.json cad_relaxed 에 자식 기록(ok·overrides·first_error·face) 유지, stage_times cad → cad_relaxed."""
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step", nx=3, ny=2)
    out = tmp_path / "_doe" / "RI"
    _r, _spec = tsc._run(out, trx._doe(tmp_path, "RI", p1), stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_path"] == "cad_relaxed" and s["cad_relaxed"]["isolated"], s
    assert s["cad_relaxed"]["after_timeout"] is False
    assert [(x["stage"], x["outcome"]) for x in s["stage_times"]] == [("cad", "FAILED_MESH"), ("cad_relaxed", "READY")]
    err = json.loads((out / "prep" / "shapes" / "d001" / "mesh" / "attempt_logs" / "cad.mesh_error.json").read_text("utf-8"))
    assert err["cad_relaxed"]["deferred"] and err["cad_relaxed"]["face"]["type"] == "Sphere"
    mj = json.loads((out / "prep" / "shapes" / "d001" / "mesh" / "mesh.json").read_text("utf-8"))
    assert mj["cad_relaxed"]["ok"] and mj["cad_relaxed"]["face"]["type"] == "Sphere" and mj["cad_relaxed"]["first_error"]


@needs_gmsh
def test_mode_cad_runs_parent_relaxed(tmp_path):
    """mode cad(사다리 없음)도 부모 cad_relaxed 1회 — v0.18.1 의 자식 안 성공과 같은 결과(READY, mesh_path cad_relaxed)."""
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step", nx=3, ny=2)
    out = tmp_path / "_doe" / "MC"
    _r, _spec = tsc._run(out, trx._doe(tmp_path, "MC", p1, mesh_mode="cad"), stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "cad" and s["mesh_path"] == "cad_relaxed", s
    assert [x["stage"] for x in s["attempts"]] == ["cad", "cad_relaxed"]


@needs_gmsh
def test_watchdog_cuts_inchild_relaxed_parent_reruns(tmp_path, monkeypatch):
    """isolate false(v0.18.1 경로) + 자식 안 cad_relaxed 충실도에서 멈춤(시험 주입 relaxed_slow): 감시 타이머가 끊음 →
    cad_relaxed 행 = 시간 초과 실패(초 > 0, '0.0 s' 아님) → 부모가 자기 세션으로 다시(direct — 주입 없음) 성공."""
    monkeypatch.setenv(mg.TEST_FAIL_ENV, "relaxed_slow")
    p1 = smany.many_dimple_solid_step(tmp_path / "up" / "u1" / "s.step", nx=3, ny=2)
    doe = trx._doe(tmp_path, "WS", p1, base_mesh={"timeout_s": 40}, mesh={"child_margin_s": 4.0,
                                                                          "cad_relaxed": {"isolate": False}})
    out = tmp_path / "_doe" / "WS"
    _r, _spec = tsc._run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = tsc._shape(out, "d001")
    st = [(a["stage"], a["status"], bool(a.get("timed_out"))) for a in s["attempts"]]
    assert st[:3] == [("cad", "FAILED_MESH", False), ("cad_relaxed", "FAILED_MESH", True), ("cad_relaxed", "READY", False)], st
    assert s["attempts"][1]["seconds"] > 1.0 and s["attempts"][1]["interrupted"]
    assert s["status"] == "READY" and s["mesh_path"] == "cad_relaxed"
    txt = mr.stage_times_text(s["stage_times"])
    assert "cad_relaxed 성공" in txt and "(시간 초과)" not in txt and "0.0 s" not in txt, txt
    assert s["stage_times"][1]["tries"] == 2


# ---------------------------------------------------------------- freeform 면별 이산 면 V-C2-45
def _arch_step(path, rise: float = 5.0) -> str:
    """판(200 × 150) 위에 얕은 원통 아치(현 80, 높이 rise)를 fragment — 아치 양끝 모서리를 판 두 조각 + 아치(세 면)가 공유(비다양체)."""
    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        o = gmsh.model.occ
        p = o.addRectangle(0, 0, 0, 200, 150)
        c = 80.0
        R = ((c / 2) ** 2 + rise ** 2) / (2 * rise)
        arc = o.addCircleArc(o.addPoint(60, 0, 0), o.addPoint(100, 0, rise - R), o.addPoint(140, 0, 0))
        s = [x for x in o.extrude([(1, arc)], 0, 150, 0) if x[0] == 2]
        o.fragment([(2, p)], s)
        o.synchronize()
        os.makedirs(os.path.dirname(str(path)), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


@needs_gmsh
def test_freeform_nonmanifold_occ_faces(tmp_path, monkeypatch):
    """비다양체 모서리(세 면 공유) 형상: 면 분류가 'one edge is incident to 3 triangles' 로 실패해도(모의 — 현장 문구)
    occ_faces 는 classifySurfaces 를 부르지 않고 OCC 면 4개 = 이산 면 4개, 공유 곡선 = OCC 모서리, 한 성분 메시·품질 오류 없음.
    surfaces classify(v0.18.1) = REMESH_CLASSIFY_FAILED."""
    import gmsh

    from esl.doe import mesh_remesh as mrm
    src = _arch_step(tmp_path / "arch.step")

    def bad(*_a, **_k):
        raise Exception("Wrong topology of triangulation for parametrization: one edge is incident to 3 triangles")
    monkeypatch.setattr(gmsh.model.mesh, "classifySurfaces", bad)
    base = {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}
    cfg = sc.compare_cfg(settings(base))
    _m, meta = mrm.remesh_file(src, 3.0, cfg, tsc.PROPS, freeform=True)
    r = meta["remesh"]
    assert r["surfaces"] == "occ_faces" and r["topology"] == "occ_edges" and r["n_patches"] == 4, r
    assert not meta["errors"] and meta["fidelity"]["hausdorff_mm"] <= meta["fidelity"]["fail_mm"]
    ff = [w for w in meta["warnings"] if w["code"] == "MESH_FREEFORM"]
    assert len(ff) == 1 and "CAD 면 경계를 따르는" in ff[0]["message"]
    old = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                                "compare": {"freeform": {"surfaces": "classify"}}}}))
    with pytest.raises(EslError) as ei:
        mrm.remesh_file(src, 3.0, old, tsc.PROPS, freeform=True)
    assert ei.value.code == "REMESH_CLASSIFY_FAILED" and "3 triangles" in ei.value.message


@needs_gmsh
def test_face_model_shared_curve_three_faces(tmp_path):
    """face_model: 아치 끝 OCC 모서리 곡선이 세 면의 경계 목록에 모두 있음(공유 경계 = OCC 모서리), 이음선 없음, 노드 = merge_nodes
    결과(S_X)와 같은 순서."""
    import gmsh
    import numpy as np

    from esl.doe import mesh_remesh as mrm
    src = _arch_step(tmp_path / "arch.step")
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        gmsh.model.occ.importShapes(src)
        gmsh.model.occ.synchronize()
        rc = {"linear_deflection_mm": 0.05, "angular_deflection_deg": 20.0, "stl_max_tris": 10 ** 6}
        X0, T0 = mrm.occ_triangulate(gmsh, rc)
        parts = mrm.occ_parts(gmsh)
    finally:
        gmsh.finalize()
    fm = mrm.face_model(parts, X0, 0.001)
    S_X, _S_T, _n = mrm.merge_nodes(X0, T0, 0.001)
    assert fm["topology"] == "occ_edges" and np.array_equal(fm["X"], S_X)
    by_curve: dict = {}
    for f, cs in fm["fcurves"].items():
        for e in cs:
            by_curve.setdefault(e, set()).add(f)
    assert sorted(len(v) for v in by_curve.values()).count(3) == 2, by_curve      # 아치 양끝 = 세 면


def test_tria_timeout_default_unchanged():
    """C2-D-46 tria 상한 검토: 기본 300 s 유지(대형 모델 tria 는 단계 몫이 아니라 남은 예산으로 제한 — 계약 근거)."""
    assert DEFAULTS["compare"]["tria"]["timeout_s"] == 300
    assert math.isclose(DEFAULTS["compare"]["refine"]["stage_share"]["tria"], 0.15)
