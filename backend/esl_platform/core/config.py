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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_serializer, model_validator

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
    preallocate: bool = False                                         # .part 사전 할당(ftruncate). v0.12.5 기본 false — Windows 는 0 을 써서 채워 그동안 다른 청크 PUT 이 기다림
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


class FsRetryCfg(_M):
    """이슈 #53 WinError 32: 원자적 교체(esl.fsutil.atomic_replace)의 Windows 잠금(WinError 5/32) 재시도.
    기본값 = esl.fsutil.DEFAULTS(시험 test_fs_retry 가 확인). 대기 = base_s × 2^i(합계 ≤ max_wait_s)."""
    attempts: int = Field(default=8, ge=1, le=100)
    max_wait_s: float = Field(default=10.0, ge=0, le=600)
    base_s: float = Field(default=0.05, gt=0, le=10)


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
    # v0.12.3: 워커 안 장시간 호출(inproc)이 취소·오류로 멈출 때 작업 스레드 종료를 기다리는 상한(넘으면 로그 후 진행)
    inproc_join_max_s: float = Field(default=3600.0, gt=0)
    env_passthrough: list[str]
    state_dir: str
    # v0.11.0(esl_scx_relay.md SR-D-9): XFER 레인(HTTP 전송·원격 대기 — SCX_FETCH 등) 루프 수. SLOT·LIGHT 와 독립, 슬롯 없음
    xfer_lanes: int = Field(default=2, ge=1, le=8)
    # 이슈 #53: 파일 교체가 백신·인덱서 등의 잠깐 잠금(WinError 5/32)에 걸릴 때 재시도(끝내 실패 → FILE_LOCKED). 백엔드도 같은 값
    fs_retry: FsRetryCfg = Field(default_factory=FsRetryCfg)


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
    # 자체 쉘 솔버 해 수용 검사(D-0.14-RESID). None = 코어 기본값(esl.config.SOLVER_CHECK_DEFAULTS) — 지정했을 때만
    # dump 에 넣는다(코어 opt DEFAULTS 와 같은 모양·DOE 설정 해시 불변)
    resid_rel_cap: float | None = Field(default=None, gt=0, lt=1)
    equilibrium_tol_rel: float | None = Field(default=None, gt=0, lt=1)

    @model_serializer(mode="wrap")
    def _drop_unset_checks(self, handler):
        d = handler(self)
        for k in ("resid_rel_cap", "equilibrium_tol_rel"):
            if d.get(k) is None:
                d.pop(k, None)
        return d


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
    engine_rad: bool = False      # v0.12.1 prep/assem_full 에 엔진 rad(<stem>_NNNN.rad, NNNN≠0000) 포함 여부(체결 정의 없음)


_KW_PATH = re.compile(r"^[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*$")


class BeadDoeFixedScanCfg(_M):
    """v0.12.1 paicad 스캔 사본(prep/assem_full)만 집합 카드 정규화(원본·모핑 사본 불변, esl.doe.assem_full).
    paicad 0.14.0 은 /GRNOD/{NODE,PART,GRNOD}/<id>·/SURF/{PART,SEG,SURF}/<id>(id = kw[2]) 만 읽는다."""

    enabled: bool = True                      # 정규화 전체 켜고 끄기
    rules: list[list[str]] = Field(default_factory=lambda: [["SURF/PART/EXT", "SURF/PART"], ["SURF/PART/ALL", "SURF/PART"]],
                                   max_length=50)        # 키워드 줄만(데이터 그대로)
    expand_subset: bool = True                # /SURF/SUBSET/<EXT|ALL>/<id>·/GRNOD/SUBSET/<id> → 파트 목록 /…/PART/<id>
    expand_gene: bool = True                  # /GRNOD/GENE(first last 쌍)·GEN_INCR → /GRNOD/NODE/<id>
    expand_solid: bool = True                 # /SURF/PART·SUBSET 에 솔리드 파트 → /SURF/SEG(EXT 외곽 면·ALL 모든 면)
    # /SUBSET 해석: auto = starter /BEGIN 버전(Invers)·#RADIOSS STARTER 주석으로 판정(불가 → 2024 규칙), 2024·2026 =
    # 데이터 줄 = 하위 subset ID(파트는 /PART 3번째 칸 subset_ID), legacy = 데이터 줄 id 가 파트여도 허용
    subset_format: Literal["auto", "2024", "2026", "legacy"] = "auto"

    @model_validator(mode="after")
    def _rules(self):
        for r in self.rules:
            if len(r) != 2 or not all(isinstance(x, str) and _KW_PATH.match(x) for x in r):
                raise ValueError("fixed_scan.rules 항목은 [\"KW/SUB/OPT\", \"KW/SUB\"] 형식")
        return self


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
    min_version: str = Field(default="0.15.4", pattern=r"^\d+(\.\d+){0,3}$")
    pinned_version: str | None = Field(default="0.15.4", pattern=r"^\d+(\.\d+){0,3}$")
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


class BeadDoeGridCfg(_M):
    """v0.17.2(이슈 #63, esl.doe.DEFAULTS["grid"] 거울): 미리보기 grid 셀 중 판정된 셀(READY·충돌·고정 스킵) 비율이
    min_ok_frac 미만이거나 READY 0 이면 BD_GRID 실패(GRID_TOO_FEW_OK·GRID_ALL_FAILED)."""

    min_ok_frac: float = Field(default=0.5, ge=0, le=1)


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
    # v0.20.0 강성 지표(esl_stiffness_metric.md §6): 순위 지표 metric lin(재풀이 없는 1차 섭동 C_lin, 새 스터디 기본)|solve(재풀이 C — 옛 동작),
    # lin_form ritz(C_ref/ρ — 사용자 확정 기본)|taylor(C_ref(2−ρ)), lin_valid = |ρ−1| 초과 → SM_LIN_RANGE, imbalance_warn = 불평형
    # imbalance_rel 초과 → SM_IMBALANCE. 새 스냅샷에만 doe.rank 로 고정(옛 스냅샷 = 키 없음 = solve)
    metric: Literal["lin", "solve"] = "lin"
    lin_form: Literal["ritz", "taylor"] = "ritz"
    lin_valid: float = Field(default=0.3, gt=0)
    imbalance_warn: float = Field(default=0.02, gt=0, le=1)


class BeadDoeLimitsCfg(_M):
    """계약에 숫자가 명시된 내부 상한(esl.doe.DEFAULTS["limits"] 거울)."""

    max_json_mb: float = Field(default=64, gt=0)
    seed_max: int = Field(default=2 ** 32 - 1, ge=0)
    n_min: int = Field(default=2, ge=2)
    levels_min: int = Field(default=2, ge=2)
    cluster_k_max: int = Field(default=5, ge=1)
    ranking_report_rows: int = Field(default=20, ge=1)
    min_disp_range_mm: float = Field(default=1.0, gt=0)


class BeadDoeFallbackNofixCfg(_M):
    """v0.15.1 OCC 정리 끔: scopes 순서로 face(그 면만 정리 없이 다시 가져와 대체)·all(세션 전체 정리·봉합 끔)."""

    scopes: list[str] = Field(default_factory=lambda: ["face", "all"], min_length=1, max_length=2)
    # face 대체 면 = 정리 없이 가져온 면 중 bbox ± bbox_tol mm·같은 면 종류·넓이 ± area_rtol(상대)이 1개일 때만(0·2개 이상 → 건너뜀)
    bbox_tol: float = Field(default=1e-2, gt=0, le=1.0)
    area_rtol: float = Field(default=1e-2, gt=0, le=0.5)
    # v0.17.4 C2-D-38 엄격 대응 0개면 정리가 키운 면(조각 → 완전한 구)을 bbox 안·넓이 ≥ area / area_grow_max 로 찾음(≤ 1 = 끔)
    area_grow_max: float = Field(default=1000.0, ge=0)

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v: list[str]) -> list[str]:
        if any(x not in ("face", "all") for x in v) or len(set(v)) != len(v):
            raise ValueError(f"nofix.scopes 는 face·all 중 중복 없이: {v}")
        return v


class BeadDoeFallbackSplitCfg(_M):
    """v0.15.1 면 분할: 실패 면을 bbox 중심을 지나는 평면 planes 개(가장 긴 bbox 방향 법선 순)로 나눔."""

    planes: int = Field(default=2, ge=1, le=2)


class BeadDoeFallbackFillCfg(_M):
    """v0.15.1 채움 면 대체: 경계 고리 BSpline 채움(안쪽 (points−1)² 점 통과), 원 면 대비 편차 ≤ tol_factor × h 일 때만."""

    tol_factor: float = Field(default=0.5, ge=0)
    points: int = Field(default=8, ge=0, le=30)
    samples: int = Field(default=10, ge=2, le=50)


class BeadDoeFallbackSmallCfg(_M):
    """v0.15.1 작은 면 평면 채움: 넓이 < area_mm2 면을 경계만으로 채움(편차 ≤ tol_factor × h)."""

    area_mm2: float = Field(default=50.27, ge=0)
    tol_factor: float = Field(default=1.0, ge=0)
    samples: int = Field(default=10, ge=2, le=50)


class BeadDoeCompareMeshFallbackCfg(_M):
    """v0.14.1 면 단위 폴백(esl.doe.mesh_gmsh.mesh_file): 2D 메싱이 실패한 면만 algorithms 순서로 재시도, relax 면 그 면의
    작은 형상 처리·구멍 둘레 분할을 풀고 다시. 실패 면이 max_faces 개를 넘으면 FAILED_MESH."""

    enabled: bool = True
    algorithms: list[int] = Field(default_factory=lambda: [6, 5, 1], max_length=8)   # gmsh Mesh.Algorithm 번호
    relax: bool = True
    max_faces: int = Field(default=20, ge=1, le=1000)
    # v0.15.1 형상 폴백(이슈 #53 Sphere 면): 단계 묶음 순서(빼면 끔), periodic_types 면은 periodic_order
    order: list[str] = Field(default_factory=lambda: ["algorithms", "relax", "split", "fill", "small"], max_length=6)
    periodic_types: list[str] = Field(default_factory=lambda: ["Sphere"], max_length=16)
    periodic_order: list[str] = Field(default_factory=lambda: ["nofix", "split", "fill", "small", "algorithms", "relax"],
                                      max_length=6)
    nofix: BeadDoeFallbackNofixCfg = BeadDoeFallbackNofixCfg()
    split: BeadDoeFallbackSplitCfg = BeadDoeFallbackSplitCfg()
    fill: BeadDoeFallbackFillCfg = BeadDoeFallbackFillCfg()
    small: BeadDoeFallbackSmallCfg = BeadDoeFallbackSmallCfg()

    @field_validator("algorithms")
    @classmethod
    def _algs(cls, v: list[int]) -> list[int]:
        bad = [a for a in v if a not in (1, 2, 5, 6, 7, 8, 9, 11)]
        if bad:
            raise ValueError(f"gmsh 2D 알고리즘 번호가 아님: {bad}")
        return v

    @field_validator("order", "periodic_order")
    @classmethod
    def _order(cls, v: list[str]) -> list[str]:
        ok = ("algorithms", "relax", "nofix", "split", "fill", "small")
        bad = [x for x in v if x not in ok]
        if bad or len(set(v)) != len(v):
            raise ValueError(f"폴백 단계는 {', '.join(ok)} 중 중복 없이: {v}")
        return v


# v0.16.0 ④ 메시 옵션(esl_compare_mesh_options.md §5): 폴백 사다리 단계 이름(C2-D-18)·메시 입력 형식(C2-D-2, Q2 — .bdf·.fem 은
# v0.16.x 에서 이 목록을 넓힘)
COMPARE_LADDER_STAGES = ("cad", "refine_local", "refine_global", "defeature", "remesh", "freeform", "tria")   # v0.16.1 += defeature(SR-D-16), v0.16.3 += freeform·tria(C2-D-26·28)
COMPARE_LADDER_DEFAULT = ("cad", "refine_local", "refine_global", "freeform", "defeature", "tria")   # v0.16.3 기본 순서
COMPARE_MESH_FORMATS = (".rad", ".inc")
# v0.16.1 작은 형상 억제 종류(esl_select_relax.md SR-D-17 — 이 순서로 실행)
DEFEATURE_KINDS = ("flange", "hole", "slot", "bead", "fillet", "narrow")


class BeadDoeCompareFaceFailCfg(_M):
    """v0.16.3 면 실패 판정(C2-D-27): 실패 면 종류 ∈ types 또는 gmsh 문구에 patterns(대소문자 무시) → skip 단계를 건너뜀."""

    enabled: bool = True
    types: list[str] = Field(default_factory=lambda: ["Sphere"], max_length=32)
    patterns: list[str] = Field(default_factory=lambda: ["periodic surface", "closed loop", "degenerate"], max_length=32)
    skip: list[str] = Field(default_factory=lambda: ["refine_local", "refine_global"], max_length=8)

    @field_validator("skip")
    @classmethod
    def _skip(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in COMPARE_LADDER_STAGES or x == "cad"]
        if bad or len(set(v)) != len(v):
            raise ValueError(f"mesh.face_fail.skip 는 cad 를 뺀 사다리 단계 중 중복 없이: {v}")
        return v


class BeadDoeCompareCadRelaxedCfg(_M):
    """v0.17.4 cad_relaxed(C2-D-32): cad 첫 세션 면 실패 → 면 폴백 전에 모델 전체를 ③ 옵션으로 1세션(품질·충실도 통과면 채택)."""

    enabled: bool = True
    occ_fix_small: int = Field(default=0, ge=0, le=1)
    curvature_n: int = Field(default=12, ge=0, le=1000)
    min_size_factor: float = Field(default=0.2, gt=0, le=1)
    defeature: bool = False    # false = 구멍 메움(compare.defeature) 끔(실측: 정리 끔 + 구멍 메움 끔이 1 성분)
    fidelity: bool = True      # 원 STEP OCC 삼각화 대비 hausdorff ≤ remesh.fidelity.fail_mm 확인
    # v0.18.2 C2-D-45: isolate = cad 자식 안이 아니라 부모가 자기 하위 프로세스·자기 제한(timeout_s, null = mesh.timeout_s)으로,
    # fidelity_samples = 충실도 비교 표본 상한(양방향 각각, 고정 간격 — remesh.fidelity.samples_max 보다 크면 그 값)
    isolate: bool = True
    timeout_s: float | None = Field(default=900.0, gt=0)
    fidelity_samples: int = Field(default=20000, ge=1000)


class BeadDoeCompareLargeCfg(_M):
    """v0.17.4 대형 모델(C2-D-33): STEP 면 > mesh.large_faces 또는 periodic_types 면 있음 → 면 폴백 세션 상한·cad 몫 줄임."""

    periodic_types: list[str] = Field(default_factory=lambda: ["Sphere"], max_length=16)
    fallback_sessions: int = Field(default=3, ge=0, le=1000)   # 0 = 상한 없음
    cad_share: float = Field(default=0.15, gt=0, le=1)         # cad 제한 ≤ cad_share × refine.total_timeout_s(auto)
    tria_timeout_s: float | None = Field(default=900.0, gt=0)   # v0.18.2 C2-D-46 대형 tria 시도 제한(null = tria.timeout_s)


class BeadDoeCompareMeshCfg(_M):
    """v0.14.0 ④ 메시 프로필(esl_step_compare.md SC-D-5): bead_doe.mesh 를 키별 덮어씀. size_mm 범위는 BeadDoeCfg 가 확인."""

    size_mm: float = Field(default=3.0, gt=0)                # h 고정(auto 아님)
    curvature_n: int = Field(default=0, ge=0, le=1000)       # 곡률 세분화 끔
    min_size_factor: float = Field(default=0.8, gt=0, le=1)  # 최소 크기 = h × 이 값
    extend_from_boundary: int = Field(default=0, ge=0, le=1)  # gmsh Mesh.MeshSizeExtendFromBoundary
    occ_fix_small: int = Field(default=1, ge=0, le=1)        # gmsh Geometry.OCCFixDegenerated·SmallEdges·SmallFaces
    feature_angle: float = Field(default=10.0, ge=0, le=180)  # 이슈 #53 BatchMesher feature_angle(기록만 — gmsh 대응 없음)
    fallback: BeadDoeCompareMeshFallbackCfg = BeadDoeCompareMeshFallbackCfg()   # v0.14.1 면 단위 폴백
    # v0.16.0 메시 방식(esl_compare_mesh_options.md C2-D-9·18): auto = ladder 를 차례로(첫 성공에서 멈춤), cad = [cad],
    # remesh = [remesh]. ladder 는 cad 가 맨 앞, 빼면 그 단계 끔, 중복 금지
    mode: Literal["cad", "remesh", "freeform", "auto"] = "auto"      # v0.16.3 += freeform(C2-D-26)
    ladder: list[str] = Field(default_factory=lambda: list(COMPARE_LADDER_DEFAULT), min_length=1,
                              max_length=len(COMPARE_LADDER_STAGES))
    keep_tries: bool = False   # true = 사다리 시도 폴더 try_<n>/ 모두 남김(false = 실패 시 마지막 시도만 — 진단용)
    face_fail: BeadDoeCompareFaceFailCfg = BeadDoeCompareFaceFailCfg()   # v0.16.3 C2-D-27
    occ_import_labels: int = Field(default=0, ge=0, le=1)    # v0.16.3 C2-D-31 STEP 라벨 읽기(0 = 안 읽음 — 수천 면 가져오기 시간)
    cad_relaxed: BeadDoeCompareCadRelaxedCfg = BeadDoeCompareCadRelaxedCfg()   # v0.17.4 C2-D-32
    large_faces: int = Field(default=1000, ge=0)                                 # v0.17.4 C2-D-33 대형 모델 면 수 기준
    large: BeadDoeCompareLargeCfg = BeadDoeCompareLargeCfg()
    child_margin_s: float = Field(default=30.0, ge=0)        # v0.17.4 C2-D-34 cad 자식 제한 = spawn 제한 − 이 값(≤ 10 %)
    heartbeat_s: float = Field(default=60.0, gt=0)           # v0.17.4 C2-D-39 메시 하위 프로세스 대기 중 진행 줄 간격

    @field_validator("ladder")
    @classmethod
    def _ladder(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in COMPARE_LADDER_STAGES]
        if bad or len(set(v)) != len(v) or v[0] != "cad":
            raise ValueError(f"mesh.ladder 는 {', '.join(COMPARE_LADDER_STAGES)} 중 중복 없이, cad 가 맨 앞: {v}")
        return v


class BeadDoeCompareRemeshFidelityCfg(_M):
    """v0.16.0 재메시 충실도(C2-D-13): hausdorff > warn_mm 경고, > fail_mm 실패(null = 끔), 샘플 상한(고정 간격 추출)."""

    warn_mm: float = Field(default=0.3, gt=0)
    fail_mm: float | None = Field(default=1.5, gt=0)
    samples_max: int = Field(default=200000, ge=1)
    # v0.16.1 SR-D-27: 경고 = max(warn_mm, warn_rel_cad × cad 메시 현 편차 추정) — 0 = 절대 기준만(v0.16.0). 해시 제외(경고 전용)
    warn_rel_cad: float = Field(default=2.0, ge=0, le=10)

    @model_validator(mode="after")
    def _order(self) -> "BeadDoeCompareRemeshFidelityCfg":
        if self.fail_mm is not None and self.fail_mm < self.warn_mm:
            raise ValueError(f"remesh.fidelity.fail_mm {self.fail_mm:g} 는 null 또는 warn_mm {self.warn_mm:g} 이상이어야 합니다")
        return self


class BeadDoeCompareRemeshCfg(_M):
    """v0.16.0 삼각형 재메시(C2-D-11~14, esl.doe.mesh_remesh): OCC 삼각화 → classifySurfaces(특징각) → createGeometry →
    quad 우선 재메시. algorithms = 모델 전체 재시도 순서, timeout_s null = bead_doe.mesh.timeout_s."""

    enabled: bool = True
    feature_angle_deg: float = Field(default=30.0, gt=0, lt=90)
    curve_angle_deg: float = Field(default=60.0, gt=0, le=180)      # v0.16.0 통합: 180 → 60(판 모서리 0.79 → 0.13 mm)
    linear_deflection_mm: float = Field(default=0.05, gt=0)
    angular_deflection_deg: float = Field(default=5.0, gt=0, le=180)
    merge_tol_mm: float = Field(default=0.001, gt=0)
    stl_max_tris: int = Field(default=5000000, ge=1)
    algorithms: list[int] = Field(default_factory=lambda: [6, 5, 1], min_length=1, max_length=8)
    recombine: bool = True
    keep_stl: bool = False
    timeout_s: float | None = Field(default=None, gt=0)
    fidelity: BeadDoeCompareRemeshFidelityCfg = BeadDoeCompareRemeshFidelityCfg()

    @field_validator("algorithms")
    @classmethod
    def _algs(cls, v: list[int]) -> list[int]:
        return BeadDoeCompareMeshFallbackCfg._algs(v)         # 같은 검사기(gmsh 2D 알고리즘 번호)

    @model_validator(mode="after")
    def _deflection(self) -> "BeadDoeCompareRemeshCfg":
        if self.linear_deflection_mm > self.fidelity.warn_mm:
            raise ValueError(f"remesh.linear_deflection_mm {self.linear_deflection_mm:g} 는 fidelity.warn_mm "
                             f"{self.fidelity.warn_mm:g} 이하여야 합니다")
        return self


class BeadDoeCompareMeshInputDiagCfg(_M):
    """v0.16.1 메시 입력 진단(SR-D-24 — 보고만): 구멍·섬 크기 기준 = compare.defeature.hole_max_d_mm · select.island.max_mm."""

    enabled: bool = True
    feature_angle_deg: float = Field(default=30.0, gt=0, le=90)


class BeadDoeCompareMeshInputCfg(_M):
    """v0.16.0 메시 입력(C2-D-2~8): 형상마다 사용자 메시(Radioss rad/inc). formats ⊆ COMPARE_MESH_FORMATS(Q2 로 넓힘),
    max_mb = 주 + include 합계(형상당), include 는 업로드 폴더 안만, size_warn_ratio = 모서리 중앙값 허용 배수."""

    enabled: bool = True
    formats: list[str] = Field(default_factory=lambda: list(COMPARE_MESH_FORMATS), min_length=1, max_length=8)
    max_mb: float = Field(default=500, gt=0)
    include: bool = True
    max_include_depth: int = Field(default=8, ge=0, le=64)
    size_warn_ratio: float = Field(default=1.5, gt=1)
    diag: BeadDoeCompareMeshInputDiagCfg = BeadDoeCompareMeshInputDiagCfg()     # v0.16.1 SR-D-24

    @field_validator("formats")
    @classmethod
    def _formats(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in COMPARE_MESH_FORMATS]
        if bad or len(set(v)) != len(v):
            raise ValueError(f"mesh_input.formats 는 {', '.join(COMPARE_MESH_FORMATS)} 중 중복 없이: {v}")
        return v


def _desc_factors(v: list[float], key: str) -> list[float]:
    if any(not 0 < f < 1 for f in v) or any(b >= a for a, b in zip(v, v[1:])):
        raise ValueError(f"{key} 는 (0, 1) 범위에서 내림차순: {v}")
    return v


class BeadDoeCompareRefineLocalCfg(_M):
    factors: list[float] = Field(default_factory=lambda: [0.75, 0.5, 0.33], min_length=1, max_length=10)
    neighbor_rings: int = Field(default=1, ge=0, le=10)
    max_faces: int = Field(default=20, ge=1, le=1000)

    @field_validator("factors")
    @classmethod
    def _f(cls, v: list[float]) -> list[float]:
        return _desc_factors(v, "refine.local.factors")


class BeadDoeCompareRefineGlobalCfg(_M):
    factors: list[float] = Field(default_factory=lambda: [0.8, 0.667], min_length=1, max_length=10)

    @field_validator("factors")
    @classmethod
    def _f(cls, v: list[float]) -> list[float]:
        return _desc_factors(v, "refine.global.factors")


class BeadDoeCompareRefineConvergenceCfg(_M):
    enabled: bool = True
    tol: float | None = Field(default=None, ge=0, lt=1)       # null = bead_doe.rank.ratio_tol
    same_h_baseline: bool = False


class BeadDoeCompareRefineCfg(_M):
    """v0.16.0 세분화 폴백(C2-D-18~24): refine_local(실패 면 + 이웃 고리)·refine_global(h × factor). max_elems = 세분화
    시도 요소 상한(bead_doe.mesh.max_elems 이상), total_timeout_s = 형상 1개 사다리 전체 시간 예산. ``global`` 은 파이썬
    예약어라 필드 이름 global_ (설정·dump 키는 global)."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_by_name=True, validate_by_alias=True,
                              serialize_by_alias=True)

    enabled: bool = True
    min_size_mm: float = Field(default=0.5, gt=0)
    max_elems: int = Field(default=600000, ge=1)
    total_timeout_s: float = Field(default=3600, gt=0)
    # v0.16.3 C2-D-29 단계 몫(total_timeout_s 비율 — 뒤 단계 몫은 앞 단계가 못 씀), 남은 몫 < min_attempt_s 면 시도 안 함
    stage_share: dict[str, float] = Field(default_factory=lambda: {"cad": 0.3, "refine_local": 0.1, "refine_global": 0.1,
                                                                   "freeform": 0.2, "defeature": 0.15, "remesh": 0.2,
                                                                   "tria": 0.15})
    min_attempt_s: float = Field(default=5.0, ge=0)
    elem_per_h2: float = Field(default=1.0, gt=0)
    local: BeadDoeCompareRefineLocalCfg = BeadDoeCompareRefineLocalCfg()
    global_: BeadDoeCompareRefineGlobalCfg = Field(default_factory=BeadDoeCompareRefineGlobalCfg, alias="global")
    convergence: BeadDoeCompareRefineConvergenceCfg = BeadDoeCompareRefineConvergenceCfg()

    @field_validator("stage_share")
    @classmethod
    def _share(cls, v: dict[str, float]) -> dict[str, float]:
        bad = [k for k, x in v.items() if k not in COMPARE_LADDER_STAGES or not 0 <= float(x) <= 1]
        if bad:
            raise ValueError(f"refine.stage_share 키는 사다리 단계, 값은 0..1: {bad}")
        return v


class BeadDoeCompareFreeformCfg(_M):
    """v0.16.3 freeform(C2-D-26): remesh 설정으로 이산 재메시하되 CAD 단계 구멍 메움 없이(hole_fill false). 지름 <
    small_hole_factor × h 구멍 수를 MESH_FREEFORM 경고에 적음. timeout_s null = remesh.timeout_s."""

    enabled: bool = True
    hole_fill: bool = False
    small_hole_factor: float = Field(default=1.0, gt=0, le=10)
    timeout_s: float | None = Field(default=None, gt=0)
    # v0.17.4 C2-D-42 freeform 삼각화 편차(null = remesh 값) — 각 5° 는 곡면 많은 STEP 에서 삼각형 폭증
    linear_deflection_mm: float | None = Field(default=None, gt=0)
    angular_deflection_deg: float | None = Field(default=20.0, gt=0, le=90)
    # v0.18.2 C2-D-44 이산 면 구성: occ_faces = OCC 면마다 이산 면(공유 경계 = OCC 모서리, 면 분류 없음), classify = v0.18.1
    surfaces: Literal["occ_faces", "classify"] = "occ_faces"


class BeadDoeCompareTriaCfg(_M):
    """v0.16.3 OCC 삼각형 폴백(C2-D-28, esl.doe.mesh_tria): BRepMesh 편차 = deflection_factor × h, 긴 변 > split_factor × h
    적합 분할, 짧은 변 < collapse_factor × h 평면 안 붕괴, 같은 평면(coplanar_deg) 안 Delaunay 뒤집기·접선 평활."""

    enabled: bool = True
    deflection_factor: float = Field(default=0.3, gt=0, le=1)       # 0.3 × 3 = 0.9 mm ≈ 3 mm CAD 메시 자체 현 편차
    angular_deflection_deg: float = Field(default=45.0, gt=0, le=90)
    merge_tol_mm: float = Field(default=0.01, gt=0)
    split_factor: float = Field(default=1.333, gt=1, le=4)
    max_split_iters: int = Field(default=24, ge=1, le=200)
    max_tris: int = Field(default=2000000, ge=1)
    coplanar_deg: float = Field(default=1.0, gt=0, le=30)
    flip_passes: int = Field(default=6, ge=0, le=100)
    collapse_factor: float = Field(default=0.6, ge=0, lt=1)
    collapse_passes: int = Field(default=6, ge=0, le=100)
    collapse_deg: float = Field(default=20.0, gt=0, le=60)   # 붕괴 허용 = 둘레 법선 산포 ≤ 이 값(매끈한 곡면 포함)
    smooth_rounds: int = Field(default=4, ge=0, le=100)
    smooth_iters: int = Field(default=5, ge=0, le=100)
    allow_missing_faces: bool = True
    timeout_s: float | None = Field(default=300, gt=0)


class BeadDoeCompareDefeatureCfg(_M):
    """이슈 #53 holes table 근사(메싱 전 OCC 형상): 내부 경계 면적 < min_hole_area_mm2 메움(r<4 원형·eq_diam<8·좁은 슬롯),
    반지름 hole_r_mm 구멍 둘레 분할 = max(hole_elems, ceil(둘레/h)) (0 = 끔) — cad 단계. min_bead_height_mm = bead 억제 기준
    (v0.16.1 defeature 단계에서 적용, cad 단계는 읽지 않음).

    v0.16.1 새 키(esl_select_relax.md §4.4 — ④ 사다리 defeature 단계에서만 읽음, base.json profile 해시 제외 SR-D-21b):
    kinds = 억제 종류·실행 순서(빼면 그 종류 끔), hole_max_d_mm = 등가 지름 4A/P 상한, slot_max_w_mm·slot_max_l_mm = 슬롯,
    flange_max_h_mm = 버링 높이, fillet_max_r_mm = 필렛 반경, narrow_w_factor = 좁은 띠 폭 × h, feature_max_mm = bead·flange
    bbox 대각 상한, plane_tol_mm = 둘레 평면 판정, compound = 쉘 fillet·narrow 병합 메시, region_pad_factor = 억제 영역 여유 × h,
    max_features = 인식 상한, list_max = defeature.json 행 상한."""

    enabled: bool = True
    min_hole_area_mm2: float = Field(default=50.27, ge=0)
    hole_elems: int = Field(default=6, ge=0, le=100)
    hole_r_mm: list[float] = Field(default_factory=lambda: [4.0, 30.0], min_length=2, max_length=2)
    min_bead_height_mm: float = Field(default=2.0, ge=0)
    kinds: list[Literal["flange", "hole", "slot", "bead", "fillet", "narrow"]] = Field(
        default_factory=lambda: list(DEFEATURE_KINDS), max_length=len(DEFEATURE_KINDS))
    hole_max_d_mm: float = Field(default=8.0, gt=0)
    slot_max_w_mm: float = Field(default=1.9, gt=0)
    slot_max_l_mm: float = Field(default=14.0, gt=0)
    flange_max_h_mm: float = Field(default=1.5, gt=0)
    fillet_max_r_mm: float = Field(default=1.5, gt=0)          # Q5 A
    narrow_w_factor: float = Field(default=0.4, gt=0, le=1)
    feature_max_mm: float = Field(default=40.0, gt=0)
    plane_tol_mm: float = Field(default=0.01, gt=0)
    compound: bool = True
    region_pad_factor: float = Field(default=1.0, ge=0)
    max_features: int = Field(default=2000, ge=1)
    list_max: int = Field(default=500, ge=1)

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError(f"defeature.kinds 는 {', '.join(DEFEATURE_KINDS)} 중 중복 없이: {v}")
        return v


class QualityLimitCfg(_M):
    warn: float
    fail: float


def _ql(w: float, f: float):
    return Field(default_factory=lambda: QualityLimitCfg(warn=w, fail=f))


class BeadDoeCompareQualityCfg(_M):
    """이슈 #53 2D criteria 표(esl.doe.mesh_quality): 기준별 warn·fail. Fail 요소 비율 > max_fail_ratio → 경고(차단 안 함)."""

    max_fail_ratio: float = Field(default=0.01, ge=0, le=1)
    min_length: QualityLimitCfg = _ql(1.8, 1.2)
    max_length: QualityLimitCfg = _ql(4.5, 5.25)
    aspect: QualityLimitCfg = _ql(4.4, 5.0)
    warpage: QualityLimitCfg = _ql(13.0, 15.0)
    skew: QualityLimitCfg = _ql(34.0, 40.0)
    jacobian: QualityLimitCfg = _ql(0.7, 0.6)
    quad_min_angle: QualityLimitCfg = _ql(46.0, 40.0)
    quad_max_angle: QualityLimitCfg = _ql(134.0, 140.0)
    tria_min_angle: QualityLimitCfg = _ql(34.0, 30.0)
    tria_max_angle: QualityLimitCfg = _ql(112.0, 120.0)
    tria_pct: QualityLimitCfg = _ql(10.0, 15.0)


LT_CELL_MAX_MM = 200.0                      # v0.20.0 LT 셀 크기 상한(계약 esl_load_transfer.md §4.1·§13.6) — 요청 검사(서비스)도 이 값
LT_LIST_MAX = 8                             # cell_choices_mm·cell_sweep_mm 길이 상한


class BeadDoeLoadTransferWorkCfg(_M):
    """v0.20.0 방식 W(일 등가) 사영(LT-2·5): 후보 요소 kNN·Newton 역사상 횟수·먼 노드 허용 거리와 경고·실패 비율."""

    knn: int = Field(default=8, ge=1, le=64)
    proj_tol_mm: float | None = Field(default=3.0, gt=0)          # null = 1.0 × h
    newton_iter: int = Field(default=10, ge=1, le=50)
    far_warn_frac: float = Field(default=0.01, ge=0, le=1)
    far_fail_frac: float = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def _order(self) -> "BeadDoeLoadTransferWorkCfg":
        if not self.far_warn_frac <= self.far_fail_frac:
            raise ValueError(f"load_transfer.work.far_warn_frac {self.far_warn_frac:g} ≤ far_fail_frac "
                             f"{self.far_fail_frac:g} 이어야 합니다")
        return self


def _lt_cells(name: str, v: list[float | None], cell_min: float, *, min_len: int) -> None:
    if not min_len <= len(v) <= LT_LIST_MAX:
        raise ValueError(f"load_transfer.{name} 길이는 {min_len}..{LT_LIST_MAX}: {len(v)}")
    if len(set(v)) != len(v):
        raise ValueError(f"load_transfer.{name} 에 중복이 있습니다: {v}")
    for x in v:
        if x is not None and not cell_min <= x <= LT_CELL_MAX_MM:
            raise ValueError(f"load_transfer.{name} 원소는 null 또는 cell_min_mm {cell_min:g}..{LT_CELL_MAX_MM:g}: {x:g}")


class BeadDoeLoadTransferDiagCfg(_M):
    """v0.20.0 하중 전달 진단(LT-10·20): 다른 방식 점수(alt)·베이스라인 셀 크기 훑기. 해시 밖(진단 설정만 바꿔도 주 결과 재사용).
    alt_designs = 안마다 다른 방식 점수(score_alt): auto = 계획 표 열(④ 켬, ①②③ 끔) | on | off."""

    enabled: bool = True
    alt: bool = True
    alt_cell_size_mm: float | None = Field(default=3.0, gt=0)      # 주 방식 work 일 때 alt cell 의 셀 크기(null = 기존 격자)
    alt_designs: Literal["auto", "on", "off"] = "auto"
    cell_sweep_mm: list[float | None] = Field(default_factory=lambda: [None, 10.0, 5.0, 3.0])   # 0 개 = 훑기 끔


class BeadDoeLoadTransferCfg(_M):
    """v0.20.0 하중 전달 — 강성 평가 모든 모드(①②③④) 공통(계약 esl_load_transfer.md §13.6). 새 스터디 기본 = 일 등가(사용자 확정
    2026-11-13). 요청으로는 method·cell_size_mm 만 덮어씀. 옛 스터디(스냅샷에 키 없음)는 이 설정과 무관(legacy)."""

    method: Literal["work", "cell"] = "work"
    cell_size_mm: float | None = Field(default=None, gt=0)          # null = 기존 ESL 요약 24×14 격자
    cell_choices_mm: list[float | None] = Field(default_factory=lambda: [None, 10.0, 5.0, 3.0])
    cell_min_mm: float = Field(default=3.0, ge=1, le=LT_CELL_MAX_MM)
    work: BeadDoeLoadTransferWorkCfg = BeadDoeLoadTransferWorkCfg()
    diag: BeadDoeLoadTransferDiagCfg = BeadDoeLoadTransferDiagCfg()

    @model_validator(mode="after")
    def _cells(self) -> "BeadDoeLoadTransferCfg":
        m = self.cell_min_mm
        _lt_cells("cell_choices_mm", self.cell_choices_mm, m, min_len=1)
        _lt_cells("diag.cell_sweep_mm", self.diag.cell_sweep_mm, m, min_len=0)
        for name, x in (("cell_size_mm", self.cell_size_mm), ("diag.alt_cell_size_mm", self.diag.alt_cell_size_mm)):
            if x is not None and not m <= x <= LT_CELL_MAX_MM:
                raise ValueError(f"load_transfer.{name} 은 null 또는 cell_min_mm {m:g}..{LT_CELL_MAX_MM:g}: {x:g}")
        return self


class BeadDoeCompareLoadTransferRegionCfg(_M):
    """v0.20.0 ④ 평가 영역(LT-8, ③ SG-D-19 와 같은 값·뜻)."""

    mode: Literal["auto", "a_bbox", "largest", "all"] = "auto"
    pad_mm: float | None = Field(default=None, gt=0)
    min_frac: float = Field(default=0.5, gt=0, le=1)


class BeadDoeCompareLoadTransferCfg(_M):
    """v0.20.0 ④ 전용(§13.6): 지지 이전(LT-7)·평가 영역(LT-8). 방식·셀·진단은 최상위 bead_doe.load_transfer."""

    support: Literal["transfer", "auto"] = "transfer"
    support_tol_mm: float | None = Field(default=None, gt=0)       # null = 2h
    region: BeadDoeCompareLoadTransferRegionCfg = BeadDoeCompareLoadTransferRegionCfg()


class BeadDoeCompareCfg(_M):
    """v0.14.0 ④ 형상 직접 비교(esl_step_compare.md §4). 섹션 없으면 기본값(enabled true — 전역 bead_doe.enabled·gmsh 필요)."""

    enabled: bool = True
    max_shapes: int = Field(default=20, ge=1, le=200)
    total_max_mb: float = Field(default=1000, gt=0)
    align_tol: float = Field(default=0.05, ge=0, le=1)        # 형상 frame 원점의 기준 frame (ξ,η) 차 허용
    align_deg: float = Field(default=5.0, ge=0, le=90)        # 법선 각 허용(°)
    min_ready_shapes: int = Field(default=1, ge=0, le=1000)   # v0.17.4 C2-D-41 비교 형상 READY 가 이보다 적으면 BD_MESH0 실패
    mesh: BeadDoeCompareMeshCfg = BeadDoeCompareMeshCfg()
    defeature: BeadDoeCompareDefeatureCfg = BeadDoeCompareDefeatureCfg()
    quality: BeadDoeCompareQualityCfg = BeadDoeCompareQualityCfg()
    remesh: BeadDoeCompareRemeshCfg = BeadDoeCompareRemeshCfg()               # v0.16.0 C2-D-11~14
    mesh_input: BeadDoeCompareMeshInputCfg = BeadDoeCompareMeshInputCfg()     # v0.16.0 C2-D-2~8
    refine: BeadDoeCompareRefineCfg = BeadDoeCompareRefineCfg()               # v0.16.0 C2-D-18~24
    freeform: BeadDoeCompareFreeformCfg = BeadDoeCompareFreeformCfg()         # v0.16.3 C2-D-26
    tria: BeadDoeCompareTriaCfg = BeadDoeCompareTriaCfg()                     # v0.16.3 C2-D-28
    load_transfer: BeadDoeCompareLoadTransferCfg = BeadDoeCompareLoadTransferCfg()   # v0.20.0 ④ 전용 support·region(LT-7·8)


class BeadDoeSelectWidthCfg(_M):
    floor_follow: Literal[0, 1] = 1                          # Q1 A: 폭 변경 시 바닥도 따라감(사면 각 유지)
    knn: int = Field(default=8, ge=1, le=64)                 # 경계 변위장 가중 평균 이웃 수(§5.4)
    end_ratio: float = Field(default=2.0, gt=1.0, le=100.0)  # §5.7 끝단 반직선 제외(국부 폭 중앙값 배수, 코어 WIDTH_END_RATIO)


class BeadDoeSelectBlendCfg(_M):
    min_mm: float = Field(default=15.0, gt=0)
    max_mm: float = Field(default=200.0, gt=0)
    k: float = Field(default=8.0, gt=0)                      # R 자동 = k × 최대 한쪽 이동(§5.6)
    fixed_margin_mm: float = Field(default=3.0, ge=0)

    @model_validator(mode="after")
    def _order(self) -> "BeadDoeSelectBlendCfg":
        if not self.min_mm <= self.max_mm:
            raise ValueError(f"bead_doe.select.blend.min_mm {self.min_mm:g} ≤ max_mm {self.max_mm:g} 이어야 합니다")
        return self


class BeadDoeSelectRangeCfg(_M):
    """기본 범위 = 공칭 × (1 ± *_rel)(v0.16.0 그대로 — R_auto 기준), v0.16.1 feasible 상한 = 공칭 × (1 + *_max_rel)(SR-D-10)."""

    depth_rel: float = Field(default=0.3, gt=0, lt=1)
    width_rel: float = Field(default=0.2, gt=0, lt=1)
    min_step_mm: float = Field(default=1.0, ge=0)
    depth_max_rel: float = Field(default=1.0, gt=0, le=5)
    width_max_rel: float = Field(default=0.6, gt=0, le=5)
    # v0.16.1 SR-D-32: W 하한 > 공칭이면 바닥 최소 폭을 국부 폭 이 분위값으로 다시(극단값 오탐 회피)
    width_floor_q: float = Field(default=0.25, gt=0, lt=1)
    # v0.16.1 SR-D-33: 기본 범위 끝 뒤집힘 점검 이분 횟수(BD_MATRIX — SELECT_RANGE_INVERTS{usable}), 0 = 끔
    check_steps: int = Field(default=5, ge=0, le=20)
    # v0.16.1 SR-D-39: usable 끝 모서리 조합 표본 수(SELECT_RANGE_COMBO), 0 = 끔
    combo_samples: int = Field(default=16, ge=0, le=1024)

    @model_validator(mode="after")
    def _max_rel(self) -> "BeadDoeSelectRangeCfg":
        for k in ("depth", "width"):
            lo, hi = getattr(self, f"{k}_rel"), getattr(self, f"{k}_max_rel")
            if hi < lo:
                raise ValueError(f"bead_doe.select.range.{k}_max_rel {hi:g} 는 {k}_rel {lo:g} 이상이어야 합니다")
        return self


class BeadDoeSelectQualityCfg(_M):
    """기준값은 bead_doe.compare.quality 한 곳(복제 없음) — 여기는 차단 비율·뒤집힘 각만(BS-D-12). v0.16.1 fail_policy:
    warn = 새 Fail 비율 초과 안도 실행(경고 SELECT_QUALITY_WARN), skip = v0.16.0 대로 제외(뒤집힘은 정책과 무관하게 제외, SR-D-1·2)."""

    max_fail_ratio: float = Field(default=0.01, ge=0, le=1)
    flip_deg: float = Field(default=60.0, gt=0, le=180)
    fail_policy: Literal["warn", "skip"] = "warn"
    # v0.16.1 SR-D-40 요소별 극단값 → SELECT_QUALITY_WARN(warn 정책만, 0 = 그 조건 끔)
    rot_warn_deg: float = Field(default=45.0, ge=0, le=180)
    area_ratio_min: float = Field(default=0.2, ge=0, lt=1)
    # v0.16.1 SR-D-37 비드 안 비선택 피처 왜곡 → FAILED_MESH(SELECT_FEATURE_DISTORTED)
    distort_rel: float = Field(default=0.25, gt=0, le=10)
    distort_min_mm: float = Field(default=0.1, ge=0)


class BeadDoeSelectIslandCfg(_M):
    """v0.16.1 섬(딤플·버링) 평면 bbox 대각 상한(§5.2) — 넘으면 섬 아님(SELECT_ISLAND_TOO_LARGE). ring_frac(SR-D-26) = 주인 바닥에서
    판 쪽으로 ≥ ring_frac·D 솟은 둘러싸인 성분은 고리형 비드 안쪽 둔덕(섬 아님, SELECT_INNER_LOOP 정보)."""

    max_mm: float = Field(default=40.0, gt=0)
    ring_frac: float = Field(default=0.9, gt=0)


class BeadDoeSelectHoldCfg(_M):
    """v0.16.1 비드별 '체결 구멍 둘레 고정'(hold_fixed, SR-D-9 — Q2 A): 고정 노드에서 ring_mm 안 제자리, blend_mm 블렌딩(보스)."""

    ring_mm: float = Field(default=3.0, ge=0)
    blend_mm: float = Field(default=8.0, gt=0)


class BeadDoeSelectHoleCfg(_M):
    """v0.16.2 구멍 건너 잇기 상한(esl_bead_auto.md AD-D-7): 등가 지름 > bridge_max_mm 인 구멍은 건너 잇지 않음
    (SELECT_BRIDGE_SKIPPED). 코어 HASH_NEW_KEYS_V0162 — 기본값이면 select 해시에서 빠짐."""

    bridge_max_mm: float = Field(default=20.0, gt=0)


class BeadDoeSelectAutoCfg(_M):
    """v0.16.2 자동 탐지 seed(AD-D-12): paicad 사면 폭이 유도 사면과 slope_diff_rel 넘게 다르면 info AUTO_SLOPE_DIFF(보고만 —
    해시 제외)."""

    slope_diff_rel: float = Field(default=0.2, ge=0, le=10)


class BeadDoeSelectGraphIslandCfg(_M):
    """v0.17.0 BEADGRAPH 섬(esl_beadgraph.md BG-D-9·D8): PCA 장축 ≤ max_mm 인 부분 트리 = 섬(강체). 그래프 경로·schema 2 elems 비드만 —
    schema 1 은 select.island.max_mm(40) 그대로(O-BG-1)."""

    max_mm: float = Field(default=60.0, gt=0)
    straddle_frac: float = Field(default=0.15, gt=0, lt=1)


class BeadDoeSelectGraphBeadCfg(_M):
    """v0.17.0 세그먼트 골격(BG-D-11·13): 비드형 바닥 폭 상한, 가지치기, 접합 판정(L·W), 짧은 구간·띠 흡수."""

    max_width_mm: float = Field(default=80.0, gt=0)
    prune_k: float = Field(default=2.2, gt=0)
    bend_deg: float = Field(default=50.0, gt=0, lt=180)
    width_jump: float = Field(default=0.35, gt=0)
    min_zone_mm: float = Field(default=12.0, ge=0)
    open_ext_mm: float = Field(default=90.0, ge=0)
    absorb_len_mm: float = Field(default=60.0, ge=0)


class BeadDoeSelectGraphCornerCfg(_M):
    """v0.17.0 코너 가드(BG-D-26): 평면 넓이 비 < area_ratio_min 이면 움직이는 노드 평면 성분 × shrink 를 ≤ iters 회."""

    area_ratio_min: float = Field(default=0.35, gt=0, lt=1)
    shrink: float = Field(default=0.8, gt=0, lt=1)
    iters: int = Field(default=40, ge=1, le=200)


class BeadDoeSelectGraphMorphCfg(_M):
    """v0.17.0 세그먼트 모핑(BG-D-24·33·34): 램프 L = max(ramp_k·ΔD_ext, ramp_k·h), 바깥 이동·달성 깊이 허용차,
    W 바깥 방향장 완화 반복 w_smooth_iters(통합 v0.17.0 — 코어 구현 키 거울)."""

    ramp_k: float = Field(default=3.0, ge=1)
    outside_tol_mm: float = Field(default=1.0e-6, gt=0, le=1e-3)
    achieved_tol_mm: float = Field(default=1.0e-6, gt=0)
    corner: BeadDoeSelectGraphCornerCfg = BeadDoeSelectGraphCornerCfg()
    w_smooth_iters: int = Field(default=3, ge=0, le=200)            # W 바깥 방향장 완화 반복(꺾임·연결부 연속, 0 = 끔) — 코어 구현 키


class BeadDoeSelectGraphLimitsCfg(_M):
    """v0.17.0 분류 상한(§7): 요소 수 초과 = GRAPH_FAILED{TOO_LARGE}, 시간 초과 = GRAPH_FAILED{TIMEOUT}, 래스터 픽셀 상한."""

    max_elems: int = Field(default=600000, ge=1, le=2_000_000)
    timeout_s: float = Field(default=180, gt=0)
    max_raster_px: int = Field(default=4_000_000, ge=100_000)


class BeadDoeSelectGraphCfg(_M):
    """v0.17.0 BEADGRAPH(esl_beadgraph.md §5.5): 메시 비드 네트워크 분류기·세그먼트 모핑 — esl.doe.DEFAULTS["select"]["graph"]·
    beadgraph.DEFAULTS 거울. 코어 HASH_NEW_KEYS_V0170 — 기본값이면 select 해시에서 빠짐(BG-D-41). enabled false = 새 스터디도 schema
    2 이지만 그래프 계산 안 함(GRAPH_FAILED{code: DISABLED}, elems 비드만)."""

    enabled: bool = True
    feature_angle_deg: float = Field(default=10.0, gt=0, le=45)     # BG-D-2(#53 param feature_angle) — select.feature_angle_deg 와 별개
    level_tol_mm: float = Field(default=0.3, gt=0)
    min_floor_area_mm2: float = Field(default=12.0, ge=0)
    root_free_frac: float = Field(default=0.2, ge=0, le=1)
    raster_mm: float = Field(default=1.0, gt=0)
    island: BeadDoeSelectGraphIslandCfg = BeadDoeSelectGraphIslandCfg()
    bead: BeadDoeSelectGraphBeadCfg = BeadDoeSelectGraphBeadCfg()
    morph: BeadDoeSelectGraphMorphCfg = BeadDoeSelectGraphMorphCfg()
    sym_tol_mm: float = Field(default=0.5, gt=0)                    # BG-D-17·21
    limits: BeadDoeSelectGraphLimitsCfg = BeadDoeSelectGraphLimitsCfg()


class BeadDoeSelectStepGraphFixedTransferCfg(_M):
    """v0.18.0 STEP_GRAPH 고정점 이전(esl_step_graph.md SG-D-13 개정 2026-11-12·15): 구멍 특징 frame 판정(A 구멍 ↔ B 구멍
    대응 ≥ max(frame_min_holes, A 구멍 50 %) within frame_match_mm(null = 2h), 잔차 중앙값 ≤ frame_resid_mm(null = h/4),
    1개 제외 최대 ≤ h/2) = xyz_nearest, 강체 맞춤 뒤 같은 기준 = xyz_fitted(≤ tol_mm, null = 기준 메시 h, 클러스터마다 검증),
    아니면 ab_hole_snap(≤ snap_mm, null = boundary.fastener_warn_mm), 둘 다 0 = none.
    mode auto(xyz → hole → none) | xyz | hole 강제. enabled false = 파일 없음 + FIXED_XFER_NONE{DISABLED}."""

    enabled: bool = True
    mode: Literal["auto", "xyz", "hole"] = "auto"
    frame_min_holes: int = Field(default=5, ge=1, le=10_000)
    frame_match_mm: float | None = Field(default=None, gt=0)
    frame_resid_mm: float | None = Field(default=None, gt=0)
    tol_mm: float | None = Field(default=None, gt=0)
    snap_mm: float | None = Field(default=None, gt=0)


class BeadDoeSelectStepGraphRegionCfg(_M):
    """v0.18.0 평가 영역(SG-D-19·20): auto(A part bbox 겹침 최대 성분, A 없으면 최대 연결 성분) | a_bbox | largest | all(제한
    없음). pad_mm null = 2h, 영역 비율 < min_frac = 경고 STEP_GRAPH_REGION_SMALL."""

    mode: Literal["auto", "a_bbox", "largest", "all"] = "auto"
    pad_mm: float | None = Field(default=None, gt=0)
    min_frac: float = Field(default=0.5, gt=0, le=1)


class BeadDoeSelectStepGraphCfg(_M):
    """v0.18.0 STEP_GRAPH(esl_step_graph.md §4.3): select_base step 스터디만 읽음 — esl.doe.DEFAULTS["select"]["step_graph"] 거울.
    코어 HASH_NEW_KEYS_V0180 — step 기준 스터디에서 기본값이 아닐 때만 select 해시에 들어감(V-SG-10). 분류 상한 = max(graph.limits,
    이 값), tria 로 끝난 사다리 메시 = 경고(warn) | 준비 실패 STEP_GRAPH_TRIA_BLOCKED(block)."""

    max_elems: int = Field(default=600000, ge=1, le=2_000_000)
    timeout_s: float = Field(default=300, gt=0)
    tria_warn_frac: float = Field(default=0.5, gt=0, le=1)
    tria_policy: Literal["warn", "block"] = "warn"
    fixed_transfer: BeadDoeSelectStepGraphFixedTransferCfg = BeadDoeSelectStepGraphFixedTransferCfg()
    region: BeadDoeSelectStepGraphRegionCfg = BeadDoeSelectStepGraphRegionCfg()


class BeadDoeSelectThumbCfg(_M):
    w: int = Field(default=320, ge=16, le=4096)
    h: int = Field(default=240, ge=16, le=4096)
    supersample: int = Field(default=2, ge=1, le=4)
    view: Literal["auto"] | list[float] = "auto"
    tilt_deg: float = Field(default=25.0, ge=-89, le=89)
    margin: float = Field(default=1.15, ge=1, le=5)
    ambient: float = Field(default=0.35, ge=0, le=1)


class BeadDoeSelectCfg(_M):
    """v0.15.0 select — 비드 직접 선택·규칙 모핑(esl_bead_select.md §10, esl.doe.DEFAULTS["select"] 거울). 섹션 없으면 기본값
    (enabled true — 전역 bead_doe.enabled 필요, paicad 무관 BS-D-2)."""

    enabled: bool = True
    feature_angle_deg: float = Field(default=15.0, ge=1, le=45)
    max_beads: int = Field(default=20, ge=1, le=99)            # 비드 id ^b[1-9][0-9]?$
    max_tiers: int = Field(default=6, ge=1, le=9)
    max_selection_kb: float = Field(default=4096, gt=0)
    normal_radius_mm: float = Field(default=10.0, gt=0)
    plane_rms_mm: float = Field(default=2.0, gt=0)
    plate_tol_mm: float = Field(default=1.0, gt=0)
    level_eps_mm: float = Field(default=0.5, gt=0)
    slope_max_mm: float = Field(default=80.0, gt=0)
    fixed_tol_mm: float = Field(default=0.01, ge=0)
    width: BeadDoeSelectWidthCfg = BeadDoeSelectWidthCfg()
    blend: BeadDoeSelectBlendCfg = BeadDoeSelectBlendCfg()
    range: BeadDoeSelectRangeCfg = BeadDoeSelectRangeCfg()
    quality: BeadDoeSelectQualityCfg = BeadDoeSelectQualityCfg()
    thumb: BeadDoeSelectThumbCfg = BeadDoeSelectThumbCfg()
    # v0.16.1(esl_select_relax.md SR-D-2·§5.2·SR-D-9): 고정 침범 = warn(경고만 — 실행) | skip(v0.16.0 대로 제외), 섬, 보스
    fixed_policy: Literal["warn", "skip"] = "warn"
    # v0.16.1 SR-D-38 다른 선택 비드 침범(W 변화가 다른 비드 경계·바닥을 움직임): warn = 경고만 | skip = 안 제외(SKIPPED_COLLISION)
    cross_bead_policy: Literal["warn", "skip"] = "warn"
    cross_bead_tol_mm: float = Field(default=0.1, ge=0)
    island: BeadDoeSelectIslandCfg = BeadDoeSelectIslandCfg()
    hold: BeadDoeSelectHoldCfg = BeadDoeSelectHoldCfg()
    hole: BeadDoeSelectHoleCfg = BeadDoeSelectHoleCfg()        # v0.16.2 AD-D-7 구멍 건너 잇기 상한
    auto: BeadDoeSelectAutoCfg = BeadDoeSelectAutoCfg()        # v0.16.2 AD-D-12 자동 탐지 사면 힌트 기준
    graph: BeadDoeSelectGraphCfg = BeadDoeSelectGraphCfg()     # v0.17.0 BEADGRAPH 분류기·세그먼트 모핑(esl_beadgraph.md §5.5)
    step_graph: BeadDoeSelectStepGraphCfg = BeadDoeSelectStepGraphCfg()     # v0.18.0 ③ select_base step(esl_step_graph.md §4.3)
    derive_cache_n: int = Field(default=8, ge=0, le=1000)      # 백엔드 derive 결과 LRU(키 = 선택 sha256), 0 = 끔
    derive_timeout_s: float = Field(default=20, gt=0, le=600)


class BeadDoeCfg(_M):
    """비드 형상 DOE(esl_bead_doe.md §14). 섹션이 없으면 enabled false(GET /doe/settings reason DOE_DISABLED)."""

    enabled: bool = False
    part_title: str = Field(default="chassis rear", min_length=1, max_length=200)
    max_entries: int = Field(default=50, ge=1, le=10000)
    max_designs: int = Field(default=200, ge=3, le=10000)
    step_max_mb: float = Field(default=200, gt=0)
    same: BeadDoeSameCfg = BeadDoeSameCfg()
    fixed_scan: BeadDoeFixedScanCfg = BeadDoeFixedScanCfg()
    paicad: BeadDoePaicadCfg = BeadDoePaicadCfg()
    mesh: BeadDoeMeshCfg = BeadDoeMeshCfg()
    doe: BeadDoeDoeCfg = BeadDoeDoeCfg()
    preview: BeadDoePreviewCfg = BeadDoePreviewCfg()
    grid: BeadDoeGridCfg = BeadDoeGridCfg()                  # v0.17.2 미리보기 grid 건강(이슈 #63)
    run: BeadDoeRunCfg = BeadDoeRunCfg()
    solve: BeadDoeSolveCfg = BeadDoeSolveCfg()
    boundary: BeadDoeBoundaryCfg = BeadDoeBoundaryCfg()
    view3d: BeadDoeView3dCfg = BeadDoeView3dCfg()
    rank: BeadDoeRankCfg = BeadDoeRankCfg()
    settings_cache_s: float = Field(default=300, ge=0)
    compare: BeadDoeCompareCfg = BeadDoeCompareCfg()
    load_transfer: BeadDoeLoadTransferCfg = BeadDoeLoadTransferCfg()   # v0.20.0 모든 모드 공통(esl_load_transfer.md §13.6)
    select: BeadDoeSelectCfg = BeadDoeSelectCfg()            # v0.15.0 select(esl_bead_select.md §10)
    limits: BeadDoeLimitsCfg = BeadDoeLimitsCfg()

    @model_validator(mode="after")
    def _compare_size(self) -> "BeadDoeCfg":
        h = self.compare.mesh.size_mm
        if not self.mesh.size_min_mm <= h <= self.mesh.size_max_mm:
            raise ValueError(f"bead_doe.compare.mesh.size_mm {h:g} 는 bead_doe.mesh.size_min_mm..size_max_mm "
                             f"({self.mesh.size_min_mm:g}..{self.mesh.size_max_mm:g}) 안이어야 합니다")
        rf = self.compare.refine
        if rf.max_elems < self.mesh.max_elems:          # C2-D-21: 세분화 상한은 cad 시도 상한 이상
            raise ValueError(f"bead_doe.compare.refine.max_elems {rf.max_elems} 는 bead_doe.mesh.max_elems "
                             f"{self.mesh.max_elems} 이상이어야 합니다")
        return self


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
    secret_file: str = ""                                # 절대경로(대시보드 SIMDASH_SCX_RELAY_SECRET_FILE 과 같은 파일). "" = 대시보드 따라가기:
                                                         # env SIMDASH_SCX_RELAY_SECRET_FILE → dashboard_root 의 .env → <런타임>/secrets/scx_relay_key
    dashboard_root: str = ""                             # v0.12.0 대시보드 설치 폴더 절대경로(secret_file "" 일 때 .env 에서 비밀 파일 경로만 읽음)
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
    same_tol: float = Field(default=0.02, ge=0.0, le=1.0)    # 비 판단 '비슷' 허용치
    hot_n: int = Field(default=20, ge=1, le=100000)          # eps_hot 원 낙하 상위 요소 수


class VerifyDropCfg(_M):
    """기능 B — Radioss 검증 낙하(v0.12.0, esl_scx_relay.md §6)."""

    enabled: bool = False
    max_scenes: int = Field(default=5, ge=1, le=100)         # 한 요청의 씬(=제출) 수 상한(Q4)
    default_worst_n: int = Field(default=3, ge=1, le=100)    # '가장 나쁜 씬 N개' 기본 N
    max_running: int = Field(default=2, ge=1, le=64)         # 동시에 실행 중인 VERIFY_DROP 수(claim 조건)
    est_hours_per_scene: float = Field(default=3, ge=0)
    poll_s: float = Field(default=60, gt=0, le=3600)
    max_wait_h: float = Field(default=72, gt=0, le=24 * 30)
    lost_after_polls: int = Field(default=10, ge=1, le=10000)
    engine_globs: list[str] = Field(default_factory=lambda: ["{stem}_0001.rad", "{stem}_000[2-9].rad"])
    result_globs: dict[str, list[str]] = Field(default_factory=lambda: {"h3d": ["*.h3d"],
                                                                        "out": ["*_0000.out", "*_0001.out"]})
    out_ok_patterns: list[str] = Field(default_factory=lambda: ["NORMAL TERMINATION"])
    out_error_patterns: list[str] = Field(default_factory=lambda: [r"(?m)^\s*ERROR TERMINATION", r"(?i)\*\*\s*ERROR"])
    max_result_bytes: int = 64 * 1024 ** 3
    compare: VerifyDropCompareCfg = VerifyDropCompareCfg()


class ItemDeleteCfg(_M):
    """v0.19.0 목록 항목 삭제(esl_item_delete.md §11). 기본값 단일 출처 = core/trash.DEFAULTS(시험 test_item_delete 가 확인)."""

    enabled: bool = True                                       # false → DELETE·delete-check 503 ITEM_DELETE_DISABLED, can_delete 항상 false
    purge_interval_s: float = Field(default=60, gt=0, le=86400)   # 워커 리퍼(휴지통 영구 삭제) 주기
    purge_batch: int = Field(default=20, ge=1, le=10000)        # 한 주기 최대 휴지통 항목 수
    purge_max_attempts: int = Field(default=20, ge=1, le=10000)   # 영구 삭제 재시도 상한(넘으면 중지 + check WARN)
    summary_job_ids_max: int = Field(default=50, ge=0, le=100000)   # deletions.summary.job_ids 최대 개수


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
    verify_drop: VerifyDropCfg = VerifyDropCfg()            # v0.12.0 기능 B — Radioss 검증 낙하
    item_delete: ItemDeleteCfg = ItemDeleteCfg()            # v0.19.0 목록 항목 삭제(섹션 없으면 기본값)

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
    warnings: list[Issue] = field(default_factory=list)  # 기동·검증은 통과하나 알릴 것(예 hpc 밑에 들여쓴 최상위 키)

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


def overlaps_real(a: str, b: str) -> bool:
    """문자열 겹침 또는 realpath(심링크·junction 해석) 끼리 겹침 — 보호 루트가 링크로 작업 폴더를 가리키는 경우까지."""
    return overlaps(a, b) or overlaps(os.path.realpath(a), os.path.realpath(b))


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
        d = _doe_settings(None)
    else:
        d = _doe_settings({"bead_doe": s.bead_doe.model_dump()})
    # v0.15.0 select·v0.16.0 ④ 메시 옵션·v0.16.1 select 정책·섬·보스·defeature 단계·메시 입력 진단: 코어 DEFAULTS 에 아직 없는
    # 키(코어 병합 전)도 pydantic 기본값(거울)으로 채운다 — 있는 키는 그대로(덮어쓰지 않음)
    _fill_missing(d.setdefault("select", {}), BeadDoeSelectCfg().model_dump())
    _fill_missing(d.setdefault("compare", {}), BeadDoeCompareCfg().model_dump())
    _fill_missing(d.setdefault("load_transfer", {}), BeadDoeLoadTransferCfg().model_dump())
    _fill_missing(d.setdefault("rank", {}), BeadDoeRankCfg().model_dump())     # v0.20.0 SM 강성 지표 키(코어 병합 전에도)
    return d


def _fill_missing(d: dict[str, Any], defaults: dict[str, Any]) -> None:
    """defaults 의 키 중 d 에 없는 것만 깊은 사본으로 넣는다(중첩 dict 는 재귀, 값이 있는 키는 그대로)."""
    for k, v in defaults.items():
        if k not in d:
            d[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(d[k], dict):
            _fill_missing(d[k], v)


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
            if overlaps_real(st.upload_root, st.esl_root):
                issues.append(Issue("storage.upload_root", "esl_root 와 겹칩니다"))
            for r in st.spdm_roots:
                if overlaps_real(st.upload_root, r):
                    issues.append(Issue("storage.upload_root", f"SPDM 루트({r})와 겹칩니다"))
        for i, r in enumerate(st.input_roots):
            if overlaps_real(r, st.esl_root):
                issues.append(Issue(f"storage.input_roots[{i}]", "esl_root 와 겹칩니다"))
        for i, r in enumerate(st.spdm_roots):
            if overlaps_real(r, st.esl_root):
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


def misplaced_top_keys(d: Any) -> list[Issue]:
    """`hpc`(extra ignore) 밑 또는 `hpc.scx` 밑에 esl 최상위 키(Settings 필드명: scx_drive·verify_drop·bead_doe·opt_run·
    worker·storage …)를 들여쓴 경우 — pydantic 은 조용히 무시하므로 경고로 알린다. physicsai 공용 키(mode·command 등)는 계속 무시."""
    out: list[Issue] = []
    if not isinstance(d, dict) or not isinstance(d.get("hpc"), dict):
        return out
    top = set(Settings.model_fields) - {"hpc"}
    hpc = d["hpc"]
    for k in hpc:
        if k in top:
            out.append(Issue(f"hpc.{k}", f"hpc.{k} 는 최상위 키입니다 — 들여쓰기를 없애세요(지금은 무시됨)"))
    scx = hpc.get("scx")
    if isinstance(scx, dict):
        for k in scx:
            if k in top and k not in HpcScxCfg.model_fields:
                out.append(Issue(f"hpc.scx.{k}", f"hpc.scx.{k} 는 최상위 키입니다 — 들여쓰기를 없애세요(지금은 무시됨)"))
    return out


def load_config_dict(d: dict[str, Any], *, environ: dict[str, str] | None = None, base_dir: str | None = None,
                     path: str | None = None, sha256: str | None = None) -> LoadedConfig:
    env = os.environ if environ is None else environ
    d = copy.deepcopy(d)
    prof = env.get(ENV_PROFILE)
    if prof and isinstance(d, dict):
        d["profile"] = prof
    s, issues, core = validate_settings(d, base_dir=base_dir)
    lib_issues, lib = validate_library(s, base_dir=base_dir)
    warns = misplaced_top_keys(d)
    if s is not None and s.verify_drop.enabled and s.hpc is not None and s.hpc.scx is not None \
            and str(s.hpc.scx.drive_base or "").strip().rstrip("/") == "~":
        warns.append(Issue("hpc.scx.drive_base", 'verify_drop.enabled 인데 hpc.scx.drive_base 가 "~"(공유 홈) — 검증 낙하는 전용 폴더가 '
                                                 '필요합니다: hpc.scx.drive_base 를 "~/<전용 폴더>" 로(VD_DRIVE_BASE_SHARED, 검증 낙하만 비활성)'))
    return LoadedConfig(s, issues + lib_issues, path, sha256, core, lib, warns)


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
