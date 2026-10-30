"""SCX 설정 변환·검사(계약 esl_scx_relay.md §6·SR-D-4). 값이 틀려도 기동은 하고 SCX 기능만 비활성(사유 SCX_CONFIG_INVALID).

- `adapter_mapping(cfg)`: `hpc.scx`(HpcScxCfg) → 어댑터 `ScxConfig.from_mapping` 인자. appliance 가 비었으면 A 는 쓸 수 있게
  자리표시 값을 넣고(어댑터 검사는 appliance 필수) `appliance_set=False` 로 B 비활성 사유(SCX_APPLIANCE_MISSING)만 남긴다.
- `config_problems(settings)`: 어댑터 `validate_scx_config` 문제(키 `hpc.scx.*`) + esl 키(client_name·scx_drive.*). 비밀 값 없음.
"""

from __future__ import annotations

import fnmatch
import os
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
    if cfg.secret_file and not secret_path_absolute(cfg.secret_file):
        out.append("hpc.scx.secret_file: 절대경로여야 합니다(SR-D-18 — 상대경로는 작업 폴더에 따라 다른 파일을 가리킴)")
    if getattr(cfg, "dashboard_root", "") and not secret_path_absolute(cfg.dashboard_root):
        out.append("hpc.scx.dashboard_root: 대시보드 설치 폴더 절대경로여야 합니다")
    if not CLIENT_NAME_RE.match(cfg.client_name or ""):
        out.append("hpc.scx.client_name: ^[a-z0-9_-]{1,32}$")
    out += drive_problems(settings)
    return out


_WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/])")


def secret_path_absolute(p: str) -> bool:
    """v0.12.0 L1: 비밀 파일 경로는 절대경로만(POSIX `/…`, Windows `C:\\…`·`\\\\서버\\공유\\…`). `~`·상대경로 거부."""
    s = str(p or "")
    if not s or s.startswith("~"):
        return False
    return bool(_WIN_ABS.match(s)) or (os.name != "nt" and s.startswith("/"))


# ---------------------------------------------------------------- v0.12.0 비밀 파일 경로 해석(secret_file "" = 대시보드 따라가기)
DASH_SECRET_KEY = "SIMDASH_SCX_RELAY_SECRET_FILE"
SECRET_SOURCE_LABEL = {"config": "설정", "env": "env", "dashboard_env": "대시보드 .env", "runtime": "런타임 기본"}
SECRET_MISSING_HINT = ("hpc.scx.secret_file 이 비어 있고 비밀 파일을 찾지 못했습니다 — env SIMDASH_SCX_RELAY_SECRET_FILE, "
                       "hpc.scx.dashboard_root(대시보드 .env 의 SIMDASH_SCX_RELAY_SECRET_FILE), <런타임>/secrets/scx_relay_key "
                       "중 하나를 두거나 secret_file 에 절대경로를 쓰세요")


def _dotenv_value(line: str, key: str) -> str | None:
    """python-dotenv 형식 한 줄에서 key 값만(`export ` 접두, 따옴표, 따옴표 밖 ` #` 주석). 다른 키면 None."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("export "):
        s = s[7:].lstrip()
    k, sep, v = s.partition("=")
    if not sep or k.strip() != key:
        return None
    v = v.strip()
    if v[:1] in ("'", '"'):
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    i = v.find(" #")
    return (v[:i] if i >= 0 else v).strip()


def dashboard_env_secret(dashboard_root: str) -> tuple[str | None, str | None]:
    """(값, 읽은 .env 경로). 대시보드처럼 <root>/.env → <root>/backend/.env 순서, SIMDASH_SCX_RELAY_SECRET_FILE 줄만 본다
    (다른 값은 읽지도 남기지도 않음 — 줄 단위로 키만 비교)."""
    if not dashboard_root:
        return None, None
    for p in (os.path.join(dashboard_root, ".env"), os.path.join(dashboard_root, "backend", ".env")):
        try:
            with open(p, encoding="utf-8-sig") as fh:
                for line in fh:
                    v = _dotenv_value(line, DASH_SECRET_KEY)
                    if v is not None:
                        return v, p
        except OSError:
            continue
    return None, None


def runtime_dir(environ: dict[str, str] | None = None) -> str | None:
    """esl 런타임 폴더 = env ESL_PLATFORM_CONFIG 가 <런타임>/config/esl_platform.yaml 일 때 그 <런타임>."""
    env = os.environ if environ is None else environ
    p = env.get("ESL_PLATFORM_CONFIG") or ""
    if not p:
        return None
    d = os.path.dirname(os.path.abspath(p))
    return os.path.dirname(d) if os.path.basename(d).lower() == "config" else None


def resolve_secret_file(cfg, *, environ: dict[str, str] | None = None, runtime: str | None = None) -> dict[str, Any]:
    """비밀 파일 경로 해석 → {path|None, source(config|env|dashboard_env|runtime|None), env_file|None, problem|None}.
    명시 절대경로가 우선(상대경로는 config_problems 가 거부). 비어 있으면 (1) esl env SIMDASH_SCX_RELAY_SECRET_FILE →
    (2) hpc.scx.dashboard_root 의 .env·backend/.env → (3) <런타임>/secrets/scx_relay_key. 값(비밀)은 읽지 않는다 — 경로만."""
    env = os.environ if environ is None else environ
    explicit = str(getattr(cfg, "secret_file", "") or "")
    if explicit:
        return {"path": explicit if secret_path_absolute(explicit) else None, "source": "config", "env_file": None,
                "problem": None if secret_path_absolute(explicit) else "hpc.scx.secret_file: 절대경로여야 합니다"}
    v = (env.get(DASH_SECRET_KEY) or "").strip()
    if v:
        ok = secret_path_absolute(v)
        return {"path": v if ok else None, "source": "env", "env_file": None,
                "problem": None if ok else f"env {DASH_SECRET_KEY}: 절대경로여야 합니다"}
    root = str(getattr(cfg, "dashboard_root", "") or "")
    if root:
        v, f = dashboard_env_secret(root)
        if v:
            ok = secret_path_absolute(v)
            return {"path": v if ok else None, "source": "dashboard_env", "env_file": f,
                    "problem": None if ok else f"{f} 의 {DASH_SECRET_KEY}: 절대경로여야 합니다"}
    rt = runtime or runtime_dir(env)
    if rt:
        p = os.path.join(rt, "secrets", "scx_relay_key")
        if os.path.isfile(p):
            return {"path": p, "source": "runtime", "env_file": None, "problem": None}
    return {"path": None, "source": None, "env_file": None, "problem": SECRET_MISSING_HINT}


def secret_source_text(r: dict[str, Any]) -> str:
    """환경 점검 표시: '출처: env | 대시보드 .env(<경로>) | 런타임 기본 | 설정'(값 미출력)."""
    src = r.get("source")
    if src == "dashboard_env":
        return f"출처: 대시보드 .env({r.get('env_file')})"
    return f"출처: {SECRET_SOURCE_LABEL.get(src, '없음')}"


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
           "secret_path_absolute",
           "CLIENT_NAME_RE", "ROOT_KEY_RE", "APPLIANCE_PLACEHOLDER"]
