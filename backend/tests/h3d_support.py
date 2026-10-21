"""서버 h3d 추출 시험 공용(계약 esl_p3_ux.md §6): 가짜 hw(HyperView TCL 출력 흉내) 실행 파일.

가짜 hw 는 실제 hw 와 같은 argv(-tcl <tcl> -input <h3d> -part <p> -output <dir> -config <request> -hot_k -top_n)를 받아
환경변수에 따라 동작한다(워커가 os.environ 을 넘기므로 시험이 monkeypatch 로 바꿈):
- FAKE_HW_MODE=ok(기본): FAKE_HW_SRC(추출 결과 CSV 폴더)의 파일을 -output 으로 복사, done.json ok(part·hot_k 기록)
- FAKE_HW_MODE=fail: done.json ok=false(code·failed_step·error·errorInfo) + 종료코드 1
- FAKE_HW_MODE=nodone: 아무것도 쓰지 않고 종료코드 3
- FAKE_HW_MODE=hang: 손자 프로세스를 하나 띄우고 둘 다 오래 잔다(pid 를 FAKE_HW_PIDS 파일에 기록) — 취소 시 트리 종료 확인
- FAKE_HW_DELAY=<초>: 시작 시 대기(동시 실행 한도 시험)
argv 는 <output>/../argv_<pid>.json 에 남긴다.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

FAKE_HW = r'''#!{python}
import json, os, shutil, subprocess, sys, time

args = sys.argv[1:]
def opt(name):
    return args[args.index(name) + 1] if name in args else None

out = opt("-output")
mode = os.environ.get("FAKE_HW_MODE", "ok")
delay = float(os.environ.get("FAKE_HW_DELAY", "0") or 0)
os.makedirs(out, exist_ok=True)
with open(os.path.join(os.path.dirname(out), "argv_%d.json" % os.getpid()), "w") as fh:
    json.dump({{"argv": sys.argv, "cwd": os.getcwd(), "env_input": os.environ.get("ESL_INPUT")}}, fh)
if mode != "progress":
    print("ESL extract fake hw start", mode, flush=True)
if delay:
    time.sleep(delay)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_HW_PIDS"], "w") as fh:
        fh.write("%d %d" % (os.getpid(), child.pid))
    time.sleep(600)
    sys.exit(0)
if mode == "progress":
    # stdout 에는 아무것도 쓰지 않고 progress.log 만 쓴다(hw.exe -b 가 Tcl stdout 을 못 내보내는 상황 흉내)
    pdelay = float(os.environ.get("FAKE_HW_PLINE_DELAY", "0.3") or 0)
    late = float(os.environ.get("FAKE_HW_PLOG_LATE", "0") or 0)
    time.sleep(late)
    plog = os.path.join(out, "progress.log")
    lines = os.environ["FAKE_HW_PLINES"].split("|")
    with open(plog, "ab") as pf:
        for ln in lines[:-1]:
            pf.write((ln + "\n").encode("utf-8")); pf.flush(); time.sleep(pdelay)
        time.sleep(float(os.environ.get("FAKE_HW_TAIL_PAUSE", "0") or 0))
        pf.write(b"\xff\xfe bad bytes\n"); pf.write((lines[-1] + "\n").encode("utf-8")); pf.flush()
    src = os.environ["FAKE_HW_SRC"]
    for name in os.listdir(src):
        if name != "done.json" and os.path.isfile(os.path.join(src, name)):
            shutil.copyfile(os.path.join(src, name), os.path.join(out, name))
    json.dump({{"ok": True, "part_spec": opt("-part"), "hot_k": 1, "top_n": 1, "h3d": opt("-input"), "warnings": []}},
              open(os.path.join(out, "done.json"), "w"))
    sys.exit(0)
if mode == "progress":
    # stdout 에는 아무것도 쓰지 않고 progress.log 만 쓴다(hw.exe -b 가 Tcl stdout 을 못 내보내는 상황 흉내).
    # FAKE_HW_PLINES(| 구분), FAKE_HW_PLINE_DELAY 줄 간격, FAKE_HW_PLOG_LATE 파일 늦게 생성, FAKE_HW_TAIL_PAUSE 마지막 줄 전 대기
    pdelay = float(os.environ.get("FAKE_HW_PLINE_DELAY", "0.3") or 0)
    time.sleep(float(os.environ.get("FAKE_HW_PLOG_LATE", "0") or 0))
    lines = os.environ["FAKE_HW_PLINES"].split("|")
    with open(os.path.join(out, "progress.log"), "ab") as pf:
        for ln in lines[:-1]:
            pf.write((ln + "\n").encode("utf-8")); pf.flush(); time.sleep(pdelay)
        time.sleep(float(os.environ.get("FAKE_HW_TAIL_PAUSE", "0") or 0))
        pf.write(b"\xff\xfe bad bytes\n"); pf.write((lines[-1] + "\n").encode("utf-8")); pf.flush()
    src = os.environ["FAKE_HW_SRC"]
    for name in os.listdir(src):
        if name != "done.json" and os.path.isfile(os.path.join(src, name)):
            shutil.copyfile(os.path.join(src, name), os.path.join(out, name))
    json.dump({{"ok": True, "part_spec": opt("-part"), "hot_k": 1, "top_n": 1, "h3d": opt("-input"), "warnings": []}},
              open(os.path.join(out, "done.json"), "w"))
    sys.exit(0)
if mode == "nodone":
    sys.exit(3)
if mode == "fail":
    json.dump({{"ok": False, "code": "H3D_MISSING_RESULT", "failed_step": "GetResultCtrlHandle",
               "error": "2051", "errorInfo": "2051\n    while executing\n\"$res GetResultCtrlHandle ctrl\""}},
              open(os.path.join(out, "done.json"), "w"))
    print("ESL extract failed at step 'GetResultCtrlHandle'", flush=True)
    sys.exit(1)
src = os.environ["FAKE_HW_SRC"]
for name in os.listdir(src):
    if name != "done.json" and os.path.isfile(os.path.join(src, name)):
        shutil.copyfile(os.path.join(src, name), os.path.join(out, name))
done = json.load(open(os.path.join(src, "done.json"))) if os.path.isfile(os.path.join(src, "done.json")) else {{}}
done.update({{"ok": True, "part_spec": opt("-part"), "hot_k": int(opt("-hot_k") or 0), "top_n": int(opt("-top_n") or 0),
             "h3d": opt("-input"), "warnings": []}})
json.dump(done, open(os.path.join(out, "done.json"), "w"))
print("ESL extract done", flush=True)
sys.exit(0)
'''

H3D_BYTES = b"HYPER3D fake h3d header" + b"\x00" * 64


def write_fake_hw(base: Path) -> Path:
    """공백이 든 폴더(argv[0] 공백 허용 확인)에 실행 가능한 가짜 hw 를 만든다."""
    d = base / "Altair Fake" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "hw"
    p.write_text(FAKE_HW.format(python=sys.executable), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def write_h3d(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(H3D_BYTES)
    return path


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return "zombie" not in fh.read()
    except OSError:
        return False
