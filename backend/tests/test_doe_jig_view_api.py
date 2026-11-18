"""v0.23.3 지그 진단 뷰·하중 정의 탭·3D 다시 만들기 API(계약 esl_jig_view.md V-0233-5·7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from doe_support import api, finish_job, study_dir, update_study
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
from test_doe_rank_metric_api import JIG_BLOCK, _done

DIAG = {"schema": "esl/doe_jig_diag/1", "n_jig": 12, "tie_spread": 0.15, "n_contact": 1, "n_patch": 2, "regions_from": "mixed",
        "regions": [{"id": 0, "kind": "contact", "part": 7, "part_title": "PANEL", "n_nodes": 30, "area_mm2": 900.0,
                     "center": [1.0, 2.0, 3.0]},
                    {"id": 1, "kind": "patch", "part": None, "part_title": None, "n_nodes": 20, "area_mm2": 400.0,
                     "center": [4.0, 5.0, 6.0]}],
        "tie_groups": [{"other_part_id": 78, "other_part_title": "PANEL", "n_nodes": 10, "n_clusters": 3, "bbox_mm": [900.0, 1.0, 500.0],
                        "cluster_dmax_mm": 12.0, "kinds": ["SECONDARY"]},
                       {"other_part_id": None, "other_part_title": None, "n_nodes": 2, "n_clusters": 1, "bbox_mm": [5.0, 0.0, 1.0],
                        "cluster_dmax_mm": 5.0, "kinds": []}],
        "tie_partner_source": "deck",
        "entries": [{"entry_id": "e1", "label": "E1", "kk": 0,
                     "dirs": {"tgt": "d000_jigdiag_e00_tgt", "fit": "d000_jigdiag_e00_fit", "err": "d000_jigdiag_e00_err"},
                     "mac": 0.159, "umax_err": 0.839, "mac_nomodes": 0.12, "umax_err_nomodes": 0.9, "work_eff": 0.4,
                     "tie_rel": 0.05, "tie_rel_groups": [0.05, 0.01], "rot_deg": 3.2, "umax_tgt": 40.0, "umax_fit": 6.4, "err_max": 38.0, "tgt_out_frac": 0.7,
                     "contrib": {"region": 0.8, "body": 0.3, "mode": 0.1},
                     "forces": [{"region": 0, "kind": "contact", "F": [0.0, 10.0, 0.0], "F_mag": 10.0, "F_n": 10.0, "F_t1": 0.0,
                                 "F_t2": 0.0, "active": True}],
                     "F_region_sum": [0.0, 10.0, 0.0], "body": [0.0, 1.0, 0.0], "modes": [{"k": 0, "a": 2.0}]}]}
VIEW = {"metric": "jig", "C_ref": 5.0, "baseline": {"id": "d000", "score": 1.0, "umax": 2.0, "epsmax": None, "worst_entry_id": "e1"},
        "n_ok": 1, "n_skipped": {}, "n_failed": {}, "per_esl_inline": False, "sensitivity": None, "sensitivity_reason": "TOO_FEW",
        "best_clean": None, "ranking": [{"id": "d001", "rank": 1, "score": 0.9, "worst_entry_id": "e1", "umax": 1.8, "epsmax": None}]}
SIDE = {"schema": "esl/doe_jig_view/1", "source": "view3d_regen", "view3d_jig": {"d001": "d001_jig"},
        "view3d_jig_esl": {"d001": "e1"}, "view3d_jig_ref": {"e1": "d000_jig_e00"}, "jig_diag": DIAG,
        "rank_views": {"jig": VIEW, "full": {**VIEW, "metric": "solve", "C_ref": 7.0}},
        "per_esl": {"jig": {"d001": [{"entry_id": "e1", "C": 4.5, "ratio": 0.9, "umax": 1.8, "epsmax": None}]}}, "warnings": []}
JIG_ROW = {"id": "d001", "values": {}, "score": 0.8, "improvement": 0.2, "worst_entry_id": "e1", "umax": 3.0, "epsmax": 1e-3,
           "rank": 1, "score_jig": 0.8, "umax_jig": 0.9, "C_jig": {"e1": 80.0}}


def _jig_done(client, world, engine, esl_root, side=SIDE, run=True):
    sid = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "jig", "cross_mesh": False, "jig": JIG_BLOCK},
                [JIG_ROW])
    if side is not None:
        (study_dir(esl_root, sid) / "post" / "jig_view.json").write_text(json.dumps(side), encoding="utf-8")
    if run:
        _run_job(engine, sid)
    return sid


def _run_job(engine, sid, state="SUCCEEDED"):
    from esl_platform.core.repositories import jobs as jobs_repo

    with engine.begin() as c:
        j = jobs_repo.insert_job(c, case_id=None, project_id="p-1", job_type="DOE_RUN", bead_doe_id=sid,
                                 params={"bead_doe_id": sid, "kind": "RUN", "out_rel": f"_doe/{sid}",
                                         "doe": {"id": sid, "scenario": "compare", "entries": []}, "warnings": ["w"]},
                                 created_by="u-power", created_by_name="파워")
    finish_job(engine, j["id"], state)
    return j["id"]


def test_results_merge_sidecar(client, world, engine, esl_root):
    sid = _jig_done(client, world, engine, esl_root)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["jig_diag"] == {k: v for k, v in DIAG.items() if k != "schema"} | {"entries": o["jig_diag"]["entries"]}
    assert o["jig_diag"]["entries"][0]["contrib"] == {"region": 0.8, "body": 0.3, "mode": 0.1}
    assert o["jig_diag"]["tie_groups"] == DIAG["tie_groups"] and o["jig_diag"]["entries"][0]["tie_rel_groups"] == [0.05, 0.01]
    assert o["jig_diag"]["regions"][0]["part_title"] == "PANEL"
    assert o["rank_views"]["jig"]["metric"] == "jig" and o["rank_views"]["full"]["C_ref"] == 7.0
    assert o["view3d_jig"] == {"d001": "d001_jig"} and o["view3d_jig_ref"] == {"e1": "d000_jig_e00"}   # result.json 에 없을 때 사이드카
    assert o["view3d_regen"] == {"available": True, "allowed": True, "reason": None}
    # result.json 값이 있으면 그것이 우선
    rp = study_dir(esl_root, sid) / "post" / "result.json"
    r = json.loads(rp.read_text(encoding="utf-8"))
    r["view3d_jig"] = {"d001": "d001_jig_old"}
    rp.write_text(json.dumps(r), encoding="utf-8")
    assert api(client, "GET", f"/doe/studies/{sid}/results").json()["view3d_jig"] == {"d001": "d001_jig_old"}
    # 다른 사용자(작성자 아님·관리자 아님) = 버튼 비활성 + 이유
    o2 = api(client, "GET", f"/doe/studies/{sid}/results", token="tok-power2").json()
    assert o2["view3d_regen"]["available"] and not o2["view3d_regen"]["allowed"] and "작성자" in o2["view3d_regen"]["reason"]
    assert api(client, "GET", f"/doe/studies/{sid}/results", token="tok-admin").json()["view3d_regen"]["allowed"] is True


def test_results_without_sidecar_null(client, world, engine, esl_root):
    sid = _jig_done(client, world, engine, esl_root, side=None)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["jig_diag"] is None and o["rank_views"] is None and o["view3d_jig"] is None
    assert o["view3d_regen"]["available"] is True
    legacy = api(client, "GET", f"/doe/studies/{_done(client, world, engine, esl_root, {})}/results").json()
    assert legacy["view3d_regen"] is None and legacy["jig_diag"] is None and legacy["rank_views"] is None


def test_per_esl_view(client, world, engine, esl_root):
    sid = _jig_done(client, world, engine, esl_root)
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=jig").json()
    assert pe["designs"][0]["per_esl"][0] == {"entry_id": "e1", "C": 4.5, "ratio": 0.9, "umax": 1.8, "epsmax": None}
    base = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001").json()
    assert base["designs"][0]["per_esl"][0]["C_solve"] == 1.2                                   # view 없음 = 기존
    r = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?design=d001&view=full")
    assert r.status_code == 409 and code(r) == "RESULT_NOT_READY"
    r = api(client, "GET", f"/doe/studies/{sid}/results/per-esl?view=xx")
    assert r.status_code == 422


def test_regenerate_queues_run_from_post(client, world, engine, esl_root):
    from esl_platform.core.repositories import doe as doe_repo
    from esl_platform.core.repositories import jobs as jobs_repo

    sid = _jig_done(client, world, engine, esl_root, run=False)
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate")
    assert r.status_code == 409 and code(r) == "VIEW3D_REGEN_UNAVAILABLE"                      # 성공한 실행 작업 없음
    _run_job(engine, sid)
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate", token="tok-power2")
    assert r.status_code == 403                                                                # 작성자 아님·관리자 아님
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate", token="tok-general")
    assert r.status_code == 403
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate")
    assert r.status_code == 202, r.text
    jid = r.json()["job"]["id"]
    with engine.connect() as c:
        job = jobs_repo.get_job(c, jid)
        steps = jobs_repo.get_steps(c, jid)
        s = doe_repo.get_study(c, sid)
    assert job["job_type"] == "DOE_RUN" and job["params"]["kind"] == "VIEW3D"
    assert job["params"]["doe"]["post_mode"] == "view3d" and job["params"]["warnings"] == []
    assert [(x["step_key"], x["state"]) for x in steps] == [("BD_BASELINE", "SKIPPED"), ("BD_DESIGNS", "SKIPPED"),
                                                            ("BD_POST", "PENDING"), ("BD_REGISTER", "PENDING")]
    assert s["phase"] == "DONE"
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()                                 # 결과 계속 보임
    assert o["view3d_regen"]["allowed"] is False and "실행 중" in o["view3d_regen"]["reason"]
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate")
    assert r.status_code == 409 and code(r) == "JOB_ACTIVE"
    finish_job(engine, jid)
    assert api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate", token="tok-admin").status_code == 202


def test_regenerate_needs_jig(client, world, engine, esl_root):
    sid = _done(client, world, engine, esl_root, {})
    _run_job(engine, sid)
    r = api(client, "POST", f"/doe/studies/{sid}/view3d/regenerate")
    assert r.status_code == 409 and code(r) == "VIEW3D_REGEN_UNAVAILABLE"


def test_regions_json_served(client, world, engine, esl_root):
    sid = _jig_done(client, world, engine, esl_root)
    d = study_dir(esl_root, sid) / "post" / "view3d" / "d000_jigdiag_e00_fit"
    d.mkdir(parents=True)
    (d / "regions.json").write_text(json.dumps({"schema": "esl/doe_jig_regions/1", "regions": []}), encoding="utf-8")
    r = api(client, "GET", f"/doe/studies/{sid}/view3d/d000_jigdiag_e00_fit/regions.json")
    assert r.status_code == 200 and r.json()["schema"] == "esl/doe_jig_regions/1"
    assert r.headers["content-type"].startswith("application/json")


def test_openapi_v0233_keys():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    assert {"jig_diag", "rank_views", "view3d_regen"} <= set(sc["DoeResultOut"]["properties"])
    assert {"DoeJigDiagOut", "DoeJigDiagEntryOut", "DoeJigDiagRegionOut", "DoeJigDiagForceOut", "DoeRankViewOut",
            "DoeRankViewsOut", "DoeView3dRegenOut"} <= set(sc)
    assert "/doe/studies/{sid}/view3d/regenerate" in json.dumps(spec["paths"])


def test_view3d_cfg_has_jig_diag():
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg

    assert DEFAULTS["view3d"]["jig_diag"] is True and BeadDoeCfg().model_dump()["view3d"]["jig_diag"] is True
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        assert yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]["view3d"]["jig_diag"] is True
