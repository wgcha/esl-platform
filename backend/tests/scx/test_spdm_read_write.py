"""v0.12.0 SPDM 보호: 기능 A 읽기(목록·고르기·내려받기)는 esl 이 SPDM 판정을 하지 않고 대시보드 relay 에 맡긴다(숨기지도 막지도
않음 — relay 403 PATH_NOT_ALLOWED → 422 SCX_PATH_NOT_ALLOWED "대시보드가 SPDM 폴더 읽기를 막고 있습니다"). 형식 검사(rel_problem·
relay_base)는 유지. 쓰기(B — drive_base 아래 잡 폴더)는 어댑터 forbidden_reason 그대로(SPDM 안·그 상위 폴더 거부)."""

from __future__ import annotations

import pytest
from esl_test_support import API, H
from scx_support import put

from esl_platform.core.config import load_config_dict
from esl_platform.core.scx import paths

SPDM = ["SharedWithMe/SPDM"]
HEALTH = {"forbidden_prefixes": SPDM, "relay_base": ""}


@pytest.fixture()
def settings_dict(settings_dict):
    d = dict(settings_dict)
    d["scx_drive"] = {**d["scx_drive"], "roots": [*d["scx_drive"]["roots"], {"key": "swm", "label": "공유", "rel": "SharedWithMe"}]}
    return d


def _b(client, path="", root="swm"):
    return client.get(f"{API}/scx/browse", params={"project_id": "p-1", "root": root, "path": path}, headers=H("tok-power"))


def test_read_has_no_esl_spdm_check_but_keeps_format_and_relay_base():
    for ok in ("SharedWithMe", "SharedWithMe/SPDM", "SharedWithMe/SPDM/x"):
        assert paths.check_drive_rel(ok, HEALTH) == ok
    with pytest.raises(Exception) as ei:                                         # 형식(첫 구간 '.')은 그대로
        paths.check_drive_rel(".hidden/x", HEALTH)
    assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED"
    with pytest.raises(Exception) as ei:                                         # relay_base 범위도 그대로
        paths.check_drive_rel("SharedWithMe/x", {"forbidden_prefixes": SPDM, "relay_base": "share"})
    assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED"


def test_write_rule_keeps_spdm_inside_and_parent_protection():
    for bad in ("SharedWithMe/esl/p-1/VD1_20261030T000000", "SharedWithMe/SPDM/p-1/VD1_20261030T000000"):
        with pytest.raises(Exception) as ei:
            paths.check_drive_rel(bad, HEALTH, write=True)
        assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED", bad
    assert paths.check_drive_rel("esl/p-1/VD1_20261030T000000", HEALTH, write=True)        # 전용 폴더는 통과


def test_settings_root_rel_parent_of_spdm_valid(settings_dict):
    lc = load_config_dict(settings_dict, environ={})
    assert lc.ok, lc.errors()


def test_browse_parent_of_spdm_lists_all_and_relay_decides(client, fake_relay):
    fake_relay.forbidden_prefixes = list(SPDM)
    put(fake_relay, "SharedWithMe/drop/a_0000.rad", b"x")
    put(fake_relay, "SharedWithMe/SPDM/proj/secret_0000.rad", b"x")
    r = _b(client)
    assert r.status_code == 200, r.text
    assert [e["name"] for e in r.json()["entries"]] == ["drop", "SPDM"]          # 숨기지 않음
    assert [e["hint"] for e in _b(client, "drop").json()["entries"]] == ["rad"]
    r = _b(client, "SPDM/proj")                                                   # esl 은 통과, relay 가 403 PATH_NOT_ALLOWED
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SCX_PATH_NOT_ALLOWED"
    assert "대시보드가 SPDM 폴더 읽기를 막고 있습니다" in r.json()["detail"]["message"]
    assert [c for c in fake_relay.calls("/list") if c["query"]["path"][0] == "SharedWithMe/SPDM/proj"]
