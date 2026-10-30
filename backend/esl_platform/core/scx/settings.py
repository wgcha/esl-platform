"""SCX 설정 변환·검사(계약 esl_scx_relay.md §6·SR-D-4). 값이 틀려도 기동은 하고 SCX 기능만 비활성(사유 SCX_CONFIG_INVALID).

- `adapter_mapping(cfg)`: `hpc.scx`(HpcScxCfg) → 어댑터 `ScxConfig.from_mapping` 인자. appliance 가 비었으면 A 는 쓸 수 있게
  자리표시 값을 넣고(어댑터 검사는 appliance 필수) `appliance_set=False` 로 B 비활성 사유(SCX_APPLIANCE_MISSING)만 남긴다.
- `config_problems(settings)`: 어댑터 `validate_scx_config` 문제(키 `hpc.scx.*`) + esl 키(client_name·scx_drive.*). 비밀 값 없음.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

CLIENT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
ROOT_KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
APPLIANCE_PLACEHOLDER = "esl-unset"     # appliance 미설정(A 전용 운영) — B 는 SCX_APPLIANCE_MISSING 으로 막는다
ADAPTER_FIELDS = (
    "relay_url", "secret_file", "drive_base", "home_display", "appliance", "version", "ncpu", "memory_gb", "queue_type",
    "run_type", "mpi", "single_precision", "poll_interval_s", "max_download_bytes", "stage_patterns", "list_additional_paths",
    "max_stage_bytes", "stage_poll_s", "stage_timeout_s", "submit_replay_attempts", "submit_replay_wait_s", "http_timeout_s",
    "transfer_timeout_s", "collect_max_depth", "health_ttl_s",
)


def scx_cfg(settings) -> Any | None:
    """settings.hpc.scx(HpcScxCfg) 또는 None."""
    h = getattr(settings, "hpc", None)
    return getattr(h, "scx", None) if h is not None else None


def appliance_set(cfg) -> bool:
    return bool(cfg is not None and str(cfg.appliance or "").strip())


def adapter_mapping(cfg) -> dict[str, Any]:
    d = {k: getattr(cfg, k) for k in ADAPTER_FIELDS}
    d["stage_patterns"] = tuple(d["stage_patterns"] or ())
    if not appliance_set(cfg):
        d["appliance"] = APPLIANCE_PLACEHOLDER
    return d


def _adapter_problems(cfg) -> list[str]:
    from simdash_adapters.hpc import ScxConfig, validate_scx_config

    return list(validate_scx_config(ScxConfig.from_mapping(adapter_mapping(cfg))))


def drive_problems(settings) -> list[str]:
    """scx_drive.* 검사(키 형식·유일, rel = 어댑터 rel_problem, 범위)."""
    from simdash_adapters.hpc.scx_naming import rel_problem

    sd = settings.scx_drive
    out: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(sd.roots):
        if not ROOT_KEY_RE.match(r.key or ""):
            out.append(f"scx_drive.roots[{i}].key: ^[a-z0-9_-]{{1,32}}$")
        elif r.key in seen:
            out.append(f"scx_drive.roots[{i}].key: 중복({r.key})")
        seen.add(r.key)
        if not (r.label or "").strip() or len(r.label) > 100:
            out.append(f"scx_drive.roots[{i}].label: 1~100자")
        why = rel_problem(r.rel or "")
        if why:
            out.append(f"scx_drive.roots[{i}].rel: {why}")
    if not 1 <= int(sd.list_max_entries) <= 50000:
        out.append("scx_drive.list_max_entries: 1~50000")
    if not 1 <= int(sd.max_files) <= 100000:
        out.append("scx_drive.max_files: 1~100000")
    if not 0 <= int(sd.file_retries) <= 10:
        out.append("scx_drive.file_retries: 0~10")
    if not 0 <= float(sd.retry_wait_s) <= 3600:
        out.append("scx_drive.retry_wait_s: 0~3600")
    for i, g in enumerate(sd.engine_globs):
        if "{stem}" not in g or "/" in g or "\\" in g:
            out.append(f"scx_drive.engine_globs[{i}]: '{{stem}}' 포함·'/'·'\\' 금지")
    return out


def config_problems(settings) -> list[str]:
    """SCX 연결 설정 문제 목록(빈 목록 = 사용 가능). hpc.scx 가 없으면 [](사유는 SCX_NOT_CONFIGURED 가 따로)."""
    cfg = scx_cfg(settings)
    if cfg is None:
        return []
    out = [f"hpc.scx: {p}" for p in _adapter_problems(cfg)]
    if not CLIENT_NAME_RE.match(cfg.client_name or ""):
        out.append("hpc.scx.client_name: ^[a-z0-9_-]{1,32}$")
    out += drive_problems(settings)
    return out


def engine_names(stem: str, names: list[str], globs: list[str]) -> list[str]:
    """같은 폴더 이름 목록 중 엔진 rad(engine_globs, {stem} 치환 — 대소문자 무시)."""
    pats = [g.replace("{stem}", stem).casefold() for g in globs]
    return [n for n in names if any(fnmatch.fnmatchcase(n.casefold(), p) for p in pats)]


def run_stem(rad_name: str) -> str | None:
    """starter 이름 → 런 이름(`<stem>_0000.rad` → `<stem>`). `_0000.rad` 가 아니면 None(엔진 rad 를 붙이지 않음)."""
    low = rad_name.casefold()
    if low.endswith("_0000.rad") and len(rad_name) > len("_0000.rad"):
        return rad_name[: -len("_0000.rad")]
    return None


__all__ = ["scx_cfg", "appliance_set", "adapter_mapping", "config_problems", "drive_problems", "engine_names", "run_stem",
           "CLIENT_NAME_RE", "ROOT_KEY_RE", "APPLIANCE_PLACEHOLDER"]
