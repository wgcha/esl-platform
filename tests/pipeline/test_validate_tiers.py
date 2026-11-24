"""v0.24.5 ④ 검증 판정 단계화(PASS · 조건부 PASS · FAIL) + MAC 판정 — 코어 시험(계약 docs/contracts/esl_validate_tiers.md §5,
V-0245-VT-1~7·10(코어)·12(코어)). 골든 = ``vt_golden``(코어 변경 전 77212df5 기록), 의도 차이 되돌림 = ``vt_compat``.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil

import numpy as np
import pytest

import vt_compat as VC
import vt_golden as G
from esl import config as cfgm
from esl import pipeline
from esl import val_metrics as vm
from esl import val_src as vs
from esl.errors import EslError
from esl.mech import bforce as bfm
from esl.mech import kabsch


@pytest.fixture(scope="module")
def golden_runs(tmp_path_factory):
    runs = {}
    for name in G.CASES:
        root = str(tmp_path_factory.mktemp(f"vt_{name}"))
        runs[name] = G.build_case(name, root)
    raw = os.environ.get("ESL_VT_RAW_DIR")                 # 개발용: 산출물 사본(비교 디버깅)
    if raw:
        for name, r in runs.items():
            dst = os.path.join(raw, name)
            if not os.path.exists(dst):
                shutil.copytree(r["out"], dst)
    return runs


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def _read(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


# ====================================================================== V-6 골든(v0.24.4 + 의도 차이만)
def back_hash(rel: str, out: str, root: str) -> str:
    """새 산출물 파일 → 의도 차이를 되돌린 뒤 골든과 같은 규칙의 해시."""
    p = os.path.join(out, rel)
    name = os.path.basename(rel)
    if name == "validation.json":
        return G.json_hash(VC.back_validation(_j(p)))
    if name == vs.SOURCES_JSON:
        return G.json_hash(VC.back_sources(_j(p), os.path.dirname(p)))
    if name == "validation.csv":
        return G.text_hash(VC.back_csv(_read(p), p, out), root)
    if name == "report.html":
        html = VC.back_report_html(out)
        return G.text_hash(_read(p) if html is None else html, root)
    return G.file_hash(p, root)


def test_v0245_vt_6_golden_v0244_plus_intended_only(golden_runs):
    """V-0245-VT-6: 05_val(루트·출처 폴더·sources.json)·06_export·07_report·단계 요약 = v0.24.4 기록값 + 의도 차이만.
    보고서: 되돌린 문서로 다시 그린 보고서 = 옛 바이트(옛 결과 재생성 = 저장 판정 그대로), 새 보고서는 5절 판정 머리·출처 표만 다름."""
    cur = {name: G.snapshot(r["out"], r["root"]) for name, r in golden_runs.items()}
    G.record_if_asked(cur)
    gold = G.load_golden()["cases"]
    assert set(gold) == set(G.CASES)
    for name, r in golden_runs.items():
        g = gold[name]
        assert set(cur[name]["files"]) == set(g["files"]), name                      # 파일 세트 불변
        diff = [f for f in sorted(g["files"]) if back_hash(f, r["out"], r["root"]) != g["files"][f]]
        assert diff == [], (name, diff)
        rj = _j(r["out"], pipeline.RUN_JSON)
        assert G.norm_summary(VC.back_summary(rj["stages"]["validate"]["summary"],
                                              os.path.join(r["out"], pipeline.D_VAL))) == g["summary"], name
        seg = cur[name]["report"]
        changed = sorted(k for k in g["report"] if seg.get(k) != g["report"][k])
        assert set(seg) == set(g["report"]), name
        assert set(changed) <= {"validation.judge", "validation.val_src"}, (name, changed)
        assert "validation.judge" in changed, name                                    # MAC 행·설명 문장(의도)
    # 옛 판정과 다른 출처(jig_disp·jig_spring: 1 % < RMS ≤ 10 % → DISP_RMS 가 FAIL 에서 조건부로) — 되돌림이 그것을 복원
    gj = G.load_golden()
    assert gj["recorded_at_commit"].startswith("77212df5")


def test_v0245_vt_7_sources_same_values_everywhere(golden_runs):
    """V-0245-VT-7: 출처 행마다 mac·grade·cond_reasons 가 sources.json 행·출처 validation.json·run.json 요약에서 같은 값."""
    seen = set()
    for name, r in golden_runs.items():
        out = r["out"]
        sj = _j(out, pipeline.D_VAL, vs.SOURCES_JSON)
        summ = _j(out, pipeline.RUN_JSON)["stages"]["validate"]["summary"]
        root = _j(out, pipeline.D_VAL, "validation.json")
        assert summ["mac"] == next(m["value"] for m in root["metrics"] if m["metric"] == "mac")
        assert summ["cond_reasons"] == root["cond_reasons"] and summ["verdict"] == root["verdict"]
        for row in sj["rows"]:
            ss = summ if vs.plan(row["key"])["legacy"] else summ["sources"][row["key"]]   # legacy 행 = 요약 루트
            assert ss["cond_reasons"] == row["cond_reasons"] and ss["mac"] == (row["metrics"] or {}).get("mac")
            if row["status"] != "done":
                assert row["verdict_scheme"] is None and row["cond_reasons"] == [] and ss["mac"] is None
                continue
            seen.add(row["key"])
            v = _j(out, pipeline.D_VAL, row["dir"] or "", "validation.json")
            mm = {m["metric"]: m for m in v["metrics"]}
            assert row["verdict_scheme"] == v["verdict_scheme"] == vm.VERDICT_SCHEME
            assert v["schema"] == vm.VALIDATION_SCHEMA
            assert row["metrics"]["mac"] == mm["mac"]["value"] == ss["mac"]
            assert row["verdict"] == v["verdict"] == ss["verdict"]
            assert row["cond_reasons"] == v["cond_reasons"] == ss["cond_reasons"]
            assert row["fail_reasons"] == v["fail_reasons"] == ss["fail_reasons"]
            judge = [m for m in v["metrics"] if m["role"] == "judge"]
            assert [m["metric"] for m in judge][:3] == ["disp_rms_rel", "disp_max_rel", "mac"]
            assert all(set(vm.FAIL_REASON) >= {m["metric"]} and "grade" in m for m in judge)
            assert (v["verdict"], v["fail_reasons"], v["cond_reasons"]) == vm.verdict_of(v["metrics"],
                                                                                          v["undetermined_reason"])
            assert vs.WARN_CODE not in row["limits"]
            assert {k: v["criteria"][k] for k in G_TIER_KEYS} == cfgm.validation_tier_settings(cfgm.load_config(r["cfg"]))
    assert seen == set(vs.KEYS)                                                       # 출처 6행 모두 검사


G_TIER_KEYS = tuple(cfgm.VALIDATION_TIER_DEFAULTS)


def test_v0245_vt_6_jig_values_and_old_key_explicit(golden_runs):
    """골든 설정(disp_rms_rel_max 0.01 명시 — Q-VT-1 명시값 존중): PASS ≤ 1 %·조건부 ≤ 10 % — 지그 변위·스프링 RMS ≈ 1.1 % 는
    DISP_RMS 조건부(옛 FAIL), DISP_MAX 는 단일 기준 FAIL 그대로. 지그 고정 MAC(검증) ≈ 0.61 → FAIL(MAC)."""
    out = golden_runs["jig"]["out"]
    rows = {x["key"]: x for x in _j(out, pipeline.D_VAL, vs.SOURCES_JSON)["rows"]}
    for k in ("jig_disp", "jig_spring"):
        r = rows[k]
        assert 0.01 < r["metrics"]["disp_rms_rel"] <= 0.10
        assert r["verdict"] == "FAIL" and r["fail_reasons"] == ["DISP_MAX"] and r["cond_reasons"] == ["DISP_RMS"]
        assert r["metrics"]["mac"] >= 0.95
    assert rows["jig"]["metrics"]["mac"] < 0.90 and "MAC" in rows["jig"]["fail_reasons"]
    v = _j(out, pipeline.D_VAL, "validation.json")
    c = v["criteria"]
    assert (c["disp_rms_rel_max"], c["disp_rms_rel_cond_max"], c["mac_min"], c["mac_cond_min"]) == (0.01, 0.10, 0.95, 0.90)


# ====================================================================== V-1 tier
def test_v0245_vt_1_tier_boundaries():
    assert vm.tier(0.05, 0.05, 0.10) == "PASS" and vm.tier(0.10, 0.05, 0.10) == "CONDITIONAL"     # 경계 포함
    assert vm.tier(0.1000001, 0.05, 0.10) == "FAIL"
    assert vm.tier(0.06, 0.05, None) == "FAIL" and vm.tier(0.05, 0.05) == "PASS"               # cond None = 단일
    assert vm.tier(0.95, 0.95, 0.90, "min") == "PASS" and vm.tier(0.90, 0.95, 0.90, "min") == "CONDITIONAL"
    assert vm.tier(0.8999, 0.95, 0.90, "min") == "FAIL"
    assert vm.tier(None, 0.05, 0.10) is None and vm.tier(None, 0.95, 0.9, "min") is None
    for bad in (float("inf"), float("-inf"), float("nan")):
        assert vm.tier(bad, 0.05, 0.10) == "FAIL" and vm.tier(bad, 0.95, 0.90, "min") == "FAIL"
    with pytest.raises(EslError) as ei:
        vm.tier(0.1, 0.05, None, "up")
    assert ei.value.code == "CONFIG_INVALID"
    assert vm.PASSING == ("PASS", "CONDITIONAL") and vm.is_passing("CONDITIONAL") and not vm.is_passing("FAIL")
    assert not vm.is_passing("UNDETERMINED") and not vm.is_passing(None) and vm.is_passing("PASS")


# ====================================================================== V-1·V-2 합성 행·종합
CCFG = {"max_err_pct_max": 10.0, "p90_err_max": 20.0}
CRIT = {"disp_rms_rel_max": 0.05, "disp_rms_rel_cond_max": 0.10, "disp_max_rel_max": 0.05, "mac_min": 0.95,
        "mac_cond_min": 0.90, "reaction_rel_max": 1e-6, "disp_noise_rel_max": 1e-3, "hotspot_strain_rel_err_max": 0.1,
        "noise_strain_rel_max": 0.05}
VALS = {"disp_rms_rel": 0.01, "disp_max_rel": 0.02, "mac": 0.99, "reaction_rel": 1e-9, "disp_noise_rel": 1e-6,
        "hotspot1_strain_rel_err": 0.01, "field_max_err_pct": 1.0, "field_p90_err_pct": 2.0,
        "noise_hotspot_strain_rel": 1e-4, "reaction_sum_rel": 1e-9, "u_rel_linear_rigid_rel": 1e-9,
        "noise_force_rel": 1e-4}


def _verdict(vals, crit=CRIT, role="judge", und=None):
    rows = vm.metric_rows({**VALS, **vals}, crit, CCFG, reaction_role=role)
    return rows, vm.verdict_of(rows, und)


@pytest.mark.parametrize("rms,grade", [(0.03, "PASS"), (0.07, "CONDITIONAL"), (0.12, "FAIL")])
def test_v0245_vt_1_rms_tiers(rms, grade):
    rows, (v, fail, cond) = _verdict({"disp_rms_rel": rms})
    r = rows[0]
    assert (r["metric"], r["grade"], r["criterion"], r["criterion_cond"], r["sense"]) == ("disp_rms_rel", grade, 0.05, 0.10,
                                                                                          "max")
    assert r["pass"] is (grade == "PASS")                                              # 조건부 행 pass false(보수적)
    assert v == grade and fail == (["DISP_RMS"] if grade == "FAIL" else []) and cond == (
        ["DISP_RMS"] if grade == "CONDITIONAL" else [])


@pytest.mark.parametrize("mac,grade", [(0.97, "PASS"), (0.92, "CONDITIONAL"), (0.85, "FAIL")])
def test_v0245_vt_1_mac_tiers(mac, grade):
    rows, (v, fail, cond) = _verdict({"mac": mac})
    r = next(x for x in rows if x["metric"] == "mac")
    assert (r["grade"], r["criterion"], r["criterion_cond"], r["sense"], r["role"]) == (grade, 0.95, 0.90, "min", "judge")
    assert v == grade and (fail, cond) == ((["MAC"], []) if grade == "FAIL" else ([], ["MAC"]) if grade == "CONDITIONAL"
                                           else ([], []))


def test_v0245_vt_2_verdict_order_and_rows():
    rows, _ = _verdict({})
    assert [m["metric"] for m in rows] == ["disp_rms_rel", "disp_max_rel", "mac", "reaction_rel", "disp_noise_rel",
                                           "hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct",
                                           "noise_hotspot_strain_rel", "reaction_sum_rel", "u_rel_linear_rigid_rel",
                                           "noise_force_rel"]                          # judge 5 · reference 4 · info 3
    assert [m["role"] for m in rows].count("judge") == 5
    assert all(set(m) >= {"grade", "criterion_cond", "sense"} for m in rows if m["role"] == "judge")
    assert all("grade" not in m for m in rows if m["role"] != "judge")
    assert list(rows[0])[:5] == ["metric", "value", "criterion", "pass", "role"]       # 옛 키 순서 그대로 + 새 키 끝
    assert _verdict({})[1] == ("PASS", [], [])
    assert _verdict({"disp_rms_rel": 0.07, "mac": 0.92})[1] == ("CONDITIONAL", [], ["DISP_RMS", "MAC"])
    # FAIL 우선(조건부 행 코드는 cond_reasons 에 남김 — 정보 보존), UNDETERMINED 최우선
    assert _verdict({"disp_rms_rel": 0.07, "disp_max_rel": 0.2})[1] == ("FAIL", ["DISP_MAX"], ["DISP_RMS"])
    assert _verdict({"disp_rms_rel": 0.2, "mac": 0.5}, und="NO_FULL_SOLVE")[1] == ("UNDETERMINED", [], [])
    # skipped judge = FAIL(불변), 응답 0 → MAC None → FAIL MAC
    rows, (v, fail, cond) = _verdict({"mac": None})
    m = next(x for x in rows if x["metric"] == "mac")
    assert m["status"] == "skipped" and m["grade"] is None and m["pass"] is None and (v, fail) == ("FAIL", ["MAC"])
    assert vm.verdict_of([], None) == ("PASS", [], [])                                 # 빈 목록 PASS
    # reaction_role info(지그): 반력 판정 제외 — 등급 키 없음
    rows, (v, *_r) = _verdict({"reaction_rel": 0.5}, role="info")
    r = next(x for x in rows if x["metric"] == "reaction_rel")
    assert r["role"] == "info" and "grade" not in r and v == "PASS"


@pytest.mark.parametrize("reac,grade", [(0.04, "PASS"), (0.07, "CONDITIONAL"), (0.12, "FAIL")])
def test_v0245_vt_5_reaction_warn_tiers_rows(reac, grade):
    """출처 반력 주의(§1.4): reaction_warn = PASS 상한·reaction_tol = 조건부 상한. full·bforce(주의 없음) = 단일."""
    crit = {**CRIT, "reaction_rel_max": 0.10, "reaction_warn_rel": 0.05}
    rows, (v, fail, cond) = _verdict({"reaction_rel": reac}, crit)
    r = next(x for x in rows if x["metric"] == "reaction_rel")
    assert (r["grade"], r["criterion"], r["criterion_cond"]) == (grade, 0.05, 0.10)
    assert v == grade and ("REACTION" in cond) is (grade == "CONDITIONAL") and ("REACTION" in fail) is (grade == "FAIL")
    rows, (v1, *_r) = _verdict({"reaction_rel": reac}, {**CRIT, "reaction_rel_max": 0.10})    # 주의 없음 = 단일 0.10
    r = next(x for x in rows if x["metric"] == "reaction_rel")
    assert r["criterion_cond"] is None and r["grade"] == ("FAIL" if reac > 0.10 else "PASS")
    row = vs.plan("fint")
    doc = {"verdict": v, "verdict_scheme": vm.VERDICT_SCHEME, "fail_reasons": fail, "cond_reasons": cond, "metrics": rows,
           "criteria": crit}
    sr = vs.done_row(row, doc, None)
    assert sr["reaction_warned"] is (grade == "CONDITIONAL") and vs.WARN_CODE not in sr["limits"]
    assert sr["cond_reasons"] == cond and sr["verdict_scheme"] == vm.VERDICT_SCHEME and sr["metrics"]["mac"] == VALS["mac"]


# ====================================================================== V-3 MAC
def test_v0245_vt_3_mac_definition():
    import synth_case

    assert vm.mac is bfm.mac                                                           # 식 복제 없음(같은 객체)
    X0, conn, et, thk = synth_case.plate()
    rng = np.random.default_rng(7)
    n = X0.shape[0]
    u_rel = 1e-2 * np.c_[np.sin(X0[:, 0] / 40.0), np.cos(X0[:, 1] / 30.0), X0[:, 0] * X0[:, 1] / 1e4]
    u_val = u_rel + 1e-4 * rng.standard_normal((n, 3))
    R = np.zeros((n, 3))
    F = np.ones((n, 3))
    kw = dict(top_n=5, hist_bins=10)
    nid = np.arange(1, n + 1)
    U = float(np.max(np.linalg.norm(u_rel, axis=1)))
    m0 = vm.disp_metrics(X0, u_rel, np.c_[u_val, np.zeros((n, 3))], R, F, [0, 1, 2], U, nid, **kw)
    d_rel = kabsch.remove_linear_rigid(X0, u_rel)[0]
    d_val = kabsch.remove_linear_rigid(X0, u_val)[0]
    assert m0["mac"] == bfm.mac(d_val, d_rel) and 0.9 < m0["mac"] < 1.0
    # u_val 에 선형 강체(미소 회전 + 병진)를 더해도 불변
    W = np.array([[0, -2e-4, 1e-4], [2e-4, 0, -3e-4], [-1e-4, 3e-4, 0]])
    u_rb = u_val + X0 @ W.T + np.array([0.3, -0.2, 0.1])
    m1 = vm.disp_metrics(X0, u_rel, np.c_[u_rb, np.zeros((n, 3))], R, F, [0, 1, 2], U, nid, **kw)
    assert m1["mac"] == pytest.approx(m0["mac"], rel=1e-9, abs=1e-12)
    m2 = vm.disp_metrics(X0, u_rel, np.c_[3.7 * u_val, np.zeros((n, 3))], R, F, [0, 1, 2], U, nid, **kw)
    assert m2["mac"] == pytest.approx(m0["mac"], rel=1e-12)                           # 배율 불변
    m3 = vm.disp_metrics(X0, u_rel, np.c_[u_rel, np.zeros((n, 3))], R, F, [0, 1, 2], U, nid, **kw)
    assert m3["mac"] == pytest.approx(1.0, abs=1e-12)                                  # 같은 변위 = 1
    m4 = vm.disp_metrics(X0, u_rel, np.zeros((n, 6)), R, F, [0, 1, 2], U, nid, **kw)
    assert m4["mac"] is None                                                           # 응답 0 → None
    rows = vm.metric_rows({**VALS, "mac": m4["mac"]}, CRIT, CCFG)
    assert vm.verdict_of(rows, None) == ("FAIL", ["MAC"], [])


# ====================================================================== V-4 설정
CFG_V072 = os.path.join(G.ROOT, "tests", "fixtures", "cumulative", "esl_v072.yaml")
SHA_V072 = "c254572d56829ed1e713be096bec394a4b4092c8a247a2b0e62e886d92e1f1ef"     # v0.24.4 코드(main 9b6b2587)로 계산한 값


def _cfg_sha(cfg):
    return hashlib.sha256(json.dumps(cfgm.redacted_settings(cfg), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _with(extra: dict):
    c = cfgm.load_config(CFG_V072)
    c["validation"].update(extra)
    return cfgm.validate_settings(c)


def test_v0245_vt_4_settings_defaults_not_injected_and_hash():
    c = cfgm.load_config(CFG_V072)
    assert not set(cfgm.VALIDATION_TIER_DEFAULTS) & set(c["validation"])            # 주입 없음
    assert _cfg_sha(c) == SHA_V072                                                     # 설정 해시 불변
    assert cfgm.validation_tier_settings(c) == {"disp_rms_rel_cond_max": 0.10, "mac_min": 0.95, "mac_cond_min": 0.90}
    assert c["validation"]["disp_rms_rel_max"] == 0.01                                 # 옛 키 0.01 명시 → 1 %/10 %(Q-VT-1)
    rows = vm.metric_rows({**VALS, "disp_rms_rel": 0.02}, {**CRIT, "disp_rms_rel_max": 0.01,
                                                           **cfgm.validation_tier_settings(c)}, CCFG)
    assert rows[0]["grade"] == "CONDITIONAL" and (rows[0]["criterion"], rows[0]["criterion_cond"]) == (0.01, 0.10)
    assert cfgm.VALIDATION_TIER_DEFAULTS == {"disp_rms_rel_cond_max": 0.10, "mac_min": 0.95, "mac_cond_min": 0.90}
    for k in cfgm.VALIDATION_TIER_DEFAULTS:
        assert f"validation.{k}" in cfgm.OPTIONAL_KEYS


def test_v0245_vt_4_settings_rules():
    assert cfgm.validation_tier_settings(_with({"disp_rms_rel_max": 0.2}))["disp_rms_rel_cond_max"] == 0.2   # 조건부 구간 0
    assert cfgm.validation_tier_settings(_with({"mac_min": 0.85}))["mac_cond_min"] == 0.85
    t = cfgm.validation_tier_settings(_with({"disp_rms_rel_cond_max": 0.2, "mac_min": 0.97, "mac_cond_min": 0.8}))
    assert t == {"disp_rms_rel_cond_max": 0.2, "mac_min": 0.97, "mac_cond_min": 0.8}
    for extra, key in [({"disp_rms_rel_cond_max": 0.005}, "validation.disp_rms_rel_cond_max"),     # 역전
                       ({"mac_min": 0.9, "mac_cond_min": 0.95}, "validation.mac_cond_min"),
                       ({"mac_cond_min": 0.96}, "validation.mac_cond_min"),                        # 기본 0.95 보다 큼
                       ({"mac_min": 0.0}, "validation.mac_min"), ({"mac_min": 1.01}, "validation.mac_min"),
                       ({"mac_cond_min": 0.0}, "validation.mac_cond_min"),
                       ({"disp_rms_rel_cond_max": 0.0}, "validation.disp_rms_rel_cond_max"),
                       ({"disp_rms_rel_cond_max": "x"}, "validation.disp_rms_rel_cond_max")]:
        with pytest.raises(EslError) as ei:
            _with(extra)
        assert ei.value.code == "CONFIG_INVALID" and key in str(ei.value), extra
    assert cfgm.validation_tier_settings(_with({"mac_min": 1.0}))["mac_min"] == 1.0


def test_v0245_vt_4_example_yaml():
    c = cfgm.load_config(os.path.join(G.ROOT, "config", "esl.example.yaml"))
    assert c["validation"]["disp_rms_rel_max"] == 0.05                                 # 0.01 → 0.05
    assert not set(cfgm.VALIDATION_TIER_DEFAULTS) & set(c["validation"])            # 새 키는 주석(선택 키 선례)
    txt = G._read(os.path.join(G.ROOT, "config", "esl.example.yaml"))
    for k, v in cfgm.VALIDATION_TIER_DEFAULTS.items():
        assert re.search(rf"\n  # {k}: {v:.2f}\s", txt), k                           # 같은 이름·같은 값


# ====================================================================== V-5 fint 반력 통합(검증만 다시)
def _revalidate(r, out):
    return pipeline.run(config_path=r["cfg"], rad=r["c"]["rad"], results=r["c"]["csv"], out=out, stage="validate",
                        echo=lambda *_: None)


@pytest.mark.parametrize("scale,grade", [(0.055, "PASS"), (0.10, "CONDITIONAL"), (0.17, "FAIL")])
def test_v0245_vt_5_fint_reaction_integration(golden_runs, tmp_path, scale, grade):
    """fint 불평형 하중 주입 → 반력 ≈ 4 % PASS, ≈ 7 % 조건부 PASS(cond_reasons REACTION·reaction_warned·한계 표식 없음),
    ≈ 12 % FAIL. full·bforce 반력 = 단일 기준 그대로."""
    r = golden_runs["bf"]
    out = os.path.join(str(tmp_path), "out")
    shutil.copytree(r["out"], out)
    p = os.path.join(out, pipeline.D_ESL, "fint.npz")
    z = dict(np.load(p, allow_pickle=False))
    z["f"] = z["f"].copy()
    z["f"][100] += scale * np.abs(z["f"]).max()
    np.savez_compressed(p, **z)
    rec = _revalidate(r, out)
    v = _j(out, pipeline.D_VAL, "fint", "validation.json")
    m = next(x for x in v["metrics"] if x["metric"] == "reaction_rel")
    row = {x["key"]: x for x in _j(out, pipeline.D_VAL, vs.SOURCES_JSON)["rows"]}
    band = {"PASS": (0.0, 0.05), "CONDITIONAL": (0.05, 0.10), "FAIL": (0.10, 1.0)}[grade]
    assert band[0] < m["value"] <= band[1], m["value"]
    assert (m["grade"], m["criterion"], m["criterion_cond"]) == (grade, 0.05, 0.10)
    f = row["fint"]
    assert f["reaction_warned"] is (grade == "CONDITIONAL") and vs.WARN_CODE not in f["limits"]
    assert ("REACTION" in f["cond_reasons"]) is (grade == "CONDITIONAL") and ("REACTION" in f["fail_reasons"]) is (
        grade == "FAIL")
    assert f["verdict"] != "PASS" or grade == "PASS"                                   # 주입 하중은 변위도 바꿈(다른 행 등급은 값대로)
    ss = rec["stages"]["validate"]["summary"]["sources"]["fint"]
    assert ss["cond_reasons"] == f["cond_reasons"] and ss["verdict"] == f["verdict"]
    for k in ("full", "bforce"):
        x = row[k]
        vv = _j(out, pipeline.D_VAL, x["dir"], "validation.json")
        mr = next(y for y in vv["metrics"] if y["metric"] == "reaction_rel")
        assert mr["criterion_cond"] is None and mr["criterion"] == 1e-6 and x["reaction_warn"] is None


# ====================================================================== V-10(코어) 정적 시험
GATE_FILES = ("esl/pipeline.py", "esl/library/cli.py", "esl/export/from_entry.py", "esl/library/report_analysis.py")


def test_v0245_vt_10_core_gates_no_direct_pass_compare():
    """§0.3 코어 게이트 파일: 문자열 "PASS" 와 직접 비교(== · != · in 리터럴) 0건 — 통과 판정은 val_metrics.is_passing·PASSING."""
    bad = []
    for rel in GATE_FILES:
        tree = ast.parse(G._read(os.path.join(G.ROOT, rel)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                sides = [node.left, *node.comparators]
                for s in sides:
                    vals = [s] + (list(s.elts) if isinstance(s, (ast.Tuple, ast.List, ast.Set)) else [])
                    if any(isinstance(x, ast.Constant) and x.value == "PASS" for x in vals):
                        bad.append(f"{rel}:{node.lineno}")
    assert bad == []
    for rel in ("esl/pipeline.py", "esl/library/cli.py", "esl/export/from_entry.py"):
        t = G._read(os.path.join(G.ROOT, rel))
        assert "_vm.is_passing(" in t or "_vm.export_warning(" in t, rel


# ====================================================================== V-12(코어) 보고서
def test_v0245_vt_12_report_new_rows_and_old_render(golden_runs):
    out = golden_runs["jig"]["out"]
    html = G._read(os.path.join(out, pipeline.D_REPORT, "report.html"))
    blk = html[html.index("<!--val-src-->"):html.index("<!--/val-src-->")]
    th = '<th class="num">MAC(검증)</th>'
    assert th in blk and blk.index("변위 최대/U</th>") < blk.index(th) < blk.index("반력 Σ‖R‖/Σ‖F‖</th>")
    assert "조건부 DISP_RMS" in blk                                                      # 지그 변위·스프링 cond 사유
    sec = html[html.index('<section id="validation">'):]
    sec = sec[:sec.index("</section>")]
    assert "판정 = 변위 지표 4 + MAC(검증), 단계 PASS·조건부 PASS·FAIL" in sec
    assert "<td>mac</td>" in sec and "≤ 0.01 / 조건부 ≤ 0.1" in sec and "≥ 0.95 / 조건부 ≥ 0.9" in sec
    assert '<td><span class="badge pass">PASS</span></td>' in sec                       # 등급 배지(통과/초과 아님)
    assert ".cond{" not in html                                                         # 조건부 배지 없음 → CSS 그대로
    # 옛 sources.json(mac 없음) → 출처 표 MAC "—", 옛 문서 → 옛 판정 머리 그대로(되돌림 재생성 = 골든 — V-6)
    old = VC.render_back(out)
    ob = old[old.index("<!--val-src-->"):old.index("<!--/val-src-->")]
    assert th in ob and ob.count('<td class="num">—</td>') >= 6 and "조건부" not in ob.replace(
        "단계(PASS·조건부 PASS·FAIL)", "")                                              # 옛 행: MAC "—"·단일 기준
    assert "<td>mac</td>" not in old and "판정 = 변위 4지표(전 노드" in old and "(허용치 ≤0.1)" in ob
    assert VC.strip_val_src_tiers(old) == VC.back_report_html(out)


def test_v0245_vt_12_report_conditional_badge(golden_runs, tmp_path):
    """root 판정이 조건부 PASS 인 Case(설정 disp_rms_rel_max 를 RMS 아래로) → 머리·5절 조건부 배지·cond 사유·CSS 추가."""
    r = golden_runs["bf"]
    out = os.path.join(str(tmp_path), "out")
    shutil.copytree(r["out"], out)
    v = _j(out, pipeline.D_VAL, "validation.json")
    rms = next(m["value"] for m in v["metrics"] if m["metric"] == "disp_rms_rel")
    txt = G._read(r["cfg"])
    txt = re.sub(r"\n  disp_rms_rel_max: [0-9.eE+-]+", f"\n  disp_rms_rel_max: {rms / 2:.6e}", txt)
    cfg = os.path.join(str(tmp_path), "cfg.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    lines = []
    rec = pipeline.run(config_path=cfg, rad=r["c"]["rad"], results=r["c"]["csv"], out=out, stage="validate",
                       echo=lines.append)
    st = rec["stages"]["validate"]
    assert st["summary"]["verdict"] == "CONDITIONAL" and st["summary"]["cond_reasons"] == ["DISP_RMS"]
    assert not [w for w in st["warnings"] if w.startswith("검증 FAIL")]                  # 조건부 = echo 만
    ln = next(x for x in lines if x.startswith("[validate] 변위 RMS="))
    assert "(PASS ≤" in ln and "· 조건부 ≤0.1)" in ln and "MAC(검증)=" in ln and ln.split(" → ")[1].startswith(
        "조건부 PASS ['DISP_RMS']")
    rec = pipeline.run(config_path=cfg, rad=r["c"]["rad"], results=r["c"]["csv"], out=out, stage="export",
                       echo=lambda *_: None)
    assert "검증 조건부 PASS 상태로 내보냄" in rec["stages"]["export"]["warnings"]
    vc = G._read(os.path.join(out, pipeline.D_EXPORT, "validation.csv")).splitlines()[1].split(",")
    assert vc[:2] == ["verdict", "CONDITIONAL"] and vc[3] == "0"                         # pass = PASS 일 때만
    pipeline.run(config_path=cfg, rad=r["c"]["rad"], results=r["c"]["csv"], out=out, stage="report", echo=lambda *_: None)
    html = G._read(os.path.join(out, pipeline.D_REPORT, "report.html"))
    assert "판정 " + '<span class="badge cond">조건부 PASS</span>' in html and ".cond{" in html
    assert '<span class="muted">조건부 DISP_RMS</span>' in html


def test_v0245_vt_12_library_analysis_verdict_labels():
    from esl.library import report_analysis as ra

    assert "조건부 PASS" in ra._verdict("CONDITIONAL") and "badge cond" in ra._verdict("CONDITIONAL")
    assert ra._verdict("PASS") == '<span class="badge pass">✓ PASS</span>' and ra._verdict(None) == '<span class="muted">—</span>'
    src = G._read(os.path.join(G.ROOT, "esl", "library", "report_analysis.py"))
    assert "PASS 비율(조건부 포함)" in src


def test_v0245_vt_10_cli_register_conditional_passes(monkeypatch, tmp_path):
    """CLI 등록: CONDITIONAL = 통과(--confirm-fail 불필요), FAIL = 지금처럼 거부."""
    from types import SimpleNamespace

    from esl.library import cli

    seen = {}

    class _E:
        def __init__(self, verdict):
            self.meta = {"quality": {"verdict": verdict}, "warnings": []}

    def fake_build(*a, **k):
        return _E(seen["v"])

    monkeypatch.setattr(cli.en, "build", fake_build)
    monkeypatch.setattr(cli.st, "load", lambda p: {"library": {"grid": {"nx": 1, "ny": 1}, "axis_ref": None,
                                                                "top_nodes": 1, "require_pass": True}})
    monkeypatch.setattr(cli.st, "scene_rules", lambda cfg: None)
    monkeypatch.setattr(cli.U, "Writer", lambda *a, **k: None)
    monkeypatch.setattr(cli.sto, "register", lambda *a, **k: {"entry_id": "e1", "product": "p", "inch": 1,
                                                              "scenario": "s", "drop_class": "d", "orient": "",
                                                              "scene": 1, "verdict": seen["v"]})
    monkeypatch.setattr(cli.sto, "entry_dir", lambda root, eid: str(tmp_path))
    a = SimpleNamespace(config="c", root=str(tmp_path), case=str(tmp_path), run_id=None, scene_path=None, mass=None,
                        by="t", confirm_fail=None, supersedes=None)
    for v in ("PASS", "CONDITIONAL"):
        seen["v"] = v
        assert cli.cmd_register(a, lambda *_: None)["verdict"] == v
    seen["v"] = "FAIL"
    with pytest.raises(EslError) as ei:
        cli.cmd_register(a, lambda *_: None)
    assert ei.value.code == "VALIDATION_NOT_PASS"


def test_v0245_vt_copy_semantics_unchanged():
    """judge 행 기준 해석 표(JUDGE_ROWS)가 FAIL_REASON 코드와 1:1, 모든 행에 모든 열."""
    cols = {"metric", "sense", "pass", "cond", "warn"}
    assert all(set(r) == cols for r in vm.JUDGE_ROWS)
    assert [r["metric"] for r in vm.JUDGE_ROWS] == list(vm.FAIL_REASON)
    assert all(r["sense"] in vm.SENSES for r in vm.JUDGE_ROWS)
    assert copy.deepcopy(vs.ROW_METRICS)[-1] == "mac"


# ====================================================================== V-8(코어) 옛 결과 = 저장 판정 그대로·바이트 불변
def _tree_sha(d):
    out = {}
    for dp, _dns, fns in os.walk(d):
        for f in fns:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, d)] = hashlib.sha256(fh.read()).hexdigest()
    return out


@pytest.mark.parametrize("name", ["jig", "never"])
def test_v0245_vt_8_old_results_report_stage_reads_only(golden_runs, tmp_path, name):
    """옛 형식 05_val(v0.24.4 와 같은 문서)로 report 단계 → 05_val 파일 바이트 불변(다시 쓰지 않음), 보고서 = v0.24.4 골든
    (출처 표의 MAC "—" 열·설명 끝 문장만 추가), 판정 머리 = 저장 판정(옛 단일 기준 — 재판정 없음)."""
    r = golden_runs[name]
    out = os.path.join(str(tmp_path), "out")
    shutil.copytree(r["out"], out)
    VC.back_tree(out)
    vd = os.path.join(out, pipeline.D_VAL)
    before = _tree_sha(vd)
    v = _j(vd, "validation.json")
    assert v["verdict_scheme"] == "disp_primary/1" and "cond_reasons" not in v
    rec = pipeline.run(config_path=r["cfg"], rad=r["c"]["rad"], results=r["c"]["csv"], out=out, stage="report",
                       echo=lambda *_: None)
    assert _tree_sha(vd) == before
    assert rec["stages"]["report"]["summary"]["verdict"] == v["verdict"]
    html = G._read(os.path.join(out, pipeline.D_REPORT, "report.html"))
    gold = G.load_golden()["cases"][name]
    html = VC.strip_val_src_tiers(html).replace(out, r["out"])           # 사본 경로 → 원 Case 경로(입력 경로는 같음)
    assert G.text_hash(html, r["root"]) == gold["files"]["07_report/report.html"]
