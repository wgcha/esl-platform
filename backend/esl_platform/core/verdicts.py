"""④ 검증 판정 값 — 통과 판정 한 곳(계약 esl_validate_tiers.md §4.1, v0.24.5).

CONDITIONAL(조건부 PASS)은 게이트(라이브러리 등록·적격·재검증 승격·run_all·CLI·내보내기)에서 통과로 처리하고 표식만 단다.
게이트 지점은 ``verdict == "PASS"`` 직접 비교 대신 ``is_passing`` 만 쓴다(정적 시험 V-0245-VT-10). 코어 ``esl.val_metrics.PASSING`` 과
같은 값(시험으로 고정). 이 모듈은 의존이 없다(워커·API·run_all 공용).
"""

from __future__ import annotations

from typing import Any

PASSING: tuple[str, ...] = ("PASS", "CONDITIONAL")
VERDICTS: tuple[str, ...] = ("PASS", "CONDITIONAL", "FAIL", "UNDETERMINED")
VERDICT_SCHEMES: tuple[str, ...] = ("disp_primary/1", "disp_primary/2")      # validations.scheme 허용값(0008·0017)


def is_passing(v: Any) -> bool:
    return v in PASSING
