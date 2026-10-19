"""V-P1B-1: 코어 합성 Case 로 API 만 써서 ①~⑥ 완주, DB 요약 = 코어 json 값. V-STALE-1: 최신성."""

from __future__ import annotations

import json
import os

import pytest
import synth_case
from esl_test_support import API, H, create_case

W = H("tok-power", True)
R = H("tok-power")


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job, lane="SLOT"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j)
    return j


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _extract_and_esl(client, worker, synth):
    r = create_case(client, synth)
    assert r.status_code == 201, r.text
    case = r.json()
    _run(client, worker, _job(client, case["id"], "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W)
    assert sug.status_code == 200, sug.text
    s = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug.json()["node_ids"]}, headers=W)
    assert s.status_code == 201, s.text
    _run(client, worker, _job(client, case["id"], "ESL_SOLVE"))
    return client.get(f"{API}/cases/{case['id']}", headers=R).json()


def test_v_p1b_1_full_flow(client, synth_inputs, worker_factory, esl_root):
    worker = worker_factory()
    # ① 입력 확인(inspect) → Case 생성 → 추출
    ir = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": synth_inputs["rad"]}, headers=W)
    assert ir.status_code == 200, ir.text
    assert ir.json()["ok"] and ir.json()["target_part"]["id"] == synth_case.PART_ID
    rr = client.post(f"{API}/paths/inspect", json={"purpose": "RESULTS", "path": synth_inputs["csv"]}, headers=W)
    assert rr.status_code == 200 and rr.json()["ok"], rr.text
    assert rr.json()["done"]["ok"] is True
    r = create_case(client, synth_inputs)
    assert r.status_code == 201, r.text
    case = r.json()
    cid = case["id"]
    cdir = os.path.join(str(esl_root), "case01")
    assert case["folder_path"] == cdir and os.path.isfile(os.path.join(cdir, "case.json"))
    assert case["part_id"] == synth_case.PART_ID

    job = _job(client, cid, "CASE_EXTRACT")
    assert [s["step_key"] for s in job["steps"]] == ["EXTRACT", "TSTAR_SCAN", "EXTRACT_REGISTER"]
    _run(client, worker, job)
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    run = _read(os.path.join(cdir, "run.json"))
    exs = run["stages"]["extract"]["summary"]
    for k in ("n_nodes", "n_elems", "n_frames", "part_id"):
        assert case["extract_summary"][k] == exs[k], k
    assert case["stage_status"]["1"]["state"] == "done" and case["stage_status"]["2"]["state"] == "done"
    log = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()
    assert log["eof"] and any("[extract]" in ln for ln in log["lines"])

    # ② t*
    t = client.get(f"{API}/cases/{cid}/tstar", headers=R)
    assert t.status_code == 200, t.text
    tj = t.json()
    assert tj["selected"]["frame_index"] == synth_case.T_STAR_FRAME and tj["selected"]["source"] == "auto"
    m = tj["metrics"][tj["selected"]["metric"]]
    assert m["candidates"][0]["frame_index"] == synth_case.T_STAR_FRAME
    assert len(m["history"]["time"]) == len(m["history"]["value"]) > 0
    bad = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": tj["selected"]["metric"],
                                                       "frame_index": 999}, headers=W)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "FRAME_NOT_CANDIDATE"
    ok = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": tj["selected"]["metric"],
                                                      "frame_index": synth_case.T_STAR_FRAME}, headers=W)
    assert ok.status_code == 200, ok.text
    assert ok.json()["tstar"]["source"] == "user"

    # ③ 지지점
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert len(sug["node_ids"]) == 3 and len(sug["corners"]) == 4
    assert sorted(sug["node_ids"]) == sorted(synth_inputs["sup_ids"])
    nn = client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": [1, 2, 3]}, headers=W)
    assert nn.status_code == 422 and nn.json()["detail"]["code"] == "NODE_NOT_IN_PART"
    s = client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    assert s.status_code == 201, s.text
    assert s.json()["dofs"] == sug["dofs"] and s.json()["source"] == "auto" and s.json()["is_current"]
    pv = client.get(f"{API}/cases/{cid}/preview", headers=R)
    assert pv.status_code == 200, pv.text
    assert len(pv.json()["points"]) == len(synth_inputs["node_id"]) and len(pv.json()["supports"]) == 3

    # ④ ESL
    _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    assert case["stage_status"]["4"]["state"] == "done"
    runs = client.get(f"{API}/cases/{cid}/esl-runs", headers=R).json()
    assert len(runs) == 1 and runs[0]["id"] == case["current_esl_run_id"] and not runs[0]["stale"]
    er = runs[0]
    assert er["latest_validation_id"] is None
    summ = _read(os.path.join(cdir, "04_esl", "esl_summary.json"))
    assert er["frame_index"] == summ["frame"]["frame_index"] == synth_case.T_STAR_FRAME
    assert er["kabsch"]["rot_deg"] == pytest.approx(summ["kabsch"]["rot_deg"])
    assert er["forces"]["equilibrium_rel"] == pytest.approx(summ["forces"]["equilibrium_rel"])
    assert er["forces"]["max_f"] == summ["forces"]["max_f"]
    assert er["forces"]["noise"]["force_rel"] == pytest.approx(summ["noise"]["force_rel"])
    assert sorted(x["node_id"] for x in er["supports"]) == sorted(sug["node_ids"])
    fo = client.get(f"{API}/esl-runs/{er['id']}/forces", params={"top": 20}, headers=R).json()
    assert len(fo["rows"]) == 20 and fo["rows"][0]["node_id"] == summ["forces"]["max_f"]["node_id"]
    assert fo["rows"][0]["mag"] == pytest.approx(summ["forces"]["max_f"]["mag"])
    assert all(fo["rows"][i]["mag"] >= fo["rows"][i + 1]["mag"] for i in range(19))

    # ⑤ 검증
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": er["id"]}))
    vals = client.get(f"{API}/cases/{cid}/validations", headers=R).json()
    assert len(vals) == 1
    v = client.get(f"{API}/validations/{vals[0]['id']}", headers=R).json()
    vj = _read(os.path.join(cdir, "05_val", "validation.json"))
    assert v["verdict"] == vj["verdict"] == "PASS" and v["fail_reasons"] == vj["fail_reasons"]
    dm = next(x["value"] for x in vj["metrics"] if x["metric"] == "disp_rms_rel")
    assert v["disp_rms_rel"] == pytest.approx(dm) and v["disp_rms_rel"] < 1e-6
    assert [h["elem_id"] for h in v["hotspots"]] == [h["elem_id"] for h in vj["hotspots"]]
    assert not v["stale"]
    er2 = client.get(f"{API}/esl-runs/{er['id']}", headers=R).json()
    assert er2["latest_validation_id"] == v["id"]

    # ⑥ 내보내기(LIGHT 레인)
    ej = _job(client, cid, "EXPORT", {"esl_run_id": er["id"], "targets": ["radioss_inc", "fem", "csv"]})
    assert ej["lane"] == "LIGHT"
    _run(client, worker, ej, lane="LIGHT")
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    assert all(case["stage_status"][str(i)]["state"] == "done" for i in range(1, 7)), case["stage_status"]
    arts = client.get(f"{API}/cases/{cid}/artifacts", headers=R).json()
    rels = {a["rel"]: a for a in arts}
    for f in ("06_export/esl_cload.inc", "06_export/esl_bcs.inc", "06_export/esl_force.fem", "06_export/f_eq.csv",
              "04_esl/esl_summary.json", "05_val/validation.json", "run.json"):
        assert f in rels, f
    dl = client.get(f"{API}/artifacts/{rels['06_export/esl_bcs.inc']['id']}/download", headers=R)
    assert dl.status_code == 200
    with open(os.path.join(cdir, "06_export", "esl_bcs.inc"), "rb") as fh:
        assert dl.content == fh.read()
    # 입력 폴더에는 아무것도 쓰지 않음
    assert not any(n.startswith(("01_", "run.json")) for n in os.listdir(os.path.dirname(synth_inputs["rad"])))


def test_v_stale_1(client, synth_inputs, worker_factory):
    worker = worker_factory()
    case = _extract_and_esl(client, worker, synth_inputs)
    cid = case["id"]
    rid = case["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": rid}))
    tj = client.get(f"{API}/cases/{cid}/tstar", headers=R).json()
    metric = tj["selected"]["metric"]
    other = next(c["frame_index"] for c in tj["metrics"][metric]["candidates"]
                 if c["frame_index"] != tj["selected"]["frame_index"] and c.get("in_D") is not False)
    # t* 변경 → ESL·검증 stale
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": metric,
                                                     "frame_index": other}, headers=W)
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["stage_status"]["4"]["state"] == "stale" and case["stage_status"]["5"]["state"] == "stale"
    assert client.get(f"{API}/esl-runs/{rid}", headers=R).json()["stale"] is True
    vid = client.get(f"{API}/cases/{cid}/validations", headers=R).json()[0]["id"]
    assert client.get(f"{API}/validations/{vid}", headers=R).json()["stale"] is True
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "VALIDATE", "params": {"esl_run_id": rid}},
                    headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    # 되돌리면 다시 최신
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": metric,
                                                     "frame_index": tj["selected"]["frame_index"]}, headers=W)
    assert client.get(f"{API}/esl-runs/{rid}", headers=R).json()["stale"] is False
    case = r.json()
    # 지지점 변경 → stale
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    alt = list(reversed(sug["node_ids"]))
    r = client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": alt}, headers=W)
    assert r.status_code == 201
    assert client.get(f"{API}/esl-runs/{rid}", headers=R).json()["stale"] is True
    # part_title 변경 → 1단계부터 stale, ESL_SOLVE 사전조건 extract
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    r = client.patch(f"{API}/cases/{cid}", json={"version": case["version"], "part_title": "other part"}, headers=W)
    assert r.status_code == 200 and r.json()["stage_status"]["1"]["state"] == "stale"
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert r.status_code == 409 and "extract" in r.json()["detail"]["missing"]
    # 같은 버전으로 다시 PATCH → 409 VERSION_CONFLICT
    r = client.patch(f"{API}/cases/{cid}", json={"version": case["version"], "title": "x"}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"


def test_esl_prerequisites(client, synth_inputs):
    r = create_case(client, synth_inputs)
    cid = r.json()["id"]
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "PREREQUISITE_MISSING" and set(d["missing"]) >= {"extract", "tstar", "support_set"}
    r = client.get(f"{API}/cases/{cid}/tstar", headers=R)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
