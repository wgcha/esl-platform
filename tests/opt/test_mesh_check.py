"""V-OR-8: 메시 검사(rad·fem) — 비지원 요소·두께·상한·연결·평탄도·법선·비드 폭/요소 크기·셀당 노드·형상·3-2-1,
check_file(MeshCheckOut) 형식, 업로드 폴더 읽기만."""
import os

import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.opt import femread, mesh_check as mc
from esl.rad import write_rad

CFG = so.cfg()


def codes(q, kind):
    return {x["code"] for x in q[kind]}


def test_clean_plate_ok():
    m = so.plate(48, 28, Lx=480, Lz=280)
    q = mc.check(m, "S2", CFG, supports=so.supports_321(m), bead={"min_width": 60.0})
    assert q["errors"] == [] and codes(q, "warnings") <= {"MAPPING_RESOLUTION"}
    assert q["metrics"]["n_components"] == 1 and q["metrics"]["elem_size_median"] == pytest.approx(10.0)


def test_warnings_and_errors():
    m = so.plate(12, 8, n_tria_cols=6, bow=30.0)
    c = m["conn"].copy()
    c[-3:] = c[-3:][:, [0, 3, 2, 1]]
    m2 = {**m, "conn": c}
    q = mc.check(m2, "S2", CFG, bead={"min_width": 20.0}, normals_changed=3)
    w = codes(q, "warnings")
    assert {"TRIA_FRAC", "NOT_FLAT", "NORMALS_ALIGNED", "BEAD_WIDTH", "MAPPING_RESOLUTION"} <= w
    q1 = mc.check(m2, "S1", CFG)
    assert "NORMALS_OPPOSITE" in codes(q1, "warnings") and "NOT_FLAT" not in codes(q1, "warnings")
    bad = {**m, "thickness": np.where(np.arange(m["elem_id"].size) == 0, 0.0, 1.5)}
    assert "THICKNESS" in codes(mc.check(bad, "S2", CFG), "errors")
    assert "MATERIAL" in codes(mc.check({**m, "nu": np.full(m["elem_id"].size, 0.6)}, "S2", CFG), "errors")
    small = {**CFG, "template": {**CFG["template"], "max_elems": 10}}
    assert "TOO_MANY_ELEMS" in codes(mc.check(m, "S2", small), "errors")
    assert "TOO_MANY_ELEMS" not in codes(mc.check(m, "S1", small), "errors")
    # 연결 성분 2개 + 일치 노드(두 판이 같은 모서리 좌표를 공유하지만 노드는 다름)
    a = so.plate(4, 4, Lx=40, Lz=40)
    b = so.plate(4, 4, Lx=40, Lz=40, node_base=100, elem_base=100)
    b["x0"] = b["x0"] + np.array([40.0, 0, 0])
    two = {k: np.concatenate([a[k], b[k] + (a["x0"].shape[0] if k == "conn" else 0)]) if k != "x0"
           else np.concatenate([a["x0"], b["x0"]]) for k in a}
    two["conn"] = np.concatenate([a["conn"], np.where(b["conn"] >= 0, b["conn"] + a["x0"].shape[0], -1)])
    q2 = mc.check(two, "S2", CFG)
    assert {"COMPONENTS", "COINCIDENT_NODES"} <= codes(q2, "warnings") and q2["metrics"]["n_components"] == 2
    # 형상: 찌그러진 쿼드
    X = m["x0"].copy()
    X[m["conn"][-1, 2], 1] += 8.0
    q3 = mc.check({**m, "x0": X}, "S1", CFG)
    assert "WARP" in codes(q3, "warnings")
    long = so.plate(2, 30, Lx=300, Lz=20)
    assert "ASPECT" in codes(mc.check(long, "S1", CFG), "warnings")
    # 3-2-1 공선
    nid = m["node_id"]
    q4 = mc.check(m, "S2", CFG, supports=[(int(nid[0]), "123"), (int(nid[1]), "23"), (int(nid[2]), "3")])
    assert "SUPPORT_DEGENERATE" in codes(q4, "errors")


def _fem_with(tmp_path, m, extra=""):
    p = femread.write_fem(str(tmp_path / "t.fem"), m)
    if extra:
        txt = open(p).read().replace("ENDDATA", extra + "ENDDATA")
        open(p, "w").write(txt)
    return p


def test_check_file_fem_and_unsupported_element(tmp_path):
    m = so.plate(30, 18, Lx=300, Lz=180)
    p = _fem_with(tmp_path, m)
    before = os.stat(p).st_mtime_ns
    out = mc.check_file(p, None, CFG, bead={"min_width": 60.0})
    assert out["ok"] and out["format"] == "fem" and out["mesh"]["n_elems"] == m["elem_id"].size
    assert out["frame"]["L_xi"] == pytest.approx(300.0) and len(out["supports_auto"]) == 3
    assert out["pids"][0]["pid"] == 10 and len(out["sha256"]) == 64
    assert os.stat(p).st_mtime_ns == before and sorted(os.listdir(tmp_path)) == ["t.fem"]
    p2 = _fem_with(tmp_path, m, "CHEXA,999,1,1,2,3,4,5,6\n+,7,8\n")
    out2 = mc.check_file(p2, None, CFG)
    assert not out2["ok"] and "ELEMENT_UNSUPPORTED" in codes(out2["quality"], "errors")
    with pytest.raises(EslError) as ei:
        mc.check_file(str(tmp_path / "x.stp"), None, CFG)
    assert ei.value.code == "MESH_FORMAT_UNSUPPORTED"


def test_check_file_rad_parts(tmp_path):
    m = so.plate(20, 12, Lx=300, Lz=180)
    ids = np.where(m["conn"] >= 0, m["node_id"][np.maximum(m["conn"], 0)], 0)
    p = str(tmp_path / "t.rad")
    write_rad(p, m["node_id"], m["x0"], m["elem_id"], m["elem_type"], ids, 5, "plate", 10, 1.5, 1, so.E_STEEL,
              so.NU, extra_parts=1)
    out = mc.check_file(p, None, CFG)
    assert out["format"] == "rad" and out["part_title"] == "plate" and len(out["parts"]) == 2
    assert any("파트 2개" in w["message"] for w in out["quality"]["warnings"])
    out2 = mc.check_file(p, "plate", CFG)
    assert out2["mesh"]["n_elems"] == m["elem_id"].size
    with pytest.raises(EslError) as ei:
        mc.check_file(p, "nope", CFG)
    assert ei.value.code == "PART_NOT_FOUND"
    bad = tmp_path / "bad.rad"
    bad.write_text("#RADIOSS STARTER\n/BEGIN\n", encoding="ascii")
    with pytest.raises(EslError) as ei:
        mc.check_file(str(bad), None, CFG)
    assert ei.value.code == "MESH_INVALID"
