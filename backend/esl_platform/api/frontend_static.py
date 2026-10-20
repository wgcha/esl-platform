"""프런트 빌드 정적 서빙(Caddy 없이): `{base_path}/`(기본 `/esl/`) 아래에 빌드 폴더를 서빙한다.

운영(`server.frontend_root` — 대시보드 Vite 프록시가 `/esl` 전체를 경로 그대로 넘기는 기본 구성)·시연(실행기 `--frontend`) 공용.
physicsai-platform `physicsai_api/frontend_static.py`와 같은 규칙(Caddy `try_files {path} /index.html`과 같음 + 경로 안전):
- `/esl` → 308 `/esl/`(쿼리 유지).
- `/esl/api`·`/esl/api/...`는 이 라우트에 아예 걸리지 않는다(기존 API 404·405 JSON 그대로).
- 빌드 폴더 안의 파일은 그대로, 없는 경로는 index.html(SPA fallback).
- `..`·드라이브·절대경로·NUL 등 경로 탈출과, 심볼릭 링크·junction으로 빌드 폴더 밖을 가리키는 경로는 404(JSON).
- index.html·일반 파일은 `Cache-Control: no-cache`, Vite 해시 자산(`assets/`)은 1년 immutable.
- 인증 없음(SPA가 `/esl/api/me`로 로그인 여부를 판단). API 인증은 바뀌지 않는다.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Match, Route
from starlette.types import Scope

from ..core.errors import DomainError

log = logging.getLogger("esl_platform.api")

NO_CACHE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"
HASHED_DIR = "assets"  # Vite build.assetsDir 기본값(파일 이름에 내용 해시)


def root_status(root: str | None, base_path: str = "/esl") -> tuple[str, str]:
    """(OK|WARN|SKIP, 문구) — 환경 점검·기동 로그용."""
    if not root:
        return "SKIP", "백엔드 정적 서빙 안 함(server.frontend_root 미설정 — Caddy 등 외부 서빙)"
    if not os.path.isdir(root):
        return "WARN", f"프런트 빌드 폴더가 없습니다: {root}"
    if not os.path.isfile(os.path.join(root, "index.html")):
        return "WARN", f"프런트 빌드 폴더에 index.html이 없습니다: {root}"
    return "OK", f"{'/' + base_path.strip('/')}/ 서빙: {root}"


class _StaticRoute(Route):
    """`{base}/{path}` 중 API 접두는 매치하지 않는 라우트 — API의 404·405가 정적 처리로 바뀌지 않게."""

    def __init__(self, path: str, endpoint, *, api_prefix: str, **kw) -> None:
        super().__init__(path, endpoint, **kw)
        self._api = api_prefix

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        p = scope.get("path", "")
        if p == self._api or p.startswith(self._api + "/"):
            return Match.NONE, {}
        return super().matches(scope)


def _not_found() -> DomainError:
    return DomainError("NOT_FOUND", "찾을 수 없습니다", status=404)


def _safe_parts(path: str) -> list[str] | None:
    """요청 경로(디코딩됨) → 안전한 이름 목록. 탈출 가능성이 있으면 None."""
    if "\x00" in path or path.startswith(("/", "\\")):
        return None
    parts = [x for x in path.replace("\\", "/").split("/") if x not in ("", ".")]
    for x in parts:
        if x == ".." or ":" in x:  # 상위 이동·드라이브 문자·NTFS 대체 스트림
            return None
    return parts


def mount_frontend(app: FastAPI, base_path: str, frontend_root: str, *, root_redirect: str | None = None) -> None:
    """빌드 폴더를 `{base_path}/` 아래에 서빙한다. `root_redirect`가 있으면 `/`도 그곳으로 보낸다(시연)."""
    base = "/" + base_path.strip("/")
    api_prefix = base + "/api"
    root = Path(frontend_root).resolve()
    status, message = root_status(frontend_root, base)
    if status != "OK":
        log.warning("프런트 정적 서빙: %s", message)

    if root_redirect:
        @app.get("/", include_in_schema=False)
        def _root() -> Response:
            return RedirectResponse(root_redirect, status_code=307)

    @app.get(base, include_in_schema=False)
    def _base(request: Request) -> Response:
        q = request.url.query
        return RedirectResponse(f"{base}/" + (f"?{q}" if q else ""), status_code=308)

    def _static(request: Request) -> Response:
        parts = _safe_parts(request.path_params.get("path", ""))
        if parts is None:
            raise _not_found()
        if parts:
            cand = root.joinpath(*parts)
            try:
                real = cand.resolve()
            except (OSError, RuntimeError):  # 링크 순환 등
                raise _not_found() from None
            if not real.is_relative_to(root):  # 링크·junction이 빌드 폴더 밖을 가리킴
                raise _not_found()
            if real.is_file():
                cache = IMMUTABLE if parts[0] == HASHED_DIR and len(parts) > 1 else NO_CACHE
                return FileResponse(real, headers={"Cache-Control": cache})
        index = root / "index.html"
        if not index.is_file():
            raise DomainError("NOT_FOUND", "프런트 빌드가 없습니다(관리자: server.frontend_root 확인)", status=404)
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})

    app.router.routes.append(_StaticRoute(f"{base}/{{path:path}}", _static, api_prefix=api_prefix,
                                          methods=["GET", "HEAD"], include_in_schema=False))
