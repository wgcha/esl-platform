"""paicad stdout 로그(capture) 심링크 가드(v0.24.4 수정 9) — 링크가 Case 밖 파일을 가리켜도 밖 파일 불변.

(a) jig_prep: ``_jig/fixed_scan.stdout.log`` 가 링크면 fixed-scan 0회·status failed·cause SYMLINK_PATH·ESL 계속.
(b) paicad_proc.run: capture 열기가 링크를 따라가지 않음(``safe_fs.open_nofollow``) — 링크도 대상도 그대로.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from doe_worker_support import calls
from test_jig_prep import _cdir, _esl, _setup_case, fake_paicad, settings_dict  # noqa: F401 (fixtures)
from test_paicad_proc import env, exe, run_extract  # noqa: F401 (fixtures)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")


def test_jig_capture_symlink_skips_scan_and_keeps_victim(client, synth_inputs, worker_factory, esl_root, fake_paicad, tmp_path):
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    cd = _cdir(esl_root)
    victim = tmp_path / "victim.txt"
    victim.write_text("PRECIOUS")
    (cd / "_jig").mkdir(exist_ok=True)
    link = cd / "_jig" / "fixed_scan.stdout.log"
    os.symlink(victim, link)
    n0 = len(calls(fake_paicad, "fixed-scan"))
    j = _esl(client, worker, case)
    assert j["state"] == "SUCCEEDED", j                                           # ESL 은 계속
    assert victim.read_text() == "PRECIOUS" and os.path.islink(link)
    assert len(calls(fake_paicad, "fixed-scan")) == n0                            # fixed-scan 실행 0
    rec = json.loads((cd / "01_extract" / "jig_prep.json").read_text())
    assert rec["status"] == "failed" and rec["cause"] == "SYMLINK_PATH", rec


def test_jig_capture_dangling_symlink_not_created(client, synth_inputs, worker_factory, esl_root, fake_paicad, tmp_path):
    worker = worker_factory()
    case = _setup_case(client, worker, synth_inputs)
    cd = _cdir(esl_root)
    ghost = tmp_path / "ghost.txt"                                                # 없는 밖 파일을 가리키는 링크
    (cd / "_jig").mkdir(exist_ok=True)
    os.symlink(ghost, cd / "_jig" / "fixed_scan.stdout.log")
    assert _esl(client, worker, case)["state"] == "SUCCEEDED"
    assert not ghost.exists()


def test_paicad_run_capture_symlink_refused(env, tmp_path):                       # noqa: F811
    from esl_worker import paicad_proc as pp

    victim = tmp_path / "victim.txt"
    victim.write_text("PRECIOUS")
    link = env["out"] / "prep" / "ext.stdout.log"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(victim, link)
    with pytest.raises(pp.PaicadError) as ei:
        run_extract(env)
    assert ei.value.code == "PATH_UNSAFE"
    assert victim.read_text() == "PRECIOUS" and os.path.islink(link)


def test_paicad_run_capture_normal_file_overwritten(env):                         # noqa: F811
    log = env["out"] / "prep" / "ext.stdout.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("OLD" * 1000)
    r = run_extract(env)
    assert r["ok"] and "OLD" not in log.read_text()                               # 정상 경로 = 매 호출 새 내용(옛 동작)


def test_open_nofollow_modes(tmp_path):
    from esl_platform.core import safe_fs

    v = tmp_path / "v"
    v.write_bytes(b"keep")
    os.symlink(v, tmp_path / "l")
    for mode in ("wb", "ab", "w", "a"):
        with pytest.raises(safe_fs.UnsafePath):
            safe_fs.open_nofollow(str(tmp_path / "l"), mode)
    assert v.read_bytes() == b"keep"
    with safe_fs.open_nofollow(str(tmp_path / "n.txt"), "w", encoding="utf-8") as fh:
        fh.write("a")
    with safe_fs.open_nofollow(str(tmp_path / "n.txt"), "a", encoding="utf-8") as fh:
        fh.write("b")
    assert (tmp_path / "n.txt").read_text() == "ab"
    with pytest.raises(ValueError):
        safe_fs.open_nofollow(str(tmp_path / "n.txt"), "r")
