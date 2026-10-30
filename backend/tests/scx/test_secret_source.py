"""v0.12.0 hpc.scx.secret_file = "" — 대시보드 비밀 파일 따라가기.

해석 순서: 명시 절대경로(상대경로 거부 L1) > (1) esl env SIMDASH_SCX_RELAY_SECRET_FILE > (2) hpc.scx.dashboard_root 의 .env →
backend/.env(python-dotenv 형식, 그 키 줄만) > (3) <런타임>/secrets/scx_relay_key. 셋 다 없으면 SCX_SECRET_INVALID + 안내.
환경 점검 hpc.scx.secret_file 에 '출처: …'(값 미출력)."""

from __future__ import annotations

import json
import os

from esl_platform.check import OK, WARN, check_scx
from esl_platform.core.config import load_config_dict
from esl_platform.core.scx import gateway, settings as S


class _C:
    def __init__(self, secret_file="", dashboard_root=""):
        self.secret_file, self.dashboard_root = secret_file, dashboard_root


def test_dotenv_line_parsing():
    k = S.DASH_SECRET_KEY
    assert S._dotenv_value(f"{k}=/a/b.key", k) == "/a/b.key"
    assert S._dotenv_value(f'export {k}="D:\\\\s\\\\k key.txt"  # 주석', k) == "D:\\\\s\\\\k key.txt"
    assert S._dotenv_value(f"{k}='/x/y' # c", k) == "/x/y"
    assert S._dotenv_value(f"{k}=/p/q #주석", k) == "/p/q"
    assert S._dotenv_value(f"# {k}=/no", k) is None
    assert S._dotenv_value("OTHER_SECRET=hunter2", k) is None
    assert S._dotenv_value(f"{k}X=/no", k) is None


def test_resolution_order_and_sources(tmp_path):
    dash = tmp_path / "simdashboard"
    (dash / "backend").mkdir(parents=True)
    rt = tmp_path / "runtime"
    (rt / "secrets").mkdir(parents=True)
    (rt / "secrets" / "scx_relay_key").write_text("k")
    # 명시 절대경로가 최우선, 상대경로는 거부
    r = S.resolve_secret_file(_C("/abs/key"), environ={S.DASH_SECRET_KEY: "/env/key"})
    assert (r["path"], r["source"]) == ("/abs/key", "config")
    r = S.resolve_secret_file(_C("rel/key"), environ={})
    assert r["path"] is None and "절대경로" in r["problem"]
    # (1) env
    r = S.resolve_secret_file(_C("", str(dash)), environ={S.DASH_SECRET_KEY: "/env/key"}, runtime=str(rt))
    assert (r["path"], r["source"]) == ("/env/key", "env")
    # (2) 대시보드 backend/.env(루트 .env 에 키가 없으면) — 다른 키 값은 결과에 없음
    (dash / ".env").write_text("SIMDASH_DB_PASSWORD=topsecret\n")
    (dash / "backend" / ".env").write_text(f'SIMDASH_X=1\n{S.DASH_SECRET_KEY}="/dash/backend.key"\n')
    r = S.resolve_secret_file(_C("", str(dash)), environ={}, runtime=str(rt))
    assert (r["path"], r["source"], r["env_file"]) == ("/dash/backend.key", "dashboard_env", str(dash / "backend" / ".env"))
    assert "topsecret" not in json.dumps(r)
    # 루트 .env 가 backend/.env 보다 먼저
    (dash / ".env").write_text(f"{S.DASH_SECRET_KEY}=/dash/root.key\n")
    assert S.resolve_secret_file(_C("", str(dash)), environ={}, runtime=str(rt))["path"] == "/dash/root.key"
    assert S.secret_source_text(S.resolve_secret_file(_C("", str(dash)), environ={})) == f"출처: 대시보드 .env({dash / '.env'})"
    # (3) 런타임 기본 — env ESL_PLATFORM_CONFIG=<런타임>/config/esl_platform.yaml 에서 런타임을 안다
    r = S.resolve_secret_file(_C(""), environ={"ESL_PLATFORM_CONFIG": str(rt / "config" / "esl_platform.yaml")})
    assert (r["path"], r["source"]) == (str(rt / "secrets" / "scx_relay_key"), "runtime")
    assert S.secret_source_text(r) == "출처: 런타임 기본"
    # 없음
    r = S.resolve_secret_file(_C("", str(tmp_path / "nodash")), environ={})
    assert r["path"] is None and r["source"] is None and "SIMDASH_SCX_RELAY_SECRET_FILE" in r["problem"]
    # env·.env 값이 상대경로면 거부
    assert S.resolve_secret_file(_C(""), environ={S.DASH_SECRET_KEY: "key.txt"})["path"] is None


def test_gateway_and_check_follow_dashboard(settings_dict, fake_relay, tmp_path, monkeypatch):
    sec = settings_dict["hpc"]["scx"]["secret_file"]
    os.chmod(sec, 0o600)
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / ".env").write_text(f"SIMDASH_SCX_RELAY_ENABLED=true\n{S.DASH_SECRET_KEY}={sec}\n")
    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["scx"].update(secret_file="", dashboard_root=str(dash))
    monkeypatch.delenv(S.DASH_SECRET_KEY, raising=False)
    monkeypatch.delenv("ESL_PLATFORM_CONFIG", raising=False)
    s = load_config_dict(d, environ={}).settings
    gateway.reset()
    gw, code, _ = gateway.get_gateway(s)
    assert code is None and gw.secret_problem() is None                 # 대시보드 .env 가 가리키는 파일로 연결
    items = {i.key: i for i in check_scx(s, "linux")}
    it = items["hpc.scx.secret_file"]
    assert it.status == OK and f"출처: 대시보드 .env({dash / '.env'})" in it.detail and fake_relay.secret not in it.detail
    assert items["scx.relay"].status == OK
    # 셋 다 없음 → SCX_SECRET_INVALID + 안내
    (dash / ".env").write_text("SIMDASH_SCX_RELAY_ENABLED=true\n")
    gateway.reset()
    s2 = load_config_dict(d, environ={}).settings
    assert gateway.get_gateway(s2)[1] == "SCX_SECRET_INVALID"
    it = {i.key: i for i in check_scx(s2, "linux")}["hpc.scx.secret_file"]
    assert it.status == WARN and "SCX_SECRET_INVALID" in it.detail and "출처: 없음" in it.detail
    # 상대 dashboard_root 는 설정 문제
    d["hpc"]["scx"]["dashboard_root"] = "dash"
    assert any("dashboard_root" in p for p in S.config_problems(load_config_dict(d, environ={}).settings))
