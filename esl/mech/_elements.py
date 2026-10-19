"""쉘 요소 배치(벡터화) 커널. 공개 API가 아님 — `esl.mech.shell` 전용.

규약
----
- 요소 국부 dof 순서(노드당 6): [u, v, w, θx, θy, θz] (국부계, 오른손 회전벡터).
- 판 운동학: 두께방향 변위 u = z·βx, v = z·βy, 여기서 βx = θy, βy = −θx.
  곡률(공학 전단) κ = [βx,x, βy,y, βx,y + βy,x], 횡전단 γ = [w,x + βx, w,y + βy].
- 막 변형률 벡터는 공학 전단 [εxx, εyy, γxy]; 출력 단계에서 텐서(γ/2)로 바꾼다.
- 국부계(ShellModel 문서 참조): 법선 n(QUAD = 대각선 외적, TRIA = 변 외적),
  e1 = 노드1→2 를 평면에 투영한 방향, e2 = n × e1. 원점 = 노드 평균.
- 뒤틀린(warped) QUAD: 실제 노드 X_i 와 투영점 p_i = X_i − h_i n 을 강체 링크로 잇는다
  (u_p = u_X + θ × (p − X)). 강체 운동이 정확히 보존된다(MSC 계열 warp 보정과 같은 생각).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

G2 = 1.0 / np.sqrt(3.0)
QUAD_GP = np.array([[-G2, -G2], [G2, -G2], [G2, G2], [-G2, G2]])
QUAD_XI = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
SHEAR_K = 5.0 / 6.0


# --------------------------------------------------------------------------
# 기하·국부계
# --------------------------------------------------------------------------
def local_frames(Xe: np.ndarray):
    """Xe (n, nn, 3) → R (n,3,3) 행=e1,e2,n · xy (n,nn,2) 투영 국부좌표 · off (n,nn,3) 투영점−실제점(전역)."""
    nn = Xe.shape[1]
    c = Xe.mean(axis=1)
    if nn == 4:
        nrm = np.cross(Xe[:, 2] - Xe[:, 0], Xe[:, 3] - Xe[:, 1])
    else:
        nrm = np.cross(Xe[:, 1] - Xe[:, 0], Xe[:, 2] - Xe[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    scale = np.max(np.linalg.norm(Xe - c[:, None, :], axis=2), axis=1)
    bad = ~(ln > 1e-12 * np.maximum(scale, 1e-300) ** 2)
    if np.any(bad):
        raise EslError("INPUT_INVALID", f"퇴화 요소(면적≈0) {int(bad.sum())}개 (배치 내 첫 위치 {int(np.argmax(bad))})")
    n = nrm / ln[:, None]
    a = Xe[:, 1] - Xe[:, 0]
    a = a - np.sum(a * n, axis=1)[:, None] * n
    la = np.linalg.norm(a, axis=1)
    if np.any(la <= 1e-12 * scale):
        raise EslError("INPUT_INVALID", "요소 변 1→2 길이≈0")
    e1 = a / la[:, None]
    e2 = np.cross(n, e1)
    R = np.stack([e1, e2, n], axis=1)
    rel = Xe - c[:, None, :]
    xy = np.einsum("nij,nkj->nki", R[:, :2, :], rel)
    h = np.einsum("nj,nkj->nk", n, rel)
    off = -h[:, :, None] * n[:, None, :]
    return R, xy, off


def transform(R: np.ndarray, off: np.ndarray) -> np.ndarray:
    """전역 요소 dof → 국부 투영점 dof 변환 T (n, 6nn, 6nn).  q_loc = T q_glob.

    노드 블록 [[R, −R·S(d)], [0, R]], S(d)θ = d × θ, d = 투영점 − 실제점.
    (u_p = u + θ × d = u − d × θ)
    """
    n, nn, _ = off.shape
    T = np.zeros((n, 6 * nn, 6 * nn))
    d = off
    S = np.zeros((n, nn, 3, 3))
    S[:, :, 0, 1] = -d[:, :, 2]
    S[:, :, 0, 2] = d[:, :, 1]
    S[:, :, 1, 0] = d[:, :, 2]
    S[:, :, 1, 2] = -d[:, :, 0]
    S[:, :, 2, 0] = -d[:, :, 1]
    S[:, :, 2, 1] = d[:, :, 0]
    RS = -np.einsum("nij,nkjl->nkil", R, S)
    for i in range(nn):
        b = 6 * i
        T[:, b:b + 3, b:b + 3] = R
        T[:, b:b + 3, b + 3:b + 6] = RS[:, i]
        T[:, b + 3:b + 6, b + 3:b + 6] = R
    return T


def plane_stress_D(E: np.ndarray, nu: np.ndarray) -> np.ndarray:
    c = E / (1.0 - nu ** 2)
    D = np.zeros((E.shape[0], 3, 3))
    D[:, 0, 0] = c
    D[:, 1, 1] = c
    D[:, 0, 1] = c * nu
    D[:, 1, 0] = c * nu
    D[:, 2, 2] = c * (1.0 - nu) / 2.0
    return D


# --------------------------------------------------------------------------
# QUAD 보조
# --------------------------------------------------------------------------
def _q4_dN(xi: float, eta: float):
    s = QUAD_XI
    N = 0.25 * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta)
    Nxi = 0.25 * s[:, 0] * (1 + s[:, 1] * eta)
    Neta = 0.25 * s[:, 1] * (1 + s[:, 0] * xi)
    return N, Nxi, Neta


def _q4_jac(xy, Nxi, Neta):
    """J (n,2,2) = [[x_ξ, y_ξ],[x_η, y_η]], detJ, invJ, 전역 미분 Nx, Ny (n,4)."""
    J = np.empty((xy.shape[0], 2, 2))
    J[:, 0, :] = np.einsum("k,nkj->nj", Nxi, xy)
    J[:, 1, :] = np.einsum("k,nkj->nj", Neta, xy)
    det = J[:, 0, 0] * J[:, 1, 1] - J[:, 0, 1] * J[:, 1, 0]
    if np.any(det <= 0):
        raise EslError("INPUT_INVALID", "QUAD 야코비안 ≤ 0 (오목·뒤집힌 요소)")
    inv = np.empty_like(J)
    inv[:, 0, 0] = J[:, 1, 1] / det
    inv[:, 1, 1] = J[:, 0, 0] / det
    inv[:, 0, 1] = -J[:, 0, 1] / det
    inv[:, 1, 0] = -J[:, 1, 0] / det
    Nx = inv[:, 0, 0, None] * Nxi + inv[:, 0, 1, None] * Neta
    Ny = inv[:, 1, 0, None] * Nxi + inv[:, 1, 1, None] * Neta
    return J, det, inv, Nx, Ny


def _membrane_B(Nx, Ny):
    nn = Nx.shape[1]
    B = np.zeros((Nx.shape[0], 3, 2 * nn))
    B[:, 0, 0::2] = Nx
    B[:, 1, 1::2] = Ny
    B[:, 2, 0::2] = Ny
    B[:, 2, 1::2] = Nx
    return B


def _plate_Bb(Nx, Ny):
    """곡률(공학) B, 판 dof [w, θx, θy]/노드. βx=θy, βy=−θx."""
    nn = Nx.shape[1]
    B = np.zeros((Nx.shape[0], 3, 3 * nn))
    B[:, 0, 2::3] = Nx
    B[:, 1, 1::3] = -Ny
    B[:, 2, 2::3] = Ny
    B[:, 2, 1::3] = -Nx
    return B


def _mitc4_cov_row(xy, xi, eta, which):
    """공변 횡전단 γ_ξ(which=0) 또는 γ_η(1)의 판 dof 행 (n,12), (xi,eta)에서 평가."""
    N, Nxi, Neta = _q4_dN(xi, eta)
    dN = Nxi if which == 0 else Neta
    xd = np.einsum("k,nk->n", dN, xy[:, :, 0])
    yd = np.einsum("k,nk->n", dN, xy[:, :, 1])
    row = np.zeros((xy.shape[0], 12))
    row[:, 0::3] = dN[None, :]
    row[:, 2::3] = N[None, :] * xd[:, None]      # βx = θy
    row[:, 1::3] = -N[None, :] * yd[:, None]     # βy = −θx
    return row


def quad_local(xy, t, E, nu, drill_factor):
    """QUAD 국부 강성 (n,24,24) + 중심 변형률 회복 행렬 S (n,6,24): [εm(공학) ; κ(공학)]."""
    n = xy.shape[0]
    D = plane_stress_D(E, nu)
    Dm = D * t[:, None, None]
    Db = D * (t ** 3 / 12.0)[:, None, None]
    Gs = SHEAR_K * E / (2.0 * (1.0 + nu)) * t

    # 중심
    _, Nxi0, Neta0 = _q4_dN(0.0, 0.0)
    J0, det0, inv0, Nx0, Ny0 = _q4_jac(xy, Nxi0, Neta0)

    Kcc = np.zeros((n, 8, 8))
    Kci = np.zeros((n, 8, 4))
    Kii = np.zeros((n, 4, 4))
    Kb = np.zeros((n, 12, 12))
    Ks = np.zeros((n, 12, 12))
    area = np.zeros(n)

    # MITC4 결합점: γ_ξ at A(0,+1), C(0,−1);  γ_η at D(+1,0), B(−1,0)
    gA = _mitc4_cov_row(xy, 0.0, 1.0, 0)
    gC = _mitc4_cov_row(xy, 0.0, -1.0, 0)
    gD = _mitc4_cov_row(xy, 1.0, 0.0, 1)
    gB = _mitc4_cov_row(xy, -1.0, 0.0, 1)

    for xi, eta in QUAD_GP:
        _, Nxi, Neta = _q4_dN(xi, eta)
        J, det, inv, Nx, Ny = _q4_jac(xy, Nxi, Neta)
        area += det
        Bm = _membrane_B(Nx, Ny)
        # 비적합 모드 (QM6, Taylor 보정): P1=1−ξ², P2=1−η²; ∂/∂x = (detJ0/detJ)·J0⁻¹ ∂/∂ξ
        f = (det0 / det)[:, None]
        p1 = np.stack([inv0[:, 0, 0] * (-2 * xi), inv0[:, 1, 0] * (-2 * xi)], axis=1) * f
        p2 = np.stack([inv0[:, 0, 1] * (-2 * eta), inv0[:, 1, 1] * (-2 * eta)], axis=1) * f
        Bi = np.zeros((n, 3, 4))
        Bi[:, 0, 0] = p1[:, 0]
        Bi[:, 0, 1] = p2[:, 0]
        Bi[:, 1, 2] = p1[:, 1]
        Bi[:, 1, 3] = p2[:, 1]
        Bi[:, 2, 0] = p1[:, 1]
        Bi[:, 2, 1] = p2[:, 1]
        Bi[:, 2, 2] = p1[:, 0]
        Bi[:, 2, 3] = p2[:, 0]
        w = det[:, None, None]
        DBm = Dm @ Bm
        Kcc += np.einsum("nki,nkj->nij", Bm, DBm) * w
        Kci += np.einsum("nki,nkj->nij", DBm, Bi) * w
        Kii += np.einsum("nki,nkj->nij", Bi, Dm @ Bi) * w

        Bb = _plate_Bb(Nx, Ny)
        Kb += np.einsum("nki,nkj->nij", Bb, Db @ Bb) * w

        gxi = 0.5 * (1 + eta) * gA + 0.5 * (1 - eta) * gC
        geta = 0.5 * (1 + xi) * gD + 0.5 * (1 - xi) * gB
        gx = inv[:, 0, 0, None] * gxi + inv[:, 0, 1, None] * geta
        gy = inv[:, 1, 0, None] * gxi + inv[:, 1, 1, None] * geta
        Ks += (np.einsum("ni,nj->nij", gx, gx) + np.einsum("ni,nj->nij", gy, gy)) * (Gs * det)[:, None, None]

    # 비적합 모드 정적 응축
    Km = Kcc - Kci @ np.linalg.solve(Kii, np.swapaxes(Kci, 1, 2))

    K = np.zeros((n, 24, 24))
    im = np.array([6 * i + j for i in range(4) for j in (0, 1)])
    ib = np.array([6 * i + j for i in range(4) for j in (2, 3, 4)])
    K[:, im[:, None], im[None, :]] += Km
    K[:, ib[:, None], ib[None, :]] += Kb + Ks

    # 중심 변형률 회복: 비적합 모드 미분은 ξ=η=0 에서 0 → 호환 Q4 B만으로 정확
    S = np.zeros((n, 6, 24))
    S[:, 0:3, im] = _membrane_B(Nx0, Ny0)
    S[:, 3:6, ib] = _plate_Bb(Nx0, Ny0)

    _add_drill(K, Nx0, Ny0, drill_factor * E * t * area, 4)
    return K, S, area


def _add_drill(K, Nx0, Ny0, kd, nn):
    """드릴링: 노드마다 ½·kd·(θz_i − ω_c)², ω_c = ½(v,x − u,y) (요소 중심). 강체 회전에 0."""
    n = K.shape[0]
    g = np.zeros((n, 6 * nn))
    for i in range(nn):
        g[:, 6 * i + 0] = -0.5 * Ny0[:, i]
        g[:, 6 * i + 1] = 0.5 * Nx0[:, i]
    # Σ_i a_i a_iᵀ,  a_i = e_i − g  →  diag(s) − s gᵀ − g sᵀ + nn·g gᵀ,  s = Σ_i e_i (θz 표시)
    s = np.zeros(6 * nn)
    s[5::6] = 1.0
    sg = s[None, :, None] * g[:, None, :]
    M = np.einsum("ni,nj->nij", g, g) * nn - sg - np.swapaxes(sg, 1, 2)
    M[:, np.arange(5, 6 * nn, 6), np.arange(5, 6 * nn, 6)] += 1.0
    K += M * kd[:, None, None]


# --------------------------------------------------------------------------
# TRIA: CST + DKT
# --------------------------------------------------------------------------
_TRI_GP = np.array([[2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3]])
_EDGES = ((0, 1), (1, 2), (2, 0))   # 중간점 4,5,6


def _tri_geom(xy):
    x, y = xy[:, :, 0], xy[:, :, 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    A2 = x[:, 1] * y[:, 2] - x[:, 2] * y[:, 1] - x[:, 0] * y[:, 2] + x[:, 2] * y[:, 0] + x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0]
    if np.any(A2 <= 0):
        raise EslError("INPUT_INVALID", "TRIA 면적 ≤ 0")
    return b / A2[:, None], c / A2[:, None], 0.5 * A2   # Lx, Ly, A


def _dkt_H(xy):
    """6절점 β = H q, β 순서 [βx1,βy1,...,βx6,βy6], q = [w,θx,θy]×3.  (n,12,9)"""
    n = xy.shape[0]
    H = np.zeros((n, 12, 9))
    P = np.array([[0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])   # β_i = P [w,θx,θy]_i
    for i in range(3):
        H[:, 2 * i:2 * i + 2, 3 * i:3 * i + 3] = P
    for k, (i, j) in enumerate(_EDGES):
        dvec = xy[:, j] - xy[:, i]
        l = np.linalg.norm(dvec, axis=1)
        s = dvec / l[:, None]
        M = 0.5 * (np.eye(2)[None] - 1.5 * np.einsum("ni,nj->nij", s, s))   # (n,2,2)
        r = 2 * (3 + k)
        H[:, r:r + 2, 3 * i:3 * i + 3] += M @ P
        H[:, r:r + 2, 3 * j:3 * j + 3] += M @ P
        cw = (1.5 / l)[:, None] * s     # β_k −= (3/2l) s (w_j − w_i)
        H[:, r:r + 2, 3 * i] += cw
        H[:, r:r + 2, 3 * j] -= cw
    return H


def _dkt_Bb(Lx, Ly, H, L):
    """곡률 B (n,3,9) 를 면적좌표 L=(L1,L2,L3) 에서."""
    n = Lx.shape[0]
    Nx = np.zeros((n, 6))
    Ny = np.zeros((n, 6))
    for i in range(3):
        Nx[:, i] = (4 * L[i] - 1) * Lx[:, i]
        Ny[:, i] = (4 * L[i] - 1) * Ly[:, i]
    for k, (i, j) in enumerate(_EDGES):
        Nx[:, 3 + k] = 4 * (Lx[:, i] * L[j] + L[i] * Lx[:, j])
        Ny[:, 3 + k] = 4 * (Ly[:, i] * L[j] + L[i] * Ly[:, j])
    Bbeta = np.zeros((n, 3, 12))
    Bbeta[:, 0, 0::2] = Nx
    Bbeta[:, 1, 1::2] = Ny
    Bbeta[:, 2, 0::2] = Ny
    Bbeta[:, 2, 1::2] = Nx
    return Bbeta @ H


def tria_local(xy, t, E, nu, drill_factor):
    n = xy.shape[0]
    D = plane_stress_D(E, nu)
    Dm = D * t[:, None, None]
    Db = D * (t ** 3 / 12.0)[:, None, None]
    Lx, Ly, A = _tri_geom(xy)
    Bm = _membrane_B(Lx, Ly)
    Km = np.einsum("nki,nkj->nij", Bm, Dm @ Bm) * A[:, None, None]
    H = _dkt_H(xy)
    Kb = np.zeros((n, 9, 9))
    for L in _TRI_GP:
        Bb = _dkt_Bb(Lx, Ly, H, L)
        Kb += np.einsum("nki,nkj->nij", Bb, Db @ Bb) * (A / 3.0)[:, None, None]
    K = np.zeros((n, 18, 18))
    im = np.array([6 * i + j for i in range(3) for j in (0, 1)])
    ib = np.array([6 * i + j for i in range(3) for j in (2, 3, 4)])
    K[:, im[:, None], im[None, :]] += Km
    K[:, ib[:, None], ib[None, :]] += Kb
    S = np.zeros((n, 6, 18))
    S[:, 0:3, im] = Bm
    S[:, 3:6, ib] = _dkt_Bb(Lx, Ly, H, (1 / 3, 1 / 3, 1 / 3))
    _add_drill(K, Lx, Ly, drill_factor * E * t * A, 3)
    return K, S, A
