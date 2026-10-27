"""T-E2E-1 합성 사례 생성기 (esl_core.md §7: max-hold 지표, first-reach t*).

곡률이 약간 있는 판(QUAD 위주 + TRIA 띠, 두께 2종) → esl.mech 로 3-2-1 지지 + 하중 2종 → 변형 u_1, u_2.
선형 강체를 뺀 d_i 를 시간 함수 a(t)·b(t) 로 섞고(d = a·d1 + b·d2), 프레임별 대회전(t* 에서 25°)+병진
강체운동을 합성한다. 변형률(Mid = 막, ShellModel.strains 의 bottom·top 평균)은 순간값 ε(t) = a·ε1 + b·ε2 에
요소별 max-hold 를 적용해 h3d 의 Max_Strain 처럼 만들고(XY 는 공학 전단 γ = 2·exy 로 저장 → 전단 규약 auto
판정 시험), Plastic Strain = max-hold(max(0, ε_eq − ε_y)). TCL 3패스 포맷 CSV(write_results_csv) + rad.

- 패턴 1(전역, a 피크 frame 6, b(6)=0) → t* = frame 6 에서 F_eq = F1(+지지 반력).
- 패턴 2(국부 집중하중, b 피크 frame 3) → 그 부근 요소의 first-reach = frame 3 → 두 번째 후보.
"""
from __future__ import annotations

import os

import numpy as np

from esl.io import max_hold, write_results_csv
from esl.mech import kabsch, strain, supports
from esl.mech.shell import ShellModel
from esl.rad import write_rad

E_MOD, NU = 2.1e5, 0.3
A_T = np.array([0.0, 0.3, 0.6, 0.5, 0.4, 0.7, 1.0, 0.8, 0.5, 0.3, 0.2])   # 패턴 1, 피크 frame 6
B_T = np.array([0.0, 0.4, 0.7, 1.0, 0.5, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0])   # 패턴 2, 피크 frame 3, b(6)=0
T_STAR_FRAME = 6
SECOND_PEAK_FRAME = 3
EPS_Y_REL = 0.4             # 소성 시작 = 0.4·max ε_eq(t*)
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


def build(root: str, hot_k: int = 200, top_n: int = 5) -> dict:
    """root/in/model_0000.rad, root/in/csv/*.csv 생성. 기대값 dict 반환."""
    X0, conn, et, thk = plate()
    N, Ne = X0.shape[0], conn.shape[0]
    node_id = 1001 + 2 * np.arange(N, dtype=np.int64)
    elem_id = 50001 + 3 * np.arange(Ne, dtype=np.int64)

    sm = ShellModel(X0, conn, et, thk, E_MOD, NU, drill_factor=1e-4)
    pc = supports.pca_corners(X0)
    sup = supports.pick_321(X0, pc["idx"])
    sup_idx = [i for i, _ in sup]

    # 패턴 1: 임의(매끈 + 집중) 하중, 지지 노드는 0
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
    eps_b = sm.strains(u_d)                      # (E,2,3), 강체 무관
    eps_d = 0.5 * (eps_b[:, 0] + eps_b[:, 1])    # Mid = 막 (E,3)
    eq1 = strain.eps_eq(eps_d)

    # 패턴 2: 패턴 1 의 ε_eq 가 작은 QUAD 의 대각 두 노드를 서로 당기는 자기평형 국부 하중(반력≈0)
    e_lo = int(np.argmin(np.where(et == 4, eq1, np.inf)))
    i, j = int(conn[e_lo, 0]), int(conn[e_lo, 2])
    dvec = (X0[j] - X0[i]) / np.linalg.norm(X0[j] - X0[i])
    F2 = np.zeros_like(F)
    F2[i], F2[j] = dvec, -dvec
    u_2, R2 = sm.solve(F2, sup)
    eps_b2 = sm.strains(u_2)
    eps_2 = 0.5 * (eps_b2[:, 0] + eps_b2[:, 1])
    sc2 = 0.6 * eq1.max() / strain.eps_eq(eps_2).max()     # 패턴 2 피크 ε_eq = 0.6·패턴 1 최대
    F2, u_2, R2, eps_2 = F2 * sc2, u_2 * sc2, R2 * sc2, eps_2 * sc2
    d2, _, _ = kabsch.remove_linear_rigid(X0, u_2[:, :3])

    # 강체 대회전 + 병진 합성
    c0 = X0.mean(axis=0)
    axis = [0.3, -0.5, 0.8]
    Fr = A_T.size
    times = 1.0e-3 * np.arange(Fr)
    U = np.empty((Fr, N, 3))
    for k in range(Fr):
        Q = rot(axis, np.radians(25.0) * k / T_STAR_FRAME)
        T = np.array([40.0 * k, -15.0 * k, 5.0 * k * k])
        x = (X0 + A_T[k] * d + B_T[k] * d2 - c0) @ Q.T + c0 + T
        U[k] = x - X0
    # 순간 변형률 → 요소별 max-hold (h3d Max_Strain), Plastic Strain
    eps_inst = A_T[:, None, None] * eps_d[None] + B_T[:, None, None] * eps_2[None]      # (F,E,3) 텐서
    eq_inst = strain.eps_eq(eps_inst)
    eq_hold, eps_hold = max_hold(eq_inst, eps_inst)
    ey = EPS_Y_REL * eq_inst[T_STAR_FRAME].max()
    epsp = np.maximum.accumulate(np.maximum(eq_inst - ey, 0.0), axis=0)
    eps_h3d = eps_hold.copy()
    eps_h3d[..., 2] *= 2.0                                   # h3d XY = 공학 전단 γ
    vm_hv = eq_hold                                          # HyperView vonMises = ε_eq(텐서)

    din = os.path.join(root, "in")
    dcsv = os.path.join(din, "csv")
    os.makedirs(dcsv, exist_ok=True)
    conn_ids = np.where(conn >= 0, node_id[np.maximum(conn, 0)], -1)
    rad = write_rad(os.path.join(din, "model_0000.rad"), node_id, X0, elem_id, et, conn_ids, PART_ID,
                    PART_TITLE, PID, thk, MID, E_MOD, NU, extra_parts=1)
    write_results_csv(dcsv, times, node_id, X0, U, elem_id, eps_h3d, vm_hv=vm_hv,
                      ezz=-(eps_hold[..., 0] + eps_hold[..., 1]), epsp=epsp, hot_k=hot_k, top_n=top_n,
                      extra_nodes=[int(node_id.max()) + 1], extra_elems=[int(elem_id.max()) + 1], elem_nodes=conn_ids)
    return {"rad": rad, "csv": dcsv, "node_id": node_id, "elem_id": elem_id, "X0": X0, "F_app": F,
            "R": R, "F2": F2, "R2": R2, "u_d": u_d, "d": d, "eps_d": eps_d, "eps_2": eps_2, "eq_hold": eq_hold,
            "eq_inst": eq_inst, "epsp": epsp, "sup": sup, "sup_ids": [int(node_id[i]) for i in sup_idx],
            "times": times, "dummy_node": int(node_id.max()) + 1, "thk": thk, "et": et}
