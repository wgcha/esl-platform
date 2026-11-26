"""V-0250-VB-11 정확도 표(계약 esl_virtual_bead.md §12-11, D-0.25.0-VB-17·19): resources/vbead_accuracy.json(화면 툴팁 자료)과
tests/doe/vbead_accuracy.md 가 같은 값, 칸 상태 = 해상도 규칙, h 5 칸 재계산 = 표, h 1.5 차 ≤ h 3 차(수렴 방향), h 3 |차| ≤ 5 %,
acc_hint 선택. 표 생성 = ``python tests/doe/synth_vbead.py OUT.json``(h 1.5 칸 느림 — 여기서는 다시 풀지 않음)."""
import itertools
import json
import os
import re

import pytest
import synth_vbead as sv
from _bg_util import bgr

from esl.doe import DEFAULTS, RESOURCES

TAB = os.path.join(RESOURCES, "vbead_accuracy.json")
MD = os.path.join(os.path.dirname(__file__), "vbead_accuracy.md")


def _tab():
    with open(TAB, encoding="utf-8") as fh:
        return json.load(fh)


def test_table_shape_and_status():
    t = _tab()
    assert t["schema"] == "esl/vbead_accuracy/1"
    keys = [(c["h"], c["d"], c["theta"]) for c in t["cells"]]
    assert keys == list(itertools.product(sv.GRID["h"], sv.GRID["d"], sv.GRID["theta"]))      # 12칸
    from esl.morph import virtual_bead as vbm
    assert sv.MIN_WALL == DEFAULTS["virtual_bead"]["min_wall_elems"]
    for c in t["cells"]:
        rs = vbm.resolution(c["h"], sv.W_TOP, c["theta"], c["d"], sv.MIN_WALL)
        want = "VB_MESH_COARSE" if rs["codes"] else ("VB_WALL_COARSE" if rs["warns"] else "ok")
        assert c["status"] == want, c
        assert (c["c_err_pct"] is None) == (want == "VB_MESH_COARSE")


def test_markdown_same_values():
    md = open(MD, encoding="utf-8").read()
    for c in _tab()["cells"]:
        row = f"| {c['h']:g} | {c['d']:g} | {c['theta']:g} |"
        assert row in md, row
        line = next(x for x in md.splitlines() if x.startswith(row))
        if c["c_err_pct"] is None:
            assert "불가" in line
        else:
            for k in ("C_p_err_pct", "C_f_err_pct", "Pi_prescribed_err_pct", "Pi_spring_err_pct"):
                assert f"{c[k]:+.3f}" in line, (k, line)


def test_convergence_and_h3_limit():
    cells = {(c["h"], c["d"], c["theta"]): c for c in _tab()["cells"]}
    for d, th in itertools.product(sv.GRID["d"], sv.GRID["theta"]):
        a, b = cells[(3.0, d, th)], cells[(1.5, d, th)]
        if a["c_err_pct"] is None or b["c_err_pct"] is None:
            continue
        assert abs(b["c_err_pct"]) <= abs(a["c_err_pct"]) + 1e-9, (d, th)                   # 수렴 방향
        assert abs(a["c_err_pct"]) <= 5.0 and abs(a["pi_err_pct"]) <= 5.0, (d, th)           # 초안 기준(측정 후 확정)


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


def test_acc_hint_pick():
    t = _tab()
    ok = [c for c in t["cells"] if c["c_err_pct"] is not None]
    c = ok[-1]
    h = bgr.vb_acc_hint(c["h"], c["d"], c["theta"], t)
    assert h == {"h": c["h"], "d": c["d"], "theta": c["theta"], "c_err_pct": c["c_err_pct"], "pi_err_pct": c["pi_err_pct"]}
    assert bgr.vb_acc_hint(50.0, 3.0, 45.0, t) is None                                       # 표 밖
    assert bgr.vb_acc_hint(3.0, 6.0, 45.0, {"cells": []}) is None
    assert re.match(r"^esl/", t["schema"])
