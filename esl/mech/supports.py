"""지지점 선택 (계약 esl_core.md §4, esl.md §6.6).

pca_corners: 초기좌표 PCA 평면에서 정규화 투영 (â, b̂) 의 4방향 극점.
pick_321: 후보 중 삼각형 면적 최대 3점 → 3-2-1 정정 구속(강체 6모드만 구속).
auto_321 (v0.10.0, esl_menu_restructure.md §5.2): pca4(= pick_321 과 같은 결과) → 품질 검사(공선·근접·조건비) →
  실패 시 후보 8개(4꼭지점 + a·b 단독 극점) 조합 재탐색(pca8). check_321: 수동 3노드에 같은 검사(후보 확장 없음).
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

from esl.errors import EslError

_SIGNS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
DEGENERATE_RATIO = 1e-6


def _orient(v):
    """부호 규약: 절대값 최대 성분이 양수."""
    return v if v[np.argmax(np.abs(v))] >= 0 else -v


def pca_corners(X0):
    X0 = np.asarray(X0, dtype=np.float64)
    if X0.ndim != 2 or X0.shape[1] != 3 or X0.shape[0] < 4:
        raise EslError("SUPPORT_DEGENERATE", "PCA 꼭지점: 노드 4개 이상 필요")
    o = X0.mean(axis=0)
    P = X0 - o
    _, s, Vt = np.linalg.svd(P, full_matrices=False)
    if s[1] <= DEGENERATE_RATIO * s[0]:
        raise EslError("SUPPORT_DEGENERATE", "노드가 공선 — 면내 주축 2개를 정할 수 없음")
    e1 = _orient(Vt[0])
    e2 = _orient(Vt[1])
    n = np.cross(e1, e2)
    a = P @ e1
    b = P @ e2

    def norm(v):
        lo, hi = v.min(), v.max()
        return 2.0 * (v - lo) / (hi - lo) - 1.0

    ah, bh = norm(a), norm(b)
    idx: list[int] = []
    for s1, s2 in _SIGNS:
        score = s1 * ah + s2 * bh
        order = np.lexsort((np.arange(score.size), -score))   # 내림차순, 동률은 낮은 인덱스
        for k in order:
            if int(k) not in idx:
                idx.append(int(k))
                break
    return {
        "idx": idx,
        "plane": {"origin": o.tolist(), "e1": e1.tolist(), "e2": e2.tolist(), "n": n.tolist()},
    }


def _rigid_matrix(X, assign):
    """구속 dof 행 × 강체 6모드 열(병진 3, 중심 기준 회전 3 / 길이 L 무차원화)."""
    ctr = X.mean(axis=0)
    L = max(float(np.max(np.linalg.norm(X - ctr, axis=1))), 1e-300)
    rows = []
    for p, dofs in zip(X, assign):
        r = (p - ctr) / L
        for d in dofs:
            row = np.zeros(6)
            row[d] = 1.0
            for i in range(3):
                w = np.zeros(3)
                w[i] = 1.0
                row[3 + i] = np.cross(w, r)[d]
            rows.append(row)
    return np.array(rows)


def _tri_area(p) -> float:
    return float(0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])))


def _best_triangle(X0, uniq):
    """후보(순서 유지) 3점 조합 중 면적 최대(동률은 앞 조합) → 노드 3개(후보 순서)."""
    best, best_area = None, -1.0
    for tri in combinations(range(len(uniq)), 3):
        area = _tri_area(X0[[uniq[i] for i in tri]])
        if area > best_area * (1 + 1e-12):
            best, best_area = tri, area
    return [uniq[i] for i in best]


def _assign_dofs(X):
    """3점(순서 고정) → ((2성분 축), 1성분 축, σmin/σmax 최대값)."""
    best_combo, best_ratio = None, -1.0
    for k2 in range(3):                 # 둘째 점: 축 k2 를 뺀 2성분
        two = tuple(d for d in range(3) if d != k2)
        for k3 in range(3):             # 셋째 점: 1성분
            A = _rigid_matrix(X, [(0, 1, 2), two, (k3,)])
            s = np.linalg.svd(A, compute_uv=False)
            ratio = s[-1] / s[0]
            if ratio > best_ratio * (1 + 1e-12):
                best_combo, best_ratio = (two, k3), ratio
    return best_combo[0], best_combo[1], float(best_ratio)


def _dof_list(nodes, two, k3):
    return [(nodes[0], "123"), (nodes[1], "".join(str(d + 1) for d in two)), (nodes[2], str(k3 + 1))]


def pick_321(X0, cand_idx):
    """→ [(node_idx, "123"), (node_idx, "ij"), (node_idx, "k")] (dof 는 1-based 문자열)."""
    X0 = np.asarray(X0, dtype=np.float64)
    cand = [int(c) for c in cand_idx]
    if len(set(cand)) < 3:
        raise EslError("SUPPORT_DEGENERATE", f"지지 후보 {len(set(cand))}개 < 3")
    if min(cand) < 0 or max(cand) >= X0.shape[0]:
        raise EslError("INPUT_INVALID", "지지 후보 인덱스 범위 밖")
    uniq = list(dict.fromkeys(cand))
    nodes = _best_triangle(X0, uniq)
    two, k3, best_ratio = _assign_dofs(X0[nodes])
    if best_ratio < DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 구속행렬 특이 (σmin/σmax={best_ratio:.2e}, 후보 공선?)")
    return _dof_list(nodes, two, k3)


# ---------------------------------------------------------------- v0.10.0 자동 선택 + 품질 검사(§5.2)
def _check_cfg(cfg) -> dict:
    from esl.config import SUPPORT_CHECK_DEFAULTS

    out = dict(SUPPORT_CHECK_DEFAULTS)
    if isinstance(cfg, dict):
        out.update({k: v for k, v in cfg.items() if k in SUPPORT_CHECK_DEFAULTS})
    return out


def _fmt(v) -> str:
    v = float(v)
    return f"{v:.2f}" if abs(v) >= 0.01 else f"{v:.0e}"


def _plane_extent(X0, plane):
    o, e1, e2 = (np.asarray(plane[k], dtype=np.float64) for k in ("origin", "e1", "e2"))
    a = (X0 - o) @ e1
    b = (X0 - o) @ e2
    La, Lb = float(a.max() - a.min()), float(b.max() - b.min())
    return a, b, La, Lb, float(np.hypot(La, Lb))


def _evaluate(X0, nodes, La, Lb, D, c):
    """3점(순서 고정) 검사 → (checks, problems, dofs|None)."""
    P = X0[list(nodes)]
    area = _tri_area(P)
    area_ratio = area / (0.5 * La * Lb) if La > 0 and Lb > 0 else 0.0
    dmin = min(float(np.linalg.norm(P[i] - P[j])) for i, j in ((0, 1), (0, 2), (1, 2)))
    min_dist_rel = dmin / D if D > 0 else 0.0
    two, k3, cond = _assign_dofs(P)
    checks = {"area_ratio": float(area_ratio), "min_dist_rel": float(min_dist_rel), "cond_ratio": float(cond)}
    probs = []
    if cond < DEGENERATE_RATIO:
        probs.append({"code": "SUPPORT_DEGENERATE",
                      "message": f"3-2-1 구속을 정할 수 없습니다(조건비 {cond:.1e} — 세 점이 한 줄)",
                      "value": float(cond), "limit": DEGENERATE_RATIO})
    lim = float(c["min_area_ratio"])
    if area_ratio < lim:
        probs.append({"code": "SUPPORT_COLLINEAR",
                      "message": f"지지 3점이 거의 한 줄입니다(면적비 {_fmt(area_ratio)} < {_fmt(lim)})",
                      "value": float(area_ratio), "limit": lim})
    lim = float(c["min_dist_rel"])
    if min_dist_rel < lim:
        probs.append({"code": "SUPPORT_TOO_CLOSE",
                      "message": f"지지 두 점이 너무 가깝습니다(거리 {_fmt(min_dist_rel)}·대각선 < {_fmt(lim)})",
                      "value": float(min_dist_rel), "limit": lim})
    lim = float(c["min_cond_ratio"])
    if DEGENERATE_RATIO <= cond < lim:
        probs.append({"code": "SUPPORT_ILL_CONDITIONED",
                      "message": f"지지 구속이 약합니다(조건비 {_fmt(cond)} < {_fmt(lim)})",
                      "value": float(cond), "limit": lim})
    dofs = [d for _, d in _dof_list(list(nodes), two, k3)] if cond >= DEGENERATE_RATIO else None
    return checks, probs, dofs


def _blocked_degenerate(message: str, rule_version: int, mode: str) -> dict:
    return {"status": "BLOCKED", "mode": mode, "idx": [], "dofs": [], "plane": None, "corners": [],
            "checks": None, "rule_version": int(rule_version),
            "problems": [{"code": "SUPPORT_DEGENERATE", "message": f"지지점을 정할 수 없습니다({message})",
                          "value": None, "limit": None}]}


def auto_321(X0, cfg=None) -> dict:
    """3-2-1 자동 선택(순수 함수, 결정적). cfg = support.auto_check(없으면 SUPPORT_CHECK_DEFAULTS).

    → {status OK|BLOCKED, mode pca4|pca8, idx[3], dofs[3], plane, corners, checks{area_ratio, min_dist_rel, cond_ratio},
       problems[{code, message, value, limit}], rule_version}. pca4 가 통과하면 idx·dofs 는 pick_321(corners) 와 같다.
       BLOCKED 의 idx·checks 는 pca4 삼각형의 것(표시용), problems = pca4 실패 검사 (+ 확장 시 SUPPORT_NO_VALID_CANDIDATE).
    """
    c = _check_cfg(cfg)
    rv = int(c["rule_version"])
    X0 = np.asarray(X0, dtype=np.float64)
    try:
        pc = pca_corners(X0)
    except EslError as exc:
        return _blocked_degenerate(exc.message, rv, "pca4")
    corners = [int(i) for i in pc["idx"]]
    if len(set(corners)) < 3:
        return {**_blocked_degenerate(f"지지 후보 {len(set(corners))}개 < 3", rv, "pca4"),
                "plane": pc["plane"], "corners": corners}
    a, b, La, Lb, D = _plane_extent(X0, pc["plane"])
    nodes = _best_triangle(X0, list(dict.fromkeys(corners)))
    checks, probs, dofs = _evaluate(X0, nodes, La, Lb, D, c)
    out = {"status": "OK", "mode": "pca4", "idx": [int(i) for i in nodes], "dofs": dofs or [], "plane": pc["plane"],
           "corners": corners, "checks": checks, "problems": [], "rule_version": rv}
    if not probs:
        return out
    if not c["expand_candidates"]:
        return {**out, "status": "BLOCKED", "problems": probs}
    ext = [int(np.argmax(a)), int(np.argmin(a)), int(np.argmax(b)), int(np.argmin(b))]
    cand = list(dict.fromkeys(corners + ext))
    best, best_area = None, -1.0
    for tri in combinations(range(len(cand)), 3):
        nd = [cand[i] for i in tri]
        ck, pr, dd = _evaluate(X0, nd, La, Lb, D, c)
        if pr:
            continue
        area = _tri_area(X0[nd])
        if area > best_area * (1 + 1e-12):
            best, best_area = (nd, ck, dd), area
    if best is not None:
        nd, ck, dd = best
        return {**out, "mode": "pca8", "idx": [int(i) for i in nd], "dofs": dd, "checks": ck}
    probs = probs + [{"code": "SUPPORT_NO_VALID_CANDIDATE", "message": f"후보 {len(cand)}개 조합 중 통과 없음",
                      "value": None, "limit": None}]
    return {**out, "status": "BLOCKED", "mode": "pca8", "problems": probs}


def check_321(X0, idx, cfg=None) -> dict:
    """수동 지정 3노드(순서 = 1번 3방향 / 2번 2방향 / 3번 1방향)에 auto_321 과 같은 검사(후보 확장 없음).

    → {status OK|BLOCKED, mode "manual", idx, dofs, plane, corners, checks, problems, rule_version}.
    dofs 는 pick_321(X0, idx) 와 같다(3점이면 삼각형이 하나뿐이고 순서 유지).
    """
    c = _check_cfg(cfg)
    rv = int(c["rule_version"])
    X0 = np.asarray(X0, dtype=np.float64)
    nodes = [int(i) for i in idx]
    if len(nodes) != 3 or len(set(nodes)) != 3:
        raise EslError("INPUT_INVALID", "지지 노드는 서로 다른 3개")
    if min(nodes) < 0 or max(nodes) >= X0.shape[0]:
        raise EslError("INPUT_INVALID", "지지 노드 인덱스 범위 밖")
    try:
        pc = pca_corners(X0)
    except EslError as exc:
        return {**_blocked_degenerate(exc.message, rv, "manual"), "idx": nodes}
    _, _, La, Lb, D = _plane_extent(X0, pc["plane"])
    checks, probs, dofs = _evaluate(X0, nodes, La, Lb, D, c)
    return {"status": "BLOCKED" if probs else "OK", "mode": "manual", "idx": nodes, "dofs": dofs or [],
            "plane": pc["plane"], "corners": [int(i) for i in pc["idx"]], "checks": checks, "problems": probs,
            "rule_version": rv}
