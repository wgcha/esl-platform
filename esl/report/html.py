"""자체 완결 HTML 보고서 공통 헬퍼 (계약 esl_p2_library.md §5).

- 외부 의존 0: CSS·그림(inline SVG)·데이터(inline JSON)·소량 JS 를 한 파일에 넣는다. CDN·외부 URL·폰트 링크 없음.
- 템플릿 엔진 없이 ``string.Template`` + 고정 레시피. 모든 텍스트는 ``esc`` 로 이스케이프.
- 라이트/다크: CSS 변수(``:root``) + ``prefers-color-scheme`` + ``data-theme`` 수동 전환.
- SVG 색은 클래스(``.s1``…)로만 지정(프레젠테이션 속성에 var() 를 쓰지 않음).
"""
from __future__ import annotations

import html as _html
import json
import math
from string import Template
from typing import Any, Iterable, Sequence

import numpy as np

CSS = """
:root{--bg:#ffffff;--fg:#1c2230;--muted:#5d6676;--card:#f5f6f8;--border:#d8dce2;--accent:#2563c9;
--ok:#18794e;--ok-bg:#e3f4ea;--bad:#b42318;--bad-bg:#fde8e6;--na:#9aa1ab;--grid:#e4e7eb;
--s1:#2563c9;--s2:#d9480f;--s3:#7a8291;--s4:#0f9d8a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#13161b;--fg:#e4e7ec;--muted:#9aa3b2;
--card:#1c2027;--border:#343a45;--accent:#6ea2ff;--ok:#5ad19a;--ok-bg:#16352a;--bad:#ff8a7e;--bad-bg:#3d1c19;
--na:#6b7280;--grid:#2a2f38;--s1:#6ea2ff;--s2:#ff9a5c;--s3:#a3abb8;--s4:#3fd2bd;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#13161b;--fg:#e4e7ec;--muted:#9aa3b2;--card:#1c2027;--border:#343a45;
--accent:#6ea2ff;--ok:#5ad19a;--ok-bg:#16352a;--bad:#ff8a7e;--bad-bg:#3d1c19;--na:#6b7280;--grid:#2a2f38;
--s1:#6ea2ff;--s2:#ff9a5c;--s3:#a3abb8;--s4:#3fd2bd;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",
"Malgun Gothic","Apple SD Gothic Neo",sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px 16px 48px}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:17px;margin:0 0 10px}h3{font-size:14px;margin:14px 0 6px}
p{margin:6px 0}.muted{color:var(--muted)}.small{font-size:12px}
section{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin:14px 0}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin:8px 0}
nav.toc a{color:var(--accent);text-decoration:none}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--border);padding:4px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.num,th.num{text-align:right;white-space:nowrap}
.tw{overflow-x:auto}
.badge{display:inline-block;padding:1px 10px;border-radius:999px;font-weight:700;font-size:13px}
.pass{color:var(--ok);background:var(--ok-bg)}.fail{color:var(--bad);background:var(--bad-bg)}
.na{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:8px 0}
.card{border:1px solid var(--border);border-radius:6px;padding:8px 10px;background:var(--bg)}
.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
svg.chart{width:100%;height:auto;display:block;font-size:11px}
svg .ax{stroke:var(--muted);stroke-width:1;fill:none}svg .gr{stroke:var(--grid);stroke-width:1}
svg text{fill:var(--muted)}svg .tl{fill:var(--fg)}
svg .s1{stroke:var(--s1);fill:none;stroke-width:1.8}svg .s2{stroke:var(--s2);fill:none;stroke-width:1.8}
svg .s3{stroke:var(--s3);fill:none;stroke-width:1.4;stroke-dasharray:4 3}svg .s4{stroke:var(--s4);fill:none;stroke-width:1.8}
svg .sr{stroke:var(--s1);fill:none;stroke-width:4;opacity:.75}svg .se{stroke:var(--s2);fill:none;stroke-width:1.6}
svg .vl{stroke:var(--bad);stroke-width:1.2;stroke-dasharray:3 3}svg .mk{fill:var(--s2)}svg .mk1{fill:var(--bad)}
svg .bar{fill:var(--s1)}svg .bar0{fill:var(--s4)}svg .crit{stroke:var(--bad);stroke-width:1.2;stroke-dasharray:4 3}
.ctrl{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;margin:6px 0 8px;font-size:13px}
.ctrl label{white-space:nowrap}.ctrl input[type=range]{width:180px}
button.tg{font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--border);background:var(--bg);
color:var(--fg);border-radius:4px;cursor:pointer}
.note{border-left:3px solid var(--accent);padding:6px 10px;margin:8px 0;background:var(--bg)}
.warn{border-left-color:var(--bad)}
code{font-size:12px;word-break:break-all}
"""

THEME_JS = """(function(){var r=document.documentElement,b=document.getElementById('theme-btn');if(!b)return;
var m=['auto','light','dark'],i=0;b.onclick=function(){i=(i+1)%3;if(m[i]==='auto')r.removeAttribute('data-theme');
else r.setAttribute('data-theme',m[i]);b.textContent='테마: '+({auto:'자동',light:'라이트',dark:'다크'})[m[i]];
window.dispatchEvent(new Event('esl-theme'));};})();"""

PAGE = Template("""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="esl $version">
<title>$title</title>
<style>$css</style>
</head>
<body>
<main>
$body
</main>
$data
<script>$script</script>
</body>
</html>
""")


def esc(s: Any) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def _finite(v) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def fmt(v: Any, digits: int = 4) -> str:
    """숫자 표시: None → —, 비유한 → ∞/—, 정수 그대로, 실수 유효숫자 digits."""
    if v is None:
        return "—"
    if isinstance(v, (bool, np.bool_)):
        return "예" if v else "아니오"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    try:
        f = float(v)
    except (TypeError, ValueError):
        return esc(v)
    if math.isnan(f):
        return "—"
    if math.isinf(f):
        return "∞" if f > 0 else "−∞"
    if f == 0:
        return "0"
    a = abs(f)
    if 1e-3 <= a < 1e6:
        s = f"{f:.{digits}g}"
    else:
        s = f"{f:.{max(digits - 1, 1)}e}"
    return s.replace("-", "−")


def pct(v: Any, digits: int = 3) -> str:
    return "—" if v is None or not _finite(v) else f"{fmt(v, digits)}%"


def round_sig(a, sig: int = 4) -> list:
    """배열 → 유효숫자 sig 자리 float 목록(JSON 크기 축소). 비유한은 None."""
    a = np.asarray(a, dtype=np.float64).ravel()
    out = []
    for v in a.tolist():
        if not math.isfinite(v):
            out.append(None)
        elif v == 0:
            out.append(0)
        else:
            out.append(float(f"{v:.{sig}g}"))
    return out


def round_fixed(a, step: float) -> list:
    """좌표 → step 단위 반올림(소수 자릿수 고정)."""
    a = np.asarray(a, dtype=np.float64).ravel()
    nd = max(0, int(-math.floor(math.log10(step)))) if step > 0 else 3
    return [round(v, nd) if math.isfinite(v) else None for v in a.tolist()]


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    return o


def json_script(id_: str, obj: Any) -> str:
    """``<script type="application/json">`` (``</`` 이스케이프 → 문서 밖으로 새지 않음)."""
    txt = json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    txt = txt.replace("</", "<\\/").replace("<!--", "<\\!--")
    return f'<script type="application/json" id="{esc(id_)}">{txt}</script>'


def page(title: str, body: str, script: str = "", data: dict | None = None, version: str = "",
         extra_css: str = "") -> str:
    return PAGE.substitute(title=esc(title), css=CSS + extra_css, body=body, version=esc(version),
                           data=json_script("esl-data", data) if data is not None else "",
                           script=THEME_JS + "\n" + script)


def section(id_: str, title: str, inner: str) -> str:
    return f'<section id="{esc(id_)}"><h2>{esc(title)}</h2>\n{inner}\n</section>'


def badge(verdict: str | None) -> str:
    if verdict == "PASS":
        return '<span class="badge pass">PASS</span>'
    if verdict == "FAIL":
        return '<span class="badge fail">FAIL</span>'
    return f'<span class="badge na">{esc(verdict or "N/A")}</span>'


def pass_cell(p) -> str:
    if p is None:
        return '<span class="na">—</span>'
    return '<span class="badge pass">통과</span>' if p else '<span class="badge fail">초과</span>'


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], num: Sequence[int] = (),
          raw: Sequence[int] = ()) -> str:
    """표. num = 오른쪽 정렬 열, raw = 이스케이프·포맷 없이 넣을 열(이미 HTML)."""
    num, raw = set(num), set(raw)
    h = "".join(f'<th class="num">{esc(x)}</th>' if i in num else f"<th>{esc(x)}</th>" for i, x in enumerate(headers))
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            txt = v if i in raw else (fmt(v) if not isinstance(v, str) else esc(v))
            cells.append(f'<td class="num">{txt}</td>' if i in num else f"<td>{txt}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def kv_table(pairs: Iterable[tuple[str, Any]]) -> str:
    rows = []
    for k, v in pairs:
        val = v if isinstance(v, Raw) else (esc(v) if isinstance(v, str) else fmt(v))
        rows.append(f"<tr><th>{esc(k)}</th><td>{val}</td></tr>")
    return f'<div class="tw"><table><tbody>{"".join(rows)}</tbody></table></div>'


class Raw(str):
    """kv_table 에서 이스케이프하지 않을 HTML 조각."""


def cards(items: Iterable[tuple[str, str]]) -> str:
    return '<div class="cards">' + "".join(
        f'<div class="card"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in items) + "</div>"


# ====================================================================== SVG 차트
def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not (_finite(lo) and _finite(hi)):
        return []
    if hi <= lo:
        hi = lo + (abs(lo) if lo else 1.0)
    raw = (hi - lo) / max(n, 1)
    p = 10.0 ** math.floor(math.log10(raw))
    step = next(m * p for m in (1, 2, 2.5, 5, 10) if m * p >= raw)
    t0 = math.ceil(lo / step - 1e-9) * step
    out = []
    t = t0
    while t <= hi + step * 1e-9:
        out.append(0.0 if abs(t) < step * 1e-9 else t)
        t += step
    return out


def _tick_label(v: float) -> str:
    return fmt(v, 3)


def line_chart(series: Sequence[dict], width: int = 520, height: int = 260, xlabel: str = "", ylabel: str = "",
               vlines: Sequence[tuple[float, str]] = (), markers: Sequence[dict] = (), title: str = "") -> str:
    """정적 SVG 꺾은선. series = [{x, y, cls('s1'..), label}], markers = [{x, y, label, cls}]."""
    xs = [v for s in series for v in s["x"] if _finite(v)]
    ys = [v for s in series for v in s["y"] if _finite(v)] + [m["y"] for m in markers if _finite(m.get("y"))]
    if not xs or not ys:
        return '<p class="muted">자료 없음</p>'
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(0.0, min(ys)), max(ys)
    if y1 <= y0:
        y1 = y0 + 1.0
    yt = nice_ticks(y0, y1)
    y1 = max(y1, yt[-1]) if yt else y1
    xt = nice_ticks(x0, x1)
    L, R, T, B = 62, 12, 22 if title else 10, 38
    pw, ph = width - L - R, height - T - B
    X = lambda v: L + (v - x0) / ((x1 - x0) or 1.0) * pw
    Y = lambda v: T + ph - (v - y0) / ((y1 - y0) or 1.0) * ph
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title or ylabel)}">']
    if title:
        out.append(f'<text class="tl" x="{L}" y="14">{esc(title)}</text>')
    for t in yt:
        out.append(f'<line class="gr" x1="{L}" x2="{L + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text x="{L - 4}" y="{Y(t) + 4:.1f}" text-anchor="end">{_tick_label(t)}</text>')
    for t in xt:
        if x0 - 1e-12 <= t <= x1 + 1e-12:
            out.append(f'<text x="{X(t):.1f}" y="{T + ph + 14}" text-anchor="middle">{_tick_label(t)}</text>')
    out.append(f'<path class="ax" d="M{L},{T}V{T + ph}H{L + pw}"/>')
    for v, lab in vlines:
        if _finite(v):
            out.append(f'<line class="vl" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + ph}"/>'
                       f'<text x="{X(v) + 3:.1f}" y="{T + 10}">{esc(lab)}</text>')
    for s in series:
        pts = [(X(a), Y(b)) for a, b in zip(s["x"], s["y"]) if _finite(a) and _finite(b)]
        if pts:
            d = "M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in pts)
            out.append(f'<path class="{esc(s.get("cls", "s1"))}" d="{d}"><title>{esc(s.get("label", ""))}</title></path>')
    for m in markers:
        if _finite(m.get("x")) and _finite(m.get("y")):
            out.append(f'<circle class="{esc(m.get("cls", "mk"))}" cx="{X(m["x"]):.1f}" cy="{Y(m["y"]):.1f}" r="3.5">'
                       f'<title>{esc(m.get("label", ""))}</title></circle>')
    out.append(f'<text x="{L + pw / 2:.0f}" y="{height - 6}" text-anchor="middle">{esc(xlabel)}</text>')
    out.append(f'<text x="12" y="{T + ph / 2:.0f}" text-anchor="middle" transform="rotate(-90 12 {T + ph / 2:.0f})">'
               f'{esc(ylabel)}</text>')
    out.append("</svg>")
    return "".join(out)


def histogram_svg(edges: Sequence[float], counts: Sequence[int], width: int = 560, height: int = 240,
                  xlabel: str = "", crit: Sequence[float] = ()) -> str:
    """정적 SVG 막대 히스토그램. crit = 기준선 x 값(예: ±p90 기준)."""
    if not edges or not counts:
        return '<p class="muted">자료 없음</p>'
    x0, x1 = float(edges[0]), float(edges[-1])
    cmax = max(max(counts), 1)
    yt = nice_ticks(0, cmax)
    ymax = max(cmax, yt[-1] if yt else cmax)
    L, R, T, B = 52, 12, 10, 38
    pw, ph = width - L - R, height - T - B
    X = lambda v: L + (v - x0) / ((x1 - x0) or 1.0) * pw
    Y = lambda v: T + ph - v / ymax * ph
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(xlabel)}">']
    for t in yt:
        out.append(f'<line class="gr" x1="{L}" x2="{L + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text x="{L - 4}" y="{Y(t) + 4:.1f}" text-anchor="end">{int(t)}</text>')
    for i, c in enumerate(counts):
        a, b = X(edges[i]), X(edges[i + 1])
        cls = "bar0" if edges[i] <= 0 <= edges[i + 1] else "bar"
        out.append(f'<rect class="{cls}" x="{a + 0.5:.1f}" y="{Y(c):.1f}" width="{max(b - a - 1, 0.5):.1f}" '
                   f'height="{T + ph - Y(c):.1f}"><title>[{fmt(edges[i], 3)}, {fmt(edges[i + 1], 3)}): {int(c)}</title></rect>')
    for t in nice_ticks(x0, x1, 8):
        out.append(f'<text x="{X(t):.1f}" y="{T + ph + 14}" text-anchor="middle">{_tick_label(t)}</text>')
    for v in crit:
        if x0 <= v <= x1:
            out.append(f'<line class="crit" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{T + ph}"/>')
    out.append(f'<path class="ax" d="M{L},{T}V{T + ph}H{L + pw}"/>')
    out.append(f'<text x="{L + pw / 2:.0f}" y="{height - 6}" text-anchor="middle">{esc(xlabel)}</text>')
    out.append("</svg>")
    return "".join(out)
