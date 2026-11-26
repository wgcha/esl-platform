"""v0.25.0 VB 시험 보조(계약 esl_virtual_bead.md §12): 정렬 quad 평판(gmsh 없음 — 결정적) · 사다리꼴 실제 메시 비드 · 가상 비드
(힌지 모핑) · 정확도 지표(V-0250-VB-11: 컴플라이언스 C 와 지그 Π — v0.24.4 ``jig_bc.METHODS`` prescribed·spring).

정확도 세계(§12-11): 평판 400×300·t 1.0·E 210 GPa·ν 0.3, 비드 중심선 (100, 150)→(300, 150)(L 200, +x), W_top 20, 끝 square
(사각 끝 — 실제 메시도 같은 식: 끝 사면이 같은 θ), r 0, 판 법선 +z, 비드는 −z 로 들어감(side −).
(A) 실제 메시 = 깊이면 가장자리(|y − 150| = W/2, x = 100 − W/2·300 + W/2)·입구 선(+ run)에 노드 행이 놓인 구조 격자 위에
    같은 단면식 z = −max(0, D − tanθ·max(0, d − W/2)) — 요소 경계 = 모서리(끝 네 귀퉁이 대각 꺾임만 요소 안).
(B) 가상 비드 = 같은 h 균일 격자(평판) + ``virtual_bead.field``·``displacement``(코어와 같은 식).
하중 2(균일 압력 1 MPa(노드 면적 몫, −z) · 집중 1 N(비드 중앙 (200, 150), −z)) · 지지(네 변 z 고정 + 면내 3-2-1).
지그 Π: tie 8점(네 귀퉁이·네 변 중점 — 두 격자 모두 노드), tie 성분 병진(translation — 3방향), 목표 u_tgt = 균일 압력 0.1 MPa 를
받은 평판(비드 없음 — 같은 격자 해)의 tie 변위… 대신 결정적 해석식 g_z = 0.2·(x/400)·(y/300) mm(면외), 하중 = 균일 압력 1.
Π = ``mixed_compliance`` C_mix(prescribed = 강제 변위 hard, spring = α·자기 강성 α 1).
"""
from __future__ import annotations

import json
import math

import numpy as np

PLATE = (400.0, 300.0)
LINE = ((100.0, 150.0), (300.0, 150.0))
W_TOP = 20.0
T, E, NU = 1.0, 2.1e5, 0.3


def _grid(xs, ys) -> dict:
    """정렬 quad 격자 → esl mesh dict(평면 z = 0)."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    nx, ny = xs.size, ys.size
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    P = np.column_stack([X.ravel(), Y.ravel(), np.zeros(X.size)])
    nid = np.arange(nx * ny).reshape(ny, nx)
    C = np.column_stack([nid[:-1, :-1].ravel(), nid[:-1, 1:].ravel(), nid[1:, 1:].ravel(), nid[1:, :-1].ravel()])
    m = C.shape[0]
    return {"node_id": np.arange(1, P.shape[0] + 1, dtype=np.int64), "x0": P, "elem_id": np.arange(1, m + 1, dtype=np.int64),
            "elem_type": np.full(m, 4, np.int8), "conn": C.astype(np.int64), "elem_pid": np.ones(m, np.int64),
            "elem_mid": np.ones(m, np.int64), "thickness": np.full(m, T), "E": np.full(m, E), "nu": np.full(m, NU)}


def _even(n: int) -> int:
    return n + (n % 2)


def uniform(h: float, size=PLATE) -> dict:
    """균일 격자(나눔 수 짝수 — 중앙선·tie 점이 노드)."""
    nx, ny = _even(max(2, int(round(size[0] / h)))), _even(max(2, int(round(size[1] / h))))
    return _grid(np.linspace(0.0, size[0], nx + 1), np.linspace(0.0, size[1], ny + 1))


def _axis(breaks, h, center):
    """구간 [b_i, b_i+1] 를 ceil(길이/h) 등분(center 를 품은 구간은 짝수 — 그 값이 노드)."""
    out = [breaks[0]]
    for a, b in zip(breaks[:-1], breaks[1:]):
        n = max(1, int(math.ceil((b - a) / h - 1e-9)))
        if a < center < b:
            n = _even(n)
        out += list(np.linspace(a, b, n + 1)[1:])
    return np.asarray(out)


def depth_z(x, y, D, theta, w_top=W_TOP, line=LINE):
    """사각 끝 사다리꼴 단면 깊이(+, 아래로): max(0, D − tanθ·max(0, d − W/2)), d = max(|y − yc|, 끝 넘침)."""
    (x0, yc), (x1, _y) = line
    over = np.maximum(np.maximum(0.0, x0 - x), x - x1)
    d = np.maximum(np.abs(y - yc), over)
    return np.maximum(0.0, D - math.tan(math.radians(theta)) * np.maximum(0.0, d - w_top / 2.0))


def real_bead(h, D, theta, w_top=W_TOP, line=LINE, size=PLATE) -> dict:
    """(A) 실제 메시 사다리꼴 비드: 모서리 선에 노드 행이 놓인 격자 + z = −depth."""
    run = D / math.tan(math.radians(theta))
    (x0, yc), (x1, _y) = line
    bx = sorted({0.0, size[0], x0 - w_top / 2 - run, x0 - w_top / 2, x1 + w_top / 2, x1 + w_top / 2 + run})
    by = sorted({0.0, size[1], yc - w_top / 2 - run, yc - w_top / 2, yc + w_top / 2, yc + w_top / 2 + run})
    m = _grid(_axis(bx, h, 0.5 * size[0]), _axis(by, h, yc))
    X = m["x0"]
    X[:, 2] = -depth_z(X[:, 0], X[:, 1], D, theta, w_top, line)
    return m


def virtual(h, D, theta, w_top=W_TOP, line=LINE, size=PLATE, end="square") -> tuple[dict, dict]:
    """(B) 균일 격자 + 힌지 모핑(코어 ``virtual_bead`` 식). 반환 (모핑 메시, field)."""
    from esl.morph import virtual_bead as vbm
    m = uniform(h, size)
    X = m["x0"]
    p0 = np.array([line[0][0], line[0][1], 0.0])
    p1 = np.array([line[1][0], line[1][1], 0.0])
    nh = np.array([0.0, 0.0, 1.0])
    q0, q1, t, L = vbm.resolve_line(p0, p1, None, None, None, (p0, nh))
    fp = vbm.footprint(X, (q0, q1, t, L, nh), w_top, theta, D, end, 0.0, 0.0)
    idx = np.flatnonzero(fp["move_mask"])
    nrm = vbm.node_normals(X, m["conn"], m["elem_type"], np.ones(m["conn"].shape[0], bool), nh)[idx]
    fd = vbm.field(fp["d"][idx], nrm, -1, w_top, theta, 0.0, idx=idx)
    out = dict(m)
    out["x0"] = X.copy()
    out["x0"][idx] += vbm.displacement(fd, D)
    return out, fd


# ---------------------------------------------------------------- 풀이
def _model(m):
    from esl.mech.shell import ShellModel
    return ShellModel(m["x0"], m["conn"], m["elem_type"], m["thickness"], m["E"], m["nu"], backend="superlu")


def _node_area(m) -> np.ndarray:
    from esl.morph import virtual_bead as vbm
    a = vbm.elem_areas(m["x0"], m["conn"], m["elem_type"])
    out = np.zeros(m["x0"].shape[0])
    for k in range(4):
        np.add.at(out, m["conn"][:, k], a / 4.0)
    return out


def _near(X, pts):
    return np.array([int(np.argmin(np.hypot(X[:, 0] - x, X[:, 1] - y))) for x, y in pts], np.int64)


TIES = ((0.0, 0.0), (200.0, 0.0), (400.0, 0.0), (0.0, 150.0), (400.0, 150.0), (0.0, 300.0), (200.0, 300.0),
        (400.0, 300.0))


def _spc(m):
    X = m["x0"]
    e = (np.abs(X[:, 0]) < 1e-9) | (np.abs(X[:, 0] - PLATE[0]) < 1e-9) | (np.abs(X[:, 1]) < 1e-9) | \
        (np.abs(X[:, 1] - PLATE[1]) < 1e-9)
    a, b = _near(X, [(0.0, 0.0), (PLATE[0], 0.0)])
    spc = {int(i): "3" for i in np.flatnonzero(e)}
    spc[int(a)] = "123"
    spc[int(b)] = "23"
    return sorted(spc.items())


def metrics(m) -> dict:
    """{C_p(균일 압력 1), C_f(집중 1 N), Pi_prescribed, Pi_spring}."""
    from esl.mech import jig_bc
    sm = _model(m)
    X = m["x0"]
    N = X.shape[0]
    fa = np.zeros((N, 3))
    fa[:, 2] = -1.0 * _node_area(m)
    ff = np.zeros((N, 3))
    ff[_near(X, [(200.0, 150.0)])[0], 2] = -1.0
    h = sm.factorize(_spc(m), order="node_mmd")
    out = {}
    for k, F in (("C_p", fa), ("C_f", ff)):
        r = h.solve(F)
        u = r[0] if isinstance(r, tuple) else r
        out[k] = float(np.sum(F * np.asarray(u)[:, :3]))
    del h, r, u                                         # 분해 1개씩만 메모리에(h 1.5 — superlu)
    import gc
    gc.collect()
    J = _near(X, TIES)
    tie = {"node": np.repeat(J, 3), "dir": np.tile(np.eye(3), (J.size, 1))}
    aux = {"node": np.zeros(0, np.int64), "dir": np.zeros((0, 3))}
    ut = np.zeros((N, 3))
    ut[:, 2] = 0.2 * (X[:, 0] / PLATE[0]) * (X[:, 1] / PLATE[1])
    for meth in ("prescribed", "spring"):
        row = jig_bc.METHODS[meth]
        kk = None
        if row["tie_stiff"] == "spring":
            kk = jig_bc.spring_k(sm, tie, mode="auto", alpha=1.0)
        BC = jig_bc.build_bc(row, tie, aux, ut, k=kk)
        hb = jig_bc.factorize(sm, BC)
        r = jig_bc.respond(hb, fa, BC)
        out[f"Pi_{meth}"] = float(r["energy"]["C_mix"])
        del hb, r
        gc.collect()
    return out


# ---------------------------------------------------------------- 정확도 표(V-0250-VB-11)
GRID = {"h": (5.0, 3.0, 1.5), "d": (3.0, 6.0), "theta": (45.0, 60.0)}
METRICS = ("C_p", "C_f", "Pi_prescribed", "Pi_spring")
MIN_WALL = 2.0                                    # = DEFAULTS virtual_bead.min_wall_elems(표 판정 — 값은 설정에서 읽어 대조)


def cell(h, D, theta, min_wall=MIN_WALL) -> dict:
    """한 칸: 해상도 판정(``virtual_bead.resolution``) + (불가 아니면) A·B 지표와 차(%)."""
    from esl.morph import virtual_bead as vbm
    rs = vbm.resolution(h, W_TOP, theta, D, min_wall)
    out = {"h": h, "d": D, "theta": theta, "wall_elems": round(rs["n_wall"], 3),
           "status": "VB_MESH_COARSE" if rs["codes"] else ("VB_WALL_COARSE" if any(
               w["code"] == "VB_WALL_COARSE" for w in rs["warns"]) else "ok")}
    if rs["codes"]:
        out.update({f"{k}_err_pct": None for k in METRICS}, c_err_pct=None, pi_err_pct=None)
        return out
    a = metrics(real_bead(h, D, theta))
    b = metrics(virtual(h, D, theta)[0])
    for k in METRICS:
        out[f"{k}_err_pct"] = round((b[k] / a[k] - 1.0) * 100.0, 3)
    out["c_err_pct"] = max((out["C_p_err_pct"], out["C_f_err_pct"]), key=abs)
    out["pi_err_pct"] = max((out["Pi_prescribed_err_pct"], out["Pi_spring_err_pct"]), key=abs)
    return out


def table(cells=None) -> dict:
    import itertools
    keys = cells or list(itertools.product(GRID["h"], GRID["d"], GRID["theta"]))
    return {"schema": "esl/vbead_accuracy/1",
            "world": {"plate_mm": list(PLATE), "t_mm": T, "E_mpa": E, "nu": NU, "line": [list(p) for p in LINE],
                      "w_top_mm": W_TOP, "end": "square", "r_mm": 0.0, "side": "-",
                      "loads": ["uniform pressure 1 MPa (-z)", "point 1 N at (200,150) (-z)"],
                      "support": "4 edges z + in-plane 3-2-1", "jig": "8 ties translation, target g_z = 0.2·x/400·y/300, "
                      "load = pressure 1, methods prescribed·spring(alpha 1)"},
            "metric": "B/A - 1 (%) — A = 모서리 정렬 실제 메시 사다리꼴, B = 균일 격자 + 힌지 모핑; c = max|C_p, C_f|, "
                      "pi = max|Π prescribed, Π spring|",
            "cells": [cell(h, d, th) for h, d, th in keys]}


def table_md(doc: dict) -> str:
    """tests/doe/vbead_accuracy.md 본문(같은 값 — 시험이 대조)."""
    st = {"ok": "–", "VB_WALL_COARSE": "VB_WALL_COARSE", "VB_MESH_COARSE": "불가(VB_MESH_COARSE)"}
    lines = ["# 가상 비드 정확도 표 (V-0250-VB-11, D-0.25.0-VB-17)", "",
             "생성: `python tests/doe/synth_vbead.py OUT.json` → resources/vbead_accuracy.json(같은 값). 차 = B/A − 1 (%),",
             "A = 모서리 정렬 실제 메시 사다리꼴 비드, B = 균일 격자(같은 h) + 힌지 모핑. 세계: " +
             json.dumps(doc["world"], ensure_ascii=False), "",
             "| h mm | D mm | θ ° | 사면 요소 n_wall | 상태 | C 압력 % | C 집중 % | Π 강제 변위 % | Π 스프링 % |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in doc["cells"]:
        head = f"| {c['h']:g} | {c['d']:g} | {c['theta']:g} | {c['wall_elems']:.2f} | {st[c['status']]} |"
        if c["c_err_pct"] is None:
            lines.append(head + " 불가 | 불가 | 불가 | 불가 |")
        else:
            lines.append(head + "".join(f" {c[k]:+.3f} |" for k in ("C_p_err_pct", "C_f_err_pct", "Pi_prescribed_err_pct",
                                                                      "Pi_spring_err_pct")))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":                       # 표 생성(느림 — h 1.5 칸): python tests/doe/synth_vbead.py OUT.json
    import json
    import sys
    doc = table()
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for c in doc["cells"]:
        print(c, flush=True)


# ---------------------------------------------------------------- 그래프 세계(derive·guard·e2e 시험)
GW_SIZE = (300.0, 200.0)
GW_CHANNEL = ((60.0, 60.0), (240.0, 60.0))        # 실제 채널 비드(−z, D 6·θ 45·W_top 20 → 입구 폭 32)
GW_HOLE = (240.0, 150.0, 10.0)                    # 구멍 중심·반폭(요소 제거) — 둘레 노드 = fixed-scan


def graph_mesh(h: float = 5.0, channel: bool = True, hole: bool = True) -> dict:
    """평판 300×200(정렬 quad) + 채널 비드(실제 메시) + 사각 구멍 → esl mesh dict(노드 압축)."""
    m = real_bead(h, 6.0, 45.0, line=GW_CHANNEL, size=GW_SIZE) if channel else uniform(h, GW_SIZE)
    if hole:
        X, C = m["x0"], m["conn"]
        cen = X[C].mean(axis=1)
        cx, cy, r = GW_HOLE
        keep = ~((np.abs(cen[:, 0] - cx) < r) & (np.abs(cen[:, 1] - cy) < r))
        C = C[keep]
        used = np.unique(C.ravel())
        remap = np.full(X.shape[0], -1)
        remap[used] = np.arange(used.size)
        n, e = used.size, int(keep.sum())
        m = {"node_id": np.arange(1, n + 1, dtype=np.int64), "x0": X[used], "elem_id": np.arange(1, e + 1, dtype=np.int64),
             "elem_type": np.full(e, 4, np.int8), "conn": remap[C], "elem_pid": np.ones(e, np.int64),
             "elem_mid": np.ones(e, np.int64), "thickness": np.full(e, T), "E": np.full(e, E), "nu": np.full(e, NU)}
    return m


def hole_rim_ids(m) -> np.ndarray:
    """구멍 둘레 노드 ID(fixed-scan 대역)."""
    cx, cy, r = GW_HOLE
    X, C = m["x0"], m["conn"]
    E = np.sort(np.concatenate([C[:, [0, 1]], C[:, [1, 2]], C[:, [2, 3]], C[:, [3, 0]]]), axis=1)
    u, cnt = np.unique(E, axis=0, return_counts=True)
    free = np.unique(u[cnt == 1].ravel())
    near = (np.abs(X[free, 0] - cx) <= 2 * r) & (np.abs(X[free, 1] - cy) <= 2 * r)
    return m["node_id"][free[near]]


def graph_world(h: float = 5.0, channel: bool = True, hole: bool = True, fixed: bool = True):
    """(mesh, graph, labels, fixed node ids, prep dir) — ``bead_graph.prep_graph`` 분류."""
    import tempfile

    from esl.doe import bead_graph as bgr
    from esl.doe import settings
    cfg = settings({"bead_doe": {"enabled": True}})
    m = graph_mesh(h, channel, hole)
    fx = tuple(int(i) for i in hole_rim_ids(m)) if (hole and fixed) else ()
    d = tempfile.mkdtemp(prefix="vb_gw_")
    st = bgr.prep_graph(m, list(fx), cfg, d)
    assert st["ok"], st
    g, lab = bgr.load_graph(d)
    return m, g, lab, fx, d


def frame_of(n=(0.0, 0.0, 1.0)) -> dict:
    return {"origin": [0.0, 0.0, 0.0], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 1.0 if n[2] > 0 else -1.0, 0.0],
            "n": list(n), "L_xi": GW_SIZE[0], "L_eta": GW_SIZE[1]}
