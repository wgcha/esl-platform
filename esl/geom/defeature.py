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
            "base_face": int(s), "key": tuple(round(v, 6) for v in bb),
            "center": [round(0.5 * (bb[i] + bb[i + 3]), 6) for i in range(3)], "size": {"d_mm": round(d, 6)},
            "area_mm2": round(float(area), 6), "action": "suppressed"}
