"""V-SR-4 `/scx/browse`(계약 esl_scx_relay.md SR-D-5·§7·§12): 루트 밖·`..`·`/`·`~`·`\\`·첫 구간 `.`·SPDM 접두(대소문자 다른 표기)·
다른 프로젝트 루트 거부, hint·정렬·숨김·페이지, general 403, 없는 경로 404, 항목 과다 413, 릴레이 다운 503{reason_code}."""

from __future__ import annotations

import pytest
from esl_test_support import API, H
from scx_support import ROOT_REL, build_model, put

W = H("tok-power", True)
R = H("tok-power")


def _b(client, path="", root="drop", token="tok-power", project="p-1", **q):
    return client.get(f"{API}/scx/browse", params={"project_id": project, "root": root, "path": path, **q}, headers=H(token))


def _code(r):
    return r.json()["detail"]["code"]


def test_browse_lists_sorted_with_hints(client, fake_relay):
    build_model(fake_relay)
    put(fake_relay, f"{ROOT_REL}/A/model/.hidden.rad", b"x")
    put(fake_relay, f"{ROOT_REL}/A/model/state.sta", b"#RADIOSS STATE FILE\n")
    put(fake_relay, f"{ROOT_REL}/A/model/Zeta.k", b"*KEYWORD\n")
    put(fake_relay, f"{ROOT_REL}/A/model/notes.txt", b"n")
    r = _b(client, "A/model")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["root"] == "drop" and j["path"] == "A/model" and j["display"] == "/Users/vd.dashboard/share/drop/A/model"
    names = [(e["name"], e["kind"], e["hint"]) for e in j["entries"]]
    assert names == [("sub", "dir", None), ("notes.txt", "file", None), ("ref_0000.rad", "file", "rad"),
                     ("ref_0001.rad", "file", "engine"), ("state.sta", "file", "state"), ("Zeta.k", "file", "include")]
    assert j["entries"][2]["size"] == len(fake_relay.drive_file(f"{ROOT_REL}/A/model/ref_0000.rad").read_bytes())
    assert j["total"] == 6 and j["truncated"] is False
    p = _b(client, "A/model", offset=1, limit=2).json()
    assert [e["name"] for e in p["entries"]] == ["notes.txt", "ref_0000.rad"] and p["truncated"] is True and p["total"] == 6
    root = _b(client).json()
    assert root["path"] == "" and [e["name"] for e in root["entries"]] == ["A"]
    assert [e["hint"] for e in _b(client, "A/res").json()["entries"]] == ["h3d"]
    assert all(c["query"]["path"][0].startswith(ROOT_REL) for c in fake_relay.calls("/list"))


@pytest.mark.parametrize("path", ["..", "A/../..", "/etc", "~/x", "A\\model", ".git", "A//model", "A/./model", "C:/x"])
def test_browse_rejects_bad_paths(client, fake_relay, path):
    build_model(fake_relay)
    r = _b(client, path)
    assert r.status_code == 422 and _code(r) == "SCX_PATH_NOT_ALLOWED", (path, r.text)
    assert not fake_relay.calls("/list")


def test_browse_root_rules(client, fake_relay, settings_dict):
    build_model(fake_relay)
    r = _b(client, root="p2only")                                     # 다른 프로젝트 전용 루트 = 없음과 같게
    assert r.status_code == 404 and _code(r) == "SCX_ROOT_NOT_FOUND"
    assert _b(client, root="nope").status_code == 404
    r = _b(client, "A/missing")
    assert r.status_code == 404 and _code(r) == "SCX_PATH_NOT_FOUND"
    r = _b(client, token="tok-general")
    assert r.status_code == 403 and _code(r) == "FORBIDDEN"
    r = _b(client, token="tok-nonmember")
    assert r.status_code == 403


def test_browse_spdm_root_rejected_case_insensitive(client, fake_relay, settings_dict, tmp_path):
    from esl_platform.core.config import load_config_dict
    from esl_platform.core.scx import paths

    put(fake_relay, "SPDM/proj/x_0000.rad", b"x")
    fake_relay.forbidden_prefixes = ["SPDM"]
    lc = load_config_dict({**settings_dict, "scx_drive": {**settings_dict["scx_drive"], "roots": [
        {"key": "bad", "label": "SPDM", "rel": "spdm/proj"}]}}, environ={})
    # v0.12.0: 읽기 SPDM 판정은 relay 에 위임 — esl resolve 는 통과, relay 가 대소문자 무관 403 PATH_NOT_ALLOWED
    _, rel = paths.resolve(lc.settings, "p-1", "bad", "", {"forbidden_prefixes": ["SPDM"]})
    assert rel == "spdm/proj"
    from esl_platform.core.scx import gateway, status

    gw, _h = status.require_fetch(lc.settings, "p-1")
    with pytest.raises(Exception) as ei:
        gw.list("spdm/proj", 100)
    assert getattr(ei.value, "relay_code", "") == "PATH_NOT_ALLOWED"
    gateway.reset()
    with pytest.raises(Exception) as ei:                             # 릴레이 읽기 범위(relay_base) 밖
        paths.resolve(lc.settings, "p-1", "bad", "", {"forbidden_prefixes": [], "relay_base": "share"})
    assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED"


def test_browse_limit_and_relay_down(client, fake_relay, settings_dict):
    build_model(fake_relay)
    for i in range(6):
        put(fake_relay, f"{ROOT_REL}/many/f{i}.inc", b"#\n")
    from esl_platform.core.scx import gateway

    ctx = client.app.state.ctx
    s = ctx.config.settings
    object.__setattr__(s.scx_drive, "list_max_entries", 3)
    try:
        r = _b(client, "many")
        assert r.status_code == 413 and _code(r) == "SCX_LIST_LIMIT"
    finally:
        object.__setattr__(s.scx_drive, "list_max_entries", 5000)
    fake_relay.stop()
    gateway.reset()
    r = _b(client, "A")
    assert r.status_code == 503 and _code(r) == "SCX_UNAVAILABLE"
    assert r.json()["detail"]["reason_code"] == "SCX_RELAY_UNREACHABLE"
