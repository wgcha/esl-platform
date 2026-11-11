"""v0.18.0 STEP_GRAPH API(계약 esl_step_graph.md §3.1·§4, V-SG-6).

- 설정: select.step_graph(pydantic 검사 — 거울은 test_doe_select_api.test_select_defaults_mirror_contract), GET /doe/settings
  scenarios.select_step = select 가능 ∧ gmsh ready(paicad 무관), select.step_graph{tria_policy, …}.
- 입력: select_base step = STEP 필수(auto·manual), props·inch·mesh_mode·mesh_refine 허용, mesh_upload_id·part_title·mesh_size_mm
  422, gmsh 없음 503, 다른 select 기준의 mesh_mode 는 여전히 422(MESH_MODE_COMPARE_ONLY). 새 스터디 = schema 2, 스냅샷
  select_base·mesh_mode·mesh_ladder. legacy scenario step 생성 계속 허용.
- 복제(step 기준 그대로·schema 1 이면 422·gmsh 없음 503), GET select/auto(step 기준이면 manual 도 seed), 준비 요약 통과.
"""

from __future__ import annotations

import json

import pytest
from doe_support import api, record_paicad, study_dir, update_study, upload_step
from sqlalchemy import text
from test_doe_select_api import _fake_core, _job, code, sbody, settings_dict, simulate_select_prep, world  # noqa: F401
from test_doe_select_graph_api import _fake_graph, write_graph  # noqa: F401


def _sg(world, uid, **kw):
    return sbody(world, select_base="step", step_upload_id=uid, **kw)


def _create(client, body):
    r = api(client, "POST", "/doe/studies", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ================================================================ 설정
def test_settings_select_step_and_step_graph_block(client, world, engine):
    from esl_platform.api.services import doe as svc

    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["select_step"] is True
    assert s["select"]["step_graph"] == {"tria_policy": "warn", "tria_warn_frac": 0.5, "max_elems": 600000, "size_mm": 3.0,
                                         "fixed_transfer": {"enabled": True, "mode": "auto"}, "region": {"mode": "auto"}}
    record_paicad(engine, ready=False, reason="PAICAD_NOT_FOUND")       # paicad 무관(SG-D-18)
    svc.reset_status_cache()
    s = api(client, "GET", "/doe/settings").json()
    assert s["enabled"] is False and s["scenarios"]["select_step"] is True
    record_paicad(engine, gmsh=False)                                   # gmsh 없음 = 막힘
    svc.reset_status_cache()
    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["select_step"] is False and s["scenarios"]["select"] is True
    svc.reset_status_cache()


@pytest.mark.parametrize("bad", [
    {"max_elems": 0}, {"max_elems": 2_000_001}, {"timeout_s": 0}, {"tria_warn_frac": 0}, {"tria_warn_frac": 1.01},
    {"tria_policy": "stop"}, {"fixed_transfer": {"mode": "near"}}, {"fixed_transfer": {"origin_tol_mm": 0}},
    {"fixed_transfer": {"axis_tol_deg": -1}}, {"fixed_transfer": {"tol_mm": 0}}, {"fixed_transfer": {"snap_mm": -2}},
    {"region": {"mode": "biggest"}}, {"region": {"pad_mm": 0}}, {"region": {"min_frac": 0}}, {"region": {"min_frac": 1.5}},
    {"unknown": 1}, {"fixed_transfer": {"unknown": 1}}])
def test_step_graph_cfg_rejects(bad):
    from esl_platform.core.config import BeadDoeSelectStepGraphCfg

    with pytest.raises(ValueError):
        BeadDoeSelectStepGraphCfg.model_validate(bad)


def test_step_graph_cfg_accepts_nulls_and_block():
    from esl_platform.core.config import BeadDoeSelectCfg

    c = BeadDoeSelectCfg.model_validate({"step_graph": {"tria_policy": "block", "fixed_transfer": {"mode": "hole",
                                                                                                 "tol_mm": 1.5},
                                                         "region": {"mode": "all", "pad_mm": 4}}})
    assert c.step_graph.tria_policy == "block" and c.step_graph.fixed_transfer.tol_mm == 1.5
    assert c.step_graph.fixed_transfer.snap_mm is None and c.step_graph.region.mode == "all"


# ================================================================ 입력 검사(SG-D-1~4)
def test_check_inputs_step_base(client, world, engine):
    uid = upload_step(client)
    r = api(client, "POST", "/doe/check-inputs", json=_sg(world, uid))         # manual + STEP 허용(기준 메시 원천)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["ok"] is True and o["step"]["file_name"] == "chassis_mid.step" and len(o["step"]["sha256"]) == 64
    assert o["base"] is None and o["mesh"] is None and o["size"] is None
    assert set(o["props_default"]) == {"t", "E", "nu"} and o["mesh_size_default_mm"] == 3.0
    assert o["mesh_mode"] == "auto" and o["remesh_available"] is True      # 설정 compare.mesh.mode
    assert o["step_graph"]["size_mm"] == 3.0 and o["step_graph"]["tria_policy"] == "warn"
    assert "defeature" in o["step_graph"]["ladder"]
    r = api(client, "POST", "/doe/check-inputs", json=_sg(world, uid, bead_source="auto", mesh_mode="cad",
                                                          mesh_refine=False))
    assert r.status_code == 200 and r.json()["mesh_mode"] == "cad"
    assert not [x for x in r.json()["step_graph"]["ladder"] if x.startswith("refine_")]


@pytest.mark.parametrize("extra, want", [
    ({"step_upload_id": None}, "INVALID_PARAMS"),
    ({"mesh_upload_id": "u-x"}, "INVALID_PARAMS"),
    ({"part_title": "chassis rear"}, "INVALID_PARAMS"),
    ({"mesh_size_mm": 3.0}, "INVALID_PARAMS"),
    ({"mesh_mode": "bogus"}, None),                     # 스키마 422(pydantic)
])
def test_check_inputs_step_base_rejects(client, world, engine, extra, want):
    uid = upload_step(client)
    b = {k: v for k, v in {**_sg(world, uid), **extra}.items() if v is not None}
    r = api(client, "POST", "/doe/studies", json=b)
    assert r.status_code == 422, r.text
    if want:
        assert code(r) == want


def test_mesh_mode_still_compare_only_for_other_select(client, world, engine):
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, mesh_mode="cad"))
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"


def test_step_base_requires_gmsh_and_remesh_rules(client, world, engine):
    from esl_platform.api.services import doe as svc

    uid = upload_step(client)
    record_paicad(engine, remesh=False)                 # 재메시 불가: freeform 강제 = 422, auto = 경고 1회
    svc.reset_status_cache()
    r = api(client, "POST", "/doe/check-inputs", json=_sg(world, uid, mesh_mode="freeform"))
    assert r.status_code == 422 and code(r) == "REMESH_UNAVAILABLE"
    r = api(client, "POST", "/doe/check-inputs", json=_sg(world, uid, mesh_mode="auto"))
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["REMESH_UNAVAILABLE"]
    record_paicad(engine, gmsh=False)
    svc.reset_status_cache()
    r = api(client, "POST", "/doe/check-inputs", json=_sg(world, uid))
    assert r.status_code == 503 and code(r) == "GMSH_UNAVAILABLE"
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world))         # 다른 select 는 gmsh 무관
    assert r.status_code == 200
    svc.reset_status_cache()


# ================================================================ 생성 · 스냅샷 · legacy
def test_create_step_base_inputs_and_snapshot(client, world, engine):
    uid = upload_step(client)
    s = _create(client, _sg(world, uid, inch=55, props={"t": 1.2, "E": 70000.0, "nu": 0.33}, mesh_mode="auto"))
    i = s["inputs"]
    assert s["scenario"] == "select" and i["select_base"] == "step" and i["select_schema"] == 2
    assert i["bead_source"] == "manual" and i["step"]["upload_id"] == uid and i["inch"] == 55
    assert i["props"] == {"t": 1.2, "E": 70000.0, "nu": 0.33} and i["mesh_mode"] == "auto" and i["mesh_refine"] is None
    assert "mesh_size_mm" not in i and i["mesh"] is None and i["part_title"] is None
    assert "STEP" in s["title"] and "chassis_mid.step" in s["title"]
    d = _job(engine, s["job"]["id"])["params"]["doe"]
    assert d["select_base"] == "step" and d["select_schema"] == 2 and d["mesh_mode"] == "auto"
    assert d["mesh_ladder"] and "defeature" in d["mesh_ladder"] and d["step"]["path"].endswith(".step")
    assert d["props"] == i["props"] and "mesh_size_mm" not in d and "base" not in d and "mesh" not in d
    # props 생략 = ③ 기본값(첫 ESL 메시), auto 도 같은 경로
    a = _create(client, _sg(world, upload_step(client), bead_source="auto"))
    assert a["inputs"]["bead_source"] == "auto" and set(a["inputs"]["props"]) == {"t", "E", "nu"}
    assert a["inputs"]["mesh_mode"] == "auto"           # 생략 = 설정 compare.mesh.mode


def test_legacy_scenario_step_still_accepted(client, world, engine):
    uid = upload_step(client)
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "step", "entry_ids": [world["a"]],
                                                  "step_upload_id": uid})
    assert r.status_code == 201, r.text
    assert r.json()["scenario"] == "step" and "select_base" not in r.json()["inputs"]
    c = api(client, "POST", f"/doe/studies/{r.json()['id']}/clone", json={})
    assert c.status_code == 201 and c.json()["scenario"] == "step"


# ================================================================ 복제
def test_clone_step_base(client, world, engine, esl_root):
    from esl_platform.api.services import doe as svc

    s = _create(client, _sg(world, upload_step(client), mesh_mode="auto"))
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert c.status_code == 201, c.text
    assert c.json()["inputs"]["select_base"] == "step" and c.json()["inputs"]["select_schema"] == 2
    d = _job(engine, c.json()["job"]["id"])["params"]["doe"]
    assert d["select_base"] == "step" and d["mesh_mode"] == "auto" and d["step"]["path"].endswith(".step")
    with engine.begin() as cn:                          # SG-D-2: step 기준인데 schema 1 = 422
        cn.execute(text("UPDATE bead_does SET inputs = inputs - 'select_schema' WHERE id=:i"), {"i": s["id"]})
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    record_paicad(engine, gmsh=False)
    svc.reset_status_cache()
    r = api(client, "POST", f"/doe/studies/{c.json()['id']}/clone", json={})
    assert r.status_code == 503 and code(r) == "GMSH_UNAVAILABLE"
    svc.reset_status_cache()


# ================================================================ GET select/auto · 준비 요약
def _seed(esl_root, sid, sel, source):
    d = study_dir(esl_root, sid) / "prep" / "select"
    d.mkdir(parents=True, exist_ok=True)
    (d / "auto_selection.json").write_text(json.dumps({
        "schema": "esl/doe_auto_selection/2", "source": source, "selection": sel, "sha256": "e" * 64,
        "hints": [], "warnings": [{"code": "FIXED_XFER_UNMATCHED", "label": "c3", "d_mm": 14.2}]}), encoding="utf-8")


def test_auto_endpoint_manual_step_seed(client, world, engine, esl_root):
    s = _create(client, _sg(world, upload_step(client)))
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"], schema=2)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == 404 and code(r) == "AUTO_NOT_AVAILABLE"        # seed 파일 없음
    gsha = write_graph(esl_root, s["id"])
    seed = {"schema_version": 2, "graph": {"sha256": gsha, "rules": 1}, "beads": [],
            "fixed_user": {"q": [[1, 4]], "t": []}}
    _seed(esl_root, s["id"], seed, "fixed_transfer")
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto", "tok-general")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["selection"] == seed and a["source"] == "fixed_transfer" and isinstance(a["sha256"], str)
    assert [w["code"] for w in a["warnings"]] == ["FIXED_XFER_UNMATCHED"]
    # manual case 기준 = 그대로 404(① 불변)
    m = _create(client, sbody(world))
    simulate_select_prep(engine, esl_root, m["id"], m["job"]["id"], world["mesh"], schema=2)
    _seed(esl_root, m["id"], seed, "graph")
    assert code(api(client, "GET", f"/doe/studies/{m['id']}/select/auto")) == "AUTO_NOT_AVAILABLE"


def test_prep_summary_step_passthrough(client, world, engine, esl_root):
    s = _create(client, _sg(world, upload_step(client)))
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"], schema=2)
    with engine.connect() as c:
        prep = dict(c.execute(text("SELECT prep FROM bead_does WHERE id=:i"), {"i": s["id"]}).scalar_one())
    mesh = {"method": "freeform", "n_nodes": 10, "n_elems": 9, "tri_frac": 0.6, "stage_times": {"cad": 1.0}}
    fixed = {"source": "a_transfer", "n": 8, "xfer": {"method": "ab_hole_snap", "matched": 3, "unmatched": 1,
                                                       "frame_ok": False}}
    region = {"mode": "auto", "n_in": 7, "n_out": 2}
    prep.update(select_base="step", mesh=mesh, fixed=fixed, region=region,
                warnings=[{"code": "STEP_GRAPH_TRIA", "message": "삼각형 메시"}])
    update_study(engine, s["id"], prep=prep)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    p = g["prep"]
    assert p["select_base"] == "step" and p["mesh"] == mesh and p["fixed"] == fixed and p["region"] == region
    assert [w["code"] for w in p["warnings"]] == ["STEP_GRAPH_TRIA"]
    # ①(case) 스터디는 mesh·region 을 내지 않음(요약 불변)
    m = _create(client, sbody(world))
    simulate_select_prep(engine, esl_root, m["id"], m["job"]["id"], world["mesh"], schema=2)
    with engine.connect() as c:
        pm = dict(c.execute(text("SELECT prep FROM bead_does WHERE id=:i"), {"i": m["id"]}).scalar_one())
    update_study(engine, m["id"], prep={**pm, "mesh": mesh, "region": region})
    p = api(client, "GET", f"/doe/studies/{m['id']}").json()["prep"]
    assert "mesh" not in p and "region" not in p and "select_base" not in p


# ================================================================ 통합 v0.18.0 §12: plan-view 보강(fixed[].src·region_ab)
def test_step_plan_extras_fixed_src_and_region(tmp_path, monkeypatch):
    """select_base step plan-view: fixed[].src = fixed_transfer.json node_id 의 노드면 "a_transfer", 아니면 "user"; region_ab =
    base_mesh.npz region(요소 bool)의 바깥 고리(구멍 고리 제외, (a,b) mm). region 없음 = None. DoePlanOut 이 두 필드를 지킴."""
    import numpy as np
    from esl.opt.keepout import project_ab
    from esl_platform.api.schemas import DoePlanOut
    from esl_platform.api.services import doe_select
    from opt_support import plate

    m = plate()                                       # 12 × 8 사각형, x 0..300 · z 0..200
    frame = {"origin": [0.0, 0.0, 0.0], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 0.0, 1.0]}
    pd = tmp_path / "prep"
    (pd / "select").mkdir(parents=True)
    monkeypatch.setattr(doe_select, "_prep_dir", lambda ctx, s: str(pd))
    c = {"limits": {"max_json_mb": 64}}
    moved = [int(m["node_id"][0]), int(m["node_id"][10])]
    (pd / "select" / "fixed_transfer.json").write_text(json.dumps({"schema": "esl/doe_fixed_transfer/2",
                                                                   "method": "xyz_nearest", "node_id": moved}))
    fx = project_ab(frame, m["x0"][[0, 10, 20]]).round(3).tolist()
    region = np.zeros(m["conn"].shape[0], bool)
    region[: 6 * 8] = True                            # x 0..150 열(왼쪽 절반)
    region[2 * 8 + 3] = False                         # 영역 안 구멍 1개(고리는 바깥만 남아야 함)
    np.savez(pd / "base_mesh.npz", region=region)
    p = {"fixed": [{"a": a, "b": b} for a, b in fx]}
    doe_select._step_plan_extras(None, {}, c, {"mesh": m, "frame": frame}, p)
    assert [f["src"] for f in p["fixed"]] == ["a_transfer", "a_transfer", "user"]
    assert len(p["region_ab"]) == 1
    ring = np.asarray(p["region_ab"][0])
    assert ring[:, 0].min() == 0.0 and ring[:, 0].max() == 150.0 and ring[:, 1].min() == 0.0 and ring[:, 1].max() == 200.0
    out = DoePlanOut.model_validate({"frame": {"a_range": [0, 300], "b_range": [0, 200]}, "outline": [], "holes": [],
                                     "elems": {"n_total": 0, "decimated": False, "points": []}, **p}).model_dump()
    assert out["region_ab"] == p["region_ab"] and out["fixed"][0]["src"] == "a_transfer"
    # region 키 없음(영역 = 전체)·이전 파일 없음 → region_ab None, 모든 고정 = user
    np.savez(pd / "base_mesh.npz", other=np.zeros(1))
    (pd / "select" / "fixed_transfer.json").unlink()
    p = {"fixed": [{"a": a, "b": b} for a, b in fx]}
    doe_select._step_plan_extras(None, {}, c, {"mesh": m, "frame": frame}, p)
    assert p["region_ab"] is None and {f["src"] for f in p["fixed"]} == {"user"}
