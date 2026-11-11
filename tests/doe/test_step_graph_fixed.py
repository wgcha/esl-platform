"""V-SG-4 A 고정점 → B 이전(esl_step_graph.md SG-D-12~15, SG-D-13 개정 2026-11-12): 구멍 특징 frame 일치 = xyz_nearest(구멍 없는
RBE2 패드 포함), 강체 맞춤 = xyz_fitted, 불일치 = 정규화 frame + B 구멍 스냅, 둘 다 실패 = none. 클러스터마다 검증·resid_mm.
B = H6 픽스처 메시(사다리 메시 대리 — 같은 좌표계 시험은 메시 출처와 무관), 결정적 바이트. V-SG-4h·4i = Verifier v0.18.0 탐침
(p1: 4.5 mm 이동·1.9° 회전이 조용히 엉뚱한 노드를 고정, p2: #63 같은 추가 형상)을 영구 시험으로."""
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
    fc = doc["frame_check"]
    assert fc["ok"] and doc["method"] == "xyz_nearest" and fc["fit"] is None
    assert fc["method"] == "holes" and fc["n_a_holes"] == fc["n_b_holes"] == fc["n_matched"] == 78
    assert fc["n_req"] == 39 and fc["resid_med_mm"] <= 1e-9 and fc["resid_max_mm"] <= 1e-9
    assert len(doc["matches"]) == len(groups) and not doc["unmatched"]
    assert set(doc["node_id"]) == set((np.asarray(fx["fixed"]) + 1).tolist())     # 고정 구멍 노드 전부
    assert all(m["d_max_mm"] <= 1e-9 and m["resid_mm"] <= 1e-9 for m in doc["matches"])
    assert all(m["feature"] == "hole" and m["via"] == "xyz" for m in doc["matches"])
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
    assert doc["matches"][-1]["feature"] == "pad" and doc["matches"][-1]["resid_mm"] <= 1e-9
    cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"fixed_transfer": {"mode": "hole"}}}}})
    dh = _xfer(mesh, a_fx, _target(mesh), cfg=cfg)
    assert dh["method"] == "ab_hole_snap" and dh["mode"] == "hole"
    assert len(dh["unmatched"]) == 1 and dh["unmatched"][0]["a_label"].endswith(f"#{len(groups)}")
    assert any(m["code"] == "FIXED_XFER_UNMATCHED" for m in sg.xfer_messages(dh))


def test_extra_geometry_frame_ok(H6, tmp_path):
    """(a'') A bbox 밖 추가 형상 → 구멍 특징 판정 ok(영역 있든 없든 — bbox 중심은 정보만, 영역 없으면 더 흔들림)."""
    mesh, fx, groups = H6
    big = ssg.add_extra(mesh)
    rm, info = sg.region_mask(big, mesh["x0"], CFG, H)
    n0 = mesh["elem_type"].size
    assert info["rule"] == "a_bbox" and rm[:n0].all()
    c = sg.centroids(big)[n0:]
    assert not rm[n0:][c[:, 0] > mesh["x0"][:, 0].max() + 2 * H].any()      # pad(2h) 밖 추가 형상 = 영역 밖
    assert info["n_out"] > 0.5 * (big["elem_type"].size - n0)
    fc = sg.frame_check(mesh, big, rm, CFG, h=H)
    assert fc["ok"] and fc["resid_med_mm"] <= 1e-9 and fc["d_origin_mm"] <= 2 * H          # bbox 차 = pad 띠만큼(정보)
    f0 = sg.frame_check(mesh, big, None, CFG, h=H)
    assert f0["ok"] and f0["d_origin_mm"] > 2 * H                              # 추가 형상이 bbox 를 흔들어도 구멍 판정은 그대로
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
    assert not (doc["frame_check"]["fit"] or {}).get("ok")                    # 1.03 배 = 강체 맞춤 불가
    assert all(m["resid_mm"] is not None and m["via"] == "hole" for m in doc["matches"])
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


# ---------------------------------------------------------------- V-SG-4h·4i (Verifier 탐침 p1·p2 → 영구 시험)
def _rigid(mesh, deg=0.0, t=(0.0, 0.0, 0.0), axis="z"):
    """B = A 를 bbox 중심 기준 회전 + 이동(탐침 p1 과 같은 변환) → (B 메시, A 점 → 참 B 위치 함수)."""
    Y = np.asarray(mesh["x0"], np.float64)
    c0 = (Y.min(0) + Y.max(0)) / 2
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    R = {"z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]), "x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]])}[axis]
    m = dict(mesh)
    m["x0"] = (Y - c0) @ R.T + c0 + np.asarray(t)
    return m, (lambda P: (np.asarray(P) - c0) @ R.T + c0 + np.asarray(t))


PROBE_P1 = [("identity", 0.0, (0, 0, 0), "z"), ("shift4.5", 0.0, (4.5, 0, 0), "z"), ("diag4.4", 0.0, (3.1, 3.1, 0), "z"),
            ("rot1.9", 1.9, (0, 0, 0), "z"), ("rot1.9+shift3", 1.9, (3, 0, 0), "z"), ("rot1.9x", 1.9, (0, 0, 0), "x"),
            ("shift6", 0.0, (6, 0, 0), "z"), ("normal2", 0.0, (0, 0, 2.0), "z")]


@pytest.mark.parametrize("name,deg,t,axis", PROBE_P1, ids=[p[0] for p in PROBE_P1])
def test_probe_p1_never_silent(H6, tmp_path, name, deg, t, axis):
    """V-SG-4h (SG-D-13 개정 (1)): 판 위에서는 A 점 h 안에 늘 B 노드가 있어 ≤ h 검사만으로는 엉뚱한 노드를 고정했다(4.5 mm
    이동 = 8/8 '대응' 인데 6 mm 어긋남, 1.9° 회전 = 14~16 mm). 이제 모든 클러스터가 (a) 맞춤 뒤 참 위치 ≤ h/4 이거나 (b) 구멍
    스냅으로 정확한 고리 노드이고, 모든 대응에 resid_mm 가 있다. 패드(구멍 없음)도 맞춤으로 정확히 옮긴다."""
    mesh, fx, groups = H6
    X = np.asarray(mesh["x0"])
    c = np.argmin(np.linalg.norm(X[:, :2] - np.array([300.0, 300.0]), axis=1))
    pad = np.argsort(np.linalg.norm(X - X[c], axis=1))[:6]
    allg = groups + [pad]
    a_fx = _afixed(tmp_path, mesh, allg)
    b, truth = _rigid(mesh, deg, t, axis)
    doc = _xfer(mesh, a_fx, _target(b))
    fc = doc["frame_check"]
    assert doc["method"] in ("xyz_nearest", "xyz_fitted", "ab_hole_snap")
    assert (doc["method"] == "xyz_nearest") == (name == "identity")
    assert all(m["resid_mm"] is not None for m in doc["matches"])
    from scipy.spatial import cKDTree
    Bx = np.asarray(b["x0"])
    idx = {int(v): i for i, v in enumerate(np.asarray(b["node_id"]))}
    tr = cKDTree(truth(X[np.concatenate(allg)]))
    err, _ = tr.query(Bx[[idx[n] for n in doc["node_id"]]])
    if doc["method"] == "ab_hole_snap":                     # 구멍 스냅 = 고리 노드 정확(패드는 UNMATCHED)
        assert err.max() <= 1e-6 and [u["a_label"] for u in doc["unmatched"]] == [f"RBE2#{len(groups)}"]
    else:
        assert err.max() <= H / 4 and len(doc["matches"]) == len(allg) and not doc["unmatched"]
        assert all(m["resid_mm"] <= H / 4 for m in doc["matches"])
        if doc["method"] == "xyz_fitted":
            assert not fc["ok"] and fc["fit"]["ok"] and fc["fit"]["resid_med_mm"] <= H / 4
            assert abs(fc["fit"]["rot_deg"] - deg) < 0.01
    # 각 A 클러스터(구멍)의 노드가 모두 옮겨짐(참 위치 그대로)
    want = {int(b["node_id"][i]) for g in groups for i in g}
    assert want <= set(doc["node_id"])


def test_probe_p1_xyz_forced_reports_unmatched(H6, tmp_path):
    """mode xyz 강제 + 맞춤 불가 B(1.03 배·5°·10 mm) → 구멍형 클러스터는 B 구멍 중심 검증에서 떨어져 UNMATCHED{resid}(조용한
    '대응' 없음, 구멍 스냅 대체 없음)."""
    mesh, fx, groups = H6
    cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"fixed_transfer": {"mode": "xyz"}}}}})
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(_xform(mesh)), cfg=cfg)
    assert not doc["frame_check"]["ok"] and not (doc["frame_check"]["fit"] or {}).get("ok")
    assert doc["method"] == "none" and doc["reason"] == "NO_MATCH" and len(doc["unmatched"]) == len(groups)
    assert all(u["resid_mm"] is not None and u["resid_mm"] > H / 2 for u in doc["unmatched"])
    msgs = sg.xfer_messages(doc)
    assert sum(m["code"] == "FIXED_XFER_UNMATCHED" for m in msgs) == len(groups)


def test_cluster_fallback_hole_snap_then_unmatched(H6, tmp_path):
    """SG-D-13 개정 (2): frame 일치여도 B 구멍이 없는 구멍형 클러스터(평가 영역 밖 탭 구멍) → 구멍 스냅 → 실패 = UNMATCHED{label,
    d_mm}; 나머지는 xyz. 패드가 판정과 어긋나면(2 mm 떨어진 A 고리) 구멍 스냅으로 정확한 고리."""
    mesh, fx, groups = H6
    X = np.asarray(mesh["x0"])
    region = sg.centroids(mesh)[:, 0] >= 0.0                    # 탭 구멍(-10, 335) 영역 밖
    tab = [k for k, g in enumerate(groups) if X[g, 0].mean() < 0][0]
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(mesh), region=region)
    assert doc["frame_check"]["ok"] and doc["method"] == "xyz_nearest"
    assert [u["a_label"] for u in doc["unmatched"]] == [f"RBE2#{tab}"] and doc["unmatched"][0]["d_mm"] > 10.0
    assert len(doc["matches"]) == len(groups) - 1
    assert {"code": "FIXED_XFER_UNMATCHED", "label": f"RBE2#{tab}",
            "d_mm": round(doc["unmatched"][0]["d_mm"], 3)} in sg.xfer_messages(doc)
    # A part 의 구멍 1개(+ 그 고리 클러스터)가 B 보다 2 mm 옆(> h/2) — 구멍 판정은 이상치 1개 제외로 ok, 그 구멍형 클러스터는 B 구멍
    # 중심 검증에서 떨어져 구멍 스냅(정확한 B 고리)으로, 나머지는 xyz
    am = dict(mesh)
    am["x0"] = X.copy()
    am["x0"][groups[0], 0] += 2.0
    d = tmp_path / "moved"
    sd.write_fixed(str(d), am, [list(map(int, g)) for g in groups])
    doc2 = _xfer(am, pio.read_fixed(str(d)), _target(mesh))
    fc = doc2["frame_check"]
    assert fc["ok"] and fc["resid_max_mm"] <= 1e-9 and fc["n_matched"] == 78        # 이상치 1개 제외
    m0 = doc2["matches"][0]
    assert doc2["method"] == "xyz_nearest" and m0["via"] == "hole" and m0["feature"] == "hole"
    assert abs(m0["resid_mm"] - 2.0) < 0.1
    assert set(mesh["node_id"][groups[0]].tolist()) <= set(doc2["node_id"])
    assert all(m["via"] == "xyz" and m["resid_mm"] <= 1e-9 for m in doc2["matches"][1:])


def test_probe_p2_extra_geometry_63_like(H6, tmp_path):
    """V-SG-4i (탐침 p2): #63 같은 추가 형상(오른쪽 끝 벽 z +17.5 → A xy 안쪽 300 mm 윗판) — 영역 a_bbox 가 일부(pad 띠)를 남겨
    bbox 중심이 ≈ 3 mm 흔들려도 구멍 특징 판정 ok·잔차 0, xyz_nearest 8/8, 추가 형상 노드 고정 0."""
    mesh, fx, groups = H6
    X = np.asarray(mesh["x0"], float)
    C = np.asarray(mesh["conn"], np.int64)
    xm = X[:, 0].max()
    edge = np.flatnonzero(np.abs(X[:, 0] - xm) < 1e-6)
    edge = edge[np.argsort(X[edge, 1])]
    zt = X[:, 2].max() + 17.5
    cols, newX, base, k = [edge], [], X.shape[0], 0
    for j in range(1, 13):
        P = X[edge].copy()
        P[:, 2] = X[edge, 2] + (zt - X[edge, 2]) * j / 12
        newX.append(P)
        cols.append(base + k + np.arange(edge.size))
        k += edge.size
    for i in range(1, 101):
        P = newX[11].copy()
        P[:, 0] = xm - 300.0 * i / 100
        newX.append(P)
        cols.append(base + k + np.arange(edge.size))
        k += edge.size
    quads = [[a[t], b[t], b[t + 1], a[t + 1]] for a, b in zip(cols, cols[1:]) for t in range(edge.size - 1)]
    big = ssg.esl_mesh(np.concatenate([X] + newX), np.concatenate([C, np.asarray(quads, np.int64)]))
    n0, N0 = C.shape[0], X.shape[0]
    big["node_id"][:N0] = mesh["node_id"]
    big["node_id"][N0:] = mesh["node_id"].max() + 1 + np.arange(big["x0"].shape[0] - N0)
    rm, info = sg.region_mask(big, X, CFG, H)
    assert info["rule"] == "a_bbox" and rm[:n0].all() and rm[n0:].any()     # 추가 형상 일부가 영역에 남음
    fc = sg.frame_check(mesh, big, rm, CFG, h=H)
    assert fc["d_origin_mm"] > 2.0                                            # bbox 중심 흔들림(정보만)
    assert fc["ok"] and fc["n_matched"] == fc["n_a_holes"] == 78 and fc["resid_max_mm"] <= 1e-9
    a_fx = _afixed(tmp_path, mesh, groups)
    doc = _xfer(mesh, a_fx, _target(big), region=rm)
    idx = {int(v): i for i, v in enumerate(big["node_id"])}
    assert doc["method"] == "xyz_nearest" and len(doc["matches"]) == len(groups) and not doc["unmatched"]
    assert not any(idx[n] >= N0 for n in doc["node_id"])
    assert all(m["resid_mm"] <= 1e-9 for m in doc["matches"])


def test_frame_check_few_holes_not_ok(H6):
    """대응 수 < frame_min_holes → 잔차 0 이어도 판정·맞춤 모두 거짓(→ 구멍 스냅)."""
    mesh, fx, groups = H6
    cfg = settings({"bead_doe": {"enabled": True, "select": {"step_graph": {"fixed_transfer": {"frame_min_holes": 100}}}}})
    fc = sg.frame_check(mesh, mesh, None, cfg, h=H)
    assert fc["n_req"] == 100 and fc["n_matched"] == 78 and not fc["ok"] and not fc["fit"]["ok"]
