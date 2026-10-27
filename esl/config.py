"""ESL 계산 코어 설정 로더 (계약 esl_core.md §5, esl.md §2 원형).

- ``load_config(path=None)``: YAML 로드 + 검증. ``path`` 가 없으면 env ``ESL_CONFIG``.
- ``validate_settings(cfg)``: 필수 키·타입·범위 검사. 실패 → ``EslError("CONFIG_INVALID", <키>: ...)``.
- ``redacted_settings(cfg)``: run.json 스냅샷용 사본(현재 비밀 값 없음 → 깊은 복사).

코드에는 키 이름과 검사 규칙만 있고 **기본값은 없다**(값은 ``config/esl.example.yaml``).
알 수 없는 키도 오타 방지를 위해 CONFIG_INVALID.
"""
from __future__ import annotations

import copy
import math
import os
from typing import Any, Callable

import yaml

from esl.errors import EslError

ENV_CONFIG = "ESL_CONFIG"
SCHEMA_VERSION = 1


def _bad(key: str, msg: str) -> EslError:
    return EslError("CONFIG_INVALID", f"{key}: {msg}")


# ---------------------------------------------------------------- 원자 검사기
def _int(lo: int | None = None, hi: int | None = None) -> Callable[[str, Any], None]:
    def chk(key, v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise _bad(key, f"정수여야 함 (값 {v!r})")
        if lo is not None and v < lo:
            raise _bad(key, f"{lo} 이상이어야 함 (값 {v})")
        if hi is not None and v > hi:
            raise _bad(key, f"{hi} 이하이어야 함 (값 {v})")
    return chk


def _num(lo: float | None = None, hi: float | None = None, lo_open=False, hi_open=False):
    def chk(key, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise _bad(key, f"유한 실수여야 함 (값 {v!r})")
        v = float(v)
        if lo is not None and (v <= lo if lo_open else v < lo):
            raise _bad(key, f"{'>' if lo_open else '≥'} {lo} 이어야 함 (값 {v})")
        if hi is not None and (v >= hi if hi_open else v > hi):
            raise _bad(key, f"{'<' if hi_open else '≤'} {hi} 이어야 함 (값 {v})")
    return chk


def _enum(*vals):
    def chk(key, v):
        if v not in vals:
            raise _bad(key, f"{list(vals)} 중 하나여야 함 (값 {v!r})")
    return chk


def _opt(chk_fn):
    """None 허용 + 그 외는 chk_fn 검사."""
    def chk(key, v):
        if v is not None:
            chk_fn(key, v)
    return chk


def _str(nonempty=True):
    def chk(key, v):
        if not isinstance(v, str) or (nonempty and not v.strip()):
            raise _bad(key, f"{'비어 있지 않은 ' if nonempty else ''}문자열이어야 함 (값 {v!r})")
    return chk


def _int_list(key, v):
    if not isinstance(v, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        raise _bad(key, f"정수 목록이어야 함 (값 {v!r})")


def _layers(key, v):
    if not isinstance(v, list) or not v or len(set(map(str, v))) != len(v) \
            or any(x not in ("mid", "bottom", "top") for x in v):
        raise _bad(key, f"[mid|bottom|top] 중복 없는 비어 있지 않은 목록이어야 함 (값 {v!r})")


def _time_window(key, v):
    if not isinstance(v, list) or len(v) != 2:
        raise _bad(key, f"[t_min, t_max] 2개 목록이어야 함 (null 허용) (값 {v!r})")
    for x in v:
        if x is not None and (isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x))):
            raise _bad(key, f"원소는 실수 또는 null (값 {v!r})")
    if v[0] is not None and v[1] is not None and float(v[0]) > float(v[1]):
        raise _bad(key, f"t_min > t_max (값 {v!r})")


def _float_fmt(max_len: int):
    def chk(key, v):
        if not isinstance(v, str):
            raise _bad(key, f"format 문자열이어야 함 (값 {v!r})")
        try:
            outs = [v.format(x) for x in (0.0, -1.234567890123e-300, 9.87654321e+300, 1.0)]
            back = [float(s) for s in outs]
        except (ValueError, IndexError, KeyError) as exc:
            raise _bad(key, f"실수 format 이 아님 ({exc}) (값 {v!r})") from None
        if back[3] != 1.0 or back[0] != 0.0:
            raise _bad(key, f"값을 보존하지 않는 format (값 {v!r})")
        for s in outs:
            if "," in s or " " in s.strip() or len(s) > max_len:
                raise _bad(key, f"출력 '{s}' 가 콤마·공백을 포함하거나 {max_len}자 초과")
    return chk


def _delimiter(key, v):
    if not isinstance(v, str) or len(v) != 1 or v in "0123456789.+-eE\"\r\n":
        raise _bad(key, f"구분자는 숫자·부호·따옴표가 아닌 1글자 (값 {v!r})")


def _material_override(key, v):
    if not isinstance(v, dict):
        raise _bad(key, f"{{mat_id: {{E, nu}}}} 사전이어야 함 (값 {v!r})")
    for mk, mv in v.items():
        try:
            int(mk)
        except (TypeError, ValueError):
            raise _bad(f"{key}.{mk}", "mat_id 는 정수") from None
        if not isinstance(mv, dict) or set(mv) - {"E", "nu", "rho"} or not {"E", "nu"} <= set(mv):
            raise _bad(f"{key}.{mk}", f"{{E, nu[, rho]}} 이어야 함 (값 {mv!r})")
        _num(0.0, lo_open=True)(f"{key}.{mk}.E", mv["E"])
        _num(-1.0, 0.5, lo_open=True, hi_open=True)(f"{key}.{mk}.nu", mv["nu"])
        if "rho" in mv and mv["rho"] is not None:
            _num(0.0, lo_open=True)(f"{key}.{mk}.rho", mv["rho"])


def _path_map(key, v):
    """{Windows 접두: 로컬 경로} (include 경로 치환). 빈 사전 허용."""
    if not isinstance(v, dict):
        raise _bad(key, f"{{원래 접두: 로컬 경로}} 사전이어야 함 (값 {v!r})")
    for mk, mv in v.items():
        if not isinstance(mk, str) or not mk.strip():
            raise _bad(f"{key}.{mk}", "접두는 비어 있지 않은 문자열")
        if not isinstance(mv, str) or not mv.strip():
            raise _bad(f"{key}.{mk}", f"로컬 경로는 비어 있지 않은 문자열 (값 {mv!r})")


# ---------------------------------------------------------------- 스키마
# 값 = 검사기 함수 또는 하위 스키마(dict). 모든 키 필수.
SCHEMA: dict[str, Any] = {
    "schema_version": _enum(SCHEMA_VERSION),
    "case": {
        "part_title": _str(),
        "part_title_match": _enum("exact", "exact_ci"),
        "rad_include_max_depth": _int(0, 64),
        "material_override": _material_override,
        "include_path_map": _path_map,
    },
    "extract": {
        "frame_stride": _int(1),
        "layers": _layers,
        "shear_convention": _enum("auto", "tensor", "engineering"),
        "hot_k": _int(1),               # 상한 없음(크면 extract 단계 경고)
        "disp_precision": _enum("float32", "float64"),
    },
    "coord_check": {                # extract 단계 rad↔h3d 좌표 개략 확인(esl_core.md §3.3)
        "max_rel": _num(0.0),              # Kabsch 강체 정합 후 잔차 최대 ≤ 이 값·bbox 이면 통과
    },
    "tstar": {
        "metric": _enum("max_strain", "plastic_strain"),
        "reach_rtol": _num(0.0, 1.0, hi_open=True),
        "top_n_times": _int(1),
        "top_k_hotspots": _int(1),
        "hotspot_min_dist": _num(0.0),
        "time_window": _time_window,
        "exclude_elem_ids": _int_list,
    },
    "support": {
        "candidates": _enum("pca4", "node_ids"),
        "node_ids": _int_list,
    },
    "solver": {
        "backend": _enum("auto", "cholmod", "pardiso", "superlu", "iterative"),
        "iter_rtol": _num(0.0, 1.0, lo_open=True, hi_open=True),
        "iter_maxiter": _opt(_int(1)),          # null = 자동(ShellModel 기본)
        "drill_factor": _num(0.0, 1.0, lo_open=True),
        "equilibrium_warn_rel": _num(0.0, lo_open=True),
    },
    "validation": {
        "disp_rms_rel_max": _num(0.0, lo_open=True),
        "hotspot_strain_rel_err_max": _num(0.0, lo_open=True),
        "reaction_rel_max": _num(0.0, lo_open=True),
        "hotspot_eval_count": _int(1),
        "full_solve": _enum("auto", "always", "never"),
        "noise_samples": _int(1, 100),
        "noise_force_rel_warn": _num(0.0, lo_open=True),
        "noise_strain_rel_max": _num(0.0, lo_open=True),
    },
    "compare": {                                # 전 요소 재현 정확도 비교(계약 esl_p2_library.md §7.2)
        "min_rel": _num(0.0, 1.0),
        "max_err_pct_max": _num(0.0, lo_open=True),
        "p90_err_max": _num(0.0, lo_open=True),
        "top_n": _int(1, 1000),
        "hist_bins": _int(2, 200),
        "section_band": _num(0.0, 0.5, lo_open=True),
    },
    "report": {                                 # Case HTML 보고서(§5·§7.3)
        "max_points": _int(100, 1_000_000),
        "top_forces": _int(1, 1000),
    },
    "export": {
        "radioss": {
            "id_offset": _int(1, 9_999_999_999 - 999_999),   # 생성 ID 가 I10 에 들어가야 함
            "ramp_time": _num(0.0, lo_open=True),
            "func_mode": _enum("ramp", "constant"),
        },
        "force_zero_tol_rel": _num(0.0, 1.0, hi_open=True),
        "num_format": _float_fmt(20),          # Radioss F20 칸·.fem 자유형식 공용
        "csv": {
            "delimiter": _delimiter,
            "float_format": _float_fmt(64),
        },
    },
    "units": {
        "label": _str(),
        "length": _str(),
        "force": _str(),
        "stress": _str(),
        "time": _str(),
    },
}


# 기본값은 여기 한 곳. 이전 버전 esl.yaml 에 coord_check(또는 max_rel)가 없어도 이 값으로 채운다(그 외 키는 모두 필수).
COORD_CHECK_DEFAULTS = {"max_rel": 0.005}
# 0.5.3~0.5.4 의 coord_check 키(0.5.5 에서 폐지): 업데이트 호환을 위해 있어도 경고 없이 무시
COORD_CHECK_LEGACY_KEYS = ("warn_max_frac", "warn_max_rel")


def _walk(schema: dict, node: Any, prefix: str) -> None:
    if not isinstance(node, dict):
        raise _bad(prefix or "<root>", f"사전(mapping)이어야 함 (값 {type(node).__name__})")
    for k in node:
        if k not in schema:
            raise _bad(f"{prefix}{k}", "알 수 없는 키")
    for k, rule in schema.items():
        key = f"{prefix}{k}"
        if k not in node:
            raise _bad(key, "필수 키 누락")
        if isinstance(rule, dict):
            _walk(rule, node[k], key + ".")
        else:
            rule(key, node[k])


def validate_settings(cfg: Any) -> dict:
    """검증 통과 시 cfg 그대로 반환. 실패 → CONFIG_INVALID(키 경로 포함)."""
    if isinstance(cfg, dict):
        cc = cfg.get("coord_check")
        if cc is None:
            cfg["coord_check"] = dict(COORD_CHECK_DEFAULTS)
        elif isinstance(cc, dict):
            for k in COORD_CHECK_LEGACY_KEYS:
                cc.pop(k, None)
            for k, v in COORD_CHECK_DEFAULTS.items():
                cc.setdefault(k, v)
    _walk(SCHEMA, cfg, "")
    sup = cfg["support"]
    if sup["candidates"] == "node_ids" and len(set(sup["node_ids"])) < 3:
        raise _bad("support.node_ids", "candidates=node_ids 이면 서로 다른 노드 ID 3개 이상 필요")
    return cfg


def resolve_config_path(path: str | os.PathLike | None = None) -> str:
    if path is None or str(path) == "":
        path = os.environ.get(ENV_CONFIG, "")
        if not path:
            raise EslError("CONFIG_INVALID", f"설정 파일 경로가 없음(--config 또는 env {ENV_CONFIG})")
    return os.fspath(path)


def load_config(path: str | os.PathLike | None = None) -> dict:
    """YAML 설정을 읽어 검증한다. path 없으면 env ESL_CONFIG."""
    p = resolve_config_path(path)
    if not os.path.isfile(p):
        raise EslError("CONFIG_INVALID", f"설정 파일이 없음: {p}")
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            cfg = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise EslError("CONFIG_INVALID", f"설정 파일을 읽을 수 없음({p}): {exc}") from None
    return validate_settings(cfg)


def redacted_settings(cfg: dict) -> dict:
    """run.json 스냅샷용 사본. (P1a 설정에는 비밀 값 없음)"""
    return copy.deepcopy(cfg)
