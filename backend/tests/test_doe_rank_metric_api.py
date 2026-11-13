"""v0.20.0 강성 지표 API·설정(계약 esl_stiffness_metric.md §6, V-SM-8): rank 설정 4곳 거울·검사, 새 스터디 스냅샷 `doe.rank`·
`inputs.rank_metric`(모든 시나리오), 옛 스터디 키 없음(solve), 복제 값 유지, 결과 필드 통과(metric·lin_form·순위 행 보조 필드)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from doe_support import api, body, finish_job, study_dir, update_study, upload_step
from esl_test_support import REPO, make_settings_dict
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    _app,
    _fresh_cache,
    _job,
    cbody,
    code,
    doe_settings_dict,
    multi_upload,
    settings_dict,
    shapes3,
    world,
)

RANK_DEFAULT = {"ratio_tol": 1e-6, "per_esl_inline_max": 2000, "metric": "lin", "lin_form": "ritz", "lin_valid": 0.3,
                "imbalance_warn": 0.02}
SNAP = {"metric": "lin", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02, "schema": 1}


# ================================================================ 설정 거울·검사
def test_rank_defaults_mirror():
    from esl_platform.core.config import BeadDoeCfg, bead_doe_settings

    assert BeadDoeCfg().model_dump()["rank"] == RANK_DEFAULT                  # 새 스터디 기본 lin·ritz(사용자 확정)
    assert bead_doe_settings(None)["rank"]["metric"] == "lin"
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert y["bead_doe"]["rank"] == RANK_DEFAULT, p
    from esl.doe import DEFAULTS

    core = DEFAULTS.get("rank") or {}
    for k in ("metric", "lin_form", "lin_valid", "imbalance_warn"):          # 코어 병합 후 — 키 이름·값 거울
        if k in core:
            assert core[k] == RANK_DEFAULT[k], k


@pytest.mark.parametrize("bad", [
    {"metric": "ritz"}, {"metric": "none"}, {"lin_form": "lin"}, {"lin_valid": 0}, {"lin_valid": -0.1},
    {"imbalance_warn": 0}, {"imbalance_warn": 1.01}, {"ratio_tol": 1}, {"unknown": 1},
])
def test_rank_config_rejects(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "rank": bad}
    lc = load_config_dict(d, environ={})
    assert not lc.ok and any(k.startswith("bead_doe.rank") for k in lc.error_keys()), lc.errors()


@pytest.mark.parametrize("good", [{"metric": "solve"}, {"lin_form": "taylor"}, {"lin_valid": 5.0}, {"imbalance_warn": 1.0},
                                  {"metric": "lin", "lin_form": "ritz", "lin_valid": 0.01, "imbalance_warn": 0.001}])
def test_rank_config_accepts(tmp_path, good):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "rank": good}
    assert load_config_dict(d, environ={}).ok


# ================================================================ 스냅샷
def test_snapshot_all_scenarios(client, world, engine):
    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], upload_step(client)))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["rank_metric"] == "lin"
    p = _job(engine, s["job"]["id"])["params"]["doe"]
    assert p["rank"] == SNAP and p["cfg"]["bead_doe"]["rank"]["metric"] == "lin"
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client)))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["inputs"]["rank_metric"] == "lin"
    assert _job(engine, c["job"]["id"])["params"]["doe"]["rank"] == SNAP


def test_snapshot_follows_config_and_clone(tmp_path, engine, fake_dashboard, clock):
    from test_doe_compare_api import record_paicad

    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["rank"] = {"metric": "solve", "lin_form": "taylor", "lin_valid": 0.5, "imbalance_warn": 0.1}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        from esl_test_support import API, H
        from opt_support import make_case, seed_opt_entry

        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        W = H("tok-power", True)
        r = c.post(f"{API}/doe/studies", json=b, headers=W)
        assert r.status_code == 201, r.text
        s = r.json()
        want = {"metric": "solve", "lin_form": "taylor", "lin_valid": 0.5, "imbalance_warn": 0.1, "schema": 1}
        assert s["inputs"]["rank_metric"] == "solve" and _job(engine, s["job"]["id"])["params"]["doe"]["rank"] == want
        finish_job(engine, s["job"]["id"])
        d2 = copy.deepcopy(d)
        d2["bead_doe"]["rank"] = {"metric": "lin"}
    with _app(tmp_path, engine, fake_dashboard, clock, d2) as c:
        r = c.post(f"{API}/doe/studies/{s['id']}/clone", json={}, headers=W)
        assert r.status_code == 201, r.text
        assert r.json()["inputs"]["rank_metric"] == "solve"                    # 복제 = 원 스터디 값 유지
        assert _job(engine, r.json()["job"]["id"])["params"]["doe"]["rank"] == want


def test_legacy_study_has_no_rank_key(client, world, engine):
    """옛 스냅샷(키 없음): 응답 inputs 에 rank_metric 없음, 복제도 키를 주입하지 않음 → 코어는 solve 동작."""
    from sqlalchemy import text

    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], upload_step(client)))
    s = r.json()
    job = _job(engine, s["job"]["id"])
    params = copy.deepcopy(job["params"])
    params["doe"].pop("rank")
    inp = copy.deepcopy(s["inputs"])
    inp.pop("rank_metric")
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(params), "i": job["id"]})
        c.execute(text("UPDATE bead_does SET inputs=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(inp), "i": s["id"]})
    assert "rank_metric" not in api(client, "GET", f"/doe/studies/{s['id']}").json()["inputs"]
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 201, r.text
    assert "rank_metric" not in r.json()["inputs"]
    assert "rank" not in _job(engine, r.json()["job"]["id"])["params"]["doe"]


# ================================================================ 결과 통과
def _done(client, world, engine, esl_root, extra, rows=None):
    s = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client))).json()
    finish_job(engine, s["job"]["id"])
    base = study_dir(esl_root, s["id"])
    (base / "post").mkdir(parents=True)
    res = {"scenario": "compare", "reference_source": "step", "C_ref": 10.0,
           "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3}, "n_ok": 1, "n_skipped": {}, "n_failed": {},
           "ranking": rows or [], "sensitivity": None, "sensitivity_reason": "COMPARE_NO_PARAMS", "boundary_warnings_n": 0,
           "view3d": [], "best": None, "noise_floor": None, "ratio_tol": 1e-6, "per_esl_inline": False, "esl": [],
           "warnings": [], **extra}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (base / "post" / "designs.json").write_text(json.dumps({"designs": [{"id": "d000", "status": "OK"}]}), encoding="utf-8")
    (base / "post" / "per_esl.json").write_text(json.dumps({"esl": [], "ratio_tol": 1e-6, "designs": {"d001": [
        {"entry_id": "e1", "C": 1.0, "C_solve": 1.2, "ratio": 0.9, "C_lin": 0.95, "C_ritz": 0.97, "rho": 1.05, "imbalance_rel": 0.03,
         "umax_def": 2.5}]}}), encoding="utf-8")
    update_study(engine, s["id"], phase="DONE", result=res)
    return s["id"]


def test_results_pass_metric_fields(client, world, engine, esl_root):
    row = {"id": "d001", "values": {}, "score": 0.9, "improvement": 0.1, "worst_entry_id": "e1", "umax": 3.0, "epsmax": 1e-3,
           "worst_ratio": 0.95, "pareto": True, "rank": 1, "score_solve": 1.4, "imbalance_max": 0.27, "rho_min": 0.9,
           "rho_max": 1.1, "umax_def": 2.5, "C": 12.0, "C_solve": {"e1": 12.0}}
    warn = {"code": "SM_LIN_RANGE", "message": "1차 근사 밖"}
    sid = _done(client, world, engine, esl_root, {"metric": "lin", "lin_form": "ritz", "C_ref_solve": 10.0, "warnings": [warn],
                                                    "n_failed": {"sm": 2}}, [row])
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["metric"] == "lin" and o["lin_form"] == "ritz" and warn in o["warnings"]
    assert o["rank"] == {"metric": "lin", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02}   # 스터디 스냅샷
    assert o["C_ref_solve"] == 10.0 and o["n_failed"] == {"sm": 2} and o["ranking"][0]["C_solve"] == {"e1": 12.0}
    r0 = o["ranking"][0]
    assert {k: r0[k] for k in ("score_solve", "imbalance_max", "rho_min", "rho_max", "umax_def")} == {
        "score_solve": 1.4, "imbalance_max": 0.27, "rho_min": 0.9, "rho_max": 1.1, "umax_def": 2.5} and "C" not in r0
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl").json()["designs"][0]["per_esl"][0]
    assert pe["C_lin"] == 0.95 and pe["C_ritz"] == 0.97 and pe["rho"] == 1.05 and pe["imbalance_rel"] == 0.03
    assert pe["umax_def"] == 2.5 and pe["C_solve"] == 1.2


def test_results_legacy_null_metric(client, world, engine, esl_root):
    sid = _done(client, world, engine, esl_root, {})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["metric"] is None and o["lin_form"] is None and o["C_ref_solve"] is None


def test_settings_rank_block(client, world):
    s = api(client, "GET", "/doe/settings").json()
    assert s["rank"] == {"metric": "lin", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02}


def test_openapi_rank_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    props = spec["components"]["schemas"]["DoeResultOut"]["properties"]
    assert "metric" in props and "lin_form" in props
