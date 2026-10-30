"""ESL 기반 Ch/R 비드 형상 DOE 코어 (계약 docs/contracts/esl_bead_doe.md, v0.9.0 D1).

코어는 DB 를 모르고 외부 명령(paicad)도 실행하지 않는다. 백엔드(D2)·워커(D3)가 설정 파일의 ``bead_doe`` 절을
``settings(cfg)`` 로 합쳐 넘긴다. ``DEFAULTS`` 는 계약 §14 설정 키의 **기본값 거울**(설정 파일에 키가 없을 때만
쓰임) — 함수 안에 숫자를 직접 쓰지 않고 이 dict(또는 호출자 설정)에서 읽는다. 크기 허용·구멍 루프·솔버는
``opt_run`` 키를 재사용한다(``opt_settings``).

모듈
- ``matrix``      : DOE 생성(LHS·Halton·풀 팩토리얼, 반올림·중복 제거·공칭 d000·sha256), 미리보기 입력(cells·thumb)
- ``paicad_io``   : paicad argv 구성(선택 쌍 규칙), RESULT/PROGRESS 해석, 보고 JSON 읽기, 실패 코드 분류, 버전 판정
- ``nodes``       : paicad check 사본(out_files)의 /NODE 좌표 읽기(readline 상한)
- ``mesh_gmsh``   : ③ gmsh 쉘 메시(quad 위주, 결정적), STEP 내보내기, 하위 프로세스 격리
- ``scenario``    : ①②③ 기준 메시·frame·지지·하중(esl.opt.target·size·identity 재사용), 입력 보호 검사
- ``boundary``    : ②③ 경계 매핑 경고(A 체결점·하중 집중 → B 체결 후보)
- ``evaluate``    : 안 해석(분해 1회 + 선택 ESL 전부), design.npz·result.json·done.json
- ``rank``        : 순위(score = 안 최악 C / 베이스라인 최악 C)·민감도(SRC + Spearman, 주효과)
- ``export_mesh`` : ③ 메시 산출물 ch_r.rad·ch_r.fem
- ``report_doe``  : 자체 완결 보고서 HTML(방법·출처·한계 절)
- ``stages``      : 워커 진입점 bd_input·bd_mesh0·bd_loads·bd_matrix·bd_eval·bd_post
"""
from __future__ import annotations

import copy
import json
import os

from esl.errors import EslError

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resources")
MESSAGES_PATH = os.path.join(RESOURCES, "doe_messages.json")
METHOD_SOURCES_PATH = os.path.join(RESOURCES, "doe_method_sources.json")

SCENARIOS = ("same", "mesh", "step")
METHODS = ("lhs", "halton", "fullfact")
PARAM_TYPES = ("D", "W", "U", "V")
SOLVERS = ("linear",)

# 안 상태 (§9.2)
READY = "READY"
RUNNING = "RUNNING"
OK = "OK"
SKIPPED = ("SKIPPED_COLLISION", "SKIPPED_FIXED", "SKIPPED_GEOM")
FAILED = ("FAILED_MORPH", "FAILED_MESH", "FAILED_SOLVE")
CANCELED = "CANCELED"
DESIGN_STATES = (READY, RUNNING, OK) + SKIPPED + FAILED + (CANCELED,)

# 계약 §14 bead_doe 기본값(설정 파일 우선). 값 변경은 설정 파일에서.
DEFAULTS: dict = {
    "enabled": False,                       # 섹션 없으면 enabled: false
    "part_title": "chassis rear",
    "max_entries": 50,
    "max_designs": 200,
    "step_max_mb": 200,
    "same": {"max_assem_mb": 4096, "engine_rad": False},     # engine_rad: prep/assem_full 에 엔진 rad 포함(v0.12.1)
    # v0.12.1 paicad 스캔 사본(prep/assem_full)만 키워드 줄 정규화 — 원본·모핑 사본(out_files) 불변
    "fixed_scan": {"enabled": True, "rules": [["SURF/PART/EXT", "SURF/PART"], ["SURF/PART/ALL", "SURF/PART"]],
                   "expand_subset": True, "expand_gene": True, "expand_solid": True},
    "paicad": {
        "exe": None, "min_version": "0.14.0", "pinned_version": "0.14.0", "threads": 4,
        "timeout_s": {"version": 60, "fixed_scan": 3600, "extract": 3600, "tag": 3600, "grid": 7200, "run": 3600,
                      "update": 1800},
        "options": {}, "env": {}, "keep_files_top": 3, "check_interval_s": 600,
    },
    "mesh": {"size_min_mm": 1.0, "size_max_mm": 20.0, "min_size_factor": 0.2, "curvature_n": 12, "algorithm": 8,
             "min_quad_frac": 0.8, "max_elems": 500000, "timeout_s": 1800,
             "occ_sew_faces": 0},                # §7.1 Geometry.OCCSewFaces (0 = 계약 기본, 면 따로인 STEP 은 1)
    "doe": {"default_method": "lhs", "default_n": 30, "seed": 1, "levels_default": 3, "levels_max": 9,
            "round_mm": 0.01, "default_types": ["D", "W"]},
    "preview": {"w": 320, "h": 240, "view_dir": "auto", "tilt_deg": 20, "margin": 1.15, "disp_range_mm": "auto"},
    "run": {"parallel": 2, "memory_margin": 0.7},
    "solve": {"reaction_warn": 0.01},
    "boundary": {"fastener_warn_mm": 10.0, "load_warn_mm": 20.0, "load_share_min": 0.2},
    "view3d": {"top_k": 3},
    # v0.10.0 §11.4 ESL별 개선 지표: '변화 없음' 허용치(③ 은 max(이 값, noise_floor)), 순위 행에 per_esl 을 넣는 상한(안 수 × ESL 수)
    "rank": {"ratio_tol": 1e-6, "per_esl_inline_max": 2000},
    "settings_cache_s": 300,
    # 계약에 숫자가 명시된 내부 상한(설정으로 바꿀 수 있게 키로 둠)
    "limits": {"max_json_mb": 64, "seed_max": 2 ** 32 - 1, "n_min": 2, "levels_min": 2, "cluster_k_max": 5,
               "ranking_report_rows": 20, "min_disp_range_mm": 1.0},
}

# 계약 §14 commands.paicad_* 기본값 거울(설정 commands 가 우선)
DEFAULT_COMMANDS: dict = {
    "paicad_version": ["{paicad}", "version", "--json"],
    "paicad_fixed_scan": ["{paicad}", "shell", "fixed-scan", "--assem-dir", "{assem_dir}", "--parts", "{parts}",
                          "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"],
    "paicad_extract": ["{paicad}", "shell", "extract", "--cad", "{cad}", "--out-dir", "{out_dir}", "--assem-dir",
                       "{assem_dir?}", "--body-map", "{body_map?}", "--options", "{options?}", "--threads",
                       "{threads}"],
    "paicad_tag": ["{paicad}", "shell", "tag", "--cad", "{cad}", "--features", "{features}", "--assem-dir",
                   "{assem_dir}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}", "--body-map", "{body_map?}",
                   "--options", "{options?}", "--threads", "{threads}"],
    "paicad_grid": ["{paicad}", "shell", "view", "grid", "--cad", "{cad}", "--features", "{features}", "--cells",
                    "{cells}", "--thumb-options", "{thumb}", "--fixed-dir", "{fixed_dir}", "--out-dir", "{out_dir}",
                    "--options", "{options?}", "--threads", "{threads}"],
    "paicad_run": ["{paicad}", "shell", "run", "--cad", "{cad}", "--features", "{features}", "--values", "{values}",
                   "--assem-dir", "{assem_dir}", "--tag-dir", "{tag_dir}", "--fixed-dir", "{fixed_dir}",
                   "--update-dir", "{update_dir}", "--morph-dir", "{morph_dir}", "--check-dir", "{check_dir}",
                   "--out-files-dir", "{out_files_dir}", "--body-map", "{body_map?}", "--options", "{options?}",
                   "--threads", "{threads}"],
    "paicad_update": ["{paicad}", "shell", "update", "--cad", "{cad}", "--features", "{features}", "--values",
                      "{values}", "--out-dir", "{out_dir}", "--options", "{options?}", "--threads", "{threads}"],
}


def _deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def settings(cfg: dict | None = None) -> dict:
    """설정 dict(전체 설정 또는 ``bead_doe`` 절) → 기본값 위에 합친 bead_doe 설정.

    전체 설정에 ``bead_doe`` 절이 없으면 enabled False(계약 §14 "섹션 없으면 enabled: false")."""
    if cfg is None:
        return copy.deepcopy(DEFAULTS)
    if not isinstance(cfg, dict):
        raise EslError("CONFIG_INVALID", "bead_doe 설정은 매핑이어야 함")
    if "bead_doe" in cfg:
        sect = cfg["bead_doe"]
        if sect is None:
            return copy.deepcopy(DEFAULTS)
        if not isinstance(sect, dict):
            raise EslError("CONFIG_INVALID", "bead_doe 절은 매핑이어야 함")
        return _deep_merge(DEFAULTS, sect)
    if any(k in cfg for k in ("opt_run", "commands", "upload", "worker")):
        return copy.deepcopy(DEFAULTS)              # 전체 설정인데 bead_doe 절 없음 → 비활성
    return _deep_merge(DEFAULTS, cfg)


def opt_settings(cfg: dict | None = None) -> dict:
    """재사용 키(opt_run.size·keepout·solver·check·grid)를 담은 opt_run 설정."""
    from esl.opt import settings as _opt
    return _opt(cfg if isinstance(cfg, dict) and "opt_run" in cfg else None)


def commands(cfg: dict | None = None) -> dict:
    """paicad argv 템플릿(설정 ``commands.paicad_*`` 우선, 없으면 기본값 거울)."""
    out = copy.deepcopy(DEFAULT_COMMANDS)
    c = (cfg or {}).get("commands") if isinstance(cfg, dict) else None
    for k, v in (c or {}).items():
        if k in out:
            if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                raise EslError("CONFIG_INVALID", f"commands.{k} 는 문자열 목록")
            out[k] = list(v)
    return out


# ---------------------------------------------------------------- 자료 파일(원본 1곳)
def _read_resource(path: str, what: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise EslError("CONFIG_INVALID", f"{what} 를 읽을 수 없음: {path}: {exc}") from None


def validate_messages(obj) -> dict:
    """``doe_messages.json`` 스키마: {version, paicad_codes{paicad 코드: 플랫폼 코드}, exit_category{종료: 코드},
    messages{코드: 문구}} — paicad_codes·exit_category 의 모든 플랫폼 코드에 문구가 있어야 함."""
    def bad(msg):
        raise EslError("CONFIG_INVALID", f"doe_messages: {msg}")
    if not isinstance(obj, dict):
        bad("최상위는 객체")
    if not isinstance(obj.get("version"), str) or not obj["version"]:
        bad("version(문자열) 필요")
    msgs = obj.get("messages")
    if not isinstance(msgs, dict) or not msgs or not all(isinstance(k, str) and isinstance(v, str) and v
                                                         for k, v in msgs.items()):
        bad("messages 는 {코드: 문구} (비어 있지 않음)")
    pc = obj.get("paicad_codes")
    if not isinstance(pc, dict) or not pc or not all(isinstance(k, str) and isinstance(v, str) for k, v in pc.items()):
        bad("paicad_codes 는 {paicad 코드: 플랫폼 코드}")
    ec = obj.get("exit_category")
    if not isinstance(ec, dict) or "other" not in ec or not all(isinstance(v, str) for v in ec.values()):
        bad("exit_category 는 {종료코드: 플랫폼 코드, other: …}")
    for k in ec:
        if k != "other" and not k.isdigit():
            bad(f"exit_category 키 {k!r} 는 정수 문자열 또는 other")
    missing = sorted({v for v in list(pc.values()) + list(ec.values()) if v not in msgs})
    if missing:
        bad(f"문구 없는 플랫폼 코드: {missing}")
    return obj


_MSG_CACHE: dict = {}


def load_messages(path: str | None = None) -> dict:
    p = path or MESSAGES_PATH
    if p not in _MSG_CACHE:
        _MSG_CACHE[p] = validate_messages(_read_resource(p, "doe_messages"))
    return _MSG_CACHE[p]


def message(code: str, path: str | None = None) -> str:
    """플랫폼 코드 → 사용자 문구(없으면 코드 그대로)."""
    return load_messages(path)["messages"].get(code, code)


def validate_method_sources(obj) -> dict:
    """``doe_method_sources.json`` 스키마: {version, summary_ko[2..4], methods{lhs,halton,fullfact,score,sensitivity},
    limits_ko[≥1], sources[{title, authors?, url?, note?}]}."""
    def bad(msg):
        raise EslError("CONFIG_INVALID", f"doe_method_sources: {msg}")
    if not isinstance(obj, dict):
        bad("최상위는 객체")
    if not isinstance(obj.get("version"), str) or not obj["version"]:
        bad("version(문자열) 필요")
    s = obj.get("summary_ko")
    if not isinstance(s, list) or not 2 <= len(s) <= 4 or not all(isinstance(x, str) and x for x in s):
        bad("summary_ko 는 문자열 2~4개")
    m = obj.get("methods")
    need = {"lhs", "halton", "fullfact", "score", "sensitivity"}
    if not isinstance(m, dict) or not need <= set(m) or not all(isinstance(m[k], str) and m[k] for k in need):
        bad(f"methods 는 {sorted(need)} 한 줄씩")
    lim = obj.get("limits_ko")
    if not isinstance(lim, list) or not lim or not all(isinstance(x, str) and x for x in lim):
        bad("limits_ko 는 문자열 1개 이상")
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
    return validate_method_sources(_read_resource(path or METHOD_SOURCES_PATH, "doe_method_sources"))


def sources_ref(ms: dict) -> str:
    return f"doe_method_sources/{ms['version']}"
