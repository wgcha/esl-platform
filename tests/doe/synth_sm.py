"""강성 지표(esl_stiffness_metric.md V-SM-1~4) 합성 도구: XZ 판(법선 Y), 3-2-1, 자기평형 하중, 국부 비드 모핑, 재풀이.

시험 전용 — 재풀이(solve)·응축(condense) 참조 구현은 여기서만(모듈은 분해 호출 금지)."""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "opt"))
import synth_opt as so  # noqa: E402

from esl.mech.shell import ShellModel  # noqa: E402


def plate(nx=24, ny=12, Lx=300.0, Lz=150.0, t=1.0, bow=3.0, n_tria_cols=4):
    """quad·tria 혼합, 살짝 휜(bow) XZ 판."""
    return so.plate(nx=nx, ny=ny, Lx=Lx, Lz=Lz, t=t, bow=bow, n_tria_cols=n_tria_cols)


def spc(mesh):
    nid = mesh["node_id"]
    return [(int(np.searchsorted(nid, n)), d) for n, d in so.supports_321(mesh)]


def model(mesh, x=None):
    return ShellModel(mesh["x0"] if x is None else x, mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"],
                      mesh["nu"], backend="superlu")


def _project_out(X, q, cols):
    """q 에서 span{1, X[:, cols]} 성분 제거(최소제곱) — Σq = Σ x_c q = 0."""
    A = np.column_stack([np.ones(X.shape[0])] + [X[:, c] for c in cols])
    c, *_ = np.linalg.lstsq(A, q, rcond=None)
    return q - A @ c


def y_load(mesh, amp=1.0):
    """Y(법선) 방향만의 자기평형 하중(굽힘 + 비틀림 + 국부 덴트). F ∥ Y 라 Y 방향 모핑에서도 모멘트 0 유지."""
    X = mesh["x0"]
    s = 2 * (X[:, 0] - X[:, 0].min()) / np.ptp(X[:, 0]) - 1
    t = 2 * (X[:, 2] - X[:, 2].min()) / np.ptp(X[:, 2]) - 1
    q = 0.5 * (3 * s ** 2 - 1) + 0.7 * s * t + 2.0 * np.exp(-((s - 0.3) ** 2 + (t + 0.2) ** 2) / 0.02)
    q = _project_out(X, q, (0, 2))
    F = np.zeros_like(X)
    F[:, 1] = amp * q
    return F


def drop_u(mesh, amp=1.0, dent=(0.35, 0.0), w=0.06):
    """낙하 변위 u_drop(병진 3, 회전 자유): 국부 덴트(면외) + 막(면내) 압축. ESL F = K₀u_drop(회전 응축)."""
    X = mesh["x0"]
    s = 2 * (X[:, 0] - X[:, 0].min()) / np.ptp(X[:, 0]) - 1
    t = 2 * (X[:, 2] - X[:, 2].min()) / np.ptp(X[:, 2]) - 1
    g = np.exp(-((s - dent[0]) ** 2 + (t - dent[1]) ** 2) / w)
    u = np.zeros_like(X)
    u[:, 1] = amp * g
    u[:, 0] = -0.2 * amp * s * g
    u[:, 2] = -0.2 * amp * t * g
    return u


def esl_force(mesh, u_drop):
    """F = K₀ u_drop(회전 응축 = ESL 생성과 같은 식). 자기평형(K 의 강체 무에너지)."""
    return model(mesh).condensed_forces(u_drop)


def bead_x(mesh, alpha, depth=8.0, center=(0.35, 0.0), r=0.12):
    """국부 비드: Y += α·depth·g(가우스, 판 정규 좌표 중심·반경). 같은 노드(S = I)."""
    X = mesh["x0"].copy()
    s = 2 * (X[:, 0] - X[:, 0].min()) / np.ptp(X[:, 0]) - 1
    t = 2 * (X[:, 2] - X[:, 2].min()) / np.ptp(X[:, 2]) - 1
    X[:, 1] += alpha * depth * np.exp(-((s - center[0]) ** 2 + (t - center[1]) ** 2) / r ** 2)
    return X


def solve(mesh, F, x=None):
    """재풀이(3-2-1): (u (N,6), C = F·u, umax)."""
    u, R = model(mesh, x).solve(F, spc(mesh))
    return u, float(np.sum(F * u[:, :3])), float(np.max(np.linalg.norm(u[:, :3], axis=1))), R


def condensed_U2(mesh, x, u_t6):
    """시험 전용 응축 참조: 회전 자유 최적 → U2 = u_tᵀ K̂ u_t(병진만)."""
    Fc = model(mesh, x).condensed_forces(u_t6[:, :3])
    return float(np.sum(Fc * u_t6[:, :3]))
