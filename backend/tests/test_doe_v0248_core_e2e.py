"""v0.24.8 통합 — 백엔드 ↔ 실제 코어(대역 아님): 합성 Case 지그 + ④ 형상 3개 → BD_LOADS → BD_EVAL → BD_POST 산출물을 스터디 폴더에 놓고
GET /results 까지(계약 esl_jig_grid_map.md §3·§5·§6). jig_kind 코어 함수 = 백엔드 대체 계산, 옛 스냅샷 안내 줄 JIG_GRID_ON_CLONE."""

from __future__ import annotations

import copy
import itertools
import json
import shutil
import sys
from pathlib import Path

import pytest
from doe_support import api, finish_job, study_dir, update_study
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    _app,
    _fresh_cache,
    _job,
    cbody,
    code,
    doe_settings_dict,
    settings_dict,
    shapes3,
    world,
)
from test_doe_rank_metric_api import _done, _strip_rank
from test_doe_v0248_b1_api import _jobs, _res, _set_params

_CORE_TESTS = str(Path(__file__).resolve().parents[2] / "tests" / "doe")
if _CORE_TESTS not in sys.path:
    sys.path.insert(0, _CORE_TESTS)

import synth_jig_grid as G  # noqa: E402

SHAPES = (("d001", {"h": 4.0, "tri_cols": 6, "node_base": 100001}),
          ("d002", {"h": 3.0, "tri_cols": 5, "node_base": 200001}),
          ("d003", {"h": 5.0, "bead": (60.0, 90.0, 4.0)}))


def _fallback_kind(plan, grid_snap):
    """백엔드 대체 계산(코어 함수가 없을 때의 계약 정의)."""
    if plan["sm_jig"] == "base":
        return "base"
    return "grid" if plan.get("jig_fix") == "grid" and grid_snap else "none"


# ================================================================ jig_kind: 백엔드 = 코어 함수
def test_backend_jig_kind_calls_core_and_matches_fallback(monkeypatch):
    from esl_platform.api.services import doe as svc
    from esl_platform.core.opt_core import doe_transfer_plan as tp

    called = []
    orig = tp.jig_kind
    monkeypatch.setattr(tp, "jig_kind", lambda p, g: called.append(1) or orig(p, g))
    n = 0
    for scn, sb in itertools.product(("same", "step", "compare", "select"), ("case", "mesh", "step")):
        try:
            plan = tp.plan_for(scn, sb)
        except Exception:  # noqa: BLE001 - 없는 조합
            continue
        for snap in (None, {"enabled": True, "cell_mm": 3.0}):
            assert svc._jig_kind(plan, snap) == _fallback_kind(plan, snap), (scn, sb, snap)
            n += 1
    assert n >= 4 and len(called) == n                       # 백엔드가 코어 함수를 부른다


# ================================================================ 실제 코어 산출물 → /results
@pytest.fixture(scope="module")
def core_out(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("jgint"))
    doe, out, _A = G.cmp_world(root, rank=G.rank_snap(grid=True), shapes=SHAPES)
    G.run_cmp(doe, out)
    return Path(out)


def test_grid_end_to_end_results(client, world, engine, esl_root, core_out):  # noqa: F811
    sid = _done(client, world, engine, esl_root, {})
    base = study_dir(esl_root, sid)
    shutil.rmtree(base / "post")
    shutil.copytree(core_out / "post", base / "post")
    res = json.loads((core_out / "post" / "result.json").read_text(encoding="utf-8"))
    update_study(engine, sid, phase="DONE", result=res)
    o = _res(client, sid)
    assert o["jig_plan"] == "grid" and o["jig_on_clone"] is None
    assert o["metric_effective"] == "jd" and o["cross_mesh"] is True
    j = o["jig"]
    assert j["transfer"] == "grid" and j["status"] in ("ok", "poor")
    g = j["grid"]                                              # n_shapes = 형상 3 + 기준 d000
    assert g["cell_mm"] == 3.0 and g["n_shapes"] == 4 and g["n_shapes_failed"] == 0
    assert isinstance(g["warnings"], list) and all(isinstance(x, str) for x in g["warnings"])
    for key in ("tie_miss_max", "tie_area_ratio_min", "tie_area_ratio_max", "noise_floor"):
        assert g[key] is not None
    jd = j["methods"]["jig_disp"]
    assert jd["status"] == "ok" and jd["grid"]["n_ok"] >= 1 and jd["grid"]["recon_mac_d000"] is not None
    assert [c["cell_mm"] for c in jd["grid"]["conv"]] == [5.0, 10.0]
    # 순위 행: noise 행 존재, 격자 순위 noise_floor = 진단 noise_floor
    assert o["noise_floor"] == g["noise_floor"] >= 0.03
    assert any(r.get("noise") is True for r in o["ranking"]), o["ranking"]
    # 격자 순위 보기 jd·js, 3D 키
    rv = o["rank_views"]
    assert {"jig_disp", "jig_spring"} <= set(rv)                               # 코어 RANK_SOURCES 키(순위 지표 이름 jd·js)
    assert rv["jig_disp"]["metric"] == "jd" and rv["jig_spring"]["metric"] == "js"
    assert all(r["score"] is not None for r in rv["jig_disp"]["ranking"])
    for k in ("view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref"):
        assert isinstance(o[k], dict) and o[k], k
    # 경고: JIG_GRID_* = {code, message} dict, 머리·영문 꼬리 없음
    gw = [w for w in o["warnings"] if isinstance(w, dict) and str(w.get("code", "")).startswith("JIG_GRID_")]
    assert any(w["code"] == "JIG_GRID_RANK" for w in gw)
    for w in gw:
        assert isinstance(w["message"], str) and not w["message"].startswith("JIG_GRID_") and "(Info" not in w["message"]
    assert not any(w["code"] == "JIG_GRID_ON_CLONE" for w in o["warnings"] if isinstance(w, dict))


def test_grid_source_missing_schema(client, world, engine, esl_root, tmp_path):  # noqa: F811
    """Case 에 지그 결과가 없으면 JIG_GRID_SOURCE_MISSING{entry·entry_id·method·reason} dict, 순위 = solve(metric_effective solve)."""
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True), shapes=SHAPES[:2], case=False)
    G.run_cmp(doe, out)
    sid = _done(client, world, engine, esl_root, {})
    base = study_dir(esl_root, sid)
    shutil.rmtree(base / "post")
    shutil.copytree(Path(out) / "post", base / "post")
    res = json.loads((Path(out) / "post" / "result.json").read_text(encoding="utf-8"))
    update_study(engine, sid, phase="DONE", result=res)
    o = _res(client, sid)
    miss = [w for w in o["warnings"] if isinstance(w, dict) and w.get("code") == "JIG_GRID_SOURCE_MISSING"]
    assert miss, o["warnings"]
    for w in miss:
        assert {"entry", "entry_id", "method", "reason", "message"} <= set(w)
    assert o["metric_effective"] == "solve"


# ================================================================ 옛 ④·옛 ③ 스터디 안내 줄 JIG_GRID_ON_CLONE
def _on_clone(o):
    return [w for w in o["warnings"] if isinstance(w, dict) and w.get("code") == "JIG_GRID_ON_CLONE"]


def test_on_clone_warning_old_only(client, world, engine, esl_root):  # noqa: F811
    new = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "warnings": []})   # 새 스냅샷(grid)
    o = _res(client, new)
    assert o["jig_plan"] == "grid" and _on_clone(o) == []
    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "warnings": []})
    for jid, params in _jobs(engine, old):
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid")
        _set_params(engine, jid, p)
    before = (study_dir(esl_root, old) / "post" / "result.json").read_bytes()
    o = _res(client, old)
    w = _on_clone(o)
    assert o["jig_plan"] == "none" and o["jig_on_clone"] is True and len(w) == 1
    assert w[0]["message"] == "이 스터디는 지그 ESL 없이 계산됐습니다 — 복제하면 Case 지그를 격자 매핑해 계산합니다" and w[0]["level"] == "info"
    assert (study_dir(esl_root, old) / "post" / "result.json").read_bytes() == before        # 산출물 바이트 불변(응답 때만)
    assert _on_clone(_res(client, old)) == w                                                  # 두 번 불러도 1건(저장 안 함)


def test_on_clone_warning_absent_for_base_and_rankless(client, world, engine, esl_root):  # noqa: F811
    from test_doe_rank_metric_api import body, upload_step  # noqa: F401

    same = body([world["a"], world["b"]], upload_step(client))                               # ① ② 같은 메시 = base 모드
    sid = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz"}, req=same)
    o = _res(client, sid)
    assert o["jig_plan"] == "base" and _on_clone(o) == []
    old = _done(client, world, engine, esl_root, {})
    _strip_rank(engine, old)
    o = _res(client, old)
    assert o["jig_plan"] == "none" and o["jig_on_clone"] is False and _on_clone(o) == []


def test_on_clone_warning_absent_when_config_off(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    from esl_platform.api.services import doe as svc

    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "warnings": []})
    for jid, params in _jobs(engine, old):
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid")
        _set_params(engine, jid, p)
    assert len(_on_clone(_res(client, old))) == 1
    monkeypatch.setattr(svc, "_jig_on_clone", lambda *a, **k: False)                          # 설정 꺼짐 = jig_on_clone 거짓
    o = _res(client, old)
    assert o["jig_on_clone"] is False and _on_clone(o) == []


# v0.24.8 fix(D-0.24.8-JG-21): 실제 코어 `_jig_post_fixed` 가 옛 ④·옛 ③ 스냅샷(rank.jig 있음)에 쓰는 지그 블록 — 검증 때 코어 산출 result.json 에서 그대로 옮김.
# 앞 시험들은 지그 블록 없는 결과로만 확인해 이 형태(블록 있음 ∧ status unsupported)에서 jig_on_clone 이 null 로 남는 결함을 놓쳤다.
UNSUP_JIG = json.loads('{"status": "unsupported", "code": "JIG_UNSUPPORTED", "region_source": null, "n_jig": 0, "n_regions": 0, "n_contact": 0, "n_patch": 0, "fit_mac_min": null, "fit_umax_err_max": null, "fit_mac_min_nomodes": null, "fit_umax_err_max_nomodes": null, "cancel_rel_max": null, "fit_work_eff_min": null, "tie_rel_max": null, "tie_spread": null, "n_modes": 0, "hz_jig": [], "hz_321": null, "hz_ratio": null, "th": {"mac_min": 0.9, "umax_err_max": 0.2, "tie_rel_warn": 0.1, "cancel_warn": 0.5, "work_eff_min": 0.05, "tie_spread_min": 0.02}, "entries": [], "tie_dofs": "normal", "methods": {"jig_disp": {"method": "prescribed", "method_name": "강제 변위", "tie_dofs": "normal", "status": "fallback", "code": "JIG_SKIPPED", "detail": null, "fit_mac_min": null, "fit_umax_err_max": null, "warnings": [], "limits": [], "n_jig": 0, "bc": null, "spring": null}, "jig_spring": {"method": "spring", "method_name": "스프링", "tie_dofs": "normal", "status": "fallback", "code": "JIG_SKIPPED", "detail": null, "fit_mac_min": null, "fit_umax_err_max": null, "warnings": [], "limits": [], "n_jig": 0, "bc": null, "spring": null}}}')


def _old_snapshot(engine, sid):
    for jid, params in _jobs(engine, sid):
        p = copy.deepcopy(params)
        p["doe"]["rank"].pop("jig_grid", None)
        _set_params(engine, jid, p)


def test_on_clone_with_core_unsupported_block_old_compare(client, world, engine, esl_root):  # noqa: F811
    """옛 ④: 결과에 코어 jig{status: unsupported} 블록이 있어도 jig_on_clone 참 + ON_CLONE 1건, 블록은 그대로 통과."""
    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "warnings": [], "jig": UNSUP_JIG})
    _old_snapshot(engine, old)
    o = _res(client, old)
    assert o["jig_plan"] == "none" and o["jig"]["status"] == "unsupported" and o["jig_on_clone"] is True
    assert len(_on_clone(o)) == 1 and _on_clone(_res(client, old)) == _on_clone(o)


def test_on_clone_with_core_unsupported_block_old_step(client, world, engine, esl_root):  # noqa: F811
    """옛 ③(scenario step, 계획 step_per_design): 같은 규칙 — 탭 사유 문구 입력 jig_on_clone 참(화면 = "복제하면 … 격자 매핑")."""
    from doe_support import body, upload_step

    req = body([world["a"]], upload_step(client), scenario="step")
    old = _done(client, world, engine, esl_root, {"scenario": "step", "metric": "solve", "lin_form": "ritz", "warnings": [], "jig": UNSUP_JIG},
                req=req)
    _old_snapshot(engine, old)
    o = _res(client, old)
    assert o["jig_plan"] == "none" and o["jig_on_clone"] is True and len(_on_clone(o)) == 1


def test_on_clone_with_core_unsupported_block_config_off(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    """설정 rank.jig_grid 꺼짐(복제해도 계산 안 함) = jig_on_clone 거짓 · ON_CLONE 없음 — 블록이 있어도 null 이 아님."""
    old = _done(client, world, engine, esl_root, {"metric": "solve", "lin_form": "ritz", "warnings": [], "jig": UNSUP_JIG})
    _old_snapshot(engine, old)
    from esl_platform.api.services import doe as svc

    orig = svc.cfg
    monkeypatch.setattr(svc, "cfg", lambda ctx: _cfg_grid_off(orig(ctx)))
    o = _res(client, old)
    assert o["jig_plan"] == "none" and o["jig_on_clone"] is False and _on_clone(o) == []


def _cfg_grid_off(c):
    c = copy.deepcopy(c)
    c["rank"] = {**c["rank"], "jig_grid": {**(c["rank"].get("jig_grid") or {}), "enabled": False}}
    return c
