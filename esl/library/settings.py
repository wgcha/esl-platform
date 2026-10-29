"""라이브러리 설정 로더 (config/library.example.yaml). 모든 키 필수, 알 수 없는 키는 CONFIG_INVALID."""
from __future__ import annotations

import copy
import math
import os
import re

import yaml

from esl.errors import EslError

ENV_CONFIG = "ESL_LIBRARY_CONFIG"


def _bad(k, m):
    return EslError("CONFIG_INVALID", f"{k}: {m}")


def _num(lo=None, hi=None, lo_open=False):
    def chk(k, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise _bad(k, f"유한 실수 (값 {v!r})")
        if lo is not None and (v <= lo if lo_open else v < lo):
            raise _bad(k, f"{'>' if lo_open else '≥'} {lo} (값 {v})")
        if hi is not None and v > hi:
            raise _bad(k, f"≤ {hi} (값 {v})")
    return chk


def _int(lo=None):
    def chk(k, v):
        if isinstance(v, bool) or not isinstance(v, int) or (lo is not None and v < lo):
            raise _bad(k, f"정수 ≥ {lo} (값 {v!r})")
    return chk


def _enum(*vals):
    def chk(k, v):
        if v not in vals:
            raise _bad(k, f"{list(vals)} 중 하나 (값 {v!r})")
    return chk


def _bool(k, v):
    if not isinstance(v, bool):
        raise _bad(k, f"true/false (값 {v!r})")


def _str(k, v):
    if not isinstance(v, str) or not v.strip():
        raise _bad(k, f"비어 있지 않은 문자열 (값 {v!r})")


def _opt(f):
    def chk(k, v):
        if v is not None:
            f(k, v)
    return chk


def _regex(k, v):
    try:
        re.compile(v)
    except (re.error, TypeError) as exc:
        raise _bad(k, f"정규식 오류 {exc}") from None


def _regex_list(k, v):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not v:
        raise _bad(k, "정규식 문자열 또는 목록")
    for i, x in enumerate(v):
        _regex(f"{k}[{i}]", x)


def _vec3(k, v):
    if not isinstance(v, list) or len(v) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
        raise _bad(k, f"[x, y, z] (값 {v!r})")
    if all(float(x) == 0 for x in v):
        raise _bad(k, "영벡터")


def _int_list(k, v):
    if not isinstance(v, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        raise _bad(k, f"정수 목록 (값 {v!r})")


def _str_list(k, v):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise _bad(k, f"문자열 목록 (값 {v!r})")


def _bounds(k, v):
    if not isinstance(v, list) or len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
        raise _bad(k, "[LB, UB]")
    if not -1.0 <= v[0] < v[1] <= 1.0:
        raise _bad(k, f"-1 ≤ LB < UB ≤ 1 (값 {v})")


def _fmt(k, v):
    try:
        if float(v.format(1.0)) != 1.0:
            raise ValueError
    except (ValueError, AttributeError, IndexError, KeyError):
        raise _bad(k, f"실수 format (값 {v!r})") from None


def _dtpg_flag(k, v):
    if not isinstance(v, str) or not (v == "" or v.isalpha()):
        raise _bad(k, f"빈 문자열 또는 영문 라벨 (값 {v!r})")


def _dtpg_fields(k, v):
    from esl.library.optdeck import DTPG_REQUIRED, DTPG_TOKENS

    if (not isinstance(v, list) or any(not isinstance(x, str) or x.upper() not in DTPG_TOKENS for x in v)
            or len(v) > 8 or any([x.upper() for x in v].count(t) != 1 for t in DTPG_REQUIRED)):
        raise _bad(k, f"{list(DTPG_TOKENS)} 목록(≤8칸, MW·ANG·BF·HGT·SKIP 각 1번) (값 {v!r})")


def _coarsen(k, v):
    if v is not False and v != "half":
        raise _bad(k, f"false | half (값 {v!r})")


SCHEMA = {
    "schema_version": _enum(1),
    "library": {
        "ista6": _opt(_str), "scene_regex": _opt(_regex_list), "inch_regex": _opt(_regex),
        "optional_fields": _str_list,
        "axis_ref": {"xi": _vec3, "eta": _vec3, "n": _opt(_vec3)},
        "grid": {"nx": _int(1), "ny": _int(1)}, "top_nodes": _int(1), "require_pass": _bool,
    },
    "analysis": {
        "svd_energy": _num(0.0, 1.0, lo_open=True), "n_representative": _int(1), "seed": _int(0),
        "n_init": _int(1), "worst_case": _bool, "normalization": _enum("none", "mass", "inch2"),
        "moment_scale": _enum("preserve", "geometric"), "equilibrate": _bool,
        "distance": _enum("pattern", "magnitude"),
        "svd_feature": _enum("cell", "nodal"),
    },
    "optdeck": {
        "design_pids": _opt(_int_list), "nondesign_pids": _int_list, "nondesign_node_ids": _int_list,
        "nondesign_radius": _num(0.0),
        "bead": {"min_width": _num(0.0, lo_open=True), "height": _num(0.0, lo_open=True),
                 "angle": _num(0.0, 90.0, lo_open=True), "buffzone": _bool, "skip": _enum("BC", "NONE"),
                 "bounds": _bounds},
        "objective": _enum("minmax", "weighted"), "reference_compliance": _enum("none", "solve"),
        "beadfrac_max": _opt(_num(0.0, 1.0, lo_open=True)), "id_offset": _int(1), "num_format": _fmt,
        "force_zero_tol_rel": _num(0.0, 1.0), "card_format": _enum("free", "fixed"), "deck_name": _str,
        "nt": _int(1),
        "dtpg": {"bead_flag": _dtpg_flag, "bead_fields": _dtpg_fields, "draw": _enum("NORM", ""),
                 "pid_cont_col": _enum(2, 3)},
        "cases": _enum("all", "representative", "representative+worst"), "max_cases": _int(1),
        "solver": {"drill_factor": _num(0.0, 1.0, lo_open=True),
                   "backend": _enum("auto", "cholmod", "pardiso", "superlu", "iterative")},
    },
    "convergence": {"cos_min": _num(0.0, 1.0, lo_open=True), "rep_same": _bool, "min_nodes_per_cell": _int(0),
                    "coarsen": _coarsen},
}

# §12 에서 추가된 키: 이전 설정 파일(설치본 library.yaml 은 업데이트 때 덮어쓰지 않음)과 호환되도록 없으면 기본값으로 채운다.
# (그 밖의 키는 여전히 모두 필수.)
# §12.4: convergence 기본 cos_min 0.95, min_nodes_per_cell 64, coarsen false (블록이 있어도 빠진 키는 채움).
# v0.8.0: optdeck.dtpg(DTPG 비드 줄 칸 배치 — OptiStruct Reference Guide DTPG 형식표, 이슈 #35).
_DTPG = {"bead_flag": "", "bead_fields": ["MW", "ANG", "BF", "HGT", "DRAW", "-", "-", "SKIP"], "draw": "NORM",
         "pid_cont_col": 3}
DEFAULTS = {("optdeck", "cases"): "all", ("optdeck", "max_cases"): 60,
            ("optdeck", "dtpg"): _DTPG, **{("optdeck", "dtpg", k): v for k, v in _DTPG.items()},
            ("convergence",): {"cos_min": 0.95, "rep_same": True, "min_nodes_per_cell": 64, "coarsen": False},
            ("convergence", "cos_min"): 0.95, ("convergence", "rep_same"): True,
            ("convergence", "min_nodes_per_cell"): 64, ("convergence", "coarsen"): False}


def fill_defaults(cfg):
    if not isinstance(cfg, dict):
        return cfg
    for path, v in DEFAULTS.items():
        node = cfg
        for k in path[:-1]:
            node = node.get(k) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and path[-1] not in node:
            node[path[-1]] = copy.deepcopy(v)
    return cfg


def _walk(schema, node, prefix):
    if not isinstance(node, dict):
        raise _bad(prefix or "<root>", "사전이어야 함")
    for k in node:
        if k not in schema:
            raise _bad(f"{prefix}{k}", "알 수 없는 키")
    for k, rule in schema.items():
        if k not in node:
            raise _bad(f"{prefix}{k}", "필수 키 누락")
        if isinstance(rule, dict):
            _walk(rule, node[k], f"{prefix}{k}.")
        else:
            rule(f"{prefix}{k}", node[k])


def validate(cfg: dict) -> dict:
    fill_defaults(cfg)
    _walk(SCHEMA, cfg, "")
    return cfg


def load(path: str | None = None) -> dict:
    """설정 + ISTA 6 표를 읽어 검증. 반환 cfg 에 ``_path``, ``_ista6`` 추가."""
    p = path or os.environ.get(ENV_CONFIG, "")
    if not p:
        raise EslError("CONFIG_INVALID", f"설정 파일 경로가 없음(--config 또는 env {ENV_CONFIG})")
    if not os.path.isfile(p):
        raise EslError("CONFIG_INVALID", f"설정 파일이 없음: {p}")
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            cfg = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise EslError("CONFIG_INVALID", f"설정 파일을 읽을 수 없음({p}): {exc}") from None
    validate(cfg)
    cfg["_path"] = os.path.abspath(p)
    cfg["_ista6"] = None
    ip = cfg["library"]["ista6"]
    if ip:
        ip = ip if os.path.isabs(ip) else os.path.join(os.path.dirname(os.path.abspath(p)), ip)
        if not os.path.isfile(ip):
            raise EslError("CONFIG_INVALID", f"library.ista6: 파일 없음 {ip}")
        with open(ip, "r", encoding="utf-8-sig") as fh:
            cfg["_ista6"] = load_ista6_dict(yaml.safe_load(fh), ip)
    return cfg


def load_ista6_dict(d, where="ista6") -> dict:
    if not isinstance(d, dict) or "faces" not in d:
        raise EslError("CONFIG_INVALID", f"{where}: faces 정의 없음")
    faces = {int(k): v for k, v in d["faces"].items()}
    if sorted(faces) != [1, 2, 3, 4, 5, 6]:
        raise EslError("CONFIG_INVALID", f"{where}: faces 는 1~6")
    d = dict(d)
    d["faces"] = faces
    return d


def scene_rules(cfg: dict) -> dict:
    lib = cfg["library"]
    return {"scene_regex": lib["scene_regex"], "inch_regex": lib["inch_regex"],
            "optional_fields": lib["optional_fields"], "ista6": cfg.get("_ista6")}
