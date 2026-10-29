"""v0.10.0 LEGACY 재검증(계약 esl_menu_restructure.md §7.3·§7.4): 실제 합성 Case 로 등록 → 항목을 LEGACY 로 되돌린 뒤
POST /library/entries/{id}/revalidate → VALIDATE(origin library_revalidate) → VAL_REGISTER 전환.

V-MR-13: 오류 순서·코드(ENTRY_NOT_LEGACY·EXTRACT_CHANGED·CASE_JOB_BUSY·RUN_SNAPSHOT_MISSING·CASE_ARCHIVED), 비현재 run 재검증 시
스냅샷 되돌림 경고, CASE_REPORT 자동 큐 없음. V-MR-14: PASS → quality 갱신·revalidated·validation_id·version+1, 항목 폴더
불변(해시), FAIL → 불변·KEPT_LEGACY, 그사이 폐기 → ENTRY_CHANGED. V-MR-16: revalidate_job·revalidate_block.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil

import pytest
from esl_test_support import API, H, create_case, make_settings_dict
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path, report={"auto": True})


def _run(client, worker, job_id, lane="SLOT", want="SUCCEEDED"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job_id}", headers=R).json()
    assert st == want and j["state"] == want, (st, j["failure_code"], j["failure_message"])
    return j


def _job(client, cid, jt, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": jt, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _hash_dir(d):
    h = {}
    for n in sorted(os.listdir(d)):
        with open(os.path.join(d, n), "rb") as fh:
            h[n] = hashlib.sha256(fh.read()).hexdigest()
    return h


def _make_legacy(engine, eid):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = (quality - 'scheme') || CAST(:q AS jsonb), "
                       "force_reason = '당시 확인' WHERE id=:i"), {"i": eid, "q": json.dumps({"status": "LEGACY"})})


def _entry(client, eid):
    r = client.get(f"{API}/library/entries/{eid}", headers=R)
    assert r.status_code == 200, r.text
    return r.json()


def test_revalidate_flow(client, synth_inputs, worker_factory, esl_root, engine, app_ctx):
    worker = worker_factory()
    r = create_case(client, synth_inputs)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT")["id"])
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    sel = case["tstar"]
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": sel["metric"],
                                                    "frame_index": sel["frame_index"]}, headers=W)
    assert r.status_code == 200, r.text
    _run(client, worker, _job(client, cid, "ESL_SOLVE")["id"])
    run1 = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    vj = _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": run1})["id"])
    _run(client, worker, vj["result"]["report_job_id"], lane="LIGHT")           # 일반 검증은 자동 보고서
    r = client.post(f"{API}/library/entries", json={"esl_run_id": run1}, headers=W)
    assert r.status_code == 201, r.text
    e = r.json()
    eid, old_vid = e["id"], e["validation_id"]
    edir = os.path.join(str(esl_root), *e["dir_rel"].split("/"))
    files_before = _hash_dir(edir)
    url = f"{API}/library/entries/{eid}/revalidate"
    assert client.post(url, headers=W).json()["detail"]["code"] == "ENTRY_NOT_LEGACY"
    _make_legacy(engine, eid)
    e = _entry(client, eid)
    assert e["eligible"] is False and e["ineligible_reason"] == "LEGACY" and e["revalidate_block"] is None
    # 이후 ESL 재계산 → 항목의 run 은 현재 run 이 아님(같은 추출이라 재검증 가능)
    _run(client, worker, _job(client, cid, "ESL_SOLVE")["id"])
    run2 = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    assert run2 != run1

    # 추출 바뀜(part_title 변경 → 추출 stale) → 409 EXTRACT_CHANGED, 목록 revalidate_block 미리 계산
    c = client.get(f"{API}/cases/{cid}", headers=R).json()
    r = client.patch(f"{API}/cases/{cid}", json={"version": c["version"], "part_title": "Other part"}, headers=W)
    assert r.status_code == 200, r.text
    r = client.post(url, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REVALIDATE_NOT_POSSIBLE"
    assert r.json()["detail"]["reason"] == "EXTRACT_CHANGED"
    blk = _entry(client, eid)["revalidate_block"]
    assert blk["reason"] == "EXTRACT_CHANGED" and blk["code"] == "REVALIDATE_NOT_POSSIBLE" and "다시 계산" in blk["message"]
    c = client.get(f"{API}/cases/{cid}", headers=R).json()
    client.patch(f"{API}/cases/{cid}", json={"version": c["version"], "part_title": case["part_title"]}, headers=W)

    # 재검증(현재 기준 FAIL 이 되도록 기준을 아주 엄격하게) → KEPT_LEGACY, 항목 불변
    val_cfg = app_ctx.config.core["validation"]
    keep = dict(val_cfg)
    val_cfg["disp_max_rel_max"] = 1e-15
    val_cfg["disp_rms_rel_max"] = 1e-15
    try:
        r = client.post(url, headers=W)
        assert r.status_code == 201, r.text
        j = r.json()
    finally:
        val_cfg.clear()
        val_cfg.update(keep)
    assert j["job_type"] == "VALIDATE" and j["params"]["origin"] == "library_revalidate" and j["params"]["entry_id"] == eid
    assert "settings" not in j["params"]
    assert _entry(client, eid)["revalidate_job"] == {"job_id": j["id"], "state": "QUEUED"}
    r = client.post(url, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_JOB_BUSY"
    jr = _run(client, worker, j["id"])
    assert jr["result"]["revalidate"]["outcome"] == "KEPT_LEGACY"
    assert jr["result"]["revalidate"]["status"] in ("FAIL", "UNDETERMINED")
    # 화면 KEPT_LEGACY 안내 괄호(§7.4 fail_reasons — 계약 키): FAIL 이면 사유 코드가 1개 이상
    fr = jr["result"]["revalidate"]["fail_reasons"]
    assert isinstance(fr, list) and (jr["result"]["revalidate"]["status"] != "FAIL" or len(fr) >= 1)
    assert "report_job_id" not in jr["result"]                                     # 자동 보고서 없음
    assert any("스냅샷에서 되돌림" in str(w) for w in jr["warnings"])               # 비현재 run → runs/<id>/ 되돌림
    e = _entry(client, eid)
    assert e["quality"]["status"] == "LEGACY" and e["validation_id"] == old_vid and e["eligible"] is False

    # 재검증 PASS → PROMOTED: quality·validation_id·revalidated·version+1, 항목 폴더 불변
    ver = e["version"]
    j = client.post(url, headers=W).json()
    jr = _run(client, worker, j["id"])
    rv = jr["result"]["revalidate"]
    assert rv["outcome"] == "PROMOTED" and rv["status"] == "PASS"
    assert rv["fail_reasons"] == []
    e = _entry(client, eid)
    q = e["quality"]
    assert e["eligible"] is True and e["ineligible_reason"] is None and e["version"] == ver + 1
    assert q["status"] == "PASS" and q["scheme"] == "disp_primary/1" and e["validation_id"] == rv["validation_id"] != old_vid
    assert q["revalidated"]["from_validation_id"] == old_vid and q["revalidated"]["from_status"] == "LEGACY"
    assert q["revalidated"]["job_id"] == j["id"] and e["force_reason"] is None and q["confirmed_fail"] is None
    assert _hash_dir(edir) == files_before
    assert client.post(url, headers=W).json()["detail"]["code"] == "ENTRY_NOT_LEGACY"
    jobs = client.get(f"{API}/cases/{cid}/jobs", headers=R).json()
    assert not [x for x in jobs if x["job_type"] == "CASE_REPORT" and x["state"] == "QUEUED"]

    # 그사이 폐기 → ENTRY_CHANGED(경고), 항목 불변
    _make_legacy(engine, eid)
    j = client.post(url, headers=W).json()
    assert client.post(f"{API}/library/entries/{eid}/retire", json={"reason": "정정"}, headers=W).status_code == 200
    jr = _run(client, worker, j["id"])
    assert jr["result"]["revalidate"]["outcome"] == "ENTRY_CHANGED"
    assert any("폐기" in str(w) for w in jr["warnings"])
    assert _entry(client, eid)["status"] == "RETIRED"

    # 스냅샷 없음 → RUN_SNAPSHOT_MISSING, Case 보관 → CASE_ARCHIVED (새 LEGACY 항목: run2 등록 후 되돌림)
    vj = _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": run2})["id"])
    worker.run_once("LIGHT")
    e2 = client.post(f"{API}/library/entries", json={"esl_run_id": run2}, headers=W).json()
    _make_legacy(engine, e2["id"])
    snap = os.path.join(str(esl_root), "case01", "runs", run2)
    shutil.move(snap, snap + ".off")
    try:
        r = client.post(f"{API}/library/entries/{e2['id']}/revalidate", headers=W)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "RUN_SNAPSHOT_MISSING"
    finally:
        shutil.move(snap + ".off", snap)
    assert client.post(f"{API}/cases/{cid}/archive", headers=W).status_code == 200
    r = client.post(f"{API}/library/entries/{e2['id']}/revalidate", headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_ARCHIVED"
    assert _entry(client, e2["id"])["revalidate_block"]["code"] == "CASE_ARCHIVED"
