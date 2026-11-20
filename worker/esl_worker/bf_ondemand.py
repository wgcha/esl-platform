"""경계력 원자료 ESL 때 보충(계약 esl_bforce_ondemand.md §1.2·§3) — 판정·요청·평가·문구(순수 함수, DB·프로세스 없음).

- ``DECIDE``: 판정 표(위에서부터 첫 일치). executor 는 결과(action·cause)만 읽고 덤프/비덤프·Case 종류로 분기하지 않는다.
- ``CAUSE_TEXT``: 원인 상세 문구(기록 `bforce_ondemand.json` 의 detail 로 저장, 코어 `_bf_text` 가 사유로 씀) 한 곳.
- ``LOG``: ESL step 로그 문구 한 곳.
- ``request_keys``: bf 전용 request.txt 키(설정 = 작업 params.settings). ``evaluate``: hw 결과 평가.
DB(세마포어·outputs)·hw 실행은 executor, 코어 호출(병합·기록)은 core_adapter 래퍼를 통해서만.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import core_adapter, h3d

BF_ONLY = "bf_only"                     # done.json mode 값(TCL — 계약 §2.4)
CODE_FAILED = "BF_EXTRACT_FAILED"
CODE_SKIPPED = "BF_EXTRACT_SKIPPED"
WORK_SUB = "bf_ondemand"                # <esl_root>/_h3d/<Case 폴더>/ 아래 작업 폴더
RAW_SUB = "raw"                         # 작업 폴더 아래 TCL 출력 폴더
HW_TEXT_MAX = 4 * 1024 * 1024           # 라이선스 문구 검색용 hw 출력 읽기 상한(바이트)
LICENSE_RE = re.compile(r"(?i)licen[cs]e")
DETAIL_MAX = 300

# 원인 → 동작 종류(요약 code·기록 status). 원인 상세 문구는 CAUSE_TEXT.
SKIPPED_CAUSES = ("NO_TYPES", "H3D_UNREADABLE", "HW_UNAVAILABLE", "SETTINGS", "WAIT")
FAILED_CAUSES = ("TIMEOUT", "LICENSE", "HW_FAILED", "MISMATCH", "MERGE")

CAUSE_TEXT: dict[str, str] = {
    "NO_TYPES": "이 h3d 에 경계력·내력 결과 유형 없음(이전 보충 {at} — 이름 후보 bforce.result_names 확인)",
    "H3D_UNREADABLE": "입력 h3d 를 읽을 수 없음({name})",
    "HW_UNAVAILABLE": "서버 HyperWorks 실행 파일 또는 추출 TCL 없음(altair.hw_exe_path)",
    "SETTINGS": "경계력 설정을 읽지 못함({code})",
    "WAIT": "HyperWorks 동시 실행 한도 {limit}개가 {wait:g} s 동안 비지 않음(altair.bf_on_demand_wait_s)",
    "TIMEOUT": "시간 초과 {timeout:g} s(altair.bf_on_demand_timeout_s)",
    "LICENSE": "HyperWorks 라이선스 확인 실패 의심({msg})",
    "HW_FAILED": "HyperView 추출 실패({msg})",
    "MISMATCH": "h3d 가 추출 때와 다름({msg}) — ① 추출부터 다시",
    "MERGE": "01_extract 병합 실패({msg})",
}

LOG: dict[str, str] = {
    "have": "[esl-worker] 경계력 원자료: 프레임 {frame} 은 01_extract 에 있음 — 보충 안 함",
    "start": "[esl-worker] 경계력 원자료 보충 시작: 프레임 {frame}{t} 이 01_extract 에 없음 → HyperView bf 전용 추출 {h3d} → {out}",
    "wait": "[esl-worker] 경계력 원자료 보충: hw 동시 실행 한도 {limit}개(altair.max_concurrent_hw) — 최대 {wait:g} s 기다립니다",
    "got": "[esl-worker] hw 실행 권한을 얻었습니다",
    "pid": "[esl-worker] 경계력 원자료 보충: hw pid {pid} 시작, 자원 제한 {applied}, 시간 한도 {timeout:g} s",
    "beat": "[esl-worker] 경계력 원자료 보충 진행 중… 경과 {min:.1f}분{step}",
    "ok": "[esl-worker] 경계력 원자료 보충 완료: 프레임 {frame}, 종류 {kinds}, {sec:.1f} s → 01_extract/bforce.* 병합"
          "(프레임 {before} + {added})",
    "failed": "[esl-worker] 경계력 원자료 보충 실패({cause}): {detail} — ESL 은 계속(경계력·내력 등급 none, BF_EXTRACT_FAILED)",
    "skipped": "[esl-worker] 경계력 원자료 보충 생략({cause}): {detail} — ESL 은 계속(BF_EXTRACT_SKIPPED)",
    "unknown": "[esl-worker] 경계력 원자료 판정 생략({code}) — 보충 안 함",
}


def detail_text(cause: str, **kw: Any) -> str:
    return CAUSE_TEXT[cause].format(**kw)


# ---------------------------------------------------------------- 판정(§1.2)
@dataclass
class Facts:
    """판정에 쓰는 사실(호출부가 모음 — 판정은 순수). None = 알 수 없음."""

    enabled: bool | None = None          # 설정 bforce.enabled
    on_demand: bool | None = None        # 설정 bforce.on_demand
    input_kind: str = "RESULTS"          # Case input_kind
    has_frame: bool | None = None        # bforce_csv.has_frame(01_extract, f)
    no_types: dict | None = None         # bforce_ondemand.no_types_before(...) 이전 시도(없으면 None)
    h3d_ok: bool = False                 # case.h3d_path 파일 읽기 가능
    hw_ok: bool = False                  # altair.hw_exe_path·추출 TCL 파일 있음
    settings_error: str | None = None    # 경계력 요청 키를 못 만든 코어 오류 code
    unknown_code: str | None = None      # has_frame 을 코어가 못 알려준 오류 code(행 4a)


@dataclass(frozen=True)
class Decision:
    action: str                          # none | skip | fill
    cause: str | None = None
    row: int = 0
    note: str | None = None              # none 일 때 작업 로그 키(LOG[...]) — 없으면 로그 없음


# (행 번호, 조건 술어, 동작, 원인, 로그 키) — 위에서부터 첫 일치. 4a = 코어가 프레임 유무를 못 알려줌(코어 구버전) → v0.24.1 동작.
DECIDE: tuple[tuple[str, Callable[[Facts], bool], str, str | None, str | None], ...] = (
    ("1", lambda f: f.enabled is False, "none", None, None),
    ("2", lambda f: f.on_demand is False, "none", None, None),
    ("3", lambda f: f.input_kind != "H3D", "none", None, None),
    ("4", lambda f: f.has_frame is True, "none", None, "have"),
    ("4a", lambda f: f.has_frame is None, "none", None, "unknown"),
    ("5", lambda f: f.no_types is not None, "skip", "NO_TYPES", None),
    ("6", lambda f: not f.h3d_ok, "skip", "H3D_UNREADABLE", None),
    ("7", lambda f: not f.hw_ok, "skip", "HW_UNAVAILABLE", None),
    ("8", lambda f: f.settings_error is not None, "skip", "SETTINGS", None),
    ("9", lambda f: True, "fill", None, None),
)


def decide(f: Facts) -> Decision:
    for row, pred, action, cause, note in DECIDE:
        if pred(f):
            return Decision(action, cause, row=row, note=note)
    raise AssertionError("DECIDE 마지막 행은 항상 일치")      # pragma: no cover


# ---------------------------------------------------------------- 요청(§3.2)
def names_from(core_settings: dict) -> dict:
    """기록·판정 5 에 쓰는 이름 후보(`{result_names, vec_comps, scalar_comps}`). 코어 설정 오류 = CoreError."""
    x = core_adapter.bforce_settings(core_settings or {})
    e = core_adapter.extract_source_settings(core_settings or {})
    return {"result_names": {k: list(v) for k, v in x["result_names"].items()}, "vec_comps": list(x["vec_comps"]),
            "scalar_comps": list(e["scalar_comps"])}


def request_keys(core_settings: dict, frames: list[int]) -> dict[str, str]:
    """bf 전용 request.txt 키: bf_only·bf_frames·bf_on 1·bf_names_<k>·bf_vec_comps·scalar_comps. CoreError 는 호출부가 SETTINGS 로."""
    x = core_adapter.bforce_settings(core_settings or {})
    e = core_adapter.extract_source_settings(core_settings or {})
    keys = {"bf_only": "1", "bf_frames": " ".join(str(int(f)) for f in sorted(set(frames)))}
    keys.update(h3d.bforce_keys({**x, "enabled": True}))
    keys["scalar_comps"] = "|".join(e["scalar_comps"])
    return keys


# ---------------------------------------------------------------- 평가(§3.4)
def _summary(exit_code: int | None, done: dict | None, extra: str = "") -> str:
    if done is None:
        msg = f"done.json 없음(종료코드 {exit_code})"
    elif not done.get("ok"):
        parts = [f"종료코드 {exit_code}",
                 f"failed_step={done.get('failed_step')}" if done.get("failed_step") else "",
                 f"code={done.get('code')}" if done.get("code") else "", str(done.get("error") or "")]
        msg = ", ".join(x for x in parts if x)
    else:
        msg = f"종료코드 {exit_code}" + (f", {extra}" if extra else "")
    return msg[:DETAIL_MAX]


def evaluate(exit_code: int | None, out_dir: str, frames: list[int], hw_text: str = ""
             ) -> tuple[bool, str | None, str, dict[str, Any] | None]:
    """(ok, cause, detail, done). ok = 종료코드 0 ∧ done ok ∧ mode bf_only ∧ bforce dict ∧ 요청 프레임 ⊂ bforce.frames.
    아니면 cause = LICENSE(done 의 error·errorInfo 또는 hw 출력에 licen[cs]e — 추정) | HW_FAILED."""
    done = h3d.read_done(out_dir)
    want = {int(f) for f in frames}
    why = ""
    ok = False
    if exit_code == 0 and done is not None and done.get("ok"):
        bf = done.get("bforce")
        if done.get("mode") != BF_ONLY:
            why = "bf 전용 출력이 아님(mode≠bf_only)"
        elif not isinstance(bf, dict):
            why = "done.json 에 bforce 없음"
        elif not want <= {int(x) for x in (bf.get("frames") or []) if isinstance(x, int)}:
            why = f"요청 프레임 {sorted(want)} ⊄ bforce.frames {bf.get('frames')}"
        else:
            ok = True
    if ok:
        return True, None, "", done
    detail = _summary(exit_code, done, why)
    blob = " ".join([str((done or {}).get("error") or ""), str((done or {}).get("errorInfo") or ""), hw_text or ""])
    cause = "LICENSE" if LICENSE_RE.search(blob) else "HW_FAILED"
    msg = detail
    if cause == "LICENSE":
        m = LICENSE_RE.search(blob)
        lo = max(0, m.start() - 60)
        snippet = " ".join(blob[lo:m.end() + 80].split())
        msg = f"{detail}; …{snippet}…"[:DETAIL_MAX]
    return False, cause, msg, done


_NOT_HW = re.compile(r"^(\[esl-worker\]|ESL extract |\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )")


def read_hw_text(log_path: str, start: int) -> str:
    """이번 hw 프로세스 출력만(start = hw 시작 직전 바이트 — argv·경로 줄은 그 앞, 상한 HW_TEXT_MAX) — LICENSE 판정용.
    워커 줄([esl-worker])과 TCL 진행 줄(progress.log 옮김·ESL extract)은 경로를 담을 수 있어 제외."""
    try:
        with open(log_path, "rb") as fh:
            fh.seek(max(0, int(start)))
            raw = fh.read(HW_TEXT_MAX).decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(ln for ln in raw.splitlines() if not _NOT_HW.match(ln))


# ---------------------------------------------------------------- 기록·요약
def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def frame_time(extract_dir: str, frame: int) -> float | None:
    """01_extract/frames.json 의 후보 프레임 시간(로그용). 없으면 None."""
    try:
        with open(os.path.join(extract_dir, "frames.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        return float(d["time_D"][list(d["frames_D"]).index(int(frame))])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def status_of(cause: str | None) -> str:
    """원인 → 기록 status(None = ok)."""
    if cause is None:
        return "ok"
    return "skipped" if cause in SKIPPED_CAUSES else "failed"


def code_of(status: str) -> str | None:
    return {"failed": CODE_FAILED, "skipped": CODE_SKIPPED}.get(status)


def attempt_record(*, frame: int, job_id: str, cause: str | None, detail: str, seconds: float | None, h3d_path: str,
                   out_rel: str, names: dict | None, kinds: dict | None, merge: dict | None) -> dict[str, Any]:
    st = status_of(cause)
    return {"frame_index": int(frame), "job_id": job_id, "status": st, "code": code_of(st), "cause": cause,
            "detail": detail, "at": utc_now(), "seconds": None if seconds is None else round(float(seconds), 1),
            "h3d": h3d_path, "out_dir": out_rel, "names": names, "kinds": kinds, "merge": merge}


def summary_of(attempt: dict[str, Any]) -> dict[str, Any]:
    m = attempt.get("merge") or {}
    return {"frame": attempt["frame_index"], "status": attempt["status"], "cause": attempt["cause"],
            "detail": attempt["detail"], "seconds": attempt["seconds"], "kinds": attempt["kinds"],
            "added": list(m.get("added") or []), "dup": list(m.get("dup") or [])}


def kinds_text(kinds: dict | None) -> str:
    """로그용 `{cont: Contact Forces, acc: Acceleration}`(찾은 종류만, 없으면 `{}`)."""
    return "{" + ", ".join(f"{k}: {v}" for k, v in (kinds or {}).items() if v) + "}"
