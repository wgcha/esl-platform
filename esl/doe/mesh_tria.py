"""④ 마지막 사다리 단계 OCC 삼각형 폴백(v0.16.3, 계약 esl_compare_mesh_options.md C2-D-28).

CAD 면 단위 gmsh 메싱(면 매개변수화)도, gmsh 이산 재메시(classifySurfaces·createGeometry)도 쓰지 않는다. STEP 형상의 OCC
BRepMesh 삼각화(gmsh ``model.mesh.importStl`` = BRepMesh_IncrementalMesh — periodic·퇴화 면도 삼각화)를 노드 병합한 뒤
**그대로** 삼각형 쉘 메시로 받는다. 크기 맞춤 = 긴 변 중점 분할(적합 — 공유 변을 같이 나눔, 새 점은 원 삼각형 위라 형상 불변)
+ 같은 평면 안 변 뒤집기(Delaunay — 가는 삼각형 개선, 형상 불변). 짧은 변 붕괴는 하지 않음(형상·위상 위험 — 작은 요소는 남음).

- BRepMesh 편차 = ``tria.deflection_factor`` × h(기본 0.05 × 3 = 0.15 mm), 각 편차 ``tria.angular_deflection_deg``.
- 삼각화가 없는 면 = 정리 옵션(OCCFix*)을 끄고 다시 가져와 재시도 → 그래도 없으면 ``tria.allow_missing_faces`` 이면 경고
  ``MESH_TRIA_HOLES``(면 id) 후 계속, 아니면(또는 그 때문에 메시가 끊기면) ``CAD_INVALID``(면 id).
- 충실도 = ``mesh_remesh.fidelity``(S = 이 BRepMesh 삼각화, deflection = 위 편차) — 원 CAD 대비 ≤ hausdorff + 편차.
- 경고 ``MESH_TRIA_FALLBACK`` 항상(삼각형만·CAD 특징선 비추종).
실행 = ``mesh_gmsh.run_isolated(kind="tria")`` 의 spawn 자식. 숫자는 모두 설정 ``bead_doe.compare.tria``.
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

from esl.errors import EslError

SCHEMA = "esl/doe_mesh/1"


def _tcfg(cfg: dict) -> dict:
    from esl.doe import DEFAULTS, _deep_merge
    over = ((cfg.get("compare") or {}).get("tria")) if isinstance(cfg, dict) else None
    return _deep_merge(DEFAULTS["compare"]["tria"], over if isinstance(over, dict) else {})


# ---------------------------------------------------------------- 삼각화
def merge_nodes_fast(X: np.ndarray, T: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, int]:
    """``mesh_remesh.merge_nodes`` 와 같은 결과(대표 = 성분 최소 번호, 퇴화·중복 삼각형·미사용 노드 제거)를 희소 연결 성분으로
    (수백만 노드에서도 파이썬 반복 없음)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    X = np.asarray(X, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
    n = X.shape[0]
    rep = np.arange(n)
    if n and tol > 0:
        pairs = cKDTree(X).query_pairs(float(tol), output_type="ndarray")
        if pairs.size:
            G = coo_matrix((np.ones(pairs.shape[0]), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
            _k, lab = connected_components(G, directed=False)
            mn = np.full(lab.max() + 1, n, dtype=np.int64)
            np.minimum.at(mn, lab, np.arange(n))
            rep = mn[lab]
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


def _import(gmsh, src: str, mc: dict, nofix: bool) -> list[int]:
    from esl.doe import mesh_gmsh as mg
    gmsh.clear()
    gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
    for k, v in mg.geometry_options(mc).items():
        gmsh.option.setNumber(k, 0 if nofix and k in mg.OCC_FIX_KEYS else v)
    mg.set_import_labels(gmsh, mc)
    gmsh.model.occ.importShapes(os.fspath(src))
    gmsh.model.occ.synchronize()
    return [int(t) for _d, t in gmsh.model.getEntities(2)]


def _probe_faces(gmsh, src: str, mc: dict) -> int:
    """정리·봉합 없이 가져와 면 수만 셈(라벨 안 읽으면 수천 면도 수 초). 읽기 실패 = 0."""
    from esl.doe import mesh_gmsh as mg
    try:
        gmsh.clear()
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)
        for k in mg.OCC_FIX_KEYS:
            gmsh.option.setNumber(k, 0)
        mg.set_import_labels(gmsh, mc)
        gmsh.model.occ.importShapes(os.fspath(src))
        gmsh.model.occ.synchronize()
        n = len(gmsh.model.getEntities(2))
    except Exception:                                       # noqa: BLE001
        n = 0
    gmsh.clear()
    return n


def occ_tris(gmsh, defl: float, ang_deg: float) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """현재 세션 OCC 형상 → BRepMesh 삼각화 (X 노드 태그 순, T, 삼각형이 없는 면 태그 목록)."""
    gmsh.option.setNumber("Mesh.StlLinearDeflection", float(defl))
    gmsh.option.setNumber("Mesh.StlLinearDeflectionRelative", 0)
    gmsh.option.setNumber("Mesh.StlAngularDeflection", math.radians(float(ang_deg)))
    gmsh.model.mesh.importStl()
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags, dtype=np.int64)
    X = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    tri, missing = [], []
    for _d, s in gmsh.model.getEntities(2):
        types, _et, nodes = gmsh.model.mesh.getElements(2, int(s))
        got = [np.asarray(nd, dtype=np.int64).reshape(-1, 3) for t, nd in zip(types, nodes) if int(t) == 2]
        k = sum(x.shape[0] for x in got)
        if k == 0:
            missing.append(int(s))
        tri += got
    T = np.concatenate(tri) if tri else np.zeros((0, 3), np.int64)
    o = np.argsort(tags, kind="stable")
    tags, X = tags[o], X[o]
    return X, np.searchsorted(tags, T), sorted(missing)


# ---------------------------------------------------------------- 크기 맞춤(적합 분할 + 평면 안 뒤집기)
def _edges(T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """고유 변 (E[m,2] 정렬) 과 삼각형별 변 번호 te[n,3](변 j = (v_j, v_{j+1}))."""
    e = np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1).reshape(-1, 2)
    e = np.sort(e, axis=1)
    E, inv = np.unique(e, axis=0, return_inverse=True)
    return E, inv.reshape(-1, 3)


def split_long(X: np.ndarray, T: np.ndarray, lmax: float, max_iters: int, max_tris: int) -> tuple[np.ndarray, np.ndarray, int]:
    """모든 변 ≤ lmax 가 될 때까지 긴 변 중점 분할(적합: 표시된 변은 양쪽 삼각형이 같이 나눔 — 1변 2분할, 2변 3분할(짧은
    대각), 3변 4분할). 결정적. 반환 (X, T, 반복 수). 삼각형 수가 max_tris 를 넘을 것 같으면 멈춤."""
    X = np.asarray(X, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64)
    it = 0
    for it in range(1, int(max_iters) + 1):
        E, te = _edges(T)
        L = np.linalg.norm(X[E[:, 1]] - X[E[:, 0]], axis=1)
        mark = L > lmax
        if not mark.any():
            return X, T, it - 1
        # 가장 긴 변 이등분 우선(가는 삼각형을 그대로 닮게 나누지 않음): 표시 = 긴 변 중 어느 삼각형의 최장 변인 것
        lt = L[te]
        mark &= np.zeros(E.shape[0], bool) | np.bincount(te[np.arange(te.shape[0]), np.argmax(lt, axis=1)],
                                                         minlength=E.shape[0]).astype(bool)
        if not mark.any():
            return X, T, it - 1
        mi = -np.ones(E.shape[0], dtype=np.int64)
        idx = np.flatnonzero(mark)
        mi[idx] = X.shape[0] + np.arange(idx.size)
        Xn = np.concatenate([X, 0.5 * (X[E[idx, 0]] + X[E[idx, 1]])])
        m = mi[te]                                           # (n,3) 변 j 중점 번호 | -1
        k = (m >= 0).sum(axis=1)
        if T.shape[0] + int(k.sum()) > int(max_tris):
            return X, T, it - 1
        out = [T[k == 0]]
        # 1변: 변 j=(a,b), 남은 꼭짓점 c → (a,m,c), (m,b,c)
        s1 = np.flatnonzero(k == 1)
        if s1.size:
            j = np.argmax(m[s1] >= 0, axis=1)
            a, b, c = T[s1, j], T[s1, (j + 1) % 3], T[s1, (j + 2) % 3]
            mm = m[s1, j]
            out += [np.stack([a, mm, c], 1), np.stack([mm, b, c], 1)]
        # 2변: 안 나뉜 변 j=(a,b), c 반대 꼭짓점; 변 b-c 중점 p, c-a 중점 q → (q,p,c), 그리고 사각형 a,b,p,q 를 짧은 대각으로
        s2 = np.flatnonzero(k == 2)
        if s2.size:
            j = np.argmax(m[s2] < 0, axis=1)
            a, b, c = T[s2, j], T[s2, (j + 1) % 3], T[s2, (j + 2) % 3]
            p, q = m[s2, (j + 1) % 3], m[s2, (j + 2) % 3]
            out.append(np.stack([q, p, c], 1))
            d_ap = np.linalg.norm(Xn[a] - Xn[p], axis=1)
            d_bq = np.linalg.norm(Xn[b] - Xn[q], axis=1)
            use_ap = d_ap <= d_bq
            out += [np.where(use_ap[:, None], np.stack([a, b, p], 1), np.stack([a, b, q], 1)),
                    np.where(use_ap[:, None], np.stack([a, p, q], 1), np.stack([b, p, q], 1))]
        s3 = np.flatnonzero(k == 3)
        if s3.size:
            a, b, c = T[s3, 0], T[s3, 1], T[s3, 2]
            mab, mbc, mca = m[s3, 0], m[s3, 1], m[s3, 2]
            out += [np.stack([a, mab, mca], 1), np.stack([mab, b, mbc], 1), np.stack([mca, mbc, c], 1),
                    np.stack([mab, mbc, mca], 1)]
        X, T = Xn, np.concatenate(out)
    return X, T, it


def _normals(X, T):
    n = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    return n / np.maximum(ln, 1e-300)[:, None], ln


def flip_planar(X: np.ndarray, T: np.ndarray, coplanar_deg: float, passes: int) -> tuple[np.ndarray, int]:
    """같은 평면(두 삼각형 법선 각 ≤ coplanar_deg) 안 내부 변만 Delaunay 뒤집기(맞은편 두 각 합 > π). 형상 불변(같은 평면).
    한 번에 서로 겹치지 않는 변만 뒤집고 passes 번 반복. 반환 (T, 뒤집은 수)."""
    T = np.asarray(T, dtype=np.int64).copy()
    cmin = math.cos(math.radians(float(coplanar_deg)))
    total = 0
    for _ in range(int(passes)):
        e = np.sort(np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1).reshape(-1, 2), axis=1)
        tri = np.repeat(np.arange(T.shape[0]), 3)
        loc = np.tile(np.arange(3), T.shape[0])
        o = np.lexsort((e[:, 1], e[:, 0]))
        e, tri, loc = e[o], tri[o], loc[o]
        same = np.all(e[1:] == e[:-1], axis=1)
        two = np.flatnonzero(same & np.r_[True, ~same[:-1]] & np.r_[~same[1:], True])
        if not two.size:
            break
        t0, t1, l0, l1 = tri[two], tri[two + 1], loc[two], loc[two + 1]
        n, _ln = _normals(X, T)
        ok = np.einsum("ij,ij->i", n[t0], n[t1]) >= cmin
        c0 = T[t0, (l0 + 2) % 3]                             # t0 의 그 변 맞은편 꼭짓점
        c1 = T[t1, (l1 + 2) % 3]
        a, b = T[t0, l0], T[t0, (l0 + 1) % 3]

        def ang(p, u, v):
            x, y = X[u] - X[p], X[v] - X[p]
            return np.arccos(np.clip(np.einsum("ij,ij->i", x, y) / np.maximum(
                np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1), 1e-300), -1, 1))
        bad = ok & (ang(c0, a, b) + ang(c1, a, b) > math.pi + 1e-9) & (c0 != c1)
        # 뒤집은 뒤 두 새 삼각형이 원 법선과 같은 방향이어야(볼록 사각형)
        nn = n[t0]                                           # 사각형 a, c1, b, c0(반시계) → (c0, a, c1)·(c0, c1, b)
        n_new0 = np.cross(X[a] - X[c0], X[c1] - X[c0])
        n_new1 = np.cross(X[c1] - X[c0], X[b] - X[c0])
        bad &= (np.einsum("ij,ij->i", n_new0, nn) > 0) & (np.einsum("ij,ij->i", n_new1, nn) > 0)
        cand = np.flatnonzero(bad)
        if not cand.size:
            break
        # 겹치지 않는 변만(결정적): 삼각형마다 그 삼각형을 쓰는 후보 중 가장 작은 번호 → 두 삼각형 모두에서 자기가 최소인 후보
        best = np.full(T.shape[0], np.iinfo(np.int64).max, dtype=np.int64)
        np.minimum.at(best, t0[cand], cand)
        np.minimum.at(best, t1[cand], cand)
        pk = cand[(best[t0[cand]] == cand) & (best[t1[cand]] == cand)]
        T[t0[pk]] = np.stack([c0[pk], a[pk], c1[pk]], 1)
        T[t1[pk]] = np.stack([c0[pk], c1[pk], b[pk]], 1)
        total += int(pk.size)
    return T, total


def smooth_planar(X: np.ndarray, T: np.ndarray, coplanar_deg: float, iters: int) -> tuple[np.ndarray, int]:
    """평면 안 내부 노드만 이웃 평균으로(접선 Laplacian — 둘레 삼각형이 모두 같은 평면(coplanar_deg)이고 경계·특징선이 아닌
    노드: 평균점이 같은 평면 위라 형상 불변). 움직인 뒤 둘레 삼각형이 뒤집히면 그 노드는 되돌림. 반환 (X, 움직인 노드 수)."""
    from scipy.sparse import coo_matrix
    X = np.asarray(X, dtype=np.float64).copy()
    n = X.shape[0]
    cmin = math.cos(math.radians(float(coplanar_deg)))
    nt, _ = _normals(X, T)
    E = np.sort(np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1).reshape(-1, 2), axis=1)
    Eu, cnt = np.unique(E, axis=0, return_counts=True)
    fixed = np.zeros(n, bool)
    fixed[Eu[cnt != 2].ravel()] = True                       # 경계·비다양체 변 끝
    # 노드별 법선 산포: 둘레 삼각형 법선이 평균 법선과 coplanar_deg 안
    vi = T.ravel()
    ti = np.repeat(np.arange(T.shape[0]), 3)
    acc = np.zeros((n, 3))
    np.add.at(acc, vi, nt[ti])
    nn = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-300)[:, None]
    dev = np.ones(n)
    np.minimum.at(dev, vi, np.einsum("ij,ij->i", nt[ti], nn[vi]))
    fixed |= dev < cmin
    A = coo_matrix((np.ones(Eu.shape[0] * 2), (np.r_[Eu[:, 0], Eu[:, 1]], np.r_[Eu[:, 1], Eu[:, 0]])), shape=(n, n)).tocsr()
    deg = np.asarray(A.sum(axis=1)).ravel()
    free = ~fixed & (deg > 0)
    moved = 0
    for _ in range(int(iters)):
        Xa = A @ X / np.maximum(deg, 1)[:, None]
        Xn = np.where(free[:, None], Xa, X)
        n2, _l = _normals(Xn, T)
        flip = np.einsum("ij,ij->i", n2, nt) <= 0.5               # 60° 넘게 돈 삼각형 = 접힘 → 그 꼭짓점 되돌림
        back = np.zeros(n, bool)
        back[T[flip].ravel()] = True
        Xn[back] = X[back]
        moved = int(np.sum(np.any(Xn != X, axis=1)))
        X = Xn
    return X, moved


def _free_nodes(X: np.ndarray, T: np.ndarray, coplanar_deg: float) -> np.ndarray:
    """평면 안 내부 노드(경계·비다양체 변 끝이 아니고 둘레 삼각형 법선이 모두 coplanar_deg 안)."""
    n = X.shape[0]
    cmin = math.cos(math.radians(float(coplanar_deg)))
    nt, _ = _normals(X, T)
    E = np.sort(np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], axis=1).reshape(-1, 2), axis=1)
    Eu, cnt = np.unique(E, axis=0, return_counts=True)
    fixed = np.zeros(n, bool)
    fixed[Eu[cnt != 2].ravel()] = True
    vi = T.ravel()
    ti = np.repeat(np.arange(T.shape[0]), 3)
    acc = np.zeros((n, 3))
    np.add.at(acc, vi, nt[ti])
    nn = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-300)[:, None]
    dev = np.ones(n)
    np.minimum.at(dev, vi, np.einsum("ij,ij->i", nt[ti], nn[vi]))
    fixed |= dev < cmin
    return ~fixed


def collapse_short(X: np.ndarray, T: np.ndarray, lmin: float, coplanar_deg: float, passes: int,
                   lmax: float) -> tuple[np.ndarray, np.ndarray, int]:
    """짧은 변(< lmin) 붕괴 — 두 끝이 모두 매끈한 면 안 내부 노드(둘레 법선 산포 ≤ coplanar_deg = 설정 collapse_deg)일 때만
    (평면이면 형상 불변, 곡면이면 중점 처짐 ≤ L²/(8R) — 충실도 지표에 그대로 잡힘). 경계·특징선 노드는 움직이지 않음. 한 번에 서로 둘레가
    겹치지 않는 변만, 붕괴 뒤 둘레 삼각형이 뒤집히거나 lmax 를 넘는 변이 생기면 취소. 반환 (X, T, 붕괴 수)."""
    X = np.asarray(X, dtype=np.float64).copy()
    T = np.asarray(T, dtype=np.int64).copy()
    total = 0
    for _ in range(int(passes)):
        free = _free_nodes(X, T, coplanar_deg)
        E, _te = _edges(T)
        L = np.linalg.norm(X[E[:, 1]] - X[E[:, 0]], axis=1)
        cand = np.flatnonzero((L < lmin) & free[E[:, 0]] & free[E[:, 1]])
        if not cand.size:
            break
        cand = cand[np.argsort(L[cand], kind="stable")]
        # 노드 → 삼각형
        vi = T.ravel()
        ti = np.repeat(np.arange(T.shape[0]), 3)
        o = np.argsort(vi, kind="stable")
        vs, ts = vi[o], ti[o]
        starts = np.searchsorted(vs, np.arange(X.shape[0] + 1))
        nt, _ = _normals(X, T)
        lock = np.zeros(X.shape[0], bool)
        alive = np.ones(T.shape[0], bool)
        done = 0
        for i in cand.tolist():
            a, b = int(E[i, 0]), int(E[i, 1])
            if lock[a] or lock[b]:
                continue
            ring = np.unique(np.r_[ts[starts[a]:starts[a + 1]], ts[starts[b]:starts[b + 1]]])
            ring = ring[alive[ring]]
            rv = np.unique(T[ring].ravel())
            if lock[rv].any():
                continue
            p = 0.5 * (X[a] + X[b])
            Tr = np.where(T[ring] == b, a, T[ring])
            keep = ~((Tr[:, 0] == Tr[:, 1]) | (Tr[:, 1] == Tr[:, 2]) | (Tr[:, 0] == Tr[:, 2]))
            Xs = X.copy() if False else None              # noqa: F841 - 가독용
            old = X[a].copy()
            X[a] = p
            Tk = Tr[keep]
            n2 = np.cross(X[Tk[:, 1]] - X[Tk[:, 0]], X[Tk[:, 2]] - X[Tk[:, 0]])
            ok = np.all(np.einsum("ij,ij->i", n2, nt[ring[keep]]) > 0)
            if ok:
                el = np.linalg.norm(X[Tk] - X[np.roll(Tk, 1, axis=1)], axis=2)
                ok = bool(el.max(initial=0.0) <= lmax)
            # 같은 두 꼭짓점을 가진 삼각형 쌍(비다양체) 방지
            if ok and np.unique(np.sort(Tk, axis=1), axis=0).shape[0] != Tk.shape[0]:
                ok = False
            if not ok:
                X[a] = old
                continue
            T[ring] = Tr
            alive[ring[~keep]] = False
            lock[rv] = True
            done += 1
        T = T[alive]
        total += done
        if not done:
            break
    used = np.unique(T)
    remap = -np.ones(X.shape[0], dtype=np.int64)
    remap[used] = np.arange(used.size)
    return X[used], remap[T], total


def X0_split(X: np.ndarray, T: np.ndarray, lmax: float, tc: dict) -> tuple[np.ndarray, np.ndarray, int, int]:
    """분할 1회 ↔ 평면 안 뒤집기를 번갈아(최장 변 이등분 + Delaunay — 가는 삼각형이 닮은꼴로 남지 않음). 반환 (X, T, 분할 반복, 뒤집기 수)."""
    T, nflip = flip_planar(X, T, float(tc["coplanar_deg"]), int(tc["flip_passes"]))
    iters = 0
    for _ in range(int(tc["max_split_iters"])):
        X2, T2, k = split_long(X, T, lmax, 1, int(tc["max_tris"]))
        if k == 0:
            break
        iters += 1
        X, T = X2, T2
        T, nf = flip_planar(X, T, float(tc["coplanar_deg"]), int(tc["flip_passes"]))
        nflip += nf
    X, T, ncol = collapse_short(X, T, float(tc["collapse_factor"]) * lmax / float(tc["split_factor"]),
                                float(tc["collapse_deg"]), int(tc["collapse_passes"]), lmax)
    T, nf = flip_planar(X, T, float(tc["coplanar_deg"]), int(tc["flip_passes"]))
    nflip += nf
    for _ in range(int(tc["smooth_rounds"])):               # 접선 평활 ↔ 뒤집기(짧은 변·가는 삼각형 개선, 형상 불변)
        X, _m = smooth_planar(X, T, float(tc["coplanar_deg"]), int(tc["smooth_iters"]))
        T, nf = flip_planar(X, T, float(tc["coplanar_deg"]), int(tc["flip_passes"]))
        nflip += nf
    for _ in range(int(tc["max_split_iters"])):            # 평활이 늘린 변을 다시 ≤ lmax 로(적합 분할)
        X2, T2, k = split_long(X, T, lmax, 1, int(tc["max_tris"]))
        if k == 0:
            break
        iters += 1
        X, T = X2, T2
    T, nf = flip_planar(X, T, float(tc["coplanar_deg"]), int(tc["flip_passes"]))
    return X, T, iters, nflip + nf


# ---------------------------------------------------------------- 본체
def tria_file(src: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None, normal_ref=None,
              out_dir: str | None = None) -> tuple[dict, dict]:
    """STEP → OCC 삼각형 쉘 메시 (mesh, mesh.json). 실패 = EslError(CAD_INVALID | TRIA_FAILED | MESH_TOO_LARGE |
    REMESH_FIDELITY | GMSH_UNAVAILABLE)."""
    from esl.doe import mesh_gmsh as mg
    from esl.doe import mesh_remesh as mrm
    from esl.doe import opt_settings
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise EslError("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    mc = cfg["mesh"]
    tc = _tcfg(cfg)
    h = mg.check_h(h, mc)
    defl = float(tc["deflection_factor"]) * h
    ang = float(tc["angular_deflection_deg"])
    t0 = time.monotonic()
    warns: list[dict] = []
    rec: dict = {"deflection_mm": round(defl, 6), "angular_deflection_deg": ang, "split_max_mm": float(tc["split_factor"]) * h}
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        ver = str(getattr(gmsh, "__version__", ""))
        best = None
        if not _probe_faces(gmsh, src, mc):                 # 빈 형상에 봉합(OCCSewFaces)을 걸면 OCC 가 비정상 종료 → 먼저 확인
            raise EslError("CAD_INVALID", "STEP 에 면이 없습니다(OCC 가 읽은 면 0개)")
        for nofix in (False, True):
            try:
                faces = _import(gmsh, src, mc, nofix)
                if not faces:                               # 빈 형상에서 importStl 은 자식이 비정상 종료할 수 있음
                    raise ValueError("STEP 에 면이 없음")
                X0, T0, miss = occ_tris(gmsh, defl, ang)
            except Exception as exc:                        # noqa: BLE001
                if nofix:
                    raise EslError("CAD_INVALID", f"OCC 가 형상을 읽거나 삼각화하지 못함: {exc}") from None
                continue
            if best is None or len(miss) < len(best[3]):
                best = (faces, X0, T0, miss, nofix)
            if not miss:
                break
        faces, X0, T0, miss, nofix = best
        rec.update(n_faces=len(faces), nofix=bool(nofix), missing_faces=miss)
    finally:
        gmsh.finalize()
    if not T0.shape[0]:
        raise EslError("CAD_INVALID", "OCC 삼각화가 비었습니다(삼각형 0개) — 면 " + ", ".join(map(str, miss[:20])))
    if miss:
        if not tc["allow_missing_faces"]:
            raise EslError("CAD_INVALID", f"OCC 가 삼각화하지 못한 면 {len(miss)}개: " + ", ".join(map(str, miss[:20])))
        warns.append({"code": "MESH_TRIA_HOLES", "message": f"OCC 가 삼각화하지 못한 면 {len(miss)}개(그 자리는 빈 구멍): 면 "
                                                            + ", ".join(map(str, miss[:20]))})
    S_X, S_T, n_merged = merge_nodes_fast(X0, T0, float(tc["merge_tol_mm"]))
    rec.update(n_stl_tris=int(T0.shape[0]), n_merged=n_merged)
    X, T, iters, nflip = X0_split(S_X, S_T, float(tc["split_factor"]) * h, tc)
    rec.update(split_iters=iters, n_flips=nflip)
    conn = np.full((T.shape[0], 4), -1, dtype=np.int64)
    conn[:, :3] = T
    et = np.full(T.shape[0], 3, dtype=np.int64)
    mesh, info = mg.build_mesh(X, conn, et, props, normal_ref)
    qual = mg.quality(mesh, cfg, opt_cfg or opt_settings(None))
    errs = list(qual["errors"])
    if miss and any(e.get("code") == "MESH_DISCONNECTED" for e in errs):
        errs = [{"code": "CAD_INVALID", "message": f"OCC 가 삼각화하지 못한 면 {len(miss)}개 때문에 메시가 끊김: 면 "
                                                   + ", ".join(map(str, miss[:20]))}] + errs
    fid = None
    if not any(e.get("code") == "MESH_TOO_LARGE" for e in errs):
        rc = dict(mrm._rcfg(cfg), linear_deflection_mm=defl, angular_deflection_deg=ang)
        fid = mrm.fidelity(S_X, S_T, mesh, h, rc)
        if fid["fail_mm"] is not None and fid["hausdorff_mm"] > fid["fail_mm"]:
            errs.append({"code": "REMESH_FIDELITY",
                         "message": f"삼각형 폴백이 원 형상과 최대 {fid['hausdorff_mm']:.3f} mm 다릅니다(> {fid['fail_mm']:g} mm)"})
    hz = "—" if fid is None else f"{fid['hausdorff_mm']:.3f}"
    warns.insert(0, {"code": "MESH_TRIA_FALLBACK",
                     "message": f"CAD 면 메시·이산 재메시가 모두 실패해 OCC 삼각화(BRepMesh, 편차 {defl:g} mm)를 그대로 삼각형 쉘로 "
                                f"썼습니다(삼각형 {int(mesh['elem_id'].size)}개, 4각 0 %, 원 형상 대비 최대 {hz} mm). 삼각형 "
                                "요소는 4각보다 굽힘 강성이 조금 높게 나올 수 있습니다"})
    meta = {"schema": SCHEMA, "method": "tria", "gmsh_version": ver, "h": h, "props": dict(props),
            "n_nodes": int(mesh["node_id"].size), "n_elems": int(mesh["elem_id"].size), "quad_frac": qual["quad_frac"],
            "quality": qual["metrics"], "errors": errs, "warnings": list(qual["warnings"]) + warns, **info, "tria": rec,
            "fidelity": fid, "seconds": round(time.monotonic() - t0, 3)}
    if out_dir:
        from esl.library import _util as U
        mg.mark_success_write()
        os.makedirs(out_dir, exist_ok=True)
        mg.save_npz_det(os.path.join(out_dir, mg.MESH_NPZ), {k: mesh[k] for k in mg.MESH_KEYS})
        U.write_json(os.path.join(out_dir, mg.MESH_JSON), {k: v for k, v in meta.items() if k != "seconds"}
                     | {"seconds": meta["seconds"]})
    if errs:
        e = errs[0]
        code = e["code"] if e["code"] in ("MESH_TOO_LARGE", "REMESH_FIDELITY", "CAD_INVALID") else "TRIA_FAILED"
        raise EslError(code, f"삼각형 폴백 오류 {e['code']}: {e['message']}")
    return mesh, meta
