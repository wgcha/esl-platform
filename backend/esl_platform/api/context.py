"""앱 문맥: 설정·DB 엔진·인증기."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.engine import Engine

from ..core.auth import Authenticator, DashboardClient
from ..core.config import LoadedConfig, Settings


@dataclass
class AppContext:
    config: LoadedConfig
    engine: Engine
    auth: Authenticator

    @property
    def settings(self) -> Settings:
        assert self.config.settings is not None
        return self.config.settings


def build_context(config: LoadedConfig, engine: Engine, *, transport: httpx.BaseTransport | None = None,
                  clock: Any = None) -> AppContext:
    if config.settings is None:
        raise RuntimeError("CONFIG_INVALID: 설정 스키마 오류로 앱을 만들 수 없습니다: " + ", ".join(config.error_keys()))
    s = config.settings
    client = DashboardClient(s.auth, transport=transport) if s.auth.mode == "dashboard" else None
    kw = {"clock": clock} if clock is not None else {}
    return AppContext(config, engine, Authenticator(s.auth, client, **kw))
