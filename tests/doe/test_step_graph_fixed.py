"""V-SG-4 A 고정점 → B 이전(esl_step_graph.md SG-D-12~15): frame 일치 = xyz_nearest(구멍 없는 RBE2 패드 포함), 불일치 = 정규화
frame + B 구멍 스냅, 둘 다 실패 = none. B = H6 픽스처 메시(사다리 메시 대리 — 같은 좌표계 시험은 메시 출처와 무관), 결정적 바이트."""
import json
import math

import numpy as np
import pytest
import synth_doe as sd
import synth_step_graph as ssg

from esl.doe import bead_graph as bgr
from esl.doe import bead_select as bs
from esl.doe import paicad_io as pio
from esl.doe import settings
from esl.doe import step_graph as sg
from esl.opt import target as tg

CFG = settings({"bead_doe": {"enabled": True}})
H = 3.0


@pytest.fixture(scope="module")
def H6():
    mesh, fx = ssg.h6_fixture_mesh()
    return mesh, fx, ssg.h6_clusters(mesh, fx)


def _target(mesh):
    arrays, meta = tg.build_template(mesh, None)
    return tg.template_target(arrays, meta)


def _afixed(tmp_path, mesh, groups, name="a_fixed"):
    d = tmp_path / name
    sd.write_fixed(str(d), mesh, [list(map(int, g)) for g in groups])
    return pio.read_fixed(str(d))


def _xfer(a_mesh, a_fx, t_b, cfg=CFG, region=None, reason=None):
    from esl.library import normalize as nz
    fa = nz.frame(a_mesh["x0"], None, a_mesh["conn"], a_mesh["elem_type"])
    return sg.fixed_transfer(a_fx, fa, t_b, cfg, a_mesh=a_mesh, region=region, h=H, hole_min_perimeter=5.0,
                             snap_default=10.0, reason=reason)


def _xform(mesh, s=1.03, deg=5.0, t=(10.0, 10.0, 0.0)):
    X = np.asarray(mesh["x0"], np.float64)
    c, sn = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    R = np.array([[c, -sn, 0], [sn, c, 0], [0, 0, 1]])
    m = dict(mesh)
    m["x0"] = (X * s) @ R.T + np.asarray(t)
    return m


def test_same_frame_xyz_all_holes(H6, tmp_path):
    mesh, fx, groups = H6
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(mesh))
    assert doc["frame_check"]["ok"] and doc["method"] == "xyz_nearest"
    assert len(doc["matches"]) == len(groups) and not doc["unmatched"]
    assert set(doc["node_id"]) == set((np.asarray(fx["fixed"]) + 1).tolist())     # 고정 구멍 노드 전부
    assert all(m["d_max_mm"] <= 1e-9 for m in doc["matches"])
    assert doc["elems"]["q"] or doc["elems"]["t"]
    assert sg.xfer_messages(doc) == []


def test_rbe2_pad_xyz_vs_hole(H6, tmp_path):
    """(a') 구멍 없는 RBE2 패드(평판 안쪽 노드 묶음) → 1순위 이전, (g) mode hole 강제 → 패드는 UNMATCHED."""
    mesh, fx, groups = H6
    X = mesh["x0"]
    c = np.argmin(np.linalg.norm(X[:, :2] - np.array([300.0, 300.0]), axis=1))
    pad = np.argsort(np.linalg.norm(X - X[c], axis=1))[:6]
    a_fx = _afixed(tmp_path, mesh, groups + [pad])
    doc = _xfer(mesh, a_fx, _target(mesh))
    assert doc["method"] == "xyz_nearest" and len(doc["matches"]) == len(groups) + 1
    assert set((mesh["node_id"][pad]).tolist()) <= set(doc["node_id"])
    cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"fixed_transfer": {"mode": "hole"}}}}})
    dh = _xfer(mesh, a_fx, _target(mesh), cfg=cfg)
    assert dh["method"] == "ab_hole_snap" and dh["mode"] == "hole"
    assert len(dh["unmatched"]) == 1 and dh["unmatched"][0]["a_label"].endswith(f"#{len(groups)}")
    assert any(m["code"] == "FIXED_XFER_UNMATCHED" for m in sg.xfer_messages(dh))


def test_extra_geometry_frame_ok(H6, tmp_path):
    """(a'') A bbox 밖 추가 형상(평가 영역 기준 frame) → 판정 ok 유지, 영역 없으면 원점이 흔들림."""
    mesh, fx, groups = H6
    big = ssg.add_extra(mesh)
    rm, info = sg.region_mask(big, mesh["x0"], CFG, H)
    n0 = mesh["elem_type"].size
    assert info["rule"] == "a_bbox" and rm[:n0].all()
    c = sg.centroids(big)[n0:]
    assert not rm[n0:][c[:, 0] > mesh["x0"][:, 0].max() + 2 * H].any()      # pad(2h) 밖 추가 형상 = 영역 밖
    assert info["n_out"] > 0.5 * (big["elem_type"].size - n0)
    fc = sg.frame_check(mesh, big, rm, CFG)
    assert fc["ok"] and fc["d_origin_mm"] <= 2 * H                            # pad 띠만큼
    assert not sg.frame_check(mesh, big, None, CFG)["ok"]                     # 영역 없으면 추가 형상이 판정을 흔듦
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(big), region=rm)
    assert doc["method"] == "xyz_nearest" and len(doc["matches"]) == len(groups)


def test_moved_b_hole_snap(H6, tmp_path):
    """(b) B 1.03 배·회전 5°·이동 10 mm → frame 불일치 → ab_hole_snap, 같은 구멍 ≥ 95 %; (c) B 에 없는 자리 → UNMATCHED."""
    mesh, fx, groups = H6
    b = _xform(mesh)
    t_b = _target(b)
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, t_b)
    assert not doc["frame_check"]["ok"] and doc["method"] == "ab_hole_snap"
    ok = 0
    for g, m in zip(groups, doc["matches"]):
        ok += set(mesh["node_id"][g].tolist()) <= set(doc["node_id"])
    assert ok >= 0.95 * len(groups) and len(doc["matches"]) >= 0.95 * len(groups)
    X = mesh["x0"]
    far = np.argsort(np.linalg.norm(X[:, :2] - np.array([600.0, 330.0]), axis=1))[:4]      # 구멍 없는 판 가운데
    a2 = _afixed(tmp_path, mesh, groups + [far], "a2")
    d2 = _xfer(mesh, a2, t_b)
    assert [u["a_label"] for u in d2["unmatched"]] == [f"RBE2#{len(groups)}"]
    assert d2["unmatched"][0]["d_mm"] > 10.0


def test_none_and_no_match(H6, tmp_path):
    mesh, fx, groups = H6
    t = _target(mesh)
    d = _xfer(mesh, None, t, reason="A_CASE_MISSING")                  # (d)
    assert d["method"] == "none" and d["reason"] == "A_CASE_MISSING" and d["elems"] == {"q": [], "t": []}
    assert sg.xfer_messages(d) == [{"code": "FIXED_XFER_NONE", "reason": "A_CASE_MISSING"}]
    cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"fixed_transfer": {"mode": "xyz"}}}}})
    far = _xform(mesh, s=1.0, deg=0.0, t=(100.0, 0.0, 0.0))
    a_fx = _afixed(tmp_path, mesh, groups)
    d2 = _xfer(mesh, a_fx, _target(far), cfg=cfg)                       # (d') 두 방법 모두 0개(xyz 강제 + 먼 B)
    assert d2["method"] == "none" and d2["reason"] == "NO_MATCH" and not d2["node_id"]
    assert sg.xfer_messages(d2)[0] == {"code": "FIXED_XFER_NONE", "reason": "NO_MATCH"}
    assert sg.xfer_messages(None, disabled=True) == [{"code": "FIXED_XFER_NONE", "reason": "DISABLED"}]


def test_deterministic_bytes(H6, tmp_path):
    """(f) 같은 입력 2회 = 같은 바이트(키 정렬·1e-3), 내부 키 _groups 는 파일에 없음."""
    mesh, fx, groups = H6
    a_fx = _afixed(tmp_path, mesh, groups)
    p1, p2 = tmp_path / "x1.json", tmp_path / "x2.json"
    s1 = sg.write_transfer(str(p1), _xfer(mesh, a_fx, _target(mesh)))
    s2 = sg.write_transfer(str(p2), _xfer(mesh, a_fx, _target(mesh)))
    assert s1 == s2 and p1.read_bytes() == p2.read_bytes()
    doc = json.loads(p1.read_bytes())
    assert doc["schema"] == sg.XFER_SCHEMA and "_groups" not in doc
    assert set(doc) >= {"method", "mode", "frame_check", "tol_mm", "snap_mm", "frame_a_sha", "frame_b_sha", "matches",
                        "unmatched", "node_id", "elems"}


def test_seed_edit_hold(H6, tmp_path):
    """(e) seed fixed_user 를 지우면 고정 없음(ψ = 1), 다시 칠하면 고정 마스크 = 이전 고정 노드 ⊇."""
    from _bg_util import prepared
    mesh, g, lab, fixed, _d = prepared("h6")
    _m, fx, groups = H6
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(mesh))
    sel, _sym, _w = bgr.auto_seed(g, lab, CFG)
    sel["beads"] = sel["beads"][:1]
    for fu, want in ((doc["elems"], True), ({"q": [], "t": []}, False)):
        s = dict(sel, fixed_user=fu)
        norm, _sha = bgr.normalize_v2(s, g, CFG, labels=lab, mesh=mesh)
        D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=())
        assert bool(np.asarray(D.fixed_mask).any()) is want
        if want:
            idx = np.searchsorted(mesh["node_id"], doc["node_id"])
            assert np.asarray(D.fixed_mask)[idx].all()
    assert bs.selection_sha256(norm)


def test_seed_fixed_user_rules():
    """SG-D-14b: 2개 이상 공유 요소, 노드 1개 묶음 = 그 노드 요소, 떨어진 묶음 = 그 노드들의 요소."""
    m = sd.plate(nx=4, ny=3, Lx=40.0, Lz=30.0)
    es = sg.seed_fixed_user(m, [np.array([0])])
    assert sum(b - a + 1 for a, b in es["q"]) == 1                     # 모서리 노드 = 요소 1개
    es2 = sg.seed_fixed_user(m, [np.array([0, 1])])
    assert sum(b - a + 1 for a, b in es2["q"]) == 1                    # 공유 요소 1개
    es3 = sg.seed_fixed_user(m, [np.array([0, 19])])                   # 떨어진 두 노드 → 각 요소
    assert sum(b - a + 1 for a, b in es3["q"]) >= 2
