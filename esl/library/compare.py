"""설계 버전 비교 — ESLSO 수렴 판정 (계약 esl_p2_library.md §12.2).

``compare(base_entries, new_entries, criteria, opts) -> result(JSON)``

비드 반영 설계(새 버전)의 **검증 낙하** ESL 을 이전 설계(기준 버전)와 씬별로 비교해 추가 반복이 필요한지 판단한다.

- 짝: 같은 씬 키 ``(scenario, seq, drop_type, round, scene, orient, suffix)`` (대소문자·앞뒤 공백 무시, None = "").
  같은 버전에 같은 키가 여럿이면 마지막(등록 순서) 항목을 쓰고 경고. 짝 없는 씬은 ``unpaired`` 로 남긴다.
  짝이 하나도 없으면 ``NO_PAIRED_SCENES``.
- 하중 특징: 항목 정규화 격자의 셀 합력·합모멘트 ``[F_loc, M_loc/L_c]`` (K × 6·nx·ny, §8 과 같은 특징) 을 단위
  노름으로. 버전 간 메시가 달라도(비드) 같은 정규화 격자에서 비교한다 — 모든 항목이 같은 nx×ny 여야 함(GRID_MISMATCH).
- 씬별 지표: ``cos`` = 단위 특징 내적(하중 패턴 유사도), ``force_ratio`` = Σ|f_i| 신/구(자기평형 하중의 합력
  벡터 ≈ 0 이므로 크기는 절점력 크기 합), ``hotspot_shift`` = hotspot1 정규화 좌표 (ξ,η) 거리, ``eps_ratio`` =
  최대변형률 ε_max 신/구(t* 의 eps_max, 없으면 hotspot1 eps_rad), 검증 품질 변화(verdict·hotspot 오차·전 요소 p90).
- 집계: cos 최소·평균, 합력비·ε_max 비 범위, hotspot 이동 최대.
- 대표 동일 여부: 짝 씬만으로 버전별 같은 k 로 k-medoids(거리 = 단위 특징 현 길이 √(2−2cos)) → 클러스터를 멤버
  겹침 최대로 매칭(헝가리안) → 매칭된 쌍마다 기준 medoid(기준 버전 특징)와 비교 medoid(비교 버전 특징)의 cos 가
  ``cos_min`` 이상이면 같은 대표(§12.4 — medoid ID 동일은 요구하지 않음: 비슷한 씬이 여럿이면 medoid 가 그중
  어느 것이든 될 수 있다). ``rep_same`` = 모든 쌍이 같은 대표. 보조 규칙(``rep_basis = base_kept``): 기준 대표를
  새 버전 특징에 그대로 쓴 군집 비용이 새 최적보다 ``REP_COST_TOL``(5%) 이하로만 크고 기준 대표 씬 자체의 버전 간
  cos 가 ``cos_min`` 이상이면 대표 유지(연속적인 씬 분포에서 거의 같은 비용의 다른 분할로 뒤집히는 경우).
- 해상도(§12.4): 항목별 셀당 노드 수(비어 있지 않은 셀) 중앙값의 최소가 ``min_nodes_per_cell``(기본 64) 미만이면
  경고, 16 미만이면 "판정 신뢰 낮음". ``coarsen: half`` 면 특징을 2×2 셀 묶음(합력 합, 모멘트는 묶음 중심으로 이동)
  으로 계산한다(12×7 이하 격자에서는 무시).
- 판정: ``cos_min ≥ criteria.cos_min`` 이고 (``criteria.rep_same`` 이면) ``rep_same`` → ``CONVERGED``
  "수렴(반복 불필요)", 아니면 ``ITERATE`` "추가 반복 권장" + 바뀐 씬 목록(cos 미달·대표 변경).
- 셀 포락 차이: 버전별 짝 씬의 셀 max|F_cell| (nx,ny) 와 차이(신 − 구) — 보고서 히트맵.

산출(``save``): ``compare.json``, ``report.html``(자체 완결, 공통 ``json_text`` 이스케이프).
"""
from __future__ import annotations

import html
import math
import os
import re

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import analysis as an
from esl.library import normalize as nz
from esl.library import report_analysis as ra
from esl.report.html import json_text

SCENE_KEYS = ("scenario", "seq", "drop_type", "round", "scene", "orient", "suffix")
DEFAULT_CRITERIA = {"cos_min": 0.95, "rep_same": True, "min_nodes_per_cell": 64, "coarsen": False}
LOW_TRUST_NODES_PER_CELL = 16          # 셀당 노드 중앙값이 이보다 작으면 "판정 신뢰 낮음"
COARSEN_MIN_GRID = (12, 7)             # 이 이하(두 방향 모두) 격자에서는 coarsen 무시
REP_COST_TOL = 0.05                    # 기준 대표를 새 버전에 그대로 쓸 때 허용 군집 비용 증가(상대)
DEFAULT_OPTS = {"n_representative": 5, "seed": 0, "n_init": 8}
VERDICT_LABEL = {"CONVERGED": "수렴(반복 불필요)", "ITERATE": "추가 반복 권장"}


# ---------------------------------------------------------------- 버전
def _vkey(v):
    parts = re.split(r"(\d+)", str(v))
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts if p != ""]


def sort_versions(versions) -> list[str]:
    """자연 정렬(v2 < v10). None 은 제외. 자연 순서가 같으면(v100·v0100, V1·v1) 원문 사전순 — 결정적."""
    return sorted({str(v) for v in versions if v is not None and str(v).strip()}, key=lambda v: (_vkey(v), v))


def previous_version(versions, new) -> str | None:
    vs = sort_versions(versions)
    new = str(new)
    if new not in vs:
        vs = sort_versions(vs + [new])
    i = vs.index(new)
    return vs[i - 1] if i > 0 else None


# ---------------------------------------------------------------- 항목 도구
def _norm(v) -> str:
    return "" if v is None else str(v).strip().lower()


def scene_key(meta: dict) -> tuple:
    s = meta.get("scene") or {}
    return tuple(_norm(s.get(k)) for k in SCENE_KEYS)


def scene_label(meta: dict) -> str:
    s = meta.get("scene") or {}
    parts = [str(s.get("scenario") or "?")]
    if s.get("seq") is not None:
        parts.append(f"#{s.get('seq')}")
    parts.append(f"{s.get('drop_type') or '?'}{s.get('orient') or ''}")
    if s.get("round"):
        parts.append(str(s.get("round")))
    parts.append(f"S{s.get('scene') if s.get('scene') is not None else '?'}")
    if s.get("suffix"):
        parts.append(str(s.get("suffix")))
    return " ".join(parts)


def coarsen_half(F, M, C):
    """2×2 셀 묶음: 합력 합, 모멘트는 묶음 중심(소속 셀 중심 평균)으로 이동 M' = Σ(M + (c − c') × F).
    F, M, C: (nx, ny, 3) 같은 좌표계. 홀수 변의 마지막 묶음은 1열(행). 반환 (F2, M2, C2) (⌈nx/2⌉, ⌈ny/2⌉, 3)."""
    nx, ny = F.shape[:2]
    mx, my = (nx + 1) // 2, (ny + 1) // 2
    I, J = np.arange(nx) // 2, np.arange(ny) // 2

    def pool(G):
        out = np.zeros((mx, my) + G.shape[2:])
        np.add.at(out, (I[:, None], J[None, :]), G)
        return out

    cnt = pool(np.ones((nx, ny)))
    C2 = pool(C) / cnt[..., None]
    F2 = pool(F)
    M2 = pool(M + np.cross(C - C2[I][:, J], F))
    return F2, M2, C2


def _coarse_on(coarsen, nx, ny) -> bool:
    return coarsen == "half" and not (nx <= COARSEN_MIN_GRID[0] and ny <= COARSEN_MIN_GRID[1])


def _feature(e, coarsen=False) -> np.ndarray:
    g = e.meta["grid"]
    nx, ny = int(g["nx"]), int(g["ny"])
    fr = e.meta["frame"]
    F = np.asarray(e.summary["cell_F_loc"], dtype=np.float64)
    M = np.asarray(e.summary["cell_M_loc"], dtype=np.float64)
    if _coarse_on(coarsen, nx, ny):
        C = e.summary.get("cell_center") if hasattr(e.summary, "get") else None
        C = nz.cell_centers(fr, nx, ny) if C is None else np.asarray(C, dtype=np.float64)
        Cl = C.reshape(-1, 3) @ nz.rotation(fr).T            # 국부 좌표(F·M 과 같은 좌표계)
        F, M, _ = coarsen_half(F, M, Cl.reshape(nx, ny, 3))
        nx, ny = F.shape[:2]
    Lc = float(np.sqrt(float(fr["L_xi"]) * float(fr["L_eta"]) / (nx * ny)))
    return np.concatenate([F.reshape(-1), (M / Lc).reshape(-1)])


def nodes_per_cell(e, coarsen=False):
    """셀당 노드 수 중앙값(비어 있지 않은 셀, coarsen 이면 묶음 셀). cell_n 이 없으면 None."""
    n = e.summary.get("cell_n") if hasattr(e.summary, "get") else None
    if n is None:
        return None
    n = np.asarray(n, dtype=np.float64)
    if n.ndim != 2:
        return None
    if _coarse_on(coarsen, *n.shape):
        mx, my = (n.shape[0] + 1) // 2, (n.shape[1] + 1) // 2
        out = np.zeros((mx, my))
        np.add.at(out, ((np.arange(n.shape[0]) // 2)[:, None], (np.arange(n.shape[1]) // 2)[None, :]), n)
        n = out
    n = n[n > 0]
    return float(np.median(n)) if n.size else None


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _eps_max(meta: dict):
    t = meta.get("tstar") or {}
    for k in ("eps_max", "value"):
        v = _num(t.get(k)) if isinstance(t, dict) else None
        if v is not None:
            return v
    hs = (meta.get("quality") or {}).get("hotspots") or []
    return _num(hs[0].get("eps_rad")) if hs else None


def _hotspot(meta: dict):
    hs = (meta.get("quality") or {}).get("hotspots") or []
    if not hs:
        return None
    h = sorted(hs, key=lambda x: (x.get("rank") is None, x.get("rank")))[0]
    xi, eta = _num(h.get("xi")), _num(h.get("eta"))
    return None if xi is None or eta is None else [xi, eta]


def _p90(meta: dict):
    fld = (meta.get("quality") or {}).get("field") or {}
    a = fld.get("abs_err_pct") if isinstance(fld, dict) else None
    return _num(a.get("p90")) if isinstance(a, dict) else None


def _quality(meta: dict) -> dict:
    q = meta.get("quality") or {}
    return {"verdict": q.get("verdict"), "hotspot1_rel_err": _num(q.get("hotspot1_rel_err")), "field_p90": _p90(meta)}


def _ratio(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pair(base, new, warns) -> tuple[list, list, list]:
    def index(entries, name):
        d: dict = {}
        for e in entries:
            k = scene_key(e.meta)
            if k in d:
                warns.append(f"{name}: 같은 씬 키 {scene_label(e.meta)} 항목이 여럿 — 마지막 {e.entry_id} 사용"
                             f"(이전 {d[k].entry_id})")
            d[k] = e
        return d

    b, n = index(base, "기준 버전"), index(new, "비교 버전")
    keys = sorted(set(b) & set(n))
    pairs = [(k, b[k], n[k]) for k in keys]
    base_only = [{"key": list(k), "label": scene_label(b[k].meta), "entry_id": b[k].entry_id}
                 for k in sorted(set(b) - set(n))]
    new_only = [{"key": list(k), "label": scene_label(n[k].meta), "entry_id": n[k].entry_id}
                for k in sorted(set(n) - set(b))]
    return pairs, base_only, new_only


# ---------------------------------------------------------------- 재군집 매칭
def _chord(Xu) -> np.ndarray:
    G = np.clip(Xu @ Xu.T, -1.0, 1.0)
    D = np.sqrt(np.maximum(2.0 - 2.0 * G, 0.0))
    np.fill_diagonal(D, 0.0)
    return D


def _clusters(Xu, k, seed, n_init):
    D = _chord(Xu)
    med, labels, cost = an.kmedoids(D, k, seed, n_init)
    return [{"medoid": int(m), "members": np.flatnonzero(labels == ci).tolist()} for ci, m in enumerate(med)], D, cost


def _assign(O: np.ndarray):
    """겹침 최대 매칭 (행, 열) 목록."""
    try:
        from scipy.optimize import linear_sum_assignment

        r, c = linear_sum_assignment(-O)
        return list(zip(r.tolist(), c.tolist()))
    except ImportError:          # pragma: no cover - scipy 는 코어 의존성
        out, used = [], set()
        for i in np.argsort(-O.max(axis=1)):
            j = next(int(j) for j in np.argsort(-O[i]) if int(j) not in used)
            used.add(j)
            out.append((int(i), j))
        return sorted(out)


def representatives(Xb, Xn, labels, k, seed=0, n_init=8, cos_min=DEFAULT_CRITERIA["cos_min"]) -> dict:
    """버전별 같은 k 재군집 → 겹침 최대 매칭 → 짝 medoid cos ≥ cos_min 이면 같은 대표(§12.4).
    Xb, Xn: 단위 특징(행 = 짝 씬)."""
    K = Xb.shape[0]
    k = int(min(max(int(k), 1), K))
    cb, _, _ = _clusters(Xb, k, seed, n_init)
    cn, Dn, cost_n = _clusters(Xn, k, seed, n_init)
    O = np.array([[len(set(a["members"]) & set(b["members"])) for b in cn] for a in cb], dtype=float)
    # 매칭 점수 = 멤버 겹침(정수) + 짝 medoid cos 동점 깨기(0..0.5 < 1)
    Cm = np.array([[float(np.clip(Xb[a["medoid"]] @ Xn[b["medoid"]], -1.0, 1.0)) for b in cn] for a in cb])
    match = []
    for i, j in _assign(O + 0.25 * (Cm + 1.0)):
        a, b = cb[i], cn[j]
        mcos = float(np.clip(Xb[a["medoid"]] @ Xn[b["medoid"]], -1.0, 1.0))
        match.append({"base_cluster": i, "new_cluster": j, "overlap": int(O[i, j]), "base_size": len(a["members"]),
                      "new_size": len(b["members"]), "base_medoid": a["medoid"], "new_medoid": b["medoid"],
                      "base_medoid_label": labels[a["medoid"]], "new_medoid_label": labels[b["medoid"]],
                      "medoid_same": a["medoid"] == b["medoid"], "medoid_cos": mcos,
                      "rep_same": a["medoid"] == b["medoid"] or mcos >= cos_min,
                      "members_same": set(a["members"]) == set(b["members"])})
    match.sort(key=lambda m: -m["base_size"])
    agree = sum(m["overlap"] for m in match) / K if K else 1.0
    # 보조 규칙: 씬 분포가 연속적이면 k-medoids 해가 거의 같은 비용의 다른 분할로 뒤집힐 수 있다(대표가 이웃 씬으로
    # 바뀜). 기준 대표를 새 버전 특징에 그대로 썼을 때 비용이 새 최적보다 REP_COST_TOL 이하로만 크고 기준 대표 씬
    # 자체의 버전 간 cos 가 모두 cos_min 이상이면 대표가 유지된 것으로 본다.
    mb = [c["medoid"] for c in cb]
    cost_kept = an._cost(Dn, mb)
    excess = (cost_kept - cost_n) / cost_n if cost_n > 0 else 0.0
    self_cos = [float(Xb[m] @ Xn[m]) for m in mb]
    kept = bool(excess <= REP_COST_TOL and min(self_cos) >= cos_min)
    by_medoid = all(m["rep_same"] for m in match)

    def brief(cs):
        return [{"cluster": ci, "medoid": c["medoid"], "medoid_label": labels[c["medoid"]], "size": len(c["members"]),
                 "members": [labels[m] for m in c["members"]]} for ci, c in enumerate(cs)]

    return {"k": k, "base": brief(cb), "new": brief(cn), "matching": match,
            "rep_same": by_medoid or kept, "rep_basis": "medoid_cos" if by_medoid else ("base_kept" if kept else None),
            "cos_min": float(cos_min), "base_reps_cost_excess": float(excess), "cost_tol": REP_COST_TOL,
            "medoid_id_same": all(m["medoid_same"] for m in match), "partition_same": all(m["members_same"] for m in match),
            "partition_agreement": float(agree)}


# ---------------------------------------------------------------- 해상도(§12.4)
RELIABILITY_LABEL = {"ok": "해상도 충분", "warn": "셀당 노드 부족(판정 주의)", "low": "판정 신뢰 낮음",
                     "unknown": "셀당 노드 정보 없음"}


def _coarsen_mode(v):
    if v in (None, False) or (isinstance(v, str) and v.strip().lower() in ("", "false", "none", "off", "no")):
        return False
    if isinstance(v, str) and v.strip().lower() == "half":
        return "half"
    raise EslError("INPUT_INVALID", f"coarsen 은 false | half (값 {v!r})")


def _resolution(pairs, nx, ny, coarsen, min_npc, warns) -> dict:
    """항목별 셀당 노드 중앙값 → 버전별·전체 최소, 경고 수준 ok|warn|low|unknown."""
    applied = _coarse_on(coarsen, nx, ny)
    if coarsen and not applied:
        warns.append(f"coarsen={coarsen}: 격자 {nx}×{ny} 가 {COARSEN_MIN_GRID[0]}×{COARSEN_MIN_GRID[1]} 이하라 무시")
    fx, fy = ((nx + 1) // 2, (ny + 1) // 2) if applied else (nx, ny)

    def side(i):
        v = [nodes_per_cell(p[i], coarsen) for p in pairs]
        v = [x for x in v if x is not None]
        return min(v) if v else None

    b, n = side(1), side(2)
    vals = [x for x in (b, n) if x is not None]
    npc = min(vals) if vals else None
    if npc is None:
        level = "unknown"
    elif npc < min(LOW_TRUST_NODES_PER_CELL, min_npc):      # 하한을 16 아래로 낮췄으면 그 값까지 허용
        level = "low"
    elif npc < min_npc:
        level = "warn"
    else:
        level = "ok"
    if level in ("warn", "low"):
        warns.append(f"셀당 노드 중앙값 {npc:g} < {min_npc:g}(특징 격자 {fx}×{fy}) — 메시가 격자에 비해 성겨 같은 패턴도 "
                     f"cos 가 낮게 나올 수 있다"
                     + (f"; {min(LOW_TRUST_NODES_PER_CELL, min_npc):g} 미만이라 판정 신뢰 낮음" if level == "low" else "")
                     + ("" if applied else " (격자를 줄이거나 convergence.coarsen: half 고려)"))
    return {"nodes_per_cell_min": npc, "nodes_per_cell_base_min": b, "nodes_per_cell_new_min": n,
            "min_nodes_per_cell": int(min_npc), "low_trust_below": LOW_TRUST_NODES_PER_CELL,
            "level": level, "label": RELIABILITY_LABEL[level], "coarsen": coarsen or False, "coarsen_applied": applied,
            "feature_grid": {"nx": fx, "ny": fy}}


# ---------------------------------------------------------------- 본체
def _q(v):
    v = [x for x in v if x is not None]
    if not v:
        return {"min": None, "max": None, "mean": None}
    return {"min": float(min(v)), "max": float(max(v)), "mean": float(np.mean(v))}


def compare(base_entries, new_entries, criteria: dict | None = None, opts: dict | None = None) -> dict:
    crit = dict(DEFAULT_CRITERIA, **{k: v for k, v in (criteria or {}).items() if v is not None})
    o = dict(DEFAULT_OPTS, **{k: v for k, v in (opts or {}).items() if v is not None})
    if not 0 < float(crit["cos_min"]) <= 1:
        raise EslError("INPUT_INVALID", f"cos_min 은 (0, 1] (값 {crit['cos_min']})")
    crit["coarsen"] = _coarsen_mode(crit.get("coarsen"))
    if isinstance(crit["min_nodes_per_cell"], bool) or not float(crit["min_nodes_per_cell"]) >= 0:
        raise EslError("INPUT_INVALID", f"min_nodes_per_cell 은 0 이상 (값 {crit['min_nodes_per_cell']})")
    warns: list[str] = []
    base_entries, new_entries = list(base_entries), list(new_entries)
    prods = {_norm((e.meta.get("model") or {}).get("product")) for e in base_entries + new_entries}
    if len(prods) > 1:
        raise EslError("INPUT_INVALID", f"비교는 같은 모델(제품)끼리만 — 모델 {sorted(prods)}")
    pairs, base_only, new_only = _pair(base_entries, new_entries, warns)
    if not pairs:
        raise EslError("NO_PAIRED_SCENES", f"같은 씬 키의 짝이 없음(기준 {len(base_entries)}개, 비교 "
                       f"{len(new_entries)}개 — 씬 키 {', '.join(SCENE_KEYS)})")
    grids = {(int(e.meta["grid"]["nx"]), int(e.meta["grid"]["ny"])) for _, b, n in pairs for e in (b, n)}
    if len(grids) != 1:
        raise EslError("GRID_MISMATCH", f"비교는 같은 정규화 격자 필요(항목 격자 {sorted(grids)})")
    nx, ny = grids.pop()
    if base_only or new_only:
        warns.append(f"짝 없는 씬: 기준에만 {len(base_only)}개, 비교에만 {len(new_only)}개 — 비교에서 제외")

    coarsen = crit["coarsen"]
    res_info = _resolution(pairs, nx, ny, coarsen, float(crit["min_nodes_per_cell"]), warns)
    Xb = np.stack([_feature(b, coarsen) for _, b, _ in pairs])
    Xn = np.stack([_feature(n, coarsen) for _, _, n in pairs])
    nb, nn = np.linalg.norm(Xb, axis=1), np.linalg.norm(Xn, axis=1)
    zero = [pairs[i][1 if nb[i] <= 0 else 2].entry_id for i in range(len(pairs)) if nb[i] <= 0 or nn[i] <= 0]
    if zero:
        raise EslError("INPUT_INVALID", f"하중이 0 인 항목: {zero}")
    Xbu, Xnu = Xb / nb[:, None], Xn / nn[:, None]
    cos = np.clip(np.sum(Xbu * Xnu, axis=1), -1.0, 1.0)
    labels = [scene_label(n.meta) for _, _, n in pairs]
    cos_min_c = float(crit["cos_min"])

    scenes = []
    for i, (k, b, n) in enumerate(pairs):
        hb, hn = _hotspot(b.meta), _hotspot(n.meta)
        eb, en_ = _eps_max(b.meta), _eps_max(n.meta)
        qb, qn = _quality(b.meta), _quality(n.meta)
        sb = _num((b.meta.get("summary") or {}).get("sum_abs_f"))
        sn = _num((n.meta.get("summary") or {}).get("sum_abs_f"))
        reasons = []
        if cos[i] < cos_min_c:
            reasons.append(f"하중 패턴 변화 cos {cos[i]:.3f} < {cos_min_c:g}")
        scenes.append({
            "index": i, "key": dict(zip(SCENE_KEYS, k)), "label": labels[i],
            "base_entry": b.entry_id, "new_entry": n.entry_id, "cos": float(cos[i]),
            "sum_abs_f_base": sb, "sum_abs_f_new": sn, "force_ratio": _ratio(sn, sb),
            "hotspot_base": hb, "hotspot_new": hn,
            "hotspot_shift": None if hb is None or hn is None else float(math.hypot(hn[0] - hb[0], hn[1] - hb[1])),
            "eps_base": eb, "eps_new": en_, "eps_ratio": _ratio(en_, eb),
            "quality_base": qb, "quality_new": qn,
            "verdict_changed": qb["verdict"] != qn["verdict"],
            "hotspot_err_delta": None if qb["hotspot1_rel_err"] is None or qn["hotspot1_rel_err"] is None
            else qn["hotspot1_rel_err"] - qb["hotspot1_rel_err"],
            "changed": bool(reasons), "reasons": reasons})

    reps = representatives(Xbu, Xnu, labels, o["n_representative"], int(o["seed"]), int(o["n_init"]), cos_min_c)
    for m in (reps["matching"] if not reps["rep_same"] else []):
        if not m["rep_same"]:
            for idx, side in ((m["base_medoid"], "기준"), (m["new_medoid"], "비교")):
                r = (f"대표 변경({side} 대표 클러스터 {m['base_cluster'] + 1}: {m['base_medoid_label']} → "
                     f"{m['new_medoid_label']}, medoid cos {m['medoid_cos']:.3f})")
                if r not in scenes[idx]["reasons"]:
                    scenes[idx]["reasons"].append(r)
                scenes[idx]["changed"] = True

    agg = {"n_paired": len(pairs), "cos_min": float(cos.min()), "cos_mean": float(cos.mean()),
           "argmin_cos": labels[int(np.argmin(cos))],
           "force_ratio": _q([s["force_ratio"] for s in scenes]), "eps_ratio": _q([s["eps_ratio"] for s in scenes]),
           "hotspot_shift": _q([s["hotspot_shift"] for s in scenes]),
           "n_below_cos": int(np.sum(cos < cos_min_c)),
           "n_verdict_changed": sum(1 for s in scenes if s["verdict_changed"]),
           "n_changed": sum(1 for s in scenes if s["changed"])}
    reasons = []
    if agg["cos_min"] < cos_min_c:
        reasons.append(f"씬 cos 최소 {agg['cos_min']:.3f} < 기준 {cos_min_c:g} ({agg['n_below_cos']}개 씬)")
    if crit["rep_same"] and not reps["rep_same"]:
        n_diff = sum(1 for m in reps["matching"] if not m["rep_same"])
        reasons.append(f"대표 케이스 변경 {n_diff}/{reps['k']}개 클러스터(k={reps['k']} 재군집 매칭, 짝 medoid cos "
                       f"< {cos_min_c:g})")
    verdict = "ITERATE" if reasons else "CONVERGED"
    conv = {"verdict": verdict, "label": VERDICT_LABEL[verdict], "converged": verdict == "CONVERGED",
            "criteria": {"cos_min": cos_min_c, "rep_same": bool(crit["rep_same"]),
                         "min_nodes_per_cell": int(crit["min_nodes_per_cell"]), "coarsen": coarsen or False},
            "reliability": res_info["level"], "reliability_label": res_info["label"], "reasons": reasons,
            "changed_scenes": [{"label": s["label"], "base_entry": s["base_entry"], "new_entry": s["new_entry"],
                                "cos": s["cos"], "reasons": s["reasons"]} for s in scenes if s["changed"]]}

    # ---- 셀 포락(짝 씬)
    def env(side):
        G = np.stack([np.asarray(p[side].summary["cell_F_loc"], dtype=np.float64) for p in pairs])
        return np.linalg.norm(G, axis=3).max(axis=0)

    eb, en_ = env(1), env(2)
    fr = pairs[0][2].meta.get("frame") or {}
    result = {
        "schema": "esl/compare/1", "created_at": U.utcnow(), "criteria": conv["criteria"], "opts": o,
        "n_base": len(base_entries), "n_new": len(new_entries), "n_paired": len(pairs),
        "scene_keys": list(SCENE_KEYS), "scenes": scenes, "unpaired": {"base_only": base_only, "new_only": new_only},
        "aggregate": agg, "representatives": reps, "convergence": conv, "grid": {"nx": nx, "ny": ny},
        "resolution": res_info,
        "envelope": {"base": eb, "new": en_, "diff": en_ - eb, "base_max": float(eb.max()), "new_max": float(en_.max()),
                     "frame": {k: fr.get(k) for k in ("L_xi", "L_eta")}},
        "warnings": warns,
    }
    return U.jsonable(result)


def save(result: dict, out_dir: str, writer: U.Writer, info: dict | None = None) -> list[str]:
    """compare.json, report.html (기존 파일은 _backup 이동)."""
    files = []

    def path(n):
        files.append(n)
        return writer.fresh_file(os.path.join(out_dir, n), out_dir)

    U.write_json(path("compare.json"), result)
    write_report(result, path("report.html"), info)
    return files


# ---------------------------------------------------------------- 보고서
def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _r(v, p=3) -> str:
    return "—" if v is None else f"{float(v):.{p}f}"


def _pct(v) -> str:
    return "—" if v is None else f"{100 * float(v):.2f}%"


def _vb(v) -> str:
    return ra._verdict(v)


def write_report(r: dict, out_html: str, info: dict | None = None) -> str:
    info = info or {}
    cv = r["convergence"]
    agg = r["aggregate"]
    reps = r["representatives"]
    nx, ny = r["grid"]["nx"], r["grid"]["ny"]
    fr = r["envelope"].get("frame") or {}
    title = info.get("title") or "ESL 설계 버전 비교"
    cls = "pass" if cv["converged"] else "fail"
    S = [f"<header><h1>{_e(title)}</h1><div class='sub'>비교 ID <b>{_e(r.get('comparison_id', '—'))}</b> · 모델 "
         f"<b>{_e(r.get('model'))}</b> · 기준 <b>{_e(r.get('base_version'))}</b> → 비교 <b>{_e(r.get('new_version'))}</b>"
         f" · 생성 {_e(r.get('created_at'))}</div></header>"]
    rs = r.get("resolution") or {}
    lvl = rs.get("level")
    badge = ""
    if lvl in ("warn", "low", "unknown"):
        npc = rs.get("nodes_per_cell_min")
        badge = (f"<span class='rel {'fail' if lvl == 'low' else 'warn'}' id='reliability'>{_e(rs.get('label'))}"
                 + (f" · 셀당 노드 {npc:g} &lt; {rs.get('min_nodes_per_cell'):g}" if npc is not None else "")
                 + "</span>")
    S.append(f"<div class='card'><span class='verdict {cls}'>{'✓' if cv['converged'] else '!'} {_e(cv['label'])}</span>"
             f"{badge}<span class='muted small'> 판정 기준: 씬 cos 최소 ≥ {cv['criteria']['cos_min']:g}"
             f"{' 그리고 대표 케이스 동일(짝 medoid cos ≥ 기준)' if cv['criteria']['rep_same'] else ''}</span>"
             + ("<ul class='small'>" + "".join(f"<li>{_e(x)}</li>" for x in cv["reasons"]) + "</ul>"
                if cv["reasons"] else "<p class='small muted'>모든 짝 씬의 하중 패턴이 기준 이상으로 같고 대표 케이스가 "
                                      "그대로다 — 추가 비드 최적화 반복이 필요 없다.</p>") + "</div>")
    fr_q, er_q, hs_q = agg["force_ratio"], agg["eps_ratio"], agg["hotspot_shift"]
    tiles = [("짝 씬", f"{r['n_paired']}"), ("cos 최소", _r(agg["cos_min"], 4)), ("cos 평균", _r(agg["cos_mean"], 4)),
             ("합력비 범위", f"{_r(fr_q['min'])}–{_r(fr_q['max'])}"),
             ("ε_max 비 최대", _r(er_q["max"])), ("hotspot 이동 최대", _r(hs_q["max"])),
             ("대표 동일", f"{'예' if reps['rep_same'] else '아니오'} (k={reps['k']})"),
             ("바뀐 씬", f"{agg['n_changed']}"),
             ("셀당 노드(중앙값 최소)", "—" if rs.get("nodes_per_cell_min") is None
              else f"{rs['nodes_per_cell_min']:g}" + (" (2×2 묶음)" if rs.get("coarsen_applied") else ""))]
    S.append("<div class='tiles'>" + "".join(f"<div class='tile'><div class='v'>{_e(v)}</div><div class='k'>{_e(k)}"
                                             "</div></div>" for k, v in tiles) + "</div>")
    # ---- 씬 표
    S.append("<h2>1. 씬별 비교</h2><p class='muted small'>cos = 셀 합력·합모멘트 특징(단위 노름) 내적, 합력비 = Σ|f| "
             "신/구, hotspot 이동 = hotspot1 정규화 좌표(ξ,η) 거리, ε_max 비 = 최대변형률 신/구.</p>"
             "<div class='filters'><input id='f-text' placeholder='검색(씬·항목)'><span class='muted small' "
             "id='f-count'></span></div>")
    cols = ["씬", "cos", "합력비", "hotspot 이동", "ε_max 비", "검증 구→신", "hotspot 오차 구→신", "기준 항목",
            "비교 항목", "변경 사유"]
    rows = []
    for s in r["scenes"]:
        qb, qn = s["quality_base"], s["quality_new"]
        flag = " class='chg'" if s["changed"] else ""
        rows.append(f"<tr{flag}><td>{_e(s['label'])}</td><td class='num' data-v='{s['cos']}'>{_r(s['cos'], 4)}</td>"
                    f"<td class='num' data-v='{s['force_ratio'] if s['force_ratio'] is not None else -1}'>"
                    f"{_r(s['force_ratio'])}</td><td class='num' data-v='"
                    f"{s['hotspot_shift'] if s['hotspot_shift'] is not None else -1}'>{_r(s['hotspot_shift'])}</td>"
                    f"<td class='num' data-v='{s['eps_ratio'] if s['eps_ratio'] is not None else -1}'>"
                    f"{_r(s['eps_ratio'])}</td><td>{_vb(qb['verdict'])} → {_vb(qn['verdict'])}</td>"
                    f"<td class='num'>{_pct(qb['hotspot1_rel_err'])} → {_pct(qn['hotspot1_rel_err'])}</td>"
                    f"<td><code>{_e(s['base_entry'])}</code></td><td><code>{_e(s['new_entry'])}</code></td>"
                    f"<td class='small'>{_e('; '.join(s['reasons']))}</td></tr>")
    S.append("<div class='tablewrap'><table id='scenes' class='sortable'><thead><tr>"
             + "".join(f"<th class='sort'>{_e(h)}</th>" for h in cols) + "</tr></thead><tbody>" + "".join(rows)
             + "</tbody></table></div>")
    un = r["unpaired"]
    if un["base_only"] or un["new_only"]:
        S.append("<div class='card'><h3>짝 없는 씬(비교 제외)</h3><table><thead><tr><th>버전</th><th>씬</th><th>항목</th>"
                 "</tr></thead><tbody>"
                 + "".join(f"<tr><td>기준만</td><td>{_e(x['label'])}</td><td><code>{_e(x['entry_id'])}</code></td></tr>"
                           for x in un["base_only"])
                 + "".join(f"<tr><td>비교만</td><td>{_e(x['label'])}</td><td><code>{_e(x['entry_id'])}</code></td></tr>"
                           for x in un["new_only"]) + "</tbody></table></div>")
    # ---- 셀 포락 차이
    env = r["envelope"]
    Eb, En, Ed = (np.asarray(env[k], dtype=float) for k in ("base", "new", "diff"))
    tips = [[f"셀 ({i},{j}) 구 {ra._fmt(Eb[i, j])} → 신 {ra._fmt(En[i, j])} (차 {ra._fmt(Ed[i, j])})" for j in range(ny)]
            for i in range(nx)]
    S.append("<h2>2. 셀 포락 차이</h2><p class='muted small'>짝 씬의 셀별 max<sub>k</sub> |F<sub>cell</sub>| (정규화 격자). "
             "차이 = 신 − 구 (파랑 증가, 주황 감소).</p><div class='grid2'><div class='card'>"
             + ra.heatmap(Ed, fr, None, tips, "div", title="셀 포락 차이 (신 − 구)", w=560, legend_label="ΔF")
             + "</div><div class='card'>"
             + ra.heatmap(En, fr, None, tips, "seq", title=f"비교 버전 {r.get('new_version')} 셀 포락", w=560,
                          legend_label="|F|")
             + "</div></div>")
    # ---- 대표
    S.append(f"<h2>3. 대표 케이스 재군집 (k = {reps['k']})</h2><p class='muted small'>버전별로 짝 씬만 같은 k 로 "
             f"k-medoids → 멤버 겹침 최대로 클러스터 매칭 → 짝 medoid 의 cos 가 기준 이상이면 같은 대표(medoid 씬이 달라도 됨). 멤버 일치율 {_pct(reps['partition_agreement'])}."
             + (f" 짝 medoid cos 는 일부 기준 미달이지만 기준 대표를 새 버전에 그대로 써도 군집 비용 증가가 "
                f"{_pct(reps.get('base_reps_cost_excess'))} ≤ {_pct(reps.get('cost_tol'))} 이고 기준 대표 씬의 버전 간 cos 가 "
                "기준 이상이라 대표 유지로 본다(거의 같은 비용의 다른 분할)." if reps.get("rep_basis") == "base_kept" else "")
             + "</p>"
             "<table><thead><tr><th>클러스터</th><th>기준 대표</th><th>비교 대표</th><th>크기 구/신</th><th>겹침</th>"
             "<th>medoid cos</th><th>대표 동일</th></tr></thead><tbody>"
             + "".join(f"<tr><td>C{m['base_cluster'] + 1}</td><td>{_e(m['base_medoid_label'])}</td>"
                       f"<td>{_e(m['new_medoid_label'])}</td><td class='num'>{m['base_size']} / {m['new_size']}</td>"
                       f"<td class='num'>{m['overlap']}</td><td class='num'>{_r(m.get('medoid_cos'), 4)}</td>"
                       f"<td>{'<span class=pass>예</span>' if m.get('rep_same', m['medoid_same']) else '<span class=fail>아니오</span>'}"
                       "</td></tr>" for m in reps["matching"]) + "</tbody></table>")
    S.append("<h2>4. 한계</h2><ul class='lim'><li>하중 패턴은 정규화 격자 셀 합력·합모멘트로 비교한다 — 셀보다 작은 "
             "국부 변화는 cos 에 작게 나타난다.</li><li>셀당 노드가 적으면(중앙값 64 미만, 특히 16 미만) 메시 해상도 차이만으로도 "
             "cos 가 낮아진다 — 이때 판정은 참고용이다.</li><li>합력비는 Σ|f_i| (자기평형 하중의 합력 벡터는 ≈ 0) 기준이다.</li>"
             "<li>판정 기준(cos_min, rep_same)은 임시값이며 실제 반복 사례로 조정해야 한다.</li></ul>")
    if r.get("warnings"):
        S.append("<h3>경고</h3><ul class='small'>" + "".join(f"<li>{_e(w)}</li>" for w in r["warnings"]) + "</ul>")
    data = {"comparison_id": r.get("comparison_id"), "model": r.get("model"), "base_version": r.get("base_version"),
            "new_version": r.get("new_version"), "convergence": cv, "aggregate": agg}
    blob = json_text(U.jsonable(data))
    css = ra.CSS + (".verdict{display:inline-block;font-size:18px;font-weight:700;padding:4px 12px;border-radius:6px;"
                    "border:1px solid currentColor;margin-right:10px}.rel{display:inline-block;font-size:13px;font-weight:600;"
                    "padding:2px 8px;border-radius:6px;border:1px solid currentColor;margin-right:10px.rel.warn{color:var(--neg)}tr.chg td:first-child{font-weight:600}")
    doc = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>ESL 설계 버전 비교</title><style>{css}</style></head><body><main>" + "".join(S)
           + f"<script type='application/json' id='esl-data'>{blob}</script>"
           + f"<script>{ra.JS}</script></main></body></html>")
    with open(out_html, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    return out_html
