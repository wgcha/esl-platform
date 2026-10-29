"""OptiStruct 출력(.out) 해석 (계약 esl_opt_run.md §8.1·§8.3, §9 history.csv).

패턴은 모두 설정 ``opt_run.solve.*``(기본값 ``esl.opt.DEFAULTS``). 실제 .out 형식 확인은 V-OR-R1(실기).

- ``parse_out(text, solve_cfg)`` → {iterations, last_iteration, converged, objective[(it, value)],
  compliance{it: {subcase: C}}, errors[], license: bool, memory: bool}
  · 반복 = ``iteration_pattern`` 의 마지막 번호, 반복 블록마다 ``objective_pattern``·``compliance_pattern``(subcase, 값).
- ``classify(exit_code, text, solve_cfg, have_files)`` → None(성공) | OS_LICENSE_UNAVAILABLE(재시도 대상) |
  SOLVER_OUT_OF_MEMORY | OS_SOLVE_FAILED.
- ``error_blocks(text, solve_cfg)`` → ERROR 블록(오류 줄 + 다음 상세 줄 ``error_detail_lines`` 줄 + 앞의
  "See next message about line N from file" 문맥: 덱 줄 번호·파일·카드·연속 줄 번호·인용 덱 줄). 같은 블록(.out 끝
  요약에 반복)은 한 번만. ``error_summary(blocks)`` → failure_message 용 한 줄씩.
- ``history(parsed, selection)`` → history.csv 행: iteration, objective(abs: max C_k/C_ref, rel: max C_k/C_k⁰),
  케이스별 C_k·C_k/C_k⁰ (C_k⁰ = 자체 솔버 초기 컴플라이언스).
"""
from __future__ import annotations

import csv
import io
import re

from esl.errors import EslError


def _f(s: str) -> float:
    return float(s.upper().replace("D", "E"))


def parse_out(text: str, solve_cfg: dict) -> dict:
    it_re = re.compile(solve_cfg["iteration_pattern"])
    ob_re = re.compile(solve_cfg["objective_pattern"])
    cp_re = re.compile(solve_cfg["compliance_pattern"])
    marks = [(m.start(), int(m.group(1))) for m in it_re.finditer(text)]
    blocks = []
    for k, (pos, it) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        blocks.append((it, text[pos:end]))
    objective, compliance = [], {}
    for it, blk in blocks:
        m = ob_re.search(blk)
        if m:
            objective.append((it, _f(m.group(1))))
        cs = {int(a): _f(b) for a, b in cp_re.findall(blk)}
        if cs:
            compliance[it] = cs
    errors = []
    for p in solve_cfg["error_patterns"]:
        for m in re.finditer(p, text):
            ln_end = text.find("\n", m.end())
            errors.append(text[m.start(): ln_end if ln_end >= 0 else len(text)].strip()[:300])
    eblocks = error_blocks(text, solve_cfg)
    lic = any(re.search(p, text) for p in solve_cfg["license_patterns"])
    mem = any(re.search(p, text) for p in solve_cfg.get("memory_patterns") or [])
    conv = any(re.search(p, text) for p in solve_cfg["converged_patterns"])
    its = [it for it, _ in blocks]
    return {"iterations": len(set(its)), "last_iteration": max(its) if its else None, "converged": conv,
            "objective": objective, "compliance": compliance, "errors": errors[:20], "error_blocks": eblocks[:20],
            "license": lic, "memory": mem}


ERROR_DEFAULTS = {
    "error_detail_lines": 4,
    "error_context_lines": 8,
    "error_context_pattern": r"(?i)See next message about line\s+(\d+)",
    "error_card_pattern": (r"(?i)\(this is\s+(?:continuation line\s+(\d+)\s+of\s+)?([A-Z][A-Z0-9_]*)\s*,\s*([^\s)]+)"
                           r"\s+bulk data\)"),
    "error_code_pattern": r"ERROR\s*#\s*(\d+)",
}


def _ecfg(solve_cfg: dict, k: str):
    v = solve_cfg.get(k)
    return ERROR_DEFAULTS[k] if v is None else v


def error_blocks(text: str, solve_cfg: dict) -> list[dict]:
    """ERROR 줄마다 {error, code, detail[], context[], deck_line_no, deck_file, card, card_id, continuation, quoted}."""
    lines = (text or "").splitlines()
    err_res = [re.compile(p) for p in solve_cfg["error_patterns"]]
    ctx_re = re.compile(_ecfg(solve_cfg, "error_context_pattern"))
    card_re = re.compile(_ecfg(solve_cfg, "error_card_pattern"))
    code_re = re.compile(_ecfg(solve_cfg, "error_code_pattern"))
    n_det = int(_ecfg(solve_cfg, "error_detail_lines"))
    n_ctx = int(_ecfg(solve_cfg, "error_context_lines"))

    def is_err(ln: str) -> bool:
        return any(r.search(ln) for r in err_res)

    def is_rule(ln: str) -> bool:
        t = ln.strip()
        return len(t) >= 10 and set(t) <= {"*", "-", "="}

    out, seen = [], set()
    for i, ln in enumerate(lines):
        if not is_err(ln):
            continue
        det = []
        for j in range(i + 1, min(len(lines), i + 1 + n_det)):
            t = lines[j].strip()
            if not t or is_rule(t) or is_err(lines[j]) or ctx_re.search(t):
                break
            det.append(t[:300])
        ctx, c0 = [], None
        for j in range(i - 1, max(-1, i - 1 - n_ctx), -1):
            if is_err(lines[j]) or is_rule(lines[j]):
                break
            if ctx_re.search(lines[j]):
                c0 = j
                break
        if c0 is not None:
            ctx = [x.strip()[:300] for x in lines[c0:i] if x.strip()]
        b = {"error": ln.strip()[:300], "code": None, "detail": det, "context": ctx, "deck_line_no": None,
             "deck_file": None, "card": None, "card_id": None, "continuation": None, "quoted": None}
        m = code_re.search(ln)
        if m:
            b["code"] = int(m.group(1))
        if ctx:
            m = ctx_re.search(ctx[0])
            b["deck_line_no"] = int(m.group(1)) if m and m.groups() else None
            for x in ctx[1:]:
                mc = card_re.search(x)
                if mc:
                    b["continuation"] = int(mc.group(1)) if mc.group(1) else None
                    b["card"], b["card_id"] = mc.group(2).upper(), mc.group(3)
                elif len(x) >= 2 and x[0] == '"' and x[-1] == '"':
                    b["quoted"] = x[1:-1]
                elif b["deck_file"] is None and b["card"] is None and b["quoted"] is None:
                    b["deck_file"] = x
        key = (b["error"], tuple(det), tuple(ctx))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def error_summary(b: dict) -> str:
    """failure_message 용 한 줄: 'ERROR # 1485 in the input data: Field 0 ... — DTPG,9000006 연속 줄 1, 덱 줄 446378: "+,BEAD,..."'."""
    head = b["error"]
    if b.get("code") is not None:
        rest = b["error"].split(str(b["code"]), 1)[-1].strip(" *:")
        head = f"ERROR # {b['code']}" + (f" {rest}" if rest else "")
    s = head + (": " + " ".join(b["detail"]) if b.get("detail") else "")
    where = []
    if b.get("card"):
        where.append(f"{b['card']},{b['card_id']}" + (f" 연속 줄 {b['continuation']}" if b.get("continuation") else ""))
    if b.get("deck_line_no") is not None:
        where.append(f"덱 줄 {b['deck_line_no']}")
    if where:
        s += " — " + ", ".join(where)
    if b.get("quoted"):
        s += f': "{b["quoted"]}"'
    return s


def error_text(blocks: list[dict]) -> str:
    """전체 블록(문맥·오류·상세 줄 그대로) — solve/os_errors.txt·작업 로그용."""
    out = []
    for k, b in enumerate(blocks, start=1):
        out.append(f"[{k}] {error_summary(b)}")
        out += [f"    {x}" for x in b["context"] + [b["error"]] + b["detail"]]
    return "\n".join(out) + ("\n" if out else "")


def classify(exit_code: int, text: str, solve_cfg: dict, have_files: bool = True) -> str | None:
    p = parse_out(text or "", solve_cfg)
    if exit_code == 0 and not p["errors"] and have_files:
        return None
    if exit_code != 0 and p["license"]:
        return "OS_LICENSE_UNAVAILABLE"
    if p["memory"]:
        return "SOLVER_OUT_OF_MEMORY"
    return "OS_SOLVE_FAILED"


def history(parsed: dict, selection: dict) -> list[dict]:
    """반복별 행. 케이스 순서 = 라벨 순(L01…), subcase 번호 = 라벨 순 1-기반(optdeck 와 같음)."""
    sel = sorted((r for r in selection["rows"] if r.get("label")), key=lambda r: r["label"])
    norm = selection["objective_norm"]
    C_ref = float(selection["C_ref"])
    obj = dict(parsed["objective"])
    its = sorted(set(obj) | set(parsed["compliance"]))
    out = []
    for it in its:
        cs = parsed["compliance"].get(it, {})
        row = {"iteration": it}
        ratios = []
        for k, r in enumerate(sel, start=1):
            c = cs.get(k)
            row[f"C_{r['label']}"] = c
            rr = None if c is None else c / float(r["C0"])
            row[f"ratio_{r['label']}"] = rr
            if c is not None:
                ratios.append(c / C_ref if norm == "abs" else rr)
        row["objective"] = max(ratios) if len(ratios) == len(sel) and ratios else obj.get(it)
        out.append(row)
    return out


def history_csv(rows: list[dict], selection: dict) -> str:
    sel = sorted((r for r in selection["rows"] if r.get("label")), key=lambda r: r["label"])
    cols = ["iteration", "objective"] + [f"C_{r['label']}" for r in sel] + [f"ratio_{r['label']}" for r in sel]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else (repr(float(r[c])) if c != "iteration" else int(r[c])) for c in cols])
    return buf.getvalue()


def subcase_summary(parsed: dict, selection: dict, c0_tol: float) -> tuple[list[dict], list[str]]:
    """OptResult.subcases + c0_tol 경고 (반복 0 의 C_os 와 자체 솔버 C_self 차)."""
    sel = sorted((r for r in selection["rows"] if r.get("label")), key=lambda r: r["label"])
    comp = parsed["compliance"]
    first = comp.get(min(comp)) if comp else {}
    last = comp.get(max(comp)) if comp else {}
    out, warns = [], []
    for k, r in enumerate(sel, start=1):
        c0os = first.get(k) if first else None
        cf = last.get(k) if last else None
        c0 = float(r["C0"])
        if c0os is not None and c0 > 0 and abs(c0os / c0 - 1.0) > float(c0_tol):
            warns.append(f"{r['label']}: OptiStruct 초기 컴플라이언스 {c0os:.4g} 와 자체 솔버 {c0:.4g} 차 "
                         f"{abs(c0os / c0 - 1) * 100:.1f} % > {float(c0_tol) * 100:g} % (요소 정식화 차이 — 결과는 OptiStruct 값 기준)")
        base = c0os if c0os is not None else c0
        out.append({"label": r["label"], "entry_id": r["entry_id"], "C0_self": c0, "C0_os": c0os, "C_final": cf,
                    "ratio": (cf / base) if (cf is not None and base) else None})
    return out, warns


def require_ok(exit_code: int, text: str, solve_cfg: dict, have_files: bool) -> dict:
    code = classify(exit_code, text, solve_cfg, have_files)
    if code is not None:
        p = parse_out(text or "", solve_cfg)
        raise EslError(code, f"OptiStruct 실패(종료코드 {exit_code}): " + ("; ".join(
            error_summary(b) for b in p["error_blocks"][:3]) or
                                                                       ("출력 파일 없음" if not have_files else "오류 패턴")))
    return parse_out(text, solve_cfg)
