"""가상 비드(화면 "추가 비드") — 평판 위 선분 + 단면 → 기존 노드 법선 모핑의 모드 무관 계산(계약 esl_virtual_bead.md §2~4,
D-0.25.0-VB-3·4·5·9).

numpy 만 — ``esl.doe``·``beadgraph``·``esl.mesh`` 를 import 하지 않고 파일·설정을 모른다(값은 인수). 호출 = ``esl.doe.bead_graph``
(derive·기저 — 분류 라벨·fixed·exclude 에서 마스크를 만들어 넘김) · ``esl.morph.core.basis_term``(hinge 항).

변형장(§4.1, 사면 각 고정형): 노드 i 의 변위 u_i(D) = s·n_i·[F_c(D − g_i) − F_c(0 − g_i)],
g_i = tanθ·Q_a(d_i − W_top/2), Q_a·F_c = 반경 a·c 둥글린 경사(r = 0 → max(0, t)), a = r·tan(θ/2)·(1 + cosθ)/2,
c = r·tan(θ/2)·tanθ. r = 0 이면 u = s·n·max(0, D − g), g = max(0, d − W_top/2)·tanθ — 깊이면 폭 W_top·사면 각 θ 유지,
입구 W_open(D) = W_top + 2D·cotθ.

STABLE INTERFACE (B1·F1·통합이 맞출 것)
  VB_RULES = 1;  REASONS(순서 고정);  WARNS;  INFOS;  HASH_KEYS;  hash_view(blk) -> dict | None
  ramp(t, c) -> ndarray;  q_round(t, a) -> ndarray;  edge_a(r, theta_deg) -> a;  edge_c(r, theta_deg) -> c
  hinge(g, c, v, v0) -> ndarray (노드별 스칼라 F_c(v − g) − F_c(v0 − g))
  resolve_line(p0, p1, length, angle_deg, frame_axes, plane) -> (p0', p1', t̂, L)
  plane_dist(p, plane) -> float
  footprint(Xp, line, w_top, theta_deg, d_max, end, r, margin) -> {d, move_mask, chk_mask, d_move, d_chk}
  host_check(elem_nodes, chk_elems, masks) -> [codes]
  resolution(h, w_top, theta_deg, d_max, min_wall_elems) -> {codes, warns[{code, …}], n_wall, n_top, run}
  field(d, normals, side, w_top, theta_deg, r, idx=None) -> {idx, vec, g, c}
  diag(X, conn, et, field, d_max) -> {stretch_max, n_fp, n_elems_fp}
  node_normals(X, conn, et, elems, ref) -> (N, 3);  edge_median(X, conn, et, elems) -> h
"""
from __future__ import annotations

import math

import numpy as np

VB_RULES = 1                      # 수치 규칙 판(basis.json vb_rules — 바뀌면 +1, 재사용 조건)
# §3.2 거부 사유(순서 고정 — 그 가상 비드는 변수 없음). 422 = VB_INPUT_INVALID·VB_MAX_COUNT(형식 오류만)
REASONS = ("VB_SCOPE", "VB_INPUT_INVALID", "VB_MAX_COUNT", "VB_NOT_ON_PLATE", "VB_OVER_BEAD", "VB_OVER_ISLAND",
           "VB_OVER_HOLE", "VB_PLATE_EDGE", "VB_FIXED", "VB_OVER_VBEAD", "VB_EXCLUDED", "VB_MESH_COARSE")
HOST_REASONS = ("VB_NOT_ON_PLATE", "VB_OVER_BEAD", "VB_OVER_ISLAND", "VB_OVER_HOLE", "VB_PLATE_EDGE", "VB_FIXED",
                "VB_OVER_VBEAD", "VB_EXCLUDED")       # host_check 가 내는 것(이 순서)
WARNS = ("VB_WALL_COARSE", "VB_TOP_NARROW")           # §3.3 경고(행은 만듦)
INFOS = ("VB_EDGE_SMEAR", "VB_BAND_OVERLAP", "VB_PREVIEW_SKIPPED", "VB_VERIFY_HINT")
ENDS = ("round", "square")
SIDES = ("+", "-")
_LEN_EPS = 1e-6
HASH_KEYS = ("min_wall_elems", "margin_mm", "theta_default_deg", "theta_range_deg", "warp_max_deg")   # §7.1 해시 안


def hash_view(blk: dict | None) -> dict | None:
    """선택 cfg 해시에 더할 값(§7.2 — 선택에 virtual_beads 가 있을 때만 호출자가 더함): 해시 안 키 + VB_RULES."""
    if not isinstance(blk, dict):
        return None
    out = {k: (sorted(float(x) for x in blk[k]) if k == "theta_range_deg" else float(blk[k]))
           for k in HASH_KEYS if k in blk}
    out["vb_rules"] = VB_RULES
    return out


# ---------------------------------------------------------------- 단면 함수
def ramp(t, c) -> np.ndarray:
    """F_c(t) = 0 (t ≤ −c) · (t + c)²/(4c) (|t| < c) · t (t ≥ c); c = 0 → max(0, t). C¹, 단조 증가."""
    t = np.asarray(t, dtype=np.float64)
    c = float(c)
    if c <= 0.0:
        return np.maximum(t, 0.0)
    return np.where(t <= -c, 0.0, np.where(t >= c, t, (t + c) ** 2 / (4.0 * c)))


def q_round(t, a) -> np.ndarray:
    """Q_a(t) — 깊이면 가장자리 모서리 둥글림(``ramp`` 와 같은 꼴, 반경 몫 a)."""
    return ramp(t, a)


def edge_a(r: float, theta_deg: float) -> float:
    """a = r·tan(θ/2)·(1 + cosθ)/2 (r = 0 → 0)."""
    th = math.radians(float(theta_deg))
    return float(r) * math.tan(th / 2.0) * (1.0 + math.cos(th)) / 2.0 if float(r) > 0.0 else 0.0


def edge_c(r: float, theta_deg: float) -> float:
    """c = r·tan(θ/2)·tanθ (r = 0 → 0)."""
    th = math.radians(float(theta_deg))
    return float(r) * math.tan(th / 2.0) * math.tan(th) if float(r) > 0.0 else 0.0


def hinge(g, c, v, v0=0.0) -> np.ndarray:
    """노드별 스칼라 크기 F_c(v − g) − F_c(v0 − g) — ``core.basis_term`` hinge 항의 원본(브라우저 ``basis.ts`` 같은 식)."""
    g = np.asarray(g, dtype=np.float64)
    return ramp(float(v) - g, c) - ramp(float(v0) - g, c)


# ---------------------------------------------------------------- 기하
def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-15:
        raise ValueError("VB_INPUT_INVALID: zero vector")
    return v / n


def plane_dist(p, plane) -> float:
    """점 p 와 평면 (p_h, n_h) 의 거리."""
    ph, nh = plane
    return abs(float(np.dot(np.asarray(p, float) - np.asarray(ph, float), _unit(nh))))


def _proj(p, plane) -> np.ndarray:
    ph, nh = plane
    nh = _unit(nh)
    p = np.asarray(p, dtype=np.float64)
    return p - float(np.dot(p - np.asarray(ph, float), nh)) * nh


def resolve_line(p0, p1, length, angle_deg, frame_axes, plane):
    """§2.2: (a) 두 점 또는 (b) 시작점 + 길이 + 각도(ESL frame 판 평면 +ξ 기준 +η 쪽) → 판 평면 사영 (p0', p1', t̂, L).
    frame_axes = (e_xi, e_eta), plane = (p_h, n_h). 길이 < 1e-6 → ValueError("VB_INPUT_INVALID")."""
    nh = _unit(plane[1])
    q0 = _proj(p0, plane)
    if p1 is not None:
        q1 = _proj(p1, plane)
    else:
        e_xi, e_eta = (np.asarray(a, dtype=np.float64) for a in frame_axes)
        ex = e_xi - float(np.dot(e_xi, nh)) * nh
        ex = _unit(ex)
        ey = np.cross(nh, ex)
        if float(np.dot(ey, e_eta)) < 0.0:                 # frame 손잡이 보존
            ey = -ey
        al = math.radians(float(angle_deg))
        t = math.cos(al) * ex + math.sin(al) * ey
        q1 = q0 + float(length) * t
    L = float(np.linalg.norm(q1 - q0))
    if not L >= _LEN_EPS:
        raise ValueError("VB_INPUT_INVALID: zero length")
    return q0, q1, (q1 - q0) / L, L


def frame_in_plane(frame_axes, n_h):
    """입력 칸 ξ·η ↔ 모델 좌표(derive ``vb_frame``): (ê_ξ', ê_η') — ``resolve_line`` (b) 와 같은 축."""
    nh = _unit(n_h)
    e_xi, e_eta = (np.asarray(a, dtype=np.float64) for a in frame_axes)
    ex = _unit(e_xi - float(np.dot(e_xi, nh)) * nh)
    ey = np.cross(nh, ex)
    if float(np.dot(ey, e_eta)) < 0.0:
        ey = -ey
    return ex, ey


def line_dist(Xp, line, end: str = "round") -> np.ndarray:
    """판 평면 사영 거리 d(x) (§3.1): round = 선분까지 거리, square = max(|y|, max(0, −s, s − L))."""
    q0, _q1, t, L = line[:4]
    nh = _unit(line[4]) if len(line) > 4 else None
    R = np.asarray(Xp, dtype=np.float64) - q0
    s = R @ t
    if nh is not None:
        R = R - (R @ nh)[:, None] * nh[None, :]            # 판 평면 사영
    perp = R - s[:, None] * t[None, :]
    y = np.linalg.norm(perp, axis=1)
    over = np.maximum(np.maximum(0.0, -s), s - L)
    if end == "square":
        return np.maximum(y, over)
    return np.sqrt(y * y + over * over)


def footprint(Xp, line, w_top, theta_deg, d_max, end="round", r=0.0, margin=0.0) -> dict:
    """§3.1: d(노드), 이동 띠 d_move = W_top/2 + d_max·cotθ + a_r(a_r = r·tan(θ/2) — 입구 둥글림 몫), 검사 띠 d_chk = d_move + margin.
    line = (p0', p1', t̂, L[, n_h]). 반환 {d, move_mask(d < d_move), chk_mask(d < d_chk), d_move, d_chk}."""
    th = math.radians(float(theta_deg))
    a_r = float(r) * math.tan(th / 2.0) if float(r) > 0.0 else 0.0
    d_move = float(w_top) / 2.0 + float(d_max) / math.tan(th) + a_r
    d_chk = d_move + float(margin)
    d = line_dist(Xp, line, end)
    return {"d": d, "move_mask": d < d_move, "chk_mask": d < d_chk, "d_move": d_move, "d_chk": d_chk}


def chk_elems(conn, et, node_mask) -> np.ndarray:
    """E_chk(요소 bool) = 노드 하나라도 mask 인 요소."""
    C = np.asarray(conn, dtype=np.int64)
    q = np.asarray(et).astype(int) == 4
    m = np.asarray(node_mask, bool)
    out = m[C[:, 0]] | m[C[:, 1]] | m[C[:, 2]]
    out[q] |= m[C[q, 3]]
    return out


def host_check(elem_nodes, chk_elems_mask, masks: dict) -> list[str]:
    """§3.2 놓을 곳 검사 → 사유 코드(HOST_REASONS 순서, 전부). elem_nodes = (m, 4) 노드(삼각형 4번째 = 3번째 또는 −1),
    chk_elems_mask = E_chk(요소 bool). masks{host, bead, island, exclude, other_vb (요소 bool), hole_nodes, edge_nodes,
    fixed_nodes (노드 bool)}. VB_NOT_ON_PLATE = H 아닌 요소 중 더 구체적인 사유(비드·섬·제외)로 설명되지 않는 것(벽·다른 바닥)."""
    E = np.asarray(chk_elems_mask, bool)
    C = np.asarray(elem_nodes, dtype=np.int64)
    m = E.size

    def em(k):
        v = masks.get(k)
        return np.zeros(m, bool) if v is None else np.asarray(v, bool)
    host, bead, isl, exc, ovb = em("host"), em("bead"), em("island"), em("exclude"), em("other_vb")
    nodes = C[E]
    nodes = np.unique(nodes[nodes >= 0]) if nodes.size else np.zeros(0, np.int64)

    def nm(k):
        v = masks.get(k)
        return bool(v is not None and nodes.size and np.asarray(v, bool)[nodes].any())
    out = []
    if (E & ~host & ~bead & ~isl & ~exc).any():
        out.append("VB_NOT_ON_PLATE")
    if (E & bead).any():
        out.append("VB_OVER_BEAD")
    if (E & isl).any():
        out.append("VB_OVER_ISLAND")
    if nm("hole_nodes"):
        out.append("VB_OVER_HOLE")
    if nm("edge_nodes"):
        out.append("VB_PLATE_EDGE")
    if nm("fixed_nodes"):
        out.append("VB_FIXED")
    if (E & ovb).any():
        out.append("VB_OVER_VBEAD")
    if (E & exc).any():
        out.append("VB_EXCLUDED")
    return out


def resolution(h, w_top, theta_deg, d_max, min_wall_elems) -> dict:
    """§3.3: run = d_max·cotθ, n_wall = run/h, n_top = W_top/h. run < h ∨ W_top < h → codes [VB_MESH_COARSE](거부),
    h ≤ run < min_wall_elems·h → warns VB_WALL_COARSE{n_wall}, h ≤ W_top < 2h → VB_TOP_NARROW{n_top}."""
    h = float(h)
    run = float(d_max) / math.tan(math.radians(float(theta_deg)))
    nw = run / h if h > 0 else math.inf
    nt = float(w_top) / h if h > 0 else math.inf
    codes, warns = [], []
    if run < h or float(w_top) < h:
        codes.append("VB_MESH_COARSE")
    else:
        if run < float(min_wall_elems) * h:
            warns.append({"code": "VB_WALL_COARSE", "n_wall": round(nw, 2)})
        if float(w_top) < 2.0 * h:
            warns.append({"code": "VB_TOP_NARROW", "n_top": round(nt, 2)})
    return {"codes": codes, "warns": warns, "n_wall": nw, "n_top": nt, "run": run}


def field(d, normals, side, w_top, theta_deg, r=0.0, idx=None) -> dict:
    """§4.1 hinge 기저: d·normals = 발자국 노드(idx 순서)의 거리·단위 법선, side ±1 → {idx, vec = s·n(단위), g, c}.
    g = tanθ·Q_a(d − W_top/2) (D 와 무관한 노드 상수), c = 입구 둥글림 몫."""
    d = np.asarray(d, dtype=np.float64)
    nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    s = float(side)
    if s not in (1.0, -1.0):
        raise ValueError("side 는 ±1")
    th = math.radians(float(theta_deg))
    a = edge_a(r, theta_deg)
    c = edge_c(r, theta_deg)
    g = math.tan(th) * q_round(d - float(w_top) / 2.0, a)
    ix = np.arange(d.size, dtype=np.int64) if idx is None else np.asarray(idx, dtype=np.int64)
    return {"idx": ix, "vec": s * nrm, "g": np.asarray(g, dtype=np.float64), "c": float(c)}


def displacement(fd: dict, D: float, D0: float = 0.0) -> np.ndarray:
    """발자국 노드 변위 (n_fp, 3) = vec·hinge(g, c, D, D0)."""
    return fd["vec"] * hinge(fd["g"], fd["c"], D, D0)[:, None]


# ---------------------------------------------------------------- 메시 보조(순수)
def _tri_area(P0, P1, P2) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(P1 - P0, P2 - P0), axis=1)


def elem_areas(X, conn, et) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    C = np.asarray(conn, dtype=np.int64)
    q = np.asarray(et).astype(int) == 4
    a = _tri_area(X[C[:, 0]], X[C[:, 1]], X[C[:, 2]])
    if q.any():
        Cq = C[q]
        a[q] += _tri_area(X[Cq[:, 0]], X[Cq[:, 2]], X[Cq[:, 3]])
    return a


def node_normals(X, conn, et, elems, ref) -> np.ndarray:
    """요소(elems — index 또는 bool)만으로 만든 노드 법선(면적 가중, ref 쪽 부호), 쓰이지 않은 노드 = ref."""
    X = np.asarray(X, dtype=np.float64)
    C = np.asarray(conn, dtype=np.int64)
    et = np.asarray(et).astype(int)
    E = np.asarray(elems)
    E = np.flatnonzero(E) if E.dtype == bool else E.astype(np.int64)
    ref = _unit(ref)
    acc = np.zeros_like(X)
    Ce = C[E]
    q = et[E] == 4
    P0, P1, P2 = X[Ce[:, 0]], X[Ce[:, 1]], X[Ce[:, 2]]
    nv = np.cross(P1 - P0, P2 - P0)                        # 2·면적·법선
    if q.any():
        P3 = X[np.where(q, Ce[:, 3], Ce[:, 2])]
        nv = np.where(q[:, None], np.cross(P2 - P0, P3 - P1), nv)
    sg = np.where(nv @ ref < 0.0, -1.0, 1.0)
    nv = nv * sg[:, None]
    for k in range(3):
        np.add.at(acc, Ce[:, k], nv)
    if q.any():
        np.add.at(acc, Ce[q, 3], nv[q])
    ln = np.linalg.norm(acc, axis=1)
    out = np.tile(ref, (X.shape[0], 1))
    ok = ln > 1e-15
    out[ok] = acc[ok] / ln[ok, None]
    return out


def edge_median(X, conn, et, elems) -> float:
    """요소(elems) 변 길이 중앙값(h — §3.3). 요소 없음 = nan."""
    X = np.asarray(X, dtype=np.float64)
    C = np.asarray(conn, dtype=np.int64)
    et = np.asarray(et).astype(int)
    E = np.asarray(elems)
    E = np.flatnonzero(E) if E.dtype == bool else E.astype(np.int64)
    if E.size == 0:
        return float("nan")
    Ce = C[E]
    q = et[E] == 4
    L = [np.linalg.norm(X[Ce[:, 1]] - X[Ce[:, 0]], axis=1), np.linalg.norm(X[Ce[:, 2]] - X[Ce[:, 1]], axis=1)]
    last = np.where(q, Ce[:, 3], Ce[:, 2])
    L.append(np.linalg.norm(X[last] - X[Ce[:, 2]], axis=1)[q])
    L.append(np.linalg.norm(X[Ce[:, 0]] - X[last], axis=1))
    return float(np.median(np.concatenate(L)))


def diag(X, conn, et, fd: dict, d_max: float) -> dict:
    """진단(§3.3 정보): D_max 에서 발자국 요소(발자국 노드를 가진 요소) 넓이 비 최대(stretch_max ≈ 1/cosθ_eff)·n_fp·n_elems_fp."""
    X = np.asarray(X, dtype=np.float64)
    idx = np.asarray(fd["idx"], dtype=np.int64)
    mk = np.zeros(X.shape[0], bool)
    mk[idx] = True
    E = np.flatnonzero(chk_elems(conn, et, mk))
    if E.size == 0:
        return {"stretch_max": 1.0, "n_fp": int(idx.size), "n_elems_fp": 0}
    x = X.copy()
    x[idx] += displacement(fd, d_max)
    C = np.asarray(conn)[E]
    t = np.asarray(et)[E]
    a0 = elem_areas(X, C, t)
    a1 = elem_areas(x, C, t)
    with np.errstate(divide="ignore", invalid="ignore"):
        rr = np.where(a0 > 0, a1 / a0, 1.0)
    return {"stretch_max": round(float(np.max(rr)), 4), "n_fp": int(idx.size), "n_elems_fp": int(E.size)}
