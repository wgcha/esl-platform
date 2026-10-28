"""비드 최적화 서버 실행 코어 (계약 docs/contracts/esl_opt_run.md, v0.7.0 O1).

코어는 DB 를 모른다. 백엔드(O2)·워커(O3)가 설정 파일의 ``opt_run`` 절을 ``settings(cfg)`` 로 합쳐 넘긴다.
여기 ``DEFAULTS`` 는 계약 §11 설정 키의 **기본값 거울**(설정 파일에 키가 없을 때만 쓰임) — 함수 안에 숫자를 직접
쓰지 않고 항상 이 dict(또는 호출자가 준 설정)에서 읽는다.

모듈
- ``femread``     : .fem(GRID·CQUAD4·CTRIA3·PSHELL·MAT1) 읽기 / 쓰기
- ``mesh_check``  : 템플릿·대상 메시 검사(§7.2), rad/fem 공통 적재
- ``identity``    : topo_sha256, S1 모델 동일성(§7.3)
- ``size``        : S2 크기 규칙(§7.1)
- ``target``      : 대상 준비(S1 CaseTarget / S2 TemplateTarget), 하중(S1 직접 / S2 셀 매핑), 덱 입력
- ``keepout``     : 비드 금지 영역(자동 구멍·가장자리 + 사각형) 마스크와 평면도 자료(§7.5)
- ``modes``       : 변형 모드 분류(§7.4)
- ``select``      : 초기 컴플라이언스(분해 1회) + 하중 선정 전략 A/B/C(§7.4)
- ``osout``       : OptiStruct .out/.hist 해석(§8)
- ``post``        : 비드 후처리 산출물(§9)
- ``png``         : 순수 Python PNG 인코더·평면도 렌더러
- ``report_opt``  : 보고서 HTML(방법·출처 절 포함, §9.1)
"""
from __future__ import annotations

import copy
import json
import os

from esl.errors import EslError

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resources")
METHOD_SOURCES_PATH = os.path.join(RESOURCES, "opt_method_sources.json")
BEAD_POST_TCL = os.path.join(RESOURCES, "tcl", "esl_bead_post.tcl")

# 계약 §11 opt_run 기본값(설정 파일 우선). 값 변경은 설정 파일에서.
DEFAULTS: dict = {
    "enabled": False,
    "max_entries": 200,
    "size": {"tol_rel": 0.02, "plate_tol_rel": 0.05, "require_inch": True},
    "template": {"max_elems": 500000, "flat_tol_rel": 0.02, "max_tria_frac": 0.2},
    "bead_defaults": {"angle": 45.0, "min_width": 60.0, "height": 10.0},
    "keepout": {"hole_radius_mm": 15.0, "edge_band_mm": 10.0, "hole_min_perimeter_mm": 5.0, "max_rects": 20,
                "frame_warn_mm": 1.0, "rect_name_max": 40},
    "loads": {"default_strategy": "A", "mac_merge": 0.95, "max_cases": 20, "default_k": 5,
              "default_objective_norm": "abs", "linkage": "average", "c0_tol": 0.05},
    "mode": {"rule_version": 1, "dent_resid_min": 0.5, "dent_conc_min": 0.6, "dent_area_frac": 0.05,
             "min_energy_rel": 1.0e-6},
    "solver": {"drill_factor": 1.0e-4, "backend": "auto"},
    "solve": {"nt": 4, "desmax": 30, "timeout_h": 12, "log_tail_lines": 2000,
              "error_patterns": [r"(?m)^\s*\*\*\* ERROR"],
              "converged_patterns": ["OPTIMIZATION HAS CONVERGED"],
              "license_patterns": [r"(?i)license.*(not available|checkout failed|insufficient|exceeded)",
                                   r"(?i)ALM_\w+_ERROR"],
              "license_retry": {"max": 3, "wait_s": 300}, "env": {},
              # .out 해석 패턴(확신도 중 — V-OR-R1 실기에서 확인)
              "iteration_pattern": r"(?m)^\s*ITERATION\s+(\d+)",
              "objective_pattern": r"(?im)^\s*Objective\s+Function\b[^=\n]*=\s*([-+]?[0-9.]+(?:[EeDd][-+]?\d+)?)",
              "compliance_pattern": (r"(?m)^\s*\|\s*\d+\s*\|[^|\n]*\|\s*COMPL\w*\s*\|[^|\n]*\|[^|\n]*\|\s*(\d+)\s*\|"
                                     r"\s*([-+]?[0-9.]+(?:[EeDd][-+]?\d+)?)"),
              "memory_patterns": [r"(?i)(insufficient|not enough)\s+memory", r"(?i)memory allocation failed"]},
    "post": {"png_px": [1600, 900], "bead_area_thr_rel": 0.1, "report_map_cells": [96, 54]},
    # 계약 §7.2 메시 검사 경고 기준(설정 가능)
    "check": {"bead_width_elem_factor": 2.0, "min_nodes_per_cell": 64, "max_aspect": 10.0, "max_warp_deg": 15.0},
    # 정규화 격자(라이브러리와 같은 24×14) — S2 셀 매핑
    "grid": {"nx": 24, "ny": 14},
    "ui": {"max_preview_points": 20000},
}

STRATEGIES = ("A", "B", "C")
OBJECTIVE_NORMS = ("abs", "rel")
MODES = ("dent", "twist", "bend")


def _deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def settings(cfg: dict | None = None) -> dict:
    """설정 dict(전체 설정 또는 ``opt_run`` 절)을 기본값 위에 합친 opt_run 설정."""
    if cfg is None:
        return copy.deepcopy(DEFAULTS)
    sect = cfg.get("opt_run", cfg) if isinstance(cfg, dict) else None
    if sect is None:
        return copy.deepcopy(DEFAULTS)
    if not isinstance(sect, dict):
        raise EslError("CONFIG_INVALID", "opt_run 절은 매핑이어야 함")
    return _deep_merge(DEFAULTS, sect)


# ---------------------------------------------------------------- 방법·출처 자료 (§9.1)
def validate_method_sources(obj) -> dict:
    """``opt_method_sources.json`` 스키마 검사. 문제 있으면 CONFIG_INVALID."""
    def bad(msg):
        raise EslError("CONFIG_INVALID", f"opt_method_sources: {msg}")
    if not isinstance(obj, dict):
        bad("최상위는 객체")
    if not isinstance(obj.get("version"), str) or not obj["version"]:
        bad("version(문자열) 필요")
    s = obj.get("summary_ko")
    if not isinstance(s, list) or not 2 <= len(s) <= 3 or not all(isinstance(x, str) and x for x in s):
        bad("summary_ko 는 문자열 2~3개")
    st = obj.get("strategies")
    if not isinstance(st, dict) or set(st) != set(STRATEGIES) or not all(isinstance(st[k], str) and st[k] for k in st):
        bad("strategies 는 A·B·C 한 줄씩")
    on = obj.get("objective_norms")
    if not isinstance(on, dict) or set(on) != set(OBJECTIVE_NORMS) or not all(isinstance(on[k], str) and on[k] for k in on):
        bad("objective_norms 는 abs·rel 한 줄씩")
    src = obj.get("sources")
    if not isinstance(src, list) or not src:
        bad("sources 는 1개 이상")
    for i, x in enumerate(src):
        if not isinstance(x, dict) or not isinstance(x.get("title"), str) or not x["title"]:
            bad(f"sources[{i}].title 필요")
        for k in ("authors", "url", "note"):
            if x.get(k) is not None and not isinstance(x[k], str):
                bad(f"sources[{i}].{k} 는 문자열")
        u = x.get("url")
        if u and not (u.startswith("https://") or u.startswith("http://")):
            bad(f"sources[{i}].url 은 http(s)")
    return obj


def load_method_sources(path: str | None = None) -> dict:
    p = path or METHOD_SOURCES_PATH
    try:
        with open(p, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError) as exc:
        raise EslError("CONFIG_INVALID", f"opt_method_sources 를 읽을 수 없음: {p}: {exc}") from None
    return validate_method_sources(obj)


def sources_ref(ms: dict) -> str:
    return f"opt_method_sources/{ms['version']}"
