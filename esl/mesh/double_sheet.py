"""판 앞뒷면 두 장 감지 — 메시로(계약 esl_tstar_manual_jig_force.md §4.4, D-0.25.2-17·18).

STEP 이 중립면 한 장이 아니라 판 앞뒷면 표면 두 장이면 마주 보는 평행 요소가 두께쯤 간격으로 짝을 이룬다. 요소를 인덱스 등간격으로
최대 ``sample_max`` 개 뽑아(결정적) 표본 요소(중심 c, 단위 법선 n, 변 길이 h)마다 짝(다른 요소 중 ① |n·n′| ≥ cos(normal_deg)
② 법선 방향 간격 g = |(c′−c)·n| ∈ [gap_min_t·t, gap_max_t·t] ③ 면내 어긋남 ‖(c′−c) − g·n‖ ≤ h)이 있는 비율 ``frac`` 과 간격 중앙값
``gap_mm`` 을 낸다. 리브·헤밍처럼 일부만 겹친 형상은 frac 이 작다. 판정(frac ≥ frac_warn → SHAPE_DOUBLE_SHEET)은 호출부.

모드 무관 독립 순수 모듈(AGENTS.md D-0.20.0-CODE): numpy·scipy.spatial 만, esl.doe 금지, 파일 IO·설정 해석 없음(값은 인수).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError


def detect(mesh: dict, t: float, *, gap_min_t: float, gap_max_t: float, normal_deg: float, sample_max: int) -> dict:
    """mesh = {x0 (N,3), conn (E,4)(삼각형 4번째 = 음수 또는 3번째 반복), elem_type (E,)(4 = 쿼드, 3 = 삼각)}, t = 판 두께(mm —
    호출부가 형상 두께 대표값). 반환 {frac, gap_mm(짝 간격 중앙값 — 짝 0 = None), n_sample}."""
    raise NotImplementedError("v0.25.2 C1 — 구현 중(접점 껍데기)")
