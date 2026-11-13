"""모드별 하중 전달 계획 시험(계약 esl_load_transfer.md V-LT-4·6·7·8 코어, V-LT-15~18, V-LT-12 회귀 코어 부분).

- ④ compare_per_shape: 공정성·지지 이전(LT-7)·평가 영역(LT-8)·파이프라인(진단 파일·CSV 끝 열·view3d_ref·LT_DIAG_SKIPPED),
  legacy 스냅샷 = 지금 경로.
- ① case_once: work = identity → loads.npz·안 결과·순위 옛 스냅샷과 같음, cell = Case 메시 셀 매핑, 진단 truth direct_nodal.
- ② bmesh_once: 전달 1회(안 = 베이스라인 하중), placement auto(구멍 없음 → frame + LT_PLACEMENT), cell null = 옛 ② 비트
  동일, 먼 노드 → BASELINE_FAILED, truth a_direct(상관·MAC null).
- ③ step_once(select step): cell null = 옛 region_loads 비트 동일, 배치 = fixed_transfer frame 판정 재사용(추가 판정 0).
- ③ step_per_design(옛 step): 베이스라인·안마다 같은 규칙(같은 방식·같은 배치, did 분기 없음).
gmsh 를 쓰는 시험은 gmsh 가 없으면 skip."""
import inspect
import json
import os
import re

import numpy as np
import pytest
import synth_compare as scmp
import synth_doe as sd

from esl.doe import DEFAULTS
from esl.doe import compare_lt as clt
from esl.doe import evaluate as ev
from esl.doe import load_transfer as ltm
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.doe import transfer_plan as tp
from esl.errors import EslError
from esl.library import _util as U
from esl.library import entry as en
from esl.opt import target as tg

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
SC = {"backend": "superlu", "drill_factor": 1e-4}
LT = tp.resolve({"schema": 1, "method": "work"}, "compare")
LX, LZ, H0 = 240.0, 180.0, 3.0
CFG_FULL = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}


def _txt(path) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _loads_bytes(out) -> bytes:
    with open(os.path.join(out, "prep", "loads.npz"), "rb") as fh:
        return fh.read()


def _entry(root, mesh, f, eid="E0"):
    return en.load(scmp.lt_save_entry(root, eid, mesh, f), raw=True)


def _solve(tgt, loads, region=None, keep=()):
    return ev.evaluate(tgt.mesh, list(tgt.supports), loads, SC, reaction_warn=1.0, keep_u=list(keep), region=region)


def _loads(tgt, e, variant=None, region=None, h=H0):
    m = tp.method_of(LT, variant)
    plan = {"identity": {"key": "topo+coords", "coord_tol_rel": 0.005}, "placement": {"kind": "global"}}
    src = ltm.src_load(e.meta["entry_id"], e.raw, e.raw["f"], e.meta["frame"], e.summary_for_mapping())
    return ltm.run_transfer_plan(plan, [src], ltm.dst_mesh(tgt.mesh, tgt.frame, region, h), m, {})


# ---------------------------------------------------------------- V-LT-4 공정성·지지
def test_fairness_same_rule_and_support_transfer(tmp_path):
    src = inspect.getsource(stg)
    calls = re.findall(r"_plan_loads\(([^)]*)\)", src)
    assert calls and all("c.scn" not in c for c in calls)                          # (b) d000·모드 분기 없음(같은 함수·spec)
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=(80.0, 110.0, 5.0))
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    fr = e.meta["frame"]
    t0 = sc.compare_target(A, fr, region=None)
    t1 = sc.compare_target(dict(A), fr, supports=t0.supports)
    l0, _ = _loads(t0, e)
    l1, _ = _loads(t1, e)
    r0, r1 = _solve(t0, l0), _solve(t1, l1)
    assert r1["per_esl"][0]["C"] / r0["per_esl"][0]["C"] == 1.0                       # (a) 같은 메시 = score 1
    # (d) 0.4 mm 평행 이동 → 이전 노드 = 최근접, C 는 지지와 무관(자기평형)
    S = scmp.lt_plate_mesh(Lx=LX + 6.0, Lz=LZ, h=H0, bead=(80.0, 110.0, 5.0), offset=(0.4, 0.0, 0.0), node_base=700001)
    ref = clt.support_xyz(t0.mesh, t0.supports)
    sup, si = clt.transfer_supports(ref, S, None, 2 * H0)
    assert si["mode"] == "transfer" and si["max_dist_mm"] == pytest.approx(0.4, abs=1e-9)
    ta = sc.compare_target(S, fr)                                                   # auto(형상마다 PCA)
    tt = sc.compare_target(S, fr, supports=sup)
    la, _ = _loads(ta, e)
    ra, rt = _solve(ta, la), _solve(tt, la)
    assert abs(rt["per_esl"][0]["C"] / ra["per_esl"][0]["C"] - 1) <= 1e-9
    _, sf = clt.transfer_supports(ref, S, None, 0.1)
    assert sf["mode"] == "fallback" and "distance" in sf["reason"]


# ---------------------------------------------------------------- V-LT-6 평가 영역
def _with_wall(m, h=H0, height=24.0):
    """주 시트(z = LZ 가장자리)에 이어진 세로 벽(y 0..height) — 주 시트 밖 추가 형상."""
    X = m["x0"]
    edge = np.flatnonzero(np.isclose(X[:, 2], LZ))
    edge = edge[np.argsort(X[edge, 0])]
    ny = round(height / h)
    rows = [edge]
    newx = []
    base = X.shape[0]
    for k in range(1, ny + 1):
        p = X[edge].copy()
        p[:, 1] = k * h
        rows.append(base + np.arange(edge.size))
        base += edge.size
        newx.append(p)
    conn = [m["conn"]]
    for k in range(ny):
        a, b = rows[k], rows[k + 1]
        conn.append(np.stack([a[:-1], a[1:], b[1:], b[:-1]], axis=1))
    C = np.concatenate(conn)
    ne = C.shape[0]
    x0 = np.concatenate([X] + newx)
    out = {"node_id": 1 + np.arange(x0.shape[0], dtype=np.int64), "x0": x0, "elem_id": 1 + np.arange(ne, dtype=np.int64),
           "elem_type": np.concatenate([m["elem_type"], np.full(ne - m["conn"].shape[0], 4, np.int8)]), "conn": C}
    for k in ("elem_pid", "elem_mid", "thickness", "E", "nu"):
        out[k] = np.full(ne, m[k][0])
    return out, m["conn"].shape[0]


def test_region_main_sheet(tmp_path):
    A = scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None)
    f = scmp.lt_esl_case(A, "smooth")
    e = _entry(tmp_path, A, f)
    M, ne_main = _with_wall(scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=H0, bead=None))
    rc = {**LT["region"], "pad_mm": 1.0}                                            # 벽 첫 줄 중심 y 1.5 > pad
    reg, info = clt.region_of(M, A["x0"], rc, H0)
    assert reg is not None and int(reg.sum()) == ne_main and info["n_out"] == M["conn"].shape[0] - ne_main
    w, inf = clt.region_messages(info, rc)
    assert [x["code"] for x in inf] == ["COMPARE_REGION"] and not w
    fr = e.meta["frame"]
    ck = sc.shape_check(M, fr, [e], stg.opt_settings()["size"], DEFAULTS["compare"], inch=75, region=reg)
    c0 = sc.shape_check(A, fr, [e], stg.opt_settings()["size"], DEFAULTS["compare"], inch=75)
    assert ck["size"]["L_xi"] == pytest.approx(c0["size"]["L_xi"], rel=1e-9)
    assert ck["size"]["L_eta"] == pytest.approx(c0["size"]["L_eta"], rel=1e-9)
    tgt = sc.compare_target(M, fr, region=reg)
    rn = clt.region_nodes(M, reg)
    pos = {int(v): i for i, v in enumerate(M["node_id"].tolist())}
    assert all(rn[pos[n]] for n, _ in tgt.supports)
    for v in (("work", None), ("cell", 10.0), ("cell", None)):
        lv, _ = _loads(tgt, e, v, region=reg)
        assert float(np.abs(lv[0][1][~rn]).max()) == 0.0, v                           # 영역 밖 하중 0
    r = _solve(tgt, lv, region=reg, keep=("E0",))
    assert r["per_esl"][0]["umax"] == pytest.approx(float(np.linalg.norm(r["u"]["E0"][rn], axis=1).max()))
    ra, ia = clt.region_of(M, A["x0"], {**LT["region"], "mode": "all"}, H0)
    assert ra is None and ia["n_out"] == 0


# ---------------------------------------------------------------- 파이프라인 (V-LT-1c·4c·5·7·8 코어·12)
def _study(root, ref="case", lt=None, n_shapes=3, rank=None):
    A = scmp.lt_plate_mesh(Lx=200.0, Lz=150.0, h=5.0, bead=None, n_tria_cols=2,
                           props={"t": 2.0, "E": 205000.0, "nu": 0.3})
    ents = []
    for k, (b, loc) in enumerate(((1.0, 0.3), (0.3, 1.0))):
        f = scmp.lt_esl_forces(A, scmp.lt_u_drop(A, bend=b, local=loc, sigma=8.0, at=(0.3 + 0.3 * k, 0.5)))
        ents.append({"id": f"E{k}", "dir": scmp.lt_save_entry(os.path.join(root, "lib"), f"E{k}", A, f),
                     "label": f"씬 {k}"})
    os.makedirs(os.path.join(root, "case"), exist_ok=True)
    rad = os.path.join(root, "case", "model_0000.rad")
    sd.write_mesh_rad(rad, A)
    paths = [scmp.plate_step(os.path.join(root, "up", f"u{k}", f"p{k}.step"), k, Lx=200.0, Lz=150.0, depth=5.0)
             for k in range(n_shapes)]
    cfg = {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 5.0}}},
           "opt_run": {"solver": {"backend": "superlu"}}}
    if ref == "case":
        shapes = [{"id": f"d{k:03d}", "name": f"s{k}", "file_name": os.path.basename(p), "path": p, "reference": False}
                  for k, p in enumerate(paths) if k > 0]
        extra = {"base": {"entry_id": "E0", "case_id": "c1", "rad_path": rad, "part_title": sd.PART_TITLE,
                          "case_dir": os.path.dirname(rad)}}
    else:
        shapes = [{"id": f"d{k:03d}", "name": f"s{k}", "file_name": os.path.basename(p), "path": p, "reference": k == 0,
                   "sha256": U.sha256_file(p)} for k, p in enumerate(paths)]
        extra = {}
    doe = {"id": "R1", "scenario": "compare", "title": "lt", "cfg": cfg, "entries": ents, "shapes": shapes,
           "reference_source": ref, "inch": 75, "props": {"t": 2.0, "E": 205000.0, "nu": 0.3}, **extra}
    if lt is not None:
        doe["load_transfer"] = lt
    if rank is not None:
        doe["rank"] = rank
    out = os.path.join(root, "run")

    def spec(stage, **kw):
        return {"stage": stage, "out": out, "doe": {**doe, **kw}}
    for s in ("bd_input", "bd_mesh0", "bd_loads"):
        stg.run_stage(spec(s), lambda m: None)
    cmp_ = U.read_json(os.path.join(out, "prep", "compare.json"))
    for x in cmp_["shapes"]:
        if x["status"] == "READY":
            stg.run_stage(spec("bd_eval", design=x["id"]), lambda m: None)
    post = stg.run_stage(spec("bd_post"), lambda m: None)
    return out, post, spec, A, ents


@needs_gmsh
def test_pipeline_case_reference_work(tmp_path, monkeypatch):
    out, post, spec, A, ents = _study(str(tmp_path), "case", {"schema": 1, "method": "work"})
    P = lambda *a: os.path.join(out, *a)
    prep = U.read_json(P("prep", "load_transfer.json"))
    rows = {r["id"]: r for r in prep["shapes"]}
    assert rows["d000"]["fast_path"] == "identity" and rows["d000"]["supports"]["mode"] == "auto"
    assert isinstance(prep["warnings"], list) and all(isinstance(r["warnings"], list) for r in prep["shapes"])
    # (V-LT-1a) prep/loads.npz = ① direct_nodal 비트 동일
    nid, loads = sc.load_loads(P("prep"))
    t, _ = sc.load_base(P("prep"))
    for (eid, F), ent in zip(loads, ents):
        e = en.load(ent["dir"], raw=True)
        fd, _ = tg.entry_load(tg.Target("S1", t.mesh, t.frame, []), e.raw)
        assert np.array_equal(F, fd)
    # (V-LT-5) 먼 노드 = 경고·지지 이전
    cmp_ = {r["id"]: r for r in U.read_json(P("prep", "compare.json"))["shapes"]}
    # 2026-11-13 개정: 비드 깊이 차(5 mm)로 먼 노드 = 경고만(실패는 fail_dist_mm 20 mm 초과 하중 비 — 배치 오류)
    assert cmp_["d001"]["status"] == "READY" and "LT_FAR_NODES" in cmp_["d001"]["warnings"]
    assert cmp_["d002"]["status"] == "READY" and "LT_FAR_NODES" in cmp_["d002"]["warnings"]
    assert rows["d002"]["supports"]["mode"] == "transfer" and rows["d002"]["supports"]["max_dist_mm"] == 0.0
    assert os.path.isfile(P("prep", "shapes", "d002", "transfer.npz"))
    assert not os.path.isfile(P("prep", "shapes", "d000", "transfer.npz"))           # 빠른 경로 = W 없음
    # (V-LT-1c·7) d000 진단: work 행 상관·MAC·배율 = 1, 셀 훑기 variant 전부
    d0 = U.read_json(P("run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "direct_nodal" and d0["d000"]["identity"] is True
    vs = {(r["variant"], r["entry_id"]): r for r in d0["d000"]["rows"]}
    assert {v for v, _ in vs} == {"work", "cell:3", "cell:legacy", "cell:10", "cell:5"}
    for eid in ("E0", "E1"):
        for k in ("load_corr", "mac", "umax_ratio", "C_ratio"):
            assert vs[("work", eid)][k] == pytest.approx(1.0, abs=1e-9)
    res = post["result"]
    lt = res["load_transfer"]
    assert (lt["method"], lt["cell_size_mm"], lt["support"], lt["region_mode"]) == ("work", None, "transfer", "auto")
    assert lt["alt"] == {"method": "cell", "cell_size_mm": 3.0} and lt["truth"] == "direct_nodal"
    assert lt["summary"][0]["variant"] == "work" and lt["summary"][0]["mac_min"] == pytest.approx(1.0, abs=1e-9)
    assert res["view3d"] == ["d000"] + [x["id"] for x in res["ranking"]][:len(res["view3d"]) - 1]   # 목록 불변
    assert set(res["view3d_esl"]) == set(res["view3d"])
    for eid, name in res["view3d_ref"].items():                                     # LT-9 d000_e<kk>
        assert re.fullmatch(r"d000_e\d\d", name) and name not in res["view3d"]
        man = U.read_json(P("post", "view3d", name, "manifest.json"))
        assert man["esl_run_id"] == eid
    diag = U.read_json(P("post", "load_transfer_diag.json"))
    assert diag["schema"] == ltm.DIAG_SCHEMA and diag["reference"]["identity"] is True
    ds = {x["id"]: x for x in diag["shapes"]}
    assert ds["d002"]["score_alt"] > 0 and ds["d000"]["score_alt"] == pytest.approx(1.0)
    head = _txt(P("post", "ranking.csv")).splitlines()[0].strip().split(",")
    assert head[-4:] == ltm_cols()
    rows_csv = [ln.split(",") for ln in _txt(P("post", "ranking.csv")).splitlines()[1:]]
    assert {r[0]: r[-4] for r in rows_csv}["d002"] == "work"
    assert "하중 전달" in _txt(P("report.html"))
    # (V-LT-7) 진단 단계 예외 → LT_DIAG_SKIPPED, 주 결과(per_esl) 불변
    before = U.read_json(P("run", "designs", "d002", "result.json"))["per_esl"]
    os.remove(P("run", "designs", "d002", "done.json"))
    real = stg._plan_loads

    def boom(c, plan, did, dst, variant=None, cache=None):
        if variant is not None:
            raise EslError("MAPPING_DEGENERATE", "시험")
        return real(c, plan, did, dst, variant, cache)
    monkeypatch.setattr(stg, "_plan_loads", boom)
    stg.run_stage(spec("bd_eval", design="d002"), lambda m: None)
    after = U.read_json(P("run", "designs", "d002", "result.json"))["per_esl"]
    assert [(p["entry_id"], p["C"], p["umax"]) for p in after] == [(p["entry_id"], p["C"], p["umax"]) for p in before]
    dd = U.read_json(P("run", "designs", "d002", "load_transfer.json"))
    assert any(str(w).startswith("LT_DIAG_SKIPPED") for w in dd["warnings"]) and "alt" not in dd["per_esl"][0]


def ltm_cols():
    return ["lt_method", "lt_far_frac", "lt_dM_rel", "score_alt"]


@needs_gmsh
def test_pipeline_step_reference_cell_no_alt(tmp_path):
    lt = {"schema": 1, "method": "cell", "cell_size_mm": 10.0, "work": {"far_fail_frac": 1.0},
          "diag": {"alt": False, "cell_sweep_mm": []}}
    out, post, spec, A, ents = _study(str(tmp_path), "step", lt, n_shapes=2)
    d0 = U.read_json(os.path.join(out, "run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "a_direct" and d0["d000"]["identity"] is False
    assert [r["variant"] for r in d0["d000"]["rows"]] == ["cell:10", "cell:10"]
    assert all(r["load_corr"] is None and r["mac"] is None and r["C_ratio"] > 0 for r in d0["d000"]["rows"])
    res = post["result"]
    assert res["load_transfer"]["alt"] is None and res["load_transfer"]["rank_alt_same"] is None
    diag = U.read_json(os.path.join(out, "post", "load_transfer_diag.json"))
    assert all("score_alt" not in x for x in diag["shapes"])
    rows = [ln.split(",") for ln in _txt(os.path.join(out, "post", "ranking.csv")).splitlines()]
    assert rows[0][-4:] == ltm_cols() and {r[0]: r[-4] for r in rows[1:]}["d001"] == "cell:10"
    assert {r[0]: r[-1] for r in rows[1:]}["d001"] == ""


@needs_gmsh
def test_pipeline_legacy_snapshot_unchanged(tmp_path):
    """V-LT-12: 스냅샷에 load_transfer 없음 = 지금 경로(새 파일·키·CSV 열 없음, 하중 = 셀 매핑)."""
    out, post, spec, A, ents = _study(str(tmp_path), "case", None, n_shapes=2)
    assert not os.path.exists(os.path.join(out, "prep", "load_transfer.json"))
    assert not os.path.exists(os.path.join(out, "post", "load_transfer_diag.json"))
    assert not os.path.exists(os.path.join(out, "run", "designs", "d000", "load_transfer.json"))
    res = post["result"]
    assert "load_transfer" not in res and "view3d_ref" not in res and "view3d_esl" not in res
    head = _txt(os.path.join(out, "post", "ranking.csv")).splitlines()[0].strip().split(",")
    assert head[-1] == "elem_ratio_ref"
    assert U.read_json(os.path.join(out, "prep", "compare.json"))["loads"]["method"] == "cell_mapping"
    assert "하중 전달" not in _txt(os.path.join(out, "report.html"))




# ---------------------------------------------------------------- ①② 파이프라인(가짜 paicad) 공용
SP = {"method": "fullfact", "levels": 2, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 6.0}]}


def _scn_run(root, doe, b_mesh, rel="model.rad", lt=None, counter=None):
    """bd_input → bd_loads → bd_matrix → bd_eval(d000 + 모든 안, 가짜 paicad) → bd_post. 반환 (out, post 결과, 안 id)."""
    if lt is not None:
        doe = {**doe, "load_transfer": lt}
    out = os.path.join(root, "_doe")

    def spec(stage, **kw):
        return {"stage": stage, "out": out, "doe": {**doe, **kw}}
    stg.run_stage(spec("bd_input"), lambda s: None)
    sd.write_extract(os.path.join(out, "prep", "extract"), sd.features_doc(b_mesh, 1))
    if doe["scenario"] == "mesh":
        sd.write_fixed(os.path.join(out, "prep", "fixed"), b_mesh, [])
    stg.run_stage(spec("bd_loads"), lambda s: None)
    stg.run_stage(spec("bd_matrix", rev=1, spec=SP), lambda s: None)
    m = U.read_json(os.path.join(out, "doe", "1", "matrix.json"))
    stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)
    n0 = len(counter) if counter is not None else 0
    for d in m["designs"][1:]:
        sd.write_run(os.path.join(out, "run", "designs", d["id"]), b_mesh, d["values"], rel=rel)
        assert stg.run_stage(spec("bd_eval", rev=1, design=d["id"], paicad={"ok": True}), lambda s: None)["status"] == "OK"
    n_design_calls = (len(counter) - n0) if counter is not None else None
    post = stg.run_stage(spec("bd_post", rev=1), lambda s: None)["result"]
    return out, post, [d["id"] for d in m["designs"]], n_design_calls


def _per(out, did):
    return [(p["entry_id"], p["C"], p["umax"], p["epsmax"]) for p in
            U.read_json(os.path.join(out, "run", "designs", did, "result.json"))["per_esl"]]


def _count_runs(monkeypatch):
    calls = []
    real = ltm.run_transfer_plan

    def wrap(plan, srcs, dst, method, cache=None):
        calls.append((method["name"], method.get("cell_size_mm"), json.dumps(plan.get("placement"), sort_keys=True)))
        return real(plan, srcs, dst, method, cache)
    monkeypatch.setattr(ltm, "run_transfer_plan", wrap)
    return calls


# ---------------------------------------------------------------- V-LT-15 ① case_once
def _same_doe(tmp_path):
    mesh = sd.plate()
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True)
    rad = sd.write_mesh_rad(str(cd / "model.rad"), mesh)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", mesh, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "dent"))]
    step = tmp_path / "up" / "ch.step"
    step.parent.mkdir()
    step.write_text("ISO-10303-21;\nfake\n")
    doe = {"id": "S1", "scenario": "same", "title": "t", "cfg": CFG_FULL,
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": str(cd)},
           "step": {"path": str(step), "file_name": "ch.step"}, "paicad_version": "0.14.0"}
    return mesh, doe, dirs


def test_case_once_work_identity_same_as_legacy(tmp_path, monkeypatch):
    mesh, doe, dirs = _same_doe(tmp_path)
    oL, pL, ids, _ = _scn_run(str(tmp_path / "L"), doe, mesh)
    calls = _count_runs(monkeypatch)
    oW, pW, _, n_des = _scn_run(str(tmp_path / "W"), doe, mesh, lt={"schema": 1, "method": "work"}, counter=calls)
    assert n_des == 0                                                              # once: 안마다 전달 0
    pf = _loads_bytes
    assert pf(oL) == pf(oW)                                                        # (a) 하중 바이트 동일
    for did in ids:
        assert _per(oL, did) == _per(oW, did), did
    assert [(x["id"], x["score"]) for x in pL["ranking"]] == [(x["id"], x["score"]) for x in pW["ranking"]]
    inp = U.read_json(os.path.join(oW, "prep", "input.json"))["load_transfer"]
    assert (inp["plan"], inp["fast_path"], inp["placement"]["kind"]) == ("case_once", "identity", "global")
    d0 = U.read_json(os.path.join(oW, "run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "direct_nodal" and d0["d000"]["n_factorizations"] == 1   # (d) 추가 인수분해 0
    for r in d0["d000"]["rows"]:
        if r["variant"] == "work":
            assert r["load_corr"] == pytest.approx(1.0, abs=1e-12) and r["mac"] == pytest.approx(1.0, abs=1e-12)
    assert not os.path.exists(os.path.join(oW, "run", "designs", ids[1], "load_transfer.json"))   # alt_designs 끔
    diag = U.read_json(os.path.join(oW, "post", "load_transfer_diag.json"))
    assert diag["plan"]["id"] == "case_once" and [s["id"] for s in diag["shapes"]] == ["d000"]
    assert pW["load_transfer"]["plan"] == "case_once" and "load_transfer" not in pL           # (b) legacy 키 없음
    hW = _txt(os.path.join(oW, "post", "ranking.csv")).splitlines()[0].strip().split(",")
    hL = _txt(os.path.join(oL, "post", "ranking.csv")).splitlines()[0].strip().split(",")
    assert hW == hL + ["lt_method", "lt_far_frac", "lt_dM_rel", "score_alt"]
    assert not os.path.exists(os.path.join(oL, "prep", "load_transfer.json"))
    # (c) cell null = Case 메시 자신에 to_target(셀 매핑) 비트 동일
    oC, _, _, _ = _scn_run(str(tmp_path / "C"), doe, mesh, lt={"schema": 1, "method": "cell"})
    t, _ = sc.load_base(os.path.join(oC, "prep"))
    _, lc = sc.load_loads(os.path.join(oC, "prep"))
    for (eid, F), dd in zip(lc, dirs):
        e = en.load(dd)
        fl, _ = tg.entry_load(tg.Target("S2", t.mesh, t.frame, []), None, e.summary_for_mapping(), None)
        assert np.array_equal(F, fl)
        assert not np.allclose(F, e.raw["f"])                                      # 비교용 — 직접과 다름


# ---------------------------------------------------------------- V-LT-16 ② bmesh_once
def _mesh_doe(tmp_path, b):
    a = sd.plate(nx=24, ny=14, Lx=480.0, Lz=280.0)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    up = tmp_path / "up"
    up.mkdir()
    sd.write_mesh_rad(str(up / "b.rad"), b)
    step = up / "b.step"
    step.write_text("ISO-10303-21;\n")
    return a, dirs, {"id": "S2", "scenario": "mesh", "cfg": CFG_FULL,
                     "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
                     "mesh": {"path": str(up / "b.rad"), "upload_root": str(up), "part_title": sd.PART_TITLE},
                     "step": {"path": str(step), "file_name": "b.step"}, "inch": 75}


def test_bmesh_once_work_placement_and_cell_legacy(tmp_path, monkeypatch):
    b = sd.plate(nx=30, ny=17, Lx=480.0, Lz=280.0)                                 # 같은 판, 다른 메시(구멍 없음)
    a, dirs, doe = _mesh_doe(tmp_path, b)
    oL, pL, ids, _ = _scn_run(str(tmp_path / "L"), doe, b, rel="b.rad")
    oC, _, _, _ = _scn_run(str(tmp_path / "C"), doe, b, rel="b.rad", lt={"schema": 1, "method": "cell"})
    pf = _loads_bytes
    assert pf(oL) == pf(oC)                                                        # (c) cell null = 옛 ② 비트 동일
    calls = _count_runs(monkeypatch)
    oW, pW, _, n_des = _scn_run(str(tmp_path / "W"), doe, b, rel="b.rad", lt={"schema": 1, "method": "work"},
                                counter=calls)
    assert n_des == 0 and len({c[2] for c in calls}) == 1                          # (a) 안마다 전달 0, 배치 1개
    inp = U.read_json(os.path.join(oW, "prep", "input.json"))
    assert inp["load_transfer"]["plan"] == "bmesh_once" and inp["load_transfer"]["placement"]["kind"] == "frame"
    assert any(str(w).startswith("LT_PLACEMENT") for w in U.read_json(os.path.join(oW, "prep", LT_JSON()))["warnings"])
    t, _ = sc.load_base(os.path.join(oW, "prep"))
    _, lw = sc.load_loads(os.path.join(oW, "prep"))
    for (eid, F), dd in zip(lw, dirs):                                             # 합력 보존(배치된 A 기준)
        e = en.load(dd)
        _, fp = ltm.place(e.raw["x0"], e.raw["f"], {"kind": "frame", "src_frame": e.meta["frame"], "dst_frame": t.frame})
        assert np.linalg.norm(F.sum(axis=0) - fp.sum(axis=0)) <= 1e-9 * np.abs(F).sum()
    d0 = U.read_json(os.path.join(oW, "run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "a_direct" and all(r["load_corr"] is None and r["mac"] is None
                                                     for r in d0["d000"]["rows"])
    assert pW["load_transfer"]["truth"] == "a_direct"
    assert "모델 차" in _txt(os.path.join(oW, "report.html"))
    # (e) 먼 노드 > far_fail → BASELINE_FAILED LT_TRANSFER_FAILED
    bh = sd.plate(nx=24, ny=14, Lx=480.0, Lz=280.0, holes=[(8, 16, 4, 10)])
    _a, _d, doe_h = _mesh_doe(tmp_path / "H", bh)
    with pytest.raises(EslError) as ei:
        _scn_run(str(tmp_path / "Hrun"), doe_h, bh, rel="b.rad",
                 lt={"schema": 1, "method": "work", "work": {"fail_dist_mm": 1.0, "fail_frac": 0.0}})
    assert ei.value.code == "BASELINE_FAILED" and "LT_TRANSFER_FAILED" in ei.value.message


def LT_JSON():
    return stg.LT_JSON


def test_bmesh_placement_rigid_and_global(tmp_path):
    """placement auto: 구멍 일치 → global, 회전 3° → rigid(R·t), 구멍 없음 → frame(위 시험)."""
    holes = [(3, 5, 3, 5), (14, 16, 8, 10), (20, 22, 2, 4), (8, 10, 9, 11), (2, 4, 10, 12), (18, 20, 6, 8)]
    a = sd.plate(nx=24, ny=14, Lx=480.0, Lz=280.0, holes=holes)
    lib = tmp_path / "lib"
    d0 = sd.save_entry(str(lib), "E0", a, "bend", 1.0)[0]
    ent = en.load(d0)
    for kind, rot in (("global", 0.0), ("rigid", 3.0)):
        b = sd.plate(nx=24, ny=14, Lx=480.0, Lz=280.0, holes=holes)
        if rot:
            th = np.radians(rot)
            R = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0], [-np.sin(th), 0, np.cos(th)]])
            b["x0"] = b["x0"] @ R.T + np.array([3.0, 0.0, 2.0])
        t, _ = sc.template_base(b, [ent], stg.opt_settings()["size"], inch=75)
        c = stg.Ctx({"stage": "bd_loads", "out": str(tmp_path / kind), "doe": {"id": "x", "scenario": "mesh",
                     "cfg": CFG_FULL, "entries": [{"id": "E0", "dir": d0}], "load_transfer": {"method": "work"}}})
        pl, info = stg._lt_decide_placement(c, tp.plan_for("mesh"), t, None, 20.0)
        assert pl["kind"] == kind, (kind, pl)


# ---------------------------------------------------------------- V-LT-17 ③ step_once(select step)·step_per_design(옛)
@needs_gmsh
def test_step_once_select_step(tmp_path, monkeypatch):
    from esl.doe import step_graph as sg
    a = sd.plate(nx=20, ny=15, Lx=200.0, Lz=150.0)
    step = scmp.plate_step(str(tmp_path / "in" / "b.step"), 2, Lx=200.0, Lz=150.0, depth=5.0)
    d0 = sd.save_entry(str(tmp_path / "lib"), "E0", a, "bend", 1.0, seed=0)[0]
    base = {"id": "S1", "scenario": "select", "select_base": "step", "select_schema": 2, "bead_source": "manual",
            "cfg": {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 5.0}}},
                    "opt_run": {"solver": {"backend": "superlu"}}},
            "entries": [{"id": "E0", "dir": d0}], "step": {"path": step, "file_name": "b.step"}, "inch": 75,
            "props": {"t": 2.0, "E": 205000.0, "nu": 0.3}}
    outs = {}
    n_fc = []
    real_fc = sg.frame_check

    def fc(*a_, **k):
        n_fc.append(1)
        return real_fc(*a_, **k)
    monkeypatch.setattr(sg, "frame_check", fc)
    for name, lt in (("L", None), ("C", {"schema": 1, "method": "cell"}), ("W", {"schema": 1, "method": "work"})):
        doe = dict(base, **({"load_transfer": lt} if lt else {}))
        out = str(tmp_path / "o" / name)
        for s in ("bd_input", "bd_mesh0", "bd_loads"):
            n0 = len(n_fc)
            stg.run_stage({"stage": s, "out": out, "doe": doe}, lambda m: None)
        outs[name] = (out, len(n_fc) - n0)
    _, lL = sc.load_loads(os.path.join(outs["L"][0], "prep"))
    _, lC = sc.load_loads(os.path.join(outs["C"][0], "prep"))
    assert all(np.array_equal(f1, f2) for (_, f1), (_, f2) in zip(lL, lC))       # cell null = region_loads 비트 동일
    assert outs["W"][1] == outs["L"][1]                                            # 배치 = fixed_transfer 판정 재사용(추가 0)
    inp = U.read_json(os.path.join(outs["W"][0], "prep", "input.json"))["load_transfer"]
    assert inp["plan"] == "step_once" and inp["placement"]["kind"] == "frame"       # 구멍 없는 판 = frame 판정 불가
    _, lW = sc.load_loads(os.path.join(outs["W"][0], "prep"))
    assert all(np.linalg.norm(f.sum(axis=0)) <= 1e-9 * np.abs(f).sum() for _, f in lW)   # 자기평형 ESL → 합력 0 유지


@needs_gmsh
def test_step_per_design_same_rule(tmp_path, monkeypatch):
    from test_mesh_gmsh import make_brep
    a = sd.plate(nx=20, ny=15, Lx=200.0, Lz=150.0)
    (tmp_path / "up").mkdir()
    brep = make_brep(tmp_path / "up" / "nominal.brep", flat=True)
    step = mg.export_step_isolated(brep, str(tmp_path / "up" / "nominal.step"),
                                   stg.settings({"bead_doe": {"mesh": {"occ_sew_faces": 1}}}))
    dirs = [sd.save_entry(str(tmp_path / "lib"), f"E{k}", a, kind, 1.0 + k, seed=k)[0]
            for k, kind in enumerate(("bend", "twist"))]
    doe = {"id": "S3", "scenario": "step", "cfg": {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}},
                                                  "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)], "step": {"path": step},
           "inch": 75, "props": {"t": 1.2, "E": 205000.0, "nu": 0.3}, "mesh_size_mm": 6.0,
           "load_transfer": {"schema": 1, "method": "work", "diag": {"enabled": False}}, "rank": RANK}
    out = str(tmp_path / "_doe")
    rec = []
    real = stg._plan_loads

    def wrap(c, plan, did, dst, variant=None, cache=None):
        rec.append((did, plan["id"], json.dumps(stg._lt_placement(c, plan), sort_keys=True), variant))
        return real(c, plan, did, dst, variant, cache)
    monkeypatch.setattr(stg, "_plan_loads", wrap)

    def spec(stage, **kw):
        return {"stage": stage, "out": out, "doe": {**doe, **kw}}
    stg.run_stage(spec("bd_input"), lambda s: None)
    stg.run_stage(spec("bd_mesh0"), lambda s: None)
    sd.write_extract(os.path.join(out, "prep", "extract"), sd.features_doc(a, 1))
    stg.run_stage(spec("bd_loads"), lambda s: None)
    stg.run_stage(spec("bd_matrix", rev=1, spec=SP), lambda s: None)
    m = U.read_json(os.path.join(out, "doe", "1", "matrix.json"))
    stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)
    for d in m["designs"][1:]:                                                     # 안 메시 = 베이스라인 형상 그대로
        dd = os.path.join(out, "run", "designs", d["id"], "update")
        os.makedirs(dd)
        make_brep(os.path.join(dd, "sample.brep"), flat=True)
        r = stg.run_stage(spec("bd_eval", rev=1, design=d["id"], paicad={"ok": True}), lambda s: None)
        assert r["status"] == "OK", r
    assert {p for _d, p, _pl, _v in rec} == {"step_per_design"}
    assert len({pl for _d, _p, pl, _v in rec}) == 1 and {v for *_r, v in rec} == {None}
    dids = [d for d, *_r in rec]
    assert dids[0] == "d000" and set(dids[1:]) >= {d["id"] for d in m["designs"][1:]}    # 베이스라인 + 안마다
    inp = U.read_json(os.path.join(out, "prep", "input.json"))["load_transfer"]
    assert inp["plan"] == "step_per_design"
    rd = U.read_json(os.path.join(out, "run", "designs", m["designs"][1]["id"], "result.json"))   # 결정 A: 다른 메시 = 지표 없음
    r0 = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    for r_ in (r0, rd):
        assert r_["sm"]["ref"] == "none" and r_["sm"]["disp"] == "none"
        assert all(p["rho"] is None and p["C_ritz"] is None and p["umax_def"] is not None for p in r_["per_esl"])
    assert not os.path.exists(os.path.join(out, "prep", "sm_ref.npz"))
    _, l0 = sc.load_loads(os.path.join(out, "prep"))                                 # 안 메시 = 베이스라인 → 같은 하중(1e-12)
    t0, _ = sc.load_base(os.path.join(out, "prep"))
    dt = sc.design_target(mg.load_mesh(os.path.join(out, "run", "designs", m["designs"][1]["id"], "mesh")), t0.frame)
    c = stg.Ctx(spec("bd_eval", rev=1, design=m["designs"][1]["id"]))
    l1 = stg._lt_target_loads(c, m["designs"][1]["id"], dt, None, 6.0)
    for (e0, f0), (e1, f1) in zip(l0, l1):
        assert e0 == e1 and np.abs(f0 - f1).max() <= 1e-12 * np.abs(f0).max()


# ---------------------------------------------------------------- V-SM-6·7·10 강성 지표(코어 통합)
RANK = {"schema": 1, "metric": "lin", "lin_form": "ritz"}


def test_solve6_equals_evaluate():
    """_solve6 = evaluate.evaluate(같은 per_esl·warnings, 비트 동일) + 6 dof 해(병진 = keep_u)."""
    a = sd.plate()
    sup = tg.auto_supports(a)
    loads = [("E0", sd.so.load(a, "bend", 1.0)), ("E1", sd.so.load(a, "dent", 2.0))]
    r0 = ev.evaluate(a, sup, loads, SC, reaction_warn=1e-9, keep_u=["E0"])
    r1 = stg._solve6(a, sup, loads, SC, reaction_warn=1e-9, keep_u=["E0"], keep6=["E0", "E1"])
    assert r0["per_esl"] == r1["per_esl"] and r0["warnings"] == r1["warnings"]
    assert np.array_equal(r0["u"]["E0"], r1["u"]["E0"]) and np.array_equal(r1["u6"]["E0"][:, :3], r0["u"]["E0"])
    assert r1["u6"]["E1"].shape == (a["x0"].shape[0], 6)


def test_sm_case_once(tmp_path, monkeypatch):
    """① case_once + doe.rank: d000 C_lin = C_ritz = C_ref(ρ = 1), 재풀이 C·umax·εmax = 옛 값, 순위 = metric,
    sm_ref.npz 1회(안마다 build_disp 0), CSV 가운데 열(§6), 옛 스냅샷(rank 없음) = solve 그대로."""
    mesh, doe, dirs = _same_doe(tmp_path)
    oL, pL, ids, _ = _scn_run(str(tmp_path / "L"), doe, mesh)
    calls = []
    real = ltm.build_disp
    monkeypatch.setattr(ltm, "build_disp", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    oS, pS, _, _ = _scn_run(str(tmp_path / "S"), {**doe, "rank": RANK}, mesh, lt={"schema": 1, "method": "work"})
    assert not calls                                                                # ① S = I(베이스라인·안 모두)
    r0 = U.read_json(os.path.join(oS, "run", "designs", "d000", "result.json"))
    for p in r0["per_esl"]:
        assert p["rho"] == pytest.approx(1.0, abs=1e-9) and p["C_lin"] == pytest.approx(p["C"], rel=1e-9)
        assert p["C_ritz"] == pytest.approx(p["C"], rel=1e-9) and p["imbalance_rel"] <= 1e-8
    assert r0["sm"]["ref"] == "base" and r0["sm"]["disp"] == "I" and r0["sm"]["metric"] == "lin"
    for did in ids:                                                                 # V-SM-10 재풀이 값 = 옛 값
        assert [x[:4] for x in _per(oL, did)] == [x[:4] for x in _per(oS, did)], did
    assert pS["metric"] == "lin" and pS["lin_form"] == "ritz"
    assert [(x["id"], x["score"]) for x in pL["ranking"]] == [(x["id"], x["score_solve"]) for x in pS["ranking"]]
    z = U.load_npz(os.path.join(oS, "prep", "sm_ref.npz"))
    assert str(z["schema"].ravel()[0]) == "esl/doe_sm_ref/1" and z["u"].shape[2] == 6
    head = _txt(os.path.join(oS, "post", "ranking.csv")).splitlines()[0].strip().split(",")
    i = head.index("score")
    assert head[i:i + 10] == stg.SM_CSV_MID and "C_solve_E0" in head and head[-4:] == stg.LT_CSV_COLS
    assert "강성 지표" in _txt(os.path.join(oS, "report.html"))
    assert "metric" not in pL and "score_solve" not in pL["ranking"][0]


def test_sm_bmesh_once_base(tmp_path, monkeypatch):
    """② bmesh_once(결정 A): 참조 = 베이스라인 B 메시에서 work 하중으로 푼 해(base), 베이스라인 ρ = 1·C_lin = C_ritz = C,
    안 = 같은 노드 S = I(build_disp 0, sm_ref.npz ref_kind base), 순위 = metric(lin). A 원본 풀이는 LT 진단 참값에만."""
    b = sd.plate(nx=30, ny=17, Lx=480.0, Lz=280.0)
    a, dirs, doe = _mesh_doe(tmp_path, b)
    n_fact = []
    real6 = stg._solve6

    def s6(*a_, **k):
        r = real6(*a_, **k)
        n_fact.append(r["stats"]["n_factorizations"])
        return r
    monkeypatch.setattr(stg, "_solve6", s6)
    calls = []
    realb = ltm.build_disp
    monkeypatch.setattr(ltm, "build_disp", lambda *a_, **k: (calls.append(1), realb(*a_, **k))[1])
    oS, pS, ids, _ = _scn_run(str(tmp_path / "S"), {**doe, "rank": RANK}, b, rel="b.rad",
                              lt={"schema": 1, "method": "work"})
    assert not calls                                                                # S_t 보간 없음(같은 메시만)
    r0 = U.read_json(os.path.join(oS, "run", "designs", "d000", "result.json"))
    assert r0["sm"]["ref"] == "base" and r0["sm"]["disp"] == "I"
    for p in r0["per_esl"]:                                                         # 베이스라인 자체 ρ = 1
        assert p["rho"] == pytest.approx(1.0, abs=1e-9) and p["C_ritz"] == pytest.approx(p["C"], rel=1e-9)
        assert p["C_lin"] == pytest.approx(p["C"], rel=1e-9) and p["imbalance_rel"] <= 1e-8
    for did in ids[1:]:                                                             # 안 = S = I(노드 그대로)
        rd = U.read_json(os.path.join(oS, "run", "designs", did, "result.json"))
        assert rd["sm"]["disp"] == "I" and all(p["rho"] is not None for p in rd["per_esl"])
    z = U.load_npz(os.path.join(oS, "prep", "sm_ref.npz"))
    assert [str(k) for k in z["ref_kind"].tolist()] == ["base"] * len(z["entry_ids"]) and "u_a_0" not in z
    # A 원본 풀이 1회(LT 진단 참값만) + 베이스라인·안 해석
    assert len(n_fact) == 1 + len(ids)
    d0 = U.read_json(os.path.join(oS, "run", "designs", "d000", "load_transfer.json"))
    assert d0["d000"]["truth"] == "a_direct"
    assert pS["metric"] == "lin" and pS["metric_effective"] == "lin" and pS["cross_mesh"] is False
    assert len(pS["ranking"]) == len(ids) - 1 and not any("SM_CROSS_MESH" in str(w) for w in pS["warnings"])


@needs_gmsh
def test_sm_compare_case_and_step(tmp_path):
    """④ compare_per_shape(결정 A): 형상마다 메시가 달라 지표 미적용 — 순위 = work 하중 재풀이 C(metric_effective solve),
    경고 SM_CROSS_MESH 1개, per_esl 지표 키 null·umax_def 만, CSV metric 열 solve, 보고서 '다른 메시 비교'. 기준 STEP 도 같음."""
    out, post, spec, A, ents = _study(str(tmp_path / "c"), "case", {"schema": 1, "method": "work"}, rank=RANK)
    for did in ("d000", "d002"):
        r_ = U.read_json(os.path.join(out, "run", "designs", did, "result.json"))
        assert r_["sm"]["ref"] == "none" and r_["sm"]["metric"] == "lin"
        assert all(p["rho"] is None and p["C_lin"] is None and p["umax_def"] is not None for p in r_["per_esl"])
    assert not os.path.exists(os.path.join(out, "prep", "sm_ref.npz"))
    res = post["result"]
    assert res["metric"] == "solve" and res["metric_effective"] == "solve" and res["cross_mesh"] is True
    assert res["ranking"][0]["score"] < 1.0
    x0 = res["ranking"][0]
    assert x0["score_solve"] == pytest.approx(x0["score"], rel=1e-12) and x0["rho_min"] is None
    assert sum(str(w).startswith("SM_CROSS_MESH") for w in res["warnings"]) == 1
    rows = _txt(os.path.join(out, "post", "ranking.csv")).splitlines()
    head = rows[0].split(",")
    assert {r.split(",")[head.index("metric")] for r in rows[1:] if r.split(",")[1]} == {"solve"}
    assert "다른 메시 비교" in _txt(os.path.join(out, "report.html"))
    out2, post2, *_ = _study(str(tmp_path / "s"), "step", {"schema": 1, "method": "work"}, n_shapes=2, rank=RANK)
    assert not os.path.exists(os.path.join(out2, "prep", "sm_ref.npz"))
    assert post2["result"]["metric_effective"] == "solve" and post2["result"]["cross_mesh"] is True
