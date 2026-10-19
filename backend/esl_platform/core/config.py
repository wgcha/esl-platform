"""플랫폼 설정 로더(계약 esl.md §2 + esl_platform_p1b.md, PAI §14 패턴).

- `load_config(path=None, environ=None)`: YAML 읽기 → `validate_settings` → `LoadedConfig`.
  경로가 없으면 env `ESL_PLATFORM_CONFIG`. env `ESL_PROFILE`이 `profile`보다 우선.
- `validate_settings(d)`: 스키마(Pydantic, 알 수 없는 키 거부) + 의미 검사(루트 겹침, 경로 문자, dev_static,
  코어 설정). 문제 목록을 돌려준다(빈 목록 = 통과).
- `redacted_settings(settings)`: 응답·로그용 사본(DB URL은 env 이름만 있으므로 비밀 없음).

코드에는 키 이름과 검사 규칙만 있고 운영 값(경로·포트·기준값)은 설정 파일에만 있다.
`altair`·`commands`·`resources` 키는 없다(서버에서 외부 프로그램을 실행하지 않음).
"""

from __future__ import annotations

import copy
import hashlib
import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENV_CONFIG = "ESL_PLATFORM_CONFIG"
ENV_PROFILE = "ESL_PROFILE"
SCHEMA_VERSION = 1
PATH_FORBIDDEN = re.compile(r'[\s&|<>^%!"\x00-\x1f]')


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerCfg(_M):
    host: str
    port: int = Field(ge=1, le=65535)
    base_path: str = Field(pattern=r"^/[A-Za-z0-9_\-/]*[A-Za-z0-9_\-]$")


class DatabaseCfg(_M):
    url_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    pool_size: int = Field(ge=1, le=100)


class Membership(_M):
    project_id: str
    role: Literal["general", "power", "admin"]


class DevPrincipal(_M):
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    memberships: list[Membership]


class AuthCfg(_M):
    mode: Literal["dashboard", "dev_static"]
    dashboard_internal_url: str
    dashboard_public_login_url: str
    cookie_name: str
    introspection_path: str
    projects_path: str
    cache_ttl_s: float = Field(ge=0)
    timeout_s: float = Field(gt=0)
    dev_static_principal: DevPrincipal | None = None


class StorageCfg(_M):
    esl_root: str
    input_roots: list[str]
    spdm_roots: list[str]


class WorkerCfg(_M):
    limiter: Literal["auto", "none", "posix", "windows_job"]
    max_logical_cores: int = Field(ge=1)
    max_memory_gb: float = Field(gt=0)
    priority: Literal["normal", "below_normal", "idle"]
    heartbeat_interval_s: float = Field(gt=0)
    lease_ttl_s: float = Field(gt=0)
    claim_interval_s: float = Field(gt=0)
    cancel_check_interval_s: float = Field(gt=0)
    terminate_grace_s: float = Field(gt=0)
    env_passthrough: list[str]
    state_dir: str


class UiCfg(_M):
    max_artifact_bytes: int = Field(ge=1)
    max_preview_points: int = Field(ge=10)
    poll_job_ms: int = Field(ge=100)
    poll_queue_ms: int = Field(ge=100)


class LoggingCfg(_M):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    mask_patterns: list[str]


class CoreCfg(_M):
    """코어 설정: `config_path`(코어 YAML 경로, 상대경로는 이 설정 파일 기준) 또는 `settings`(코어 설정 그대로)."""

    config_path: str | None = None
    settings: dict[str, Any] | None = None


class Settings(_M):
    schema_version: Literal[1]
    profile: Literal["dev", "prod"]
    server: ServerCfg
    database: DatabaseCfg
    auth: AuthCfg
    storage: StorageCfg
    worker: WorkerCfg
    ui: UiCfg
    logging: LoggingCfg
    core: CoreCfg

    @property
    def api_prefix(self) -> str:
        return self.server.base_path.rstrip("/") + "/api"


@dataclass
class Issue:
    key: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "message": self.message}


@dataclass
class LoadedConfig:
    settings: Settings | None
    issues: list[Issue] = field(default_factory=list)
    path: str | None = None
    sha256: str | None = None
    core: dict[str, Any] | None = None  # 검증된 코어 설정(작업 생성 시 스냅샷)

    @property
    def ok(self) -> bool:
        return self.settings is not None and not self.issues and self.core is not None

    def error_keys(self) -> list[str]:
        return [i.key for i in self.issues]

    def errors(self) -> list[dict[str, str]]:
        return [i.as_dict() for i in self.issues]


# ---------------------------------------------------------------- 경로 도우미
def norm_abs(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def is_within(child: str, parent: str) -> bool:
    c, p = norm_abs(child), norm_abs(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


def overlaps(a: str, b: str) -> bool:
    return is_within(a, b) or is_within(b, a)


WIN_ABS = re.compile(r"^[A-Za-z]:[/\\\\]")
WIN_UNC = re.compile(r"^[\\/]{2}[^\\/]+[\\/][^\\/]+")


def is_abs_path(p: str) -> bool:
    """Windows 드라이브 절대경로(예시 설정을 Linux 에서도 검증하기 위함) 또는 POSIX 호스트의 `/` 절대경로.

    Windows 호스트에서는 드라이브 없는 루트 상대(`\\x`, `/x`)·드라이브 상대(`C:x`)를 받지 않는다(os.path.isabs 미사용).
    """
    if not p:
        return False
    if WIN_ABS.match(p) or WIN_UNC.match(p):
        return True
    return os.name != "nt" and posixpath.isabs(p)


def _path_issue(key: str, p: str) -> Issue | None:
    if not is_abs_path(p):
        return Issue(key, "절대경로여야 합니다")
    if PATH_FORBIDDEN.search(p):
        return Issue(key, '경로에 공백·제어문자·& | < > ^ % ! " 를 쓸 수 없습니다')
    return None


# ---------------------------------------------------------------- 검증
def _schema(d: Any) -> tuple[Settings | None, list[Issue]]:
    if not isinstance(d, dict):
        return None, [Issue("(root)", "YAML 최상위는 mapping 이어야 합니다")]
    try:
        return Settings.model_validate(d), []
    except ValidationError as exc:
        out = []
        for e in exc.errors():
            key = ".".join(str(x) for x in e.get("loc", ())) or "(root)"
            out.append(Issue(key, str(e.get("msg", ""))))
        return None, out


def _semantic(s: Settings, base_dir: str | None) -> tuple[list[Issue], dict[str, Any] | None]:
    issues: list[Issue] = []
    st = s.storage
    for key, p in [("storage.esl_root", st.esl_root)] + [
        (f"storage.input_roots[{i}]", r) for i, r in enumerate(st.input_roots)
    ] + [(f"storage.spdm_roots[{i}]", r) for i, r in enumerate(st.spdm_roots)]:
        iss = _path_issue(key, p)
        if iss:
            issues.append(iss)
    if not issues:
        for i, r in enumerate(st.input_roots):
            if overlaps(r, st.esl_root):
                issues.append(Issue(f"storage.input_roots[{i}]", "esl_root 와 겹칩니다"))
        for i, r in enumerate(st.spdm_roots):
            if overlaps(r, st.esl_root):
                issues.append(Issue(f"storage.spdm_roots[{i}]", "esl_root 와 겹칩니다"))
    if s.auth.mode == "dev_static":
        if s.profile != "dev":
            issues.append(Issue("auth.mode", "dev_static 은 profile=dev 에서만 허용됩니다"))
        if s.auth.dev_static_principal is None:
            issues.append(Issue("auth.dev_static_principal", "dev_static 에 필요합니다"))
    w = s.worker
    if w.lease_ttl_s <= w.heartbeat_interval_s:
        issues.append(Issue("worker.lease_ttl_s", "heartbeat_interval_s 보다 커야 합니다"))
    for i, pat in enumerate(s.logging.mask_patterns):
        try:
            re.compile(pat)
        except re.error as exc:
            issues.append(Issue(f"logging.mask_patterns[{i}]", f"정규식 오류: {exc}"))

    core = None
    c = s.core
    if (c.config_path is None) == (c.settings is None):
        issues.append(Issue("core", "config_path 와 settings 중 정확히 하나가 필요합니다"))
        return issues, None
    from esl_worker.core_adapter import CoreError, load_core_config, validate_core_settings

    try:
        if c.config_path is not None:
            p = c.config_path
            if not os.path.isabs(p):
                p = os.path.join(base_dir or os.getcwd(), p)
            if not os.path.isfile(p):
                issues.append(Issue("core.config_path", f"파일이 없습니다: {p}"))
                return issues, None
            core = load_core_config(p)
        else:
            core = validate_core_settings(c.settings)
    except CoreError as exc:
        issues.append(Issue("core", f"{exc.code}: {exc.message}"))
        core = None
    return issues, core


def validate_settings(d: Any, *, base_dir: str | None = None) -> tuple[Settings | None, list[Issue], dict | None]:
    s, issues = _schema(d)
    if s is None:
        return None, issues, None
    sem, core = _semantic(s, base_dir)
    return s, sem, core


def load_config_dict(d: dict[str, Any], *, environ: dict[str, str] | None = None, base_dir: str | None = None,
                     path: str | None = None, sha256: str | None = None) -> LoadedConfig:
    env = os.environ if environ is None else environ
    d = copy.deepcopy(d)
    prof = env.get(ENV_PROFILE)
    if prof and isinstance(d, dict):
        d["profile"] = prof
    s, issues, core = validate_settings(d, base_dir=base_dir)
    return LoadedConfig(s, issues, path, sha256, core)


def load_config(path: str | None = None, *, environ: dict[str, str] | None = None) -> LoadedConfig:
    env = os.environ if environ is None else environ
    p = path or env.get(ENV_CONFIG)
    if not p:
        return LoadedConfig(None, [Issue("(file)", f"설정 파일 경로가 없습니다(env {ENV_CONFIG})")])
    try:
        with open(p, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return LoadedConfig(None, [Issue("(file)", f"설정 파일을 읽을 수 없습니다: {exc}")], p)
    sha = hashlib.sha256(raw).hexdigest()
    try:
        d = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return LoadedConfig(None, [Issue("(file)", f"YAML 오류: {exc}")], p, sha)
    return load_config_dict(d, environ=env, base_dir=os.path.dirname(os.path.abspath(p)), path=p, sha256=sha)


def redacted_settings(s: Settings) -> dict[str, Any]:
    d = s.model_dump()
    d["database"] = {"url_env": s.database.url_env, "pool_size": s.database.pool_size}
    return d
