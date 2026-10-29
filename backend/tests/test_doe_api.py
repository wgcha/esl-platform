"""비드 DOE API(계약 esl_bead_doe.md §10) — V-BD-12(권한·오류 표 §10.3·PREVIEW_STALE·VERSION_CONFLICT·solver ≠ linear·
비활성 사유·/doe/settings 관리자만 경로·다운로드 탈출·bundle), V-BD-1(API 행렬 = 코어 행렬 sha, 422), 작업 params 형식·
응답에 서버 절대경로 없음, 업로드·Case 입력 읽기만(V-BD-14 API 쪽)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from doe_support import (
    PARAMS,
    R,
    STEP_BYTES,
    W,
    api,
    body,
    doe_settings_dict,
    finish_job,
    rad_mesh_bytes,
    record_paicad,
    simulate_prep,
    simulate_preview,
    simulate_run,
    study_dir,
    update_study,
    upload_step,
)
from esl_test_support import API, H
from opt_support import make_case, plate, seed_opt_entry, tree, upload_files
from sqlalchemy import text


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
    other = seed_opt_entry(engine, esl_root, "c1", plate(node_base=5000), "bend", scene_no=3)
    record_paicad(engine)
    return {"a": a, "b": b, "other": other, "mesh": m}


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


def _create(client, world, scenario="same", **kw):
    uid = upload_step(client)
    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], uid, scenario, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def _job(engine, jid):
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM jobs WHERE id=:i"), {"i": jid}).mappings().one())


# ================================================================ 설정·비활성 사유(§6.5)
def test_settings_enabled_and_method_sources(client, world):
    from esl.doe import load_method_sources

    s = api(client, "GET", "/doe/settings").json()
    assert s["enabled"] is True and s["reason"] is None
    assert s["paicad"] == {"ready": True, "version": "0.14.0", "pinned": "0.14.0", "warning": None}
    assert s["gmsh"] == {"ready": True, "version": "4.13.1"} and s["scenarios"] == {"same": True, "mesh": True, "step": True}
    assert s["doe"]["default_types"] == ["D", "W"] and s["doe"]["methods"] == ["lhs", "halton", "fullfact"]
    assert s["part_title"] == "chassis rear" and s["max_designs"] == 200 and s["step_max_mb"] == 200
    ms = load_method_sources()
    m = s["method_sources"]
    assert m["version"] == ms["version"] and m["summary_ko"] == ms["summary_ko"] and m["sources"] == ms["sources"]
    assert set(m["methods"]) == {"lhs", "halton", "fullfact"} and set(m["metrics"]) == {"score", "sensitivity"}
    assert m["limits"] == ms["limits_ko"]
    assert client.get(f"{API}/doe/settings").status_code == 401


@pytest.mark.parametrize("case", ["no_section", "no_exe", "missing_exe", "no_record", "low", "no_ocp", "no_gmsh"])
def test_disabled_reasons(tmp_path, engine, fake_dashboard, clock, case):
    base = tmp_path / case
    base.mkdir()
    d = doe_settings_dict(base, paicad=case != "missing_exe")
    if case == "no_section":
        d.pop("bead_doe")
    if case == "no_exe":
        d["bead_doe"]["paicad"]["exe"] = None
    if case == "low":
        record_paicad(engine, ready=False, version="0.13.2", reason="PAICAD_VERSION_LOW")
    elif case == "no_ocp":
        record_paicad(engine, ready=False, ocp=None, reason="PAICAD_OCP_MISSING")
    elif case == "no_gmsh":
        record_paicad(engine, gmsh=False)
    elif case != "no_record":
        record_paicad(engine)
    want = {"no_section": "DOE_DISABLED", "no_exe": "PAICAD_NOT_CONFIGURED", "missing_exe": "PAICAD_NOT_FOUND",
            "no_record": "PAICAD_CHECK_FAILED", "low": "PAICAD_VERSION_LOW", "no_ocp": "PAICAD_OCP_MISSING",
            "no_gmsh": None}[case]
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        s = c.get(f"{API}/doe/settings", headers=R).json()
        assert s["reason"] == want and s["enabled"] is (want is None)
        assert str(base) not in json.dumps(s)                     # 서버 경로 없음
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid = upload_step(c)
        if want is None:                                          # gmsh 없음 → ③ 만 비활성
            assert s["scenarios"] == {"same": True, "mesh": True, "step": False}
            r = c.post(f"{API}/doe/check-inputs", json=body([eid], uid, "step"), headers=W)
            assert r.status_code == 503 and r.json()["detail"]["code"] == "GMSH_UNAVAILABLE"
        else:
            r = c.post(f"{API}/doe/check-inputs", json=body([eid], uid), headers=W)
            assert r.status_code == 503 and r.json()["detail"]["code"] == want
            assert str(base) not in r.text


# ================================================================ 입력 검사·연구 생성(①)
def test_check_inputs_same_model(client, world, engine):
    uid = upload_step(client)
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"], world["other"]], uid))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is False and [e["ok"] for e in out["entries"]] == [True, False]
    assert out["entries"][1]["reason"] == "TOPOLOGY"
    assert out["base"]["entry_id"] == world["a"] and out["base"]["case_id"] == "c1" and out["base"]["topo_sha256"]
    assert out["step"]["file_name"] == "chassis_mid.step" and len(out["step"]["sha256"]) == 64
    assert "rad_path" not in json.dumps(out) and "/inputs/" not in json.dumps(out)
    with engine.connect() as c:
        res = c.execute(text("SELECT state, result FROM uploads WHERE id=:i"), {"i": uid}).one()
    assert res.state == "COMPLETED" and res.result["purpose"] == "doe_step" and res.result["rel"] == "rad/chassis_mid.step"
    # 다른 모델 ESL 이 섞이면 연구 생성 422 MODEL_MISMATCH
    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["other"]], uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MODEL_MISMATCH"


def test_check_inputs_errors(client, world, engine, settings_dict):
    bad = upload_step(client, b"not a step file\n")
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], bad))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "STEP_INVALID"
    two = upload_files(client, {"rad/a.step": STEP_BYTES, "rad/b.stp": STEP_BYTES})
    assert api(client, "POST", "/doe/check-inputs", json=body([world["a"]], two)).json()["detail"]["code"] == "STEP_INVALID"
    uid = upload_step(client)
    r = api(client, "POST", "/doe/check-inputs", json=body(["nope"], uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ENTRY_NOT_FOUND"
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], "nope"))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "UPLOAD_NOT_FOUND"
    # 남의 업로드는 없는 것과 같다
    other = upload_step(client, token="tok-power2")
    assert api(client, "POST", "/doe/check-inputs", json=body([world["a"]], other)).status_code == 404
    partial = upload_files(client, {"rad/c.step": STEP_BYTES}, complete_files=False)
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], partial))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "UPLOAD_NOT_READY"
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], uid, mesh_upload_id=uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


def test_assem_too_large(tmp_path, engine, fake_dashboard, clock):
    base = tmp_path / "big"
    base.mkdir()
    d = doe_settings_dict(base)
    d["bead_doe"]["same"] = {"max_assem_mb": 0.000001}
    ir = Path(d["storage"]["input_roots"][0])
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        make_case(engine, ir, "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid = upload_step(c)
        r = c.post(f"{API}/doe/check-inputs", json=body([eid], uid), headers=W)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "ASSEM_TOO_LARGE"
        assert str(ir) not in r.json()["detail"]["message"]


def test_case_folder_link_rejected(client, world, inputs_root, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (inputs_root / "lnk").symlink_to(target)
    uid = upload_step(client)
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"


def test_permissions_and_create_job_params(client, world, engine, esl_root, inputs_root):
    uid = upload_step(client)
    b = body([world["a"], world["b"]], uid, title="75형 Ch/R 1차")
    assert client.post(f"{API}/doe/studies", json=b).status_code == 401
    assert client.post(f"{API}/doe/studies", json=b, headers=R).json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    assert client.post(f"{API}/doe/studies", json=b, headers=H("tok-general", True)).status_code == 403
    assert client.post(f"{API}/doe/studies", json=b, headers=H("tok-nonmember", True)).status_code == 403
    before = tree(inputs_root)
    r = client.post(f"{API}/doe/studies", json=b, headers=W)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["phase"] == "PREP" and s["version"] == 1 and s["scenario"] == "same" and s["title"] == "75형 Ch/R 1차"
    assert s["inputs"]["step"]["file_name"] == "chassis_mid.step" and s["inputs"]["part_title"] == "Chassis rear"
    assert s["prep"] is None and s["doe"] is None and s["result_ready"] is False
    job = s["job"]
    assert job["job_type"] == "DOE_PREP" and job["stage"] == 11 and job["lane"] == "SLOT"
    assert [x["step_key"] for x in job["steps"]] == ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"]
    assert [x["kind"] for x in job["steps"]] == ["INTERNAL", "INTERNAL", "LOCAL", "INTERNAL", "INTERNAL"]
    assert job["params"] == {"bead_doe_id": s["id"], "kind": "PREP", "out_rel": f"_doe/{s['id']}", "rev": None,
                             "matrix_sha256": None}
    assert str(esl_root) not in r.text and str(inputs_root) not in r.text     # 응답에 서버 절대경로 없음
    assert tree(inputs_root) == before and not study_dir(esl_root, s["id"]).exists()   # 쓰기 없음(워커가 만듦)
    # 워커가 받는 params(계약 머리말)
    p = _job(engine, job["id"])["params"]
    d = p["doe"]
    assert p["bead_doe_id"] == s["id"] and p["kind"] == "PREP" and p["out_rel"] == f"_doe/{s['id']}"
    assert d["scenario"] == "same" and [e["id"] for e in d["entries"]] == [world["a"], world["b"]]
    assert Path(d["entries"][0]["dir"]).is_dir() and d["base"]["entry_id"] == world["a"]
    assert d["base"]["rad_path"].endswith("c1_0000.rad") and d["base"]["case_dir"] == str(inputs_root)
    assert Path(d["step"]["path"]).is_file() and len(d["step"]["sha256"]) == 64
    assert set(d["cfg"]) == {"bead_doe", "opt_run", "commands"} and d["cfg"]["bead_doe"]["enabled"] is True
    assert d["cfg"]["commands"]["paicad_run"][0] == "{paicad}" and d["core"]
    # 조회 권한
    sid = s["id"]
    assert api(client, "GET", f"/doe/studies/{sid}", "tok-general").status_code == 200
    assert api(client, "GET", f"/doe/studies/{sid}", "tok-nonmember").status_code == 403
    assert api(client, "GET", "/doe/studies/nope").json()["detail"]["code"] == "DOE_NOT_FOUND"
    assert api(client, "GET", "/doe/studies", "tok-nonmember", params={"project_id": "p-1"}).status_code == 403
    assert [x["id"] for x in api(client, "GET", "/doe/studies", params={"project_id": "p-1"}).json()] == [sid]
    assert api(client, "GET", "/doe/studies", "tok-nonmember").json() == []
    # 작업 조회도 서버 경로 없음, 다른 사용자 취소는 전역 관리자만
    jr = client.get(f"{API}/jobs/{job['id']}", headers=R)
    assert jr.status_code == 200 and str(esl_root) not in jr.text and str(inputs_root) not in jr.text
    assert client.get(f"{API}/jobs/{job['id']}", headers=H("tok-nonmember")).status_code == 403
    assert client.post(f"{API}/jobs/{job['id']}/cancel", headers=H("tok-power2", True)).status_code == 403
    # 활성 작업 중 미리보기 409(준비 전 → PREP_NOT_READY 보다 JOB_ACTIVE 가 먼저)
    r = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": 1, "spec": {"method": "lhs", "params": []}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_ACTIVE"
    assert api(client, "GET", f"/doe/studies/{sid}/params").json()["detail"]["code"] == "PREP_NOT_READY"
    assert api(client, "GET", f"/doe/studies/{sid}/plan-view").status_code == 409


def test_prep_failure_retry(client, world, engine):
    s = _create(client, world)
    finish_job(engine, s["job"]["id"], "FAILED", "PAICAD_INPUT")
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["phase"] == "FAILED" and g["job"]["failure_code"] == "PAICAD_INPUT"
    assert client.post(f"{API}/jobs/{s['job']['id']}/retry", headers=H("tok-power2", True)).status_code == 403
    r = client.post(f"{API}/jobs/{s['job']['id']}/retry", headers=W)
    assert r.status_code == 201, r.text
    nj = r.json()
    assert nj["job_type"] == "DOE_PREP" and nj["params"]["bead_doe_id"] == s["id"]
    assert _job(engine, nj["id"])["params"] == _job(engine, s["job"]["id"])["params"]     # 연구 스냅샷 그대로
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["phase"] == "PREP" and g["job"]["id"] == nj["id"]


# ================================================================ 준비 결과 → 행렬·미리보기·실행
def _ready(client, world, engine, esl_root):
    s = _create(client, world)
    simulate_prep(engine, esl_root, s["id"], s["job"]["id"])
    return api(client, "GET", f"/doe/studies/{s['id']}").json()


SPEC = {"method": "lhs", "n": 6, "seed": 7, "params": [{"name": "CHR_BEAD_W_1", "lo": 10.0, "hi": 15.0},
                                                       {"name": "CHR_BEAD_D_1", "lo": 3.0, "hi": 6.0}]}


def test_params_plan_and_bead_png(client, world, engine, esl_root):
    s = _ready(client, world, engine, esl_root)
    assert s["phase"] == "READY" and s["prep"]["n_beads"] == 2 and s["prep"]["boundary"] == {"n_warn": 1, "n_info": 0}
    p = api(client, "GET", f"/doe/studies/{s['id']}/params", "tok-general").json()
    assert [b["id"] for b in p["beads"]] == ["B1", "B5"]
    assert p["beads"][1] == {"id": "B5", "k": 0, "shape": "circular", "sense": "", "center_ab": [0.0, 0.0],
                             "nominal": {"depth": 3.0, "width": 10.0, "length": None}, "fixed_overlap": True, "png": None}
    u = next(x for x in p["params"] if x["name"] == "CHR_BEAD_U_1")
    assert u["feasible"] == [-5.0, 5.0] and u["type"] == "U"                # feasible 없음 → default_range
    assert p["warnings"][0]["code"] == "BEAD_FIXED_OVERLAP"
    r = api(client, "GET", f"/doe/studies/{s['id']}/beads/B1.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n" and r.headers["content-type"] == "image/png"
    assert api(client, "GET", f"/doe/studies/{s['id']}/beads/B5.png").status_code == 404
    assert api(client, "GET", f"/doe/studies/{s['id']}/beads/..%2Fx.png").status_code == 404
    pv = api(client, "GET", f"/doe/studies/{s['id']}/plan-view").json()
    assert pv["frame"]["a_range"] == [0, 300] and "key" not in pv and "auto_keepout" not in pv
    assert pv["links"][0]["from_ab"] == [15.0, 25.0] and pv["links"][0]["to_ab"] == [10.0, 20.0]
    assert pv["links"][0]["kind"] == "fastener" and pv["links"][1]["kind"] == "load"
    assert pv["links"][1]["from_ab"] == [50.0, 60.0]
    assert api(client, "GET", f"/doe/studies/{s['id']}/plan-view", "tok-nonmember").status_code == 403


def test_matrix_same_as_core_and_errors(client, world, engine, esl_root):
    from esl.doe import matrix as mx
    from esl.doe import settings as doe_settings

    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    r = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": s["version"], "spec": SPEC})
    assert r.status_code == 200, r.text
    m = r.json()
    core = mx.generate(copy.deepcopy(SPEC), PARAMS, doe_settings({"bead_doe": {"enabled": True}}))
    assert m["matrix_sha256"] == core["matrix_sha256"] and m["designs"][0]["id"] == "d000"
    assert m["n_designs"] == core["n_designs"] and m["warnings"] == []
    # 입력 순서를 섞어도 같은 sha(V-BD-1)
    sp2 = {**SPEC, "params": list(reversed(SPEC["params"]))}
    assert api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": 1, "spec": sp2}).json()["matrix_sha256"] \
        == m["matrix_sha256"]
    out = api(client, "POST", f"/doe/studies/{sid}/matrix",
              json={"version": 1, "spec": {**SPEC, "params": [{"name": "CHR_BEAD_D_1", "lo": 1.0, "hi": 6.0}]}}).json()
    assert out["warnings"][0]["code"] == "RANGE_OUTSIDE_FEASIBLE"
    cases = [({"params": [{"name": "X_BEAD_D_9", "lo": 1, "hi": 2}]}, "DOE_PARAM_UNKNOWN"),
             ({"params": [{"name": "CHR_BEAD_D_1", "lo": 0.0, "hi": 2}]}, "DOE_RANGE_INVALID"),
             ({"params": [{"name": "CHR_BEAD_W_1", "lo": 5, "hi": 5}]}, "DOE_RANGE_INVALID"),
             ({"params": []}, "DOE_NO_PARAMS"),
             ({"n": 200}, "DOE_TOO_LARGE"),
             ({"method": "fullfact", "levels": 9, "n": None,
               "params": [{"name": n, "lo": 1, "hi": 2} for n in ("CHR_BEAD_D_1", "CHR_BEAD_W_1", "CHR_BEAD_U_1")]},
              "DOE_TOO_LARGE")]
    for over, code in cases:
        r = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": 1, "spec": {**SPEC, **over}})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (over, r.text)


def test_preview_run_flow(client, world, engine, esl_root, inputs_root):
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    r = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"] + 5, "spec": SPEC})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    assert api(client, "POST", f"/doe/studies/{sid}/preview", "tok-general",
               json={"version": s["version"], "spec": SPEC}).status_code == 403
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": s["version"], "matrix_sha256": "a" * 64})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREVIEW_STALE"
    r = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC})
    assert r.status_code == 202, r.text
    p = r.json()
    assert p["phase"] == "PREVIEW" and p["version"] == s["version"] + 1 and p["doe"]["rev"] == 1
    assert p["doe"]["preview"] is None and p["job"]["job_type"] == "DOE_PREVIEW"
    assert [x["step_key"] for x in p["job"]["steps"]] == ["BD_MATRIX", "BD_GRID", "BD_PREVIEW_REGISTER"]
    sha = p["doe"]["matrix_sha256"]
    jp = _job(engine, p["job"]["id"])["params"]
    assert jp["kind"] == "PREVIEW" and jp["doe"]["rev"] == 1 and jp["doe"]["matrix_sha256"] == sha
    assert jp["doe"]["spec"]["params"][0]["name"] == "CHR_BEAD_D_1" and jp["doe"]["paicad_version"] == "0.14.0"
    r = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": p["version"], "spec": SPEC})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_ACTIVE"
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": 1, "spec": SPEC}).json()
    simulate_preview(engine, esl_root, sid, p["job"]["id"], m)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g["phase"] == "PREVIEW_READY"
    pv = g["doe"]["preview"]
    assert pv["matrix_sha256"] == sha and pv["skipped"] == {"collision": 1, "fixed": 0, "geom": 0}
    cells = pv["cells"]
    assert [c["id"] for c in cells] == [d["id"] for d in m["designs"][1:]]
    assert cells[0]["status"] == "SKIPPED_COLLISION" and cells[0]["code"] == "GEOM_FEATURE_COLLISION"
    assert cells[1]["status"] == "READY" and cells[1]["thumb"] is False               # VIEW_* → READY + 그림 없음
    assert cells[2]["status"] == "READY" and cells[2]["thumb"] is True and cells[2]["values"] == m["designs"][3]["values"]
    t = api(client, "GET", f"/doe/studies/{sid}/preview/thumb/{cells[2]['id']}")
    assert t.status_code == 200 and t.content[:4] == b"\x89PNG"
    assert api(client, "GET", f"/doe/studies/{sid}/preview/thumb/d000").status_code == 200
    assert api(client, "GET", f"/doe/studies/{sid}/preview/thumb/{cells[1]['id']}").status_code == 404
    assert api(client, "GET", f"/doe/studies/{sid}/preview/thumb/A.B").status_code == 404
    v = g["version"]
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": v, "matrix_sha256": sha, "solver": "nlstat"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SOLVER_UNSUPPORTED"
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": v, "matrix_sha256": "b" * 64})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREVIEW_STALE"
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": v, "matrix_sha256": sha})
    assert r.status_code == 202, r.text
    rr = r.json()
    assert rr["phase"] == "RUN" and rr["job"]["job_type"] == "DOE_RUN"
    assert [x["step_key"] for x in rr["job"]["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    assert [x["kind"] for x in rr["job"]["steps"]] == ["INTERNAL", "LOCAL", "INTERNAL", "INTERNAL"]
    jp = _job(engine, rr["job"]["id"])["params"]
    assert jp["kind"] == "RUN" and jp["doe"]["run"] == {"solver": "linear", "parallel": 2}
    assert jp["doe"]["matrix_sha256"] == sha and jp["preview"]["rev"] == 1
    assert api(client, "GET", f"/doe/studies/{sid}/results").json()["detail"]["code"] == "RESULT_NOT_READY"
    out = simulate_run(engine, esl_root, sid, rr["job"]["id"], m)
    v = api(client, "GET", f"/doe/studies/{sid}").json()["version"]
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": v, "matrix_sha256": sha})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ALREADY_RUN"
    r = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": v, "spec": SPEC})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ALREADY_RUN"
    _check_results(client, sid, out["best"], m, esl_root)


def _check_results(client, sid, best, m, esl_root):
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g["phase"] == "DONE" and g["result_ready"] is True
    res = api(client, "GET", f"/doe/studies/{sid}/results", "tok-general").json()
    assert res["C_ref"] == 120.0 and res["baseline"] == {"id": "d000", "score": 1.0, "umax": 3.9, "epsmax": 0.0026}
    assert res["ranking"][0]["id"] == best and "C" not in res["ranking"][0] and "noise" not in res["ranking"][0]
    assert [(e["id"], e["status"]) for e in res["excluded"]] == [(m["designs"][1]["id"], "SKIPPED_COLLISION"),
                                                                 (m["designs"][3]["id"], "FAILED_MORPH")]
    assert res["excluded"][0]["values"] == m["designs"][1]["values"]
    assert res["best"]["id"] == best
    assert [f["rel"] for f in res["best"]["files"]] == [f"best/{best}/values.json", f"best/{best}/include/chr_0001.inc",
                                                         f"best/{best}/sample.brep"]
    assert all(f["downloadable"] and f["size"] > 0 for f in res["best"]["files"])
    assert res["noise_floor"] is None and res["view3d"] == ["d000", best] and res["sensitivity"] is None
    assert {w["code"] for w in res["warnings"]} == {"STEP_EXPORT_SKIPPED", "SENSITIVITY_TOO_FEW"}
    files = api(client, "GET", f"/doe/studies/{sid}/files").json()
    rels = [f["rel"] for f in files]
    assert rels[0] == "report.html" and rels[1] == "post/ranking.csv" and set(files[0]) == {"rel", "size", "downloadable"}
    assert not any(r.endswith("paicad.log") for r in rels)                   # argv·paicad.log 는 전역 관리자만
    assert any(r.endswith("paicad.log") for r in (f["rel"] for f in api(client, "GET", f"/doe/studies/{sid}/files",
                                                                         "tok-admin").json()))
    d = api(client, "GET", f"/doe/studies/{sid}/download", params={"rel": f"best/{best}/sample.brep"})
    assert d.status_code == 200 and d.content == b"DBRep"
    for bad in ("../x", "/etc/passwd", f"run/designs/{best}/paicad/paicad.log"):
        assert api(client, "GET", f"/doe/studies/{sid}/download", params={"rel": bad}).status_code in (404, 422), bad
    r = api(client, "GET", f"/doe/studies/{sid}/download", params={"rel": f"best/{best}/sample\x00.brep"})   # NUL → 422(500 아님)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE", r.text
    rep = api(client, "GET", f"/doe/studies/{sid}/report")
    assert rep.status_code == 200 and "default-src 'none'" in rep.headers["content-security-policy"]
    z = api(client, "GET", f"/doe/studies/{sid}/bundle")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert f"doe_{sid}/report.html" in names and f"doe_{sid}/post/ranking.csv" in names
    assert f"doe_{sid}/best/{best}/sample.brep" in names and not any("paicad.log" in n for n in names)
    assert api(client, "GET", f"/doe/studies/{sid}/bundle", params={"parts": "nope"}).status_code == 422
    man = api(client, "GET", f"/doe/studies/{sid}/view3d/{best}/manifest.json").json()
    assert man["geometry_url"] == f"/doe/studies/{sid}/view3d/{best}/part.glb" and man["lod_url"] is None
    assert man["values_url"] == f"/doe/studies/{sid}/view3d/{best}/values.bin" and man["key"] == f"doe/{best}"
    f = api(client, "GET", man["geometry_url"])
    assert f.status_code == 200 and f.content[:4] == b"glTF"
    assert api(client, "GET", man["values_url"]).status_code == 200
    assert api(client, "GET", f"/doe/studies/{sid}/view3d/{best}/manifest2.json").status_code == 404
    assert api(client, "GET", f"/doe/studies/{sid}/view3d/zz9/manifest.json").status_code == 404
    assert api(client, "GET", f"/doe/studies/{sid}/view3d/{best}/part.glb", "tok-nonmember").status_code == 403
    assert str(esl_root) not in json.dumps(res)


def test_clone(client, world, engine, esl_root):
    s = _ready(client, world, engine, esl_root)
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"title": "2차"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["id"] != s["id"] and c["title"] == "2차" and c["phase"] == "PREP" and c["job"]["job_type"] == "DOE_PREP"
    a, b = _job(engine, s["job"]["id"])["params"]["doe"], _job(engine, c["job"]["id"])["params"]["doe"]
    assert b["id"] == c["id"] and b["step"] == a["step"] and b["entries"] == a["entries"] and b["base"] == a["base"]
    assert api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"x": 1}).status_code == 422
    assert api(client, "POST", f"/doe/studies/{s['id']}/clone", "tok-general", json={}).status_code == 403
    assert api(client, "POST", "/doe/studies/nope/clone", json={}).status_code == 404
    # 다른 power 사용자: 원 연구의 STEP 업로드(작성자 것)를 다시 쓰는 복제는 403 UPLOAD_NOT_OWNED(§15 업로드는 본인 것만)
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", "tok-power2", json={})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "UPLOAD_NOT_OWNED", r.text


# ================================================================ ②·③ 입력 검사
def test_mesh_scenario_check_and_size(client, world, engine, tmp_path):
    step = upload_step(client)
    mesh = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path)})
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"], world["other"]], step, "mesh",
                                                          mesh_upload_id=mesh, inch=55))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and all(e["ok"] for e in out["entries"]) and out["base"] is None
    assert out["mesh"]["ok"] is True and out["mesh"]["format"] == "rad"
    assert abs(out["size"]["rel_xi"]) < 1e-6 and out["size"]["inch"] == 55
    s = api(client, "POST", "/doe/studies", json=body([world["a"], world["other"]], step, "mesh", mesh_upload_id=mesh,
                                                      inch=55))
    assert s.status_code == 201, s.text
    d = _job(engine, s.json()["job"]["id"])["params"]["doe"]
    assert d["mesh"]["path"].endswith("rad/B_0000.rad") and Path(d["mesh"]["upload_root"]).is_dir()
    assert d["mesh"]["part_title"] and "base" not in d
    # 크기 다름(±5 % 밖) → 422 SIZE_MISMATCH, 인치 다름도
    big = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path, plate(Lx=360.0), "chassis rear")})
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], step, "mesh", mesh_upload_id=big))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SIZE_MISMATCH"
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], step, "mesh", mesh_upload_id=mesh, inch=65))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SIZE_MISMATCH"
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], step, "mesh", mesh_upload_id=mesh,
                                                          part_title="nothing here"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PART_NOT_FOUND"
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], step, "mesh"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


def test_step_scenario_defaults_and_validation(client, world, engine):
    step = upload_step(client)
    r = api(client, "POST", "/doe/check-inputs", json=body([world["a"], world["other"]], step, "step"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["props_default"] == {"t": 1.5, "E": 2.1e5, "nu": 0.3}         # Q2 A: A Ch/R 두께 중앙값·주 PID E·ν
    assert out["mesh_size_default_mm"] == 20.0                                  # 모서리 25 mm → size_max_mm 20 으로 자름
    assert out["size"] is None and out["mesh"] is None
    r = api(client, "POST", "/doe/studies", json=body([world["a"]], step, "step", mesh_size_mm=50))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    r = api(client, "POST", "/doe/studies", json=body([world["a"]], step, "step", props={"t": 1, "E": 1, "nu": 0.6}))
    assert r.status_code == 422
    r = api(client, "POST", "/doe/studies", json=body([world["a"]], step, "same", mesh_size_mm=5))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    r = api(client, "POST", "/doe/studies", json=body([world["a"]], step, "step", props={"t": 1.2, "E": 2e5, "nu": 0.3},
                                                      mesh_size_mm=5))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["props"] == {"t": 1.2, "E": 2e5, "nu": 0.3} and s["inputs"]["mesh_size_mm"] == 5
    d = _job(engine, s["job"]["id"])["params"]["doe"]
    assert d["props"] == {"t": 1.2, "E": 2e5, "nu": 0.3} and d["mesh_size_mm"] == 5.0 and "base" not in d


def test_history_lists_doe_jobs(client, world, engine):
    s = _create(client, world)
    r = client.get(f"{API}/history", params={"project_id": "p-1"}, headers=R)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    it = next(x for x in items if x["id"] == s["job"]["id"])
    assert it["job_type"] == "DOE_PREP" and it["stage"] == 11 and it["subject_title"] == s["title"]
    r = client.get(f"{API}/history", params={"project_id": "p-1", "q": s["title"][:6]}, headers=R)
    assert any(x["id"] == s["job"]["id"] for x in r.json()["items"])


def test_stale_retry_rejected(client, world, engine, esl_root):
    """검증 지적: 실패한 미리보기 → 재시도 성공 → 실행 → DONE 뒤 원래 실패 작업을 다시 재시도하면 연구가 되돌아가던 문제 —
    가장 최근 작업이 아니거나 연구가 끝났으면 409 DOE_RETRY_STALE, phase·결과 불변."""
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    old = p["job"]["id"]
    finish_job(engine, old, "FAILED", "PAICAD_FAILED")
    r = client.post(f"{API}/jobs/{old}/retry", headers=W)
    assert r.status_code == 201, r.text
    new = r.json()["id"]
    r = client.post(f"{API}/jobs/{old}/retry", headers=W)                      # 이미 재시도한 작업(뒤에 새 작업 있음)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_RETRY_STALE"
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": 1, "spec": SPEC}).json()
    simulate_preview(engine, esl_root, sid, new, m)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    rr = api(client, "POST", f"/doe/studies/{sid}/run",
             json={"version": g["version"], "matrix_sha256": g["doe"]["matrix_sha256"]}).json()
    simulate_run(engine, esl_root, sid, rr["job"]["id"], m)
    r = client.post(f"{API}/jobs/{old}/retry", headers=W)                      # 끝난 연구의 오래된 실패 작업
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DOE_RETRY_STALE", r.text
    g2 = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g2["phase"] == "DONE" and g2["result_ready"] is True
    assert api(client, "GET", f"/doe/studies/{sid}/results").status_code == 200


def test_register_rejects_phase_regression(engine, world, client, esl_root):
    """워커 등록 단계도 phase 역행 금지: DONE 연구에 오래된 DOE_PREVIEW 결과 등록 → RegisterError(DOE_PHASE_STALE)."""
    from esl_worker.register import RegisterError, _study

    s = _ready(client, world, engine, esl_root)
    update_study(engine, s["id"], phase="DONE")
    with engine.begin() as c, pytest.raises(RegisterError) as ei:
        _study(c, {"bead_doe_id": s["id"], "job_type": "DOE_PREVIEW"})
    assert ei.value.code == "DOE_PHASE_STALE"
    with engine.begin() as c, pytest.raises(RegisterError):
        _study(c, {"bead_doe_id": s["id"], "job_type": "DOE_RUN"})                # DONE 뒤 다시 등록도 거부
    update_study(engine, s["id"], phase="PREVIEW")
    with engine.begin() as c:
        assert _study(c, {"bead_doe_id": s["id"], "job_type": "DOE_PREVIEW"})["phase"] == "PREVIEW"   # 제 단계는 허용


def test_matrix_uses_prep_snapshot_cfg(client, world, engine, esl_root):
    """검증 지적: 준비 뒤 서버 설정이 바뀌어도 /matrix·미리보기는 연구 준비 시점 설정(워커와 같은 값)으로 행렬을 만든다."""
    s = _create(client, world)
    simulate_prep(engine, esl_root, s["id"], s["job"]["id"])
    p = _job(engine, s["job"]["id"])["params"]
    p["doe"]["cfg"]["bead_doe"]["max_designs"] = 4                       # 준비 시점 설정(스냅샷) ≠ 지금 설정(200)
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(p), "i": s["job"]["id"]})
    r = api(client, "POST", f"/doe/studies/{s['id']}/matrix", json={"version": 1, "spec": SPEC})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_TOO_LARGE", r.text
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    r = api(client, "POST", f"/doe/studies/{s['id']}/preview", json={"version": g["version"], "spec": SPEC})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DOE_TOO_LARGE"


def test_log_path_mask_rules():
    """작업 로그 경로 가리기(§15, 검증 지적): 알려진 루트 → 이름표 + 상대 경로, 그 밖 절대경로 → ‹…›/파일명.
    paicad argv(JSON, Windows 역슬래시 이중)·OptiStruct argv 같은 규칙, 상대·URL·분수는 그대로."""
    from esl_platform.api.services.jobs import mask_server_paths

    roots = [("E:\\\\shared\\\\ESL_WORK", "‹ESL_ROOT›"), ("E:\\shared\\ESL_WORK", "‹ESL_ROOT›"),
             ("E:/shared/ESL_WORK", "‹ESL_ROOT›"), ("/srv/esl", "‹ESL_ROOT›")]
    line = '[esl-worker] paicad_grid argv: ["C:\\\\ESL\\\\.runtime\\\\venv\\\\Scripts\\\\paicad.exe", "--out-dir", "E:\\\\shared\\\\ESL_WORK\\\\_doe\\\\x\\\\grid"]'
    out = mask_server_paths(line, roots)
    assert "C:" not in out and "shared" not in out and "‹…›/paicad.exe" in out and "‹ESL_ROOT›" in out, out
    os_line = "[esl-worker] OptiStruct argv: ['C:/Altair/2026/hwsolvers/scripts/optistruct.bat', '/srv/esl/_opt/r1/solve/deck.fem', '-nt', '4']"
    out = mask_server_paths(os_line, roots)
    assert out == "[esl-worker] OptiStruct argv: ['‹…›/optistruct.bat', '‹ESL_ROOT›/_opt/r1/solve/deck.fem', '-nt', '4']", out
    keep = "step 1/3 · http://host/esl · rad/a.inc · ratio 3/4"
    assert mask_server_paths(keep, roots) == keep


# ---------------------------------------------------------------- v0.10.0 V-MR-15 게이트(적격 항목만)
def test_create_rejects_ineligible_entries(client, world, engine):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = quality || CAST(:q AS jsonb) WHERE id=:i"),
                  {"i": world["b"], "q": '{"status": "FAIL", "verdict": "FAIL"}'})
    uid = upload_step(client)
    r = client.post(f"{API}/doe/studies", json=body([world["a"], world["b"]], uid), headers=W)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "ENTRY_NOT_ELIGIBLE" and d["reasons"] == {world["b"]: "FAIL"}



def _to_legacy(engine, eid):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = (quality - 'scheme') || CAST(:q AS jsonb) WHERE id=:i"),
                  {"i": eid, "q": '{"status": "LEGACY"}'})


def test_clone_retry_preview_gate_ineligible(client, world, engine, esl_root):
    """통합 검증 지적 1c: 복제·다음 단계 작업도 MR-D-10 게이트(대상 ESL 이 LEGACY 가 되면 422 ENTRY_NOT_ELIGIBLE)."""
    s = _ready(client, world, engine, esl_root)
    _to_legacy(engine, world["b"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "ENTRY_NOT_ELIGIBLE" and d["entry_ids"] == [world["b"]], r.text
    assert d["reasons"] == {world["b"]: "LEGACY"}
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    r = api(client, "POST", f"/doe/studies/{s['id']}/preview", json={"version": g["version"], "spec": SPEC})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ENTRY_NOT_ELIGIBLE", r.text
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM bead_does")).scalar_one() == 1      # 복제 행 없음


def test_prep_retry_gate_ineligible(client, world, engine):
    s = _create(client, world)
    finish_job(engine, s["job"]["id"], "FAILED", "PAICAD_INPUT")
    _to_legacy(engine, world["a"])
    r = client.post(f"{API}/jobs/{s['job']['id']}/retry", headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ENTRY_NOT_ELIGIBLE", r.text



def test_results_per_esl_metrics_sort_and_endpoint(client, world, engine, esl_root):
    """v0.10.0 §11.4: 순위 행의 ESL별 개선 지표·정렬 키(sort)·per-esl 별도 조회, 이전 결과(지표 없음)는 그대로."""
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": 1, "spec": SPEC}).json()
    simulate_preview(engine, esl_root, sid, p["job"]["id"], m)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    rr = api(client, "POST", f"/doe/studies/{sid}/run",
             json={"version": g["version"], "matrix_sha256": g["doe"]["matrix_sha256"]}).json()
    simulate_run(engine, esl_root, sid, rr["job"]["id"], m)
    assert api(client, "GET", f"/doe/studies/{sid}/results", params={"sort": "worst_ratio"}).status_code == 200
    base = study_dir(esl_root, sid)
    res = json.loads((base / "post" / "result.json").read_text(encoding="utf-8"))
    row = res["ranking"][0]
    per_a = [{"entry_id": world["a"], "label": "A", "C": 50.0, "ratio": 0.5, "umax": 1.0, "epsmax": 0.001},
             {"entry_id": world["b"], "label": "B", "C": 120.0, "ratio": 1.2, "umax": 2.0, "epsmax": 0.002}]
    row.update(worst_ratio=1.2, min_improvement=-0.2, all_improved=False, n_improved=1, n_worsened=1, n_unchanged=0,
               geo_mean_improvement=1 - (0.6 ** 0.5), pareto=True, per_esl=per_a)
    row2 = {**row, "id": "d099", "score": 0.9, "rank": 2, "worst_ratio": 0.95, "min_improvement": 0.05,
            "all_improved": True, "n_improved": 2, "n_worsened": 0, "geo_mean_improvement": 0.06, "per_esl": []}
    res["ranking"] = [row, row2]
    res.update(ratio_tol=1e-6, per_esl_inline=True, esl=[{"entry_id": world["a"], "label": "A"},
                                                          {"entry_id": world["b"], "label": "B"}])
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (base / "post" / "per_esl.json").write_text(json.dumps({"esl": res["esl"], "ratio_tol": 1e-6,
                                                            "designs": {row["id"]: per_a, "d099": []}}), encoding="utf-8")
    r = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert r["sort"] == "score" and [x["id"] for x in r["ranking"]] == [row["id"], "d099"]
    x = r["ranking"][0]
    assert x["all_improved"] is False and x["n_worsened"] == 1 and x["pareto"] is True and x["per_esl"][1]["ratio"] == 1.2
    assert r["per_esl_inline"] is True and r["ratio_tol"] == 1e-6 and [e["label"] for e in r["esl"]] == ["A", "B"]
    r = api(client, "GET", f"/doe/studies/{sid}/results", params={"sort": "worst_ratio"}).json()
    assert [x["id"] for x in r["ranking"]] == ["d099", row["id"]] and r["ranking"][0]["rank"] == 2   # rank = score 순위
    bad = api(client, "GET", f"/doe/studies/{sid}/results", params={"sort": "nope"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_PARAMS"
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl", params={"design": row["id"]}, token="tok-general")
    assert pe.status_code == 200 and pe.json()["designs"] == [{"id": row["id"], "per_esl": per_a}]
    assert [d["id"] for d in api(client, "GET", f"/doe/studies/{sid}/results/per-esl").json()["designs"]] == sorted(
        [row["id"], "d099"])
    nf = api(client, "GET", f"/doe/studies/{sid}/results/per-esl", params={"design": "zz"})
    assert nf.status_code == 404 and nf.json()["detail"]["code"] == "DESIGN_NOT_FOUND"
    assert api(client, "GET", f"/doe/studies/{sid}/results/per-esl", "tok-nonmember").status_code == 403
