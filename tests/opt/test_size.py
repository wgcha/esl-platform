"""V-OR-1: S2 크기 규칙 — ESL 간 ±2 %·템플릿 ±5 % 경계, 인치 null 경고, 템플릿 인치 없음/있음, 격자 혼합."""
import pytest

from esl.errors import EslError
from esl.opt import settings
from esl.opt import size as sz

CFG = settings()["size"]


def row(eid, L_xi, L_eta, inch=75, grid=(24, 14)):
    return {"entry_id": eid, "inch": inch, "L_xi": L_xi, "L_eta": L_eta, "grid": grid}


def test_entries_boundary_2pct():
    base = row("E1", 1000.0, 600.0)
    ok = sz.check_entries([base, row("E2", 1020.0, 588.0)], CFG)        # 정확히 +2 %, −2 %
    assert ok["ok"], ok
    bad = sz.check_entries([base, row("E2", 1020.5, 600.0)], CFG)
    assert not bad["ok"] and bad["errors"][0]["code"] == "SIZE_MISMATCH" and bad["errors"][0]["entry_id"] == "E2"
    bad2 = sz.check_entries([base, row("E2", 1000.0, 587.9)], CFG)
    assert not bad2["ok"]


def test_inch_rules():
    r = sz.check_entries([row("E1", 1000, 600, 75), row("E2", 1000, 600, 65)], CFG)
    assert not r["ok"] and "인치" in r["errors"][0]["message"]
    r = sz.check_entries([row("E1", 1000, 600, 75), row("E2", 1000, 600, None)], CFG)
    assert r["ok"] and any("INCH_UNKNOWN" in w for w in r["warnings"])
    r = sz.check_entries([row("E1", 1000, 600, None), row("E2", 1000, 600, 75)], CFG)
    assert r["ok"] and r["warnings"]
    loose = dict(CFG, require_inch=False)
    assert sz.check_entries([row("E1", 1000, 600, 75), row("E2", 1000, 600, 65)], loose)["ok"]


def test_template_boundary_5pct_and_inch():
    rows = [row("E1", 1000, 600), row("E2", 1010, 606), row("E3", 990, 594)]    # 중앙값 1000×600
    assert sz.check_template(rows, {"inch": None, "L_xi": 1050.0, "L_eta": 570.0}, CFG)["ok"]
    assert not sz.check_template(rows, {"inch": None, "L_xi": 1050.1, "L_eta": 600.0}, CFG)["ok"]
    assert sz.check_template(rows, {"inch": 75, "L_xi": 1000.0, "L_eta": 600.0}, CFG)["inch_ok"] is True
    t = sz.check_template(rows, {"inch": 65, "L_xi": 1000.0, "L_eta": 600.0}, CFG)
    assert not t["ok"] and "인치" in t["reasons"][0]
    t = sz.check_template([row("E1", 1000, 600, None)], {"inch": 65, "L_xi": 1000.0, "L_eta": 600.0}, CFG)
    assert t["ok"] and t["warnings"]


def test_assert_ok_raises_same_codes():
    rows = [row("E1", 1000, 600), row("E2", 1100, 600)]
    with pytest.raises(EslError) as ei:
        sz.assert_ok(rows, CFG)
    assert ei.value.code == "SIZE_MISMATCH"
    with pytest.raises(EslError) as ei:
        sz.assert_ok([row("E1", 1000, 600), row("E2", 1000, 600, grid=(12, 7))], CFG)
    assert ei.value.code == "GRID_MISMATCH"
    with pytest.raises(EslError) as ei:
        sz.assert_ok([row("E1", 1000, 600)], CFG, {"inch": None, "L_xi": 1100, "L_eta": 600})
    assert ei.value.code == "SIZE_MISMATCH"
    out = sz.assert_ok([row("E1", 1000, 600), row("E2", 1000, 600, None)], CFG, {"inch": None, "L_xi": 1000,
                                                                                   "L_eta": 600})
    assert out["warnings"]
