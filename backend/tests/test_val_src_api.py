"""v0.24.3 ④ 검증 출처별 API(계약 esl_validate_sources.md §7·§14.1 V-0243-VAL-12~16).

코어 산출(05_val/sources.json·05_val/<dir>/)은 묶음 A 형식(§6.2·§6.3)의 픽스처로 심는다. 계획 표·문구는 실제 코어
``esl.val_src``(어댑터 ``core_adapter.val_src_plan``·``val_reason_text``).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import numpy as np
import pytest
from esl_test_support import API, REPO, H, create_case, make_settings_dict
from p2_support import seed_run, write_compare_field

R = H("tok-power")
@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path, ui={"max_preview_points": 500})


@pytest.fixture()
def case(client, mini_inputs, esl_root):
    r = create_case(client, mini_inputs)
    assert r.status_code == 201, r.text
    c = r.json()
    c["dir"] = os.path.join(str(esl_root), c["folder_name"])
    return c


def _code(r):
    return r.json()["detail"]["code"]


def write_compare_disp(d: str, n: int = 60, seed: int = 1) -> None:
    rng = np.random.default_rng(seed)
    ab = np.column_stack([rng.uniform(-150, 150, n), rng.uniform(-100, 100, n)])
    d_rel = rng.normal(0, 1e-2, (n, 3))
    d_val = d_rel * 1.02
    e = np.linalg.norm(d_val - d_rel, axis=1)
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "compare_disp.npz"), node_id=np.arange(1, n + 1, dtype=np.int64), ab=ab,
                        d_rel=d_rel, d_val=d_val, e=e, is_support=np.arange(n) < 3, U=np.float64(0.05),
                        plane_origin=np.array([0.0, 800.0, 300.0]), plane_e1=np.array([1.0, 0, 0]),
                        plane_e2=np.array([0, 0, 1.0]))


def src_doc(verdict="FAIL", rms=0.012, excl=7, hot=3) -> dict:
    return {"schema": "esl/validation/3", "verdict": verdict, "verdict_scheme": "disp_primary/1",
            "undetermined_reason": None, "fail_reasons": ["DISP_RMS"] if verdict == "FAIL" else [],
            "metrics": [{"metric": "disp_rms_rel", "value": rms}, {"metric": "disp_max_rel", "value": 0.03},
                        {"metric": "reaction_rel", "value": 0.002}, {"metric": "disp_noise_rel", "value": 0.0004}],
            "hotspots": [{"elem_id": hot, "eps_val": 0.01, "eps_rad": 0.011, "rel_err": -0.09, "rank": 1}],
            "hotspots_excluded": [{"elem_id": excl, "reason": "NOT_RISING"}],
            "criteria": {"disp_rms_rel": 0.01, "reaction_role": "info"},
            "field": {"max": {"abs_err_pct": 12.5}, "abs_err_pct": {"p90": 4.0}},
            "disp": {"rms_rel": rms}, "strain_ref": {"n_valid": 10},
            "src": {"key": "bforce"}}


def sj_row(key: str, status="done", **kw) -> dict:
    base = {"key": key, "status": status, "code": None, "reason": None, "dir": "" if key == "full" else key,
            "verdict": None, "fail_reasons": [], "undetermined_reason": None, "reaction_role": None, "cond_text": None,
            "note": None, "limits": [], "limit_text": [], "comparable": None}
    base.update(kw)
    return base


def seed_sources(base: str, rows: list[dict], *, bforce_doc: dict | None = None) -> None:
    """05_val 형식 폴더(base)에 sources.json·bforce/ 결과를 심는다."""
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "sources.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "esl/val_sources/1", "default": "full", "enabled": True, "rows": rows}, fh)
    if bforce_doc is not None:
        d = os.path.join(base, "bforce")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "validation.json"), "w", encoding="utf-8") as fh:
            json.dump(bforce_doc, fh)
        write_compare_field(d, 120, seed=5)
        write_compare_disp(d)


FULL_ROW = dict(verdict="PASS", reaction_role=None, cond_text="하중 기준 형상 F = K₀·u_rel · 지지 bc321")
BF_ROW = dict(verdict="FAIL", fail_reasons=["DISP_RMS"], reaction_role="info", cond_text="조건 bforce",
              note="이 하중으로 정적 풀이한 변위 …", limits=["BF_TIE_MISSING"], limit_text=["tie 체결력 미포함"],
              comparable=False)


def rows_full_bf_fint_unavail() -> list[dict]:
    return [sj_row("jig", "na", code="V3D_STUDY_ONLY", reason="강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)"),
            sj_row("full", **FULL_ROW), sj_row("bforce", **BF_ROW),
            sj_row("fint", "unavailable", code="FINT_NO_DATA", reason="내력 하중 자료 없음(검증 시험)")]


def _seed_old_and_new(engine, case, client):
    """검증 3건: A(가장 오래됨 — 스냅샷 없음 = 파일 없음), B(스냅샷, sources.json 없음 = 옛), C(최신, sources.json 있음)."""
    a = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    b = seed_run(engine, case["id"], val_extra={"scheme": None})
    c = seed_run(engine, case["id"], verdict="FAIL", val_extra={"scheme": "disp_primary/1", "fail_reasons": ["DISP_RMS"]})
    return a, b, c


# ---------------------------------------------------------------- V-12 단건
def test_validation_legacy_paths_are_unchanged(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    vid = s["validation_id"]
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail(), bforce_doc=src_doc())
    plain = client.get(f"{API}/validations/{vid}", headers=R)
    full = client.get(f"{API}/validations/{vid}", params={"src": "full"}, headers=R)
    assert plain.status_code == full.status_code == 200
    assert plain.content == full.content
    hist = client.get(f"{API}/cases/{case['id']}/validations", headers=R).json()
    assert json.loads(plain.content) == hist[0]
    assert plain.json()["dir_rel"] == "05_val" and "src" not in plain.json()
    keys = set(plain.json())
    assert keys == {"id", "esl_run_id", "case_id", "job_id", "disp_rms_rel", "reaction_rel", "hotspots", "excluded",
                    "verdict", "fail_reasons", "criteria", "field", "dir_rel", "created_at", "stale", "scheme", "status",
                    "disp_max_rel", "disp_noise_rel", "undetermined_reason", "disp", "strain_ref"}


def test_legacy_path_does_not_touch_core_plan(client, engine, case, monkeypatch):
    from esl_platform.api.services import results as svc

    def boom():
        raise AssertionError("src 없음 경로는 출처 계획을 읽지 않는다")

    monkeypatch.setattr(svc, "_val_plan", boom)
    s = seed_run(engine, case["id"])
    for tail in ("", "/field", "/disp-field", "/section"):
        r = client.get(f"{API}/validations/{s['validation_id']}{tail}", headers=R)
        assert r.status_code in (200, 409), (tail, r.text)       # 409 = compare 파일 없음(PREREQUISITE_MISSING)


def test_source_validation_maps_fields(client, engine, case):
    from esl_platform.core import core_outputs as co

    s = seed_run(engine, case["id"], verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    vid = s["validation_id"]
    doc = src_doc()
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail(), bforce_doc=doc)
    parent = client.get(f"{API}/validations/{vid}", headers=R).json()
    r = client.get(f"{API}/validations/{vid}", params={"src": "bforce"}, headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    f = co.validation_fields(doc)
    for k, v in f.items():
        assert d[k] == v, k
    for k in ("id", "esl_run_id", "case_id", "job_id", "created_at", "stale"):
        assert d[k] == parent[k], k
    assert d["dir_rel"] == "05_val/bforce" and d["status"] == "FAIL" and d["verdict"] == "FAIL"
    assert d["hotspots"][0]["elem_id"] == 3 and d["excluded"] == [{"elem_id": 7, "reason": "NOT_RISING"}]
    assert d["disp_rms_rel"] == 0.012 and d["criteria"]["reaction_role"] == "info"
    assert parent["verdict"] == "PASS"                                     # 부모(full) 행은 그대로


def test_source_errors(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    vid = s["validation_id"]
    u = f"{API}/validations/{vid}"
    r = client.get(u, params={"src": "nope"}, headers=R)
    assert r.status_code == 404 and _code(r) == "SOURCE_NOT_FOUND"
    assert r.json()["detail"]["src"] == "nope" and r.json()["detail"]["keys"] == ["jig", "full", "bforce", "fint"]
    # sources.json 없음(옛 검증) → 409 VAL_SOURCE_UNAVAILABLE(reason_code VAL_SRC_NOT_RUN)
    r = client.get(u, params={"src": "bforce"}, headers=R)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "VAL_SOURCE_UNAVAILABLE" and d["reason_code"] == "VAL_SRC_NOT_RUN"
    assert d["src"] == "bforce" and "다시 실행" in d["reason"]
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail(), bforce_doc=src_doc())
    r = client.get(u, params={"src": "fint"}, headers=R)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["reason_code"] == "FINT_NO_DATA" and d["reason"] == "내력 하중 자료 없음(검증 시험)"
    r = client.get(u, params={"src": "jig"}, headers=R)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["reason_code"] == "V3D_STUDY_ONLY" and d["code"] == "VAL_SOURCE_UNAVAILABLE"
    for tail in ("/field", "/disp-field", "/section"):
        r = client.get(u + tail, params={"src": "fint"}, headers=R)
        assert r.status_code == 409 and _code(r) == "VAL_SOURCE_UNAVAILABLE", tail
    # 검증 폴더 없음(이후 검증으로 바뀜) = 409 VALIDATION_FILES_GONE
    s2 = seed_run(engine, case["id"])
    r = client.get(u, params={"src": "bforce"}, headers=R)
    assert r.status_code == 409 and _code(r) == "VALIDATION_FILES_GONE"
    assert client.get(f"{API}/validations/{uuid.uuid4()}", params={"src": "bforce"}, headers=R).status_code == 404
    assert s2["validation_id"]


def test_source_read_from_snapshot_and_backup(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    vid = s["validation_id"]
    seed_run(engine, case["id"])                                           # 더 새 검증 → 이 검증은 Case 05_val 이 아님
    snap = os.path.join(case["dir"], "runs", s["run_id"], "05_val")
    seed_sources(snap, rows_full_bf_fint_unavail(), bforce_doc=src_doc(rms=0.021))
    Path(snap, "platform_validation_id.txt").write_text(vid, encoding="utf-8")
    r = client.get(f"{API}/validations/{vid}", params={"src": "bforce"}, headers=R)
    assert r.status_code == 200 and r.json()["disp_rms_rel"] == 0.021
    assert client.get(f"{API}/validations/{vid}/field", params={"src": "bforce"}, headers=R).status_code == 200
    # 스냅샷이 _backup 으로 밀려난 뒤에도 표식으로 찾음
    bdir = os.path.join(case["dir"], "_backup", "20261120T000000_000000Z", "runs", s["run_id"])
    os.makedirs(bdir)
    os.rename(snap, os.path.join(bdir, "05_val"))
    r = client.get(f"{API}/validations/{vid}", params={"src": "bforce"}, headers=R)
    assert r.status_code == 200 and r.json()["disp_rms_rel"] == 0.021
    src = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    assert [x["available"] for x in src["rows"]] == [False, True, True, False]


# ---------------------------------------------------------------- V-13 field·disp-field·section
def test_source_npz_endpoints(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    vid, base = s["validation_id"], os.path.join(case["dir"], "05_val")
    seed_sources(base, rows_full_bf_fint_unavail(), bforce_doc=src_doc(hot=1002))
    write_compare_field(base, 300, seed=2)                    # full(루트) 는 다른 크기
    write_compare_disp(base, 40, seed=9)
    u = f"{API}/validations/{vid}"
    f0 = client.get(f"{u}/field", headers=R)
    f1 = client.get(f"{u}/field", params={"src": "full"}, headers=R)
    fb = client.get(f"{u}/field", params={"src": "bforce"}, headers=R)
    assert f0.status_code == f1.status_code == fb.status_code == 200
    assert f0.content == f1.content and f0.json()["n_total"] == 300 and fb.json()["n_total"] == 120
    d0 = client.get(f"{u}/disp-field", headers=R).json()
    db = client.get(f"{u}/disp-field", params={"src": "bforce"}, headers=R).json()
    assert d0["n_total"] == 40 and db["n_total"] == 60
    assert client.get(f"{u}/disp-field", params={"src": "full"}, headers=R).content == \
        client.get(f"{u}/disp-field", headers=R).content
    s0 = client.get(f"{u}/section", headers=R).json()
    sb = client.get(f"{u}/section", params={"src": "bforce"}, headers=R)
    assert sb.status_code == 200, sb.text
    sbj = sb.json()
    assert sbj["has_val"] is True and sbj["n_elems"] != s0["n_elems"] or sbj["s"] != s0["s"]
    assert any(x["key"] == "hotspot1" for x in sbj["suggest"])            # 추천 단면 = 출처 문서 hotspot
    assert client.get(f"{u}/section", params={"src": "x"}, headers=R).status_code == 404
    # 출처 폴더에 compare_disp 만 없음 → 단면은 has_val False, disp-field 는 PREREQUISITE_MISSING
    os.remove(os.path.join(base, "bforce", "compare_disp.npz"))
    assert client.get(f"{u}/section", params={"src": "bforce"}, headers=R).json()["has_val"] is False
    r = client.get(f"{u}/disp-field", params={"src": "bforce"}, headers=R)
    assert r.status_code == 409 and _code(r) == "PREREQUISITE_MISSING"


# ---------------------------------------------------------------- V-14 sources 경로
def _tree(root: str) -> list[str]:
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


def test_sources_paths_four_kinds_and_read_only(client, engine, case):
    a, b, c = _seed_old_and_new(engine, case, client)
    # b = LEGACY 옛 검증(스냅샷 폴더, sources.json 없음), a = 폴더 없음, c = 최신(Case 05_val, sources.json 있음)
    snap = os.path.join(case["dir"], "runs", b["run_id"], "05_val")
    os.makedirs(snap)
    Path(snap, "platform_validation_id.txt").write_text(b["validation_id"], encoding="utf-8")
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail(), bforce_doc=src_doc())
    before = _tree(case["dir"])
    new = client.get(f"{API}/validations/{c['validation_id']}/sources", headers=R)
    assert new.status_code == 200, new.text
    nj = new.json()
    assert nj["validation_id"] == c["validation_id"] and nj["default"] == "full"
    assert [r["key"] for r in nj["rows"]] == ["jig", "full", "bforce", "fint"]
    jig, full, bf, fint = nj["rows"]
    assert (jig["available"], jig["code"], jig["status"]) == (False, "V3D_STUDY_ONLY", None)
    assert jig["reason"] == "강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)"
    assert full["available"] and full["status"] == "FAIL" and full["fail_reasons"] == ["DISP_RMS"]   # DB 가 기준
    assert full["cond_text"] == FULL_ROW["cond_text"] and full["note"] is None and full["limits"] == []
    assert bf["available"] and bf["status"] == "FAIL" and bf["reaction_role"] == "info" and bf["comparable"] is False
    assert bf["limits"] == ["BF_TIE_MISSING"] and bf["limit_text"] == ["tie 체결력 미포함"] and bf["note"]
    assert bf["fail_reasons"] == ["DISP_RMS"] and bf["code"] is None
    assert not fint["available"] and fint["code"] == "FINT_NO_DATA" and fint["status"] is None and fint["cond_text"] is None
    # 옛(LEGACY) 검증: legacy 행 = DB(LEGACY), 나머지 VAL_SRC_NOT_RUN(jig = V3D_STUDY_ONLY)
    old = client.get(f"{API}/validations/{b['validation_id']}/sources", headers=R).json()["rows"]
    assert old[1]["status"] == "LEGACY" and old[1]["available"] and old[1]["cond_text"] is None
    assert old[1]["comparable"] is None and old[1]["limits"] == []
    assert [(r["code"], r["available"]) for r in old if r["key"] != "full"] == [
        ("V3D_STUDY_ONLY", False), ("VAL_SRC_NOT_RUN", False), ("VAL_SRC_NOT_RUN", False)]
    assert "다시 실행" in old[2]["reason"]
    # 파일 없음
    gone = client.get(f"{API}/validations/{a['validation_id']}/sources", headers=R).json()["rows"]
    assert gone[1]["status"] == "PASS" and gone[1]["available"]
    assert [(r["code"], r["available"]) for r in gone if r["key"] != "full"] == [("VALIDATION_FILES_GONE", False)] * 3
    assert "이후 검증으로 바뀌었습니다" in gone[0]["reason"]
    # 이력: /cases/{id}/validations 와 같은 순서·개수
    h = client.get(f"{API}/cases/{case['id']}/validations/sources", headers=R)
    assert h.status_code == 200, h.text
    hj = h.json()
    ids = [v["id"] for v in client.get(f"{API}/cases/{case['id']}/validations", headers=R).json()]
    assert hj["case_id"] == case["id"] and [i["validation_id"] for i in hj["items"]] == ids
    assert hj["items"][0]["rows"] == nj["rows"]
    assert _tree(case["dir"]) == before                                  # 읽기만 — 새 파일 0
    assert client.get(f"{API}/validations/{uuid.uuid4()}/sources", headers=R).status_code == 404
    assert client.get(f"{API}/cases/{uuid.uuid4()}/validations/sources", headers=R).status_code == 404
    assert client.get(f"{API}/cases/{case['id']}/validations/sources").status_code == 401


def test_sources_corrupt_json_is_treated_as_missing(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    os.makedirs(os.path.join(case["dir"], "05_val"))
    Path(case["dir"], "05_val", "sources.json").write_text("{not json", encoding="utf-8")
    rows = client.get(f"{API}/validations/{s['validation_id']}/sources", headers=R).json()["rows"]
    assert rows[2]["code"] == "VAL_SRC_NOT_RUN" and rows[1]["available"]


def test_sources_row_with_missing_dir_is_unavailable_on_fetch(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail())     # bforce/ 폴더 없음
    r = client.get(f"{API}/validations/{s['validation_id']}", params={"src": "bforce"}, headers=R)
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "VALIDATION_FILES_GONE"


# ---------------------------------------------------------------- V-15 워커 / V-16 스키마
def test_validation_fields_matches_worker_conversion():
    from esl_platform.core import core_outputs as co

    f = co.validation_fields(src_doc())
    assert list(f) == ["hotspots", "excluded", "verdict", "scheme", "undetermined_reason", "disp_rms_rel",
                       "reaction_rel", "disp_max_rel", "disp_noise_rel", "fail_reasons", "criteria", "field", "disp",
                       "strain_ref"]
    assert f["scheme"] == "disp_primary/1" and f["hotspots"][0]["eps_val"] == 0.01
    old = co.validation_fields({"verdict": "PASS", "excluded": [{"elem_id": 5, "reason": "x"}],
                                "hotspots": [{"elem_id": 1, "eps_os": 0.5, "eps_rad": "0.4"}], "disp_rms_rel": 0.1})
    assert old["scheme"] is None and old["hotspots"][0]["eps_val"] == 0.5 and old["hotspots"][0]["eps_rad"] == 0.4
    assert old["excluded"] == [{"elem_id": 5, "reason": "x"}] and old["disp_rms_rel"] == 0.1 and old["field"] is None


def test_openapi_new_paths_schemas_and_unchanged_validation_out():
    spec = json.loads((Path(REPO) / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    paths, sch = spec["paths"], spec["components"]["schemas"]
    assert {"/esl/api/validations/{vid}/sources", "/esl/api/cases/{case_id}/validations/sources"} <= set(paths)
    assert {"ValidationSourceRow", "ValidationSourcesOut", "ValidationSourcesHistItem",
            "ValidationSourcesHistOut"} <= set(sch)
    assert set(sch["ValidationSourceRow"]["properties"]) == {
        "key", "available", "code", "reason", "status", "fail_reasons", "undetermined_reason", "reaction_role", "reaction_tol", "reaction_tol_key", "reaction_warn", "reaction_warned",
        "cond_text", "note", "limits", "limit_text", "comparable"}
    assert set(sch["ValidationOut"]["properties"]) == {
        "id", "esl_run_id", "case_id", "job_id", "disp_rms_rel", "reaction_rel", "hotspots", "excluded", "verdict",
        "fail_reasons", "criteria", "field", "dir_rel", "created_at", "stale", "scheme", "status", "disp_max_rel",
        "disp_noise_rel", "undetermined_reason", "disp", "strain_ref"}          # 새 필드 없음
    for p in ("/esl/api/validations/{vid}", "/esl/api/validations/{vid}/field", "/esl/api/validations/{vid}/disp-field",
              "/esl/api/validations/{vid}/section"):
        assert "src" in {q["name"] for q in paths[p]["get"]["parameters"]}, p
