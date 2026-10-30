"""V-SR-2 연결 계층(계약 esl_scx_relay.md SR-D-1·3·18, §12): 헤더 X-SCX-Relay-Client: esl, relay_url loopback·경로 거부,
비밀 형식 오류 → 비활성 사유, 비밀 값이 caplog·오류 본문·repr·/scx/status·설정 사본에 없음, 프록시 환경변수 무시, 마스킹."""

from __future__ import annotations

import json
import logging

import pytest
from esl_test_support import API, H

from esl_platform.core.config import load_config_dict, redacted_settings
from esl_platform.core.scx import gateway, mask, messages, status


def _settings(settings_dict, **scx):
    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["scx"].update(scx)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    return lc.settings


def test_client_header_is_esl_and_health(fake_relay, loaded_config, settings_dict):
    gw, code, _ = gateway.get_gateway(loaded_config.settings)
    assert code is None and gw.client_name == "esl"
    h = gw.health()
    assert h["drive_mode"] == "scx"
    seen = fake_relay.headers_seen[-1]
    assert seen["x-scx-relay-client"] == "esl" and seen["x-scx-relay-key"] == fake_relay.secret
    # 같은 설정 = 같은 인스턴스(프로세스당 1개)
    assert gateway.get_gateway(loaded_config.settings)[0] is gw
    # client_name 설정값 그대로(physicsai 기본 'physicsai' 아님)
    gw2, _, _ = gateway.get_gateway(_settings(settings_dict, client_name="esl-2"))
    gw2.health()
    assert fake_relay.headers_seen[-1]["x-scx-relay-client"] == "esl-2"


@pytest.mark.parametrize("url", ["http://10.0.0.5:8000", "http://127.0.0.1:8000/internal", "https://127.0.0.1:8000",
                                 "http://127.0.0.1", "http://u:p@127.0.0.1:8000"])
def test_relay_url_must_be_loopback_port_only(settings_dict, url):
    s = _settings(settings_dict, relay_url=url)
    gw, code, detail = gateway.get_gateway(s)
    assert gw is None and code == "SCX_CONFIG_INVALID" and "relay_url" in detail
    st = status.evaluate(s, "p-1")
    assert st["fetch"] == {"enabled": False, "reason_code": "SCX_CONFIG_INVALID", "reason": messages.text("SCX_CONFIG_INVALID")}


def test_bad_client_name_and_roots_are_config_errors_not_startup_errors(settings_dict):
    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["scx"]["client_name"] = "ESL!"
    d["scx_drive"]["roots"].append({"key": "drop", "label": "중복", "rel": ".hidden/x"})
    lc = load_config_dict(d, environ={})
    assert lc.ok                                                   # 기동은 함(설정 오류 목록 없음)
    _, code, detail = gateway.get_gateway(lc.settings)
    assert code == "SCX_CONFIG_INVALID" and "client_name" in detail and "중복" in detail and "roots[2].rel" in detail


def test_secret_problems_disable_with_reason(settings_dict, tmp_path, fake_relay):
    bad = tmp_path / "bad_key"
    bad.write_text("short\n", encoding="utf-8")
    s = _settings(settings_dict, secret_file=str(bad))
    st = status.evaluate(s, "p-1")
    assert st["fetch"]["reason_code"] == "SCX_SECRET_INVALID" and "short" not in json.dumps(status.public(st), ensure_ascii=False)
    s = _settings(settings_dict, secret_file=str(tmp_path / "none"))
    assert status.evaluate(s, "p-1")["fetch"]["reason_code"] == "SCX_SECRET_INVALID"
    # 다른 비밀(대시보드와 다름) → RELAY_UNAUTHORIZED
    other = tmp_path / "other_key"
    other.write_text("Z" * 43 + "\n", encoding="utf-8")
    s = _settings(settings_dict, secret_file=str(other))
    assert status.evaluate(s, "p-1")["fetch"]["reason_code"] == "SCX_RELAY_UNAUTHORIZED"


def test_secret_never_leaks(client, fake_relay, loaded_config, caplog, monkeypatch):
    secret = fake_relay.secret
    caplog.set_level(logging.DEBUG)
    gw, _, _ = gateway.get_gateway(loaded_config.settings)
    assert secret not in repr(gw) and secret not in repr(gw.client())
    r = client.get(f"{API}/scx/status", params={"project_id": "p-1"}, headers=H("tok-general"))
    assert r.status_code == 200 and secret not in r.text
    assert secret not in json.dumps(redacted_settings(loaded_config.settings), default=str)
    # 오류 본문: 릴레이가 비밀 값을 메시지에 넣어도 문구에서 가려짐(어댑터 on_secret → mask)
    from simdash_adapters.hpc import HpcGatewayError

    f = messages.classify(HpcGatewayError("SUBMIT_FAILED", f"relay X: key={secret} Bearer abc.def.ghi", relay_code="X"))
    assert secret not in f.message and "Bearer ***" in f.message
    logging.getLogger("esl.test").warning("value %s", secret)        # 로그 처리기 필터
    for rec in caplog.records:
        assert secret not in rec.getMessage()
    assert secret not in caplog.text


def test_proxy_env_ignored(loaded_config, monkeypatch):
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")                  # 닫힌 포트 — 쓰면 실패
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    gw, _, _ = gateway.get_gateway(loaded_config.settings)
    assert gw.health()["relay_version"] == 1


def test_adapter_missing_disables_only_scx(loaded_config, monkeypatch):
    monkeypatch.setattr(gateway, "_ADAPTER", {"ok": False, "version": None, "commit": None,
                                              "reason": "SCX_ADAPTER_MISSING: 시험"})
    st = status.evaluate(loaded_config.settings, "p-1")
    assert st["fetch"]["reason_code"] == "SCX_ADAPTER_MISSING" and st["verify"]["reason_code"] == "VD_DISABLED"


def test_mask_text_rules():
    mask.register_secret("S" * 43)
    t = mask.mask_text("k=" + "S" * 43 + " X-SCX-Relay-Key: abc Bearer x.y.z eyJa.eyJb.c C:\\Users\\vd\\secret\\f.rad /opt/esl/x/y.txt")
    assert "S" * 43 not in t and "X-SCX-Relay-Key: ***" in t and "Bearer ***" in t and "eyJ" not in t
    assert "C:\\Users" not in t and "‹…›/f.rad" in t and "/opt/esl" not in t
    assert len(mask.mask_text("x" * 500)) == 200


def test_adapter_lock_constants_match_lock():
    from esl_test_support import REPO

    lk = json.loads((REPO / "deploy" / "simdash_adapters.lock").read_text(encoding="utf-8"))
    assert lk["commit"] == gateway.ADAPTER_COMMIT and lk["version"] == gateway.ADAPTER_VERSION
    import simdash_adapters

    assert simdash_adapters.__version__ == lk["version"]


@pytest.mark.parametrize("path", ["secrets/scx_relay_key", "./k", "~/k", "..\\k"])
def test_secret_file_must_be_absolute(settings_dict, path):
    """v0.12.0 L1(SR-D-18): hpc.scx.secret_file 상대경로 → 설정 오류(기동은 함, SCX 기능만 비활성)."""
    s = _settings(settings_dict, secret_file=path)
    _, code, detail = gateway.get_gateway(s)
    assert code == "SCX_CONFIG_INVALID" and "secret_file" in detail and "절대경로" in detail
    assert status.evaluate(s, "p-1")["fetch"]["reason_code"] == "SCX_CONFIG_INVALID"
