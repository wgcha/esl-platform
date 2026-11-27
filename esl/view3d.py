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


# ====================================================================== v0.24.1 재현(목표·응답·오차) — esl_view3d_sources.md §3
RECON_SCHEMA = "esl/view3d_recon/1"
RECON_VERSION = 1
RECON_JSON, RECON_BIN = "recon.json", "recon.bin"
RECON_KEYS = ("tgt", "fit", "err")


def _umax(u: np.ndarray) -> float:
    return float(np.linalg.norm(u, axis=1).max()) if u.shape[0] else 0.0


def recon_fields(u_tgt, u_fit) -> dict[str, Any]:
    """재현 수치(순수): err = u_fit − u_tgt, 색 범위 tgt_max·fit_max·err_max(노드 변위 크기 최대), mac·umax_* =
    ``esl.mech.bforce.mac``·``recon_report`` 정의 그대로(식 복제 없음 — 목표 = 기준, 응답 = 재현)."""
    from esl.mech import bforce as bfm

    t = np.asarray(u_tgt, np.float64).reshape(-1, 3)
    f = np.asarray(u_fit, np.float64).reshape(-1, 3)
    if t.shape != f.shape:
        raise EslError("OUTPUT_INCONSISTENT", "목표·응답 변위 크기가 서로 다릅니다")
    err = f - t
    rep = bfm.recon_report(t, f, None, np.zeros((0, 3)))
    return {"err": err, "tgt_max": _umax(t), "fit_max": _umax(f), "err_max": _umax(err), "mac": rep["mac"],
            "umax_tgt": rep["umax_ref"], "umax_fit": rep["umax_val"], "umax_err": rep["umax_err"]}


def pack_disp(named) -> tuple[bytes, list[dict[str, Any]]]:
    """변위 배열 여러 개 → (bytes, arrays). 배열마다 int16×3(성분별 s_c = max|u_c|/32767 — ``pack_values`` 의 u 규칙과 같음,
    전부 0 이면 s = 0·q = 0), 정점별 x,y,z 교차, 4바이트 정렬(패딩 0). named = [(key, (N,3)), …] 순서 그대로."""
    buf = bytearray()
    arrays = []
    for key, u in named:
        v = np.asarray(u, np.float64).reshape(-1, 3)
        scale = (np.abs(v).max(axis=0) if v.shape[0] else np.zeros(3)) / 32767
        s = np.where(scale > 0, scale, 1.0)
        q = np.clip(np.rint(v / s), -32767, 32767).astype("<i2")
        buf += b"\x00" * (-len(buf) % 4)
        arrays.append({"key": str(key), "dtype": "int16", "comps": 3, "offset": len(buf),
                       "scale": [float(x) for x in scale]})
        buf += q.tobytes()
    buf += b"\x00" * (-len(buf) % 4)
    return bytes(buf), arrays


def build_recon(out_dir: str, *, node_id, u_tgt, u_fit, key: str, src: str, rigid: str,
                esl_run_id: str = "") -> dict[str, Any]:
    """out_dir 에 recon.bin(tgt·fit·err int16×3) 을 먼저, recon.json 을 마지막에 쓰고 recon dict 를 돌려준다(build_view 와 같은
    "출력 폴더에 쓰는 빌더" 계열 — json 이 없으면 미완성). 정점 순서 = 입력 순서(호출부가 model/메시 노드 순서로 맞춰 넘김)."""
    nid = np.asarray(node_id, np.int64).reshape(-1)
    t = np.asarray(u_tgt, np.float64)
    f = np.asarray(u_fit, np.float64)
    n = nid.size
    if t.shape != (n, 3) or f.shape != (n, 3):
        raise EslError("OUTPUT_INCONSISTENT", "node_id·목표·응답 변위 크기가 서로 다릅니다")
    if not (np.isfinite(t).all() and np.isfinite(f).all()):
        raise EslError("OUTPUT_INVALID", "목표·응답 변위에 NaN/inf 가 있습니다")
    r = recon_fields(t, f)
    b, arrays = pack_disp([("tgt", t), ("fit", f), ("err", r["err"])])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, RECON_BIN), "wb") as fh:
        fh.write(b)
    doc = {"schema": RECON_SCHEMA, "recon_version": RECON_VERSION, "key": str(key), "src": str(src),
           "esl_run_id": str(esl_run_id), "n_nodes": int(n), "rigid": str(rigid), "bytes": len(b), "arrays": arrays,
           "ranges": {"tgt_max": r["tgt_max"], "fit_max": r["fit_max"], "err_max": r["err_max"]},
           "mac": r["mac"], "umax_tgt": r["umax_tgt"], "umax_fit": r["umax_fit"], "umax_err": r["umax_err"]}
    with open(os.path.join(out_dir, RECON_JSON), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, allow_nan=False)
    return doc


def unpack_disp(buf: bytes, arrays: list[dict[str, Any]], n: int) -> dict[str, np.ndarray]:
    """recon.bin 복원(시험·검증용 — 프런트 decodeDisp 와 같은 계산): q·s, (n,3)."""
    return {a["key"]: np.frombuffer(buf, np.dtype("<i2"), count=n * 3, offset=int(a["offset"])).astype(np.float64)
            .reshape(n, 3) * np.asarray(a["scale"], np.float64).reshape(1, 3) for a in arrays}


# ====================================================================== 범위
def _p99(v: np.ndarray) -> float | None:
    """⑤ DP-10 과 같은 견고한 범위(P99, 유효숫자 2자리 올림). 값이 없으면 None."""
    from .report.field import robust_range

    r = robust_range(v, "zero")
    return None if r.get("max") is None else float(r["max"])


# ====================================================================== 전체 생성
SUPPORT_EXTRA_KEYS = ("kind", "dirs", "val", "via")   # v0.25.2 via = "force"(강제로 붙인 지지 — esl_tstar_manual_jig_force.md §4.3)   # 지지 표식 일반형 필드(esl.mech.jig_bc.support_marks_full — 계약 esl_bead_pos_u.md §10.2)


def _check_inputs(node_id, x0, conn, f, u_rel) -> tuple:
    """build_view·build_scene_pack 공용 입력 검사 → (nid, x0, conn) 배열."""
    nid = np.asarray(node_id, np.int64)
    x0 = np.asarray(x0, np.float64)
    conn = np.asarray(conn, np.int64)
    n = nid.size
    if x0.shape != (n, 3) or f.shape != (n, 3) or u_rel.shape != (n, 3):
        raise EslError("OUTPUT_INCONSISTENT", "node_id·x0·f·u_rel 크기가 서로 다릅니다")
    if not (np.isfinite(f).all() and np.isfinite(u_rel).all() and np.isfinite(x0).all()):
        raise EslError("OUTPUT_INVALID", "x0·f_eq·u_rel 에 NaN/inf 가 있습니다")
    return nid, x0, conn


def _part(x0, conn, elem_type) -> dict:
    """형상 공용(씬과 무관): 노드 기하·삼각형·bbox·양자화 위치."""
    geom = node_geometry(x0, conn, elem_type)
    tris = triangulate(conn, elem_type)
    lo, hi = x0.min(axis=0), x0.max(axis=0)
    center, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    return {"geom": geom, "tris": tris, "lo": lo, "hi": hi, "center": center, "half": half,
            "q": quantize_positions(x0, center, half)}


def _extras(units: dict) -> dict:
    return {"units": units["length"], "up": "Z", "generator": f"esl view3d {BUILDER_VERSION}"}


def _write_lod(out_dir: str, P: dict, x0, p, c: dict, units: dict) -> dict:
    src, ltris = lod_grid(x0, P["tris"], p, int(c["lod_target_vertices"]))
    lbytes = write_glb(os.path.join(out_dir, GEOMETRY_LOD), P["q"][src], P["center"], P["half"], "_SRC",
                       src.astype(np.uint32), ltris, _extras(units))
    return {"name": GEOMETRY_LOD, "bytes": lbytes, "n_vertices": int(src.size)}


def _support_rows(nid, x0, supports) -> tuple[list, list]:
    """지지점 → 정점 행(manifest supports)·지지 노드 ID."""
    n = nid.size
    order = np.argsort(nid, kind="stable")
    sup_rows, sup_ids = [], []
    for s in supports or ():
        pos = int(np.searchsorted(nid[order], int(s["node_id"])))
        if pos >= n or nid[order][pos] != int(s["node_id"]):
            continue
        v = int(order[pos])
        sup_ids.append(int(nid[v]))
        row = {"node_id": int(nid[v]), "vertex": v, "dof": str(s["dof"]), "x0": x0[v].tolist()}
        for k in SUPPORT_EXTRA_KEYS:                  # v0.24.9 BM §10.2: kind·dirs·val(있을 때만 — 옛 행·옛 파일 바이트 불변)
            if k in s:
                row[k] = s[k]
        sup_rows.append(row)
    return sup_rows, sup_ids


def _load_fields(x0, f, p, fn, mag, umag, n: int) -> tuple[dict, list, list, list]:
    """(ranges, sum_f, sum_m, moment_center) — manifest 값 범위·합력."""
    loaded = mag > 0
    mc = x0.mean(axis=0)                           # 코어 esl_summary moment_center 와 같은 정의(X0 평균)
    sum_f = f.sum(axis=0)
    sum_m = np.cross(x0 - mc, f).sum(axis=0)
    ranges = {"pa": {"max": float(p.max()) if n else 0.0, "p99": _p99(p[loaded]) if loaded.any() else None},
              "fn_abs": {"max": float(np.abs(fn).max()) if n else 0.0,
                         "p99": _p99(np.abs(fn)[loaded]) if loaded.any() else None},
              "fmag_max": float(mag.max()) if n else 0.0, "u_max": float(umag.max()) if n else 0.0}
    return ranges, sum_f.tolist(), sum_m.tolist(), mc.tolist()


def _now(created_at: str | None) -> str:
    return created_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_view(out_dir: str, *, node_id, x0, conn, elem_type, f, u_rel, supports=(), cfg: dict[str, Any] | None = None,
               key: str = "", esl_run_id: str = "", units: dict[str, str] | None = None,
               created_at: str | None = None, tie_marks: list | None = None) -> dict[str, Any]:
    """out_dir 에 part.glb·(part_lod.glb)·values.bin·manifest.json 을 쓰고 manifest dict 를 돌려준다.

    supports = [{"node_id", "dof", …}] (03_bc/support.json 또는 run.supports). x0 는 model.npz 에서 취한다.
    v0.25.1: 본문을 씬 묶음(``build_scene_pack``)과 같은 내부 함수로 나눔 — 출력 바이트 불변(tests/test_view3d_golden.py).
    """
    c = {**DEFAULTS, **(cfg or {})}
    f = np.asarray(f, np.float64)
    u_rel = np.asarray(u_rel, np.float64)
    nid, x0, conn = _check_inputs(node_id, x0, conn, f, u_rel)
    n = nid.size
    units = {"length": "mm", "force": "N", "pressure": "MPa", **(units or {})}
    os.makedirs(out_dir, exist_ok=True)

    P = _part(x0, conn, elem_type)
    geom, tris = P["geom"], P["tris"]
    fn, p = face_values(f, geom)
    mag = np.linalg.norm(f, axis=1)
    umag = np.linalg.norm(u_rel, axis=1)
    lo, hi = P["lo"], P["hi"]
    gbytes = write_glb(os.path.join(out_dir, GEOMETRY), P["q"], P["center"], P["half"], "_NODE_ID", nid.astype(np.uint32),
                       tris, _extras(units))
    lod = None
    if n > int(c["lod_min_nodes"]):
        lod = _write_lod(out_dir, P, x0, p, c, units)

    vbytes, arrays = pack_values(p, fn, mag, u_rel)
    with open(os.path.join(out_dir, VALUES), "wb") as fh:
        fh.write(vbytes)

    sup_rows, sup_ids = _support_rows(nid, x0, supports)
    ranges, sum_f, sum_m, mc = _load_fields(x0, f, p, fn, mag, umag, n)
    manifest = {
        "schema": SCHEMA, "builder_version": BUILDER_VERSION, "key": key, "esl_run_id": esl_run_id,
        "n_nodes": int(n), "n_elems": int(conn.shape[0]), "n_tris": int(tris.shape[0]),
        "units": units["length"], "force_unit": units["force"], "pressure_unit": units["pressure"], "up": "Z",
        "bbox": {"min": lo.tolist(), "max": hi.tolist(), "diag": float(np.linalg.norm(hi - lo))},
        "plate_normal": geom.n_p.tolist(),
        "geometry": {"name": GEOMETRY, "bytes": gbytes}, "lod": lod,
        "values": {"name": VALUES, "bytes": len(vbytes), "arrays": arrays},
        "ranges": ranges, "sum_f": sum_f, "sum_m": sum_m, "moment_center": mc,
        "supports": sup_rows,
        "top": top_rows(nid, x0, f, fn, p, sup_ids, int(c["top_max"])),
        "clusters": clusters(nid, x0, f, u_rel, int(c["cluster_k_max"]), int(c["kmeans_max_iter"])),
        "created_at": _now(created_at),
    }
    if tie_marks is not None:                          # v0.25.2 §4.3: 강제·못 붙인 체결부 자리(격자 지그 강제 부여 스냅샷만 — 옛 manifest 불변)
        manifest["tie_marks"] = tie_marks
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, allow_nan=False)
    return manifest


# ====================================================================== v0.25.1 씬 묶음 — esl_view3d_scene_legend.md §2.2·§2.3
SCENE_SCHEMA = "esl/view3d_scene/1"
SCENE_BUILDER_VERSION = 1
PACK_JSON = "pack.json"
C_UNIT = "N·mm"


def scene_files(kk: int) -> tuple[str, str]:
    """씬 순번 kk(스냅샷 엔트리 순서) → (manifest, values) 파일 이름 e<kk>.json·e<kk>.bin."""
    return f"e{int(kk):02d}.json", f"e{int(kk):02d}.bin"


def _q16(v: np.ndarray) -> tuple[bytes, float]:
    """int16 부호 양자화(``pack_values`` 의 fn 규칙): s = max|v|/32767(전부 0 이면 0·q 0). 복원 오차 ≤ s/2."""
    a = np.asarray(v, np.float64).reshape(-1)
    s = float(np.abs(a).max()) / 32767 if a.size else 0.0
    q = np.clip(np.rint(a / (s if s > 0 else 1.0)), -32767, 32767).astype("<i2")
    return q.tobytes(), s


def pack_scene_values(p, fn, fmag, u, c, dc=None) -> tuple[bytes, list[dict[str, Any]]]:
    """씬 값 파일 e<kk>.bin: ``pack_values`` 배열(pa·fn·fmag·u — 같은 바이트) 뒤에 c(int16)·dc(int16, 있을 때만), 4바이트 정렬."""
    buf, arrays = pack_values(p, fn, fmag, u)
    buf = bytearray(buf)
    for key, v in (("c", c), ("dc", dc)):
        if v is None:
            continue
        b, s = _q16(v)
        buf += b"\x00" * (-len(buf) % 4)
        arrays.append({"key": key, "dtype": "int16", "comps": 1, "offset": len(buf), "scale": s})
        buf += b
    buf += b"\x00" * (-len(buf) % 4)
    return bytes(buf), arrays


def _pct(v: np.ndarray, q: float) -> float | None:
    return float(np.percentile(v, q)) if v.size else None


def scene_ranges(c, dc=None) -> tuple[dict, dict | None]:
    """색 범위 자료(§2.3): c{min, max, p01, p99}·dc{abs_max, abs_p99} — 백분위는 값이 0 이 아닌 노드(하중 없는 노드 0 이 대부분이라
    전 노드 백분위는 0 에 붙음 — pa·fn 범위가 하중 노드만 쓰는 것과 같은 규칙). 없으면 None."""
    a = np.asarray(c, np.float64).reshape(-1)
    nz = a[a != 0]
    rc = {"min": float(a.min()) if a.size else 0.0, "max": float(a.max()) if a.size else 0.0,
          "p01": _pct(nz, 1.0), "p99": _pct(nz, 99.0)}
    rd = None
    if dc is not None:
        d = np.abs(np.asarray(dc, np.float64).reshape(-1))
        rd = {"abs_max": float(d.max()) if d.size else 0.0, "abs_p99": _pct(d[d != 0], 99.0)}
    return rc, rd


def build_scene_pack(out_dir: str, *, node_id, x0, conn, elem_type, scenes, cfg: dict[str, Any] | None = None,
                     key: str = "", src: str = "", did: str = "", units: dict[str, str] | None = None,
                     created_at: str | None = None, existing: dict | None = None, write_pack: bool = True) -> dict[str, Any]:
    """씬 묶음(계약 §2.2): out_dir 에 part.glb(``build_view`` 와 같은 바이트 규칙)·씬마다 e<kk>.bin·e<kk>.json·(part_lod.glb)·pack.json
    (마지막 — 없으면 미완성)을 쓰고 pack dict 를 돌려준다.

    scenes = 씬 dict 반복자(한 번에 하나씩 만들어도 됨 — 메모리 = 씬 1개): {entry_id, kk, f (N,3), u (N,3) 화면 변위, supports,
    c (N,) C 기여도, c_meta{kind, sum, offset, value, parts{W_F, W_v, W_g}}, dc (N,) | None, dc_meta | None, pins{umax{…}}}.
    existing = 같은 형상의 이전 pack.json(보충 — 그 씬·part 파일은 그대로 두고 새 씬만 더함). LOD 대표 값 = 씬별 면압의 노드별 최댓값.
    write_pack False = pack.json 을 아직 쓰지 않음(차이를 나중에 더할 묶음 — ``patch_scene_dc`` 뒤 ``write_pack_json``)."""
    c = {**DEFAULTS, **(cfg or {})}
    nid = np.asarray(node_id, np.int64)
    x0 = np.asarray(x0, np.float64)
    conn = np.asarray(conn, np.int64)
    n = nid.size
    if x0.shape != (n, 3) or not np.isfinite(x0).all():
        raise EslError("OUTPUT_INCONSISTENT", "node_id·x0 크기가 서로 다르거나 NaN/inf 가 있습니다")
    units = {"length": "mm", "force": "N", "pressure": "MPa", **(units or {})}
    os.makedirs(out_dir, exist_ok=True)
    P = _part(x0, conn, elem_type)
    geom, tris = P["geom"], P["tris"]
    lo, hi = P["lo"], P["hi"]
    old = existing if isinstance(existing, dict) and existing.get("builder_version") == SCENE_BUILDER_VERSION \
        and int(existing.get("n_nodes", -1)) == n and os.path.isfile(os.path.join(out_dir, GEOMETRY)) else None
    if old is not None:
        gbytes = int(old["geometry"]["bytes"])
    else:
        gbytes = write_glb(os.path.join(out_dir, GEOMETRY), P["q"], P["center"], P["half"], "_NODE_ID",
                           nid.astype(np.uint32), tris, _extras(units))
    p_max = np.zeros(n)
    docs: list[tuple[str, dict]] = []
    rows = list((old or {}).get("scenes") or [])
    for s in scenes:
        f = np.asarray(s["f"], np.float64)
        u = np.asarray(s["u"], np.float64)
        _check_inputs(nid, x0, conn, f, u)
        kk = int(s["kk"])
        mname, vname = scene_files(kk)
        fn, p = face_values(f, geom)
        np.maximum(p_max, p, out=p_max)
        mag = np.linalg.norm(f, axis=1)
        umag = np.linalg.norm(u, axis=1)
        cv = np.asarray(s["c"], np.float64).reshape(-1)
        dv = None if s.get("dc") is None else np.asarray(s["dc"], np.float64).reshape(-1)
        if cv.size != n or (dv is not None and dv.size != n) or not np.isfinite(cv).all() \
                or (dv is not None and not np.isfinite(dv).all()):
            raise EslError("OUTPUT_INCONSISTENT", "C 기여도·차이 배열 크기가 노드 수와 다르거나 NaN/inf 가 있습니다")
        vbytes, arrays = pack_scene_values(p, fn, mag, u, cv, dv)
        with open(os.path.join(out_dir, vname), "wb") as fh:
            fh.write(vbytes)
        sup_rows, sup_ids = _support_rows(nid, x0, s.get("supports") or ())
        ranges, sum_f, sum_m, mc = _load_fields(x0, f, p, fn, mag, umag, n)
        rc, rd = scene_ranges(cv, dv)
        ranges["c"] = rc
        ranges["dc"] = rd
        man = {
            "schema": SCHEMA, "builder_version": BUILDER_VERSION, "key": f"{key}/e{kk:02d}", "esl_run_id": str(s["entry_id"]),
            "n_nodes": int(n), "n_elems": int(conn.shape[0]), "n_tris": int(tris.shape[0]),
            "units": units["length"], "force_unit": units["force"], "pressure_unit": units["pressure"], "up": "Z",
            "bbox": {"min": lo.tolist(), "max": hi.tolist(), "diag": float(np.linalg.norm(hi - lo))},
            "plate_normal": geom.n_p.tolist(),
            "geometry": {"name": GEOMETRY, "bytes": gbytes}, "lod": None,
            "values": {"name": vname, "bytes": len(vbytes), "arrays": arrays},
            "ranges": ranges, "sum_f": sum_f, "sum_m": sum_m, "moment_center": mc,
            "supports": sup_rows,
            "top": top_rows(nid, x0, f, fn, p, sup_ids, int(c["top_max"])),
            "clusters": clusters(nid, x0, f, u, int(c["cluster_k_max"]), int(c["kmeans_max_iter"])),
            "created_at": _now(created_at),
            "c": {**dict(s["c_meta"]), "unit": C_UNIT},
            "dc": None if dv is None else dict(s.get("dc_meta") or {}),
            "pins": dict(s.get("pins") or {}),
        }
        docs.append((mname, man))
        rows = [r for r in rows if int(r["kk"]) != kk] + [{"entry_id": str(s["entry_id"]), "kk": kk, "manifest": mname,
                                                           "values": vname}]
    lod = (old or {}).get("lod")
    if n > int(c["lod_min_nodes"]) and docs and (old is None or lod is None
                                                 or not os.path.isfile(os.path.join(out_dir, GEOMETRY_LOD))):
        lod = _write_lod(out_dir, P, x0, p_max, c, units)
    for mname, man in docs:
        man["lod"] = lod
        with open(os.path.join(out_dir, mname), "w", encoding="utf-8") as fh:
            json.dump(man, fh, ensure_ascii=False, allow_nan=False)
    rows.sort(key=lambda r: int(r["kk"]))
    pack = {"schema": SCENE_SCHEMA, "builder_version": SCENE_BUILDER_VERSION, "key": key, "src": src, "did": did,
            "n_nodes": int(n), "n_elems": int(conn.shape[0]), "n_tris": int(tris.shape[0]),
            "bbox": {"min": lo.tolist(), "max": hi.tolist(), "diag": float(np.linalg.norm(hi - lo))},
            "plate_normal": geom.n_p.tolist(), "geometry": {"name": GEOMETRY, "bytes": gbytes}, "lod": lod,
            "scenes": rows, "created_at": _now(created_at)}
    if write_pack:
        write_pack_json(out_dir, pack)
    return pack


def write_pack_json(out_dir: str, pack: dict) -> None:
    """pack.json(묶음 완성 표시 — 마지막에 씀)."""
    with open(os.path.join(out_dir, PACK_JSON), "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, allow_nan=False)


def patch_scene_dc(out_dir: str, kk: int, dc, dc_meta: dict) -> None:
    """이미 쓴 씬(dc 없음)에 차이를 더함: e<kk>.bin 끝에 dc(int16 — ``pack_scene_values`` 와 같은 정렬·양자화, 결과 바이트 = 처음부터 dc 를
    넣어 쓴 것과 같음), e<kk>.json values·dc·ranges.dc 갱신."""
    mname, vname = scene_files(kk)
    with open(os.path.join(out_dir, mname), encoding="utf-8") as fh:
        man = json.load(fh)
    with open(os.path.join(out_dir, vname), "rb") as fh:
        buf = bytearray(fh.read())
    dv = np.asarray(dc, np.float64).reshape(-1)
    if dv.size != int(man["n_nodes"]) or not np.isfinite(dv).all():
        raise EslError("OUTPUT_INCONSISTENT", "차이 배열 크기가 노드 수와 다르거나 NaN/inf 가 있습니다")
    if any(a["key"] == "dc" for a in man["values"]["arrays"]):
        raise EslError("OUTPUT_INCONSISTENT", f"{mname}: 차이가 이미 있습니다")
    b, sc = _q16(dv)
    buf += b"\x00" * (-len(buf) % 4)
    man["values"]["arrays"].append({"key": "dc", "dtype": "int16", "comps": 1, "offset": len(buf), "scale": sc})
    buf += b
    buf += b"\x00" * (-len(buf) % 4)
    man["values"]["bytes"] = len(buf)
    man["dc"] = dict(dc_meta)
    man["ranges"]["dc"] = scene_ranges(np.zeros(0), dv)[1]
    with open(os.path.join(out_dir, vname), "wb") as fh:
        fh.write(bytes(buf))
    with open(os.path.join(out_dir, mname), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, allow_nan=False)
