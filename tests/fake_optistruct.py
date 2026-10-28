#!/usr/bin/env python3
"""가짜 OptiStruct + 가짜 HyperView(비드 후처리) — 워커 OPT_RUN 시험용(계약 esl_opt_run.md §8·§9, V-OR-11·12·17).

역할은 argv 로 정한다: ``-tcl`` 이 있으면 hw(비드 후처리 TCL 흉내), 아니면 OptiStruct.
제어 = 실행 파일(래퍼) 폴더의 ``fake_os_control.json``(워커는 환경변수를 ``worker.env_passthrough`` 만 넘기므로 파일로).
호출마다 ``fake_os_calls.jsonl`` 에 {role, argv, cwd, env 키, mode} 한 줄을 남긴다.

OptiStruct 흉내: argv = [exe, <deck>.fem, (-check), ...]. cwd 에 ``<deck>.out`` 을 쓰고(반복 블록: ``ITERATION n`` /
``Objective Function … = v`` / ``|  1 |COMP |COMPLIAN| | | <subcase> | <C> |``), 본 실행이면 ``<deck>_des.h3d``
(가짜: JSON {node_id, shape}), ``<deck>.h3d``·``.hist``·``.stat`` 도 쓴다. 초기 C 는 ``../load/selection.json`` 의
선정 C⁰(자체 솔버 값과 같게 — c0_tol 경고 없음), 반복마다 줄어든다. DESMAX 는 덱 ``DOPTPRM,DESMAX,n``.

control 키
- mode: ok(기본, ``iterations`` 회 후 수렴) | nonconv(DESMAX 까지, 수렴 표식 없음) | check_fail(-check 에서 *** ERROR,
  종료코드 1) | fail(본 실행 *** ERROR, 종료코드 3) | exit1(오류 패턴 없이 종료코드 1) | hang(손자 프로세스와 함께 오래
  잔다, pid 를 ``fake_os_pids`` 에 기록) | nodes(본 실행이 _des.h3d 를 남기지 않음) | memory(메모리 부족 메시지·종료코드 2)
- license: 처음 n 번 호출(``license_on``: solve | check | both, 기본 solve)은 라이선스 오류 + 종료코드 1
  (카운터 = ``fake_os_license_count``)
- iterations(기본 3), iter_delay(초, 반복 사이 대기 — 진행률·취소 시험), shape_scale(기본 1.0)
hw 흉내: argv -input <_des.h3d> -output <dir> → <dir>/shape.csv(node_id,dx,dy,dz)·done.json·progress.log.
  control ``hw_mode``: ok | fail(done.json ok=false, 종료코드 1) | badnodes(노드 하나 빠짐).
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(os.environ.get("FAKE_OS_SELF") or sys.argv[0]))


def _control() -> dict:
    p = os.path.join(HERE, "fake_os_control.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _record(role: str, ctl: dict) -> None:
    with open(os.path.join(HERE, "fake_os_calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": role, "argv": sys.argv, "cwd": os.getcwd(), "env": sorted(os.environ),
                             "mode": ctl.get("mode", "ok"), "t": time.time()}) + "\n")


def _bump_counter(name: str) -> int:
    p = os.path.join(HERE, name)
    try:
        n = int(open(p).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    n += 1
    with open(p, "w") as fh:
        fh.write(str(n))
    return n


def _read_deck(fem: str) -> dict:
    nodes, n_sub, desmax = [], 0, 30
    with open(fem, encoding="ascii", errors="replace") as fh:
        for ln in fh:
            if ln.startswith("GRID,"):
                p = ln.strip().split(",")
                nodes.append((int(p[1]), float(p[3]), float(p[4]), float(p[5])))
            elif re.match(r"^SUBCASE\s+\d+", ln):
                n_sub += 1
            elif ln.startswith("DOPTPRM,DESMAX,"):
                desmax = int(ln.strip().split(",")[2])
    return {"nodes": nodes, "n_sub": n_sub, "desmax": desmax}


def _c0s(n_sub: int) -> list[float]:
    try:
        with open(os.path.join(os.getcwd(), "..", "load", "selection.json"), encoding="utf-8") as fh:
            sel = json.load(fh)
        rows = sorted((r for r in sel["rows"] if r.get("label")), key=lambda r: r["label"])
        return [float(r["C0"]) for r in rows][:n_sub] + [1.0] * max(0, n_sub - len(rows))
    except (OSError, ValueError, KeyError):
        return [1.0e4 / (k + 1) for k in range(n_sub)]


def optistruct(ctl: dict) -> int:
    args = sys.argv[1:]
    fem = next(a for a in args if not a.startswith("-") and a.lower().endswith(".fem"))
    check = "-check" in args
    stem = os.path.splitext(os.path.basename(fem))[0]
    out_path = os.path.join(os.getcwd(), stem + ".out")
    mode = ctl.get("mode", "ok")
    lic_n = int(ctl.get("license", 0) or 0)
    lic_on = ctl.get("license_on", "solve")
    print(f"fake OptiStruct {'check' if check else 'solve'} {fem}", flush=True)
    if lic_n and (lic_on == "both" or (lic_on == "check") == check):
        if _bump_counter("fake_os_license_count") <= lic_n:
            with open(out_path, "w") as fh:
                fh.write(" *** ERROR # 9999 ***\n Altair license checkout failed: ALM_LICENSE_ERROR\n")
            print("license checkout failed (fake)", flush=True)
            return 1
    deck = _read_deck(fem)
    head = " OptiStruct 2026.1 (fake)\n"
    if check:
        if mode == "check_fail":
            with open(out_path, "w") as fh:
                fh.write(head + " *** ERROR # 1000 *** fake deck error on card DTPG\n")
            return 1
        with open(out_path, "w") as fh:
            fh.write(head + " CHECK RUN COMPLETED (fake)\n")
        return 0
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        with open(os.path.join(HERE, "fake_os_pids"), "w") as fh:
            fh.write(f"{os.getpid()} {child.pid}")
        with open(out_path, "w") as fh:
            fh.write(head + "ITERATION    0\n")
        time.sleep(600)
        return 0
    if mode == "exit1":
        with open(out_path, "w") as fh:
            fh.write(head + " abnormal termination (fake)\n")
        return 1
    if mode == "memory":
        with open(out_path, "w") as fh:
            fh.write(head + " *** ERROR # 5000 *** insufficient memory (fake)\n")
        return 2
    n_it = deck["desmax"] if mode == "nonconv" else min(int(ctl.get("iterations", 3)), deck["desmax"])
    c0 = _c0s(deck["n_sub"])
    delay = float(ctl.get("iter_delay", 0) or 0)
    with open(out_path, "w") as fh:
        fh.write(head)
        for it in range(n_it + 1):
            f = 1.0 - 0.3 * it / max(1, n_it)
            fh.write(f"ITERATION {it:4d}\n")
            fh.write(f" Objective Function (Minimize MINMAX)      =  {f:.5E}\n")
            for k, c in enumerate(c0, start=1):
                fh.write(f" |     1  |COMP     |COMPLIAN|       |        |  {k:6d} |  {c * f:.5E} |\n")
            fh.flush()
            if mode == "fail" and it == 1:
                fh.write(" *** ERROR # 2000 *** fake solver failure\n")
                return 3
            if delay:
                time.sleep(delay)
        if mode != "nonconv":
            fh.write(" OPTIMIZATION HAS CONVERGED.\n")
        else:
            fh.write(" MAXIMUM NUMBER OF DESIGN ITERATIONS REACHED.\n")
    base = os.path.join(os.getcwd(), stem)
    for ext in (".h3d", ".hist", ".stat"):
        with open(base + ext, "w") as fh:
            fh.write(f"fake {ext}\n")
    if mode != "nodes":
        nodes = deck["nodes"]
        xs = [n[1] for n in nodes]
        zs = [n[3] for n in nodes]
        cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
        rx, rz = max(1e-9, (max(xs) - min(xs)) / 4), max(1e-9, (max(zs) - min(zs)) / 4)
        sc = float(ctl.get("shape_scale", 1.0))
        shape = [[0.0, sc * 10.0 * math.exp(-(((x - cx) / rx) ** 2 + ((z - cz) / rz) ** 2)), 0.0]
                 for _, x, _, z in nodes]
        with open(base + "_des.h3d", "w") as fh:
            json.dump({"fake": "des.h3d", "node_id": [n[0] for n in nodes], "shape": shape}, fh)
    return 0


def hw(ctl: dict) -> int:
    args = sys.argv[1:]

    def opt(name):
        return args[args.index(name) + 1] if name in args else None

    out = opt("-output")
    src = opt("-input")
    os.makedirs(out, exist_ok=True)
    plog = os.path.join(out, "progress.log")
    mode = ctl.get("hw_mode", "ok")
    with open(plog, "a") as pf:
        pf.write("step load\n")
    if mode == "fail":
        json.dump({"ok": False, "code": "BEAD_POST_FAILED", "failed_step": "load", "error": "fake hw failure"},
                  open(os.path.join(out, "done.json"), "w"))
        return 1
    with open(src) as fh:
        d = json.load(fh)
    ids, shape = d["node_id"], d["shape"]
    if mode == "badnodes":
        ids, shape = ids[1:], shape[1:]
    with open(os.path.join(out, "shape.csv"), "w") as fh:
        fh.write("node_id,dx,dy,dz\n")
        for n, s in zip(ids, shape):
            fh.write(f"{n},{s[0]!r},{s[1]!r},{s[2]!r}\n")
    with open(plog, "a") as pf:
        pf.write("step export\n")
    json.dump({"ok": True, "subcase": 1, "simulation": 3, "n_simulations": 4, "n_nodes": len(ids),
               "shape_type": "Shape Change"}, open(os.path.join(out, "done.json"), "w"))
    return 0


def main() -> int:
    ctl = _control()
    role = "hw" if "-tcl" in sys.argv[1:] else "optistruct"
    _record(role, ctl)
    rc = hw(ctl) if role == "hw" else optistruct(ctl)
    _record(role + "_end", {**ctl, "mode": rc})
    return rc


if __name__ == "__main__":
    sys.exit(main())
