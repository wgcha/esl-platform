"""순수 Python PNG 인코더 + 평면도 렌더러 (계약 esl_opt_run.md §9 bead_map.png·keepout.png). 의존성: numpy + zlib.

- ``encode_png(rgb)``: (H, W, 3) uint8 → PNG 바이트(필터 0, zlib 9 — 같은 입력이면 같은 바이트).
- ``render_plan(mesh, frame, …)``: 대상 (a, b) mm 평면도. 요소를 삼각형으로 나눠 픽셀 중심 포함 판정으로 래스터화
  (요소 번호 버퍼) → 값이 있으면 순차 색(0 → vmax), 비설계·금지 영역은 회색 빗금, 사각형 외곽선 주황,
  3-2-1 지지 초록 기호, 색 막대 범례(숫자는 5×7 비트맵 글꼴).
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

from esl.opt.keepout import project_ab

# 순차 색(viridis 근사 앵커)
_SEQ = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=np.float64)
BG = (255, 255, 255)
EDGE_GRAY = (200, 200, 200)
HATCH_BG = (225, 225, 225)
HATCH_FG = (150, 150, 150)
NODATA = (235, 241, 250)
ORANGE = (230, 120, 20)
GREEN = (20, 150, 60)
BLACK = (30, 30, 30)

_FONT = {  # 5×7, 행 = 위→아래, 비트 4..0 = 왼→오
    "0": [14, 17, 19, 21, 25, 17, 14], "1": [4, 12, 4, 4, 4, 4, 14], "2": [14, 17, 1, 2, 4, 8, 31],
    "3": [31, 2, 4, 2, 1, 17, 14], "4": [2, 6, 10, 18, 31, 2, 2], "5": [31, 16, 30, 1, 1, 17, 14],
    "6": [6, 8, 16, 30, 17, 17, 14], "7": [31, 1, 2, 4, 8, 8, 8], "8": [14, 17, 17, 14, 17, 17, 14],
    "9": [14, 17, 17, 15, 1, 2, 12], ".": [0, 0, 0, 0, 0, 12, 12], "-": [0, 0, 0, 31, 0, 0, 0],
    "+": [0, 4, 4, 31, 4, 4, 0], "E": [31, 16, 16, 30, 16, 16, 31], "m": [0, 0, 26, 21, 21, 17, 17],
    "h": [16, 16, 22, 25, 17, 17, 17], "=": [0, 0, 31, 0, 31, 0, 0], " ": [0] * 7,
}


def encode_png(rgb: np.ndarray) -> bytes:
    a = np.ascontiguousarray(rgb, dtype=np.uint8)
    if a.ndim != 3 or a.shape[2] != 3:
        raise ValueError("rgb 는 (H, W, 3) uint8")
    h, w = a.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), a.reshape(h, w * 3)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def decode_png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG 아님")
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def seq_color(v: np.ndarray) -> np.ndarray:
    v = np.clip(np.asarray(v, dtype=np.float64), 0.0, 1.0) * (len(_SEQ) - 1)
    i = np.minimum(np.floor(v).astype(int), len(_SEQ) - 2)
    t = (v - i)[..., None]
    return np.round(_SEQ[i] * (1 - t) + _SEQ[i + 1] * t).astype(np.uint8)


class Canvas:
    def __init__(self, w: int, h: int):
        self.w, self.h = int(w), int(h)
        self.img = np.empty((self.h, self.w, 3), np.uint8)
        self.img[:] = BG

    def rect(self, x0, y0, x1, y1, color, fill=True):
        x0, x1 = sorted((int(round(x0)), int(round(x1))))
        y0, y1 = sorted((int(round(y0)), int(round(y1))))
        x0c, x1c, y0c, y1c = max(x0, 0), min(x1, self.w - 1), max(y0, 0), min(y1, self.h - 1)
        if x0c > x1c or y0c > y1c:
            return
        if fill:
            self.img[y0c:y1c + 1, x0c:x1c + 1] = color
        else:
            for (a, b, c, d) in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)):
                self.line(a, b, c, d, color)

    def line(self, x0, y0, x1, y1, color, width: int = 1):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.round(np.linspace(x0, x1, n)).astype(int)
        ys = np.round(np.linspace(y0, y1, n)).astype(int)
        for dx in range(width):
            for dy in range(width):
                x, y = xs + dx - width // 2, ys + dy - width // 2
                ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
                self.img[y[ok], x[ok]] = color

    def text(self, x, y, s: str, color=BLACK, scale: int = 2):
        cx = int(x)
        for ch in s:
            g = _FONT.get(ch, _FONT[" "])
            for r, bits in enumerate(g):
                for c in range(5):
                    if bits >> (4 - c) & 1:
                        self.rect(cx + c * scale, y + r * scale, cx + (c + 1) * scale - 1, y + (r + 1) * scale - 1, color)
            cx += 6 * scale
        return cx

    def png(self) -> bytes:
        return encode_png(self.img)


def _triangles(conn, et):
    conn = np.asarray(conn, dtype=np.int64)
    et = np.asarray(et).astype(int)
    q = np.flatnonzero(et == 4)
    t = np.flatnonzero(et != 4)
    tri = np.concatenate([conn[t][:, :3], conn[q][:, [0, 1, 2]], conn[q][:, [0, 2, 3]]])
    own = np.concatenate([t, q, q])
    return tri, own


def rasterize(P: np.ndarray, conn, et, w: int, h: int) -> np.ndarray:
    """픽셀 좌표 노드 P (N,2) → 요소 번호 버퍼 (h, w) int32 (-1 = 빈 곳). 뒤 요소가 덮어씀(결정적)."""
    buf = np.full((h, w), -1, dtype=np.int32)
    tri, own = _triangles(conn, et)
    if tri.size == 0:
        return buf
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    lo = np.floor(np.minimum(np.minimum(A, B), C) - 0.5).astype(int)
    hi = np.ceil(np.maximum(np.maximum(A, B), C) - 0.5).astype(int)
    lo = np.clip(lo, 0, [w - 1, h - 1])
    hi = np.clip(hi, 0, [w - 1, h - 1])
    span = hi - lo
    det = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (C[:, 0] - A[:, 0]) * (B[:, 1] - A[:, 1])
    ok = np.abs(det) > 1e-12
    eps = 1e-9
    big = ok & (np.max(span, axis=1) >= _SMALL_SPAN)
    small = ok & ~big

    def put(sel, px, py):
        x, y = px + 0.5, py + 0.5
        a, b, c = A[sel], B[sel], C[sel]
        d = det[sel]
        l1 = ((b[:, 0] - x) * (c[:, 1] - y) - (c[:, 0] - x) * (b[:, 1] - y)) / d
        l2 = ((c[:, 0] - x) * (a[:, 1] - y) - (a[:, 0] - x) * (c[:, 1] - y)) / d
        inside = (l1 >= -eps) & (l2 >= -eps) & (1.0 - l1 - l2 >= -eps)
        buf[py[inside], px[inside]] = own[sel[inside]]

    # 큰 삼각형(드묾): 삼각형마다 bbox 격자 먼저, 작은 삼각형: 오프셋(dx, dy)마다 전체를 한 번에(결정적 순서)
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
    return buf


_SMALL_SPAN = 20


def render_plan(mesh: dict, frame: dict, *, values=None, vmax: float | None = None, hatch_mask=None,
                rects: list | None = None, supports: list | None = None, size=(1600, 900),
                unit_label: str = "mm") -> bytes:
    """평면도 PNG. values (E,) 요소값(None 이면 연한 바탕), hatch_mask (E,) 회색 빗금, rects = keepout.compute 의
    rects(a·b 범위), supports = [(node_id, dof)]."""
    W, H = int(size[0]), int(size[1])
    cv = Canvas(W, H)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    ab = project_ab(frame, X)
    a0, a1 = map(float, frame["a_range"])
    b0, b1 = map(float, frame["b_range"])
    legend_w = 150 if values is not None else 0
    m = 30
    sx = (W - 2 * m - legend_w) / max(a1 - a0, 1e-9)
    sy = (H - 2 * m) / max(b1 - b0, 1e-9)
    s = min(sx, sy)
    ox = m + ((W - 2 * m - legend_w) - s * (a1 - a0)) / 2
    oy = m + ((H - 2 * m) - s * (b1 - b0)) / 2

    def to_px(a, b):
        return ox + (np.asarray(a) - a0) * s, H - (oy + (np.asarray(b) - b0) * s)

    px, py = to_px(ab[:, 0], ab[:, 1])
    buf = rasterize(np.column_stack([px, py]), mesh["conn"], mesh["elem_type"], W, H)
    ne = np.asarray(mesh["conn"]).shape[0]
    col = np.empty((ne, 3), np.uint8)
    if values is not None:
        v = np.asarray(values, dtype=np.float64)
        vm = float(vmax) if vmax else (float(np.nanmax(v)) if np.isfinite(v).any() and np.nanmax(v) > 0 else 1.0)
        col[:] = seq_color(np.nan_to_num(v / vm, nan=0.0))
    else:
        col[:] = NODATA
    hm = np.zeros(ne, bool) if hatch_mask is None else np.asarray(hatch_mask, dtype=bool)
    col[hm] = HATCH_BG
    inside = buf >= 0
    cv.img[inside] = col[buf[inside]]
    yy, xx = np.nonzero(inside)
    hsel = hm[buf[yy, xx]] & (((xx + yy) % 8) < 2)
    cv.img[yy[hsel], xx[hsel]] = HATCH_FG
    for r in rects or []:
        xa, ya = to_px(r["a"][0], r["b"][0])
        xb, yb = to_px(r["a"][1], r["b"][1])
        cv.rect(xa, ya, xb, yb, ORANGE, fill=False)
        cv.rect(xa + 1, ya - 1, xb - 1, yb + 1, ORANGE, fill=False)
    if supports:
        nid = np.asarray(mesh["node_id"], dtype=np.int64)
        pos = {int(v): i for i, v in enumerate(nid.tolist())}
        for n, dof in supports:
            i = pos.get(int(n))
            if i is None:
                continue
            x, y = px[i], py[i]
            k = 3 + len(str(dof)) * 2
            cv.line(x - k, y + k, x + k, y + k, GREEN, 2)
            cv.line(x - k, y + k, x, y - k, GREEN, 2)
            cv.line(x + k, y + k, x, y - k, GREEN, 2)
    cv.rect(ox, H - oy, ox + s * (a1 - a0), H - (oy + s * (b1 - b0)), EDGE_GRAY, fill=False)
    if values is not None:
        lx = W - legend_w + 20
        top, bot = m + 20, H - m - 20
        n = bot - top
        grad = seq_color(np.linspace(1.0, 0.0, n))
        cv.img[top:bot, lx:lx + 24] = grad[:, None, :]
        cv.rect(lx, top, lx + 24, bot, BLACK, fill=False)
        cv.text(lx + 30, top - 7, _fmt(vm) + " " + unit_label)
        cv.text(lx + 30, bot - 7, "0")
    return cv.png()


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if 0.01 <= abs(v) < 10000:
        return f"{v:.3g}" if abs(v) < 100 else f"{v:.0f}"
    return f"{v:.2E}"
