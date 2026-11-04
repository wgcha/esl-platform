"""③ gmsh 쉘 메시 (계약 esl_bead_doe.md §7, BD-D-20, V-BD-6).

gmsh 는 Python 모듈로 **코어 하위 프로세스 안에서** 호출한다(외부 명령 아님). ``run_isolated`` 가
``multiprocessing``(spawn) 자식 프로세스를 띄워 타임아웃(``mesh.timeout_s``)·크래시를 격리하고(둘 다 ``FAILED_MESH``),
자식은 표준 출력(OCC 메시지)을 ``mesh.log`` 로 돌린 뒤 ``mesh_file`` 로 실제 메싱을 한다.

절차(§7.1): ``initialize(["-noenv"], readConfigFiles=False)``, Terminal 0, NumThreads 1, OCCSewFaces = mesh.occ_sew_faces(계약 기본 0),
``occ.importShapes`` → synchronize, 크기 MeshSizeMax = h, Min = h × min_size_factor, FromCurvature = curvature_n,
ExtendFromBoundary 1, Algorithm = mesh.algorithm(8), RecombineAll 1, RecombinationAlgorithm 1(blossom),
SubdivisionAlgorithm 0, ElementOrder 1, Smoothing 3, ``generate(2)``.
출력: 노드 1..N(gmsh 태그 순 재번호, 요소가 안 쓰는 노드 제거), 요소 1..E(gmsh 요소 태그 순, CQUAD4/CTRIA3,
면적 ≤ 1e-12·중복 노드 요소 제거), 법선을 기준 n 쪽으로 정렬(``esl.opt.target.align_normals``), PID 1, t·E·ν = props.
``mesh.npz`` 는 zip 날짜를 고정해 같은 입력 → 같은 바이트(단일 스레드 gmsh 결정성).
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
import zipfile

import numpy as np

from esl.errors import EslError

MESH_NPZ = "mesh.npz"
MESH_JSON = "mesh.json"
MESH_LOG = "mesh.log"
_AREA_MIN = 1e-12
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MESH_KEYS = ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu")


def available() -> tuple[bool, str | None]:
    """(gmsh import 가능, 버전)."""
    try:
        import gmsh  # noqa: F401
    except Exception:                                       # noqa: BLE001 - 공유 라이브러리 누락(OSError) 포함
        return False, None
    try:
        return True, str(gmsh.__version__)
    except AttributeError:
        return True, None


def save_npz_det(path: str, arrays: dict) -> str:
    """allow_pickle=False 로 읽히는 npz 를 zip 날짜 고정·키 정렬로 쓴다(바이트 결정성)."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for k in sorted(arrays):
            zi = zipfile.ZipInfo(f"{k}.npy", date_time=_ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with zf.open(zi, "w", force_zip64=True) as fh:
                np.lib.format.write_array(fh, np.ascontiguousarray(arrays[k]), allow_pickle=False)
    os.replace(tmp, path)
    return path


def check_h(h: float, mcfg: dict) -> float:
    h = float(h)
    if not (float(mcfg["size_min_mm"]) <= h <= float(mcfg["size_max_mm"])):
        raise EslError("INPUT_INVALID", f"요소 크기 {h} mm 가 범위 {mcfg['size_min_mm']}..{mcfg['size_max_mm']} 밖")
    return h


def gmsh_options(h: float, mcfg: dict) -> dict:
    """메싱 옵션(가져온 뒤 적용). 선택 키(v0.14.0 ④ 프로필, esl_step_compare.md SC-D-5): ``extend_from_boundary`` 가 있으면
    Mesh.MeshSizeExtendFromBoundary = 그 값(없으면 지금 값 1 — ③ 결과 바이트 불변, V-SC-8)."""
    efb = int(mcfg["extend_from_boundary"]) if mcfg.get("extend_from_boundary") is not None else 1
    return {"Mesh.MeshSizeMax": float(h), "Mesh.MeshSizeMin": float(h) * float(mcfg["min_size_factor"]),
            "Mesh.MeshSizeFromCurvature": int(mcfg["curvature_n"]), "Mesh.MeshSizeExtendFromBoundary": efb,
            "Mesh.Algorithm": int(mcfg["algorithm"]), "Mesh.RecombineAll": 1, "Mesh.RecombinationAlgorithm": 1,
            "Mesh.SubdivisionAlgorithm": 0, "Mesh.ElementOrder": 1, "Mesh.Smoothing": 3}


OCC_FIX_KEYS = ("Geometry.OCCFixDegenerated", "Geometry.OCCFixSmallEdges", "Geometry.OCCFixSmallFaces")


def geometry_options(mcfg: dict) -> dict:
    """가져오기 전 OCC 옵션(선택 키 ``occ_fix_small`` — 1 이면 작은 모서리·면·퇴화 정리 = 1). 키 없음·0 → {}(gmsh 기본, ③ 불변)."""
    v = mcfg.get("occ_fix_small")
    if v is None or not int(v):
        return {}
    return {k: 1 for k in OCC_FIX_KEYS}


def _elem_area(X, conn, et):
    a = np.cross(X[conn[:, 1]] - X[conn[:, 0]], X[conn[:, 2]] - X[conn[:, 0]])
    area = 0.5 * np.linalg.norm(a, axis=1)
    q = et == 4
    if q.any():
        b = np.cross(X[conn[q, 2]] - X[conn[q, 0]], X[conn[q, 3]] - X[conn[q, 0]])
        area[q] += 0.5 * np.linalg.norm(b, axis=1)
    return area


def _extract(gmsh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags, dtype=np.int64)
    X = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    o = np.argsort(tags, kind="stable")
    tags, X = tags[o], X[o]
    etypes, etags, enodes = gmsh.model.mesh.getElements(2)
    rows, et, eg = [], [], []
    for t, tg, nd in zip(etypes, etags, enodes):
        t = int(t)
        if t == 2:
            k = 3
        elif t == 3:
            k = 4
        else:
            raise EslError("FAILED_MESH", f"gmsh 2D 요소 형식 {t} (1차 tri/quad 만)")
        nd = np.asarray(nd, dtype=np.int64).reshape(-1, k)
        c = np.full((nd.shape[0], 4), -1, dtype=np.int64)
        c[:, :k] = nd
        rows.append(c)
        et.append(np.full(nd.shape[0], k, dtype=np.int64))
        eg.append(np.asarray(tg, dtype=np.int64))
    if not rows:
        raise EslError("FAILED_MESH", "gmsh 가 2D 요소를 만들지 못함")
    C, ET, EG = np.concatenate(rows), np.concatenate(et), np.concatenate(eg)
    o = np.argsort(EG, kind="stable")
    C, ET = C[o], ET[o]
    pos = np.searchsorted(tags, np.where(C >= 0, C, tags[0]))
    if np.any(tags[np.minimum(pos, tags.size - 1)][C >= 0] != C[C >= 0]):
        raise EslError("FAILED_MESH", "gmsh 요소가 없는 노드를 참조")
    conn = np.where(C >= 0, pos, -1)
    return X, conn, ET


def build_mesh(X, conn, et, props: dict, normal_ref=None) -> tuple[dict, dict]:
    """정리(퇴화 요소 제거·미사용 노드 제거·재번호)·법선 정렬 → (mesh dict, info)."""
    from esl.library import normalize as nz
    from esl.opt.target import align_normals
    n_in = int(conn.shape[0])
    q = et == 4
    k = np.where(q, 4, 3)
    dup = np.zeros(conn.shape[0], bool)
    for a in range(4):
        for b in range(a + 1, 4):
            use = (b < k)
            dup |= use & (conn[:, a] == conn[:, b])
    area = _elem_area(X, np.where(conn >= 0, conn, conn[:, :1]), et)
    keep = ~dup & (area > _AREA_MIN)
    conn, et = conn[keep], et[keep]
    used = np.unique(conn[conn >= 0])
    remap = -np.ones(X.shape[0], dtype=np.int64)
    remap[used] = np.arange(used.size)
    conn = np.where(conn >= 0, remap[np.maximum(conn, 0)], -1)
    X = X[used]
    ne = int(conn.shape[0])
    mesh = {"node_id": np.arange(1, X.shape[0] + 1, dtype=np.int64), "x0": X,
            "elem_id": np.arange(1, ne + 1, dtype=np.int64), "elem_type": et.astype(np.int8), "conn": conn,
            "elem_pid": np.ones(ne, dtype=np.int64), "thickness": np.full(ne, float(props["t"])),
            "E": np.full(ne, float(props["E"])), "nu": np.full(ne, float(props["nu"]))}
    n = normal_ref
    if n is None:
        n = nz.frame(X, None, conn, et)["n"]
    c2, flip = align_normals(mesh, n)
    mesh["conn"] = c2
    return mesh, {"n_removed_elems": n_in - ne, "n_flipped": int(flip.sum())}


def quality(mesh: dict, cfg: dict, opt_cfg: dict) -> dict:
    """esl.opt.mesh_check 지표 + quad_frac·max_elems → {errors, warnings, metrics, quad_frac}."""
    from esl.opt import mesh_check
    mc = cfg["mesh"]
    et = np.asarray(mesh["elem_type"]).astype(int)
    ne = int(et.size)
    qf = float(np.sum(et == 4)) / ne if ne else 0.0
    if ne > int(mc["max_elems"]):
        return {"errors": [{"code": "MESH_TOO_LARGE", "message": f"요소 {ne} > 상한 {mc['max_elems']}"}],
                "warnings": [], "metrics": {"n_elems": ne}, "quad_frac": qf}
    oc = dict(opt_cfg)
    oc["template"] = dict(opt_cfg["template"], max_elems=int(mc["max_elems"]), max_tria_frac=1.0 - float(mc["min_quad_frac"]))
    r = mesh_check.check(mesh, "S2", oc)
    warns = [w for w in r["warnings"] if w["code"] not in ("NORMALS_ALIGNED", "TRIA_FRAC", "COMPONENTS")]
    errs = list(r["errors"])
    if int(r["metrics"].get("n_components") or 1) > 1:
        errs.append({"code": "MESH_DISCONNECTED", "message": f"메시 연결 성분 {r['metrics']['n_components']}개 — 면이 서로 "
                                                             "붙어 있지 않은 형상(설정 bead_doe.mesh.occ_sew_faces 1 검토)"})
    if qf < float(mc["min_quad_frac"]):
        warns.append({"code": "MESH_QUAD_FRAC", "message": f"4각 비율 {qf:.3f} < {mc['min_quad_frac']}"})
    return {"errors": errs, "warnings": warns, "metrics": r["metrics"], "quad_frac": qf}


def _loop_info(occ, curves) -> float:
    return float(sum(occ.getMass(1, abs(int(c))) for c in curves))


def _face_loops(gmsh, s: int) -> list[list[int]]:
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


def _curve_points(gmsh, c: int) -> set[int]:
    """곡선 끝점(닫힌 곡선도 — combined=True 는 시작=끝 점을 지워 빈 목록을 줌)."""
    return {abs(int(p)) for _d, p in gmsh.model.getBoundary([(1, int(c))], combined=False, oriented=False)}


def _seam_points(gmsh, s: int) -> set[int]:
    """면 s 의 seam(같은 면 경계에 두 번 나오는 곡선 — 원통·원뿔·토러스 등 periodic 면의 이음선) 끝점 태그.
    ``getBoundary(combined=True)`` 는 seam 을 지워 periodic 면의 양 끝 고리가 따로 떨어진 고리처럼 보인다(v0.14.1)."""
    seen: dict[int, int] = {}
    for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False):
        seen[abs(int(t))] = seen.get(abs(int(t)), 0) + 1
    pts: set[int] = set()
    for c, n in seen.items():
        if n >= 2:
            pts |= _curve_points(gmsh, c)
    return pts


def _is_hole(gmsh, s: int, cl: list[int], seam_pts: set[int]) -> bool:
    """고리 cl 이 면 s 의 '구멍'인가(v0.14.1 — 이슈 #53 ④ periodic 면 메싱 실패 원인 수정):
    (a) 모든 곡선이 자유 모서리(이 면에만 붙음 — 이웃 면과 공유하면 구멍이 아니라 보스·버링 벽 같은 이음부) 이고
    (b) seam 끝점을 지나지 않음(periodic 면을 한 바퀴 감는 끝 고리 — 원통 끝 원 — 는 구멍이 아님)."""
    for c in cl:
        up, _down = gmsh.model.getAdjacencies(1, abs(int(c)))
        if any(int(f) != int(s) for f in up):
            return False
        if seam_pts and seam_pts & _curve_points(gmsh, abs(int(c))):
            return False
    return True


def _bbox_key(gmsh, dim: int, tag: int) -> tuple:
    """세션이 바뀌어도 같은 면을 찾는 열쇠(bbox 6값, 1e-6 mm 반올림) — 태그는 형상 처리 결과에 따라 바뀔 수 있음."""
    return tuple(round(float(v), 6) for v in gmsh.model.getBoundingBox(dim, tag))


def _bump(out: dict, k: str) -> None:
    """선택 집계(0 이면 키 자체를 두지 않음 — 정상 STEP 의 mesh.json 바이트 불변)."""
    out[k] = int(out.get(k) or 0) + 1


def _key_near(a: tuple, b: tuple, tol: float = 1e-4) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _key_in(a: tuple, b: tuple, tol: float = 1e-3) -> bool:
    """bbox a 가 bbox b 안(형상 폴백으로 나뉜 조각이 원 면 안인지)."""
    return len(a) == len(b) == 6 and all(b[i] - tol <= a[i] and a[i + 3] <= b[i + 3] + tol for i in range(3))


def defeature(gmsh, df: dict, h: float, skip_keys: tuple = ()) -> dict:
    """④ 작은 형상 처리(이슈 #53 BatchMesher holes table 근사, esl_step_compare.md SC-D-5 보강) — 가져온 OCC 형상에서:

    - 면의 내부 경계(구멍) 중 면적 < ``min_hole_area_mm2``(기본 π·4² — r<4 원형·eq_diam<8·좁은 슬롯) → 같은 경계로 막는 면을
      평면 면은 외곽·큰 구멍 고리로 다시 만들어 작은 구멍 내부 wire 를 지움(곡면은 막는 면을 fragment 로 붙임 —
      경계 모서리는 남음). OCP ShapeUpgrade_RemoveInternalWires 와 같은 결과를
      gmsh API 만으로(OCP 불필요).
    - 남은 구멍(원형 가정 r = 둘레/2π) 반지름 ``hole_r_mm`` 범위 → 둘레 분할 수 = max(hole_elems, ceil(P/h)) transfinite 곡선
      (v0.14.0 수정: 예전 min(hole_elems 6, …) 은 큰 구멍 둘레 모서리가 P/6 으로 길어져 품질 max_length Fail — 이제 구멍
      모서리 ≤ h, 작은 구멍은 최소 hole_elems 분할). hole_elems 0 이면 생략.
    실패는 형상 처리만 건너뛰고 경고(DEFEATURE_SKIPPED). 반환 {filled, filled_area_max, hole_sized, skipped, warnings}."""
    import math

    occ = gmsh.model.occ
    amin = float(df.get("min_hole_area_mm2") or 0.0)
    out = {"filled": 0, "filled_area_max": None, "hole_sized": 0, "skipped": 0, "warnings": []}
    try:
        surfs = [t for _d, t in occ.getEntities(2)]
        patches, rebuilt = [], []
        for s in surfs:
            loops = _face_loops(gmsh, s)
            if len(loops) <= 1:
                continue
            if skip_keys and any(_key_near(_bbox_key(gmsh, 2, s), k) for k in skip_keys):
                _bump(out, "relaxed")                    # 폴백 제약 해제 면: 형상 처리 안 함
                continue
            seam = _seam_points(gmsh, s)
            per = [_loop_info(occ, cl) for cl in loops]
            outer = int(max(range(len(per)), key=lambda i: per[i]))
            small, keep = [], [loops[outer]]
            for i, cl in enumerate(loops):
                if i == outer:
                    continue
                if not _is_hole(gmsh, s, cl, seam):      # v0.14.1: 이음부·periodic 끝 고리는 구멍 아님(그대로 둠)
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
                if a < amin and skip_keys and any(_key_near(tuple(round(float(v), 6) for v in occ.getBoundingBox(2, pt)), k)
                                                  for k in skip_keys):
                    _bump(out, "relaxed")                # 폴백 제약 해제: 이 막는 면이 실패한 면 → 메우지 않음
                    keep.append(cl)
                    occ.remove([(2, pt)])
                elif a < amin:
                    small.append((cl, pt))
                    out["filled_area_max"] = max(a, out["filled_area_max"] or 0.0)
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
        if patches:
            occ.fragment([(2, s) for _d, s in occ.getEntities(2) if s not in patches], [(2, p) for p in patches])
        if rebuilt:
            occ.remove([(1, c) for c in sorted(set(rebuilt))], recursive=True)
        occ.synchronize()
        n_el = int(df.get("hole_elems") or 0)
        r_lo, r_hi = [float(x) for x in (df.get("hole_r_mm") or [4.0, 30.0])]
        done: set[int] = set()
        relaxed = {s for _d, s in occ.getEntities(2)
                   if skip_keys and any(_key_near(_bbox_key(gmsh, 2, s), k) for k in skip_keys)}
        if n_el > 0:
            for _d, s in occ.getEntities(2):
                loops = _face_loops(gmsh, s)
                if len(loops) <= 1 or s in relaxed:
                    continue
                seam = _seam_points(gmsh, s)
                per = [_loop_info(occ, cl) for cl in loops]
                outer = int(max(range(len(per)), key=lambda i: per[i]))
                for i, cl in enumerate(loops):
                    cs = [abs(int(c)) for c in cl]
                    if i == outer or any(c in done for c in cs):
                        continue
                    if not _is_hole(gmsh, s, cl, seam):  # v0.14.1: 이음부·periodic 끝 고리는 분할 강제 안 함
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


class _FaceFail(Exception):
    """gmsh 2D 메싱이 한 면에서 멈춤(gmsh API 는 첫 오류에서 예외 — 그 뒤 면은 메시 안 됨). key = 형상 폴백 단계가
    그 면에 적용되지 못한 경우 그 폴백 상태 열쇠(메싱 전 실패 — 다음 단계로)."""

    def __init__(self, msg: str, face: dict | None, key: tuple | None = None):
        super().__init__(msg)
        self.msg = msg
        self.face = face
        self.key = key


# ---------------------------------------------------------------- v0.15.1 형상 폴백(실패 면만 — 이슈 #53 Sphere 면)
GEOM_STAGES = ("split", "fill", "small")
STAGE_NAMES = {"algorithm": "2D 알고리즘", "relax": "제약 해제", "split": "면 분할", "fill": "채움 면 대체",
               "small": "작은 면 평면 채움"}
_AREA_RTOL = 1e-3                                           # 면 분할 전후 넓이 보존 허용(상대)


class _GeomSkip(Exception):
    """형상 폴백 단계를 이 면에 쓸 수 없음(조각 1개·넓이 불일치·편차 초과·고리 여러 개 등) — 다음 단계로."""


def _face_by_key(gmsh, key: tuple) -> int | None:
    for _d, t in gmsh.model.getEntities(2):
        if _key_near(_bbox_key(gmsh, 2, t), key):
            return int(t)
    return None


def _outer_wire(gmsh, s: int) -> list[int]:
    """면 s 의 바깥 경계 곡선(seam — 경계에 두 번 나오는 곡선 — 제외)을 끝점으로 이은 순서. 고리가 1개가 아니면 _GeomSkip."""
    cnt: dict[int, int] = {}
    for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False):
        cnt[abs(int(t))] = cnt.get(abs(int(t)), 0) + 1
    cs = sorted(c for c, n in cnt.items() if n == 1)
    if not cs:
        raise _GeomSkip("seam 아닌 경계 곡선 없음")
    ends = {c: sorted(_curve_points(gmsh, c)) for c in cs}
    order, left = [cs[0]], set(cs[1:])
    while left:
        tail = set(ends[order[-1]])
        nxt = next((c for c in sorted(left) if tail & set(ends[c])), None)
        if nxt is None:
            break
        order.append(nxt)
        left.discard(nxt)
    if left:
        raise _GeomSkip(f"경계 고리가 1개가 아님(곡선 {len(cs)}개 중 {len(left)}개 따로)")
    return order


def _face_samples(gmsh, s: int, n: int, interior: bool) -> np.ndarray:
    """면 s 위 매개변수 격자 점(isInside 만) — interior 면 경계 줄 제외(1..n-1), 아니면 0..n."""
    (u0, v0), (u1, v1) = gmsh.model.getParametrizationBounds(2, s)
    rng = range(1, n) if interior else range(n + 1)
    pts = []
    for i in rng:
        for j in rng:
            uv = [u0 + (u1 - u0) * i / n, v0 + (v1 - v0) * j / n]
            if gmsh.model.isInside(2, s, uv, parametric=True):
                pts.append(uv)
    if not pts:
        return np.zeros((0, 3))
    return np.asarray(gmsh.model.getValue(2, s, [x for uv in pts for x in uv]), dtype=np.float64).reshape(-1, 3)


def _dist_to(gmsh, s: int, P: np.ndarray) -> float:
    if not P.size:
        return 0.0
    Q = np.asarray(gmsh.model.getClosestPoint(2, s, P.ravel().tolist())[0], dtype=np.float64).reshape(-1, 3)
    return float(np.max(np.linalg.norm(Q - P, axis=1)))


def _drop_free(gmsh, curves) -> None:
    """면을 바꾼 뒤 어느 면에도 붙지 않은 곡선(seam·극점 퇴화 모서리)을 지움 — 1D 만 메시되는 잔재 방지."""
    occ = gmsh.model.occ
    free = []
    for c in sorted({int(x) for x in curves}):
        try:
            up, _dn = gmsh.model.getAdjacencies(1, c)
        except Exception:                                    # noqa: BLE001, S112 - 이미 없는 곡선
            continue
        if not len(up):
            free.append((1, c))
    if free:
        occ.remove(free, recursive=True)
        occ.synchronize()


def _fill_face(gmsh, s: int, h: float, n_pts: int, tol: float, n_dev: int) -> dict:
    """면 s 를 바깥 경계 고리의 addSurfaceFilling(BSpline, 비periodic) 으로 대체. n_pts > 1 이면 원 면 안쪽 격자 점
    (n_pts−1)² 개를 지나게(원 면 모양 유지). 편차 = max(원 면 표본 → 채움 면, 채움 면 표본 → 원 면) 최단 거리(mm) > tol
    이면 _GeomSkip(원 면 그대로)."""
    occ = gmsh.model.occ
    wire = _outer_wire(gmsh, s)
    old = {abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False)}
    P = _face_samples(gmsh, s, n_pts, True) if n_pts > 1 else np.zeros((0, 3))
    try:
        w = occ.addCurveLoop([int(c) for c in wire])
        pts = [occ.addPoint(*map(float, p)) for p in P]
        f = occ.addSurfaceFilling(w, pointTags=pts)
        if pts:
            occ.remove([(0, p) for p in pts])
        occ.synchronize()
    except Exception as exc:                                 # noqa: BLE001
        occ.synchronize()
        raise _GeomSkip(f"채움 면을 만들지 못함: {exc}") from None
    try:
        dev = max(_dist_to(gmsh, f, _face_samples(gmsh, s, n_dev, False)),
                  _dist_to(gmsh, s, _face_samples(gmsh, f, n_dev, False)))
    except Exception as exc:                                 # noqa: BLE001
        dev, why = None, str(exc)
    if dev is None or dev > tol:
        occ.remove([(2, f)])
        occ.synchronize()
        _drop_free(gmsh, {abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, f)], oriented=False)}
                   if f in [t for _d, t in occ.getEntities(2)] else ())
        raise _GeomSkip(f"채움 면 편차 {'계산 실패: ' + why if dev is None else f'{dev:.3f} mm'} > 허용 {tol:g} mm")
    occ.remove([(2, s)])
    occ.synchronize()
    new = {abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, f)], combined=False, oriented=False)}
    if not new <= set(wire):                                 # 경계 곡선을 새로 만든 경우만 이웃과 봉합
        nb = sorted({int(u) for c in wire for u in gmsh.model.getAdjacencies(1, int(c))[0]} - {f})
        occ.fragment([(2, f)] + [(2, t) for t in nb], [])
        occ.synchronize()
    _drop_free(gmsh, old - set(wire))
    return {"deviation_mm": round(float(dev), 4), "new_ids": [int(f)]}


def _split_face(gmsh, s: int, n_planes: int) -> dict:
    """면 s 를 bbox 중심을 지나는 평면 n_planes 개(가장 긴 bbox 방향의 법선 순)로 잘라 비periodic 조각으로(그 면만
    fragment, 그다음 조각 + 이웃 면만 다시 fragment 해 공유 경계 유지). 조각 < 2·넓이 불일치 → _GeomSkip."""
    occ = gmsh.model.occ
    bb = gmsh.model.getBoundingBox(2, s)
    c = [0.5 * (bb[i] + bb[i + 3]) for i in range(3)]
    ext = [bb[i + 3] - bb[i] for i in range(3)]
    L = 2.0 * max(ext) + 1.0
    a0 = float(occ.getMass(2, s))
    curves = sorted({abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False)})
    nb = sorted({int(u) for cc in curves for u in gmsh.model.getAdjacencies(1, cc)[0]} - {s})
    n_before = len(occ.getEntities(2))
    a_nb = sum(float(occ.getMass(2, t)) for t in nb)
    tools = []
    for ax in sorted(range(3), key=lambda i: (-ext[i], i))[:max(1, min(2, int(n_planes)))]:
        r = occ.addRectangle(-L, -L, 0.0, 2 * L, 2 * L)
        if ax == 0:
            occ.rotate([(2, r)], 0, 0, 0, 0, 1, 0, np.pi / 2)
        elif ax == 1:
            occ.rotate([(2, r)], 0, 0, 0, 1, 0, 0, np.pi / 2)
        occ.translate([(2, r)], *c)
        tools.append((2, r))
    try:
        _out, mp = occ.fragment([(2, s)], tools)
        pieces = [int(t) for _d, t in mp[0]]
        rest = sorted({e for m in mp[1:] for e in m if e[0] == 2 and int(e[1]) not in pieces})
        if rest:
            occ.remove(rest, recursive=True)
        occ.synchronize()
        live = {int(t) for _d, t in occ.getEntities(2)}
        if len(pieces) < 2 or not set(pieces) <= live:
            raise _GeomSkip(f"면이 조각으로 나뉘지 않음(조각 {len(pieces)}개)")
        a1 = sum(float(occ.getMass(2, t)) for t in pieces)
        if abs(a1 - a0) > _AREA_RTOL * max(a0, 1e-12):
            raise _GeomSkip(f"조각 넓이 합 {a1:.4g} ≠ 원 면 {a0:.4g} mm²")
        occ.fragment([(2, t) for t in pieces + nb], [])
        occ.synchronize()
        n_after = len(occ.getEntities(2))
        a2 = sum(float(occ.getMass(2, t)) for t in nb) + sum(float(occ.getMass(2, t)) for t in pieces
                                                             if t in {int(x) for _d, x in occ.getEntities(2)})
    except _GeomSkip:
        raise
    except Exception as exc:                                 # noqa: BLE001
        occ.synchronize()
        raise _GeomSkip(f"면 분할 실패: {exc}") from None
    if n_after != n_before - 1 + len(pieces):
        raise _GeomSkip(f"분할 뒤 면 수 {n_after} ≠ {n_before - 1 + len(pieces)}")
    if abs(a2 - (a_nb + a1)) > _AREA_RTOL * max(a_nb + a1, 1e-12):
        raise _GeomSkip(f"봉합 뒤 넓이 {a2:.6g} ≠ {a_nb + a1:.6g} mm²")
    _drop_free(gmsh, curves)
    new_ids = sorted(int(t) for _d, t in occ.getEntities(2) if _key_in(_bbox_key(gmsh, 2, t), tuple(bb)) and t not in nb)
    return {"deviation_mm": 0.0, "new_ids": new_ids, "pieces": len(pieces)}


def _apply_geom(gmsh, key: tuple, stage: str, h: float, fb: dict) -> dict:
    """형상 폴백 한 단계를 bbox 키 면에 적용(이 세션 OCC 모델 — 원본 STEP 은 건드리지 않음). 반환 기록."""
    s = _face_by_key(gmsh, key)
    if s is None:
        raise _GeomSkip("이 세션에서 면을 찾지 못함")
    occ = gmsh.model.occ
    if stage == "split":
        sc = fb.get("split") if isinstance(fb.get("split"), dict) else {}
        return _split_face(gmsh, s, int(sc.get("planes") or 2))
    if stage == "fill":
        fc = fb.get("fill") if isinstance(fb.get("fill"), dict) else {}
        tol = float(fc.get("tol_factor", 0.5)) * h
        return _fill_face(gmsh, s, h, int(fc.get("points", 6)), tol, int(fc.get("samples", 10)))
    if stage == "small":
        sm = fb.get("small") if isinstance(fb.get("small"), dict) else {}
        amax = float(sm.get("area_mm2", 50.27))
        a = float(occ.getMass(2, s))
        if not a < amax:
            raise _GeomSkip(f"면 넓이 {a:.4g} mm² ≥ 작은 면 기준 {amax:g} mm²")
        return _fill_face(gmsh, s, h, 0, float(sm.get("tol_factor", 1.0)) * h, int(sm.get("samples", 10)))
    raise _GeomSkip(f"알 수 없는 형상 폴백 단계 {stage}")


def _failed_face(gmsh, msg: str, log: list | None = None) -> dict | None:
    """실패 직후 모델에서 실패 면 찾기: 메시지의 면 번호(예: 'Impossible to mesh periodic surface 2824') → gmsh 로그의
    마지막 'Meshing surface N'(단일 스레드 — 실패한 그 면) → 태그 순 첫 '요소 0개' 면."""
    import re
    tags = [int(t) for _d, t in gmsh.model.getEntities(2)]
    tag = None
    m = re.search(r"surface\s+(\d+)", msg or "")
    if m and int(m.group(1)) in tags:
        tag = int(m.group(1))
    for line in reversed(log or []):
        if tag is not None:
            break
        m = re.search(r"Meshing surface (\d+)", str(line))
        if m and int(m.group(1)) in tags:
            tag = int(m.group(1))
    if tag is None:
        for t in sorted(tags):
            if not sum(len(x) for x in gmsh.model.mesh.getElements(2, t)[1]):
                tag = t
                break
    if tag is None:
        return None
    bb = gmsh.model.getBoundingBox(2, tag)
    return {"id": tag, "type": str(gmsh.model.getType(2, tag)),
            "center": [round(0.5 * (float(bb[i]) + float(bb[i + 3])), 3) for i in range(3)],
            "key": _bbox_key(gmsh, 2, tag)}


def _session(gmsh, src: str, mc: dict, h: float, opts: dict, gopts: dict, *, step_out: str | None,
             face_alg: dict, relax: tuple, face_geom: dict | None = None, fb: dict | None = None) -> tuple:
    """gmsh 세션 1회(가져오기 → 옵션 → 작은 형상 처리 → 형상 폴백 → 면별 알고리즘 → 2D). face_alg = {bbox 키: 2D 알고리즘},
    relax = 제약 해제할 면 bbox 키들, face_geom = {bbox 키: 형상 폴백 단계(split·fill·small)} — 이 세션의 OCC 모델만 바꿈
    (원본 STEP·step_out 은 가져온 그대로). 적용 못 하면 _FaceFail(key=그 키, 메싱 전).
    반환 (X, conn, et, ver, dfi, step_done, applied{키: 태그}, geom{키: 기록})."""
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
        for k, v in gopts.items():
            gmsh.option.setNumber(k, v)
        try:
            gmsh.model.occ.importShapes(os.fspath(src))
            gmsh.model.occ.synchronize()
        except Exception as exc:                            # noqa: BLE001
            raise EslError("FAILED_MESH", f"형상 파일을 읽지 못함: {exc}") from None
        step_done = None
        if step_out:
            gmsh.write(os.fspath(step_out))
            step_done = os.path.basename(step_out)
        for k, v in opts.items():
            gmsh.option.setNumber(k, v)
        dfi = None
        df = mc.get("defeature")
        if isinstance(df, dict) and df.get("enabled"):       # v0.14.0 ④ 선택 키(없으면 ③ 그대로)
            dfi = defeature(gmsh, df, h, skip_keys=relax) if relax else defeature(gmsh, df, h)
        applied: dict = {}
        geom: dict = {}
        for gk, stage in (face_geom or {}).items():          # v0.15.1 형상 폴백(실패했던 면만, state 순서 = 결정적)
            try:
                geom[gk] = {"stage": stage, **_apply_geom(gmsh, gk, stage, h, fb or {})}
            except _GeomSkip as gs:
                bb = list(gk)
                raise _FaceFail(f"{STAGE_NAMES.get(stage, stage)} 적용 안 됨: {gs}",
                                {"id": None, "type": None, "key": gk,
                                 "center": [round(0.5 * (bb[i] + bb[i + 3]), 3) for i in range(3)]}, key=gk) from None
            if geom[gk].get("new_ids"):
                applied[gk] = int(geom[gk]["new_ids"][0])
        if face_alg:
            for _d, t in gmsh.model.getEntities(2):
                k = _bbox_key(gmsh, 2, t)
                for fk, alg in face_alg.items():
                    if _key_near(k, fk):
                        gmsh.model.mesh.setAlgorithm(2, t, int(alg))
                        applied[fk] = int(t)
        gmsh.logger.start()
        try:
            gmsh.model.mesh.generate(2)
        except Exception as exc:                            # noqa: BLE001
            msg = str(exc)
            raise _FaceFail(msg, _failed_face(gmsh, msg, gmsh.logger.get())) from None
        finally:
            gmsh.logger.stop()
        X, conn, et = _extract(gmsh)
        ver = str(getattr(gmsh, "__version__", ""))
    finally:
        gmsh.finalize()
    return X, conn, et, ver, dfi, step_done, applied, geom


ALG_NAMES = {1: "MeshAdapt", 2: "Automatic", 5: "Delaunay", 6: "Frontal-Delaunay", 7: "BAMG",
             8: "Frontal-Delaunay for Quads", 9: "Packing of Parallelograms", 11: "Quasi-structured Quad"}


DEFAULT_ORDER = ("algorithms", "relax")                     # fallback.order 없을 때(v0.14.1 그대로)


def _ladder(mc: dict, fb: dict, ftype: str | None = None) -> list[tuple[int, bool, str | None]]:
    """면 폴백 순서(설정 ``mesh.fallback``): [(알고리즘, 제약 해제, 형상 단계)]. 단계 묶음 순서 = ``order``(없으면
    algorithms → relax — v0.14.1 그대로), 실패 면 종류가 ``periodic_types`` 에 있으면 ``periodic_order``(있을 때):
    - ``algorithms``: ``algorithms`` 를 차례로(제약 그대로)
    - ``relax``: ``relax`` 면 제약(작은 형상 처리·구멍 둘레 분할)을 푼 뒤 기본 알고리즘 + ``algorithms`` 를 다시 차례로
    - ``split``·``fill``·``small``(v0.15.1 형상 폴백): 그 면만 형상을 바꾼 뒤 기본 알고리즘(목록에 없으면 끔)."""
    base = int(mc["algorithm"])
    algs = [int(a) for a in (fb.get("algorithms") or [])]
    order = list(fb.get("order") or DEFAULT_ORDER)
    if ftype and ftype in (fb.get("periodic_types") or []) and fb.get("periodic_order"):
        order = list(fb["periodic_order"])
    steps: list[tuple[int, bool, str | None]] = []
    for st in order:
        if st == "algorithms":
            steps += [(a, False, None) for a in algs if a != base]
        elif st == "relax" and fb.get("relax"):
            steps += [(a, True, None) for a in [base] + [x for x in algs if x != base]]
        elif st in GEOM_STAGES:
            steps.append((base, False, st))
    return steps


def fallback_label(x: dict) -> str:
    """mesh_fallback 면 기록 한 줄(경고·보고서 공용): 알고리즘 단계 = 알고리즘 이름(+제약 해제), 형상 단계 = 단계명(+편차)."""
    st = x.get("stage") or ("relax" if x.get("relaxed") else "algorithm")
    if st in GEOM_STAGES:
        d = x.get("deviation_mm")
        return f"{STAGE_NAMES[st]}" + (f"(편차 {float(d):.2f} mm)" if d is not None and st != "split" else "")
    return f"{x.get('algorithm_name')}{'(제약 해제)' if x.get('relaxed') else ''}"


def _step_label(step: tuple) -> str:
    a, r, g = step
    return STAGE_NAMES[g] if g else f"{ALG_NAMES.get(a, a)}{'(제약 해제)' if r else ''}"


def _face_label(f: dict) -> str:
    c = f.get("center") or []
    return f"면 {f.get('id')}({f.get('type')}, 위치 x {c[0]:g}, y {c[1]:g}, z {c[2]:g} mm 부근)" if len(c) == 3 else \
        f"면 {f.get('id')}({f.get('type')})"


def mesh_file(src: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None, normal_ref=None,
              out_dir: str | None = None, step_out: str | None = None) -> tuple[dict, dict]:
    """BREP/STEP → (mesh dict, mesh.json dict). out_dir 이 있으면 mesh.npz·mesh.json 을 쓴다. 이 프로세스 안에서 실행.

    v0.14.1 면 단위 폴백(선택 키 ``mesh.fallback`` — ④ 프로필만, ③ 은 키 없음 → 예전 그대로): 2D 메싱이 한 면에서 실패하면
    **그 면만** 다른 2D 알고리즘(``fallback.algorithms`` 순서)으로, 그래도 실패하면 그 면의 작은 형상 처리·구멍 둘레 분할을
    풀고(``fallback.relax``) 다시 메싱한다. 시도마다 새 gmsh 세션(같은 입력 → 같은 결과). 성공 형상의 다른 면은 그대로.
    v0.15.1 형상 폴백(``fallback.order``·``periodic_order`` 의 split·fill·small — 이슈 #53 Sphere 면): 그 면만 bbox 중심 평면으로
    나누거나(split), 경계 고리의 BSpline 채움 면으로 바꾸거나(fill, 원 면 대비 편차 ≤ ``fill.tol_factor`` × h), 작은 면이면
    경계만으로 채움(small) — 이 세션 OCC 모델만 바꿈(원본 STEP 불변). 나뉜 조각의 실패는 원 면의 다음 단계로.
    폴백이 쓰인 면 → meta.mesh_fallback(stage·deviation_mm) + 경고 MESH_FACE_FALLBACK. 끝내 실패 → FAILED_MESH(면 id·종류·bbox
    중심·시도한 단계)."""
    from esl.doe import opt_settings
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise EslError("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    mc = cfg["mesh"]
    h = check_h(h, mc)
    opts = gmsh_options(h, mc)
    gopts = geometry_options(mc)
    fb = mc.get("fallback") if isinstance(mc.get("fallback"), dict) else {}
    on = bool(fb.get("enabled"))
    max_faces = max(1, int(fb.get("max_faces") or 20))
    t_lim = float(mc.get("timeout_s") or 0.0)
    t0 = time.monotonic()
    state: dict = {}                                        # bbox 키 → {face, ladder, step(ladder 위치), errors[]}
    step_done = None
    first = True
    while True:
        cur = {k: v["ladder"][v["step"]] for k, v in state.items()}
        face_alg = {k: st[0] for k, st in cur.items() if st[2] is None}
        relax = tuple(k for k, st in cur.items() if st[1])
        face_geom = {k: st[2] for k, st in cur.items() if st[2]}
        try:
            X, conn, et, ver, dfi, sd, applied, geom = _session(gmsh, src, mc, h, opts, gopts,
                                                                step_out=step_out if first else None,
                                                                face_alg=face_alg, relax=relax,
                                                                face_geom=face_geom, fb=fb)
            if first:
                step_done = sd
            break
        except _FaceFail as ff:
            if first and step_out:
                step_done = os.path.basename(step_out)
            first = False
            f = ff.face
            lad = _ladder(mc, fb, f.get("type")) if (on and f is not None) else []
            if f is None or (not lad and ff.key is None):
                if f is None:
                    raise EslError("FAILED_MESH", f"gmsh 메싱 실패: {ff.msg}") from None
                raise EslError("FAILED_MESH", f"gmsh 메싱 실패: {_face_label(f)} — {ff.msg}") from None
            if ff.key is not None:                          # 형상 폴백 단계를 그 면에 못 씀 → 다음 단계
                k = ff.key
            else:
                k = next((kk for kk in state if _key_near(kk, f["key"])), None)
                if k is None:                               # 형상 폴백으로 나뉜/바뀐 조각의 실패 = 원 면의 실패
                    k = next((kk for kk, v in state.items() if v["ladder"][v["step"]][2]
                              and _key_in(f["key"], kk, max(1e-3, h))), None)
            if k is None:
                if max_faces and len(state) >= max_faces:
                    raise EslError("FAILED_MESH", f"gmsh 메싱 실패: 메시가 안 되는 면이 {max_faces}개를 넘음"
                                   f"(mesh.fallback.max_faces) — 마지막 {_face_label(f)}: {ff.msg}") from None
                k = f["key"]
                state[k] = {"face": f, "ladder": lad, "step": 0, "errors": [ff.msg]}
            else:
                v = state[k]
                v["errors"].append(ff.msg)
                v["step"] += 1
                if v["step"] >= len(v["ladder"]):
                    f0 = v["face"]
                    tried = " → ".join(_step_label(x) for x in v["ladder"])
                    raise EslError("FAILED_MESH", f"gmsh 메싱 실패: {_face_label(f0)}을(를) 메시하지 못했습니다 — "
                                   f"기본 {ALG_NAMES.get(int(mc['algorithm']), mc['algorithm'])} 뒤 {tried} 재시도도 실패. "
                                   f"CAD 에서 이 면(작은 모서리·좁은 띠·이음선)을 확인하세요. (gmsh: {v['errors'][0]}"
                                   + (f"; 마지막: {ff.msg}" if ff.msg != v["errors"][0] else "") + ")") from None
            if t_lim and time.monotonic() - t0 > t_lim:
                raise EslError("FAILED_MESH", f"gmsh 메싱 실패: 면 폴백 중 mesh.timeout_s {t_lim:g} s 초과 — "
                               f"{_face_label(state[k]['face'])}: {ff.msg}") from None
            a, r, g = state[k]["ladder"][state[k]["step"]]
            nxt = (f"{STAGE_NAMES[g]}(형상 바꾼 뒤 {ALG_NAMES.get(a, a)})" if g else
                   f"{ALG_NAMES.get(a, a)}{' + 제약 해제(작은 형상 처리·구멍 둘레 분할 끔)' if r else ''}")
            print(f"[mesh_fallback] {_face_label(state[k]['face'])} 실패: {ff.msg} → 이 면만 {nxt} 로 다시", flush=True)
    mesh, info = build_mesh(X, conn, et, props, normal_ref)
    oc = opt_cfg or opt_settings(None)
    qual = quality(mesh, cfg, oc)
    meta = {"schema": "esl/doe_mesh/1", "gmsh_version": ver, "options": {**opts, **gopts}, "h": h, "props": dict(props),
            "n_nodes": int(mesh["node_id"].size), "n_elems": int(mesh["elem_id"].size), "quad_frac": qual["quad_frac"],
            "quality": qual["metrics"], "errors": qual["errors"], "warnings": qual["warnings"], **info,
            "step": step_done, "seconds": round(time.monotonic() - t0, 3)}
    if dfi is not None:
        meta["defeature"] = dfi
    if state:                                               # v0.14.1 면 폴백 기록(정상 STEP 은 키 없음 — 바이트 불변)
        faces = []
        for k, v in state.items():
            a, r, g = v["ladder"][v["step"]]
            stage = g or ("relax" if r else "algorithm")
            gr = geom.get(k) or {}
            x = {"id": applied.get(k, v["face"]["id"]), "failed_id": v["face"]["id"], "type": v["face"]["type"],
                 "center": v["face"]["center"], "stage": stage, "stage_name": STAGE_NAMES[stage], "algorithm": a,
                 "algorithm_name": ALG_NAMES.get(a, str(a)), "relaxed": bool(r),
                 "deviation_mm": gr.get("deviation_mm"), "errors": v["errors"]}
            if g:
                x["new_ids"] = list(gr.get("new_ids") or [])
            faces.append(x)
        meta["mesh_fallback"] = {"n_faces": len(faces), "faces": faces}
        ids = ", ".join(str(x["failed_id"]) for x in faces)
        kinds = "·".join(dict.fromkeys(("다른 알고리즘" if x["stage"] == "algorithm" else x["stage_name"]) for x in faces))
        meta["warnings"] = list(meta["warnings"]) + [{
            "code": "MESH_FACE_FALLBACK",
            "message": f"면 {len(faces)}개(gmsh 면 id {ids})가 기본 2D 알고리즘으로 메시되지 않아 그 면만 {kinds}로 메시함 — "
                       + "; ".join(f"{_face_label(x | {'id': x['failed_id']})} → {fallback_label(x)}" for x in faces)}]
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        save_npz_det(os.path.join(out_dir, MESH_NPZ), {k: mesh[k] for k in MESH_KEYS})
        from esl.library import _util as U
        U.write_json(os.path.join(out_dir, MESH_JSON), {k: v for k, v in meta.items() if k != "seconds"}
                     | {"seconds": meta["seconds"]})
    if qual["errors"]:
        e = qual["errors"][0]
        raise EslError("FAILED_MESH", f"메시 품질 오류 {e['code']}: {e['message']}")
    return mesh, meta


def load_mesh(d: str) -> dict:
    from esl.library import _util as U
    arr = U.load_npz(os.path.join(d, MESH_NPZ))
    return {k: arr[k] for k in MESH_KEYS}


# ---------------------------------------------------------------- 하위 프로세스 격리
def write_step(src: str, dst: str) -> str:
    """BREP/STEP → STEP(OCC 형상, 메시 없음). 이 프로세스 안에서 실행."""
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise EslError("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)
        try:
            gmsh.model.occ.importShapes(os.fspath(src))
            gmsh.model.occ.synchronize()
            gmsh.write(os.fspath(dst))
        except Exception as exc:                            # noqa: BLE001
            raise EslError("FAILED_MESH", f"STEP 내보내기 실패: {exc}") from None
    finally:
        gmsh.finalize()
    return dst


def _child(job_path: str) -> int:
    with open(job_path, "r", encoding="utf-8") as fh:
        job = json.load(fh)
    out = job["out_dir"]
    err = os.path.join(out, "mesh_error.json")
    try:
        if job.get("step_only"):
            write_step(job["src"], job["step_out"])
            return 0
        mesh_file(job["src"], job["h"], job["cfg"], job["props"], opt_cfg=job.get("opt_cfg"),
                  normal_ref=job.get("normal_ref"), out_dir=out, step_out=job.get("step_out"))
    except EslError as exc:
        with open(err, "w", encoding="utf-8") as fh:
            json.dump({"code": exc.code, "message": exc.message}, fh, ensure_ascii=False)
        return 3
    return 0


def _watch_parent(ppid: int, interval: float = 1.0) -> None:
    """부모(코어 자식)가 강제 종료되면 이 gmsh 자식도 끝낸다(v0.14.0 — ④ 형상 병렬 메싱 취소 시 고아 방지)."""
    import threading

    def run() -> None:
        while True:
            time.sleep(interval)
            if os.getppid() != ppid:
                os._exit(4)
    if ppid > 1:
        threading.Thread(target=run, name="esl-gmsh-parent-watch", daemon=True).start()


def _child_entry(job_path: str, log_path: str, ppid: int | None = None) -> None:
    """spawn 자식 진입점: fd 1·2 → mesh.log, 실패는 mesh_error.json + 종료코드 3."""
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    if ppid and os.name != "nt":
        _watch_parent(int(ppid))
    sys.exit(_child(job_path))


def _spawn(job: dict, out_dir: str, to: float) -> int:
    from esl.library import _util as U
    jp = os.path.join(out_dir, "mesh_job.json")
    U.write_json(jp, job)
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_child_entry, args=(jp, os.path.join(out_dir, MESH_LOG), os.getpid()), daemon=True)
    p.start()
    p.join(to)
    if p.is_alive():
        p.terminate()
        p.join(5)
        if p.is_alive():
            p.kill()
            p.join()
        raise EslError("FAILED_MESH", f"gmsh 하위 프로세스가 제한 시간 {to:g} s 안에 끝나지 않음(mesh.timeout_s)")
    ep = os.path.join(out_dir, "mesh_error.json")
    if p.exitcode != 0:
        if os.path.isfile(ep):
            e = U.read_json(ep)
            raise EslError(str(e.get("code") or "FAILED_MESH"), str(e.get("message") or ""))
        raise EslError("FAILED_MESH", f"gmsh 하위 프로세스가 비정상 종료(코드 {p.exitcode}) — {MESH_LOG} 확인")
    return 0


def export_step_isolated(src: str, dst: str, cfg: dict, timeout_s: float | None = None) -> str:
    """하위 프로세스에서 BREP → STEP (BD-D-18). gmsh 없음 → GMSH_UNAVAILABLE."""
    out_dir = os.path.dirname(os.path.abspath(dst))
    os.makedirs(out_dir, exist_ok=True)
    ep = os.path.join(out_dir, "mesh_error.json")
    if os.path.exists(ep):
        os.remove(ep)
    to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
    _spawn({"step_only": True, "src": os.path.abspath(src), "out_dir": out_dir, "step_out": os.path.abspath(dst)},
           out_dir, to)
    for name in ("mesh_job.json",):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            os.remove(p)
    return dst


def run_isolated(src: str, out_dir: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None,
                 normal_ref=None, step_out: str | None = None, timeout_s: float | None = None) -> tuple[dict, dict]:
    """하위 프로세스에서 ``mesh_file`` → (mesh, mesh.json). 타임아웃·크래시 → FAILED_MESH, gmsh 없음 → GMSH_UNAVAILABLE."""
    from esl.doe import opt_settings
    from esl.library import _util as U
    os.makedirs(out_dir, exist_ok=True)
    job = {"src": os.path.abspath(src), "out_dir": os.path.abspath(out_dir), "h": float(h), "cfg": cfg,
           "props": {k: float(v) for k, v in props.items()}, "opt_cfg": opt_cfg or opt_settings(None),
           "normal_ref": None if normal_ref is None else [float(x) for x in normal_ref],
           "step_out": None if not step_out else os.path.abspath(step_out)}
    for name in (MESH_NPZ, MESH_JSON, "mesh_error.json"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            os.remove(p)
    to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
    t0 = time.monotonic()
    _spawn(job, out_dir, to)
    meta = U.read_json(os.path.join(out_dir, MESH_JSON))
    meta["wall_seconds"] = round(time.monotonic() - t0, 3)
    return load_mesh(out_dir), meta

