"""V-BD-8·9: 순위(C_ref = 베이스라인 최악, score·개선율, 동률 id 순, 스킵·실패 제외, OK 0, 잡음 이내)와
민감도(합성 선형 응답 SRC 정확·R²=1, 단조 비선형 ρ=1, 풀 팩토리얼 주효과, 표본 부족 null)."""
import numpy as np
import pytest

from esl.doe import matrix as mx
from esl.doe import rank as rk
from esl.doe import settings
from esl.errors import EslError


def res(did, status="OK", Cs=(1.0, 2.0), values=None):
    per = [{"entry_id": f"E{i + 1}", "C": c, "umax": 10 * c, "epsmax": 0.01 * c} for i, c in enumerate(Cs)]
    return {"id": did, "status": status, "values": values or {}, "per_esl": per if status == "OK" else [],
            "warnings": []}


def test_rank_basic():
    R = rk.rank([res("d000", Cs=(3.0, 4.0)), res("d002", Cs=(2.0, 3.0)), res("d001", Cs=(3.0, 1.0)),
                 res("d003", Cs=(5.0, 1.0)), res("d004", "SKIPPED_COLLISION"), res("d005", "SKIPPED_FIXED"),
                 res("d006", "FAILED_MORPH"), res("d007", "FAILED_SOLVE"), res("d008", "FAILED_MESH")])
    assert R["C_ref"] == 4.0
    ids = [x["id"] for x in R["ranking"]]
    assert ids == ["d001", "d002", "d003"]                     # 0.75(d001,d002 동률 → id 순), 1.25
    a = R["ranking"][0]
    assert a["rank"] == 1 and a["score"] == 0.75 and abs(a["improvement"] - 0.25) < 1e-15
    assert a["worst_entry_id"] == "E1" and a["umax"] == 30.0 and a["umax_all"] == 30.0
    assert R["ranking"][2]["improvement"] == pytest.approx(-0.25)
    assert R["n_skipped"] == {"collision": 1, "fixed": 1, "geom": 0}
    assert R["n_failed"] == {"morph": 1, "mesh": 1, "solve": 1}
    assert R["baseline"]["score"] == 1.0 and R["baseline"]["worst_entry_id"] == "E2"
    assert R["n_ok"] == 3 and not R["warnings"]


def test_rank_no_feasible_and_baseline_failed():
    R = rk.rank([res("d000"), res("d001", "SKIPPED_GEOM")])
    assert R["ranking"] == [] and R["warnings"] == [{"code": "NO_FEASIBLE_DESIGNS"}]
    with pytest.raises(EslError) as ei:
        rk.rank([res("d000", "FAILED_SOLVE"), res("d001")])
    assert ei.value.code == "BASELINE_FAILED"
    with pytest.raises(EslError):
        rk.rank([res("d001")])


def test_noise_flag():
    R = rk.rank([res("d000", Cs=(10.0,)), res("d001", Cs=(9.95,)), res("d002", Cs=(9.0,))], noise_floor=0.01)
    nz = {x["id"]: x["noise"] for x in R["ranking"]}
    assert nz == {"d001": True, "d002": False}
    assert rk.rank([res("d000"), res("d001")])["ranking"][0]["noise"] is None


def _samples(fn, method="lhs", n=24, levels=None):
    params = [{"name": "A", "lo": 2.0, "hi": 6.0}, {"name": "B", "lo": 10.0, "hi": 16.0},
              {"name": "C", "lo": -5.0, "hi": 5.0}]
    tab = [{"name": p["name"], "type": "U", "nominal": (p["lo"] + p["hi"]) / 2} for p in params]
    sp = {"method": method, "seed": 3, "params": params}
    if method == "fullfact":
        sp["levels"] = levels
    else:
        sp["n"] = n
    m = mx.generate(sp, tab, settings())
    out = [{"values": d["values"], "score": fn(d["values"])} for d in m["designs"]]
    return out, m["spec"]["params"]


def test_sensitivity_linear_exact():
    def f(v):
        return 1.0 + 0.3 * (v["A"] - 2.0) / 4.0 - 0.1 * (v["B"] - 10.0) / 6.0 + 0.0 * v["C"]
    s, params = _samples(f)
    out = rk.sensitivity(s, params, method="lhs")
    assert not out["null"] and abs(out["r2"] - 1.0) < 1e-9
    p = {r["name"]: r for r in out["params"]}
    assert abs(p["A"]["beta"] - 0.3) < 1e-9 and abs(p["B"]["beta"] + 0.1) < 1e-9 and abs(p["C"]["beta"]) < 1e-9
    Z = np.array([[(x["values"]["A"] - 2) / 4, (x["values"]["B"] - 10) / 6] for x in s])
    y = np.array([x["score"] for x in s])
    assert abs(p["A"]["src"] - 0.3 * Z[:, 0].std() / y.std()) < 1e-9
    assert abs(p["B"]["src"] + 0.1 * Z[:, 1].std() / y.std()) < 1e-9


def test_sensitivity_monotone_spearman_and_mains():
    s, params = _samples(lambda v: float(np.exp(v["A"])))
    out = rk.sensitivity(s, params, method="lhs")
    p = {r["name"]: r for r in out["params"]}
    assert abs(p["A"]["spearman"] - 1.0) < 1e-12
    s2, params2 = _samples(lambda v: v["A"] ** 2 + v["B"], method="fullfact", levels=3)
    out2 = rk.sensitivity(s2, params2, method="fullfact", levels=3)
    me = {r["name"]: r["main_effects"] for r in out2["params"]}
    assert [m["level"] for m in me["A"]] == [2.0, 4.0, 6.0]
    # A 수준 평균 = A² + mean(B)
    assert all(abs(m["mean"] - (m["level"] ** 2 + 13.0)) < 1e-9 for m in me["A"] if m["n"] == 9)


def test_sensitivity_too_few():
    s, params = _samples(lambda v: v["A"], n=3)
    out = rk.sensitivity(s[:4], params, method="lhs")
    assert out["null"] and out["reason"] == "SENSITIVITY_TOO_FEW"
    assert rk.spearman([1, 1, 1], [1, 2, 3]) is None
    assert list(rk._rankdata(np.array([3.0, 1.0, 3.0, 2.0]))) == [3.5, 1.0, 3.5, 2.0]
