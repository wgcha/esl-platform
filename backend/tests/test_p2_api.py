"""P2 플랫폼(계약 esl_p2_library.md §7·§11) API: DB 0003, 권한·오류 코드, field 다운샘플 크기, CSP 헤더, 경로 보호.

계산 없이 DB 행·산출물 파일을 직접 심어 API 만 시험한다(전체 흐름 E2E 는 worker/tests/test_p2_e2e.py).
"""

from __future__ import annotations

import os
import uuid

import numpy as np
import pytest
from esl_platform.core.db.tables import jobs, library_entries
from esl_test_support import API, REPO, H, create_case, make_settings_dict
from p2_support import seed_entry, seed_run, write_compare_field
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

W = H("tok-power", True)
R = H("tok-power")
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"


@pytest.fixture()
def settings_dict(tmp_path):
    # 다운샘플 시험: 미리보기 점 상한을 작게
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


# ---------------------------------------------------------------- DB 0003
def test_db_0003_tables_and_checks(engine, case):
    from sqlalchemy import inspect

    names = set(inspect(engine).get_table_names())
    assert {"library_entries", "analysis_runs"} <= names
    cols = {c["name"]: c for c in inspect(engine).get_columns("jobs")}
    assert cols["case_id"]["nullable"] and "analysis_id" in cols
    assert "field" in {c["name"] for c in inspect(engine).get_columns("validations")}
    base = dict(project_id="p-1", stage=8, lane="SLOT", state="QUEUED", queue_seq=1, params={}, created_by="u",
                created_by_name="u")
    for bad in (dict(job_type="LIB_ANALYZE", case_id=None, analysis_id=None),          # 분석 없음
                dict(job_type="CASE_EXTRACT", case_id=None, analysis_id=None),          # Case 없음
                dict(job_type="LIB_ANALYZE", case_id=case["id"], analysis_id=None)):
        with pytest.raises(IntegrityError):
            with engine.begin() as c:
                c.execute(insert(jobs).values(id=str(uuid.uuid4()), **base, **bad))
    s = seed_run(engine, case["id"])
    seed_entry(engine, case["id"], s["run_id"])
    with pytest.raises(IntegrityError):          # 같은 run 의 ACTIVE 항목 2개 금지
        seed_entry(engine, case["id"], s["run_id"])
    seed_entry(engine, case["id"], s["run_id"], status="RETIRED")     # RETIRED 는 허용
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(insert(library_entries).values(
                id="x", project_id="p", case_id=case["id"], esl_run_id=s["run_id"], status="RETIRED", model={},
                scene={}, quality={}, dir_rel="_library/entries/x", summary_rel="s", sha256="0" * 64,
                registered_by="u", registered_by_name="u"))        # RETIRED 인데 retired_at 없음


def test_migration_0003_on_pre_0003_db(engine, db_url):
    """0002 시점 DB(라이브러리 테이블·analysis_id 없음, case_id NOT NULL, 옛 CHECK)에 0003 적용."""
    from alembic import command
    from alembic.config import Config

    with engine.begin() as c:
        c.execute(text("DROP INDEX ux_jobs_analysis_active"))
        c.execute(text("ALTER TABLE jobs DROP CONSTRAINT ck_jobs_subject"))
        c.execute(text("ALTER TABLE jobs DROP COLUMN analysis_id"))
        c.execute(text("DROP TABLE analysis_runs"))
        c.execute(text("DROP TABLE library_entries"))
        c.execute(text("ALTER TABLE jobs ALTER COLUMN case_id SET NOT NULL"))
        c.execute(text("ALTER TABLE jobs DROP CONSTRAINT ck_jobs_job_type"))
        c.execute(text("ALTER TABLE jobs ADD CONSTRAINT ck_jobs_job_type CHECK "
                       "(job_type IN ('CASE_EXTRACT','ESL_SOLVE','VALIDATE','EXPORT'))"))
        c.execute(text("ALTER TABLE validations DROP COLUMN field"))
        c.execute(text("UPDATE alembic_version SET version_num = '0002'"))
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")       # 멱등
    with engine.connect() as c:
        tabs = {r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
        idx = {r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes"))}
        cons = {r[0]: r[1] for r in c.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"))}
        nullable = c.execute(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='jobs' "
                                  "AND column_name='case_id'")).scalar_one()
        ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert {"library_entries", "analysis_runs"} <= tabs and ver == "0003" and nullable == "YES"
    assert {"ux_library_entries_run_active", "ux_jobs_analysis_active"} <= idx
    assert "LIB_ANALYZE" in cons["ck_jobs_job_type"] and "REPORT" in cons["ck_artifacts_kind"]
    assert "ck_jobs_subject" in cons and "fk_jobs_analysis_id_analysis_runs" in cons


# ---------------------------------------------------------------- Case 보고서: CSP·첨부·경로 보호
def test_case_report_csp_download_and_guard(client, case, tmp_path):
    cid = case["id"]
    r = client.get(f"{API}/cases/{cid}/report", headers=R)
    assert r.status_code == 404 and _code(r) == "REPORT_NOT_FOUND"
    d = os.path.join(case["dir"], "07_report")
    os.makedirs(d)
    html = "<!doctype html><html><body><h1>보고서</h1></body></html>"
    with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    r = client.get(f"{API}/cases/{cid}/report", headers=R)
    assert r.status_code == 200 and r.text == html
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff" and "content-disposition" not in r.headers
    r = client.get(f"{API}/cases/{cid}/report", params={"download": 1}, headers=R)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["content-security-policy"] == CSP
    # 조회 = ACTIVE 사용자(일반 사용자 가능), 비인증 401, 승인 대기 403
    assert client.get(f"{API}/cases/{cid}/report", headers=H("tok-general")).status_code == 200
    assert client.get(f"{API}/cases/{cid}/report").status_code == 401
    r = client.get(f"{API}/cases/{cid}/report", headers=H("tok-pending"))
    assert r.status_code == 403 and _code(r) == "ACCOUNT_NOT_ACTIVE"
    # Case 폴더 밖을 가리키는 심링크 → 거부
    outside = tmp_path / "outside.html"
    outside.write_text("secret", encoding="utf-8")
    os.remove(os.path.join(d, "report.html"))
    os.symlink(outside, os.path.join(d, "report.html"))
    r = client.get(f"{API}/cases/{cid}/report", headers=R)
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE" and "secret" not in r.text


# ---------------------------------------------------------------- 겹쳐보기 field·section
def test_field_downsample_layers_and_section(client, engine, case):
    s = seed_run(engine, case["id"])
    vid = s["validation_id"]
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409 and _code(r) == "PREREQUISITE_MISSING"          # compare_field.npz 없음
    n = 6000
    arr = write_compare_field(os.path.join(case["dir"], "05_val"), n)
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["n_total"] == n and f["decimated"] is True and f["layer"] == "rad"
    assert 0 < f["n_returned"] == len(f["points"]) <= 500                  # ≤ ui.max_preview_points
    assert len(f["cell"]) == 2 and set(f["plane"]) == {"origin", "e1", "e2"}
    both = np.concatenate([arr["eps_rad"], arr["eps_esl"]])
    assert f["color_range"]["min"] == pytest.approx(both.min()) and f["color_range"]["max"] == pytest.approx(both.max())
    ids = {int(e): k for k, e in enumerate(arr["elem_id"])}
    for eid, a, b, v, reason in f["points"][:50]:
        k = ids[eid]
        assert (a, b) == pytest.approx(tuple(arr["centroid2d"][k])) and v == pytest.approx(arr["eps_rad"][k])
        assert reason == {0: "OK", 1: "HOLD", 2: "LOW"}[int(arr["reason"][k])]
    # 다운샘플은 셀마다 valid 우선 → 반환 점 대부분 OK
    assert sum(p[4] == "OK" for p in f["points"]) > 0.8 * len(f["points"])
    r = client.get(f"{API}/validations/{vid}/field", params={"layer": "err", "max_points": 100}, headers=R).json()
    assert r["n_returned"] <= 100 and r["color_range"]["max"] == -r["color_range"]["min"] > 0
    for eid, _, _, v, reason in r["points"]:
        k = ids[eid]
        if reason == "OK":
            assert v == pytest.approx(100 * arr["rel_err"][k])
        else:
            assert v is None                                              # 비교 불가 → 회색
    e = client.get(f"{API}/validations/{vid}/field", params={"layer": "esl", "max_points": 100000}, headers=R).json()
    assert e["n_returned"] <= 500                                           # 상한은 설정값
    assert client.get(f"{API}/validations/{vid}/field", params={"layer": "x"}, headers=R).status_code == 422
    # 작은 모델은 다운샘플 안 함
    write_compare_field(os.path.join(case["dir"], "05_val"), 300)
    f2 = client.get(f"{API}/validations/{vid}/field", headers=R).json()
    assert f2["n_returned"] == f2["n_total"] == 300 and f2["decimated"] is False and f2["cell"] is None
    # 단면선
    sec = client.get(f"{API}/validations/{vid}/section", params={"axis": "eta", "at": 0.5}, headers=R)
    assert sec.status_code == 200, sec.text
    sj = sec.json()
    assert sj["axis"] == "eta" and sj["n_elems"] > 0
    assert len(sj["s"]) == len(sj["w_rad"]) == len(sj["w_esl"]) == len(sj["w0"]) > 0
    assert all(sj["s"][i] <= sj["s"][i + 1] for i in range(len(sj["s"]) - 1))
    assert client.get(f"{API}/validations/{vid}/section", params={"at": 1.5}, headers=R).status_code == 422
    # 같은 Case 에 더 새 검증 → 이전 검증 산출물은 바뀜(스냅샷 없음) → 409
    s2 = seed_run(engine, case["id"])
    r = client.get(f"{API}/validations/{vid}/field", headers=R)
    assert r.status_code == 409 and _code(r) == "VALIDATION_FILES_GONE"
    assert client.get(f"{API}/validations/{s2['validation_id']}/field", headers=R).status_code == 200
    # run 스냅샷(표식 = 검증 id)이 있으면 이전 검증도 읽음
    snap = os.path.join(case["dir"], "runs", s["run_id"], "05_val")
    write_compare_field(snap, 200)
    with open(os.path.join(snap, "platform_validation_id.txt"), "w", encoding="utf-8") as fh:
        fh.write(vid)
    assert client.get(f"{API}/validations/{vid}/field", headers=R).json()["n_total"] == 200
    r = client.get(f"{API}/validations/{uuid.uuid4()}/field", headers=R)
    assert r.status_code == 404 and _code(r) == "VALIDATION_NOT_FOUND"


# ---------------------------------------------------------------- 라이브러리 등록 오류
def test_register_errors(client, engine, case):
    body = lambda rid, **kw: {"esl_run_id": rid, **kw}
    r = client.post(f"{API}/library/entries", json=body(str(uuid.uuid4())), headers=W)
    assert r.status_code == 404 and _code(r) == "ESL_RUN_NOT_FOUND"
    s = seed_run(engine, case["id"])
    for tok, code in (("tok-general", 403), ("tok-nonmember", 403)):
        r = client.post(f"{API}/library/entries", json=body(s["run_id"]), headers=H(tok, True))
        assert r.status_code == code and _code(r) == "FORBIDDEN"
    r = client.post(f"{API}/library/entries", json=body(s["run_id"]), headers=R)          # CSRF 헤더 없음
    assert r.status_code == 403 and _code(r) == "CSRF_HEADER_REQUIRED"
    r = client.post(f"{API}/library/entries", json=body(s["run_id"], extra=1), headers=W)
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    # 검증 없음 → 409 PREREQUISITE_MISSING
    s0 = seed_run(engine, case["id"], verdict=None)
    r = client.post(f"{API}/library/entries", json=body(s0["run_id"]), headers=W)
    assert r.status_code == 409 and _code(r) == "PREREQUISITE_MISSING" and "validation" in r.json()["detail"]["missing"]
    # FAIL + 사유 없음 → 422 VALIDATION_NOT_PASS
    sf = seed_run(engine, case["id"], verdict="FAIL")
    r = client.post(f"{API}/library/entries", json=body(sf["run_id"]), headers=W)
    assert r.status_code == 422 and _code(r) == "VALIDATION_NOT_PASS"
    r = client.post(f"{API}/library/entries", json=body(sf["run_id"], force_reason="  "), headers=W)
    assert r.status_code == 422 and _code(r) == "VALIDATION_NOT_PASS"
    # 사유가 있어도 run 스냅샷이 없으면 409
    r = client.post(f"{API}/library/entries", json=body(sf["run_id"], force_reason="확정"), headers=W)
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["run_snapshot"]
    # 다른 run 의 검증 id → 422
    r = client.post(f"{API}/library/entries", json=body(s["run_id"], validation_id=sf["validation_id"]), headers=W)
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    # 이미 ACTIVE 항목 → 409 ENTRY_EXISTS
    eid = seed_entry(engine, case["id"], s["run_id"])
    r = client.post(f"{API}/library/entries", json=body(s["run_id"]), headers=W)
    assert r.status_code == 409 and _code(r) == "ENTRY_EXISTS" and r.json()["detail"]["entry_id"] == eid


def test_library_config_missing_503(client, app_ctx, engine, case):
    app_ctx.config.library = None
    s = seed_run(engine, case["id"])
    r = client.post(f"{API}/library/entries", json={"esl_run_id": s["run_id"]}, headers=W)
    assert r.status_code == 503 and _code(r) == "LIBRARY_CONFIG_MISSING"
    r = client.post(f"{API}/library/analyses", json={"project_id": "p-1"}, headers=W)
    assert r.status_code == 503 and _code(r) == "LIBRARY_CONFIG_MISSING"


# ---------------------------------------------------------------- 목록·메타 수정·retire
def test_list_patch_retire(client, engine, case):
    runs = [seed_run(engine, case["id"]) for _ in range(3)]
    e1 = seed_entry(engine, case["id"], runs[0]["run_id"], name="55QX10A", drop_type="Corner", orient="146")
    e2 = seed_entry(engine, case["id"], runs[1]["run_id"], name="65QX10A", inch=65, drop_type="Edge", orient="12",
                    verdict="FAIL", registered_by="u-power2")
    lst = client.get(f"{API}/library/entries", params={"project_id": "p-1"}, headers=H("tok-general"))
    assert lst.status_code == 200 and {e["id"] for e in lst.json()} == {e1, e2}
    assert lst.json()[0]["case_title"] == case["title"]
    q = lambda **p: [e["id"] for e in client.get(f"{API}/library/entries", params=p, headers=R).json()]
    assert q(drop_type="corner") == [e1] and q(model="65QX10A") == [e2] and q(verdict="FAIL") == [e2]
    assert q(orient="12", project_id="p-1") == [e2] and q(inch="55") == [e1] and q(project_id="p-2") == []
    assert client.get(f"{API}/library/entries", params={"status": "X"}, headers=R).status_code == 422
    assert client.get(f"{API}/library/entries").status_code == 401
    # PATCH: power 이상, 버전 충돌, 메타만
    e = client.get(f"{API}/library/entries/{e1}", headers=R).json()
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": e["version"], "model": {"product_mass": 21.5}},
                     headers=H("tok-general", True))
    assert r.status_code == 403
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": e["version"], "model": {"product_mass": 21.5},
                                                          "scene": {"orient": "34", "drop_type": "Edge"}}, headers=W)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["model"]["product_mass"] == 21.5 and p["model"]["name"] == "55QX10A"
    assert p["scene"]["orient"] == "34" and p["scene"]["drop_class"] == "Edge" and p["scene"]["faces"] == [3, 4]
    assert p["version"] == e["version"] + 1
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": e["version"], "note": "x"}, headers=W)
    assert r.status_code == 409 and _code(r) == "VERSION_CONFLICT"
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": p["version"], "model": {"product_mass": None}},
                     headers=W)
    assert r.status_code == 200 and r.json()["model"]["product_mass"] is None
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": 9, "scene": {"orient": "7"}}, headers=W)
    assert r.status_code == 422
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": 9, "sha256": "x"}, headers=W)
    assert r.status_code == 422                                                     # 메타 외 수정 불가
    # retire: 등록자 또는 admin
    r = client.post(f"{API}/library/entries/{e2}/retire", json={"reason": "정정"}, headers=W)     # 다른 power
    assert r.status_code == 403
    r = client.post(f"{API}/library/entries/{e2}/retire", json={"reason": "정정"}, headers=H("tok-general", True))
    assert r.status_code == 403
    r = client.post(f"{API}/library/entries/{e2}/retire", json={"reason": "정정"}, headers=H("tok-power2", True))
    assert r.status_code == 200 and r.json()["status"] == "RETIRED" and r.json()["retired_by_id"] == "u-power2"
    assert r.json()["retire_reason"] == "정정" and r.json()["retired_at"]
    r = client.post(f"{API}/library/entries/{e2}/retire", headers=H("tok-admin", True))
    assert r.status_code == 409 and _code(r) == "ENTRY_RETIRED"
    r = client.post(f"{API}/library/entries/{e1}/retire", headers=H("tok-admin", True))          # 전역 admin
    assert r.status_code == 200 and r.json()["retired_by_id"] == "u-admin"
    r = client.patch(f"{API}/library/entries/{e1}", json={"version": 99, "note": "x"}, headers=W)
    assert r.status_code == 409 and _code(r) == "ENTRY_RETIRED"
    assert q(status="ACTIVE") == [] and set(q(status="RETIRED")) == {e1, e2}
    # retire 후 같은 run 재등록은 unique 위반 아님(DB 수준)
    seed_entry(engine, case["id"], runs[1]["run_id"])
    r = client.get(f"{API}/library/entries/{uuid.uuid4()}", headers=R)
    assert r.status_code == 404 and _code(r) == "ENTRY_NOT_FOUND"


# ---------------------------------------------------------------- 분석 생성 오류·조회·파일 보호
def test_analysis_errors_and_files(client, engine, case, esl_root):
    runs = [seed_run(engine, case["id"]) for _ in range(3)]
    e1 = seed_entry(engine, case["id"], runs[0]["run_id"], esl_root=str(esl_root), grid=(24, 14))
    e2 = seed_entry(engine, case["id"], runs[1]["run_id"], esl_root=str(esl_root), grid=(12, 8), drop_type="Face",
                    orient="3", product_mass=20.0)
    url = f"{API}/library/analyses"
    r = client.post(url, json={"project_id": "p-1"}, headers=H("tok-general", True))
    assert r.status_code == 403 and _code(r) == "FORBIDDEN"
    r = client.post(url, json={"project_id": "p-1"}, headers=H("tok-nonmember", True))
    assert r.status_code == 403
    r = client.post(url, json={"project_id": "p-1", "filters": {"drop_type": ["Edge"]}}, headers=W)
    assert r.status_code == 422 and _code(r) == "NO_MATCHING_ENTRIES"
    r = client.post(url, json={"project_id": "p-1"}, headers=W)                       # 대상 없음 + 격자 다름
    assert r.status_code == 422 and _code(r) == "GRID_MISMATCH"
    r = client.post(url, json={"project_id": "p-1", "target_entry_id": str(uuid.uuid4())}, headers=W)
    assert r.status_code == 422 and _code(r) == "TARGET_INVALID"
    r = client.post(url, json={"project_id": "p-1", "target_entry_id": e1, "options": {"normalization": "mass"}},
                    headers=W)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "NORMALIZATION_META_MISSING" and d["entry_ids"] == [e1]
    r = client.post(url, json={"project_id": "p-1", "filters": {"entry_ids": [e1, str(uuid.uuid4())]}}, headers=W)
    assert r.status_code == 422 and _code(r) == "ENTRY_NOT_FOUND"
    r = client.post(url, json={"project_id": "p-1", "options": {"n_representative": 0}}, headers=W)
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    r = client.post(url, json={"project_id": "p-1", "options": {"objective": "x"}}, headers=W)
    assert r.status_code == 422
    # 생성 성공: 대상 e2(질량 있음) + 필터 Face → LIB_ANALYZE 작업 QUEUED(SLOT)
    r = client.post(url, json={"project_id": "p-1", "title": "면 낙하", "target_entry_id": e2,
                               "filters": {"drop_class": ["Face"]},
                               "options": {"normalization": "mass", "n_representative": 3, "objective": "weighted"}},
                    headers=W)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "QUEUED" and a["entry_ids"] == [e2] and a["n_entries"] == 1
    assert a["job"]["job_type"] == "LIB_ANALYZE" and a["job"]["lane"] == "SLOT" and a["job"]["case_id"] is None
    assert a["job"]["analysis_id"] == a["id"] and "settings" not in a["job"]["params"]
    assert [s["step_key"] for s in a["job"]["steps"]] == ["ANALYZE", "OPTDECK", "REPORT", "LIB_REGISTER"]
    assert a["folder_path"] == os.path.join(str(esl_root), "_analysis", a["id"])
    assert a["options"] == {"normalization": "mass", "n_representative": 3, "objective": "weighted"}
    g = client.get(f"{url}/{a['id']}", headers=H("tok-general"))
    assert g.status_code == 200 and g.json()["id"] == a["id"]
    assert [x["id"] for x in client.get(url, params={"project_id": "p-1"}, headers=R).json()] == [a["id"]]
    assert client.get(url, params={"project_id": "p-2"}, headers=R).json() == []
    j = client.get(f"{API}/jobs/{a['job']['id']}", headers=R).json()
    assert j["analysis_id"] == a["id"] and j["case_id"] is None
    # 보고서·파일: 아직 없음
    r = client.get(f"{url}/{a['id']}/report", headers=R)
    assert r.status_code == 404 and _code(r) == "REPORT_NOT_FOUND"
    assert client.get(f"{url}/{a['id']}/files", headers=R).json() == []
    adir = a["folder_path"]
    os.makedirs(os.path.join(adir, "opt"))
    os.makedirs(os.path.join(adir, "_backup", "old"))
    for rel, txt in (("report.html", "<html>r</html>"), ("opt/esl_bead.fem", "BEGIN BULK"), ("analysis.json", "{}"),
                     ("_backup/old/report.html", "old")):
        with open(os.path.join(adir, *rel.split("/")), "w", encoding="utf-8") as fh:
            fh.write(txt)
    files = client.get(f"{url}/{a['id']}/files", headers=R).json()
    assert [(f["rel"], f["kind"]) for f in files] == [("report.html", "report"), ("opt/esl_bead.fem", "optdeck"),
                                                     ("analysis.json", "analysis")]
    dl = client.get(f"{url}/{a['id']}/download", params={"rel": "opt/esl_bead.fem"}, headers=R)
    assert dl.status_code == 200 and dl.content == b"BEGIN BULK"
    rp = client.get(f"{url}/{a['id']}/report", headers=R)
    assert rp.status_code == 200 and rp.headers["content-security-policy"] == CSP and rp.text == "<html>r</html>"
    for bad in ("../../case01/case.json", "/etc/passwd", "opt/../../x"):
        r = client.get(f"{url}/{a['id']}/download", params={"rel": bad}, headers=R)
        assert r.status_code == 422 and _code(r) == "PATH_UNSAFE", bad
    r = client.get(f"{url}/{a['id']}/download", params={"rel": "nope.txt"}, headers=R)
    assert r.status_code == 404
    # 같은 분석의 진행 중 작업이 있으면 재시도 불가, 취소 후 재시도 → 분석의 job_id 갱신
    jid = a["job"]["id"]
    assert client.post(f"{API}/jobs/{jid}/retry", headers=W).status_code == 409
    assert client.post(f"{API}/jobs/{jid}/cancel", headers=W).json()["state"] == "CANCELED"
    assert client.get(f"{url}/{a['id']}", headers=R).json()["status"] == "CANCELED"
    nr = client.post(f"{API}/jobs/{jid}/retry", headers=W)
    assert nr.status_code == 201, nr.text
    a2 = client.get(f"{url}/{a['id']}", headers=R).json()
    assert a2["job_id"] == nr.json()["id"] and a2["status"] == "QUEUED" and nr.json()["analysis_id"] == a["id"]
    r = client.get(f"{url}/{uuid.uuid4()}", headers=R)
    assert r.status_code == 404 and _code(r) == "ANALYSIS_NOT_FOUND"


def test_case_report_job_create(client, case):
    """CASE_REPORT 수동 생성: 추출 전이면 409, 잘못된 검증 id 422."""
    r = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "CASE_REPORT", "params": {}}, headers=W)
    assert r.status_code == 409 and _code(r) == "PREREQUISITE_MISSING"
    r = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "LIB_ANALYZE", "params": {}}, headers=W)
    assert r.status_code == 422
