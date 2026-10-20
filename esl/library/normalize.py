"""정규화 좌표계와 격자 요약 (계약 esl_p2_library.md §1).

좌표계 ``frame(x0, axis_ref, conn, elem_type)``:
- 평면 = 2차 모멘트 주축(PCA). ``conn`` 을 주면 **면적 가중**(삼각형 정확 적분, 쿼드는 대각선 분할) — 메시 밀도와
  무관한 기하량. 없으면 절점 균등 가중.
- 면내 두 주축 중 ``axis_ref["xi"]`` 와 |내적|이 큰 쪽이 ξ(가로), 다른 쪽이 η(세로). 부호는 각각
  ``axis_ref`` 의 xi·eta 와의 내적이 양수가 되도록 고정(기본 ξ≈+X, η≈+Z) → 모델마다 PCA 부호가 뒤집히지 않음.
- n = ξ × η (오른손계). 기본 참조축이면 n = −Y. ``axis_ref["n"]`` 을 주면 n·n_ref < 0 일 때 경고만 한다
  (오른손계를 유지해야 국부 모멘트 성분이 일관되므로 n 부호를 따로 뒤집지 않는다).
- 바운딩: 절점 투영 a=(x−o)·ξ, b=(x−o)·η 의 [min, max] → ξ,η ∈ [0,1].

격자 ``grid_summary(x0, f, nx, ny, frame)``:
- 셀 (i,j): i = floor(ξ·nx + 1e-9), j = floor(η·ny + 1e-9) (셀 경계 위 노드는 위쪽 셀, ξ=1 은 마지막 셀). 셀 중심 c_ij = 평면 위 점
  o + a_c ξ + b_c η (ζ=0) — 메시와 무관한 기하 기준점(대상 메시에서도 같은 정의 → 매핑 기준점).
- 셀 합력 F = Σ f_i, 셀 합모멘트 M = Σ (x_i − c_ij) × f_i (셀 중심 기준). 전역 성분과 국부(ξ,η,n) 성분 둘 다.
- 전체 합력·합모멘트(좌표계 원점 기준), Σ|f|, 상위 절점력(정규화 좌표).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

DEFAULT_AXIS_REF = {"xi": [1.0, 0.0, 0.0], "eta": [0.0, 0.0, 1.0]}
AMBIGUOUS_DOT = 1e-6
BOUNDARY_EPS = 1e-9


def _triangles(conn, elem_type):
    conn = np.asarray(conn, dtype=np.int64)
    et = np.asarray(elem_type).astype(int)
    q = et == 4
    tri = [conn[~q][:, :3], conn[q][:, [0, 1, 2]], conn[q][:, [0, 2, 3]]]
    return np.concatenate(tri, axis=0)


def surface_moments(x0, conn, elem_type):
    """면적, 면적 중심, 중심 기준 2차 모멘트 텐서 ∫(x−c)(x−c)ᵀ dA (삼각형 정확식)."""
    x0 = np.asarray(x0, dtype=np.float64)
    T = _triangles(conn, elem_type)
    a, b, c = x0[T[:, 0]], x0[T[:, 1]], x0[T[:, 2]]
    A = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    At = float(A.sum())
    if At <= 0:
        raise EslError("INPUT_INVALID", "면적이 0 인 메시")
    s = a + b + c
    cen = (A[:, None] * s / 3.0).sum(axis=0) / At
    # ∫ x xᵀ dA = A/12 (Σ v vᵀ + s sᵀ)
    S = (np.einsum("t,ti,tj->ij", A, a, a) + np.einsum("t,ti,tj->ij", A, b, b) + np.einsum("t,ti,tj->ij", A, c, c)
         + np.einsum("t,ti,tj->ij", A, s, s)) / 12.0
    C = S - At * np.outer(cen, cen)
    return At, cen, C


def node_areas(x0, conn, elem_type) -> np.ndarray:
    """절점 기여 면적(요소 면적을 꼭지점 수로 균등 분배) — 합성 시험·하중 밀도 계산용."""
    x0 = np.asarray(x0, dtype=np.float64)
    T = _triangles(conn, elem_type)
    a, b, c = x0[T[:, 0]], x0[T[:, 1]], x0[T[:, 2]]
    A = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    out = np.zeros(x0.shape[0])
    for k in range(3):
        np.add.at(out, T[:, k], A / 3.0)
    return out


def frame(x0, axis_ref=None, conn=None, elem_type=None) -> dict:
    x0 = np.asarray(x0, dtype=np.float64)
    if x0.ndim != 2 or x0.shape[1] != 3 or x0.shape[0] < 3:
        raise EslError("INPUT_INVALID", "x0 는 (N≥3, 3)")
    ref = dict(DEFAULT_AXIS_REF)
    if axis_ref:
        ref.update({k: v for k, v in axis_ref.items() if v is not None})
    warns: list[str] = []
    if conn is not None:
        _, o, C = surface_moments(x0, conn, elem_type)
        method = "area"
    else:
        o = x0.mean(axis=0)
        P = x0 - o
        C = P.T @ P
        method = "nodes"
    w, V = np.linalg.eigh(C)                         # 오름차순
    if w[2] <= 0 or w[1] <= 1e-12 * w[2]:
        raise EslError("INPUT_INVALID", "형상이 공선 — 평면 주축을 정할 수 없음")
    e_a, e_b = V[:, 2], V[:, 1]                      # 면내 주축(큰 순)
    xr = np.asarray(ref["xi"], dtype=np.float64)
    er = np.asarray(ref["eta"], dtype=np.float64)
    da, db = abs(e_a @ xr), abs(e_b @ xr)
    if abs(da - db) <= AMBIGUOUS_DOT * max(np.linalg.norm(xr), 1.0):
        warns.append("axis_ref.xi 가 두 면내 주축과 같은 각도 — 최대 주축을 ξ 로 사용")
        ex, ee = e_a, e_b
    elif da >= db:
        ex, ee = e_a, e_b
    else:
        ex, ee = e_b, e_a
    if ex @ xr < 0:
        ex = -ex
    if abs(ee @ er) <= AMBIGUOUS_DOT:
        warns.append("axis_ref.eta 가 η 축과 수직 — η 부호를 n = ξ×η 가 axis_ref 의 xi×eta 와 같은 쪽이 되도록 정함")
        nref = np.cross(xr, er)
        if np.cross(ex, ee) @ nref < 0:
            ee = -ee
    elif ee @ er < 0:
        ee = -ee
    n = np.cross(ex, ee)
    if ref.get("n") is not None and n @ np.asarray(ref["n"], dtype=np.float64) < 0:
        warns.append("n = ξ×η 가 axis_ref.n 과 반대 방향(오른손계 유지 — 후면 바깥 규약 확인 필요)")
    a = (x0 - o) @ ex
    b = (x0 - o) @ ee
    z = (x0 - o) @ n
    if a.max() - a.min() <= 0 or b.max() - b.min() <= 0:
        raise EslError("INPUT_INVALID", "정규화 바운딩 폭이 0")
    return {"schema": "esl/frame/1", "method": method, "origin": o.tolist(), "e_xi": ex.tolist(),
            "e_eta": ee.tolist(), "n": n.tolist(), "a_range": [float(a.min()), float(a.max())],
            "b_range": [float(b.min()), float(b.max())], "z_range": [float(z.min()), float(z.max())],
            "L_xi": float(a.max() - a.min()), "L_eta": float(b.max() - b.min()),
            "axis_ref": {k: (None if v is None else list(map(float, v))) for k, v in ref.items()},
            "warnings": warns}


def rotation(fr: dict) -> np.ndarray:
    """R (3,3): 행 = ξ, η, n.  국부 = R @ 전역, 전역 = Rᵀ @ 국부."""
    return np.array([fr["e_xi"], fr["e_eta"], fr["n"]], dtype=np.float64)


def local_coords(fr: dict, x) -> np.ndarray:
    """(N,3) → (N,3) [ξ, η, ζ]: ξ,η ∈ [0,1] 정규화, ζ = 평면 법선 거리(길이 단위)."""
    x = np.asarray(x, dtype=np.float64).reshape(-1, 3)
    P = x - np.asarray(fr["origin"])
    a, b, z = P @ np.asarray(fr["e_xi"]), P @ np.asarray(fr["e_eta"]), P @ np.asarray(fr["n"])
    a0, a1 = fr["a_range"]
    b0, b1 = fr["b_range"]
    return np.column_stack([(a - a0) / (a1 - a0), (b - b0) / (b1 - b0), z])


def to_global(fr: dict, xi, eta, zeta=0.0) -> np.ndarray:
    """정규화 좌표 → 전역 점."""
    xi, eta = np.broadcast_arrays(np.asarray(xi, float), np.asarray(eta, float))
    zeta = np.broadcast_to(np.asarray(zeta, float), xi.shape)
    a0, a1 = fr["a_range"]
    b0, b1 = fr["b_range"]
    a = a0 + xi * (a1 - a0)
    b = b0 + eta * (b1 - b0)
    o = np.asarray(fr["origin"])
    return (o + a[..., None] * np.asarray(fr["e_xi"]) + b[..., None] * np.asarray(fr["e_eta"])
            + zeta[..., None] * np.asarray(fr["n"]))


def cell_index(fr: dict, x, nx: int, ny: int):
    """(N,) i, j 셀 번호 (경계 포함, 바깥 점은 가장자리 셀로 clip)."""
    loc = local_coords(fr, x)
    # 셀 경계 위 노드(ξ·nx 가 정수)는 반올림 오차와 무관하게 위쪽 셀로: floor(ξ·nx + BOUNDARY_EPS)
    i = np.clip(np.floor(loc[:, 0] * nx + BOUNDARY_EPS).astype(np.int64), 0, nx - 1)
    j = np.clip(np.floor(loc[:, 1] * ny + BOUNDARY_EPS).astype(np.int64), 0, ny - 1)
    return i, j, loc


def cell_centers(fr: dict, nx: int, ny: int) -> np.ndarray:
    """(nx, ny, 3) 셀 중심 전역 좌표(평면 위, ζ=0)."""
    xi = (np.arange(nx) + 0.5) / nx
    eta = (np.arange(ny) + 0.5) / ny
    XI, ETA = np.meshgrid(xi, eta, indexing="ij")
    return to_global(fr, XI, ETA)


def grid_summary(x0, f, nx: int = 24, ny: int = 14, fr: dict | None = None, top_n: int = 50,
                 node_id=None, axis_ref=None, conn=None, elem_type=None) -> dict:
    """셀별 합력·합모멘트(셀 중심 기준, 전역 + 국부) 등. 반환 dict 의 배열은 npz 에 그대로 저장 가능."""
    x0 = np.asarray(x0, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    if f.shape != x0.shape:
        raise EslError("INPUT_INVALID", "f 와 x0 는 같은 (N,3)")
    if nx < 1 or ny < 1:
        raise EslError("INPUT_INVALID", "nx, ny ≥ 1")
    if fr is None:
        fr = frame(x0, axis_ref, conn, elem_type)
    i, j, loc = cell_index(fr, x0, nx, ny)
    cid = i * ny + j
    C = cell_centers(fr, nx, ny).reshape(-1, 3)
    r = x0 - C[cid]
    m = np.cross(r, f)
    cF = np.zeros((nx * ny, 3))
    cM = np.zeros((nx * ny, 3))
    for k in range(3):
        cF[:, k] = np.bincount(cid, weights=f[:, k], minlength=nx * ny)
        cM[:, k] = np.bincount(cid, weights=m[:, k], minlength=nx * ny)
    cnt = np.bincount(cid, minlength=nx * ny)
    R = rotation(fr)
    o = np.asarray(fr["origin"])
    tF = f.sum(axis=0)
    tM = np.cross(x0 - o, f).sum(axis=0)
    mag = np.linalg.norm(f, axis=1)
    order = np.lexsort((np.arange(mag.size), -mag))[: int(top_n)]
    nid = np.arange(x0.shape[0], dtype=np.int64) if node_id is None else np.asarray(node_id, dtype=np.int64)
    return {
        "nx": int(nx), "ny": int(ny),
        "cell_F": cF.reshape(nx, ny, 3), "cell_M": cM.reshape(nx, ny, 3),
        "cell_F_loc": (cF @ R.T).reshape(nx, ny, 3), "cell_M_loc": (cM @ R.T).reshape(nx, ny, 3),
        "cell_n": cnt.reshape(nx, ny).astype(np.int64),
        "cell_center": C.reshape(nx, ny, 3),
        "total_F": tF, "total_M": tM, "total_F_loc": R @ tF, "total_M_loc": R @ tM,
        "sum_abs_f": np.float64(mag.sum()),
        "top_node_id": nid[order], "top_xi": loc[order, 0], "top_eta": loc[order, 1],
        "top_f": f[order], "top_f_loc": f[order] @ R.T, "top_mag": mag[order],
    }
