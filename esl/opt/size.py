"""S2 크기 규칙 (계약 esl_opt_run.md OR-D-7, §7.1). 화면(API 응답)·POST /opt/runs·OPT_PREP 가 같은 함수를 쓴다.

입력 행: ``{entry_id, inch|None, L_xi, L_eta, grid?: (nx, ny)}`` (라이브러리 ``model.inch``·``frame.L_xi/L_eta``).

- 기준 = 첫 행. 인치: ``require_inch`` 이면 양쪽 다 있을 때 같아야 함(다르면 오류), 한쪽이라도 없으면 치수만 + 경고
  ``INCH_UNKNOWN``. ``require_inch`` 가 거짓이면 인치를 보지 않는다.
- 치수: ``|L − L_기준| / L_기준 ≤ tol_rel`` (ξ·η 각각). 인치 정규화 없음(none 고정).
- 템플릿: ESL 치수 중앙값 대비 ``|L_t − med| / med ≤ plate_tol_rel``. 템플릿 인치는 선택 — 있으면(그리고 ESL 인치가
  있으면) 같아야 함, 없으면 치수만.
- 격자(nx, ny)가 섞이면 ``GRID_MISMATCH``.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError


def _rel(a: float, b: float) -> float:
    return abs(float(a) - float(b)) / abs(float(b)) if float(b) != 0 else float("inf")


def check_entries(rows: list[dict], size_cfg: dict) -> dict:
    """반환 {ok, base, rows:[{entry_id, ok, d_xi, d_eta, inch_ok, reasons[]}], errors[], warnings[]}."""
    tol = float(size_cfg["tol_rel"])
    req_inch = bool(size_cfg.get("require_inch", True))
    if not rows:
        raise EslError("INPUT_INVALID", "ESL 이 없음")
    b = rows[0]
    out_rows, errors, warns = [], [], []
    grids = {tuple(r["grid"]) for r in rows if r.get("grid") is not None}
    if len(grids) > 1:
        errors.append({"code": "GRID_MISMATCH", "message": f"정규화 격자가 섞임: {sorted(grids)}"})
    for r in rows:
        dx, de = _rel(r["L_xi"], b["L_xi"]), _rel(r["L_eta"], b["L_eta"])
        reasons = []
        inch_ok = None
        if req_inch:
            if r.get("inch") is None or b.get("inch") is None:
                if r is not b or r.get("inch") is None:
                    w = f"{r['entry_id']}: 인치 정보 없음 — 치수만 비교(INCH_UNKNOWN)"
                    if w not in warns:
                        warns.append(w)
            else:
                inch_ok = int(r["inch"]) == int(b["inch"])
                if not inch_ok:
                    reasons.append(f"인치 {r['inch']} ≠ 기준 {b['inch']}")
        if dx > tol:
            reasons.append(f"가로 L_xi {r['L_xi']:.1f} 기준 대비 {dx * 100:.2f} % > {tol * 100:g} %")
        if de > tol:
            reasons.append(f"세로 L_eta {r['L_eta']:.1f} 기준 대비 {de * 100:.2f} % > {tol * 100:g} %")
        out_rows.append({"entry_id": r["entry_id"], "ok": not reasons, "d_xi": dx, "d_eta": de, "inch_ok": inch_ok,
                         "reasons": reasons})
    errors += [{"code": "SIZE_MISMATCH", "entry_id": r["entry_id"], "message": "; ".join(r["reasons"])}
               for r in out_rows if not r["ok"]]
    med = {"L_xi": float(np.median([r["L_xi"] for r in rows])), "L_eta": float(np.median([r["L_eta"] for r in rows]))}
    inches = sorted({int(r["inch"]) for r in rows if r.get("inch") is not None})
    return {"ok": not errors, "base": b["entry_id"], "rows": out_rows, "errors": errors, "warnings": warns,
            "median": med, "inches": inches}


def check_template(rows: list[dict], template: dict, size_cfg: dict) -> dict:
    """ESL 행 + 템플릿 {inch|None, L_xi, L_eta} → {ok, d_xi, d_eta, inch_ok, reasons[], warnings[]}."""
    tol = float(size_cfg["plate_tol_rel"])
    req_inch = bool(size_cfg.get("require_inch", True))
    med = {"L_xi": float(np.median([r["L_xi"] for r in rows])), "L_eta": float(np.median([r["L_eta"] for r in rows]))}
    dx, de = _rel(template["L_xi"], med["L_xi"]), _rel(template["L_eta"], med["L_eta"])
    reasons, warns = [], []
    inch_ok = None
    t_inch = template.get("inch")
    if req_inch and t_inch is not None:
        e_inch = sorted({int(r["inch"]) for r in rows if r.get("inch") is not None})
        if e_inch:
            inch_ok = e_inch == [int(t_inch)]
            if not inch_ok:
                reasons.append(f"템플릿 인치 {t_inch} ≠ ESL 인치 {e_inch}")
        else:
            warns.append("ESL 인치 정보 없음 — 템플릿과 치수만 비교(INCH_UNKNOWN)")
    if dx > tol:
        reasons.append(f"템플릿 가로 {template['L_xi']:.1f} vs ESL 중앙값 {med['L_xi']:.1f}: {dx * 100:.2f} % > {tol * 100:g} %")
    if de > tol:
        reasons.append(f"템플릿 세로 {template['L_eta']:.1f} vs ESL 중앙값 {med['L_eta']:.1f}: {de * 100:.2f} % > {tol * 100:g} %")
    return {"ok": not reasons, "d_xi": dx, "d_eta": de, "inch_ok": inch_ok, "reasons": reasons, "warnings": warns,
            "median": med}


def assert_ok(rows: list[dict], size_cfg: dict, template: dict | None = None) -> dict:
    """세 검사 지점 공통: 실패 시 SIZE_MISMATCH / GRID_MISMATCH. 반환 {entries, template, warnings}."""
    r = check_entries(rows, size_cfg)
    g = [e for e in r["errors"] if e["code"] == "GRID_MISMATCH"]
    if g:
        raise EslError("GRID_MISMATCH", g[0]["message"])
    if not r["ok"]:
        raise EslError("SIZE_MISMATCH", "크기가 다른 ESL: " + "; ".join(f"{e['entry_id']}: {e['message']}"
                                                                    for e in r["errors"][:10]))
    t = None
    if template is not None:
        t = check_template(rows, template, size_cfg)
        if not t["ok"]:
            raise EslError("SIZE_MISMATCH", "템플릿 크기 불일치: " + "; ".join(t["reasons"]))
    return {"entries": r, "template": t, "warnings": r["warnings"] + (t["warnings"] if t else [])}
