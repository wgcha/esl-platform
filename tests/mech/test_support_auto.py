"""V-MR-1 (v0.10.0 esl_menu_restructure.md §5.2): auto_321 자동 선택·품질 검사, check_321 수동 검사, 기존 결과 불변."""
import copy

import numpy as np
import pytest

from esl.config import SUPPORT_CHECK_DEFAULTS, support_check_settings
from esl.errors import EslError
from esl.mech import supports
from meshes import rect_quads, rot_matrix


def _grid(xs, ys, keep=lambda x, y: True):
    return np.array([[x, y, 0.0] for x in xs for y in ys if keep(x, y)], float)


def _tilted_plate():
    X, c, t = rect_quads(600.0, 250.0, 24, 10, distort=0.2, seed=3)
    R = rot_matrix([0.4, 1.0, -0.6], 0.8)
    return X @ R.T + [100.0, 200.0, -50.0]


def test_rect_pca4_ok_same_as_pick_321():
    Xg = _tilted_plate()
    r = supports.auto_321(Xg)
    assert r["status"] == "OK" and r["mode"] == "pca4" and not r["problems"]
    assert r["checks"]["area_ratio"] == pytest.approx(1.0, abs=0.05)
    assert r["checks"]["min_dist_rel"] > SUPPORT_CHECK_DEFAULTS["min_dist_rel"]
    ref = supports.pick_321(Xg, supports.pca_corners(Xg)["idx"])
    assert r["idx"] == [i for i, _ in ref] and r["dofs"] == [d for _, d in ref]
    assert r["corners"] == supports.pca_corners(Xg)["idx"] and r["rule_version"] == 1


def test_thin_plate_too_close_blocked():
    thin = _grid(np.linspace(0, 1000, 51), np.linspace(0, 10, 3))
    r = supports.auto_321(thin)
    codes = [p["code"] for p in r["problems"]]
    assert r["status"] == "BLOCKED" and "SUPPORT_TOO_CLOSE" in codes and codes[-1] == "SUPPORT_NO_VALID_CANDIDATE"
    tc = next(p for p in r["problems"] if p["code"] == "SUPPORT_TOO_CLOSE")
    assert tc["value"] < tc["limit"] == SUPPORT_CHECK_DEFAULTS["min_dist_rel"] and "너무 가깝습니다" in tc["message"]
    assert len(r["idx"]) == 3 and r["checks"]["min_dist_rel"] == pytest.approx(tc["value"])


def test_arrow_collinear_then_pca8_expansion():
    arrow = _grid(np.linspace(0, 130, 27), np.linspace(0, 60, 13), lambda x, y: x <= 100 or abs(y - 30) <= (130 - x))
    assert supports.auto_321(arrow)["mode"] == "pca4"           # 기본 기준은 pca4 통과
    cfg = {"min_area_ratio": 0.9}
    r = supports.auto_321(arrow, cfg)
    assert r["status"] == "OK" and r["mode"] == "pca8" and r["checks"]["area_ratio"] >= 0.9
    assert len(set(r["idx"])) == 3 and [len(d) for d in r["dofs"]] == [3, 2, 1]
    b = supports.auto_321(arrow, {**cfg, "expand_candidates": False})
    assert b["status"] == "BLOCKED" and b["mode"] == "pca4"
    assert [p["code"] for p in b["problems"]] == ["SUPPORT_COLLINEAR"] and "거의 한 줄" in b["problems"][0]["message"]
    assert supports.auto_321(arrow, cfg) == r                    # 결정적


def test_ill_conditioned_threshold():
    Xg = _tilted_plate()
    cond = supports.auto_321(Xg)["checks"]["cond_ratio"]
    r = supports.auto_321(Xg, {"min_cond_ratio": min(0.99, cond * 2), "expand_candidates": False})
    assert r["status"] == "BLOCKED" and r["problems"][0]["code"] == "SUPPORT_ILL_CONDITIONED"
    assert "구속이 약합니다" in r["problems"][0]["message"]


def test_collinear_nodes_degenerate():
    line = np.array([[i, 2.0 * i, 0.0] for i in range(10)], float)
    r = supports.auto_321(line)
    assert r["status"] == "BLOCKED" and [p["code"] for p in r["problems"]] == ["SUPPORT_DEGENERATE"]
    assert r["idx"] == [] and r["plane"] is None


def test_check_321_manual():
    rect = _grid(np.linspace(0, 100, 11), np.linspace(0, 60, 7))
    ok = supports.check_321(rect, [76, 70, 6])
    assert ok["status"] == "OK" and ok["mode"] == "manual" and not ok["problems"]
    assert ok["dofs"] == [d for _, d in supports.pick_321(rect, [76, 70, 6])]
    bad = supports.check_321(rect, [0, 1, 2])            # 한 변 위 세 점(공선)
    codes = {p["code"] for p in bad["problems"]}
    assert bad["status"] == "BLOCKED" and {"SUPPORT_DEGENERATE", "SUPPORT_COLLINEAR", "SUPPORT_TOO_CLOSE"} <= codes
    near = supports.check_321(rect, [0, 1, 76])
    assert near["status"] == "BLOCKED" and {p["code"] for p in near["problems"]} == {"SUPPORT_TOO_CLOSE"}
    with pytest.raises(EslError):
        supports.check_321(rect, [0, 0, 1])


def test_settings_defaults_not_injected():
    from esl.config import validate_settings
    import yaml
    import os

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "config", "esl.example.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    before = copy.deepcopy(cfg)
    validate_settings(cfg)
    assert "auto_check" not in cfg["support"]
    assert cfg["support"] == before["support"]
    assert support_check_settings(cfg) == SUPPORT_CHECK_DEFAULTS
    cfg["support"]["auto_check"] = {"min_area_ratio": 0.2}
    validate_settings(cfg)
    assert support_check_settings(cfg)["min_area_ratio"] == 0.2
    assert support_check_settings(cfg)["min_dist_rel"] == SUPPORT_CHECK_DEFAULTS["min_dist_rel"]
    cfg["support"]["auto_check"] = {"min_area_ratio": 2.0}
    with pytest.raises(EslError):
        validate_settings(cfg)
    cfg["support"]["auto_check"] = {"expand_candidates": "yes"}
    with pytest.raises(EslError):
        validate_settings(cfg)
