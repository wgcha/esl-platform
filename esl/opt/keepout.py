"""비드 금지 영역 (계약 esl_opt_run.md OR-D-11, §7.5). 평면도 자료(``plan_view``)와 워커 마스크(``compute``)는
같은 함수(``compute``)로 만든다 → 화면 미리보기 = 실행 결과.

좌표계: 대상 frame 의 (a, b) mm — a = (x − o)·ξ, b = (x − o)·η, 경계 ``a_range``·``b_range``. 요소 판정점 = 요소 중심 투영.

- 자동 구멍: 자유 모서리(요소 1개만 쓰는 모서리)의 연결 성분 = 루프. 둘레(3D) 최대 루프 = 외곽, 나머지 중 둘레 ≥
  ``hole_min_perimeter_mm`` = 구멍(미만은 메시 결함으로 무시). 구멍 루프 노드에서 3D 거리 ≤ ``hole_radius_mm`` 인 노드를
  쓰는 요소 → 금지(사유 1).
- 자동 가장자리: 외곽 루프 노드에서 3D 거리 ≤ ``edge_band_mm`` 인 노드를 쓰는 요소 → 금지(사유 2).
- 사각형: Rect{name, corner a0b0|a1b0|a0b1|a1b1, x_mm, y_mm, w_mm, h_mm} → (a, b) 범위(§7.5 식). 일부가 경계 밖이면 잘라서
  적용(경고), 완전히 밖이면 ``KEEPOUT_INVALID``. 요소 중심이 들면 금지(사유 3).
- 사유 우선순위: 구멍(1) > 가장자리(2) > 사각형(3). 마스크 = 합집합.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from esl.errors import EslError

CORNERS = ("a0b0", "a1b0", "a0b1", "a1b1")
REASON_NONE, REASON_HOLE, REASON_EDGE, REASON_RECT = 0, 1, 2, 3


# ---------------------------------------------------------------- 좌표·요소 중심
def project_ab(frame: dict, x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1, 3)
    P = x - np.asarray(frame["origin"], dtype=np.float64)
    return np.column_stack([P @ np.asarray(frame["e_xi"], dtype=np.float64),
                            P @ np.asarray(frame["e_eta"], dtype=np.float64)])


def centroids(mesh: dict) -> np.ndarray:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    out = np.empty((c.shape[0], 3))
    q = et == 4
    out[q] = X[c[q]].mean(axis=1)
    out[~q] = X[c[~q, :3]].mean(axis=1)
    return out


def _edges(conn, et):
    conn = np.asarray(conn, dtype=np.int64)
    et = np.asarray(et).astype(int)
    q, t = conn[et == 4], conn[et != 4]
    return np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]],
                           t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=0)


def free_edges(conn, et) -> np.ndarray:
    E = np.sort(_edges(conn, et), axis=1)
    if E.size == 0:
        return np.zeros((0, 2), np.int64)
    uniq, cnt = np.unique(E, axis=0, return_counts=True)
    return uniq[cnt == 1]


def _rings(B: np.ndarray) -> list[list[int]]:
    """자유 모서리 → 순서 있는 루프(노드 인덱스) 목록. 결정적: 작은 노드에서 시작, 작은 이웃 우선."""
    if B.size == 0:
        return []
    adj: dict[int, list[int]] = {}
    for a, b in B.tolist():
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    for k in adj:
        adj[k].sort()
    used: set[tuple[int, int]] = set()
    rings = []
    for start in sorted(adj):
        for nb in adj[start]:
            e = (min(start, nb), max(start, nb))
            if e in used:
                continue
            ring = [start]
            used.add(e)
            prev, cur = start, nb
            while cur != start:
                ring.append(cur)
                nxt = None
                for c in adj[cur]:
                    ee = (min(cur, c), max(cur, c))
                    if ee not in used:
                        nxt = c
                        break
                if nxt is None:
                    break
                used.add((min(cur, nxt), max(cur, nxt)))
                prev, cur = cur, nxt
            rings.append(ring)
    return rings


def boundary_loops(mesh: dict, min_perimeter: float) -> dict:
    """{outer: ring|None, holes: [ring], ignored: [ring], perimeters} (ring = 노드 인덱스 목록)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    rings = _rings(free_edges(mesh["conn"], mesh["elem_type"]))
    per = [float(np.sum(np.linalg.norm(X[r] - X[np.roll(r, -1)], axis=1))) if len(r) > 1 else 0.0 for r in rings]
    if not rings:
        return {"outer": None, "holes": [], "ignored": [], "perimeters": []}
    k_out = max(range(len(rings)), key=lambda k: (per[k], -min(rings[k])))
    holes, ign = [], []
    for k, r in enumerate(rings):
        if k == k_out:
            continue
        (holes if per[k] >= float(min_perimeter) else ign).append(r)
    return {"outer": rings[k_out], "holes": holes, "ignored": ign,
            "perimeters": {"outer": per[k_out], "holes": [per[rings.index(h)] for h in holes]}}


# ---------------------------------------------------------------- 사각형
def validate_rects(rects, kcfg: dict) -> list[dict]:
    if rects is None:
        return []
    if not isinstance(rects, list):
        raise EslError("KEEPOUT_INVALID", "rects 는 목록")
    if len(rects) > int(kcfg["max_rects"]):
        raise EslError("KEEPOUT_INVALID", f"사각형 {len(rects)}개 > 최대 {kcfg['max_rects']}")
    out = []
    for i, r in enumerate(rects):
        if not isinstance(r, dict):
            raise EslError("KEEPOUT_INVALID", f"사각형 {i + 1}: 객체가 아님")
        name = str(r.get("name") or f"R{i + 1}")
        if len(name) > int(kcfg.get("rect_name_max", 40)):
            raise EslError("KEEPOUT_INVALID", f"사각형 {i + 1}: 이름 {len(name)}자 > {kcfg.get('rect_name_max', 40)}")
        corner = r.get("corner")
        if corner not in CORNERS:
            raise EslError("KEEPOUT_INVALID", f"사각형 '{name}': 기준 모서리는 {CORNERS}")
        try:
            x, y, w, h = (float(r[k]) for k in ("x_mm", "y_mm", "w_mm", "h_mm"))
        except (KeyError, TypeError, ValueError):
            raise EslError("KEEPOUT_INVALID", f"사각형 '{name}': x_mm·y_mm·w_mm·h_mm 숫자 필요") from None
        if not all(math.isfinite(v) for v in (x, y, w, h)) or x < 0 or y < 0 or w <= 0 or h <= 0:
            raise EslError("KEEPOUT_INVALID", f"사각형 '{name}': X·Y ≥ 0, 가로·세로 > 0 (값 {x}, {y}, {w}, {h})")
        out.append({"name": name, "corner": corner, "x_mm": x, "y_mm": y, "w_mm": w, "h_mm": h})
    return out


def rect_bounds(rect: dict, frame: dict) -> dict:
    """Rect → {a: [a0,a1], b: [b0,b1], clipped, outside} (frame (a,b) mm)."""
    amin, amax = map(float, frame["a_range"])
    bmin, bmax = map(float, frame["b_range"])
    x, y, w, h = rect["x_mm"], rect["y_mm"], rect["w_mm"], rect["h_mm"]
    c = rect["corner"]
    a = [amin + x, amin + x + w] if c[:2] == "a0" else [amax - x - w, amax - x]
    b = [bmin + y, bmin + y + h] if c[2:] == "b0" else [bmax - y - h, bmax - y]
    outside = a[1] <= amin or a[0] >= amax or b[1] <= bmin or b[0] >= bmax
    ca = [max(a[0], amin), min(a[1], amax)]
    cb = [max(b[0], bmin), min(b[1], bmax)]
    clipped = (not outside) and (ca != a or cb != b)
    return {"a": ca if not outside else a, "b": cb if not outside else b, "clipped": clipped, "outside": outside,
            "a_raw": a, "b_raw": b}


def rect_from_bounds(a0: float, b0: float, w: float, h: float, corner: str, frame: dict, name: str = "") -> dict:
    """(a0,b0) 좌하 점 + 크기 → 주어진 기준 모서리의 Rect (드래그 → 숫자 동기화와 같은 식, 1 mm 반올림은 화면 몫)."""
    amin, amax = map(float, frame["a_range"])
    bmin, bmax = map(float, frame["b_range"])
    x = a0 - amin if corner[:2] == "a0" else amax - (a0 + w)
    y = b0 - bmin if corner[2:] == "b0" else bmax - (b0 + h)
    return {"name": name, "corner": corner, "x_mm": x, "y_mm": y, "w_mm": w, "h_mm": h}


# ---------------------------------------------------------------- 마스크
def _near_nodes(X: np.ndarray, seeds: list[int], r: float) -> np.ndarray:
    if not seeds or r <= 0:
        return np.zeros(X.shape[0], dtype=bool)
    tree = cKDTree(X[np.asarray(sorted(set(seeds)), dtype=np.int64)])
    d, _ = tree.query(X, k=1, distance_upper_bound=float(r) * (1 + 1e-12) + 1e-12)
    return np.isfinite(d) & (d <= float(r) * (1 + 1e-12) + 1e-12)


def _elems_using(mesh: dict, node_mask: np.ndarray) -> np.ndarray:
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    out = np.zeros(c.shape[0], dtype=bool)
    for k in range(4):
        ok = k < et
        out |= ok & node_mask[np.maximum(c[:, k], 0)]
    return out


def compute(mesh: dict, frame: dict, keepout: dict | None, kcfg: dict) -> dict:
    """금지 영역 마스크. keepout = {rects:[Rect], auto:{hole: bool, edge: bool}} (없으면 자동 둘 다 켬, 사각형 없음).

    반환 {mask (E,) bool, reason (E,) int8, counts{n_elems_auto_hole, n_elems_auto_edge, n_elems_rects, n_keepout},
    rects:[{…, a, b, clipped}], loops{outer, holes, ignored}, warnings[]}.
    """
    ko = keepout or {}
    auto = {"hole": True, "edge": True}
    auto.update({k: bool(v) for k, v in (ko.get("auto") or {}).items() if k in ("hole", "edge")})
    rects = validate_rects(ko.get("rects") or [], kcfg)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    ne = np.asarray(mesh["conn"]).shape[0]
    loops = boundary_loops(mesh, float(kcfg["hole_min_perimeter_mm"]))
    warns: list[str] = []
    if loops["ignored"]:
        warns.append(f"둘레 < {kcfg['hole_min_perimeter_mm']} mm 자유 모서리 루프 {len(loops['ignored'])}개 무시(메시 결함?)")
    hole_e = np.zeros(ne, dtype=bool)
    edge_e = np.zeros(ne, dtype=bool)
    if auto["hole"] and loops["holes"]:
        seeds = [n for r in loops["holes"] for n in r]
        hole_e = _elems_using(mesh, _near_nodes(X, seeds, float(kcfg["hole_radius_mm"])))
    if auto["edge"] and loops["outer"] is not None:
        edge_e = _elems_using(mesh, _near_nodes(X, loops["outer"], float(kcfg["edge_band_mm"])))
    ab = project_ab(frame, centroids(mesh))
    rect_e = np.zeros(ne, dtype=bool)
    rres = []
    for r in rects:
        bb = rect_bounds(r, frame)
        if bb["outside"]:
            raise EslError("KEEPOUT_INVALID", f"사각형 '{r['name']}' 이 대상 경계 밖에 완전히 있음 "
                                              f"(a {bb['a_raw']}, b {bb['b_raw']}, 경계 a {frame['a_range']}, b {frame['b_range']})")
        if bb["clipped"]:
            warns.append(f"사각형 '{r['name']}' 이 대상 경계를 벗어나 잘라서 적용")
        m = (ab[:, 0] >= bb["a"][0]) & (ab[:, 0] <= bb["a"][1]) & (ab[:, 1] >= bb["b"][0]) & (ab[:, 1] <= bb["b"][1])
        rect_e |= m
        rres.append({**r, "a": bb["a"], "b": bb["b"], "clipped": bb["clipped"], "n_elems": int(m.sum())})
    reason = np.zeros(ne, dtype=np.int8)
    reason[rect_e] = REASON_RECT
    reason[edge_e] = REASON_EDGE
    reason[hole_e] = REASON_HOLE
    mask = reason > 0
    counts = {"n_elems_auto_hole": int(np.sum(reason == REASON_HOLE)),
              "n_elems_auto_edge": int(np.sum(reason == REASON_EDGE)),
              "n_elems_rects": int(np.sum(reason == REASON_RECT)), "n_keepout": int(mask.sum()),
              "n_holes": len(loops["holes"])}
    return {"mask": mask, "reason": reason, "counts": counts, "rects": rres, "auto": auto, "loops": loops,
            "warnings": warns}


def frame_shift_warning(saved: dict | None, current: dict, kcfg: dict) -> str | None:
    """저장 세트 frame(a_range·b_range) 과 현재 대상 frame 이 frame_warn_mm 이상 다르면 경고 문구."""
    if not saved:
        return None
    tol = float(kcfg.get("frame_warn_mm", 1.0))
    d = max(abs(float(saved[k][i]) - float(current[k][i])) for k in ("a_range", "b_range") for i in (0, 1))
    if d >= tol:
        return f"모델 경계가 달라짐(최대 {d:.1f} mm) — 사각형 위치 확인"
    return None


# ---------------------------------------------------------------- 평면도 자료
def _ring_ab(frame, X, ring) -> list[list[float]]:
    ab = project_ab(frame, X[np.asarray(ring, dtype=np.int64)])
    return [[round(float(a), 3), round(float(b), 3)] for a, b in ab]


def region_rings(mesh: dict, elem_mask: np.ndarray, frame: dict) -> list[list[list[float]]]:
    """선택 요소 영역의 경계 루프(평면 (a,b)) — 짝홀 채우기(evenodd)로 그리면 영역이 된다."""
    if not np.any(elem_mask):
        return []
    sub = {"conn": np.asarray(mesh["conn"])[elem_mask], "elem_type": np.asarray(mesh["elem_type"])[elem_mask]}
    X = np.asarray(mesh["x0"], dtype=np.float64)
    return [_ring_ab(frame, X, r) for r in _rings(free_edges(sub["conn"], sub["elem_type"])) if len(r) >= 3]


def plan_view(mesh: dict, frame: dict, kcfg: dict, max_points: int, keepout: dict | None = None) -> dict:
    """PlanViewOut 자료(§5.2). 자동 영역은 사각형 없이 ``compute`` 로 만든 마스크의 경계."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    auto = (keepout or {}).get("auto") or {"hole": True, "edge": True}
    res = compute(mesh, frame, {"rects": [], "auto": auto}, kcfg)
    loops = res["loops"]
    ab = project_ab(frame, centroids(mesh))
    ne = ab.shape[0]
    step = max(1, int(math.ceil(ne / max(int(max_points), 1))))
    idx = np.arange(0, ne, step)
    pid = np.asarray(mesh["elem_pid"], dtype=np.int64)
    pts = [[round(float(ab[i, 0]), 2), round(float(ab[i, 1]), 2), int(pid[i])] for i in idx]
    return {"frame": {"a_range": [float(v) for v in frame["a_range"]], "b_range": [float(v) for v in frame["b_range"]]},
            "outline": _ring_ab(frame, X, loops["outer"]) if loops["outer"] is not None else [],
            "holes": [_ring_ab(frame, X, r) for r in loops["holes"]],
            "elems": {"n_total": int(ne), "decimated": step > 1, "points": pts},
            "auto_keepout": {"hole_radius_mm": float(kcfg["hole_radius_mm"]),
                             "edge_band_mm": float(kcfg["edge_band_mm"]),
                             "polygons": region_rings(mesh, res["mask"], frame),
                             "counts": res["counts"]},
            "warnings": res["warnings"]}
