"""순위·민감도 (계약 esl_bead_doe.md BD-D-6, §11, V-BD-8·9).

순위: C_ref = max_i C_{d000,i}(베이스라인의 선택 ESL 최악), score_d = max_i C_{d,i} / C_ref, 개선율 = 1 − score_d.
오름차순, 동률 = 안 id 사전순. 스킵·실패 안은 순위 밖. OK 0개(베이스라인 제외) → 경고 NO_FEASIBLE_DESIGNS.
③ 은 |개선율| < noise_floor 인 안에 ``noise: true``.

ESL별 개선 지표(v0.10.0, 계약 esl_bead_doe.md §11.4): 최악 ESL 절대 max 점수는 한 씬의 문제가 다른 씬으로 옮겨가는
상황을 못 보므로 안 d·ESL i 마다 r_{d,i} = C_{d,i} / C_{d000,i}(베이스라인 같은 ESL 대비) 를 두고
worst_ratio = max_i r, min_improvement = 1 − worst_ratio, all_improved = worst_ratio < 1 − tol,
n_improved = #{r < 1 − tol}, n_worsened = #{r > 1 + tol}(|1 − r| ≤ tol 은 변화 없음), geo_mean_improvement =
1 − (Π r)^(1/n), pareto = 베이스라인·다른 OK 안 어느 것에도 모든 ESL 에서 지배당하지 않음(지배 = 모든 i 에서 r ≤, 하나 이상 <).
tol = 설정 rank.ratio_tol(기본 1e-6), ③ 은 max(ratio_tol, noise_floor). 베이스라인 C ≤ 0 인 ESL 은 비율에서 뺀다(경고).

민감도: OK 안(베이스라인 포함)의 변수를 [lo, hi] → [0, 1] 정규화, score 에 최소자승 선형 회귀(절편 포함) →
SRC_j = β_j·σ_xj/σ_y, R². Spearman ρ(동률 평균 순위). fullfact 는 수준별 평균(주효과). OK 수 < 변수 수 + 2 → None.
"""
from __future__ import annotations

import numpy as np

from esl.doe import FAILED, SKIPPED
from esl.errors import EslError

BASELINE = "d000"
_SKIP_KEY = {"SKIPPED_COLLISION": "collision", "SKIPPED_FIXED": "fixed", "SKIPPED_GEOM": "geom"}
_FAIL_KEY = {"FAILED_MORPH": "morph", "FAILED_MESH": "mesh", "FAILED_SOLVE": "solve"}


def _agg(r: dict) -> dict:
    per = r.get("per_esl") or []
    if not per:
        raise EslError("INPUT_INVALID", f"{r.get('id')}: per_esl 없음")
    w = per[0]
    for p in per[1:]:
        if p["C"] > w["C"]:
            w = p
    return {"C": float(w["C"]), "worst": w["entry_id"], "umax": float(w["umax"]), "epsmax": float(w["epsmax"]),
            "umax_all": float(max(p["umax"] for p in per)), "epsmax_all": float(max(p["epsmax"] for p in per))}


def ratio_tol(noise_floor: float | None, base_tol: float = 1e-6) -> float:
    """'변화 없음' 허용치: 설정 rank.ratio_tol, ③(잡음 바닥 있음)은 둘 중 큰 값."""
    t = float(base_tol)
    return max(t, float(noise_floor)) if noise_floor is not None else t


def per_esl_metrics(ratios: list[float], tol: float) -> dict:
    """한 안의 ESL별 비율 r_i → worst_ratio·min_improvement·all_improved·n_improved·n_worsened·geo_mean_improvement."""
    if not ratios:
        return {"worst_ratio": None, "min_improvement": None, "all_improved": None, "n_improved": 0,
                "n_worsened": 0, "n_unchanged": 0, "geo_mean_improvement": None}
    r = np.asarray(ratios, dtype=np.float64)
    worst = float(r.max())
    n_imp = int(np.sum(r < 1.0 - tol))
    n_wor = int(np.sum(r > 1.0 + tol))
    gm = float(np.exp(np.mean(np.log(np.maximum(r, 1e-300)))))
    return {"worst_ratio": worst, "min_improvement": 1.0 - worst, "all_improved": bool(worst < 1.0 - tol),
            "n_improved": n_imp, "n_worsened": n_wor, "n_unchanged": int(r.size - n_imp - n_wor),
            "geo_mean_improvement": 1.0 - gm}


def pareto_flags(vecs: dict[str, list[float]], baseline: list[float] | None = None) -> dict[str, bool]:
    """안 id → ESL별 비율 벡터(같은 순서). 다른 안(또는 베이스라인 = 전부 1)에 지배당하지 않으면 True. 결정적(입력 순서 무관)."""
    ids = sorted(vecs)
    M = {i: np.asarray(vecs[i], dtype=np.float64) for i in ids}
    others = [(i, M[i]) for i in ids]
    if baseline is not None:
        others.append(("__base__", np.asarray(baseline, dtype=np.float64)))
    out = {}
    for i in ids:
        a = M[i]
        dom = False
        for j, b in others:
            if j == i or b.shape != a.shape:
                continue
            if np.all(b <= a) and np.any(b < a):
                dom = True
                break
        out[i] = not dom
    return out


def rank(results: list[dict], *, noise_floor: float | None = None, tol: float = 1e-6) -> dict:
    """result.json 목록(베이스라인 포함) → DoeResultOut 순위 부분(+ ESL별 개선 지표, 행의 per_esl)."""
    by = {r["id"]: r for r in results}
    b = by.get(BASELINE)
    if b is None or b.get("status") != "OK":
        raise EslError("BASELINE_FAILED", "베이스라인 d000 결과가 없거나 실패")
    ba = _agg(b)
    C_ref = ba["C"]
    if not C_ref > 0:
        raise EslError("BASELINE_FAILED", f"베이스라인 최악 컴플라이언스가 양수가 아님 ({C_ref})")
    rows, n_sk, n_fl, n_other = [], {v: 0 for v in _SKIP_KEY.values()}, {v: 0 for v in _FAIL_KEY.values()}, 0
    tl = ratio_tol(noise_floor, tol)
    base_C = {p["entry_id"]: float(p["C"]) for p in b.get("per_esl") or []}
    order = [p["entry_id"] for p in b.get("per_esl") or [] if float(p["C"]) > 0]
    warns_extra = [{"code": "BASELINE_ESL_ZERO", "entry_ids": [e for e, c in base_C.items() if not c > 0]}] \
        if any(not c > 0 for c in base_C.values()) else []
    for r in sorted(results, key=lambda x: x["id"]):
        if r["id"] == BASELINE:
            continue
        st = r.get("status")
        if st in SKIPPED:
            n_sk[_SKIP_KEY[st]] += 1
            continue
        if st in FAILED:
            n_fl[_FAIL_KEY[st]] += 1
            continue
        if st != "OK":
            n_other += 1
            continue
        a = _agg(r)
        s = a["C"] / C_ref
        imp = 1.0 - s
        pe = {p["entry_id"]: p for p in r.get("per_esl") or []}
        per = [{"entry_id": e, "C": float(pe[e]["C"]), "ratio": float(pe[e]["C"]) / base_C[e],
                "umax": float(pe[e]["umax"]), "epsmax": float(pe[e]["epsmax"])} for e in order if e in pe]
        met = per_esl_metrics([x["ratio"] for x in per], tl)
        rows.append({"id": r["id"], "values": dict(r.get("values") or {}), "score": s, "improvement": imp,
                     "worst_entry_id": a["worst"], "umax": a["umax"], "epsmax": a["epsmax"],
                     "umax_all": a["umax_all"], "epsmax_all": a["epsmax_all"],
                     "noise": None if noise_floor is None else bool(abs(imp) < float(noise_floor)),
                     "warnings_n": len(r.get("warnings") or []), **met, "per_esl": per,
                     "C": {p["entry_id"]: float(p["C"]) for p in r.get("per_esl") or []}})
    full = {x["id"]: [p["ratio"] for p in x["per_esl"]] for x in rows if len(x["per_esl"]) == len(order)}
    pf = pareto_flags(full, [1.0] * len(order))
    for x in rows:
        x["pareto"] = bool(pf.get(x["id"], False))
    rows.sort(key=lambda x: (x["score"], x["id"]))
    for k, x in enumerate(rows):
        x["rank"] = k + 1
    warns = ([] if rows else [{"code": "NO_FEASIBLE_DESIGNS"}]) + warns_extra
    return {"C_ref": C_ref, "baseline": {"id": BASELINE, "score": 1.0, "umax": ba["umax"], "epsmax": ba["epsmax"],
                                         "umax_all": ba["umax_all"], "epsmax_all": ba["epsmax_all"],
                                         "worst_entry_id": ba["worst"]},
            "n_ok": len(rows), "n_skipped": n_sk, "n_failed": n_fl, "n_other": n_other, "ranking": rows,
            "noise_floor": noise_floor, "ratio_tol": tl, "esl_order": order, "warnings": warns}


SORT_KEYS = {
    # 키 → (행 → 정렬 값, 오름차순이 좋은 쪽). 동률은 score → 안 id
    "score": lambda x: x["score"],
    "worst_ratio": lambda x: x.get("worst_ratio") if x.get("worst_ratio") is not None else float("inf"),
    "geo_mean_improvement": lambda x: -(x.get("geo_mean_improvement") if x.get("geo_mean_improvement") is not None
                                        else float("-inf")),
    "n_worsened": lambda x: x.get("n_worsened", 0),
    "pareto": lambda x: 0 if x.get("pareto") else 1,
}


def sort_rows(rows: list[dict], key: str = "score") -> list[dict]:
    """순위표 정렬(기본 score — rank 필드는 score 순위 그대로)."""
    if key not in SORT_KEYS:
        raise EslError("INPUT_INVALID", f"정렬 키 {key} — {sorted(SORT_KEYS)}")
    f = SORT_KEYS[key]
    return sorted(rows, key=lambda x: (f(x), x["score"], x["id"]))


def _rankdata(v: np.ndarray) -> np.ndarray:
    """동률 평균 순위(1부터)."""
    o = np.argsort(v, kind="mergesort")
    r = np.empty(v.size, dtype=np.float64)
    sv = v[o]
    i = 0
    while i < v.size:
        j = i
        while j + 1 < v.size and sv[j + 1] == sv[i]:
            j += 1
        r[o[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return r


def _pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = a - a.mean(), b - b.mean()
    den = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    return None if den <= 0 else float(np.sum(a * b) / den)


def spearman(x, y) -> float | None:
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    return _pearson(_rankdata(x), _rankdata(y))


def sensitivity(samples: list[dict], params: list[dict], *, method: str, levels: int | None = None,
                round_mm: float = 0.01) -> dict:
    """samples = [{values{name: v}, score}] (OK 안 + 베이스라인), params = 정규화 spec params [{name, lo, hi}].

    반환 {method:"src+spearman", r2, params[{name, src, spearman, beta, main_effects?}], n} 또는
    {method, null:True, reason:"SENSITIVITY_TOO_FEW", n}."""
    k = len(params)
    n = len(samples)
    if n < k + 2:
        return {"method": "src+spearman", "null": True, "reason": "SENSITIVITY_TOO_FEW", "n": n, "k": k}
    names = [p["name"] for p in params]
    lo = np.array([float(p["lo"]) for p in params])
    hi = np.array([float(p["hi"]) for p in params])
    X = np.array([[float(s["values"][nm]) for nm in names] for s in samples], dtype=np.float64)
    Z = (X - lo) / (hi - lo)
    y = np.array([float(s["score"]) for s in samples], dtype=np.float64)
    A = np.column_stack([np.ones(n), Z])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    beta = coef[1:]
    sy = float(np.std(y))
    sx = np.std(Z, axis=0)
    yhat = A @ coef
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = None if sst <= 0 else float(1.0 - np.sum((y - yhat) ** 2) / sst)
    out = []
    for j, nm in enumerate(names):
        row = {"name": nm, "beta": float(beta[j]), "src": float(beta[j] * sx[j] / sy) if sy > 0 else 0.0,
               "spearman": spearman(Z[:, j], y)}
        if method == "fullfact" and levels:
            lv = [lo[j] + t * (hi[j] - lo[j]) / (int(levels) - 1) for t in range(int(levels))]
            tol = max(float(round_mm), 1e-12)
            me = []
            for v in lv:
                m = np.abs(X[:, j] - v) <= tol
                if m.any():
                    me.append({"level": float(v), "mean": float(y[m].mean()), "n": int(m.sum())})
            row["main_effects"] = me
        out.append(row)
    return {"method": "src+spearman", "null": False, "r2": r2, "params": out, "n": n, "k": k}
