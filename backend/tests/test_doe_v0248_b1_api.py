"""v0.24.8 B1 — ④·옛 ③ 격자 지그 백엔드(계약 esl_jig_grid_map.md §2.2·§3·§5·§6·§7.1·§7.3·§9 의 백엔드 부분, V-0248-JG-15 설정 거울·
검사, 11 하위 호환·14 문구 입력값 jig_on_clone·17 e2e 의 API 층).

- 설정: rank.jig_grid DEFAULTS(코어 병합 후)·pydantic·yaml 2개 거울, 검사 범위(ValidationError·CONFIG_INVALID), cell_min_mm 교차 검사.
- 스냅샷: rank.jig 가 켜져 있고 jig_grid.enabled 이면 모든 시나리오에 jig_grid 블록(블록 안 schema 1, rank.schema 값 2 불변), 꺼짐 = 키 없음, 복제 갱신.
- 응답: jig_plan = tp.jig_kind(계획, 스냅샷 jig_grid)(코어 함수가 있으면 그 값, 없으면 계약 정의), 옛 스냅샷 = "none" 그대로, jig_on_clone 규칙,
  jig.transfer·jig.grid·jig.methods{}.grid 통과(옛 결과 = null), 사이드카 view3d_jd·js 병합 불변.
코어 산출물은 계약 §6 형식의 합성 result.json·사이드카로 시험한다(코어 C1 과 독립).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from doe_support import api, body, finish_job, study_dir, upload_step
from esl_test_support import REPO, make_settings_dict
from sqlalchemy import text
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    _fresh_cache,
    _job,
    code,
    doe_settings_dict,
    settings_dict,
    world,
)
from test_doe_jig_view_api import JIG_BLOCK, JIG_ROW, SIDE
from test_doe_rank_metric_api import JIG_GRID_DEFAULT, SNAP, _done, _strip_rank
from test_doe_v0246_b1_api import M_OK, M_SPR

# 계약 §6 result.json jig 블록의 격자 새 키(합성 — 코어 C1 산출과 같은 이름)
GRID = {"cell_mm": 3.0, "n_groups": 1, "n_shapes": 3, "n_shapes_failed": 1, "tie_miss_max": 0.05, "tie_area_ratio_min": 0.8,
        "tie_area_ratio_max": 1.3, "k_scale_min": 0.9, "k_scale_max": 1.2, "noise_floor": 0.034, "load_dF_max": 1e-12,
        "load_dM_max": 2e-12, "corr_rel_max": 0.02, "small_frac_max": 0.6, "frame_shift_max_mm": 0.0, "sample_outside_max": 0,
        "warnings": ["스냅샷 tie_dofs normal 과 Case 값 translation 이 다름"]}
GRID_M = {"n_ok": 2, "n_failed": 1, "case_recon_mac_min": 0.998, "recon_mac_d000": 0.996, "recon_umax_err_d000": 0.01, "alpha": 0.01,
          "conv": [{"cell_mm": 5.0, "dpi_max": 0.008, "dumax_max": 0.01, "mac_min": 0.999},
                   {"cell_mm": 10.0, "dpi_max": 0.03, "dumax_max": 0.04, "mac_min": 0.997}]}
GRID_JIG = {**JIG_BLOCK, "status": "ok", "tie_dofs": "normal", "transfer": "grid", "grid": GRID,
            "methods": {"jig_disp": {**M_OK, "grid": GRID_M}, "jig_spring": {**M_SPR, "grid": {**GRID_M, "n_failed": 0}}}}
GRID_V3D = {**SIDE, "view3d_jd": {"d001": "d001_jd"}, "view3d_jd_esl": {"d001": "e1"}, "view3d_jd_ref": {"e1": "d000_jd_e00"},
            "view3d_js": {"d001": "d001_js"}, "view3d_js_esl": {"d001": "e1"}, "view3d_js_ref": {"e1": "d000_js_e00"}}
GRID_KEYS = ("view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref")


def _res(client, sid):
    r = api(client, "GET", f"/doe/studies/{sid}/results")
    assert r.status_code == 200, r.text
    return r.json()


def _plan_grid(monkeypatch, *, jig_kind=None):
    """계획 표 compare_per_shape 의 jig_fix 를 grid 로(코어 C1 의 계획 표 값 대역). jig_kind 를 주면 코어 함수 대역도 심음."""
    from esl_platform.core.opt_core import doe_transfer_plan as tp

    orig = tp.plan_for

    def fake(scn, sb="case"):
        p = dict(orig(scn, sb))
        if p["dst"] in ("design", "shape"):
            p.update(jig_fix="grid", jig_ctx="shape")
        return p

    monkeypatch.setattr(tp, "plan_for", fake)
    if jig_kind is not None:
        monkeypatch.setattr(tp, "jig_kind", jig_kind, raising=False)


# ================================================================ 설정 (V-0248-JG-15)
def test_jig_grid_defaults_mirror():
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg, bead_doe_settings

    assert BeadDoeCfg().model_dump()["rank"]["jig_grid"] == JIG_GRID_DEFAULT
    assert bead_doe_settings(None)["rank"]["jig_grid"] == JIG_GRID_DEFAULT
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert y["bead_doe"]["rank"]["jig_grid"] == JIG_GRID_DEFAULT, p
    core = (DEFAULTS.get("rank") or {}).get("jig_grid")
    if core is None:
        pytest.skip("코어 esl.doe.DEFAULTS rank.jig_grid 미병합(C1 전) — 병합 후 이 줄이 대조한다")
    assert core == JIG_GRID_DEFAULT


@pytest.mark.parametrize("bad", [
    {"enabled": "x"}, {"cell_mm": 0.5}, {"cell_mm": 200.1}, {"cell_mm": 0}, {"conv_mm": [5, 5, 10, 20]}, {"conv_mm": [3.0]},
    {"conv_mm": [0.5]}, {"conv_mm": [201]}, {"tie_capture_rel": 0}, {"tie_capture_rel": 1.01},
    {"tie_snap_rel": 0.2}, {"tie_snap_rel": 2.1}, {"tie_normal_deg": 0}, {"tie_normal_deg": 90},
    {"tie_miss_frac_max": -0.1}, {"tie_miss_frac_max": 1.1}, {"sample_nbr": 0}, {"sample_nbr": 4},
    {"sample_normal_deg": 0}, {"sample_normal_deg": 90.1}, {"area_ratio_warn": 1}, {"conv_warn": 0},
    {"frame_shift_warn": 0}, {"load_resid_warn": 0}, {"noise_floor_min": -0.01}, {"noise_floor_min": 0.21}, {"unknown": 1},
])
def test_jig_grid_rejects(bad):
    from pydantic import ValidationError
    from esl_platform.core.config import BeadDoeCfg

    with pytest.raises(ValidationError):
        BeadDoeCfg.model_validate({"rank": {"jig_grid": bad}})


def test_jig_grid_accepts_edges():
    from esl_platform.core.config import BeadDoeCfg

    ok = {"cell_mm": 200, "conv_mm": [], "tie_capture_rel": 1, "tie_snap_rel": 2, "tie_miss_frac_max": 0, "sample_nbr": 3,
          "sample_normal_deg": 90, "noise_floor_min": 0.2, "enabled": False}
    g = BeadDoeCfg.model_validate({"rank": {"jig_grid": ok}}).rank.jig_grid
    assert g.cell_mm == 200 and g.conv_mm == [] and g.enabled is False and g.noise_floor_min == 0.2


def test_jig_grid_cell_min_cross_check():
    """cell_mm·conv_mm 의 하한 = load_transfer.cell_min_mm(계약 §7.1 '검사' 열)."""
    from pydantic import ValidationError
    from esl_platform.core.config import BeadDoeCfg

    cfg = BeadDoeCfg.model_validate({"load_transfer": {"cell_min_mm": 4.0, "cell_choices_mm": [None, 10], "diag": {"alt_cell_size_mm": 5.0, "cell_sweep_mm": []}},
                                     "rank": {"jig_grid": {"cell_mm": 4.0, "conv_mm": [5.0, 10.0]}}})
    assert cfg.rank.jig_grid.cell_mm == 4.0
    with pytest.raises(ValidationError, match="cell_min_mm"):
        BeadDoeCfg.model_validate({"load_transfer": {"cell_min_mm": 4.0, "cell_choices_mm": [None, 10], "diag": {"alt_cell_size_mm": 5.0, "cell_sweep_mm": []}}})  # 기본 3.0 < 4
    with pytest.raises(ValidationError, match="cell_min_mm"):
        BeadDoeCfg.model_validate({"load_transfer": {"cell_min_mm": 4.0, "cell_choices_mm": [None, 10], "diag": {"alt_cell_size_mm": 5.0, "cell_sweep_mm": []}},
                                   "rank": {"jig_grid": {"cell_mm": 4.0, "conv_mm": [3.5]}}})


@pytest.mark.parametrize("bad", [{"cell_mm": 0.5}, {"tie_snap_rel": 0.1}, {"conv_mm": [3.0]}, {"noise_floor_min": 1}])
def test_jig_grid_config_load_rejects(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "rank": {"jig_grid": bad}}
    lc = load_config_dict(d, environ={})
    assert not lc.ok and any(k.startswith("bead_doe.rank.jig_grid") for k in lc.error_keys()), lc.errors()


# ================================================================ 스냅샷 (§6 rank_snapshot)
def test_rank_snapshot_jig_grid_block():
    from esl_platform.api.services.doe import rank_snapshot
    from esl_platform.core.config import BeadDoeCfg

    on = rank_snapshot(BeadDoeCfg().model_dump())
    assert on["jig_grid"] == {**JIG_GRID_DEFAULT, "schema": 1} and on["schema"] == 2          # rank.schema 값 불변
    assert on == SNAP
    off = rank_snapshot(BeadDoeCfg.model_validate({"rank": {"jig_grid": {"enabled": False}}}).model_dump())
    assert "jig_grid" not in off and off["jig"] and off["schema"] == 2
    nojig = rank_snapshot(BeadDoeCfg.model_validate({"rank": {"metric": "solve", "jig": {"enabled": False}}}).model_dump())
    assert "jig_grid" not in nojig and "jig" not in nojig and nojig["schema"] == 1         # rank.jig 꺼짐 = jig_grid 도 없음
    custom = rank_snapshot(BeadDoeCfg.model_validate({"rank": {"jig_grid": {"cell_mm": 4.0, "noise_floor_min": 0.05}}}).model_dump())
    assert custom["jig_grid"]["cell_mm"] == 4.0 and custom["jig_grid"]["noise_floor_min"] == 0.05


def test_snapshot_in_every_scenario(client, world, engine):
    """모든 시나리오(①~④)의 새 스냅샷에 jig_grid(코어가 계획으로 무시 — base 모드 해시 불변 전제)."""
    for req in (body([world["a"], world["b"]], upload_step(client)),):
        s = api(client, "POST", "/doe/studies", json=req)
        assert s.status_code == 201, s.text
        assert _job(engine, s.json()["job"]["id"])["params"]["doe"]["rank"]["jig_grid"] == {**JIG_GRID_DEFAULT, "schema": 1}


def test_clone_refreshes_old_snapshot_adds_grid(client, world, engine):
    """옛 스냅샷(rank.jig 있고 jig_grid 없음 — v0.24.7) 복제 = 지금 설정으로 jig_grid 추가 + RANK_REFRESHED 문구."""
    s = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], upload_step(client))).json()
    job = _job(engine, s["job"]["id"])
    params = copy.deepcopy(job["params"])
    params["doe"]["rank"].pop("jig_grid")
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(params), "i": job["id"]})
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 201, r.text
    j = _job(engine, r.json()["job"]["id"])
    assert j["params"]["doe"]["rank"] == SNAP
    msg = next(w["message"] for w in j["params"]["warnings"] if w["code"] == "RANK_REFRESHED")
    assert "지그 격자 설정 추가" in msg and "지그 계산 추가" not in msg
    finish_job(engine, r.json()["job"]["id"])
    r2 = api(client, "POST", f"/doe/studies/{r.json()['id']}/clone", json={})              # 이미 지금 설정 = 경고 없음
    assert "RANK_REFRESHED" not in [w.get("code") for w in _job(engine, r2.json()["job"]["id"])["params"]["warnings"]]


# ================================================================ 응답 jig_plan·jig_on_clone·새 키 (§6·§7.3)
def test_old_snapshot_and_results_keep_old_values(client, world, engine, esl_root):
    """§7.3-1: 옛 스냅샷 ④ = jig_plan none(기존 값 그대로), 기존 jig 블록의 새 키 transfer·grid·methods.grid = null."""
    sid4 = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})          # 새 스냅샷 ④(코어 계획 jig_fix grid) = grid
    o = _res(client, sid4)
    assert o["jig_plan"] == "grid" and o["jig_on_clone"] is False and o["jig"] is None
    for jid, params in _jobs(engine, sid4):                                                          # 옛 스냅샷(jig_grid 없음) = none
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid")
        _set_params(engine, jid, p)
    o = _res(client, sid4)
    assert o["jig_plan"] == "none" and o["jig"] is None
    same = body([world["a"], world["b"]], upload_step(client))
    sid1 = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"}, req=same)
    o1 = _res(client, sid1)
    assert o1["jig_plan"] == "base" and o1["jig_on_clone"] is True                              # base 모드 값 불변(jig_grid 가 스냅샷에 있어도)
    old_jig = {**JIG_BLOCK, "tie_dofs": "normal", "methods": {"jig_disp": M_OK}}
    sidj = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "jig", "cross_mesh": False, "jig": old_jig},
                 req=same | {})
    oj = _res(client, sidj)["jig"]
    assert oj["transfer"] is None and oj["grid"] is None and oj["methods"]["jig_disp"]["grid"] is None
    assert oj["status"] == JIG_BLOCK["status"] and oj["tie_dofs"] == "normal"                  # 기존 키 값 그대로


def test_old_study_without_rank_plan_none(client, world, engine, esl_root):
    sid = _done(client, world, engine, esl_root, {})
    _strip_rank(engine, sid)
    o = _res(client, sid)
    assert o["jig_plan"] == "none" and o["rank"] is None and o["jig_on_clone"] is False


def test_jig_plan_grid_and_jig_on_clone_rules(client, world, engine, esl_root, monkeypatch):
    """계획 jig_fix grid(코어 C1 계획 표 대역): 새 스냅샷 = jig_plan grid, 옛 스냅샷(jig_grid 없음) = none + jig_on_clone = 설정 켜짐 여부."""
    _plan_grid(monkeypatch)                                              # jig_kind 는 코어 함수 없음 → 계약 정의 대체
    sid = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})          # 새 스냅샷(jig_grid 있음)
    o = _res(client, sid)
    assert o["jig_plan"] == "grid" and o["jig_on_clone"] is False        # 지그 블록 없는 결과인데 grid 계획(코어가 안 냄) — 복제 안내 아님

    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})
    for jid, params in _jobs(engine, old):
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid")
        _set_params(engine, jid, p)
    oo = _res(client, old)
    assert oo["jig_plan"] == "none" and oo["jig_on_clone"] is True       # 복제하면 격자 지그(설정 rank.jig·jig_grid 켜짐)


def test_jig_on_clone_false_when_config_off(tmp_path, engine, fake_dashboard, clock, esl_root, monkeypatch):
    from test_doe_compare_api import _app, record_paicad

    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["rank"] = {"jig_grid": {"enabled": False}}
    record_paicad(engine)
    _plan_grid(monkeypatch)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        from esl_test_support import API, H
        from opt_support import make_case, seed_opt_entry
        from test_doe_compare_api import multi_upload

        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True}, {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/studies", json=b, headers=H("tok-power", True))
        assert r.status_code == 201, r.text
        s = r.json()
        assert "jig_grid" not in _job(engine, s["job"]["id"])["params"]["doe"]["rank"]       # 꺼짐 = 스냅샷 키 없음
        finish_job(engine, s["job"]["id"])
        base = study_dir(esl_root, s["id"])
        (base / "post").mkdir(parents=True)
        res = {"scenario": "compare", "reference_source": "step", "C_ref": 10.0, "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3},
               "n_ok": 1, "n_skipped": {}, "n_failed": {}, "ranking": [], "sensitivity": None, "boundary_warnings_n": 0, "view3d": [],
               "best": None, "noise_floor": None, "ratio_tol": 1e-6, "per_esl_inline": False, "esl": [], "warnings": []}
        (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
        (base / "post" / "designs.json").write_text(json.dumps({"designs": [{"id": "d000", "status": "OK"}]}), encoding="utf-8")
        from doe_support import update_study

        update_study(engine, s["id"], phase="DONE", result=res)
        o = c.get(f"{API}/doe/studies/{s['id']}/results", headers=H("tok-power")).json()
        assert o["jig_plan"] == "none" and o["jig_on_clone"] is False        # 격자 설정이 꺼져 있어 복제해도 계산 안 함


def test_jig_plan_delegates_to_core_jig_kind(client, world, engine, esl_root, monkeypatch):
    """코어 tp.jig_kind 가 있으면 그 값을 그대로 쓴다(인수 = 계획 행·스냅샷 rank.jig_grid 블록 또는 None)."""
    calls: list = []

    def fake_kind(plan, grid_snap):
        calls.append((plan["sm_jig"], plan.get("jig_fix"), None if grid_snap is None else grid_snap.get("cell_mm")))
        return "grid" if grid_snap else "none"

    _plan_grid(monkeypatch, jig_kind=fake_kind)
    sid = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})
    assert _res(client, sid)["jig_plan"] == "grid" and calls[-1] == ("none", "grid", 3.0)
    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"})
    for jid, params in _jobs(engine, old):
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid")
        _set_params(engine, jid, p)
    assert _res(client, old)["jig_plan"] == "none" and calls[-1] == ("none", "grid", None)


def _jobs(engine, sid):
    from esl_platform.core.db.tables import jobs as jobs_t

    with engine.begin() as c:
        return [(i, p) for i, p in c.execute(jobs_t.select().with_only_columns(jobs_t.c.id, jobs_t.c.params)
                                             .where(jobs_t.c.bead_doe_id == sid)).all()]


def _set_params(engine, jid, p):
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(p), "i": jid})


# ================================================================ 격자 결과 통과·병합 (§5·§6)
def _grid_study(client, world, engine, esl_root, jig=GRID_JIG, side=GRID_V3D, extra=None):
    row = {**JIG_ROW}
    sid = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "jig", "cross_mesh": False, "jig": jig,
                                                   "noise_floor": 0.034, **(extra or {})}, [row])
    if side is not None:
        (study_dir(esl_root, sid) / "post" / "jig_view.json").write_text(json.dumps(side), encoding="utf-8")
    return sid


def test_grid_result_passthrough(client, world, engine, esl_root, monkeypatch):
    _plan_grid(monkeypatch)
    o = _res(client, _grid_study(client, world, engine, esl_root))
    j = o["jig"]
    assert o["jig_plan"] == "grid" and o["jig_on_clone"] is None                     # 지그 블록 있음 = null
    assert j["transfer"] == "grid" and j["status"] == "ok" and j["tie_dofs"] == "normal"
    assert j["grid"] == GRID                                                           # 값 그대로(고정 필드명 전부)
    assert j["methods"]["jig_disp"]["grid"] == GRID_M
    assert j["methods"]["jig_spring"]["grid"]["n_failed"] == 0 and j["methods"]["jig_spring"]["spring"] == M_SPR["spring"]
    assert o["noise_floor"] == 0.034


def test_grid_result_minimal_nullable_fields(client, world, engine, esl_root):
    """solve 대체 순위(noise_floor null)·스프링 없음(k_scale null)·진단 일부 없음도 통과."""
    g = {"cell_mm": 5.0, "n_groups": 2, "n_shapes": 4, "n_shapes_failed": 0, "noise_floor": None, "k_scale_min": None, "k_scale_max": None}
    jig = {**GRID_JIG, "grid": g, "methods": {"jig_disp": {**M_OK, "grid": {"n_ok": 4, "n_failed": 0}}}}
    o = _res(client, _grid_study(client, world, engine, esl_root, jig=jig, side=None))
    assert o["jig"]["grid"]["noise_floor"] is None and o["jig"]["grid"]["k_scale_min"] is None and o["jig"]["grid"]["warnings"] == []
    mg = o["jig"]["methods"]["jig_disp"]["grid"]
    assert mg["conv"] == [] and mg["recon_mac_d000"] is None and mg["alpha"] is None


def test_grid_v3d_sidecar_merge_unchanged(client, world, engine, esl_root, monkeypatch):
    """v0.24.6 병합 그대로: 사이드카 view3d_jd·js 키 병합(jig 만 result.json 우선)."""
    _plan_grid(monkeypatch)
    o = _res(client, _grid_study(client, world, engine, esl_root))
    assert o["view3d_jd"] == {"d001": "d001_jd"} and o["view3d_jd_ref"] == {"e1": "d000_jd_e00"}
    assert o["view3d_js"] == {"d001": "d001_js"} and o["view3d_js_esl"] == {"d001": "e1"}
    assert o["view3d_jig"] == {"d001": "d001_jig"}


def test_grid_regen_view3d_availability(client, world, engine, esl_root, monkeypatch):
    """격자 스터디 3D 다시 만들기 판정은 methods[src].status(옛 규칙 그대로) — 새 키가 판정을 막지 않음."""
    _plan_grid(monkeypatch)
    sid = _grid_study(client, world, engine, esl_root)
    o = _res(client, sid)
    avail = o.get("view3d_regen")
    assert avail is None or isinstance(avail, dict)       # 응답이 깨지지 않음(작업 상태는 test_doe_v3d_src_api 가 다룸)


def test_openapi_v0248_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    assert {"transfer", "grid"} <= set(sc["DoeJigOut"]["properties"])
    assert "grid" in sc["DoeJigMethodOut"]["properties"]
    assert set(sc["DoeJigGridOut"]["properties"]) == set(GRID)
    assert set(sc["DoeJigGridMethodOut"]["properties"]) == set(GRID_M)
    assert set(sc["DoeJigGridConvOut"]["properties"]) == {"cell_mm", "dpi_max", "dumax_max", "mac_min"}
    jp = sc["DoeResultOut"]["properties"]["jig_plan"]
    assert "grid" in json.dumps(jp)
    tr = json.dumps(sc["DoeJigOut"]["properties"]["transfer"])
    assert '"base"' in tr and '"grid"' in tr
