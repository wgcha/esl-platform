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
    assert res["ranking"][0]["shape"] == {"name": "비드 2", "file_name": "p2.step", "reference": False,
                                          "source": "step", "mesh_method": "cad"}      # v0.16.0 §3 새 키(source·mesh_method)
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
    assert res["baseline"]["shape"] == {"name": "Case 메시", "file_name": None, "reference": True, "source": "case",
                                        "mesh_method": "mesh_input"}        # v0.16.0 C2-D-10: Case 기준 = mesh_input(source 로 구분)
    # C2-D-1(v0.16.0 Verifier Med 1): {cad, Case 메시} 만이면 COMPARE_REF_CASE_MESH 와 겹치므로 MIXED 없음
    assert not any(str(w).startswith("COMPARE_MESH_METHOD_MIXED") for w in res["warnings"])
    assert not any(str(w).startswith("COMPARE_MESH_METHOD_MIXED") for w in r["bd_mesh0"]["warnings"])
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


# ---------------------------------------------------------------- v0.16.0 메시 방식 사다리(esl_compare_mesh_options.md V-C2-3·13·15·16)
def _two(tmp_path, sid: str, **doe_kw):
    """기준 평판 d000 + 비드 1 d001 ④ doe dict(STEP 2개)."""
    _a, ents = _lib(tmp_path / "lib")
    up = tmp_path / "up"
    paths = [scmp.plate_step(up / f"u{k}" / f"p{k}.step", k, Lx=LX, Lz=LZ, depth=5.0) for k in range(2)]
    shapes = [{"id": f"d{k:03d}", "name": n, "file_name": os.path.basename(p), "path": p, "reference": k == 0,
               "sha256": U.sha256_file(p)} for k, (n, p) in enumerate(zip(("평판", "비드"), paths))]
    doe = {"id": sid, "scenario": "compare", "title": "④ 사다리", "cfg": _cfg(), "entries": ents, "shapes": shapes,
           "reference_source": "step", "inch": 75, "props": PROPS, **doe_kw}
    return doe, up


def _inject_cad_fail(monkeypatch, ids, code="MESH_FAILED", err=None):
    """cad 시도(stages._cmp_mesh_one)만 실패 주입 — 사다리 다음 단계는 실제 gmsh(시험용 monkeypatch, 설정 키 아님)."""
    real = stg._cmp_mesh_one

    def fake(c, row, h, ccfg, props, *, fail_info=False, timeout_s=None):
        if row["id"] in ids:
            d = stg._cmp_mesh_dir(c, row["id"])
            c.writer.makedirs(d)
            if err is not None:
                U.write_json(os.path.join(d, mg.MESH_ERROR), err)
            return {"id": row["id"], "status": "FAILED_MESH", "code": code, "message": "주입된 CAD 실패"}
        return real(c, row, h, ccfg, props, fail_info=fail_info, timeout_s=timeout_s)
    monkeypatch.setattr(stg, "_cmp_mesh_one", fake)


def _shape(out, did):
    return next(x for x in U.read_json(str(out / "prep" / "compare.json"))["shapes"] if x["id"] == did)


@needs_gmsh
def test_mesh_mode_auto_cad_ok_bytes_equal_cad(tmp_path):
    """V-C2-3·8·15: cad 가 성공하는 auto = mode cad 와 mesh.npz·loads.npz·base_mesh.npz 바이트 동일, 사다리 미진입(시도 폴더·
    size_fields·refine 없음), input_sha256 은 cad(=v0.15.x)만 불변."""
    doe, _up = _two(tmp_path, "A0")
    outs = {}
    for mode in ("cad", "auto"):
        out = tmp_path / "_doe" / mode
        kw = {} if mode == "cad" else {"mesh_mode": "auto"}
        r, spec = _run(out, {**doe, **kw})
        outs[mode] = (out, spec)
        for did in ("d000", "d001"):
            s = _shape(out, did)
            assert s["status"] == "READY" and s["mesh_method"] == "cad" and "refine" not in s and "cad_error" not in s
            md = out / "prep" / "shapes" / did / "mesh"
            assert not [p for p in os.listdir(md) if p.startswith("try_")]
            assert "size_fields" not in U.read_json(str(md / "mesh.json"))
    (oc, sc_), (oa, sa) = outs["cad"], outs["auto"]
    for rel in ("prep/shapes/d000/mesh/mesh.npz", "prep/shapes/d001/mesh/mesh.npz", "prep/loads.npz", "prep/base_mesh.npz"):
        assert (oc / rel).read_bytes() == (oa / rel).read_bytes(), rel
    cmp_c = U.read_json(str(oc / "prep" / "compare.json"))
    assert "mesh_mode" not in cmp_c and U.read_json(str(oa / "prep" / "compare.json"))["mesh_mode"] == "auto"
    # 이어하기 해시: cad 는 v0.15.x 와 같은 키 구성(mesh_mode 없음 = cad), auto 는 사다리 설정이 들어가 다름
    h_cad = stg.design_sha(stg.Ctx(sc_("bd_eval", design="d001")), "d001")
    h_auto = stg.design_sha(stg.Ctx(sa("bd_eval", design="d001")), "d001")
    assert h_cad != h_auto
    assert stg.design_sha(stg.Ctx(sc_("bd_eval", design="d001", mesh_mode="cad")), "d001") == h_cad


@needs_gmsh
def test_mesh_mode_auto_fallback_and_too_large(tmp_path, monkeypatch):
    """V-C2-3: cad MESH_FAILED 주입 → 재메시 폴백(method fallback·REMESH_USED·cad_error·fidelity, 성공본 mesh/ 로 교체, 시도 폴더
    삭제). cad MESH_TOO_LARGE 주입 → 폴백 없음."""
    doe, up = _two(tmp_path, "A1", mesh_mode="auto", mesh_ladder=["cad", "remesh"])
    stamp = sc.tree_stamp(str(up))
    _inject_cad_fail(monkeypatch, {"d001"})
    out = tmp_path / "_doe" / "A1"
    r, spec = _run(out, doe)
    s = _shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "fallback", s
    assert s["cad_error"] == {"code": "MESH_FAILED", "message": "주입된 CAD 실패"}
    assert s["fidelity"]["hausdorff_mm"] >= 0 and "area_ratio" in s["fidelity"]
    assert [a["stage"] for a in s["attempts"]] == ["cad", "remesh"] and s["attempts"][-1]["status"] == "READY"
    md = out / "prep" / "shapes" / "d001" / "mesh"
    assert (md / "mesh.npz").is_file() and not (md / "mesh_error.json").exists()
    assert not [p for p in os.listdir(md) if p.startswith("try_")]
    mj = U.read_json(str(md / "mesh.json"))
    assert mj["method"] == "remesh" and mj["mesh_method"] == "fallback"
    ws = r["bd_mesh0"]["warnings"]
    assert any(w.startswith("REMESH_USED") and "주입된 CAD 실패" in w and "d001" in w for w in ws)
    assert any(w.startswith("COMPARE_MESH_METHOD_MIXED") for w in ws)
    assert _shape(out, "d000")["mesh_method"] == "cad"
    # 결과 shape·ranking.csv·보고서
    for did in ("d000", "d001"):
        assert stg.run_stage(spec("bd_eval", design=did), lambda m: None)["status"] == "OK"
    res = stg.run_stage(spec("bd_post"), lambda m: None)["result"]
    x = res["ranking"][0]
    assert x["shape"]["mesh_method"] == "fallback" and x["shape"]["source"] == "step" and "fidelity" in x["shape"]
    assert any(str(w).startswith("REMESH_USED") for w in res["warnings"])
    csv = (out / "post" / "ranking.csv").read_text(encoding="utf-8").splitlines()
    assert csv[0].endswith(",source,mesh_method,hausdorff_mm,refine_h_mm,elem_ratio_ref")
    assert any(ln.startswith("d001,1,OK") and ",step,fallback," in ln for ln in csv)
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "재메시(폴백)" in html and "REMESH_USED" in html and "CAD 면 구조를 버린 근사" in html
    assert sc.tree_stamp(str(up)) == stamp
    # MESH_TOO_LARGE(사용자 상한) → 폴백 없음
    _inject_cad_fail(monkeypatch, {"d001"}, code="MESH_TOO_LARGE")
    out2 = tmp_path / "_doe" / "A2"
    _run(out2, {**doe, "id": "A2"}, stages=("bd_input", "bd_mesh0"))
    s2 = _shape(out2, "d001")
    assert s2["status"] == "FAILED_MESH" and s2["code"] == "MESH_TOO_LARGE" and "attempts" not in s2


def _face_key(path):
    """시험용: STEP 을 ④ 가져오기 옵션으로 읽어 가장 큰 면의 bbox 키·넓이와 전체 넓이."""
    import gmsh
    cfg = sc.compare_cfg(settings({"bead_doe": _cfg()["bead_doe"]}))
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", int(cfg["mesh"].get("occ_sew_faces", 0)))
        for k, v in mg.geometry_options(cfg["mesh"]).items():
            gmsh.option.setNumber(k, v)
        gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        ar = {t: gmsh.model.occ.getMass(2, t) for _d, t in gmsh.model.getEntities(2)}
        big = max(ar, key=lambda t: (ar[t], -t))
        small = min(ar, key=lambda t: (ar[t], t))
        return list(mg._bbox_key(gmsh, 2, small)), float(ar[small]), float(sum(ar.values())), big
    finally:
        gmsh.finalize()


@needs_gmsh
def test_mesh_refine_local_then_global(tmp_path, monkeypatch):
    """V-C2-13(워커 사다리): 실패 면 기록이 있으면 refine_local ×0.75 에서 성공(method refine·kind local·faces·elem_ratio_ref·
    MESH_REFINED). 면 기록이 없으면 REFINE_LOCAL_NO_FACE 후 refine_global ×0.8 성공. 국부 요소 수 < 전역."""
    doe, up = _two(tmp_path, "R1", mesh_mode="auto")
    key, a_loc, A, _big = _face_key(doe["shapes"][1]["path"])
    err = {"code": "FAILED_MESH", "message": "x", "face": {"id": 7, "type": "Plane", "center": [0, 0, 0], "key": key},
           "geom": {"area_mm2": A, "n_faces": 9, "local_area_mm2": a_loc * 3, "local_faces": 3}}
    _inject_cad_fail(monkeypatch, {"d001"}, err=err)
    out = tmp_path / "_doe" / "R1"
    r, _spec = _run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = _shape(out, "d001")
    rf = s["refine"]
    assert s["status"] == "READY" and s["mesh_method"] == "refine" and rf["kind"] == "local", s
    assert rf["factor"] == 0.75 and rf["h_mm"] == pytest.approx(0.75 * H) and rf["base_h_mm"] == H
    assert rf["faces"] and all(isinstance(f["bbox_key"], str) and f["ring"] in (0, 1) for f in rf["faces"])
    assert rf["elem_ratio_ref"] == pytest.approx(s["n_elems"] / _shape(out, "d000")["n_elems"], abs=1e-4)
    assert rf["n_est"] and rf["elem_ratio_h"] and [a["stage"] for a in rf["attempts"]] == ["cad", "refine_local"]
    mj = U.read_json(str(out / "prep" / "shapes" / "d001" / "mesh" / "mesh.json"))
    assert mj["refine"]["elem_ratio_ref"] == rf["elem_ratio_ref"] and mj["size_fields"]["entries"][0]["faces"]
    assert any(w.startswith("MESH_REFINED") and "국부 세분화" in w and f"h {0.75 * H:g} mm" in w for w in r["bd_mesh0"]["warnings"])
    n_local = s["n_elems"]
    # 면 기록 없음 → 국부 건너뜀(info) → 전역 ×0.8
    _inject_cad_fail(monkeypatch, {"d001"}, err=None)
    out2 = tmp_path / "_doe" / "R2"
    r2, _ = _run(out2, {**doe, "id": "R2"}, stages=("bd_input", "bd_mesh0"))
    s2 = _shape(out2, "d001")
    assert s2["mesh_method"] == "refine" and s2["refine"]["kind"] == "global" and s2["refine"]["h_mm"] == pytest.approx(0.8 * H)
    assert [a["stage"] for a in s2["attempts"]] == ["cad", "refine_local", "refine_global"]
    assert s2["attempts"][1]["skipped"] and s2["attempts"][1]["reason"] == "no_face"
    assert any(i.startswith("REFINE_LOCAL_NO_FACE") for i in r2["bd_mesh0"]["info"])
    assert n_local < s2["n_elems"]
    # 상한(V-C2-14): refine.max_elems 를 아주 작게 → 세분화 모두 건너뜀(REFINE_SKIPPED_LIMIT elems) → remesh
    cfg3 = _cfg()
    cfg3["bead_doe"]["compare"]["refine"] = {"max_elems": 300000}
    cfg3["bead_doe"]["mesh"]["max_elems"] = 300000
    _inject_cad_fail(monkeypatch, {"d001"}, err={**err, "geom": {**err["geom"], "area_mm2": A * 1e4}})
    out3 = tmp_path / "_doe" / "R3"
    r3, _ = _run(out3, {**doe, "id": "R3", "cfg": cfg3}, stages=("bd_input", "bd_mesh0"))
    s3 = _shape(out3, "d001")
    assert s3["mesh_method"] == "fallback", s3["attempts"]
    assert {a["reason"] for a in s3["attempts"] if a.get("skipped")} == {"elems", "not_compound"}   # v0.16.1 defeature 2번째
    assert any(i.startswith("REFINE_SKIPPED_LIMIT") and "elems" in i for i in r3["bd_mesh0"]["info"])


def _fake_iso(monkeypatch, did, *, hang=False, other_timeout=None):
    """시험용: 형상 did(시도 폴더 prep/shapes/<did>/mesh…) 의 run_isolated 를 모두 실패로 바꿈(hang = 제한 시간만큼 멈춘 뒤 시간 초과, 아니면 즉시 크래시).
    다른 형상은 실제 gmsh(other_timeout 이 있으면 그 제한 시간으로). 반환 = 호출 기록 [{kind, timeout, t0, t1}]."""
    import time
    real = mg.run_isolated
    calls: list[dict] = []

    def fake(src, out_dir, h, cfg, props, *, timeout_s=None, kind="cad", **kw):
        if f"{os.sep}shapes{os.sep}{did}{os.sep}" not in os.path.abspath(str(out_dir)) + os.sep:
            return real(src, out_dir, h, cfg, props, timeout_s=other_timeout or timeout_s, kind=kind, **kw)
        to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
        t0 = time.monotonic()
        if hang:
            time.sleep(to)
        calls.append({"kind": kind, "timeout": to, "t0": t0, "t1": time.monotonic()})
        raise EslError("REMESH_FAILED" if kind == "remesh" else "FAILED_MESH",
                       f"{kind} 주입 {'시간 초과' if hang else '크래시'}")
    monkeypatch.setattr(mg, "run_isolated", fake)
    return calls


@needs_gmsh
def test_ladder_time_budget_without_area(tmp_path, monkeypatch):
    """Verifier Med 3: cad 가 시간 초과(넓이 기록 없음 → n_est 없음)여도 누적 예산 refine.total_timeout_s 로 판정. 시도마다
    제한 시간 = min(mesh.timeout_s, 남은 예산), 예산이 다 되면 남은 세분화·remesh 는 REFINE_SKIPPED_LIMIT(time). 총 시간 ≤ 예산."""
    budget, to = 1.0, 0.4
    cfg = _cfg()
    cfg["bead_doe"]["mesh"]["timeout_s"] = to
    cfg["bead_doe"]["compare"]["refine"] = {"total_timeout_s": budget}
    doe, _up = _two(tmp_path, "T1", mesh_mode="auto", cfg=cfg)
    calls = _fake_iso(monkeypatch, "d001", hang=True, other_timeout=600)
    out = tmp_path / "_doe" / "T1"
    r, _ = _run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = _shape(out, "d001")
    assert s["status"] == "FAILED_MESH" and s["cad_error"]["message"] == "cad 주입 시간 초과", s
    assert [c["kind"] for c in calls] == ["cad", "cad", "cad"]          # cad + 전역 ×0.8 + ×0.667(남은 0.2 s)
    assert calls[0]["timeout"] == pytest.approx(to) and calls[1]["timeout"] == pytest.approx(to)
    assert calls[2]["timeout"] < to                                      # 남은 예산으로 줄임
    assert sum(c["timeout"] for c in calls) <= budget + 1e-6
    assert calls[-1]["t1"] - calls[0]["t0"] <= budget + 0.5               # 총 시간 ≤ 예산(+ 프로세스 밖 여유)
    att = s["attempts"]
    assert [a["stage"] for a in att] == ["cad", "refine_local", "refine_global", "refine_global", "defeature", "defeature",
                                         "remesh"]                     # v0.16.1 defeature(SR-D-16): 예산 소진 → 건너뜀
    assert att[1]["reason"] == "no_face" and att[-1]["skipped"] and att[-1]["reason"] == "time"
    assert [(a["skipped"], a["reason"]) for a in att[4:6]] == [(True, "time"), (True, "not_compound")]
    assert any(i.startswith("REFINE_SKIPPED_LIMIT") and "remesh" in i and "time" in i for i in r["bd_mesh0"].get("info") or [])
    # check_limits 단위: n_est 없어도 누적 시간이 예산 이상이면 time
    from esl.doe import mesh_refine as mr
    c2 = {"compare": {"refine": {"total_timeout_s": 10}}}
    assert mr.check_limits({"n_est": None}, c2, None, 10.0) == "time"
    assert mr.check_limits({"n_est": None}, c2, None, 9.0) is None
    assert mr.attempt_timeout(1800, c2, 7.5) == pytest.approx(2.5) and mr.attempt_timeout(1, c2, 0) == 1.0


@needs_gmsh
def test_ladder_all_fail_reference_message_and_tries(tmp_path, monkeypatch):
    """Verifier Med 2·Low: 기준 d000 이 사다리 전부 실패 → 작업 실패 메시지에 CAD 원 오류와 마지막 오류. 시도 폴더는 마지막
    것만 남음(keep_tries false), keep_tries true 면 모두 남음."""
    doe, _up = _two(tmp_path, "F1", mesh_mode="auto")
    _fake_iso(monkeypatch, "d000")
    with pytest.raises(EslError) as ei:
        _run(tmp_path / "_doe" / "F1", doe, stages=("bd_input", "bd_mesh0"))
    assert ei.value.code == "REMESH_FAILED"
    assert ei.value.message == "기준 형상 메시 실패: CAD 메시 실패: cad 주입 크래시 → 세분화·형상 단순화·재메시도 실패: remesh 주입 크래시"
    md = tmp_path / "_doe" / "F1" / "prep" / "shapes" / "d000" / "mesh"
    assert sorted(p for p in os.listdir(md) if p.startswith("try_")) == ["try_4"]      # 전역 ×0.8·×0.667·defeature·remesh 중 마지막
    cfg = _cfg()
    cfg["bead_doe"]["compare"]["mesh"]["keep_tries"] = True
    with pytest.raises(EslError):
        _run(tmp_path / "_doe" / "F2", {**doe, "id": "F2", "cfg": cfg}, stages=("bd_input", "bd_mesh0"))
    md2 = tmp_path / "_doe" / "F2" / "prep" / "shapes" / "d000" / "mesh"
    assert sorted(p for p in os.listdir(md2) if p.startswith("try_")) == ["try_1", "try_2", "try_3", "try_4"]
    # 문구 함수: cad_error 없으면 원 message, 모두 건너뛰면 사유
    assert stg._ladder_fail_text({"message": "m"}) == "m"
    assert stg._ladder_fail_text({"message": "m", "cad_error": {"code": "MESH_FAILED", "message": "c"},
                                  "attempts": [{"stage": "remesh", "skipped": True, "reason": "time"}]}) == \
        "CAD 메시 실패: c → 세분화·재메시는 건너뜀(time)"


@needs_gmsh
def test_refine_convergence_check(tmp_path, monkeypatch):
    """V-C2-16: 세분화 형상(전역 h_r) → BD_POST 가 기준 d000 을 h_r 로 다시 메시·해석(run/designs/d000_h<h>/), ESL별 δ 기록,
    tol 경계에서 MESH_REFINE_BIAS, same_h_baseline 개선율, 캐시 재사용, Case 기준이면 생략 info."""
    doe, _up = _two(tmp_path, "V1", mesh_mode="auto", mesh_ladder=["cad", "refine_global"])
    _inject_cad_fail(monkeypatch, {"d001"})
    out = tmp_path / "_doe" / "V1"
    _r, spec = _run(out, doe)
    assert _shape(out, "d001")["mesh_method"] == "refine"
    hr = 0.8 * H
    for did in ("d000", "d001"):
        assert stg.run_stage(spec("bd_eval", design=did), lambda m: None)["status"] == "OK"
    logs: list[str] = []
    ret = stg.run_stage(spec("bd_post"), logs.append)
    res = ret["result"]
    b = res["refine_bias"]["d001"]
    assert b["h_mm"] == pytest.approx(hr) and len(b["per_esl"]) == 2 and b["delta_max"] >= 0
    assert all(p["delta"] == pytest.approx(p["C_hr"] / p["C_h"] - 1.0) for p in b["per_esl"])
    assert (out / "run" / "designs" / f"d000_h{hr:g}" / "result.json").is_file()
    assert any(f"수렴 점검 d000 h {hr:g} mm" in ln for ln in logs)
    row = next(x for x in res["ranking"] if x["id"] == "d001")
    assert row["shape"]["refine_bias"]["h_mm"] == pytest.approx(hr) and row["shape"]["refine"]["kind"] == "global"
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "수렴 점검" in html and "세분화(전역" in html and "메시 의존 오차" in html
    dmax = b["delta_max"]
    # tol 경계: tol < δ → 경고, tol > δ → 없음. 캐시 재사용(같은 h_r, 판정 설정만 다름)
    for tol, want in ((dmax * 0.5, True), (dmax * 2.0 + 1e-9, False)):
        cfg = _cfg()
        cfg["bead_doe"]["compare"]["refine"] = {"convergence": {"tol": tol, "same_h_baseline": True}}
        logs = []
        res2 = stg.run_stage(spec("bd_post", cfg=cfg), logs.append)["result"]
        assert any("이전 결과 재사용" in ln for ln in logs)
        assert any(str(w).startswith("MESH_REFINE_BIAS") for w in res2["warnings"]) is want
        b2 = res2["refine_bias"]["d001"]
        assert b2["over_tol"] is want and b2["tol"] == pytest.approx(tol)
        assert b2["improvement_same_h"] == pytest.approx(1.0 - b2["score_same_h"])
        assert next(x for x in res2["ranking"] if x["id"] == "d001")["improvement_same_h"] == b2["improvement_same_h"]
    # 캐시 키에 gmsh·occ 버전(Verifier Low): 버전이 바뀌면 재사용하지 않고 다시 메시·해석
    from esl.doe import mesh_remesh
    v0 = mesh_remesh.build_versions()
    assert v0["gmsh"] == mg.available()[1] and v0["occ"]
    monkeypatch.setattr(mesh_remesh, "build_versions", lambda: {**v0, "occ": "0.0.0-test"})
    logs = []
    stg.run_stage(spec("bd_post"), logs.append)
    assert not any("이전 결과 재사용" in ln for ln in logs) and any(f"수렴 점검 d000 h {hr:g} mm · 요소" in ln for ln in logs)
    # Case 기준·메시 입력 기준 → 다시 메시할 수 없어 생략(info)
    c = stg.Ctx(spec("bd_post"))
    doc = {"reference_source": "case", "shapes": [{"id": "d000", "source": "case"},
                                                  {"id": "d001", "name": "b", "mesh_method": "refine", "refine": {"h_mm": 4}}]}
    bias, w, info = stg._cmp_refine_bias(c, None, doc, [{"id": "d001", "status": "OK"}], 1e-6, lambda m: None)
    assert bias == {} and w == [] and info[0].startswith("REFINE_CONVERGENCE_SKIPPED")


# ---------------------------------------------------------------- v0.16.1 사다리 defeature 단계(esl_select_relax.md V-SR-18·20·21)
def _dimple_two(tmp_path, sid, **doe_kw):
    """기준 평판 d000 + 낮은 딤플(깊이 1.5 < min_bead_height 2) 판 d001."""
    _a, ents = _lib(tmp_path / "lib")
    up = tmp_path / "up"
    paths = [scmp.dimple_plate_step(up / "u0" / "flat.step", [], Lx=LX, Lz=LZ),
             scmp.dimple_plate_step(up / "u1" / "low.step", [(100.0, 75.0, 12.0, 1.5)], Lx=LX, Lz=LZ)]
    shapes = [{"id": f"d{k:03d}", "name": n, "file_name": os.path.basename(p), "path": p, "reference": k == 0,
               "sha256": U.sha256_file(p)} for k, (n, p) in enumerate(zip(("평판", "낮은 딤플"), paths))]
    return {"id": sid, "scenario": "compare", "title": "④ 형상 단순화", "cfg": _cfg(), "entries": ents, "shapes": shapes,
            "reference_source": "step", "inch": 75, "props": PROPS, "mesh_mode": "auto", **doe_kw}


@needs_gmsh
def test_ladder_defeature_stage(tmp_path, monkeypatch):
    """V-SR-18: cad 실패 주입 → defeature(READY) → remesh 시도 없음, mesh_method defeature, 형상 행 defeature 요약,
    mesh/defeature.json, MESH_DEFEATURED·COMPARE_MESH_METHOD_MIXED, 보고서 '작은 형상 억제' 절.
    V-SR-21: base.json profile 에 v0.16.1 새 키 없음, 새 키 변경 → defeature 형상 해시만 바뀜, mesh_input.diag 변경 → 불변."""
    doe = _dimple_two(tmp_path, "DF", mesh_ladder=["cad", "defeature", "remesh"])
    _inject_cad_fail(monkeypatch, {"d001"})
    out = tmp_path / "_doe" / "DF"
    r, spec = _run(out, doe, stages=("bd_input", "bd_mesh0"))
    s = _shape(out, "d001")
    assert s["status"] == "READY" and s["mesh_method"] == "defeature", s.get("attempts")
    assert [a["stage"] for a in s["attempts"]] == ["cad", "defeature"] and s["attempts"][1]["compound"] is True
    assert s["cad_error"]["message"] == "주입된 CAD 실패"
    df = s["defeature"]
    assert df["n"] == 1 and df["counts"] == {"bead": 1} and df["skipped_n"] == 0
    assert df["suppressed_max_mm"] == pytest.approx(1.5, abs=0.15) and df["outside_hausdorff_mm"] < 0.3
    md = out / "prep" / "shapes" / "d001" / "mesh"
    lst = U.read_json(str(md / "defeature.json"))
    assert lst["n"] == 1 and lst["features"][0]["kind"] == "bead" and lst["features"][0]["center"][:2] == pytest.approx([100, 75])
    mj = U.read_json(str(md / "mesh.json"))
    assert mj["mesh_method"] == "defeature" and mj["defeature_stage"]["counts"] == {"bead": 1}
    assert not [p for p in os.listdir(md) if p.startswith("try_")]
    d0 = _shape(out, "d000")
    assert d0["mesh_method"] == "cad" and "defeature_stage" not in d0
    cmp = U.read_json(str(out / "prep" / "compare.json"))
    ws = cmp["warnings"]
    assert any(w.startswith("MESH_DEFEATURED") and "1개 억제(bead 1)" in w and "d001" in w for w in ws), ws
    assert any(w.startswith("COMPARE_MESH_METHOD_MIXED") and "defeature" in w for w in ws), ws
    prof = U.read_json(str(out / "prep" / "base.json"))["profile"]["defeature"]
    assert not set(prof) & set(stg.DEFEAT_NEW_KEYS_V0161) and "min_bead_height_mm" in prof
    from esl.doe import report_doe as rd
    html = rd.render_compare({"study": {"id": "DF"}, "shapes": cmp["shapes"], "profile": cmp["profile"],
                              "defeature_lists": stg._defeat_lists(stg.Ctx(spec("bd_eval")), cmp["shapes"])})
    assert "작은 형상 억제" in html and "형상 단순화" in html and "딤플·비드 1" in html
    # 이어하기 해시(SR-D-21b): 새 키 = defeature 형상만, diag = 불변
    def shas(cfg):
        c = stg.Ctx({"stage": "bd_eval", "out": str(out), "doe": {**doe, "cfg": cfg}})
        return stg._cmp_sha(c, "d000"), stg._cmp_sha(c, "d001")
    base = shas(_cfg())
    new_key = shas(_cfg(defeature={"hole_max_d_mm": 6.0}))
    diag = shas(_cfg(mesh_input={"diag": {"enabled": False}}))
    assert new_key[0] == base[0] and new_key[1] != base[1] and diag == base


def _fake_defeat(monkeypatch, did, plan):
    """형상 did 의 defeature 시도(run_isolated cfg 에 mesh.defeature_stage)만 바꿈 — plan[i] = i 번째 시도의 동작:
    ('fail', mesh_error 추가 dict) | ('nofeat', None). 반환 호출 기록 [compound]."""
    real = mg.run_isolated
    calls: list = []

    def fake(src, out_dir, h, cfg, props, **kw):
        ds = (cfg.get("mesh") or {}).get("defeature_stage")
        if f"{os.sep}shapes{os.sep}{did}{os.sep}" not in os.path.abspath(str(out_dir)) + os.sep or ds is None:
            return real(src, out_dir, h, cfg, props, **kw)
        calls.append(bool(ds["compound"]))
        act, extra = plan[len(calls) - 1]
        if act == "nofeat":
            raise EslError("DEFEATURE_NO_FEATURE", "형상 단순화 단계: 억제할 작은 형상이 없음")
        os.makedirs(out_dir, exist_ok=True)
        U.write_json(os.path.join(out_dir, mg.MESH_ERROR), {"code": "FAILED_MESH", "message": "x", **(extra or {})})
        raise EslError("FAILED_MESH", f"defeature 주입 {len(calls)}")
    monkeypatch.setattr(mg, "run_isolated", fake)
    return calls


@needs_gmsh
def test_ladder_defeature_compound_retry_and_skips(tmp_path, monkeypatch):
    """V-SR-20: compound 묶음 면 실패 → 2번째 시도(compound 끔), 다른 면 실패 → not_compound 건너뜀, 억제 대상 0 →
    SKIPPED no_feature(2번째 기록 없음) + 정보 DEFEATURE_NO_FEATURE. 사다리 전부 실패 → FAILED_MESH 문구에 '형상 단순화'."""
    K = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    cases = {"retry": [("fail", {"face": {"key": K}, "compound_keys": [K]}), ("fail", None)],
             "other": [("fail", {"face": {"key": [0, 0, 0, 1, 1, 1]}, "compound_keys": [K]})],
             "nofeat": [("nofeat", None)]}
    for name, plan in cases.items():
        doe = _dimple_two(tmp_path / name, f"R{name}", mesh_ladder=["cad", "defeature"])
        _inject_cad_fail(monkeypatch, {"d001"})
        calls = _fake_defeat(monkeypatch, "d001", plan)
        out = tmp_path / "_doe" / name
        r, _spec = _run(out, doe, stages=("bd_input", "bd_mesh0"))
        s = _shape(out, "d001")
        att = [(a["stage"], a["status"], a.get("compound"), a.get("reason")) for a in s["attempts"]]
        assert s["status"] == "FAILED_MESH" and s.get("mesh_method") is None, name
        if name == "retry":
            assert calls == [True, False]
            assert att[1:] == [("defeature", "FAILED_MESH", True, None), ("defeature", "FAILED_MESH", False, None)]
            assert stg._ladder_fail_text(s) == "CAD 메시 실패: 주입된 CAD 실패 → 형상 단순화도 실패: defeature 주입 2"
        elif name == "other":
            assert calls == [True]
            assert att[1:] == [("defeature", "FAILED_MESH", True, None), ("defeature", "SKIPPED", False, "not_compound")]
        else:
            assert calls == [True] and att[1:] == [("defeature", "SKIPPED", True, "no_feature")]
            assert any(i.startswith("DEFEATURE_NO_FEATURE") and "d001" in i for i in r["bd_mesh0"]["info"])
        monkeypatch.undo()
