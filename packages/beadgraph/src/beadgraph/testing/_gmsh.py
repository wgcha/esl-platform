"""gmsh extraction + clean-up for the synthetic generators ([synth] extra only — gmsh, shapely). Standalone (no esl):
2D first-order elements -> (X, conn 0-based with tri 4th = -1), degenerate elements dropped, unused nodes removed,
element winding made consistent and facing ``normal_ref``."""
from __future__ import annotations

import numpy as np


def extract(gmsh):
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags, dtype=np.int64)
    X = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    o = np.argsort(tags, kind="stable")
    tags, X = tags[o], X[o]
    etypes, etags, enodes = gmsh.model.mesh.getElements(2)
    rows, eg = [], []
    for t, tg, nd in zip(etypes, etags, enodes):
        k = {2: 3, 3: 4}[int(t)]
        nd = np.asarray(nd, dtype=np.int64).reshape(-1, k)
        c = np.full((nd.shape[0], 4), -1, dtype=np.int64)
        c[:, :k] = nd
        rows.append(c)
        eg.append(np.asarray(tg, dtype=np.int64))
    C, EG = np.concatenate(rows), np.concatenate(eg)
    C = C[np.argsort(EG, kind="stable")]
    pos = np.searchsorted(tags, np.where(C >= 0, C, tags[0]))
    return X, np.where(C >= 0, pos, -1)


def clean(X, conn, normal_ref=(0.0, 0.0, 1.0)):
    from beadgraph.topo import Topo
    k = np.where(conn[:, 3] >= 0, 4, 3)
    dup = np.zeros(conn.shape[0], bool)
    for a in range(4):
        for b in range(a + 1, 4):
            dup |= (b < k) & (conn[:, a] == conn[:, b])
    conn = conn[~dup]
    used = np.unique(conn[conn >= 0])
    remap = -np.ones(X.shape[0], np.int64)
    remap[used] = np.arange(used.size)
    conn = np.where(conn >= 0, remap[np.maximum(conn, 0)], -1)
    X = X[used]
    t = Topo(X, conn)
    raw = t.normal.copy()
    t2 = Topo(X, conn)
    # Topo orients consistently; reverse elements whose own winding disagrees with the consistent field
    nref = np.asarray(normal_ref, float)
    cons = t2.normal * np.sign((t2.normal * t2.area[:, None]).sum(axis=0) @ nref or 1.0)
    flip = np.einsum("ij,ij->i", raw, cons) < 0
    c2 = conn.copy()
    q = c2[:, 3] >= 0
    c2[flip & q] = c2[flip & q][:, [0, 3, 2, 1]]
    tq = flip & ~q
    c2[tq, :3] = c2[tq][:, [0, 2, 1]]
    return X, c2
