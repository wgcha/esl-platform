"""v0.14.0 ④ 형상 직접 비교 API(계약 esl_step_compare.md §3·§6·SC-D-1·3, V-SC-3·4): 활성(paicad 무관·gmsh 필요·compare 꺼짐),
입력 검사 오류 표, 한 업로드 여러 STEP(rel), 기준 미지정(Case 메시 + COMPARE_REF_CASE_MESH), 형상 id 규칙, matrix·preview 등 409
SCENARIO_UNSUPPORTED, run 이 matrix_sha256 없이 동작(PREP_NOT_READY·ALREADY_RUN), 결과 shape·민감도 생략, per-esl 이름, 복제."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from doe_support import (
    R,
    W,
    api,
    doe_settings_dict,
    finish_job,
    record_paicad,
    study_dir,
    update_study,
)
from esl_test_support import API
from opt_support import make_case, plate, seed_opt_entry, upload_files
from sqlalchemy import text


def step_bytes(tag: str) -> bytes:
    return (f"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('{tag}'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\n"
            "END-ISO-10303-21;\n").encode()


@pytest.fixture()
def settings_dict(tmp_path):
    return doe_settings_dict(tmp_path)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from esl_platform.api.services import doe as svc

    svc.reset_status_cache()
    yield
    svc.reset_status_cache()


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    a = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    b = seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2)
    record_paicad(engine)
    return {"a": a, "b": b}


def multi_upload(client, n: int, prefix: str = "s") -> tuple[str, list[str]]:
    rels = [f"rad/{prefix}{k}.step" for k in range(n)]
    return upload_files(client, {r: step_bytes(f"{prefix}{k}") for k, r in enumerate(rels)}), rels


def cbody(world, shapes, **kw):
    return {"project_id": "p-1", "scenario": "compare", "entry_ids": [world["a"], world["b"]], "shapes": shapes, **kw}


def shapes3(client, ref: int | None = 0):
    uid, rels = multi_upload(client, 3)
    names = ["기준 평판", "비드 1", "비드 2"]
    return [{"upload_id": uid, "rel": r, "name": names[k], "reference": k == ref} for k, r in enumerate(rels)]


def _app(tmp_path, engine, fake_dashboard, clock, d):
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock))
    return TestClient(app, base_url="http://127.0.0.1")


def _job(engine, jid):
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM jobs WHERE id=:i"), {"i": jid}).mappings().one())


def code(r):
    return r.json()["detail"]["code"]


# ================================================================ 활성(SC-D-3)
def test_settings_compare_block(client, world):
    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["compare"] is True and s["compare"] == {
        "enabled": True, "reason": None, "max_shapes": 20, "total_max_mb": 1000.0, "mesh_size_mm": 3.0}


@pytest.mark.parametrize("case", ["paicad_low", "paicad_missing", "no_gmsh", "compare_off", "doe_off"])
def test_compare_enable_rules(tmp_path, engine, fake_dashboard, clock, case):
    base = tmp_path / case
    base.mkdir()
    d = doe_settings_dict(base, paicad=case != "paicad_missing")
    if case == "compare_off":
        d["bead_doe"]["compare"] = {"enabled": False}
    if case == "doe_off":
        d["bead_doe"]["enabled"] = False
    if case == "paicad_low":
        record_paicad(engine, ready=False, version="0.13.2", reason="PAICAD_VERSION_LOW")
    elif case == "paicad_missing":
        record_paicad(engine, ready=False, version=None, reason="PAICAD_NOT_FOUND")
    else:
        record_paicad(engine, gmsh=case != "no_gmsh")
    want = {"paicad_low": None, "paicad_missing": None, "no_gmsh": "GMSH_UNAVAILABLE", "compare_off": "COMPARE_DISABLED",
            "doe_off": "DOE_DISABLED"}[case]
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        s = c.get(f"{API}/doe/settings", headers=R).json()
        assert s["scenarios"]["compare"] is (want is None) and s["compare"]["reason"] == want
        if case.startswith("paicad"):
            assert s["enabled"] is False and s["scenarios"]["same"] is False        # ①②③ 은 막힘, ④ 는 활성
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/check-inputs", json=b, headers=W)
        if want is None:
            assert r.status_code == 200, r.text
        else:
            assert r.status_code == 503 and code(r) == want


# ================================================================ 입력 검사(V-SC-4)
def test_check_inputs_errors(client, world, engine, settings_dict):
    sh = shapes3(client)
    ok = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh))
    assert ok.status_code == 200, ok.text
    o = ok.json()
    assert o["reference_source"] == "step" and o["step"] is None and o["size"] is None and o["base"] is None
    assert [(x["index"], x["name"], x["file_name"], x["reference"], x["id"]) for x in o["shapes"]] == [
        (0, "기준 평판", "s0.step", True, "d000"), (1, "비드 1", "s1.step", False, "d001"),
        (2, "비드 2", "s2.step", False, "d002")]
    assert all(len(x["sha256"]) == 64 and x["size_mb"] >= 0 for x in o["shapes"])
    assert o["props_default"]["t"] > 0 and o["mesh_size_default_mm"] == 3.0 and o["warnings"] == []

    def err(shapes, **kw):
        r = api(client, "POST", "/doe/check-inputs", json=cbody(world, shapes, **kw))
        assert r.status_code in (400, 404, 409, 422), r.text
        return r.json()["detail"]
    assert err([])["code"] == "SHAPES_EMPTY"
    assert err(sh[:1])["code"] == "SHAPES_TOO_FEW"                           # 기준 있음 → 2개 이상
    assert err([dict(sh[0], reference=True), dict(sh[1], reference=True)])["code"] == "REFERENCE_MULTIPLE"
    for bad in ("", "   ", "x" * 65, "a\tb", "a\x00b", "줄 바꿈"):
        d = err([sh[0], dict(sh[1], name=bad)])
        assert d["code"] == "SHAPE_NAME_INVALID" and d["index"] == 1, bad
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], dict(sh[1], name="  " + "y" * 64 + "  ")]))
    assert r.status_code == 200 and r.json()["shapes"][1]["name"] == "y" * 64          # 앞뒤 공백 제거 후 64자
    d = err([dict(sh[0], name="Plate A"), dict(sh[1], name="plate a")])
    assert d["code"] == "SHAPE_NAME_DUPLICATE" and d["index"] == [0, 1]
    assert err([sh[0], dict(sh[1], rel=sh[0]["rel"])])["code"] == "INVALID_PARAMS"       # 같은 업로드 파일 2번
    assert err([sh[0], dict(sh[1], rel=None)])["code"] == "INVALID_PARAMS"                # 한 업로드 여러 STEP → rel 필요
    d = err([sh[0], dict(sh[1], rel="rad/nope.step")])
    assert d["code"] == "STEP_INVALID" and d["index"] == 1
    for extra in ({"step_upload_id": sh[0]["upload_id"]}, {"part_title": "x"}, {"mesh_upload_id": sh[0]["upload_id"]}):
        assert err(sh, **extra)["code"] == "INVALID_PARAMS"
    many = [{"upload_id": sh[0]["upload_id"], "rel": sh[0]["rel"], "name": f"n{k}"} for k in range(21)]
    assert err(many)["code"] == "SHAPES_TOO_MANY"
    bad = upload_files(client, {"rad/x.step": b"not a step\n"})
    d = err([sh[0], {"upload_id": bad, "name": "나쁨"}])
    assert d["code"] == "STEP_INVALID" and d["index"] == 1
    assert err([sh[0], {"upload_id": "nope", "name": "없음"}])["code"] == "UPLOAD_NOT_FOUND"
    other = upload_files(client, {"rad/o.step": step_bytes("o")}, token="tok-power2")
    assert err([sh[0], {"upload_id": other, "name": "남의 것"}])["code"] == "UPLOAD_NOT_FOUND"
    r = api(client, "POST", "/doe/check-inputs", json={**cbody(world, sh), "entry_ids": ["nope"]})
    assert code(r) == "ENTRY_NOT_FOUND"
    # 같은 sha256 STEP → 경고(차단 아님), 업로드 1개 = STEP 1개면 rel 생략 가능
    u1 = upload_files(client, {"rad/dup.step": step_bytes("dup")})
    u2 = upload_files(client, {"rad/dup2.step": step_bytes("dup")})
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], {"upload_id": u1, "name": "D1"},
                                                                   {"upload_id": u2, "name": "D2"}]))
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["SHAPE_DUPLICATE_FILE"]
    # 같은 파일을 (upload_id, rel 생략)·(upload_id, rel) 로 두 번 → 422(정규화된 동일 파일 판정)
    for pair in ([{"upload_id": u1, "name": "D1"}, {"upload_id": u1, "rel": "rad/dup.step", "name": "D1b"}],
                 [{"upload_id": u1, "rel": "rad/dup.step", "name": "D1"}, {"upload_id": u1, "name": "D1b"}]):
        d = err([sh[0], *pair])
        assert d["code"] == "INVALID_PARAMS", d



def test_check_inputs_same_resolved_file(client, world, monkeypatch):
    """지정(upload_id·rel)이 달라도 해석된 실제 파일이 같으면(정규화 경로) 422 INVALID_PARAMS + index."""
    from esl_platform.api.services import doe as svc

    sh = shapes3(client)
    real = svc.up_svc.doe_source
    calls = {}

    def fake(ctx, principal, upload_id, project_id, kind, rel=None):
        up, root, path = real(ctx, principal, upload_id, project_id, kind, rel=rel)
        if rel == sh[2]["rel"]:                                  # 세 번째 형상 → 두 번째와 같은 파일(경로 표기만 다름)
            path = os.path.join(os.path.dirname(calls["p1"]), ".", os.path.basename(calls["p1"]))
        elif rel == sh[1]["rel"]:
            calls["p1"] = path
        return up, root, path
    monkeypatch.setattr(svc.up_svc, "doe_source", fake)
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh))
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS", r.text
    assert r.json()["detail"]["index"] == [1, 2]


def test_total_size_limit(tmp_path, engine, fake_dashboard, clock):
    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["compare"] = {"total_max_mb": 0.0001}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/check-inputs", json=b, headers=W)
        assert r.status_code == 422 and code(r) == "SHAPES_TOO_LARGE"


def test_case_reference_check(client, world, engine):
    uid, rels = multi_upload(client, 2)
    sh = [{"upload_id": uid, "rel": rels[0], "name": "B안"}, {"upload_id": uid, "rel": rels[1], "name": "C안"}]
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh[:1]))
    assert r.status_code == 200, r.text                                      # 기준 없음 → 1개 이상
    o = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh)).json()
    assert o["reference_source"] == "case" and o["base"]["entry_id"] == world["a"] and o["base"]["case_id"] == "c1"
    assert [x["id"] for x in o["shapes"]] == ["d001", "d002"]
    assert [w["code"] for w in o["warnings"]] == ["COMPARE_REF_CASE_MESH"]
    with engine.begin() as c:                                                # 첫 ESL Case 입력 없음 → 409
        c.execute(text("UPDATE cases SET rad_path = '/nowhere/x.rad' WHERE id = 'c1'"))
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh))
    assert r.status_code == 409 and code(r) == "PREREQUISITE_MISSING"


# ================================================================ 연구·실행(SC-D-1·4)
def test_create_run_flow_and_unsupported(client, world, engine, esl_root):
    sh = shapes3(client, ref=1)                                             # 기준 = 두 번째 → d000, 나머지 요청 순서
    r = api(client, "POST", "/doe/studies", json=cbody(world, sh, title="④ 1차", props={"t": 1.2, "E": 2.0e5, "nu": 0.3}))
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["id"]
    assert s["scenario"] == "compare" and s["phase"] == "PREP" and s["title"] == "④ 1차"
    ins = s["inputs"]
    assert ins["reference_source"] == "step" and ins["props"] == {"t": 1.2, "E": 2.0e5, "nu": 0.3}
    assert [(x["id"], x["name"], x["reference"]) for x in ins["shapes"]] == [
        ("d000", "비드 1", True), ("d001", "기준 평판", False), ("d002", "비드 2", False)]
    assert str(esl_root) not in r.text and "path" not in json.dumps(ins)
    job = s["job"]
    assert [x["step_key"] for x in job["steps"]] == ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"]
    d = _job(engine, job["id"])["params"]["doe"]
    assert d["scenario"] == "compare" and d["reference_source"] == "step" and "step" not in d
    assert [x["id"] for x in d["shapes"]] == ["d000", "d001", "d002"] and all(Path(x["path"]).is_file() for x in d["shapes"])
    assert d["cfg"]["bead_doe"]["compare"]["mesh"]["size_mm"] == 3.0 and d["props"]["t"] == 1.2
    r = api(client, "POST", "/doe/studies", json=cbody(world, sh, mesh_size_mm=4.0))
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    # matrix·preview·params·plan-view·thumb·bead png → 409 SCENARIO_UNSUPPORTED
    for m, p, kw in (("POST", "matrix", {"json": {"version": 1, "spec": {"method": "lhs", "params": []}}}),
                     ("POST", "preview", {"json": {"version": 1, "spec": {"method": "lhs", "params": []}}}),
                     ("GET", "params", {}), ("GET", "plan-view", {}), ("GET", "preview/thumb/d001", {}),
                     ("GET", "beads/B1.png", {})):
        rr = api(client, m, f"/doe/studies/{sid}/{p}", **kw)
        assert rr.status_code == 409 and code(rr) == "SCENARIO_UNSUPPORTED", (p, rr.text)
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": 1})
    assert r.status_code == 409 and code(r) == "JOB_ACTIVE"
    finish_job(engine, job["id"])
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": 1})
    assert r.status_code == 409 and code(r) == "PREP_NOT_READY"
    prep = {"n_beads": 0, "n_params": 0, "paicad_version": None, "warnings": [], "boundary": None, "n_shapes": 3,
            "n_ready": 2, "failed": [{"id": "d002", "status": "FAILED_SIZE", "code": "SHAPE_MISALIGNED"}],
            "reference_source": "step", "shapes": [
                {"id": "d000", "name": "비드 1", "status": "READY", "n_elems": 100, "quad_ratio": 1.0,
                 "quality": {"fail_elems": 0, "fail_ratio": 0.0, "warn_elems": 1}},
                {"id": "d002", "name": "비드 2", "status": "FAILED_SIZE", "code": "SHAPE_MISALIGNED"}],
            "mesh": {"size_mm": 3.0, "gmsh_version": "4.13.1"}}
    update_study(engine, sid, phase="READY", prep=prep)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g["phase"] == "READY" and g["prep"]["n_ready"] == 2 and g["prep"]["shapes"][0]["quad_ratio"] == 1.0
    assert g["prep"]["shapes"][0]["quality"]["fail_elems"] == 0 and g["prep"]["failed"][0]["status"] == "FAILED_SIZE"
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"], "solver": "nonlinear"})
    assert r.status_code == 422 and code(r) == "SOLVER_UNSUPPORTED"
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"]})       # matrix_sha256 없이
    assert r.status_code == 202, r.text
    s2 = r.json()
    assert s2["phase"] == "RUN" and s2["job"]["job_type"] == "DOE_RUN"
    assert [x["step_key"] for x in s2["job"]["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    p = _job(engine, s2["job"]["id"])["params"]["doe"]
    assert p["run"]["solver"] == "linear" and "matrix_sha256" not in p
    finish_job(engine, s2["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": s2["version"]})
    assert r.status_code == 409 and code(r) == "ALREADY_RUN"
    # 결과(SC-D-4·§6): shape·민감도 생략·excluded shape·per-esl name
    base = study_dir(esl_root, sid)
    (base / "post").mkdir(parents=True)
    res = {"scenario": "compare", "reference_source": "step", "C_ref": 10.0,
           "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3, "worst_entry_id": world["a"],
                        "shape": {"name": "비드 1", "file_name": "s1.step", "reference": True}},
           "n_ok": 1, "n_skipped": {"collision": 0, "fixed": 0, "geom": 0},
           "n_failed": {"morph": 0, "mesh": 0, "solve": 0, "size": 1},
           "ranking": [{"id": "d001", "values": {}, "score": 0.9, "improvement": 0.1, "worst_entry_id": world["a"],
                        "umax": 0.9, "epsmax": 1e-3, "worst_ratio": 0.95, "pareto": True, "rank": 1,
                        "shape": {"name": "기준 평판", "file_name": "s0.step", "reference": False}}],
           "sensitivity": None, "sensitivity_reason": "COMPARE_NO_PARAMS", "boundary_warnings_n": 0, "view3d": [],
           "best": None, "noise_floor": None, "ratio_tol": 1e-6, "per_esl_inline": False, "esl": [], "warnings": []}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (base / "post" / "designs.json").write_text(json.dumps({"designs": [
        {"id": "d000", "status": "OK"}, {"id": "d001", "status": "OK"},
        {"id": "d002", "status": "FAILED_SIZE", "code": "SHAPE_MISALIGNED",
         "shape": {"name": "비드 2", "file_name": "s2.step", "reference": False}}]}), encoding="utf-8")
    (base / "post" / "per_esl.json").write_text(json.dumps({"esl": [], "ratio_tol": 1e-6, "designs": {"d001": []},
                                                            "names": {"d001": "기준 평판"}}), encoding="utf-8")
    update_study(engine, sid, phase="DONE", result=res)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["scenario"] == "compare" and o["reference_source"] == "step" and o["sensitivity"] is None
    assert o["sensitivity_reason"] == "COMPARE_NO_PARAMS" and not [w for w in o["warnings"] if w["code"] == "SENSITIVITY_TOO_FEW"]
    assert o["ranking"][0]["shape"]["name"] == "기준 평판" and o["baseline"]["shape"]["name"] == "비드 1"
    assert o["excluded"] == [{"id": "d002", "status": "FAILED_SIZE", "code": "SHAPE_MISALIGNED", "values": {},
                              "shape": {"name": "비드 2", "file_name": "s2.step", "reference": False}}]
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl").json()
    assert pe["designs"] == [{"id": "d001", "name": "기준 평판", "per_esl": []}]
    # 복제: 모든 형상 업로드가 남아 있어야
    r = api(client, "POST", f"/doe/studies/{sid}/clone", json={})
    assert r.status_code == 201, r.text
    assert r.json()["scenario"] == "compare" and len(r.json()["inputs"]["shapes"]) == 3
    Path(d["shapes"][2]["path"]).unlink()
    r = api(client, "POST", f"/doe/studies/{sid}/clone", json={})
    assert r.status_code == 409 and code(r) == "PREREQUISITE_MISSING" and r.json()["detail"]["missing"] == [2]


def test_other_scenarios_reject_shapes(client, world):
    uid, rels = multi_upload(client, 1)
    r = api(client, "POST", "/doe/check-inputs", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"]],
                                                       "shapes": [{"upload_id": uid, "name": "x"}]})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    r = api(client, "POST", "/doe/check-inputs", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"]]})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
