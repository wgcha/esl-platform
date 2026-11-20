"""v0.24.1 3D 보기 하중 출처 표(계약 docs/contracts/esl_view3d_sources.md §2.1·§2.3·§2.5) — 선언 + 순수 함수만.

- 출처 키 하나 ``KEYS = ("jig", "jig_disp", "jig_spring", "full", "bforce", "fint")`` = 스터디 ``esl.doe.stages.RANK_SOURCES`` 키
  순서 = 화면 ``frontend/src/view3d/sources.ts:SOURCE_ROWS`` (시험이 셋이 같음을 확인). v0.24.4(esl_jig_case.md §2·§5.4): 지그 3방식
  (jig = 고정·jig_disp = 강제 변위·jig_spring = 스프링 — 방식 표 ``esl.mech.jig_bc.METHODS`` 열 src)이 Case 행을 가짐.
- Case 계획 표 ``CASE_PLAN``: 행 = 출처 1개, 모든 행이 모든 열(``COLUMNS``)을 가짐(누락 = CONFIG_INVALID, 값 None = "이 출처에 없음").
  호출부(백엔드 services/view3d.py)는 열만 읽고 출처 이름으로 분기하지 않는다(AGENTS.md). 새 출처 = 행 추가.
- 파일 IO·설정 해석 없음. import 허용 = ``esl.errors`` 만(esl.doe·esl.pipeline·esl_platform·esl_worker 금지 — 시험 V-4).

위치 토큰: ``esl`` = ESL 실행 산출물 04_esl(스냅샷 우선), ``val`` = 그 ESL 실행의 최신 검증 05_val. 파일 = ``(위치, 파일, 배열)``.
"""

from __future__ import annotations

from typing import Any

from .errors import EslError

KEYS = ("jig", "jig_disp", "jig_spring", "full", "bforce", "fint")
COLUMNS = ("key", "legacy", "load", "target", "resp", "recon_tgt", "rigid", "support", "summary", "doc", "dir",
           "recon_dir", "na", "resp_na", "fallback")
LOCS = ("esl", "val")
RIGIDS = ("kabsch", "linear")
FILE_COLS = ("load", "target", "resp", "recon_tgt")         # (위치, 파일, 배열) 열 — 호출부 have 키

CASE_PLAN: tuple[dict[str, Any], ...] = (
    # v0.24.4 지그 3방식(esl_jig_case.md §5.4): 하중 = 04_esl/<src>.npz f, 응답 = 같은 npz u_val(파트 Kabsch 제거), 지지 = 행 load
    # 파일의 bc 배열(tie + 3-2-1 면내 — 백엔드 SUPPORT_FILES["jig"])
    {"key": "jig", "legacy": False, "load": ("esl", "jig.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("esl", "jig.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
     "support": "jig", "summary": "jig", "doc": ("esl", "jig.json"), "dir": "view3d_jig",
     "recon_dir": "view3d_jig_recon", "na": "JIG_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False},
    {"key": "jig_disp", "legacy": False, "load": ("esl", "jig_disp.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("esl", "jig_disp.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
     "support": "jig", "summary": "jig_disp", "doc": ("esl", "jig_disp.json"), "dir": "view3d_jig_disp",
     "recon_dir": "view3d_jig_disp_recon", "na": "JIG_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False},
    {"key": "jig_spring", "legacy": False, "load": ("esl", "jig_spring.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("esl", "jig_spring.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
     "support": "jig", "summary": "jig_spring", "doc": ("esl", "jig_spring.json"), "dir": "view3d_jig_spring",
     "recon_dir": "view3d_jig_spring_recon", "na": "JIG_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False},
    {"key": "full", "legacy": True, "load": ("esl", "f_eq.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("val", "compare_disp.npz", "d_val"), "recon_tgt": ("val", "compare_disp.npz", "d_rel"), "rigid": "linear",
     "support": "bc", "summary": None, "doc": None, "dir": "view3d", "recon_dir": "view3d_recon",
     "na": "PREREQUISITE_MISSING", "resp_na": "V3D_RESP_NEED_VAL", "fallback": True},
    {"key": "bforce", "legacy": False, "load": ("esl", "bforce.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("esl", "bforce.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
     "support": "bc", "summary": "bforce", "doc": ("esl", "bforce.json"), "dir": "view3d_bforce",
     "recon_dir": "view3d_bforce_recon", "na": "V3D_SRC_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False},
    {"key": "fint", "legacy": False, "load": ("esl", "fint.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
     "resp": ("esl", "fint.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
     "support": "bc", "summary": "fint", "doc": ("esl", "fint.json"), "dir": "view3d_fint",
     "recon_dir": "view3d_fint_recon", "na": "V3D_SRC_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False},
)

# 사유 문구(사유 부분만 — 화면이 "<이름> 불가 — <사유>" 로 붙임). 원본 한 곳(§2.5).
REASON_TEXT = {
    "V3D_STUDY_ONLY": "강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)",
    "V3D_SRC_NOT_RUN": "이 ESL 결과에는 없습니다(v0.24.0 이전 계산) — ESL 을 다시 계산하면 생깁니다",
    "BF_DISABLED": "설정에서 꺼짐(bforce.enabled)",
    "FINT_DISABLED": "설정에서 꺼짐(bforce.fint.enabled)",
    "PREREQUISITE_MISSING": "ESL 산출물(04_esl/f_eq.npz·u_rel.npz 또는 01_extract/model.npz)이 없습니다",
    "V3D_RESP_NEED_VAL": "응답 변위 없음 — ⑤ 검증에서 전체 풀이(validation.full_solve)를 하면 보입니다",
    "V3D_RESP_SKIPPED": "응답 변위 없음 — ESL 단계 재현 풀이 생략",
    # v0.24.4(esl_jig_case.md §5.4 — val_src 에서 이동, 문구 = esl_validate_sources.md §2.3 그대로): 옛 ESL 결과(지그 파일·요약 없음)
    "JIG_NOT_RUN": "이 ESL 결과에는 지그 ESL 이 없습니다(v0.24.4 이전 계산) — ③ ESL 을 다시 계산하면 생깁니다",
}


def check_plan(plan=CASE_PLAN) -> None:
    """계획 표 검사: 모든 행 모든 열·키 순서 = KEYS·legacy 정확히 1행·위치 토큰·강체 규칙. 어기면 CONFIG_INVALID."""
    keys = []
    for r in plan:
        miss = [c for c in COLUMNS if c not in r]
        if miss:
            raise EslError("CONFIG_INVALID", f"3D 출처 계획 행 {r.get('key')!r} 에 열이 없습니다: {miss}")
        keys.append(r["key"])
        for c in FILE_COLS:
            v = r[c]
            if v is not None and (len(v) != 3 or v[0] not in LOCS):
                raise EslError("CONFIG_INVALID", f"3D 출처 계획 {r['key']}.{c} 형식 오류: {v!r}")
        if r["doc"] is not None and (len(r["doc"]) != 2 or r["doc"][0] not in LOCS):
            raise EslError("CONFIG_INVALID", f"3D 출처 계획 {r['key']}.doc 형식 오류: {r['doc']!r}")
        if r["rigid"] is not None and r["rigid"] not in RIGIDS:
            raise EslError("CONFIG_INVALID", f"3D 출처 계획 {r['key']}.rigid 값 오류: {r['rigid']!r}")
        if r["load"] is not None and not (r["target"] and r["dir"] and r["recon_dir"]):
            raise EslError("CONFIG_INVALID", f"3D 출처 계획 {r['key']}: load 가 있으면 target·dir·recon_dir 가 있어야 합니다")
    if tuple(keys) != KEYS:
        raise EslError("CONFIG_INVALID", f"3D 출처 계획 키 순서 {keys} ≠ {list(KEYS)}")
    if sum(1 for r in plan if r["legacy"]) != 1:
        raise EslError("CONFIG_INVALID", "3D 출처 계획 legacy 행은 정확히 1개여야 합니다")


def plan(key: str | None) -> dict[str, Any]:
    """출처 키 → 계획 행. None = legacy 행(옛 URL). 모르는 키 = EslError SOURCE_NOT_FOUND."""
    for r in CASE_PLAN:
        if (key is None and r["legacy"]) or r["key"] == key:
            return r
    raise EslError("SOURCE_NOT_FOUND", f"모르는 하중 출처입니다: {key} (가능: {list(KEYS)})")


def legacy_key() -> str:
    return plan(None)["key"]


def has_load(key: str) -> bool:
    """이 출처가 Case 하중 보기를 가질 수 있는가(설정 view3d.case_src_default 검증용)."""
    return plan(key)["load"] is not None


def reason_text(code: str | None, detail: str | None = None) -> str | None:
    """사유 코드 → 문구. 표에 없는 코드(Case 요약 code — BF_NO_DATA 등)는 detail(요약 reason) 그대로. detail 이 있으면
    표 문구 뒤 괄호로(V3D_RESP_SKIPPED = 재현 생략 사유)."""
    if code is None:
        return None
    base = REASON_TEXT.get(code)
    if base is None:
        return detail if detail else code
    return f"{base}({detail})" if detail else base


def case_status(row: dict[str, Any], summary: dict[str, Any] | None, have: dict[str, bool],
                doc_reason: str | None = None) -> dict[str, Any]:
    """Case 출처 상태(순수 — 파일 IO 없음, 호출부가 존재 여부·요약을 넘김).

    have = {"model", "load", "target", "resp", "recon_tgt": 파일·배열 있음}. 규칙(§2.3):
    load(또는 target·model) 없음 → 요약 code(BF_DISABLED·BF_NO_DATA·*_FAILED…) 가 있으면 그것(reason = 요약 reason 그대로),
    없으면 행 na. resp 없음 → 요약 recon = skipped 이면 resp_na + doc 의 recon.reason, 그 밖 resp_na.
    반환 {available, code, reason, resp, resp_code, resp_reason}.
    """
    s = summary if isinstance(summary, dict) else {}
    if row["load"] is None:
        code = row["na"]
        return {"available": False, "code": code, "reason": reason_text(code), "resp": False, "resp_code": code,
                "resp_reason": reason_text(code)}
    if not (have.get("model") and have.get("load") and have.get("target")):
        if s.get("code"):
            code, reason = str(s["code"]), reason_text(str(s["code"]), s.get("reason"))
        else:
            code, reason = row["na"], reason_text(row["na"])
        return {"available": False, "code": code, "reason": reason, "resp": False, "resp_code": code, "resp_reason": reason}
    if row["resp"] is not None and have.get("resp") and have.get("recon_tgt"):
        return {"available": True, "code": None, "reason": None, "resp": True, "resp_code": None, "resp_reason": None}
    code = row["resp_na"]
    why = doc_reason if s.get("recon") == "skipped" else None
    return {"available": True, "code": None, "reason": None, "resp": False, "resp_code": code,
            "resp_reason": reason_text(code, why)}


check_plan()
