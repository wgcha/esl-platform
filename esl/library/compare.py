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
  겹침 최대로 매칭(헝가리안) → 매칭된 쌍마다 medoid 씬이 같은지. ``rep_same`` = 모두 같음.
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
from esl.library import report_analysis as ra
from esl.report.html import json_text

SCENE_KEYS = ("scenario", "seq", "drop_type", "round", "scene", "orient", "suffix")
DEFAULT_CRITERIA = {"cos_min": 0.9, "rep_same": True}
DEFAULT_OPTS = {"n_representative": 5, "seed": 0, "n_init": 8}
VERDICT_LABEL = {"CONVERGED": "수렴(반복 불필요)", "ITERATE": "추가 반복 권장"}


# ---------------------------------------------------------------- 버전
def _vkey(v):
    parts = re.split(r"(\d+)", str(v))
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts if p != ""]


def sort_versions(versions) -> list[str]:
    """자연 정렬(v2 < v10). None 은 제외."""
    return sorted({str(v) for v in versions if v is not None and str(v).strip()}, key=_vkey)


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


def _feature(e) -> np.ndarray:
    g = e.meta["grid"]
    nx, ny = int(g["nx"]), int(g["ny"])
    fr = e.meta["frame"]
    Lc = float(np.sqrt(float(fr["L_xi"]) * float(fr["L_eta"]) / (nx * ny)))
    F = np.asarray(e.summary["cell_F_loc"], dtype=np.float64)
    M = np.asarray(e.summary["cell_M_loc"], dtype=np.float64)
    return np.concatenate([F.reshape(-1), (M / Lc).reshape(-1)])


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
    med, labels, _ = an.kmedoids(_chord(Xu), k, seed, n_init)
    return [{"medoid": int(m), "members": np.flatnonzero(labels == ci).tolist()} for ci, m in enumerate(med)]


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


def representatives(Xb, Xn, labels, k, seed=0, n_init=8) -> dict:
    """버전별 같은 k 재군집 → 겹침 최대 매칭 → medoid 동일 여부."""
    K = Xb.shape[0]
    k = int(min(max(int(k), 1), K))
    cb = _clusters(Xb, k, seed, n_init)
    cn = _clusters(Xn, k, seed, n_init)
    O = np.array([[len(set(a["members"]) & set(b["members"])) for b in cn] for a in cb], dtype=float)
    match = []
    for i, j in _assign(O):
        a, b = cb[i], cn[j]
        match.append({"base_cluster": i, "new_cluster": j, "overlap": int(O[i, j]), "base_size": len(a["members"]),
                      "new_size": len(b["members"]), "base_medoid": a["medoid"], "new_medoid": b["medoid"],
                      "base_medoid_label": labels[a["medoid"]], "new_medoid_label": labels[b["medoid"]],
                      "medoid_same": a["medoid"] == b["medoid"],
                      "members_same": set(a["members"]) == set(b["members"])})
    match.sort(key=lambda m: -m["base_size"])
    agree = sum(m["overlap"] for m in match) / K if K else 1.0

    def brief(cs):
        return [{"cluster": ci, "medoid": c["medoid"], "medoid_label": labels[c["medoid"]], "size": len(c["members"]),
                 "members": [labels[m] for m in c["members"]]} for ci, c in enumerate(cs)]

    return {"k": k, "base": brief(cb), "new": brief(cn), "matching": match,
            "rep_same": all(m["medoid_same"] for m in match), "partition_same": all(m["members_same"] for m in match),
            "partition_agreement": float(agree)}


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

    Xb = np.stack([_feature(b) for _, b, _ in pairs])
    Xn = np.stack([_feature(n) for _, _, n in pairs])
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

    reps = representatives(Xbu, Xnu, labels, o["n_representative"], int(o["seed"]), int(o["n_init"]))
    for m in reps["matching"]:
        if not m["medoid_same"]:
            for idx, side in ((m["base_medoid"], "기준"), (m["new_medoid"], "비교")):
                r = f"대표 변경({side} 대표 클러스터 {m['base_cluster'] + 1}: {m['base_medoid_label']} → {m['new_medoid_label']})"
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
        n_diff = sum(1 for m in reps["matching"] if not m["medoid_same"])
        reasons.append(f"대표 케이스 변경 {n_diff}/{reps['k']}개 클러스터(k={reps['k']} 재군집 매칭)")
    verdict = "ITERATE" if reasons else "CONVERGED"
    conv = {"verdict": verdict, "label": VERDICT_LABEL[verdict], "converged": verdict == "CONVERGED",
            "criteria": {"cos_min": cos_min_c, "rep_same": bool(crit["rep_same"])}, "reasons": reasons,
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
    S.append(f"<div class='card'><span class='verdict {cls}'>{'✓' if cv['converged'] else '!'} {_e(cv['label'])}</span>"
             f"<span class='muted small'> 판정 기준: 씬 cos 최소 ≥ {cv['criteria']['cos_min']:g}"
             f"{' 그리고 대표 케이스 동일' if cv['criteria']['rep_same'] else ''}</span>"
             + ("<ul class='small'>" + "".join(f"<li>{_e(x)}</li>" for x in cv["reasons"]) + "</ul>"
                if cv["reasons"] else "<p class='small muted'>모든 짝 씬의 하중 패턴이 기준 이상으로 같고 대표 케이스가 "
                                      "그대로다 — 추가 비드 최적화 반복이 필요 없다.</p>") + "</div>")
    fr_q, er_q, hs_q = agg["force_ratio"], agg["eps_ratio"], agg["hotspot_shift"]
    tiles = [("짝 씬", f"{r['n_paired']}"), ("cos 최소", _r(agg["cos_min"], 4)), ("cos 평균", _r(agg["cos_mean"], 4)),
             ("합력비 범위", f"{_r(fr_q['min'])}–{_r(fr_q['max'])}"),
             ("ε_max 비 최대", _r(er_q["max"])), ("hotspot 이동 최대", _r(hs_q["max"])),
             ("대표 동일", f"{'예' if reps['rep_same'] else '아니오'} (k={reps['k']})"),
             ("바뀐 씬", f"{agg['n_changed']}")]
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
             f"k-medoids → 멤버 겹침 최대로 클러스터 매칭. 멤버 일치율 {_pct(reps['partition_agreement'])}.</p>"
             "<table><thead><tr><th>클러스터</th><th>기준 대표</th><th>비교 대표</th><th>크기 구/신</th><th>겹침</th>"
             "<th>대표 동일</th></tr></thead><tbody>"
             + "".join(f"<tr><td>C{m['base_cluster'] + 1}</td><td>{_e(m['base_medoid_label'])}</td>"
                       f"<td>{_e(m['new_medoid_label'])}</td><td class='num'>{m['base_size']} / {m['new_size']}</td>"
                       f"<td class='num'>{m['overlap']}</td><td>{'<span class=pass>예</span>' if m['medoid_same'] else '<span class=fail>아니오</span>'}"
                       "</td></tr>" for m in reps["matching"]) + "</tbody></table>")
    S.append("<h2>4. 한계</h2><ul class='lim'><li>하중 패턴은 정규화 격자 셀 합력·합모멘트로 비교한다 — 셀보다 작은 "
             "국부 변화는 cos 에 작게 나타난다.</li><li>합력비는 Σ|f_i| (자기평형 하중의 합력 벡터는 ≈ 0) 기준이다.</li>"
             "<li>판정 기준(cos_min, rep_same)은 임시값이며 실제 반복 사례로 조정해야 한다.</li></ul>")
    if r.get("warnings"):
        S.append("<h3>경고</h3><ul class='small'>" + "".join(f"<li>{_e(w)}</li>" for w in r["warnings"]) + "</ul>")
    data = {"comparison_id": r.get("comparison_id"), "model": r.get("model"), "base_version": r.get("base_version"),
            "new_version": r.get("new_version"), "convergence": cv, "aggregate": agg}
    blob = json_text(U.jsonable(data))
    css = ra.CSS + (".verdict{display:inline-block;font-size:18px;font-weight:700;padding:4px 12px;border-radius:6px;"
                    "border:1px solid currentColor;margin-right:10px}tr.chg td:first-child{font-weight:600}")
    doc = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>ESL 설계 버전 비교</title><style>{css}</style></head><body><main>" + "".join(S)
           + f"<script type='application/json' id='esl-data'>{blob}</script>"
           + f"<script>{ra.JS}</script></main></body></html>")
    with open(out_html, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    return out_html
