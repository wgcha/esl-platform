"""색 지도 공용 자원 읽기 — ``resources/colormaps.json`` 읽기 전용 (v0.25.1, 계약 esl_view3d_scene_legend.md §5.8, D-0.25.1-VL-14).

파이썬에서 색 지도 자원을 여는 **유일한** 모듈(TS 쪽 짝 = ``frontend/src/lib/colormap.ts``). 정점(RGB) 리터럴은 자원에만 있다 —
호출부는 역할(``seq``·``div``·``region``)로 지도를 고르고 정점·지도 이름을 적지 않는다. ``esl.doe``·``esl.view3d`` 를 import 하지
않는다(순수 — numpy·json 만). 쓰기 없음.

보간 규칙(TS 와 같은 식 — 반올림까지, §5.8): ``s = t·(n−1)``(t 를 [0,1] 로 자름, NaN = 0), ``i = min(floor(s), n−2)``,
``f = s − i``, 채널 = ``floor(a + (b − a)·f + 0.5)``. 정점은 같은 간격(i/(n−1)).
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

from esl.errors import EslError

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resources")
COLORMAPS_PATH = os.path.join(RESOURCES, "colormaps.json")
SCHEMA = "esl/colormaps/1"
INTERP = "srgb-linear"
KINDS = ("seq", "div", "class")
SPECIALS = ("nan", "out", "none")

_CACHE: dict[str, dict] = {}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _bad(msg: str):
    raise EslError("CONFIG_INVALID", f"colormaps: {msg}")


def _rgb_list(v, what: str) -> list[int]:
    if (not isinstance(v, list) or len(v) != 3
            or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in v)):
        _bad(f"{what} 는 [r, g, b] 정수 0..255")
    return [int(c) for c in v]


def _validate(doc) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        _bad(f"schema 는 {SCHEMA!r}")
    if doc.get("interp") != INTERP:
        _bad(f"interp 는 {INTERP!r}")
    maps = doc.get("maps")
    if not isinstance(maps, dict) or not maps:
        _bad("maps 는 {이름: 지도}")
    out_maps: dict[str, dict] = {}
    for name, m in maps.items():
        if not isinstance(m, dict) or m.get("kind") not in KINDS:
            _bad(f"maps.{name}.kind 는 {'|'.join(KINDS)}")
        stops = m.get("stops")
        if not isinstance(stops, list) or len(stops) < 2:
            _bad(f"maps.{name}.stops 는 정점 2개 이상")
        st = [_rgb_list(s, f"maps.{name}.stops[{k}]") for k, s in enumerate(stops)]
        if m["kind"] == "div":                     # 0 중심 정점이 있어야 함(정점 수 홀수 · center 0.5)
            if m.get("center") != 0.5 or len(st) % 2 == 0:
                _bad(f"maps.{name}: kind div 는 center 0.5 · 정점 수 홀수")
        chk = m.get("check")
        if not isinstance(chk, str) or not _HEX64.match(chk):
            _bad(f"maps.{name}.check 는 sha256 16진 64자")
        out_maps[name] = {"name": str(name), "kind": m["kind"], "stops": st, "check": chk,
                          **({"center": 0.5} if m["kind"] == "div" else {})}
    roles = doc.get("roles")
    if not isinstance(roles, dict) or not roles or not all(isinstance(v, str) and v in out_maps for v in roles.values()):
        _bad("roles 는 {역할: 지도 이름}(maps 에 있는 이름)")
    sp = doc.get("special")
    if not isinstance(sp, dict) or any(k not in sp for k in SPECIALS):
        _bad(f"special 은 {', '.join(SPECIALS)} 를 모두 가짐")
    special = {str(k): _rgb_list(v, f"special.{k}") for k, v in sp.items()}
    return {"schema": SCHEMA, "interp": INTERP, "maps": out_maps, "roles": dict(roles), "special": special}


def load(path: str | None = None) -> dict:
    """자원 1회 읽기·검사(캐시) → {schema, interp, maps{이름: {name, kind, stops, check, center?}}, roles, special}.
    못 읽음·형식 오류(스키마·정점 수·div center) = CONFIG_INVALID."""
    p = path or COLORMAPS_PATH
    if p not in _CACHE:
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            raise EslError("CONFIG_INVALID", f"colormaps 를 읽을 수 없음: {p}: {exc}") from None
        _CACHE[p] = _validate(doc)
    return _CACHE[p]


def map_for(role: str, path: str | None = None) -> dict:
    """역할(seq·div·region) → 지도 {name, kind, stops, check, center?}. 없는 역할 = CONFIG_INVALID."""
    doc = load(path)
    name = doc["roles"].get(role)
    if name is None:
        _bad(f"역할 {role!r} 없음(roles: {', '.join(sorted(doc['roles']))})")
    return doc["maps"][name]


def rgb(cmap: dict, t) -> np.ndarray:
    """t(스칼라·배열, 0..1) → (…, 3) uint8. 범위 밖 = 자름, NaN = t 0. 보간 = 모듈 설명의 규칙(TS 와 같은 바이트)."""
    stops = np.asarray(cmap["stops"], dtype=np.float64)
    n = stops.shape[0]
    tt = np.asarray(t, dtype=np.float64)
    tt = np.clip(np.where(np.isnan(tt), 0.0, tt), 0.0, 1.0)
    s = tt * (n - 1)
    i = np.minimum(np.floor(s).astype(np.int64), n - 2)
    f = (s - i)[..., None]
    a, b = stops[i], stops[i + 1]
    return np.floor(a + (b - a) * f + 0.5).astype(np.uint8)


def css(cmap: dict, t: float) -> str:
    """t(스칼라) → 'rgb(r,g,b)'."""
    r, g, b = (int(c) for c in rgb(cmap, float(t)))
    return f"rgb({r},{g},{b})"


def table(cmap: dict, n: int = 256) -> np.ndarray:
    """t = k/(n−1)(k = 0…n−1) 색표 (n, 3) uint8. n = 256 의 768바이트 sha256 = 자원 ``check``(V-0251-38)."""
    n = int(n)
    if n < 2:
        raise ValueError("n ≥ 2")
    return rgb(cmap, np.arange(n, dtype=np.float64) / (n - 1))


def special(name: str, path: str | None = None) -> tuple[int, int, int]:
    """특수 색(nan = 계산 불가 · out = 범위 밖 · none = 영향 없음) → (r, g, b)."""
    sp = load(path)["special"]
    if name not in sp:
        _bad(f"special {name!r} 없음")
    r, g, b = sp[name]
    return (r, g, b)


def as_json(roles=("seq", "div"), path: str | None = None) -> dict:
    """보고서 JS 에 넣을 정점 묶음 {역할: {name, kind, stops, center?}} (+ interp). JS 는 이것만 읽는다(정점 리터럴 없음)."""
    out: dict = {"interp": load(path)["interp"]}
    for r in roles:
        m = map_for(r, path)
        out[r] = {"name": m["name"], "kind": m["kind"], "stops": [list(s) for s in m["stops"]],
                  **({"center": m["center"]} if "center" in m else {})}
    return out
