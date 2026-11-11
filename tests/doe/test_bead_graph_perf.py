"""V-BG-13 performance (perf, slow): 220k-element synthetic (H6 tiled 2x, 208 876 elements + a strip of the third tile)
-> classify <= 60 s and tracemalloc <= 300 MB, derive (schema 2) <= 3 s, basis 20 variables <= 60 s; 250 001 elements
-> GRAPH_FAILED{TOO_LARGE}."""
import time
import tracemalloc

import numpy as np
import pytest
from _bg_util import CFG, bgr, bs, cf, esl_mesh

pytestmark = [pytest.mark.perf, pytest.mark.slow]


def tiled(n_target=220_000):
    fx = cf.load_fixture("h6")
    X, C, F = fx["x0"], fx["conn"].astype(np.int64), fx["fixed"].astype(np.int64)
    xs, cs, fs = [], [], []
    off = 0
    k = 0
    while sum(c.shape[0] for c in cs) < n_target:
        Xk = X + np.array([1300.0 * k, 0.0, 0.0])
        xs.append(Xk)
        cs.append(np.where(C >= 0, C + off, -1))
        fs.append(F + off)
        off += X.shape[0]
        k += 1
    Xa, Ca, Fa = np.vstack(xs), np.vstack(cs), np.concatenate(fs)
    m = n_target
    keep = Ca[:m]
    used = np.unique(keep[keep >= 0])
    remap = -np.ones(Xa.shape[0], np.int64)
    remap[used] = np.arange(used.size)
    return {"x0": Xa[used], "conn": np.where(keep >= 0, remap[np.maximum(keep, 0)], -1).astype(np.int32),
            "fixed": remap[Fa][remap[Fa] >= 0].astype(np.int32)}


def test_perf_220k():
    fx = tiled()
    mesh = esl_mesh(fx)
    assert mesh["elem_id"].size == 220_000
    import tempfile
    d = tempfile.mkdtemp(prefix="bg_perf_")
    tracemalloc.start()
    t0 = time.perf_counter()
    st = bgr.prep_graph(mesh, fx["fixed"] + 1, CFG, d)
    dt = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"classify 220k: {dt:.1f} s, peak {peak / 2 ** 20:.0f} MB, segments {st['n_segments']}")
    assert st["ok"], st
    assert dt <= 60.0 and peak <= 300 * 2 ** 20
    g, lab = bgr.load_graph(d)
    sel, _sym, _w = bgr.auto_seed(g, lab, CFG)
    t0 = time.perf_counter()
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx["fixed"] + 1)
    dd = time.perf_counter() - t0
    print(f"derive {dd:.2f} s, beads {len(D.beads)}")
    assert dd <= 3.0
    t0 = time.perf_counter()
    B = bs.basis(mesh, D, CFG)
    db = time.perf_counter() - t0
    print(f"basis {len(B.vars)} variables {db:.1f} s")
    assert len(B.vars) >= 20 and db <= 60.0 * len(B.vars) / 20.0


def test_too_large():
    fx = cf.load_fixture("h5")
    mesh = esl_mesh(fx)
    n = int(CFG["select"]["graph"]["limits"]["max_elems"]) + 1   # v0.17.4 기본 600,000(이슈 #63 — 현장 267,470 요소)
    reps = n // mesh["elem_id"].size + 1
    big = {k: (np.tile(v, reps)[:n] if np.ndim(v) == 1 and v.size == mesh["elem_id"].size else v) for k, v in mesh.items()}
    big["conn"] = np.tile(mesh["conn"], (reps, 1))[:n]
    big["elem_type"] = np.tile(mesh["elem_type"], reps)[:n]
    st = bgr.prep_graph(big, (), CFG, "/nonexistent-never-written")
    assert st["ok"] is False and st["code"] == "TOO_LARGE"
