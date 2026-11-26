"""V-0250-VB-12·23·24 — 비정렬 실제 모형 H6 독립 측정(계약 esl_virtual_bead.md §12-12·§19.6-23·24, v0.24.7 교훈: 기본 범위 끝까지).

개정 2·3(r 생략 = h, A warp = 정보, 평탄부 host, 깊이 보상): 모두 실제 derive(host 덮어쓰기 없음)·실제 ``guard_selection``.
  (1) 위 부모 바닥 띠(y 654) ξ L 200 계약 단면(W_top 15·θ 45·d_max 5) — base host, ok,
  (2) 위 띠 30° — 띠 폭 ≈ 40 mm 라 VB_PLATE_EDGE(개정 2 로 발자국이 1.25·r·tan(θ/2) 넓어져 이웃 링 비드에도 닿음 — VB-C1-16),
  (3) 평탄부(plateau, floor 11): 계약 자리 (125, 300) ξ L 120·(250, 300) 30° L 100 은 보스·구멍·자식 비드에 닿아 거부 →
      닿지 않는 자리(VB-C1-17): (150, 180) ξ L 120 θ 45, (250, 180) 30° L 60 θ 45, (200, 480) 30° L 60 θ 60
      ((250, 180) 의 θ 60 은 그 자리 h 2.97 > run 2.89 라 VB_MESH_COARSE).
D = d_max·0.5 d_max 뒤집힘 0·jac·tri 새 위반 0, 발자국 밖 이동 ≤ 1e-12, range guard blocked 아님. 측정값 = work/vbead_h6.md."""
import numpy as np
import pytest
import synth_guard as sg
from _bg_util import CFG, bgr, bs, prepared

from esl.doe import DEFAULTS
from esl.doe import mesh_quality as mq
from esl.morph import virtual_bead as vbm

pytestmark = pytest.mark.slow

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}
RU = sg.rules()
FR = {"origin": [0.0, 0.0, 0.0], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 1.0, 0.0], "n": [0.0, 0.0, 1.0]}
CRIT = bgr._crit(RU["range_guard"], CFG)


@pytest.fixture(scope="module")
def H6():
    return prepared("h6")


def _derive(H6, vbs):
    m, g, lab, fx, _d = H6
    s = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}}, "beads": [],
         "ties": [], "virtual_beads": vbs}
    n, _ = bgr.normalize_v2(s, g, CFG, labels=lab, mesh=m, shape_rules=RU)
    return bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, shape_rules=RU, virtual_bead=BLK, frame=FR)


def measure(H6, D) -> dict:
    """D = d_max·0.5 d_max: 뒤집힘·새 품질 위반(jac·tri, warp 는 정보)·발자국 밖 이동 최대 + 실제 guard_selection(A)."""
    mesh = H6[0]
    B = bs.basis(mesh, D, CFG)
    var = next(v for v in B.vars if v["name"] == "A1_A")
    x0 = np.asarray(mesh["x0"], np.float64)
    dmax = float(D.vbeads[0].d_max)
    out = {}
    outside = np.ones(x0.shape[0], bool)
    outside[var["idx"]] = False
    for k, Dv in (("d_max", dmax), ("half", 0.5 * dmax)):
        x = bs.morph(x0, B, {"A1_A": Dv})
        am = np.flatnonzero(bs.affected_elems(mesh, x0, x))
        p = mq.guard_probe(x0, x, mesh["conn"], mesh["elem_type"], am, flip_deg=CRIT["flip_deg"], jac_min=CRIT["jac_min"],
                           tria_angle_min_deg=CRIT["tria_angle_min_deg"], warp_max_deg=BLK["warp_max_deg"])
        out[k] = {"inverted": p["inverted"], "jac_bad_new": p["jac_bad_new"], "tri_bad_new": p["tri_bad_new"],
                  "warp_bad_new": p["warp_bad_new"], "warp_max": round(float(p["warp_max"] or 0.0), 2),
                  "outside_max": float(np.abs(x[outside] - x0[outside]).max())}
    doc = bgr.guard_selection(mesh, D, B, CFG, only=["A1_A"])
    e = doc["entries"][0]
    out["guard"] = {"state": e["state"], "usable": e["usable"], "warp": e["warp"],
                    "reason": next((x["reason"] for x in e["ends"] if not x["ok"]), None)}
    return out


def _check(r):
    for k in ("d_max", "half"):
        assert r[k]["inverted"] == 0 and r[k]["jac_bad_new"] == 0 and r[k]["tri_bad_new"] == 0, r
        assert r[k]["outside_max"] <= 1e-12, r
    assert r["guard"]["state"] != "blocked", r


def test_contract_xi_on_base_band_v24(H6):
    D = _derive(H6, [{"id": "a1", "p0": [400.0, 654.0, 0.0], "p1": [600.0, 654.0, 0.0], "w_top": 15.0, "d_max": 5.0}])
    vb = D.vbeads[0]
    assert vb.reasons == [] and vb.ok and vb.host == "base", vb.reasons
    assert [w["code"] for w in vb.warnings] == ["VB_WALL_COARSE", "VB_EDGE_SMEAR"]    # 개정 1 과 같은 코드
    assert vb.r_source == "default" and vb.r == pytest.approx(min(vb.h, vbm.r_cap(15.0, 45.0, 5.0)), abs=1e-4)
    _check(measure(H6, D))


def test_contract_30deg_on_base_band_v24(H6):
    D = _derive(H6, [{"id": "a1", "p0": [700.0, 649.0, 0.0], "length": 20.0, "angle_deg": 30.0, "w_top": 15.0,
                      "d_max": 5.0}])
    assert "VB_PLATE_EDGE" in D.vbeads[0].reasons


@pytest.mark.parametrize("p0,ang,L,th", [((150.0, 180.0, 10.0), 0.0, 120.0, 45.0), ((250.0, 180.0, 10.0), 30.0, 60.0, 45.0),
                                         ((200.0, 480.0, 10.0), 30.0, 60.0, 60.0)], ids=["xi", "30deg", "30deg_t60"])
def test_plateau_derive_v23(H6, p0, ang, L, th):
    v = {"id": "a1", "p0": list(p0), "length": L, "angle_deg": ang, "w_top": 15.0, "d_max": 5.0}
    if th != 45.0:
        v["theta_deg"] = th
    D = _derive(H6, [v])
    vb = D.vbeads[0]
    assert vb.ok and vb.host == "plateau" and vb.host_floor == 11, vb.reasons
    _check(measure(H6, D))


def test_contract_plateau_spots_rejected_v23(H6):
    """계약 자리 (125, 300) ξ L 120·(250, 300) 30° L 100 은 평탄부 위 보스·구멍·자식 비드에 닿음(측정 고정 — VB-C1-17)."""
    D = _derive(H6, [{"id": "a1", "p0": [125.0, 300.0, 10.0], "length": 120.0, "angle_deg": 0.0, "w_top": 15.0,
                      "d_max": 5.0},
                     {"id": "a2", "p0": [250.0, 300.0, 10.0], "length": 100.0, "angle_deg": 30.0, "w_top": 15.0,
                      "d_max": 5.0}])
    assert all(v.reasons for v in D.vbeads) and all(v.host == "plateau" for v in D.vbeads)
