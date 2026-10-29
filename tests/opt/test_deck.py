"""V-OR-10·21(코어): OPT_RUN 덱 — server 없으면 기존 골든 불변, OPT_RUN 덱 골든(subcase L01…(C 내림차순),
목표 기준별 DOBJREF POS, 헤더 objective_norm·C_ref, 금지 영역 요소 비설계 PSHELL·DTPG 제외, DOPTPRM·OUTPUT, 비드 45°·60·10)."""
import os
import re
import sys

import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.library import optdeck as od
from esl.opt import keepout as ko
from esl.opt import select as sl
from esl.opt import settings
from esl.opt import target as tg

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden")
UPDATE = os.environ.get("ESL_UPDATE_GOLDEN") == "1"
LIB_GOLDEN = os.path.join(os.path.dirname(HERE), "library", "golden")
CFG = settings()


def test_no_server_matches_library_golden(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "library"))
    try:
        import test_optdeck as t0
    finally:
        sys.path.pop(0)
    od.write(t0.small_mesh(), t0.load_cases(), t0.SUP, t0.DESIGN, str(tmp_path))
    for n in ("esl_bead.fem", "esl_loads.inc"):
        got = open(os.path.join(tmp_path, n), encoding="ascii").read()
        assert got == open(os.path.join(LIB_GOLDEN, f"optdeck_small_{n}"), encoding="ascii").read()
    assert "DOPTPRM" not in got and "OUTPUT" not in open(os.path.join(tmp_path, "esl_bead.fem")).read()


def _case(norm, synthetic=True):
    m = so.plate(6, 4, Lx=60, Lz=40, pid=10)
    m["elem_pid"][:4] = 11                                     # 비설계 PID 후보
    sup = so.supports_321(m)
    t = tg.Target("S1", m, ko_frame(m), sup)
    if synthetic:   # 골든용: 수치 해 없이 정확한 값(플랫폼 간 바이트 동일)
        N = m["node_id"].size
        forces = {}
        for k, e in enumerate(("Ea", "Eb", "Ec")):
            f = np.zeros((N, 3))
            f[k, 1], f[N - 1 - k, 1] = 2.5 * (k + 1), -2.5 * (k + 1)
            forces[e] = f
        cands = [{"entry_id": e, "C0": c, "umax": 0.5, "mode": None, "scene": e}
                 for e, c in (("Ea", 1.25e4), ("Eb", 3.0e4), ("Ec", 7.5e3))]
        sel = sl.select(cands, "A", loads_cfg=CFG["loads"], objective_norm=norm, U=np.eye(3, 12),
                        u_rows={"Ea": 0, "Eb": 1, "Ec": 2})
    else:
        loads = {"Ea": so.load(m, "bend", amp=1.0), "Eb": so.load(m, "twist", amp=10.0),
                 "Ec": so.load(m, "rand", seed=1)}
        cands = [{"entry_id": e, "mode": None, "scene": e} for e in sorted(loads)]
        sel, forces, _ = sl.run(t, cands, loads.__getitem__, strategy="A", objective_norm=norm, k=None, cfg=so.cfg())
    kres = ko.compute(m, t.frame, {"rects": [{"name": "PCB", "corner": "a0b0", "x_mm": 30.0, "y_mm": 0.0,
                                              "w_mm": 12.0, "h_mm": 12.0}], "auto": {"hole": False, "edge": False}},
                      CFG["keepout"])
    des, _ = tg.design_mask(t, [11], kres["mask"])
    design = tg.deck_design(t, design=des, bead=CFG["bead_defaults"], run_id=42, desmax=CFG["solve"]["desmax"],
                            selection=sel, optdeck_cfg={"id_offset": 9000, "num_format": "{:.6E}"})
    return t, sel, forces, des, kres, design


def ko_frame(m):
    from esl.library import normalize as nz
    return nz.frame(m["x0"], None, m["conn"], m["elem_type"])


def _num(s):
    return float(s)


@pytest.mark.parametrize("norm,synthetic", [("abs", True), ("rel", True), ("abs", False), ("rel", False)])
def test_opt_run_deck(tmp_path, norm, synthetic):
    t, sel, forces, des, kres, design = _case(norm, synthetic)
    lcs = tg.deck_load_cases(sel, forces)
    s = od.write(t.mesh, lcs, t.supports, design, str(tmp_path))
    fem = open(os.path.join(tmp_path, "esl_bead.fem"), encoding="ascii").read()
    # 골든(abs 만 — rel 은 POS 만 다름)
    if norm == "abs" and synthetic:
        gp = os.path.join(GOLDEN, "opt_run_esl_bead.fem")
        if UPDATE:
            os.makedirs(GOLDEN, exist_ok=True)
            open(gp, "w", encoding="ascii", newline="\n").write(fem)
        assert fem == open(gp, encoding="ascii").read()
    # subcase 라벨 L01… = C 내림차순
    labels = re.findall(r"^\s*LABEL (\S+)", fem, re.M)
    sel_rows = sorted((r for r in sel["rows"] if r["label"]), key=lambda r: r["label"])
    assert labels == [r["label"] for r in sel_rows] == [f"L{k:02d}" for k in range(1, len(sel_rows) + 1)]
    Cs = [r["C0"] for r in sel_rows]
    assert Cs == sorted(Cs, reverse=True)
    # DOBJREF POS
    pos = [_num(ln.split(",")[4]) for ln in fem.splitlines() if ln.startswith("DOBJREF")]
    if norm == "abs":
        assert len(set(pos)) == 1 and pos[0] == pytest.approx(max(Cs), rel=1e-8) and sel["C_ref"] == max(Cs)
    else:
        assert pos == pytest.approx(Cs, rel=1e-8)
    assert f"$ objective_norm {norm} C_ref " in fem and "$ load_strategy A" in fem and "$ opt_run 42 S1" in fem
    # 서버 카드
    assert "OUTPUT,H3D,ALL" in fem.split("BEGIN BULK")[0] and "DOPTPRM,DESMAX,30" in fem.split("BEGIN BULK")[1]
    assert "DESOBJ(MINMAX)" in fem
    # 비드 45°·60·10
    # 공식 DTPG 비드 줄: MW ANG BF HGT NORM YD ZD SKIP (플래그 없음) — 이슈 #35 "+,BEAD,60.,45.,10.,YES,BC" 회귀
    lines = fem.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("DTPG,"))
    assert lines[k + 1] == "+,60.,45.,YES,10.,NORM,,,BC" and ",BEAD," not in fem
    assert re.search(r"^\+,+BOUNDS,0\.,1\.", fem, re.M)
    # 비설계 = PID 11 ∪ 금지 영역 사각형 → DTPG 목록에서 제외
    pm = {p["pid"]: p for p in s["pshell_map"]}
    nd_pids = {p for p, v in pm.items() if not v["design"]}
    assert s["n_nondesign_elems"] == int((~des).sum()) and s["nondesign_reasons"]["by_elems"] > 0
    eid = t.mesh["elem_id"]
    elem_pshell = {int(ln.split(",")[1]): int(ln.split(",")[2]) for ln in fem.splitlines()
                   if ln.startswith(("CQUAD4", "CTRIA3"))}
    for e, d in zip(eid.tolist(), des.tolist()):
        assert (elem_pshell[e] in nd_pids) is (not d)
    dtpg = fem.split("DTPG,")[1].split("\n")[0]
    for p in nd_pids:
        assert f",{p}" not in dtpg
    assert kres["counts"]["n_elems_rects"] > 0


def test_server_requires_desmax(tmp_path):
    t, sel, forces, des, kres, design = _case("abs")
    design["server"]["desmax"] = 0
    with pytest.raises(EslError):
        od.write(t.mesh, tg.deck_load_cases(sel, forces), t.supports, design, str(tmp_path))
    design["server"]["desmax"] = 5
    design["nondesign_elem_ids"] = [999999]
    with pytest.raises(EslError):
        od.write(t.mesh, tg.deck_load_cases(sel, forces), t.supports, design, str(tmp_path))


def test_deck_load_cases_missing_force():
    _, sel, forces, *_ = _case("abs", synthetic=False)
    with pytest.raises(EslError):
        tg.deck_load_cases(sel, {})
    lc = tg.deck_load_cases(sel, forces)
    assert [x["ref"] for x in lc] == [r["pos"] for r in sorted((r for r in sel["rows"] if r["label"]),
                                                                 key=lambda r: r["label"])]
    assert all(np.asarray(x["f"]).shape == (forces[x["entry_id"]].shape) for x in lc)
