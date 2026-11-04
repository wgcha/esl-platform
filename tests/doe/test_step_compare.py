"""v0.14.0 ④ 형상 직접 비교 코어(계약 esl_step_compare.md V-SC-1·2·3·5·6·8 코어 부분 + 이슈 #53 메싱 기준).

- V-SC-6/8: gmsh 선택 키(ExtendFromBoundary·OCCFix*) — 키 없으면 ③ 옵션 그대로, ④ 프로필이 gmsh 에 그대로, 같은 STEP 2회 바이트 동일,
  작은 구멍(Ø2·Ø6) 메움(이슈 #53 holes table) → 최소 모서리 ≥ 0.6 h, r 4~30 구멍 둘레 분할 max(6, ceil(둘레/h))(둘레 요소 max_length Fail 0).
- V-SC-1(코어)·2: 합성 STEP 3개(평판 / 비드 1 / 비드 2) + 어긋난 형상 1개 → 순위 비드 2 < 비드 1 < 기준, frame 고정(바이트 동일),
  형상별 auto_supports, 셀 매핑 합력·합모멘트 평형, FAILED_SIZE 형상만 제외, 이름·CSV·보고서·메시 산출물, 민감도 생략.
- V-SC-3: 기준 미지정 → 첫 ESL Case 메시 d000(셀 매핑·auto_supports) + COMPARE_REF_CASE_MESH(준비·결과·보고서).
- V-SC-5: 크기 ±5 %(4.9/5.1 %)·원점 0.05 경계·법선 5° 경계, 기준 크기 불일치 → 준비 실패 SIZE_MISMATCH.
- 품질(이슈 #53 criteria): 정사각형 0 Fail, 찌그러진 요소 기준별 Fail, Fail 비율 상한 경고.
gmsh 가 없으면 gmsh 쓰는 시험만 skip."""
import os

import numpy as np
import pytest

import synth_compare as scmp
import synth_doe as sd
from esl.doe import DEFAULTS, opt_settings, settings
from esl.doe import mesh_gmsh as mg
from esl.doe import mesh_quality as mq
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U
from esl.library import mapping as mp
from esl.opt import target as tg
from esl.opt.mesh_check import _edge_lengths

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
PROPS = {"t": 2.0, "E": 205000.0, "nu": 0.3}
H = 5.0                                    # 시험 속도용 프로필 크기(기본 3 mm 는 워커 E2E·설정 시험)
LX, LZ = 200.0, 150.0


def _cfg(**cmp):
    c = {"mesh": {"size_mm": H}, **cmp}
    return {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": c},
            "opt_run": {"solver": {"backend": "superlu"}}}


def _lib(root):
    a = sd.plate(nx=20, ny=15, Lx=LX, Lz=LZ)
    dirs = [sd.save_entry(str(root), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    return a, [{"id": f"E{k}", "dir": d, "label": f"씬 {k}"} for k, d in enumerate(dirs)]


def _run(out, doe, stages=("bd_input", "bd_mesh0", "bd_loads")):
    def spec(stage, **kw):
        return {"stage": stage, "out": str(out), "doe": {**doe, **kw}}
    return {s: stg.run_stage(spec(s), lambda m: None) for s in stages}, spec


# ---------------------------------------------------------------- V-SC-6·8 메시 프로필
def test_gmsh_options_optional_keys_keep_step3():
    m3 = DEFAULTS["mesh"]
    assert mg.gmsh_options(5.0, m3) == {
        "Mesh.MeshSizeMax": 5.0, "Mesh.MeshSizeMin": 1.0, "Mesh.MeshSizeFromCurvature": 12,
        "Mesh.MeshSizeExtendFromBoundary": 1, "Mesh.Algorithm": 8, "Mesh.RecombineAll": 1,
        "Mesh.RecombinationAlgorithm": 1, "Mesh.SubdivisionAlgorithm": 0, "Mesh.ElementOrder": 1, "Mesh.Smoothing": 3}
    assert mg.geometry_options(m3) == {}                                    # ③ 은 선택 키 없음 → 바이트 불변
    prof = sc.compare_profile(settings({"bead_doe": {"enabled": True}}))
    o = mg.gmsh_options(prof["size_mm"], prof)
    assert (o["Mesh.MeshSizeMax"], o["Mesh.MeshSizeMin"], o["Mesh.MeshSizeFromCurvature"],
            o["Mesh.MeshSizeExtendFromBoundary"]) == (3.0, pytest.approx(2.4), 0, 0)
    assert mg.geometry_options(prof) == {k: 1 for k in mg.OCC_FIX_KEYS}
    assert prof["feature_angle"] == 10.0 and "defeature" not in prof
    cc = sc.compare_cfg(settings({"bead_doe": {"enabled": True}}))
    assert cc["mesh"]["defeature"]["min_hole_area_mm2"] == pytest.approx(50.27) and "defeature" not in settings()["mesh"]


@needs_gmsh
def test_profile_deterministic_and_small_holes(tmp_path):
    cfg = sc.compare_cfg(settings({"bead_doe": _cfg()["bead_doe"]}))
    cfg3 = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    src = scmp.plate_step(tmp_path / "b.step", 1, Lx=LX, Lz=LZ)
    m1, meta = mg.run_isolated(src, str(tmp_path / "a"), H, cfg, PROPS)
    mg.run_isolated(src, str(tmp_path / "b"), H, cfg, PROPS)
    assert (tmp_path / "a" / "mesh.npz").read_bytes() == (tmp_path / "b" / "mesh.npz").read_bytes()
    o = meta["options"]
    assert o["Mesh.MeshSizeMax"] == H and o["Mesh.MeshSizeMin"] == pytest.approx(0.8 * H)
    assert o["Mesh.MeshSizeFromCurvature"] == 0 and o["Mesh.MeshSizeExtendFromBoundary"] == 0
    assert all(o[k] == 1 for k in mg.OCC_FIX_KEYS)
    # 이슈 #53 holes table: r < 4(면적 < π·4²) 메움 → 작은 모서리 없음, r 4~30 둘레 분할 = max(6, ceil(둘레/h))
    for d, filled in ((2.0, 1), (6.0, 1)):
        p = scmp.plate_step(tmp_path / f"h{d}.step", Lx=LX, Lz=LZ, hole=(100.0, 75.0, d))
        m, mt = mg.mesh_file(p, 3.0, cfg3, PROPS)
        assert mt["defeature"]["filled"] == filled
        L = _edge_lengths(m["x0"], m["conn"], np.asarray(m["elem_type"]).astype(int))
        assert float(np.min(L)) >= 0.6 * 3.0, float(np.min(L))
    q = settings()["compare"]["quality"]
    for dia, hh in ((24.0, 3.0), (56.0, 3.0), (8.4, 3.0), (8.4, 6.0)):
        p = scmp.plate_step(tmp_path / f"h{dia}_{hh}.step", Lx=LX, Lz=LZ, hole=(100.0, 75.0, dia))
        m, mt = mg.mesh_file(p, hh, cfg3, PROPS)
        assert mt["defeature"]["filled"] == 0 and mt["defeature"]["hole_sized"] == 1
        X = m["x0"]
        r = np.hypot(X[:, 0] - 100.0, X[:, 2] - 75.0)
        n_exp = max(6, int(np.ceil(np.pi * dia / hh)))                     # r 12 → 26, r 28 → 59, r 4.2 → 9(h 3)·6(h 6)
        assert int(np.sum(np.abs(r - dia / 2) < 1e-6)) == n_exp, (dia, hh)
        on = np.abs(r - dia / 2) < 1e-6
        e = m["conn"]
        et = np.asarray(m["elem_type"]).astype(int)
        L = _edge_lengths(X, e, et)
        touch = on[e[:, :3]].sum(axis=1) >= 1
        assert float(np.nanmax(L[touch])) <= max(hh, np.pi * dia / 6) * 1.25, (dia, hh, float(np.nanmax(L[touch])))
        if hh == 3.0:                                                      # 큰 구멍 둘레 요소 max_length Fail 없음(이슈 #53)
            met = mq.element_metrics(X, e, et)
            assert int(np.sum(met["max_length"][touch] > q["max_length"]["fail"])) == 0, dia
    off = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1},
                                                "compare": {"defeature": {"enabled": False}}}}))
    _m, mt = mg.mesh_file(scmp.plate_step(tmp_path / "h2b.step", Lx=LX, Lz=LZ, hole=(100.0, 75.0, 2.0)), 3.0, off, PROPS)
    assert "defeature" not in mt


# ---------------------------------------------------------------- 품질(이슈 #53 criteria)
def test_quality_criteria():
    q = settings()["compare"]["quality"]
    m = sd.plate(nx=10, ny=10, Lx=30.0, Lz=30.0)                           # 3 mm 정사각형
    s = mq.summarize(m, q)
    assert s["fail_elems"] == 0 and s["warn_elems"] == 0 and s["tria_pct"] == 0.0 and not s["over_limit"]
    X = np.array(m["x0"], dtype=float, copy=True)
    c0 = m["conn"][0]
    X[c0[2]] += [1.8, 0.0, 1.8]                                             # 요소 1개 찌그러뜨림(길이·각·야코비안)
    X[c0[3], 1] += 1.5                                                      # 뒤틀림(warpage)
    s2 = mq.summarize({**m, "x0": X}, q)
    assert s2["fail_elems"] >= 1 and s2["fail_by"]["warpage"] >= 1 and s2["fail_by"]["max_length"] >= 1
    assert s2["fail_ratio"] > 0.01 and s2["over_limit"]                      # 100 요소 중 Fail ≥ 1 → 1 % 초과
    mt = sd.plate(nx=10, ny=10, Lx=30.0, Lz=30.0, n_tria_cols=3)
    st = mq.summarize(mt, q)
    assert st["tria_pct"] > 15 and st["tria_level"] == "fail"
    met = mq.element_metrics(m["x0"], m["conn"], m["elem_type"])
    assert np.allclose(met["jacobian"], 1.0) and np.allclose(met["skew"], 0.0, atol=1e-9)
    assert np.allclose(met["min_angle"], 90.0) and np.allclose(met["aspect"], 1.0)


# ---------------------------------------------------------------- V-SC-5 크기·정렬 경계
def _xform(mesh, *, sx=1.0, shift=(0.0, 0.0, 0.0), rot_deg=0.0):
    X = np.array(mesh["x0"], dtype=float, copy=True)
    X[:, 0] *= sx
    c = X.mean(axis=0)
    a = np.radians(rot_deg)
    R = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    X = (X - c) @ R.T + c + np.asarray(shift)
    return {**mesh, "x0": X}


def test_size_align_boundaries(tmp_path):
    a, ents = _lib(tmp_path / "lib")
    from esl.library.entry import load
    E = [load(e["dir"]) for e in ents]
    ref = sd.plate(nx=40, ny=30, Lx=LX, Lz=LZ)
    t, _ = sc.template_base(ref, E, opt_settings(None)["size"], inch=75)
    cc = settings()["compare"]
    size = opt_settings(None)["size"]

    def chk(m):
        return sc.shape_check(m, t.frame, E, size, cc, inch=75)
    assert chk(ref)["ok"]
    assert chk(_xform(ref, sx=1.049))["ok"]
    r = chk(_xform(ref, sx=1.051))
    assert not r["ok"] and r["code"] == "SHAPE_SIZE_MISMATCH"
    assert chk(_xform(ref, shift=(0.049 * LX, 0.0, 0.0)))["ok"]
    r = chk(_xform(ref, shift=(0.051 * LX, 0.0, 0.0)))
    assert r["code"] == "SHAPE_MISALIGNED" and r["align"]["dxi"] == pytest.approx(0.051, abs=1e-6)
    assert chk(_xform(ref, shift=(0.0, 0.0, -0.049 * LZ)))["ok"]
    assert chk(_xform(ref, shift=(0.0, 0.0, 0.051 * LZ)))["code"] == "SHAPE_MISALIGNED"
    r = chk(_xform(ref, rot_deg=4.9))
    assert r["ok"] and r["align"]["angle_deg"] == pytest.approx(4.9, abs=1e-6)
    assert chk(_xform(ref, rot_deg=5.1))["code"] == "SHAPE_MISALIGNED"
    with pytest.raises(EslError) as ei:                                     # 기준 vs ESL 크기 불일치 → 준비 실패
        sc.template_base(_xform(ref, sx=1.06), E, size, inch=75)
    assert ei.value.code == "SIZE_MISMATCH"


# ---------------------------------------------------------------- V-SC-1(코어)·2 파이프라인
@needs_gmsh
def test_compare_pipeline_frame_fixed(tmp_path):
    a, ents = _lib(tmp_path / "lib")
    up = tmp_path / "up"
    paths = [scmp.plate_step(up / f"u{k}" / f"p{k}.step", k, Lx=LX, Lz=LZ, depth=5.0) for k in range(3)]
    paths.append(scmp.plate_step(up / "u3" / "shift.step", 0, Lx=LX, Lz=LZ, shift=(30.0, 0.0, 0.0)))   # Δξ 0.15
    stamp = sc.tree_stamp(str(up))
    names = ["기준 평판", "비드 1", "비드 2", "어긋난 판"]
    shapes = [{"id": f"d{k:03d}", "name": names[k], "file_name": os.path.basename(p), "path": p, "reference": k == 0,
               "sha256": U.sha256_file(p)} for k, p in enumerate(paths)]
    doe = {"id": "C1", "scenario": "compare", "title": "④ 시험", "cfg": _cfg(), "entries": ents, "shapes": shapes,
           "reference_source": "step", "inch": 75, "props": PROPS}
    out = tmp_path / "_doe" / "C1"
    r, spec = _run(out, doe)
    assert r["bd_input"]["reference_source"] == "step" and (out / "input" / "shapes" / "d002.step").is_file()
    cmp = U.read_json(str(out / "prep" / "compare.json"))
    st = {x["id"]: x for x in cmp["shapes"]}
    assert st["d003"]["status"] == "FAILED_SIZE" and st["d003"]["code"] == "SHAPE_MISALIGNED"
    assert all(st[d]["status"] == "READY" and st[d]["quality"]["n_elems"] == st[d]["n_elems"] for d in ("d000", "d001", "d002"))
    assert cmp["profile"]["size_mm"] == H and cmp["profile"]["extend_from_boundary"] == 0
    base = U.read_json(str(out / "prep" / "base.json"))
    for did in ("d000", "d001", "d002"):
        assert stg.run_stage(spec("bd_eval", design=did), lambda m: None)["status"] == "OK"
    # V-SC-2 frame 고정·형상별 지지·셀 매핑 평형
    c = stg.Ctx(spec("bd_eval"))
    t, _ = sc.load_base(c.p("prep"))
    from esl.library.entry import load
    E = [load(e["dir"]) for e in ents]
    for did in ("d000", "d001", "d002"):
        mesh, sup, loads, _info = stg._cmp_design_mesh(c, t, did)
        dt = sc.compare_target(mesh, t.frame)
        assert U.jsonable(dt.frame) == base["frame"]                       # 바이트 동일(같은 dict)
        assert sup == tg.auto_supports(mesh) and len(sup) == 3
        for (eid, F), e in zip(loads, E):
            tF, tM = mp.resultants(mesh["x0"], F, mesh["x0"].mean(axis=0))
            s = np.abs(F).sum()
            assert np.linalg.norm(tF) <= 1e-9 * s and np.linalg.norm(tM) <= 1e-9 * s * 400
            f2, info = mp.to_target(e.summary_for_mapping(), mesh["x0"], t.frame, {"equilibrate": False})
            assert info["conservation_rel_max"] < 1e-9
    res = stg.run_stage(spec("bd_post"), lambda m: None)["result"]
    rk = [x["id"] for x in res["ranking"]]
    assert rk == ["d002", "d001"], [(x["id"], x["score"]) for x in res["ranking"]]
    s1, s2 = (next(x for x in res["ranking"] if x["id"] == d)["score"] for d in ("d001", "d002"))
    assert s2 < s1 < 1.0
    assert res["ranking"][0]["shape"] == {"name": "비드 2", "file_name": "p2.step", "reference": False}
    assert res["baseline"]["shape"]["name"] == "기준 평판" and res["ranking"][0]["values"] == {}
    assert res["sensitivity"] is None and res["sensitivity_reason"] == "COMPARE_NO_PARAMS" and res["noise_floor"] is None
    assert res["n_failed"]["size"] == 1 and res["scenario"] == "compare" and res["reference_source"] == "step"
    assert all(x.get("worst_ratio") is not None and "pareto" in x for x in res["ranking"])
    csv = (out / "post" / "ranking.csv").read_text(encoding="utf-8").splitlines()
    assert csv[0].startswith("id,rank,status,name,file_name,score") and any("비드 2" in ln for ln in csv)
    assert any(ln.startswith("d003,,FAILED_SIZE,어긋난 판") for ln in csv)
    des = U.read_json(str(out / "post" / "designs.json"))["designs"]
    assert next(d for d in des if d["id"] == "d003")["shape"]["name"] == "어긋난 판"
    for did in ("d000", "d001", "d002"):                                    # SC-D-11 전 OK 형상 메시 산출물
        assert (out / "best" / did / "ch_r.rad").is_file() and (out / "best" / did / "ch_r.fem").is_file()
    assert not (out / "best" / "d000" / "values.json").exists()
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "④ 형상 직접 비교" in html and "비드 2" in html and "어긋난 판" in html and "defeature" in html
    assert U.read_json(str(out / "post" / "per_esl.json"))["names"]["d002"] == "비드 2"
    assert set(res["view3d"]) >= {"d000", "d002"}
    assert sc.tree_stamp(str(up)) == stamp                                   # 업로드 폴더 불변
    # 이어하기: 같은 입력이면 재사용
    assert stg.run_stage(spec("bd_eval", design="d001"), lambda m: None)["reused"] is True


# ---------------------------------------------------------------- V-SC-3 기준 미지정
@needs_gmsh
def test_case_reference(tmp_path):
    a, ents = _lib(tmp_path / "lib")
    case = tmp_path / "case"
    case.mkdir()
    sd.write_mesh_rad(str(case / "model_0000.rad"), a)
    up = tmp_path / "up"
    paths = [scmp.plate_step(up / f"u{k}" / f"p{k}.step", k, Lx=LX, Lz=LZ, depth=5.0) for k in (1, 2)]
    shapes = [{"id": f"d{k + 1:03d}", "name": f"비드 {k + 1}", "file_name": os.path.basename(p), "path": p,
               "reference": False} for k, p in enumerate(paths)]
    doe = {"id": "C2", "scenario": "compare", "cfg": _cfg(), "entries": ents, "shapes": shapes,
           "reference_source": "case", "inch": 75, "props": PROPS,
           "base": {"entry_id": "E0", "case_id": "c1", "rad_path": str(case / "model_0000.rad"),
                    "part_title": sd.PART_TITLE, "case_dir": str(case)}}
    out = tmp_path / "_doe" / "C2"
    stamp = sc.tree_stamp(str(case))
    r, spec = _run(out, doe)
    assert any(w.startswith("COMPARE_REF_CASE_MESH") for w in r["bd_input"]["warnings"])
    shp = U.read_json(str(out / "prep" / "shapes.json"))
    assert shp["reference_source"] == "case" and shp["shapes"][0]["id"] == "d000" and shp["shapes"][0]["source"] == "case"
    base = U.read_json(str(out / "prep" / "base.json"))
    assert base["target"] == "S2" and base["n_nodes"] == a["node_id"].size          # 셀 매핑 대상(직접 노드 아님)
    m0 = mg.load_mesh(str(out / "prep" / "shapes" / "d000" / "mesh"))
    assert np.allclose(m0["thickness"], PROPS["t"])                                  # 모든 형상 같은 물성
    inp = U.read_json(str(out / "prep" / "input.json"))
    assert inp["loads"]["method"] == "cell_mapping"
    c = stg.Ctx(spec("bd_eval"))
    t, _ = sc.load_base(c.p("prep"))
    _mesh, sup, _loads, _ = stg._cmp_design_mesh(c, t, "d000")
    assert sup == tg.auto_supports(t.mesh)                                           # ESL 3-2-1 아님
    for did in ("d000", "d001", "d002"):
        assert stg.run_stage(spec("bd_eval", design=did), lambda m: None)["status"] == "OK"
    res = stg.run_stage(spec("bd_post"), lambda m: None)["result"]
    assert res["reference_source"] == "case" and any(str(w).startswith("COMPARE_REF_CASE_MESH") for w in res["warnings"])
    assert res["baseline"]["shape"] == {"name": "Case 메시", "file_name": None, "reference": True, "source": "case"}
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "COMPARE_REF_CASE_MESH" in html and "첫 ESL Case 메시" in html
    assert sc.tree_stamp(str(case)) == stamp


@needs_gmsh
def test_reference_mesh_failure_and_size(tmp_path):
    a, ents = _lib(tmp_path / "lib")
    up = tmp_path / "up"
    big = scmp.plate_step(up / "a" / "big.step", 0, Lx=LX * 1.3, Lz=LZ)
    ok = scmp.plate_step(up / "b" / "ok.step", 1, Lx=LX, Lz=LZ)
    junk = up / "c" / "junk.step"
    junk.parent.mkdir(parents=True)
    junk.write_text("ISO-10303-21;\nnot really\n")
    mk = lambda p, k, ref: {"id": f"d{k:03d}", "name": f"s{k}", "file_name": os.path.basename(str(p)), "path": str(p),  # noqa: E731
                            "reference": ref}
    doe = {"id": "C3", "scenario": "compare", "cfg": _cfg(), "entries": ents, "inch": 75, "props": PROPS,
           "reference_source": "step", "shapes": [mk(big, 0, True), mk(ok, 1, False)]}
    with pytest.raises(EslError) as ei:
        _run(tmp_path / "_doe" / "C3", doe)
    assert ei.value.code == "SIZE_MISMATCH"
    doe2 = {**doe, "id": "C4", "shapes": [mk(junk, 0, True), mk(ok, 1, False)]}
    with pytest.raises(EslError) as ei:
        _run(tmp_path / "_doe" / "C4", doe2)
    assert ei.value.code == "MESH_FAILED"
    doe3 = {**doe, "id": "C5", "shapes": [mk(ok, 0, True), mk(junk, 1, False)]}            # 그 밖 형상 실패 → 진행
    _run(tmp_path / "_doe" / "C5", doe3)
    st = {x["id"]: x for x in U.read_json(str(tmp_path / "_doe" / "C5" / "prep" / "compare.json"))["shapes"]}
    assert st["d000"]["status"] == "READY" and st["d001"]["status"] == "FAILED_MESH" and st["d001"]["code"] == "MESH_FAILED"


# ---------------------------------------------------------------- v0.14.0 해 잔차 판정(후방 오차, decisions D-0.14-RESID)
@needs_gmsh
def test_synthetic_plate_3mm_solves(tmp_path):
    """합성 평판 400×300 · 3 mm 메시 · 3점 auto_supports: 얇은 판(t 0.8)은 조건수가 커 ‖Ku−F‖/‖F‖ 가 옛 허용 1e-8 을 넘지만
    (정상 해) 노름 후방 오차 η 는 기계 정밀도 수준 → SOLVER_SINGULAR 가 아니다. t 2.0 은 옛 기준으로도 통과(결과 불변 경로)."""
    from esl.doe import evaluate as ev
    from esl.mech import shell as _shell
    from esl.mech.shell import ShellModel

    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    p = scmp.plate_step(tmp_path / "flat.step", 0, Lx=400.0, Lz=300.0)
    m, mt = mg.mesh_file(p, 3.0, cfg, PROPS)
    assert mt["options"]["Mesh.MeshSizeMax"] == 3.0 and m["conn"].shape[0] > 12000
    spc = ev.spc_of(m, tg.auto_supports(m))
    X = m["x0"]
    F = np.zeros_like(X)
    F[:, 1] = np.sin(np.pi * (X[:, 0] - X[:, 0].min()) / 400.0) * 10.0
    F[:, 2] = np.cos(np.pi * (X[:, 2] - X[:, 2].min()) / 300.0) * 3.0
    F -= F.mean(axis=0)
    rr = {}
    for t in (0.8, 2.0):
        sm = ShellModel(X, m["conn"], m["elem_type"], t, 205000.0, 0.3, backend="superlu")
        u, _R = sm.factorize(spc).solve(F)
        assert np.all(np.isfinite(u))
        rr[t] = sm.stats["solve_resid_rel"]
        assert sm.stats["solve_backward_err"] < 1e-14, sm.stats
    assert rr[0.8] > _shell.RESID_REL_TOL, rr                     # 옛 판정이면 SOLVER_SINGULAR 였던 경우
    assert rr[2.0] <= _shell.RESID_REL_TOL, rr
    # 허용치를 기계 정밀도 아래로 조이면 같은 해도 SOLVER_SINGULAR(판정이 실제로 η 를 본다)
    sm = ShellModel(X, m["conn"], m["elem_type"], 0.8, 205000.0, 0.3, backend="superlu", resid_backward_tol=1e-30)
    with pytest.raises(EslError) as ei:
        sm.factorize(spc).solve(F)
    assert ei.value.code == "SOLVER_SINGULAR" and "후방 오차" in ei.value.message


# ---------------------------------------------------------------- v0.15.1 Sphere 면 형상 폴백(이슈 #53) — 준비 기록·보고서 표
@needs_gmsh
def test_compare_sphere_fallback_recorded(tmp_path):
    _a, ents = _lib(tmp_path / "lib")
    up = tmp_path / "up"
    paths = [scmp.dimple_plate_step(up / "u0" / "flat.step", [], Lx=LX, Lz=LZ),
             scmp.dimple_plate_step(up / "u1" / "dimple.step", [(100.0, 75.0, 20.0, 5.0)], Lx=LX, Lz=LZ)]
    stamp = sc.tree_stamp(str(up))
    shapes = [{"id": f"d{k:03d}", "name": n, "file_name": os.path.basename(p), "path": p, "reference": k == 0,
               "sha256": U.sha256_file(p)} for k, (n, p) in enumerate(zip(("평판", "딤플"), paths))]
    doe = {"id": "C2", "scenario": "compare", "title": "④ 구면", "cfg": _cfg(), "entries": ents, "shapes": shapes,
           "reference_source": "step", "inch": 75, "props": PROPS}
    out = tmp_path / "_doe" / "C2"
    _run(out, doe, stages=("bd_input", "bd_mesh0"))
    cmp = U.read_json(str(out / "prep" / "compare.json"))
    d1 = next(x for x in cmp["shapes"] if x["id"] == "d001")
    d0 = next(x for x in cmp["shapes"] if x["id"] == "d000")
    assert "mesh_fallback" not in d0 and "fallback_faces" not in d0["quality"]       # 정상 형상은 기록 없음
    assert d1["status"] == "READY" and d1["quality"]["fallback_faces"] == 1
    assert d1["quality"]["fallback_stages"] == ["OCC 정리 끔(그 면만)"]
    f = d1["mesh_fallback"]["faces"][0]
    assert f["stage"] == "nofix" and f["scope"] == "face" and f["type"] == "Sphere" and f["deviation_mm"] == 0.0
    assert any(w.startswith("MESH_FACE_FALLBACK: d001") and "OCC 정리 끔(그 면만)" in w for w in cmp["warnings"])
    assert sc.tree_stamp(str(up)) == stamp                                   # 업로드 폴더(원본 STEP) 불변
    from esl.doe import report_doe as rd
    html = rd.render_compare({"study": {"id": "C2"}, "shapes": cmp["shapes"], "profile": cmp["profile"]})
    assert "폴백 면 1개(id " in html and "OCC 정리 끔(그 면만)" in html
