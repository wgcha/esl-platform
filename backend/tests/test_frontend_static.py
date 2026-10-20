"""운영 정적 서빙: server.frontend_root → 백엔드가 /esl/ 아래에 프런트 빌드를 직접 서빙(Caddy 없이).

대시보드 Vite 프록시가 /esl 전체를 경로 rewrite 없이 127.0.0.1:<server.port>로 넘기는 기본 구성을 시험한다
(physicsai-platform backend/tests/test_frontend_static.py 와 같은 규칙)."""

from __future__ import annotations

import copy
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from esl_test_support import API, H

INDEX = "<!doctype html><p>esl</p>"


def _build(tmp_path):
    fe = tmp_path / "fe"
    (fe / "assets").mkdir(parents=True)
    (fe / "index.html").write_text(INDEX, encoding="utf-8")
    (fe / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (fe / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.txt").write_text("SECRET", encoding="utf-8")
    return fe


def _app(settings_dict, engine, fake_dashboard, frontend_root):
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict

    d = copy.deepcopy(settings_dict)
    d["server"] = {**d["server"], "frontend_root": frontend_root}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler))
    return create_app(ctx)


def _is_not_found_json(r) -> bool:
    return (r.status_code == 404 and r.headers["content-type"].startswith("application/json")
            and r.json()["detail"]["code"] == "NOT_FOUND")


def test_static_serving_rules(settings_dict, tmp_path, engine, fake_dashboard):
    fe = _build(tmp_path)
    app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # SPA: 루트·없는 경로 → index.html(no-cache), 인증 없이
        for p in ("/esl/", "/esl/cases/abc/2", "/esl/library/x", "/esl/assets"):
            r = c.get(p)
            assert r.status_code == 200 and r.text == INDEX, p
            assert r.headers["cache-control"] == "no-cache" and r.headers["content-type"].startswith("text/html"), p
        assert c.head("/esl/cases/abc").status_code == 200
        # 존재하는 파일: 해시 자산은 1년 캐시, 그 밖은 no-cache
        r = c.get("/esl/assets/index-abc123.js")
        assert r.status_code == 200 and r.text == "console.log(1)" and "max-age=31536000" in r.headers["cache-control"]
        r = c.get("/esl/favicon.svg")
        assert r.status_code == 200 and r.text == "<svg/>" and r.headers["cache-control"] == "no-cache"
        # /esl → 308 /esl/(쿼리 유지)
        r = c.get("/esl", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/esl/"
        r = c.get("/esl?x=1", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "/esl/?x=1"
        # 경로 탈출(평문·인코딩·역슬래시·드라이브·NUL) → JSON 404, 비밀 내용 노출 없음
        for p in ("/esl/../secret.txt", "/esl/%2e%2e/secret.txt", "/esl/..%2fsecret.txt", "/esl/%2E%2E%2Fsecret.txt",
                  "/esl/assets/..%5c..%5csecret.txt", "/esl/assets/%2e%2e/%2e%2e/secret.txt",
                  "/esl/C:%5cWindows%5cwin.ini", "/esl/x%00.js"):
            r = c.get(p)
            assert _is_not_found_json(r) and "SECRET" not in r.text, (p, r.status_code, r.text)
        # API 접두는 정적 처리로 가지 않는다: 없는 경로 = JSON 404(메서드 무관), 있는 경로의 다른 메서드 = 405
        for method in ("GET", "POST", "DELETE"):
            for p in (f"{API}/nonexistent", f"{API}/cases/x/y/z", API, f"{API}/", "/esl/%61pi/nonexistent"):
                assert _is_not_found_json(c.request(method, p)), (method, p)
        assert c.get(f"{API}/health").json()["status"] == "ok"
        assert c.delete(f"{API}/health").status_code == 405
        # 인증 영향 없음: 정적은 인증 없이, API는 그대로 인증 필요
        assert c.get(f"{API}/me").status_code == 401
        assert c.get(f"{API}/me", headers=H("tok-admin")).status_code == 200
        # 운영에서는 '/'를 가로채지 않는다(대시보드 몫), openapi에 정적 라우트 없음
        assert c.get("/", follow_redirects=False).status_code == 404
        paths = c.get(f"{API}/openapi.json").json()["paths"]
        assert not [p for p in paths if not p.startswith(API)]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink 없음")
def test_static_symlink_escape_is_rejected(settings_dict, tmp_path, engine, fake_dashboard):
    fe = _build(tmp_path)
    try:
        os.symlink(tmp_path / "secret.txt", fe / "leak.txt")
        os.symlink(tmp_path / "outside", fe / "leakdir", target_is_directory=True)
        os.symlink(fe / "favicon.svg", fe / "inside.svg")
    except OSError as exc:  # Windows 권한 없음(개발자 모드 꺼짐)
        pytest.skip(f"symlink 생성 불가: {exc}")
    app = _app(settings_dict, engine, fake_dashboard, str(fe))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        for p in ("/esl/leak.txt", "/esl/leakdir/x.txt", "/esl/leakdir"):
            r = c.get(p)
            assert _is_not_found_json(r) and "SECRET" not in r.text, p
        assert c.get("/esl/inside.svg").text == "<svg/>"   # 빌드 폴더 안을 가리키는 링크는 허용


def test_static_root_missing_starts(settings_dict, tmp_path, engine, fake_dashboard):
    """빌드 폴더·index.html이 없어도 기동하고(설정 오류 아님), 화면 요청은 JSON 404, API는 정상."""
    from esl_platform.api.frontend_static import root_status

    missing = tmp_path / "nofe"
    app = _app(settings_dict, engine, fake_dashboard, str(missing))
    assert root_status(str(missing))[0] == "WARN" and "폴더가 없습니다" in root_status(str(missing))[1]
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.get("/esl/cases/1")
        assert _is_not_found_json(r) and "프런트 빌드가 없습니다" in r.json()["detail"]["message"]
        assert c.get(f"{API}/health").status_code == 200
    missing.mkdir()
    assert root_status(str(missing))[0] == "WARN" and "index.html" in root_status(str(missing))[1]
    assert root_status(str(_build(tmp_path)))[0] == "OK"
    assert root_status(None)[0] == "SKIP" and root_status("")[0] == "SKIP"


def test_static_not_configured(client):
    """기본(null): 정적 서빙 없음(Caddy 등 외부 서빙)."""
    assert _is_not_found_json(client.get("/esl/"))
    assert _is_not_found_json(client.get("/esl/cases/3"))
    assert client.get("/esl", follow_redirects=False).status_code == 404


def test_frontend_root_config_rules(settings_dict):
    from esl_platform.core.config import load_config_dict

    for v in (None, ""):
        d = copy.deepcopy(settings_dict)
        d["server"] = {**d["server"], "frontend_root": v}
        assert load_config_dict(d, environ={}).ok
    d = copy.deepcopy(settings_dict)
    d["server"] = {**d["server"], "frontend_root": "relative/frontend"}
    assert "server.frontend_root" in load_config_dict(d, environ={}).error_keys()
    d["server"]["frontend_root"] = "D:/esl-platform/.runtime/frontend"   # Windows 절대경로 형식도 허용(존재 여부는 점검 WARN만)
    assert "server.frontend_root" not in load_config_dict(d, environ={}).error_keys()


def test_safe_parts_unit():
    from esl_platform.api.frontend_static import _safe_parts

    assert _safe_parts("") == []
    assert _safe_parts("assets/a.js") == ["assets", "a.js"]
    assert _safe_parts("./a//b/") == ["a", "b"]
    for bad in ("..", "a/../b", "a\\..\\b", "/etc/passwd", "\\\\srv\\share", "C:/x", "a/C:", "x\x00", "a.txt:stream"):
        assert _safe_parts(bad) is None, bad
