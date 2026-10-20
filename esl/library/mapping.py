"""정규화 격자 셀 합력·합모멘트 → 대상 메시 절점력 (계약 esl_p2_library.md §3 매핑).

``to_target(entry_summary, target_mesh, frame, opts=None) -> (F (N,3), info)``

- 원본 항목의 셀 (i,j) 국부 성분 합력 F_loc·합모멘트 M_loc(셀 중심 기준)를 대상 좌표계로 돌려(전역 = Rᵀ·국부)
  대상 메시에서 **같은 정규화 셀에 든 노드**에 분배한다.
- 셀마다 최소노름 해: min Σ|f_i|²  s.t.  Σ f_i = F,  Σ (x_i − c) × f_i = M  (6 제약).
  f = Aᵀ(AAᵀ)⁻¹b 를 ``lstsq`` 로 계산(노드 중심·크기로 무차원화해 조건수 확보). 해는 기준점 c 선택과 무관.
- 셀에 노드가 3개 미만이거나 공선에 가까우면(중심화 좌표 특이값 비 s₂/s₁ < ``min_spread``, 기본 0.2) 6 제약을
  만족할 수 없거나(공선) 축 둘레 모멘트를 만들려고 큰 상쇄 절점력이 생기므로(거의 공선 — 조건수 ∝ s₁/s₂)
  **인접 셀과 병합**: 4-이웃 중 노드가 가장 많은 셀(동률은 작은 번호), 없으면 8-이웃, 그것도 없으면 이웃 전부를
  더해 가며 조건을 만족할 때까지 키운다. 병합 그룹은 그룹 합력·합모멘트(그룹 기준점으로 옮긴 값)를 보존한다.
  원본에 하중이 있으나 대상에 노드가 없는 셀(대상 형상의 구멍 등)도 같은 규칙으로 이웃에 넘긴다(총량 보존).
- ``moment_scale``: ``preserve``(기본, 계약 = 합모멘트 그대로) | ``geometric``(M × √(L_ξ,t·L_η,t / L_ξ,s·L_η,s),
  기하 비례 가정. 원본이 자기평형이면 닮은꼴 대상에서도 자기평형이 유지됨).
- ``equilibrate``(기본 True): 매핑 뒤 전체 합력·합모멘트 잔차를 전 노드 최소노름 보정으로 0 으로 만든다
  (크기가 다른 모델로 옮길 때 Σ c×F 가 달라져 생기는 불평형 → 3-2-1 반력 방지). 보정 전 셀 보존 오차·보정 전후 평형을
  ``info`` 에 기록. 보정량은 작지만 셀 합력을 미세하게 바꾸므로 보존 검증은 보정 전 값(``F_cells``)으로 한다.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError
from esl.library import normalize as nz

MIN_SPREAD = 0.2
RANK_TOL = 1e-10


def _rank_ok(X: np.ndarray, tol: float) -> bool:
    if X.shape[0] < 3:
        return False
    P = X - X.mean(axis=0)
    s = np.linalg.svd(P, compute_uv=False)
    return bool(s[0] > 0 and s[1] > tol * s[0])


def min_norm_forces(X, F, M, ref) -> tuple[np.ndarray, float]:
    """노드 X (m,3)에 Σf = F, Σ(x−ref)×f = M 을 만족하는 최소노름 f (m,3). 반환 (f, 제약 상대 잔차)."""
    X = np.asarray(X, dtype=np.float64)
    F = np.asarray(F, dtype=np.float64)
    M = np.asarray(M, dtype=np.float64)
    xc = X.mean(axis=0)
    Mc = M + np.cross(np.asarray(ref, dtype=np.float64) - xc, F)     # 노드 중심 기준으로 옮김
    r = X - xc
    L = float(np.max(np.linalg.norm(r, axis=1)))
    if L <= 0:
        raise EslError("MAPPING_DEGENERATE", "노드가 한 점에 모임")
    rs = r / L
    m = X.shape[0]
    A = np.zeros((6, 3 * m))
    A[0, 0::3] = A[1, 1::3] = A[2, 2::3] = 1.0
    A[3, 1::3], A[3, 2::3] = -rs[:, 2], rs[:, 1]
    A[4, 0::3], A[4, 2::3] = rs[:, 2], -rs[:, 0]
    A[5, 0::3], A[5, 1::3] = -rs[:, 1], rs[:, 0]
    b = np.concatenate([F, Mc / L])
    sol, _, rank, sv = np.linalg.lstsq(A, b, rcond=None)
    if rank < 6 or sv[-1] <= RANK_TOL * sv[0]:
        raise EslError("MAPPING_DEGENERATE", f"6 제약 행렬 계수 부족(rank {rank})")
    f = sol.reshape(m, 3)
    res = A @ sol - b
    scale = float(np.linalg.norm(b))
    return f, (float(np.linalg.norm(res) / scale) if scale > 0 else float(np.linalg.norm(res)))


def resultants(X, f, ref):
    f = np.asarray(f, dtype=np.float64)
    return f.sum(axis=0), np.cross(np.asarray(X) - np.asarray(ref), f).sum(axis=0)


def _x0_of(target_mesh):
    if isinstance(target_mesh, dict):
        return np.asarray(target_mesh["x0"], dtype=np.float64)
    return np.asarray(target_mesh, dtype=np.float64)


def _neighbors(c: int, nx: int, ny: int, diag: bool) -> list[int]:
    i, j = divmod(c, ny)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if (di == 0 and dj == 0) or (not diag and di != 0 and dj != 0):
                continue
            a, b = i + di, j + dj
            if 0 <= a < nx and 0 <= b < ny:
                out.append(a * ny + b)
    return out


def _groups(loaded, members, X, nx, ny, tol):
    """셀 → 그룹(병합) 목록. 하중이 있고 조건 미달인 셀만 키운다."""
    n = nx * ny
    gid = np.arange(n)
    groups = {c: [c] for c in range(n)}

    def nodes_of(g):
        return np.concatenate([members[c] for c in groups[g]]) if groups[g] else np.zeros(0, np.int64)

    for c in range(n):
        g = gid[c]
        if not loaded[c] and not any(loaded[k] for k in groups[g]):
            continue
        while not _rank_ok(X[nodes_of(g)], tol):
            cur = set(groups[g])
            cand = sorted({k for cc in cur for k in _neighbors(cc, nx, ny, False)} - cur)
            withn = [k for k in cand if members[k].size > 0]
            if not withn:
                cand8 = sorted({k for cc in cur for k in _neighbors(cc, nx, ny, True)} - cur)
                withn = [k for k in cand8 if members[k].size > 0]
                if not withn:
                    add = cand8 or cand
                    if not add:
                        raise EslError("MAPPING_DEGENERATE", "대상 메시 전체에 비공선 노드 3개가 없음")
                    add_groups = sorted({int(gid[k]) for k in add})
                    for h in add_groups:
                        if h != g:
                            for k in groups[h]:
                                gid[k] = g
                            groups[g] += groups.pop(h)
                    continue
            best = max(withn, key=lambda k: (members[k].size, -k))
            h = int(gid[best])
            if h != g:
                for k in groups[h]:
                    gid[k] = g
                groups[g] += groups.pop(h)
    return {g: sorted(v) for g, v in groups.items()}, gid


def to_target(entry_summary: dict, target_mesh, frame: dict, opts: dict | None = None):
    o = {"moment_scale": "preserve", "equilibrate": True, "min_spread": MIN_SPREAD}
    if opts:
        o.update({k: v for k, v in opts.items() if v is not None})
    X = _x0_of(target_mesh)
    nx, ny = int(entry_summary["nx"]), int(entry_summary["ny"])
    Floc = np.asarray(entry_summary["cell_F_loc"], dtype=np.float64).reshape(-1, 3)
    Mloc = np.asarray(entry_summary["cell_M_loc"], dtype=np.float64).reshape(-1, 3)
    ms = 1.0
    if o["moment_scale"] == "geometric":
        sf = entry_summary.get("frame")
        if not sf:
            raise EslError("INPUT_INVALID", "moment_scale=geometric 에는 원본 frame(L_xi, L_eta) 필요")
        ms = float(np.sqrt(frame["L_xi"] * frame["L_eta"] / (sf["L_xi"] * sf["L_eta"])))
    elif o["moment_scale"] != "preserve":
        raise EslError("INPUT_INVALID", f"moment_scale: preserve|geometric (값 {o['moment_scale']!r})")
    R = nz.rotation(frame)
    Fg = Floc @ R
    Mg = (Mloc @ R) * ms
    i, j, _ = nz.cell_index(frame, X, nx, ny)
    cid = i * ny + j
    order = np.argsort(cid, kind="stable")
    bounds = np.searchsorted(cid[order], np.arange(nx * ny + 1))
    members = [order[bounds[c]:bounds[c + 1]] for c in range(nx * ny)]
    C = nz.cell_centers(frame, nx, ny).reshape(-1, 3)
    loaded = (np.linalg.norm(Fg, axis=1) > 0) | (np.linalg.norm(Mg, axis=1) > 0)
    groups, gid = _groups(loaded, members, X, nx, ny, float(o["min_spread"]))

    f = np.zeros_like(X)
    max_res = 0.0
    merged = []
    for g, cells in groups.items():
        if not any(loaded[c] for c in cells):
            continue
        nodes = np.concatenate([members[c] for c in cells])
        ref = C[cells].mean(axis=0)
        Fs = Fg[cells].sum(axis=0)
        Ms = (Mg[cells] + np.cross(C[cells] - ref, Fg[cells])).sum(axis=0)
        fg, res = min_norm_forces(X[nodes], Fs, Ms, ref)
        f[nodes] += fg
        max_res = max(max_res, res)
        if len(cells) > 1:
            merged.append({"cells": [[int(c // ny), int(c % ny)] for c in cells], "n_nodes": int(nodes.size)})

    # 보존 검증(그룹별, 대상 메시에서 다시 계산): 상대 오차 = (|ΔF| + |ΔM|/L) / (|F| + |M|/L)
    cons = 0.0
    for g, cells in groups.items():
        if not any(loaded[c] for c in cells):
            continue
        nodes = np.concatenate([members[c] for c in cells])
        ref = C[cells].mean(axis=0)
        Fs = Fg[cells].sum(axis=0)
        Ms = (Mg[cells] + np.cross(C[cells] - ref, Fg[cells])).sum(axis=0)
        F1, M1 = resultants(X[nodes], f[nodes], ref)
        L = max(float(np.max(np.linalg.norm(X[nodes] - X[nodes].mean(axis=0), axis=1))), 1e-300)
        den = np.linalg.norm(Fs) + np.linalg.norm(Ms) / L
        if den > 0:
            cons = max(cons, float((np.linalg.norm(F1 - Fs) + np.linalg.norm(M1 - Ms) / L) / den))

    F_cells = f.copy()
    ctr = X.mean(axis=0)
    Lb = float(np.linalg.norm(X.max(axis=0) - X.min(axis=0)))
    sabs = float(np.linalg.norm(f, axis=1).sum())
    tF, tM = resultants(X, f, ctr)
    eq_before = {"force_rel": float(np.linalg.norm(tF) / sabs) if sabs > 0 else 0.0,
                 "moment_rel": float(np.linalg.norm(tM) / (sabs * Lb)) if sabs > 0 else 0.0}
    corr = 0.0
    if o["equilibrate"] and sabs > 0:
        d, _ = min_norm_forces(X, -tF, -tM, ctr)
        f = f + d
        corr = float(np.linalg.norm(d, axis=1).sum() / sabs)
    tF2, tM2 = resultants(X, f, ctr)
    sabs2 = float(np.linalg.norm(f, axis=1).sum())
    eq_after = {"force_rel": float(np.linalg.norm(tF2) / sabs2) if sabs2 > 0 else 0.0,
                "moment_rel": float(np.linalg.norm(tM2) / (sabs2 * Lb)) if sabs2 > 0 else 0.0}
    info = {"nx": nx, "ny": ny, "moment_scale": o["moment_scale"], "moment_factor": ms,
            "n_groups_loaded": int(sum(1 for cells in groups.values() if any(loaded[c] for c in cells))),
            "merged_groups": merged, "n_cells_loaded": int(loaded.sum()),
            "n_cells_empty_loaded": int(sum(1 for c in range(nx * ny) if loaded[c] and members[c].size == 0)),
            "solve_residual_max": max_res, "conservation_rel_max": cons,
            "equilibrium_before": eq_before, "equilibrium_after": eq_after,
            "equilibrate": bool(o["equilibrate"]), "equilibrate_correction_rel": corr}
    return f, {**info, "F_cells": F_cells}
