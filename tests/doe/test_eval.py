"""V-BD-7: 안 해석 — 분해 1회/안, C·umax·εmax 가 개별 solve 와 1e-9 일치, 반력 잔차 경고, 지지 퇴화,
병렬 상한 자동 축소(BD-D-15), done.json 이어하기 규칙(BD-D-16, 코어 부분)."""
import numpy as np
import pytest

import synth_doe as sd
from esl.doe import evaluate as ev
from esl.errors import EslError
from esl.mech.shell import ShellModel
from esl.mech.strain import eps_eq_max_layer

SOLVER = {"drill_factor": 1e-4, "backend": "superlu"}


def setup():
    mesh = sd.plate(nx=10, ny=6)
    sup = sd.so.supports_321(mesh)
    loads = [(f"E{k}", sd.so.load(mesh, kind, 1.0 + k, seed=k)) for k, kind in enumerate(("bend", "twist", "dent"))]
    return mesh, sup, loads


def test_one_factorization_and_matches_single_solve():
    mesh, sup, loads = setup()
    r = ev.evaluate(mesh, sup, loads, SOLVER, reaction_warn=0.01, keep_u=["E1"])
    assert r["stats"]["n_factorizations"] == 1 and r["stats"]["n_solves"] == 3
    spc = ev.spc_of(mesh, sup)
    for row, (eid, F) in zip(r["per_esl"], loads):
        sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                        backend="superlu")
        u, _ = sm.solve(F, spc)
        C = float(np.sum(F * u[:, :3]))
        assert row["entry_id"] == eid
        assert abs(row["C"] - C) <= 1e-9 * abs(C)
        um = float(np.max(np.linalg.norm(u[:, :3], axis=1)))
        assert abs(row["umax"] - um) <= 1e-9 * um
        em = float(np.max(eps_eq_max_layer(sm.strains(u))))
        assert abs(row["epsmax"] - em) <= 1e-9 * em
        assert row["reaction_rel"] < 1e-6
    assert set(r["u"]) == {"E1"} and r["u"]["E1"].shape == (mesh["node_id"].size, 3)
    assert not r["warnings"]
    w = ev.worst(r["per_esl"])
    assert w["C"] == max(x["C"] for x in r["per_esl"])


def test_reaction_residual_warning():
    mesh, sup, _ = setup()
    F = np.zeros_like(mesh["x0"])
    F[:, 1] = 1.0                                   # 비평형(면외 합력) → 3-2-1 반력 = 하중 합
    r = ev.evaluate(mesh, sup, [("E9", F)], SOLVER, reaction_warn=0.01)
    assert r["warnings"] and r["warnings"][0]["code"] == "REACTION_RESIDUAL" and r["warnings"][0]["ratio"] > 0.5


def test_support_degenerate_and_missing_node():
    mesh, _, loads = setup()
    nid = mesh["node_id"]
    bad = [(int(nid[0]), "123"), (int(nid[1]), "23"), (int(nid[2]), "3")]      # 한 줄 위 세 점
    with pytest.raises(EslError) as ei:
        ev.evaluate(mesh, bad, loads, SOLVER, reaction_warn=0.01)
    assert ei.value.code == "SUPPORT_DEGENERATE"
    with pytest.raises(EslError) as ei:
        ev.spc_of(mesh, [(999999, "123")])
    assert ei.value.code == "NODE_NOT_IN_PART"


def test_parallel_limit():
    r = ev.parallel_limit(220000, 2, 0.7, "superlu", available=1 << 50)
    assert r["parallel"] == 2 and not r["reduced"]
    est = r["estimate_bytes"]
    r = ev.parallel_limit(220000, 4, 0.7, "superlu", available=int(est * 2.0))
    assert r["parallel"] == 1 and r["reduced"]
    assert ev.parallel_limit(1000, 3, 0.7, "superlu", available=0)["parallel"] == 3   # 모름(0) → 축소 없음


def test_done_reuse_rules(tmp_path):
    d = str(tmp_path)
    s1 = ev.input_sha256({"a": 1.0}, "m", "l", "c", "0.14.0")
    assert s1 == ev.input_sha256({"a": 1}, "m", "l", "c", "0.14.0")
    assert s1 != ev.input_sha256({"a": 1.0}, "m", "l", "c", "0.14.1")
    assert ev.reusable(d, s1) is None
    ev.write_done(d, s1, "SKIPPED_COLLISION")
    assert ev.reusable(d, s1)["status"] == "SKIPPED_COLLISION"          # 결정적 스킵 → 재시도 안 함
    assert ev.reusable(d, "other") is None
    ev.write_done(d, s1, "FAILED_SOLVE")
    assert ev.reusable(d, s1) is None                                   # FAILED_* 만 다시
    ev.write_done(d, s1, "OK")
    assert ev.reusable(d, s1) is None                                   # result.json 없음
    (tmp_path / "result.json").write_text("{}")
    assert ev.reusable(d, s1)["status"] == "OK"


def test_design_npz_roundtrip(tmp_path):
    mesh, _, _ = setup()
    ev.save_design(str(tmp_path), mesh["node_id"], mesh["x0"] + 1.0, mesh)
    z = ev.load_design(str(tmp_path))
    assert np.array_equal(z["node_id"], mesh["node_id"]) and np.allclose(z["x"], mesh["x0"] + 1.0)
    assert z["x"].dtype == np.float64 and z["conn"].shape == mesh["conn"].shape and "pid" in z
    doc = ev.result_doc("d003", "OK", {"X": 1.0}, per_esl=[{"entry_id": "E1", "C": 2.0, "umax": 1, "epsmax": 0.1},
                                                           {"entry_id": "E2", "C": 3.0, "umax": 1, "epsmax": 0.1}])
    assert doc["worst_entry_id"] == "E2" and doc["C_max"] == 3.0 and doc["score"] is None
