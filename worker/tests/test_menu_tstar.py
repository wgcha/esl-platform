"""v0.10.0 ② t*·지지점(계약 esl_menu_restructure.md §5): 실제 추출(코어 합성 Case) 후 PUT /tstar 자동 3-2-1.

V-MR-2: 지지 없음 → 자동 세트(source auto)·support_auto OK, 지지 있음 → KEPT(사용자 편집 세트 덮어쓰기 0), BLOCKED → 200·
지지 없음·problems, 같은 t* 재확정 허용, version 충돌 409, 수동 POST /support-sets 검사 실패 422 SUPPORT_CHECK_FAILED·
성공 MANUAL. V-MR-3: step_status. V-MR-4: BLOCKED Case 의 ESL_SOLVE 409 support_blocked. V-MR-5: 하위 호환(수동 세트 유지).
"""

from __future__ import annotations

from esl_test_support import API, H, create_case

W = H("tok-power", True)
R = H("tok-power")


def _run(client, worker, job_id, lane="SLOT"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job_id}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _extracted(client, worker, synth, folder):
    r = create_case(client, synth, folder=folder, title=folder)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    j = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    _run(client, worker, j["id"])
    return client.get(f"{API}/cases/{cid}", headers=R).json()


def _put(client, case, **kw):
    sel = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()["selected"]
    body = {"version": case["version"], "metric": sel["metric"], "frame_index": sel["frame_index"], **kw}
    return client.put(f"{API}/cases/{case['id']}/tstar", json=body, headers=W)


def test_put_tstar_auto_support_kept_manual(client, synth_inputs, worker_factory):
    worker = worker_factory()
    case = _extracted(client, worker, synth_inputs, "case01")
    assert case["current_support_set_id"] is None and case["tstar"]["source"] == "auto"
    st = case["step_status"]
    assert st["input"]["state"] == "done" and st["tstar"]["state"] == "none"
    assert st["tstar"]["reason"]["code"] == "TSTAR_NOT_CONFIRMED"
    # 같은 t*(auto 그대로) 재확정 허용 → 자동 3-2-1
    r = _put(client, case)
    assert r.status_code == 200, r.text
    c = r.json()
    sa = c["tstar"]["support_auto"]
    assert sa["status"] == "OK" and sa["mode"] == "pca4" and sa["rule_version"] == 1
    assert sa["checks"]["area_ratio"] > 0.9 and c["current_support_set_id"]
    assert c["step_status"]["tstar"] == {"state": "done", "job_id": None, "reason": None}
    assert c["stage_status"]["3"]["state"] == "done" and c["tstar"]["source"] == "user"
    sets = client.get(f"{API}/cases/{case['id']}/support-sets", headers=R).json()
    assert len(sets) == 1 and sets[0]["source"] == "auto" and sets[0]["is_current"] and [len(d) for d in sets[0]["dofs"]] == [3, 2, 1]
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    assert sug["status"] == "OK" and sug["node_ids"] == sets[0]["node_ids"] and sug["problems"] == []
    # version 충돌
    assert _put(client, case).status_code == 409
    # 다시 확정 → KEPT(새 세트 없음)
    r = _put(client, c)
    assert r.status_code == 200 and r.json()["tstar"]["support_auto"] == {"status": "KEPT", "source": "auto"}
    assert len(client.get(f"{API}/cases/{case['id']}/support-sets", headers=R).json()) == 1
    # 수동 지정: 같은 품질 검사 — 한 변 위 세 점(공선)·가까운 점 → 422 SUPPORT_CHECK_FAILED
    nodes = client.get(f"{API}/cases/{case['id']}/preview", headers=R).json()["points"]
    ids = [p[0] for p in nodes]
    r = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": ids[:3]}, headers=W)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "SUPPORT_CHECK_FAILED" and d["problems"]
    assert {p["code"] for p in d["problems"]} & {"SUPPORT_COLLINEAR", "SUPPORT_TOO_CLOSE", "SUPPORT_DEGENERATE"}
    # 다른 꼭지점 3개(자동과 다름) → 201 source user, support_auto MANUAL
    corners = sug["corners"]
    other = [n for n in corners if n not in sug["node_ids"]] + [n for n in sug["node_ids"]][:2]
    r = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": other[:3]}, headers=W)
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "user"
    c = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    assert c["tstar"]["support_auto"]["status"] == "MANUAL" and c["tstar"]["support_auto"]["checks"]
    # 이전 수동 세트는 t* 재확정해도 유지(V-MR-5)
    r = _put(client, c)
    assert r.json()["tstar"]["support_auto"] == {"status": "KEPT", "source": "user"}
    assert r.json()["current_support_set_id"] == c["current_support_set_id"]


def test_put_tstar_blocked_then_manual(client, synth_inputs, worker_factory, app_ctx):
    worker = worker_factory()
    case = _extracted(client, worker, synth_inputs, "case02")
    ac = app_ctx.config.core["support"]
    ac["auto_check"] = {"min_dist_rel": 0.99}                 # 기준 조정(관리자) → 자동 선택 BLOCKED
    try:
        r = _put(client, case)
        assert r.status_code == 200, r.text
        c = r.json()
        sa = c["tstar"]["support_auto"]
        assert sa["status"] == "BLOCKED" and sa["mode"] == "pca8" and c["current_support_set_id"] is None
        assert sa["problems"][0]["code"] == "SUPPORT_TOO_CLOSE" and sa["problems"][-1]["code"] == "SUPPORT_NO_VALID_CANDIDATE"
        assert c["step_status"]["tstar"]["state"] == "failed"
        assert c["step_status"]["tstar"]["reason"]["code"] == "SUPPORT_AUTO_BLOCKED"
        assert client.get(f"{API}/cases/{case['id']}/support-sets", headers=R).json() == []
        sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
        assert sug["status"] == "BLOCKED" and sug["problems"]
        j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
        assert j.status_code == 409 and j.json()["detail"]["support_blocked"] is True
        r = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "SUPPORT_CHECK_FAILED"
    finally:
        ac.pop("auto_check", None)
    r = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    assert r.status_code == 201, r.text
    c = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    assert c["tstar"]["support_auto"]["status"] == "MANUAL" and c["step_status"]["tstar"]["state"] == "done"
    j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert j.status_code == 201, j.text
