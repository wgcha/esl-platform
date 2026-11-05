"""④ 삼각형 재메시(계약 esl_compare_mesh_options.md §4 R1~R8, C2-D-11~14).

CAD 면 구조를 버리고, 단순화(작은 구멍 메움)한 OCC 형상의 삼각화(BRepMesh — gmsh ``model.mesh.importStl``)를
이산 면 하나로 합친 뒤 gmsh ``classifySurfaces``(특징각) → ``createGeometry`` → quad 우선 재메시(④ 프로필 h 그대로)한다.
CAD 면 단위 메싱이 실패하는 복잡한 중립면 STEP 의 대안(사다리 마지막 단계). 실행은 ``mesh_gmsh.run_isolated(kind="remesh")``
의 spawn 자식 안(``mesh_gmsh._child``).

충실도(R8, C2-D-13): 단순화 후 CAD 삼각화 S(편차 ``linear_deflection_mm``) 대비 재메시 M 의 양방향 거리 —
d_MS = M 노드 → S 삼각형, d_SM = S 꼭짓점·삼각형 중심 → M 요소(quad 는 삼각형 2개). 후보 = 삼각형 중심 cKDTree k 개 +
정확한 점-삼각형 거리. S 의 긴 삼각형(평면 면 BRepMesh 는 면 하나가 삼각형 몇 개)은 같은 평면 안에서 최장 변 이등분으로
변 ≤ h 까지 나눠(거리 불변) 후보 검색이 정확하게 한다. 원 CAD 대비 편차는 hausdorff_mm + deflection_mm 이하.
숫자는 모두 설정(``bead_doe.compare.remesh``·``compare.mesh``·``mesh``)에서 읽는다(하드코딩 없음).
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

from esl.errors import EslError

SCHEMA = "esl/doe_mesh/1"
STL_NPZ = "remesh_stl.npz"
KNN = 8                                                     # 계약 C2-D-13 후보 수(k=8)
DIST_EPS_MM = 1e-6                                          # 이 값 이하 거리는 '면 위'(부동소수 잡음) — 정확화 생략


def _rcfg(cfg: dict) -> dict:
    from esl.doe import DEFAULTS, _deep_merge
    over = ((cfg.get("compare") or {}).get("remesh")) if isinstance(cfg, dict) else None
    return _deep_merge(DEFAULTS["compare"]["remesh"], over if isinstance(over, dict) else {})


def available() -> tuple[bool, str | None]:
    """(gmsh 에 model.mesh.importStl 이 있음, gmsh 버전) — R-C2-1·C2-D-16 ``remesh_available``."""
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        return False, None
    ver = str(getattr(gmsh, "__version__", "")) or None
    return bool(hasattr(gmsh.model.mesh, "importStl")), ver


def occ_version(gmsh) -> str | None:
    """gmsh 빌드 정보의 'OCC version: x.y.z' (C2-D-14 결정성 기록)."""
    import re
    try:
        m = re.search(r"OCC version:\s*([0-9][0-9.]*)", gmsh.option.getString("General.BuildInfo"))
    except Exception:                                       # noqa: BLE001
        return None
    return m.group(1) if m else None


_BUILD_VERSIONS: dict | None = None


def build_versions() -> dict:
    """{gmsh, occ} 버전(프로세스당 한 번 — 캐시 키용, v0.16.0 수렴 점검). gmsh 가 이미 초기화돼 있으면 그대로 읽고, 아니면
    설정 파일·시그널 처리 없이 잠깐 초기화했다 닫습니다. 읽지 못한 값은 None."""
    global _BUILD_VERSIONS
    if _BUILD_VERSIONS is not None:
        return dict(_BUILD_VERSIONS)
    ok, ver = available()
    occ = None
    if ok:
        import gmsh
        own = False
        try:
            if not gmsh.isInitialized():
                gmsh.initialize(readConfigFiles=False, interruptible=False)
                own = True
                gmsh.option.setNumber("General.Terminal", 0)
            occ = occ_version(gmsh)
        except Exception:                                   # noqa: BLE001 - 버전 기록 실패는 캐시 키 None
            occ = None
        finally:
            if own:
                try:
                    gmsh.finalize()
                except Exception:                           # noqa: BLE001
                    pass
    _BUILD_VERSIONS = {"gmsh": ver, "occ": occ}
    return dict(_BUILD_VERSIONS)


# ---------------------------------------------------------------- 기하(점-삼각형 거리)
def point_tri_dist(P: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """점 P 와 삼각형 ABC 의 최단 거리(브로드캐스트, (...,3) → (...)). Ericson 'Real-Time Collision Detection' 5.1.5
    영역 판정(꼭짓점 → 변 → 내부) — 퇴화 삼각형도 변·꼭짓점 거리로."""
    P, A, B, C = (np.asarray(x, dtype=np.float64) for x in (P, A, B, C))
    ab, ac, ap = B - A, C - A, P - A

    def dot(u, v):
        return np.sum(u * v, axis=-1)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    bp = P - B
    d3, d4 = dot(ab, bp), dot(ac, bp)
    cp = P - C
    d5, d6 = dot(ab, cp), dot(ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    with np.errstate(divide="ignore", invalid="ignore"):
        v_ab = np.where(d1 - d3 != 0, d1 / (d1 - d3), 0.0)
        w_ac = np.where(d2 - d6 != 0, d2 / (d2 - d6), 0.0)
        den_bc = (d4 - d3) + (d5 - d6)
        w_bc = np.where(den_bc != 0, (d4 - d3) / den_bc, 0.0)
        den = va + vb + vc
        v_in = np.where(den != 0, vb / den, 0.0)
        w_in = np.where(den != 0, vc / den, 0.0)
    conds = [(d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (vc <= 0) & (d1 >= 0) & (d3 <= 0),
             (d6 >= 0) & (d5 <= d6), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
             (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)]
    cands = [A, B, A + v_ab[..., None] * ab, C, A + w_ac[..., None] * ac, B + w_bc[..., None] * (C - B)]
    Q = A + v_in[..., None] * ab + w_in[..., None] * ac
    for c, q in zip(reversed(conds), reversed(cands)):      # 앞 조건 우선(Ericson 순서)
        Q = np.where(c[..., None], q, Q)
    d = np.linalg.norm(P - Q, axis=-1)
    bad = ~np.isfinite(d)                                   # 완전 퇴화(세 점 같음 등) → 꼭짓점·변 최솟값
    if np.any(bad):
        alt = np.minimum.reduce([np.linalg.norm(P - A, axis=-1), np.linalg.norm(P - B, axis=-1),
                                 np.linalg.norm(P - C, axis=-1)])
        d = np.where(bad, alt, d)
    return d


def subdivide(X: np.ndarray, T: np.ndarray, lmax: float, max_tris: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """삼각형을 최장 변 중점으로 이등분해 모든 변 ≤ lmax(같은 평면 — 면 거리 불변, 비적합 T 접합 허용). 결정적."""
    X = np.asarray(X, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
    pts = [X]
    n_pts = X.shape[0]
    done = []
    cur = T
    Xall = X
    while cur.size:
        a, b, c = Xall[cur[:, 0]], Xall[cur[:, 1]], Xall[cur[:, 2]]
        L = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 1)
        big = L.max(axis=1) > lmax
        done.append(cur[~big])
        cur, L = cur[big], L[big]
        if not cur.size:
            break
        if max_tris is not None and sum(x.shape[0] for x in done) + 2 * cur.shape[0] > max_tris:
            done.append(cur)                                # 상한: 더 나누지 않음(후보 검색 근사)
            break
        e = np.argmax(L, axis=1)                            # 0: 0-1, 1: 1-2, 2: 2-0
        rot = np.stack([cur[np.arange(cur.shape[0]), (e + j) % 3] for j in range(3)], 1)   # 최장 변 = rot0-rot1
        mid = 0.5 * (Xall[rot[:, 0]] + Xall[rot[:, 1]])
        mi = n_pts + np.arange(mid.shape[0], dtype=np.int64)
        n_pts += mid.shape[0]
        pts.append(mid)
        Xall = np.concatenate([Xall, mid])
        cur = np.concatenate([np.stack([rot[:, 0], mi, rot[:, 2]], 1), np.stack([mi, rot[:, 1], rot[:, 2]], 1)])
    Tout = np.concatenate(done) if done else np.zeros((0, 3), np.int64)
    return Xall, Tout


def _tri_area(X, T) -> float:
    return float(0.5 * np.linalg.norm(np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]]), axis=1).sum())


def mesh_tris(X: np.ndarray, conn: np.ndarray, et: np.ndarray) -> np.ndarray:
    """쉘 요소 → 삼각형(quad 는 0-1-2, 0-2-3)."""
    conn = np.asarray(conn, dtype=np.int64)
    q = np.asarray(et).astype(int) == 4
    t1 = conn[:, :3]
    t2 = conn[q][:, [0, 2, 3]]
    return np.concatenate([t1, t2])


def _stride(n: int, m: int) -> np.ndarray:
    """0..n-1 에서 고정 간격 m 개(결정적)."""
    if n <= m:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, m).round().astype(np.int64))


def _dist_to_tris(P: np.ndarray, X: np.ndarray, T: np.ndarray, chunk: int = 50000) -> np.ndarray:
    from scipy.spatial import cKDTree
    if not P.shape[0]:
        return np.zeros(0)
    cen = (X[T[:, 0]] + X[T[:, 1]] + X[T[:, 2]]) / 3.0
    k = int(min(KNN, T.shape[0]))
    tree = cKDTree(cen)
    out = np.empty(P.shape[0])
    for s in range(0, P.shape[0], chunk):
        p = P[s:s + chunk]
        _d, idx = tree.query(p, k=k)
        idx = np.asarray(idx).reshape(p.shape[0], k)
        tri = T[idx]                                        # (n,k,3)
        d = point_tri_dist(p[:, None, :], X[tri[..., 0]], X[tri[..., 1]], X[tri[..., 2]])
        out[s:s + chunk] = d.min(axis=1)
    # 정확화: k 후보 최솟값 D 는 상한 — 진짜 최근접 삼각형의 중심은 D + rc(중심-꼭짓점 최대 거리) 안에 있다. D > 0 인 점만
    # 그 반경 안 삼각형 전부로 다시 계산(가는 띠 면 근처처럼 가까운 중심 k 개가 모두 다른 삼각형인 경우).
    rc = float(np.max(np.linalg.norm(X[T] - cen[:, None, :], axis=2)))
    for i in np.flatnonzero(out > DIST_EPS_MM).tolist():
        cand = tree.query_ball_point(P[i], out[i] + rc)
        if len(cand) > k:
            tri = T[np.asarray(cand, dtype=np.int64)]
            out[i] = min(out[i], float(point_tri_dist(P[i][None, :], X[tri[:, 0]], X[tri[:, 1]], X[tri[:, 2]]).min()))
    return out


def fidelity(S_X: np.ndarray, S_T: np.ndarray, mesh: dict, h: float, rc: dict) -> dict:
    """C2-D-13 양방향 거리 지표 {hausdorff_mm, max_dev_mm, p95_mm, area_ratio, deflection_mm, samples, warn_mm, fail_mm,
    over_warn}. 샘플 > fidelity.samples_max 면 고정 간격 추출."""
    fc = rc["fidelity"]
    smax = int(fc["samples_max"])
    X = np.asarray(mesh["x0"], dtype=np.float64)
    MT = mesh_tris(X, mesh["conn"], mesh["elem_type"])
    sx, st = subdivide(S_X, S_T, float(h), max_tris=max(4 * smax, int(S_T.shape[0])))
    pm = X[_stride(X.shape[0], smax)]
    d_ms = _dist_to_tris(pm, sx, st)
    cen = (sx[st[:, 0]] + sx[st[:, 1]] + sx[st[:, 2]]) / 3.0
    ps = np.concatenate([sx, cen])
    ps = ps[_stride(ps.shape[0], smax)]
    d_sm = _dist_to_tris(ps, X, MT)
    allv = np.concatenate([d_ms, d_sm])
    a_s = _tri_area(S_X, S_T)
    a_m = _tri_area(X, MT)
    haus = float(max(d_ms.max(initial=0.0), d_sm.max(initial=0.0)))
    warn = float(fc["warn_mm"])
    fail = fc.get("fail_mm")
    return {"hausdorff_mm": round(haus, 6), "max_dev_mm": round(float(d_ms.max(initial=0.0)), 6),
            "p95_mm": round(float(np.percentile(allv, 95)) if allv.size else 0.0, 6),
            "area_ratio": round(a_m / a_s, 6) if a_s > 0 else None,
            "deflection_mm": float(rc["linear_deflection_mm"]), "samples": int(allv.size),
            "warn_mm": warn, "fail_mm": None if fail is None else float(fail), "over_warn": bool(haus > warn)}


# ---------------------------------------------------------------- 삼각화 정리(R4)
def merge_nodes(X: np.ndarray, T: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, int]:
    """거리 ≤ tol 노드를 가장 작은 번호로 합치고(합집합-찾기, 결정적) 퇴화·중복 삼각형·미사용 노드 제거.
    반환 (X', T', 합친 노드 수)."""
    from scipy.spatial import cKDTree
    X = np.asarray(X, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
    n = X.shape[0]
    rep = np.arange(n)
    if n and tol > 0:
        pairs = cKDTree(X).query_pairs(float(tol), output_type="ndarray")
        if pairs.size:
            pairs = np.sort(pairs, axis=1)
            pairs = pairs[np.lexsort((pairs[:, 1], pairs[:, 0]))]

            def find(a):
                while rep[a] != a:
                    rep[a] = rep[rep[a]]
                    a = rep[a]
                return a
            for a, b in pairs.tolist():
                ra, rb = find(a), find(b)
                if ra != rb:
                    rep[max(ra, rb)] = min(ra, rb)
            for i in range(n):
                rep[i] = find(i)
    n_merged = int(np.sum(rep != np.arange(n)))
    T = rep[T]
    ok = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])
    T = T[ok]
    _u, first = np.unique(np.sort(T, axis=1), axis=0, return_index=True)
    T = T[np.sort(first)]
    used = np.unique(T)
    remap = -np.ones(n, dtype=np.int64)
    remap[used] = np.arange(used.size)
    return X[used], remap[T], n_merged


# ---------------------------------------------------------------- 본체
def _fail(code: str, msg: str) -> EslError:
    return EslError(code, msg)


def occ_triangulate(gmsh, rc: dict) -> tuple[np.ndarray, np.ndarray]:
    """R3 현재 세션 OCC 형상 → 삼각화 (X0 노드 태그 순, T0 노드 인덱스). linear/angular deflection = remesh 설정.
    실패 = REMESH_FAILED | REMESH_STL_EMPTY. ④ defeature 단계 충실도 기준 S0(``esl.geom.defeature.reference_tris``)도 이 함수."""
    try:
        gmsh.option.setNumber("Mesh.StlLinearDeflection", float(rc["linear_deflection_mm"]))
        gmsh.option.setNumber("Mesh.StlLinearDeflectionRelative", 0)
        gmsh.option.setNumber("Mesh.StlAngularDeflection", math.radians(float(rc["angular_deflection_deg"])))
        gmsh.model.mesh.importStl()
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        types, _etags, enodes = gmsh.model.mesh.getElements(2)
    except Exception as exc:                                # noqa: BLE001
        raise _fail("REMESH_FAILED", f"OCC 삼각화 실패: {exc}") from None
    tags = np.asarray(tags, dtype=np.int64)
    X0 = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    tri = [np.asarray(nd, dtype=np.int64).reshape(-1, 3) for t, nd in zip(types, enodes) if int(t) == 2]
    T0 = np.concatenate(tri) if tri else np.zeros((0, 3), np.int64)
    if not T0.shape[0]:
        raise _fail("REMESH_STL_EMPTY", "STEP 에서 삼각화를 만들지 못함(면 없음)")
    if T0.shape[0] > int(rc["stl_max_tris"]):
        raise _fail("REMESH_FAILED", f"삼각화 {T0.shape[0]}개 > 상한 remesh.stl_max_tris {rc['stl_max_tris']}")
    o = np.argsort(tags, kind="stable")
    tags, X0 = tags[o], X0[o]
    return X0, np.searchsorted(tags, T0)


def remesh_file(src: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None, normal_ref=None,
                out_dir: str | None = None) -> tuple[dict, dict]:
    """STEP → 삼각형 재메시 (mesh dict, mesh.json dict). out_dir 이 있으면 mesh.npz·mesh.json(·remesh_stl.npz) 를 쓴다.
    이 프로세스 안에서 gmsh 실행(격리는 ``mesh_gmsh.run_isolated(kind="remesh")``). 실패 = EslError(code =
    REMESH_FAILED | REMESH_STL_EMPTY | REMESH_CLASSIFY_FAILED | REMESH_FIDELITY | MESH_TOO_LARGE | GMSH_UNAVAILABLE |
    REMESH_UNAVAILABLE)."""
    from esl.doe import mesh_gmsh as mg
    from esl.doe import opt_settings
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise _fail("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    if not hasattr(gmsh.model.mesh, "importStl"):
        raise _fail("REMESH_UNAVAILABLE", f"gmsh {getattr(gmsh, '__version__', '?')} 에 model.mesh.importStl 이 없음")
    mc = cfg["mesh"]
    rc = _rcfg(cfg)
    h = mg.check_h(h, mc)
    opts = mg.gmsh_options(h, mc)
    gopts = mg.geometry_options(mc)
    t0 = time.monotonic()
    warns: list[dict] = []
    infos: list[dict] = []
    rec: dict = {"feature_angle_deg": float(rc["feature_angle_deg"]), "curve_angle_deg": float(rc["curve_angle_deg"]),
                 "linear_deflection_mm": float(rc["linear_deflection_mm"]),
                 "angular_deflection_deg": float(rc["angular_deflection_deg"]), "merge_tol_mm": float(rc["merge_tol_mm"])}
    dfi = None
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        ver = str(getattr(gmsh, "__version__", ""))
        occ_ver = occ_version(gmsh)
        # R1 가져오기
        try:
            gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
            for k, v in gopts.items():
                gmsh.option.setNumber(k, v)
            gmsh.model.occ.importShapes(os.fspath(src))
            gmsh.model.occ.synchronize()
            faces = [int(t) for _d, t in gmsh.model.getEntities(2)]
            rec["n_faces"] = len(faces)
            rec["area_mm2"] = round(float(sum(gmsh.model.occ.getMass(2, t) for t in faces)), 6)
        except Exception as exc:                            # noqa: BLE001
            raise _fail("REMESH_FAILED", f"형상 파일을 읽지 못함: {exc}") from None
        if not faces:
            raise _fail("REMESH_STL_EMPTY", "STEP 에 면이 없음")
        # R2 작은 구멍 메움(CAD 단계, C2-D-12) — 구멍 둘레 분할은 재메시 곡선에 적용하지 않음
        df = mc.get("defeature")
        if isinstance(df, dict) and df.get("enabled"):
            dfi = mg.defeature(gmsh, dict(df, hole_elems=0), h)
            for w in dfi.get("warnings") or []:
                warns.append({"code": "DEFEATURE_SKIPPED", "message": str(w)})
            if int(df.get("hole_elems") or 0) > 0:
                infos.append({"code": "REMESH_HOLE_SIZING_SKIPPED",
                              "message": "재메시 곡선에는 구멍 둘레 분할(hole_elems)을 적용하지 않음"})
            if dfi.get("filled"):
                # 다시 만든 평면 면은 이웃과 OCC 모서리를 공유하지 않아 BRepMesh 경계 노드가 어긋남(면이 떨어진 삼각화) →
                # 이 세션 형상을 임시 BREP 으로 쓰고 봉합(OCCSewFaces 1)해 다시 읽음. 임시 파일은 출력 폴더(없으면 시스템 임시)
                import tempfile
                try:
                    with tempfile.TemporaryDirectory(prefix="remesh_", dir=out_dir if out_dir and os.path.isdir(out_dir)
                                                     else None) as td:
                        bp = os.path.join(td, "defeatured.brep")
                        gmsh.write(bp)
                        gmsh.clear()
                        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
                        gmsh.model.occ.importShapes(bp)
                        gmsh.model.occ.synchronize()
                    rec["resewn"] = True
                except Exception as exc:                    # noqa: BLE001
                    raise _fail("REMESH_FAILED", f"작은 구멍 메움 뒤 형상 봉합 실패: {exc}") from None
        # R3 OCC 삼각화(v0.16.1 함수로 분리 — esl.geom.defeature.reference_tris 와 같은 코드)
        X0, T0 = occ_triangulate(gmsh, rc)
        # R4 이산 면 1개로 병합
        S_X, S_T, n_merged = merge_nodes(X0, T0, float(rc["merge_tol_mm"]))
        rec.update(n_stl_tris=int(T0.shape[0]), n_stl_nodes=int(X0.shape[0]), n_merged=n_merged,
                   n_tris=int(S_T.shape[0]), n_nodes_stl=int(S_X.shape[0]))
        if not S_T.shape[0]:
            raise _fail("REMESH_STL_EMPTY", "병합 뒤 삼각형이 없음")
        try:
            # 노드 병합은 merge_nodes(절대 거리 merge_tol_mm) 로 끝냄 — gmsh removeDuplicateNodes 는 Geometry.Tolerance 를
            # 모델 크기에 비례해 써서(4.13.1 실측: 0.001 → 21067 노드가 1435 로 뭉개짐) 쓰지 않음
            gmsh.clear()
            s = gmsh.model.addDiscreteEntity(2)
            gmsh.model.mesh.addNodes(2, s, list(range(1, S_X.shape[0] + 1)), S_X.ravel().tolist())
            gmsh.model.mesh.addElementsByType(s, 2, [], (S_T + 1).ravel().tolist())
        except Exception as exc:                            # noqa: BLE001
            raise _fail("REMESH_FAILED", f"삼각화 병합 실패: {exc}") from None
        # R5 면 분류 → 기하
        try:
            gmsh.model.mesh.classifySurfaces(math.radians(float(rc["feature_angle_deg"])), True, True,
                                             math.radians(float(rc["curve_angle_deg"])))
            gmsh.model.mesh.createGeometry()
            rec["n_patches"] = len(gmsh.model.getEntities(2))
        except Exception as exc:                            # noqa: BLE001
            raise _fail("REMESH_CLASSIFY_FAILED",
                        f"면 분류(특징각 {rc['feature_angle_deg']}°)에 실패: {exc}") from None
        # R6 재메시(모델 전체, algorithms 차례로 — 면 폴백 없음)
        for k, v in opts.items():
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.RecombineAll", 1 if rc["recombine"] else 0)
        attempts, used = [], None
        algs = [int(a) for a in (rc.get("algorithms") or [int(mc["algorithm"])])]
        for a in algs:
            gmsh.option.setNumber("Mesh.Algorithm", a)
            try:
                gmsh.model.mesh.generate(2)
                used = a
                break
            except Exception as exc:                        # noqa: BLE001
                attempts.append({"algorithm": a, "error": str(exc)})
                try:
                    gmsh.model.mesh.clear()
                except Exception:                           # noqa: BLE001
                    pass
        rec["attempts"] = attempts
        if used is None:
            first = attempts[0]["error"] if attempts else "?"
            last = attempts[-1]["error"] if attempts else "?"
            raise _fail("REMESH_FAILED", f"삼각형 재메시 실패(알고리즘 {algs}): {first}"
                        + (f"; 마지막: {last}" if last != first else ""))
        rec["algorithm"] = used
        # R7 추출
        try:
            X, conn, et = mg._extract(gmsh)
        except EslError as exc:
            raise _fail("REMESH_FAILED", exc.message) from None
    finally:
        gmsh.finalize()
    mesh, info = mg.build_mesh(X, conn, et, props, normal_ref)
    oc = opt_cfg or opt_settings(None)
    qual = mg.quality(mesh, cfg, oc)
    errs = list(qual["errors"])
    fid = None
    if not any(e.get("code") == "MESH_TOO_LARGE" for e in errs):
        fid = fidelity(S_X, S_T, mesh, h, rc)            # R8
        if fid["over_warn"]:
            warns.append({"code": "REMESH_FIDELITY_WARN",
                          "message": f"재메시가 단순화 형상과 최대 {fid['hausdorff_mm']:.3f} mm 다름(> 경고 {fid['warn_mm']:g} mm)"})
        if fid["fail_mm"] is not None and fid["hausdorff_mm"] > fid["fail_mm"]:
            errs.append({"code": "REMESH_FIDELITY",
                         "message": f"재메시가 원 형상과 최대 {fid['hausdorff_mm']:.3f} mm 다릅니다(> {fid['fail_mm']:g} mm)"})
    opts_rec = dict(opts, **gopts)
    opts_rec["Mesh.Algorithm"] = used
    opts_rec["Mesh.RecombineAll"] = 1 if rc["recombine"] else 0
    meta = {"schema": SCHEMA, "method": "remesh", "gmsh_version": ver, "occ_version": occ_ver, "options": opts_rec,
            "h": h, "props": dict(props), "n_nodes": int(mesh["node_id"].size), "n_elems": int(mesh["elem_id"].size),
            "quad_frac": qual["quad_frac"], "quality": qual["metrics"], "errors": errs,
            "warnings": list(qual["warnings"]) + warns, "infos": infos, **info, "remesh": rec, "fidelity": fid,
            "seconds": round(time.monotonic() - t0, 3)}
    if dfi is not None:
        meta["defeature"] = dfi
    if out_dir:
        from esl.library import _util as U
        os.makedirs(out_dir, exist_ok=True)
        mg.save_npz_det(os.path.join(out_dir, mg.MESH_NPZ), {k: mesh[k] for k in mg.MESH_KEYS})
        if rc.get("keep_stl"):
            mg.save_npz_det(os.path.join(out_dir, STL_NPZ), {"x": S_X, "tri": S_T})
        U.write_json(os.path.join(out_dir, mg.MESH_JSON), {k: v for k, v in meta.items() if k != "seconds"}
                     | {"seconds": meta["seconds"]})
    if errs:
        e = errs[0]
        code = e["code"] if e["code"] in ("MESH_TOO_LARGE", "REMESH_FIDELITY") else "REMESH_FAILED"
        raise _fail(code, f"재메시 품질 오류 {e['code']}: {e['message']}")
    return mesh, meta
