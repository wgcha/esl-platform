"""v0.24.3 ④ 검증 출처별 통합(계약 esl_validate_sources.md §14.1): 실제 코어(esl.val_src)로 합성 Case 를 API 로 ①~④ 완주 →
워커 register_validation(출처 행·legacy 필드) → 백엔드 API(출처 목록·출처별 validation·field·disp-field·section·이력).
``VAL_SRC_DUMP=<경로>`` 이면 실제 응답을 프런트 픽스처 JSON 으로 저장(frontend/src/__tests__/fixtures/real_v0243.json)."""

from __future__ import annotations

import json
import os
import shutil

import pytest
from esl_test_support import API, H, create_case, make_settings_dict

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def fs(request):
    return getattr(request, "param", "auto")


@pytest.fixture()
def settings_dict(tmp_path, fs):
    d = make_settings_dict(tmp_path, report={"auto": False})
    d["core"]["settings"]["validation"]["full_solve"] = fs
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


def test_val_src_real_core_end_to_end(client, synth_inputs, worker_factory, esl_root, tmp_path):
    from test_bforce_stage import _add_bforce

    c = synth_inputs
    plain = str(tmp_path / "inputs" / "csv_plain")
    shutil.copytree(c["csv"], plain)
    _add_bforce(c, c["csv"], fint_sign=1.0)                    # 경계력(접촉력)·내력 자료 있는 Case
    worker = worker_factory()
    base = {"project_id": "p-1", "rad_path": c["rad"]}
    cid, rid, vid = _through_validate(client, worker, {**base, "folder_name": "case01", "title": "bf", "results_dir": c["csv"]})
    cid2, rid2, vid2 = _through_validate(client, worker, {**base, "folder_name": "case02", "title": "plain",
                                                           "results_dir": plain})
    out: dict = {}
    val_dir = os.path.join(str(esl_root), "case01", "05_val")
    sj = json.load(open(os.path.join(val_dir, "sources.json"), encoding="utf-8"))
    st = {r["key"]: r for r in sj["rows"]}
    assert [r["key"] for r in sj["rows"]] == ["jig", "full", "bforce", "fint"]
    assert st["full"]["status"] == st["bforce"]["status"] == st["fint"]["status"] == "done" and st["jig"]["status"] == "na"
    assert st["jig"]["dir"] is None and st["full"]["dir"] == ""

    # ---- 출처 행: KEYS 순서·상태·사유 문구·한계
    s = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    out["sources_bf"] = s
    rows = {r["key"]: r for r in s["rows"]}
    assert s["default"] == "full" and list(rows) == ["jig", "full", "bforce", "fint"]
    assert [rows[k]["available"] for k in rows] == [False, True, True, True]
    assert rows["jig"]["code"] == "V3D_STUDY_ONLY" and rows["jig"]["reason"]
    assert rows["bforce"]["note"] == st["bforce"]["note"] and "수치 일관성" not in (rows["bforce"]["note"] or "")
    assert rows["bforce"]["cond_text"] == st["bforce"]["cond_text"] and rows["bforce"]["limits"] == st["bforce"]["limits"]
    assert rows["bforce"]["comparable"] is False                  # BF_TIE_MISSING = 비교용 아님
    assert rows["full"]["status"] == client.get(f"{API}/validations/{vid}", headers=R).json()["status"]
    p = client.get(f"{API}/cases/{cid}/validations/sources", headers=R).json()
    assert [i["validation_id"] for i in p["items"]] == [vid]
    out["hist_bf"] = p

    s2 = client.get(f"{API}/validations/{vid2}/sources", headers=R).json()
    out["sources_plain"] = s2
    r2 = {r["key"]: r for r in s2["rows"]}
    assert r2["full"]["available"] and not r2["bforce"]["available"] and not r2["fint"]["available"]
    assert r2["bforce"]["code"] and r2["bforce"]["reason"] and r2["bforce"]["note"] is None
    sj2 = json.load(open(os.path.join(str(esl_root), "case02", "05_val", "sources.json"), encoding="utf-8"))
    for r in sj2["rows"]:
        if r["status"] != "done":
            assert r["dir"] is None
    assert not os.path.isdir(os.path.join(str(esl_root), "case02", "05_val", "bforce"))
    for k in ("bforce", "fint"):                                  # 출처 결과 없음 → 409 VAL_SOURCE_UNAVAILABLE{src, reason}
        e = client.get(f"{API}/validations/{vid2}", params={"src": k}, headers=R)
        assert e.status_code == 409 and e.json()["detail"]["code"] == "VAL_SOURCE_UNAVAILABLE"
        assert e.json()["detail"]["reason"] == r2[k]["reason"]
        out[f"err_plain_{k}"] = e.json()["detail"]
    assert client.get(f"{API}/validations/{vid}", params={"src": "nope"}, headers=R).status_code == 404

    # ---- 출처별 validation·field·disp-field·section
    default = client.get(f"{API}/validations/{vid}", headers=R).json()
    assert default == client.get(f"{API}/validations/{vid}", params={"src": "full"}, headers=R).json()
    out["validation_full"] = default
    for k in ("bforce", "fint"):
        v = client.get(f"{API}/validations/{vid}", params={"src": k}, headers=R)
        assert v.status_code == 200, v.text
        v = v.json()
        assert v["status"] == st[k]["verdict"] and v["disp_rms_rel"] == st[k]["metrics"]["disp_rms_rel"]
        out[f"validation_{k}"] = v
        f = client.get(f"{API}/validations/{vid}/field", params={"layer": "err", "src": k, "max_points": 60}, headers=R)
        d = client.get(f"{API}/validations/{vid}/disp-field", params={"layer": "err", "src": k, "max_points": 60}, headers=R)
        sec = client.get(f"{API}/validations/{vid}/section", params={"src": k}, headers=R)
        assert f.status_code == d.status_code == sec.status_code == 200, (f.text, d.text, sec.text)
        out[f"field_{k}"], out[f"disp_{k}"], out[f"section_{k}"] = f.json(), d.json(), sec.json()
        assert d.json()["n_total"] == default["disp"]["n_nodes"]
    out["field_full"] = client.get(f"{API}/validations/{vid}/field", params={"layer": "err", "max_points": 60}, headers=R).json()
    out["disp_full"] = client.get(f"{API}/validations/{vid}/disp-field", params={"layer": "err"}, headers=R).json()

    # ---- 옛 검증(sources.json 없음): 출처 행 = full 만, 나머지 VAL_SRC_NOT_RUN
    snap = os.path.join(str(esl_root), "case01", "runs", rid, "05_val")
    assert os.path.isfile(os.path.join(snap, "sources.json")) and os.path.isfile(os.path.join(snap, "bforce", "validation.json"))
    for d in (val_dir, snap):
        os.remove(os.path.join(d, "sources.json"))
    old = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    ro = {r["key"]: r for r in old["rows"]}
    assert ro["full"]["available"] and not ro["bforce"]["available"] and ro["bforce"]["code"] == "VAL_SRC_NOT_RUN"
    assert ro["bforce"]["reason"]
    out["sources_old"] = old
    assert client.get(f"{API}/validations/{vid}", headers=R).json() == default

    dump = os.environ.get("VAL_SRC_DUMP")
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), default=str)


@pytest.mark.parametrize("fs", ["never"], indirect=True)
def test_val_src_undetermined_sources_have_no_compare_files(client, synth_inputs, worker_factory, esl_root):
    """full_solve never: full 은 u_rel 응축 참고 변위로, 출처(bforce·fint)는 fallback 없음 → 판정 불가 + compare 파일 없음
    (05_val/<dir>/ 에 validation.json·validation.csv 만). 화면은 이 출처의 필드·변위 카드를 사유와 함께 끈다."""
    from test_bforce_stage import _add_bforce

    c = synth_inputs
    _add_bforce(c, c["csv"], fint_sign=1.0)
    worker = worker_factory()
    cid, rid, vid = _through_validate(client, worker, {"project_id": "p-1", "rad_path": c["rad"], "folder_name": "case01",
                                                        "title": "nv", "results_dir": c["csv"]})
    val_dir = os.path.join(str(esl_root), "case01", "05_val")
    for k in ("bforce", "fint"):
        assert sorted(os.listdir(os.path.join(val_dir, k))) == ["validation.csv", "validation.json"]
    s = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    rows = {r["key"]: r for r in s["rows"]}
    out = {"sources": s}
    for k in ("bforce", "fint"):
        assert rows[k]["available"] and rows[k]["status"] == "UNDETERMINED" and rows[k]["undetermined_reason"]
        v = client.get(f"{API}/validations/{vid}", params={"src": k}, headers=R)
        assert v.status_code == 200 and v.json()["status"] == "UNDETERMINED"
        out[f"validation_{k}"] = v.json()
        for url in ("field", "disp-field"):
            e = client.get(f"{API}/validations/{vid}/{url}", params={"src": k}, headers=R)
            assert e.status_code == 409 and e.json()["detail"]["code"] == "PREREQUISITE_MISSING", e.text
            out[f"{url}_{k}"] = e.json()["detail"]
    dump = os.environ.get("VAL_SRC_DUMP_NV")
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
