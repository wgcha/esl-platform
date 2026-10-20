"""플랫폼 설정 로더(계약 esl.md §2 + esl_platform_p1b.md, PAI §14 패턴).

- `load_config(path=None, environ=None)`: YAML 읽기 → `validate_settings` → `LoadedConfig`.
  경로가 없으면 env `ESL_PLATFORM_CONFIG`. env `ESL_PROFILE`이 `profile`보다 우선.
- `validate_settings(d)`: 스키마(Pydantic, 알 수 없는 키 거부) + 의미 검사(루트 겹침, 경로 문자, dev_static,
  코어 설정). 문제 목록을 돌려준다(빈 목록 = 통과).
- `redacted_settings(settings)`: 응답·로그용 사본(DB URL은 env 이름만 있으므로 비밀 없음).

코드에는 키 이름과 검사 규칙만 있고 운영 값(경로·포트·기준값)은 설정 파일에만 있다.
P3-UX §6: 서버 h3d 추출(워커 LOCAL step H3D_EXTRACT)만 외부 프로그램을 실행한다 — `altair.hw_exe_path`,
`commands.h3d_extract`(argv 템플릿, esl.md §4.4: argv[0] = `{hw}`, 허용 placeholder 만, shell=False).
TCL 은 설정이 아니라 코드 스냅샷 안 `resources/tcl/esl_h3d_extract.tcl`(`default_extract_tcl()`).
P3-UX §9.1: PC 연결 코드·토큰 `client_token.*`.
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    # 백엔드가 {base_path}/ 아래에 직접 서빙할 프런트 빌드 폴더(대시보드 Vite 프록시 구성 — 기본). None·빈 값 = 서빙 안 함(Caddy 등 외부 서빙)
    frontend_root: str | None = None


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
    # P3-UX: 브라우저 업로드 저장 위치(절대경로, SPDM 밖, esl_root 와 겹침 금지). 있으면 input_roots 에 자동 포함.
    # None = 업로드 끔(업로드 API 503 UPLOAD_DISABLED)
    upload_root: str | None = None
    # 서버 폴더 찾아보기(/fs/browse) 루트에 spdm_roots 를 읽기 전용으로 포함(쓰기는 여전히 금지). 기본 끔(계약 §6)
    browse_spdm: bool = False

    @model_validator(mode="before")
    @classmethod
    def _include_upload_root(cls, d: Any) -> Any:
        """upload_root 를 input_roots 에 자동 포함(이미 그 안이면 그대로)."""
        if isinstance(d, dict) and isinstance(d.get("upload_root"), str) and d["upload_root"] \
                and isinstance(d.get("input_roots"), list):
            up = d["upload_root"]
            if not any(isinstance(r, str) and r and is_within(up, r) for r in d["input_roots"]):
                d = {**d, "input_roots": [*d["input_roots"], up]}
        return d


UPLOAD_EXT_DEFAULT = [".rad", ".inc", ".k", ".csv", ".json", ".txt", ".tcl", ".h3d"]


class UploadCfg(_M):
    """브라우저 분할 업로드(계약 esl_p3_ux.md §1.1). 값은 설정 파일에서만."""

    chunk_mb: int = Field(default=16, ge=1, le=256)                   # 청크 크기(MB)
    max_file_bytes: int = Field(default=64 * 1024 ** 3, ge=1)          # 파일당(h3d 30 GB 수용)
    max_upload_bytes: int = Field(default=100 * 1024 ** 3, ge=1)       # 업로드당
    min_free_gb: float = Field(default=20, ge=0)                       # 업로드 후에도 남길 upload_root 드라이브 여유
    max_files: int = Field(default=5000, ge=1, le=100000)
    max_concurrent_per_user: int = Field(default=2, ge=1, le=20)
    stale_hours: float = Field(default=72, gt=0)
    allowed_ext: list[str] = Field(default_factory=lambda: list(UPLOAD_EXT_DEFAULT))

    @property
    def chunk_bytes(self) -> int:
        return self.chunk_mb * 1024 * 1024


MAX_SLOTS = 16   # worker_slot 행 수(0006) — worker.slots 상한


class WorkerCfg(_M):
    limiter: Literal["auto", "none", "posix", "windows_job"]
    max_logical_cores: int = Field(ge=1)
    max_memory_gb: float = Field(gt=0)
    # P3-UX §6: SLOT 레인 동시 작업 수(같은 Case 는 직렬). 작업별 자원 = max_memory_gb·max_logical_cores 를 slots 로 나눔
    slots: int = Field(default=2, ge=1, le=MAX_SLOTS)
    # 작업 1개 메모리 한도(GB). 있으면 이 값 우선(없으면 max_memory_gb / slots)
    per_job_memory_gb: float | None = Field(default=None, gt=0)
    # POSIX RLIMIT_AS(가상 주소 공간) = max_memory_gb × vm_headroom. Windows Job 메모리는 커밋 기준이라 곱하지 않음.
    vm_headroom: float = Field(default=1.5, ge=1.0, le=8.0)
    priority: Literal["normal", "below_normal", "idle"]
    heartbeat_interval_s: float = Field(gt=0)
    lease_ttl_s: float = Field(gt=0)
    claim_interval_s: float = Field(gt=0)
    cancel_check_interval_s: float = Field(gt=0)
    terminate_grace_s: float = Field(gt=0)
    env_passthrough: list[str]
    state_dir: str


H3D_EXTRACT_DEFAULT = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl_fwd}", "-input", "{h3d_fwd}",
                       "-part", "{part}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}",
                       "-hot_k", "{hot_k}", "-top_n", "{top_n}"]
# esl.md §4.4 + P3-UX §6: h3d_extract 허용 placeholder(argv[0] 은 {hw} 만)
H3D_EXTRACT_PLACEHOLDERS = ("hw", "extract_tcl", "extract_tcl_fwd", "h3d", "h3d_fwd", "request", "request_fwd",
                            "request_json", "request_json_fwd", "out_dir", "out_dir_fwd", "part", "hot_k", "top_n")
EXE_FORBIDDEN = re.compile(r'[&|<>^%!"\x00-\x1f]')       # argv[0] 실행 파일 경로: 공백만 허용


class AltairCfg(_M):
    """서버 h3d 추출(계약 esl_p3_ux.md §6). hw 는 워커 LOCAL step 에서만 실행."""

    version_label: str | None = None
    # 실행 파일 경로는 코드에 두지 않는다(esl.md §2) — 예시·설치 설정이 채움(2026.1 기본 경로). None = 서버 h3d 추출 불가
    hw_exe_path: str | None = None
    max_concurrent_hw: int = Field(default=2, ge=1, le=MAX_SLOTS)   # 동시 hw 수(라이선스 한도) — DB 세마포어


class CommandsCfg(_M):
    h3d_extract: list[str] = Field(default_factory=lambda: list(H3D_EXTRACT_DEFAULT), min_length=1)


class ClientTokenCfg(_M):
    """PC 연결 코드·토큰(계약 esl_p3_ux.md §9.1)."""

    ttl_days: float = Field(default=30, gt=0, le=366)           # 토큰 유효 기간
    code_ttl_min: float = Field(default=15, gt=0, le=1440)      # 연결 코드 유효 시간
    # 교환 실패 잠금(계약 §10): 출발지 구분 가능(peer 가 루프백 아님, 또는 trusted_proxies 의 프록시가 붙인
    # X-Forwarded-For)이면 출발지별 lock_per_source 회, 구분 불가면 서버 전체 lock_global 회 — 창·잠금 lock_minutes 분.
    lock_per_source: int = Field(default=5, ge=1, le=100)
    lock_global: int = Field(default=30, ge=1, le=10000)
    lock_minutes: float = Field(default=15, gt=0, le=1440)
    # X-Forwarded-For 를 믿을 프록시(peer 주소·CIDR, 또는 주소가 아닌 peer 이름 그대로). 비면 XFF 무시.
    trusted_proxies: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _legacy_keys(cls, v: Any) -> Any:
        """이전 키(max_failures·lock_min) → lock_per_source·lock_minutes(새 키가 있으면 새 키 우선)."""
        if isinstance(v, dict):
            v = dict(v)
            for old, new in (("max_failures", "lock_per_source"), ("lock_min", "lock_minutes")):
                if old in v:
                    val = v.pop(old)
                    v.setdefault(new, val)
        return v

    @model_validator(mode="after")
    def _check_proxies(self) -> "ClientTokenCfg":
        for p in self.trusted_proxies:
            if not p or len(p) > 100:
                raise ValueError("client_token.trusted_proxies: 빈 값·100자 초과 불가")
            if any(c in p for c in "/.:") and not _is_net(p):
                raise ValueError(f"client_token.trusted_proxies: 주소·CIDR 형식이 아닙니다: {p}")
        return self


def _is_net(p: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_network(p, strict=False)
        return True
    except ValueError:
        return False


class UiCfg(_M):
    max_artifact_bytes: int = Field(ge=1)
    max_preview_points: int = Field(ge=10)
    poll_job_ms: int = Field(ge=100)
    poll_queue_ms: int = Field(ge=100)
    max_bundle_bytes: int = Field(default=5 * 1024 ** 3, ge=1)       # 결과 받기(zip) 상한, 초과 시 413
    browse_page_max: int = Field(default=1000, ge=10, le=10000)       # /fs/browse 한 번에 돌려주는 항목 수 상한


class LoggingCfg(_M):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    mask_patterns: list[str]


class CoreCfg(_M):
    """코어 설정: `config_path`(코어 YAML 경로, 상대경로는 이 설정 파일 기준) 또는 `settings`(코어 설정 그대로)."""

    config_path: str | None = None
    settings: dict[str, Any] | None = None


class ReportCfg(_M):
    """Case 보고서(계약 esl_p2_library.md §11): VALIDATE 성공 시 CASE_REPORT 자동 큐."""

    auto: bool = True


class LibraryCfg(_M):
    """라이브러리 설정(esl.library.settings 스키마): `config_path`(상대경로는 이 설정 파일 기준) 또는 `settings`.

    `settings` 의 `library.ista6` 상대경로도 이 설정 파일 기준.
    """

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
    report: ReportCfg = ReportCfg()
    upload: UploadCfg = UploadCfg()
    library: LibraryCfg | None = None   # 없으면 라이브러리 쓰기 API 503(LIBRARY_CONFIG_MISSING)
    altair: AltairCfg = AltairCfg()
    commands: CommandsCfg = CommandsCfg()
    client_token: ClientTokenCfg = ClientTokenCfg()

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
    library: dict[str, Any] | None = None  # 검증된 라이브러리 설정(+ _ista6), 없으면 None

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


# ---------------------------------------------------------------- 외부 실행(h3d 추출)
_PH = re.compile(r"\{([^{}]*)\}")


def template_placeholders(tok: str) -> list[str]:
    return _PH.findall(tok)


def _altair_issues(s: Settings) -> list[Issue]:
    out: list[Issue] = []
    hw = s.altair.hw_exe_path
    if hw is None:
        pass
    elif not is_abs_path(hw):
        out.append(Issue("altair.hw_exe_path", "절대경로여야 합니다"))
    elif EXE_FORBIDDEN.search(hw):
        out.append(Issue("altair.hw_exe_path", '경로에 제어문자·& | < > ^ % ! " 를 쓸 수 없습니다(공백은 허용)'))
    tpl = s.commands.h3d_extract
    if tpl[0] != "{hw}":
        out.append(Issue("commands.h3d_extract[0]", "argv[0] 은 {hw} 여야 합니다(esl.md §4.4)"))
    for i, tok in enumerate(tpl):
        for name in template_placeholders(tok):
            if name not in H3D_EXTRACT_PLACEHOLDERS or (name == "hw" and i != 0):
                out.append(Issue(f"commands.h3d_extract[{i}]", f"허용되지 않는 placeholder {{{name}}}"))
        if "{" in _PH.sub("", tok) or "}" in _PH.sub("", tok):
            out.append(Issue(f"commands.h3d_extract[{i}]", "중괄호 짝이 맞지 않습니다"))
        if i and EXE_FORBIDDEN.search(_PH.sub("", tok)):
            out.append(Issue(f"commands.h3d_extract[{i}]", '제어문자·& | < > ^ % ! " 를 쓸 수 없습니다'))
    if not any(n in ("out_dir", "out_dir_fwd") for t in tpl for n in template_placeholders(t)):
        out.append(Issue("commands.h3d_extract", "{out_dir} 또는 {out_dir_fwd} 가 필요합니다"))
    if not any(n in ("h3d", "h3d_fwd") for t in tpl for n in template_placeholders(t)):
        out.append(Issue("commands.h3d_extract", "{h3d} 또는 {h3d_fwd} 가 필요합니다"))
    return out


def app_root() -> str:
    """코드 스냅샷(저장소 루트 또는 <런타임>/app) — backend/esl_platform 의 두 단계 위."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def default_extract_tcl() -> str:
    """서버 h3d 추출 TCL: 코드 스냅샷 안 resources/tcl/esl_h3d_extract.tcl(배포가 함께 복사)."""
    return os.path.join(app_root(), "resources", "tcl", "esl_h3d_extract.tcl")


def per_job_limits(w: WorkerCfg) -> tuple[float, int]:
    """작업 1개 자원(메모리 GB, 논리 코어): per_job_memory_gb 우선, 아니면 max_memory_gb / slots. 코어 = max_logical_cores // slots(≥1)."""
    mem = float(w.per_job_memory_gb) if w.per_job_memory_gb else float(w.max_memory_gb) / int(w.slots)
    cores = max(1, int(w.max_logical_cores) // int(w.slots))
    return mem, cores


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


def _library(s: Settings, base_dir: str | None) -> tuple[list[Issue], dict[str, Any] | None]:
    lc = s.library
    if lc is None:
        return [], None
    if (lc.config_path is None) == (lc.settings is None):
        return [Issue("library", "config_path 와 settings 중 정확히 하나가 필요합니다")], None
    from esl_worker.core_adapter import CoreError, load_library_config, validate_library_settings

    base = base_dir or os.getcwd()
    try:
        if lc.config_path is not None:
            p = lc.config_path if os.path.isabs(lc.config_path) else os.path.join(base, lc.config_path)
            if not os.path.isfile(p):
                return [Issue("library.config_path", f"파일이 없습니다: {p}")], None
            return [], load_library_config(p)
        return [], validate_library_settings(lc.settings, base)
    except CoreError as exc:
        return [Issue("library", f"{exc.code}: {exc.message}")], None


def _semantic(s: Settings, base_dir: str | None) -> tuple[list[Issue], dict[str, Any] | None]:
    issues: list[Issue] = []
    # 폴더·index.html이 없는 것은 오류가 아니다(기동 후 배치될 수 있음) — 환경 점검 server.frontend_root가 WARN으로 알린다
    if s.server.frontend_root and not is_abs_path(s.server.frontend_root):
        issues.append(Issue("server.frontend_root", "절대경로여야 합니다(빈 값 = 서빙 안 함)"))
    st = s.storage
    for key, p in [("storage.esl_root", st.esl_root)] + [
        (f"storage.input_roots[{i}]", r) for i, r in enumerate(st.input_roots)
    ] + [(f"storage.spdm_roots[{i}]", r) for i, r in enumerate(st.spdm_roots)]:
        iss = _path_issue(key, p)
        if iss:
            issues.append(iss)
    if st.upload_root is not None:
        iss = _path_issue("storage.upload_root", st.upload_root)
        if iss:
            issues.append(iss)
    if not issues:
        if st.upload_root is not None:
            if overlaps(st.upload_root, st.esl_root):
                issues.append(Issue("storage.upload_root", "esl_root 와 겹칩니다"))
            for r in st.spdm_roots:
                if overlaps(st.upload_root, r):
                    issues.append(Issue("storage.upload_root", f"SPDM 루트({r})와 겹칩니다"))
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
    for i, ext in enumerate(s.upload.allowed_ext):
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
            issues.append(Issue(f"upload.allowed_ext[{i}]", "'.확장자'(소문자·숫자) 형식이어야 합니다"))
    if s.upload.max_file_bytes > s.upload.max_upload_bytes:
        issues.append(Issue("upload.max_file_bytes", "max_upload_bytes 보다 클 수 없습니다"))
    issues += _altair_issues(s)
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


def validate_library(s: Settings | None, *, base_dir: str | None = None) -> tuple[list[Issue], dict | None]:
    if s is None:
        return [], None
    return _library(s, base_dir)


def load_config_dict(d: dict[str, Any], *, environ: dict[str, str] | None = None, base_dir: str | None = None,
                     path: str | None = None, sha256: str | None = None) -> LoadedConfig:
    env = os.environ if environ is None else environ
    d = copy.deepcopy(d)
    prof = env.get(ENV_PROFILE)
    if prof and isinstance(d, dict):
        d["profile"] = prof
    s, issues, core = validate_settings(d, base_dir=base_dir)
    lib_issues, lib = validate_library(s, base_dir=base_dir)
    return LoadedConfig(s, issues + lib_issues, path, sha256, core, lib)


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
