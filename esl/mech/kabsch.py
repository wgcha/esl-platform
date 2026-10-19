"""강체 적합·제거 (계약 esl_core.md §4, esl.md §6.5).

fit: min_{R∈SO(3), t} Σ_i |R·X0_i + t − x_i|²  (균등 가중, 중심화 + SVD, 반사 보정).
remove_rigid: u_rel = Rᵀ(X0 + u − t) − X0.
수치: 큰 좌표·병진에서도 정밀도를 지키려고 중심화 좌표로 계산한다
  u_rel = (Rᵀ − I)(X0 − c0) + Rᵀ(u − ū).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

DEGENERATE_RATIO = 1e-9


def _fit_centered(P, Q, allow_reflection):
    """P = X0 − c0, Q = x − c (중심화). R 반환과 info."""
    sP = np.linalg.svd(P, compute_uv=False)
    if sP.size < 2 or sP[0] <= 0 or sP[1] / sP[0] < DEGENERATE_RATIO:
        raise EslError("KABSCH_DEGENERATE", f"점들이 공선/일치 (특이값 비 {sP[1] / sP[0] if sP[0] > 0 else 0:.2e})")
    H = P.T @ Q
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    if d == 0:
        d = 1.0
    reflected = False
    if d < 0 and not allow_reflection:
        Dm = np.diag([1.0, 1.0, -1.0])
        R = Vt.T @ Dm @ U.T
        reflected = True
    else:
        R = Vt.T @ U.T
    return R, {"sv_X0": sP.tolist(), "reflection_corrected": reflected}


def fit(X0, x, allow_reflection: bool = False):
    X0 = np.asarray(X0, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if X0.ndim != 2 or X0.shape[1] != 3 or x.shape != X0.shape:
        raise EslError("INPUT_INVALID", "X0, x 는 같은 (n,3)")
    if X0.shape[0] < 3:
        raise EslError("KABSCH_DEGENERATE", f"점 {X0.shape[0]}개 < 3")
    c0 = X0.mean(axis=0)
    c = x.mean(axis=0)
    R, info = _fit_centered(X0 - c0, x - c, allow_reflection)
    t = c - R @ c0
    r = X0 @ R.T + t - x
    info["rms"] = float(np.sqrt(np.mean(np.sum(r * r, axis=1))))
    info["det"] = float(np.linalg.det(R))
    return R, t, info


def rotation_deg(R) -> float:
    c = (np.trace(R) - 1.0) / 2.0
    # 작은 각에서 arccos 정밀도 손실 → arctan2(‖axial‖, c)
    ax = 0.5 * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return float(np.degrees(np.arctan2(np.linalg.norm(ax), c)))


def remove_rigid(X0, u):
    """전 노드 Kabsch 후 u_rel = Rᵀ(X0+u−t) − X0.  info {rms_def, max_def, rot_deg}."""
    X0 = np.asarray(X0, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    if X0.ndim != 2 or X0.shape[1] != 3 or u.shape != X0.shape:
        raise EslError("INPUT_INVALID", "X0, u 는 같은 (N,3)")
    if X0.shape[0] < 3:
        raise EslError("KABSCH_DEGENERATE", f"점 {X0.shape[0]}개 < 3")
    c0 = X0.mean(axis=0)
    ub = u.mean(axis=0)
    P = X0 - c0
    du = u - ub
    R, fi = _fit_centered(P, P + du, False)
    t = c0 + ub - R @ c0
    u_rel = P @ (R.T - np.eye(3)).T + du @ R      # (Rᵀ−I)P + Rᵀ du  (행벡터: v·R = (Rᵀv)ᵀ)
    nrm = np.linalg.norm(u_rel, axis=1)
    info = {
        "rms_def": float(np.sqrt(np.mean(nrm ** 2))),
        "max_def": float(nrm.max()),
        "rot_deg": rotation_deg(R),
        "reflection_corrected": fi["reflection_corrected"],
    }
    return u_rel, R, t, info


def remove_linear_rigid(X0, u):
    """미소(선형화) 강체 a + ω×(X0−c0) 를 최소제곱으로 제거 (계약 외 보조, S5 검증용).

    선형 해석 결과(u_val)처럼 회전이 '미소 회전'으로 들어 있는 장에는 Kabsch(유한 회전)보다
    이쪽이 정확하다(Kabsch 는 O(ω²·L) 잔차를 남김).  반환 (u_rel, a(3,), ω(3,)).
    """
    X0 = np.asarray(X0, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    if X0.ndim != 2 or X0.shape[1] != 3 or u.shape != X0.shape:
        raise EslError("INPUT_INVALID", "X0, u 는 같은 (N,3)")
    P = X0 - X0.mean(axis=0)
    s = np.linalg.svd(P, compute_uv=False)
    if X0.shape[0] < 3 or s[0] <= 0 or s[1] / s[0] < DEGENERATE_RATIO:
        raise EslError("KABSCH_DEGENERATE", "점 3개 미만 또는 공선")
    n = X0.shape[0]
    A = np.zeros((3 * n, 6))
    for i in range(3):
        A[i::3, i] = 1.0
        w = np.zeros(3)
        w[i] = 1.0
        A[:, 3 + i] = np.cross(w, P).ravel()
    coef, *_ = np.linalg.lstsq(A, u.ravel(), rcond=None)
    u_rel = (u.ravel() - A @ coef).reshape(n, 3)
    return u_rel, coef[:3], coef[3:]
