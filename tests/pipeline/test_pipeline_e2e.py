"""T-E2E-1: 합성 사례(max-hold 지표, §7) → CLI --stage all → first-reach t*·F_eq·검증·내보내기. 재개·수동 옵션·오류 경로."""
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

import synth_case
from esl import cli
from esl.io import RESULT_FILES

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
# 합성 사례 변위는 float64 로 저장(write_results_csv) → 잡음 바닥도 float64 기준
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")


def _snapshot(d):
    out = {}
    for base, _, files in os.walk(d):
        for f in files:
            p = os.path.join(base, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def _args(case, out, *extra):
    return ["run", "--config", case["cfg"], "--rad", case["rad"], "--results", case["csv"], "--out", out, *extra]


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("e2e"))
    c = synth_case.build(root)
    c["root"] = root
    c["cfg"] = os.path.join(root, "esl64.yaml")
    assert "disp_precision: float64" in CFG64_TEXT
    with open(c["cfg"], "w", encoding="utf-8") as fh:
        fh.write(CFG64_TEXT)
    c["in_snapshot"] = _snapshot(os.path.join(root, "in"))
    out = os.path.join(root, "out")
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "esl", *_args(c, out, "--stage", "all")], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    c["elapsed"] = time.perf_counter() - t0
    c["proc"] = p
    c["out"] = out
    return c


def _copy_out(case, tmp_path):
    dst = str(tmp_path / "out")
    shutil.copytree(case["out"], dst)
    return dst


def test_e2e_all(case):
    p = case["proc"]
    assert p.returncode == 0, p.stderr
    for key in ("[extract]", "[tstar]", "[esl]", "[validate]", "[export]", "[report]", "PASS", "t* = frame 6"):
        assert key in p.stdout
    out = case["out"]
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["error"] is None and set(run["stages"]) == {"extract", "tstar", "esl", "validate", "export", "report"}
    assert all(s["status"] == "done" and s["elapsed_s"] >= 0 for s in run["stages"].values())
    assert len(run["inputs"]["rad"]["sha256"]) == 64
    assert set(run["inputs"]["results_files"]) == set(RESULT_FILES)
    assert run["config"]["snapshot"]["case"]["part_title"] == "chassis rear"

    # 추출: 전단 규약 auto → 공학 전단(합성 XY = γ), D = 두 지표 후보 합집합
    ex = run["stages"]["extract"]["summary"]
    assert ex["shear"]["convention"] == "engineering" and ex["shear"]["max_rel_mismatch"] < 1e-6
    assert ex["frames_D"] == sorted({synth_case.T_STAR_FRAME, synth_case.SECOND_PEAK_FRAME})
    assert ex["n_hot"] == 200
    for fn in ("final.npz", "history.npz", "strain_frames.npz", "disp.npz"):
        assert os.path.isfile(os.path.join(out, "01_extract", fn))
    assert not os.path.exists(os.path.join(out, "01_extract", "strain_tensor.npz"))

    # t* (first-reach): 지표 2개 모두 기록, TCL D 와 Python 재계산 일치
    tj = json.load(open(os.path.join(out, "02_tstar", "tstar.json"), encoding="utf-8"))
    assert tj["metric"] == "max_strain" and tj["selected"]["frame_index"] == synth_case.T_STAR_FRAME
    assert [c["frame_index"] for c in tj["candidates"]] == [synth_case.T_STAR_FRAME, synth_case.SECOND_PEAK_FRAME]
    assert set(tj["metrics"]) == {"max_strain", "plastic_strain"}
    for m, rec in tj["metrics"].items():
        assert rec["tstar"]["frame_index"] == synth_case.T_STAR_FRAME, m
        assert rec["tcl_check"]["match"] is True, (m, rec["tcl_check"])
        assert len(rec["history"]["m"]) == len(synth_case.A_T)
    # first-reach 정의 재확인: rank 1 요소의 max-hold 값은 t* 에서 처음 최종값에 도달
    e1 = list(case["elem_id"]).index(tj["selected"]["elem_id"])
    eqh = case["eq_hold"][:, e1]
    assert eqh[synth_case.T_STAR_FRAME] == eqh[-1] > eqh[synth_case.T_STAR_FRAME - 1]
    assert tj["selected"]["value"] == pytest.approx(case["eq_hold"][-1].max(), rel=1e-6)
    assert all(h["rising"] for h in tj["hotspots"])
    with open(os.path.join(out, "02_tstar", "candidates.csv"), encoding="utf-8") as fh:
        assert sum(1 for line in fh if line.startswith("plastic_strain,")) == 2

    # 강체 대회전 확인 + F_eq
    summ = json.load(open(os.path.join(out, "04_esl", "esl_summary.json"), encoding="utf-8"))
    assert summ["kabsch"]["rot_deg"] >= 20.0
    assert summ["noise"]["disp_precision"] == "float64"
    assert summ["noise"]["force_rel"] < 1e-3 and summ["noise"]["hotspot_strain_rel"] < 1e-6
    z = np.load(os.path.join(out, "04_esl", "f_eq.npz"), allow_pickle=False)
    assert np.array_equal(z["node_id"], case["node_id"])
    f, Fa, R = z["f"], case["F_app"], case["R"]
    si = [i for i, _ in case["sup"]]
    free = np.ones(len(f), bool)
    free[si] = False
    ref = np.abs(Fa).max()
    err_free = np.abs(f[free] - Fa[free]).max() / ref
    err_sup = np.abs(f[si] - R[si]).max() / ref
    assert err_free < 1e-6, err_free
    assert err_sup < 1e-6, err_sup
    assert np.array_equal(np.flatnonzero(z["is_bc"]), np.sort(si))
    sup = json.load(open(os.path.join(out, "03_bc", "support.json"), encoding="utf-8"))
    assert [s["node_id"] for s in sup["supports"]] == case["sup_ids"]

    # 검증
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    m = {x["metric"]: x["value"] for x in val["metrics"]}
    assert val["verdict"] == "PASS" and val["fail_reasons"] == []
    assert m["noise_hotspot_strain_rel"] < 1e-6
    assert m["disp_rms_rel"] < 1e-8
    assert m["reaction_rel"] < 1e-8
    assert m["hotspot1_strain_rel_err"] < 1e-6        # float32 저장 한계
    assert len(val["hotspots"]) == val["criteria"]["hotspot_eval_count"] == 3
    assert all(h["rel_err"] < 1e-6 for h in val["hotspots"])
    assert val["hotspots"][0]["elem_id"] == tj["selected"]["elem_id"]          # rank 1 포함
    assert val["criteria"]["layers"] == ["mid"]
    assert val["criteria"]["disp_rms_rel_max"] == 0.01      # 설정 스냅샷

    # 전 요소 재현 정확도(계약 esl_p2_library.md §7.2): 같은 솔버로 만든 합성 → 오차 ≈ 0 → PASS
    fs = val["field"]
    assert m["field_max_err_pct"] < 1e-4 and m["field_p90_err_pct"] < 1e-4
    assert fs["prev_source"] == "strain_frames" and fs["prev_frame_index"] == synth_case.T_STAR_FRAME - 1
    assert fs["max"]["elem_id"] == tj["selected"]["elem_id"]                 # 최대변형률 요소 = t* rank 1
    assert fs["max"]["eps_rad"] == pytest.approx(tj["selected"]["value"], rel=1e-6)
    assert fs["max"]["eps_esl_max_elem_id"] == fs["max"]["elem_id"]
    assert fs["frac_within"] == {"5": 1.0, "10": 1.0, "20": 1.0}
    assert fs["n_valid"] > 0.5 * fs["n_elems"] and fs["n_hold"] > 0          # 패턴 2 부근은 hold(비교 불가)
    assert fs["n_valid"] + fs["n_hold"] + fs["n_low"] + fs["n_excluded"] + fs["n_no_prev"] == fs["n_elems"]
    assert len(fs["top"]) == 20 and len(fs["hist"]["counts"]) == 20 and sum(fs["hist"]["counts"]) == fs["n_valid"]
    assert fs["criteria"] == {"max_err_pct_max": 10.0, "p90_err_max": 20.0}
    z = np.load(os.path.join(out, "05_val", "compare_field.npz"), allow_pickle=False)
    E = len(case["elem_id"])
    assert np.array_equal(z["elem_id"], case["elem_id"]) and z["reason"].dtype == np.int8
    assert z["centroid2d"].shape == (E, 2) and z["centroid3d"].shape == (E, 3)
    for k in ("eps_rad", "eps_esl", "rel_err", "valid", "n0", "w_rel", "w_val"):
        assert z[k].shape == (E,), k
    assert int(z["valid"].sum()) == fs["n_valid"] and np.all(z["reason"][z["valid"]] == 0)
    # rising 정의 재확인: 순간 ε 가 직전 프레임 hold 보다 크면 상승 중
    eqh = case["eq_hold"]
    ft = synth_case.T_STAR_FRAME
    rising = eqh[ft] > eqh[ft - 1] * (1 + 1e-6)
    assert np.array_equal(z["rising"], rising)
    for a in ("xi", "eta"):                      # 단면선(ξ·η = 0.5): 전체 solve → u_val ≈ u_rel
        assert z[f"sec_{a}_s"].size > 5 and np.allclose(z[f"sec_{a}_w_val"], z[f"sec_{a}_w_rel"], atol=1e-8)
        assert np.all(np.diff(z[f"sec_{a}_s"]) > 0)
    assert np.abs(z["w_rel"]).max() > 0.1                                   # 면외 변형이 있음
    rep = os.path.join(out, "07_report", "report.html")
    assert os.path.getsize(rep) > 10_000 and run["stages"]["report"]["summary"]["verdict"] == "PASS"

    # 내보내기 파일·ID 범위
    exp = os.path.join(out, "06_export")
    for fn in ("esl_cload.inc", "esl_bcs.inc", "esl_force.fem", "f_eq.csv", "u_rel.csv", "reactions_321.csv",
               "tstar_candidates.csv", "hotspots.csv", "validation.csv"):
        assert os.path.getsize(os.path.join(exp, fn)) > 0, fn
    off = 9000000
    ids = []
    for fn in ("esl_cload.inc", "esl_bcs.inc"):
        for line in open(os.path.join(exp, fn), encoding="utf-8"):
            if line.startswith(("/FUNCT/", "/GRNOD/NODE/", "/CLOAD/", "/BCS/")):
                ids.append(int(line.strip().split("/")[-1]))
    for line in open(os.path.join(exp, "esl_force.fem"), encoding="utf-8"):
        if line.startswith("PSHELL,"):
            ids.append(int(line.split(",")[1]))
        if line.startswith(("FORCE,", "SPC1,")):
            ids.append(int(line.split(",")[1]))
    assert ids and all(off <= v <= off + 999999 for v in ids)
    for fn in ("esl_cload.inc", "esl_bcs.inc", "esl_force.fem"):         # inc·fem 전체 ASCII
        assert all(b < 128 for b in open(os.path.join(exp, fn), "rb").read()), fn
    # 비영 성분 수 = /CLOAD 수
    n_cload = sum(1 for line in open(os.path.join(exp, "esl_cload.inc"), encoding="utf-8")
                  if line.startswith("/CLOAD/"))
    fe = np.abs(f) > 1e-9 * np.linalg.norm(f, axis=1).max()
    assert n_cload == int(fe.sum())

    # 입력 폴더 무변경
    assert _snapshot(os.path.join(case["root"], "in")) == case["in_snapshot"]
    print(f"\nE2E: F_eq err free={err_free:.2e} sup={err_sup:.2e}, disp_rms_rel={m['disp_rms_rel']:.2e}, "
          f"reaction={m['reaction_rel']:.2e}, elapsed {case['elapsed']:.2f}s")


def test_resume_stage_esl_moves_old_to_backup(case, tmp_path, capsys):
    out = _copy_out(case, tmp_path)
    old = open(os.path.join(out, "04_esl", "f_eq.csv"), "rb").read()
    assert cli.main(_args(case, out, "--stage", "esl")) == 0
    bk = os.path.join(out, "_backup")
    stamps = os.listdir(bk)
    assert len(stamps) == 1
    moved = os.path.join(bk, stamps[0])
    assert open(os.path.join(moved, "04_esl", "f_eq.csv"), "rb").read() == old
    assert os.path.isfile(os.path.join(moved, "03_bc", "support.json"))
    assert os.path.isfile(os.path.join(moved, "run.json"))
    assert os.path.isfile(os.path.join(out, "04_esl", "f_eq.csv"))
    # 다른 단계는 건드리지 않음
    assert not os.path.exists(os.path.join(moved, "01_extract"))
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["stages"]["validate"]["stale"] is True and run["stages"]["export"]["stale"] is True
    assert run["stages"]["esl"]["stale"] is False
    assert len(run["history"]) == 2
    # 이어서 validate 단계만
    assert cli.main(_args(case, out, "--stage", "validate")) == 0
    assert "PASS" in capsys.readouterr().out


def test_frame_manual_second_candidate(case, tmp_path):
    out = _copy_out(case, tmp_path)
    assert cli.main(_args(case, out, "--stage", "esl", "--frame", str(synth_case.SECOND_PEAK_FRAME))) == 0
    f = np.load(os.path.join(out, "04_esl", "f_eq.npz"), allow_pickle=False)["f"]
    k = synth_case.SECOND_PEAK_FRAME
    a, b = synth_case.A_T[k], synth_case.B_T[k]
    expect = a * (case["F_app"] + case["R"]) + b * (case["F2"] + case["R2"])
    assert np.abs(f - expect).max() / np.abs(expect).max() < 1e-6
    summ = json.load(open(os.path.join(out, "04_esl", "esl_summary.json"), encoding="utf-8"))
    assert summ["frame"]["source"] == "user"


def test_frame_not_candidate(case, tmp_path, capsys):
    out = _copy_out(case, tmp_path)
    assert cli.main(_args(case, out, "--stage", "esl", "--frame", "4")) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("FRAME_NOT_CANDIDATE: ") and "\n" not in err
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["error"]["code"] == "FRAME_NOT_CANDIDATE" and run["stages"]["esl"]["status"] == "failed"
    # 실패 전에 기존 산출물을 옮기지 않음
    assert os.path.isfile(os.path.join(out, "04_esl", "f_eq.npz"))


def test_support_nodes_manual_and_not_in_part(case, tmp_path, capsys):
    out = _copy_out(case, tmp_path)
    ids = case["sup_ids"]
    assert cli.main(_args(case, out, "--stage", "esl", "--support-nodes", ",".join(map(str, ids)))) == 0
    sup = json.load(open(os.path.join(out, "03_bc", "support.json"), encoding="utf-8"))
    assert sup["mode"] == "cli" and sorted(s["node_id"] for s in sup["supports"]) == sorted(ids)
    bad = f"{ids[0]},{ids[1]},{case['dummy_node']}"
    assert cli.main(_args(case, out, "--stage", "esl", "--support-nodes", bad)) == 1
    assert capsys.readouterr().err.startswith("NODE_NOT_IN_PART: ")


def test_out_inside_input_rejected(case, capsys):
    out = os.path.join(case["csv"], "out")
    assert cli.main(_args(case, out)) == 1
    assert capsys.readouterr().err.startswith("INPUT_INVALID: ")
    assert not os.path.exists(out)


def test_prerequisite_missing(case, tmp_path, capsys):
    out = str(tmp_path / "empty")
    assert cli.main(_args(case, out, "--stage", "validate")) == 1
    assert capsys.readouterr().err.startswith("PREREQUISITE_MISSING: ")
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["error"]["code"] == "PREREQUISITE_MISSING"


def test_config_error_recorded(case, tmp_path, capsys):
    out = str(tmp_path / "o")
    bad = tmp_path / "bad.yaml"
    bad.write_text(open(CFG, encoding="utf-8").read().replace("frame_stride: 1", "frame_stride: 0"),
                   encoding="utf-8")
    args = ["run", "--config", str(bad), "--rad", case["rad"], "--results", case["csv"], "--out", out]
    assert cli.main(args) == 1
    err = capsys.readouterr().err
    assert err.startswith("CONFIG_INVALID: extract.frame_stride")
    assert json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))["error"]["code"] == "CONFIG_INVALID"


def test_esl_config_env(case, tmp_path, monkeypatch):
    out = _copy_out(case, tmp_path)
    monkeypatch.setenv("ESL_CONFIG", CFG)
    args = ["run", "--rad", case["rad"], "--results", case["csv"], "--out", out, "--stage", "tstar"]
    assert cli.main(args) == 0


def test_export_id_range_collision(case, tmp_path, capsys):
    out = _copy_out(case, tmp_path)
    cfg = tmp_path / "small_offset.yaml"
    cfg.write_text(open(CFG, encoding="utf-8").read().replace("id_offset: 9000000", "id_offset: 50"),
                   encoding="utf-8")
    args = ["run", "--config", str(cfg), "--rad", case["rad"], "--results", case["csv"], "--out", out,
            "--stage", "export"]
    assert cli.main(args) == 1
    assert capsys.readouterr().err.startswith("ID_RANGE_COLLISION: ")
    assert os.path.isfile(os.path.join(out, "06_export", "esl_cload.inc"))     # 기존 산출물 유지


def test_unit_id_ignored_warning(case, tmp_path, capsys):
    """대상 파트의 /PART·/PROP·/MAT·/NODE 헤더 unit_ID ≠ 0 → 변환 없이 경고(run.json·콘솔)."""
    d = tmp_path / "unit_in"
    d.mkdir()
    txt = open(case["rad"], encoding="utf-8").read()
    for a, b in (("/NODE\n", "/NODE/3\n"), ("/PART/7\n", "/PART/7/3\n"), ("/PROP/SHELL/70\n", "/PROP/SHELL/70/3\n"),
                 ("/MAT/LAW1/700\n", "/MAT/LAW1/700/3\n"), ("/MAT/LAW1/701\n", "/MAT/LAW1/701/5\n")):
        assert a in txt
        txt = txt.replace(a, b)
    rad = d / "unit_0000.rad"
    rad.write_text(txt, encoding="utf-8")
    out = str(tmp_path / "o")
    assert cli.main(["run", "--config", case["cfg"], "--rad", str(rad), "--results", case["csv"], "--out", out,
                     "--stage", "extract"]) == 0
    con = capsys.readouterr().out
    w = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))["stages"]["extract"]["warnings"]
    got = sorted(x.split(" — ")[0] for x in w if x.startswith("UNIT_ID_IGNORED"))
    assert got == ["UNIT_ID_IGNORED: /MAT/LAW1/700 unit=3", "UNIT_ID_IGNORED: /NODE unit=3",
                   "UNIT_ID_IGNORED: /PART/7 unit=3", "UNIT_ID_IGNORED: /PROP/SHELL/70 unit=3"]
    assert "unit=5" not in json.dumps(w)              # 대상 파트가 쓰지 않는 카드는 경고 없음
    assert con.count("경고: UNIT_ID_IGNORED") == 4


def test_validate_without_full_solve(case, tmp_path, capsys):
    """validation.full_solve: never → 판정 불가(UNDETERMINED, NO_FULL_SOLVE): 변위·반력 skipped, 변형률은 참고로만 계산
    (계약 esl_disp_primary.md D4 — 변형률로 대신 PASS 하지 않음)."""
    out = _copy_out(case, tmp_path)
    cfg = tmp_path / "nofull.yaml"
    cfg.write_text(open(case["cfg"], encoding="utf-8").read().replace("full_solve: auto", "full_solve: never"),
                   encoding="utf-8")
    args = ["run", "--config", str(cfg), "--rad", case["rad"], "--results", case["csv"], "--out", out,
            "--stage", "validate"]
    assert cli.main(args) == 0
    o = capsys.readouterr().out
    assert "변위 RMS=skipped" in o and "UNDETERMINED" in o and "NO_FULL_SOLVE" in o
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    m = {x["metric"]: x for x in val["metrics"]}
    assert val["verdict"] == "UNDETERMINED" and val["full_solve"]["run"] is False
    assert val["undetermined_reason"] == "NO_FULL_SOLVE" and val["fail_reasons"] == []
    assert m["disp_rms_rel"]["status"] == "skipped" and m["disp_rms_rel"]["pass"] is None
    assert m["reaction_rel"]["status"] == "skipped" and val["reactions"] == []
    assert m["hotspot1_strain_rel_err"]["value"] < 1e-6 and len(val["hotspots"]) == 3
    assert not os.path.exists(os.path.join(out, "05_val", "compare.csv"))
    # 전 요소 비교는 full_solve=never 에서도 동작(u_rel + 응축 회전 → ESL 막 변형률), 참고 지표로만
    assert m["field_max_err_pct"]["value"] < 1e-4 and m["field_p90_err_pct"]["exceeded"] is False


def test_full_solve_auto_memory_decision(monkeypatch):
    from esl import config, pipeline
    cfg = config.load_config(CFG)
    ctx = pipeline.Context(cfg=cfg, config_path="", rad="", results="", out="", ts="", frame=None,
                           support_nodes=None, echo=print, record={})

    class Direct:
        pass

    monkeypatch.setattr(pipeline, "available_memory", lambda: 512 * 2 ** 30)
    d = pipeline.full_solve_decision(ctx, Direct(), 300_000)            # 30만 요소 ≈ 24 GB 추정 < 512 GB
    assert d["run"] is True and d["mem_need_est"] == pytest.approx(2.4e10)
    monkeypatch.setattr(pipeline, "available_memory", lambda: 15 * 2 ** 30)
    d = pipeline.full_solve_decision(ctx, Direct(), 300_000)
    assert d["run"] is False and "GB" in d["reason"]
    it = Direct()
    it.is_direct = False
    monkeypatch.setattr(pipeline, "available_memory", lambda: None)
    assert pipeline.full_solve_decision(ctx, it, 10)["run"] is True      # 반복법: 메모리 추정 무관, rtol≤1e-12
    assert pipeline.full_solve_decision(ctx, Direct(), 10 ** 9)["run"] is True    # 모르면 수행(상한 거부 없음)
    cfg["validation"]["full_solve"] = "always"
    monkeypatch.setattr(pipeline, "available_memory", lambda: 1)
    assert pipeline.full_solve_decision(ctx, it, 300_000)["run"] is True


def test_solver_stats_recorded(case):
    """ShellModel.stats 가 esl_summary.json·run.json(esl·validate 요약)에 기록된다."""
    out = case["out"]
    summ = json.load(open(os.path.join(out, "04_esl", "esl_summary.json"), encoding="utf-8"))
    from esl.mech.shell import available_backends
    assert summ["solver"]["backend"] == available_backends()[0] and summ["solver"]["backend_requested"] == "auto"
    assert "K_rr" in summ["solver"] and summ["solver"]["n_elems"] > 0
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["stages"]["esl"]["summary"]["solver"]["K_rr"]["backend_used"]
    assert "K_ff" in run["stages"]["validate"]["summary"]["solver"]


def test_validate_iterative_backend_rtol(case, tmp_path, capsys):
    """solver.backend=iterative: S5 전체계 solve 수행(auto), rtol = min(설정 iter_rtol, 1e-12), stats 기록."""
    out = _copy_out(case, tmp_path)
    cfg = tmp_path / "iter.yaml"
    cfg.write_text(open(case["cfg"], encoding="utf-8").read()
                   .replace("backend: auto", "backend: iterative").replace("iter_maxiter: null", "iter_maxiter: 50000"),
                   encoding="utf-8")
    args = ["run", "--config", str(cfg), "--rad", case["rad"], "--results", case["csv"], "--out", out,
            "--stage", "validate"]
    assert cli.main(args) == 0, capsys.readouterr()
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    assert val["full_solve"]["run"] is True and val["verdict"] == "PASS"
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    st = run["stages"]["validate"]["summary"]["solver"]
    assert st["backend"] == "iterative" and st["K_ff"]["backend_used"] == "iterative"
    assert max(st["K_ff"]["resid_rel"]) <= 1e-8
    assert st["K_ff"]["rtol"] == 1e-12 and st["K_ff"]["maxiter"] == 50000


def test_config_solver_iter_keys(tmp_path):
    from esl import config
    from esl.errors import EslError
    import yaml
    cfg = config.load_config(CFG)
    assert cfg["solver"]["iter_rtol"] == 1e-10 and cfg["solver"]["iter_maxiter"] is None
    for key, bad in (("iter_rtol", 0.0), ("iter_rtol", 1.0), ("iter_maxiter", 0), ("iter_maxiter", 1.5)):
        c = yaml.safe_load(open(CFG, encoding="utf-8"))
        c["solver"][key] = bad
        with pytest.raises(EslError) as ei:
            config.validate_settings(c)
        assert f"solver.{key}" in ei.value.message
    c = yaml.safe_load(open(CFG, encoding="utf-8"))
    c["extract"]["hot_k"] = 5000                                     # 상한 없음
    assert config.validate_settings(c)["extract"]["hot_k"] == 5000


def test_export_targets_only_selected(case, tmp_path, capsys):
    """export_targets: 선택한 대상 파일만 생성(csv 만이면 ID 계획·충돌 검사 생략)."""
    from esl import pipeline
    out = _copy_out(case, tmp_path)
    base = ["run", "--config", case["cfg"], "--rad", case["rad"], "--results", case["csv"], "--out", out,
            "--stage", "export"]
    assert cli.main(base + ["--export-targets", "csv"]) == 0
    files = sorted(os.listdir(os.path.join(out, "06_export")))
    assert files == ["f_eq.csv", "hotspots.csv", "reactions_321.csv", "tstar_candidates.csv", "u_rel.csv",
                     "validation.csv"]
    rec = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))["stages"]["export"]["summary"]
    assert rec["targets"] == ["csv"] and rec["id_range"] is None
    assert cli.main(base + ["--export-targets", "fem"]) == 0
    assert sorted(os.listdir(os.path.join(out, "06_export"))) == ["esl_force.fem"]
    assert cli.main(base + ["--export-targets", "radioss_inc,csv"]) == 0
    got = set(os.listdir(os.path.join(out, "06_export")))
    assert {"esl_cload.inc", "esl_bcs.inc", "f_eq.csv"} <= got and "esl_force.fem" not in got
    capsys.readouterr()
    assert cli.main(base + ["--export-targets", "xls"]) == 1
    assert capsys.readouterr().err.startswith("INPUT_INVALID: ")
    with pytest.raises(Exception):
        pipeline.normalize_export_targets([])


def test_export_ignores_validation_of_other_esl(case, tmp_path):
    """validation.json 의 esl_ref 가 현재 esl_summary.json 과 다르면 내보내기에 검증 결과를 쓰지 않음."""
    from esl import pipeline
    out = _copy_out(case, tmp_path)
    kw = dict(rad=case["rad"], results=case["csv"], out=out, config_path=case["cfg"], echo=lambda m: None)
    pipeline.run(stage="esl", tag="run-A", **kw)
    pipeline.run(stage="validate", **kw)
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    assert val["esl_ref"] == "run-A"
    pipeline.run(stage="esl", tag="run-B", **kw)           # 04_esl = B, 05_val = A 의 검증
    rec = pipeline.run(stage="export", export_targets=["csv"], **kw)
    s = rec["stages"]["export"]
    assert s["summary"]["validation_used"] is False and s["summary"]["esl_ref"] == "run-B"
    assert "validation.csv" not in os.listdir(os.path.join(out, "06_export"))
    assert any("현재 ESL" in w for w in s["warnings"])


def _set_cfg(src, dst, *pairs):
    txt = open(src, encoding="utf-8").read()
    for a, b in pairs:
        assert a in txt, a
        txt = txt.replace(a, b)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return str(dst)


def test_field_distorted_radioss_strain_is_reference_only(case, tmp_path, capsys):
    """의도적 왜곡: 합성 Radioss ε(strain_frames 의 t*·직전 프레임 텐서)를 10% 키움 →
    rel_err = 1/1.1 − 1 = −9.09% 가 전 valid 요소에 균일 → 기준 5% 초과는 "참고 초과"일 뿐 판정은 변위 기준이라 PASS
    (0.5.7, 계약 esl_disp_primary.md D1·D2)."""
    out = _copy_out(case, tmp_path)
    p = os.path.join(out, "01_extract", "strain_frames.npz")
    z = dict(np.load(p, allow_pickle=False))
    for k in ("eps", "prev_eps", "vm_hv", "prev_vm_hv"):
        z[k] = (z[k] * np.float32(1.1)).astype(np.float32)
    np.savez_compressed(p, **z)
    expect = 100.0 * (1.0 / 1.1 - 1.0)
    cfg = _set_cfg(case["cfg"], tmp_path / "c.yaml", ("max_err_pct_max: 10.0", "max_err_pct_max: 5.0"),
                   ("p90_err_max: 20.0", "p90_err_max: 5.0"))
    args = ["run", "--config", cfg, "--rad", case["rad"], "--results", case["csv"], "--out", out, "--stage", "validate"]
    assert cli.main(args) == 0
    o = capsys.readouterr().out
    assert "→ PASS" in o and "[참고 초과]" in o
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    fs = val["field"]
    m = {x["metric"]: x for x in val["metrics"]}
    assert fs["max"]["err_pct"] == pytest.approx(expect, abs=1e-3)            # ≈ −9.09 %
    assert m["field_max_err_pct"]["value"] == pytest.approx(-expect, abs=1e-3)
    assert m["field_max_err_pct"]["pass"] is None and m["field_max_err_pct"]["exceeded"] is True
    assert fs["abs_err_pct"]["p90"] == pytest.approx(-expect, abs=1e-3) and fs["frac_within"]["5"] == 0.0
    assert val["verdict"] == "PASS" and val["fail_reasons"] == [] and val["strain_ref"]["exceeded"] is True
    assert val["strain_ref"]["n_exceed"] == val["strain_ref"]["n_valid"] > 0          # 균일 −9.09% > 5% 인 valid 전부
    # 기본 기준(10%·20%)이면 9.09% 는 초과 아님 — hotspot 기준(10%)도 마찬가지
    assert cli.main(args[:2] + [case["cfg"]] + args[3:]) == 0
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    assert val["verdict"] == "PASS" and val["field"]["max"]["abs_err_pct"] == pytest.approx(-expect, abs=1e-3)
    assert val["strain_ref"]["exceeded"] is False and val["strain_ref"]["n_exceed"] == 0
    # 15% 키우면 기본 기준으로도 최대변형률 오차 "참고 초과"(판정은 그대로 PASS)
    z2 = dict(z)
    for k in ("eps", "prev_eps", "vm_hv", "prev_vm_hv"):
        z2[k] = (z[k] / np.float32(1.1) * np.float32(1.15)).astype(np.float32)
    np.savez_compressed(p, **z2)
    assert cli.main(args[:2] + [case["cfg"]] + args[3:]) == 0
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    m = {x["metric"]: x for x in val["metrics"]}
    assert m["field_max_err_pct"]["exceeded"] is True and m["field_p90_err_pct"]["exceeded"] is False
    assert val["verdict"] == "PASS" and val["fail_reasons"] == [] and set(val["strain_ref"]["exceeded_metrics"]) == {
        "hotspot1_strain_rel_err", "field_max_err_pct"}


def test_field_old_extract_without_prev_uses_history(case, tmp_path):
    """예전 추출(strain_frames.npz 에 prev_* 없음) → H 요소만 history 로 상승 판정, 나머지 NO_PREV + 경고."""
    out = _copy_out(case, tmp_path)
    p = os.path.join(out, "01_extract", "strain_frames.npz")
    z = {k: v for k, v in np.load(p, allow_pickle=False).items() if not k.startswith("prev_")}
    np.savez_compressed(p, **z)
    rec = __import__("esl.pipeline", fromlist=["run"]).run(
        config_path=case["cfg"], rad=case["rad"], results=case["csv"], out=out, stage="validate", echo=lambda m: None)
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    fs = val["field"]
    assert fs["prev_source"] == "history_H" and fs["n_no_prev"] == len(case["elem_id"]) - 200
    assert 0 < fs["n_valid"] <= 200 and val["verdict"] == "PASS"
    assert any("NO_PREV" in w for w in rec["stages"]["validate"]["warnings"])


def test_report_failure_keeps_previous_stages(case, tmp_path, monkeypatch, capsys):
    """--stage all 에서 report 가 실패해도 run 은 성공, 앞 단계 산출물 유지, run.json stages.report = failed."""
    from esl import pipeline
    from esl.report import case_report

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(case_report, "build_case_report", boom)
    out = str(tmp_path / "o")
    rec = pipeline.run(config_path=case["cfg"], rad=case["rad"], results=case["csv"], out=out, stage="all",
                       echo=print)
    assert rec["error"] is None and rec["stages"]["report"]["status"] == "failed"
    assert rec["stages"]["report"]["error"]["code"] == "INTERNAL_ERROR"
    assert rec["stages"]["export"]["status"] == "done"
    assert os.path.isfile(os.path.join(out, "06_export", "esl_cload.inc"))
    assert "보고서 생성 실패" in capsys.readouterr().out
    # report 단계만 직접 실행하면 오류로 보고
    with pytest.raises(RuntimeError):
        pipeline.run(config_path=case["cfg"], rad=case["rad"], results=case["csv"], out=out, stage="report",
                     echo=lambda m: None)
