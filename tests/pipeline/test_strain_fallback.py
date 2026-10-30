"""h3d 변형률 결과 대체(v0.12.1, 계약 esl_strain_fallback.md §4·§5·§8): 합성 사례를 source 별로 → CLI --stage all.

- strain_tensor(dump): 층별 순간 Strain → 코어 max-hold 재현 → t* = 기존 사례와 같은 frame 6, ESL 비교 층 [bottom, top],
  STRAIN_TMAX_SAMPLED, 판정 PASS. 메타(frames.json·esl_summary·validation·extract 요약) strain_source.
- plastic_strain: 지표 = epsp, 전단 판정 생략(factor 1), 참고 지표 = ε_eq(ESL) vs epsp.
- max_stress: 참고 지표(hotspot·전 요소 ε·잡음 ε) skipped(None) + STRAIN_FROM_STRESS, 판정은 변위 주지표 그대로.
"""
import json
import os

import numpy as np
import pytest

import synth_case
from esl import cli
from esl.library import entry as lib_entry
from esl.report.case_report import build_case_report

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")


def _run(tmp_path, source):
    root = str(tmp_path)
    c = synth_case.build(root, source=source)
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(CFG64_TEXT)
    out = os.path.join(root, "out")
    rc = cli.main(["run", "--config", cfg, "--rad", c["rad"], "--results", c["csv"], "--out", out, "--stage", "all"])
    assert rc == 0
    j = lambda *p: json.load(open(os.path.join(out, *p), encoding="utf-8"))
    return c, out, j


def _metric(val, name):
    return next(m for m in val["metrics"] if m["metric"] == name)


def test_dump_strain_tensor_pipeline(tmp_path):
    c, out, j = _run(tmp_path, "strain_tensor")
    fr = j("01_extract", "frames.json")
    sf = fr["strain_fallback"]
    assert sf["source"] == "strain_tensor" and sf["mode"] == "dump" and sf["layers"] == ["Lower", "Upper"]
    assert sf["esl_layers"] == ["bottom", "top"] and sf["dt_out"] == pytest.approx(1e-3)
    assert fr["shear"]["convention"] == "engineering" and fr["shear"]["dump"]["convention"] == "engineering"
    assert any(w.startswith("STRAIN_TMAX_SAMPLED") for w in fr["warnings"])
    run = j("run.json")
    assert "strain_raw.csv" in run["inputs"]["results_files"]
    assert run["stages"]["extract"]["summary"]["strain_source"] == "strain_tensor"
    tj = j("02_tstar", "tstar.json")
    assert tj["selected"]["frame_index"] == synth_case.T_STAR_FRAME
    with np.load(os.path.join(out, "01_extract", "history.npz")) as z:
        from esl.mech import strain
        assert np.allclose(strain.eps_eq(z["eps"] * np.array([1, 1, 0.5], np.float32)), z["vm_hv"], rtol=1e-5)
        assert np.all(np.diff(z["vm_hv"], axis=0) >= 0)                          # 시간 누적 최대(max-hold)
    assert j("04_esl", "esl_summary.json")["strain_source"] == "strain_tensor"
    val = j("05_val", "validation.json")
    assert val["strain_source"] == "strain_tensor" and val["verdict"] == "PASS"
    assert val["criteria"]["layers"] == ["bottom", "top"]
    assert _metric(val, "hotspot1_strain_rel_err")["value"] is not None
    e = lib_entry.build(out)
    assert e.meta["quality"]["strain_source"] == "strain_tensor"
    html, _ = build_case_report(out)
    assert "대체: Strain 텐서 기준" in html


def test_plastic_strain_source_pipeline(tmp_path):
    c, out, j = _run(tmp_path, "plastic_strain")
    fr = j("01_extract", "frames.json")
    assert fr["strain_fallback"]["source"] == "plastic_strain"
    assert fr["shear"]["factor"] == 1.0 and fr["shear"]["skipped"] == "strain_source=plastic_strain"
    assert not any("HyperView vonMises 의 최대 상대 불일치" in w for w in fr["warnings"])
    tj = j("02_tstar", "tstar.json")
    h = tj["metrics"]["max_strain"]["history"]["m"]
    assert h == pytest.approx(tj["metrics"]["plastic_strain"]["history"]["m"])     # max_strain 계열 = epsp
    val = j("05_val", "validation.json")
    assert val["strain_source"] == "plastic_strain" and val["verdict"] == "PASS"
    assert _metric(val, "hotspot1_strain_rel_err")["value"] is not None
    assert lib_entry.build(out).meta["quality"]["strain_source"] == "plastic_strain"


def test_max_stress_source_skips_strain_reference(tmp_path):
    c, out, j = _run(tmp_path, "max_stress")
    fr = j("01_extract", "frames.json")
    assert fr["strain_fallback"]["source"] == "max_stress" and fr["shear"]["factor"] == 1.0
    tj = j("02_tstar", "tstar.json")
    assert tj["selected"]["frame_index"] == synth_case.T_STAR_FRAME                 # σ_vM 순위·t*
    val = j("05_val", "validation.json")
    assert val["strain_source"] == "max_stress" and val["verdict"] == "PASS"         # 판정 = 변위 주지표
    for name in ("hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct", "noise_hotspot_strain_rel"):
        m = _metric(val, name)
        assert m["value"] is None and m["status"] == "skipped" and m["exceeded"] is False, name
    assert val["field"]["skipped"] == "STRAIN_FROM_STRESS"
    run = j("run.json")
    ws = [w for st in run["stages"].values() for w in (st.get("warnings") or [])]
    assert any(str(w).startswith("STRAIN_FROM_STRESS") for w in ws)
    assert lib_entry.build(out).meta["quality"]["strain_source"] == "max_stress"
