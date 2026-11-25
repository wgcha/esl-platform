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

JIG_DEFAULT = {"enabled": True, "fix_kinds": ["INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"], "contact_gap_mm": 2.0, "knn": 8,
               "chunk_nodes": 65536, "max_surf_tris": 20000000, "max_regions": 8, "min_regions": 2, "min_region_nodes": 3,
               "min_region_area_mm2": 25.0, "patch_count": 6, "body_force": True, "basis_tangential": True, "n_modes": 4,
               "rho_t_mm3": 7.85e-9, "modes_sigma": 0.0, "modes_tol": 1e-8, "modes_maxiter": 2000, "modes_ref321": False,
               "w_inplane": 0.1, "reg_force": 1e-3, "reg_modes": 0.0, "ridge": 1e-8, "active_tol": 1e-3,
               "mac_min": 0.9, "umax_err_max": 0.2, "tie_rel_warn": 0.1, "cancel_warn": 0.5, "work_eff_min": 0.05,
               "tie_spread_min": 0.02,
               # v0.24.4 새 키(esl.mech.jig.JIG_NEW_KEYS 거울 — spring_alpha 기본 0.01: 메인 결정, α=1 은 prescribed 와 구분 안 됨)
               "tie_dofs": "normal", "methods": ["prescribed", "spring"], "normal_kink_deg": 45.0,
               "aux321_dup_deg": 10.0, "aux_reaction_warn": 0.05, "spring_k_mode": "auto", "spring_alpha": 0.01,
               "spring_k_value": None, "spring_alpha_scan": []}
NEW_JIG = ("tie_dofs", "methods", "normal_kink_deg", "aux321_dup_deg", "aux_reaction_warn", "spring_k_mode", "spring_alpha",
           "spring_k_value", "spring_alpha_scan")
# v0.24.8 격자 지그(esl_jig_grid_map.md §7.1) — rank.jig_grid 기본
JIG_GRID_DEFAULT = {"enabled": True, "cell_mm": 3.0, "conv_mm": [5.0, 10.0], "tie_capture_rel": 0.25, "tie_snap_rel": 0.75,
                    "tie_normal_deg": 30.0, "tie_miss_frac_max": 0.1, "sample_nbr": 1, "sample_normal_deg": 45.0,
                    "area_ratio_warn": 2.0, "conv_warn": 0.02, "frame_shift_warn": 0.5, "load_resid_warn": 1e-6,
                    "noise_floor_min": 0.01}
RANK_DEFAULT = {"ratio_tol": 1e-6, "per_esl_inline_max": 2000, "metric": "jig", "lin_form": "ritz", "lin_valid": 0.3,
                "imbalance_warn": 0.02, "eval_region": "part", "eval_free_edge_mm": 10.0, "eval_boxes": [], "jig": JIG_DEFAULT, "jig_grid": JIG_GRID_DEFAULT}
# v0.24.0 보완(esl_fint.md §6.2): 새 스냅샷에 평가 영역 고정
EVAL_SNAP = {"mode": "part", "free_edge_mm": 10.0, "boxes": []}
# v0.23.0: 새 스냅샷 = metric 기본 jig + rank.jig 설정 전체 + schema 2(esl_jig_rank.md §4)
SNAP = {"metric": "jig", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02, "jig": JIG_DEFAULT, "schema": 2,
        "eval_region": EVAL_SNAP, "jig_grid": {**JIG_GRID_DEFAULT, "schema": 1}}   # v0.24.8: rank.jig 가 있으면 jig_grid 블록(블록 안 schema 1)


# ================================================================ 설정 거울·검사
def test_rank_defaults_mirror():
    from esl_platform.core.config import BeadDoeCfg, bead_doe_settings

    assert BeadDoeCfg().model_dump()["rank"] == RANK_DEFAULT                  # v0.23.0 새 스터디 기본 jig·lin_form ritz
    assert bead_doe_settings(None)["rank"]["metric"] == "jig"
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert y["bead_doe"]["rank"] == RANK_DEFAULT, p
    from esl.doe import DEFAULTS

    # 코어 DEFAULTS 전체 거울(jig 절 새 키 9개 포함 — v0.24.4 통합 후 예외 없음)
    core = DEFAULTS["rank"]
    skip = ("jig", "jig_grid") if "jig_grid" not in core else ("jig",)     # v0.24.8 jig_grid: 코어 DEFAULTS 병합 전에만 뺌(병합 후 전체 대조)
    assert {k: v for k, v in core.items() if k != "jig"} == {k: v for k, v in RANK_DEFAULT.items() if k not in skip}
    assert core["jig"] == JIG_DEFAULT


@pytest.mark.parametrize("bad", [
    {"metric": "ritz"}, {"metric": "none"}, {"lin_form": "lin"}, {"lin_valid": 0}, {"lin_valid": -0.1},
    {"imbalance_warn": 0}, {"imbalance_warn": 1.01}, {"ratio_tol": 1}, {"unknown": 1},
    {"jig": {"enabled": False}},                                           # metric jig(기본) ∧ enabled false
    {"metric": "solve", "jig": {"fix_kinds": ["RBE9"]}}, {"metric": "solve", "jig": {"fix_kinds": []}},
    {"metric": "solve", "jig": {"fix_kinds": ["RBE2", "RBE2"]}}, {"jig": {"contact_gap_mm": 0}}, {"jig": {"knn": 65}},
    {"jig": {"chunk_nodes": 1000}}, {"jig": {"max_regions": 33}}, {"jig": {"min_regions": 9}}, {"jig": {"patch_count": 0}},
    {"jig": {"active_tol": 1}}, {"jig": {"mac_min": 1.5}}, {"jig": {"umax_err_max": 0}}, {"jig": {"unknown": 1}},
    {"jig": {"ridge": -1}}, {"jig": {"n_modes": 21}}, {"jig": {"n_modes": -1}}, {"jig": {"rho_t_mm3": 0}},
    {"jig": {"modes_tol": -1}}, {"jig": {"modes_maxiter": 0}}, {"jig": {"w_inplane": 1.1}}, {"jig": {"reg_force": -1}}, {"jig": {"reg_modes": -1}},
    {"jig": {"cancel_warn": 0}}, {"jig": {"cancel_warn": 1.1}}, {"jig": {"work_eff_min": 0}}, {"jig": {"work_eff_min": 1}},
])
def test_rank_config_rejects(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "rank": bad}
    lc = load_config_dict(d, environ={})
    assert not lc.ok and any(k.startswith("bead_doe.rank") for k in lc.error_keys()), lc.errors()


@pytest.mark.parametrize("good", [{"metric": "solve"}, {"lin_form": "taylor"}, {"lin_valid": 5.0}, {"imbalance_warn": 1.0},
                                  {"metric": "solve", "jig": {"enabled": False}}, {"jig": {"fix_kinds": ["RBE2"], "knn": 64}},
                                  {"jig": {"n_modes": 0, "basis_tangential": False, "modes_sigma": 5.0, "reg_force": 0,
                                           "w_inplane": 0, "cancel_warn": 1.0, "work_eff_min": 0.5, "reg_modes": 0.1}},
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
    assert s["inputs"]["rank_metric"] == "jig"
    p = _job(engine, s["job"]["id"])["params"]["doe"]
    assert p["rank"] == SNAP and p["cfg"]["bead_doe"]["rank"]["metric"] == "jig"
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client)))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["inputs"]["rank_metric"] == "jig"
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
        want = {"metric": "solve", "lin_form": "taylor", "lin_valid": 0.5, "imbalance_warn": 0.1, "jig": JIG_DEFAULT,
                "schema": 2, "eval_region": EVAL_SNAP, "jig_grid": {**JIG_GRID_DEFAULT, "schema": 1}}
        assert s["inputs"]["rank_metric"] == "solve" and _job(engine, s["job"]["id"])["params"]["doe"]["rank"] == want
        finish_job(engine, s["job"]["id"])
        d2 = copy.deepcopy(d)
        d2["bead_doe"]["rank"] = {"metric": "lin"}
    with _app(tmp_path, engine, fake_dashboard, clock, d2) as c:
        r = c.post(f"{API}/doe/studies/{s['id']}/clone", json={}, headers=W)
        assert r.status_code == 201, r.text
        # v0.23.2 D-0.23.2-1: 복제 = 지금 설정으로 순위 설정 갱신(이전 v0.20.0~v0.23.1 은 원 값 유지)
        assert r.json()["inputs"]["rank_metric"] == "lin"
        j = _job(engine, r.json()["job"]["id"])
        assert j["params"]["doe"]["rank"] == {**SNAP, "metric": "lin"}
        assert [w for w in j["params"]["warnings"] if w.get("code") == "RANK_REFRESHED"] == \
            [{"code": "RANK_REFRESHED", "message": "순위 설정을 지금 설정으로 갱신했습니다(원 스터디 순위 지표 solve → lin)"}]


def test_clone_refreshes_old_rank_schema1(client, world, engine):
    """V-0232-1: 원 스냅샷 rank schema 1(metric solve, jig 없음 — v0.20.0~v0.22.x) → 복제 = 지금 설정 rank_snapshot(schema 2·jig),
    경고 RANK_REFRESHED 1개, load_transfer 유지(diag 만 갱신)·설계안 상태(doe) 없음 그대로. 같은 설정 재복제 = 경고 없음."""
    from sqlalchemy import text

    s = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], upload_step(client))).json()
    job = _job(engine, s["job"]["id"])
    params = copy.deepcopy(job["params"])
    params["doe"]["rank"] = {"metric": "solve", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02, "schema": 1}
    params["doe"]["load_transfer"]["method"] = "cell"
    inp = {**s["inputs"], "rank_metric": "solve"}
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(params), "i": job["id"]})
        c.execute(text("UPDATE bead_does SET inputs=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(inp), "i": s["id"]})
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 201, r.text
    cl = r.json()
    j = _job(engine, cl["job"]["id"])
    assert j["params"]["doe"]["rank"] == SNAP and cl["inputs"]["rank_metric"] == "jig"
    assert [w["code"] for w in j["params"]["warnings"]].count("RANK_REFRESHED") == 1
    assert "지그 계산 추가" in next(w["message"] for w in j["params"]["warnings"] if w["code"] == "RANK_REFRESHED")
    assert j["params"]["doe"]["load_transfer"]["method"] == "cell"                       # 다른 복제 정책 그대로
    assert not {"spec", "rev", "matrix_sha256", "design"} & set(j["params"]["doe"]) and cl["doe"] is None
    finish_job(engine, cl["job"]["id"])
    r2 = api(client, "POST", f"/doe/studies/{cl['id']}/clone", json={})                    # 이미 지금 설정 = 경고 없음
    assert r2.status_code == 201, r2.text
    j2 = _job(engine, r2.json()["job"]["id"])
    assert j2["params"]["doe"]["rank"] == SNAP and "RANK_REFRESHED" not in [w.get("code") for w in j2["params"]["warnings"]]


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
def _done(client, world, engine, esl_root, extra, rows=None, req=None):
    s = api(client, "POST", "/doe/studies", json=req or cbody(world, shapes3(client))).json()
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
    assert o["rank"] == {"metric": "jig", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02}   # 스터디 스냅샷(키 4개 그대로)
    assert o["C_ref_solve"] == 10.0 and o["n_failed"] == {"sm": 2} and o["ranking"][0]["C_solve"] == {"e1": 12.0}
    r0 = o["ranking"][0]
    assert {k: r0[k] for k in ("score_solve", "imbalance_max", "rho_min", "rho_max", "umax_def")} == {
        "score_solve": 1.4, "imbalance_max": 0.27, "rho_min": 0.9, "rho_max": 1.1, "umax_def": 2.5} and "C" not in r0
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl").json()["designs"][0]["per_esl"][0]
    assert pe["C_lin"] == 0.95 and pe["C_ritz"] == 0.97 and pe["rho"] == 1.05 and pe["imbalance_rel"] == 0.03
    assert pe["umax_def"] == 2.5 and pe["C_solve"] == 1.2


def test_results_cross_mesh_metric_effective(client, world, engine, esl_root):
    """결정 A(2026-11-13): ④·옛 ③ = 다른 메시 비교 — 코어 metric_effective solve·cross_mesh true 가 최상위와 rank{…} 에,
    경고 SM_CROSS_MESH 는 warnings 그대로. 같은 메시(① ②·새 ③) = metric_effective lin·cross_mesh false."""
    warn = {"code": "SM_CROSS_MESH", "message": "다른 메시 비교(정밀도 낮음)"}
    sid = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "C_ref_solve": 10.0,
                                                    "metric_effective": "solve", "cross_mesh": True, "warnings": [warn],
                                                    "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3,
                                                                 "umax_def": 0.4}})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["metric"] == "solve" and o["metric_effective"] == "solve" and o["cross_mesh"] is True and warn in o["warnings"]
    assert o["baseline"]["umax_def"] == 0.4                    # 강체 제거 umax(새 스냅샷) 통과
    assert o["rank"] == {"metric": "jig", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02,
                         "metric_effective": "solve", "cross_mesh": True}
    assert "n_fallback" not in o["rank"]                                     # ④ 불변(대체 없음)
    row = {"id": "d001", "values": {}, "score": 1.1, "improvement": -0.1, "worst_entry_id": "e1", "umax": 3.0,
           "epsmax": 1e-3, "rank": 1, "score_solve": 1.1, "basis": "solve", "sm_warn": ["SM_LIN_RANGE"]}
    sid2 = _done(client, world, engine, esl_root, {"metric": "lin", "lin_form": "ritz", "C_ref_solve": 10.0,
                                                     "metric_effective": "lin", "cross_mesh": False, "n_fallback": 1},
                 [row])
    o2 = api(client, "GET", f"/doe/studies/{sid2}/results").json()
    assert o2["metric_effective"] == "lin" and o2["cross_mesh"] is False and o2["rank"]["metric_effective"] == "lin"
    assert o2["rank"]["n_fallback"] == 1                                    # R-SM-1 결정: 재풀이 대체 안 수
    assert o2["ranking"][0]["basis"] == "solve" and o2["ranking"][0]["sm_warn"] == ["SM_LIN_RANGE"]


def test_results_legacy_null_metric(client, world, engine, esl_root):
    sid = _done(client, world, engine, esl_root, {})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["metric"] is None and o["lin_form"] is None and o["C_ref_solve"] is None
    assert o["metric_effective"] is None and o["cross_mesh"] is None and "umax_def" not in o["baseline"]


def test_settings_rank_block(client, world):
    s = api(client, "GET", "/doe/settings").json()
    assert s["rank"] == {"metric": "jig", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02}


def test_openapi_rank_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    props = spec["components"]["schemas"]["DoeResultOut"]["properties"]
    assert "metric" in props and "lin_form" in props and "metric_effective" in props and "cross_mesh" in props


# ================================================================ v0.23.0 지그 블록 통과(esl_jig_rank.md V-JIG-14)
JIG_BLOCK = {"status": "poor", "code": None, "region_source": "mixed", "n_jig": 12, "n_regions": 3, "n_contact": 1, "n_patch": 2,
             "fit_mac_min": 0.82, "fit_umax_err_max": 0.31, "fit_mac_min_nomodes": 0.6,
             "fit_umax_err_max_nomodes": 0.5, "cancel_rel_max": 0.1, "fit_work_eff_min": 0.9, "tie_rel_max": 0.02, "tie_spread": 0.15, "n_modes": 4,
             "hz_jig": [3.1, 5.2, 7.7, 9.9], "hz_321": [0.75, 1.5], "hz_ratio": 4.13,
             "th": {"mac_min": 0.9, "umax_err_max": 0.2, "tie_rel_warn": 0.1, "cancel_warn": 0.5, "work_eff_min": 0.05,
                    "tie_spread_min": 0.02},
             "entries": [{"entry_id": "e1", "label": "E1", "mac": 0.82, "umax_err": 0.31, "mac_nomodes": 0.6,
                          "umax_err_nomodes": 0.5, "err_p95": 0.2, "n_active": 2, "F_sum_abs": 410.0, "cancel_rel": 0.1,
                          "work_eff": 0.9, "rot_deg": 12.5}]}


def test_results_pass_jig_block(client, world, engine, esl_root):
    row = {"id": "d001", "values": {}, "score": 0.8, "improvement": 0.2, "worst_entry_id": "e1", "umax": 3.0, "epsmax": 1e-3,
           "rank": 1, "score_jig": 0.8, "umax_jig": 0.9, "C_jig": {"e1": 80.0}, "C": 80.0}
    sid = _done(client, world, engine, esl_root, {"metric": "jig", "lin_form": "ritz", "metric_effective": "jig",
                                                    "cross_mesh": False, "jig": JIG_BLOCK, "n_failed": {"jig": 1}}, [row])
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["metric"] == "jig" and o["metric_effective"] == "jig" and o["rank"]["metric_effective"] == "jig"
    assert o["jig"] == {**JIG_BLOCK, "methods": None, "tie_dofs": None, "transfer": None, "grid": None} \
        and o["n_failed"] == {"jig": 1}   # v0.24.6·v0.24.8 새 키 null
    r0 = o["ranking"][0]
    assert (r0["score_jig"], r0["umax_jig"], r0["C_jig"]) == (0.8, 0.9, {"e1": 80.0})
    sid2 = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "solve", "cross_mesh": True,
                                                     "jig": {**JIG_BLOCK, "status": "unsupported", "code": "JIG_UNSUPPORTED",
                                                             "region_source": None, "entries": [], "fit_mac_min": None,
                                                             "fit_umax_err_max": None, "tie_rel_max": None,
                                                             "fit_mac_min_nomodes": None, "fit_umax_err_max_nomodes": None,
                                                             "cancel_rel_max": None, "fit_work_eff_min": None, "n_modes": 0, "hz_jig": [],
                                                             "hz_321": None, "hz_ratio": None}})
    o2 = api(client, "GET", f"/doe/studies/{sid2}/results").json()
    assert o2["jig"]["status"] == "unsupported" and o2["jig"]["code"] == "JIG_UNSUPPORTED" and o2["metric_effective"] == "solve"


def test_results_legacy_null_jig(client, world, engine, esl_root):
    o = api(client, "GET", f"/doe/studies/{_done(client, world, engine, esl_root, {})}/results").json()
    assert o["jig"] is None
    sid = _done(client, world, engine, esl_root, {"metric": "lin", "lin_form": "ritz"})            # jig 블록 없는 스냅샷
    assert api(client, "GET", f"/doe/studies/{sid}/results").json()["jig"] is None


def test_openapi_jig_schemas():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    assert "jig" in sc["DoeResultOut"]["properties"]
    assert set(sc["DoeJigOut"]["properties"]) == {"status", "code", "region_source", "n_jig", "n_regions", "n_contact", "n_patch",
                                                  "fit_mac_min", "fit_umax_err_max", "fit_mac_min_nomodes",
                                                  "fit_umax_err_max_nomodes", "cancel_rel_max", "fit_work_eff_min", "tie_rel_max", "tie_spread",
                                                  "n_modes", "hz_jig", "hz_321", "hz_ratio", "th", "entries", "tie_dofs", "methods"}   # v0.24.6
    assert set(sc["DoeJigThOut"]["properties"]) == {"mac_min", "umax_err_max", "tie_rel_warn", "cancel_warn", "work_eff_min",
                                                         "tie_spread_min"}
    assert set(sc["DoeJigEntryOut"]["properties"]) == {"entry_id", "label", "mac", "umax_err", "mac_nomodes",
                                                       "umax_err_nomodes", "err_p95", "n_active", "F_sum_abs", "cancel_rel",
                                                       "work_eff", "rot_deg"}
    assert "jig" in json.dumps(sc["DoeResultOut"]["properties"]["metric"])


def test_rank_snapshot_jig_enabled_flag():
    """V-JIG-11: jig 켜짐 = {jig{설정 전체}, schema 2}, enabled false = jig 키 없음·schema 1(metric solve|lin 일 때만 허용)."""
    from esl_platform.api.services.doe import rank_snapshot
    from esl_platform.core.config import BeadDoeCfg

    on = rank_snapshot(BeadDoeCfg().model_dump())
    assert on == SNAP
    off_cfg = BeadDoeCfg.model_validate({"rank": {"metric": "solve", "jig": {"enabled": False}}}).model_dump()
    off = rank_snapshot(off_cfg)
    assert off == {"metric": "solve", "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02, "schema": 1,
                   "eval_region": EVAL_SNAP}


# ================================================================ v0.23.2 지그 미계산 표시·지그 3D 통과(esl_v0232_fixes.md §3·§4.3)
def _strip_rank(engine, sid):
    from sqlalchemy import text

    from esl_platform.core.db.tables import jobs as jobs_t

    with engine.begin() as c:
        for jid, params in c.execute(jobs_t.select().with_only_columns(jobs_t.c.id, jobs_t.c.params)
                                     .where(jobs_t.c.bead_doe_id == sid)).all():
            p = copy.deepcopy(params)
            p["doe"].pop("rank", None)
            c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(p), "i": jid})


def test_results_jig_on_clone(client, world, engine, esl_root):
    """V-0232-2: jig 블록 없는 결과 — rank 있음 ∧ 계획 sm_jig base(①) = true, ④ = false, rank 없음 = false, 블록 있으면 null."""
    same = body([world["a"], world["b"]], upload_step(client))
    sid = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"}, req=same)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["jig"] is None and o["jig_on_clone"] is True
    sid4 = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})          # ④ compare
    assert api(client, "GET", f"/doe/studies/{sid4}/results").json()["jig_on_clone"] is False
    sidl = _done(client, world, engine, esl_root, {}, req=body([world["a"], world["b"]], upload_step(client)))
    _strip_rank(engine, sidl)                                                                       # 옛 스냅샷(rank 없음)
    assert api(client, "GET", f"/doe/studies/{sidl}/results").json()["jig_on_clone"] is False
    sidj = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "jig", "cross_mesh": False,
                                                    "jig": JIG_BLOCK,
                                                    "view3d_jig": {"d001": "d001_jig"}, "view3d_jig_esl": {"d001": "e1"},
                                                    "view3d_jig_ref": {"e1": "d000_jig_e00"}}, req=same | {})
    oj = api(client, "GET", f"/doe/studies/{sidj}/results").json()
    assert oj["jig_on_clone"] is None and oj["view3d_jig"] == {"d001": "d001_jig"}
    assert oj["view3d_jig_esl"] == {"d001": "e1"} and oj["view3d_jig_ref"] == {"e1": "d000_jig_e00"}
    assert o["view3d_jig"] is None


def test_openapi_v0232_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    props = spec["components"]["schemas"]["DoeResultOut"]["properties"]
    assert {"view3d_jig", "view3d_jig_esl", "view3d_jig_ref", "jig_on_clone"} <= set(props)


def test_view3d_cfg_mirror():
    """V-0232-5: DEFAULTS["view3d"] == BeadDoeView3dCfg() == 두 예시 yaml(jig·jig_support_max)."""
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg

    want = {"top_k": 3, "jig": True, "jig_support_max": 64, "jig_diag": True, "jig_tie_gap_mm": 5.0, "regen_keep_backups": 1,   # v0.23.3
            "recon": True}                                                                    # v0.24.1 재현 진단(esl_view3d_sources.md §7)
    assert DEFAULTS["view3d"] == want and BeadDoeCfg().model_dump()["view3d"] == want
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert y["bead_doe"]["view3d"] == want, p


@pytest.mark.parametrize("bad", [{"jig_support_max": 0}, {"jig_support_max": 2001}, {"jig": "x"}])
def test_view3d_cfg_rejects(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "view3d": bad}
    lc = load_config_dict(d, environ={})
    assert not lc.ok and any(k.startswith("bead_doe.view3d") for k in lc.error_keys()), lc.errors()
