"""CAD(OCC) 단계 작은 형상 인식·억제 공통 모듈 (계약 docs/contracts/esl_select_relax.md §5B.1, SR-D-17~22, v0.16.1).

gmsh 모듈을 인자로 받고 **현재 gmsh 세션** 안에서만 동작한다(초기화·종료는 호출자). 설정 dict 는 호출자가 넘긴다
(DEFAULTS 직접 참조는 ``criteria`` 의 기본값 채움만).

- 위상 도우미(``loop_length``·``face_loops``·``curve_points``·``seam_points``·``is_hole``·``bbox_key``·``key_near``) =
  v0.16.0 ``mesh_gmsh`` 의 ``_이름`` 본문 그대로(``mesh_gmsh`` 는 같은 ``_이름`` 으로 재노출).
- ``holes`` = v0.14.1 ``mesh_gmsh.defeature`` 본문 그대로(④ cad 단계·재메시 R2). ``collect`` 를 줄 때만 메운 고리 목록을 모음.
- ``criteria``·``find_features``·``suppress``·``reference_tris``·``fidelity_split`` = ④ 사다리 ``defeature`` 단계(§5A).
호출 지점: mesh_gmsh 세션(③ 베이스라인·③ 안 BREP — ``bead_doe.mesh.defeature`` 가 있을 때만, ④ cad/refine/defeature),
재메시 R2(``mesh_gmsh.defeature`` 래퍼), (예약) STEP 모핑 — ``find_features``.
"""
from __future__ import annotations

import math

import numpy as np

from esl.errors import EslError

KINDS = ("flange", "hole", "slot", "bead", "fillet", "narrow")       # SR-D-17 실행 순서


def loop_length(occ, curves) -> float:
    return float(sum(occ.getMass(1, abs(int(c))) for c in curves))


def face_loops(gmsh, s: int) -> list[list[int]]:
    """면 s 의 경계 곡선을 끝점 공유로 묶은 닫힌 고리들(gmsh getCurveLoops 는 외곽·구멍을 한 고리로 줄 때가 있음)."""
    curves = sorted({abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, s)], oriented=False)})
    parent = {c: c for c in curves}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_pt: dict[int, int] = {}
    for c in curves:
        for _d, p in gmsh.model.getBoundary([(1, c)], oriented=False):
            p = abs(int(p))
            if p in by_pt:
                parent[find(c)] = find(by_pt[p])
            else:
                by_pt[p] = c
    groups: dict[int, list[int]] = {}
    for c in curves:
        groups.setdefault(find(c), []).append(c)
    return [sorted(g) for _k, g in sorted(groups.items())]


def curve_points(gmsh, c: int) -> set[int]:
    """곡선 끝점(닫힌 곡선도 — combined=True 는 시작=끝 점을 지워 빈 목록을 줌)."""
    return {abs(int(p)) for _d, p in gmsh.model.getBoundary([(1, int(c))], combined=False, oriented=False)}


def seam_points(gmsh, s: int) -> set[int]:
    """면 s 의 seam(같은 면 경계에 두 번 나오는 곡선 — 원통·원뿔·토러스 등 periodic 면의 이음선) 끝점 태그.
    ``getBoundary(combined=True)`` 는 seam 을 지워 periodic 면의 양 끝 고리가 따로 떨어진 고리처럼 보인다(v0.14.1)."""
    seen: dict[int, int] = {}
    for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False):
        seen[abs(int(t))] = seen.get(abs(int(t)), 0) + 1
    pts: set[int] = set()
    for c, n in seen.items():
        if n >= 2:
            pts |= curve_points(gmsh, c)
    return pts


def is_hole(gmsh, s: int, cl: list[int], seam_pts: set[int]) -> bool:
    """고리 cl 이 면 s 의 '구멍'인가(v0.14.1 — 이슈 #53 ④ periodic 면 메싱 실패 원인 수정):
    (a) 모든 곡선이 자유 모서리(이 면에만 붙음 — 이웃 면과 공유하면 구멍이 아니라 보스·버링 벽 같은 이음부) 이고
    (b) seam 끝점을 지나지 않음(periodic 면을 한 바퀴 감는 끝 고리 — 원통 끝 원 — 는 구멍이 아님)."""
    for c in cl:
        up, _down = gmsh.model.getAdjacencies(1, abs(int(c)))
        if any(int(f) != int(s) for f in up):
            return False
        if seam_pts and seam_pts & curve_points(gmsh, abs(int(c))):
            return False
    return True


def bbox_key(gmsh, dim: int, tag: int) -> tuple:
    """세션이 바뀌어도 같은 면을 찾는 열쇠(bbox 6값, 1e-6 mm 반올림) — 태그는 형상 처리 결과에 따라 바뀔 수 있음."""
    return tuple(round(float(v), 6) for v in gmsh.model.getBoundingBox(dim, tag))


def _bump(out: dict, k: str) -> None:
    """선택 집계(0 이면 키 자체를 두지 않음 — 정상 STEP 의 mesh.json 바이트 불변)."""
    out[k] = int(out.get(k) or 0) + 1


def key_near(a: tuple, b: tuple, tol: float = 1e-4) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def holes(gmsh, df: dict, h: float, skip_keys: tuple = (), *, collect: list | None = None) -> dict:
    """④ 작은 형상 처리(이슈 #53 BatchMesher holes table 근사, esl_step_compare.md SC-D-5 보강) — 가져온 OCC 형상에서:

    - 면의 내부 경계(구멍) 중 면적 < ``min_hole_area_mm2``(기본 π·4² — r<4 원형·eq_diam<8·좁은 슬롯) → 같은 경계로 막는 면을
      평면 면은 외곽·큰 구멍 고리로 다시 만들어 작은 구멍 내부 wire 를 지움(곡면은 막는 면을 fragment 로 붙임 —
      경계 모서리는 남음). OCP ShapeUpgrade_RemoveInternalWires 와 같은 결과를
      gmsh API 만으로(OCP 불필요).
    - 남은 구멍(원형 가정 r = 둘레/2π) 반지름 ``hole_r_mm`` 범위 → 둘레 분할 수 = max(hole_elems, ceil(P/h)) transfinite 곡선
      (v0.14.0 수정: 예전 min(hole_elems 6, …) 은 큰 구멍 둘레 모서리가 P/6 으로 길어져 품질 max_length Fail — 이제 구멍
      모서리 ≤ h, 작은 구멍은 최소 hole_elems 분할). hole_elems 0 이면 생략.
    실패는 형상 처리만 건너뛰고 경고(DEFEATURE_SKIPPED). 반환 {filled, filled_area_max, hole_sized, skipped, warnings}."""
    occ = gmsh.model.occ
    amin = float(df.get("min_hole_area_mm2") or 0.0)
    out = {"filled": 0, "filled_area_max": None, "hole_sized": 0, "skipped": 0, "warnings": []}
    try:
        surfs = [t for _d, t in occ.getEntities(2)]
        patches, rebuilt = [], []
        for s in surfs:
            loops = face_loops(gmsh, s)
            if len(loops) <= 1:
                continue
            if skip_keys and any(key_near(bbox_key(gmsh, 2, s), k) for k in skip_keys):
                _bump(out, "relaxed")                    # 폴백 제약 해제 면: 형상 처리 안 함
                continue
            seam = seam_points(gmsh, s)
            per = [loop_length(occ, cl) for cl in loops]
            outer = int(max(range(len(per)), key=lambda i: per[i]))
            small, keep = [], [loops[outer]]
            staged: list = []
            for i, cl in enumerate(loops):
                if i == outer:
                    continue
                if not is_hole(gmsh, s, cl, seam):      # v0.14.1: 이음부·periodic 끝 고리는 구멍 아님(그대로 둠)
                    keep.append(cl)
                    _bump(out, "not_hole")
                    continue
                try:
                    w = occ.addCurveLoop([int(c) for c in cl])
                    try:
                        pt = occ.addPlaneSurface([w])
                    except Exception:                    # noqa: BLE001 - 평면 아님 → 채움 면
                        pt = occ.addSurfaceFilling(w)
                    a = float(occ.getMass(2, pt))
                except Exception:                        # noqa: BLE001
                    out["skipped"] += 1
                    keep.append(cl)
                    continue
                if a < amin and skip_keys and any(key_near(tuple(round(float(v), 6) for v in occ.getBoundingBox(2, pt)), k)
                                                  for k in skip_keys):
                    _bump(out, "relaxed")                # 폴백 제약 해제: 이 막는 면이 실패한 면 → 메우지 않음
                    keep.append(cl)
                    occ.remove([(2, pt)])
                elif a < amin:
                    small.append((cl, pt))
                    out["filled_area_max"] = max(a, out["filled_area_max"] or 0.0)
                    if collect is not None:              # v0.16.1 defeature 단계 목록(None 이면 동작·반환 불변)
                        staged.append(_hole_feat(gmsh, occ, cl, pt, a, s))
                else:
                    keep.append(cl)
                    occ.remove([(2, pt)])
            if not small:
                continue
            if gmsh.model.getType(2, s) == "Plane":
                # 평면 면: 외곽 + 큰 구멍 고리만으로 다시 만든다(작은 구멍 내부 wire 삭제 — ShapeUpgrade_RemoveInternalWires 와 같음)
                for _cl, pt in small:
                    occ.remove([(2, pt)])
                occ.remove([(2, s)])
                occ.addPlaneSurface([occ.addCurveLoop([int(c) for c in cl]) for cl in keep], s)
                rebuilt += [int(c) for cl, _pt in small for c in cl]
            else:                                        # 곡면: 막는 면을 붙임(구멍 경계 모서리는 남음)
                patches += [pt for _cl, pt in small]
            out["filled"] += len(small)
            if collect is not None:
                collect.extend(staged)
        if patches:
            occ.fragment([(2, s) for _d, s in occ.getEntities(2) if s not in patches], [(2, p) for p in patches])
        if rebuilt:
            occ.remove([(1, c) for c in sorted(set(rebuilt))], recursive=True)
        occ.synchronize()
        n_el = int(df.get("hole_elems") or 0)
        r_lo, r_hi = [float(x) for x in (df.get("hole_r_mm") or [4.0, 30.0])]
        done: set[int] = set()
        relaxed = {s for _d, s in occ.getEntities(2)
                   if skip_keys and any(key_near(bbox_key(gmsh, 2, s), k) for k in skip_keys)}
        if n_el > 0:
            for _d, s in occ.getEntities(2):
                loops = face_loops(gmsh, s)
                if len(loops) <= 1 or s in relaxed:
                    continue
                seam = seam_points(gmsh, s)
                per = [loop_length(occ, cl) for cl in loops]
                outer = int(max(range(len(per)), key=lambda i: per[i]))
                for i, cl in enumerate(loops):
                    cs = [abs(int(c)) for c in cl]
                    if i == outer or any(c in done for c in cs):
                        continue
                    if not is_hole(gmsh, s, cl, seam):  # v0.14.1: 이음부·periodic 끝 고리는 분할 강제 안 함
                        continue
                    P = per[i]
                    r = P / (2 * math.pi)
                    if not r_lo <= r <= r_hi:
                        continue
                    n = max(n_el, int(math.ceil(P / h - 1e-9)))       # 모서리 ≤ h, 최소 hole_elems 분할
                    for c in cs:
                        L = float(occ.getMass(1, c))
                        gmsh.model.mesh.setTransfiniteCurve(c, max(2, int(round(n * L / P)) + 1))
                        done.add(c)
                    out["hole_sized"] += 1
    except Exception as exc:                             # noqa: BLE001 - 형상 처리 실패는 메싱을 막지 않음
        out["warnings"].append(f"DEFEATURE_SKIPPED: 작은 형상 처리 실패 — {exc}")
        try:
            occ.synchronize()
        except Exception:                                # noqa: BLE001
            pass
    return out


def _hole_feat(gmsh, occ, cl: list, pt: int, area: float, s: int) -> dict:
    """holes() 가 메운 고리 1개 → 특징 dict(kind hole, method holes_v0141). 막는 면 pt 가 아직 있을 때 부른다."""
    bb = [float(v) for v in occ.getBoundingBox(2, pt)]
    P = loop_length(occ, cl)
    d = 4.0 * float(area) / P if P > 0 else 0.0
    return {"kind": "hole", "method": "holes_v0141", "faces": [int(s)], "curves": sorted(abs(int(c)) for c in cl),
            "base_face": int(s), "key": tuple(round(v, 6) for v in bb), "bbox": [round(v, 6) for v in bb],   # bbox = 억제 영역 Ω_f
            "center": [round(0.5 * (bb[i] + bb[i + 3]), 6) for i in range(3)], "size": {"d_mm": round(d, 6)},
            "area_mm2": round(float(area), 6), "action": "suppressed"}


# ====================================================================== v0.16.1 ④ defeature 단계 (§5A, SR-D-17~21)
LE_TOL = 1e-6                     # '≤ 기준' 비교 여유(mm — OCC bbox·곡률의 부동소수 잡음, 경계값이 정확히 기준이면 포함)
FILLET_TYPES = ("Cylinder", "Torus", "BSpline surface", "Bezier surface")   # gmsh getType 이름(BSpline = 필렛 근사 면)
CRIT_KEYS = ("kinds", "hole_max_d_mm", "slot_max_w_mm", "slot_max_l_mm", "flange_max_h_mm", "min_bead_height_mm",
             "fillet_max_r_mm", "narrow_w_factor", "feature_max_mm", "plane_tol_mm", "compound", "region_pad_factor",
             "max_features", "list_max")


def criteria(df: dict, h: float) -> dict:
    """compare.defeature(+ DEFAULTS 기본값) → 절대 기준 {kinds, hole_max_d, slot_max_w, slot_max_l, flange_max_h, bead_min_h,
    fillet_max_r, narrow_w (= narrow_w_factor·h), feature_max, plane_tol, region_pad (= region_pad_factor·h), max_features,
    list_max, compound}. 검증 실패 → EslError CONFIG_INVALID."""
    from esl.doe import DEFAULTS
    d = dict(DEFAULTS["compare"]["defeature"])
    d.update({k: v for k, v in (df or {}).items() if v is not None})
    kinds = d.get("kinds")
    if not isinstance(kinds, (list, tuple)) or len(set(kinds)) != len(kinds) or any(k not in KINDS for k in kinds):
        raise EslError("CONFIG_INVALID", f"compare.defeature.kinds {kinds!r} — {list(KINDS)} 중 중복 없이")
    try:
        out = {"kinds": tuple(kinds),
               "hole_max_d": float(d["hole_max_d_mm"]), "slot_max_w": float(d["slot_max_w_mm"]),
               "slot_max_l": float(d["slot_max_l_mm"]), "flange_max_h": float(d["flange_max_h_mm"]),
               "bead_min_h": float(d["min_bead_height_mm"]), "fillet_max_r": float(d["fillet_max_r_mm"]),
               "narrow_w": float(d["narrow_w_factor"]) * float(h), "feature_max": float(d["feature_max_mm"]),
               "plane_tol": float(d["plane_tol_mm"]), "region_pad": float(d["region_pad_factor"]) * float(h),
               "max_features": int(d["max_features"]), "list_max": int(d["list_max"]), "compound": bool(d["compound"])}
    except (KeyError, TypeError, ValueError) as exc:
        raise EslError("CONFIG_INVALID", f"compare.defeature 값 오류: {exc}") from None
    pos = ("hole_max_d", "slot_max_w", "slot_max_l", "flange_max_h", "bead_min_h", "fillet_max_r", "narrow_w",
           "feature_max", "plane_tol")
    if any(out[k] <= 0 for k in pos) or out["region_pad"] < 0 or out["max_features"] < 1 or out["list_max"] < 1 \
            or not 0 < float(d["narrow_w_factor"]) <= 1:
        raise EslError("CONFIG_INVALID", "compare.defeature: *_mm > 0, narrow_w_factor (0, 1], region_pad_factor ≥ 0, "
                                         "max_features·list_max ≥ 1")
    return out


def _curve_pts(gmsh, c: int, n: int = 16) -> np.ndarray:
    """곡선 c 위 n+1 점(매개 등분, 방향 = 곡선 자체)."""
    lo, hi = gmsh.model.getParametrizationBounds(1, int(c))
    t = np.linspace(float(lo[0]), float(hi[0]), n + 1)
    return np.asarray(gmsh.model.getValue(1, int(c), t.tolist()), dtype=np.float64).reshape(-1, 3)


def _loop_points(gmsh, curves: list[int]) -> np.ndarray:
    return np.vstack([_curve_pts(gmsh, c) for c in curves]) if curves else np.zeros((0, 3))


def _plane_fit(P: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """최소제곱 평면 (중심, 법선, 최대 거리)."""
    c = P.mean(axis=0)
    if P.shape[0] < 3:
        return c, np.array([0.0, 0.0, 1.0]), 0.0
    _u, _s, vt = np.linalg.svd(P - c, full_matrices=False)
    n = vt[-1] / np.linalg.norm(vt[-1])
    return c, n, float(np.max(np.abs((P - c) @ n)))


def _newell_area(gmsh, curves: list[int]) -> float:
    """닫힌 고리 투영 넓이(Newell): 곡선마다 점열을 끝점으로 이어 붙여 다각형 — 곡선 방향이 섞여도 쓰도록 사슬로 정렬."""
    segs = [_curve_pts(gmsh, c, 64) for c in curves]          # 64 등분: 원 구멍 d_eq = 4A/P 오차 < 0.1 %
    if not segs:
        return 0.0
    chain = [segs.pop(0)]
    while segs:
        end = chain[-1][-1]
        k = int(np.argmin([min(np.linalg.norm(s[0] - end), np.linalg.norm(s[-1] - end)) for s in segs]))
        s = segs.pop(k)
        chain.append(s if np.linalg.norm(s[0] - end) <= np.linalg.norm(s[-1] - end) else s[::-1])
    P = np.vstack(chain)
    nv = 0.5 * np.cross(P, np.roll(P, -1, axis=0)).sum(axis=0)
    return float(np.linalg.norm(nv))


def _rect_wl(P: float, A: float) -> tuple[float | None, float | None]:
    """사각 근사 t² − (P/2)t + A = 0 의 두 근(작은 = 폭, 큰 = 길이). 실근 없음(원에 가까움) → (None, None)."""
    b = P / 2.0
    disc = b * b - 4.0 * A
    if disc < 0:
        return None, None
    r = math.sqrt(disc)
    return (b - r) / 2.0, (b + r) / 2.0


def _bbox(gmsh, dim: int, tags) -> list[float]:
    bbs = np.asarray([gmsh.model.getBoundingBox(dim, int(t)) for t in tags], dtype=np.float64).reshape(-1, 6)
    return [float(v) for v in np.concatenate([bbs[:, :3].min(axis=0), bbs[:, 3:].max(axis=0)])]


def _diag(bb) -> float:
    return float(np.linalg.norm(np.asarray(bb[3:]) - np.asarray(bb[:3])))


def _topology(gmsh) -> dict:
    """면·곡선 인접(결정적 — 태그 오름차순)."""
    faces = sorted(int(t) for _d, t in gmsh.model.getEntities(2))
    fc, inner = {}, set()
    for s in faces:
        cnt: dict[int, int] = {}
        for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False):
            cnt[abs(int(t))] = cnt.get(abs(int(t)), 0) + 1
        fc[s] = sorted(cnt)
        inner |= {c for c, n in cnt.items() if n >= 2}      # seam(같은 면 경계에 두 번) = 면 안쪽 이음선
    occ = gmsh.model.occ
    for c in {c for cs in fc.values() for c in cs}:
        try:
            if float(occ.getMass(1, c)) <= 1e-9:            # 퇴화 곡선(구 극점) — 경계 아님
                inner.add(c)
        except Exception:                                 # noqa: BLE001
            inner.add(c)
    cf: dict[int, list[int]] = {}
    for s, cs in fc.items():
        for c in cs:
            cf.setdefault(c, [])
            if s not in cf[c]:
                cf[c].append(s)
    for c in cf:
        cf[c].sort()
    return {"faces": faces, "fc": fc, "cf": cf, "inner": inner}


def _free_loops(gmsh, topo: dict, faces: list[int] | None = None) -> list[list[int]]:
    """자유 곡선(인접 면 1개)을 끝점 공유로 이은 닫힌 고리들(면 경계에 묶지 않음 — seam·여러 면 통과 허용).
    faces 를 주면 그 면 묶음 안에서만 '자유'(묶음 밖 면과 공유하지 않음)를 셈."""
    fs = set(topo["faces"] if faces is None else faces)
    inner = topo.get("inner") or set()
    free = sorted(c for c, ss in topo["cf"].items() if len([s for s in ss if s in fs]) == 1 and c not in inner)
    parent = {c: c for c in free}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_pt: dict[int, int] = {}
    for c in free:
        for p in sorted(curve_points(gmsh, c)):
            if p in by_pt:
                ra, rb = find(c), find(by_pt[p])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            else:
                by_pt[p] = c
    groups: dict[int, list[int]] = {}
    for c in free:
        groups.setdefault(find(c), []).append(c)
    return [sorted(g) for _k, g in sorted(groups.items())]


def _components(topo: dict) -> dict[int, int]:
    """면 → 연결 쉘 성분 번호(곡선 공유, 최소 면 태그 순)."""
    comp: dict[int, int] = {}
    k = 0
    for s in topo["faces"]:
        if s in comp:
            continue
        stack = [s]
        comp[s] = k
        while stack:
            f = stack.pop()
            for c in topo["fc"][f]:
                for g in topo["cf"][c]:
                    if g not in comp:
                        comp[g] = k
                        stack.append(g)
        k += 1
    return comp


def _feat(gmsh, kind: str, faces: list[int], curves: list[int], base: int | None, size: dict, area: float) -> dict:
    tags = faces if faces else []
    bb = _bbox(gmsh, 2, tags) if tags else _bbox(gmsh, 1, curves)
    return {"kind": kind, "faces": sorted(int(f) for f in faces), "curves": sorted(int(c) for c in curves),
            "base_face": None if base is None else int(base), "key": tuple(round(v, 6) for v in bb),
            "bbox": [round(v, 6) for v in bb], "center": [round(0.5 * (bb[i] + bb[i + 3]), 6) for i in range(3)],
            "size": {k: round(float(v), 6) for k, v in size.items()}, "area_mm2": round(float(area), 6)}


def _height(gmsh, faces: list[int], L_pts: np.ndarray) -> float:
    """C 각 면 bbox 8 꼭짓점을 고리 L 최소제곱 평면 법선에 투영한 거리 최대(§5A.3 위쪽 근사)."""
    c, n, _ = _plane_fit(L_pts)
    h = 0.0
    for f in faces:
        b = gmsh.model.getBoundingBox(2, int(f))
        for i in range(8):
            p = np.array([b[0] if i & 1 == 0 else b[3], b[1] if i & 2 == 0 else b[4], b[2] if i & 4 == 0 else b[5]])
            h = max(h, abs(float((p - c) @ n)))
    return h


def _attached(gmsh, topo: dict, base: int, L: list[int], fmax: float) -> list[int] | None:
    """고리 L 건너편 면 묶음 C(base 를 지나지 않는 BFS). bbox 대각이 fmax 를 넘으면 즉시 None(비용 상한)."""
    start = sorted({g for c in L for g in topo["cf"].get(c, []) if g != base})
    if not start:
        return None
    seen = set(start)
    stack = list(start)
    while stack:
        f = stack.pop()
        for c in topo["fc"][f]:
            for g in topo["cf"][c]:
                if g != base and g not in seen:
                    seen.add(g)
                    stack.append(g)
        if _diag(_bbox(gmsh, 2, sorted(seen))) > fmax:
            return None
    return sorted(seen)


def _radius(gmsh, s: int) -> float | None:
    """면 매개 중앙 주곡률 → r = 1/max|κ| (곡률 0 이면 None)."""
    try:
        lo, hi = gmsh.model.getParametrizationBounds(2, int(s))
        uv = [0.5 * (float(lo[0]) + float(hi[0])), 0.5 * (float(lo[1]) + float(hi[1]))]
        k1, k2, _d1, _d2 = gmsh.model.getPrincipalCurvatures(int(s), uv)
        k = max(abs(float(k1[0])), abs(float(k2[0])))
        return 1.0 / k if k > 1e-12 else None
    except Exception:                                    # noqa: BLE001
        return None


def _on_planes(gmsh, topo: dict, loop: list[int]) -> bool:
    """자유 고리 곡선의 인접 면이 모두 평면인가(보스 바닥 고리의 구멍 ↔ 원통·원뿔 버링 벽의 관 끝 구분)."""
    fs = {g for c in loop for g in topo["cf"].get(c, [])}
    return bool(fs) and all(str(gmsh.model.getType(2, int(g))) == "Plane" for g in fs)


def find_features(gmsh, crit: dict, *, kinds: tuple[str, ...] | None = None) -> list[dict]:
    """§5A.3 인식만(형상 불변). 특징 = {id, kind, faces, curves, base_face, key(bbox6), bbox, center[3],
    size{d_mm | w_mm,l_mm | h_mm | r_mm}, area_mm2}. 순서 결정적(kind 순서 → 중심 좌표 1e-3 반올림 사전순).
    인식 수 > max_features → 앞에서 자르고 마지막 특징에 표지(호출자가 DEFEATURE_TOO_MANY)."""
    kinds = tuple(kinds if kinds is not None else crit["kinds"])
    topo = _topology(gmsh)
    occ = gmsh.model.occ
    comp = _components(topo)
    feats: list[dict] = []
    used_faces: set[int] = set()
    # flange·bead: 바탕 면 B 의 안쪽 고리 L(이웃 공유) 건너편 묶음 C
    cands = []
    for B in topo["faces"]:
        loops = face_loops(gmsh, B)
        if len(loops) <= 1:
            continue
        seam = seam_points(gmsh, B)
        per = [loop_length(occ, cl) for cl in loops]
        outer = int(max(range(len(per)), key=lambda i: per[i]))
        for i, L in enumerate(loops):
            if i == outer or is_hole(gmsh, B, L, seam):
                continue
            C = _attached(gmsh, topo, B, L, crit["feature_max"])
            if not C:
                continue
            # C 의 자유 고리 = 쉘 전체에서 자유(인접 면 1개)인 C 의 곡선(L 은 B 와 공유 — 제외됨)
            sub = {"faces": C, "fc": {f: topo["fc"][f] for f in C}, "inner": topo["inner"],
                   "cf": {c: topo["cf"][c] for f in C for c in topo["fc"][f] if len(topo["cf"][c]) == 1}}
            fl = _free_loops(gmsh, sub)
            hC = _height(gmsh, C, _loop_points(gmsh, L))
            cands.append((B, L, C, fl, hC))
    cands.sort(key=lambda x: -len(x[2]))
    taken: list[set] = []
    for B, L, C, fl, hC in cands:
        sC = set(C)
        if any(sC <= t for t in taken):                     # 큰 묶음의 일부(필렛 → 구면) = 같은 특징(판정도 큰 묶음 기준)
            continue
        taken.append(sC)
        area = float(sum(occ.getMass(2, f) for f in C))
        if hC <= crit["plane_tol"] and len(fl) <= 1:      # SR-D-41: 높이 0 묶음(바탕 면과 한 평면 — 경계에 걸친 보스의 평평한
            continue                                      # 조각)은 억제해도 형상이 안 바뀜 → 목록 제외(그 안 구멍은 아래 hole 규칙)
        if len(fl) == 1 and "flange" in kinds and hC <= crit["flange_max_h"] + LE_TOL:
            feats.append(_feat(gmsh, "flange", C, L, B, {"h_mm": hC}, area) | {"free_loop": fl[0]})
        elif not fl and "bead" in kinds and hC < crit["bead_min_h"]:
            feats.append(_feat(gmsh, "bead", C, L, B, {"h_mm": hC}, area))
        elif len(fl) == 1 and not _on_planes(gmsh, topo, fl[0]):   # 높은 버링 벽: 끝 자유 고리는 구멍이 아님(관 끝)
            feats.append({"kind": "_wall", "faces": C, "free_loop": fl[0]})
        # (자유 고리가 평면 위 = 보스 바닥 고리의 가운데 구멍 → 보스는 남기고 그 구멍은 아래 hole·slot 규칙으로)
    walls = [f for f in feats if f["kind"] == "_wall"]
    feats = [f for f in feats if f["kind"] != "_wall"]
    for f in feats:
        used_faces |= set(f["faces"])
    skip_loops = {tuple(w["free_loop"]) for w in walls} | {tuple(f["free_loop"]) for f in feats if f.get("free_loop")}
    # hole·slot: 쉘 자유 고리(연결 성분마다 바깥 경계 = |넓이| 최대 제외)
    if "hole" in kinds or "slot" in kinds:
        loops = _free_loops(gmsh, topo)
        rec = []
        for lp in loops:
            if tuple(lp) in skip_loops:
                continue
            P = loop_length(occ, lp)
            A = _newell_area(gmsh, lp)
            f0 = topo["cf"][lp[0]][0]
            rec.append((comp[f0], lp, P, A))
        outer = {}
        for k, lp, P, A in rec:
            if k not in outer or A > outer[k][1]:
                outer[k] = (tuple(lp), A)
        for k, lp, P, A in rec:
            if tuple(lp) == outer[k][0]:
                continue
            d = 4.0 * A / P if P > 0 else 0.0
            w, ln = _rect_wl(P, A)
            if "hole" in kinds and d <= crit["hole_max_d"] + LE_TOL:
                feats.append(_feat(gmsh, "hole", [], lp, topo["cf"][lp[0]][0], {"d_mm": d}, A))
            elif "slot" in kinds and w is not None and w <= crit["slot_max_w"] + LE_TOL and ln <= crit["slot_max_l"] + LE_TOL:
                feats.append(_feat(gmsh, "slot", [], lp, topo["cf"][lp[0]][0], {"w_mm": w, "l_mm": ln}, A))
    # fillet·narrow: 띠 모양 면(두 이웃, 곡선 2개 이상 공유)
    for s in topo["faces"]:
        if s in used_faces:
            continue
        cs = topo["fc"][s]
        if any(len(topo["cf"][c]) == 1 and c not in topo["inner"] for c in cs):   # 자유 고리 포함(구멍·버링 벽) 제외
            continue
        nb = sorted({g for c in cs for g in topo["cf"][c] if g != s})
        shared = [c for c in cs if any(g != s for g in topo["cf"][c])]
        cs = [c for c in cs if c not in topo["inner"]]
        typ = str(gmsh.model.getType(2, s))
        if "fillet" in kinds and len(nb) == 2 and len(shared) >= 2 and typ in FILLET_TYPES:
            r = _radius(gmsh, s)
            if r is not None and r <= crit["fillet_max_r"] + LE_TOL:
                feats.append(_feat(gmsh, "fillet", [s], cs, None, {"r_mm": r}, occ.getMass(2, s)) | {"neighbors": nb})
                continue
        if "narrow" in kinds and nb:
            A = float(occ.getMass(2, s))
            P = float(sum(occ.getMass(1, c) for c in cs))
            w, ln = _rect_wl(P, A)
            if w is not None and w < crit["narrow_w"] and ln > w:
                feats.append(_feat(gmsh, "narrow", [s], cs, None, {"w_mm": w, "l_mm": ln}, A) | {"neighbors": nb})
    order = {k: i for i, k in enumerate(kinds)}
    feats.sort(key=lambda f: (order.get(f["kind"], 99), tuple(round(v, 3) for v in f["center"]), f["curves"]))
    if len(feats) > crit["max_features"]:
        n = len(feats)
        feats = feats[:crit["max_features"]]
        feats[-1]["too_many"] = {"n": n, "max": crit["max_features"]}
    for i, f in enumerate(feats):
        f["id"] = f"f{i + 1:04d}"
    return feats


def _fill_loop(gmsh, curves: list[int], plane_tol: float) -> tuple[int, str]:
    """기존 곡선 고리 → 평면 면(평면 판정 ≤ plane_tol) 또는 채움 면. 반환 (면 태그, method)."""
    occ = gmsh.model.occ
    w = occ.addCurveLoop([int(c) for c in curves])
    _c, _n, dev = _plane_fit(_loop_points(gmsh, curves))
    if dev <= plane_tol:
        try:
            return int(occ.addPlaneSurface([w])), "plane"
        except Exception:                                 # noqa: BLE001 - 평면 아님 → 채움
            pass
    return int(occ.addSurfaceFilling(w)), "filling"


def suppress(gmsh, feats: list[dict], crit: dict, h: float, *, compound: bool = True) -> dict:
    """§5A.4 실행(종류 순서 = crit.kinds). 반환 {features(+action suppressed|skipped, method plane|filling|removed+hole|
    occ_defeature|compound, reason?), counts{kind: n}, n, skipped_n, compound_groups[[tag…]], compound_keys[[bbox6]],
    warnings}. 특징마다 try — 실패하면 그 특징만 skipped(만든 엔티티 제거). occ.synchronize 포함."""
    occ = gmsh.model.occ
    out = {"features": [], "counts": {}, "n": 0, "skipped_n": 0, "compound_groups": [], "compound_keys": [],
           "warnings": []}
    vols = [t for _d, t in occ.getEntities(3)]
    groups: list[set] = []
    order = {k: i for i, k in enumerate(crit["kinds"])}
    for f in sorted(feats, key=lambda x: (order.get(x["kind"], 99), x.get("id", ""))):
        r = dict(f)
        k = f["kind"]
        if f.get("method") == "holes_v0141":
            out["features"].append(r)
            continue
        before = {d: {t for _d, t in occ.getEntities(d)} for d in (1, 2)}
        try:
            if k in ("hole", "slot"):
                _t, m = _fill_loop(gmsh, f["curves"], crit["plane_tol"])
                r["method"] = m
            elif k == "flange":
                occ.remove([(2, int(s)) for s in f["faces"]])
                _t, m = _fill_loop(gmsh, f["curves"], crit["plane_tol"])
                r["method"] = "removed+hole"
            elif k == "bead":
                occ.remove([(2, int(s)) for s in f["faces"]])
                _t, m = _fill_loop(gmsh, f["curves"], crit["plane_tol"])
                r["method"] = m
            elif k in ("fillet", "narrow"):
                if vols:
                    occ.defeature(vols, [int(s) for s in f["faces"]])
                    r["method"] = "occ_defeature"
                elif not compound:
                    r.update(action="skipped", reason="compound_off")
                    out["features"].append(r)
                    out["skipped_n"] += 1
                    continue
                else:
                    nb = f.get("neighbors") or []
                    if k == "fillet":                       # 작은 쪽 이웃 1개(큰 바탕 면은 구멍이 많아 재매개변수화 위험)
                        pick = [min(nb, key=lambda s: (float(occ.getMass(2, s)), s))] if nb else []
                    else:                                   # 가장 긴 공유 곡선 이웃 1개
                        lens = {}
                        for s in nb:
                            cs = {abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, s)], combined=False,
                                                                                    oriented=False)}
                            lens[s] = sum(float(occ.getMass(1, c)) for c in f["curves"] if c in cs)
                        pick = [max(nb, key=lambda s: (lens[s], -s))] if nb else []
                    g = set(int(s) for s in f["faces"]) | set(int(s) for s in pick)
                    for gg in [x for x in groups if x & g]:  # 겹치는 묶음은 합침
                        g |= gg
                        groups.remove(gg)
                    groups.append(g)
                    r["method"] = "compound"
            r["action"] = "suppressed"
            out["counts"][k] = int(out["counts"].get(k, 0)) + 1
            out["n"] += 1
        except Exception as exc:                          # noqa: BLE001 - 한 특징 실패가 단계를 막지 않음
            for d in (2, 1):
                new = sorted({t for _d, t in occ.getEntities(d)} - before[d])
                if new:
                    try:
                        occ.remove([(d, t) for t in new])
                    except Exception:                     # noqa: BLE001
                        pass
            r.update(action="skipped", reason=str(exc)[:200])
            out["skipped_n"] += 1
        out["features"].append(r)
    occ.synchronize()
    if groups:
        live = {int(t) for _d, t in gmsh.model.getEntities(2)}
        for g in sorted(groups, key=lambda x: min(x)):
            tags = sorted(t for t in g if t in live)
            if len(tags) >= 2:
                gmsh.model.mesh.setCompound(2, tags)
                out["compound_groups"].append(tags)
                out["compound_keys"] += [list(bbox_key(gmsh, 2, t)) for t in tags]
    return out


def reference_tris(gmsh, src: str, mc: dict, rc: dict) -> tuple[np.ndarray, np.ndarray]:
    """원 STEP 을 mc 정리 옵션(OCCSewFaces·OCCFix*)으로 현재 세션에 다시 가져와 OCC 삼각화(S0, 노드 병합) —
    mesh_remesh R3·R4 와 같은 함수(코드 1곳). 세션 모델은 지운다(gmsh.clear)."""
    import os

    from esl.doe import mesh_gmsh as mg
    from esl.doe import mesh_remesh as mrm
    gmsh.clear()
    gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
    for k, v in mg.geometry_options(mc).items():
        gmsh.option.setNumber(k, v)
    gmsh.model.occ.importShapes(os.fspath(src))
    gmsh.model.occ.synchronize()
    X0, T0 = mrm.occ_triangulate(gmsh, rc)
    S_X, S_T, _n = mrm.merge_nodes(X0, T0, float(rc["merge_tol_mm"]))
    return S_X, S_T


def _in_boxes(P: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """점별 상자 소속(n, m) 불리언."""
    if not boxes.size:
        return np.zeros((P.shape[0], 0), bool)
    lo, hi = boxes[:, :3], boxes[:, 3:]
    return np.all((P[:, None, :] >= lo[None]) & (P[:, None, :] <= hi[None]), axis=2)


def fidelity_split(S_X, S_T, mesh: dict, h: float, rc: dict, feats: list[dict], pad_mm: float) -> dict:
    """SR-D-19: C2-D-13 ``mesh_remesh.fidelity`` 와 같은 샘플링·k 후보·정확한 점-삼각형 거리, 샘플을 억제 영역
    Ω = ∪ Ω_f(특징 bbox ± pad_mm) 안/밖으로 나눔 → {outside: C2-D-13 지표(바깥 샘플), per_feature: {id: dev_mm},
    suppressed_max_mm}. 특징 dict 에 dev_mm 을 채움(compound·skipped 특징은 Ω 아님)."""
    from esl.doe import mesh_remesh as mrm
    fc = rc["fidelity"]
    smax = int(fc["samples_max"])
    X = np.asarray(mesh["x0"], dtype=np.float64)
    MT = mrm.mesh_tris(X, mesh["conn"], mesh["elem_type"])
    sx, st = mrm.subdivide(np.asarray(S_X, float), np.asarray(S_T, np.int64), float(h),
                           max_tris=max(4 * smax, int(np.asarray(S_T).shape[0])))
    pm = X[mrm._stride(X.shape[0], smax)]
    d_ms = mrm._dist_to_tris(pm, sx, st)
    cen = (sx[st[:, 0]] + sx[st[:, 1]] + sx[st[:, 2]]) / 3.0
    ps = np.concatenate([sx, cen])
    ps = ps[mrm._stride(ps.shape[0], smax)]
    d_sm = mrm._dist_to_tris(ps, X, MT)
    om = [f for f in feats if f.get("action", "suppressed") == "suppressed" and f.get("method") != "compound"
          and f.get("bbox")]
    boxes = np.asarray([[*(np.asarray(f["bbox"][:3]) - pad_mm), *(np.asarray(f["bbox"][3:]) + pad_mm)] for f in om],
                       dtype=np.float64).reshape(-1, 6)
    ia, ib = _in_boxes(pm, boxes), _in_boxes(ps, boxes)
    oa, ob = ~ia.any(axis=1), ~ib.any(axis=1)
    per = {}
    for j, f in enumerate(om):
        v = np.concatenate([d_ms[ia[:, j]], d_sm[ib[:, j]]])
        f["dev_mm"] = round(float(v.max()) if v.size else 0.0, 6)
        per[f["id"]] = f["dev_mm"]
    a, b = d_ms[oa], d_sm[ob]
    allv = np.concatenate([a, b])
    haus = float(max(a.max(initial=0.0), b.max(initial=0.0)))
    warn, chord = mrm.warn_threshold(S_X, S_T, h, rc)      # SR-D-27 cad 메시 편차 대비 상대 경고(절대 warn_mm 이 하한)
    fail = fc.get("fail_mm")
    outside = {"hausdorff_mm": round(haus, 6), "max_dev_mm": round(float(a.max(initial=0.0)), 6),
               "p95_mm": round(float(np.percentile(allv, 95)) if allv.size else 0.0, 6),
               "deflection_mm": float(rc["linear_deflection_mm"]), "samples": int(allv.size), "warn_mm": round(warn, 6),
               "fail_mm": None if fail is None else float(fail), "over_warn": bool(haus > warn)}
    if chord is not None:
        outside["cad_chord_mm"] = chord
    return {"outside": outside, "per_feature": per,
            "suppressed_max_mm": round(max(per.values()), 6) if per else 0.0}


def list_doc(feats: list[dict], list_max: int) -> dict:
    """mesh/defeature.json(SR-D-20) = {schema, n(전체 특징 수), counts{kind: 억제 수}, truncated(bool), features[≤ list_max]}.
    특징 {id, kind, center, bbox, size, area_mm2, faces_n, action, method, reason?, dev_mm}, 결정적 순서 = kind → 중심
    (1e-3 반올림) 사전순."""
    rows = []
    for f in feats:
        r = {"id": f.get("id"), "kind": f["kind"], "center": f.get("center"), "bbox": f.get("bbox"),
             "size": f.get("size"), "area_mm2": f.get("area_mm2"), "faces_n": len(f.get("faces") or []),
             "action": f.get("action", "suppressed"), "method": f.get("method"), "dev_mm": f.get("dev_mm")}
        if f.get("reason"):
            r["reason"] = f["reason"]
        rows.append(r)
    rows.sort(key=lambda r: (r["kind"], tuple(round(float(v), 3) for v in (r["center"] or [0, 0, 0]))))
    counts: dict = {}
    for r in rows:
        if r["action"] == "suppressed":
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"schema": "esl/defeature/1", "n": len(rows), "counts": dict(sorted(counts.items())),
            "truncated": len(rows) > int(list_max), "features": rows[:int(list_max)]}
