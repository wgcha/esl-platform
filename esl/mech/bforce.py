"""경계력 ESL 하중 조립 — 낙하 해석이 계산한 노드 힘을 하중으로 (계약 docs/contracts/esl_bforce.md §0·§3, v0.24.0).

경계력 ESL(접촉력 전용 — D-0.24.0-BF-12): F = s_c·CONT + s_t·CONT2 − M·ACC (= 노드 내력, M a = F_ext − F_int).
등급 full(CONT + CONT2) > contact(CONT만 — tie 체결력 미포함, 불평형은 관성 이완) > none. FINT 는 등급에 쓰지 않음(full 검산만).
내력 ESL(별도 출처 fint — esl_fint.md §1, D-0.24.0-BF-13): F = s_f·FINT(``fint_build`` — 자기평형, 잔차 진단, 균형 기본 none).

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
LIMIT_DECOMP = "BF_NO_DECOMP"         # (v0.24.0 초안 fint 등급 — 경계력에서는 더 쓰지 않음, 문구만 유지)
LIMIT_ROT = "FINT_ROT_LINKS"          # 내력 ESL 한계: 회전 연결 노드(RBODY·스프링·빔)의 노드 모멘트 미사용(esl_fint.md §12)
LIMIT_TEXT = {LIMIT_TIE: "tie 체결력 미포함 — 조립 부품 하중 누락", LIMIT_DECOMP: "내력만(접촉·관성 분해 없음)",
              LIMIT_ROT: "회전 연결 노드(RBODY·스프링·빔) 노드 모멘트 미사용"}   # 한계 문구 원본 1곳
FINT_SCHEMA_SOURCE = "fint"           # 내력 ESL 진단 = 같은 스키마(esl/bforce/1) + source
CODE_UNBAL = "FINT_UNBALANCED"
CODE_SHARED = "FINT_SHARED_NODES"
CODE_SIGN = "BF_SIGN_SUSPECT"
FORMULA = {"full": "F = CONT + CONT2 − M·ACC", "fint": "F = s·FINT", "contact": "F = CONT − M·ACC"}


def grade_of(have) -> str:
    """있는 종류 집합 → 경계력 ESL 등급(접촉력 전용 — full > contact > none, FINT 무관 — D-0.24.0-BF-12)."""
    h = set(have)
    if "cont" in h and "cont2" in h:
        return "full"
    if "cont" in h:
        return "contact"
    return "none"


def fint_grade_of(have) -> str:
    """있는 종류 집합 → 내력 ESL 등급(fint | none — esl_fint.md §0)."""
    return "fint" if "fint" in set(have) else "none"


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
        raise EslError("BF_NO_DATA", f"경계력 자료 없음(접촉력 없음) — 있는 종류 {sorted(have)}")
    sg = {"cont": 1, "cont2": 1, "fint": "auto", **(signs or {})}
    n = _vec(data["cont"]).shape[0]
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
    if "fint" in have and grade == "full":            # FINT 검산(full 만 — contact 는 tie 누락분이 섞여 검산 무의미)
        Fi = _vec(data["fint"], n)
        s, fsrc = fint_sign_of(Fi, sg["fint"], F_full=F)
        fint_sign = float(s)
        nf = float(np.linalg.norm(fint_sign * Fi))
        fcheck = float(np.linalg.norm(F - fint_sign * Fi) / nf) if nf > 0 else None
    return {"grade": grade, "F": F, "F_ref": F @ Rm, "parts": parts, "m": m, "mass_source": msrc,
            "fint_sign": fint_sign, "fint_sign_source": fsrc, "fint_check_rel": fcheck,
            "decomposed": grade == "full", "limits": limits, "warnings": warns}


def fint_sign_of(Fi, s="auto", *, F_full=None, R=None, u_rel=None) -> tuple[float, str]:
    """FINT 부호 s(1 | −1)와 출처: 설정 값(config) | auto — F_full 이 있으면 ‖F_full − s·FINT‖ 최소(full_match), 아니면
    Σ s·(FINT Rᵀ)·u_rel ≥ 0(work_positive — 내력이 변형에 양의 일), 둘 다 없으면 1(default)."""
    if s != "auto":
        return _sign(s, "fint"), "config"
    Fi = np.asarray(Fi, dtype=np.float64)
    if F_full is not None:
        e_p = float(np.linalg.norm(F_full - Fi))
        e_m = float(np.linalg.norm(F_full + Fi))
        return (1.0 if e_p <= e_m else -1.0), "full_match"
    if u_rel is not None:
        Rm = np.eye(3) if R is None else np.asarray(R, dtype=np.float64)
        w = float(np.sum((Fi @ Rm) * np.asarray(u_rel, dtype=np.float64)))
        return (1.0 if w >= 0.0 else -1.0), "work_positive"
    return 1.0, "default"


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


def limit_text(codes) -> list[str]:
    return [LIMIT_TEXT.get(x, x) for x in codes]


def sign_check(X0, data: dict, m_deck=None, *, use_inertia: bool = True, signs: dict | None = None, R=None,
               g: float = 9810.0) -> dict | None:
    """CONT 부호 가정 점검(진단 전용 — 결과를 바꾸지 않음). contact·full 등급에서 접촉 항(CONT·CONT2)의 설정 부호 F 와
    반전 부호 F′ 의 불평형 force_rel = ‖ΣF‖/Σ‖F‖ 와 관성 이완 ā(g)를 비교한다. 설정 쪽이 force_rel 이 더 크고(질량이 있으면 ā 도
    더 클 때) = suspect. 해당 없음(fint 등급·접촉력 없음) = None. 반환 {suspect, force_rel, force_rel_flip, abar_g, abar_g_flip}."""
    have = {k for k in KINDS if data.get(k) is not None}
    if grade_of(have) not in ("full", "contact"):
        return None
    sg = {"cont": 1, "cont2": 1, **{k: v for k, v in (signs or {}).items() if k in ("cont", "cont2")}}
    flip = {k: -_sign(v, k) for k, v in sg.items()}
    X0 = np.asarray(X0, dtype=np.float64)

    def _one(sgn: dict) -> tuple[float, float | None]:
        a = assemble(data, m_deck, use_inertia=use_inertia, signs=sgn, R=R)
        Fr = a["F_ref"]
        fr = equilibrium(X0, Fr)["force_rel"]
        if a["m"] is None or not float(np.sum(a["m"])) > 0:
            return fr, None
        ab = inertia_relief(X0, a["m"], Fr)["abar"]
        return fr, float(np.linalg.norm(ab[:3]) / float(g)) if g else None

    fr, ag = _one(sg)
    fr_f, ag_f = _one(flip)
    worse = fr > fr_f
    if ag is not None and ag_f is not None:
        worse = worse and ag > ag_f
    return {"suspect": bool(worse), "force_rel": fr, "force_rel_flip": fr_f, "abar_g": ag, "abar_g_flip": ag_f}


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
    sc = None
    try:
        sc = sign_check(X0, data, m_deck, use_inertia=use_inertia, signs=signs, R=R, g=g)
    except EslError:
        sc = None
    if sc is not None and sc["suspect"]:
        warns.append({"code": CODE_SIGN, "force_rel": sc["force_rel"], "force_rel_flip": sc["force_rel_flip"],
                      "abar_g": sc["abar_g"], "abar_g_flip": sc["abar_g_flip"]})
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
           "sign_check": sc,
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


def fint_build(X0, u_total, fint, m=None, *, mass_source: str | None = None, R=None, u_rel=None, sign="auto",
               balance: str = "none", tol_force: float = 1e-3, tol_moment: float = 1e-3, links: dict | None = None,
               kinds: dict | None = None, g: float = 9810.0, F_full=None) -> dict:
    """내력 ESL(esl_fint.md §1 — D-0.24.0-BF-13): F = s·FINT(전역) → F_ref = F Rᵀ(행 표기 F @ R) → 균형(기본 none).
    잔차 = 변형 형상(x_def = X0 + u_total) 합력·합모멘트 상대값 — 부품 요소 내력은 자기평형이라 ≈ 0, 허용치(tol_force·tol_moment)
    초과 = unbalanced + 경고 FINT_UNBALANCED. balance inertia_relief 는 unbalanced 일 때만 관성 이완(질량 m 필요 — 없으면
    경고 FINT_NO_MASS, 이완 없음). links = 공유·회전 연결 노드 진단(esl.rad.shared.node_links — 표시만, 내력 그대로 사용).
    반환 {F_bal (기준계 풀이 하중), F_raw (전역), m, doc (esl/bforce/1 필드 + source·fint 블록 — recon 없음)}."""
    if balance not in BALANCES:
        raise EslError("CONFIG_INVALID", f"bforce.fint.balance 는 {BALANCES}: {balance}")
    X0 = np.asarray(X0, dtype=np.float64)
    Fi = _vec(fint, X0.shape[0])
    Rm = np.eye(3) if R is None else np.asarray(R, dtype=np.float64)
    s, ssrc = fint_sign_of(Fi, sign, R=Rm, u_rel=u_rel)
    F = float(s) * Fi
    Fr = F @ Rm
    xdef = X0 + (np.zeros_like(X0) if u_total is None else np.asarray(u_total, dtype=np.float64))
    e_def, e_ref = equilibrium(xdef, F), equilibrium(X0, Fr)
    unbal = bool(e_def["force_rel"] > float(tol_force) or e_def["moment_rel"] > float(tol_moment))
    warns: list = []
    if unbal:
        warns.append({"code": CODE_UNBAL, "force_rel": e_def["force_rel"], "moment_rel": e_def["moment_rel"],
                      "tol_force": float(tol_force), "tol_moment": float(tol_moment)})
    mm = None if m is None else np.asarray(m, dtype=np.float64).reshape(-1)
    if mm is not None and mm.size != X0.shape[0]:
        raise EslError("INPUT_INVALID", f"질량 길이 {mm.size} ≠ 노드 수 {X0.shape[0]}")
    rel = {"abar": [0.0] * 6, "corr_rel": 0.0, "center": None}
    Fb, applied = Fr, "none"
    if balance == "inertia_relief" and unbal:
        if mm is None or not float(mm.sum()) > 0:
            warns.append({"code": "FINT_NO_MASS"})
        else:
            ir = inertia_relief(X0, mm, Fr)
            Fb, applied = ir["F_bal"], "inertia_relief"
            rel = {"abar": [float(v) for v in ir["abar"]], "corr_rel": ir["corr_rel"], "center": ir["center"].tolist()}
    e_bal = equilibrium(X0, Fb)
    lk = links or {"status": "skipped"}
    n_sh = int(lk.get("n_shared") or 0) if lk.get("status") == "ok" else 0
    n_rot = int(lk.get("n_rot") or 0) if lk.get("status") == "ok" else 0
    if n_sh > 0:
        warns.append({"code": CODE_SHARED, "n": n_sh, "by_part": lk.get("by_part")})
    limits = [LIMIT_ROT] if n_rot > 0 else []
    mag = np.linalg.norm(Fb, axis=1)
    imax = int(np.argmax(mag)) if mag.size else 0
    sa = float(mag.sum())
    sa_full = None if F_full is None else float(np.linalg.norm(np.asarray(F_full, dtype=np.float64), axis=1).sum())
    doc = {"schema": SCHEMA, "source": FINT_SCHEMA_SOURCE, "grade": "fint", "decomposed": False, "formula": FORMULA["fint"],
           "kinds": dict(kinds) if kinds is not None else {k: k == "fint" for k in KINDS},
           "mass_source": mass_source if applied == "inertia_relief" else None,
           "mass_total": None if mm is None or applied != "inertia_relief" else float(mm.sum()),
           "use_inertia": False, "balance": balance, "signs": {"fint": float(s)}, "sign_check": None,
           "fint_sign_source": ssrc, "fint_check_rel": None,
           "eq_raw": {"def": _eq_short(e_def), "ref": _eq_short(e_ref)}, "eq_bal": {"ref": _eq_short(e_bal)},
           "omitted_f": [float(-x) for x in e_ref["sum_f"]], "omitted_m": [float(-x) for x in e_ref["sum_m"]],
           "abar": rel["abar"], "abar_g": float(np.linalg.norm(rel["abar"][:3]) / float(g)) if g else None,
           "abar_rot": float(np.linalg.norm(rel["abar"][3:])), "corr_rel": rel["corr_rel"], "mass_center": rel["center"],
           "sum_abs": sa, "sum_abs_full": sa_full, "sum_abs_ratio_full": (sa / sa_full) if sa_full else None,
           "max_f": {"idx": imax, "mag": float(mag[imax]) if mag.size else 0.0},
           "n_nodes_loaded": int(np.sum(np.linalg.norm(F, axis=1) > 0)),
           "parts_sum_abs": {"cont": None, "cont2": None, "inertia": None},
           "fint": {"residual": {"force_rel": e_def["force_rel"], "moment_rel": e_def["moment_rel"]},
                    "tol": {"force_rel": float(tol_force), "moment_rel": float(tol_moment)}, "unbalanced": unbal,
                    "balance": balance, "balance_applied": applied, "shared_nodes": lk,
                    "rot_nodes": {"n": n_rot, **({k: lk[k] for k in ("rot", "rot_node_ids", "rbody_unresolved") if k in lk})}},
           "limits": limits, "warnings": warns}
    return {"F_bal": Fb, "F_raw": F, "m": mm if applied == "inertia_relief" else None, "doc": doc}


def plastic_diag(epsp, area, eps_min: float) -> dict:
    """소성 진단(esl_fint.md §4 — 계산 변경 없음): 요소 εᵖ(t*)·면적 → {status ok, eps_min, frac(면적 비율 εᵖ > eps_min), max, n,
    n_total}. εᵖ 없음(None·전부 NaN) = {status: "none"}."""
    if epsp is None:
        return {"status": "none"}
    e = np.asarray(epsp, dtype=np.float64).reshape(-1)
    A = np.asarray(area, dtype=np.float64).reshape(-1)
    if e.size != A.size:
        raise EslError("INPUT_INVALID", f"소성 변형률 길이 {e.size} ≠ 요소 수 {A.size}")
    ok = np.isfinite(e)
    if not ok.any():
        return {"status": "none"}
    hit = ok & (e > float(eps_min))
    At = float(A[ok].sum())
    return {"status": "ok", "eps_min": float(eps_min), "frac": float(A[hit].sum() / At) if At > 0 else 0.0,
            "max": float(e[ok].max()), "n": int(hit.sum()), "n_total": int(ok.sum())}
