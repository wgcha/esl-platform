"""v0.24.0 보완 내력 ESL·평가 영역 umax — 강성 스터디(계약 esl_fint.md §5·§6, V-0240-F-d·f·g).

합성: ① case_once 판(test_jig_stages.build_same) + 엔트리마다 가짜 Case(04_esl/u_rel·bforce.*(contact)·fint.*(내력 = 자기평형 하중)).
"""
import glob
import hashlib
import json
import os

import numpy as np
import pytest
import test_bforce_doe as B
import test_jig_stages as T

from esl.doe import rank as rk
from esl.doe import stages as stg
from esl.doe import eval_region as evr
from esl.library import _util as U
from esl.mech import bforce as bfm

FI = stg.NODAL_BY_KEY["fint"]
EV = {"mode": "exclude_free_edges", "free_edge_mm": 15.0, "boxes": []}


def _fake_fint(entry_dir, scale=1.0):
    meta = U.read_json(os.path.join(entry_dir, "entry.json"))
    d = os.path.join(meta["source"]["case_dir"], "04_esl")
    z = U.load_npz(os.path.join(d, "bforce.npz"))
    np.savez_compressed(os.path.join(d, "fint.npz"), node_id=z["node_id"], f=scale * np.asarray(z["f"]))
    U.write_json(os.path.join(d, "fint.json"), {
        "schema": bfm.SCHEMA, "source": "fint", "grade": "fint", "limits": [], "mass_source": None,
        "frame": {"frame_index": 6}, "eq_raw": {"ref": {"force_rel": 1e-9, "moment_rel": 2e-3}},
        "abar_g": 0.0, "corr_rel": 0.0, "recon": {"status": "ok", "mac": 0.995, "mac_min": 0.9, "umax_err": 0.01,
                                                   "reaction_rel": 1e-9},
        "fint": {"residual": {"force_rel": 2e-6, "moment_rel": 4e-4}, "unbalanced": False,
                 "shared_nodes": {"status": "ok", "n_shared": 3}},
        "plastic": {"status": "ok", "frac": 0.031, "max": 0.042, "eps_min": 0.002, "n": 5, "n_total": 160}})


def _setup(t):
    mesh, doe, info = B._setup(t)
    for k, e in enumerate(doe["entries"]):
        _fake_fint(e["dir"], scale=1.3 - 0.1 * k)              # 경계력과 다른 하중(값 섞임 검사)
    return mesh, doe


@pytest.fixture(scope="module")
def frun(tmp_path_factory):
    t = tmp_path_factory.mktemp("fidoe")
    mesh, doe = _setup(t)
    rank = T.rank_snap(eval_region=EV)                         # 새 스냅샷(평가 영역 고정)
    out, post, ids = T.run(str(t / "o"), doe, mesh, rank=rank)
    return {"out": out, "ids": ids, "mesh": mesh, "doe": {**doe, "rank": rank, "rev": 1}}


def _v(out, ns):
    return U.read_json(os.path.join(out, "post", stg._nf(ns, "view")))


def test_v0240_f_fint_view_block_3d(frun):
    out = frun["out"]
    sd_ = _v(out, FI)
    blk = sd_["fint"]
    assert sd_["schema"] == stg.BF_VIEW_SCHEMA and sd_["load_source"] == "fint" and blk["source"] == "fint"
    assert blk["status"] == "ok" and blk["grade_min"] == "fint" and blk["limits"] == []
    e0 = blk["entries"][0]
    assert e0["plastic_frac"] == pytest.approx(0.031) and e0["plastic_max"] == pytest.approx(0.042)
    assert e0["n_shared"] == 3 and e0["unbalanced"] is False and e0["res_force_rel"] == pytest.approx(2e-6)
    v = sd_["rank_views"]["fint"]
    assert v["metric"] == "fi" and v["n_ok"] == len(frun["ids"]) - 1
    for d in frun["ids"]:
        sc_ = U.read_json(os.path.join(out, "run", "designs", d, "fint.json"))
        assert sc_["source"] == "fint" and all(p["C_fi"] > 0 and "umax_fi_ev" in p for p in sc_["per_esl"])
    assert sd_["view3d_fi"] and all(n.endswith("_fi") for n in sd_["view3d_fi"].values())
    assert all(os.path.isdir(os.path.join(out, "post", "view3d", n)) for n in sd_["view3d_fi_ref"].values())
    assert all("_fi_e" in n for n in sd_["view3d_fi_ref"].values())
    # 경계력 블록(같은 형식): 내력 전용 값 null, 소성은 Case 에 있으면 표시
    bb = _v(out, stg.NODAL_BY_KEY["bforce"])["bforce"]
    assert bb["source"] == "bforce" and bb["entries"][0]["n_shared"] is None and bb["entries"][0]["unbalanced"] is None


def test_v0240_f_d_tabs_independent(frun):
    """탭 독립: 내력 보기에 다른 출처 값 없음, 다른 보기·주 결과에 내력 값 없음."""
    out = frun["out"]
    vf = _v(out, FI)["rank_views"]["fint"]
    for x in vf["ranking"] + [vf["baseline"]]:
        assert not ({"C_jig", "score_jig", "umax_jig", "score_solve", "C_solve", "imbalance_max", "C_bf", "C_fi"} & set(x))
        assert "C_bf" not in json.dumps(x) and "umax_bf" not in json.dumps(x)
    vb = _v(out, stg.NODAL_BY_KEY["bforce"])["rank_views"]["bforce"]
    jv = U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    for x in vb["ranking"] + jv["rank_views"]["jig"]["ranking"] + jv["rank_views"]["full"]["ranking"]:
        assert "C_fi" not in json.dumps(x) and "umax_fi" not in json.dumps(x)
    res = U.read_json(os.path.join(out, "post", "result.json"))
    assert "C_fi" not in json.dumps(res) and "fint" not in res
    # 순위가 다른 하중이면 다를 수 있음 — 같은 안 집합·각자 지표
    assert {x["id"] for x in vf["ranking"]} == {x["id"] for x in vb["ranking"]}


def test_v0240_f_f_umax_eval_region(frun):
    """새 스냅샷: 모든 출처 행·기준에 umax_ev(그 출처 per_esl 값) ≤ umax(같은 출처), 결과 eval_region 요약."""
    out = frun["out"]
    res = U.read_json(os.path.join(out, "post", "result.json"))
    ev_ = res["eval_region"]
    assert ev_["mode"] == "exclude_free_edges" and 0 < ev_["n_nodes"] < ev_["n_total"]
    jv = U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    views = {"main": res, "jig": jv["rank_views"]["jig"], "full": jv["rank_views"]["full"],
             "bforce": _v(out, stg.NODAL_BY_KEY["bforce"])["rank_views"]["bforce"], "fint": _v(out, FI)["rank_views"]["fint"]}
    for k, v in views.items():
        rows = v["ranking"] + [v["baseline"]]
        for x in rows:
            assert x["umax_ev"] is not None and x["umax_ev"] <= x["umax"] * (1 + 1e-12) + 1e-15, (k, x["id"] if "id" in x else "b")
            assert x["umax_ev_all"] >= x["umax_ev"] - 1e-15
    # 출처별 값이 서로 다름(섞임 없음): 지그 umax_ev ≠ 전 노드 umax_ev(다른 하중·지지)
    assert views["jig"]["baseline"]["umax_ev"] != views["full"]["baseline"]["umax_ev"]
    assert views["fint"]["baseline"]["umax_ev"] != views["bforce"]["baseline"]["umax_ev"]


def test_v0240_f_f_eval_mask_modes():
    mesh = T.plate_mesh() if hasattr(T, "plate_mesh") else None
    if mesh is None:
        from tests.mech.test_bforce import plate
        mesh = plate(nx=10, ny=6, Lx=100.0, Ly=60.0)
    X = mesh["x0"]
    allm = evr.eval_mask(X, mesh["conn"], mesh["elem_type"], "part")
    assert allm.all()
    fe = evr.free_edge_nodes(mesh["conn"], mesh["elem_type"])
    assert fe.size == 2 * (10 + 6)                             # 사각 판 둘레 노드 수
    ex = evr.eval_mask(X, mesh["conn"], mesh["elem_type"], "exclude_free_edges", 15.0)
    from scipy.spatial import cKDTree
    d, _ = cKDTree(X[fe]).query(X)
    assert np.array_equal(ex, d > 15.0) and 0 < ex.sum() < X.shape[0] and not ex[fe].any()
    lo = X.min(axis=0)
    box = evr.eval_mask(X, mesh["conn"], mesh["elem_type"], "box", boxes=[{"lo": lo.tolist(), "hi": (lo + [30.0, 30.0, 50.0]).tolist()}])
    assert np.array_equal(box, np.all((X >= lo) & (X <= lo + [30.0, 30.0, 50.0]), axis=1)) and box.sum() > 0
    with pytest.raises(Exception):
        evr.eval_mask(X, mesh["conn"], mesh["elem_type"], "nope")


def test_v0240_f_g_old_snapshot_no_new_keys(tmp_path):
    """옛 스냅샷(rank 에 eval_region 없음): result.json·per_esl.json·ranking.csv 에 umax_ev·eval_region 없음(새 키 0)."""
    mesh, doe = _setup(tmp_path)
    out, post, ids = T.run(str(tmp_path / "o"), doe, mesh, rank=T.rank_snap())
    for n in ("result.json", "per_esl.json", "ranking.csv"):
        txt = open(os.path.join(out, "post", n), encoding="utf-8").read()
        assert "umax_ev" not in txt and "eval_region" not in txt, n
    for d in ids:
        assert "umax_ev" not in open(os.path.join(out, "run", "designs", d, "result.json"), encoding="utf-8").read()
        assert "umax_fi_ev" not in open(os.path.join(out, "run", "designs", d, "fint.json"), encoding="utf-8").read()
    assert "umax_ev" not in json.dumps(_v(out, FI)["rank_views"]["fint"])


def _hashes(out):
    h = B._hashes(out)
    for n in ("bforce_view.json", "bforce.json"):
        for p in (os.path.join(out, "post", n), os.path.join(out, "prep", n)):
            if os.path.isfile(p):
                h[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    for p in glob.glob(os.path.join(out, "run", "designs", "*", "bforce.json")):
        h[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return h


def test_v0240_f_g_add_fint_existing_study(tmp_path):
    """내력 계산 전 스터디 + post_mode fint: 기존 결과·경계력 사이드카 바이트 불변, 내력 사이드카·보기 생김."""
    mesh, doe = _setup(tmp_path)
    old_cfg = {**doe["cfg"], "bead_doe": {**doe["cfg"]["bead_doe"], "fint": {"enabled": False}}}
    out, post, ids = T.run(str(tmp_path / "o"), {**doe, "cfg": old_cfg}, mesh, rank=T.rank_snap())
    assert not os.path.isfile(os.path.join(out, "post", "fint_view.json"))
    assert os.path.isfile(os.path.join(out, "post", stg.BF_VIEW_JSON))
    h0 = _hashes(out)
    spec = {"stage": "bd_post", "out": out, "doe": {**doe, "cfg": old_cfg, "rank": T.rank_snap(), "rev": 1,
                                                    "post_mode": "fint", "fint_cfg": {"enabled": True}}}
    r = stg.run_stage(spec, lambda s: None)
    assert r["files"] == ["post/fint_view.json"]
    assert _hashes(out) == h0
    sd_ = _v(out, FI)
    assert sd_["source"] == "add" and sd_["rank_views"]["fint"]["n_ok"] == len(ids) - 1


def test_v0240_f_unavailable_no_fint(tmp_path):
    """Case 에 FINT 없음(fint.json grade none + 사유) → 블록 unavailable·사유 그대로, 보기 없음."""
    mesh, doe, _ = B._setup(tmp_path)
    for e in doe["entries"]:
        meta = U.read_json(os.path.join(e["dir"], "entry.json"))
        U.write_json(os.path.join(meta["source"]["case_dir"], "04_esl", "fint.json"),
                     {"schema": bfm.SCHEMA, "source": "fint", "grade": "none", "code": "FINT_NO_DATA",
                      "reason": "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가"})
    out, post, ids = T.run(str(tmp_path / "o"), doe, mesh, rank=T.rank_snap())
    blk = _v(out, FI)["fint"]
    assert blk["status"] == "unavailable" and blk["code"] == "FINT_NO_DATA" and "/H3D/NODA/FINT" in blk["reason"]
    assert "rank_views" not in _v(out, FI)


def test_v0240_f_rank_metric_fi():
    base = {"id": "d000", "status": "OK", "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1, "C_fi": 2.0}]}
    good = {"id": "d001", "status": "OK", "values": {}, "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1,
                                                                      "C_fi": 1.0}]}
    bad = {"id": "d002", "status": "OK", "values": {}, "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1,
                                                                     "C_fi": None}]}
    R = rk.rank([base, good, bad], metric="fi")
    assert R["n_ok"] == 1 and R["n_failed"]["fi"] == 1 and R["ranking"][0]["score"] == pytest.approx(0.5)
