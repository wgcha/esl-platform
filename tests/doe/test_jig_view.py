"""v0.23.3 지그 진단 뷰 · 하중 정의 보기 · 3D 다시 만들기(계약 esl_jig_view.md V-0233-1~4)."""
import glob
import hashlib
import json
import os

import numpy as np
import pytest
import test_jig_stages as T

from esl.doe import jig as jg
from esl.doe import rank as rk
from esl.doe import stages as stg
from esl.library import _util as U
from esl.view3d import unpack_values


@pytest.fixture(scope="module")
def jrun(tmp_path_factory):
    t = tmp_path_factory.mktemp("jigview")
    mesh, doe = T.build_same(t)
    out, post, ids = T.run(str(t / "o"), doe, mesh, rank=T.rank_snap())
    return out, post, ids, {**doe, "rank": T.rank_snap(), "rev": 1}


def _side(out):
    return U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))


def _basis(out):
    z = U.load_npz(os.path.join(out, "prep", "jig.npz"))
    return z, stg._jig_basis_of(z, int(z["a"].shape[1]))


def _mesh(out):
    return dict(stg.sc.load_base(os.path.join(out, "prep"))[0].mesh)


# ---------------------------------------------------------------- V-0233-1 순수 함수
def test_kind_forces_and_response_superpose(jrun):
    out = jrun[0]
    z, basis = _basis(out)
    mesh = _mesh(out)
    N = z["node_id"].size
    jidx = np.asarray(z["jig_idx"], dtype=np.int64)
    fit = np.asarray(z["omega"], bool).copy()
    fit[jidx] = False
    h = jg.factor(mesh, jidx, {"backend": "superlu"})
    U_ = jg.basis_response(h, basis, fit)["U"]
    for a in np.asarray(z["a"], dtype=np.float64):
        parts = jg.kind_forces(basis, a, N)
        assert set(parts) == {"region", "body", "mode"}
        F = jg.forces(basis, a, N)
        np.testing.assert_allclose(sum(parts.values()), F, rtol=0, atol=1e-12 * max(1.0, np.abs(F).max()))
        kr = jg.kind_response(h, parts)
        want = np.einsum("k,kmi->mi", a, U_)
        np.testing.assert_allclose(kr["u"][fit], want, rtol=0, atol=1e-9 * np.abs(want).max())
        np.testing.assert_allclose(sum(kr["parts"].values()), kr["u"], rtol=0, atol=1e-14 * np.abs(want).max())


def test_diag_report_out_of_plane_fraction():
    n = 50
    rng = np.random.default_rng(1)
    nrm = np.tile([0.0, 1.0, 0.0], (n, 1))
    w = {"area": rng.uniform(1, 2, n), "normal": nrm}
    fm = np.ones(n, bool)
    s = rng.normal(size=n)
    u_out = nrm * s[:, None]
    u_in = np.stack([s, np.zeros(n), -s], axis=1)
    r1 = jg.diag_report(u_out, u_out, {"region": u_out, "body": 0 * u_out, "mode": 0 * u_out}, w, fm)
    assert r1["tgt_out_frac"] == pytest.approx(1.0) and r1["err_max"] == 0.0
    assert r1["contrib"] == {"region": pytest.approx(1.0), "body": 0.0, "mode": 0.0}
    r2 = jg.diag_report(u_in, 2 * u_in, {"region": u_in, "body": u_in, "mode": 0 * u_in}, w, fm)
    assert r2["tgt_out_frac"] == pytest.approx(0.0, abs=1e-15)
    assert r2["contrib"]["region"] == pytest.approx(0.5) and r2["umax_fit"] == pytest.approx(2 * r2["umax_tgt"])


# ---------------------------------------------------------------- V-0233-2 진단 산출
def test_diag_outputs_match_superposition(jrun):
    out, post, ids, _doe = jrun
    side = _side(out)
    assert side["schema"] == stg.JIG_VIEW_SCHEMA and side["source"] == "bd_post" and side["warnings"] == []
    assert "view3d_jig" not in side                                           # BD_POST 는 result.json 에(불변)
    dg = side["jig_diag"]
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    z, basis = _basis(out)
    mesh = _mesh(out)
    N = z["node_id"].size
    jidx = np.asarray(z["jig_idx"], dtype=np.int64)
    h = jg.factor(mesh, jidx, {"backend": "superlu"})
    zeids = [str(e) for e in z["entry_ids"].tolist()]
    assert [e["entry_id"] for e in dg["entries"]] == zeids and dg["n_jig"] == jd["fix"]["n_jig"]
    assert dg["n_contact"] == jd["n_contact"] and dg["n_patch"] == jd["n_patch"] and len(dg["regions"]) == len(jd["regions"])
    rv = jg.region_vertices(basis)
    for e in dg["entries"]:
        assert e["dirs"] == {k: f"d000_jigdiag_e{e['kk']:02d}_{k}" for k in ("tgt", "fit", "err")}
        a = np.asarray(z["a"][zeids.index(e["entry_id"])], dtype=np.float64)
        u_fit = jg.kind_response(h, jg.kind_forces(basis, a, N))["u"]
        je = next(x for x in jd["entries"] if x["entry_id"] == e["entry_id"])
        assert e["mac"] == je["mac"] and e["tie_rel"] == je["tie_rel"] and e["rot_deg"] == je["rot_deg"]
        assert set(e["contrib"]) == {"region", "body", "mode"} and 0.0 <= e["tgt_out_frac"] <= 1.0
        d = os.path.join(out, "post", "view3d", e["dirs"]["fit"])
        man = U.read_json(os.path.join(d, "manifest.json"))
        assert man["esl_run_id"] == e["entry_id"] and {s["dof"] for s in man["supports"]} == {"123"}
        assert man["ranges"]["u_max"] == pytest.approx(float(np.linalg.norm(u_fit, axis=1).max()), rel=1e-9)
        with open(os.path.join(d, "values.bin"), "rb") as fh:
            vals = unpack_values(fh.read(), man["values"]["arrays"], man["n_nodes"])
        uq = np.asarray(vals["u"], dtype=np.float64).reshape(-1, 3)
        sc = np.asarray(next(x for x in man["values"]["arrays"] if x["key"] == "u")["scale"], dtype=np.float64)
        assert np.abs(uq - u_fit).max() <= float(np.max(sc)) * 1.01                # 저장값 = Σ a_k U_k(양자화 안)
        F_reg = jg.kind_forces(basis, a, N)["region"].sum(axis=0)              # 화살표 합 = 영역 합력 합
        np.testing.assert_allclose(e["F_region_sum"], F_reg, rtol=1e-9, atol=1e-9 * max(1.0, np.abs(F_reg).max()))
        np.testing.assert_allclose(np.sum([f["F"] for f in e["forces"]], axis=0), e["F_region_sum"], rtol=1e-12, atol=1e-12)
        rg = U.read_json(os.path.join(d, stg.JIG_REGIONS_JSON))
        assert [r["vertices"] for r in rg["regions"]] == [v.tolist() for v in rv]
        assert [r["kind"] for r in rg["regions"]] == [r["kind"] for r in jd["regions"]]
        tg = U.read_json(os.path.join(out, "post", "view3d", e["dirs"]["tgt"], "manifest.json"))
        er = U.read_json(os.path.join(out, "post", "view3d", e["dirs"]["err"], "manifest.json"))
        assert tg["ranges"]["u_max"] == pytest.approx(e["umax_tgt"], rel=1e-6) or tg["ranges"]["u_max"] >= e["umax_tgt"]
        assert er["ranges"]["u_max"] >= e["err_max"] * (1 - 1e-9)


def test_diag_off_and_legacy(tmp_path):
    mesh, doe = T.build_same(tmp_path / "a")
    doe["cfg"] = {**T.CFG_FULL, "bead_doe": {"enabled": True, "view3d": {"jig_diag": False}}}
    out, post, ids = T.run(str(tmp_path / "a" / "o"), doe, mesh, rank=T.rank_snap())
    assert not os.path.exists(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    assert not glob.glob(os.path.join(out, "post", "view3d", "*jigdiag*"))
    mesh, doe = T.build_same(tmp_path / "b")
    out, post, ids = T.run(str(tmp_path / "b" / "o"), doe, mesh)                     # 지그 없는 스냅샷 = 사이드카 없음
    assert not os.path.exists(os.path.join(out, "post", stg.JIG_VIEW_JSON))


# ---------------------------------------------------------------- V-0233-3 하중 정의 보기
def test_rank_views_consistent_and_unmixed(jrun):
    out, post, ids, _doe = jrun
    rv = _side(out)["rank_views"]
    results = [U.read_json(p) for p in sorted(glob.glob(os.path.join(out, "run", "designs", "*", "result.json")))]
    for view, metric in (("jig", "jig"), ("full", "solve")):
        R = rk.rank(results, noise_floor=post.get("noise_floor"), metric=metric, lin_form="ritz", lin_valid=0.3)
        v = rv[view]
        assert v["metric"] == metric and v["C_ref"] == pytest.approx(R["C_ref"])
        assert [x["id"] for x in v["ranking"]] == [x["id"] for x in R["ranking"]]
        assert [x["score"] for x in v["ranking"]] == pytest.approx([x["score"] for x in R["ranking"]])
        assert [x["worst_entry_id"] for x in v["ranking"]] == [x["worst_entry_id"] for x in R["ranking"]]
        assert "sensitivity" in v and "sensitivity_reason" in v and v["per_esl_inline"] is True
    for x in rv["jig"]["ranking"] + [rv["jig"]["baseline"]]:
        assert not set(stg.VIEW_DROP_JIG) & set(x) and x["epsmax"] is None
        for p in x.get("per_esl") or []:
            assert not {"C_solve", "rho", "imbalance_rel", "umax_def"} & set(p)
    by = {r["id"]: {p["entry_id"]: p for p in r["per_esl"]} for r in results}
    for x in rv["jig"]["ranking"]:
        assert x["umax"] == by[x["id"]][x["worst_entry_id"]]["umax_jig"]           # 지그 umax(mm)
    for x in rv["full"]["ranking"] + [rv["full"]["baseline"]]:
        assert not set(stg.VIEW_DROP_FULL) & set(x)
    assert [x["id"] for x in rv["jig"]["ranking"]] == [x["id"] for x in post["ranking"]]   # metric jig 스터디 = 주 순위와 같음


# ---------------------------------------------------------------- V-0233-4 3D 다시 만들기 = 결과 파일 불변
def _hashes(out):
    pats = ["post/ranking.csv", "post/result.json", "post/per_esl.json", "post/designs.json", "report.html",
            "run/designs/*/result.json", "best/**/*"]
    h = {}
    for p in pats:
        for f in sorted(glob.glob(os.path.join(out, p), recursive=True)):
            if os.path.isfile(f):
                with open(f, "rb") as fh:
                    h[os.path.relpath(f, out)] = hashlib.sha256(fh.read()).hexdigest()
    return h


def test_regen_keeps_result_files(tmp_path):
    mesh, doe = T.build_same(tmp_path)
    out, post, ids = T.run(str(tmp_path / "o"), doe, mesh, rank=T.rank_snap())
    side0 = _side(out)
    # v0.23.1 형으로 되돌림: result.json 에 view3d_jig* 없음, 지그 3D·사이드카·진단 폴더 없음
    rp = os.path.join(out, "post", "result.json")
    res = U.read_json(rp)
    for k in ("view3d_jig", "view3d_jig_esl", "view3d_jig_ref"):
        res.pop(k)
    U.write_json(rp, res)
    import shutil
    for d in glob.glob(os.path.join(out, "post", "view3d", "*jig*")):
        shutil.rmtree(d)
    os.remove(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    before = _hashes(out)
    assert any(k.startswith("run/designs/") for k in before) and "report.html" in before
    spec = {"stage": "bd_post", "out": out, "doe": {**doe, "rank": T.rank_snap(), "rev": 1, "post_mode": "view3d"}}
    r = stg.run_stage(spec, lambda s: None)
    assert r["result"] is None and r["files"] == ["post/" + stg.JIG_VIEW_JSON]
    assert _hashes(out) == before                                                  # 결과 파일 바이트 불변
    side = _side(out)
    assert side["source"] == "view3d_regen"
    assert {"view3d_jig", "view3d_jig_esl", "view3d_jig_ref"} <= set(side)
    assert side["view3d_jig"] == post["view3d_jig"] and side["view3d_jig_ref"] == post["view3d_jig_ref"]
    for d in side["view3d_jig"].values():
        assert os.path.isfile(os.path.join(out, "post", "view3d", d, "manifest.json"))
    assert json.dumps(side["rank_views"], sort_keys=True) == json.dumps(side0["rank_views"], sort_keys=True)
    assert [e["dirs"] for e in side["jig_diag"]["entries"]] == [e["dirs"] for e in side0["jig_diag"]["entries"]]
    # v0.23.2 형(result.json 에 view3d_jig 있음): 지그 응답 3D 는 다시 만들지 않음 → 사이드카에 키 없음
    res["view3d_jig"] = post["view3d_jig"]
    U.write_json(rp, res)
    stg.run_stage(spec, lambda s: None)
    assert "view3d_jig" not in _side(out)


def test_regen_requires_result(tmp_path):
    mesh, doe = T.build_same(tmp_path)
    out = str(tmp_path / "o")
    os.makedirs(os.path.join(out, "post"))
    with pytest.raises(stg.EslError) as ei:
        stg.run_stage({"stage": "bd_post", "out": out, "doe": {**doe, "rev": 1, "post_mode": "view3d"}}, lambda s: None)
    assert ei.value.code == "RESULT_NOT_READY"
