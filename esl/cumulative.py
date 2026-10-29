"""누적 낙하 씬 변형률 규칙 (계약 esl_cumulative_input.md §6, 순수 함수).

- ``aggregate_select(st, how)``: state.npz 의 prev_* 중 사용할 집계(요소값 1개).
- ``diagnose(prev, h3d0, final, detect, forced)``: h3d 값이 이미 누적값인지(§6.2).
- ``choose(prev_aggs, h3d0, final, detect, how, forced)``: auto 집계 선택 + epsp 진단.
- ``series(raw, prev, mode)``: (cum, inc) — max-hold 는 상수 더하기로 유지된다(§6.3).
- ``write_prev_csv(model, path, agg)``: 워커가 TCL ``prev_file`` 로 넘길 CSV(elem_id,prev_epsp,prev_eq).

Q1(가정 확정 A): max_strain 의 이전 값 prev_eq = 이전 소성 변형률(잔류 대용).
"""
from __future__ import annotations

import os

import numpy as np

from esl.errors import EslError

AGGS = ("mid_mean", "mid_max", "max", "mean")
MODES = ("cumulative", "incremental", "trivial")
DETECT_DEFAULTS = {"prev_floor": 1.0e-6, "min_elems": 10, "rel_tol": 0.05, "mono_frac": 0.99}


def _det(detect: dict | None) -> dict:
    d = dict(DETECT_DEFAULTS)
    if detect:
        d.update({k: v for k, v in detect.items() if v is not None})
    return d


def diagnose(prev, h3d0, final, detect: dict | None = None, forced: str = "auto") -> dict:
    """§6.2. prev·h3d0·final 은 같은 요소 순서 (n,) 배열(h3d0 의 NaN = 그 요소 frame0 값 없음).

    반환 {mode(유효: cumulative|incremental|trivial), detected(cumulative|incremental|ambiguous|trivial),
    r0, mono, n_S, forced(bool), ambiguous(bool)}.
    """
    d = _det(detect)
    prev = np.asarray(prev, dtype=np.float64)
    h0 = np.asarray(h3d0, dtype=np.float64)
    fin = np.asarray(final, dtype=np.float64)
    pmax = float(np.nanmax(prev)) if prev.size else 0.0
    thr = max(float(d["prev_floor"]), 1e-3 * pmax)
    S = (prev > thr) & np.isfinite(h0) & np.isfinite(fin)
    nS = int(S.sum())
    r0 = mono = None
    if nS < int(d["min_elems"]):
        detected = "trivial"
    else:
        r0 = float(np.median(h0[S] / prev[S]))
        mono = float(np.mean(fin[S] >= prev[S] * (1.0 - 1e-3)))
        if abs(r0 - 1.0) <= float(d["rel_tol"]) and mono >= float(d["mono_frac"]):
            detected = "cumulative"
        elif r0 <= float(d["rel_tol"]):
            detected = "incremental"
        else:
            detected = "ambiguous"
    if forced in ("cumulative", "incremental"):
        mode = forced
    elif detected == "ambiguous":
        mode = "incremental"            # 합이 더 큼 = 보수적
    else:
        mode = detected
    return {"mode": mode, "detected": detected, "r0": r0, "mono": mono, "n_S": nS,
            "forced": forced in ("cumulative", "incremental"), "ambiguous": detected == "ambiguous"}


def choose(prev_aggs: dict, h3d0, final, detect: dict | None = None, how: str = "auto",
           forced: str = "auto") -> tuple[str, dict]:
    """§6.1 집계 선택 + epsp 진단. auto: 누적 판정되는 집계 중 median|h3d0−agg|/agg 최소, 없으면 mid_mean."""
    if how != "auto":
        if how not in AGGS:
            raise EslError("CONFIG_INVALID", f"cumulative.epsp_agg: {how}")
        return how, diagnose(prev_aggs[how], h3d0, final, detect, forced)
    h0 = np.asarray(h3d0, dtype=np.float64)
    best = None
    for a in AGGS:
        dg = diagnose(prev_aggs[a], h0, final, detect, "auto")
        if dg["detected"] != "cumulative":
            continue
        p = np.asarray(prev_aggs[a], dtype=np.float64)
        d = _det(detect)
        S = (p > max(float(d["prev_floor"]), 1e-3 * float(np.nanmax(p)))) & np.isfinite(h0)
        err = float(np.median(np.abs(h0[S] - p[S]) / p[S]))
        if best is None or err < best[0] - 1e-9:          # 동률(반올림 수준)은 앞 순서(mid_mean 우선)
            best = (err, a)
    a = best[1] if best else "mid_mean"
    dg = diagnose(prev_aggs[a], h0, final, detect, forced)
    if best:
        dg["agg_err"] = best[0]
    return a, dg


def series(raw, prev, mode: str):
    """(cum, inc): raw (F,n) 또는 (n,), prev (n,). trivial 은 cum = inc = raw."""
    raw = np.asarray(raw, dtype=np.float64)
    prev = np.asarray(prev, dtype=np.float64)
    if mode == "trivial":
        return raw, raw
    if mode == "cumulative":
        return raw, raw - prev
    if mode == "incremental":
        return raw + prev, raw
    raise EslError("CONFIG_INVALID", f"누적 모드: {mode}")


def prev_values(st: dict, agg: str) -> np.ndarray:
    """state.npz dict → 사용 집계 prev (E,)."""
    return np.asarray(st[f"prev_{agg}"], dtype=np.float64)


def write_prev_csv(model, path: str, agg: str = "auto") -> int:
    """워커용: parse_rad 결과(model.state['epsp'])로 elem_id,prev_epsp,prev_eq CSV(대상 파트 E 행). 반환 행 수.

    auto 집계는 h3d 를 보기 전이라 mid_mean(§6.1 기본)을 쓴다 — TCL 의 '+prev' 순위용 근사.
    """
    st = getattr(model, "state", None)
    eid = np.asarray(model.elem_id, dtype=np.int64)
    ep = st.get("epsp") if st else None
    a = "mid_mean" if agg == "auto" else agg
    prev = np.zeros(eid.size) if ep is None else np.asarray(ep.agg[a], dtype=np.float64)
    tmp = path + ".part"
    with open(tmp, "w", encoding="ascii", newline="\n") as fh:
        fh.write("elem_id,prev_epsp,prev_eq\n")
        for i, v in zip(eid.tolist(), prev.tolist()):
            fh.write(f"{i},{v!r},{v!r}\n")
    os.replace(tmp, path)
    return int(eid.size)
