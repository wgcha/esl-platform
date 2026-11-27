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

순위 지표(v0.20.0, 계약 esl_stiffness_metric.md SM-2): ``metric`` = solve(재풀이 C — 옛 스냅샷, 이 정의 그대로·바이트 동일)
| lin(1차 섭동 — per_esl 의 ``C_ritz``(lin_form ritz, 기본) 또는 ``C_lin``(taylor)). 구조(최악 ESL 비·오름차순·동률)는 같고 값만
바뀐다. 새 스냅샷(베이스라인 per_esl 에 ``C_lin`` 키) 이면 행에 보조 열 score_solve·imbalance_max·rho_min·rho_max·umax_def·
C_solve{…}, 최상위에 metric·lin_form·C_ref_solve. lin 에서 지표가 null(SM_SKIPPED) 인 안 = 순위 밖 n_failed["sm"].

민감도: OK 안(베이스라인 포함)의 변수를 [lo, hi] → [0, 1] 정규화, score 에 최소자승 선형 회귀(절편 포함) →
SRC_j = β_j·σ_xj/σ_y, R². Spearman ρ(동률 평균 순위). fullfact 는 수준별 평균(주효과). OK 수 < 변수 수 + 2 → None.
"""
from __future__ import annotations

import numpy as np

from esl.doe import FAILED, SKIPPED
from esl.doe import stiffness_metric as sm
from esl.errors import EslError

BASELINE = "d000"
# 하중 출처 지표 키 → (n_failed 이름, 베이스라인 값 없음 문구). 지그(v0.23.0)·경계력 ESL(v0.24.0 esl_bforce.md §5.4)
_ALT_KEYS = {"C_jig": ("jig", "베이스라인 지그 지표가 없음(JIG_SKIPPED)"),
             "C_bf": ("bf", "베이스라인 경계력 ESL 지표가 없음(BF_DESIGN_FAILED)"),
             "C_fi": ("fi", "베이스라인 내력 ESL 지표가 없음(FINT_DESIGN_FAILED)"),
             # v0.24.4 P2c(esl_jig_case.md §7): 지그 강제 변위·스프링 — null 안 = n_failed["jd"|"js"](JIG_DESIGN_FAILED)
             "C_jd": ("jd", "베이스라인 지그 변위 지표가 없음(JIG_SKIPPED)"),
             "C_js": ("js", "베이스라인 지그 스프링 지표가 없음(JIG_SKIPPED)")}
_VIEW_ONLY = frozenset(sm.VIEW_METRICS.values())   # 보기 전용 지표(옛 스냅샷 허용 — 노드 힘 출처)
_SKIP_KEY = {"SKIPPED_COLLISION": "collision", "SKIPPED_FIXED": "fixed", "SKIPPED_GEOM": "geom"}
_FAIL_KEY = {"FAILED_MORPH": "morph", "FAILED_MESH": "mesh", "FAILED_SOLVE": "solve"}


def _agg(r: dict, key: str = "C") -> dict:
    per = r.get("per_esl") or []
    if not per:
        raise EslError("INPUT_INVALID", f"{r.get('id')}: per_esl 없음")
    w = per[0]
    for p in per[1:]:
        if p[key] > w[key]:
            w = p
    out = {"C": float(w[key]), "worst": w["entry_id"], "umax": float(w["umax"]), "epsmax": float(w["epsmax"]),
           "umax_all": float(max(p["umax"] for p in per)), "epsmax_all": float(max(p["epsmax"] for p in per))}
    if key != "C" or "C_lin" in w:
        out["umax_def"] = _f(w.get("umax_def"))
    if "umax_ev" in w:                          # v0.24.0 평가 영역 umax(새 스냅샷만 — esl_fint.md §6.2)
        ev = [p.get("umax_ev") for p in per]
        out["umax_ev"] = _f(w.get("umax_ev"))
        out["umax_ev_all"] = max(float(v) for v in ev) if all(v is not None for v in ev) else None
    return out


def _f(v):
    return None if v is None else float(v)


def _sm_new(b: dict) -> bool:
    """새 스냅샷(강성 지표 키가 per_esl 에 있음) 여부 — 베이스라인 기준."""
    return any("C_lin" in p for p in b.get("per_esl") or [])


def _sm_aux(r: dict, a: dict, C_ref_solve: float) -> dict:
    """새 스냅샷 보조 열: score_solve(옛 정의)·imbalance_max·rho_min·rho_max·umax_def(최악 ESL 기준 — metric)."""
    per = r.get("per_esl") or []
    rho = [float(p["rho"]) for p in per if p.get("rho") is not None]
    imb = [float(p["imbalance_rel"]) for p in per if p.get("imbalance_rel") is not None]
    return {"score_solve": max(float(p["C"]) for p in per) / C_ref_solve,
            "imbalance_max": max(imb) if imb else None, "rho_min": min(rho) if rho else None,
            "rho_max": max(rho) if rho else None, "umax_def": a.get("umax_def")}


def _jig_ref(b: dict) -> dict | None:
    """베이스라인 지그 기준(모든 ESL 의 C_jig 가 양수일 때만): {C, umax}. 지그 값 없음 = None(옛 스냅샷·fallback)."""
    per = b.get("per_esl") or []
    if not per or any(p.get("C_jig") is None for p in per):
        return None
    c = max(float(p["C_jig"]) for p in per)
    um = [p.get("umax_jig") for p in per]
    umax = max(float(v) for v in um) if all(v is not None for v in um) else None
    return {"C": c, "umax": umax} if c > 0 else None


def _jig_aux(r: dict, ref: dict) -> dict:
    """행 보조 열: score_jig(= max_i C_jig / 기준)·umax_jig(비)·C_jig{entry: N·mm}. 안에 지그 값이 없으면 null."""
    per = r.get("per_esl") or []
    ok = bool(per) and all(p.get("C_jig") is not None for p in per)
    um = ok and ref["umax"] and all(p.get("umax_jig") is not None for p in per)
    return {"score_jig": max(float(p["C_jig"]) for p in per) / ref["C"] if ok else None,
            "umax_jig": max(float(p["umax_jig"]) for p in per) / ref["umax"] if um else None,
            "C_jig": {p["entry_id"]: float(p["C_jig"]) for p in per} if ok else None}


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


def rank(results: list[dict], *, noise_floor: float | None = None, tol: float = 1e-6,
         extra_failed: dict | None = None, metric: str = "solve", lin_form: str = sm.LIN_FORM_DEFAULT,
         lin_valid: float | None = None, noise_floor_by_id: dict | None = None) -> dict:
    """result.json 목록(베이스라인 포함) → DoeResultOut 순위 부분(+ ESL별 개선 지표, 행의 per_esl).

    noise_floor_by_id(v0.24.8 fix JG-26) = 형상(안)별 noise_floor {id: nf_d} — 있는 안의 행 판정(ESL별 tol·noise 표식·n_improved·
    all_improved)은 nf_d, 없는 안은 noise_floor. 최상위 noise_floor·ratio_tol 은 noise_floor 그대로. None = 옛 계산(바이트 동일).

    extra_failed = 추가 실패 상태 {상태: n_failed 키}(④ ``{"FAILED_SIZE": "size"}`` — 없으면 ①②③ 결과 그대로).
    metric·lin_form = 순위 지표(SM-2) — 기본 solve = 옛 정의 바이트 동일, lin 은 새 스냅샷(per_esl 에 C_lin) 에서만.
    lin_valid(R-SM-1 결정 2026-11-13, lin 일 때만): |ρ−1| > lin_valid 인 ESL 이 있는 안은 그 안의 순위 값을 재풀이 C 로 대체
    (score = max_i C_solve / C_ref_solve, ESL별 비 = C_solve / 베이스라인 C_solve) — 행 basis "solve" + sm_warn [SM_LIN_RANGE],
    나머지 basis "lin", 최상위 n_fallback. None = 대체 없음(옛 동작)."""
    key = sm.metric_key(metric, lin_form)
    fail_key = dict(_FAIL_KEY, **(extra_failed or {}))
    by = {r["id"]: r for r in results}
    b = by.get(BASELINE)
    if b is None or b.get("status") != "OK":
        raise EslError("BASELINE_FAILED", "베이스라인 d000 결과가 없거나 실패")
    new = _sm_new(b)
    alt = _ALT_KEYS.get(key)                    # 다른 하중 출처 지표(지그·경계력) — 값 null 안 = 순위 밖 n_failed[이름]
    if key != "C" and not new and key not in _VIEW_ONLY:
        raise EslError("INPUT_INVALID", "rank.metric lin 인데 결과에 강성 지표(C_lin)가 없음 — 옛 스냅샷은 solve")
    if key != "C":
        if any(p.get(key) is None for p in b.get("per_esl") or []):
            raise EslError("BASELINE_FAILED", alt[1] if alt else "베이스라인 강성 지표가 없음(SM_SKIPPED)")
        fail_key[f"__{alt[0] if alt else 'sm'}__"] = alt[0] if alt else "sm"
    ba = _agg(b, key)
    C_ref = ba["C"]
    if not C_ref > 0:
        raise EslError("BASELINE_FAILED", f"베이스라인 최악 컴플라이언스가 양수가 아님 ({C_ref})")
    C_ref_solve = _agg(b)["C"] if new else None
    if new and not C_ref_solve > 0:
        raise EslError("BASELINE_FAILED", f"베이스라인 최악 컴플라이언스(solve)가 양수가 아님 ({C_ref_solve})")
    jig_ref = _jig_ref(b)
    rows, n_sk, n_fl, n_other = [], {v: 0 for v in _SKIP_KEY.values()}, {v: 0 for v in fail_key.values()}, 0
    tl = ratio_tol(noise_floor, tol)
    base_C = {p["entry_id"]: float(p[key]) for p in b.get("per_esl") or []}
    base_S = {p["entry_id"]: float(p["C"]) for p in b.get("per_esl") or []}
    fb_on = key not in ("C", "C_jig", *_VIEW_ONLY) and lin_valid is not None
    lin_key = sm.metric_key("lin", lin_form)
    lin_ref = (_agg(b, lin_key)["C"] if new and all(p.get(lin_key) is not None for p in b.get("per_esl") or [])
               else None)
    lin_ref = lin_ref if lin_ref is not None and lin_ref > 0 else None
    order = [p["entry_id"] for p in b.get("per_esl") or [] if float(p[key]) > 0]
    warns_extra = [{"code": "BASELINE_ESL_ZERO", "entry_ids": [e for e, c in base_C.items() if not c > 0]}] \
        if any(not c > 0 for c in base_C.values()) else []
    for r in sorted(results, key=lambda x: x["id"]):
        if r["id"] == BASELINE:
            continue
        st = r.get("status")
        if st in SKIPPED:
            n_sk[_SKIP_KEY[st]] += 1
            continue
        if st in FAILED or st in fail_key:
            n_fl[fail_key[st]] += 1
            continue
        if st != "OK":
            n_other += 1
            continue
        if key != "C" and any(p.get(key) is None for p in r.get("per_esl") or []):
            n_fl[alt[0] if alt else "sm"] += 1      # 강성 지표(SM_SKIPPED)·지그(JIG_DESIGN_FAILED)·경계력(BF_DESIGN_FAILED) 실패 — 순위 밖
            continue
        fb = fb_on and sm.out_of_range(r.get("per_esl") or [], lin_valid)
        k_r, ref_r, base_r = ("C", C_ref_solve, base_S) if fb else (key, C_ref, base_C)
        a = _agg(r, k_r)
        s = a["C"] / ref_r
        imp = 1.0 - s
        pe = {p["entry_id"]: p for p in r.get("per_esl") or []}
        per = [{"entry_id": e, "C": float(pe[e][k_r]), "ratio": float(pe[e][k_r]) / base_r[e],
                "umax": float(pe[e]["umax"]), "epsmax": float(pe[e]["epsmax"])} for e in order if e in pe]
        if new:
            for x in per:
                p = pe[x["entry_id"]]
                x.update(C_solve=float(p["C"]), rho=_f(p.get("rho")), imbalance_rel=_f(p.get("imbalance_rel")),
                         umax_def=_f(p.get("umax_def")))
        for x in per:
            if "umax_ev" in pe[x["entry_id"]]:
                x["umax_ev"] = _f(pe[x["entry_id"]]["umax_ev"])
        nf_r = noise_floor
        if noise_floor_by_id and r["id"] in noise_floor_by_id:   # 형상별 오차 범위(JG-26) — 그 안의 행 판정만
            nf_r = float(noise_floor_by_id[r["id"]])
        met = per_esl_metrics([x["ratio"] for x in per], tl if nf_r is noise_floor else ratio_tol(nf_r, tol))
        row = {"id": r["id"], "values": dict(r.get("values") or {}), "score": s, "improvement": imp,
               "worst_entry_id": a["worst"], "umax": a["umax"], "epsmax": a["epsmax"],
               "umax_all": a["umax_all"], "epsmax_all": a["epsmax_all"],
               "noise": None if nf_r is None else bool(abs(imp) < float(nf_r)),
               "warnings_n": len(r.get("warnings") or []), **met, "per_esl": per,
               "C": {p["entry_id"]: float(p[k_r]) for p in r.get("per_esl") or []}}
        if "umax_ev" in a:
            row["umax_ev"], row["umax_ev_all"] = a["umax_ev"], a["umax_ev_all"]
        if fb_on:
            row["basis"] = "solve" if fb else "lin"
            if fb:
                row["sm_warn"] = ["SM_LIN_RANGE"]
        if new and lin_ref:                     # 보조 열: 1차 지표 비(lin_form 식, metric 과 무관 — solve 주 열일 때 비교용)
            row["score_lin"] = (_agg(r, lin_key)["C"] / lin_ref
                                if all(p.get(lin_key) is not None for p in r.get("per_esl") or []) else None)
        if new:
            row.update(_sm_aux(r, a, C_ref_solve), C_solve={p["entry_id"]: float(p["C"]) for p in r.get("per_esl") or []})
        if jig_ref is not None:                 # 지그 보조 열(metric 과 무관 — 베이스라인에 지그 값이 있을 때만, v0.23.0)
            row.update(_jig_aux(r, jig_ref))
        rows.append(row)
    full = {x["id"]: [p["ratio"] for p in x["per_esl"]] for x in rows if len(x["per_esl"]) == len(order)}
    pf = pareto_flags(full, [1.0] * len(order))
    for x in rows:
        x["pareto"] = bool(pf.get(x["id"], False))
    rows.sort(key=lambda x: (x["score"], x["id"]))
    for k, x in enumerate(rows):
        x["rank"] = k + 1
    warns = ([] if rows else [{"code": "NO_FEASIBLE_DESIGNS"}]) + warns_extra
    out = {"C_ref": C_ref, "baseline": {"id": BASELINE, "score": 1.0, "umax": ba["umax"], "epsmax": ba["epsmax"],
                                        "umax_all": ba["umax_all"], "epsmax_all": ba["epsmax_all"],
                                        "worst_entry_id": ba["worst"]},
           "n_ok": len(rows), "n_skipped": n_sk, "n_failed": n_fl, "n_other": n_other, "ranking": rows,
           "noise_floor": noise_floor, "ratio_tol": tl, "esl_order": order, "warnings": warns}
    if "umax_ev" in ba:
        out["baseline"].update(umax_ev=ba["umax_ev"], umax_ev_all=ba["umax_ev_all"])
    if new:
        out["baseline"].update(_sm_aux(b, ba, C_ref_solve))
        if jig_ref is not None:
            out["baseline"].update(_jig_aux(b, jig_ref))
        out.update(metric=metric, lin_form=lin_form, C_ref_solve=C_ref_solve)
    if fb_on:
        out["n_fallback"] = sum(1 for x in rows if x.get("basis") == "solve")
    return out


# v0.25.2 결과 개수 줄(esl_tstar_manual_jig_force.md §4.1 — D-0.25.2-14): n_skipped·n_failed 키 → 라벨(한 곳 — 화면 거울
# frontend pages/doe COUNT_LABELS, API counts 가 없을 때만 씀). 표에 없는 키 = 키 그대로. 순서 = 이 표 순서(표에 없는 키는 뒤, 이름순).
COUNT_OK = {"key": "ok", "label": "성공"}
COUNT_LABELS = {"mesh": "메시", "size": "크기/정렬", "solve": "해석", "morph": "모핑",
                "collision": "스킵(충돌)", "fixed": "스킵(고정)", "geom": "스킵(형상)",
                "jig": "지그 매핑 제외", "jd": "지그 매핑 제외", "js": "지그 매핑 제외",
                "bf": "경계력 없음", "fi": "내력 없음", "sm": "강성 지표 없음", "ref": "참고용"}


JIG_METRIC_KEYS = ("C_jig", "C_jd", "C_js")       # v0.25.2 §7.2: 지그 출처 순위(참고용 꼬리표 jig_ref 가 붙는 순위 — 전 노드·경계력·내력 아님)


def mark_ref(R: dict, metric_key: str, ref_ids) -> dict:
    """참고용 형상 표시(§3.4·§4.1 — 순위 값·정렬 불변): metric_key 가 지그 출처 순위면 ref_ids 안의 행에 jig_ref True(참일 때만 키),
    R["n_ref"] = 그 수(> 0 일 때만 키). R 을 바꾸고 돌려준다."""
    if metric_key in JIG_METRIC_KEYS:
        refs = set(ref_ids or ())
        n = 0
        for x in R.get("ranking") or []:
            if x.get("id") in refs:
                x["jig_ref"] = True
                n += 1
        if n:
            R["n_ref"] = n
    return R


def count_items(R: dict) -> list[dict]:
    """결과 개수(§4.1): [{key, label, n}] = 성공(n_ok, 항상) + n_skipped·n_failed 의 0 이 아닌 모든 키(COUNT_LABELS 순서) +
    참고용(n_ref > 0 일 때만). 같은 키가 n_skipped·n_failed 양쪽에 있으면 합. 순수 함수(보고서·결과 문서 공용)."""
    out = [{**COUNT_OK, "n": int(R.get("n_ok") or 0)}]
    acc: dict[str, int] = {}
    for blk in ("n_skipped", "n_failed"):
        for k, v in (R.get(blk) or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) != 0:
                acc[str(k)] = acc.get(str(k), 0) + int(v)
    order = list(COUNT_LABELS)
    for k in sorted(acc, key=lambda k: (order.index(k) if k in order else len(order), k)):
        out.append({"key": k, "label": COUNT_LABELS.get(k, k), "n": acc[k]})
    nr = R.get("n_ref")
    if isinstance(nr, (int, float)) and not isinstance(nr, bool) and int(nr) > 0:
        out.append({"key": "ref", "label": COUNT_LABELS["ref"], "n": int(nr)})
    return out


def attach_shapes(R: dict, shapes: dict[str, dict]) -> dict:
    """④ 형상 이름(v0.14.0 SC-D-4): 순위 행·베이스라인에 shape{name, file_name, reference}. shapes = {id: {name, file_name,
    reference, source?}}. 민감도는 변수가 없어 생략(COMPARE_NO_PARAMS — 호출자)."""
    def sh(did: str) -> dict:
        s = shapes.get(did) or {}
        out = {"name": s.get("name") or did, "file_name": s.get("file_name"), "reference": bool(s.get("reference"))}
        if s.get("source") == "case":          # 기준 = Case 메시(SC-D-2)
            out["source"] = "case"
        return out
    for x in R["ranking"]:
        x["shape"] = sh(x["id"])
        x["values"] = {}
    R["baseline"]["shape"] = sh(BASELINE)
    return R


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
