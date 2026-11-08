"""v0.16.0 ④ 메시 입력(esl_compare_mesh_options.md C2-D-2~8, V-C2-5·6): 사용자 Radioss 메시(.rad/.inc)를 그대로 형상으로."""
import hashlib
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rad"))
import synth_mesh_rad as smr  # noqa: E402

from esl.doe import mesh_gmsh as mg  # noqa: E402
from esl.doe import mesh_input as mi  # noqa: E402
from esl.doe import scenario as sc  # noqa: E402
from esl.doe import settings  # noqa: E402
from esl.errors import EslError  # noqa: E402

PROPS = {"t": 1.2, "E": 205000.0, "nu": 0.3}


def _cfg(**over):
    c = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "compare": over}}))
    return c


def _code(fn, *a, **k):
    with pytest.raises(EslError) as ei:
        fn(*a, **k)
    return ei.value.code


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _deck(d, dx=3.0, length="mm", two=True):
    ids, X, e1, c1 = smr.grid(10, 8, dx, dx)
    lines = smr.begin(length) + smr.part(1, "chassis") + smr.nodes(ids, X) + smr.shells(1, e1[:40], c1[:40])
    ids2, X2, e2, c2 = smr.grid(3, 3, dx, dx, x0=200.0, nid0=5001, eid0=7001)
    smr.write(d / "inc" / "b.inc", smr.shells(1, e1[40:], c1[40:]) + ['/INCLUDE "c.inc"'])
    smr.write(d / "inc" / "c.inc", (smr.part(2, "other") + smr.nodes(ids2, X2) + smr.shells(2, e2, c2)) if two else ["# 빈"])
    return smr.write(d / "main.rad", lines + ['/INCLUDE "inc/b.inc"', "/END"])


def test_read_shape_mesh_parts_includes_id_map(tmp_path):
    main = _deck(tmp_path)
    shas = {p: _sha(p) for p in (main, tmp_path / "inc" / "b.inc", tmp_path / "inc" / "c.inc")}
    cfg = _cfg()
    assert _code(mi.read_shape_mesh, str(tmp_path), "main.rad", None, PROPS, cfg) == "MESH_INPUT_PART_REQUIRED"
    assert [p["id"] for p in mi.scan_parts(str(tmp_path), "main.rad", cfg)] == [1, 2]
    out = tmp_path.parent / (tmp_path.name + "_out")
    m, meta = mi.read_shape_mesh(str(tmp_path), "main.rad", 1, PROPS, cfg, out_dir=str(out))
    assert set(mg.MESH_KEYS) <= set(m) and m["elem_id"].tolist() == list(range(1, 81))
    assert np.all(m["thickness"] == 1.2) and np.all(m["E"] == 205000.0)
    assert meta["method"] == "mesh_input" and meta["part_id"] == 1 and meta["length_unit"] == "mm"
    assert [f["rel"] for f in meta["files"]] == ["main.rad", "inc/b.inc", "inc/c.inc"]
    assert meta["id_map"]["elem_id_orig"].tolist() == list(range(1, 81))
    assert meta["id_map"]["node_id_orig"].size == m["node_id"].size == 99
    assert abs(meta["edge_median_mm"] - 3.0) < 1e-9 and meta["n_components"] == 1
    assert not [w for w in meta["warnings"] if w["code"].startswith("MESH_INPUT")]
    assert (out / mi.ID_MAP_NPZ).is_file() and (out / mg.MESH_NPZ).is_file()
    m2, meta2 = mi.read_shape_mesh(str(tmp_path), "main.rad", 2, PROPS, cfg)
    assert m2["elem_id"].size == 9 and meta2["id_map"]["elem_id_orig"][0] == 7001
    assert {p: _sha(p) for p in shas} == shas                          # 원본(입력 폴더) 불변


def test_mesh_input_rules(tmp_path):
    cfg = _cfg()
    root = tmp_path / "in"
    _deck(root, two=False)
    assert mi.read_shape_mesh(str(root), "main.rad", None, PROPS, cfg)[1]["part_id"] == 1   # 쉘 파트 1개 → 생략 가능
    (root / "x.bdf").write_text("GRID\n")
    assert _code(mi.read_shape_mesh, str(root), "x.bdf", 1, PROPS, cfg) == "MESH_FORMAT_UNSUPPORTED"
    ids, X, e, c = smr.grid(4, 4, 3.0, 3.0)
    smr.write(root / "m_unit.rad", smr.begin("m") + smr.nodes(ids, X) + smr.shells(1, e, c))
    assert _code(mi.read_shape_mesh, str(root), "m_unit.rad", 1, PROPS, cfg) == "MESH_INPUT_UNIT"
    smr.write(root / "only.inc", smr.nodes(ids, X) + smr.shells(9, e, c))       # /BEGIN 없음 → mm 가정 info
    _m, meta = mi.read_shape_mesh(str(root), "only.inc", None, PROPS, cfg)
    codes = [x["code"] for x in meta["infos"]]
    assert "MESH_INPUT_UNIT_ASSUMED" in codes and "MESH_INPUT_PART_CARD_MISSING" in codes
    smr.write(tmp_path / "outside.inc", smr.nodes(ids, X) + smr.shells(9, e, c))
    smr.write(root / "esc.rad", ['/INCLUDE "../outside.inc"'])
    assert _code(mi.read_shape_mesh, str(root), "esc.rad", 9, PROPS, cfg) == "PATH_OUTSIDE_ROOT"
    smr.write(root / "miss.rad", ['/INCLUDE "nope.inc"'])
    assert _code(mi.read_shape_mesh, str(root), "miss.rad", 9, PROPS, cfg) == "MESH_INPUT_INVALID"
    if hasattr(os, "symlink"):
        try:
            os.symlink(tmp_path / "outside.inc", root / "lnk.inc")
        except OSError:
            pass
        else:
            smr.write(root / "lnk.rad", ['/INCLUDE "lnk.inc"'])
            assert _code(mi.read_shape_mesh, str(root), "lnk.rad", 9, PROPS, cfg) == "PATH_OUTSIDE_ROOT"
    (root / "prev.sta").write_text("/BEGIN\nprev\n")
    smr.write(root / "st.rad", ['/INCLUDE "only.inc"', '/INCLUDE "prev.sta"'])
    assert _code(mi.read_shape_mesh, str(root), "st.rad", 9, PROPS, cfg) == "MESH_INPUT_INVALID"
    small = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"max_elems": 10}}}))
    assert _code(mi.read_shape_mesh, str(root), "only.inc", None, PROPS, small) == "MESH_TOO_LARGE"
    assert _code(mi.read_shape_mesh, str(root), "main.rad", 1, PROPS, _cfg(mesh_input={"max_mb": 1e-6})) \
        == "MESH_INPUT_TOO_LARGE"
    assert _code(mi.read_shape_mesh, str(root), "main.rad", 1, PROPS, _cfg(mesh_input={"include": False})) \
        == "MESH_INPUT_INVALID"


def test_size_diff_and_disconnected(tmp_path):
    """V-C2-6: 6 mm 메시 → MESH_INPUT_SIZE_DIFF(h 3 mm, r 1.5), 기준 대비 비, 두 조각 → MESH_INPUT_DISCONNECTED."""
    cfg = _cfg()
    _deck(tmp_path / "a", dx=6.0, two=False)
    _m, meta = mi.read_shape_mesh(str(tmp_path / "a"), "main.rad", 1, PROPS, cfg)
    assert [w["code"] for w in meta["warnings"]].count("MESH_INPUT_SIZE_DIFF") == 1
    _deck(tmp_path / "b", dx=4.0, two=False)                            # 4 mm 는 [2, 4.5] 안 — 기준 2.5 mm 대비 ×1.6
    assert not [w for w in mi.read_shape_mesh(str(tmp_path / "b"), "main.rad", 1, PROPS, cfg)[1]["warnings"]
                if w["code"] == "MESH_INPUT_SIZE_DIFF"]
    _m, mb = mi.read_shape_mesh(str(tmp_path / "b"), "main.rad", 1, PROPS, cfg, ref_e50=2.5)
    assert any(w["code"] == "MESH_INPUT_SIZE_DIFF" for w in mb["warnings"])
    ids, X, e, c = smr.grid(4, 4, 3.0, 3.0)
    ids2, X2, e2, c2 = smr.grid(4, 4, 3.0, 3.0, x0=100.0, nid0=500, eid0=500)
    smr.write(tmp_path / "c" / "two.rad", smr.nodes(np.r_[ids, ids2], np.r_[X, X2])
              + smr.shells(3, np.r_[e, e2], np.r_[c, c2]))
    _m, mc = mi.read_shape_mesh(str(tmp_path / "c"), "two.rad", 3, PROPS, cfg)
    assert mc["n_components"] == 2 and any(w["code"] == "MESH_INPUT_DISCONNECTED" for w in mc["warnings"])
    assert not mc["errors"]                                             # 조각은 경고만(MESH_DISCONNECTED 오류 아님)


def test_length_unit_rules():
    assert mi.length_unit(None) == {"unit": None, "ok": None}
    assert mi.length_unit(smr.begin("mm")[1:])["ok"] is True
    assert mi.length_unit(smr.begin("m")[1:])["ok"] is False
    assert mi.length_unit(smr.begin("0.001")[1:])["ok"] is True
    assert mi.length_unit(smr.begin("1.0")[1:])["ok"] is False


def test_mesh_input_diag_report_only(tmp_path):
    """V-SR-23(SR-D-24): 작은 구멍(3×3 mm 요소 1개 뺀 구멍, 등가 지름 3 ≤ 8) → 형상 meta.diag·정보 MESH_INPUT_DIAG,
    mesh.npz 바이트 = 진단 끈 결과와 같음(보고만), diag.enabled false → 키 없음, 설정 해시(hash_view)에서 diag 절 제외."""
    ids, X, e, c = smr.grid(10, 8, 3.0, 3.0)
    keep = np.ones(e.size, bool)
    keep[4 * 8 + 3] = False                                             # 가운데 요소 1개
    smr.write(tmp_path / "in" / "h.rad", smr.begin("mm") + smr.part(1, "chassis") + smr.nodes(ids, X)
              + smr.shells(1, e[keep], c[keep]) + ["/END"])
    outs = {}
    for k, cfg in (("on", _cfg()), ("off", _cfg(mesh_input={"diag": {"enabled": False}}))):
        od = tmp_path / k
        _m, meta = mi.read_shape_mesh(str(tmp_path / "in"), "h.rad", 1, PROPS, cfg, out_dir=str(od))
        outs[k] = (meta, _sha(od / mg.MESH_NPZ))
    on, off = outs["on"][0], outs["off"][0]
    assert on["diag"] == {"holes_n": 1, "holes_small_n": 1, "islands_n": 0, "free_loops_n": 2}
    assert any(i["code"] == "MESH_INPUT_DIAG" and "작은 구멍 1" in i["message"] for i in on["infos"])
    assert "diag" not in off and not any(i["code"] == "MESH_INPUT_DIAG" for i in off["infos"])
    assert outs["on"][1] == outs["off"][1]
    assert mi.hash_view(_cfg()) == mi.hash_view(_cfg(mesh_input={"diag": {"enabled": False}}))
    assert "diag" not in mi.hash_view(_cfg()) and mi.hash_view(_cfg()) != mi.hash_view(_cfg(mesh_input={"max_mb": 10}))
