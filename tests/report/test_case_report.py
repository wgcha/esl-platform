"""Case HTML 보고서(esl.report.case_report, 계약 esl_p2_library.md §5·§7.3): 합성 E2E 산출물 → report.html.

자체 완결(외부 URL·외부 리소스 0), 크기 상한, 주요 절·겹쳐보기 컨트롤 존재, inline JSON 데이터, 다운샘플,
누락 산출물 내성, 이스케이프.
"""
import json
import os
import re
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
import synth_case  # noqa: E402

from esl import pipeline  # noqa: E402
from esl.report import case_report  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
SECTIONS = ("inputs", "tstar", "supports", "feq", "validation", "field", "overlay", "section", "top", "hist", "notes")
MAX_BYTES = 3 * 1024 * 1024
_EXTERNAL = [r"https?://", r"(?:src|href)\s*=\s*[\"']?//", r"<link\b", r"<script[^>]*\bsrc\s*=", r"@import",
             r"url\(", r"<iframe", r"<img\b", r"\bfetch\(", r"XMLHttpRequest", r"<object\b", r"<embed\b"]


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("rep"))
    c = synth_case.build(root)
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64"))
    out = os.path.join(root, "out")
    rec = pipeline.run(config_path=cfg, rad=c["rad"], results=c["csv"], out=out, stage="all", echo=lambda m: None)
    c.update(cfg=cfg, out=out, rec=rec, root=root)
    return c


def _html(path):
    return open(path, encoding="utf-8").read()


def _data(doc):
    m = re.search(r'<script type="application/json" id="esl-data">(.*?)</script>', doc, re.S)
    assert m
    return json.loads(m.group(1).replace("<\\/", "</"))


def _assert_self_contained(doc):
    for pat in _EXTERNAL:
        assert not re.search(pat, doc, re.I), pat
    assert doc.count("<script") == 2                    # inline JSON 1 + inline JS 1


def test_report_generated_by_pipeline(case):
    path = os.path.join(case["out"], "07_report", "report.html")
    st = case["rec"]["stages"]["report"]
    assert st["status"] == "done" and st["summary"]["path"] == "07_report/report.html"
    doc = _html(path)
    assert 10_000 < os.path.getsize(path) <= MAX_BYTES
    _assert_self_contained(doc)
    assert doc.startswith("<!DOCTYPE html>") and '<html lang="ko">' in doc
    for sid in SECTIONS:
        assert f'<section id="{sid}">' in doc, sid
    assert "자료 없음" not in doc and st["summary"]["missing"] == []
    # 겹쳐보기 컨트롤: 레이어 4종, 불투명도 슬라이더, 캔버스 3장, 단면선 배율 슬라이더
    for s in ('value="rad"', 'value="esl"', 'value="err"', 'value="ovl"', 'id="ovl-op"', 'id="cv0"', 'id="cv1"',
              'id="cv2"', 'id="sec-k"', 'name="sax"', "prefers-color-scheme:dark", 'id="theme-btn"'):
        assert s in doc, s
    assert '<span class="badge pass">PASS</span>' in doc
    assert "요소 정식화·회전 자유도 차이만큼만 어긋나고" in doc            # 의미 주석(§7.2 마지막 항)
    assert "<svg" in doc and "xmlns" not in doc
    d = _data(doc)
    E = len(case["elem_id"])
    mp = d["map"]
    assert mp["n_total"] == mp["n_shown"] == E and mp["cell"] is None and len(mp["sz"]) == E
    assert len(mp["x"]) == len(mp["rad"]) == len(mp["err"]) == len(mp["st"]) == E
    assert len(mp["hot"]) == 3 and len(mp["sup"]) == 3 and mp["max"] is not None
    val = json.load(open(os.path.join(case["out"], "05_val", "validation.json"), encoding="utf-8"))
    assert sum(1 for s in mp["st"] if s == 0) == val["field"]["n_valid"]
    assert mp["vmax"] == pytest.approx(val["field"]["max"]["eps_rad"], rel=1e-6)
    assert d["sec"]["xi"]["s"] and d["sec"]["eta"]["s"] and d["sec"]["k0exp"] >= 0


def test_report_downsampled(case, tmp_path):
    info = case_report.write_case_report(case["out"], out_path=str(tmp_path / "r.html"), max_points=300)
    assert info["downsampled"] is True and info["n_points"] <= 300 and info["n_elems"] == len(case["elem_id"])
    d = _data(_html(tmp_path / "r.html"))
    assert d["map"]["cell"] is not None and "sz" not in d["map"]


def test_report_large_model_size_bound(tmp_path):
    """요소 25만 개(가짜 compare_field.npz) → report.max_points=20000 다운샘플, 파일 ≤ 3 MB."""
    E = 250_000
    rng = np.random.default_rng(1)
    d = tmp_path / "case" / "05_val"
    d.mkdir(parents=True)
    c2 = np.c_[rng.uniform(-900, 900, E), rng.uniform(-500, 500, E)]
    er = rng.uniform(0, 0.05, E)
    rel = rng.normal(0, 0.05, E)
    valid = rng.uniform(size=E) > 0.2
    np.savez_compressed(d / "compare_field.npz", elem_id=np.arange(E, dtype=np.int64) + 1, centroid2d=c2,
                        centroid3d=np.c_[c2, np.zeros(E)], eps_rad=er, eps_esl=er * (1 + rel), rel_err=rel,
                        valid=valid, rising=valid, reason=np.where(valid, 0, 1).astype(np.int8),
                        elem_size=np.full(E, 4.0), plane_origin=np.zeros(3), plane_e1=np.eye(3)[0],
                        plane_e2=np.eye(3)[1], plane_n=np.eye(3)[2])
    info = case_report.write_case_report(str(tmp_path / "case"), max_points=20000)
    assert info["downsampled"] and info["n_points"] <= 20000
    assert info["bytes"] <= MAX_BYTES, info["bytes"]
    _assert_self_contained(_html(info["path"]))


def test_report_tolerates_missing_stages_and_escapes(case, tmp_path):
    out = str(tmp_path / "o")
    os.makedirs(out)
    shutil.copytree(os.path.join(case["out"], "01_extract"), os.path.join(out, "01_extract"))
    mp = os.path.join(out, "01_extract", "model_meta.json")
    meta = json.load(open(mp, encoding="utf-8"))
    meta["part_title"] = "<script>alert(1)</script>&"
    json.dump(meta, open(mp, "w", encoding="utf-8"))
    rec = pipeline.run(config_path=case["cfg"], rad=case["rad"], results=case["csv"], out=out, stage="report",
                       echo=lambda m: None)
    s = rec["stages"]["report"]
    assert s["status"] == "done" and "02_tstar/tstar.json" in s["summary"]["missing"]
    assert any("없는 산출물" in w for w in s["warnings"])
    doc = _html(os.path.join(out, "07_report", "report.html"))
    assert "<script>alert(1)</script>" not in doc and "&lt;script&gt;alert(1)&lt;/script&gt;&amp;" in doc
    assert doc.count("자료 없음") >= 5 and _data(doc)["map"] is None
    _assert_self_contained(doc)
