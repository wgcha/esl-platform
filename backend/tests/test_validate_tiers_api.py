"""④ 검증 판정 단계화(PASS·조건부 PASS·FAIL)·MAC — 백엔드(계약 esl_validate_tiers.md §4, v0.24.5).

V-0245-VT-8 옛 결과 응답 불변 · VT-9 migration 0017 업·다운 · VT-10 게이트(CONDITIONAL = 통과)·정적 시험 · VT-11 묶음 등급.
코어 문서 형식(계약 §1.5 — validation.json·sources.json 의 verdict CONDITIONAL·mac·cond_reasons)은 픽스처로 가정한다.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import get_args

import pytest
from esl_test_support import API, REPO, H, create_case, make_settings_dict
from p2_support import seed_entry, seed_run
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_val_src_api import FULL_ROW, rows_full_bf_fint_unavail, seed_sources, sj_row

R = H("tok-power")
W = H("tok-power", True)
HEAD = "0017"


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


def _cfg(db_url):
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = db_url
    return cfg


def _case_row(engine, cid="c1"):
    with engine.begin() as c:
        c.execute(text("INSERT INTO cases (id, project_id, folder_name, title, rad_path, results_dir, "
                       "input_fingerprint, part_title, created_by, created_by_name) VALUES "
                       f"('{cid}','p-1','f_{cid}','t','/r','/s','{{}}','x','u','u')"))


def _cons(engine, table):
    with engine.connect() as c:
        return {r[0]: r[1] for r in c.execute(text(
            f"SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = '{table}'::regclass"))}


def _cols(engine):
    with engine.connect() as c:
        return {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='validations'"))}


def _ver(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _run_all_row(engine, verdict):
    """run_alls 최소 행(ck 시험용) — 종료 상태 DONE."""
    rid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT INTO run_alls (id, case_id, project_id, status, from_step, verdict, core_settings, created_by, "
                       "created_by_name, finished_at) VALUES (:i,'c1','p-1','DONE','input',:v,'{}'::jsonb,'u','u', now())"),
                  {"i": rid, "v": verdict})
    return rid


# ================================================================ V-0245-VT-9 migration 0017
def _to_0016_state(engine):
    """0017 이전(0016) 스키마: 새 컬럼·CHECK 제거, 0008·0013 의 옛 CHECK 복원, alembic_version = 0016."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM run_alls"))
        c.execute(text("DELETE FROM validations WHERE verdict = 'CONDITIONAL' OR scheme = 'disp_primary/2'"))
        for n in ("ck_validations_conditional", "ck_validations_scheme", "ck_validations_verdict"):
            c.execute(text(f"ALTER TABLE validations DROP CONSTRAINT {n}"))
        c.execute(text("ALTER TABLE validations ADD CONSTRAINT ck_validations_verdict "
                       "CHECK (verdict IN ('PASS','FAIL','UNDETERMINED'))"))
        c.execute(text("ALTER TABLE validations ADD CONSTRAINT ck_validations_scheme "
                       "CHECK (scheme IS NULL OR scheme IN ('disp_primary/1'))"))
        c.execute(text("ALTER TABLE run_alls DROP CONSTRAINT ck_run_alls_verdict"))
        c.execute(text("ALTER TABLE run_alls ADD CONSTRAINT ck_run_alls_verdict "
                       "CHECK (verdict IS NULL OR verdict IN ('PASS','FAIL','UNDETERMINED'))"))
        c.execute(text("ALTER TABLE validations DROP COLUMN mac"))
        c.execute(text("ALTER TABLE validations DROP COLUMN cond_reasons"))
        c.execute(text("UPDATE alembic_version SET version_num = '0016'"))


def test_vt9_upgrade_keeps_old_rows_and_allows_conditional(engine, db_url):
    from alembic import command

    _case_row(engine)
    olds = {v: seed_run(engine, "c1", verdict=v, val_extra={"scheme": "disp_primary/1", **(
        {"undetermined_reason": "ZERO_DISP"} if v == "UNDETERMINED" else {})})["validation_id"]
            for v in ("PASS", "FAIL", "UNDETERMINED")}
    legacy = seed_run(engine, "c1", verdict="PASS")["validation_id"]        # scheme NULL = LEGACY
    _to_0016_state(engine)
    assert _ver(engine) == "0016" and not ({"mac", "cond_reasons"} & _cols(engine))
    with pytest.raises(DBAPIError):                                         # 0016: CONDITIONAL 거부
        seed_run(engine, "c1", verdict="CONDITIONAL", val_extra={"scheme": "disp_primary/1"})
    command.upgrade(_cfg(db_url), "head")
    assert _ver(engine) == HEAD and {"mac", "cond_reasons"} <= _cols(engine)
    cons = _cons(engine, "validations")
    assert "CONDITIONAL" in cons["ck_validations_verdict"] and "disp_primary/2" in cons["ck_validations_scheme"]
    assert "ck_validations_conditional" in cons and "CONDITIONAL" in _cons(engine, "run_alls")["ck_run_alls_verdict"]
    with engine.connect() as c:                                             # 기존 행 보존·백필 없음
        rows = {r.id: r for r in c.execute(text("SELECT id, verdict, scheme, mac, cond_reasons FROM validations"))}
    assert {rows[i].verdict for i in olds.values()} == {"PASS", "FAIL", "UNDETERMINED"}
    assert rows[legacy].scheme is None
    for r in rows.values():
        assert r.mac is None and r.cond_reasons == []
    # CONDITIONAL 삽입 가능(새 체계에서만), run_alls 도
    ok = seed_run(engine, "c1", verdict="CONDITIONAL", val_extra={"scheme": "disp_primary/2", "mac": 0.93,
                                                                   "cond_reasons": ["MAC"]})
    with engine.connect() as c:
        r = c.execute(text("SELECT mac, cond_reasons FROM validations WHERE id=:i"), {"i": ok["validation_id"]}).one()
    assert r.mac == pytest.approx(0.93) and r.cond_reasons == ["MAC"]
    for bad in ({"scheme": "disp_primary/1"}, {}):                          # 옛 체계·LEGACY + CONDITIONAL 거부
        with pytest.raises(DBAPIError):
            seed_run(engine, "c1", verdict="CONDITIONAL", val_extra=bad)
    seed_run(engine, "c1", verdict="PASS", val_extra={"scheme": "disp_primary/2"})
    _run_all_row(engine, "CONDITIONAL")
    with pytest.raises(DBAPIError):
        _run_all_row(engine, "MAYBE")


def test_vt9_idempotent_on_create_all_db(engine, db_url):
    from alembic import command

    before = (_cols(engine), _cons(engine, "validations"), _cons(engine, "run_alls"))
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '0016'"))
    command.upgrade(_cfg(db_url), "head")
    command.upgrade(_cfg(db_url), "head")
    assert _ver(engine) == HEAD and (_cols(engine), _cons(engine, "validations"), _cons(engine, "run_alls")) == before


def test_vt9_downgrade_blocked_by_conditional_then_ok(engine, db_url):
    """downgrade 규칙(계약 §4.2·0008 선례): CONDITIONAL·disp_primary/2 행(검증) 또는 CONDITIONAL 전체 실행이 있으면 중단
    (데이터 보존). 없으면 CHECK 복원·컬럼 삭제(옛 PASS·FAIL·UNDETERMINED 행 보존)."""
    from alembic import command

    _case_row(engine)
    keep = seed_run(engine, "c1", verdict="PASS", val_extra={"scheme": "disp_primary/1"})
    cond = seed_run(engine, "c1", verdict="CONDITIONAL", val_extra={"scheme": "disp_primary/2", "mac": 0.92})
    with pytest.raises(Exception) as ei:
        command.downgrade(_cfg(db_url), "0016")
    assert "CONDITIONAL" in str(ei.value) or "disp_primary/2" in str(ei.value)
    assert _ver(engine) == HEAD and {"mac", "cond_reasons"} <= _cols(engine)                      # 스키마·데이터 그대로
    with engine.begin() as c:
        c.execute(text("DELETE FROM validations WHERE id=:i"), {"i": cond["validation_id"]})
        c.execute(text("INSERT INTO validations (id, esl_run_id, case_id, job_id, hotspots, verdict, criteria, "
                       "dir_rel, scheme) SELECT gen_random_uuid()::text, esl_run_id, case_id, job_id, '[]'::jsonb, "
                       "'PASS', '{}'::jsonb, '05_val', 'disp_primary/2' FROM validations WHERE id=:i"), {"i": keep["validation_id"]})
    with pytest.raises(Exception) as ei:                                                             # PASS 여도 /2 행이 있으면 중단
        command.downgrade(_cfg(db_url), "0016")
    assert "disp_primary/2" in str(ei.value)
    with engine.begin() as c:
        c.execute(text("DELETE FROM validations WHERE scheme='disp_primary/2'"))
    rid = _run_all_row(engine, "CONDITIONAL")
    with pytest.raises(Exception) as ei:                                                             # run_alls CONDITIONAL
        command.downgrade(_cfg(db_url), "0016")
    assert "전체 실행" in str(ei.value)
    with engine.begin() as c:
        c.execute(text("DELETE FROM run_alls WHERE id=:i"), {"i": rid})
    command.downgrade(_cfg(db_url), "0016")
    assert _ver(engine) == "0016" and not ({"mac", "cond_reasons"} & _cols(engine))
    cons = _cons(engine, "validations")
    assert "CONDITIONAL" not in cons["ck_validations_verdict"] and "ck_validations_conditional" not in cons
    assert "disp_primary/2" not in cons["ck_validations_scheme"]
    assert "CONDITIONAL" not in _cons(engine, "run_alls")["ck_run_alls_verdict"]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM validations")).scalar_one() == 1                  # PASS 행 보존
    with pytest.raises(DBAPIError):
        seed_run(engine, "c1", verdict="CONDITIONAL", val_extra={"scheme": "disp_primary/1"})
    command.upgrade(_cfg(db_url), "head")                                                             # 다시 올라감
    assert _ver(engine) == HEAD


# ================================================================ V-0245-VT-8 API(옛 결과 불변 + 새 필드)
def test_vt8_old_validation_response_adds_only_null_mac_and_empty_reasons(client, engine, case):
    s = seed_run(engine, case["id"], val_extra={"scheme": "disp_primary/1"})
    d = client.get(f"{API}/validations/{s['validation_id']}", headers=R).json()
    assert d["status"] == "PASS" and d["verdict"] == "PASS" and d["mac"] is None and d["cond_reasons"] == []
    assert d["fail_reasons"] == [] and d["criteria"] == {}
    lst = client.get(f"{API}/cases/{case['id']}/validations", headers=R).json()
    assert lst[0] == d


def test_vt8_conditional_validation_out(client, engine, case):
    s = seed_run(engine, case["id"], verdict="CONDITIONAL",
                 val_extra={"scheme": "disp_primary/2", "mac": 0.931, "cond_reasons": ["DISP_RMS", "MAC"]})
    d = client.get(f"{API}/validations/{s['validation_id']}", headers=R).json()
    assert d["verdict"] == d["status"] == "CONDITIONAL" and d["scheme"] == "disp_primary/2"
    assert d["mac"] == pytest.approx(0.931) and d["cond_reasons"] == ["DISP_RMS", "MAC"] and d["fail_reasons"] == []
    # 출처 문서(src) = 그 출처 validation.json 의 mac·cond_reasons
    seed_sources(os.path.join(case["dir"], "05_val"), rows_full_bf_fint_unavail(), bforce_doc=None)
    bdir = os.path.join(case["dir"], "05_val", "bforce")
    os.makedirs(bdir, exist_ok=True)
    doc = {"schema": "esl/validation/4", "verdict": "CONDITIONAL", "verdict_scheme": "disp_primary/2",
           "fail_reasons": [], "cond_reasons": ["MAC"], "hotspots": [], "criteria": {"mac_min": 0.95},
           "metrics": [{"metric": "disp_rms_rel", "value": 0.03}, {"metric": "mac", "value": 0.9}]}
    Path(bdir, "validation.json").write_text(json.dumps(doc), encoding="utf-8")
    b = client.get(f"{API}/validations/{s['validation_id']}", params={"src": "bforce"}, headers=R).json()
    assert b["status"] == b["verdict"] == "CONDITIONAL" and b["mac"] == pytest.approx(0.9) and b["cond_reasons"] == ["MAC"]


def test_vt8_source_rows_carry_scheme_and_cond_reasons(client, engine, case):
    s = seed_run(engine, case["id"], verdict="CONDITIONAL",
                 val_extra={"scheme": "disp_primary/2", "mac": 0.93, "cond_reasons": ["MAC"]})
    rows = rows_full_bf_fint_unavail()
    rows[4] = sj_row("bforce", verdict="CONDITIONAL", verdict_scheme="disp_primary/2", cond_reasons=["REACTION"],
                     reaction_warned=True, comparable=True)
    seed_sources(os.path.join(case["dir"], "05_val"), rows)
    d = client.get(f"{API}/validations/{s['validation_id']}/sources", headers=R)
    assert d.status_code == 200, d.text
    by = {r["key"]: r for r in d.json()["rows"]}
    assert by["full"]["status"] == "CONDITIONAL" and by["full"]["scheme"] == "disp_primary/2"
    assert by["full"]["cond_reasons"] == ["MAC"]                                      # legacy 키 = DB 행
    assert by["bforce"]["status"] == "CONDITIONAL" and by["bforce"]["cond_reasons"] == ["REACTION"]
    assert by["bforce"]["scheme"] == "disp_primary/2" and by["bforce"]["reaction_warned"] is True
    assert by["fint"]["scheme"] is None and by["fint"]["cond_reasons"] == []           # 결과 없는 행
    assert by["jig"]["scheme"] is None


# ================================================================ V-0245-VT-10 게이트(CONDITIONAL = 통과)
def test_vt10_passing_single_place():
    from esl_platform.api.services import common
    from esl_platform.core import verdicts

    assert common.PASSING == verdicts.PASSING == ("PASS", "CONDITIONAL")
    assert verdicts.is_passing("CONDITIONAL") and verdicts.is_passing("PASS")
    assert not any(verdicts.is_passing(x) for x in ("FAIL", "UNDETERMINED", None, "LEGACY"))
    from esl import val_metrics as vm                            # 코어(v0.24.5 통합 후 항상 있음 — skip 없음)

    assert tuple(vm.PASSING) == verdicts.PASSING


GATE_FILES = ("backend/esl_platform/api/services/library.py", "backend/esl_platform/api/services/doe.py",
              "backend/esl_platform/api/services/opt.py", "backend/esl_platform/api/services/cases.py",
              "backend/esl_platform/core/run_all.py", "worker/esl_worker/register.py",
              "backend/esl_platform/api/services/library_export.py", "backend/esl_platform/api/services/results.py")
DIRECT_PASS = re.compile(r"""(?:verdict|status)(?:"\]|'\]|["'`)])?\s*(?:==|!=|in \(|not in \()\s*["']PASS["']""")


def test_vt10_no_direct_pass_compare_in_gates():
    """게이트 지점은 verdict·status 와 "PASS" 직접 비교 0건(is_passing 만)."""
    bad = []
    for rel in GATE_FILES:
        for n, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
            if DIRECT_PASS.search(line):
                bad.append(f"{rel}:{n}: {line.strip()}")
    assert not bad, bad


def test_vt10_eligibility_and_register_gate(client, engine, case):
    from esl_platform.api.services import library as lib

    assert lib.eligibility({"scheme": "disp_primary/2", "status": "CONDITIONAL", "verdict": "CONDITIONAL"}) == (True, None)
    assert lib.eligibility({"scheme": "disp_primary/2", "verdict": "CONDITIONAL"}) == (True, None)
    assert lib.eligibility({"scheme": "disp_primary/1", "status": "PASS"}) == (True, None)
    assert lib.eligibility({"scheme": "disp_primary/1", "status": "FAIL"}) == (False, "FAIL")
    assert lib.eligibility({"status": "CONDITIONAL"}) == (False, "LEGACY")
    # 등록 게이트: 조건부 PASS 는 VALIDATION_NOT_PASS 가 아니다(스냅샷이 없어 그 다음 규칙 409 run_snapshot 까지 간다)
    sc = seed_run(engine, case["id"], verdict="CONDITIONAL", val_extra={"scheme": "disp_primary/2", "mac": 0.93})
    r = client.post(f"{API}/library/entries", json={"esl_run_id": sc["run_id"]}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["run_snapshot"]
    sf = seed_run(engine, case["id"], verdict="FAIL", val_extra={"scheme": "disp_primary/2"})
    r = client.post(f"{API}/library/entries", json={"esl_run_id": sf["run_id"]}, headers=W)
    assert r.status_code == 422 and _code(r) == "VALIDATION_NOT_PASS"


def test_vt10_case_list_library_status(client, engine, case):
    from esl_platform.api.services import cases as svc

    cond = {"scheme": "disp_primary/2", "status": "CONDITIONAL", "verdict": "CONDITIONAL"}
    assert svc.library_summary({"count": 1, "latest": {"id": "e", "quality": cond, "registered_at": None}})["latest_status"] \
        == "CONDITIONAL"
    ok = {"scheme": "disp_primary/1", "status": "PASS", "verdict": "PASS"}
    assert svc.library_summary({"count": 1, "latest": {"id": "e", "quality": ok, "registered_at": None}})["latest_status"] == "PASS"


def test_vt10_schema_literals_include_conditional():
    from esl_platform.api import schemas as sch

    for model, flds in (("ValidationOut", ("verdict", "status")), ("ValidationSourceRow", ("status",)),
                        ("RunAllOut", ("verdict",)), ("CaseLibraryOut", ("latest_status",))):
        cls = getattr(sch, model)
        for fld in flds:
            assert "CONDITIONAL" in str(cls.model_fields[fld].annotation), (model, fld)
    assert get_args(sch.LoadGradeLit)[:2] == ("PASS", "CONDITIONAL")


# ================================================================ V-0245-VT-11 묶음 등급
def test_vt11_grades_order_and_confirm():
    from esl_platform.api.services import library as lib

    assert lib.LOAD_GRADES == ("PASS", "CONDITIONAL", "caution", "not_comparable", "UNDETERMINED", "FAIL", "NO_RESULT")
    cond = {"available": True, "status": "CONDITIONAL", "limits": [], "comparable": True}
    assert lib._row_grade(cond, {}) == ("CONDITIONAL", ["CONDITIONAL"])
    # 새 행(CONDITIONAL) + reaction_warned → 이중 표식 없이 CONDITIONAL
    assert lib._row_grade({**cond, "reaction_warned": True}, {})[0] == "CONDITIONAL"
    # 옛 행(PASS) + reaction_warned → caution(확인 필요 유지)
    assert lib._row_grade({"available": True, "status": "PASS", "limits": [], "reaction_warned": True,
                           "comparable": True}, {})[0] == "caution"
    # 조건부 + 한계 caution → 나쁜 쪽(caution)
    assert lib._row_grade({**cond, "limits": ["X"]}, {"X": "caution"}) == ("caution", ["CONDITIONAL", "caution"])
    sm = lib._source_summary("full", "L", [{"entry_id": "a", "grade": "CONDITIONAL", "load_available": True},
                                           {"entry_id": "b", "grade": "PASS", "load_available": True}])
    assert sm["worst"] == "CONDITIONAL" and sm["needs_confirm"] is False
    sm = lib._source_summary("full", "L", [{"entry_id": "a", "grade": "caution", "load_available": True}])
    assert sm["needs_confirm"] is True


def test_vt11_check_load_source_conditional_no_ack(client, engine, esl_root, inputs_root):
    """조건부 PASS 출처 선택 = ack 없이 진행(스냅샷에 등급 기록), caution 은 그대로 확인 필요."""
    from esl_platform.api.services import library as lib
    from opt_support import make_case, plate, seed_opt_entry
    from test_load_source_api import BF_DOC, link, rows_ok

    make_case(engine, inputs_root, "c1")
    m = plate()
    e = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    w = {"case_dir": Path(esl_root) / "f_c1"}
    link(engine, w, e, rows_ok(bforce={"verdict": "CONDITIONAL", "verdict_scheme": "disp_primary/2",
                                       "cond_reasons": ["MAC"], "comparable": True}), loads={"bforce": BF_DOC})
    ctx = client.app.state.ctx if hasattr(client.app.state, "ctx") else None
    r = client.get(f"{API}/library/entries/sources", params={"ids": e}, headers=R)
    assert r.status_code == 200, r.text
    bf = next(s for s in r.json()["sources"] if s["key"] == "bforce")
    assert bf["entries"][0]["status"] == "CONDITIONAL" and bf["entries"][0]["grade"] == "CONDITIONAL"
    assert bf["worst"] == "CONDITIONAL" and bf["needs_confirm"] is False
    if ctx is not None:
        chk = lib.check_load_source(ctx, "bforce", [e], None)                      # ack 없이 통과
        assert chk["worst"] == "CONDITIONAL" and chk["entries"][0]["status"] == "CONDITIONAL"


# ================================================================ 프런트 픽스처(real_v0245.json) 덤프
def test_vt_dump_real_v0245_fixture(client, engine, case):
    """실제 백엔드 응답 형식(ValidationOut·출처 행)을 frontend/src/__tests__/fixtures/real_v0245.json 으로 덤프한다
    (VT_DUMP=<경로> 일 때만 쓴다 — 응답 형식이 바뀌면 다시 만든다). 코어 문서 형식은 계약 §1.5 의 픽스처(코어 묶음 C 통합 뒤
    워커 e2e 덤프로 교체). 쓰지 않을 때도 응답의 새 필드 형식을 확인한다."""
    s = seed_run(engine, case["id"], verdict="CONDITIONAL",
                 val_extra={"scheme": "disp_primary/2", "mac": 0.9312, "cond_reasons": ["DISP_RMS", "MAC"],
                            "disp_rms_rel": 0.072, "disp_max_rel": 0.038})
    vid = s["validation_id"]
    with engine.begin() as c:
        c.execute(text("UPDATE validations SET criteria = CAST(:c AS jsonb) WHERE id=:i"), {"i": vid, "c": json.dumps({
            "disp_rms_rel_max": 0.05, "disp_rms_rel_cond_max": 0.1, "mac_min": 0.95, "mac_cond_min": 0.9,
            "disp_max_rel_max": 0.05, "reaction_rel_max": 0.1, "reaction_warn_rel": 0.05})})
    rows = rows_full_bf_fint_unavail()
    rows[3] = sj_row("full", verdict="CONDITIONAL", verdict_scheme="disp_primary/2", cond_reasons=["DISP_RMS", "MAC"], **{
        k: v for k, v in FULL_ROW.items() if k != "verdict"})
    rows[4] = sj_row("bforce", verdict="FAIL", verdict_scheme="disp_primary/2", fail_reasons=["MAC"], reaction_role="info",
                     comparable=False, limits=["BF_TIE_MISSING"], limit_text=["tie 체결력 미포함"])
    rows[5] = sj_row("fint", verdict="CONDITIONAL", verdict_scheme="disp_primary/2", cond_reasons=["REACTION"],
                     reaction_role="judge", reaction_tol=0.1, reaction_tol_key="validation.sources.reaction_tol",
                     reaction_warn=0.05, reaction_warned=True, comparable=True)
    seed_sources(os.path.join(case["dir"], "05_val"), rows)
    val = client.get(f"{API}/validations/{vid}", headers=R)
    srcs = client.get(f"{API}/validations/{vid}/sources", headers=R)
    assert val.status_code == srcs.status_code == 200
    v, sj = val.json(), srcs.json()
    assert v["mac"] == pytest.approx(0.9312) and v["cond_reasons"] == ["DISP_RMS", "MAC"] and v["status"] == "CONDITIONAL"
    by = {r["key"]: r for r in sj["rows"]}
    assert by["fint"]["status"] == "CONDITIONAL" and by["fint"]["reaction_warned"] is True
    assert by["bforce"]["status"] == "FAIL" and by["bforce"]["fail_reasons"] == ["MAC"]
    out = os.environ.get("VT_DUMP")
    if out:
        Path(out).write_text(json.dumps({"validation": v, "sources": sj}, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ §11 화면 출처 숨김(설정 ui.hidden_sources)
def test_vt11_hidden_sources_setting_and_version(client):
    from esl_platform.core.config import UiCfg

    assert list(UiCfg.model_fields["hidden_sources"].default_factory()) == ["bforce", "fint", "jig"]        # 기본
    r = client.get(f"{API}/version", headers=R)
    assert r.status_code == 200 and r.json()["ui"]["hidden_sources"] == ["bforce", "fint", "jig"]
    for rel in ("config/esl_platform.example.yaml", "config/esl_platform.prod.example.yaml"):
        assert "hidden_sources: [bforce, fint, jig]" in (REPO / rel).read_text(encoding="utf-8")


def test_vt11_hidden_sources_empty_override():
    from esl_platform.core.config import UiCfg

    base = dict(max_artifact_bytes=1, max_preview_points=10, poll_job_ms=100, poll_queue_ms=100)
    assert UiCfg(**base).hidden_sources == ["bforce", "fint", "jig"]
    assert UiCfg(**base, hidden_sources=[]).hidden_sources == []


def test_vt11_hidden_sources_unknown_key_warns_once(settings_dict, tmp_path, monkeypatch, caplog):
    """v0.24.5 Verifier: ui.hidden_sources 오타 키(화면이 조용히 무시) → 거부 안 함, 설정 경고 1개 → 백엔드 시작 로그 1줄.
    알려진 키(코어 출처 표 KEYS)·[]·기본 = 경고 없음."""
    import logging

    import yaml
    from esl_platform.api import main as api_main
    from esl_platform.core import config as cfgm
    from esl_platform.core.db import engine as dbe

    def with_hidden(v):
        return {**settings_dict, "ui": {**settings_dict["ui"], "hidden_sources": v}}

    bad = with_hidden(["bforce", "fnt", "jig_fixed"])
    lc = cfgm.load_config_dict(bad, environ={})
    assert lc.ok and lc.settings.ui.hidden_sources == ["bforce", "fnt", "jig_fixed"]          # 거부 안 함(값 그대로 전달)
    hw = [w for w in lc.warnings if w.key == "ui.hidden_sources"]
    assert len(hw) == 1 and hw[0].message.startswith("ui.hidden_sources 에 모르는 출처 키 ['fnt', 'jig_fixed']")
    for d in (settings_dict, with_hidden([]), with_hidden(["bforce", "fint", "jig"]),
              with_hidden(["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"])):
        assert [w for w in cfgm.load_config_dict(d, environ={}).warnings if w.key == "ui.hidden_sources"] == []
    # 시작 로그: _app_from_env 가 설정 경고를 1줄씩 남긴다(DB 엔진·앱 생성은 대역)
    p = tmp_path / "esl_platform_bad.yaml"
    p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv(cfgm.ENV_CONFIG, str(p))
    monkeypatch.delenv(cfgm.ENV_PROFILE, raising=False)
    monkeypatch.setenv(lc.settings.database.url_env, "postgresql+psycopg://unused@127.0.0.1:1/unused")
    monkeypatch.setattr(dbe, "make_engine", lambda url, pool: object())
    monkeypatch.setattr(api_main, "build_context", lambda config, engine: config)
    monkeypatch.setattr(api_main, "create_app", lambda ctx, bind_host=None: ctx)
    with caplog.at_level(logging.WARNING, logger="esl_platform.api"):
        got = api_main._app_from_env()
    lines = [r.getMessage() for r in caplog.records if "ui.hidden_sources" in r.getMessage()]
    assert got.settings.ui.hidden_sources == ["bforce", "fnt", "jig_fixed"]
    assert len(lines) == 1 and lines[0].startswith("설정 경고: ui.hidden_sources 에 모르는 출처 키")
