"""D 밖 프레임 채움 — 판정 표·병합·시도 기록(계약 esl_tstar_manual_jig_force.md §2.4, D-0.25.2-3·4·7).

직접 고른 t* 가 추출 때 변위·변형률을 받은 프레임 집합 D 밖이면, 워커가 ③ ESL 단계 시작 전에 그 프레임 f 만 HyperView 로
한 번 더 읽어(TCL ``fr_only 1`` + ``fr_frames "<f>"`` — 전 노드 변위 f, 전 요소 변형률 f·f−1, 경계력 종류 f) ``fill_out`` 에
쓰고, 이 모듈이 Case ``01_extract/disp.npz``·``strain_frames.npz`` 끝에 덧붙인다(기존 키·dtype·행 위치 불변). ``frames.json`` 에는
새 키 ``frames_fill`` 만 더한다(``frames_D``·``time_D``·``candidate_frames`` 불변 — 자동 t* 재계산 결과 불변).

- 판정 표 ``DECIDE``(이 모듈 한 곳 — 워커·백엔드가 같은 표를 읽음, 사실 ``Facts`` 는 호출부가 모음, 위에서부터 첫 일치).
- 시도 기록 ``01_extract/frame_fill.json``(``esl/frame_fill/1``) 형식 소유 = 이 모듈(워커가 쓰고 코어 ESL 단계가 읽음).
- 쓰기 = 임시 파일 → 이전 파일 사본을 ``<Case>/_backup/<UTC>/01_extract/`` → os.replace(npz 2개 → json 마지막).

독립 모듈: numpy·esl.errors·esl.io.results_csv·esl.io.backup 만 import(esl.pipeline·esl.doe 금지), 설정을 해석하지 않는다
(``esl.io.bforce_ondemand`` 와 같은 규칙).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass

import numpy as np

from esl.errors import EslError
from esl.io import backup as _bk
from esl.io import results_csv as _rc

EXTRACT = "01_extract"
RECORD = "frame_fill.json"
RECORD_SCHEMA = "esl/frame_fill/1"
STATUSES = ("ok", "failed", "blocked")
FILL_MODE = "fr_only"                          # TCL 채움 모드 done.json mode
DISP_NPZ, STRAIN_NPZ, FRAMES_JSON = "disp.npz", "strain_frames.npz", "frames.json"
FILL_KEY = "frames_fill"                       # frames.json 새 키(채웠을 때만)

# 판정 표(계약 §2.4 — 위에서부터 첫 일치). when = Facts 의 참/거짓 조건 이름(None = 그 밖), action = have | block | fill.
# text 는 화면 문구 원본(백엔드 GET /tstar fill.text·422 FRAME_NOT_EXTRACTABLE text) — {name} = 입력 h3d 파일 이름.
DECIDE = (
    {"row": 1, "when": "have", "action": "have", "code": None, "text": None},
    {"row": 2, "when": "csv_input", "action": "block", "code": "NO_H3D",
     "text": "이 Case 는 h3d 없이 만든 것이라 후보 프레임만 고를 수 있습니다"},
    {"row": 3, "when": "dump_mode", "action": "block", "code": "DUMP_MODE",
     "text": "변형률을 순간값으로 받은 Case(덤프 방식)는 후보 프레임만 고를 수 있습니다"},
    {"row": 4, "when": "h3d_unreadable", "action": "block", "code": "H3D_UNREADABLE",
     "text": "입력 h3d 를 읽을 수 없습니다({name})"},
    {"row": 5, "when": "hw_unavailable", "action": "block", "code": "HW_UNAVAILABLE",
     "text": "서버 HyperWorks 를 쓸 수 없습니다(관리자 문의)"},
    {"row": 6, "when": None, "action": "fill", "code": None, "text": None},
)


@dataclass(frozen=True)
class Facts:
    """판정 사실(호출부가 모음 — 이 모듈은 파일·설정을 해석하지 않음, 단 ``extract_facts`` 가 01_extract 로 알 수 있는 2개를 줌).

    have        그 프레임이 disp.npz 와 strain_frames.npz 둘 다에 있음(D ∪ 이미 채운 프레임)
    csv_input   Case 입력이 결과 CSV 폴더(h3d 없음)
    dump_mode   추출이 덤프 방식(frames.json strain_fallback.mode == "dump")
    h3d_readable 입력 h3d 파일이 있고 읽힘
    hw_available 서버 hw 실행 파일·TCL 이 있음
    h3d_name    문구 {name}(h3d 파일 이름 — 없으면 "")"""
    have: bool
    csv_input: bool = False
    dump_mode: bool = False
    h3d_readable: bool = True
    hw_available: bool = True
    h3d_name: str = ""


def _hit(when: str | None, f: Facts) -> bool:
    if when is None:
        return True
    if when == "h3d_unreadable":
        return not f.h3d_readable
    if when == "hw_unavailable":
        return not f.hw_available
    return bool(getattr(f, when))


def decide(facts: Facts) -> dict:
    """DECIDE 첫 일치 행 → {row, action: have|block|fill, code: str|None, text: str|None}(text 의 {name} 채움)."""
    for r in DECIDE:
        if _hit(r["when"], facts):
            txt = None if r["text"] is None else r["text"].replace("{name}", str(facts.h3d_name or ""))
            return {"row": int(r["row"]), "action": r["action"], "code": r["code"], "text": txt}
    raise EslError("INTERNAL_ERROR", "frame_fill.DECIDE 에 맞는 행이 없음")      # 마지막 행이 그 밖이라 오지 않음


def _utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _npz_frames(path: str) -> list[int]:
    if not os.path.isfile(path):
        return []
    try:
        with np.load(path, allow_pickle=False) as z:
            return [int(x) for x in np.asarray(z["frame_index"]).reshape(-1)]
    except (OSError, KeyError, ValueError):
        return []


def have_frame(extract_dir: str, frame: int) -> bool:
    """그 프레임이 disp.npz 와 strain_frames.npz 둘 다에 있음(판정 표 행 1)."""
    f = int(frame)
    return f in _npz_frames(os.path.join(extract_dir, DISP_NPZ)) and f in _npz_frames(os.path.join(extract_dir, STRAIN_NPZ))


def frames_have(extract_dir: str) -> list[int]:
    """변위·변형률이 다 있는 프레임(오름차순) — API ``frames_have``."""
    a = set(_npz_frames(os.path.join(extract_dir, DISP_NPZ)))
    b = set(_npz_frames(os.path.join(extract_dir, STRAIN_NPZ)))
    return sorted(a & b)


def extract_facts(extract_dir: str, frame: int) -> dict:
    """01_extract 로 알 수 있는 사실 {have, dump_mode}(나머지 Facts 키는 호출부 — 입력 종류·h3d·hw)."""
    dump = False
    try:
        meta = _read_json(os.path.join(extract_dir, FRAMES_JSON))
        sf = meta.get("strain_fallback") if isinstance(meta, dict) else None
        dump = isinstance(sf, dict) and sf.get("mode") == "dump"
    except (OSError, ValueError):
        pass
    return {"have": have_frame(extract_dir, frame), "dump_mode": bool(dump)}


def fill_frames(frame: int) -> tuple[list[int], list[int]]:
    """채움 요청 프레임: ([f], [f−1]) — f = 0 이면 직전 없음([0], [])."""
    f = int(frame)
    if f < 0:
        raise EslError("INPUT_INVALID", f"프레임 번호 {frame} < 0")
    return [f], ([f - 1] if f > 0 else [])


def request_keys(meta: dict, frame: int) -> dict:
    """TCL 채움 요청 키(request.txt 에 더할 것 — 계약 §2.4): fr_only 1·fr_frames "<f>"·strain_sources = 추출 때 source 하나
    (frames.json strain_fallback.source — 추출과 같은 결과 유형을 고르게). 경계력(bf_on)·이름 후보·part·subcase 는 워커가 추출 때와
    같은 값으로 넣는다(이 모듈은 설정을 해석하지 않음). 덤프 방식 = INPUT_INVALID(판정 표 행 3 이 먼저 막음)."""
    fr, _prev = fill_frames(frame)
    sf = (meta or {}).get("strain_fallback") if isinstance(meta, dict) else None
    if isinstance(sf, dict) and sf.get("mode") == "dump":
        raise EslError("INPUT_INVALID", "덤프 방식 Case 는 채움 불가(DUMP_MODE)")
    src = _rc.strain_source_of(meta)
    return {"fr_only": "1", "fr_frames": " ".join(str(f) for f in fr), "strain_sources": src}


# ====================================================================== 병합
def merge(extract_dir: str, fill_out: str, frame: int, *, job_id: str | None = None) -> dict:
    """채움 출력(fill_out — TCL fr_only 의 disp.csv·strain_frames.csv·done.json) → extract_dir(<Case>/01_extract) 병합.

    같은 h3d 확인(done.json n_frames = frames.json n_frames_h3d, f·f−1 시각 = history.npz 시각 정확 일치 — 아니면
    FRAME_FILL_MISMATCH, 아무것도 쓰지 않음) → disp.npz·strain_frames.npz 끝에 프레임 f 덧붙임(이미 있으면 건드리지 않음 —
    added false) → frames.json frames_fill += {frame_index, time, at, job_id}. 반환 {frame, time, added: bool}.
    오류: FRAME_FILL_OUTPUT(채움 출력이 아님·요청 프레임 없음), FRAME_FILL_MISMATCH, FRAME_FILL_MERGE(01_extract 읽기)."""
    raise NotImplementedError("v0.25.2 C1 — 구현 중(접점 껍데기)")


# ====================================================================== 시도 기록
def _record_path(extract_dir: str) -> str:
    return os.path.join(extract_dir, RECORD)


def read_record(extract_dir: str) -> dict | None:
    """01_extract/frame_fill.json(없거나 읽기·형식 오류 = None)."""
    p = _record_path(extract_dir)
    if not os.path.isfile(p):
        return None
    try:
        doc = _read_json(p)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("attempts"), list):
        return None
    return doc


def attempts(extract_dir: str) -> list[dict]:
    doc = read_record(extract_dir)
    return [a for a in (doc or {}).get("attempts", []) if isinstance(a, dict)]


def record(extract_dir: str, attempt: dict) -> None:
    """시도 기록 1건 추가(누적, tmp → replace). attempt = {frame, job_id, status ok|failed|blocked, cause, detail, seconds, at}
    (frame·status 필수, at 없으면 지금). 기존 파일이 읽히지 않으면 <Case>/_backup/<UTC>/01_extract/ 로 옮긴 뒤 새로 시작."""
    if not isinstance(attempt, dict) or attempt.get("status") not in STATUSES:
        raise EslError("INPUT_INVALID", f"채움 시도 기록 status 는 {STATUSES} 중 하나: {attempt!r:.200}")
    try:
        int(attempt.get("frame"))
    except (TypeError, ValueError):
        raise EslError("INPUT_INVALID", "채움 시도 기록에 frame 이 없음") from None
    a = {"frame": int(attempt["frame"]), "job_id": attempt.get("job_id"), "status": attempt["status"],
         "cause": attempt.get("cause"), "detail": attempt.get("detail"), "seconds": attempt.get("seconds"),
         "at": attempt.get("at") or _utc()}
    p = _record_path(extract_dir)
    doc = read_record(extract_dir)
    if doc is None and os.path.isfile(p):             # 깨진 기록 = 지우지 않고 백업
        bdir = os.path.join(os.path.dirname(extract_dir), _bk.BACKUP_DIR, _bk.utc_stamp(), EXTRACT)
        os.makedirs(bdir, exist_ok=True)
        _bk.replace(p, _bk.free_target(bdir, RECORD))
    if doc is None:
        doc = {"schema": RECORD_SCHEMA, "attempts": []}
    doc["attempts"].append(a)
    os.makedirs(extract_dir, exist_ok=True)
    tmp = f"{p}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    _bk.replace(tmp, p)


def last_attempt(extract_dir: str, frame: int, job_id: str | None = None) -> dict | None:
    """그 프레임(job_id 를 주면 그 작업)의 마지막 시도(없으면 None) — 코어 ESL 단계 요약·작업 결과 frame_fill."""
    last = None
    for a in attempts(extract_dir):
        try:
            if int(a.get("frame")) != int(frame):
                continue
        except (TypeError, ValueError):
            continue
        if job_id is not None and str(a.get("job_id")) != str(job_id):
            continue
        last = a
    return last


def fill_entry(extract_dir: str, frame: int) -> dict | None:
    """frames.json frames_fill 에서 그 프레임 항목(없으면 None) — 채운 프레임인지(ESL 요약 tstar_manual.filled)."""
    try:
        meta = _read_json(os.path.join(extract_dir, FRAMES_JSON))
    except (OSError, ValueError):
        return None
    for e in (meta.get(FILL_KEY) or []) if isinstance(meta, dict) else []:
        try:
            if isinstance(e, dict) and int(e.get("frame_index")) == int(frame):
                return e
        except (TypeError, ValueError):
            continue
    return None
