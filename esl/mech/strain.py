"""등가변형률 (계약 esl_core.md §4).

입력은 면내 텐서 성분 (exx, eyy, exy=γ/2). 비압축 가정(ezz = −(exx+eyy)) von Mises 등가
총변형률  ε_eq = sqrt(2/3 ε:ε) = (2/√3)·sqrt(exx² + eyy² + exx·eyy + exy²).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

_C = 2.0 / np.sqrt(3.0)


def eps_eq(eps) -> np.ndarray:
    e = np.asarray(eps)
    if e.shape[-1] != 3:
        raise EslError("INPUT_INVALID", "eps 마지막 축은 (exx, eyy, exy)")
    e = e.astype(np.float64, copy=False)
    xx, yy, xy = e[..., 0], e[..., 1], e[..., 2]
    return _C * np.sqrt(np.maximum(xx * xx + yy * yy + xx * yy + xy * xy, 0.0))


def eps_eq_max_layer(eps) -> np.ndarray:
    """eps (..., L, 3) → (...) layer 최대 ε_eq."""
    e = np.asarray(eps)
    if e.ndim < 2:
        raise EslError("INPUT_INVALID", "eps 는 (..., L, 3)")
    return eps_eq(e).max(axis=-1)
