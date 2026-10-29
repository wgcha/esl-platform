"""누적 씬 상태 파일 파서 (계약 esl_cumulative_input.md §2~§5, V-CI-P1·P2·P3·P4·P6)."""
import os
import shutil
import sys

import numpy as np
import pytest

from esl.errors import EslError
from esl.rad import parse_rad, write_rad
from esl.rad import parser as _p
from esl.rad import state as _st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ISSUE = os.path.join(ROOT, "tests", "fixtures", "cumulative", "issue34")
sys.path.insert(0, os.path.join(ROOT, "tests", "cumulative"))
import synth_cum  # noqa: E402

RAD34 = os.path.join(ISSUE, "Scene07_Edge23_2nd_0000.rad")


# ------------------------------------------------------------------ V-CI-P1 이슈 #34 발췌
def test_p1_issue34_nodes_thickness_and_epsp_aggregates():
    m = parse_rad(RAD34, "Chassis_Rear")
    st = m.state
    assert st is not None and m.part_id == 2
    # 패딩 헤더 /SHELL/         2 → 대상 파트 2 의 쉘 9개, THK 81–100열(상태 두께)
    assert m.elem_id.tolist() == list(range(100001, 100010))
    assert m.thickness[0] == pytest.approx(1.1995980739594, abs=0) and m.thickness[8] == 1.1983038187027
    # 붙은 /NODE 실수(공백 없음): 쉘이 참조하는 노드 18개 = 상태 파일 좌표
    assert m.node_id.size == 18 and st["coord"] == {"source": "state", "n_nodes_state": 18, "n_nodes_rad": 0,
                                                     "n_dup": 0, "n_dup_state": 0}
    i = int(np.searchsorted(m.node_id, 101040))
    sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures", "cumulative"))
    import make_issue34
    assert m.x0[i].tolist() == pytest.approx(list(make_issue34.node_xyz(101040)), abs=1e-12)
    # 상태 파일 종류는 내용으로(.str 헤더가 .sta 이름을 담아도 geometry), /INIBRI 는 이름만 기록
    kinds = {os.path.basename(f["path"]): f["kinds"] for f in st["files"]}
    assert kinds == {"10_Edge_Drop_Scene07_Edge23_1st_0002.str": ["geometry"],
                     "10_Edge_Drop_Scene07_Edge23_1st_0002.sta": ["initial"]}
    sta = [f for f in st["files"] if f["path"].endswith(".sta")][0]
    assert sta["other_blocks"] == ["/INIBRI/STRA_F", "/INIBRI/FAIL"] and sta["inishe_subs"] == ["EPSP_F"]
    assert all(f["runname"] == "10_Edge_Drop_Scene07_Edge23_1st" for f in st["files"])
    # EPSP 집계 4종(100001: 0.001·(IPT·10+IPG), 100002: IPT 3 = 0.02, 100009: NPT=0·NPG=4 1층)
    ep = st["epsp"]
    assert ep.has.tolist() == [True] * 5 + [False] * 3 + [True]
    assert ep.npt.tolist() == [5, 5, 5, 5, 5, 0, 0, 0, 0] and ep.npg[0] == 4 and ep.npg[8] == 4
    a = ep.agg
    assert a["mid_mean"][0] == pytest.approx(0.0325) and a["mid_max"][0] == pytest.approx(0.034)
    assert a["max"][0] == pytest.approx(0.054) and a["mean"][0] == pytest.approx(0.0325)
    assert a["mid_mean"][1] == pytest.approx(0.02) and a["mean"][1] == pytest.approx(0.004)
    assert a["max"][1] == pytest.approx(0.02)
    assert a["mid_mean"][8] == pytest.approx(0.0025) and a["mid_max"][8] == pytest.approx(0.004)
    assert a["max"][8] == pytest.approx(0.004) and a["mean"][8] == pytest.approx(0.0025)
    assert ep.n_records == 11            # 비대상 101054·101055·2091792~4 는 숫자 해석 없이 건너뜀
    assert any(w.startswith("STATE_PARTIAL:") and "100006" in w for w in st["warnings"])
    # 두께 통계 t/t₀ (t₀ = /PROP/SHELL 1.2)
    th = st["thickness"]
    assert th["source"] == "state" and th["t0"] == 1.2 and th["n_changed"] == 0
    assert th["ratio"]["min"] == pytest.approx(1.1983038187027 / 1.2)
    assert th["elem_max_thinning"] == 100009 and st["thk_sta_mismatch"] == 0
    # 상태 /BEGIN 은 units_label 을 바꾸지 않음, 숫자 배율 같음
    assert all(b["compared"] and b["same"] for b in st["begin"]["files"])


def test_p1_thickness_source_prop_uses_original_thickness():
    m = parse_rad(RAD34, "Chassis_Rear", thickness_source="prop")
    assert np.all(m.thickness == 1.2) and m.state["thickness"]["k_l_source"] == "prop"


def test_state_identification_by_header_or_extension(tmp_path):
    a = tmp_path / "x.inc"
    a.write_text("\n  \n#RADIOSS STATE FILE foo_0001.sta\n/NODE\n")
    b = tmp_path / "y.STR"
    b.write_text("/NODE\n")
    c = tmp_path / "z.inc"
    c.write_text("# just a deck\n/NODE\n")
    assert _st.is_state_file(str(a)) and _st.is_state_file(str(b)) and not _st.is_state_file(str(c))


# ------------------------------------------------------------------ V-CI-P2 헤더 규칙
@pytest.mark.parametrize("line,expect", [
    ("/SHELL/         2", ["SHELL", "2"]), ("/TETRA4/        22", ["TETRA4", "22"]),
    ("/SHELL/2", ["SHELL", "2"]), ("/MAT/LAW2/5   # comment", ["MAT", "LAW2", "5"]),
    ("/PART/   7    3", ["PART", "7", "3"]), ("/TITLE some 12", ["TITLE"]), ("/NODE", ["NODE"]),
])
def test_p2_header_pieces(line, expect):
    assert _p._head_pieces(line) == expect


def test_p2_padded_header_was_a_bug_and_plain_decks_unchanged(tmp_path):
    nid = np.arange(1, 10)
    xs, ys = np.meshgrid([0.0, 1, 2], [0.0, 1, 2], indexing="ij")
    x0 = np.c_[xs.ravel(), ys.ravel(), np.zeros(9)]
    conn = np.array([[1, 4, 5, 2], [2, 5, 6, 3], [4, 7, 8, 5], [5, 8, 9, 6]])
    rad = write_rad(tmp_path / "m.rad", nid, x0, [11, 12, 13, 14], [4] * 4, conn, 3, "plate", 1, 1.5, 1, 2e5, 0.3)
    m1 = parse_rad(rad, "plate")
    txt = open(rad).read().replace("/SHELL/3\n", "/SHELL/         3\n")
    assert "/SHELL/         3" in txt
    p2 = tmp_path / "m2.rad"
    p2.write_text(txt)
    m2 = parse_rad(p2, "plate")            # 예전: /SHELL/ → part_ID 없음 RAD_PARSE_ERROR
    assert m1.state is None and m2.state is None
    for k in ("node_id", "x0", "elem_id", "conn", "thickness"):
        assert np.array_equal(getattr(m1, k), getattr(m2, k)), k


# ------------------------------------------------------------------ V-CI-P3 숫자 대체 경로·오류
def _sta_with(tmp_path, rows, elem_ids=(11,)):
    """대상 요소 11 하나(쉘 1개 모델) + 주어진 .sta 레코드 행."""
    nid = np.array([1, 2, 3, 4])
    x0 = np.array([[0.0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]])
    rad = write_rad(tmp_path / "base.rad", nid, x0, list(elem_ids), [4], [[1, 2, 3, 4]], 3, "plate", 1, 1.0, 1,
                    2e5, 0.3)
    sta = tmp_path / "prev_0001.sta"
    sta.write_text("\n".join(synth_cum.BEGIN_NUM + synth_cum.COMMENT7 + rows) + "\n")
    txt = open(rad).read().replace("/END", "#include prev_0001.sta\n/END")
    p = tmp_path / "m.rad"
    p.write_text(txt)
    return p


def test_p3_whitespace_glued_fortran_and_d_exponent(tmp_path):
    rows = ["        11         1         5 1.0000000000000E+00",
            "1.0-3 2.0D-03 3.0E-3",                       # 공백 구분 + Fortran 지수 + D 지수
            "-4.0000000000000E-03-5.0E-3"]               # 붙은 실수(공백 없음) — 대체 경로 토큰 분리
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    ep = m.state["epsp"]
    assert ep.agg["max"][0] == pytest.approx(0.003) and ep.agg["mean"][0] == pytest.approx(-0.0006)
    assert ep.fallback_rows == 2
    rows = ["        11         1         4 1.0000000000000E+00",
            "            1.0D-03       2.000000-03 3.0000000000000E-03 4.0000000000000E-03"]
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    assert m.state["epsp"].agg["mean"][0] == pytest.approx(0.0025)


@pytest.mark.parametrize("rows,msg", [
    (["        11         5         4 1.0000000000000E+00", " 0.0000000000000E+00" * 5], "값"),
    (["        11         1         2 1.0000000000000E+00", " 1.0000000000000E+00" * 3], "초과"),
    (["        11         1         0 1.0000000000000E+00"], "NPG"),
    (["        11         1         1 0.0000000000000E+00", " 1.0000000000000E+00"], "THK"),
    (["        11         1         4 1.0000000000000E+00", " 1.0000000000000E+00" * 2,
      "        12         1         4 1.0000000000000E+00", " 1.0000000000000E+00" * 4], "헤더"),
])
def test_p3_target_record_format_errors(tmp_path, rows, msg):
    with pytest.raises(EslError) as ei:
        parse_rad(_sta_with(tmp_path, rows), "plate")
    assert ei.value.code == "STATE_PARSE_ERROR" and msg in ei.value.message
    assert "prev_0001.sta:" in ei.value.message                 # 파일:행


def test_p3_non_target_format_errors_are_ignored(tmp_path):
    rows = ["        99         5         4 1.0000000000000E+00", " garbage", "xx",
            "        11         1         4 1.0000000000000E+00", " 1.0000000000000E-02" * 4,
            "        98         1        -1 1.0000000000000E+00"]
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    assert m.state["epsp"].agg["max"][0] == pytest.approx(0.01)


def test_p3_duplicate_shellid_last_wins(tmp_path):
    rows = ["        11         1         1 1.0000000000000E+00", " 1.0000000000000E-02",
            "        11         1         1 1.0000000000000E+00", " 3.0000000000000E-02"]
    m = parse_rad(_sta_with(tmp_path, rows), "plate")
    assert m.state["epsp"].agg["max"][0] == pytest.approx(0.03)
    assert any(w.startswith("STATE_DUP_DEFINITION:") and "EPSP_F" in w for w in m.state["warnings"])


# ------------------------------------------------------------------ V-CI-P4 include 순서·중복·부분
@pytest.fixture(scope="module")
def small(tmp_path_factory):
    d = tmp_path_factory.mktemp("p4")
    nq = 4
    xs, ys = np.meshgrid(np.arange(nq + 1) * 10.0, np.arange(nq + 1) * 10.0, indexing="ij")
    X0 = np.c_[xs.ravel(), ys.ravel(), np.zeros(xs.size)]
    nid = 101 + np.arange(X0.shape[0])
    conn = []
    for i in range(nq):
        for j in range(nq):
            a = i * (nq + 1) + j
            conn.append([a, a + nq + 1, a + nq + 2, a + 1])
    conn = np.array(conn)
    cid = nid[conn]
    eid = 1001 + np.arange(conn.shape[0])
    et = np.full(eid.size, 4)
    X1 = X0 + np.c_[np.zeros(X0.shape[0]), np.zeros(X0.shape[0]), 0.01 * X0[:, 0]]
    t1 = 2.0 - 0.001 * np.arange(eid.size)
    synth_cum.write_str(d / "s_0001.str", nid, X1, eid, et, cid, t1, part_id=7, extra_tetra=False)
    orig = write_rad(d / "orig.rad", nid, X0, eid, et, cid, 7, "plate", 70, 2.0, 700, 2e5, 0.3)
    return {"d": d, "orig": orig, "X1": X1, "t1": t1, "nid": nid, "eid": eid, "et": et, "cid": cid}


def _variant(small, name, where, keep_orig):
    d = small["d"]
    txt = open(small["orig"]).read()
    if not keep_orig:
        out, skip = [], False
        for ln in txt.split("\n"):
            if ln.startswith("/"):
                skip = ln.startswith("/NODE") or ln.startswith("/SHELL/")
            if not skip:
                out.append(ln)
        txt = "\n".join(out)
    inc = "#include s_0001.str"
    if where == "before":
        txt = txt.replace("/NODE", inc + "\n/NODE", 1) if keep_orig else txt.replace("/MAT", inc + "\n/MAT", 1)
    else:
        txt = txt.replace("/END", inc + "\n/END")
    p = d / f"{name}.rad"
    p.write_text(txt)
    return p


@pytest.mark.parametrize("where", ["before", "after"])
@pytest.mark.parametrize("keep_orig", [True, False])
def test_p4_state_definitions_win_regardless_of_order(small, where, keep_orig):
    p = _variant(small, f"v_{where}_{keep_orig}", where, keep_orig)
    m = parse_rad(p, "plate")
    assert np.allclose(m.x0, small["X1"][np.argsort(small["nid"])], atol=0, rtol=1e-12)
    assert np.allclose(m.thickness, small["t1"]) and m.elem_id.tolist() == small["eid"].tolist()
    st = m.state
    dup = [w for w in st["warnings"] if w.startswith("STATE_DUP_DEFINITION")]
    if keep_orig:
        assert st["coord"]["n_dup"] == small["nid"].size and st["elems"]["n_dup"] == small["eid"].size
        assert dup and f"노드 {small['nid'].size}·요소 {small['eid'].size}개" in dup[0]
        # 원두께 t0 = /PROP/SHELL(2.0) → 감육 통계
        assert st["thickness"]["t0"] == 2.0 and st["thickness"]["n_changed"] == 0
    else:
        assert not dup and st["coord"]["n_dup"] == 0
    assert not any(w.startswith("STATE_PARTIAL") for w in st["warnings"])


def test_p4_partial_state_falls_back_to_rad(small):
    d = small["d"]
    half = small["eid"].size // 2
    synth_cum.write_str(d / "half_0001.str", small["nid"][:10], small["X1"][:10], small["eid"][:half],
                        small["et"][:half], small["cid"][:half], small["t1"][:half], part_id=7, extra_tetra=False)
    txt = open(small["orig"]).read().replace("/END", "#include half_0001.str\n/END")
    p = d / "partial.rad"
    p.write_text(txt)
    m = parse_rad(p, "plate")
    w = [x for x in m.state["warnings"] if x.startswith("STATE_PARTIAL")]
    assert w and f"요소 {small['eid'].size - half}/{small['eid'].size}" in w[0]
    assert m.state["elems"] == {"n_state": half, "n_rad": small["eid"].size - half, "n_dup": half, "n_dup_state": 0}
    assert np.allclose(m.thickness[:half], small["t1"][:half]) and np.all(m.thickness[half:] == 2.0)


def test_p4_rad_only_duplicates_still_error(small, tmp_path):
    txt = open(small["orig"]).read()
    i = txt.index("\n/SHELL/7\n")
    j = txt.index("\n/", i + 1)
    p = tmp_path / "dup.rad"
    p.write_text(txt[:j] + txt[i:j] + txt[j:])
    with pytest.raises(EslError) as ei:
        parse_rad(p, "plate")
    assert ei.value.code == "RAD_PARSE_ERROR" and "중복 요소" in ei.value.message


def test_state_include_missing_code(small, tmp_path):
    shutil.copy(small["orig"], tmp_path / "o.rad")
    p = tmp_path / "o.rad"
    p.write_text(p.read_text().replace("/END", "#include ../prev/Run1_0002.sta\n/END"))
    with pytest.raises(EslError) as ei:
        parse_rad(p, "plate")
    assert ei.value.code == "STATE_INCLUDE_MISSING" and "Run1_0002.sta" in ei.value.message


# ------------------------------------------------------------------ V-CI-P6 /BEGIN
def test_p6_begin_compare():
    num = _st.begin_values(["r", "2024 0", " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00",
                            " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00"])
    num2 = _st.begin_values(["r", "2024 0", " 1.0000000000000E+00 1.0000000000000E+00 1.0000000000000E+00",
                             " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00"])
    txt = _st.begin_values(["r", "2024 0", "                  Mg                  mm                   s"])
    assert num["numeric"] and not txt["numeric"]
    assert _st.compare_begin(num, num) ["same"] is True
    assert _st.compare_begin(num, num2)["same"] is False
    assert _st.compare_begin(txt, num)["compared"] is False


def test_p6_unit_mismatch_warning(tmp_path):
    shutil.copytree(ISSUE, tmp_path / "i")
    s = tmp_path / "i" / "10_Edge_Drop_Scene07_Edge23_1st_0002.str"
    t = s.read_text().split("\n")
    t[4] = " 1.0000000000000E+00 1.0000000000000E+00 1.0000000000000E+00"
    s.write_text("\n".join(t))
    m = parse_rad(tmp_path / "i" / "Scene07_Edge23_2nd_0000.rad", "Chassis_Rear")
    assert any(w.startswith("STATE_UNIT_MISMATCH") for w in m.state["warnings"])
