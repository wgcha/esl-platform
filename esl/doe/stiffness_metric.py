"""강성 지표 1차 섭동 — 재풀이 없는 순위 지표·강체 제거 표시·불평형 진단 (계약 esl_stiffness_metric.md SM-1~5).

모드 무관 순수 모듈(D-0.20.0-SM-5): 입력 배열(u_ref, S, K_t, F_t, C_ref …)만 받고 지표·진단을 돌려준다.
import 허용 = numpy·scipy.sparse·esl.errors·esl.mech.shell(``stiffness`` 안에서 조립 ``K()`` 만 — 분해 호출 없음).
esl.doe.* · 파일 IO · 설정 해석은 쓰지 않는다(전달 행렬 S 는 호출자가 ``load_transfer.build_disp`` 로 만들어 넘김).

정의(§2(3), ESL i·대상 t)::

    C_ref  = u_refᵀ K_A u_ref                 U2 = u_tᵀ K_t u_t,  u_t = S u_ref
    ρ      = U2 / C_ref
    C_lin  = C_ref (2 − ρ)   (lin_form taylor)     C_ritz = C_ref / ρ   (lin_form ritz)
    imbalance_rel = Σ_n ‖(F_t − K_t u_t)_n,병진‖ / Σ_n ‖F_t,n‖

순위식 기본(lin_form)은 ``LIN_FORM_DEFAULT`` 한 곳(Q-SM-1 사용자 확정 2026-11-13: ritz).
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from esl.errors import EslError

LIN_FORM_DEFAULT = "ritz"            # Q-SM-1 확정: ritz C_ref/ρ (taylor 는 설정 rank.lin_form 으로 선택)
LIN_FORMS = ("taylor", "ritz")
METRICS = ("lin", "solve")
LIN_VALID_DEFAULT = 0.3
IMBALANCE_WARN_DEFAULT = 0.02


# ---------------------------------------------------------------- 강체 6 dof (§2(5))
def _omega_mask(n: int, mask) -> np.ndarray | None:
    if mask is None:
        return None
    m = np.asarray(mask)
    if m.dtype == bool:
        if m.shape != (n,):
            raise EslError("INPUT_INVALID", f"mask 길이 {m.shape} ≠ 노드 수 {n}")
        return m
    b = np.zeros(n, bool)
    b[m.astype(np.int64)] = True
    return b


def rigid_fit(x, u6, mask=None):
    """최소제곱 강체 (a, ω, x̄): argmin Σ_{n∈Ω} ‖u_n − a − ω × (x_n − x̄)‖², w_n = 1, x̄ = Ω 노드 평균.

    x̄ 가 평균이라 a = Ω 의 u 평균으로 분리되고 ω 는 3×3 정규방정식 J ω = Σ r × u(J = Σ ‖r‖²I − r rᵀ) —
    6×6 정규방정식과 같은 해(블록 대각). u6 는 (N,3)|(N,6)(병진만 씀). mask = Ω(노드 bool 또는 인덱스), None = 전체."""
    x = np.asarray(x, dtype=np.float64)
    u = np.asarray(u6, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 3 or u.ndim != 2 or u.shape[0] != x.shape[0] or u.shape[1] not in (3, 6):
        raise EslError("INPUT_INVALID", "x (N,3), u (N,3|6)")
    m = _omega_mask(x.shape[0], mask)
    xs, us = (x, u[:, :3]) if m is None else (x[m], u[m, :3])
    if xs.shape[0] < 3:
        raise EslError("INPUT_INVALID", "강체 맞춤 노드가 3개 미만")
    xb = xs.mean(axis=0)
    r = xs - xb
    a = us.mean(axis=0)
    J = np.eye(3) * float(np.einsum("ij,ij->", r, r)) - r.T @ r
    b = np.cross(r, us - a).sum(axis=0)
    w, V = np.linalg.eigh(J)
    if not w[-1] > 0 or w[0] <= 1e-12 * w[-1]:
        raise EslError("INPUT_INVALID", "강체 맞춤 노드가 한 직선 위(rank < 6)")
    om = V @ ((V.T @ b) / w)
    return a, om, xb


def remove_rigid(x, u6, mask=None) -> np.ndarray:
    """u_def = u − a − ω × (x − x̄)(전 노드), θ_def = θ − ω(u6 가 (N,6) 일 때). (a, ω) 는 Ω 로 맞춤."""
    x = np.asarray(x, dtype=np.float64)
    u = np.array(u6, dtype=np.float64, copy=True)
    a, om, xb = rigid_fit(x, u, mask)
    u[:, :3] -= a + np.cross(om, x - xb)
    if u.shape[1] == 6:
        u[:, 3:] -= om
    return u


def umax_def(x, u6, mask=None) -> float:
    """강체 제거 후 max_{n∈Ω} ‖u_def,n‖(표시 전용)."""
    ud = remove_rigid(x, u6, mask)[:, :3]
    m = _omega_mask(ud.shape[0], mask)
    if m is not None:
        ud = ud[m]
    return float(np.max(np.linalg.norm(ud, axis=1))) if ud.size else 0.0


# ---------------------------------------------------------------- 전달 (§2(2))
def apply_disp(S, u6, R=None) -> np.ndarray:
    """u_t = S u_ref(성분 공통). S = scipy.sparse (N_t×N_A) | 정수 index 배열(순열·부분, u_t[k] = u[S[k]]) | None(I).
    R(3×3, 배치 rigid·frame) 이면 보간 뒤 병진·회전 3-벡터를 각각 R 로 돌림."""
    u = np.asarray(u6, dtype=np.float64)
    if u.ndim != 2 or u.shape[1] not in (3, 6):
        raise EslError("INPUT_INVALID", "u (N,3|6)")
    if S is None:
        out = u.copy()
    elif sp.issparse(S):
        if S.shape[1] != u.shape[0]:
            raise EslError("INPUT_INVALID", f"S 열 {S.shape[1]} ≠ 원본 노드 {u.shape[0]}")
        out = np.asarray(sp.csr_matrix(S) @ u, dtype=np.float64)
    else:
        idx = np.asarray(S)
        if idx.ndim != 1 or idx.dtype.kind not in "iu":
            raise EslError("INPUT_INVALID", "S 는 sparse 행렬·정수 index 배열·None")
        out = u[idx.astype(np.int64)]
    if R is not None:
        Rm = np.asarray(R, dtype=np.float64)
        if Rm.shape != (3, 3):
            raise EslError("INPUT_INVALID", "R 은 3×3")
        out = out.copy()
        for k in range(0, out.shape[1], 3):
            out[:, k:k + 3] = out[:, k:k + 3] @ Rm.T
    return out


# ---------------------------------------------------------------- 조립 (분해 없음)
def stiffness(mesh_t: dict, solver_cfg: dict | None = None, elem_mask=None) -> sp.csr_matrix:
    """대상 강성 K_t(6N_t×6N_t, 지지 없음) — ``ShellModel(...).K()`` 조립만. elem_mask(요소 bool) = Ω 요소만 조립
    (노드 번호는 그대로 — 영역 밖 노드 행은 0). 조립은 백엔드와 무관하므로 superlu 로 만들어 백엔드 탐색·경고를 피함."""
    from esl.mech.shell import ShellModel
    cfg = solver_cfg or {}
    conn = np.asarray(mesh_t["conn"], dtype=np.int64)
    et = np.asarray(mesh_t["elem_type"])
    ne = conn.shape[0]

    def per_elem(v):
        a = np.asarray(v, dtype=np.float64)
        return a if a.ndim == 0 else np.broadcast_to(a, (ne,))

    t, E, nu = per_elem(mesh_t["thickness"]), per_elem(mesh_t["E"]), per_elem(mesh_t["nu"])
    if elem_mask is not None:
        m = np.asarray(elem_mask, bool)
        if m.shape != (ne,):
            raise EslError("INPUT_INVALID", f"elem_mask 길이 {m.shape} ≠ 요소 수 {ne}")
        conn, et = conn[m], et[m]
        t, E, nu = (v if v.ndim == 0 else v[m] for v in (t, E, nu))
    sm = ShellModel(mesh_t["x0"], conn, et, t, E, nu, drill_factor=float(cfg.get("drill_factor", 1e-4)),
                    backend="superlu")
    return sm.K()


# ---------------------------------------------------------------- 지표 (§2(3))
def _flat6(u6, n_dof: int | None = None) -> np.ndarray:
    u = np.asarray(u6, dtype=np.float64)
    if u.ndim != 2 or u.shape[1] != 6:
        raise EslError("INPUT_INVALID", "u 는 (N,6) — 회전 포함")
    v = u.reshape(-1)
    if n_dof is not None and v.size != n_dof:
        raise EslError("INPUT_INVALID", f"u 자유도 {v.size} ≠ K {n_dof}")
    return v


def reference(K_A, u_ref6, F_A=None) -> dict:
    """C_ref = u_refᵀ K_A u_ref(A 변형에너지 2배), bal = |F_Aᵀu_ref − C_ref| / C_ref(반력 일·자기평형 확인, F_A 있을 때)."""
    v = _flat6(u_ref6, K_A.shape[0])
    C = float(v @ (K_A @ v))
    out = {"C_ref": C, "bal": None}
    if F_A is not None:
        F = np.asarray(F_A, dtype=np.float64)
        w = float(np.sum(F * np.asarray(u_ref6, dtype=np.float64)[:, :3]))
        out["bal"] = abs(w - C) / C if C > 0 else None
    return out


def lin_value(C_ref: float, rho: float, lin_form: str = LIN_FORM_DEFAULT) -> float:
    if lin_form == "taylor":
        return float(C_ref * (2.0 - rho))
    if lin_form == "ritz":
        return float(C_ref / rho)
    raise EslError("CONFIG_INVALID", f"rank.lin_form {lin_form} — {list(LIN_FORMS)}")


def metrics(K_t, u_t6, F_t, C_ref: float, *, lin_valid: float = LIN_VALID_DEFAULT,
            imbalance_warn: float = IMBALANCE_WARN_DEFAULT, node_mask=None, entry_id=None) -> dict:
    """대상 지표 {U2, rho, C_lin, C_ritz, imbalance_rel, warnings[]}. 조립 K_t 와 SpMV 1회만(분해 없음).

    F_t(N,3) = 해석 하중(불평형 진단 전용, None 이면 imbalance_rel = None). node_mask = Ω 노드(불평형 합 범위, None = 전체).
    경고: |ρ−1| > lin_valid 또는 C_lin ≤ 0 → SM_LIN_RANGE, imbalance_rel > imbalance_warn → SM_IMBALANCE."""
    C_ref = float(C_ref)
    if not C_ref > 0:
        raise EslError("INPUT_INVALID", f"C_ref 가 양수가 아님 ({C_ref})")
    v = _flat6(u_t6, K_t.shape[0])
    Kv = K_t @ v
    U2 = float(v @ Kv)
    rho = U2 / C_ref
    C_lin = C_ref * (2.0 - rho)
    C_ritz = C_ref / rho if rho > 0 else None
    imb = None
    if F_t is not None:
        F = np.asarray(F_t, dtype=np.float64)
        r = F - Kv.reshape(-1, 6)[:, :3]
        m = _omega_mask(F.shape[0], node_mask)
        if m is not None:
            F, r = F[m], r[m]
        den = float(np.linalg.norm(F, axis=1).sum())
        imb = float(np.linalg.norm(r, axis=1).sum()) / den if den > 0 else None
    warns = []
    tag = {} if entry_id is None else {"entry_id": entry_id}
    if abs(rho - 1.0) > float(lin_valid) or not C_lin > 0:
        warns.append({"code": "SM_LIN_RANGE", **tag, "rho": rho})
    if imb is not None and imb > float(imbalance_warn):
        warns.append({"code": "SM_IMBALANCE", **tag, "imbalance_rel": imb})
    return {"U2": U2, "rho": rho, "C_lin": C_lin, "C_ritz": C_ritz, "imbalance_rel": imb, "warnings": warns}


def ts_err(F_A, T, u_t6, u_ref6, C_ref: float) -> float:
    """전달 일관성 |F_Aᵀ(T S u_ref − u_ref)| / C_ref — T(N_A×N_t, 대상 변위 → A 노드 보간, 하중 전달 W), u_t = S u_ref."""
    back = apply_disp(T, np.asarray(u_t6, dtype=np.float64)[:, :3])
    F = np.asarray(F_A, dtype=np.float64)
    return abs(float(np.sum(F * (back - np.asarray(u_ref6, dtype=np.float64)[:, :3])))) / float(C_ref)


# ---------------------------------------------------------------- 순위 값 (§2(4))
def metric_key(metric: str, lin_form: str = LIN_FORM_DEFAULT) -> str:
    """per_esl 행에서 순위 값으로 쓸 키: solve → C, lin → C_ritz | C_lin."""
    if metric == "solve":
        return "C"
    if metric == "lin":
        if lin_form not in LIN_FORMS:
            raise EslError("CONFIG_INVALID", f"rank.lin_form {lin_form} — {list(LIN_FORMS)}")
        return "C_ritz" if lin_form == "ritz" else "C_lin"
    raise EslError("CONFIG_INVALID", f"rank.metric {metric} — {list(METRICS)}")


def out_of_range(per_esl: list[dict], lin_valid: float) -> bool:
    """R-SM-1 결정(2026-11-13): 한 안의 ESL 중 하나라도 |ρ−1| > lin_valid(1차 근사 범위 밖)면 참 — 그 안의 순위 값은 재풀이 C.
    ρ 가 없는(null) ESL 은 판정에서 뺌."""
    return any(p.get("rho") is not None and abs(float(p["rho"]) - 1.0) > float(lin_valid) for p in per_esl)


def score(per_esl: list[dict], metric: str, lin_form: str = LIN_FORM_DEFAULT) -> dict:
    """한 안의 per_esl → {M{entry_id: 값|None}, worst(argmax, 동률 = 앞), M_max, missing[entry_id]}.
    값이 None(SM_SKIPPED) 인 ESL 은 missing 에 모으고 최악 계산에서 뺌."""
    k = metric_key(metric, lin_form)
    M, miss, w, wv = {}, [], None, None
    for p in per_esl:
        x = p.get(k)
        M[p["entry_id"]] = None if x is None else float(x)
        if x is None:
            miss.append(p["entry_id"])
            continue
        if w is None or float(x) > wv:
            w, wv = p["entry_id"], float(x)
    return {"key": k, "M": M, "worst": w, "M_max": wv, "missing": miss}
