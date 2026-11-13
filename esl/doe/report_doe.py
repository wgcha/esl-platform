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

SCN_KO = {"same": "① 같은 모델", "mesh": "② 다른 모델(메시 있음)", "step": "③ 다른 모델(STEP 만)", "compare": "④ 형상 직접 비교",
          "select": "① 같은 모델 · 비드 직접 선택"}
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


METRIC_DEFS = [
    ("전 씬 개선", "모든 ESL 에서 베이스라인 대비 컴플라이언스가 줄었는가(최악 비율 < 1 − 허용치)"),
    ("최소 개선율", "1 − max_i(C_안,i / C_베이스라인,i) — 가장 덜 개선된(또는 가장 악화된) 씬의 개선율"),
    ("개선/악화 씬", "비율 < 1 − 허용치 = 개선, > 1 + 허용치 = 악화, 그 사이 = 변화 없음"),
    ("기하평균 개선율", "1 − (Π_i C_안,i / C_베이스라인,i)^(1/n)"),
    ("Pareto", "베이스라인·다른 안 어느 것에도 모든 ESL 에서 지배당하지 않음(지배 = 모든 ESL 비율 ≤, 하나 이상 <)"),
]


def _ratio_cell(r) -> str:
    """ESL별 개선율 % 셀(개선 초록·악화 빨강, 세기 = |1 − r| 최대 50 %)."""
    if r is None:
        return "–"
    imp = 1.0 - float(r)
    a = min(abs(imp) / 0.5, 1.0) * 0.55 + 0.08
    col = f"rgba(22,163,74,{a:.2f})" if imp > 0 else f"rgba(220,38,38,{a:.2f})" if imp < 0 else "transparent"
    return f"<span style='display:inline-block;min-width:4.5em;padding:0 4px;background:{col}'>{H.esc(_pct(imp))}</span>"


def per_esl_html(rk: list, esl: list, top_n: int) -> str:
    """ESL별 개선율 히트맵(행 = 상위 안, 열 = ESL)."""
    if not rk or not esl or not rk[0].get("per_esl"):
        return ""
    hdr = ["안"] + [e.get("label") or e["entry_id"][:8] for e in esl]
    trs = []
    for x in rk[:top_n]:
        rr = {p["entry_id"]: p.get("ratio") for p in x.get("per_esl") or []}
        trs.append([x["id"]] + [_ratio_cell(rr.get(e["entry_id"])) for e in esl])
    return ("<h3>ESL별 개선율(베이스라인 같은 ESL 대비)</h3>"
            + H.table(hdr, trs, num=tuple(range(1, len(hdr))), raw=tuple(range(1, len(hdr)))))


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


SHAPE_STATE_KO = {"READY": "실행 대상", "OK": "성공", "FAILED_MESH": "메시 실패", "FAILED_SIZE": "크기·정렬 불일치",
                  "FAILED_SOLVE": "해석 실패", "CANCELED": "취소"}


def _methods_limits(ms: dict, extra_limits: list | None = None) -> list[str]:
    if not ms:
        return []
    inner = "<ul>" + "".join(f"<li>{H.esc(s)}</li>" for s in ms.get("summary_ko") or []) + "</ul>"
    src = []
    for s in ms.get("sources") or []:
        t = H.esc(s["title"])
        if s.get("url"):
            t = f'<a href="{H.esc(s["url"])}" rel="noreferrer">{t}</a>'
        src.append(f"<li>{t}" + (f" — {H.esc(s['authors'])}" if s.get("authors") else "")
                   + (f" <span class='muted'>({H.esc(s['note'])})</span>" if s.get("note") else "") + "</li>")
    inner += "<h3>출처</h3><ol>" + "".join(src) + "</ol>"
    inner += f"<p class='small muted'>자료 버전 {H.esc(ms.get('version'))}</p>"
    lim = list(extra_limits or []) + list(ms.get("limits_ko") or [])
    return [H.section("method", "방법·출처", inner),
            H.section("limits", "한계", "<ul>" + "".join(f"<li>{H.esc(s)}</li>" for s in lim) + "</ul>")]


SOURCE_KO = {"step": "STEP", "mesh": "메시", "case": "Case"}
METHOD_LABEL = {"cad": "CAD", "refine": "세분화", "remesh": "재메시", "fallback": "재메시(폴백)", "mesh_input": "메시 입력",
                "defeature": "형상 단순화"}
KIND_KO = {"hole": "구멍", "slot": "슬롯", "flange": "버링", "bead": "딤플·비드", "fillet": "필렛", "narrow": "좁은 띠"}


def defeature_html(shapes: list, lists: dict, top: int = 20) -> str:
    """v0.16.1 '작은 형상 억제' 절(§5A.5): 형상별 종류별 개수·억제 영역 최대 편차·바깥 Hausdorff + 목록 상위 top 행."""
    rows = [s for s in shapes if s.get("mesh_method") == "defeature"]
    if not rows:
        return ""
    out = ["<h3>작은 형상 억제</h3><p class='small'>CAD 메시가 실패한 형상만 작은 형상을 억제한 뒤 메시했습니다(원 STEP 대비 "
           "편차는 억제 영역과 그 밖을 따로 셈).</p>"]
    trs = []
    for s in rows:
        ds = s.get("defeature") or {}
        trs.append([s["id"], s.get("name") or "", ds.get("n"),
                    " · ".join(f"{KIND_KO.get(k, k)} {v}" for k, v in (ds.get("counts") or {}).items()),
                    ds.get("skipped_n"), _f(ds.get("suppressed_max_mm")), _f(ds.get("outside_hausdorff_mm"))])
    out.append(H.table(["id", "이름", "억제 수", "종류별", "건너뜀", "억제 영역 최대 편차 mm", "그 밖 Hausdorff mm"], trs,
                       num=(2, 4, 5, 6)))
    for s in rows:
        doc = (lists or {}).get(s["id"]) or {}
        fs = (doc.get("features") or [])[:top]
        if not fs:
            continue
        out.append(f"<p class='small'>{H.esc(s['id'])} 억제 목록(상위 {len(fs)} / {doc.get('n', len(fs))})</p>")
        out.append(H.table(["종류", "중심 x, y, z mm", "크기", "처리", "편차 mm"],
                           [[KIND_KO.get(f["kind"], f["kind"]), ", ".join(_f(v) for v in f.get("center") or []),
                             ", ".join(f"{k} {_f(v)}" for k, v in (f.get("size") or {}).items()),
                             f"{f.get('action')} {f.get('method') or ''}".strip() + (f" ({f['reason']})" if f.get("reason") else ""),
                             _f(f.get("dev_mm"))] for f in fs]))
    return "".join(out)
MESH_HEAD_CODES = ("COMPARE_MESH_METHOD_MIXED", "REMESH_USED", "REMESH_FIDELITY_WARN", "MESH_INPUT_SIZE_DIFF",
                   "MESH_INPUT_DISCONNECTED", "MESH_REFINED", "MESH_REFINE_BIAS")


def method_label(s: dict) -> str:
    """'메시 방식' 짧은 표기(§8): 세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.4) / 세분화(전역 2.4 mm · 요소 ×1.6)."""
    m = s.get("mesh_method")
    if not m:
        return ""
    rf = s.get("refine") or {}
    if m == "refine" and rf:
        r = rf.get("elem_ratio_ref") or rf.get("elem_ratio_h")
        tail = f" · 요소 ×{float(r):.2f}" if r else ""
        if rf.get("kind") == "local":
            return (f"세분화(국부 ×{_f(rf.get('factor'))} · {_f(rf.get('h_mm'))} mm · 면 {len(rf.get('faces') or [])}"
                    f"{tail})")
        return f"세분화(전역 {_f(rf.get('h_mm'))} mm{tail})"
    return METHOD_LABEL.get(m, m)


def mesh_detail_html(shapes: list) -> str:
    """메시 방식 상세 표(§9): 출처·방식·파트 ID·충실도(Hausdorff·면적비, 원 CAD 대비 ≤ +편차)·요소 크기 중앙값·h·배율·세분화 면·
    요소 배수. CAD 만 쓴 정상 비교(모두 cad·step)면 표를 생략."""
    if all((s.get("mesh_method") in (None, "cad")) and (s.get("source") or "step") == "step" for s in shapes):
        return ""
    trs = []
    for s in shapes:
        fd = s.get("fidelity") or {}
        rf = s.get("refine") or {}
        fid = ""
        if fd.get("hausdorff_mm") is not None:
            fid = (f"{float(fd['hausdorff_mm']):.3f} mm · 면적비 {float(fd.get('area_ratio') or 0):.3f} "
                   f"(원 CAD 대비 ≤ {float(fd['hausdorff_mm']) + float(fd.get('deflection_mm') or 0):.3f} mm)")
        r = rf.get("elem_ratio_ref") or rf.get("elem_ratio_h")
        trs.append([s["id"], s.get("name") or "", SOURCE_KO.get(s.get("source") or "step", s.get("source") or ""),
                    method_label(s), "" if s.get("part_id") is None else s.get("part_id"), fid,
                    "" if s.get("edge_median_mm") is None else _f(s.get("edge_median_mm")),
                    "" if not rf else _f(rf.get("h_mm")), "" if not rf or rf.get("factor") is None else _f(rf.get("factor")),
                    "" if not rf or rf.get("kind") != "local" else len(rf.get("faces") or []),
                    "" if not r else f"×{float(r):.2f}",
                    "" if not s.get("cad_error") else f"{s['cad_error'].get('code')}: {s['cad_error'].get('message') or ''}"])
    return ("<h3>메시 방식</h3>" + H.table(["id", "이름", "출처", "메시 방식", "파트 ID", "충실도(Hausdorff)", "요소 크기 중앙값 mm",
                                         "h mm", "배율", "세분화 면", "요소 배수", "CAD 첫 오류"], trs, num=(4, 6, 7, 8, 9)))


def convergence_html(shapes: list, bias: dict, esl: list) -> str:
    """수렴 점검 표(C2-D-24): 세분화 형상마다 기준 d000 을 h_r 로 다시 푼 ESL별 δ(same_h_baseline 이면 두 개선율)."""
    if not bias:
        return ""
    labels = {e["entry_id"]: e.get("label") or e["entry_id"][:8] for e in esl}
    trs = []
    for s in shapes:
        b = bias.get(s["id"])
        if not b:
            continue
        if b.get("delta_max") is None:
            trs.append([s["id"], s.get("name") or "", _f(b.get("h_mm")), "—", "—", f"실패 {b.get('error') or ''}", ""])
            continue
        per = " · ".join(f"{labels.get(p['entry_id'], p['entry_id'][:8])} {p['delta'] * 100:+.2f} %"
                         for p in b.get("per_esl") or [])
        both = ""
        if b.get("improvement_same_h") is not None:
            both = f"같은 h 기준 {_pct(b['improvement_same_h'])}"
        trs.append([s["id"], s.get("name") or "", _f(b.get("h_mm")), f"{float(b['delta_max']) * 100:.2f} %",
                    f"{float(b.get('tol') or 0) * 100:g} %", ("초과 ⚠ " if b.get("over_tol") else "") + per, both])
    return ("<h3>수렴 점검(기준 d000 을 세분화 h 로 다시 해석)</h3>"
            + H.table(["id", "이름", "h_r mm", "max|δ|", "허용", "ESL별 δ = C_ref(h_r)/C_ref(h) − 1", "개선율"], trs,
                      num=(2, 3, 4)))


LT_METHOD_KO = {"work": "일 등가(원본 절점력 → 형상 면 최근접점 형상함수)", "cell": "셀 매핑"}
LT_SUPPORT_KO = {"transfer": "기준 지지 → 형상 최근접 노드", "auto": "형상마다 자동 3-2-1", "fallback": "이전 실패 → 자동 3-2-1"}
LT_TRUTH_KO = {"direct_nodal": "① 원본 절점력 직접(기준 = ESL 메시)", "a_direct": "ESL 원본 메시 직접 풀이",
               "mixed": "ESL 마다 다름"}


def _rng(v) -> str:
    return "—" if not v else (f"×{_f(v[0])}" if v[0] == v[1] else f"×{_f(v[0])}~{_f(v[1])}")


def lt_variant_ko(v: str | None) -> str:
    if not v:
        return "—"
    if v == "work":
        return "일 등가"
    if v == "cell:legacy":
        return "셀 기존 24×14"
    return f"셀 {v.split(':', 1)[1]} mm" if v.startswith("cell:") else v


def load_transfer_html(lt: dict | None) -> str:
    """v0.20.0 ④ 하중 전달 절(esl_load_transfer.md LT-13): 방식·지지·영역·참값, 기준 d000 참값 대비 variant 요약·표, 형상 표.
    lt = {result: result.json.load_transfer, diag: post/load_transfer_diag.json} — 없으면 빈 문자열(legacy)."""
    if not lt or not lt.get("result"):
        return ""
    res = lt["result"]
    diag = lt.get("diag") or {}
    cs = res.get("cell_size_mm")
    alt = res.get("alt") or None
    pairs = [("전달 계획", res.get("plan") or "—"),
             ("하중 전달", LT_METHOD_KO.get(res.get("method"), res.get("method"))
              + ("" if res.get("method") != "cell" else (" 기존 24×14" if cs is None else f" {_f(cs)} mm"))),
             ("지지", LT_SUPPORT_KO.get(res.get("support"), res.get("support") or "—")),
             ("평가 영역", res.get("region_mode") or "—"),
             ("다른 방식(진단)", "—" if not alt else lt_variant_ko("work" if alt.get("method") == "work" else (
                 "cell:legacy" if alt.get("cell_size_mm") is None else f"cell:{float(alt['cell_size_mm']):g}"))),
             ("기준 참값", LT_TRUTH_KO.get(res.get("truth"), res.get("truth") or "—")),
             ("다른 방식 순위 같음", "—" if res.get("rank_alt_same") is None else ("예" if res["rank_alt_same"] else "아니오"))]
    inner = H.kv_table(pairs)
    sm = res.get("summary") or []
    if sm:
        inner += "<h3>베이스라인(d000) — 참값 대비</h3>" + H.table(
            ["variant", "umax 배율", "C 배율", "MAC 최소", "하중 상관 최소"],
            [[lt_variant_ko(x["variant"]), _rng(x.get("umax_ratio")), _rng(x.get("C_ratio")), x.get("mac_min"),
              x.get("load_corr_min")] for x in sm], num=(3, 4))
    rows = (diag.get("d000") or {}).get("rows") or []
    if rows:
        inner += H.table(["variant", "ESL", "하중 상관", "Σ|F| 배율", "max|F| 배율", "umax 배율", "C 배율", "MAC"],
                         [[lt_variant_ko(r["variant"]), r.get("label") or r.get("entry_id"), r.get("load_corr"),
                           r.get("sum_abs_ratio"), r.get("max_abs_ratio"), r.get("umax_ratio"), r.get("C_ratio"),
                           r.get("mac")] for r in rows], num=(2, 3, 4, 5, 6, 7))
    shp = diag.get("shapes") or []
    if len(shp) > 1:                                        # once 계획 = 베이스라인 1행 → 형상 표 생략
        trs = []
        for x in shp:
            prim = [p.get("primary") or {} for p in x.get("per_esl") or []]
            ff = [float(p["far_frac"]) for p in prim if p.get("far_frac") is not None]
            dm = [float(p["dM_rel_before"]) for p in prim if p.get("dM_rel_before") is not None]
            sp = x.get("supports") or {}
            trs.append([x["id"], x.get("status") or "", x.get("score_alt"), max(ff) if ff else None,
                        max(dm) if dm else None, LT_SUPPORT_KO.get(sp.get("mode"), sp.get("mode") or "—"),
                        sp.get("max_dist_mm"), (x.get("region") or {}).get("n_out")])
        inner += "<h3>형상별</h3>" + H.table(["id", "상태", "score(다른 방식)", "먼 노드 하중 비", "모멘트 오차(보정 전)",
                                              "지지", "지지 이전 거리 mm", "영역 밖 요소"], trs, num=(2, 3, 4, 6, 7))
    model_diff = res.get("truth") == "a_direct" and (res.get("plan") or "") in ("bmesh_once", "step_once",
                                                                                 "step_per_design")
    inner += ("<p class='small muted'>배율 = variant ÷ 참값(같은 베이스라인(d000) 지지·물성·영역). 하중 상관 = 3N 성분 코사인, MAC = "
              "(u·u_ref)²/((u·u)(u_ref·u_ref)) — 기준이 ESL 메시와 같을 때만. "
              + ("②③ 참값 = ESL 원본 메시 직접 풀이라 배율에 모델 차(A ≠ B)가 포함됩니다 — 방식 간 상대 비교용. "
                 if model_diff else "") + "전체는 post/load_transfer_diag.json</p>")
    return inner


SM_METRIC_KO = {"lin": "1차 강성 지표(재풀이 없음)", "solve": "재풀이 컴플라이언스"}
SM_FORM_KO = {"ritz": "C_ref / ρ (Ritz)", "taylor": "C_ref (2 − ρ) (Taylor)"}
SM_CROSS_KO = ("다른 메시 비교(정밀도 낮음) — 형상·안마다 메시가 달라 1차 강성 지표를 쓰지 않고 work 하중을 옮겨 재풀이한 C 로 "
               "순위를 매깁니다")
SM_VERIFY_CROSS = "순위는 재풀이 C(다른 메시 비교)입니다 — 상위 안은 산출물로 Radioss 검증 낙하를 돌려 확인하세요."
SM_VERIFY = ("순위는 1차 강성 지표입니다 — 상위 안은 산출물(ch_r.rad·ch_r.fem)로 Radioss 검증 낙하를 돌려 확인하세요"
             "(ESL 원본 변형을 강제하는 관점이라 하중 재분배·국부 좌굴은 보지 못함).")


def stiffness_html(sm: dict | None, res: dict, names: dict, top_n: int = 20) -> str:
    """v0.20.0 강성 지표 절(esl_stiffness_metric.md §7·SM-7): 지표 정의·보조 열 표(score_solve·불평형·ρ·umax 강체 제거·εmax)·
    검증 낙하 안내. sm = {metric, lin_form, imbalance_warn} — 없으면 빈 문자열(옛 스냅샷)."""
    if not sm:
        return ""
    rk = res.get("ranking") or []
    warn = float(sm.get("imbalance_warn") or 0.02)
    met = sm.get("metric_effective") or sm.get("metric")
    if sm.get("cross_mesh"):                     # 결정 A: 다른 메시 비교 — 지표 미적용, 순위 = 재풀이 C
        inner = H.kv_table([("순위 지표", SM_METRIC_KO.get(met, met)), ("비교", SM_CROSS_KO)])
    else:
        inner = H.kv_table([("순위 지표", SM_METRIC_KO.get(met, met)),
                            ("식", SM_FORM_KO.get(sm.get("lin_form"), sm.get("lin_form"))),
                            ("정의", "ρ = U_안 / U_ref(베이스라인 변형 u_ref 를 같은 메시의 안에 줄 때 변형에너지 비), "
                                    "C_ref = 베이스라인 컴플라이언스"),
                            ("불평형 경고", f"imbalance_rel > {warn:g}")])
    trs = []
    for x in rk[:top_n]:
        imb = x.get("imbalance_max")
        dim = imb is not None and float(imb) > warn
        trs.append([x["rank"], x["id"], names.get(x["id"], x["id"]), x["score"], x.get("score_solve"),
                    "—" if imb is None else (f"{float(imb) * 100:.1f} %" + (" ⚠" if dim else "")),
                    "—" if x.get("rho_min") is None else f"{_f(x['rho_min'])}~{_f(x['rho_max'])}",
                    x.get("umax_def"), x.get("epsmax")])
    if trs:
        inner += "<h3>보조 열(재풀이·변위 — 순위와 무관)</h3>" + H.table(
            ["순위", "id", "이름", "score(지표)", "score(재풀이)", "불평형 max", "ρ 범위", "umax 강체 제거", "εmax"], trs,
            num=(0, 3, 4, 7, 8))
    verify = SM_VERIFY_CROSS if sm.get("cross_mesh") else SM_VERIFY
    inner += f"<p class='small muted'>{H.esc(verify)} 불평형이 큰 행(⚠)은 재풀이 변위가 무른 모드로 부풀 수 있습니다.</p>"
    return inner


def render_compare(ctx: dict) -> str:
    """④ 형상 직접 비교 보고서(esl_step_compare.md §6): 형상 표·메시 프로필·기준 출처(+ COMPARE_REF_CASE_MESH)·순위·
    ESL별 개선율·한계(+ 메시 차이·같은 좌표계 전제·작은 구멍 메움만·필렛 제거 없음). 변수·DOE·미리보기·민감도·경계 절 없음."""
    st = ctx.get("study") or {}
    ip = ctx.get("inputs") or {}
    ver = ctx.get("versions") or {}
    res = ctx.get("result") or {}
    prof = ctx.get("profile") or {}
    shapes = ctx.get("shapes") or []
    names = {s["id"]: s.get("name") or s["id"] for s in shapes}
    case_ref = ctx.get("reference_source") == "case"
    S = [f"<h1>강성 평가 스터디 · ④ 형상 직접 비교 · {H.esc(st.get('title') or st.get('id'))}</h1>",
         f"<p class='muted small'>연구 {H.esc(st.get('id'))} · {H.esc(st.get('created_at'))} · ESL "
         f"{len(st.get('entry_ids') or [])}개 · 형상 {len(shapes)}개</p>"]
    if case_ref:
        S.append(f"<p class='warn'><b>COMPARE_REF_CASE_MESH</b> — {H.esc(_msg('COMPARE_REF_CASE_MESH'))}</p>")
    for w in ctx.get("warnings") or []:                     # v0.16.0 메시 방식 머리 경고(esl_compare_mesh_options.md §9)
        code, _sep, msg = str(w).partition(": ")
        if code in MESH_HEAD_CODES:
            S.append(f"<p class='warn'><b>{H.esc(code)}</b> — {H.esc(msg or _msg(code))}</p>")
    rk = res.get("ranking") or []
    if rk:
        b = rk[0]
        S.append(H.cards([("최적 형상", H.esc(names.get(b["id"], b["id"]))), ("score", H.esc(_f(b["score"]))),
                          ("개선율", H.esc(_pct(b["improvement"]))), ("성공 형상", H.esc(res.get("n_ok")))]))
    pairs = [("시나리오", "④ 형상 직접 비교"),
             ("기준", f"{names.get('d000', 'd000')} ({'첫 ESL Case 메시' if case_ref else '기준 STEP'})"),
             ("인치", ip.get("inch")), ("gmsh 버전", ver.get("gmsh"))]
    if ip.get("props"):
        p = ip["props"]
        pairs.append(("쉘 물성(모든 형상 같음)", f"t {_f(p.get('t'))} mm · E {_f(p.get('E'))} MPa · ν {_f(p.get('nu'))}"))
    pairs.append(("메시 프로필", f"요소 {_f(prof.get('size_mm'))} mm · 최소 ×{_f(prof.get('min_size_factor'))} · 곡률 "
                               f"{prof.get('curvature_n')} · 경계 확장 {prof.get('extend_from_boundary')} · OCC 작은 형상 정리 "
                               f"{prof.get('occ_fix_small')}"))
    inner = H.kv_table(pairs)
    ents = ip.get("entries") or []
    if ents:
        inner += "<h3>선택 ESL</h3>" + H.table(["ESL", "이름", "출처 Case"],
                                              [[e.get("entry_id"), e.get("label") or "", e.get("case") or ""]
                                               for e in ents])
    S.append(H.section("inputs", "1. 입력", inner))
    trs = []
    for s in shapes:
        trs.append([s["id"], s.get("name") or "", s.get("file_name") or ("Case 메시" if s.get("source") == "case" else ""),
                    SOURCE_KO.get(s.get("source") or "step", s.get("source") or ""), method_label(s),
                    (str(s.get("sha256") or "")[:12] + "…") if s.get("sha256") else "", s.get("n_elems") or "",
                    "" if s.get("quad_ratio") is None else _f(s.get("quad_ratio")),
                    "" if not s.get("quality") else f"{s['quality']['fail_elems']} ({s['quality']['fail_ratio'] * 100:.2f} %)"
                    + (f" · 폴백 면 {s['quality']['fallback_faces']}개(id "
                       f"{', '.join(map(str, s['quality'].get('fallback_face_ids') or []))}"
                       + (f": {', '.join(s['quality']['fallback_stages'])}" if s["quality"].get("fallback_stages") else "")
                       + ")" if s["quality"].get("fallback_faces") else ""),
                    SHAPE_STATE_KO.get(s.get("status"), s.get("status") or ""), s.get("code") or ""])
    inner = H.table(["id", "이름", "파일", "출처", "메시 방식", "sha256", "요소 수", "quad 비율", "품질 Fail", "준비 상태", "코드"],
                    trs, num=(6, 7))
    inner += mesh_detail_html(shapes) + convergence_html(shapes, ctx.get("refine_bias") or {}, ctx.get("esl") or [])
    inner += defeature_html(shapes, ctx.get("defeature_lists") or {})
    S.append(H.section("shapes", "2. 형상", inner))
    df = prof.get("defeature") or {}
    if df:
        S.append("<p class='small muted'>작은 형상 처리(이슈 #53 holes table 근사): 내부 경계 면적 &lt; "
                 f"{H.esc(_f(df.get('min_hole_area_mm2')))} mm² 메움 · 반지름 {H.esc(df.get('hole_r_mm'))} mm 구멍 둘레 요소 "
                 f"{H.esc(df.get('hole_elems'))}개 · 비드 억제 기준 {H.esc(_f(df.get('min_bead_height_mm')))} mm(defeature 단계에서 적용)</p>")
    if rk:
        top_n = int(ctx.get("ranking_rows") or 20)
        hdr = ["순위", "id", "이름", "score", "개선율", "최악 ESL", "umax", "εmax", "전 씬 개선", "최소 개선율", "개선/악화 씬",
               "기하평균 개선율", "Pareto"]
        rows = []
        for x in rk[:top_n]:
            allv = x.get("all_improved")
            rows.append([x["rank"], x["id"], names.get(x["id"], x["id"]), x["score"], _pct(x["improvement"]),
                         x.get("worst_entry_id") or "", x["umax"], x["epsmax"],
                         "–" if allv is None else ("✓" if allv else "✗"), _pct(x.get("min_improvement")),
                         f"{x.get('n_improved', 0)} / {x.get('n_worsened', 0)}", _pct(x.get("geo_mean_improvement")),
                         "●" if x.get("pareto") else ""])
        inner = H.table(hdr, rows, num=(0, 3, 6, 7, 9, 11))
        inner += per_esl_html(rk, ctx.get("esl") or [], top_n)
        inner += ("<p class='small muted'>지표 정의 — " + " · ".join(f"{H.esc(k)}: {H.esc(v)}" for k, v in METRIC_DEFS)
                  + f" (허용치 {H.esc(_f(res.get('ratio_tol')))})</p>")
        inner += (f"<p class='small muted'>C_ref(기준 형상 최악) {H.esc(_f(res.get('C_ref')))} · 기준 umax "
                  f"{H.esc(_f((res.get('baseline') or {}).get('umax')))} · 전체는 ranking.csv</p>")
    else:
        inner = f"<p>{H.esc(_msg('NO_FEASIBLE_DESIGNS'))}</p>"
    nf = res.get("n_failed") or {}
    inner += (f"<p class='small'>성공 {H.esc(res.get('n_ok', 0))} · 실패 메시 {H.esc(nf.get('mesh', 0))}·크기/정렬 "
              f"{H.esc(nf.get('size', 0))}·해석 {H.esc(nf.get('solve', 0))}</p>")
    S.append(H.section("ranking", "3. 순위(기준 형상 대비)", inner))
    sm_html = stiffness_html(ctx.get("stiffness"), res, names)
    if sm_html:                                             # v0.20.0 SM-7(새 스냅샷만)
        S.append(H.section("stiffness", "강성 지표", sm_html))
    lt_html = load_transfer_html(ctx.get("load_transfer"))
    if lt_html:                                             # v0.20.0 LT-13(새 스냅샷만 — legacy 보고서 바이트 불변)
        S.append(H.section("load_transfer", "하중 전달", lt_html))
    best = ctx.get("best")
    if best:
        S.append(H.section("best", f"4. 최적 형상 {best.get('id')} {names.get(best.get('id'), '')}",
                           "<p class='small'>산출물: " + H.esc(", ".join(best.get("files") or [])) + "</p>"))
    warns = [w for w in ctx.get("warnings") or [] if not str(w).startswith("COMPARE_REF_CASE_MESH")]
    if warns:
        S.append(H.section("warnings", "경고", "<ul>" + "".join(f"<li>{H.esc(w)}</li>" for w in warns) + "</ul>"))
    S += _methods_limits(ctx.get("sources") or {}, ctx.get("limits_extra"))
    title = f"강성 평가 스터디 {st.get('title') or st.get('id') or ''}".strip()
    return H.page(title, "\n".join(S), extra_css=EXTRA_CSS, version="doe")


WARN_KO = {"FIXED_MOVED": "체결 위치 어긋남", "QUALITY_WARN": "품질 경고", "CROSS_BEAD_MOVE": "다른 비드 침범",
           "MORPH_EXTREME_ELEMENTS": "극단 요소"}           # v0.16.2 AD-D-8
MESH_BASE_KO = "B 메시(다른 모델 — 하중 셀 매핑, 지지 자동 3-2-1)"   # v0.16.2 AD-D-20 select_base mesh 머리
STEP_BASE_KO = "③ 그래프(기준 메시 기저 모핑, 메시 방식 {method})"   # v0.18.0 SG-D-11 select_base step 머리


def _warn_ko(w) -> str:
    return "⚠ " + " · ".join(WARN_KO.get(x, x) for x in w) if w else ""


def selection_html(sel: dict, ms: dict | None = None) -> str:
    """v0.15.0 select: 비드 표(단 깊이·폭·사면·블렌딩·경고) + 모핑 규칙 + 미리보기 품질(새 Fail/영향 요소)."""
    rows = []
    for b in sel.get("beads") or []:
        if b.get("src") == "graph":                  # v0.17.0 그래프 비드 1줄(§6.3) — schema 1 행은 그대로
            w = "—" if b.get("W_nom") is None else _f(b["W_nom"])
            rows.append([b.get("id"), b.get("name"), f"D {_f(b.get('D_nom'))} (상대)", w,
                         f"세그먼트 {b.get('n_segments', 0)} · 접합 구역 {b.get('n_junction_zones', 0)} · 묶음 출처(그래프)",
                         "—", ", ".join(sorted({x.get("code", "") for x in b.get("warnings") or []})) or "—"])
            continue
        tiers = " · ".join(f"D{t['k']} {_f(t.get('D_nom'))}" for t in b.get("tiers") or [])
        w = "—" if b.get("W_nom") is None else f"{_f(b['W_nom'])} ({_f(b.get('W_min'))}–{_f(b.get('W_max'))})"
        rows.append([b.get("id"), b.get("name"), tiers, w, (b.get("slope") or {}).get("n_elems"),
                     _f(b.get("blend_mm")) + (" (잘림)" if b.get("blend_clipped") else ""),
                     ", ".join(sorted({x.get("code", "") for x in b.get("warnings") or []})) or "—"])
    inner = H.table(["비드", "이름", "단 깊이 mm", "폭 mm (최소–최대)", "사면 요소", "블렌딩 R mm", "경고"], rows)
    fx = sel.get("fixed") or {}
    inner += (f"<p class='small'>선택 sha256 <code>{H.esc(str(sel.get('sha256'))[:16])}…</code> · 고정 노드 "
              f"{H.esc(fx.get('source'))} (스캔 {H.esc(fx.get('scan_n', 0))} · 사용자 {H.esc(fx.get('user_n', 0))})</p>")
    q = sel.get("quality") or []
    if q:
        inner += "<h3>미리보기 품질(새 Fail / 영향 요소)</h3>" + H.table(
            ["안", "상태", "새 Fail", "영향 요소", "고정 최대 변위 mm", "경고"],
            [[x["id"], STATE_KO.get(x.get("state"), x.get("state")), x.get("new_fail"), x.get("n_affected"),
              _f(x.get("fixed_max_mm")), _warn_ko(x.get("warn"))] for x in q], num=(2, 3, 4))
    mv = sel.get("fixed_moved") or []
    if mv:                                       # v0.16.1 확정 1: 고정 노드도 모핑대로 움직인 안(제외하지 않음)
        inner += ("<h3>체결 위치 어긋남</h3><p class='small'>아래 안은 고정 노드(체결 위치)가 모핑으로 같이 움직였습니다 — "
                  "결과·받기 파일을 쓰기 전에 RBE2/TIE 위치를 확인하세요(받기 rad 사본에 경고 주석).</p>")
        inner += H.table(["안", "고정 노드 수", "최대 이동 mm", "원인 변수(상위 3)"],
                         [[x["id"], x.get("n"), _f(x.get("max_mm")),
                           ", ".join(f"{v['name']} {_f(v['max_mm'])} mm" for v in x.get("bead_vars") or []) or "—"]
                          for x in mv], num=(1, 2))
    sm = (ms or {}).get("select") or {}
    if sm:
        inner += "<h3>모핑 규칙</h3><ul>" + "".join(f"<li><b>{H.esc(k)}</b>: {H.esc(v)}</li>"
                                                for k, v in (sm.get("methods") or {}).items()) + "</ul>"
        inner += "<ul class='small'>" + "".join(f"<li>{H.esc(x)}</li>" for x in sm.get("limits_ko") or []) + "</ul>"
        src = [f"<li>{H.esc(x['title'])}" + (f" — {H.esc(x['authors'])}" if x.get("authors") else "")
               + (f" <span class='muted'>({H.esc(x['note'])})</span>" if x.get("note") else "") + "</li>"
               for x in sm.get("sources") or []]
        inner += "<ol class='small'>" + "".join(src) + "</ol>"
    return inner


def render(ctx: dict) -> str:
    st = ctx.get("study") or {}
    if st.get("scenario") == "compare":
        return render_compare(ctx)
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
        if b.get("warn"):                        # v0.16.1 Q1 = A: 순위 그대로 + 경고 없는 최상위 1줄
            bc = (ctx.get("selection") or {}).get("best_clean")
            if not ctx.get("selection"):         # v0.16.2 AD-D-8 다른 시나리오(극단 요소 ⚠): 순위에서 경고 없는 최상위
                bc = next((x["id"] for x in res["ranking"] if not x.get("warn")), None)
            S.append(f"<p class='warn'>⚠ 최적 안 {H.esc(b['id'])} 은(는) {H.esc(_warn_ko(b['warn'])[2:])} 경고 안입니다 — "
                     f"경고 없는 최상위: {H.esc(bc or '없음')}</p>")
    # 1. 입력
    step_row = ("STEP", f"{(ip.get('step') or {}).get('file_name')} (sha256 {str((ip.get('step') or {}).get('sha256'))[:12]}…)")
    if st.get("scenario") == "select":
        step_row = ("STEP", "없음 — 낙하 메시에서 비드 직접 선택(산출물에 CAD 없음)")
        if ip.get("step"):                       # v0.16.2 자동 탐지(seed 출처 — 산출물에 CAD 없음)
            step_row = ("STEP", f"{(ip.get('step') or {}).get('file_name')} — 자동 탐지 초기 선택 입력(산출물에 CAD 없음)")
    pairs = [("시나리오", SCN_KO.get(st.get("scenario"), str(st.get("scenario")))),
             step_row,
             ("파트 제목", ip.get("part_title")), ("인치", ip.get("inch")),
             ("paicad 버전", ver.get("paicad")), ("gmsh 버전", ver.get("gmsh"))]
    if ip.get("select_base") == "mesh":
        pairs.insert(1, ("기준", MESH_BASE_KO))
    if ip.get("select_base") == "step":          # v0.18.0 SG-D-11 방법 1줄(기존 ③ 과 다른 방식)
        mm = (ip.get("mesh") or {}).get("method") or "?"
        pairs[1] = ("STEP", f"{(ip.get('step') or {}).get('file_name')} — 기준 메시 원천(산출물에 CAD 없음)")
        pairs.insert(1, ("기준", STEP_BASE_KO.format(method=mm)))
    if ip.get("mesh") and ip.get("select_base") != "step":
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
    if ctx.get("selection"):
        S.append(H.section("selection", "1-1. 비드 선택·모핑 규칙", selection_html(ctx["selection"], ms)))
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
        # v0.16.1 ⚠ 열(select) — v0.16.2 AD-D-8: 다른 시나리오도 경고 안(극단 요소)이 있을 때만(없으면 보고서 불변)
        sel_w = st.get("scenario") == "select" or any(x.get("warn") for x in rk)
        hdr = (["순위", "안", "score", "개선율", "최악 ESL", "umax", "εmax", "전 씬 개선", "최소 개선율", "개선/악화 씬",
                "기하평균 개선율", "Pareto"] + names + ["경고"] + (["⚠"] if sel_w else []))
        trs = []
        for x in rk[:top_n]:
            imp = H.esc(_pct(x["improvement"])) + (" <span class='muted'>(잡음 이내)</span>" if x.get("noise") else "")
            allv = x.get("all_improved")
            trs.append([x["rank"], x["id"], x["score"], imp, x.get("worst_entry_id") or "", x["umax"], x["epsmax"],
                        "–" if allv is None else ("✓" if allv else "✗"), _pct(x.get("min_improvement")),
                        f"{x.get('n_improved', 0)} / {x.get('n_worsened', 0)}", _pct(x.get("geo_mean_improvement")),
                        "●" if x.get("pareto") else ""]
                       + [x["values"].get(n) for n in names] + [x.get("warnings_n", 0)]
                       + ([_warn_ko(x.get("warn"))] if sel_w else []))
        inner = H.table(hdr, trs, num=(0, 2, 5, 6, 8, 10) + tuple(range(12, 12 + len(names))), raw=(3,))
        inner += per_esl_html(rk, ctx.get("esl") or [], top_n)
        inner += ("<p class='small muted'>지표 정의 — " + " · ".join(f"{H.esc(k)}: {H.esc(v)}" for k, v in METRIC_DEFS)
                  + f" (허용치 {H.esc(_f(res.get('ratio_tol')))})</p>")
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
    sm_html = stiffness_html(ctx.get("stiffness"), res, {})
    if sm_html:                                             # v0.20.0 SM-7(새 스냅샷만)
        S.append(H.section("stiffness", "강성 지표", sm_html))
    lt_html = load_transfer_html(ctx.get("load_transfer"))
    if lt_html:                                             # v0.20.0 LT-13·20(새 스냅샷만 — legacy 보고서 바이트 불변)
        S.append(H.section("load_transfer", "하중 전달", lt_html))
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
