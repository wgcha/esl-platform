"""하중 전달 공용 모듈 — 모드 무관 순수 모듈(계약 esl_load_transfer.md §13.2 D-0.20.0-LT-15, ①②③④ 공통).

입력 = 원본 ``SrcLoad``(ESL 원본 메시·노드힘·frame·24×14 요약) + 대상 ``DstMesh``(메시·frame·활성 요소 마스크·h) + ``Method``
+ ``Placement``(global | rigid(R, t) | frame — 모듈 밖이 정함) + ``Identity``(topo | topo+coords | none) → 대상 노드힘 + 진단 행.
esl.doe 를 import 하지 않고 파일 IO·설정 해석이 없다(계획 표 = ``transfer_plan``, ④ 지지·영역 = ``compare_lt``).

- 전략 등록 ``STRATEGIES``/``register``: ``identity``(``target.entry_load`` S1 재배열 — ① direct_nodal 과 비트 동일),
  ``work``(LT-2 일 등가 f_t = Tᵀ f_A: A 노드마다 대상 요소 최근접점(TRIA = Ericson 점-삼각형, QUAD = 두 삼각형 최근접점 →
  쌍선형 (r,s) Gauss-Newton 역사상) 형상함수 — 분할 1 → 합력 보존), ``cell``(LT-6: cell_size_mm null = ``target.entry_load`` S2
  (24×14 요약·``mapping.to_target``) 그대로, 값 s = ESL raw 새 요약·셀 최소노름 6 제약, 노드 0~2 개·공선 셀은 그 셀 A 노드 힘을 W 로).
- 실행기 ``transfer``·``run_transfer_plan``: method = work ∧ identity 키로 같은 메시(∧ 활성 = 전체) → identity 전략(LT-22 — cell 은
  같은 메시여도 셀), 아니면 방식 전략 → 공통 후처리(LT-4 합력·합모멘트 보존 보정 — 배치된 원본 값으로, cell:legacy 는 기존 합 0
  보정 그대로), 먼 노드·지표 행. 진단 함수(``load_corr``·``mac``·``diag_rows``·``summary``)도 모드 무관.
- 대규모: 사영은 A 노드 청크(``CHUNK``) × 요소 중심 cKDTree k 후보 — 피크 메모리 O(N_A + N_e + 청크·k).
"""
from __future__ import annotations

import hashlib
import time

import numpy as np

from esl.errors import EslError
from esl.library import mapping as mp
from esl.library import normalize as nz

DIAG_SCHEMA = "esl/doe_load_transfer_diag/1"
METHODS = ("work", "cell")
IDENTITY_KEYS = ("topo", "topo+coords", "none")
PLACEMENTS = ("global", "rigid", "frame")
CHUNK = 20000                 # 사영 A 노드 청크
BATCH_MIN_CELLS = 10000       # LT-6: 셀 1만 개 이상 = 6×6 정규방정식 일괄 풀이
TIE_REL = 1e-12               # LT-2 거리 동률(× h) → 작은 요소 번호
NEWTON_TOL = 1e-10            # LT-2 잔차 ≤ 1e-10·h (자연좌표 증분)
UNBALANCED_REL = 1e-6         # LT-4 LT_ESL_UNBALANCED
MESH_KEYS = ("node_id", "x0", "conn", "elem_type")


# ====================================================================== 자료형
def _sha(parts) -> str:
    h = hashlib.sha256(b"esl/lt/1\n")
    for a in parts:
        if isinstance(a, (str, bytes)):
            h.update(a.encode() if isinstance(a, str) else a)
        else:
            a = np.ascontiguousarray(np.asarray(a))
            h.update(f"{a.dtype.str}{a.shape}".encode())
            h.update(a.tobytes())
    return h.hexdigest()[:16]


def mesh_sha(mesh: dict) -> str:
    """메시 sha(앞 16자) — node_id·x0·conn·elem_type."""
    return _sha([np.asarray(mesh["node_id"]).astype("<i8"), np.asarray(mesh["x0"]).astype("<f8"),
                 np.asarray(mesh["conn"]).astype("<i8"), np.asarray(mesh["elem_type"]).astype("<i8")])


def src_load(key, mesh: dict, f, frame: dict | None = None, summary: dict | None = None) -> dict:
    """SrcLoad {key, mesh{node_id, x0, conn, elem_type}, f (N_A,3), frame(ESL meta.frame), summary(24×14), mesh_sha}."""
    m = {k: np.asarray(mesh[k]) for k in MESH_KEYS}
    m["x0"] = np.asarray(m["x0"], dtype=np.float64)
    return {"key": key, "mesh": m, "f": np.asarray(f, dtype=np.float64), "frame": frame, "summary": summary,
            "mesh_sha": mesh_sha(m)}


def dst_mesh(mesh: dict, frame: dict, elem_mask=None, h: float = 3.0) -> dict:
    """DstMesh {mesh, frame, elem_mask(요소 bool | None = 전체), h} (+ 내부 nodes = 활성 노드 인덱스, sha)."""
    m = {k: np.asarray(mesh[k]) for k in MESH_KEYS}
    m["x0"] = np.asarray(m["x0"], dtype=np.float64)
    em = None if elem_mask is None else np.asarray(elem_mask, bool)
    return {"mesh": m, "frame": frame, "elem_mask": em, "h": float(h), "nodes": np.flatnonzero(active_nodes(m, em)),
            "sha": _sha([mesh_sha(m), b"-" if em is None else np.packbits(em).tobytes(), repr(float(h))])}


def active_nodes(mesh: dict, elem_mask) -> np.ndarray:
    """활성 요소가 쓰는 노드(bool) — None = 전부."""
    n = np.asarray(mesh["x0"]).shape[0]
    if elem_mask is None:
        return np.ones(n, bool)
    C4, _ = _corners(mesh)
    out = np.zeros(n, bool)
    out[C4[np.asarray(elem_mask, bool)].ravel()] = True
    return out


def _corners(mesh: dict) -> tuple[np.ndarray, np.ndarray]:
    """(E,4) 노드 인덱스(TRIA 4번째 = 1번째 — 가중 0) · quad 마스크."""
    C = np.asarray(mesh["conn"], dtype=np.int64)
    q = np.asarray(mesh["elem_type"]).astype(int) == 4
    C4 = C[:, :4].copy()
    C4[~q, 3] = C4[~q, 0]
    return C4, q


def _centroids(mesh: dict) -> np.ndarray:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C4, q = _corners(mesh)
    k = np.where(q, 4.0, 3.0)
    s = X[C4].sum(axis=1) - np.where(q[:, None], 0.0, X[C4[:, 3]])
    return s / k[:, None]


def same_mesh(src_mesh: dict, dst_mesh_: dict, key: str, tol: float = 0.005) -> bool:
    """identity 판정: topo = 노드 ID 집합 같음, topo+coords = + 같은 ID 좌표 차 최대 ≤ tol × 원본 bbox 대각, none = 거짓."""
    if key not in IDENTITY_KEYS:
        raise EslError("CONFIG_INVALID", f"identity key topo|topo+coords|none: {key!r}")
    if key == "none":
        return False
    na = np.asarray(src_mesh["node_id"], dtype=np.int64)
    nt = np.asarray(dst_mesh_["node_id"], dtype=np.int64)
    if na.size != nt.size:
        return False
    oa, ot = np.argsort(na, kind="stable"), np.argsort(nt, kind="stable")
    if not np.array_equal(na[oa], nt[ot]):
        return False
    if key == "topo":
        return True
    xa = np.asarray(src_mesh["x0"], dtype=np.float64)[oa]
    xt = np.asarray(dst_mesh_["x0"], dtype=np.float64)[ot]
    diag = float(np.linalg.norm(xa.max(axis=0) - xa.min(axis=0))) if xa.size else 0.0
    dmax = float(np.max(np.linalg.norm(xa - xt, axis=1))) if xa.size else 0.0
    return dmax <= float(tol) * (diag or 1.0)


def identity_ok(raw: dict, t_mesh: dict, tol_rel: float) -> bool:
    """LT-2 동일 메시(topo+coords) — 원본 raw·대상 메시 dict."""
    return same_mesh(raw, t_mesh, "topo+coords", tol_rel)


# ====================================================================== 배치 (LT-23)
def place(x, f, placement: dict | None) -> tuple[np.ndarray, np.ndarray]:
    """원본 좌표·힘을 대상 좌표로: global = 그대로, rigid = (R x + t, R f), frame = 정규화 (ξ, η, ζ) 사상
    x' = to_global(F_dst, local_coords(F_src, x)), f' = R_dstᵀ R_src f(셀 매핑 cell_F_loc @ R 과 같은 가정)."""
    x = np.asarray(x, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    kind = (placement or {}).get("kind", "global")
    if kind == "global":
        return x, f
    if kind == "rigid":
        R = np.asarray(placement["R"], dtype=np.float64)
        t = np.asarray(placement["t"], dtype=np.float64)
        return x @ R.T + t, f @ R.T
    if kind == "frame":
        fs, fd = placement.get("src_frame"), placement.get("dst_frame")
        if not fs or not fd:
            raise EslError("INPUT_INVALID", "placement frame 에는 src_frame·dst_frame 필요")
        loc = nz.local_coords(fs, x)
        xp = nz.to_global(fd, loc[:, 0], loc[:, 1], loc[:, 2])
        return np.asarray(xp, dtype=np.float64), f @ nz.rotation(fs).T @ nz.rotation(fd)
    raise EslError("CONFIG_INVALID", f"placement global|rigid|frame: {kind!r}")


def placement_sha(placement: dict | None) -> str:
    p = placement or {"kind": "global"}
    parts = [p.get("kind", "global")]
    for k in ("R", "t"):
        if p.get(k) is not None:
            parts.append(np.asarray(p[k], dtype=np.float64))
    for k in ("src_frame", "dst_frame"):
        if p.get(k):
            parts.append(repr(sorted((kk, repr(v)) for kk, v in p[k].items())))
    return _sha(parts)

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
    t0 = time.monotonic()
    XA = np.asarray(a_x, dtype=np.float64)
    X = np.asarray(t_mesh["x0"], dtype=np.float64)
    C4, isq = _corners(t_mesh)
    elems = np.arange(C4.shape[0]) if region is None else np.flatnonzero(np.asarray(region, bool))
    if elems.size == 0:
        raise EslError("MAPPING_DEGENERATE", "하중 전달 대상 영역 요소가 없음")
    cen = _centroids(t_mesh)[elems]
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

def unplace_points(x, placement: dict | None) -> np.ndarray:
    """``place`` 의 점 역변환(대상 좌표 → 원본 좌표): rigid = Rᵀ(x − t), frame = to_global(F_src, local_coords(F_dst, x))."""
    x = np.asarray(x, dtype=np.float64)
    kind = (placement or {}).get("kind", "global")
    if kind == "global":
        return x
    if kind == "rigid":
        R = np.asarray(placement["R"], dtype=np.float64)
        return (x - np.asarray(placement["t"], dtype=np.float64)) @ R
    if kind == "frame":
        fs, fd = placement.get("src_frame"), placement.get("dst_frame")
        loc = nz.local_coords(fd, x)
        return np.asarray(nz.to_global(fs, loc[:, 0], loc[:, 1], loc[:, 2]), dtype=np.float64)
    raise EslError("CONFIG_INVALID", f"placement global|rigid|frame: {kind!r}")


def placement_rotation(placement: dict | None) -> np.ndarray | None:
    """배치 회전(벡터용): global = None, rigid = R, frame = R_dstᵀ R_src (place 의 f 회전과 같음)."""
    kind = (placement or {}).get("kind", "global")
    if kind == "global":
        return None
    if kind == "rigid":
        return np.asarray(placement["R"], dtype=np.float64)
    return nz.rotation(placement["dst_frame"]).T @ nz.rotation(placement["src_frame"])


def build_disp(a_mesh: dict, t_mesh: dict, placement: dict | None, wcfg: dict, h: float,
               identity: dict | None = None) -> tuple:
    """변위 보간 S_t(N_t × N_A, 성분 공통 — 계약 esl_stiffness_metric.md §2(2)): 하중 W(LT-2)와 역할을 바꾼 같은 사영 코드 —
    대상 노드를 배치 역변환으로 A 좌표에 놓고 A 요소 최근접점의 형상함수 행. 같은 메시(identity 키) = 순열 index 배열
    (u_t = u_A[perm] — 비트 동일). 반환 (S: scipy.sparse csr | index 배열, info{kind, max_dist_mm, far_n, far_frac, R})."""
    idn = identity or {"key": "none"}
    R = placement_rotation(placement)
    if same_mesh(a_mesh, t_mesh, idn.get("key", "none"), float(idn.get("coord_tol_rel") or 0.005)):
        na = np.asarray(a_mesh["node_id"], dtype=np.int64)
        order = np.argsort(na, kind="stable")
        perm = order[np.searchsorted(na[order], np.asarray(t_mesh["node_id"], dtype=np.int64))]
        return perm, {"kind": "perm", "max_dist_mm": 0.0, "far_n": 0, "far_frac": 0.0, "R": None}
    from scipy import sparse
    xt = unplace_points(t_mesh["x0"], placement)
    W = build_work(xt, a_mesh, None, wcfg, h)
    n_t, n_a = xt.shape[0], np.asarray(a_mesh["x0"]).shape[0]
    rows = np.repeat(np.arange(n_t), 4)
    S = sparse.csr_matrix((W["w"].ravel(), (rows, W["nodes"].ravel())), shape=(n_t, n_a))
    fm = far_mask(W, wcfg, h)
    return S, {"kind": "interp", "max_dist_mm": float(W["max_dist_mm"]), "far_n": int(fm.sum()),
               "far_frac": float(fm.mean()) if fm.size else 0.0, "R": None if R is None else R.tolist(),
               "seconds": W["seconds"]}


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


# ====================================================================== 전략 (identity·work·cell)
STRATEGIES: dict = {}


def register(name: str, fn) -> None:
    """전략 등록: fn(src_placed, dst, method, cache) -> (f0 (N_t,3), extra dict). extra 의 내부 키: ``_W``(먼 노드용 W),
    ``_no_conserve``(실행기 LT-4 보정 생략 — 자기 보정이 있는 전략), 그 밖 키는 진단 행에 그대로."""
    STRATEGIES[str(name)] = fn


def cache_key(src_mesh_sha: str, dst: dict, placement: dict | None, method: dict) -> tuple:
    """W 캐시 키 = (원본 메시 sha, 대상 sha, 배치 sha, work 설정 sha) — 호출자가 수명 관리(파일 캐시 포함)."""
    return (src_mesh_sha, dst["sha"], placement_sha(placement), _sha([repr(sorted((method.get("work") or {}).items()))]))


def work_of(src: dict, dst: dict, method: dict, cache: dict | None) -> dict:
    """W 연산자(캐시 키 = ``cache_key``)."""
    key = (src["mesh_sha"], dst["sha"], src.get("placement_sha") or placement_sha(None),
           _sha([repr(sorted((method.get("work") or {}).items()))]))
    if cache is not None and key in cache:
        return cache[key]
    W = build_work(src["mesh"]["x0"], dst["mesh"], dst["elem_mask"], method["work"], dst["h"])
    if cache is not None:
        cache[key] = W
    return W


def _s_identity(src: dict, dst: dict, method: dict, cache):
    from esl.opt import target as tg
    f, _ = tg.entry_load(tg.Target("S1", dst["mesh"], dst["frame"], []), {"node_id": src["mesh"]["node_id"],
                                                                         "f": src["f"]})
    return np.asarray(f, dtype=np.float64), {"fast_path": "identity", "_no_conserve": True}


def _s_work(src: dict, dst: dict, method: dict, cache):
    W = work_of(src, dst, method, cache)
    return apply_work(W, src["f"], dst["mesh"]["x0"].shape[0]), {"_W": W}


def _s_cell(src: dict, dst: dict, method: dict, cache):
    X = dst["mesh"]["x0"]
    s = method.get("cell_size_mm")
    if s is None:                                # legacy 격자: target.entry_load S2 그대로(활성 노드만)
        from esl.opt import target as tg
        if src.get("summary") is None:
            raise EslError("INPUT_INVALID", "legacy 셀 매핑에는 ESL 요약(summary) 필요")
        idx = dst["nodes"]
        st = tg.Target("S2", {"x0": X[idx], "node_id": dst["mesh"]["node_id"][idx]}, dst["frame"], [])
        fr, info = tg.entry_load(st, None, src["summary"], method.get("mapping_opts"))
        if idx.size == X.shape[0]:
            f = np.asarray(fr, dtype=np.float64)
        else:
            f = np.zeros_like(X)
            f[idx] = fr
        return f, {"corr_rel": float(info.get("equilibrate_correction_rel") or 0.0), "_no_conserve": True}
    orig = src.get("orig") or src                # 새 요약 = 원본 frame·원본 좌표(셀 사상은 frame 정규화 — 배치 무관)
    raw = {"x0": orig["mesh"]["x0"], "f": orig["f"]}
    f0, extra = cell_loads(raw, src["frame"], dst["mesh"], dst["frame"], dst["nodes"], float(s),
                           lambda: work_of(src, dst, method, cache),
                           float(method.get("min_spread") or mp.MIN_SPREAD))
    out = {k: extra[k] for k in ("small_frac", "n_cells_loaded", "n_cells_small")}
    key_hit = [v for k, v in (cache or {}).items() if isinstance(k, tuple) and k[0] == src["mesh_sha"]
               and k[1] == dst["sha"]]
    if extra["n_cells_small"] and key_hit:
        out["_W"] = key_hit[0]
    return f0, out


register("identity", _s_identity)
register("work", _s_work)
register("cell", _s_cell)


def _metrics(f, extra: dict) -> dict:
    a = np.linalg.norm(np.asarray(f, dtype=np.float64), axis=1)
    return {"sum_abs_f": float(a.sum()), "max_abs_f": float(a.max()) if a.size else 0.0, **extra}


load_metrics = _metrics


# ====================================================================== 실행기
def transfer(src: dict, dst: dict, method: dict, placement: dict | None = None, identity: dict | None = None,
             cache: dict | None = None) -> tuple[np.ndarray, dict]:
    """원본 1개 → (대상 노드힘 (N_t,3), 진단 행 §5 primary 키 + strategy). identity 자동 경로 = work 이고 같은 메시(LT-22)."""
    name = str(method["name"])
    if name not in STRATEGIES:
        raise EslError("CONFIG_INVALID", f"load_transfer method: {name!r} (등록 {sorted(STRATEGIES)})")
    idn = identity or {"key": "none"}
    strat = name
    if name == "work" and dst["elem_mask"] is None and same_mesh(src["mesh"], dst["mesh"], idn.get("key", "none"),
                                                                 float(idn.get("coord_tol_rel") or 0.005)):
        strat = "identity"
    if strat == "identity":
        sp = src
    else:
        if (placement or {}).get("kind") == "frame":         # frame 배치 = 원본 ESL frame → 대상 frame(없으면 각자 것)
            placement = {"src_frame": src.get("frame"), "dst_frame": dst.get("frame"), **placement}
        xp, fp = place(src["mesh"]["x0"], src["f"], placement)
        sp = {**src, "mesh": {**src["mesh"], "x0": xp}, "f": fp, "orig": src, "placement_sha": placement_sha(placement)}
    X = dst["mesh"]["x0"]
    b = balance(sp["mesh"]["x0"], sp["f"])
    f0, extra = STRATEGIES[strat](sp, dst, method, cache)
    extra = dict(extra)
    W = extra.pop("_W", None)
    if extra.pop("_no_conserve", False):
        f = f0
        dF, dM = _errs(X, f, b)
        cons = {"dF_rel": dF, "dM_rel_before": dM, "dM_rel": dM, "corr_rel": float(extra.pop("corr_rel", 0.0))}
    else:
        f, cons = conserve(X, f0, dst["nodes"], b)
    far_frac = 0.0 if strat == "identity" else None
    if W is not None:
        fm = far_mask(W, method["work"], dst["h"])
        far_frac = float(np.linalg.norm(sp["f"][fm], axis=1).sum() / b["sabs"]) if b["sabs"] > 0 else 0.0
        extra["_far"] = (int(fm.sum()), float(W["max_dist_mm"]), int(W["newton_fallback_n"]), float(W["seconds"]),
                         sp["mesh_sha"])
    row = _metrics(f, {**cons, "far_frac": far_frac, **extra, "strategy": strat})
    return f, row


def variant_label(method_name: str, cell_size_mm) -> str:
    """진단 variant 이름: work | cell:legacy | cell:<s> | <등록 이름>."""
    if method_name == "cell":
        return "cell:legacy" if cell_size_mm is None else f"cell:{float(cell_size_mm):g}"
    return str(method_name)


def run_transfer_plan(plan: dict, srcs: list[dict], dst: dict, method: dict, cache: dict | None = None
                      ) -> tuple[list, dict]:
    """공용 실행기 1개. plan = 해석된 계획 {identity{key, coord_tol_rel}, placement{kind, …}}(계획 표·배치는 모듈 밖에서 정함).
    반환 ([(key, F)], {variant, method, cell_size_mm, fast_path, per_esl[행 + entry_id], transfer{max_dist_mm, far_n,
    newton_fallback_n, seconds}(원본 메시마다 1회), warnings[LT_ESL_UNBALANCED]})."""
    cache = cache if cache is not None else {}
    s = None if method["name"] == "work" else method.get("cell_size_mm")
    out, per, warns = [], [], []
    tr = {"max_dist_mm": 0.0, "far_n": 0, "newton_fallback_n": 0, "seconds": 0.0}
    seen: set = set()
    for src in srcs:
        b = balance(src["mesh"]["x0"], src["f"])
        if b["sabs"] > 0 and float(np.linalg.norm(b["F"])) / b["sabs"] > UNBALANCED_REL:
            warns.append({"code": "LT_ESL_UNBALANCED", "entry_id": src["key"],
                          "rel": float(np.linalg.norm(b["F"])) / b["sabs"]})
        f, row = transfer(src, dst, method, plan.get("placement"), plan.get("identity"), cache)
        fr = row.pop("_far", None)
        if fr is not None and fr[4] not in seen:
            seen.add(fr[4])
            tr["far_n"] += fr[0]
            tr["max_dist_mm"] = max(tr["max_dist_mm"], fr[1])
            tr["newton_fallback_n"] += fr[2]
            tr["seconds"] += fr[3]
        out.append((src["key"], f))
        per.append({"entry_id": src["key"], **row})
    fast = bool(per) and all(p["strategy"] == "identity" for p in per)
    return out, {"variant": variant_label(method["name"], s), "method": method["name"], "cell_size_mm": s,
                 "fast_path": "identity" if fast else None, "per_esl": per, "transfer": tr, "warnings": warns}

def far_state(info: dict, wcfg: dict) -> tuple[str | None, float]:
    """먼 노드 판정(LT-5): (None | LT_FAR_NODES | LT_TRANSFER_FAILED, ESL 최대 far_frac)."""
    ff = max([float(p.get("far_frac") or 0.0) for p in info["per_esl"]] or [0.0])
    if ff > float(wcfg["far_fail_frac"]):
        return "LT_TRANSFER_FAILED", ff
    if ff > float(wcfg["far_warn_frac"]):
        return "LT_FAR_NODES", ff
    return None, ff
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
