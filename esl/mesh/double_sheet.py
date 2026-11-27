"""판 앞뒷면 두 장 감지 — 메시로(계약 esl_tstar_manual_jig_force.md §4.4, D-0.25.2-17·18).

STEP 이 중립면 한 장이 아니라 판 앞뒷면 표면 두 장이면 마주 보는 평행 요소가 두께쯤 간격으로 짝을 이룬다. 요소를 인덱스 등간격으로
최대 ``sample_max`` 개 뽑아(결정적) 표본 요소(중심 c, 단위 법선 n, 변 길이 h)마다 짝(다른 요소 중 ① |n·n′| ≥ cos(normal_deg)
② 법선 방향 간격 g = |(c′−c)·n| ∈ [gap_min_t·t, gap_max_t·t] ③ 면내 어긋남 ‖(c′−c) − ((c′−c)·n)·n‖ ≤ h)이 있는 비율 ``frac`` 과
짝 간격(표본마다 가장 가까운 짝) 중앙값 ``gap_mm`` 을 낸다. 리브·헤밍처럼 일부만 겹친 형상은 frac 이 작다. 판정(frac ≥ frac_warn →
SHAPE_DOUBLE_SHEET)은 호출부.

모드 무관 독립 순수 모듈(AGENTS.md D-0.20.0-CODE): numpy·scipy.spatial 만, esl.doe 금지, 파일 IO·설정 해석 없음(값은 인수).
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from esl.errors import EslError


def _elem_geom(mesh: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """요소 중심 (E,3)·단위 법선 (E,3)(면적 0 = 0 벡터)·변 길이 최대 (E,). 쿼드 = 대각선 외적, 삼각 = 두 변 외적."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    q = et == 4
    c0, c1, c2 = X[conn[:, 0]], X[conn[:, 1]], X[conn[:, 2]]
    c3 = np.where(q[:, None], X[np.maximum(conn[:, 3], 0)], c2)
    cen = np.where(q[:, None], (c0 + c1 + c2 + c3) / 4.0, (c0 + c1 + c2) / 3.0)
    nrm = np.where(q[:, None], np.cross(c2 - c0, c3 - c1), np.cross(c1 - c0, c2 - c0))
    ln = np.linalg.norm(nrm, axis=1)
    n = np.divide(nrm, ln[:, None], out=np.zeros_like(nrm), where=ln[:, None] > 0)
    e = [np.linalg.norm(c1 - c0, axis=1), np.linalg.norm(c2 - c1, axis=1)]
    e += [np.where(q, np.linalg.norm(c3 - c2, axis=1), np.linalg.norm(c0 - c2, axis=1)),
          np.where(q, np.linalg.norm(c0 - c3, axis=1), 0.0)]
    return cen, n, np.max(np.stack(e, axis=1), axis=1)


def detect(mesh: dict, t: float, *, gap_min_t: float, gap_max_t: float, normal_deg: float, sample_max: int) -> dict:
    """mesh = {x0 (N,3), conn (E,4)(삼각형 4번째 = 음수), elem_type (E,)(4 = 쿼드, 3 = 삼각)}, t = 판 두께(mm — 호출부가 형상 두께
    대표값). 반환 {frac, gap_mm(짝 간격 중앙값 — 짝 0 = None), n_sample}. 요소 0 = frac 0."""
    tt = float(t)
    if not np.isfinite(tt) or tt <= 0:
        raise EslError("INPUT_INVALID", f"두께 t = {t!r} ≤ 0")
    lo, hi = float(gap_min_t) * tt, float(gap_max_t) * tt
    if not (0.0 <= lo < hi):
        raise EslError("INPUT_INVALID", f"간격 범위 [{lo:g}, {hi:g}]")
    cen, n, h = _elem_geom(mesh)
    E = cen.shape[0]
    if E == 0 or int(sample_max) < 1:
        return {"frac": 0.0, "gap_mm": None, "n_sample": 0}
    ns = min(int(sample_max), E)
    samp = np.unique(np.round(np.linspace(0, E - 1, ns)).astype(np.int64))      # 인덱스 등간격(결정적)
    cosv = float(np.cos(np.radians(float(normal_deg))))
    tree = cKDTree(cen)
    hmax = float(h.max())
    balls = tree.query_ball_point(cen[samp], float(np.hypot(hi, hmax)) + 1e-9)
    found = np.zeros(samp.size, bool)
    gaps = np.full(samp.size, np.inf)
    for k, (i, nb) in enumerate(zip(samp.tolist(), balls)):
        j = np.asarray([x for x in nb if x != i], dtype=np.int64)
        if j.size == 0 or not np.any(n[i]):
            continue
        d = cen[j] - cen[i]
        g = d @ n[i]
        ag = np.abs(g)
        par = np.abs(n[j] @ n[i]) >= cosv
        off = np.linalg.norm(d - g[:, None] * n[i][None, :], axis=1)
        ok = par & (ag >= lo) & (ag <= hi) & (off <= h[i])
        if ok.any():
            found[k] = True
            gaps[k] = float(ag[ok].min())
    nf = int(found.sum())
    return {"frac": nf / samp.size, "gap_mm": float(np.median(gaps[found])) if nf else None, "n_sample": int(samp.size)}
