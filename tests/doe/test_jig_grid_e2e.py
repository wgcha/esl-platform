"""v0.24.8 격자 지그 통합(계약 esl_jig_grid_map.md §2.3·§3·§5·§6 — V-0248-JG-5·8·10·11·13·16·17(코어)·18·20·21·22).

세계 = tests/doe/synth_jig_grid.py: ④ 형상 직접 비교(기준 = Case 메시 d000, d001 = 다른 메시 h 4, d002 = 같은 위상 비드(강성↑)) ·
옛 ③(scenario step, 가짜 gmsh — 안 = 띠 비드 깊이 변수). Case 지그 = 엔트리마다 04_esl jig_disp·jig_spring."""
import copy
import json
import os
import time

import numpy as np
import pytest
import synth_jig_grid as G

from esl.doe import DEFAULTS
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.library import _util as U
from esl.mech import grid_map as gm
from esl.mech import jig_bc


def _P(out, *a):
    return os.path.join(out, *a)


def _res(out, did):
    return U.read_json(_P(out, "run", "designs", did, "result.json"))


def _jgr(out, did):
    return U.read_json(_P(out, "run", "designs", did, stg.JG_JSON))


def _codes(ws):
    return [str(w if isinstance(w, str) else w.get("code")).split(":", 1)[0] for w in ws]


@pytest.fixture(scope="module")
def cmp_run(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("jg4"))
    doe, out, A = G.cmp_world(root, rank=G.rank_snap(grid=True))
    t0 = time.monotonic()
    post = G.run_cmp(doe, out)
    return {"doe": doe, "out": out, "A": A, "post": post, "seconds": time.monotonic() - t0}


@pytest.fixture(scope="module")
def step_run(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("jg3"))
    mp = pytest.MonkeyPatch()
    try:
        with G.fake_gmsh(mp):
            doe, out, A = G.step_world(root, rank=G.rank_snap(grid=True))
            post = G.run_step(doe, out, A)
            yield {"doe": doe, "out": out, "A": A, "post": post, "mp": mp}
    finally:
        mp.undo()


# ---------------------------------------------------------------- V-0248-JG-17(코어)·10·5 ④ 격자 순위
def test_cmp_grid_rank_files_and_monotone(cmp_run):
    out, res = cmp_run["out"], cmp_run["post"]["result"]
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    assert prep["schema"] == gm.SCHEMA and prep["status"] == "ok" and prep["cell_mm"] == 3.0
    assert {s: m["status"] for s, m in prep["methods"].items()} == {"jig_disp": "ok", "jig_spring": "ok"}
    assert len(prep["groups"]) == 1 and os.path.isfile(_P(out, *prep["groups"][0]["npz"].split("/")))
    z = U.load_npz(_P(out, *prep["groups"][0]["npz"].split("/")))
    for k in ("f_jig_disp", "f_jig_spring", "vox_key", "vox_u_part", "tie_x", "tie_seg", "tie_tri", "tie_q", "tie_kappa_jig_spring",
              "tie_kq_jig_spring", "cellF_jig_disp", "sup_x"):
        assert k in z, k
    assert "tie_kappa_jig_disp" not in z                                       # 강제 변위 출처 = k 없음
    assert res["metric_effective"] == "jd" and res["cross_mesh"] is True
    c = _codes(res["warnings"])
    assert "JIG_GRID_RANK" in c and "SM_CROSS_MESH" not in c                   # 배타
    d0 = _res(out, "d000")
    j0 = _jgr(out, "d000")
    assert j0["schema"] == gm.RUN_SCHEMA and d0["sm"]["jig"]["status"] == "ok"
    for p in d0["per_esl"]:                                                    # d000: C_<pe> = E_0 → score 1 정확
        for src, pe in (("jig_disp", "jd"), ("jig_spring", "js")):
            e0 = next(e for e in j0["methods"][src]["entries"] if e["entry_id"] == p["entry_id"])
            assert p[f"C_{pe}"] == e0["E"]
            for k in ("umax", "WF", "Wg", "umax_ev"):
                assert f"{k}_{pe}" in p or k == "umax_ev"
    sc_ = {x["id"]: x for x in res["ranking"]}
    assert res["baseline"]["id"] == "d000" if "id" in res["baseline"] else True
    assert sc_["d002"]["score"] < 1.0                                          # 비드(강성↑, 같은 위상) → s < 1(jd)
    r2 = _res(out, "d002")
    for pe in ("jd", "js"):
        s_ = max(p[f"C_{pe}"] / q[f"C_{pe}"] for p, q in zip(r2["per_esl"], d0["per_esl"]))
        assert s_ < 1.0, pe
    jig = res["jig"]
    assert jig["transfer"] == "grid" and jig["status"] in ("ok", "poor") and jig["grid"]["n_shapes"] == 3
    assert jig["grid"]["noise_floor"] == res["noise_floor"] and res["noise_floor"] >= DEFAULTS["rank"]["jig_grid"]["noise_floor_min"]
    for src in ("jig_disp", "jig_spring"):
        g = jig["methods"][src]["grid"]
        assert g["n_ok"] == 3 and g["n_failed"] == 0 and g["recon_mac_d000"] is not None
        assert [x["cell_mm"] for x in g["conv"]] == [5.0, 10.0] and all(x["mac_min"] is not None for x in g["conv"])
    head = open(_P(out, "post", "ranking.csv"), encoding="utf-8").readline().strip().split(",")
    assert head[-4:] == ["C_jd", "umax_jd", "C_js", "umax_js"]
    rep = open(_P(out, "report.html"), encoding="utf-8").read()
    assert "격자" in rep


def test_cmp_factor_count_and_map(cmp_run):
    out = cmp_run["out"]
    for did in ("d000", "d001", "d002"):
        j = _jgr(out, did)
        assert j["factor"]["n"] == 2                                           # [prescribed, spring] → 형상당 분해 2(d000 수렴 0 추가)
        assert j["map"]["tie"]["n_miss"] == 0
        for src in ("jig_disp", "jig_spring"):
            for e in j["methods"][src]["entries"]:
                assert e["load"]["dF_rel"] <= 1e-9 and e["load"]["dM_rel"] <= 1e-9
    assert _jgr(out, "d000")["conv"]["jig_disp"][0]["cell_mm"] == 5.0


# ---------------------------------------------------------------- V-0248-JG-8 하중 = _plan_loads cell(s) 비트 동일
def test_loads_bitwise_plan_loads(cmp_run):
    out, doe = cmp_run["out"], cmp_run["doe"]
    c = stg.Ctx({"stage": "bd_eval", "out": out, "doe": {**doe, "design": "d001"}})
    t, _ = sc.load_base(c.p("prep"))
    mesh, sup, _l, _i = stg._cmp_design_mesh(c, t, "d001")
    reg = c._lt_last["region"]
    last = dict(c._lt_last)
    res = stg._jg_shape(c, t, "d001", mesh, sup, reg, keep_u=True)
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    z = U.load_npz(_P(out, *prep["groups"][0]["npz"].split("/")))
    from esl.doe import load_transfer as ltm
    ents = {str(e.meta["entry_id"]): e for e in c.entries(raw=True)}
    srcs = [ltm.src_load(eid, ents[eid].raw, z["f_jig_disp"][k], ents[eid].meta["frame"])
            for k, eid in enumerate(prep["groups"][0]["entry_ids"])]
    L, _info = stg._plan_loads(c, stg._lt_plan(c), "d001", last["dst"], ("cell", 3.0), {}, srcs=srcs)
    for eid, F in L:
        assert np.asarray(res["loads"]["jig_disp"][eid]).tobytes() == np.asarray(F).tobytes()
    # 3D 재실행 = 평가 값(결정적)
    j1 = _jgr(out, "d001")
    for src in ("jig_disp", "jig_spring"):
        for e in j1["methods"][src]["entries"]:
            assert res["methods"][src]["rows"][e["entry_id"]]["C_mix"] == e["C_mix"]


def test_load_resid_warning_code(tmp_path):
    g = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    g["load_resid_warn"] = 1e-300
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=g), shapes=G.SHAPES_DEFAULT[:1])
    G.run_cmp(doe, out, post=False)
    assert any(str(w).startswith("JIG_GRID_LOAD_RESID") for w in _jgr(out, "d001")["warnings"] + _res(out, "d001")["warnings"])


# ---------------------------------------------------------------- V-0248-JG-13 3D
def test_cmp_3d_sidecar_and_regen(cmp_run, monkeypatch):
    out, doe, res = cmp_run["out"], cmp_run["doe"], cmp_run["post"]["result"]
    side = U.read_json(_P(out, "post", stg.JIG_VIEW_JSON))
    for tag in ("jd", "js"):
        assert side[f"view3d_{tag}"] and side[f"view3d_{tag}_ref"]
        for did, name in side[f"view3d_{tag}"].items():
            assert name == f"{did}_{tag}" and os.path.isfile(_P(out, "post", "view3d", name, "manifest.json"))
        for _e, name in side[f"view3d_{tag}_ref"].items():
            assert name.startswith(f"d000_{tag}_e") and os.path.isdir(_P(out, "post", "view3d", name))
    assert set(side["rank_views"]) >= {"jig_disp", "jig_spring", "full"}
    v = side["rank_views"]["jig_disp"]
    assert v["metric"] == "jd" and v["sensitivity"] is None and v["sensitivity_reason"] == "COMPARE_NO_PARAMS"
    assert all("shape" in x for x in v["ranking"])
    assert "result.json" and "view3d_jd" not in res                           # result.json 불변(사이드카에만)
    # 다시 만들기(④ m = None): 옛 사이드카 3D 키 없애고 → 새로 만듦
    side2 = {k: v_ for k, v_ in side.items() if not k.startswith("view3d_j")}
    U.write_json(_P(out, "post", stg.JIG_VIEW_JSON), side2)
    r = stg.run_stage({"stage": "bd_post", "out": out, "doe": {**doe, "post_mode": "view3d"}}, lambda m: None)
    s3 = U.read_json(_P(out, "post", stg.JIG_VIEW_JSON))
    assert s3["view3d_jd"] == side["view3d_jd"] and s3["source"] == "view3d_regen" and r["files"]
    # 실패 격리: 3D 재실행 예외 → VIEW3D_FAILED 경고만
    U.write_json(_P(out, "post", stg.JIG_VIEW_JSON), side2)

    def boom(*a, **k):
        raise RuntimeError("3d")
    monkeypatch.setattr(stg, "_jg_shape", boom)
    stg.run_stage({"stage": "bd_post", "out": out, "doe": {**doe, "post_mode": "view3d"}}, lambda m: None)
    s4 = U.read_json(_P(out, "post", stg.JIG_VIEW_JSON))
    assert "view3d_jd" not in s4 and any(str(w).startswith("VIEW3D_FAILED") for w in s4["warnings"])
    U.write_json(_P(out, "post", stg.JIG_VIEW_JSON), side)


# ---------------------------------------------------------------- V-0248-JG-20 옛 ③(scenario step) e2e
def test_step_grid_e2e(step_run):
    out, res = step_run["out"], step_run["post"]["result"]
    assert res["metric_effective"] == "jd" and "JIG_GRID_RANK" in _codes(res["warnings"])
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    assert prep["status"] == "ok" and prep["placement"]["kind"] in ("global", "rigid", "frame")
    d0 = _res(out, "d000")
    assert all(p["C_jd"] is not None and p["C_js"] is not None for p in d0["per_esl"])
    ids = [x["id"] for x in res["ranking"]]
    assert ids and all(_jgr(out, i)["status"] == "ok" for i in ids)
    head = open(_P(out, "post", "ranking.csv"), encoding="utf-8").readline().strip().split(",")
    assert head[-4:] == ["C_jd", "umax_jd", "C_js", "umax_js"]
    assert res["jig"]["transfer"] == "grid"
    side = U.read_json(_P(out, "post", stg.JIG_VIEW_JSON))
    assert side.get("view3d_jd")


def test_step_rigid_placement_e2e(tmp_path, monkeypatch):
    """옛 ③ 배치 auto → rigid(기준 형상이 A 에서 강체 이동): 형상 노드 → A 좌표 unplace·R_pl, 지그 잡기 miss 0."""
    from esl.doe import step_graph as sgm
    th = np.radians(10.0)
    R = [[np.cos(th), 0.0, np.sin(th)], [0.0, 1.0, 0.0], [-np.sin(th), 0.0, np.cos(th)]]
    tvec = [15.0, 0.0, -8.0]
    real_plate = G.plate

    def moved(h=5.0, **kw):
        m = real_plate(h, **kw)
        if kw.get("node_base") == G.STEP_BASE["node_base"]:
            m["x0"] = np.asarray(m["x0"]) @ np.asarray(R).T + np.asarray(tvec)
        return m
    monkeypatch.setattr(G, "plate", moved)
    monkeypatch.setattr(sgm, "frame_check", lambda *a, **k: {"ok": False, "fit": {"ok": True, "R": R, "t": tvec,
                                                                                  "resid_med_mm": 0.0}})
    with G.fake_gmsh(monkeypatch):
        doe, out, A = G.step_world(str(tmp_path), rank=G.rank_snap(grid=True))
        G.run_step(doe, out, A, post=False)
    assert U.read_json(_P(out, "prep", "input.json"))["load_transfer"]["placement"]["kind"] == "rigid"
    j0 = _jgr(out, "d000")
    assert j0["status"] == "ok" and j0["map"]["tie"]["n_miss"] == 0


# ---------------------------------------------------------------- V-0248-JG-18 실패 격리 · V-10 출처
def test_no_case_jig_falls_back_to_solve(tmp_path):
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True), case=False, shapes=G.SHAPES_DEFAULT[:1])
    post = G.run_cmp(doe, out)
    res = post["result"]
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    assert prep["status"] == "fallback" and prep["code"] == "JIG_GRID_SOURCE_MISSING"
    assert res["metric_effective"] == "solve" and "SM_CROSS_MESH" in _codes(res["warnings"]) \
        and "JIG_GRID_RANK" not in _codes(res["warnings"])
    w = [x for x in res["warnings"] if isinstance(x, dict) and x.get("code") == "JIG_GRID_SOURCE_MISSING"]
    assert w and "다시 실행" in w[0]["message"] and "복제" in w[0]["message"] and "재풀이(solve)" in w[0]["message"]
    assert {"entry", "method", "reason"} <= set(w[0])                          # 구조화 경고(백엔드 {code, message, …})
    assert res["noise_floor"] is None and res["jig"]["status"] == "fallback"
    assert _res(out, "d000")["status"] == "OK"                                 # BASELINE_FAILED 없음


def test_first_method_missing_uses_next_ok(tmp_path):
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True), shapes=G.SHAPES_DEFAULT[1:], methods=("spring",))
    post = G.run_cmp(doe, out)
    res = post["result"]
    assert res["metric_effective"] == "js"
    w = [x for x in res["warnings"] if isinstance(x, dict) and x.get("code") == "JIG_GRID_SOURCE_MISSING"]
    assert w and "강제 변위" in w[0]["message"] and "스프링" in w[0]["message"] and w[0]["method"] == "prescribed"
    # base 모드 _jig_rank_src = 상태 무관 첫 방식(바이트 불변)
    c = stg.Ctx({"stage": "bd_post", "out": out, "doe": doe})
    assert stg._jig_rank_src(c) == "jig_disp" and stg._jg_rank_src(c) == "jig_spring"


def test_runner_exception_only_that_shape(tmp_path, monkeypatch):
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True))
    real = gm.run_shape

    def wrap(mesh_S, *a, **k):
        if np.asarray(mesh_S["x0"]).shape[0] != np.asarray(_A["x0"]).shape[0]:   # d001(다른 메시 h 4)만
            raise RuntimeError("격자 실행기 시험")
        return real(mesh_S, *a, **k)
    monkeypatch.setattr(gm, "run_shape", wrap)
    post = G.run_cmp(doe, out)
    res = post["result"]
    assert res["metric_effective"] == "jd" and res["n_failed"].get("jd", 0) >= 1
    assert any(str(w).startswith("JIG_DESIGN_FAILED") for w in _res(out, "d001")["warnings"])
    assert all(p["C_jd"] is None for p in _res(out, "d001")["per_esl"]) and _res(out, "d001")["status"] == "OK"
    assert res["jig"]["methods"]["jig_disp"]["grid"]["n_failed"] == 1


def test_baseline_grid_failure_no_ref(tmp_path, monkeypatch):
    doe, out, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True), shapes=G.SHAPES_DEFAULT[1:])
    real = gm.run_shape

    def wrap(mesh_S, *a, **k):
        if np.asarray(mesh_S["x0"])[:, 1].max() < 1e-9:                     # d000(평판 Case 메시 — d002 는 비드)
            raise RuntimeError("기준 실패")
        return real(mesh_S, *a, **k)
    monkeypatch.setattr(gm, "run_shape", wrap)
    post = G.run_cmp(doe, out)
    res = post["result"]
    assert res["metric_effective"] == "solve" and "JIG_GRID_NO_REF" in _codes(res["warnings"])
    assert "SM_CROSS_MESH" in _codes(res["warnings"]) and _res(out, "d000")["status"] == "OK"
    assert all(p["C_jd"] is None for p in _res(out, "d002")["per_esl"])


# ---------------------------------------------------------------- V-0248-JG-21 묶음(스프링 파라미터·sp_k 불일치)
def test_groups_spring_params_and_mismatch(tmp_path):
    doe, out, A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=True), shapes=G.SHAPES_DEFAULT[1:])
    cd1 = os.path.join(str(tmp_path), "cases", "c1")
    u1 = G.u_drop(A, 1)
    G.write_case(cd1, A, u1, G.case_jig(A, u1, G.forces(A, u1), k_mode="value", k_value=900.0))   # E1 = 다른 스프링 파라미터
    for s in ("bd_input", "bd_mesh0", "bd_loads"):
        G.run_stage(out, doe, s)
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    assert len(prep["groups"]) == 2 and [g["entry_ids"] for g in prep["groups"]] == [["E0"], ["E1"]]
    # 같은 묶음 안 sp_k 불일치(파라미터 기록은 같고 값만 다름) → 그 엔트리만 fallback
    G.write_case(cd1, A, u1, G.case_jig(A, u1, G.forces(A, u1)))
    z = dict(np.load(os.path.join(cd1, "04_esl", "jig_spring.npz")))
    z["sp_k"] = z["sp_k"] * 1.01
    np.savez_compressed(os.path.join(cd1, "04_esl", "jig_spring.npz"), **z)
    G.run_stage(out, doe, "bd_loads")
    prep = U.read_json(_P(out, "prep", stg.JG_JSON))
    assert len(prep["groups"]) == 1
    e1 = next(e for e in prep["methods"]["jig_spring"]["entries"] if e["entry_id"] == "E1")
    assert e1["status"] == "fallback" and "스프링 k 가 다름" in e1["reason"]
    assert any(str(w).startswith("JIG_GRID_SOURCE_MISSING") and "스프링 k" in str(w) for w in prep["warnings"])
    z = U.load_npz(_P(out, *prep["groups"][0]["npz"].split("/")))
    assert z["ok_jig_spring"].tolist() == [True, False] and z["ok_jig_disp"].tolist() == [True, True]


# ---------------------------------------------------------------- V-0248-JG-22 noise_floor
def test_noise_floor_rules(tmp_path, cmp_run):
    out, res = cmp_run["out"], cmp_run["post"]["result"]
    j0 = _jgr(out, "d000")
    dp5 = max(r_["dpi_max"] for rows in j0["conv"].values() for r_ in rows if r_["cell_mm"] == 5.0)
    nfmin = DEFAULTS["rank"]["jig_grid"]["noise_floor_min"]
    assert res["noise_floor"] == pytest.approx(max(dp5, nfmin), rel=0, abs=0)
    assert all(x.get("noise") == (abs(x["improvement"]) < res["noise_floor"]) for x in res["ranking"])
    c = stg.Ctx({"stage": "bd_post", "out": out, "doe": cmp_run["doe"]})
    assert stg._jg_nf(c, 0.5) == 0.5                                           # 옛 ③ 메시 잡음 바닥이 크면 그 값(셋 중 최댓값)
    g = copy.deepcopy(DEFAULTS["rank"]["jig_grid"])
    g["conv_mm"] = []
    g["noise_floor_min"] = 0.07
    doe2, out2, _A = G.cmp_world(str(tmp_path), rank=G.rank_snap(grid=g), shapes=G.SHAPES_DEFAULT[1:])
    r2 = G.run_cmp(doe2, out2)["result"]
    assert r2["noise_floor"] == 0.07 and r2["jig"]["grid"]["noise_floor"] == 0.07   # conv_mm 빈 값 = noise_floor_min
    assert "conv" not in json.dumps(_jgr(out2, "d000").get("conv") or {}) or _jgr(out2, "d000")["conv"] == \
        {"jig_disp": [], "jig_spring": []}
    # noise_floor_min 은 해시 밖(이어하기 불변)
    ca = stg.Ctx({"stage": "bd_eval", "out": out2, "doe": doe2})
    g3 = dict(g, noise_floor_min=0.15)
    cb = stg.Ctx({"stage": "bd_eval", "out": out2, "doe": {**doe2, "rank": G.rank_snap(grid=g3)}})
    assert stg._cfg_hash(ca) == stg._cfg_hash(cb)


# ---------------------------------------------------------------- V-0248-JG-11 base 모드(①) — jig_grid 있어도 산출물 바이트 동일
def test_base_mode_ignores_grid(tmp_path, monkeypatch):
    import sys

    import test_jig_methods as JMe
    import test_jig_modes as JMo
    JMe._bead_world(monkeypatch)                                               # ① 세계(test_jig_modes runs 와 같은 준비)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_v0248_c1"))
    import golden as GD
    ra, rb = tmp_path / "a", tmp_path / "b"
    ra.mkdir()
    rb.mkdir()
    out_a, _d = JMo._same(ra, monkeypatch)
    real = JMo.snap
    try:
        JMo.snap = lambda: {**real(), "jig_grid": copy.deepcopy(DEFAULTS["rank"]["jig_grid"])}
        out_b, _d = JMo._same(rb, monkeypatch)
    finally:
        JMo.snap = real
    def norm(o, root):
        if isinstance(o, dict):
            return {k: norm(v, root) for k, v in o.items() if "seconds" not in k and k not in ("mtime", "at")}
        if isinstance(o, list):
            return [norm(v, root) for v in o]
        return o.replace(root, "<ROOT>") if isinstance(o, str) else o
    a = GD.tree_sha(out_a, str(ra))
    b = GD.tree_sha(out_b, str(rb))
    assert sorted(a) == sorted(b)
    for k in [k for k in a if a[k] != b[k]]:                                  # 다른 파일 = 시간·mtime·절대 경로 뿐이어야
        assert k.endswith(".json"), k
        ja, jb = (json.load(open(os.path.join(o_, k), encoding="utf-8")) for o_ in (out_a, out_b))
        assert norm(ja, str(ra)) == norm(jb, str(rb)), k
    assert not os.path.exists(os.path.join(out_b, "prep", stg.JG_JSON))


# ---------------------------------------------------------------- V-0248-JG-16 비용(합성 120×80 형상 — 기록)
def test_cost_record(capsys):
    from esl.doe import evaluate as ev
    A = G.plate(3.0)
    S = __import__("synth_compare").lt_plate_mesh(Lx=360.0, Lz=240.0, h=3.0, bead=None, n_tria_cols=0, props=G.PROPS)
    S["x0"] = np.asarray(S["x0"]) * np.array([LXr := G.LX / 360.0, 1.0, G.LZ / 240.0])        # 120×80 칸을 A 판 크기로
    u = G.u_drop(A, 0)
    F = G.forces(A, u)
    cj = G.case_jig(A, u, F)
    grp = G.grid_group(A, [u], [cj], ("prescribed", "spring"))
    L, _ = G.shape_loads(A, S, [F], 3.0)
    t0 = time.monotonic()
    res = gm.run_shape(S, G.sup321(S), {s: [("E0", L[0][1])] for s in ("jig_disp", "jig_spring")}, grp["skel"], grp["field"],
                       grp["GF"], np.eye(3), S["x0"], methods=["prescribed", "spring"], entries=["E0"],
                       params={"tie_dofs": "normal", "kink_deg": 45.0, "dup_deg": 10.0}, cfg=G.GRID_CFG, solver_cfg=G.SOLVER,
                       spring=grp["spring"])
    tg = time.monotonic() - t0
    t1 = time.monotonic()
    ev.evaluate(S, __import__("synth_doe").so.supports_321(S), [("E0", L[0][1])], dict(G.SOLVER), reaction_warn=1e9)
    tb = time.monotonic() - t1
    assert res["factor"]["n"] == 2 and LXr > 0
    with capsys.disabled():
        print(f"\nJG cost 120×80 ({S['x0'].shape[0]} 노드): 격자 지그 {tg:.2f}s(분해 2 · {res['factor']['seconds']:.2f}s) vs "
              f"3-2-1 평가 {tb:.2f}s → 비 {tg / max(tb, 1e-9):.2f}")
