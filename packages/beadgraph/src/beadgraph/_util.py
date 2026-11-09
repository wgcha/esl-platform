"""small helpers: cfg merge, rounding (BG-D-12: 1e-3 mm), canonical JSON / sha256."""
from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np


def merge(a: dict, b: dict | None) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def merged_cfg(cfg: dict | None) -> dict:
    from .defaults import DEFAULTS
    c = merge(DEFAULTS, cfg or {})
    c.pop("enabled", None)                 # esl-only switch (select.graph.enabled) — not a classification key
    return _plain(c)


def _plain(o):
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, bool):
        return o
    if isinstance(o, int):
        return o
    if isinstance(o, float):
        return float(o)
    return o


def f(x, nd: int = 3) -> float:
    v = float(x)
    if not math.isfinite(v):
        return 0.0
    r = round(v, nd)
    return 0.0 if r == 0 else r


def f3(x) -> float:
    return f(x, 3)


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256_json(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def wendland(t):
    t = np.asarray(t, dtype=np.float64)
    return np.where(t < 1.0, (1.0 - t) ** 4 * (4.0 * t + 1.0), 0.0)
