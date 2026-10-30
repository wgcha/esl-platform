"""V-SR-3 `/scx/status`(계약 esl_scx_relay.md SR-D-19): 사유 순서 전 경로 + 헬스 TTL 캐시 + 대시보드 다운(포트 닫힘) 시 3 s 안 응답,
프로젝트별 루트, 권한(멤버 조회·비멤버 403)."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from esl_test_support import API, H

from esl_platform.core.config import load_config_dict
from esl_platform.core.scx import status


def _settings(settings_dict, **top):
    d = json.loads(json.dumps(settings_dict))
    for k, v in top.items():
        if v is None:
            d.pop(k, None)
        elif isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    return lc.settings


def _with_scx(settings_dict, **scx):
    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["scx"].update(scx)
    return d


class MiniRelay:
    """/health 응답만 정하는 가짜(drive_mode·relay_base·job_api·writes_active, 또는 404 HTML·503 RELAY_DISABLED)."""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.mode = "ok"
        self.health = {"relay_version": 1, "drive_mode": "scx", "writes_active": True, "job_api": True, "queue_paused": False,
                       "relay_base": "", "forbidden_prefixes": ["SPDM"], "max_download_bytes": 1 << 30}
        relay = self

        class Hd(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                if relay.mode == "nohtml":
                    body, code, ct = b"<html>not found</html>", 404, "text/html"
                elif relay.mode == "disabled":
                    body, code, ct = json.dumps({"code": "RELAY_DISABLED", "message": "off"}).encode(), 503, "application/json"
                else:
                    body, code, ct = json.dumps(relay.health).encode(), 200, "application/json"
                self.send_response(code)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def mini(fake_relay):
    m = MiniRelay(fake_relay.secret)
    yield m
    m.stop()


def test_reason_order_feature_switches(settings_dict):
    s = _settings(settings_dict, scx_drive={"enabled": False}, hpc=None)
    st = status.evaluate(s, "p-1")
    assert st["fetch"]["reason_code"] == "SCX_FETCH_DISABLED" and st["verify"]["reason_code"] == "VD_DISABLED"
    s = _settings(settings_dict, hpc=None)
    assert status.evaluate(s, "p-1")["fetch"]["reason_code"] == "SCX_NOT_CONFIGURED"
    ok = status.evaluate(_settings(settings_dict), "p-1")
    assert ok["fetch"] == {"enabled": True, "reason_code": None, "reason": None}
    assert ok["relay"]["reachable"] and ok["relay"]["job_api"] and ok["adapters"]["commit"] == "a363a89e8f93"
    # 프로젝트에 허용된 루트가 없으면 SCX_NO_ROOTS(다른 프로젝트 전용 루트만 있음)
    s = _settings(settings_dict, scx_drive={"roots": [{"key": "p2only", "label": "x", "rel": "share/p2", "projects": ["p-2"]}]})
    assert status.evaluate(s, "p-1")["fetch"]["reason_code"] == "SCX_NO_ROOTS"
    assert status.evaluate(s, "p-2")["fetch"]["enabled"] is True


def test_dashboard_down_fast(settings_dict):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()                                                    # 닫힌 포트(대시보드 다운)
    s = _settings(_with_scx(settings_dict, relay_url=f"http://127.0.0.1:{port}"))
    t0 = time.monotonic()
    st = status.evaluate(s, "p-1")
    assert time.monotonic() - t0 < 3.0
    assert st["fetch"]["reason_code"] == "SCX_RELAY_UNREACHABLE" and st["relay"]["reachable"] is False
    assert "대시보드에 연결할 수 없습니다" in st["fetch"]["reason"]


def test_relay_route_missing_disabled_mode_and_verify_order(settings_dict, mini):
    d = _with_scx(settings_dict, relay_url=mini.url)
    mini.mode = "nohtml"
    assert status.evaluate(_settings(d), "p-1")["fetch"]["reason_code"] == "SCX_RELAY_DISABLED"
    mini.mode = "disabled"
    assert status.evaluate(_settings(d), "p-1")["fetch"]["reason_code"] == "SCX_RELAY_DISABLED"
    mini.mode = "ok"
    mini.health["drive_mode"] = "local"
    assert status.evaluate(_settings(d), "p-1")["fetch"]["reason_code"] == "SCX_DRIVE_MODE_OFF"
    mini.health["drive_mode"] = "scx"
    # B 판정 순서(v0.12.0 — 다 통과하면 사용 가능, VD_NOT_AVAILABLE 해제)
    dv = {**d, "verify_drop": {"enabled": True}}
    mini.health.update(writes_active=False)
    st = status.evaluate(_settings(dv), "p-1")
    assert st["fetch"]["enabled"] and st["verify"]["reason_code"] == "SCX_WRITES_OFF"
    mini.health.update(writes_active=True, job_api=False)
    assert status.evaluate(_settings(dv), "p-1")["verify"]["reason_code"] == "SCX_JOB_API_OFF"
    mini.health.update(job_api=True)
    dva = json.loads(json.dumps(dv))
    dva["hpc"]["scx"]["appliance"] = ""
    assert status.evaluate(_settings(dva), "p-1")["verify"]["reason_code"] == "SCX_APPLIANCE_MISSING"
    mini.health["relay_base"] = "share"
    assert status.evaluate(_settings(dv), "p-1")["verify"]["reason_code"] == "SCX_BASE_OUTSIDE_RELAY"
    mini.health["relay_base"] = "esl"
    st = status.evaluate(_settings(dv), "p-1")
    assert st["verify"] == {"enabled": True, "reason_code": None, "reason": None}


def test_verify_drive_base_shared_home(settings_dict, mini):
    """v0.12.0: hpc.scx.drive_base = "~"(공유 홈 자체) + verify_drop.enabled → 설정 경고 + 검증 낙하만 비활성 VD_DRIVE_BASE_SHARED
    (PBS 제출은 계정 전용 폴더 "~/<폴더>"). 기능 A(조회)는 그대로."""
    d = _with_scx(settings_dict, relay_url=mini.url, drive_base="~")
    mini.mode = "ok"
    mini.health.update(drive_mode="scx", writes_active=True, job_api=True, relay_base="")
    dv = {**d, "verify_drop": {"enabled": True}}
    lc = load_config_dict(dv, environ={})
    assert lc.ok and [w.key for w in lc.warnings] == ["hpc.scx.drive_base"]
    assert "VD_DRIVE_BASE_SHARED" in lc.warnings[0].message
    st = status.evaluate(lc.settings, "p-1")
    assert st["fetch"]["enabled"] is True
    assert st["verify"]["reason_code"] == "VD_DRIVE_BASE_SHARED"
    assert st["verify"]["reason"] == '검증 낙하는 전용 폴더가 필요합니다: hpc.scx.drive_base 를 "~/<전용 폴더>" 로'
    # 검증 낙하가 꺼져 있으면 경고 없음, 전용 폴더면 통과
    assert load_config_dict(d, environ={}).warnings == []
    ok = load_config_dict({**_with_scx(settings_dict, relay_url=mini.url, drive_base="~/esl"), "verify_drop": {"enabled": True}},
                          environ={})
    assert ok.warnings == [] and status.evaluate(ok.settings, "p-1")["verify"]["enabled"] is True


def test_health_ttl_cache(settings_dict, fake_relay):
    s = _settings(_with_scx(settings_dict, health_ttl_s=30))
    for _ in range(3):
        assert status.evaluate(s, "p-1")["fetch"]["enabled"]
    assert len(fake_relay.calls("/health")) == 1
    status.evaluate(s, "p-1", force=True)
    assert len(fake_relay.calls("/health")) == 2
    s0 = _settings(settings_dict)                                   # ttl 0 = 매번
    status.evaluate(s0, "p-1")
    status.evaluate(s0, "p-1")
    assert len(fake_relay.calls("/health")) == 4


def test_status_api_permissions_and_roots(client):
    r = client.get(f"{API}/scx/status", params={"project_id": "p-1"}, headers=H("tok-general"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["fetch"]["enabled"] and j["roots"] == [{"key": "drop", "label": "낙하해석 공유"}]
    assert j["verify"] == {"enabled": False, "reason_code": "VD_DISABLED", "reason": j["verify"]["reason"]}
    assert set(j["relay"]) >= {"reachable", "drive_state", "queue_paused", "writes_active", "job_api", "max_download_bytes",
                               "checked_at"}
    assert "secret" not in r.text and "relay_url" not in r.text
    r = client.get(f"{API}/scx/status", params={"project_id": "p-2"}, headers=H("tok-nonmember"))
    assert [x["key"] for x in r.json()["roots"]] == ["drop", "p2only"]
    r = client.get(f"{API}/scx/status", params={"project_id": "p-1"}, headers=H("tok-nonmember"))
    assert r.status_code == 403
