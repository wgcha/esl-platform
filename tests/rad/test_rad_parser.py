"""T-RAD-1·2 (esl_core.md §6, esl.md V-RAD-1·2)."""
import os
import shutil

import numpy as np
import pytest

from esl.errors import EslError
from esl.rad import list_parts, parse_rad, write_rad

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
MAIN = os.path.join(FIX, "main.rad")
M2 = os.path.join(FIX, "model2.rad")


def _code(fn, *a, **k):
    with pytest.raises(EslError) as ei:
        fn(*a, **k)
    return ei.value.code


# ---------------------------------------------------------------- T-RAD-1
def test_part_title_ci_whitespace_and_includes():
    m = parse_rad(MAIN, "main board")
    assert m.part_id == 10
    m2 = parse_rad(MAIN, "  MAIN\tBoard ")
    assert m2.part_id == 10
    assert [os.path.basename(p) for p in m.includes] == ["level1.inc", "level2.inc"]
    # include 2단에 있는 파트도 해석
    assert parse_rad(MAIN, "BRACKET").part_id == 30
    assert parse_rad(MAIN, "Cover Plate").part_id == 20
    assert m.units_label == "Mg mm s"


def test_exact_match_mode():
    assert _code(parse_rad, MAIN, "main board", match="exact") == "PART_NOT_FOUND"
    assert parse_rad(MAIN, "  Main   BOARD", match="exact").part_id == 10


def test_part_not_found_and_ambiguous():
    assert _code(parse_rad, MAIN, "nope") == "PART_NOT_FOUND"
    assert _code(parse_rad, M2, "dup title") == "PART_AMBIGUOUS"


def test_list_parts():
    parts = {p["id"]: p for p in list_parts(MAIN)}
    assert sorted(parts) == [10, 20, 30, 40]
    assert parts[10]["n_elems"] == 4 and parts[40]["n_elems"] == 1


def test_max_ids_whole_model():
    m = parse_rad(MAIN, "main board")
    assert m.max_ids == {"node": 2008, "elem": 5003, "part": 40, "prop": 4, "mat": 3,
                         "func": 900, "grnod": 77, "load": 12, "bcs": 5}


def test_include_depth_and_missing(tmp_path):
    assert _code(parse_rad, MAIN, "bracket", max_include_depth=1) == "RAD_PARSE_ERROR"
    d = tmp_path / "d"
    shutil.copytree(FIX, d)
    os.remove(d / "inc" / "level2.inc")
    assert _code(parse_rad, d / "main.rad", "main board") == "RAD_PARSE_ERROR"


# ---------------------------------------------------------------- T-RAD-2
def test_mesh_values_and_layout():
    m = parse_rad(MAIN, "main board")
    assert m.node_id.dtype == np.int64 and m.node_id.tolist() == list(range(1, 10))
    assert m.x0.dtype == np.float64 and m.x0.shape == (9, 3)
    assert np.allclose(m.x0[8], [20.0, 20.0, 0.0])
    assert m.elem_id.tolist() == [101, 102, 103, 104]          # 오름차순(카드 순서 무관)
    assert m.elem_type.dtype == np.int8 and m.elem_type.tolist() == [4, 4, 4, 4]
    # conn 은 노드 행 인덱스
    assert m.conn.dtype == np.int64
    assert m.node_id[m.conn[0]].tolist() == [1, 2, 5, 4]
    assert m.node_id[m.conn[3]].tolist() == [5, 6, 9, 8]
    assert m.elem_pid.tolist() == [1, 1, 1, 1]
    # 요소 카드 두께(>0) 우선, 0/빈칸이면 /PROP/SHELL Thick
    assert m.thickness.tolist() == [1.6, 2.5, 1.6, 1.6]


def test_tria_and_law2():
    m = parse_rad(MAIN, "cover plate")
    assert m.elem_type.tolist() == [3, 3]
    assert m.conn[:, 3].tolist() == [-1, -1]
    assert m.node_id[m.conn[0, :3]].tolist() == [201, 202, 204]
    assert m.thickness.tolist() == [1.2, 0.8]
    assert m.mats == [{"id": 2, "law": "LAW2", "E": 4500.0, "nu": 0.38, "rho": 1.32e-9, "source": "rad"}]
    assert np.all(m.E == 4500.0) and np.all(m.nu == 0.38)


def test_law1_law36():
    m1 = parse_rad(MAIN, "main board")
    assert m1.mats[0]["law"] == "LAW1" and m1.mats[0]["E"] == 210000.0 and m1.mats[0]["nu"] == 0.3
    assert m1.mats[0]["rho"] == 7.85e-9
    m3 = parse_rad(MAIN, "bracket")
    assert m3.mats[0]["law"] == "LAW36" and m3.mats[0]["E"] == 73000.0 and m3.mats[0]["nu"] == 0.33
    assert m3.thickness.tolist() == [2.0]


def test_unsupported_law_and_override():
    assert _code(parse_rad, M2, "rubber skin") == "MATERIAL_UNRESOLVED"
    m = parse_rad(M2, "rubber skin", material_override={"7": {"E": 12.5, "nu": 0.49}})
    assert m.mats[0]["source"] == "override" and m.mats[0]["E"] == 12.5
    assert np.all(m.E == 12.5) and np.all(m.nu == 0.49)
    m = parse_rad(M2, "rubber skin", material_override={7: {"E": 12.5, "nu": 0.49}})
    assert m.mats[0]["id"] == 7
    assert _code(parse_rad, M2, "rubber skin", material_override={7: {"E": -1, "nu": 0.3}}) == "MATERIAL_UNRESOLVED"


def test_non_shell_element_in_part():
    assert _code(parse_rad, M2, "mixed", material_override={7: {"E": 1.0, "nu": 0.3}}) == "UNSUPPORTED_ELEMENT"
    assert _code(parse_rad, MAIN, "foam block") == "UNSUPPORTED_ELEMENT"


def test_fixed_width_adjacent_fields(tmp_path):
    # 필드가 공백 없이 붙어 있는 노드 행(10자 ID + 20자 실수)과 D 지수
    import esl.rad.parser as P
    assert P._f("-2.5D+00") == -2.5 and P._f("1.0-3") == 1e-3


# ---------------------------------------------------------------- writer 왕복
def test_writer_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    nid = np.array([3, 7, 8, 12, 15, 20], dtype=np.int64)
    x0 = rng.normal(size=(6, 3)) * 37.123456789
    eid = np.array([9, 4, 6])
    et = np.array([4, 3, 4])
    conn = np.array([[3, 7, 8, 12], [8, 12, 15, -1], [12, 15, 20, 7]])
    th = np.array([1.5, 1.5, 2.25])
    p = write_rad(tmp_path / "s_0000.rad", nid, x0, eid, et, conn, 5, "Synth Part", 11, th, 21,
                  2.1e5, 0.3, extra_parts=2)
    m = parse_rad(p, "synth part")
    o = np.argsort(eid)
    assert m.node_id.tolist() == nid.tolist()
    assert np.allclose(m.x0, x0, rtol=1e-13, atol=0)
    assert m.elem_id.tolist() == eid[o].tolist()
    assert m.elem_type.tolist() == et[o].tolist()
    cids = np.where(m.conn >= 0, m.node_id[m.conn], -1)
    assert cids.tolist() == conn[o].tolist()
    assert m.thickness.tolist() == th[o].tolist()
    assert m.E.tolist() == [2.1e5] * 3 and m.nu.tolist() == [0.3] * 3
    assert m.part_id == 5 and m.elem_pid.tolist() == [11] * 3
    assert m.max_ids["part"] == 7 and m.max_ids["node"] == 28 and m.max_ids["elem"] == 11
    assert parse_rad(p, "extra_part_2").part_id == 7
    # 스칼라 두께
    p2 = write_rad(tmp_path / "t.rad", nid, x0, eid, et, conn, 5, "S", 11, 0.7, 21, 1e3, 0.25)
    assert parse_rad(p2, "s").thickness.tolist() == [0.7] * 3


# ---------------------------------------------------------------- 헤더 unit_ID 접미
_UNIT_DECK = """\
/BEGIN
run
      2022         0
                  Mg                  mm                   s
                  Mg                  mm                   s
/UNIT/9
unit_mm
                  Mg                  mm                   s
/NODE/9
         1                 0.0                 0.0                 0.0
         2                10.0                 0.0                 0.0
         3                10.0                10.0                 0.0
         4                 0.0                10.0                 0.0
/PART/10/9
Unit Part
         1         1         0
/SHELL/10
       100         1         2         3         4
/MAT/ELAST/1/9
steel
            7.85E-09
            210000.0                 0.3
/MAT/LAW2/9
alu_id9
            2.70E-09
             70000.0                0.33
/PROP/SHELL/1/9
prop1
        24
#                 Hm                  Hf                  Hr                  Dm                  Dn

         5                           1.6
/PROP/SHELL/9
prop9
        24

         5                           9.9
/TABLE/1/321/9
tab
/FUNCT/55/9
f
/GRNOD/NODE/66/9
g
/CLOAD/7/9
c
/BCS/3/9
b
/END
"""


def test_header_unit_suffix_not_read_as_id(tmp_path):
    p = tmp_path / "unit_0000.rad"
    p.write_text(_UNIT_DECK)
    m = parse_rad(p, "unit part")
    assert m.part_id == 10
    # /MAT/ELAST/1/9 의 id 는 1 (unit 9 아님) — /MAT/LAW2/9 (id 9) 와 섞이지 않음
    assert m.mats[0]["id"] == 1 and m.mats[0]["E"] == 210000.0 and m.mats[0]["nu"] == 0.3
    assert m.thickness.tolist() == [1.6]
    assert m.elem_pid.tolist() == [1]
    # /NODE/9 는 unit 이라 노드 ID 집계와 무관, /TABLE/1/321 은 차원 1 · ID 321
    assert m.max_ids == {"node": 4, "elem": 100, "part": 10, "prop": 9, "mat": 9,
                         "func": 321, "grnod": 66, "load": 7, "bcs": 3}


def test_split_header_layouts():
    import esl.rad.parser as P
    sh = P._split_header
    assert sh(["MAT", "LAW1", "5", "2"]) == ("MAT", "LAW1", 5, 2)
    assert sh(["MAT", "LAW36", "5"]) == ("MAT", "LAW36", 5, None)
    assert sh(["PROP", "SHELL", "3", "1"]) == ("PROP", "SHELL", 3, 1)
    assert sh(["PART", "8", "1"]) == ("PART", None, 8, 1)
    assert sh(["NODE", "1"]) == ("NODE", None, None, 1)
    assert sh(["SHELL", "10"]) == ("SHELL", None, 10, None)
    assert sh(["TABLE", "1", "77", "4"])[2:] == (77, 4)


# ---------------------------------------------------------------- Windows 절대 include
def _win_inc_deck(tmp_path, inc_line):
    d = tmp_path / "deck"
    shutil.copytree(FIX, d)
    txt = (d / "main.rad").read_text()
    txt = txt.replace("#include inc/level1.inc", inc_line)
    (d / "main.rad").write_text(txt)
    return d


def test_include_windows_abs_with_path_map(tmp_path):
    d = _win_inc_deck(tmp_path, '/INCLUDE "C:\\Users\\Eng\\Proj\\inc\\level1.inc"')
    # level1.inc 는 다시 상대경로 inc/level2.inc 를 포함
    m = parse_rad(d / "main.rad", "bracket",
                  include_path_map={"c:/users/eng/PROJ": str(d)})
    assert m.part_id == 30
    assert os.path.normpath(str(d / "inc" / "level1.inc")) in m.includes
    assert not any("파일명으로 대체" in w for w in m.warnings)


def test_include_unc_with_path_map(tmp_path):
    d = _win_inc_deck(tmp_path, '/INCLUDE "\\\\fileserver\\cae\\inc\\level1.inc"')
    m = parse_rad(d / "main.rad", "cover plate", include_path_map={"//FILESERVER/cae": str(d)})
    assert m.part_id == 20


def test_include_windows_abs_basename_fallback(tmp_path):
    d = _win_inc_deck(tmp_path, '/INCLUDE "D:/elsewhere/level1.inc"')
    # rad 폴더에 level1.inc 를 두면 파일명으로 찾고 경고
    shutil.copy(d / "inc" / "level1.inc", d / "level1.inc")
    m = parse_rad(d / "main.rad", "cover plate")
    assert m.part_id == 20
    assert any("D:/elsewhere/level1.inc" in w and "파일명으로 대체" in w for w in m.warnings)


def test_include_windows_abs_unresolved_message(tmp_path):
    d = _win_inc_deck(tmp_path, '/INCLUDE "D:/elsewhere/nothere.inc"')
    with pytest.raises(EslError) as ei:
        parse_rad(d / "main.rad", "main board")
    assert ei.value.code == "RAD_PARSE_ERROR"
    msg = str(ei.value)
    assert "D:/elsewhere/nothere.inc" in msg and "include_path_map" in msg
