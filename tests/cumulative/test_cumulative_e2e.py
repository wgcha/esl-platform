"""누적 씬 E2E·회귀 (계약 esl_cumulative_input.md §14: V-CI-E1·E2·S3(D 밖)·S4·B1·T1)."""
import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(ROOT, "tests", "io")]

import golden_util  # noqa: E402
import make_golden  # noqa: E402
import synth_cum  # noqa: E402
import tcl_golden  # noqa: E402
from esl import cli  # noqa: E402
from esl.io import pack_results  # noqa: E402
from esl.rad import parse_rad  # noqa: E402

CFG = os.path.join(ROOT, "config", "esl.example.yaml")
FIX = os.path.join(ROOT, "tests", "fixtures", "cumulative")


def _cfg(root, extra=""):
    txt = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")
    txt = txt.replace("hot_k: 200 ", "hot_k: 5000")
    p = os.path.join(root, "esl64.yaml")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(txt + extra)
    return p


def _run(cfg, rad, csv, out, *stages):
    rc = 0
    for st in stages:
        rc = rc or cli.main(["run", "--config", cfg, "--rad", rad, "--results", csv, "--out", out, "--stage", st])
    return rc


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def cum(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("cum"))
    c = synth_cum.build(root)
    c["root"] = root
    c["cfg"] = _cfg(root)
    c["out"] = os.path.join(root, "out")
    snap = {f: os.stat(os.path.join(c["din"], f)).st_mtime_ns for f in os.listdir(c["din"])
            if os.path.isfile(os.path.join(c["din"], f))}
    c["rc"] = cli.main(["run", "--config", c["cfg"], "--rad", c["rad"], "--results", c["csv"], "--out", c["out"],
                        "--stage", "all"])
    c["snap"] = snap
    return c


# ------------------------------------------------------------------ V-CI-E1
def test_e1_cumulative_e2e_state_geometry_and_tstar(cum):
    assert cum["rc"] == 0
    out = cum["out"]
    # 입력 폴더 쓰기 없음
    assert {f: os.stat(os.path.join(cum["din"], f)).st_mtime_ns for f in cum["snap"]} == cum["snap"]
    z = np.load(os.path.join(out, "01_extract", "model.npz"))
    order = np.argsort(cum["node_id"])
    assert np.allclose(z["x0"], cum["X1"][order], rtol=0, atol=1e-9)          # K_L 좌표 = 상태(.str) 변형 좌표
    eo = np.argsort(cum["elem_id"])
    assert np.allclose(z["thickness"], cum["thk1"][eo], rtol=1e-12)           # K_L 두께 = 상태 THK
    mm = _j(out, "01_extract", "model_meta.json")
    assert mm["cumulative"] is True and mm["state_summary"] == "state_summary.json"
    ss = _j(out, "01_extract", "state_summary.json")
    assert ss["schema"] == "esl/state/1" and [sorted(f["kinds"]) for f in ss["files"]] == [["geometry"], ["initial"]]
    assert all(len(f["sha256"]) == 64 for f in ss["files"])
    assert ss["coord"]["source"] == "state" and ss["coord"]["rad_coord_source"] == "rad:state"
    assert ss["diagnosis"]["epsp"]["mode"] == "cumulative" and ss["diagnosis"]["eq"]["mode"] == "incremental"
    assert ss["agg"] == "mid_mean" and ss["frame0_source"] == "frame0.csv"
    assert ss["thickness"]["source"] == "state" and ss["thickness"]["max_thinning_pct"] == pytest.approx(3.0, abs=0.1)
    assert ss["epsp_init"]["max"] == pytest.approx(synth_cum.PREV_BIG)
    st = np.load(os.path.join(out, "01_extract", "state.npz"), allow_pickle=False)
    assert np.allclose(st["prev_mid_mean"], cum["prev"][eo], atol=1e-14) and st["node_from_state"].all()
    fr = _j(out, "01_extract", "frames.json")
    assert fr["cumulative"]["epsp_mode"] == "cumulative" and fr["frame0_source"] == "frame0.csv"
    assert fr["tcl_cumulative"]["rank_sets"] == ["raw", "raw+prev"]
    rj = _j(out, "run.json")
    assert [os.path.basename(x["path"]) for x in rj["inputs"]["state_files"]] == [cum["str"], cum["sta"]]
    assert rj["stages"]["extract"]["summary"]["cumulative"]["eq_mode"] == "incremental"
    # t*: 누적 순위 1위 = 이전 손상 큰 요소, first-reach = 증분 계열(frame 3) — 비누적 규칙이면 frame 6
    tj = _j(out, "02_tstar", "tstar.json")
    eb = int(cum["elem_id"][cum["e_big"]])
    ts = tj["metrics"]["max_strain"]["tstar"]
    assert ts["elem_id"] == eb and ts["frame_index"] == 3 and tj["selected"]["frame_index"] == 3
    assert ts["value"] == pytest.approx(ts["value_prev"] + ts["value_inc"])
    assert ts["value_prev"] == pytest.approx(synth_cum.PREV_BIG)
    assert ts["value_inc"] == pytest.approx(float(cum["eq_hold"][-1, cum["e_big"]]), rel=1e-6)
    assert tj["cumulative"]["eq_mode"] == "incremental" and tj["schema"] == "esl/tstar/2"
    assert "n_excluded_no_increment" in tj["metrics"]["max_strain"]["cumulative"]
    assert set(tj["candidates"][0]) >= {"value", "value_inc", "value_prev"}
    assert "m_inc" in tj["metrics"]["max_strain"]["history"]
    hdr = open(os.path.join(out, "02_tstar", "candidates.csv")).readline().strip().split(",")
    assert hdr[-2:] == ["value_inc", "value_prev"]
    # ESL: 상태 형상 K_L → 자기평형·검증 PASS
    es = _j(out, "04_esl", "esl_summary.json")
    assert es["frame"]["frame_index"] == 3
    v = _j(out, "05_val", "validation.json")
    m = {x["metric"]: x for x in v["metrics"]}
    assert v["verdict"] == "PASS" and m["disp_rms_rel"]["value"] < 1e-8 and m["reaction_rel"]["value"] < 1e-8
    # V-CI-S4: ⑤ 변형률 참고 비교 = 증분 기준, 판정(변위 4지표) 불변
    sr = v["strain_ref"]
    assert sr["basis"] == "increment" and sr["n_plastic_cum"] >= sr["n_plastic_inc"]
    assert sr["cum_max"] > sr["inc_max"] > 0
    assert m["hotspot1_strain_rel_err"]["value"] < 1e-6
    # 보고서 절
    html = open(os.path.join(out, "07_report", "report.html"), encoding="utf-8").read()
    assert "누적 낙하 입력" in html and cum["str"] in html


def test_e1_thickness_source_prop_cross_check(cum, tmp_path):
    cfg = _cfg(str(tmp_path), "")
    txt = open(cfg, encoding="utf-8").read().replace("thickness_source: state", "thickness_source: prop")
    open(cfg, "w", encoding="utf-8").write(txt)
    out = str(tmp_path / "out")
    assert cli.main(["run", "--config", cfg, "--rad", cum["rad"], "--results", cum["csv"], "--out", out,
                     "--stage", "extract"]) == 0
    z = np.load(os.path.join(out, "01_extract", "model.npz"))
    assert np.all(z["thickness"] == synth_cum.T0)
    assert _j(out, "01_extract", "state_summary.json")["thickness"]["k_l_source"] == "prop"


def test_s3_candidate_frame_not_extracted_falls_back(cum, tmp_path, capsys):
    """D 에서 frame 3 을 빼면(PC 추출본 등) CUMULATIVE_FRAME_NOT_EXTRACTED 후 다음 후보."""
    import shutil
    d = str(tmp_path / "csv")
    shutil.copytree(cum["csv"], d)
    dj = json.load(open(os.path.join(d, "done.json")))
    dj["frames_D"] = [6]
    dj["candidate_frames"] = {"max_strain": [6], "plastic_strain": [6]}
    json.dump(dj, open(os.path.join(d, "done.json"), "w"))
    out = str(tmp_path / "out")
    assert _run(cum["cfg"], cum["rad"], d, out, "extract", "tstar") == 0
    tj = _j(out, "02_tstar", "tstar.json")
    assert tj["selected"]["frame_index"] == 6 and tj["metrics"]["max_strain"]["adjusted"]["from"] == 3
    assert "CUMULATIVE_FRAME_NOT_EXTRACTED" in capsys.readouterr().out + json.dumps(_j(out, "run.json"))


def test_enabled_off_treats_state_as_plain_include(cum, tmp_path):
    cfg = _cfg(str(tmp_path), "")
    txt = open(cfg, encoding="utf-8").read().replace("  enabled: auto  ", "  enabled: off   ")
    open(cfg, "w", encoding="utf-8").write(txt)
    out = str(tmp_path / "out")
    assert _run(cfg, cum["rad"], cum["csv"], out, "extract", "tstar") == 0
    assert not os.path.exists(os.path.join(out, "01_extract", "state.npz"))
    tj = _j(out, "02_tstar", "tstar.json")
    assert "cumulative" not in tj and tj["selected"]["frame_index"] == 6
    z = np.load(os.path.join(out, "01_extract", "model.npz"))
    assert np.allclose(z["x0"], cum["X1"][np.argsort(cum["node_id"])], atol=1e-9)   # 형상 규칙은 적용


# ------------------------------------------------------------------ V-CI-E2
def test_e2_same_run_without_state_include_warns(cum, tmp_path, capsys):
    out = str(tmp_path / "out")
    rc = _run(cum["cfg"], cum["rad_orig"], cum["csv"], out, "extract", "tstar")
    assert rc == 0
    text = capsys.readouterr().out + json.dumps(_j(out, "run.json"), ensure_ascii=False)
    assert "CUMULATIVE_STATE_NOT_INCLUDED" in text
    assert not os.path.exists(os.path.join(out, "01_extract", "state_summary.json"))
    tj = _j(out, "02_tstar", "tstar.json")
    assert "cumulative" not in tj and tj["selected"]["frame_index"] == 6     # 기존 규칙(raw first-reach)
    assert "value_inc" not in tj["candidates"][0]


# ------------------------------------------------------------------ V-CI-B1 비누적 산출물 = v0.7.2
def test_b1_noncumulative_outputs_identical_to_v072(tmp_path):
    gold = _j(FIX, "golden_v072.json")
    got = make_golden.run_case(str(tmp_path))
    env = golden_util.env_key()
    solver_free = [k for k in gold["files"] if k.startswith(("01_extract/", "02_tstar/", "03_bc/"))]
    assert set(got) == set(gold["files"])                       # 새 파일 없음
    for k in solver_free:
        assert got[k] == gold["files"][k], k
    if env == gold["env"]:
        diff = [k for k in gold["files"] if got[k] != gold["files"][k]]
        assert diff == [], diff
    else:
        pytest.skip(f"솔버 의존 산출물 비교는 골든 환경({gold['env']})에서만 — 현재 {env}")


def test_b1_tcl_outputs_identical_without_request_keys(tmp_path):
    assert tcl_golden.tcl_digest(str(tmp_path)) == _j(FIX, "tcl_golden_v072.json")


# ------------------------------------------------------------------ V-CI-T1 TCL prev_file·F0 패스(mock)
def test_t1_tcl_prev_file_and_frame0_pass(tmp_path):
    import test_tcl_mock as tm
    from esl.mech import tstar
    prev = tmp_path / "prev.csv"
    prev.write_text("elem_id,prev_epsp,prev_eq\n10,0.0,0.0\n11,0.5,0.5\n12,0,0\n13,0,0\n14,0,0\n15,0,0\n")
    m, ref, drv, out = tm._setup(tmp_path, extra_req=f"prev_file\t{prev}\nframe0_pass\t1\ncum_min_incr\t1e-5\n")
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["cumulative"]["prev_n"] == 6 and done["cumulative"]["frame0"] is True
    assert done["cumulative"]["rank_sets"] == ["raw", "raw+prev"] and done["cumulative"]["frame0_rows"] == 6
    lines = (out / "frame0.csv").read_text().strip().split("\n")
    assert lines[0] == "elem_id,vm_hv,epsp" and len(lines) == 7
    # H = raw top ∪ (raw+prev) top(최종 raw > min_incr): 요소 11 이 prev 로 들어옴
    hk = 2
    vm, ep = ref["vm"], ref["ep"]
    pe = np.array([0.0, 0.5, 0, 0, 0, 0])
    Hs = set(tstar.hot_set(vm[-1], ep[-1], hk).tolist())
    okv = vm[-1] > 1e-5
    oke = ep[-1] > 1e-5
    Hs |= {int(i) for i in np.argsort(-(np.where(okv, vm[-1] + pe, -np.inf)), kind="stable")[:hk] if okv[i]}
    Hs |= {int(i) for i in np.argsort(-(np.where(oke, ep[-1] + pe, -np.inf)), kind="stable")[:hk] if oke[i]}
    assert done["n_hot"] == len(Hs) and 1 in Hs
    D = set(done["frames_D"])
    assert set(done["candidate_frames"]["max_strain"]) <= D and set(done["candidate_frames_prev"]["max_strain"]) <= D
    assert len(D) <= 4 * 3
    assert "frame0.csv done: 6 elements" in (out / "progress.log").read_text()
    res = pack_results(out, m, tmp_path / "npz")
    assert res["frame0"] is True
    z = np.load(tmp_path / "npz" / "frame0.npz")
    assert np.allclose(z["vm_hv"], ref["vm"][0]) and np.allclose(z["epsp"], ref["ep"][0])


def test_t1_tcl_static_tcl85_and_no_branch_without_keys():
    src = open(os.path.join(ROOT, "resources", "tcl", "esl_h3d_extract.tcl"), encoding="ascii").read()
    assert "prev_file \"\" frame0_pass 0 cum_min_incr 1e-5" in src
    assert "if {$f0pass eq \"1\"}" in src and "if {$::esl::has_prev" in src
    for bad in ("lmap", "dict map", "string cat", "lpop"):
        assert bad not in src


def test_w1_write_prev_csv(tmp_path):
    from esl import cumulative as cu
    m = parse_rad(os.path.join(FIX, "issue34", "Scene07_Edge23_2nd_0000.rad"), "Chassis_Rear")
    p = str(tmp_path / "prev.csv")
    assert cu.write_prev_csv(m, p) == 9
    rows = open(p).read().strip().split("\n")
    assert rows[0] == "elem_id,prev_epsp,prev_eq" and rows[1].startswith("100001,0.0325")
