"""v0.24.0 경계력 ESL — Case 파이프라인(계약 esl_bforce.md §2·§4, V-0240-j).

합성 Case(synth_case: 대회전 25°·병진 강체 운동 + 변형) 에 t* 변형 형상 전역 성분의 접촉력·가속도 CSV 를 더해
extract → tstar → esl → 04_esl/bforce.json(contact 등급, 관성 이완)·재현 MAC. 경계력 자료 없는 추출물 = 등급 none,
전 노드 ESL 산출물(f_eq·u_rel·esl_summary)은 경계력과 무관.
"""
import json
import os
import shutil

import numpy as np
import pytest

import synth_case
from esl import pipeline
from esl.mech import bforce as bfm
from esl.mech.mass import lumped_mass
from esl.rad import parse_rad

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")
A0 = np.array([300.0, -9810.0 * 150.0, 2.0e5])           # 강체 감속(가속도) — 관성 이완이 지움


def _add_bforce(c, csv_dir):
    done_p = os.path.join(csv_dir, "done.json")
    done = json.load(open(done_p, encoding="utf-8"))
    D = list(done["frames_D"])
    X0 = c["X0"]
    model = parse_rad(c["rad"], "chassis rear")
    rho_e, _ = bfm.rho_per_elem(np.full(model.elem_id.size, model.mats[0]["id"]), model.mats, 7.85e-9)
    m = lumped_mass({"x0": model.x0, "conn": model.conn, "elem_type": model.elem_type, "thickness": model.thickness},
                    rho_e)
    assert np.allclose(model.x0, X0)
    Fi1, Fi2 = c["F_app"] + c["R"], c["F2"] + c["R2"]     # 내력 = K u (지지 반력 포함 — 자기평형)
    axis = [0.3, -0.5, 0.8]
    rows_c, rows_a = [], []
    for k in D:
        Q = synth_case.rot(axis, np.radians(25.0) * k / synth_case.T_STAR_FRAME)
        Fint = (synth_case.A_T[k] * Fi1 + synth_case.B_T[k] * Fi2) @ Q.T
        acc = np.broadcast_to(A0, X0.shape)
        cont = Fint + m[:, None] * acc                    # F = CONT − M·ACC = 내력
        for i, n in enumerate(c["node_id"]):
            rows_c.append(f"{k},{n},{float(cont[i, 0])!r},{float(cont[i, 1])!r},{float(cont[i, 2])!r}")
            rows_a.append(f"{k},{n},{float(acc[i, 0])!r},{float(acc[i, 1])!r},{float(acc[i, 2])!r}")
    with open(os.path.join(csv_dir, "bf_cont.csv"), "w", encoding="utf-8") as fh:
        fh.write("frame_index,node_id,x,y,z\n" + "\n".join(rows_c) + "\n")
    with open(os.path.join(csv_dir, "bf_acc.csv"), "w", encoding="utf-8") as fh:
        fh.write("frame_index,node_id,x,y,z\n" + "\n".join(rows_a) + "\n")
    nul = {"type": None, "reason": "not in h3d"}
    done["bforce"] = {"on": True, "frames": D, "kinds": {
        "cont": {"type": "Contact Forces", "comps": ["X", "Y", "Z"], "rows": len(rows_c)},
        "acc": {"type": "Acceleration", "comps": ["X", "Y", "Z"], "rows": len(rows_a)},
        "cont2": nul, "mass": nul, "fint": nul}}
    json.dump(done, open(done_p, "w", encoding="utf-8"))
    return m


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("bfp"))
    c = synth_case.build(root)
    cfg = os.path.join(root, "esl64.yaml")
    open(cfg, "w", encoding="utf-8").write(CFG64_TEXT)
    plain = os.path.join(root, "in", "csv_plain")
    shutil.copytree(c["csv"], plain)
    m = _add_bforce(c, c["csv"])
    outs = {}
    for name, csv in (("bf", c["csv"]), ("plain", plain)):
        out = os.path.join(root, "out_" + name)
        pipeline.run(cfg, c["rad"], csv, out, stage="extract", echo=lambda *_: None)
        pipeline.run(cfg, c["rad"], csv, out, stage="tstar", echo=lambda *_: None)
        pipeline.run(cfg, c["rad"], csv, out, stage="esl", frame=synth_case.T_STAR_FRAME, echo=lambda *_: None)
        outs[name] = out
    return {"c": c, "m": m, **outs}


def _j(p):
    return json.load(open(p, encoding="utf-8"))


def test_v0240_j_contact_grade_stage(runs):
    d = _j(os.path.join(runs["bf"], "04_esl", "bforce.json"))
    assert d["schema"] == "esl/bforce/1" and d["grade"] == "contact" and d["mass_source"] == "deck"
    assert d["limits"] == ["BF_TIE_MISSING"] and d["frame"]["frame_index"] == synth_case.T_STAR_FRAME
    assert d["rot_deg"] == pytest.approx(25.0, abs=0.5)
    # CONT 에 관성(강체 감속 m·a)이 섞여 있고 F = CONT − M·ACC 가 그것을 지움 → 내력(자기평형)
    assert d["parts_sum_abs"]["inertia"] > d["sum_abs"] and d["eq_raw"]["def"]["force_rel"] < 1e-9
    assert d["corr_rel"] < 1e-6
    M = runs["m"].sum()
    assert d["mass_total"] == pytest.approx(M, rel=1e-12)
    assert d["eq_bal"]["ref"]["force_rel"] < 1e-12 and d["eq_bal"]["ref"]["moment_rel"] < 1e-12
    assert d["recon"]["status"] == "ok" and d["recon"]["mac"] > 0.999 and abs(d["recon"]["umax_err"]) < 0.01
    assert d["recon"]["reaction_rel"] < 1e-6
    z = np.load(os.path.join(runs["bf"], "04_esl", "bforce.npz"), allow_pickle=False)
    fz = np.load(os.path.join(runs["bf"], "04_esl", "f_eq.npz"), allow_pickle=False)
    assert np.array_equal(z["node_id"], fz["node_id"]) and z["f"].shape == fz["f"].shape and "u_val" in z.files
    rj = _j(os.path.join(runs["bf"], "run.json"))
    st = rj["stages"]["esl"]["summary"]["bforce"] if "stages" in rj else None
    if st is not None:
        assert st["grade"] == "contact" and st["recon"] == "ok"
    ex = _j(os.path.join(runs["bf"], "01_extract", "bforce.json"))
    assert ex["kinds"]["cont"]["type"] == "Contact Forces" and ex["kinds"]["cont2"]["type"] is None


def test_v0240_j_no_data_and_full_esl_unchanged(runs):
    assert not os.path.isfile(os.path.join(runs["plain"], "04_esl", "bforce.json"))     # 산출물 집합 불변(이전 추출물)
    assert not os.path.isfile(os.path.join(runs["plain"], "04_esl", "bforce.npz"))
    st = _j(os.path.join(runs["plain"], "run.json"))["stages"]["esl"]["summary"]["bforce"]
    assert st["grade"] == "none" and st["code"] == "BF_NO_DATA"
    assert not os.path.isfile(os.path.join(runs["plain"], "01_extract", "bforce.json"))   # 옛 추출물 = 쓰지 않음
    for fn in ("f_eq.npz", "u_rel.npz"):
        a = np.load(os.path.join(runs["bf"], "04_esl", fn), allow_pickle=False)
        b = np.load(os.path.join(runs["plain"], "04_esl", fn), allow_pickle=False)
        for k in a.files:
            assert np.array_equal(a[k], b[k]), (fn, k)
    sa = _j(os.path.join(runs["bf"], "04_esl", "esl_summary.json"))
    sb = _j(os.path.join(runs["plain"], "04_esl", "esl_summary.json"))
    assert "bforce" not in sa
    for k in ("forces", "kabsch", "supports", "frame"):
        assert sa[k] == sb[k], k
