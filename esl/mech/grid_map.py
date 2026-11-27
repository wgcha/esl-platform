"""다른 메시 강성 스터디의 지그 ESL — Case 지그를 A 기준 공통 격자로 형상마다 사상 (계약 docs/contracts/esl_jig_grid_map.md §1·§2.1,
결정 D-0.24.8-JG-2~8·14).

모드 무관 독립 순수 모듈(AGENTS.md D-0.20.0-CODE): import = numpy · scipy.spatial(cKDTree) · scipy.sparse(.csgraph) · esl.errors ·
esl.library.normalize · esl.mech.{jig, jig_bc, kabsch, shell, bforce}. **esl.doe 금지·파일 IO 없음·설정 해석 없음**(값은 키워드 인수 —
기본값은 ``esl.doe.DEFAULTS["rank"]["jig_grid"]`` 한 곳), 시나리오·계획 이름 없음. 결정적(정렬 키·동률 = 작은 인덱스, cKDTree 결과
정렬, 고정 합 순서 — bincount). 메모리 O(N_S + P + V + 청크·k) — N_S×P 배열 없음.

흐름(호출자 = ``esl.doe.stages._jg_prep``·``_jg_shape``):
  A 쪽(BD_LOADS 1회, 원천 묶음 g 마다) ``grid_frame`` → ``build_field``(복셀 u 장) · ``tie_skeleton``(Case tie 점·변·면·클러스터) ·
  ``skel_spring``(스프링 출처: Case sp_k → 골격 면적 밀도 κ·클러스터 합 K_q).
  형상 S(BD_EVAL 마다) ``run_shape`` = ``capture``(골격 잡기 band|snap|miss) → ``shape_bcs``(형상 자기 tie_rows·3-2-1 재선정·g =
  골격 보간·3-2-1 값 = ``sample_field``·스프링 k = ``shape_spring_k``) → 패턴 묶음마다 분해 1(``jig_bc.factorize``) → 엔트리마다
  ``jig_bc.respond``(C_mix·E·W_F·W_g·R_sum·umax).

prep/jig_grid.json 스키마 ``SCHEMA`` · run/designs/<did>/jig_grid.json 스키마 ``RUN_SCHEMA`` (필드는 계약 §6 — stages 가 씀).
"""
from __future__ import annotations

import itertools
import time
from typing import Any

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from esl.errors import EslError
from esl.library import normalize as nz
from esl.mech import bforce, jig, jig_bc

SCHEMA = "esl/doe_jig_grid/1"
RUN_SCHEMA = "esl/doe_jig_grid_run/1"
VIA_MISS, VIA_BAND, VIA_SNAP = 0, 1, 2
VIA_FORCE = 3                                       # v0.25.2 강제 부여(esl_tstar_manual_jig_force.md §3.1)
VIA_NAMES = {VIA_MISS: "miss", VIA_BAND: "band", VIA_SNAP: "snap", VIA_FORCE: "force"}
# v0.25.2 옛 스냅샷 규칙(§3.6 — jig_bc.LEGACY_ABSENT 와 같은 관례): 스냅샷 rank.jig_grid 원본에 이 키가 없으면 DEFAULTS 에서 채우지
# 않고 이 값(None = 강제 부여 끔 → capture(force=None) = v0.25.1 코드 경로, 결과·해시 바이트 불변)
LEGACY_ABSENT = {"tie_force": None}
# v0.25.2 잡기 단계 표(§3.1 — D-0.25.2-8): capture 가 위에서부터 돈다(단계 이름 분기 없음 — 열만 읽음). 앞 단계가 잡은 노드는 뒤 단계가
# 다시 쓰지 않는다. target: all = 전 묶음 | empty = 앞 단계 뒤 노드 0 묶음. dist: 거리 한도 열(capture_rel·snap_rel = ×max(h_T, h_S),
# force = tie_force.max_dist_mm(None = 없음, 값 = max(값, snap 한도))). normal: 법선 조건 각 열. pick: within = 한도 안 전부 |
# nearest1 = 법선 맞는 최근접 1노드 | area_fill = 거리순 면적 합 ≥ 묶음 면적(최소 1). value: extrap = 골격 보간 + 선형 외삽 |
# point = 그 골격 점 | closest = 골격 최근접점(클립, 외삽 없음). on: always | force(= 스냅샷 tie_force.enabled). 못 잡은 묶음 = miss.
CAPTURE_STAGES = (
    {"via": VIA_BAND, "target": "all", "dist": "capture_rel", "normal": "tie_normal_deg", "pick": "within",
     "value": "extrap", "on": "always"},
    {"via": VIA_SNAP, "target": "empty", "dist": "snap_rel", "normal": "tie_normal_deg", "pick": "nearest1",
     "value": "point", "on": "always"},
    {"via": VIA_FORCE, "target": "empty", "dist": "force", "normal": "force_normal_deg", "pick": "area_fill",
     "value": "closest", "on": "force"},
)
ELEM_PT, ELEM_SEG, ELEM_TRI = 0, 1, 2
# 해시 밖 키(경고 임계·수렴 진단 크기·표시 판정 — 계산 결과(per_esl)를 바꾸지 않음, 계약 §7.1)
HASH_EXCLUDE = ("area_ratio_warn", "conv_warn", "frame_shift_warn", "load_resid_warn", "conv_mm", "noise_floor_min",
                "noise_floor_mismatch", "mesh_h_ratio_warn", "mesh_tri_frac_warn",    # v0.24.8 fix JG-23: 메시 차이 표시 판정(해시 밖)
                "tie_force_far_warn_mm")                     # v0.25.2 먼 강제 표시 임계(§3.6 — 경고·참고용·3D 색만)
# 해시에서 빼는 고정 키(백엔드 rank_snapshot 이 블록 안에 넣는 schema: 1 — 값 고정, 키 유무로 해시가 갈리지 않게)
HASH_FIXED = ("schema", "enabled")
# 격자 npz 키(§1.2 — stages 가 g<k>.npz 로 저장). 접미 <frame>·<src> 는 METHODS.frame·src 열 값
NPZ_FIELD = ("vox_key", "vox_x", "vox_n", "vox_a")
NPZ_SKEL = ("tie_idx", "tie_x", "tie_seg", "tie_tri", "tie_q", "tie_area", "tie_dir", "tie_rank", "h_T", "sup_x")


# ====================================================================== 격자 좌표계 — §1.1
def grid_frame(frame_A: dict, cell_mm: float) -> dict:
    """A ESL frame(``nz.frame``) + 칸 s → GF{frame, cell_mm, nx, ny, dxi, deta, dz, z0}. 칸 = 기존 셀 하중 칸과 같은 수식
    (nx = max(1, round(L_ξ/s)) — ``load_transfer.cell_loads``), 층 Δζ = s(z0 = z_range[0])."""
    s = float(cell_mm)
    if not np.isfinite(s) or s <= 0:
        raise EslError("INPUT_INVALID", f"격자 크기 {cell_mm!r} ≤ 0")
    fr = {k: (np.asarray(frame_A[k], dtype=np.float64).tolist() if k in ("origin", "e_xi", "e_eta", "n")
              else [float(x) for x in frame_A[k]]) for k in ("origin", "e_xi", "e_eta", "n", "a_range", "b_range")}
    L_xi = float(frame_A.get("L_xi", fr["a_range"][1] - fr["a_range"][0]))
    L_eta = float(frame_A.get("L_eta", fr["b_range"][1] - fr["b_range"][0]))
    nx, ny = max(1, round(L_xi / s)), max(1, round(L_eta / s))
    z0 = float((frame_A.get("z_range") or [0.0, 0.0])[0])
    return {"frame": fr, "cell_mm": s, "nx": int(nx), "ny": int(ny), "dxi": L_xi / nx, "deta": L_eta / ny, "dz": s,
            "z0": z0}


def vox_key(GF: dict, X) -> np.ndarray:
    """(N,3) A 좌표 → 복셀 키 (i, j, k) int64: i·j = ``nz.cell_index`` 와 같은 floor(+BOUNDARY_EPS)·clip, k = floor((ζ − z0)/s)."""
    loc = nz.local_coords(GF["frame"], np.asarray(X, dtype=np.float64).reshape(-1, 3))
    i = np.clip(np.floor(loc[:, 0] * GF["nx"] + nz.BOUNDARY_EPS).astype(np.int64), 0, GF["nx"] - 1)
    j = np.clip(np.floor(loc[:, 1] * GF["ny"] + nz.BOUNDARY_EPS).astype(np.int64), 0, GF["ny"] - 1)
    k = np.floor((loc[:, 2] - GF["z0"]) / GF["dz"]).astype(np.int64)
    return np.stack([i, j, k], axis=1)


def _orient_rows(V):
    """행마다 최대 절댓값 성분이 양수가 되게(동률 = 앞 성분)."""
    j = np.argmax(np.abs(V), axis=1)
    sg = np.sign(V[np.arange(V.shape[0]), j])
    sg[sg == 0] = 1.0
    return V * sg[:, None]


# ====================================================================== A 쪽 — §1.2
def build_field(GF: dict, X_A, weights_A: dict, U: dict) -> dict:
    """복셀 장: A 노드가 있는 칸만(키 사전순). 중심 X_v = ΣA·x/ΣA, 법선 N_v = Σ A m mᵀ 최대 고유벡터(부호 = 최대 절댓값 성분 +),
    면적 A_v, U_v = Σ A u/ΣA (프레임 열마다 (K, V, 3)). 면적 0 노드(고립)는 뺌. 반환 Field{key, x, n, a, u{frame}}."""
    X = np.asarray(X_A, dtype=np.float64)
    A = np.asarray(weights_A["area"], dtype=np.float64)
    m = np.asarray(weights_A["normal"], dtype=np.float64)
    use = np.flatnonzero(A > 0)
    keys, inv = np.unique(vox_key(GF, X[use]), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    V = keys.shape[0]
    a = np.bincount(inv, weights=A[use], minlength=V)
    xv = np.stack([np.bincount(inv, weights=A[use] * X[use, d], minlength=V) for d in range(3)], axis=1) / a[:, None]
    S = np.zeros((V, 3, 3))
    for p in range(3):
        for q in range(p, 3):
            S[:, p, q] = np.bincount(inv, weights=A[use] * m[use, p] * m[use, q], minlength=V)
            S[:, q, p] = S[:, p, q]
    _lam, vec = np.linalg.eigh(S)
    nv = _orient_rows(vec[:, :, 2])
    u_out = {}
    for fr, Uf in U.items():
        Uf = np.asarray(Uf, dtype=np.float64)
        K = Uf.shape[0]
        uo = np.zeros((K, V, 3))
        for kk in range(K):
            for d in range(3):
                uo[kk, :, d] = np.bincount(inv, weights=A[use] * Uf[kk, use, d], minlength=V) / a
        u_out[str(fr)] = uo
    return {"key": keys.astype(np.int64), "x": xv, "n": nv, "a": a, "u": u_out}


def _elem_edges(mesh) -> np.ndarray:
    """요소 변(정렬 쌍, 중복 제거) — 쿼드 4·트라이 3."""
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    q = np.asarray(mesh["elem_type"]).astype(np.int64) == 4
    pairs = [conn[:, [0, 1]], conn[:, [1, 2]], conn[q][:, [2, 3]], conn[q][:, [3, 0]], conn[~q][:, [2, 0]]]
    e = np.concatenate(pairs, axis=0)
    e = e[(e[:, 0] >= 0) & (e[:, 1] >= 0) & (e[:, 0] != e[:, 1])]
    e = np.sort(e, axis=1)
    return np.unique(e, axis=0) if e.size else np.zeros((0, 2), np.int64)


def tie_skeleton(mesh_A, tie_idx, tie_dir, tie_rank, U_tie: dict) -> dict:
    """tie 골격(§1.2): 점 P = tie_idx(A 노드 인덱스 — 정렬·중복 없음), 변 = 양 끝이 P 인 A 요소 변, 면 = 꼭짓점이 모두 P 인 A 요소
    (쿼드 → (0,1,2)(0,2,3)), 클러스터 q = 변 연결 성분, 면적 = ``jig.node_weights(A).area``, h_T = P 에 닿는 A 변 길이 중앙값.
    tie_dir (P,3,3)·tie_rank (P,) = Case 구속 방향(행 r < rank 만 유효), U_tie {frame: (K,P,3)}. 골격 인덱스 = P 안 위치."""
    P = np.asarray(tie_idx, dtype=np.int64).reshape(-1)
    if P.size == 0:
        raise EslError("JIG_NO_TIE", "Case 지그 tie 점이 없음")
    if np.any(np.diff(P) <= 0):
        raise EslError("INPUT_INVALID", "tie_idx 는 정렬·중복 없음이어야 함")
    X = np.asarray(mesh_A["x0"], dtype=np.float64)
    N = X.shape[0]
    pos = np.full(N, -1, np.int64)
    pos[P] = np.arange(P.size)
    E = _elem_edges(mesh_A)
    pe = pos[E] if E.size else np.zeros((0, 2), np.int64)
    seg = pe[(pe[:, 0] >= 0) & (pe[:, 1] >= 0)]
    seg = np.unique(np.sort(seg, axis=1), axis=0) if seg.size else np.zeros((0, 2), np.int64)
    touch = (pe[:, 0] >= 0) | (pe[:, 1] >= 0) if E.size else np.zeros(0, bool)
    L = np.linalg.norm(X[E[touch, 0]] - X[E[touch, 1]], axis=1) if E.size else np.zeros(0)
    h_T = float(np.median(L)) if L.size else 0.0
    conn = np.asarray(mesh_A["conn"], dtype=np.int64)
    q4 = np.asarray(mesh_A["elem_type"]).astype(np.int64) == 4
    pc = np.where(conn >= 0, pos[np.maximum(conn, 0)], -1)
    tri_rows = []
    full3 = (~q4) & np.all(pc[:, :3] >= 0, axis=1)
    tri_rows.append(pc[full3][:, :3])
    full4 = q4 & np.all(pc >= 0, axis=1)
    tri_rows.append(pc[full4][:, [0, 1, 2]])
    tri_rows.append(pc[full4][:, [0, 2, 3]])
    tri = np.concatenate(tri_rows, axis=0).astype(np.int64) if tri_rows else np.zeros((0, 3), np.int64)
    if seg.size:
        G = coo_matrix((np.ones(seg.shape[0]), (seg[:, 0], seg[:, 1])), shape=(P.size, P.size))
        nq, lab = connected_components(G, directed=False)
    else:
        nq, lab = P.size, np.arange(P.size)
    # 클러스터 번호 = 첫 점 인덱스 순(결정적)
    first = np.full(int(nq), P.size, np.int64)
    np.minimum.at(first, lab, np.arange(P.size))
    rel = np.empty(int(nq), np.int64)
    rel[np.argsort(first, kind="stable")] = np.arange(int(nq))
    q = rel[lab].astype(np.int64)
    w = jig.node_weights(mesh_A)
    td = np.asarray(tie_dir, dtype=np.float64).reshape(P.size, 3, 3)
    tr = np.asarray(tie_rank, dtype=np.int64).reshape(P.size)
    return {"idx": P, "x": X[P].copy(), "seg": seg.astype(np.int64), "tri": tri, "q": q, "n_q": int(nq),
            "area": np.asarray(w["area"], dtype=np.float64)[P].copy(), "dir": td, "rank": tr,
            "u": {str(k): np.asarray(v, dtype=np.float64) for k, v in U_tie.items()}, "h_T": h_T}


def tie_dirs_of(tie_nodes, bc_node, bc_dir, sp_node, sp_dir) -> tuple[np.ndarray, np.ndarray]:
    """Case 구속 행(bc_kind = tie 의 bc_* 와 sp_*, A 노드 인덱스) → 골격 점마다 방향 (P,3,3)·랭크 (P,)(행 순서 그대로, 최대 3)."""
    P = np.asarray(tie_nodes, dtype=np.int64)
    nodes = np.r_[np.asarray(bc_node, dtype=np.int64).reshape(-1), np.asarray(sp_node, dtype=np.int64).reshape(-1)]
    dirs = np.concatenate([np.asarray(bc_dir, dtype=np.float64).reshape(-1, 3),
                           np.asarray(sp_dir, dtype=np.float64).reshape(-1, 3)], axis=0)
    td = np.zeros((P.size, 3, 3))
    tr = np.zeros(P.size, np.int64)
    p = np.searchsorted(P, nodes)
    for r in range(nodes.size):
        i = int(p[r])
        if i < P.size and P[i] == nodes[r] and tr[i] < 3:
            td[i, tr[i]] = dirs[r]
            tr[i] += 1
    return td, tr


def skel_spring(skel: dict, sp_node, sp_k) -> dict:
    """스프링 면적 밀도(§1.2): 골격 점마다 κ_P = Σ_{행: sp_node = P} sp_k / A_P (N/mm³), 클러스터 합 K_q = Σ sp_k (N/mm).
    sp_node = A 노드 인덱스(Case 스프링 행 — 같은 노드 행끼리 k 가 달라도 합만 씀). 골격 밖 노드 = INPUT_INVALID."""
    P = skel["idx"]
    sn = np.asarray(sp_node, dtype=np.int64).reshape(-1)
    sk = np.asarray(sp_k, dtype=np.float64).reshape(-1)
    if sn.size != sk.size or sn.size == 0:
        raise EslError("INPUT_INVALID", "스프링 행 sp_node·sp_k 길이")
    pos = np.searchsorted(P, sn).clip(0, max(P.size - 1, 0))
    if np.any(P[pos] != sn):
        raise EslError("INPUT_INVALID", "스프링 행 노드가 tie 골격 밖")
    A = skel["area"]
    if np.any(A <= 0):
        raise EslError("INPUT_INVALID", "tie 골격 점 면적 0")
    ks = np.bincount(pos, weights=sk, minlength=P.size)
    return {"kappa": ks / A, "kq": np.bincount(skel["q"][pos], weights=sk, minlength=skel["n_q"])}


def case_tie(bc: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Case 지그 BC 배열(``jig_bc.save_bc`` — A 노드 인덱스) → tie 골격 점 P(스프링 출처 = unique(sp_node), 그 밖 bc_node[bc_kind =
    KIND_TIE]) · 방향 (P,3,3) · 랭크 (P,)."""
    b = jig_bc.load_bc(bc)
    sp = np.asarray(b["sp_node"], dtype=np.int64)
    kind = np.asarray(b["bc_kind"]).astype(np.int64)
    tsel = kind == jig_bc.KIND_TIE
    P = np.unique(sp) if sp.size else np.unique(np.asarray(b["bc_node"], dtype=np.int64)[tsel])
    td, tr = tie_dirs_of(P, np.asarray(b["bc_node"])[tsel], np.asarray(b["bc_dir"])[tsel], sp, b["sp_dir"])
    return P, td, tr


def build_group(mesh_A, frame_A: dict, cell_mm: float, tie_idx, tie_dir, tie_rank, U_frames: dict,
                spring_rows: dict | None = None, sup_x=None) -> dict:
    """원천 묶음 1개의 A 쪽 격자 값(§1.2): GF·복셀 장(U_frames = {frame: (K, N_A, 3)})·tie 골격(+ 골격 점 u)·스프링 출처마다 κ·K_q
    (spring_rows = {src: (sp_node, sp_k)} — 묶음 대표 엔트리 Case 행). 반환 G{GF, field, skel, spring{src: (kappa, kq)}, sup_x}."""
    X = np.asarray(mesh_A["x0"], dtype=np.float64)
    GF = grid_frame(frame_A, cell_mm)
    U = {str(k): np.asarray(v, dtype=np.float64) for k, v in U_frames.items()}
    field = build_field(GF, X, jig.node_weights(mesh_A), U)
    P = np.asarray(tie_idx, dtype=np.int64)
    skel = tie_skeleton(mesh_A, P, tie_dir, tie_rank, {k: v[:, P, :] for k, v in U.items()})
    sp = {}
    for src, (sn, sk) in (spring_rows or {}).items():
        r = skel_spring(skel, sn, sk)
        sp[str(src)] = (r["kappa"], r["kq"])
    return {"GF": GF, "field": field, "skel": skel, "spring": sp,
            "sup_x": None if sup_x is None else np.asarray(sup_x, dtype=np.float64).reshape(-1, 3)}


def group_arrays(G: dict) -> dict:
    """묶음 → npz 배열(§1.2 키). f_<src>·cellF/M 는 호출자가 더함."""
    f, sk = G["field"], G["skel"]
    out = {"vox_key": f["key"], "vox_x": f["x"], "vox_n": f["n"], "vox_a": f["a"],
           "tie_idx": sk["idx"], "tie_x": sk["x"], "tie_seg": sk["seg"], "tie_tri": sk["tri"], "tie_q": sk["q"],
           "tie_area": sk["area"], "tie_dir": sk["dir"], "tie_rank": sk["rank"], "h_T": np.asarray(sk["h_T"]),
           "sup_x": np.zeros((0, 3)) if G.get("sup_x") is None else G["sup_x"]}
    for fr, u in f["u"].items():
        out[f"vox_u_{fr}"] = u
    for fr, u in sk["u"].items():
        out[f"tie_u_{fr}"] = u
    for src, (kap, kq) in G["spring"].items():
        out[f"tie_kappa_{src}"] = kap
        out[f"tie_kq_{src}"] = kq
    return out


def group_from_arrays(z, frame_A: dict, cell_mm: float) -> dict:
    """npz 배열(``group_arrays``) → G(GF 는 frame_A·cell_mm 로 다시 — 결정적)."""
    keys = list(z.keys()) if hasattr(z, "keys") else list(z)
    fu = {k[len("vox_u_"):]: np.asarray(z[k], dtype=np.float64) for k in keys if k.startswith("vox_u_")}
    tu = {k[len("tie_u_"):]: np.asarray(z[k], dtype=np.float64) for k in keys if k.startswith("tie_u_")}
    q = np.asarray(z["tie_q"], dtype=np.int64)
    skel = {"idx": np.asarray(z["tie_idx"], dtype=np.int64), "x": np.asarray(z["tie_x"], dtype=np.float64),
            "seg": np.asarray(z["tie_seg"], dtype=np.int64).reshape(-1, 2),
            "tri": np.asarray(z["tie_tri"], dtype=np.int64).reshape(-1, 3), "q": q,
            "n_q": int(q.max()) + 1 if q.size else 0, "area": np.asarray(z["tie_area"], dtype=np.float64),
            "dir": np.asarray(z["tie_dir"], dtype=np.float64), "rank": np.asarray(z["tie_rank"], dtype=np.int64),
            "u": tu, "h_T": float(np.asarray(z["h_T"]).reshape(-1)[0])}
    sp = {k[len("tie_kappa_"):]: (np.asarray(z[k], dtype=np.float64), np.asarray(z["tie_kq_" + k[len("tie_kappa_"):]],
                                                                                   dtype=np.float64))
          for k in keys if k.startswith("tie_kappa_")}
    sx = np.asarray(z["sup_x"], dtype=np.float64).reshape(-1, 3) if "sup_x" in keys else np.zeros((0, 3))
    return {"GF": grid_frame(frame_A, cell_mm),
            "field": {"key": np.asarray(z["vox_key"], dtype=np.int64), "x": np.asarray(z["vox_x"], dtype=np.float64),
                      "n": np.asarray(z["vox_n"], dtype=np.float64), "a": np.asarray(z["vox_a"], dtype=np.float64),
                      "u": fu},
            "skel": skel, "spring": sp, "sup_x": sx if sx.size else None}


# ====================================================================== 거리(정확) — §1.3-2
def _closest_seg(p, a, b):
    ab = b - a
    den = np.einsum("ij,ij->i", ab, ab)
    t = np.divide(np.einsum("ij,ij->i", p - a, ab), den, out=np.zeros(den.shape), where=den > 0).clip(0.0, 1.0)
    c = a + t[:, None] * ab
    return np.linalg.norm(p - c, axis=1), t


def _closest_tri(p, a, b, c):
    """점-삼각형 최근접(Ericson, Real-Time Collision Detection §5.1.5) — 배열 버전. 반환 (거리, 무게중심 (M,3))."""
    M = p.shape[0]
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    bary = np.zeros((M, 3))
    done = np.zeros(M, bool)

    def put(mask, w):
        nonlocal done
        m = mask & ~done
        bary[m] = w[m] if np.ndim(w) == 2 else w
        done |= m
    with np.errstate(divide="ignore", invalid="ignore"):
        put((d1 <= 0) & (d2 <= 0), np.array([1.0, 0.0, 0.0]))                          # 꼭짓점 A
        put((d3 >= 0) & (d4 <= d3), np.array([0.0, 1.0, 0.0]))                          # 꼭짓점 B
        v = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), np.stack([1 - v, v, np.zeros(M)], axis=1))   # 변 AB
        put((d6 >= 0) & (d5 <= d6), np.array([0.0, 0.0, 1.0]))                          # 꼭짓점 C
        w = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), np.stack([1 - w, np.zeros(M), w], axis=1))   # 변 AC
        w2 = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), np.stack([np.zeros(M), 1 - w2, w2], axis=1))   # 변 BC
        den = va + vb + vc
        vv, ww = vb / den, vc / den
        put(np.ones(M, bool), np.stack([1 - vv - ww, vv, ww], axis=1))                  # 안쪽
    bary = np.nan_to_num(bary)
    q = bary[:, :1] * a + bary[:, 1:2] * b + bary[:, 2:3] * c
    return np.linalg.norm(p - q, axis=1), bary


def _csr(rows, n):
    """정점 → 원소 CSR(원소 = 행 위치)."""
    rows = np.asarray(rows, dtype=np.int64)
    if rows.size == 0:
        return np.zeros(n + 1, np.int64), np.zeros(0, np.int64)
    r = rows.reshape(rows.shape[0], -1)
    v = r.ravel()
    e = np.repeat(np.arange(r.shape[0]), r.shape[1])
    o = np.lexsort((e, v))
    v, e = v[o], e[o]
    ptr = np.zeros(n + 1, np.int64)
    np.add.at(ptr, v + 1, 1)
    return np.cumsum(ptr), e


def _gather(ptr, ix, pts):
    """점 목록 pts 의 CSR 원소 → (pair 위치, 원소)."""
    cnt = ptr[pts + 1] - ptr[pts]
    tot = int(cnt.sum())
    if tot == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    rep = np.repeat(np.arange(pts.size), cnt)
    off = np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    return rep, ix[ptr[pts][rep] + off]


def _proj_ok(m, dirs, rank, cosv):
    """법선 맞음: m 의 구속 방향 부분공간(행 r < rank) 사영 노름 ≥ cos(각). m = 0 → 거짓."""
    d = np.einsum("nri,ni->nr", dirs, m)
    valid = np.arange(3)[None, :] < rank[:, None]
    pn = np.sqrt(np.sum(np.where(valid, d * d, 0.0), axis=1))
    return (pn >= cosv) & (np.linalg.norm(m, axis=1) > 0)


def _shape_h(mesh_S, Xs, near: np.ndarray | None) -> float:
    E = _elem_edges(mesh_S)
    if E.size == 0:
        return 0.0
    if near is not None and near.any():
        sel = near[E[:, 0]] | near[E[:, 1]]
        if sel.any():
            E = E[sel]
    return float(np.median(np.linalg.norm(Xs[E[:, 0]] - Xs[E[:, 1]], axis=1)))


def capture(skel: dict, mesh_S, Xs_A, R_pl, *, capture_rel: float, snap_rel: float, normal_deg: float,
            force: dict | None = None) -> dict:
    """tie 잡기(§1.3-2): 형상 노드 ŷ(A 좌표)의 골격 거리 d = min(점·변·면 정확 거리). r_cap = capture_rel·max(h_T, h_S),
    band = d ≤ r_cap ∧ 법선 맞음(형상 법선 R_plᵀ m 의 최근접 골격 점 구속 방향 부분공간 사영 ≥ cos(normal_deg)), 띠 0 클러스터 =
    법선 맞는 최근접 1노드(≤ snap_rel·max(h_T, h_S) — snap), 그래도 0 = miss. 반환 Cap{idx (m,) 정렬, elem_kind, elem, pts (m,3),
    w (m,3)(골격 점 보간 — 면 = 무게중심, 변 = 선형, 점·snap = 그 점), dist, via, q (m,), clusters[…], n_reject_normal, r_cap, h_S}.

    v0.25.2(esl_tstar_manual_jig_force.md §3.1·§3.2): 단계는 CAPTURE_STAGES 표를 위에서부터 돈다(열 pick 으로 함수 선택 — 이름 분기
    없음). force = 스냅샷 rank.jig_grid.tie_force{enabled, max_dist_mm, normal_deg}(None = v0.25.1 코드 경로 그대로 — 결과 바이트 불변).
    강제 단계 묶음 기록 = via "force"·dist·shift, Cap 에 force(설정 사본)·r_snap·force_limit 추가(force 가 있을 때만)."""
    S = _cap_init(skel, mesh_S, Xs_A, R_pl, capture_rel=capture_rel, snap_rel=snap_rel, normal_deg=normal_deg, force=force)
    on = {"always": True, "force": bool(force and force.get("enabled"))}
    for row in CAPTURE_STAGES:
        if not on[row["on"]]:
            continue
        _PICK[row["pick"]](S, row)
    return _cap_finish(S)


def _cap_init(skel, mesh_S, Xs_A, R_pl, *, capture_rel, snap_rel, normal_deg, force) -> dict:
    Xs = np.asarray(Xs_A, dtype=np.float64)
    R = np.asarray(R_pl, dtype=np.float64).reshape(3, 3)
    wS = jig.node_weights(mesh_S)
    mA = np.asarray(wS["normal"], dtype=np.float64) @ R          # 형상 법선 → A 좌표(행 벡터: v_A = v_S R)
    aS = np.asarray(wS["area"], dtype=np.float64)
    Xp = skel["x"]
    tP = cKDTree(Xp)
    h_T = float(skel["h_T"])
    dn, _ = tP.query(Xs, k=1, distance_upper_bound=2.0 * h_T if h_T > 0 else np.inf)
    h_S = _shape_h(mesh_S, Xs, np.isfinite(dn))
    href = max(h_T, h_S)
    seg = skel["seg"]
    return {"skel": skel, "Xs": Xs, "NS": Xs.shape[0], "mA": mA, "aS": aS, "tP": tP, "tS": None, "h_S": h_S,
            "r_cap": float(capture_rel) * href, "r_snap": float(snap_rel) * href,
            "Lmax": float(np.linalg.norm(Xp[seg[:, 0]] - Xp[seg[:, 1]], axis=1).max()) if seg.size else 0.0,
            "cosv": float(np.cos(np.radians(float(normal_deg)))), "force": None if force is None else dict(force),
            "taken": np.zeros(Xs.shape[0], bool), "parts": [], "n_rej": 0, "cl_extra": {}}


def _cap_have(S) -> np.ndarray:
    """묶음별 지금까지 잡힌 노드 수."""
    nq = S["skel"]["n_q"]
    have = np.zeros(nq, np.int64)
    for p in S["parts"]:
        if p["q"].size:
            have += np.bincount(p["q"], minlength=nq)
    return have


def _cap_put(S, idx, kind, elem, dist, pts, w, qn, via: int) -> None:
    S["parts"].append({"idx": np.asarray(idx, np.int64), "kind": np.asarray(kind, np.int64), "elem": np.asarray(elem, np.int64),
                       "dist": np.asarray(dist, np.float64), "pts": np.asarray(pts, np.int64).reshape(-1, 3),
                       "w": np.asarray(w, np.float64).reshape(-1, 3), "q": np.asarray(qn, np.int64),
                       "via": np.full(np.asarray(idx).size, via, np.int64)})
    S["taken"][np.asarray(idx, np.int64)] = True


def _pick_within(S, row) -> None:
    """band(표 행 1 — v0.25.1 코드 그대로): 후보 × 골격 원소(점·변·면) 정확 거리 ≤ r_cap ∧ 법선 맞음, 대상 = 전 묶음."""
    skel, Xs, mA = S["skel"], S["Xs"], S["mA"]
    Xp, tP = skel["x"], S["tP"]
    nP = skel["idx"].size
    r_cap, Lmax, cosv = S["r_cap"], S["Lmax"], S["cosv"]
    seg, tri = skel["seg"], skel["tri"]
    dc, _ = tP.query(Xs, k=1, distance_upper_bound=r_cap + Lmax + 1e-12)
    cand = np.flatnonzero(np.isfinite(dc))
    # 후보 × 골격 원소 쌍(점·변·면) — 원소 = 후보 공 안 점에 닿는 것
    balls = tP.query_ball_point(Xs[cand], r_cap + Lmax + 1e-12) if cand.size else []
    pc = np.repeat(np.arange(cand.size), [len(b) for b in balls]) if cand.size else np.zeros(0, np.int64)
    pp = np.asarray([i for b in balls for i in sorted(b)], dtype=np.int64)
    sptr, six = _csr(seg, nP)
    tptr, tix = _csr(tri, nP)
    rows = []                                               # (후보 위치, kind, 원소, 거리, w0, w1, w2, p0, p1, p2)
    if pp.size:
        d0 = np.linalg.norm(Xs[cand[pc]] - Xp[pp], axis=1)
        rows.append((pc, np.full(pc.size, ELEM_PT), pp, d0, np.ones(pc.size), np.zeros(pc.size), np.zeros(pc.size),
                     pp, pp, pp))
        r_, e_ = _gather(sptr, six, pp)
        if r_.size:
            key = np.unique(np.stack([pc[r_], e_], axis=1), axis=0)
            a, b = seg[key[:, 1], 0], seg[key[:, 1], 1]
            d1, t = _closest_seg(Xs[cand[key[:, 0]]], Xp[a], Xp[b])
            rows.append((key[:, 0], np.full(key.shape[0], ELEM_SEG), key[:, 1], d1, 1 - t, t, np.zeros(t.size), a, b, a))
        r_, e_ = _gather(tptr, tix, pp)
        if r_.size:
            key = np.unique(np.stack([pc[r_], e_], axis=1), axis=0)
            a, b, c = tri[key[:, 1], 0], tri[key[:, 1], 1], tri[key[:, 1], 2]
            d2, bc = _closest_tri(Xs[cand[key[:, 0]]], Xp[a], Xp[b], Xp[c])
            rows.append((key[:, 0], np.full(key.shape[0], ELEM_TRI), key[:, 1], d2, bc[:, 0], bc[:, 1], bc[:, 2], a, b, c))
    if rows:
        cols = [np.concatenate([r[i] for r in rows]) for i in range(10)]
        o = np.lexsort((cols[2], cols[1], cols[3], cols[0]))      # 후보 → 거리 → kind(점 우선) → 원소 번호
        cols = [x[o] for x in cols]
        first = np.r_[True, cols[0][1:] != cols[0][:-1]]
        cols = [x[first] for x in cols]
        cidx = cand[cols[0]]
        W = np.stack(cols[4:7], axis=1)
        PT = np.stack(cols[7:10], axis=1).astype(np.int64)
        near_pt = PT[np.arange(PT.shape[0]), np.argmax(W, axis=1)]
        ok = _proj_ok(mA[cidx], skel["dir"][near_pt], skel["rank"][near_pt], cosv)
        inb = cols[3] <= r_cap
        band = inb & ok
        S["n_rej"] = int(np.sum(inb & ~ok))
        sel = np.flatnonzero(band)
        _cap_put(S, cidx[sel], cols[1][sel].astype(np.int64), cols[2][sel].astype(np.int64), cols[3][sel], PT[sel], W[sel],
                 skel["q"][near_pt[sel]], int(row["via"]))
    else:
        _cap_put(S, np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0), np.zeros((0, 3), np.int64),
                 np.zeros((0, 3)), np.zeros(0, np.int64), int(row["via"]))


def _pick_nearest1(S, row) -> None:
    """snap(표 행 2 — v0.25.1 코드 그대로): 노드 0 묶음마다 법선 맞는 최근접 1노드(≤ r_snap), 값 = 그 골격 점."""
    skel, Xs, mA, taken = S["skel"], S["Xs"], S["mA"], S["taken"]
    Xp = skel["x"]
    r_snap, cosv = S["r_snap"], S["cosv"]
    have = _cap_have(S)
    if S["tS"] is None:
        S["tS"] = cKDTree(Xs)
    tS = S["tS"]
    add = []
    for q in np.flatnonzero(have == 0).tolist():                # snap(클러스터 순 — 결정적)
        Pq = np.flatnonzero(skel["q"] == q)
        best = None
        for pi in Pq.tolist():
            for n in sorted(tS.query_ball_point(Xp[pi], r_snap + 1e-12)):
                if taken[n]:
                    continue
                if not _proj_ok(mA[n:n + 1], skel["dir"][pi:pi + 1], skel["rank"][pi:pi + 1], cosv)[0]:
                    continue
                d = float(np.linalg.norm(Xs[n] - Xp[pi]))
                if best is None or (d, n, pi) < best:
                    best = (d, n, pi)
        if best is not None:
            d, n, pi = best
            taken[n] = True
            add.append((n, ELEM_PT, pi, d, pi, q))
    if add:
        a_ = np.asarray(add, dtype=np.float64)
        pp_ = a_[:, 4].astype(np.int64)
        _cap_put(S, a_[:, 0].astype(np.int64), a_[:, 1].astype(np.int64), a_[:, 2].astype(np.int64), a_[:, 3],
                 np.stack([pp_, pp_, pp_], axis=1), np.tile([1.0, 0.0, 0.0], (pp_.size, 1)), a_[:, 5].astype(np.int64),
                 int(row["via"]))


def _closest_cluster(skel: dict, X, Pq, segq, triq):
    """점들 X (M,3) → 묶음 골격(점 Pq·변 segq 행·면 triq 행 — 골격 전역 번호) 최근접: (kind, elem, dist, pts (M,3), w (M,3)),
    동률 = 거리 → kind(점 우선) → 원소 번호(band 와 같은 규칙). 외삽 없음(클립 — 변 t ∈ [0,1], 면 = Ericson 최근접)."""
    Xp, seg, tri = skel["x"], skel["seg"], skel["tri"]
    M = X.shape[0]
    rows = []
    pc = np.repeat(np.arange(M), Pq.size)
    pp = np.tile(Pq, M)
    rows.append((pc, np.full(pc.size, ELEM_PT), pp, np.linalg.norm(X[pc] - Xp[pp], axis=1), np.ones(pc.size),
                 np.zeros(pc.size), np.zeros(pc.size), pp, pp, pp))
    if segq.size:
        pc = np.repeat(np.arange(M), segq.size)
        e_ = np.tile(segq, M)
        a, b = seg[e_, 0], seg[e_, 1]
        d1, t = _closest_seg(X[pc], Xp[a], Xp[b])
        rows.append((pc, np.full(pc.size, ELEM_SEG), e_, d1, 1 - t, t, np.zeros(t.size), a, b, a))
    if triq.size:
        pc = np.repeat(np.arange(M), triq.size)
        e_ = np.tile(triq, M)
        a, b, c = tri[e_, 0], tri[e_, 1], tri[e_, 2]
        d2, bc = _closest_tri(X[pc], Xp[a], Xp[b], Xp[c])
        rows.append((pc, np.full(pc.size, ELEM_TRI), e_, d2, bc[:, 0], bc[:, 1], bc[:, 2], a, b, c))
    cols = [np.concatenate([r[i] for r in rows]) for i in range(10)]
    o = np.lexsort((cols[2], cols[1], cols[3], cols[0]))
    cols = [x[o] for x in cols]
    first = np.r_[True, cols[0][1:] != cols[0][:-1]]
    cols = [x[first] for x in cols]
    return (cols[1].astype(np.int64), cols[2].astype(np.int64), cols[3], np.stack(cols[7:10], axis=1).astype(np.int64),
            np.stack(cols[4:7], axis=1))


FORCE_K0 = 16                                       # 강제 단계 KD 최근접 질의 첫 k(배증 — 결과와 무관, 속도만)


def _pick_area_fill(S, row) -> None:
    """강제 부여(표 행 3 — §3.2): 앞 단계 뒤에도 노드 0 인 묶음 q 마다(묶음 번호 순), 안 잡힌 형상 노드를 묶음 골격까지 정확 거리 d
    (점·변·면 최근접 — 클립)로 (d, 노드 번호) 오름차순 → 면적 합 ≥ 묶음 면적 A_q 인 첫 노드까지(최소 1, 모자라면 있는 만큼).
    거리 한도 = force.max_dist_mm(None = 없음, 값 = max(값, r_snap)), 법선 조건 = force.normal_deg(≥ 90 = 없음, 아니면 band 와 같은
    _proj_ok). 형상 전체를 정렬하지 않음: 묶음 골격 점에서 형상 KD 최근접 k 배증 + 정확 거리 하한 d ≥ d_점 − L_q(L_q = 묶음 변 최대
    길이) — 고른 마지막 거리 + L_q 가 k 번째 이웃 거리보다 작으면 완결."""
    skel, Xs, aS, mA, taken, NS = S["skel"], S["Xs"], S["aS"], S["mA"], S["taken"], S["NS"]
    fc = S["force"] or {}
    md = fc.get("max_dist_mm")
    lim = None if md is None else max(float(md), S["r_snap"])
    nd = float(fc.get("normal_deg", 90.0))
    use_n = nd < 90.0
    cosf = float(np.cos(np.radians(nd)))
    Xp, seg, tri = skel["x"], skel["seg"], skel["tri"]
    Aq = np.bincount(skel["q"], weights=skel["area"], minlength=skel["n_q"])
    have = _cap_have(S)
    if S["tS"] is None:
        S["tS"] = cKDTree(Xs)
    tS = S["tS"]
    S["force_limit"] = lim
    for q in np.flatnonzero(have == 0).tolist():
        Pq = np.flatnonzero(skel["q"] == q)
        segq = np.flatnonzero(skel["q"][seg[:, 0]] == q) if seg.size else np.zeros(0, np.int64)
        triq = np.flatnonzero(skel["q"][tri[:, 0]] == q) if tri.size else np.zeros(0, np.int64)
        Lq = float(np.linalg.norm(Xp[seg[segq, 0]] - Xp[seg[segq, 1]], axis=1).max()) if segq.size else 0.0
        tQ = cKDTree(Xp[Pq])
        k = FORCE_K0
        pick = None
        while True:
            kk = min(k, NS)
            dk, ik = tS.query(Xp[Pq], k=kk)
            dk, ik = np.asarray(dk).reshape(Pq.size, -1), np.asarray(ik).reshape(Pq.size, -1)
            complete = kk >= NS
            r_k = np.inf if complete else float(dk[:, -1].min())      # 이 밖의 노드는 d_점 ≥ r_k → d ≥ r_k − L_q
            cand = np.unique(ik[ik < NS])
            cand = cand[~taken[cand]]
            res = _area_fill_one(skel, Xs, aS, mA, cand, tQ, Pq, segq, triq, Lq, float(Aq[q]), lim, use_n, cosf)
            if res is not None:
                sel, d_need = res
                if complete or d_need < r_k:
                    pick = sel
                    break
            elif complete:
                break
            k *= 2
        if pick is None or pick[0].size == 0:
            continue                                         # 못 붙임(miss) — 한도·법선 조건 밖이거나 남은 노드 없음
        n_, kd_, el_, ds_, pt_, w_ = pick
        _cap_put(S, n_, kd_, el_, ds_, pt_, w_, np.full(n_.size, q, np.int64), int(row["via"]))
        a_s = aS[n_]
        xs = (a_s @ Xs[n_]) / a_s.sum() if a_s.sum() > 0 else Xs[n_].mean(axis=0)
        a_p = skel["area"][Pq]
        xa = (a_p @ Xp[Pq]) / a_p.sum() if a_p.sum() > 0 else Xp[Pq].mean(axis=0)
        S["cl_extra"][q] = {"dist": float(ds_.max()), "shift": float(np.linalg.norm(xs - xa))}


def _area_fill_one(skel, Xs, aS, mA, cand, tQ, Pq, segq, triq, Lq: float, A: float, lim, use_n: bool, cosf: float):
    """후보 cand(KD 최근접 합집합 — 안 잡힌 노드) 안에서 강제 선택. 반환 None(후보 없음) 또는 (선택 (n, kind, elem, dist, pts, w),
    완결에 필요한 거리 d_need — 이 거리 안의 형상 노드가 모두 cand 에 있어야 선택이 정확). 정확 거리는 점 거리 d_점 ≤ T 인 풀에만
    계산(T = 점 거리로 면적이 차는 거리 + L_q, 모자라면 배증 — 정확 거리 ≤ d 인 노드는 d_점 ≤ d + L_q)."""
    if cand.size == 0:
        return None
    d_pt, _j = tQ.query(Xs[cand], k=1)
    d_pt = np.asarray(d_pt, dtype=np.float64).reshape(-1)
    if lim is not None:
        keep = d_pt - Lq <= lim
        cand, d_pt = cand[keep], d_pt[keep]
        if cand.size == 0:
            return (np.zeros(0, np.int64),) * 6, lim + Lq
    o = np.lexsort((cand, d_pt))
    cs = np.cumsum(aS[cand[o]])
    h = np.flatnonzero(cs >= A)
    T = (float(d_pt[o[h[0]]]) if h.size else np.inf) + Lq
    while True:
        pool = np.flatnonzero(d_pt <= T) if np.isfinite(T) else np.arange(cand.size)
        kind, elem, dist, pts, w = _closest_cluster(skel, Xs[cand[pool]], Pq, segq, triq)
        ok = np.ones(pool.size, bool)
        if use_n:
            near_pt = pts[np.arange(pts.shape[0]), np.argmax(w, axis=1)]
            ok &= _proj_ok(mA[cand[pool]], skel["dir"][near_pt], skel["rank"][near_pt], cosf)
        if lim is not None:
            ok &= dist <= lim
        oo = np.flatnonzero(ok)
        oo = oo[np.lexsort((cand[pool][oo], dist[oo]))]
        csum = np.cumsum(aS[cand[pool][oo]])
        hit = np.flatnonzero(csum >= A)
        if hit.size:
            m_ = int(hit[0]) + 1
            d_last = float(dist[oo[m_ - 1]])
            if not np.isfinite(T) or d_last + Lq <= T:          # 풀 밖 노드는 정확 거리 > T − L_q ≥ d_last
                sel = oo[:m_]
                return (cand[pool][sel], kind[sel], elem[sel], dist[sel], pts[sel], w[sel]), d_last + Lq
        elif not np.isfinite(T) or pool.size == cand.size:
            sel = oo                                         # 면적 모자람 — 있는 만큼(한도 안 전부)
            need = (lim + Lq) if lim is not None else np.inf
            return (cand[pool][sel], kind[sel], elem[sel], dist[sel], pts[sel], w[sel]), need
        T = np.inf if not np.isfinite(T) or T <= 0 else 2.0 * T


_PICK = {"within": _pick_within, "nearest1": _pick_nearest1, "area_fill": _pick_area_fill}


def _cap_finish(S) -> dict:
    skel, Xs, aS = S["skel"], S["Xs"], S["aS"]
    parts = S["parts"]
    cat = {k: (np.concatenate([p[k] for p in parts]) if parts else None) for k in ("idx", "kind", "elem", "dist", "q", "via")}
    idx = cat["idx"] if parts else np.zeros(0, np.int64)
    kind = cat["kind"] if parts else np.zeros(0, np.int64)
    elem = cat["elem"] if parts else np.zeros(0, np.int64)
    dist = cat["dist"] if parts else np.zeros(0)
    qn = cat["q"] if parts else np.zeros(0, np.int64)
    via = cat["via"] if parts else np.zeros(0, np.int64)
    pts = np.concatenate([p["pts"] for p in parts], axis=0) if parts else np.zeros((0, 3), np.int64)
    w = np.concatenate([p["w"] for p in parts], axis=0) if parts else np.zeros((0, 3))
    o = np.argsort(idx, kind="stable")
    idx, kind, elem, dist, pts, w, qn, via = idx[o], kind[o], elem[o], dist[o], pts[o], w[o], qn[o], via[o]
    w_clip, pts_clip = w.copy(), pts.copy()
    w, pts = _extrapolate(skel, Xs, idx, kind, dist, via, pts, w)
    cl = []
    na = np.bincount(skel["q"], minlength=skel["n_q"])
    aa = np.bincount(skel["q"], weights=skel["area"], minlength=skel["n_q"])
    ns = np.bincount(qn, minlength=skel["n_q"]) if qn.size else np.zeros(skel["n_q"], np.int64)
    as_ = np.bincount(qn, weights=aS[idx], minlength=skel["n_q"]) if qn.size else np.zeros(skel["n_q"])
    snapq = set(qn[via == VIA_SNAP].tolist())
    forceq = set(qn[via == VIA_FORCE].tolist())
    for q in range(skel["n_q"]):
        v = VIA_FORCE if q in forceq else (VIA_SNAP if q in snapq else (VIA_BAND if ns[q] else VIA_MISS))
        rec = {"q": q, "n_a": int(na[q]), "n_s": int(ns[q]), "area_a": float(aa[q]), "area_s": float(as_[q]),
               "via": VIA_NAMES[v], "miss": v == VIA_MISS}
        if v == VIA_FORCE:
            rec.update(S["cl_extra"][q])
        cl.append(rec)
    out = {"idx": idx, "elem_kind": kind, "elem": elem, "pts": pts, "w": w, "w_clip": w_clip, "pts_clip": pts_clip, "dist": dist,
           "via": via, "q": qn,
           "clusters": cl, "n_reject_normal": S["n_rej"], "r_cap": S["r_cap"], "h_S": S["h_S"], "normal_A": S["mA"], "area_S": aS}
    if S["force"] is not None:                       # v0.25.2: 강제 부여 설정이 있는 스냅샷만(옛 = 키 없음)
        out.update(force=S["force"], r_snap=S["r_snap"], force_limit=S.get("force_limit"))
    return out


def _extrapolate(skel: dict, Xs, idx, kind, dist, via, pts, w):
    """골격 밖 띠 노드(D-0.24.8-JG-16 — 최근접이 변·점, 거리 > 0, band)의 보간 → 선형 외삽: 최근접 골격 점에 닿는 면 중 바깥 정도
    (음의 무게중심 합)가 가장 작은 면의 비클립 무게중심(평면 사영), 면이 없으면 변 = 선분 방향 비클립 선형, 점·snap = 그 값.
    외삽 거리 ≤ r_cap(잡힌 노드만). 거리 0(A 를 형상으로 — 항등)은 그대로."""
    w = w.copy()
    pts = pts.copy()
    tri, seg, Xp = skel["tri"], skel["seg"], skel["x"]
    tptr, tix = _csr(tri, Xp.shape[0])
    for i in np.flatnonzero((kind != ELEM_TRI) & (dist > 0) & (via == VIA_BAND)):
        x = Xs[idx[i]]
        near = int(pts[i, int(np.argmax(w[i]))])
        cand = tix[tptr[near]:tptr[near + 1]]
        best = None
        for t in cand.tolist():
            a, b, c = Xp[tri[t]]
            nrm = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(nrm))
            if ln <= 0:
                continue
            nrm /= ln
            xp = x - float(np.dot(x - a, nrm)) * nrm
            T = np.column_stack([b - a, c - a])
            lam = np.linalg.lstsq(T, xp - a, rcond=None)[0]
            bc = np.array([1.0 - lam.sum(), lam[0], lam[1]])
            out = float(-np.minimum(bc, 0.0).sum())
            if best is None or (out, t) < best[:2]:
                best = (out, t, bc)
        if best is not None:
            w[i] = best[2]
            pts[i] = tri[best[1]]
        elif kind[i] == ELEM_SEG:
            sa, sb = int(pts[i, 0]), int(pts[i, 1])
            ab = Xp[sb] - Xp[sa]
            den = float(ab @ ab)
            tt = float((x - Xp[sa]) @ ab) / den if den > 0 else 0.0
            w[i] = [1.0 - tt, tt, 0.0]
    return w, pts


def sample_tie(skel: dict, cap: dict, frame: str, k: int) -> np.ndarray:
    """골격 보간(§1.3-3) of tie_u_<frame>[k] → (m,3) A 좌표 값(잡힌 노드 순)."""
    u = skel["u"][frame][int(k)]
    return np.einsum("mj,mjd->md", cap["w"], u[cap["pts"]])


def _tangent(m):
    m = np.asarray(m, dtype=np.float64)
    nm = np.linalg.norm(m, axis=1)
    m = np.divide(m, nm[:, None], out=np.tile([0.0, 0.0, 1.0], (m.shape[0], 1)), where=nm[:, None] > 0)
    e = np.tile([1.0, 0.0, 0.0], (m.shape[0], 1))
    e[np.abs(m[:, 0]) > 0.9] = [0.0, 1.0, 0.0]
    t1 = e - np.einsum("ij,ij->i", e, m)[:, None] * m
    t1 /= np.linalg.norm(t1, axis=1)[:, None]
    return m, t1, np.cross(m, t1)


def sample_field(field: dict, GF: dict, Xq_A, mq_A, frame: str, k: int, *, nbr: int, normal_deg: float) -> dict:
    """복셀 표본(노드 보간, §1.3-5): 이웃 (2·nbr+1)³ 복셀 중 |N_v·m| ≥ cos(normal_deg)(없으면 법선 조건 없이 — n_normal_relax),
    w_v = A_v·exp(−(‖X_v − ŷ‖/s)²), 접평면 2D 선형 가중 최소제곱 → 절편 c. 후보 < 3 ∨ 중심 모멘트 최소 고유값 < (0.1 s)²Σw = 가중 평균
    (n_const). 후보 0 = 이웃 ×2 한 번(n_expand), 그래도 0 = 격자 밖(값 0, n_outside). 반환 {u (q,3), n_const, n_expand, n_outside,
    n_normal_relax, max_dist}."""
    Xq = np.asarray(Xq_A, dtype=np.float64).reshape(-1, 3)
    nq = Xq.shape[0]
    out = np.zeros((nq, 3))
    res = {"u": out, "n_const": 0, "n_expand": 0, "n_outside": 0, "n_normal_relax": 0, "max_dist": 0.0}
    if nq == 0:
        return res
    keys = field["key"]
    s = float(GF["cell_mm"])
    U = field["u"][frame][int(k)]
    m, t1, t2 = _tangent(mq_A)
    cosv = float(np.cos(np.radians(float(normal_deg))))
    qk = vox_key(GF, Xq)
    lo = np.minimum(keys.min(axis=0), qk.min(axis=0)) - 2 * int(nbr) - 1
    hi = np.maximum(keys.max(axis=0), qk.max(axis=0)) + 2 * int(nbr) + 1
    dims = hi - lo + 1

    def code(kk):
        r = kk - lo
        return (r[:, 0] * dims[1] + r[:, 1]) * dims[2] + r[:, 2]
    vcode = code(keys)                                      # 사전순 키 → 단조 코드(정렬됨)

    def pairs(qsel, n):
        qq, vv = [], []
        for off in itertools.product(range(-n, n + 1), repeat=3):
            c = code(qk[qsel] + np.asarray(off, dtype=np.int64))
            p = np.searchsorted(vcode, c).clip(0, vcode.size - 1)
            hit = vcode[p] == c
            qq.append(qsel[hit])
            vv.append(p[hit])
        qq, vv = np.concatenate(qq), np.concatenate(vv)
        o = np.lexsort((vv, qq))
        return qq[o], vv[o]
    allq = np.arange(nq)
    qq, vv = pairs(allq, int(nbr))
    cnt = np.bincount(qq, minlength=nq)
    empty = np.flatnonzero(cnt == 0)
    if empty.size:
        q2, v2 = pairs(empty, 2 * int(nbr))
        res["n_expand"] = int(empty.size)
        qq, vv = np.r_[qq, q2], np.r_[vv, v2]
        o = np.lexsort((vv, qq))
        qq, vv = qq[o], vv[o]
    cnt = np.bincount(qq, minlength=nq)
    res["n_outside"] = int(np.sum(cnt == 0))
    if qq.size == 0:
        return res
    nok = np.abs(np.einsum("ij,ij->i", field["n"][vv], m[qq])) >= cosv
    has_ok = np.bincount(qq, weights=nok.astype(float), minlength=nq) > 0
    keep = nok | ~has_ok[qq]
    res["n_normal_relax"] = int(np.sum((cnt > 0) & ~has_ok))
    qq, vv = qq[keep], vv[keep]
    d = field["x"][vv] - Xq[qq]
    dist = np.linalg.norm(d, axis=1)
    w = field["a"][vv] * np.exp(-(dist / s) ** 2)
    a = np.einsum("ij,ij->i", d, t1[qq])
    b = np.einsum("ij,ij->i", d, t2[qq])

    def acc(x):
        return np.bincount(qq, weights=x, minlength=nq)
    S0, Sa, Sb = acc(w), acc(w * a), acc(w * b)
    Saa, Sab, Sbb = acc(w * a * a), acc(w * a * b), acc(w * b * b)
    Su = np.stack([acc(w * U[vv, j]) for j in range(3)], axis=1)
    Sau = np.stack([acc(w * a * U[vv, j]) for j in range(3)], axis=1)
    Sbu = np.stack([acc(w * b * U[vv, j]) for j in range(3)], axis=1)
    ncnt = np.bincount(qq, minlength=nq)
    dmin = np.full(nq, np.inf)
    np.minimum.at(dmin, qq, dist)
    ok = S0 > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        Caa = Saa - Sa * Sa / S0
        Cab = Sab - Sa * Sb / S0
        Cbb = Sbb - Sb * Sb / S0
        tr, det = Caa + Cbb, Caa * Cbb - Cab * Cab
        lmin = 0.5 * (tr - np.sqrt(np.maximum(tr * tr - 4 * det, 0.0)))
    lin = ok & (ncnt >= 3) & (lmin >= (0.1 * s) ** 2 * S0)
    const = ok & ~lin
    out[const] = Su[const] / S0[const, None]
    li = np.flatnonzero(lin)
    if li.size:
        A3 = np.zeros((li.size, 3, 3))
        A3[:, 0, 0], A3[:, 0, 1], A3[:, 0, 2] = S0[li], Sa[li], Sb[li]
        A3[:, 1, 0], A3[:, 1, 1], A3[:, 1, 2] = Sa[li], Saa[li], Sab[li]
        A3[:, 2, 0], A3[:, 2, 1], A3[:, 2, 2] = Sb[li], Sab[li], Sbb[li]
        rhs = np.stack([Su[li], Sau[li], Sbu[li]], axis=1)
        sol = np.linalg.solve(A3, rhs)
        out[li] = sol[:, 0, :]
    res["n_const"] = int(const.sum())
    res["max_dist"] = float(dmin[ok].max()) if ok.any() else 0.0
    return res


# ====================================================================== 스프링 k — §1.3-6
def shape_spring_k(skel: dict, cap: dict, tie_S: dict, area_S, kappa, kq) -> dict:
    """스프링 k(설계·메시 무관 — D-0.24.8-JG-14): 1차 k̃_{n,r} = κ(ŷ_n)·A_S,n / r_n(형상 자기 랭크 r_n 행에 균등), κ(ŷ) = 골격 보간
    (``sample_tie`` 와 같은 pts·w), 클러스터 합 보존 c_q = K_q / Σ_{n∈q} Σ_r k̃, k = c_q·k̃(snap 1노드 = K_q/r_n). 형상 강성 불필요.
    반환 {k (r,) — 행 순서 = tie_S, c_q (Q,)(잡힌 노드 없는 클러스터 = nan), k_scale_min, k_scale_max}."""
    tn = np.asarray(tie_S["node"], dtype=np.int64).reshape(-1)
    idx = cap["idx"]
    pos = np.searchsorted(idx, tn)
    if tn.size and (np.any(pos >= idx.size) or np.any(idx[pos.clip(0, max(idx.size - 1, 0))] != tn)):
        raise EslError("INPUT_INVALID", "tie_S 행 노드가 잡힌 노드 밖")
    kap = np.asarray(kappa, dtype=np.float64)
    kqv = np.asarray(kq, dtype=np.float64)
    kn = np.einsum("mj,mj->m", cap.get("w_clip", cap["w"]), kap[cap.get("pts_clip", cap["pts"])])   # κ = 클립 보간(양수 유지)
    rn = np.bincount(pos, minlength=idx.size)
    aS = np.asarray(area_S, dtype=np.float64)
    kt = kn[pos] * aS[tn] / rn[pos]
    qr = cap["q"][pos]
    Q = int(kqv.size)
    Sq = np.bincount(qr, weights=kt, minlength=Q)
    with np.errstate(divide="ignore", invalid="ignore"):
        cq = np.where(Sq > 0, kqv / Sq, np.nan)
    k = cq[qr] * kt
    snap = cap["via"][pos] == VIA_SNAP
    if snap.any():
        k[snap] = kqv[qr[snap]] / rn[pos[snap]]
        for q in np.unique(qr[snap]).tolist():
            cq[q] = kqv[q] / Sq[q] if Sq[q] > 0 else np.nan
    if np.any(~np.isfinite(k)) or np.any(k <= 0):
        raise EslError("INPUT_INVALID", "격자 스프링 k ≤ 0(골격 κ 보간)")
    fin = cq[np.isfinite(cq)]
    return {"k": k, "c_q": cq, "k_scale_min": float(fin.min()) if fin.size else None,
            "k_scale_max": float(fin.max()) if fin.size else None}


# ====================================================================== 형상 BC — §1.3-2~7
def shape_bcs(mesh_S, sup321_idx, cap: dict, skel: dict, field: dict, GF: dict, R_pl, Xs_A, *, methods, entries, params: dict,
              kink_deg: float, dup_deg: float, spring: dict | None = None) -> dict:
    """형상 BC(값 = ``jig_bc.build_bc`` 그대로): tie = ``jig_bc.tie_rows(mesh_S, cap.idx, td)``(구속 방향 = 형상 자기 법선), 3-2-1 =
    ``jig_bc.aux_rows``(형상 PCA 판 평면), u_tgt = tie 노드 R_pl·골격 보간 · 3-2-1 노드 R_pl·복셀 표본(그 밖 0), 스프링 k =
    ``shape_spring_k``(spring = {src: (kappa, kq)}). params: tie_dofs·sample_nbr·sample_normal_deg. entries = 묶음 엔트리 id(순서 =
    격자 u 의 k). 반환 {groups{pattern_sha: [(method, k, BC)]}, tie, aux, k_spring{src: shape_spring_k 결과}, diag{sample}}."""
    td = str(params["tie_dofs"])
    XS = np.asarray(mesh_S["x0"], dtype=np.float64)
    R = np.asarray(R_pl, dtype=np.float64).reshape(3, 3)
    tie = jig_bc.tie_rows(mesh_S, cap["idx"], td, kink_deg=float(kink_deg))
    aux = jig_bc.aux_rows(XS, sup321_idx, tie, td, dup_deg=float(dup_deg))
    an = np.unique(np.asarray(aux["node"], dtype=np.int64))
    Xs = np.asarray(Xs_A, dtype=np.float64)
    mA = cap["normal_A"]
    ksp: dict = {}
    groups: dict = {}
    diag = None
    cache: dict = {}
    for m in methods:
        row = jig_bc.METHODS[m]
        fr = str(row["frame"])
        kk = None
        if row["tie_stiff"] != "hard":
            src = row["src"]
            if spring is None or src not in spring:
                raise EslError("INPUT_INVALID", f"스프링 출처 {src} 의 골격 κ·K_q 없음")
            if src not in ksp:
                ksp[src] = shape_spring_k(skel, cap, tie, cap["area_S"], *spring[src])
            kk = ksp[src]["k"]
        for k, _eid in enumerate(entries):
            if (fr, k) not in cache:
                ut = np.zeros((XS.shape[0], 3))
                if an.size:
                    sf = sample_field(field, GF, Xs[an], mA[an], fr, k, nbr=int(params["sample_nbr"]),
                                      normal_deg=float(params["sample_normal_deg"]))
                    ut[an] = sf["u"] @ R.T
                    if diag is None:
                        diag = {kx: sf[kx] for kx in ("n_const", "n_expand", "n_outside", "n_normal_relax", "max_dist")}
                        diag["n_pts"] = int(an.size)
                ut[cap["idx"]] = sample_tie(skel, cap, fr, k) @ R.T     # tie 노드 = 골격 값(3-2-1 과 겹치면 골격 우선)
                cache[(fr, k)] = ut
            BC = jig_bc.build_bc(row, tie, aux, cache[(fr, k)], k=kk)
            groups.setdefault(jig_bc.pattern_sha(BC), []).append((m, k, BC))
    return {"groups": groups, "tie": tie, "aux": aux, "k_spring": ksp,
            "diag": diag or {"n_pts": 0, "n_const": 0, "n_expand": 0, "n_outside": 0, "n_normal_relax": 0, "max_dist": 0.0}}


# ====================================================================== 공용 실행기 — §1.3-8·§2.1
def _shell(mesh_S, solver_cfg: dict | None):
    from esl.mech.shell import ShellModel, solver_check_kwargs
    cfg = solver_cfg or {}
    return ShellModel(mesh_S["x0"], mesh_S["conn"], mesh_S["elem_type"], mesh_S["thickness"], mesh_S["E"], mesh_S["nu"],
                      drill_factor=float(cfg.get("drill_factor", 1e-4)), backend=str(cfg.get("backend", "auto")),
                      **solver_check_kwargs(cfg))


def _umax(u3, mask) -> float:
    uu = u3 if mask is None else u3[np.asarray(mask, bool)]
    return float(np.linalg.norm(uu, axis=1).max()) if uu.size else 0.0


def _tie_diag0(cap: dict, ksp: dict) -> dict:
    cl = cap["clusters"]
    ratios = [c["area_s"] / c["area_a"] for c in cl if not c["miss"] and c["area_a"] > 0]
    ks_min = [v["k_scale_min"] for v in ksp.values() if v.get("k_scale_min") is not None]
    ks_max = [v["k_scale_max"] for v in ksp.values() if v.get("k_scale_max") is not None]
    return {"n_clusters": len(cl), "n_miss": sum(1 for c in cl if c["miss"]),
            "n_snap": sum(1 for c in cl if c["via"] == "snap"), "n_reject_normal": int(cap["n_reject_normal"]),
            "r_cap_mm": float(cap["r_cap"]), "h_S": float(cap["h_S"]), "n_captured": int(cap["idx"].size),
            "area_ratio_min": float(min(ratios)) if ratios else None, "area_ratio_max": float(max(ratios)) if ratios else None,
            "k_scale_min": float(min(ks_min)) if ks_min else None, "k_scale_max": float(max(ks_max)) if ks_max else None}


def force_diag(cap: dict, skel: dict, Xs_A, X_S, R_pl, *, far_mm: float, frac_max: float, marks_max: int | None) -> dict:
    """강제 부여 진단(§3.4·§4.3·§6.3 — 스냅샷에 tie_force 가 있을 때만 map.tie 에 더함): n_force, n_far(옮긴 거리 > far_mm — 표시
    임계), force{dist_min_mm, dist_med_mm, dist_max_mm, shift_max_mm, far_mm, limit_mm(설정 max_dist_mm — null = 없음)}, ref(참고용 =
    (강제 + 못 붙임)/묶음 > frac_max ∨ n_far ≥ 1), marks[{q, via: force|miss, x (Case 체결부 중심 — 형상 전역 좌표), to(force — 붙인
    노드 면적 가중 중심, 형상 전역), dist, n, far}](묶음 번호 순, marks_max 넘으면 dist 큰 순으로 남김 — 못 붙임 = 가장 큼, marks_truncated).
    A 좌표 → 형상 전역: 가장 가까운 형상 노드 n0 기준 x_S = X_S[n0] + (x_A − ŷ[n0])·R_plᵀ(배치가 강체면 정확)."""
    cl = cap["clusters"]
    n_cl = len(cl)
    fcl = [c for c in cl if c["via"] == VIA_NAMES[VIA_FORCE]]
    mcl = [c for c in cl if c["miss"]]
    far = float(far_mm)
    d = sorted(float(c["dist"]) for c in fcl)
    n_far = sum(1 for x in d if x > far)
    fc = cap.get("force") or {}
    fd = {"dist_min_mm": d[0] if d else None, "dist_med_mm": float(np.median(d)) if d else None,
          "dist_max_mm": d[-1] if d else None,
          "shift_max_mm": max(float(c["shift"]) for c in fcl) if fcl else None, "far_mm": far,
          "limit_mm": None if fc.get("max_dist_mm") is None else float(fc["max_dist_mm"])}
    ref = bool((n_cl and (len(fcl) + len(mcl)) / n_cl > float(frac_max)) or n_far >= 1)
    Xs = np.asarray(Xs_A, dtype=np.float64)
    XS = np.asarray(X_S, dtype=np.float64)
    R = np.asarray(R_pl, dtype=np.float64).reshape(3, 3)
    marks = []
    sel = fcl + mcl
    if sel and Xs.shape[0]:
        tS = cKDTree(Xs)
        aS = np.asarray(cap["area_S"], dtype=np.float64)
        Xp, ar = skel["x"], skel["area"]

        def to_S(xa):
            _d, n0 = tS.query(xa, k=1)
            return (XS[int(n0)] + (xa - Xs[int(n0)]) @ R.T).tolist()
        for c in sorted(sel, key=lambda c: c["q"]):
            Pq = np.flatnonzero(skel["q"] == c["q"])
            a_p = ar[Pq]
            xa = (a_p @ Xp[Pq]) / a_p.sum() if a_p.sum() > 0 else Xp[Pq].mean(axis=0)
            mk = {"q": int(c["q"]), "via": c["via"], "x": to_S(xa)}
            if c["via"] == VIA_NAMES[VIA_FORCE]:
                nn = cap["idx"][(cap["q"] == c["q"]) & (cap["via"] == VIA_FORCE)]
                w_ = aS[nn]
                xs = (w_ @ XS[nn]) / w_.sum() if w_.sum() > 0 else XS[nn].mean(axis=0)
                mk.update(to=xs.tolist(), dist=float(c["dist"]), n=int(nn.size), far=bool(float(c["dist"]) > far))
            else:
                mk.update(dist=None, n=0, far=False)
            marks.append(mk)
    out = {"n_force": len(fcl), "n_far": int(n_far), "force": fd, "ref": ref, "marks": marks}
    if marks_max is not None and len(marks) > int(marks_max):
        keep = sorted(marks, key=lambda m: (-(np.inf if m["dist"] is None else m["dist"]), m["q"]))[:int(marks_max)]
        out["marks"] = sorted(keep, key=lambda m: m["q"])
        out["marks_truncated"] = True
    return out


def frame_shift(Xs_A, X_S, nodes, frame_A: dict, frame_dst: dict) -> float:
    """하중 칸(각 쪽 frame 정규화) ↔ BC 표본(배치) 위치 차 max ‖ŷ − to_global(F_A, local(F_dst, y))‖(§1.1)."""
    n = np.asarray(nodes, dtype=np.int64)
    if n.size == 0:
        return 0.0
    loc = nz.local_coords(frame_dst, np.asarray(X_S, dtype=np.float64)[n])
    g = nz.to_global(frame_A, loc[:, 0], loc[:, 1], loc[:, 2])
    return float(np.linalg.norm(np.asarray(Xs_A, dtype=np.float64)[n] - g, axis=1).max())


def run_shape(mesh_S, sup321_idx, loads: dict, skel: dict, field: dict, GF: dict, R_pl, Xs_A, *, methods, entries,
              params: dict, cfg: dict, solver_cfg: dict | None, spring: dict | None = None, omega=None, ev_mask=None,
              keep_u: bool = False, values: list | None = None, marks_max: int | None = None) -> dict:
    """공용 실행기(형상 1개 · 묶음 1개): 잡기 → BC → 패턴 묶음마다 분해 1 → 엔트리마다 응답. loads = {src: [(eid, F (N_S,3))]}
    (entries 순 — 격자 u 의 k), cfg = 격자 설정(tie_capture_rel·tie_snap_rel·tie_normal_deg·tie_miss_frac_max·sample_nbr·
    sample_normal_deg), params = {tie_dofs, kink_deg, dup_deg(+ frame_A·frame_dst·X_S 진단 — 선택, sup_x — A 3-2-1 점)}.
    values = [{"key", "loads": {src: [(eid, F)]}, "field", "GF"}] — 같은 BC 패턴(분해 재사용)에 다른 크기의 하중·3-2-1 값(수렴 진단).
    반환 {methods{src: {status, code, err, rows{eid: {C_mix, E, W_F, W_g, R_sum, umax, umax_ev?, aux_reaction_rel}}, pattern_sha, shared}},
    map{tie, sample, frame_shift_mm, sup_shift_mm}, factor{n, seconds}, u?{src: {eid: (N,3)}}, bc{src: BC(첫 엔트리)},
    rcfs?{src: {eid: {bc, rc, fs}}}(keep_u 일 때 — v0.25.1 씬 C 기여도: 엔트리 BC 값·구속 반력·스프링 힘),
    values?{key: {src: {eid: {C_mix, E, umax, u}}}}}. 실패는 방식 행(status failed·code) — 예외 대신."""
    t0 = time.monotonic()
    p = {**params, "sample_nbr": cfg["sample_nbr"], "sample_normal_deg": cfg["sample_normal_deg"]}
    cap = capture(skel, mesh_S, Xs_A, R_pl, capture_rel=float(cfg["tie_capture_rel"]), snap_rel=float(cfg["tie_snap_rel"]),
                  normal_deg=float(cfg["tie_normal_deg"]), force=cfg.get("tie_force"))
    srcs = [jig_bc.METHODS[m]["src"] for m in methods]
    out: dict[str, Any] = {"methods": {}, "factor": {"n": 0, "seconds": 0.0}, "bc": {}}
    if cap.get("force") is not None:                   # v0.25.2: 강제로 붙인 형상 노드(3D 지지 표식 via force — 강제 설정 스냅샷만)
        out["force_nodes"] = cap["idx"][cap["via"] == VIA_FORCE].copy()
    n_cl = len(cap["clusters"])
    n_miss = sum(1 for c in cap["clusters"] if c["miss"])
    XS = np.asarray(mesh_S["x0"], dtype=np.float64)

    def _tie_diag(cap_, ksp_):                         # v0.25.2: 강제 부여 설정 스냅샷이면 map.tie 에 강제 진단 키(§6.3)
        d_ = _tie_diag0(cap_, ksp_)
        if cap_.get("force") is not None:
            d_.update(force_diag(cap_, skel, Xs_A, XS, R_pl, far_mm=float(cfg["tie_force_far_warn_mm"]),
                                 frac_max=float(cfg["tie_miss_frac_max"]), marks_max=marks_max))
        return d_

    def fail_all(code, err, tie_d, samp):
        for s in srcs:
            out["methods"][s] = {"status": "failed", "code": code, "err": err, "rows": {}, "pattern_sha": None,
                                 "shared": False}
        out["map"] = {"tie": tie_d, "sample": samp, "frame_shift_mm": None, "sup_shift_mm": None}
        out["seconds"] = round(time.monotonic() - t0, 3)
        return out
    empty_s = {"n_pts": 0, "n_const": 0, "n_expand": 0, "n_outside": 0, "n_normal_relax": 0, "max_dist": 0.0}
    if cap["idx"].size == 0 or (n_cl and n_miss / n_cl > float(cfg["tie_miss_frac_max"])):
        return fail_all("JIG_GRID_TIE_MISS", f"{n_miss}/{n_cl}", _tie_diag(cap, {}), empty_s)
    try:
        bcs = shape_bcs(mesh_S, sup321_idx, cap, skel, field, GF, R_pl, Xs_A, methods=methods, entries=entries, params=p,
                        kink_deg=float(params["kink_deg"]), dup_deg=float(params["dup_deg"]), spring=spring)
    except EslError as exc:
        code = exc.code if exc.code == "JIG_SUPPORT_DEGENERATE" else "JIG_DESIGN_FAILED"
        return fail_all(code, f"{exc.code}: {exc.message}"[:300], _tie_diag(cap, {}), empty_s)
    tie_d = _tie_diag(cap, bcs["k_spring"])
    an = np.unique(np.asarray(bcs["aux"]["node"], dtype=np.int64))
    fs = None
    if params.get("frame_A") is not None and params.get("frame_dst") is not None:
        fs = frame_shift(Xs_A, XS, np.r_[cap["idx"], an], params["frame_A"], params["frame_dst"])
    ss = None
    if params.get("sup_x") is not None and bcs["aux"].get("nodes"):
        sx = np.asarray(params["sup_x"], dtype=np.float64).reshape(-1, 3)
        nn = np.asarray(bcs["aux"]["nodes"], dtype=np.int64)
        if sx.shape[0] == nn.size:
            ss = float(np.linalg.norm(np.asarray(Xs_A)[nn] - sx, axis=1).max())
    out["map"] = {"tie": tie_d, "sample": bcs["diag"], "frame_shift_mm": fs, "sup_shift_mm": ss}
    sm = _shell(mesh_S, solver_cfg)
    comps = jig_bc.components(mesh_S)
    by_src_loads = {s: dict(loads.get(s) or []) for s in srcs}
    if keep_u:
        out["u"] = {}
    if values:
        out["values"] = {v["key"]: {} for v in values}
    rows_of: dict = {s: {} for s in srcs}
    meta: dict = {}
    order = sorted(bcs["groups"].items(), key=lambda kv: min(methods.index(m) for m, _k, _b in kv[1]))
    for sha, items in order:
        BC0 = items[0][2]
        msrc = sorted({jig_bc.METHODS[m]["src"] for m, _k, _b in items}, key=srcs.index)
        try:
            rf = jig_bc.rigid_free(XS, comps, BC0)
            if rf["rigid_free"] > 0:
                raise EslError("JIG_SUPPORT_DEGENERATE", f"rigid_free {rf['rigid_free']}")
            t1 = time.monotonic()
            h = jig_bc.factorize(sm, BC0)
            out["factor"]["n"] += 1
            out["factor"]["seconds"] += time.monotonic() - t1
            for m, k, BC in items:
                src = jig_bc.METHODS[m]["src"]
                eid = entries[k]
                F = by_src_loads[src].get(eid)
                if src not in out["bc"]:
                    out["bc"][src] = BC
                if F is None:
                    continue
                r = jig_bc.respond(h, F, BC)
                u3 = np.asarray(r["u"], dtype=np.float64)[:, :3]
                en = r["energy"]
                row = {"C_mix": float(en["C_mix"]), "E": float(en["E"]), "W_F": float(en["W_F"]), "W_g": float(en["W_g"]),
                       "R_sum": float(en["R_sum"]), "umax": _umax(u3, omega),
                       "aux_reaction_rel": float(jig_bc.aux_reaction_rel(F, BC, r["rc"]))}
                if ev_mask is not None:
                    row["umax_ev"] = _umax(u3, ev_mask)
                rows_of[src][eid] = row
                if keep_u:
                    out["u"].setdefault(src, {})[eid] = u3
                    # v0.25.1 씬 3D C 기여도(esl_view3d_scene_legend.md §2.6): 그 엔트리 BC(값·바닥)·반력·스프링 힘(계산 불변 — 보관만)
                    out.setdefault("rcfs", {}).setdefault(src, {})[eid] = {"bc": BC, "rc": np.asarray(r["rc"], dtype=np.float64),
                                                                          "fs": np.asarray(r["fs"], dtype=np.float64)}
                for v in values or []:
                    Fv = dict((v["loads"].get(src) or [])).get(eid)
                    if Fv is None:
                        continue
                    BCv = _revalue(BC, m, k, bcs, cap, skel, v["field"], v["GF"], R_pl, Xs_A, p)
                    rv = jig_bc.respond(h, Fv, BCv)
                    uv = np.asarray(rv["u"], dtype=np.float64)[:, :3]
                    out["values"][v["key"]].setdefault(src, {})[eid] = {
                        "C_mix": float(rv["energy"]["C_mix"]), "E": float(rv["energy"]["E"]), "umax": _umax(uv, omega),
                        "u": uv}
            del h
            for s in msrc:
                meta[s] = {"status": "ok", "code": None, "err": None, "pattern_sha": sha,
                           "shared": len({jig_bc.METHODS[m]["src"] for m, _k, _b in items}) > 1}
        except EslError as exc:
            code = exc.code if exc.code in ("JIG_SUPPORT_DEGENERATE",) else "JIG_DESIGN_FAILED"
            for s in msrc:
                meta[s] = {"status": "failed", "code": code, "err": f"{exc.code}: {exc.message}"[:300], "pattern_sha": sha,
                           "shared": False}
                rows_of[s] = {}
    for s in srcs:
        mt = meta.get(s) or {"status": "failed", "code": "JIG_DESIGN_FAILED", "err": "BC 없음", "pattern_sha": None,
                             "shared": False}
        out["methods"][s] = {**mt, "rows": rows_of[s] if mt["status"] == "ok" else {}}
    out["factor"]["seconds"] = round(out["factor"]["seconds"], 3)
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


def _revalue(BC: dict, m: str, k: int, bcs: dict, cap: dict, skel: dict, field: dict, GF: dict, R_pl, Xs_A, p: dict) -> dict:
    """같은 패턴 BC 의 값만 다른 격자로(3-2-1 행 = 새 복셀 표본, tie 행 = 골격 — 격자 크기 무관). 분해 재사용(수렴 진단)."""
    row = jig_bc.METHODS[m]
    fr = str(row["frame"])
    aux = bcs["aux"]
    an = np.unique(np.asarray(aux["node"], dtype=np.int64))
    R = np.asarray(R_pl, dtype=np.float64).reshape(3, 3)
    ut = np.zeros((np.asarray(Xs_A).shape[0], 3))
    if an.size:
        sf = sample_field(field, GF, np.asarray(Xs_A)[an], cap["normal_A"][an], fr, k, nbr=int(p["sample_nbr"]),
                          normal_deg=float(p["sample_normal_deg"]))
        ut[an] = sf["u"] @ R.T
    ut[cap["idx"]] = sample_tie(skel, cap, fr, k) @ R.T
    kk = None if row["tie_stiff"] == "hard" else BC["sp_k"]
    out = jig_bc.build_bc(row, bcs["tie"], aux, ut, k=kk)
    if jig_bc.pattern_sha(out) != jig_bc.pattern_sha(BC):
        raise EslError("INPUT_INVALID", "수렴 진단 BC 패턴이 다름")
    return out


def recon(X_S, u_S, ut_S, omega=None) -> dict:
    """기준 재현(d000): u_S(파트 Kabsch 제거)와 ũ_rel(형상 노드 복셀 표본)의 MAC·umax_err — ``bforce.recon_report`` 그대로."""
    from esl.mech import kabsch
    u = kabsch.remove_rigid(np.asarray(X_S, dtype=np.float64), np.asarray(u_S, dtype=np.float64)[:, :3])[0]
    ut = np.asarray(ut_S, dtype=np.float64)
    if omega is not None:
        mk = np.asarray(omega, bool)
        u, ut = u[mk], ut[mk]
    r = bforce.recon_report(ut, u, None, np.zeros((1, 3)))
    return {"mac": r["mac"], "umax_err": r["umax_err"]}


def mac(u, v) -> float | None:
    """MAC(같은 노드) — ``bforce.mac``."""
    return bforce.mac(np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64))


def mesh_stats(mesh) -> dict:
    """형상 메시 통계(v0.24.8 fix JG-23 — 기준 d000 과 메시 방식 비교): h = 요소 변(중복 제거) 길이 중앙값(mm, 원 좌표),
    tri_frac = 삼각형 요소 비율(요소 수 기준). 요소 0 = {h: 0, tri_frac: 0}."""
    et = np.asarray(mesh["elem_type"]).astype(np.int64)
    E = _elem_edges(mesh)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    h = float(np.median(np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1))) if E.size else 0.0
    return {"h": h, "tri_frac": float(np.count_nonzero(et != 4) / et.size) if et.size else 0.0}


def mesh_mismatch(ref: dict, stats: dict, *, h_ratio_warn: float, tri_frac_warn: float) -> bool:
    """형상 메시가 기준과 다른 방식인가: h 비(형상/기준)가 [1/r, r] 밖이거나 삼각 비율 차 > tri_frac_warn."""
    h0, h1 = float(ref["h"]), float(stats["h"])
    if h0 <= 0.0 or h1 <= 0.0:
        return False
    r = float(h_ratio_warn)
    return h1 * r < h0 or h1 > h0 * r or abs(float(stats["tri_frac"]) - float(ref["tri_frac"])) > float(tri_frac_warn)


def hash_view(grid_cfg_raw: dict | None) -> dict:
    """이어하기 해시 보기: 스냅샷 원본 rank.jig_grid 사본에서 HASH_EXCLUDE 키를 뺌(설정 병합 전 — D-0.24.5-VT-16)."""
    return {k: grid_cfg_raw[k] for k in sorted(grid_cfg_raw or {}) if k not in HASH_EXCLUDE and k not in HASH_FIXED}
