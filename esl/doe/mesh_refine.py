"""④ 세분화 폴백 계획(계약 esl_compare_mesh_options.md C2-D-18~22, §4A).

기본 h(3 mm)로 CAD 메시가 실패한 형상만 요소를 더 잘게 짜서 다시 시도한다. 이 모듈은 **계획**(시도 목록·요소 수 예측·
상한 판정)과 gmsh 세션 안 면 찾기만 한다. 실행(시도 폴더·``run_isolated``·성공본 교체)은 워커 ``stages._cmp_mesh_shape``.

- ``plan(stage, prev_meta, h, cfg, avail_bytes)`` → 시도 목록. stage = cad | refine_local | refine_global | defeature | remesh.
  defeature(v0.16.1 esl_select_relax.md §5A.1) = 시도 2개(compound 켬 → compound 면 실패 때만 compound 끔, only_if).
  시도 dict = {stage, kind(local|global|None), factor, h_mm(목표 크기), mesh_h(run_isolated 의 h), base_h_mm, n_est,
  bytes_est, size_fields?, max_elems?, skipped, reason(elems|memory|time|no_face|None), info?}.
- ``attempt_cfg(cfg, attempt)`` → 그 시도에 넘길 cfg 사본(mesh.size_fields, 세분화면 mesh.max_elems = refine.max_elems).
- ``check_limits(attempt, cfg, avail_bytes, elapsed_s, t_prev, n_prev)`` → 건너뛸 사유 | None(시도 직전 다시 판정용).
- ``estimate_elems(face_areas, h, local_keys, h_l)`` → 예측 요소 수(N = ΣA / h² × elem_per_h2, 국부 = N_h + A_l(1/h_l² − 1/h²)).
- ``neighbor_faces(gmsh, keys, rings)`` → bbox 키 면 + 이웃 고리(곡선 공유) [{tag, ring, key, type, center, area}].
- ``geom_summary(src, mc, keys, rings)`` → 실패 시도 뒤 같은 STEP 넓이(gmsh 자식 안에서만 — ``mesh_gmsh._fail_info``).
- ``failed_faces(meta)`` / ``read_attempt(out_dir)`` → 직전 시도 실패 면 목록 / 시도 폴더의 mesh.json 또는 mesh_error.json.

숫자는 모두 설정(``bead_doe.compare.refine``·``compare.mesh``·``mesh``·``run``)에서 읽는다.
"""
from __future__ import annotations

import copy
import math
import os

from esl.errors import EslError

STAGES = ("cad", "refine_local", "refine_global", "defeature", "remesh")   # v0.16.1 defeature(SR-D-16)
REFINE_STAGES = ("refine_local", "refine_global")
SKIP_INFO = "REFINE_SKIPPED_LIMIT"
NO_FACE_INFO = "REFINE_LOCAL_NO_FACE"


def _rcfg(cfg: dict) -> dict:
    """compare.refine(없으면 DEFAULTS 거울)."""
    from esl.doe import DEFAULTS, _deep_merge
    over = ((cfg.get("compare") or {}).get("refine")) if isinstance(cfg, dict) else None
    return _deep_merge(DEFAULTS["compare"]["refine"], over if isinstance(over, dict) else {})


def ladder(cfg: dict, mode: str | None = None) -> list[str]:
    """C2-D-18 시도 단계: auto = compare.mesh.ladder(중복 제거·알 수 없는 단계 오류), cad = [cad], remesh = [remesh]."""
    from esl.doe import DEFAULTS
    cm = (cfg.get("compare") or {}).get("mesh") or {}
    m = str(mode or cm.get("mode") or DEFAULTS["compare"]["mesh"]["mode"])
    if m == "cad":
        return ["cad"]
    if m == "remesh":
        return ["remesh"]
    if m != "auto":
        raise EslError("CONFIG_INVALID", f"compare.mesh.mode {m!r} (cad|remesh|auto)")
    lad = list(cm.get("ladder") or DEFAULTS["compare"]["mesh"]["ladder"])
    bad = [s for s in lad if s not in STAGES]
    if bad or len(set(lad)) != len(lad) or lad[0] != "cad":
        raise EslError("CONFIG_INVALID", f"compare.mesh.ladder {lad} — 단계 ⊆ {list(STAGES)}, cad 맨 앞, 중복 금지")
    return lad


# ---------------------------------------------------------------- 예측
def _key(k) -> tuple:
    return tuple(round(float(v), 6) for v in k)


def estimate_elems(face_areas, h: float, local_keys=None, h_l: float | None = None, *, elem_per_h2: float = 1.0) -> int:
    """C2-D-21 예측 요소 수. face_areas = 전체 넓이(mm², 수) 또는 {bbox 키: 넓이}. local_keys = 국부 면 bbox 키 목록
    또는 국부 넓이(수). h_l 이 있으면 N = N_h + A_l × (1/h_l² − 1/h²) × e, 없으면 N_h = ΣA / h² × e."""
    from esl.doe.mesh_gmsh import _key_near
    if isinstance(face_areas, dict):
        areas = {_key(k): float(a) for k, a in face_areas.items()}
        A = sum(areas.values())
    else:
        areas, A = {}, float(face_areas)
    e = float(elem_per_h2)
    n = A / (float(h) ** 2) * e
    if h_l is not None and local_keys is not None:
        if isinstance(local_keys, (int, float)):
            Al = float(local_keys)
        else:
            ks = [_key(k) for k in local_keys]
            Al = sum(a for k, a in areas.items() if any(_key_near(k, q) for q in ks))
        n += Al * (1.0 / float(h_l) ** 2 - 1.0 / float(h) ** 2) * e
    return int(math.ceil(max(n, 0.0) - 1e-9))


def _bytes_est(n_est: int, avail: int | None, margin: float) -> float:
    """BD-D-15 와 같은 식(evaluate.parallel_limit, 병렬 1, n_nodes ≈ 요소 수 — quad 위주)."""
    from esl.doe.evaluate import parallel_limit
    return float(parallel_limit(max(int(n_est), 1), 1, margin, available=avail)["estimate_bytes"])


def check_limits(attempt: dict, cfg: dict, avail_bytes: int | None, elapsed_s: float | None = None,
                 t_prev: float | None = None, n_prev: int | None = None) -> str | None:
    """시도 실행 전 상한 판정(C2-D-21) → 'elems' | 'memory' | 'time' | None. 누적 시간이 refine.total_timeout_s 이상이면
    n_est 와 무관하게 'time'. n_est 가 없으면(넓이 모름 — cad 시간 초과·크래시) 요소·메모리·시간 외삽 판정은 생략합니다
    (시도 제한 시간이 남은 예산으로 줄어 총 시간은 예산 안 — ``attempt_timeout``)."""
    rc = _rcfg(cfg)
    n = attempt.get("n_est")
    if elapsed_s is not None and remaining_s(cfg, elapsed_s) <= 0:
        return "time"
    if n is None:
        return None
    if n > int(rc["max_elems"]):
        return "elems"
    margin = float((cfg.get("run") or {}).get("memory_margin", 0.7))
    b = attempt.get("bytes_est")
    if b is None:
        b = attempt["bytes_est"] = _bytes_est(n, avail_bytes, margin)
    if avail_bytes and b > float(avail_bytes) * margin:
        return "memory"
    if elapsed_s is not None and t_prev and n_prev:
        if float(elapsed_s) + float(t_prev) * (float(n) / float(n_prev)) > float(rc["total_timeout_s"]):
            return "time"
    return None


def remaining_s(cfg: dict, elapsed_s: float | None) -> float:
    """형상 1개 사다리의 남은 시간 예산(refine.total_timeout_s − 누적, 음수 가능)."""
    return float(_rcfg(cfg)["total_timeout_s"]) - float(elapsed_s or 0.0)


def attempt_timeout(base_s: float, cfg: dict, elapsed_s: float | None) -> float:
    """시도 1회 제한 시간 = min(단계 기본 제한 시간, 남은 예산)(C2-D-21, v0.16.0 수정)."""
    return max(0.0, min(float(base_s), remaining_s(cfg, elapsed_s)))


# ---------------------------------------------------------------- 직전 시도
def read_attempt(out_dir: str) -> dict:
    """시도 폴더 → mesh.json(성공·품질 실패) 또는 mesh_error.json(실패) 내용. 둘 다 없으면 {}."""
    from esl.doe import mesh_gmsh as mg
    from esl.library import _util as U
    for name in (mg.MESH_JSON, mg.MESH_ERROR):
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            return dict(U.read_json(p))
    return {}


def failed_faces(meta: dict | None) -> list[dict]:
    """직전 시도의 실패 면 [{key, type, center, id, local_area_mm2?}] — meta.faces(워커 누적) → meta.face(mesh_error.json)
    → meta.errors[].face 순. bbox 키가 같은 면은 한 번만."""
    m = meta or {}
    src = list(m.get("faces") or [])
    if m.get("face"):
        src.append(m["face"])
    src += [e["face"] for e in (m.get("errors") or []) if isinstance(e, dict) and e.get("face")]
    out, seen = [], set()
    for f in src:
        if not isinstance(f, dict) or f.get("key") is None:
            continue
        k = _key(f["key"])
        if k in seen:
            continue
        seen.add(k)
        out.append({**f, "key": list(k)})
    return out


def _calib(meta: dict, rc: dict) -> float:
    """elem_per_h2 보정: 직전 메타에 실측(n_elems·넓이·h)이 있으면 그 비, 없으면 설정값."""
    g = meta.get("geom") or {}
    try:
        n, A, h = int(meta["n_elems"]), float(g["area_mm2"]), float(meta["h"])
        if n > 0 and A > 0 and h > 0:
            return n * h * h / A
    except (KeyError, TypeError, ValueError):
        pass
    return float(rc["elem_per_h2"])


def plan(stage: str, prev_meta: dict | None, h: float, cfg: dict, avail_bytes: int | None, *,
         elapsed_s: float | None = None) -> list[dict]:
    """한 사다리 단계의 시도 목록(C2-D-19~21). prev_meta = 직전 시도 기록(``read_attempt`` + 워커 누적 ``faces``·
    ``geom``·``seconds``/``wall_seconds``·``n_est``). 건너뛰는 시도도 목록에 남김(skipped·reason — 워커가 info 기록).
    refine.enabled false 면 세분화 단계는 []."""
    if stage not in STAGES:
        raise EslError("INPUT_INVALID", f"알 수 없는 사다리 단계 {stage!r}")
    h = float(h)
    base = {"stage": stage, "kind": None, "factor": None, "h_mm": h, "mesh_h": h, "base_h_mm": h, "n_est": None,
            "bytes_est": None, "skipped": False, "reason": None}
    if stage in ("cad", "remesh"):
        return [base]
    if stage == "defeature":                                # v0.16.1 §5A.1: 기본 h 그대로, 형상만 단순화
        from esl.geom import defeature as gdf
        crit = gdf.criteria(((cfg.get("compare") or {}).get("defeature")) or {}, h)
        pm = dict(prev_meta or {})
        area = (pm.get("geom") or {}).get("area_mm2")
        rc = _rcfg(cfg)
        n = estimate_elems(area, h, elem_per_h2=_calib(pm, rc)) if area else None
        a1 = dict(base, n_est=n, compound=bool(crit["compound"]))
        out = [a1]
        if crit["compound"] and ({"fillet", "narrow"} & set(crit["kinds"])):
            out.append(dict(base, n_est=n, compound=False, only_if="compound_failed"))
        el = float(elapsed_s) if elapsed_s is not None else None
        for a in out:
            why = check_limits(a, cfg, avail_bytes, el, pm.get("wall_seconds", pm.get("seconds")), pm.get("n_est"))
            if why:
                a.update(skipped=True, reason=why, info=SKIP_INFO)
        return out
    rc = _rcfg(cfg)
    if not rc.get("enabled", True):
        return []
    pm = dict(prev_meta or {})
    area = (pm.get("geom") or {}).get("area_mm2")
    e = _calib(pm, rc)
    t_prev = pm.get("wall_seconds", pm.get("seconds"))
    n_prev = pm.get("n_est") or pm.get("n_elems") or (estimate_elems(area, h, elem_per_h2=e) if area else None)
    floor = float(rc["min_size_mm"])
    out: list[dict] = []
    if stage == "refine_local":
        lc = rc["local"]
        faces = failed_faces(pm)[:max(1, int(lc["max_faces"]))]
        if not faces:
            return [dict(base, kind="local", skipped=True, reason="no_face", info=NO_FACE_INFO)]
        rings = int(lc["neighbor_rings"])
        la = [f.get("local_area_mm2") for f in faces]
        if all(a is not None for a in la):
            a_loc = float(sum(la))
        else:
            gl = (pm.get("geom") or {}).get("local_area_mm2")
            a_loc = float(gl) if gl is not None and len(faces) == 1 else None
        seen: set = set()
        for f in lc["factors"]:
            hl = max(float(f) * h, floor)
            if hl >= h or round(hl, 9) in seen:
                continue
            seen.add(round(hl, 9))
            n = estimate_elems(area, h, a_loc, hl, elem_per_h2=e) if (area is not None and a_loc is not None) else None
            out.append(dict(base, kind="local", factor=float(f), h_mm=hl, n_est=n,
                            size_fields=[{"keys": [f_["key"] for f_ in faces], "size_mm": hl, "rings": rings}],
                            faces=[{k: f_.get(k) for k in ("key", "type", "center", "id")} for f_ in faces],
                            max_elems=int(rc["max_elems"])))
    else:
        seen = set()
        for g in rc["global"]["factors"]:
            hg = max(float(g) * h, floor)                       # 하한 = refine.min_size_mm(세분화 시도는 check_h 하한도 이 값)
            if hg >= h or round(hg, 9) in seen:
                continue
            seen.add(round(hg, 9))
            n = estimate_elems(area, hg, elem_per_h2=e) if area is not None else None
            out.append(dict(base, kind="global", factor=float(g), h_mm=hg, mesh_h=hg, n_est=n,
                            max_elems=int(rc["max_elems"])))
    el = float(elapsed_s) if elapsed_s is not None else None
    for a in out:
        why = check_limits(a, cfg, avail_bytes, el, t_prev, n_prev)
        if why:
            a.update(skipped=True, reason=why, info=SKIP_INFO)
    return out


def attempt_cfg(cfg: dict, attempt: dict) -> dict:
    """시도에 넘길 cfg 사본(원 cfg 불변): size_fields 가 있으면 mesh.size_fields, 세분화면 mesh.max_elems = refine 상한."""
    out = dict(cfg)
    mc = dict(cfg["mesh"])
    if attempt.get("size_fields"):
        mc["size_fields"] = copy.deepcopy(attempt["size_fields"])
    else:
        mc.pop("size_fields", None)
    if attempt.get("stage") == "defeature":                 # v0.16.1: 이 키가 있을 때만 세션이 defeature 단계(다른 단계 바이트 불변)
        from esl.geom import defeature as gdf
        mc["defeature_stage"] = {"crit": gdf.criteria(((cfg.get("compare") or {}).get("defeature")) or {},
                                                      float(attempt.get("mesh_h") or attempt.get("h_mm"))),
                                 "compound": bool(attempt.get("compound", True))}
    else:
        mc.pop("defeature_stage", None)
    if attempt.get("stage") in REFINE_STAGES:
        if attempt.get("max_elems") is not None:
            mc["max_elems"] = int(attempt["max_elems"])
        # 세분화 시도만 check_h 하한 = refine.min_size_mm(기본 mesh.size_min_mm 1.0 > 0.5 — 0.5~1.0 mm h 허용)
        mc["size_min_mm"] = min(float(mc["size_min_mm"]), float(_rcfg(cfg)["min_size_mm"]))
    out["mesh"] = mc
    return out


# ---------------------------------------------------------------- gmsh 세션 안
def _face_rec(gmsh, t: int, ring: int) -> dict:
    from esl.doe.mesh_gmsh import _bbox_key
    bb = gmsh.model.getBoundingBox(2, t)
    try:
        area = round(float(gmsh.model.occ.getMass(2, t)), 6)
    except Exception:                                       # noqa: BLE001 - OCC 아닌 면
        area = None
    return {"tag": int(t), "ring": int(ring), "key": list(_bbox_key(gmsh, 2, t)), "type": str(gmsh.model.getType(2, t)),
            "center": [round(0.5 * (float(bb[i]) + float(bb[i + 3])), 3) for i in range(3)], "area": area}


def neighbor_faces(gmsh, keys, rings: int) -> list[dict]:
    """bbox 키 면(같은 키 — 없으면 그 키 bbox 를 품는 가장 작은 면: 형상 폴백 조각의 키) + 곡선을 공유하는 이웃 rings 고리.
    반환 [{tag, ring, key, type, center, area}] (ring 0 = 키 면, 태그 순 — 결정적)."""
    from esl.doe.mesh_gmsh import _bbox_key, _key_in, _key_near
    ents = [int(t) for _d, t in gmsh.model.getEntities(2)]
    bbs = {t: _bbox_key(gmsh, 2, t) for t in ents}
    ring_of: dict[int, int] = {}
    for k in keys:
        k = _key(k)
        hit = [t for t in ents if _key_near(bbs[t], k)]
        if not hit:
            cont = [t for t in ents if _key_in(k, bbs[t])]
            if cont:
                vol = {t: sum(bbs[t][i + 3] - bbs[t][i] for i in range(3)) for t in cont}
                hit = [min(cont, key=lambda t: (vol[t], t))]
        for t in hit:
            ring_of.setdefault(t, 0)
    front = sorted(ring_of)
    for r in range(1, max(0, int(rings)) + 1):
        nxt = set()
        for s in front:
            for _d, c in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False):
                up, _dn = gmsh.model.getAdjacencies(1, abs(int(c)))
                nxt |= {int(u) for u in up if int(u) not in ring_of}
        for t in sorted(nxt):
            ring_of[t] = r
        front = sorted(nxt)
    return [_face_rec(gmsh, t, ring_of[t]) for t in sorted(ring_of)]


def geom_summary(src: str, mc: dict, keys, rings: int) -> dict:
    """STEP 을 메싱과 같은 가져오기 옵션(OCCSewFaces·OCCFix*)으로 읽은 {area_mm2, n_faces, local_area_mm2, local_faces}.
    gmsh 를 쓰므로 spawn 자식 안에서만 부른다(``mesh_gmsh._fail_info``)."""
    import gmsh

    from esl.doe import mesh_gmsh as mg
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
        for k, v in mg.geometry_options(mc).items():
            gmsh.option.setNumber(k, v)
        gmsh.model.occ.importShapes(os.fspath(src))
        gmsh.model.occ.synchronize()
        ents = [int(t) for _d, t in gmsh.model.getEntities(2)]
        A = float(sum(gmsh.model.occ.getMass(2, t) for t in ents))
        loc = neighbor_faces(gmsh, list(keys), rings) if keys else []
        return {"area_mm2": round(A, 6), "n_faces": len(ents),
                "local_area_mm2": round(float(sum(f["area"] or 0.0 for f in loc)), 6) if loc else None,
                "local_faces": len(loc)}
    finally:
        gmsh.finalize()


def compound_failed(meta: dict | None) -> bool:
    """defeature 첫 시도 실패 면(mesh_error.json face.key)이 그 시도의 compound 묶음 면인가(§5A.1 2번째 시도 조건)."""
    from esl.doe.mesh_gmsh import _key_near
    m = meta or {}
    ks = [tuple(float(v) for v in k) for k in (m.get("compound_keys") or [])]
    f = (m.get("face") or {}).get("key")
    if not ks:
        return False
    if f is None:                                           # 면을 특정 못 한 실패(compound 재매개변수화 등) = compound 탓으로 봄
        return True
    return any(_key_near(tuple(float(v) for v in f), k, 1e-3) for k in ks)
