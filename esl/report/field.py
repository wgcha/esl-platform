"""ESL 재현 정확도 전 요소 비교 (계약 esl_p2_library.md §7.1·§7.2) — 순수 함수.

- ``rising_mask``: t* 에서 "상승 중"인 요소 ``v[f] > v[f−1]·(1+rtol)`` (f=0 이면 ``v > 0``). max-hold 값은 상승 중일
  때만 순간값과 같다 → 상승 중이 아닌 요소는 비교 불가(사유 HOLD).
- ``classify``: valid = 상승 중 ∧ ε_rad ≥ min_rel·max ε_rad(상승 요소) ∧ 제외 아님, 사유 코드(i1).
- ``summarize``: 최대변형률 비교, |오차| 분위수·비율, 상위 N, 히스토그램.
- ``plane_coords``·``elem_mean``·``section``: PCA 평면 (ξ, η) 실좌표·면외 좌표, 단면선(ξ 또는 η 고정) 자료.
- ``downsample``: 2D 셀 격자 다운샘플(셀마다 대표 요소 1개 = valid 우선, ε_rad 최대) — 보고서·API 미리보기용.

- 0.5.7(계약 esl_disp_primary.md): ``strain_reference``(초과 요소·소성 영역·P99), ``disp_analysis``(변위 전 노드),
  ``ceil2``·``robust_range``(레전드 자동 범위 §14), ``section_stats``·``section_line``·``normalized_point``(단면선 §15).

오차 정의: ``rel_err = (ε_esl − ε_rad)/ε_rad`` (부호 있음), 요약의 ``*_pct`` 는 100 배(%), 분위수는 |rel_err|.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError
from esl.mech import supports

# 사유 코드(compare_field.npz reason, i1) — validation.json field.reason_codes 와 같음
R_OK, R_HOLD, R_LOW, R_EXCLUDED, R_NO_PREV = 0, 1, 2, 3, 4
REASONS = {R_OK: "OK", R_HOLD: "HOLD", R_LOW: "LOW", R_EXCLUDED: "EXCLUDED", R_NO_PREV: "NO_PREV"}
REASON_TEXT = {
    "OK": "비교 대상(t* 에서 상승 중, ε_rad ≥ min_rel·max)",
    "HOLD": "t* 에서 상승 중이 아님 — Max_Strain 이 이전 최대값을 유지(hold) 중이라 순간값이 아님",
    "LOW": "상승 중이지만 ε_rad < min_rel·max ε_rad (작은 변형률 — 상대오차가 의미 없음)",
    "EXCLUDED": "tstar.exclude_elem_ids 로 제외",
    "NO_PREV": "직전 프레임 값이 없어 상승 여부를 알 수 없음(예전 TCL 출력)",
}
SECTION_BINS_MAX = 200
SEMANTIC_NOTE = ("F_eq 는 u_rel(강체 제거 변위장)을 선형 탄성 모델에서 재현하는 하중이므로, 변형률(운동학량)은 "
                 "요소 정식화·회전 자유도 차이만큼만 어긋나고, 응력은 소성 영역에서 탄성 과대평가된다.")
# 보고서용 축 명칭(화면 문구는 프런트 소유). axis=xi: ξ 고정 → 판 폭 방향으로 그림, axis=eta: η 고정 → 판 길이 방향
AXIS_LABEL = {"eta": "판 길이 방향", "xi": "판 폭 방향"}
SECTION_LABEL = {"eta": "길이 방향 중앙선", "xi": "폭 방향 중앙선"}
FLAG_EXCEED, FLAG_PLASTIC = 1, 2          # /field points 6번째 열 flags 비트


def rising_mask(v, v_prev=None, rtol: float = 1e-6) -> np.ndarray:
    """(E,) bool: ``v > v_prev·(1+rtol)``, v_prev 가 None(t* = 첫 프레임)이면 ``v > 0``. NaN 은 False."""
    v = np.asarray(v, dtype=np.float64)
    if v_prev is None:
        out = v > 0
    else:
        vp = np.asarray(v_prev, dtype=np.float64)
        if vp.shape != v.shape:
            raise EslError("INPUT_INVALID", f"v_prev {vp.shape} ≠ v {v.shape}")
        out = v > vp * (1.0 + float(rtol))
    return out & np.isfinite(v)


def classify(eps_rad, rising, min_rel: float, exclude=None, known=None):
    """valid (E,) bool, reason (E,) i1, max_rad(float), 기준 요소 위치(int 또는 None).

    - exclude: 제외 마스크(EXCLUDED), known: 상승 여부를 아는 요소(아니면 NO_PREV; None = 전부 앎).
    - max_rad = 상승 중·제외 아님·상승 여부 앎 요소의 ε_rad 최대.
    """
    er = np.asarray(eps_rad, dtype=np.float64)
    E = er.size
    rising = np.asarray(rising, dtype=bool)
    ex = np.zeros(E, bool) if exclude is None else np.asarray(exclude, dtype=bool)
    kn = np.ones(E, bool) if known is None else np.asarray(known, dtype=bool)
    reason = np.full(E, R_OK, dtype=np.int8)
    reason[~rising] = R_HOLD
    reason[~kn] = R_NO_PREV
    reason[ex] = R_EXCLUDED
    cand = (reason == R_OK) & np.isfinite(er) & (er > 0)
    reason[(reason == R_OK) & ~cand] = R_LOW
    if not cand.any():
        return np.zeros(E, bool), reason, None, None
    pos = np.flatnonzero(cand)
    imax = int(pos[np.lexsort((pos, -er[pos]))[0]])       # 최대, 동률은 낮은 위치
    max_rad = float(er[imax])
    low = cand & (er < float(min_rel) * max_rad)
    reason[low] = R_LOW
    valid = reason == R_OK
    return valid, reason, max_rad, imax


def rel_error(eps_esl, eps_rad) -> np.ndarray:
    """(ε_esl − ε_rad)/ε_rad, ε_rad ≤ 0 이면 NaN."""
    er = np.asarray(eps_rad, dtype=np.float64)
    ee = np.asarray(eps_esl, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(er > 0, (ee - er) / np.where(er > 0, er, 1.0), np.nan)


def _nice_ceil(x: float) -> float:
    """1·2·2.5·5×10^k 중 x 이상인 가장 작은 값."""
    if not np.isfinite(x) or x <= 0:
        return 1.0
    p = 10.0 ** np.floor(np.log10(x))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if m * p >= x * (1 - 1e-12):
            return float(m * p)
    return float(10 * p)


def histogram(err_pct, bins: int) -> dict:
    """부호 있는 오차 % 히스토그램. 범위 ±R, R = nice_ceil(P99 |오차|) (최소 1%), 범위 밖은 끝 bin 에 포함."""
    e = np.asarray(err_pct, dtype=np.float64)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return {"edges": [], "counts": [], "range_pct": None, "n": 0, "n_clipped": 0}
    R = max(1.0, _nice_ceil(float(np.percentile(np.abs(e), 99))))
    edges = np.linspace(-R, R, int(bins) + 1)
    clipped = int(np.sum(np.abs(e) > R))
    counts, _ = np.histogram(np.clip(e, -R, R), bins=edges)
    return {"edges": edges.tolist(), "counts": counts.astype(int).tolist(), "range_pct": R, "n": int(e.size),
            "n_clipped": clipped}


def _row(i, elem_id, eps_rad, eps_esl, rel, valid, reason, c2=None):
    r = {"elem_id": int(elem_id[i]), "eps_rad": float(eps_rad[i]), "eps_esl": float(eps_esl[i]),
         "err_pct": None if not np.isfinite(rel[i]) else float(100.0 * rel[i]), "valid": bool(valid[i]),
         "reason": REASONS[int(reason[i])]}
    if c2 is not None:
        r["xi"], r["eta"] = float(c2[i, 0]), float(c2[i, 1])
    return r


def summarize(elem_id, eps_rad, eps_esl, rel, valid, reason, rising, max_pos, top_n: int, hist_bins: int,
              c2=None) -> dict:
    """validation.json ``field`` 의 수치 요약(판정·설정 메타는 호출자가 덧붙임)."""
    eps_rad = np.asarray(eps_rad, dtype=np.float64)
    eps_esl = np.asarray(eps_esl, dtype=np.float64)
    rel = np.asarray(rel, dtype=np.float64)
    E = eps_rad.size
    counts = {f"n_{REASONS[c].lower()}": int(np.sum(reason == c)) for c in REASONS}
    out: dict = {"n_elems": int(E), "n_rising": int(np.sum(rising)), "n_valid": int(np.sum(valid)), **counts}
    # 최대변형률 비교
    if max_pos is not None:
        k = int(max_pos)
        fin = np.isfinite(eps_esl)
        j = int(np.flatnonzero(fin)[np.argmax(eps_esl[fin])]) if fin.any() else k
        out["max"] = {"elem_id": int(elem_id[k]), "eps_rad": float(eps_rad[k]), "eps_esl": float(eps_esl[k]),
                      "err_pct": float(100.0 * rel[k]), "abs_err_pct": float(abs(100.0 * rel[k])),
                      "eps_esl_max": float(eps_esl[j]), "eps_esl_max_elem_id": int(elem_id[j]),
                      "peak_err_pct": float(100.0 * (eps_esl[j] - eps_rad[k]) / eps_rad[k])}
        if c2 is not None:
            out["max"]["xi"], out["max"]["eta"] = float(c2[k, 0]), float(c2[k, 1])
            out["max"]["esl_max_xi"], out["max"]["esl_max_eta"] = float(c2[j, 0]), float(c2[j, 1])
    else:
        out["max"] = None
    a = np.abs(100.0 * rel[valid])
    a = a[np.isfinite(a)]
    if a.size:
        out["abs_err_pct"] = {"mean": float(a.mean()), "p50": float(np.percentile(a, 50)),
                              "p90": float(np.percentile(a, 90)), "p95": float(np.percentile(a, 95)),
                              "p99": float(np.percentile(a, 99)), "max": float(a.max())}
        out["frac_within"] = {str(t): float(np.mean(a <= t)) for t in (5, 10, 20)}
    else:
        out["abs_err_pct"] = None
        out["frac_within"] = None
    vpos = np.flatnonzero(valid)
    top = vpos[np.lexsort((vpos, -eps_rad[vpos]))][: int(top_n)]
    out["top"] = [_row(i, elem_id, eps_rad, eps_esl, rel, valid, reason, c2) for i in top]
    ar = np.abs(rel[vpos])
    worst = vpos[np.lexsort((vpos, -np.where(np.isfinite(ar), ar, -1.0)))][: int(top_n)]
    out["worst"] = [_row(i, elem_id, eps_rad, eps_esl, rel, valid, reason, c2) for i in worst]
    out["hist"] = histogram(100.0 * rel[valid], hist_bins)
    return out


# ====================================================================== 기하: PCA 평면·단면선
def plane_coords(x0, centroids) -> dict:
    """PCA 평면(esl.mech.supports.pca_corners 와 같은 축·부호 규약) 위 요소 중심 (ξ, η) 실좌표·면외 n0,
    노드 투영 범위(정규화 기준)."""
    x0 = np.asarray(x0, dtype=np.float64)
    C = np.asarray(centroids, dtype=np.float64)
    pl = supports.pca_corners(x0)["plane"]
    o, e1, e2, n = (np.asarray(pl[k], dtype=np.float64) for k in ("origin", "e1", "e2", "n"))
    P = x0 - o
    xr = [float((P @ e1).min()), float((P @ e1).max())]
    yr = [float((P @ e2).min()), float((P @ e2).max())]
    Q = C - o
    return {"origin": o, "e1": e1, "e2": e2, "n": n, "xi": Q @ e1, "eta": Q @ e2, "n0": Q @ n,
            "xi_range": np.array(xr), "eta_range": np.array(yr)}


def elem_mean(conn, elem_type, vals) -> np.ndarray:
    """노드 값 (N,...) → 요소 평균 (E,...) (TRIA 는 노드 3개)."""
    conn = np.asarray(conn)
    vals = np.asarray(vals, dtype=np.float64)
    q = np.asarray(elem_type) == 4
    out = np.empty((conn.shape[0],) + vals.shape[1:])
    out[q] = vals[conn[q]].mean(axis=1)
    out[~q] = vals[conn[~q, :3]].mean(axis=1)
    return out


def elem_size(x0, conn, elem_type, plane=None) -> np.ndarray:
    """요소 대표 크기 sqrt(면적) (E,) — 평면 투영 없이 3D 면적."""
    x0 = np.asarray(x0, dtype=np.float64)
    conn = np.asarray(conn)
    q = np.asarray(elem_type) == 4
    a = x0[conn[:, 0]]
    b = x0[conn[:, 1]]
    c = x0[conn[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if q.any():
        d = x0[np.maximum(conn[:, 3], 0)]
        area_q = 0.5 * np.linalg.norm(np.cross(c - a, d - a), axis=1)
        area = np.where(q, area + area_q, area)
    return np.sqrt(np.maximum(area, 0.0))


def section(fixed_norm, along, n0, w_rel, w_val, at: float, band: float, nbins_max: int = SECTION_BINS_MAX) -> dict:
    """단면선: 정규화 좌표 ``fixed_norm`` 이 ``at ± band`` 인 요소를 ``along``(실좌표) 순으로 bin 평균.

    반환 {s, n0, w_rel, w_val (bin 평균), n_elems, at, band}. 요소가 없으면 빈 배열.
    """
    fx = np.asarray(fixed_norm, dtype=np.float64)
    sel = np.flatnonzero(np.abs(fx - float(at)) <= float(band))
    empty = {"s": np.zeros(0), "n0": np.zeros(0), "w_rel": np.zeros(0), "w_val": np.zeros(0), "n_elems": 0,
             "at": float(at), "band": float(band)}
    if sel.size == 0:
        return empty
    s = np.asarray(along, dtype=np.float64)[sel]
    nb = int(min(nbins_max, sel.size))
    lo, hi = float(s.min()), float(s.max())
    if hi <= lo:
        k = np.zeros(sel.size, dtype=np.int64)
        nb = 1
    else:
        k = np.minimum(((s - lo) / (hi - lo) * nb).astype(np.int64), nb - 1)
    cnt = np.bincount(k, minlength=nb).astype(np.float64)
    keep = cnt > 0

    def mean(v):
        return (np.bincount(k, weights=np.asarray(v, dtype=np.float64)[sel], minlength=nb)[keep] / cnt[keep])

    return {"s": np.bincount(k, weights=s, minlength=nb)[keep] / cnt[keep], "n0": mean(n0), "w_rel": mean(w_rel),
            "w_val": mean(w_val), "n_elems": int(sel.size), "at": float(at), "band": float(band)}


def section_band(cfg_band: float, sizes, xi_range, eta_range) -> tuple[float, float]:
    """(ξ 띠, η 띠) 정규화 반폭 = max(설정, 0.75·중앙 요소 크기/범위)."""
    h = float(np.median(sizes)) if np.size(sizes) else 0.0
    out = []
    for r in (xi_range, eta_range):
        L = float(r[1] - r[0])
        out.append(max(float(cfg_band), 0.75 * h / L if L > 0 else 0.5))
    return out[0], out[1]


def normalize(v, rng) -> np.ndarray:
    lo, hi = float(rng[0]), float(rng[1])
    return (np.asarray(v, dtype=np.float64) - lo) / (hi - lo) if hi > lo else np.zeros(np.shape(v))


# ====================================================================== 다운샘플
def downsample(xi, eta, eps_rad, valid, max_points: int):
    """2D 셀 격자 다운샘플. 반환 (idx(오름차순), cell(dx, dy) 또는 None(다운샘플 안 함)).

    격자 nx×ny ≤ max_points(평면 범위 종횡비), 셀마다 valid 우선·ε_rad 최대(동률 낮은 위치) 요소 1개.
    """
    xi = np.asarray(xi, dtype=np.float64)
    eta = np.asarray(eta, dtype=np.float64)
    n = xi.size
    mp = int(max_points)
    if n <= mp:
        return np.arange(n), None
    x0, x1, y0, y1 = float(xi.min()), float(xi.max()), float(eta.min()), float(eta.max())
    W, H = max(x1 - x0, 1e-300), max(y1 - y0, 1e-300)
    nx = int(max(1, min(mp, np.floor(np.sqrt(mp * W / H)))))
    ny = int(max(1, mp // nx))
    ix = np.minimum(((xi - x0) / W * nx).astype(np.int64), nx - 1)
    iy = np.minimum(((eta - y0) / H * ny).astype(np.int64), ny - 1)
    cell = ix * ny + iy
    er = np.where(np.isfinite(eps_rad), eps_rad, -np.inf)
    order = np.lexsort((np.arange(n), -er, ~np.asarray(valid, dtype=bool), cell))
    first = np.unique(cell[order], return_index=True)[1]
    return np.sort(order[first]), (W / nx, H / ny)


# ====================================================================== 0.5.7 변형률 참고 (계약 esl_disp_primary.md §3.4)
def strain_reference(rel, valid, epsp, n_elems: int, max_err_pct_max: float) -> dict:
    """변형률 참고 집계(판정 아님). 반환 {exceed (E,) bool, plastic (E,) bool|None, ref dict(공통 부분)}.

    - exceed = valid ∧ 100·|rel_err| > max_err_pct_max (NaN → False), 비율 분모 = 전 요소(``frac_exceed``),
      valid 요소(``frac_exceed_valid``) 병기. p99_err_pct = valid 요소 |오차| % 의 99 분위(없으면 None).
    - plastic = epsp > 0 (엄격 부등호, NaN → False). epsp 가 None 이면 ``plastic: None``.
    """
    rel = np.asarray(rel, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    E = int(n_elems)
    with np.errstate(invalid="ignore"):
        exceed = valid & (100.0 * np.abs(rel) > float(max_err_pct_max))
    n_valid = int(valid.sum())
    n_ex = int(exceed.sum())
    a = 100.0 * np.abs(rel[valid])
    a = a[np.isfinite(a)]
    ref = {"n_elems": E, "n_valid": n_valid, "n_exceed": n_ex,
           "frac_exceed": (n_ex / E) if E else 0.0, "frac_exceed_valid": (n_ex / n_valid) if n_valid else None,
           "p99_err_pct": float(np.percentile(a, 99)) if a.size else None,
           "max_err_pct_max": float(max_err_pct_max)}
    if epsp is None:
        ref["plastic"] = None
        return {"exceed": exceed, "plastic": None, "ref": ref}
    ep = np.asarray(epsp, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        plastic = ep > 0
    n_pl = int(plastic.sum())
    ref["plastic"] = {"n_plastic": n_pl, "frac_plastic": (n_pl / E) if E else 0.0,
                      "n_exceed_plastic": int((exceed & plastic).sum())}
    return {"exceed": exceed, "plastic": plastic, "ref": ref}


# ====================================================================== 0.5.7 변위 전 노드 분석 (§3.5)
def _hist_log10(r, bins: int) -> dict:
    """log10(r) 균등 bin 히스토그램. r=0 은 ``n_zero`` 로 따로. 범위 [floor(log10 min r>0), ceil(log10 max r)]."""
    r = np.asarray(r, dtype=np.float64)
    r = r[np.isfinite(r)]
    n_zero = int(np.sum(r <= 0))
    pos = r[r > 0]
    if pos.size == 0:
        return {"edges_log10": [], "counts": [], "n": int(r.size), "n_zero": n_zero}
    lo = float(np.floor(np.log10(pos.min())))
    hi = float(np.ceil(np.log10(pos.max())))
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, int(bins) + 1)
    counts, _ = np.histogram(np.log10(pos), bins=edges)
    return {"edges_log10": edges.tolist(), "counts": counts.astype(int).tolist(), "n": int(r.size), "n_zero": n_zero}


def disp_analysis(node_id, x0, d_rel, d_val, U: float, is_support, top_n: int, hist_bins: int) -> dict:
    """변위 전 노드 분석. e_i = ‖d_val − d_rel‖, r_i = e_i/U. 반환 {summary(validation.json ``disp``), arrays(compare_disp.npz)}.

    x0 노드를 ``plane_coords`` 와 같은 PCA 평면(e1 = 판 길이 방향, e2 = 판 폭 방향)에 투영한 (a, b).
    """
    nid = np.asarray(node_id, dtype=np.int64)
    d_rel = np.asarray(d_rel, dtype=np.float64)
    d_val = np.asarray(d_val, dtype=np.float64)
    sup = np.asarray(is_support, dtype=bool)
    N = int(nid.size)
    e = np.linalg.norm(d_val - d_rel, axis=1)
    U = float(U)
    r = e / U
    pl = plane_coords(x0, np.asarray(x0, dtype=np.float64))
    ab = np.stack([pl["xi"], pl["eta"]], axis=1)
    mag_rel = np.linalg.norm(d_rel, axis=1)
    order = np.lexsort((nid, -r))
    top = [{"node_id": int(nid[i]), "r": float(r[i]), "e": float(e[i]), "u_rel_mag": float(mag_rel[i]),
            "a": float(ab[i, 0]), "b": float(ab[i, 1]), "is_support": bool(sup[i])} for i in order[: int(top_n)]]
    support = [{"node_id": int(nid[i]), "r": float(r[i]), "e": float(e[i])} for i in np.flatnonzero(sup)]
    imax = int(order[0]) if N else 0
    pq = {k: float(np.percentile(r, q)) for k, q in (("p50", 50), ("p90", 90), ("p99", 99))}
    summary = {"U": U, "n_nodes": N, "n_support": int(sup.sum()),
               "rms_rel": float(np.sqrt(np.mean(e ** 2)) / U), "max_rel": float(r.max()),
               "max_node_id": int(nid[imax]), **pq, "max": float(r.max()),
               "hist": _hist_log10(r, hist_bins), "top": top, "support": support,
               "plane": {k: pl[k].tolist() for k in ("origin", "e1", "e2", "n", "xi_range", "eta_range")}}
    arrays = {"node_id": nid, "ab": ab, "d_rel": d_rel, "d_val": d_val, "e": e, "is_support": sup,
              "U": np.float64(U), "plane_origin": pl["origin"], "plane_e1": pl["e1"], "plane_e2": pl["e2"],
              "plane_n": pl["n"]}
    return {"summary": summary, "arrays": arrays}


# ====================================================================== 0.5.7 레전드 자동 범위 (§14)
def ceil2(x):
    """유효숫자 2자리 올림(263.4 → 270, 0.01234 → 0.013). x ≤ 0 이거나 비유한이면 None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x) or x <= 0:
        return None
    p = 10.0 ** (np.floor(np.log10(x)) - 1.0)
    m = np.ceil(x / p * (1.0 - 1e-12))
    return float(f"{m * p:.12g}")


def robust_range(values, kind: str = "sym", pct: float = 99) -> dict:
    """견고한 컬러 범위 {min, max, basis("p99"), raw(올림 전 분위값)}. 빈 입력·비유한·분위값 ≤ 0 → min/max None.

    - ``sym``: R = ceil2(P(|v|)), {−R, +R}.  - ``zero``: {0, ceil2(P(v))}.  - ``minmax``: {min v, ceil2(P(v))}.
    """
    if kind not in ("sym", "zero", "minmax"):
        raise EslError("INPUT_INVALID", f"robust_range kind: {kind}")
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    basis = f"p{pct:g}"
    out = {"min": None, "max": None, "basis": basis, "raw": None}
    if v.size == 0:
        return out
    raw = float(np.percentile(np.abs(v) if kind == "sym" else v, pct))
    out["raw"] = raw
    top = ceil2(raw)
    if top is None:
        return out
    if kind == "sym":
        out.update(min=-top, max=top)
    elif kind == "zero":
        out.update(min=0.0, max=top)
    else:
        out.update(min=float(v.min()), max=top)
    return out


# ====================================================================== 0.5.7 단면선 확장 (§15)
def section_stats(s, w_rel, w_val, U) -> dict:
    """단면 bin 값에서 Δw = w_val − w_rel 와 통계. 반환 {dw (list), stats}.

    stats = {dw_max_abs, s_at_dw_max, dw_rms(bin 기준 √mean(dw²)), U, dw_max_rel, dw_rms_rel, w_max_abs}.
    w_val 이 None(전체 재해석 해 없음)이면 dw 는 빈 배열, dw 관련 값 null(w_max_abs 만 값). 단면이 비면 전부 null.
    """
    keys = ("dw_max_abs", "s_at_dw_max", "dw_rms", "U", "dw_max_rel", "dw_rms_rel", "w_max_abs")
    s = np.asarray(s, dtype=np.float64)
    wr = np.asarray(w_rel, dtype=np.float64)
    if s.size == 0:
        return {"dw": [], "stats": {k: None for k in keys}}
    Uf = None if U is None or not np.isfinite(float(U)) or float(U) <= 0 else float(U)
    if w_val is None:
        return {"dw": [], "stats": {**{k: None for k in keys}, "w_max_abs": float(np.max(np.abs(wr)))}}
    wv = np.asarray(w_val, dtype=np.float64)
    dw = wv - wr
    k = int(np.argmax(np.abs(dw)))
    mx, rms = float(abs(dw[k])), float(np.sqrt(np.mean(dw ** 2)))
    return {"dw": dw.tolist(),
            "stats": {"dw_max_abs": mx, "s_at_dw_max": float(s[k]), "dw_rms": rms, "U": Uf,
                      "dw_max_rel": None if Uf is None else mx / Uf, "dw_rms_rel": None if Uf is None else rms / Uf,
                      "w_max_abs": float(max(np.max(np.abs(wr)), np.max(np.abs(wv))))}}


def section_line(plane, xi_range, eta_range, axis: str, at: float, band: float) -> dict:
    """지도에 그릴 단면 중심선 {a0, b0, a1, b1, band_abs} (PCA 평면 실좌표, 대상 파트 범위 양 끝).

    axis=eta: η = η_lo + at·Lη 고정, ξ 범위 전체(길이 방향 단면). axis=xi: ξ 고정, η 범위 전체(폭 방향 단면).
    band_abs = 정규화 띠 반폭 × 고정 축 범위(실좌표 반폭). ``plane`` 은 호출 규약 호환용(범위만 사용).
    """
    xl, xh = float(xi_range[0]), float(xi_range[1])
    el, eh = float(eta_range[0]), float(eta_range[1])
    rng = {"xi_range": [xl, xh], "eta_range": [el, eh]}        # 지도 클릭 → 정규화 좌표 변환용
    if axis == "eta":
        b = el + float(at) * (eh - el)
        return {"a0": xl, "b0": b, "a1": xh, "b1": b, "band_abs": float(band) * (eh - el), **rng}
    if axis == "xi":
        a = xl + float(at) * (xh - xl)
        return {"a0": a, "b0": el, "a1": a, "b1": eh, "band_abs": float(band) * (xh - xl), **rng}
    raise EslError("INPUT_INVALID", f"section_line axis: {axis}")


def normalized_point(ab, xi_range, eta_range) -> tuple[float, float]:
    """(a, b) 실좌표 → 정규화 (ξ_n, η_n) = (값 − min)/(max − min), [0, 1] 로 자름. 퇴화 범위는 0."""
    a, b = float(ab[0]), float(ab[1])
    out = []
    for v, r in ((a, xi_range), (b, eta_range)):
        lo, hi = float(r[0]), float(r[1])
        out.append(float(np.clip((v - lo) / (hi - lo), 0.0, 1.0)) if hi > lo else 0.0)
    return out[0], out[1]
