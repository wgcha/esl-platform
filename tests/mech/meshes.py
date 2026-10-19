"""시험용 메시 생성기."""
import numpy as np


def rect_quads(L, B, nx, ny, distort=0.0, seed=0):
    xs = np.linspace(0, L, nx + 1)
    ys = np.linspace(0, B, ny + 1)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    P = np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], axis=1)
    if distort:
        rng = np.random.default_rng(seed)
        inner = (P[:, 0] > 0) & (P[:, 0] < L) & (P[:, 1] > 0) & (P[:, 1] < B)
        h = min(L / nx, B / ny)
        P[inner, :2] += distort * h * rng.uniform(-1, 1, (inner.sum(), 2))
    nid = lambda i, j: i * (ny + 1) + j
    conn = []
    for i in range(nx):
        for j in range(ny):
            conn.append([nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)])
    return P, np.array(conn), np.full(len(conn), 4, np.int8)


def quads_to_trias(conn, alternate=True):
    out = []
    for k, (a, b, c, d) in enumerate(conn):
        if alternate and k % 2:
            out += [[a, b, d, -1], [b, c, d, -1]]
        else:
            out += [[a, b, c, -1], [a, c, d, -1]]
    return np.array(out), np.full(len(out), 3, np.int8)


def macneal_patch():
    """MacNeal–Harder 왜곡 5요소 patch (0.24×0.12)."""
    P = np.array([[0, 0], [0.24, 0], [0.24, 0.12], [0, 0.12],
                  [0.04, 0.02], [0.18, 0.03], [0.16, 0.08], [0.08, 0.08]], float)
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7], [4, 5, 6, 7]])
    X = np.c_[P, np.zeros(len(P))]
    return X, conn, np.full(5, 4, np.int8), np.arange(4), np.arange(4, 8)


def rot_matrix(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def rigid_modes(X):
    """(6N, 6) 선형 강체 모드: 병진 3 + 원점 기준 회전 3 (회전 dof 포함)."""
    N = X.shape[0]
    Rm = np.zeros((N, 6, 6))
    for i in range(3):
        Rm[:, i, i] = 1.0
        w = np.zeros(3)
        w[i] = 1.0
        Rm[:, :3, 3 + i] = np.cross(w, X)
        Rm[:, 3 + i, 3 + i] = 1.0
    return Rm.reshape(6 * N, 6)


def cylinder_panel(R, ang, H, nt, nz):
    th = np.linspace(-ang / 2, ang / 2, nt + 1)
    zs = np.linspace(0, H, nz + 1)
    T, Z = np.meshgrid(th, zs, indexing="ij")
    X = np.stack([R * np.cos(T).ravel(), R * np.sin(T).ravel(), Z.ravel()], axis=1)
    nid = lambda i, j: i * (nz + 1) + j
    conn = [[nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)] for i in range(nt) for j in range(nz)]
    return X, np.array(conn), np.full(len(conn), 4, np.int8)


def spherical_cap(R, ang, n):
    """구면 위 격자(뒤틀린 쿼드)."""
    a = np.linspace(-ang / 2, ang / 2, n + 1)
    A, B = np.meshgrid(a, a, indexing="ij")
    d = np.stack([np.tan(A).ravel(), np.tan(B).ravel(), np.ones(A.size)], axis=1)
    X = R * d / np.linalg.norm(d, axis=1)[:, None]
    nid = lambda i, j: i * (n + 1) + j
    conn = [[nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)] for i in range(n) for j in range(n)]
    return X, np.array(conn), np.full(len(conn), 4, np.int8)
