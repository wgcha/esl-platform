"""입력 보호(realpath 기준): 심볼릭 링크·'..' 우회, include 폴더, 출력 안 링크, 백업 이동 재확인.

Verifier 재현(verify/fs.py) 시나리오 이식 + include 폴더·include_path_map.
"""
import inspect
import json
import os
import shutil

import pytest

import synth_case
from esl import cli, pipeline
from esl.rad import parse_rad

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")

needs_symlink = pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt",
                                   reason="심볼릭 링크 생성 불가 환경")


def _snapshot(d):
    out = {}
    for base, dirs, files in os.walk(d):
        for f in files + [x for x in dirs if os.path.islink(os.path.join(base, x))]:
            p = os.path.join(base, f)
            st = os.lstat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("guard"))
    c = synth_case.build(root)
    c["root"] = root
    c["cfg"] = os.path.join(root, "esl64.yaml")
    with open(c["cfg"], "w", encoding="utf-8") as fh:
        fh.write(open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64"))
    # extract+tstar 까지 한 번 (출력 안 링크 시험용 원본)
    c["base_out"] = os.path.join(root, "base_out")
    assert cli.main(_args(c, c["base_out"], "--stage", "extract")) == 0
    assert cli.main(_args(c, c["base_out"], "--stage", "tstar")) == 0
    assert cli.main(_args(c, c["base_out"], "--stage", "esl")) == 0
    shutil.rmtree(os.path.join(c["base_out"], "_backup"))          # run.json 백업 정리(시험 기준 상태)
    c["in_snapshot"] = _snapshot(os.path.join(root, "in"))
    return c


def _args(case, out, *extra, rad=None, cfg=None):
    return ["run", "--config", cfg or case["cfg"], "--rad", rad or case["rad"], "--results", case["csv"],
            "--out", out, *extra]


def _err(capsys):
    return capsys.readouterr().err.strip()


def _inputs_unchanged(case):
    assert _snapshot(os.path.join(case["root"], "in")) == case["in_snapshot"]


# ------------------------------------------------------------------ verify/fs.py 이식
@needs_symlink
def test_symlink_out_into_results_dir(case, tmp_path, capsys):
    link = tmp_path / "link_to_csv"
    os.symlink(case["csv"], link)
    assert cli.main(_args(case, str(link / "sub"), "--stage", "extract")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert not os.path.exists(os.path.join(case["csv"], "sub"))
    _inputs_unchanged(case)


@needs_symlink
def test_symlink_out_is_rad_dir(case, tmp_path, capsys):
    link = tmp_path / "link_to_in"
    os.symlink(os.path.dirname(case["rad"]), link)
    assert cli.main(_args(case, str(link), "--stage", "extract")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert sorted(os.listdir(os.path.dirname(case["rad"]))) == ["csv", "model_0000.rad"]
    _inputs_unchanged(case)


@needs_symlink
def test_symlinked_rad_file_protects_target_dir(case, tmp_path, capsys):
    """rad 파일 자체가 링크면 링크가 가리키는 실제 폴더도 보호."""
    d = tmp_path / "deck"
    d.mkdir()
    os.symlink(case["rad"], d / "model_0000.rad")
    out = os.path.join(os.path.dirname(case["rad"]), "o")
    assert cli.main(_args(case, out, rad=str(d / "model_0000.rad"))) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert not os.path.exists(out)


def test_dotdot_path(case, capsys):
    out = case["csv"] + os.sep + ".." + os.sep + "csv" + os.sep + "x"
    assert cli.main(_args(case, out)) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert not os.path.exists(os.path.join(case["csv"], "x"))


def test_out_is_parent_of_inputs(case, capsys):
    assert cli.main(_args(case, case["root"])) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert not os.path.exists(os.path.join(case["root"], "run.json"))


def test_rerun_backup_and_inputs_unchanged(case, tmp_path):
    out = str(tmp_path / "out")
    shutil.copytree(case["base_out"], out)
    assert cli.main(_args(case, out, "--stage", "esl")) == 0
    bk = os.path.join(out, "_backup")
    stamps = os.listdir(bk)
    assert len(stamps) == 1 and sorted(os.listdir(os.path.join(bk, stamps[0]))) == ["03_bc", "04_esl", "run.json"]
    _inputs_unchanged(case)


# ------------------------------------------------------------------ 출력 안의 링크(쓰기 직전 재확인)
@needs_symlink
def test_stage_dir_symlink_outside_rejected(case, tmp_path, capsys):
    out = str(tmp_path / "out")
    shutil.copytree(case["base_out"], out)
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "keep.txt").write_text("x")
    shutil.rmtree(os.path.join(out, "03_bc"))
    os.symlink(ext, os.path.join(out, "03_bc"))
    assert cli.main(_args(case, out, "--stage", "esl")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert sorted(os.listdir(ext)) == ["keep.txt"]
    assert os.path.islink(os.path.join(out, "03_bc"))


@needs_symlink
def test_stage_dir_symlink_into_input_rejected(case, tmp_path, capsys):
    out = str(tmp_path / "out")
    shutil.copytree(case["base_out"], out)
    shutil.rmtree(os.path.join(out, "04_esl"))
    os.symlink(case["csv"], os.path.join(out, "04_esl"))
    assert cli.main(_args(case, out, "--stage", "esl")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    _inputs_unchanged(case)


@needs_symlink
def test_backup_dir_symlink_rejected(case, tmp_path, capsys):
    """백업 이동 대상(_backup)이 밖을 가리키면 이동하지 않음."""
    out = str(tmp_path / "out")
    shutil.copytree(case["base_out"], out)
    ext = tmp_path / "ext_bk"
    ext.mkdir()
    os.symlink(ext, os.path.join(out, "_backup"))
    assert cli.main(_args(case, out, "--stage", "esl")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert os.listdir(ext) == []
    assert os.path.isfile(os.path.join(out, "04_esl", "f_eq.npz"))       # 기존 산출물 그대로


@needs_symlink
def test_run_json_symlink_rejected(case, tmp_path, capsys):
    out = str(tmp_path / "out")
    shutil.copytree(case["base_out"], out)
    tgt = tmp_path / "victim.json"
    tgt.write_text(open(os.path.join(out, "run.json"), encoding="utf-8").read(), encoding="utf-8")
    before = tgt.read_bytes()
    os.remove(os.path.join(out, "run.json"))
    os.symlink(tgt, os.path.join(out, "run.json"))
    assert cli.main(_args(case, out, "--stage", "tstar")) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert tgt.read_bytes() == before
    assert not os.path.isdir(os.path.join(out, "_backup"))


def test_guard_unit(tmp_path):
    out = tmp_path / "o"
    prot = pipeline.protected_dirs(str(tmp_path / "in" / "a.rad"), str(tmp_path / "res"))
    ro = pipeline.check_overlap(str(out), prot)
    assert ro == pipeline.real_path(str(out))
    ctx = pipeline.Context(cfg={}, config_path="", rad="", results="", out=str(out), ts="t", frame=None,
                           support_nodes=None, echo=print, record={}, protected=prot, out_real=ro)
    assert ctx.guard(str(out / "x" / "y.csv"))
    for bad in (str(tmp_path / "elsewhere.csv"), str(out / ".." / "in" / "z")):
        with pytest.raises(pipeline.EslError) as ei:
            ctx.guard(bad)
        assert ei.value.code == "INPUT_INVALID"


# ------------------------------------------------------------------ include 폴더 보호
def _include_deck(case, tmp_path, spec_prefix=None):
    inc = tmp_path / "incdir"
    inc.mkdir()
    shutil.copy(case["rad"], inc / "model.inc")
    deck = tmp_path / "deck"
    deck.mkdir()
    spec = (spec_prefix + "/model.inc") if spec_prefix else str(inc / "model.inc")
    (deck / "main_0000.rad").write_text(f"#RADIOSS STARTER\n#include {spec}\n", encoding="utf-8")
    return str(deck / "main_0000.rad"), str(inc)


def test_out_inside_include_dir_rejected(case, tmp_path, capsys):
    rad, inc = _include_deck(case, tmp_path)
    assert parse_rad(rad, "chassis rear").includes          # include 를 실제로 읽음
    out = os.path.join(inc, "out")
    assert cli.main(_args(case, out, rad=rad)) == 1
    err = _err(capsys)
    assert err.startswith("INPUT_INVALID: ") and "include" in err
    assert sorted(os.listdir(inc)) == ["model.inc"]           # run.json 포함 아무것도 쓰지 않음


def test_out_inside_include_dir_rejected_on_later_stage(case, tmp_path, capsys):
    """tstar 등 후속 단계도 이전 실행이 기록한 include 폴더를 보호."""
    rad, inc = _include_deck(case, tmp_path)
    out1 = str(tmp_path / "ok")
    assert cli.main(_args(case, out1, "--stage", "extract", rad=rad)) == 0
    meta = json.load(open(os.path.join(out1, "01_extract", "model_meta.json"), encoding="utf-8"))
    assert any(p.endswith("model.inc") for p in meta["includes"])
    out2 = os.path.join(inc, "o2")
    shutil.copytree(out1, out2)
    before = _snapshot(inc)
    assert cli.main(_args(case, out2, "--stage", "tstar", rad=rad)) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert _snapshot(inc) == before


@pytest.mark.skipif("include_path_map" not in inspect.signature(parse_rad).parameters,
                    reason="esl.rad.parse_rad 에 include_path_map 인자 없음")
def test_include_path_map_from_config(case, tmp_path):
    rad, inc = _include_deck(case, tmp_path, spec_prefix="D:/proj/cae")
    cfg = tmp_path / "map.yaml"
    txt = open(case["cfg"], encoding="utf-8").read().replace(
        "include_path_map: {}", "include_path_map: {\"D:/proj/cae\": \"" + inc.replace("\\", "/") + "\"}")
    assert "D:/proj/cae" in txt
    cfg.write_text(txt, encoding="utf-8")
    out = str(tmp_path / "o")
    assert cli.main(_args(case, out, "--stage", "extract", rad=rad, cfg=str(cfg))) == 0
    meta = json.load(open(os.path.join(out, "01_extract", "model_meta.json"), encoding="utf-8"))
    assert [os.path.realpath(p) for p in meta["includes"]] == [os.path.realpath(os.path.join(inc, "model.inc"))]
    run = json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))
    assert run["config"]["snapshot"]["case"]["include_path_map"] == {"D:/proj/cae": inc.replace("\\", "/")}


# ------------------------------------------------------------------ 새 out + --stage (verify2/fs3.py I·J·L)
def _rel_include_deck(case, tmp_path, via_link=False):
    """rad 폴더 밖 형제 폴더의 include(상대 경로 ../incdir/model.inc, 또는 링크 ../inclink/model.inc)."""
    inc = tmp_path / "incdir"
    inc.mkdir()
    shutil.copy(case["rad"], inc / "model.inc")
    name = "incdir"
    if via_link:
        os.symlink(str(inc), str(tmp_path / "inclink"))
        name = "inclink"
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "main_0000.rad").write_text(f'#RADIOSS STARTER\n/INCLUDE "../{name}/model.inc"\n', encoding="utf-8")
    return str(deck / "main_0000.rad"), str(inc)


def test_new_out_is_include_dir_later_stage_no_write(case, tmp_path, capsys):
    """(I) out = include 폴더, --stage tstar, run.json·model_meta.json 없음 → 아무것도 쓰거나 옮기지 않음."""
    rad, inc = _rel_include_deck(case, tmp_path)
    # include 폴더에 있던 run.json(사용자 파일)도 _backup 으로 옮기지 않아야 함
    with open(os.path.join(inc, "run.json"), "w", encoding="utf-8") as fh:
        fh.write("{}\n")
    before = _snapshot(inc)
    assert cli.main(_args(case, inc, "--stage", "tstar", rad=rad)) == 1
    err = _err(capsys)
    assert err.startswith("INPUT_INVALID: ") and "include" in err
    assert _snapshot(inc) == before
    assert sorted(os.listdir(inc)) == ["model.inc", "run.json"]


def test_new_out_under_include_dir_export_stage_no_write(case, tmp_path, capsys):
    """(J) out = include 폴더/sub, --stage export → sub 폴더도 만들지 않음."""
    rad, inc = _rel_include_deck(case, tmp_path)
    before = _snapshot(inc)
    assert cli.main(_args(case, os.path.join(inc, "sub"), "--stage", "export", rad=rad)) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert _snapshot(inc) == before and sorted(os.listdir(inc)) == ["model.inc"]


@needs_symlink
def test_new_out_under_include_symlink_esl_stage_no_write(case, tmp_path, capsys):
    """(L) include 를 링크 폴더로 참조, out = 링크/o3, --stage esl → 실제 include 폴더에 쓰지 않음."""
    rad, inc = _rel_include_deck(case, tmp_path, via_link=True)
    before = _snapshot(inc)
    assert cli.main(_args(case, str(tmp_path / "inclink" / "o3"), "--stage", "esl", rad=rad)) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert _snapshot(inc) == before and sorted(os.listdir(inc)) == ["model.inc"]


def test_prerequisite_missing_new_out_outside_inputs(case, tmp_path, capsys):
    """단계 시작 전 실패(PREREQUISITE_MISSING): 보호 검사를 통과한 출력에만 run.json 기록, 입력 불변."""
    rad, inc = _rel_include_deck(case, tmp_path)
    before = _snapshot(inc)
    out = str(tmp_path / "fresh")
    assert cli.main(_args(case, out, "--stage", "tstar", rad=rad)) == 1
    assert _err(capsys).startswith("PREREQUISITE_MISSING: ")
    assert sorted(os.listdir(out)) == ["run.json"]
    assert json.load(open(os.path.join(out, "run.json"), encoding="utf-8"))["error"]["code"] == "PREREQUISITE_MISSING"
    assert _snapshot(inc) == before
    _inputs_unchanged(case)


def test_include_path_map_dir_protected_on_later_stage(case, tmp_path, capsys):
    """설정 include_path_map 으로만 찾는 include 폴더도 --stage tstar 새 out 에서 보호."""
    rad, inc = _include_deck(case, tmp_path, spec_prefix="D:/proj/cae")
    cfg = tmp_path / "map.yaml"
    cfg.write_text(open(case["cfg"], encoding="utf-8").read().replace(
        "include_path_map: {}", "include_path_map: {\"D:/proj/cae\": \"" + inc.replace("\\", "/") + "\"}"),
        encoding="utf-8")
    before = _snapshot(inc)
    assert cli.main(_args(case, os.path.join(inc, "o"), "--stage", "tstar", rad=rad, cfg=str(cfg))) == 1
    assert _err(capsys).startswith("INPUT_INVALID: ")
    assert _snapshot(inc) == before and sorted(os.listdir(inc)) == ["model.inc"]
