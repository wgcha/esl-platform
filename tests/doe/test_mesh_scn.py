"""V-BD-5: ② 다른 모델 + B 메시 — 크기 ±5 %·인치, B 베이스라인 1회 매핑·지지가 모든 안 동일(ID 불변), 셀 합력·합모멘트
보존 1e-9, B_NO_FASTENERS, B 메시 복사(업로드 밖 include 거부·sha 재확인), 경계 경고 산출(코어 단계)."""

import numpy as np
import pytest

import synth_doe as sd
from esl.doe import opt_settings
from esl.doe import scenario as sc
from esl.doe import stages as stg
from esl.errors import EslError
from esl.library import _util as U
from esl.library import mapping as mp
from esl.library.entry import load as load_entry

CFG_FULL = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}


def test_size_rule_and_inch(tmp_path):
    a = sd.plate(nx=12, ny=8, Lx=300.0, Lz=200.0)
    d1, _ = sd.save_entry(str(tmp_path / "lib"), "E1", a, inch=75)
    e1 = load_entry(d1)
    size = opt_settings({"opt_run": {}})["size"]
    ok = sd.plate(nx=14, ny=9, Lx=314.0, Lz=191.0)                        # +4.7 %, −4.5 %
    t, info = sc.template_base(ok, [e1], size, inch=75)
    assert t.scenario == "S2" and info["template"]["ok"]
    with pytest.raises(EslError) as ei:
        sc.template_base(sd.plate(nx=14, ny=9, Lx=316.0, Lz=200.0), [e1], size, inch=75)   # +5.3 %
    assert ei.value.code == "SIZE_MISMATCH"
    with pytest.raises(EslError) as ei:
        sc.template_base(ok, [e1], size, inch=65)
    assert ei.value.code == "SIZE_MISMATCH"
    t2, info2 = sc.template_base(ok, [e1], size, inch=None)                  # B 인치 없음 → 치수만
    assert info2["template"]["inch_ok"] is None


def test_copy_mesh_upload(tmp_path):
    up = tmp_path / "up"
    up.mkdir()
    mesh = sd.plate()
    sd.write_mesh_rad(str(up / "part.inc"), mesh)
    (up / "main.rad").write_text("#RADIOSS STARTER\n#include part.inc\n/END\n")
    files = sc.copy_mesh_upload(str(up / "main.rad"), str(up), str(tmp_path / "dst"))
    assert [f["rel"] for f in files] == ["main.rad", "part.inc"]
    assert files[1]["sha256"] == U.sha256_file(str(tmp_path / "dst" / "part.inc"))
    (tmp_path / "outside.inc").write_text("/END\n")
    (up / "bad.rad").write_text("#include ../outside.inc\n/END\n")
    with pytest.raises(EslError) as ei:
        sc.copy_mesh_upload(str(up / "bad.rad"), str(up), str(tmp_path / "dst2"))
    assert ei.value.code == "PATH_OUTSIDE_ROOT"
    (up / "miss.rad").write_text("#include nothere.inc\n/END\n")
    with pytest.raises(EslError) as ei:
        sc.copy_mesh_upload(str(up / "miss.rad"), str(up), str(tmp_path / "dst3"))
    assert ei.value.code == "MESH_INVALID"


def test_mesh_pipeline_mapping_once(tmp_path):
    a = sd.plate(nx=24, ny=14, Lx=480.0, Lz=280.0)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), f"E{k}", a, kind, 1.0 + k, seed=k)[0] for k, kind in enumerate(("bend", "twist"))]
    b = sd.plate(nx=26, ny=15, Lx=490.0, Lz=276.0, holes=[(12, 14, 6, 8)])
    up = tmp_path / "up"
    up.mkdir()
    sd.write_mesh_rad(str(up / "b.rad"), b)
    step = up / "b.step"
    step.write_text("ISO-10303-21;\n")
    stamp = sc.tree_stamp(str(up))
    doe = {"id": "S2", "scenario": "mesh", "cfg": CFG_FULL, "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "mesh": {"path": str(up / "b.rad"), "upload_root": str(up), "part_title": sd.PART_TITLE},
           "step": {"path": str(step), "file_name": "b.step"}, "inch": 75}
    out = tmp_path / "_doe" / "S2"

    def spec(stage, **kw):
        return {"stage": stage, "out": str(out), "doe": {**doe, **kw}}
    r = stg.run_stage(spec("bd_input"), lambda s: None)
    assert r["part_id"] == sd.PART_ID
    assert (out / "input" / "mesh" / "b.rad").is_file()
    sd.write_extract(str(out / "prep" / "extract"), sd.features_doc(b, 2))
    sd.write_fixed(str(out / "prep" / "fixed"), b, [])                       # B 체결 없음
    sd.write_fixed(str(out / "prep" / "a_fixed"), a, [[0, 1, 15], [200, 201]])
    r = stg.run_stage(spec("bd_loads"), lambda s: None)
    assert "B_NO_FASTENERS" in r["info"] and r["boundary"]["n_warn"] >= 1
    bj = U.read_json(str(out / "prep" / "boundary.json"))
    assert {w["code"] for w in bj["warnings"]} <= {"BOUNDARY_FASTENER_FAR", "BOUNDARY_LOAD_UNSUPPORTED"}
    assert any(p["label"].startswith("A RBE2") for p in bj["a_points"])
    assert any(p["kind"] == "HOLE" for p in bj["fixed"])
    plan = U.read_json(str(out / "prep" / "plan.json"))
    assert plan["a_points"] == bj["a_points"] and len(plan["beads"]) == 2
    # 매핑 1회: loads.npz = B 베이스라인 노드 하중, 셀 합력·합모멘트 보존
    t, _ = sc.load_base(str(out / "prep"))
    nid, loads = sc.load_loads(str(out / "prep"))
    assert np.array_equal(nid, t.mesh["node_id"])
    for (eid, F), dd in zip(loads, dirs):
        e = load_entry(dd)
        f2, info = mp.to_target(e.summary_for_mapping(), t.mesh["x0"], t.frame, {"equilibrate": False})
        assert info["conservation_rel_max"] < 1e-9
        X = t.mesh["x0"]
        tF, tM = mp.resultants(X, F, X.mean(axis=0))
        assert np.linalg.norm(tF) <= 1e-9 * np.abs(F).sum() and np.linalg.norm(tM) <= 1e-9 * np.abs(F).sum() * 600
    sp = {"method": "fullfact", "levels": 2, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 6.0}]}
    stg.run_stage(spec("bd_matrix", rev=1, spec=sp), lambda s: None)
    m = U.read_json(str(out / "doe" / "1" / "matrix.json"))
    stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)
    for d in m["designs"][1:]:
        sd.write_run(str(out / "run" / "designs" / d["id"]), b, d["values"], rel="b.rad")
        assert stg.run_stage(spec("bd_eval", rev=1, design=d["id"], paicad={"ok": True}), lambda s: None)["status"] == "OK"
    # 지지 = 같은 node_id(B 베이스라인 자동 3-2-1), 하중 = 같은 배열
    sup0 = U.read_json(str(out / "prep" / "base.json"))["supports"]
    assert len(sup0) == 3
    res = stg.run_stage(spec("bd_post", rev=1), lambda s: None)["result"]
    assert res["n_ok"] == 2 and res["boundary_warnings_n"] == bj["n_warn"]
    assert sc.tree_stamp(str(up)) == stamp
