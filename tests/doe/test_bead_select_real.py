"""v0.16.1 실제 Ch/R 사진 사례(select 완화 — esl_select_relax.md §5.2~5.4) 합성 시험.

합성 메시 = ``synth_bead.real_case(kind)``(높이장 구조 4각 h 2 mm, 사면 60°, 보스 = 바닥 위 원뿔대, 구멍 = 요소 제거 계단 경계).
1 network(사다리 T 교차 4 + L), 2 boss_field(넓은 돌출 평판 + 버링 구멍 보스 12), 3 edge_slot(판 가장자리 비드 + 사각 슬롯·컷아웃),
4 ring(고리형 비드 3 — 안쪽 둔덕 Ø60·Ø24·Ø14), 5 edge_boss(개구 경계에 반쯤 걸친 보스), 6 channel(U·Ω 채널).
④ defeature 사례 7(보스 남김·보스 구멍만 메움)은 ``tests/geom/test_defeature.py``."""
import time

import numpy as np
import pytest

import synth_bead as sb
from esl.doe import bead_select as bs
from esl.doe import settings

CFG = settings({"bead_doe": {"enabled": True}})
H = 2.0


def _derive(g, ids, cfg=CFG):
    return bs.derive_obj(g["mesh"], bs.normalize_input(sb.real_selection(g, ids), cfg), cfg, fixed_node_ids=g["fixed_ids"])


def _codes(b):
    return [w["code"] for w in b.warnings]


def _bead(D, ids, name):
    return D.bead(f"b{ids.index(name) + 1}")


def _states(g, D, B):
    """변수마다 기본 범위 양 끝 판정 [(var, value, state, code, inverted)]."""
    x0 = g["mesh"]["x0"]
    out = []
    for row in bs.params_table(D, CFG):
        for v in row["default_range"]:
            st = bs.design_state(g["mesh"], x0, bs.morph(x0, B, {row["name"]: v}), D.fixed_mask, CFG)
            out.append((row["name"], v, st["state"], st["code"], int(st["quality"]["inverted"])))
    return out


def _never_silently_torn(states):
    """뒤집힌 요소가 있는 안은 반드시 FAILED_MESH(SELECT_MORPH_INVERTED) — READY 안은 뒤집힘 0."""
    for name, v, st, code, inv in states:
        assert (st == "READY" and inv == 0) or (st == "FAILED_MESH" and code == "SELECT_MORPH_INVERTED"), (name, v, st, inv)


# ---------------------------------------------------------------- 1 비드 네트워크(T·L 교차)
NET = ["A", "C", "B1", "B2", "L"]


@pytest.fixture(scope="module")
def net():
    g = sb.real_case("network", H)
    D = _derive(g, NET)
    return g, D, bs.basis(g["mesh"], D, CFG)


def test_network_no_spread_and_warning(net):
    """사다리 전부 선택: 교차부 사면은 가까운 바닥의 비드로 나뉨(측지 Voronoi) → 레일 A·C 의 사면에 가로대 사면 요소 없음,
    SELECT_SLOPE_LEAK 없음, D·W 공칭 = 정답, SELECT_BEAD_NETWORK(교차). 따로 떨어진 L 비드는 네트워크 아님."""
    g, D, _B = net
    lab = g["label"]
    for name in NET:
        b = _bead(D, NET, name)
        tr = g["beads"][name]
        assert b.W_nom == pytest.approx(tr["W"], abs=H), name
        assert b.tiers[0]["D_nom"] == pytest.approx(tr["D"], abs=0.05), name
        assert "SELECT_SLOPE_LEAK" not in _codes(b) and "SELECT_NONPLANAR_BASE" not in _codes(b), name
        assert ("SELECT_BEAD_NETWORK" in _codes(b)) == (name != "L"), name
        cen = D.index.centroid[b.slope_mask][:, :2]                           # 이웃 비드 사면으로 번지지 않음: 사면 요소는
        d = np.min([sb._seg_dist(cen, p, q) for p, q in tr["segs"]], axis=0)     # 모두 제 중심선에서 개구 반폭 + h 안
        assert d.max() <= tr["w"] + H, (name, float(d.max()))
        own_s = lab[b.slope_mask] == f"{name}s"
        assert own_s.mean() > 0.95, name                                        # 교차 모서리(표지 모호) 몇 요소만 예외
    a = _bead(D, NET, "A")
    w = next(x for x in a.warnings if x["code"] == "SELECT_BEAD_NETWORK")
    assert w["slope_split"] > 0 and w["n_elems"] > 0


def test_network_partial_selection_warns():
    """레일 A 만 선택: 사면이 이웃 가로대 벽으로 번짐(v0.16.0 대로) → SELECT_BEAD_NETWORK 로 알림."""
    g = sb.real_case("network", H)
    b = _derive(g, ["A"]).bead("b1")
    assert "SELECT_BEAD_NETWORK" in _codes(b) and "SELECT_SLOPE_LEAK" in _codes(b)


def test_network_width_offset_at_junction(net):
    """교차부 W 오프셋: 모든 비드의 기본 범위 끝 안이 '조용히 찢어지지' 않음, 사다리 비드 A·C·B1·B2 의 W 는 뒤집힘 없이 READY.
    (L 비드 안쪽 모서리는 W +20 % 에서 뒤집힘 1 → FAILED_MESH 로 제외 — 오목 모서리 한계.)"""
    g, D, B = net
    st = _states(g, D, B)
    _never_silently_torn(st)
    for k in range(1, 5):
        assert all(s == "READY" for n, _v, s, _c, _i in st if n == f"B{k}_W"), k
    assert all(s == "READY" for n, _v, s, _c, _i in st if n.endswith("_D1"))


# ---------------------------------------------------------------- 2 넓은 돌출 평판 위 보스 다수(버링 구멍)
def test_boss_field_islands_with_holes():
    """섬 12개(가운데 구멍 1개씩) 모두 흡수, 바닥 구멍 0(버링 구멍은 섬 안), 섬 요소 = 정답, W·D 공칭, derive + 기저 ≤ 3 s,
    D 변경 시 섬 내부 = 둘레 평균(강체 평행 이동)."""
    g = sb.real_case("boss_field", H)
    t0 = time.perf_counter()
    D = _derive(g, ["P"])
    B = bs.basis(g["mesh"], D, CFG)
    dt = time.perf_counter() - t0
    b = D.bead("b1")
    assert len(b.islands) == 12 and [i["free_loops"] for i in b.islands] == [1] * 12
    assert len(b.holes) == 0 and not b.open and b.w_enabled and b.inner_loops_n == 0
    assert sorted(np.concatenate([i["elems"] for i in b.islands]).tolist()) == np.flatnonzero(g["label"] == "isl").tolist()
    assert b.W_nom == pytest.approx(120.0, abs=H) and b.tiers[0]["D_nom"] == pytest.approx(6.0, abs=0.05)
    assert b.sense == "convex" and dt < 3.0
    x0 = g["mesh"]["x0"]
    x = bs.morph(x0, B, {"B1_D1": B.nominal()["B1_D1"] + 1.0})
    for i in b.islands:
        t = (x - x0)[i["rim"]].mean(axis=0)
        assert np.allclose((x - x0)[i["interior"]], t, atol=1e-9)
    st = _states(g, D, B)
    _never_silently_torn(st)
    assert all(s == "READY" for n, _v, s, _c, _i in st if n == "B1_D1")


# ---------------------------------------------------------------- 3 판 가장자리 비드 · 사각 슬롯·컷아웃
def test_edge_bead_and_slots():
    """판 가장자리에 닿는 비드 E = 열린 경계(W 없음 — B4 유지), 바닥 슬롯 1 은 관통 구멍. 닫힌 비드 S = 슬롯 2 관통 구멍, W 있음.
    판 컷아웃(비드 밖)은 어느 비드에도 안 들어감."""
    g = sb.real_case("edge_slot", H)
    D = _derive(g, ["E", "S"])
    e, s = D.bead("b1"), D.bead("b2")
    assert e.open and not e.w_enabled and "SELECT_OPEN_BOUNDARY" in _codes(e) and len(e.holes) == 1
    assert not s.open and s.w_enabled and len(s.holes) == 2 and "SELECT_OPEN_BOUNDARY" not in _codes(s)
    assert s.W_nom == pytest.approx(28.0, abs=H) and s.inner_loops_n == 0
    X = g["mesh"]["x0"]
    for b in (e, s):
        for hl in b.holes:
            c = X[hl["nodes"]].mean(axis=0)
            assert not (20.0 <= c[0] <= 50.0 and 20.0 <= c[1] <= 40.0)              # 컷아웃 아님
    assert e.islands == [] and s.islands == []


# ---------------------------------------------------------------- 4 고리형(환형) 테두리 비드
@pytest.fixture(scope="module")
def ring():
    g = sb.real_case("ring", H)
    D = _derive(g, ["R1", "R2", "R3"])
    return g, D, bs.basis(g["mesh"], D, CFG)


def test_ring_inner_loop_is_boundary(ring):
    """안쪽 둔덕(판 높이까지 솟음) = 섬 아님(island.ring_frac) — 크기로는 섬 상한 안인 Ø14 둔덕(R3)도. 안쪽 고리 1 = 진짜 경계,
    SELECT_INNER_LOOP{n 1, ring 1}, SELECT_ISLAND_TOO_LARGE 없음, W 공칭 ≈ 정답."""
    g, D, _B = ring
    for k, name in enumerate(["R1", "R2", "R3"]):
        b = D.bead(f"b{k + 1}")
        assert b.islands == [] and b.inner_loops_n == 1 and len(b.loops) == 2, name
        w = [x for x in b.warnings if x["code"] == "SELECT_INNER_LOOP"]
        assert w == [{"code": "SELECT_INNER_LOOP", "n": 1, "ring": 1}], name
        assert "SELECT_ISLAND_TOO_LARGE" not in _codes(b)
        assert b.W_nom == pytest.approx(g["beads"][name]["W"], abs=1.5 * H), name
    # 규칙 끔(ring_frac 아주 큼) → 작은 둔덕 R3 이 섬으로 흡수돼 W 가 틀어짐(이 규칙이 막는 회귀)
    cfg = settings({"bead_doe": {"enabled": True, "select": {"island": {"ring_frac": 100.0}}}})
    b3 = _derive(g, ["R1", "R2", "R3"], cfg).bead("b3")
    assert len(b3.islands) == 1 and b3.W_nom > 2 * g["beads"]["R3"]["W"]


def test_ring_width_offsets_both_loops(ring):
    """W 넓힘 = 바깥 고리는 바깥으로, 안쪽 고리는 안쪽(고리 중심 쪽)으로 — 두 고리 모두 오프셋."""
    g, D, B = ring
    x0 = g["mesh"]["x0"]
    centers = {"R1": (90.0, 100.0), "R2": (190.0, 100.0), "R3": (255.0, 100.0)}
    for k, name in enumerate(["R1", "R2", "R3"]):
        b = D.bead(f"b{k + 1}")
        x = bs.morph(x0, B, {f"B{k + 1}_W": B.nominal()[f"B{k + 1}_W"] + 2.0})
        c = np.array(centers[name])
        dr = {}
        for lp in b.loops:
            n = lp["nodes"]
            r0 = np.linalg.norm(x0[n, :2] - c, axis=1)
            dr[float(r0.mean())] = float(np.mean(np.linalg.norm(x[n, :2] - c, axis=1) - r0))
        (ri, di), (ro, do) = sorted(dr.items())
        assert do > 0.5 and di < -0.5, (name, dr)                                     # 바깥 +, 안쪽 −
    _never_silently_torn(_states(g, D, B))


# ---------------------------------------------------------------- 5 경계에 반쯤 걸친 보스(들쭉날쭉한 경계)
def test_edge_boss_width_and_no_silent_tear():
    """W·D 공칭 = 정답, 바닥 안 보스 1 = 섬, 보스 발치 평평한 요소로 SELECT_BEAD_NETWORK 오탐 없음, 범위 끝 안은 찢어지면
    반드시 FAILED_MESH. (한계: 판 쪽 보스 벽까지 사면 BFS 가 올라가 보스 윗면이 안쪽 고리로 남고 국부 폭 최소가 튐 — 보고만.)"""
    g = sb.real_case("edge_boss", H)
    D = _derive(g, ["G"])
    B = bs.basis(g["mesh"], D, CFG)
    b = D.bead("b1")
    assert b.W_nom == pytest.approx(40.0, abs=H) and b.tiers[0]["D_nom"] == pytest.approx(10.0, abs=0.05)
    assert len(b.islands) == 1 and "SELECT_BEAD_NETWORK" not in _codes(b) and b.w_enabled
    assert b.inner_loops_n >= 2                                                         # 한계(위 문서) 고정
    _never_silently_torn(_states(g, D, B))


# ---------------------------------------------------------------- 6 Ω·U 채널(깊은 오목 경계)
def test_channel_width_stable():
    """U·Ω: W 공칭 = 정답, 국부 폭 최소 = 공칭(오목 경계에서 짧게 튀지 않음), 최대 ≤ 2 W(모서리 대각), 안쪽 고리 없음, D 범위 끝
    안 READY, W 는 찢어지면 FAILED_MESH(오목 모서리 W +20 % = 뒤집힘 2~4 요소 — 한계)."""
    g = sb.real_case("channel", H)
    D = _derive(g, ["U", "O"])
    B = bs.basis(g["mesh"], D, CFG)
    for k, name in enumerate(["U", "O"]):
        b = D.bead(f"b{k + 1}")
        assert b.W_nom == pytest.approx(20.0, abs=H) and b.W_min >= 20.0 - H and b.W_max <= 2 * 20.0 + 1e-6, name
        assert b.inner_loops_n == 0 and not b.open and b.islands == [], name
    st = _states(g, D, B)
    _never_silently_torn(st)
    assert all(s == "READY" for n, _v, s, _c, _i in st if n.endswith("_D1"))
