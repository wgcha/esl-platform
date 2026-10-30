"""원 낙하 vs 검증 낙하 비교(계약 esl_scx_relay.md SR-D-16·§9.3, V-SR-11). 결정적, 숫자만, PASS/FAIL 없음.

입력: 두 추출 폴더(``01_extract`` — model.npz·strain_frames.npz·disp.npz·frames.json), 원 Case 확정 t*(시각), ESL 선형 예측 비
(그 Case ESL 의 r_umax·r_epsmax — v0.10.0 §11.4), 설정 {same_tol, hot_n}. 검증 쪽 기준 좌표는 ``x0_verify``(모핑 좌표 — 추출은
원 rad 위상으로 하므로 좌표를 덮어 쓴다)가 있으면 그것.

위상: 대상 파트 요소 ID 집합·연결(노드 ID)이 같아야 함(좌표는 다름 — 모핑). 다르면 ``VD_TOPOLOGY_MISMATCH``.

행(rows) — 값은 후보 프레임 D(strain_frames·disp 가 있는 프레임) 기준:
- ``eps_peak``  시간·요소 최대 ε_eq(기존 추출 정의 — Max_Strain 텐서 + 전단 규약, 누적 아님), 요소 ID·시각 병기
- ``eps_hot``   원 낙하 상위 hot_n 요소(요소별 시간 최대 ε_eq)의 요소별 비 → 평균(행 ratio)·최대(hot.max_ratio)
- ``disp_peak`` 프레임별 전 노드 Kabsch 강체 제거 ‖u_rel‖ 최대의 시간 최대
- ``eps_tstar``·``disp_tstar`` 원 t* 에 가장 가까운 프레임(양쪽 각각)의 같은 지표
판단: 비 < 1−tol 개선(better), > 1+tol 악화(worse), 그 밖 비슷(same). ``predicted`` = ε 행은 r_epsmax, 변위 행은 r_umax.
``agree`` = (ratio−1)(predicted−1) > 0 또는 둘 다 비슷 — 예측이 없으면 None.
"""
from __future__ import annotations

import io
import json
import os

import numpy as np

from esl.errors import EslError
from esl.io import rad_eq, strain_source_of
from esl.mech import kabsch

D_EXTRACT = "01_extract"
ROW_LABELS = {
    "eps_peak": "최대 등가 변형률 ε_eq(시간·요소 최대)",
    "eps_hot": "원 낙하 상위 요소 ε_eq(요소별 비 평균)",
    "disp_peak": "최대 상대 변위 ‖u_rel‖(강체 제거, 시간 최대)",
    "eps_tstar": "t* 최대 등가 변형률 ε_eq",
    "disp_tstar": "t* 최대 상대 변위 ‖u_rel‖",
}
CSV_HEADER = ["key", "label", "orig", "verify", "ratio", "predicted", "verdict", "agree"]


def _npz(d: str, name: str) -> dict:
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        raise EslError("VD_RESULT_MISSING", f"추출 산출물이 없음: {os.path.basename(d)}/{name}")
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _json(d: str, name: str) -> dict:
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        raise EslError("VD_RESULT_MISSING", f"추출 산출물이 없음: {os.path.basename(d)}/{name}")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _load(out: str, x0_override: dict | None = None) -> dict:
    d = os.path.join(out, D_EXTRACT) if os.path.isdir(os.path.join(out, D_EXTRACT)) else out
    m = _npz(d, "model.npz")
    sf = _npz(d, "strain_frames.npz")
    dp = _npz(d, "disp.npz")
    fr = _json(d, "frames.json")
    factor = float(((fr.get("shear") or {}).get("factor")) or 1.0)
    src = strain_source_of(fr)
    eq = rad_eq(sf["eps"], sf["vm_hv"], factor, src)                     # (D, E) — 대체 source 면 epsp·σ_vM(§4)
    x0 = np.asarray(m["x0"], dtype=np.float64).copy()
    nid = np.asarray(m["node_id"], dtype=np.int64)
    if x0_override:
        pos = {int(v): i for i, v in enumerate(nid.tolist())}
        for k, v in x0_override.items():
            i = pos.get(int(k))
            if i is not None:
                x0[i] = v
    dnid = np.asarray(dp["node_id"], dtype=np.int64)
    if not np.array_equal(dnid, nid):
        raise EslError("VD_TOPOLOGY_MISMATCH", "disp.npz 노드 ID 가 model.npz 와 다름")
    u = np.asarray(dp["u"], dtype=np.float64)                          # (D, N, 3)
    ur = np.zeros(u.shape[0])
    for k in range(u.shape[0]):
        rel, *_ = kabsch.remove_rigid(x0, u[k])
        ur[k] = float(np.linalg.norm(rel, axis=1).max()) if rel.size else 0.0
    return {"elem_id": np.asarray(m["elem_id"], dtype=np.int64), "conn": np.asarray(m["conn"], dtype=np.int64),
            "node_id": nid, "eq": eq, "time": np.asarray(sf["time"], dtype=np.float64),
            "elem_time": np.asarray(sf["elem_id"], dtype=np.int64), "ur": ur,
            "disp_time": np.asarray(dp["time"], dtype=np.float64), "strain_source": src}


def _topology(a: dict, b: dict) -> None:
    if a["elem_id"].shape != b["elem_id"].shape or not np.array_equal(a["elem_id"], b["elem_id"]):
        raise EslError("VD_TOPOLOGY_MISMATCH", f"대상 파트 요소 ID 집합이 다름(원 {a['elem_id'].size}, 검증 {b['elem_id'].size})")
    if a["conn"].shape != b["conn"].shape or not np.array_equal(a["conn"], b["conn"]):
        raise EslError("VD_TOPOLOGY_MISMATCH", "대상 파트 요소 연결(노드 ID)이 다름")
    if not np.array_equal(a["node_id"], b["node_id"]):
        raise EslError("VD_TOPOLOGY_MISMATCH", "대상 파트 노드 ID 집합이 다름")
    if not np.array_equal(a["elem_time"], a["elem_id"]) or not np.array_equal(b["elem_time"], b["elem_id"]):
        raise EslError("VD_TOPOLOGY_MISMATCH", "strain_frames.npz 요소 순서가 model.npz 와 다름")


def _nearest(times: np.ndarray, t: float | None) -> int | None:
    if t is None or times.size == 0:
        return None
    return int(np.argmin(np.abs(times - float(t))))


def _verdict(r: float | None, tol: float) -> str | None:
    if r is None:
        return None
    return "better" if r < 1.0 - tol else ("worse" if r > 1.0 + tol else "same")


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not a > 0:
        return None
    return float(b) / float(a)


def _agree(r: float | None, p: float | None, tol: float) -> bool | None:
    if r is None or p is None:
        return None
    if _verdict(r, tol) == "same" and _verdict(p, tol) == "same":
        return True
    return bool((r - 1.0) * (p - 1.0) > 0)


def compare(orig_out: str, verify_out: str, *, tstar_time: float | None = None, predicted: dict | None = None,
            same_tol: float = 0.02, hot_n: int = 20, x0_verify: dict | None = None) -> dict:
    """VerifyCompare 본문 {rows, hot, warnings, tstar}. orig_out·verify_out = 01_extract 가 있는 폴더(또는 그 폴더 자체)."""
    a = _load(orig_out)
    b = _load(verify_out, x0_verify)
    _topology(a, b)
    tol = float(same_tol)
    pred = predicted or {}
    p_eps = pred.get("r_epsmax")
    p_u = pred.get("r_umax")
    warns: list[str] = []
    if a["strain_source"] != b["strain_source"]:
        warns.append(f"VD_STRAIN_SOURCE_MISMATCH: 원 낙하 변형률 source {a['strain_source']} ≠ 검증 낙하 {b['strain_source']} "
                     f"— ε 행 비는 서로 다른 양의 비교(참고)")
    E = a["elem_id"]
    rows = []

    def row(key: str, o: float | None, v: float | None, p: float | None, **extra) -> None:
        r = _ratio(o, v)
        rows.append({"key": key, "label": ROW_LABELS[key], "orig": o, "verify": v, "ratio": r,
                     "predicted": None if p is None else float(p), "verdict": _verdict(r, tol) or "same",
                     "agree": _agree(r, None if p is None else float(p), tol), **extra})

    # eps_peak
    def peak(x: dict) -> tuple[float, int, float]:
        if x["eq"].size == 0:
            return 0.0, -1, 0.0
        k, e = np.unravel_index(int(np.argmax(x["eq"])), x["eq"].shape)
        return float(x["eq"][k, e]), int(x["elem_id"][e]), float(x["time"][k])

    po, pv = peak(a), peak(b)
    row("eps_peak", po[0], pv[0], p_eps, orig_elem_id=po[1], orig_time=po[2], verify_elem_id=pv[1], verify_time=pv[2])
    # eps_hot
    ta = a["eq"].max(axis=0) if a["eq"].size else np.zeros(E.size)
    tb = b["eq"].max(axis=0) if b["eq"].size else np.zeros(E.size)
    n = int(max(1, min(int(hot_n), E.size)))
    order = np.lexsort((E, -ta))[:n]                       # 큰 순, 동률 = 요소 ID 순(결정적)
    sel = order[ta[order] > 0]
    if sel.size < order.size:
        warns.append(f"원 낙하 상위 요소 중 ε_eq = 0 인 {order.size - sel.size}개는 비에서 뺌")
    rr = tb[sel] / ta[sel] if sel.size else np.zeros(0)
    hot = {"n": int(sel.size), "mean_ratio": float(rr.mean()) if rr.size else None,
           "max_ratio": float(rr.max()) if rr.size else None, "elem_ids": E[sel].tolist()}
    r_hot = hot["mean_ratio"]
    rows.append({"key": "eps_hot", "label": ROW_LABELS["eps_hot"],
                 "orig": float(ta[sel].mean()) if sel.size else None, "verify": float(tb[sel].mean()) if sel.size else None,
                 "ratio": r_hot, "predicted": None if p_eps is None else float(p_eps),
                 "verdict": _verdict(r_hot, tol) or "same", "agree": _agree(r_hot, p_eps, tol)})
    # disp_peak
    row("disp_peak", float(a["ur"].max()) if a["ur"].size else None, float(b["ur"].max()) if b["ur"].size else None, p_u)
    # t*
    ts = {"orig_time": None, "verify_time": None}
    ka, kb = _nearest(a["time"], tstar_time), _nearest(b["time"], tstar_time)
    if ka is None or kb is None:
        warns.append("원 Case t* 가 없어 t* 지표를 비우고 넣지 않음")
    else:
        ts = {"orig_time": float(a["time"][ka]), "verify_time": float(b["time"][kb])}
        row("eps_tstar", float(a["eq"][ka].max()), float(b["eq"][kb].max()), p_eps)
        da, db = _nearest(a["disp_time"], tstar_time), _nearest(b["disp_time"], tstar_time)
        row("disp_tstar", float(a["ur"][da]), float(b["ur"][db]), p_u)
        if b["time"].size > 1 and abs(ts["verify_time"] - float(tstar_time)) > float(np.max(np.diff(b["time"]))):
            warns.append("검증 낙하 후보 프레임이 원 t* 와 한 프레임 간격 이상 떨어져 있음(t* 지표는 참고)")
    return {"rows": _clean(rows), "hot": _clean(hot), "warnings": warns, "tstar": ts, "same_tol": tol,
            "orig_strain_source": a["strain_source"], "vd_strain_source": b["strain_source"],
            "strain_source": b["strain_source"]}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def compare_csv(result: dict) -> str:
    """compare.json 의 rows → CSV(같은 행). 숫자는 repr(결정적), 빈 값 = 빈 칸."""
    buf = io.StringIO()
    buf.write(",".join(CSV_HEADER) + "\n")
    for r in result.get("rows") or []:
        vals = []
        for k in CSV_HEADER:
            v = r.get(k)
            if v is None:
                vals.append("")
            elif isinstance(v, bool):
                vals.append("true" if v else "false")
            elif isinstance(v, float):
                vals.append(repr(v))
            else:
                s = str(v)
                vals.append('"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s)
        buf.write(",".join(vals) + "\n")
    return buf.getvalue()


__all__ = ["compare", "compare_csv", "ROW_LABELS", "CSV_HEADER"]
