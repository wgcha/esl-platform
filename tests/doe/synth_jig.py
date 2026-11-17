"""지그 순위(esl_jig_rank.md V-JIG-n) 합성 도구.

- ``plate``: synth_sm.plate(XZ 판, 법선 Y) — 지그 시험 기본은 평판(bow 0).
- ``tie_groups``: 두 짧은 변(x 최소·최대) 근처 노드 묶음(묶음마다 n_per 개, 비공선 2×2) — tie(INTER_TYPE2) 노드 대용.
- ``neighbors`` / ``surface``: 인접 부품 = 대상 판에서 법선(Y)으로 g 떨어진 작은 쉘 판 2개(+Y 쪽) + 솔리드 블록 1개
  (브릭 2×2×1, −Y 쪽 — 외곽 면 삼각형). ``surface`` 는 jig.contact_regions 의 surf dict({"x","tri","tri_part"}).
- ``rib_x``: 지그 선(짧은 변) 사이 스팬 방향(x) 리브 비드 — 깊이 증가 = 굽힘 강성 증가.
- ``write_rad_with_neighbors``: 대상 파트 + 인접 쉘·SH3N·BRICK·TETRA10·BRIC20·PENTA6 파트 + /INTER/TYPE2 카드 rad
  (V-JIG-12·13 용, Backend 시험이 씀).
- ``jig_factor`` / ``solve_jig``: 시험 참조 풀이(지그 = 병진 123).
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth_doe as sd  # noqa: E402
import synth_sm as ss  # noqa: E402

from esl.doe import jig  # noqa: E402

PART_ID = sd.PART_ID
NEIGHBOR_PARTS = {"shell_a": 101, "shell_b": 102, "brick": 103, "pusher": 104}
RAD_PARTS = {"shell": 201, "sh3n": 202, "brick": 203, "tetra10": 204, "bric20": 205, "penta6": 206}
SOLVER = {"drill_factor": 1e-4, "backend": "superlu"}


def plate(nx=24, ny=12, Lx=300.0, Lz=150.0, t=1.0, bow=0.0, n_tria_cols=4):
    return ss.plate(nx=nx, ny=ny, Lx=Lx, Lz=Lz, t=t, bow=bow, n_tria_cols=n_tria_cols)


def _norm_coords(X):
    s = (X[:, 0] - X[:, 0].min()) / np.ptp(X[:, 0])
    t = (X[:, 2] - X[:, 2].min()) / np.ptp(X[:, 2])
    return s, t


def tie_groups(mesh, n_groups=4, n_per=4, edge=0.04, z_pos=(0.25, 0.75)):
    """짧은 변 근처 tie 묶음: 중심 (s = edge | 1 − edge, t ∈ z_pos) 에서 가까운 n_per 노드(거리·인덱스 순)."""
    X = mesh["x0"]
    lo, hi = X.min(axis=0), X.max(axis=0)
    centers = []
    for s in (edge, 1.0 - edge):
        for t in z_pos:
            centers.append((lo[0] + s * (hi[0] - lo[0]), lo[2] + t * (hi[2] - lo[2])))
    centers = centers[:: max(1, len(centers) // n_groups)][:n_groups] if n_groups < len(centers) else centers
    out = []
    for cx, cz in centers:
        d = np.hypot(X[:, 0] - cx, X[:, 2] - cz)
        out.append(np.lexsort((np.arange(d.size), d))[:n_per].astype(np.int64))
    return out


def jig_of(groups):
    return np.unique(np.concatenate(groups)).astype(np.int64)


# ---------------------------------------------------------------- 인접 부품
def _bow_y(mesh, x, z, bow):
    X = mesh["x0"]
    lo, hi = X.min(axis=0), X.max(axis=0)
    return bow * np.sin(np.pi * (x - lo[0]) / (hi[0] - lo[0])) * np.sin(np.pi * (z - lo[2]) / (hi[2] - lo[2]))


def _shell_grid(x0, x1, z0, z1, nx, nz, yfun):
    xs = np.linspace(x0, x1, nx + 1)
    zs = np.linspace(z0, z1, nz + 1)
    P = np.array([[x, yfun(x, z), z] for x in xs for z in zs])
    nid = lambda i, j: i * (nz + 1) + j   # noqa: E731
    Q = np.array([[nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)] for i in range(nx) for j in range(nz)],
                 dtype=np.int64)
    return P, Q


def _brick_grid(x0, x1, z0, z1, ytop, h, nx=2, nz=2):
    xs = np.linspace(x0, x1, nx + 1)
    zs = np.linspace(z0, z1, nz + 1)
    P, idx = [], {}
    for k, dy in enumerate((-h, 0.0)):
        for i, x in enumerate(xs):
            for j, z in enumerate(zs):
                idx[(i, j, k)] = len(P)
                P.append([x, ytop(x, z) + dy, z])
    H = []
    for i in range(nx):
        for j in range(nz):
            b = [idx[(i, j, 0)], idx[(i + 1, j, 0)], idx[(i + 1, j + 1, 0)], idx[(i, j + 1, 0)]]
            t = [idx[(i, j, 1)], idx[(i + 1, j, 1)], idx[(i + 1, j + 1, 1)], idx[(i, j + 1, 1)]]
            H.append(b + t)
    return np.array(P, float), np.array(H, dtype=np.int64)


HEX_FACES = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def ext_faces(H):
    """솔리드(헥사) 외곽 면 = 공유되지 않는 면(EXT 규칙)."""
    F = np.concatenate([H[:, list(f)] for f in HEX_FACES], axis=0)
    key = np.sort(F, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return F[cnt[inv.reshape(-1)] == 1]


BOXES = {  # 이름: (s0, s1, t0, t1, 쪽 ±1(Y), 종류)
    "shell_a": (0.22, 0.45, 0.15, 0.48, +1, "shell"),
    "shell_b": (0.55, 0.80, 0.52, 0.85, +1, "shell"),
    "brick": (0.40, 0.60, 0.55, 0.90, -1, "brick"),
    "pusher": (0.42, 0.58, 0.25, 0.75, -1, "shell"),     # 판 중앙 아래(−Y) — 중앙 덴트(+Y)를 미는 부품
}


def neighbors(mesh, gap=1.0, which=("shell_a", "shell_b", "brick"), bow=0.0, brick_h=10.0, boxes=None):
    """인접 부품 dict 목록: {"name", "part", "x" (P,3), "quad" (m,4) 국부 인덱스(쉘 = 요소, 솔리드 = 외곽 면), "hex"?}.
    기본 상자(BOXES, 판 정규 좌표 s·t): shell_a·shell_b = +Y 쪽 +g 쉘 판, brick = −Y 쪽 −g 브릭 2×2×1, pusher = 중앙 −Y 쉘."""
    X = mesh["x0"]
    lo, hi = X.min(axis=0), X.max(axis=0)
    L = hi - lo
    by = lambda x, z: _bow_y(mesh, x, z, bow)   # noqa: E731
    bx = dict(BOXES, **(boxes or {}))
    out = []
    for name in which:
        s0, s1, t0, t1, side, kind = bx[name]
        x0, x1 = lo[0] + s0 * L[0], lo[0] + s1 * L[0]
        z0, z1 = lo[2] + t0 * L[2], lo[2] + t1 * L[2]
        part = NEIGHBOR_PARTS[name]
        if kind == "brick":
            if side > 0:
                P, H = _brick_grid(x0, x1, z0, z1, lambda x, z: by(x, z) + gap + brick_h, brick_h)
            else:
                P, H = _brick_grid(x0, x1, z0, z1, lambda x, z: by(x, z) - gap, brick_h)
            out.append({"name": name, "part": part, "x": P, "quad": ext_faces(H), "hex": H})
        else:
            P, Q = _shell_grid(x0, x1, z0, z1, 7, 6, lambda x, z: by(x, z) + side * gap)
            out.append({"name": name, "part": part, "x": P, "quad": Q})
    return out


def surface(parts) -> dict:
    """인접 부품 → jig surf dict: 쿼드 (0,1,2)(0,2,3) 삼각형, 부품 순서대로 이어 붙임."""
    xs, tris, tp = [], [], []
    off = 0
    for p in parts:
        Q = np.asarray(p["quad"], dtype=np.int64) + off
        tris.append(np.concatenate([Q[:, [0, 1, 2]], Q[:, [0, 2, 3]]], axis=0))
        tp.append(np.full(2 * Q.shape[0], int(p["part"]), dtype=np.int64))
        xs.append(np.asarray(p["x"], float))
        off += xs[-1].shape[0]
    if not xs:
        return {"x": np.zeros((0, 3)), "tri": np.zeros((0, 3), np.int64), "tri_part": np.zeros(0, np.int64)}
    return {"x": np.concatenate(xs), "tri": np.concatenate(tris), "tri_part": np.concatenate(tp)}


# ---------------------------------------------------------------- 형상 변경
def rib_x(mesh, alpha, depth=6.0, t_centers=(0.375, 0.625), w=0.05):
    """스팬(x) 방향 리브 비드: Y += α·depth·Σ exp(−((t − t_c)/w)²) (지그 선 사이 전 길이). 같은 노드(S = I)."""
    X = mesh["x0"].copy()
    _, t = _norm_coords(X)
    X[:, 1] += alpha * depth * sum(np.exp(-((t - c) / w) ** 2) for c in t_centers)
    return X


# ---------------------------------------------------------------- 참조 풀이
def model(mesh, x=None):
    return ss.model(mesh, x)


def jig_factor(mesh, J, x=None):
    m = dict(mesh) if x is None else dict(mesh, x0=x)
    return jig.factor(m, J, SOLVER)


def solve_jig(mesh, J, F, x=None):
    u, R = jig_factor(mesh, J, x).solve(F)
    return u, R


def case(nx=24, ny=12, gap=1.0, which=("shell_a", "shell_b", "brick"), n_groups=4, **kw):
    """기본 합성 사례: 메시·tie 묶음·J·Ω(전체)·F(= Ω∖J)·가중치·표면."""
    m = plate(nx=nx, ny=ny, **kw)
    groups = tie_groups(m, n_groups=n_groups)
    J = jig_of(groups)
    N = m["x0"].shape[0]
    omega = np.ones(N, bool)
    fit = omega.copy()
    fit[J] = False
    w = jig.node_weights(m)
    nb = neighbors(m, gap=gap, which=which)
    return {"mesh": m, "groups": groups, "J": J, "omega": omega, "fit": fit, "w": w, "parts": nb,
            "surf": surface(nb), "gap": gap}


# ---------------------------------------------------------------- rad (V-JIG-12·13)
def _i(*v):
    return "".join(f"{int(x):10d}" for x in v)


def _node_line(n, p):
    return f"{int(n):10d}{p[0]:20.10f}{p[1]:20.10f}{p[2]:20.10f}"


def write_rad_with_neighbors(path, mesh, *, gap=1.0, groups=None, x=None, node_base=100000, elem_base=100000):
    """대상 쉘 파트(sd.write_mesh_rad) + 인접 부품 6 파트 + tie 카드를 담은 starter.

    인접: shell(/SHELL, +Y 판 shell_a), sh3n(/SH3N, shell_b 를 삼각형으로), brick(/BRICK 2×2×1, −Y), tetra10(/TETRA10 여러 줄
    — 브릭 옆), bric20(/BRIC20 3줄), penta6(/PENTA6). tie = /GRNOD/NODE(tie 노드 ID) + /SURF/PART/EXT(인접 shell) +
    /INTER/TYPE2. 반환 {"path", "parts": {이름: part id}, "node_id": {이름: (P,)}, "x": {이름: (P,3)}, "elems": {이름: 연결 ID}}."""
    X = mesh["x0"] if x is None else x
    sd.write_mesh_rad(path, mesh, X)
    with open(path, encoding="utf-8") as fh:
        L = fh.read().splitlines()
    assert L[-1] == "/END"
    L = L[:-1]
    nbs = {p["name"]: p for p in neighbors(dict(mesh, x0=X), gap=gap)}
    lo, hi = X.min(axis=0), X.max(axis=0)
    span = hi - lo
    nid_next = [node_base]
    out_nodes, out_x, out_el = {}, {}, {}
    node_lines = ["/NODE"]

    def add_nodes(name, P):
        ids = np.arange(nid_next[0] + 1, nid_next[0] + 1 + P.shape[0], dtype=np.int64)
        nid_next[0] += P.shape[0]
        for n, p in zip(ids, P):
            node_lines.append(_node_line(n, p))
        out_nodes[name], out_x[name] = ids, np.asarray(P, float)
        return ids

    blocks = []
    eid = [elem_base]

    def nxt():
        eid[0] += 1
        return eid[0]

    def part_hdr(name, solid):
        pid = RAD_PARTS[name]
        prop = 9001 if solid else 9000
        return [f"/PART/{pid}", f"neighbor_{name}", _i(prop, sd.MID)]

    # shell (/SHELL) = shell_a
    ids = add_nodes("shell", nbs["shell_a"]["x"])
    Q = ids[nbs["shell_a"]["quad"]]
    out_el["shell"] = Q
    blocks += part_hdr("shell", False) + [f"/SHELL/{RAD_PARTS['shell']}"] + [_i(nxt(), *q) for q in Q]
    # sh3n = shell_b 삼각형
    ids = add_nodes("sh3n", nbs["shell_b"]["x"])
    Qb = ids[nbs["shell_b"]["quad"]]
    T = np.concatenate([Qb[:, [0, 1, 2]], Qb[:, [0, 2, 3]]])
    out_el["sh3n"] = T
    blocks += part_hdr("sh3n", False) + [f"/SH3N/{RAD_PARTS['sh3n']}"] + [_i(nxt(), *t) for t in T]
    # brick
    ids = add_nodes("brick", nbs["brick"]["x"])
    H = ids[nbs["brick"]["hex"]]
    out_el["brick"] = H
    blocks += part_hdr("brick", True) + [f"/BRICK/{RAD_PARTS['brick']}"] + [_i(nxt(), *h) for h in H]
    # tetra10: 정사면체 1개(코너 4 + 중간 6), −Y 쪽 (s 0.10~0.18, t 0.40~0.50)
    x0, z0 = lo[0] + 0.10 * span[0], lo[2] + 0.40 * span[2]
    a = 0.08 * span[0]
    C = np.array([[x0, -gap, z0], [x0 + a, -gap, z0], [x0, -gap, z0 + a], [x0, -gap - a, z0]])
    E6 = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
    P10 = np.concatenate([C, np.array([(C[i] + C[j]) / 2 for i, j in E6])])
    ids = add_nodes("tetra10", P10)
    out_el["tetra10"] = ids[None, :]
    e = nxt()
    blocks += part_hdr("tetra10", True) + [f"/TETRA10/{RAD_PARTS['tetra10']}", _i(e, *ids[:9]), _i(*ids[9:])]
    # bric20: 헥사 1개(코너 8 + 중간 12), −Y 쪽 (s 0.82~0.90, t 0.10~0.20)
    x0, z0 = lo[0] + 0.82 * span[0], lo[2] + 0.10 * span[2]
    bx, bz, hh = 0.08 * span[0], 0.10 * span[2], 8.0
    C = np.array([[x0, -gap - hh, z0], [x0 + bx, -gap - hh, z0], [x0 + bx, -gap - hh, z0 + bz], [x0, -gap - hh, z0 + bz],
                  [x0, -gap, z0], [x0 + bx, -gap, z0], [x0 + bx, -gap, z0 + bz], [x0, -gap, z0 + bz]])
    E12 = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 5), (2, 6), (3, 7), (4, 5), (5, 6), (6, 7), (7, 4)]
    P20 = np.concatenate([C, np.array([(C[i] + C[j]) / 2 for i, j in E12])])
    ids = add_nodes("bric20", P20)
    out_el["bric20"] = ids[None, :]
    e = nxt()
    blocks += part_hdr("bric20", True) + [f"/BRIC20/{RAD_PARTS['bric20']}", _i(e, *ids[:9]), _i(*ids[9:19]),
                                          _i(*ids[19:])]
    # penta6: 쐐기 1개, −Y 쪽 (s 0.10~0.18, t 0.75~0.85)
    x0, z0 = lo[0] + 0.10 * span[0], lo[2] + 0.75 * span[2]
    C = np.array([[x0, -gap - 6.0, z0], [x0 + a, -gap - 6.0, z0], [x0, -gap - 6.0, z0 + a],
                  [x0, -gap, z0], [x0 + a, -gap, z0], [x0, -gap, z0 + a]])
    ids = add_nodes("penta6", C)
    out_el["penta6"] = ids[None, :]
    blocks += part_hdr("penta6", True) + [f"/PENTA6/{RAD_PARTS['penta6']}", _i(nxt(), *ids)]
    # tie
    tie = []
    if groups is not None:
        tn = mesh["node_id"][jig_of(groups)]
        tie = ["/GRNOD/NODE/7001", "TIE-NODES"] + [_i(*tn[k:k + 10]) for k in range(0, tn.size, 10)]
        tie += ["/SURF/PART/EXT/7002", "TIE-SURF", _i(RAD_PARTS["shell"])]
        tie += ["/INTER/TYPE2/7003", "TIE-SHELL", _i(7001, 7002)]
    props = ["/PROP/SHELL/9000", "neighbor_shell", _i(24, 0), "", _i(5, 0) + f"{1.0:20.6f}",
             "/PROP/SOLID/9001", "neighbor_solid", _i(0)]
    L += node_lines + props + blocks + tie + ["/END"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return {"path": os.fspath(path), "parts": dict(RAD_PARTS), "node_id": out_nodes, "x": out_x, "elems": out_el,
            "target_part": PART_ID}
