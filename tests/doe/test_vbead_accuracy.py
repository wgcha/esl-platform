"""V-0250-VB-11·27 정확도 표(계약 esl_virtual_bead.md §12-11·§19.5·§19.9.1-6, D-0.25.0-VB-17·19·25·26): resources/vbead_accuracy.json
(schema 2 — cells = r 기본·깊이 보상, cells_r0 = f238144d 값 보존)과 tests/doe/vbead_accuracy.md 가 같은 값, 칸 상태 = 해상도 규칙,
h 5 칸 재계산 = 표, h 1.5 차 ≤ h 3 차(수렴 방향), h 3 |차| ≤ 5 %, acc_hint 세 갈래. 표 생성 =
``python tests/doe/synth_vbead.py OUT.json OLD.json``(h 1.5 칸 느림 — 여기서는 다시 풀지 않음)."""
import itertools
import json
import os
import shutil
import subprocess

import pytest
import synth_vbead as sv
from _bg_util import bgr

from esl.doe import DEFAULTS, RESOURCES

TAB = os.path.join(RESOURCES, "vbead_accuracy.json")
MD = os.path.join(os.path.dirname(__file__), "vbead_accuracy.md")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tab():
    with open(TAB, encoding="utf-8") as fh:
        return json.load(fh)


def test_table_shape_and_status():
    t = _tab()
    assert t["schema"] == "esl/vbead_accuracy/2" and t["world"]["r_mm"] == "default"
    from esl.morph import virtual_bead as vbm
    assert sv.MIN_WALL == DEFAULTS["virtual_bead"]["min_wall_elems"]
    for name in ("cells", "cells_r0"):
        keys = [(c["h"], c["d"], c["theta"]) for c in t[name]]
        assert keys == list(itertools.product(sv.GRID["h"], sv.GRID["d"], sv.GRID["theta"]))      # 12칸
        for c in t[name]:
            rs = vbm.resolution(c["h"], sv.W_TOP, c["theta"], c["d"], sv.MIN_WALL)
            want = "VB_MESH_COARSE" if rs["codes"] else ("VB_WALL_COARSE" if rs["warns"] else "ok")
            assert c["status"] == want, c
            assert (c["c_err_pct"] is None) == (want == "VB_MESH_COARSE")
            assert "depth_mm" not in c                                                         # 개정 3
    for c in t["cells"]:
        if c["c_err_pct"] is not None:
            assert c["r"] == pytest.approx(min(c["h"], vbm.r_cap(sv.W_TOP, min(c["theta"], 59.99), c["d"])), abs=1e-3)
            assert c["warp_n"] >= 0 and c["warp_max_deg"] >= 0


def test_cells_r0_preserved():
    """cells_r0 = f238144d 의 cells(git 이 있을 때 — 얕은 복제·배포본은 건너뜀)."""
    if shutil.which("git") is None:
        pytest.skip("git 없음")
    r = subprocess.run(["git", "-C", ROOT, "show", "f238144d:resources/vbead_accuracy.json"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("f238144d 없음")
    assert _tab()["cells_r0"] == json.loads(r.stdout)["cells"]


def test_markdown_same_values():
    md = open(MD, encoding="utf-8").read()
    t = _tab()
    a, b = md.index("— cells\n"), md.index("— cells_r0\n")
    for part, cells in ((md[a:b], t["cells"]), (md[b:], t["cells_r0"])):
        for c in cells:
            row = f"| {c['h']:g} | {c['d']:g} | {c['theta']:g} |"
            line = next(x for x in part.splitlines() if x.startswith(row))
            if c["c_err_pct"] is None:
                assert "불가" in line
            else:
                for k in ("C_p_err_pct", "C_f_err_pct", "Pi_prescribed_err_pct", "Pi_spring_err_pct"):
                    assert f"{c[k]:+.3f}" in line, (k, line)
                if "r" in c:
                    assert f"{c['r']:.4f}" in line and f"| {c['warp_n']} |" in line


def test_convergence_and_h3_limit():
    for name in ("cells", "cells_r0"):
        cells = {(c["h"], c["d"], c["theta"]): c for c in _tab()[name]}
        mx = {h: max((abs(c["c_err_pct"]) for k, c in cells.items() if k[0] == h and c["c_err_pct"] is not None),
                     default=0.0) for h in sv.GRID["h"]}
        assert mx[1.5] <= mx[3.0] + 1e-9, (name, mx)                                         # 수렴 방향(최대 |차|)
        for d, th in itertools.product(sv.GRID["d"], sv.GRID["theta"]):
            a = cells[(3.0, d, th)]
            if a["c_err_pct"] is not None:
                assert abs(a["c_err_pct"]) <= 5.0 and abs(a["pi_err_pct"]) <= 5.0, (name, d, th)


@pytest.mark.slow
def test_h5_cell_recomputed():
    """h 5 칸(계산 가능한 것)을 다시 풀어 표와 같음(결정적 — 1e-3 %)."""
    for c in _tab()["cells"]:
        if c["h"] != 5.0:
            continue
        got = sv.cell(c["h"], c["d"], c["theta"])
        for k, v in c.items():
            if k.endswith("_pct") and v is not None:
                assert got[k] == pytest.approx(v, abs=1e-3), (k, c)
            elif not k.endswith("_pct"):
                assert got[k] == v, k


def test_acc_hint_pick_v27():
    t = _tab()
    ok = [c for c in t["cells"] if c["c_err_pct"] is not None]
    c = ok[-1]
    h = bgr.vb_acc_hint(c["h"], c["d"], c["theta"], t)                                          # r 생략 → cells
    assert h["c_err_pct"] == c["c_err_pct"] and h["r"] == c["r"]
    c0 = next(x for x in t["cells_r0"] if (x["h"], x["d"], x["theta"]) == (c["h"], c["d"], c["theta"]))
    h0 = bgr.vb_acc_hint(c["h"], c["d"], c["theta"], t, r_user=0.0, r_resolved=0.0)            # 준 r 0 → cells_r0
    assert h0["c_err_pct"] == c0["c_err_pct"]
    assert bgr.vb_acc_hint(c["h"], c["d"], c["theta"], t, r_user=c["r"], r_resolved=c["r"])["c_err_pct"] == c["c_err_pct"]
    assert bgr.vb_acc_hint(c["h"], c["d"], c["theta"], t, r_user=3 * c["r"], r_resolved=3 * c["r"]) is None
    assert bgr.vb_acc_hint(50.0, 3.0, 45.0, t) is None                                         # 표 밖
    assert bgr.vb_acc_hint(3.0, 6.0, 45.0, {"cells": []}) is None
