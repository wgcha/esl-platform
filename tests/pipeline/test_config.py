"""설정 로드·검증: 예시 통과, 필수 키 누락·잘못된 값 → CONFIG_INVALID(키 경로 포함)."""
import copy
import os

import pytest
import yaml

from esl import config
from esl.errors import EslError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")


@pytest.fixture
def base():
    with open(CFG, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_example_loads():
    cfg = config.load_config(CFG)
    assert cfg["export"]["radioss"]["id_offset"] == 9000000
    assert cfg["extract"]["disp_precision"] == "float32"          # H3D 기본 저장 정밀도
    assert cfg["validation"]["noise_samples"] == 3 and cfg["case"]["include_path_map"] == {}
    assert cfg["extract"]["layers"] == ["mid"] and cfg["extract"]["shear_convention"] == "auto"
    assert cfg["extract"]["hot_k"] == 200 and cfg["tstar"]["metric"] == "max_strain"
    assert cfg["tstar"]["reach_rtol"] == 1e-6 and cfg["solver"]["backend"] == "auto"
    assert cfg["validation"]["full_solve"] == "auto"
    assert config.redacted_settings(cfg) == cfg and config.redacted_settings(cfg) is not cfg


def test_env_path(monkeypatch):
    monkeypatch.setenv("ESL_CONFIG", CFG)
    assert config.load_config()["schema_version"] == 1
    monkeypatch.delenv("ESL_CONFIG")
    with pytest.raises(EslError) as ei:
        config.load_config()
    assert ei.value.code == "CONFIG_INVALID"


def _set(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[k]
    if value is _DEL:
        del d[keys[-1]]
    else:
        d[keys[-1]] = value


_DEL = object()


@pytest.mark.parametrize("path,value,key", [
    ("case.part_title", _DEL, "case.part_title"),
    ("validation", _DEL, "validation"),
    ("export.radioss.id_offset", _DEL, "export.radioss.id_offset"),
    ("validation.disp_rms_rel_max", -0.1, "validation.disp_rms_rel_max"),
    ("validation.hotspot_eval_count", 0, "validation.hotspot_eval_count"),
    ("validation.hotspot_eval_count", 2.5, "validation.hotspot_eval_count"),
    ("extract.layers", ["middle"], "extract.layers"),
    ("extract.layers", [], "extract.layers"),
    ("extract.layers", ["mid", "mid"], "extract.layers"),
    ("extract.layers", "mid", "extract.layers"),
    ("extract.shear_convention", "gamma", "extract.shear_convention"),
    ("extract.hot_k", 0, "extract.hot_k"),
    ("extract.hot_k", 201, "extract.hot_k"),
    ("tstar.metric", "vm", "tstar.metric"),
    ("tstar.metric", _DEL, "tstar.metric"),
    ("tstar.reach_rtol", 1.0, "tstar.reach_rtol"),
    ("tstar.reach_rtol", -1e-6, "tstar.reach_rtol"),
    ("solver.backend", "mumps", "solver.backend"),
    ("validation.full_solve", "maybe", "validation.full_solve"),
    ("validation.full_solve", _DEL, "validation.full_solve"),
    ("extract.frame_stride", True, "extract.frame_stride"),
    ("tstar.time_window", [0.5, 0.1], "tstar.time_window"),
    ("tstar.time_window", [None], "tstar.time_window"),
    ("tstar.exclude_elem_ids", ["a"], "tstar.exclude_elem_ids"),
    ("export.radioss.func_mode", "step", "export.radioss.func_mode"),
    ("export.radioss.id_offset", "9000000", "export.radioss.id_offset"),
    ("export.num_format", "{:d}", "export.num_format"),
    ("export.num_format", "{:.30E}", "export.num_format"),
    ("export.csv.delimiter", ".", "export.csv.delimiter"),
    ("case.part_title_match", "fuzzy", "case.part_title_match"),
    ("case.material_override", {1: {"E": -1, "nu": 0.3}}, "case.material_override.1.E"),
    ("solver.drill_factor", 0.0, "solver.drill_factor"),
    ("support.candidates", "node_ids", "support.node_ids"),
    ("schema_version", 2, "schema_version"),
    ("extra_section", {}, "extra_section"),
    ("tstar.unknown", 1, "tstar.unknown"),
    ("extract.disp_precision", "float16", "extract.disp_precision"),
    ("extract.disp_precision", _DEL, "extract.disp_precision"),
    ("validation.noise_samples", 0, "validation.noise_samples"),
    ("validation.noise_strain_rel_max", 0.0, "validation.noise_strain_rel_max"),
    ("validation.noise_force_rel_warn", "0.1", "validation.noise_force_rel_warn"),
    ("case.include_path_map", [], "case.include_path_map"),
    ("case.include_path_map", {"D:/x": ""}, "case.include_path_map.D:/x"),
    ("case.include_path_map", {"D:/x": 3}, "case.include_path_map.D:/x"),
])
def test_invalid(base, path, value, key):
    cfg = copy.deepcopy(base)
    _set(cfg, path, value)
    with pytest.raises(EslError) as ei:
        config.validate_settings(cfg)
    assert ei.value.code == "CONFIG_INVALID"
    assert ei.value.message.startswith(key + ":"), ei.value.message


def test_bad_yaml_and_missing_file(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("case: [unclosed", encoding="utf-8")
    for path in (p, tmp_path / "nope.yaml"):
        with pytest.raises(EslError) as ei:
            config.load_config(path)
        assert ei.value.code == "CONFIG_INVALID"
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(EslError) as ei:
        config.load_config(p)
    assert ei.value.code == "CONFIG_INVALID"
