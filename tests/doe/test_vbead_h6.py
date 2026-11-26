"""V-0250-VB-12 — 비정렬 실제 모형 H6 독립 측정(계약 esl_virtual_bead.md §12-12, v0.24.7 교훈: 기본 범위 끝까지).

H6 의 부모 바닥(segment base)은 판 가장자리 띠(아래 y ≈ 1..32 — 폭 ≈ 31 mm, 위 y ≈ 634..674 — 폭 ≈ 40 mm)뿐이고 넓은
평탄부는 plateau(segment 11, 깊이 4 — host 아님: Q-VB-2 기본·R-VB-7)다(VB-C1-6). 그래서:
  (1) 계약 단면(W_top 15·θ 45·d_max 5) ξ 방향은 위 띠에 들어감 → derive ok + 측정,
  (2) 30° 는 띠에 들어가지 않음 → VB_PLATE_EDGE(측정 고정 — 완화 안 함, 메인 결정 대상),
  (3) 계약 단면 2개(ξ 1·30° 1)를 평탄부(plateau — 판 평면 위 순수 장 ``virtual_bead``, host 판정만 plateau 로)에 놓아 같은 측정.
측정값은 work/vbead_h6.md 에 기록."""
import numpy as np
import pytest
import synth_guard as sg
from _bg_util import CFG, bgr, bs, prepared

from esl.doe import DEFAULTS
from esl.doe import mesh_quality as mq
from esl.morph import range_guard as rgm
from esl.morph import virtual_bead as vbm

pytestmark = pytest.mark.slow

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}
RU = sg.rules()
FR = {"origin": [0.0, 0.0, 0.0], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 1.0, 0.0], "n": [0.0, 0.0, 1.0]}
CRIT = {**bgr._crit(RU["range_guard"], CFG), "warp_max_deg": BLK["warp_max_deg"]}


@pytest.fixture(scope="module")
def H6():
    return prepared("h6")


def _derive(H6, vbs):
    m, g, lab, fx, _d = H6
    s = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}}, "beads": [],
         "ties": [], "virtual_beads": vbs}
    n, _ = bgr.normalize_v2(s, g, CFG, labels=lab, mesh=m)
    return bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, shape_rules=RU, virtual_bead=BLK, frame=FR)


def measure(mesh, var) -> dict:
    """D = d_max·0.5 d_max: 뒤집힘(flip_deg)·새 품질 위반(jac·tri·warp)·발자국 밖 이동 최대 + range guard 단일(A crit)."""
    from esl.doe.bead_select import Basis
    x0 = np.asarray(mesh["x0"], np.float64)
    B = Basis([var], x0.shape[0], "x")
    dmax = float(var["d_max"])
    out = {}
    outside = np.ones(x0.shape[0], bool)
    outside[var["idx"]] = False
    for k, D in (("d_max", dmax), ("half", 0.5 * dmax)):
        x = bs.morph(x0, B, {var["name"]: D})
        am = np.flatnonzero(bs.affected_elems(mesh, x0, x))
        p = mq.guard_probe(x0, x, mesh["conn"], mesh["elem_type"], am, flip_deg=CRIT["flip_deg"], jac_min=CRIT["jac_min"],
                           tria_angle_min_deg=CRIT["tria_angle_min_deg"], warp_max_deg=CRIT["warp_max_deg"])
        out[k] = {"inverted": p["inverted"], "jac_bad_new": p["jac_bad_new"], "tri_bad_new": p["tri_bad_new"],
                  "warp_bad_new": p["warp_bad_new"], "warp_max": round(float(p["warp_max"] or 0.0), 2),
                  "outside_max": float(np.abs(x[outside] - x0[outside]).max())}
    P = bgr._Prober(mesh, CRIT, None)
    L = P.local([bgr._pv(var)])
    r = rgm.single(var["name"], 0.0, 0.0, dmax, lambda v: P.ok(L, [v]), steps=int(RU["range_guard"]["steps"]),
                   budget=rgm.Budget(None, None), min_keep_frac=RU["range_guard"]["min_keep_frac"])
    out["guard"] = {"state": r["state"], "usable": r["usable"],
                    "reason": next((e["reason"] for e in r["ends"] if not e["ok"]), None)}
    return out


def test_contract_xi_on_base_band(H6):
    """(1) 계약 단면 ξ 방향(L 200)을 위 부모 바닥 띠(y 654 — 폭 ≈ 40 mm)에 → derive ok, D = d_max·0.5 d_max 뒤집힘 0,
    발자국 밖 이동 0, 품질 위반 수·range guard 측정(work/vbead_h6.md)."""
    D = _derive(H6, [{"id": "a1", "p0": [400.0, 654.0, 0.0], "p1": [600.0, 654.0, 0.0], "w_top": 15.0, "d_max": 5.0}])
    vb = D.vbeads[0]
    assert vb.reasons == [] and vb.ok, vb.reasons
    var = bgr.vb_basis_vars(D)[0]
    var["d_max"] = 5.0
    r = measure(H6[0], var)
    for k in ("d_max", "half"):
        assert r[k]["inverted"] == 0 and r[k]["outside_max"] <= 1e-12, r


def test_contract_30deg_on_base_band_rejected(H6):
    """(2) 계약 단면 30° 는 띠(≈ 40 mm)에 들어가지 않음 → VB_PLATE_EDGE(측정 고정 — VB-C1-6, 평탄부 측정은 (3))."""
    D = _derive(H6, [{"id": "a1", "p0": [700.0, 649.0, 0.0], "length": 20.0, "angle_deg": 30.0, "w_top": 15.0,
                      "d_max": 5.0}])
    assert D.vbeads[0].reasons == ["VB_PLATE_EDGE"]


def _plateau_var(H6, p0, ang, L, name):
    m, g, lab, _fx, _d = H6
    X, C, et = np.asarray(m["x0"]), np.asarray(m["conn"]), np.asarray(m["elem_type"])
    plat = (lab["segment"] == 11) & (lab["cls"] == 0) & (lab["junction_zone"] < 0) & (lab["island"] < 0)
    hn = np.unique(C[plat][:, :3])
    from esl.morph.core import plane_fit
    ph, nh, _ = plane_fit(X[hn])
    nh = nh if nh[2] > 0 else -nh
    line = vbm.resolve_line(np.array(p0, float), None, L, ang, ([1.0, 0, 0], [0, 1.0, 0]), (ph, nh))
    fp = vbm.footprint(X, (*line, nh), 15.0, 45.0, 5.0, "round", 0.0, float(BLK["margin_mm"]))
    chk = vbm.chk_elems(C, et, fp["chk_mask"])
    assert vbm.host_check(C, chk, {"host": plat}) == []                            # 평탄부 안(벽·섬·비드 없음)
    idx = np.flatnonzero(fp["move_mask"])
    nrm = vbm.node_normals(X, C, et, plat, nh)[idx]
    f = vbm.field(fp["d"][idx], nrm, -1, 15.0, 45.0, 0.0, idx=idx)
    h = vbm.edge_median(X, C, et, vbm.chk_elems(C, et, fp["move_mask"]) & plat)
    return {"name": name, "type": "A", "bead": "a1", "nominal": 0.0, "idx": f["idx"].astype(np.int32),
            "vec": f["vec"], "form": "hinge", "g": f["g"], "c": f["c"], "d_max": 5.0, "h": h}


@pytest.mark.parametrize("p0,ang,L", [((125.0, 300.0, 10.0), 0.0, 120.0), ((250.0, 300.0, 10.0), 30.0, 100.0)],
                         ids=["xi", "30deg"])
def test_contract_section_on_plateau(H6, p0, ang, L):
    """(3) 계약 단면(W_top 15·θ 45·d_max 5) 2개를 평탄부에 — D = d_max·0.5 d_max 뒤집힘 0, 발자국 밖 0(측정 기록)."""
    var = _plateau_var(H6, p0, ang, L, "A1_A")
    r = measure(H6[0], var)
    for k in ("d_max", "half"):
        assert r[k]["inverted"] == 0 and r[k]["outside_max"] <= 1e-12, r
    assert r["guard"]["state"] in ("ok", "limited", "blocked")
