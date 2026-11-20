"""v0.24.3 ④ 검증 출처 계획 표(계약 docs/contracts/esl_validate_sources.md §2·§10) — 선언 + 순수 함수만.

- 키·순서 = ``esl.view3d_src.KEYS``(import — 스터디 RANK_SOURCES·3D CASE_PLAN·화면 SOURCE_ROWS 와 같음, 시험 V-4).
- ``VAL_PLAN``: 행 = 출처 1개, 모든 행이 모든 열(``COLUMNS``)을 가짐(누락 = CONFIG_INVALID, 값 None = "이 출처에 없음").
  호출부(``esl.pipeline.stage_validate``·백엔드 어댑터)는 열만 읽고 출처 이름으로 분기하지 않는다(AGENTS.md).
  CASE_PLAN(3D 표시 열)에 검증 열을 더하지 않는다(D-0.24.3-VAL-2).
- 문구(사유·하중 프레임·균형·지지·변위 설명·한계 등급·보고서 출처 이름)는 이 모듈 한 곳.
- 파일 IO·설정 해석 없음. import 허용 = ``esl.errors``·``esl.view3d_src``·``esl.mech.bforce``(LIMIT_TEXT 만)
  (esl.doe·esl.pipeline·esl_platform·esl_worker 금지 — 시험 V-4).

파일 열 = ``(위치, 파일, 배열)``, 진단 ``doc`` = ``(위치, 파일)`` — 위치 ``esl`` = Case ``04_esl``.
"""

from __future__ import annotations

from typing import Any

from .errors import EslError
from .mech.bforce import LIMIT_TEXT as _BF_LIMIT_TEXT
from .view3d_src import KEYS
from .view3d_src import reason_text as _v3d_reason_text

SCHEMA_SOURCES = "esl/val_sources/1"          # 05_val/sources.json
SOURCES_JSON = "sources.json"
COLUMNS = ("key", "legacy", "load", "required", "load_frame", "balance", "support", "reaction_role", "reaction_tol_key", "reaction_warn_key", "target",
           "rigid", "resp", "fallback", "noise_force", "summary", "doc", "limits", "dir", "na", "note")
LOCS = ("esl",)
SUPPORTS = ("bc321", "jig")                   # bc321 = 03_bc/support.json 3-2-1, jig = 04_esl/jig.npz 지그 노드 123(P2)
REACTION_ROLES = ("judge", "info")
RIGIDS = ("linear",)                          # 비교 강체 제거 규칙 — 전부 linear(§3.1·§4.2)
RESPS = ("solve",)                            # 응답 = 검증 단계 풀이(D-0.24.3-VAL-3)
FALLBACKS = ("u_rel_condensed",)              # 전체 풀이를 못 할 때 변형률 참고 변위(None = 생략)
STATUSES = ("done", "unavailable", "failed", "disabled", "na")
FILE_COLS = ("load", "target")

# 반력 허용치 설정 키(계획 열 reaction_tol_key): None = 공통 기준 validation.reaction_rel_max, 문자열 = 그 설정 키(출처 키 → 허용치
# 사전, 사전에 없는 출처는 공통 기준). 값은 esl/config.py VALIDATION_SOURCES_DEFAULTS["reaction_tol"].
TOL_KEY = "validation.sources.reaction_tol"
WARN_KEY = "validation.sources.reaction_warn"
WARN_CODE = "REACTION_ABOVE_WARN"             # 반력 주의 표식(한계 코드와 같은 자리, 등급 caution)

VAL_PLAN: tuple[dict[str, Any], ...] = (
    {"key": "jig", "legacy": False, "load": None, "required": False, "load_frame": None, "balance": None,
     "support": None, "reaction_role": None, "reaction_tol_key": None, "reaction_warn_key": None, "target": None, "rigid": "linear", "resp": "solve", "fallback": None,
     "noise_force": False, "summary": None, "doc": None, "limits": None, "dir": None, "na": "V3D_STUDY_ONLY",
     "note": None},
    {"key": "full", "legacy": True, "load": ("esl", "f_eq.npz", "f"), "required": True, "load_frame": "ref_k0",
     "balance": "self", "support": "bc321", "reaction_role": "judge", "reaction_tol_key": None, "reaction_warn_key": None, "target": ("esl", "u_rel.npz", "u_rel"),
     "rigid": "linear", "resp": "solve", "fallback": "u_rel_condensed", "noise_force": True, "summary": None,
     "doc": None, "limits": None, "dir": "", "na": "PREREQUISITE_MISSING", "note": "VAL_NOTE_CONSISTENCY"},
    {"key": "bforce", "legacy": False, "load": ("esl", "bforce.npz", "f"), "required": False, "load_frame": "ref_rot",
     "balance": ("balance",), "support": "bc321", "reaction_role": "judge", "reaction_tol_key": TOL_KEY, "reaction_warn_key": WARN_KEY,
     "target": ("esl", "u_rel.npz", "u_rel"),
     "rigid": "linear", "resp": "solve", "fallback": None, "noise_force": False, "summary": "bforce",
     "doc": ("esl", "bforce.json"), "limits": ("limits",), "dir": "bforce", "na": "V3D_SRC_NOT_RUN",
     "note": "VAL_NOTE_RECON"},
    {"key": "fint", "legacy": False, "load": ("esl", "fint.npz", "f"), "required": False, "load_frame": "ref_rot",
     "balance": ("fint", "balance_applied"), "support": "bc321", "reaction_role": "judge",
     "reaction_tol_key": TOL_KEY, "reaction_warn_key": WARN_KEY, "target": ("esl", "u_rel.npz", "u_rel"), "rigid": "linear", "resp": "solve", "fallback": None,
     "noise_force": False, "summary": "fint", "doc": ("esl", "fint.json"), "limits": ("limits",), "dir": "fint",
     "na": "V3D_SRC_NOT_RUN", "note": "VAL_NOTE_RECON"},
)

# ---------------------------------------------------------------- 문구(원본 한 곳 — §2.2·§2.3·§10)
# 보고서(07_report)·echo 용 출처 이름 = 화면 frontend/src/view3d/sources.ts:SOURCE_ROWS label 과 같은 값(시험이 확인).
LABEL = {"jig": "지그 ESL", "full": "전 노드 ESL", "bforce": "경계력 ESL", "fint": "내력 ESL"}
# 새 사유 문구(사유 부분만 — 화면 unavailText 가 "<이름> 불가 — <사유>" 로 붙임). 없는 코드는 view3d_src.reason_text.
REASON_TEXT = {
    "VAL_SRC_NOT_RUN": "이 검증에는 출처별 결과가 없습니다(v0.24.3 이전 검증) — ④ 검증을 다시 실행하면 생깁니다",
    "VAL_SRC_FAILED": "출처 검증 계산 실패({detail}) — 다른 출처 결과는 그대로",
    "VAL_SRC_DISABLED": "설정에서 꺼짐(validation.sources.enabled)",
    "VALIDATION_FILES_GONE": "이 검증의 산출물이 이후 검증으로 바뀌었습니다(같은 ESL 결과로 다시 검증)",
    "JIG_NOT_RUN": "이 ESL 결과에는 지그 ESL 이 없습니다(v0.24.4 이전 계산) — ③ ESL 을 다시 계산하면 생깁니다",
}
FAILED_DETAIL_MAX = 300
LOAD_FRAME_TEXT = {"ref_k0": "기준 형상 F = K₀·u_rel",
                   "ref_rot": "기준 형상 F_ref = Rᵀ·F(낙하 프레임 → S3 Kabsch R)",
                   "ref_basis": "기준 형상 F = Σ a_k·기저(지그 맞춤)"}
BALANCE_TEXT = {"self": "자기평형(구성상)", "jig": "지그 지지(tie 노드 123)가 받음", "inertia_relief": "관성 이완",
                "none": "균형 보정 없음 — 불평형은 지지 반력으로"}
SUPPORT_TEXT = {"bc321": "3-2-1(03_bc/support.json)", "jig": "지그 노드 123(04_esl/jig.npz)"}
NOTE_TEXT = {
    "VAL_NOTE_CONSISTENCY": "ESL 재해석 변위와 Radioss 변위의 차이 — 계산·경계조건·저장 정밀도의 수치 일관성을 봅니다"
                            "(물리적 차이가 아닙니다).",
    "VAL_NOTE_RECON": "이 하중으로 정적 풀이한 변위와 Radioss 변위(강체 제거)의 차이 — 하중이 낙하 변형을 얼마나 "
                      "재현하는지(물리 차이 포함)를 봅니다.",
}
COND_TAIL = "목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이"
# 한계 등급(§10): not_comparable = "비교용 아님", caution = 주의. 표에 없는 코드 = caution(보수적 — 비교 가능 표시 유지).
LIMIT_CLASS = {"BF_TIE_MISSING": "not_comparable", "FINT_ROT_LINKS": "caution", "JIG_REGION_FALLBACK": "caution"}
LIMIT_CLASS_TEXT = {"not_comparable": "비교용 아님", "caution": "주의"}
LIMIT_TEXT = {**_BF_LIMIT_TEXT}               # 한계 문구 원본 = esl.mech.bforce.LIMIT_TEXT(P2 jig 문구는 jig.json 에서)


def check_plan(plan=VAL_PLAN) -> None:
    """계획 표 검사(§2): 열·키 순서 = KEYS·legacy 정확히 1행·dir 유일·rigid 전부 linear·resp 전부 solve·support ∈
    SUPPORTS·reaction_role ∈ {judge, info}·파일 열 형식. 어기면 CONFIG_INVALID."""
    keys, dirs = [], []
    for r in plan:
        miss = [c for c in COLUMNS if c not in r]
        if miss:
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 행 {r.get('key')!r} 에 열이 없습니다: {miss}")
        extra = [c for c in r if c not in COLUMNS]
        if extra:
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 행 {r['key']!r} 에 모르는 열: {extra}")
        keys.append(r["key"])
        if r["rigid"] not in RIGIDS:
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.rigid = {r['rigid']!r} (전부 {RIGIDS[0]})")
        if r["resp"] not in RESPS:
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.resp = {r['resp']!r} (전부 {RESPS[0]})")
        for c in FILE_COLS:
            v = r[c]
            if v is not None and (len(v) != 3 or v[0] not in LOCS):
                raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.{c} 형식 오류: {v!r}")
        if r["doc"] is not None and (len(r["doc"]) != 2 or r["doc"][0] not in LOCS):
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.doc 형식 오류: {r['doc']!r}")
        if r["fallback"] is not None and r["fallback"] not in FALLBACKS:
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.fallback 값 오류: {r['fallback']!r}")
        for c in ("reaction_tol_key", "reaction_warn_key"):
            if r[c] is not None and not (isinstance(r[c], str) and r[c]):
                raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.{c} 형식 오류: {r[c]!r}")
        if r["load"] is not None:
            if r["support"] not in SUPPORTS:
                raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}.support = {r['support']!r} ∉ {SUPPORTS}")
            if r["reaction_role"] not in REACTION_ROLES:
                raise EslError("CONFIG_INVALID",
                               f"검증 출처 계획 {r['key']}.reaction_role = {r['reaction_role']!r} ∉ {REACTION_ROLES}")
            if r["target"] is None or r["dir"] is None or r["load_frame"] not in LOAD_FRAME_TEXT or r["note"] not in NOTE_TEXT:
                raise EslError("CONFIG_INVALID",
                               f"검증 출처 계획 {r['key']}: load 가 있으면 target·dir·load_frame·note 가 있어야 합니다")
            if r["balance"] is None:
                raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}: load 가 있으면 balance 가 있어야 합니다")
            dirs.append(r["dir"])
        if r["legacy"] and (r["load"] is None or r["dir"] != "" or not r["required"] or r["fallback"] is None):
            raise EslError("CONFIG_INVALID",
                           "검증 출처 계획 legacy 행은 load·required·fallback 이 있고 dir = '' (05_val 루트)")
        if not r["legacy"] and r["dir"] == "":
            raise EslError("CONFIG_INVALID", f"검증 출처 계획 {r['key']}: 05_val 루트(dir '')는 legacy 행만")
    if tuple(keys) != KEYS:
        raise EslError("CONFIG_INVALID", f"검증 출처 계획 키 순서 {keys} ≠ {list(KEYS)}")
    if sum(1 for r in plan if r["legacy"]) != 1:
        raise EslError("CONFIG_INVALID", "검증 출처 계획 legacy 행은 정확히 1개여야 합니다")
    if len(set(dirs)) != len(dirs):
        raise EslError("CONFIG_INVALID", f"검증 출처 계획 dir 중복: {dirs}")


def plan(key: str | None) -> dict[str, Any]:
    """출처 키 → 계획 행. None = legacy 행. 모르는 키 = EslError SOURCE_NOT_FOUND."""
    for r in VAL_PLAN:
        if (key is None and r["legacy"]) or r["key"] == key:
            return r
    raise EslError("SOURCE_NOT_FOUND", f"모르는 하중 출처입니다: {key} (가능: {list(KEYS)})")


def legacy_key() -> str:
    return plan(None)["key"]


def reason_text(code: str | None, detail: str | None = None) -> str | None:
    """사유 코드 → 문구(사유 부분). 새 코드(REASON_TEXT) 우선, 나머지는 ``view3d_src.reason_text``(표에 없으면 detail 그대로)."""
    if code is None:
        return None
    if code in REASON_TEXT:
        base = REASON_TEXT[code]
        if "{detail}" in base:
            return base.format(detail=(detail or code)[:FAILED_DETAIL_MAX])
        return f"{base}({detail})" if detail else base
    return _v3d_reason_text(code, detail)


def doc_get(doc: dict[str, Any] | None, path) -> Any:
    """진단 json 안 키 경로 값(없으면 None)."""
    cur: Any = doc
    for k in path or ():
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def row_status(row: dict[str, Any], have_load: bool, doc: dict[str, Any] | None = None,
               summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """출처 행 상태(순수 — 호출부가 하중 존재·진단 json·ESL 요약 forces.<summary> 를 넘김). §4.4 우선순위:
    load 열 None → na(행 na), 하중 있음 → done(검증 후보), 없음 → 진단 json code·reason → ESL 요약 code·reason → 행 na
    (status unavailable). 반환 {status, code, reason}."""
    if row["load"] is None:
        return {"status": "na", "code": row["na"], "reason": reason_text(row["na"])}
    if have_load:
        return {"status": "done", "code": None, "reason": None}
    d = doc if isinstance(doc, dict) else {}
    s = summary if isinstance(summary, dict) else {}
    if d.get("code"):
        code, detail = str(d["code"]), d.get("reason")
    elif s.get("code"):
        code, detail = str(s["code"]), s.get("reason")
    else:
        code, detail = row["na"], None
    return {"status": "unavailable", "code": code, "reason": reason_text(code, detail)}


def failed_status(err: str) -> dict[str, Any]:
    """검증 계산 예외 → {status failed, code VAL_SRC_FAILED, reason}(오류 ≤ 300자)."""
    return {"status": "failed", "code": "VAL_SRC_FAILED", "reason": reason_text("VAL_SRC_FAILED", str(err))}


def disabled_status() -> dict[str, Any]:
    return {"status": "disabled", "code": "VAL_SRC_DISABLED", "reason": reason_text("VAL_SRC_DISABLED")}


def balance_of(row: dict[str, Any], doc: dict[str, Any] | None) -> str | None:
    """균형 방식 코드: 열이 고정 코드(str)면 그것, 키 경로(tuple)면 진단 json 안 적용값."""
    b = row["balance"]
    if b is None or isinstance(b, str):
        return b
    v = doc_get(doc, b)
    return None if v is None else str(v)


def cond_of(row: dict[str, Any], doc: dict[str, Any] | None) -> dict[str, Any]:
    """조건 코드 {load_frame, balance, support, rigid, resp}."""
    return {"load_frame": row["load_frame"], "balance": balance_of(row, doc), "support": row["support"],
            "rigid": row["rigid"], "resp": row["resp"]}


def cond_text(row: dict[str, Any], doc: dict[str, Any] | None) -> str:
    """조건 한 줄: "하중 <load_frame> · 지지 <support> · 균형 <balance> · 목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이"."""
    c = cond_of(row, doc)
    lf = LOAD_FRAME_TEXT.get(c["load_frame"], c["load_frame"] or "–")
    sp = SUPPORT_TEXT.get(c["support"], c["support"] or "–")
    bl = BALANCE_TEXT.get(c["balance"], c["balance"] or "–")
    return f"하중 {lf} · 지지 {sp} · 균형 {bl} · {COND_TAIL}"


def note_text(row: dict[str, Any]) -> str | None:
    return NOTE_TEXT.get(row["note"]) if row["note"] else None


def limit_codes(row: dict[str, Any], doc: dict[str, Any] | None) -> list[str]:
    """진단 json 의 한계 코드 목록(계획 열 limits 키 경로, 없으면 빈 목록)."""
    if row["limits"] is None:
        return []
    v = doc_get(doc, row["limits"])
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def limit_class(code: str) -> str:
    return LIMIT_CLASS.get(code, "caution")


def limit_info(codes) -> dict[str, Any]:
    """한계 코드 → {limits, limit_text, comparable}. comparable = not any(not_comparable) (§10)."""
    cs = [str(x) for x in (codes or [])]
    return {"limits": cs, "limit_text": [LIMIT_TEXT.get(x, x) for x in cs],
            "comparable": not any(limit_class(x) == "not_comparable" for x in cs)}


def src_block(row: dict[str, Any], doc: dict[str, Any] | None, sum_abs_f: float | None) -> dict[str, Any]:
    """출처 validation.json 끝 ``src`` 블록(§6.3)."""
    c = cond_of(row, doc)
    loc_file = None if row["load"] is None else f"04_esl/{row['load'][1]}"
    return {"key": row["key"], "load": loc_file, "sum_abs_f": sum_abs_f, **c, "cond_text": cond_text(row, doc),
            "note": note_text(row), **limit_info(limit_codes(row, doc))}


def empty_row(row: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
    """sources.json 행 — 상태가 done 이 아닐 때(verdict 이하 null·빈 값, dir null)."""
    return {"key": row["key"], "status": st["status"], "code": st.get("code"), "reason": st.get("reason"), "dir": None,
            "verdict": None, "fail_reasons": [], "undetermined_reason": None, "metrics": None, "reaction_role": None,
            "reaction_tol": None, "reaction_tol_key": None, "reaction_warn": None, "reaction_warned": False, "cond": None, "cond_text": None, "note": None, "limits": [], "limit_text": [], "comparable": None}


ROW_METRICS = ("disp_rms_rel", "disp_max_rel", "reaction_rel", "disp_noise_rel", "reaction_sum_rel",
               "hotspot1_strain_rel_err", "field_p90_err_pct")


def done_row(row: dict[str, Any], doc_val: dict[str, Any], diag: dict[str, Any] | None) -> dict[str, Any]:
    """sources.json 행 — 검증한 출처(값 = 그 출처 validation.json)."""
    vals = {m["metric"]: m.get("value") for m in doc_val.get("metrics") or []}
    crit = doc_val.get("criteria") or {}
    tol, warn, reac = crit.get("reaction_rel_max"), crit.get("reaction_warn_rel"), vals.get("reaction_rel")
    warned = bool(row["reaction_role"] == "judge" and warn is not None and reac is not None and tol is not None
                  and warn < reac <= tol)
    lim = limit_info(limit_codes(row, diag))
    if warned:                                  # PASS 유지 + 주의(한계와 같은 자리에 표시 — 화면 탭·보고서)
        lim["limits"].append(WARN_CODE)
        lim["limit_text"].append(f"반력 {reac * 100:.3g} % — {warn * 100:g} % 초과, 받침점 주변 국부 변형 확인")
    return {"key": row["key"], "status": "done", "code": None, "reason": None, "dir": row["dir"],
            "verdict": doc_val["verdict"], "fail_reasons": list(doc_val.get("fail_reasons") or []),
            "undetermined_reason": doc_val.get("undetermined_reason"),
            "metrics": {k: vals.get(k) for k in ROW_METRICS}, "reaction_role": row["reaction_role"],
            "reaction_tol": tol, "reaction_tol_key": row["reaction_tol_key"], "reaction_warn": warn,
            "reaction_warned": warned,
            "cond": cond_of(row, diag), "cond_text": cond_text(row, diag), "note": note_text(row),
            **lim}


check_plan()
