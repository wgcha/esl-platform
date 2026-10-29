"""paicad 실행(계약 esl_bead_doe.md §6, V-BD-2·3) — argv 선택 쌍·경로 realpath·메타문자·shell=False·env 최소,
가짜 paicad 종료코드 → §6.3 코드, 타임아웃·취소 트리 종료, PROGRESS 중계, 버전 점검(낮음·OCP 없음·고정 불일치), gmsh 점검."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from doe_worker_support import calls, doe_worker_settings, pid_alive, set_control, started_pids, write_fake_paicad

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")


@pytest.fixture()
def exe(tmp_path):
    return write_fake_paicad(tmp_path)


def make(tmp_path, exe, **bd):
    from esl_platform.core.config import load_config_dict

    d = doe_worker_settings(tmp_path, exe, **bd)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    return lc.settings


def snap(settings) -> dict:
    from esl_worker.paicad_proc import _settings_cfg

    return _settings_cfg(settings)


@pytest.fixture()
def env(tmp_path, exe):
    s = make(tmp_path, exe)
    out = Path(s.storage.esl_root) / "_doe" / "S1"
    (out / "input" / "step").mkdir(parents=True)
    cad = out / "input" / "step" / "ch.step"
    cad.write_text("ISO-10303-21;\n")
    return {"s": s, "cfg": snap(s), "out": out, "cad": cad, "exe": exe}


def run_extract(e, d: str = "ext", stage: str = "prep", **kw):
    from esl_worker import paicad_proc as pp

    od = e["out"] / "prep" / d
    od.mkdir(parents=True, exist_ok=True)
    return pp.run("paicad_extract", {"cad": str(e["cad"]), "out_dir": str(od), "assem_dir": None, "body_map": None,
                                     "options": None, "threads": 2},
                  settings=e["s"], cfg=kw.pop("cfg", e["cfg"]), out_root=str(e["out"]),
                  in_roots=list(e["s"].storage.input_roots), cwd=str(e["out"] / "prep"),
                  capture=str(e["out"] / "prep" / f"{d}.stdout.log"), report=str(od / "shell_features.json"),
                  stage=stage, **kw)


# ---------------------------------------------------------------- V-BD-2 argv·경로·env·shell=False
def test_argv_selection_pairs_meta_and_exe(env, tmp_path):
    from esl_worker import paicad_proc as pp

    s, cfg, out = env["s"], env["cfg"], env["out"]
    exe = str(env["exe"])
    a = pp.build_argv("paicad_grid", {"cad": "c", "features": "f", "cells": "x", "thumb": "t", "fixed_dir": "",
                                      "out_dir": "o", "options": None, "threads": 4}, cfg, exe)
    assert a[0] == exe and a[1:4] == ["shell", "view", "grid"]
    i = a.index("--fixed-dir")
    assert a[i + 1] == "" and "--options" not in a and a[-2:] == ["--threads", "4"]   # 빈 문자열 유지, None 은 쌍 제거
    with pytest.raises(pp.PaicadError) as ei:                                            # 필수 자리 None
        pp.build_argv("paicad_grid", {"cad": "c"}, cfg, exe)
    assert ei.value.code == "CONFIG_INVALID"
    with pytest.raises(pp.PaicadError) as ei:                                            # 메타문자
        pp.build_argv("paicad_update", {"cad": "a&b", "features": "f", "values": "v", "out_dir": "o",
                                        "options": None, "threads": 1}, cfg, exe)
    assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(pp.PaicadError) as ei:
        pp.build_argv("paicad_version", {}, cfg, None)
    assert ei.value.code == "PAICAD_NOT_CONFIGURED"
    with pytest.raises(pp.PaicadError) as ei:
        pp.build_argv("paicad_version", {}, cfg, str(tmp_path / "nope"))
    assert ei.value.code == "PAICAD_NOT_FOUND"
    bad = dict(cfg)
    bad["commands"] = {**cfg["commands"], "paicad_version": ["python", "version"]}       # argv[0] 허용목록
    with pytest.raises(pp.PaicadError) as ei:
        pp.build_argv("paicad_version", {}, bad, exe)
    assert ei.value.code == "CONFIG_INVALID"
    # 경로 realpath: 출력은 연구 폴더 안만, 입력은 연구 폴더·input_roots 안만, 링크 성분 거부
    roots = list(s.storage.input_roots)
    pp.check_paths({"out_dir": str(out / "prep" / "x"), "cad": str(env["cad"]), "fixed_dir": ""}, str(out), roots)
    with pytest.raises(pp.PaicadError) as ei:
        pp.check_paths({"out_dir": str(tmp_path / "elsewhere")}, str(out), roots)
    assert ei.value.code == "PATH_OUTSIDE_ROOT"
    with pytest.raises(pp.PaicadError):
        pp.check_paths({"cad": str(tmp_path / "x.step")}, str(out), roots)
    pp.check_paths({"assem_dir": roots[0]}, str(out), roots)
    (out / "lnk").symlink_to(tmp_path)
    with pytest.raises(pp.PaicadError) as ei:
        pp.check_paths({"out_dir": str(out / "lnk" / "o")}, str(out), roots)
    assert ei.value.code == "PATH_OUTSIDE_ROOT"


def test_shell_false_env_minimal_and_progress(env, tmp_path, monkeypatch):
    from esl_worker import localproc

    (tmp_path / "b").mkdir()
    s = make(tmp_path / "b", env["exe"], paicad={"env": {"PAICAD_LICENSE_HINT": "x"}})
    out = Path(s.storage.esl_root) / "_doe" / "S1"
    (out / "input" / "step").mkdir(parents=True)
    cad = out / "input" / "step" / "ch.step"
    cad.write_text("ISO-10303-21;\n")
    e = {**env, "s": s, "cfg": snap(s), "out": out, "cad": cad}
    seen = {}
    orig = subprocess.Popen

    def spy(*a, **kw):
        seen.update(kw)
        return orig(*a, **kw)

    monkeypatch.setattr(localproc.subprocess, "Popen", spy)
    monkeypatch.setenv("ESL_SECRET_TOKEN", "do-not-pass")
    monkeypatch.setenv("PYTHONPATH", "/nowhere")
    prog = []
    lines = []
    r = run_extract(e, on_progress=lambda p, m: prog.append(p), on_line=lines.append)
    assert r["ok"], r
    assert seen["shell"] is False and seen["stdin"] == subprocess.DEVNULL
    keys = set(calls(env["exe"], "extract")[-1]["env"])
    assert "ESL_SECRET_TOKEN" not in keys and "PYTHONPATH" not in keys
    assert {"PYTHONUTF8", "PYTHONIOENCODING", "PAICAD_LICENSE_HINT", "PATH"} <= keys
    assert prog and prog[-1] == 100 and any(ln.startswith("PAICAD RESULT OK") for ln in lines)
    assert (e["out"] / "prep" / "ext" / "paicad.log").is_file()
    # 사용자 문자열 없음: argv 는 템플릿 토큰·서버 경로·정수만
    a = r["argv"]
    assert all(t.startswith(("-", "/")) or t in ("shell", "extract", "2") for t in a[1:]), a


# ---------------------------------------------------------------- V-BD-3 종료코드·코드 표·타임아웃·취소
@pytest.mark.parametrize("fail,stage,want_code,want_status", [
    ({"exit": 13, "code": "GEOM_EXTRACT_EMPTY"}, "prep", "NO_BEADS", None),
    ({"exit": 12, "code": "SHELL_BODY_NOT_SHEET"}, "prep", "STEP_NOT_SHEET", None),
    ({"exit": 3, "code": "GEOM_INPUT_INVALID"}, "prep", "PAICAD_INPUT", None),
    ({"exit": 20, "code": "GEOM_INTERNAL"}, "prep", "PAICAD_FAILED", None),
    ({"exit": 10, "code": "GEOM_FEATURE_COLLISION"}, "design", "SKIPPED_COLLISION", "SKIPPED_COLLISION"),
    ({"exit": 10, "code": "SHELL_FIXED_REGION_VIOLATION"}, "design", "SKIPPED_FIXED", "SKIPPED_FIXED"),
    ({"exit": 11, "code": "GEOM_QUALITY"}, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ({"exit": 11, "code": "WEIRD_NEW_CODE"}, "design", "FAILED_MORPH", "FAILED_MORPH"),      # 모르는 코드 → 종료 범주
    ({"exit": 14, "code": "VIEW_TOO_LARGE"}, "prep", "PAICAD_INPUT", None),
    ({"exit": 0, "code": "NO_REPORT"}, "prep", "PAICAD_FAILED", None),                       # 종료 0 인데 보고 없음
])
def test_exit_codes_map(env, fail, stage, want_code, want_status):
    set_control(env["exe"], fail={"extract": fail})
    r = run_extract(env, stage=stage)
    assert not r["ok"] and r["code"] == want_code and r["status"] == want_status, r
    assert r["exit_code"] == fail["exit"]
    if fail["code"] == "WEIRD_NEW_CODE":
        assert r["paicad_code"] == "WEIRD_NEW_CODE" and "WEIRD_NEW_CODE" in r["message"]


def test_exit2_args_is_internal(env):
    cfg = dict(env["cfg"])
    cfg["commands"] = {**cfg["commands"], "paicad_extract": ["{paicad}", "shell", "extract", "--bogus", "--cad", "{cad}",
                                                             "--out-dir", "{out_dir}"]}
    r = run_extract(env, cfg=cfg)
    assert r["exit_code"] == 2 and r["code"] == "PAICAD_INTERNAL"


def test_timeout_kills_tree(tmp_path, exe):
    s = make(tmp_path, exe, paicad={"timeout_s": {"extract": 1}})
    out = Path(s.storage.esl_root) / "_doe" / "S1"
    (out / "input" / "step").mkdir(parents=True)
    cad = out / "input" / "step" / "ch.step"
    cad.write_text("x")
    set_control(exe, sleep={"extract": 30})
    t0 = time.monotonic()
    r = run_extract({"s": s, "cfg": snap(s), "out": out, "cad": cad, "exe": exe})
    assert time.monotonic() - t0 < 20
    assert r["timeout"] and r["code"] == "PAICAD_TIMEOUT" and r["exit_code"] is None
    assert started_pids(exe) and not any(pid_alive(p) for p in started_pids(exe))


def test_cancel_stop_event_kills_tree(env):
    from esl_worker import paicad_proc as pp

    set_control(env["exe"], sleep={"extract": 30})
    procs = pp.Procs()
    threading.Timer(1.0, procs.stop.set).start()
    with pytest.raises(pp.PaicadCanceled):
        run_extract(env, procs=procs)
    assert started_pids(env["exe"]) and not any(pid_alive(p) for p in started_pids(env["exe"]))
    assert not procs.items
    # tick 예외(lease 상실·취소) → 트리 종료 후 그대로 전파
    set_control(env["exe"], sleep={"extract": 30})
    n = {"k": 0}

    def tick():
        n["k"] += 1
        if n["k"] > 5:
            raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError):
        run_extract(env, d="ext2", tick=tick)
    assert not any(pid_alive(p) for p in started_pids(env["exe"]))


# ---------------------------------------------------------------- 버전·gmsh 점검(§6.5)
@pytest.mark.parametrize("ctl,ready,reason,warn", [
    ({}, True, None, False),
    ({"version": "0.13.2"}, False, "PAICAD_VERSION_LOW", True),
    ({"ocp": None}, False, "PAICAD_OCP_MISSING", False),
    ({"version": "0.15.0"}, True, None, True),
])
def test_version_check(env, ctl, ready, reason, warn):
    from esl_worker import paicad_proc as pp

    set_control(env["exe"], **ctl)
    v = pp.version_check(env["s"])
    assert v["ready"] is ready and v["reason"] == reason and bool(v["warning"]) is warn, v
    assert v["pinned"] == "0.14.0" and v["checked_at"].endswith("Z")


def test_version_check_missing_exe(tmp_path, exe):
    from esl_worker import paicad_proc as pp

    s = make(tmp_path, tmp_path / "no_such_paicad")
    assert pp.version_check(s)["reason"] == "PAICAD_NOT_FOUND"
    (exe.parent / "broken").write_text("#!/bin/sh\necho not json\n")
    (exe.parent / "broken").chmod(0o755)
    (tmp_path / "x").mkdir()
    s = make(tmp_path / "x", exe.parent / "broken")
    assert pp.version_check(s)["reason"] == "PAICAD_CHECK_FAILED"


def test_gmsh_check_and_status_cache(env, monkeypatch):
    from esl_worker import paicad_proc as pp

    g = pp.gmsh_check()
    try:
        import gmsh  # noqa: F401
        assert g["ready"] is True and g["version"]
    except Exception:  # noqa: BLE001
        assert g == {"ready": False, "version": None}
    c = pp.StatusCache()
    v1 = c.get(env["s"])
    assert v1["paicad"]["ready"] is True and "gmsh" in v1
    n = len(calls(env["exe"], "version"))
    assert c.get(env["s"]) is v1 and len(calls(env["exe"], "version")) == n            # check_interval_s 캐시
    c.get(env["s"], force=True)
    assert len(calls(env["exe"], "version")) == n + 1
