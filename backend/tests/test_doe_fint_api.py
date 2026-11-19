"""v0.24.0 보완 내력 ESL·평가 영역 API(계약 esl_fint.md §5.2·§6.2·§7, V-0240-F-i): fint 사이드카 병합·per-esl view=fint·
sources/{src} 일반화(fint 202·모르는 출처 404)·평가 영역 스냅샷·설정 거울."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml
from doe_support import api, finish_job, study_dir
from esl_test_support import REPO
from test_doe_bforce_api import BLOCK, BSIDE, BVIEW, _bf_done
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

FBLOCK = {**copy.deepcopy(BLOCK), "source": "fint", "grade_min": "fint", "limits": [], "limit_text": []}
FBLOCK["entries"][0].update(grade="fint", limits=[], plastic_frac=0.031, plastic_max=0.042, n_shared=3, unbalanced=False,
                            res_force_rel=2e-6, res_moment_rel=4e-4)
FSIDE = {"schema": "esl/doe_bforce_view/1", "source": "add", "load_source": "fint", "settings": {"enabled": True},
         "fint": FBLOCK, "rank_views": {"fint": {**BVIEW, "metric": "fi", "n_failed": {"fi": 0}}},
         "view3d_fi": {"d001": "d001_fi"}, "view3d_fi_esl": {"d001": "e1"}, "view3d_fi_ref": {"e1": "d000_fi_e00"},
         "per_esl": {"fint": {"d001": [{"entry_id": "e1", "C": 2.1, "ratio": 0.7, "umax": 0.6, "epsmax": 1.5e-4}]}},
         "warnings": []}


def test_results_merge_fint_and_bforce_independent(client, world, engine, esl_root, monkeypatch):
    sid = _bf_done(client, world, engine, esl_root, monkeypatch)
    (study_dir(esl_root, sid) / "post" / "fint_view.json").write_text(json.dumps(FSIDE), encoding="utf-8")
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["fint"]["source"] == "fint" and o["fint"]["entries"][0]["n_shared"] == 3
    assert o["fint"]["entries"][0]["plastic_frac"] == 0.031 and o["fint"]["entries"][0]["unbalanced"] is False
    assert o["rank_views"]["fint"]["metric"] == "fi" and o["rank_views"]["bforce"]["metric"] == "bf"
    assert o["view3d_fi"] == {"d001": "d001_fi"} and o["view3d_fi_ref"] == {"e1": "d000_fi_e00"}
    assert o["view3d_bf"] == {"d001": "d001_bf"}                                    # 경계력 값 그대로(섞임 없음)
    assert o["bforce"]["entries"][0]["n_shared"] is None
    assert o["fint_add"] == {"available": True, "allowed": True, "reason": None}
    o2 = api(client, "GET", f"/doe/studies/{sid}/results", token="tok-power2").json()
    assert not o2["fint_add"]["allowed"] and "내력 ESL 을 계산할" in o2["fint_add"]["reason"]
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=fint").json()
    assert pe["designs"][0]["per_esl"][0]["C"] == 2.1
    pb = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=bforce").json()
    assert pb["designs"][0]["per_esl"][0]["C"] == 2.55


def test_add_fint_and_unknown_source(client, world, engine, esl_root, monkeypatch):
    from esl_platform.core.repositories import jobs as jobs_repo

    sid = _bf_done(client, world, engine, esl_root, monkeypatch, side=None)
    r = api(client, "POST", f"/doe/studies/{sid}/sources/nope")
    assert r.status_code == 404 and code(r) == "SOURCE_NOT_FOUND"
    assert api(client, "POST", f"/doe/studies/{sid}/sources/fint", token="tok-power2").status_code == 403
    r = api(client, "POST", f"/doe/studies/{sid}/sources/fint")
    assert r.status_code == 202, r.text
    jid = r.json()["job"]["id"]
    with engine.connect() as c:
        job = jobs_repo.get_job(c, jid)
    assert job["params"]["kind"] == "FINT" and job["params"]["doe"]["post_mode"] == "fint"
    assert job["params"]["doe"]["fint_cfg"] == {"enabled": True, "grades": ["fint"], "view3d": True}
    assert "bforce_cfg" not in job["params"]["doe"]
    finish_job(engine, jid)


def test_fint_unsupported_on_compare_plan(client, world, engine, esl_root):
    from test_doe_rank_metric_api import _done

    sid = _done(client, world, engine, esl_root, {})                                  # ④ = 계획 bf none
    _run_job(engine, sid)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["fint"] is None and o["fint_add"] is None and o["eval_region"] is None
    r = api(client, "POST", f"/doe/studies/{sid}/sources/fint")
    assert r.status_code == 409 and code(r) == "FINT_UNSUPPORTED"


def test_results_eval_region_passthrough(client, world, engine, esl_root, monkeypatch):
    sid = _bf_done(client, world, engine, esl_root, monkeypatch)
    rp = study_dir(esl_root, sid) / "post" / "result.json"
    res = json.loads(rp.read_text(encoding="utf-8"))
    res["eval_region"] = {"mode": "exclude_free_edges", "free_edge_mm": 10.0, "boxes": [], "n_nodes": 90, "n_total": 120}
    rp.write_text(json.dumps(res), encoding="utf-8")
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["eval_region"]["mode"] == "exclude_free_edges" and o["eval_region"]["n_nodes"] == 90


def test_rank_snapshot_eval_region_and_cfg_mirror():
    from esl.doe import DEFAULTS
    from esl_platform.api.services.doe import rank_snapshot
    from esl_platform.core.config import BeadDoeCfg

    d = BeadDoeCfg().model_dump()
    assert DEFAULTS["fint"] == d["fint"] == {"enabled": True, "grades": ["fint"], "view3d": True}
    for k in ("eval_region", "eval_free_edge_mm", "eval_boxes"):
        assert DEFAULTS["rank"][k] == d["rank"][k]
    snap = rank_snapshot(d)
    assert snap["eval_region"] == {"mode": "part", "free_edge_mm": 10.0, "boxes": []}
    d2 = copy.deepcopy(d)
    d2["rank"].update(eval_region="box", eval_boxes=[{"lo": [0, 0, 0], "hi": [1, 2, 3]}])
    assert rank_snapshot(d2)["eval_region"] == {"mode": "box", "free_edge_mm": 10.0,
                                                "boxes": [{"lo": [0.0, 0.0, 0.0], "hi": [1.0, 2.0, 3.0]}]}
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["fint"] == DEFAULTS["fint"]
        assert {k: y["rank"][k] for k in ("eval_region", "eval_free_edge_mm", "eval_boxes")} == \
            {k: DEFAULTS["rank"][k] for k in ("eval_region", "eval_free_edge_mm", "eval_boxes")}


def test_openapi_v0240_fint_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    assert {"fint", "fint_add", "view3d_fi", "view3d_fi_esl", "view3d_fi_ref", "eval_region"} <= set(sc["DoeResultOut"]["properties"])
    assert "fint" in sc["DoeRankViewsOut"]["properties"] and "source" in sc["DoeBforceOut"]["properties"]
    assert {"plastic_frac", "n_shared", "unbalanced"} <= set(sc["DoeBforceEntryOut"]["properties"])
