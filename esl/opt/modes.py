"""변형 모드 분류 — 덴팅·뒤틀림·굽힘 (계약 esl_opt_run.md OR-D-13, §7.4).

용도: 표시·보고서·라이브러리 분류/검색 + 하중 선정 전략 B. ESL 자신의 메시(raw)에서 계산한다.

- w_i = u_rel,i · n (frame 법선), s = 2(a − a_min)/L_xi − 1, t = 2(b − b_min)/L_eta − 1 ∈ [−1, 1].
- 기저(르장드르 2차): 1, s, t, P2(s), P2(t), s·t — 노드 면적(``node_areas``) 가중 최소자승.
- E_bend = ‖c_P2s·P2(s) + c_P2t·P2(t)‖²_A, E_twist = ‖c_st·s t‖²_A, 잔차 r = w − 적합, E_res = ‖r‖²_A,
  E_tot = E_bend + E_twist + E_res (강체·평면 성분 1, s, t 제외).
- κ = 잔차 에너지 밀도(r²) 큰 노드부터 면적 합이 ``dent_area_frac`` × 전체 면적이 될 때까지의 잔차 에너지 비율.
- 덴팅 = E_res/E_tot ≥ ``dent_resid_min`` AND κ ≥ ``dent_conc_min``. 아니면 E_bend ≥ E_twist → 굽힘, 아니면 뒤틀림.
- max|w| = 0 이거나 E_tot < ``min_energy_rel`` · max|w|² · A 면 분류 불가(None, 경고).

저장 레코드(``library_entries.deform_mode``): {auto, metrics{bend, twist, resid, kappa}, user, user_by, user_at,
rule_version}. effective = user ?? auto. 기준값 변경(rule_version 증가) 시 ``refresh`` 가 auto 만 다시 계산하고 user 유지.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError
from esl.library import normalize as nz

MODES = ("dent", "twist", "bend")
LABEL_KO = {"dent": "덴팅", "twist": "뒤틀림", "bend": "굽힘", None: "분류 불가"}


def _p2(x):
    return 0.5 * (3.0 * x * x - 1.0)


def classify(x0, conn, elem_type, u_rel, frame: dict, mode_cfg: dict) -> dict:
    """반환 {mode, metrics{bend, twist, resid, kappa, energy_tot, w_max}, coeffs, rule_version, warnings}."""
    x0 = np.asarray(x0, dtype=np.float64)
    u = np.asarray(u_rel, dtype=np.float64)
    if u.shape != x0.shape:
        raise EslError("INPUT_INVALID", "u_rel 과 x0 는 같은 (N,3)")
    n = np.asarray(frame["n"], dtype=np.float64)
    w = u @ n
    P = x0 - np.asarray(frame["origin"], dtype=np.float64)
    a = P @ np.asarray(frame["e_xi"], dtype=np.float64)
    b = P @ np.asarray(frame["e_eta"], dtype=np.float64)
    a0, a1 = map(float, frame["a_range"])
    b0, b1 = map(float, frame["b_range"])
    s = 2.0 * (a - a0) / (a1 - a0) - 1.0
    t = 2.0 * (b - b0) / (b1 - b0) - 1.0
    A = nz.node_areas(x0, conn, elem_type)
    At = float(A.sum())
    rv = int(mode_cfg["rule_version"])
    wmax = float(np.max(np.abs(w))) if w.size else 0.0
    base = {"rule_version": rv, "warnings": []}
    if wmax <= 0 or At <= 0:
        return {**base, "mode": None, "metrics": {"bend": None, "twist": None, "resid": None, "kappa": None,
                                                   "energy_tot": 0.0, "w_max": wmax}, "coeffs": None,
                "warnings": ["면외 변위 0 — 변형 모드 분류 불가"]}
    Phi = np.column_stack([np.ones_like(s), s, t, _p2(s), _p2(t), s * t])
    sw = np.sqrt(A)
    c, *_ = np.linalg.lstsq(Phi * sw[:, None], w * sw, rcond=None)
    fit = Phi @ c
    r = w - fit
    bend = c[3] * Phi[:, 3] + c[4] * Phi[:, 4]
    twist = c[5] * Phi[:, 5]
    Eb = float(np.sum(A * bend ** 2))
    Et = float(np.sum(A * twist ** 2))
    Er = float(np.sum(A * r ** 2))
    Etot = Eb + Et + Er
    met = {"bend": None, "twist": None, "resid": None, "kappa": None, "energy_tot": Etot, "w_max": wmax}
    if Etot < float(mode_cfg["min_energy_rel"]) * wmax ** 2 * At or Etot <= 0:
        return {**base, "mode": None, "metrics": met, "coeffs": c.tolist(),
                "warnings": ["굽힘·뒤틀림·잔차 에너지가 너무 작음(강체·평면 성분뿐) — 분류 불가"]}
    dens = r ** 2
    order = np.lexsort((np.arange(dens.size), -dens))
    cumA = np.cumsum(A[order])
    k = int(np.searchsorted(cumA, float(mode_cfg["dent_area_frac"]) * At, side="left")) + 1
    top = order[:min(k, order.size)]
    kappa = float(np.sum(A[top] * dens[top]) / Er) if Er > 0 else 0.0
    met.update(bend=Eb / Etot, twist=Et / Etot, resid=Er / Etot, kappa=kappa)
    if met["resid"] >= float(mode_cfg["dent_resid_min"]) and kappa >= float(mode_cfg["dent_conc_min"]):
        mode = "dent"
    elif Eb >= Et:
        mode = "bend"
    else:
        mode = "twist"
    return {**base, "mode": mode, "metrics": met, "coeffs": c.tolist()}


def classify_raw(raw: dict, frame: dict, mode_cfg: dict) -> dict:
    """라이브러리 항목 raw(x0, conn, elem_type, u_rel) + meta.frame."""
    return classify(raw["x0"], raw["conn"], raw["elem_type"], raw["u_rel"], frame, mode_cfg)


def record(auto: dict, user: str | None = None, user_by: str | None = None, user_at: str | None = None) -> dict:
    if user is not None and user not in MODES:
        raise EslError("INVALID_PARAMS", f"deform_mode: {MODES} 또는 null (값 {user!r})")
    m = auto.get("metrics") or {}
    return {"auto": auto.get("mode"), "metrics": {k: m.get(k) for k in ("bend", "twist", "resid", "kappa")},
            "user": user, "user_by": user_by if user is not None else None,
            "user_at": user_at if user is not None else None, "rule_version": int(auto["rule_version"])}


def effective(dm: dict | None) -> str | None:
    if not dm:
        return None
    return dm.get("user") or dm.get("auto")


def set_user(dm: dict, user: str | None, by: str | None, at: str | None) -> dict:
    """사용자 수정(None = 자동으로 되돌림)."""
    if user is not None and user not in MODES:
        raise EslError("INVALID_PARAMS", f"deform_mode: {MODES} 또는 null (값 {user!r})")
    out = dict(dm)
    out.update(user=user, user_by=by if user is not None else None, user_at=at if user is not None else None)
    return out


def needs_refresh(dm: dict | None, mode_cfg: dict) -> bool:
    return dm is None or int(dm.get("rule_version") or 0) != int(mode_cfg["rule_version"])


def refresh(dm: dict | None, auto: dict) -> dict:
    """auto 만 새로(기준값 변경), user 는 유지."""
    new = record(auto)
    if dm and dm.get("user") is not None:
        new.update(user=dm["user"], user_by=dm.get("user_by"), user_at=dm.get("user_at"))
    return new
