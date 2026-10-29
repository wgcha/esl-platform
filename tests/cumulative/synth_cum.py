"""누적 낙하 씬 합성 사례(V-CI-E1·E2·W1·S*): 1차 런 변형 형상·두께·EPSP 를 상태 파일(.str/.sta)로 쓰고,
2차 런(상태 형상 기준 변위 + raw 변형률) TCL 출력 CSV 를 만든다.

- 1차 런: 판 X0 에 하중 → 작은 변형 X1 = X0 + d1(max 0.4 mm — 원 rad 와 비교해도 좌표 검사 통과),
  두께 t1 = t0·(1 − 0.03·w) (최대 3 % 감육), EPSP(IPT,IPG) = p(e)·(1 + 0.1·(IPT−3)) (IPG 무관 → mid_mean = p).
  p 는 매끈한 장 + 패턴 2 부근 요소 하나(E_BIG)에 큰 값 PREV_BIG.
- 2차 런: ShellModel(X1, t1) 로 패턴 1(전역, 피크 frame 6)·패턴 2(국부, 피크 frame 3) 변형, 강체 운동 합성.
  Max_Strain = 증분(이번 낙하) max-hold, Plastic Strain h3d = 이전 + 증분(INISHE 로 초기화된 누적값),
  frame0.csv(F0 패스 흉내): vm_hv = 0, epsp = 이전값.
- 기대: 누적 순위 1위 = E_BIG(이전 + 이번), first-reach = 증분 계열 → t* = frame 3 (비누적 규칙이면 6).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))

import synth_case  # noqa: E402
from esl.io import max_hold, write_results_csv  # noqa: E402
from esl.mech import kabsch, strain, supports  # noqa: E402
from esl.mech.shell import ShellModel  # noqa: E402
from esl.rad import write_rad  # noqa: E402
from esl.rad import writer as _w  # noqa: E402

RUN1 = "Plate_Drop_1st"
PART_ID, PART_TITLE, PID, MID = 7, "Chassis  REAR", 70, 700
E_MOD, NU, T0 = 2.1e5, 0.3, 2.0
PREV_BIG = 0.08
EQ_MAX = 2.0e-3            # 2차 런 패턴 1 최대 ε_eq
NPT, NPG = 5, 4
COMMENT7 = [
    "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
    "/INISHE/EPSP_F",
    "#------------------------ REPEAT --------------------------",
    "#  SHELLID, NPT, NPG, THK",
    "# REPEAT IPT=1,MAX(1,NPT) : REPEAT IPG=1,NPG : EPSP(IPG,IPT)",
    "#---------------------- END REPEAT ------------------------",
    "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|----10---|",
]
BEGIN_NUM = ["/BEGIN", RUN1, "      2024         0",
             " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00",
             " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00"]


def f20(v: float) -> str:
    return f"{v:20.13E}"


def write_str(path, node_id, X1, elem_id, et, conn_ids, thk1, part_id=PART_ID, extra_tetra=True):
    L = [f"#RADIOSS STATE FILE {RUN1}_0002.sta"] + BEGIN_NUM
    q = et == 4
    for kw, sel in (("SHELL", q), ("SH3N", ~q)):
        if not sel.any():
            continue
        L.append(f"/{kw}/{part_id:10d}")
        L.append("#  SHELLID      NOD1      NOD2      NOD3      NOD4                                THK")
        nn = 4 if kw == "SHELL" else 3
        for e in np.flatnonzero(sel):
            row = f"{int(elem_id[e]):10d}" + "".join(f"{int(n):10d}" for n in conn_ids[e][:nn])
            L.append(row.ljust(80) + f20(thk1[e]))
    if extra_tetra:
        L += ["", "", f"/TETRA4/{22:10d}", "# TETRA4ID      NOD1      NOD2      NOD3      NOD4",
              "    706053    530713    309378    309380    307200"]
    L += ["/NODE", "#    NODID               XCOOR               YCOOR               ZCOOR"]
    for k in range(node_id.size):
        L.append(f"{int(node_id[k]):10d}" + "".join(f20(c) for c in X1[k]))
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path


def write_sta(path, elem_id, et, thk1, epsp_layers, elems=None):
    """epsp_layers (E, NPT) — IPG 무관 값(IPG 수 = QUAD 4·TRIA 1). elems: 쓸 요소 위치(기본 전부)."""
    L = ["", ""] + BEGIN_NUM + COMMENT7
    idx = range(elem_id.size) if elems is None else elems
    for e in idx:
        g = NPG if et[e] == 4 else 1
        L.append(f"{int(elem_id[e]):10d}{NPT:10d}{g:10d}{f20(thk1[e])}")
        vals = [float(epsp_layers[e, ipt]) for ipt in range(NPT) for _ in range(g)]
        for k in range(0, len(vals), 5):
            L.append("".join(f20(v) for v in vals[k:k + 5]))
    L += ["", "", COMMENT7[0], "/INIBRI/STRA_F", "#  BRICKID      NPT    ISOLNOD    ISOLID",
          "    924269         1         4         1",
          "-3.5189106711186E-04-4.5962637523189E-04-3.3091797376983E-04",
          "-3.0851305928081E-04 3.1190240406431E-04 2.4872072390281E-04", "/INIBRI/FAIL"]
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path


def write_main_rad(path, includes, t0=T0):
    L = ["#RADIOSS STARTER", "/BEGIN", "#Runname", "Plate_Drop_2nd", _w._i10(2024) + _w._i10(0),
         " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00",
         " 1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00", _w._RULER]
    L += _w._mat_law1(MID, f"mat_{MID}", 7.85e-9, E_MOD, NU)
    L += _w._prop_shell(PID, f"prop_{PID}", t0)
    L += _w._part(PART_ID, PART_TITLE, PID, MID)
    L += _w._part(22, "bracket", PID, MID)
    for inc in includes:
        L.append(f"#include {inc}")
    L.append("/END")
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path


def build(root: str, hot_k: int = 5000, top_n: int = 5, epsp_h3d_cumulative: bool = True) -> dict:
    X0, conn, et, _thk = synth_case.plate()
    N, Ne = X0.shape[0], conn.shape[0]
    node_id = 1001 + 2 * np.arange(N, dtype=np.int64)
    elem_id = 50001 + 3 * np.arange(Ne, dtype=np.int64)
    conn_ids = np.where(conn >= 0, node_id[np.maximum(conn, 0)], -1)
    pc = supports.pca_corners(X0)
    sup = supports.pick_321(X0, pc["idx"])
    sup_idx = [i for i, _ in sup]
    s = (X0 - X0.mean(axis=0)) / 150.0

    # ---------------- 1차 런(작은 변형) → 상태
    sm0 = ShellModel(X0, conn, et, np.full(Ne, T0), E_MOD, NU, drill_factor=1e-4)
    F1 = np.stack([0 * s[:, 0], 0 * s[:, 1], 30 * np.cos(1.1 * s[:, 0]) * np.sin(1.7 * s[:, 1] + 0.3) + 5], axis=1)
    F1[sup_idx] = 0.0
    u1, _ = sm0.solve(F1, sup)
    u1 = u1[:, :3] * (0.4 / np.abs(u1[:, :3]).max())
    X1 = X0 + u1
    C0 = np.where((et == 4)[:, None], X0[np.maximum(conn, 0)][:, :4].mean(axis=1),
                  X0[conn[:, :3]].mean(axis=1))
    w = np.exp(-np.sum(((C0 - C0.mean(axis=0)) / 80.0) ** 2, axis=1))
    thk1 = T0 * (1.0 - 0.03 * w)
    p = 0.02 * w * (w > 0.3)

    # ---------------- 2차 런(상태 형상 기준)
    sm = ShellModel(X1, conn, et, thk1, E_MOD, NU, drill_factor=1e-4)
    rng = np.random.default_rng(7)
    F = np.stack([20 * np.sin(2.1 * s[:, 0]) * np.cos(1.3 * s[:, 1]),
                  -15 * np.cos(1.7 * s[:, 1]) + 5 * s[:, 0],
                  40 * np.cos(1.2 * s[:, 0]) * np.sin(2.3 * s[:, 1] + 0.4) + 10], axis=1)
    hot = rng.choice(N, 6, replace=False)
    F[hot] += rng.normal(0, 400, (6, 3))
    F[sup_idx] = 0.0
    u_d, _ = sm.solve(F, sup)
    eb = sm.strains(u_d)
    e1 = 0.5 * (eb[:, 0] + eb[:, 1])
    sc = EQ_MAX / strain.eps_eq(e1).max()
    u_d, e1 = u_d * sc, e1 * sc
    eq1 = strain.eps_eq(e1)
    d1, _, _ = kabsch.remove_linear_rigid(X1, u_d[:, :3])
    e_lo = int(np.argmin(np.where(et == 4, eq1, np.inf)))
    i, j = int(conn[e_lo, 0]), int(conn[e_lo, 2])
    dv = (X1[j] - X1[i]) / np.linalg.norm(X1[j] - X1[i])
    F2 = np.zeros_like(F)
    F2[i], F2[j] = dv, -dv
    u_2, _ = sm.solve(F2, sup)
    eb2 = sm.strains(u_2)
    e2 = 0.5 * (eb2[:, 0] + eb2[:, 1])
    sc2 = 0.6 * eq1.max() / strain.eps_eq(e2).max()
    u_2, e2 = u_2 * sc2, e2 * sc2
    d2, _, _ = kabsch.remove_linear_rigid(X1, u_2[:, :3])
    A, B = synth_case.A_T, synth_case.B_T
    Fr = A.size
    times = 1.0e-3 * np.arange(Fr)
    c0 = X1.mean(axis=0)
    U = np.empty((Fr, N, 3))
    for k in range(Fr):
        Q = synth_case.rot([0.3, -0.5, 0.8], np.radians(10.0) * k / synth_case.T_STAR_FRAME)
        T = np.array([20.0 * k, -5.0 * k, 2.0 * k * k])
        U[k] = (X1 + A[k] * d1 + B[k] * d2 - c0) @ Q.T + c0 + T - X1
    inst = A[:, None, None] * e1[None] + B[:, None, None] * e2[None]
    eq_inst = strain.eps_eq(inst)
    eq_hold, eps_hold = max_hold(eq_inst, inst)
    ey = 0.4 * eq_inst[synth_case.T_STAR_FRAME].max()
    inc_ep = np.maximum.accumulate(np.maximum(eq_inst - ey, 0.0), axis=0)
    # 이전 손상 큰 요소: 패턴 2 국부 요소(e_lo) — 이번 증분 작음(first-reach = frame 3)
    e_big = e_lo
    p[e_big] = PREV_BIG
    # 이전 손상만(이번 증가 없음) 요소: ε_eq 가장 작은 QUAD 여러 개는 증분 0 근처
    layers = p[:, None] * (1.0 + 0.1 * (np.arange(NPT)[None, :] - 2))      # IPT 3 = p → mid_mean = p
    epsp_h3d = inc_ep + p[None, :] if epsp_h3d_cumulative else inc_ep
    eps_h3d = eps_hold.copy()
    eps_h3d[..., 2] *= 2.0

    din = os.path.join(root, "in")
    dcsv = os.path.join(din, "csv")
    os.makedirs(dcsv, exist_ok=True)
    sname, aname = f"{RUN1}_0002.str", f"{RUN1}_0002.sta"
    write_str(os.path.join(din, sname), node_id, X1, elem_id, et, conn_ids, thk1)
    write_sta(os.path.join(din, aname), elem_id, et, thk1, layers)
    rad = write_main_rad(os.path.join(din, "model_2nd_0000.rad"), [sname, aname])
    rad0 = write_rad(os.path.join(din, "model_orig_0000.rad"), node_id, X0, elem_id, et, conn_ids, PART_ID,
                     PART_TITLE, PID, np.full(Ne, T0), MID, E_MOD, NU)
    write_results_csv(dcsv, times, node_id, X1, U, elem_id, eps_h3d, vm_hv=eq_hold,
                      ezz=-(eps_hold[..., 0] + eps_hold[..., 1]), epsp=epsp_h3d, hot_k=hot_k, top_n=top_n,
                      elem_nodes=conn_ids)
    with open(os.path.join(dcsv, "frame0.csv"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("elem_id,vm_hv,epsp\n")
        for e in range(Ne):
            fh.write(f"{int(elem_id[e])},{float(eq_hold[0, e])!r},{float(epsp_h3d[0, e])!r}\n")
    dpath = os.path.join(dcsv, "done.json")
    done = json.load(open(dpath, encoding="utf-8"))
    done["cumulative"] = {"prev_file_sha256": None, "prev_n": int(Ne), "frame0": True, "frame0_rows": int(Ne),
                          "rank_sets": ["raw", "raw+prev"], "min_incr": 1e-5}
    with open(dpath, "w", encoding="utf-8") as fh:
        json.dump(done, fh)
    return {"rad": rad, "rad_orig": rad0, "csv": dcsv, "din": din, "node_id": node_id, "elem_id": elem_id,
            "X0": X0, "X1": X1, "thk1": thk1, "prev": p, "e_big": e_big, "inc_ep": inc_ep, "eq_hold": eq_hold,
            "epsp_h3d": epsp_h3d, "times": times, "et": et, "conn_ids": conn_ids, "str": sname, "sta": aname}
