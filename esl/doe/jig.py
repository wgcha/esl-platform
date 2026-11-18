"""지그 순위 공용 순수 모듈 (계약 docs/contracts/esl_jig_rank.md §1·§5.1, v0.23.0).

체결부(tie) 노드를 병진 123 으로 물린 지그에서 몇 곳(접촉 영역·공간 패치)의 가압 하중 + 체적력을 맞춰 기준 낙하 변형
(sm_ref)을 재현하고(D-JIG-2~6), 설계안은 같은 지그·같은 노드 하중으로 재풀이해 비교한다(D-JIG-7).

모드 무관 독립 모듈(AGENTS.md D-0.20.0-CODE): ``esl.doe`` 를 import 하지 않고 파일 IO·설정 해석을 하지 않는다 —
값은 모두 인수(기본값은 호출자가 DEFAULTS["rank"]["jig"] 에서 해석해 키워드로 넘김).
import 허용 = numpy · scipy(sparse·csgraph·spatial·optimize) · esl.errors · esl.mech.shell · esl.mech.kabsch.

결정성: 같은 입력 → 비트 동일(정렬 키·동률 규칙 고정, BVLS, bincount·고정 순서 합).
대규모 거리: 삼각형 중심 cKDTree + 노드 청크 → 후보 삼각형만 정확 점-삼각형 거리(Ericson). 메모리 O(T + chunk·knn),
N×T 배열 없음(V-JIG-8).
"""
from __future__ import annotations

import time

import numpy as np
import scipy.sparse as sp
from scipy.optimize import lsq_linear
from scipy.sparse.linalg import ArpackNoConvergence, LinearOperator, eigsh, splu
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from esl.errors import EslError
from esl.mech import kabsch
from esl.mech.shell import ShellModel, solver_check_kwargs

SCHEMA = "esl/doe_jig/1"
TIE_KINDS = ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN")   # 문서용 — 비트 변환은 호출자(paicad_io.FIXED_KINDS)
REGION_CONTACT = 1
REGION_PATCH = 2
KIND_NAME = {REGION_CONTACT: "contact", REGION_PATCH: "patch"}
HASH_EXCLUDE = ("mac_min", "umax_err_max", "tie_rel_warn", "cancel_warn", "work_eff_min", "rho_t_mm3",
                "modes_ref321", "tie_spread_min")   # 해시 밖(D-JIG-11)
TIE_REL = 1e-12            # 최근접 삼각형 동률 폭(× gap)
SIGN_FREE_REL = 1e-9       # 접촉 법선 부호 자유 판정(× ΣA·max(gap, 1))


# ====================================================================== 메시 기초
def _conn(mesh):
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    return conn, et


def _edges(mesh) -> tuple[np.ndarray, np.ndarray]:
    """요소 변 (a, b) — 쿼드 (0,1)(1,2)(2,3)(3,0), 트라이 (0,1)(1,2)(2,0)."""
    conn, et = _conn(mesh)
    q = et == 4
    a = [conn[:, 0], conn[:, 1], conn[q, 2], conn[q, 3], conn[~q, 2]]
    b = [conn[:, 1], conn[:, 2], conn[q, 3], conn[q, 0], conn[~q, 0]]
    return np.concatenate(a), np.concatenate(b)


def _components(n: int, a: np.ndarray, b: np.ndarray) -> tuple[int, np.ndarray]:
    G = sp.coo_matrix((np.ones(a.size, dtype=np.int8), (a, b)), shape=(n, n)).tocsr()
    return connected_components(G, directed=False)


def _elem_nodes(conn, et):
    """(E,4) 노드 · 노드 수(E,) — 트라이 4번째 칸은 사용 안 함."""
    return conn, np.where(et == 4, 4, 3)


def node_weights(mesh) -> dict:
    """노드 면적 A_n = Σ A_e/nn_e, 단위 법선(이웃 요소 법선 면적 가중 합), 두께(이웃 요소 면적 가중 평균),
    요소 면적·단위 법선(트라이 = 변 (1−0)×(2−0), 쿼드 = 대각선 (2−0)×(3−1) — ShellModel 국부계와 같음).
    쿼드 면적 = ½‖d₁×d₂‖ = 대각선 법선 평면 투영 면적 = ShellModel.area. 고립 노드 = area 0·normal 0·thick 0."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn, et = _conn(mesh)
    N, E = X.shape[0], conn.shape[0]
    q = et == 4
    v = np.empty((E, 3))
    p0, p1, p2 = X[conn[:, 0]], X[conn[:, 1]], X[conn[:, 2]]
    v[~q] = np.cross(p1[~q] - p0[~q], p2[~q] - p0[~q])
    if q.any():
        p3 = X[conn[q, 3]]
        v[q] = np.cross(p2[q] - p0[q], p3 - p1[q])
    nrm = np.linalg.norm(v, axis=1)
    A = 0.5 * nrm
    m = np.divide(v, nrm[:, None], out=np.zeros_like(v), where=nrm[:, None] > 0)
    nn = np.where(q, 4, 3)
    rows = np.concatenate([conn[:, 0], conn[:, 1], conn[:, 2], conn[q, 3]])
    eidx = np.concatenate([np.arange(E)] * 3 + [np.flatnonzero(q)])
    area = np.bincount(rows, weights=(A / nn)[eidx], minlength=N)
    aw = np.bincount(rows, weights=A[eidx], minlength=N)
    t = np.broadcast_to(np.asarray(mesh["thickness"], dtype=np.float64), (E,))
    thick = np.divide(np.bincount(rows, weights=(A * t)[eidx], minlength=N), aw, out=np.zeros(N), where=aw > 0)
    ns = np.stack([np.bincount(rows, weights=(A[:, None] * m)[eidx, k], minlength=N) for k in range(3)], axis=1)
    nl = np.linalg.norm(ns, axis=1)
    normal = np.divide(ns, nl[:, None], out=np.zeros_like(ns), where=nl[:, None] > 0)
    return {"area": area, "normal": normal, "thick": thick, "elem_area": A, "elem_normal": m}


# ====================================================================== (1) 지그 노드
def select_jig_nodes(mesh, node_id, *, kind_mask=None, kind_bits=0) -> dict:
    """지그 노드 J (D-JIG-1): node_id 후보 ∩ 메시 node_id. kind_mask 가 있으면 ``kind_mask & kind_bits ≠ 0`` 만.
    검사(분해 전): J = ∅ → JIG_NO_TIE; 요소 그래프 연결 성분마다 J ≥ 3·비공선 아님 → JIG_SUPPORT_DEGENERATE."""
    cand = np.asarray(node_id, dtype=np.int64).reshape(-1)
    if kind_mask is not None:
        km = np.asarray(kind_mask, dtype=np.int64).reshape(-1)
        if km.shape != cand.shape:
            raise EslError("INPUT_INVALID", "kind_mask 와 node_id 길이가 다름")
        cand = cand[(km & int(kind_bits)) != 0]
    cand = np.unique(cand)
    mid = np.asarray(mesh["node_id"], dtype=np.int64)
    order = np.argsort(mid, kind="stable")
    sid = mid[order]
    pos = np.searchsorted(sid, cand)
    ok = (pos < sid.size) & (sid[np.minimum(pos, max(sid.size - 1, 0))] == cand) if sid.size else np.zeros(cand.size, bool)
    idx = np.sort(order[pos[ok]]).astype(np.int64)
    detail = {"n_input": int(cand.size), "n_missing": int((~ok).sum())}
    X = np.asarray(mesh["x0"], dtype=np.float64)
    N = X.shape[0]
    a, b = _edges(mesh)
    ncomp, lab = _components(N, a, b)
    used = np.zeros(N, bool)
    used[a] = True
    used[b] = True
    comps = np.unique(lab[used])                       # 요소가 있는 성분만(고립 노드 제외)
    out = {"idx": idx, "node_id": mid[idx], "n_comp": int(comps.size), "code": None, "detail": detail}
    if idx.size == 0:
        out["code"] = "JIG_NO_TIE"
        return out
    bad = []
    for c in comps:
        nodes = np.flatnonzero(lab == c)
        j = idx[lab[idx] == c]
        good = False
        if j.size >= 3:
            P = X[j] - X[j].mean(axis=0)
            s = np.linalg.svd(P, compute_uv=False)
            good = bool(s[0] > 0 and s[1] / s[0] >= kabsch.DEGENERATE_RATIO)
        if not good:
            bad.append({"comp": int(c), "n_nodes": int(nodes.size), "n_jig": int(j.size)})
    if bad:
        out["code"] = "JIG_SUPPORT_DEGENERATE"
        detail["bad_comp_nodes"] = [d["n_nodes"] for d in bad]
        detail["bad_comp_jig"] = [d["n_jig"] for d in bad]
    detail["n_comp"] = int(comps.size)
    return out


def support_spread(x, jig_idx, part_mask=None) -> dict:
    """지그 노드 분포 점검(D-JIG-19 진단): tie_spread = 지그 노드 좌표 PCA 2번째 표준편차 / 대상 파트 노드 PCA 1번째 표준편차
    (특성 길이). 쉘 지그 노드는 대개 한 면 위라 3번째 표준편차 ≈ 0 → 면 안 분포의 최솟값(1·2 주축 중 작은 쪽 = 2번째)을 쓴다.
    part_mask None = 모든 노드. 반환 {"tie_spread": float | None(지그 2점 미만·파트 크기 0), "jig_std": [3], "part_std": [3]}."""
    X = np.asarray(x, dtype=np.float64).reshape(-1, 3)
    J = np.asarray(jig_idx, dtype=np.int64).reshape(-1)
    P = X if part_mask is None else X[np.asarray(part_mask, bool)]

    def std3(Y):
        if Y.shape[0] < 2:
            return np.zeros(3)
        s = np.linalg.svd(Y - Y.mean(axis=0), compute_uv=False) / np.sqrt(Y.shape[0])
        return np.concatenate([s, np.zeros(3 - s.size)])
    sj, sp_ = std3(X[J]), std3(P)
    val = float(sj[1] / sp_[0]) if J.size >= 2 and sp_[0] > 0 else None
    return {"tie_spread": val, "jig_std": [float(v) for v in sj], "part_std": [float(v) for v in sp_]}


# ====================================================================== (2) 목표 변형
def target_disp(x, u3, jig_idx, fit_mask) -> dict:
    """지그 노드 Kabsch **유한 회전** 강체 제거(D-JIG-2·16): (R, t) = kabsch.fit(x_J, x_J + u_J),
    u_tgt = Rᵀ(x + u − t) − x = (Rᵀ − I)(x − c0) + Rᵀ(u − ū) (중심화 식 — kabsch.remove_rigid 와 같은 정밀도 처리)."""
    x = np.asarray(x, dtype=np.float64)
    u3 = np.asarray(u3, dtype=np.float64)[:, :3]
    J = np.asarray(jig_idx, dtype=np.int64)
    F = np.asarray(fit_mask, bool)
    R, t, _ = kabsch.fit(x[J], x[J] + u3[J])
    c0 = x[J].mean(axis=0)
    ub = u3[J].mean(axis=0)
    u_tgt = (x - c0) @ (R.T - np.eye(3)).T + (u3 - ub) @ R          # 행벡터: v·R = (Rᵀv)ᵀ
    nf = np.linalg.norm(u_tgt[F], axis=1)
    umax = float(nf.max()) if nf.size else 0.0
    tj = float(np.linalg.norm(u_tgt[J], axis=1).max()) if J.size else 0.0
    tie_rel = tj / umax if umax > 0 else (0.0 if tj == 0 else float("inf"))
    return {"u_tgt": u_tgt, "R": R, "t": t, "rot_deg": kabsch.rotation_deg(R), "umax_tgt": umax,
            "tie_rel": float(tie_rel)}


# ====================================================================== (3) 가압 영역
def _closest_tri(p, a, b, c):
    """점-삼각형 최근접점(Ericson 5.1.5 — load_transfer LT-2 와 같은 식), 브로드캐스트 (…,3) → 점 (…,3)."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("...i,...i", ab, ap)
    d2 = np.einsum("...i,...i", ac, ap)
    bp = p - b
    d3 = np.einsum("...i,...i", ab, bp)
    d4 = np.einsum("...i,...i", ac, bp)
    cp = p - c
    d5 = np.einsum("...i,...i", ab, cp)
    d6 = np.einsum("...i,...i", ac, cp)
    del ap, bp, cp
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    sh = d1.shape
    lam = np.zeros(sh + (3,))
    done = np.zeros(sh, bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (d1 <= 0) & (d2 <= 0)
        lam[m] = (1.0, 0.0, 0.0)
        done |= m
        m = ~done & (d3 >= 0) & (d4 <= d3)
        lam[m] = (0.0, 1.0, 0.0)
        done |= m
        m = ~done & (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        v = d1 / (d1 - d3)
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - v[m], v[m], 0.0
        done |= m
        m = ~done & (d6 >= 0) & (d5 <= d6)
        lam[m] = (0.0, 0.0, 1.0)
        done |= m
        m = ~done & (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        w = d2 / (d2 - d6)
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - w[m], 0.0, w[m]
        done |= m
        m = ~done & (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        lam[m, 0], lam[m, 1], lam[m, 2] = 0.0, 1.0 - w[m], w[m]
        done |= m
        m = ~done
        den = va + vb + vc
        v = vb / den
        w = vc / den
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - v[m] - w[m], v[m], w[m]
    bad = ~np.all(np.isfinite(lam), axis=-1)
    if bad.any():
        dd = np.stack([np.linalg.norm(p - a, axis=-1), np.linalg.norm(p - b, axis=-1),
                       np.linalg.norm(p - c, axis=-1)], axis=-1)
        k = np.argmin(dd, axis=-1)
        lam[bad] = 0.0
        lam[bad, k[bad]] = 1.0
    return lam[..., 0:1] * a + lam[..., 1:2] * b + lam[..., 2:3] * c


def nearest_tri(xq, surf, *, gap_mm, knn, chunk_nodes, thick_q=None) -> dict:
    """노드 xq (n,3) → 최근접 표면 삼각형(틈 ≤ gap 후보만): {"dist" (n,) 중립면 거리 (후보 없음 = inf), "clear" (n,) 틈
    = dist − (thick_q + tri_thick)/2 (D-JIG-19, 두께 없음 = dist), "tri" (n,) (−1 = 없음), "q" (n,3)}. 최근접 = 틈 최소,
    동률(≤ 1e-12·gap) = 작은 삼각형 번호. surf["tri_thick"] (T,) 없음 = 0, thick_q None = 0 (기존과 비트 동일).
    삼각형 중심 cKDTree + 노드 청크 → 메모리 O(T + chunk·knn)."""
    xq = np.asarray(xq, dtype=np.float64).reshape(-1, 3)
    n = xq.shape[0]
    P = np.asarray(surf["x"], dtype=np.float64).reshape(-1, 3)
    tri = np.asarray(surf["tri"], dtype=np.int64).reshape(-1, 3)
    T = tri.shape[0]
    dist = np.full(n, np.inf)
    clear = np.full(n, np.inf)
    best = np.full(n, -1, dtype=np.int64)
    qq = np.zeros((n, 3))
    if n == 0 or T == 0:
        return {"dist": dist, "clear": clear, "tri": best, "q": qq}
    tt = surf.get("tri_thick") if isinstance(surf, dict) else None
    tt = np.zeros(T) if tt is None else np.maximum(np.asarray(tt, dtype=np.float64).reshape(-1), 0.0)
    tq = np.zeros(n) if thick_q is None else np.maximum(np.asarray(thick_q, dtype=np.float64).reshape(-1), 0.0)
    gap = float(gap_mm)
    ctr = np.empty((T, 3))
    rmax = 0.0
    step = max(int(chunk_nodes), 1)
    for s in range(0, T, step):                      # 중심·R_max 를 삼각형 청크로(꼭짓점 배열 전체를 만들지 않음)
        t = tri[s:s + step]
        a, b, c = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]
        cc = (a + b + c) / 3.0
        ctr[s:s + step] = cc
        r = np.sqrt(np.max(np.stack([np.sum((a - cc) ** 2, axis=1), np.sum((b - cc) ** 2, axis=1),
                                     np.sum((c - cc) ** 2, axis=1)], axis=1), axis=1))
        rmax = max(rmax, float(r.max()))
    tree = cKDTree(ctr)
    k = int(min(int(knn), T))
    ub = gap + rmax + 0.5 * (float(tq.max()) + float(tt.max()))     # 틈 ≤ gap ⇔ 중립면 거리 ≤ gap + 반두께 합
    ub = float(np.nextafter(ub, np.inf)) * (1.0 + 1e-12)   # 경계 포함(보수적)
    tol = TIE_REL * gap
    for s in range(0, n, step):
        xc = xq[s:s + step]
        _, ii = tree.query(xc, k=k, distance_upper_bound=ub)
        ii = np.asarray(ii, dtype=np.int64).reshape(xc.shape[0], k)
        valid = ii < T
        ic = np.where(valid, ii, 0)
        tc = tri[ic]
        qc = _closest_tri(xc[:, None, :], P[tc[..., 0]], P[tc[..., 1]], P[tc[..., 2]])
        d = np.linalg.norm(qc - xc[:, None, :], axis=-1)
        d[~valid] = np.inf
        g = d - 0.5 * (tq[s:s + step, None] + tt[ic])                 # 틈(두께 0 이면 g = d 그대로)
        g[~valid] = np.inf
        dmin = g.min(axis=1)
        key = np.where(valid & (g <= dmin[:, None] + tol), ii, T + 1)
        j = np.argmin(key, axis=1)
        has = np.isfinite(dmin)
        r = np.arange(xc.shape[0])
        dist[s:s + step] = np.where(has, d[r, j], np.inf)
        clear[s:s + step] = np.where(has, g[r, j], np.inf)
        best[s:s + step] = np.where(has, ii[r, j], -1)
        qq[s:s + step] = np.where(has[:, None], qc[r, j], 0.0)
    return {"dist": dist, "clear": clear, "tri": best, "q": qq}


def _region(kind, part, nodes, X, A, sign_ref) -> dict:
    nodes = np.sort(np.asarray(nodes, dtype=np.int64))
    a = A[nodes]
    sa = float(a.sum())
    ctr = (a[:, None] * X[nodes]).sum(axis=0) / sa if sa > 0 else X[nodes].mean(axis=0)
    return {"kind": int(kind), "part": int(part), "nodes": nodes, "area": sa, "center": ctr,
            "sign_ref": np.asarray(sign_ref, dtype=np.float64)}


def contact_regions(mesh, cand_mask, surf, *, gap_mm, knn, chunk_nodes, max_regions, min_regions, min_nodes,
                    min_area_mm2, weights) -> dict:
    """접촉 영역만(보충 없음, D-JIG-3·19): 후보 노드 중 틈(중립면 거리 − (t_대상 + t_상대)/2, t_대상 = weights["thick"],
    t_상대 = surf["tri_thick"] — 없으면 0) ≤ gap 인 노드 → 같은 상대 파트의 대상 메시 연결 성분
    (양 끝이 모두 집합 안·같은 파트인 변) → 노드 수·면적 필터 → (−면적, part, 최소 노드) 상위 max_regions."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    N = X.shape[0]
    A = np.asarray(weights["area"], dtype=np.float64)
    cand = np.flatnonzero(np.asarray(cand_mask, bool))
    tw = weights.get("thick") if isinstance(weights, dict) else None
    near = nearest_tri(X[cand], surf, gap_mm=gap_mm, knn=knn, chunk_nodes=chunk_nodes,
                       thick_q=None if tw is None else np.asarray(tw, dtype=np.float64)[cand])
    hit = near["clear"] <= float(gap_mm)
    cn = cand[hit]
    part = np.full(N, -1, dtype=np.int64)
    tri_part = np.asarray(surf["tri_part"], dtype=np.int64).reshape(-1)
    part[cn] = tri_part[near["tri"][hit]]
    qn = np.zeros((N, 3))
    qn[cn] = near["q"][hit]
    regions = []
    if cn.size:
        a, b = _edges(mesh)
        keep = (part[a] >= 0) & (part[a] == part[b])
        _, lab = _components(N, a[keep], b[keep])
        lc = lab[cn]
        order = np.argsort(lc, kind="stable")
        lcs, cns = lc[order], cn[order]
        cut = np.flatnonzero(np.diff(lcs)) + 1
        for grp in np.split(cns, cut):
            grp = np.sort(grp)
            ar = float(A[grp].sum())
            if grp.size < int(min_nodes) or ar < float(min_area_mm2):
                continue
            sref = (A[grp][:, None] * (X[grp] - qn[grp])).sum(axis=0)
            r = _region(REGION_CONTACT, part[grp[0]], grp, X, A, sref)
            r["gap_mm"] = float(gap_mm)
            regions.append(r)
    n_found = len(regions)
    regions.sort(key=lambda r: (-r["area"], r["part"], int(r["nodes"][0])))
    regions = regions[:int(max_regions)]
    return {"regions": regions, "n_contact_nodes": int(cn.size), "n_found": n_found,
            "ok": len(regions) >= int(min_regions)}


def _pca_axes(P):
    c = P - P.mean(axis=0)
    _, _, Vt = np.linalg.svd(c, full_matrices=False)
    ax = []
    for k in range(2):
        v = Vt[k].copy() if k < Vt.shape[0] else np.zeros(3)
        if np.any(v):
            j = int(np.argmax(np.abs(v)))
            if v[j] < 0:
                v = -v
        ax.append(v)
    return c, ax


def patch_regions(mesh, cand_mask, *, exclude_mask, n_fill, patch_count, min_nodes, weights) -> dict:
    """공간 패치(D-JIG-3 보충): 후보 = cand ∧ ¬exclude 를 PCA 1·2축 격자 g₁×g₂(P = patch_count)로 분할, 노드 ≥ min_nodes
    셀만, (−면적, −1, 최소 노드) 상위 n_fill 개. 부호 자유(sign_ref 0)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    A = np.asarray(weights["area"], dtype=np.float64)
    nf = int(n_fill)
    cp = np.flatnonzero(np.asarray(cand_mask, bool) & ~np.asarray(exclude_mask, bool))
    if nf <= 0 or cp.size == 0:
        return {"regions": [], "n_cells": 0}
    Pn = int(patch_count)
    c, ax = _pca_axes(X[cp])
    s1, s2 = c @ ax[0], c @ ax[1]
    L1, L2 = float(np.ptp(s1)), float(np.ptp(s2))
    if L2 > 0:
        g1 = max(1, int(round(np.sqrt(Pn * L1 / L2))))
    else:
        g1 = Pn if L1 > 0 else 1
    g2 = max(1, int(np.ceil(Pn / g1)))

    def cell(s, L, g):
        if L <= 0:
            return np.zeros(s.size, dtype=np.int64)
        return np.minimum(np.floor((s - s.min()) / L * g).astype(np.int64), g - 1)

    cid = cell(s1, L1, g1) * g2 + cell(s2, L2, g2)
    order = np.argsort(cid, kind="stable")
    cs, ns = cid[order], cp[order]
    cut = np.flatnonzero(np.diff(cs)) + 1
    regions = []
    for grp in np.split(ns, cut):
        if grp.size < int(min_nodes):
            continue
        regions.append(_region(REGION_PATCH, -1, grp, X, A, np.zeros(3)))
    n_cells = len(regions)
    regions.sort(key=lambda r: (-r["area"], -1, int(r["nodes"][0])))
    return {"regions": regions[:nf], "n_cells": n_cells}


def select_regions(mesh, cand_mask, jig_idx, surf, *, gap_mm, knn, chunk_nodes, max_regions, min_regions, min_nodes,
                   min_area_mm2, patch_count, weights, surf_reason=None) -> dict:
    """가압 영역 = 접촉 영역 유지 + 부족분만 패치 보충(Q-JIG-2 확정 — 보충 규칙의 유일한 구현).
    surf None(no_deck·surf_failed = surf_reason) → n_c = 0. n_fill = 0 (n_c ≥ min_regions) | min_regions − n_c (1 ≤ n_c)
    | min(patch_count, max_regions) (n_c = 0). 패치 후보 = cand ∖ (접촉 영역 노드 ∪ J). 순서 = 접촉 → 패치."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    N = X.shape[0]
    cand = np.asarray(cand_mask, bool)
    if surf is None:
        cr = {"regions": [], "n_contact_nodes": 0, "n_found": 0}
        reason = surf_reason if surf_reason in ("no_deck", "surf_failed") else "no_deck"
    else:
        cr = contact_regions(mesh, cand, surf, gap_mm=gap_mm, knn=knn, chunk_nodes=chunk_nodes,
                             max_regions=max_regions, min_regions=min_regions, min_nodes=min_nodes,
                             min_area_mm2=min_area_mm2, weights=weights)
        reason = "few_contact"
    contact = cr["regions"]
    nc = len(contact)
    if nc >= int(min_regions):
        n_fill = 0
    elif nc >= 1:
        n_fill = int(min_regions) - nc
    else:
        n_fill = min(int(patch_count), int(max_regions))
    excl = np.zeros(N, bool)
    excl[np.asarray(jig_idx, dtype=np.int64)] = True
    for r in contact:
        excl[r["nodes"]] = True
    pr = patch_regions(mesh, cand, exclude_mask=excl, n_fill=n_fill, patch_count=patch_count, min_nodes=min_nodes,
                       weights=weights)
    patch = pr["regions"][:max(int(max_regions) - nc, 0)]
    npch = len(patch)
    if nc and npch:
        frm = "mixed"
    elif nc:
        frm = "contact"
    else:
        frm = "patch"
    return {"regions": contact + patch, "regions_from": frm, "n_contact": nc, "n_patch": npch,
            "fill_reason": reason if n_fill > 0 else None, "n_fill": int(n_fill),
            "n_contact_nodes": int(cr["n_contact_nodes"]), "n_found": int(cr["n_found"]),
            "n_cells": int(pr["n_cells"])}


# ====================================================================== (4b) 모드 관성 기저
def lumped_mass(weights, rho_t) -> np.ndarray:
    """집중질량 m_n = A_n·t_n·ρ_t [t] (D-JIG-15)."""
    return np.asarray(weights["area"], dtype=np.float64) * np.asarray(weights["thick"], dtype=np.float64) * float(rho_t)


def mass_diag6(m) -> np.ndarray:
    """(N,) → (6N,) 대각: 병진 m, 회전 0."""
    m = np.asarray(m, dtype=np.float64).reshape(-1)
    out = np.zeros((m.size, 6))
    out[:, :3] = m[:, None]
    return out.ravel()


def opinv_from(h, n_nodes) -> LinearOperator:
    """지그 정적 분해 h(FactorizedSolve) → 자유 dof 우변 b 에 K_ff⁻¹ b (σ = 0 shift-invert, 추가 분해 0).
    ARPACK mode 3 은 OPinv 를 M·x 에만 적용 → 회전 우변 0. 회전 성분 ≠ 0(> 1e-14·‖b‖) = JIG_MODES_FAILED."""
    N = int(n_nodes)
    free = np.asarray(h.free, dtype=np.int64)
    nf = free.size

    def mv(b):
        b = np.asarray(b, dtype=np.float64).reshape(-1)
        f = np.zeros(6 * N)
        f[free] = b
        f6 = f.reshape(N, 6)
        nb_ = float(np.linalg.norm(b))
        if np.linalg.norm(f6[:, 3:]) > 1e-14 * nb_:
            raise EslError("JIG_MODES_FAILED", "OPinv 우변에 회전 성분 — 지그 분해 재사용 불가(σ ≠ 0 또는 회전 질량)")
        u, _ = h.solve(f6[:, :3].copy())
        return u.reshape(-1)[free]

    return LinearOperator((nf, nf), matvec=mv, dtype=np.float64)


def _mode_sign(v):
    j = int(np.argmax(np.abs(v)))
    return -v if v[j] < 0 else v


def jig_modes(K, M, fixed, n, sigma, *, opinv=None, tol=0.0, maxiter=None) -> dict:
    """구속 고유치 K φ = λ M φ 최저 n 개(shift-invert σ, which LM, v0 = 1/√n_f 결정적).
    K (6N,6N) csr, M (6N,) 대각, fixed = 구속 dof. opinv 주면 그것(σ = 0 지그 분해 재사용), 없으면 (K − σM)_ff splu.
    반환 {"lam" (m,) 오름차순, "phi" (m,N,6), "hz" (m,), "n_conv", "ok", "err"} — 일부만 수렴(ArpackNoConvergence 부분 해)·
    λ ≤ 0 제외는 ok False + 수렴분. 쓸 모드 0 개·그 밖 예외 = EslError("JIG_MODES_FAILED")(``.detail`` = {n_conv, err})."""
    K = sp.csr_matrix(K)
    Md = np.asarray(M, dtype=np.float64).reshape(-1)
    ndof = Md.size
    N = ndof // 6
    free = np.setdiff1d(np.arange(ndof), np.asarray(fixed, dtype=np.int64))
    Kff = K[free][:, free]
    Mff = sp.diags(Md[free]).tocsr()
    nf = free.size
    k = int(min(int(n), nf - 1))
    err = None
    try:
        if opinv is None:
            lu = splu((Kff - float(sigma) * Mff).tocsc())
            opinv = LinearOperator((nf, nf), matvec=lu.solve, dtype=np.float64)
        v0 = np.full(nf, 1.0 / np.sqrt(nf))
        lam, vec = eigsh(Kff, k=k, M=Mff, sigma=float(sigma), which="LM", v0=v0, tol=float(tol), maxiter=maxiter,
                         OPinv=opinv)
    except ArpackNoConvergence as e:
        lam, vec = np.asarray(e.eigenvalues, dtype=np.float64), np.asarray(e.eigenvectors, dtype=np.float64)
        err = "ARPACK_NO_CONVERGENCE"
    except EslError as e:
        ex = EslError("JIG_MODES_FAILED", e.message)
        ex.detail = {"n_conv": 0, "err": e.code}
        raise ex from e
    except Exception as e:  # noqa: BLE001 — 고유치 실패는 정보(모드 없이 진행)
        ex = EslError("JIG_MODES_FAILED", f"{type(e).__name__}: {e}")
        ex.detail = {"n_conv": 0, "err": type(e).__name__}
        raise ex from e
    lam = np.asarray(lam, dtype=np.float64).reshape(-1)
    vec = np.asarray(vec, dtype=np.float64).reshape(nf, -1) if lam.size else np.zeros((nf, 0))
    good = np.isfinite(lam) & (lam > 0)
    if not good.all():
        err = err or "LAMBDA_NONPOSITIVE"
    order = np.argsort(lam[good], kind="stable")
    lam, vec = lam[good][order], vec[:, good][:, order]
    if lam.size == 0:
        ex = EslError("JIG_MODES_FAILED", f"수렴한 양의 고유치 없음 ({err})")
        ex.detail = {"n_conv": 0, "err": err or "NONE"}
        raise ex
    if lam.size < int(n) and err is None:
        err = "FEWER_MODES"
    phi = np.zeros((lam.size, ndof))
    phi[:, free] = vec.T
    phi = phi.reshape(lam.size, N, 6)
    for i in range(lam.size):
        s = phi[i, :, :3].ravel()
        j = int(np.argmax(np.abs(s)))
        if s[j] < 0:
            phi[i] = -phi[i]
    return {"lam": lam, "phi": phi, "hz": np.sqrt(lam) / (2.0 * np.pi), "n_conv": int(lam.size),
            "ok": err is None, "err": err}


def mode_loads(phi, m) -> np.ndarray:
    """관성 하중 g_k = m·φ_k[:, :3], Σ_n ‖g_k,n‖ = 1 N, 부호 = 최대 절댓값 성분 양수 → (m_modes, N, 3)."""
    phi = np.asarray(phi, dtype=np.float64)
    m = np.asarray(m, dtype=np.float64).reshape(-1)
    out = np.zeros((phi.shape[0], phi.shape[1], 3))
    for k in range(phi.shape[0]):
        g = m[:, None] * phi[k, :, :3]
        s = float(np.linalg.norm(g, axis=1).sum())
        if s > 0:
            g = g / s
        out[k] = _mode_sign(g.ravel()).reshape(-1, 3)
    return out


# ====================================================================== (4) 하중 기저
COL_NORMAL, COL_TANGENT, COL_BODY, COL_MODE = 1, 2, 3, 4


def _frame(n):
    k = int(np.argmin(np.abs(n)))
    e = np.zeros(3)
    e[k] = 1.0
    t1 = np.cross(e, n)
    t1 /= np.linalg.norm(t1)
    t2 = np.cross(n, t1)
    return t1, t2


def _layout(basis):
    """(R, 영역 열 수 nc, 체적력 시작, 모드 시작, 모드 수)."""
    R = basis["reg_ptr"].size - 1
    nc = 3 if basis.get("tangential", True) else 1
    b0 = R * nc
    m0 = b0 + (3 if basis.get("body_w") is not None else 0)
    mf = basis.get("mode_f")
    return R, nc, b0, m0, 0 if mf is None else int(mf.shape[0])


def load_basis(mesh, regions, weights, omega_mask, *, body_force: bool, tangential: bool = True, modes=None) -> dict:
    """영역마다 [n, t1, t2](tangential False = [n]) 단위 합력(면적 가중 분산 = RBE3 등가) → (body_force) 체적력
    [e_x, e_y, e_z](A·t 가중, Ω) → 모드 관성 g_k(mode_loads, Σ‖·‖ = 1 N). col_kind 1 법선·2 접선·3 체적력·4 모드."""
    A = np.asarray(weights["area"], dtype=np.float64)
    nrm = np.asarray(weights["normal"], dtype=np.float64)
    th = np.asarray(weights["thick"], dtype=np.float64)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    N = A.size
    R = len(regions)
    ptr = np.zeros(R + 1, dtype=np.int64)
    nodes, ws = [], []
    rdir = np.zeros((R, 3, 3))
    rsign = np.zeros(R, dtype=np.int8)
    rkind = np.zeros(R, dtype=np.int8)
    rpart = np.zeros(R, dtype=np.int64)
    n_free = 0
    for r, reg in enumerate(regions):
        nd = np.asarray(reg["nodes"], dtype=np.int64)
        a = A[nd]
        sa = float(a.sum())
        w = a / sa if sa > 0 else np.full(nd.size, 1.0 / nd.size)
        S = (a[:, None, None] * nrm[nd][:, :, None] * nrm[nd][:, None, :]).sum(axis=0)
        if not np.any(S):
            S = np.cov((X[nd] - X[nd].mean(axis=0)).T) if nd.size > 1 else np.eye(3)
        _, V = np.linalg.eigh(S)
        n = V[:, -1].copy()
        n /= np.linalg.norm(n)
        sign = 0
        if int(reg["kind"]) == REGION_CONTACT:
            sr = float(n @ np.asarray(reg["sign_ref"], dtype=np.float64))
            g = max(float(reg.get("gap_mm", 1.0)), 1.0)
            if abs(sr) <= SIGN_FREE_REL * sa * g:
                n_free += 1
            else:
                sign = 1
                if sr < 0:
                    n = -n
        if sign == 0:
            j = int(np.argmax(np.abs(n)))
            if n[j] < 0:
                n = -n
        t1, t2 = _frame(n)
        rdir[r] = np.stack([n, t1, t2])
        rsign[r] = sign
        rkind[r] = int(reg["kind"])
        rpart[r] = int(reg["part"])
        nodes.append(nd)
        ws.append(w)
        ptr[r + 1] = ptr[r] + nd.size
    body_w = None
    if body_force:
        om = np.asarray(omega_mask, bool)
        at = np.where(om, A * th, 0.0)
        s = float(at.sum())
        if s <= 0:
            raise EslError("INPUT_INVALID", "체적력 기저: Ω 면적×두께 합 0")
        body_w = at / s
    mode_f = None
    if modes is not None and np.asarray(modes).size:
        mode_f = np.asarray(modes, dtype=np.float64).reshape(-1, N, 3)
    nm = 0 if mode_f is None else mode_f.shape[0]
    reg_cols = [COL_NORMAL, COL_TANGENT, COL_TANGENT] if tangential else [COL_NORMAL]
    col_kind = np.array(reg_cols * R + [COL_BODY] * (3 if body_force else 0) + [COL_MODE] * nm, dtype=np.int8)
    return {"col_kind": col_kind, "mode_f": mode_f, "tangential": bool(tangential),
            "reg_ptr": ptr, "reg_node": np.concatenate(nodes) if nodes else np.zeros(0, np.int64),
            "reg_w": np.concatenate(ws) if ws else np.zeros(0), "reg_dir": rdir, "reg_sign": rsign,
            "reg_kind": rkind, "reg_part": rpart, "body_w": body_w, "nb": int(col_kind.size),
            "n_normal_free": int(n_free), "n_nodes": int(N)}


def forces(basis, a, n_nodes) -> np.ndarray:
    """F = Σ_k a_k f_k (N,3) — 영역 → 체적력 → 모드 순서로 누적(결정적)."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    nb = int(basis["nb"])
    if a.size != nb:
        raise EslError("INPUT_INVALID", f"a 길이 {a.size} ≠ nb {nb}")
    F = np.zeros((int(n_nodes), 3))
    ptr, nd, w, D = basis["reg_ptr"], basis["reg_node"], basis["reg_w"], basis["reg_dir"]
    R, nc, b0, m0, nm = _layout(basis)
    for r in range(R):
        v = a[nc * r:nc * r + nc] @ D[r, :nc]
        s, e = ptr[r], ptr[r + 1]
        np.add.at(F, nd[s:e], w[s:e, None] * v)
    if basis.get("body_w") is not None:
        F += basis["body_w"][:, None] * a[b0:b0 + 3]
    for k in range(nm):
        if a[m0 + k] != 0.0:
            F += a[m0 + k] * basis["mode_f"][k]
    return F


def _unit(nb, k):
    e = np.zeros(nb)
    e[k] = 1.0
    return e


def load_density(basis, weights) -> dict:
    """jig.npz 노드 면적당 밀도 키(§5.5, v0.24.0 메시 독립 전달용): node_area (N,), reg_area (R,), reg_q (R,3,3) =
    reg_dir/area_r, body_q (N,) = body_w/node_area | None, mode_q (m,N,3) = mode_f/node_area | None (면적 0 노드 = 0)."""
    A = np.asarray(weights["area"], dtype=np.float64)
    ptr, nd = basis["reg_ptr"], basis["reg_node"]
    R = ptr.size - 1
    ra = np.array([float(A[nd[ptr[r]:ptr[r + 1]]].sum()) for r in range(R)])
    rq = np.divide(basis["reg_dir"], ra[:, None, None], out=np.zeros_like(basis["reg_dir"]),
                   where=ra[:, None, None] > 0)
    bq = None
    if basis.get("body_w") is not None:
        bq = np.divide(basis["body_w"], A, out=np.zeros_like(A), where=A > 0)
    mq = None
    if basis.get("mode_f") is not None:
        mf = basis["mode_f"]
        mq = np.divide(mf, A[None, :, None], out=np.zeros_like(mf), where=A[None, :, None] > 0)
    return {"node_area": A.copy(), "reg_area": ra, "reg_q": rq, "body_q": bq, "mode_q": mq}


# ====================================================================== (5) 해석 · 보정
def factor(mesh, jig_idx, solver_cfg):
    """K(mesh 좌표), spc = J 병진 123 → 분해 1회. SOLVER_SINGULAR → JIG_SUPPORT_DEGENERATE. 모드용 K = h.model.K()."""
    cfg = solver_cfg or {}
    sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                    drill_factor=float(cfg.get("drill_factor", 1e-4)), backend=str(cfg.get("backend", "auto")),
                    **solver_check_kwargs(cfg))
    try:
        return sm.factorize([(int(i), "123") for i in np.asarray(jig_idx, dtype=np.int64)])
    except EslError as e:
        if e.code == "SOLVER_SINGULAR":
            raise EslError("JIG_SUPPORT_DEGENERATE", e.message) from e
        raise


def basis_response(h, basis, fit_mask) -> dict:
    """U_k = u[F, :3] (k = 1..nb) — 같은 분해로 nb 회 solve."""
    nb = int(basis["nb"])
    N = int(h.model.n_nodes)
    fm = np.asarray(fit_mask, bool)
    U = np.zeros((nb, int(fm.sum()), 3))
    null = []
    for k in range(nb):
        u, _ = h.solve(forces(basis, _unit(nb, k), N))
        U[k] = u[fm, :3]
        if not np.any(U[k]):
            null.append(k)
    return {"U": U, "null_cols": null}


def _weighted(V, a, n, w_ip):
    """W V (노드별 W_n = a_n(nnᵀ + w_ip(I − nnᵀ))), V (…, M, 3)."""
    vn = np.einsum("...mi,mi->...m", V, n)
    return a[:, None] * (w_ip * V + (1.0 - w_ip) * vn[..., None] * n)


def fit_loads(U, u_tgt_fit, w_fit, n_fit, basis, *, ridge, w_inplane, reg_force, reg_modes=0.0, drop_kinds=()) -> dict:
    """법선/면내 가중 최소제곱 + 하중 Tikhonov(D-JIG-5·16):
    min (Ua − u)ᵀW(Ua − u) + ḡ_N·(reg_force·Σ_{col_kind ∈ 2,3} a² + reg_modes·Σ_{col_kind = 4} a²) (D-JIG-17 분리),
    W_n = (A_n/mean A)(nnᵀ + w_ip(I − nnᵀ)), ḡ_N = mean_{법선 열} G_kk. 법선 열 = ridge 만.
    정규화 b = D_s a: Ĝ = D_s⁻¹GD_s⁻¹ + λI + diag(ρ_k·ḡ_N/G_kk) = LLᵀ (ρ_k = reg_force | reg_modes | 0),
    b* = BVLS argmin ‖Lᵀb − L⁻¹D_s⁻¹h‖² (접촉 법선 b ≥ 0). drop_kinds 열은 a = 0(모드 제외 맞춤 = (4,))."""
    U = np.asarray(U, dtype=np.float64)
    nb = U.shape[0]
    ut = np.asarray(u_tgt_fit, dtype=np.float64)
    aw = np.asarray(w_fit, dtype=np.float64)
    aw = aw / aw.mean() if aw.size and aw.mean() > 0 else aw
    nn = np.asarray(n_fit, dtype=np.float64)
    wip = float(w_inplane)
    ck = np.asarray(basis["col_kind"]).astype(np.int64)
    G = np.zeros((nb, nb))
    hv = np.zeros(nb)
    for k in range(nb):
        WUk = _weighted(U[k], aw, nn, wip)
        G[k] = np.einsum("lmi,mi->l", U, WUk)
        hv[k] = float(np.sum(WUk * ut))
    G = 0.5 * (G + G.T)
    dg = np.maximum(np.diag(G), 0.0)
    s = np.sqrt(dg)
    smax = float(s.max()) if s.size else 0.0
    normal = ck == COL_NORMAL
    gN = float(dg[normal].mean()) if normal.any() else (float(dg.mean()) if dg.size else 0.0)
    use = (s > 1e-14 * smax) if smax > 0 else np.zeros(nb, bool)
    use &= ~np.isin(ck, np.asarray(tuple(drop_kinds), dtype=np.int64))
    act = np.flatnonzero(use)
    a = np.zeros(nb)
    lo = np.full(nb, -np.inf)
    R, nc, _, _, _ = _layout(basis)
    for r in range(R):
        if int(basis["reg_sign"][r]) > 0:
            lo[nc * r] = 0.0
    n_bound = 0
    if act.size:
        d = s[act]
        rho = np.where(np.isin(ck[act], (COL_TANGENT, COL_BODY)), float(reg_force),
                       np.where(ck[act] == COL_MODE, float(reg_modes), 0.0))
        pen = rho * gN / dg[act]
        Gh = G[np.ix_(act, act)] / d[:, None] / d[None, :] + np.diag(float(ridge) + pen)
        Gh = 0.5 * (Gh + Gh.T)
        try:
            L = np.linalg.cholesky(Gh)
        except np.linalg.LinAlgError as e:
            raise EslError("SOLVER_SINGULAR", "지그 보정 정규방정식 특이 — jig.ridge > 0 필요") from e
        rhs = np.linalg.solve(L, hv[act] / d)
        lb = lo[act]
        if np.all(np.isinf(lb)):
            b = np.linalg.solve(L.T, rhs)
        else:
            res = lsq_linear(L.T, rhs, bounds=(lb, np.full(act.size, np.inf)), method="bvls", tol=1e-12)
            b = res.x
            b = np.where(np.isfinite(lb) & (b < 0), 0.0, b)
            n_bound = int(np.sum(np.isfinite(lb) & (b <= 0.0)))
        a[act] = b / d
    r = np.einsum("k,kmi->mi", a, U) - ut
    den = float(np.sum(_weighted(ut, aw, nn, wip) * ut))
    resid = float(np.sqrt(np.sum(_weighted(r, aw, nn, wip) * r) / den)) if den > 0 else 0.0
    return {"a": a, "resid_rel": resid, "n_bound_active": n_bound, "g_N": gN}


def respond(h, loads, *, umax_mask=None, keep_u=False) -> list[dict]:
    """하중 [(entry_id, F (N,3))] → [{entry_id, C_jig = F·u, umax_jig = max_{umax_mask} ‖u‖, react_rel, u}]."""
    out = []
    mk = None if umax_mask is None else np.asarray(umax_mask, bool)
    for eid, F in loads:
        F = np.asarray(F, dtype=np.float64)
        u, Rf = h.solve(F)
        ut = u[:, :3]
        C = float(np.sum(F * ut))
        uu = ut if mk is None else ut[mk]
        umax = float(np.linalg.norm(uu, axis=1).max()) if uu.size else 0.0
        sabs = float(np.linalg.norm(F, axis=1).sum())
        rr = float(np.linalg.norm(F.sum(axis=0) + Rf.sum(axis=0)) / sabs) if sabs > 0 else 0.0
        out.append({"entry_id": eid, "C_jig": C, "umax_jig": umax, "react_rel": rr,
                    "u": ut.copy() if keep_u else None})
    return out


# ====================================================================== (6) 기준 재현 진단
def _quality(f, t, A):
    """맞춤 노드 값 f·t (M,3) → {mac, umax_err, err_p95, resid_rel} + umax 두 개."""
    num = float(np.sum(f * t)) ** 2
    den = float(np.sum(f * f)) * float(np.sum(t * t))
    mac = num / den if den > 0 else 0.0
    nt = np.linalg.norm(t, axis=1)
    umax_tgt = float(nt.max()) if nt.size else 0.0
    umax_fit = float(np.linalg.norm(f, axis=1).max()) if f.size else 0.0
    e = np.linalg.norm(f - t, axis=1)
    if umax_tgt > 0:
        umax_err = abs(umax_fit - umax_tgt) / umax_tgt
        p95 = float(np.percentile(e, 95)) / umax_tgt
    else:
        umax_err = 0.0 if umax_fit == 0 else float("inf")
        p95 = 0.0 if not e.size or e.max() == 0 else float("inf")
    dA = float(np.sum(A * nt ** 2))
    resid = float(np.sqrt(np.sum(A * e ** 2) / dA)) if dA > 0 else 0.0
    return {"mac": float(mac), "umax_err": float(umax_err), "err_p95": float(p95), "resid_rel": resid}, umax_tgt, umax_fit


def _col_abs(basis, a) -> float:
    """Σ_k Σ_n ‖a_k f_k(n)‖ — 열마다 노드 하중 노름 합(영역 = |a|·Σw, 체적력 = |a|·Σbody_w, 모드 = |a|·Σ‖g‖)."""
    a = np.asarray(a, dtype=np.float64)
    R, nc, b0, m0, nm = _layout(basis)
    ptr, w = basis["reg_ptr"], basis["reg_w"]
    tot = 0.0
    for r in range(R):
        sw = float(w[ptr[r]:ptr[r + 1]].sum())
        for j in range(nc):
            tot += abs(float(a[nc * r + j])) * sw * float(np.linalg.norm(basis["reg_dir"][r, j]))
    if basis.get("body_w") is not None:
        sb = float(np.abs(basis["body_w"]).sum())
        tot += sb * float(np.abs(a[b0:b0 + 3]).sum())
    for k in range(nm):
        tot += abs(float(a[m0 + k])) * float(np.linalg.norm(basis["mode_f"][k], axis=1).sum())
    return tot


def fit_report(u_fit, u_tgt, fit_mask, weights, basis, a, *, jig_idx, active_tol, u_fit_nomodes=None) -> dict:
    """MAC·umax 오차·P95·잔차비(모드 포함 with_modes / 제외 without_modes)·영역 합력·모드 계수·활성 수·상쇄비(D-JIG-6·15·17).
    work_eff = |Σ f·u_fit| / Σ ‖f‖‖u_fit‖ (병진, 비지그 노드 — JIG_LOAD_CANCEL 판정, D-JIG-18). 정보용: cancel_rel =
    1 − Σ_n‖F_n‖ / Σ_kΣ_n‖a_k f_k(n)‖ (열 사이 상쇄, F_node_abs·F_col_abs), F_sum_abs = Σ 영역 합력 노름 + ‖체적력‖ + Σ|a_모드|.
    u_fit_nomodes = 모드 제외 맞춤 변위((N,3) 또는 맞춤 노드 (M,3) — U a), None = without_modes null. tie_rel 도 함께."""
    fm = np.asarray(fit_mask, bool)
    uf = np.asarray(u_fit, dtype=np.float64)[:, :3]
    ut = np.asarray(u_tgt, dtype=np.float64)[:, :3]
    A = np.asarray(weights["area"], dtype=np.float64)[fm]
    t = ut[fm]
    wm, umax_tgt, umax_fit = _quality(uf[fm], t, A)
    wo = None
    if u_fit_nomodes is not None:
        un = np.asarray(u_fit_nomodes, dtype=np.float64)[:, :3]
        wo = _quality(un[fm] if un.shape[0] == fm.size else un, t, A)[0]
    J = np.asarray(jig_idx, dtype=np.int64)
    tj = float(np.linalg.norm(ut[J], axis=1).max()) if J.size else 0.0
    tie_rel = tj / umax_tgt if umax_tgt > 0 else 0.0
    a = np.asarray(a, dtype=np.float64)
    D = basis["reg_dir"]
    R, nc, b0, m0, nm = _layout(basis)
    Rv = [a[nc * r:nc * r + nc] @ D[r, :nc] for r in range(R)]
    mags = [float(np.linalg.norm(v)) for v in Rv]
    mmax = max(mags) if mags else 0.0
    body = a[b0:b0 + 3] if basis.get("body_w") is not None else None
    rows = []
    for r in range(R):
        act = bool(mags[r] > float(active_tol) * mmax) if mmax > 0 else False
        k = int(basis["reg_kind"][r])
        ft = (float(a[nc * r + 1]), float(a[nc * r + 2])) if nc == 3 else (0.0, 0.0)
        rows.append({"region": r, "kind": KIND_NAME.get(k, str(k)),
                     "part": int(basis["reg_part"][r]) if k == REGION_CONTACT else None,
                     "F_n": float(a[nc * r]), "F_t1": ft[0], "F_t2": ft[1],
                     "F": [float(x) for x in Rv[r]], "active": act})
    fsum = float(sum(mags))
    if body is not None:
        fsum += float(np.linalg.norm(body))
    modes = []
    for k in range(nm):
        ak = float(a[m0 + k])
        modes.append({"k": k, "a": ak})
        fsum += abs(ak)
    # 상쇄비(D-JIG-17): 기저 열 사이 상호 상쇄만 — 1 − Σ_n ‖Σ_k a_k f_k(n)‖ / Σ_k Σ_n ‖a_k f_k(n)‖
    # (단일 열의 자기평형 — 고차 모드 합력 ≈ 0 — 은 상쇄 아님. 한 열만 쓰면 0)
    Fn = forces(basis, a, int(basis["n_nodes"]))
    num = float(np.linalg.norm(Fn, axis=1).sum())
    den = _col_abs(basis, a)
    cancel = 1.0 - num / den if den > 0 else 0.0
    # 일 효율(D-JIG-18 — JIG_LOAD_CANCEL 판정): |Σ f·u_fit| / Σ ‖f‖‖u_fit‖ (병진, 비지그 노드)
    nj = np.ones(Fn.shape[0], bool)
    nj[J] = False
    fw, uw_ = Fn[nj], uf[nj]
    wden = float(np.sum(np.linalg.norm(fw, axis=1) * np.linalg.norm(uw_, axis=1)))
    work_eff = abs(float(np.sum(fw * uw_))) / wden if wden > 0 else 0.0
    return {"with_modes": wm, "without_modes": wo, "modes": modes, **wm, "umax_tgt": umax_tgt, "umax_fit": umax_fit,
            "F_sum_abs": fsum, "F_node_abs": num, "F_col_abs": den, "cancel_rel": float(max(cancel, 0.0)),
            "work_eff": float(work_eff),
            "n_active": int(sum(r_["active"] for r_ in rows)),
            "body": None if body is None else [float(x) for x in body], "forces": rows, "tie_rel": float(tie_rel)}


# ====================================================================== (7) 설계 비교
def design_response(mesh, jig_idx, loads, solver_cfg, *, umax_mask=None, keep_u=False) -> dict:
    """안 d: K_d(안 좌표)·같은 J·같은 F_i(하중 제어 — 모드 하중도 기준 고정 벡터, 재계산 없음) → respond 행 + 통계.
    keep_u = 행에 u (N,3)(v0.23.2 지그 3D — 기본 False 는 이전과 같음)."""
    t0 = time.monotonic()
    h = factor(mesh, jig_idx, solver_cfg)
    rows = respond(h, loads, umax_mask=umax_mask, keep_u=keep_u)
    return {"rows": rows, "stats": {"seconds": time.monotonic() - t0, "n_solves": int(h.n_solves),
                                    "backend": str(h.model.stats.get("backend"))}}


def support_sample(x, jig_idx, m: int) -> np.ndarray:
    """v0.23.2 지그 3D tie 마커(표시만): 지그 노드에서 최원점 샘플링 min(|J|, m) 개 — 첫 점 = 가장 작은 노드 인덱스, 이후 고른 점들까지
    최소 거리가 최대인 점(동률 = 작은 인덱스). 반환 = 노드 인덱스(고른 순서). 결정적."""
    J = np.unique(np.asarray(jig_idx, dtype=np.int64))
    m = int(m)
    if m <= 0 or J.size == 0:
        return np.zeros(0, dtype=np.int64)
    if J.size <= m:
        return J
    P = np.asarray(x, dtype=np.float64)[J]
    pick = [0]
    d = np.linalg.norm(P - P[0], axis=1)
    for _ in range(m - 1):
        k = int(np.argmax(d))                       # argmax = 첫 최대(작은 인덱스 — J 정렬)
        pick.append(k)
        d = np.minimum(d, np.linalg.norm(P - P[k], axis=1))
    return J[np.asarray(pick, dtype=np.int64)]


def hash_view(jig_cfg: dict) -> dict:
    """해시용 사본: HASH_EXCLUDE(임계값·보고용 키) 제외(D-JIG-11)."""
    return {k: v for k, v in dict(jig_cfg).items() if k not in HASH_EXCLUDE}


# ====================================================================== v0.23.3 지그 진단 뷰(esl_jig_view.md §1.2) — 보고만, 계산 불변
DIAG_KINDS = (("region", (COL_NORMAL, COL_TANGENT)), ("body", (COL_BODY,)), ("mode", (COL_MODE,)))


def kind_forces(basis, a, n_nodes) -> dict:
    """열 종류별 하중 {region: 법선·접선 열, body: 체적력 열, mode: 모드 열} (N,3) — 각 = forces(basis, a·[col_kind ∈ 종류]).
    선형이라 합 = forces(basis, a)(누적 순서만 달라 1e-12 상대 안)."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    ck = np.asarray(basis["col_kind"])
    return {name: forces(basis, np.where(np.isin(ck, ks), a, 0.0), n_nodes) for name, ks in DIAG_KINDS}


def kind_response(h, parts: dict) -> dict:
    """종류별 하중 parts{k: (N,3)} 를 같은 분해로 풀어 {u: Σ u_k (N,3), parts: {k: u_k (N,3)}}(하중 0 종류는 solve 생략·0)."""
    out, tot = {}, None
    for k, F in parts.items():
        F = np.asarray(F, dtype=np.float64)
        if not np.any(F):
            uk = np.zeros_like(F)
        else:
            uk = np.asarray(h.solve(F)[0], dtype=np.float64)[:, :3]
        out[k] = uk
        tot = uk.copy() if tot is None else tot + uk
    return {"u": tot, "parts": out}


def diag_report(u_tgt, u_fit, parts, weights, fit_mask) -> dict:
    """진단 보강(맞춤 노드 F): contrib{k} = ‖u_k‖_F/‖u_fit‖_F(병진 L2 — 종류끼리 상쇄하면 합 > 1), tgt_out_frac = 목표 면외 에너지 비
    Σ A (n̂·u_tgt)² / Σ A ‖u_tgt‖²(면내 = 1 − 값), err_max = max ‖u_fit − u_tgt‖, umax_tgt·umax_fit."""
    fm = np.asarray(fit_mask, bool)
    t = np.asarray(u_tgt, dtype=np.float64)[fm]
    f = np.asarray(u_fit, dtype=np.float64)[fm]
    A = np.asarray(weights["area"], dtype=np.float64)[fm]
    n = np.asarray(weights["normal"], dtype=np.float64)[fm]
    nf = float(np.linalg.norm(f))
    contrib = {k: (float(np.linalg.norm(np.asarray(v, dtype=np.float64)[fm])) / nf if nf > 0 else 0.0)
               for k, v in parts.items()}
    tot = float(np.sum(A * np.sum(t * t, axis=1)))
    out_e = float(np.sum(A * np.sum(t * n, axis=1) ** 2))
    e = np.linalg.norm(f - t, axis=1)
    return {"contrib": contrib, "tgt_out_frac": out_e / tot if tot > 0 else 0.0,
            "err_max": float(e.max()) if e.size else 0.0,
            "umax_tgt": float(np.linalg.norm(t, axis=1).max()) if t.size else 0.0,
            "umax_fit": float(np.linalg.norm(f, axis=1).max()) if f.size else 0.0}


def region_vertices(basis) -> list:
    """영역마다 노드 인덱스(정렬) — reg_ptr·reg_node 그대로."""
    ptr, nd = np.asarray(basis["reg_ptr"]), np.asarray(basis["reg_node"], dtype=np.int64)
    return [np.sort(nd[ptr[r]:ptr[r + 1]]) for r in range(ptr.size - 1)]
