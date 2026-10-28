"""V-OR-13: 후처리 — 가짜 shape.csv → bead.npz·csv·PNG(결정적 바이트)·bead_mesh.rad 재파싱(좌표·ID)·.fem,
c0_tol 경고, 노드 불일치 BEAD_POST_FAILED, .out 해석·history.csv, OptResult 조립, bead_post TCL 실패 경로."""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.opt import BEAD_POST_TCL, femread, keepout as ko, osout, png, post, settings
from esl.opt import select as sl
from esl.opt import target as tg
from esl.rad import parse_rad

CFG = settings()


@pytest.fixture()
def run(tmp_path):
    m = so.plate(20, 12, Lx=300, Lz=180, holes=[(8, 10, 5, 7)], n_tria_cols=2)
    sup = so.supports_321(m)
    from esl.library import normalize as nz
    t = tg.Target("S1", m, nz.frame(m["x0"], None, m["conn"], m["elem_type"]), sup,
                  source={"part_id": 7, "part_title": "chassis_rear", "rho": 7.85e-9})
    kres = ko.compute(m, t.frame, {"rects": [{"name": "PCB", "corner": "a1b1", "x_mm": 10.0, "y_mm": 10.0,
                                              "w_mm": 60.0, "h_mm": 40.0}]}, CFG["keepout"])
    des, _ = tg.design_mask(t, [], kres["mask"])
    # 가짜 Shape Change: 법선(-Y) 방향 비드 높이 = 10·sin, 금지 영역 노드는 0
    X = m["x0"]
    h = 10.0 * np.clip(np.sin(np.pi * X[:, 0] / 75.0), 0, 1)
    n = np.asarray(t.frame["n"])
    shape = h[:, None] * n[None, :]
    p = tmp_path / "shape.csv"
    rows = ["node_id,dx,dy,dz"] + [f"{int(i)},{d[0]!r},{d[1]!r},{d[2]!r}" for i, d in
                                   zip(m["node_id"][::-1], shape[::-1].tolist())]       # 순서 섞임
    p.write_text("\n".join(rows) + "\n")
    return t, kres, des, shape, str(p)


def test_outputs(tmp_path, run):
    t, kres, des, shape, p = run
    sh = post.read_shape_csv(p, t.mesh["node_id"])
    assert np.allclose(sh, shape)
    out = tmp_path / "post"
    s = post.write_outputs(str(out), t, sh, design=des, keepout_reason=kres["reason"], rects=kres["rects"],
                           bead=CFG["bead_defaults"], post_cfg=CFG["post"])
    assert sorted(os.listdir(out)) == sorted(s["files"])
    z = np.load(out / "bead.npz")
    assert np.allclose(z["h"], np.sum(shape * post.node_normals(t.mesh), axis=1))
    hin = np.linalg.norm(shape, axis=1)
    assert z["h"].max() == pytest.approx(hin.max(), rel=1e-9) and s["height_max"] == pytest.approx(hin.max(), rel=1e-9)
    assert np.array_equal(z["design"], des) and np.array_equal(z["keepout_reason"], kres["reason"])
    assert 0 < s["area_frac"] < 1
    lines = (out / "bead_nodes.csv").read_text().splitlines()
    assert lines[0] == "node_id,x0,y0,z0,h,dx,dy,dz" and len(lines) == t.n_nodes + 1
    b1 = (out / "bead_map.png").read_bytes()
    assert png.decode_png_size(b1) == tuple(CFG["post"]["png_px"])
    out2 = tmp_path / "post2"
    post.write_outputs(str(out2), t, sh, design=des, keepout_reason=kres["reason"], rects=kres["rects"],
                       bead=CFG["bead_defaults"], post_cfg=CFG["post"])
    assert (out2 / "bead_map.png").read_bytes() == b1                       # 결정적 바이트
    rm = parse_rad(str(out / "bead_mesh.rad"), "chassis_rear")
    assert np.array_equal(rm.node_id, t.mesh["node_id"]) and np.array_equal(rm.elem_id, t.mesh["elem_id"])
    assert np.allclose(rm.x0, t.mesh["x0"] + shape, atol=1e-9)
    fm = femread.read_fem(str(out / "bead_mesh.fem"))
    assert np.array_equal(fm["elem_id"], t.mesh["elem_id"]) and np.allclose(fm["x0"], t.mesh["x0"] + shape, rtol=1e-8)
    kp = post.write_keepout_png(str(tmp_path / "keepout.png"), t, kres, des, (800, 450))
    assert png.decode_png_size(open(kp, "rb").read()) == (800, 450)


def test_shape_csv_mismatch(tmp_path, run):
    t, _, _, _, p = run
    lines = open(p).read().splitlines()
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(EslError) as ei:
        post.read_shape_csv(str(bad), t.mesh["node_id"])
    assert ei.value.code == "BEAD_POST_FAILED"
    with pytest.raises(EslError) as ei:
        post.read_shape_csv(str(tmp_path / "none.csv"), t.mesh["node_id"])
    assert ei.value.code == "BEAD_POST_FAILED"
    bad.write_text("node_id,dx\n1,2\n")
    with pytest.raises(EslError):
        post.read_shape_csv(str(bad), t.mesh["node_id"])


OUT = """
 OptiStruct 2026.1
ITERATION    0
 Objective Function (Minimize MINMAX)      =  1.00000E+00
 |     1  |COMP     |COMPLIAN|       |        |       1 |  3.06000E+04 |
 |     1  |COMP     |COMPLIAN|       |        |       2 |  1.25000E+04 |
ITERATION    1
 Objective Function (Minimize MINMAX)      =  8.00000E-01
 |     1  |COMP     |COMPLIAN|       |        |       1 |  2.40000E+04 |
 |     1  |COMP     |COMPLIAN|       |        |       2 |  1.00000E+04 |
 OPTIMIZATION HAS CONVERGED.
"""


def _sel():
    cands = [{"entry_id": "Ea", "C0": 3.0e4, "umax": 1.0, "mode": None}, {"entry_id": "Eb", "C0": 1.25e4, "umax": 1.0,
                                                                          "mode": None}]
    return sl.select(cands, "A", loads_cfg=CFG["loads"], U=np.eye(2), u_rows={"Ea": 0, "Eb": 1})


def test_osout_history_and_c0_tol():
    sc = CFG["solve"]
    p = osout.parse_out(OUT, sc)
    assert p["last_iteration"] == 1 and p["converged"] and p["objective"] == [(0, 1.0), (1, 0.8)]
    assert p["compliance"][1] == {1: 2.4e4, 2: 1.0e4}
    sel = _sel()
    rows = osout.history(p, sel)
    assert rows[1]["objective"] == pytest.approx(0.8) and rows[0]["ratio_L01"] == pytest.approx(1.02)
    csvt = osout.history_csv(rows, sel)
    assert csvt.splitlines()[0] == "iteration,objective,C_L01,C_L02,ratio_L01,ratio_L02"
    subs, warns = osout.subcase_summary(p, sel, CFG["loads"]["c0_tol"])
    assert len(warns) == 0 and subs[0]["C0_os"] == 3.06e4 and subs[0]["ratio"] == pytest.approx(2.4e4 / 3.06e4)
    subs, warns = osout.subcase_summary(p, sel, 0.01)
    assert len(warns) == 1 and "L01" in warns[0]
    res = post.assemble_result(selection=sel, parsed=p, desmax=30, subcases=subs, keepout_counts={},
                               n_design_elems=10, bead_summary={"height_max": 10.0, "area_frac": 0.3},
                               normals={"mode": "kept", "normals_opposite": 0}, solve_meta={"seconds": 1.5},
                               warnings=warns)
    assert res["converged"] and res["objective"]["history"] == pytest.approx([1.02, 0.8]) and res["iterations"] == 1
    assert res["load_selection"]["C_ref"] == 3.0e4 and "normals_opposite" in res
    json.dumps(res)


def test_osout_classify():
    sc = CFG["solve"]
    assert osout.classify(0, OUT, sc, True) is None
    assert osout.classify(0, OUT, sc, False) == "OS_SOLVE_FAILED"
    assert osout.classify(3, "*** ERROR # 1 license checkout failed", sc) == "OS_LICENSE_UNAVAILABLE"
    assert osout.classify(1, "ALM_LICENSE_ERROR: none", sc) == "OS_LICENSE_UNAVAILABLE"
    assert osout.classify(1, " *** ERROR # 5000 bad card DTPG", sc) == "OS_SOLVE_FAILED"
    assert osout.classify(1, "insufficient memory for solver", sc) == "SOLVER_OUT_OF_MEMORY"
    with pytest.raises(EslError) as ei:
        osout.require_ok(1, "*** ERROR # 12 bad", sc, True)
    assert ei.value.code == "OS_SOLVE_FAILED" and "bad" in ei.value.message


TCLSH = shutil.which("tclsh") or shutil.which("tclsh8.6")


@pytest.mark.skipif(TCLSH is None, reason="tclsh 없음")
def test_bead_post_tcl_failure_path(tmp_path):
    """HyperView 없이 tclsh 로 실행 → hwi 없음 → done.json ok:false BEAD_POST_FAILED (문법·실패 기록 흐름)."""
    h3d = tmp_path / "esl_bead_des.h3d"
    h3d.write_bytes(b"x")
    out = tmp_path / "post"
    r = subprocess.run([TCLSH, BEAD_POST_TCL, "-input", str(h3d), "-output", str(out)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 1
    d = json.loads((out / "done.json").read_text())
    assert d["ok"] is False and d["code"] == "BEAD_POST_FAILED" and d["failed_step"]
    r = subprocess.run([TCLSH, BEAD_POST_TCL, "-input", str(tmp_path / "none.h3d"), "-output", str(out)],
                       capture_output=True, text=True, timeout=60)
    d = json.loads((out / "done.json").read_text())
    assert d["ok"] is False and "not found" in d["error"]
    assert (out / "_backup").is_dir()                                       # 이전 done.json 백업(삭제 없음)
