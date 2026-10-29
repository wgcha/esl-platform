"""Case HTML 보고서 (계약 esl_p2_library.md §5·§7.3) → ``<case>/07_report/report.html``.

자체 완결 단일 파일(inline CSS·SVG·JSON·소량 JS, 외부 URL 0). 내용: 입력 요약, t* max-hold 곡선(두 지표),
3-2-1 지지점, F_eq 상위 표, 검증 요약, 전 요소 재현 정확도(최대변형률 비교·분위수), **겹쳐보기**(2D 요소 컨투어
Radioss ε / ESL ε / 오차 % 전환 + 불투명도 슬라이더 겹치기, 공통 색 범위, 회색 = 비교 불가, hotspot·지지점 표시),
변형 단면선 겹치기(초기·Radioss·ESL, 배율 슬라이더), 상위 N 표, 히스토그램, 의미 주석.

요소 수가 ``max_points`` 를 넘으면 2D 셀 격자 다운샘플(esl.report.field.downsample). 각 절은 앞 단계 산출물이
없으면 "자료 없음"으로 표시한다(보고서 생성 자체는 실패하지 않음).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any

import numpy as np

import esl
from esl.display import display_path
from esl.report import field as F
from esl.report import html as H

D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT, D_REPORT = (
    "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report")
REPORT_NAME = "report.html"
METRIC_LABEL = {"max_strain": "Max_Strain ε_eq", "plastic_strain": "Plastic Strain"}


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_npz(path: str) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


class _Case:
    """사례 폴더 산출물(있는 것만)."""

    def __init__(self, case_dir: str, record: dict | None):
        self.dir = case_dir
        self.missing: list[str] = []
        self.record = record if record is not None else self.json(None, "run.json") or {}
        self.meta = self.json(D_EXTRACT, "model_meta.json")
        self.frames = self.json(D_EXTRACT, "frames.json")
        self.model = self.npz(D_EXTRACT, "model.npz")
        self.tstar = self.json(D_TSTAR, "tstar.json")
        self.support = self.json(D_BC, "support.json")
        self.summ = self.json(D_ESL, "esl_summary.json")
        self.feq = self.npz(D_ESL, "f_eq.npz")
        self.val = self.json(D_VAL, "validation.json")
        self.field = self.npz(D_VAL, "compare_field.npz")

    def _p(self, sub, name):
        return os.path.join(self.dir, name) if sub is None else os.path.join(self.dir, sub, name)

    def json(self, sub, name):
        p = self._p(sub, name)
        if not os.path.isfile(p):
            self.missing.append(f"{sub}/{name}" if sub else name)
            return None
        return _read_json(p)

    def npz(self, sub, name):
        p = self._p(sub, name)
        if not os.path.isfile(p):
            self.missing.append(f"{sub}/{name}")
            return None
        return _load_npz(p)


def _none(msg: str = "자료 없음 — 해당 단계를 먼저 실행") -> str:
    return f'<p class="muted">{H.esc(msg)}</p>'


# ====================================================================== 절
def _sec_inputs(c: _Case) -> str:
    rec = c.record or {}
    inp = rec.get("inputs") or {}
    rad = inp.get("rad") or {}
    meta = c.meta or {}
    fr = c.frames or {}
    cfg = (rec.get("config") or {})
    sel = (c.tstar or {}).get("selected") or {}
    units = ((cfg.get("snapshot") or {}).get("units") or {})
    th = meta.get("thickness_range")
    mats = ", ".join(f"#{m.get('id')} law{m.get('law')} E={H.fmt(m.get('E'))} ν={H.fmt(m.get('nu'))}"
                     for m in (meta.get("mats") or [])[:6])
    pairs = [
        ("파트", f"{meta.get('part_id', '—')} '{meta.get('part_title', '—')}'"),
        ("노드 / 요소", f"{meta.get('n_nodes', '—')} / {meta.get('n_elems', '—')} "
                     f"(QUAD {meta.get('n_quad', '—')}, TRIA {meta.get('n_tria', '—')})"),
        ("두께 범위", "—" if not th else f"{H.fmt(th[0])} ~ {H.fmt(th[1])}"),
        ("재료", mats or "—"),
        ("단위", units.get("label") or meta.get("units_label") or "—"),
        ("rad", H.Raw(f"<code>{H.esc(display_path(rad.get('path', '—')))}</code>")),
        ("rad sha256", H.Raw(f"<code>{H.esc(rad.get('sha256', '—'))}</code>")),
        ("결과 CSV 폴더", H.Raw(f"<code>{H.esc(display_path(inp.get('results_dir', '—')))}</code>")),
        ("h3d", display_path(fr.get("h3d")) or "—"),
        ("프레임(이력) / 후보 D", f"{fr.get('n_frames', '—')} / {fr.get('frames_D', '—')}"),
        ("직전 프레임(비교용)", f"{fr.get('prev_frame_index', '—')}"),
        ("전단 규약", ((fr.get("shear") or {}).get("convention")) or "—"),
        ("t* (선택)", "—" if not sel else f"frame {sel.get('frame_index')} · time {H.fmt(sel.get('time'))} · "
                                       f"{sel.get('metric', '—')} · {sel.get('source', '—')}"),
        ("설정 sha256", H.Raw(f"<code>{H.esc(cfg.get('sha256', '—'))}</code>")),
    ]
    return H.kv_table(pairs)


_MODE_KO = {"cumulative": "누적값", "incremental": "증분(이번 낙하분)", "trivial": "이전 소성 거의 없음"}


def _state_summary(c: _Case) -> dict | None:
    """누적 씬이면 01_extract/state_summary.json (없으면 None — 비누적 보고서는 바뀌지 않음, missing 에도 안 넣음)."""
    p = c._p(D_EXTRACT, "state_summary.json")
    return _read_json(p) if os.path.isfile(p) else None


def _sec_cumulative(c: _Case, ss: dict) -> str:
    """누적 낙하 입력(계약 esl_cumulative_input.md §8): 상태 파일·좌표·두께·이전 소성·h3d 판정·t* 3값."""
    files = H.table(["파일", "종류", "크기(MB)", "runname"],
                    [(os.path.basename(f.get("path", "")), ", ".join(f.get("kinds") or []) or "—",
                      None if f.get("size") is None else f["size"] / 1e6, f.get("runname") or "—")
                     for f in ss.get("files") or []], num=(2,))
    co, el, th = ss.get("coord") or {}, ss.get("elems") or {}, ss.get("thickness") or {}
    ei, dg = ss.get("epsp_init") or {}, ss.get("diagnosis") or {}
    r = th.get("ratio") or {}

    def dtext(d):
        if not d:
            return "—"
        t = _MODE_KO.get(d.get("mode"), d.get("mode"))
        if d.get("ambiguous"):
            t += " (판정 불확실 → 증분으로 보고 합)"
        if d.get("forced"):
            t += " (설정 강제)"
        if d.get("r0") is not None:
            t += f" · r0 {H.fmt(d['r0'])} · 일치 비율 {H.fmt(d.get('mono'))} · |S| {d.get('n_S')}"
        return t
    pairs = [
        ("좌표 출처", f"상태 파일 {co.get('n_nodes_state', '—')} / rad {co.get('n_nodes_rad', '—')} 노드 "
                  f"(중복 {co.get('n_dup', 0)}) — K_L·형상 = 이전 런 변형 좌표"),
        ("요소 출처", f"상태 파일 {el.get('n_state', '—')} / rad {el.get('n_rad', '—')} (중복 {el.get('n_dup', 0)})"),
        ("두께 t/t₀", "—" if not r else f"최소 {H.fmt(r.get('min'))} · 평균 {H.fmt(r.get('mean'))} · 최대 "
                                       f"{H.fmt(r.get('max'))} (t₀ {H.fmt(th.get('t0'))}, K_L 두께 = "
                                       f"{th.get('k_l_source', '—')})"),
        ("두께 변화 >1 % 요소", f"{th.get('n_changed', '—')} · 최대 감육 {H.fmt(th.get('max_thinning_pct'))} % "
                            f"@ elem {th.get('elem_max_thinning', '—')}"),
        ("이전 소성 변형률", f"최대 {H.fmt(ei.get('max'))} · P99 {H.fmt(ei.get('p99'))} · 양수 요소 "
                       f"{ei.get('n_pos', '—')} (집계 {ss.get('agg', '—')}, 원값 최대 {H.fmt(ei.get('prev_max'))})"),
        ("h3d 소성(Plastic Strain)", dtext(dg.get("epsp"))),
        ("h3d 총변형률(Max_Strain)", dtext(dg.get("eq"))),
        ("경고", ", ".join(ss.get("warning_codes") or []) or "없음"),
    ]
    rows = []
    for m, rec in ((c.tstar or {}).get("metrics") or {}).items():
        ts = (rec or {}).get("tstar") or {}
        if "value_inc" not in ts:
            continue
        rows.append((METRIC_LABEL.get(m, m), ts.get("frame_index"), ts.get("elem_id"), ts.get("value"),
                     ts.get("value_prev"), ts.get("value_inc"),
                     ((rec.get("cumulative") or {}).get("n_excluded_no_increment"))))
    ttab = H.table(["지표", "t* frame", "elem", "누적", "이전", "이번(증분)", "이전 손상만 제외"], rows,
                   num=(1, 2, 3, 4, 5, 6)) if rows else _none("t* 자료 없음")
    note = ('<p class="small muted">t* 순위 = 누적(이전 + 이번), 시점 = 이번 낙하 증분이 최종값에 처음 도달한 프레임. '
            '총변형률의 이전 값은 이전 소성 변형률로 근사(가정 확정 Q1 — 탄성 회복·방향 무시). ⑤ 변형률 참고 비교는 '
            '이번 낙하 증분 기준.</p>')
    return files + H.kv_table(pairs) + ttab + note


def _sec_tstar(c: _Case) -> str:
    tj = c.tstar
    if not tj:
        return _none()
    sel = tj.get("selected") or {}
    charts = []
    for m in ("max_strain", "plastic_strain"):
        rec = (tj.get("metrics") or {}).get(m) or {}
        hist = rec.get("history")
        if not hist or "error" in rec:
            charts.append(f"<div><h3>{H.esc(METRIC_LABEL[m])}</h3>{_none(rec.get('error', '자료 없음'))}</div>")
            continue
        ts = rec.get("tstar") or {}
        marks = [{"x": x["time"], "y": x["value"], "label": f"후보 {x['rank']}: frame {x['frame_index']} · "
                  f"elem {x['elem_id']} · {H.fmt(x['value'])}", "cls": "mk1" if x["rank"] == 1 else "mk"}
                 for x in rec.get("candidates") or []]
        vl = [(sel.get("time"), f"t* (선택) f{sel.get('frame_index')}")] if m == tj.get("metric") else \
             [(ts.get("time"), f"t* f{ts.get('frame_index')}")]
        svg = H.line_chart([{"x": hist["time"], "y": hist["m"], "cls": "s1", "label": f"max_e∈H {m}"}],
                           xlabel="time", ylabel=METRIC_LABEL[m], vlines=vl, markers=marks,
                           title=f"{METRIC_LABEL[m]} — max-hold 최대값 m(t)")
        cand = H.table(["rank", "frame", "time", "elem", "값", "D 안"],
                       [(x["rank"], x["frame_index"], x["time"], x["elem_id"], x["value"], "예" if x.get("in_D") else "아니오")
                        for x in rec.get("candidates") or []], num=(0, 1, 2, 3, 4))
        charts.append(f"<div><h3>{H.esc(METRIC_LABEL[m])}</h3>{svg}{cand}</div>")
    note = ('<p class="small muted">h3d 의 Max_Strain·Plastic Strain 은 요소별 max-hold 값 — t* = 최종 최대값에 처음 '
            '도달한 프레임(first-reach). 점 = 후보 프레임(빨강 = rank 1).</p>')
    return f'<div class="grid2">{"".join(charts)}</div>{note}'


def _sec_supports(c: _Case) -> str:
    sp = c.support
    if not sp:
        return _none()
    rows = [(s["node_id"], s["dof"], s.get("flags", ""), *s["x0"]) for s in sp.get("supports") or []]
    return (f'<p>지지 방식: <b>{H.esc(sp.get("mode"))}</b> — 3-2-1 정정 구속(강체 6자유도만 구속, 자기평형 하중이면 '
            f'반력≈0). 겹쳐보기 지도에 △로 표시.</p>'
            + H.table(["node", "dof", "flags", "x0", "y0", "z0"], rows, num=(3, 4, 5)))


def _sec_feq(c: _Case, top: int) -> str:
    if not c.summ or not c.feq:
        return _none()
    s = c.summ
    fo = s.get("forces") or {}
    kb = s.get("kabsch") or {}
    f = np.asarray(c.feq["f"], dtype=np.float64)
    nid = c.feq["node_id"]
    bc = c.feq["is_bc"]
    mag = np.linalg.norm(f, axis=1)
    order = np.lexsort((np.arange(mag.size), -mag))[:top]
    cards = H.cards([
        ("t* frame", H.fmt((s.get("frame") or {}).get("frame_index"))),
        ("강체 회전(Kabsch)", f"{H.fmt(kb.get('rot_deg'))}°"),
        ("Σ|F|", H.fmt(fo.get("sum_abs_f"))), ("|ΣF| / Σ|F|", H.fmt(fo.get("equilibrium_rel"))),
        ("합모멘트 상대", H.fmt(fo.get("moment_rel"))), ("비영 노드", H.fmt(fo.get("n_nodes_nonzero"))),
    ])
    rows = [(i + 1, int(nid[k]), f[k, 0], f[k, 1], f[k, 2], mag[k], "BC" if bc[k] else "") for i, k in enumerate(order)]
    return (cards + f"<h3>|F| 상위 {len(rows)}개 노드</h3>"
            + H.table(["#", "node", "Fx", "Fy", "Fz", "|F|", ""], rows, num=(0, 1, 2, 3, 4, 5)))


_METRIC_TEXT = {
    "disp_rms_rel": "변위 왕복 RMS(u_val − u_rel)/max|u_rel|",
    "hotspot1_strain_rel_err": "hotspot 1위 |ε_val − ε_rad|/ε_rad",
    "reaction_rel": "3-2-1 반력 Σ|R|/Σ|F|",
    "disp_max_rel": "변위 왕복 max|u_val − u_rel|/max|u_rel| (전 노드)",
    "disp_noise_rel": "변위 저장 정밀도 잡음 δ/max|u_rel| (추가 해석 없음)",
    "reaction_sum_rel": "|ΣR|/Σ|F|",
    "u_rel_linear_rigid_rel": "u_rel 의 잔여 미소 강체 성분",
    "noise_hotspot_strain_rel": "변위 정밀도 잡음 → hotspot ε 상대 변화",
    "noise_force_rel": "변위 정밀도 잡음 → rms(F_noise)/rms(F_eq)",
    "field_max_err_pct": "최대변형률 요소 |ε_esl − ε_rad|/ε_rad (%)",
    "field_p90_err_pct": "valid 요소 |오차| 90 분위 (%)",
}


STATUS_TEXT = {"PASS": "PASS", "FAIL": "FAIL", "UNDETERMINED": "판정 불가", "LEGACY": "이전 판정 체계"}
UNDET_TEXT = {"NO_FULL_SOLVE": "전체 재해석 생략 — 변위 비교가 없어 판정하지 않음",
              "ZERO_DISP": "u_rel 이 전부 0(변형 없음) — 상대 지표를 정의할 수 없어 판정하지 않음"}


def status_of(v: dict | None) -> str | None:
    """표시 상태: scheme(verdict_scheme)이 없으면 LEGACY, 아니면 verdict (PASS|FAIL|UNDETERMINED)."""
    if not v:
        return None
    return v.get("verdict") if v.get("verdict_scheme") else "LEGACY"


def status_badge(v: dict | None) -> str:
    st = status_of(v)
    if st in ("PASS", "FAIL"):
        return H.badge(st)
    if st is None:
        return H.badge(None)
    extra = f' <span class="small muted">당시 {H.esc(v.get("verdict"))}</span>' if st == "LEGACY" else ""
    return f'<span class="badge na">{H.esc(STATUS_TEXT[st])}</span>{extra}'


def _sec_disp(v: dict) -> str:
    """변위 전 노드 분석(full_solve 수행 시): 로그 히스토그램 표 + 상위 노드 표."""
    dp = v.get("disp")
    if not dp:
        return ""
    h = dp.get("hist") or {}
    e = h.get("edges_log10") or []
    cnt = h.get("counts") or []
    rows = [(f"1e{e[i]:g} ~ 1e{e[i + 1]:g}", cnt[i]) for i in range(len(cnt))]
    if h.get("n_zero"):
        rows.insert(0, ("= 0", h["n_zero"]))
    top = [(i + 1, t["node_id"], t["r"], t["e"], t["u_rel_mag"], "지지" if t.get("is_support") else "")
           for i, t in enumerate(dp.get("top") or [])]
    cards = H.cards([("U = max|u_rel|", H.fmt(dp.get("U"))),
                     ("RMS(e)/U", H.fmt(dp.get("rms_rel"))),
                     ("max(e)/U", H.fmt(dp.get("max_rel")) + f'<div class="small muted">node {H.esc(dp.get("max_node_id"))}</div>'),
                     ("P50 / P90 / P99 (e/U)", f'{H.fmt(dp.get("p50"), 3)} / {H.fmt(dp.get("p90"), 3)} / {H.fmt(dp.get("p99"), 3)}'),
                     ("노드 / 지지", f'{H.fmt(dp.get("n_nodes"))} / {H.fmt(dp.get("n_support"))}')])
    return ("<h3>변위 비교 (전 노드)</h3>"
            '<p class="small muted">e = ‖d_val − d_rel‖(양쪽 독립 미소 강체 제거 후), r = e/U. S4 와 S5 가 같은 K 를 쓰므로 '
            "이 값은 물리 차이가 아니라 계산·경계조건·저장 정밀도의 수치 일관성이다.</p>"
            + cards + "<h4>r = e/U 분포 (log10 bin)</h4>" + H.table(["r 범위", "노드 수"], rows, num=(1,))
            + "<h4>상위 노드</h4>" + H.table(["#", "node", "r = e/U", "e", "‖d_rel‖", ""], top, num=(0, 1, 2, 3, 4)))


def _sec_validation(c: _Case) -> str:
    v = c.val
    if not v:
        return _none()
    st = status_of(v)
    legacy = st == "LEGACY"
    mets = v.get("metrics") or []

    def row(m):
        return (m["metric"], _METRIC_TEXT.get(m["metric"], ""), m.get("value"), m.get("criterion"),
                H.pass_cell(m.get("pass")) if m.get("status") != "skipped" else '<span class="na">생략</span>')

    judge = [m for m in mets if (m.get("role") == "judge")] if not legacy else mets
    fs = v.get("full_solve") or {}
    hs = [(h["rank"], h["elem_id"], h.get("eps_rad"), h.get("eps_val"),
           None if h.get("rel_err") is None else 100.0 * float(h["rel_err"])) for h in v.get("hotspots") or []]
    ex = [(h["rank"], h["elem_id"], h.get("reason", "")) for h in v.get("hotspots_excluded") or []]
    out = [f'<p>판정: {status_badge(v)} '
           + (f'<span class="muted">사유 {H.esc(", ".join(v.get("fail_reasons") or []))}</span>'
              if v.get("fail_reasons") else "") + "</p>"]
    if st == "UNDETERMINED":
        out.append(f'<p class="small">{H.esc(UNDET_TEXT.get(v.get("undetermined_reason"), v.get("undetermined_reason") or ""))}'
                   f' (full_solve={H.esc((v.get("criteria") or {}).get("full_solve", fs.get("mode")))}: '
                   f'{H.esc(fs.get("reason", ""))})</p>')
    else:
        out.append(f'<p class="small muted">S5 전체 재해석: {"수행" if fs.get("run") else "생략"} ({H.esc(fs.get("reason", ""))})</p>')
    if not legacy:
        out.append('<p class="small muted">판정 = 변위 4지표(전 노드, 3-2-1 지지 노드 포함). 변형률은 아래 "참고" 표 — 판정에 쓰지 않는다.</p>')
    out.append(H.table(["지표", "의미", "값", "기준", "판정"], [row(m) for m in judge], num=(2, 3), raw=(4,)))
    if not legacy:
        refs = [m for m in mets if m.get("role") == "reference"]
        sr = v.get("strain_ref") or {}
        pl = sr.get("plastic")
        out.append("<h3>변형률 (참고 — 판정 아님)</h3>")
        out.append(H.table(["지표", "의미", "값", "참고 기준", "참고 초과"],
                           [(m["metric"], _METRIC_TEXT.get(m["metric"], ""), m.get("value"), m.get("criterion"),
                             '<span class="badge na">참고 초과</span>' if m.get("exceeded") else '<span class="na">—</span>')
                            for m in refs], num=(2, 3), raw=(4,)))
        out.append(H.cards([
            ("기준 초과 요소", f'{H.fmt(sr.get("n_exceed"))} / {H.fmt(sr.get("n_elems"))}'
                          f'<div class="small muted">{H.pct(None if sr.get("frac_exceed") is None else 100 * sr["frac_exceed"])}'
                          f' (valid 대비 {H.pct(None if sr.get("frac_exceed_valid") is None else 100 * sr["frac_exceed_valid"])})</div>'),
            ("|오차| P99", H.pct(sr.get("p99_err_pct"))),
            ("소성 영역 (epsp>0)", "—" if pl is None else f'{H.fmt(pl.get("n_plastic"))} ({H.pct(100 * pl["frac_plastic"])})'
                                 f'<div class="small muted">초과 ∩ 소성 {H.fmt(pl.get("n_exceed_plastic"))}</div>')]))
    out.append(_sec_disp(v))
    out.append("<h3>hotspot (t* 에서 상승 중인 H 요소)</h3>"
               + (H.table(["rank", "elem", "ε_rad", "ε_val", "오차 %"], hs, num=(0, 1, 2, 3, 4)) if hs else _none("비교한 hotspot 없음")))
    if ex:
        out.append("<h3>비교 제외 hotspot</h3>" + H.table(["rank", "elem", "사유"], ex, num=(0, 1)))
    return "".join(out)


def _field_summary(c: _Case) -> str:
    v = c.val or {}
    fs = v.get("field")
    if not fs:
        return _none("전 요소 비교 자료 없음 — validate 단계를 다시 실행")
    mx = fs.get("max") or {}
    ae = fs.get("abs_err_pct") or {}
    fw = fs.get("frac_within") or {}
    cr = fs.get("criteria") or {}
    card = H.cards([
        ("max ε_rad (t* 상승 요소)", H.fmt(mx.get("eps_rad")) + f'<div class="small muted">elem {H.esc(mx.get("elem_id", "—"))}</div>'),
        ("같은 요소 ε_esl", H.fmt(mx.get("eps_esl"))),
        ("최대변형률 오차", H.pct(mx.get("err_pct")) + f'<div class="small muted">참고 기준 ≤ {H.fmt(cr.get("max_err_pct_max"))}%</div>'),
        ("ESL 전체 최대 ε", H.fmt(mx.get("eps_esl_max")) + f'<div class="small muted">elem {H.esc(mx.get("eps_esl_max_elem_id", "—"))}, '
                                                         f'최대끼리 {H.pct(mx.get("peak_err_pct"))}</div>'),
        ("|오차| P90", H.pct(ae.get("p90")) + f'<div class="small muted">참고 기준 ≤ {H.fmt(cr.get("p90_err_max"))}%</div>'),
        ("valid / 전체", f'{H.fmt(fs.get("n_valid"))} / {H.fmt(fs.get("n_elems"))}'),
    ])
    q = H.table(["평균", "P50", "P90", "P95", "최대", "≤5%", "≤10%", "≤20%"],
                [(H.pct(ae.get("mean")), H.pct(ae.get("p50")), H.pct(ae.get("p90")), H.pct(ae.get("p95")),
                  H.pct(ae.get("max")),
                  *[("—" if not fw else f"{100 * fw.get(k, 0):.1f}%") for k in ("5", "10", "20")])],
                num=range(8), raw=range(8))
    cnt = H.table(["사유", "요소 수", "설명"],
                  [(name, fs.get(f"n_{name.lower()}", 0), (fs.get("reason_text") or F.REASON_TEXT).get(name, ""))
                   for name in F.REASONS.values()], num=(1,))
    d = fs.get("definition") or {}
    defs = (f'<p class="small muted">오차 = (ε_esl − ε_rad)/ε_rad. ε_rad = t* 프레임 Max_Strain ε_eq(같은 공식), '
            f'ε_esl = {H.esc(d.get("eps_esl", "검증 해 막 변형률 ε_eq"))}. 상승 중 = {H.esc(d.get("rising", ""))}; '
            f'valid = 상승 중 ∧ ε_rad ≥ {H.fmt(fs.get("min_rel"))}·max ε_rad. 직전 프레임 출처: '
            f'{H.esc(fs.get("prev_source", "—"))} (frame {H.esc(fs.get("prev_frame_index", "—"))}).</p>')
    return card + q + defs + "<h3>요소 분류</h3>" + cnt


def _map_data(c: _Case, max_points: int, hot: list[dict], supports_xyz: list) -> dict | None:
    z = c.field
    if not z:
        return None
    c2 = np.asarray(z["centroid2d"], dtype=np.float64)
    er = np.asarray(z["eps_rad"], dtype=np.float64)
    ee = np.asarray(z["eps_esl"], dtype=np.float64)
    rel = np.asarray(z["rel_err"], dtype=np.float64)
    valid = np.asarray(z["valid"], dtype=bool)
    reason = np.asarray(z["reason"], dtype=np.int64)
    rising = np.asarray(z["rising"], dtype=bool)
    idx, cell = F.downsample(c2[:, 0], c2[:, 1], er, valid, max_points)
    xr = [float(c2[:, 0].min()), float(c2[:, 0].max())]
    yr = [float(c2[:, 1].min()), float(c2[:, 1].max())]
    span = max(xr[1] - xr[0], yr[1] - yr[0], 1e-9)
    step = 10.0 ** np.floor(np.log10(span / 2000.0)) if span > 0 else 0.01
    shown = rising & (reason != F.R_EXCLUDED)
    vmax = max(float(np.max(er[shown], initial=0.0)), float(np.max(ee[shown], initial=0.0)))
    if vmax <= 0:
        vmax = float(np.nanmax(np.r_[er, ee, 1e-30]))
    crit = ((c.val or {}).get("field") or {}).get("criteria") or {}
    err_r = float(max(crit.get("p90_err_max") or 20.0, 1e-6))
    o, e1, e2 = (np.asarray(z[k], dtype=np.float64) for k in ("plane_origin", "plane_e1", "plane_e2"))

    def proj(p):
        q = np.asarray(p, dtype=np.float64) - o
        return [float(q @ e1), float(q @ e2)]

    m = ((c.val or {}).get("field") or {}).get("max") or {}
    d = {"x": H.round_fixed(c2[idx, 0], step), "y": H.round_fixed(c2[idx, 1], step),
         "id": [int(v) for v in np.asarray(z["elem_id"])[idx]],
         "rad": H.round_sig(er[idx]), "esl": H.round_sig(ee[idx]), "err": H.round_sig(100.0 * rel[idx], 3),
         "st": [int(v) for v in reason[idx]], "xr": xr, "yr": yr, "vmax": vmax, "errR": err_r,
         "n_total": int(er.size), "n_shown": int(idx.size), "cell": None if cell is None else list(cell),
         "hot": [{"p": proj(h["centroid"]), "label": str(h["rank"]), "id": h["elem_id"]} for h in hot],
         "sup": [{"p": proj(x), "label": str(nid)} for nid, x in supports_xyz],
         "max": None if not m or m.get("xi") is None else {"p": [m["xi"], m["eta"]], "id": m.get("elem_id")}}
    if cell is None:
        # 표시 크기: QUAD sqrt(A), TRIA sqrt(2A)(같은 사각 칸의 삼각형 두 개가 칸을 덮도록) × 1.12
        sz = np.asarray(z["elem_size"], dtype=np.float64)
        et = (c.model or {}).get("elem_type")
        if et is not None and np.size(et) == sz.size:
            sz = np.where(np.asarray(et) == 3, sz * np.sqrt(2.0), sz)
        d["sz"] = H.round_sig(sz[idx] * 1.12, 2)
    return d


def _sec_overlay(c: _Case, mapd: dict | None) -> str:
    if mapd is None:
        return _none("전 요소 비교 자료(05_val/compare_field.npz) 없음 — validate 단계를 다시 실행")
    ds = ("" if mapd["cell"] is None else
          f' 요소 {mapd["n_total"]}개 → 2D 셀 격자 다운샘플 {mapd["n_shown"]}개(셀마다 valid 우선·ε_rad 최대 요소).')
    return f"""<p class="small muted">PCA 평면(ξ, η) 투영 요소 중심 컨투어. Radioss·ESL 은 공통 색 범위 [0, {H.fmt(mapd['vmax'])}],
오차는 ±{H.fmt(mapd['errR'])}%(|P90| 기준) 고정 범위. 회색 = 비교 불가(t* 에서 상승 중 아님 등 — 오차 레이어는 valid 아닌 요소 전부).
○ 숫자 = hotspot 순위, 빨간 조준 원 = 최대변형률 요소, △ = 3-2-1 지지점.{H.esc(ds)}</p>
<div class="ctrl" id="map-ctrl">
<span>레이어</span>
<label><input type="radio" name="lay" value="rad" checked> Radioss ε</label>
<label><input type="radio" name="lay" value="esl"> ESL ε</label>
<label><input type="radio" name="lay" value="err"> 오차 %</label>
<label><input type="radio" name="lay" value="ovl"> 겹치기</label>
<label>Radioss <input type="range" id="ovl-op" min="0" max="100" value="50" disabled aria-label="ESL 불투명도"> ESL
<span id="ovl-opv">50%</span></label>
<label><input type="checkbox" id="mk-on" checked> 표식</label>
</div>
<div id="mapw" style="position:relative;width:100%"><canvas id="cv0"></canvas><canvas id="cv1"></canvas><canvas id="cv2"></canvas></div>
<div id="legend" class="small" style="margin-top:6px"></div>
<div id="readout" class="small muted" style="min-height:1.5em">요소 위에 마우스를 올리면 값 표시</div>"""


def _sec_section(c: _Case) -> str:
    if not c.field or "sec_xi_s" not in c.field:
        return _none("단면선 자료 없음")
    run = ((c.val or {}).get("full_solve") or {}).get("run")
    extra = "" if run else " (S5 전체 재해석 생략 → ESL 변위 = u_rel 이므로 두 선이 겹친다)"
    return f"""<p class="small muted">단면 요소(정규화 좌표 ξ 또는 η = 0.5 ± 띠)의 면외(PCA n) 좌표: 초기 n0, Radioss n0 + k·w_rel,
ESL n0 + k·w_val (w = 미소 강체 제거 변위의 면외 성분, 요소 평균·구간 평균). k = 변형 배율.{H.esc(extra)}</p>
<div class="ctrl">
<label><input type="radio" name="sax" value="xi" checked> ξ = 0.5 단면(η 방향)</label>
<label><input type="radio" name="sax" value="eta"> η = 0.5 단면(ξ 방향)</label>
<label>배율 k <input type="range" id="sec-k" min="0" max="4" step="0.01" value="0" aria-label="변형 배율"> <span id="sec-kv">1</span></label>
</div>
<div id="sec-plot"></div>
<p class="small"><span style="color:var(--s3)">┅ 초기</span> · <span style="color:var(--s1)">━ Radioss(u_rel)</span> ·
<span style="color:var(--s2)">━ ESL(u_val)</span></p>"""


def _sec_top(c: _Case) -> str:
    fs = (c.val or {}).get("field")
    if not fs:
        return _none()

    def rows(lst):
        return [(i + 1, r["elem_id"], r["eps_rad"], r["eps_esl"], H.pct(r["err_pct"])) for i, r in enumerate(lst)]

    hd = ["#", "elem", "ε_rad", "ε_esl", "오차 %"]
    return (f"<h3>ε_rad 상위 {len(fs.get('top') or [])} (valid)</h3>" + H.table(hd, rows(fs.get("top") or []),
                                                                                 num=(0, 1, 2, 3, 4), raw=(4,))
            + f"<h3>|오차| 상위 {len(fs.get('worst') or [])} (valid)</h3>"
            + H.table(hd, rows(fs.get("worst") or []), num=(0, 1, 2, 3, 4), raw=(4,)))


def _sec_hist(c: _Case) -> str:
    fs = (c.val or {}).get("field")
    if not fs or not (fs.get("hist") or {}).get("counts"):
        return _none("valid 요소 없음")
    h = fs["hist"]
    p90 = (fs.get("criteria") or {}).get("p90_err_max")
    crit = [] if p90 is None else [-float(p90), float(p90)]
    note = (f'<p class="small muted">valid 요소 {h["n"]}개의 부호 있는 오차(ESL − Radioss)/Radioss, 범위 ±{H.fmt(h["range_pct"])}%'
            + (f' (범위 밖 {h["n_clipped"]}개는 끝 막대에 포함)' if h.get("n_clipped") else "")
            + ". 점선 = ±P90 기준.</p>")
    return H.histogram_svg(h["edges"], h["counts"], xlabel="오차 % (ε_esl − ε_rad)/ε_rad", crit=crit) + note


def _sec_notes(c: _Case) -> str:
    fs = (c.val or {}).get("field") or {}
    note = fs.get("note") or F.SEMANTIC_NOTE
    return (f'<div class="note">{H.esc(note)}</div>'
            '<div class="note">Radioss 값은 요소별 max-hold(누적 최대)이므로 t* 에서 상승 중인 요소만 순간값과 같다 — '
            '그 외 요소(회색)는 다른 시점의 최대값을 유지 중이라 비교하지 않는다.</div>'
            '<div class="note">한계: 선형 ESL(소성·접촉 비선형 무시), 쉘 막 변형률(중립면) 기준, 판정 기준은 임시값(설정).</div>')


# ====================================================================== JS (소량, inline)
JS = r"""
(function(){
var el=document.getElementById('esl-data');if(!el)return;var D=JSON.parse(el.textContent);
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()||'#999';}
function nice(lo,hi,n){if(!(hi>lo)){hi=lo+(Math.abs(lo)||1);}var r=(hi-lo)/n,p=Math.pow(10,Math.floor(Math.log10(r))),
 st=[1,2,2.5,5,10].map(function(m){return m*p;}).filter(function(s){return s>=r;})[0],t=Math.ceil(lo/st-1e-9)*st,o=[];
 for(;t<=hi+st*1e-9;t+=st)o.push(Math.abs(t)<st*1e-9?0:t);return o;}
function f3(v){if(v===null||v===undefined||!isFinite(v))return '—';var a=Math.abs(v);
 return (a!==0&&(a<1e-3||a>=1e6))?v.toExponential(3):(+v.toPrecision(4)).toString();}
var VIR=[[68,1,84],[72,40,120],[62,74,137],[49,104,142],[38,130,142],[31,158,137],[53,183,121],[109,205,89],[180,222,44],[253,231,37]];
var DIV=[[49,54,149],[69,117,180],[145,191,219],[240,228,140],[252,141,89],[215,48,39],[165,0,38]];
function lerp(c,t){t=Math.max(0,Math.min(1,t));var s=t*(c.length-1),i=Math.min(Math.floor(s),c.length-2),f=s-i,a=c[i],b=c[i+1];
 return 'rgb('+Math.round(a[0]+(b[0]-a[0])*f)+','+Math.round(a[1]+(b[1]-a[1])*f)+','+Math.round(a[2]+(b[2]-a[2])*f)+')';}
function grad(c){return 'linear-gradient(90deg,'+c.map(function(x,i){return 'rgb('+x.join(',')+') '+(100*i/(c.length-1)).toFixed(0)+'%';}).join(',')+')';}
var M=D.map;
if(M){
 var N=M.x.length,wrap=document.getElementById('mapw'),cv=[0,1,2].map(function(i){var c=document.getElementById('cv'+i);
  c.style.position=i?'absolute':'relative';c.style.left='0';c.style.top='0';c.style.width='100%';c.style.display='block';return c;});
 var layer='rad',op=0.5,mk=true,geo=null;
 var READ={0:'비교 대상',1:'HOLD(상승 중 아님)',2:'LOW(작은 변형률)',3:'EXCLUDED',4:'NO_PREV'};
 function col(L,i){var st=M.st[i];
  if(L==='err'){if(st!==0||M.err[i]===null)return null;return lerp(DIV,(M.err[i]/M.errR+1)/2);}
  var v=L==='rad'?M.rad[i]:M.esl[i];if(st===1||st===3||st===4||v===null)return null;return lerp(VIR,v/M.vmax);}
 function setup(){var w=wrap.clientWidth||800,dx=M.xr[1]-M.xr[0]||1,dy=M.yr[1]-M.yr[0]||1,pad=20,
  h=Math.max(240,Math.min(680,(w-2*pad)*dy/dx+2*pad)),s=Math.min((w-2*pad)/dx,(h-2*pad)/dy),
  ox=(w-s*dx)/2,oy=(h-s*dy)/2,r=window.devicePixelRatio||1;
  cv.forEach(function(c){c.width=Math.round(w*r);c.height=Math.round(h*r);c.style.height=h+'px';});
  geo={w:w,h:h,s:s,r:r,X:function(x){return ox+(x-M.xr[0])*s;},Y:function(y){return h-oy-(y-M.yr[0])*s;}};}
 function draw(c,L){var g=c.getContext('2d'),G=geo,na=css('--na');g.setTransform(G.r,0,0,G.r,0,0);g.clearRect(0,0,G.w,G.h);
  for(var i=0;i<N;i++){var cx=G.X(M.x[i]),cy=G.Y(M.y[i]),ww,hh;
   if(M.cell){ww=M.cell[0]*G.s;hh=M.cell[1]*G.s;}else{ww=hh=(M.sz[i]||0)*G.s;}
   ww=Math.max(ww,1.2);hh=Math.max(hh,1.2);var k=col(L,i);g.fillStyle=k||na;g.fillRect(cx-ww/2,cy-hh/2,ww,hh);}}
 function marks(){var c=cv[2],g=c.getContext('2d'),G=geo;g.setTransform(G.r,0,0,G.r,0,0);g.clearRect(0,0,G.w,G.h);if(!mk)return;
  var fg=css('--fg'),bg=css('--bg'),bad=css('--bad');g.lineWidth=1.6;g.font='11px system-ui,sans-serif';
  if(M.max){var x=G.X(M.max.p[0]),y=G.Y(M.max.p[1]);g.strokeStyle=bad;g.lineWidth=2.6;g.beginPath();g.arc(x,y,13,0,6.2832);g.stroke();
   g.beginPath();g.moveTo(x-17,y);g.lineTo(x-11,y);g.moveTo(x+11,y);g.lineTo(x+17,y);g.moveTo(x,y-17);g.lineTo(x,y-11);g.moveTo(x,y+11);g.lineTo(x,y+17);g.stroke();g.lineWidth=1.6;}
  (M.sup||[]).forEach(function(s){var x=G.X(s.p[0]),y=G.Y(s.p[1]);g.beginPath();g.moveTo(x,y-8);g.lineTo(x-7,y+5);g.lineTo(x+7,y+5);g.closePath();
   g.fillStyle=bg;g.fill();g.strokeStyle=fg;g.stroke();});
  (M.hot||[]).forEach(function(h){var x=G.X(h.p[0]),y=G.Y(h.p[1]);g.beginPath();g.arc(x,y,8,0,6.2832);g.fillStyle=bg;g.fill();
   g.strokeStyle=fg;g.stroke();g.fillStyle=fg;g.textAlign='center';g.textBaseline='middle';g.fillText(h.label,x,y+0.5);});
}
 function legend(){var L=layer,h,na='<span style="display:inline-block;width:14px;height:10px;background:var(--na);vertical-align:middle"></span> 비교 불가';
  if(L==='err'){h='오차 % <span style="display:inline-block;width:200px;height:10px;vertical-align:middle;background:'+grad(DIV)+'"></span> '
   +'−'+f3(M.errR)+' … 0 … +'+f3(M.errR)+'% (범위 밖은 끝 색) · '+na;}
  else{h=(L==='ovl'?'Radioss / ESL (공통 범위) ':'ε_eq ')+'<span style="display:inline-block;width:200px;height:10px;vertical-align:middle;background:'
   +grad(VIR)+'"></span> 0 … '+f3(M.vmax)+' · '+na;}
  document.getElementById('legend').innerHTML=h;}
 function render(){setup();var L=layer==='ovl'?'rad':layer;draw(cv[0],L);
  if(layer==='ovl'){draw(cv[1],'esl');cv[1].style.opacity=op;cv[1].style.visibility='visible';}else{cv[1].style.visibility='hidden';}
  marks();legend();}
 document.querySelectorAll('input[name=lay]').forEach(function(r){r.onchange=function(){layer=this.value;
  document.getElementById('ovl-op').disabled=(layer!=='ovl');render();};});
 var opr=document.getElementById('ovl-op');opr.oninput=function(){op=this.value/100;document.getElementById('ovl-opv').textContent=this.value+'%';
  cv[1].style.opacity=op;};
 document.getElementById('mk-on').onchange=function(){mk=this.checked;marks();};
 cv[2].addEventListener('mousemove',function(ev){var b=cv[2].getBoundingClientRect(),mx=ev.clientX-b.left,my=ev.clientY-b.top,best=-1,bd=144;
  for(var i=0;i<N;i++){var dx=geo.X(M.x[i])-mx,dy=geo.Y(M.y[i])-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=i;}}
  var o=document.getElementById('readout');if(best<0){o.textContent='';return;}
  o.textContent='요소 '+M.id[best]+': ε_rad='+f3(M.rad[best])+', ε_esl='+f3(M.esl[best])+', 오차='+(M.err[best]===null?'—':f3(M.err[best])+'%')
   +' · '+READ[M.st[best]]+' (ξ='+f3(M.x[best])+', η='+f3(M.y[best])+')';});
 var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(render,120);});
 window.addEventListener('esl-theme',render);render();
}
var S=D.sec;
if(S){var ax='xi',kexp=0,box=document.getElementById('sec-plot');
 function sp(){var d=S[ax];if(!d||!d.s.length){box.innerHTML='<p class="muted">단면 요소 없음</p>';return;}
  var k=Math.pow(10,kexp),n=d.s.length,ys=[d.n0,d.n0.map(function(v,i){return v+k*d.wr[i];}),d.n0.map(function(v,i){return v+k*d.wv[i];})],
  W=760,Hh=300,L=64,R=12,T=10,B=38,pw=W-L-R,ph=Hh-T-B,x0=Math.min.apply(null,d.s),x1=Math.max.apply(null,d.s),
  all=[].concat(ys[0],ys[1],ys[2]),y0=Math.min.apply(null,all),y1=Math.max.apply(null,all);
  if(!(y1>y0)){y0-=1;y1+=1;}var m=(y1-y0)*0.08;y0-=m;y1+=m;if(!(x1>x0))x1=x0+1;
  var X=function(v){return L+(v-x0)/(x1-x0)*pw;},Y=function(v){return T+ph-(v-y0)/(y1-y0)*ph;},o=[];
  o.push('<svg class="chart" viewBox="0 0 '+W+' '+Hh+'" role="img" aria-label="단면선">');
  nice(y0,y1,5).forEach(function(t){o.push('<line class="gr" x1="'+L+'" x2="'+(L+pw)+'" y1="'+Y(t).toFixed(1)+'" y2="'+Y(t).toFixed(1)+'"/><text x="'+(L-4)+'" y="'+(Y(t)+4).toFixed(1)+'" text-anchor="end">'+f3(t)+'</text>');});
  nice(x0,x1,6).forEach(function(t){if(t>=x0&&t<=x1)o.push('<text x="'+X(t).toFixed(1)+'" y="'+(T+ph+14)+'" text-anchor="middle">'+f3(t)+'</text>');});
  o.push('<path class="ax" d="M'+L+','+T+'V'+(T+ph)+'H'+(L+pw)+'"/>');
  ['s3','sr','se'].forEach(function(c,j){o.push('<path class="'+c+'" d="M'+d.s.map(function(s,i){return X(s).toFixed(1)+','+Y(ys[j][i]).toFixed(1);}).join('L')+'"/>');});
  o.push('<text x="'+(L+pw/2)+'" y="'+(Hh-6)+'" text-anchor="middle">'+(ax==='xi'?'η (PCA 평면 실좌표)':'ξ (PCA 평면 실좌표)')+'</text>');
  o.push('<text x="12" y="'+(T+ph/2)+'" text-anchor="middle" transform="rotate(-90 12 '+(T+ph/2)+')">면외 n</text></svg>');
  box.innerHTML=o.join('');document.getElementById('sec-kv').textContent=f3(k);}
 var kr=document.getElementById('sec-k');kexp=+(S.k0exp||0);kr.value=kexp;
 kr.oninput=function(){kexp=+this.value;sp();};
 document.querySelectorAll('input[name=sax]').forEach(function(r){r.onchange=function(){ax=this.value;sp();};});sp();}
})();
"""


def _section_data(c: _Case) -> dict | None:
    z = c.field
    if not z or "sec_xi_s" not in z:
        return None
    out: dict[str, Any] = {}
    wmax, span = 0.0, 0.0
    for a in ("xi", "eta"):
        s = np.asarray(z[f"sec_{a}_s"], dtype=np.float64)
        out[a] = {"s": H.round_sig(s, 6), "n0": H.round_sig(z[f"sec_{a}_n0"], 6),
                  "wr": H.round_sig(z[f"sec_{a}_w_rel"], 5), "wv": H.round_sig(z[f"sec_{a}_w_val"], 5)}
        if s.size:
            wmax = max(wmax, float(np.max(np.abs(np.r_[z[f"sec_{a}_w_rel"], z[f"sec_{a}_w_val"]]))))
            span = max(span, float(s.max() - s.min()))
    # 기본 배율: 최대 면외 변위 × k ≈ 단면 길이의 5% (1 ~ 10^4)
    k0 = 1.0 if wmax <= 0 or span <= 0 else min(max(0.05 * span / wmax, 1.0), 1e4)
    out["k0exp"] = round(float(np.log10(k0)), 2)
    return out


# ====================================================================== 조립
def build_case_report(case_dir: str, record: dict | None = None, max_points: int = 20000, top_forces: int = 20,
                      title: str | None = None) -> tuple[str, dict]:
    """HTML 문자열과 요약 dict({sections, missing, n_points, downsampled, verdict})."""
    c = _Case(case_dir, record)
    meta = c.meta or {}
    v = c.val or {}
    hot = [h for h in v.get("hotspots") or [] if h.get("centroid") is not None]
    sup_xyz = [(s["node_id"], s["x0"]) for s in (c.support or {}).get("supports") or []]
    mapd = _map_data(c, max_points, hot, sup_xyz)
    secd = _section_data(c)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    t = title or f"ESL Case 보고서 — {meta.get('part_title', os.path.basename(os.path.abspath(case_dir)))}"
    ss = _state_summary(c)
    parts = [
        ("inputs", "1. 입력 요약", _sec_inputs(c)),
        *([("cumulative", "1-1. 누적 낙하 입력", _sec_cumulative(c, ss))] if ss else []),
        ("tstar", "2. t* — max-hold 곡선(두 지표)", _sec_tstar(c)),
        ("supports", "3. 3-2-1 지지점", _sec_supports(c)),
        ("feq", "4. 등가하중 F_eq", _sec_feq(c, top_forces)),
        ("validation", "5. 검증 요약", _sec_validation(c)),
        ("field", "6. ESL 재현 정확도 — 전 요소 비교 (참고 — 판정 아님)", _field_summary(c)),
        ("overlay", "7. 겹쳐보기 — Radioss ε / ESL ε / 오차 %", _sec_overlay(c, mapd)),
        ("section", "8. 변형 단면선 겹치기", _sec_section(c)),
        ("top", "9. 상위 요소 표", _sec_top(c)),
        ("hist", "10. 오차 히스토그램", _sec_hist(c)),
        ("notes", "11. 의미·한계", _sec_notes(c)),
    ]
    toc = '<nav class="toc">' + "".join(f'<a href="#{i}">{H.esc(n)}</a>' for i, n, _ in parts) + "</nav>"
    head = (f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">'
            f'<div><h1>{H.esc(t)}</h1><p class="muted small">생성 {H.esc(now)} · esl {H.esc(esl.__version__)}'
            f' · 판정 {status_badge(v)}'
            + (f' · tag {H.esc((c.summ or {}).get("tag"))}' if (c.summ or {}).get("tag") else "")
            + '</p></div><button type="button" class="tg" id="theme-btn">테마: 자동</button></div>')
    if c.missing:
        head += (f'<p class="small muted">없는 산출물(해당 절은 "자료 없음"): '
                 f'{H.esc(", ".join(sorted(set(c.missing))))}</p>')
    body = head + toc + "\n".join(H.section(i, n, inner) for i, n, inner in parts)
    data = {"map": mapd, "sec": secd}
    doc = H.page(t, body, script=JS, data=data, version=esl.__version__)
    info = {"sections": [i for i, _, _ in parts], "missing": sorted(set(c.missing)),
            "n_points": None if mapd is None else mapd["n_shown"],
            "n_elems": None if mapd is None else mapd["n_total"],
            "downsampled": None if mapd is None else mapd["cell"] is not None, "verdict": v.get("verdict"),
            "status": status_of(v)}
    return doc, info


def write_case_report(case_dir: str, out_path: str | None = None, **kw) -> dict:
    """보고서를 써서 요약 반환(pipeline 밖에서 직접 쓸 때). out_path 기본 <case>/07_report/report.html."""
    doc, info = build_case_report(case_dir, **kw)
    out_path = out_path or os.path.join(case_dir, D_REPORT, REPORT_NAME)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    info.update(path=out_path, bytes=os.path.getsize(out_path))
    return info
