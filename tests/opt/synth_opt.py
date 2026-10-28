"""OPT 코어 시험용 합성 도구: XZ 평면 판(법선 Y, TV 후면 규약), 구멍, 자기평형 하중, 가짜 라이브러리 항목."""
from __future__ import annotations

import numpy as np

from esl.library import mapping as mp
from esl.library import normalize as nz
from esl.mech import supports as msup
from esl.mech.shell import ShellModel
from esl.opt import settings
from esl.opt.target import Target

E_STEEL, NU = 2.1e5, 0.3


def plate(nx=12, ny=8, Lx=300.0, Lz=200.0, holes=(), n_tria_cols=0, node_base=1, elem_base=1, pid=10, t=1.5,
          bow=0.0):
    """XZ 평면 판. holes = [(i0, i1, j0, j1)] 셀 범위를 비워 구멍. bow: 면외(Y) 살짝 휨(mm)."""
    xs = np.linspace(0.0, Lx, nx + 1)
    zs = np.linspace(0.0, Lz, ny + 1)
    X = np.array([[x, bow * np.sin(np.pi * x / Lx) * np.sin(np.pi * z / Lz), z] for x in xs for z in zs])
    nid = lambda i, j: i * (ny + 1) + j   # noqa: E731
    conn, et = [], []
    for i in range(nx):
        for j in range(ny):
            if any(a <= i < b and c <= j < d for a, b, c, d in holes):
                continue
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if i < n_tria_cols:
                conn += [[a, b, c, -1], [a, c, d, -1]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    conn = np.array(conn, dtype=np.int64)
    used = np.unique(conn[conn >= 0])
    remap = -np.ones(X.shape[0], dtype=np.int64)
    remap[used] = np.arange(used.size)
    conn = np.where(conn >= 0, remap[np.maximum(conn, 0)], -1)
    X = X[used]
    ne = conn.shape[0]
    return {"node_id": node_base + np.arange(X.shape[0], dtype=np.int64), "x0": X,
            "elem_id": elem_base + np.arange(ne, dtype=np.int64), "elem_type": np.array(et, dtype=np.int8),
            "conn": conn, "elem_pid": np.full(ne, pid, dtype=np.int64), "elem_mid": np.full(ne, 1, dtype=np.int64),
            "thickness": np.full(ne, t), "E": np.full(ne, E_STEEL), "nu": np.full(ne, NU)}


def supports_321(mesh):
    X = mesh["x0"]
    pc = msup.pca_corners(X)
    return [(int(mesh["node_id"][i]), d) for i, d in msup.pick_321(X, pc["idx"])]


def equilibrate(X, F):
    ctr = X.mean(axis=0)
    tF, tM = mp.resultants(X, F, ctr)
    d, _ = mp.min_norm_forces(X, -tF, -tM, ctr)
    return F + d


def load(mesh, kind="bend", amp=1.0, seed=0):
    """자기평형 절점 하중. kind: bend(면외 P2), twist(면외 s·t), dent(국부 집중), rand(무작위)."""
    X = mesh["x0"]
    fr = nz.frame(X, None, mesh["conn"], mesh["elem_type"])
    loc = nz.local_coords(fr, X)
    s, t = 2 * loc[:, 0] - 1, 2 * loc[:, 1] - 1
    n = np.asarray(fr["n"])
    A = nz.node_areas(X, mesh["conn"], mesh["elem_type"])
    if kind == "bend":
        q = 0.5 * (3 * s ** 2 - 1)
    elif kind == "twist":
        q = s * t
    elif kind == "dent":
        q = np.exp(-((s - 0.3) ** 2 + (t + 0.2) ** 2) / 0.01)
    elif kind == "rand":
        q = np.random.default_rng(seed).normal(size=s.size)
    else:
        raise ValueError(kind)
    F = amp * (q * A)[:, None] * n[None, :]
    return equilibrate(X, F)


class FakeEntry:
    """라이브러리 항목 대역: meta(entry_id, frame, esl.supports, model.inch, grid), raw, summary."""

    def __init__(self, entry_id, mesh, F, supports, inch=None, scene=None, mode=None, nx=24, ny=14):
        self.entry_id = entry_id
        X = mesh["x0"]
        fr = nz.frame(X, None, mesh["conn"], mesh["elem_type"])
        sm = ShellModel(X, mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], backend="superlu")
        nid = mesh["node_id"]
        spc = [(int(np.searchsorted(nid, n)), d) for n, d in supports]
        u, _ = sm.solve(F, spc)
        self.raw = {**{k: mesh[k] for k in mesh}, "f": np.asarray(F, float), "u_rel": u[:, :3]}
        gs = nz.grid_summary(X, F, nx, ny, fr, top_n=5, node_id=nid)
        self.summary = {k: gs[k] for k in ("cell_F_loc", "cell_M_loc", "cell_F", "cell_M")}
        self.meta = {"entry_id": entry_id, "frame": fr, "grid": {"nx": nx, "ny": ny},
                     "esl": {"supports": [{"node_id": n, "dof": d} for n, d in supports]},
                     "model": {"inch": inch}, "scene": {"scene": scene}, "mode": mode}

    def summary_for_mapping(self):
        return {**self.summary, "nx": self.meta["grid"]["nx"], "ny": self.meta["grid"]["ny"],
                "frame": self.meta["frame"]}


def s1_target(mesh, supports):
    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    return Target("S1", mesh, fr, supports)


def cfg(**over):
    c = settings()
    c["solver"]["backend"] = "superlu"
    for k, v in over.items():
        c[k].update(v)
    return c
