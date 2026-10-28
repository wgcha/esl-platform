"""④ ESL 3D 하중 보기 파생 자료(계약 docs/contracts/esl_3d_load.md, v0.5.8). 순수 numpy, 외부 프로그램·새 의존 없음.

산출(출력 폴더 하나에 모두): ``part.glb``(부품 표면, KHR_mesh_quantization int16 위치, ``_NODE_ID``),
``part_lod.glb``(N > ``lod_min_nodes`` 일 때만, ``_SRC``), ``values.bin``(노드 값 양자화), ``manifest.json``.

- 정점 = model.npz 노드 순서 그대로(정점 i = 노드 i). GLB 위치 단위 mm, 좌표는 전역 그대로(Z-up).
- 표면 색 값(L3-C1, 사용자 결정 Q1): 면압 ``p_i = |Fn_i| / A_i``  [force/length² = MPa(N·mm)],
  ``Fn_i = F_i · n_i``(면외 하중, 부호 있음, 툴팁용), ``A_i`` = 인접 요소 면적 / 요소 절점 수(사각형 4, 삼각형 3)의 합.
  ``A_i = 0``(요소에 안 쓰이는 고립 노드)이면 p = 0.
- 상위 N·군집은 서버 계산(결정적 가중 k-means, 난수 없음).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import struct
from typing import Any

import numpy as np

from .errors import EslError

BUILDER_VERSION = 1
SCHEMA = "esl/view3d/1"
GEOMETRY, GEOMETRY_LOD, VALUES, MANIFEST = "part.glb", "part_lod.glb", "values.bin", "manifest.json"
DEFAULTS = {"lod_min_nodes": 500_000, "lod_target_vertices": 100_000, "top_max": 100, "cluster_k_max": 5,
            "kmeans_max_iter": 50}
NORMAL_EPS = 1e-12

_GL_ARRAY_BUFFER, _GL_ELEMENT_ARRAY_BUFFER = 34962, 34963
_GL_SHORT, _GL_UINT = 5122, 5125


# ====================================================================== 법선·면적·면압
class NodeGeom:
    """노드 법선 n(N,3), 대표 면적 area(N,), 판 기준 법선 n_p(3,)."""

    __slots__ = ("n", "area", "n_p")

    def __init__(self, n: np.ndarray, area: np.ndarray, n_p: np.ndarray) -> None:
        self.n, self.area, self.n_p = n, area, n_p


def plate_normal(x0: np.ndarray) -> np.ndarray:
    """X0 PCA 최소 분산 축. 부호: 성분 최대 절대값이 +(같으면 앞 성분)."""
    x = np.asarray(x0, np.float64)
    if x.shape[0] < 3:
        return np.array([0.0, 0.0, 1.0])
    c = x - x.mean(axis=0)
    _, v = np.linalg.eigh(c.T @ c / x.shape[0])
    n = v[:, 0].copy()
    if n[int(np.argmax(np.abs(n)))] < 0:
        n = -n
    return n


def _quad_mask(elem_type: np.ndarray) -> np.ndarray:
    return np.asarray(elem_type) == 4


def elem_cross(x0: np.ndarray, conn: np.ndarray, elem_type: np.ndarray) -> np.ndarray:
    """요소별 면적 벡터 방향 외적 w(E,3): 사각형 (x_c−x_a)×(x_d−x_b), 삼각형 (x_b−x_a)×(x_c−x_a). 면적 = |w|/2."""
    q = _quad_mask(elem_type)
    a, b, c = x0[conn[:, 0]], x0[conn[:, 1]], x0[conn[:, 2]]
    w = np.cross(b - a, c - a)
    if q.any():
        w[q] = np.cross(c[q] - a[q], x0[conn[q, 3]] - b[q])
    return w


def node_geometry(x0: np.ndarray, conn: np.ndarray, elem_type: np.ndarray,
                  n_p: np.ndarray | None = None) -> NodeGeom:
    """노드 법선(면적 가중, 판 법선으로 방향 통일)과 대표 면적(L3-5·L3-C1)."""
    x0 = np.asarray(x0, np.float64)
    conn = np.asarray(conn, np.int64)
    n_nodes = x0.shape[0]
    if n_p is None:
        n_p = plate_normal(x0)
    q = _quad_mask(elem_type)
    w = elem_cross(x0, conn, elem_type)
    w[w @ n_p < 0] *= -1.0                      # n_e·n_p < 0 이면 뒤집음(면적 가중 합이므로 w 부호 반전)
    vec = 0.5 * w                               # A_e · n_e
    area_e = 0.5 * np.linalg.norm(w, axis=1)
    share = area_e / np.where(q, 4.0, 3.0)      # 절점당 면적
    acc = np.zeros((n_nodes, 3))
    area = np.zeros(n_nodes)
    for j in range(4):
        m = np.ones(conn.shape[0], bool) if j < 3 else q
        idx = conn[m, j]
        for k in range(3):
            acc[:, k] += np.bincount(idx, weights=vec[m, k], minlength=n_nodes)
        area += np.bincount(idx, weights=share[m], minlength=n_nodes)
    nrm = np.linalg.norm(acc, axis=1)
    ok = nrm >= NORMAL_EPS
    n = np.tile(n_p, (n_nodes, 1))
    n[ok] = acc[ok] / nrm[ok][:, None]
    return NodeGeom(n, area, n_p)


def face_values(f: np.ndarray, geom: NodeGeom) -> tuple[np.ndarray, np.ndarray]:
    """(Fn(N) 부호 있음, p = |Fn|/A (MPa)). A = 0 → p = 0."""
    fn = np.einsum("ij,ij->i", np.asarray(f, np.float64), geom.n)
    p = np.zeros_like(fn)
    ok = geom.area > 0
    p[ok] = np.abs(fn[ok]) / geom.area[ok]
    return fn, p


# ====================================================================== 상위 N
def top_rows(node_id, x0, f, fn, p, support_ids, top: int) -> list[dict[str, Any]]:
    """전 노드 정렬 = ``/forces`` 와 같은 lexsort((node_id, −|F|)). 행 {rank,node_id,vertex,x,y,z,fx,fy,fz,mag,fn,p,is_support}."""
    mag = np.linalg.norm(f, axis=1)
    order = np.lexsort((node_id, -mag))[:max(0, int(top))]
    sup = {int(s) for s in support_ids}
    return [{"rank": r + 1, "node_id": int(node_id[i]), "vertex": int(i), "x": float(x0[i, 0]), "y": float(x0[i, 1]),
             "z": float(x0[i, 2]), "fx": float(f[i, 0]), "fy": float(f[i, 1]), "fz": float(f[i, 2]),
             "mag": float(mag[i]), "fn": float(fn[i]), "pa": float(p[i]), "is_support": int(node_id[i]) in sup}
            for r, i in enumerate(order.tolist())]


# ====================================================================== 군집(L3-7)
def _d2(xt: np.ndarray, c: np.ndarray) -> np.ndarray:
    """점 xt(3,n) 에서 c(3,) 까지 거리²(차이를 직접 제곱: 상쇄 오차 없음)."""
    d = xt[0] - c[0]
    out = d * d
    d = xt[1] - c[1]
    out += d * d
    d = xt[2] - c[2]
    out += d * d
    return out


def _centers(xt: np.ndarray, w: np.ndarray, labels: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """(중심 = Σw x/Σw, 군집별 노드 수)."""
    cnt = np.bincount(labels, minlength=k)
    sw = np.bincount(labels, weights=w, minlength=k)
    c = np.zeros((k, 3))
    for d in range(3):
        c[:, d] = np.bincount(labels, weights=w * xt[d], minlength=k)
    nz = sw > 0
    c[nz] /= sw[nz][:, None]
    return c, cnt


def _assign(xt: np.ndarray, centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """가장 가까운 중심(같으면 작은 군집 번호)과 그 거리²."""
    best = _d2(xt, centers[0])
    lab = np.zeros(xt.shape[1], np.intp)
    for k in range(1, centers.shape[0]):
        d = _d2(xt, centers[k])
        m = d < best                                # 엄격한 < : 같으면 작은 번호 유지
        lab[m] = k
        np.minimum(best, d, out=best)
    return lab, best


def kmeans_weighted(x: np.ndarray, w: np.ndarray, k: int, max_iter: int = 50,
                    init: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, int]:
    """결정적 가중 k-means → (labels, centers(k_actual,3), k_actual).

    입력은 **node_id 오름차순**이어야 한다(argmax 동률 = 작은 node_id). 초기화(난수 없음, 가중 최원점):
    c1 = argmax w, c_j = argmax w·min_l‖x−c_l‖². Lloyd: 배정(동률 작은 번호) → 중심 = Σw x/Σw, 배정이 안 바뀌거나 ``max_iter`` 회면 종료.
    빈 군집은 argmax w·d²(자기 군집 중심까지) 노드로 다시 심음(최대 3회), 그래도 비면 군집을 줄임(k_actual).
    ``init`` 은 시험용 초기 중심(k,3).
    """
    n = x.shape[0]
    if n == 0:
        return np.zeros(0, np.int64), np.zeros((0, 3)), 0
    xt = np.ascontiguousarray(x.T)
    k = max(1, min(int(k), n))
    if init is not None:
        centers = np.asarray(init, np.float64).copy()
        k = centers.shape[0]
    else:
        first = int(np.argmax(w))
        centers = [x[first]]
        mind = _d2(xt, x[first])
        while len(centers) < k:
            score = w * mind
            i = int(np.argmax(score))
            if score[i] <= 0.0:
                break                               # 서로 다른 점이 모자람 → k_actual 감소
            centers.append(x[i])
            mind = np.minimum(mind, _d2(xt, x[i]))
        centers = np.array(centers)
        k = centers.shape[0]
    labels, dist = _assign(xt, centers)
    for _ in range(3):                              # 빈 군집 재심기(번호 작은 것부터 1개씩, 최대 3회)
        cnt = np.bincount(labels, minlength=k)
        empty = np.flatnonzero(cnt == 0)
        if empty.size == 0:
            break
        score = np.where(cnt[labels] > 1, w * dist, -1.0)
        i = int(np.argmax(score))
        if score[i] <= 0.0:
            break
        centers[int(empty[0])] = x[i]
        labels, dist = _assign(xt, centers)
    cnt = np.bincount(labels, minlength=k)
    if (cnt == 0).any():                            # 재심기로도 못 채운 군집 제거
        keep = np.flatnonzero(cnt > 0)
        centers = centers[keep]
        k = centers.shape[0]
        labels, dist = _assign(xt, centers)
    for _ in range(int(max_iter)):
        centers, cnt = _centers(xt, w, labels, k)
        new, dist = _assign(xt, centers)
        if np.array_equal(new, labels):
            break
        labels = new
    centers, cnt = _centers(xt, w, labels, k)        # 최종 배정 기준 하중 중심
    if (cnt == 0).any():                            # 반복 중 비게 된 군집 제거(드묾)
        keep = np.flatnonzero(cnt > 0)
        remap = -np.ones(k, np.int64)
        remap[keep] = np.arange(keep.size)
        labels = remap[labels]
        k = keep.size
        centers, cnt = _centers(xt, w, labels, k)
    return labels, centers, k


def clusters(node_id: np.ndarray, x0: np.ndarray, f: np.ndarray, u_rel: np.ndarray, k_max: int = 5,
             max_iter: int = 50) -> dict[str, Any]:
    """K = 2..k_max 군집 합력 표(계약 §3.6). {str(K): {"k_actual", "rows":[…]}}.

    대상 = |F| > 0 노드 전부(지지점 포함), 좌표 X0, 가중 |F|. 입력 순서와 무관하게 node_id 오름차순으로 정규화해 계산하므로
    노드 순서를 섞어도 결과(node_id 기준)가 같다.
    """
    mag = np.linalg.norm(f, axis=1)
    sel = np.flatnonzero(mag > 0)
    sel = sel[np.argsort(node_id[sel], kind="stable")]
    nid, x, F, u, w = node_id[sel], x0[sel], f[sel], u_rel[sel], mag[sel]
    out: dict[str, Any] = {}
    for k in range(2, int(k_max) + 1):
        labels, centers, ka = kmeans_weighted(x, w, k, max_iter)
        rows = []
        for j in range(ka):
            m = labels == j
            Fj, xj, wj = F[m], x[m], w[m]
            r = Fj.sum(axis=0)
            sw = float(wj.sum())
            c = centers[j]
            mom = np.cross(xj - c, Fj).sum(axis=0)
            rmag = float(np.linalg.norm(r))
            rows.append({"n_nodes": int(m.sum()), "center": c.tolist(),
                         "u_center": ((wj[:, None] * u[m]).sum(axis=0) / sw).tolist() if sw > 0 else [0.0] * 3,
                         "r": r.tolist(), "r_mag": rmag, "sum_abs": sw, "cancel": (1.0 - rmag / sw) if sw > 0 else 0.0,
                         "m": mom.tolist(), "m_mag": float(np.linalg.norm(mom)), "min_node_id": int(nid[m].min())})
        rows.sort(key=lambda d: (-d["r_mag"], d["min_node_id"]))
        out[str(k)] = {"k_actual": int(ka), "rows": [{"label": f"C{i + 1}", **d} for i, d in enumerate(rows)]}
    return out


# ====================================================================== 삼각형·LOD
def triangulate(conn: np.ndarray, elem_type: np.ndarray) -> np.ndarray:
    """사각형 (a,b,c,d) → (a,b,c),(a,c,d), 삼각형 (a,b,c). 요소 순서 유지. uint32 (T,3)."""
    conn = np.asarray(conn, np.int64)
    q = _quad_mask(elem_type)
    cnt = 1 + q.astype(np.int64)
    start = np.cumsum(cnt) - cnt
    tris = np.empty((int(cnt.sum()), 3), np.uint32)
    tris[start] = conn[:, :3]
    tris[start[q] + 1] = conn[q][:, [0, 2, 3]]
    return tris


def _cells(x0: np.ndarray, lo: np.ndarray, h: float) -> np.ndarray:
    ijk = np.floor((x0 - lo) / h).astype(np.int64)
    m = ijk.max(axis=0) + 1
    return (ijk[:, 0] * m[1] + ijk[:, 1]) * m[2] + ijk[:, 2]


def lod_grid(x0: np.ndarray, tris: np.ndarray, p: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    """대표 원 노드 격자 군집 LOD(계약 §3.4): (src(M,) 원 정점 번호, tris(T',3) 새 번호 uint32).

    정육면체 셀 크기를 이분 탐색해 점유 셀 수 ≈ target, 셀 대표 = 셀 안 면압 p 최대 원 노드(같으면 작은 번호), 삼각형을 대표로
    치환해 퇴화·중복 삼각형 제거, 쓰인 대표만 새 번호.
    """
    n = x0.shape[0]
    lo, hi = x0.min(axis=0), x0.max(axis=0)
    ext = float((hi - lo).max())
    if n == 0 or ext <= 0:
        return np.zeros(0, np.int64), np.zeros((0, 3), np.uint32)

    def count(h: float) -> int:
        return int(np.unique(_cells(x0, lo, h)).size)

    a, b = ext / 4096.0, ext * 1.0001            # a: 셀 많음, b: 셀 1개
    best_h, best_c = b, 1
    for _ in range(18):
        h = float(np.sqrt(a * b))
        c = count(h)
        if c <= 1.1 * target:
            if c > best_c:
                best_h, best_c = h, c
            b = h
        else:
            a = h
        if 0.9 * target <= c <= 1.1 * target:
            break
    cell = _cells(x0, lo, best_h)
    order = np.lexsort((np.arange(n), -p, cell))
    sc = cell[order]
    first = np.concatenate(([True], sc[1:] != sc[:-1]))
    rep_nodes = order[first]                      # 셀별 대표 원 노드(셀 키 오름차순)
    inv = np.cumsum(first) - 1
    rep_of = np.empty(n, np.int64)
    rep_of[order] = rep_nodes[inv]                # 정점 → 대표 정점
    t = rep_of[np.asarray(tris, np.int64)]
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    t = t[keep]
    if t.shape[0]:
        key = np.sort(t, axis=1)
        _, ui = np.unique(key, axis=0, return_index=True)
        t = t[np.sort(ui)]
    used = np.unique(t)
    new_id = -np.ones(n, np.int64)
    new_id[used] = np.arange(used.size)
    return used, new_id[t].astype(np.uint32)


# ====================================================================== GLB
def quantize_positions(x: np.ndarray, center: np.ndarray, half: np.ndarray) -> np.ndarray:
    """SHORT normalized: q = round((x−center)/half·32767), half = 0 인 축은 scale 1(q = 0)."""
    scale = np.where(half > 0, half, 1.0)
    return np.clip(np.rint((x - center) / scale * 32767.0), -32767, 32767).astype(np.int16)


def write_glb(path: str, q: np.ndarray, center: np.ndarray, half: np.ndarray, attr: str, attr_values: np.ndarray,
              tris: np.ndarray, extras: dict[str, Any]) -> int:
    """glTF 2.0 바이너리 한 개(메시 1, 재질 없음). 반환 = 파일 바이트 수.

    버퍼: POSITION int16×3(+2B 패딩, stride 8) · 사용자 속성(``_NODE_ID``/``_SRC``, uint32) · 인덱스 uint32.
    노드 translation = bbox 중심, scale = 반축(0 이면 1).
    """
    n = q.shape[0]
    pos = np.zeros((n, 4), np.int16)
    pos[:, :3] = q
    pos_b = pos.tobytes()
    att_b = np.ascontiguousarray(attr_values, np.uint32).tobytes()
    idx_b = np.ascontiguousarray(tris, np.uint32).tobytes()
    qmin = q.min(axis=0).astype(int).tolist() if n else [0, 0, 0]
    qmax = q.max(axis=0).astype(int).tolist() if n else [0, 0, 0]
    ext = ["KHR_mesh_quantization"]
    gltf = {
        "asset": {"version": "2.0", "generator": extras["generator"], "extras": extras},
        "extensionsUsed": ext, "extensionsRequired": ext,
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": [float(v) for v in center],
                   "scale": [float(v) if v > 0 else 1.0 for v in half]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, attr: 1}, "indices": 2, "mode": 4}]}],
        "buffers": [{"byteLength": len(pos_b) + len(att_b) + len(idx_b)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b), "byteStride": 8, "target": _GL_ARRAY_BUFFER},
            {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(att_b), "target": _GL_ARRAY_BUFFER},
            {"buffer": 0, "byteOffset": len(pos_b) + len(att_b), "byteLength": len(idx_b),
             "target": _GL_ELEMENT_ARRAY_BUFFER}],
        "accessors": [
            {"bufferView": 0, "componentType": _GL_SHORT, "normalized": True, "count": n, "type": "VEC3",
             "min": qmin, "max": qmax},
            {"bufferView": 1, "componentType": _GL_UINT, "count": n, "type": "SCALAR"},
            {"bufferView": 2, "componentType": _GL_UINT, "count": int(tris.size), "type": "SCALAR"}],
    }
    js = json.dumps(gltf, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    js += b" " * (-len(js) % 4)
    binb = pos_b + att_b + idx_b
    binb += b"\x00" * (-len(binb) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total))
        fh.write(struct.pack("<I4s", len(js), b"JSON"))
        fh.write(js)
        fh.write(struct.pack("<I4s", len(binb), b"BIN\x00"))
        fh.write(binb)
    return total


def read_glb(path: str) -> tuple[dict[str, Any], bytes]:
    """(JSON, BIN 청크) — 시험·검증용 최소 파서."""
    with open(path, "rb") as fh:
        data = fh.read()
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or ver != 2 or total != len(data):
        raise EslError("OUTPUT_INVALID", f"GLB 머리 오류: {path}")
    off, js, binb = 12, None, b""
    while off < len(data):
        ln, typ = struct.unpack_from("<I4s", data, off)
        body = data[off + 8:off + 8 + ln]
        if typ == b"JSON":
            js = json.loads(body.decode("ascii"))
        elif typ == b"BIN\x00":
            binb = body
        off += 8 + ln
    return js, binb


# ====================================================================== values.bin
def pack_values(p: np.ndarray, fn: np.ndarray, fmag: np.ndarray, u: np.ndarray) -> tuple[bytes, list[dict[str, Any]]]:
    """머리 없는 little-endian, 배열마다 4바이트 정렬(패딩 0). 반환 (bytes, manifest arrays).

    p uint16(s = max/65535, 면압 MPa) · fn int16(s = max|fn|/32767, N, 부호) · fmag uint16(s = max/65535, N) ·
    u int16×3(성분별 s_c = max|u_c|/32767, mm, 정점별 x,y,z 교차). 전부 0 이면 s = 0, q = 0.
    """
    def quant(v: np.ndarray, qmax: int, signed: bool, scale: np.ndarray) -> np.ndarray:
        s = np.where(scale > 0, scale, 1.0)
        q = np.clip(np.rint(v / s), -qmax if signed else 0, qmax)
        return q.astype(np.int16 if signed else np.uint16)

    specs = [("pa", "uint16", 1, np.asarray(p, np.float64)[:, None], 65535, False),
             ("fn", "int16", 1, np.asarray(fn, np.float64)[:, None], 32767, True),
             ("fmag", "uint16", 1, np.asarray(fmag, np.float64)[:, None], 65535, False),
             ("u", "int16", 3, np.asarray(u, np.float64).reshape(-1, 3), 32767, True)]
    buf = bytearray()
    arrays = []
    for key, dtype, comps, v, qmax, signed in specs:
        scale = (np.abs(v).max(axis=0) if v.shape[0] else np.zeros(comps)) / qmax
        q = quant(v, qmax, signed, scale)
        buf += b"\x00" * (-len(buf) % 4)
        arrays.append({"key": key, "dtype": dtype, "comps": comps, "offset": len(buf),
                       "scale": float(scale[0]) if comps == 1 else [float(s) for s in scale]})
        buf += q.astype("<" + ("i2" if signed else "u2")).tobytes()
    buf += b"\x00" * (-len(buf) % 4)
    return bytes(buf), arrays


def unpack_values(buf: bytes, arrays: list[dict[str, Any]], n: int) -> dict[str, np.ndarray]:
    """values.bin 복원(프런트 values.ts 와 같은 계산): q·s. comps 3 이면 (n,3)."""
    out = {}
    for a in arrays:
        dt_ = np.dtype("<i2" if a["dtype"] == "int16" else "<u2")
        c = int(a["comps"])
        q = np.frombuffer(buf, dt_, count=n * c, offset=int(a["offset"])).astype(np.float64).reshape(n, c)
        s = np.asarray(a["scale"], np.float64).reshape(1, -1)
        v = q * s
        out[a["key"]] = v[:, 0] if c == 1 else v
    return out


# ====================================================================== 범위
def _p99(v: np.ndarray) -> float | None:
    """⑤ DP-10 과 같은 견고한 범위(P99, 유효숫자 2자리 올림). 값이 없으면 None."""
    from .report.field import robust_range

    r = robust_range(v, "zero")
    return None if r.get("max") is None else float(r["max"])


# ====================================================================== 전체 생성
def build_view(out_dir: str, *, node_id, x0, conn, elem_type, f, u_rel, supports=(), cfg: dict[str, Any] | None = None,
               key: str = "", esl_run_id: str = "", units: dict[str, str] | None = None,
               created_at: str | None = None) -> dict[str, Any]:
    """out_dir 에 part.glb·(part_lod.glb)·values.bin·manifest.json 을 쓰고 manifest dict 를 돌려준다.

    supports = [{"node_id", "dof", …}] (03_bc/support.json 또는 run.supports). x0 는 model.npz 에서 취한다.
    """
    c = {**DEFAULTS, **(cfg or {})}
    nid = np.asarray(node_id, np.int64)
    x0 = np.asarray(x0, np.float64)
    f = np.asarray(f, np.float64)
    u_rel = np.asarray(u_rel, np.float64)
    conn = np.asarray(conn, np.int64)
    n = nid.size
    if x0.shape != (n, 3) or f.shape != (n, 3) or u_rel.shape != (n, 3):
        raise EslError("OUTPUT_INCONSISTENT", "node_id·x0·f·u_rel 크기가 서로 다릅니다")
    if not (np.isfinite(f).all() and np.isfinite(u_rel).all() and np.isfinite(x0).all()):
        raise EslError("OUTPUT_INVALID", "x0·f_eq·u_rel 에 NaN/inf 가 있습니다")
    units = {"length": "mm", "force": "N", "pressure": "MPa", **(units or {})}
    os.makedirs(out_dir, exist_ok=True)

    geom = node_geometry(x0, conn, elem_type)
    fn, p = face_values(f, geom)
    mag = np.linalg.norm(f, axis=1)
    umag = np.linalg.norm(u_rel, axis=1)
    tris = triangulate(conn, elem_type)

    lo, hi = x0.min(axis=0), x0.max(axis=0)
    center, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    q = quantize_positions(x0, center, half)
    extras = {"units": units["length"], "up": "Z", "generator": f"esl view3d {BUILDER_VERSION}"}
    gbytes = write_glb(os.path.join(out_dir, GEOMETRY), q, center, half, "_NODE_ID", nid.astype(np.uint32), tris, extras)
    lod = None
    if n > int(c["lod_min_nodes"]):
        src, ltris = lod_grid(x0, tris, p, int(c["lod_target_vertices"]))
        lbytes = write_glb(os.path.join(out_dir, GEOMETRY_LOD), q[src], center, half, "_SRC", src.astype(np.uint32),
                           ltris, extras)
        lod = {"name": GEOMETRY_LOD, "bytes": lbytes, "n_vertices": int(src.size)}

    vbytes, arrays = pack_values(p, fn, mag, u_rel)
    with open(os.path.join(out_dir, VALUES), "wb") as fh:
        fh.write(vbytes)

    # 지지점 → 정점
    order = np.argsort(nid, kind="stable")
    sup_rows, sup_ids = [], []
    for s in supports or ():
        pos = int(np.searchsorted(nid[order], int(s["node_id"])))
        if pos >= n or nid[order][pos] != int(s["node_id"]):
            continue
        v = int(order[pos])
        sup_ids.append(int(nid[v]))
        sup_rows.append({"node_id": int(nid[v]), "vertex": v, "dof": str(s["dof"]), "x0": x0[v].tolist()})

    loaded = mag > 0
    mc = x0.mean(axis=0)                           # 코어 esl_summary moment_center 와 같은 정의(X0 평균)
    sum_f = f.sum(axis=0)
    sum_m = np.cross(x0 - mc, f).sum(axis=0)
    ranges = {"pa": {"max": float(p.max()) if n else 0.0, "p99": _p99(p[loaded]) if loaded.any() else None},
              "fn_abs": {"max": float(np.abs(fn).max()) if n else 0.0,
                         "p99": _p99(np.abs(fn)[loaded]) if loaded.any() else None},
              "fmag_max": float(mag.max()) if n else 0.0, "u_max": float(umag.max()) if n else 0.0}
    manifest = {
        "schema": SCHEMA, "builder_version": BUILDER_VERSION, "key": key, "esl_run_id": esl_run_id,
        "n_nodes": int(n), "n_elems": int(conn.shape[0]), "n_tris": int(tris.shape[0]),
        "units": units["length"], "force_unit": units["force"], "pressure_unit": units["pressure"], "up": "Z",
        "bbox": {"min": lo.tolist(), "max": hi.tolist(), "diag": float(np.linalg.norm(hi - lo))},
        "plate_normal": geom.n_p.tolist(),
        "geometry": {"name": GEOMETRY, "bytes": gbytes}, "lod": lod,
        "values": {"name": VALUES, "bytes": len(vbytes), "arrays": arrays},
        "ranges": ranges, "sum_f": sum_f.tolist(), "sum_m": sum_m.tolist(), "moment_center": mc.tolist(),
        "supports": sup_rows,
        "top": top_rows(nid, x0, f, fn, p, sup_ids, int(c["top_max"])),
        "clusters": clusters(nid, x0, f, u_rel, int(c["cluster_k_max"]), int(c["kmeans_max_iter"])),
        "created_at": created_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, allow_nan=False)
    return manifest
