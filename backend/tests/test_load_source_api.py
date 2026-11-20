"""v0.24.4 P3 B3 — 하중 출처 선택(계약 esl_jig_case.md §9·esl_validate_sources.md §12.2, V-0244-JIG-14·V-0244-VAL-7).

`load_source`(스터디 DoeStudyIn·비드 최적화 OptRunIn)·`load_source_ack`·묶음 판정 `GET /library/entries/sources?ids=`.
출처 판정은 항목 검증의 05_val/sources.json(형식 esl/val_sources/1 픽스처), 하중 존재는 Case runs/<run>/04_esl 파일(+진단 json).
출처 계획 표는 실제 코어 ``esl.val_src``. 코어 A3(source_load)는 쓰지 않는다(백엔드는 파일 존재·진단 json 만 본다).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from doe_support import R, W, body, doe_settings_dict, record_paicad, upload_step
from esl_test_support import API
from opt_support import make_case, plate, run_body, seed_opt_entry
from sqlalchemy import text
from test_val_src_api import FULL_ROW, sj_row


@pytest.fixture()
def settings_dict(tmp_path):
    return doe_settings_dict(tmp_path)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from esl_platform.api.services import doe as svc

    svc.reset_status_cache()
    yield
    svc.reset_status_cache()


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    a = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    b = seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2)
    record_paicad(engine)
    return {"a": a, "b": b, "mesh": m, "case_dir": Path(esl_root) / "f_c1"}


def _code(r):
    return r.json()["detail"]["code"]


def _run_val(engine, eid):
    with engine.connect() as c:
        return c.execute(text("SELECT e.esl_run_id, v.id FROM library_entries e JOIN validations v ON "
                              "v.esl_run_id = e.esl_run_id WHERE e.id=:i").bindparams(i=eid)).one()


def link(engine, w, eid, rows, *, loads: dict[str, dict | None] | None = None):
    """항목의 검증을 항목에 잇고(library_entries.validation_id), 그 검증 스냅샷 05_val/sources.json 을 쓰고, 출처 하중 파일을
    runs/<run>/04_esl 에 둔다. loads = {파일 접두(jig·bforce …): 진단 json | None(없음 — json 안 씀)}."""
    run_id, vid = _run_val(engine, eid)
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET validation_id=:v WHERE id=:i"), {"v": vid, "i": eid})
        c.execute(text("UPDATE validations SET scheme='disp_primary/1' WHERE id=:v"), {"v": vid})
    snap = w["case_dir"] / "runs" / run_id / "05_val"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "sources.json").write_text(json.dumps({"schema": "esl/val_sources/1", "default": "full", "enabled": True,
                                                    "rows": rows}), encoding="utf-8")
    (snap / "platform_validation_id.txt").write_text(vid, encoding="utf-8")
    esl = w["case_dir"] / "runs" / run_id / "04_esl"
    esl.mkdir(parents=True, exist_ok=True)
    for stem, doc in (loads or {}).items():
        np.savez_compressed(esl / f"{stem}.npz", f=np.zeros((2, 3)))
        if doc is not None:
            (esl / f"{stem}.json").write_text(json.dumps(doc), encoding="utf-8")
    return run_id, vid


def rows_ok(**over):
    """full PASS + bforce PASS(비교 가능) + fint 결과 없음 + 지그 세 행 PASS."""
    ok = dict(verdict="PASS", comparable=True)
    r = {"full": sj_row("full", **FULL_ROW), "bforce": sj_row("bforce", **ok),
         "fint": sj_row("fint", "unavailable", code="FINT_NO_DATA", reason="내력 하중 자료 없음"),
         "jig": sj_row("jig", **ok), "jig_disp": sj_row("jig_disp", **ok), "jig_spring": sj_row("jig_spring", **ok)}
    for k, v in over.items():
        r[k] = sj_row(k, **v) if isinstance(v, dict) else v
    return [r[k] for k in ("jig", "jig_disp", "jig_spring", "full", "bforce", "fint")]


BF_DOC = {"grade": "A", "status": "ok"}
JIG_FIXED_TR = {"method": "fixed", "tie_dofs": "translation", "status": "ok"}


def link_both(engine, w, rows=None, loads=None):
    for e in (w["a"], w["b"]):
        link(engine, w, e, rows if rows is not None else rows_ok(), loads=loads)


def create_opt(client, w, **kw):
    return client.post(f"{API}/opt/runs", json=run_body([w["a"], w["b"]], **kw), headers=W)


def job_params(engine, jid):
    with engine.connect() as c:
        return c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": jid}).scalar_one()


# ================================================================ 묶음 판정 GET /library/entries/sources
def test_entries_sources_bundle(client, engine, world):
    link_both(engine, world, rows_ok(bforce={"verdict": "FAIL", "fail_reasons": ["DISP_RMS"]}),
              loads={"bforce": BF_DOC, "jig": JIG_FIXED_TR})
    link(engine, world, world["b"], rows_ok(), loads={"bforce": BF_DOC, "jig": JIG_FIXED_TR})        # b 는 bforce PASS
    r = client.get(f"{API}/library/entries/sources", params={"ids": f"{world['a']},{world['b']}"}, headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ids"] == [world["a"], world["b"]] and [i["entry_id"] for i in d["items"]] == d["ids"]
    keys = ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    assert [s["key"] for s in d["sources"]] == keys and all([r_["key"] for r_ in i["rows"]] == keys for i in d["items"])
    by = {s["key"]: s for s in d["sources"]}
    assert by["full"]["worst"] == "PASS" and by["full"]["needs_confirm"] is False
    assert by["full"]["entries"][0]["load_available"] is True and by["full"]["label"]       # legacy = 항목 자신의 하중
    assert by["bforce"]["worst"] == "FAIL" and by["bforce"]["needs_confirm"] is True
    assert by["bforce"]["entries"][0]["grade"] == "FAIL" and by["bforce"]["entries"][1]["grade"] == "PASS"
    assert by["fint"]["worst"] == "NO_RESULT" and by["fint"]["unavailable_entry_ids"] == [world["a"], world["b"]]
    assert by["jig"]["worst"] == "PASS" and by["jig"]["unavailable_entry_ids"] == []
    assert by["jig_disp"]["unavailable_entry_ids"] == [world["a"], world["b"]]               # 파일 없음 = 하중 없음
    row = d["items"][0]["rows"][4]
    assert row["load_available"] is True and row["grade"] == "FAIL" and row["flags"] == ["FAIL"] and row["status"] == "FAIL"
    assert row["opt_code"] is None and row["opt_reason"] is None                              # 지그 아닌 행 = 전달 불가 안내 없음
    jrow = d["items"][0]["rows"][0]
    assert jrow["opt_code"] is None                                                           # 병진 구속 + 고정 지그 = 비드 최적화로 전달 가능
    fi = d["items"][0]["rows"][5]
    assert fi["load_available"] is False and fi["load_code"] == "V3D_SRC_NOT_RUN" and fi["load_reason"]
    assert client.get(f"{API}/library/entries/sources", params={"ids": "nope"}, headers=R).status_code == 404
    assert client.get(f"{API}/library/entries/sources", params={"ids": ""}, headers=R).status_code == 422
    assert client.get(f"{API}/library/entries/sources", params={"ids": world["a"]}).status_code == 401
    # 경로 충돌 없음 — 항목 단건 조회는 그대로
    assert client.get(f"{API}/library/entries/{world['a']}", headers=R).status_code == 200


def test_entries_sources_grades_not_comparable_caution_and_no_validation(client, engine, world):
    link(engine, world, world["a"], rows_ok(bforce={"verdict": "PASS", "comparable": False, "limits": ["BF_TIE_MISSING"]},
                                            jig={"verdict": "PASS", "comparable": True, "limits": ["JIG_DISP_FROM_TARGET"]}),
         loads={"bforce": BF_DOC, "jig": JIG_FIXED_TR})
    # b: validation_id 없음 → 결과 없음(NO_RESULT) — 하중 파일은 있음
    run_id, _ = _run_val(engine, world["b"])
    (world["case_dir"] / "runs" / run_id / "04_esl").mkdir(parents=True)
    np.savez_compressed(world["case_dir"] / "runs" / run_id / "04_esl" / "bforce.npz", f=np.zeros((2, 3)))
    r = client.get(f"{API}/library/entries/sources", params={"ids": f"{world['a']},{world['b']}"}, headers=R)
    by = {s["key"]: s for s in r.json()["sources"]}
    assert by["bforce"]["entries"][0]["grade"] == "not_comparable" and by["bforce"]["entries"][0]["comparable"] is False
    assert by["bforce"]["entries"][1]["grade"] == "NO_RESULT" and by["bforce"]["entries"][1]["load_available"] is True
    assert by["bforce"]["worst"] == "NO_RESULT"
    assert by["jig"]["entries"][0]["grade"] == "caution" and by["jig"]["entries"][0]["flags"] == ["caution"]


def test_load_state_doc_blocks_and_grades_order():
    from esl_platform.api.schemas import LoadGradeLit
    from esl_platform.api.services import library as lib
    from typing import get_args

    assert tuple(get_args(LoadGradeLit)) == lib.LOAD_GRADES
    row = {"legacy": False, "load": ("esl", "bforce.npz", "f"), "doc": ("esl", "bforce.json"), "na": "V3D_SRC_NOT_RUN"}
    assert lib._row_grade({"available": True, "status": "PASS", "limits": [], "comparable": True}, {})[0] == "PASS"
    assert lib._row_grade({"available": True, "status": "FAIL", "limits": ["X"], "comparable": False}, {"X": "not_comparable"}) \
        == ("FAIL", ["not_comparable", "FAIL"])
    assert lib._row_grade({"available": False, "status": None}, {})[0] == "NO_RESULT"
    assert lib._row_grade({"available": True, "status": "LEGACY", "limits": [], "comparable": None}, {})[0] == "NO_RESULT"
    assert lib._row_grade({"available": True, "status": "PASS", "limits": [], "reaction_warned": True,
                           "comparable": True}, {})[0] == "caution"
    assert lib._find_load({**row, "legacy": True}, [])[0] == ""
    assert lib._find_load({**row, "load": None}, [])[2] == "V3D_SRC_NOT_RUN"


def test_doc_status_or_grade_none_means_no_load(client, engine, world, tmp_path):
    link_both(engine, world, loads={"bforce": {"grade": "none", "code": "BF_NO_DATA", "reason": "경계력 자료 없음"}})
    r = client.get(f"{API}/library/entries/sources", params={"ids": world["a"]}, headers=R)
    bf = next(s for s in r.json()["sources"] if s["key"] == "bforce")["entries"][0]
    assert bf["load_available"] is False and bf["load_code"] == "BF_NO_DATA" and bf["load_reason"] == "경계력 자료 없음"


# ================================================================ 비드 최적화 POST /opt/runs
def test_opt_without_load_source_is_unchanged(client, engine, world):
    r = create_opt(client, world)
    assert r.status_code == 201, r.text
    o = r.json()
    p = job_params(engine, o["job"]["id"])
    assert "load_source" not in p and "load_source" not in p["options"] and "load_source_check" not in p["options"]
    assert "load_source" not in o["options"]
    assert set(p["options"]) == {"objective_norm", "load_strategy", "k", "supports"}
    # ack 만 있고 출처가 없으면 무시(지금과 같음)
    r = create_opt(client, world, load_source_ack=True)
    assert r.status_code == 201 and "load_source" not in job_params(engine, r.json()["job"]["id"])


def test_opt_unknown_key_and_s2_jig_static(client, engine, world):
    r = create_opt(client, world, load_source="nope")
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "INVALID_PARAMS" and d["keys"] == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    r = create_opt(client, world, scenario="S2", template_id="x", load_source="jig")
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNSUPPORTED" and "템플릿" in d["reason"]


def test_opt_confirm_flow_bforce(client, engine, world):
    link_both(engine, world, rows_ok(bforce={"verdict": "FAIL", "fail_reasons": ["DISP_RMS"], "comparable": False,
                                             "limits": ["BF_TIE_MISSING"]}), loads={"bforce": BF_DOC})
    r = create_opt(client, world, load_source="bforce")
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNCONFIRMED" and d["worst"] == "FAIL"
    assert [e["entry_id"] for e in d["entries"]] == [world["a"], world["b"]] and d["entries"][0]["status"] == "FAIL"
    assert d["entries"][0]["comparable"] is False and d["entries"][0]["flags"] == ["not_comparable", "FAIL"]
    r = create_opt(client, world, load_source="bforce", load_source_ack=False)
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNCONFIRMED"
    r = create_opt(client, world, load_source="bforce", load_source_ack=True)
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["options"]["load_source"] == "bforce"
    chk = o["options"]["load_source_check"]
    assert chk["key"] == "bforce" and chk["worst"] == "FAIL"
    assert chk["entries"][0] == {"entry_id": world["a"], "status": "FAIL", "comparable": False,
                                 "validation_id": _run_val(engine, world["a"])[1]}
    p = job_params(engine, o["job"]["id"])
    assert p["load_source"] == "bforce" and p["options"]["load_source"] == "bforce"       # 워커 읽는 키


def test_opt_pass_source_needs_no_ack_and_full_is_default_gate(client, engine, world):
    link_both(engine, world, loads={"bforce": BF_DOC})
    r = create_opt(client, world, load_source="bforce")
    assert r.status_code == 201, r.text
    assert r.json()["options"]["load_source_check"]["worst"] == "PASS"
    r = create_opt(client, world, load_source="full")                      # legacy 출처: 항상 하중 있음, 판정 = full PASS
    assert r.status_code == 201 and job_params(engine, r.json()["job"]["id"])["load_source"] == "full"


def test_opt_unavailable_when_no_load(client, engine, world, esl_root, inputs_root):
    make_case(engine, inputs_root, "c2")                                    # 같은 Case 의 다른 실행 폴더도 찾으므로 b 는 다른 Case
    world["b"] = seed_opt_entry(engine, esl_root, "c2", world["mesh"], "twist", scene_no=2)
    link(engine, world, world["a"], rows_ok(), loads={"bforce": BF_DOC})
    link(engine, {**world, "case_dir": Path(esl_root) / "f_c2"}, world["b"], rows_ok(), loads={})     # b 는 bforce 하중 파일 없음
    r = create_opt(client, world, load_source="bforce")
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNAVAILABLE" and d["entry_ids"] == [world["b"]]
    assert set(d["reasons"]) == {world["b"]} and d["reasons"][world["b"]]
    # ack 로도 못 넘김(하중 없음은 차단)
    r = create_opt(client, world, load_source="bforce", load_source_ack=True)
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNAVAILABLE"
    r = create_opt(client, world, load_source="fint", load_source_ack=True)
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNAVAILABLE"


def test_opt_jig_translation_fixed_only(client, engine, world):
    link_both(engine, world, loads={"jig": JIG_FIXED_TR, "jig_disp": {"method": "prescribed", "tie_dofs": "translation", "status": "ok"},
                                    "jig_spring": {"method": "spring", "tie_dofs": "translation", "status": "ok"}})
    r = create_opt(client, world, load_source="jig")
    assert r.status_code == 201, r.text
    assert job_params(engine, r.json()["job"]["id"])["load_source"] == "jig"
    for key in ("jig_disp", "jig_spring"):
        r = create_opt(client, world, load_source=key, load_source_ack=True)
        d = r.json()["detail"]
        assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNSUPPORTED", key
        assert set(d["entry_ids"]) == {world["a"], world["b"]} and "병진 구속 + 고정" in d["reason"]
    # normal 구속 성분 지그 = 미지원
    link_both(engine, world, loads={"jig": {"method": "fixed", "tie_dofs": "normal", "status": "ok"}})
    r = create_opt(client, world, load_source="jig", load_source_ack=True)
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNSUPPORTED" and "법선" in r.json()["detail"]["reason"]
    # 미지원은 확인(ack)으로 넘길 수 없고, 확인 요청보다 먼저
    link_both(engine, world, rows_ok(jig={"verdict": "FAIL", "fail_reasons": ["DISP_RMS"]}),
              loads={"jig": {"method": "fixed", "tie_dofs": "normal", "status": "ok"}})
    r = create_opt(client, world, load_source="jig")
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNSUPPORTED"


def test_entries_sources_pre_announces_opt_unsupported(client, engine, world):
    """tie_dofs=normal 지그는 비드 최적화 생성 때 422 UNSUPPORTED — 같은 규칙을 묶음 응답이 미리 알린다(opt_code·opt_reason). 스터디용 필드(load_*)는 불변."""
    link_both(engine, world, loads={"jig": {"method": "fixed", "tie_dofs": "normal", "status": "ok"},
                                    "jig_disp": {"method": "prescribed", "tie_dofs": "translation", "status": "ok"}})
    r = client.get(f"{API}/library/entries/sources", params={"ids": f"{world['a']},{world['b']}"}, headers=R)
    assert r.status_code == 200, r.text
    for it in r.json()["items"]:
        jig, disp, full = it["rows"][0], it["rows"][1], it["rows"][3]
        assert jig["load_available"] is True and jig["opt_code"] == "LOAD_SOURCE_UNSUPPORTED" and "법선" in jig["opt_reason"]
        assert disp["opt_code"] == "LOAD_SOURCE_UNSUPPORTED" and "병진 구속 + 고정" in disp["opt_reason"]   # 강제 변위 = 항상 미지원
        assert full["opt_code"] is None and full["opt_reason"] is None
    # 생성 때 서버 판정(422)과 같은 사유
    r2 = create_opt(client, world, load_source="jig", load_source_ack=True)
    assert r2.json()["detail"]["reason"] == r.json()["items"][0]["rows"][0]["opt_reason"]


def test_opt_retry_keeps_load_source(client, engine, world):
    link_both(engine, world, loads={"bforce": BF_DOC})
    o = create_opt(client, world, load_source="bforce").json()
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='FAILED', queue_seq=NULL, failure_code='X', finished_at=now() WHERE id=:i"),
                  {"i": o["job"]["id"]})
    r = client.post(f"{API}/jobs/{o['job']['id']}/retry", headers=W)
    assert r.status_code in (200, 201, 202), r.text
    assert job_params(engine, r.json()["id"])["load_source"] == "bforce"


# ================================================================ 강성 스터디 POST /doe/studies
def create_study(client, world, **kw):
    uid = upload_step(client)
    return client.post(f"{API}/doe/studies", json=body([world["a"], world["b"]], uid, **kw), headers=W)


def test_study_without_load_source_is_unchanged(client, engine, world):
    r = create_study(client, world)
    assert r.status_code == 201, r.text
    s = r.json()
    p = job_params(engine, s["job"]["id"])
    assert "load_source" not in p["doe"] and "load_source_check" not in p["doe"]
    assert "load_source" not in s["inputs"] and "load_source_check" not in s["inputs"]
    r = create_study(client, world, load_source_ack=True)                 # ack 만 = 무시
    assert r.status_code == 201 and "load_source" not in job_params(engine, r.json()["job"]["id"])["doe"]


def test_study_confirm_flow_and_snapshot(client, engine, world):
    link_both(engine, world, rows_ok(bforce={"verdict": "FAIL", "fail_reasons": ["DISP_RMS"]}), loads={"bforce": BF_DOC})
    r = create_study(client, world, load_source="bforce")
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNCONFIRMED" and d["worst"] == "FAIL" and len(d["entries"]) == 2
    r = create_study(client, world, load_source="bforce", load_source_ack=True)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["load_source"] == "bforce" and s["inputs"]["load_source_check"]["worst"] == "FAIL"
    p = job_params(engine, s["job"]["id"])
    assert p["doe"]["load_source"] == "bforce" and p["doe"]["load_source_check"] == s["inputs"]["load_source_check"]
    assert p["doe"]["rank"]["metric"] == "jig"                              # 순위 설정 스냅샷은 그대로(코어가 load_source 로 기준 결정)
    # 복제 = 원 스터디의 하중 출처 유지
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='SUCCEEDED', queue_seq=NULL, finished_at=now() WHERE id=:i"), {"i": s["job"]["id"]})


def test_study_unavailable_unknown_key_compare(client, engine, world):
    link_both(engine, world, loads={})
    r = create_study(client, world, load_source="bforce", load_source_ack=True)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "LOAD_SOURCE_UNAVAILABLE" and set(d["entry_ids"]) == {world["a"], world["b"]}
    r = create_study(client, world, load_source="nope")
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS"
    r = create_study(client, world, scenario="compare", load_source="full")
    assert r.status_code == 422 and _code(r) == "INVALID_PARAMS" and "비교" in r.json()["detail"]["message"]


def test_study_jig_source_adds_method_to_rank_snapshot(tmp_path, engine, fake_dashboard, clock, esl_root, inputs_root):
    from test_doe_compare_api import _app

    d = doe_settings_dict(tmp_path, bead_doe={"enabled": True, "paicad": {"exe": str(tmp_path / "tools" / "paicad")},
                                              "settings_cache_s": 0, "rank": {"jig": {"methods": ["fixed"]}}})
    make_case(engine, inputs_root, "c1")
    m = plate()
    w = {"a": seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1),
         "b": seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2), "case_dir": Path(esl_root) / "f_c1"}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        link_both(engine, w, loads={"jig": JIG_FIXED_TR, "jig_spring": {"method": "spring", "tie_dofs": "translation"}})
        r = create_study(c, w)
        assert r.status_code == 201
        assert job_params(engine, r.json()["job"]["id"])["doe"]["rank"]["jig"]["methods"] == ["fixed"]       # 출처 없음 = 설정 그대로
        r = create_study(c, w, load_source="jig_spring")
        assert r.status_code == 201, r.text
        s = r.json()
        p = job_params(engine, s["job"]["id"])
        assert p["doe"]["rank"]["jig"]["methods"] == ["fixed", "spring"] and p["doe"]["load_source"] == "jig_spring"
        assert p["doe"]["rank"]["schema"] == 2
        # 복제도 그 방식을 계산(지금 설정으로 갱신해도 methods 에 spring 유지)
        with engine.begin() as cx:
            cx.execute(text("UPDATE jobs SET state='SUCCEEDED', queue_seq=NULL, finished_at=now() WHERE id=:i"),
                       {"i": s["job"]["id"]})
            cx.execute(text("UPDATE bead_does SET phase='READY' WHERE id=:i"), {"i": s["id"]})
        r = c.post(f"{API}/doe/studies/{s['id']}/clone", json={}, headers=W)
        assert r.status_code == 201, r.text
        cp = job_params(engine, r.json()["job"]["id"])
        assert cp["doe"]["load_source"] == "jig_spring" and cp["doe"]["rank"]["jig"]["methods"] == ["fixed", "spring"]
        assert r.json()["inputs"]["load_source"] == "jig_spring"


def test_study_jig_source_with_jig_disabled(tmp_path, engine, fake_dashboard, clock, esl_root, inputs_root):
    from test_doe_compare_api import _app

    d = doe_settings_dict(tmp_path, bead_doe={"enabled": True, "paicad": {"exe": str(tmp_path / "tools" / "paicad")},
                                              "settings_cache_s": 0, "rank": {"metric": "solve", "jig": {"enabled": False}}})
    make_case(engine, inputs_root, "c1")
    m = plate()
    w = {"a": seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1),
         "b": seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2), "case_dir": Path(esl_root) / "f_c1"}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        link_both(engine, w, loads={"jig": JIG_FIXED_TR})
        r = create_study(c, w, load_source="jig", load_source_ack=True)
        dd = r.json()["detail"]
        assert r.status_code == 422 and dd["code"] == "LOAD_SOURCE_UNAVAILABLE" and "rank.jig.enabled" in dd["reasons"][w["a"]]


# ================================================================ OpenAPI
def test_openapi_has_load_source_keys(client):
    spec = client.get(f"{API}/openapi.json").json() if client.get(f"{API}/openapi.json").status_code == 200 else None
    if spec is None:
        pytest.skip("openapi 경로 없음")
    sch = spec["components"]["schemas"]
    for name in ("OptRunIn", "DoeStudyIn", "DoeCheckIn"):
        props = sch[name]["properties"]
        assert "load_source" in props and "load_source_ack" in props, name
    assert "/api/v1/library/entries/sources" in "".join(spec["paths"]) or any("entries/sources" in p for p in spec["paths"])
