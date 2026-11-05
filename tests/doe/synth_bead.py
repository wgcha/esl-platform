"""비드 직접 선택 시험용 합성 메시(계약 esl_bead_select.md §16, 순수 numpy, 시험 중 생성, 정답 표지 포함).

600×400 판(XY 평면, 상판 z = 0, 비드는 −z 로 들어감 = concave), 구조 격자(4각 위주 + 판 구석 3각 일부):
- **경로형 2단 비드 b1**: x 100..500, 중심선 꺾인 3 구간(y 170 → 200, 꺾임 x 230·370), 개구 폭(세로) 50 → 70 선형 가변,
  단1 깊이 22, 단2 깊이 14(x 300..400 구간만 — 나란한 단, 경사로 10 mm), 사면 각 ≈ 60°(사면 2줄), 끝단 사면 포함.
  격자가 비드 형상을 따라가므로(행 위치가 열마다 다름) 요소 표지가 정확하다. 필렛·구멍은 생략(정답 표지 단순화).
- **1단 원형 비드 b2**: 중심 (560, 345), 깊이 6, 개구 지름 40(정사각 블록 → 원 사상), 사면 1줄.
- **고정 노드 고리 4개**(RBE2 대용 노드 집합, 반경 ``fixed_r``): 하나는 b1 아래 경계에서 약 18 mm.

선택: ``open_end``(b1 이 판 오른쪽 가장자리까지 → 열린 경계), ``wavy``(상판 물결 → 사면 BFS 새기),
``h``(요소 크기), ``scale="big"``(약 22만 노드 — 성능 시험만).

반환 dict: mesh(MESH_KEYS + elem_mid), label(요소별 'plate'|'b1t1'|'b1t2'|'b1s'|'b2t1'|'b2s'), fixed_ids(노드 ID), fixed_groups,
truth{b1: {D: {1: 22, 2: 14}, W_cols: 열별 수직 개구 폭 × cos(경로 각)}, b2: {D: {1: 6}, W: 40}}, node_ij, …
"""
from __future__ import annotations

import math

import numpy as np

TAN60 = math.tan(math.radians(60.0))
E_STEEL, NU = 205000.0, 0.3


def _cols(Lx, h, specials):
    xs = list(np.arange(0.0, Lx + 1e-9, h))
    sp = sorted(set(round(s, 6) for s in specials if 0 < s < Lx))
    keep = [x for x in xs if all(abs(x - s) > 0.3 * h for s in sp) or x in (0.0, Lx)]
    return np.array(sorted(set(keep) | set(sp)))


def generate(h: float = 5.0, *, open_end: bool = False, wavy: bool = False, scale: str = "small",
             fixed_r: float = 6.0, d1: float = 22.0, d2: float = 14.0, tria: bool = True, features: bool | tuple = False) -> dict:
    if scale == "big":
        h = 1.0
    Lx, Ly = 600.0, 400.0
    xa, xb = 100.0, (Lx if open_end else 500.0)
    r1 = d1 / TAN60
    kinks = (230.0, 370.0)
    ramp = (290.0, 300.0, 400.0, 410.0)
    specials = [xa, xa + r1, *kinks, *ramp] + ([] if open_end else [xb - r1, xb])
    xs = _cols(Lx, h, specials)

    def yc(x):
        if x <= kinks[0]:
            return 170.0
        if x >= kinks[1]:
            return 200.0
        return 170.0 + 30.0 * (x - kinks[0]) / (kinks[1] - kinks[0])

    def slope_ang(x):
        return math.atan(30.0 / (kinks[1] - kinks[0])) if kinks[0] < x < kinks[1] else 0.0

    def wv(x):
        t = min(max((x - xa) / (500.0 - xa), 0.0), 1.0)
        return 50.0 + 20.0 * t

    def depth(x):
        a0, a1, b0, b1 = ramp
        if x <= a0 or x >= b1:
            return d1
        if a1 <= x <= b0:
            return d2
        if x < a1:
            return d1 + (d2 - d1) * (x - a0) / (a1 - a0)
        return d2 + (d1 - d2) * (x - b0) / (b1 - b0)

    def along(x):
        if x <= xa:
            return 0.0
        if x < xa + r1:
            return (x - xa) / r1
        if open_end or x <= xb - r1:
            return 1.0
        if x < xb:
            return (xb - x) / r1
        return 0.0

    band_lo, band_hi = 100.0, 290.0
    n_lo = max(2, int(round(45.0 / h)))
    n_s, n_f = 2, max(2, int(round(40.0 / h)))
    n_hi = max(2, int(round(75.0 / h)))
    below = np.arange(0.0, band_lo, h)
    above = np.arange(band_hi, Ly + 1e-9, h)
    above = above[above > band_hi + 1e-9]
    if above.size == 0 or above[-1] < Ly - 1e-9:
        above = np.append(above, Ly)
    rows_c = []                       # 행별 cross 매개변수(0 = 상판, 1 = 바닥)
    for _ in below:
        rows_c.append(0.0)
    rows_c += [0.0] * n_lo            # band_lo .. open_lo(앞)
    rows_c += [0.0] + [k / n_s for k in range(1, n_s)]      # open_lo, 사면 내부
    rows_c += [1.0] * (n_f + 1)                            # floor_lo .. floor_hi
    rows_c += [1.0 - k / n_s for k in range(1, n_s)] + [0.0]  # 사면 내부, open_hi
    rows_c += [0.0] * (n_hi - 1)
    rows_c += [0.0] * above.size
    nrow = len(rows_c)

    def col_rows(x):
        w = wv(x)
        D = depth(x) if xa <= x <= xb else d1
        r = D / TAN60
        o_lo, o_hi = yc(x) - w / 2.0, yc(x) + w / 2.0
        f_lo, f_hi = o_lo + r, o_hi - r
        ys = list(below)
        ys += list(np.linspace(band_lo, o_lo, n_lo + 1)[:-1])
        ys += list(np.linspace(o_lo, f_lo, n_s + 1)[:-1])
        ys += list(np.linspace(f_lo, f_hi, n_f + 1))
        ys += list(np.linspace(f_hi, o_hi, n_s + 1)[1:])
        ys += list(np.linspace(o_hi, band_hi, n_hi + 1)[1:-1])
        ys += [band_hi] + list(above)
        return np.array(ys[:nrow]) if len(ys) >= nrow else np.array(ys)

    rows0 = col_rows(xs[0])
    nrow = rows0.size
    rows_c = rows_c[:nrow]
    rows_c = np.array(rows_c)
    nx, ny = xs.size, nrow
    X = np.zeros((nx, ny, 3))
    zcode = np.zeros((nx, ny))                    # 깊이(+)
    full = np.zeros((nx, ny), bool)               # 바닥 노드(c = 1, a = 1)
    Dn = np.zeros((nx, ny))
    for i, x in enumerate(xs):
        ys = col_rows(x)
        a = along(x)
        D = depth(x) if xa <= x <= xb else d1
        for j in range(ny):
            c = rows_c[j]
            dep = D * min(c, a) if xa <= x <= xb else 0.0
            X[i, j] = (x, ys[j], -dep)
            zcode[i, j] = dep
            full[i, j] = c == 1.0 and a == 1.0 and xa <= x <= xb
            Dn[i, j] = D
    # 원형 비드 b2 (정사각 블록 → 원)
    cx, cy, R0, B, D2 = 560.0, 345.0, 20.0, 25.0, 6.0
    rmap = [(0.0, 0.0), (5.0, 5.5), (10.0, 11.0), (15.0, 20.0 - D2 / TAN60), (20.0, 20.0)]
    b2_floor = np.zeros((nx, ny), bool)
    b2_rho = np.full((nx, ny), np.inf)
    for i, x in enumerate(xs):
        for j in range(ny):
            px, py = X[i, j, 0], X[i, j, 1]
            dx, dy = px - cx, py - cy
            rho = max(abs(dx), abs(dy))
            if rho > B + 1e-9:
                continue
            b2_rho[i, j] = rho
            d = math.hypot(dx, dy)
            if d < 1e-12:                         # 중심 노드: 사상 없음(제자리) — 바닥 깊이만(z = −D)
                X[i, j, 2] = -D2
                b2_floor[i, j] = True
                continue
            u = np.array([dx, dy]) / d
            if rho <= 20.0 + 1e-9:
                r = np.interp(rho, [p[0] for p in rmap], [p[1] for p in rmap])
                q = u * r
            else:
                t = (rho - 20.0) / (B - 20.0)
                q = (1 - t) * u * (20.0 + (rho - 20.0)) + t * np.array([dx, dy])
            X[i, j, 0], X[i, j, 1] = cx + q[0], cy + q[1]
            if rho <= 15.0 + 1e-9:
                X[i, j, 2] = -D2
                b2_floor[i, j] = True
    if wavy:
        plate_node = (zcode == 0) & ~np.isfinite(b2_rho)
        X[..., 2] += np.where(plate_node, 8.0 * np.sin(2 * np.pi * X[..., 0] / 30.0), 0.0)
    nid = np.arange(nx * ny).reshape(nx, ny)
    conn, et, lab = [], [], []
    eij: dict = {}                                 # (i, j) → 4각 요소 번호(features 용 — 출력 불변)
    for i in range(nx - 1):
        for j in range(ny - 1):
            a_, b_, c_, d_ = nid[i, j], nid[i + 1, j], nid[i + 1, j + 1], nid[i, j + 1]
            ij = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            zz = [zcode[p] for p in ij]
            r2 = [b2_rho[p] for p in ij]
            if all(np.isfinite(r) for r in r2) and max(r2) <= 20.0 + 1e-9:
                L = "b2t1" if max(r2) <= 15.0 + 1e-9 else "b2s"
            elif all(z == 0 for z in zz):
                L = "plate"
            elif all(full[p] for p in ij) and all(Dn[p] == d1 for p in ij):
                L = "b1t1"
            elif all(full[p] for p in ij) and all(Dn[p] == d2 for p in ij):
                L = "b1t2"
            else:
                L = "b1s"
            if tria and L == "plate" and X[i, j, 0] < 40.0 and X[i, j, 1] < 40.0:
                conn += [[a_, b_, c_, -1], [a_, c_, d_, -1]]
                et += [3, 3]
                lab += [L, L]
            else:
                eij[(i, j)] = len(conn)
                conn.append([a_, b_, c_, d_])
                et.append(4)
                lab.append(L)
    Xf = X.reshape(-1, 3)
    feat = None
    if isinstance(features, tuple):                # V-SR-15 성능: (섬 수, 구멍 수) 격자 배치
        Xf, conn, et, lab, feat = _many_features(Xf.copy(), conn, et, lab, eij, rows_c, *features)
    elif features:                                 # v0.16.1 비드 바닥 안 형상(esl_select_relax.md §11)
        Xf, conn, et, lab, feat = _add_features(Xf.copy(), conn, et, lab, eij, rows_c, xs, h)
    conn = np.array(conn, np.int64)
    et = np.array(et, np.int8)
    ne = conn.shape[0]
    q = et == 4
    elem_id = np.zeros(ne, np.int64)
    elem_id[q] = 1 + np.arange(int(q.sum()))
    elem_id[~q] = 900001 + np.arange(int((~q).sum()))
    mesh = {"node_id": 1 + np.arange(Xf.shape[0], dtype=np.int64), "x0": Xf, "elem_id": elem_id, "elem_type": et,
            "conn": conn, "elem_pid": np.full(ne, 10, np.int64), "elem_mid": np.full(ne, 1, np.int64),
            "thickness": np.full(ne, 1.5), "E": np.full(ne, E_STEEL), "nu": np.full(ne, NU)}
    # 고정 노드 고리
    ylo180 = yc(180.0) - wv(180.0) / 2.0
    centers = [(180.0, ylo180 - 18.0 - fixed_r), (50.0, 60.0), (550.0, 60.0), (50.0, 350.0)]
    groups = []
    for (fx, fy) in centers:
        d = np.hypot(Xf[:, 0] - fx, Xf[:, 1] - fy)
        groups.append(mesh["node_id"][(d <= fixed_r) & (np.abs(Xf[:, 2]) < 1e-9)])
    if feat is not None:                            # 체결 구멍 둘레 고정 노드 고리
        groups.append(mesh["node_id"][feat["fastener_rim"]])
        nid = feat["node_map"][nid]
    cols_in = [x for x in xs if xa + r1 + 1 < x < (xb - r1 - 1)]
    W_cols = np.array([wv(x) * math.cos(slope_ang(x)) for x in cols_in])
    extra = {} if feat is None else {"islands": feat["islands"], "hole_rims": feat["hole_rims"],
                                     "fastener_rim": feat["fastener_rim"], "feature_kinds": feat["kinds"]}
    return {**extra, "mesh": mesh, "label": np.array(lab), "fixed_ids": np.concatenate(groups), "fixed_groups": groups,
            "fixed_centers": centers, "xs": xs, "nx": nx, "ny": ny, "h": h, "rows_c": rows_c,
            "node_ij": nid, "zcode": zcode, "depth_fn": depth, "along_fn": along, "yc": yc, "wv": wv,
            "truth": {"b1": {"D": {1: d1, 2: d2}, "W_cols": W_cols}, "b2": {"D": {1: 6.0}, "W": 2 * R0}},
            "xa": xa, "xb": xb, "kinks": kinks, "ramp": ramp, "open_end": open_end}


def _add_features(X, conn, et, lab, eij, rows_c, xs, h):
    """b1 단1 바닥(평면 구간, 구조 격자)에 (1) 관통 구멍(2×2 요소 제거 ≈ Ø10), (2) 딤플 3개(3×3 블록 가운데 4노드 ∓3 mm —
    둘은 아래(깊어짐), 하나는 위로 볼록), (3) 버링(2×2 구멍 + 둘레에서 아래로 4 mm 칼라), (4) 체결 구멍(2×2 구멍, 둘레 8노드 =
    고정 노드). 섬 표지 'b1i'(딤플 9요소·칼라 8요소). 쓰지 않는 노드 제거·재번호(node_map: 옛 → 새, 지운 노드 −1)."""
    ny = rows_c.size
    floor_rows = [j for j in range(ny - 1) if rows_c[j] == 1.0 and rows_c[j + 1] == 1.0]
    j0, nf = floor_rows[0], len(floor_rows)
    jm = j0 + nf // 2
    cols = sorted({i for (i, j) in eij if all(lab[eij.get((i, jj), -1)] == "b1t1" if (i, jj) in eij else False
                                             for jj in floor_rows)})
    run = [cols[0]]
    for c in cols[1:]:                           # 첫 연속 구간(평면 단1 바닥)
        if c != run[-1] + 1:
            break
        run.append(c)
    plan = [("hole", 2), ("dimple", 3), ("dimple", 3), ("dimple_up", 3), ("burr", 2), ("fastener", 2)]
    need = sum(w for _k, w in plan)
    gap = 2 if len(run) - 2 >= need + 2 * len(plan) else 1
    assert len(run) - 2 >= need + gap * (len(plan) - 1), (len(run), need)
    i = run[1]
    n0 = X.shape[0]
    node = lambda ii, jj: ii * ny + jj           # noqa: E731
    dele: set = set()
    new_nodes: list = []
    collar: list = []
    islands, hole_rims, kinds = [], [], []
    fast_rim = None
    for kind, w in plan:
        rows = list(range(jm - 1, jm - 1 + w)) if w == 3 else list(range(jm - 1, jm + 1))
        blk = [eij[(ii, jj)] for ii in range(i, i + w) for jj in rows]
        rim = sorted({node(ii, jj) for ii in range(i, i + w + 1) for jj in range(rows[0], rows[-1] + 2)
                      if ii in (i, i + w) or jj in (rows[0], rows[-1] + 1)})
        if kind.startswith("dimple"):
            inner = [node(ii, jj) for ii in range(i + 1, i + w) for jj in range(rows[0] + 1, rows[-1] + 1)]
            X[inner, 2] += 3.0 if kind == "dimple_up" else -3.0
            for e in blk:
                lab[e] = "b1i"
            islands.append({"kind": kind, "elems": blk, "rim": rim, "interior": inner})
        else:
            dele |= set(blk)
            ring = [node(i, rows[0]), node(i + 1, rows[0]), node(i + 2, rows[0]), node(i + 2, rows[0] + 1),
                    node(i + 2, rows[0] + 2), node(i + 1, rows[0] + 2), node(i, rows[0] + 2), node(i, rows[0] + 1)]
            if kind == "burr":
                base = n0 + len(new_nodes)
                for v in ring:
                    new_nodes.append(X[v] + np.array([0.0, 0.0, -4.0]))
                ce = []
                for k in range(8):
                    a_, b_ = ring[k], ring[(k + 1) % 8]
                    ce.append([a_, b_, base + (k + 1) % 8, base + k])
                collar += ce
                islands.append({"kind": "burr", "elems": ce, "rim": sorted(ring),
                                "interior": list(range(base, base + 8))})
            else:
                hole_rims.append(ring)
                if kind == "fastener":
                    fast_rim = ring
        kinds.append(kind)
        i += w + gap
    keep = [k for k in range(len(conn)) if k not in dele]
    old2new_e = {k: n for n, k in enumerate(keep)}
    conn2 = [conn[k] for k in keep]
    et2 = [et[k] for k in keep]
    lab2 = [lab[k] for k in keep]
    c_start = len(conn2)
    for q in collar:
        conn2.append(q)
        et2.append(4)
        lab2.append("b1i")
    if new_nodes:
        X = np.vstack([X, np.asarray(new_nodes)])
    used = np.zeros(X.shape[0], bool)
    for q in conn2:
        used[[v for v in q if v >= 0]] = True
    node_map = np.full(X.shape[0], -1, np.int64)
    node_map[used] = np.arange(int(used.sum()))
    conn2 = [[int(node_map[v]) if v >= 0 else -1 for v in q] for q in conn2]
    ci = c_start
    out_isl = []
    for isl in islands:
        if isl["kind"] == "burr":
            el = list(range(ci, ci + 8))
            ci += 8
        else:
            el = [old2new_e[e] for e in isl["elems"]]
        out_isl.append({"kind": isl["kind"], "elems": np.asarray(el, np.int64),
                        "rim": node_map[np.asarray(isl["rim"])], "interior": node_map[np.asarray(isl["interior"])]})
    feat = {"islands": out_isl, "hole_rims": [node_map[np.asarray(r)] for r in hole_rims],
            "fastener_rim": node_map[np.asarray(fast_rim)], "kinds": kinds, "node_map": node_map[:n0]}
    return X[used], conn2, et2, lab2, feat


def _many_features(X, conn, et, lab, eij, rows_c, n_isl, n_hole):
    """V-SR-15: b1 단1 바닥 첫 연속 구간에 2×2 섬(가운데 노드 −1 mm) n_isl 개 + 1요소 구멍 n_hole 개를 3칸 간격 격자로."""
    ny = rows_c.size
    floor_rows = [j for j in range(ny - 1) if rows_c[j] == 1.0 and rows_c[j + 1] == 1.0]
    cols = sorted({i for (i, j) in eij if all((i, jj) in eij and lab[eij[(i, jj)]] == "b1t1" for jj in floor_rows)})
    run = [cols[0]]
    for c in cols[1:]:
        if c != run[-1] + 1:
            break
        run.append(c)
    slots = [(i, j) for j in range(floor_rows[0] + 1, floor_rows[-1] - 1, 3) for i in range(run[0] + 1, run[-1] - 1, 3)]
    assert len(slots) >= n_isl + n_hole, (len(slots), n_isl, n_hole)
    dele, islands = set(), []
    for k, (i, j) in enumerate(slots[:n_isl + n_hole]):
        if k % 5 < 2 and len(islands) < n_isl or k - len(islands) >= n_hole:
            v = (i + 1) * ny + (j + 1)
            X[v, 2] -= 1.0
            el = [eij[(ii, jj)] for ii in (i, i + 1) for jj in (j, j + 1)]
            for e in el:
                lab[e] = "b1i"
            islands.append(el)
        else:
            dele.add(eij[(i, j)])
    keep = [k for k in range(len(conn)) if k not in dele]
    o2n = {k: n for n, k in enumerate(keep)}
    feat = {"islands": [{"kind": "dimple", "elems": np.asarray([o2n[e] for e in el], np.int64)} for el in islands],
            "hole_rims": [], "fastener_rim": np.zeros(0, np.int64), "kinds": [], "node_map": np.arange(X.shape[0])}
    return X, [conn[k] for k in keep], [et[k] for k in keep], [lab[k] for k in keep], feat


def elemset(mesh, mask):
    from esl.doe.bead_select import ranges_from_ids
    m = np.asarray(mask, bool)
    q = np.asarray(mesh["elem_type"]) == 4
    return {"q": ranges_from_ids(mesh["elem_id"][m & q]), "t": ranges_from_ids(mesh["elem_id"][m & ~q])}


def selection(g, *, b1_tiers=(1, 2), b2=True, **b1_extra) -> dict:
    """정답 바닥만 넣은 SelectionIn(사면 auto)."""
    m, lab = g["mesh"], g["label"]
    beads = [{"id": "b1", "name": "경로 비드", "tiers": [{"k": k + 1, "floor": elemset(m, lab == f"b1t{t}")}
                                                       for k, t in enumerate(b1_tiers)],
              "slope": {"mode": "auto"}, "blend_mm": "auto", **b1_extra}]
    if b2:
        beads.append({"id": "b2", "tiers": [{"k": 1, "floor": elemset(m, lab == "b2t1")}], "slope": {"mode": "auto"},
                      "blend_mm": "auto"})
    return {"schema_version": 1, "beads": beads}


# ====================================================================== v0.16.1 실제 Ch/R 사진 사례(높이장 메시)
# generate() 와 독립(그 출력 바이트 불변). 판 XY(z = 0), 구조 4각 격자 h, z = 높이장(비드 = 중심선 망까지 거리로 깊이, 사면 60°),
# 보스(섬) = 바닥 위 원뿔대 높이 더함, 구멍 = 요소 중심이 구멍 안이면 요소 제거(계단 경계). 정답 표지 = 노드 높이 상태로.
def _seg_dist(P: np.ndarray, a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-300), 0.0, 1.0)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def real_case(kind: str, h: float = 2.0) -> dict:
    """kind = network | boss_field | edge_slot | ring | edge_boss | channel. 반환 {mesh, label(요소별 'plate'|'<bead>f'|
    '<bead>s'|'isl'|'hole' 없음), beads{id: {D, W(개구 폭 = 2w), segs}}, bosses[{c, r, H, hole_r}], fixed_ids, truth{…}}.
    label '<id>f' = 그 비드 바닥(법선 ≤ 15° ∧ 중심 깊이 ≥ 0.75 D, 보스 영향 없음), 'isl' = 보스(벽 + 윗면)."""
    T = TAN60
    beads: dict = {}
    bosses: list = []
    holes: list = []                 # ("circle", cx, cy, r) | ("rect", x0, y0, x1, y1)
    Lx, Ly = 300.0, 200.0
    if kind == "network":            # 사다리(레일 2 + 가로대 2 = T 교차 4) + 따로 떨어진 L 비드
        beads = {"A": {"D": 8.0, "w": 10.0, "segs": [((30, 60), (230, 60))]},
                 "C": {"D": 8.0, "w": 10.0, "segs": [((30, 140), (230, 140))]},
                 "B1": {"D": 8.0, "w": 10.0, "segs": [((80, 60), (80, 140))]},
                 "B2": {"D": 8.0, "w": 10.0, "segs": [((180, 60), (180, 140))]},
                 "L": {"D": 8.0, "w": 10.0, "segs": [((255, 30), (255, 170)), ((255, 170), (285, 170))]}}
    elif kind == "boss_field":       # 넓은 돌출(위로 6) 평판 140×120 위 보스 12(Ø10~20, 높이 3~5, 가운데 버링 구멍)
        beads = {"P": {"D": -6.0, "w": 60.0, "segs": [((80, 100), (220, 100))]}}
        k = 0
        for j, y in enumerate((70.0, 100.0, 130.0)):
            for i, x in enumerate((100.0, 135.0, 170.0, 205.0)):
                r = (5.0, 7.0, 9.0, 10.0)[(i + j) % 4]
                bosses.append({"c": (x - 5.0 * (j == 1), y), "r": r, "H": (3.0, 4.0, 5.0)[k % 3],
                               "hole_r": (2.0, 3.0, 4.0)[k % 3]})
                k += 1
    elif kind == "edge_slot":        # 판 오른쪽 가장자리에 닿는 비드 E(열림) + 닫힌 비드 S, 둘 다 바닥에 사각 슬롯, 판 컷아웃
        beads = {"E": {"D": 6.0, "w": 14.0, "segs": [((120, 60), (Lx + 20.0, 60))]},
                 "S": {"D": 6.0, "w": 14.0, "segs": [((60, 140), (240, 140))]}}
        holes = [("rect", 190.0, 57.0, 206.0, 63.0), ("rect", 100.0, 137.0, 116.0, 143.0),
                 ("rect", 170.0, 136.0, 178.0, 144.0), ("rect", 20.0, 20.0, 50.0, 40.0)]
    elif kind == "ring":             # 고리형 비드: 큰 고리(안쪽 둔덕 Ø60) · 중간(Ø24) · 작은 고리(안쪽 둔덕 Ø14 — 크기로는 섬 상한 40 안)
        n = 48
        def circ(cx, cy, R):
            p = [(cx + R * math.cos(2 * math.pi * t / n), cy + R * math.sin(2 * math.pi * t / n)) for t in range(n + 1)]
            return [(p[t], p[t + 1]) for t in range(n)]
        beads = {"R1": {"D": 6.0, "w": 10.0, "segs": circ(90.0, 100.0, 40.0)},
                 "R2": {"D": 6.0, "w": 8.0, "segs": circ(190.0, 100.0, 20.0)},
                 "R3": {"D": 4.0, "w": 6.0, "segs": circ(255.0, 100.0, 13.0)}}
    elif kind == "edge_boss":        # 곧은 비드 + 개구 경계에 반쯤 걸친 보스 2개(위·아래 가장자리), 바닥 안 보스 1
        beads = {"G": {"D": 10.0, "w": 20.0, "segs": [((60, 100), (240, 100))]}}
        bosses = [{"c": (110.0, 120.0), "r": 9.0, "H": 4.0, "hole_r": 0.0, "z0": "plate"},
                  {"c": (190.0, 80.0), "r": 9.0, "H": 4.0, "hole_r": 0.0, "z0": "plate"},
                  {"c": (150.0, 100.0), "r": 5.0, "H": 3.0, "hole_r": 0.0}]
    elif kind == "channel":          # U 자 채널 비드(깊은 오목 경계 — 안쪽 판 60×70) + Ω 비드
        beads = {"U": {"D": 8.0, "w": 10.0, "segs": [((40, 170), (40, 40)), ((40, 40), (140, 40)), ((140, 40), (140, 170))]},
                 "O": {"D": 8.0, "w": 10.0, "segs": [((170, 60), (190, 60)), ((190, 60), (190, 160)), ((190, 160), (260, 160)),
                                                    ((260, 160), (260, 60)), ((260, 60), (280, 60))]}}
    else:
        raise ValueError(kind)
    xs = np.arange(0.0, Lx + 1e-9, h)
    ys = np.arange(0.0, Ly + 1e-9, h)
    nx, ny = xs.size, ys.size
    XX, YY = np.meshgrid(xs, ys, indexing="ij")
    P = np.column_stack([XX.ravel(), YY.ravel()])
    z = np.zeros(P.shape[0])
    own = np.full(P.shape[0], -1, np.int64)       # 노드가 깊이를 받은 비드 번호
    ids = list(beads)
    for bi, bid in enumerate(ids):
        b = beads[bid]
        d = np.min([_seg_dist(P, a, c) for a, c in b["segs"]], axis=0)
        r = abs(b["D"]) / T
        t = np.clip((b["w"] - d) / r, 0.0, 1.0)
        dep = b["D"] * t
        upd = np.abs(dep) > np.abs(z) + 1e-12
        z[upd] = -dep[upd]
        own[upd] = bi
        b["W"] = 2.0 * b["w"]
        b["floor_w"] = 2.0 * (b["w"] - r)
    zb = np.zeros(P.shape[0])                      # 보스 높이 더함(바닥 기준 +H 위쪽 = −z 반대, 바닥 법선 쪽)
    for bo in bosses:
        cx, cy = bo["c"]
        d = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
        s = bo["H"] / T
        t = np.clip((bo["r"] - d) / s, 0.0, 1.0)
        zb = np.maximum(zb, bo["H"] * t)
        if bo.get("hole_r"):
            holes.append(("circle", cx, cy, bo["hole_r"]))
    sgn = np.where(z < 0, 1.0, np.where(z > 0, -1.0, 1.0))  # 바닥 위쪽 = 판 쪽
    Z = z + sgn * zb
    X3 = np.column_stack([P, Z])
    nid = np.arange(nx * ny).reshape(nx, ny)
    conn, lab = [], []
    for i in range(nx - 1):
        for j in range(ny - 1):
            q = [nid[i, j], nid[i + 1, j], nid[i + 1, j + 1], nid[i, j + 1]]
            cxy = P[q].mean(axis=0)
            if any((hh[0] == "circle" and math.hypot(cxy[0] - hh[1], cxy[1] - hh[2]) < hh[3]) or
                   (hh[0] == "rect" and hh[1] < cxy[0] < hh[3] and hh[2] < cxy[1] < hh[4]) for hh in holes):
                continue
            if (zb[q] > 1e-12).any():
                L = "isl"
            elif (np.abs(z[q]) < 1e-12).all():
                L = "plate"
            else:                                    # 바닥 = 클릭 확장과 같게: 법선 ≤ 15° ∧ 중심 깊이 ≥ 0.75 D(사면 발치 거의 평평한 요소 포함)
                o = own[q]
                bi = int(o[o >= 0][0]) if (o >= 0).any() else -1
                nv = np.cross(X3[q[2]] - X3[q[0]], X3[q[3]] - X3[q[1]])
                flat = abs(nv[2]) >= math.cos(math.radians(15.0)) * np.linalg.norm(nv)
                if bi >= 0 and flat and abs(z[q].mean()) >= 0.75 * abs(beads[ids[bi]]["D"]) and (o == bi).all():
                    L = f"{ids[bi]}f"
                else:
                    L = f"{ids[bi]}s" if bi >= 0 else "plate"
            conn.append(q)
            lab.append(L)
    conn = np.asarray(conn, np.int64)
    used = np.zeros(nx * ny, bool)
    used[conn.ravel()] = True
    nm = np.full(nx * ny, -1, np.int64)
    nm[used] = np.arange(int(used.sum()))
    conn = nm[conn]
    Xf = X3[used]
    ne = conn.shape[0]
    mesh = {"node_id": 1 + np.arange(Xf.shape[0], dtype=np.int64), "x0": Xf, "elem_id": 1 + np.arange(ne, dtype=np.int64),
            "elem_type": np.full(ne, 4, np.int8), "conn": conn, "elem_pid": np.full(ne, 10, np.int64),
            "elem_mid": np.full(ne, 1, np.int64), "thickness": np.full(ne, 1.5), "E": np.full(ne, E_STEEL),
            "nu": np.full(ne, NU)}
    d = np.hypot(Xf[:, 0] - 10.0, Xf[:, 1] - 10.0)
    fixed = mesh["node_id"][d <= 4.0]               # 판 구석 체결(비드와 무관)
    return {"mesh": mesh, "label": np.array(lab), "beads": beads, "bosses": bosses, "holes": holes, "fixed_ids": fixed,
            "h": h, "kind": kind}


def real_selection(g: dict, ids, **extra) -> dict:
    """정답 바닥('<id>f')만 넣은 SelectionIn(사면 auto) — ids 순서대로 비드 b1, b2, …(이름 = 사례 id)."""
    m, lab = g["mesh"], g["label"]
    return {"schema_version": 1, "beads": [{"id": f"b{n + 1}", "name": i, "tiers": [{"k": 1, "floor": elemset(m, lab == f"{i}f")}],
                                            "slope": {"mode": "auto"}, "blend_mm": "auto", **extra}
                                           for n, i in enumerate(ids)]}
