"""컴플라이언스 장 — 노드 C 기여도·umax 위치·보존 격자 사상·차이 (계약 docs/contracts/esl_view3d_scene_legend.md §3,
결정 D-0.25.1-VL-4·5·6).

모드 무관 독립 순수 모듈(AGENTS.md D-0.20.0-CODE): import = numpy · ``esl.mech.grid_map``(``grid_frame``·``vox_key`` 만) ·
``esl.errors``. **esl.doe·esl.view3d 금지, 파일 IO 없음, 설정 해석 없음**(값은 인수), 시나리오·출처 이름 없음. 결정적(정렬 키·
동률 = 작은 인덱스, 고정 합 순서 — bincount).

- ``nodal_c``: c_n = F_n·u_n − Σ_{지정 변위 행 c ∈ n} v_c r_c − Σ_{스프링 행 s ∈ n} g_s f_s. Σc = Fᵀu(값 0 지지) 또는
  ``jig_bc.mixed_compliance`` 의 C_mix(지정 변위·스프링) — 행 → 노드 대응은 ``jig_bc._dot_rows`` 와 같은 행 순서(bc_node·sp_node).
- ``umax_pin``: 평가와 같은 배열·같은 함수(``evaluate.umax_in`` 규칙 — 마스크가 비면 전 노드)로 최대 ‖u‖ 노드(동률 = 작은 인덱스).
- ``conserve_map``: 공통 좌표의 두 메시를 같은 복셀 키(``grid_map.vox_key``)로 묶어 기준 값을 셀에 더하고 셀 안 대상 노드에 똑같이
  나눈다(합 보존). 대상 노드가 없는 셀 = 가장 가까운 대상 노드 1개(``moved_rel`` 기록). ``sample_field``(보간)는 합을 보존하지 않아
  쓰지 않는다.
- ``diff``: dc = c_d − ĉ_0(같은 노드 배열 위).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError
from esl.mech.grid_map import grid_frame, vox_key

NN_CELLS = 2_000_000                  # 최근접 탐색 거리 행렬 원소 상한(빈 셀 묶음 × 대상 노드 — 16 MB)

__all__ = ["nodal_c", "umax_pin", "conserve_map", "diff", "grid_frame"]


def _rows_to_nodes(n_nodes: int, nodes, w) -> np.ndarray:
    """행 값 w 를 행의 노드에 더함(bincount — 행 순서 고정 합)."""
    nd = np.asarray(nodes, dtype=np.int64).reshape(-1)
    ww = np.asarray(w, dtype=np.float64).reshape(-1)
    if nd.size == 0:
        return np.zeros(n_nodes)
    if nd.size != ww.size:
        raise EslError("INPUT_INVALID", f"지지 행 {nd.size} ≠ 값 {ww.size}")
    if nd.min() < 0 or nd.max() >= n_nodes:
        raise EslError("INPUT_INVALID", "지지 행 노드 인덱스가 메시 밖")
    return np.bincount(nd, weights=ww, minlength=n_nodes)


def nodal_c(F, u3, bc=None, rc=None, fs=None) -> dict:
    """노드 C 기여도(§3.1): {c (N,), sum Σc, W_F Fᵀu, W_v Σ v r, W_g Σ g f}.

    F (N,3) 하중, u3 (N,≥3) 풀이 변위(앞 3성분), bc = BC dict(``bc_node``·``bc_val``·``sp_node``·``sp_g`` — ``jig_bc`` 형식) 또는 None
    (값 0 지지 = fu), rc = 구속 행 반력(``jig_bc.solve`` 순서), fs = 스프링 힘. bc 가 있고 rc/fs 가 없으면 그 항 0 이 아니라 오류."""
    Fa = np.asarray(F, dtype=np.float64).reshape(-1, 3)
    ua = np.asarray(u3, dtype=np.float64)
    if ua.ndim != 2 or ua.shape[0] != Fa.shape[0] or ua.shape[1] < 3:
        raise EslError("INPUT_INVALID", "F·u 크기가 서로 다릅니다")
    ua = ua[:, :3]
    n = Fa.shape[0]
    c = np.einsum("ij,ij->i", Fa, ua)
    WF = float(np.sum(Fa * ua))
    Wv = Wg = 0.0
    if bc is not None:
        v = np.asarray(bc.get("bc_val", np.zeros(0)), dtype=np.float64).reshape(-1)
        if v.size:
            if rc is None:
                raise EslError("INPUT_INVALID", "지정 변위 행 반력 rc 가 필요합니다")
            r = np.asarray(rc, dtype=np.float64).reshape(-1)
            if r.size != v.size:
                raise EslError("INPUT_INVALID", f"반력 {r.size} ≠ 구속 행 {v.size}")
            c = c - _rows_to_nodes(n, bc["bc_node"], v * r)
            Wv = float(v @ r)
        g = np.asarray(bc.get("sp_g", np.zeros(0)), dtype=np.float64).reshape(-1)
        if g.size:
            if fs is None:
                raise EslError("INPUT_INVALID", "스프링 힘 fs 가 필요합니다")
            f = np.asarray(fs, dtype=np.float64).reshape(-1)
            if f.size != g.size:
                raise EslError("INPUT_INVALID", f"스프링 힘 {f.size} ≠ 스프링 행 {g.size}")
            c = c - _rows_to_nodes(n, bc["sp_node"], g * f)
            Wg = float(g @ f)
    return {"c": c, "sum": float(np.sum(c)), "W_F": WF, "W_v": Wv, "W_g": Wg}


def umax_pin(u3, mask=None) -> dict:
    """umax 위치(§3.3): {index, value} — value = max_{mask} ‖u‖(``evaluate.umax_in`` 과 같은 계산 — 같은 배열·같은 마스크면 같은 값),
    mask None 또는 빈 마스크 = 전 노드, 동률 = 가장 작은 인덱스(argmax 첫 최대). 노드가 없으면 {index None, value 0.0}."""
    ua = np.asarray(u3, dtype=np.float64)
    ut = ua[:, :3] if ua.ndim == 2 else ua.reshape(-1, 3)
    if mask is None:
        idx = None
        uu = ut
    else:
        mk = np.asarray(mask, bool).reshape(-1)
        if mk.size != ut.shape[0]:
            raise EslError("INPUT_INVALID", "umax 마스크 크기가 노드 수와 다릅니다")
        idx = np.flatnonzero(mk) if mk.any() else None
        uu = ut[mk] if mk.any() else ut
    if not uu.size:
        return {"index": None, "value": 0.0}
    nrm = np.linalg.norm(uu, axis=1)
    k = int(np.argmax(nrm))
    return {"index": int(k if idx is None else idx[k]), "value": float(nrm.max())}


def _cell_ids(GF: dict, X_src, X_dst) -> tuple[np.ndarray, np.ndarray, int]:
    """두 점 집합의 같은 셀 번호(0..n_cells−1, 키 (i,j,k) 사전순)."""
    ks = vox_key(GF, X_src)
    kd = vox_key(GF, X_dst)
    allk = np.concatenate([ks, kd], axis=0)
    if allk.shape[0] == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), 0
    kmin = allk[:, 2].min()
    span = int(allk[:, 2].max() - kmin) + 1
    lin = (allk[:, 0] * int(GF["ny"]) + allk[:, 1]) * span + (allk[:, 2] - kmin)
    uq, inv = np.unique(lin, return_inverse=True)
    inv = inv.reshape(-1)
    return inv[:ks.shape[0]], inv[ks.shape[0]:], int(uq.size)


def _nearest(P, Q) -> np.ndarray:
    """P (m,3) 각 점의 Q (n,3) 최근접 인덱스(유클리드 — 차이를 직접 제곱, 동률 = 작은 인덱스 — argmin 첫 최소). 거리 행렬은
    NN_CELLS 원소 이하 묶음(메모리 상한 — 대상 노드 수와 무관)."""
    out = np.empty(P.shape[0], np.int64)
    Qt = np.ascontiguousarray(Q.T)
    step = max(1, NN_CELLS // max(1, Q.shape[0]))
    for s in range(0, P.shape[0], step):
        p = P[s:s + step]
        d2 = (Qt[0][None, :] - p[:, 0:1]) ** 2
        d2 += (Qt[1][None, :] - p[:, 1:2]) ** 2
        d2 += (Qt[2][None, :] - p[:, 2:3]) ** 2
        out[s:s + step] = np.argmin(d2, axis=1)
    return out


def conserve_map(c_src, X_src, X_dst, GF: dict) -> tuple[np.ndarray, dict]:
    """보존 격자 사상(§3.2): 기준 값 c_src(노드 X_src)를 대상 노드 X_dst 로. 둘 다 같은 공통 좌표(GF 의 frame — ``grid_frame``).
    셀 합 = Σ 기준 노드 값, 대상 노드 = 셀 합 / 그 셀의 대상 노드 수, 대상 노드 없는 셀 = 셀 기준 노드 중심에서 가장 가까운 대상 노드 1개.
    반환 (c_dst (N_dst,), info{cell_mm, n_cells, n_empty, moved_rel, sum_src, sum_dst})."""
    cs = np.asarray(c_src, dtype=np.float64).reshape(-1)
    Xs = np.asarray(X_src, dtype=np.float64).reshape(-1, 3)
    Xd = np.asarray(X_dst, dtype=np.float64).reshape(-1, 3)
    if cs.size != Xs.shape[0]:
        raise EslError("INPUT_INVALID", "기준 값·좌표 크기가 다릅니다")
    if Xd.shape[0] == 0:
        raise EslError("INPUT_INVALID", "대상 메시 노드가 없습니다")
    cid_s, cid_d, n_cells = _cell_ids(GF, Xs, Xd)
    csum = np.bincount(cid_s, weights=cs, minlength=n_cells)
    cnt_d = np.bincount(cid_d, minlength=n_cells)
    out = np.zeros(Xd.shape[0])
    has = cnt_d > 0
    share = np.zeros(n_cells)
    share[has] = csum[has] / cnt_d[has]
    out += share[cid_d]
    src_cells = np.unique(cid_s)
    empty = src_cells[~has[src_cells]]
    moved = 0.0
    if empty.size:
        cnt_s = np.bincount(cid_s, minlength=n_cells).astype(np.float64)
        cen = np.zeros((n_cells, 3))
        for d in range(3):
            cen[:, d] = np.bincount(cid_s, weights=Xs[:, d], minlength=n_cells)
        P = cen[empty] / cnt_s[empty][:, None]
        nn = _nearest(P, Xd)
        out += np.bincount(nn, weights=csum[empty], minlength=Xd.shape[0])
        moved = float(np.abs(csum[empty]).sum())
    tot = float(np.abs(cs).sum())
    info = {"cell_mm": float(GF["cell_mm"]), "n_cells": int(n_cells), "n_empty": int(empty.size),
            "moved_rel": (moved / tot) if tot > 0 else 0.0, "sum_src": float(cs.sum()), "sum_dst": float(out.sum())}
    return out, info


def diff(c_d, c_0_on_d) -> np.ndarray:
    """차이(§3.2): dc = c_d − ĉ_0(같은 노드 배열 — 항등이면 ĉ_0 = c_0 그대로)."""
    a = np.asarray(c_d, dtype=np.float64).reshape(-1)
    b = np.asarray(c_0_on_d, dtype=np.float64).reshape(-1)
    if a.size != b.size:
        raise EslError("INPUT_INVALID", "차이: 안·기준 값 크기가 다릅니다")
    return a - b

