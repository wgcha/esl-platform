"""지지점 선택 (계약 esl_core.md §4, esl.md §6.6).

pca_corners: 초기좌표 PCA 평면에서 정규화 투영 (â, b̂) 의 4방향 극점.
pick_321: 후보 중 삼각형 면적 최대 3점 → 3-2-1 정정 구속(강체 6모드만 구속).
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

from esl.errors import EslError

_SIGNS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
DEGENERATE_RATIO = 1e-6


def _orient(v):
    """부호 규약: 절대값 최대 성분이 양수."""
    return v if v[np.argmax(np.abs(v))] >= 0 else -v


def pca_corners(X0):
    X0 = np.asarray(X0, dtype=np.float64)
    if X0.ndim != 2 or X0.shape[1] != 3 or X0.shape[0] < 4:
        raise EslError("SUPPORT_DEGENERATE", "PCA 꼭지점: 노드 4개 이상 필요")
    o = X0.mean(axis=0)
    P = X0 - o
    _, s, Vt = np.linalg.svd(P, full_matrices=False)
    if s[1] <= DEGENERATE_RATIO * s[0]:
        raise EslError("SUPPORT_DEGENERATE", "노드가 공선 — 면내 주축 2개를 정할 수 없음")
    e1 = _orient(Vt[0])
    e2 = _orient(Vt[1])
    n = np.cross(e1, e2)
    a = P @ e1
    b = P @ e2

    def norm(v):
        lo, hi = v.min(), v.max()
        return 2.0 * (v - lo) / (hi - lo) - 1.0

    ah, bh = norm(a), norm(b)
    idx: list[int] = []
    for s1, s2 in _SIGNS:
        score = s1 * ah + s2 * bh
        order = np.lexsort((np.arange(score.size), -score))   # 내림차순, 동률은 낮은 인덱스
        for k in order:
            if int(k) not in idx:
                idx.append(int(k))
                break
    return {
        "idx": idx,
        "plane": {"origin": o.tolist(), "e1": e1.tolist(), "e2": e2.tolist(), "n": n.tolist()},
    }


def _rigid_matrix(X, assign):
    """구속 dof 행 × 강체 6모드 열(병진 3, 중심 기준 회전 3 / 길이 L 무차원화)."""
    ctr = X.mean(axis=0)
    L = max(float(np.max(np.linalg.norm(X - ctr, axis=1))), 1e-300)
    rows = []
    for p, dofs in zip(X, assign):
        r = (p - ctr) / L
        for d in dofs:
            row = np.zeros(6)
            row[d] = 1.0
            for i in range(3):
                w = np.zeros(3)
                w[i] = 1.0
                row[3 + i] = np.cross(w, r)[d]
            rows.append(row)
    return np.array(rows)


def pick_321(X0, cand_idx):
    """→ [(node_idx, "123"), (node_idx, "ij"), (node_idx, "k")] (dof 는 1-based 문자열)."""
    X0 = np.asarray(X0, dtype=np.float64)
    cand = [int(c) for c in cand_idx]
    if len(set(cand)) < 3:
        raise EslError("SUPPORT_DEGENERATE", f"지지 후보 {len(set(cand))}개 < 3")
    if min(cand) < 0 or max(cand) >= X0.shape[0]:
        raise EslError("INPUT_INVALID", "지지 후보 인덱스 범위 밖")
    uniq = list(dict.fromkeys(cand))
    best, best_area = None, -1.0
    for tri in combinations(range(len(uniq)), 3):
        p = X0[[uniq[i] for i in tri]]
        area = 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0]))
        if area > best_area * (1 + 1e-12):
            best, best_area = tri, area
    nodes = [uniq[i] for i in best]
    X = X0[nodes]
    best_combo, best_ratio = None, -1.0
    for k2 in range(3):                 # 둘째 점: 축 k2 를 뺀 2성분
        two = tuple(d for d in range(3) if d != k2)
        for k3 in range(3):             # 셋째 점: 1성분
            A = _rigid_matrix(X, [(0, 1, 2), two, (k3,)])
            s = np.linalg.svd(A, compute_uv=False)
            ratio = s[-1] / s[0]
            if ratio > best_ratio * (1 + 1e-12):
                best_combo, best_ratio = (two, k3), ratio
    if best_ratio < DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 구속행렬 특이 (σmin/σmax={best_ratio:.2e}, 후보 공선?)")
    two, k3 = best_combo
    return [
        (nodes[0], "123"),
        (nodes[1], "".join(str(d + 1) for d in two)),
        (nodes[2], str(k3 + 1)),
    ]
