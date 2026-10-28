"""V-OR-8 (fem): 자유·소형·대형 필드 동일 결과, 연속 줄, 실수 축약, INCLUDE 거부, 비지원 카드 집계, CP 거부,
PSHELL/MAT1 누락, write_fem 왕복."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.opt import femread as fr

FREE = """$ template
BEGIN BULK
GRID,1,,0.,0.,0.
GRID,2,,10.,0.,0.
GRID,3,,10.,0.,10.
GRID,4,,0.,0.,10.
GRID,5,,20.,0.,0.
CQUAD4,11,7,1,2,3,4
CTRIA3,12,7,2,5,3
PSHELL,7,3,1.5,3
MAT1,3,2.1+5,,0.3,7.85-9
CBAR,99,1,1,2
ENDDATA
"""


def f8(*xs):
    return "".join(f"{str(x):<8}" for x in xs)


SMALL = "\n".join([
    "BEGIN BULK",
    f8("GRID", 1, "", "0.", "0.", "0."), f8("GRID", 2, "", "10.", "0.", "0."), f8("GRID", 3, "", "10.", "0.", "10."),
    f8("GRID", 4, "", "0.", "0.", "10."), f8("GRID", 5, "", "20.", "0.", "0."),
    f8("CQUAD4", 11, 7, 1, 2, 3, 4), f8("CTRIA3", 12, 7, 2, 5, 3),
    f8("PSHELL", 7, 3, "1.5", 3), f8("MAT1", 3, "2.1E5", "", ".3"),
    "ENDDATA"])


def f16(name, *xs):
    return f"{name:<8}" + "".join(f"{str(x):<16}" for x in xs)


LARGE = "\n".join([
    "BEGIN BULK",
    f16("GRID*", 1, "", "0.", "0."), "*       0.", f16("GRID*", 2, "", "10.", "0."), "*       0.",
    f16("GRID*", 3, "", "10.", "0."), "*       10.", f16("GRID*", 4, "", "0.", "0."), "*       10.",
    f16("GRID*", 5, "", "20.", "0."), "*       0.",
    "CQUAD4,11,7,1,2,3,4", "CTRIA3,12,7,2,5,3", "PSHELL,7,3,1.5,3", "MAT1,3,210000.,,0.3", "ENDDATA"])


def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="ascii")
    return str(p)


def test_formats_agree(tmp_path):
    a = fr.read_fem(_w(tmp_path, "a.fem", FREE))
    b = fr.read_fem(_w(tmp_path, "b.fem", SMALL))
    c = fr.read_fem(_w(tmp_path, "c.fem", LARGE))
    for m in (b, c):
        for k in ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu"):
            assert np.array_equal(np.asarray(a[k]), np.asarray(m[k])), k
    assert a["E"][0] == 2.1e5 and a["mats"][0]["rho"] == 7.85e-9
    assert a["unsupported"] == {"CBAR": 1}
    assert a["elem_type"].tolist() == [4, 3] and a["conn"][1].tolist() == [1, 4, 2, -1]
    assert a["pids"][0]["n_elems"] == 2


def test_continuation_free_and_small(tmp_path):
    txt = "BEGIN BULK\nGRID,1,,0.,0.,0.\nGRID,2,,1.,0.,0.\nGRID,3,,1.,0.,1.\nCTRIA3,5,7,1,2,3,,,+\n+,,0.1\n" \
          "PSHELL,7,3,2.0\n" + f8("MAT1", 3, "", "8.0E4", ".3") + "\nENDDATA\n"
    m = fr.read_fem(_w(tmp_path, "c.fem", txt))
    assert m["elem_id"].tolist() == [5]
    assert abs(m["E"][0] - 2 * 8.0e4 * 1.3) < 1e-6          # E 없으면 G·ν 로


@pytest.mark.parametrize("bad,msg", [
    ("INCLUDE 'x.inc'\n", "INCLUDE"),
    ("GRID,9,5,0.,0.,0.\n", "CP"),
])
def test_rejects(tmp_path, bad, msg):
    with pytest.raises(EslError) as ei:
        fr.read_fem(_w(tmp_path, "x.fem", FREE.replace("ENDDATA\n", bad + "ENDDATA\n")))
    assert ei.value.code == "MESH_INVALID" and msg in ei.value.message


def test_rejects_include_before_bulk(tmp_path):
    """통합(Verifier, 계약 §7.2): BEGIN BULK 앞(제어·케이스 구역) INCLUDE 도 거부."""
    assert "BEGIN BULK" in FREE
    txt = "SUBCASE 1\n  INCLUDE 'loads.inc'\n" + FREE
    with pytest.raises(EslError) as ei:
        fr.read_fem(_w(tmp_path, "h.fem", txt))
    assert ei.value.code == "MESH_INVALID" and "INCLUDE" in ei.value.message and "줄 2" in ei.value.message


def test_missing_prop_mat(tmp_path):
    with pytest.raises(EslError) as ei:
        fr.read_fem(_w(tmp_path, "x.fem", FREE.replace("PSHELL,7,3,1.5,3\n", "")))
    assert "PSHELL" in ei.value.message
    with pytest.raises(EslError) as ei:
        fr.read_fem(_w(tmp_path, "y.fem", FREE.replace("MAT1,3,2.1+5,,0.3,7.85-9\n", "")))
    assert "MAT1" in ei.value.message
    with pytest.raises(EslError):
        fr.read_fem(_w(tmp_path, "z.fem", FREE.replace("CQUAD4,11,7,1,2,3,4", "CQUAD4,11,7,1,2,3,44")))


def test_write_roundtrip(tmp_path):
    m = so.plate(5, 3, n_tria_cols=1)
    m["thickness"][:4] = 2.0
    p = fr.write_fem(str(tmp_path / "out.fem"), m, header=["round trip"])
    r = fr.read_fem(p)
    for k in ("node_id", "elem_id", "elem_type", "conn"):
        assert np.array_equal(np.asarray(r[k]), np.asarray(m[k])), k
    assert np.allclose(r["x0"], m["x0"]) and np.allclose(r["thickness"], m["thickness"])
    assert np.allclose(r["E"], m["E"]) and np.allclose(r["nu"], m["nu"])
    assert set(r["elem_pid"].tolist()) >= {10}
    assert r["mats"][0]["id"] == 1                           # 원 재료 ID 유지
