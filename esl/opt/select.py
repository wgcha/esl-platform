"""초기 컴플라이언스 + 하중 선정 전략 A/B/C (계약 esl_opt_run.md OR-D-14·15, §7.4). 모든 전략 결정적.

초기 컴플라이언스(``initial_compliance``): 대상 초기 형상(비드 없음) 자체 쉘 솔버, 3-2-1, **분해 1회·다중 RHS**.
후보마다 u_k, C_k = Σ F_k·u_k[:, :3], umax_k = max‖u_k[:, :3]‖. 전략 A·C 는 병진 u_k(float32)를 (K, 3N) 배열 또는
memmap(``u_store``)에 쌓아 MAC 를 계산한다(메모리에는 하중 1개만).

선정(``select``):
0. 정렬 = C 내림차순, 동률 entry_id 사전순. C ≤ 0 은 제외(``not_selected`` + 경고), 모두 제외 → NO_LOAD_CASES.
   mac_ij = (u_i·u_j)² / ((u_i·u_i)(u_j·u_j)) — 부호 무관. Gram 은 정렬 순서로 계산(입력 순서와 무관한 바이트).
   군집 = d = 1 − mac, scipy linkage(method = loads.linkage) + fcluster(maxclust), 입력 = 정렬 순서,
   대표 = 군집 내 C 최대(정렬상 첫 원소), 군집 번호 = 대표 C 내림차순.
A 전부(기본): 정렬 순서로 보며 남긴 것 중 mac ≥ mac_merge 가 있으면 merged(대상 = mac 최대, 동률은 먼저 남긴 것,
   sign = sgn(u_i·u_target)), 없으면 남김. 남은 수 ≤ max_cases → included, 초과 → 남은 것만 max_cases 군집 대표.
B 모드별 최악: effective 모드별 C 최대 1개 mode_rep(≤3), 나머지 not_selected, 빈 모드는 excluded_modes,
   세 모드 모두 0 → NO_MODE_CANDIDATES.
C 군집 k: 병합 없이 전 후보를 min(k, 후보 수) 군집 → cluster_rep / clustered. k ∉ 1..max_cases → INVALID_PARAMS.
목표: abs(기본) POS = C_ref = max 선정 C⁰ (모든 subcase 같은 값), rel POS = C_i⁰. 라벨 L01… = 선정 C 내림차순.
"""
from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from esl.errors import EslError
from esl.opt import MODES, OBJECTIVE_NORMS, STRATEGIES

_ROUND = 12


def _r(x):
    return None if x is None else float(round(float(x), _ROUND))


# ---------------------------------------------------------------- 초기 컴플라이언스
def initial_compliance(target, entry_ids: list, load_fn, solver_cfg: dict, *, store_u: bool = True,
                       u_store: str | None = None, progress=None) -> dict:
    """후보 ESL 전부의 C⁰·umax (분해 1회).

    load_fn(entry_id) -> F (N,3) (대상 노드 순서). u_store: 경로면 np.memmap(float32, (K, 3N)), None 이면 메모리 배열.
    반환 {entry_ids, C (K,), umax (K,), U (K,3N) float32 | None, stats}.
    """
    from esl.mech.shell import ShellModel
    m = target.mesh
    sm = ShellModel(m["x0"], m["conn"], m["elem_type"], m["thickness"], m["E"], m["nu"],
                    drill_factor=float(solver_cfg["drill_factor"]), backend=str(solver_cfg["backend"]))
    nid = np.asarray(m["node_id"], dtype=np.int64)
    order = np.argsort(nid, kind="stable")
    spc = []
    for n, dof in target.supports:
        p = order[np.searchsorted(nid[order], int(n))]
        if nid[p] != int(n):
            raise EslError("NODE_NOT_IN_PART", f"3-2-1 노드 {n} 가 대상 메시에 없음")
        spc.append((int(p), str(dof)))
    K = len(entry_ids)
    N = nid.size
    U = None
    if store_u:
        if u_store:
            U = np.lib.format.open_memmap(u_store, mode="w+", dtype=np.float32, shape=(K, 3 * N))
        else:
            U = np.zeros((K, 3 * N), dtype=np.float32)
    C = np.zeros(K)
    umax = np.zeros(K)
    h = sm.factorize(spc)
    if progress:
        progress(0, K)
    for k, e in enumerate(entry_ids):
        F = np.asarray(load_fn(e), dtype=np.float64)
        u, _ = h.solve(F)
        ut = u[:, :3]
        C[k] = float(np.sum(F * ut))
        umax[k] = float(np.max(np.linalg.norm(ut, axis=1))) if N else 0.0
        if U is not None:
            U[k] = ut.reshape(-1).astype(np.float32)
        if progress:
            progress(k + 1, K)
    if isinstance(U, np.memmap):
        U.flush()
    return {"entry_ids": list(entry_ids), "C": C, "umax": umax, "U": U,
            "stats": {"n_factorizations": int(sm.stats.get("n_factorizations", 0)), "n_solves": h.n_solves,
                      "backend": sm.stats.get("backend"), "K_ff": sm.stats.get("K_ff")}}


def gram(U, rows: list[int], block: int = 32) -> np.ndarray:
    """G[i,j] = u_{rows[i]}·u_{rows[j]} (float64), 블록 단위(memmap 도 메모리에 전부 올리지 않음)."""
    n = len(rows)
    G = np.zeros((n, n))
    for i0 in range(0, n, block):
        A = np.asarray(U[rows[i0:i0 + block]], dtype=np.float64)
        for j0 in range(0, i0 + block, block):
            if j0 > i0:
                break
            B = A if j0 == i0 else np.asarray(U[rows[j0:j0 + block]], dtype=np.float64)
            g = A @ B.T
            G[i0:i0 + A.shape[0], j0:j0 + B.shape[0]] = g
            G[j0:j0 + B.shape[0], i0:i0 + A.shape[0]] = g.T
    return G


def mac_from_gram(G: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = np.diag(G).copy()
    den = np.outer(d, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        mac = np.where(den > 0, G ** 2 / den, 0.0)
    mac = np.clip(mac, 0.0, 1.0)
    np.fill_diagonal(mac, 1.0)
    return mac, np.sign(G)


# ---------------------------------------------------------------- 군집
def _clusters(items: list[int], mac: np.ndarray, n_clusters: int, method: str) -> list[list[int]]:
    """items(정렬 순서 위치) → 군집 목록(각 군집 = 정렬 순서 위치, 군집 순서 = 대표(첫 원소) 순)."""
    n = len(items)
    if n == 0:
        return []
    if n_clusters >= n or n == 1:
        return [[i] for i in items]
    sub = mac[np.ix_(items, items)]
    D = 1.0 - sub
    iu = np.triu_indices(n, 1)
    cond = np.maximum(D[iu], 0.0)
    Z = linkage(cond, method=method)
    lab = fcluster(Z, t=int(n_clusters), criterion="maxclust")
    groups: dict[int, list[int]] = {}
    for pos, l in zip(items, lab.tolist()):
        groups.setdefault(int(l), []).append(pos)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


# ---------------------------------------------------------------- 선정
def _validate(strategy, k, objective_norm, loads_cfg):
    if strategy not in STRATEGIES:
        raise EslError("INVALID_PARAMS", f"load_strategy: {STRATEGIES} (값 {strategy!r})")
    if objective_norm not in OBJECTIVE_NORMS:
        raise EslError("INVALID_PARAMS", f"objective_norm: {OBJECTIVE_NORMS} (값 {objective_norm!r})")
    mc = int(loads_cfg["max_cases"])
    if strategy == "C":
        if k is None or isinstance(k, bool) or not isinstance(k, (int, np.integer)) or not 1 <= int(k) <= mc:
            raise EslError("INVALID_PARAMS", f"k 는 1..{mc} 정수 (값 {k!r})")


def select(cands: list[dict], strategy: str = "A", *, loads_cfg: dict, objective_norm: str = "abs", k=None,
           U=None, u_rows: dict | None = None, sources_ref: str | None = None) -> dict:
    """LoadSelection (§5.2).

    cands: [{entry_id, C0, umax, mode (effective)|None, scene?}] (입력 순서 무관).
    U: (K', 3N) 병진 변위 배열(memmap 가능), u_rows: {entry_id: U 행 번호} — 전략 A·C 에 필요.
    """
    _validate(strategy, k, objective_norm, loads_cfg)
    if not cands:
        raise EslError("NO_LOAD_CASES", "하중 후보가 없음")
    ids = [str(c["entry_id"]) for c in cands]
    if len(set(ids)) != len(ids):
        raise EslError("INVALID_PARAMS", "같은 ESL 이 두 번 선택됨")
    srt = sorted(cands, key=lambda c: (-float(c["C0"]), str(c["entry_id"])))
    warns: list[str] = []
    rows = [{"entry_id": str(c["entry_id"]), "scene": c.get("scene"), "mode": c.get("mode"), "C0": _r(c["C0"]),
             "pos": None, "umax": _r(c.get("umax")), "status": "not_selected", "merged_into": None,
             "mac_to_target": None, "sign": None, "cluster": None, "label": None, "note": None} for c in srt]
    valid = [i for i, c in enumerate(srt) if float(c["C0"]) > 0]
    for i, c in enumerate(srt):
        if float(c["C0"]) <= 0:
            rows[i]["note"] = "C0<=0"
            warns.append(f"{c['entry_id']}: 초기 컴플라이언스 {float(c['C0']):.3g} ≤ 0 — 제외(하중 0?)")
    if not valid:
        raise EslError("NO_LOAD_CASES", "모든 후보의 초기 컴플라이언스가 0 이하(하중 0)")
    mc = int(loads_cfg["max_cases"])
    method = str(loads_cfg.get("linkage", "average"))
    clusters_out: list[dict] = []
    excluded_modes: list[str] = []
    mac = sgn = None
    if strategy in ("A", "C"):
        if U is None or u_rows is None:
            raise EslError("INPUT_INVALID", f"전략 {strategy} 에는 후보 변위(U) 필요")
        G = gram(U, [int(u_rows[str(srt[i]["entry_id"])]) for i in range(len(srt))])
        mac, sgn = mac_from_gram(G)
    selected: list[int] = []

    def put_clusters(groups, status_rep):
        for cid, g in enumerate(groups, start=1):
            rep = g[0]
            rows[rep]["status"] = status_rep
            rows[rep]["cluster"] = cid
            selected.append(rep)
            for i in g[1:]:
                rows[i].update(status="clustered", cluster=cid, merged_into=rows[rep]["entry_id"],
                               mac_to_target=_r(mac[i, rep]), sign=int(sgn[i, rep]) or 1)
            mm = mac[np.ix_(g, g)]
            clusters_out.append({"id": cid, "rep_entry_id": rows[rep]["entry_id"],
                                 "members": [rows[i]["entry_id"] for i in g],
                                 "min_mac": _r(float(mm.min()) if len(g) > 1 else 1.0)})

    if strategy == "A":
        thr = float(loads_cfg["mac_merge"])
        kept: list[int] = []
        for i in valid:
            best, bm = None, -1.0
            for j in kept:
                if mac[i, j] >= thr and mac[i, j] > bm:
                    best, bm = j, float(mac[i, j])
            if best is None:
                kept.append(i)
            else:
                rows[i].update(status="merged", merged_into=rows[best]["entry_id"], mac_to_target=_r(bm),
                               sign=int(sgn[i, best]) or 1)
        if len(kept) <= mc:
            for i in kept:
                rows[i]["status"] = "included"
            selected = list(kept)
        else:
            put_clusters(_clusters(kept, mac, mc, method), "cluster_rep")
    elif strategy == "B":
        for m in MODES:
            cand = [i for i in valid if rows[i]["mode"] == m]
            if not cand:
                excluded_modes.append(m)
                continue
            rows[cand[0]]["status"] = "mode_rep"
            selected.append(cand[0])
        if not selected:
            raise EslError("NO_MODE_CANDIDATES", "전략 B: 덴팅·뒤틀림·굽힘 모두 후보 0(분류 불가 포함) — 모드 수정 또는 "
                                                 "전략 A·C")
    else:
        put_clusters(_clusters(valid, mac, min(int(k), len(valid)), method), "cluster_rep")
    selected.sort()
    C_ref = float(srt[selected[0]]["C0"])
    for n, i in enumerate(selected, start=1):
        rows[i]["label"] = f"L{n:02d}"
        rows[i]["pos"] = _r(C_ref if objective_norm == "abs" else float(srt[i]["C0"]))
    return {"strategy": strategy, "objective_norm": objective_norm, "C_ref": _r(C_ref),
            "k": int(k) if strategy == "C" else None,
            "mac_merge": float(loads_cfg["mac_merge"]) if strategy == "A" else None, "max_cases": mc,
            "n_selected_esl": len(cands), "n_cases": len(selected), "rows": rows, "clusters": clusters_out,
            "excluded_modes": excluded_modes if strategy == "B" else [], "sources_ref": sources_ref,
            "warnings": warns}


def selection_bytes(sel: dict) -> bytes:
    """결정성 비교용 정규 JSON 바이트."""
    import json
    return json.dumps(sel, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run(target, cands: list[dict], load_fn, *, strategy: str, objective_norm: str, k, cfg: dict,
        u_store: str | None = None, sources_ref: str | None = None, progress=None) -> tuple[dict, dict, dict]:
    """OPT_LOAD 한 번: 초기 컴플라이언스 → 선정. cands = [{entry_id, mode, scene}] (C0·umax 는 여기서 채움).

    반환 (LoadSelection, {entry_id: F} 선정 하중만, compliance 정보(stats·C·umax)).
    """
    _validate(strategy, k, objective_norm, cfg["loads"])
    ids = [str(c["entry_id"]) for c in cands]
    comp = initial_compliance(target, ids, load_fn, cfg["solver"], store_u=strategy in ("A", "C"),
                              u_store=u_store, progress=progress)
    full = []
    for c, C0, um in zip(cands, comp["C"], comp["umax"]):
        full.append({**c, "C0": float(C0), "umax": float(um)})
    sel = select(full, strategy, loads_cfg=cfg["loads"], objective_norm=objective_norm, k=k, U=comp["U"],
                 u_rows={e: i for i, e in enumerate(ids)}, sources_ref=sources_ref)
    forces = {r["entry_id"]: np.asarray(load_fn(r["entry_id"]), dtype=np.float64) for r in sel["rows"] if r["label"]}
    return sel, forces, {"C": comp["C"], "umax": comp["umax"], "stats": comp["stats"], "entry_ids": ids}
