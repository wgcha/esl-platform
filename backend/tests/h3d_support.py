"""서버 h3d 추출 시험 공용(계약 esl_p3_ux.md §6): 가짜 hw(HyperView TCL 출력 흉내) 실행 파일.

가짜 hw 는 실제 hw 와 같은 argv(-tcl <tcl> -input <h3d> -part <p> -output <dir> -config <request> -hot_k -top_n)를 받아
환경변수에 따라 동작한다(워커가 os.environ 을 넘기므로 시험이 monkeypatch 로 바꿈):
- FAKE_HW_MODE=ok(기본): FAKE_HW_SRC(추출 결과 CSV 폴더)의 파일을 -output 으로 복사, done.json ok(part·hot_k 기록)
- FAKE_HW_MODE=fail: done.json ok=false(code·failed_step·error·errorInfo) + 종료코드 1
- FAKE_HW_MODE=nodone: 아무것도 쓰지 않고 종료코드 3
- FAKE_HW_MODE=hang: 손자 프로세스를 하나 띄우고 둘 다 오래 잔다(pid 를 FAKE_HW_PIDS 파일에 기록) — 취소 시 트리 종료 확인
- FAKE_HW_MODE=license: 라이선스 실패 문구 출력 + 종료코드 1(done.json 없음)
- request bf_only 1(v0.24.2): FAKE_HW_BF_SRC 의 bf_<k>.csv 에서 bf_frames 행만 복사, done.json mode bf_only
  (FAKE_HW_BF_NFRAMES·FAKE_HW_BF_TIMES·FAKE_HW_BF_TYPE·FAKE_HW_BF_NOFRAMES 로 조정)
- FAKE_HW_TCL_DATA(+FAKE_HW_TCL_MOCK·FAKE_HW_TCL_SCRIPT, `write_tcl_bf_env`): bf_only 요청을 실제 TCL 을 tclsh+hwmock 으로
  돌려 처리(done.json·bf_<k>.csv 가 실제 TCL 출력 — v0.24.2 통합)
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
if mode == "license":
    print("ERROR: License checkout failed (no licenses available)", flush=True)
    sys.exit(1)
req = {{}}
if opt("-config") and os.path.isfile(opt("-config")):
    for ln in open(opt("-config"), encoding="utf-8"):
        if "\t" in ln and not ln.startswith("#"):
            k, v = ln.rstrip("\n").split("\t", 1)
            req[k] = v
if req.get("bf_only") == "1" and os.environ.get("FAKE_HW_TCL_DATA"):
    # 실제 TCL(esl_h3d_extract.tcl) 을 tclsh + 가짜 hwi(tests/io/fixtures/hwmock.tcl)로 실행 — 출력은 실제 TCL 형식 그대로
    tclsh = os.environ.get("ESL_TCLSH") or shutil.which("tclsh") or shutil.which("tclsh8.6")
    drv = os.path.join(os.path.dirname(out), "tcl_driver_%d.tcl" % os.getpid())
    with open(drv, "w", encoding="utf-8") as fh:
        fh.write("set ::ESL_NO_EXIT 1\nsource {{%s}}\nsource {{%s}}\n" % (os.environ["FAKE_HW_TCL_MOCK"], os.environ["FAKE_HW_TCL_DATA"]))
        fh.write("set ::argv [list -input {{%s}} -config {{%s}} -output {{%s}} -part {{%s}} -hot_k 1 -top_n 1]\n"
                 % (opt("-input"), opt("-config"), out, opt("-part") or ""))
        fh.write("source {{%s}}\nexit $::esl::rc\n" % os.environ["FAKE_HW_TCL_SCRIPT"])
    r = subprocess.run([tclsh, drv], capture_output=True, text=True)
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.stdout.flush()
    sys.exit(r.returncode)
if req.get("bf_only") == "1":
    # bf 전용 흉내(계약 esl_bforce_ondemand.md §2): FAKE_HW_BF_SRC 의 bf_<k>.csv 에서 요청 프레임 행만 쓴다
    frames = sorted(int(x) for x in req["bf_frames"].split())
    bsrc = os.environ["FAKE_HW_BF_SRC"]
    kinds = {{}}
    for name in sorted(os.listdir(bsrc)):
        if name.startswith("bf_") and name.endswith(".csv"):
            k = name[3:-4]
            with open(os.path.join(bsrc, name), encoding="utf-8") as fi, open(os.path.join(out, name), "w", encoding="utf-8") as fo:
                rows = 0
                fo.write(fi.readline())
                for ln in fi:
                    if int(ln.split(",", 1)[0]) in frames:
                        fo.write(ln); rows += 1
            kinds[k] = {{"type": os.environ.get("FAKE_HW_BF_TYPE", "Contact Forces"), "comps": ["X", "Y", "Z"], "rows": rows}}
    times = json.loads(os.environ.get("FAKE_HW_BF_TIMES", "{{}}"))
    bf_frames = [] if os.environ.get("FAKE_HW_BF_NOFRAMES") else frames
    json.dump({{"ok": True, "mode": "bf_only", "h3d": opt("-input"), "part_spec": opt("-part"),
               "n_frames": int(os.environ.get("FAKE_HW_BF_NFRAMES", "0")), "n_nodes": 0, "frames": frames,
               "value_format": "%.17g", "passes": {{"BF": {{"frames": frames, "node_chunks": 1, "rows": 0, "seconds": 0.0}}}},
               "frame_times": [times.get(str(f), f * 0.001) for f in frames],
               "bforce": {{"on": True, "frames": bf_frames, "kinds": kinds}}, "warnings": []}},
              open(os.path.join(out, "done.json"), "w"))
    print("ESL bf-only done", flush=True)
    sys.exit(0)
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

def write_tcl_bf_env(base: Path, synth: dict, types: dict | None = None, extra: str = "", seed: int = 11):
    """실제 TCL bf 전용 모드용 hwmock 데이터(data.tcl)를 synth_case 모델(노드·프레임 시간)에 맞춰 쓴다.

    반환 (환경변수 dict, 값 {표시명: (프레임, 노드, 성분) 배열}). types = {표시명: 성분 목록}(기본 CONT·ACC = 등급 contact).
    시간 = synth["csv"]/frames.csv 글자 그대로("Time = <t>") — 실제 h3d 처럼 추출·보충이 같은 sim_time 을 본다."""
    import csv as _csv

    import numpy as np

    root = Path(__file__).resolve().parents[2]
    types = types or {"Contact Forces": ["X", "Y", "Z"], "Acceleration": ["X", "Y", "Z", "Mag"]}

    # 키 문자열 규칙은 tests/io/test_tcl_mock.py:_key 와 같다(그 모듈은 pytest 시험이라 import 하지 않음)
    def key(*parts):
        el = [("{" + str(p) + "}") if (str(p) == "" or " " in str(p)) else str(p) for p in parts]
        return "{" + " ".join(el) + "}"

    with open(Path(synth["csv"]) / "frames.csv", encoding="utf-8") as fh:
        times = [r["time"] for r in _csv.DictReader(fh)]
    nid = [int(n) for n in synth["node_id"]]
    import synth_case

    pid, title = synth_case.PART_ID, synth_case.PART_TITLE
    rng = np.random.default_rng(seed)
    lines = [
        "set ::mock::sims {" + " ".join('"Time = %s"' % t for t in times) + "}",
        "set ::mock::parts [dict create %d [dict create elems {} nodes {%s}]]" % (pid, " ".join(map(str, nid))),
        "set ::mock::names [dict create %d {%s}]" % (pid, title),
        "set ::mock::coords [dict create " + " ".join("%d {%r %r %r}" % ((n,) + tuple(float(x) for x in xyz))
                                                    for n, xyz in zip(nid, synth["X0"])) + "]",
        "set ::mock::vals [dict create]",
        "set ::mock::dtinfo [dict create]",
    ]
    vals = {}
    for name, comps in types.items():
        lines.append("dict set ::mock::dtinfo {%s} {comps {%s} layers {}}" % (name, " ".join("{%s}" % c for c in comps)))
        v = rng.normal(size=(len(times), len(nid), len(comps)))
        vals[name] = v
        kv = []
        for f in range(len(times)):
            for k, n in enumerate(nid):
                for c, comp in enumerate(comps):
                    kv.append(f"{key(name, comp, '', f, n)} {float(v[f, k, c])!r}")
        lines.append("set ::mock::vals [dict merge $::mock::vals [dict create " + " ".join(kv) + "]]")
    if extra:
        lines.append(extra)
    data = Path(base) / "tcl_bf_data.tcl"
    data.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {"FAKE_HW_TCL_DATA": str(data), "FAKE_HW_TCL_MOCK": str(root / "tests" / "io" / "fixtures" / "hwmock.tcl"),
           "FAKE_HW_TCL_SCRIPT": str(root / "resources" / "tcl" / "esl_h3d_extract.tcl")}
    return env, vals


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
