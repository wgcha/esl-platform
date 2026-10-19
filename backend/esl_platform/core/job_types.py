"""작업 유형(계약 esl_platform_p1b.md §2). 전부 INTERNAL: 코어 단계 step(자식 프로세스) + 등록 step(DB)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    key: str
    core_stage: str | None  # None = 플랫폼 등록 step(워커 프로세스 안)


@dataclass(frozen=True)
class JobTypeDef:
    job_type: str
    stage: int  # UI 단계 1~6
    lane: str  # SLOT | LIGHT
    steps: tuple[StepDef, ...]


JOB_TYPES: dict[str, JobTypeDef] = {
    "CASE_EXTRACT": JobTypeDef("CASE_EXTRACT", 1, "SLOT", (
        StepDef("EXTRACT", "extract"), StepDef("TSTAR_SCAN", "tstar"), StepDef("EXTRACT_REGISTER", None))),
    "ESL_SOLVE": JobTypeDef("ESL_SOLVE", 4, "SLOT", (StepDef("ESL", "esl"), StepDef("ESL_REGISTER", None))),
    "VALIDATE": JobTypeDef("VALIDATE", 5, "SLOT", (StepDef("VALIDATE", "validate"), StepDef("VAL_REGISTER", None))),
    "EXPORT": JobTypeDef("EXPORT", 6, "LIGHT", (StepDef("EXPORT", "export"), StepDef("EXP_REGISTER", None))),
}

EXPORT_TARGETS = ("radioss_inc", "fem", "csv")
