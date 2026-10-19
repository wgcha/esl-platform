"""인치 간 하중 크기 정규화 (계약 esl_p2_library.md §0 Q3, §3).

라이브러리에는 절대값을 저장하고 집계 시 선택한다.

- ``none``  : 그대로 (factor 1)
- ``mass``  : F × m_target / m_source  (같은 낙하 높이·비슷한 감속도면 충격력 ∝ 질량)
- ``inch2`` : F × (inch_target / inch_source)²  (면적 비례)

``meta = {"source": {"mass":, "inch":}, "target": {"mass":, "inch":}}``. 필요한 값이 없거나 0 이하이면
``NORMALIZATION_META_MISSING``.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

MODES = ("none", "mass", "inch2")


def factor(mode: str, meta: dict | None) -> float:
    if mode not in MODES:
        raise EslError("INPUT_INVALID", f"normalization 은 {list(MODES)} 중 하나 (값 {mode!r})")
    if mode == "none":
        return 1.0
    key = "mass" if mode == "mass" else "inch"
    try:
        s = float(meta["source"][key])
        t = float(meta["target"][key])
    except (TypeError, KeyError, ValueError):
        raise EslError("NORMALIZATION_META_MISSING", f"normalization={mode}: source·target 의 {key} 가 필요") from None
    if not (np.isfinite(s) and np.isfinite(t)) or s <= 0 or t <= 0:
        raise EslError("NORMALIZATION_META_MISSING", f"normalization={mode}: {key} 는 양수 (source {s}, target {t})")
    return t / s if mode == "mass" else (t / s) ** 2


def scale(F, mode: str, meta: dict | None = None):
    """(F × factor, factor)."""
    k = factor(mode, meta)
    return np.asarray(F, dtype=np.float64) * k, k
