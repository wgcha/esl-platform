"""V-BD-4: ① 같은 모델 — 동일성(topo)·다른 모델 MODEL_MISMATCH, 모핑 노드 읽기(바뀐 파일만·ID 불변·누락 오류·좌표 필드만),
노드 직접 하중이 모든 안에 같음, BD_BASE_CUMULATIVE, ASSEM_TOO_LARGE 경계, 링크 거부, 입력 폴더 불변(코어 단계)."""
import os

import numpy as np
import pytest

import synth_doe as sd
from esl.doe import nodes as nd
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U
from esl.library.entry import load as load_entry

CFG_FULL = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}


def case(tmp_path, mesh=None):
    mesh = mesh or sd.plate()
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True)
    rad = sd.write_mesh_rad(str(cd / "model.rad"), mesh)
    return mesh, str(cd), rad


def test_identity_and_model_mismatch(tmp_path):
    mesh, cd, rad = case(tmp_path)
    lib = tmp_path / "lib"
    d1, _ = sd.save_entry(str(lib), "E1", mesh, "bend")
    d2, _ = sd.save_entry(str(lib), "E2", mesh, "twist")
    e1, e2 = load_entry(d1), load_entry(d2)
    t, info = sc.same_base(rad, sd.PART_TITLE, e1, [e1, e2], coord_tol_rel=0.005)
    assert t.scenario == "S1" and t.n_nodes == mesh["node_id"].size and info == []
    assert [r["entry_id"] for r in t.source["identity"]][-1] == "E2"
    other = sd.plate(nx=10, ny=8)
    d3, _ = sd.save_entry(str(lib), "E3", other, "bend")
    with pytest.raises(EslError) as ei:
        sc.same_base(rad, sd.PART_TITLE, e1, [load_entry(d3)], coord_tol_rel=0.005)
    assert ei.value.code == "MODEL_MISMATCH"
    loads, linfo = sc.entry_loads(t, [e1, e2])
    assert linfo["method"] == "direct_nodal"
    assert np.allclose(loads[0][1], e1.raw["f"]) and np.allclose(loads[1][1], e2.raw["f"])


def test_assem_limit_links_and_cumulative(tmp_path):
    mesh, cd, rad = case(tmp_path)
    size = os.path.getsize(rad)
    (tmp_path / "case" / "input" / "notes.txt").write_text("x" * 100000)          # rad/inc 외 파일은 합계 제외
    mb = size / (1024 * 1024)
    r = sc.assem_dir_check(cd, mb)                                                # 같음 = 허용
    assert r["n_files"] == 1 and abs(r["total_mb"] - round(mb, 3)) < 1e-9
    with pytest.raises(EslError) as ei:
        sc.assem_dir_check(cd, mb * 0.999)
    assert ei.value.code == "ASSEM_TOO_LARGE"
    os.symlink(rad, os.path.join(cd, "link.inc"))
    with pytest.raises(EslError) as ei:
        sc.assem_dir_check(cd, 1e9)
    assert ei.value.code == "PATH_OUTSIDE_ROOT"
    os.remove(os.path.join(cd, "link.inc"))
    with pytest.raises(EslError) as ei:
        sc.assem_dir_check(str(tmp_path / "nope"), 1)
    assert ei.value.code == "PREREQUISITE_MISSING"
    assert not sc.is_cumulative(rad)
    main = os.path.join(cd, "main.rad")
    with open(main, "w") as fh:
        fh.write("#RADIOSS STARTER\n#include model.rad\n#include state.str\n/END\n")
    open(os.path.join(cd, "state.str"), "w").close()
    assert sc.is_cumulative(main)


def test_morphed_nodes(tmp_path):
    mesh = sd.plate()
    od = tmp_path / "out_files"
    od.mkdir()
    x = mesh["x0"].copy()
    x[:5, 1] += 1.25
    sd.write_mesh_rad(str(od / "a.rad"), mesh, x)
    X, info = nd.morphed_coords(str(od), ["a.rad"], mesh["node_id"], mesh["x0"], expected_moved=5)
    assert np.allclose(X, x) and info["n_moved"] == 5 and info["n_found"] == mesh["node_id"].size
    assert abs(info["max_disp"] - 1.25) < 1e-12
    # 바뀐 파일만: 대상 노드 일부만 있는 사본 → 나머지는 원 좌표
    part = tmp_path / "out2"
    part.mkdir()
    lines = ["/NODE", "#  node_ID                  Xc                  Yc                  Zc"]
    for i in range(3):
        lines.append(f"{int(mesh['node_id'][i]):>10d}{x[i, 0]:>20.6f}{x[i, 1]:>20.6f}{x[i, 2]:>20.6f}")
    lines += ["/SHELL/7", "#comment", "/END"]
    (part / "n.inc").write_text("\n".join(lines) + "\n")
    X2, i2 = nd.morphed_coords(str(part), ["n.inc"], mesh["node_id"], mesh["x0"])
    assert i2["n_found"] == 3 and np.allclose(X2[:3], x[:3]) and np.allclose(X2[3:], mesh["x0"][3:])
    # 자유 형식(쉼표)
    (part / "f.inc").write_text(f"/NODE\n{int(mesh['node_id'][0])}, 1.5, 2.5, 3.5\n/END\n")
    X3, _ = nd.morphed_coords(str(part), ["f.inc"], mesh["node_id"], mesh["x0"])
    assert np.allclose(X3[0], [1.5, 2.5, 3.5])
    with pytest.raises(EslError) as ei:
        nd.morphed_coords(str(part), ["missing.inc"], mesh["node_id"], mesh["x0"])
    assert ei.value.code == "MORPH_NODES_MISSING"
    with pytest.raises(EslError) as ei:
        nd.morphed_coords(str(part), ["../out_files/a.rad"], mesh["node_id"], mesh["x0"])
    assert ei.value.code == "PATH_OUTSIDE_ROOT"
    (part / "e.inc").write_text("/NODE\n/END\n")
    with pytest.raises(EslError) as ei:
        nd.morphed_coords(str(part), ["e.inc"], mesh["node_id"], mesh["x0"], expected_moved=4)
    assert ei.value.code == "MORPH_NODES_MISSING"
    nid0 = int(mesh["node_id"][0])
    (part / "d.inc").write_text(f"/NODE\n{nid0:>10d}{1.0:>20}{0.0:>20}{0.0:>20}\n{nid0:>10d}{2.0:>20}{0.0:>20}{0.0:>20}\n")
    with pytest.raises(EslError) as ei:
        nd.morphed_coords(str(part), ["d.inc"], mesh["node_id"], mesh["x0"])
    assert ei.value.code == "RAD_PARSE_ERROR"
    (part / "long.inc").write_bytes(b"/NODE\n" + b"1" * 5000)
    with pytest.raises(EslError) as ei:
        nd.read_nodes(str(part / "long.inc"), None, max_line=1024)
    assert ei.value.code == "RAD_PARSE_ERROR"


def _spec(tmp, stage, doe, **extra):
    return {"stage": stage, "out": str(tmp / "_doe" / "S1"), "doe": {**doe, **extra}}


def test_same_pipeline_direct_loads(tmp_path):
    """① 코어 흐름(가짜 paicad): 입력 → 하중 → 행렬 → 안 평가 → 후처리. 모든 안의 하중이 같은 노드 하중."""
    mesh, cd, rad = case(tmp_path)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", mesh, kind, 1.0 + k, seed=k)[0]
            for k, kind in enumerate(("bend", "twist", "dent"))]
    step = tmp_path / "up" / "ch.step"
    step.parent.mkdir()
    step.write_text("ISO-10303-21;\nfake\n")
    stamp_case, stamp_lib = sc.tree_stamp(cd), sc.tree_stamp(str(lib))
    doe = {"id": "S1", "scenario": "same", "title": "t", "cfg": CFG_FULL,
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": cd},
           "step": {"path": str(step), "file_name": "ch.step"}, "paicad_version": "0.14.0"}
    r = stg.run_stage(_spec(tmp_path, "bd_input", doe), lambda s: None)
    assert r["part_id"] == sd.PART_ID
    out = tmp_path / "_doe" / "S1"
    assert (out / "input" / "step" / "ch.step").read_text().startswith("ISO-10303-21;")
    sd.write_extract(str(out / "prep" / "extract"), sd.features_doc(mesh, 2))
    r = stg.run_stage(_spec(tmp_path, "bd_loads", doe), lambda s: None)
    assert r["n_params"] == 8 and r["boundary"] is None
    spec = {"method": "lhs", "n": 4, "seed": 5, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 6.0},
                                                          {"name": "CHASSIS_REAR_BEAD_W_1", "lo": 10.0, "hi": 14.0}]}
    r = stg.run_stage(_spec(tmp_path, "bd_matrix", doe, rev=1, spec=spec), lambda s: None)
    m = U.read_json(str(out / "doe" / "1" / "matrix.json"))
    assert r["matrix_sha256"] == m["matrix_sha256"] and m["n_designs"] == 5
    with pytest.raises(EslError) as ei:
        stg.run_stage(_spec(tmp_path, "bd_matrix", doe, rev=2, spec=spec, matrix_sha256="0" * 64), lambda s: None)
    assert ei.value.code == "MATRIX_MISMATCH"
    ids = [d["id"] for d in m["designs"]]
    sd.write_grid(str(out / "doe" / "1" / "grid"), {i: ("OK", None) for i in ids[1:-1]} |
                  {ids[-1]: ("FAIL", "GEOM_FEATURE_COLLISION")})
    r = stg.run_stage(_spec(tmp_path, "bd_eval", doe, rev=1, design="d000"), lambda s: None)
    assert r["status"] == "OK"
    for d in m["designs"][1:-1]:
        sd.write_run(str(out / "run" / "designs" / d["id"]), mesh, d["values"])
        r = stg.run_stage(_spec(tmp_path, "bd_eval", doe, rev=1, design=d["id"], paicad={"ok": True, "seconds": 1.0}),
                          lambda s: None)
        assert r["status"] == "OK", r
    # 같은 입력 → 재사용
    r = stg.run_stage(_spec(tmp_path, "bd_eval", doe, rev=1, design=ids[1], paicad={"ok": True}), lambda s: None)
    assert r["reused"]
    # paicad 실패 안 → 상태만 기록
    r = stg.run_stage(_spec(tmp_path, "bd_eval", doe, rev=1, design=ids[-1],
                            paicad={"ok": False, "status": "SKIPPED_COLLISION", "code": "SKIPPED_COLLISION"}),
                      lambda s: None)
    assert r["status"] == "SKIPPED_COLLISION"
    # 모든 안의 하중 = loads.npz(노드 직접, 원본 F_eq)
    nid, loads = sc.load_loads(str(out / "prep"))
    assert np.array_equal(nid, mesh["node_id"])
    for k, (eid, F) in enumerate(loads):
        assert eid == f"E{k}" and np.allclose(F, load_entry(dirs[k]).raw["f"])
    d1 = U.read_json(str(out / "run" / "designs" / ids[1] / "result.json"))
    z = U.load_npz(str(out / "run" / "designs" / ids[1] / "design.npz"))
    assert np.array_equal(z["node_id"], mesh["node_id"]) and set(z) == {"node_id", "x"}
    assert np.allclose(z["x"], sd.morph_x(mesh, m["designs"][1]["values"]))
    assert len(d1["per_esl"]) == 3 and d1["status"] == "OK"
    r = stg.run_stage(_spec(tmp_path, "bd_post", doe, rev=1), lambda s: None)
    res = r["result"]
    assert res["n_ok"] == len(ids) - 2 and res["n_skipped"]["collision"] == 1
    assert res["ranking"][0]["rank"] == 1 and res["best"]["id"] == res["ranking"][0]["id"]
    assert (out / "report.html").is_file() and (out / "post" / "ranking.csv").is_file()
    assert (out / "post" / "view3d" / "d000" / "manifest.json").is_file()
    best = out / "best" / res["best"]["id"]
    assert (best / "values.json").is_file() and (best / "include" / "model.rad").is_file()
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "방법·출처" in html and "한계" in html and "<script src" not in html
    # 입력 폴더 불변
    assert sc.tree_stamp(cd) == stamp_case and sc.tree_stamp(str(lib)) == stamp_lib
