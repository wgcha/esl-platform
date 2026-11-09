"""공통 모핑 코어 — 비드 강성 시나리오의 모핑 안전 규칙(계약 esl_select_relax.md SR-D-35~44, v0.16.1).

입력 = 메시 노드·요소(``esl.mesh.features.MeshIndex`` 또는 MESH_KEYS dict)·좌표 배열·피처 라벨(요소/노드 마스크)만 —
메시 출처(gmsh STEP 메시·사용자 .rad/.inc·재메시)를 모른다(SR-D-44). numpy/scipy 만, 파일·DB 없음.
호출: ③ select(``esl.doe.bead_select``) · 자동 탐지 기본 모핑(paicad same·mesh 안 좌표 — ``post_morph_warnings``) ·
사용자 메시 입력 기준(select 기준 메시가 Case .rad/.inc 일 때 같은 경로) · (보류) ③ STEP 모핑.
섬 판정·구멍 분류·바닥 조각 다각형·판 가장자리는 ``esl.mesh.features``(enclosed_components·free_edge_components·
outer_polygons·plate_edge_nodes) — 이 모듈은 그 위의 기준 평면·피처·안 판정 규칙.
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from esl.mesh.features import MeshIndex

_EPS = 1e-12
U_EPS = 1e-9                       # 영향 판정(노드 변위 > U_EPS mm — bead_select §6, AD-D-10: 한 곳에서 정의, bead_select 는 재노출)


def _r(v, nd: int = 4):
    if v is None:
        return None
    f = float(v)
    if not math.isfinite(f):
        return None
    r = round(f, nd)
    return 0.0 if r == 0 else r


def _mask_of(n: int, idx) -> np.ndarray:
    m = np.zeros(n, bool)
    m[np.asarray(idx, dtype=np.int64)] = True
    return m


def _quality_cfg(qc: dict | None) -> dict:
    """select.quality 설정(DEFAULTS 위에 병합 — AD-D-10: 리터럴 기본값을 코드에 두지 않음)."""
    from esl.doe import DEFAULTS, _deep_merge
    return _deep_merge(DEFAULTS["select"]["quality"], qc or {})


def plane_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """최소제곱 평면 (점, 단위 법선, rms)."""
    p = X.mean(axis=0)
    if X.shape[0] < 3:
        return p, np.array([0.0, 0.0, 1.0]), 0.0
    _, s, vt = np.linalg.svd(X - p, full_matrices=False)
    m = vt[-1]
    rms = float(np.sqrt(np.mean(((X - p) @ m) ** 2)))
    return p, m / np.linalg.norm(m), rms


# ====================================================================== 기준 평면(SR-D-36)
def plate_refit(ix: MeshIndex, region: np.ndarray, floor: np.ndarray, par: np.ndarray, excl: np.ndarray, n_bar: np.ndarray,
                loop_nodes: np.ndarray, skip_nodes: np.ndarray, *, plate_tol: float, island_max: float,
                plane_rms: float) -> dict | None:
    """SR-D-36 기준 평면 다시 맞춤(첫 맞춤 잔차 > plane_rms 일 때 호출). region = 피처(비드) 요소 마스크, floor = 바닥 요소 마스크,
    par = 바닥 평균 법선에 평행한 요소, excl = 제외 요소, loop_nodes = 바깥 경계 고리 노드, skip_nodes = 맞춤에서 뺄 노드 마스크.
    판 묶음 = region 에 닿은 밖 평행 요소 높이 묶음(간격 > plate_tol) 중 최다(멈춤 요소의 절반 이상일 때만, 동률 = 바닥에서 먼 쪽 →
    앞). 다른 묶음 중 판에서 바닥 쪽 높이이고 판 평행 영역과 이어지지 않은(벽으로만 이어진) 평면 bbox > island_max 영역 = 교차하는
    다른 피처의 바닥(증거). 증거 없음 → None. 증거 있음 → 밖 요소가 모두 판 높이 평행 요소인 고리 노드로 맞춤:
    {status ok, p, m, rms, n_excluded} (rms ≤ plane_rms) | {status ambiguous, rms, n_plate}."""
    nb = np.unique(ix.adj[np.flatnonzero(region)].indices) if region.any() else np.zeros(0, np.int64)
    stop = nb[~region[nb] & ~excl[nb] & par[nb]]
    if stop.size < 3 or loop_nodes.size == 0:
        return None
    zc = ix.centroid @ n_bar
    zF = float(np.median(zc[floor]))
    o = np.argsort(zc[stop], kind="stable")
    zs = zc[stop][o]
    cut = np.flatnonzero(np.diff(zs) > plate_tol)
    groups = np.split(np.arange(zs.size), cut + 1)
    gi = max(range(len(groups)), key=lambda i: (groups[i].size, abs(float(np.median(zs[groups[i]])) - zF), -i))
    if 2 * groups[gi].size < zs.size:               # 판 높이가 하나로 안 정해짐(물결 판)
        return None
    zlo, zhi = float(zs[groups[gi]].min()), float(zs[groups[gi]].max())
    flat = ~region & ~excl & par
    fl = np.flatnonzero(flat)
    _nc, cl = csgraph.connected_components(ix.adj[fl][:, fl], directed=False)
    comp = np.full(ix.n_elems, -1, np.int64)
    comp[fl] = cl
    pc = set(np.unique(comp[stop[o][groups[gi]]]).tolist())
    zp = float(np.median(zs[groups[gi]]))
    evid = False
    for i, g in enumerate(groups):
        if i == gi or (float(np.median(zs[g])) - zp) * (zF - zp) <= 0:
            continue
        for c in sorted(set(np.unique(comp[stop[o][g]]).tolist()) - pc):
            kn = ix.elem_nodes(comp == c)
            if np.linalg.norm(ix.X[kn].max(axis=0) - ix.X[kn].min(axis=0)) > island_max:
                evid = True
                break
        if evid:
            break
    if not evid:
        return None
    plate = flat & (zc >= zlo - plate_tol) & (zc <= zhi + plate_tol)
    c_out = ix.node_count(~region)
    ok = (c_out > 0) & (c_out == ix.node_count(plate)) & ~skip_nodes
    keep = loop_nodes[ok[loop_nodes]]
    rms0 = None
    if keep.size >= 3:
        p, m, rms0 = plane_fit(ix.X[keep])
        if rms0 <= plane_rms:
            return {"status": "ok", "p": p, "m": m, "rms": rms0, "n_excluded": int(loop_nodes.size - keep.size)}
    return {"status": "ambiguous", "rms": rms0, "n_plate": int(keep.size)}


# ====================================================================== 안쪽 고리로 남은 피처(SR-D-37 b)
def stuck_features(ix: MeshIndex, region: np.ndarray, excl: np.ndarray, others: np.ndarray, floor_masks: list,
                   levels: list, p_b: np.ndarray, m_b: np.ndarray, e1: np.ndarray, e2: np.ndarray, *, plate_tol: float,
                   island_max: float, ring_frac: float) -> list[dict]:
    """region 밖 요소의 연결 성분 중 가장 큰 것(판) 밖 성분 R 마다, others·excl 요소 없음, 평면 bbox ≤ island_max, 가장 가까운
    바닥 단 높이 levels[k](기준면 깊이)에서 plate_tol 넘게 벗어나고 판 쪽으로 ring_frac·D 미만 → {k(1..), rim, interior, stuck 1}."""
    out_e = np.flatnonzero(~region)
    res: list[dict] = []
    if out_e.size == 0 or not floor_masks:
        return res
    X = ix.X
    _nc, lab = csgraph.connected_components(ix.adj[out_e][:, out_e], directed=False)
    size = np.bincount(lab)
    first = np.full(size.size, np.iinfo(np.int64).max)
    np.minimum.at(first, lab, out_e)
    order = np.argsort(first, kind="stable")
    big = int(order[np.argmax(size[order])])
    z = (X - p_b) @ m_b
    fnodes = [ix.elem_nodes(Fk) for Fk in floor_masks]
    trees = [cKDTree(X[fn]) if fn.size else None for fn in fnodes]
    for c in order.tolist():
        if c == big:
            continue
        R = out_e[lab == c]
        if others[R].any() or excl[R].any():
            continue
        rn = ix.elem_nodes(_mask_of(ix.n_elems, R))
        uv = np.column_stack([(X[rn] - p_b) @ e1, (X[rn] - p_b) @ e2])
        if float(np.linalg.norm(uv.max(axis=0) - uv.min(axis=0))) > island_max:
            continue
        dk = [float(t.query(X[rn], k=1)[0].min()) if t is not None else math.inf for t in trees]
        ki = int(np.argmin(dk))
        if not math.isfinite(dk[ki]):
            continue
        Dk = float(levels[ki])
        dz = z[rn] - Dk
        rise = float(np.max(-dz))
        if float(np.max(np.abs(dz))) <= plate_tol or (abs(Dk) > _EPS and rise >= ring_frac * abs(Dk)):
            continue
        dd, _ = cKDTree(X[rn]).query(X[fnodes[ki]], k=1)
        rim = fnodes[ki][dd <= float(dd.min()) + 2.0 * ix.h_med]
        res.append({"k": ki + 1, "rim": rim, "interior": rn, "stuck": 1})
    return res


def enclosed_features(ix: MeshIndex, too_large: list, floor_masks: list) -> list[dict]:
    """SR-D-37 a 섬이 못 된 둘러싸인 성분(enclosed_components ``too_large`` — elems·owner) → {k, rim(주인 바닥 노드), interior}."""
    res = []
    for t in too_large:
        kn = ix.elem_nodes(_mask_of(ix.n_elems, t["elems"]))
        fk = np.zeros(ix.n_nodes, bool)
        fk[ix.elem_nodes(floor_masks[int(t["owner"])])] = True
        if fk[kn].any() and (~fk[kn]).any():
            res.append({"k": int(t["owner"]) + 1, "rim": kn[fk[kn]], "interior": kn[~fk[kn]]})
    return res


# ====================================================================== 범위(SR-D-39)
def w_limits(ix: MeshIndex, items: list[dict]) -> list[tuple[int, dict]]:
    """SR-D-39b items[{id, W_nom, W_range[lo, hi] | None, tier_masks, p_b, e1, e2, boundary_nodes}] → [(item 순번, 경고)]."""
    out = []
    h = ix.h_med
    for bi, b in enumerate(items):
        if b.get("W_range") is None or b.get("W_nom") is None:
            continue
        lo, hi = b["W_range"]
        mv = max(abs(float(hi) - b["W_nom"]), abs(b["W_nom"] - float(lo))) / 2.0
        tm = b["tier_masks"]
        if len(tm) >= 2:
            gaps = []
            for m0, m1 in zip(tm[:-1], tm[1:]):
                a, c = ix.elem_nodes(m0), ix.elem_nodes(m1)
                if a.size and c.size:
                    P = ix.X - b["p_b"]
                    pa = np.column_stack([P[a] @ b["e1"], P[a] @ b["e2"]])
                    pc = np.column_stack([P[c] @ b["e1"], P[c] @ b["e2"]])
                    d, _ = cKDTree(pa).query(pc, k=1)
                    edge = d[d > 1e-9]
                    if edge.size:
                        gaps.append(float(np.min(edge)))
            if gaps and mv > min(gaps):
                out.append((bi, {"code": "SELECT_W_RANGE_LIMIT", "by": "tier", "move_mm": _r(mv), "lim_mm": _r(min(gaps))}))
        for o in items:
            if o is b or not o["boundary_nodes"].size or not b["boundary_nodes"].size:
                continue
            d, _ = cKDTree(ix.X[o["boundary_nodes"]]).query(ix.X[b["boundary_nodes"]], k=1)
            dm = float(d.min())
            if dm <= h:                                # 맞닿음(교차) = 네트워크 경고 몫
                continue
            if mv > 0.5 * dm:
                out.append((bi, {"code": "SELECT_W_RANGE_LIMIT", "by": "neighbor", "with": o["id"], "move_mm": _r(mv),
                                 "lim_mm": _r(0.5 * dm)}))
    return out


def inverted_any(mesh: dict, x0: np.ndarray, x: np.ndarray, flip_deg: float) -> bool:
    """안 좌표 x 의 뒤집힘(``design_state`` 와 같은 식 — 영향 요소의 야코비안 ≤ 0 ∨ 법선 각 > flip_deg) 여부."""
    from esl.doe import mesh_quality as mq
    u = np.linalg.norm(np.asarray(x) - np.asarray(x0), axis=1) > U_EPS
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    am = u[C[:, 0]] | u[C[:, 1]] | u[C[:, 2]]
    q = et == 4
    am[q] |= u[C[q, 3]]
    return mq.inverted_count(x0, x, C, et, np.flatnonzero(am), flip_deg=flip_deg) > 0


def range_combo(ends: list, inverted_fn, m: int, steps: int) -> dict | None:
    """SR-D-39 조합 검증: ends[(var, nominal, usable_lo, usable_hi)], inverted_fn(values) → bool. 모서리 표본(변수 n ≤ log2 m 이면
    2^n 전부, 아니면 시드 0 난수 m 개)에서 뒤집힘이 있으면 공칭 쪽 공통 비율 s 를 steps 회 이분 → SELECT_RANGE_COMBO 경고 | None."""
    if m <= 0 or len(ends) < 2:
        return None
    n = len(ends)
    if n <= int(math.floor(math.log2(m))):
        bits = np.array([[(i >> j) & 1 for j in range(n)] for i in range(2 ** n)], np.int8)
    else:
        bits = np.random.default_rng(0).integers(0, 2, size=(m, n), dtype=np.int8)

    def n_bad(sc_: float, first: bool = False) -> int:
        k = 0
        for row in bits:
            vals = {nm: nom + sc_ * ((hi if bt else lo) - nom) for (nm, nom, lo, hi), bt in zip(ends, row)}
            k += int(inverted_fn(vals))
            if first and k:
                break
        return k
    k1 = n_bad(1.0)
    if not k1:
        return None
    a, b = 0.0, 1.0
    for _ in range(max(int(steps), 1)):
        mid = 0.5 * (a + b)
        if n_bad(mid, first=True):
            b = mid
        else:
            a = mid
    return {"code": "SELECT_RANGE_COMBO", "vars": [e[0] for e in ends], "corners": int(bits.shape[0]), "inverted_n": int(k1),
            "scale": _r(a), "usable": {nm: [_r(nom + a * (lo - nom)), _r(nom + a * (hi - nom))] for nm, nom, lo, hi in ends}}


# ====================================================================== 안 판정 보조(SR-D-37·38·40)
def cross_footprint(vars_: list[dict], regions: dict) -> list[dict]:
    """SR-D-38 W 변수(vars_[{name, type, bead, nominal, idx, vec}])의 기저가 다른 피처 regions[bead](경계·바닥 노드)에 주는
    ‖B‖ > 0 노드·크기 → [{var, bead, other, nominal, idx, mag}] (자기 영역 노드 제외)."""
    cross = []
    for v in vars_:
        if v["type"] != "W":
            continue
        idx = np.asarray(v["idx"]).astype(np.int64)
        mag = np.linalg.norm(v["vec"], axis=1)
        own = regions.get(v["bead"], np.zeros(0, np.int64))
        for bid, reg in regions.items():
            if bid == v["bead"]:
                continue
            hit = np.isin(idx, reg) & ~np.isin(idx, own) & (mag > 0)
            if hit.any():
                cross.append({"var": v["name"], "bead": v["bead"], "other": bid, "nominal": float(v["nominal"]),
                              "idx": idx[hit], "mag": mag[hit]})
    return cross


def post_morph_warnings(mesh: dict, x0, x, qc: dict, *, flip_deg: float) -> list[dict]:
    """메시 출처·모핑 방식과 무관한 안 좌표 사후 점검(자동 탐지 기본 모핑 등 외부 모핑 결과): 영향 요소 극단값(SR-D-40)만 —
    뒤집힘 요소는 극단값 계산에서 빼지 않음. 해당 없으면 [] (기존 결과 바이트 불변)."""
    from esl.doe import mesh_quality as mq
    x0 = np.asarray(x0, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    u = np.linalg.norm(x - x0, axis=1) > U_EPS
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    am = u[C[:, 0]] | u[C[:, 1]] | u[C[:, 2]]
    am[et == 4] |= u[C[et == 4, 3]]
    if not am.any():
        return []
    idx = np.flatnonzero(am)
    n0 = mq._elem_normals(x0, C[idx], et[idx])
    n1 = mq._elem_normals(x, C[idx], et[idx])
    rot = float(np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n0, n1), -1.0, 1.0))).max())
    e = extremes(mesh, x0, x, am, {"max_flip_deg": min(rot, float(flip_deg))}, qc)
    return [{"code": "MORPH_EXTREME_ELEMENTS", **e}] if e else []


def bridge_holes(ix: MeshIndex, loops: list[dict], holes: list[dict], *, max_d_mm: float | None = None,
                 skipped: list | None = None) -> list[dict]:
    """SR-D-35 경계 고리를 끊는 구멍(경계 노드에 닿는 관통 구멍 — 비드 벽을 가로지르는 슬롯) 건너 잇기: 열린 고리의 끝점이
    구멍 자유 모서리 노드면 같은 구멍에 끝점이 있는 열린 고리(자기 자신 포함, 평면 거리 가까운 쪽 — 동률 = 앞 고리)와 이어 붙인다
    (구멍을 가로지르는 가상 선분 1개). 자기 자신과 이어지면 닫힌 고리(``bridged`` = 건넌 구멍 수). 구멍이 없으면 입력 그대로.
    AD-D-7 상한: ``max_d_mm`` 가 있으면 등가 지름(``eq_d_mm``) > max_d_mm 인 구멍은 건너 잇지 않고(고리는 열린 채) ``skipped`` 에
    {code SELECT_BRIDGE_SKIPPED, eq_d_mm, gap_mm}(gap = 건너 이었을 끝점 사이 거리, 구멍마다 1번)을 더한다. 상한 이하 구멍만이면
    v0.16.1 과 같은 결과(바이트 불변)."""
    if not holes or all(lp["closed"] for lp in loops):
        return loops
    big = set()
    if max_d_mm is not None:
        big = {k for k, hl in enumerate(holes) if float(hl.get("eq_d_mm") or 0.0) > float(max_d_mm)}
    seen_big: set = set()
    blocked: set = set()                                 # 큰 구멍에 닿은 끝점(건너 잇지 않음)
    hid = {}
    for k, hl in enumerate(holes):
        for v in np.asarray(hl.get("all_nodes", hl["nodes"])).tolist():
            hid.setdefault(int(v), k)
    X = ix.X
    out = [dict(lp) for lp in loops]
    for lp in out:
        lp.setdefault("bridged", 0)
    changed = True
    while changed:
        changed = False
        for i, lp in enumerate(out):
            if lp["closed"]:
                continue
            end = int(lp["nodes"][-1])
            h = None if end in blocked else hid.get(end)
            if h is None:
                lp["nodes"] = lp["nodes"][::-1]          # 반대쪽 끝이 구멍에 닿으면 뒤집어 다시
                end = int(lp["nodes"][-1])
                h = None if end in blocked else hid.get(end)
                if h is None:
                    continue
            best = None
            for j, lq in enumerate(out):
                if lq["closed"] or lq.get("_gone"):
                    continue
                for side in (0, -1):
                    v = int(lq["nodes"][side])
                    if hid.get(v) != h or (j == i and side == -1):
                        continue
                    d = float(np.linalg.norm(X[v] - X[end]))
                    if best is None or d < best[0] - 1e-12:
                        best = (d, j, side)
            if best is None:
                continue
            _d, j, side = best
            if h in big:                                 # AD-D-7: 큰 개구는 건너 잇지 않음(경고 1번)
                if h not in seen_big:
                    seen_big.add(h)
                    if skipped is not None:
                        skipped.append({"code": "SELECT_BRIDGE_SKIPPED", "eq_d_mm": _r(holes[h].get("eq_d_mm")),
                                        "gap_mm": _r(_d)})
                blocked.add(end)
                changed = True
                break
            if j == i:
                lp["closed"] = True
                lp["bridged"] += 1
            else:
                lq = out[j]
                nxt = lq["nodes"] if side == 0 else lq["nodes"][::-1]
                lp["nodes"] = np.concatenate([lp["nodes"], nxt])
                lp["bridged"] += 1 + lq["bridged"]
                lq["_gone"] = True
            changed = True
            break
        out = [lp for lp in out if not lp.get("_gone")]
    return out

def extremes(mesh: dict, x0, x, am: np.ndarray, q: dict, qc: dict) -> dict | None:
    """SR-D-40 요소별 극단값: 영향 요소의 넓이 비(안/공칭) 최소 < area_ratio_min 또는 법선 회전 최대 > rot_warn_deg(뒤집힘
    flip_deg 이하 구간) → {area_ratio_min, rot_max_deg}, 아니면 None(키가 없거나 0 이면 그 조건 끔)."""
    a_min = float(qc.get("area_ratio_min") or 0.0)
    r_max = float(qc.get("rot_warn_deg") or 0.0)
    idx = np.flatnonzero(am)
    if idx.size == 0 or (a_min <= 0 and r_max <= 0):
        return None
    C = np.asarray(mesh["conn"], dtype=np.int64)[idx]
    et = np.asarray(mesh["elem_type"]).astype(np.int64)[idx]

    def area(X):
        X = np.asarray(X, dtype=np.float64)
        a, b, c = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        w = np.cross(b - a, c - a)
        qd = et == 4
        if qd.any():
            d = X[C[qd, 3]]
            w[qd] = np.cross(c[qd] - a[qd], d - b[qd])
        return 0.5 * np.linalg.norm(w, axis=1)
    ar = float(np.min(area(x) / np.maximum(area(x0), 1e-300)))
    rot = float(q.get("max_flip_deg") or 0.0)
    if (a_min > 0 and ar < a_min) or (r_max > 0 and rot > r_max):
        return {"area_ratio_min": _r(ar), "rot_max_deg": _r(rot, 2)}
    return None

def feature_distortion(x0, x, checks: dict, qc: dict) -> dict | None:
    """SR-D-37 비드 안 비선택 피처(섬이 못 된 둘러싸인 성분 — 섬 크기·다각형 조건 탈락) 강체성: u = x − x0, t = mean u(둘레),
    dev = max ‖u(내부) − t‖ > max(distort_min_mm, distort_rel·‖t‖) 이면 {code SELECT_FEATURE_DISTORTED, bead, k, dev_mm, floor_mm}
    (dev 최대 피처), 아니면 None."""
    feats = checks.get("features") or []
    if not feats:
        return None
    u = np.asarray(x, dtype=np.float64) - np.asarray(x0, dtype=np.float64)
    qd = _quality_cfg(qc)
    rel, mn = float(qd["distort_rel"]), float(qd["distort_min_mm"])
    worst = None
    for f in feats:
        if f["rim"].size == 0 or f["interior"].size == 0:
            continue
        t = u[f["rim"]].mean(axis=0)
        dev = float(np.max(np.linalg.norm(u[f["interior"]] - t, axis=1)))
        mv = float(np.linalg.norm(t))
        if dev > max(mn, rel * mv) and (worst is None or dev > worst["dev_mm"]):
            worst = {"code": "SELECT_FEATURE_DISTORTED", "bead": f["bead"], "k": int(f["k"]), "dev_mm": _r(dev),
                     "floor_mm": _r(mv)}
    return worst

def cross_move(checks: dict, values: dict, tol: float) -> dict | None:
    """SR-D-38 한 비드의 W 변화가 다른 선택 비드의 경계·바닥 노드를 움직인 양: 항목(W 변수 v, 다른 비드 b)마다 |Δv|·‖B_v‖ > tol
    인 노드 수·최대 → {code SELECT_CROSS_BEAD_MOVE, n, max_mm, beads[[v, b], …]}(합), 없으면 None."""
    n, mx, pairs = 0, 0.0, []
    for c in checks.get("cross") or []:
        if c["var"] not in values:
            continue
        dv = abs(float(values[c["var"]]) - float(c["nominal"]))
        if dv == 0.0 or c["mag"].size == 0:
            continue
        m = dv * c["mag"]
        k = int(np.sum(m > tol))
        if k:
            n += k
            mx = max(mx, float(m.max()))
            pairs.append([c["var"], c["other"]])
    if not n:
        return None
    return {"code": "SELECT_CROSS_BEAD_MOVE", "n": n, "max_mm": _r(mx), "beads": pairs}

def outside_moved(x0, x, allowed, changed, tol: float) -> dict | None:
    """v0.17.0 BG-D-34 바깥 이동: 바뀐 변수들의 허용 노드 합 A 밖 노드의 최대 이동 > tol 이면
    {code BG_OUTSIDE_MOVED, n, max_mm, vars} (안 판정 FAILED_MESH — 정책 무관), 아니면 None.
    allowed = [{var, nominal, zone(노드 index) | mask(bool)}], changed = 값 dict(공칭과 다른 변수만) 또는 변수 이름 목록."""
    x0 = np.asarray(x0, dtype=np.float64)
    if isinstance(changed, dict):
        names = {a["var"] for a in allowed if a["var"] in changed and float(changed[a["var"]]) != float(a.get("nominal",
                                                                                                          np.nan))}
    else:
        names = set(changed)
    if not names:
        return None
    ok = np.zeros(x0.shape[0], bool)
    for a in allowed:
        if a["var"] in names:
            if "mask" in a:
                ok |= np.asarray(a["mask"], bool)
            else:
                ok[np.asarray(a["zone"], np.int64)] = True
    d = np.linalg.norm(np.asarray(x, dtype=np.float64) - x0, axis=1)
    d[ok] = 0.0
    n = int(np.sum(d > tol))
    if not n:
        return None
    return {"code": "BG_OUTSIDE_MOVED", "n": n, "max_mm": _r(float(d.max()), 6), "vars": sorted(names)}


def checks_arrays(checks: dict) -> dict:
    """design_checks → npz 배열(키 chk_*; 비면 빈 dict — derived.npz 바이트 불변). v0.17.0: chk_o<i>_bits = 변수별 허용 노드
    마스크 비트열(np.packbits) + chk_o<i>_meta {var, nominal, n} — 그래프 기저가 있을 때만(schema 1 키 없음)."""
    arr = {}
    for i, o in enumerate(checks.get("outside") or []):
        n = int(o["n"]) if "n" in o else None
        zone = np.asarray(o["zone"], np.int64)
        nn = n if n is not None else int(o.get("n_nodes", 0))
        mask = np.zeros(nn, bool)
        mask[zone] = True
        arr[f"chk_o{i}_bits"] = np.packbits(mask)
        arr[f"chk_o{i}_meta"] = np.frombuffer(json.dumps({"var": o["var"], "nominal": o["nominal"], "n": nn}).encode(),
                                              np.uint8)
    for i, f in enumerate(checks.get("features") or []):
        arr[f"chk_f{i}_rim"] = f["rim"].astype(np.int64)
        arr[f"chk_f{i}_int"] = f["interior"].astype(np.int64)
        arr[f"chk_f{i}_meta"] = np.frombuffer(json.dumps({"bead": f["bead"], "k": f["k"]}).encode(), np.uint8)
    for i, c in enumerate(checks.get("cross") or []):
        arr[f"chk_c{i}_idx"] = c["idx"].astype(np.int64)
        arr[f"chk_c{i}_mag"] = c["mag"].astype(np.float64)
        arr[f"chk_c{i}_meta"] = np.frombuffer(json.dumps({k: c[k] for k in ("var", "bead", "other", "nominal")}).encode(),
                                              np.uint8)
    return arr

def checks_from_arrays(z) -> dict:
    """checks_arrays 의 역(키가 없으면 {})."""
    out: dict = {}
    keys = sorted(k for k in z if k.startswith("chk_"))
    oi = sorted({int(k.split("_")[1][1:]) for k in keys if k.startswith("chk_o")})
    if oi:
        out["outside"] = []
        for i in oi:
            meta = json.loads(bytes(np.asarray(z[f"chk_o{i}_meta"], np.uint8)).decode())
            m = np.unpackbits(np.asarray(z[f"chk_o{i}_bits"], np.uint8))[:meta["n"]].astype(bool)
            out["outside"].append({"var": meta["var"], "nominal": meta["nominal"], "zone": np.flatnonzero(m)})
    fi = sorted({int(k.split("_")[1][1:]) for k in keys if k.startswith("chk_f")})
    ci = sorted({int(k.split("_")[1][1:]) for k in keys if k.startswith("chk_c")})
    if fi:
        out["features"] = [{**json.loads(bytes(np.asarray(z[f"chk_f{i}_meta"], np.uint8)).decode()),
                            "rim": np.asarray(z[f"chk_f{i}_rim"], np.int64), "interior": np.asarray(z[f"chk_f{i}_int"], np.int64)}
                           for i in fi]
    if ci:
        out["cross"] = [{**json.loads(bytes(np.asarray(z[f"chk_c{i}_meta"], np.uint8)).decode()),
                         "idx": np.asarray(z[f"chk_c{i}_idx"], np.int64), "mag": np.asarray(z[f"chk_c{i}_mag"], np.float64)}
                        for i in ci]
    return out
