"""v0.24.5 ④ 검증 단계화·MAC 실연동(계약 esl_validate_tiers.md §1.5·§4·§11·§12): 실제 코어(esl.val_metrics·esl.val_src)로 합성 Case 를
API 로 ①~④ 완주 → 워커 register_validation(migration 0017 컬럼) → 백엔드 API. 프런트가 가정한 코어 형식(B+F 픽스처)과 실제 출력이 맞는지 대조한다.
``VT_E2E_DUMP=<경로>`` 이면 실제 응답을 프런트 픽스처 JSON 으로 저장(frontend/src/__tests__/fixtures/real_v0245.json)."""

from __future__ import annotations

import json
import os

import pytest
from esl_test_support import API, H, create_case, legacy_sources, make_settings_dict

W = H("tok-power", True)
R = H("tok-power")
JIG = ("jig", "jig_disp", "jig_spring")


@pytest.fixture()
def settings_dict(request, tmp_path):
    d = make_settings_dict(tmp_path, report={"auto": False})
    if "defaults" not in request.node.name:           # 기본 = 경계력·내력·지그 고정 끔(§12) — 형식 시험은 v0.24.4 출처로 되돌림
        legacy_sources(d)
    if "formats" in request.node.name:            # 합성 Case 의 오차(~1e-13)가 PASS 상한을 넘고 조건부 상한(10 %) 이내가 되도록 설정으로만
        d["core"]["settings"]["validation"]["disp_rms_rel_max"] = 1e-30
    return d


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job):
    st = worker.run_once("SLOT")
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])


def _through_validate(client, worker, body):
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    rid = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": rid}))
    vid = client.get(f"{API}/cases/{cid}/validations", headers=R).json()[0]["id"]
    return cid, rid, vid


def _case(client, synth_inputs, worker_factory, esl_root, bf: bool):
    from test_bforce_stage import _add_bforce

    c = synth_inputs
    if bf:
        _add_bforce(c, c["csv"], fint_sign=1.0)
    cid, rid, vid = _through_validate(client, worker_factory(), {"project_id": "p-1", "rad_path": c["rad"], "folder_name": "case01",
                                                                  "title": "vt", "results_dir": c["csv"]})
    vdir = os.path.join(str(esl_root), "case01", "05_val")
    return vid, vdir


def test_vt_real_core_conditional_formats(client, synth_inputs, worker_factory, esl_root):
    """B+F 가 픽스처로 가정한 코어 형식 = 실제 코어 출력(§1.5)."""
    vid, vdir = _case(client, synth_inputs, worker_factory, esl_root, bf=True)
    vj = json.load(open(os.path.join(vdir, "validation.json"), encoding="utf-8"))
    sj = json.load(open(os.path.join(vdir, "sources.json"), encoding="utf-8"))
    fj = json.load(open(os.path.join(vdir, "fint", "validation.json"), encoding="utf-8"))
    v = client.get(f"{API}/validations/{vid}", headers=R).json()
    s = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    # ---- validation.json
    assert vj["schema"] == "esl/validation/4" and vj["verdict"] == "CONDITIONAL" and vj["verdict_scheme"] == "disp_primary/2"
    assert vj["cond_reasons"] == ["DISP_RMS"] and vj["fail_reasons"] == []
    assert {"disp_rms_rel_cond_max", "mac_min", "mac_cond_min"} <= set(vj["criteria"])
    mm = {m["metric"]: m for m in vj["metrics"]}
    assert mm["mac"]["role"] == "judge" and mm["mac"]["sense"] == "min" and mm["mac"]["grade"] == "PASS"
    assert mm["disp_rms_rel"]["grade"] == "CONDITIONAL" and mm["disp_rms_rel"]["criterion_cond"] == vj["criteria"]["disp_rms_rel_cond_max"]
    # ---- sources.json 행: verdict_scheme·cond_reasons·metrics.mac, 미수행 행 scheme null·cond_reasons []
    rows = {r["key"]: r for r in sj["rows"]}
    for k in ("full", "bforce", "fint"):
        assert rows[k]["verdict"] == "CONDITIONAL" and rows[k]["verdict_scheme"] == "disp_primary/2"
        assert rows[k]["cond_reasons"] == ["DISP_RMS"] and rows[k]["metrics"]["mac"] is not None
        assert "REACTION_ABOVE_WARN" not in rows[k]["limits"]            # 새 행은 이중 표식 없음
    for k in JIG:
        assert rows[k]["status"] == "unavailable" and rows[k]["verdict_scheme"] is None and rows[k]["cond_reasons"] == []
    # ---- 출처 반력(fint): criteria reaction_rel_max = 조건부 상한 · reaction_warn_rel = PASS 상한, judge 행 criterion = warn · criterion_cond = tol
    assert fj["criteria"]["reaction_rel_max"] == rows["fint"]["reaction_tol"] == 0.1
    assert fj["criteria"]["reaction_warn_rel"] == rows["fint"]["reaction_warn"] == 0.05
    rr = {m["metric"]: m for m in fj["metrics"]}["reaction_rel"]
    assert rr["criterion"] == 0.05 and rr["criterion_cond"] == 0.1 and rr["role"] == "judge" and rr["grade"] == "PASS"
    # ---- API(워커 register → migration 0017 컬럼 → 응답)
    assert v["status"] == v["verdict"] == "CONDITIONAL" and v["scheme"] == "disp_primary/2"
    assert v["mac"] == pytest.approx(vj["metrics"][2]["value"]) and v["cond_reasons"] == ["DISP_RMS"] and v["stale"] is False
    ar = {r["key"]: r for r in s["rows"]}
    for k in ("full", "bforce", "fint"):
        assert ar[k]["status"] == "CONDITIONAL" and ar[k]["scheme"] == "disp_primary/2" and ar[k]["cond_reasons"] == ["DISP_RMS"]
    for k in JIG:
        assert ar[k]["status"] is None and ar[k]["scheme"] is None and ar[k]["cond_reasons"] == []
    dump = os.environ.get("VT_E2E_DUMP")
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump({"validation": v, "sources": s}, fh, ensure_ascii=False, indent=1, default=str)


def test_vt_defaults_sources_off_match_hidden(client, synth_inputs, worker_factory, esl_root):
    """기본 설정(§12)에서 코어가 계산하지 않은 출처(bforce·fint·지그 고정)가 화면 숨김(ui.hidden_sources)과 일치한다."""
    vid, vdir = _case(client, synth_inputs, worker_factory, esl_root, bf=True)     # 경계력·내력 결과가 Case 에 있어도 끈 출처는 계산 0
    hidden = set(client.get(f"{API}/version", headers=R).json()["ui"]["hidden_sources"])
    s = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    ar = {r["key"]: r for r in s["rows"]}
    off = {k for k, r in ar.items() if not r["available"] and str(r["code"]).endswith(("_DISABLED", "VAL_SRC_NOT_RUN"))}
    if os.environ.get("VT_E2E_PROBE"):
        print({k: (r["available"], r["code"]) for k, r in ar.items()}, hidden)
    assert off == hidden, ({k: (r["available"], r["code"]) for k, r in ar.items()}, hidden)
    assert ar["full"]["available"] and not os.path.isdir(os.path.join(vdir, "bforce")) and not os.path.isdir(os.path.join(vdir, "fint"))
