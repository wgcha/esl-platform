"""비드 최적화 API(계약 esl_opt_run.md §5) — V-OR-1(API 크기), V-OR-2(API 동일성·지연 백필), V-OR-4(API 모드),
V-OR-15(권한·SOLVER_NOT_CONFIGURED·다운로드 탈출·bundle 상한·CSP·plan-view 상한), V-OR-19(환경 점검 ↔ solver_ready),
V-OR-20·21(전략·k·목표 기준 저장·응답·retry 유지·422), OPT_RUN 작업 형식."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from esl_test_support import API, H
from opt_support import (
    R,
    W,
    make_case,
    opt_settings_dict,
    plate,
    register_template,
    run_body,
    seed_opt_entry,
)
from sqlalchemy import text


@pytest.fixture()
def settings_dict(tmp_path):
    return opt_settings_dict(tmp_path)


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    a = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    b = seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2)
    other = seed_opt_entry(engine, esl_root, "c1", plate(node_base=5000), "bend", scene_no=3)
    return {"a": a, "b": b, "other": other, "mesh": m}


def _entry(client, eid):
    r = client.get(f"{API}/library/entries/{eid}", headers=R)
    assert r.status_code == 200, r.text
    return r.json()


def _fail_job(engine, job_id):
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='FAILED', queue_seq=NULL, failure_code='OS_SOLVE_FAILED', "
                       "finished_at=now() WHERE id=:i"), {"i": job_id})


# ================================================================ V-OR-15 설정·권한
def test_settings_defaults_and_method_sources(client):
    from esl.opt import load_method_sources

    r = client.get(f"{API}/opt/settings", headers=R)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["enabled"] is True and s["solver_ready"] is True and s["solver_reason"] is None
    assert s["bead_defaults"] == {"angle": 45.0, "min_width": 60.0, "height": 10.0}
    assert s["keepout_auto"] == {"hole_radius_mm": 15.0, "edge_band_mm": 10.0}
    assert s["loads"] == {"default_objective_norm": "abs", "default_strategy": "A", "mac_merge": 0.95, "max_cases": 20,
                          "default_k": 5}
    assert s["size"] == {"tol_rel": 0.02, "plate_tol_rel": 0.05, "require_inch": True}
    assert s["method_sources"] == load_method_sources()                 # 자료 파일 1곳(§9.1)
    assert s["template_ext"] == [".rad", ".inc", ".fem"] and s["max_rects"] == 20 and s["max_entries"] == 200
    assert client.get(f"{API}/opt/settings").status_code == 401


def test_solver_not_configured_503(tmp_path, engine, fake_dashboard, clock):
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    base = tmp_path / "nosolver"
    base.mkdir()
    d = opt_settings_dict(base, solver=False)                # 설정 경로는 있으나 파일 없음
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock))
    make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
    eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        s = c.get(f"{API}/opt/settings", headers=R).json()
        assert s["solver_ready"] is False and "파일이 없습니다" in s["solver_reason"]
        # 서버 경로는 전역 관리자에게만(통합 Verifier 7)
        assert "optistruct.bat" not in s["solver_reason"] and "관리자 문의" in s["solver_reason"]
        sa = c.get(f"{API}/opt/settings", headers=H("tok-admin")).json()
        assert "optistruct.bat" in sa["solver_reason"]
        r = c.post(f"{API}/opt/runs", json=run_body([eid]), headers=W)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "SOLVER_NOT_CONFIGURED"
        assert "optistruct.bat" not in r.json()["detail"]["message"]


def test_permissions(client, world):
    body = run_body([world["a"]])
    assert client.post(f"{API}/opt/runs", json=body).status_code == 401
    assert client.post(f"{API}/opt/runs", json=body, headers=R).json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    assert client.post(f"{API}/opt/runs", json=body, headers=H("tok-general", True)).status_code == 403
    assert client.post(f"{API}/opt/runs", json=body, headers=H("tok-nonmember", True)).status_code == 403
    r = client.post(f"{API}/opt/runs", json=body, headers=W)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.get(f"{API}/opt/runs/{rid}", headers=H("tok-general")).status_code == 200    # 조회 = 프로젝트 조회 권한
    assert client.get(f"{API}/opt/runs/{rid}", headers=H("tok-nonmember")).status_code == 403
    assert client.get(f"{API}/opt/runs/nope", headers=R).json()["detail"]["code"] == "OPT_RUN_NOT_FOUND"
    assert client.get(f"{API}/opt/runs", params={"project_id": "p-1"}, headers=H("tok-nonmember")).status_code == 403
    assert [x["id"] for x in client.get(f"{API}/opt/runs", headers=H("tok-nonmember")).json()] == []
    lst = client.get(f"{API}/opt/runs", params={"project_id": "p-1", "scenario": "S1"}, headers=R).json()
    assert [x["id"] for x in lst] == [rid]
    # 다른 사용자의 작업 재시도·취소는 전역 관리자만(기존 규칙)
    job = r.json()["job"]["id"]
    assert client.post(f"{API}/jobs/{job}/cancel", headers=H("tok-power2", True)).status_code == 403


# ================================================================ 작업 형식(§6.1) · V-OR-20 · V-OR-21
def test_run_creates_opt_job_and_params(client, world, engine):
    r = client.post(f"{API}/opt/runs", json=run_body([world["a"], world["b"]], title="강건 비드 1차"), headers=W)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["scenario"] == "S1" and o["load_strategy"] == "A" and o["objective_norm"] == "abs" and o["k"] is None
    assert o["state"] == "QUEUED" and o["report_ready"] is False and o["dir_rel"] == f"_opt/{o['id']}"
    assert o["design"]["bead"] == {"angle": 45.0, "min_width": 60.0, "height": 10.0}
    assert o["base"]["entry_id"] == world["a"] and o["base"]["rad_file_name"] == "c1_0000.rad"
    assert "rad_path" not in o["base"]                                  # 서버 경로는 응답에 없음
    job = o["job"]
    assert job["job_type"] == "OPT_RUN" and job["stage"] == 10 and job["lane"] == "SLOT"
    assert job["opt_run_id"] == o["id"] and job["case_id"] is None
    assert [(s["step_key"], s["kind"], s["core_stage"]) for s in job["steps"]] == [
        ("OPT_PREP", "INTERNAL", "opt_prep"), ("OPT_LOAD", "INTERNAL", "opt_load"),
        ("OPT_DECK", "INTERNAL", "opt_deck"), ("OS_SOLVE", "LOCAL", None), ("OPT_POST", "LOCAL", "opt_post"),
        ("OPT_REGISTER", "INTERNAL", None)]
    assert "settings" not in job["params"]                               # 설정 스냅샷은 응답에서 뺌
    with engine.connect() as c:
        p = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": job["id"]}).scalar_one()
    assert p["opt_run_id"] == o["id"] and p["scenario"] == "S1"
    assert set(p["settings"]) == {"opt_run", "core", "library"} and p["settings"]["opt_run"]["enabled"] is True
    assert [e["id"] for e in p["entries"]] == [world["a"], world["b"]]
    assert [e["mode"] for e in p["entries"]] == ["bend", "twist"]
    assert p["base"]["rad_path"].endswith("c1_0000.rad") and p["base"]["part_title"] == "Chassis rear"
    assert p["options"] == {"objective_norm": "abs", "load_strategy": "A", "k": None, "supports": None}
    assert p["keepout_key"] == {"topo_sha256": o["base"]["topo_sha256"]} and p["template"] is None
    # 같은 실행의 비종료 작업은 1개(부분 unique)
    with pytest.raises(Exception):
        with engine.begin() as c:
            c.execute(text("INSERT INTO jobs (id, opt_run_id, project_id, job_type, stage, lane, state, queue_seq, "
                           "holds_slot, params, created_by, created_by_name) VALUES ('x', :r, 'p-1', 'OPT_RUN', 10, "
                           "'SLOT', 'QUEUED', 999, false, '{}', 'u', 'u')"), {"r": o["id"]})


def test_strategy_k_norm_saved_retry_keeps_and_422(client, world, engine):
    ids = [world["a"], world["b"]]
    r = client.post(f"{API}/opt/runs", json=run_body(ids, options={"load_strategy": "C", "k": 2,
                                                                   "objective_norm": "rel"}), headers=W)
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["load_strategy"], o["k"], o["objective_norm"]) == ("C", 2, "rel")
    with engine.connect() as c:
        row = c.execute(text("SELECT load_strategy, k, objective_norm FROM opt_runs WHERE id=:i"), {"i": o["id"]}).one()
    assert tuple(row) == ("C", 2, "rel")
    # C 기본 k = 5
    r2 = client.post(f"{API}/opt/runs", json=run_body(ids, options={"load_strategy": "C"}), headers=W).json()
    assert r2["k"] == 5
    # 잘못된 값 422
    for opts in ({"load_strategy": "D"}, {"load_strategy": "C", "k": 0}, {"load_strategy": "C", "k": 21},
                 {"objective_norm": "max"}, {"k": 99}):
        rr = client.post(f"{API}/opt/runs", json=run_body(ids, options=opts), headers=W)
        assert rr.status_code == 422 and rr.json()["detail"]["code"] == "INVALID_PARAMS", (opts, rr.text)
    bad = client.post(f"{API}/opt/runs", json=run_body(ids, design={"bead": {"angle": 95, "min_width": 60,
                                                                               "height": 10}}), headers=W)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_PARAMS"
    # retry: 같은 params(전략·k·목표 기준 스냅샷), 실행 행 값 유지, 실행의 최신 작업 갱신
    _fail_job(engine, o["job"]["id"])
    rt = client.post(f"{API}/jobs/{o['job']['id']}/retry", headers=W)
    assert rt.status_code == 201, rt.text
    nj = rt.json()
    assert nj["opt_run_id"] == o["id"] and nj["retry_of_job_id"] == o["job"]["id"] and nj["resume_from_step"] is None
    assert nj["params"]["options"] == {"objective_norm": "rel", "load_strategy": "C", "k": 2, "supports": None}
    g = client.get(f"{API}/opt/runs/{o['id']}", headers=R).json()
    assert g["job"]["id"] == nj["id"] and (g["load_strategy"], g["k"], g["objective_norm"]) == ("C", 2, "rel")
    assert client.post(f"{API}/jobs/{nj['id']}/retry", headers=W).status_code == 409        # 진행 중
    # 로그 경로 = 실행 폴더(없으면 빈 줄)
    lg = client.get(f"{API}/jobs/{nj['id']}/log", headers=R)
    assert lg.status_code == 200 and lg.json()["lines"] == []


def test_strategy_b_needs_modes(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    z1 = seed_opt_entry(engine, esl_root, "c1", plate(), "zero", scene_no=1)
    z2 = seed_opt_entry(engine, esl_root, "c1", plate(), "zero", scene_no=2)
    r = client.post(f"{API}/opt/runs", json=run_body([z1, z2], options={"load_strategy": "B"}), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "NO_MODE_CANDIDATES"
    assert client.post(f"{API}/opt/runs", json=run_body([z1, z2]), headers=W).status_code == 201   # A 는 모드와 무관


# ================================================================ V-OR-2 (API) S1 동일성 · 지연 백필
def test_s1_check_lazy_backfill_and_model_mismatch(client, world, engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM library_entries WHERE topo_sha256 IS NOT NULL")).scalar_one() == 0
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [world["a"], world["b"],
                                                                                    world["other"]]}, headers=W)
    assert r.status_code == 200, r.text
    out = r.json()
    rows = {e["entry_id"]: e for e in out["entries"]}
    assert rows[world["a"]]["same_model"] and rows[world["b"]]["same_model"]
    assert not rows[world["other"]]["same_model"] and rows[world["other"]]["reason"] == "TOPOLOGY"
    b = out["base"]
    assert b["entry_id"] == world["a"] and b["case_id"] == "c1" and b["part_title"] == "Chassis rear"
    assert b["n_nodes"] == 117 and b["n_elems"] == 96 and len(b["supports"]) == 3
    assert b["pids"] == [{"pid": 10, "title": None, "n_elems": 96, "thickness": 1.5, "E": 2.1e5, "nu": 0.3}]
    from esl.opt import identity

    assert b["topo_sha256"] == identity.topo_sha256(world["mesh"])          # 코어 같은 함수
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM library_entries WHERE topo_sha256 IS NOT NULL")).scalar_one()
        ver = c.execute(text("SELECT version FROM library_entries WHERE id=:i"), {"i": world["a"]}).scalar_one()
    assert n == 3 and ver == 1                                              # 백필은 version 을 올리지 않음
    e = _entry(client, world["a"])
    assert e["topo_sha256"] == b["topo_sha256"] and e["size"]["inch"] == 55
    assert (e["size"]["L_xi"], e["size"]["L_eta"]) == (pytest.approx(300.0), pytest.approx(200.0))
    # POST /opt/runs S1: 다른 모델 → 422 MODEL_MISMATCH(행 목록)
    rr = client.post(f"{API}/opt/runs", json=run_body([world["a"], world["other"]]), headers=W)
    assert rr.status_code == 422 and rr.json()["detail"]["code"] == "MODEL_MISMATCH"
    assert rr.json()["detail"]["entries"] == [{"entry_id": world["other"], "same_model": False, "reason": "TOPOLOGY"}]


def test_s1_missing_model_info_and_case_input(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    make_case(engine, inputs_root, "c2", rad=False)                   # Case 입력 rad 없음
    ok = seed_opt_entry(engine, esl_root, "c1")
    noraw = seed_opt_entry(engine, esl_root, "c1", raw=False, scene_no=2)   # raw 없음 → topo null
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [ok, noraw]}, headers=W).json()
    assert r["entries"][1] == {"entry_id": noraw, "same_model": False, "reason": "MODEL_INFO_MISSING"}
    assert _entry(client, noraw)["topo_sha256"] is None
    rr = client.post(f"{API}/opt/runs", json=run_body([ok, noraw]), headers=W)
    assert rr.status_code == 422 and rr.json()["detail"]["code"] == "MODEL_MISMATCH"
    e2 = seed_opt_entry(engine, esl_root, "c2", scene_no=3)
    for path in ("/opt/s1-check",):
        x = client.post(f"{API}{path}", json={"project_id": "p-1", "entry_ids": [e2]}, headers=W)
        assert x.status_code == 409 and x.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    x = client.post(f"{API}/opt/runs", json=run_body([e2]), headers=W)
    assert x.status_code == 409 and x.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    # 다른 프로젝트·없는 항목·중복
    x = client.post(f"{API}/opt/runs", json=run_body([ok, "nope"]), headers=W)
    assert x.status_code == 422 and x.json()["detail"]["code"] == "ENTRY_NOT_FOUND"
    assert x.json()["detail"]["entry_ids"] == ["nope"]
    x = client.post(f"{API}/opt/runs", json=run_body([ok, ok]), headers=W)
    assert x.status_code == 422 and x.json()["detail"]["code"] == "INVALID_PARAMS"
    x = client.post(f"{API}/opt/runs", json=run_body([ok], options={"supports": [
        {"node_id": 1, "dof": "123"}, {"node_id": 2, "dof": "13"}, {"node_id": 3, "dof": "1"}]}), headers=W)
    assert x.status_code == 422 and x.json()["detail"]["code"] == "INVALID_PARAMS"      # S1 은 3-2-1 지정 불가


# ================================================================ V-OR-4 (API) 변형 모드 표시·수정
def test_deform_mode_backfill_patch_and_rule_version(client, world, engine):
    a = _entry(client, world["a"])
    assert a["deform_mode"]["auto"] == "bend" and a["deform_mode"]["effective"] == "bend"
    assert a["deform_mode"]["user"] is None and a["deform_mode"]["rule_version"] == 1
    assert set(a["deform_mode"]["metrics"]) == {"bend", "twist", "resid", "kappa"}
    assert _entry(client, world["b"])["deform_mode"]["effective"] == "twist"
    lst = client.get(f"{API}/library/entries", params={"project_id": "p-1", "mode": "twist"}, headers=R).json()
    assert [e["id"] for e in lst] == [world["b"]]
    assert client.get(f"{API}/library/entries", params={"mode": "x"}, headers=R).status_code == 422
    # 사용자 수정(power, version 잠금)
    url = f"{API}/library/entries/{world['a']}"
    assert client.patch(url, json={"version": a["version"], "deform_mode": "dent"},
                        headers=H("tok-general", True)).status_code == 403
    p = client.patch(url, json={"version": a["version"], "deform_mode": "dent"}, headers=W)
    assert p.status_code == 200, p.text
    dm = p.json()["deform_mode"]
    assert (dm["auto"], dm["user"], dm["effective"], dm["user_by"]) == ("bend", "dent", "dent", "파워")
    stale = client.patch(url, json={"version": a["version"], "deform_mode": "twist"}, headers=W)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "VERSION_CONFLICT"
    assert client.patch(url, json={"version": p.json()["version"], "deform_mode": "wave"}, headers=W).status_code == 422
    # 전략 A·C 결과는 모드와 무관: 실행 params 의 모드는 표시용(효과적 모드 스냅샷)
    # 기준값 변경(rule_version) → auto 만 다시 계산, user 유지
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET deform_mode = jsonb_set(jsonb_set(deform_mode, '{rule_version}', "
                       "'0'), '{auto}', '\"twist\"') WHERE id=:i"), {"i": world["a"]})
    g = _entry(client, world["a"])["deform_mode"]
    assert (g["auto"], g["user"], g["rule_version"]) == ("bend", "dent", 1)
    # null = 자동으로 되돌림
    cur = _entry(client, world["a"])
    p2 = client.patch(url, json={"version": cur["version"], "deform_mode": None}, headers=W).json()["deform_mode"]
    assert (p2["user"], p2["effective"], p2["user_by"]) == (None, "bend", None)
    # 다른 키만 수정하면 모드는 그대로
    cur = _entry(client, world["a"])
    p3 = client.patch(url, json={"version": cur["version"], "note": "메모"}, headers=W).json()
    assert p3["deform_mode"]["effective"] == "bend" and p3["note"] == "메모"


# ================================================================ V-OR-1 (API) S2 크기 · 템플릿
def test_s2_size_rules_and_template_state(client, engine, esl_root, inputs_root, tmp_path):
    make_case(engine, inputs_root, "c1")
    e1 = seed_opt_entry(engine, esl_root, "c1", scene_no=1)
    e2 = seed_opt_entry(engine, esl_root, "c1", L=(306.5, 200.0), scene_no=2)       # +2.17 % → 불일치
    e3 = seed_opt_entry(engine, esl_root, "c1", L=(305.9, 200.0), scene_no=3)       # +1.97 % → 같음
    e4 = seed_opt_entry(engine, esl_root, "c1", inch=65, scene_no=4)
    e5 = seed_opt_entry(engine, esl_root, "c1", inch=None, scene_no=5)
    t = register_template(client, tmp_path)
    tid = t["id"]
    assert t["L_xi"] == pytest.approx(300.0) and t["L_eta"] == pytest.approx(200.0) and t["inch"] is None

    def run(ids, **kw):
        return client.post(f"{API}/opt/runs", json=run_body(ids, "S2", template_id=tid, **kw), headers=W)

    for ids in ([e1, e2], [e1, e4]):
        r = run(ids)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "SIZE_MISMATCH", r.text
    ok = run([e1, e3, e5])
    assert ok.status_code == 201, ok.text
    o = ok.json()
    assert o["template"]["id"] == tid and o["base"] is None and o["size"]["template"]["ok"] is True
    assert any("INCH_UNKNOWN" in w for w in o["size"]["warnings"])
    assert any("INCH_UNKNOWN" in w for w in o["job"]["warnings"])
    # 템플릿 인치 있으면 같아야 함
    t65 = register_template(client, tmp_path, title="65형", inch=65)
    r = client.post(f"{API}/opt/runs", json=run_body([e1], "S2", template_id=t65["id"]), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SIZE_MISMATCH"
    # 템플릿 ±5 %: 큰 템플릿
    big = register_template(client, tmp_path, title="큰 판", mesh=plate(Lx=320.0))
    r = client.post(f"{API}/opt/runs", json=run_body([e1], "S2", template_id=big["id"]), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SIZE_MISMATCH"
    # 템플릿 없음·S2 에 template_id 없음·S1 에 template_id
    r = client.post(f"{API}/opt/runs", json=run_body([e1], "S2", template_id="nope"), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TEMPLATE_NOT_FOUND"
    r = client.post(f"{API}/opt/runs", json=run_body([e1], "S2"), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TEMPLATE_NOT_FOUND"
    r = client.post(f"{API}/opt/runs", json=run_body([e1], "S1", template_id=tid), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"
    # 3-2-1 지정(S2): 템플릿 노드만
    sup = [{"node_id": 1, "dof": "123"}, {"node_id": 117, "dof": "13"}, {"node_id": 9, "dof": "1"}]
    assert run([e1], options={"supports": sup}).status_code == 201
    r = run([e1], options={"supports": [*sup[:2], {"node_id": 99999, "dof": "1"}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_PARAMS"


# ================================================================ V-OR-15 파일·다운로드·bundle·CSP·plan-view
def _fake_outputs(esl_root: Path, rid: str) -> Path:
    d = esl_root / "_opt" / rid
    for rel, data in (("report.html", b"<html><body>bead</body></html>"), ("opt.json", b"{}"),
                      ("post/bead_map.png", b"\x89PNG\r\n\x1a\nfake"), ("post/bead.npz", b"npz"),
                      ("load/selection.json", b"{}"), ("deck/esl_bead.fem", b"BEGIN BULK\n"),
                      ("solve/esl_bead.out", b"out\n"), ("solve/tmp/scratch.bin", b"x"),
                      ("_backup/x/old.txt", b"old")):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return d


def test_files_download_bundle_report(client, world, engine, esl_root, tmp_path):
    o = client.post(f"{API}/opt/runs", json=run_body([world["a"]]), headers=W).json()
    rid = o["id"]
    assert client.get(f"{API}/opt/runs/{rid}/report", headers=R).json()["detail"]["code"] == "REPORT_NOT_FOUND"
    assert client.get(f"{API}/opt/runs/{rid}/bundle", headers=R).json()["detail"]["code"] == "BUNDLE_EMPTY"
    d = _fake_outputs(esl_root, rid)
    (tmp_path / "secret.txt").write_text("secret")
    (d / "post" / "link.txt").symlink_to(tmp_path / "secret.txt")
    with engine.begin() as c:
        c.execute(text("UPDATE opt_runs SET report_rel='report.html' WHERE id=:i"), {"i": rid})
    files = client.get(f"{API}/opt/runs/{rid}/files", headers=R).json()
    rels = [f["rel"] for f in files]
    assert rels[0] == "report.html" and "solve/tmp/scratch.bin" not in rels and "post/link.txt" not in rels
    assert not any(r.startswith("_backup") for r in rels)
    kinds = {f["rel"]: f["kind"] for f in files}
    assert kinds["post/bead_map.png"] == "result" and kinds["load/selection.json"] == "selection"
    assert kinds["deck/esl_bead.fem"] == "deck" and kinds["solve/esl_bead.out"] == "solve"
    assert client.get(f"{API}/opt/runs/{rid}", headers=R).json()["report_ready"] is True
    r = client.get(f"{API}/opt/runs/{rid}/download", params={"rel": "deck/esl_bead.fem"}, headers=R)
    assert r.status_code == 200 and r.content == b"BEGIN BULK\n"
    for rel in ("../../secret.txt", "post/link.txt", "solve/tmp/scratch.bin", "_backup/x/old.txt", "/etc/passwd"):
        x = client.get(f"{API}/opt/runs/{rid}/download", params={"rel": rel}, headers=R)
        assert x.status_code in (404, 422), (rel, x.status_code)
    rep = client.get(f"{API}/opt/runs/{rid}/report", headers=R)
    assert rep.status_code == 200 and "default-src 'none'" in rep.headers["content-security-policy"]
    png = client.get(f"{API}/opt/runs/{rid}/bead-map.png", headers=R)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.get(f"{API}/opt/runs/{rid}/files", headers=H("tok-nonmember")).status_code == 403
    import io
    import zipfile

    z = client.get(f"{API}/opt/runs/{rid}/bundle", headers=R)
    assert z.status_code == 200
    names = sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
    assert f"opt_{rid}/report.html" in names and f"opt_{rid}/deck/esl_bead.fem" in names
    assert not any(n.endswith(".npz") or "/solve/" in n for n in names)
    z2 = client.get(f"{API}/opt/runs/{rid}/bundle", params={"parts": "solve,raw"}, headers=R)
    n2 = zipfile.ZipFile(io.BytesIO(z2.content)).namelist()
    assert f"opt_{rid}/solve/esl_bead.out" in n2 and f"opt_{rid}/report.html" not in n2
    assert client.get(f"{API}/opt/runs/{rid}/bundle", params={"parts": "x"}, headers=R).status_code == 422


def test_bundle_limit_and_plan_view_limit(tmp_path, engine, fake_dashboard, clock):
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    d = opt_settings_dict(tmp_path)
    d["ui"]["max_bundle_bytes"] = 10
    d["view3d"] = {"max_nodes": 50}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    esl_root, inputs = Path(d["storage"]["esl_root"]), Path(d["storage"]["input_roots"][0])
    make_case(engine, inputs, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        x = c.get(f"{API}/opt/plan-view", params={"entry_id": eid}, headers=R)
        assert x.status_code == 413 and x.json()["detail"]["code"] == "PLAN_VIEW_TOO_LARGE"
        rid = c.post(f"{API}/opt/runs", json=run_body([eid]), headers=W).json()["id"]
        _fake_outputs(esl_root, rid)
        b = c.get(f"{API}/opt/runs/{rid}/bundle", headers=R)
        assert b.status_code == 413 and b.json()["detail"]["code"] == "BUNDLE_TOO_LARGE"


def test_plan_view_s1_equals_core(client, world):
    from esl.opt import keepout
    from esl.library import normalize as nz

    r = client.get(f"{API}/opt/plan-view", params={"entry_id": world["a"]}, headers=R)
    assert r.status_code == 200, r.text
    pv = r.json()
    m = world["mesh"]
    exp = keepout.plan_view(m, nz.frame(m["x0"], None, m["conn"], m["elem_type"]), keepout_cfg(), 20000)
    assert pv["outline"] == exp["outline"] and pv["auto_keepout"]["polygons"] == exp["auto_keepout"]["polygons"]
    assert pv["elems"]["n_total"] == 96 and pv["frame"]["a_range"] == pytest.approx([-150.0, 150.0])
    assert pv["key"]["topo_sha256"] and pv["key"]["template_id"] is None
    assert client.get(f"{API}/opt/plan-view", headers=R).status_code == 422
    assert client.get(f"{API}/opt/plan-view", params={"entry_id": world["a"]},
                      headers=H("tok-nonmember")).status_code == 403


def keepout_cfg():
    from esl.opt import settings

    return settings()["keepout"]


# ================================================================ V-OR-19 환경 점검 ↔ /opt/settings.solver_ready
def test_check_matches_solver_ready(tmp_path, client, settings_dict):
    from esl_platform import check

    cfgd = tmp_path / "chk"
    cfgd.mkdir()
    d = json.loads(json.dumps(settings_dict))
    p = cfgd / "esl_platform.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    items = {i.key: i for i in check.run_checks(str(p), use_db=False, platform="linux")}
    assert items["opt_run.solver_ready"].status == "OK" and items["altair.optistruct_path"].status == "OK"
    assert items["opt_run.bead_post_tcl"].status == "OK" and items["storage.templates.write"].status == "OK"
    assert client.get(f"{API}/opt/settings", headers=R).json()["solver_ready"] is True
    Path(d["altair"]["optistruct_path"]).unlink()                       # 같은 판정: 둘 다 준비 안 됨
    items = {i.key: i for i in check.run_checks(str(p), use_db=False, platform="win32")}
    s = client.get(f"{API}/opt/settings", headers=H("tok-admin")).json()       # 관리자 = 경로 포함 원문
    assert items["opt_run.solver_ready"].status == "FAIL" and s["solver_ready"] is False
    assert items["opt_run.solver_ready"].detail == s["solver_reason"]
    assert items["altair.optistruct_path"].status == "FAIL"
    d["opt_run"]["enabled"] = False
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    items = {i.key: i for i in check.run_checks(str(p), use_db=False, platform="linux")}
    assert items["opt_run"].status == "SKIP" and "opt_run.solver_ready" not in items


def test_history_lists_opt_run(client, world):
    o = client.post(f"{API}/opt/runs", json=run_body([world["a"]], title="이력 확인"), headers=W).json()
    h = client.get(f"{API}/history", params={"project_id": "p-1", "job_type": "OPT_RUN"}, headers=R)
    assert h.status_code == 200, h.text
    it = h.json()["items"]
    assert [x["opt_run_id"] for x in it] == [o["id"]] and it[0]["subject_title"] == "이력 확인"
    q = client.get(f"{API}/history", params={"project_id": "p-1", "q": "이력"}, headers=R).json()["items"]
    assert [x["id"] for x in q] == [o["job"]["id"]]
    rv = client.get(f"{API}/jobs/{o['job']['id']}/review", headers=R)
    assert rv.status_code == 200 and rv.json()["job"]["opt_run_id"] == o["id"]


def test_opt_job_routes_require_project_view_and_hide_server_paths(client, world):
    """통합(Verifier): OPT_RUN 작업 조회·로그·이력 상세는 프로젝트 조회 권한, 응답 params 에 서버 절대경로 없음."""
    o = client.post(f"{API}/opt/runs", json=run_body([world["a"]]), headers=W).json()
    jid = o["job"]["id"]
    assert "rad_path" not in (o["job"]["params"].get("base") or {})
    NON = H("tok-nonmember")
    for path in (f"/jobs/{jid}", f"/jobs/{jid}/log", f"/jobs/{jid}/review", f"/jobs/{jid}/files",
                 f"/jobs/{jid}/report"):
        r = client.get(f"{API}{path}", headers=NON)
        assert r.status_code == 403, (path, r.status_code, r.text)
    r = client.get(f"{API}/jobs/{jid}", headers=R)
    assert r.status_code == 200
    base = r.json()["params"]["base"]
    assert "rad_path" not in base and base["rad_file_name"].endswith(".rad")
    rv = client.get(f"{API}/jobs/{jid}/review", headers=R).json()
    assert "rad_path" not in json.dumps(rv["input"]["params"])
    assert client.get(f"{API}/jobs/{jid}/log", headers=R).status_code == 200


def test_acquire_os_semaphore(client, world, engine):
    """altair.max_concurrent_os DB 세마포어(acquire_os / release_os) — 워커 OS_SOLVE 가 쓴다."""
    from esl_platform.core.repositories import jobs as jobs_repo

    jobs_ = []
    for i in range(2):
        o = client.post(f"{API}/opt/runs", json=run_body([world["a"]]), headers=W).json()
        jid = o["job"]["id"]
        with engine.begin() as c:
            c.execute(text("UPDATE jobs SET state='RUNNING', holds_slot=true, queue_seq=NULL, lease_owner_id='w', "
                           "lease_token=:t, lease_acquired_at=now(), lease_expires_at=now() + interval '1 hour' "
                           "WHERE id=:i"), {"t": f"tok{i}", "i": jid})
            c.execute(text("UPDATE job_steps SET state='RUNNING' WHERE job_id=:i AND step_no=4"), {"i": jid})
        jobs_.append((jid, f"tok{i}"))
    with engine.begin() as c:
        assert jobs_repo.acquire_os(c, jobs_[0][0], jobs_[0][1], 4, 1) is True
        assert jobs_repo.acquire_os(c, jobs_[0][0], jobs_[0][1], 4, 1) is True          # 이미 잡음
    with engine.begin() as c:
        assert jobs_repo.acquire_os(c, jobs_[1][0], jobs_[1][1], 4, 1) is False
        assert jobs_repo.os_in_use(c) == 1
    with engine.begin() as c:
        jobs_repo.release_os(c, jobs_[0][0], jobs_[0][1], 4)                            # 라이선스 대기 중 반납
    with engine.begin() as c:
        assert jobs_repo.acquire_os(c, jobs_[1][0], jobs_[1][1], 4, 1) is True
        assert jobs_repo.acquire_os(c, jobs_[0][0], jobs_[0][1], 4, 2) is True           # 한도 2
    with engine.begin() as c:
        c.execute(text("UPDATE job_steps SET state='SUCCEEDED' WHERE job_id=:i AND step_no=4"), {"i": jobs_[1][0]})
        assert jobs_repo.os_in_use(c) == 1                                              # step 끝 → 자동 해제


# ---------------------------------------------------------------- v0.10.0 V-MR-15 게이트(적격 항목만)
def test_run_rejects_ineligible_entries(client, world, engine):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = quality - 'scheme' - 'status' WHERE id=:i"),
                  {"i": world["b"]})
    r = client.post(f"{API}/opt/runs", json=run_body([world["a"], world["b"]]), headers=W)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "ENTRY_NOT_ELIGIBLE"
    assert d["entry_ids"] == [world["b"]] and d["reasons"] == {world["b"]: "LEGACY"}
    e = _entry(client, world["b"])
    assert e["eligible"] is False and e["ineligible_reason"] == "LEGACY"
    assert _entry(client, world["a"])["eligible"] is True
    r = client.post(f"{API}/opt/runs", json=run_body([world["a"]]), headers=W)
    assert r.status_code == 201, r.text


def _to_legacy(engine, eid):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = (quality - 'scheme') || CAST(:q AS jsonb) WHERE id=:i"),
                  {"i": eid, "q": '{"status": "LEGACY"}'})


def test_retry_gate_ineligible(client, world, engine):
    """통합 검증 지적 1c: 재시도가 생성 때 게이트를 우회하지 않음(대상 ESL 이 LEGACY → 422 ENTRY_NOT_ELIGIBLE)."""
    r = client.post(f"{API}/opt/runs", json=run_body([world["a"], world["b"]]), headers=W)
    assert r.status_code == 201, r.text
    o = r.json()
    _fail_job(engine, o["job"]["id"])
    _to_legacy(engine, world["b"])
    rt = client.post(f"{API}/jobs/{o['job']['id']}/retry", headers=W)
    assert rt.status_code == 422 and rt.json()["detail"]["code"] == "ENTRY_NOT_ELIGIBLE", rt.text
    assert rt.json()["detail"]["entry_ids"] == [world["b"]]
