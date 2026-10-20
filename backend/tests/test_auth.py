"""V-AUTH-1~4: 가짜 대시보드 introspection, 캐시, 권한 표, X-ESL-Request. 판정 순서 401 → 404 → 403 → 409."""

from __future__ import annotations

from esl_test_support import API, H, create_case
from sqlalchemy import text


def test_v_auth_1_introspection(client, fake_dashboard):
    r = client.get(f"{API}/me", headers=H("tok-power"))
    assert r.status_code == 200
    assert r.json() == {"user_id": "u-power", "username": "power", "display_name": "파워", "is_global_admin": False,
                        "roles": {"p-1": "power"}}
    assert fake_dashboard.calls[-1].headers["authorization"] == "Bearer tok-power"
    r = client.get(f"{API}/me", cookies={"analysis_canvas_session": "tok-general"})
    assert r.status_code == 200 and r.json()["roles"] == {"p-1": "general"}
    cases = [("tok-pending", 403, "ACCOUNT_NOT_ACTIVE"), ("tok-suspended", 403, "ACCOUNT_NOT_ACTIVE"),
             ("tok-unknown", 401, "AUTHENTICATION_REQUIRED")]
    for tok, st, code in cases:
        r = client.get(f"{API}/me", headers=H(tok))
        assert (r.status_code, r.json()["detail"]["code"]) == (st, code), tok
    r = client.get(f"{API}/me", headers=H("tok-suspended"))
    assert "AUTH_ACCOUNT_SUSPENDED" in r.json()["detail"]["message"]  # 대시보드 거부 사유 전달(#11)
    r = client.get(f"{API}/me")
    assert r.status_code == 401
    for mode, code in (("503", "DASHBOARD_AUTH_UNAVAILABLE"), ("timeout", "DASHBOARD_UNREACHABLE"),
                       ("500", "DASHBOARD_UNREACHABLE"), ("badjson", "DASHBOARD_UNREACHABLE")):
        fake_dashboard.mode = mode
        r = client.get(f"{API}/me", headers=H("tok-admin"))
        assert (r.status_code, r.json()["detail"]["code"]) == (503, code), mode
    fake_dashboard.mode = "ok"
    assert client.get(f"{API}/health").json()["status"] == "ok"


def test_v_auth_2_cache(client, fake_dashboard, clock, engine):
    for _ in range(3):
        assert client.get(f"{API}/me", headers=H("tok-power")).status_code == 200
    assert fake_dashboard.me_calls() == 1
    clock.t += 31
    client.get(f"{API}/me", headers=H("tok-power"))
    assert fake_dashboard.me_calls() == 2
    # 실패는 캐시하지 않음
    fake_dashboard.mode = "timeout"
    client.get(f"{API}/me", headers=H("tok-x"))
    fake_dashboard.mode = "ok"
    n = fake_dashboard.me_calls()
    client.get(f"{API}/me", headers=H("tok-x"))
    assert fake_dashboard.me_calls() == n + 1
    # 토큰 원문은 캐시 키·DB 에 없음
    ctx = client.app.state.ctx
    assert all("tok-" not in k for k in ctx.auth.me_cache.keys())
    with engine.connect() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))]
        for t in tables:
            dump = str(c.execute(text(f'SELECT * FROM "{t}"')).all())
            assert "tok-" not in dump, t


def test_v_auth_3_permissions(client, mini_inputs, worker_factory):
    # 비멤버·general 은 조회 가능, 실행 403
    for tok in ("tok-general", "tok-nonmember"):
        r = create_case(client, mini_inputs, token=tok)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN", tok
    r = create_case(client, mini_inputs)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    for tok in ("tok-general", "tok-nonmember", "tok-admin"):
        assert client.get(f"{API}/cases/{cid}", headers=H(tok)).status_code == 200
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}},
                    headers=H("tok-general", True))
    assert r.status_code == 403
    job = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}},
                      headers=H("tok-power", True)).json()
    # 같은 프로젝트 다른 power 사용자는 남의 작업 취소·재시도 403, 전역 관리자는 가능
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=H("tok-power2", True))
    assert r.status_code == 403
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=H("tok-admin", True))
    assert r.status_code == 200 and r.json()["state"] == "CANCELED"
    assert client.post(f"{API}/jobs/{job['id']}/retry", headers=H("tok-power2", True)).status_code == 403
    assert client.post(f"{API}/jobs/{job['id']}/retry", headers=H("tok-power", True)).status_code == 201
    # 프로젝트 없음 404 (권한보다 먼저)
    r = client.post(f"{API}/cases", json={"project_id": "p-zz", "folder_name": "zz", "title": "t",
                                          "rad_path": mini_inputs["rad"], "results_dir": mini_inputs["csv"]},
                    headers=H("tok-general", True))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_v_auth_4_csrf_and_order(client, mini_inputs):
    cid = create_case(client, mini_inputs).json()["id"]
    r = client.post(f"{API}/cases/{cid}/archive", headers=H("tok-power"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CSRF_HEADER_REQUIRED"
    r = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": mini_inputs["rad"]}, headers=H("tok-power"))
    assert r.status_code == 403
    # 401 → 404 → 403 → 409
    assert client.post(f"{API}/cases/nope/archive", headers={"X-ESL-Request": "1"}).status_code == 401
    assert client.post(f"{API}/cases/nope/archive", headers=H("tok-general", True)).status_code == 404
    assert client.post(f"{API}/cases/{cid}/archive", headers=H("tok-general", True)).status_code == 403
    client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=H("tok-power", True))
    r = client.post(f"{API}/cases/{cid}/archive", headers=H("tok-power", True))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_HAS_ACTIVE_JOB"


def test_loopback_dashboard_ignores_env_proxy(monkeypatch):
    # 회사 PC의 HTTP(S)_PROXY 가 127.0.0.1 대시보드 호출을 가로채 403 이 나던 문제(#11)
    from esl_platform.core.auth import DashboardClient, is_loopback_url

    assert is_loopback_url("http://127.0.0.1:8000") and is_loopback_url("http://localhost:8000")
    assert is_loopback_url("http://[::1]:8000") and not is_loopback_url("http://dash.corp:8000")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")

    class Cfg:
        dashboard_internal_url = "http://127.0.0.1:8000"
        timeout_s = 1

    c = DashboardClient(Cfg())
    assert c._client._trust_env is False
    c.close()
    Cfg.dashboard_internal_url = "http://dash.corp:8000"
    c = DashboardClient(Cfg())
    assert c._client._trust_env is True
    c.close()
