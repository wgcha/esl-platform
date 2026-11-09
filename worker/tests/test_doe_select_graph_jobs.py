"""v0.17.0 BEADGRAPH 워커(계약 esl_beadgraph.md §5.3·BG-D-40·42, V-BG-16 의 워커 부분·V-BG-12 의 준비 부분) — 실제 PG·워커·코어,
가짜 paicad(fixed-scan·extract), 합성 비드 메시(tests/doe/synth_bead.py).

- 새 select 스터디(schema 2) 준비: BD_GEOM plan = [a_fixed] + fixed + (auto ∧ STEP) extract0 → extract(힌트만 — tag 없음),
  extract 실패·paicad 없음 = 정보 AUTO_HINT_UNAVAILABLE(준비 경고 아님 — AUTO_DETECT_FAILED 없음), STEP 없음 = 힌트 없음.
- 분류 결과: 코어 BD_LOADS 가 prep/select/graph.json 을 남기면 준비 요약 graph{ok, sha256, n_*}, 아니면 graph{ok false, code} +
  준비 경고 GRAPH_FAILED{detail} 1개(준비 READY — 직접 칠하기로 계속).
- schema 1 스터디 준비 = v0.16.2 그대로(graph 키·graph 파일 없음 — 나머지 회귀는 test_doe_select_*_jobs·e2e).
- E2E(자동 seed → 저장 → 미리보기 → 실행, GRAPH_FAILED + elems 비드 실행)는 코어 esl.doe.bead_graph(Impl-Core) 병합 후에만.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from doe_support import api
from doe_worker_support import calls, doe_worker_settings, set_control, write_fake_paicad
from esl_test_support import REPO
from test_doe_select_jobs import create_select, make_bead_case, preview, run_job, save_selection, start_run, study

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_bead as sb  # noqa: E402

pytestmark = [pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트"), pytest.mark.select_schema2]
CORE_GRAPH = importlib.util.find_spec("esl.doe.bead_graph") is not None
needs_core_graph = pytest.mark.skipif(not CORE_GRAPH, reason="코어 esl.doe.bead_graph(v0.17.0 Impl-Core) 병합 후")


@pytest.fixture()
def exe(tmp_path):
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, exe, request):
    sel = getattr(request, "param", None)
    return doe_worker_settings(tmp_path, exe, **({"select": sel} if sel else {}))


@pytest.fixture()
def worker(worker_factory, exe):
    set_control(exe, rules=[])
    w = worker_factory()
    w.heartbeat_once()
    return w


def prep_dir(esl_root: Path, sid: str) -> Path:
    return esl_root / "_doe" / sid / "prep"


def check_graph_summary(g: dict[str, Any], esl_root: Path, sid: str) -> None:
    """준비 요약 graph 와 prep/select/graph.json 이 맞는지(코어 병합 전 = GRAPH_FAILED 경로)."""
    gp = prep_dir(esl_root, sid) / "select" / "graph.json"
    pg = g["prep"]["graph"]
    codes = [w["code"] for w in g["prep"]["warnings"]]
    if gp.is_file():
        doc = json.loads(gp.read_text())
        assert pg["ok"] is True and pg["sha256"] == hashlib.sha256(gp.read_bytes()).hexdigest()
        assert pg["n_segments"] == len(doc.get("segments") or []) and pg["rules"] == doc.get("rules")
        assert "GRAPH_FAILED" not in codes
    else:
        assert pg["ok"] is False and isinstance(pg["code"], str) and pg["code"]
        gf = [w for w in g["prep"]["warnings"] if w["code"] == "GRAPH_FAILED"]
        assert len(gf) == 1 and gf[0]["detail"] == pg["code"]


# ================================================================ 준비(BD_GEOM plan · 준비 요약)
def test_schema2_manual_prep_plan_and_graph_summary(client, engine, worker, esl_root, inputs_root, exe):
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"])
    assert s["inputs"]["select_schema"] == 2 and s["inputs"]["bead_source"] == "manual"
    run_job(client, worker, s["job"]["id"])
    assert [c["cmd"] for c in calls(exe) if c["cmd"] != "version"] == ["fixed-scan"]          # 수동 = v0.16.2 와 같은 plan
    assert not (prep_dir(esl_root, s["id"]) / "auto_detect.json").exists()
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["fixed"]["source"] == "scan" and "auto" not in g["prep"]
    check_graph_summary(g, esl_root, s["id"])
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/graph")
    assert r.status_code == (200 if g["prep"]["graph"]["ok"] else 404)


def test_schema2_auto_with_step_hint_plan(client, engine, worker, esl_root, inputs_root, exe):
    """BG §5.3: auto + STEP = fixed-scan → extract(1차) → extract(힌트) — tag 없음. auto_detect.json role hint."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=True)
    j = run_job(client, worker, s["job"]["id"])
    assert {x["step_key"]: x["state"] for x in j["steps"]}["BD_GEOM"] == "SUCCEEDED"
    d = prep_dir(esl_root, s["id"])
    inp = json.loads((d / "input.json").read_text())
    cmds = [c["cmd"] for c in calls(exe) if c["cmd"] != "version"]
    ad = json.loads((d / "auto_detect.json").read_text())
    assert ad["role"] == "hint" and ad["step_given"] is True and ad["paicad_version"] == "0.14.1"
    if inp.get("step"):                 # 코어 BD_INPUT 이 STEP 사본을 남김(v0.16.2 코어)
        assert cmds == ["fixed-scan", "extract", "extract"] and ad["ok"] is True
    else:
        assert cmds == ["fixed-scan"] and (ad["ok"], ad["step"], ad["code"]) == (False, "extract0", "PREREQUISITE_MISSING")
    assert "tag" not in cmds and not (d / "tag").exists()
    assert not any("[BD_GEOM] AUTO_DETECT_FAILED" in x for x in j["warnings"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["auto"]["source"] == "graph"
    assert g["prep"]["auto"]["hint"] == {"ok": ad["ok"], "step": ad["step"], "code": ad["code"], "step_given": True}
    assert "AUTO_DETECT_FAILED" not in [x["code"] for x in g["prep"]["warnings"]]
    check_graph_summary(g, esl_root, s["id"])


def test_schema2_auto_without_step(client, engine, worker, esl_root, inputs_root, exe):
    """auto + STEP 없음 = 허용(힌트 없음): fixed-scan 만, AUTO_HINT_UNAVAILABLE 없음."""
    w = make_bead_case(engine, esl_root, inputs_root)
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "select", "entry_ids": w["entry_ids"],
                                                  "bead_source": "auto"})
    assert r.status_code == 201, r.text
    s = r.json()
    j = run_job(client, worker, s["job"]["id"])
    assert [c["cmd"] for c in calls(exe) if c["cmd"] != "version"] == ["fixed-scan"]
    ad = json.loads((prep_dir(esl_root, s["id"]) / "auto_detect.json").read_text())
    assert (ad["role"], ad["ok"], ad["step_given"], ad["step"]) == ("hint", False, False, None)
    assert not any("[BD_GEOM] 정보 AUTO_HINT_UNAVAILABLE" in x or "[BD_GEOM] AUTO_DETECT_FAILED" in x for x in j["warnings"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["auto"]["hint"]["step_given"] is False
    check_graph_summary(g, esl_root, s["id"])


@pytest.mark.parametrize("ctl, step", [({"version": "0.1.0"}, "version"),
                                       ({"fail": {"extract": {"code": "GEOM_CAD_FAILED", "exit": 10}}}, "extract0")],
                         ids=["paicad_unusable", "extract_failed"])
def test_schema2_hint_unavailable_is_info(client, engine, worker, esl_root, inputs_root, exe, ctl, step):
    """extract 실패·paicad 없음 = 정보 AUTO_HINT_UNAVAILABLE{step, code} — 준비 READY, 준비 경고에 AUTO_* 없음(seed 와 무관)."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=True)
    set_control(exe, rules=[], **ctl)
    j = run_job(client, worker, s["job"]["id"])
    d = prep_dir(esl_root, s["id"])
    inp = json.loads((d / "input.json").read_text())
    if step == "extract0" and not inp.get("step"):
        pytest.skip("코어 BD_INPUT 이 select STEP 사본을 남기지 않음(v0.16.2 코어 이전)")
    ad = json.loads((d / "auto_detect.json").read_text())
    assert (ad["ok"], ad["step"]) == (False, step) and ad["code"]
    assert [x for x in j["warnings"] if "AUTO_HINT_UNAVAILABLE" in x and "정보" in x]
    assert not any("[BD_GEOM] AUTO_DETECT_FAILED" in x for x in j["warnings"])
    assert "tag" not in [c["cmd"] for c in calls(exe)]
    g = study(client, s["id"])
    assert g["phase"] == "READY"
    assert not [x for x in g["prep"]["warnings"] if x["code"].startswith("AUTO_")]
    assert g["prep"]["auto"]["hint"]["ok"] is False and g["prep"]["auto"]["hint"]["step"] == step


def test_schema1_prep_unchanged(client, engine, worker, esl_root, inputs_root, exe, monkeypatch):
    """V-BG-12(준비): schema 1 스터디 준비 = graph 키·graph 파일 없음, auto = v0.16.2 plan(tag 포함 — AUTO_STEPS)."""
    from esl_platform.api.services import doe as svc

    monkeypatch.setattr(svc, "SELECT_SCHEMA_NEW", 1)
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    g = study(client, s["id"])
    assert "graph" not in g["prep"] and not (prep_dir(esl_root, s["id"]) / "select" / "graph.json").exists()
    assert not (prep_dir(esl_root, s["id"]) / "select" / "graph_labels.npz").exists()
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/graph").json()["detail"]["code"] == "GRAPH_NOT_AVAILABLE"


# ================================================================ 등록(BD_PREP_REGISTER) 단위
def _write(p: Path, doc: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_register_graph_summary_unit(tmp_path):
    from esl_worker import register as rg

    s2 = {"inputs": {"select_schema": 2, "bead_source": "auto"}}
    assert rg._select_graph_prep({"inputs": {}}, {}, str(tmp_path), {}, []) == {}            # schema 1 = 키 없음
    # 분류 결과 있음 → ok + 개수, 남은 GRAPH_FAILED 문자열 경고는 지움
    g = {"schema": "beadgraph/1", "version": "1.0.0", "rules": 1, "morph_rules": 1, "floors": [{}, {}],
         "segments": [{}, {}, {}], "junction_zones": [{}], "islands": [], "holes": [{}], "networks": [{}]}
    _write(tmp_path / "prep" / "select" / "graph.json", g)
    warns = [{"code": "GRAPH_FAILED", "message": "x"}]
    out = rg._select_graph_prep(s2, {}, str(tmp_path), {}, warns)["graph"]
    raw = (tmp_path / "prep" / "select" / "graph.json").read_bytes()
    assert out == {"ok": True, "code": None, "sha256": hashlib.sha256(raw).hexdigest(), "beadgraph_version": "1.0.0",
                   "rules": 1, "morph_rules": 1, "n_floors": 2, "n_segments": 3, "n_junction_zones": 1, "n_islands": 0,
                   "n_holes": 1, "n_networks": 1}
    assert warns == []
    (tmp_path / "prep" / "select" / "graph.json").unlink()
    # 실패: 코어 기록 graph.code → 문자열 경고 → dict 경고 → ERROR 순, 경고는 한 개(detail)
    for inp, want in (({"graph": {"ok": False, "code": "TOO_LARGE"}}, "TOO_LARGE"),
                      ({"warnings": ["GRAPH_FAILED: 분류 시간 초과(TIMEOUT 180 s)"]}, "TIMEOUT"),
                      ({"warnings": [{"code": "GRAPH_FAILED", "detail": "NO_FLOOR"}]}, "NO_FLOOR"),
                      ({"info": [{"code": "GRAPH_FAILED", "graph_code": "DISABLED"}]}, "DISABLED"),
                      ({}, "ERROR")):
        warns = [{"code": "GRAPH_FAILED", "message": "코어 문자열"}, {"code": "FIXED_INFO_MISSING", "message": "y"}]
        out = rg._select_graph_prep(s2, inp, str(tmp_path), {"GRAPH_FAILED": "분류 실패: {detail}"}, warns)
        assert out == {"graph": {"ok": False, "code": want}}, inp
        assert [w["code"] for w in warns] == ["FIXED_INFO_MISSING", "GRAPH_FAILED"]
        assert warns[-1] == {"code": "GRAPH_FAILED", "message": f"분류 실패: {want}", "detail": want}
    # 다른 주 번호·형식 오류 = 실패
    _write(tmp_path / "prep" / "select" / "graph.json", {"schema": "other/1"})
    assert rg._select_graph_prep(s2, {}, str(tmp_path), {}, [])["graph"]["ok"] is False


def test_register_auto_v2_unit(tmp_path):
    from esl_worker import register as rg

    s2 = {"inputs": {"select_schema": 2, "bead_source": "auto"}}
    warns: list[dict[str, Any]] = [{"code": "AUTO_DETECT_FAILED", "message": "코어 paicad seed 경로(옛 코어)"}]
    out = rg._select_auto_prep(s2, {}, str(tmp_path), {}, warns)
    assert out == {"auto": {"ok": False, "source": "graph", "step": None, "code": "GRAPH_FAILED", "available": False,
                            "n_beads": 0, "selection_sha256": None,
                            "hint": {"ok": False, "step": None, "code": None, "step_given": False}}}
    assert warns == []                                  # schema 2 = AUTO_DETECT_FAILED 경고 없음(GRAPH_FAILED 한 곳)
    _write(tmp_path / "prep" / "select" / "auto_selection.json",
           {"schema": "esl/doe_auto_selection/2", "selection": {"beads": [{}, {}]}, "sha256": "a" * 64})
    _write(tmp_path / "prep" / "auto_detect.json", {"schema": "esl/doe_auto_detect/1", "role": "hint", "ok": False,
                                                    "step": "extract", "code": "GEOM_CAD_FAILED", "step_given": True})
    out = rg._select_auto_prep({**s2, "inputs": {**s2["inputs"], "select_base": "mesh"}}, {}, str(tmp_path), {}, warns)
    assert out["select_base"] == "mesh"
    assert out["auto"] == {"ok": True, "source": "graph", "step": None, "code": None, "available": True, "n_beads": 2,
                           "selection_sha256": "a" * 64,
                           "hint": {"ok": False, "step": "extract", "code": "GEOM_CAD_FAILED", "step_given": True}}
    out = rg._select_auto_prep(s2, {"auto": {"n_beads": 5, "selection_sha256": "b" * 64}}, str(tmp_path), {}, warns)
    assert (out["auto"]["n_beads"], out["auto"]["selection_sha256"]) == (5, "b" * 64)


def test_select_schema_helper():
    from esl_worker.doe_jobs import select_schema

    assert select_schema({}) == 1 and select_schema({"select_schema": 1}) == 1 and select_schema({"select_schema": 2}) == 2
    assert select_schema({}, {"select_schema": 2}) == 2 and select_schema({"select_schema": "2"}) == 1


# ================================================================ E2E(코어 병합 후 — V-BG-16)
def _elems_v2(sel1: dict[str, Any]) -> dict[str, Any]:
    """schema 1 선택 → schema 2(모든 비드 src elems — 분류 실패 시 직접 칠하기)."""
    return {**{k: v for k, v in sel1.items() if k != "schema_version"}, "schema_version": 2,
            "beads": [{**b, "src": "elems"} for b in sel1["beads"]]}


@needs_core_graph
@pytest.mark.parametrize("settings_dict", [{"graph": {"enabled": False}}], indirect=True)
def test_e2e_graph_failed_elems_beads_run(client, engine, worker, esl_root, inputs_root, exe, settings_dict):
    """V-BG-16: GRAPH_FAILED(graph.enabled false = DISABLED) → 준비 READY + 경고 1개, elems 비드(schema 2)로 저장·미리보기·실행."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["graph"] == {"ok": False, "code": "DISABLED"}
    assert [x["detail"] for x in g["prep"]["warnings"] if x["code"] == "GRAPH_FAILED"] == ["DISABLED"]
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/graph").status_code == 404
    s = save_selection(client, g, _elems_v2(sb.selection(w["g"])))
    names = [x["name"] for x in api(client, "GET", f"/doe/studies/{s['id']}/params").json()["params"]]
    assert "B1_D1" in names
    p = preview(client, s, {"method": "fullfact", "levels": 2, "params": [{"name": "B1_D1", "lo": 20.0, "hi": 24.0}]})
    run_job(client, worker, p["job"]["id"])
    r = start_run(client, study(client, s["id"]))
    run_job(client, worker, r["job"]["id"])
    g = study(client, s["id"])
    assert g["phase"] == "DONE" and g["result_ready"] is True


@needs_core_graph
def test_e2e_auto_seed_save_preview_run_equals_manual(client, engine, worker, esl_root, inputs_root, exe):
    """V-BG-16: schema 2 auto → 그래프 seed → 그대로 저장(sha = seed sha) → 미리보기(BG_OUTSIDE_MOVED 없음) → 실행. 같은 선택을
    수동 스터디에 저장·실행한 결과와 순위 바이트 동일."""
    w = make_bead_case(engine, esl_root, inputs_root)
    out = {}
    for auto in (True, False):
        s = create_select(client, w["entry_ids"], auto=auto)
        run_job(client, worker, s["job"]["id"])
        g = study(client, s["id"])
        if not g["prep"]["graph"]["ok"]:
            pytest.skip(f"합성 메시 분류 실패({g['prep']['graph']['code']}) — 코어 시험 V-BG-1·2 확인")
        if auto:
            a = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
            assert a.status_code == 200, a.text
            seed = a.json()
            if not seed["selection"]["beads"]:
                pytest.skip("합성 메시에서 자동 seed 비드 없음")
            sel = seed["selection"]
        s = save_selection(client, g, sel)
        if auto:
            assert s["selection"]["sha256"] == seed["sha256"]
        params = api(client, "GET", f"/doe/studies/{s['id']}/params").json()["params"]
        d = next(x for x in params if x["type"] == "D")
        p = preview(client, s, {"method": "fullfact", "levels": 2,
                                "params": [{"name": d["name"], "lo": d["default_range"][0], "hi": d["default_range"][1]}]})
        run_job(client, worker, p["job"]["id"])
        gm = esl_root / "_doe" / s["id"] / "doe" / "1" / "grid" / "grid_manifest.json"
        cells = json.loads(gm.read_text())["cells"]
        assert not [c for c in cells if c.get("code") == "BG_OUTSIDE_MOVED"]
        r = start_run(client, study(client, s["id"]))
        run_job(client, worker, r["job"]["id"])
        res = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
        out[auto] = [(x["id"], x.get("score")) for x in res["ranking"]]
    assert out[True] == out[False]
