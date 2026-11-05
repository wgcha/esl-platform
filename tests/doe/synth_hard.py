"""v0.16.1 어려운 사례 H1~H4 생성기(시험 엔지니어 재현 자료 → 회귀 시험 ``test_bead_select_hard.py`` 로 고정, SR-D-35~43).
겹치고 복잡한 형상(높이장 구조 4각 메시 + 같은 형상 OCC STEP).

높이장 = 고체 불리언 의미(판 윗면 z = 0, 아래가 재료):
- 비드(오목): s = max(−D, −T·(w − d)) 를 min 으로 깎음(d = 중심선 거리 또는 사각 inset), 사면 60°.
- 돌출 평판(D < 0): s = min(|D|, T·(w − d)) 를 max 로 붙임.
- 보스(바닥 위로 솟음, 원뿔대 60°): b = z_top − T·max(0, ρ − r_top) 를 max 로 붙임 → 'isl'.
- 딤플(더 깊게): b = z_bot + T·max(0, ρ − r_bot) 를 min 으로 깎음 → 'isl'.
- 루버(작은 사각 돌기): b = z_top − T·max(0, outset) 를 max → 'isl'.
- 구멍: 요소 중심이 원·사각 안이면 요소 제거.
- 플랜지: y < yf 노드를 (x, yf, yf − y) 로 세움(판 가장자리 90° 꺾임) — 고정 노드 = 플랜지 끝 줄.
표지: 'plate' | '<bid>f<k>'(단 k 바닥: 법선 ≤ 15° ∧ 모든 노드가 그 성분 소유 ∧ 평균 깊이가 D_k ± 0.25·단 높이) | '<bid>s' | 'isl'.
"""
from __future__ import annotations

import math
import os

import numpy as np

BOSS_R = 2.5                 # H1 교차 보스 윗면 반지름(3.5 = 벽까지 1요소 — 섬 판정 실패 변형)
TAN60 = math.tan(math.radians(60.0))
E_STEEL, NU = 205000.0, 0.3


def seg_dist(P, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-300), 0.0, 1.0)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


def _inset(P, comp):
    """성분 경계 안쪽 거리 w − d (양수 = 개구 안)."""
    if "rect" in comp:
        cx, cy, hx, hy = comp["rect"]
        return np.minimum(hx - np.abs(P[:, 0] - cx), hy - np.abs(P[:, 1] - cy))
    d = np.min([seg_dist(P, a, c) for a, c in comp["segs"]], axis=0)
    return comp["w"] - d


def build(spec: dict, h: float = 2.0) -> dict:
    T = TAN60
    Lx, Ly = spec["Lx"], spec["Ly"]
    xs = np.arange(0.0, Lx + 1e-9, h)
    ys = np.arange(0.0, Ly + 1e-9, h)
    nx, ny = xs.size, ys.size
    XX, YY = np.meshgrid(xs, ys, indexing="ij")
    P = np.column_stack([XX.ravel(), YY.ravel()])
    n = P.shape[0]
    Z = np.zeros(n)
    own = np.full(n, -1, np.int64)
    comps = spec["comps"]
    for ci, c in enumerate(comps):
        ins = _inset(P, c)
        if c["D"] > 0:
            s = np.maximum(-c["D"], -T * ins)
            upd = s < Z - 1e-12
        else:
            s = np.minimum(-c["D"], T * ins)
            upd = s > Z + 1e-12
        Z[upd] = s[upd]
        own[upd] = ci
    Zb = Z.copy()
    isl_node = np.zeros(n, bool)
    holes = list(spec.get("holes", []))
    for bo in spec.get("bosses", []):
        cx, cy = bo["c"]
        rho = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
        b = bo["z_top"] - T * np.maximum(0.0, rho - bo["r_top"])
        u = b > Z + 1e-9
        Z[u] = b[u]
        isl_node |= u
        if bo.get("hole_r"):
            holes.append(("circle", cx, cy, bo["hole_r"]))
    for dm in spec.get("dimples", []):
        cx, cy = dm["c"]
        rho = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
        b = dm["z_bot"] + T * np.maximum(0.0, rho - dm["r_bot"])
        u = b < Z - 1e-9
        Z[u] = b[u]
        isl_node |= u
    for lv in spec.get("louvers", []):
        cx, cy, hx, hy = lv["rect"]
        o = np.maximum(np.abs(P[:, 0] - cx) - hx, np.abs(P[:, 1] - cy) - hy)
        b = lv["z_top"] - T * np.maximum(0.0, o)
        u = b > Z + 1e-9
        Z[u] = b[u]
        isl_node |= u
    X3 = np.column_stack([P, Z])
    fl = spec.get("flange")
    if fl:                                            # 판 아래 가장자리(y < yf) 세움
        yf = fl["yf"]
        m = P[:, 1] < yf - 1e-9
        X3[m, 2] = Z[m] + (yf - P[m, 1])
        X3[m, 1] = yf
    nid = np.arange(n).reshape(nx, ny)
    conn, lab = [], []
    steps = {}
    for c in comps:                                   # 단 높이(같은 비드 다음 얕은 단과의 차)
        same = sorted([abs(o["D"]) for o in comps if o["bead"] == c["bead"] and abs(o["D"]) < abs(c["D"])])
        steps[id(c)] = abs(c["D"]) - (same[-1] if same else 0.0)
    for i in range(nx - 1):
        for j in range(ny - 1):
            q = [nid[i, j], nid[i + 1, j], nid[i + 1, j + 1], nid[i, j + 1]]
            cxy = P[q].mean(axis=0)
            if any((hh[0] == "circle" and math.hypot(cxy[0] - hh[1], cxy[1] - hh[2]) < hh[3]) or
                   (hh[0] == "rect" and hh[1] < cxy[0] < hh[3] and hh[2] < cxy[1] < hh[4]) for hh in holes):
                continue
            if isl_node[q].any():
                L = "isl"
            elif (np.abs(Zb[q]) < 1e-12).all():
                L = "plate" if not (fl and (P[q, 1] < fl["yf"] - 1e-9).any()) else "flange"
            else:                                   # 클릭 확장과 같게: 평평 ∧ 깊이 = 그 비드 단 k(± 0.25 단 높이) → 단 k 바닥
                o = own[q]
                ci = int(np.bincount(o[o >= 0]).argmax()) if (o >= 0).any() else -1
                bid = comps[ci]["bead"]
                nv = np.cross(X3[q[2]] - X3[q[0]], X3[q[3]] - X3[q[1]])
                flat = abs(nv[2]) >= math.cos(math.radians(15.0)) * np.linalg.norm(nv)
                zm = abs(Zb[q].mean())
                L = f"{bid}s"
                if flat:
                    for c in comps:
                        if c["bead"] == bid and abs(zm - abs(c["D"])) <= 0.25 * steps[id(c)]:
                            L = f"{bid}f{c['k']}"
            conn.append(q)
            lab.append(L)
    conn = np.asarray(conn, np.int64)
    used = np.zeros(n, bool)
    used[conn.ravel()] = True
    nm = np.full(n, -1, np.int64)
    nm[used] = np.arange(int(used.sum()))
    conn = nm[conn]
    Xf = X3[used]
    ne = conn.shape[0]
    mesh = {"node_id": 1 + np.arange(Xf.shape[0], dtype=np.int64), "x0": Xf, "elem_id": 1 + np.arange(ne, dtype=np.int64),
            "elem_type": np.full(ne, 4, np.int8), "conn": conn, "elem_pid": np.full(ne, 10, np.int64),
            "elem_mid": np.full(ne, 1, np.int64), "thickness": np.full(ne, 1.5), "E": np.full(ne, E_STEEL),
            "nu": np.full(ne, NU)}
    fixed = []
    for (fx, fy, fr) in spec.get("fixed", [(10.0, Ly - 10.0, 4.0)]):
        d = np.hypot(Xf[:, 0] - fx, Xf[:, 1] - fy)
        fixed.append(mesh["node_id"][(d <= fr) & (np.abs(Xf[:, 2]) < 1e-9)])
    if fl and fl.get("fixed"):
        top = Xf[:, 2] >= fl["yf"] - 1e-9
        fixed.append(mesh["node_id"][top & (Xf[:, 0] >= fl["fixed"][0]) & (Xf[:, 0] <= fl["fixed"][1])])
    return {"mesh": mesh, "label": np.array(lab), "spec": spec, "fixed_ids": np.concatenate(fixed) if fixed else np.zeros(0, np.int64),
            "h": h, "own_node": nm, "isl_node": isl_node[used]}


def height(spec: dict, P: np.ndarray) -> np.ndarray:
    """build() 와 같은 높이장 z(x, y)(구멍·플랜지 없음) — ④ 메시 편차 기준."""
    T = TAN60
    n = P.shape[0]
    Z = np.zeros(n)
    for c in spec["comps"]:
        ins = _inset(P, c)
        Z = np.minimum(Z, np.maximum(-c["D"], -T * ins)) if c["D"] > 0 else np.maximum(Z, np.minimum(-c["D"], T * ins))
    for bo in spec.get("bosses", []):
        rho = np.hypot(P[:, 0] - bo["c"][0], P[:, 1] - bo["c"][1])
        Z = np.maximum(Z, bo["z_top"] - T * np.maximum(0.0, rho - bo["r_top"]))
    for dm in spec.get("dimples", []):
        rho = np.hypot(P[:, 0] - dm["c"][0], P[:, 1] - dm["c"][1])
        Z = np.minimum(Z, dm["z_bot"] + T * np.maximum(0.0, rho - dm["r_bot"]))
    for lv in spec.get("louvers", []):
        cx, cy, hx, hy = lv["rect"]
        o = np.maximum(np.abs(P[:, 0] - cx) - hx, np.abs(P[:, 1] - cy) - hy)
        Z = np.maximum(Z, lv["z_top"] - T * np.maximum(0.0, o))
    return Z


def elemset(mesh, mask):
    from esl.doe.bead_select import ranges_from_ids
    m = np.asarray(mask, bool)
    q = np.asarray(mesh["elem_type"]).astype(int) == 4
    return {"q": ranges_from_ids(mesh["elem_id"][m & q]), "t": ranges_from_ids(mesh["elem_id"][m & ~q])}


def selection(g, beads, links=None, **extra):
    """beads = [(name, n_tiers)] → b1.. 순서. links = {name: [[2, 3]]}."""
    m, lab = g["mesh"], g["label"]
    out = []
    for n_, (name, nt) in enumerate(beads):
        b = {"id": f"b{n_ + 1}", "name": name, "tiers": [{"k": k, "floor": elemset(m, lab == f"{name}f{k}")} for k in range(1, nt + 1)],
             "slope": {"mode": "auto"}, "blend_mm": "auto", **extra}
        if links and name in links:
            b["links"] = links[name]
        out.append(b)
    return {"schema_version": 1, "beads": out}


# ============================================================================ 사례
def case(kind: str) -> dict:
    if kind == "H1":            # X 교차: 얕은 S(15) · 깊은 Dp(25) — 대각 교차, 교차 바닥 보스, S 바닥 딤플 2
        a, b = (50.0, 50.0), (270.0, 210.0)
        c, d = (50.0, 210.0), (270.0, 50.0)
        return {"Lx": 320.0, "Ly": 260.0,
                "comps": [{"bead": "S", "k": 1, "D": 15.0, "w": 18.0, "segs": [(a, b)]},
                          {"bead": "Dp", "k": 1, "D": 25.0, "w": 24.0, "segs": [(c, d)]}],
                "bosses": [{"c": (160.0, 130.0), "r_top": BOSS_R, "z_top": -21.0, "hole_r": 1.5}],
                "dimples": [{"c": (85.0, 75.5), "r_bot": 2.5, "z_bot": -18.0}, {"c": (235.0, 184.5), "r_bot": 2.5, "z_bot": -18.0}],
                "fixed": [(10.0, 130.0, 4.0), (310.0, 130.0, 4.0)]}
    if kind == "H2":            # 3단 계단(닫힌 직선 비드 단면 다단): 8 · 16 · 24, 단마다 딤플, 단1→2 사면에 걸친 구멍
        segs = [((80.0, 110.0), (240.0, 110.0))]
        return {"Lx": 320.0, "Ly": 220.0,
                "comps": [{"bead": "T", "k": 1, "D": 8.0, "w": 50.0, "segs": segs},
                          {"bead": "T", "k": 2, "D": 16.0, "w": 34.0, "segs": segs},
                          {"bead": "T", "k": 3, "D": 24.0, "w": 20.0, "segs": segs}],
                "dimples": [{"c": (110.0, 110.0 + 37.4), "r_bot": 2.0, "z_bot": -10.5},
                            {"c": (150.0, 110.0 + 17.8), "r_bot": 2.0, "z_bot": -18.5},
                            {"c": (190.0, 110.0), "r_bot": 1.5, "z_bot": -26.0}],
                "holes": [("circle", 210.0, 110.0 - 27.0, 4.0)],     # 단1(d 29.4..45.4)·사면(24.8..29.4)·단2 에 걸침
                "fixed": [(10.0, 10.0, 4.0), (310.0, 210.0, 4.0)]}
    if kind == "H3":            # 근접·합류·플랜지: A·B 간격 8 < 블렌딩, A 벽 = 돌출 평판 P 벽(접선 합류), C 는 플랜지 9 mm 옆
        return {"Lx": 320.0, "Ly": 240.0,
                "comps": [{"bead": "A", "k": 1, "D": 8.0, "w": 10.0, "segs": [((60.0, 150.0), (260.0, 150.0))]},
                          {"bead": "B", "k": 1, "D": 8.0, "w": 10.0, "segs": [((60.0, 122.0), (260.0, 122.0))]},
                          # 돌출 평판(위 6): 개구 아래 가장자리 = A 개구 위 가장자리(y 160) → A 벽(−8→0)과 P 벽(0→+6)이 한 평면
                          {"bead": "P", "k": 1, "D": -6.0, "rect": (160.0, 160.0 + 30.0, 90.0, 30.0)},
                          {"bead": "C", "k": 1, "D": 6.0, "w": 8.0, "segs": [((60.0, 25.0), (260.0, 25.0))]}],
                "flange": {"yf": 8.0, "fixed": (40.0, 280.0)},
                "fixed": [(10.0, 230.0, 4.0)]}
    if kind == "H4":            # 밀집·관통: 비드 G(10, 개구 40×220 사각 frustum) + 보스 6(겹침·맞닿음·경계 걸침) + 벽 가로지르는 슬롯 + 루버 2
        z_f = -10.0
        bosses = [{"c": (80.0, 100.0), "r_top": 5.0, "z_top": z_f + 4.0, "hole_r": 2.5},
                  {"c": (93.0, 100.0), "r_top": 5.0, "z_top": z_f + 4.0, "hole_r": 0.0},     # 1 과 겹침
                  {"c": (118.0, 100.0), "r_top": 4.0, "z_top": z_f + 5.0, "hole_r": 2.0},
                  {"c": (129.6, 100.0), "r_top": 3.0, "z_top": z_f + 3.0, "hole_r": 0.0},    # 3 과 맞닿음
                  {"c": (170.0, 120.0), "r_top": 6.0, "z_top": 3.0, "hole_r": 3.0},          # 위 개구 경계에 걸침(판 위로 3)
                  {"c": (210.0, 80.0), "r_top": 5.0, "z_top": 2.0, "hole_r": 0.0}]           # 아래 개구 경계에 걸침
        return {"Lx": 300.0, "Ly": 200.0,
                "comps": [{"bead": "G", "k": 1, "D": 10.0, "rect": (150.0, 100.0, 110.0, 20.0)}],
                "bosses": bosses,
                "louvers": [{"rect": (150.0, 96.0, 6.0, 2.0), "z_top": z_f + 1.5},
                            {"rect": (240.0, 100.0, 2.0, 6.0), "z_top": z_f + 1.5}],
                "holes": [("rect", 60.0, 108.0, 66.0, 128.0)],     # 슬롯 6×20: 바닥(≤114.2) → 벽 → 판(≥120)
                "fixed": [(10.0, 10.0, 4.0), (290.0, 190.0, 4.0)]}
    raise ValueError(kind)


# ============================================================================ H4 STEP (같은 형상 OCC)
def h4_step(path: str) -> str:
    """case('H4') 와 같은 형상의 쉘 STEP: 판 슬래브(z −30..0)에서 비드 frustum 을 깎고 보스 원뿔대·루버 frustum 을 붙이고
    구멍(버링·슬롯)을 뚫은 뒤 바닥(z −30)에 닿는 면(밑면·옆면·관통 구멍 벽)을 버린 윗면 쉘."""
    import gmsh
    sp = case("H4")
    T = TAN60
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        zb = -30.0
        slab = occ.addBox(0, 0, zb, sp["Lx"], sp["Ly"], -zb)

        def rect_wire(cx, cy, hx, hy, z):
            p = [occ.addPoint(cx - hx, cy - hy, z), occ.addPoint(cx + hx, cy - hy, z), occ.addPoint(cx + hx, cy + hy, z),
                 occ.addPoint(cx - hx, cy + hy, z)]
            ln = [occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)]
            return occ.addCurveLoop(ln)

        def frustum(cx, cy, hx0, hy0, z0, hx1, hy1, z1):
            w0, w1 = rect_wire(cx, cy, hx0, hy0, z0), rect_wire(cx, cy, hx1, hy1, z1)
            out = occ.addThruSections([w0, w1], makeSolid=True, makeRuled=True)
            return [e for e in out if e[0] == 3]

        cx, cy, hx, hy = sp["comps"][0]["rect"]
        D = sp["comps"][0]["D"]
        e = 2.0                                          # 판 위로 조금 더(깔끔한 불리언)
        cut = frustum(cx, cy, hx - D / T, hy - D / T, -D, hx + e / T, hy + e / T, e)
        body, _ = occ.cut([(3, slab)], cut)
        adds = []
        for bo in sp["bosses"]:
            zt = bo["z_top"]
            z0 = -D - 1.0
            r0 = bo["r_top"] + (zt - z0) / T
            adds.append((3, occ.addCone(bo["c"][0], bo["c"][1], z0, 0, 0, zt - z0, r0, bo["r_top"])))
        for lv in sp["louvers"]:
            lx, ly, lhx, lhy = lv["rect"]
            zt = lv["z_top"]
            z0 = -D - 1.0
            adds += frustum(lx, ly, lhx + (zt - z0) / T, lhy + (zt - z0) / T, z0, lhx, lhy, zt)
        body, _ = occ.fuse(body, adds)
        tools = []
        for bo in sp["bosses"]:
            if bo.get("hole_r"):
                tools.append((3, occ.addCylinder(bo["c"][0], bo["c"][1], zb - 1, 0, 0, 40.0, bo["hole_r"])))
        for hh in sp["holes"]:
            if hh[0] == "rect":
                tools.append((3, occ.addBox(hh[1], hh[2], zb - 1, hh[3] - hh[1], hh[4] - hh[2], 40.0)))
        body, _ = occ.cut(body, tools)
        occ.synchronize()
        vols = [t for d_, t in body if d_ == 3]
        faces = gmsh.model.getBoundary([(3, v) for v in vols], oriented=False, combined=True)
        keep, drop = [], []
        for _d, f in faces:
            bb = gmsh.model.getBoundingBox(2, abs(f))
            (drop if bb[2] <= zb + 1e-6 else keep).append(abs(f))
        occ.remove([(3, v) for v in vols])
        occ.remove([(2, f) for f in drop], recursive=True)
        occ.synchronize()
        left = [t for _d, t in gmsh.model.getEntities(2)]
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        gmsh.write(path)
        return path, len(left), len(drop)
    finally:
        gmsh.finalize()
