"""t*·후보 시점·hotspot 탐색 (계약 esl_core.md §4, esl.md §6.4).

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
