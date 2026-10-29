"""v0.10.0 메뉴 재구성(계약 esl_menu_restructure.md) API — 계산 없이 DB 행·항목 파일을 심어 시험.

V-MR-3(라이브러리 EXPORT 가 stage_status "6" 에 영향 없음)·V-MR-4(ESL_SOLVE support_blocked)·V-MR-6(다중 내보내기 생성·오류
전부·전체 롤백)·V-MR-8(묶음 상태 계산·목록)·V-MR-9(zip 구조·409·413·경로 탈출 없음)·V-MR-15(종합분석 게이트·필터 제외)·
V-MR-16(EntryOut 키·목록 쿼리 수 상수)·V-MR-13 일부(재검증 API 오류 코드)·V-MR-25(설정 기본값).
전체 흐름(실계산)은 worker/tests/test_lib_export.py·test_revalidate.py·test_menu_tstar.py.
"""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile

import pytest
from esl_platform.core.db.tables import jobs
from esl_test_support import API, H, create_case, make_settings_dict
from p2_support import seed_entry, seed_run
from sqlalchemy import event, insert, text

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path, library_export={"max_entries": 4}, ui={"library_export_enabled": True})


@pytest.fixture()
def two_cases(client, mini_inputs, esl_root):
    out = []
    for k in range(2):
        r = create_case(client, mini_inputs, folder=f"mr{k}", title=f"메뉴 {k}")
        assert r.status_code == 201, r.text
        out.append(r.json())
    return out


def _code(r):
    return r.json()["detail"]["code"]


def _entry(engine, esl_root, case_id, *, files=True, **kw):
    s = seed_run(engine, case_id, verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    eid = seed_entry(engine, case_id, s["run_id"], esl_root=str(esl_root), **kw)
    if files:
        with open(os.path.join(str(esl_root), "_library", "entries", eid, "raw.npz"), "wb") as fh:
            fh.write(b"PK")
    return eid


def _tree(d):
    out = {}
    for base, _, names in os.walk(d):
        for n in names:
            p = os.path.join(base, n)
            out[os.path.relpath(p, d)] = os.path.getsize(p)
    return out


# ---------------------------------------------------------------- 설정
def test_library_export_settings_defaults(app_ctx):
    from esl_platform.core.config import LibraryExportCfg

    d = LibraryExportCfg()
    assert (d.max_entries, d.max_bundle_bytes, d.wait_s) == (50, None, 600.0)
    assert app_ctx.settings.library_export.max_entries == 4


# ---------------------------------------------------------------- V-MR-6 생성·오류
def test_create_batch_errors(client, engine, esl_root, two_cases):
    c0, c1 = two_cases
    e1 = _entry(engine, esl_root, c0["id"])
    e2 = _entry(engine, esl_root, c1["id"])
    url = f"{API}/library/exports"
    ok = {"project_id": "p-1", "entry_ids": [e1, e2], "targets": ["radioss_inc", "fem", "csv"]}
    for bad in ({"entry_ids": []}, {"entry_ids": [e1, e1]}, {"targets": []}, {"targets": ["xls"]},
                {"options": {"id_offset": -1}}, {"options": {"id_offset": "x"}}, {"options": {"id_policy": "z"}}):
        r = client.post(url, json={**ok, **bad}, headers=W)
        assert r.status_code == 422 and _code(r) == "INVALID_PARAMS", (bad, r.text)
    r = client.post(url, json={**ok, "entry_ids": [str(uuid.uuid4()) for _ in range(5)]}, headers=W)
    assert r.status_code == 422 and _code(r) == "TOO_MANY_ENTRIES" and r.json()["detail"]["max"] == 4
    ghost = str(uuid.uuid4())
    r = client.post(url, json={**ok, "entry_ids": [e1, ghost]}, headers=W)
    assert r.status_code == 422 and _code(r) == "ENTRY_NOT_FOUND" and r.json()["detail"]["entry_ids"] == [ghost]
    retired = _entry(engine, esl_root, c0["id"], status="RETIRED", scene_no=9)
    r = client.post(url, json={**ok, "entry_ids": [retired]}, headers=W)
    assert r.status_code == 422 and _code(r) == "ENTRY_NOT_FOUND"
    nofile = _entry(engine, esl_root, c0["id"], files=False, scene_no=8)
    r = client.post(url, json={**ok, "entry_ids": [e1, nofile]}, headers=W)
    assert r.status_code == 409 and _code(r) == "ENTRY_FILES_MISSING" and r.json()["detail"]["entry_ids"] == [nofile]
    for tok in ("tok-general", "tok-nonmember"):
        assert client.post(url, json=ok, headers=H(tok, True)).status_code == 403
    assert client.post(url, json=ok, headers=R).status_code == 403                          # CSRF
    # 같은 Case 에 비종료 EXPORT → 409 CASE_JOB_BUSY, 전체 롤백(작업·묶음 폴더 0)
    with engine.begin() as c:
        c.execute(insert(jobs).values(id=str(uuid.uuid4()), case_id=c1["id"], project_id="p-1", job_type="EXPORT",
                                      stage=6, lane="LIGHT", state="QUEUED", queue_seq=1, params={},
                                      created_by="u-power", created_by_name="파워"))
    before = _count_export_jobs(engine)
    r = client.post(url, json=ok, headers=W)
    assert r.status_code == 409 and _code(r) == "CASE_JOB_BUSY" and r.json()["detail"]["case_ids"] == [c1["id"]]
    assert _count_export_jobs(engine) == before
    assert not os.path.isdir(os.path.join(str(esl_root), "_exports")) or not os.listdir(
        os.path.join(str(esl_root), "_exports"))


def _count_export_jobs(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM jobs WHERE job_type='EXPORT'")).scalar_one()


def _finish(engine, job_id, state="SUCCEEDED", code=None):
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state=:s, queue_seq=NULL, failure_code=:c, finished_at=now() WHERE id=:i"),
                  {"s": state, "c": code, "i": job_id})


def _write_item(esl_root, batch_id, label, ok=True, files=("esl_force.fem",), id_range=(9000001, 9000100)):
    d = os.path.join(str(esl_root), "_exports", batch_id, label)
    os.makedirs(d, exist_ok=True)
    for n in files:
        with open(os.path.join(d, n), "w", encoding="ascii") as fh:
            fh.write("$ fem\n" * 10)
    rec = {"ok": ok, "entry_id": "x", "label": label, "files": list(files) if ok else [],
           "id_range": list(id_range) if ok else None, "warnings": [], "error": None if ok else
           {"code": "ID_RANGE_COLLISION", "message": "겹침"}}
    with open(os.path.join(d, "export.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh)


def test_create_batch_jobs_state_list_bundle(client, engine, esl_root, two_cases, app_ctx):
    c0, c1 = two_cases
    a1 = _entry(engine, esl_root, c0["id"], scene_no=1)
    a2 = _entry(engine, esl_root, c0["id"], scene_no=2)
    b1 = _entry(engine, esl_root, c1["id"], scene_no=3, scheme=None)             # LEGACY 도 내보내기 허용
    with engine.begin() as c:                                                      # 같은 모델 = 같은 topo
        c.execute(text("UPDATE library_entries SET topo_sha256='T1' WHERE id IN (:a, :b, :c)"),
                  {"a": a1, "b": a2, "c": b1})
    case_before = [_tree(os.path.join(str(esl_root), c["folder_name"])) for c in two_cases]
    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1, b1, a2],
                                                    "targets": ["csv", "fem"], "options": {"id_offset": 5000000}},
                    headers=W)
    assert r.status_code == 202, r.text
    o = r.json()
    bid = o["batch_id"]
    assert o["state"] == "QUEUED" and o["targets"] == ["fem", "csv"] and len(o["jobs"]) == 2
    assert o["options"] == {"id_offset": 5000000, "id_policy": "per_model_sequential"}
    assert [it["label"][:3] for it in o["items"]] == ["01_", "02_", "03_"] and o["items"][1]["legacy"] is True
    assert all(it["state"] == "PENDING" for it in o["items"]) and o["bundle"] == {"ready": False, "bytes": None}
    bdir = os.path.join(str(esl_root), "_exports", bid)
    with open(os.path.join(bdir, "batch.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["entry_ids"] == [a1, b1, a2] and doc["job_ids"] == [j["job_id"] for j in o["jobs"]]
    with engine.connect() as c:
        rows = {r[0]: r[1] for r in c.execute(text("SELECT case_id, params FROM jobs WHERE params->>'batch_id'=:b"),
                                              {"b": bid}).all()}
    pa, pb = rows[c0["id"]], rows[c1["id"]]
    assert pa["origin"] == "library" and [i["entry_id"] for i in pa["items"]] == [a1, a2]
    # Q3 B: 같은 모델 = Case 작업 순 → 선택 순(교착 없는 순서), 첫 항목만 시작 오프셋
    assert pa["items"][0]["id_offset"] == 5000000 and pa["items"][1]["id_offset"] == f"after:{a1}"
    assert pb["items"][0]["id_offset"] == f"after:{a2}" and pb["items"][0]["after_label"] == pa["items"][1]["label"]
    assert pa["items"][0]["dir_rel"] == f"_library/entries/{a1}" and set(pa["settings"]) == {"export", "units"}
    # 작업 응답: 서버 절대경로·설정 스냅샷 없음
    j = client.get(f"{API}/jobs/{o['jobs'][0]['job_id']}", headers=R).json()
    assert "settings" not in j["params"] and str(esl_root) not in json.dumps(j)
    # Case 단계 상태(⑥)에는 영향 없음(V-MR-3)
    cs = client.get(f"{API}/cases/{c0['id']}", headers=R).json()
    assert cs["stage_status"]["6"]["state"] == "none" and set(cs["step_status"]) == {"input", "tstar", "esl", "validate"}
    # 같은 Case 에 다시 → 409
    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1], "targets": ["fem"]},
                    headers=W)
    assert r.status_code == 409 and _code(r) == "CASE_JOB_BUSY"
    url = f"{API}/library/exports/{bid}"
    assert client.get(f"{url}/bundle", headers=R).json()["detail"]["code"] == "EXPORT_NOT_READY"
    # 진행: a1 완료, 작업 A RUNNING → RUNNING
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='RUNNING', queue_seq=NULL, started_at=now() WHERE id=:i"),
                  {"i": o["jobs"][0]["job_id"]})
    _write_item(esl_root, bid, o["items"][0]["label"])
    g = client.get(url, headers=R).json()
    assert g["state"] == "RUNNING" and [it["state"] for it in g["items"]] == ["DONE", "PENDING", "PENDING"]
    assert g["items"][0]["files"] == [{"rel": f"{o['items'][0]['label']}/esl_force.fem", "size": 60}]
    # A 성공(a2 실패 기록) · B 실패 → PARTIAL
    _write_item(esl_root, bid, o["items"][2]["label"], ok=False)
    _finish(engine, o["jobs"][0]["job_id"])
    _finish(engine, o["jobs"][1]["job_id"], "FAILED", "EXPORT_ALL_FAILED")
    g = client.get(url, headers=R).json()
    assert g["state"] == "PARTIAL" and [it["state"] for it in g["items"]] == ["DONE", "FAILED", "FAILED"]
    assert g["items"][1]["error"]["code"] == "EXPORT_ALL_FAILED" and g["items"][2]["error"]["code"] == "ID_RANGE_COLLISION"
    assert g["bundle"]["ready"] is True and g["bundle"]["bytes"] == 60
    lst = client.get(f"{API}/library/exports", params={"project_id": "p-1"}, headers=R).json()
    assert [b["batch_id"] for b in lst] == [bid] and lst[0]["n_items"] == 3 and lst[0]["state"] == "PARTIAL"
    assert client.get(f"{API}/library/exports", params={"project_id": "p-1"},
                      headers=H("tok-nonmember")).status_code == 403
    # zip: manifest·README·<NN>_<label>/ (성공 항목만), 루트 기준 이름, 경로 탈출 없음
    z = client.get(f"{url}/bundle", headers=R)
    assert z.status_code == 200, z.text
    assert z.headers["content-disposition"].endswith('_1.zip"')
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names == ["manifest.json", "README.txt", f"{o['items'][0]['label']}/esl_force.fem"]
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    man = json.loads(zf.read("manifest.json"))
    assert [i["state"] for i in man["items"]] == ["DONE", "FAILED", "FAILED"] and man["items"][1]["legacy"] is True
    assert man["items"][0]["validation"]["status"] == "PASS" and man["items"][1]["validation"]["status"] == "LEGACY"
    assert "LEGACY" in zf.read("README.txt").decode("utf-8")
    # 413(상한), 404, 성공 0 → 409 EXPORT_FAILED
    object.__setattr__(app_ctx.settings.library_export, "max_bundle_bytes", 10)        # (설정은 frozen)
    z = client.get(f"{url}/bundle", headers=R)
    assert z.status_code == 413 and _code(z) == "BUNDLE_TOO_LARGE"
    object.__setattr__(app_ctx.settings.library_export, "max_bundle_bytes", None)
    assert client.get(f"{API}/library/exports/{uuid.uuid4()}", headers=R).status_code == 404
    assert _code(client.get(f"{API}/library/exports/..%2F..", headers=R)) in ("EXPORT_NOT_FOUND", "NOT_FOUND")
    os.remove(os.path.join(bdir, o["items"][0]["label"], "export.json"))
    g = client.get(url, headers=R).json()
    assert g["state"] == "FAILED"
    assert _code(client.get(f"{url}/bundle", headers=R)) == "EXPORT_FAILED"
    # 취소 포함 종료 → CANCELED
    _finish(engine, o["jobs"][1]["job_id"], "CANCELED", "CANCELED")
    assert client.get(url, headers=R).json()["state"] == "CANCELED"
    assert [_tree(os.path.join(str(esl_root), c["folder_name"])) for c in two_cases] == case_before


def test_independent_policy_offsets(client, engine, esl_root, two_cases):
    c0, _ = two_cases
    a1 = _entry(engine, esl_root, c0["id"], scene_no=1)
    a2 = _entry(engine, esl_root, c0["id"], scene_no=2)
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET topo_sha256='T1' WHERE id IN (:a, :b)"), {"a": a1, "b": a2})
    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1, a2], "targets": ["fem"],
                                                    "options": {"id_policy": "independent"}}, headers=W)
    assert r.status_code == 202, r.text
    with engine.connect() as c:
        p = c.execute(text("SELECT params FROM jobs WHERE params->>'batch_id'=:b"), {"b": r.json()["batch_id"]}).scalar_one()
    assert [i["id_offset"] for i in p["items"]] == ["auto", "auto"]                 # 설정 export.radioss.id_offset


# ---------------------------------------------------------------- V-MR-4 ESL_SOLVE support_blocked
def test_esl_solve_support_blocked(client, engine, two_cases):
    c0, _ = two_cases
    ts = {"metric": "max_strain", "frame_index": 1, "time": 0.001, "elem_id": 101, "value": 0.01, "source": "user",
          "support_auto": {"status": "BLOCKED", "mode": "pca8", "rule_version": 1,
                           "problems": [{"code": "SUPPORT_TOO_CLOSE", "message": "지지 두 점이 너무 가깝습니다"}]}}
    with engine.begin() as c:
        c.execute(text("UPDATE cases SET tstar=CAST(:t AS jsonb), extract_summary=CAST(:e AS jsonb) WHERE id=:i"),
                  {"t": json.dumps(ts), "e": json.dumps({"job_id": "x", "requested_part_title": c0["part_title"]}),
                   "i": c0["id"]})
    r = client.post(f"{API}/cases/{c0['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "PREREQUISITE_MISSING" and "support_set" in d["missing"]
    assert d["support_blocked"] is True and d["problems"][0]["code"] == "SUPPORT_TOO_CLOSE"
    st = client.get(f"{API}/cases/{c0['id']}", headers=R).json()["step_status"]["tstar"]
    assert st["state"] == "failed" and st["reason"]["code"] == "SUPPORT_AUTO_BLOCKED"
    ts.pop("support_auto")
    with engine.begin() as c:
        c.execute(text("UPDATE cases SET tstar=CAST(:t AS jsonb) WHERE id=:i"), {"t": json.dumps(ts), "i": c0["id"]})
    st = client.get(f"{API}/cases/{c0['id']}", headers=R).json()["step_status"]["tstar"]
    assert st["state"] == "none" and st["reason"]["code"] == "TSTAR_NOT_CONFIRMED"
    r = client.post(f"{API}/cases/{c0['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert "support_blocked" not in r.json()["detail"]


# ---------------------------------------------------------------- V-MR-15·16 게이트·EntryOut
def test_analysis_gate_and_excluded(client, engine, esl_root, two_cases):
    c0, _ = two_cases
    ok1 = _entry(engine, esl_root, c0["id"], scene_no=1)
    ok2 = _entry(engine, esl_root, c0["id"], scene_no=2)
    leg = _entry(engine, esl_root, c0["id"], scene_no=3, scheme=None)
    url = f"{API}/library/analyses"
    r = client.post(url, json={"project_id": "p-1", "filters": {"entry_ids": [ok1, leg]}}, headers=W)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "ENTRY_NOT_ELIGIBLE" and d["entry_ids"] == [leg]
    r = client.post(url, json={"project_id": "p-1", "target_entry_id": leg}, headers=W)
    assert r.status_code == 422 and _code(r) == "ENTRY_NOT_ELIGIBLE"
    r = client.post(url, json={"project_id": "p-1"}, headers=W)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["excluded_ineligible"] == 1 and sorted(a["entry_ids"]) == sorted([ok1, ok2])
    with engine.connect() as c:
        p = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": a["job_id"]}).scalar_one()
    assert p["entries"][0]["overlay"]["status"] == "PASS" and p["entries"][0]["overlay"]["scheme"] == "disp_primary/1"
    r = client.post(url, json={"project_id": "p-1", "filters": {"verdict": ["LEGACY"]}}, headers=W)
    assert r.status_code == 422 and _code(r) == "NO_MATCHING_ENTRIES" and r.json()["detail"]["excluded_ineligible"] == 1


def test_entry_out_keys_and_constant_queries(client, engine, esl_root, two_cases, app_ctx):
    c0, c1 = two_cases
    _entry(engine, esl_root, c0["id"], scene_no=1)
    leg = _entry(engine, esl_root, c1["id"], scene_no=2, scheme=None)
    fail = _entry(engine, esl_root, c0["id"], scene_no=3, verdict="FAIL")
    und = _entry(engine, esl_root, c0["id"], scene_no=4, verdict="UNDETERMINED")
    lst = {e["id"]: e for e in client.get(f"{API}/library/entries", params={"project_id": "p-1"}, headers=R).json()}
    assert {k: (v["eligible"], v["ineligible_reason"]) for k, v in lst.items() if k in (leg, fail, und)} == {
        leg: (False, "LEGACY"), fail: (False, "FAIL"), und: (False, "UNDETERMINED")}
    # 부적격 + run 스냅샷 없음(심은 행) → 재검증 불가 사유를 목록에서 미리 계산
    assert lst[leg]["revalidate_block"]["reason"] == "RUN_SNAPSHOT_MISSING" and lst[leg]["revalidate_job"] is None
    ok = next(e for e in lst.values() if e["eligible"])
    assert ok["revalidate_block"] is None and ok["ineligible_reason"] is None

    def count(n_extra):
        for k in range(n_extra):
            _entry(engine, esl_root, c1["id"], scene_no=10 + k, scheme=None)
        n = [0]

        def cb(*_a, **_k):
            n[0] += 1

        event.listen(engine, "before_cursor_execute", cb)
        try:
            r = client.get(f"{API}/library/entries", params={"project_id": "p-1"}, headers=R)
            assert r.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", cb)
        return n[0], len(r.json())

    q1, n1 = count(0)
    q2, n2 = count(5)
    assert n2 == n1 + 5 and q1 == q2, (q1, q2)


# ---------------------------------------------------------------- V-MR-13 재검증 API 오류(계산 없음)
def test_revalidate_api_errors(client, engine, esl_root, two_cases):
    c0, _ = two_cases
    url = lambda e: f"{API}/library/entries/{e}/revalidate"  # noqa: E731
    r = client.post(url(str(uuid.uuid4())), headers=W)
    assert r.status_code == 404 and _code(r) == "ENTRY_NOT_FOUND"
    ok = _entry(engine, esl_root, c0["id"], scene_no=1)
    leg = _entry(engine, esl_root, c0["id"], scene_no=2, scheme=None)
    ret = _entry(engine, esl_root, c0["id"], scene_no=3, scheme=None, status="RETIRED")
    assert client.post(url(leg), headers=H("tok-general", True)).status_code == 403
    assert _code(client.post(url(ret), headers=W)) == "ENTRY_RETIRED"
    assert _code(client.post(url(ok), headers=W)) == "ENTRY_NOT_LEGACY"
    r = client.post(url(leg), headers=W)                       # 심은 run 은 스냅샷 폴더 없음
    assert r.status_code == 409 and _code(r) == "REVALIDATE_NOT_POSSIBLE"
    assert r.json()["detail"]["reason"] == "RUN_SNAPSHOT_MISSING"
    with engine.begin() as c:
        c.execute(text("UPDATE cases SET status='ARCHIVED' WHERE id=:i"), {"i": c0["id"]})
    assert _code(client.post(url(leg), headers=W)) == "CASE_ARCHIVED"
    # 등록: FAIL 사유 대화상자 폐지 — force_reason 은 무시(구 클라이언트 호환)
    s = seed_run(engine, c0["id"], verdict="FAIL", val_extra={"scheme": "disp_primary/1"})
    r = client.post(f"{API}/library/entries", json={"esl_run_id": s["run_id"], "force_reason": "확정"}, headers=W)
    assert r.status_code == 422 and _code(r) == "VALIDATION_NOT_PASS"


def _to_legacy(engine, eid):
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET quality = (quality - 'scheme') || CAST(:q AS jsonb) WHERE id=:i"),
                  {"i": eid, "q": '{"status": "LEGACY"}'})


def test_analysis_retry_gate_ineligible(client, engine, esl_root, two_cases):
    """통합 검증 지적 1c: 종합분석 재시도(LIB_ANALYZE)도 게이트 — 대상 항목이 부적격이면 422 ENTRY_NOT_ELIGIBLE."""
    c0, _ = two_cases
    ok1 = _entry(engine, esl_root, c0["id"], scene_no=1)
    ok2 = _entry(engine, esl_root, c0["id"], scene_no=2)
    r = client.post(f"{API}/library/analyses", json={"project_id": "p-1", "filters": {"entry_ids": [ok1, ok2]}}, headers=W)
    assert r.status_code == 201, r.text
    jid = r.json()["job_id"]
    _finish(engine, jid, "FAILED", "X")
    _to_legacy(engine, ok2)
    r = client.post(f"{API}/jobs/{jid}/retry", headers=W)
    assert r.status_code == 422 and _code(r) == "ENTRY_NOT_ELIGIBLE" and r.json()["detail"]["entry_ids"] == [ok2], r.text
