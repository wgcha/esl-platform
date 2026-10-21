"""FastAPI 앱(계약 esl.md §5). 모든 라우트는 `{server.base_path}/api` 접두(기본 `/esl/api`).

실행: `uvicorn esl_platform.api.main:app --host 127.0.0.1 --port 8110 --no-proxy-headers`(XFF 해석은 앱이 trusted_proxies 로만) (env ESL_PLATFORM_CONFIG, ESL_DATABASE_URL).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..core.config import LoadedConfig, load_config
from ..core.errors import DomainError
from .context import AppContext, build_context
from .routers import cases, client_tokens, history, jobs, library, results, system, uploads

log = logging.getLogger("esl_platform.api")


class StartupRefused(RuntimeError):
    """기동 거부(CONFIG_INVALID)."""


def check_startup(config: LoadedConfig, bind_host: str | None = None) -> None:
    """dev_static 은 profile=dev 이고 127.0.0.1 바인딩일 때만."""
    s = config.settings
    if s is None:
        raise StartupRefused("CONFIG_INVALID: 설정 스키마 오류 " + ", ".join(config.error_keys()))
    host = bind_host or s.server.host
    if s.auth.mode == "dev_static" and (s.profile != "dev" or host != "127.0.0.1"):
        raise StartupRefused("CONFIG_INVALID: auth.mode=dev_static 은 profile=dev 이고 127.0.0.1 바인딩일 때만 허용됩니다")


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


def create_app(ctx: AppContext, *, bind_host: str | None = None) -> FastAPI:
    check_startup(ctx.config, bind_host)
    prefix = ctx.settings.api_prefix
    app = FastAPI(title="ESL Platform API", version=__version__, openapi_url=f"{prefix}/openapi.json",
                  docs_url=f"{prefix}/docs", redoc_url=None)
    app.state.ctx = ctx

    @app.exception_handler(DomainError)
    async def _domain(_req: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail()})

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": [str(x) for x in e.get("loc", [])], "msg": str(e.get("msg", ""))} for e in exc.errors()]
        return _error(422, "INVALID_PARAMS", "요청 값이 올바르지 않습니다", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error(404, "NOT_FOUND", "찾을 수 없습니다")
        if exc.status_code == 405:
            return _error(405, "METHOD_NOT_ALLOWED", "허용되지 않는 메서드입니다")
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _internal(_req: Request, exc: Exception) -> JSONResponse:
        log.exception("처리되지 않은 오류")
        return _error(500, "INTERNAL_ERROR", "서버 내부 오류가 발생했습니다")

    for r in (system, cases, jobs, results, history, library, uploads, client_tokens):
        app.include_router(r.router, prefix=prefix)
    if ctx.settings.server.frontend_root:  # 운영 기본: 대시보드 Vite 프록시가 /esl 전체를 넘긴다(Caddy 없이) — '/'는 가로채지 않음
        from .frontend_static import mount_frontend

        mount_frontend(app, ctx.settings.server.base_path, ctx.settings.server.frontend_root)
    return app


def _app_from_env() -> FastAPI:
    from ..core.db.engine import make_engine

    config = load_config()
    if config.settings is None:
        raise StartupRefused("CONFIG_INVALID: " + "; ".join(f"{i.key}: {i.message}" for i in config.issues))
    if not config.ok:
        log.warning("설정 검증 실패: %s — 조회만 동작, 쓰기 API 는 503", config.error_keys())
    url = os.environ.get(config.settings.database.url_env, "")
    if not url:
        raise StartupRefused(f"DB 접속 정보가 없습니다: 환경변수 {config.settings.database.url_env}")
    engine = make_engine(url, config.settings.database.pool_size)
    return create_app(build_context(config, engine), bind_host=os.environ.get("ESL_BIND_HOST"))


def __getattr__(name: str):  # 지연 생성: `uvicorn esl_platform.api.main:app`
    if name == "app":
        global app
        app = _app_from_env()
        return app
    raise AttributeError(name)
