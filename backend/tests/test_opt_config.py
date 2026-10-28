"""비드 최적화 설정 키(계약 esl_opt_run.md §11): OptRunCfg 기본값 = esl.opt.DEFAULTS(코어 설정 거울), 섹션 없으면 꺼짐,
altair.optistruct_path·max_concurrent_os, commands.os_check·os_solve·bead_post argv 검사, solve 정규식·env 허용 키, job_types."""

from __future__ import annotations

import copy

import pytest
from esl_test_support import PLATFORM_EXAMPLE, make_settings_dict


def _issues(d):
    from esl_platform.core.config import load_config_dict

    return {i["key"] for i in load_config_dict(d, environ={}).errors()}


def test_defaults_mirror_core_and_missing_section_disabled(tmp_path):
    import esl.opt as core_opt
    from esl_platform.core.config import OptRunCfg, load_config_dict, opt_settings

    assert OptRunCfg().model_dump() == core_opt.DEFAULTS
    lc = load_config_dict(make_settings_dict(tmp_path), environ={})
    assert lc.ok
    d = make_settings_dict(tmp_path)
    d.pop("opt_run", None)
    lc = load_config_dict(d, environ={})
    assert lc.settings.opt_run is None and opt_settings(lc.settings)["enabled"] is False
    assert opt_settings(lc.settings) == core_opt.settings(None)
    d["opt_run"] = {"enabled": True, "loads": {"mac_merge": 0.9}, "keepout": {"max_rects": 5}}
    o = opt_settings(load_config_dict(d, environ={}).settings)
    assert o["enabled"] is True and o["loads"]["mac_merge"] == 0.9 and o["loads"]["max_cases"] == 20
    assert o["keepout"]["max_rects"] == 5 and o["keepout"]["hole_radius_mm"] == 15.0
    assert o == core_opt.settings({"opt_run": d["opt_run"]})


def test_examples_parse_with_opt_section():
    import yaml
    from esl_platform.core.config import load_config

    lc = load_config(str(PLATFORM_EXAMPLE), environ={})
    assert lc.ok, lc.errors()
    s = lc.settings
    assert s.opt_run.enabled is True and s.altair.max_concurrent_os == 1
    assert s.commands.os_check[0] == "{optistruct}" and s.commands.bead_post[0] == "{hw}"
    assert ".fem" in s.upload.allowed_ext
    prod = yaml.safe_load((PLATFORM_EXAMPLE.parent / "esl_platform.prod.example.yaml").read_text(encoding="utf-8"))
    assert prod["opt_run"] == yaml.safe_load(PLATFORM_EXAMPLE.read_text(encoding="utf-8"))["opt_run"]


@pytest.mark.parametrize("patch,key", [
    ({"commands": {"os_check": ["optistruct", "{fem}"]}}, "commands.os_check[0]"),
    ({"commands": {"os_solve": ["{optistruct}", "{fem}", "{h3d}"]}}, "commands.os_solve[2]"),
    ({"commands": {"os_solve": ["{optistruct}", "-nt", "{nt}"]}}, "commands.os_solve"),
    ({"commands": {"os_check": ["{optistruct}", "{fem}", "a&b"]}}, "commands.os_check[2]"),
    ({"commands": {"bead_post": ["{optistruct}", "{h3d_fwd}", "{out_dir_fwd}"]}}, "commands.bead_post[0]"),
    ({"commands": {"bead_post": ["{hw}", "{out_dir}"]}}, "commands.bead_post"),
    ({"altair": {"optistruct_path": "relative/optistruct.bat"}}, "altair.optistruct_path"),
    ({"altair": {"optistruct_path": "C:/Altair/opt&.bat"}}, "altair.optistruct_path"),
    ({"opt_run": {"solve": {"env": {"PATH": "x"}}}}, "opt_run.solve.env.PATH"),
    ({"opt_run": {"solve": {"error_patterns": ["("]}}}, "opt_run.solve.error_patterns[0]"),
    ({"opt_run": {"loads": {"default_k": 30}}}, "opt_run.loads"),
    ({"opt_run": {"loads": {"default_strategy": "D"}}}, "opt_run.loads.default_strategy"),
    ({"opt_run": {"bead_defaults": {"angle": 90}}}, "opt_run.bead_defaults.angle"),
    ({"opt_run": {"unknown": 1}}, "opt_run.unknown"),
])
def test_invalid_opt_keys(tmp_path, patch, key):
    d = make_settings_dict(tmp_path)
    for k, v in patch.items():
        base = copy.deepcopy(d.get(k) or {})
        for kk, vv in v.items():
            if isinstance(vv, dict) and isinstance(base.get(kk), dict):
                base[kk] = {**base[kk], **vv}
            else:
                base[kk] = vv
        d[k] = base
    assert any(i == key or i.startswith(key) for i in _issues(d)), (_issues(d), key)


def test_solve_env_allowed_keys(tmp_path):
    d = make_settings_dict(tmp_path)
    d["opt_run"] = {"enabled": True, "solve": {"env": {"ALTAIR_LICENSE_PATH": "6200@lic", "OMP_STACKSIZE": "64M",
                                                       "ALTAIR_HOME": "C:/Altair"}}}
    assert _issues(d) == set()


def test_job_type_def():
    from esl_platform.core.db import tables
    from esl_platform.core.job_types import JOB_TYPES, OPT_STEP_WEIGHTS, steps_for

    jt = JOB_TYPES["OPT_RUN"]
    assert (jt.stage, jt.lane) == (10, "SLOT") and "OPT_RUN" in tables.JOB_TYPES
    assert [(s.key, s.core_stage, s.kind) for s in steps_for("OPT_RUN")] == [
        ("OPT_PREP", "opt_prep", "INTERNAL"), ("OPT_LOAD", "opt_load", "INTERNAL"), ("OPT_DECK", "opt_deck", "INTERNAL"),
        ("OS_SOLVE", None, "LOCAL"), ("OPT_POST", "opt_post", "LOCAL"), ("OPT_REGISTER", None, "INTERNAL")]
    assert list(OPT_STEP_WEIGHTS) == [s.key for s in jt.steps] and sum(OPT_STEP_WEIGHTS.values()) == 100
