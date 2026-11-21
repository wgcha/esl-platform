"""v0.24.3 07_report 출처별 판정 표(계약 esl_validate_sources.md §4.5·§10, V-0243-VAL-10).

05_val/sources.json 이 있으면 5절 끝에 표 1개(행 = 계획 표 순서 중 하중 열이 있는 출처, 한계 열), 없으면 v0.24.2 보고서와
같은 HTML(생성 시각 제외)·같은 missing 목록.
"""
import json
import os
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
import synth_case  # noqa: E402
from test_bforce_stage import _add_bforce  # noqa: E402

from esl import pipeline, val_src  # noqa: E402
from esl.report import case_report  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
_BLOCK = re.compile(r"<!--val-src-->(.*?)<!--/val-src-->", re.DOTALL)
_NOW = re.compile(r"생성 \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    out = {}
    for name in ("bf", "plain"):
        root = str(tmp_path_factory.mktemp(f"rvs_{name}"))
        c = synth_case.build(root)
        if name == "bf":
            _add_bforce(c, c["csv"], fint_sign=-1.0)
        cfg = os.path.join(root, "esl64.yaml")
        with open(CFG, encoding="utf-8") as fh:
            txt = fh.read().replace("disp_precision: float32", "disp_precision: float64")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(txt)
        o = os.path.join(root, "out")
        pipeline.run(config_path=cfg, rad=c["rad"], results=c["csv"], out=o, stage="all",
                     frame=synth_case.T_STAR_FRAME, echo=lambda *_: None)
        out[name] = o
    return out


def _section5(html: str) -> str:
    a = html.index('id="validation"')
    return html[a:html.index('id="field"', a)]


def test_v10_table_in_section5_rows_and_limits(cases):
    html, info = case_report.build_case_report(cases["bf"])
    blocks = _BLOCK.findall(html)
    assert len(blocks) == 1 and len(_BLOCK.findall(_section5(html))) == 1           # 5절 안 표 1개
    b = blocks[0]
    labels = [val_src.LABEL[r["key"]] for r in val_src.VAL_PLAN if r["load"] is not None]
    t = b[b.index("<table"):]                                                        # 표 안(설명 문구 제외)
    pos = [t.index(x) for x in labels]
    assert pos == sorted(pos)                                                        # 순서 = KEYS 중 load 있는 행
    rows = re.findall(r"<tr>(.*?)</tr>", b, re.DOTALL)[1:]
    assert len(rows) == 6                                                            # v0.24.4: 지그 3방식 행(의도 변경 §12-6)
    for k in ("jig", "jig_disp", "jig_spring"):                                      # tie 준비 없는 Case = 불가 + 사유
        jr = next(x for x in rows if val_src.LABEL[k] in x)
        assert "불가" in jr and "tie 노드 준비 기록이 없어" in jr and "PASS" not in jr
    bf_row = next(x for x in rows if val_src.LABEL["bforce"] in x)
    assert "비교용 아님" in bf_row and "tie 체결력 미포함" in bf_row and "PASS" in bf_row
    assert "관성 이완" in bf_row                                                     # 조건(균형) 문구
    assert "sources.json" not in " ".join(info["missing"])
    with open(os.path.join(cases["bf"], pipeline.D_REPORT, case_report.REPORT_NAME), encoding="utf-8") as fh:
        assert len(_BLOCK.findall(fh.read())) == 1                                   # 파이프라인 report 단계도 같음


def test_v10_without_sources_json_equals_v0242_report(cases, tmp_path):
    with_src, info1 = case_report.build_case_report(cases["bf"])
    cp = str(tmp_path / "old")
    shutil.copytree(cases["bf"], cp)
    os.remove(os.path.join(cp, pipeline.D_VAL, val_src.SOURCES_JSON))
    old, info2 = case_report.build_case_report(cp)
    assert "<!--val-src-->" not in old
    norm = lambda s: _NOW.sub("생성 <TS>", s)                                       # noqa: E731
    assert norm(old) == norm(_BLOCK.sub("", with_src).replace("<!--val-src-->", ""))
    assert info1["missing"] == info2["missing"] and info1["sections"] == info2["sections"]
    # 손상 sources.json = 없음과 같음(보고서 실패 없음, missing 불변)
    with open(os.path.join(cp, pipeline.D_VAL, val_src.SOURCES_JSON), "w", encoding="utf-8") as fh:
        fh.write("{bad")
    bad, info3 = case_report.build_case_report(cp)
    assert norm(bad) == norm(old) and info3["missing"] == info2["missing"]


def test_v10_unavailable_rows_show_reason(cases):
    html, _ = case_report.build_case_report(cases["plain"])
    b = _BLOCK.findall(html)[0]
    with open(os.path.join(cases["plain"], pipeline.D_VAL, val_src.SOURCES_JSON), encoding="utf-8") as fh:
        rows = {r["key"]: r for r in json.load(fh)["rows"]}
    assert rows["bforce"]["status"] == "unavailable"
    bf_row = next(x for x in re.findall(r"<tr>(.*?)</tr>", b, re.DOTALL) if val_src.LABEL["bforce"] in x)
    assert "불가" in bf_row and rows["bforce"]["code"] != "" and "PASS" not in bf_row
