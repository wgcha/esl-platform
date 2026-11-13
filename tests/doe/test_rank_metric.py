"""V-SM-5(순위 부분): rank(metric=solve) = 옛 rank, metric lin(ritz 기본·taylor)·ESL별 비·pareto·보조 열·SM_SKIPPED."""
import json

import pytest

from esl.doe import rank as rk
from esl.doe import stiffness_metric as smm
from esl.errors import EslError

LEGACY_ROW_KEYS = {"id", "values", "score", "improvement", "worst_entry_id", "umax", "epsmax", "umax_all", "epsmax_all",
                   "noise", "warnings_n", "worst_ratio", "min_improvement", "all_improved", "n_improved", "n_worsened",
                   "n_unchanged", "geo_mean_improvement", "per_esl", "C", "pareto", "rank"}
LEGACY_TOP_KEYS = {"C_ref", "baseline", "n_ok", "n_skipped", "n_failed", "n_other", "ranking", "noise_floor",
                   "ratio_tol", "esl_order", "warnings"}


def legacy(did, Cs, status="OK"):
    per = [{"entry_id": f"E{i + 1}", "C": c, "umax": 10 * c, "epsmax": 0.01 * c, "reaction_rel": 0.0}
           for i, c in enumerate(Cs)]
    return {"id": did, "status": status, "values": {"h": len(did)}, "per_esl": per if status == "OK" else [],
            "warnings": []}


def new(did, rows, status="OK"):
    """rows = [(C_solve, rho)] — C_ref_i = 10, C_lin = C_ref(2−ρ), C_ritz = C_ref/ρ."""
    per = []
    for i, (c, rho) in enumerate(rows):
        p = {"entry_id": f"E{i + 1}", "C": c, "umax": 100 * c, "epsmax": 0.01 * c, "reaction_rel": 0.0,
             "umax_def": 7 * c, "imbalance_rel": 0.01 * (i + 1), "rho": rho}
        if rho is None:
            p.update(C_lin=None, C_ritz=None)
        else:
            p.update(C_lin=smm.lin_value(10.0 * (i + 1), rho, "taylor"), C_ritz=smm.lin_value(10.0 * (i + 1), rho, "ritz"))
        per.append(p)
    return {"id": did, "status": status, "values": {}, "per_esl": per if status == "OK" else [], "warnings": []}


def _dump(R):
    return json.dumps(R, sort_keys=False)


def test_legacy_solve_identical_and_keys():
    rs = [legacy("d000", (3.0, 4.0)), legacy("d001", (3.0, 1.0)), legacy("d002", (2.0, 3.0)),
          legacy("d003", (5.0, 1.0)), legacy("d004", (), "FAILED_SOLVE")]
    a = rk.rank(json.loads(json.dumps(rs)))
    b = rk.rank(json.loads(json.dumps(rs)), metric="solve", lin_form="taylor")
    assert _dump(a) == _dump(b)
    assert set(a) == LEGACY_TOP_KEYS and all(set(x) == LEGACY_ROW_KEYS for x in a["ranking"])
    assert set(a["n_failed"]) == {"morph", "mesh", "solve"}
    with pytest.raises(EslError) as e:
        rk.rank(rs, metric="lin")
    assert e.value.code == "INPUT_INVALID"
    with pytest.raises(EslError) as e:
        rk.rank(rs, metric="xx")
    assert e.value.code == "CONFIG_INVALID"


def _set():
    # d000: ρ = 1 → C_lin = C_ritz = C_ref = (10, 20). solve C 는 오염된 값(불평형 증폭 흉내).
    return [new("d000", [(10.0, 1.0), (20.0, 1.0)]),
            new("d001", [(30.0, 1.25), (19.0, 0.98)]),   # solve: 30/20 → 나쁨,  lin: E1 ρ>1 → 강함
            new("d002", [(9.0, 0.9), (25.0, 1.1)]),
            new("d003", [(8.0, 1.6), (18.0, 0.8)]),      # E2 ρ 0.8: taylor 24 vs ritz 25 / E1 taylor 4 ritz 6.25
            new("d004", [(5.0, None), (5.0, 1.0)]),      # SM_SKIPPED
            new("d005", [], "FAILED_SOLVE")]


def test_lin_ritz_default_ranking():
    R = rk.rank(_set(), metric="lin")
    assert R["metric"] == "lin" and R["lin_form"] == "ritz" == smm.LIN_FORM_DEFAULT
    assert R["C_ref"] == 20.0 and R["C_ref_solve"] == 20.0
    by = {x["id"]: x for x in R["ranking"]}
    # ritz: d001 max(8, 20/0.98=20.408) → 1.0204, d002 max(11.1, 18.18) → 0.909, d003 max(6.25, 25) → 1.25
    assert [x["id"] for x in R["ranking"]] == ["d002", "d001", "d003"]
    assert by["d001"]["score"] == pytest.approx(20.0 / 0.98 / 20.0) and by["d001"]["worst_entry_id"] == "E2"
    assert by["d003"]["score"] == pytest.approx(1.25)
    # ESL별 비 = 같은 metric 값의 베이스라인 대비
    assert by["d002"]["per_esl"][0]["ratio"] == pytest.approx((10 / 0.9) / 10.0)
    assert by["d002"]["per_esl"][0]["C_solve"] == 9.0 and by["d002"]["C_solve"] == {"E1": 9.0, "E2": 25.0}
    assert by["d002"]["C"]["E2"] == pytest.approx(20 / 1.1)
    # 보조 열: score_solve = 옛 정의, ρ 범위·불평형·umax_def(metric 최악 ESL)
    assert by["d001"]["score_solve"] == pytest.approx(30.0 / 20.0)
    assert by["d003"]["rho_min"] == 0.8 and by["d003"]["rho_max"] == 1.6 and by["d003"]["imbalance_max"] == 0.02
    assert by["d001"]["umax_def"] == 7 * 19.0 and by["d001"]["umax"] == 100 * 19.0
    assert R["n_failed"]["sm"] == 1 and R["n_ok"] == 3           # d004 지표 없음 → 순위 밖
    assert R["baseline"]["score_solve"] == 1.0 and R["baseline"]["rho_min"] == 1.0


def test_lin_taylor_vs_solve_and_pareto():
    T = rk.rank(_set(), metric="lin", lin_form="taylor")
    by = {x["id"]: x for x in T["ranking"]}
    # taylor: d003 max(10(2−1.6)=4, 20(2−0.8)=24) → 1.2, d001 max(7.5, 20.4) → 1.02, d002 max(11, 18) → 0.9
    assert [x["id"] for x in T["ranking"]] == ["d002", "d001", "d003"]
    assert by["d003"]["score"] == pytest.approx(1.2) and by["d002"]["score"] == pytest.approx(0.9)
    S = rk.rank(_set(), metric="solve")                          # 새 스냅샷의 solve = 보조 열과 같은 값
    assert S["metric"] == "solve" and S["n_failed"].get("sm") is None and S["n_ok"] == 4
    for x in S["ranking"]:
        assert x["score"] == x["score_solve"]
    old_like = rk.rank([{**r, "per_esl": [{k: p[k] for k in ("entry_id", "C", "umax", "epsmax")} for p in r["per_esl"]]}
                        for r in _set()])
    assert [(x["id"], x["score"]) for x in S["ranking"]] == [(x["id"], x["score"]) for x in old_like["ranking"]]
    # pareto(같은 metric 비): ritz d002 = (1.111, 0.909) — 다른 안에 지배당하지 않음
    L = rk.rank(_set(), metric="lin")
    assert {x["id"]: x["pareto"] for x in L["ranking"]} == {"d001": True, "d002": True, "d003": True}
    assert {x["id"]: x["n_improved"] for x in L["ranking"]} == {"d001": 1, "d002": 1, "d003": 1}


def test_lin_baseline_missing_fails():
    rs = _set()
    rs[0] = new("d000", [(10.0, None), (20.0, 1.0)])
    with pytest.raises(EslError) as e:
        rk.rank(rs, metric="lin")
    assert e.value.code == "BASELINE_FAILED"
    assert rk.rank(rs, metric="solve")["n_ok"] == 4             # solve 는 지표 없어도 그대로
