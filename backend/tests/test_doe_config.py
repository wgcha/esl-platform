"""비드 DOE 설정(계약 esl_bead_doe.md §14): 기본값 = 코어 esl.doe.DEFAULTS·DEFAULT_COMMANDS, 섹션 없으면 꺼짐, paicad argv
검사(argv[0] {paicad}·허용 자리·필수 자리), 예시 설정(.step·.stp 허용, bead_doe 절), 작업 유형(stage 11·step 목록 = 코어 단계)."""

from __future__ import annotations

import copy

import pytest
import yaml
from esl_test_support import REPO, make_settings_dict


def test_defaults_mirror_core():
    from esl.doe import DEFAULT_COMMANDS, DEFAULTS
    from esl_platform.core.config import PAICAD_DEFAULTS, BeadDoeCfg, CommandsCfg, bead_doe_settings

    assert BeadDoeCfg().model_dump() == DEFAULTS                       # 숫자는 한 곳(코어 기본값 거울)과 같게
    cc = CommandsCfg()
    assert {k: getattr(cc, k) for k in PAICAD_DEFAULTS} == DEFAULT_COMMANDS
    assert bead_doe_settings(None)["enabled"] is False


def test_section_absent_disabled_and_merge(tmp_path):
    from esl_platform.core.config import bead_doe_settings, load_config_dict

    d = make_settings_dict(tmp_path)
    d.pop("bead_doe", None)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    assert lc.settings.bead_doe is None and bead_doe_settings(lc.settings)["enabled"] is False
    d["bead_doe"] = {"enabled": True, "doe": {"default_n": 12}, "mesh": {"occ_sew_faces": 1}}
    s = bead_doe_settings(load_config_dict(d, environ={}).settings)
    assert s["enabled"] is True and s["doe"]["default_n"] == 12 and s["doe"]["seed"] == 1 and s["mesh"]["occ_sew_faces"] == 1


@pytest.mark.parametrize("bad, key", [
    ({"commands": {"paicad_run": ["{hw}", "shell", "run"]}}, "commands.paicad_run[0]"),
    ({"commands": {"paicad_grid": ["{paicad}", "shell", "view", "grid", "--cad", "{cad}", "--x", "{evil}"]}},
     "commands.paicad_grid[7]"),
    ({"commands": {"paicad_update": ["{paicad}", "shell", "update", "--cad", "{cad}"]}}, "commands.paicad_update"),
    ({"commands": {"paicad_extract": ["{paicad}", "shell", "extract", "--cad", "{cad}", "--out-dir", "{out_dir}&x",
                                      "--threads", "{threads}"]}}, "commands.paicad_extract[6]"),
    ({"bead_doe": {"enabled": True, "paicad": {"exe": "relative/paicad"}}}, "bead_doe.paicad.exe"),
    ({"bead_doe": {"enabled": True, "paicad": {"env": {"BAD KEY": "x"}}}}, "bead_doe.paicad.env.BAD KEY"),
])
def test_semantic_issues(tmp_path, bad, key):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    for k, v in bad.items():
        d[k] = {**copy.deepcopy(d.get(k) or {}), **v}
    lc = load_config_dict(d, environ={})
    assert key in lc.error_keys(), lc.errors()


@pytest.mark.parametrize("bad", [{"doe": {"levels_default": 5, "levels_max": 4}},
                                 {"mesh": {"size_min_mm": 30.0}}, {"doe": {"default_method": "sobol"}},
                                 {"unknown_key": 1}, {"preview": {"view_dir": "up"}}])
def test_schema_errors(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, **bad}
    lc = load_config_dict(d, environ={})
    assert not lc.ok and any(k.startswith("bead_doe") for k in lc.error_keys()), lc.errors()


def test_examples_and_upload_ext():
    from esl_platform.core.config import UPLOAD_EXT_DEFAULT, BeadDoeCfg

    assert {".step", ".stp"} <= set(UPLOAD_EXT_DEFAULT)
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert {".step", ".stp"} <= set(y["upload"]["allowed_ext"]), p
        b = BeadDoeCfg.model_validate(y["bead_doe"])
        assert b.enabled is True and b.paicad.exe is None and b.part_title == "chassis rear", p
        assert y["commands"]["paicad_run"][0] == "{paicad}", p


def test_job_types_match_core_stages():
    from esl.doe.stages import STAGES
    from esl_platform.core.db import tables
    from esl_platform.core.job_types import DOE_JOB_TYPES, DOE_STAGES, DOE_STEP_WEIGHTS, JOB_TYPES

    assert DOE_STAGES == STAGES and set(DOE_JOB_TYPES) <= set(tables.JOB_TYPES)
    for jt in DOE_JOB_TYPES:
        d = JOB_TYPES[jt]
        assert d.stage == 11 and d.lane == "SLOT"
        assert {s.core_stage for s in d.steps if s.core_stage} <= set(STAGES)
        assert [s.key for s in d.steps] == list(DOE_STEP_WEIGHTS[jt]) and sum(DOE_STEP_WEIGHTS[jt].values()) == 100
    assert [s.kind for s in JOB_TYPES["DOE_RUN"].steps] == ["INTERNAL", "LOCAL", "INTERNAL", "INTERNAL"]


def test_check_cli_bead_doe_items(tmp_path, engine):
    """환경 점검: paicad 실행 파일은 존재만, 버전·OCP 는 워커 기록만 읽는다(외부 명령 실행 없음)."""
    from doe_support import doe_settings_dict, record_paicad
    from esl_platform.check import _paicad_record, check_bead_doe
    from esl_platform.core.config import load_config_dict

    d = doe_settings_dict(tmp_path)
    s = load_config_dict(d, environ={}).settings
    items = {i.key: i for i in check_bead_doe(s, "linux")}
    assert items["bead_doe.paicad.exe"].status == "OK" and items["bead_doe.messages"].status == "OK"
    assert items["bead_doe.method_sources"].status == "OK" and items["storage.doe.write"].status == "OK"
    with engine.connect() as c:
        assert _paicad_record(c).status == "WARN"                         # 워커 기록 없음
    record_paicad(engine, ready=False, version="0.13.0", reason="PAICAD_VERSION_LOW")
    with engine.connect() as c:
        it = _paicad_record(c)
    assert it.status == "WARN" and "PAICAD_VERSION_LOW" in it.detail
    record_paicad(engine)
    with engine.connect() as c:
        assert _paicad_record(c).status == "OK"
    d.pop("bead_doe")
    assert [i.status for i in check_bead_doe(load_config_dict(d, environ={}).settings, "linux")] == ["SKIP"]
