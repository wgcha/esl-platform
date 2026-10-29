"""v0.8.0 (이슈 #35): OptiStruct 덱 카드 필드 정합 — OptiStruct Reference Guide 형식표와 칸 단위 대조.

출처: DTPG https://help.altair.com/hwsolvers/os/topics/solvers/os/dtpg_bulk_r.htm (2025·2026 형식표:
비드 줄 = (1) 빈 칸 (2) MW (3) ANG (4) BF (5) HGT (6) NORM/XD (7) YD (8) ZD (9) SKIP, 플래그 없음 /
PID 연속 줄 = (2) 빈 칸, (3) PID7… / BOUNDS 줄 = (2) BOUNDS (3) LB (4) UB). 실기 .out(이슈 #35):
``"+,BEAD,60.,45.,10.,YES,BC"`` → ``ERROR # 1485 … Field 0 contains unrecognized/unexpected label``.
"""
import os
import sys

import numpy as np
import pytest

from esl.errors import EslError
from esl.library import optdeck as od
from esl.library import settings as lset
from esl.opt import DEFAULTS
from esl.opt import osout

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_1485 = os.path.join(HERE, "data", "os_check_1485.out")
ISSUE35_LINE = "+,BEAD,60.,45.,10.,YES,BC"
SKIP = ("NONE", "BC", "SPC", "LOAD", "BOTH")


def _t0():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "library"))
    try:
        import test_optdeck as t0
    finally:
        sys.path.pop(0)
    return t0


def _cols(ln: str, fmt: str) -> list[str]:
    """카드 줄 → 칸 (1)..(9) (0-기반 목록, [0] = 카드명/연속 표시)."""
    if fmt == "free":
        c = ln.split(",")
    else:
        c = [ln[k:k + 8].strip() for k in range(0, len(ln), 8)]
    return (c + [""] * 10)[:10]


def _card_lines(fem: str, name: str) -> list[list[str]]:
    lines = fem.splitlines()
    out, on = [], False
    for ln in lines:
        if ln.startswith("$"):
            continue
        head = ln.split(",")[0] if "," in ln else ln[:8].strip()
        if head == name:
            out.append([ln])
            on = True
        elif head == "+" and on:
            out[-1].append(ln)
        else:
            on = False
    return out


def _num(x):
    try:
        float(x)
        return "." in x or "E" in x.upper()
    except ValueError:
        return False


def _write(tmp_path, n_pids=1, fmt="free", **kw):
    t0 = _t0()
    m = t0.small_mesh()
    if n_pids > 1:   # 요소마다 다른 PID → 설계 PSHELL n_pids 개
        m["elem_pid"] = 70 + np.arange(m["elem_id"].size) % n_pids
    d = {**t0.DESIGN, "nondesign_node_ids": [], "card_format": fmt,
         "bead": {"min_width": 60.0, "angle": 45.0, "height": 10.0}, "server": {"opt_run_id": 7, "scenario": "S1",
                                                                              "desmax": 30}, **kw}
    s = od.write(m, t0.load_cases(), t0.SUP, d, str(tmp_path))
    return s, open(os.path.join(tmp_path, "esl_bead.fem"), encoding="ascii").read()


@pytest.mark.parametrize("fmt", ["free", "fixed"])
def test_dtpg_matches_reference_layout(tmp_path, fmt):
    s, fem = _write(tmp_path, fmt=fmt)
    (dtpg,) = _card_lines(fem, "DTPG")
    c0 = _cols(dtpg[0], fmt)
    assert c0[:4] == ["DTPG", str(s["ids"]["dtpg"]), "PSHELL", str(s["design_pids"][0])]
    bead = _cols(dtpg[1], fmt)
    assert bead[0] == "+"
    assert _num(bead[1]) and float(bead[1]) == 60.0          # (2) MW
    assert _num(bead[2]) and float(bead[2]) == 45.0          # (3) ANG 1..89
    assert bead[3] in ("YES", "NO")                           # (4) BF
    assert _num(bead[4]) and float(bead[4]) == 10.0          # (5) HGT
    assert bead[5] == "NORM" and bead[6] == bead[7] == ""     # (6) NORM/XD (7) YD (8) ZD
    assert bead[8] in SKIP and bead[8] == "BC"                # (9) SKIP
    bnd = _cols(dtpg[2], fmt)
    assert bnd[:4] == ["+", "BOUNDS", "0.", "1."]
    assert len(dtpg) == 3 and "BEAD" not in fem.replace("BEADFRAC", "")
    if fmt == "free":
        assert dtpg[1] == "+,60.,45.,YES,10.,NORM,,,BC" and dtpg[1] != ISSUE35_LINE
    else:
        assert all(len(ln) <= 72 and len(ln) % 8 == 0 and "," not in ln for ln in dtpg)


def test_dtpg_pid_continuation_starts_col3(tmp_path):
    s, fem = _write(tmp_path, n_pids=9)
    (dtpg,) = _card_lines(fem, "DTPG")
    pids = [str(p) for p in s["design_pids"]]
    assert len(pids) > 6
    assert _cols(dtpg[0], "free")[3:9] == pids[:6]
    cont = _cols(dtpg[1], "free")
    assert cont[0] == "+" and cont[1] == "" and cont[2:2 + len(pids) - 6] == pids[6:]
    assert _num(_cols(dtpg[2], "free")[1])                    # 그다음 = 비드 줄(MW)


def test_dtpg_layout_configurable_and_validated(tmp_path):
    # 옛 배치를 설정으로 재현할 수 있음(버전별 차이 흡수용) — 기본값은 공식 형식
    _s, fem = _write(tmp_path, dtpg={"bead_flag": "BEAD", "bead_fields": ["MW", "ANG", "HGT", "BF", "SKIP"]})
    assert ISSUE35_LINE in fem.splitlines()
    for bad in ({"bead_fields": ["MW", "ANG", "BF", "SKIP"]}, {"bead_fields": ["MW", "ANG", "BF", "HGT", "SKIP", "X"]},
                {"pid_cont_col": 4}, {"draw": "X"}, {"bead_flag": "B1"}, {"oops": 1}):
        with pytest.raises(EslError):
            od.dtpg_layout(bad)
    assert od.dtpg_layout(None) == od.DTPG_DEFAULT


def test_library_settings_fill_and_validate_dtpg():
    cfg = {"optdeck": {}}
    lset.fill_defaults(cfg)
    assert cfg["optdeck"]["dtpg"] == od.DTPG_DEFAULT
    rule = lset.SCHEMA["optdeck"]["dtpg"]["bead_fields"]
    rule("k", ["MW", "ANG", "BF", "HGT", "DRAW", "-", "-", "SKIP"])
    with pytest.raises(EslError):
        rule("k", ["MW", "ANG", "BF", "HGT"])


def test_other_cards_field_positions(tmp_path):
    s, fem = _write(tmp_path)
    ids = s["ids"]
    (dresp,) = _card_lines(fem, "DRESP1")
    assert _cols(dresp[0], "free")[:4] == ["DRESP1", str(ids["dresp_comp"]), "COMP", "COMP"]   # ID LABEL RTYPE (PTYPE 비움)
    dob = [_cols(c[0], "free") for c in _card_lines(fem, "DOBJREF")]
    assert [c[:6] for c in dob] == [["DOBJREF", str(ids["dobjref"]), str(ids["dresp_comp"]), "", "2.5", "1"],
                                    ["DOBJREF", str(ids["dobjref"]), str(ids["dresp_comp"]), "", "1.", "2"]]
    assert _card_lines(fem, "DOPTPRM")[0] == ["DOPTPRM,DESMAX,30"]
    case = fem.split("BEGIN BULK")[0]
    assert f"DESOBJ(MINMAX) = {ids['dobjref']}" in case and "OUTPUT,H3D,ALL" in case
    assert [ln.strip() for ln in case.splitlines() if ln.strip().startswith("LABEL")] == \
        ["LABEL REP1_Corner146", "LABEL REP2_Face3"]
    # 모든 줄 ASCII, 자유형식 데이터 칸 ≤ 8(+카드명), 실수 칸에 소수점
    for ln in fem.splitlines():
        assert ln.isascii()
        if not ln.startswith("$") and "," in ln and not ln.startswith("INCLUDE"):
            assert len(ln.split(",")) <= 9, ln


def test_parse_real_1485_out():
    text = open(OUT_1485, encoding="utf-8").read()
    cfg = DEFAULTS["solve"]
    assert osout.classify(0, text, cfg, True) == "OS_SOLVE_FAILED"    # 종료코드 0 이어도 ERROR → 실패
    p = osout.parse_out(text, cfg)
    assert len(p["errors"]) == 2 and len(p["error_blocks"]) == 1      # 본문 + 끝 요약 → 한 블록
    b = p["error_blocks"][0]
    assert b["code"] == 1485 and b["detail"] == ["Field 0 contains unrecognized/unexpected label."]
    assert b["card"] == "DTPG" and b["card_id"] == "9000006" and b["continuation"] == 1
    assert b["deck_line_no"] == 446378 and b["quoted"] == ISSUE35_LINE
    assert b["deck_file"].endswith("/solve/esl_bead.fem")
    assert osout.error_summary(b) == ('ERROR # 1485 in the input data: Field 0 contains unrecognized/unexpected label. — DTPG,9000006 '
                                      f'연속 줄 1, 덱 줄 446378: "{ISSUE35_LINE}"')
    full = osout.error_text(p["error_blocks"])
    assert "See next message about line 446378" in full and "(this is continuation line 1 of DTPG,9000006 bulk data)" in full
    with pytest.raises(EslError, match="Field 0 contains"):
        osout.require_ok(0, text, cfg, True)


def test_error_detail_lines_setting_and_plain_error():
    cfg = {**DEFAULTS["solve"], "error_detail_lines": 1}
    text = " *** ERROR # 2000 *** bad thing\n line a\n line b\n\n"
    (b,) = osout.parse_out(text, cfg)["error_blocks"]
    assert b["detail"] == ["line a"] and b["context"] == [] and b["card"] is None
    assert osout.error_summary(b) == "ERROR # 2000 bad thing: line a"
    assert osout.parse_out(text, {**cfg, "error_detail_lines": 0})["error_blocks"][0]["detail"] == []
