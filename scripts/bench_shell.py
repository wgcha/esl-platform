"""쉘 솔버 대규모 벤치 (테스트 스위트 아님).

실데이터 규모(223,415 쉘 요소, 약 22만 노드, 1.33M dof) 곡면 판(원통 패널, QUAD 위주 + TRIA 일부)으로
조립·condensed_forces·solve·strains 시간과 피크 RSS 를 백엔드별로 잰다. 백엔드마다 별도 프로세스로
돌려 피크 RSS 가 섞이지 않게 한다.

    python scripts/bench_shell.py                       # 설치된 모든 백엔드, 223,415 요소
    python scripts/bench_shell.py --backend cholmod --n 470 --ntria 2515
    python scripts/bench_shell.py --n 100               # 소형 확인
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402


def curved_mesh(n: int, ntria: int, R: float = 2000.0, ang: float = 1.2, H: float = 2400.0):
    """원통 패널 n×n QUAD, 앞쪽 ntria 개 쿼드를 TRIA 2개씩으로 분할 → 요소 n² + ntria."""
    th = np.linspace(-ang / 2, ang / 2, n + 1)
    zs = np.linspace(0.0, H, n + 1)
    T, Z = np.meshgrid(th, zs, indexing="ij")
    X = np.stack([R * np.cos(T).ravel(), R * np.sin(T).ravel(), Z.ravel()], axis=1)
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    i, j = i.ravel(), j.ravel()
    nid = lambda a, b: a * (n + 1) + b  # noqa: E731
    q = np.stack([nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)], axis=1)
    tq, rest = q[:ntria], q[ntria:]
    t1 = np.c_[tq[:, 0], tq[:, 1], tq[:, 2], -np.ones(len(tq), int)]
    t2 = np.c_[tq[:, 0], tq[:, 2], tq[:, 3], -np.ones(len(tq), int)]
    conn = np.concatenate([rest, t1, t2])
    et = np.r_[np.full(len(rest), 4), np.full(2 * len(tq), 3)].astype(np.int8)
    return X, conn, et


def run_one(backend: str, n: int, ntria: int) -> dict:
    from esl.mech import kabsch, supports
    from esl.mech.shell import ShellModel, _rss_peak_mb

    X, conn, et = curved_mesh(n, ntria)
    out = {"backend": backend, "n_elems": int(len(conn)), "n_quad": int((et == 4).sum()),
           "n_tria": int((et == 3).sum()), "n_nodes": int(len(X)), "n_dof": int(6 * len(X))}
    s = (X - X.mean(0)) / np.ptp(X, axis=0).max()
    u = 2.0 * np.c_[np.sin(3 * s[:, 0]) * s[:, 2], s[:, 0] ** 2 - s[:, 1] * s[:, 2], np.cos(2 * s[:, 2]) * s[:, 1]]
    out["rss_mesh_mb"] = _rss_peak_mb()

    m = ShellModel(X, conn, et, 1.6, 2.1e5, 0.3, backend=backend)
    t0 = time.perf_counter()
    m.K()
    out["t_assembly_s"] = time.perf_counter() - t0
    out["rss_after_K_mb"] = _rss_peak_mb()

    t0 = time.perf_counter()
    F = m.condensed_forces(u)
    out["t_condensed_s"] = time.perf_counter() - t0
    out["rss_after_condensed_mb"] = _rss_peak_mb()
    sF = np.abs(F).sum()
    out["equil_force_rel"] = float(np.linalg.norm(F.sum(0)) / sF)

    spc = supports.pick_321(X, supports.pca_corners(X)["idx"])
    t0 = time.perf_counter()
    uv, R = m.solve(F, spc)
    out["t_solve_s"] = time.perf_counter() - t0
    out["rss_after_solve_mb"] = _rss_peak_mb()
    res, _, _ = kabsch.remove_linear_rigid(X, uv[:, :3] - u)
    out["roundtrip_rms_rel"] = float(np.sqrt(np.mean(np.sum(res ** 2, 1))) / np.abs(u).max())
    out["reaction_rel"] = float(np.abs(R).sum() / sF)

    t0 = time.perf_counter()
    eps = m.strains(uv)
    out["t_strains_s"] = time.perf_counter() - t0
    out["eps_max"] = float(np.abs(eps).max())
    out["rss_peak_mb"] = _rss_peak_mb()
    out["stats"] = m.stats
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=None, help="auto|cholmod|pardiso|superlu (생략 시 설치된 전부)")
    ap.add_argument("--n", type=int, default=470, help="격자 n×n 쿼드 (470 → 220,900)")
    ap.add_argument("--ntria", type=int, default=2515, help="TRIA 2개로 나눌 쿼드 수 (기본 → 223,415 요소)")
    ap.add_argument("--json", default=None, help="결과 JSON 저장 경로")
    a = ap.parse_args()

    if a.backend:
        r = run_one(a.backend, a.n, a.ntria)
        print("RESULT " + json.dumps(r, default=float))
        return

    from esl.mech.shell import _pyamg, available_backends
    rows = []
    for b in available_backends() + (["iterative"] if _pyamg() is not None else []):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--backend", b, "--n", str(a.n),
                            "--ntria", str(a.ntria)], capture_output=True, text=True)
        line = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
        if p.returncode != 0 or not line:
            rows.append({"backend": b, "error": (p.stderr or p.stdout)[-500:], "returncode": p.returncode})
            continue
        rows.append(json.loads(line[0][7:]))
    hdr = ("backend", "elems", "dof", "assembly", "condensed", "solve", "strains", "peak RSS", "nnz(L) K_ff",
           "rt rms")
    print(" | ".join(hdr))
    for r in rows:
        if "error" in r:
            print(f"{r['backend']} | 실패 rc={r['returncode']} | {r['error'][-200:]!r}")
            continue
        print(f"{r['backend']} | {r['n_elems']} | {r['n_dof']} | {r['t_assembly_s']:.1f}s | {r['t_condensed_s']:.1f}s"
              f" | {r['t_solve_s']:.1f}s | {r['t_strains_s']:.1f}s | {r['rss_peak_mb'] / 1024:.2f} GB"
              f" | {r['stats']['K_ff']['nnz_L'] / 1e6:.0f}M | {r['roundtrip_rms_rel']:.1e}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1, default=float)


if __name__ == "__main__":
    main()
