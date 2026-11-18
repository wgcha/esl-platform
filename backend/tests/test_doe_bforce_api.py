"""v0.24.0 경계력 ESL API(계약 esl_bforce.md §6·§7, V-0240-k): 사이드카 병합·per-esl view=bforce·추가 계산 작업·설정 거울."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from doe_support import api, finish_job, study_dir
from esl_test_support import REPO
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
from test_doe_jig_view_api import _run_job
from test_doe_rank_metric_api import _done

BVIEW = {"metric": "bf", "C_ref": 3.0, "baseline": {"id": "d000", "score": 1.0, "umax": 0.8, "epsmax": 2e-4, "worst_entry_id": "e1"},
         "n_ok": 1, "n_skipped": {}, "n_failed": {"bf": 0}, "per_esl_inline": False, "sensitivity": None,
         "sensitivity_reason": "TOO_FEW", "best_clean": None,
         "ranking": [{"id": "d001", "rank": 1, "score": 0.85, "worst_entry_id": "e1", "umax": 0.7, "epsmax": 1.8e-4}]}
BLOCK = {"status": "ok", "code": None, "reason": None, "grade_min": "contact",
         "entries": [{"entry_id": "e1", "label": "E1", "grade": "contact", "mass_source": "deck", "source": "/c/04_esl",
                      "eq_force_rel": 0.12, "eq_moment_rel": 0.03, "abar_g": 41.0, "corr_rel": 0.2, "recon_mac": 0.97,
                      "recon_umax_err": -0.04, "reaction_rel": 1e-12, "limits": ["BF_TIE_MISSING"], "reason": None}],
         "limits": ["BF_TIE_MISSING"], "limit_text": ["tie 체결력 미포함 — 조립 부품 하중 누락"], "n_designs": 2, "n_failed": 0}
BSIDE = {"schema": "esl/doe_bforce_view/1", "source": "add", "settings": {"enabled": True}, "bforce": BLOCK,
         "rank_views": {"bforce": BVIEW}, "view3d_bf": {"d001": "d001_bf"}, "view3d_bf_esl": {"d001": "e1"},
         "view3d_bf_ref": {"e1": "d000_bf_e00"},
         "per_esl": {"bforce": {"d001": [{"entry_id": "e1", "C": 2.55, "ratio": 0.85, "umax": 0.7, "epsmax": 1.8e-4}]}},
         "warnings": []}


def _bf_done(client, world, engine, esl_root, mp, side=BSIDE, plan="base", run=True):
    """테스트 스터디는 ④(compare) 행 — 계획 열 bf 만 바꿔 같은 메시 계획처럼(시나리오 열 제약 그대로)."""
    from esl_platform.api.services import doe as svc

    sid = _done(client, world, engine, esl_root, {})
    mp.setattr(svc, "_plan_bf", lambda s: plan)
    if side is not None:
        (study_dir(esl_root, sid) / "post" / "bforce_view.json").write_text(json.dumps(side), encoding="utf-8")
    if run:
        _run_job(engine, sid)
    return sid


def test_results_merge_bforce_sidecar(client, world, engine, esl_root, monkeypatch):
    sid = _bf_done(client, world, engine, esl_root, monkeypatch)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["bforce"]["grade_min"] == "contact" and o["bforce"]["limit_text"] == BLOCK["limit_text"]
    assert o["bforce"]["entries"][0]["recon_mac"] == 0.97
    assert o["rank_views"]["bforce"]["metric"] == "bf" and o["rank_views"]["jig"] is None
    assert o["view3d_bf"] == {"d001": "d001_bf"} and o["view3d_bf_ref"] == {"e1": "d000_bf_e00"}
    assert o["bforce_add"] == {"available": True, "allowed": True, "reason": None}
    o2 = api(client, "GET", f"/doe/studies/{sid}/results", token="tok-power2").json()
    assert not o2["bforce_add"]["allowed"] and "경계력 ESL 을 계산할" in o2["bforce_add"]["reason"]


def test_results_without_bforce_and_compare_plan(client, world, engine, esl_root):
    sid = _done(client, world, engine, esl_root, {})                                  # ④ = 계획 bf none
    _run_job(engine, sid)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["bforce"] is None and o["view3d_bf"] is None and o["rank_views"] is None and o["bforce_add"] is None
    r = api(client, "POST", f"/doe/studies/{sid}/sources/bforce")
    assert r.status_code == 409 and code(r) == "BF_UNSUPPORTED"


def test_per_esl_view_bforce(client, world, engine, esl_root, monkeypatch):
    sid = _bf_done(client, world, engine, esl_root, monkeypatch)
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=bforce").json()
    assert pe["designs"][0]["per_esl"][0]["C"] == 2.55
    r = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=jig")
    assert r.status_code == 409 and code(r) == "RESULT_NOT_READY"                       # 지그 사이드카 없음


def test_add_bforce_queues_run_from_post(client, world, engine, esl_root, monkeypatch):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_platform.core.repositories import jobs as jobs_repo

    sid = _bf_done(client, world, engine, esl_root, monkeypatch, side=None, run=False)
    r = api(client, "POST", f"/doe/studies/{sid}/sources/bforce")
    assert r.status_code == 409 and code(r) == "BF_ADD_UNAVAILABLE"                     # 성공한 실행 작업 없음
    _run_job(engine, sid)
    assert api(client, "POST", f"/doe/studies/{sid}/sources/bforce", token="tok-power2").status_code == 403
    r = api(client, "POST", f"/doe/studies/{sid}/sources/bforce")
    assert r.status_code == 202, r.text
    jid = r.json()["job"]["id"]
    with engine.connect() as c:
        job = jobs_repo.get_job(c, jid)
        steps = jobs_repo.get_steps(c, jid)
        s = doe_repo.get_study(c, sid)
    assert job["job_type"] == "DOE_RUN" and job["params"]["kind"] == "BFORCE"
    assert job["params"]["doe"]["post_mode"] == "bforce" and job["params"]["doe"]["bforce_cfg"]["enabled"] is True
    assert [(x["step_key"], x["state"]) for x in steps] == [("BD_BASELINE", "SKIPPED"), ("BD_DESIGNS", "SKIPPED"),
                                                            ("BD_POST", "PENDING"), ("BD_REGISTER", "PENDING")]
    assert s["phase"] == "DONE"
    r = api(client, "POST", f"/doe/studies/{sid}/sources/bforce")
    assert r.status_code == 409 and code(r) == "JOB_ACTIVE"
    finish_job(engine, jid)


def test_openapi_v0240_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    assert {"bforce", "bforce_add", "view3d_bf", "view3d_bf_esl", "view3d_bf_ref"} <= set(sc["DoeResultOut"]["properties"])
    assert {"DoeBforceOut", "DoeBforceEntryOut"} <= set(sc) and "bforce" in sc["DoeRankViewsOut"]["properties"]
    assert "/doe/studies/{sid}/sources/bforce" in json.dumps(spec["paths"])


def test_bforce_cfg_mirror():
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg

    assert DEFAULTS["bforce"] == BeadDoeCfg().model_dump()["bforce"] == {"enabled": True, "grades": ["full", "fint", "contact"],
                                                                         "view3d": True}
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        assert yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]["bforce"] == DEFAULTS["bforce"]
