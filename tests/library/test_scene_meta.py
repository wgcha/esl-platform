"""P2 §2 씬 메타 파싱 + ISTA 6 해석 + 라이브러리 설정."""
import os

import pytest
import yaml

from esl.errors import EslError
from esl.library import scene_meta, settings

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "library.example.yaml")
EXAMPLE = "F:/Hyper_work/VD_25y/75QN80H/75QN80H_v072_260511/CUMULATIVE/17_Corner_Drop_2nd_Scene10_Corner146_2nd_comp.h3d"


@pytest.fixture(scope="module")
def rules():
    return settings.scene_rules(settings.load(CFG))


def test_contract_example(rules):
    r = scene_meta.parse(EXAMPLE, rules)
    exp = {"project": "VD_25y", "model": "75QN80H", "inch": 75, "version": "v072", "date": "260511",
           "scenario": "CUMULATIVE", "seq": 17, "drop_type": "Corner", "round": "2nd", "scene": 10, "orient": "146",
           "suffix": "2nd", "variant": "comp"}
    for k, v in exp.items():
        assert r[k] == v, k
    assert r["date_iso"] == "2026-05-11"
    assert r["faces"] == [1, 4, 6] and r["drop_class"] == "Corner"
    assert r["face_names"] == ["top", "left", "far_end"]
    assert r["warnings"] == []
    assert abs(sum(x * x for x in r["impact_dir_local"]) - 1.0) < 1e-12


def test_windows_backslash_and_folder_name(rules):
    p = r"D:\Hyper_work\VD_25y\55QX10A\55QX10A_v003_260101\FREE\03_Edge_Drop_1st_Scene2_Edge34\result.h3d"
    r = scene_meta.parse(p, rules)
    assert (r["model"], r["inch"], r["scenario"], r["seq"], r["drop_type"], r["orient"], r["scene"]) == \
        ("55QX10A", 55, "FREE", 3, "Edge", "34", 2)
    assert r["faces"] == [3, 4] and r["drop_class"] == "Edge"
    assert r["suffix"] is None and r["variant"] is None and r["warnings"] == []


def test_partial_failure_keeps_other_fields(rules):
    r = scene_meta.parse("F:/w/VD_25y/75QN80H/75QN80H_v072_260511/CUMULATIVE/random_name.h3d", rules)
    assert r["model"] == "75QN80H" and r["inch"] == 75 and r["scenario"] == "CUMULATIVE"
    assert r["seq"] is None and r["drop_type"] is None and r["orient"] is None
    w = " ".join(r["warnings"])
    for k in ("seq", "drop_type", "scene", "orient"):
        assert f"{k}:" in w
    assert "round:" not in w and "variant:" not in w          # 선택 필드는 경고 없음
    r2 = scene_meta.parse("17_Face_Drop_Scene1_Face3.h3d", rules)
    assert r2["drop_type"] == "Face" and r2["faces"] == [3] and r2["model"] is None
    assert any("model:" in x for x in r2["warnings"])


@pytest.mark.parametrize("orient,dt,msg", [("13", "Edge", "마주보는"), ("147", "Corner", "1~6"),
                                           ("11", "Edge", "1~6"), ("146", "Edge", "불일치")])
def test_orient_validation(rules, orient, dt, msg):
    r = scene_meta.parse(f"01_{dt}_Drop_1st_Scene1_{dt}{orient}.h3d", rules)
    assert any(msg in w for w in r["warnings"]), r["warnings"]
    if msg != "불일치":
        assert r["faces"] is None


def test_custom_regex(rules):
    rr = dict(rules, scene_regex=[r"(?P<model>[A-Z0-9]+)-(?P<drop_type>Corner|Edge|Face)-(?P<orient>\d+)-S(?P<scene>\d+)"])
    r = scene_meta.parse("x/65ABC-Corner-235-S7.h3d", rr)
    assert (r["model"], r["inch"], r["drop_type"], r["orient"], r["scene"], r["faces"]) == \
        ("65ABC", 65, "Corner", "235", 7, [2, 3, 5])


def test_ista6_heights_placeholder_and_lookup():
    ist = settings.load(CFG)["_ista6"]
    assert sorted(ist["faces"]) == [1, 2, 3, 4, 5, 6]
    assert scene_meta.drop_height(25.0, "Corner", ist) is None          # 표 미입력(TODO)
    filled = dict(ist, heights={"bins": [{"weight_min": 0, "weight_max": 30, "Corner": 610}]})
    assert scene_meta.drop_height(25.0, "Corner", filled) == 610
    assert scene_meta.drop_height(35.0, "Corner", filled) is None


def test_settings_reject_unknown_and_missing(tmp_path):
    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
    cfg["analysis"]["typo"] = 1
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(EslError) as e:
        settings.load(str(p))
    assert e.value.code == "CONFIG_INVALID" and "analysis.typo" in e.value.message
    cfg["analysis"].pop("typo")
    cfg["optdeck"]["bead"]["skip"] = "LOAD"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(EslError):
        settings.load(str(p))
