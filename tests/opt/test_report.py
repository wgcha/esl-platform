"""V-OR-20(코어): opt_method_sources.json 스키마, 보고서 "방법·출처" 절 = 같은 문구·링크(이스케이프)·실행 전략 표시,
선정 표·목표 기준 표시, 이스케이프."""
import copy
import html
import json

import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.opt import METHOD_SOURCES_PATH, load_method_sources, settings, sources_ref, validate_method_sources
from esl.opt import report_opt as rp
from esl.opt import select as sl

CFG = settings()


def test_sources_file_schema():
    ms = load_method_sources()
    assert ms == json.load(open(METHOD_SOURCES_PATH, encoding="utf-8"))
    assert len(ms["summary_ko"]) == 3 and set(ms["strategies"]) == {"A", "B", "C"} and set(ms["objective_norms"]) == {
        "abs", "rel"}
    assert len(ms["sources"]) == 3 and ms["sources"][0]["url"].startswith("https://help.altair.com/")
    assert sources_ref(ms) == f"opt_method_sources/{ms['version']}"


@pytest.mark.parametrize("mut", [
    lambda d: d.pop("version"),
    lambda d: d.__setitem__("summary_ko", ["하나"]),
    lambda d: d["strategies"].pop("C"),
    lambda d: d["objective_norms"].__setitem__("max", "x"),
    lambda d: d.__setitem__("sources", []),
    lambda d: d["sources"][0].__setitem__("url", "javascript:alert(1)"),
    lambda d: d["sources"][1].__setitem__("title", ""),
])
def test_sources_schema_rejects(mut):
    d = copy.deepcopy(load_method_sources())
    mut(d)
    with pytest.raises(EslError) as ei:
        validate_method_sources(d)
    assert ei.value.code == "CONFIG_INVALID"


def _sel(strategy="C", norm="rel"):
    V = np.eye(4)
    cands = [{"entry_id": f"E{k}", "C0": c, "umax": 0.1 * c, "mode": m, "scene": s}
             for k, (c, m, s) in enumerate([(4.0, "bend", "<script>alert(1)</script>"), (3.0, "twist", "05 Edge 12"),
                                            (2.0, "dent", "21 Corner"), (1.0, None, "x")])]
    return sl.select(cands, strategy, loads_cfg=CFG["loads"], objective_norm=norm, k=2 if strategy == "C" else None,
                     U=V, u_rows={f"E{k}": k for k in range(4)}, sources_ref="opt_method_sources/v")


@pytest.mark.parametrize("strategy,norm", [("A", "abs"), ("B", "abs"), ("C", "rel")])
def test_report_method_section(tmp_path, strategy, norm):
    ms = load_method_sources()
    sel = _sel(strategy, norm)
    ctx = {"run": {"id": 7, "scenario": "S1", "title": "75형 <b>1차</b>", "entry_ids": ["E0", "E1"]},
           "selection": sel, "result": None, "target": {"n_nodes": 10, "n_elems": 8}, "keepout": {},
           "design": {"bead": CFG["bead_defaults"]}, "deck": {"desmax": 30}, "sources": ms}
    p = rp.write(str(tmp_path / "report.html"), ctx)
    doc = open(p, encoding="utf-8").read()
    assert "<script>alert(1)</script>" not in doc and "&lt;script&gt;alert(1)&lt;/script&gt;" in doc
    assert "<b>1차</b>" not in doc
    sec = doc.split("<section id='method'>")[1].split("</section>")[0]
    for line in ms["summary_ko"]:
        assert html.escape(line, quote=True) in sec
    for k, v in ms["strategies"].items():
        assert html.escape(v, quote=True) in sec
    for s in ms["sources"]:
        assert html.escape(s["title"], quote=True) in sec
        if s.get("url"):
            assert f'href="{html.escape(s["url"], quote=True)}" target="_blank" rel="noopener noreferrer"' in sec
    now = [x for x in sec.split("<li") if "class='now'" in x]
    assert len(now) == 2                                        # 전략 1 + 목표 기준 1
    assert html.escape(ms["strategies"][strategy], quote=True) in now[0]
    assert html.escape(ms["objective_norms"][norm], quote=True) in now[1]
    # 선정 표: 전략·목표 기준 표시
    assert rp.STRATEGY_KO[strategy] in doc and f"목표 <b>{rp.NORM_KO[norm]}</b>" in doc
    if strategy == "C":
        assert "k = 2" in doc


def test_report_with_result_and_bead_grid(tmp_path):
    from esl.library import normalize as nz
    m = so.plate(12, 8)
    fr = nz.frame(m["x0"], None, m["conn"], m["elem_type"])
    he = np.linspace(0, 10, m["elem_id"].size)
    g = rp.bead_grid(m, fr, he, np.ones(m["elem_id"].size, bool), cells=(12, 8))
    assert g["values"].shape == (12, 8) and g["values"].max() > 0
    sel = _sel("A", "abs")
    res = {"converged": False, "iterations": 3, "desmax": 30, "objective": {"initial": 1.0, "final": 0.7},
           "bead": {"height_max": 9.9, "area_frac": 0.3},
           "subcases": [{"label": "L01", "entry_id": "E0", "C0_self": 4.0, "C0_os": 4.1, "C_final": 3.0, "ratio": 0.73}],
           "warnings": ["수렴 표식 없음 <x>"]}
    hist = [{"iteration": 0, "objective": 1.0}, {"iteration": 1, "objective": 0.8}, {"iteration": 3, "objective": 0.7}]
    ctx = {"run": {"id": 1, "scenario": "S2"}, "selection": sel, "result": res, "history": hist, "bead_grid": g,
           "target": {"source": {"rad": {"path": "D:/a<b>.rad", "sha256": "ab" * 32}, "part_title": "p"}},
           "keepout": {"rects": [{"name": "<PCB>", "corner": "a0b0", "x_mm": 1, "y_mm": 2, "w_mm": 3, "h_mm": 4}],
                       "counts": {"n_elems_rects": 5}, "cfg": CFG["keepout"]},
           "keepout_png": b"\x89PNG\r\n\x1a\nfake", "sources": load_method_sources()}
    doc = rp.render(ctx)
    assert "미수렴" in doc and "수렴 이력" in doc and "&lt;PCB&gt;" in doc and "&lt;x&gt;" in doc
    assert "data:image/png;base64," in doc and "비드 높이" in doc and "a&lt;b&gt;.rad" in doc
