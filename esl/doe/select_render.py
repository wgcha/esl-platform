"""비드 직접 선택 미리보기 3D 썸네일 (계약 esl_bead_select.md §7.2, v0.15.0 — paicad 비의존, 순수 numpy).

- 시점(``view``): 영향 노드(기저 idx 합집합) 공칭 bbox 를 비드 평균 n̂ 방향(깊어짐을 보는 쪽 — 카메라는 −n̂ 쪽)에서 frame −η 로
  ``thumb.tilt_deg`` 기울인 직교 투영, 여백 ``thumb.margin``. 모든 칸 같은 시점·같은 축척(공칭 bbox 기준).
- 래스터: 내부 해상도 = (w, h) × ``supersample`` — ``png.rasterize`` 방식(오프셋 반복, 결정적)에 깊이 버퍼 추가
  (픽셀 중심 무게중심 보간 깊이, 가까운 것 유지, 동률 = 작은 삼각형 번호), 요소 법선 램버트(양면, 광원 = 시선 + 위 20°,
  주변광 ``thumb.ambient``) × 색, ``supersample``² 평균 축소 → ``png.encode_png``(결정적 바이트).
- 색: 발산(파랑 = 깊어짐 +, 흰 = 0, 빨강 = 얕아짐 −), 범위 ±V(모든 칸 같은 V), 영향 없는 삼각형 = 회색 음영.
  비드 경계(현재 위치) 진회색 1 px.
"""
from __future__ import annotations

import math

import numpy as np

from esl.opt.png import encode_png

GRAY = np.array([200.0, 200.0, 200.0])
BG = np.array([255.0, 255.0, 255.0])
EDGE = (70, 70, 70)
BLUE = np.array([33.0, 102.0, 172.0])
RED = np.array([178.0, 24.0, 43.0])
WHITE = np.array([247.0, 247.0, 247.0])
_SMALL = 24


def diverging(t: np.ndarray) -> np.ndarray:
    """t ∈ [−1, 1] → RGB float (−1 빨강, 0 흰, +1 파랑)."""
    t = np.clip(np.asarray(t, dtype=np.float64), -1.0, 1.0)[..., None]
    pos = WHITE + (BLUE - WHITE) * np.maximum(t, 0.0)
    neg = WHITE + (RED - WHITE) * np.maximum(-t, 0.0)
    return np.where(t >= 0, pos, neg)


def color_values(x0, x, direction, has) -> np.ndarray:
    """c_i = (x_d − x0)·n̂_b(노드 비드 방향, 깊어짐 +), 영향 밖 0."""
    c = np.einsum("ij,ij->i", np.asarray(x) - np.asarray(x0), direction)
    return np.where(has, c, 0.0)


def view_normal(x0, n_hats) -> np.ndarray:
    """SR-D-34 시점 법선: 비드마다 n̂_b(바닥 쪽 — 볼록·오목이면 서로 반대)를 판 법선(``view3d.plate_normal``) 쪽으로 맞춘 뒤 평균.
    볼록·오목이 섞여도 상쇄되지 않고, sense 와 무관하게 같은 쪽에서 본다."""
    from esl.view3d import plate_normal
    pn = plate_normal(np.asarray(x0, dtype=np.float64))
    ns = [np.asarray(n, dtype=np.float64) for n in n_hats]
    if not ns:
        return pn
    v = np.mean([n if float(n @ pn) >= 0 else -n for n in ns], axis=0)
    nv = float(np.linalg.norm(v))
    return v / nv if nv > 1e-12 else pn


def view(x0, affected: np.ndarray, n_hat_mean, frame: dict | None, tcfg: dict) -> dict:
    """{f(시선), r(오른쪽), u(위), center, scale(px/mm 내부), w, h} — 공칭 bbox 기준(모든 칸 같은 값).
    v0.16.1 SR-D-34: 시점 법선은 판 법선 쪽으로 맞추고 카메라는 그 쪽에서 내려다봄 — 볼록·오목(n̂ 부호)과 무관하게 화면 오른쪽 =
    η × n_p, 위 ≈ +η(n_p = 판 법선, η = frame e_eta 또는 y)."""
    from esl.view3d import plate_normal
    X = np.asarray(x0, dtype=np.float64)
    pts = X[affected] if np.any(affected) else X
    n = np.asarray(n_hat_mean, dtype=np.float64)
    n = n / max(np.linalg.norm(n), 1e-300)
    if float(n @ plate_normal(X)) < 0:
        n = -n
    eta = np.asarray((frame or {}).get("e_eta") or [0.0, 1.0, 0.0], dtype=np.float64)
    eta = eta - (eta @ n) * n
    if np.linalg.norm(eta) < 1e-9:
        eta = np.array([0.0, 1.0, 0.0]) if abs(n[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        eta = eta - (eta @ n) * n
    eta /= np.linalg.norm(eta)
    t = math.radians(float(tcfg["tilt_deg"]))
    # SR-D-34: 카메라 = 판 법선(+n) 쪽 위에서 내려다봄(−n), η 쪽으로 기울임 → 화면 오른쪽 = η × n, 위 ≈ +η(평면도와 같은 방향)
    f = -math.cos(t) * n + math.sin(t) * eta
    f /= np.linalg.norm(f)
    xi = np.cross(eta, n)
    r = xi - (xi @ f) * f
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    ss = int(tcfg["supersample"])
    W, H = int(tcfg["w"]) * ss, int(tcfg["h"]) * ss
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    corners = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1]) for c in (lo[2], hi[2])])
    center = 0.5 * (lo + hi)
    pr = (corners - center) @ r
    pu = (corners - center) @ u
    span_r = max(float(pr.max() - pr.min()), 1e-6) * float(tcfg["margin"])
    span_u = max(float(pu.max() - pu.min()), 1e-6) * float(tcfg["margin"])
    scale = min(W / span_r, H / span_u)
    return {"f": f, "r": r, "u": u, "center": center, "scale": scale, "w": W, "h": H, "ss": ss}


def _project(X, v):
    P = X - v["center"]
    px = v["w"] / 2.0 + (P @ v["r"]) * v["scale"]
    py = v["h"] / 2.0 - (P @ v["u"]) * v["scale"]
    dz = P @ v["f"]
    return np.column_stack([px, py]), dz


def raster_depth(P2: np.ndarray, depth: np.ndarray, tris: np.ndarray, w: int, h: int):
    """(삼각형 번호 버퍼 int32 (h,w) −1 = 빈 곳, 무게중심 l0·l1·l2 (h,w,3)). 가까운(depth 작은) 것, 동률 = 작은 번호."""
    tri_buf = np.full(h * w, -1, np.int64)
    zbuf = np.full(h * w, np.inf)
    lam = np.zeros((h * w, 3))
    A, B, C = P2[tris[:, 0]], P2[tris[:, 1]], P2[tris[:, 2]]
    lo = np.floor(np.minimum(np.minimum(A, B), C) - 0.5).astype(np.int64)
    hi = np.ceil(np.maximum(np.maximum(A, B), C) - 0.5).astype(np.int64)
    vis = (hi[:, 0] >= 0) & (hi[:, 1] >= 0) & (lo[:, 0] < w) & (lo[:, 1] < h)
    lo = np.clip(lo, 0, [w - 1, h - 1])
    hi = np.clip(hi, 0, [w - 1, h - 1])
    span = hi - lo
    det = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (C[:, 0] - A[:, 0]) * (B[:, 1] - A[:, 1])
    ok = vis & (np.abs(det) > 1e-12)
    dA, dB, dC = depth[tris[:, 0]], depth[tris[:, 1]], depth[tris[:, 2]]
    eps = 1e-9

    def put(sel, px, py):
        x, y = px + 0.5, py + 0.5
        a, b, c = A[sel], B[sel], C[sel]
        d = det[sel]
        l1 = ((b[:, 0] - x) * (c[:, 1] - y) - (c[:, 0] - x) * (b[:, 1] - y)) / d
        l2 = ((c[:, 0] - x) * (a[:, 1] - y) - (a[:, 0] - x) * (c[:, 1] - y)) / d
        l3 = 1.0 - l1 - l2
        ins = (l1 >= -eps) & (l2 >= -eps) & (l3 >= -eps)
        if not ins.any():
            return
        s, px, py, l1, l2, l3 = sel[ins], px[ins], py[ins], l1[ins], l2[ins], l3[ins]
        z = l1 * dA[s] + l2 * dB[s] + l3 * dC[s]
        pix = py * w + px
        # 같은 묶음 안 경합: (pix, z, tri) 정렬 첫 행
        o = np.lexsort((s, z, pix))
        pix, z, s, l1, l2, l3 = pix[o], z[o], s[o], l1[o], l2[o], l3[o]
        first = np.concatenate([[True], pix[1:] != pix[:-1]])
        pix, z, s, l1, l2, l3 = pix[first], z[first], s[first], l1[first], l2[first], l3[first]
        cur_z, cur_t = zbuf[pix], tri_buf[pix]
        better = (z < cur_z) | ((z == cur_z) & ((cur_t < 0) | (s < cur_t)))
        pix, z, s = pix[better], z[better], s[better]
        zbuf[pix] = z
        tri_buf[pix] = s
        lam[pix] = np.column_stack([l1[better], l2[better], l3[better]])

    big = ok & (np.max(span, axis=1) >= _SMALL)
    small = ok & ~big
    for t in np.flatnonzero(big):
        xs = np.arange(lo[t, 0], hi[t, 0] + 1)
        ys = np.arange(lo[t, 1], hi[t, 1] + 1)
        gx, gy = np.meshgrid(xs, ys)
        put(np.full(gx.size, t), gx.ravel(), gy.ravel())
    if small.any():
        for dy in range(int(span[small, 1].max()) + 1):
            for dx in range(int(span[small, 0].max()) + 1):
                sel = np.flatnonzero(small & (span[:, 0] >= dx) & (span[:, 1] >= dy))
                if sel.size:
                    put(sel, lo[sel, 0] + dx, lo[sel, 1] + dy)
    return tri_buf.reshape(h, w), lam.reshape(h, w, 3)


def _line(img, p0, p1, color):
    n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))) + 1
    xs = np.round(np.linspace(p0[0], p1[0], n)).astype(int)
    ys = np.round(np.linspace(p0[1], p1[1], n)).astype(int)
    ok = (xs >= 0) & (xs < img.shape[1]) & (ys >= 0) & (ys < img.shape[0])
    img[ys[ok], xs[ok]] = color


def render(x, tris: np.ndarray, c: np.ndarray | None, has: np.ndarray | None, v: dict, v_max: float, tcfg: dict,
           loops=()) -> bytes:
    """안 좌표 x(N,3)·삼각형(T,3)·노드 색 값 c(N)(None = 공칭 회색) → PNG 바이트(w×h)."""
    X = np.asarray(x, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)
    P2, dz = _project(X, v)
    W, H, ss = v["w"], v["h"], v["ss"]
    buf, lam = raster_depth(P2, dz, tris, W, H)
    # 램버트(양면)
    a, b, cc = X[tris[:, 0]], X[tris[:, 1]], X[tris[:, 2]]
    n = np.cross(b - a, cc - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    el = math.radians(20.0)
    L = -(math.cos(el) * v["f"]) + math.sin(el) * v["u"]
    L /= np.linalg.norm(L)
    amb = float(tcfg["ambient"])
    shade_t = amb + (1.0 - amb) * np.abs(n @ L)
    img = np.empty((H, W, 3))
    img[:] = BG
    m = buf >= 0
    t = buf[m]
    sh = shade_t[t][:, None]
    if c is None or v_max <= 0:
        col = np.broadcast_to(GRAY, (t.size, 3))
    else:
        tv = tris[t]
        l = lam[m]
        cv = (l[:, 0] * c[tv[:, 0]] + l[:, 1] * c[tv[:, 1]] + l[:, 2] * c[tv[:, 2]]) / v_max
        aff = has[tv].any(axis=1) if has is not None else np.ones(t.size, bool)
        col = np.where(aff[:, None], diverging(cv), GRAY)
    img[m] = col * sh
    out = img.reshape(H // ss, ss, W // ss, ss, 3).mean(axis=(1, 3))
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    for lp in loops:
        q = P2[np.asarray(lp, dtype=np.int64)] / ss
        for i in range(len(q)):
            _line(out, q[i], q[(i + 1) % len(q)], EDGE)
    return encode_png(out)


def png_rgb(data: bytes) -> np.ndarray:
    """encode_png 결과(필터 0, RGB8) 해독 — 시험·검증용."""
    import struct
    import zlib
    w, h = struct.unpack(">II", data[16:24])
    pos, chunks = 8, []
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        if tag == b"IDAT":
            chunks.append(data[pos + 8:pos + 8 + ln])
        pos += 12 + ln
    raw = np.frombuffer(zlib.decompress(b"".join(chunks)), np.uint8).reshape(h, w * 3 + 1)
    return raw[:, 1:].reshape(h, w, 3)
