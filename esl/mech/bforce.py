"""경계력 ESL 하중 조립 — 낙하 해석이 계산한 노드 힘을 하중으로 (계약 docs/contracts/esl_bforce.md §0·§3, v0.24.0).

F = s_c·CONT + s_t·CONT2 − M·ACC (= 노드 내력, M a = F_ext − F_int) 또는 F = s_f·FINT. 등급(D-0.24.0-BF-1):
full(CONT + CONT2) > fint(FINT) > contact(CONT만 — tie 체결력 미포함, 불평형은 관성 이완) > none.

부호: CONT·CONT2 = 그 노드에 작용하는 힘, FINT = s_f(auto: full 이면 ‖F − s·FINT‖ 최소, 아니면 Σ s·FINT_ref·u_rel > 0).
좌표: h3d 벡터 = t* 변형 형상 전역 성분 → 기준 형상 F_ref,n = Rᵀ F_n(R = S4 Kabsch 회전, 행 표기 F @ R).
균형: 관성 이완 ā = (RᵀMR)⁻¹RᵀF, F_bal = F − M R ā(R = 강체 6모드, 질량 중심 기준) → 3-2-1 반력 ≈ 0.

모드 무관 독립 모듈(AGENTS.md): ``esl.doe``·``esl.pipeline`` import 금지, 파일 IO·설정 해석 없음 — 값은 모두 인수.
import 허용 = numpy · esl.errors · esl.mech.kabsch · esl.mech.mass.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

SCHEMA = "esl/bforce/1"
KINDS = ("cont", "cont2", "acc", "mass", "fint")
VEC_KINDS = ("cont", "cont2", "acc", "fint")
GRADES = ("full", "fint", "contact", "none")
GRADE_RANK = {"full": 3, "fint": 2, "contact": 1, "none": 0}
BALANCES = ("inertia_relief", "none")
LIMIT_TIE = "BF_TIE_MISSING"          # contact 등급 한계: tie 체결력 미포함 — 조립 부품 하중 누락
LIMIT_DECOMP = "BF_NO_DECOMP"         # fint 등급: 분해 정보 없음
FORMULA = {"full": "F = CONT + CONT2 − M·ACC", "fint": "F = s·FINT", "contact": "F = CONT − M·ACC"}


def grade_of(have) -> str:
    """있는 종류 집합 → 등급(우선순위 full > fint > contact > none)."""
    h = set(have)
    if "cont" in h and "cont2" in h:
        return "full"
    if "fint" in h:
        return "fint"
    if "cont" in h:
        return "contact"
    return "none"


def rho_per_elem(elem_mid, mats: list, default_rho: float) -> tuple[np.ndarray, list]:
    """요소 밀도 ρ_e(deck /MAT rho) — 없거나 ≤ 0 인 재료는 default_rho, 반환 (ρ_e (E,), 기본값을 쓴 재료 id 목록)."""
    mid = np.asarray(elem_mid, dtype=np.int64).reshape(-1)
    rho_of = {}
    for mt in mats or []:
        try:
            v = mt.get("rho")
            rho_of[int(mt["id"])] = float(v) if v is not None else None
        except (KeyError, TypeError, ValueError):
            continue
    out = np.empty(mid.size)
    miss = []
    for k in np.unique(mid).tolist():
        v = rho_of.get(int(k))
        if v is None or not v > 0:
            v = float(default_rho)
            miss.append(int(k))
        out[mid == k] = v
    return out, miss


def _vec(a, n: int | None = None) -> np.ndarray:
    a = np.asarray(a, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 3 or (n is not None and a.shape[0] != n):
        raise EslError("INPUT_INVALID", f"경계력 벡터 shape 오류 {a.shape}")
    return a


def _sign(v, name: str) -> float:
    s = float(v)
    if s not in (1.0, -1.0):
        raise EslError("CONFIG_INVALID", f"bforce.signs.{name} 는 1 또는 -1: {v}")
    return s


def assemble(data: dict, m_deck=None, *, use_inertia: bool = True, signs: dict | None = None, R=None,
             u_rel=None) -> dict:
    """data = {cont, cont2, acc, fint: (N,3) | None, mass: (N,) | None}, m_deck = deck 근사 질량 (N,) | None.
    R = 기준 형상 회전(3,3)(None = I), u_rel = 기준계 변형 변위(fint 부호 auto 규칙용).
    반환 {grade, F (전역), F_ref, parts{cont, cont2, inertia} (전역, 없으면 None), m, mass_source, fint_sign,
    fint_sign_source, fint_check_rel, decomposed, limits, warnings}. 등급 none = EslError BF_NO_DATA."""
    have = {k for k in KINDS if data.get(k) is not None}
    grade = grade_of(have)
    if grade == "none":
        raise EslError("BF_NO_DATA", f"경계력 자료 없음(접촉력·내력 모두 없음) — 있는 종류 {sorted(have)}")
    sg = {"cont": 1, "cont2": 1, "fint": "auto", **(signs or {})}
    n = _vec(data["cont"] if "cont" in have else data["fint"]).shape[0]
    Rm = np.eye(3) if R is None else np.asarray(R, dtype=np.float64)
    warns: list = []
    limits: list = []
    if data.get("mass") is not None:
        m = np.asarray(data["mass"], dtype=np.float64).reshape(-1)
        msrc = "h3d"
    elif m_deck is not None:
        m = np.asarray(m_deck, dtype=np.float64).reshape(-1)
        msrc = "deck"
    else:
        m, msrc = None, None
    if m is not None and m.size != n:
        raise EslError("INPUT_INVALID", f"질량 길이 {m.size} ≠ 노드 수 {n}")
    parts = {"cont": None, "cont2": None, "inertia": None}
    F = None
    if grade in ("full", "contact"):
        parts["cont"] = _sign(sg["cont"], "cont") * _vec(data["cont"], n)
        F = parts["cont"].copy()
        if grade == "full":
            parts["cont2"] = _sign(sg["cont2"], "cont2") * _vec(data["cont2"], n)
            F = F + parts["cont2"]
        if use_inertia:
            if data.get("acc") is None:
                warns.append({"code": "BF_NO_ACC"})
            elif m is None:
                warns.append({"code": "BF_NO_MASS"})
            else:
                parts["inertia"] = -m[:, None] * _vec(data["acc"], n)
                F = F + parts["inertia"]
        if msrc == "deck" and parts["inertia"] is not None:
            warns.append({"code": "BF_MASS_APPROX"})
        if grade == "contact":
            limits.append(LIMIT_TIE)
    fint_sign, fsrc, fcheck = None, None, None
    if "fint" in have:
        Fi = _vec(data["fint"], n)
        s = sg["fint"]
        if s == "auto":
            if F is not None and grade == "full":
                e_p = float(np.linalg.norm(F - Fi))
                e_m = float(np.linalg.norm(F + Fi))
                s, fsrc = (1.0 if e_p <= e_m else -1.0), "full_match"
            elif u_rel is not None:
                w = float(np.sum((Fi @ Rm) * np.asarray(u_rel, dtype=np.float64)))
                s, fsrc = (1.0 if w >= 0.0 else -1.0), "work_positive"
            else:
                s, fsrc = 1.0, "default"
        else:
            s, fsrc = _sign(s, "fint"), "config"
        fint_sign = float(s)
        if grade == "fint":
            F = fint_sign * Fi
            limits.append(LIMIT_DECOMP)
        else:
            nf = float(np.linalg.norm(fint_sign * Fi))
            fcheck = float(np.linalg.norm(F - fint_sign * Fi) / nf) if nf > 0 else None
    return {"grade": grade, "F": F, "F_ref": F @ Rm, "parts": parts, "m": m, "mass_source": msrc,
            "fint_sign": fint_sign, "fint_sign_source": fsrc, "fint_check_rel": fcheck,
            "decomposed": grade == "full", "limits": limits, "warnings": warns}


def equilibrium(X, F) -> dict:
    """합력·합모멘트(산술 중심 기준)와 상대값 force_rel = ‖ΣF‖/Σ‖F‖, moment_rel = ‖ΣM‖/(Σ‖F‖·L_bbox)."""
    X = np.asarray(X, dtype=np.float64)
    F = np.asarray(F, dtype=np.float64)
    c = X.mean(axis=0)
    sf = F.sum(axis=0)
    sm = np.cross(X - c, F).sum(axis=0)
    mag = np.linalg.norm(F, axis=1)
    sa = float(mag.sum())
    L = float(np.linalg.norm(X.max(axis=0) - X.min(axis=0))) if X.size else 0.0
    return {"sum_f": sf, "sum_m": sm, "center": c, "sum_abs": sa, "L_bbox": L,
            "force_rel": float(np.linalg.norm(sf) / sa) if sa > 0 else 0.0,
            "moment_rel": float(np.linalg.norm(sm) / (sa * L)) if sa > 0 and L > 0 else 0.0}


def rigid_modes(X, c) -> np.ndarray:
    """(N,3,6): 열 0~2 병진, 3~5 회전 e_k × (X − c)."""
    r = np.asarray(X, dtype=np.float64) - np.asarray(c, dtype=np.float64)
    N = r.shape[0]
    Rm = np.zeros((N, 3, 6))
    Rm[:, 0, 0] = Rm[:, 1, 1] = Rm[:, 2, 2] = 1.0
    Rm[:, 1, 3], Rm[:, 2, 3] = -r[:, 2], r[:, 1]          # e_x × r = (0, −r_z, r_y)
    Rm[:, 0, 4], Rm[:, 2, 4] = r[:, 2], -r[:, 0]          # e_y × r = (r_z, 0, −r_x)
    Rm[:, 0, 5], Rm[:, 1, 5] = -r[:, 1], r[:, 0]          # e_z × r = (−r_y, r_x, 0)
    return Rm


def inertia_relief(X, m, F) -> dict:
    """관성 이완: c = 질량 중심, ā = (RᵀMR)⁻¹RᵀF, F_bal = F − M R ā(자기평형 — RᵀF_bal = 0).
    반환 {F_bal, abar[6](병진 3 + 각가속도 3), center, mass_total, corr_rel = Σ‖M R ā‖ / Σ‖F‖}."""
    X = np.asarray(X, dtype=np.float64)
    F = np.asarray(F, dtype=np.float64)
    m = np.asarray(m, dtype=np.float64).reshape(-1)
    M = float(m.sum())
    if not M > 0 or np.any(m < 0):
        raise EslError("BF_MASS_INVALID", f"관성 이완 질량이 양수가 아님(합 {M})")
    c = (m[:, None] * X).sum(axis=0) / M
    Rm = rigid_modes(X, c)
    A = np.einsum("n,nik,nil->kl", m, Rm, Rm)
    b = np.einsum("nik,ni->k", Rm, F)
    abar = np.linalg.lstsq(A, b, rcond=None)[0]
    corr = m[:, None] * np.einsum("nik,k->ni", Rm, abar)
    sa = float(np.linalg.norm(F, axis=1).sum())
    return {"F_bal": F - corr, "abar": abar, "center": c, "mass_total": M,
            "corr_rel": float(np.linalg.norm(corr, axis=1).sum() / sa) if sa > 0 else 0.0}


def mac(u, v) -> float | None:
    """MAC = (u·v)² / ((u·u)(v·v)) — 병진 성분 평탄화. 한쪽이 0 이면 None."""
    a = np.asarray(u, dtype=np.float64).reshape(-1)
    b = np.asarray(v, dtype=np.float64).reshape(-1)
    den = float(a @ a) * float(b @ b)
    return float((a @ b) ** 2 / den) if den > 0 else None


def recon_report(u_rel, u_val_rel, reac, F) -> dict:
    """재현 비교: MAC, umax(기준·재현)·umax 오차(부호 있음 — (재현 − 기준)/기준), 반력 비(‖ΣR‖/Σ‖F‖·max‖R‖/max‖F‖)."""
    u = np.asarray(u_rel, dtype=np.float64)
    v = np.asarray(u_val_rel, dtype=np.float64)
    F = np.asarray(F, dtype=np.float64)
    um_r = float(np.linalg.norm(u, axis=1).max()) if u.size else 0.0
    um_v = float(np.linalg.norm(v, axis=1).max()) if v.size else 0.0
    fm = np.linalg.norm(F, axis=1)
    sa, fmax = float(fm.sum()), float(fm.max()) if fm.size else 0.0
    Rr = np.zeros((1, 3)) if reac is None else np.asarray(reac, dtype=np.float64)
    rm = np.linalg.norm(Rr, axis=1)
    return {"mac": mac(u, v), "umax_ref": um_r, "umax_val": um_v,
            "umax_err": float((um_v - um_r) / um_r) if um_r > 0 else None,
            "reaction_rel": float(np.linalg.norm(Rr.sum(axis=0)) / sa) if sa > 0 else 0.0,
            "reaction_max_rel": float(rm.max() / fmax) if fmax > 0 and rm.size else 0.0}


def _eq_short(e: dict) -> dict:
    return {"sum_f": [float(x) for x in e["sum_f"]], "sum_m": [float(x) for x in e["sum_m"]],
            "force_rel": float(e["force_rel"]), "moment_rel": float(e["moment_rel"])}


def build(X0, u_total, data: dict, m_deck=None, *, R=None, u_rel=None, use_inertia: bool = True,
          signs: dict | None = None, balance: str = "inertia_relief", g: float = 9810.0, F_full=None) -> dict:
    """조립 + 기준 형상 회전 + 균형 + 진단(§3.4·§3.5 — recon 제외). 반환 {F_bal (기준계 풀이 하중), F_raw (전역),
    m, doc (bforce.json 필드 — schema·grade… recon 없음)}. 등급 none = EslError BF_NO_DATA."""
    if balance not in BALANCES:
        raise EslError("CONFIG_INVALID", f"bforce.balance 는 {BALANCES}: {balance}")
    X0 = np.asarray(X0, dtype=np.float64)
    a = assemble(data, m_deck, use_inertia=use_inertia, signs=signs, R=R, u_rel=u_rel)
    F, Fr = a["F"], a["F_ref"]
    xdef = X0 + (np.zeros_like(X0) if u_total is None else np.asarray(u_total, dtype=np.float64))
    e_def, e_ref = equilibrium(xdef, F), equilibrium(X0, Fr)
    warns = list(a["warnings"])
    rel = {"abar": [0.0] * 6, "corr_rel": 0.0, "center": None, "mass_total": None}
    Fb = Fr
    if balance == "inertia_relief":
        m = a["m"]
        if m is None:
            raise EslError("BF_NO_MASS", "관성 이완에 질량이 필요(h3d MASS 또는 deck 근사)")
        ir = inertia_relief(X0, m, Fr)
        Fb = ir["F_bal"]
        rel = {"abar": [float(v) for v in ir["abar"]], "corr_rel": ir["corr_rel"], "center": ir["center"].tolist(),
               "mass_total": ir["mass_total"]}
    e_bal = equilibrium(X0, Fb)
    mag = np.linalg.norm(Fb, axis=1)
    imax = int(np.argmax(mag)) if mag.size else 0
    sa_full = None if F_full is None else float(np.linalg.norm(np.asarray(F_full, dtype=np.float64), axis=1).sum())
    sa = float(mag.sum())
    psa = {k: (None if v is None else float(np.linalg.norm(v, axis=1).sum())) for k, v in a["parts"].items()}
    doc = {"schema": SCHEMA, "grade": a["grade"], "decomposed": a["decomposed"], "formula": FORMULA[a["grade"]],
           "kinds": {k: data.get(k) is not None for k in KINDS}, "mass_source": a["mass_source"],
           "mass_total": None if a["m"] is None else float(np.sum(a["m"])),
           "use_inertia": bool(use_inertia), "balance": balance,
           "signs": {"cont": (signs or {}).get("cont", 1), "cont2": (signs or {}).get("cont2", 1),
                     "fint": a["fint_sign"] if a["fint_sign"] is not None else (signs or {}).get("fint", "auto")},
           "fint_sign_source": a["fint_sign_source"], "fint_check_rel": a["fint_check_rel"],
           "eq_raw": {"def": _eq_short(e_def), "ref": _eq_short(e_ref)}, "eq_bal": {"ref": _eq_short(e_bal)},
           "omitted_f": [float(-x) for x in e_ref["sum_f"]], "omitted_m": [float(-x) for x in e_ref["sum_m"]],
           "abar": rel["abar"], "abar_g": float(np.linalg.norm(rel["abar"][:3]) / float(g)) if g else None,
           "abar_rot": float(np.linalg.norm(rel["abar"][3:])), "corr_rel": rel["corr_rel"],
           "mass_center": rel["center"],
           "sum_abs": sa, "sum_abs_full": sa_full,
           "sum_abs_ratio_full": (sa / sa_full) if sa_full else None,
           "max_f": {"idx": imax, "mag": float(mag[imax]) if mag.size else 0.0},
           "n_nodes_loaded": int(np.sum(np.linalg.norm(F, axis=1) > 0)),
           "parts_sum_abs": psa, "limits": list(a["limits"]), "warnings": warns}
    return {"F_bal": Fb, "F_raw": F, "m": a["m"], "doc": doc}
