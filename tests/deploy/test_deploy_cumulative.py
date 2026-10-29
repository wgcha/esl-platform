"""v0.8.0 setup_config: OptiStruct 경로 자동 감지(V-CI-D1~D5)·upload.allowed_ext .sta·.str 1회 보충(V-CI-U1) —
계약 esl_cumulative_input.md §12·§9.1."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import setup_config as sc
import yaml
from conftest import ROOT
from test_deploy_setup_config import _inputs, _run


def _altair(tmp_path: Path, layout: str = "2026") -> tuple[str, str]:
    """가짜 Altair 설치 → (hw.exe, optistruct.bat)."""
    if layout == "2026":
        base = tmp_path / "Altair" / "2026.1"
        hw = base / "hwdesktop" / "hw" / "bin" / "win64" / "hw.exe"
    else:
        base = tmp_path / "Altair2019"
        hw = base / "hw" / "bin" / "win64" / "hw.exe"
    os_bat = base / "hwsolvers" / "scripts" / "optistruct.bat"
    for p in (hw, os_bat):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("@echo off\n")
    return str(hw).replace("\\", "/"), str(os_bat).replace("\\", "/")


def _old_config(tmp_path: Path, hw: str, drop_opt_run=True, drop_os=True, extra_edit=None) -> tuple[dict, Path]:
    """새 설치로 설정을 만든 뒤 v0.7.x 이전 모양으로(opt_run 섹션·optistruct_path 없음, hw_exe_path = hw)."""
    inp = _inputs(tmp_path)
    r1 = _run("write", inp)
    cfg = Path(r1["config_path"])
    out, skip = [], False
    for ln in cfg.read_text(encoding="utf-8").splitlines():
        if drop_opt_run and ln.startswith("opt_run:"):
            skip = True
            continue
        if skip and (ln.startswith((" ", "#")) or not ln.strip()):
            continue
        skip = False
        if drop_os and ln.strip().startswith("optistruct_path:"):
            continue
        if ln.strip().startswith("hw_exe_path:"):
            ln = re.sub(r"hw_exe_path:\s*\S.*?(\s+#.*)?$", lambda m: f"hw_exe_path: \"{hw}\"" + (m.group(1) or ""), ln)
        out.append(ln)
    text = "\n".join(out) + "\n"
    if extra_edit:
        text = extra_edit(text)
    cfg.write_text(text, encoding="utf-8")
    return inp, cfg


# ------------------------------------------------------------------ V-CI-D1
@pytest.mark.parametrize("layout", ["2026", "legacy"])
def test_d1_autodetect_adds_path_and_enabled(tmp_path, layout):
    hw, bat = _altair(tmp_path, layout)
    inp, cfg = _old_config(tmp_path, hw)
    before = cfg.read_text(encoding="utf-8")
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["altair"]["optistruct_path"] == bat and d["opt_run"] == {"enabled": True}
    assert r["opt_autodetect"]["added"] == {"altair.optistruct_path": bat, "opt_run.enabled": True}
    assert r["write"]["validation"]["ok"] is True                     # opt_run 나머지 키 = 로더 기본값
    assert not [w for w in r["warnings"] if "opt_run" in w]
    line = r["write"]["opt_autodetect"]["line"]
    assert line.startswith("비드 최적화 자동 설정: altair.optistruct_path = ") and "opt_run.enabled = true 추가" in line
    bk = r["write"]["opt_autodetect"]["backup"]
    assert bk and Path(bk).read_text(encoding="utf-8") == before and "_backup" in bk     # 수정 전 사본
    assert sc.OPT_AUTODETECT_NOTE in cfg.read_text(encoding="utf-8")
    # 다시 실행해도 바뀌지 않음
    r2 = _run("write", inp)
    assert r2["opt_autodetect"]["added"] == {} and r2["write"]["opt_autodetect"]["line"] is None


def test_d1_no_candidate_or_missing_hw(tmp_path):
    hw, bat = _altair(tmp_path)
    Path(bat).unlink()
    inp, cfg = _old_config(tmp_path, hw)
    r = _run("write", inp)
    assert r["opt_autodetect"]["added"] == {}
    assert [w for w in r["warnings"] if "opt_run" in w] == [sc.OPT_RUN_HINT + sc.OPT_AUTODETECT_NONE]
    assert "opt_run" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))
    # hw 파일 자체가 없으면 기존 안내 그대로
    (tmp_path / "b").mkdir()
    inp2, cfg2 = _old_config(tmp_path / "b", str(tmp_path / "nope" / "hw.exe"))
    r2 = _run("write", inp2)
    assert [w for w in r2["warnings"] if "opt_run" in w] == [sc.OPT_RUN_HINT]


def test_d1_search_depth_limited_to_six_levels(tmp_path):
    base = tmp_path / "A"
    hw = base / "1" / "2" / "3" / "4" / "5" / "6" / "hw.exe"
    hw.parent.mkdir(parents=True)
    hw.write_text("x")
    bat = base / "hwsolvers" / "scripts" / "optistruct.bat"
    bat.parent.mkdir(parents=True)
    bat.write_text("x")
    assert sc.find_optistruct(str(hw)) is None                                # base 는 7단계 위
    assert sc.find_optistruct(str(hw), levels=7) == str(bat).replace("\\", "/")


# ------------------------------------------------------------------ V-CI-D2
@pytest.mark.parametrize("cur,keep", [('"C:/Other/optistruct.bat"', True), ("null", False), ('""', False)])
def test_d2_existing_optistruct_path_kept_or_filled(tmp_path, cur, keep):
    hw, bat = _altair(tmp_path)

    def put(text):
        return re.sub(r"(?m)^(altair:.*\n)", lambda m: m.group(1) + f"  optistruct_path: {cur}\n", text, count=1)
    inp, cfg = _old_config(tmp_path, hw, extra_edit=put)
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    if keep:                                                    # 파일이 없어도 기존 값 불변(→ 기존 503 사유)
        assert d["altair"]["optistruct_path"] == "C:/Other/optistruct.bat" and "opt_run" not in d
        assert r["opt_autodetect"]["added"] == {}
    else:
        assert d["altair"]["optistruct_path"] == bat and d["opt_run"]["enabled"] is True


# ------------------------------------------------------------------ V-CI-D3
def test_d3_opt_run_enabled_rules(tmp_path):
    hw, bat = _altair(tmp_path)
    # 섹션은 있는데 enabled 키 없음 → 그 키만
    inp, cfg = _old_config(tmp_path, hw, drop_opt_run=False, extra_edit=_drop_enabled)
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["opt_run"]["enabled"] is True and r["opt_autodetect"]["added"]["opt_run.enabled"] is True
    assert r["write"]["validation"]["ok"] is True
    # 명시 enabled: false → 불변 + 안내 1줄(경로는 채움)
    (tmp_path / "f").mkdir()
    inp2, cfg2 = _old_config(tmp_path / "f", hw, drop_opt_run=False, extra_edit=_set_false)
    r2 = _run("write", inp2)
    d2 = yaml.safe_load(cfg2.read_text(encoding="utf-8"))
    assert d2["opt_run"]["enabled"] is False and d2["altair"]["optistruct_path"] == bat
    assert "opt_run.enabled" not in r2["opt_autodetect"]["added"]
    assert [w for w in r2["warnings"] if "opt_run" in w] == [w for w in r2["warnings"] if "false 로 꺼져" in w]
    assert len([w for w in r2["warnings"] if "opt_run" in w]) == 1


def _opt_run_block(text):
    m = re.search(r"(?ms)^opt_run:.*?(?=^\S|\Z)", text)
    return m


def _drop_enabled(text):
    m = _opt_run_block(text)
    blk = re.sub(r"(?m)^  enabled:.*\n", "", m.group(0))
    return text[:m.start()] + blk + text[m.end():]


def _set_false(text):
    m = _opt_run_block(text)
    blk = re.sub(r"(?m)^  enabled:[^#\n]*", "  enabled: false ", m.group(0), count=1)
    return text[:m.start()] + blk + text[m.end():]


# ------------------------------------------------------------------ V-CI-D4
def test_d4_preserves_other_keys_comments_bom_crlf(tmp_path):
    hw, bat = _altair(tmp_path)
    inp, cfg = _old_config(tmp_path, hw)
    raw = cfg.read_text(encoding="utf-8").replace("\n", "\r\n")
    cfg.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
    before = yaml.safe_load(raw)
    _run("write", inp)
    after_raw = cfg.read_bytes()
    assert b"\r\n" in after_raw and b"\n" not in after_raw.replace(b"\r\n", b"")
    after = yaml.safe_load(after_raw.decode("utf-8-sig"))
    exp = dict(before)
    exp["altair"] = {**before["altair"], "optistruct_path": bat}
    exp["opt_run"] = {"enabled": True}
    assert after == exp
    comments_before = [ln for ln in raw.split("\r\n") if ln.lstrip().startswith("#")]
    comments_after = [ln for ln in after_raw.decode("utf-8-sig").split("\r\n") if ln.lstrip().startswith("#")]
    assert all(c in comments_after for c in comments_before)


def test_d4_flow_style_not_written(tmp_path):
    hw, bat = _altair(tmp_path)
    inp, cfg = _old_config(tmp_path, hw, extra_edit=lambda t: t + "opt_run: {max_cases: 20}\n")
    before = cfg.read_text(encoding="utf-8")
    r = _run("write", inp)
    assert cfg.read_text(encoding="utf-8") == before
    assert any("자동으로 보충하지 못했습니다" in w for w in r["warnings"])
    assert r["write"]["opt_autodetect"]["line"] is None


# ------------------------------------------------------------------ V-CI-D5
def test_d5_console_line_in_install_common():
    src = (ROOT / "deploy" / "install-common.ps1").read_bytes()
    t = src.decode("utf-8-sig")
    assert "$Result.write.opt_autodetect.line" in t and "$Result.write.ext_supplement.line" in t
    assert "Write-EslStep $Result.write.opt_autodetect.line" in t


# ------------------------------------------------------------------ V-CI-U1 업로드 확장자 1회 보충
def test_u1_allowed_ext_supplement_once(tmp_path):
    def explicit(text):
        return re.sub(r"(?m)^  allowed_ext:.*$", "  allowed_ext: [.rad, .inc, .csv, .h3d]   # 사용자 목록", text)
    inp, cfg = _old_config(tmp_path, str(tmp_path / "nohw.exe"), extra_edit=explicit)
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    doe = sc.code_supports("bead_doe", str(ROOT))                # v0.9.0 코드(bead_doe 스키마)면 .step·.stp 도 1회 보충
    tail = [".step", ".stp"] if doe else []
    assert d["upload"]["allowed_ext"] == [".rad", ".inc", ".csv", ".h3d", ".sta", ".str", *tail]
    assert "# 사용자 목록" in cfg.read_text(encoding="utf-8")
    rec = json.loads((Path(inp["runtime_dir"]) / "state" / "ext_supplement.json").read_text(encoding="utf-8"))
    assert rec["0.8.0"] == [".sta", ".str"]
    assert rec.get("0.9.0") == ([".step", ".stp"] if doe else None)
    assert r["write"]["ext_supplement"]["line"].startswith("업로드 허용 확장자 보충:")
    # 사용자가 뺀 뒤 재실행 → 다시 넣지 않음
    text = cfg.read_text(encoding="utf-8")
    cfg.write_text(re.sub(r', "\.sta", "\.str"', "", text, count=1), encoding="utf-8")
    assert ".sta" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))["upload"]["allowed_ext"]
    r2 = _run("write", inp)
    assert ".sta" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))["upload"]["allowed_ext"]
    assert r2["ext_supplement"]["added"] == []


def test_u1_no_explicit_list_or_already_present(tmp_path):
    inp, cfg = _old_config(tmp_path, str(tmp_path / "nohw.exe"),
                           extra_edit=lambda t: re.sub(r"(?m)^  allowed_ext:.*\n", "", t))
    r = _run("write", inp)
    assert r["ext_supplement"]["added"] == [] and "allowed_ext" not in (yaml.safe_load(cfg.read_text()) .get("upload") or {})
