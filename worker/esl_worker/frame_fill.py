"""D 밖 프레임 채움 워커 쪽(계약 esl_tstar_manual_jig_force.md §2.4 — v0.25.2 TM) — 사실 모으기·요청 키·평가·문구(DB·프로세스 없음).

- 판정 표·병합·시도 기록은 코어 ``esl.io.frame_fill``(core_adapter 경유) 한 곳. 이 모듈은 그 판정에 줄 사실(``facts``)·hw 요청(``request_extra``)·
  결과 평가(``evaluate``)·로그/원인 문구(``LOG``·``CAUSE_TEXT``)만 가진다. 백엔드(GET/PUT /tstar 가능 판정·ESL 작업 사전 점검)도 ``facts``·``decide`` 를 같이 쓴다.
- hw 실행·세마포어·기록 호출은 executor(``Executor._frame_fill``)가 한다. 시간 한도·대기 한도 = ``altair.frame_fill_timeout_s``·``frame_fill_wait_s``.
- 실패 = ESL 단계 실패 ``TSTAR_FRAME_FILL_FAILED``(경계력 보충과 달리 계속하지 않음 — 변위가 없으면 ESL 을 만들 수 없다).
"""

from __future__ import annotations

import os
from typing import Any

from . import bf_ondemand, core_adapter, h3d

FILL_MODE = "fr_only"                   # done.json mode 값(TCL — 계약 §2.4)
CODE_FAILED = "TSTAR_FRAME_FILL_FAILED"
WORK_SUB = "frame_fill"                 # <esl_root>/_h3d/<Case 폴더>/ 아래 작업 폴더
RAW_SUB = "raw"                         # 작업 폴더 아래 TCL 출력 폴더
DETAIL_MAX = 300

# 원인 → 상세 문구(기록 frame_fill.json 의 detail·단계 실패 메시지). 판정 표 block 사유(NO_H3D…)는 코어 DECIDE 문구를 그대로 쓴다.
FAILED_CAUSES = ("WAIT", "TIMEOUT", "LICENSE", "HW_FAILED", "MISMATCH", "MERGE", "SETTINGS")
CAUSE_TEXT: dict[str, str] = {
    "WAIT": "HyperWorks 동시 실행 한도 {limit}개가 {wait:g} s 동안 비지 않음(altair.frame_fill_wait_s)",
    "TIMEOUT": "시간 초과 {timeout:g} s(altair.frame_fill_timeout_s)",
    "LICENSE": "HyperWorks 라이선스 확인 실패 의심({msg})",
    "HW_FAILED": "HyperView 추출 실패({msg})",
    "MISMATCH": "h3d 가 추출 때와 다름({msg}) — ① 추출부터 다시",
    "MERGE": "01_extract 병합 실패({msg})",
    "SETTINGS": "채움 요청을 만들지 못함({msg})",
}

LOG: dict[str, str] = {
    "start": "[esl-worker] 직접 고른 t*: 프레임 {frame}{t} 의 변위·변형률이 01_extract 에 없음 → HyperView 채움 추출(fr_only) {h3d} → {out}",
    "wait": "[esl-worker] 프레임 채움: hw 동시 실행 한도 {limit}개(altair.max_concurrent_hw) — 최대 {wait:g} s 기다립니다",
    "got": "[esl-worker] hw 실행 권한을 얻었습니다",
    "pid": "[esl-worker] 프레임 채움: hw pid {pid} 시작, 자원 제한 {applied}, 시간 한도 {timeout:g} s",
    "beat": "[esl-worker] 프레임 채움 진행 중… 경과 {min:.1f}분{step}",
    "ok": "[esl-worker] 프레임 채움 완료: 프레임 {frame}, {sec:.1f} s → 01_extract/disp.npz·strain_frames.npz 병합({added})",
    "failed": "[esl-worker] 프레임 채움 실패({cause}): {detail} — ESL 단계 실패(TSTAR_FRAME_FILL_FAILED)",
    "blocked": "[esl-worker] 프레임 채움 불가({cause}): {detail} — ESL 단계 실패(TSTAR_FRAME_FILL_FAILED)",
    "bf": "[esl-worker] 프레임 채움: 같은 실행의 경계력 원자료도 병합({kinds})",
    "bf_skip": "[esl-worker] 프레임 채움: 경계력 원자료 병합 생략({detail}) — 경계력 보충이 따로 판단합니다",
}


def detail_text(cause: str, **kw: Any) -> str:
    return CAUSE_TEXT[cause].format(**kw)[:DETAIL_MAX]


# ---------------------------------------------------------------- 사실(판정에 줄 것)
def tcl_and_hw_ok(settings: Any) -> bool:
    """서버 hw 실행 파일·추출 TCL 이 있음(판정 표 행 5). settings = 플랫폼 Settings(None 이면 점검 생략 = 참)."""
    if settings is None:
        return True
    from esl_platform.core.config import default_extract_tcl

    hw = settings.altair.hw_exe_path
    return bool(hw) and os.path.isfile(hw) and os.path.isfile(default_extract_tcl())


def facts(case: dict[str, Any], extract_dir: str, frame: int, settings: Any = None):
    """코어 ``Facts``(계약 §2.4): have·dump_mode = 01_extract(core_adapter.frame_fill_extract_facts), csv_input = Case 입력이 h3d 아님,
    h3d_readable = case.h3d_path 파일 읽기 가능, hw_available = tcl_and_hw_ok(settings). 코어가 01_extract 를 못 읽으면 have False·덤프 아님."""
    try:
        ex = core_adapter.frame_fill_extract_facts(extract_dir, frame)
    except core_adapter.CoreError:
        ex = {"have": False, "dump_mode": False}
    h3d_path = case.get("h3d_path")
    readable = bool(h3d_path) and os.path.isfile(h3d_path) and os.access(h3d_path, os.R_OK)
    cls = core_adapter.frame_fill_facts_cls()
    return cls(have=bool(ex.get("have")), csv_input=str(case.get("input_kind") or "RESULTS") != "H3D",
               dump_mode=bool(ex.get("dump_mode")), h3d_readable=readable, hw_available=tcl_and_hw_ok(settings),
               h3d_name=os.path.basename(h3d_path or ""))


def fill_state(case: dict[str, Any], extract_dir: str, settings: Any = None) -> dict[str, Any]:
    """Case 단위 채움 가능 여부(API GET /tstar ``fill``): {available, code, text}. have 는 보지 않음(프레임과 무관 — 행 2~5 만)."""
    f = facts(case, extract_dir, -1, settings)
    cls = core_adapter.frame_fill_facts_cls()
    f = cls(have=False, csv_input=f.csv_input, dump_mode=f.dump_mode, h3d_readable=f.h3d_readable,
            hw_available=f.hw_available, h3d_name=f.h3d_name)
    dec = core_adapter.frame_fill_decide(f)
    if dec["action"] == "block":
        return {"available": False, "code": dec["code"], "text": dec["text"]}
    return {"available": True, "code": None, "text": None}


# ---------------------------------------------------------------- 요청(§2.4)
def request_extra(core_settings: dict, meta: dict, frame: int, warn: list[str] | None = None) -> dict[str, str]:
    """request.txt 에 더할 키: 추출 때 키(변형률 이름 후보·경계력 bf 키 — 설정 = 작업 params.settings) + 코어 채움 키
    (fr_only 1·fr_frames "<f>"·strain_sources = 추출 때 source 하나 — 추출 키의 strain_sources 를 덮어씀). CoreError 는 호출부가 SETTINGS 로."""
    keys: dict[str, str] = {}
    keys.update(h3d.strain_request(core_settings or {}))
    keys.update(h3d.bforce_request(core_settings or {}, warn))
    keys.update(core_adapter.frame_fill_request_keys(meta, frame))
    return keys


# ---------------------------------------------------------------- 평가
def evaluate(exit_code: int | None, out_dir: str, frame: int, hw_text: str = ""
             ) -> tuple[bool, str | None, str, dict[str, Any] | None]:
    """(ok, cause, detail, done). ok = 종료코드 0 ∧ done ok ∧ mode fr_only ∧ frames ∋ 요청 프레임 ∧ disp.csv·strain_frames.csv 있음.
    아니면 cause = LICENSE(done 의 error·errorInfo 또는 hw 출력에 licen[cs]e — 추정) | HW_FAILED."""
    done = h3d.read_done(out_dir)
    why = ""
    ok = False
    if exit_code == 0 and done is not None and done.get("ok"):
        frames = [int(x) for x in (done.get("frames") or []) if isinstance(x, int) and not isinstance(x, bool)]
        missing = [n for n in ("disp.csv", "strain_frames.csv") if not os.path.isfile(os.path.join(out_dir, n))]
        if done.get("mode") != FILL_MODE:
            why = "채움 출력이 아님(mode≠fr_only)"
        elif int(frame) not in frames:
            why = f"요청 프레임 {int(frame)} ∉ frames {done.get('frames')}"
        elif missing:
            why = f"출력 없음: {', '.join(missing)}"
        else:
            ok = True
    if ok:
        return True, None, "", done
    detail = bf_ondemand._summary(exit_code, done, why)
    blob = " ".join([str((done or {}).get("error") or ""), str((done or {}).get("errorInfo") or ""), hw_text or ""])
    cause = "LICENSE" if bf_ondemand.LICENSE_RE.search(blob) else "HW_FAILED"
    msg = detail
    if cause == "LICENSE":
        m = bf_ondemand.LICENSE_RE.search(blob)
        lo = max(0, m.start() - 60)
        snippet = " ".join(blob[lo:m.end() + 80].split())
        msg = f"{detail}; …{snippet}…"[:DETAIL_MAX]
    return False, cause, msg, done


# ---------------------------------------------------------------- 기록·요약
def frame_time(extract_dir: str, frame: int) -> float | None:
    """01_extract/history.npz 의 그 프레임 시각(로그용). 없으면 None."""
    import numpy as np

    try:
        with np.load(os.path.join(extract_dir, "history.npz"), allow_pickle=False) as z:
            fi = np.asarray(z["frame_index"]).reshape(-1)
            hit = np.flatnonzero(fi == int(frame))
            return float(np.asarray(z["time"]).reshape(-1)[int(hit[0])]) if hit.size else None
    except (OSError, KeyError, ValueError, IndexError):
        return None


def status_of(cause: str | None, blocked: bool = False) -> str:
    if blocked:
        return "blocked"
    return "ok" if cause is None else "failed"


def attempt_record(*, frame: int, job_id: str, cause: str | None, detail: str, seconds: float | None,
                   blocked: bool = False) -> dict[str, Any]:
    """코어 ``frame_fill.record`` 에 줄 시도 1건(형식 소유 = 코어: frame·job_id·status·cause·detail·seconds·at)."""
    return {"frame": int(frame), "job_id": job_id, "status": status_of(cause, blocked), "cause": cause,
            "detail": detail or None, "seconds": None if seconds is None else round(float(seconds), 1),
            "at": bf_ondemand.utc_now()}


def summary_of(attempt: dict[str, Any]) -> dict[str, Any]:
    """작업 결과·step outputs 의 ``frame_fill{status, frame, seconds, cause?, detail?}``(계약 §6.1 — 채움을 시도했을 때만)."""
    out: dict[str, Any] = {"status": attempt["status"], "frame": attempt["frame"], "seconds": attempt["seconds"]}
    if attempt.get("cause"):
        out["cause"] = attempt["cause"]
    if attempt.get("detail"):
        out["detail"] = attempt["detail"]
    return out
