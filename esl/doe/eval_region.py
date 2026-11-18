"""평가 영역 노드 마스크 — 보조 지표 umax(평가 영역) (계약 docs/contracts/esl_fint.md §6.2, D-0.24.0-BF-16).

part = 대상 파트 전 노드, exclude_free_edges = 자유 경계(한 요소에만 속한 변) 노드에서 거리 ≤ d 인 노드 제외, box = 좌표 상자 합집합 안.
모드 무관 독립 모듈(AGENTS.md): esl.doe 다른 모듈 import 없음, 파일 IO·설정 해석 없음 — 값은 인수.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

EVAL_MODES = ("part", "exclude_free_edges", "box")


def free_edge_nodes(conn, elem_type) -> np.ndarray:
    """자유 경계 노드 인덱스(정렬): 한 요소에만 속한 변의 끝 노드. conn (E,4) 노드 행 인덱스(트라이 4번째 −1), elem_type 3|4."""
    C = np.asarray(conn, dtype=np.int64)
    q = np.asarray(elem_type).astype(np.int64) == 4
    e = [C[:, [0, 1]], C[:, [1, 2]], C[q][:, [2, 3]], C[q][:, [3, 0]], C[~q][:, [2, 0]]]
    E = np.sort(np.concatenate(e, axis=0), axis=1)
    E = E[(E >= 0).all(axis=1)]
    if not E.size:
        return np.zeros(0, dtype=np.int64)
    u, cnt = np.unique(E, axis=0, return_counts=True)
    return np.unique(u[cnt == 1].reshape(-1))


def eval_mask(x0, conn, elem_type, mode: str = "part", free_edge_mm: float = 10.0, boxes=()) -> np.ndarray:
    """평가 영역 노드 bool (N,): part = 전 노드, exclude_free_edges = 자유 경계 노드에서 거리 ≤ free_edge_mm 인 노드 제외,
    box = boxes([{lo: [x,y,z], hi: [x,y,z]}]) 합집합 안 노드만(경계 포함). 순수·결정적."""
    X = np.asarray(x0, dtype=np.float64)
    N = X.shape[0]
    if mode == "part":
        return np.ones(N, bool)
    if mode == "exclude_free_edges":
        fe = free_edge_nodes(conn, elem_type)
        if not fe.size:
            return np.ones(N, bool)
        from scipy.spatial import cKDTree
        d, _ = cKDTree(X[fe]).query(X, k=1)
        return d > float(free_edge_mm)
    if mode == "box":
        mk = np.zeros(N, bool)
        for b in boxes or ():
            lo = np.asarray(b["lo"], dtype=np.float64).reshape(3)
            hi = np.asarray(b["hi"], dtype=np.float64).reshape(3)
            mk |= np.all((X >= lo) & (X <= hi), axis=1)
        return mk
    raise EslError("CONFIG_INVALID", f"rank.eval_region {mode} — {list(EVAL_MODES)}")
