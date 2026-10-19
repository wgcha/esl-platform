"""종합분석 (계약 esl_p2_library.md §3, §8).

``run(entries, target=None, opts=None) -> (result: dict(JSON), arrays: dict(npz))``

1. 하중 케이스 {F_k}: 대상 메시가 있으면 각 항목을 ``mapping.to_target`` 으로 옮긴다. 대상과 **같은 메시**(mesh_sha256
   일치)인 항목은 원본 절점 F_eq 그대로. 그 뒤 ``normalization.scale``(none|mass|inch2).
   대상이 없으면(§8 전 라이브러리 통계) 정규화 격자 셀 합력·합모멘트를 그대로 특징으로 쓴다(모든 항목 같은 격자 필요).
2. 포락: 대상 격자 셀별 max_k |F_cell|, 그 방향(국부 단위벡터)·케이스. 대상이 있으면 절점별 max_k |f_i| 도.
3. SVD 특징 X (``svd_feature``): ``cell``(기본) = 대상 격자 셀별 [F_loc, M_loc/L_c] (K × 6·nx·ny, L_c = 셀 크기) —
   매핑된 하중이 담는 정보는 셀 합력·합모멘트뿐이므로(셀 내부 분포는 최소노름 보간) 대상 자체 항목(원본 절점력)과
   매핑 항목을 같은 해상도로 비교한다. ``nodal`` = 절점력 (K × 3N) — 계약 문구 그대로지만 원본/매핑 해상도 차이
   (특히 지지 반력 같은 집중력)가 패턴 차이로 보인다.
   X = U S Vᵀ (중심화하지 않음). ``distance: pattern``(기본)이면 각 행을 단위 노름으로 나눈 X̂ 를
   분해한다(크기와 무관한 하중 **패턴** 다양성 — 크기는 최악 케이스·minmax 가 다룬다). ``magnitude`` 면 X 그대로.
   누적 에너지 ΣS²_{≤r}/ΣS² ≥ svd_energy 인 최소 r. 특징 Z = U_r S_r (케이스별 모드 계수).
4. k-medoids(PAM: BUILD 초기화 + 시드 고정 무작위 초기화 n_init−1 개, SWAP 수렴, 최소 비용 채택)로 **실제 씬**
   n_representative 개 선택. 거리 = 특징 Z 의 유클리드 거리. pattern 이면 ‖ẑ_i − ẑ_j‖ ≈ √(2(1−cos θ_ij))
   (단위 하중 벡터 사이 현의 길이, r 모드 근사) — r=1 에서도 패턴 차이를 보존한다(절단 특징의 cosine 은 부호만 남음).
5. 최악 케이스(옵션 worst_case): 클러스터마다 Σ_i|f_i| 최대 씬을 추가 하중 케이스로. (자기평형 하중의 합력 벡터는 ≈0
   이므로 '합력 최대'는 절점력 크기 합으로 정의.)
6. 통계 뷰: 씬 유형(Corner/Edge/Face)·orient·인치·시나리오별 Σ|f| 분포와 셀 포락, 검증 오차 분포, SVD 계수 산점.
"""
from __future__ import annotations

import csv
import os

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import mapping as mp
from esl.library import normalization as nm
from esl.library import normalize as nz

DEFAULT_OPTS = {"svd_energy": 0.9, "n_representative": 5, "seed": 0, "n_init": 8, "worst_case": False,
                "normalization": "none", "moment_scale": "preserve", "equilibrate": True, "distance": "pattern", "svd_feature": "cell",
                "target_mass": None, "target_inch": None}
GROUP_KEYS = ("drop_class", "orient", "inch", "scenario", "verdict")


# ---------------------------------------------------------------- k-medoids
def _cost(D, med):
    return float(D[:, med].min(axis=1).sum())


def _build_init(D, k):
    K = D.shape[0]
    med = [int(np.argmin(D.sum(axis=1)))]
    while len(med) < k:
        cur = D[:, med].min(axis=1)
        best, bc = None, None
        for h in range(K):
            if h in med:
                continue
            c = float(np.minimum(cur, D[:, h]).sum())
            if bc is None or c < bc - 1e-15:
                best, bc = h, c
        med.append(best)
    return med


def kmedoids(D, k: int, seed: int = 0, n_init: int = 8, max_iter: int = 200):
    """PAM. 반환 (medoids 정렬 목록, labels (K,), cost). 같은 입력·시드면 같은 결과."""
    D = np.asarray(D, dtype=np.float64)
    K = D.shape[0]
    k = int(min(max(k, 1), K))
    rng = np.random.default_rng(seed)
    inits = [_build_init(D, k)] + [sorted(rng.choice(K, k, replace=False).tolist()) for _ in range(max(n_init - 1, 0))]
    best, best_cost = None, None
    for med in inits:
        med = list(map(int, med))
        cost = _cost(D, med)
        for _ in range(max_iter):
            improved = False
            for mi in range(k):
                for h in range(K):
                    if h in med:
                        continue
                    cand = med.copy()
                    cand[mi] = h
                    c = _cost(D, cand)
                    if c < cost - 1e-12 * max(cost, 1.0):
                        med, cost, improved = cand, c, True
            if not improved:
                break
        med = sorted(med)
        if best is None or cost < best_cost - 1e-12 * max(best_cost, 1.0):
            best, best_cost = med, cost
    labels = np.argmin(D[:, best], axis=1)
    return best, labels, best_cost


def distance_matrix(Z) -> np.ndarray:
    """특징 행 사이 유클리드 거리 (K,K)."""
    Z = np.asarray(Z, dtype=np.float64)
    D = np.sqrt(np.maximum(np.sum((Z[:, None, :] - Z[None, :, :]) ** 2, axis=2), 0.0))
    np.fill_diagonal(D, 0.0)
    return D


# ---------------------------------------------------------------- 도구
def _cell_sums_local(x0, F, fr, nx, ny):
    """(K,N,3) → (K,nx,ny,3) 대상 격자 셀 합력(국부 성분)."""
    i, j, _ = nz.cell_index(fr, x0, nx, ny)
    cid = i * ny + j
    R = nz.rotation(fr)
    out = np.zeros((F.shape[0], nx * ny, 3))
    for k in range(F.shape[0]):
        for c in range(3):
            out[k, :, c] = np.bincount(cid, weights=F[k, :, c], minlength=nx * ny)
    return (out @ R.T).reshape(F.shape[0], nx, ny, 3), np.bincount(cid, minlength=nx * ny).reshape(nx, ny)


def boundary_outline(x0, conn, elem_type, fr) -> np.ndarray:
    """메시 경계 모서리(한 요소만 쓰는 모서리)의 정규화 좌표 선분 (S,2,2)."""
    conn = np.asarray(conn, dtype=np.int64)
    et = np.asarray(elem_type).astype(int)
    q, t = conn[et == 4], conn[et != 4]
    E = np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]],
                        t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=0)
    E = np.sort(E, axis=1)
    uniq, cnt = np.unique(E, axis=0, return_counts=True)
    B = uniq[cnt == 1]
    loc = nz.local_coords(fr, x0)[:, :2]
    return np.stack([loc[B[:, 0]], loc[B[:, 1]]], axis=1)


def _brief(e) -> dict:
    s = e.meta.get("scene") or {}
    q = e.meta.get("quality") or {}
    m = e.meta.get("model") or {}
    fld = q.get("field") or {}
    return {"entry_id": e.meta["entry_id"], "product": m.get("product"), "inch": m.get("inch"),
            "version": m.get("version"), "scenario": s.get("scenario"), "seq": s.get("seq"),
            "drop_type": s.get("drop_type"), "drop_class": s.get("drop_class") or s.get("drop_type"),
            "orient": s.get("orient"), "scene": s.get("scene"), "round": s.get("round"), "variant": s.get("variant"),
            "verdict": q.get("verdict"), "hotspot1_rel_err": q.get("hotspot1_rel_err"),
            "field_p90": fld.get("p90") if isinstance(fld, dict) else None,
            "mass": (m.get("mass") or {}).get("value"), "tstar_time": (e.meta.get("tstar") or {}).get("time")}


def _q(v):
    v = np.asarray(v, dtype=float)
    if v.size == 0:
        return None
    return {"n": int(v.size), "min": float(v.min()), "p25": float(np.percentile(v, 25)),
            "median": float(np.median(v)), "p75": float(np.percentile(v, 75)), "max": float(v.max())}


# ---------------------------------------------------------------- 본체
def run(entries, target=None, opts: dict | None = None):
    o = dict(DEFAULT_OPTS)
    if opts:
        o.update({k: v for k, v in opts.items() if v is not None or k in ("target_mass", "target_inch")})
    if not 0 < float(o["svd_energy"]) <= 1:
        raise EslError("INPUT_INVALID", "svd_energy 는 (0, 1]")
    entries = list(entries)
    if not entries:
        raise EslError("INPUT_INVALID", "분석할 항목이 없음(필터 확인)")
    K = len(entries)
    warns: list[str] = []
    briefs = [_brief(e) for e in entries]

    # ---- 정규화 계수
    if target is not None:
        tm = target.meta.get("model") or {}
        tmeta = {"mass": o["target_mass"] if o["target_mass"] is not None else (tm.get("mass") or {}).get("value"),
                 "inch": o["target_inch"] if o["target_inch"] is not None else tm.get("inch")}
    else:
        tmeta = {"mass": o["target_mass"], "inch": o["target_inch"]}
    factors = []
    for b in briefs:
        if o["normalization"] == "none":
            factors.append(1.0)
        else:
            factors.append(nm.factor(o["normalization"], {"source": {"mass": b["mass"], "inch": b["inch"]},
                                                          "target": tmeta}))
    factors = np.asarray(factors)

    arrays: dict = {}
    case_info = []
    if target is not None:
        if target.raw is None:
            raise EslError("INPUT_INVALID", "대상 항목의 원본(raw) 메시가 필요")
        tx = np.asarray(target.raw["x0"], dtype=np.float64)
        tfr = target.meta["frame"]
        nx, ny = int(target.meta["grid"]["nx"]), int(target.meta["grid"]["ny"])
        N = tx.shape[0]
        F = np.zeros((K, N, 3))
        for k, e in enumerate(entries):
            same = e.meta.get("mesh_sha256") == target.meta.get("mesh_sha256")
            if same:
                if e.raw is None:
                    raise EslError("INPUT_INVALID", f"대상과 같은 메시 항목 {e.entry_id}: 원본 F_eq(raw) 필요")
                F[k] = np.asarray(e.raw["f"], dtype=np.float64)
                info = {"self": True, "conservation_rel_max": 0.0, "merged_groups": [], "equilibrium_after": None,
                        "equilibrate_correction_rel": 0.0}
            else:
                fk, info = mp.to_target(e.summary_for_mapping(), tx, tfr,
                                        {"moment_scale": o["moment_scale"], "equilibrate": o["equilibrate"]})
                info.pop("F_cells", None)
                info["self"] = False
                F[k] = fk
            F[k] *= factors[k]
            case_info.append(info)
        G, cnt = _cell_sums_local(tx, F, tfr, nx, ny)
        if o["svd_feature"] == "nodal":
            X = F.reshape(K, -1)
        elif o["svd_feature"] == "cell":
            Lc = float(np.sqrt(tfr["L_xi"] * tfr["L_eta"] / (nx * ny)))
            Mc = np.stack([nz.grid_summary(tx, F[k], nx, ny, tfr, top_n=1)["cell_M_loc"] for k in range(K)])
            X = np.concatenate([G.reshape(K, -1), (Mc / Lc).reshape(K, -1)], axis=1)
        else:
            raise EslError("INPUT_INVALID", f"svd_feature: cell|nodal (값 {o['svd_feature']!r})")
        nmag = np.linalg.norm(F, axis=2)
        arrays.update(mapped_F=F, node_id=np.asarray(target.raw["node_id"]), node_env_mag=nmag.max(axis=0),
                      node_env_case=np.argmax(nmag, axis=0).astype(np.int64),
                      target_xi_eta=nz.local_coords(tfr, tx)[:, :2],
                      outline=boundary_outline(tx, target.raw["conn"], target.raw["elem_type"], tfr),
                      cell_count=cnt)
        sum_abs = nmag.sum(axis=1)
    else:
        grids = {(int(e.meta["grid"]["nx"]), int(e.meta["grid"]["ny"])) for e in entries}
        if len(grids) != 1:
            raise EslError("GRID_MISMATCH", f"대상 없는 분석은 같은 격자 필요(항목 격자 {sorted(grids)})")
        nx, ny = grids.pop()
        G = np.stack([np.asarray(e.summary["cell_F_loc"]) * fk for e, fk in zip(entries, factors)])
        Mloc = np.stack([np.asarray(e.summary["cell_M_loc"]) * fk for e, fk in zip(entries, factors)])
        Lc = np.array([np.sqrt(e.meta["frame"]["L_xi"] * e.meta["frame"]["L_eta"] / (nx * ny)) for e in entries])
        X = np.concatenate([G.reshape(K, -1), (Mloc / Lc[:, None, None, None]).reshape(K, -1)], axis=1)
        sum_abs = np.array([float(e.meta["summary"]["sum_abs_f"]) for e in entries]) * factors
        case_info = [{"self": None} for _ in entries]
        tfr = None

    # ---- 포락(대상 격자)
    gmag = np.linalg.norm(G, axis=3)
    env_case = np.argmax(gmag, axis=0)
    env_mag = gmag.max(axis=0)
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    env_vec = G[env_case, ii, jj]
    env_dir = env_vec / np.where(env_mag > 0, env_mag, 1.0)[..., None]
    arrays.update(cell_F_loc=G, env_mag=env_mag, env_case=env_case.astype(np.int64), env_dir=env_dir)

    # ---- SVD
    if o["distance"] not in ("pattern", "magnitude"):
        raise EslError("INPUT_INVALID", f"distance: pattern|magnitude (값 {o['distance']!r})")
    xn = np.linalg.norm(X, axis=1)
    if np.any(xn <= 0):
        raise EslError("INPUT_INVALID", f"하중이 0 인 항목: {[briefs[k]['entry_id'] for k in np.flatnonzero(xn <= 0)]}")
    Xs = X / xn[:, None] if o["distance"] == "pattern" else X
    Ux, S, _ = np.linalg.svd(Xs, full_matrices=False)
    tot = float(np.sum(S ** 2))
    if tot <= 0:
        raise EslError("INPUT_INVALID", "모든 하중이 0")
    energy = S ** 2 / tot
    cum = np.cumsum(energy)
    r = int(np.searchsorted(cum, float(o["svd_energy"]) - 1e-12) + 1)
    r = min(r, S.size)
    scores = Ux * S
    Z = scores[:, :r]
    D = distance_matrix(Z)
    kk = int(min(int(o["n_representative"]), K))
    if kk < int(o["n_representative"]):
        warns.append(f"항목 {K}개 < n_representative {o['n_representative']} — 대표 {kk}개")
    med, labels, cost = kmedoids(D, kk, int(o["seed"]), int(o["n_init"]))
    arrays.update(svd_S=S, svd_scores=scores, dist=D, labels=labels.astype(np.int64))

    clusters = []
    for ci, m in enumerate(med):
        mem = np.flatnonzero(labels == ci)
        worst = int(mem[np.argmax(sum_abs[mem])])
        clusters.append({"id": ci, "medoid": int(m), "medoid_entry": briefs[m]["entry_id"], "members": mem.tolist(),
                         "size": int(mem.size), "worst": worst, "worst_entry": briefs[worst]["entry_id"],
                         "mean_dist": float(D[mem, m].mean())})
    clusters.sort(key=lambda c: (-c["size"], c["medoid"]))
    remap = {c["id"]: n for n, c in enumerate(clusters)}
    for c in clusters:
        c["id"] = remap[c["id"]]
    labels = np.array([remap[int(x)] for x in labels], dtype=np.int64)
    arrays["labels"] = labels
    load_cases = []
    for c in clusters:
        load_cases.append({"label": f"REP{c['id'] + 1}", "case_index": c["medoid"], "entry_id": c["medoid_entry"],
                           "role": "medoid", "cluster": c["id"]})
    if o["worst_case"]:
        for c in clusters:
            if c["worst"] != c["medoid"]:
                load_cases.append({"label": f"WORST{c['id'] + 1}", "case_index": c["worst"],
                                   "entry_id": c["worst_entry"], "role": "worst", "cluster": c["id"]})

    cases = []
    for k, b in enumerate(briefs):
        ci = case_info[k]
        cases.append({"index": k, **b, "scale_factor": float(factors[k]), "sum_abs_f": float(sum_abs[k]),
                      "cluster": int(labels[k]), "is_medoid": k in med,
                      "is_worst": any(c["worst"] == k for c in clusters),
                      "self": ci.get("self"),
                      "mapping": None if ci.get("self") is None else
                      {"conservation_rel_max": ci.get("conservation_rel_max"),
                       "n_merged_groups": len(ci.get("merged_groups") or []),
                       "equilibrium_before": ci.get("equilibrium_before"),
                       "equilibrium_after": ci.get("equilibrium_after"),
                       "equilibrate_correction_rel": ci.get("equilibrate_correction_rel"),
                       "moment_factor": ci.get("moment_factor")},
                      "svd_coef": scores[k, :min(3, S.size)].tolist()})

    # ---- 통계 뷰
    stats = {"groups": {}, "group_env": {}, "verification": [], "svd_scatter": []}
    for key in GROUP_KEYS:
        vals = {}
        for k, b in enumerate(briefs):
            vals.setdefault(str(b.get(key)), []).append(k)
        stats["groups"][key] = {v: {"n": len(ix), "cases": ix, "sum_abs_f": _q(sum_abs[ix])}
                                for v, ix in sorted(vals.items())}
        if key == "drop_class":
            labs = sorted(vals)
            arrays["group_env_drop_class"] = np.stack([gmag[vals[v]].max(axis=0) for v in labs])
            stats["group_env"]["drop_class"] = labs
    for k, b in enumerate(briefs):
        stats["verification"].append({"index": k, "entry_id": b["entry_id"], "verdict": b["verdict"],
                                      "hotspot1_rel_err": b["hotspot1_rel_err"], "field_p90": b["field_p90"]})
        stats["svd_scatter"].append({"index": k, "c1": float(scores[k, 0]),
                                     "c2": float(scores[k, 1]) if S.size > 1 else 0.0, "cluster": int(labels[k])})
    errs = [b["hotspot1_rel_err"] for b in briefs if isinstance(b["hotspot1_rel_err"], (int, float))]
    stats["verification_summary"] = _q(errs)

    mapping_summary = None
    if target is not None:
        mapped = [c for c in case_info if not c.get("self")]
        mapping_summary = {
            "n_self": sum(1 for c in case_info if c.get("self")), "n_mapped": len(mapped),
            "conservation_rel_max": max([c["conservation_rel_max"] for c in mapped], default=0.0),
            "n_merged_groups_total": sum(len(c.get("merged_groups") or []) for c in mapped),
            "equilibrate_correction_rel_max": max([c["equilibrate_correction_rel"] for c in mapped], default=0.0),
            "moment_scale": o["moment_scale"], "equilibrate": bool(o["equilibrate"])}
    result = {
        "schema": "esl/analysis/1", "created_at": U.utcnow(), "opts": o,
        "target": None if target is None else {
            "entry_id": target.entry_id, "mesh_sha256": target.meta.get("mesh_sha256"),
            "model": {k: (target.meta.get("model") or {}).get(k) for k in ("product", "inch", "version", "part_id",
                                                                         "part_title", "n_nodes", "n_elems",
                                                                         "units_label")},
            "frame": tfr, "target_norm_meta": tmeta},
        "grid": {"nx": nx, "ny": ny},
        "n_cases": K, "cases": cases,
        "svd": {"singular_values": S.tolist(), "energy": energy.tolist(), "cum_energy": cum.tolist(),
                "n_modes": r, "threshold": float(o["svd_energy"]), "feature": (o["svd_feature"] if target is not None else "cell(entry grid)"),
                "rows": "unit" if o["distance"] == "pattern" else "raw"},
        "clusters": clusters, "kmedoids_cost": cost, "load_cases": load_cases,
        "envelope": {"max": float(env_mag.max()), "argmax_cell": [int(v) for v in np.unravel_index(np.argmax(env_mag),
                                                                                                   env_mag.shape)]},
        "mapping": mapping_summary, "stats": stats, "warnings": warns,
    }
    arrays["case_entry_id"] = np.array([b["entry_id"] for b in briefs])
    return U.jsonable(result), arrays


def save(result: dict, arrays: dict, out_dir: str, writer: U.Writer) -> list[str]:
    """analysis.json, mapped_loads.npz, envelope.csv, representatives.csv (기존 파일은 _backup 이동)."""
    files = []

    def path(n):
        files.append(n)
        return writer.fresh_file(os.path.join(out_dir, n), out_dir)

    U.write_json(path("analysis.json"), result)
    np.savez_compressed(path("mapped_loads.npz"), **{k: np.asarray(v) for k, v in arrays.items()})
    nx, ny = result["grid"]["nx"], result["grid"]["ny"]
    cases = result["cases"]
    cnt = arrays.get("cell_count")
    with open(path("envelope.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["i", "j", "xi_c", "eta_c", "max_abs_f", "case_index", "entry_id", "dir_xi", "dir_eta", "dir_n",
                    "n_target_nodes"])
        for i in range(nx):
            for j in range(ny):
                k = int(arrays["env_case"][i, j])
                d = arrays["env_dir"][i, j]
                w.writerow([i, j, f"{(i + 0.5) / nx:.6g}", f"{(j + 0.5) / ny:.6g}", f"{arrays['env_mag'][i, j]:.9E}",
                            k, cases[k]["entry_id"], f"{d[0]:.6g}", f"{d[1]:.6g}", f"{d[2]:.6g}",
                            "" if cnt is None else int(cnt[i, j])])
    with open(path("representatives.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label", "role", "cluster", "cluster_size", "case_index", "entry_id", "product", "inch",
                    "drop_type", "orient", "scene", "scenario", "verdict", "sum_abs_f", "members"])
        for lc in result["load_cases"]:
            c = cases[lc["case_index"]]
            cl = result["clusters"][lc["cluster"]]
            w.writerow([lc["label"], lc["role"], lc["cluster"], cl["size"], lc["case_index"], lc["entry_id"],
                        c["product"], c["inch"], c["drop_type"], c["orient"], c["scene"], c["scenario"], c["verdict"],
                        f"{c['sum_abs_f']:.9E}", " ".join(cases[m]["entry_id"] for m in cl["members"])])
    return files
