"""⑤ 검증 변위 주지표 판정(계약 esl_disp_primary.md, v0.5.7): 합성 E2E 산출물에서 validate 단계만 다시 돌려 확인.

V-DP-1 지표 수식(알려진 Δ, 지지 노드 포함) · V-DP-2 변위 잡음 δ/U(S4 값·재계산, 추가 solve 0회)
V-DP-3 변형률 참고만 초과 → PASS · V-DP-4 4지표 각각 → FAIL 코드 · V-DP-5 full_solve never → UNDETERMINED
V-DP-6 U=0 → ZERO_DISP · V-DP-7 초과·소성 집계 · V-DP-8 compare_disp.npz · V-DP-14 보고서 · V-DP-15 설정.
"""
import csv
import json
import os
import re
import shutil

import numpy as np
import pytest

import synth_case
from esl import config, pipeline
from esl.mech import kabsch
from esl.mech.shell import ShellModel
from esl.report import case_report
from esl.report import field as F

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("dp"))
    c = synth_case.build(root)
    c["cfg"] = os.path.join(root, "esl64.yaml")
    with open(c["cfg"], "w", encoding="utf-8") as fh:
        fh.write(CFG64_TEXT)
    c["out"] = os.path.join(root, "out")
    c["rec"] = pipeline.run(config_path=c["cfg"], rad=c["rad"], results=c["csv"], out=c["out"], stage="all",
                            echo=lambda m: None)
    c["root"] = root
    return c


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def _validate(base, tmp_path, *pairs, mutate=None, tag="v"):
    """out 복사본에서 설정을 바꿔(pairs = (원문, 대체)) validate 단계만 실행 → (validation.json, out, rec)."""
    out = str(tmp_path / f"out_{tag}")
    shutil.copytree(base["out"], out)
    txt = CFG64_TEXT
    for a, b in pairs:
        assert a in txt, a
        txt = txt.replace(a, b)
    cfg = str(tmp_path / f"cfg_{tag}.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    if mutate:
        mutate(out)
    rec = pipeline.run(config_path=cfg, rad=base["rad"], results=base["csv"], out=out, stage="validate",
                       echo=lambda m: None)
    return _j(out, "05_val", "validation.json"), out, rec


def _m(val):
    return {x["metric"]: x for x in val["metrics"]}


# ---------------------------------------------------------------- 기본 산출물·스키마
def test_default_run_is_pass_with_new_schema(base):
    val = _j(base["out"], "05_val", "validation.json")
    assert val["schema"] == "esl/validation/3" and val["verdict_scheme"] == "disp_primary/1"
    assert val["verdict"] == "PASS" and val["fail_reasons"] == [] and val["undetermined_reason"] is None
    m = _m(val)
    roles = {k: v["role"] for k, v in m.items()}
    assert [k for k, r in roles.items() if r == "judge"] == ["disp_rms_rel", "disp_max_rel", "reaction_rel", "disp_noise_rel"]
    assert {k for k, r in roles.items() if r == "reference"} == {
        "hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct", "noise_hotspot_strain_rel"}
    assert all(m[k]["pass"] is None and isinstance(m[k]["exceeded"], bool) for k in roles if roles[k] == "reference")
    assert all(m[k]["pass"] is True for k in roles if roles[k] == "judge")
    assert val["criteria"]["disp_max_rel_max"] == 0.05 and val["criteria"]["disp_noise_rel_max"] == 1e-3
    assert val["noise_source"] == "esl_summary" and val["strain_ref"]["exceeded"] is False
    rec = base["rec"]["stages"]["validate"]["summary"]
    assert rec["disp_max_rel"] == m["disp_max_rel"]["value"] and rec["disp_noise_rel"] == m["disp_noise_rel"]["value"]
    assert rec["undetermined_reason"] is None and rec["strain_ref"]["n_exceed"] == val["strain_ref"]["n_exceed"]
    assert val["disp"]["n_nodes"] == len(base["node_id"]) and val["disp"]["n_support"] == 3
    # validation.csv: 첫 행 verdict, role 열, reference 행의 pass 열 = exceeded
    rows = list(csv.reader(open(os.path.join(base["out"], "05_val", "validation.csv"), encoding="utf-8")))
    assert rows[0] == ["metric", "value", "criterion", "pass", "role"] and rows[1][0] == "verdict" and rows[1][1] == "PASS"
    byname = {r[0]: r for r in rows[2:] if len(r) == 5}
    assert byname["disp_rms_rel"][4] == "judge" and byname["hotspot1_strain_rel_err"][4] == "reference"
    assert byname["hotspot1_strain_rel_err"][3] == "0" and byname["noise_force_rel"][4] == "info"


# ---------------------------------------------------------------- V-DP-1
def test_dp1_metrics_match_formula_with_known_delta_including_support(base, tmp_path, monkeypatch):
    out = str(tmp_path / "out_d")
    shutil.copytree(base["out"], out)
    ur = np.load(os.path.join(out, "04_esl", "u_rel.npz"), allow_pickle=False)
    nid, u_rel = ur["node_id"], ur["u_rel"]
    X0 = np.load(os.path.join(out, "01_extract", "model.npz"), allow_pickle=False)["x0"]
    sup = _j(out, "03_bc", "support.json")["supports"]
    sup_idx = [int(np.flatnonzero(nid == s["node_id"])[0]) for s in sup]
    N = nid.size
    rng = np.random.default_rng(3)
    delta = 1e-4 * rng.normal(size=(N, 3))
    delta[sup_idx[0]] += np.array([0.2, -0.1, 0.05])               # 지지 노드의 큰 차이도 분포에 포함돼야 함
    delta[7] += np.array([0.0, 0.0, 0.1])
    seen = {}
    orig = ShellModel.solve

    def patched(self, Fv, spc):
        u, R = orig(self, Fv, spc)
        seen["u"] = u[:, :3].copy()
        u = u.copy()
        u[:, :3] += delta
        return u, R

    monkeypatch.setattr(ShellModel, "solve", patched)
    pipeline.run(config_path=base["cfg"], rad=base["rad"], results=base["csv"], out=out, stage="validate",
                 echo=lambda m: None)
    val = _j(out, "05_val", "validation.json")
    d_val, _, _ = kabsch.remove_linear_rigid(X0, seen["u"] + delta)
    d_rel, _, _ = kabsch.remove_linear_rigid(X0, u_rel)
    e = np.linalg.norm(d_val - d_rel, axis=1)
    U = float(np.max(np.linalg.norm(u_rel, axis=1)))                # 분모 = 강체 제거 전 max|u_rel|
    m = _m(val)
    assert m["disp_rms_rel"]["value"] == pytest.approx(np.sqrt(np.mean(e ** 2)) / U, rel=1e-12)
    assert m["disp_max_rel"]["value"] == pytest.approx(e.max() / U, rel=1e-12)
    assert val["disp"]["U"] == pytest.approx(U, rel=1e-14)
    # 지지 노드를 빼면 값이 달라진다 = 지지 노드가 실제로 포함됨
    keep = np.ones(N, bool)
    keep[sup_idx] = False
    assert abs(np.sqrt(np.mean(e[keep] ** 2)) / U - m["disp_rms_rel"]["value"]) > 1e-6
    crit = val["criteria"]
    expect = [c for c, v, t in (("DISP_RMS", m["disp_rms_rel"]["value"], crit["disp_rms_rel_max"]),
                                ("DISP_MAX", m["disp_max_rel"]["value"], crit["disp_max_rel_max"])) if v > t]
    assert "DISP_MAX" in expect                                        # 최대 오차(지지 노드)가 기준 초과
    assert val["verdict"] == "FAIL" and val["fail_reasons"] == expect
    # compare_disp.npz 와 일치
    z = np.load(os.path.join(out, "05_val", "compare_disp.npz"), allow_pickle=False)
    assert np.allclose(z["e"], e, rtol=1e-12, atol=0) and float(z["U"]) == pytest.approx(U)
    assert z["is_support"].sum() == 3 and bool(z["is_support"][sup_idx[0]])


# ---------------------------------------------------------------- V-DP-2
def test_dp2_disp_noise_from_summary_and_recomputed_without_extra_solve(base, tmp_path, monkeypatch):
    calls = {"n": 0}
    orig = ShellModel.solve

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(ShellModel, "solve", counting)
    val, out, _ = _validate(base, tmp_path, tag="a")
    assert calls["n"] == 1                                           # 전체 해석 1회뿐(잡음용 추가 해석 없음)
    summ = _j(out, "04_esl", "esl_summary.json")
    U = float(np.max(np.linalg.norm(np.load(os.path.join(out, "04_esl", "u_rel.npz"))["u_rel"], axis=1)))
    m = _m(val)
    assert val["noise_source"] == "esl_summary"
    assert m["disp_noise_rel"]["value"] == pytest.approx(summ["noise"]["delta"] / U, rel=1e-13)
    assert m["disp_noise_rel"]["criterion"] == 1e-3 and m["disp_noise_rel"]["pass"] is True

    def drop_noise(o):
        p = os.path.join(o, "04_esl", "esl_summary.json")
        s = _j(o, "04_esl", "esl_summary.json")
        s.pop("noise")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(s, fh)

    calls["n"] = 0
    val2, out2, rec2 = _validate(base, tmp_path, mutate=drop_noise, tag="b")
    assert calls["n"] == 1 and val2["noise_source"] == "recomputed"
    assert _m(val2)["disp_noise_rel"]["value"] == pytest.approx(_m(val)["disp_noise_rel"]["value"], rel=1e-13)
    assert val2["verdict"] == "PASS" and val2["noise"] is None
    assert any("잡음" in w for w in rec2["stages"]["validate"]["warnings"])


# ---------------------------------------------------------------- V-DP-3
def test_dp3_strain_reference_exceeded_but_disp_pass_is_pass(base, tmp_path):
    val, out, rec = _validate(
        base, tmp_path,
        ("hotspot_strain_rel_err_max: 0.10", "hotspot_strain_rel_err_max: 1.0e-30"),
        ("noise_strain_rel_max: 0.05", "noise_strain_rel_max: 1.0e-30"),
        ("max_err_pct_max: 10.0", "max_err_pct_max: 1.0e-30"), ("p90_err_max: 20.0", "p90_err_max: 1.0e-30"))
    m = _m(val)
    assert all(m[k]["exceeded"] is True for k in ("hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct",
                                                    "noise_hotspot_strain_rel"))
    assert val["verdict"] == "PASS" and val["fail_reasons"] == [] and val["strain_ref"]["exceeded"] is True
    assert set(val["strain_ref"]["exceeded_metrics"]) == {"hotspot1_strain_rel_err", "field_max_err_pct",
                                                           "field_p90_err_pct", "noise_hotspot_strain_rel"}
    assert rec["stages"]["validate"]["summary"]["verdict"] == "PASS"
    assert not any("FAIL" in w for w in rec["stages"]["validate"]["warnings"])        # 경고 문구 없음(D6)


# ---------------------------------------------------------------- V-DP-4
@pytest.mark.parametrize("key,old,code", [
    ("disp_rms_rel", "disp_rms_rel_max: 0.01 ", "DISP_RMS"),
    ("disp_max_rel", "disp_max_rel_max: 0.05 ", "DISP_MAX"),
    ("reaction_rel", "reaction_rel_max: 1.0e-6 ", "REACTION"),
    ("disp_noise_rel", "disp_noise_rel_max: 1.0e-3 ", "DISP_NOISE")])
def test_dp4_each_judge_metric_alone_fails_with_its_code(base, tmp_path, key, old, code):
    name = old.split(":")[0]
    val, _, rec = _validate(base, tmp_path, (old, f"{name}: 1.0e-30 "), tag=key)
    m = _m(val)
    assert val["verdict"] == "FAIL" and val["fail_reasons"] == [code]
    assert [k for k, x in m.items() if x["role"] == "judge" and x["pass"] is False] == [key]
    assert any(code in w for w in rec["stages"]["validate"]["warnings"])


# ---------------------------------------------------------------- V-DP-5
def test_dp5_full_solve_never_is_undetermined(base, tmp_path):
    val, out, rec = _validate(base, tmp_path, ("full_solve: auto", "full_solve: never"))
    m = _m(val)
    assert val["verdict"] == "UNDETERMINED" and val["undetermined_reason"] == "NO_FULL_SOLVE" and val["fail_reasons"] == []
    assert val["disp"] is None and val["verdict_scheme"] == "disp_primary/1"
    for k in ("disp_rms_rel", "disp_max_rel", "reaction_rel"):
        assert m[k]["value"] is None and m[k]["pass"] is None and m[k]["status"] == "skipped"
    assert m["disp_noise_rel"]["value"] is not None and m["disp_noise_rel"]["pass"] is True    # 값은 기록
    assert not os.path.exists(os.path.join(out, "05_val", "compare_disp.npz"))
    assert not os.path.exists(os.path.join(out, "05_val", "compare.csv"))
    sr = val["strain_ref"]                                                                    # 변형률 참고는 계산됨
    assert sr["n_elems"] == len(base["elem_id"]) and sr["n_exceed"] >= 0 and "p99_err_pct" in sr
    z = np.load(os.path.join(out, "05_val", "compare_field.npz"), allow_pickle=False)
    assert {"epsp", "plastic", "exceed"} <= set(z.files)
    assert rec["stages"]["validate"]["summary"]["verdict"] == "UNDETERMINED"
    # UNDETERMINED 는 변형률이 좋아도 PASS 가 아니고, 잡음 바닥이 기준을 넘어도 UNDETERMINED 가 우선
    val2, _, _ = _validate(base, tmp_path, ("full_solve: auto", "full_solve: never"),
                           ("disp_noise_rel_max: 1.0e-3 ", "disp_noise_rel_max: 1.0e-30 "), tag="n")
    assert val2["verdict"] == "UNDETERMINED" and val2["fail_reasons"] == [] and _m(val2)["disp_noise_rel"]["pass"] is False


# ---------------------------------------------------------------- V-DP-6
def test_dp6_zero_displacement_is_undetermined_zero_disp(base, tmp_path):
    def zero_u(o):
        p = os.path.join(o, "04_esl", "u_rel.npz")
        z = dict(np.load(p, allow_pickle=False))
        z["u_rel"] = np.zeros_like(z["u_rel"])
        np.savez_compressed(p, **z)

    val, out, rec = _validate(base, tmp_path, mutate=zero_u)
    assert val["verdict"] == "UNDETERMINED" and val["undetermined_reason"] == "ZERO_DISP" and val["fail_reasons"] == []
    assert val["disp"] is None and not os.path.exists(os.path.join(out, "05_val", "compare_disp.npz"))
    assert _m(val)["disp_noise_rel"]["value"] is None


# ---------------------------------------------------------------- V-DP-7
def test_dp7_strain_reference_matches_fixture_arrays(base, tmp_path):
    z0 = np.load(os.path.join(base["out"], "05_val", "compare_field.npz"), allow_pickle=False)
    a = np.sort(100 * np.abs(z0["rel_err"][z0["valid"]]))
    thr = float(a[len(a) // 2])                                     # 중앙값 → 대략 절반이 초과
    val, out, _ = _validate(base, tmp_path, ("max_err_pct_max: 10.0", f"max_err_pct_max: {thr!r}"))
    z = np.load(os.path.join(out, "05_val", "compare_field.npz"), allow_pickle=False)
    valid, rel = z["valid"], z["rel_err"]
    exceed = valid & (100 * np.abs(rel) > thr)
    with np.load(os.path.join(out, "01_extract", "strain_frames.npz"), allow_pickle=False) as sf:
        fd = int(np.flatnonzero(sf["frame_index"] == val["frame"]["frame_index"])[0])
        plastic = np.asarray(sf["epsp"][fd], np.float64) > 0
    sr = val["strain_ref"]
    E = len(base["elem_id"])
    assert 0 < sr["n_exceed"] < sr["n_valid"] and sr["n_exceed"] == int(exceed.sum())
    assert sr["frac_exceed"] == pytest.approx(sr["n_exceed"] / E) and sr["frac_exceed_valid"] == pytest.approx(
        sr["n_exceed"] / int(valid.sum()))
    assert sr["p99_err_pct"] == pytest.approx(np.percentile(100 * np.abs(rel[valid]), 99))
    assert val["field"]["abs_err_pct"]["p99"] == pytest.approx(sr["p99_err_pct"])
    assert plastic.any() and sr["plastic"]["n_plastic"] == int(plastic.sum())
    assert sr["plastic"]["n_exceed_plastic"] == int((exceed & plastic).sum())
    assert sr["plastic"]["frac_plastic"] == pytest.approx(plastic.sum() / E)
    assert np.array_equal(z["exceed"], exceed) and np.array_equal(z["plastic"], plastic)
    assert z["epsp"].dtype == np.float64 and z["epsp"].shape == (E,)
    # epsp 가 없으면 plastic null, epsp 열은 NaN
    def strip(o):
        p = os.path.join(o, "01_extract", "strain_frames.npz")
        d = {k: v for k, v in np.load(p, allow_pickle=False).items() if k != "epsp"}
        np.savez_compressed(p, **d)

    val2, out2, _ = _validate(base, tmp_path, mutate=strip, tag="noepsp")
    assert val2["strain_ref"]["plastic"] is None
    z2 = np.load(os.path.join(out2, "05_val", "compare_field.npz"), allow_pickle=False)
    assert np.isnan(z2["epsp"]).all() and not z2["plastic"].any()


# ---------------------------------------------------------------- V-DP-8
def test_dp8_compare_disp_npz_keys_dtypes_and_summary(base):
    p = os.path.join(base["out"], "05_val", "compare_disp.npz")
    z = np.load(p, allow_pickle=False)                              # allow_pickle=False 로 읽힘
    N = len(base["node_id"])
    spec = {"node_id": ("i", (N,)), "ab": ("f", (N, 2)), "d_rel": ("f", (N, 3)), "d_val": ("f", (N, 3)),
            "e": ("f", (N,)), "is_support": ("b", (N,)), "U": ("f", ()), "plane_origin": ("f", (3,)),
            "plane_e1": ("f", (3,)), "plane_e2": ("f", (3,)), "plane_n": ("f", (3,))}
    assert set(spec) <= set(z.files)
    for k, (kind, shape) in spec.items():
        assert z[k].dtype.kind == kind and z[k].shape == shape, k
    assert z["node_id"].dtype == np.int64 and np.array_equal(z["node_id"], base["node_id"])
    val = _j(base["out"], "05_val", "validation.json")
    d = val["disp"]
    assert d["hist"]["n"] == N and len(d["hist"]["edges_log10"]) == len(d["hist"]["counts"]) + 1
    assert sum(d["hist"]["counts"]) + d["hist"]["n_zero"] == N
    assert len(d["top"]) == val["criteria"].get("disp_top_n", 20) or len(d["top"]) == 20
    r = [t["r"] for t in d["top"]]
    assert r == sorted(r, reverse=True) and d["max_rel"] == r[0] and d["max_node_id"] == d["top"][0]["node_id"]
    assert {s["node_id"] for s in d["support"]} == {s["node_id"] for s in _j(base["out"], "03_bc", "support.json")["supports"]}
    assert np.allclose(z["e"] / float(z["U"]), [x for x in z["e"] / float(z["U"])])
    assert d["rms_rel"] == _m(val)["disp_rms_rel"]["value"] and d["max_rel"] == _m(val)["disp_max_rel"]["value"]


# ---------------------------------------------------------------- V-DP-14 보고서
def _report(out):
    doc, info = case_report.build_case_report(out)
    return doc, info


def test_dp14_report_status_badges_and_tables(base, tmp_path):
    doc, info = _report(base["out"])
    assert info["status"] == "PASS" and 'class="badge pass">PASS' in doc
    sec = re.search(r'<section id="validation">(.*?)</section>', doc, re.S).group(1)
    for k in ("disp_rms_rel", "disp_max_rel", "reaction_rel", "disp_noise_rel"):
        assert k in sec
    assert "변형률 (참고 — 판정 아님)" in sec and "기준 초과 요소" in sec and "소성 영역" in sec and "|오차| P99" in sec
    assert "변위 비교 (전 노드)" in sec and "수치 일관성" in sec and "log10" in sec and "상위 노드" in sec
    ref_part = sec.split("변형률 (참고 — 판정 아님)")[1]
    assert "hotspot1_strain_rel_err" in ref_part and "hotspot1_strain_rel_err" not in sec.split("변형률 (참고")[0].split("<h3>")[0]
    # UNDETERMINED
    _, out, _ = _validate(base, tmp_path, ("full_solve: auto", "full_solve: never"), tag="r_und")
    doc, info = _report(out)
    sec = re.search(r'<section id="validation">(.*?)</section>', doc, re.S).group(1)
    assert info["status"] == "UNDETERMINED" and "판정 불가" in sec and "전체 재해석 생략" in sec
    assert "변위 비교 (전 노드)" not in sec
    # FAIL
    _, out, _ = _validate(base, tmp_path, ("reaction_rel_max: 1.0e-6 ", "reaction_rel_max: 1.0e-30 "), tag="r_fail")
    doc, info = _report(out)
    assert info["status"] == "FAIL" and 'class="badge fail">FAIL' in doc and "REACTION" in doc
    # LEGACY: schema 2 validation.json (verdict_scheme 없음) → "이전 판정 체계" + 당시 verdict
    def legacy(o):
        p = os.path.join(o, "05_val", "validation.json")
        v = _j(o, "05_val", "validation.json")
        for k in ("verdict_scheme", "undetermined_reason", "disp", "strain_ref", "noise_source"):
            v.pop(k, None)
        v["schema"] = "esl/validation/2"
        v["metrics"] = [{k: x for k, x in m.items() if k not in ("role", "exceeded")} for m in v["metrics"]]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(v, fh)

    legacy(out)
    doc, info = _report(out)
    sec = re.search(r'<section id="validation">(.*?)</section>', doc, re.S).group(1)
    assert info["status"] == "LEGACY" and "이전 판정 체계" in doc and "당시 FAIL" in sec
    assert "변형률 (참고 — 판정 아님)" not in sec


# ---------------------------------------------------------------- V-DP-15 설정
def test_dp15_config_new_keys_defaults_and_example_yaml():
    import yaml

    ex = yaml.safe_load(open(CFG, encoding="utf-8"))
    v = ex["validation"]
    assert (v["disp_rms_rel_max"], v["disp_max_rel_max"], v["reaction_rel_max"], v["disp_noise_rel_max"],
            v["disp_top_n"], v["disp_hist_bins"]) == (0.01, 0.05, 1e-6, 1e-3, 20, 20)
    cfg = config.load_config(CFG)                                   # 예시 yaml 로드
    assert cfg["validation"]["disp_max_rel_max"] == 0.05
    # 신규 키가 없는 이전 설정 파일 → 기본값(esl/config.py 한 곳)
    old = yaml.safe_load(open(CFG, encoding="utf-8"))
    for k in config.VALIDATION_DEFAULTS:
        old["validation"].pop(k)
    got = config.validate_settings(old)
    assert {k: got["validation"][k] for k in config.VALIDATION_DEFAULTS} == config.VALIDATION_DEFAULTS == {
        "disp_max_rel_max": 0.05, "disp_noise_rel_max": 1e-3, "disp_top_n": 20, "disp_hist_bins": 20}
    # 범위 검사
    bad = yaml.safe_load(open(CFG, encoding="utf-8"))
    bad["validation"]["disp_max_rel_max"] = 0
    with pytest.raises(Exception):
        config.validate_settings(bad)
    # V-CFG-2: 판정 코드에 기준 숫자 리터럴(0.05·1e-3·0.01 등)이 없다 — 기준값은 설정/VALIDATION_DEFAULTS 에서만
    src = open(os.path.join(ROOT, "esl", "pipeline.py"), encoding="utf-8").read()
    body = src[src.index("def stage_validate"):src.index("# ====================================================================== export")]
    code = "\n".join(re.sub(r"#.*$", "", ln) for ln in body.splitlines())
    code = re.sub(r'f?"[^"\n]*"|f?\'[^\'\n]*\'', '""', code)         # 문자열(로그 문구) 제거
    for lit in ("0.05", "1e-3", "1.0e-3", "0.01", "1e-6", "1.0e-6", "0.10"):
        assert lit not in code, lit
