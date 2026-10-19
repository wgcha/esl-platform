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
    for key in ("[extract]", "[tstar]", "[esl]", "[validate]", "[export]", "PASS", "t* = frame 6"):
        assert key in p.stdout
    out = case["out"]
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["error"] is None and set(run["stages"]) == {"extract", "tstar", "esl", "validate", "export"}
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
    """validation.full_solve: never → hotspot 변형률(u_rel + 응축 회전)만 비교, disp·반력 skipped, 판정은 hotspot."""
    out = _copy_out(case, tmp_path)
    cfg = tmp_path / "nofull.yaml"
    cfg.write_text(open(case["cfg"], encoding="utf-8").read().replace("full_solve: auto", "full_solve: never"),
                   encoding="utf-8")
    args = ["run", "--config", str(cfg), "--rad", case["rad"], "--results", case["csv"], "--out", out,
            "--stage", "validate"]
    assert cli.main(args) == 0
    o = capsys.readouterr().out
    assert "disp_rms_rel=skipped" in o and "PASS" in o
    val = json.load(open(os.path.join(out, "05_val", "validation.json"), encoding="utf-8"))
    m = {x["metric"]: x for x in val["metrics"]}
    assert val["verdict"] == "PASS" and val["full_solve"]["run"] is False
    assert m["disp_rms_rel"]["status"] == "skipped" and m["disp_rms_rel"]["pass"] is None
    assert m["reaction_rel"]["status"] == "skipped" and val["reactions"] == []
    assert m["hotspot1_strain_rel_err"]["value"] < 1e-6 and len(val["hotspots"]) == 3
    assert not os.path.exists(os.path.join(out, "05_val", "compare.csv"))
    assert cli.main(args[:-1] + ["export"]) == 0                       # 내보내기는 그대로 동작


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
