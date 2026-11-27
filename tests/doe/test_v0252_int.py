"""v0.25.2 통합 INT-10·11(계약 esl_tstar_manual_jig_force.md §15.4 — 독립 검증 결함·현장 위험 보정).

- INT-11 구멍 위치 어긋남(`grid_map.rim_shift`): 판이 이어져 있으면 band 잡기는 위치가 어긋나도 "잡힘" 이라(검증: 면내 이동에서 잡힌 묶음의
  중심 이동 중앙값 < 0.5 mm) Case 체결부 구멍 가장자리 ↔ 형상 자유 변으로 본다. 정렬 검사(SHAPE_MISALIGNED — frame 원점 차 ≤ align_tol·L)
  안의 이동만 대상(밖은 정렬 검사가 형상을 뺌).
- INT-10 최적(산출물) = 참고(jig_ref) 아닌 최상위, 모두 참고면 최상위 참고 + BEST_IS_REF, ranking.csv·보고서 "참고" 열(강제 부여 스냅샷만).
"""
from __future__ import annotations

import csv
import io
import json
import os

import numpy as np
import pytest

import synth_jig_grid as G
from esl.doe import rank as rk
from esl.doe import scenario as sc
from esl.mech import grid_map as gm

TOL = 0.5 * 3.0                                   # frame_shift_warn × cell_mm(설정 기본) — rim_shift 임계


def _holed(h=2.5, *, bead=None, node_base=1, shift=(0.0, 0.0, 0.0), r=4.0):
    m = G.holes(G.plate(h, bead=bead, node_base=node_base), range(len(G.BOLTS)), r=r)
    m["x0"] = np.asarray(m["x0"], dtype=np.float64) + np.asarray(shift, dtype=np.float64)
    return m


def _skel(A):
    P = G.tie_idx(A)
    td = np.zeros((P.size, 3, 3))
    td[:, 0] = (0.0, 1.0, 0.0)
    return gm.tie_skeleton(A, P, td, np.ones(P.size, np.int64), {"part": np.zeros((1, P.size, 3))})


def _rim(A, skel):
    return np.isin(skel["idx"], gm.free_edge_nodes(A))


N_PLATE = (0.0, 1.0, 0.0)                         # 판 평면 y = 0


# ------------------------------------------------------------------ INT-11 순수 함수
def test_int11_free_edge_nodes_and_rim_shift_pure():
    A = _holed()
    fe = gm.free_edge_nodes(A)
    X = A["x0"][fe]
    on_out = (np.isclose(X[:, 0], 0) | np.isclose(X[:, 0], G.LX) | np.isclose(X[:, 2], 0) | np.isclose(X[:, 2], G.LZ))
    near_hole = np.min([np.hypot(X[:, 0] - bx, X[:, 2] - bz) for bx, bz in G.BOLTS], axis=0) <= 6.0
    assert np.all(on_out | near_hole) and near_hole.sum() >= 6 * 4           # 바깥 둘레 + 구멍 6곳 가장자리
    sk = _skel(A)
    rim = _rim(A, sk)
    assert rim.any()
    same = gm.rim_shift(sk, rim, A["x0"], fe, N_PLATE)
    assert same["mm"] == 0.0 and same["n"] == 6                              # 항등 = 0
    for d in (3.0, 5.0):                                                      # 같은 형상을 면내 d mm 옮김 → 그 방향
        S = _holed(shift=(d, 0.0, 0.0))
        r = gm.rim_shift(sk, rim, S["x0"], gm.free_edge_nodes(S), N_PLATE)
        assert r["n"] == 6 and r["mm"] > TOL and r["vec"][0] > 0 and abs(r["vec"][2]) < 0.2 * r["vec"][0], (d, r)
    S = _holed(shift=(0.0, 0.0, -4.0))
    r = gm.rim_shift(sk, rim, S["x0"], gm.free_edge_nodes(S), N_PLATE)
    assert r["mm"] > TOL and r["vec"][2] < 0
    rng = np.random.default_rng(1)                                            # 메시 잡음(면내 ±0.3 mm 흔듦) = 임계 아래
    J = A["x0"].copy()
    J[:, [0, 2]] += rng.uniform(-0.3, 0.3, (J.shape[0], 2))
    assert gm.rim_shift(sk, rim, J, fe, N_PLATE)["mm"] < TOL
    full = G.plate(2.5)                                                       # 형상에 구멍 없음(메워짐) = 비교 묶음 0 → None(거짓 경보 없음)
    assert gm.rim_shift(sk, rim, full["x0"], gm.free_edge_nodes(full), N_PLATE) is None
    assert gm.rim_shift(sk, np.zeros(rim.size, bool), A["x0"], fe, N_PLATE) is None    # Case 에 구멍 가장자리 없음(와셔 면만)
    nofill = G.plate(2.5)                                                     # Case 구멍 없는 판(합성 세계 기본) = 해당 없음
    sk0 = _skel(nofill)
    assert gm.rim_shift(sk0, _rim(nofill, sk0), nofill["x0"], gm.free_edge_nodes(nofill), N_PLATE) is None


def test_int11_alignment_check_scope():
    """정렬 검사 범위(원인 확인): 300 mm 면내 이동 = SHAPE_MISALIGNED(frame 원점 차 > align_tol·L), 정렬 허용 안의 이동만 rim_shift 대상."""
    from esl.doe import DEFAULTS
    tol, deg = DEFAULTS["compare"]["align_tol"], DEFAULTS["compare"]["align_deg"]
    A = _holed()
    fA = sc.shape_frame(A, None)
    far = sc.align_check(fA, sc.shape_frame(_holed(shift=(300.0, 0.0, 0.0)), fA.get("axis_ref")), tol, deg)
    near = sc.align_check(fA, sc.shape_frame(_holed(shift=(4.0, 0.0, 0.0)), fA.get("axis_ref")), tol, deg)
    assert far["ok"] is False and near["ok"] is True


# ------------------------------------------------------------------ INT-10 순수 함수
def test_int10_best_order():
    R = [{"id": "d002", "jig_ref": True}, {"id": "d001"}, {"id": "d003", "jig_ref": True}, {"id": "d004"}]
    assert rk.best_order(R) == (["d001", "d004", "d002", "d003"], False)
    assert rk.best_order([{"id": "a", "jig_ref": True}, {"id": "b", "jig_ref": True}]) == (["a", "b"], True)
    assert rk.best_order([{"id": "a"}, {"id": "b"}]) == (["a", "b"], False)          # jig_ref 없음 = 순위 순 그대로
    assert rk.best_order([]) == ([], False)


# ------------------------------------------------------------------ 스터디(④ 격자 지그, 강제 부여 스냅샷)
def _world(root, shapes, force=True):
    """Case A = 구멍 6곳(r 4 — 와셔 면 r 9 안쪽) 판. cmp_world 의 A = G.plate(hA) 를 이 메시로 바꿔 부른다."""
    orig = G.plate
    A_mesh = _holed(2.5)
    G.plate = lambda h=5.0, **kw: A_mesh if h == 2.5 and not kw else orig(h, **kw)
    try:
        doe, out, _A = G.cmp_world(str(root), hA=2.5, shapes=shapes, rank=G.rank_snap(grid=True, force=force))
    finally:
        G.plate = orig
    G.run_cmp(doe, out)
    return out


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def _codes(ws):
    return [w.get("code") if isinstance(w, dict) else str(w).split(":", 1)[0] for w in ws or []]


SHIFTED = ("d002", {"mesh": _holed(2.5, bead=(60.0, 90.0, 4.0), node_base=200001, shift=(4.0, 0.0, 0.0))})
SAME = ("d001", {"mesh": _holed(2.5, node_base=100001)})


@pytest.fixture(scope="module")
def mixed(tmp_path_factory):
    return _world(tmp_path_factory.mktemp("int_mixed"), (SAME, SHIFTED))


def test_int11_shift_warning_ref_and_int10_best(mixed):
    out = mixed
    t1 = _j(out, "run", "designs", "d001", "jig_grid.json")["map"]["tie"]
    t2 = _j(out, "run", "designs", "d002", "jig_grid.json")
    tie2 = t2["map"]["tie"]
    assert t1["shift"]["over"] is False and t1["shift"]["mm"] < TOL and t1["ref"] is False
    assert tie2["shift"]["over"] is True and tie2["shift"]["mm"] > TOL and tie2["shift"]["vec"][0] > 0 and tie2["ref"] is True
    assert tie2["shift"]["tol_mm"] == pytest.approx(TOL)
    assert "JIG_GRID_TIE_SHIFT" in _codes(t2["warnings"])
    res = _j(out, "post", "result.json")
    assert "JIG_GRID_TIE_SHIFT" in _codes(res["warnings"]) and "JIG_GRID_TIE_HINT" in _codes(res["warnings"])
    rows = {x["id"]: x for x in res["ranking"]}
    assert rows["d002"].get("jig_ref") is True and "jig_ref" not in rows["d001"] and res["n_ref"] == 1
    # INT-10: 순위·번호 불변, 최적 = 참고 아닌 최상위
    order, all_ref = rk.best_order(res["ranking"])
    assert not all_ref and res["best"]["id"] == order[0] == "d001"
    assert [x["rank"] for x in res["ranking"]] == sorted(x["rank"] for x in res["ranking"])
    assert "BEST_IS_REF" not in _codes(res["warnings"])
    html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
    assert "<th>참고</th>" in html
    assert res["ranking"][0]["id"] == "d002" and res["ranking"][0]["rank"] == 1           # 비드 형상(참고)이 1위 — 순위 그대로
    assert "순위 1위 d002 는 지그 순위가 참고용" in html                                    # 최적에서 건너뛴 안내
    # 요약 카드(맨 위) 도 result.best — 참고 1위(d002) 가 아니라 d001, 안내 줄이 카드 바로 뒤에도 있음
    head = html.split("<h2", 1)[0]
    assert res["best"]["id"] == "d001" and "d001" in head and "순위 1위 d002 는 지그 순위가 참고용" in head
    assert html.count("순위 1위 d002 는 지그 순위가 참고용") >= 2
    with open(os.path.join(out, "post", "ranking.csv"), encoding="utf-8") as fh:
        rr = list(csv.DictReader(io.StringIO(fh.read())))
    by = {r["id"]: r for r in rr}
    assert list(rr[0])[-1] == "jig_ref" and by["d002"]["jig_ref"] == "True" and by["d001"]["jig_ref"] == "False"
    assert by["d000"]["jig_ref"] == ""


def test_int10_best_is_ref_when_all_ref(tmp_path):
    out = _world(tmp_path, (SHIFTED,))
    res = _j(out, "post", "result.json")
    assert [x["id"] for x in res["ranking"]] == ["d002"] and res["ranking"][0]["jig_ref"] is True
    assert res["best"]["id"] == "d002" and "BEST_IS_REF" in _codes(res["warnings"])


def test_int10_11_old_snapshot_no_new_columns(tmp_path):
    """옛 스냅샷(tie_force 없음) = 구멍 위치 진단·참고 열·최적 규칙 없음(결과 바이트 불변은 골든 test_v0252_golden)."""
    out = _world(tmp_path, (SAME, SHIFTED), force=False)
    tie2 = _j(out, "run", "designs", "d002", "jig_grid.json")["map"]["tie"]
    assert "shift" not in tie2 and "ref" not in tie2
    res = _j(out, "post", "result.json")
    assert all("jig_ref" not in x for x in res["ranking"]) and res["best"]["id"] == res["ranking"][0]["id"]
    assert "JIG_GRID_TIE_SHIFT" not in _codes(res["warnings"])
    head = open(os.path.join(out, "post", "ranking.csv"), encoding="utf-8").readline()
    assert "jig_ref" not in head
    assert "<th>참고</th>" not in open(os.path.join(out, "report.html"), encoding="utf-8").read()
