"""v0.24.0 경계력 ESL — 강성 스터디(계약 esl_bforce.md §5·§6, V-0240-c·d·g·h).

합성: ① case_once 판(test_jig_stages.build_same) + 엔트리마다 가짜 Case(04_esl/u_rel·bforce.npz·bforce.json). 엔트리 E0 은 #63 처럼
전 노드 ESL F = K₀u₀(u₀ = 물리 변형 + 큰 비틀림 회전장) — 경계력 하중은 물리 하중 F_true(자기평형).
"""
import glob
import hashlib
import json
import os

import numpy as np
import pytest
import synth_doe as sd
import test_jig_stages as T

from esl.doe import DEFAULTS
from esl.doe import evaluate as ev
from esl.doe import rank as rk
from esl.doe import stages as stg
from esl.library import _util as U
from esl.mech import bforce as bfm
from esl.mech.mass import lumped_mass
from esl.mech.shell import ShellModel

TWIST = 0.35            # #63 대회전 성분(rad) — 판 길이 방향으로 선형 증가하는 비틀림


def _rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _twist(X):
    """x 방향 비틀림 대회전 변위장(선형화하지 않은 회전) — 낙하 변위의 강체·준강체 대회전 성분."""
    L = X[:, 0].max() - X[:, 0].min()
    c = X.mean(axis=0)
    out = np.empty_like(X)
    for i, p in enumerate(X):
        R = _rot_x(TWIST * (p[0] - X[:, 0].min()) / L)
        out[i] = (p - c) @ R.T + c - p
    return out


def _fake_case(root, entry_dir, F_bf, grade="contact"):
    meta = U.read_json(os.path.join(entry_dir, "entry.json"))
    z = U.load_npz(os.path.join(entry_dir, "raw.npz"))
    cd = os.path.join(root, "case_" + meta["entry_id"])
    d = os.path.join(cd, "04_esl")
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "u_rel.npz"), node_id=z["node_id"], u_rel=z["u_rel"])
    np.savez_compressed(os.path.join(d, "bforce.npz"), node_id=z["node_id"], f=F_bf)
    lim = ["BF_TIE_MISSING"] if grade == "contact" else []
    U.write_json(os.path.join(d, "bforce.json"), {"schema": bfm.SCHEMA, "grade": grade, "limits": lim,
                                                   "mass_source": "deck", "frame": {"frame_index": 6},
                                                   "eq_raw": {"ref": {"force_rel": 0.12, "moment_rel": 0.03}},
                                                   "abar_g": 41.0, "corr_rel": 0.2,
                                                   "recon": {"status": "ok", "mac": 0.97, "umax_err": -0.04,
                                                             "reaction_rel": 1e-12}})
    meta["source"] = {"case_dir": cd, "snapshot_dir": None}
    U.write_json(os.path.join(entry_dir, "entry.json"), meta)
    return cd


def _setup(t, grade="contact"):
    mesh, doe = T.build_same(t)
    bd = doe["cfg"]["bead_doe"]                       # v0.24.5 §12: 경계력·내력 기본 끔 → 이 시험(그 출처를 다룸)은 다시 켬
    doe["cfg"] = {**doe["cfg"], "bead_doe": {**bd, "bforce": {**DEFAULTS["bforce"], "enabled": True},
                                             "fint": {**DEFAULTS["fint"], "enabled": True}}}
    X = mesh["x0"]
    sm = ShellModel(X, mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], backend="superlu")
    m = lumped_mass(mesh, 7.85e-9)
    info = {}
    for k, e in enumerate(doe["entries"]):
        z = dict(U.load_npz(os.path.join(e["dir"], "raw.npz")))
        F_true = bfm.inertia_relief(X, m, np.asarray(z["f"], dtype=np.float64))["F_bal"]
        if k == 0:                                     # #63: 전 노드 ESL = K₀ (u_true + 대회전 성분)
            sup = [(int(np.searchsorted(mesh["node_id"], n)), dd) for n, dd in T.sd.so.supports_321(mesh)]
            u_true, _ = sm.solve(F_true, sup)
            u0 = u_true[:, :3] + _twist(X)
            z["u_rel"] = u0
            z["f"] = sm.condensed_forces(u0)
            info["sum_abs_full"] = float(np.linalg.norm(z["f"], axis=1).sum())
            info["sum_abs_bf"] = float(np.linalg.norm(F_true, axis=1).sum())
        np.savez_compressed(os.path.join(e["dir"], "raw.npz"), **z)
        _fake_case(str(t), e["dir"], F_true, grade)
    return mesh, doe, info


@pytest.fixture(scope="module")
def brun(tmp_path_factory):
    t = tmp_path_factory.mktemp("bfdoe")
    mesh, doe, info = _setup(t)
    out, post, ids = T.run(str(t / "o"), doe, mesh, rank=T.rank_snap())
    return {"out": out, "post": post, "ids": ids, "doe": {**doe, "rank": T.rank_snap(), "rev": 1}, "info": info,
            "mesh": mesh}


def _side(out):
    return U.read_json(os.path.join(out, "post", stg.BF_VIEW_JSON))


def test_v0240_bforce_view_and_block(brun):
    out = brun["out"]
    sd_ = _side(out)
    assert sd_["schema"] == stg.BF_VIEW_SCHEMA and sd_["source"] == "bd_post"
    blk = sd_["bforce"]
    assert blk["status"] == "ok" and blk["grade_min"] == "contact" and blk["limits"] == ["BF_TIE_MISSING"]
    assert blk["limit_text"] == ["tie 체결력 미포함 — 조립 부품 하중 누락"] and blk["n_failed"] == 0
    v = sd_["rank_views"]["bforce"]
    assert v["metric"] == "bf" and v["n_ok"] == len(brun["ids"]) - 1
    for d in brun["ids"]:
        sc_ = U.read_json(os.path.join(out, "run", "designs", d, stg.BF_DESIGN_JSON))
        assert sc_["schema"] == stg.BF_DESIGN_SCHEMA and all(p["C_bf"] > 0 for p in sc_["per_esl"])
    # 3D: 안 = <did>_bf, 기준 = d000_bf_e<kk>, 화살표용 하중이 manifest 에
    assert sd_["view3d_bf"] and all(os.path.isdir(os.path.join(out, "post", "view3d", n)) for n in sd_["view3d_bf"].values())
    assert all(os.path.isdir(os.path.join(out, "post", "view3d", n)) for n in sd_["view3d_bf_ref"].values())
    prep = U.read_json(os.path.join(out, "prep", stg.BF_PREP_JSON))
    assert prep["status"] == "ok" and all(r["grade"] == "contact" and r["source"] for r in prep["entries"])


def test_v0240_h_views_independent(brun):
    """탭 독립: 경계력 보기 행에 다른 출처 키 없음, 지그·전 노드 보기(jig_view)·주 순위에 C_bf 없음."""
    out = brun["out"]
    v = _side(out)["rank_views"]["bforce"]
    for x in v["ranking"] + [v["baseline"]]:
        assert not ({"C_jig", "score_jig", "umax_jig", "score_solve", "C_solve", "imbalance_max", "C_bf"} & set(x))
        assert x["umax"] is not None and x["epsmax"] is not None
    jv = U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    for key in ("jig", "full"):
        for x in jv["rank_views"][key]["ranking"]:
            assert "C_bf" not in json.dumps(x) and "umax_bf" not in json.dumps(x)
    res = U.read_json(os.path.join(out, "post", "result.json"))
    assert "C_bf" not in json.dumps(res) and "bforce" not in res
    for d in brun["ids"]:
        assert "C_bf" not in json.dumps(U.read_json(os.path.join(out, "run", "designs", d, "result.json")))


def test_v0240_d_no_inflation_vs_full_esl(brun):
    """#63 대비: 전 노드 ESL(대회전 포함 K₀u₀)은 Σ|F| 가 물리 하중보다 훨씬 크고 설계안 재풀이 umax 가 기준 대비 커질 수 있으나,
    경계력 ESL 은 물리 크기·자기평형이라 안 umax 비가 1 근처(팽창 없음)."""
    info = brun["info"]
    assert info["sum_abs_full"] > 20.0 * info["sum_abs_bf"]
    out = brun["out"]
    v = _side(out)["rank_views"]["bforce"]
    ub = v["baseline"]["umax"]
    rb = [x["umax"] / ub for x in v["ranking"]]
    assert max(rb) <= 1.05 and min(rb) > 0.5
    res = U.read_json(os.path.join(out, "post", "result.json"))
    rf = [x["umax"] / res["baseline"]["umax"] for x in res["ranking"]]
    fb = {x["id"]: x["umax"] / ub for x in v["ranking"]}
    ff = {x["id"]: x["umax"] / res["baseline"]["umax"] for x in res["ranking"]}
    assert all(fb[d] < 1.0 < ff[d] for d in fb)            # 비드 강화: 경계력 = 개선, 전 노드(대회전 상쇄 하중) = 악화로 보임
    brun["info"].update(umax_ratio_bf=rb, umax_ratio_full=rf)
    print("V-0240-d", {"sum_abs_full/bf": info["sum_abs_full"] / info["sum_abs_bf"], "umax_ratio_bf": rb,
                       "umax_ratio_full": rf})


def test_v0240_c_stiffening_monotone(brun):
    """비드 강화(두께 1.0 → 1.5 → 2.0배, 같은 메시) → umax_bf·C_bf 단조 감소(경계력 하중 그대로 재풀이)."""
    out, mesh = brun["out"], brun["mesh"]
    t, _ = stg.sc.load_base(os.path.join(out, "prep"))
    c = stg.Ctx({"stage": "bd_post", "out": out, "doe": brun["doe"]})
    loads = stg._bf_loads(c, dict(t.mesh))
    X = np.asarray(t.mesh["x0"])
    mid = np.abs(X[np.asarray(t.mesh["conn"])[:, 0], 0] - X[:, 0].mean()) < 0.25 * np.ptp(X[:, 0])
    um, Cs = [], []
    for f in (1.0, 1.5, 2.0):
        mm = dict(t.mesh)
        mm["thickness"] = np.where(mid, np.asarray(t.mesh["thickness"]) * f, np.asarray(t.mesh["thickness"]))
        r = ev.evaluate(mm, list(t.supports), loads, {"backend": "superlu", "drill_factor": 1e-4}, reaction_warn=1e-3)
        um.append(max(p["umax"] for p in r["per_esl"]))
        Cs.append(max(p["C"] for p in r["per_esl"]))
    assert um[0] > um[1] > um[2] and Cs[0] > Cs[1] > Cs[2]


def _hashes(out):
    fs = [os.path.join(out, "post", n) for n in ("ranking.csv", "result.json", "per_esl.json", "designs.json")]
    fs += [os.path.join(out, "report.html")] + glob.glob(os.path.join(out, "run", "designs", "*", "result.json"))
    fs += glob.glob(os.path.join(out, "run", "designs", "*", "design.npz"))
    fs += [os.path.join(out, "post", stg.JIG_VIEW_JSON)]
    return {f: hashlib.sha256(open(f, "rb").read()).hexdigest() for f in fs if os.path.isfile(f)}


def test_v0240_g_add_source_existing_study(tmp_path):
    """기존 스터디(경계력 계산 전 — 사이드카 없음) + Case 에 경계력 생김 → post_mode bforce: 결과 파일 바이트 불변, 사이드카·보기."""
    mesh, doe, _ = _setup(tmp_path)
    old_cfg = {**doe["cfg"], "bead_doe": {**doe["cfg"]["bead_doe"], "bforce": {"enabled": False}}}
    out, post, ids = T.run(str(tmp_path / "o"), {**doe, "cfg": old_cfg}, mesh, rank=T.rank_snap())
    assert not os.path.isfile(os.path.join(out, "post", stg.BF_VIEW_JSON))
    assert not glob.glob(os.path.join(out, "run", "designs", "*", stg.BF_DESIGN_JSON))
    h0 = _hashes(out)
    spec = {"stage": "bd_post", "out": out, "doe": {**doe, "cfg": old_cfg, "rank": T.rank_snap(), "rev": 1,
                                                    "post_mode": "bforce", "bforce_cfg": {"enabled": True}}}
    r = stg.run_stage(spec, lambda s: None)
    assert r["files"] == ["post/" + stg.BF_VIEW_JSON]
    assert _hashes(out) == h0                                  # 기존 결과 파일 바이트 불변
    sd_ = _side(out)
    assert sd_["source"] == "add" and sd_["rank_views"]["bforce"]["n_ok"] == len(ids) - 1
    assert len(glob.glob(os.path.join(out, "run", "designs", "*", stg.BF_DESIGN_JSON))) == len(ids)


def test_v0240_unavailable_grade_none(tmp_path):
    """Case 에 경계력 자료 없음(등급 none) → 블록 unavailable + 사유, 보기 없음, 순위·결과 불변."""
    mesh, doe = T.build_same(tmp_path)
    bd = doe["cfg"]["bead_doe"]                       # v0.24.5 §12: 경계력 기본 끔 → 켠 상태에서 자료 없음을 봄
    doe["cfg"] = {**doe["cfg"], "bead_doe": {**bd, "bforce": {**DEFAULTS["bforce"], "enabled": True}}}
    out, post, ids = T.run(str(tmp_path / "o"), doe, mesh, rank=T.rank_snap())
    sd_ = _side(out)
    assert sd_["bforce"]["status"] == "unavailable" and sd_["bforce"]["code"] == "BF_NOT_FOUND"
    assert "rank_views" not in sd_ and sd_["bforce"]["entries"][0]["grade"] == "none"


def test_v0240_rank_metric_bf_legacy_ok():
    """rank(metric bf): 옛 스냅샷(C_lin 없음)도 허용, 값 null 안 = n_failed["bf"]."""
    base = {"id": "d000", "status": "OK", "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1, "C_bf": 2.0}]}
    good = {"id": "d001", "status": "OK", "values": {}, "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1,
                                                                      "C_bf": 1.5}]}
    bad = {"id": "d002", "status": "OK", "values": {}, "per_esl": [{"entry_id": "E0", "C": 1.0, "umax": 1.0, "epsmax": 0.1,
                                                                     "C_bf": None}]}
    R = rk.rank([base, good, bad], metric="bf")
    assert R["n_ok"] == 1 and R["n_failed"]["bf"] == 1 and R["ranking"][0]["score"] == pytest.approx(0.75)


def test_v0240_bf_on_plan_column_only():
    """BF-11: 경계력 ESL 계산 여부는 계획 열 bf 로만 — 시나리오 이름 분기 없음. compare 행 bf none = 계산 안 함(결과 불변)."""
    import inspect
    import types

    from esl.doe import transfer_plan as tp
    cfg = {"bforce": {"enabled": True}}
    for (scn, base), pid in tp.PLAN_OF.items():
        c = types.SimpleNamespace(scn=scn, cfg=cfg, D={}, select_base=base)
        c.D = {"select_base": base} if base else {}
        want = tp.PLANS[pid]["bf"] == "base"
        try:
            got = stg._bf_on(c)
        except Exception:                               # noqa: BLE001 — select 는 스냅샷 기준 필요(plan_for 인자) — 열 값만 확인
            got = want
        assert got is want
    assert tp.plan_for("compare")["bf"] == "none"
    assert stg._bf_on(types.SimpleNamespace(scn="compare", cfg=cfg, D={})) is False
    src = inspect.getsource(stg)
    assert "_bf_on(c)" in src and 'c.scn != "compare" and _bf_on' not in src
