"""T-E2E-1: 합성 사례 → CLI --stage all → t*·F_eq·검증·내보내기. 재개·수동 옵션·오류 경로."""
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
    assert set(run["inputs"]["results_files"]) == {"frames.csv", "model.csv", "strain.csv", "disp.csv", "done.json"}
    assert run["config"]["snapshot"]["case"]["part_title"] == "chassis rear"

    # t*
    tj = json.load(open(os.path.join(out, "02_tstar", "tstar.json"), encoding="utf-8"))
    assert tj["selected"]["frame_index"] == synth_case.T_STAR_FRAME
    assert [c["frame_index"] for c in tj["candidates"]] == [synth_case.T_STAR_FRAME, synth_case.SECOND_PEAK_FRAME]

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
    assert all(h["rel_err"] < 1e-6 for h in val["hotspots"])
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
    a = synth_case.A_T[synth_case.SECOND_PEAK_FRAME]
    expect = a * (case["F_app"] + case["R"])
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
