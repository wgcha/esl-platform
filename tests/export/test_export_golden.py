"""T-EXP-1: 소형 메시 inc·fem 골든(수작업 기대값), ID 배정·범위 충돌."""
import os
from types import SimpleNamespace

import numpy as np
import pytest

from esl.errors import EslError
from esl.export import all_ids, dof_flags, force_mask, plan_ids
from esl.export import csvout, optistruct, radioss

OFF = 1_000_000
NF = "{:.6E}"
MAX_IDS = {"node": 16, "elem": 103, "part": 1, "prop": 5, "mat": 9, "func": 3, "grnod": 0, "load": 0, "bcs": 0}


@pytest.fixture
def small():
    model = SimpleNamespace(
        node_id=np.array([11, 12, 13, 14, 15, 16]),
        x0=np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], float),
        elem_id=np.array([101, 102, 103]),
        elem_type=np.array([4, 4, 3], np.int8),
        conn=np.array([[0, 1, 4, 3], [1, 2, 5, 4], [2, 5, 4, -1]]),
        elem_pid=np.array([5, 5, 5]),
        thickness=np.array([1.0, 1.5, 1.0]),
        mats=[{"id": 9, "E": 70000.0, "nu": 0.33}],
    )
    F = np.array([[10.0, 0.0, 0.0],
                  [0.0, -5.0, 2.5],
                  [0.0, 0.0, 0.0],
                  [1e-12, 3.0, 0.0],      # 1e-12 < 1e-9·max|F| → 생략
                  [-10.0, 2.0, -2.5],
                  [0.0, 0.0, 0.0]])
    sup = [(11, "123"), (13, "13"), (16, "3")]
    return model, F, sup


def _plan(model, F, sup, tol=1e-9):
    mask = force_mask(F, tol)
    groups, _ = optistruct.pshell_groups(model.elem_pid, model.thickness)
    return mask, plan_ids(OFF, MAX_IDS, len(sup), len(groups), int(mask.any(axis=1).sum()), int(mask.sum()))


def test_plan_ids_sequential(small):
    model, F, sup = small
    mask, plan = _plan(model, F, sup)
    assert mask.sum() == 7 and mask.any(axis=1).sum() == 4
    assert plan["func"] == OFF + 1 and plan["fem_spc_sid"] == OFF + 2 and plan["fem_load_sid"] == OFF + 3
    assert plan["bcs_grnod"] == [OFF + 4, OFF + 5, OFF + 6] and plan["bcs"] == [OFF + 7, OFF + 8, OFF + 9]
    assert plan["pshell"] == [OFF + 10, OFF + 11]
    assert plan["cload_grnod"] == list(range(OFF + 12, OFF + 16))
    assert plan["cload"] == list(range(OFF + 16, OFF + 23))
    ids = all_ids(plan)
    assert len(set(ids)) == len(ids) and all(OFF < v <= OFF + 22 for v in ids) and plan['range'] == [OFF + 1, OFF + 22]


def test_id_range_collision():
    for key in ("func", "grnod", "load", "bcs", "prop"):
        with pytest.raises(EslError) as ei:
            plan_ids(OFF, {**MAX_IDS, key: OFF + 5}, 3, 1, 1, 1)
        assert ei.value.code == "ID_RANGE_COLLISION"
        assert f"[{OFF + 1}, {OFF + 3 + 6 + 1 + 2}]" in ei.value.message and str(OFF + 5) in ei.value.message
    # 생성하지 않는 종류(노드·요소)는 무관
    plan_ids(OFF, {**MAX_IDS, "node": 5 * OFF, "elem": 5 * OFF}, 3, 1, 1, 1)


def test_plan_ids_no_fixed_width_issue24():
    """이슈 #24: 하중 노드 277608, 성분 832823, 지지 3, PSHELL 1 → 1,110,441 ID 가 폭 제한 없이 배정."""
    plan = plan_ids(OFF, MAX_IDS, 3, 1, 277_608, 832_823)
    assert plan["n_ids"] == 1_110_441 and plan["range"] == [OFF + 1, OFF + 1_110_441]
    ids = all_ids(plan)
    assert len(ids) == len(set(ids)) == 1_110_441 and min(ids) == OFF + 1 and max(ids) == OFF + 1_110_441
    assert plan["cload_grnod"][0] == OFF + 11 and plan["cload"][-1] == OFF + 1_110_441


def test_plan_ids_auto():
    p = plan_ids("auto", MAX_IDS, 3, 1, 1, 1)
    assert p["id_offset"] == 9_000_000 and p["id_offset_auto"] and p["func"] == 9_000_001
    # 모델 ID 가 기본 시작점 이상 → 최대 ID 위 10의 거듭제곱으로
    p = plan_ids("auto", {**MAX_IDS, "grnod": 9_500_000}, 3, 1, 1, 1)
    assert p["id_offset"] == 10_000_000 and p["func"] == 10_000_001
    p = plan_ids("auto", {**MAX_IDS, "load": 12_345_678}, 3, 1, 1, 1)
    assert p["id_offset"] == 100_000_000
    # node·elem 이 커도 생성 종류가 아니므로 무관
    assert plan_ids("auto", {**MAX_IDS, "node": 99_999_999}, 3, 1, 1, 1)["id_offset"] == 9_000_000
    with pytest.raises(EslError) as ei:               # 올린 시작점이 상한을 넘기면 오류
        plan_ids("auto", {**MAX_IDS, "bcs": 1_500_000_000}, 3, 1, 600_000_000, 900_000_000)
    assert ei.value.code == "ID_RANGE_COLLISION" and "2147483647" in ei.value.message


def test_plan_ids_limit():
    with pytest.raises(EslError) as ei:
        plan_ids(2_147_000_000, MAX_IDS, 3, 1, 400_000, 600_000)
    assert ei.value.code == "ID_RANGE_COLLISION" and "상한" in ei.value.message
    need = 3 + 6 + 1 + 1 + 1
    assert plan_ids(2_147_483_647 - need, MAX_IDS, 3, 1, 1, 1)["max_used"] == 2_147_483_647     # 딱 맞게
    with pytest.raises(EslError):
        plan_ids(2_147_483_647 - need + 1, MAX_IDS, 3, 1, 1, 1)


def test_dof_flags():
    assert [dof_flags(d) for d in ("123", "12", "13", "23", "1", "2", "3")] == \
           ["111", "110", "101", "011", "100", "010", "001"]


def _cards(path, kw):
    """카드 kw 의 (헤더, title, 데이터 행들) 목록(주석 제외)."""
    lines = [ln.rstrip("\n") for ln in open(path, encoding="utf-8")]
    out, cur = [], None
    for ln in lines:
        if ln.startswith("/"):
            cur = [ln] if ln.startswith(kw) else None
            if cur is not None:
                out.append(cur)
        elif cur is not None and not ln.startswith("#"):
            cur.append(ln)
    return out


def test_cload_inc_golden(small, tmp_path):
    model, F, sup = small
    mask, plan = _plan(model, F, sup)
    p = str(tmp_path / "esl_cload.inc")
    r = radioss.write_cload_inc(p, model.node_id, F, mask, plan, "ramp", 1e-3, NF, ["hdr"])
    assert r == {"n_cload": 7, "n_grnod": 4}
    fun = _cards(p, "/FUNCT/")
    assert fun == [[f"/FUNCT/{OFF + 1}", "ESL_ramp",
                    "        0.000000E+00        0.000000E+00",
                    "        1.000000E-03        1.000000E+00",
                    "        1.000000E+30        1.000000E+00"]]
    gr = _cards(p, "/GRNOD/NODE/")
    assert [g[0] for g in gr] == [f"/GRNOD/NODE/{OFF + k}" for k in range(12, 16)]
    assert [g[2] for g in gr] == ["        11", "        12", "        14", "        15"]
    cl = _cards(p, "/CLOAD/")
    assert len(cl) == 7                                   # = 비영 성분 수
    f1 = f"{OFF + 1:>10d}"
    expect = [
        (OFF + 16, "ESL_N11_FX", "X", OFF + 12, "1.000000E+01"),
        (OFF + 17, "ESL_N12_FY", "Y", OFF + 13, "-5.000000E+00"),
        (OFF + 18, "ESL_N12_FZ", "Z", OFF + 13, "2.500000E+00"),
        (OFF + 19, "ESL_N14_FY", "Y", OFF + 14, "3.000000E+00"),
        (OFF + 20, "ESL_N15_FX", "X", OFF + 15, "-1.000000E+01"),
        (OFF + 21, "ESL_N15_FY", "Y", OFF + 15, "2.000000E+00"),
        (OFF + 22, "ESL_N15_FZ", "Z", OFF + 15, "-2.500000E+00"),
    ]
    for card, (lid, title, d, gid, val) in zip(cl, expect):
        row = f1 + f"{d:>10}" + f"{0:>10d}" * 2 + f"{gid:>10d}" + f"{'1.000000E+00':>20}" + f"{val:>20}"
        assert card == [f"/CLOAD/{lid}", title, row]
        assert len(row) == 90
    # constant 함수
    radioss.write_cload_inc(p, model.node_id, F, mask, plan, "constant", 1e-3, NF, [])
    assert _cards(p, "/FUNCT/")[0][2:] == ["        0.000000E+00        1.000000E+00",
                                           "        1.000000E+30        1.000000E+00"]


def test_bcs_inc_golden(small, tmp_path):
    model, F, sup = small
    _, plan = _plan(model, F, sup)
    p = str(tmp_path / "esl_bcs.inc")
    radioss.write_bcs_inc(p, sup, plan, ["hdr"])
    assert _cards(p, "/GRNOD/NODE/") == [
        [f"/GRNOD/NODE/{OFF + 4}", "ESL_321_N11", "        11"],
        [f"/GRNOD/NODE/{OFF + 5}", "ESL_321_N13", "        13"],
        [f"/GRNOD/NODE/{OFF + 6}", "ESL_321_N16", "        16"],
    ]
    assert _cards(p, "/BCS/") == [
        [f"/BCS/{OFF + 7}", "ESL_321_N11_DOF123", f"   111 000         0{OFF + 4:>10d}"],
        [f"/BCS/{OFF + 8}", "ESL_321_N13_DOF13", f"   101 000         0{OFF + 5:>10d}"],
        [f"/BCS/{OFF + 9}", "ESL_321_N16_DOF3", f"   001 000         0{OFF + 6:>10d}"],
    ]


def test_force_fem_golden(small, tmp_path):
    model, F, sup = small
    mask, plan = _plan(model, F, sup)
    p = str(tmp_path / "esl_force.fem")
    r = optistruct.write_force_fem(p, model, F, mask, sup, plan, NF, ["hdr"])
    assert r["n_pshell"] == 2 and r["n_force"] == 4 and r["n_spc1"] == 3
    L = [ln.rstrip("\n") for ln in open(p, encoding="utf-8") if not ln.startswith("$")]
    S, LD = OFF + 2, OFF + 3
    P1, P2 = OFF + 10, OFF + 11
    e = NF.format
    assert L == [
        "SUBCASE 1", "  LABEL ESL_FORCE", f"  SPC = {S}", f"  LOAD = {LD}",
        "  DISPLACEMENT(H3D,PUNCH) = ALL", "  SPCFORCE(H3D,PUNCH) = ALL", "  STRAIN(H3D) = ALL",
        "BEGIN BULK",
        *[f"GRID,{n},,{e(x)},{e(y)},{e(z)}" for n, (x, y, z) in zip(model.node_id, model.x0)],
        f"CQUAD4,101,{P1},11,12,15,14",
        f"CQUAD4,102,{P2},12,13,16,15",
        f"CTRIA3,103,{P1},13,16,15",
        f"PSHELL,{P1},9,1.000000E+00,9,,9",
        f"PSHELL,{P2},9,1.500000E+00,9,,9",
        "MAT1,9,7.000000E+04,,3.300000E-01",
        f"FORCE,{LD},11,0,1.000000E+00,1.000000E+01,0.000000E+00,0.000000E+00",
        f"FORCE,{LD},12,0,1.000000E+00,0.000000E+00,-5.000000E+00,2.500000E+00",
        f"FORCE,{LD},14,0,1.000000E+00,0.000000E+00,3.000000E+00,0.000000E+00",
        f"FORCE,{LD},15,0,1.000000E+00,-1.000000E+01,2.000000E+00,-2.500000E+00",
        f"SPC1,{S},123,11",
        f"SPC1,{S},13,13",
        f"SPC1,{S},3,16",
        "ENDDATA",
    ]


def test_pshell_split_by_pid_and_thickness():
    groups, inv = optistruct.pshell_groups([5, 5, 6, 5], [1.0, 2.0, 1.0, 1.0])
    assert groups == [(5, 1.0), (5, 2.0), (6, 1.0)] and inv.tolist() == [0, 1, 2, 0]


def test_csv_writer(tmp_path):
    fmt = csvout.CsvFormat(";", "{:.3E}")
    p = str(tmp_path / "a.csv")
    csvout.write_csv(p, ("a", "b", "c", "d"), [(1, 2.5, True, "x;y"), (np.int64(3), np.float32(1), False, None)], fmt)
    raw = open(p, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode() == 'a;b;c;d\n1;2.500E+00;1;"x;y"\n3;1.000E+00;0;\n'


def test_f20_overflow_rejected():
    with pytest.raises(EslError) as ei:
        radioss.f20(1.0, "{:.20E}")
    assert ei.value.code == "CONFIG_INVALID"
    with pytest.raises(EslError) as ei:
        radioss.i10(10 ** 10)
    assert ei.value.code == "ID_RANGE_COLLISION" and "I10" in ei.value.message


def test_outputs_ascii_only_with_non_ascii_header(small, tmp_path):
    """inc·fem 은 ASCII 전용: 한글·기호가 섞인 헤더(파트 title 등)도 치환되어 기록."""
    model, F, sup = small
    mask, plan = _plan(model, F, sup)
    hdr = ["part 7 '차체 후방'", "|F_c| > 1e-9·max|F| — t*", ""]
    paths = [str(tmp_path / n) for n in ("a.inc", "b.inc", "c.fem")]
    radioss.write_cload_inc(paths[0], model.node_id, F, mask, plan, "ramp", 1e-3, NF, hdr)
    radioss.write_bcs_inc(paths[1], sup, plan, hdr)
    optistruct.write_force_fem(paths[2], model, F, mask, sup, plan, NF, hdr)
    for p in paths:
        raw = open(p, "rb").read()
        assert all(b < 128 for b in raw), p
        assert b"\\ucc28" in raw          # '차' → \ucc28 (정보 보존)


def test_node_id_too_wide_is_esl_error(small, tmp_path):
    model, F, sup = small
    mask, plan = _plan(model, F, sup)
    big = model.node_id.copy()
    big[0] = 12_345_678_901
    with pytest.raises(EslError) as ei:
        radioss.write_cload_inc(str(tmp_path / "x.inc"), big, F, mask, plan, "ramp", 1e-3, NF, [])
    assert ei.value.code == "ID_RANGE_COLLISION" and "12345678901" in ei.value.message
    with pytest.raises(EslError) as ei:
        radioss.write_bcs_inc(str(tmp_path / "y.inc"), [(12_345_678_901, "123")] + sup[1:], plan, [])
    assert ei.value.code == "ID_RANGE_COLLISION"
