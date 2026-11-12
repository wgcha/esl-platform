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
    assert cfg["export"]["radioss"]["id_offset"] == "auto"
    assert cfg["extract"]["disp_precision"] == "float32"          # H3D 기본 저장 정밀도
    assert cfg["validation"]["noise_samples"] == 3 and cfg["case"]["include_path_map"] == {}
    assert cfg["extract"]["layers"] == ["mid"] and cfg["extract"]["shear_convention"] == "auto"
    assert cfg["extract"]["hot_k"] == 200 and cfg["tstar"]["metric"] == "max_strain"
    assert cfg["tstar"]["reach_rtol"] == 1e-6 and cfg["solver"]["backend"] == "auto"
    assert cfg["validation"]["full_solve"] == "auto"
    assert cfg["compare"] == {"min_rel": 0.1, "max_err_pct_max": 10.0, "p90_err_max": 20.0, "top_n": 20,
                              "hist_bins": 20, "section_band": 0.02}
    assert cfg["report"] == {"max_points": 20000, "top_forces": 20}
    assert config.redacted_settings(cfg) == cfg and config.redacted_settings(cfg) is not cfg


def test_coord_check_defaults_and_legacy_keys_ignored(base):
    """0.5.5: coord_check.max_rel(기본 0.005). 이전 키(warn_max_frac·warn_max_rel)는 경고 없이 무시, 없으면 기본값."""
    assert config.validate_settings(copy.deepcopy(base))["coord_check"] == {"max_rel": 0.005}
    b = copy.deepcopy(base)
    del b["coord_check"]
    assert config.validate_settings(b)["coord_check"] == config.COORD_CHECK_DEFAULTS == {"max_rel": 0.005}
    b = copy.deepcopy(base)
    b["coord_check"] = {"warn_max_frac": 0.01, "warn_max_rel": 0.01}           # 0.5.3~0.5.4 설정 그대로
    assert config.validate_settings(b)["coord_check"] == {"max_rel": 0.005}
    b = copy.deepcopy(base)
    b["coord_check"] = {"warn_max_frac": 0.5, "max_rel": 0.02}
    assert config.validate_settings(b)["coord_check"] == {"max_rel": 0.02}


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
    ("coord_check.max_rel", -1, "coord_check.max_rel"),
    ("coord_check.max_rel", "x", "coord_check.max_rel"),
    ("coord_check.unknown_key", 1, "coord_check.unknown_key"),
    ("extract.hot_k", 2.5, "extract.hot_k"),
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
    ("export.radioss.id_offset", "AUTO", "export.radioss.id_offset"),
    ("export.radioss.id_offset", 2147483647, "export.radioss.id_offset"),
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
    ("compare", _DEL, "compare"),
    ("compare.min_rel", 1.5, "compare.min_rel"),
    ("compare.max_err_pct_max", 0, "compare.max_err_pct_max"),
    ("compare.p90_err_max", _DEL, "compare.p90_err_max"),
    ("compare.top_n", 0, "compare.top_n"),
    ("compare.hist_bins", 1, "compare.hist_bins"),
    ("compare.section_band", 0.0, "compare.section_band"),
    ("report", _DEL, "report"),
    ("report.max_points", 10, "report.max_points"),
    ("report.top_forces", 2.5, "report.top_forces"),
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


# v0.12.1 h3d 변형률 결과 대체 설정(esl_strain_fallback.md §2): 선택 키, 없으면 기본값(cfg 에 주입 안 함)
def _base_cfg():
    with open(CFG, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_extract_strain_sources_optional_and_validated():
    cfg = config.validate_settings(_base_cfg())
    assert "strain_sources" not in cfg["extract"]
    x = config.extract_source_settings(cfg)
    assert x["strain_sources"] == ["max_strain", "plastic_strain", "strain_tensor", "max_stress"]
    assert x["result_names"]["plastic_strain"] == ["Plastic Strain", "Plastic_Strain"]
    c = _base_cfg()
    c["extract"].update(strain_sources=["strain_tensor", "max_strain"], result_names={"strain_tensor": ["Strain", "EPS"]},
                        tensor_layer_exclude=[])
    x = config.extract_source_settings(config.validate_settings(c))
    assert x["strain_sources"] == ["strain_tensor", "max_strain"] and x["result_names"]["strain_tensor"] == ["Strain", "EPS"]
    assert x["result_names"]["max_strain"] == ["Max_Strain"] and x["tensor_layer_exclude"] == []
    assert x["tensor_layer_prefer"] == ["Lower", "Upper"]
    for key, val in (("strain_sources", []), ("strain_sources", ["max_strain", "max_strain"]),
                     ("strain_sources", ["bogus"]), ("result_names", {"bogus": ["X"]}),
                     ("result_names", {"max_strain": ["a|b"]}), ("tensor_comps", {"xx": []}), ("vm_comps", "vonMises"),
                     ("tensor_layer_prefer", ["Lower|Upper"])):
        c = _base_cfg()
        c["extract"][key] = val
        with pytest.raises(EslError) as ei:
            config.validate_settings(c)
        assert ei.value.code == "CONFIG_INVALID" and f"extract.{key}" in ei.value.message, (key, val)


def test_solver_check_keys_optional():
    """solver.resid_rel_cap·equilibrium_tol_rel(D-0.14-RESID) 선택 키: 없으면 SOLVER_CHECK_DEFAULTS, 범위 밖 CONFIG_INVALID."""
    cfg = config.validate_settings(_base_cfg())
    assert config.solver_check_settings(cfg["solver"]) == config.SOLVER_CHECK_DEFAULTS
    assert "resid_rel_cap" not in cfg["solver"]                  # cfg 에 주입하지 않음
    c = _base_cfg()
    c["solver"].update(resid_rel_cap=1e-3, equilibrium_tol_rel=1e-5)
    assert config.solver_check_settings(config.validate_settings(c)["solver"]) == {
        "resid_rel_cap": 1e-3, "equilibrium_tol_rel": 1e-5}
    for key, val in (("resid_rel_cap", 0.0), ("equilibrium_tol_rel", 1.0)):
        c = _base_cfg()
        c["solver"][key] = val
        with pytest.raises(EslError) as ei:
            config.validate_settings(c)
        assert f"solver.{key}" in ei.value.message


def test_extract_dump_keys_optional():
    cfg = config.validate_settings(_base_cfg())
    assert config.dump_settings(cfg) == {"dump_keep": False, "dump_max_bytes": 40 * 1024 ** 3}
    c = _base_cfg()
    c["extract"].update(dump_keep=True, dump_max_bytes=1000)
    assert config.dump_settings(config.validate_settings(c)) == {"dump_keep": True, "dump_max_bytes": 1000}
    for key, val in (("dump_keep", "no"), ("dump_max_bytes", 0)):
        c = _base_cfg()
        c["extract"][key] = val
        with pytest.raises(EslError) as ei:
            config.validate_settings(c)
        assert f"extract.{key}" in ei.value.message


# ---------------------------------------------------------------- v0.16.0 ④ 메시 옵션 설정 거울(esl_compare_mesh_options.md §5)
# 거울 규칙: esl.doe.DEFAULTS["compare"] = 플랫폼 pydantic(BeadDoeCompareCfg) 기본값 = config/esl_platform*.example.yaml.
# 코어 DEFAULTS 에 새 키가 아직 없으면(Core 병합 전) 그 키의 코어 대조만 건너뜀(S2 방식) — pydantic·yaml 대조는 항상.
_C2_KEYS = ("remesh", "mesh_input", "refine", "freeform", "tria")   # v0.16.3 += freeform·tria
_C2_MESH_KEYS = ("mode", "ladder", "face_fail", "occ_import_labels",   # v0.16.3 += face_fail·occ_import_labels
                 "cad_relaxed", "large_faces", "large", "child_margin_s", "heartbeat_s")   # v0.17.4 C2-D-32~34
_PLATFORM_YAMLS = ("esl_platform.example.yaml", "esl_platform.prod.example.yaml")


def _platform_cfg():
    return pytest.importorskip("esl_platform.core.config")


def _bead_doe_yaml(name):
    with open(os.path.join(ROOT, "config", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["bead_doe"]


def test_compare_mesh_options_mirror():
    """V-C2-10·17: DEFAULTS = pydantic = example yaml 2개(메시 방식·사다리·재메시·메시 입력·세분화)."""
    pc = _platform_cfg()
    from esl.doe import DEFAULTS

    dump = pc.BeadDoeCfg().model_dump()["compare"]
    assert dump["mesh"]["mode"] == "auto" and dump["mesh"]["ladder"] == ["cad", "refine_local", "refine_global", "freeform",
                                                                         "defeature", "tria"]   # v0.16.3 C2-D-26·28
    assert dump["refine"]["stage_share"]["tria"] == 0.15 and dump["mesh"]["occ_import_labels"] == 0   # v0.16.3 C2-D-29·31
    assert dump["mesh"]["face_fail"]["skip"] == ["refine_local", "refine_global"]
    assert dump["mesh"]["cad_relaxed"] == {"enabled": True, "occ_fix_small": 0, "curvature_n": 12, "min_size_factor": 0.2,
                                           "defeature": False, "fidelity": True,                               # v0.17.4 C2-D-32
                                           "isolate": True, "timeout_s": 900.0, "fidelity_samples": 20000}     # v0.18.2 C2-D-45
    assert dump["freeform"]["surfaces"] == "occ_faces"                                                         # v0.18.2 C2-D-44
    assert dump["mesh"]["large"] == {"periodic_types": ["Sphere"], "fallback_sessions": 3, "cad_share": 0.15,
                                      "tria_timeout_s": 900.0} and \
        dump["mesh"]["large_faces"] == 1000 and dump["mesh"]["child_margin_s"] == 30.0   # C2-D-33·34
    assert dump["remesh"]["feature_angle_deg"] == 30.0 and dump["remesh"]["fidelity"] == {
        "warn_mm": 0.3, "fail_mm": 1.5, "samples_max": 200000, "warn_rel_cad": 2.0}     # v0.16.1 SR-D-27
    assert dump["mesh_input"] == {"enabled": True, "formats": [".rad", ".inc"], "max_mb": 500, "include": True,
                                  "max_include_depth": 8, "size_warn_ratio": 1.5,
                                  "diag": {"enabled": True, "feature_angle_deg": 30.0}}       # v0.16.1 SR-D-24
    assert dump["refine"]["global"] == {"factors": [0.8, 0.667]} and dump["refine"]["max_elems"] == 600000
    core = DEFAULTS["compare"]
    cview = _core_view_v0161(dump, core)
    for k in _C2_KEYS:
        if k in core:
            assert core[k] == cview[k], k
    for k in _C2_MESH_KEYS:
        if k in core["mesh"]:
            assert core["mesh"][k] == cview["mesh"][k], k
    for name in _PLATFORM_YAMLS:
        y = _bead_doe_yaml(name)["compare"]
        for k in _C2_KEYS:
            assert y[k] == dump[k], (name, k)
        for k in _C2_MESH_KEYS:
            assert y["mesh"][k] == dump["mesh"][k], (name, k)
        assert pc.BeadDoeCfg.model_validate(_bead_doe_yaml(name)).compare.refine.global_.factors == [0.8, 0.667]
    # 섹션이 없는 설정·옛 코어 DEFAULTS 와도 bead_doe_settings 는 새 키를 채움(백엔드 서비스가 키를 그대로 읽음)
    s = pc.bead_doe_settings(None)["compare"]
    assert all(k in s for k in _C2_KEYS) and all(k in s["mesh"] for k in _C2_MESH_KEYS)


# v0.16.1(esl_select_relax.md §4.4): defeature 단계 새 키·메시 입력 진단 — 코어 DEFAULTS 에 아직 없으면 그 키만 코어 대조 생략
_DEFEAT_KEYS_V0161 = ("kinds", "hole_max_d_mm", "slot_max_w_mm", "slot_max_l_mm", "flange_max_h_mm", "fillet_max_r_mm",
                      "narrow_w_factor", "feature_max_mm", "plane_tol_mm", "compound", "region_pad_factor", "max_features",
                      "list_max")


def _core_view_v0161(dump, core):
    import copy

    out = copy.deepcopy(dump)
    for k in _DEFEAT_KEYS_V0161:
        if k not in (core.get("defeature") or {}):
            out["defeature"].pop(k)
    if "diag" not in (core.get("mesh_input") or {}):
        out["mesh_input"].pop("diag")
    if "defeature" not in (core.get("mesh") or {}).get("ladder", ["defeature"]):
        out["mesh"]["ladder"] = [x for x in out["mesh"]["ladder"] if x != "defeature"]
    return out


def test_compare_defeature_stage_mirror():
    """V-SR-20(설정): defeature 새 키 기본값 = 계약 §4.4 = example yaml 2개(코어 DEFAULTS 에 있으면 그것과도)."""
    pc = _platform_cfg()
    from esl.doe import DEFAULTS

    want = {"enabled": True, "min_hole_area_mm2": 50.27, "hole_elems": 6, "hole_r_mm": [4.0, 30.0], "min_bead_height_mm": 2.0,
            "kinds": ["flange", "hole", "slot", "bead", "fillet", "narrow"], "hole_max_d_mm": 8.0, "slot_max_w_mm": 1.9,
            "slot_max_l_mm": 14.0, "flange_max_h_mm": 1.5, "fillet_max_r_mm": 1.5, "narrow_w_factor": 0.4,
            "feature_max_mm": 40.0, "plane_tol_mm": 0.01, "compound": True, "region_pad_factor": 1.0,
            "max_features": 2000, "list_max": 500}
    dump = pc.BeadDoeCfg().model_dump()["compare"]
    assert dump["defeature"] == want
    core = DEFAULTS["compare"]
    assert core["defeature"] == _core_view_v0161(dump, core)["defeature"]
    for name in _PLATFORM_YAMLS:
        y = _bead_doe_yaml(name)["compare"]
        assert y["defeature"] == want and y["mesh_input"]["diag"] == dump["mesh_input"]["diag"], name
        assert y["mesh"]["ladder"] == dump["mesh"]["ladder"], name
    s = pc.bead_doe_settings(None)["compare"]
    assert all(k in s["defeature"] for k in _DEFEAT_KEYS_V0161) and "diag" in s["mesh_input"]


def test_select_graph_mirror_v0170():
    """v0.17.0 BEADGRAPH §5.5 거울: esl.doe.DEFAULTS select.graph = pydantic BeadDoeSelectGraphCfg = example yaml 2개
    (통합: 코어 구현 키 morph.w_smooth_iters 3 포함)."""
    pc = _platform_cfg()
    from esl.doe import DEFAULTS

    dump = pc.BeadDoeSelectGraphCfg().model_dump()
    assert dump["morph"]["w_smooth_iters"] == 3
    assert dump == DEFAULTS["select"]["graph"]
    for name in _PLATFORM_YAMLS:
        assert _bead_doe_yaml(name)["select"]["graph"] == dump, name
    assert not pc.BeadDoeSelectGraphCfg.model_validate({"morph": {"w_smooth_iters": 0}}).morph.w_smooth_iters
    with pytest.raises(Exception):
        pc.BeadDoeSelectGraphCfg.model_validate({"morph": {"w_smooth_iters": -1}})


@pytest.mark.parametrize("over, frag", [
    ({"compare": {"mesh": {"ladder": ["cad", "defeature", "defeature"]}}}, "ladder"),       # 중복
    ({"compare": {"mesh": {"ladder": ["defeature", "cad"]}}}, "ladder"),                    # cad 맨 앞
    ({"compare": {"defeature": {"kinds": ["hole", "hole"]}}}, "kinds"),
    ({"compare": {"defeature": {"kinds": ["logo"]}}}, "kinds"),
    ({"compare": {"defeature": {"hole_max_d_mm": 0}}}, "hole_max_d_mm"),
    ({"compare": {"defeature": {"narrow_w_factor": 1.5}}}, "narrow_w_factor"),             # (0, 1]
    ({"compare": {"defeature": {"region_pad_factor": -1}}}, "region_pad_factor"),
    ({"compare": {"defeature": {"max_features": 0}}}, "max_features"),
    ({"compare": {"defeature": {"list_max": 0}}}, "list_max"),
    ({"compare": {"mesh_input": {"diag": {"feature_angle_deg": 91}}}}, "feature_angle_deg"),
])
def test_compare_defeature_stage_invalid(over, frag):
    pc = _platform_cfg()
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as ei:
        pc.BeadDoeCfg.model_validate({"enabled": True, **over})
    assert frag in str(ei.value), str(ei.value)


def test_compare_defeature_stage_valid():
    """순서 바꿈(cad 뒤 자유)·defeature 뺌(v0.16.0 순서)·종류 끔 허용."""
    pc = _platform_cfg()
    for lad in (["cad", "defeature", "refine_local", "refine_global", "remesh"], ["cad", "refine_local", "refine_global", "remesh"]):
        assert pc.BeadDoeCfg.model_validate({"compare": {"mesh": {"ladder": lad}}}).compare.mesh.ladder == lad
    d = pc.BeadDoeCfg.model_validate({"compare": {"defeature": {"kinds": ["hole"], "compound": False}}}).compare.defeature
    assert d.kinds == ["hole"] and d.compound is False


@pytest.mark.parametrize("over, frag", [
    ({"compare": {"mesh": {"mode": "fast"}}}, "mode"),
    ({"compare": {"mesh": {"ladder": ["refine_local", "cad"]}}}, "ladder"),            # cad 맨 앞
    ({"compare": {"mesh": {"ladder": ["cad", "remesh", "remesh"]}}}, "ladder"),        # 중복
    ({"compare": {"mesh": {"ladder": ["cad", "split"]}}}, "ladder"),                   # 모르는 단계
    ({"compare": {"mesh": {"ladder": []}}}, "ladder"),
    ({"compare": {"remesh": {"feature_angle_deg": 90}}}, "feature_angle_deg"),         # (0, 90)
    ({"compare": {"remesh": {"feature_angle_deg": 0}}}, "feature_angle_deg"),
    ({"compare": {"remesh": {"curve_angle_deg": 181}}}, "curve_angle_deg"),            # (0, 180]
    ({"compare": {"remesh": {"linear_deflection_mm": 0}}}, "linear_deflection_mm"),
    ({"compare": {"remesh": {"linear_deflection_mm": 0.5}}}, "linear_deflection_mm"),  # > fidelity.warn_mm
    ({"compare": {"remesh": {"fidelity": {"warn_mm": 0.3, "fail_mm": 0.2}}}}, "fail_mm"),
    ({"compare": {"remesh": {"algorithms": [3]}}}, "algorithms"),
    ({"compare": {"mesh_input": {"formats": [".bdf"]}}}, "formats"),                   # Q2: v0.16.0 은 rad·inc 만
    ({"compare": {"mesh_input": {"formats": [".rad", ".rad"]}}}, "formats"),
    ({"compare": {"mesh_input": {"max_mb": 0}}}, "max_mb"),
    ({"compare": {"mesh_input": {"size_warn_ratio": 1.0}}}, "size_warn_ratio"),
    ({"compare": {"refine": {"local": {"factors": [0.5, 0.75]}}}}, "factors"),         # 내림차순
    ({"compare": {"refine": {"global": {"factors": [1.0]}}}}, "factors"),              # (0, 1)
    ({"compare": {"refine": {"min_size_mm": 0}}}, "min_size_mm"),
    ({"compare": {"refine": {"max_elems": 400000}}}, "max_elems"),                     # ≥ bead_doe.mesh.max_elems
    ({"compare": {"refine": {"convergence": {"tol": -1}}}}, "tol"),
    ({"compare": {"refine": {"unknown": 1}}}, "unknown"),
])
def test_compare_mesh_options_invalid(over, frag):
    """V-C2-10·17: 잘못된 값 → 검증 실패(키 경로·이유에 해당 키)."""
    pc = _platform_cfg()
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as ei:
        pc.BeadDoeCfg.model_validate({"enabled": True, **over})
    assert frag in str(ei.value), str(ei.value)


def test_compare_mesh_options_valid_overrides():
    pc = _platform_cfg()
    b = pc.BeadDoeCfg.model_validate({"compare": {
        "mesh": {"mode": "cad", "ladder": ["cad", "remesh"]},
        "remesh": {"fidelity": {"warn_mm": 0.3, "fail_mm": None}, "timeout_s": 600},
        "mesh_input": {"formats": [".rad"]},
        "refine": {"enabled": False, "global": {"factors": [0.9, 0.5]}, "convergence": {"tol": 0.01}}}})
    d = b.model_dump()["compare"]
    assert d["mesh"]["ladder"] == ["cad", "remesh"] and d["remesh"]["fidelity"]["fail_mm"] is None
    assert d["refine"]["global"] == {"factors": [0.9, 0.5]} and d["mesh_input"]["formats"] == [".rad"]
