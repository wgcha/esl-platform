"""0.5.2 대상 파트만 읽는 rad 파서 ↔ 기존(0.5.1) 파서 동작 동일성·성능 회귀 시험.

기준 구현: tests/rad/legacy_parser.py (0.5.1 esl/rad/parser.py 그대로 보존).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from esl.errors import EslError
from esl.rad import parser as NEW

HERE = Path(__file__).parent
FIX = HERE / "fixtures"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_esl_test_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


OLD = _load("legacy_parser")
SYN = _load("synth_rad")


def _run(fn, *a, **k):
    try:
        return ("ok", fn(*a, **k))
    except EslError as e:
        return ("err", (e.code, str(e)))


def _assert_same_model(a, b):
    for f in dataclasses.fields(a):
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, np.ndarray):
            assert va.dtype == vb.dtype and va.shape == vb.shape, f.name
            assert np.array_equal(va, vb), f.name
        else:
            assert va == vb, f.name


def _assert_same(rad, title, **kw):
    ro, rn = _run(OLD.parse_rad, rad, title, **kw), _run(NEW.parse_rad, rad, title, **kw)
    assert ro[0] == rn[0], (title, ro, rn)
    if ro[0] == "ok":
        _assert_same_model(ro[1], rn[1])
    else:
        assert ro[1] == rn[1]
    return rn


def _assert_same_deck(rad, **kw):
    lo, ln = _run(OLD.list_parts, rad, **kw), _run(NEW.list_parts, rad, **kw)
    assert lo == ln
    if lo[0] == "ok":
        for p in lo[1]:
            _assert_same(rad, p["title"], **kw)
            _assert_same(rad, p["title"], match="exact", **kw)
    _assert_same(rad, "no such part", **kw)
    return lo


@pytest.mark.parametrize("name", ["main.rad", "model2.rad", "real_101_parts.rad"])
def test_fixtures_identical(name):
    _assert_same_deck(FIX / name)
    _assert_same_deck(FIX / name, max_include_depth=1)


def test_fixture_override_identical():
    for ov in ({"7": {"E": 12.5, "nu": 0.49}}, {7: {"E": -1, "nu": 0.3}}, {1: {"E": 5.0, "nu": 0.2, "rho": 1.0}}):
        for title in ("rubber skin", "mixed", "dup title"):
            _assert_same(FIX / "model2.rad", title, material_override=ov)
        _assert_same(FIX / "main.rad", "main board", material_override=ov)


@pytest.mark.parametrize("nodes", ["before", "after", "split"])
@pytest.mark.parametrize("crlf", [False, True])
def test_synthetic_identical(tmp_path, nodes, crlf):
    rad, title = SYN.make_model(tmp_path, 4000, n_parts=5, nodes=nodes, fancy=True, crlf=crlf, seed=3)
    lo = _assert_same_deck(rad)
    assert lo[0] == "ok" and len(lo[1]) == 6
    m = _assert_same(rad, title)[1]
    assert m.elem_id.size == 800 and m.includes
    _assert_same(rad, title, max_include_depth=1)            # 깊이 초과 오류 동일


def test_synthetic_plain_identical(tmp_path):
    rad, title = SYN.make_model(tmp_path, 3000, n_parts=4, nodes="split", fancy=False, seed=1)
    _assert_same_deck(rad)


_BASE = """\
/BEGIN
run
      2022         0
                  Mg                  mm                   s
                  Mg                  mm                   s
{nodes_before}
/PART/1
Target
         1         1         0
/PART/2
Other
         2         2         0
/SHELL/2
        50         1         2         3         4
{shell}
/MAT/{law}/1
m
            7.85E-09
            210000.0                 0.3
/MAT/ELAST/2
m2
            7.85E-09
            70000.0                 0.33
/PROP/SHELL/1
p
        24

{prop_tail}
         5                           1.6
/PROP/SHELL/2
p2
        24

         5                           2.0
{nodes_after}
"""
_NODES = """\
/NODE{unit}
         1                 0.0                 0.0                 0.0
         2                10.0                 0.0                 0.0
         3                10.0                10.0                 0.0
         4                 0.0                10.0                 0.0
         4                 0.0                12.5                 0.0
"""


def _deck(tmp_path, *, shell="/SHELL/1\n         7         1         2         3         4\n",
          law="ELAST", prop_tail="#Hm", unit="", after=False, extra=""):
    nodes = _NODES.format(unit=unit)
    txt = _BASE.format(nodes_before="" if after else nodes, nodes_after=nodes if after else "",
                       shell=shell, law=law, prop_tail=prop_tail) + extra
    p = tmp_path / "d_0000.rad"
    p.write_text(txt)
    return p


@pytest.mark.parametrize("kw", [
    {}, {"after": True}, {"unit": "/9"}, {"law": "LAW99"}, {"law": "LAW36"},
    {"shell": "/SHELL/1\n         7         1         2         3        77\n"},          # 없는 노드
    {"shell": "/SHELL/1\n         7         1         2         3\n"},                     # 삼각형(n4 공란)
    {"shell": "/SHELL/1\n         7         1         2         3         4\n         7         2         3         4         1\n"},  # 중복 ID
    {"shell": "/SH3N/1\n         7         1         2         3\n/BRICK/1\n         9         1         2         3         4\n"},
    {"shell": "/SHELL/1\n         7         1                   3         4\n"},          # 대상 파트 형식 오류
    {"shell": "/SHELL/1\n         7         1         2         3         4                         0.0                 abc\n"},
    {"shell": ""},                                                                         # 대상 쉘 없음
    {"extra": "/PART/1\nTarget\n         1         1         0\n/MAT/ELAST/1\nx\n 1\n 1.0 0.3\n"},  # 중복 경고
    {"extra": "/PART/3\ntarget\n         1         1         0\n"},                          # PART_AMBIGUOUS
    {"extra": "#include missing.inc\n"},
    {"extra": "/INCLUDE\n"},
])
def test_small_decks_identical(tmp_path, kw):
    p = _deck(tmp_path, **kw)
    lo, ln = _run(OLD.list_parts, p), _run(NEW.list_parts, p)
    if lo[0] == "ok" or lo[1][0] != "RAD_PARSE_ERROR" or "해석 실패" not in lo[1][1]:
        assert lo == ln
    # (행·카드 형식 오류는 list_parts 가 더 이상 잡지 않음 — 0.5.2 동작 변화)
    fmt_err = lo[0] == "err" and "해석 실패" in lo[1][1]
    for t in ("target", "other", "nope"):
        for ov in (None, {1: {"E": 1.0, "nu": 0.3}}):
            if fmt_err and t != "target":
                # 대상(target) 쪽 형식 오류: 다른 파트를 고르면 새 파서는 그 행을 읽지 않음
                assert _run(NEW.parse_rad, p, t, material_override=ov)[0] == ("err" if t == "nope" else "ok")
                continue
            _assert_same(p, t, material_override=ov)


def test_error_codes_unchanged(tmp_path):
    assert _run(NEW.parse_rad, _deck(tmp_path), "nope")[1][0] == "PART_NOT_FOUND"
    assert _run(NEW.parse_rad, _deck(tmp_path, extra="/PART/3\ntarget\n         1         1         0\n"),
                "target")[1][0] == "PART_AMBIGUOUS"
    assert _run(NEW.parse_rad, _deck(tmp_path, law="LAW99"), "target")[1][0] == "MATERIAL_UNRESOLVED"
    assert _run(NEW.parse_rad, _deck(tmp_path, extra="#include missing.inc\n"), "target")[1][0] == "RAD_PARSE_ERROR"


def test_other_part_format_error_skipped(tmp_path):
    """동작 변화(0.5.2): 다른 파트 요소 블록·미참조 노드 좌표의 형식 오류는 더 이상 검출하지 않음."""
    bad = ("/SHELL/1\n         7         1         2         3         4\n"
           "/SHELL/2\n        51         1         2         3         4                         0.0                 abc\n")
    p = _deck(tmp_path, shell=bad,
              extra="/NODE\n        99                 xyz                 0.0                 0.0\n")
    assert _run(OLD.parse_rad, p, "target")[0] == "err"
    m = NEW.parse_rad(p, "target")
    assert m.elem_id.tolist() == [7] and m.max_ids["elem"] == 51 and m.max_ids["node"] == 99
    assert {q["id"]: q["n_elems"] for q in NEW.list_parts(p)} == {1: 1, 2: 2}


def _timed(fn, *a):
    t = time.perf_counter()
    fn(*a)
    return time.perf_counter() - t


def test_perf_regression(tmp_path):
    """합성 20만 요소(대상 20%): 기존 대비 list_parts ≤ 0.5배, parse_rad ≤ 0.8배 + 느슨한 절대 상한.

    참고(1M 요소, 개발 PC): list_parts 5.2→0.4 s, parse_rad 6.3→1.7 s (docs/decisions.md 0.5.2).
    """
    n = int(os.environ.get("ESL_PERF_ELEMS", "200000"))
    rad, title = SYN.make_model(tmp_path, n, fancy=False)
    t_old_l, t_new_l = _timed(OLD.list_parts, rad), _timed(NEW.list_parts, rad)
    t_old_p, t_new_p = _timed(OLD.parse_rad, rad, title), _timed(NEW.parse_rad, rad, title)
    print(f"\nlist_parts {t_old_l:.2f}->{t_new_l:.2f}s, parse_rad {t_old_p:.2f}->{t_new_p:.2f}s (n={n})")
    scale = n / 200000
    assert t_new_l <= 0.5 * t_old_l and t_new_l < 3.0 * scale
    assert t_new_p <= 0.8 * t_old_p and t_new_p < 8.0 * scale
