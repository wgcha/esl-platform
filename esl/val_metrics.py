"""v0.24.3 검증 지표 계산 — 출처 무관 순수 함수(계약 docs/contracts/esl_validate_sources.md §3·§5.1, D-0.24.3-VAL-10).

``esl.pipeline.stage_validate`` 가 legacy(full) 행과 출처 행에 **같은 함수·같은 인수 규칙**으로 부른다. 정의 =
``esl_disp_primary.md`` §3 그대로(목표 = S3 u_rel, U = max‖u_rel‖, 비교 = 응답·목표 양쪽 ``remove_linear_rigid``,
reaction_rel = Σ‖R‖/Σ‖F‖, reaction_sum_rel = ‖ΣR‖/Σ‖F‖). full 경로 호출 결과 = v0.24.2 인라인 계산과 비트 동일(골든 V-1).

파일 IO·설정 해석·경고(ctx.warnings) 없음 — 값은 인수. import 허용 = numpy·``esl.errors``·``esl.mech.kabsch``·
``esl.report.field``(순수). esl.doe·esl.pipeline·esl_platform·esl_worker 금지(시험 V-4).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from esl.errors import EslError
from esl.mech import kabsch
from esl.report import field as _field

VERDICT_SCHEME = "disp_primary/1"      # 계약 esl_disp_primary.md: 판정 = 변위 4지표, 변형률은 참고
VALIDATION_SCHEMA = "esl/validation/3"
FAIL_REASON = {"disp_rms_rel": "DISP_RMS", "disp_max_rel": "DISP_MAX", "reaction_rel": "REACTION",
               "disp_noise_rel": "DISP_NOISE"}
STRAIN_SKIPPED = "STRAIN_FROM_STRESS"   # 응력 대체: 변형률 참고 지표 전부 생략(§4)
_SREF_SKIP_KEYS = ("n_exceed", "frac_exceed", "frac_exceed_valid", "p99_err_pct")


def disp_metrics(X0, u_rel, u_val6, R, F, spc_idx, U, node_id, *, top_n: int, hist_bins: int) -> dict[str, Any]:
    """변위 판정 지표(§3.1): 양쪽 독립 선형 강체 제거 후 e = ‖d_val − d_rel‖, RMS·max / U, 반력 두 정의, u_rel 선형 강체
    크기, 전 노드 분석(``field.disp_analysis``). spc_idx = 지지 노드 인덱스(지지 표시)."""
    U = float(U)
    if not U > 0:
        raise EslError("INPUT_INVALID", "U = max|u_rel| 가 0 — 변위 지표를 정의할 수 없음")
    d_val, _, _ = kabsch.remove_linear_rigid(X0, u_val6[:, :3])
    d_rel, _, _ = kabsch.remove_linear_rigid(X0, u_rel)
    delta = d_val - d_rel
    dn = np.linalg.norm(delta, axis=1)
    disp_rms_rel = float(np.sqrt(np.mean(dn ** 2)) / U)
    disp_max_rel = float(dn.max() / U)
    sum_abs = float(np.linalg.norm(F, axis=1).sum())
    reac_abs_rel = float(np.linalg.norm(R, axis=1).sum() / sum_abs) if sum_abs > 0 else 0.0
    reac_sum_rel = float(np.linalg.norm(R.sum(axis=0)) / sum_abs) if sum_abs > 0 else 0.0
    lin_rigid_rel = float(np.max(np.linalg.norm(u_rel - d_rel, axis=1)) / U)
    is_sup = np.zeros(np.asarray(node_id).size, dtype=bool)
    is_sup[list(spc_idx)] = True
    disp_an = _field.disp_analysis(node_id, X0, d_rel, d_val, U, is_sup, top_n, hist_bins)
    return {"d_rel": d_rel, "d_val": d_val, "dn": dn, "disp_rms_rel": disp_rms_rel, "disp_max_rel": disp_max_rel,
            "reaction_rel": reac_abs_rel, "reaction_sum_rel": reac_sum_rel, "lin_rigid_rel": lin_rigid_rel,
            "disp_an": disp_an, "sum_abs_f": sum_abs}


def hotspot_rows(hs, eps_rad, eps_val) -> tuple[list, list]:
    """hotspot 비교 표: compared → (rank, elem_id, metric_value, centroid, ε_rad, ε_val, rel_err), comparable 아님 → 제외 표
    (사유·ε_rad·ε_val). 제외 판정 = Radioss 쪽(출처 무관)."""
    hots, excluded = [], []
    for h in hs:
        e = h["elem_pos"]
        rec = {"rank": h["rank"], "elem_id": h["elem_id"], "metric_value": h["value"], "centroid": h["centroid"]}
        if h["compared"]:
            er, ev = float(eps_rad[e]), float(eps_val[e])
            rec.update(eps_rad=er, eps_val=ev, rel_err=abs(ev - er) / er if er > 0 else float("inf"))
            hots.append(rec)
        elif not h["comparable"]:
            rec.update(reason=h["reason"], eps_rad=float(eps_rad[e]), eps_val=float(eps_val[e]))
            excluded.append(rec)
    return hots, excluded


def field_compare(base: dict[str, Any], eps_esl, d_rel, d_val, *, model_arrays: dict[str, Any], ccfg: dict[str, Any],
                  esl_layers_text: str) -> tuple[dict, dict]:
    """전 요소 재현 정확도 비교(esl_p2_library.md §7.2) → (compare_field.npz 배열, validation.json field 요약).

    base = Radioss 쪽(출처 무관 — ``pipeline._field_base``): eps_rad·상승·valid·사유·소성·기하(PCA 평면·단면 띠).
    eps_esl = 이 출처 검증 해 ε_eq(extract.layers), d_rel·d_val (N,3) = 단면선 변위.
    """
    elem_id, conn, et = model_arrays["elem_id"], model_arrays["conn"], model_arrays["elem_type"]
    eps_rad, valid, reason, rising = base["eps_rad"], base["valid"], base["reason"], base["rising"]
    E = int(np.asarray(elem_id).size)
    epsp = base["epsp"]
    rel = _field.rel_error(eps_esl, eps_rad)
    sref = _field.strain_reference(rel, valid, epsp, E, ccfg["max_err_pct_max"])
    pl, C3, c2, size = base["plane"], base["C3"], base["c2"], base["size"]
    n = pl["n"]
    bx, by = base["band"]
    w_rel = _field.elem_mean(conn, et, np.asarray(d_rel) @ n)
    w_val = _field.elem_mean(conn, et, np.asarray(d_val) @ n)
    sec_xi = _field.section(base["xin"], pl["eta"], pl["n0"], w_rel, w_val, 0.5, bx)      # ξ=0.5 고정, η 방향
    sec_eta = _field.section(base["etn"], pl["xi"], pl["n0"], w_rel, w_val, 0.5, by)     # η=0.5 고정, ξ 방향
    pfi, frame_index = base["prev_frame_index"], base["frame_index"]

    summ = _field.summarize(elem_id, eps_rad, eps_esl, rel, valid, reason, rising, base["imax"],
                            ccfg["top_n"], ccfg["hist_bins"], c2=c2)
    summ.update(schema="esl/field/1", frame_index=int(frame_index), prev_frame_index=pfi,
                prev_source=base["prev_source"], rtol=base["rtol"], min_rel=float(ccfg["min_rel"]),
                max_rad=base["max_rad"],
                reason_codes={str(k): v for k, v in _field.REASONS.items()}, reason_text=_field.REASON_TEXT,
                definition={"rel_err": "(eps_esl - eps_rad)/eps_rad", "abs_err_pct": "100*|rel_err| (valid 요소)",
                            "max_err_pct": "max.abs_err_pct: t* 상승 요소 중 ε_rad 최대 요소의 오차",
                            "valid": "rising ∧ eps_rad ≥ min_rel·max_rad ∧ 제외 아님",
                            "rising": "v[t*] > v[t*−1]·(1+rtol), t*=첫 프레임이면 v>0 (v = Max_Strain ε_eq)",
                            "eps_esl": f"검증 해 ε_eq({esl_layers_text}, 막 z=0 기본)"},
                plane={k: pl[k].tolist() for k in ("origin", "e1", "e2", "n", "xi_range", "eta_range")},
                sections={"xi": {"at": 0.5, "band": bx, "n_elems": sec_xi["n_elems"]},
                          "eta": {"at": 0.5, "band": by, "n_elems": sec_eta["n_elems"]}},
                note=_field.SEMANTIC_NOTE)
    arrays = dict(
        elem_id=np.asarray(elem_id).astype(np.int64), centroid2d=c2, centroid3d=C3,
        eps_rad=np.asarray(eps_rad, np.float64), eps_esl=np.asarray(eps_esl, np.float64), rel_err=rel,
        valid=valid, rising=rising, reason=reason.astype(np.int8), elem_size=size,
        epsp=np.full(E, np.nan) if epsp is None else epsp,
        plastic=np.zeros(E, bool) if sref["plastic"] is None else sref["plastic"], exceed=sref["exceed"],
        n0=pl["n0"], w_rel=w_rel, w_val=w_val,
        plane_origin=pl["origin"], plane_e1=pl["e1"], plane_e2=pl["e2"], plane_n=n,
        xi_range=pl["xi_range"], eta_range=pl["eta_range"],
        frame_index=np.int64(frame_index), prev_frame_index=np.int64(pfi),
        **{f"sec_xi_{k}": sec_xi[k] for k in ("s", "n0", "w_rel", "w_val")},
        **{f"sec_eta_{k}": sec_eta[k] for k in ("s", "n0", "w_rel", "w_val")},
        sec_band=np.array([bx, by]))
    summ["strain_ref_base"] = sref["ref"]
    return arrays, summ


def _judged(name, v, c):
    if v is None:
        return {"metric": name, "value": None, "criterion": c, "pass": None, "status": "skipped", "role": "judge"}
    return {"metric": name, "value": v, "criterion": c, "pass": bool(v <= c), "role": "judge"}


def _ref(name, v, c):
    r = {"metric": name, "value": v, "criterion": c, "pass": None, "role": "reference",
         "exceeded": bool(v is not None and not v <= c)}
    if v is None:
        r["status"] = "skipped"
    return r


def _info(name, v):
    return {"metric": name, "value": v, "criterion": None, "pass": None, "role": "info"}


def metric_rows(values: dict[str, Any], crit: dict[str, Any], ccfg: dict[str, Any], *, reaction_role: str = "judge",
                strain_skipped: bool = False) -> list[dict]:
    """지표 행(judge 4 · reference 4 · info 3, 순서 고정). reaction_role = info → 반력 지표 role info(기준 없음, 판정 제외).
    strain_skipped(응력 대체) → 변형률 참고 지표 4개 값 None."""
    v = dict(values)
    if strain_skipped:
        for k in ("hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct", "noise_hotspot_strain_rel"):
            v[k] = None
    reac = (_judged("reaction_rel", v["reaction_rel"], crit["reaction_rel_max"]) if reaction_role == "judge"
            else _info("reaction_rel", v["reaction_rel"]))
    return [
        _judged("disp_rms_rel", v["disp_rms_rel"], crit["disp_rms_rel_max"]),
        _judged("disp_max_rel", v["disp_max_rel"], crit["disp_max_rel_max"]),
        reac,
        _judged("disp_noise_rel", v["disp_noise_rel"], crit["disp_noise_rel_max"]),
        _ref("hotspot1_strain_rel_err", v["hotspot1_strain_rel_err"], crit["hotspot_strain_rel_err_max"]),
        _ref("field_max_err_pct", v["field_max_err_pct"], ccfg["max_err_pct_max"]),
        _ref("field_p90_err_pct", v["field_p90_err_pct"], ccfg["p90_err_max"]),
        _ref("noise_hotspot_strain_rel", v["noise_hotspot_strain_rel"], crit["noise_strain_rel_max"]),
        _info("reaction_sum_rel", v["reaction_sum_rel"]),
        _info("u_rel_linear_rigid_rel", v["u_rel_linear_rigid_rel"]),
        _info("noise_force_rel", v["noise_force_rel"]),
    ]


def verdict_of(metrics: list[dict], undetermined_reason: str | None) -> tuple[str, list[str]]:
    """판정: 판정 불가 사유가 있으면 UNDETERMINED, 아니면 role judge 지표 전부 통과 = PASS."""
    if undetermined_reason:
        return "UNDETERMINED", []
    judge = [m for m in metrics if m["role"] == "judge"]
    verdict = "PASS" if all(m["pass"] is True for m in judge) else "FAIL"
    return verdict, [FAIL_REASON[m["metric"]] for m in judge if m["pass"] is not True]


def validation_doc(*, frame, verdict, undetermined_reason, esl_ref, fail_reasons, criteria, noise, noise_source,
                   metrics, full_solve, hotspots, hotspots_excluded, reactions, reaction_sum, disp, strain_ref, field,
                   strain_source, created_at, src: dict | None = None) -> dict[str, Any]:
    """validation.json(esl/validation/3) — 키 순서 고정(v0.24.2 와 같음), 출처 문서는 끝에 src 블록(§6.3)."""
    doc = {"schema": VALIDATION_SCHEMA, "frame": frame, "verdict": verdict, "verdict_scheme": VERDICT_SCHEME,
           "undetermined_reason": undetermined_reason, "esl_ref": esl_ref,
           "fail_reasons": fail_reasons, "criteria": criteria, "noise": noise, "noise_source": noise_source,
           "metrics": metrics, "full_solve": full_solve, "hotspots": hotspots, "hotspots_excluded": hotspots_excluded,
           "reactions": reactions, "reaction_sum": reaction_sum, "disp": disp, "strain_ref": strain_ref,
           "field": field, "strain_source": strain_source, "created_at": created_at}
    if src is not None:
        doc["src"] = src
    return doc


def evaluate(c: dict[str, Any], *, F, u_val6, R, eps_val, reaction_role: str, noise_force: bool,
             created_at: str, criteria: dict[str, Any] | None = None, src: dict | None = None) -> dict[str, Any]:
    """한 출처의 검증(§3·§6.1) — legacy 와 출처가 같은 순서·같은 정의. 순수(c = 공통 값, 출처 무관).

    c 키: X0·node_id·u_rel·U·solved·undetermined_reason·spc·hs·eps_rad·base·model_arrays·layers_text·strain_source·
    strain_skipped·ccfg·crit·disp_top_n·disp_hist_bins·noise·noise_source·n_strain·n_force·disp_noise_rel·cum_plastic·
    frame·esl_ref·full_solve. 응답: 풀이했으면 u_val6 (N,6)·R (N,3), 아니면 None. eps_val = 이 출처 검증 해 ε_eq (E,)
    (풀이·대체 변위가 없으면 None → hotspot·field·변형률 참고 생략).
    반환 {doc, field_arrays, disp_arrays, compare(d_rel, d_val, dn) | None, values, hots, excluded, sref, fsum}.
    """
    ccfg, crit = c["ccfg"], c["crit"]
    skipped = bool(c["strain_skipped"])
    dm = None
    if c["solved"]:
        dm = disp_metrics(c["X0"], c["u_rel"], u_val6, R, F, [i for i, _ in c["spc"]], c["U"], c["node_id"],
                          top_n=c["disp_top_n"], hist_bins=c["disp_hist_bins"])
        d_rel, d_val = dm["d_rel"], dm["d_val"]
    else:
        d_rel = d_val = c["u_rel"]
    hots: list[dict] = []
    excluded: list[dict] = []
    farr, fsum, sref = None, None, None
    h1 = f_max = f_p90 = None
    if eps_val is not None:
        hots, excluded = hotspot_rows(c["hs"], c["eps_rad"], eps_val)
        h1 = hots[0]["rel_err"] if hots else float("inf")
        if skipped:
            h1 = None                                   # 응력 대체: 변형률 참고 지표 생략(§4)
        farr, fsum = field_compare(c["base"], eps_val, d_rel, d_val, model_arrays=c["model_arrays"], ccfg=ccfg,
                                   esl_layers_text=c["layers_text"])
        f_max = fsum["max"]["abs_err_pct"] if fsum["max"] else float("inf")
        f_p90 = fsum["abs_err_pct"]["p90"] if fsum["abs_err_pct"] else float("inf")
        if skipped:
            # 응력 대체: 변형률 참고 지표 전부 생략(None) — hotspot rel_err·전 요소 오차·기준 초과 비율(§4, Verifier Med1)
            f_max = f_p90 = None
            fsum["skipped"] = STRAIN_SKIPPED
            fsum.update({"max": None, "abs_err_pct": None, "frac_within": None})
            for rec in hots + excluded:
                rec["rel_err"] = None
        fsum["criteria"] = {"max_err_pct_max": ccfg["max_err_pct_max"], "p90_err_max": ccfg["p90_err_max"]}
        sref = fsum.pop("strain_ref_base")
        if skipped:
            sref.update({k: None for k in _SREF_SKIP_KEYS})
            sref["skipped"] = STRAIN_SKIPPED
    values = {"disp_rms_rel": None if dm is None else dm["disp_rms_rel"],
              "disp_max_rel": None if dm is None else dm["disp_max_rel"],
              "reaction_rel": None if dm is None else dm["reaction_rel"],
              "disp_noise_rel": c["disp_noise_rel"], "hotspot1_strain_rel_err": h1, "field_max_err_pct": f_max,
              "field_p90_err_pct": f_p90, "noise_hotspot_strain_rel": c["n_strain"],
              "reaction_sum_rel": None if dm is None else dm["reaction_sum_rel"],
              "u_rel_linear_rigid_rel": None if dm is None else dm["lin_rigid_rel"],
              "noise_force_rel": c["n_force"] if noise_force else None}
    metrics = metric_rows(values, crit, ccfg, reaction_role=reaction_role, strain_skipped=skipped)
    if sref is not None:
        sref["exceeded"] = any(m["exceeded"] for m in metrics if m["role"] == "reference")
        sref["exceeded_metrics"] = [m["metric"] for m in metrics if m["role"] == "reference" and m["exceeded"]]
        if c["cum_plastic"] is not None:
            sref.update(c["cum_plastic"])
    verdict, fail_reasons = verdict_of(metrics, c["undetermined_reason"])
    nid = c["node_id"]
    reactions = [] if R is None else [{"node_id": int(nid[i]), "dof": d, "r": R[i].tolist()} for i, d in c["spc"]]
    doc = validation_doc(frame=c["frame"], verdict=verdict, undetermined_reason=c["undetermined_reason"],
                         esl_ref=c["esl_ref"], fail_reasons=fail_reasons,
                         criteria=crit if criteria is None else criteria, noise=c["noise"],
                         noise_source=c["noise_source"], metrics=metrics, full_solve=c["full_solve"], hotspots=hots,
                         hotspots_excluded=excluded, reactions=reactions,
                         reaction_sum=None if R is None else R.sum(axis=0),
                         disp=None if dm is None else dm["disp_an"]["summary"], strain_ref=sref, field=fsum,
                         strain_source=c["strain_source"], created_at=created_at, src=src)
    return {"doc": doc, "field_arrays": farr, "disp_arrays": None if dm is None else dm["disp_an"]["arrays"],
            "compare": None if dm is None else (dm["d_rel"], dm["d_val"], dm["dn"]), "values": values, "hots": hots,
            "excluded": excluded, "sref": sref, "fsum": fsum, "sum_abs_f": None if dm is None else dm["sum_abs_f"]}
