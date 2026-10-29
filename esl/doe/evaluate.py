"""안 해석 (계약 esl_bead_doe.md BD-D-5·16, §4 result.json·design.npz·done.json, V-BD-7).

안마다 ``ShellModel(x_d, conn, type, t, E, ν).factorize(spc)`` 1회 → 선택 ESL 전부 ``solve`` →
C_{d,i} = Σ F_i·u[:, :3], umax_{d,i} = max‖u[:, :3]‖, εmax_{d,i} = max ``eps_eq_max_layer(strains(u))``.
반력 ‖ΣR‖ / Σ‖F‖ > ``solve.reaction_warn`` 이면 안 경고 ``REACTION_RESIDUAL``(모핑 후 평형이 조금 깨짐).
지지 rank < 6 → ``SUPPORT_DEGENERATE``(호출자가 안 ``FAILED_SOLVE``).
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np

from esl.errors import EslError
from esl.library import _util as U

DESIGN_NPZ = "design.npz"
RESULT_JSON = "result.json"
DONE_JSON = "done.json"


def spc_of(mesh: dict, supports) -> list[tuple[int, str]]:
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    out = []
    for n, d in supports:
        if int(n) not in pos:
            raise EslError("NODE_NOT_IN_PART", f"3-2-1 노드 {n} 가 안 메시에 없음")
        out.append((pos[int(n)], str(d)))
    return out


def evaluate(mesh: dict, supports, loads, solver_cfg: dict, *, reaction_warn: float, keep_u=()) -> dict:
    """mesh(x0 = 안 좌표) + 지지 + [(entry_id, F)] → {per_esl[{entry_id, C, umax, epsmax}], warnings, stats, u{eid: u3}}.

    keep_u = 변위 (N,3) 를 돌려줄 entry_id 목록(view3d 용)."""
    from esl.mech.shell import ShellModel
    from esl.mech.strain import eps_eq_max_layer
    from esl.mech import supports as msup
    from esl.opt.target import support_check
    sr = support_check(mesh, supports)
    if sr["rank"] < 6 or sr["sigma_ratio"] < msup.DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 지지가 강체 6모드를 구속하지 못함: {list(supports)}")
    t0 = time.monotonic()
    sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                    drill_factor=float(solver_cfg["drill_factor"]), backend=str(solver_cfg["backend"]))
    h = sm.factorize(spc_of(mesh, supports))
    per, warns, keep = [], [], {}
    want = set(keep_u or ())
    for eid, F in loads:
        F = np.asarray(F, dtype=np.float64)
        u, R = h.solve(F)
        ut = u[:, :3]
        C = float(np.sum(F * ut))
        umax = float(np.max(np.linalg.norm(ut, axis=1))) if ut.size else 0.0
        eps = eps_eq_max_layer(sm.strains(u))
        epsmax = float(np.max(eps)) if eps.size else 0.0
        sabs = float(np.linalg.norm(F, axis=1).sum())
        rr = float(np.linalg.norm(R.sum(axis=0)) / sabs) if sabs > 0 else 0.0
        if rr > float(reaction_warn):
            warns.append({"code": "REACTION_RESIDUAL", "entry_id": eid, "ratio": rr})
        per.append({"entry_id": eid, "C": C, "umax": umax, "epsmax": epsmax, "reaction_rel": rr})
        if eid in want:
            keep[eid] = ut.copy()
    return {"per_esl": per, "warnings": warns, "u": keep,
            "stats": {"n_factorizations": int(sm.stats.get("n_factorizations", 0)), "n_solves": h.n_solves,
                      "backend": sm.stats.get("backend"), "seconds": round(time.monotonic() - t0, 3)}}


def parallel_limit(n_nodes: int, parallel: int, memory_margin: float, backend: str = "auto",
                   available: int | None = None) -> dict:
    """BD-D-15: estimate_direct_bytes × p ≤ available_memory × memory_margin 이 되게 p 자동 축소(최소 1)."""
    from esl.mech.shell import available_memory_bytes, estimate_direct_bytes, resolve_backend
    try:
        b = resolve_backend(backend)
    except EslError:
        b = "superlu"
    n = 6 * int(n_nodes)
    est = float(estimate_direct_bytes(n, 36 * 9 * int(n_nodes), b))
    avail = available if available is not None else available_memory_bytes()
    p = max(1, int(parallel))
    if avail:
        cap = int(float(avail) * float(memory_margin) // max(est, 1.0))
        p = max(1, min(p, cap))
    return {"parallel": p, "requested": int(parallel), "estimate_bytes": est, "available_bytes": avail,
            "reduced": p < int(parallel)}


def worst(per_esl: list[dict]) -> dict:
    """최악 ESL(C 최대, 동률 = 목록 앞) 행."""
    if not per_esl:
        raise EslError("INPUT_INVALID", "ESL 해석 결과가 없음")
    best = per_esl[0]
    for r in per_esl[1:]:
        if r["C"] > best["C"]:
            best = r
    return best


# ---------------------------------------------------------------- 파일
def save_design(d: str, node_id, x, mesh: dict | None = None, writer: U.Writer | None = None) -> str:
    """design.npz = node_id, x (N,3) float64 (③ 은 + conn, type, pid). allow_pickle=False 규칙."""
    from esl.doe.mesh_gmsh import save_npz_det
    g = writer.guard if writer is not None else (lambda p: p)
    arr = {"node_id": np.asarray(node_id, dtype=np.int64), "x": np.asarray(x, dtype=np.float64)}
    if mesh is not None:
        arr.update(conn=np.asarray(mesh["conn"], dtype=np.int64), type=np.asarray(mesh["elem_type"]).astype(np.int8),
                   pid=np.asarray(mesh["elem_pid"], dtype=np.int64))
    p = os.path.join(d, DESIGN_NPZ)
    save_npz_det(g(p), arr)
    return p


def load_design(d: str) -> dict:
    return U.load_npz(os.path.join(d, DESIGN_NPZ))


def result_doc(did: str, status: str, values: dict, *, paicad: dict | None = None, mesh: dict | None = None,
               solve: dict | None = None, per_esl: list | None = None, warnings: list | None = None,
               code: str | None = None, message: str | None = None) -> dict:
    """§4 result.json {id, status, values, paicad{code, seconds}, mesh{…}, solve{seconds, backend}, per_esl, score,
    worst_entry_id, warnings[]} (score 는 BD_POST 가 채움 — 여기서는 None)."""
    w = worst(per_esl) if per_esl else None
    return U.jsonable({"id": did, "status": status, "values": dict(values), "code": code, "message": message,
                       "paicad": paicad, "mesh": mesh, "solve": solve, "per_esl": per_esl or [],
                       "C_max": None if w is None else w["C"], "worst_entry_id": None if w is None else w["entry_id"],
                       "score": None, "warnings": list(warnings or [])})


def config_hash(cfg: dict) -> str:
    s = json.dumps(U.jsonable(cfg), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def input_sha256(values: dict, base_mesh_sha: str, loads_sha: str | None, cfg_hash: str,
                 paicad_version: str | None) -> str:
    """BD-D-16 input_sha256 = (values, 기준 메시 sha, 하중 sha, 설정 해시, paicad 버전)."""
    doc = {"values": {k: float(v) for k, v in sorted(values.items())}, "base_mesh": base_mesh_sha,
           "loads": loads_sha, "cfg": cfg_hash, "paicad": paicad_version}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


RETRY_STATES = ("FAILED_MORPH", "FAILED_MESH", "FAILED_SOLVE", "CANCELED", "RUNNING", "READY")


def reusable(d: str, sha: str) -> dict | None:
    """done.json 이 같은 input_sha256 이고 상태가 재시도 대상(FAILED_*·CANCELED)이 아니면 그 내용(재사용), 아니면 None."""
    p = os.path.join(d, DONE_JSON)
    if not os.path.isfile(p):
        return None
    try:
        doc = U.read_json(p)
    except (OSError, ValueError):
        return None
    if doc.get("input_sha256") != sha or doc.get("status") in RETRY_STATES:
        return None
    if doc.get("status") == "OK" and not os.path.isfile(os.path.join(d, RESULT_JSON)):
        return None
    return doc


def write_done(d: str, sha: str, status: str, writer: U.Writer | None = None) -> None:
    g = writer.guard if writer is not None else (lambda p: p)
    U.write_json(g(os.path.join(d, DONE_JSON)), {"input_sha256": sha, "status": status, "at": U.utcnow()})
