"""Design checks on a morphed node array (BG-D-32..34): outside-zero, achieved depth / width, island residual, and the
inverted-element count (normal flip > flip_deg or a non-positive quad corner — same rule as esl quality)."""
from __future__ import annotations

import numpy as np

from . import _util as U
from .morph import _skeleton_dist


def changed(basis, values) -> list:
    out = []
    for v in basis:
        if v["name"] in values and float(values[v["name"]]) != float(v["nominal"]):
            out.append(v)
    return out


def outside_moved(x0, x, basis, values, tol: float) -> dict:
    """max displacement of nodes outside the union of the changed variables' allowed zones."""
    x0 = np.asarray(x0, np.float64)
    ch = changed(basis, values)
    allowed = np.zeros(x0.shape[0], bool)
    for v in ch:
        allowed[np.asarray(v["zone"], np.int64)] = True
    d = np.linalg.norm(np.asarray(x, np.float64) - x0, axis=1)
    d[allowed] = 0.0
    n = int((d > tol).sum())
    return {"n": n, "max_mm": float(d.max()) if d.size else 0.0, "vars": sorted(v["name"] for v in ch),
            "failed": n > 0}


def basis_leak(basis) -> list[dict]:
    """BG-D-32: supp(B_v) ⊆ zone(v) for every variable -> list of {var, n, max_mm} violations."""
    out = []
    for v in basis:
        bad = ~np.isin(np.asarray(v["idx"], np.int64), np.asarray(v["zone"], np.int64))
        if bad.any():
            out.append({"code": "BG_BASIS_LEAK", "var": v["name"], "n": int(bad.sum()),
                        "max_mm": float(np.linalg.norm(np.asarray(v["vec"])[bad], axis=1).max())})
    return out


def achieved(graph, labels, nodes, x, basis, values, elems=None) -> dict:
    """D: max |Δh − s·Δv| over the achieved nodes; W: |ΔW_measured − Δv| (entry nodes at full ramp)."""
    x0 = np.asarray(nodes, np.float64)
    x = np.asarray(x, np.float64)
    n0 = np.asarray(graph["frame"]["n0"], float)
    out = {}
    M = None
    for v in changed(basis, values):
        dv = float(values[v["name"]]) - float(v["nominal"])
        idx = np.asarray(v["info"].get("achieved_idx", []), np.int64)
        if idx.size == 0:
            out[v["name"]] = None
            continue
        if v["kind"] == "D":
            dh = (x[idx] - x0[idx]) @ n0
            out[v["name"]] = float(np.abs(dh - v["info"]["sign"] * dv).max())
        else:
            if M is None:
                M = _PlanOnly(graph, x0)
            d0, _n, _i = _skeleton_dist(M, v["segs"], M.plan(x0[idx]))
            d1, _n, _i = _skeleton_dist(M, v["segs"], M.plan(x[idx]))
            out[v["name"]] = float(abs(2.0 * (np.median(d1) - np.median(d0)) - dv))
    return out


class _PlanOnly:
    def __init__(self, graph, X):
        fr = graph["frame"]
        self.e1, self.e2 = np.asarray(fr["e1"], float), np.asarray(fr["e2"], float)
        self.origin = np.asarray(fr.get("origin", [0.0, 0.0]), float)
        self.segs = {s["id"]: s for s in graph["segments"]}

    def plan(self, X):
        return np.c_[X @ self.e1, X @ self.e2] - self.origin


def island_residual(labels, nodes, x, basis, values, elems) -> float:
    """max |u − mean u| over the nodes of each island moved by a changed variable (rigid translation)."""
    if elems is None:
        return 0.0
    x0 = np.asarray(nodes, np.float64)
    u = np.asarray(x, np.float64) - x0
    C = np.asarray(elems, np.int64)
    isl = np.asarray(labels["island"], np.int64)
    ids = set()
    held = set()
    for v in changed(basis, values):
        ids |= set(v["info"].get("islands", [])) - set(v["info"].get("straddle", []))
        ids |= set(v["info"].get("band_islands", []))
        held |= {w["island"] for w in v["info"]["warnings"] if w["code"] == "BG_ISLAND_HELD"}
    worst = 0.0
    for i in sorted(ids - held):
        nd = np.unique(C[isl == i])
        nd = nd[nd >= 0]
        if nd.size == 0:
            continue
        uu = u[nd]
        worst = max(worst, float(np.linalg.norm(uu - uu.mean(axis=0), axis=1).max()))
    return worst


def _quad_jacobian(X, Cq):
    """scaled bilinear Jacobian on the element's own projected plane (2x2 Gauss points) — min / max (same rule as esl
    ``mesh_quality.element_metrics``; negative = inverted)."""
    P = X[Cq]
    p0, p1, p2, p3 = (P[:, i] for i in range(4))
    n = np.cross(p2 - p0, p3 - p1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    e1 = (p1 - p0) - np.einsum("ij,ij->i", p1 - p0, n)[:, None] * n
    e1 /= np.maximum(np.linalg.norm(e1, axis=1, keepdims=True), 1e-300)
    e2 = np.cross(n, e1)
    R = P - P.mean(axis=1, keepdims=True)
    xy = np.stack([np.einsum("mkj,mj->mk", R, e1), np.einsum("mkj,mj->mk", R, e2)], axis=2)
    g = 1.0 / np.sqrt(3.0)
    dets = []
    for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
        dxi = 0.25 * np.array([-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)])
        deta = 0.25 * np.array([-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)])
        a = np.einsum("k,mkj->mj", dxi, xy)
        b = np.einsum("k,mkj->mj", deta, xy)
        dets.append(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    D = np.stack(dets, axis=1)
    return D.min(axis=1) / np.maximum(np.abs(D).max(axis=1), 1e-300)


def inverted_count(nodes, x, elems, flip_deg: float = 60.0) -> int:
    """elements with a moved node that are inverted: quad Jacobian <= 0 or element normal rotated > flip_deg."""
    X0 = np.asarray(nodes, np.float64)
    X1 = np.asarray(x, np.float64)
    C = np.asarray(elems, np.int64)
    q = C[:, 3] >= 0
    moved = np.linalg.norm(X1 - X0, axis=1) > 1e-9
    am = moved[C[:, 0]] | moved[C[:, 1]] | moved[C[:, 2]] | (q & moved[np.where(q, C[:, 3], 0)])
    C, q = C[am], q[am]
    if C.shape[0] == 0:
        return 0

    def normals(X):
        a, b, c = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        n = np.cross(b - a, c - a)
        d = X[np.where(q, C[:, 3], C[:, 2])]
        n[q] = np.cross(c[q] - a[q], d[q] - b[q])
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]
    rot = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", normals(X0), normals(X1)), -1, 1)))
    inv = rot > flip_deg
    if q.any():
        inv[q] |= _quad_jacobian(X1, C[q]) <= 0.0
    return int(inv.sum())


def check(graph, labels, nodes, x, basis, values, cfg=None, elems=None) -> dict:
    c = U.merged_cfg(cfg)
    tol = float(c["morph"]["outside_tol_mm"])
    out = outside_moved(nodes, x, basis, values, tol)
    return {"outside": {k: out[k] for k in ("n", "max_mm", "vars")}, "outside_failed": out["failed"],
            "achieved": achieved(graph, labels, nodes, x, basis, values),
            "island_residual_mm": island_residual(labels, nodes, x, basis, values, elems),
            "inverted": inverted_count(nodes, x, elems) if elems is not None else None}
