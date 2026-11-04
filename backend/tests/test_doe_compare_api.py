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
        "enabled": True, "reason": None, "max_shapes": 20, "total_max_mb": 1000.0, "mesh_size_mm": 3.0,
        # v0.16.0 §6 (C2-D-9·16): 설정 기본 메시 방식·재메시 가능·메시 입력·STEP 사용 가능
        "mesh_mode": "auto", "remesh_available": True,
        "mesh_input": {"enabled": True, "formats": [".rad", ".inc"], "max_mb": 500.0}, "step_ready": True}


@pytest.mark.parametrize("case", ["paicad_low", "paicad_missing", "no_gmsh", "no_gmsh_no_mesh_input", "compare_off",
                                  "doe_off"])
def test_compare_enable_rules(tmp_path, engine, fake_dashboard, clock, case):
    base = tmp_path / case
    base.mkdir()
    d = doe_settings_dict(base, paicad=case != "paicad_missing")
    if case == "compare_off":
        d["bead_doe"]["compare"] = {"enabled": False}
    if case == "no_gmsh_no_mesh_input":
        d["bead_doe"]["compare"] = {"mesh_input": {"enabled": False}}
    if case == "doe_off":
        d["bead_doe"]["enabled"] = False
    if case == "paicad_low":
        record_paicad(engine, ready=False, version="0.13.2", reason="PAICAD_VERSION_LOW")
    elif case == "paicad_missing":
        record_paicad(engine, ready=False, version=None, reason="PAICAD_NOT_FOUND")
    else:
        record_paicad(engine, gmsh=not case.startswith("no_gmsh"))
    # v0.16.0 C2-D-16: gmsh 가 없어도 메시 입력이 켜져 있으면 ④ 활성(STEP 형상만 check-inputs 503 GMSH_UNAVAILABLE)
    want = {"paicad_low": None, "paicad_missing": None, "no_gmsh": None, "no_gmsh_no_mesh_input": "GMSH_UNAVAILABLE",
            "compare_off": "COMPARE_DISABLED", "doe_off": "DOE_DISABLED"}[case]
    want_check = "GMSH_UNAVAILABLE" if case == "no_gmsh" else want
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        s = c.get(f"{API}/doe/settings", headers=R).json()
        assert s["scenarios"]["compare"] is (want is None) and s["compare"]["reason"] == want
        assert s["compare"]["step_ready"] is (not case.startswith("no_gmsh") and case != "doe_off")
        if case.startswith("paicad"):
            assert s["enabled"] is False and s["scenarios"]["same"] is False        # ①②③ 은 막힘, ④ 는 활성
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/check-inputs", json=b, headers=W)
        if want_check is None:
            assert r.status_code == 200, r.text
        else:
            assert r.status_code == 503 and code(r) == want_check
        if case == "no_gmsh":
            assert r.json()["detail"]["index"] == [0, 1]                       # STEP 형상 index


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


# ================================================================ v0.16.0 ④ 메시 옵션(esl_compare_mesh_options.md §3·§6, V-C2-9)
def _f10(*v) -> str:
    return "".join(f"{x:>10}" for x in v)


def rad_bytes(parts=((1, "plate A", "SHELL"),), *, include: str | None = None, nodes: int = 6) -> bytes:
    """작은 Radioss 덱(1차 스캔용): /NODE + /PART(제목) + 파트마다 /SHELL·/SH3N 블록 1행, include 1줄(선택)."""
    ln = ["#RADIOSS STARTER", "/NODE"] + [f"{i:>10}{float(i):>20}{0.0:>20}{0.0:>20}" for i in range(1, nodes + 1)]
    for pid, title, _kw in parts:
        if title is not None:
            ln += [f"/PART/{pid}", title, _f10(1, 1)]
    for pid, _title, kw in parts:
        ln += [f"/{kw}/{pid}", _f10(pid, 1, 2, 3, 4) if kw == "SHELL" else _f10(pid, 1, 2, 3)]
    if include:
        ln.append(f"#include {include}")
    ln.append("/END")
    return ("\n".join(ln) + "\n").encode()


def inc_bytes(pid: int, kw: str = "SHELL", extra: str = "") -> bytes:
    return (f"/{kw}/{pid}\n" + _f10(100 + pid, 3, 4, 5, 6) + "\n" + extra).encode()


def mesh_upload(client) -> str:
    """주 rad(파트 1·2 카드, 2 = 쉘 + 솔리드) + include(파트 3 쉘 블록만 — /PART 카드 없음)."""
    main = rad_bytes(((1, "plate A", "SHELL"), (2, "plate B", "SH3N")), include="part3.inc")
    inc = inc_bytes(3, extra="/BRICK/2\n" + _f10(9, 1, 2, 3, 4, 5, 6, 1, 2) + "\n")
    return upload_files(client, {"rad/model.rad": main, "rad/part3.inc": inc})


def upload_dir(engine, uid: str) -> Path:
    with engine.connect() as c:
        return Path(c.execute(text("SELECT dir_path FROM uploads WHERE id=:i"), {"i": uid}).scalar_one())


def mshape(uid, name, rel=None, part_id=None, **kw):
    d = {"upload_id": uid, "name": name, "source": "mesh", **kw}
    if rel is not None:
        d["rel"] = rel
    if part_id is not None:
        d["part_id"] = part_id
    return d


def test_mesh_shape_check(client, world, engine):
    sh = shapes3(client)
    mu = mesh_upload(client)
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(mu, "메시 안", part_id=1)]))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["mesh_mode"] == "auto" and o["remesh_available"] is True and o["warnings"] == []
    s0, s1 = o["shapes"]
    assert (s0["source"], s0["part_id"], s0["main_rel"]) == ("step", None, "rad/s0.step")
    assert (s1["source"], s1["part_id"], s1["main_rel"], s1["file_name"], s1["id"]) == (
        "mesh", 1, "rad/model.rad", "model.rad", "d001")
    assert [f["rel"] for f in s1["files"]] == ["rad/model.rad", "rad/part3.inc"] and all(len(f["sha256"]) == 64
                                                                                          for f in s1["files"])
    assert s1["sha256"] == s1["files"][0]["sha256"]
    assert s1["parts"] == [{"id": 1, "title": "plate A", "n_shells": 1}, {"id": 2, "title": "plate B", "n_shells": 1},
                           {"id": 3, "title": None, "n_shells": 1}]
    with engine.connect() as c:                                               # 업로드 결과 purpose doe_mesh(파트·파일 목록)
        res = c.execute(text("SELECT result FROM uploads WHERE id=:i"), {"i": mu}).scalar_one()
    assert res["purpose"] == "doe_mesh" and res["rel"] == "rad/model.rad" and res["part_id"] == 1
    assert [f["rel"] for f in res["files"]] == ["rad/model.rad", "rad/part3.inc"]

    def err(shapes, **kw):
        rr = api(client, "POST", "/doe/check-inputs", json=cbody(world, shapes, **kw))
        assert rr.status_code in (400, 409, 422, 503), rr.text
        return rr.json()["detail"]
    d = err([sh[0], mshape(mu, "M")])                                         # 쉘 파트 3개 + ID 없음
    assert d["code"] == "MESH_INPUT_PART_REQUIRED" and d["index"] == 1 and [p["id"] for p in d["parts"]] == [1, 2, 3]
    assert err([sh[0], mshape(mu, "M", part_id=99)])["code"] == "MESH_INPUT_PART_NOT_FOUND"
    assert err([sh[0], mshape(mu, "M", part_id=2)])["code"] == "MESH_INPUT_UNSUPPORTED_ELEMENT"   # 파트 2 = 쉘 + 솔리드
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(mu, "M", part_id=3)]))
    assert r.status_code == 200 and [(w["code"], w["index"]) for w in r.json()["warnings"]] == [
        ("MESH_INPUT_PART_CARD_MISSING", 1)]                                  # /PART 없이 쉘 블록만(부분 export) → info
    # source·part_id 검증(§6 순서): source 값, step 에 part_id
    assert err([sh[0], dict(sh[1], source="bdf")])["code"] == "INVALID_PARAMS"
    d = err([sh[0], dict(sh[1], part_id=1)])
    assert d["code"] == "INVALID_PARAMS" and d["index"] == 1
    assert err([sh[0], mshape(mu, "M", part_id=0)])["code"] == "INVALID_PARAMS"
    # mesh rel 지정: 업로드에 없는 rel → MESH_INPUT_INVALID, 형식 밖(.fem — Q2) → MESH_FORMAT_UNSUPPORTED
    d = err([sh[0], mshape(mu, "M", rel="rad/nope.rad", part_id=1)])
    assert d["code"] == "MESH_INPUT_INVALID" and d["index"] == 1
    fu = upload_files(client, {"rad/a.rad": rad_bytes(), "rad/b.fem": b"$ fem\n"})
    assert err([sh[0], mshape(fu, "M", rel="rad/b.fem")])["code"] == "MESH_FORMAT_UNSUPPORTED"
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(fu, "M", rel="rad/a.rad")]))
    assert r.status_code == 200 and r.json()["shapes"][1]["part_id"] == 1      # 쉘 파트 하나 → part_id 생략 가능
    # 한 rad 의 다른 파트 = 다른 형상(허용), 같은 파트 두 번 = 422
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(mu, "P1", part_id=1),
                                                                   mshape(mu, "P3", part_id=3)]))
    assert r.status_code == 200, r.text
    assert err([sh[0], mshape(mu, "P1", part_id=1), mshape(mu, "P1b", part_id=1)])["code"] == "INVALID_PARAMS"
    assert err([sh[0], mshape(mu, "P1", part_id=1), mshape(mu, "P1b", rel="rad/model.rad", part_id=1)])["code"] == \
        "INVALID_PARAMS"                                                      # 지정 방식만 다른 같은 파일·파트
    # 같은 내용 다른 업로드(같은 sha·파트) → 경고만
    mu2 = mesh_upload(client)
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(mu, "A", part_id=1),
                                                                   mshape(mu2, "B", part_id=1)]))
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["SHAPE_DUPLICATE_FILE"]
    # .inc 하나(부분 export, /PART 없음) — 주 파일 자동 선택
    iu = upload_files(client, {"rad/only.inc": inc_bytes(7)})
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(iu, "inc")]))
    assert r.status_code == 200, r.text
    assert r.json()["shapes"][1]["part_id"] == 7 and r.json()["warnings"][0]["code"] == "MESH_INPUT_PART_CARD_MISSING"
    # 세션에 rad 가 둘이면 rel 필요(② 와 같은 주 파일 규칙)
    two = upload_files(client, {"rad/x.rad": rad_bytes(), "rad/y.rad": rad_bytes()})
    assert err([sh[0], mshape(two, "M")])["code"] == "MESH_INVALID"
    # 쉘 없는 덱
    nos = upload_files(client, {"rad/n.rad": b"#RADIOSS STARTER\n/END\n"})
    assert err([sh[0], mshape(nos, "M")])["code"] == "MESH_INPUT_INVALID"
    # 기준 = 메시 형상, 나머지 STEP(혼합 Q1) — 형상 id 규칙 동일
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [dict(sh[1], reference=False),
                                                                   mshape(mu, "기준 메시", part_id=1, reference=True)]))
    assert r.status_code == 200 and [x["id"] for x in r.json()["shapes"]] == ["d001", "d000"]


def test_mesh_shape_include_rules(client, world, engine, tmp_path):
    """C2-D-3: include 는 업로드 폴더 안만(밖·링크 → PATH_OUTSIDE_ROOT), 못 찾음·상태 파일 → MESH_INPUT_INVALID, 원본 불변."""
    sh = shapes3(client)

    def err(uid, **kw):
        rr = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(uid, "M", **kw)]))
        assert rr.status_code == 422, rr.text
        return rr.json()["detail"]
    outside = tmp_path / "outside.inc"
    outside.write_bytes(inc_bytes(5))
    u = upload_files(client, {"rad/m.rad": rad_bytes(include=str(outside))})
    d = err(u)
    assert d["code"] == "PATH_OUTSIDE_ROOT" and str(tmp_path) not in json.dumps(d)
    u = upload_files(client, {"rad/m.rad": rad_bytes(include="../../../x.inc")})
    assert err(u)["code"] == "PATH_OUTSIDE_ROOT"                             # 없어도 같은 코드(존재 확인 통로 차단)
    u = upload_files(client, {"rad/m.rad": rad_bytes(include="nothere.inc")})
    assert err(u)["code"] == "MESH_INPUT_INVALID"
    u = upload_files(client, {"rad/m.rad": rad_bytes(include="prev.sta"), "rad/prev.sta": b"#radioss state file\n"})
    assert err(u)["code"] == "MESH_INPUT_INVALID"                            # 상태 파일 include
    u = upload_files(client, {"rad/m.rad": rad_bytes(include="lnk.inc")})
    (upload_dir(engine, u) / "rad" / "lnk.inc").symlink_to(outside)
    assert err(u)["code"] == "PATH_OUTSIDE_ROOT"                             # 링크
    # 정상 include 2단 + 원본 sha 전후 불변
    main = rad_bytes(include="sub/a.inc")
    a = b"#include b.inc\n" + inc_bytes(4)
    b = inc_bytes(4, kw="SH3N")
    u = upload_files(client, {"rad/m.rad": main, "rad/sub/a.inc": a, "rad/sub/b.inc": b})
    before = {p.name: p.read_bytes() for p in (upload_dir(engine, u) / "rad").rglob("*") if p.is_file()}
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [sh[0], mshape(u, "M", part_id=4)]))
    assert r.status_code == 200, r.text
    assert [f["rel"] for f in r.json()["shapes"][1]["files"]] == ["rad/m.rad", "rad/sub/a.inc", "rad/sub/b.inc"]
    after = {p.name: p.read_bytes() for p in (upload_dir(engine, u) / "rad").rglob("*") if p.is_file()}
    assert before == after


def test_mesh_input_settings_rules(tmp_path, engine, fake_dashboard, clock):
    """크기 상한(MESH_INPUT_TOO_LARGE)·include 끔·형식 좁힘·메시 입력 끔, gmsh 없음 + 메시만 = 허용."""
    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["compare"] = {"mesh_input": {"max_mb": 0.0001, "formats": [".rad"]}}
    record_paicad(engine, gmsh=False)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")

        def post(shapes):
            return c.post(f"{API}/doe/check-inputs", headers=W,
                          json={"project_id": "p-1", "scenario": "compare", "entry_ids": [eid], "shapes": shapes})
        big = upload_files(c, {"rad/m.rad": rad_bytes(nodes=400)})
        r = post([mshape(big, "A")])
        assert r.status_code == 422 and code(r) == "MESH_INPUT_TOO_LARGE" and r.json()["detail"]["index"] == 0
        iu = upload_files(c, {"rad/only.inc": inc_bytes(7)})
        r = post([mshape(iu, "A")])
        assert r.status_code == 422 and code(r) == "MESH_FORMAT_UNSUPPORTED"     # formats = [.rad] → .inc 거부
    d["bead_doe"]["compare"] = {"mesh_input": {"include": False}}
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1", scene_no=3)

        def post(shapes):
            return c.post(f"{API}/doe/check-inputs", headers=W,
                          json={"project_id": "p-1", "scenario": "compare", "entry_ids": [eid], "shapes": shapes})
        u = upload_files(c, {"rad/m.rad": rad_bytes(include="a.inc"), "rad/a.inc": inc_bytes(2)})
        r = post([mshape(u, "A", part_id=1)])
        assert r.status_code == 422 and code(r) == "MESH_INPUT_INVALID"
        ok = upload_files(c, {"rad/m.rad": rad_bytes()})
        r = post([mshape(ok, "A")])                                            # gmsh 없음 + 메시 형상만 → 허용
        assert r.status_code == 200, r.text
        assert r.json()["remesh_available"] is False                           # STEP 없으면 재메시 경고 없음
        assert [w["code"] for w in r.json()["warnings"]] == ["COMPARE_REF_CASE_MESH"]
        uid, rels = multi_upload(c, 1)
        r = post([mshape(ok, "A"), {"upload_id": uid, "rel": rels[0], "name": "S"}])
        assert r.status_code == 503 and code(r) == "GMSH_UNAVAILABLE" and r.json()["detail"]["index"] == [1]
    d["bead_doe"]["compare"] = {"mesh_input": {"enabled": False}}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1", scene_no=4)
        ok = upload_files(c, {"rad/m.rad": rad_bytes()})
        r = c.post(f"{API}/doe/check-inputs", headers=W, json={"project_id": "p-1", "scenario": "compare",
                                                                "entry_ids": [eid], "shapes": [mshape(ok, "A")]})
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS" and r.json()["detail"]["index"] == [0]


def test_mesh_mode_rules(client, world, engine):
    """C2-D-9·16: mesh_mode 값·④ 전용, remesh 미지원 → mode remesh 422 REMESH_UNAVAILABLE / auto 경고 1회 / 메시만이면 무관."""
    sh = shapes3(client)
    mu = mesh_upload(client)
    for m in ("cad", "remesh", "auto"):
        r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh, mesh_mode=m))
        assert r.status_code == 200 and r.json()["mesh_mode"] == m, r.text
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh, mesh_mode="fast"))
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    r = api(client, "POST", "/doe/check-inputs", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"]],
                                                       "step_upload_id": sh[0]["upload_id"], "mesh_mode": "cad"})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    record_paicad(engine, remesh=False)                                         # 워커: importStl 없음
    from esl_platform.api.services import doe as svc

    svc.reset_status_cache()
    assert api(client, "GET", "/doe/settings").json()["compare"]["remesh_available"] is False
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh, mesh_mode="remesh"))
    assert r.status_code == 422 and code(r) == "REMESH_UNAVAILABLE" and "4.13.1" in r.json()["detail"]["message"]
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh))           # auto(설정 기본) → 경고 1회
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["REMESH_UNAVAILABLE"]
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, sh, mesh_mode="cad"))
    assert r.status_code == 200 and r.json()["warnings"] == []
    r = api(client, "POST", "/doe/check-inputs", json=cbody(world, [mshape(mu, "M", part_id=1)], mesh_mode="remesh"))
    assert r.status_code == 200 and [w["code"] for w in r.json()["warnings"]] == ["COMPARE_REF_CASE_MESH"]  # 메시 형상에는 해당 없음
    record_paicad(engine, remesh=None)                                          # 옛 워커(기록 없음) → 불가로 봄
    svc.reset_status_cache()
    assert api(client, "GET", "/doe/settings").json()["compare"]["remesh_available"] is False


def test_mesh_shape_study_and_clone(client, world, engine):
    sh = shapes3(client)
    mu = mesh_upload(client)
    body = cbody(world, [sh[0], mshape(mu, "메시 안", part_id=3), sh[1]], mesh_mode="cad")
    r = api(client, "POST", "/doe/studies", json=body)
    assert r.status_code == 201, r.text
    s = r.json()
    ins = s["inputs"]
    assert ins["mesh_mode"] == "cad"
    assert [(x["id"], x["source"], x["part_id"]) for x in ins["shapes"]] == [
        ("d000", "step", None), ("d001", "mesh", 3), ("d002", "step", None)]
    assert "path" not in json.dumps(ins) and "upload_root" not in json.dumps(ins)
    dd = _job(engine, s["job"]["id"])["params"]["doe"]
    assert dd["mesh_mode"] == "cad"
    m = dd["shapes"][1]
    assert m["source"] == "mesh" and m["part_id"] == 3 and m["main_rel"] == "rad/model.rad"
    assert Path(m["path"]).is_file() and Path(m["upload_root"]).is_dir()
    assert [f["rel"] for f in m["files"]] == ["rad/model.rad", "rad/part3.inc"]
    assert dd["shapes"][0]["source"] == "step"
    assert dd["mesh_refine"] is None and dd["mesh_ladder"] == ["cad", "refine_local", "refine_global", "remesh"]
    r = api(client, "POST", "/doe/studies", json={**body, "mesh_mode": None, "mesh_refine": False})   # 생략 → 설정(auto)
    assert r.status_code == 201 and r.json()["inputs"]["mesh_mode"] == "auto", r.text
    assert r.json()["inputs"]["mesh_refine"] is False
    assert _job(engine, r.json()["job"]["id"])["params"]["doe"]["mesh_ladder"] == ["cad", "remesh"]
    r = api(client, "POST", "/doe/check-inputs", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"]],
                                                       "step_upload_id": sh[0]["upload_id"], "mesh_refine": True})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"                # ④ 전용
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 201, r.text
    assert _job(engine, r.json()["job"]["id"])["params"]["doe"]["mesh_mode"] == "cad"
    (upload_dir(engine, mu) / "rad" / "part3.inc").unlink()                      # include 업로드 누락 → 복제 409
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 409 and code(r) == "PREREQUISITE_MISSING" and r.json()["detail"]["missing"] == [1]
