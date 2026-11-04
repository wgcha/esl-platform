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
             fixed_r: float = 6.0, d1: float = 22.0, d2: float = 14.0, tria: bool = True) -> dict:
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
                conn.append([a_, b_, c_, d_])
                et.append(4)
                lab.append(L)
    conn = np.array(conn, np.int64)
    et = np.array(et, np.int8)
    ne = conn.shape[0]
    q = et == 4
    elem_id = np.zeros(ne, np.int64)
    elem_id[q] = 1 + np.arange(int(q.sum()))
    elem_id[~q] = 900001 + np.arange(int((~q).sum()))
    Xf = X.reshape(-1, 3)
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
    cols_in = [x for x in xs if xa + r1 + 1 < x < (xb - r1 - 1)]
    W_cols = np.array([wv(x) * math.cos(slope_ang(x)) for x in cols_in])
    return {"mesh": mesh, "label": np.array(lab), "fixed_ids": np.concatenate(groups), "fixed_groups": groups,
            "fixed_centers": centers, "xs": xs, "nx": nx, "ny": ny, "h": h, "rows_c": rows_c,
            "node_ij": nid, "zcode": zcode, "depth_fn": depth, "along_fn": along, "yc": yc, "wv": wv,
            "truth": {"b1": {"D": {1: d1, 2: d2}, "W_cols": W_cols}, "b2": {"D": {1: 6.0}, "W": 2 * R0}},
            "xa": xa, "xb": xb, "kinks": kinks, "ramp": ramp, "open_end": open_end}


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
