"""지그 ESL 경계 3방식 · tie 구속 성분 · 3-2-1 면내 · 스프링 · 순위 지표 Π (계약 docs/contracts/esl_jig_case.md §2.2·§2.3·§3·§4.2,
결정 D-0.24.4-JIG-2~10).

- 방식 표 ``METHODS``(fixed 고정 · prescribed 강제 변위 · spring 스프링)·tie 구속 성분 표 ``TIE_DOFS``(normal 법선 — 새 기본 ·
  translation 병진 — 옛). 호출부(Case ``pipeline._jig_esl``·스터디 ``stages._jig_*``·검증 ``_SUPPORT_FN``)는 **열 값만** 읽고
  방식·출처 이름으로 분기하지 않는다(AGENTS.md D-0.20.0-CODE). 이 모듈 안도 같은 규칙(열 값으로 동작을 고름).
- 경계 = 구속 행 (노드, 단위 방향 d̂, 값 v)(d̂ᵀu = v) + 스프링 행 (노드, d̂, k, 바닥 g). 해는 ``ShellModel.factorize_bc``
  (국부 틀) 또는 축 방향 구속만이면 ``ShellModel.factorize``(옛 spc 경로 — 같은 해) — 자료로 고름(이름 분기 없음).
- 순위 지표: 정규화 혼합 컴플라이언스 C_mix = Fᵀu − Σ v_c r_c − Σ g_s f_s(= −2Π*), E = 2U_tot, s = 1 + ΔC_mix/E_0(§3.8).

모드 무관 독립 순수 모듈: import = numpy · esl.errors · esl.mech.{shell, kabsch, supports, mass, jig}. 파일 IO·설정 파일 해석 없음
(값은 인수 — 기본값 = ``esl.mech.jig.JIG_DEFAULTS``). 결정적(정렬·부호 규칙 고정).
"""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from esl.errors import EslError
from esl.mech import jig, kabsch, supports
from esl.mech.mass import elem_area_normal
from esl.mech.shell import mesh_components, rigid_rank

# ====================================================================== 계획 표(선언)
METHOD_COLS = ("src", "tie_value", "tie_stiff", "frame", "factor", "tie_rel_warn", "limits", "name")
METHODS: dict[str, dict[str, Any]] = {
    "fixed": {"src": "jig", "tie_value": "zero", "tie_stiff": "hard", "frame": "jig_kabsch", "factor": "own",
              "tie_rel_warn": True, "limits": (), "name": "고정"},
    "prescribed": {"src": "jig_disp", "tie_value": "target", "tie_stiff": "hard", "frame": "part", "factor": "fixed",
                   "tie_rel_warn": False, "limits": ("JIG_DISP_FROM_TARGET",), "name": "강제 변위"},
    "spring": {"src": "jig_spring", "tie_value": "target", "tie_stiff": "spring", "frame": "part", "factor": "own",
               "tie_rel_warn": False, "limits": (), "name": "스프링"},
}
TIE_COLS = ("dirs", "aux321", "text")
TIE_DOFS: dict[str, dict[str, Any]] = {
    "normal": {"dirs": "normal_subspace", "aux321": "inplane", "text": "tie 면외(법선)"},
    "translation": {"dirs": "xyz", "aux321": "none", "text": "tie 병진 123"},
}
# 옛 스냅샷(rank.jig 에 tie_dofs·methods 키 없음)의 뜻 — DEFAULTS(normal·세 방식)와 다름(V-0244-JIG-15, 코드 상수 한 곳)
LEGACY_ABSENT: dict[str, Any] = {"tie_dofs": "translation", "methods": ("fixed",)}
COL_VALUES = {"tie_value": ("zero", "target"), "tie_stiff": ("hard", "spring"), "frame": ("jig_kabsch", "part"),
              "factor": ("own", "fixed"), "dirs": ("normal_subspace", "xyz"), "aux321": ("inplane", "none")}
KIND_TIE, KIND_AUX = 1, 2               # bc_kind: tie 구속 · 3-2-1 면내
# v0.24.6 지그 3D 지지 표식 dof 문자열(표시만 — support_marks): tie · 3-2-1 면내. 백엔드 Case view3d JIG_TIE_DOF·JIG_AUX_DOF 와 같은 값
MARK_TIE, MARK_AUX = "123", "ij"
SPRING_ALPHA_MIN = 1e-3                 # α 하한(§3.4 — k → 0 이면 normal 은 면외 강체가 스프링으로만 막혀 조건수 악화)
SPRING_K_MODES = ("auto", "value")
BC_KEYS = ("bc_node", "bc_dir", "bc_val", "bc_kind", "sp_node", "sp_dir", "sp_k", "sp_g")


def check_plan() -> None:
    """두 표의 모든 행이 모든 열을 채웠고 값이 허용 집합 안인지(빈 칸·모르는 값 = CONFIG_INVALID). fixed 공유 열이 가리키는
    방식은 자기 분해(own)여야 함."""
    for name, row in METHODS.items():
        miss = [c for c in METHOD_COLS if c not in row or row[c] is None or (row[c] == "" and c != "limits")]
        if miss:
            raise EslError("CONFIG_INVALID", f"jig_bc.METHODS[{name}] 빈 열 {miss}")
        for c, ok in COL_VALUES.items():
            if c in row and row[c] not in ok:
                raise EslError("CONFIG_INVALID", f"jig_bc.METHODS[{name}].{c} = {row[c]!r} ∉ {ok}")
        if not isinstance(row["limits"], tuple) or not isinstance(row["tie_rel_warn"], bool):
            raise EslError("CONFIG_INVALID", f"jig_bc.METHODS[{name}] limits(튜플)·tie_rel_warn(bool)")
        if row["factor"] != "own" and METHODS.get(row["factor"], {}).get("factor") != "own":
            raise EslError("CONFIG_INVALID", f"jig_bc.METHODS[{name}].factor 가 자기 분해 방식을 가리키지 않음")
    for name, row in TIE_DOFS.items():
        miss = [c for c in TIE_COLS if not row.get(c)]
        if miss:
            raise EslError("CONFIG_INVALID", f"jig_bc.TIE_DOFS[{name}] 빈 열 {miss}")
        for c, ok in COL_VALUES.items():
            if c in row and row[c] not in ok:
                raise EslError("CONFIG_INVALID", f"jig_bc.TIE_DOFS[{name}].{c} = {row[c]!r} ∉ {ok}")
    if len({r["src"] for r in METHODS.values()}) != len(METHODS):
        raise EslError("CONFIG_INVALID", "jig_bc.METHODS src 중복")
    if sum(1 for r in METHODS.values() if r["factor"] == "own" and r["tie_stiff"] == "hard") != 1:
        raise EslError("CONFIG_INVALID", "jig_bc.METHODS: 공유 기저 분해(factor own ∧ tie_stiff hard) 행은 정확히 1개")


def tie_dofs_of(jig_cfg: dict) -> str:
    """스냅샷·설정의 tie 구속 성분 — 키 없음 = LEGACY_ABSENT(translation)."""
    return str(jig_cfg.get("tie_dofs", LEGACY_ABSENT["tie_dofs"]))


def methods_of(jig_cfg: dict) -> tuple[str, ...]:
    """스냅샷·설정의 방식 목록(설정 순서) — 키 없음 = LEGACY_ABSENT(fixed 만)."""
    m = jig_cfg.get("methods")
    return tuple(LEGACY_ABSENT["methods"]) if m is None else tuple(str(x) for x in m)


def check_cfg(jig_cfg: dict) -> None:
    """새 키 값 검사(§11 스키마 — 형식 오류 = CONFIG_INVALID): tie_dofs ∈ TIE_DOFS, methods ⊂ METHODS(비어 있지 않음·중복 없음),
    normal_kink_deg ∈ (0, 180), aux321_dup_deg ∈ [0, 90), aux_reaction_warn ≥ 0, spring_k_mode ∈ (auto, value),
    spring_alpha ≥ 1e-3, value 모드 ⇒ spring_k_value > 0, spring_alpha_scan = α 목록(각 ≥ 1e-3). 없는 키는 검사 안 함."""
    def bad(msg):
        raise EslError("CONFIG_INVALID", f"jig: {msg}")
    if "tie_dofs" in jig_cfg and jig_cfg["tie_dofs"] not in TIE_DOFS:
        bad(f"tie_dofs {jig_cfg['tie_dofs']!r} ∉ {tuple(TIE_DOFS)}")
    if "methods" in jig_cfg:
        m = jig_cfg["methods"]
        if not isinstance(m, (list, tuple)) or not m or len(set(m)) != len(m) or any(x not in METHODS for x in m):
            bad(f"methods {m!r} — {tuple(METHODS)} 의 비어 있지 않은 부분집합(중복 없음)")

    def num(k, lo, hi=None, lo_open=False):
        if k not in jig_cfg:
            return
        v = jig_cfg[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or \
                (v <= lo if lo_open else v < lo) or (hi is not None and v >= hi):
            bad(f"{k} = {v!r} 범위 밖")
    num("normal_kink_deg", 0.0, 180.0, lo_open=True)
    num("aux321_dup_deg", 0.0, 90.0)
    num("aux_reaction_warn", 0.0)
    num("spring_alpha", SPRING_ALPHA_MIN)
    if "spring_k_mode" in jig_cfg and jig_cfg["spring_k_mode"] not in SPRING_K_MODES:
        bad(f"spring_k_mode {jig_cfg['spring_k_mode']!r} ∉ {SPRING_K_MODES}")
    kv = jig_cfg.get("spring_k_value")
    if kv is not None and (isinstance(kv, bool) or not isinstance(kv, (int, float)) or not np.isfinite(kv) or kv <= 0):
        bad(f"spring_k_value = {kv!r}(> 0 N/mm 또는 null)")
    if jig_cfg.get("spring_k_mode") == "value" and kv is None:
        bad("spring_k_mode = value 이면 spring_k_value(> 0 N/mm) 필요")
    sc = jig_cfg.get("spring_alpha_scan", [])
    if not isinstance(sc, (list, tuple)) or any(isinstance(a, bool) or not isinstance(a, (int, float)) or
                                                 not np.isfinite(a) or a < SPRING_ALPHA_MIN for a in sc):
        bad(f"spring_alpha_scan = {sc!r}(α ≥ {SPRING_ALPHA_MIN} 목록)")


def basis_method() -> str:
    """하중 기저·모드를 계산하는 공유 분해의 방식(열로 고름: factor = own ∧ tie_stiff = hard — 세 방식 공통 구속 집합, §3.4
    "모드 기저는 fixed 구속(값 0)으로 1회"). 표에 정확히 1행(check_plan)."""
    rows = [m for m, r in METHODS.items() if r["factor"] == "own" and r["tie_stiff"] == "hard"]
    if len(rows) != 1:
        raise EslError("CONFIG_INVALID", f"jig_bc.METHODS: 공유 기저 분해(factor own ∧ tie_stiff hard) 행이 1개가 아님 {rows}")
    return rows[0]


def factor_groups(methods) -> dict[str, list[str]]:
    """분해 묶음(METHODS.factor 열): {분해 주인 방식: [그 분해를 쓰는 방식…]} — fixed·prescribed 는 fixed 분해 공유(값만 다름).
    공유 대상이 목록에 없어도 분해는 함(prescribed 만 계산해도 fixed 구속 집합으로 분해)."""
    out: dict[str, list[str]] = {}
    for m in methods:
        owner = m if METHODS[m]["factor"] == "own" else METHODS[m]["factor"]
        out.setdefault(owner, []).append(m)
    return out


# ====================================================================== (1) tie 법선(국부 면외) — §3.1
def _node_elem(conn, et, n_nodes):
    """노드 → 이웃 요소 CSR(indptr, elem) — 쿼드 4·트라이 3 코너."""
    conn = np.asarray(conn, dtype=np.int64)
    q = np.asarray(et).astype(np.int64) == 4
    E = conn.shape[0]
    rows = np.concatenate([conn[:, 0], conn[:, 1], conn[:, 2], conn[q, 3]])
    eidx = np.concatenate([np.arange(E)] * 3 + [np.flatnonzero(q)])
    order = np.lexsort((eidx, rows))
    rows, eidx = rows[order], eidx[order]
    keep = np.r_[True, (rows[1:] != rows[:-1]) | (eidx[1:] != eidx[:-1])]        # 퇴화(같은 노드 두 번) 중복 제거
    rows, eidx = rows[keep], eidx[keep]
    indptr = np.zeros(int(n_nodes) + 1, dtype=np.int64)
    np.add.at(indptr, rows + 1, 1)
    return np.cumsum(indptr), eidx


def _orient(v):
    j = int(np.argmax(np.abs(v)))
    return -v if v[j] < 0 else v


def node_frames(mesh, nodes, *, kink_deg: float, valid_elem=None) -> dict:
    """구속 법선(§3.1, D-0.24.4-JIG-4): S_n = Σ_{e∋n, valid} A_e m̂_e m̂_eᵀ(기준 형상, ``mass.elem_area_normal`` 식) 고유분해
    λ₁ ≥ λ₂ ≥ λ₃, 구속 방향 = λ₁ 고유벡터 + λ_k ≥ τλ₁ 인 고유벡터(τ = tan²(kink_deg/2) — 평판 1·꺾임 2·모서리 3),
    부호 = 최대 절댓값 성분 양수.
    valid = 두께 > 0 ∧ E > 0(null shell 제외 — ``valid_elem`` 로 덮어씀). valid 이웃 없으면 이웃 전 요소, 그래도 없으면(고립) 3축.
    반환 {node (m,), dir (m,3), dirs [(n, d̂)], rank (len(nodes),), nodes (정렬·중복 제거), rank_counts {1,2,3},
    n_isolated, n_null_excluded(null 이웃을 뺀 노드 수), kink_deg}."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    N, E = X.shape[0], conn.shape[0]
    nd = np.unique(np.asarray(nodes, dtype=np.int64).reshape(-1))
    if nd.size and (nd.min() < 0 or nd.max() >= N):
        raise EslError("INPUT_INVALID", "node_frames 노드 인덱스 범위 밖")
    if valid_elem is None:
        th = np.broadcast_to(np.asarray(mesh.get("thickness", 1.0), dtype=np.float64), (E,))
        Em = np.broadcast_to(np.asarray(mesh.get("E", 1.0), dtype=np.float64), (E,))
        valid = (th > 0) & (Em > 0)
    else:
        valid = np.asarray(valid_elem, bool).reshape(E)
    A, m = elem_area_normal(X, conn, et)
    ptr, eidx = _node_elem(conn, et, N)
    tau = float(np.tan(np.radians(float(kink_deg)) / 2.0) ** 2)
    S = np.zeros((nd.size, 3, 3))
    n_null = 0
    iso = np.zeros(nd.size, bool)
    for i, n in enumerate(nd):
        es = eidx[ptr[n]:ptr[n + 1]]
        ev = es[valid[es]]
        if ev.size < es.size:
            n_null += 1
        use = ev if ev.size else es
        if use.size == 0:
            iso[i] = True
            continue
        S[i] = np.einsum("e,ei,ej->ij", A[use], m[use], m[use])
    lam, V = np.linalg.eigh(S) if nd.size else (np.zeros((0, 3)), np.zeros((0, 3, 3)))
    iso |= ~(lam[:, 2] > 0) if nd.size else iso
    rows_n, rows_d = [], []
    rank = np.zeros(nd.size, dtype=np.int64)
    for i, n in enumerate(nd):
        if iso[i]:
            dd = [np.eye(3)[k] for k in range(3)]
        else:
            dd = [_orient(V[i, :, k].copy()) for k in (2, 1, 0) if k == 2 or lam[i, k] >= tau * lam[i, 2]]
        rank[i] = len(dd)
        rows_n += [int(n)] * len(dd)
        rows_d += dd
    node = np.asarray(rows_n, dtype=np.int64)
    dirv = np.asarray(rows_d, dtype=np.float64).reshape(-1, 3)
    return {"node": node, "dir": dirv, "dirs": [(int(a), b) for a, b in zip(node, dirv)], "rank": rank, "nodes": nd,
            "rank_counts": {k: int(np.sum(rank == k)) for k in (1, 2, 3)}, "n_isolated": int(iso.sum()),
            "n_null_excluded": int(n_null), "kink_deg": float(kink_deg)}


def tie_rows(mesh, jig_idx, tie_dofs: str, *, kink_deg: float, valid_elem=None) -> dict:
    """tie 구속 행(TIE_DOFS.dirs 열): normal_subspace = ``node_frames``, xyz = 노드마다 전역 3축. 반환 {node, dir, normals(진단|None)}."""
    row = TIE_DOFS[tie_dofs]
    J = np.unique(np.asarray(jig_idx, dtype=np.int64).reshape(-1))
    if row["dirs"] == "normal_subspace":
        fr = node_frames(mesh, J, kink_deg=kink_deg, valid_elem=valid_elem)
        diag = {k: fr[k] for k in ("rank_counts", "n_isolated", "n_null_excluded", "kink_deg")}
        return {"node": fr["node"], "dir": fr["dir"], "normals": diag}
    return {"node": np.repeat(J, 3), "dir": np.tile(np.eye(3), (J.size, 1)), "normals": None}


# ====================================================================== (2) 3-2-1 면내 부분 — §3.3
def _sup321(sup321):
    by = {}
    for p, d in sup321:
        by.setdefault(len(str(d)), []).append(int(p))
    if sorted(by) != [1, 2, 3] or any(len(v) != 1 for v in by.values()):
        raise EslError("INPUT_INVALID", f"3-2-1 지지 형식이 아님: {list(sup321)!r}")
    return by[3][0], by[2][0], by[1][0]


def aux321_inplane(X0, sup321, tie_dirs, *, dup_deg: float) -> dict:
    """3-2-1 면내 행(§3.3, D-0.24.4-JIG-5): 판 평면 = 파트 PCA(``supports.pca_corners`` 축 e₁·e₂, 법선 e₃),
    n₁(123) → e₁, e₂ · n₂(2성분) → ê = e₃ × (x₂ − x₁)/‖·‖(면내 회전 막음). n₃·모든 면외 성분 제외.
    중복 제거: 그 노드의 tie 구속 방향(+ 앞서 받은 면내 행)에 대해 Gram–Schmidt, 남은 노름 < sin(dup_deg) = 행 뺌(n_dup).
    반환 {node, dir, rows [(n, d̂)], nodes [n₁, n₂, n₃], n_dup, plane{e1, e2, n}}."""
    X = np.asarray(X0, dtype=np.float64)
    n1, n2, n3 = _sup321(sup321)
    pl = supports.pca_corners(X)["plane"]
    e1, e2, e3 = (np.asarray(pl[k], dtype=np.float64) for k in ("e1", "e2", "n"))
    s = X[n2] - X[n1]
    eh = np.cross(e3, s)
    if np.linalg.norm(eh) <= 1e-12 * max(np.linalg.norm(s), 1e-300):
        raise EslError("JIG_SUPPORT_DEGENERATE", "3-2-1 면내: n₁–n₂ 가 판 법선과 평행")
    cand = [(n1, e1), (n1, e2), (n2, eh / np.linalg.norm(eh))]
    tn = np.asarray(tie_dirs["node"], dtype=np.int64).reshape(-1)
    td = np.asarray(tie_dirs["dir"], dtype=np.float64).reshape(-1, 3)
    thr = float(np.sin(np.radians(float(dup_deg))))
    basis: dict[int, list] = {}
    out_n, out_d, n_dup = [], [], 0
    for n, d in cand:
        if n not in basis:                            # 그 노드 tie 방향 정규직교 기저
            qs: list[np.ndarray] = []
            for v in td[tn == n]:
                w = v - sum((q @ v) * q for q in qs) if qs else v.copy()
                nr = float(np.linalg.norm(w))
                if nr > 1e-12:
                    qs.append(w / nr)
            basis[n] = qs
        w = d - sum((q @ d) * q for q in basis[n]) if basis[n] else d.copy()
        nr = float(np.linalg.norm(w))
        if nr < thr:
            n_dup += 1
            continue
        u = w / nr
        basis[n].append(u)
        out_n.append(int(n))
        out_d.append(u)
    node = np.asarray(out_n, dtype=np.int64)
    dirv = np.asarray(out_d, dtype=np.float64).reshape(-1, 3)
    return {"node": node, "dir": dirv, "rows": [(int(a), b) for a, b in zip(node, dirv)],
            "nodes": [int(n1), int(n2), int(n3)], "n_dup": int(n_dup),
            "plane": {"e1": e1.tolist(), "e2": e2.tolist(), "n": e3.tolist()}}


def aux_rows(X0, sup321, tie: dict, tie_dofs: str, *, dup_deg: float) -> dict:
    """3-2-1 면내 행(TIE_DOFS.aux321 열): inplane = ``aux321_inplane``, none = 빈 행."""
    if TIE_DOFS[tie_dofs]["aux321"] == "inplane":
        return aux321_inplane(X0, sup321, tie, dup_deg=dup_deg)
    return {"node": np.zeros(0, np.int64), "dir": np.zeros((0, 3)), "rows": [], "nodes": [], "n_dup": 0, "plane": None}


# ====================================================================== (3) 목표 프레임 · BC — §3.2
def target(frame: str, X0, u_part, jig_idx, fit_mask) -> dict:
    """METHODS.frame 열: part = u_part 그대로(파트 Kabsch — Case u_rel, ④ 목표와 같은 프레임), jig_kabsch = 지그 노드 Kabsch
    유한 회전 제거(``jig.target_disp`` — D-JIG-16). 반환 {u_tgt (N,3), tie_rel, rot_deg}."""
    u = np.asarray(u_part, dtype=np.float64)[:, :3]
    J = np.asarray(jig_idx, dtype=np.int64)
    if frame == "jig_kabsch":
        t = jig.target_disp(X0, u, J, fit_mask)
        return {"u_tgt": t["u_tgt"], "tie_rel": float(t["tie_rel"]), "rot_deg": float(t["rot_deg"])}
    if frame != "part":
        raise EslError("CONFIG_INVALID", f"frame {frame!r}")
    fm = np.asarray(fit_mask, bool)
    nf = np.linalg.norm(u[fm], axis=1)
    umax = float(nf.max()) if nf.size else 0.0
    tj = float(np.linalg.norm(u[J], axis=1).max()) if J.size else 0.0
    return {"u_tgt": u.copy(), "tie_rel": tj / umax if umax > 0 else 0.0, "rot_deg": 0.0}


def _dot_rows(nodes, dirs, u):
    nodes = np.asarray(nodes, dtype=np.int64)
    return np.einsum("ri,ri->r", np.asarray(dirs, dtype=np.float64).reshape(-1, 3), np.asarray(u)[nodes, :3]) \
        if nodes.size else np.zeros(0)


def build_bc(method_row: dict, tie: dict, aux: dict, u_tgt, *, k=None) -> dict:
    """방식 행(METHODS 열 tie_value·tie_stiff) → BC{bc_node, bc_dir, bc_val, bc_kind(1 tie·2 aux), sp_node, sp_dir, sp_k, sp_g}.
    tie 값 = 0(zero) | d̂·u_tgt(target), tie_stiff hard = 구속 행 · spring = 스프링 행(k 필요, 바닥 g = tie 값).
    3-2-1 면내 행 = 항상 강제(hard), 값 = d̂·u_tgt(그 방식 목표 — 프레임 고정점, Q-JIGC-3)."""
    tn = np.asarray(tie["node"], dtype=np.int64).reshape(-1)
    td = np.asarray(tie["dir"], dtype=np.float64).reshape(-1, 3)
    an = np.asarray(aux["node"], dtype=np.int64).reshape(-1)
    ad = np.asarray(aux["dir"], dtype=np.float64).reshape(-1, 3)
    tv = np.zeros(tn.size) if method_row["tie_value"] == "zero" else _dot_rows(tn, td, u_tgt)
    av = _dot_rows(an, ad, u_tgt)
    if method_row["tie_stiff"] == "hard":
        return {"bc_node": np.r_[tn, an].astype(np.int64), "bc_dir": np.concatenate([td, ad], axis=0),
                "bc_val": np.r_[tv, av].astype(np.float64),
                "bc_kind": np.r_[np.full(tn.size, KIND_TIE), np.full(an.size, KIND_AUX)].astype(np.int8),
                "sp_node": np.zeros(0, np.int64), "sp_dir": np.zeros((0, 3)), "sp_k": np.zeros(0), "sp_g": np.zeros(0)}
    kk = None if k is None else np.asarray(k, dtype=np.float64).reshape(-1)
    if kk is None or kk.size != tn.size or np.any(~np.isfinite(kk)) or np.any(kk <= 0):
        raise EslError("INPUT_INVALID", "스프링 경계: tie 행마다 k > 0 필요")
    return {"bc_node": an.copy(), "bc_dir": ad.copy(), "bc_val": av.astype(np.float64),
            "bc_kind": np.full(an.size, KIND_AUX, dtype=np.int8),
            "sp_node": tn.copy(), "sp_dir": td.copy(), "sp_k": kk.copy(), "sp_g": tv.astype(np.float64)}


def spring_k(K0, tie: dict, *, mode: str, alpha: float | None = None, value=None) -> np.ndarray:
    """스프링 강성(§3.5, D-0.24.4-JIG-7): auto = α·d̂ᵀK₀[n]d̂(K₀[n] = 기준 설계 노드 병진 3×3 대각 블록 — 파트 자기 국부 강성),
    value = 모든 행 같은 값(N/mm). K0 = ShellModel(기준 설계) 또는 6N×6N 희소 행렬. α < 1e-3·value ≤ 0 = CONFIG_INVALID.
    α None = ``jig.JIG_DEFAULTS["spring_alpha"]``(기본값 한 곳 — D-0.24.4-JIG-19). 기준 설계에서 한 번 계산해 저장하고 안은
    재계산하지 않는다(§3.7)."""
    tn = np.asarray(tie["node"], dtype=np.int64).reshape(-1)
    td = np.asarray(tie["dir"], dtype=np.float64).reshape(-1, 3)
    if mode == "value":
        if value is None or isinstance(value, bool) or not np.isfinite(float(value)) or float(value) <= 0:
            raise EslError("CONFIG_INVALID", f"spring_k_value = {value!r}(> 0 N/mm 필요)")
        return np.full(tn.size, float(value))
    if mode != "auto":
        raise EslError("CONFIG_INVALID", f"spring_k_mode {mode!r} ∉ {SPRING_K_MODES}")
    a = float(jig.JIG_DEFAULTS["spring_alpha"] if alpha is None else alpha)
    if not np.isfinite(a) or a < SPRING_ALPHA_MIN:
        raise EslError("CONFIG_INVALID", f"spring_alpha = {alpha!r} < {SPRING_ALPHA_MIN}")
    if hasattr(K0, "_diag_blocks"):
        B = K0._diag_blocks(0, 3)[tn]
    else:
        K = K0.tocsr()
        r = (6 * tn)[:, None, None] + np.arange(3)[None, :, None]
        c = (6 * tn)[:, None, None] + np.arange(3)[None, None, :]
        rr, cc = np.broadcast_arrays(r, c)
        B = np.asarray(K[rr.ravel(), cc.ravel()]).reshape(tn.size, 3, 3)
    k = a * np.einsum("ri,rij,rj->r", td, B, td)
    if np.any(~np.isfinite(k)) or np.any(k <= 0):
        raise EslError("INPUT_INVALID", "스프링 강성 auto: 노드 자기 강성 d̂ᵀK₀[n]d̂ ≤ 0")
    return k


# ====================================================================== (4) 강체 모드 확인 — §3.3
def components(mesh) -> dict:
    """요소 그래프 연결 성분 {n_comp, labels (N,), used (N,) 요소 있는 노드}."""
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    N = np.asarray(mesh["x0"]).shape[0]
    nc, lab = mesh_components(conn, et, N)
    used = np.zeros(N, bool)
    q = et == 4
    used[conn[q].ravel()] = True
    used[conn[~q, :3].ravel()] = True
    return {"n_comp": int(nc), "labels": np.asarray(lab, dtype=np.int64), "used": used}


def rigid_free(X0, mesh_components_, BC: dict) -> dict:
    """남은 강체 모드 수(§3.3): 요소 있는 연결 성분마다 6 − rank(A), A 행 = [d̂ᵀ, ((x − c)/L × d̂)ᵀ](구속 행 + 스프링 행).
    0 이어야 함 — > 0 = JIG_SUPPORT_DEGENERATE{rigid_free, comp}(호출자). 반환 {rigid_free, per_comp[{comp, n_nodes, n_rows,
    rank, free}]}."""
    mc = mesh_components_
    nodes = np.r_[np.asarray(BC["bc_node"], dtype=np.int64), np.asarray(BC["sp_node"], dtype=np.int64)]
    dirs = np.concatenate([np.asarray(BC["bc_dir"], dtype=np.float64).reshape(-1, 3),
                           np.asarray(BC["sp_dir"], dtype=np.float64).reshape(-1, 3)], axis=0)
    per = [c for c in rigid_rank(X0, mc["labels"], mc["n_comp"], nodes, dirs)
           if mc["used"][mc["labels"] == c["comp"]].any()]
    return {"rigid_free": int(sum(c["free"] for c in per)), "per_comp": per}


# ====================================================================== (5) 해 — 분해 선택(자료) · 공통 해 인터페이스
def _axis_rows(BC):
    d = np.asarray(BC["bc_dir"], dtype=np.float64).reshape(-1, 3)
    ax = np.argmax(np.abs(d), axis=1) if d.size else np.zeros(0, np.int64)
    sg = np.sign(d[np.arange(d.shape[0]), ax]) if d.size else np.zeros(0)
    exact = d.shape[0] == 0 or bool(np.all(np.abs(d).sum(axis=1) == 1.0) and np.all(np.abs(sg) == 1.0))
    return exact, ax.astype(np.int64), sg


class SpcSolve:
    """축 방향 구속만·스프링 없음 → ``ShellModel.factorize``(옛 spc 경로, FactorizedSolve)를 ``BcSolve`` 와 같은 인터페이스로:
    ``solve(F, values, ground) -> (u, R, rc, fs)``·``K_t``·``free_t``·``fixed_t``·``to_local``/``to_global``(항등)·``solve_t``."""

    def __init__(self, h, BC: dict):
        self.h = h
        self.model = h.model
        _, ax, sg = _axis_rows(BC)
        bn = np.asarray(BC["bc_node"], dtype=np.int64)
        pos = {(int(p), int(d)): i for i, (p, d) in enumerate(h.cons)}
        try:
            self._ci = np.asarray([pos[(int(n), int(a))] for n, a in zip(bn, ax)], dtype=np.int64)
        except KeyError as e:
            raise EslError("INPUT_INVALID", f"BC 행이 분해 구속 집합에 없음: {e}") from None
        if np.unique(self._ci).size != self._ci.size or self._ci.size != len(h.cons):
            raise EslError("INPUT_INVALID", "BC 행 ↔ 분해 구속 dof 가 1:1 이 아님")
        self._sg, self._bn, self._ax = sg, bn, ax
        self.K_t = h.K
        self.free_t = np.asarray(h.free, dtype=np.int64)
        self.free = self.free_t
        self.fixed_t = np.asarray([6 * p + d for p, d in h.cons], dtype=np.int64)
        self.bc_node, self.bc_dir = bn, np.asarray(BC["bc_dir"], dtype=np.float64).reshape(-1, 3)
        self.sp_node, self.sp_dir, self.sp_k = np.zeros(0, np.int64), np.zeros((0, 3)), np.zeros(0)

    @property
    def n_solves(self) -> int:
        return int(self.h.n_solves)

    def to_local(self, x):
        return np.array(x, dtype=np.float64, copy=True)

    def to_global(self, x):
        return np.array(x, dtype=np.float64, copy=True)

    def solve(self, F, values=None, ground=None):
        if ground is not None and np.asarray(ground).size:
            raise EslError("INPUT_INVALID", "spc 경로에는 스프링 없음")
        if values is None:
            u, R = self.h.solve(F)
        else:
            v = np.asarray(values, dtype=np.float64).reshape(-1)
            if v.size != self._ci.size:
                raise EslError("INPUT_INVALID", f"values 길이 {v.size} ≠ 구속 행 {self._ci.size}")
            vc = np.zeros(self._ci.size)
            vc[self._ci] = self._sg * v                            # d̂ = ±e_k: d̂ᵀu = v ⇔ u_k = ±v
            u, R = self.h.solve(F, values=vc)
        rc = self._sg * R[self._bn, self._ax]
        return u, R, rc, np.zeros(0)

    def solve_t(self, b):
        N = self.model.n_nodes
        f = np.zeros(6 * N)
        f[self.free_t] = np.asarray(b, dtype=np.float64).reshape(-1)
        u, _ = self.h.solve(f.reshape(N, 6)[:, :3].copy())
        return u.reshape(-1)[self.free_t]


def factorize(sm, BC: dict):
    """BC 구속 집합(값 제외)·스프링 → 분해 1회. 축 방향 구속만·스프링 없음 = ``SpcSolve``(옛 ``factorize`` 경로), 그 밖
    ``sm.factorize_bc``. 고르는 기준은 자료(방향 행)뿐 — 방식 이름 분기 없음. SOLVER_SINGULAR → JIG_SUPPORT_DEGENERATE.
    분해 순서 = 설정 solver.jig_factor_order(``sm.jig_factor_order`` — node_mmd 면 노드 블록 순서, default 면 예전 MMD). 이 함수
    (새 지그 경로)에만 적용 — 옛 3-2-1·spc 호출(``sm.factorize(spc)``)은 order 를 안 줘 바이트 불변."""
    order = getattr(sm, "jig_factor_order", None)
    order = order if order == "node_mmd" else None
    exact, ax, _ = _axis_rows(BC)
    has_sp = np.asarray(BC["sp_node"]).size > 0
    bn = np.asarray(BC["bc_node"], dtype=np.int64)
    try:
        if exact and not has_sp and np.unique(bn * 3 + ax).size == bn.size:
            spc: dict[int, str] = {}
            for n, a in zip(bn.tolist(), ax.tolist()):
                spc[n] = spc.get(n, "") + str(a + 1)
            h = sm.factorize([(n, "".join(sorted(d))) for n, d in sorted(spc.items())], order=order)
            return SpcSolve(h, BC)
        return sm.factorize_bc((bn, np.asarray(BC["bc_dir"], dtype=np.float64).reshape(-1, 3)),
                               springs=(np.asarray(BC["sp_node"], dtype=np.int64),
                                        np.asarray(BC["sp_dir"], dtype=np.float64).reshape(-1, 3),
                                        np.asarray(BC["sp_k"], dtype=np.float64)) if has_sp else None,
                               order=order)
    except EslError as e:
        if e.code == "SOLVER_SINGULAR":
            raise EslError("JIG_SUPPORT_DEGENERATE", e.message) from e
        raise


def needs_ground(BC: dict) -> bool:
    """u_g(F = 0·값/바닥만) 해가 필요한가 — 값·바닥이 모두 0 이면 u_g = 0(계산 생략·옛 경로)."""
    return bool(np.any(np.asarray(BC["bc_val"]) != 0) or np.any(np.asarray(BC["sp_g"]) != 0))


def solve(h, F, BC: dict, *, homogeneous: bool = False):
    """BC 의 값·바닥으로 풀기(homogeneous = 값·바닥 0 — 하중 기저 응답 U_k). → (u (N,6), R (N,3), rc (m,), fs (ms,))."""
    if homogeneous:
        return h.solve(F)
    return h.solve(F, values=np.asarray(BC["bc_val"], dtype=np.float64),
                   ground=np.asarray(BC["sp_g"], dtype=np.float64) if np.asarray(BC["sp_node"]).size else None)


def aux_index(BC: dict) -> np.ndarray:
    """BC 구속 행 중 3-2-1 면내 행(bc_kind = KIND_AUX)의 위치(rc 순서)."""
    return np.flatnonzero(np.asarray(BC["bc_kind"]).astype(np.int64) == KIND_AUX)


def basis_response(h, basis: dict, fit_mask, BC: dict) -> dict:
    """하중 기저 응답(동차 — 값·바닥 0): ``jig.basis_response`` 와 같은 해(같은 하중·같은 solve — U 비트 동일) + 열마다 3-2-1 면내
    행 반력 rc_aux (nb, n_aux)(맞춤의 면내 반력 0 등식 제약용 — D-0.24.4-JIG-20). 반환 {U (nb, M, 3), null_cols, rc_aux}."""
    nb = int(basis["nb"])
    N = int(h.model.n_nodes)
    fm = np.asarray(fit_mask, bool)
    ia = aux_index(BC)
    U = np.zeros((nb, int(fm.sum()), 3))
    rca = np.zeros((nb, ia.size))
    null = []
    for k in range(nb):
        u, _R, rc, _fs = solve(h, jig.forces(basis, jig._unit(nb, k), N), BC, homogeneous=True)
        U[k] = u[fm, :3]
        rca[k] = np.asarray(rc, dtype=np.float64)[ia]
        if not np.any(U[k]):
            null.append(k)
    return {"U": U, "null_cols": null, "rc_aux": rca}


def aux_eq(BC: dict, rc_aux_basis, rc_aux_ground=None):
    """3-2-1 면내 반력 0 등식(D-0.24.4-JIG-20): r_aux(a) = r_aux,g + Σ_k a_k r_aux,k = 0 → (C (n_aux, nb), c (n_aux,)) =
    (rc_aux_basisᵀ, −r_aux,g). 3-2-1 면내 행이 없으면(translation) None — 맞춤은 옛 경로 그대로. 평판·정정(면내 3자유도)이면
    면내 합력 2·면내 모멘트 1 = 0 과 같다(면외 tie 반력은 면내 강체 일을 하지 않음)."""
    rb = np.asarray(rc_aux_basis, dtype=np.float64)
    if rb.ndim != 2 or rb.shape[1] == 0 or aux_index(BC).size == 0:
        return None
    g = np.zeros(rb.shape[1]) if rc_aux_ground is None else np.asarray(rc_aux_ground, dtype=np.float64).reshape(-1)
    return rb.T.copy(), -g


def modes(h, weights, n_modes: int, rho_t: float, *, sigma: float = 0.0, tol: float = 0.0, maxiter=None) -> dict:
    """지그 구속 저차 모드(D-JIG-15 — σ = 0 이면 지그 분해 재사용, 아니면 (K − σM)_ff 분해) → {phi (m,N,6) 전역, lam, hz,
    n_conv, ok, err, g (m,N,3) 관성 하중}. 변환 공간 해법(BcSolve)은 K̃·fixed_t 로 풀고 φ = to_global(φ̃)(질량 = 병진 등방
    m·I₃ — 회전 불변). 실패 = JIG_MODES_FAILED(``jig.jig_modes`` 규칙 그대로)."""
    m = jig.lumped_mass(weights, rho_t)
    M6 = jig.mass_diag6(m)
    N = int(h.model.n_nodes)
    sg = float(sigma)
    md = jig.jig_modes(h.K_t, M6, h.fixed_t, int(n_modes), sg, opinv=jig.opinv_from(h, N) if sg == 0.0 else None,
                       tol=tol, maxiter=maxiter)
    md["phi"] = h.to_global(md["phi"])
    md["g"] = jig.mode_loads(md["phi"], m)
    return md


# ====================================================================== (6) 지표 — §3.8
def mixed_compliance(F, u, BC: dict, rc, fs) -> dict:
    """C_mix = Fᵀu − Σ v_c r_c − Σ g_s f_s(= −2Π*), E = Fᵀu + Σ v_c r_c + Σ f_s d̂_sᵀu_{n_s} + Σ f_s²/k_s(= 2U_tot),
    W_F = Fᵀu(하중 일), W_g = Σ v r + Σ g f_s(지지 일), R_sum = Σ|r_c| + Σ|f_s|."""
    F = np.asarray(F, dtype=np.float64)
    u3 = np.asarray(u, dtype=np.float64)[:, :3]
    v = np.asarray(BC["bc_val"], dtype=np.float64)
    r = np.asarray(rc, dtype=np.float64).reshape(-1)
    g = np.asarray(BC["sp_g"], dtype=np.float64)
    f = np.asarray(fs, dtype=np.float64).reshape(-1)
    k = np.asarray(BC["sp_k"], dtype=np.float64)
    WF = float(np.sum(F * u3))
    Wv = float(v @ r) if v.size else 0.0
    Wg = float(g @ f) if g.size else 0.0
    ws = _dot_rows(BC["sp_node"], BC["sp_dir"], u3)
    E = WF + Wv + (float(f @ ws) if f.size else 0.0) + (float(np.sum(f * f / k)) if f.size else 0.0)
    return {"C_mix": WF - Wv - Wg, "E": E, "W_F": WF, "W_g": Wv + Wg,
            "R_sum": float(np.abs(r).sum() + np.abs(f).sum())}


def score(C_mix_d: float, C_mix_0: float, E_0: float) -> float:
    """s_d = 1 + (C_mix,d − C_mix,0)/E_0 — 작을수록 강함(값·바닥 없으면 C_d/C_0). E_0 ≤ 0 = INPUT_INVALID."""
    if not np.isfinite(E_0) or E_0 <= 0:
        raise EslError("INPUT_INVALID", f"기준 에너지 E_0 = {E_0!r} ≤ 0")
    return 1.0 + (float(C_mix_d) - float(C_mix_0)) / float(E_0)


def per_esl_C(C_mix_d: float, C_mix_0: float, E_0: float) -> float:
    """per_esl 저장값 C_<pe> = E_0 + (C_mix,d − C_mix,0), C_ref = E_0 → 기존 비 C/C_ref = ``score``(최악 엔트리 구조 그대로)."""
    return float(E_0) + (float(C_mix_d) - float(C_mix_0))


def aux_reaction_rel(F, BC: dict, rc) -> float:
    """3-2-1 면내 반력비 Σ_n‖r_aux,n‖ / Σ‖F_n‖(정보 — 평형인 면내 맞춤 하중이면 ≈ 0). F = 0 이면 0."""
    kind = np.asarray(BC["bc_kind"]).astype(np.int64)
    sel = kind == KIND_AUX
    if not sel.any():
        return 0.0
    nodes = np.asarray(BC["bc_node"], dtype=np.int64)[sel]
    vec = np.asarray(rc, dtype=np.float64)[sel][:, None] * np.asarray(BC["bc_dir"], dtype=np.float64)[sel]
    un, inv = np.unique(nodes, return_inverse=True)
    acc = np.zeros((un.size, 3))
    np.add.at(acc, inv, vec)
    sF = float(np.linalg.norm(np.asarray(F, dtype=np.float64), axis=1).sum())
    return float(np.linalg.norm(acc, axis=1).sum()) / sF if sF > 0 else 0.0


# ====================================================================== (7) 한 방식 맞춤 — §3.4
def run_method(h, basis: dict, U, u_tgt, BC: dict, fit_mask, weights: dict, *, jig_idx, ridge: float, w_inplane: float,
               reg_force: float, reg_modes: float, active_tol: float, nomodes: bool = True, rc_basis=None) -> dict:
    """응답 분해 u = u_g + Σ a_k U_k(u_g = F 0·값/바닥만, U = ``jig.basis_response(h, …)`` 동차 해), 맞춤 a* = ``jig.fit_loads``
    (U, (u_tgt − u_g)[M], …)(가중·정규화·BVLS 그대로), F = Σ a*_k f_k, 응답 u = BC 값·바닥으로 1회 해(= u_g + U a* — 선형).
    품질 = ``jig.fit_report``(u_fit vs u_tgt, 맞춤 노드 M), 지표 = ``mixed_compliance``.
    rc_basis = ``basis_response`` 의 rc_aux(같은 분해) — 주면 3-2-1 면내 반력 0 등식 제약(``aux_eq`` — D-0.24.4-JIG-20, 면내 행이
    없으면 제약 없음 = 옛 경로). 반환 {a, F, u (N,6), u_fit (N,3), u_g (N,3), R, rc, fs, fit, report, energy, aux_reaction_rel,
    aux_eq(제약 정보 | None)}."""
    fm = np.asarray(fit_mask, bool)
    N = fm.size
    ut = np.asarray(u_tgt, dtype=np.float64)[:, :3]
    rcg = np.zeros(aux_index(BC).size)
    if needs_ground(BC):
        sg_ = solve(h, np.zeros((N, 3)), BC)
        ug = np.asarray(sg_[0], dtype=np.float64)[:, :3]
        rcg = np.asarray(sg_[2], dtype=np.float64)[aux_index(BC)]
    else:
        ug = np.zeros((N, 3))
    eq = None if rc_basis is None else aux_eq(BC, rc_basis, rcg)
    area = np.asarray(weights["area"], dtype=np.float64)
    w_fit = area[fm] / max(float(area[fm].mean()), 1e-300)
    n_fit = np.asarray(weights["normal"], dtype=np.float64)[fm]
    rhs = (ut - ug)[fm]
    kw = {"ridge": float(ridge), "w_inplane": float(w_inplane), "reg_force": float(reg_force),
          "reg_modes": float(reg_modes)}
    if eq is not None:
        kw["eq"] = eq
    fr = jig.fit_loads(U, rhs, w_fit, n_fit, basis, **kw)
    a = fr["a"]
    F = jig.forces(basis, a, N)
    u, R, rc, fs = solve(h, F, BC)
    unm = None
    if nomodes and basis.get("mode_f") is not None:
        fnm = jig.fit_loads(U, rhs, w_fit, n_fit, basis, drop_kinds=(jig.COL_MODE,), **kw)
        unm = ug[fm] + np.einsum("k,kmi->mi", fnm["a"], np.asarray(U))
    rep = jig.fit_report(u[:, :3], ut, fm, weights, basis, a, jig_idx=jig_idx, active_tol=float(active_tol),
                         u_fit_nomodes=unm)
    return {"a": a, "F": F, "u": u, "u_fit": u[:, :3].copy(), "u_g": ug, "R": R, "rc": rc, "fs": fs, "fit": fr,
            "report": rep, "energy": mixed_compliance(F, u, BC, rc, fs), "aux_reaction_rel": aux_reaction_rel(F, BC, rc),
            "aux_eq": fr.get("eq")}


def respond(h, F, BC: dict) -> dict:
    """설계안 응답(§3.7 — 같은 BC 값·바닥·k·F): {u, R, rc, fs, energy}. 안마다 K_d 로 ``factorize(sm_d, BC)`` 한 h."""
    u, R, rc, fs = solve(h, F, BC)
    return {"u": u, "R": R, "rc": rc, "fs": fs, "energy": mixed_compliance(F, u, BC, rc, fs)}


def flags(method: str, rep: dict, *, aux_rel: float, th: dict) -> dict:
    """방식 판정(열 값만): warnings = JIG_FIT_POOR(mac < mac_min ∨ umax_err > umax_err_max)·JIG_TIE_RELATIVE(METHODS.tie_rel_warn
    ∧ tie_rel > tie_rel_warn)·JIG_LOAD_CANCEL(work_eff < work_eff_min), info = JIG_AUX_REACTION(aux_rel > aux_reaction_warn),
    limits = METHODS.limits. 반환 {warnings [코드], info [코드], limits [코드]}."""
    row = METHODS[method]
    w = []
    if rep["mac"] < float(th["mac_min"]) or rep["umax_err"] > float(th["umax_err_max"]):
        w.append("JIG_FIT_POOR")
    if row["tie_rel_warn"] and rep["tie_rel"] > float(th["tie_rel_warn"]):
        w.append("JIG_TIE_RELATIVE")
    if rep["work_eff"] < float(th["work_eff_min"]):
        w.append("JIG_LOAD_CANCEL")
    info = ["JIG_AUX_REACTION"] if aux_rel > float(th["aux_reaction_warn"]) else []
    return {"warnings": w, "info": info, "limits": list(row["limits"])}


# ====================================================================== (7b) 3D 지지 표식(표시만 — 계산 불변, esl_viewer_hv.md §8.1)
def _mark_nodes(bc_node, bc_kind, sp_node, x0, smax: int) -> tuple[list[int], list[int]]:
    """표식 노드(v0.24.6 규칙 — 일반형·옛 2튜플 공용): tie = KIND_TIE 구속 행 노드 ∪ 스프링 행 노드 → ``jig.support_sample`` 최원점
    샘플 ≤ smax 개, 면내 = KIND_AUX 노드 전부(샘플된 tie 와 겹치면 tie 만). 범위 밖 노드 무시. 반환 (tie 샘플 순서, 면내 오름차순)."""
    n = int(np.asarray(x0).shape[0])
    bn = np.asarray(bc_node, dtype=np.int64).reshape(-1)
    bk = np.asarray(bc_kind).astype(np.int64).reshape(-1)
    sp = np.asarray(sp_node, dtype=np.int64).reshape(-1)
    if bk.size != bn.size:
        raise EslError("INPUT_INVALID", f"support_marks: bc_kind 길이 {bk.size} ≠ bc_node {bn.size}")
    ok = (bn >= 0) & (bn < n)
    tie = jig.support_sample(x0, np.unique(np.r_[bn[ok & (bk == KIND_TIE)], sp[(sp >= 0) & (sp < n)]]), int(smax))
    shown = set(int(i) for i in tie.tolist())
    aux = [int(i) for i in np.unique(bn[ok & (bk == KIND_AUX)]).tolist() if int(i) not in shown]
    return [int(i) for i in tie.tolist()], aux


def support_marks(bc_node, bc_kind, sp_node, x0, smax: int) -> list[tuple[int, str]]:
    """지그 3D 지지 표식 옛 2튜플(D-0.24.6-VW-13 — v0.24.9 일반형 ``support_marks_full`` 의 어댑터, 바이트 불변): tie 샘플 = MARK_TIE,
    3-2-1 면내 = MARK_AUX. 반환 [(노드 인덱스, dof)] — tie 샘플 순서 뒤 면내 오름차순. 순수·결정적."""
    tie, aux = _mark_nodes(bc_node, bc_kind, sp_node, x0, smax)
    return [(i, MARK_TIE) for i in tie] + [(i, MARK_AUX) for i in aux]


# v0.24.9 BM(계약 esl_bead_pos_u.md §10.2): 표식 종류. 지그 아닌 출처(전 노드 ESL 등)의 3-2-1 = support321(기존 dof 그대로)
MARK_KINDS = ("tie_fixed", "tie_disp", "tie_spring", "aux_inplane", "support321")


def mark_kind_of(method_row: dict | None, hard_vals=None) -> str:
    """tie 구속(hard) 행의 표식 종류 — METHODS 열만 읽음: tie_stiff spring = tie_spring, tie_value zero = tie_fixed, target =
    tie_disp. method_row 없음(옛 지그 고정 npz) = 값이 모두 0 이면 tie_fixed, 아니면 tie_disp."""
    if method_row is not None:
        if method_row["tie_stiff"] == "spring":
            return "tie_spring"
        return "tie_fixed" if method_row["tie_value"] == "zero" else "tie_disp"
    v = np.asarray(hard_vals if hard_vals is not None else [], dtype=np.float64)
    return "tie_fixed" if not np.any(v != 0.0) else "tie_disp"


def mark_dof(kind: str) -> str:
    """일반형 kind → 옛 dof 문자열(사이드카 dof 필드 — 옛 뷰어 호환): aux_inplane = MARK_AUX, 그 밖 tie = MARK_TIE."""
    return MARK_AUX if kind == "aux_inplane" else MARK_TIE


def _r6(v) -> float:
    return float(round(float(v), 6)) + 0.0


def support_marks_full(BC: dict, x0, smax: int, method_row: dict | None = None) -> list[tuple[int, str, list, object]]:
    """지그 3D 지지 표식 일반형(§10.2): [(노드 인덱스, kind, dirs, val)] — 노드·순서 = ``support_marks``(같은 ``_mark_nodes``).
    dirs = 그 노드의 행 방향(단위 3 벡터 목록 — 법선 1개, 꺾임 2개), val = tie_fixed 행마다 0 · tie_disp 행마다 g(mm) ·
    tie_spring {k: [N/mm…], g: [mm…]}(스프링 행) · aux_inplane 행마다 지정값. 값은 BC 배열(bc_*·sp_*)에서 그대로(새 계산 없음).
    method_row = METHODS 행(tie 종류 판정 — ``mark_kind_of``)."""
    B = save_bc(BC)
    tie, aux = _mark_nodes(B["bc_node"], B["bc_kind"], B["sp_node"], x0, smax)
    bn, bk = B["bc_node"], B["bc_kind"].astype(np.int64)
    sp = B["sp_node"]
    out = []
    for i in tie:
        rs = np.flatnonzero(sp == i)
        if rs.size:
            out.append((i, "tie_spring", [[_r6(x) for x in B["sp_dir"][r]] for r in rs],
                        {"k": [_r6(B["sp_k"][r]) for r in rs], "g": [_r6(B["sp_g"][r]) for r in rs]}))
            continue
        rh = np.flatnonzero((bn == i) & (bk == KIND_TIE))
        kind = mark_kind_of(method_row, B["bc_val"][rh])
        if kind == "tie_spring":                        # 스프링 방식인데 구속 행만 있음(있을 수 없음) — 값 그대로 변위로
            kind = "tie_disp"
        out.append((i, kind, [[_r6(x) for x in B["bc_dir"][r]] for r in rh],
                    [0.0 if kind == "tie_fixed" else _r6(B["bc_val"][r]) for r in rh]))
    for i in aux:
        ra = np.flatnonzero((bn == i) & (bk == KIND_AUX))
        out.append((i, "aux_inplane", [[_r6(x) for x in B["bc_dir"][r]] for r in ra], [_r6(B["bc_val"][r]) for r in ra]))
    return out


def mark_rows(marks, node_id) -> list[dict]:
    """일반형 표식 → 사이드카·3D 행 [{node_id, dof, kind, dirs, val}] (dof = 옛 문자열 — 옛 뷰어 호환)."""
    nid = np.asarray(node_id, dtype=np.int64)
    return [{"node_id": int(nid[i]), "dof": mark_dof(k), "kind": k, "dirs": d, "val": v} for i, k, d, v in marks]


# ====================================================================== (8) 저장 형식(배열 — 파일 IO 는 호출자)
def save_bc(BC: dict) -> dict:
    """BC → npz 배열 dict(고정 dtype — 없으면 길이 0)."""
    def arr(k, dt, shape2=None):
        a = np.asarray(BC.get(k, np.zeros(0)), dtype=dt)
        return a.reshape(-1, 3) if shape2 else a.reshape(-1)
    return {"bc_node": arr("bc_node", np.int64), "bc_dir": arr("bc_dir", np.float64, True),
            "bc_val": arr("bc_val", np.float64), "bc_kind": arr("bc_kind", np.int8),
            "sp_node": arr("sp_node", np.int64), "sp_dir": arr("sp_dir", np.float64, True),
            "sp_k": arr("sp_k", np.float64), "sp_g": arr("sp_g", np.float64)}


def load_bc(z) -> dict:
    """npz(또는 매핑) → BC(키 없음 = 길이 0)."""
    return save_bc({k: z[k] for k in BC_KEYS if k in z})


def pattern_sha(BC: dict) -> str:
    """구속 패턴(bc_node·bc_dir·sp_node·sp_dir·sp_k — 값 제외) sha256: 같은 값이면 같은 분해(④ 묶음·안 분해 공유 키)."""
    b = save_bc(BC)
    h = hashlib.sha256()
    for k in ("bc_node", "bc_dir", "sp_node", "sp_dir", "sp_k"):
        a = np.ascontiguousarray(b[k])
        h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
        h.update(a.tobytes())
    return h.hexdigest()


def kabsch_part(X0, u):
    """파트 Kabsch 프레임(스터디 sm_ref → prescribed·spring 목표, §3.2) = ``kabsch.remove_rigid``(유한 회전)."""
    return kabsch.remove_rigid(np.asarray(X0, dtype=np.float64), np.asarray(u, dtype=np.float64)[:, :3])[0]


check_plan()
