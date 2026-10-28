"""S1 모델 동일성 (계약 esl_opt_run.md OR-D-4, §7.3, 결정 0.5.5).

- ``topo_sha256(mesh)``: 정렬 node_id + 요소 ID 순 ``canon_conn``(노드 ID, 회전·반전·삼각형 표현 동치) 의 sha256.
  좌표는 넣지 않는다 → 버전 간 좌표 미세차에 둔감. 목록·s1-check·금지 영역 세트 키.
- ``same_model(base, other, coord_tol_rel)``: 0.5.5 전체 규칙 — 노드 ID 집합 같음 → 요소(ID) 집합·연결 같음 →
  좌표 Kabsch 강체 정합 잔차 ≤ coord_tol_rel × bbox 대각선. reason = NODE_IDS | CONNECTIVITY | COORDS.
- ``check_entries(base_mesh, entries, coord_tol_rel)``: 화면/작업용 행 목록, ``assert_same`` 은 MODEL_MISMATCH.
"""
from __future__ import annotations

import hashlib

import numpy as np

from esl.errors import EslError
from esl.io.results_csv import canon_conn


def conn_ids(mesh: dict) -> np.ndarray:
    """(E,4) 노드 ID (없음 = 0)."""
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    ids = np.where(c >= 0, nid[np.maximum(c, 0)], 0)
    ids[et == 3, 3] = 0
    return ids


def topo_sha256(mesh: dict) -> str:
    nid = np.sort(np.asarray(mesh["node_id"], dtype=np.int64))
    eid = np.asarray(mesh["elem_id"], dtype=np.int64)
    order = np.argsort(eid, kind="stable")
    cc = canon_conn(conn_ids(mesh))[order]
    h = hashlib.sha256()
    h.update(b"esl/topo/1\n")
    for a in (nid, eid[order], cc):
        a = np.ascontiguousarray(a.astype("<i8"))
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def _kabsch_residual(xa: np.ndarray, xb: np.ndarray) -> float:
    ca, cb = xa.mean(axis=0), xb.mean(axis=0)
    A, B = xa - ca, xb - cb
    U, _, Vt = np.linalg.svd(A.T @ B)
    s = np.sign(np.linalg.det(U @ Vt)) or 1.0
    R = (U @ np.diag([1.0, 1.0, s]) @ Vt).T
    return float(np.max(np.linalg.norm(A @ R.T - B, axis=1))) if A.size else 0.0


def same_model(base: dict, other: dict, coord_tol_rel: float) -> dict:
    """반환 {same, reason, detail, topo_equal, coord_residual_rel}."""
    na = np.asarray(base["node_id"], dtype=np.int64)
    nb = np.asarray(other["node_id"], dtype=np.int64)
    out = {"same": False, "reason": None, "detail": "", "topo_equal": False, "coord_residual_rel": None}
    sa, sb = np.sort(na), np.sort(nb)
    if sa.size != sb.size or not np.array_equal(sa, sb):
        only_a = np.setdiff1d(sa, sb)[:5].tolist()
        only_b = np.setdiff1d(sb, sa)[:5].tolist()
        out.update(reason="NODE_IDS", detail=f"노드 ID 집합 다름(기준 {sa.size}개 / 이 항목 {sb.size}개, 기준만 {only_a}, "
                                              f"이 항목만 {only_b})")
        return out
    ea = np.asarray(base["elem_id"], dtype=np.int64)
    eb = np.asarray(other["elem_id"], dtype=np.int64)
    oa, ob = np.argsort(ea, kind="stable"), np.argsort(eb, kind="stable")
    if ea.size != eb.size or not np.array_equal(ea[oa], eb[ob]):
        out.update(reason="CONNECTIVITY", detail=f"요소 ID 집합 다름(기준 {ea.size}개 / 이 항목 {eb.size}개)")
        return out
    ca, cb = canon_conn(conn_ids(base))[oa], canon_conn(conn_ids(other))[ob]
    bad = np.any(ca != cb, axis=1)
    if bad.any():
        out.update(reason="CONNECTIVITY", detail=f"요소 연결 다름: {int(bad.sum())}/{ea.size}개, 예 요소 "
                                                 f"{ea[oa][bad][:5].tolist()}")
        return out
    out["topo_equal"] = True
    xa = np.asarray(base["x0"], dtype=np.float64)[np.argsort(na, kind="stable")]
    xb = np.asarray(other["x0"], dtype=np.float64)[np.argsort(nb, kind="stable")]
    diag = float(np.linalg.norm(xa.max(axis=0) - xa.min(axis=0))) or 1.0
    res = _kabsch_residual(xb, xa) / diag
    out["coord_residual_rel"] = res
    if res > float(coord_tol_rel):
        out.update(reason="COORDS", detail=f"좌표 강체 정합 후 잔차 {res:.3g} > {coord_tol_rel} (bbox 대각선 비)")
        return out
    out["same"] = True
    return out


def check_entries(base_mesh: dict, others: list[tuple[str, dict]], coord_tol_rel: float) -> list[dict]:
    """[(entry_id, mesh)] → [{entry_id, same_model, reason, detail}]."""
    rows = []
    for eid, m in others:
        r = same_model(base_mesh, m, coord_tol_rel)
        rows.append({"entry_id": eid, "same_model": r["same"], "reason": r["reason"], "detail": r["detail"]})
    return rows


def assert_same(rows: list[dict]) -> None:
    bad = [r for r in rows if not r["same_model"]]
    if bad:
        lst = "; ".join(f"{r['entry_id']}: {r['reason']}" for r in bad[:10])
        raise EslError("MODEL_MISMATCH", f"기준 모델과 다른 ESL {len(bad)}개(기존 형상 최적화는 같은 모델만 — 다른 모델은 "
                                         f"빼거나 템플릿 최적화 사용): {lst}")
