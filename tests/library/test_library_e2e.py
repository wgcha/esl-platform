"""P2 합성 E2E: 코어 합성 Case(크기 1.0/1.2배 · 메시 밀도 3종 · 하중 패턴 2종) 6개 → run --stage all → register →
analyze(대상 = 하나) → 대표 케이스가 두 패턴을 각각 대표 · 매핑 보존 · optdeck · HTML 보고서(외부 URL 0) · 스크린샷.
"""
import csv
import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest

import synth_lib
from esl import cli as core_cli
from esl.library import analysis
from esl.library import cli as lcli
from esl.library import store
from esl.mech.shell import ShellModel

ROOT = synth_lib.ROOT
LCFG = os.path.join(ROOT, "config", "library.example.yaml")
HERE = os.path.dirname(os.path.abspath(__file__))
# (모델, 배율, nx, ny, 패턴, 변위 크기, orient)
SPECS = [("50QX10A", 1.0, 24, 16, "A", 1.0, "Corner146"), ("60QX10A", 1.2, 30, 20, "A", 0.9, "Corner235"),
         ("50QX10A", 1.0, 30, 20, "B", 1.0, "Edge34"), ("60QX10A", 1.2, 24, 16, "B", 1.1, "Face3"),
         ("50QX10A", 1.0, 36, 24, "A", 1.3, "Edge12"), ("60QX10A", 1.2, 36, 24, "B", 0.8, "Face6")]


def _snapshot(d):
    out = {}
    for base, _, files in os.walk(d):
        for f in files:
            p = os.path.join(base, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def _lib(*args):
    lines = []
    rc = lcli.main(list(args), echo=lines.append)
    return rc, "\n".join(lines)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    base = str(tmp_path_factory.mktemp("lib_e2e"))
    cfg = synth_lib.config64(os.path.join(base, "esl64.yaml"))
    cases = []
    for k, (model, sc, nx, ny, pat, amp, ori) in enumerate(SPECS):
        dt = {"C": "Corner", "E": "Edge", "F": "Face"}[ori[0]]
        h3d = f"F:/Hyper_work/VD_26y/{model}/{model}_v001_261019/FREE/{k + 1:02d}_{dt}_Drop_1st_Scene{k + 1}_{ori}_comp.h3d"
        cdir = os.path.join(base, f"case{k}")
        c = synth_lib.build(cdir, h3d, sc, nx, ny, pat, amp)
        out = os.path.join(cdir, "out")
        rc = core_cli.main(["run", "--config", cfg, "--rad", c["rad"], "--results", c["csv"], "--out", out,
                            "--stage", "all"])
        assert rc == 0, f"core run failed for case {k}"
        c.update(out=out, spec=SPECS[k])
        cases.append(c)
    root = os.path.join(base, "esl_root")
    snaps = [_snapshot(c["out"]) for c in cases]
    ids = []
    for c in cases:
        rc, txt = _lib("register", "--root", root, "--case", c["out"], "--config", LCFG, "--by", "tester")
        assert rc == 0, txt
        ids.append(re.search(r"\[register\] (E[0-9a-f]{12})", txt).group(1))
    return {"base": base, "cases": cases, "root": root, "ids": ids, "snaps": snaps, "cfg": cfg}


def test_register_index_and_inputs_untouched(lib):
    for c, s in zip(lib["cases"], lib["snaps"]):
        assert _snapshot(c["out"]) == s                               # Case 폴더(입력)에 쓰지 않음
    idx = store.read_index(lib["root"])
    assert set(idx) == set(lib["ids"])
    r0 = idx[lib["ids"][0]]
    assert (r0["product"], r0["inch"], r0["drop_class"], r0["orient"], r0["scene"], r0["verdict"], r0["scenario"]) == \
        ("50QX10A", 50, "Corner", "146", 1, "PASS", "FREE")
    rc, txt = _lib("list", "--root", lib["root"], "--filter", "drop_class=Corner")
    assert rc == 0 and txt.strip().endswith("2개")
    e = store.load_entry(lib["root"], lib["ids"][1], raw=True)
    m = e.meta
    assert m["model"]["inch"] == 60 and m["scene"]["faces"] == [2, 3, 5] and m["quality"]["verdict"] == "PASS"
    assert all(len(v["sha256"]) == 64 for v in m["source"]["files"].values())
    assert m["grid"] == {"nx": 24, "ny": 14, "top_n": 50} and len(m["summary"]["top"]) == 10
    assert np.allclose(e.summary["cell_F"].sum(axis=(0, 1)), e.raw["f"].sum(axis=0), atol=1e-9)
    assert abs(m["frame"]["L_xi"] - 360.0) < 1e-6 and abs(m["frame"]["L_eta"] - 240.0) < 1e-6


def test_register_rules(lib, tmp_path, capsys):
    c0 = lib["cases"][0]["out"]
    rc, _ = _lib("register", "--root", lib["root"], "--case", c0, "--config", LCFG)
    assert rc == 1 and "ENTRY_EXISTS" in capsys.readouterr().err
    rc, _ = _lib("register", "--root", os.path.join(c0, "lib"), "--case", c0, "--config", LCFG)
    assert rc == 1 and "INPUT_INVALID" in capsys.readouterr().err
    assert not os.path.exists(os.path.join(c0, "lib"))
    # 검증 FAIL → 거부, --confirm-fail 로 확정 등록, run 스냅샷(runs/<id>/) 사용, 정정(supersedes) → retired
    cp = str(tmp_path / "case_fail")
    shutil.copytree(c0, cp)
    vp = os.path.join(cp, "05_val", "validation.json")
    v = json.load(open(vp, encoding="utf-8"))
    v["verdict"] = "FAIL"
    v["fail_reasons"] = ["HOTSPOT_STRAIN"]
    json.dump(v, open(vp, "w", encoding="utf-8"))
    root2 = str(tmp_path / "root2")
    rc, _ = _lib("register", "--root", root2, "--case", cp, "--config", LCFG)
    assert rc == 1 and "VALIDATION_NOT_PASS" in capsys.readouterr().err
    rc, txt = _lib("register", "--root", root2, "--case", cp, "--config", LCFG, "--confirm-fail", "누적 소성 영역 허용")
    assert rc == 0, txt
    old = re.search(r"(E[0-9a-f]{12})", txt).group(1)
    assert store.load_entry(root2, old).meta["quality"]["confirmed_fail"]["reason"] == "누적 소성 영역 허용"
    for sub in ("03_bc", "04_esl"):
        shutil.copytree(os.path.join(cp, sub), os.path.join(cp, "runs", "R7", sub))
    rc, txt = _lib("register", "--root", root2, "--case", cp, "--config", LCFG, "--run-id", "R7",
                   "--confirm-fail", "정정", "--supersedes", old)
    assert rc == 0, txt
    new = re.search(r"(E[0-9a-f]{12})", txt).group(1)
    assert new != old
    idx = store.read_index(root2)
    assert idx[old]["status"] == "retired" and idx[old]["superseded_by"] == new
    assert [r["entry_id"] for r in store.query(root2)] == [new]
    assert store.load_entry(root2, new).meta["source"]["snapshot_dir"].endswith(os.path.join("runs", "R7"))
    rc, txt = _lib("retire", "--root", root2, "--entry", new, "--reason", "시험")
    assert rc == 0 and store.query(root2) == [] and len(store.query(root2, include_retired=True)) == 2


@pytest.fixture(scope="module")
def analyzed(lib):
    rc, txt = _lib("analyze", "--root", lib["root"], "--config", LCFG, "--target", lib["ids"][0], "--id", "AE2E",
                   "--n-representative", "2")
    assert rc == 0, txt
    d = store.analysis_dir(lib["root"], "AE2E")
    res = json.load(open(os.path.join(d, "analysis.json"), encoding="utf-8"))
    with np.load(os.path.join(d, "mapped_loads.npz"), allow_pickle=False) as z:
        arr = {k: z[k] for k in z.files}
    return {"dir": d, "res": res, "arr": arr, "txt": txt}


def test_representatives_cover_both_patterns(lib, analyzed):
    res = analyzed["res"]
    pid = {e: c["pattern"] for e, c in zip(lib["ids"], lib["cases"])}
    pat = {c["index"]: pid[c["entry_id"]] for c in res["cases"]}
    assert [c["entry_id"] for c in res["cases"]] == lib["ids"]          # 색인(등록) 순서
    lab = {c["index"]: c["cluster"] for c in res["cases"]}
    for p in ("A", "B"):
        assert len({lab[i] for i in pat if pat[i] == p}) == 1          # 같은 패턴 = 한 클러스터
    assert lab[0] != lab[2] and pat[0] == "A" and pat[2] == "B"
    meds = [lc["case_index"] for lc in res["load_cases"] if lc["role"] == "medoid"]
    assert sorted(pat[m] for m in meds) == ["A", "B"]                  # 대표가 두 패턴을 각각 대표
    assert all(res["cases"][m]["is_medoid"] for m in meds)
    # 패턴 내 거리 ≪ 패턴 간 거리 (크기 1.0/1.2배·메시 밀도와 무관)
    D = analyzed["arr"]["dist"]
    same = [D[i, j] for i in pat for j in pat if i < j and pat[i] == pat[j]]
    diff = [D[i, j] for i in pat for j in pat if pat[i] != pat[j]]
    assert max(same) < 0.1 * min(diff), (max(same), min(diff))


def test_mapping_conservation_and_outputs(lib, analyzed):
    res, arr, d = analyzed["res"], analyzed["arr"], analyzed["dir"]
    assert res["cases"][0]["self"] is True
    tgt = store.load_entry(lib["root"], lib["ids"][0], raw=True)
    # mapped_loads.npz = 덱에 들어간 케이스 전부(§12.1 기본 all → 모든 씬)
    assert res["deck"]["mode"] == "all" and res["deck"]["n_subcases"] == 6
    assert arr["mapped_F"].shape == (6, tgt.raw["node_id"].size, 3)
    assert arr["load_case_index"].tolist() == list(range(6))
    for lc, f in zip(res["load_cases"], analysis.load_case_forces(res, arr)):
        if res["cases"][lc["case_index"]]["self"]:
            assert np.allclose(f, tgt.raw["f"])
    m = res["mapping"]
    assert m["n_self"] == 1 and m["n_mapped"] == 5 and m["conservation_rel_max"] < 1e-10
    for c in res["cases"][1:]:
        assert c["mapping"]["conservation_rel_max"] < 1e-10
        assert c["mapping"]["equilibrium_after"]["force_rel"] < 1e-12
        assert c["mapping"]["equilibrium_after"]["moment_rel"] < 1e-12
    rows = list(csv.reader(open(os.path.join(d, "envelope.csv"), encoding="utf-8")))
    assert len(rows) == 1 + 24 * 14
    env = np.array([float(r[4]) for r in rows[1:]]).reshape(24, 14)
    assert np.allclose(env, arr["env_mag"], rtol=1e-8)
    reps = list(csv.DictReader(open(os.path.join(d, "representatives.csv"), encoding="utf-8")))
    assert [r["label"] for r in reps] == ["REP1", "REP2"]
    # 같은 ID 로 다시 분석 → 이전 산출물은 _backup 으로 이동
    rc, txt = _lib("analyze", "--root", lib["root"], "--config", LCFG, "--target", lib["ids"][0], "--id", "AE2E",
                   "--n-representative", "2")
    assert rc == 0, txt
    bk = os.path.join(d, "_backup")
    assert os.path.isdir(bk) and any("analysis.json" in fs for _, _, fs in os.walk(bk))


def test_optdeck_and_report(lib, analyzed, tmp_path):
    root, d = lib["root"], analyzed["dir"]
    rc, txt = _lib("optdeck", "--root", root, "--config", LCFG, "--analysis", "AE2E", "--reference-compliance", "solve")
    assert rc == 0, txt
    opt = os.path.join(d, "opt")
    for n in ("esl_bead.fem", "esl_loads.inc", "run_optistruct.bat", "README.txt", "optdeck.json"):
        assert os.path.isfile(os.path.join(opt, n)), n
    summ = json.load(open(os.path.join(opt, "optdeck.json"), encoding="utf-8"))
    fem = open(os.path.join(opt, "esl_bead.fem"), encoding="ascii").read()
    assert fem.count("\nSUBCASE ") == 6 and "DESOBJ(MINMAX)" in fem and "\nDTPG," in fem
    assert summ["deck_cases"]["mode"] == "all" and summ["deck_cases"]["n_subcases"] == 6
    refs = [s["ref"] for s in summ["subcases"]]
    assert all(r > 0 for r in refs)
    pos = [float(ln.split(",")[4]) for ln in fem.splitlines() if ln.startswith("DOBJREF")]
    assert np.allclose(pos, refs, rtol=1e-6)
    # FORCE = 매핑 하중, 3-2-1 반력 ≈ 0 (자기평형)
    tgt = store.load_entry(root, lib["ids"][0], raw=True)
    nid = tgt.raw["node_id"]
    arr = analyzed["arr"]
    inc = open(os.path.join(opt, "esl_loads.inc"), encoding="ascii").read().splitlines()
    res = analyzed["res"]
    sm = ShellModel(tgt.raw["x0"], tgt.raw["conn"], tgt.raw["elem_type"], tgt.raw["thickness"], tgt.raw["E"],
                    tgt.raw["nu"])
    spc = [(int(np.searchsorted(nid, s["node_id"])), s["dof"]) for s in tgt.meta["esl"]["supports"]]
    for k, s in enumerate(summ["subcases"]):
        F = np.zeros((nid.size, 3))
        for ln in inc:
            p = ln.split(",")
            if p[0] == "FORCE" and int(p[1]) == s["load_sid"]:
                F[np.searchsorted(nid, int(p[2]))] = [float(x) for x in p[5:8]]
        ref = analysis.deck_case_forces(res, arr)[k]
        assert np.abs(F - ref).max() <= 1e-8 * np.abs(ref).max()
        u, R = sm.solve(F, spc)
        assert np.abs(R).sum() / np.linalg.norm(F, axis=1).sum() < 1e-6
        assert np.sum(F * u[:, :3]) == pytest.approx(s["ref"], rel=1e-6)
    rc, txt = _lib("report", "--root", root, "--analysis", "AE2E")
    assert rc == 0, txt
    html = open(os.path.join(d, "report.html"), encoding="utf-8").read()
    assert html.startswith("<!doctype html>") and html.count("<svg") >= 6
    assert not re.search(r"https?:|//[a-z0-9]|\bsrc\s*=|@import|url\(", html, re.I)   # 외부 의존 0
    for eid in lib["ids"]:
        assert eid in html
    assert "esl_bead.fem" in html and "prefers-color-scheme:dark" in html
    _screenshots(os.path.join(d, "report.html"), tmp_path)


def _screenshots(html, tmp_path):
    """Playwright(Node, 설치된 Chromium)로 라이트·다크 스크린샷. 없으면 생략(skip 아님 — 정적 검사는 위에서 끝남)."""
    node = shutil.which("node")
    if not node:
        return
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    try:
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    env["NODE_PATH"] = npm_root
    out_dir = os.environ.get("ESL_REPORT_SHOT_DIR") or str(tmp_path)
    os.makedirs(out_dir, exist_ok=True)
    for theme in ("light", "dark"):
        p = subprocess.run([node, os.path.join(HERE, "screenshot_report.js"), html,
                            os.path.join(out_dir, f"report_{theme}"), theme],
                           capture_output=True, text=True, env=env, timeout=180)
        if p.returncode == 3:          # playwright 모듈 없음
            return
        assert p.returncode == 0, p.stderr
        info = json.loads(p.stdout.strip().splitlines()[-1])
        assert info == {"external_requests": [], "page_errors": []}
        for suf in ("_top.png", "_envelope.png"):
            assert os.path.getsize(os.path.join(out_dir, f"report_{theme}{suf}")) > 10_000
