"""작업 유형(계약 esl_platform_p1b.md §2 + esl_p2_library.md §11). 전부 INTERNAL: 코어 단계 step(자식 프로세스) +
등록 step(DB).

- CASE_REPORT(LIGHT): 코어 ``report`` 단계 → ``<case>/07_report/report.html``. VALIDATE 성공 시 자동 큐(``report.auto``).
- LIB_ANALYZE(SLOT): 라이브러리 종합분석 → 덱(대상 있을 때) → 보고서 → DB 요약. Case 가 없다(case_id NULL,
  analysis_id 필수). 산출물 ``<esl_root>/_analysis/<analysis_id>/``.
- LIB_COMPARE(LIGHT, §12.2): 설계 버전 비교 → DB 요약. Case·분석이 없다(comparison_id 필수).
  산출물 ``<esl_root>/_compare/<comparison_id>/``(compare.json, report.html).
- OPT_RUN(SLOT, stage 10, 계약 esl_opt_run.md §6.1): 비드 최적화 서버 실행. 대상 = jobs.opt_run_id(case·분석·비교 NULL).
  산출물 ``<esl_root>/_opt/<opt_run_id>/``. OS_SOLVE(LOCAL, OptiStruct)·OPT_POST(LOCAL+코어, hw TCL 후처리) 는 워커가 실행.
- DOE_PREP·DOE_PREVIEW·DOE_RUN(SLOT, stage 11, 계약 esl_bead_doe.md §9.1): 비드 형상 DOE 준비·미리보기·실행.
  대상 = jobs.bead_doe_id(case·분석·비교·최적화 NULL). 산출물 ``<esl_root>/_doe/<bead_doe_id>/``. BD_GEOM·BD_GRID·
  BD_DESIGNS(LOCAL — paicad 외부 명령) 는 워커가 실행, 나머지 코어 단계는 ``esl.doe.stages.run_stage``.
- P3-UX §6: CASE_EXTRACT 첫 step ``H3D_EXTRACT``(LOCAL — 워커가 hw 실행)는 Case 입력이 h3d(input_kind H3D)일 때만 만든다
  (결과 폴더 입력이면 생략 → 기존 step 번호 그대로).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    key: str
    core_stage: str | None  # None = 플랫폼 등록 step(워커 프로세스 안)
    kind: str = "INTERNAL"  # INTERNAL | LOCAL(외부 프로그램)
    h3d_only: bool = False  # Case 입력이 h3d 일 때만


@dataclass(frozen=True)
class JobTypeDef:
    job_type: str
    stage: int  # UI 단계 1~6, 7 = Case 보고서, 8 = 라이브러리 분석, 9 = 설계 버전 비교, 10 = 비드 최적화, 11 = 비드 DOE
    lane: str  # SLOT | LIGHT
    steps: tuple[StepDef, ...]


JOB_TYPES: dict[str, JobTypeDef] = {
    "CASE_EXTRACT": JobTypeDef("CASE_EXTRACT", 1, "SLOT", (
        StepDef("H3D_EXTRACT", None, kind="LOCAL", h3d_only=True), StepDef("EXTRACT", "extract"), StepDef("TSTAR_SCAN", "tstar"), StepDef("EXTRACT_REGISTER", None))),
    "ESL_SOLVE": JobTypeDef("ESL_SOLVE", 4, "SLOT", (StepDef("ESL", "esl"), StepDef("ESL_REGISTER", None))),
    "VALIDATE": JobTypeDef("VALIDATE", 5, "SLOT", (StepDef("VALIDATE", "validate"), StepDef("VAL_REGISTER", None))),
    "EXPORT": JobTypeDef("EXPORT", 6, "LIGHT", (StepDef("EXPORT", "export"), StepDef("EXP_REGISTER", None))),
    "CASE_REPORT": JobTypeDef("CASE_REPORT", 7, "LIGHT", (StepDef("REPORT", "report"),
                                                          StepDef("REPORT_REGISTER", None))),
    "LIB_ANALYZE": JobTypeDef("LIB_ANALYZE", 8, "SLOT", (
        StepDef("ANALYZE", "lib_analyze"), StepDef("OPTDECK", "lib_optdeck"), StepDef("REPORT", "lib_report"),
        StepDef("LIB_REGISTER", None))),
    "LIB_COMPARE": JobTypeDef("LIB_COMPARE", 9, "LIGHT", (
        StepDef("COMPARE", "lib_compare"), StepDef("COMPARE_REGISTER", None))),
    "OPT_RUN": JobTypeDef("OPT_RUN", 10, "SLOT", (
        StepDef("OPT_PREP", "opt_prep"), StepDef("OPT_LOAD", "opt_load"), StepDef("OPT_DECK", "opt_deck"),
        StepDef("OS_SOLVE", None, kind="LOCAL"), StepDef("OPT_POST", "opt_post", kind="LOCAL"),
        StepDef("OPT_REGISTER", None))),
    "DOE_PREP": JobTypeDef("DOE_PREP", 11, "SLOT", (
        StepDef("BD_INPUT", "bd_input"), StepDef("BD_MESH0", "bd_mesh0"), StepDef("BD_GEOM", None, kind="LOCAL"),
        StepDef("BD_LOADS", "bd_loads"), StepDef("BD_PREP_REGISTER", None))),
    "DOE_PREVIEW": JobTypeDef("DOE_PREVIEW", 11, "SLOT", (
        StepDef("BD_MATRIX", "bd_matrix"), StepDef("BD_GRID", None, kind="LOCAL"), StepDef("BD_PREVIEW_REGISTER", None))),
    "DOE_RUN": JobTypeDef("DOE_RUN", 11, "SLOT", (
        StepDef("BD_BASELINE", "bd_eval"), StepDef("BD_DESIGNS", None, kind="LOCAL"),
        StepDef("BD_POST", "bd_post"), StepDef("BD_REGISTER", None))),
}
CASE_JOB_TYPES = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT")
LIB_STAGES = ("lib_analyze", "lib_optdeck", "lib_report", "lib_compare")
LIB_JOB_TYPES = ("LIB_ANALYZE", "LIB_COMPARE")
OPT_JOB_TYPES = ("OPT_RUN",)
OPT_STAGES = ("opt_prep", "opt_load", "opt_deck", "opt_post")
# 계약 §6.3: 작업 progress 가중(step 순서 OPT_PREP·OPT_LOAD·OPT_DECK·OS_SOLVE·OPT_POST·OPT_REGISTER, 합 100)
OPT_STEP_WEIGHTS = {"OPT_PREP": 1, "OPT_LOAD": 4, "OPT_DECK": 1, "OS_SOLVE": 82, "OPT_POST": 10, "OPT_REGISTER": 2}

DOE_JOB_TYPES = ("DOE_PREP", "DOE_PREVIEW", "DOE_RUN")
DOE_STAGES = ("bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post")   # = esl.doe.stages.STAGES
# 계약 §9.3: 작업 progress 가중(step 순서, 합 100)
DOE_STEP_WEIGHTS = {
    "DOE_PREP": {"BD_INPUT": 10, "BD_MESH0": 5, "BD_GEOM": 60, "BD_LOADS": 20, "BD_PREP_REGISTER": 5},
    "DOE_PREVIEW": {"BD_MATRIX": 5, "BD_GRID": 90, "BD_PREVIEW_REGISTER": 5},
    "DOE_RUN": {"BD_BASELINE": 5, "BD_DESIGNS": 85, "BD_POST": 9, "BD_REGISTER": 1},
}

EXPORT_TARGETS = ("radioss_inc", "fem", "csv")


def steps_for(job_type: str, *, h3d: bool = False) -> tuple[StepDef, ...]:
    """작업에 만들 step 목록(h3d_only step 은 h3d 입력일 때만)."""
    return tuple(sd for sd in JOB_TYPES[job_type].steps if h3d or not sd.h3d_only)
