"""지그 순위 통합(계약 esl_jig_rank.md V-JIG-6 통합·7·11 일부·12): ① case_once 접촉 영역, metric 무관 계산, fallback, ② 패치 보충,
옛 스냅샷 불변, 해시, ④·옛 ③ unsupported(스텁), ③ xfer 지그 노드. gmsh 가 필요한 ③④ 전체 파이프라인은 test_lt_modes 가 담당."""
import copy
import csv
import inspect
import os
import re
import types

import numpy as np
import pytest
import synth_doe as sd

from esl.doe import DEFAULTS
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.library import _util as U

CFG_FULL = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}
LT = {"schema": 1, "method": "work"}
SP = {"method": "fullfact", "levels": 2, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 6.0}]}
NX, NY, LX, LZ = 12, 8, 300.0, 200.0


def jcfg(**over):
    j = copy.deepcopy(DEFAULTS["rank"]["jig"])
    j.update(over)
    return j


def rank_snap(metric="jig", jig=None, **kw):
    r = {"schema": 2, "metric": metric, "lin_form": "ritz", "lin_valid": 0.3, "imbalance_warn": 0.02}
    if jig is not False:
        r["jig"] = jig if jig is not None else jcfg()
    else:
        r["schema"] = 1
    r.update(kw)
    return r


def tie_groups():
    """짧은 변(x = 0, x = Lx) 근처 노드 4개씩 2 묶음(비공선) — plate 노드 인덱스 i·(ny+1)+j."""
    n = NY + 1
    a = [0 * n + 0, 0 * n + 1, 0 * n + 2, 1 * n + 1]
    b = [NX * n + 0, NX * n + 1, NX * n + 2, (NX - 1) * n + 1]
    return [a, b]


def _hex_block(n0, e0, x0, z0, nx, nz, y0, y1, d=25.0):
    rows, idx = [], {}
    for k, y in enumerate((y0, y1)):
        for j in range(nz + 1):
            for i in range(nx + 1):
                idx[(i, j, k)] = n0 + len(rows)
                rows.append((idx[(i, j, k)], (x0 + i * d, y, z0 + j * d)))
    el = []
    for j in range(nz):
        for i in range(nx):
            el.append([e0 + len(el), idx[(i, j, 0)], idx[(i + 1, j, 0)], idx[(i + 1, j + 1, 0)], idx[(i, j + 1, 0)],
                       idx[(i, j, 1)], idx[(i + 1, j, 1)], idx[(i + 1, j + 1, 1)], idx[(i, j + 1, 1)]])
    return rows, el


def add_neighbors(rad_path, gap=1.0):
    """판(XZ, 법선 Y) 위 gap 떨어진 쉘 판(파트 8: x 100..200, z 50..150)과 아래 gap 떨어진 솔리드(파트 9: x 200..275, z 50..100)."""
    d = 25.0
    rows, shell = [], []
    for j in range(5):
        for i in range(5):
            rows.append((900001 + j * 5 + i, (100.0 + i * d, gap, 50.0 + j * d)))
    for j in range(4):
        for i in range(4):
            a = 900001 + j * 5 + i
            shell.append([900101 + j * 4 + i, a, a + 1, a + 6, a + 5])
    r2, el = _hex_block(910001, 910101, 200.0, 50.0, 3, 2, -10.0 - gap, -gap)
    txt = open(rad_path).read()
    nodes = "/NODE\n" + "".join(f"{i:10d}{x:20.10g}{y:20.10g}{z:20.10g}\n" for i, (x, y, z) in rows + r2)
    sh = "/SHELL/8\n" + "".join("".join(f"{v:10d}" for v in e) + "\n" for e in shell)
    br = "/BRICK/9\n" + "".join("".join(f"{v:10d}" for v in e) + "\n" for e in el)
    i = txt.rindex("/END") if "/END" in txt else len(txt)
    open(rad_path, "w").write(txt[:i] + nodes + sh + br + txt[i:])


def build_same(tmp_path, neighbors=True):
    mesh = sd.plate(nx=NX, ny=NY, Lx=LX, Lz=LZ)
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True)
    rad = sd.write_mesh_rad(str(cd / "model.rad"), mesh)
    if neighbors:
        add_neighbors(rad)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", mesh, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "dent"))]
    step = tmp_path / "up" / "ch.step"
    step.parent.mkdir()
    step.write_text("ISO-10303-21;\nfake\n")
    doe = {"id": "S1", "scenario": "same", "title": "t", "cfg": CFG_FULL,
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": str(cd)},
           "step": {"path": str(step), "file_name": "ch.step"}, "paicad_version": "0.14.0", "load_transfer": LT}
    return mesh, doe


def build_mesh(tmp_path):
    b = sd.plate(nx=NX, ny=NY, Lx=LX, Lz=LZ)
    a = sd.plate(nx=24, ny=14, Lx=LX, Lz=LZ)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    up = tmp_path / "up"
    up.mkdir()
    sd.write_mesh_rad(str(up / "b.rad"), b)
    step = up / "b.step"
    step.write_text("ISO-10303-21;\n")
    return b, {"id": "S2", "scenario": "mesh", "cfg": CFG_FULL, "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
               "mesh": {"path": str(up / "b.rad"), "upload_root": str(up), "part_title": sd.PART_TITLE},
               "step": {"path": str(step), "file_name": "b.step"}, "inch": 75, "load_transfer": LT}


def run(root, doe, mesh, *, rank=None, fixed=True, kinds=("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"), rel="model.rad",
        groups=None):
    """bd_input → bd_loads → bd_matrix → bd_eval(d000 + 안, 가짜 paicad) → bd_post. 반환 (out, post 결과, 안 id)."""
    if rank is not None:
        doe = {**doe, "rank": rank}
    out = os.path.join(root, "_doe")

    def spec(stage, **kw):
        return {"stage": stage, "out": out, "doe": {**doe, **kw}}
    stg.run_stage(spec("bd_input"), lambda s: None)
    sd.write_extract(os.path.join(out, "prep", "extract"), sd.features_doc(mesh, 1))
    if fixed:
        sd.write_fixed(os.path.join(out, "prep", "fixed"), mesh, tie_groups() if groups is None else groups, kinds=kinds)
    elif doe["scenario"] == "mesh":
        sd.write_fixed(os.path.join(out, "prep", "fixed"), mesh, [], kinds=("RBE2",))
    stg.run_stage(spec("bd_loads"), lambda s: None)
    stg.run_stage(spec("bd_matrix", rev=1, spec=SP), lambda s: None)
    m = U.read_json(os.path.join(out, "doe", "1", "matrix.json"))
    stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)
    for d in m["designs"][1:]:
        sd.write_run(os.path.join(out, "run", "designs", d["id"]), mesh, d["values"], rel=rel)
        assert stg.run_stage(spec("bd_eval", rev=1, design=d["id"], paicad={"ok": True}), lambda s: None)["status"] == "OK"
    post = stg.run_stage(spec("bd_post", rev=1), lambda s: None)["result"]
    return out, post, [d["id"] for d in m["designs"]]


def _txt(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _csv(out):
    rows = list(csv.reader(_txt(os.path.join(out, "post", "ranking.csv")).splitlines()))
    return rows[0], rows[1:]


# ---------------------------------------------------------------- V-JIG-12 ① case_once 접촉 영역
@pytest.fixture(scope="module")
def case_run(tmp_path_factory):
    t = tmp_path_factory.mktemp("jigcase")
    mesh, doe = build_same(t)
    return run(str(t / "o"), doe, mesh, rank=rank_snap())


def test_case_once_contact_regions_and_outputs(case_run):
    out, post, ids = case_run
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["schema"] == "esl/doe_jig/1" and jd["status"] == "ok" and jd["code"] is None
    assert jd["regions_from"] == "contact" and jd["n_contact"] == 2 and jd["n_patch"] == 0
    assert sorted(r["part"] for r in jd["regions"] if r["kind"] == "contact") == [8, 9]
    assert jd["fix"]["source"] == "fixed" and jd["fix"]["n_jig"] == 8 and jd["fix"]["kinds"] == DEFAULTS["rank"]["jig"]["fix_kinds"]
    assert {e["entry_id"] for e in jd["entries"]} == {"E0", "E1"} and jd["surf"]["source"] == "case"
    z = U.load_npz(os.path.join(out, "prep", "jig.npz"))
    assert str(z["schema"].ravel()[0]) == "esl/doe_jig/1"
    assert {"node_id", "jig_idx", "omega", "reg_ptr", "reg_node", "reg_w", "reg_dir", "reg_sign", "reg_kind", "reg_part",
            "entry_ids", "a", "C_ref", "umax_ref"} <= set(z)
    b = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    assert b["sm"]["jig"] == {"status": "ok", "code": None}
    assert all(p["C_jig"] > 0 and p["umax_jig"] > 0 for p in b["per_esl"])
    res = post
    assert res["metric"] == "jig" and res["metric_effective"] == "jig" and res["cross_mesh"] is False
    assert res["baseline"]["score_jig"] == pytest.approx(1.0, abs=1e-12)                 # d000 = 기준 그대로
    jb = res["jig"]
    assert jb["status"] in ("ok", "poor") and jb["region_source"] == "contact" and jb["n_regions"] == 2
    assert jb["th"] == {k: DEFAULTS["rank"]["jig"][k] for k in ("mac_min", "umax_err_max", "tie_rel_warn", "cancel_warn", "work_eff_min", "tie_spread_min")}
    assert {e["entry_id"] for e in jb["entries"]} == {"E0", "E1"} and jb["fit_mac_min"] is not None
    assert jb["tie_spread"] == pytest.approx(jd["tie_spread"]) and jb["tie_spread"] > jb["th"]["tie_spread_min"]
    assert not any("JIG_SUPPORT_WEAK" in str(w) for w in res["warnings"])                 # 두 짧은 변 tie = 분포 충분
    sf = jd["surf"]                                                                        # 쉘 파트 8 = 두께 모름(카드·PROP 없음)
    assert sf["thickness_known"] == pytest.approx(1.0 - 2 * sf["n_shell"] / sf["n_tris"])   # 솔리드 외곽 면 = 0(앎)
    for x in res["ranking"]:
        assert x["score"] == pytest.approx(x["score_jig"], rel=1e-12) and x["umax_jig"] is not None
        assert set(x["C_jig"]) == {"E0", "E1"}
    head, rows = _csv(out)
    assert head[-4:] == stg.JIG_CSV_COLS and rows[0][-2] == rows[1][-2]                  # 스터디 공통 열
    base = next(r for r in rows if r[0] == "d000")
    assert float(base[-4]) == pytest.approx(1.0) and float(base[-3]) == pytest.approx(1.0)
    assert "지그" in _txt(os.path.join(out, "report.html"))


def test_metric_solve_still_computes_jig(tmp_path):
    mesh, doe = build_same(tmp_path)
    out, post, ids = run(str(tmp_path / "o"), doe, mesh, rank=rank_snap(metric="solve"))
    assert os.path.isfile(os.path.join(out, "prep", "jig.npz"))                          # Q-JIG-1: metric 무관 항상 계산
    assert post["metric"] == "solve" and post["metric_effective"] == "solve"
    assert all(x.get("score_jig") is not None for x in post["ranking"])
    assert all(x["score"] == pytest.approx(x["score_solve"], rel=1e-12) for x in post["ranking"])
    assert post["jig"]["status"] in ("ok", "poor")


def test_fallback_no_tie_ranks_like_solve(tmp_path):
    mesh, doe = build_same(tmp_path / "a")
    out, post, ids = run(str(tmp_path / "a" / "o"), doe, mesh, rank=rank_snap(), fixed=False)
    assert post["jig"]["status"] == "fallback" and post["jig"]["code"] == "JIG_NO_TIE" and post["jig"]["entries"] == []
    assert post["metric"] == "solve" and post["metric_effective"] == "solve"
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "fallback" and jd["code"] == "JIG_NO_TIE" and not os.path.exists(os.path.join(out, "prep", "jig.npz"))
    r0 = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    assert r0["sm"]["jig"] == {"status": "fallback", "code": "JIG_NO_TIE"} and all(p["C_jig"] is None for p in r0["per_esl"])
    mesh2, doe2 = build_same(tmp_path / "b")
    out2, post2, _ = run(str(tmp_path / "b" / "o"), doe2, mesh2, rank=rank_snap(metric="solve"), fixed=False)
    assert [(x["id"], x["score"]) for x in post["ranking"]] == [(x["id"], x["score"]) for x in post2["ranking"]]
    assert any("체결부" in str(w) or "tie" in str(w).lower() for w in r0["warnings"])      # 베이스라인 결과 경고(문구)


# ---------------------------------------------------------------- ② 업로드 사본: 인접 부품 없음 → 패치 보충
def test_mesh_scenario_patch_fallback(tmp_path):
    b, doe = build_mesh(tmp_path)
    out, post, ids = run(str(tmp_path / "o"), doe, b, rank=rank_snap(), rel="b.rad")
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "ok" and jd["regions_from"] == "patch" and jd["n_contact"] == 0 and jd["n_patch"] >= 1
    assert jd["fill_reason"] == "few_contact" and jd["surf"]["source"] == "mesh" and jd["surf"]["n_tris"] == 0
    assert all(r["kind"] == "patch" and r["sign"] == 0 for r in jd["regions"])
    assert any(str(w).startswith("JIG_REGION_FALLBACK") for w in jd["warnings"])
    assert post["jig"]["region_source"] == "patch" and post["metric_effective"] == "jig"


# ---------------------------------------------------------------- V-JIG-7 옛 스냅샷 불변
def test_legacy_snapshots_have_no_jig(tmp_path):
    mesh, doe = build_same(tmp_path / "n")
    out, post, ids = run(str(tmp_path / "n" / "o"), doe, mesh)                               # (a) rank 없음
    assert not os.path.exists(os.path.join(out, "prep", "jig.json")) and "jig" not in post and "metric" not in post
    head, _ = _csv(out)
    assert not set(stg.JIG_CSV_COLS) & set(head)
    assert all("C_jig" not in p for p in U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))["per_esl"])
    mesh, doe = build_same(tmp_path / "m")
    out, post, ids = run(str(tmp_path / "m" / "o"), doe, mesh, rank={"schema": 1, "metric": "lin", "lin_form": "ritz"})   # (b) jig 없음
    assert not os.path.exists(os.path.join(out, "prep", "jig.npz")) and "jig" not in post and post["metric"] == "lin"
    assert all("score_jig" not in x for x in post["ranking"])
    head, _ = _csv(out)
    assert not set(stg.JIG_CSV_COLS) & set(head) and head[head.index("metric")] == "metric"
    r0 = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    assert "jig" not in r0["sm"] and all("C_jig" not in p for p in r0["per_esl"])
    mesh, doe = build_same(tmp_path / "k")
    out, post, ids = run(str(tmp_path / "k" / "o"), doe, mesh, rank={"schema": 1, "lin_form": "ritz"})   # (c) metric 키 없음 = solve
    assert post["metric"] == "solve" and post["metric_effective"] == "solve" and "jig" not in post


def _ctx(tmp_path, rank, scn="same"):
    spec = {"stage": "bd_post", "out": str(tmp_path / "_doe"), "doe": {"id": "S", "scenario": scn, "cfg": CFG_FULL,
                                                                       "entries": [], "rank": rank, "load_transfer": LT}}
    return stg.Ctx(spec)


def test_sm_metric_default_and_hash(tmp_path):
    c = _ctx(tmp_path, {"schema": 1, "lin_form": "ritz"})
    assert stg._sm(c)["metric"] == "solve" and stg._sm(c)["jig"] is None and stg._jig(c) is None
    c = _ctx(tmp_path, rank_snap())
    assert stg._jig(c) == DEFAULTS["rank"]["jig"] and stg._sm(c)["metric"] == "jig"
    h_on = stg._cfg_hash(c)
    h_off = stg._cfg_hash(_ctx(tmp_path, rank_snap(jig=False, metric="solve")))
    assert h_on != h_off
    for k, v in (("mac_min", 0.5), ("umax_err_max", 0.9), ("tie_rel_warn", 0.5), ("cancel_warn", 0.9), ("work_eff_min", 0.5),
                 ("rho_t_mm3", 3e-8), ("modes_ref321", True), ("tie_spread_min", 0.5)):     # HASH_EXCLUDE = 해시 밖
        assert stg._cfg_hash(_ctx(tmp_path, rank_snap(jig=jcfg(**{k: v})))) == h_on
    for k, v in (("contact_gap_mm", 3.0), ("n_modes", 2), ("modes_sigma", -1.0), ("modes_tol", 1e-6), ("modes_maxiter", 500),
                 ("w_inplane", 0.5), ("reg_force", 1e-2), ("reg_modes", 1e-2), ("basis_tangential", False)):
        assert stg._cfg_hash(_ctx(tmp_path, rank_snap(jig=jcfg(**{k: v})))) != h_on, k     # 하중을 바꾸는 키 = 해시 안
    assert stg._cfg_hash(_ctx(tmp_path, rank_snap(metric="solve"))) == h_on                  # metric 도 해시 밖(SM-6)
    assert stg._jig(_ctx(tmp_path, rank_snap(jig=jcfg(enabled=False), metric="solve"))) is None


# ---------------------------------------------------------------- ④·옛 ③ unsupported, ③ xfer(스텁 — gmsh 불필요)
def test_post_unsupported_plans(tmp_path):
    for scn in ("compare", "step"):
        c = _ctx(tmp_path, rank_snap(), scn=scn)
        assert stg._jig(c) is None and stg._jig_snap(c) is not None
        blk, w = stg._jig_post(c, stg._sm_post(c), {})
        assert blk["status"] == "unsupported" and blk["code"] == "JIG_UNSUPPORTED" and blk["entries"] == []
        assert blk["th"]["mac_min"] == DEFAULTS["rank"]["jig"]["mac_min"] and any("JIG_UNSUPPORTED" in x for x in w)
        sm = stg._sm_post(c)
        assert sm["metric"] == "jig" and sm["metric_effective"] == "solve" and sm["cross_mesh"] is True
    c = _ctx(tmp_path, rank_snap(metric="solve"), scn="compare")
    assert stg._jig_post(c, stg._sm_post(c), {})[1] == []                                   # metric solve = 경고 없음(블록만)
    assert stg._jig_post(_ctx(tmp_path, {"schema": 1, "metric": "lin"}), None, {}) == (None, [])


def test_step_xfer_nodes_unfiltered(tmp_path):
    mesh = sd.plate(nx=NX, ny=NY, Lx=LX, Lz=LZ)
    n = NY + 1
    ids = [int(mesh["node_id"][i]) for g in tie_groups() for i in g]
    out = tmp_path / "_doe"
    U.write_json(str(out / "prep" / "select" / "fixed_transfer.json"), {"node_id": ids}) if (out / "prep" / "select").mkdir(parents=True) is None else None
    c = _ctx(tmp_path, rank_snap(), scn="select")
    c.D["select_base"] = "step"
    plan = tp.plan_for("select", "step")
    infos = []
    sel = stg._jig_nodes(c, plan, mesh, jcfg(), infos)
    assert sel["code"] is None and sel["idx"].size == len(ids) and sel["source"] == "xfer"
    assert any(i.startswith("JIG_FIX_UNFILTERED") for i in infos)


# ---------------------------------------------------------------- V-JIG-15 호출부는 시나리오 이름으로 분기하지 않음
def test_stages_no_scenario_branch_in_jig():
    src = "".join(inspect.getsource(getattr(stg, n)) for n in dir(stg) if n.startswith("_jig"))
    assert "c.scn" not in src and "scenario" not in src
    assert not re.search(r"""["'](case_once|bmesh_once|step_once|step_per_design|compare_per_shape)["']""", src)


# ---------------------------------------------------------------- V-JIG-22·18·21 모드 관성(D-JIG-15)·정규화(D-JIG-16)
def test_modes_default_outputs_and_hz_rescale(tmp_path):
    assert DEFAULTS["rank"]["jig"]["modes_ref321"] is False                                # D-JIG-19: 3-2-1 비교는 켰을 때만
    mesh, doe = build_same(tmp_path / "d")
    out0, post0, _ = run(str(tmp_path / "d" / "o"), doe, mesh, rank=rank_snap())
    md0 = U.read_json(os.path.join(out0, "prep", "jig.json"))["modes"]
    assert md0["n_conv"] >= 1 and md0["hz_321"] is None and md0["hz_ratio"] is None
    assert "mode_lam_321" not in U.load_npz(os.path.join(out0, "prep", "jig.npz")) and post0["jig"]["hz_321"] is None
    mesh, doe = build_same(tmp_path)
    rk0 = rank_snap(jig=jcfg(modes_ref321=True))
    out, post, _ = run(str(tmp_path / "o"), doe, mesh, rank=rk0)
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    md = jd["modes"]
    assert md["n_req"] == 4 and md["n_conv"] >= 1 and md["ok"] and len(md["lam"]) == md["n_conv"] == len(md["hz"])
    assert md["rho_t_used"] == DEFAULTS["rank"]["jig"]["rho_t_mm3"] and md["hz_321"] is not None and md["hz_ratio"] is not None
    assert jd["tangential"] is True and jd["w_inplane"] == 0.1 and jd["reg_force"] == 1e-3
    z = U.load_npz(os.path.join(out, "prep", "jig.npz"))
    m, N = md["n_conv"], z["node_id"].size
    assert z["mode_f"].shape == (m, N, 3) and z["mode_q"].shape == (m, N, 3) and z["mode_lam"].shape == (m,)
    assert z["mode_rho_t"].shape == (1,) and "mode_lam_321" in z and {"node_area", "reg_q", "reg_area", "body_q", "col_kind"} <= set(z)
    assert np.allclose(z["mode_q"] * z["node_area"][None, :, None], z["mode_f"], atol=1e-12)
    assert int((z["col_kind"] == 4).sum()) == m and z["a"].shape[1] == z["col_kind"].size
    jb = post["jig"]
    assert jb["n_modes"] == m and len(jb["hz_jig"]) == m and jb["hz_321"] is not None and jb["hz_ratio"] > 0
    assert jb["fit_mac_min_nomodes"] is not None and jb["cancel_rel_max"] is not None
    assert jb["th"]["cancel_warn"] == 0.5 and jb["th"]["work_eff_min"] == 0.05 and 0 < jb["fit_work_eff_min"] <= 1 and all(e["rot_deg"] >= 0 and e["mac_nomodes"] is not None for e in jb["entries"])
    assert jb["hz_jig"][0] == pytest.approx(md["hz"][0], rel=1e-12)
    # ρ_t 4배 → hz ½ (해시 밖 — 재실행 없이 bd_post 만)
    rk4 = rank_snap(jig=jcfg(modes_ref321=True, rho_t_mm3=4 * DEFAULTS["rank"]["jig"]["rho_t_mm3"]))
    d4 = {**doe, "rank": rk4, "rev": 1}
    p4 = stg.run_stage({"stage": "bd_post", "out": out, "doe": d4}, lambda s: None)["result"]
    assert p4["jig"]["hz_jig"] == pytest.approx([h / 2 for h in jb["hz_jig"]], rel=1e-12)
    assert p4["jig"]["hz_321"] == pytest.approx([h / 2 for h in jb["hz_321"]], rel=1e-12)
    assert p4["jig"]["hz_ratio"] == pytest.approx(jb["hz_ratio"], rel=1e-12)
    assert [(x["id"], x["score"]) for x in p4["ranking"]] == [(x["id"], x["score"]) for x in post["ranking"]]


def test_modes_off_no_eigsh_and_deterministic(tmp_path, monkeypatch):
    from esl.doe import jig as jg

    def boom(*a, **k):
        raise AssertionError("eigsh 호출 금지(n_modes 0)")
    monkeypatch.setattr(jg, "eigsh", boom)
    outs = []
    for k in ("a", "b"):
        mesh, doe = build_same(tmp_path / k)
        outs.append(run(str(tmp_path / k / "o"), doe, mesh, rank=rank_snap(jig=jcfg(n_modes=0))))
    out, post, _ = outs[0]
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "ok" and jd["modes"]["n_req"] == 0 and jd["modes"]["lam"] == [] and jd["modes"]["hz_321"] is None
    assert all(e["without_modes"] is None and e["modes"] == [] for e in jd["entries"])
    z = U.load_npz(os.path.join(out, "prep", "jig.npz"))
    assert not ({"mode_f", "mode_q", "mode_lam", "mode_rho_t", "mode_lam_321"} & set(z)) and not (z["col_kind"] == 4).any()
    jb = post["jig"]
    assert jb["n_modes"] == 0 and jb["hz_jig"] == [] and jb["hz_321"] is None and jb["hz_ratio"] is None
    assert jb["fit_mac_min_nomodes"] is None and all(e["mac_nomodes"] is None for e in jb["entries"])
    b = lambda o: open(os.path.join(o[0], "prep", "jig.npz"), "rb").read()          # noqa: E731
    assert b(outs[0]) == b(outs[1])                                                  # 결정적(비트 동일)


def test_modes_failure_continues_without_modes(tmp_path, monkeypatch):
    from esl.doe import jig as jg
    from esl.errors import EslError

    def bad(*a, **k):
        ex = EslError("JIG_MODES_FAILED", "x")
        ex.detail = {"n_conv": 0, "err": "TEST"}
        raise ex
    monkeypatch.setattr(jg, "jig_modes", bad)
    mesh, doe = build_same(tmp_path)
    out, post, _ = run(str(tmp_path / "o"), doe, mesh, rank=rank_snap())
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "ok" and jd["modes"]["ok"] is False and jd["modes"]["n_conv"] == 0
    assert any("JIG_MODES_FAILED" in str(i) or "모드 계산" in str(i) for i in jd["info"])
    assert post["jig"]["status"] in ("ok", "poor") and post["jig"]["n_modes"] == 0 and post["jig"]["hz_321"] is None
    assert post["metric_effective"] == "jig"


def test_load_cancel_warning_only(tmp_path):
    mesh, doe = build_same(tmp_path)
    out, post, _ = run(str(tmp_path / "o"), doe, mesh, rank=rank_snap(jig=jcfg(work_eff_min=0.9999)))
    assert post["jig"]["status"] in ("ok", "poor") and post["metric_effective"] == "jig" and post["ranking"]
    assert post["jig"]["th"]["work_eff_min"] == 0.9999 and post["jig"]["fit_work_eff_min"] < 0.9999
    assert sum("상쇄" in str(w) for w in post["warnings"]) == 1                      # 경고 1개(순위 계속)
    mesh2, doe2 = build_same(tmp_path / "b")
    _, post2, _ = run(str(tmp_path / "b" / "o"), doe2, mesh2, rank=rank_snap(jig=jcfg(work_eff_min=1e-6)))
    assert not any("상쇄" in str(w) for w in post2["warnings"])
    assert [(x["id"], x["score"]) for x in post["ranking"]] == [(x["id"], x["score"]) for x in post2["ranking"]]


# ---------------------------------------------------------------- D-JIG-19 (Verifier 지적) 예외·경로·지그 분포
def test_baseline_unexpected_exception_falls_back(tmp_path, monkeypatch):
    """지그 함수가 예상 밖 예외(RuntimeError)를 내도 d000 은 성공 — JIG_SKIPPED(detail = 종류·메시지) + fallback → solve 순위."""
    from esl.doe import jig as jg

    def boom(*a, **k):
        raise RuntimeError("synthetic jig crash")
    monkeypatch.setattr(jg, "select_regions", boom)
    mesh, doe = build_same(tmp_path)
    out, post, ids = run(str(tmp_path / "o"), doe, mesh, rank=rank_snap())
    r0 = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    assert r0["sm"]["jig"] == {"status": "fallback", "code": "JIG_SKIPPED"} and all(p["C_jig"] is None for p in r0["per_esl"])
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "fallback" and jd["code"] == "JIG_SKIPPED"
    assert "RuntimeError" in jd["detail"] and "synthetic jig crash" in jd["detail"]
    assert any(str(w).startswith("JIG_SKIPPED") and "RuntimeError" in str(w) for w in r0["warnings"])
    assert post["metric_effective"] == "solve" and post["jig"]["status"] == "fallback" and post["jig"]["code"] == "JIG_SKIPPED"
    assert len(post["ranking"]) == len(ids) - 1


def test_surface_deck_link_or_escape_rejected(tmp_path):
    """원 Case deck 이 링크(또는 허용 폴더 밖)면 읽지 않음 → JIG_SURF_UNAVAILABLE(PATH_OUTSIDE_ROOT) + 패치."""
    mesh, doe = build_same(tmp_path)
    real = doe["base"]["rad_path"]
    lnk = os.path.join(os.path.dirname(real), "link.rad")
    os.symlink(real, lnk)
    out = tmp_path / "_doe"
    (out / "prep").mkdir(parents=True)
    U.write_json(str(out / "prep" / "input.json"), {"part_id": sd.PART_ID})
    J = jcfg()
    fit = np.ones(mesh["node_id"].size, bool)
    plan = {"jig_ctx": "case"}
    for rad, case_dir in ((lnk, os.path.dirname(real)), (real, str(tmp_path / "elsewhere"))):
        c = stg.Ctx({"stage": "bd_post", "out": str(out), "doe": {**doe, "base": {**doe["base"], "rad_path": rad,
                                                                                  "case_dir": case_dir}}})
        warns = []
        surf, why, info = stg._jig_surface(c, plan, mesh, fit, J, warns)
        assert surf is None and why == "surf_failed" and info is None
        assert len(warns) == 1 and warns[0].startswith("JIG_SURF_UNAVAILABLE") and "PATH_OUTSIDE_ROOT" in warns[0]
    c = stg.Ctx({"stage": "bd_post", "out": str(out), "doe": doe})                            # 정상 경로 = 읽음
    surf, why, info = stg._jig_surface(c, plan, mesh, fit, J, [])
    assert surf is not None and why is None and info["n_tris"] > 0


def test_support_weak_clustered_ties(tmp_path):
    """tie 가 한 보스(모서리 한 묶음)에 몰리면 JIG_SUPPORT_WEAK 경고 1개(순위 계속), tie_spread 는 jig.json·result.json 에."""
    mesh, doe = build_same(tmp_path)
    one = [tie_groups()[0]]
    out, post, _ = run(str(tmp_path / "o"), doe, mesh, rank=rank_snap(jig=jcfg(tie_spread_min=0.15)), groups=one)
    jd = U.read_json(os.path.join(out, "prep", "jig.json"))
    assert jd["status"] == "ok" and jd["fix"]["n_jig"] == 4 and 0 < jd["tie_spread"] < 0.15
    jb = post["jig"]
    assert jb["tie_spread"] == pytest.approx(jd["tie_spread"]) and jb["th"]["tie_spread_min"] == 0.15
    assert sum(str(w).startswith("JIG_SUPPORT_WEAK") for w in post["warnings"]) == 1
    assert post["metric_effective"] == "jig" and jb["status"] in ("ok", "poor") and post["ranking"]
