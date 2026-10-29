"""강성 평가 스터디(이전 이름 비드 DOE) 보고서 HTML (계약 esl_bead_doe.md §11 report.html).

``render(ctx) -> str`` / ``write(path, ctx) -> str``. 자체 완결 단일 파일(``esl.report.html`` 공통 CSS·inline SVG,
외부 의존 0). 모든 텍스트 HTML 이스케이프. "방법·출처"·"한계" 절 문구는 ``resources/doe_method_sources.json`` 그대로,
코드 문구는 ``resources/doe_messages.json``.

ctx 키
- study{id, title, scenario, created_at, entry_ids[]}, inputs{step{file_name, sha256}, mesh{files[]}|None, part_title,
  inch, props{t,E,nu}|None, mesh_size_mm|None, entries[{entry_id, label, case}]}, versions{paicad, gmsh}
- params[] (변수 표), spec(정규화), matrix_sha256, n_designs, dropped_duplicates
- preview{counts{ok, collision, fixed, geom}, cells[{id, state, code}]}
- result(rank.rank 결과 + sensitivity), noise_floor
- boundary{warnings[], info[]}|None, plan(DoePlanOut)|None, best{id, values, files[]}|None, sources(method sources)
"""
from __future__ import annotations

from esl.doe import load_messages
from esl.report import html as H

SCN_KO = {"same": "① 같은 모델", "mesh": "② 다른 모델(메시 있음)", "step": "③ 다른 모델(STEP 만)"}
METHOD_KO = {"lhs": "LHS", "halton": "Halton", "fullfact": "풀 팩토리얼"}
STATE_KO = {"READY": "실행 대상", "OK": "성공", "SKIPPED_COLLISION": "충돌 스킵", "SKIPPED_FIXED": "고정 침범 스킵",
            "SKIPPED_GEOM": "형상 실패 스킵", "FAILED_MORPH": "모핑 실패", "FAILED_MESH": "메시 실패",
            "FAILED_SOLVE": "해석 실패", "CANCELED": "취소"}
EXTRA_CSS = """svg.plan{width:100%;height:auto;display:block;border:1px solid var(--border);background:var(--bg)}
svg .ol{stroke:var(--muted);fill:none;stroke-width:1.2}svg .hl{stroke:var(--na);fill:var(--grid);stroke-width:1}
svg .fx{fill:var(--s1)}svg .ap{stroke:var(--s2);stroke-width:2}svg .lp{fill:var(--bad);opacity:.45}
svg .lk{stroke:var(--bad);stroke-width:1.2;stroke-dasharray:4 3}svg .bd{stroke:var(--s4);fill:none;stroke-width:1.2}
svg .bp{fill:var(--s1)}svg .bn{fill:var(--s2)}td.noise{color:var(--muted)}"""
_f = H.fmt


def _msg(code) -> str:
    try:
        return load_messages()["messages"].get(code, code)
    except Exception:                                       # noqa: BLE001 - 보고서는 문구 누락으로 실패하지 않음
        return str(code)


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:+.1f} %"


def sensitivity_svg(sens: dict | None, w: int = 620) -> str:
    if not sens or sens.get("null"):
        return f"<p class='muted'>{H.esc(_msg((sens or {}).get('reason') or 'SENSITIVITY_TOO_FEW'))}</p>"
    ps = sens["params"]
    rh, ox, top = 22, 190, 26
    h = top + rh * len(ps) + 30
    mid, half = ox + (w - ox - 20) / 2, (w - ox - 20) / 2
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="민감도">',
           f'<text class="tl" x="4" y="14">SRC(파랑)·Spearman ρ(주황), 범위 −1..+1 · R² {H.esc(_f(sens.get("r2")))}</text>',
           f'<line class="ax" x1="{mid:.1f}" x2="{mid:.1f}" y1="{top - 4}" y2="{top + rh * len(ps)}"/>']
    for i, p in enumerate(ps):
        y = top + i * rh
        out.append(f'<text x="{ox - 6}" y="{y + 14}" text-anchor="end">{H.esc(p["name"])}</text>')
        for k, (val, cls, dy) in enumerate(((p.get("src"), "bar", 2), (p.get("spearman"), "bar0", 11))):
            if val is None:
                continue
            v = max(-1.0, min(1.0, float(val)))
            x0, x1 = (mid, mid + v * half) if v >= 0 else (mid + v * half, mid)
            out.append(f'<rect class="{"bp" if k == 0 else "bn"}" x="{x0:.1f}" y="{y + dy}" width="{max(x1 - x0, 0.5):.1f}" '
                       f'height="8"><title>{H.esc(p["name"])}: {H.esc(_f(val))}</title></rect>')
    for t in (-1, 0, 1):
        out.append(f'<text x="{mid + t * half:.1f}" y="{h - 10}" text-anchor="middle">{t}</text>')
    out.append("</svg>")
    return "".join(out)


def plan_svg(plan: dict | None, w: int = 620) -> str:
    if not plan or not plan.get("frame"):
        return ""
    ar, br = plan["frame"]["a_range"], plan["frame"]["b_range"]
    La, Lb = max(ar[1] - ar[0], 1e-9), max(br[1] - br[0], 1e-9)
    pad = 12
    h = int(round((w - 2 * pad) * Lb / La)) + 2 * pad
    X = lambda a: pad + (a - ar[0]) / La * (w - 2 * pad)        # noqa: E731
    Y = lambda b: h - pad - (b - br[0]) / Lb * (h - 2 * pad)     # noqa: E731

    def poly(ring, cls):
        if not ring:
            return ""
        pts = " ".join(f"{X(p[0]):.1f},{Y(p[1]):.1f}" for p in ring)
        return f'<polygon class="{cls}" points="{pts}"/>'
    out = [f'<svg class="plan" viewBox="0 0 {w} {h}" role="img" aria-label="경계 매핑 평면도">',
           poly(plan.get("outline"), "ol")]
    out += [poly(r, "hl") for r in plan.get("holes") or []]
    out += [poly(b.get("ring"), "bd") for b in plan.get("beads") or []]
    pos = {}
    for p in plan.get("fixed") or []:
        pos[p["label"]] = (p["a"], p["b"])
        out.append(f'<circle class="fx" cx="{X(p["a"]):.1f}" cy="{Y(p["b"]):.1f}" r="3"><title>{H.esc(p["label"])}'
                   '</title></circle>')
    for p in plan.get("a_points") or []:
        pos[p["label"]] = (p["a"], p["b"])
        x, y = X(p["a"]), Y(p["b"])
        out.append(f'<path class="ap" d="M{x - 4:.1f} {y - 4:.1f}L{x + 4:.1f} {y + 4:.1f}M{x - 4:.1f} {y + 4:.1f}'
                   f'L{x + 4:.1f} {y - 4:.1f}"><title>{H.esc(p["label"])}</title></path>')
    for p in plan.get("load_points") or []:
        r = 3 + 12 * float(p.get("share") or 0)
        out.append(f'<circle class="lp" cx="{X(p["a"]):.1f}" cy="{Y(p["b"]):.1f}" r="{r:.1f}"><title>하중 '
                   f'{H.esc(p["entry_id"])} {H.esc(_f(p.get("share")))}</title></circle>')
    for lk in plan.get("links") or []:
        if not lk.get("warn") or lk.get("from") not in pos or lk.get("to") not in pos:
            continue
        (a0, b0), (a1, b1) = pos[lk["from"]], pos[lk["to"]]
        out.append(f'<line class="lk" x1="{X(a0):.1f}" y1="{Y(b0):.1f}" x2="{X(a1):.1f}" y2="{Y(b1):.1f}"/>')
    out.append("</svg>")
    return "".join(out)


def render(ctx: dict) -> str:
    st = ctx.get("study") or {}
    ip = ctx.get("inputs") or {}
    ver = ctx.get("versions") or {}
    spec = ctx.get("spec") or {}
    res = ctx.get("result") or {}
    pv = ctx.get("preview") or {}
    bd = ctx.get("boundary") or {}
    ms = ctx.get("sources") or {}
    S = [f"<h1>강성 평가 스터디 · {H.esc(SCN_KO.get(st.get('scenario'), st.get('scenario')))} · "
         f"{H.esc(st.get('title') or st.get('id'))}</h1>",
         "<p class='muted small'>(이전 이름: 비드 DOE)</p>",
         f"<p class='muted small'>연구 {H.esc(st.get('id'))} · {H.esc(st.get('created_at'))} · ESL "
         f"{len(st.get('entry_ids') or [])}개</p>"]
    if res.get("ranking"):
        b = res["ranking"][0]
        S.append(H.cards([("최적 안", H.esc(b["id"])), ("score", H.esc(_f(b["score"]))),
                          ("개선율", H.esc(_pct(b["improvement"]))), ("성공 안", H.esc(res.get("n_ok"))),
                          ("경계 경고", H.esc(len(bd.get("warnings") or [])))]))
    # 1. 입력
    pairs = [("시나리오", SCN_KO.get(st.get("scenario"), str(st.get("scenario")))),
             ("STEP", f"{(ip.get('step') or {}).get('file_name')} (sha256 {str((ip.get('step') or {}).get('sha256'))[:12]}…)"),
             ("파트 제목", ip.get("part_title")), ("인치", ip.get("inch")),
             ("paicad 버전", ver.get("paicad")), ("gmsh 버전", ver.get("gmsh"))]
    if ip.get("mesh"):
        pairs.append(("B 메시", ", ".join(f.get("rel", "") for f in ip["mesh"].get("files") or [])))
    if ip.get("props"):
        p = ip["props"]
        pairs.append(("쉘 물성(③)", f"t {_f(p.get('t'))} mm · E {_f(p.get('E'))} MPa · ν {_f(p.get('nu'))}"))
    if ip.get("mesh_size_mm") is not None:
        pairs.append(("요소 크기(③)", f"{_f(ip['mesh_size_mm'])} mm"))
    inner = H.kv_table(pairs)
    ents = ip.get("entries") or []
    if ents:
        inner += "<h3>선택 ESL</h3>" + H.table(["ESL", "이름", "출처 Case"],
                                              [[e.get("entry_id"), e.get("label") or "", e.get("case") or ""]
                                               for e in ents])
    S.append(H.section("inputs", "1. 입력", inner))
    # 2. 변수·DOE
    rows = []
    inc = {p["name"]: p for p in spec.get("params") or []}
    for p in ctx.get("params") or []:
        r = inc.get(p["name"])
        fe = p.get("feasible") or [None, None]
        rows.append([p["name"], p.get("type"), p.get("nominal"), f"{_f(fe[0])}–{_f(fe[1])}",
                     "포함" if r else "—", "" if not r else f"{_f(r['lo'])}–{_f(r['hi'])}"])
    lv = f"수준 {spec.get('levels')}" if spec.get("method") == "fullfact" else f"n {spec.get('n')}"
    inner = H.table(["변수", "종류", "공칭", "feasible(추정)", "DOE", "범위"], rows, num=(2,))
    inner += (f"<p>방식 <b>{H.esc(METHOD_KO.get(spec.get('method'), spec.get('method')))}</b> · {H.esc(lv)} · seed "
              f"{H.esc(spec.get('seed'))} · 안 {H.esc(ctx.get('n_designs'))}개(공칭 d000 포함, 중복 제거 "
              f"{H.esc(ctx.get('dropped_duplicates') or 0)}) · 행렬 sha256 <code>{H.esc(ctx.get('matrix_sha256'))}</code></p>")
    S.append(H.section("doe", "2. 변수·DOE", inner))
    # 3. 미리보기
    c = pv.get("counts") or {}
    sk = [x for x in pv.get("cells") or [] if x.get("state") not in ("READY", "OK")]
    inner = (f"<p>OK {H.esc(c.get('ok', 0))} · 충돌 {H.esc(c.get('collision', 0))} · 고정 침범 "
             f"{H.esc(c.get('fixed', 0))} · 형상 실패 {H.esc(c.get('geom', 0))}</p>")
    if sk:
        inner += H.table(["안", "상태", "코드", "설명"], [[x["id"], STATE_KO.get(x["state"], x["state"]),
                                                       x.get("code") or "", _msg(x["state"])] for x in sk])
    S.append(H.section("preview", "3. 미리보기 스킵", inner))
    # 4. 순위
    rk = res.get("ranking") or []
    top_n = int(ctx.get("ranking_rows") or 20)
    names = [p["name"] for p in spec.get("params") or []]
    if rk:
        hdr = ["순위", "안", "score", "개선율", "최악 ESL", "umax", "εmax"] + names + ["경고"]
        trs = []
        for x in rk[:top_n]:
            imp = H.esc(_pct(x["improvement"])) + (" <span class='muted'>(잡음 이내)</span>" if x.get("noise") else "")
            trs.append([x["rank"], x["id"], x["score"], imp, x.get("worst_entry_id") or "", x["umax"], x["epsmax"]]
                       + [x["values"].get(n) for n in names] + [x.get("warnings_n", 0)])
        inner = H.table(hdr, trs, num=(0, 2, 5, 6) + tuple(range(7, 7 + len(names))), raw=(3,))
        inner += (f"<p class='small muted'>C_ref(베이스라인 최악) {H.esc(_f(res.get('C_ref')))} · 베이스라인 umax "
                  f"{H.esc(_f((res.get('baseline') or {}).get('umax')))} · 전체는 ranking.csv</p>")
        if res.get("noise_floor") is not None:
            inner += f"<p class='small'>③ 메시 잡음 바닥 {H.esc(_pct(res['noise_floor']))}(공칭 BREP 왕복 재메시 score 차)</p>"
    else:
        inner = f"<p>{H.esc(_msg('NO_FEASIBLE_DESIGNS'))}</p>"
    nf = res.get("n_failed") or {}
    ns = res.get("n_skipped") or {}
    inner += (f"<p class='small'>성공 {H.esc(res.get('n_ok', 0))} · 스킵 충돌 {H.esc(ns.get('collision', 0))}·고정 "
              f"{H.esc(ns.get('fixed', 0))}·형상 {H.esc(ns.get('geom', 0))} · 실패 모핑 {H.esc(nf.get('morph', 0))}·메시 "
              f"{H.esc(nf.get('mesh', 0))}·해석 {H.esc(nf.get('solve', 0))}</p>")
    S.append(H.section("ranking", "4. 순위", inner))
    # 5. 민감도
    S.append(H.section("sensitivity", "5. 파라미터 민감도", sensitivity_svg(res.get("sensitivity"))))
    # 6. 경계 경고
    if ctx.get("boundary") is not None:
        items = list(bd.get("warnings") or []) + list(bd.get("info") or [])
        inner = plan_svg(ctx.get("plan"))
        if items:
            inner += H.table(["코드", "대상", "거리 mm", "기준 mm", "설명"],
                             [[w["code"], w.get("label") or w.get("entry_id") or w.get("index") or "",
                               w.get("d_mm"), w.get("limit_mm"), _msg(w["code"])] for w in items], num=(2, 3))
        else:
            inner += "<p>경고 없음</p>"
        S.append(H.section("boundary", "6. 경계 매핑 경고(차단 아님)", inner))
    # 7. 최적 안
    best = ctx.get("best")
    if best:
        inner = H.kv_table([(k, v) for k, v in sorted((best.get("values") or {}).items())])
        inner += "<p class='small'>산출물: " + H.esc(", ".join(best.get("files") or [])) + "</p>"
        S.append(H.section("best", f"7. 최적 안 {best.get('id')}", inner))
    # 8. 방법·출처
    if ms:
        inner = "<ul>" + "".join(f"<li>{H.esc(s)}</li>" for s in ms.get("summary_ko") or []) + "</ul>"
        inner += "<ul>" + "".join(f"<li><b>{H.esc(k)}</b>: {H.esc(v)}</li>" for k, v in (ms.get("methods") or {}).items()) + "</ul>"
        src = []
        for s in ms.get("sources") or []:
            t = H.esc(s["title"])
            if s.get("url"):
                t = f'<a href="{H.esc(s["url"])}" rel="noreferrer">{t}</a>'
            src.append(f"<li>{t}" + (f" — {H.esc(s['authors'])}" if s.get("authors") else "")
                       + (f" <span class='muted'>({H.esc(s['note'])})</span>" if s.get("note") else "") + "</li>")
        inner += "<h3>출처</h3><ol>" + "".join(src) + "</ol>"
        inner += f"<p class='small muted'>자료 버전 {H.esc(ms.get('version'))}</p>"
        S.append(H.section("method", "8. 방법·출처", inner))
        S.append(H.section("limits", "9. 한계", "<ul>" + "".join(f"<li>{H.esc(s)}</li>" for s in ms.get("limits_ko") or [])
                           + "</ul>"))
    title = f"강성 평가 스터디 {st.get('title') or st.get('id') or ''}".strip()
    return H.page(title, "\n".join(S), extra_css=EXTRA_CSS, version="doe")


def write(path: str, ctx: dict) -> str:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(ctx))
    return path
