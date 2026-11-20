"""V-CFG: 예시 설정 로드·검증, 필수 키 누락·알 수 없는 키·루트 겹침·dev_static·코어 설정 오류 → CONFIG_INVALID."""

from __future__ import annotations

import copy

import pytest
from esl_test_support import API, H, PLATFORM_EXAMPLE, make_settings_dict

from esl_platform.core.config import load_config, load_config_dict, redacted_settings


def test_example_config_loads():
    lc = load_config(str(PLATFORM_EXAMPLE), environ={})
    assert lc.ok, lc.errors()
    assert lc.settings.api_prefix == "/esl/api"
    assert lc.core["case"]["part_title"] == "chassis rear"
    red = redacted_settings(lc.settings)        # P3-UX §6: 서버 h3d 추출 설정(기본값)
    assert red["altair"]["max_concurrent_hw"] == 2 and red["altair"]["hw_exe_path"].endswith("/hw.exe")
    assert red["commands"]["h3d_extract"][0] == "{hw}" and red["worker"]["slots"] == 2
    assert red["client_token"]["ttl_days"] == 30


def test_profile_env_override():
    lc = load_config(str(PLATFORM_EXAMPLE), environ={"ESL_PROFILE": "prod"})
    assert lc.settings.profile == "prod"
    assert lc.ok  # example 은 dashboard 모드 → prod 허용


def test_missing_config_path():
    lc = load_config(None, environ={})
    assert not lc.ok and lc.error_keys() == ["(file)"]


def _bad(tmp_path, mutate):
    d = make_settings_dict(tmp_path)
    mutate(d)
    return load_config_dict(d, environ={})


@pytest.mark.parametrize("mut,key", [
    (lambda d: d["server"].pop("port"), "server.port"),
    (lambda d: d.__setitem__("altair", {"unknown": 1}), "altair.unknown"),
    (lambda d: d.__setitem__("altair", {"hw_exe_path": "relative/hw.exe"}), "altair.hw_exe_path"),
    (lambda d: d.__setitem__("altair", {"hw_exe_path": "C:/a&b/hw.exe"}), "altair.hw_exe_path"),
    (lambda d: d.__setitem__("altair", {"max_concurrent_hw": 0}), "altair.max_concurrent_hw"),
    (lambda d: d.__setitem__("commands", {"h3d_extract": ["cmd.exe", "{h3d}", "{out_dir}"]}), "commands.h3d_extract[0]"),
    (lambda d: d.__setitem__("commands", {"h3d_extract": ["{hw}", "{h3d}", "{out_dir}", "{evil}"]}),
     "commands.h3d_extract[3]"),
    (lambda d: d.__setitem__("commands", {"h3d_extract": ["{hw}", "{h3d}", "{out_dir}", "a&b"]}),
     "commands.h3d_extract[3]"),
    (lambda d: d.__setitem__("commands", {"h3d_extract": ["{hw}", "{h3d}"]}), "commands.h3d_extract"),
    (lambda d: d["worker"].__setitem__("slots", 17), "worker.slots"),
    (lambda d: d.__setitem__("client_token", {"ttl_days": 0}), "client_token.ttl_days"),
    (lambda d: d["worker"].__setitem__("timeout_s", 5), "worker.timeout_s"),
    (lambda d: d["storage"].__setitem__("input_roots", [d["storage"]["esl_root"] + "/sub"]), "storage.input_roots[0]"),
    (lambda d: d["storage"].__setitem__("esl_root", "relative/path"), "storage.esl_root"),
    (lambda d: d["storage"].__setitem__("esl_root", "/tmp/a b"), "storage.esl_root"),
    (lambda d: d["worker"].__setitem__("lease_ttl_s", 0.1), "worker.lease_ttl_s"),
    (lambda d: d.__setitem__("core", {}), "core"),
    (lambda d: d["core"]["settings"].__setitem__("unknown_key", 1), "core"),
    (lambda d: d["logging"].__setitem__("mask_patterns", ["("]), "logging.mask_patterns[0]"),
])
def test_invalid(tmp_path, mut, key):
    lc = _bad(tmp_path, mut)
    assert not lc.ok
    assert any(k == key or k.startswith(key) for k in lc.error_keys()), lc.errors()


def test_dev_static_requires_dev(tmp_path):
    lc = _bad(tmp_path, lambda d: (d["auth"].__setitem__("mode", "dev_static"), d.__setitem__("profile", "prod")))
    assert "auth.mode" in lc.error_keys()


def test_dev_static_startup_refused(tmp_path, engine):
    from esl_platform.api.context import build_context
    from esl_platform.api.main import StartupRefused, create_app

    d = make_settings_dict(tmp_path)
    d["auth"]["mode"] = "dev_static"
    lc = load_config_dict(d, environ={})
    assert lc.ok
    create_app(build_context(lc, engine), bind_host="127.0.0.1")
    with pytest.raises(StartupRefused):
        create_app(build_context(lc, engine), bind_host="0.0.0.0")


def test_write_api_503_when_config_invalid(tmp_path, engine, fake_dashboard):
    import httpx
    from fastapi.testclient import TestClient

    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app

    d = make_settings_dict(tmp_path)
    d["core"]["settings"] = copy.deepcopy(d["core"]["settings"])
    d["core"]["settings"]["oops"] = 1
    lc = load_config_dict(d, environ={})
    assert lc.settings is not None and not lc.ok
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler)))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": "c1", "title": "t", "rad_path": "/x",
                                         "results_dir": "/y"}, headers=H("tok-power", True))
        assert r.status_code == 503 and r.json()["detail"]["code"] == "CONFIG_INVALID"
        st = c.get(f"{API}/status", headers=H("tok-power")).json()
        assert st["config"]["ok"] is False and st["config"]["errors"]
        # 형식: {key, message}[] (프런트 ConfigIssue)
        assert all(set(e) == {"key", "message"} and all(isinstance(v, str) for v in e.values())
                   for e in st["config"]["errors"])


# ---------------------------------------------------------------- v0.24.2 경계력 보충 설정 거울(V-0242-BFD-12)
def test_bf_on_demand_keys_mirror(tmp_path):
    import yaml
    from esl_platform.core.config import AltairCfg

    assert AltairCfg().bf_on_demand_timeout_s == 1800 and AltairCfg().bf_on_demand_wait_s == 600
    root = PLATFORM_EXAMPLE.parent
    for name in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        alt = yaml.safe_load((root / name).read_text(encoding="utf-8"))["altair"]
        assert alt["bf_on_demand_timeout_s"] == 1800 and alt["bf_on_demand_wait_s"] == 600, name
    lc = load_config(str(PLATFORM_EXAMPLE), environ={})
    assert lc.settings.altair.bf_on_demand_timeout_s == 1800 and lc.settings.altair.bf_on_demand_wait_s == 600
    assert redacted_settings(lc.settings)["altair"]["bf_on_demand_wait_s"] == 600
    for key, val in (("bf_on_demand_timeout_s", 59), ("bf_on_demand_wait_s", -1)):
        lc = _bad(tmp_path, lambda d, k=key, v=val: d.__setitem__("altair", {k: v}))
        assert not lc.ok and any(e == f"altair.{key}" or e.startswith(f"altair.{key}") for e in lc.error_keys()), lc.errors()
    assert _bad(tmp_path, lambda d: d.__setitem__("altair", {"bf_on_demand_wait_s": 0})).ok
