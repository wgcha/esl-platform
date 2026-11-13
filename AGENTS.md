# 작업 지침 (esl-platform)

계약 원본은 `docs/contracts/*.md`, 결정 기록은 `docs/decisions.md`. 충돌하면 계약이 우선한다.

## 코드 구조 원칙 (D-0.20.0-CODE, 2026-11-13)

- **둘 이상 모드(①②③④)가 쓰는 계산은 모드 무관 독립 모듈**로 둔다. 모듈은 `esl.doe` 를 import 하지 않고 파일 IO·설정 해석을 하지 않으며, 필요한 값은 인수로 받는다(예: `esl/doe/load_transfer.py`, `esl/doe/stiffness_metric.py`).
- **모드 차이는 선언형 계획 표 한 곳**에 열로 적는다(예: `esl/doe/transfer_plan.py` 의 `PLANS` — `reuse`·`mask`·`sm_ref`·`sm_rank` …). 호출하는 쪽(`stages.py`)은 계획 열만 읽고 시나리오 이름으로 분기하지 않는다. 새 계획 행은 모든 열을 채운다(빈 칸 = `CONFIG_INVALID`).
- 모드마다 다른 동작이 필요하면 먼저 계획 표에 열을 더하고, 그 열의 값으로 공용 함수를 고른다. 진단·결과 스키마는 모드 공통 1개.
- 값은 하드코딩하지 않는다: 기본값은 `esl/doe/__init__.py` DEFAULTS·backend pydantic·`config/*.example.yaml` 2개에 같은 이름으로 둔다.
