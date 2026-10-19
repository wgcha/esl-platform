"""T-E2E-1 합성 사례 생성기.

곡률이 약간 있는 판(QUAD 위주 + TRIA 띠, 두께 2종) → esl.mech 로 3-2-1 지지 + 하중 F_app → 변형 u_d.
u_d 에서 선형 강체를 뺀 d 를 시간 스케일 a(t) 로 키우고, 프레임별 대회전(t* 에서 25°)+병진 강체운동을
합성해 TCL 포맷 CSV(write_results_csv) + rad(write_rad) 를 쓴다. strain 은 ShellModel.strains(u_d)·a(t).
"""
from __future__ import annotations

import os

import numpy as np

from esl.io import write_results_csv
from esl.mech import kabsch, supports
from esl.mech.shell import ShellModel
from esl.rad import write_rad

E_MOD, NU = 2.1e5, 0.3
A_T = np.array([0.0, 0.3, 0.6, 0.5, 0.4, 0.7, 1.0, 0.8, 0.5, 0.3, 0.2])   # 피크 frame 6 (2번째 국소최대 frame 2)
T_STAR_FRAME = 6
SECOND_PEAK_FRAME = 2
PART_ID, PART_TITLE = 7, "Chassis  REAR"      # 설정 "chassis rear" 와 exact_ci 로 일치
PID, MID = 70, 700


def rot(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def plate(nx=40, ny=26, Lx=300.0, Ly=200.0, n_tria_cols=4):
    xs = np.linspace(0, Lx, nx + 1)
    ys = np.linspace(0, Ly, ny + 1)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    Z = 15.0 * (1 - ((X - Lx / 2) / (Lx / 2)) ** 2) + 5.0 * ((Y - Ly / 2) / (Ly / 2)) ** 2
    P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1) + np.array([1000.0, 500.0, 200.0])
    nid = lambda i, j: i * (ny + 1) + j
    conn, et = [], []
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if i < n_tria_cols:
                if (i + j) % 2:
                    conn += [[a, b, d, -1], [b, c, d, -1]]
                else:
                    conn += [[a, b, c, -1], [a, c, d, -1]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    conn = np.array(conn, dtype=np.int64)
    et = np.array(et, dtype=np.int8)
    q = et == 4
    cx = np.where(q, P[np.maximum(conn, 0)][:, :4, 0].mean(axis=1), P[conn[:, :3]][:, :, 0].mean(axis=1))
    thk = np.where(cx < 1000.0 + Lx / 2, 2.0, 2.5)
    return P, conn, et, thk


def build(root: str) -> dict:
    """root/in/model_0000.rad, root/in/csv/*.csv 생성. 기대값 dict 반환."""
    X0, conn, et, thk = plate()
    N, Ne = X0.shape[0], conn.shape[0]
    node_id = 1001 + 2 * np.arange(N, dtype=np.int64)
    elem_id = 50001 + 3 * np.arange(Ne, dtype=np.int64)

    sm = ShellModel(X0, conn, et, thk, E_MOD, NU, drill_factor=1e-4)
    pc = supports.pca_corners(X0)
    sup = supports.pick_321(X0, pc["idx"])
    sup_idx = [i for i, _ in sup]

    # 임의(매끈 + 집중) 하중, 지지 노드는 0
    rng = np.random.default_rng(42)
    s = (X0 - X0.mean(axis=0)) / 150.0
    F = np.stack([20 * np.sin(2.1 * s[:, 0]) * np.cos(1.3 * s[:, 1]),
                  -15 * np.cos(1.7 * s[:, 1]) + 5 * s[:, 0],
                  40 * np.cos(1.2 * s[:, 0]) * np.sin(2.3 * s[:, 1] + 0.4) + 10], axis=1)
    hot = rng.choice(N, 6, replace=False)
    F[hot] += rng.normal(0, 400, (6, 3))
    F[sup_idx] = 0.0
    u_d, R = sm.solve(F, sup)
    sc = 1.0 / np.abs(u_d[:, :3]).max()          # max|u_d| = 1 mm
    F, u_d, R = F * sc, u_d * sc, R * sc
    d, _, _ = kabsch.remove_linear_rigid(X0, u_d[:, :3])
    eps_d = sm.strains(u_d)                      # (E,2,3), 강체 무관

    # 강체 대회전 + 병진 합성
    c0 = X0.mean(axis=0)
    axis = [0.3, -0.5, 0.8]
    Fr = A_T.size
    times = 1.0e-3 * np.arange(Fr)
    U = np.empty((Fr, N, 3))
    for k in range(Fr):
        Q = rot(axis, np.radians(25.0) * k / T_STAR_FRAME)
        T = np.array([40.0 * k, -15.0 * k, 5.0 * k * k])
        x = (X0 + A_T[k] * d - c0) @ Q.T + c0 + T
        U[k] = x - X0
    eps = A_T[:, None, None, None] * eps_d[None]

    din = os.path.join(root, "in")
    dcsv = os.path.join(din, "csv")
    os.makedirs(dcsv, exist_ok=True)
    conn_ids = np.where(conn >= 0, node_id[np.maximum(conn, 0)], -1)
    rad = write_rad(os.path.join(din, "model_0000.rad"), node_id, X0, elem_id, et, conn_ids, PART_ID,
                    PART_TITLE, PID, thk, MID, E_MOD, NU, extra_parts=1)
    write_results_csv(dcsv, times, node_id, X0, U, elem_id, eps,
                      extra_nodes=[int(node_id.max()) + 1], extra_elems=[int(elem_id.max()) + 1])
    return {"rad": rad, "csv": dcsv, "node_id": node_id, "elem_id": elem_id, "X0": X0, "F_app": F,
            "R": R, "u_d": u_d, "d": d, "eps_d": eps_d, "sup": sup, "sup_ids": [int(node_id[i]) for i in sup_idx],
            "times": times, "dummy_node": int(node_id.max()) + 1, "thk": thk, "et": et}
