"""변위 정밀도 잡음 바닥(S4 noise, S5 NOISE_FLOOR).

- float32 로 양자화한 변위(verify/pipe32.py 재현) + disp_precision=float32 → 경고 + verdict FAIL(NOISE_FLOOR).
- δ = 0.5·ulp·max|X0+u| (float32 → 2^-24·max|x|), 고정 시드 → 결정적.
"""
import csv
import io
import json
import os
import shutil
from contextlib import redirect_stdout

import numpy as np
import pytest

import synth_case
from esl import cli, config, pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")


def _quantize_disp_f32(csv_dir):
    p = os.path.join(csv_dir, "disp.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(rows[0]) + "\n")
        for r in rows[1:]:
            fh.write(",".join(r[:2] + [repr(float(np.float32(float(x)))) for x in r[2:]]) + "\n")


@pytest.fixture(scope="module")
def f32(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("f32"))
    c = synth_case.build(root)
    _quantize_disp_f32(c["csv"])
    out = os.path.join(root, "out")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["run", "--config", CFG, "--rad", c["rad"], "--results", c["csv"], "--out", out])
    c.update(out=out, rc=rc, stdout=buf.getvalue())
    return c


def _j(*p):
    return json.load(open(os.path.join(*p), encoding="utf-8"))


def test_float32_e2e_warns_and_fails(f32):
    assert f32["rc"] == 0                                    # 계산 자체는 성공, 판정만 FAIL
    out = f32["out"]
    summ = _j(out, "04_esl", "esl_summary.json")
    n = summ["noise"]
    assert n["disp_precision"] == "float32" and n["n_samples"] == 3
    assert n["delta"] == pytest.approx(2.0 ** -24 * n["x_abs_max"], rel=1e-12)
    assert n["force_rel"] > 0.1                              # 경고 기준 초과
    assert n["hotspot_strain_rel"] > 0.05                    # FAIL 기준 초과
    assert len(n["hotspot_elem_id"]) == 3
    val = _j(out, "05_val", "validation.json")
    assert val["verdict"] == "FAIL" and val["fail_reasons"] == ["NOISE_FLOOR"]
    m = {x["metric"]: x for x in val["metrics"]}
    assert m["noise_hotspot_strain_rel"]["pass"] is False
    assert m["noise_hotspot_strain_rel"]["criterion"] == 0.05
    run = _j(out, "run.json")
    es = run["stages"]["esl"]
    assert es["summary"]["noise"]["force_rel"] == n["force_rel"]
    assert any("잡음 바닥" in w and "F_eq" in w for w in es["warnings"])
    assert run["stages"]["validate"]["summary"]["fail_reasons"] == ["NOISE_FLOOR"]
    s = f32["stdout"]
    assert "잡음 바닥(float32" in s and "force_rel=" in s and "hotspot_strain_rel=" in s
    assert "NOISE_FLOOR" in s and "→ FAIL" in s
    print(f"\nfloat32 E2E: noise.force_rel={n['force_rel']:.3e}, hotspot_strain_rel={n['hotspot_strain_rel']:.3e}")


def test_float32_data_with_float64_setting_is_not_flagged(f32, tmp_path):
    """설정이 데이터 정밀도를 결정: float64 로 선언하면 잡음 바닥은 무시할 수준(사용자 책임)."""
    cfg = tmp_path / "c64.yaml"
    cfg.write_text(open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64"),
                   encoding="utf-8")
    out = str(tmp_path / "o")
    shutil.copytree(f32["out"], out)
    assert cli.main(["run", "--config", str(cfg), "--rad", f32["rad"], "--results", f32["csv"], "--out", out,
                     "--stage", "esl"]) == 0
    n = _j(out, "04_esl", "esl_summary.json")["noise"]
    assert n["disp_precision"] == "float64" and n["hotspot_strain_rel"] < 1e-6


def test_noise_floor_unit_deterministic_and_scales():
    X0, conn, et, thk = synth_case.plate(nx=12, ny=8)
    from esl.mech.shell import ShellModel
    sm = ShellModel(X0, conn, et, thk, 2.1e5, 0.3)
    u_rel = 1e-2 * np.sin(X0 / 37.0) * np.array([0.2, 0.3, 1.0])
    F = sm.condensed_forces(u_rel)
    base = config.load_config(CFG)
    res = {}
    for prec in ("float32", "float64"):
        cfg = json.loads(json.dumps(base))
        cfg["extract"]["disp_precision"] = prec
        ctx = pipeline.Context(cfg=cfg, config_path="", rad="", results="", out="", ts="", frame=None,
                               support_nodes=None, echo=print, record={})
        a = pipeline.noise_floor(ctx, sm, X0, u_rel, u_rel, F, [0, 5, 9])
        b = pipeline.noise_floor(ctx, sm, X0, u_rel, u_rel, F, [0, 5, 9])
        assert a == b                                         # 고정 시드
        assert a["delta"] == pytest.approx(0.5 * np.finfo(np.dtype(prec)).eps * np.abs(X0 + u_rel).max())
        res[prec] = a
    assert res["float32"]["force_rel"] > 1e6 * res["float64"]["force_rel"]
