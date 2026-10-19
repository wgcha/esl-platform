"""라이브러리 시험용 합성 Case 생성기 (코어 합성 생성기 tests/pipeline/synth_case.py 의 도구 재사용).

TV 후면처럼 XZ 평면(가로 X, 세로 Z, 두께 방향 Y)에 놓인 약간 휜 판. 크기 배율 ``scale``(인치 비례)과 메시 밀도
(nx, ny)를 바꿀 수 있고, 하중은 **정규화 좌표 (ξ,η) 의 매끄러운 분포 하중 × 절점 기여 면적** 이라 메시와 무관한
같은 하중장을 준다.

- 패턴 A: 면외(−Y) 분포 하중 q_n = 1 + 1.5 ξ² + sin(πη) (굽힘 지배)
- 패턴 B: 면내 분포 하중 q_ξ = sin(2πη), q_η = 0.6 cos(πξ) (막/전단 지배)

분포 하중에 강체 가속도 관성력을 더해 자기평형(낙하 ESL 과 같은 성질, 지지 반력 ≈ 0)으로 만든 뒤
3-2-1 지지(pca 4꼭지점 → pick_321)로 풀어 변형 d 를 만들고 max|d| = amp mm 로 스케일. 시간 이력 a(t)(피크 frame 6)
× d + 대회전·병진 강체운동 → TCL 3패스 CSV + rad. h3d 경로(씬 메타 규칙 파일명)는 done.json → frames.json 에 남는다.
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
import synth_case  # noqa: E402  (코어 합성 Case 도구: rot, A_T, 재료 상수)

from esl.io import max_hold, write_results_csv  # noqa: E402
from esl.library import normalize as nz  # noqa: E402
from esl.mech import kabsch, strain, supports  # noqa: E402
from esl.mech.shell import ShellModel  # noqa: E402
from esl.rad import write_rad  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")


def plate_xz(nx, ny, scale=1.0, Lx=300.0, Lz=200.0, n_tria_cols=2):
    """(X0, conn, elem_type, thickness). 가로 X·세로 Z, 면외 Y 로 약간 휨(배율과 닮은꼴)."""
    Lx, Lz = Lx * scale, Lz * scale
    xs = np.linspace(0, Lx, nx + 1)
    zs = np.linspace(0, Lz, ny + 1)
    Xg, Zg = np.meshgrid(xs, zs, indexing="ij")
    Yg = scale * (12.0 * (1 - ((Xg - Lx / 2) / (Lx / 2)) ** 2) + 4.0 * ((Zg - Lz / 2) / (Lz / 2)) ** 2)
    P = np.stack([Xg.ravel(), Yg.ravel(), Zg.ravel()], axis=1) + np.array([-150.0, 800.0, 300.0])
    nid = lambda i, j: i * (ny + 1) + j   # noqa: E731
    conn, et = [], []
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if i < n_tria_cols:
                conn += [[a, b, c, -1], [a, c, d, -1]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    conn = np.array(conn, dtype=np.int64)
    et = np.array(et, dtype=np.int8)
    thk = np.full(conn.shape[0], 2.5)
    return P, conn, et, thk


def pattern_load(X0, conn, et, pattern, frame=None):
    fr = frame or nz.frame(X0, None, conn, et)
    loc = nz.local_coords(fr, X0)
    xi, eta = loc[:, 0], loc[:, 1]
    A = nz.node_areas(X0, conn, et)
    R = nz.rotation(fr)
    q = np.zeros((X0.shape[0], 3))
    if pattern == "A":
        q[:, 2] = -(1.0 + 1.5 * xi ** 2 + np.sin(np.pi * eta))
    elif pattern == "B":
        q[:, 0] = np.sin(2 * np.pi * eta)
        q[:, 1] = 0.6 * np.cos(np.pi * xi)
    else:
        raise ValueError(pattern)
    F = (q @ R) * A[:, None]              # 전역 성분 절점력
    return equilibrate_inertial(X0, F, A)


def equilibrate_inertial(X0, F, m):
    """강체 가속도 관성력(d'Alembert) f_i = −m_i (a + α×(x_i−c)) 을 더해 ΣF = 0, ΣM = 0 (낙하 ESL 처럼 자기평형)."""
    c = (m[:, None] * X0).sum(axis=0) / m.sum()
    r = X0 - c
    Ft = F.sum(axis=0)
    Mt = np.cross(r, F).sum(axis=0)
    # 관성력의 합력 = −M a, 합모멘트 = −J α  (J = Σ m (|r|² I − r rᵀ))
    J = np.einsum("i,ij,ik->jk", m, r, r)
    J = np.trace(J) * np.eye(3) - J
    a = Ft / m.sum()
    al = np.linalg.solve(J, Mt)
    return F - m[:, None] * (a + np.cross(al, r))


def build(root, h3d_path, scale=1.0, nx=24, ny=16, pattern="A", amp=1.0, n_tria_cols=2):
    """root/in/model_0000.rad, root/in/csv/*.csv. 반환 {rad, csv, F_app, X0, ...}."""
    X0, conn, et, thk = plate_xz(nx, ny, scale, n_tria_cols=n_tria_cols)
    N, Ne = X0.shape[0], conn.shape[0]
    node_id = 2001 + 3 * np.arange(N, dtype=np.int64)
    elem_id = 70001 + 2 * np.arange(Ne, dtype=np.int64)
    sm = ShellModel(X0, conn, et, thk, synth_case.E_MOD, synth_case.NU, drill_factor=1e-4)
    pc = supports.pca_corners(X0)
    sup = supports.pick_321(X0, pc["idx"])
    F = pattern_load(X0, conn, et, pattern)
    u_d, R = sm.solve(F, sup)
    sc = amp / np.abs(u_d[:, :3]).max()
    F, u_d, R = F * sc, u_d * sc, R * sc
    d, _, _ = kabsch.remove_linear_rigid(X0, u_d[:, :3])
    eps_b = sm.strains(u_d)
    eps_d = 0.5 * (eps_b[:, 0] + eps_b[:, 1])
    A_T = synth_case.A_T
    c0 = X0.mean(axis=0)
    Fr = A_T.size
    times = 1.0e-3 * np.arange(Fr)
    U = np.empty((Fr, N, 3))
    for k in range(Fr):
        Q = synth_case.rot([0.2, 0.9, -0.3], np.radians(20.0) * k / synth_case.T_STAR_FRAME)
        T = np.array([30.0 * k, -10.0 * k, 4.0 * k * k])
        U[k] = (X0 + A_T[k] * d - c0) @ Q.T + c0 + T - X0
    eps_inst = A_T[:, None, None] * eps_d[None]
    eq_inst = strain.eps_eq(eps_inst)
    eq_hold, eps_hold = max_hold(eq_inst, eps_inst)
    ey = 0.5 * eq_inst[synth_case.T_STAR_FRAME].max()
    epsp = np.maximum.accumulate(np.maximum(eq_inst - ey, 0.0), axis=0)
    din = os.path.join(root, "in")
    dcsv = os.path.join(din, "csv")
    os.makedirs(dcsv, exist_ok=True)
    conn_ids = np.where(conn >= 0, node_id[np.maximum(conn, 0)], -1)
    rad = write_rad(os.path.join(din, "model_0000.rad"), node_id, X0, elem_id, et, conn_ids, synth_case.PART_ID,
                    synth_case.PART_TITLE, synth_case.PID, thk, synth_case.MID, synth_case.E_MOD, synth_case.NU)
    write_results_csv(dcsv, times, node_id, X0, U, elem_id, eps_hold, vm_hv=eq_hold,
                      ezz=-(eps_hold[..., 0] + eps_hold[..., 1]), epsp=epsp, h3d=h3d_path)
    return {"rad": rad, "csv": dcsv, "X0": X0, "conn": conn, "et": et, "F_app": F, "R": R, "node_id": node_id,
            "sup_ids": [int(node_id[i]) for i, _ in sup], "pattern": pattern, "scale": scale}


def config64(path):
    """합성 변위는 float64 로 저장 → 잡음 바닥도 float64 기준 설정."""
    txt = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return path
