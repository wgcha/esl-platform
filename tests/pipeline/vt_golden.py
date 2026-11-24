"""v0.24.5 ④ 검증 판정 단계화(계약 docs/contracts/esl_validate_tiers.md §5-6·§5-8) — 골든 도구.

골든 ``tests/fixtures/val_tiers/golden_v0244.json`` 은 코어 변경 **전**(계약 커밋 77212df5 = v0.24.4 검증 코드)에
``ESL_GOLDEN_RECORD=1`` 로 기록했다. 다시 기록하면 안 된다: 깨지면 v0.24.4 값(지표·파일 세트·보고서 기존 부분)이 바뀐 것이다.

합성 Case 5종(bf = 경계력·내력 자료, plain = 없음, never = ``full_solve: never``, stress = 응력 대체, jig = 지그 3방식 포함
출처 6행)의 05_val 전부(루트·출처 폴더·sources.json)·06_export·07_report(전체 + 절 조각)·단계 요약을 기록한다.
설정 = 예시 yaml(float64) + ``disp_rms_rel_max: 0.01``(기록 당시 예시 값 — 변경 후에는 Q-VT-1 "명시값 존중" 경로가 된다).

npz 는 배열(이름·dtype·shape·바이트) 해시, JSON 은 시각·시간·메모리 값을 뺀 정규 JSON(키 순서 유지) 해시, 텍스트는 실행 루트·
시각·버전 문자열을 치환한 sha256.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import numpy as np

import esl
from esl import pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "val_tiers", "golden_v0244.json")
RECORDED_AT = "77212df5 (= v0.24.4 stage_validate·report code, v0.24.5 계약 커밋)"
TAG = "golden-v0245-vt"
CASES = ("bf", "plain", "never", "stress", "jig")
VOLATILE = {"created_at", "assembly_s", "tocsr_s", "factor_s", "solve_s", "eval_s", "rss_peak_mb", "mem_avail_mb",
            "mem_avail"}
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_SRC_BLOCK = re.compile(r"<!--val-src-->.*?<!--/val-src-->", re.DOTALL)
_SECTION = re.compile(r'<section id="([^"]+)">(.*?)</section>', re.DOTALL)
# 5절(검증 요약) 안 판정 머리(판정 줄·설명·판정 표)와 나머지(참고 표 이후)를 나누는 첫 표식 — 둘 중 먼저 나오는 것
_VAL_SPLIT = ("<h3>변형률 (참고", "<h3>변위 비교", "<h3>hotspot")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def cfg_text() -> str:
    """골든 설정 = 예시 yaml(float64) + disp_rms_rel_max 0.01 명시(기록 당시 예시 값)."""
    t = _read(os.path.join(ROOT, "config", "esl.example.yaml")).replace("disp_precision: float32",
                                                                         "disp_precision: float64")
    t2, n = re.subn(r"(\n  disp_rms_rel_max: )[0-9.eE+-]+", r"\g<1>0.01", t)
    assert n == 1
    return t2


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def json_hash(doc) -> str:
    return _sha(json.dumps(strip(doc), ensure_ascii=False, indent=1).encode())


def npz_hash(path: str) -> str:
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as z:
        for k in z.files:
            a = z[k]
            h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
            h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def norm_text(s: str, root: str) -> str:
    s = s.replace(root, "<ROOT>").replace(root.replace("\\", "/"), "<ROOT>")
    s = _TS.sub("<TS>", s)
    return s.replace(f"esl {esl.__version__}", "esl <VER>").replace(f'"{esl.__version__}"', '"<VER>"')


def text_hash(s: str, root: str) -> str:
    return _sha(norm_text(s, root).encode())


def report_segments(html: str, root: str) -> dict[str, str]:
    """보고서 조각 해시: head(첫 절 앞)·절마다·tail(마지막 절 뒤) + 5절은 judge(판정 머리)·rest(참고 표 이후, 출처 표 제외)·
    val_src(출처 표 블록)로 나눔."""
    t = norm_text(html, root)
    segs: dict[str, str] = {}
    ms = list(_SECTION.finditer(t))
    segs["head"] = _sha(t[:ms[0].start()].encode()) if ms else _sha(t.encode())
    for m in ms:
        sid, inner = m.group(1), m.group(2)
        if sid == "validation":
            blk = _SRC_BLOCK.search(inner)
            segs["validation.val_src"] = _sha((blk.group(0) if blk else "").encode())
            body = _SRC_BLOCK.sub("", inner)
            cut = min([body.index(x) for x in _VAL_SPLIT if x in body] or [len(body)])
            segs["validation.judge"] = _sha(body[:cut].encode())
            segs["validation.rest"] = _sha(body[cut:].encode())
        else:
            segs[f"section.{sid}"] = _sha(inner.encode())
    segs["tail"] = _sha(t[ms[-1].end():].encode()) if ms else ""
    return segs


def file_hash(path: str, root: str) -> str:
    if path.endswith(".npz"):
        return npz_hash(path)
    if path.endswith(".json"):
        return json_hash(json.loads(_read(path)))
    return text_hash(_read(path), root)


def norm_summary(summ: dict) -> str:
    return json_hash(json.loads(json.dumps(summ)))


def snapshot(out: str, root: str) -> dict:
    """05_val/**·06_export/**·07_report/report.html 해시 + 보고서 조각 + 단계 요약(검증) 해시."""
    files: dict[str, str] = {}
    for sub in (pipeline.D_VAL, pipeline.D_EXPORT, pipeline.D_REPORT):
        base = os.path.join(out, sub)
        for dp, dns, fns in os.walk(base):
            dns.sort()
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                files[os.path.relpath(p, out).replace(os.sep, "/")] = file_hash(p, root)
    rep = os.path.join(out, pipeline.D_REPORT, "report.html")
    rj = json.loads(_read(os.path.join(out, pipeline.RUN_JSON)))
    return {"files": files, "report": report_segments(_read(rep), root) if os.path.isfile(rep) else {},
            "summary": norm_summary(rj["stages"]["validate"]["summary"])}


# ====================================================================== Case 만들기
def build_case(name: str, root: str) -> dict:
    """합성 Case(name ∈ CASES)를 stage 별로 끝까지(extract → … → report) 실행 → {out, root, c, cfg}."""
    import synth_case
    from test_bforce_stage import _add_bforce

    c = synth_case.build(root, source="max_stress" if name == "stress" else "max_strain")
    if name in ("bf", "never", "jig"):
        _add_bforce(c, c["csv"], fint_sign=-1.0)
    if name == "jig":
        from test_jig_case import add_neighbor
        add_neighbor(c)
    txt = cfg_text()
    if name == "never":
        assert "full_solve: auto" in txt
        txt = txt.replace("full_solve: auto", "full_solve: never")
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    out = os.path.join(root, "out")
    kw = {"config_path": cfg, "rad": c["rad"], "results": c["csv"], "out": out, "frame": synth_case.T_STAR_FRAME,
          "echo": lambda *_: None, "tag": TAG}
    for st in pipeline.STAGES:
        pipeline.run(stage=st, **kw)
        if st == "extract" and name == "jig":
            from test_jig_case import tie_index, write_fixed
            write_fixed(out, c, tie_index())
    return {"out": out, "root": root, "c": c, "cfg": cfg, "kw": kw}


def load_golden() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def record_if_asked(cur: dict) -> None:
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not os.path.isfile(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump({"recorded_at_commit": RECORDED_AT, "cases": cur}, fh, ensure_ascii=False, indent=1,
                      sort_keys=True)
            fh.write("\n")
