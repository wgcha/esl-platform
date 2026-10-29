"""DOE 생성 (계약 esl_bead_doe.md BD-D-7·8, §5). API(``POST …/matrix``·``preview``)와 워커(BD_MATRIX)가 같은 함수를 쓴다.

- 입력 ``DoeSpec {method, n?, levels?, seed?, params:[{name, lo, hi}]}`` + 준비 변수 표(``paicad_io.params_table``).
- 변수 순서 = 이름 사전순(요청 순서와 무관 → 같은 (spec, seed) 는 같은 행렬·같은 sha256).
- ``lhs``: ``random.Random(seed)`` — 변수 순서대로 층 순열(shuffle), 그다음 행 우선(안 i → 변수 j)으로 층 안 균일 난수.
- ``halton``: ``scipy.stats.qmc.Halton(d, scramble=True, seed=numpy.random.default_rng(seed))``.
- ``fullfact``: 변수별 등간격 수준(기본 ``doe.levels_default``) 곱(itertools.product, 변수 순서).
- 값 = lo + u·(hi − lo) → ``doe.round_mm`` 반올림 → 중복·공칭 동일 안 제거(먼저 나온 것 유지) → d001… 번호.
  공칭 = d000(항상 포함, values = 포함 변수의 공칭값). 포함 안 한 변수는 값 파일에 넣지 않음(= 공칭).
- 행렬 sha256 = {spec(정규화), designs} 정렬 키 JSON(구분자 고정)의 sha256.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random

import numpy as np

from esl.doe import METHODS, PARAM_TYPES
from esl.errors import EslError

_POSITIVE = ("D", "W")              # 물리 하한(> 0)이 있는 변수 종류
_FEAS_TOL = 1e-9


def _num(x) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(float(x))


def round_to(v: float, q: float) -> float:
    """q 격자 반올림(부동소수 꼬리 제거, −0 → 0)."""
    if q <= 0:
        return float(v)
    nd = max(0, -int(math.floor(math.log10(q))) + 2)
    r = round(round(float(v) / q) * q, nd)
    return 0.0 if r == 0 else r


def _table(params_table) -> dict:
    out = {}
    for p in params_table or []:
        out[str(p["name"])] = p
    return out


def default_params(params_table, cfg: dict) -> list[dict]:
    """기본 포함 변수(BD-D-7): ``use_default`` 이고 종류 ∈ ``doe.default_types``, 범위 = feasible."""
    types = set(cfg["doe"]["default_types"])
    out = []
    for p in sorted(params_table or [], key=lambda r: r["name"]):
        if not p.get("use_default") or p.get("type") not in types:
            continue
        rng = p.get("feasible") or p.get("default_range")
        if not rng:
            continue
        out.append({"name": p["name"], "lo": float(rng[0]), "hi": float(rng[1])})
    return out


def default_spec(params_table, cfg: dict) -> dict:
    d = cfg["doe"]
    sp = {"method": d["default_method"], "seed": int(d["seed"]), "params": default_params(params_table, cfg)}
    if sp["method"] == "fullfact":
        sp["levels"] = int(d["levels_default"])
    else:
        sp["n"] = int(d["default_n"])
    return sp


def normalize_spec(spec: dict, params_table, cfg: dict) -> tuple[dict, list[dict]]:
    """검증·정규화(§5). 반환 (정규화 spec, warnings[{code, name}]). 오류는 EslError(422 코드)."""
    if not isinstance(spec, dict):
        raise EslError("DOE_RANGE_INVALID", "spec 은 객체")
    d, lim = cfg["doe"], cfg["limits"]
    method = spec.get("method", d["default_method"])
    if method not in METHODS:
        raise EslError("DOE_RANGE_INVALID", f"method 는 {'·'.join(METHODS)} (값 {method!r})")
    seed = spec.get("seed", d["seed"])
    if seed is None:
        seed = d["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= int(lim["seed_max"]):
        raise EslError("DOE_RANGE_INVALID", f"seed 는 0..{lim['seed_max']} 정수 (값 {seed!r})")
    params = spec.get("params")
    if not isinstance(params, list) or not params:
        raise EslError("DOE_NO_PARAMS", "포함 변수(params)가 1개 이상 필요")
    tab = _table(params_table)
    seen, rows, warns = set(), [], []
    for p in params:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            raise EslError("DOE_PARAM_UNKNOWN", f"변수 항목 형식 오류: {p!r}")
        name = p["name"]
        if name not in tab:
            raise EslError("DOE_PARAM_UNKNOWN", f"준비 변수 표에 없는 변수: {name}")
        if name in seen:
            raise EslError("DOE_PARAM_UNKNOWN", f"변수가 두 번 지정됨: {name}")
        seen.add(name)
        lo, hi = p.get("lo"), p.get("hi")
        if not (_num(lo) and _num(hi)):
            raise EslError("DOE_RANGE_INVALID", f"{name}: lo·hi 는 유한한 수")
        lo, hi = float(lo), float(hi)
        if not lo < hi:
            raise EslError("DOE_RANGE_INVALID", f"{name}: lo {lo} < hi {hi} 이어야 함")
        typ = tab[name].get("type")
        if typ in _POSITIVE and lo <= 0:
            raise EslError("DOE_RANGE_INVALID", f"{name}: 깊이·폭 하한은 0 보다 커야 함 (lo {lo})")
        fe = tab[name].get("feasible")
        if fe and (lo < float(fe[0]) - _FEAS_TOL or hi > float(fe[1]) + _FEAS_TOL):
            warns.append({"code": "RANGE_OUTSIDE_FEASIBLE", "name": name, "feasible": [float(fe[0]), float(fe[1])]})
        rows.append({"name": name, "lo": lo, "hi": hi})
    rows.sort(key=lambda r: r["name"])
    warns.sort(key=lambda w: w["name"])
    out = {"method": method, "seed": int(seed), "params": rows}
    k = len(rows)
    maxd = int(cfg["max_designs"])
    if method == "fullfact":
        lv = spec.get("levels", d["levels_default"])
        if lv is None:
            lv = d["levels_default"]
        if isinstance(lv, bool) or not isinstance(lv, int) or not int(lim["levels_min"]) <= lv <= int(d["levels_max"]):
            raise EslError("DOE_RANGE_INVALID", f"levels 는 {lim['levels_min']}..{d['levels_max']} 정수 (값 {lv!r})")
        out["levels"] = int(lv)
        count = lv ** k
    else:
        n = spec.get("n", d["default_n"])
        if n is None:
            n = d["default_n"]
        if isinstance(n, bool) or not isinstance(n, int) or n < int(lim["n_min"]):
            raise EslError("DOE_RANGE_INVALID", f"n 은 {lim['n_min']}..{maxd} 정수 (값 {n!r})")
        out["n"] = int(n)
        count = n
    if count + 1 > maxd:
        raise EslError("DOE_TOO_LARGE", f"안 수 {count} + 공칭 1 > 상한 {maxd} (bead_doe.max_designs)")
    return out, warns


def _halton(k: int, n: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc
    try:
        eng = qmc.Halton(d=k, scramble=True, rng=np.random.default_rng(seed))
    except TypeError:                                   # scipy < 1.15
        eng = qmc.Halton(d=k, scramble=True, seed=np.random.default_rng(seed))
    return np.asarray(eng.random(n), dtype=np.float64)


def unit_samples(spec: dict) -> np.ndarray:
    """정규화 spec → (n, k) 단위 표본 u ∈ [0, 1] (변수 순서 = spec.params 순서)."""
    k = len(spec["params"])
    m = spec["method"]
    if m == "lhs":
        n = int(spec["n"])
        rng = random.Random(int(spec["seed"]))
        perms = []
        for _ in range(k):
            p = list(range(n))
            rng.shuffle(p)
            perms.append(p)
        u = np.empty((n, k))
        for i in range(n):
            for j in range(k):
                u[i, j] = (perms[j][i] + rng.random()) / n
        return u
    if m == "halton":
        return _halton(k, int(spec["n"]), int(spec["seed"]))
    if m == "fullfact":
        lv = int(spec["levels"])
        grid = [j / (lv - 1) for j in range(lv)]
        return np.array(list(itertools.product(grid, repeat=k)), dtype=np.float64).reshape(-1, k)
    raise EslError("DOE_RANGE_INVALID", f"method: {m}")


def nominal_values(spec: dict, params_table) -> dict:
    tab = _table(params_table)
    return {p["name"]: float(tab[p["name"]]["nominal"]) for p in spec["params"]}


def matrix_sha256(spec: dict, designs: list[dict]) -> str:
    doc = {"spec": spec, "designs": [{"id": d["id"], "values": d["values"]} for d in designs]}
    s = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def generate(spec: dict, params_table, cfg: dict) -> dict:
    """DoeMatrixOut {spec, matrix_sha256, designs[{id, values}] (d000 포함), n_designs, dropped_duplicates, warnings}."""
    ns, warns = normalize_spec(spec, params_table, cfg)
    q = float(cfg["doe"]["round_mm"])
    names = [p["name"] for p in ns["params"]]
    lo = np.array([p["lo"] for p in ns["params"]])
    hi = np.array([p["hi"] for p in ns["params"]])
    u = unit_samples(ns)
    vals = lo[None, :] + u * (hi - lo)[None, :]
    nom = nominal_values(ns, params_table)
    nom_key = tuple(round_to(nom[n], q) for n in names)
    seen = {nom_key}
    designs = [{"id": "d000", "values": {n: float(nom[n]) for n in names}}]
    dropped = 0
    for row in vals:
        key = tuple(round_to(v, q) for v in row)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        designs.append({"id": f"d{len(designs):03d}", "values": dict(zip(names, key))})
    return {"spec": ns, "matrix_sha256": matrix_sha256(ns, designs), "designs": designs, "n_designs": len(designs),
            "dropped_duplicates": dropped, "warnings": warns}


# ---------------------------------------------------------------- 미리보기·실행 입력 파일
def values_doc(values: dict) -> dict:
    """paicad 값 파일 {schema_version: 1, values: {name: number}} (포함 변수만, 나머지 = 공칭)."""
    return {"schema_version": 1, "values": {k: float(v) for k, v in sorted(values.items())}}


def cells_doc(matrix: dict) -> dict:
    """``cells.json`` (d000 제외 — 공칭 썸네일은 grid nominal)."""
    return {"schema_version": 1, "cells": [{"id": d["id"], "values": {k: float(v) for k, v in d["values"].items()}}
                                           for d in matrix["designs"] if d["id"] != "d000"]}


def thumb_options(cfg: dict, frame: dict, spec: dict, params_table) -> dict:
    """``thumb_options.json``: view_dir auto = frame n 을 −η 쪽으로 ``preview.tilt_deg`` 기울임,
    disp_range_mm auto = [0, max(D 변수 |hi−공칭|, |lo−공칭|), 최소 ``limits.min_disp_range_mm``]."""
    pv = cfg["preview"]
    vd = pv["view_dir"]
    if vd == "auto":
        t = math.radians(float(pv["tilt_deg"]))
        n = np.asarray(frame["n"], dtype=np.float64)
        e = np.asarray(frame["e_eta"], dtype=np.float64)
        v = math.cos(t) * n - math.sin(t) * e
        vd = [float(x) for x in v / np.linalg.norm(v)]
    dr = pv["disp_range_mm"]
    if dr == "auto":
        tab = _table(params_table)
        m = float(cfg["limits"]["min_disp_range_mm"])
        for p in spec["params"]:
            r = tab.get(p["name"]) or {}
            if r.get("type") == "D":
                nomv = float(r["nominal"])
                m = max(m, abs(p["hi"] - nomv), abs(p["lo"] - nomv))
        dr = [0.0, float(m)]
    return {"schema_version": 1, "w": int(pv["w"]), "h": int(pv["h"]), "view_dir": [float(x) for x in vd],
            "margin": float(pv["margin"]), "disp_range_mm": [float(dr[0]), float(dr[1])], "colormap": "turbo16",
            "nominal_ghost": True, "edges": False}


def param_type(name: str) -> str | None:
    """``<COMP>_BEAD_<D|U|V|W>_<k>`` → 종류 문자(없으면 None)."""
    parts = str(name).split("_")
    for i in range(len(parts) - 2, 0, -1):
        if parts[i - 1] == "BEAD" and parts[i] in PARAM_TYPES:
            return parts[i]
    return None
