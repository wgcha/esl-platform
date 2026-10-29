"""비드 DOE 워커 시험 도우미(계약 esl_bead_doe.md V-BD-2·3·11·14·15): 가짜 paicad 실행 파일·제어·호출 기록, 설정."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from esl_test_support import REPO

WRAPPER = '''#!{python}
import os, runpy, sys
os.environ["FAKE_PAICAD_SELF"] = os.path.abspath(__file__)
sys.path.insert(0, {repo!r})
sys.argv[0] = os.path.abspath(__file__)
runpy.run_path({fake!r}, run_name="__main__")
'''
COMP = "CHASSIS_REAR"
D1, D2 = f"{COMP}_BEAD_D_1", f"{COMP}_BEAD_D_2"
# fullfact 3수준 D1·D2 ∈ {2.5, 4.5, 6.5}: 미리보기 스킵 3(충돌·고정·형상), shell run morph 실패 1(①②)
RULES = [{"when": {D1: [6.4, 6.6], D2: [2.4, 2.6]}, "code": "GEOM_FEATURE_COLLISION"},
         {"when": {D1: [6.4, 6.6], D2: [6.4, 6.6]}, "code": "SHELL_FIXED_REGION_VIOLATION"},
         {"when": {D1: [2.4, 2.6], D2: [6.4, 6.6]}, "code": "GEOM_CAD_FAILED"},
         {"when": {D1: [4.4, 4.6], D2: [6.4, 6.6]}, "code": "GEOM_QUALITY"}]
SPEC = {"method": "fullfact", "levels": 3, "params": [{"name": D1, "lo": 2.5, "hi": 6.5},
                                                      {"name": D2, "lo": 2.5, "hi": 6.5}]}


def write_fake_paicad(base: Path) -> Path:
    d = base / "fake_paicad"
    d.mkdir(exist_ok=True)
    p = d / "paicad"
    p.write_text(WRAPPER.format(python=sys.executable, repo=str(REPO), fake=str(REPO / "tests" / "fake_paicad.py")))
    p.chmod(0o755)
    return p


def set_control(exe: Path, **ctl: Any) -> None:
    (exe.parent / "fake_paicad_control.json").write_text(json.dumps(ctl))


def calls(exe: Path, cmd: str | None = None) -> list[dict[str, Any]]:
    p = exe.parent / "fake_paicad_calls.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    return [r for r in rows if cmd is None or r["cmd"] == cmd]


def started_pids(exe: Path) -> list[int]:
    d = exe.parent / "fake_paicad_running"
    return sorted(int(p.stem) for p in d.glob("*.json")) if d.is_dir() else []


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                       # 좀비(종료했으나 회수 전)는 죽은 것으로
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def max_overlap(rows: list[dict[str, Any]]) -> int:
    ev = sorted([(r["t0"], 1) for r in rows] + [(r["t1"], -1) for r in rows], key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _t, d in ev:
        cur += d
        best = max(best, cur)
    return best


def doe_worker_settings(base: Path, exe: Path, **bd: Any) -> dict[str, Any]:
    from doe_support import doe_settings_dict

    d = doe_settings_dict(base)
    sect = d["bead_doe"]
    sect["paicad"] = {**sect.get("paicad", {}), "exe": str(exe), "threads": 2,
                      "timeout_s": {"version": 30, "fixed_scan": 60, "extract": 60, "tag": 60, "grid": 60, "run": 60,
                                    "update": 60}}
    for k, v in bd.items():
        if isinstance(v, dict) and isinstance(sect.get(k), dict):
            sect[k] = {**sect[k], **v}
        else:
            sect[k] = v
    return d


def plate_step(path: Path, lx: float = 300.0, lz: float = 200.0) -> bytes:
    """XZ 평면(y = 0) 판 STEP(gmsh OCC) — ③ 입력."""
    import gmsh
    import numpy as np

    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        s = gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, lx, lz)
        gmsh.model.occ.rotate([(2, s)], 0, 0, 0, 1, 0, 0, np.pi / 2)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()
