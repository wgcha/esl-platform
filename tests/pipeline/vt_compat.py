"""v0.24.5 의도 변경 되돌림(골든 비교용 — 계약 docs/contracts/esl_validate_tiers.md §5-6, D-0.24.3-VAL-8 보충 선례).

새 결과(verdict_scheme ``disp_primary/2``)를 v0.24.4 형식으로 되돌려 옛 골든(v0.7.2·v0.24.2·v0.24.3·v0.24.4)과 비교한다.
되돌리는 것 = 의도 차이만: schema·verdict_scheme 문자열, ``cond_reasons``, criteria 새 키 3개, judge 행 grade·criterion_cond·sense,
``mac`` 행·sources.json 행 verdict_scheme·cond_reasons·metrics.mac, run.json 요약 mac·cond_reasons, 그리고 옛 단일 기준 판정
(행 pass·verdict·fail_reasons — 옛 규칙 ``v ≤ 기준``으로 같은 값에서 다시 계산, 출처 반력 기준 = 허용치) + 옛 반력 주의 표식
(REACTION_ABOVE_WARN). 나머지 키·값은 그대로 — 되돌린 결과가 옛 골든과 바이트 같아야 한다.
보고서는 되돌린 문서로 **새 코드가 다시 그린** 것(옛 결과 표시 = 저장 판정 그대로, §3.2)을 옛 골든과 비교한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile

from esl import val_metrics as vm
from esl import val_src as vs
from esl.export import csvout

OLD_SCHEMA = "esl/validation/3"
OLD_SCHEME = vm.VERDICT_SCHEMES[0]
NEW_CRIT_KEYS = ("disp_rms_rel_cond_max", "mac_min", "mac_cond_min")
NEW_ROW_KEYS = ("grade", "criterion_cond", "sense")
NEW_METRIC = "mac"
OLD_JUDGE_CODE = {k: v for k, v in vm.FAIL_REASON.items() if k != NEW_METRIC}


def is_new(doc) -> bool:
    return isinstance(doc, dict) and doc.get("verdict_scheme") == vm.VERDICT_SCHEME


def back_validation(doc: dict) -> dict:
    """validation.json(루트·출처 폴더) 새 → v0.24.4 형식. 옛 문서는 그대로."""
    if not is_new(doc):
        return doc
    d = {k: v for k, v in doc.items() if k != "cond_reasons"}
    d["schema"], d["verdict_scheme"] = OLD_SCHEMA, OLD_SCHEME
    crit = {k: v for k, v in doc["criteria"].items() if k not in NEW_CRIT_KEYS}
    d["criteria"] = crit
    mets = []
    for m in doc["metrics"]:
        if m["metric"] == NEW_METRIC:
            continue
        if m["role"] == "judge":
            m = {k: v for k, v in m.items() if k not in NEW_ROW_KEYS}
            c = crit["reaction_rel_max"] if m["metric"] == "reaction_rel" else m["criterion"]
            m["criterion"] = c
            if m.get("status") != "skipped":
                m["pass"] = bool(m["value"] <= c)
        mets.append(m)
    d["metrics"] = mets
    if d["verdict"] != vm.UNDETERMINED:
        judge = [m for m in mets if m["role"] == "judge"]
        d["verdict"] = vm.PASS if all(m["pass"] is True for m in judge) else vm.FAIL
        d["fail_reasons"] = [OLD_JUDGE_CODE[m["metric"]] for m in judge if m["pass"] is not True]
    return d


def _row_back(r: dict, vdoc: dict | None) -> dict:
    out = {k: v for k, v in r.items() if k not in ("verdict_scheme", "cond_reasons")}
    if isinstance(out.get("metrics"), dict):
        out["metrics"] = {k: v for k, v in out["metrics"].items() if k != NEW_METRIC}
    if vdoc is not None:
        out["verdict"], out["fail_reasons"] = vdoc["verdict"], list(vdoc["fail_reasons"])
    if out.get("reaction_warned"):                    # v0.24.4: PASS 유지 + 주의 표식(한계 자리)
        reac, warn = out["metrics"]["reaction_rel"], out["reaction_warn"]
        out["limits"] = [*out["limits"], vs.WARN_CODE]
        out["limit_text"] = [*out["limit_text"], f"반력 {reac * 100:.3g} % — {warn * 100:g} % 초과, 받침점 주변 국부 변형 확인"]
    return out


def _val_doc(val_dir: str, sub: str | None) -> dict | None:
    p = os.path.join(val_dir, sub or "", "validation.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return back_validation(json.load(fh))


def back_sources(sj: dict, val_dir: str) -> dict:
    """sources.json 새 → v0.24.4 형식(행 verdict·fail_reasons = 되돌린 출처 validation.json)."""
    rows = sj.get("rows") or []
    if not any(r.get("verdict_scheme") == vm.VERDICT_SCHEME for r in rows) and not any("cond_reasons" in r for r in rows):
        return sj
    out = dict(sj)
    out["rows"] = [_row_back(r, _val_doc(val_dir, r.get("dir")) if r.get("status") == "done" else None) for r in rows]
    return out


def back_summary(summ: dict, val_dir: str) -> dict:
    """run.json stages.validate.summary 새 → v0.24.4 키·판정."""
    if "cond_reasons" not in summ:
        return summ
    s = {k: v for k, v in summ.items() if k not in ("cond_reasons", NEW_METRIC)}
    root = _val_doc(val_dir, None)
    if root is not None:
        s["verdict"], s["fail_reasons"] = root["verdict"], list(root["fail_reasons"])
    if isinstance(s.get("sources"), dict):
        dirs = {r["key"]: r["dir"] for r in vs.VAL_PLAN}
        src = {}
        for k, x in s["sources"].items():
            y = {kk: vv for kk, vv in x.items() if kk not in ("cond_reasons", NEW_METRIC)}
            if y.get("status") == "done":
                bd = _val_doc(val_dir, dirs.get(k))
                if bd is not None:
                    y["verdict"], y["fail_reasons"] = bd["verdict"], list(bd["fail_reasons"])
            src[k] = y
        s["sources"] = src
    return s


def csv_format(out: str) -> csvout.CsvFormat:
    with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
        c = json.load(fh)["config"]["snapshot"]["export"]["csv"]
    return csvout.CsvFormat(c["delimiter"], c["float_format"])


def validation_csv_text(doc: dict, fmt: csvout.CsvFormat) -> str:
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "v.csv")
        csvout.write_validation_csv(p, doc, fmt)
        with open(p, encoding="utf-8", newline="") as fh:
            return fh.read()


def back_csv(text: str, path: str, out: str) -> str:
    """validation.csv(05_val 루트·출처 폴더·06_export) — 같은 자리 validation.json(06_export = 05_val 루트)이 새 형식이면
    되돌린 문서로 같은 쓰기 함수(csvout.write_validation_csv)로 다시 씀. 새 파일이 새 문서를 그대로 쓴 것인지도 확인."""
    d = os.path.dirname(path)
    vdir = os.path.join(out, "05_val") if os.path.basename(d) == "06_export" else d
    p = os.path.join(vdir, "validation.json")
    if not os.path.isfile(p):
        return text
    with open(p, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not is_new(doc):
        return text
    fmt = csv_format(out)
    assert text == validation_csv_text(doc, fmt), path            # 새 파일 = 새 문서 그대로(행 추가·pass = grade PASS)
    return validation_csv_text(back_validation(doc), fmt)


def back_report_html(out: str) -> str | None:
    """되돌린 05_val 문서로 새 코드가 다시 그린 보고서에서 출처 표의 v0.24.5 추가분(MAC 열 "—"·설명 끝 문장)을 뺀 것 =
    v0.24.4 보고서 바이트(옛 결과 재생성 = 저장 판정 그대로). 새 형식이 아니면 None."""
    html = render_back(out)
    return None if html is None else strip_val_src_tiers(html)


def render_back(out: str) -> str | None:
    """되돌린 05_val 문서(옛 결과와 같은 형식)로 새 코드가 다시 그린 보고서 그대로. 새 형식이 아니면 None."""
    vd = os.path.join(out, "05_val")
    p = os.path.join(vd, "validation.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        if not is_new(json.load(fh)):
            return None
    from esl.report import case_report

    with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
        rec = json.load(fh)
    rec = back_record_cfg(rec)
    rcfg = rec["config"]["snapshot"]["report"]
    with tempfile.TemporaryDirectory() as t:
        cp = os.path.join(t, "case")
        shutil.copytree(out, cp, ignore=shutil.ignore_patterns("07_report"))
        back_tree(cp)
        doc, _ = case_report.build_case_report(cp, record=rec, max_points=rcfg["max_points"],
                                               top_forces=rcfg["top_forces"])
    return doc.replace(cp, out)


# v0.24.5 §12 되돌림 설정(vt_golden.REENABLE_V0244 — bforce.enabled true·jig.methods 세 방식) = v0.24.4 기본과 같은 계산. 보고서
# 1절 "설정 sha256" 만 달라지므로 그 두 절을 뺀 스냅샷의 sha(= v0.24.4 때 같은 설정의 값)로 되돌린다.
REENABLE_SNAP = {"bforce": {"enabled": True}, "jig": {"methods": ["fixed", "prescribed", "spring"]}}


def _snap_sha(snap: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def back_record_cfg(rec: dict) -> dict:
    """run.json 기록의 config(snapshot·sha256)에서 §12 되돌림 절을 뺀 사본(그 절이 정확히 되돌림 값일 때만)."""
    cfg = rec.get("config") or {}
    snap = cfg.get("snapshot") or {}
    if not all(snap.get(k) == v for k, v in REENABLE_SNAP.items()):
        return rec
    s2 = {k: v for k, v in snap.items() if k not in REENABLE_SNAP}
    return {**rec, "config": {**cfg, "snapshot": s2, "sha256": _snap_sha(s2)}}


def back_cfg_sha_text(text: str, out: str) -> str:
    """파일 글자 안 설정 sha(되돌림 절 포함) → 절을 뺀 sha(보고서를 pipeline 이 직접 쓴 경우)."""
    with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
        rec = json.load(fh)
    new = back_record_cfg(rec)
    return text if new is rec else text.replace(rec["config"]["sha256"], new["config"]["sha256"])


_SRC_BLOCK = re.compile(r"<!--val-src-->.*?<!--/val-src-->", re.DOTALL)
_MAC_TH = '<th class="num">MAC(검증)</th>'


def strip_val_src_tiers(html: str) -> str:
    """출처 표(<!--val-src--> 블록)에서 v0.24.5 추가분(머리 설명 끝 문장·"MAC(검증)" 열)만 뺌 — 옛 sources.json 을 새 코드로
    그린 표 = v0.24.4 표(MAC 칸은 전부 "—"인지도 확인)."""
    from esl.report import case_report

    def fix(m):
        b = m.group(0)
        assert b.count(case_report.VAL_SRC_TIERS_NOTE) == 1 and b.count(_MAC_TH) == 1
        b = b.replace(case_report.VAL_SRC_TIERS_NOTE, "")
        heads = re.findall(r"<th[^>]*>.*?</th>", b)
        col = heads.index(_MAC_TH)
        b = b.replace(_MAC_TH, "")

        def row(rm):
            cells = re.findall(r"<td[^>]*>.*?</td>", rm.group(1))
            assert cells[col] == '<td class="num">—</td>', cells[col]
            return "<tr>" + "".join(c for i, c in enumerate(cells) if i != col) + "</tr>"
        return re.sub(r"<tr>((?:<td[^>]*>.*?</td>)+)</tr>", row, b)
    return _SRC_BLOCK.sub(fix, html)


def back_tree(out: str) -> None:
    """Case 폴더의 05_val 문서(루트·출처 폴더 validation.json·sources.json)를 제자리에서 v0.24.4 형식으로 바꿈(시험 사본 전용)."""
    vd = os.path.join(out, "05_val")
    srcj = os.path.join(vd, vs.SOURCES_JSON)
    sj = None
    if os.path.isfile(srcj):
        with open(srcj, encoding="utf-8") as fh:
            sj = back_sources(json.load(fh), vd)          # 출처 validation.json 을 바꾸기 전에(같은 되돌림)
    for dp, _dns, fns in os.walk(vd):
        if "validation.json" in fns:
            p = os.path.join(dp, "validation.json")
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            if is_new(doc):
                _dump(p, back_validation(doc))
    if sj is not None:
        _dump(srcj, sj)


def _dump(p: str, obj) -> None:
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
