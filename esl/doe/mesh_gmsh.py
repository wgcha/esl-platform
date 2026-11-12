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
from esl.fsutil import atomic_replace
from esl.geom import defeature as gdf

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
    atomic_replace(tmp, path)
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


def set_import_labels(gmsh, mcfg: dict) -> None:
    """v0.16.3 C2-D-31 선택 키 ``mesh.occ_import_labels``(④ 프로필만, 기본 0): STEP 가져오기 때 XCAF 이름표(라벨)를 읽지 않음 —
    면이 수천 개인 STEP 에서 gmsh 4.13 라벨 처리가 면 수에 초선형(합성 1915 면: 234 s → 5 s). 형상·태그는 같고 mesh.json
    options 에는 기록하지 않음(키가 없으면 아무것도 안 함 — ③ 그대로)."""
    if "occ_import_labels" in mcfg:
        gmsh.option.setNumber("Geometry.OCCImportLabels", int(mcfg["occ_import_labels"]))


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


# v0.16.1 위상 도우미·작은 구멍 처리 = 공통 모듈 esl.geom.defeature(SR-D-22) — 같은 _이름으로 재노출(본문 이동만, 바이트 불변)
_loop_info = gdf.loop_length
_face_loops = gdf.face_loops
_curve_points = gdf.curve_points
_seam_points = gdf.seam_points
_is_hole = gdf.is_hole
_bbox_key = gdf.bbox_key
_key_near = gdf.key_near
_bump = gdf._bump


def _key_in(a: tuple, b: tuple, tol: float = 1e-3) -> bool:
    """bbox a 가 bbox b 안(형상 폴백으로 나뉜 조각이 원 면 안인지)."""
    return len(a) == len(b) == 6 and all(b[i] - tol <= a[i] and a[i + 3] <= b[i + 3] + tol for i in range(3))


def defeature(gmsh, df: dict, h: float, skip_keys: tuple = ()) -> dict:
    """④ 작은 형상 처리(v0.14.1 holes table 근사) — 래퍼(v0.16.1): 본문 = ``esl.geom.defeature.holes``(SR-D-22, V-SR-16)."""
    return gdf.holes(gmsh, df, h, skip_keys)


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
NOFIX_SCOPES = ("face", "all")                               # nofix 범위: 그 면만 정리 없이 다시 가져와 대체 / 세션 전체 정리 끔
STAGE_NAMES = {"algorithm": "2D 알고리즘", "relax": "제약 해제", "split": "면 분할", "fill": "채움 면 대체",
               "small": "작은 면 평면 채움", "nofix": "OCC 정리 끔", "nofix_face": "OCC 정리 끔(그 면만)",
               "nofix_all": "OCC 정리 끔(전체)"}
_AREA_RTOL = 1e-3                                           # 면 분할 전후 넓이 보존 허용(상대)


def _fb_defaults() -> dict:
    """DEFAULTS 의 compare.mesh.fallback(형상 폴백 기본값의 한 곳 — 코드 안 상수 중복 방지)."""
    from esl.doe import DEFAULTS
    try:
        return DEFAULTS["compare"]["mesh"]["fallback"]
    except (KeyError, TypeError):
        return {}


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


def _same_face_hits(cands: list, key: tuple, typ: str, area: float, bbox_tol: float, area_rtol: float) -> list[int]:
    """엄격 대응 후보: bbox(± bbox_tol)·면 종류·넓이(상대 area_rtol)가 모두 맞는 tag 목록."""
    return [int(t) for t, ty, a, bb in cands
            if _key_near(tuple(bb), key, bbox_tol) and str(ty) == str(typ)
            and abs(float(a) - area) <= area_rtol * max(abs(area), 1e-12)]


def _pick_same_face(cands: list, key: tuple, typ: str, area: float, bbox_tol: float, area_rtol: float) -> int:
    """nofix(그 면만) 대체 면 고르기: cands = [(tag, 종류, 넓이, bbox)] 중 bbox(± bbox_tol)·면 종류·넓이(상대 area_rtol)가 모두
    맞는 면이 정확히 1개일 때만 그 tag. 0개·2개 이상(대칭 쌍처럼 bbox·종류·넓이가 같은 면) → _GeomSkip(엉뚱한 면 대체 방지)."""
    hit = _same_face_hits(cands, key, typ, area, bbox_tol, area_rtol)
    if len(hit) != 1:
        raise _GeomSkip(f"정리 없이 가져온 형상에 같은 면(bbox ±{bbox_tol:g}·종류 {typ}·넓이 ±{area_rtol:g}) 후보 "
                        f"{len(hit)}개{' — 하나로 정할 수 없음' if hit else ''}")
    return hit[0]


def _pick_grown_face(cands: list, key: tuple, typ: str, area: float, bbox_tol: float, grow: float) -> int:
    """C2-D-38 엄격 대응(bbox·넓이 같음) 후보 0개일 때: OCC 정리가 작은 조각을 키운 면(실측: 0.08 mm² 구 조각 → 63.53 mm² 완전한
    구)을 찾음 — 같은 종류 ∧ bbox 가 정리 뒤 bbox(± bbox_tol) 안 ∧ 넓이 ∈ [area / grow, area]. 정확히 1개일 때만."""
    lo = [float(v) - bbox_tol for v in key[:3]]
    hi = [float(v) + bbox_tol for v in key[3:]]
    hit = [int(t) for t, ty, a, bb in cands
           if str(ty) == str(typ) and all(lo[i] <= float(bb[i]) and float(bb[i + 3]) <= hi[i] for i in range(3))
           and area / grow <= float(a) <= area * (1.0 + 1e-6)]
    if len(hit) != 1:
        raise _GeomSkip(f"넓이가 줄어든(정리 전 조각) 같은 종류 후보 {len(hit)}개")
    return hit[0]


def _pick_nofix_face(cands: list, key: tuple, typ: str, area: float, bbox_tol: float, area_rtol: float,
                     grow: float) -> tuple[int | None, str | None]:
    """nofix(그 면만) 대체 면 → (tag | None, 사유). 엄격 대응 정확히 1개 = 그 면. 엄격 후보 0개이고 grow > 1 일 때만
    C2-D-38 정리가 키운 면(_pick_grown_face). 엄격 후보 2개 이상 = 모호 → 고르지 않음(키운 면 찾기도 안 함)."""
    try:
        return _pick_same_face(cands, key, typ, area, bbox_tol, area_rtol), None
    except _GeomSkip as gs:
        why = str(gs)
    if grow > 1.0 and not _same_face_hits(cands, key, typ, area, bbox_tol, area_rtol):
        try:
            return _pick_grown_face(cands, key, typ, area, bbox_tol, grow), None
        except _GeomSkip as gs2:
            why = f"{why}; {gs2}"
    return None, why


def _nofix_face(gmsh, src: str, key: tuple, fb: dict | None = None) -> dict:
    """nofix(그 면만): 같은 STEP 을 OCC 정리(OCCFix*·OCCSewFaces) 없이 한 번 더 가져와 bbox·면 종류·넓이가 같은 면 하나만 남기고,
    정리된 원 면을 그 면으로 바꾼 뒤 원 면 이웃과만 fragment(공유 경계 복원). 극점 퇴화 모서리가 남아 Sphere 면이 메시된다.
    후보 0·2개 이상·면 수 불일치 → _GeomSkip(원 세션 그대로). 허용값 = fallback.nofix.bbox_tol·area_rtol."""
    occ = gmsh.model.occ
    s = _face_by_key(gmsh, key)
    if s is None:
        raise _GeomSkip("이 세션에서 면을 찾지 못함")
    nf = (fb or {}).get("nofix") if isinstance((fb or {}).get("nofix"), dict) else {}
    dn = _fb_defaults().get("nofix") or {}
    bbox_tol = float(nf.get("bbox_tol", dn.get("bbox_tol", 1e-2)))
    area_rtol = float(nf.get("area_rtol", dn.get("area_rtol", 1e-2)))
    typ0, area0 = str(gmsh.model.getType(2, s)), float(occ.getMass(2, s))
    curves = sorted({abs(int(t)) for _d, t in gmsh.model.getBoundary([(2, s)], combined=False, oriented=False)})
    nb = sorted({int(u) for c in curves for u in gmsh.model.getAdjacencies(1, c)[0]} - {s})
    before = {d: {int(t) for _x, t in occ.getEntities(d)} for d in range(4)}
    n_before = len(before[2])
    keep = {k: gmsh.option.getNumber(k) for k in OCC_FIX_KEYS + ("Geometry.OCCSewFaces",)}
    try:
        for k in keep:
            gmsh.option.setNumber(k, 0)
        occ.importShapes(os.fspath(src))
        occ.synchronize()
    except Exception as exc:                                 # noqa: BLE001
        raise _GeomSkip(f"정리 없이 다시 가져오지 못함: {exc}") from None
    finally:
        for k, v in keep.items():
            gmsh.option.setNumber(k, v)
    new = {d: sorted(int(t) for _x, t in occ.getEntities(d) if int(t) not in before[d]) for d in range(4)}
    cands = [(t, gmsh.model.getType(2, t), occ.getMass(2, t), _bbox_key(gmsh, 2, t)) for t in new[2]]
    grow = float(nf.get("area_grow_max", dn.get("area_grow_max", 0.0)) or 0.0)
    f, why = _pick_nofix_face(cands, key, typ0, area0, bbox_tol, area_rtol, grow)
    if new[3]:
        occ.remove([(3, t) for t in new[3]])
    rest = [(2, t) for t in new[2] if t != f]
    if rest:
        occ.remove(rest, recursive=True)
    occ.synchronize()
    if f is None:
        _drop_free(gmsh, new[1])
        raise _GeomSkip(why)
    occ.remove([(2, s)])
    occ.synchronize()
    try:
        occ.fragment([(2, f)] + [(2, t) for t in nb], [])
        occ.synchronize()
    except Exception as exc:                                 # noqa: BLE001
        occ.synchronize()
        raise _GeomSkip(f"이웃 면과 봉합 실패: {exc}") from None
    _drop_free(gmsh, set(curves) | set(new[1]))
    n_after = len(occ.getEntities(2))
    if n_after != n_before:
        raise _GeomSkip(f"대체 뒤 면 수 {n_after} ≠ {n_before}")
    nid = _face_by_key(gmsh, _bbox_key(gmsh, 2, f)) if f in {int(t) for _d, t in occ.getEntities(2)} else None
    return {"deviation_mm": 0.0, "new_ids": [int(nid if nid is not None else f)], "scope": "face"}


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
        fd = _fb_defaults().get("fill") or {}
        return _fill_face(gmsh, s, h, int(fc.get("points", fd.get("points", 8))), tol, int(fc.get("samples", 10)))
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


DEFEAT_KEY = "__defeature_stage__"                          # v0.16.1 _session 반환 geom 안 defeature 단계 기록 키
_LAST_DEFEAT: dict = {}                                     # 자식 프로세스 1작업: 마지막 세션 compound 면 bbox(실패 기록용)
SIZE_FIELDS_KEY = "__size_fields__"                         # _session 반환 geom 안 세분화 기록 키(bbox 키와 겹치지 않음)


def apply_size_fields(gmsh, entries: list, mc: dict) -> dict:
    """v0.16.0 국부 세분화(esl_compare_mesh_options.md C2-D-19, §4A): ``mesh.size_fields = [{keys:[bbox 키…], size_mm,
    rings?}]`` 의 면(bbox 키 → 이 세션 면, ``rings`` 고리 이웃 포함 — ``mesh_refine.neighbor_faces``)에 gmsh Constant Field
    (VIn = size_mm, 경계 곡선 포함)를 주고 Min 배경장으로 둔다. 이 시도에서만 Mesh.MeshSizeMin = min(size_mm) × min_size_factor.
    반환 {entries:[{size_mm, rings, n_keys, faces:[{tag, ring, key, type, center, area}]}], mesh_size_min}."""
    from esl.doe import mesh_refine as mr
    fld = gmsh.model.mesh.field
    ids, rec, smin = [], [], None
    for e in entries:
        size = float(e["size_mm"])
        rings = int(e.get("rings") or 0)
        keys = [tuple(float(v) for v in k) for k in (e.get("keys") or [])]
        faces = mr.neighbor_faces(gmsh, keys, rings)
        rec.append({"size_mm": size, "rings": rings, "n_keys": len(keys), "faces": faces})
        if not faces:
            continue
        f = fld.add("Constant")
        fld.setNumber(f, "VIn", size)
        fld.setNumber(f, "IncludeBoundary", 1)
        fld.setNumbers(f, "SurfacesList", sorted(int(x["tag"]) for x in faces))
        ids.append(f)
        smin = size if smin is None else min(smin, size)
    out = {"entries": rec, "mesh_size_min": None}
    if ids:
        m = fld.add("Min")
        fld.setNumbers(m, "FieldsList", ids)
        fld.setAsBackgroundMesh(m)
        out["mesh_size_min"] = float(smin) * float(mc["min_size_factor"])
        gmsh.option.setNumber("Mesh.MeshSizeMin", out["mesh_size_min"])
    return out


def _session(gmsh, src: str, mc: dict, h: float, opts: dict, gopts: dict, *, step_out: str | None,
             face_alg: dict, relax: tuple, face_geom: dict | None = None, fb: dict | None = None,
             nofix_all: bool = False) -> tuple:
    """gmsh 세션 1회(가져오기 → 옵션 → 작은 형상 처리 → 형상 폴백 → 면별 알고리즘 → 2D). face_alg = {bbox 키: 2D 알고리즘},
    relax = 제약 해제할 면 bbox 키들, face_geom = {bbox 키: 형상 폴백 단계(split·fill·small)} — 이 세션의 OCC 모델만 바꿈
    (원본 STEP·step_out 은 가져온 그대로). 적용 못 하면 _FaceFail(key=그 키, 메싱 전). nofix_face 는 작은 형상 처리 전에,
    nofix_all = 이 세션 전체를 OCC 정리(OCCFix*·OCCSewFaces) 없이 가져옴.
    반환 (X, conn, et, ver, dfi, step_done, applied{키: 태그}, geom{키: 기록})."""
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        # v0.17.4 C2-D-34 감시 자식(_RUN track)만 gmsh 문구를 mesh.log 로(시간 초과 때 마지막 'Meshing surface N (종류' → 실패 면)
        gmsh.option.setNumber("General.Terminal", 1 if _RUN.get("track") else 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0 if nofix_all else int(mc.get("occ_sew_faces", 0)))
        for k, v in gopts.items():
            gmsh.option.setNumber(k, 0 if nofix_all and k in OCC_FIX_KEYS else v)
        set_import_labels(gmsh, mc)
        _import(gmsh, src)
        if _RUN.get("track") and "faces" not in _RUN:       # v0.17.4 첫 가져오기 면 목록(감시 타이머가 로그 면 번호 → 기록)
            _RUN["faces"] = {int(t): {"type": str(gmsh.model.getType(2, t)), "key": _bbox_key(gmsh, 2, t)}
                             for _d, t in gmsh.model.getEntities(2)}
        step_done = None
        if step_out:
            gmsh.write(os.fspath(step_out))
            step_done = os.path.basename(step_out)
        for k, v in opts.items():
            gmsh.option.setNumber(k, v)
        applied: dict = {}
        geom: dict = {}

        def nofix_faces() -> None:
            for gk, stage in (face_geom or {}).items():      # v0.15.1 nofix(그 면만) — 작은 형상 처리 전
                if stage != "nofix_face":
                    continue
                try:
                    geom[gk] = {"stage": stage, **_nofix_face(gmsh, src, gk, fb)}
                except _GeomSkip as gs:
                    bb = list(gk)
                    raise _FaceFail(f"{STAGE_NAMES[stage]} 적용 안 됨: {gs}",
                                    {"id": None, "type": None, "key": gk,
                                     "center": [round(0.5 * (bb[i] + bb[i + 3]), 3) for i in range(3)]}, key=gk) from None
                applied[gk] = int(geom[gk]["new_ids"][0])
        nofix_faces()
        dfi = None
        df = mc.get("defeature")
        ds = mc.get("defeature_stage")                       # v0.16.1 ④ 사다리 defeature 단계(키 없으면 v0.16.0 그대로)
        feats: list = []
        if isinstance(df, dict) and df.get("enabled") and not nofix_all:   # v0.14.0 ④ 선택 키(없으면 ③ 그대로)
            sig0 = _occ_sig(gmsh)                            # v0.17.4 C2-D-37 실패한 구멍 메움은 되돌림(재가져오기)
            if isinstance(ds, dict):
                dfi = gdf.holes(gmsh, df, h, relax, collect=feats)
            else:
                dfi = defeature(gmsh, df, h, skip_keys=relax) if relax else defeature(gmsh, df, h)
            if any(str(w).startswith("DEFEATURE_SKIPPED") for w in dfi.get("warnings") or []) and _occ_sig(gmsh) != sig0:
                gmsh.clear()
                _import(gmsh, src)
                geom.clear()
                applied.clear()
                feats.clear()
                nofix_faces()
                dfi = dict(dfi, filled=0, hole_sized=0, reverted=True,
                           warnings=list(dfi["warnings"]) + ["DEFEATURE_REVERTED: 작은 형상 처리가 실패하며 형상을 바꿔 원 형상으로 "
                                                             "되돌림(다시 가져옴) — 구멍 메움 없이 메시"])
        if isinstance(ds, dict):
            crit = ds["crit"]
            found = gdf.find_features(gmsh, crit, targets=ds["targets"]) if ds.get("targets") else \
                gdf.find_features(gmsh, crit)
            sup = gdf.suppress(gmsh, found, crit, h, compound=bool(ds.get("compound", True)))
            _LAST_DEFEAT.clear()
            _LAST_DEFEAT.update(compound_keys=sup["compound_keys"])
            if sup["n"] == 0:
                raise EslError("DEFEATURE_NO_FEATURE", "형상 단순화 단계: 억제할 작은 형상이 없음")
            geom[DEFEAT_KEY] = {"collected": feats, **sup}
        for gk, stage in (face_geom or {}).items():          # v0.15.1 형상 폴백(실패했던 면만, state 순서 = 결정적)
            if stage in ("nofix_face", "nofix_all"):
                continue
            try:
                geom[gk] = {"stage": stage, **_apply_geom(gmsh, gk, stage, h, fb or {})}
            except _GeomSkip as gs:
                bb = list(gk)
                raise _FaceFail(f"{STAGE_NAMES.get(stage, stage)} 적용 안 됨: {gs}",
                                {"id": None, "type": None, "key": gk,
                                 "center": [round(0.5 * (bb[i] + bb[i + 3]), 3) for i in range(3)]}, key=gk) from None
            if geom[gk].get("new_ids"):
                applied[gk] = int(geom[gk]["new_ids"][0])
        if mc.get("size_fields"):                             # v0.16.0 세분화(C2-D-19) — 키 없으면 아무것도 안 함(바이트 불변)
            geom[SIZE_FIELDS_KEY] = apply_size_fields(gmsh, mc["size_fields"], mc)
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


def _import(gmsh, src: str) -> None:
    try:
        gmsh.model.occ.importShapes(os.fspath(src))
        gmsh.model.occ.synchronize()
    except Exception as exc:                                # noqa: BLE001
        raise EslError("FAILED_MESH", f"형상 파일을 읽지 못함: {exc}") from None


def _occ_sig(gmsh) -> tuple:
    """OCC 모델 서명(차원별 개수 + 면 bbox 키) — 구멍 메움이 모델을 바꿨는지(C2-D-37)."""
    occ = gmsh.model.occ
    return (tuple(len(occ.getEntities(d)) for d in range(4)),
            tuple(sorted(_bbox_key(gmsh, 2, t) for _d, t in gmsh.model.getEntities(2))))


def disconnected_hint(errs: list, dfi: dict | None, mc: dict) -> list:
    """v0.17.4 C2-D-37 MESH_DISCONNECTED 안내를 실제 원인에 맞춤: 구멍 메움 실패·되돌림 → compare.defeature, OCC 정리 켬 →
    occ_fix_small 0, 그 밖(정리 끔·봉합 끔) = 예전 occ_sew_faces 안내. 다른 오류는 그대로."""
    out = []
    for e in errs or []:
        if e.get("code") != "MESH_DISCONNECTED":
            out.append(e)
            continue
        head = str(e.get("message") or "").split(" — ")[0]
        if any(str(w).startswith(("DEFEATURE_SKIPPED", "DEFEATURE_REVERTED")) for w in (dfi or {}).get("warnings") or []):
            why = "작은 구멍 메움(defeature)이 실패하며 형상을 끊음(설정 bead_doe.compare.defeature.enabled false 검토)"
        elif geometry_options(mc):
            why = "OCC 작은 모서리·면 정리가 면을 바꿈(설정 bead_doe.compare.mesh.occ_fix_small 0 검토)"
        else:
            why = str(e.get("message") or "").split(" — ", 1)[1] if " — " in str(e.get("message") or "") else ""
        out.append(dict(e, message=f"{head} — {why}" if why else head))
    return out


ALG_NAMES = {1: "MeshAdapt", 2: "Automatic", 5: "Delaunay", 6: "Frontal-Delaunay", 7: "BAMG",
             8: "Frontal-Delaunay for Quads", 9: "Packing of Parallelograms", 11: "Quasi-structured Quad"}


DEFAULT_ORDER = ("algorithms", "relax")                     # fallback.order 없을 때(v0.14.1 그대로)


def _ladder(mc: dict, fb: dict, ftype: str | None = None) -> list[tuple[int, bool, str | None]]:
    """면 폴백 순서(설정 ``mesh.fallback``): [(알고리즘, 제약 해제, 형상 단계)]. 단계 묶음 순서 = ``order``(없으면
    algorithms → relax — v0.14.1 그대로), 실패 면 종류가 ``periodic_types`` 에 있으면 ``periodic_order``(있을 때):
    - ``algorithms``: ``algorithms`` 를 차례로(제약 그대로)
    - ``relax``: ``relax`` 면 제약(작은 형상 처리·구멍 둘레 분할)을 푼 뒤 기본 알고리즘 + ``algorithms`` 를 다시 차례로
    - ``split``·``fill``·``small``(v0.15.1 형상 폴백): 그 면만 형상을 바꾼 뒤 기본 알고리즘(목록에 없으면 끔)
    - ``nofix``: OCC 정리 없이 — ``nofix.scopes`` 순서(face = 그 면만 정리 없이 다시 가져와 대체, all = 세션 전체 정리 끔)."""
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
        elif st == "nofix":
            nf = fb.get("nofix") if isinstance(fb.get("nofix"), dict) else {}
            steps += [(base, False, f"nofix_{x}") for x in (nf.get("scopes") or NOFIX_SCOPES) if x in NOFIX_SCOPES]
    return steps


def fallback_label(x: dict) -> str:
    """mesh_fallback 면 기록 한 줄(경고·보고서 공용): 알고리즘 단계 = 알고리즘 이름(+제약 해제), 형상 단계 = 단계명(+편차)."""
    st = x.get("stage") or ("relax" if x.get("relaxed") else "algorithm")
    if st == "nofix":
        return STAGE_NAMES[f"nofix_{x['scope']}"] if x.get("scope") in NOFIX_SCOPES else STAGE_NAMES["nofix"]
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


# ---------------------------------------------------------------- v0.17.4 cad_relaxed·대형 모델·자식 제한(C2-D-32~35)
RELAXED_KEYS = ("occ_fix_small", "curvature_n", "min_size_factor")   # cad_relaxed 가 ④ 프로필에서 덮어쓰는 키
_RUN: dict = {}                                             # 자식 1작업 진행 기록(track·faces·face·sessions·relaxed)


def _relaxed_try(gmsh, src: str, mc: dict, h: float, props: dict, cfg: dict, opt_cfg, normal_ref, fb: dict, rx: dict,
                 ff, step_out: str | None) -> tuple[dict, tuple | None]:
    """C2-D-32 cad_relaxed: 모델 전체를 RELAXED_KEYS 만 바꾼 옵션으로 1세션(면 폴백 없음) → 품질 오류 없음 ∧ (rx.fidelity 면) 원
    STEP OCC 삼각화 대비 hausdorff ≤ remesh.fidelity.fail_mm 일 때만 채택. 반환 (기록, _session 결과 | None)."""
    from esl.doe import opt_settings
    over = {k: rx[k] for k in RELAXED_KEYS if rx.get(k) is not None}
    mc_r = dict(mc, **over)
    if not rx.get("defeature", False) and isinstance(mc.get("defeature"), dict):   # 실측: 정리 끔 + 구멍 메움 끔이 통함
        mc_r["defeature"] = dict(mc["defeature"], enabled=False)
        over = dict(over, defeature=False)
    opts_r, gopts_r = gmsh_options(h, mc_r), geometry_options(mc_r)
    rec: dict = {"tried": True, "ok": False, "overrides": over}
    if ff is not None:
        rec["first_error"] = ff.msg
        if ff.face is not None:
            rec["face"] = {k: ff.face.get(k) for k in ("id", "type", "center")}
    _RUN["relaxed"] = rec
    t1 = time.monotonic()
    _RUN["relaxed_t1"] = t1                                 # v0.18.2 C2-D-45 감시 타이머가 끊으면 이 시각부터 초(interrupted)
    try:
        got = _session(gmsh, src, mc_r, h, opts_r, gopts_r, step_out=step_out, face_alg={}, relax=(), fb=fb)
    except _FaceFail as e:
        rec.update(error=e.msg, seconds=round(time.monotonic() - t1, 3))
        return rec, None
    except EslError as e:
        rec.update(error=e.message, seconds=round(time.monotonic() - t1, 3))
        return rec, None
    mesh = build_mesh(got[0], got[1], got[2], props, normal_ref)[0]
    qe = disconnected_hint(quality(mesh, cfg, opt_cfg or opt_settings(None))["errors"], got[4], mc_r)
    if qe:
        rec.update(error=f"품질 오류 {qe[0]['code']}: {qe[0]['message']}", seconds=round(time.monotonic() - t1, 3))
        return rec, None
    if rx.get("fidelity", True):
        fd = _relaxed_fidelity(gmsh, src, mc_r, mesh, h, cfg)
        rec["fidelity"] = fd
        if fd.get("fail_mm") is not None and float(fd["hausdorff_mm"]) > float(fd["fail_mm"]):
            rec.update(error=f"원 STEP 대비 최대 {float(fd['hausdorff_mm']):.3f} mm(> {float(fd['fail_mm']):g} mm)",
                       seconds=round(time.monotonic() - t1, 3))
            return rec, None
    rec.update(ok=True, seconds=round(time.monotonic() - t1, 3), _opts=opts_r, _gopts=gopts_r)
    return rec, got


def _relaxed_fidelity(gmsh, src: str, mc_r: dict, mesh: dict, h: float, cfg: dict) -> dict:
    """cad_relaxed 메시 ↔ 같은 가져오기 옵션의 원 STEP OCC 삼각화(remesh 충실도 함수 — 코드 1곳). 기준 삼각화 각 편차 =
    compare.freeform.angular_deflection_deg(20°, C2-D-42 — 구면이 많으면 5° 는 삼각형 폭증), 선 편차는 remesh 절대값(0.05 mm) 그대로."""
    from esl.doe import mesh_remesh as mrm
    rc = mrm._rcfg(cfg)
    ang = mrm._fcfg(cfg).get("angular_deflection_deg")
    if ang is not None:
        rc = dict(rc, angular_deflection_deg=float(ang))
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        S_X, S_T = gdf.reference_tris(gmsh, src, mc_r, rc)
    finally:
        gmsh.finalize()
    ns = (mc_r.get("cad_relaxed") or {}).get("fidelity_samples") if isinstance(mc_r.get("cad_relaxed"), dict) else None
    if ns:                                                  # v0.18.2 C2-D-45 표본 상한(고정 간격 — 양방향 각각 ≤ ns 점)
        rc = dict(rc, fidelity=dict(rc["fidelity"], samples_max=min(int(rc["fidelity"]["samples_max"]), int(ns))))
    fd = mrm.fidelity(S_X, S_T, mesh, h, rc)
    out = {k: fd.get(k) for k in ("hausdorff_mm", "p95_mm", "area_ratio", "warn_mm", "fail_mm", "over_warn")}
    if ns:
        out["samples"] = fd.get("samples")
    return out


STEP_SURF = {"Sphere": "SPHERICAL_SURFACE", "Torus": "TOROIDAL_SURFACE", "Cylinder": "CYLINDRICAL_SURFACE",
             "Cone": "CONICAL_SURFACE", "BSpline surface": "B_SPLINE_SURFACE"}   # gmsh 면 종류 → STEP 엔터티


def step_scan(src: str, types=("Sphere",)) -> dict:
    """C2-D-33 STEP 본문 세기(gmsh 없이, 결정적): {n_faces, periodic:{종류: 개수}}. STEP 이 아니면(BREP 등) n_faces None."""
    import re
    out: dict = {"n_faces": None, "periodic": {}}
    if os.path.splitext(str(src))[1].lower() not in (".step", ".stp"):
        return out
    with open(src, "rb") as fh:
        b = fh.read()
    out["n_faces"] = len(re.findall(rb"=\s*(?:ADVANCED_FACE|FACE_SURFACE)\s*\(", b))
    for t in types or ():
        e = STEP_SURF.get(str(t))
        if e:
            n = len(re.findall(rb"[=,(]\s*" + e.encode() + rb"\s*\(", b))
            if n:
                out["periodic"][str(t)] = n
    return out


def large_model(src: str, mc: dict) -> dict:
    """C2-D-33 대형 모델 판정: STEP 면 > mesh.large_faces 또는 large.periodic_types 면이 있음. 키 없으면(③) large False."""
    lg = mc.get("large") if isinstance(mc.get("large"), dict) else None
    if lg is None or mc.get("large_faces") is None:
        return {"large": False}
    sc = step_scan(src, lg.get("periodic_types") or ())
    why = []
    if sc["n_faces"] is not None and sc["n_faces"] > int(mc["large_faces"]):
        why.append("faces")
    if sc["periodic"]:
        why.append("periodic")
    return {"large": bool(why), "reason": why, **sc}


def log_face(log_path: str, faces: dict | None = None, tail: int = 1 << 19) -> dict | None:
    """C2-D-35 mesh.log 끝(tail 바이트)에서 마지막으로 메시하던 면: 'periodic surface N' → '[mesh_fallback] 면 N(종류' →
    gmsh 'Meshing surface N (종류'. faces(_RUN 면 목록)가 있으면 key 를 붙임. 없으면 None."""
    import re
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - tail))
            txt = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    tag = typ = None
    m = list(re.finditer(r"periodic surface (\d+)", txt))
    if m:
        tag = int(m[-1].group(1))
    for pat in (r"\[mesh_fallback\] 면 (\d+)\(([^,)]+)", r"Meshing surface (\d+) \(([^,)]+)"):
        mm = list(re.finditer(pat, txt))
        if mm and (tag is None or int(mm[-1].group(1)) == tag):
            tag, typ = int(mm[-1].group(1)), mm[-1].group(2).strip()
            break
    if tag is None:
        return None
    f = (faces or {}).get(tag) or (faces or {}).get(str(tag)) or {}
    out = {"id": tag, "type": f.get("type") or typ}
    if f.get("key") is not None:
        k = [float(v) for v in f["key"]]
        out.update(key=k, center=[round(0.5 * (k[i] + k[i + 3]), 3) for i in range(3)])
    if m:
        out["error"] = f"Impossible to mesh periodic surface {tag}"
    return out


def mesh_file(src: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None, normal_ref=None,
              out_dir: str | None = None, step_out: str | None = None, t_lim_s: float | None = None,
              large: bool = False) -> tuple[dict, dict]:
    """BREP/STEP → (mesh dict, mesh.json dict). out_dir 이 있으면 mesh.npz·mesh.json 을 쓴다. 이 프로세스 안에서 실행.

    v0.14.1 면 단위 폴백(선택 키 ``mesh.fallback`` — ④ 프로필만, ③ 은 키 없음 → 예전 그대로): 2D 메싱이 한 면에서 실패하면
    **그 면만** 다른 2D 알고리즘(``fallback.algorithms`` 순서)으로, 그래도 실패하면 그 면의 작은 형상 처리·구멍 둘레 분할을
    풀고(``fallback.relax``) 다시 메싱한다. 시도마다 새 gmsh 세션(같은 입력 → 같은 결과). 성공 형상의 다른 면은 그대로.
    v0.15.1 형상 폴백(``fallback.order``·``periodic_order`` 의 split·fill·small — 이슈 #53 Sphere 면): 그 면만 bbox 중심 평면으로
    나누거나(split), 경계 고리의 BSpline 채움 면으로 바꾸거나(fill, 원 면 대비 편차 ≤ ``fill.tol_factor`` × h), 작은 면이면
    경계만으로 채움(small) — 이 세션 OCC 모델만 바꿈(원본 STEP 불변). 나뉜 조각의 실패는 원 면의 다음 단계로.
    폴백이 쓰인 면 → meta.mesh_fallback(stage·deviation_mm) + 경고 MESH_FACE_FALLBACK. 끝내 실패 → FAILED_MESH(면 id·종류·bbox
    중심·시도한 단계).

    v0.17.4(선택 인자·키 — 없으면 예전 그대로): ``t_lim_s`` = 면 폴백 시간 상한을 mesh.timeout_s 보다 줄임(C2-D-34 — spawn 제한보다
    먼저 끝나 실패 면 기록을 남김), ``mesh.cad_relaxed``(C2-D-32 — 첫 세션 면 실패 → 면 폴백 전에 모델 전체를 ③ 옵션으로 1세션,
    ``direct`` 면 처음부터 그 세션만), ``large``(C2-D-33 — 면 폴백 세션 수 ≤ ``mesh.large.fallback_sessions``)."""
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
    if t_lim_s is not None:                                 # v0.17.4 C2-D-34 자식 제한(spawn 제한 − 여유)
        t_lim = min(t_lim, float(t_lim_s)) if t_lim else float(t_lim_s)
    rx = mc.get("cad_relaxed") if isinstance(mc.get("cad_relaxed"), dict) else {}
    lg = mc.get("large") if isinstance(mc.get("large"), dict) else {}
    max_sess = int(lg.get("fallback_sessions") or 0) if large else 0
    for k in ("relaxed", "face", "sessions", "relaxed_t1", "relaxed_cad_s"):
        _RUN.pop(k, None)
    t0 = time.monotonic()
    state: dict = {}                                        # bbox 키 → {face, ladder, step(ladder 위치), errors[]}
    step_done = None
    first = True
    rx_rec: dict | None = None
    n_sess = 0
    if rx.get("direct"):                                    # v0.17.4 부모의 cad_relaxed 시도(cad 시간 초과 뒤): 이 세션만
        rx_rec, got = _relaxed_try(gmsh, src, mc, h, props, cfg, opt_cfg, normal_ref, fb, rx, None, step_out)
        for k in ("first_error", "face"):                   # v0.18.2 C2-D-45 cad 자식의 첫 실패 면(부모가 넘김)
            if (rx.get("first") or {}).get(k) is not None:
                rx_rec[k] = rx["first"][k]
        if got is None:
            raise EslError("FAILED_MESH", f"gmsh 메싱 실패: cad_relaxed(③ 옵션 전체 재시도) 실패 — {rx_rec.get('error')}")
        X, conn, et, ver, dfi, step_done, applied, geom = got
        opts, gopts = rx_rec.pop("_opts"), rx_rec.pop("_gopts")
        first = False
    while rx_rec is None or not rx_rec.get("ok"):
        cur = {k: v["ladder"][v["step"]] for k, v in state.items()}
        face_alg = {k: st[0] for k, st in cur.items() if st[2] is None}
        relax = tuple(k for k, st in cur.items() if st[1])
        face_geom = {k: st[2] for k, st in cur.items() if st[2]}
        k_all = next((k for k, st in cur.items() if st[2] == "nofix_all"), None)
        n_sess += 1
        _RUN["sessions"] = n_sess
        try:
            X, conn, et, ver, dfi, sd, applied, geom = _session(gmsh, src, mc, h, opts, gopts,
                                                                step_out=step_out if first else None,
                                                                face_alg=face_alg, relax=relax,
                                                                face_geom=face_geom, fb=fb, nofix_all=k_all is not None)
            if first:
                step_done = sd
            if k_all is not None:
                geom[k_all] = {"stage": "nofix_all", "deviation_mm": 0.0, "new_ids": [], "scope": "all"}
            k_nf = k_all if k_all is not None else next((k for k, st in cur.items() if st[2] == "nofix_face"), None)
            if k_nf is not None:                            # 정리 끔(전체·그 면만): 다른 면 작은 모서리·틈·대체 면 연결 끊김
                qe = disconnected_hint(quality(build_mesh(X, conn, et, props, normal_ref)[0], cfg,
                                               opt_cfg or opt_settings(None))["errors"], dfi, mc)
                if qe:                                      # → 품질 오류면 쓰지 않음(원 세션 기준 다음 단계)
                    g_nf = cur[k_nf][2]
                    raise _FaceFail(f"{STAGE_NAMES[g_nf]} 뒤 품질 오류 {qe[0]['code']}: {qe[0]['message']}",
                                    state[k_nf]["face"], key=k_nf)
            break
        except _FaceFail as ff:
            if first and step_out:
                step_done = os.path.basename(step_out)
            was_first = first
            first = False
            if was_first and ff.face is not None:           # v0.17.4 감시 기록용 첫 실패 면
                _RUN["face"] = dict(ff.face, error=ff.msg)
            if was_first and rx.get("enabled") and rx.get("defer"):   # v0.18.2 C2-D-45 부모가 자기 세션·예산으로(이 자식은 면 폴백만)
                rec_d: dict = {"deferred": True, "first_error": ff.msg, "cad_seconds": round(time.monotonic() - t0, 3)}
                if ff.face is not None:
                    rec_d["face"] = {k: ff.face.get(k) for k in ("id", "type", "center")}
                _RUN["relaxed"] = rec_d
                print("[cad_relaxed] 부모 프로세스가 따로 시도(cad_relaxed.isolate) → 이 자식은 면 폴백", flush=True)
            elif was_first and rx.get("enabled"):           # v0.17.4 C2-D-32 면 폴백 전에 ③ 옵션 전체 1세션
                t_first = round(time.monotonic() - t0, 3)
                _RUN["relaxed_cad_s"] = t_first
                rx_rec, got = _relaxed_try(gmsh, src, mc, h, props, cfg, opt_cfg, normal_ref, fb, rx, ff, None)
                rx_rec["cad_seconds"] = t_first
                if got is not None:
                    X, conn, et, ver, dfi, _sd, applied, geom = got
                    opts, gopts = rx_rec.pop("_opts"), rx_rec.pop("_gopts")
                    break
                print(f"[cad_relaxed] ③ 옵션 전체 재시도 실패: {rx_rec.get('error')} → 면 폴백", flush=True)
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
            if k is None and k_all is not None:             # 정리 끔(전체)이 만든 다른 면 실패 → 그 단계 실패(원 세션 기준)
                k = k_all
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
            if max_sess and n_sess - 1 >= max_sess:         # v0.17.4 C2-D-33 대형 모델: 면 폴백 세션(재가져오기) 상한
                raise EslError("FAILED_MESH", f"gmsh 메싱 실패: 대형 모델 면 폴백 세션 {max_sess}회 상한"
                               f"(compare.mesh.large.fallback_sessions) — {_face_label(state[k]['face'])}: {ff.msg}") from None
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
    if rx_rec is not None and rx_rec.get("ok"):           # v0.17.4 C2-D-32 cad_relaxed 채택(정상 STEP 은 키 없음 — 바이트 불변)
        meta["cad_relaxed"] = rx_rec
        fd = rx_rec.get("fidelity") or {}
        meta["warnings"] = list(meta["warnings"]) + [{
            "code": "MESH_CAD_RELAXED",
            "message": "cad 메시가 " + (f"{_face_label(rx_rec['face'])}에서 실패해" if rx_rec.get("face") else "실패해")
                       + " 면 폴백 전에 모델 전체를 ③ 옵션(" + ", ".join(f"{k} {v}" for k, v in rx_rec["overrides"].items())
                       + ")으로 다시 메시함"
                       + (f" — 원 STEP 대비 최대 {float(fd['hausdorff_mm']):.3f} mm" if fd.get("hausdorff_mm") is not None
                          else "")}]
    if mc.get("size_fields"):                               # v0.16.0 세분화 기록(키 없으면 mesh.json 바이트 불변)
        meta["size_fields"] = geom.get(SIZE_FIELDS_KEY)
    dlist = None
    if isinstance(mc.get("defeature_stage"), dict) and geom.get(DEFEAT_KEY) is not None:   # v0.16.1 SR-D-19·20
        meta["defeature_stage"], dlist = _defeature_record(gmsh, src, mc, cfg, mesh, h, geom[DEFEAT_KEY])
        meta["warnings"] = list(meta["warnings"]) + dlist.pop("_warnings")
    if state:                                             # v0.14.1 면 폴백 기록(정상 STEP 은 키 없음 — 바이트 불변)
        faces = []
        for k, v in state.items():
            a, r, g = v["ladder"][v["step"]]
            stage = ("nofix" if g and g.startswith("nofix") else g) or ("relax" if r else "algorithm")
            gr = geom.get(k) or {}
            x = {"id": applied.get(k, v["face"]["id"]), "failed_id": v["face"]["id"], "type": v["face"]["type"],
                 "center": v["face"]["center"], "stage": stage, "stage_name": STAGE_NAMES[stage], "algorithm": a,
                 "algorithm_name": ALG_NAMES.get(a, str(a)), "relaxed": bool(r),
                 "deviation_mm": gr.get("deviation_mm"), "errors": v["errors"]}
            if g:
                x["new_ids"] = list(gr.get("new_ids") or [])
            if stage == "nofix":
                x["scope"] = gr.get("scope") or g.split("_", 1)[1]
            faces.append(x)
        meta["mesh_fallback"] = {"n_faces": len(faces), "faces": faces}
        ids = ", ".join(str(x["failed_id"]) for x in faces)
        kinds = "·".join(dict.fromkeys(("다른 알고리즘" if x["stage"] == "algorithm" else x["stage_name"]) for x in faces))
        meta["warnings"] = list(meta["warnings"]) + [{
            "code": "MESH_FACE_FALLBACK",
            "message": f"면 {len(faces)}개(gmsh 면 id {ids})가 기본 2D 알고리즘으로 메시되지 않아 그 면만 {kinds}로 메시함 — "
                       + "; ".join(f"{_face_label(x | {'id': x['failed_id']})} → {fallback_label(x)}" for x in faces)}]
    if out_dir:
        mark_success_write()
        os.makedirs(out_dir, exist_ok=True)
        save_npz_det(os.path.join(out_dir, MESH_NPZ), {k: mesh[k] for k in MESH_KEYS})
        from esl.library import _util as U
        if dlist is not None:
            U.write_json(os.path.join(out_dir, DEFEAT_LIST), dlist)
        U.write_json(os.path.join(out_dir, MESH_JSON), {k: v for k, v in meta.items() if k != "seconds"}
                     | {"seconds": meta["seconds"]})
    if dlist is not None and meta["defeature_stage"]["fidelity"]["fail"]:
        o = meta["defeature_stage"]["fidelity"]["outside"]
        raise EslError("DEFEATURE_FIDELITY", f"작은 형상 억제 뒤 메시가 억제 영역 밖에서 원 STEP 과 최대 {o['hausdorff_mm']:.3f} mm "
                                             f"다름(> {o['fail_mm']:g} mm)")
    if qual["errors"]:
        e = disconnected_hint(qual["errors"], dfi, mc)[0]            # v0.17.4 안내를 원인에 맞춤(실패 문구만)
        raise EslError("FAILED_MESH", f"메시 품질 오류 {e['code']}: {e['message']}")
    return mesh, meta


DEFEAT_LIST = "defeature.json"


def _defeature_record(gmsh, src: str, mc: dict, cfg: dict, mesh: dict, h: float, rec: dict) -> tuple[dict, dict]:
    """defeature 단계 성공 메시 → (mesh.json.defeature_stage, defeature.json 목록 + _warnings). 원 STEP 을 같은 정리 옵션으로
    다시 가져와 OCC 삼각화(S0) → 억제 영역 안/밖 충실도(SR-D-19). 바깥 fail 이면 fidelity.fail True(호출자가 DEFEATURE_FIDELITY)."""
    from esl.doe import mesh_remesh as mrm
    crit = mc["defeature_stage"]["crit"]
    rc = mrm._rcfg(cfg)
    feats = list(rec.get("collected") or []) + list(rec.get("features") or [])
    for i, f in enumerate(rec.get("collected") or []):
        f["id"] = f"h{i + 1:04d}"
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        S_X, S_T = gdf.reference_tris(gmsh, src, mc, rc)
    finally:
        gmsh.finalize()
    fid = gdf.fidelity_split(S_X, S_T, mesh, h, rc, feats, float(crit["region_pad"]))
    o = fid["outside"]
    fid_rec = {"outside": o, "suppressed_max_mm": fid["suppressed_max_mm"],
               "fail": bool(o.get("fail_mm") is not None and o["hausdorff_mm"] > float(o["fail_mm"]))}
    ok = [f for f in feats if f.get("action", "suppressed") == "suppressed"]
    counts: dict = {}
    for f in ok:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    doc = gdf.list_doc(feats, int(crit["list_max"]))
    warns = []
    tm = next((f["too_many"] for f in feats if f.get("too_many")), None)
    if tm:
        warns.append({"code": "DEFEATURE_TOO_MANY", "message": f"작은 형상 {tm['n']}개 > 상한 {tm['max']} — 앞 {tm['max']}개만"})
    if o.get("over_warn"):
        warns.append({"code": "REMESH_FIDELITY_WARN",
                      "message": f"형상 단순화 메시가 억제 영역 밖에서 원 STEP 과 최대 {o['hausdorff_mm']:.3f} mm 다름"
                                 f"(> 경고 {o['warn_mm']:g} mm)"})
    doc["_warnings"] = warns
    stage = {"counts": dict(sorted(counts.items())), "n": len(ok), "skipped_n": int(rec.get("skipped_n") or 0),
             "compound": [list(g) for g in rec.get("compound_groups") or []], "fidelity": fid_rec, "list_file": DEFEAT_LIST}
    return stage, doc


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
    if job.get("child_timeout_s"):                          # v0.17.4 C2-D-34
        _RUN["track"] = True
        _arm_deadline(job, err)
    try:
        if job.get("step_only"):
            write_step(job["src"], job["step_out"])
            return 0
        if os.environ.get(TEST_FAIL_ENV):                   # v0.16.3 시험 전용 고장 주입(설정 키 아님 — 환경 변수만)
            _test_fail_hook(job, os.environ[TEST_FAIL_ENV])
        if job.get("kind") in ("remesh", "freeform"):       # v0.16.0 삼각형 재메시(C2-D-11), v0.16.3 freeform(C2-D-26)
            from esl.doe import mesh_remesh
            kw = {"freeform": True} if job["kind"] == "freeform" else {}
            mesh_remesh.remesh_file(job["src"], job["h"], job["cfg"], job["props"], opt_cfg=job.get("opt_cfg"),
                                    normal_ref=job.get("normal_ref"), out_dir=out, **kw)
            return 0
        if job.get("kind") == "tria":                       # v0.16.3 OCC 삼각형 폴백(C2-D-28)
            from esl.doe import mesh_tria
            mesh_tria.tria_file(job["src"], job["h"], job["cfg"], job["props"], opt_cfg=job.get("opt_cfg"),
                                normal_ref=job.get("normal_ref"), out_dir=out)
            return 0
        kw = {}
        if job.get("child_timeout_s"):                      # v0.17.4 C2-D-34(키 없으면 예전 호출 그대로)
            kw["t_lim_s"] = float(job["loop_timeout_s"])
        if job.get("large"):                                # v0.17.4 C2-D-33
            kw["large"] = True
        mesh_file(job["src"], job["h"], job["cfg"], job["props"], opt_cfg=job.get("opt_cfg"),
                  normal_ref=job.get("normal_ref"), out_dir=out, step_out=job.get("step_out"), **kw)
    except EslError as exc:
        rec = {"code": exc.code, "message": exc.message}
        if job.get("fail_info") and exc.code == "FAILED_MESH":          # v0.16.0 세분화 입력(실패 면·면적, C2-D-19·21)
            rec.update(_fail_info(exc, job))
        if isinstance((job.get("cfg") or {}).get("mesh", {}).get("defeature_stage"), dict) and \
                _LAST_DEFEAT.get("compound_keys"):                     # v0.16.1 compound 면 실패 판정(2번째 시도)
            rec["compound_keys"] = _LAST_DEFEAT["compound_keys"]
        if _RUN.get("track"):                               # v0.17.4 cad_relaxed 결과·세션 수(실패 기록에만)
            rec.update(_run_record())
        _write_err(err, rec)
        return 3
    return 0


import threading as _threading

_ERR_LOCK = _threading.Lock()                               # v0.17.4 감시 타이머·주 스레드 중 먼저 쓴 쪽만 mesh_error.json
_ERR_DONE: dict = {}
_OK_WRITE: dict = {}                                        # 성공 결과 쓰기 시작(done) — 이 뒤로 감시 타이머는 아무것도 안 함


def mark_success_write() -> None:
    """성공 메시(mesh.npz·mesh.json)를 쓰기 직전에 부름: 감시 타이머가 mesh_error.json 을 쓰거나 자식을 끝내지 않게."""
    with _ERR_LOCK:
        _OK_WRITE["done"] = True


def _write_err(err: str, rec: dict) -> bool:
    with _ERR_LOCK:
        if _ERR_DONE.get(err):
            return False
        with open(err, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        _ERR_DONE[err] = True
        return True


def _run_record() -> dict:
    out: dict = {"progress": {"sessions": _RUN.get("sessions"), "n_faces": len(_RUN.get("faces") or {}) or None}}
    rr = _RUN.get("relaxed")
    if rr:
        out["cad_relaxed"] = {k: v for k, v in rr.items() if not k.startswith("_")}
        x = out["cad_relaxed"]
        if x.get("tried") and x.get("seconds") is None and x.get("error") is None:   # v0.18.2 C2-D-45 끝나기 전에 끊김
            x["interrupted"] = True
            if _RUN.get("relaxed_t1") is not None:
                x["seconds"] = round(time.monotonic() - float(_RUN["relaxed_t1"]), 3)
            if x.get("cad_seconds") is None and _RUN.get("relaxed_cad_s") is not None:
                x["cad_seconds"] = _RUN["relaxed_cad_s"]
    return out


def _arm_deadline(job: dict, err: str) -> None:
    """C2-D-34 자식 감시 타이머: job.child_timeout_s 에 아직 끝나지 않았으면(gmsh 2D 가 한 면에서 멈춤 등) mesh_error.json 에
    시간 초과 + 실패 면(첫 실패 면 → mesh.log 마지막 면) 기록 후 종료코드 3 — 부모 spawn 이 죽이기 전에(정상 종료면 아무것도 안 함)."""
    import threading
    t = float(job["child_timeout_s"])
    with _ERR_LOCK:                                         # 이 작업의 성공 쓰기 표시만 봄(같은 프로세스 앞 작업 무관)
        _OK_WRITE.clear()

    def fire() -> None:
        face = _RUN.get("face") or log_face(os.path.join(job["out_dir"], MESH_LOG), _RUN.get("faces"))
        msg = f"gmsh 메싱 실패: 자식 제한 시간 {t:g} s 초과(시간 초과)"
        rec: dict = {"code": "FAILED_MESH", "timed_out": True}
        if face:
            msg += f" — {_face_label(face)}" + (f" (gmsh: {face['error']})" if face.get("error") else "")
            if face.get("key") is not None:
                rec["face"] = {"id": face.get("id"), "type": face.get("type"), "center": face.get("center"),
                               "key": [float(v) for v in face["key"]]}
            else:
                rec["log_face"] = {"id": face.get("id"), "type": face.get("type")}
        rec["message"] = msg
        rec.update(_run_record())
        with _ERR_LOCK:                                     # 잠금 안에서 종료 — 성공 쓰기(mark_success_write)와 겹치지 않음
            if _OK_WRITE.get("done") or _ERR_DONE.get(err):
                return
            try:
                with open(err, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh, ensure_ascii=False)
            except Exception:                               # noqa: BLE001
                return
            _ERR_DONE[err] = True
            sys.stdout.flush()
            os._exit(3)
    th = threading.Timer(t, fire)
    th.daemon = True
    th.start()


TEST_FAIL_ENV = "ESL_TEST_MESH_FAIL"


def _test_fail_hook(job: dict, spec: str) -> None:
    """시험 전용(V-C2-26~29): 환경 변수 ESL_TEST_MESH_FAIL = 쉼표 목록 —
    ``cad`` = cad 시도의 gmsh 2D 가 곡면(Sphere·BSpline·Bezier) 면이 남아 있으면 'Impossible to mesh periodic surface N'
    (면 폴백 nofix·split·fill 로도 못 피함, defeature 가 평면으로 바꾸면 통과), ``defeature`` = defeature 단계 2D 항상 실패,
    ``hang``(v0.17.4) = cad 시도에서 OCC 정리(OCCFixDegenerated 1)가 켜져 있으면 첫 Sphere 면에서 gmsh 형식 'Meshing surface N
    (Sphere, …)' 한 줄을 찍고 멈춤(자식 감시 타이머 시험 — 정리 끔 cad_relaxed 는 실제 2D),
    ``remesh`` = remesh·freeform 의 2D 항상 실패, ``fidelity`` = freeform·remesh 충실도 fail_mm 을 아주 작게. 운영에서는 이 변수가 없다."""
    import gmsh
    kinds = {x.strip() for x in spec.split(",") if x.strip()}
    kind = job.get("kind") or "cad"
    ds = (job.get("cfg") or {}).get("mesh", {}).get("defeature_stage")
    real = gmsh.model.mesh.generate

    def gen_cad(dim=3):
        for _d, t in gmsh.model.getEntities(2):
            if str(gmsh.model.getType(2, t)) in ("Sphere", "BSpline surface", "Bezier surface"):
                raise RuntimeError(f"Impossible to mesh periodic surface {t}")
        return real(dim)

    def gen_fail(dim=3):
        raise RuntimeError("test: 2D meshing failed")

    def gen_hang(dim=3):
        if gmsh.option.getNumber("Geometry.OCCFixDegenerated") == 1:
            for _d, t in gmsh.model.getEntities(2):
                if str(gmsh.model.getType(2, t)) == "Sphere":
                    print(f"Info    : [ 50%] Meshing surface {t} (Sphere, Frontal-Delaunay for Quads)", flush=True)
                    time.sleep(3600)
        return real(dim)
    if kind == "cad" and not isinstance(ds, dict) and "hang" in kinds:
        gmsh.model.mesh.generate = gen_hang
    elif kind == "cad" and not isinstance(ds, dict) and "cad" in kinds:
        gmsh.model.mesh.generate = gen_cad
    elif kind == "cad" and isinstance(ds, dict) and "defeature" in kinds:
        gmsh.model.mesh.generate = gen_fail
    elif kind == "cad" and isinstance(ds, dict) and "cad" in kinds:
        gmsh.model.mesh.generate = gen_cad
    elif kind in ("remesh", "freeform") and "remesh" in kinds:
        gmsh.model.mesh.generate = gen_fail
    if kind in ("remesh", "freeform") and "fidelity" in kinds:
        cm = job["cfg"].setdefault("compare", {})
        rm = dict(cm.get("remesh") or {})
        rm["fidelity"] = dict(rm.get("fidelity") or {}, warn_mm=1e-9, fail_mm=1e-9)
        cm["remesh"] = rm


def _fail_info(exc: BaseException, job: dict) -> dict:
    """cad 시도 실패 → {face?:{id, type, center, key}, geom?:{area_mm2, n_faces, local_area_mm2, local_faces}}.
    면 = 마지막 _FaceFail(mesh_file 이 ``raise … from None`` 으로 던져도 __context__ 에 남음). geom = 같은 STEP 을 같은
    가져오기 옵션으로 다시 읽은 넓이(세분화 요소 수 예측용). 실패해도 빈 dict(오류 기록은 그대로)."""
    out: dict = {}
    e, n = exc.__context__, 0
    while e is not None and n < 8:
        if isinstance(e, _FaceFail) and e.face:
            f = e.face
            key = e.key if e.key is not None else f.get("key")
            if key is not None:
                out["face"] = {"id": f.get("id"), "type": f.get("type"), "center": f.get("center"),
                               "key": [float(v) for v in key]}
            break
        e, n = e.__context__, n + 1
    try:
        from esl.doe import mesh_refine as mr
        rings = int(((job["cfg"].get("compare") or {}).get("refine") or {}).get("local", {}).get("neighbor_rings") or 0)
        keys = [tuple(out["face"]["key"])] if "face" in out else []
        out["geom"] = mr.geom_summary(job["src"], job["cfg"]["mesh"], keys, rings)
    except Exception:                                       # noqa: BLE001 - 예측 자료 없음 = 상한 판정 생략
        pass
    return out


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


def _spawn(job: dict, out_dir: str, to: float, beat=None, beat_s: float = 60.0) -> int:
    from esl.library import _util as U
    jp = os.path.join(out_dir, "mesh_job.json")
    U.write_json(jp, job)
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_child_entry, args=(jp, os.path.join(out_dir, MESH_LOG), os.getpid()), daemon=True)
    p.start()
    if beat is None:
        p.join(to)
    else:                                                   # v0.17.4 C2-D-39 진행 줄(결과 무관 — join 을 나눠 기다림)
        t0 = time.monotonic()
        while p.is_alive() and time.monotonic() - t0 < to:
            p.join(min(float(beat_s), max(0.0, to - (time.monotonic() - t0))))
            if p.is_alive() and time.monotonic() - t0 < to:
                try:
                    beat(round(time.monotonic() - t0, 1), last_step(os.path.join(out_dir, MESH_LOG)))
                except Exception:                           # noqa: BLE001 - 진행 줄 실패는 메싱과 무관
                    pass
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


MESH_ERROR = "mesh_error.json"
RUN_KINDS = ("cad", "remesh", "freeform", "tria")   # v0.16.3 += freeform·tria(C2-D-26·28)


def last_step(log_path: str, tail: int = 1 << 16) -> str | None:
    """mesh.log 끝의 마지막 폴백 진행 줄([mesh_fallback]·[cad_relaxed]) — 진행 줄용(C2-D-39)."""
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - tail))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for ln in reversed(lines):
        if ln.startswith(("[mesh_fallback]", "[cad_relaxed]")):
            return ln[:240]
    return None


def run_isolated(src: str, out_dir: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None,
                 normal_ref=None, step_out: str | None = None, timeout_s: float | None = None,
                 kind: str = "cad", max_elems: int | None = None, fail_info: bool = False,
                 large: bool = False, beat=None) -> tuple[dict, dict]:
    """하위 프로세스에서 ``mesh_file``(kind cad) 또는 ``mesh_remesh.remesh_file``(kind remesh, v0.16.0 C2-D-11) →
    (mesh, mesh.json). 타임아웃·크래시 → FAILED_MESH, gmsh 없음 → GMSH_UNAVAILABLE.

    v0.16.0 선택 인자(기본값이면 job·결과가 v0.15.x 와 같음): ``max_elems`` = 품질 요소 상한 덮어쓰기(세분화 시도 =
    refine.max_elems, C2-D-21 — cfg 사본의 mesh.max_elems), ``fail_info`` = cad 실패 시 mesh_error.json 에 실패 면·넓이
    (``face``·``geom`` — ``mesh_refine.plan`` 입력). kind remesh 의 제한 시간 = remesh.timeout_s(null 이면 mesh.timeout_s).
    v0.17.4: kind cad ∧ ``mesh.child_margin_s``(④ 프로필) → 자식 제한 = spawn 제한 − 여유(C2-D-34), ``large`` → 면 폴백 세션 상한."""
    from esl.doe import opt_settings
    from esl.library import _util as U
    if kind not in RUN_KINDS:
        raise EslError("INPUT_INVALID", f"알 수 없는 메시 작업 종류 {kind!r} ({'|'.join(RUN_KINDS)})")
    os.makedirs(out_dir, exist_ok=True)
    if max_elems is not None:
        cfg = dict(cfg)
        cfg["mesh"] = dict(cfg["mesh"], max_elems=int(max_elems))
    job = {"src": os.path.abspath(src), "out_dir": os.path.abspath(out_dir), "h": float(h), "cfg": cfg,
           "props": {k: float(v) for k, v in props.items()}, "opt_cfg": opt_cfg or opt_settings(None),
           "normal_ref": None if normal_ref is None else [float(x) for x in normal_ref],
           "step_out": None if not step_out else os.path.abspath(step_out)}
    if kind != "cad":
        job["kind"] = kind
    if fail_info:
        job["fail_info"] = True
    for name in (MESH_NPZ, MESH_JSON, MESH_ERROR):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            os.remove(p)
    if timeout_s is None and kind in ("remesh", "freeform", "tria"):
        rt = ((cfg.get("compare") or {}).get(kind) or {}).get("timeout_s")
        if rt is None and kind == "freeform":
            rt = ((cfg.get("compare") or {}).get("remesh") or {}).get("timeout_s")
        timeout_s = float(rt) if rt is not None else None
    to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
    if kind == "cad" and cfg["mesh"].get("child_margin_s") is not None:
        mg_s = min(float(cfg["mesh"]["child_margin_s"]), 0.1 * to)
        job["child_timeout_s"] = round(max(0.5 * to, to - mg_s), 3)     # 감시 타이머(spawn 보다 먼저)
        job["loop_timeout_s"] = round(max(0.4 * to, to - 2.0 * mg_s), 3)   # 면 폴백 반복 상한(실패 면·넓이 기록 시간)
    if large and kind == "cad":
        job["large"] = True
    t0 = time.monotonic()
    if beat is None:
        _spawn(job, out_dir, to)
    else:
        _spawn(job, out_dir, to, beat=beat, beat_s=float(cfg["mesh"].get("heartbeat_s") or 60.0))
    meta = U.read_json(os.path.join(out_dir, MESH_JSON))
    meta["wall_seconds"] = round(time.monotonic() - t0, 3)
    return load_mesh(out_dir), meta

