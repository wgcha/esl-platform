"""작업 유형(계약 esl_platform_p1b.md §2 + esl_p2_library.md §11). 전부 INTERNAL: 코어 단계 step(자식 프로세스) +
등록 step(DB).

- CASE_REPORT(LIGHT): 코어 ``report`` 단계 → ``<case>/07_report/report.html``. VALIDATE 성공 시 자동 큐(``report.auto``).
- LIB_ANALYZE(SLOT): 라이브러리 종합분석 → 덱(대상 있을 때) → 보고서 → DB 요약. Case 가 없다(case_id NULL,
  analysis_id 필수). 산출물 ``<esl_root>/_analysis/<analysis_id>/``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    key: str
    core_stage: str | None  # None = 플랫폼 등록 step(워커 프로세스 안)


@dataclass(frozen=True)
class JobTypeDef:
    job_type: str
    stage: int  # UI 단계 1~6, 7 = Case 보고서, 8 = 라이브러리 분석
    lane: str  # SLOT | LIGHT
    steps: tuple[StepDef, ...]


JOB_TYPES: dict[str, JobTypeDef] = {
    "CASE_EXTRACT": JobTypeDef("CASE_EXTRACT", 1, "SLOT", (
        StepDef("EXTRACT", "extract"), StepDef("TSTAR_SCAN", "tstar"), StepDef("EXTRACT_REGISTER", None))),
    "ESL_SOLVE": JobTypeDef("ESL_SOLVE", 4, "SLOT", (StepDef("ESL", "esl"), StepDef("ESL_REGISTER", None))),
    "VALIDATE": JobTypeDef("VALIDATE", 5, "SLOT", (StepDef("VALIDATE", "validate"), StepDef("VAL_REGISTER", None))),
    "EXPORT": JobTypeDef("EXPORT", 6, "LIGHT", (StepDef("EXPORT", "export"), StepDef("EXP_REGISTER", None))),
    "CASE_REPORT": JobTypeDef("CASE_REPORT", 7, "LIGHT", (StepDef("REPORT", "report"),
                                                          StepDef("REPORT_REGISTER", None))),
    "LIB_ANALYZE": JobTypeDef("LIB_ANALYZE", 8, "SLOT", (
        StepDef("ANALYZE", "lib_analyze"), StepDef("OPTDECK", "lib_optdeck"), StepDef("REPORT", "lib_report"),
        StepDef("LIB_REGISTER", None))),
}
CASE_JOB_TYPES = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT")
LIB_STAGES = ("lib_analyze", "lib_optdeck", "lib_report")

EXPORT_TARGETS = ("radioss_inc", "fem", "csv")
