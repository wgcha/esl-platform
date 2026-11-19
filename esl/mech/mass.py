"""쉘 요소 면적·법선과 집중질량 (계약 esl_bforce.md §3 — D-0.24.0-BF-3).

면적·법선 식은 지그(``esl.doe.jig.node_weights``)와 한 곳: 트라이 = 변 (1−0)×(2−0), 쿼드 = 대각선 (2−0)×(3−1)
(ShellModel 국부계와 같음 — 쿼드 면적 = ½‖d₁×d₂‖). 독립 모듈(esl.doe import 없음, 파일 IO·설정 해석 없음).
"""
from __future__ import annotations

import numpy as np


def elem_area_normal(X, conn, et) -> tuple[np.ndarray, np.ndarray]:
    """요소 면적 A(E,)·단위 법선(E,3)(면적 0 = 법선 0). conn (E,4) 노드 행 인덱스, et 3|4."""
    X = np.asarray(X, dtype=np.float64)
    conn = np.asarray(conn, dtype=np.int64)
    et = np.asarray(et).astype(np.int64)
    E = conn.shape[0]
    q = et == 4
    v = np.empty((E, 3))
    p0, p1, p2 = X[conn[:, 0]], X[conn[:, 1]], X[conn[:, 2]]
    v[~q] = np.cross(p1[~q] - p0[~q], p2[~q] - p0[~q])
    if q.any():
        p3 = X[conn[q, 3]]
        v[q] = np.cross(p2[q] - p0[q], p3 - p1[q])
    nrm = np.linalg.norm(v, axis=1)
    A = 0.5 * nrm
    m = np.divide(v, nrm[:, None], out=np.zeros_like(v), where=nrm[:, None] > 0)
    return A, m


def lumped_mass(mesh, rho_e) -> np.ndarray:
    """집중질량 m_n = Σ_e ρ_e·t_e·A_e / nn_e (N,) — 질량 합 = Σ ρ t A 정확. rho_e = 스칼라 또는 (E,)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    N, E = X.shape[0], conn.shape[0]
    A, _ = elem_area_normal(X, conn, et)
    q = et == 4
    t = np.broadcast_to(np.asarray(mesh["thickness"], dtype=np.float64), (E,))
    rho = np.broadcast_to(np.asarray(rho_e, dtype=np.float64), (E,))
    me = rho * t * A / np.where(q, 4.0, 3.0)
    rows = np.concatenate([conn[:, 0], conn[:, 1], conn[:, 2], conn[q, 3]])
    eidx = np.concatenate([np.arange(E)] * 3 + [np.flatnonzero(q)])
    return np.bincount(rows, weights=me[eidx], minlength=N)
