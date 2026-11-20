"""v0.24.4 P2b W2 — Case 지그 tie 준비(계약 esl_jig_case.md §5.1, 시험 V-0244-JIG-8 워커 부분).

판정 표·캐시 키·기록·쓰기 검사(순수) + 가짜 ex 로 실행 분기(paicad·사본은 monkeypatch) + 가짜 paicad 실행 파일(tests/fake_paicad.py)로
ESL_SOLVE 통합: 첫 ESL = fixed-scan 1회·캐시 기록, 같은 입력 재실행 = 0회, 입력 바뀜 = 다시(이전 캐시는 _backup), 끔 = 호출 0, 실패 = ESL 계속.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from doe_worker_support import calls, doe_worker_settings, set_control, write_fake_paicad
from esl_test_support import API, H, create_case

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")


# ================================================================ 순수: 판정 표
def F(**kw: Any):
    from esl_worker.jig_prep import Facts

    base = dict(case_enabled=True, core_enabled=True, cache_have=False, paicad_ready=True)
    base.update(kw)
    return Facts(**base)


@pytest.mark.parametrize("kw,want", [
    ({"case_enabled": False}, ("none", None, "1")),                           # bead_doe.case_jig.enabled 거짓
    ({"core_enabled": False}, ("none", None, "2")),                           # 코어 jig.enabled 거짓
    ({"case_enabled": False, "core_enabled": False, "cache_have": True}, ("none", None, "1")),   # 위 행 우선
    ({"settings_error": "CONFIG_INVALID: x"}, ("skip", "SETTINGS", "2a")),
    ({"input_error": "Case 입력 rad 없음"}, ("skip", "NO_INPUT", "2b")),
    ({"cache_have": True}, ("none", None, "3")),                               # 캐시 일치 — paicad 상태와 무관
    ({"cache_have": True, "paicad_ready": False}, ("none", None, "3")),
    ({"paicad_ready": False}, ("skip", "PAICAD_UNAVAILABLE", "4")),
    ({}, ("fill", None, "5")),
])
def test_decide_table(kw, want):
    from esl_worker.jig_prep import decide

    d = decide(F(**kw))
    assert (d.action, d.cause, d.row) == want
    assert decide(F(**kw)) == d                                               # 순수 — 같은 사실 = 같은 판정


def test_decide_have_logs_and_last_row_always_matches():
    from esl_worker import jig_prep

    assert jig_prep.decide(F(cache_have=True)).note == "have"
    assert jig_prep.decide(F(case_enabled=False)).note is None
    assert jig_prep.DECIDE[-1][1](jig_prep.Facts()) is True
    assert {c for *_r, c, _n in jig_prep.DECIDE if c} <= set(jig_prep.SKIPPED_CAUSES)
    assert set(jig_prep.CAUSE_TEXT) == set(jig_prep.SKIPPED_CAUSES) | set(jig_prep.FAILED_CAUSES)


def test_status_codes():
    from esl_worker import jig_prep as jp

    assert jp.status_of(None) == "ok" and jp.code_of("ok") is None
    for c in jp.SKIPPED_CAUSES:
        assert jp.status_of(c) == "skipped" and jp.code_of("skipped") == "JIG_FIXED_SKIPPED"
    for c in jp.FAILED_CAUSES:
        assert jp.status_of(c) == "failed" and jp.code_of("failed") == "JIG_FIXED_FAILED"
    rec = jp.attempt_record(job_id="j", cause="TIMEOUT", detail=jp.detail_text("TIMEOUT", timeout=60), seconds=61.234, key="k",
                            part_id=7, fix_kinds=["A"], assem="in_place", n_nodes=None)
    assert rec["status"] == "failed" and rec["code"] == "JIG_FIXED_FAILED" and rec["seconds"] == 61.2
    assert "60" in rec["detail"] and jp.summary_of(rec)["cause"] == "TIMEOUT"


# ================================================================ 순수: 캐시 키·매니페스트
def test_cache_key_depends_on_files_part_and_kinds(tmp_path):
    from esl_worker import jig_prep as jp

    a, b = tmp_path / "a.rad", tmp_path / "inc" / "b.inc"
    b.parent.mkdir()
    a.write_text("x")
    b.write_text("y")
    m1 = jp.manifest_of([str(a), str(b)], str(tmp_path))
    assert [r["path"] for r in m1] == ["a.rad", "inc/b.inc"] and m1[0]["size"] == 1 and len(m1[0]["sha256"]) == 64
    k = jp.cache_key(m1, 7, ["INTER_TYPE2_MAIN", "INTER_TYPE2_SECONDARY"])
    assert k == jp.cache_key(jp.manifest_of([str(a), str(b)], str(tmp_path)), 7, ["INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"])
    assert k != jp.cache_key(m1, 8, ["INTER_TYPE2_MAIN", "INTER_TYPE2_SECONDARY"])        # 파트 id
    assert k != jp.cache_key(m1, 7, ["INTER_TYPE2_MAIN"])                                  # fix_kinds
    b.write_text("z")                                                                       # 내용(크기 같아도 sha256)
    assert k != jp.cache_key(jp.manifest_of([str(a), str(b)], str(tmp_path)), 7,
                             ["INTER_TYPE2_MAIN", "INTER_TYPE2_SECONDARY"])
    out = tmp_path.parent / "elsewhere.rad"                                                 # 루트 밖 = 절대경로
    out.write_text("q")
    assert jp.manifest_of([str(out)], str(tmp_path))[0]["path"] == str(out).replace(os.sep, "/")


def test_has_cache_needs_key_and_all_files(tmp_path):
    from esl_worker import jig_prep as jp

    d = Path(jp.fixed_dir(str(tmp_path)))
    assert not jp.has_cache(str(tmp_path), "k")
    d.mkdir(parents=True)
    (d / jp.NODES_JSON).write_text(json.dumps({"key": "k"}))
    assert not jp.has_cache(str(tmp_path), "k")                                            # paicad 산출 없음
    (d / "shell_scan.json").write_text("{}")
    (d / "fixed_nodes.npz").write_bytes(b"x")
    assert jp.has_cache(str(tmp_path), "k") and not jp.has_cache(str(tmp_path), "other")
    (d / jp.NODES_JSON).write_text("not json")
    assert not jp.has_cache(str(tmp_path), "k")


def test_guard_allows_only_case_jig_locations(tmp_path):
    from esl_worker import core_adapter, jig_prep as jp

    g = jp.make_guard(str(tmp_path))
    for ok in ("_jig/assem_full/x.rad", "_jig", "01_extract/jig_fixed/shell_scan.json", "01_extract/jig_prep.json"):
        assert g(str(tmp_path / ok)) == str(tmp_path / ok)
    for bad in ("01_extract/model.npz", "04_esl/f_eq.npz", "01_extract/jig_fixed_x", "_jigx/a", "../outside.rad",
                "01_input/main.rad", ""):
        with pytest.raises(core_adapter.CoreError) as ei:
            g(str(tmp_path / bad) if bad else str(tmp_path.parent))
        assert ei.value.code == "PATH_OUTSIDE_ROOT"


def test_write_record_and_backup_move(tmp_path):
    from esl_worker import jig_prep as jp

    rec = jp.attempt_record(job_id="j", cause=None, detail="", seconds=1.0, key="k", part_id=3, fix_kinds=["X"],
                            assem="staged", n_nodes=5)
    jp.write_record(str(tmp_path), rec)
    got = json.loads((tmp_path / "01_extract" / "jig_prep.json").read_text(encoding="utf-8"))
    assert got["status"] == "ok" and got["code"] is None and got["n_nodes"] == 5 and got["schema"] == "esl/jig_prep/1"
    d = Path(jp.fixed_dir(str(tmp_path)))
    d.mkdir(parents=True)
    (d / "a.txt").write_text("old")
    dest = jp._backup_move(str(tmp_path), "01_extract/jig_fixed")
    assert dest and not d.exists() and (Path(dest) / "a.txt").read_text() == "old" and "_backup" in dest
    assert jp._backup_move(str(tmp_path), "01_extract/jig_fixed") is None                  # 없으면 아무것도 안 함


# ================================================================ 가짜 ex 로 gather·run 분기
class FakeEx(SimpleNamespace):
    def _wait_tick(self, st):
        return None


def _fake_ex(tmp_path: Path, *, case_enabled=True, rad_inside=True, with_meta=True, timeout_s=None) -> FakeEx:
    cdir = tmp_path / "case"
    (cdir / "01_extract").mkdir(parents=True)
    if with_meta:
        (cdir / "01_extract" / "model_meta.json").write_text(json.dumps({"part_id": 7}))
    inp = tmp_path / "inputs"
    inp.mkdir()
    (inp / "main_0000.rad").write_text("#RADIOSS STARTER\n/BEGIN\n")
    cj = SimpleNamespace(enabled=case_enabled, timeout_s=timeout_s)
    st = SimpleNamespace(bead_doe=SimpleNamespace(case_jig=cj),
                         storage=SimpleNamespace(input_roots=[str(inp)], upload_root=None),
                         worker=SimpleNamespace(progress_heartbeat_s=30, heartbeat_interval_s=1, inproc_join_max_s=5))
    return FakeEx(case={"rad_path": str(inp / "main_0000.rad")}, cdir=str(cdir), settings=st,
                  job={"id": "job-1", "params": {"settings": {}}}, lib=None)


@pytest.fixture()
def patched(monkeypatch):
    """paicad 점검·설정·입력 검사를 가짜로(코어 include 트리 읽기·해시는 실제)."""
    from esl_worker import doe_jobs, paicad_proc

    st = SimpleNamespace(version_calls=0, scan_calls=[], stage_calls=0, ready=True)

    def version_check(settings, cfg=None):
        st.version_calls += 1
        return {"ready": st.ready, "version": "0.15.4", "ocp": "7", "pinned": None, "warning": None,
                "reason": None if st.ready else "PAICAD_NOT_CONFIGURED"}

    monkeypatch.setattr(paicad_proc, "version_check", version_check)
    monkeypatch.setattr(paicad_proc, "_settings_cfg", lambda s: {"bead_doe": {"paicad": {"timeout_s": {"fixed_scan": 90}}},
                                                                 "commands": {}})
    monkeypatch.setattr(doe_jobs, "check_input_path", lambda settings, p, purpose: p)
    monkeypatch.setattr(doe_jobs, "_tick", lambda ex: (lambda: None))
    return st


def _scan_ok(st, n=4):
    """가짜 _fixed_scan: out_dir 에 paicad 산출 3개 모양을 씀(코어 read_fixed 가 읽는 형식)."""
    import numpy as np

    def fake(ex, step, *, assem_dir, parts, out_dir, cwd, capture, opts, threads, echo, progress=None, tick=None,
             label="", cfg=None, stage="prep"):
        st.scan_calls.append({"assem_dir": assem_dir, "parts": parts, "out_dir": out_dir, "cfg": cfg, "label": label})
        Path(out_dir, "shell_scan.json").write_text(json.dumps({"status": "OK", "fixed": {"clusters": [{"id": 0}]}}))
        np.savez(Path(out_dir, "fixed_nodes.npz"), node_id=np.arange(n), part=np.full(n, 7), kind_mask=np.full(n, 1),
                 cluster=np.zeros(n, int), xyz=np.zeros((n, 3)))
        return {"ok": True, "code": None, "timeout": False, "exit_code": 0, "report": {}}
    return fake


def test_gather_off_costs_nothing(tmp_path, patched):
    from esl_worker import jig_prep as jp

    ex = _fake_ex(tmp_path, case_enabled=False)
    f, inp = jp.gather(ex, {}, {})
    assert f.case_enabled is False and inp is None and f.cache_have is None and patched.version_calls == 0
    ex2 = _fake_ex(tmp_path / "b")
    f, inp = jp.gather(ex2, {"jig": {"enabled": False}}, {})                               # 코어 jig.enabled 거짓
    assert f.core_enabled is False and inp is None and patched.version_calls == 0
    assert jp.run(_fake_ex(tmp_path / "c", case_enabled=False), None, lambda m: None) is None
    assert not os.path.exists(tmp_path / "c" / "case" / "01_extract" / "jig_prep.json")    # 기록도 없음


def test_gather_input_errors_become_skip(tmp_path, patched):
    from esl_worker import jig_prep as jp

    ex = _fake_ex(tmp_path, with_meta=False)
    f, inp = jp.gather(ex, {}, {})
    assert inp is None and "model_meta" in (f.input_error or "") and jp.decide(f).cause == "NO_INPUT"
    out = jp.run(ex, None, lambda m: None)
    assert out["status"] == "skipped" and out["code"] == "JIG_FIXED_SKIPPED" and "model_meta" in out["detail"]
    ex3 = _fake_ex(tmp_path / "x")
    ex3.case = {"rad_path": None}
    assert "rad 없음" in (jp.gather(ex3, {}, {})[0].input_error or "")


def test_run_paicad_unavailable_is_skipped_record(tmp_path, patched):
    from esl_worker import jig_prep as jp

    patched.ready = False
    ex = _fake_ex(tmp_path)
    logs: list[str] = []
    out = jp.run(ex, None, logs.append)
    assert out["status"] == "skipped" and out["code"] == "JIG_FIXED_SKIPPED" and out["cause"] == "PAICAD_UNAVAILABLE"
    assert "PAICAD_NOT_CONFIGURED" in out["detail"] and any("지그 tie 준비 생략" in m for m in logs)
    rec = json.loads(Path(ex.cdir, "01_extract", "jig_prep.json").read_text(encoding="utf-8"))
    assert rec["status"] == "skipped" and rec["key"] and rec["part_id"] == 7 and rec["seconds"] is None
    assert not Path(jp.fixed_dir(ex.cdir)).exists() and patched.scan_calls == []


def test_run_fill_in_place_then_cache_hit_then_input_change(tmp_path, patched, monkeypatch):
    from esl_worker import doe_jobs, jig_prep as jp

    monkeypatch.setattr(doe_jobs, "_fixed_scan", _scan_ok(patched, n=6))
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex, fn, **kw: fn())             # 작업 스레드 없이
    ex = _fake_ex(tmp_path)
    logs: list[str] = []
    out = jp.run(ex, None, logs.append)
    assert out["status"] == "ok" and out["code"] is None and out["n_nodes"] == 6 and out["assem"] == "in_place"
    assert len(patched.scan_calls) == 1 and patched.version_calls == 1
    c = patched.scan_calls[0]
    assert c["assem_dir"] == os.path.dirname(ex.case["rad_path"]) and c["parts"] == "7"      # 제자리(Case 입력 폴더)
    assert c["cfg"]["bead_doe"]["paicad"]["timeout_s"]["fixed_scan"] == 90                  # timeout_s null = paicad 값
    fd = Path(jp.fixed_dir(ex.cdir))
    meta = json.loads((fd / jp.NODES_JSON).read_text(encoding="utf-8"))
    assert meta["schema"] == jp.SCHEMA and meta["n_nodes"] == 6 and meta["part_id"] == 7 and meta["assem"] == "in_place"
    assert sorted(p.name for p in fd.iterdir()) == ["fixed_nodes.json", "fixed_nodes.npz", "shell_scan.json"]
    assert not Path(ex.cdir, "_jig", jp.TMP_SUB).exists()                                   # 임시 출력은 최종으로 이동
    assert any("지그 tie 준비 완료" in m for m in logs)
    # 같은 입력 재실행 = 캐시 일치 → paicad 점검·fixed-scan 0회
    logs.clear()
    assert jp.run(ex, None, logs.append) is None
    assert len(patched.scan_calls) == 1 and patched.version_calls == 1 and any("캐시 일치" in m for m in logs)
    # 입력(starter) 바뀜 → 다시, 이전 캐시는 _backup 으로
    Path(ex.case["rad_path"]).write_text("#RADIOSS STARTER\n/BEGIN\n# changed\n")
    out2 = jp.run(ex, None, logs.append)
    assert out2["status"] == "ok" and len(patched.scan_calls) == 2
    backups = list(Path(ex.cdir, "_backup").rglob("fixed_nodes.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text())["key"] == meta["key"]
    assert json.loads((fd / jp.NODES_JSON).read_text())["key"] != meta["key"]


def test_run_timeout_setting_overrides_paicad_limit(tmp_path, patched, monkeypatch):
    from esl_worker import doe_jobs, jig_prep as jp

    monkeypatch.setattr(doe_jobs, "_fixed_scan", _scan_ok(patched))
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex, fn, **kw: fn())
    ex = _fake_ex(tmp_path, timeout_s=123.0)
    assert jp.run(ex, None, lambda m: None)["status"] == "ok"
    assert patched.scan_calls[0]["cfg"]["bead_doe"]["paicad"]["timeout_s"]["fixed_scan"] == 123.0


@pytest.mark.parametrize("res,cause,part", [
    ({"ok": False, "code": "TIMEOUT", "timeout": True, "exit_code": None}, "TIMEOUT", "시간 초과"),
    ({"ok": False, "code": "PAICAD_FAILED", "message": "bad", "paicad_code": "GEOM_X", "timeout": False, "exit_code": 20,
      "detail": "d"}, "SCAN_FAILED", "GEOM_X"),
])
def test_run_scan_failure_is_recorded_and_not_raised(tmp_path, patched, monkeypatch, res, cause, part):
    from esl_worker import doe_jobs, jig_prep as jp

    monkeypatch.setattr(doe_jobs, "_fixed_scan", lambda *a, **k: res)
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex, fn, **kw: fn())
    ex = _fake_ex(tmp_path)
    out = jp.run(ex, None, lambda m: None)
    assert out["status"] == "failed" and out["code"] == "JIG_FIXED_FAILED" and out["cause"] == cause and part in out["detail"]
    assert not Path(jp.fixed_dir(ex.cdir)).exists()                                          # 부분 출력은 캐시로 안 남음
    assert json.loads(Path(ex.cdir, "01_extract", "jig_prep.json").read_text())["status"] == "failed"


def test_run_paicad_start_failure_and_unexpected_error_continue(tmp_path, patched, monkeypatch):
    from esl_worker import doe_jobs, jig_prep as jp
    from esl_worker.executor import _Canceled, _StepFailed

    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex, fn, **kw: fn())
    monkeypatch.setattr(doe_jobs, "_fixed_scan", lambda *a, **k: (_ for _ in ()).throw(_StepFailed("PAICAD_NOT_FOUND", "x")))
    out = jp.run(_fake_ex(tmp_path / "a"), None, lambda m: None)
    assert out["cause"] == "SCAN_FAILED" and "PAICAD_NOT_FOUND" in out["detail"]
    monkeypatch.setattr(doe_jobs, "_fixed_scan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = jp.run(_fake_ex(tmp_path / "b"), None, lambda m: None)
    assert out["cause"] == "EXCEPTION" and "boom" in out["detail"]
    monkeypatch.setattr(doe_jobs, "_fixed_scan", lambda *a, **k: (_ for _ in ()).throw(_Canceled()))
    with pytest.raises(_Canceled):                                                          # 취소는 전파
        jp.run(_fake_ex(tmp_path / "c"), None, lambda m: None)


def test_run_unreadable_scan_output_is_failed(tmp_path, patched, monkeypatch):
    from esl_worker import doe_jobs, jig_prep as jp

    def bad(ex, step, *, out_dir, **kw):
        Path(out_dir, "shell_scan.json").write_text(json.dumps({"status": "FAIL", "code": "X"}))
        return {"ok": True, "code": None, "timeout": False, "exit_code": 0}

    monkeypatch.setattr(doe_jobs, "_fixed_scan", bad)
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex, fn, **kw: fn())
    out = jp.run(_fake_ex(tmp_path), None, lambda m: None)
    assert out["cause"] == "READ_FAILED" and out["status"] == "failed"


def test_run_stages_copy_when_include_outside_and_retries_parse_failure(tmp_path, patched, monkeypatch):
    """include 트리가 Case 입력 폴더 밖 → 정규화 사본(_jig/assem_full)에 fixed-scan. 제자리 FIXED_PARSE_FAILED → 사본으로 한 번 더."""
    from esl_worker import core_adapter, doe_jobs, jig_prep as jp

    ex = _fake_ex(tmp_path)
    outside = tmp_path / "shared" / "inc.rad"
    outside.parent.mkdir()
    outside.write_text("x")
    rad = Path(ex.case["rad_path"])
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex_, fn, **kw: fn())
    monkeypatch.setattr(core_adapter, "jig_model_files", lambda starter, roots, **k: [str(rad), str(outside)])
    staged: list[dict] = []

    def fake_stage(ex_, starter, case_dir, rel, echo, label="", **kw):
        d = Path(kw["out"]) / rel
        kw["guard"](str(d))
        d.mkdir(parents=True, exist_ok=True)
        staged.append({"rel": rel, "dest": str(d), "man_path": kw["man_path"], "out": kw["out"]})
        return str(d), {}

    monkeypatch.setattr(doe_jobs, "_stage_full", fake_stage)
    monkeypatch.setattr(doe_jobs, "_fixed_scan", _scan_ok(patched))
    out = jp.run(ex, None, lambda m: None)
    assert out["status"] == "ok" and out["assem"] == "staged" and len(staged) == 1
    assert staged[0]["dest"] == os.path.join(ex.cdir, "_jig", "assem_full") and staged[0]["out"] == os.path.join(ex.cdir, "_jig")
    assert patched.scan_calls[0]["assem_dir"] == staged[0]["dest"]
    # 제자리(모두 Case 입력 폴더 안) + 첫 시도 FIXED_PARSE_FAILED → 사본으로 재시도
    ex2 = _fake_ex(tmp_path / "two")
    patched.scan_calls.clear()
    staged.clear()
    monkeypatch.setattr(core_adapter, "jig_model_files", lambda starter, roots, **k: [ex2.case["rad_path"]])
    ok = _scan_ok(patched)
    seq = iter([{"ok": False, "code": "FIXED_PARSE_FAILED", "timeout": False, "exit_code": 2, "message": "m"}, None])

    def flaky(*a, **k):
        r = next(seq)
        return r if r is not None else ok(*a, **k)

    monkeypatch.setattr(doe_jobs, "_fixed_scan", flaky)
    out2 = jp.run(ex2, None, lambda m: None)
    assert out2["status"] == "ok" and out2["assem"] == "staged" and len(staged) == 1


# ================================================================ 공용 추출: doe_jobs
def test_doe_jobs_shared_helpers_signatures():
    import inspect

    from esl_worker import doe_jobs

    sig = inspect.signature(doe_jobs._stage_full)
    for k in ("out", "guard", "man_path", "dcfg", "cc"):
        assert sig.parameters[k].default is None and sig.parameters[k].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(sig.parameters)[:6] == ["ex", "starter", "case_dir", "rel", "echo", "label"]   # 옛 호출 모양 불변
    assert "cfg" in inspect.signature(doe_jobs._paicad).parameters


def test_fixed_scan_helper_passes_same_values_as_before(monkeypatch):
    from esl_worker import core_adapter, doe_jobs

    seen = {}

    def fake_paicad(ex, st, key, values, **kw):
        seen.update(key=key, values=values, **kw)
        return {"ok": True}

    monkeypatch.setattr(doe_jobs, "_paicad", fake_paicad)
    r = doe_jobs._fixed_scan(None, "ST", assem_dir="/a", parts="7", out_dir="/o", cwd="/c", capture="/c/x.log", opts=None,
                             threads=3, echo=print, label="L ")
    assert r == {"ok": True} and seen["key"] == "paicad_fixed_scan"
    assert seen["values"] == {"assem_dir": "/a", "parts": "7", "out_dir": "/o", "options": None, "threads": 3}
    assert seen["report"] == os.path.join("/o", core_adapter.doe_paicad_io().SCAN_JSON) and seen["stage"] == "prep"
    assert "cfg" not in seen                                                                  # 스터디 호출은 cfg 를 넘기지 않음(옛 동작)


# ================================================================ ESL_SOLVE 통합(가짜 paicad 실행 파일)
@pytest.fixture()
def fake_paicad(tmp_path) -> Path:
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(request, tmp_path, fake_paicad):
    d = doe_worker_settings(tmp_path, fake_paicad)
    d["worker"]["slots"] = 2
    if "case_jig_disabled" in request.node.name:             # 끔 시험: bead_doe.case_jig.enabled false
        d["bead_doe"]["case_jig"] = {"enabled": False}
    return d


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _setup_case(client, worker, synth, folder="case01"):
    r = create_case(client, synth, folder=folder)
    assert r.status_code == 201, r.text
    case = r.json()
    j = _job(client, case["id"], "CASE_EXTRACT")
    assert worker.run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{j['id']}", headers=R).json()
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    return case


def _esl(client, worker, case) -> dict:
    j = _job(client, case["id"], "ESL_SOLVE")
    worker.run_once("SLOT")
    return client.get(f"{API}/jobs/{j['id']}", headers=R).json()


def _log(client, j, step=1) -> list[str]:
    return client.get(f"{API}/jobs/{j['id']}/log", params={"step": step}, headers=R).json()["lines"]


def _esl_outputs(engine, j) -> dict:
    from sqlalchemy import text

    with engine.connect() as c:
        return c.execute(text("SELECT outputs FROM job_steps WHERE job_id = :j AND step_key = 'ESL'"),
                         {"j": j["id"]}).scalar_one() or {}


def _esl_step_no(j) -> int:
    return next(s for s in j["steps"] if s["step_key"] == "ESL")["step_no"]


def _cdir(esl_root, folder="case01") -> Path:
    return Path(str(esl_root)) / folder


def test_esl_solve_prepares_tie_once_then_cache_then_changed_input(client, synth_inputs, worker_factory, esl_root, fake_paicad,
                                                                    engine):
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    cd = _cdir(esl_root)
    assert calls(fake_paicad, "fixed-scan") == [] and not (cd / "01_extract" / "jig_prep.json").exists()
    j = _esl(client, worker, case)
    assert j["state"] == "SUCCEEDED", j
    assert len(calls(fake_paicad, "fixed-scan")) == 1
    fd = cd / "01_extract" / "jig_fixed"
    assert {"fixed_nodes.json", "fixed_nodes.npz", "shell_scan.json"} <= {p.name for p in fd.iterdir()}
    rec = json.loads((cd / "01_extract" / "jig_prep.json").read_text(encoding="utf-8"))
    assert rec["status"] == "ok" and rec["code"] is None and rec["assem"] == "in_place" and rec["n_nodes"] > 0
    assert rec["job_id"] == j["id"] and rec["part_id"] == synth_inputs.get("part_id", rec["part_id"])
    meta = json.loads((fd / "fixed_nodes.json").read_text(encoding="utf-8"))
    assert meta["key"] == rec["key"]
    assert _esl_outputs(engine, j)["jig_prep"]["status"] == "ok"
    assert j["result"]["jig_prep"]["n_nodes"] == rec["n_nodes"]
    assert any("지그 tie 준비 완료" in ln for ln in _log(client, j, _esl_step_no(j)))
    assert not (cd / "_jig" / "assem_full").exists() and not (cd / "_jig" / "fixed_tmp").exists()    # 제자리 — 사본 없음
    # 같은 입력 ESL 다시 = fixed-scan 0회(캐시)
    j2 = _esl(client, worker, case)
    assert j2["state"] == "SUCCEEDED" and len(calls(fake_paicad, "fixed-scan")) == 1
    assert any("캐시 일치" in ln for ln in _log(client, j2, _esl_step_no(j2)))
    assert "jig_prep" not in _esl_outputs(engine, j2)
    assert "jig_prep" not in (j2["result"] or {})
    # 입력이 바뀌면 다시(이전 캐시 _backup)는 가짜 ex 시험 test_run_fill_in_place_then_cache_hit_then_input_change — 실제 Case 는 입력이 바뀌면
    # ESL 이 stale 로 막혀 여기서는 못 만듦


def test_esl_solve_registers_jig_artifacts(client, synth_inputs, worker_factory, esl_root):
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    j = _esl(client, worker, case)
    assert j["state"] == "SUCCEEDED"
    arts = client.get(f"{API}/cases/{case['id']}/artifacts", headers=R).json()
    arts = arts if isinstance(arts, list) else arts.get("items", [])
    by = {a.get("rel_path") or a.get("path"): a for a in arts}
    ext = _cdir(esl_root) / "01_extract"
    for name in ("jig_prep.json", "jig_fixed/shell_scan.json", "jig_fixed/fixed_nodes.npz", "jig_fixed/fixed_nodes.json"):
        a = by.get(str(ext / name))
        assert a is not None and a["job_id"] == j["id"], (name, sorted(by))


def test_esl_solve_case_jig_disabled_zero_calls_and_unchanged_files(client, synth_inputs, worker_factory, esl_root, fake_paicad,
                                                                    engine):
    # 끔: bead_doe.case_jig.enabled false → 지그 준비 호출 0(fixed-scan·version 점검도 0), 기록·폴더·작업 폴더·step 출력·로그 줄 없음
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    n_version = len(calls(fake_paicad, "version"))
    j = _esl(client, worker, case)
    assert j["state"] == "SUCCEEDED", j
    cd = _cdir(esl_root)
    assert calls(fake_paicad, "fixed-scan") == [] and len(calls(fake_paicad, "version")) == n_version
    assert not (cd / "01_extract" / "jig_prep.json").exists() and not (cd / "01_extract" / "jig_fixed").exists()
    assert not (cd / "_jig").exists()
    assert "jig_prep" not in _esl_outputs(engine, j) and "jig_prep" not in (j["result"] or {})
    assert not any(ln.startswith("[esl-worker] 지그 tie") for ln in _log(client, j, _esl_step_no(j)))


def test_esl_solve_paicad_failure_keeps_esl_succeeding(client, synth_inputs, worker_factory, esl_root, fake_paicad, engine):
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    set_control(fake_paicad, fail={"fixed-scan": {"code": "GEOM_INTERNAL", "exit": 20, "message": "forced"}})
    j = _esl(client, worker, case)
    assert j["state"] == "SUCCEEDED", j                                                         # ESL 은 계속
    cd = _cdir(esl_root)
    rec = json.loads((cd / "01_extract" / "jig_prep.json").read_text(encoding="utf-8"))
    assert rec["status"] == "failed" and rec["code"] == "JIG_FIXED_FAILED" and rec["cause"] == "SCAN_FAILED"
    assert not (cd / "01_extract" / "jig_fixed").exists()
    assert (cd / "04_esl" / "f_eq.npz").is_file()                                               # 기존 산출물 그대로
    assert _esl_outputs(engine, j)["jig_prep"]["code"] == "JIG_FIXED_FAILED"
    assert any("지그 tie 준비 실패" in ln for ln in _log(client, j, _esl_step_no(j)))
    # 실패 뒤 다시 하면(캐시 없음) 한 번 더 시도 — 이번엔 성공
    set_control(fake_paicad)
    j2 = _esl(client, worker, case)
    assert j2["state"] == "SUCCEEDED" and len(calls(fake_paicad, "fixed-scan")) == 2
    assert json.loads((cd / "01_extract" / "jig_prep.json").read_text())["status"] == "ok"
