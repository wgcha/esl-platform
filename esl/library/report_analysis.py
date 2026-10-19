"""종합분석 HTML 보고서 (계약 esl_p2_library.md §5, §8).

``write(analysis_result, out_html, arrays=None, opt_summary=None, info=None) -> str``

- 자체 완결 단일 파일: CSS·inline SVG·데이터·JS(정렬·필터 소량) 모두 내장, 외부 URL·CDN·폰트 0
  (SVG 는 HTML5 inline 이라 xmlns 도 쓰지 않음).
- 라이트/다크: CSS 변수, ``prefers-color-scheme`` + ``data-theme`` 둘 다. 히트맵은 테마 색 + 불투명도 램프라
  두 테마에서 같은 의미(0 = 바탕색으로 사라짐).
- 절: 표지 · 필터/요약 · 씬 표(정렬·필터) · 포락 히트맵(정규화 격자 + 대상 외곽) · 대표 케이스(모드 에너지 곡선,
  선택 씬, 셀 하중: 법선 성분 발산 색 + 면내 화살표) · 통계 뷰(유형·인치별 Σ|F|, SVD 계수 산점, 검증 오차) ·
  최적화 설정 · 한계.
"""
from __future__ import annotations

import html
import json
import math
import os

import numpy as np

from esl.library import _util as U

MAX_OUTLINE_SEGMENTS = 30000
SHAPES = ("circle", "square", "triangle", "diamond", "cross", "circle", "square", "triangle")


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _fmt(v, p=4) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(v):
        return str(v)
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        return f"{v:.{p - 1}e}"
    return f"{v:.{p}g}"


def _pct(v) -> str:
    return "—" if v is None else f"{100 * float(v):.2f}%"


CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--panel:#ffffff;--fg:#0b0b0b;--muted:#52514e;--faint:#8a8984;--grid:#e4e3df;
--line:#d3d2cc;--seq:#2a78d6;--pos:#2a78d6;--neg:#eb6834;--hl:#e34948;
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--c6:#008300;--c7:#6250d6;--c8:#e34948;
--pass:#008300;--fail:#c43c3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#1a1a19;
--panel:#232322;--fg:#f0efec;--muted:#c3c2b7;--faint:#8f8e86;--grid:#363633;--line:#4a4945;--seq:#5598e7;
--pos:#5598e7;--neg:#d95926;--hl:#e66767;--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;
--c6:#008300;--c7:#9085e9;--c8:#e66767;--pass:#3fae3f;--fail:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--panel:#232322;--fg:#f0efec;--muted:#c3c2b7;
--faint:#8f8e86;--grid:#363633;--line:#4a4945;--seq:#5598e7;--pos:#5598e7;--neg:#d95926;--hl:#e66767;
--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--c6:#008300;--c7:#9085e9;--c8:#e66767;
--pass:#3fae3f;--fail:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI","Malgun Gothic",
"Apple SD Gothic Neo",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}
.card>h3:first-child{margin-top:2px}
.sub{color:var(--muted)}.muted{color:var(--muted)}.small{font-size:12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.tile .v{font-size:22px;font-weight:600}.tile .k{color:var(--muted);font-size:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,470px),1fr));gap:12px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:4px 6px;border-bottom:1px solid var(--grid);text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}
th.sort{cursor:pointer;user-select:none}th.sort:after{content:" \\2195";color:var(--faint)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.tablewrap{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.filters input,.filters select{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;
padding:4px 8px;font:inherit}
.chip{display:inline-block;border:1px solid var(--line);border-radius:12px;padding:1px 8px;margin:2px;font-size:12px}
.badge{display:inline-block;padding:0 6px;border-radius:4px;font-size:11.5px;font-weight:600}
.pass{color:var(--pass)}.fail{color:var(--fail)}
svg{display:block;max-width:100%;height:auto}
svg text{fill:var(--muted);font-size:11px}svg .ttl{fill:var(--fg);font-size:12px;font-weight:600}
svg .ax{stroke:var(--line);stroke-width:1}svg .gl{stroke:var(--grid);stroke-width:1}
svg .ol{stroke:var(--fg);stroke-width:1.2;fill:none;opacity:.75}
svg rect.cell:hover,svg .pt:hover{stroke:var(--fg);stroke-width:1.5}
ul.lim li{margin:4px 0}
code{font-size:12px}
"""

JS = """
(function(){
 function cellv(td){var v=td.getAttribute('data-v');if(v===null)v=td.textContent;var n=parseFloat(v);
  return isNaN(n)?v.toLowerCase():n;}
 document.querySelectorAll('table.sortable').forEach(function(t){
  t.querySelectorAll('th.sort').forEach(function(th,ci){var asc=true;th.addEventListener('click',function(){
   var tb=t.tBodies[0];var rows=Array.prototype.slice.call(tb.rows);var idx=th.cellIndex;
   rows.sort(function(a,b){var x=cellv(a.cells[idx]),y=cellv(b.cells[idx]);
    if(typeof x==='number'&&typeof y==='number')return asc?x-y:y-x;return asc?String(x).localeCompare(String(y)):
    String(y).localeCompare(String(x));});
   asc=!asc;rows.forEach(function(r){tb.appendChild(r);});});});});
 var q=document.getElementById('f-text'),d=document.getElementById('f-drop'),v=document.getElementById('f-verdict'),
     c=document.getElementById('f-cluster'),cnt=document.getElementById('f-count');
 function apply(){var rows=document.querySelectorAll('#scenes tbody tr');var n=0;
  rows.forEach(function(r){var ok=(!q.value||r.textContent.toLowerCase().indexOf(q.value.toLowerCase())>=0)&&
   (!d.value||r.getAttribute('data-drop')===d.value)&&(!v.value||r.getAttribute('data-verdict')===v.value)&&
   (!c.value||r.getAttribute('data-cluster')===c.value);r.style.display=ok?'':'none';if(ok)n++;});
  if(cnt)cnt.textContent=n+' / '+rows.length;}
 [q,d,v,c].forEach(function(el){if(el)el.addEventListener('input',apply);});apply();
})();
"""


# ---------------------------------------------------------------- SVG 도구
def _svg(w, h, body, label) -> str:
    return (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" role="img" '
            f'aria-label="{_e(label)}">{body}</svg>')


def _plot_box(fr, w=620, maxh=460):
    if fr and fr.get("L_xi") and fr.get("L_eta"):
        ar = float(fr["L_eta"]) / float(fr["L_xi"])
    else:
        ar = 14 / 24
    ar = min(max(ar, 0.25), 1.6)
    pw = w
    ph = pw * ar
    if ph > maxh:
        ph = maxh
        pw = ph / ar
    return pw, ph


def _arrow(x0, y0, dx, dy, cls_color, width=1.4) -> str:
    L = math.hypot(dx, dy)
    if L < 1.0:
        return ""
    ux, uy = dx / L, dy / L
    hx, hy = x0 + dx, y0 + dy
    hs = min(5.0, 0.4 * L)
    p1 = (hx - ux * hs - uy * hs * 0.55, hy - uy * hs + ux * hs * 0.55)
    p2 = (hx - ux * hs + uy * hs * 0.55, hy - uy * hs - ux * hs * 0.55)
    return (f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{hx - ux * hs * 0.6:.1f}" y2="{hy - uy * hs * 0.6:.1f}" '
            f'stroke="{cls_color}" stroke-width="{width}"/>'
            f'<polygon points="{hx:.1f},{hy:.1f} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="{cls_color}"/>')


def _outline_path(outline, ox, oy, pw, ph) -> str:
    if outline is None or len(outline) == 0:
        return ""
    seg = np.asarray(outline, dtype=float)
    if seg.shape[0] > MAX_OUTLINE_SEGMENTS:
        seg = seg[:: int(math.ceil(seg.shape[0] / MAX_OUTLINE_SEGMENTS))]
    parts = []
    for (a, b) in seg:
        parts.append(f"M{ox + a[0] * pw:.1f} {oy + (1 - a[1]) * ph:.1f}L{ox + b[0] * pw:.1f} {oy + (1 - b[1]) * ph:.1f}")
    return f'<path class="ol" d="{"".join(parts)}"/>'


def heatmap(values, fr, outline=None, tips=None, mode="seq", vec=None, title="", w=620, legend_label="",
            highlight=None) -> str:
    """values (nx,ny). mode seq: |값| 불투명도 램프(--seq), div: 부호별 --pos/--neg. vec (nx,ny,2) 면내 화살표."""
    V = np.asarray(values, dtype=float)
    nx, ny = V.shape
    pw, ph = _plot_box(fr, w - 90)
    ox, oy = 46.0, 24.0
    W, H = pw + 90, ph + 84
    vmax = float(np.max(np.abs(V))) if V.size else 0.0
    cw, chh = pw / nx, ph / ny
    out = [f'<text class="ttl" x="{ox}" y="15">{_e(title)}</text>']
    for i in range(nx):
        for j in range(ny):
            v = V[i, j]
            a = (abs(v) / vmax) if vmax > 0 else 0.0
            col = "var(--seq)" if mode == "seq" else ("var(--pos)" if v >= 0 else "var(--neg)")
            x, y = ox + i * cw, oy + (ny - 1 - j) * chh
            tip = tips[i][j] if tips is not None else f"({i},{j}) {_fmt(v)}"
            out.append(f'<rect class="cell" x="{x + 0.5:.1f}" y="{y + 0.5:.1f}" width="{max(cw - 1, 0.5):.1f}" '
                       f'height="{max(chh - 1, 0.5):.1f}" fill="{col}" fill-opacity="{0.06 + 0.94 * a:.3f}" rx="1">'
                       f'<title>{_e(tip)}</title></rect>')
    if highlight is not None:
        i, j = highlight
        out.append(f'<rect x="{ox + i * cw:.1f}" y="{oy + (ny - 1 - j) * chh:.1f}" width="{cw:.1f}" height="{chh:.1f}" '
                   f'fill="none" stroke="var(--hl)" stroke-width="2"/>')
    out.append(_outline_path(outline, ox, oy, pw, ph))
    if vec is not None:
        Vv = np.asarray(vec, dtype=float)
        m = float(np.max(np.linalg.norm(Vv, axis=2))) if Vv.size else 0.0
        if m > 0:
            s = 0.48 * min(cw, chh) / m
            for i in range(nx):
                for j in range(ny):
                    cx, cy = ox + (i + 0.5) * cw, oy + (ny - 1 - j + 0.5) * chh
                    out.append(_arrow(cx, cy, Vv[i, j, 0] * s, -Vv[i, j, 1] * s, "var(--fg)", 1.1))
    out.append(f'<rect x="{ox}" y="{oy}" width="{pw:.1f}" height="{ph:.1f}" fill="none" class="ax"/>')
    out.append(f'<text x="{ox + pw / 2:.1f}" y="{oy + ph + 16:.1f}" text-anchor="middle">ξ (가로) →</text>')
    out.append(f'<text x="{ox - 8}" y="{oy + ph / 2:.1f}" text-anchor="middle" '
               f'transform="rotate(-90 {ox - 8} {oy + ph / 2:.1f})">η (세로) →</text>')
    # 색 막대
    lx, ly, lw = ox, oy + ph + 28, min(260.0, pw)
    n = 24
    for k in range(n):
        t = (k + 0.5) / n
        if mode == "seq":
            col, a = "var(--seq)", t
        else:
            col, a = ("var(--neg)", 1 - 2 * t) if t < 0.5 else ("var(--pos)", 2 * t - 1)
        out.append(f'<rect x="{lx + k * lw / n:.1f}" y="{ly}" width="{lw / n + 0.3:.1f}" height="9" fill="{col}" '
                   f'fill-opacity="{0.06 + 0.94 * a:.3f}"/>')
    lo = "0" if mode == "seq" else _fmt(-vmax, 3)
    out.append(f'<text x="{lx}" y="{ly + 21}">{lo}</text>')
    out.append(f'<text x="{lx + lw}" y="{ly + 21}" text-anchor="end">{_fmt(vmax, 3)}</text>')
    out.append(f'<text x="{lx + lw + 10}" y="{ly + 8}">{_e(legend_label)}</text>')
    return _svg(W, H, "".join(out), title)


def line_chart(xs, ys, title, xlabel, ylabel, hline=None, vline=None, w=520, h=260, bars=None) -> str:
    ox, oy, pw, ph = 52, 26, w - 70, h - 66
    xs = list(xs)
    xmin, xmax = (min(xs) - 0.5, max(xs) + 0.5) if xs else (0, 1)
    X = lambda v: ox + (v - xmin) / (xmax - xmin) * pw   # noqa: E731
    Y = lambda v: oy + (1 - v) * ph                      # noqa: E731
    out = [f'<text class="ttl" x="{ox}" y="15">{_e(title)}</text>']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        out.append(f'<line class="gl" x1="{ox}" x2="{ox + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text x="{ox - 6}" y="{Y(t) + 4:.1f}" text-anchor="end">{t:.2f}</text>')
    if bars is not None:
        bw = max(min(pw / max(len(xs), 1) * 0.6, 18), 2)
        for x, b in zip(xs, bars):
            out.append(f'<rect x="{X(x) - bw / 2:.1f}" y="{Y(b):.1f}" width="{bw:.1f}" height="{Y(0) - Y(b):.1f}" '
                       f'fill="var(--c3)" fill-opacity=".55" rx="2"><title>모드 {x}: 에너지 {b:.4f}</title></rect>')
    if hline is not None:
        out.append(f'<line x1="{ox}" x2="{ox + pw}" y1="{Y(hline):.1f}" y2="{Y(hline):.1f}" stroke="var(--neg)" '
                   f'stroke-dasharray="5 4" stroke-width="1.5"/><text x="{ox + pw}" y="{Y(hline) - 4:.1f}" '
                   f'text-anchor="end">기준 {hline:.2f}</text>')
    if vline is not None:
        out.append(f'<line x1="{X(vline):.1f}" x2="{X(vline):.1f}" y1="{oy}" y2="{oy + ph}" stroke="var(--faint)" '
                   f'stroke-dasharray="3 3"/><text x="{X(vline) + 4:.1f}" y="{oy + 12}">r = {vline}</text>')
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    out.append(f'<polyline points="{pts}" fill="none" stroke="var(--c1)" stroke-width="2"/>')
    for x, y in zip(xs, ys):
        out.append(f'<circle class="pt" cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="var(--c1)" stroke="var(--panel)" '
                   f'stroke-width="2"><title>모드 {x}: 누적 {y:.4f}</title></circle>')
    step = max(1, int(math.ceil(len(xs) / 12)))
    for x in xs[::step]:
        out.append(f'<text x="{X(x):.1f}" y="{oy + ph + 15}" text-anchor="middle">{x}</text>')
    out.append(f'<line class="ax" x1="{ox}" x2="{ox + pw}" y1="{oy + ph}" y2="{oy + ph}"/>')
    out.append(f'<text x="{ox + pw / 2:.1f}" y="{h - 8}" text-anchor="middle">{_e(xlabel)}</text>')
    out.append(f'<text x="12" y="{oy + ph / 2:.1f}" text-anchor="middle" transform="rotate(-90 12 {oy + ph / 2:.1f})">'
               f'{_e(ylabel)}</text>')
    return _svg(w, h, "".join(out), title)


def _marker(shape, x, y, r, color, tip, extra="") -> str:
    t = f"<title>{_e(tip)}</title>"
    if shape == "square":
        return (f'<rect class="pt" x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                f'fill="{color}" stroke="var(--panel)" stroke-width="2" {extra}>{t}</rect>')
    if shape == "triangle":
        return (f'<polygon class="pt" points="{x:.1f},{y - r * 1.2:.1f} {x - r * 1.1:.1f},{y + r * 0.8:.1f} '
                f'{x + r * 1.1:.1f},{y + r * 0.8:.1f}" fill="{color}" stroke="var(--panel)" stroke-width="2" {extra}>'
                f'{t}</polygon>')
    if shape == "diamond":
        return (f'<polygon class="pt" points="{x:.1f},{y - r * 1.25:.1f} {x + r * 1.25:.1f},{y:.1f} {x:.1f},'
                f'{y + r * 1.25:.1f} {x - r * 1.25:.1f},{y:.1f}" fill="{color}" stroke="var(--panel)" '
                f'stroke-width="2" {extra}>{t}</polygon>')
    if shape == "cross":
        return (f'<path class="pt" d="M{x - r:.1f} {y - r:.1f}L{x + r:.1f} {y + r:.1f}M{x - r:.1f} {y + r:.1f}'
                f'L{x + r:.1f} {y - r:.1f}" stroke="{color}" stroke-width="3" {extra}>{t}</path>')
    return (f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" stroke="var(--panel)" '
            f'stroke-width="2" {extra}>{t}</circle>')


def scatter(points, title, xlabel, ylabel, w=520, h=360) -> str:
    """points: [{x, y, cluster, label, tip, big}]"""
    ox, oy, pw, ph = 56, 26, w - 76, h - 70
    if not points:
        return ""
    xs = np.array([p["x"] for p in points], float)
    ys = np.array([p["y"] for p in points], float)

    def rng(v):
        lo, hi = float(v.min()), float(v.max())
        if hi == lo:
            lo, hi = lo - 1, hi + 1
        pad = 0.08 * (hi - lo)
        return lo - pad, hi + pad

    x0, x1 = rng(xs)
    y0, y1 = rng(ys)
    X = lambda v: ox + (v - x0) / (x1 - x0) * pw   # noqa: E731
    Y = lambda v: oy + (1 - (v - y0) / (y1 - y0)) * ph   # noqa: E731
    out = [f'<text class="ttl" x="{ox}" y="15">{_e(title)}</text>',
           f'<rect x="{ox}" y="{oy}" width="{pw}" height="{ph}" fill="none" class="ax"/>']
    if x0 < 0 < x1:
        out.append(f'<line class="gl" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{oy}" y2="{oy + ph}"/>')
    if y0 < 0 < y1:
        out.append(f'<line class="gl" x1="{ox}" x2="{ox + pw}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>')
    for t in np.linspace(x0, x1, 5):
        out.append(f'<text x="{X(t):.1f}" y="{oy + ph + 15}" text-anchor="middle">{_fmt(t, 2)}</text>')
    for t in np.linspace(y0, y1, 5):
        out.append(f'<text x="{ox - 6}" y="{Y(t) + 4:.1f}" text-anchor="end">{_fmt(t, 2)}</text>')
    for p in points:
        c = int(p.get("cluster", 0))
        col = f"var(--c{c % 8 + 1})"
        r = 7.5 if p.get("big") else 5
        out.append(_marker(SHAPES[c % len(SHAPES)], X(p["x"]), Y(p["y"]), r, col, p.get("tip", "")))
        if p.get("label"):
            out.append(f'<text x="{X(p["x"]) + 9:.1f}" y="{Y(p["y"]) - 7:.1f}" style="fill:var(--fg)">'
                       f'{_e(p["label"])}</text>')
    out.append(f'<text x="{ox + pw / 2:.1f}" y="{h - 10}" text-anchor="middle">{_e(xlabel)}</text>')
    out.append(f'<text x="14" y="{oy + ph / 2:.1f}" text-anchor="middle" transform="rotate(-90 14 {oy + ph / 2:.1f})">'
               f'{_e(ylabel)}</text>')
    return _svg(w, h, "".join(out), title)


def strip(groups, title, xlabel, w=520, fmt_tip=None) -> str:
    """groups: [(group label, [(value, cluster, tip)])] → 가로 strip plot."""
    groups = [g for g in groups if g[1]]
    if not groups:
        return ""
    rowh = 30
    ox, oy = 110, 26
    pw = w - ox - 20
    h = oy + rowh * len(groups) + 40
    vals = np.array([v for _, pts in groups for v, _, _ in pts], float)
    lo, hi = float(min(vals.min(), 0.0)), float(vals.max())
    if hi == lo:
        hi = lo + 1
    X = lambda v: ox + (v - lo) / (hi - lo) * pw    # noqa: E731
    out = [f'<text class="ttl" x="{ox - 100}" y="15">{_e(title)}</text>']
    for t in np.linspace(lo, hi, 5):
        out.append(f'<line class="gl" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{oy}" y2="{oy + rowh * len(groups)}"/>'
                   f'<text x="{X(t):.1f}" y="{oy + rowh * len(groups) + 14}" text-anchor="middle">{_fmt(t, 3)}</text>')
    for gi, (lab, pts) in enumerate(groups):
        cy = oy + rowh * gi + rowh / 2
        out.append(f'<text x="{ox - 8}" y="{cy + 4:.1f}" text-anchor="end">{_e(lab)} ({len(pts)})</text>')
        for k, (v, c, tip) in enumerate(pts):
            jit = ((k * 7919) % 11 - 5) * 1.6
            out.append(_marker(SHAPES[int(c) % len(SHAPES)], X(v), cy + jit, 4.5, f"var(--c{int(c) % 8 + 1})", tip))
    out.append(f'<text x="{ox + pw / 2:.1f}" y="{h - 6}" text-anchor="middle">{_e(xlabel)}</text>')
    return _svg(w, h, "".join(out), title)


# ---------------------------------------------------------------- 본문
def _verdict(v) -> str:
    if v == "PASS":
        return '<span class="badge pass">✓ PASS</span>'
    if v == "FAIL":
        return '<span class="badge fail">✕ FAIL</span>'
    return '<span class="muted">—</span>'


def _scene_label(c) -> str:
    return (f"{c.get('product') or '?'} {c.get('drop_class') or c.get('drop_type') or '?'}{c.get('orient') or ''}"
            f" S{c.get('scene') if c.get('scene') is not None else '?'}")


def write(analysis_result: dict, out_html: str, arrays: dict | None = None, opt_summary: dict | None = None,
          info: dict | None = None) -> str:
    """arrays 가 없으면 out_html 옆 mapped_loads.npz (analysis.save 산출물)를 읽는다."""
    if arrays is None:
        arrays = U.load_npz(os.path.join(os.path.dirname(os.path.abspath(out_html)), "mapped_loads.npz"))
    r = analysis_result
    info = info or {}
    cases = r["cases"]
    nx, ny = r["grid"]["nx"], r["grid"]["ny"]
    tgt = r.get("target")
    fr = (tgt or {}).get("frame")
    outline = arrays.get("outline")
    S = []
    title = info.get("title") or "ESL 종합분석 보고서"
    S.append(f"<header><h1>{_e(title)}</h1><div class='sub'>분석 ID <b>{_e(info.get('analysis_id', '—'))}</b> · "
             f"생성 {_e(r.get('created_at'))} · 항목 {r['n_cases']}개 · 대상 "
             f"{_e((tgt or {}).get('entry_id') or '없음(정규화 격자 기준)')}</div></header>")
    # ---- 요약 타일
    env_max = r["envelope"]["max"]
    tiles = [("항목(씬)", r["n_cases"]), ("SVD 모드 r", f"{r['svd']['n_modes']} (≥{r['svd']['threshold']:.2f})"),
             ("대표 케이스", len([lc for lc in r["load_cases"] if lc["role"] == "medoid"])),
             ("하중 케이스(덱)", len(r["load_cases"])), ("셀 포락 최대 |F|", _fmt(env_max)),
             ("PASS 비율", _pct(np.mean([c.get("verdict") == "PASS" for c in cases])) if cases else "—")]
    if r.get("mapping"):
        tiles.append(("매핑 보존 오차 최대", _fmt(r["mapping"]["conservation_rel_max"], 2)))
    S.append("<div class='tiles'>" + "".join(f"<div class='tile'><div class='v'>{_e(v)}</div><div class='k'>{_e(k)}"
                                             f"</div></div>" for k, v in tiles) + "</div>")
    # ---- 대상·필터
    o = r["opts"]
    filt = info.get("filters") or {}
    chips = "".join(f"<span class='chip'>{_e(k)} = {_e(v)}</span>" for k, v in filt.items()) or \
        "<span class='muted'>없음(전체 활성 항목)</span>"
    tm = (tgt or {}).get("model") or {}
    S.append("<h2>1. 대상 · 필터 · 설정</h2><div class='grid2'><div class='card'><h3>대상 모델</h3>")
    if tgt:
        S.append(f"<table><tr><th>항목</th><td>{_e(tgt['entry_id'])}</td></tr><tr><th>제품·인치</th><td>"
                 f"{_e(tm.get('product'))} · {_e(tm.get('inch'))}\"</td></tr><tr><th>파트</th><td>{_e(tm.get('part_id'))}"
                 f" '{_e(tm.get('part_title'))}'</td></tr><tr><th>노드·요소</th><td>{_e(tm.get('n_nodes'))} · "
                 f"{_e(tm.get('n_elems'))}</td></tr><tr><th>정규화 크기</th><td>L_ξ {_fmt(fr['L_xi'])} × L_η "
                 f"{_fmt(fr['L_eta'])} ({_e(tm.get('units_label') or '모델 단위')})</td></tr></table>")
    else:
        S.append("<p class='muted'>대상 모델 없음 — 정규화 격자 셀 합력·합모멘트로 통계·대표 선택(§8).</p>")
    S.append(f"</div><div class='card'><h3>필터</h3>{chips}<h3>설정</h3><table>"
             f"<tr><th>하중 정규화</th><td>{_e(o['normalization'])}</td></tr>"
             f"<tr><th>격자</th><td>{nx} × {ny}</td></tr>"
             f"<tr><th>SVD 누적 에너지</th><td>{o['svd_energy']}</td></tr>"
             f"<tr><th>대표 수 · 거리 · 시드</th><td>{o['n_representative']} · {_e(o['distance'])} · {o['seed']}</td></tr>"
             f"<tr><th>최악 케이스 포함</th><td>{'예' if o['worst_case'] else '아니오'}</td></tr>"
             f"<tr><th>모멘트 · 평형 보정</th><td>{_e(o['moment_scale'])} · {'예' if o['equilibrate'] else '아니오'}</td></tr>"
             "</table></div></div>")
    # ---- 씬 표
    drops = sorted({str(c.get("drop_class")) for c in cases})
    verdicts = sorted({str(c.get("verdict")) for c in cases})
    clus = sorted({int(c["cluster"]) for c in cases})
    S.append("<h2>2. 씬 표</h2><div class='filters'><input id='f-text' placeholder='검색(모델·씬·항목)'>"
             "<select id='f-drop'><option value=''>낙하 유형 전체</option>"
             + "".join(f"<option>{_e(d)}</option>" for d in drops) + "</select><select id='f-verdict'>"
             "<option value=''>검증 전체</option>" + "".join(f"<option>{_e(v)}</option>" for v in verdicts)
             + "</select><select id='f-cluster'><option value=''>클러스터 전체</option>"
             + "".join(f"<option value='{k}'>C{k + 1}</option>" for k in clus)
             + "</select><span class='muted small' id='f-count'></span></div>")
    cols = ["#", "항목", "제품", "인치", "시나리오", "seq", "유형", "orient", "scene", "검증", "hotspot 오차",
            "Σ|F|", "배율", "클러스터", "역할"]
    rows = []
    roles = {lc["case_index"]: lc["label"] for lc in r["load_cases"]}
    for c in cases:
        role = roles.get(c["index"], "")
        rows.append(
            f"<tr data-drop='{_e(c.get('drop_class'))}' data-verdict='{_e(c.get('verdict'))}' "
            f"data-cluster='{c['cluster']}'><td class='num'>{c['index']}</td><td><code>{_e(c['entry_id'])}</code>"
            f"{' <span class=chip>대상</span>' if c.get('self') else ''}</td><td>{_e(c.get('product'))}</td>"
            f"<td class='num'>{_e(c.get('inch'))}</td><td>{_e(c.get('scenario'))}</td><td class='num'>{_e(c.get('seq'))}</td>"
            f"<td>{_e(c.get('drop_class'))}</td><td>{_e(c.get('orient'))}</td><td class='num'>{_e(c.get('scene'))}</td>"
            f"<td data-v='{_e(c.get('verdict'))}'>{_verdict(c.get('verdict'))}</td>"
            f"<td class='num' data-v='{c.get('hotspot1_rel_err') if c.get('hotspot1_rel_err') is not None else -1}'>"
            f"{_pct(c.get('hotspot1_rel_err'))}</td><td class='num' data-v='{c['sum_abs_f']}'>{_fmt(c['sum_abs_f'])}</td>"
            f"<td class='num'>{_fmt(c['scale_factor'], 3)}</td><td>C{c['cluster'] + 1}</td><td>{_e(role)}</td></tr>")
    S.append("<div class='tablewrap'><table id='scenes' class='sortable'><thead><tr>"
             + "".join(f"<th class='sort'>{_e(h)}</th>" for h in cols) + "</tr></thead><tbody>" + "".join(rows)
             + "</tbody></table></div>")
    # ---- 포락
    env = np.asarray(arrays["env_mag"])
    ec = np.asarray(arrays["env_case"])
    ed = np.asarray(arrays["env_dir"])
    cnt = arrays.get("cell_count")
    tips = [[f"셀 ({i},{j}) ξ≈{(i + 0.5) / nx:.3f} η≈{(j + 0.5) / ny:.3f}\nmax|F| = {_fmt(env[i, j])}\n"
             f"씬 #{int(ec[i, j])} {cases[int(ec[i, j])]['entry_id']} ({_scene_label(cases[int(ec[i, j])])})\n"
             f"방향(ξ,η,n) = ({ed[i, j, 0]:.2f}, {ed[i, j, 1]:.2f}, {ed[i, j, 2]:.2f})"
             + (f"\n대상 노드 {int(cnt[i, j])}" if cnt is not None else "") for j in range(ny)] for i in range(nx)]
    am = r["envelope"]["argmax_cell"]
    S.append("<h2>3. 포락 맵</h2><p class='muted'>셀별 max<sub>k</sub> |F<sub>cell</sub>| (대상 메시 위 매핑·정규화된 "
             "하중의 셀 합력). 화살표 = 최대 케이스의 면내(ξ,η) 방향, 선 = 대상 형상 외곽(정규화 좌표). 셀에 마우스를 "
             "올리면 값·씬·방향.</p><div class='card'>"
             + heatmap(env, fr, outline, tips, "seq", vec=ed[..., :2] * env[..., None], title="셀 포락 max|F|",
                       legend_label="|F| (모델 힘 단위)", highlight=am) + "</div>")
    # ---- 대표 케이스
    sv = r["svd"]
    nm = min(len(sv["cum_energy"]), 30)
    xs = list(range(1, nm + 1))
    S.append("<h2>4. 대표 케이스</h2><div class='grid2'><div class='card'>"
             + line_chart(xs, sv["cum_energy"][:nm], "SVD 누적 에너지", "모드 번호", "누적 에너지",
                          hline=sv["threshold"], vline=sv["n_modes"], bars=sv["energy"][:nm])
             + f"<p class='small muted'>특징 {_e(sv.get('feature'))}({'행 단위 노름' if sv.get('rows') == 'unit' else '원값'}) "
               f"X = U S Vᵀ (중심화 없음). 누적 에너지 ≥ {sv['threshold']:.2f} 인 "
               f"최소 r = {sv['n_modes']} 모드 계수로 k-medoids({_e(o['distance'])}) → 실제 씬을 대표로 선택.</p></div>"
             "<div class='card'><h3>선택된 하중 케이스</h3><table><thead><tr><th>라벨</th><th>역할</th><th>씬</th>"
             "<th>항목</th><th>클러스터 크기</th><th>평균 거리</th></tr></thead><tbody>")
    for lc in r["load_cases"]:
        c = cases[lc["case_index"]]
        cl = r["clusters"][lc["cluster"]]
        S.append(f"<tr><td><b>{_e(lc['label'])}</b></td><td>{'대표(medoid)' if lc['role'] == 'medoid' else '최악'}</td>"
                 f"<td>{_e(_scene_label(c))}</td><td><code>{_e(lc['entry_id'])}</code></td><td class='num'>{cl['size']}"
                 f"</td><td class='num'>{_fmt(cl['mean_dist'], 3)}</td></tr>")
    S.append("</tbody></table></div></div>")
    G = np.asarray(arrays["cell_F_loc"])
    S.append("<div class='grid2'>")
    for lc in r["load_cases"]:
        k = lc["case_index"]
        c = cases[k]
        cl = r["clusters"][lc["cluster"]]
        mem = ", ".join(f"#{m}" for m in cl["members"])
        tips_k = [[f"셀 ({i},{j}) F_loc = ({G[k, i, j, 0]:.3g}, {G[k, i, j, 1]:.3g}, {G[k, i, j, 2]:.3g})"
                   for j in range(ny)] for i in range(nx)]
        S.append(f"<div class='card'><h3>{_e(lc['label'])} — {_e(_scene_label(c))}</h3>"
                 f"<div class='small muted'>{_e(c['entry_id'])} · {_e(c.get('scenario'))} · 검증 {_e(c.get('verdict'))}"
                 f" · Σ|F| {_fmt(c['sum_abs_f'])} · 클러스터 C{lc['cluster'] + 1}: {_e(mem)}</div>"
                 + heatmap(G[k, ..., 2], fr, outline, tips_k, "div", vec=G[k, ..., :2],
                           title="셀 법선 성분 F_n(색) + 면내 F_ξη(화살표)", w=520, legend_label="F_n")
                 + "</div>")
    S.append("</div>")
    # ---- 통계 뷰
    st = r["stats"]
    S.append("<h2>5. 통계 뷰</h2><div class='grid2'>")
    for key, lab in (("drop_class", "씬 유형별 Σ|F|"), ("inch", "인치별 Σ|F|")):
        grp = []
        for v, g in st["groups"].get(key, {}).items():
            grp.append((v, [(cases[i]["sum_abs_f"], cases[i]["cluster"], f"#{i} {_scene_label(cases[i])}: "
                             f"{_fmt(cases[i]['sum_abs_f'])}") for i in g["cases"]]))
        S.append("<div class='card'>" + strip(grp, lab, "Σ|f_i| (절점력 크기 합, 정규화 후)") + "</div>")
    pts = [{"x": p["c1"], "y": p["c2"], "cluster": p["cluster"], "big": cases[p["index"]]["is_medoid"],
            "label": f"C{p['cluster'] + 1}" if cases[p["index"]]["is_medoid"] else "",
            "tip": f"#{p['index']} {_scene_label(cases[p['index']])} (C{p['cluster'] + 1})"} for p in st["svd_scatter"]]
    S.append("<div class='card'>" + scatter(pts, "씬 간 하중 패턴: SVD 계수 산점", "모드 1 계수", "모드 2 계수")
             + "<p class='small muted'>색·모양 = 클러스터, 큰 표시 = 대표(medoid). 같은 패턴은 원점에서 같은 방향에 모인다.</p>"
               "</div>")
    ver = [(lab, [(100 * float(x["hotspot1_rel_err"]), cases[x["index"]]["cluster"],
                   f"#{x['index']} {_scene_label(cases[x['index']])}: {100 * float(x['hotspot1_rel_err']):.2f}%")
                  for x in st["verification"] if x["hotspot1_rel_err"] is not None and str(x["verdict"]) == lab])
           for lab in ("PASS", "FAIL", "None")]
    S.append("<div class='card'>" + (strip(ver, "검증 오차 분포 (hotspot1 ε_eq 상대오차)", "%")
                                     or "<p class='muted'>검증 오차 없음</p>") + "</div>")
    ge = arrays.get("group_env_drop_class")
    if ge is not None and st.get("group_env", {}).get("drop_class"):
        for gi, lab in enumerate(st["group_env"]["drop_class"]):
            S.append("<div class='card'>" + heatmap(np.asarray(ge[gi]), fr, outline, None, "seq",
                                                    title=f"유형 {lab}: 셀 포락 max|F|", w=520, legend_label="|F|")
                     + "</div>")
    S.append("</div>")
    # ---- 최적화 설정
    S.append("<h2>6. 비드 최적화 설정</h2>")
    if opt_summary:
        b = opt_summary.get("bead") or {}
        S.append("<div class='grid2'><div class='card'><table>"
                 f"<tr><th>덱</th><td><code>{_e(opt_summary.get('deck'))}</code> ({_e(opt_summary.get('card_format'))})</td></tr>"
                 f"<tr><th>목적</th><td>{_e(opt_summary.get('objective'))} 컴플라이언스</td></tr>"
                 f"<tr><th>subcase</th><td>{opt_summary.get('n_subcases')}</td></tr>"
                 f"<tr><th>비드 MW·ANG·BH</th><td>{_e(b.get('min_width'))} · {_e(b.get('angle'))}° · {_e(b.get('height'))}"
                 f"</td></tr><tr><th>BUFFZONE·SKIP·BOUNDS</th><td>{_e(b.get('buffzone'))} · {_e(b.get('skip'))} · "
                 f"{_e(b.get('bounds'))}</td></tr><tr><th>설계 / 비설계 요소</th><td>{opt_summary.get('n_design_elems')} / "
                 f"{opt_summary.get('n_nondesign_elems')}</td></tr><tr><th>설계 PSHELL</th><td>"
                 f"{_e(opt_summary.get('design_pids'))}</td></tr><tr><th>3-2-1</th><td>{_e(opt_summary.get('supports'))}"
                 "</td></tr></table></div><div class='card'><h3>subcase</h3><table><thead><tr><th>#</th><th>라벨</th>"
                 "<th>항목</th><th>FORCE 수</th><th>기준값 POS</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{s['subcase']}</td><td>{_e(s['label'])}</td><td><code>{_e(s['entry_id'])}</code></td>"
                           f"<td class='num'>{s['n_force']}</td><td class='num'>{_fmt(s.get('ref'))}</td></tr>"
                           for s in opt_summary.get("subcases") or [])
                 + "</tbody></table><h3>카드 확신도</h3><ul class='small'>"
                 + "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in (opt_summary.get("confidence") or {}).items())
                 + "</ul></div></div>")
    else:
        S.append("<p class='muted'>덱 미생성 — <code>python -m esl.library optdeck</code> 실행 후 보고서를 다시 만들면 "
                 "여기에 요약이 나온다.</p>")
    # ---- 매핑 품질
    if r.get("mapping"):
        m = r["mapping"]
        S.append(f"<p class='small muted'>매핑: 대상 자체 항목 {m['n_self']}개(원본 F_eq), 매핑 {m['n_mapped']}개, 셀(그룹) "
                 f"합력·합모멘트 보존 상대오차 최대 {_fmt(m['conservation_rel_max'], 2)}, 병합 그룹 "
                 f"{m['n_merged_groups_total']}개, 평형 보정량 최대 {_pct(m['equilibrate_correction_rel_max'])}.</p>")
    # ---- 한계
    S.append("<h2>7. 한계</h2><ul class='lim'>"
             "<li><b>선형 ESL</b>: F_eq 는 t* 순간의 강체 제거 변위장을 선형 탄성 쉘로 재현하는 하중이다. 소성·접촉·"
             "대변형 비선형은 반영되지 않으며 소성 영역 응력은 과대평가된다. CUMULATIVE(누적 소성) 씬은 오차가 커질 수 "
             "있으므로 검증 오차로 거른다.</li>"
             "<li><b>매핑 근사</b>: 다른 인치·메시로의 이동은 정규화 좌표(PCA 평면 바운딩) 기하 비례 가정이다. 마운트·보스 "
             "위치가 비례하지 않으면 국부 하중 위치가 어긋난다. 셀 내부 분포는 최소노름 해(셀 합력·합모멘트만 보존)라 "
             "셀보다 작은 하중 집중은 퍼진다.</li>"
             "<li><b>크기 정규화</b>: mass·inch2 는 단순 비례 가정이며 실제 충격 하중의 크기 비와 다를 수 있다.</li>"
             "<li><b>대표 선택</b>: SVD·k-medoids 는 하중 패턴 유사도 기준이며 응답(변형률) 기준이 아니다. 최악 케이스 "
             "옵션으로 보완한다.</li>"
             "<li><b>OptiStruct 덱</b>: DTPG·DOBJREF 등 최적화 카드는 이 환경에서 실행 검증하지 못했다(확신도 표기). "
             "<code>run_optistruct.bat -check</code> 로 먼저 확인.</li></ul>")
    if r.get("warnings"):
        S.append("<h3>경고</h3><ul class='small'>" + "".join(f"<li>{_e(w)}</li>" for w in r["warnings"]) + "</ul>")
    data = {"analysis_id": info.get("analysis_id"), "n_cases": r["n_cases"], "load_cases": r["load_cases"]}
    blob = json.dumps(U.jsonable(data), ensure_ascii=False).replace("</", "<\\/")
    doc = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>ESL 종합분석</title><style>{CSS}</style></head><body><main>" + "".join(S)
           + f"<script type='application/json' id='esl-data'>{blob}</script>"
           + f"<script>{JS}</script></main></body></html>")
    with open(out_html, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    return out_html
