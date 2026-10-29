"""V-BD-2·3 (코어): paicad argv 선택 쌍 규칙, RESULT/PROGRESS 해석, 판정(§6.2), 코드 매핑 표 §6.3·모르는 코드 범주,
doe_messages.json·doe_method_sources.json 스키마, 버전 점검(낮음·OCP null·고정 불일치), 보고 JSON 읽기(변수 표·grid)."""
import json
import os

import numpy as np
import pytest

import synth_doe as sd
from esl.doe import DEFAULT_COMMANDS, load_messages, load_method_sources, message, settings, validate_messages
from esl.doe import paicad_io as pio
from esl.errors import EslError

CFG = settings()


# ---------------------------------------------------------------- argv
def test_argv_optional_pairs_and_empty_string():
    v = {"paicad": "C:/venv/Scripts/paicad.exe", "cad": "a.step", "features": "f.json", "cells": "c.json",
         "thumb": "t.json", "fixed_dir": "", "out_dir": "grid", "options": None, "threads": 4}
    a = pio.command_argv("paicad_grid", v)
    assert a[0] == "C:/venv/Scripts/paicad.exe"
    i = a.index("--fixed-dir")
    assert a[i + 1] == ""                                            # ③ 빈 문자열 유지
    assert "--options" not in a                                      # 선택 쌍 제거
    assert a[-2:] == ["--threads", "4"]
    a2 = pio.command_argv("paicad_extract", {"paicad": "p", "cad": "a.step", "out_dir": "o", "threads": 2})
    assert a2 == ["p", "shell", "extract", "--cad", "a.step", "--out-dir", "o", "--threads", "2"]
    a3 = pio.command_argv("paicad_extract", {"paicad": "p", "cad": "a.step", "out_dir": "o", "threads": 2,
                                             "assem_dir": "asm", "body_map": "bm.json", "options": "op.json"})
    assert a3[a3.index("--assem-dir") + 1] == "asm" and a3[a3.index("--body-map") + 1] == "bm.json"


def test_argv_errors():
    with pytest.raises(EslError) as ei:
        pio.command_argv("paicad_grid", {"paicad": "p", "cad": "a", "features": "f", "cells": "c", "thumb": "t",
                                         "fixed_dir": None, "out_dir": "o", "threads": 1})
    assert ei.value.code == "CONFIG_INVALID"                         # 필수 자리 null
    with pytest.raises(EslError):
        pio.build_argv(["paicad", "version"], {})                    # argv[0] 허용목록
    with pytest.raises(EslError):
        pio.build_argv(["{paicad}", "--x", "{y}"], {"paicad": "p", "y": True})
    with pytest.raises(EslError):
        pio.build_argv(["{paicad}", "a{b"], {"paicad": "p"})
    with pytest.raises(EslError):
        pio.command_argv("paicad_nope", {})
    cfg = {"commands": {"paicad_version": ["{paicad}", "version", "--json", "--x"]}}
    assert pio.command_argv("paicad_version", {"paicad": "p"}, cfg)[-1] == "--x"
    assert pio.parts_arg([12, 3, 3]) == "3,12"


def test_default_commands_match_contract():
    for k, tpl in DEFAULT_COMMANDS.items():
        assert tpl[0] == "{paicad}", k
    assert DEFAULT_COMMANDS["paicad_run"].count("{out_files_dir}") == 1


# ---------------------------------------------------------------- stdout / 판정
def test_parse_stdout():
    out = "noise\nPAICAD PROGRESS 10 loading\nPAICAD PROGRESS 140 x\nPAICAD RESULT FAIL GEOM_CAD_FAILED shell_update.json\n" \
          "PAICAD RESULT OK - shell_update.json\n"
    r = pio.parse_stdout(out)
    assert r["progress"] == [(10, "loading"), (100, "x")]
    assert r["result"] == ("OK", None, "shell_update.json")
    assert pio.parse_line("PAICAD RESULT PASS - -") == ("result", "PASS", None, None)


def test_judge(tmp_path):
    rep = tmp_path / "shell_update.json"
    rep.write_text(json.dumps({"status": "OK", "warnings": [{"code": "W1"}]}))
    ok = pio.judge("design", 0, "PAICAD RESULT OK - shell_update.json\n", str(rep))
    assert ok["ok"] and ok["warnings"] == [{"code": "W1"}]
    miss = pio.judge("prep", 0, "PAICAD RESULT OK - x\n", str(tmp_path / "none.json"))
    assert not miss["ok"] and miss["code"] == "PAICAD_FAILED"
    rep.write_text(json.dumps({"status": "FAIL", "code": "GEOM_FEATURE_COLLISION"}))
    sk = pio.judge("design", 10, "PAICAD RESULT FAIL GEOM_FEATURE_COLLISION shell_update.json\n", str(rep))
    assert not sk["ok"] and sk["status"] == "SKIPPED_COLLISION"
    assert pio.judge("prep", 2, "", None)["code"] == "PAICAD_INTERNAL"
    t = pio.judge("design", None, "", None, timeout=True)
    assert t["code"] == "PAICAD_TIMEOUT" and t["status"] == "FAILED_MORPH"
    assert pio.judge("prep", 20, "", None)["code"] == "PAICAD_FAILED"


# §6.3 표 (paicad 코드, 종료, 단계, 기대 플랫폼 코드, 기대 안 상태)
TABLE = [
    ("SHELL_BODY_NOT_SHEET", 12, "prep", "STEP_NOT_SHEET", None),
    ("GEOM_EXTRACT_EMPTY", 13, "prep", "NO_BEADS", None),
    ("GEOM_BODY_MAP_FAILED", 12, "prep", "BODY_MAP_FAILED", None),
    ("GEOM_BASELINE_MISMATCH", 12, "prep", "STEP_MESH_MISMATCH", None),
    ("SHELL_PART_NOT_FOUND", 3, "prep", "PART_NOT_FOUND", None),
    ("SHELL_UNSUPPORTED_ELEMENT", 12, "prep", "MESH_INVALID", None),
    ("SHELL_FIXED_PARSE_FAILED", 12, "prep", "FIXED_PARSE_FAILED", None),
    ("GEOM_TAG_FAILED", 12, "prep", "PAICAD_INPUT", None),
    ("GEOM_INPUT_INVALID", 3, "prep", "PAICAD_INPUT", None),
    ("GEOM_FEATURE_COLLISION", 10, "design", "SKIPPED_COLLISION", "SKIPPED_COLLISION"),
    ("SHELL_FIXED_REGION_VIOLATION", 10, "preview", "SKIPPED_FIXED", "SKIPPED_FIXED"),
    ("SHELL_FIXED_REGION_VIOLATION", 11, "design", "SKIPPED_FIXED", "SKIPPED_FIXED"),
    ("GEOM_CAD_FAILED", 10, "design", "SKIPPED_GEOM", "SKIPPED_GEOM"),
    ("GEOM_TOPOLOGY_CHANGED", 10, "design", "SKIPPED_GEOM", "SKIPPED_GEOM"),
    ("GEOM_MORPH_FAILED", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("GEOM_QUALITY", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("GEOM_DEVIATION", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("GEOM_PARAM_MISMATCH", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("GEOM_INTERFERENCE", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("GEOM_TIE_PROJECTION", 11, "design", "FAILED_MORPH", "FAILED_MORPH"),
    ("VIEW_TOO_LARGE", 14, "preview", "THUMB_UNAVAILABLE", None),
    ("VIEW_TESSELLATION_FAILED", 14, "preview", "THUMB_UNAVAILABLE", None),
    ("GEOM_OUTPUT_EXISTS", 3, "prep", "PAICAD_INTERNAL", None),
    ("GEOM_INTERNAL", 20, "design", "PAICAD_FAILED", "FAILED_MORPH"),
]


@pytest.mark.parametrize("code,ex,stage,pc,status", TABLE)
def test_code_table(code, ex, stage, pc, status):
    c = pio.classify(stage, ex, code)
    assert c["code"] == pc
    assert c["status"] == status
    assert c["message"] == message(pc) and c["message"] != pc


def test_unknown_codes_by_exit_category():
    assert pio.classify("design", 10, "GEOM_NEW_THING")["code"] == "SKIPPED_GEOM"
    c = pio.classify("design", 11, "GEOM_NEW_THING")
    assert c["code"] == "FAILED_MORPH" and "GEOM_NEW_THING" in c["message"]       # 원 코드 병기
    for ex in (3, 12, 13):
        assert pio.classify("prep", ex, "X_NEW")["code"] == "PAICAD_INPUT"
    assert pio.classify("prep", 99, "X_NEW")["code"] == "PAICAD_FAILED"
    assert pio.classify("prep", 10, "X_NEW")["code"] == "PAICAD_INPUT"             # 준비 단계에 안 상태 없음
    assert pio.classify("prep", 2, "GEOM_FEATURE_COLLISION")["code"] == "PAICAD_INTERNAL"


def test_messages_schema():
    m = load_messages()
    for k in ("STEP_NOT_SHEET", "NO_BEADS", "PAICAD_TIMEOUT", "ASSEM_TOO_LARGE", "BOUNDARY_FASTENER_FAR",
              "PAICAD_OCP_MISSING", "GMSH_UNAVAILABLE"):
        assert m["messages"][k]
    bad = json.loads(json.dumps(m))
    bad["paicad_codes"]["X"] = "NO_TEXT_CODE"
    with pytest.raises(EslError):
        validate_messages(bad)
    with pytest.raises(EslError):
        validate_messages({"version": "1", "messages": {}, "paicad_codes": {}, "exit_category": {}})
    ms = load_method_sources()
    assert ms["sources"] and ms["limits_ko"] and set(ms["methods"]) >= {"lhs", "halton", "fullfact"}


# ---------------------------------------------------------------- 버전
def test_version_check():
    v = pio.parse_version_json('{"paicad": "0.14.0", "ocp": "7.8.1", "numpy": "2"}')
    r = pio.check_version(v, CFG)
    assert r["ready"] and r["warning"] is None and r["reason"] is None
    r = pio.check_version({"paicad": "0.13.9", "ocp": "7.8"}, CFG)
    assert not r["ready"] and r["reason"] == "PAICAD_VERSION_LOW"
    r = pio.check_version({"paicad": "0.14.0", "ocp": None}, CFG)
    assert not r["ready"] and r["reason"] == "PAICAD_OCP_MISSING"
    r = pio.check_version({"paicad": "0.15.2", "ocp": "7.8"}, CFG)
    assert r["ready"] and "PAICAD_VERSION_PINNED" in r["warning"]
    assert pio.check_version(None, CFG)["reason"] == "PAICAD_CHECK_FAILED"
    with pytest.raises(EslError) as ei:
        pio.parse_version_json("paicad 0.14.0")
    assert ei.value.code == "PAICAD_CHECK_FAILED"


# ---------------------------------------------------------------- 보고 JSON
def test_params_table_groups_and_split(tmp_path):
    mesh = sd.plate()
    doc = sd.features_doc(mesh, 2, mirror=True, fixed_overlap_last=True)
    sd.write_extract(str(tmp_path), doc)
    d = pio.read_features(str(tmp_path))
    rows = pio.params_table(d)
    names = [r["name"] for r in rows]
    assert "CHASSIS_REAR_BEAD_D_1" in names and "CHASSIS_REAR_BEAD_D_2" not in names       # MIRROR 대표 1개
    r = next(x for x in rows if x["name"] == "CHASSIS_REAR_BEAD_D_1")
    assert r["group_members"] == ["CHASSIS_REAR_BEAD_D_1", "CHASSIS_REAR_BEAD_D_2"]
    assert r["type"] == "D" and r["feasible"] == [2.0, 6.5] and r["feasible_source"] == "estimate"
    u2 = next(x for x in rows if x["name"] == "CHASSIS_REAR_BEAD_U_2")
    assert u2["use_default"] is False                                                    # 고정 겹침 비드
    split = pio.params_table(d, {"symmetry_split": ["G1"]})
    assert "CHASSIS_REAR_BEAD_D_2" in [x["name"] for x in split]
    fr = {"origin": [0, 0, 0], "e_xi": [1, 0, 0], "e_eta": [0, 0, 1]}
    beads = pio.beads_table(d, fr)
    assert beads[0]["center_ab"] == [100.0, 100.0] and beads[0]["png"].endswith(".png")
    assert pio.extract_warnings(d)[0]["code"] == "BEAD_NEAR_FIXED"
    assert pio.body_map_doc(d, 7) == {"schema_version": 1, "map": {"SHEET": "PART:7"}}
    with pytest.raises(EslError) as ei:
        pio.body_map_doc({"parts": [{"body": "A"}, {"body": "B"}]}, 7)
    assert ei.value.code == "STEP_BODY_COUNT"
    bad = dict(doc, kind="solid")
    sd.write_extract(str(tmp_path / "b"), bad)
    with pytest.raises(EslError):
        pio.read_features(str(tmp_path / "b"))


def test_read_json_limit(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"a": "x" * 3000}))
    with pytest.raises(EslError) as ei:
        pio.read_json_limited(str(p), 0.001)
    assert ei.value.code == "PAICAD_FAILED"


def test_grid_states(tmp_path):
    sd.write_grid(str(tmp_path), {"d001": ("OK", None), "d002": ("FAIL", "GEOM_FEATURE_COLLISION"),
                                  "d003": ("FAIL", "SHELL_FIXED_REGION_VIOLATION"), "d004": ("FAIL", "GEOM_CAD_FAILED"),
                                  "d005": ("ERROR", "VIEW_TOO_LARGE"), "d006": ("ERROR", "GEOM_INTERNAL")})
    g = pio.read_grid(str(tmp_path), ["d001", "d002", "d003", "d004", "d005", "d006", "d007"])
    st = {c["id"]: c["state"] for c in g["cells"]}
    assert st == {"d001": "READY", "d002": "SKIPPED_COLLISION", "d003": "SKIPPED_FIXED", "d004": "SKIPPED_GEOM",
                  "d005": "READY", "d006": "SKIPPED_GEOM", "d007": "SKIPPED_GEOM"}
    assert g["counts"] == {"ok": 2, "collision": 1, "fixed": 1, "geom": 3, "thumb_warn": 1}
    assert g["missing"] == ["d007"]


def test_fixed_points(tmp_path):
    mesh = sd.plate()
    sd.write_fixed(str(tmp_path), mesh, [[0, 1, 9], [50]], kinds=("RBE2", "INTER_TYPE2_SECONDARY"))
    fx = pio.read_fixed(str(tmp_path))
    pts = pio.fixed_points(fx)
    assert [p["kind"] for p in pts] == ["RBE2", "INTER_TYPE2"]
    assert np.allclose(pts[0]["xyz"], mesh["x0"][[0, 1, 9]].mean(axis=0))
    assert pio.kind_labels(1 << 2 | 1 << 5) == ["RBE2", "BCS"]
    os.remove(tmp_path / "fixed_nodes.npz")
    with pytest.raises(EslError):
        pio.read_fixed(str(tmp_path))
