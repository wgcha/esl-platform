"""v0.25.2 #96 재현 합성(계약 esl_tstar_manual_jig_force.md §0.3·§10.3 — V-0252-21~23).

#96 형상 d001 = STEP 이 중립면 한 장이 아니라 판 앞뒷면 두 장(간격 = 두께 t) + 체결 위치 어긋남(Case 체결부 6곳 중 4곳 자리에 구멍 —
와셔 면 없음). 두 장은 바깥 둘레 벽 요소로 이어져 한 덩어리(솔리드 STEP 의 바깥 면 흉내 — 요소 수 ≈ 2배).
"""
from __future__ import annotations

import numpy as np

import synth_jig_grid as G


def _free_edges(conn, et):
    q = np.asarray(et).astype(np.int64) == 4
    e = []
    for k, (c, isq) in enumerate(zip(np.asarray(conn), q)):
        nodes = [int(x) for x in (c if isq else c[:3])]
        for i in range(len(nodes)):
            a, b = nodes[i], nodes[(i + 1) % len(nodes)]
            e.append((min(a, b), max(a, b), a, b))
    cnt = {}
    for a, b, _o0, _o1 in e:
        cnt[(a, b)] = cnt.get((a, b), 0) + 1
    return [(o0, o1) for a, b, o0, o1 in e if cnt[(a, b)] == 1]


def double_sheet(mesh: dict, t: float, *, wall: bool = True) -> dict:
    """판 메시(판 평면 y = 0) → 앞뒷면 두 장(y = ±t/2, 같은 요소·두께) + (wall) 바깥 둘레 벽 쿼드. 노드 ID = 원래·+10⁶."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    N = X.shape[0]
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int8)
    top = X + np.array([0.0, 0.5 * t, 0.0])
    bot = X - np.array([0.0, 0.5 * t, 0.0])
    c2 = np.where(conn >= 0, conn + N, -1)
    c2 = np.where((et == 4)[:, None], c2[:, [0, 3, 2, 1]], np.c_[c2[:, [0, 2, 1]], c2[:, 3:]])   # 뒷면 = 뒤집은 방향
    walls = []
    if wall:
        x0, x1 = X[:, 0].min(), X[:, 0].max()
        z0, z1 = X[:, 2].min(), X[:, 2].max()
        for a, b in _free_edges(conn, et):
            pa, pb = X[a], X[b]
            outer = any(abs(pa[i] - v) < 1e-9 and abs(pb[i] - v) < 1e-9 for i, v in ((0, x0), (0, x1), (2, z0), (2, z1)))
            if outer:
                walls.append([a, b, b + N, a + N])
    W = np.asarray(walls, dtype=np.int64).reshape(-1, 4)
    allc = np.concatenate([conn, c2, W], axis=0)
    ne = allc.shape[0]
    ett = np.concatenate([et, et, np.full(W.shape[0], 4, np.int8)])

    def rep(k, v=None):
        a = np.asarray(mesh[k])
        return np.concatenate([a, a, np.full(W.shape[0], a[0] if v is None else v, dtype=a.dtype)])
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    return {"node_id": np.r_[nid, nid + 1_000_000], "x0": np.concatenate([top, bot], axis=0), "conn": allc,
            "elem_type": ett, "elem_id": 1 + np.arange(ne, dtype=np.int64), "elem_pid": rep("elem_pid"),
            "elem_mid": rep("elem_mid"), "thickness": rep("thickness"), "E": rep("E"), "nu": rep("nu")}


def issue96_shape(h: float = 5.0, missing=(0, 2, 3, 5)) -> dict:
    """#96 꼴 형상 메시: 볼트 missing 자리에 구멍(r 13 — 와셔 면 없음) + 판 앞뒷면 두 장(t = PROPS t)."""
    m = G.holes(G.plate(h, node_base=100001), list(missing))
    return double_sheet(m, float(G.PROPS["t"]))
