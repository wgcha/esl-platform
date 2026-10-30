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
v0.7.0(esl_opt_run.md §11): 비드 최적화 `opt_run.*`(OptRunCfg — 기본값 = `esl.opt.DEFAULTS`, 섹션 없으면 enabled false),
OptiStruct `altair.optistruct_path`·`altair.max_concurrent_os`, argv 템플릿 `commands.os_check`·`os_solve`(argv[0] =
`{optistruct}`)·`bead_post`(argv[0] = `{hw}`). 후처리 TCL 은 코드 스냅샷 안 `resources/tcl/esl_bead_post.tcl`.
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


UPLOAD_EXT_DEFAULT = [".rad", ".inc", ".k", ".csv", ".json", ".txt", ".tcl", ".h3d", ".fem",   # .fem: S2 템플릿(v0.7.0)
                      ".sta", ".str",          # 누적 낙하 씬 이전 런 상태 파일(v0.8.0)
                      ".step", ".stp"]         # 비드 DOE 중립면 STEP(v0.9.0 esl_bead_doe.md §14)


class UploadCfg(_M):
    """브라우저 분할 업로드(계약 esl_p3_ux.md §1.1). 값은 설정 파일에서만."""

    chunk_mb: int = Field(default=64, ge=1, le=256)                   # 새 세션 청크 크기 C(MB, 세션에 고정). 계약 범위 8..256 — 시험용으로 1 까지 허용
    parallel: int = Field(default=4, ge=1, le=8)                      # 업로드당 동시 청크(초과 429) — 응답 max_parallel
    write_buffer_kb: int = Field(default=1024, ge=64, le=8192)        # 스트리밍 쓰기 단위
    preallocate: bool = True                                          # .part 사전 할당(ftruncate)
    max_file_bytes: int = Field(default=64 * 1024 ** 3, ge=1)          # 파일당(h3d 30 GB 수용)
    max_upload_bytes: int = Field(default=100 * 1024 ** 3, ge=1)       # 업로드당
    min_free_gb: float = Field(default=20, ge=0)                       # 업로드 후에도 남길 upload_root 드라이브 여유
    max_files: int = Field(default=5000, ge=1, le=100000)
    max_concurrent_per_user: int = Field(default=2, ge=1, le=20)
    stale_hours: float = Field(default=72, gt=0)
    allowed_ext: list[str] = Field(default_factory=lambda: list(UPLOAD_EXT_DEFAULT))
    state_scan_kb: int = Field(default=4096, ge=4, le=1024 * 1024)   # complete 상태 파일(.sta/.str) 종류 판정에 읽는 앞부분(KB, 줄 길이 상한 겸)

    @property
    def chunk_bytes(self) -> int:
        return self.chunk_mb * 1024 * 1024

    @property
    def write_buffer_bytes(self) -> int:
        return self.write_buffer_kb * 1024


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
    # v0.11.0(esl_scx_relay.md SR-D-9): XFER 레인(HTTP 전송·원격 대기 — SCX_FETCH 등) 루프 수. SLOT·LIGHT 와 독립, 슬롯 없음
    xfer_lanes: int = Field(default=2, ge=1, le=8)


H3D_EXTRACT_DEFAULT = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl_fwd}", "-input", "{h3d_fwd}",
                       "-part", "{part}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}",
                       "-hot_k", "{hot_k}", "-top_n", "{top_n}"]
# esl.md §4.4 + P3-UX §6: h3d_extract 허용 placeholder(argv[0] 은 {hw} 만)
H3D_EXTRACT_PLACEHOLDERS = ("hw", "extract_tcl", "extract_tcl_fwd", "h3d", "h3d_fwd", "request", "request_fwd",
                            "request_json", "request_json_fwd", "out_dir", "out_dir_fwd", "part", "hot_k", "top_n")
EXE_FORBIDDEN = re.compile(r'[&|<>^%!"\x00-\x1f]')       # argv[0] 실행 파일 경로: 공백만 허용
# esl_opt_run.md §8.1·§9·§11: OptiStruct(-check·본 실행)·비드 후처리(hw) argv 템플릿
OS_CHECK_DEFAULT = ["{optistruct}", "{fem}", "-check", "-tmpdir", "{scratch}"]
OS_SOLVE_DEFAULT = ["{optistruct}", "{fem}", "-nt", "{nt}", "-tmpdir", "{scratch}"]
BEAD_POST_DEFAULT = ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{post_tcl_fwd}", "-input", "{h3d_fwd}",
                     "-output", "{out_dir_fwd}", "-config", "{request_fwd}"]
OS_PLACEHOLDERS = ("optistruct", "fem", "fem_fwd", "nt", "work_dir", "scratch", "mem_mb")
BEAD_POST_PLACEHOLDERS = ("hw", "post_tcl", "post_tcl_fwd", "h3d", "h3d_fwd", "out_dir", "out_dir_fwd", "request",
                          "request_fwd")


class AltairCfg(_M):
    """서버 h3d 추출(계약 esl_p3_ux.md §6). hw 는 워커 LOCAL step 에서만 실행."""

    version_label: str | None = None
    # 실행 파일 경로는 코드에 두지 않는다(esl.md §2) — 예시·설치 설정이 채움(2026.1 기본 경로). None = 서버 h3d 추출 불가
    hw_exe_path: str | None = None
    max_concurrent_hw: int = Field(default=2, ge=1, le=MAX_SLOTS)   # 동시 hw 수(라이선스 한도) — DB 세마포어
    # v0.7.0 비드 최적화(esl_opt_run.md §8): OptiStruct 실행 파일(optistruct.bat). None = 서버 최적화 불가(503)
    optistruct_path: str | None = None
    max_concurrent_os: int = Field(default=1, ge=1, le=MAX_SLOTS)   # 동시 OptiStruct 수 — DB 세마포어(acquire_os)


# v0.9.0 비드 DOE(esl_bead_doe.md §6.1·§14): paicad argv 템플릿(argv[0] = {paicad}). 기본값 = esl.doe.DEFAULT_COMMANDS
# (시험 test_doe_config 가 확인). `{name?}` = 선택 자리(null 이면 바로 앞 플래그와 함께 제거 — 워커 paicad_io.build_argv).
PAICAD_VERSION_DEFAULT = ["{paicad}", "version", "--json"]
PAICAD_FIXED_SCAN_DEFAULT = ["{paicad}", "shell", "fixed-scan", "--assem-dir", "{assem_dir}", "--parts", "{parts}",
                             "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"]
PAICAD_EXTRACT_DEFAULT = ["{paicad}", "shell", "extract", "--cad", "{cad}", "--out-dir", "{out_dir}", "--assem-dir",
                          "{assem_dir?}", "--body-map", "{body_map?}", "--options", "{options?}", "--threads",
                          "{threads}"]
PAICAD_TAG_DEFAULT = ["{paicad}", "shell", "tag", "--cad", "{cad}", "--features", "{features}", "--assem-dir",
                      "{assem_dir}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}", "--body-map", "{body_map?}",
                      "--options", "{options?}", "--threads", "{threads}"]
PAICAD_GRID_DEFAULT = ["{paicad}", "shell", "view", "grid", "--cad", "{cad}", "--features", "{features}", "--cells",
                       "{cells}", "--thumb-options", "{thumb}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}",
                       "--options", "{options?}", "--threads", "{threads}"]
PAICAD_RUN_DEFAULT = ["{paicad}", "shell", "run", "--cad", "{cad}", "--features", "{features}", "--values", "{values}",
                      "--assem-dir", "{assem_dir}", "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}",
                      "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}",
                      "--out-files-dir", "{out_files_dir}", "--body-map", "{body_map?}", "--options", "{options?}",
                      "--threads", "{threads}"]
PAICAD_UPDATE_DEFAULT = ["{paicad}", "shell", "update", "--cad", "{cad}", "--features", "{features}", "--values",
                         "{values}", "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"]
PAICAD_PLACEHOLDERS = ("paicad", "assem_dir", "assem_dir?", "parts", "out_dir", "options?", "threads", "cad",
                       "body_map?", "features", "fixed_dir", "cells", "thumb", "values", "tag_dir", "update_dir",
                       "morph_dir", "check_dir", "out_files_dir")
PAICAD_DEFAULTS = {"paicad_version": PAICAD_VERSION_DEFAULT, "paicad_fixed_scan": PAICAD_FIXED_SCAN_DEFAULT,
                   "paicad_extract": PAICAD_EXTRACT_DEFAULT, "paicad_tag": PAICAD_TAG_DEFAULT,
                   "paicad_grid": PAICAD_GRID_DEFAULT, "paicad_run": PAICAD_RUN_DEFAULT,
                   "paicad_update": PAICAD_UPDATE_DEFAULT}
PAICAD_COMMANDS = tuple(PAICAD_DEFAULTS)
PAICAD_EXE_KEY = ".".join(("bead_doe", "paicad", "exe"))   # 설정 키 이름(문자열 리터럴 정적 검사 회피)


class CommandsCfg(_M):
    h3d_extract: list[str] = Field(default_factory=lambda: list(H3D_EXTRACT_DEFAULT), min_length=1)
    os_check: list[str] = Field(default_factory=lambda: list(OS_CHECK_DEFAULT), min_length=1)
    os_solve: list[str] = Field(default_factory=lambda: list(OS_SOLVE_DEFAULT), min_length=1)
    bead_post: list[str] = Field(default_factory=lambda: list(BEAD_POST_DEFAULT), min_length=1)
    paicad_version: list[str] = Field(default_factory=lambda: list(PAICAD_VERSION_DEFAULT), min_length=1)
    paicad_fixed_scan: list[str] = Field(default_factory=lambda: list(PAICAD_FIXED_SCAN_DEFAULT), min_length=1)
    paicad_extract: list[str] = Field(default_factory=lambda: list(PAICAD_EXTRACT_DEFAULT), min_length=1)
    paicad_tag: list[str] = Field(default_factory=lambda: list(PAICAD_TAG_DEFAULT), min_length=1)
    paicad_grid: list[str] = Field(default_factory=lambda: list(PAICAD_GRID_DEFAULT), min_length=1)
    paicad_run: list[str] = Field(default_factory=lambda: list(PAICAD_RUN_DEFAULT), min_length=1)
    paicad_update: list[str] = Field(default_factory=lambda: list(PAICAD_UPDATE_DEFAULT), min_length=1)


# ---------------------------------------------------------------- v0.7.0 비드 최적화(esl_opt_run.md §11)
# 기본값은 esl.opt.DEFAULTS 와 같다(시험 test_opt_config 가 확인). 값 변경은 설정 파일에서.
class OptSizeCfg(_M):
    tol_rel: float = Field(default=0.02, gt=0, le=1)
    plate_tol_rel: float = Field(default=0.05, gt=0, le=1)
    require_inch: bool = True


class OptTemplateCfg(_M):
    max_elems: int = Field(default=500000, ge=1)
    flat_tol_rel: float = Field(default=0.02, gt=0)
    max_tria_frac: float = Field(default=0.2, ge=0, le=1)


class OptBeadCfg(_M):
    angle: float = Field(default=45.0, gt=0, lt=90)          # deg
    min_width: float = Field(default=60.0, gt=0)            # mm
    height: float = Field(default=10.0, gt=0)               # mm


class OptKeepoutCfg(_M):
    hole_radius_mm: float = Field(default=15.0, ge=0)
    edge_band_mm: float = Field(default=10.0, ge=0)
    hole_min_perimeter_mm: float = Field(default=5.0, ge=0)
    max_rects: int = Field(default=20, ge=0, le=1000)
    frame_warn_mm: float = Field(default=1.0, ge=0)
    rect_name_max: int = Field(default=40, ge=1, le=200)


class OptLoadsCfg(_M):
    default_strategy: Literal["A", "B", "C"] = "A"
    mac_merge: float = Field(default=0.95, gt=0, le=1)
    max_cases: int = Field(default=20, ge=1, le=1000)
    default_k: int = Field(default=5, ge=1)
    default_objective_norm: Literal["abs", "rel"] = "abs"
    linkage: Literal["average", "complete", "single", "weighted"] = "average"
    c0_tol: float = Field(default=0.05, ge=0)

    @model_validator(mode="after")
    def _k(self) -> "OptLoadsCfg":
        if self.default_k > self.max_cases:
            raise ValueError("opt_run.loads.default_k 는 max_cases 이하여야 합니다")
        return self


class OptModeCfg(_M):
    rule_version: int = Field(default=1, ge=1)
    dent_resid_min: float = Field(default=0.5, ge=0, le=1)
    dent_conc_min: float = Field(default=0.6, ge=0, le=1)
    dent_area_frac: float = Field(default=0.05, gt=0, le=1)
    min_energy_rel: float = Field(default=1.0e-6, ge=0)


class OptSolverCfg(_M):
    drill_factor: float = Field(default=1.0e-4, gt=0)
    backend: str = "auto"


class OptLicenseRetryCfg(_M):
    max: int = Field(default=3, ge=0, le=100)
    wait_s: float = Field(default=300, ge=0)


OPT_SOLVE_ENV_KEYS = ("ALTAIR_LICENSE_PATH", "ALTAIR_HOME")      # + OMP_* (계약 §8.1)


class OptSolveCfg(_M):
    nt: int = Field(default=4, ge=1, le=1024)
    desmax: int = Field(default=30, ge=1, le=10000)
    timeout_h: float = Field(default=12, gt=0)
    log_tail_lines: int = Field(default=2000, ge=1)
    error_patterns: list[str] = Field(default_factory=lambda: [r"(?m)^\s*\*\*\* ERROR"])
    converged_patterns: list[str] = Field(default_factory=lambda: ["OPTIMIZATION HAS CONVERGED"])
    license_patterns: list[str] = Field(default_factory=lambda: [
        r"(?i)license.*(not available|checkout failed|insufficient|exceeded)", r"(?i)ALM_\w+_ERROR"])
    license_retry: OptLicenseRetryCfg = OptLicenseRetryCfg()
    env: dict[str, str] = Field(default_factory=dict)
    iteration_pattern: str = r"(?m)^\s*ITERATION\s+(\d+)"
    objective_pattern: str = r"(?im)^\s*Objective\s+Function\b[^=\n]*=\s*([-+]?[0-9.]+(?:[EeDd][-+]?\d+)?)"
    compliance_pattern: str = (r"(?m)^\s*\|\s*\d+\s*\|[^|\n]*\|\s*COMPL\w*\s*\|[^|\n]*\|[^|\n]*\|\s*(\d+)\s*\|"
                               r"\s*([-+]?[0-9.]+(?:[EeDd][-+]?\d+)?)")
    memory_patterns: list[str] = Field(default_factory=lambda: [r"(?i)(insufficient|not enough)\s+memory",
                                                                r"(?i)memory allocation failed"])
    # ERROR 블록 상세(failure_message·solve/os_errors.txt): 오류 다음 상세 줄 수, 앞 문맥(See next message …) 줄 수
    error_detail_lines: int = Field(default=4, ge=0, le=100)
    error_context_lines: int = Field(default=8, ge=0, le=100)
    error_context_pattern: str = r"(?i)See next message about line\s+(\d+)"
    error_card_pattern: str = (r"(?i)\(this is\s+(?:continuation line\s+(\d+)\s+of\s+)?([A-Z][A-Z0-9_]*)\s*,\s*"
                               r"([^\s)]+)\s+bulk data\)")
    error_code_pattern: str = r"ERROR\s*#\s*(\d+)"
    error_message_max: int = Field(default=480, ge=80, le=500)     # 작업 failure_message 열 500자


class OptPostCfg(_M):
    png_px: list[int] = Field(default_factory=lambda: [1600, 900], min_length=2, max_length=2)
    bead_area_thr_rel: float = Field(default=0.1, ge=0, le=1)
    report_map_cells: list[int] = Field(default_factory=lambda: [96, 54], min_length=2, max_length=2)


class OptCheckCfg(_M):
    bead_width_elem_factor: float = Field(default=2.0, ge=0)
    min_nodes_per_cell: float = Field(default=64, ge=0)
    max_aspect: float = Field(default=10.0, gt=0)
    max_warp_deg: float = Field(default=15.0, gt=0)


class OptGridCfg(_M):
    nx: int = Field(default=24, ge=1, le=1000)
    ny: int = Field(default=14, ge=1, le=1000)


class OptUiCfg(_M):
    max_preview_points: int = Field(default=20000, ge=10)


class OptRunCfg(_M):
    """비드 최적화(esl_opt_run.md §11). 섹션이 없으면 enabled false(POST /opt/runs 503 OPT_RUN_DISABLED)."""

    enabled: bool = False
    max_entries: int = Field(default=200, ge=1, le=10000)
    size: OptSizeCfg = OptSizeCfg()
    template: OptTemplateCfg = OptTemplateCfg()
    bead_defaults: OptBeadCfg = OptBeadCfg()
    keepout: OptKeepoutCfg = OptKeepoutCfg()
    loads: OptLoadsCfg = OptLoadsCfg()
    mode: OptModeCfg = OptModeCfg()
    solver: OptSolverCfg = OptSolverCfg()
    solve: OptSolveCfg = OptSolveCfg()
    post: OptPostCfg = OptPostCfg()
    check: OptCheckCfg = OptCheckCfg()
    grid: OptGridCfg = OptGridCfg()
    ui: OptUiCfg = OptUiCfg()


# ---------------------------------------------------------------- v0.9.0 비드 DOE(esl_bead_doe.md §14)
# 기본값은 esl.doe.DEFAULTS 와 같다(시험 test_doe_config 가 확인). 값 변경은 설정 파일에서. 크기 허용·구멍 루프·솔버·셀
# 매핑은 opt_run·library 키를 재사용한다(새 키 없음).
class BeadDoeSameCfg(_M):
    max_assem_mb: float = Field(default=4096, gt=0)          # ① Case 폴더 rad/inc 합계 상한(BD-D-13, Q1 A)


class BeadDoeTimeoutCfg(_M):
    version: float = Field(default=60, gt=0)
    fixed_scan: float = Field(default=3600, gt=0)
    extract: float = Field(default=3600, gt=0)
    tag: float = Field(default=3600, gt=0)
    grid: float = Field(default=7200, gt=0)
    run: float = Field(default=3600, gt=0)
    update: float = Field(default=1800, gt=0)


class BeadDoePaicadCfg(_M):
    exe: str | None = None                                   # setup_config 자동 감지(<런타임 venv>/Scripts/paicad 실행 파일)
    min_version: str = Field(default="0.14.0", pattern=r"^\d+(\.\d+){0,3}$")
    pinned_version: str | None = Field(default="0.14.0", pattern=r"^\d+(\.\d+){0,3}$")
    threads: int = Field(default=4, ge=1, le=1024)
    timeout_s: BeadDoeTimeoutCfg = BeadDoeTimeoutCfg()
    options: dict[str, Any] = Field(default_factory=dict)    # paicad shell options.json 내용(선택)
    env: dict[str, str] = Field(default_factory=dict)
    keep_files_top: int = Field(default=3, ge=0, le=1000)
    check_interval_s: float = Field(default=600, gt=0)       # 워커 paicad/gmsh 점검 주기


class BeadDoeMeshCfg(_M):
    size_min_mm: float = Field(default=1.0, gt=0)
    size_max_mm: float = Field(default=20.0, gt=0)
    min_size_factor: float = Field(default=0.2, gt=0, le=1)
    curvature_n: int = Field(default=12, ge=0, le=1000)
    algorithm: int = Field(default=8, ge=1, le=11)
    min_quad_frac: float = Field(default=0.8, ge=0, le=1)
    max_elems: int = Field(default=500000, ge=1)
    timeout_s: float = Field(default=1800, gt=0)
    occ_sew_faces: int = Field(default=0, ge=0, le=1)        # gmsh Geometry.OCCSewFaces(0 = 계약 기본, 면 따로인 STEP 은 1)

    @model_validator(mode="after")
    def _range(self) -> "BeadDoeMeshCfg":
        if self.size_min_mm > self.size_max_mm:
            raise ValueError("bead_doe.mesh.size_min_mm 는 size_max_mm 이하여야 합니다")
        return self


class BeadDoeDoeCfg(_M):
    default_method: Literal["lhs", "halton", "fullfact"] = "lhs"
    default_n: int = Field(default=30, ge=2)
    seed: int = Field(default=1, ge=0, le=2 ** 32 - 1)
    levels_default: int = Field(default=3, ge=2, le=9)
    levels_max: int = Field(default=9, ge=2, le=9)
    round_mm: float = Field(default=0.01, gt=0)
    default_types: list[Literal["D", "W", "U", "V"]] = Field(default_factory=lambda: ["D", "W"])

    @model_validator(mode="after")
    def _lv(self) -> "BeadDoeDoeCfg":
        if self.levels_default > self.levels_max:
            raise ValueError("bead_doe.doe.levels_default 는 levels_max 이하여야 합니다")
        return self


class BeadDoePreviewCfg(_M):
    w: int = Field(default=320, ge=16, le=4096)
    h: int = Field(default=240, ge=16, le=4096)
    view_dir: Literal["auto"] | list[float] = "auto"
    tilt_deg: float = Field(default=20, ge=0, le=90)
    margin: float = Field(default=1.15, gt=0)
    disp_range_mm: Literal["auto"] | list[float] = "auto"


class BeadDoeRunCfg(_M):
    parallel: int = Field(default=2, ge=1, le=64)
    memory_margin: float = Field(default=0.7, gt=0, le=1)


class BeadDoeSolveCfg(_M):
    reaction_warn: float = Field(default=0.01, ge=0)


class BeadDoeBoundaryCfg(_M):
    fastener_warn_mm: float = Field(default=10.0, ge=0)
    load_warn_mm: float = Field(default=20.0, ge=0)
    load_share_min: float = Field(default=0.2, ge=0, le=1)


class BeadDoeView3dCfg(_M):
    top_k: int = Field(default=3, ge=0, le=50)


class BeadDoeRankCfg(_M):
    """v0.10.0 ESL별 개선 지표(esl.doe.DEFAULTS["rank"] 거울): ratio_tol = '변화 없음' 허용치(③ 은 max(값, noise_floor)),
    per_esl_inline_max = 순위 행에 per_esl 을 넣는 상한(안 수 × ESL 수, 넘으면 GET …/results/per-esl)."""

    ratio_tol: float = Field(default=1e-6, ge=0, lt=1)
    per_esl_inline_max: int = Field(default=2000, ge=0)


class BeadDoeLimitsCfg(_M):
    """계약에 숫자가 명시된 내부 상한(esl.doe.DEFAULTS["limits"] 거울)."""

    max_json_mb: float = Field(default=64, gt=0)
    seed_max: int = Field(default=2 ** 32 - 1, ge=0)
    n_min: int = Field(default=2, ge=2)
    levels_min: int = Field(default=2, ge=2)
    cluster_k_max: int = Field(default=5, ge=1)
    ranking_report_rows: int = Field(default=20, ge=1)
    min_disp_range_mm: float = Field(default=1.0, gt=0)


class BeadDoeCfg(_M):
    """비드 형상 DOE(esl_bead_doe.md §14). 섹션이 없으면 enabled false(GET /doe/settings reason DOE_DISABLED)."""

    enabled: bool = False
    part_title: str = Field(default="chassis rear", min_length=1, max_length=200)
    max_entries: int = Field(default=50, ge=1, le=10000)
    max_designs: int = Field(default=200, ge=3, le=10000)
    step_max_mb: float = Field(default=200, gt=0)
    same: BeadDoeSameCfg = BeadDoeSameCfg()
    paicad: BeadDoePaicadCfg = BeadDoePaicadCfg()
    mesh: BeadDoeMeshCfg = BeadDoeMeshCfg()
    doe: BeadDoeDoeCfg = BeadDoeDoeCfg()
    preview: BeadDoePreviewCfg = BeadDoePreviewCfg()
    run: BeadDoeRunCfg = BeadDoeRunCfg()
    solve: BeadDoeSolveCfg = BeadDoeSolveCfg()
    boundary: BeadDoeBoundaryCfg = BeadDoeBoundaryCfg()
    view3d: BeadDoeView3dCfg = BeadDoeView3dCfg()
    rank: BeadDoeRankCfg = BeadDoeRankCfg()
    settings_cache_s: float = Field(default=300, ge=0)
    limits: BeadDoeLimitsCfg = BeadDoeLimitsCfg()


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
    upload_slim_hint_gb: float = Field(default=5, ge=0)               # 브라우저 업로드 h3d 가 이 크기(GB)를 넘으면 압축 모드 안내(0 = 끔)
    # v0.10.0: 라이브러리 [내보내기](다중 ESL zip) 노출. 기본 false = 화면 숨김, /library/exports API 는 전역 관리자만(그 외 403 EXPORT_DISABLED)
    library_export_enabled: bool = False


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


class HistoryCfg(_M):
    """실행 이력(계약 esl_p3_history.md §4): `_backup` 표식 검증 파일 탐색 상한, 내보내기·보고서 작업별 보존."""

    backup_scan_max: int = Field(default=100, ge=1, le=100000)   # 검증 파일 표식 탐색 시 열어 보는 _backup 폴더 최대 수(최신 순)
    archive_files: bool = True                                    # EXPORT·CASE_REPORT 성공 시 <case>/history/<job_id>/ 에 복사


class View3dCfg(_M):
    """④ ESL 3D 하중 보기 파생 캐시(계약 esl_3d_load.md §10). 섹션이 없어도 이 기본값으로 동작."""

    enabled: bool = True
    max_nodes: int = Field(default=2_000_000, ge=1)                  # 초과 시 413 VIEW3D_TOO_LARGE(캐시 안 함)
    max_glb_bytes: int = Field(default=64 * 1024 ** 2, ge=1)         # part.glb+part_lod.glb, values.bin 각각
    lod_min_nodes: int = Field(default=500_000, ge=0)                # 초과 시 part_lod.glb 추가
    lod_target_vertices: int = Field(default=100_000, ge=100)
    top_max: int = Field(default=100, ge=1, le=1000)                 # manifest 상위 행 수(= 화살표 최대)
    cluster_k_max: int = Field(default=5, ge=2, le=8)
    kmeans_max_iter: int = Field(default=50, ge=1, le=1000)
    build_wait_s: float = Field(default=60.0, ge=0.0)                # 생성 세마포어 대기, 초과 시 503 VIEW3D_BUSY


class LibraryCfg(_M):
    """라이브러리 설정(esl.library.settings 스키마): `config_path`(상대경로는 이 설정 파일 기준) 또는 `settings`.

    `settings` 의 `library.ista6` 상대경로도 이 설정 파일 기준.
    """

    config_path: str | None = None
    settings: dict[str, Any] | None = None


class LibraryExportCfg(_M):
    """라이브러리 다중 내보내기(v0.10.0 esl_menu_restructure.md §6·§10). 섹션이 없어도 이 기본값으로 동작."""

    max_entries: int = Field(default=50, ge=1, le=1000)              # POST /library/exports 항목 수 상한(422 TOO_MANY_ENTRIES)
    max_bundle_bytes: int | None = Field(default=None, ge=1)          # zip 상한, null = ui.max_bundle_bytes
    wait_s: float = Field(default=600.0, ge=0.0)                      # 같은 모델 앞 항목(다른 Case 작업) 결과 대기 상한


# ---------------------------------------------------------------- v0.11.0 SCX 릴레이(계약 esl_scx_relay.md §6)
# 기본값 단일 출처. 값 범위·형식은 어댑터 validate_scx_config + core/scx/settings.py 가 검사하고, 틀려도 기동은 하며 SCX 기능만
# 비활성(사유 SCX_CONFIG_INVALID — 설정 오류 목록에 넣지 않음). 형(型)이 틀린 값만 여기서 설정 오류.
class HpcScxCfg(_M):
    """`hpc.scx.*` — 키 이름 = physicsai hpc.scx.*(SR-D-4, 관리자가 블록 복사) + esl 추가 키 client_name.
    physicsai 쪽에만 있는 키는 무시한다(extra ignore)."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    relay_url: str = ""                                  # 필수. http://127.0.0.1:<대시보드 백엔드 포트>
    secret_file: str = ""                                # 필수. 절대경로(대시보드 SIMDASH_SCX_RELAY_SECRET_FILE 과 같은 파일 권장)
    client_name: str = "esl"                             # ^[a-z0-9_-]{1,32}$ (X-SCX-Relay-Client)
    drive_base: str = "~/esl"                            # B 쓰기 기준("~" | "~/<상대>")
    home_display: str = "/Users/vd.dashboard"            # 표시 전용
    appliance: str = ""                                  # B 필수(비면 B 비활성 SCX_APPLIANCE_MISSING)
    version: str = "26.1"
    ncpu: int = 16
    memory_gb: int | None = None
    queue_type: str = "implicit"
    run_type: str = "both - use starter and engine files"
    mpi: str = "Pure MPI"
    single_precision: bool = False
    poll_interval_s: float | None = None
    max_download_bytes: int = 64 * 1024 ** 3
    stage_patterns: list[str] = Field(default_factory=lambda: ["*.rad", "*.inc", "*.k", "*.sta", "*.str"])
    list_additional_paths: bool = True
    max_stage_bytes: int = 20 * 1024 ** 3
    stage_poll_s: float = 5
    stage_timeout_s: float = 14400
    submit_replay_attempts: int = 3
    submit_replay_wait_s: float = 10
    http_timeout_s: float = 30
    transfer_timeout_s: float = 14400
    collect_max_depth: int = 2
    health_ttl_s: float = 30


class HpcCfg(_M):
    """`hpc` — esl 은 scx 블록만 읽는다(physicsai 의 mode·command 등 다른 키는 무시)."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    scx: HpcScxCfg | None = None                         # 없으면 SCX 기능 전부 비활성(SCX_NOT_CONFIGURED)


class ScxDriveRootCfg(_M):
    key: str                                             # ^[a-z0-9_-]{1,32}$, 유일
    label: str
    rel: str                                             # 릴레이 홈 기준 상대(첫 구간 '.' 금지, SPDM 루트 밖)
    projects: list[str] = Field(default_factory=list)    # [] = 모든 프로젝트


class ScxDriveCfg(_M):
    """기능 A — SCX 드라이브에서 고르기(새 Case 4번째 탭)."""

    enabled: bool = False
    roots: list[ScxDriveRootCfg] = Field(default_factory=list)   # 0개면 A 비활성(SCX_NO_ROOTS)
    list_max_entries: int = 5000                         # 릴레이 max_entries(1~50000)
    max_files: int = 2000                                # rad + include + 엔진 합계
    engine_globs: list[str] = Field(default_factory=lambda: ["{stem}_0001.rad", "{stem}_000[2-9].rad"])
    file_retries: int = 2
    retry_wait_s: float = 30


class VerifyDropCompareCfg(_M):
    same_tol: float = 0.02
    hot_n: int = 20


class VerifyDropCfg(_M):
    """기능 B — Radioss 검증 낙하(키만, 구현 v0.12.0)."""

    enabled: bool = False
    max_scenes: int = 5
    default_worst_n: int = 3
    max_running: int = 2
    est_hours_per_scene: float = 3
    poll_s: float = 60
    max_wait_h: float = 72
    lost_after_polls: int = 10
    engine_globs: list[str] = Field(default_factory=lambda: ["{stem}_0001.rad", "{stem}_000[2-9].rad"])
    result_globs: dict[str, list[str]] = Field(default_factory=lambda: {"h3d": ["*.h3d"],
                                                                        "out": ["*_0000.out", "*_0001.out"]})
    out_ok_patterns: list[str] = Field(default_factory=lambda: ["NORMAL TERMINATION"])
    out_error_patterns: list[str] = Field(default_factory=lambda: [r"(?m)^\s*ERROR TERMINATION", r"(?i)\*\*\s*ERROR"])
    max_result_bytes: int = 64 * 1024 ** 3
    compare: VerifyDropCompareCfg = VerifyDropCompareCfg()


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
    history: HistoryCfg = HistoryCfg()
    view3d: View3dCfg = View3dCfg()
    upload: UploadCfg = UploadCfg()
    library: LibraryCfg | None = None   # 없으면 라이브러리 쓰기 API 503(LIBRARY_CONFIG_MISSING)
    altair: AltairCfg = AltairCfg()
    commands: CommandsCfg = CommandsCfg()
    client_token: ClientTokenCfg = ClientTokenCfg()
    opt_run: OptRunCfg | None = None    # v0.7.0 비드 최적화. 없으면 enabled false
    bead_doe: BeadDoeCfg | None = None  # v0.9.0 비드 형상 DOE. 없으면 enabled false
    library_export: LibraryExportCfg = LibraryExportCfg()   # v0.10.0 라이브러리 다중 내보내기
    hpc: HpcCfg | None = None                               # v0.11.0 SCX 릴레이(hpc.scx). 없으면 SCX 기능 비활성
    scx_drive: ScxDriveCfg = ScxDriveCfg()                  # v0.11.0 기능 A
    verify_drop: VerifyDropCfg = VerifyDropCfg()            # v0.11.0 기능 B(키만 — 구현 v0.12.0)

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


def _exe_issue(key: str, p: str | None) -> Issue | None:
    if p is None:
        return None
    if not is_abs_path(p):
        return Issue(key, "절대경로여야 합니다")
    if EXE_FORBIDDEN.search(p):
        return Issue(key, '경로에 제어문자·& | < > ^ % ! " 를 쓸 수 없습니다(공백은 허용)')
    return None


def _argv_issues(key: str, tpl: list[str], exe: str, allowed: tuple[str, ...],
                 need: tuple[tuple[str, ...], ...]) -> list[Issue]:
    """argv 템플릿 공통 검사(esl.md §4.4): argv[0] = {exe}, 허용 placeholder 만, 중괄호 짝, 메타문자 거부, 필수 placeholder."""
    out: list[Issue] = []
    if tpl[0] != "{" + exe + "}":
        out.append(Issue(f"{key}[0]", f"argv[0] 은 {{{exe}}} 여야 합니다(esl.md §4.4)"))
    for i, tok in enumerate(tpl):
        for name in template_placeholders(tok):
            if name not in allowed or (name == exe and i != 0):
                out.append(Issue(f"{key}[{i}]", f"허용되지 않는 placeholder {{{name}}}"))
        if "{" in _PH.sub("", tok) or "}" in _PH.sub("", tok):
            out.append(Issue(f"{key}[{i}]", "중괄호 짝이 맞지 않습니다"))
        if i and EXE_FORBIDDEN.search(_PH.sub("", tok)):
            out.append(Issue(f"{key}[{i}]", '제어문자·& | < > ^ % ! " 를 쓸 수 없습니다'))
    for group in need:
        if not any(n in group for t in tpl for n in template_placeholders(t)):
            out.append(Issue(key, " 또는 ".join("{" + g + "}" for g in group) + " 가 필요합니다"))
    return out


def _altair_issues(s: Settings) -> list[Issue]:
    out: list[Issue] = []
    for key, p in (("altair.hw_exe_path", s.altair.hw_exe_path), ("altair.optistruct_path", s.altair.optistruct_path)):
        iss = _exe_issue(key, p)
        if iss:
            out.append(iss)
    out += _argv_issues("commands.h3d_extract", s.commands.h3d_extract, "hw", H3D_EXTRACT_PLACEHOLDERS,
                        (("out_dir", "out_dir_fwd"), ("h3d", "h3d_fwd")))
    out += _argv_issues("commands.os_check", s.commands.os_check, "optistruct", OS_PLACEHOLDERS, (("fem", "fem_fwd"),))
    out += _argv_issues("commands.os_solve", s.commands.os_solve, "optistruct", OS_PLACEHOLDERS, (("fem", "fem_fwd"),))
    out += _argv_issues("commands.bead_post", s.commands.bead_post, "hw", BEAD_POST_PLACEHOLDERS,
                        (("out_dir", "out_dir_fwd"), ("h3d", "h3d_fwd")))
    return out


def _opt_issues(s: Settings) -> list[Issue]:
    """opt_run 의미 검사: 정규식 컴파일, solve.env 허용 키(ALTAIR_LICENSE_PATH·ALTAIR_HOME·OMP_*)."""
    o = s.opt_run
    if o is None:
        return []
    out: list[Issue] = []
    sv = o.solve
    pats = [(f"opt_run.solve.{k}[{i}]", p) for k in ("error_patterns", "converged_patterns", "license_patterns",
                                                       "memory_patterns") for i, p in enumerate(getattr(sv, k))]
    pats += [(f"opt_run.solve.{k}", getattr(sv, k)) for k in ("iteration_pattern", "objective_pattern",
                                                              "compliance_pattern", "error_context_pattern",
                                                              "error_card_pattern", "error_code_pattern")]
    for key, pat in pats:
        try:
            re.compile(pat)
        except re.error as exc:
            out.append(Issue(key, f"정규식 오류: {exc}"))
    for k, v in sv.env.items():
        if not (k in OPT_SOLVE_ENV_KEYS or re.fullmatch(r"OMP_[A-Z0-9_]+", k)):
            out.append(Issue(f"opt_run.solve.env.{k}", "허용 키는 ALTAIR_LICENSE_PATH·ALTAIR_HOME·OMP_* 입니다"))
        elif re.search(r"[\x00-\x1f]", v):
            out.append(Issue(f"opt_run.solve.env.{k}", "제어문자를 쓸 수 없습니다"))
    if any(int(x) < 16 for x in o.post.png_px) or any(int(x) < 1 for x in o.post.report_map_cells):
        out.append(Issue("opt_run.post", "png_px ≥ 16, report_map_cells ≥ 1"))
    return out


def _doe_issues(s: Settings) -> list[Issue]:
    """비드 DOE: paicad argv 템플릿(argv[0] = {paicad}, 허용 placeholder, 기본값의 필수 자리), paicad.exe 경로 문자,
    paicad.env 제어문자. 섹션이 없어도 commands 는 검사한다(설정 파일에 잘못 쓴 템플릿을 일찍 알림)."""
    out: list[Issue] = []
    for key in PAICAD_COMMANDS:
        tpl = getattr(s.commands, key)
        need = tuple((n,) for t in PAICAD_DEFAULTS[key] for n in template_placeholders(t)
                     if not n.endswith("?") and n != "paicad")
        out += _argv_issues(f"commands.{key}", tpl, "paicad", PAICAD_PLACEHOLDERS, need)
    b = s.bead_doe
    if b is None:
        return out
    iss = _exe_issue(PAICAD_EXE_KEY, b.paicad.exe)
    if iss:
        out.append(iss)
    for k, v in b.paicad.env.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k):
            out.append(Issue(f"bead_doe.paicad.env.{k}", "환경 변수 이름 형식이 아닙니다"))
        elif re.search(r"[\x00-\x1f]", v):
            out.append(Issue(f"bead_doe.paicad.env.{k}", "제어문자를 쓸 수 없습니다"))
    return out


def bead_doe_settings(s: Settings | None) -> dict[str, Any]:
    """코어 esl.doe 가 받는 bead_doe 설정 dict(esl.doe.settings 와 같은 키, 섹션 없으면 DEFAULTS·enabled false)."""
    from .opt_core import doe_settings as _doe_settings

    if s is None or s.bead_doe is None:
        return _doe_settings(None)
    return _doe_settings({"bead_doe": s.bead_doe.model_dump()})


def bead_doe_commands(s: Settings) -> dict[str, list[str]]:
    """paicad argv 템플릿 {commands.paicad_*} (워커가 작업 스냅샷으로 받음)."""
    return {k: list(getattr(s.commands, k)) for k in PAICAD_COMMANDS}


def paicad_exe_status(s: Settings | None) -> tuple[bool, str | None]:
    """paicad 실행 파일 설정·존재(stat 만 — 백엔드는 실행하지 않는다, §6.5). (ok, 사유 코드)."""
    if s is None or s.bead_doe is None or not s.bead_doe.enabled:
        return False, "DOE_DISABLED"
    p = s.bead_doe.paicad.exe
    if not p:
        return False, "PAICAD_NOT_CONFIGURED"
    if not os.path.isfile(p):
        return False, "PAICAD_NOT_FOUND"
    return True, None


def opt_settings(s: Settings | None) -> dict[str, Any]:
    """코어 esl.opt 가 받는 opt_run 설정 dict(esl.opt.settings 와 같은 키, 섹션 없으면 DEFAULTS·enabled false)."""
    from .opt_core import settings as _opt_settings

    if s is None or s.opt_run is None:
        return _opt_settings(None)
    return _opt_settings({"opt_run": s.opt_run.model_dump()})


def default_bead_post_tcl() -> str:
    """비드 후처리 TCL: 코드 스냅샷 안 resources/tcl/esl_bead_post.tcl."""
    return os.path.join(app_root(), "resources", "tcl", "esl_bead_post.tcl")


def opt_solver_status(s: Settings | None) -> tuple[bool, str | None]:
    """서버 비드 최적화 실행 가능 여부(환경 점검 check.py 와 GET /opt/settings.solver_ready 가 같은 함수, V-OR-19).

    반환 (ready, reason). 조건: opt_run.enabled, altair.optistruct_path 설정·파일 존재, 후처리 hw(altair.hw_exe_path)
    설정, esl_bead_post.tcl 존재.
    """
    if s is None:
        return False, "설정 검증 실패"
    if s.opt_run is None or not s.opt_run.enabled:
        return False, "비드 최적화가 꺼져 있습니다(설정 opt_run.enabled)"
    p = s.altair.optistruct_path
    if not p:
        return False, "서버 OptiStruct 경로가 설정되지 않았습니다(altair.optistruct_path — 관리자 문의)"
    if not os.path.isfile(p):
        return False, f"OptiStruct 실행 파일이 없습니다: {p} (altair.optistruct_path 확인)"
    if not s.altair.hw_exe_path:
        return False, "비드 후처리용 HyperView 경로가 설정되지 않았습니다(altair.hw_exe_path)"
    if not os.path.isfile(default_bead_post_tcl()):
        return False, f"비드 후처리 TCL 이 코드 스냅샷에 없습니다: {default_bead_post_tcl()}"
    return True, None


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
    issues += _opt_issues(s)
    issues += _doe_issues(s)
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
