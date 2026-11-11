"""v0.18.0 STEP_GRAPH 합성 STEP(계약 esl_step_graph.md §8): beadgraph H6 픽스처의 평면 형상 나무를 OCC 시트로.

``synth_h6.build_tree`` → ``domain_and_creases``·``faces_of``(주름선으로 나뉜 평면 다각형) → 노드화된 주름선 사슬마다 높이를 올린
꼭짓점을 잇는 OCC 직선 모서리(면끼리 같은 모서리 태그 공유) → 면: 올린 꼭짓점이 한 평면이면 평면 면, 아니면 경계 채움
(``addSurfaceFilling``) → STEP. 정답 = ``synth_h6.ground_truth(mesh, root)``(형상 기준 — 어떤 메시에도). gmsh·shapely 필요
(없으면 시험 skip). ``h6_step(path)`` 은 같은 gmsh 판에서 결정적이며, 시험은 세션 캐시 폴더(ESL_SG_CACHE)를 쓴다.
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "packages", "beadgraph", "src")
if PKG not in sys.path:
    sys.path.insert(0, PKG)

PLANE_TOL = 1e-4


def _key(c):
    return (round(float(c[0]), 5), round(float(c[1]), 5))


def _chains(L):
    import shapely
    merged = shapely.line_merge(L)
    geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    return [np.asarray(g.coords)[:, :2] for g in geoms]


def h6_step(path: str) -> str:
    """H6 시트 STEP(1200 × 675 mm, 면 246 — 평면 + 경계 채움)."""
    from beadgraph.testing import synth_h6 as s6
    root, _ = s6.build_tree()
    dom, L = s6.domain_and_creases(root)
    faces = s6.faces_of(dom, L)
    chains = _chains(L)
    nodes = {}
    for ch in chains:
        for c in (ch[0], ch[-1]):
            nodes[_key(c)] = True
    allpts = np.unique(np.concatenate(chains), axis=0)
    z, *_ = s6.evaluate(root, allpts)
    zmap = {_key(p): float(v) for p, v in zip(allpts, z)}

    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        pid = {}

        def P(c):
            k = _key(c)
            if k not in pid:
                pid[k] = occ.addPoint(k[0], k[1], zmap.get(k, 0.0))
            return pid[k]
        lid = {}

        def line(a, b):
            k = (min(a, b), max(a, b))
            if k not in lid:
                lid[k] = occ.addLine(k[0], k[1])
            return lid[k] if a == k[0] else -lid[k]

        def loop(coords):
            cs = [c for c in np.asarray(coords)[:-1, :2]]
            ids = [P(c) for c in cs]
            segs = [line(a, b) for a, b in zip(ids, ids[1:] + ids[:1]) if a != b]
            return occ.addCurveLoop(segs), cs
        n_plane = n_fill = 0
        for f in faces:
            import shapely
            f = shapely.geometry.polygon.orient(f, 1.0)
            ext, cs = loop(f.exterior.coords)
            p3 = np.array([[c[0], c[1], zmap.get(_key(c), 0.0)] for c in cs])
            A = np.c_[p3[:, :2], np.ones(len(p3))]
            coef = np.linalg.lstsq(A, p3[:, 2], rcond=None)[0]
            planar = float(np.abs(A @ coef - p3[:, 2]).max()) < PLANE_TOL
            if planar:
                inner = [loop(r.coords)[0] for r in f.interiors]
                occ.addPlaneSurface([ext] + inner)
                n_plane += 1
            else:
                occ.addSurfaceFilling(ext)
                n_fill += 1
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


def h6_truth(mesh: dict) -> dict:
    """사다리 메시 → beadgraph.testing.evaluate_h6 가 읽는 fx(픽스처 형식 + 정답)."""
    from beadgraph.testing import synth_h6 as s6
    C = np.asarray(mesh["conn"], np.int64)
    m = {"x0": np.asarray(mesh["x0"], np.float64), "conn": C,
         "fixed_nodes": fixed_nodes(mesh), "elem_type": np.asarray(mesh["elem_type"])}
    return s6.fixture_arrays(m)


def fixed_nodes(mesh: dict) -> np.ndarray:
    """H6 고정 구멍 둘레 노드(평면 거리 < 0.05 mm — synth_h6.build 와 같은 규칙) 인덱스."""
    import shapely
    from beadgraph.testing import synth_h6 as s6
    root, _ = s6.build_tree()
    X = np.asarray(mesh["x0"], np.float64)
    pts = shapely.points(X[:, 0], X[:, 1])
    fx = []
    for f in root.walk():
        for g, _t, fixed in f.holes:
            if fixed:
                fx.append(np.flatnonzero(shapely.distance(pts, g.boundary) < 0.05))
    return np.unique(np.concatenate(fx)) if fx else np.zeros(0, np.int64)


def esl_mesh(X, C) -> dict:
    """(x0, conn tri 4th = -1) → esl 메시 dict(노드·요소 ID 1부터)."""
    C = np.asarray(C, np.int64)
    n, m = X.shape[0], C.shape[0]
    return {"node_id": np.arange(1, n + 1, dtype=np.int64), "x0": np.asarray(X, np.float64),
            "elem_id": np.arange(1, m + 1, dtype=np.int64), "elem_type": np.where(C[:, 3] >= 0, 4, 3).astype(np.int8),
            "conn": C, "elem_pid": np.ones(m, np.int64), "elem_mid": np.ones(m, np.int64), "thickness": np.ones(m),
            "E": np.full(m, 205000.0), "nu": np.full(m, 0.3)}


def tri_split(mesh: dict) -> dict:
    """사각형을 짧은 대각선으로 삼각형 2개씩(§0.1 삼각형 대리)."""
    X = np.asarray(mesh["x0"], np.float64)
    C = np.asarray(mesh["conn"], np.int64)
    q = C[:, 3] >= 0
    out = [np.c_[C[~q, :3], -np.ones((~q).sum(), np.int64)]]
    Q = C[q]
    d02 = np.linalg.norm(X[Q[:, 0]] - X[Q[:, 2]], axis=1)
    d13 = np.linalg.norm(X[Q[:, 1]] - X[Q[:, 3]], axis=1)
    a = d02 <= d13
    t1 = np.where(a[:, None], Q[:, [0, 1, 2]], Q[:, [0, 1, 3]])
    t2 = np.where(a[:, None], Q[:, [0, 2, 3]], Q[:, [1, 2, 3]])
    neg = -np.ones((Q.shape[0], 1), np.int64)
    out += [np.c_[t1, neg], np.c_[t2, neg]]
    return esl_mesh(X, np.concatenate(out))


def add_extra(mesh: dict, *, ext: float = 20.0, z1: float = 30.0, y0: float = -1e9, y1: float = 1e9, h: float = 3.0):
    """V-SG-4b 추가 형상(메시 수준 — 주 시트 노드·요소 불변, 뒤에 덧붙임): 오른쪽 끝(x 최대 — H6 = 탭 x 1220) 노드 중 y0..y1 에서
    +x 로 ext 만큼 평면 띠 → 끝에서 z 0 → z1 수직 벽(사각 요소). 주 시트와 노드 공유(한 연결 성분)."""
    X = np.asarray(mesh["x0"], np.float64)
    C = np.asarray(mesh["conn"], np.int64)
    xm = X[:, 0].max()
    edge = np.flatnonzero((np.abs(X[:, 0] - xm) < 1e-6) & (X[:, 1] >= y0) & (X[:, 1] <= y1))
    edge = edge[np.argsort(X[edge, 1])]
    cols = [edge]
    newX = []
    nx = max(2, int(round(ext / h)))
    nz = max(2, int(round(z1 / h)))
    base = X.shape[0]
    k = 0
    for i in range(1, nx + 1):
        P = X[edge].copy()
        P[:, 0] = xm + ext * i / nx
        newX.append(P)
        cols.append(base + k + np.arange(edge.size))
        k += edge.size
    top = newX[-1]
    for j in range(1, nz + 1):
        P = top.copy()
        P[:, 2] = top[:, 2] + z1 * j / nz
        newX.append(P)
        cols.append(base + k + np.arange(edge.size))
        k += edge.size
    quads = []
    for a, b in zip(cols, cols[1:]):
        for t in range(edge.size - 1):
            quads.append([a[t], b[t], b[t + 1], a[t + 1]])
    X2 = np.concatenate([X] + newX)
    C2 = np.concatenate([C, np.asarray(quads, np.int64)])
    out = esl_mesh(X2, C2)
    out["node_id"][:X.shape[0]] = np.asarray(mesh["node_id"])
    out["node_id"][X.shape[0]:] = int(np.asarray(mesh["node_id"]).max()) + 1 + np.arange(X2.shape[0] - X.shape[0])
    out["elem_id"][:C.shape[0]] = np.asarray(mesh["elem_id"])
    out["elem_id"][C.shape[0]:] = int(np.asarray(mesh["elem_id"]).max()) + 1 + np.arange(C2.shape[0] - C.shape[0])
    return out


# ---------------------------------------------------------------- 가벼운 대역(해석 없이 — 큰 H6 메시용)
class LightEntry:
    """라이브러리 항목 대역(해석 없음): meta{entry_id, frame, grid, model.inch, esl.supports}, raw(A part 메시),
    summary(셀 합력 — 판 법선 방향 균일 압력 + 한쪽 모서리 굽힘)."""

    def __init__(self, eid, mesh, inch=55, nx=24, ny=14):
        from esl.library import normalize as nz
        X = np.asarray(mesh["x0"], np.float64)
        fr = nz.frame(X, None, mesh["conn"], mesh["elem_type"])
        n = np.asarray(fr["n"], np.float64)
        a = (X - np.asarray(fr["origin"])) @ np.asarray(fr["e_xi"])
        F = np.outer(1.0 + (a - a.min()) / max(np.ptp(a), 1e-9), n)
        F -= F.mean(axis=0)
        gs = nz.grid_summary(X, F, nx, ny, fr, top_n=5, node_id=mesh["node_id"])
        self.summary = {k: gs[k] for k in ("cell_F_loc", "cell_M_loc", "cell_F", "cell_M")}
        self.raw = {**{k: mesh[k] for k in mesh}, "f": F}
        self.meta = {"entry_id": eid, "frame": fr, "grid": {"nx": nx, "ny": ny}, "esl": {"supports": []},
                     "model": {"inch": inch}}

    def summary_for_mapping(self):
        return {**self.summary, "nx": self.meta["grid"]["nx"], "ny": self.meta["grid"]["ny"], "frame": self.meta["frame"]}


def h6_fixture_mesh():
    from beadgraph.testing import conformance as cf
    fx = cf.load_fixture("h6")
    return esl_mesh(fx["x0"], fx["conn"]), fx


def h6_clusters(mesh, fx) -> list:
    """고정 구멍마다 둘레 노드 인덱스 묶음(정답 고정 구멍 중심에 가장 가까운 것)."""
    X = np.asarray(mesh["x0"])
    F = np.asarray(fx["fixed"], np.int64)
    hx = fx["exp_hole_xy"][fx["exp_hole_fixed"]]
    lab = np.argmin(np.linalg.norm(X[F, None, :2] - hx[None], axis=2), axis=1)
    return [F[lab == k] for k in range(hx.shape[0]) if (lab == k).any()]
