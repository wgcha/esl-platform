"""④ 형상 비교 하중 전달 — 일 등가(W) · 셀(C) · 지지 이전 · 평가 영역 · 진단 (계약 esl_load_transfer.md, v0.20.0).

- 방식 W(D-0.20.0-LT-2): f_t = T_tᵀ f_A. A(ESL 원본 메시) 노드마다 대상 영역 요소 중 최근접점(TRIA = Ericson 점-삼각형,
  QUAD = 두 삼각형 최근접점 → 쌍선형 (r,s) Gauss-Newton 역사상)의 형상함수로 힘을 나눈다(분할 1 → 합력 보존).
  동일 메시(노드 ID 집합 같음·좌표 차 ≤ coord_check.max_rel × bbox 대각) = ``target.entry_load`` S1 재배열(① 과 비트 동일).
- 방식 C(LT-6): cell_size_mm null = 기존 24×14 요약·``mapping.to_target`` 그대로(legacy), 값 s = ESL raw 새 요약(셀마다
  최소노름 6 제약, 노드 0~2 개·공선 셀은 그 셀 A 노드 힘을 W 로).
- LT-4 합력·합모멘트 보존 보정(W·새 C): 원본 f_A 의 값으로 영역 노드 최소노름 보정(합 0 강제 아님).
- 대규모: 사영은 A 노드 청크(``CHUNK``) × 요소 중심 cKDTree k 후보 — 피크 메모리 O(N_A + N_e + 청크·k).

함수: ``resolve``·``region_of``·``build_work``·``apply_work``·``conserve``·``cell_loads``·``shape_loads``·
``transfer_supports``·``load_corr``·``mac``·``diag_rows``·``summary``. 매핑·대상·평가·그래프 모듈은 가져다 쓰기만.
"""
from __future__ import annotations

import hashlib
import time

import numpy as np

from esl.errors import EslError
from esl.library import mapping as mp
from esl.library import normalize as nz

SCHEMA = 1
DIAG_SCHEMA = "esl/doe_load_transfer_diag/1"
METHODS = ("work", "cell")
SUPPORTS = ("transfer", "auto")
REGION_MODES = ("auto", "a_bbox", "largest", "all")
CHUNK = 20000                 # 사영 A 노드 청크
BATCH_MIN_CELLS = 10000       # LT-6: 셀 1만 개 이상 = 6×6 정규방정식 일괄 풀이
TIE_REL = 1e-12               # LT-2 거리 동률(× h) → 작은 요소 번호
NEWTON_TOL = 1e-10            # LT-2 잔차 ≤ 1e-10·h (자연좌표 증분)
CELL_MAX_MM = 200.0
UNBALANCED_REL = 1e-6         # LT-4 LT_ESL_UNBALANCED


# ====================================================================== 설정
def resolve(spec_lt: dict | None) -> dict | None:
    """스냅샷 ``doe.load_transfer``(해석된 dict) → 기본값 위에 합친 설정. None = legacy(키 없음)."""
    if spec_lt is None:
        return None
    from esl.doe import DEFAULTS, _deep_merge
    if not isinstance(spec_lt, dict):
        raise EslError("CONFIG_INVALID", "load_transfer 는 매핑이어야 함")
    lt = _deep_merge(DEFAULTS["compare"]["load_transfer"], {k: v for k, v in spec_lt.items() if k != "schema"})

    def bad(msg):
        raise EslError("CONFIG_INVALID", f"load_transfer.{msg}")
    if lt["method"] not in METHODS:
        bad("method work|cell")
    if lt["support"] not in SUPPORTS:
        bad("support transfer|auto")
    if (lt.get("region") or {}).get("mode") not in REGION_MODES:
        bad("region.mode auto|a_bbox|largest|all")
    cmin = float(lt["cell_min_mm"])
    for k, v in (("cell_size_mm", lt["cell_size_mm"]), ("diag.alt_cell_size_mm", lt["diag"]["alt_cell_size_mm"])):
        if v is not None and not cmin <= float(v) <= CELL_MAX_MM:
            raise EslError("LOAD_TRANSFER_INVALID", f"load_transfer.{k} {v} 는 {cmin:g}..{CELL_MAX_MM:g} mm")
    if lt["method"] == "work" and spec_lt.get("cell_size_mm") is not None:
        raise EslError("LOAD_TRANSFER_INVALID", "load_transfer: work 에는 cell_size_mm 를 줄 수 없음")
    w = lt["work"]
    if not 1 <= int(w["knn"]) <= 64 or not 1 <= int(w["newton_iter"]) <= 50:
        bad("work.knn 1..64, newton_iter 1..50")
    if not 0.0 <= float(w["far_warn_frac"]) <= float(w["far_fail_frac"]) <= 1.0:
        bad("work 0 ≤ far_warn_frac ≤ far_fail_frac ≤ 1")
    return lt


def variant_label(method: str, cell_size_mm) -> str:
    """진단 variant 이름: work | cell:legacy | cell:<s>."""
    if method == "work":
        return "work"
    return "cell:legacy" if cell_size_mm is None else f"cell:{float(cell_size_mm):g}"


def primary_variant(lt: dict) -> tuple[str, float | None]:
    return str(lt["method"]), (None if lt["method"] == "work" else lt.get("cell_size_mm"))


def alt_variant(lt: dict) -> tuple[str, float | None] | None:
    """다른 방식(diag.alt): work ↔ cell(alt_cell_size_mm). 진단 끔·alt 끔 = None."""
    dg = lt.get("diag") or {}
    if not dg.get("enabled") or not dg.get("alt"):
        return None
    if lt["method"] == "work":
        return "cell", dg.get("alt_cell_size_mm")
    return "work", None


def hash_view(lt: dict) -> dict:
    """LT-12 이어하기 해시 대상(diag 제외)."""
    return {k: lt.get(k) for k in ("method", "cell_size_mm", "work", "support", "support_tol_mm", "region")}


def public(lt: dict) -> dict:
    """결과·스냅샷 요약 {method, cell_size_mm, support, region_mode}."""
    return {"method": lt["method"], "cell_size_mm": lt.get("cell_size_mm"), "support": lt["support"],
            "region_mode": (lt.get("region") or {}).get("mode")}


# ====================================================================== 메시 도우미
def a_mesh_sha(raw: dict) -> str:
    """ESL 원본 메시 sha(앞 16자) — node_id·x0·conn·elem_type."""
    h = hashlib.sha256(b"esl/lt_amesh/1\n")
    for k, dt in (("node_id", "<i8"), ("x0", "<f8"), ("conn", "<i8"), ("elem_type", "<i8")):
        a = np.ascontiguousarray(np.asarray(raw[k]).astype(dt))
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()[:16]


def mesh_sha(mesh: dict) -> str:
    return a_mesh_sha(mesh)


def region_of(mesh: dict, a_xyz, rcfg: dict, h: float) -> tuple[np.ndarray | None, dict]:
    """LT-8 형상 평가 영역(③ ``step_graph.region_mask`` 재사용) → (요소 bool | None(= 전체), 정보)."""
    from esl.doe import step_graph as sg
    cfg = {"select": {"step_graph": {"region": {k: rcfg.get(k) for k in ("mode", "pad_mm", "min_frac")}}}}
    m, info = sg.region_mask(mesh, a_xyz, cfg, h)
    return (None if info["n_out"] == 0 else m), info


def region_messages(info: dict, rcfg: dict) -> tuple[list[dict], list[dict]]:
    """(경고 COMPARE_REGION_SMALL, 정보 COMPARE_REGION) 구조화 dict."""
    warns, infos = [], []
    if info["n_out"] > 0:
        infos.append({"code": "COMPARE_REGION", "n_in": info["n_in"], "n_out": info["n_out"],
                      "out_bbox": info["out_bbox"], "mode": info["mode"]})
    if float(info["n_in"]) < float(rcfg["min_frac"]) * float(info["n_in"] + info["n_out"]):
        warns.append({"code": "COMPARE_REGION_SMALL", "frac": info["frac"], "min_frac": float(rcfg["min_frac"])})
    return warns, infos


def region_nodes(mesh: dict, region) -> np.ndarray:
    from esl.doe import step_graph as sg
    return sg.region_nodes(mesh, region)


def _corners(mesh: dict) -> tuple[np.ndarray, np.ndarray]:
    """(E,4) 노드 인덱스(TRIA 4번째 = 1번째 — 가중 0) · quad 마스크."""
    C = np.asarray(mesh["conn"], dtype=np.int64)
    q = np.asarray(mesh["elem_type"]).astype(int) == 4
    C4 = C[:, :4].copy()
    C4[~q, 3] = C4[~q, 0]
    return C4, q


def identity_ok(raw: dict, t_mesh: dict, tol_rel: float) -> bool:
    """LT-2 동일 메시 빠른 경로: 노드 ID 집합 같음 ∧ 같은 ID 좌표 차 최대 ≤ tol_rel × A bbox 대각(전역 원좌표)."""
    na = np.asarray(raw["node_id"], dtype=np.int64)
    nt = np.asarray(t_mesh["node_id"], dtype=np.int64)
    if na.size != nt.size:
        return False
    oa, ot = np.argsort(na, kind="stable"), np.argsort(nt, kind="stable")
    if not np.array_equal(na[oa], nt[ot]):
        return False
    xa = np.asarray(raw["x0"], dtype=np.float64)[oa]
    xt = np.asarray(t_mesh["x0"], dtype=np.float64)[ot]
    diag = float(np.linalg.norm(xa.max(axis=0) - xa.min(axis=0))) if xa.size else 0.0
    dmax = float(np.max(np.linalg.norm(xa - xt, axis=1))) if xa.size else 0.0
    return dmax <= float(tol_rel) * (diag or 1.0)


# ====================================================================== 사영 (LT-2)
def _closest_tri(p, a, b, c):
    """점-삼각형 최근접점(Ericson 5.1.5, 경계 clamp) — 브로드캐스트 (…,3). 반환 (점, 무게중심 (…,3))."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("...i,...i", ab, ap)
    d2 = np.einsum("...i,...i", ac, ap)
    bp = p - b
    d3 = np.einsum("...i,...i", ab, bp)
    d4 = np.einsum("...i,...i", ac, bp)
    cp = p - c
    d5 = np.einsum("...i,...i", ab, cp)
    d6 = np.einsum("...i,...i", ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    sh = d1.shape
    lam = np.zeros(sh + (3,))
    done = np.zeros(sh, bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (d1 <= 0) & (d2 <= 0)                                   # 꼭짓점 a
        lam[m] = (1.0, 0.0, 0.0)
        done |= m
        m = ~done & (d3 >= 0) & (d4 <= d3)                          # 꼭짓점 b
        lam[m] = (0.0, 1.0, 0.0)
        done |= m
        m = ~done & (vc <= 0) & (d1 >= 0) & (d3 <= 0)               # 모서리 ab
        v = d1 / (d1 - d3)
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - v[m], v[m], 0.0
        done |= m
        m = ~done & (d6 >= 0) & (d5 <= d6)                          # 꼭짓점 c
        lam[m] = (0.0, 0.0, 1.0)
        done |= m
        m = ~done & (vb <= 0) & (d2 >= 0) & (d6 <= 0)               # 모서리 ac
        w = d2 / (d2 - d6)
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - w[m], 0.0, w[m]
        done |= m
        m = ~done & (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)  # 모서리 bc
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        lam[m, 0], lam[m, 1], lam[m, 2] = 0.0, 1.0 - w[m], w[m]
        done |= m
        m = ~done                                                   # 면 안
        den = va + vb + vc
        v = vb / den
        w = vc / den
        lam[m, 0], lam[m, 1], lam[m, 2] = 1.0 - v[m] - w[m], v[m], w[m]
    bad = ~np.all(np.isfinite(lam), axis=-1)                        # 퇴화 삼각형 → 가장 가까운 꼭짓점
    if bad.any():
        dd = np.stack([np.linalg.norm(p - a, axis=-1), np.linalg.norm(p - b, axis=-1),
                       np.linalg.norm(p - c, axis=-1)], axis=-1)
        k = np.argmin(dd, axis=-1)
        lam[bad] = 0.0
        lam[bad, k[bad]] = 1.0
    q = lam[..., 0:1] * a + lam[..., 1:2] * b + lam[..., 2:3] * c
    return q, lam


def _bilinear_N(r, s):
    return 0.25 * np.stack([(1 - r) * (1 - s), (1 + r) * (1 - s), (1 + r) * (1 + s), (1 - r) * (1 + s)], axis=-1)


def _quad_newton(P, Xq, r, s, n_iter: int):
    """쌍선형 사상 x(r,s) 의 P 최근접 (r,s) Gauss-Newton(≤ n_iter, 증분 ≤ NEWTON_TOL) → (r, s, 수렴)."""
    conv = np.zeros(r.shape, bool)
    for _ in range(int(n_iter)):
        N = _bilinear_N(r, s)
        x = np.einsum("nk,nki->ni", N, Xq)
        dr = 0.25 * np.stack([-(1 - s), (1 - s), (1 + s), -(1 + s)], axis=-1)
        ds = 0.25 * np.stack([-(1 - r), -(1 + r), (1 + r), (1 - r)], axis=-1)
        xr = np.einsum("nk,nki->ni", dr, Xq)
        xs = np.einsum("nk,nki->ni", ds, Xq)
        res = P - x
        a11 = np.einsum("ni,ni->n", xr, xr)
        a12 = np.einsum("ni,ni->n", xr, xs)
        a22 = np.einsum("ni,ni->n", xs, xs)
        b1 = np.einsum("ni,ni->n", xr, res)
        b2 = np.einsum("ni,ni->n", xs, res)
        det = a11 * a22 - a12 * a12
        ok = det > 0
        with np.errstate(divide="ignore", invalid="ignore"):
            d_r = np.where(ok, (a22 * b1 - a12 * b2) / det, 0.0)
            d_s = np.where(ok, (a11 * b2 - a12 * b1) / det, 0.0)
        live = ~conv & ok
        r = np.where(live, r + d_r, r)
        s = np.where(live, s + d_s, s)
        conv |= live & (np.maximum(np.abs(d_r), np.abs(d_s)) <= NEWTON_TOL)
        if conv.all():
            break
    return r, s, conv


def build_work(a_x, t_mesh: dict, region, wcfg: dict, h: float) -> dict:
    """LT-2 W 연산자: A 노드 → 대상 영역 요소 최근접점 형상함수. 반환 {elem, nodes (N_A,4), w (N_A,4), dist,
    newton_fallback_n, max_dist_mm, seconds}. 좌표 = 전역 원좌표."""
    from scipy.spatial import cKDTree

    from esl.doe import step_graph as sg
    t0 = time.monotonic()
    XA = np.asarray(a_x, dtype=np.float64)
    X = np.asarray(t_mesh["x0"], dtype=np.float64)
    C4, isq = _corners(t_mesh)
    elems = np.arange(C4.shape[0]) if region is None else np.flatnonzero(np.asarray(region, bool))
    if elems.size == 0:
        raise EslError("MAPPING_DEGENERATE", "하중 전달 대상 영역 요소가 없음")
    cen = sg.centroids({"x0": X, "conn": t_mesh["conn"], "elem_type": t_mesh["elem_type"]})[elems]
    tree = cKDTree(cen)
    k = int(min(int(wcfg["knn"]), elems.size))
    na = XA.shape[0]
    out_e = np.zeros(na, np.int64)
    out_n = np.zeros((na, 4), np.int64)
    out_w = np.zeros((na, 4))
    out_d = np.zeros(na)
    n_fb = 0
    tie = TIE_REL * float(h)
    big = np.iinfo(np.int64).max
    for s0 in range(0, na, CHUNK):
        P = XA[s0:s0 + CHUNK]
        n = P.shape[0]
        _, cand = tree.query(P, k=k)
        cand = np.asarray(cand).reshape(n, k)
        e = elems[cand]                                     # (n,k) 전역 요소 번호
        Cn = C4[e]                                          # (n,k,4)
        Pk = np.broadcast_to(P[:, None, :], (n, k, 3))
        q1, l1 = _closest_tri(Pk, X[Cn[..., 0]], X[Cn[..., 1]], X[Cn[..., 2]])
        d1 = np.linalg.norm(Pk - q1, axis=-1)
        q2, l2 = _closest_tri(Pk, X[Cn[..., 0]], X[Cn[..., 2]], X[Cn[..., 3]])
        d2 = np.linalg.norm(Pk - q2, axis=-1)
        qk = isq[e]
        second = qk & (d2 < d1)
        d = np.where(second, d2, d1)
        dmin = d.min(axis=1)
        okk = d <= dmin[:, None] + tie
        j = np.argmin(np.where(okk, e, big), axis=1)        # 동률 = 작은 요소 번호(결정적)
        rows = np.arange(n)
        ej = e[rows, j]
        nodes = Cn[rows, j]
        quad = isq[ej]
        sec = second[rows, j]
        lam1, lam2 = l1[rows, j], l2[rows, j]
        w = np.zeros((n, 4))
        tri = ~quad                                         # TRIA: 무게중심 (0,1,2)
        w[tri, :3] = lam1[tri]
        lin = np.zeros((n, 4))                              # QUAD 선형 대체(그 삼각형)
        lin[:, 0] = np.where(sec, lam2[:, 0], lam1[:, 0])
        lin[:, 1] = np.where(sec, 0.0, lam1[:, 1])
        lin[:, 2] = np.where(sec, lam2[:, 1], lam1[:, 2])
        lin[:, 3] = np.where(sec, lam2[:, 2], 0.0)
        if quad.any():
            qi = np.flatnonzero(quad)
            corner = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
            rs0 = lin[qi] @ corner                          # 초기값 = 삼각형 무게중심의 자연좌표
            Xq = X[nodes[qi]]
            Pq = np.where(sec[qi, None], q2[rows, j][qi], q1[rows, j][qi])
            r, s, conv = _quad_newton(Pq, Xq, rs0[:, 0], rs0[:, 1], int(wcfg["newton_iter"]))
            r, s = np.clip(r, -1.0, 1.0), np.clip(s, -1.0, 1.0)
            Nq = _bilinear_N(r, s)
            wq = np.where(conv[:, None], Nq, lin[qi])
            w[qi] = wq
            n_fb += int((~conv).sum())
        out_e[s0:s0 + n] = ej
        out_n[s0:s0 + n] = nodes
        out_w[s0:s0 + n] = w
        out_d[s0:s0 + n] = dmin
    return {"elem": out_e, "nodes": out_n, "w": out_w, "dist": out_d, "newton_fallback_n": int(n_fb),
            "max_dist_mm": float(out_d.max()) if na else 0.0, "seconds": round(time.monotonic() - t0, 3)}


def apply_work(W: dict, f_A, n_t: int, rows=None) -> np.ndarray:
    """f_t = Tᵀ f_A (rows = 쓰는 A 노드 인덱스, None = 전부)."""
    f = np.asarray(f_A, dtype=np.float64)
    nodes, w = W["nodes"], W["w"]
    if rows is not None:
        nodes, w, f = nodes[rows], w[rows], f[rows]
    out = np.zeros((int(n_t), 3))
    idx = nodes.ravel()
    for k in range(3):
        out[:, k] = np.bincount(idx, weights=(w * f[:, k:k + 1]).ravel(), minlength=int(n_t))
    return out


def far_mask(W: dict, wcfg: dict, h: float) -> np.ndarray:
    tol = float(wcfg["proj_tol_mm"]) if wcfg.get("proj_tol_mm") is not None else 1.0 * float(h)
    return np.asarray(W["dist"]) > tol


# ====================================================================== 보존 보정 (LT-4)
def _sabs(f) -> float:
    return float(np.linalg.norm(np.asarray(f, dtype=np.float64), axis=1).sum())


def balance(X_A, f_A) -> dict:
    """A 기준 합력·합모멘트(A 노드 중심) + 크기 척도."""
    XA = np.asarray(X_A, dtype=np.float64)
    c = XA.mean(axis=0)
    F, M = mp.resultants(XA, f_A, c)
    Lb = float(np.linalg.norm(XA.max(axis=0) - XA.min(axis=0))) if XA.size else 0.0
    return {"c": c, "F": F, "M": M, "sabs": _sabs(f_A), "Lb": Lb or 1.0}


def _errs(X_t, f_t, b: dict) -> tuple[float, float]:
    F, M = mp.resultants(np.asarray(X_t, dtype=np.float64), f_t, b["c"])
    s = b["sabs"]
    if s <= 0:
        return 0.0, 0.0
    return float(np.linalg.norm(F - b["F"]) / s), float(np.linalg.norm(M - b["M"]) / (s * b["Lb"]))


def conserve(X_t, f_t, rn_idx, b: dict) -> tuple[np.ndarray, dict]:
    """LT-4: 영역 노드 최소노름 보정으로 합력·합모멘트를 원본 값으로. 반환 (f, {dF_rel_before, dM_rel_before, dF_rel,
    dM_rel, corr_rel})."""
    X = np.asarray(X_t, dtype=np.float64)
    f = np.array(f_t, dtype=np.float64, copy=True)
    dF0, dM0 = _errs(X, f, b)
    corr = 0.0
    if b["sabs"] > 0:
        Ft, Mt = mp.resultants(X, f, b["c"])
        d, _ = mp.min_norm_forces(X[rn_idx], b["F"] - Ft, b["M"] - Mt, b["c"])
        f[rn_idx] += d
        st = _sabs(f)
        corr = float(np.linalg.norm(d, axis=1).sum() / st) if st > 0 else 0.0
    dF1, dM1 = _errs(X, f, b)
    return f, {"dF_rel_before": dF0, "dM_rel_before": dM0, "dF_rel": dF1, "dM_rel": dM1, "corr_rel": corr}


# ====================================================================== 셀 (LT-6)
def _cell_members(cid: np.ndarray, n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(cid, kind="stable")
    bounds = np.searchsorted(cid[order], np.arange(n_cells + 1))
    return order, bounds


def _batch_min_norm(X, idx, cid_of, cells, F, M, ref, min_spread):
    """셀 일괄 최소노름(6×6 정규방정식 닫힌 꼴): f_i = F/m + λ × r̂_i, λ = (Σ(|r̂|²I − r̂r̂ᵀ))⁻¹ M_c/L.
    idx = 대상 노드, cid_of = 그 노드 셀 번호(cells 안 순번), 반환 (f (len(idx),3), ok (len(cells),))."""
    nc = len(cells)
    m = np.bincount(cid_of, minlength=nc).astype(np.float64)
    Xn = X[idx]
    xc = np.stack([np.bincount(cid_of, weights=Xn[:, k], minlength=nc) for k in range(3)], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = xc / m[:, None]
    r = Xn - xc[cid_of]
    L = np.zeros(nc)
    np.maximum.at(L, cid_of, np.linalg.norm(r, axis=1))
    P = np.zeros((nc, 3, 3))                                 # 중심화 공분산(랭크 판정 — _rank_ok 와 같은 뜻)
    for a in range(3):
        for c in range(3):
            P[:, a, c] = np.bincount(cid_of, weights=r[:, a] * r[:, c], minlength=nc)
    ev = np.sqrt(np.clip(np.linalg.eigvalsh(P)[:, ::-1], 0.0, None))
    ok = (m >= 3) & (ev[:, 0] > 0) & (ev[:, 1] > float(min_spread) * ev[:, 0]) & (L > 0)
    Ls = np.where(L > 0, L, 1.0)
    rs = r / Ls[cid_of][:, None]
    G = np.zeros((nc, 3, 3))
    q = np.einsum("ni,ni->n", rs, rs)
    for a in range(3):
        for c in range(3):
            G[:, a, c] = np.bincount(cid_of, weights=(q if a == c else 0.0) - rs[:, a] * rs[:, c], minlength=nc)
    Mc = M + np.cross(ref - xc, F)
    G[~ok] = np.eye(3)
    lam = np.linalg.solve(G, (Mc / Ls[:, None])[..., None])[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (F / np.where(m > 0, m, 1.0)[:, None])[cid_of] + np.cross(lam[cid_of], rs)
    f[~ok[cid_of]] = 0.0
    return f, ok


def cell_loads(raw: dict, efr: dict, t_mesh: dict, t_frame: dict, rn_idx: np.ndarray, s: float, W_get,
               min_spread: float = mp.MIN_SPREAD) -> tuple[np.ndarray, dict]:
    """LT-6 새 C(셀 크기 s): ESL raw → ESL frame 새 요약 → 기준 frame 같은 (i,j) 셀 영역 노드 최소노름 분배, 작은 셀은 그
    셀 A 노드 힘을 W 로. W_get() = W 연산자(필요할 때만 만듦). LT-4 보정 전 힘과 정보."""
    XA = np.asarray(raw["x0"], dtype=np.float64)
    fA = np.asarray(raw["f"], dtype=np.float64)
    X = np.asarray(t_mesh["x0"], dtype=np.float64)
    nx = max(1, round(float(efr["L_xi"]) / float(s)))
    ny = max(1, round(float(efr["L_eta"]) / float(s)))
    gs = nz.grid_summary(XA, fA, nx, ny, fr=efr, top_n=0)
    R = nz.rotation(t_frame)
    Fg = gs["cell_F_loc"].reshape(-1, 3) @ R
    Mg = gs["cell_M_loc"].reshape(-1, 3) @ R
    Cc = nz.cell_centers(t_frame, nx, ny).reshape(-1, 3)
    nc = nx * ny
    loaded = (np.linalg.norm(Fg, axis=1) > 0) | (np.linalg.norm(Mg, axis=1) > 0)
    ti, tj, _ = nz.cell_index(t_frame, X[rn_idx], nx, ny)
    tcid = ti * ny + tj
    order, bounds = _cell_members(tcid, nc)
    f = np.zeros_like(X)
    cells = np.flatnonzero(loaded)
    small = np.zeros(nc, bool)
    if nc >= BATCH_MIN_CELLS:
        sel = loaded[tcid]
        idx = rn_idx[sel]
        pos = np.full(nc, -1, np.int64)
        pos[cells] = np.arange(cells.size)
        cid_of = pos[tcid[sel]]
        fb, ok = _batch_min_norm(X, idx, cid_of, cells, Fg[cells], Mg[cells], Cc[cells], min_spread)
        for k in range(3):
            f[:, k] += np.bincount(idx, weights=fb[:, k], minlength=X.shape[0])
        small[cells[~ok]] = True
    else:
        for c in cells.tolist():
            nodes = rn_idx[order[bounds[c]:bounds[c + 1]]]
            if nodes.size >= 3 and mp._rank_ok(X[nodes], min_spread):
                try:
                    fg, _ = mp.min_norm_forces(X[nodes], Fg[c], Mg[c], Cc[c])
                except EslError:
                    small[c] = True
                    continue
                f[nodes] += fg
            else:
                small[c] = True
    ai, aj, _ = nz.cell_index(efr, XA, nx, ny)
    a_small = small[ai * ny + aj]
    if a_small.any():
        f += apply_work(W_get(), fA, X.shape[0], rows=np.flatnonzero(a_small))
    sa = _sabs(fA)
    info = {"nx": nx, "ny": ny, "n_cells_loaded": int(loaded.sum()), "n_cells_small": int((small & loaded).sum()),
            "small_frac": float(np.linalg.norm(fA[a_small], axis=1).sum() / sa) if sa > 0 else 0.0,
            "batched": bool(nc >= BATCH_MIN_CELLS)}
    return f, info


# ====================================================================== 대상 하중 (LT-1)
class Ctx:
    """shape_loads 문맥: 영역·h·좌표 허용·매핑 옵션 + W 캐시(A 메시 sha 별)."""

    def __init__(self, region=None, h: float = 3.0, coord_tol: float = 0.005, mapping_opts: dict | None = None,
                 W: dict | None = None):
        self.region = None if region is None else np.asarray(region, bool)
        self.h = float(h)
        self.coord_tol = float(coord_tol)
        self.mapping_opts = mapping_opts
        self.W = dict(W or {})
        self.ident: dict = {}


def _work_of(ctx: Ctx, sha: str, raw: dict, t_mesh: dict, wcfg: dict) -> dict:
    if sha not in ctx.W:
        ctx.W[sha] = build_work(raw["x0"], t_mesh, ctx.region, wcfg, ctx.h)
    return ctx.W[sha]


def _ident(ctx: Ctx, sha: str, raw: dict, t_mesh: dict) -> bool:
    if sha not in ctx.ident:
        ctx.ident[sha] = ctx.region is None and identity_ok(raw, t_mesh, ctx.coord_tol)
    return ctx.ident[sha]


def _metrics(f, extra: dict) -> dict:
    a = np.linalg.norm(np.asarray(f, dtype=np.float64), axis=1)
    return {"sum_abs_f": float(a.sum()), "max_abs_f": float(a.max()) if a.size else 0.0, **extra}


def shape_loads(target, entries, lt: dict, ctx: Ctx, variant: tuple | None = None) -> tuple[list, dict]:
    """LT-1 모든 형상(d000 포함) 같은 함수. entries = raw 포함 LibraryEntry, variant = (method, cell_size_mm) — None =
    스터디 주 방식. 반환 ([(entry_id, F (N,3))], {variant, fast_path, per_esl[…], transfer{…}, warnings[]})."""
    from esl.opt import target as tg
    method, s = variant if variant is not None else primary_variant(lt)
    wcfg = lt["work"]
    mesh = target.mesh
    X = np.asarray(mesh["x0"], dtype=np.float64)
    n_t = X.shape[0]
    rn_idx = np.flatnonzero(region_nodes(mesh, ctx.region))
    out, per, warns = [], [], []
    tr = {"max_dist_mm": 0.0, "far_n": 0, "newton_fallback_n": 0, "seconds": 0.0}
    seen_sha: set = set()
    fast_all = True
    for e in entries:
        eid = e.meta.get("entry_id")
        raw = e.raw
        sha = a_mesh_sha(raw)
        b = balance(raw["x0"], raw["f"])
        if b["sabs"] > 0 and float(np.linalg.norm(b["F"])) / b["sabs"] > UNBALANCED_REL:
            warns.append({"code": "LT_ESL_UNBALANCED", "entry_id": eid,
                          "rel": float(np.linalg.norm(b["F"])) / b["sabs"]})
        row: dict = {"entry_id": eid}
        if method == "work" and _ident(ctx, sha, raw, mesh):
            f, _ = tg.entry_load(tg.Target("S1", mesh, target.frame, []), raw)     # ① direct_nodal 과 같은 코드
            dF, dM = _errs(X, f, b)
            row.update(_metrics(f, {"dF_rel": dF, "dM_rel_before": dM, "dM_rel": dM, "corr_rel": 0.0,
                                    "far_frac": 0.0, "fast_path": "identity"}))
            out.append((eid, np.asarray(f, dtype=np.float64)))
            per.append(row)
            continue
        fast_all = False
        if method == "cell" and s is None:                   # legacy 격자(지금 to_target 그대로, 영역 노드만)
            st = tg.Target("S2", {"x0": X[rn_idx], "node_id": np.asarray(mesh["node_id"])[rn_idx]}, target.frame, [])
            fr, _info = tg.entry_load(st, None, e.summary_for_mapping(), ctx.mapping_opts)
            f = np.zeros((n_t, 3))
            f[rn_idx] = fr
            dF, dM = _errs(X, f, b)
            row.update(_metrics(f, {"dF_rel": dF, "dM_rel_before": dM, "dM_rel": dM,
                                    "corr_rel": float(_info.get("equilibrate_correction_rel") or 0.0),
                                    "far_frac": None}))
            out.append((eid, f))
            per.append(row)
            continue
        W = None
        if method == "work":
            W = _work_of(ctx, sha, raw, mesh, wcfg)
            f0 = apply_work(W, raw["f"], n_t)
            extra = {}
        else:
            f0, extra = cell_loads(raw, e.meta["frame"], mesh, target.frame, rn_idx, float(s),
                                   lambda sha=sha, raw=raw: _work_of(ctx, sha, raw, mesh, wcfg))
            W = ctx.W.get(sha)
        f, cons = conserve(X, f0, rn_idx, b)
        far_frac = None
        if W is not None:
            fm = far_mask(W, wcfg, ctx.h)
            far_frac = float(np.linalg.norm(np.asarray(raw["f"])[fm], axis=1).sum() / b["sabs"]) if b["sabs"] > 0 else 0.0
            if sha not in seen_sha:
                seen_sha.add(sha)
                tr["max_dist_mm"] = max(tr["max_dist_mm"], float(W["max_dist_mm"]))
                tr["far_n"] += int(fm.sum())
                tr["newton_fallback_n"] += int(W["newton_fallback_n"])
                tr["seconds"] += float(W["seconds"])
        row.update(_metrics(f, {**cons, "far_frac": far_frac,
                                **({"small_frac": extra["small_frac"], "n_cells_loaded": extra["n_cells_loaded"],
                                    "n_cells_small": extra["n_cells_small"]} if extra else {})}))
        out.append((eid, f))
        per.append(row)
    return out, {"variant": variant_label(method, s), "method": method, "cell_size_mm": s,
                 "fast_path": "identity" if (fast_all and method == "work" and entries) else None,
                 "per_esl": per, "transfer": tr, "warnings": warns}


def far_state(info: dict, wcfg: dict) -> tuple[str | None, float]:
    """먼 노드 판정(LT-5): (None | LT_FAR_NODES | LT_TRANSFER_FAILED, ESL 최대 far_frac)."""
    ff = max([float(p.get("far_frac") or 0.0) for p in info["per_esl"]] or [0.0])
    if ff > float(wcfg["far_fail_frac"]):
        return "LT_TRANSFER_FAILED", ff
    if ff > float(wcfg["far_warn_frac"]):
        return "LT_FAR_NODES", ff
    return None, ff


# ====================================================================== 지지 (LT-7)
def auto_supports(mesh: dict, region) -> list:
    """영역 노드로 PCA 3-2-1(영역 = 전체면 ``target.auto_supports`` 와 같음)."""
    from esl.opt import target as tg
    if region is None:
        return tg.auto_supports(mesh)
    rn = region_nodes(mesh, region)
    return tg.auto_supports({"x0": np.asarray(mesh["x0"])[rn], "node_id": np.asarray(mesh["node_id"])[rn]})


def support_xyz(mesh: dict, supports) -> list[dict]:
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    X = np.asarray(mesh["x0"], dtype=np.float64)
    return [{"node_id": int(n), "dof": str(d), "xyz": X[pos[int(n)]].tolist()} for n, d in supports]


def _support_ok(mesh: dict, sup) -> bool:
    from esl.mech import supports as msup
    from esl.opt import target as tg
    try:
        sr = tg.support_check(mesh, sup)
    except EslError:
        return False
    return sr["rank"] >= 6 and sr["sigma_ratio"] >= msup.DEGENERATE_RATIO


def transfer_supports(ref: list[dict], mesh: dict, region, tol: float) -> tuple[list, dict]:
    """LT-7 기준 d000 지지점(xyz) → 형상 영역 최근접 노드(동률 = 작은 인덱스), 같은 dof. 거리 > tol 또는 rank < 6 →
    영역 auto 3-2-1(fallback). 반환 (지지 [(node_id, dof)], {mode, max_dist_mm, reason?})."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    rn = np.flatnonzero(region_nodes(mesh, region))
    sup, dmax = [], 0.0
    for s in ref:
        d = np.linalg.norm(X[rn] - np.asarray(s["xyz"], dtype=np.float64), axis=1)
        j = int(np.argmin(d))
        dmax = max(dmax, float(d[j]))
        sup.append((int(nid[rn[j]]), str(s["dof"])))
    if dmax > float(tol):
        reason = f"distance {dmax:.3g} mm > {float(tol):g} mm"
    elif not _support_ok(mesh, sup):
        reason = "rank < 6"
    else:
        return sup, {"mode": "transfer", "max_dist_mm": dmax}
    return auto_supports(mesh, region), {"mode": "fallback", "max_dist_mm": dmax, "reason": reason}


# ====================================================================== 진단 (LT-10)
def load_corr(f_m, f_ref) -> float | None:
    a = np.asarray(f_m, dtype=np.float64).ravel()
    b = np.asarray(f_ref, dtype=np.float64).ravel()
    den = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / den) if den > 0 else None


def mac(u_m, u_ref) -> float | None:
    a = np.asarray(u_m, dtype=np.float64).ravel()
    b = np.asarray(u_ref, dtype=np.float64).ravel()
    den = float((a @ a) * (b @ b))
    return float((a @ b) ** 2 / den) if den > 0 else None


def _ratio(a, b):
    return None if a is None or b is None or float(b) == 0.0 else float(a) / float(b)


def diag_rows(variants: list[dict], truth: dict, labels: dict) -> list[dict]:
    """d000 참값 대비 행. variants = [{variant, entry_id, f, C, umax, u?}], truth = {entry_id: {f?, C, umax, u?, kind}}."""
    rows = []
    for v in variants:
        t = truth.get(v["entry_id"])
        if t is None:
            continue
        ident = t.get("f") is not None
        fa = np.linalg.norm(np.asarray(v["f"]), axis=1)
        if ident:
            ta = np.linalg.norm(np.asarray(t["f"]), axis=1)
            s_ref, m_ref = float(ta.sum()), float(ta.max()) if ta.size else 0.0
        else:
            s_ref, m_ref = t.get("sum_abs_f"), t.get("max_abs_f")
        rows.append({"entry_id": v["entry_id"], "label": labels.get(v["entry_id"], str(v["entry_id"])[:8]),
                     "variant": v["variant"], "truth": t.get("kind"),
                     "load_corr": load_corr(v["f"], t["f"]) if ident else None,
                     "sum_abs_ratio": _ratio(float(fa.sum()), s_ref),
                     "max_abs_ratio": _ratio(float(fa.max()) if fa.size else 0.0, m_ref),
                     "umax_ratio": _ratio(v["umax"], t["umax"]), "C_ratio": _ratio(v["C"], t["C"]),
                     "mac": mac(v["u"], t["u"]) if ident and v.get("u") is not None and t.get("u") is not None else None})
    return rows


def summary(rows: list[dict], order: list[str]) -> list[dict]:
    """result.json.load_transfer.summary: variant 별 umax_ratio·C_ratio [min,max], mac_min, load_corr_min."""
    out = []
    for vname in order:
        rs = [r for r in rows if r["variant"] == vname]
        if not rs:
            continue

        def rng(k, rs=rs):
            v = [float(r[k]) for r in rs if r.get(k) is not None]
            return [min(v), max(v)] if v else None

        def mn(k, rs=rs):
            v = [float(r[k]) for r in rs if r.get(k) is not None]
            return min(v) if v else None
        out.append({"variant": vname, "umax_ratio": rng("umax_ratio"), "C_ratio": rng("C_ratio"), "mac_min": mn("mac"),
                    "load_corr_min": mn("load_corr")})
    return out


def sweep_variants(lt: dict) -> list[tuple[str, float | None]]:
    """d000 진단 variant 목록(중복 제거, 순서 = 주 → alt → cell_sweep_mm)."""
    dg = lt.get("diag") or {}
    out = [primary_variant(lt)]
    if not dg.get("enabled"):
        return out
    a = alt_variant(lt)
    if a is not None:
        out.append(a)
    for s in dg.get("cell_sweep_mm") or []:
        out.append(("cell", None if s is None else float(s)))
    seen, uniq = set(), []
    for m, s in out:
        k = variant_label(m, s)
        if k not in seen:
            seen.add(k)
            uniq.append((m, s))
    return uniq


def a_direct_mesh(raw: dict, props: dict) -> dict:
    """참값 a_direct 용 A 메시(스터디 물성으로 덮어씀)."""
    ne = int(np.asarray(raw["elem_type"]).size)
    m = {k: np.asarray(raw[k]) for k in ("node_id", "x0", "elem_id", "elem_type", "conn")}
    m["elem_pid"] = np.asarray(raw.get("elem_pid", np.zeros(ne, np.int64)))
    m["thickness"] = np.full(ne, float(props["t"]))
    m["E"] = np.full(ne, float(props["E"]))
    m["nu"] = np.full(ne, float(props["nu"]))
    return m


# ====================================================================== W 저장
def save_work(path: str, Ws: dict, key: str, writer=None) -> str:
    """prep/shapes/<did>/transfer.npz: 키 = A 메시 sha 앞 16자(+ _elem·_nodes·_w·_dist), key = 대상 메시·영역·설정 해시."""
    from esl.doe.mesh_gmsh import save_npz_det
    arr = {"key": np.asarray(key)}
    for sha, W in Ws.items():
        arr.update({f"{sha}_elem": W["elem"], f"{sha}_nodes": W["nodes"], f"{sha}_w": W["w"], f"{sha}_dist": W["dist"],
                    f"{sha}_meta": np.asarray([W["newton_fallback_n"], W["max_dist_mm"], W["seconds"]], np.float64)})
    g = writer.guard if writer is not None else (lambda p: p)
    save_npz_det(g(path), arr)
    return path


def load_work(path: str, key: str) -> dict:
    """save_work 역(키 다르면 빈 dict — 다시 만듦)."""
    import os
    if not os.path.isfile(path):
        return {}
    with np.load(path, allow_pickle=False) as z:
        if "key" not in z.files or str(z["key"]) != key:
            return {}
        out = {}
        for k in z.files:
            if k.endswith("_elem"):
                sha = k[:-5]
                meta = z[f"{sha}_meta"]
                out[sha] = {"elem": z[k], "nodes": z[f"{sha}_nodes"], "w": z[f"{sha}_w"], "dist": z[f"{sha}_dist"],
                            "newton_fallback_n": int(meta[0]), "max_dist_mm": float(meta[1]), "seconds": float(meta[2])}
        return out


def work_key(t_mesh: dict, region, lt: dict, h: float) -> str:
    h_ = hashlib.sha256(b"esl/lt_work/1\n")
    h_.update(mesh_sha(t_mesh).encode())
    h_.update(b"-" if region is None else np.packbits(np.asarray(region, bool)).tobytes())
    h_.update(repr((sorted((lt.get("work") or {}).items()), float(h))).encode())
    return h_.hexdigest()
