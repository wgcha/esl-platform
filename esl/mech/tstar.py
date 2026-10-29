"""t*·후보 시점·hotspot 탐색 (계약 esl_core.md §4 scan(구), §7 first-reach: scan_reach 외).

- m(f) = max_e eps_eq[f,e] (exclude 적용). 선택은 time_window [t_min, t_max](닫힌 구간) 안의 프레임만.
- t* = argmax m (동률은 이른 프레임). 그 프레임의 최대 요소(동률은 낮은 위치).
- 후보 = 창 안 m(f) 의 국소 최대(같은 값 연속 구간은 하나로 보고 첫 프레임, 양 끝은 한쪽 이웃만 비교),
  m 내림차순(동률은 이른 프레임) 상위 top_n. rank 1 = t*.
- hotspot = t* 에서 ε_eq 내림차순(동률 낮은 위치), 이미 뽑힌 hotspot 중심과의 거리 ≥ min_dist 인 것만, 상위 top_k.
- history: 전 프레임 time, eps_max(m, 창과 무관), eps_hotspot1(hotspot 1위 요소의 이력). numpy 배열.
- NaN 은 −inf 로 취급.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError


def _local_max_frames(m):
    """1차원 m 에서 국소 최대 plateau 의 첫 위치 목록."""
    n = m.size
    starts = [0]
    for i in range(1, n):
        if m[i] != m[i - 1]:
            starts.append(i)
    vals = [m[s] for s in starts]
    out = []
    for k, s in enumerate(starts):
        left = vals[k - 1] if k > 0 else -np.inf
        right = vals[k + 1] if k + 1 < len(vals) else -np.inf
        if vals[k] > left and vals[k] > right and np.isfinite(vals[k]):
            out.append(s)
    if not out and n and np.isfinite(m).any():    # 상수열 등
        out.append(int(np.argmax(m)))
    return out


def scan(time, eps_eq, centroids, top_n, top_k, min_dist, time_window=(None, None), exclude_mask=None):
    time = np.asarray(time, dtype=np.float64)
    e = np.asarray(eps_eq, dtype=np.float64)
    C = np.asarray(centroids, dtype=np.float64)
    if e.ndim != 2 or e.shape[0] != time.size or C.shape != (e.shape[1], 3):
        raise EslError("INPUT_INVALID", "time (F,), eps_eq (F,E), centroids (E,3)")
    F, E = e.shape
    e = np.where(np.isnan(e), -np.inf, e)
    if exclude_mask is not None:
        ex = np.asarray(exclude_mask, dtype=bool)
        if ex.shape != (E,):
            raise EslError("INPUT_INVALID", "exclude_mask 는 (E,)")
        e = np.where(ex[None, :], -np.inf, e)
    if E == 0 or F == 0:
        raise EslError("INPUT_INVALID", "프레임 또는 요소가 없음")
    m = e.max(axis=1)
    tmin, tmax = (time_window or (None, None))
    win = np.ones(F, bool)
    if tmin is not None:
        win &= time >= float(tmin)
    if tmax is not None:
        win &= time <= float(tmax)
    fpos = np.flatnonzero(win)
    if fpos.size == 0 or not np.isfinite(m[fpos]).any():
        raise EslError("INPUT_INVALID", "time_window·exclude 적용 후 유효 프레임/요소 없음")

    def elem_at(f):
        return int(np.argmax(e[f]))

    fstar = int(fpos[np.argmax(m[fpos])])
    estar = elem_at(fstar)

    # 후보: 창 안 연속 구간별 국소 최대
    loc = []
    seg_start = 0
    for i in range(1, fpos.size + 1):
        if i == fpos.size or fpos[i] != fpos[i - 1] + 1:
            seg = fpos[seg_start:i]
            loc += [int(seg[j]) for j in _local_max_frames(m[seg])]
            seg_start = i
    if fstar not in loc:
        loc.append(fstar)
    loc.sort(key=lambda f: (-m[f], f))
    loc.remove(fstar)
    loc.insert(0, fstar)
    cands = [
        {"rank": r + 1, "frame_pos": f, "time": float(time[f]), "eps_max": float(m[f]), "elem_pos": elem_at(f)}
        for r, f in enumerate(loc[: max(int(top_n), 1)])
    ]

    # hotspot
    row = e[fstar]
    order = np.lexsort((np.arange(E), -row))
    hot: list[int] = []
    md2 = float(min_dist) ** 2
    for k in order:
        if len(hot) >= int(top_k) or not np.isfinite(row[k]):
            break
        if hot:
            d2 = np.sum((C[hot] - C[k]) ** 2, axis=1)
            if np.any(d2 < md2):
                continue
        hot.append(int(k))
    hotspots = [
        {"rank": r + 1, "elem_pos": k, "eps_eq": float(row[k]), "centroid": C[k].tolist()}
        for r, k in enumerate(hot)
    ]
    h1 = hot[0] if hot else estar
    return {
        "tstar": {"frame_pos": fstar, "time": float(time[fstar]), "elem_pos": estar, "eps_eq": float(m[fstar])},
        "candidates": cands,
        "hotspots": hotspots,
        "history": {"time": time.copy(), "eps_max": m.copy(), "eps_hotspot1": e[:, h1].copy()},
    }


# ====================================================================== first-reach (esl_core.md §7.1·§7.2·§7.4)
# h3d 의 Max_Strain·Plastic Strain 은 요소별 누적 최대(max-hold) → t* = 최종 최대값에 처음 도달한 프레임.
# 아래 함수는 TCL(esl_h3d_extract.tcl)의 H·D 선택과 같은 규칙이다(동률: 낮은 위치 = 낮은 요소 ID 우선).

def first_reach(v, rtol: float) -> np.ndarray:
    """v (F,E) → (E,) 위치: min{f : v[f,e] ≥ v[F-1,e]·(1−rtol)}. 만족 프레임이 없으면(음수 최종값 등) F−1."""
    v = np.asarray(v, dtype=np.float64)
    if v.ndim != 2 or v.shape[0] == 0:
        raise EslError("INPUT_INVALID", "v 는 (F,E), F ≥ 1")
    thr = v[-1] * (1.0 - float(rtol))
    ok = v >= thr[None, :]
    any_ok = ok.any(axis=0)
    return np.where(any_ok, np.argmax(ok, axis=0), v.shape[0] - 1).astype(np.int64)


def _desc_order(vals) -> np.ndarray:
    """값 내림차순, 동률은 낮은 위치 우선."""
    vals = np.asarray(vals, dtype=np.float64)
    return np.lexsort((np.arange(vals.size), -vals))


def hot_set(final_vm, final_epsp, hot_k: int) -> np.ndarray:
    """H = (최종 vm 상위 hot_k) ∪ (최종 epsp 상위 hot_k), 값 > 0 인 요소만(|H| 상한 없음).
    반환: 오름차순 위치."""
    k = int(hot_k)
    out: set[int] = set()
    for vals in (final_vm, final_epsp):
        vals = np.asarray(vals, dtype=np.float64)
        o = [int(i) for i in _desc_order(vals) if vals[i] > 0][:k]
        out.update(o)
    return np.array(sorted(out), dtype=np.int64)


def candidate_frames(v, rtol: float, top_n: int, mask=None) -> list[tuple[int, int]]:
    """§7.2 D 규칙: 요소를 최종값 내림차순(동률 낮은 위치)으로 훑으며 first-reach 프레임을 서로 다른 것만 top_n 개.
    최종값 ≤ 0 인 요소는 건너뜀. mask (E,) bool = 대상 요소. 반환 [(frame_pos, elem_pos)], 첫 항목이 t*."""
    v = np.asarray(v, dtype=np.float64)
    fr = first_reach(v, rtol)
    fin = v[-1]
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    for e in _desc_order(fin):
        if len(out) >= int(top_n):
            break
        if not (fin[e] > 0) or (mask is not None and not mask[e]):
            continue
        f = int(fr[e])
        if f not in seen:
            seen.add(f)
            out.append((f, int(e)))
    return out


def rising_hotspots(v, f: int, centroids, top_k: int, min_dist: float, rtol: float,
                    exclude_mask=None, first: int | None = None) -> list[dict]:
    """§7.4 hotspot: 프레임 f 에서 '상승 중'인 요소 v[f,e] > v[f−1,e]·(1+rtol) (f=0 이면 v>0).
    v[f] 내림차순(동률 낮은 위치), first(최종값 1위 등)는 상승 여부와 무관하게 맨 앞.
    이미 뽑힌 hotspot 중심과 거리 < min_dist 인 요소 제외, 상위 top_k."""
    v = np.asarray(v, dtype=np.float64)
    C = np.asarray(centroids, dtype=np.float64)
    cur = v[f]
    rising = cur > (v[f - 1] * (1.0 + float(rtol))) if f > 0 else cur > 0
    ok = rising & np.isfinite(cur)
    if exclude_mask is not None:
        ok &= ~np.asarray(exclude_mask, dtype=bool)
    order = [int(e) for e in _desc_order(np.where(np.isfinite(cur), cur, -np.inf)) if ok[e]]
    if first is not None:
        order = [int(first)] + [e for e in order if e != int(first)]
    hot: list[int] = []
    md2 = float(min_dist) ** 2
    for k in order:
        if len(hot) >= int(top_k):
            break
        if hot and np.any(np.sum((C[hot] - C[k]) ** 2, axis=1) < md2):
            continue
        hot.append(k)
    return [{"rank": r + 1, "elem_pos": k, "value": float(cur[k]), "rising": bool(rising[k]),
             "centroid": C[k].tolist()} for r, k in enumerate(hot)]


def scan_reach(time, v, centroids, top_n, top_k, min_dist, rtol, time_window=(None, None), exclude_mask=None):
    """first-reach t* (§7.1·§7.4). v (F,H) 지표 이력(max-hold), centroids (H,3).

    - time_window [t_min, t_max] 안의 프레임만 보고, 창의 마지막 프레임 값을 최종값으로 쓴다.
    - 후보 = candidate_frames(창, exclude 제외), rank 1 = t*. hotspot = rising_hotspots(t*, first=rank1 요소).
    - history m(f) = max_{e∈H, exclude 제외} v[f,e] (전 프레임).
    반환 위치는 전체 프레임·H 기준.
    """
    time = np.asarray(time, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    C = np.asarray(centroids, dtype=np.float64)
    if v.ndim != 2 or v.shape[0] != time.size or C.shape != (v.shape[1], 3):
        raise EslError("INPUT_INVALID", "time (F,), v (F,H), centroids (H,3)")
    F, H = v.shape
    if F == 0 or H == 0:
        raise EslError("INPUT_INVALID", "프레임 또는 이력 요소(H)가 없음")
    ex = np.zeros(H, bool) if exclude_mask is None else np.asarray(exclude_mask, dtype=bool)
    if ex.shape != (H,):
        raise EslError("INPUT_INVALID", "exclude_mask 는 (H,)")
    tmin, tmax = (time_window or (None, None))
    win = np.ones(F, bool)
    if tmin is not None:
        win &= time >= float(tmin)
    if tmax is not None:
        win &= time <= float(tmax)
    fpos = np.flatnonzero(win)
    if fpos.size == 0:
        raise EslError("INPUT_INVALID", "time_window 안에 프레임이 없음")
    vv = np.where(np.isfinite(v), v, -np.inf)
    cand = candidate_frames(vv[fpos], rtol, top_n, mask=~ex)
    if not cand:
        raise EslError("INPUT_INVALID", "지표 최종값이 양수인 요소가 없음(time_window·exclude 적용 후)")
    cands = [{"rank": r + 1, "frame_pos": int(fpos[f]), "time": float(time[fpos[f]]), "elem_pos": e,
              "value": float(vv[fpos[-1], e])} for r, (f, e) in enumerate(cand)]
    t0 = cands[0]
    hots = rising_hotspots(vv, t0["frame_pos"], C, top_k, min_dist, rtol, exclude_mask=ex, first=t0["elem_pos"])
    m = np.where(ex[None, :], -np.inf, vv).max(axis=1)
    return {"tstar": dict(t0), "candidates": cands, "hotspots": hots, "history": {"time": time.copy(), "m": m}}


# ====================================================================== 누적 씬 (esl_cumulative_input.md §6.4, CI-D-9)
def scan_reach_cum(time, cum, inc, centroids, top_n, top_k, min_dist, rtol, time_window=(None, None),
                   exclude_mask=None, min_increment: float = 1e-5):
    """누적 씬 t*: 순위 = 누적 최종값(cum), first-reach = 증분 계열(inc) — 상수 prev 가 작은 증분을 가리지 않게.

    이번 증분 최종값 ≤ min_increment 인 요소(이전 손상만)는 후보·hotspot 에서 제외(Q2 가정 확정 A), 수는
    ``n_excluded_no_increment``. hotspot '상승 중' 판정도 inc 계열, 정렬 값은 cum. 반환 위치는 전체 프레임·H 기준,
    값은 value(=cum)·value_inc·value_prev.
    """
    time = np.asarray(time, dtype=np.float64)
    cum = np.asarray(cum, dtype=np.float64)
    inc = np.asarray(inc, dtype=np.float64)
    C = np.asarray(centroids, dtype=np.float64)
    if cum.shape != inc.shape or cum.ndim != 2 or cum.shape[0] != time.size or C.shape != (cum.shape[1], 3):
        raise EslError("INPUT_INVALID", "time (F,), cum·inc (F,H), centroids (H,3)")
    F, H = cum.shape
    if F == 0 or H == 0:
        raise EslError("INPUT_INVALID", "프레임 또는 이력 요소(H)가 없음")
    ex = np.zeros(H, bool) if exclude_mask is None else np.asarray(exclude_mask, dtype=bool)
    tmin, tmax = (time_window or (None, None))
    win = np.ones(F, bool)
    if tmin is not None:
        win &= time >= float(tmin)
    if tmax is not None:
        win &= time <= float(tmax)
    fpos = np.flatnonzero(win)
    if fpos.size == 0:
        raise EslError("INPUT_INVALID", "time_window 안에 프레임이 없음")
    cv = np.where(np.isfinite(cum), cum, -np.inf)
    iv = np.where(np.isfinite(inc), inc, -np.inf)
    cw, iw = cv[fpos], iv[fpos]
    has_inc = iw[-1] > float(min_increment)
    n_excl = int(np.sum(~has_inc & ~ex & (cw[-1] > 0)))
    ok = ~ex & has_inc
    fr = first_reach(iw, rtol)
    fin = cw[-1]
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    for e in _desc_order(fin):
        if len(out) >= int(top_n):
            break
        if not (fin[e] > 0) or not ok[e]:
            continue
        f = int(fr[e])
        if f not in seen:
            seen.add(f)
            out.append((f, int(e)))
    if not out:
        raise EslError("INPUT_INVALID", "이번 낙하 증분이 있는(> min_increment) 요소가 없음(time_window·exclude 적용 후)")
    last = int(fpos[-1])
    cands = [{"rank": r + 1, "frame_pos": int(fpos[f]), "time": float(time[fpos[f]]), "elem_pos": e,
              "value": float(cv[last, e]), "value_inc": float(iv[last, e]),
              "value_prev": float(cv[last, e] - iv[last, e])} for r, (f, e) in enumerate(out)]
    t0 = cands[0]
    f = t0["frame_pos"]
    rising = iv[f] > (iv[f - 1] * (1.0 + float(rtol))) if f > 0 else iv[f] > 0
    hok = rising & np.isfinite(cv[f]) & ok
    order = [int(e) for e in _desc_order(cv[f]) if hok[e]]
    order = [t0["elem_pos"]] + [e for e in order if e != t0["elem_pos"]]
    hot: list[int] = []
    md2 = float(min_dist) ** 2
    for k in order:
        if len(hot) >= int(top_k):
            break
        if hot and np.any(np.sum((C[hot] - C[k]) ** 2, axis=1) < md2):
            continue
        hot.append(k)
    hots = [{"rank": r + 1, "elem_pos": k, "value": float(cv[f, k]), "value_inc": float(iv[f, k]),
             "value_prev": float(cv[f, k] - iv[f, k]), "rising": bool(rising[k]), "centroid": C[k].tolist()}
            for r, k in enumerate(hot)]
    m = np.where(ex[None, :], -np.inf, cv).max(axis=1)
    mi = np.where(ex[None, :], -np.inf, iv).max(axis=1)
    return {"tstar": dict(t0), "candidates": cands, "hotspots": hots, "n_excluded_no_increment": n_excl,
            "history": {"time": time.copy(), "m": m, "m_inc": mi}}
