"""v0.24.3 ④ 검증 출처 계획 표·순수 지표(계약 esl_validate_sources.md §2·§3·§5·§10, V-0243-VAL-2·4·5 순수 부분)."""

from __future__ import annotations

import os
import re
import subprocess
import sys

import numpy as np
import pytest

from esl import val_metrics as vm
from esl import val_src as vs
from esl import view3d_src
from esl.errors import EslError
from esl.mech import bforce as bfm
from esl.mech import kabsch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- V-4 계획 표
def test_v4_plan_keys_columns_legacy_dirs():
    from esl.doe import stages as stg

    assert vs.KEYS is view3d_src.KEYS
    assert tuple(r["key"] for r in vs.VAL_PLAN) == vs.KEYS == tuple(r["key"] for r in stg.RANK_SOURCES)
    assert tuple(r["key"] for r in view3d_src.CASE_PLAN) == vs.KEYS
    assert all(tuple(r) == vs.COLUMNS for r in vs.VAL_PLAN)                  # 모든 행 모든 열(같은 순서)
    leg = [r for r in vs.VAL_PLAN if r["legacy"]]
    assert len(leg) == 1 and leg[0]["key"] == vs.legacy_key() == "full" and leg[0]["dir"] == "" and leg[0]["required"]
    assert vs.plan(None) is leg[0] and vs.plan("bforce")["dir"] == "bforce"
    dirs = [r["dir"] for r in vs.VAL_PLAN if r["dir"] is not None]
    assert len(dirs) == len(set(dirs))
    assert {r["rigid"] for r in vs.VAL_PLAN} == {"linear"} and {r["resp"] for r in vs.VAL_PLAN} == {"solve"}
    assert all(r["support"] in vs.SUPPORTS and r["reaction_role"] in vs.REACTION_ROLES
               for r in vs.VAL_PLAN if r["load"] is not None)
    assert [r["key"] for r in vs.VAL_PLAN if r["noise_force"]] == ["full"]
    assert [r["key"] for r in vs.VAL_PLAN if r["fallback"]] == ["full"]
    # v0.24.4(esl_jig_case.md §5.5 — V-0243-VAL-4 의도 변경): 지그 3방식 행 = 행 load 파일 bc 지지·반력 정보·한계 = jig.json limits
    for k in ("jig", "jig_disp", "jig_spring"):
        r = vs.plan(k)
        assert r["load"] == ("esl", f"{k}.npz", "f") and r["doc"] == ("esl", f"{k}.json") and r["summary"] == k
        assert (r["support"], r["reaction_role"], r["load_frame"], r["balance"], r["dir"], r["na"], r["note"]) == (
            "jig", "info", "ref_basis", k, k, "JIG_NOT_RUN", "VAL_NOTE_RECON")
        assert r["limits"] == ("limits",) and r["reaction_tol_key"] is None and not r["required"]
        assert vs.LABEL[k].startswith("지그 ") and vs.GROUP[k] == "jig" and vs.SHORT[k] in vs.LABEL[k]
    assert vs.GROUP_LABEL == {"jig": "지그 ESL"} and vs.SUPPORTS == ("bc321", "jig")
    # CASE_PLAN(3D 표시 열)에 검증 열을 더하지 않음(D-0.24.3-VAL-2)
    assert not ({"reaction_role", "noise_force", "load_frame", "balance"} & set(view3d_src.COLUMNS))
    with pytest.raises(EslError) as ei:
        vs.plan("xyz")
    assert ei.value.code == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize("mut", ["drop_col", "extra_col", "two_legacy", "order", "rigid", "resp", "support", "role",
                                 "dup_dir", "bad_loc", "legacy_dir", "root_dir", "legacy_fallback"])
def test_v4_check_plan_rejects_invalid(mut):
    rows = [dict(r) for r in vs.VAL_PLAN]
    ix = {r["key"]: i for i, r in enumerate(rows)}
    b = rows[ix["bforce"]]
    if mut == "drop_col":
        b.pop("note")
    elif mut == "extra_col":
        b["label"] = "x"
    elif mut == "two_legacy":
        b["legacy"] = True
    elif mut == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif mut == "rigid":
        b["rigid"] = "kabsch"
    elif mut == "resp":
        b["resp"] = "esl"
    elif mut == "support":
        b["support"] = "bc"
    elif mut == "role":
        b["reaction_role"] = "warn"
    elif mut == "dup_dir":
        b["dir"] = "fint"
    elif mut == "bad_loc":
        b["load"] = ("disk", "bforce.npz", "f")
    elif mut == "legacy_dir":
        rows[ix["full"]]["dir"] = "full"
    elif mut == "legacy_fallback":
        rows[ix["full"]]["fallback"] = None
    else:
        b["dir"] = ""
    with pytest.raises(EslError) as ei:
        vs.check_plan(tuple(rows))
    assert ei.value.code == "CONFIG_INVALID"


def test_v4_import_graph_independent():
    code = ("import sys, numpy as np; import esl.val_src as vs, esl.val_metrics as vm; "
            "vs.row_status(vs.plan('bforce'), False, None, None); vm.verdict_of([], None); "
            "bad = [m for m in sys.modules if m.startswith(('esl.doe', 'esl.pipeline', 'esl_platform', 'esl_worker'))]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": ROOT}, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_v4_labels_equal_frontend_source_rows():
    """보고서 출처 이름(val_src.LABEL) = 화면 SOURCE_ROWS label(원본 sources.ts)."""
    with open(os.path.join(ROOT, "frontend", "src", "view3d", "sources.ts"), encoding="utf-8") as fh:
        ts = fh.read()
    blk = ts[ts.index("export const SOURCE_ROWS"):]
    blk = blk[:blk.index("];")]
    if '"jig_disp"' not in blk:
        # v0.24.4 P2b: 화면 행(C2 — frontend/src/view3d/sources.ts)은 다른 작업 트리에서 병행 — 병합 전 트리에서만 건너뜀
        # (병합 후에는 이 조건이 거짓이라 항상 비교한다)
        pytest.skip("frontend sources.ts 에 v0.24.4 지그 3방식 행이 아직 없음(C2 병합 전)")
    got = dict(re.findall(r'\{\s*key:\s*"(\w+)",\s*label:\s*"([^"]+)"', blk))
    assert got == vs.LABEL and tuple(got) == vs.KEYS


def test_v4_note_text_legacy_equals_stage5_text():
    """legacy 변위 설명(VAL_NOTE_CONSISTENCY) = v0.24.2 화면 문구(Stage5.tsx:261 — v0.24.2 기록값) 그대로."""
    v0242 = "ESL 재해석 변위와 Radioss 변위의 차이 — 계산·경계조건·저장 정밀도의 수치 일관성을 봅니다(물리적 차이가 아닙니다)."
    assert vs.NOTE_TEXT["VAL_NOTE_CONSISTENCY"] == v0242
    assert vs.note_text(vs.plan(None)) == vs.NOTE_TEXT["VAL_NOTE_CONSISTENCY"]
    assert vs.note_text(vs.plan("fint")) == vs.NOTE_TEXT["VAL_NOTE_RECON"] == vs.note_text(vs.plan("jig_spring"))


# ---------------------------------------------------------------- V-5 row_status(순수)
BF, FI, JIG = vs.plan("bforce"), vs.plan("fint"), vs.plan("jig")


@pytest.mark.parametrize("row,have,doc,summ,exp_code,exp_reason", [
    (BF, True, None, None, None, None),
    (BF, False, None, {"grade": None, "code": "BF_DISABLED"}, "BF_DISABLED", "설정에서 꺼짐(bforce.enabled)"),
    (FI, False, None, {"grade": None, "code": "FINT_DISABLED"}, "FINT_DISABLED", "설정에서 꺼짐(bforce.fint.enabled)"),
    (BF, False, None, {"grade": "none", "code": "BF_NO_DATA", "reason": "추출물에 경계력 결과 없음"}, "BF_NO_DATA",
     "추출물에 경계력 결과 없음"),
    (BF, False, None, {"grade": "none", "code": "BF_EXTRACT_FAILED", "reason": "보충 실패 — x"}, "BF_EXTRACT_FAILED",
     "보충 실패 — x"),
    (BF, False, None, {"grade": "none", "code": "BF_EXTRACT_SKIPPED", "reason": "보충 생략 — y"}, "BF_EXTRACT_SKIPPED",
     "보충 생략 — y"),
    # 진단 json code 가 요약보다 우선(계약 §4.4)
    (BF, False, {"code": "BF_FAILED", "reason": "ValueError: z"}, {"code": "BF_FAILED", "reason": "other"}, "BF_FAILED",
     "ValueError: z"),
    (FI, False, {"code": "FINT_NO_DATA", "reason": "내력 출력 없음"}, {"code": "FINT_NO_DATA", "reason": "q"},
     "FINT_NO_DATA", "내력 출력 없음"),
    # 옛 ESL(파일·요약 없음) → 행 na
    (BF, False, None, None, "V3D_SRC_NOT_RUN", view3d_src.REASON_TEXT["V3D_SRC_NOT_RUN"]),
    # v0.24.4 지그 행: 하중 있음 → done, 옛 ESL → JIG_NOT_RUN, 준비 없음·실패 = 요약·진단 code·reason
    (JIG, True, None, None, None, None),
    (JIG, False, None, None, "JIG_NOT_RUN", view3d_src.REASON_TEXT["JIG_NOT_RUN"]),
    (JIG, False, None, {"status": "unavailable", "code": "JIG_NOT_PREPARED", "reason": "준비 기록 없음"}, "JIG_NOT_PREPARED",
     "준비 기록 없음"),
    (JIG, False, {"status": "unavailable", "code": "JIG_FAILED", "reason": "공유 단계 x"},
     {"code": "JIG_FAILED", "reason": "y"}, "JIG_FAILED", "공유 단계 x"),
])
def test_v5_row_status_table(row, have, doc, summ, exp_code, exp_reason):
    st = vs.row_status(row, have, doc, summ)
    exp_status = "na" if row["load"] is None else ("done" if have else "unavailable")
    assert st == {"status": exp_status, "code": exp_code, "reason": exp_reason}


def test_v5_new_reason_codes_and_failed_detail():
    assert vs.reason_text("VAL_SRC_NOT_RUN").startswith("이 검증에는 출처별 결과가 없습니다")
    assert vs.reason_text("VAL_SRC_DISABLED") == "설정에서 꺼짐(validation.sources.enabled)"
    long = "E" * 1000
    f = vs.failed_status(long)
    assert f["status"] == "failed" and f["code"] == "VAL_SRC_FAILED"
    assert f["reason"] == f"출처 검증 계산 실패({'E' * 300}) — 다른 출처 결과는 그대로"
    assert vs.disabled_status() == {"status": "disabled", "code": "VAL_SRC_DISABLED",
                                    "reason": vs.REASON_TEXT["VAL_SRC_DISABLED"]}
    assert vs.reason_text("VALIDATION_FILES_GONE").startswith("이 검증의 산출물이 이후 검증으로 바뀌었습니다")
    assert vs.reason_text(None) is None and vs.reason_text("BF_NO_DATA", "d") == "d"


def test_v5_limits_and_cond_text():
    assert vs.limit_info(["BF_TIE_MISSING"]) == {"limits": ["BF_TIE_MISSING"],
                                                 "limit_text": [bfm.LIMIT_TEXT["BF_TIE_MISSING"]], "comparable": False}
    li = vs.limit_info(["FINT_ROT_LINKS"])
    assert li["comparable"] is True and li["limit_text"] == [bfm.LIMIT_TEXT["FINT_ROT_LINKS"]]
    assert vs.limit_info([])["comparable"] is True and vs.limit_info(None)["limits"] == []
    assert vs.limit_class("JIG_REGION_FALLBACK") == "caution" and vs.limit_class("NEW_CODE") == "caution"
    assert vs.limit_codes(BF, {"limits": ["BF_TIE_MISSING"]}) == ["BF_TIE_MISSING"] and vs.limit_codes(BF, None) == []
    assert vs.limit_codes(vs.plan("full"), {"limits": ["X"]}) == []                         # full: 열 None
    # 균형 = 고정 코드 또는 진단 json 적용값
    assert vs.balance_of(vs.plan("full"), None) == "self"
    assert vs.balance_of(BF, {"balance": "inertia_relief"}) == "inertia_relief"
    assert vs.balance_of(FI, {"fint": {"balance_applied": "none"}}) == "none" and vs.balance_of(FI, None) is None
    t = vs.cond_text(FI, {"fint": {"balance_applied": "none"}})
    assert t == ("하중 " + vs.LOAD_FRAME_TEXT["ref_rot"] + " · 지지 " + vs.SUPPORT_TEXT["bc321"] + " · 균형 "
                 + vs.BALANCE_TEXT["none"] + " · 목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이")
    sb = vs.src_block(BF, {"balance": "inertia_relief", "limits": ["BF_TIE_MISSING"]}, 12.5)
    assert list(sb) == ["key", "load", "sum_abs_f", "load_frame", "balance", "support", "rigid", "resp", "cond_text",
                        "note", "limits", "limit_text", "comparable"]
    assert sb["load"] == "04_esl/bforce.npz" and sb["comparable"] is False and sb["sum_abs_f"] == 12.5


# ---------------------------------------------------------------- V-2 val_metrics(순수)
def _plate(n=7):
    xs, ys = np.meshgrid(np.linspace(0, 100, n), np.linspace(0, 60, n), indexing="ij")
    X0 = np.stack([xs.ravel(), ys.ravel(), 0.3 * np.sin(xs.ravel() / 30.0)], axis=1)
    return X0


def test_v2_disp_metrics_rigid_invariance_and_reaction_definitions():
    rng = np.random.default_rng(5)
    X0 = _plate()
    N = X0.shape[0]
    u_rel = 0.1 * rng.normal(size=(N, 3))
    U = float(np.max(np.linalg.norm(u_rel, axis=1)))
    w, t = np.array([1e-6, -2e-6, 3e-6]), np.array([0.01, -0.02, 0.005])
    u6 = np.zeros((N, 6))
    u6[:, :3] = u_rel + t + np.cross(w, X0)                          # u_rel + 미소(선형) 강체
    F = rng.normal(size=(N, 3))
    R = np.zeros((N, 3))
    R[0] = [0.3, -0.1, 0.2]
    R[5] = [0.0, 0.4, 0.0]
    nid = np.arange(N) + 1
    m = vm.disp_metrics(X0, u_rel, u6, R, F, [0, 5], U, nid, top_n=5, hist_bins=8)
    assert m["disp_rms_rel"] < 1e-12 and m["disp_max_rel"] < 1e-12
    sF = np.linalg.norm(F, axis=1).sum()
    assert m["reaction_rel"] == pytest.approx(np.linalg.norm(R, axis=1).sum() / sF, rel=1e-14)       # Σ‖R‖/Σ‖F‖
    assert m["reaction_sum_rel"] == pytest.approx(np.linalg.norm(R.sum(axis=0)) / sF, rel=1e-14)    # ‖ΣR‖/Σ‖F‖
    assert m["sum_abs_f"] == pytest.approx(sF) and m["disp_an"]["summary"]["n_support"] == 2
    # 유한 회전이 섞이면 선형 제거는 O(ω²L) 잔차만 남김(응답·목표 같은 연산)
    Q = np.array([[np.cos(1e-3), -np.sin(1e-3), 0], [np.sin(1e-3), np.cos(1e-3), 0], [0, 0, 1]])
    c = X0.mean(axis=0)
    u6b = np.zeros((N, 6))
    u6b[:, :3] = (X0 + u_rel - c) @ Q.T + c - X0
    mb = vm.disp_metrics(X0, u_rel, u6b, R, F, [0], U, nid, top_n=5, hist_bins=8)
    d_ref, _, _ = kabsch.remove_linear_rigid(X0, u_rel)
    d_b, _, _ = kabsch.remove_linear_rigid(X0, u6b[:, :3])
    assert mb["disp_max_rel"] == pytest.approx(np.linalg.norm(d_b - d_ref, axis=1).max() / U, rel=1e-12)
    assert 0 < mb["disp_max_rel"] < 1e-3
    with pytest.raises(EslError):
        vm.disp_metrics(X0, u_rel, u6, R, F, [0], 0.0, nid, top_n=5, hist_bins=8)


CRIT = {"disp_rms_rel_max": 0.01, "disp_max_rel_max": 0.05, "reaction_rel_max": 1e-6, "disp_noise_rel_max": 1e-3,
        "hotspot_strain_rel_err_max": 0.1, "noise_strain_rel_max": 0.05}
CCFG = {"max_err_pct_max": 10.0, "p90_err_max": 20.0}
VALS = {"disp_rms_rel": 1e-3, "disp_max_rel": 2e-3, "reaction_rel": 0.5, "disp_noise_rel": 1e-6,
        "hotspot1_strain_rel_err": 0.01, "field_max_err_pct": 1.0, "field_p90_err_pct": 2.0,
        "noise_hotspot_strain_rel": 1e-4, "reaction_sum_rel": 1e-9, "u_rel_linear_rigid_rel": 0.1,
        "noise_force_rel": None}


def test_v2_metric_rows_reaction_role_and_verdict():
    j = vm.metric_rows(VALS, CRIT, CCFG, reaction_role="judge")
    assert [m["metric"] for m in j] == ["disp_rms_rel", "disp_max_rel", "reaction_rel", "disp_noise_rel",
                                        "hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct",
                                        "noise_hotspot_strain_rel", "reaction_sum_rel", "u_rel_linear_rigid_rel",
                                        "noise_force_rel"]
    assert vm.verdict_of(j, None) == ("FAIL", ["REACTION"])                       # 반력 판정(정정 지지)
    i = vm.metric_rows(VALS, CRIT, CCFG, reaction_role="info")
    r = next(m for m in i if m["metric"] == "reaction_rel")
    assert r == {"metric": "reaction_rel", "value": 0.5, "criterion": None, "pass": None, "role": "info"}
    assert vm.verdict_of(i, None) == ("PASS", [])                                 # info → 판정·fail_reasons 제외
    assert vm.verdict_of(j, "NO_FULL_SOLVE") == ("UNDETERMINED", [])
    s = vm.metric_rows(VALS, CRIT, CCFG, strain_skipped=True)
    assert all(m["value"] is None and m["status"] == "skipped" for m in s if m["role"] == "reference")
    none = vm.metric_rows({**VALS, "disp_rms_rel": None}, CRIT, CCFG)
    assert none[0]["status"] == "skipped" and vm.verdict_of(none, None) == ("FAIL", ["DISP_RMS", "REACTION"])


def test_v2_validation_doc_key_order_and_src_last():
    kw = {k: None for k in ("frame", "verdict", "undetermined_reason", "esl_ref", "fail_reasons", "criteria", "noise",
                            "noise_source", "metrics", "full_solve", "hotspots", "hotspots_excluded", "reactions",
                            "reaction_sum", "disp", "strain_ref", "field", "strain_source", "created_at")}
    d = vm.validation_doc(**kw)
    assert list(d) == ["schema", "frame", "verdict", "verdict_scheme", "undetermined_reason", "esl_ref", "fail_reasons",
                       "criteria", "noise", "noise_source", "metrics", "full_solve", "hotspots", "hotspots_excluded",
                       "reactions", "reaction_sum", "disp", "strain_ref", "field", "strain_source", "created_at"]
    assert d["schema"] == "esl/validation/3" and d["verdict_scheme"] == "disp_primary/1"
    d2 = vm.validation_doc(**kw, src={"key": "bforce"})
    assert list(d2)[-1] == "src" and list(d2)[:-1] == list(d)


def test_v2_hotspot_rows_compared_and_excluded():
    eps_rad = np.array([1.0, 2.0, 0.0, 4.0])
    eps_val = np.array([1.1, 2.0, 0.5, 3.0])
    hs = [{"rank": 1, "elem_pos": 0, "elem_id": 10, "value": 1.0, "centroid": [0, 0, 0], "compared": True,
           "comparable": True, "reason": None},
          {"rank": 2, "elem_pos": 2, "elem_id": 12, "value": 0.0, "centroid": [1, 0, 0], "compared": True,
           "comparable": True, "reason": None},
          {"rank": 3, "elem_pos": 3, "elem_id": 13, "value": 4.0, "centroid": [2, 0, 0], "compared": False,
           "comparable": False, "reason": "hold"},
          {"rank": 4, "elem_pos": 1, "elem_id": 11, "value": 2.0, "centroid": [3, 0, 0], "compared": False,
           "comparable": True, "reason": None}]
    hots, ex = vm.hotspot_rows(hs, eps_rad, eps_val)
    assert [h["elem_id"] for h in hots] == [10, 12] and hots[0]["rel_err"] == pytest.approx(0.1)
    assert hots[1]["rel_err"] == float("inf")
    assert ex == [{"rank": 3, "elem_id": 13, "metric_value": 4.0, "centroid": [2, 0, 0], "reason": "hold",
                   "eps_rad": 4.0, "eps_val": 3.0}]


def test_core_adapter_val_wrappers():
    sys.path.insert(0, os.path.join(ROOT, "worker"))
    from esl_worker import core_adapter as ca

    p = ca.val_src_plan()
    assert p["keys"] == vs.KEYS and p["legacy"] == "full" and p["sources_json"] == "sources.json"
    assert [r["key"] for r in p["rows"]] == list(vs.KEYS) and p["rows"][2] == vs.VAL_PLAN[2]
    assert p["rows"][2] is not vs.VAL_PLAN[2]                                     # 사본
    assert p["reason_text"]["VAL_SRC_NOT_RUN"] == vs.REASON_TEXT["VAL_SRC_NOT_RUN"] and p["label"] == vs.LABEL
    assert ca.val_row_status(row=vs.plan("bforce"), have_load=False, doc=None, summary=None)["code"] == "V3D_SRC_NOT_RUN"
    assert ca.val_reason_text("VAL_SRC_DISABLED") == vs.REASON_TEXT["VAL_SRC_DISABLED"]


# ---- 출처별 반력 허용치·주의(D-0.24.3-VAL: fint 주의 5 %·불합격 10 %, 사용자 결정 2026-11-20) ----
@pytest.mark.parametrize("reac,verdict,warned", [(3e-2, "PASS", False), (7e-2, "PASS", True), (1.2e-1, "FAIL", False)])
def test_fint_reaction_two_stage(reac, verdict, warned):
    ms_vals = {k: 1e-6 for k in ("disp_rms_rel", "disp_max_rel")}
    row = vs.plan("fint")
    from esl import config as ec
    tol, warn = ec.source_reaction_tol(None, row["reaction_tol_key"], "fint"), ec.source_reaction_tol(None, row["reaction_warn_key"], "fint")
    assert (tol, warn) == (0.10, 0.05)
    crit = {**CRIT, "reaction_rel_max": tol}
    ms = vm.metric_rows({**VALS, **ms_vals, "reaction_rel": reac, "disp_noise_rel": 1e-6}, crit, CCFG, reaction_role="judge")
    v, why = vm.verdict_of(ms, None)
    assert v == verdict and (why == ["REACTION"]) == (verdict == "FAIL")
    r = vs.done_row(row, {"verdict": v, "fail_reasons": why, "metrics": ms, "criteria": {**crit, "reaction_warn_rel": warn}}, None)
    assert r["reaction_tol"] == 0.10 and r["reaction_warn"] == 0.05 and r["reaction_warned"] is warned
    assert (vs.WARN_CODE in r["limits"]) == warned and r["comparable"] is True
    assert (any("5 % 초과" in t for t in r["limit_text"])) == warned


@pytest.mark.parametrize("key", ["full", "bforce"])
def test_full_bforce_reaction_criterion_unchanged(key):
    from esl import config as ec
    row = vs.plan(key)
    assert ec.source_reaction_tol(None, row["reaction_tol_key"], key) is None   # 공통 기준 1e-6
    assert ec.source_reaction_tol(None, row["reaction_warn_key"], key) is None


def test_reaction_tol_config_override_and_hash_neutral():
    from esl import config as ec
    cfg = {"validation": {"sources": {"reaction_tol": {"fint": 0.2, "bforce": 0.3}, "reaction_warn": {"fint": 0.1}}}}
    assert ec.source_reaction_tol(cfg, vs.TOL_KEY, "fint") == 0.2
    assert ec.source_reaction_tol(cfg, vs.TOL_KEY, "bforce") == 0.3
    assert ec.source_reaction_tol(cfg, vs.plan("full")["reaction_tol_key"], "full") is None
    assert ec.validation_sources_settings(None)["reaction_tol"] == {"fint": 0.10}
    assert ec.validation_sources_settings({})["reaction_warn"] == {"fint": 0.05}
    for k in ("validation.sources.reaction_tol", "validation.sources.reaction_warn"):
        assert k in ec.OPTIONAL_KEYS


# ---------------------------------------------------------------- v0.24.4 지그 행 문구·한계(V-0244-JIG-9 순수 부분)
def test_v0244_jig_support_text_limits_and_classes():
    J, JD = vs.plan("jig"), vs.plan("jig_disp")
    doc = {"bc": {"tie_text": "tie 면외(법선)", "n_jig": 12, "n_aux": 3}, "limits": ["JIG_DISP_FROM_TARGET", "JIG_AUX_REACTION"],
           "limit_text": ["tie 강제 — 유리", "면내 반력 큼"]}
    assert vs.support_text("jig", doc) == "지그 경계(tie 면외(법선) 12 + 3-2-1 면내 3)"
    assert vs.support_text("jig", None) == "지그 경계(– – + 3-2-1 면내 –)"                    # 진단 없음 = "–"
    assert vs.support_text("bc321", doc) == vs.SUPPORT_TEXT["bc321"]                          # 자리 없는 문구 그대로
    t = vs.cond_text(JD, doc)
    assert t == ("하중 " + vs.LOAD_FRAME_TEXT["ref_basis"] + " · 지지 지그 경계(tie 면외(법선) 12 + 3-2-1 면내 3) · 균형 "
                 + vs.BALANCE_TEXT["jig_disp"] + " · 목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이")
    # 한계: 코드 = 진단 json limits, 문구 = 같은 자리 limit_text(LIMIT_TEXT 에 없는 코드), 등급 caution → 비교 가능
    assert vs.limit_doc_text(J, doc) == {"JIG_DISP_FROM_TARGET": "tie 강제 — 유리", "JIG_AUX_REACTION": "면내 반력 큼"}
    sb = vs.src_block(JD, doc, 3.0)
    assert sb["limits"] == doc["limits"] and sb["limit_text"] == doc["limit_text"] and sb["comparable"] is True
    assert vs.limit_class("JIG_DISP_FROM_TARGET") == vs.limit_class("JIG_AUX_REACTION") == "caution"
    assert vs.limit_doc_text(J, {"limits": ["X"], "limit_text": []}) == {}                    # 길이 다름 = 무시
    assert vs.limit_doc_text(vs.plan("full"), doc) == {}
    # 기존 출처: LIMIT_TEXT 문구 우선(진단 json limit_text 가 있어도 바이트 불변)
    bf = {"limits": ["BF_TIE_MISSING"], "limit_text": ["다른 문구"]}
    assert vs.src_block(vs.plan("bforce"), bf, 1.0)["limit_text"] == [bfm.LIMIT_TEXT["BF_TIE_MISSING"]]
    assert vs.reason_text("JIG_NOT_RUN") == view3d_src.REASON_TEXT["JIG_NOT_RUN"] and "JIG_NOT_RUN" not in vs.REASON_TEXT
