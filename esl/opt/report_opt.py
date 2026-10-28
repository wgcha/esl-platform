"""비드 최적화 보고서 HTML (계약 esl_opt_run.md §9 report.html, §9.1 방법·출처).

``render(ctx) -> str`` / ``write(path, ctx) -> str``. 자체 완결 단일 파일(CSS·inline SVG, 그림은 inline SVG 또는
data: PNG — 보고서 CSP ``img-src data:``). 모든 텍스트·링크는 HTML 이스케이프. "방법·출처" 절의 문구·링크는
``resources/opt_method_sources.json``(``esl.opt.load_method_sources``) 그대로 — 실행 전략·목표 기준은 굵게.

ctx 키
- run{id, scenario, title, created_at, entry_ids}, selection(LoadSelection), result(OptResult | None)
- target{n_nodes, n_elems, source, identity[] | size{}, normals{}, warnings[]}, keepout{counts, rects, auto, cfg}
- design{bead{angle, min_width, height}, nondesign_pids[]}, deck{desmax, n_design_elems, n_nondesign_elems}
- history[rows] (osout.history), bead_grid{values (nx,ny), frame, outline} (``bead_grid``), keepout_png bytes,
  sources(method sources dict)
"""
from __future__ import annotations

import base64
import html
import math

import numpy as np

from esl.library import report_analysis as ra
from esl.library import normalize as nz

STATUS_KO = {"included": "포함", "merged": "병합됨", "cluster_rep": "군집 대표", "clustered": "군집 멤버",
             "mode_rep": "모드 대표", "not_selected": "미선정"}
STRATEGY_KO = {"A": "A 전부 넣기", "B": "B 모드별 최악", "C": "C 군집 대표 k개"}
NORM_KO = {"abs": "절대", "rel": "상대"}
MODE_KO = {"dent": "덴팅", "twist": "뒤틀림", "bend": "굽힘", None: "—"}
EXTRA_CSS = """
table.sel td.st{white-space:nowrap} tr.picked td{font-weight:600} .chip{display:inline-block;padding:1px 7px;
border:1px solid var(--line);border-radius:10px;font-size:12px;margin-right:4px} .now{font-weight:700}
img.plan{max-width:100%;height:auto;border:1px solid var(--line)} section{margin-bottom:22px}
"""


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


_f = ra._fmt


def bead_grid(mesh: dict, frame: dict, elem_h, design, cells=(96, 54)) -> dict:
    """요소 |h| 면적 가중 평균을 정규화 격자 cells 에 모은 값 (nx, ny) + 외곽 선분(정규화 좌표)."""
    from esl.library.analysis import boundary_outline
    from esl.library.entry import _areas
    from esl.opt.keepout import centroids
    nx, ny = int(cells[0]), int(cells[1])
    X = np.asarray(mesh["x0"], dtype=np.float64)
    A = _areas(X, np.asarray(mesh["conn"]), np.asarray(mesh["elem_type"]))
    loc = nz.local_coords(frame, centroids(mesh))
    i = np.clip(np.floor(loc[:, 0] * nx).astype(int), 0, nx - 1)
    j = np.clip(np.floor(loc[:, 1] * ny).astype(int), 0, ny - 1)
    des = np.asarray(design, dtype=bool)
    w = A * des
    num = np.bincount(i * ny + j, weights=w * np.abs(np.asarray(elem_h, dtype=float)), minlength=nx * ny)
    den = np.bincount(i * ny + j, weights=w, minlength=nx * ny)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.where(den > 0, num / den, 0.0)
    return {"values": v.reshape(nx, ny), "frame": frame,
            "outline": boundary_outline(X, mesh["conn"], mesh["elem_type"], frame)}


def _conv_svg(hist: list, norm: str, w=560, h=260) -> str:
    pts = [(r["iteration"], r["objective"]) for r in hist if r.get("objective") is not None]
    if not pts:
        return "<p class='muted'>수렴 이력 없음</p>"
    ox, oy, pw, ph = 56, 26, w - 76, h - 66
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(max(xs), min(xs) + 1)
    ymax = max(max(ys), 1e-12) * 1.08
    X = lambda v: ox + (v - x0) / (x1 - x0) * pw   # noqa: E731
    Y = lambda v: oy + (1 - v / ymax) * ph          # noqa: E731
    lab = "max C_k / C_ref" if norm == "abs" else "max C_k / C_k⁰"
    out = [f'<text class="ttl" x="{ox}" y="15">수렴 이력 ({_e(lab)})</text>']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        v = t * ymax
        out.append(f'<line class="gl" x1="{ox}" x2="{ox + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text x="{ox - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.2f}</text>')
    out.append(f'<polyline points="{" ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in pts)}" fill="none" '
               f'stroke="var(--c1)" stroke-width="2"/>')
    for a, b in pts:
        out.append(f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="3" fill="var(--c1)"><title>반복 {a}: {b:.4f}</title>'
                   f'</circle>')
    step = max(1, int(math.ceil(len(xs) / 12)))
    for a in xs[::step]:
        out.append(f'<text x="{X(a):.1f}" y="{oy + ph + 15}" text-anchor="middle">{a}</text>')
    out.append(f'<line class="ax" x1="{ox}" x2="{ox + pw}" y1="{oy + ph}" y2="{oy + ph}"/>')
    out.append(f'<text x="{ox + pw / 2:.1f}" y="{h - 8}" text-anchor="middle">반복</text>')
    return ra._svg(w, h, "".join(out), "수렴 이력")


def method_section(sources: dict, strategy: str, objective_norm: str, k=None) -> str:
    S = ["<section id='method'><h2>방법·출처</h2>"]
    S.append("<ul>" + "".join(f"<li>{_e(x)}</li>" for x in sources["summary_ko"]) + "</ul>")
    S.append("<h3>하중 선정 전략</h3><ul>")
    for key in ("A", "B", "C"):
        cur = key == strategy
        extra = f" (이 실행, k = {_e(k)})" if cur and key == "C" and k else (" (이 실행)" if cur else "")
        S.append(f"<li class='{'now' if cur else ''}'>{_e(key)}: {_e(sources['strategies'][key])}{extra}</li>")
    S.append("</ul><h3>목표 기준</h3><ul>")
    for key in ("abs", "rel"):
        cur = key == objective_norm
        S.append(f"<li class='{'now' if cur else ''}'>{_e(NORM_KO[key])}: {_e(sources['objective_norms'][key])}"
                 f"{' (이 실행)' if cur else ''}</li>")
    S.append("</ul><h3>출처</h3><ol class='src'>")
    for s in sources["sources"]:
        t = _e(s["title"])
        if s.get("url"):
            t = f"<a href=\"{_e(s['url'])}\" target=\"_blank\" rel=\"noopener noreferrer\">{t}</a>"
        meta = " · ".join(_e(s[k]) for k in ("authors", "note") if s.get(k))
        S.append(f"<li>{t}{(' — ' + meta) if meta else ''}</li>")
    S.append(f"</ol><p class='small muted'>자료 버전 {_e(sources['version'])}</p></section>")
    return "".join(S)


def selection_table(sel: dict) -> str:
    rows = []
    for r in sel["rows"]:
        st = STATUS_KO.get(r["status"], r["status"])
        if r.get("label"):
            st += f" {r['label']}"
        note = []
        if r.get("merged_into"):
            s = f"→ {r['merged_into']}"
            if r.get("mac_to_target") is not None:
                s += f" (MAC {r['mac_to_target']:.3f}{', 반대 방향' if r.get('sign') == -1 else ''})"
            note.append(s)
        if r.get("cluster"):
            note.append(f"군집 {r['cluster']}")
        if r.get("note"):
            note.append(r["note"])
        rows.append(f"<tr class='{'picked' if r.get('label') else ''}'><td class='st'>{_e(st)}</td>"
                    f"<td>{_e(r.get('scene') or r['entry_id'])}</td><td class='num'>{_f(r['C0'])}</td>"
                    f"<td class='num'>{_f(r.get('pos'))}</td><td class='num'>{_f(r.get('umax'))}</td>"
                    f"<td>{_e(MODE_KO.get(r.get('mode'), r.get('mode')))}</td><td>{_e('; '.join(note))}</td></tr>")
    head = (f"<p>전략 <b>{_e(STRATEGY_KO[sel['strategy']])}</b>"
            + (f" (k = {_e(sel['k'])})" if sel.get("k") else "")
            + f" · 목표 <b>{_e(NORM_KO[sel['objective_norm']])}</b> (C_ref {_f(sel['C_ref'])}) · ESL {sel['n_selected_esl']} → "
            f"케이스 {sel['n_cases']}"
            + (f" · 제외 모드 {_e(', '.join(MODE_KO[m] for m in sel['excluded_modes']))}" if sel.get("excluded_modes") else "")
            + "</p>")
    return (head + "<table class='sel'><thead><tr><th>상태</th><th>씬</th><th>C⁰</th><th>POS</th><th>umax</th><th>모드</th>"
            "<th>비고</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def render(ctx: dict) -> str:
    run = ctx.get("run") or {}
    sel = ctx["selection"]
    res = ctx.get("result")
    tg = ctx.get("target") or {}
    ko = ctx.get("keepout") or {}
    de = ctx.get("design") or {}
    dk = ctx.get("deck") or {}
    S = [f"<h1>비드 최적화 · {_e(run.get('scenario'))} · {_e(run.get('title') or run.get('id'))}</h1>",
         f"<p class='muted small'>실행 {_e(run.get('id'))} · {_e(run.get('created_at'))} · 입력 ESL "
         f"{len(run.get('entry_ids') or [])}개</p>"]
    S.append("<section><h2>1. 하중 선정</h2>" + selection_table(sel) + "</section>")
    S.append("<section><h2>2. 대상</h2><ul>")
    S.append(f"<li>노드 {_e(tg.get('n_nodes'))} · 요소 {_e(tg.get('n_elems'))}</li>")
    src = tg.get("source") or {}
    if src.get("rad"):
        S.append(f"<li>기준 Case 입력 rad: {_e(src['rad'].get('path'))} (sha256 {_e(str(src['rad'].get('sha256'))[:12])}…), "
                 f"파트 {_e(src.get('part_title'))}</li>")
    if src.get("template_id") or src.get("file_name"):
        S.append(f"<li>템플릿 {_e(src.get('template_id'))} {_e(src.get('file_name'))}</li>")
    for r in tg.get("identity") or []:
        S.append(f"<li>{_e(r['entry_id'])}: {'같은 모델' if r['same_model'] else '다른 모델 ' + _e(r.get('reason'))}</li>")
    if tg.get("size"):
        sz = tg["size"]
        S.append(f"<li>크기 검사: {'통과' if sz.get('ok', True) else '불일치'} {_e('; '.join(sz.get('warnings') or []))}</li>")
    nm = tg.get("normals") or {}
    if nm.get("normals_flipped"):
        S.append(f"<li>법선 정렬(템플릿): {nm['normals_flipped']}개 요소 연결 순서 뒤집음</li>")
    if nm.get("normals_opposite"):
        S.append(f"<li>법선 반대 요소 {nm['normals_opposite']}개 — 원 연결 유지(경고)</li>")
    for w in tg.get("warnings") or []:
        S.append(f"<li class='muted'>{_e(w)}</li>")
    S.append("</ul></section>")
    c = ko.get("counts") or {}
    S.append("<section><h2>3. 비드 금지 영역</h2>")
    cfg = ko.get("cfg") or {}
    auto = ko.get("auto") or {}
    S.append(f"<p>자동: 구멍 주변 {_e(cfg.get('hole_radius_mm'))} mm {'켬' if auto.get('hole', True) else '끔'} "
             f"(요소 {c.get('n_elems_auto_hole', 0)}) · 가장자리 {_e(cfg.get('edge_band_mm'))} mm "
             f"{'켬' if auto.get('edge', True) else '끔'} (요소 {c.get('n_elems_auto_edge', 0)}) · 사각형 "
             f"{len(ko.get('rects') or [])}개 (요소 {c.get('n_elems_rects', 0)})</p>")
    if ko.get("rects"):
        S.append("<table><thead><tr><th>이름</th><th>기준 모서리</th><th>X</th><th>Y</th><th>가로</th><th>세로</th></tr>"
                 "</thead><tbody>" + "".join(
                     f"<tr><td>{_e(r['name'])}</td><td>{_e(r['corner'])}</td><td class='num'>{_f(r['x_mm'])}</td>"
                     f"<td class='num'>{_f(r['y_mm'])}</td><td class='num'>{_f(r['w_mm'])}</td>"
                     f"<td class='num'>{_f(r['h_mm'])}</td></tr>" for r in ko["rects"]) + "</tbody></table>")
    if ctx.get("keepout_png"):
        S.append("<img class='plan' alt='금지 영역 평면도' src='data:image/png;base64,"
                 + base64.b64encode(ctx["keepout_png"]).decode("ascii") + "'>")
    S.append("</section>")
    b = de.get("bead") or {}
    S.append(f"<section><h2>4. 덱 설정</h2><p>비드 경사 {_f(b.get('angle'))}° · 최소 폭 {_f(b.get('min_width'))} mm · "
             f"높이 {_f(b.get('height'))} mm · BOUNDS 0~1 · 방향 = 요소 법선(+n) · DESMAX {_e(dk.get('desmax'))} · "
             f"설계 요소 {_e(dk.get('n_design_elems'))} / 비설계 {_e(dk.get('n_nondesign_elems'))}"
             + (f" · 비설계 PID {_e(de.get('nondesign_pids'))}" if de.get("nondesign_pids") else "") + "</p></section>")
    S.append("<section><h2>5. 결과</h2>")
    if res:
        ob = res.get("objective") or {}
        S.append(f"<p>{'수렴' if res.get('converged') else '미수렴'} · 반복 {_e(res.get('iterations'))}/{_e(res.get('desmax'))}"
                 f" · 목적 {_f(ob.get('initial'))} → {_f(ob.get('final'))} · 비드 최대 높이 "
                 f"{_f((res.get('bead') or {}).get('height_max'))} mm · 비드 면적 "
                 f"{ra._pct((res.get('bead') or {}).get('area_frac'))}</p>")
        S.append(_conv_svg(ctx.get("history") or [], sel["objective_norm"]))
        S.append("<table><thead><tr><th>케이스</th><th>ESL</th><th>C⁰ 자체</th><th>C⁰ OS</th><th>C 최종</th><th>비율</th>"
                 "</tr></thead><tbody>" + "".join(
                     f"<tr><td>{_e(s['label'])}</td><td>{_e(s['entry_id'])}</td><td class='num'>{_f(s['C0_self'])}</td>"
                     f"<td class='num'>{_f(s.get('C0_os'))}</td><td class='num'>{_f(s.get('C_final'))}</td>"
                     f"<td class='num'>{_f(s.get('ratio'))}</td></tr>" for s in res.get("subcases") or [])
                 + "</tbody></table>")
        if ctx.get("bead_grid"):
            g = ctx["bead_grid"]
            S.append(ra.heatmap(g["values"], g["frame"], g.get("outline"), title="비드 높이 |h| (설계 요소 평균)",
                                legend_label="mm"))
        if res.get("warnings"):
            S.append("<h3>경고</h3><ul class='small'>" + "".join(f"<li>{_e(w)}</li>" for w in res["warnings"]) + "</ul>")
    else:
        S.append("<p class='muted'>아직 결과 없음</p>")
    S.append("</section>")
    S.append(method_section(ctx["sources"], sel["strategy"], sel["objective_norm"], sel.get("k")))
    S.append("<section><h2>한계</h2><ul class='lim'><li>선형 ESL(t* 한 시점) — 소성·접촉 비선형 미반영.</li>"
             "<li>초기 컴플라이언스는 자체 쉘 솔버 값, 결과 표시는 OptiStruct 값 기준(요소 정식화 차이).</li>"
             "<li>S2 셀 매핑은 정규화 좌표 기하 비례 가정(셀보다 작은 하중 집중은 퍼짐).</li>"
             "<li>비드 반영 메시는 검증 낙하 해석으로 확인 필요(새 Case → 라이브러리 등록 → 버전 비교).</li></ul></section>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>ESL 비드 최적화</title><style>{ra.CSS}{EXTRA_CSS}</style></head><body><main>" + "".join(S)
            + "</main></body></html>")


def write(path: str, ctx: dict) -> str:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(ctx))
    return path
