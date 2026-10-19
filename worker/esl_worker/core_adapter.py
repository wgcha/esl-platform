"""코어(`esl`) 호출 어댑터 — 플랫폼에서 코어를 부르는 **유일한** 곳.

- 계산은 `esl.pipeline.run(...)` 단일 진입점(계약 esl_platform_p1b.md §2). 코어 시그니처가 바뀌는 중일 수 있어
  `inspect.signature`로 받는 인자만 골라 넘긴다(설정은 `cfg=`(dict) 또는 `config_path_or_dict`/`config_path`).
- 동기 API(지지점 제안·저장, 경로 확인)에 필요한 소규모 보조 함수(`list_parts`, `scan_includes`,
  `pca_corners`, `pick_321`, 설정 검증, `/status` 용 솔버 백엔드 조회)도 여기서만 import 한다. 없으면 `CoreUnavailable`.
- 코어 오류(`esl.errors.EslError`)는 `CoreError(code, message)`로 바꿔 플랫폼 코드가 코어 예외 타입에 묶이지 않게 한다.
"""

from __future__ import annotations

import copy
import importlib
import inspect
from collections.abc import Callable
from typing import Any

DEFAULT_STAGES = ("extract", "tstar", "esl", "validate", "export")


class CoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class CoreUnavailable(CoreError):
    def __init__(self, what: str) -> None:
        super().__init__("CORE_UNAVAILABLE", f"코어 기능을 찾을 수 없습니다: {what}")


def _mod(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:  # pragma: no cover - 배포 오류
        raise CoreUnavailable(f"{name} ({exc})") from None


def _attr(module: str, name: str):
    m = _mod(module)
    fn = getattr(m, name, None)
    if fn is None:
        raise CoreUnavailable(f"{module}.{name}")
    return fn


def _esl_error_type():
    try:
        return importlib.import_module("esl.errors").EslError
    except (ImportError, AttributeError):  # pragma: no cover
        return ()


def _wrap(fn: Callable, *args, **kwargs):
    err = _esl_error_type()
    try:
        return fn(*args, **kwargs)
    except CoreError:
        raise
    except Exception as exc:
        if err and isinstance(exc, err):
            raise CoreError(getattr(exc, "code", "CORE_ERROR"), getattr(exc, "message", str(exc))) from None
        raise


# ---------------------------------------------------------------- 정보
def core_version() -> str:
    return str(getattr(_mod("esl"), "__version__", "unknown"))


def stages() -> tuple[str, ...]:
    return tuple(getattr(_mod("esl.pipeline"), "STAGES", DEFAULT_STAGES))


def solver_backends(core_cfg: dict | None) -> dict[str, Any]:
    """`GET /status` tools: 코어 ShellModel 과 같은 규칙(esl.mech.shell)으로 해석한 solver.backend 와 사용 가능 목록.

    - ``solver_backend``: 설정 값을 ``resolve_backend`` 로 해석한 값(= ShellModel.stats["backend"]; auto → 설치된
      직접법 1순위). 설정 백엔드가 미설치면 설정 값 그대로.
    - ``solver_backends_available``: ``available_backends()`` (우선순위 순) + ``iterative``(항상 가능).
    """
    requested = str(((core_cfg or {}).get("solver") or {}).get("backend") or "auto")
    shell = _mod("esl.mech.shell")
    avail = list(shell.available_backends())
    if "iterative" not in avail:
        avail.append("iterative")
    try:
        backend = shell.resolve_backend(requested)
    except Exception:  # 미설치 백엔드 지정 → 작업 실행 시 코어가 INPUT_INVALID
        backend = requested
    return {"solver_backend": backend, "solver_backends_available": avail}


# ---------------------------------------------------------------- 설정
def validate_core_settings(cfg: Any) -> dict:
    fn = _attr("esl.config", "validate_settings")
    return _wrap(fn, copy.deepcopy(cfg))


def load_core_config(path: str) -> dict:
    fn = _attr("esl.config", "load_config")
    return _wrap(fn, path)


# ---------------------------------------------------------------- 파이프라인
def run_signature() -> list[str]:
    return list(inspect.signature(_attr("esl.pipeline", "run")).parameters)


def run_pipeline(
    cfg: dict,
    rad: str,
    results: str,
    out: str,
    stage: str,
    *,
    frame: int | None = None,
    support_nodes: list[int] | None = None,
    echo: Callable[[str], None] | None = None,
) -> dict:
    """`esl.pipeline.run` 1회 호출. 받지 않는 인자는 넘기지 않는다(시그니처 검사)."""
    fn = _attr("esl.pipeline", "run")
    params = inspect.signature(fn).parameters
    kw: dict[str, Any] = {}
    if "cfg" in params:
        kw["cfg"] = copy.deepcopy(cfg)
    elif "config_path_or_dict" in params:
        kw["config_path_or_dict"] = copy.deepcopy(cfg)
    elif "config" in params:
        kw["config"] = copy.deepcopy(cfg)
    else:
        raise CoreUnavailable("esl.pipeline.run 이 설정 dict 를 받지 않음")
    for name, value in (("rad", rad), ("results", results), ("out", out), ("stage", stage)):
        if name not in params:
            raise CoreUnavailable(f"esl.pipeline.run 인자 {name}")
        kw[name] = value
    if frame is not None:
        if "frame" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 frame")
        kw["frame"] = int(frame)
    if support_nodes is not None:
        if "support_nodes" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 support_nodes")
        kw["support_nodes"] = [int(n) for n in support_nodes]
    if echo is not None and "echo" in params:
        kw["echo"] = echo
    rec = _wrap(fn, **kw)
    return rec if isinstance(rec, dict) else {}


# ---------------------------------------------------------------- 동기 API 보조
def list_parts(rad: str, max_depth: int, include_path_map: dict | None = None) -> list[dict]:
    fn = _attr("esl.rad", "list_parts")
    kw: dict[str, Any] = {}
    params = inspect.signature(fn).parameters
    if "max_include_depth" in params:
        kw["max_include_depth"] = max_depth
    if "include_path_map" in params and include_path_map:
        kw["include_path_map"] = include_path_map
    return list(_wrap(fn, rad, **kw))


def scan_includes(rad: str, max_depth: int, include_path_map: dict | None = None) -> list[str]:
    fn = _attr("esl.rad", "scan_includes")
    kw: dict[str, Any] = {}
    params = inspect.signature(fn).parameters
    if "max_depth" in params:
        kw["max_depth"] = max_depth
    if "include_path_map" in params and include_path_map:
        kw["include_path_map"] = include_path_map
    return list(_wrap(fn, rad, **kw))


def pca_corners(x0) -> dict:
    return _wrap(_attr("esl.mech.supports", "pca_corners"), x0)


def pick_321(x0, cand_idx) -> list[tuple[int, str]]:
    out = _wrap(_attr("esl.mech.supports", "pick_321"), x0, list(cand_idx))
    return [(int(i), str(d)) for i, d in out]
