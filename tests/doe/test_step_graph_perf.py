"""V-SG-12 성능(perf·slow 표지, esl_step_graph.md §8): 600 000 요소(H6 중점 분할 ×4 + x 방향 타일, 마지막 타일은 잘림) —
step 상한(SG-D-16 i: max(graph.limits, step_graph) = 600 000 요소·300 s)으로 classify ≤ 300 s·RSS ≤ 1.5 GB, derive ≤ 8 s;
600 001 요소 = GRAPH_FAILED{TOO_LARGE}(분류 없이 준비 계속 — src elems 비드 경로). CI 는 측정값 기록(초과 = 경고), 목표의
``ESL_PERF_FAIL_X``(기본 3)배를 넘을 때만 실패 — 판정은 실기 V-SG-R1. classify 는 RSS 를 따로 재려고 하위 프로세스에서 돈다."""
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
import warnings

import numpy as np
import pytest
from _bg_util import CFG, bgr, bs, cf, esl_mesh

from esl.doe import stages as stg
from esl.doe import step_graph as sg

pytestmark = [pytest.mark.perf, pytest.mark.slow]
FAIL_X = float(os.environ.get("ESL_PERF_FAIL_X", "3"))
N_TARGET = 600_000


def midsplit(X: np.ndarray, C: np.ndarray):
    """중점 분할: 사각형 → 사각형 4개(모서리 중점 + 중심), 삼각형 → 삼각형 4개. 원 노드 번호 유지(새 노드는 뒤에)."""
    C = np.asarray(C, np.int64)
    q = C[:, 3] >= 0
    k = np.where(q, 4, 3)
    a = C[:, :4]
    b = np.where(np.arange(4)[None, :] < (k[:, None] - 1), np.roll(a, -1, axis=1), a[:, :1])   # 다음 꼭짓점(삼각형 고리)
    ed = np.stack([a, b], axis=2)[np.arange(4)[None, :] < k[:, None]]
    key = np.sort(ed, axis=1)
    uk, inv = np.unique(key, axis=0, return_inverse=True)
    n0 = X.shape[0]
    mid = n0 + inv.ravel()
    Xm = 0.5 * (X[uk[:, 0]] + X[uk[:, 1]])
    M = -np.ones((C.shape[0], 4), np.int64)
    M[np.arange(4)[None, :] < k[:, None]] = mid
    nq = int(q.sum())
    cen = n0 + uk.shape[0] + np.arange(nq)
    Xc = X[C[q]].mean(axis=1)
    out = []
    Cq, Mq = C[q], M[q]
    for i in range(4):                                       # 사각형: 꼭짓점 i, 모서리 i 중점, 중심, 모서리 i-1 중점
        out.append(np.c_[Cq[:, i], Mq[:, i], cen, Mq[:, (i - 1) % 4]])
    Ct, Mt = C[~q], M[~q]
    neg = -np.ones(Ct.shape[0], np.int64)
    for i in range(3):
        out.append(np.c_[Ct[:, i], Mt[:, i], Mt[:, (i - 1) % 3], neg])
    out.append(np.c_[Mt[:, 0], Mt[:, 1], Mt[:, 2], neg])
    return np.vstack([X, Xm, Xc]), np.vstack(out)


def big_mesh(n_target: int = N_TARGET):
    fx = cf.load_fixture("h6")
    X, C = midsplit(np.asarray(fx["x0"], np.float64), fx["conn"])
    F = np.asarray(fx["fixed"], np.int64)
    xs, cs, fs = [], [], []
    off = k = 0
    while sum(c.shape[0] for c in cs) < n_target:
        xs.append(X + np.array([1300.0 * k, 0.0, 0.0]))
        cs.append(np.where(C >= 0, C + off, -1))
        fs.append(F + off)
        off += X.shape[0]
        k += 1
    Xa, Ca, Fa = np.vstack(xs), np.vstack(cs)[:n_target], np.concatenate(fs)
    used = np.unique(Ca[Ca >= 0])
    remap = -np.ones(Xa.shape[0], np.int64)
    remap[used] = np.arange(used.size)
    return {"x0": Xa[used], "conn": np.where(Ca >= 0, remap[np.maximum(Ca, 0)], -1).astype(np.int64),
            "fixed": remap[Fa][remap[Fa] >= 0].astype(np.int64)}


def _step_limits():
    s = sg.cfg_of(CFG)
    return {"max_elems": s["max_elems"], "timeout_s": s["timeout_s"]}


_CHILD = r"""
import json, sys, time
import numpy as np
sys.path[:0] = json.loads(sys.argv[3])
from _bg_util import CFG, bgr, esl_mesh
z = np.load(sys.argv[1])
fx = {"x0": z["x0"], "conn": z["conn"], "fixed": z["fixed"]}
mesh = esl_mesh(fx)
t0 = time.perf_counter()
st = bgr.prep_graph(mesh, fx["fixed"] + 1, CFG, sys.argv[2], limits=json.loads(sys.argv[4]))
st["wall_s"] = time.perf_counter() - t0
print("RESULT" + json.dumps({k: st[k] for k in ("ok", "code", "n_segments", "n_islands", "seconds", "wall_s")}))
"""


def _check(name, val, budget, unit, rows):
    msg = f"V-SG-12 {name}: {val:.1f} {unit} (목표 {budget} {unit})"
    rows.append(msg)
    if val > budget:
        warnings.warn(msg + " — 이 환경 측정값(기록용)", stacklevel=2)
    assert val <= FAIL_X * budget, msg


def test_perf_600k_classify_derive():
    fx = big_mesh()
    assert fx["conn"].shape[0] == N_TARGET and (fx["conn"][:, 3] >= 0).mean() > 0.9
    d = tempfile.mkdtemp(prefix="sg_perf_")
    src = os.path.join(d, "mesh.npz")
    np.savez(src, **fx)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    paths = [here, root, os.path.join(root, "packages", "beadgraph", "src")]
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    p = subprocess.run([sys.executable, "-c", _CHILD, src, d, json.dumps(paths), json.dumps(_step_limits())],
                       capture_output=True, text=True, timeout=FAIL_X * 300 + 120, check=False)
    rss_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0      # Linux ru_maxrss = KiB
    assert p.returncode == 0, p.stderr[-2000:]
    st = json.loads(next(ln for ln in p.stdout.splitlines() if ln.startswith("RESULT"))[6:])
    rows = []
    print(f"classify 600k: {st}")
    assert st["ok"], st
    _check("classify", st["wall_s"], 300.0, "s", rows)
    if rss_mb > before / 1024.0:                            # 앞선 하위 프로세스가 더 컸으면 이 값은 상한일 뿐(기록만)
        _check("classify RSS", rss_mb, 1536.0, "MB", rows)
    mesh = esl_mesh(fx)
    g, lab = bgr.load_graph(d)
    sel, _sym, _w = bgr.auto_seed(g, lab, CFG)
    t0 = time.perf_counter()
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx["fixed"] + 1)
    dd = time.perf_counter() - t0
    print(f"derive {dd:.2f} s, beads {len(D.beads)}")
    _check("derive", dd, 8.0, "s", rows)
    print("\n".join(rows))


def test_600001_too_large_elems_path():
    """600 001 요소 → step 상한으로도 TOO_LARGE(분류 안 함) → 준비 경고 GRAPH_FAILED{detail TOO_LARGE} — 준비는 READY 로
    계속하고 비드는 직접 칠하기(src elems)."""
    fx = cf.load_fixture("h5")
    mesh = esl_mesh(fx)
    n = N_TARGET + 1
    reps = n // mesh["elem_id"].size + 1
    big = {k: (np.tile(v, reps)[:n] if np.ndim(v) == 1 and v.size == mesh["elem_id"].size else v) for k, v in mesh.items()}
    big["conn"] = np.tile(mesh["conn"], (reps, 1))[:n]
    st = bgr.prep_graph(big, (), CFG, "/nonexistent-never-written", limits=_step_limits())
    assert st["ok"] is False and st["code"] == "TOO_LARGE"
    w = stg.graph_failed_warning(st["code"])
    assert w["code"] == "GRAPH_FAILED" and w["detail"] == "TOO_LARGE"
    st2 = bgr.prep_graph(big, (), CFG, "/nonexistent-never-written")      # step 상한 없음(①②) = 같은 결과
    assert st2["code"] == "TOO_LARGE"
