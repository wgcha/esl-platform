"""서버 h3d 추출(계약 esl_p3_ux.md §6, 명령 규칙 esl.md §4.4) — CASE_EXTRACT 첫 step H3D_EXTRACT(LOCAL).

- argv 는 설정 `commands.h3d_extract` 템플릿에서만 만든다. argv[0] = `{hw}` → `altair.hw_exe_path`(설정 검증이 보장),
  shell=False(localproc). 치환값에 제어문자·cmd 메타문자 `& | < > ^ % ! "`(hw 가 .bat/.cmd 면 `; , = ( )` 추가)가 있으면
  실행 전 거부(`INPUT_INVALID`). `*_fwd` = `/` 구분 경로(TCL 용).
- TCL = 코드 스냅샷 안 `resources/tcl/esl_h3d_extract.tcl`(설정 아님). 출력 = Case results_dir(`<esl_root>/_h3d/<폴더>/raw`),
  hw 작업 폴더·request.txt = `<esl_root>/_h3d/<폴더>/`. h3d 는 읽기만.
- 성공 = 종료코드 0 + done.json ok + frames.csv·model.csv 존재. 실패 → `H3D_EXTRACT_FAILED`(done.json 의 code·failed_step·
  error 를 메시지로, errorInfo 는 step 로그로).
- 시작 전 출력 폴더의 이전 done.json·CSV 는 `<out>/_backup/<UTC>/`로 옮긴다(삭제 없음, TCL 의 백업 규칙과 같음).
- 프로세스 트리 종료(취소·lease 상실): POSIX 는 새 세션(프로세스 그룹) killpg(TERM → grace → KILL), Windows 는 작업별
  Job Object TerminateJobObject + taskkill /T /F 보조.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import localproc
from .localproc import (  # noqa: F401 - 기존 import 경로 유지
    BAT_META,
    BATCH_EXT,
    META,
    PLACEHOLDER,
    fwd,
)

FAILURE = "H3D_EXTRACT_FAILED"
REQUIRED_OUTPUTS = ("done.json", "frames.csv", "model.csv")
H3dError = localproc.ProcError       # 공통화(localproc) — 기존 except h3d.H3dError 그대로


def values_for(*, hw: str, tcl: str, h3d: str, request: str, out_dir: str, part: str, hot_k: int,
               top_n: int) -> dict[str, str]:
    return {"hw": hw, "extract_tcl": tcl, "extract_tcl_fwd": fwd(tcl), "h3d": h3d, "h3d_fwd": fwd(h3d),
            "request": request, "request_fwd": fwd(request), "request_json": request, "request_json_fwd": fwd(request),
            "out_dir": out_dir, "out_dir_fwd": fwd(out_dir), "part": str(part), "hot_k": str(int(hot_k)),
            "top_n": str(int(top_n))}


def build_argv(template: list[str], values: dict[str, str]) -> list[str]:
    """템플릿 → argv. argv[0] 은 {hw} 만(설정 검증과 이중), 치환값 메타문자 거부(INPUT_INVALID)."""
    return localproc.build_argv(template, values, exe="hw", what="commands.h3d_extract")


def write_request(path: str, *, part: str, hot_k: int, top_n: int, extra: dict[str, str] | None = None) -> None:
    """request.txt(key<TAB>value, TCL 고급 옵션). -part·-hot_k·-top_n 인자가 우선이지만 인자 전달이 안 되는 설치본 대비.

    extra: 누적 씬 키(prev_file·frame0_pass·cum_min_incr — 계약 esl_cumulative_input.md §6.5). 없으면 기존과 같은 내용.
    """
    lines = ["# ESL 서버 h3d 추출 요청(워커가 작성)", f"part_title\t{part}", f"hot_k\t{int(hot_k)}", f"top_n\t{int(top_n)}"]
    for k, v in (extra or {}).items():
        if "\t" in str(v) or "\n" in str(v) or "\r" in str(v):
            raise H3dError("INPUT_INVALID", f"request.txt 값에 탭·줄바꿈: {k}")
        lines.append(f"{k}\t{v}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


PROGRESS_LOG = "progress.log"      # TCL(::esl::progress)이 출력 폴더에 append 하는 진행 로그
PROGRESS_HEARTBEAT_S = 60.0        # 새 줄이 없을 때 하트비트 간격 기본값(worker.progress_heartbeat_s 가 있으면 그것)
PROGRESS_POLL_S = 1.0              # progress.log 확인 주기


class ProgressTail(localproc.FileTail):
    """<out_dir>/progress.log 의 새 줄만 돌려준다(localproc.FileTail)."""

    def __init__(self, out_dir: str) -> None:
        super().__init__(os.path.join(out_dir, PROGRESS_LOG))


PROGRESS_LOAD_S_PER_GB = 40.0      # 모델 로드 구간(0→15%) 경과시간 기반 진행률의 예상 시간(h3d GB당 초)
_TS = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ")


def expected_load_s(h3d_path: str) -> float:
    try:
        gb = os.path.getsize(h3d_path) / (1024 ** 3)
    except OSError:
        gb = 1.0
    return min(1800.0, max(30.0, gb * PROGRESS_LOAD_S_PER_GB))


class ProgressTracker:
    """TCL progress.log 줄 → step 진행률(%, 단조 증가). 줄 자체는 영문 원문 그대로 작업 로그로 옮긴다.
    가중치: 모델 로드 0→15(로드 중엔 경과시간 기반), A 15→25, B 25→70(프레임), C 70→95(프레임·청크), 마무리 →99."""

    def __init__(self, expected_load_s: float = 60.0, now: float | None = None) -> None:
        self.pct = 0.0
        self.expected = max(1.0, expected_load_s)
        self.t0 = time.monotonic() if now is None else now
        self.loaded = False
        self.last_step = ""

    def _set(self, p: float) -> None:
        self.pct = max(self.pct, min(99.0, p))

    def tick(self, now: float | None = None) -> float:
        if not self.loaded:
            el = (time.monotonic() if now is None else now) - self.t0
            self._set(14.5 * min(el / self.expected, 1.0))
        return self.pct

    def feed(self, raw: str) -> float:
        ln = _TS.sub("", raw.strip())
        m: Any
        if ln.startswith("step "):
            self.last_step = ln[5:]
        elif re.match(r"part \S+.*: \d+ elements", ln) or ln.startswith("pass A start"):
            self.loaded = True
            self._set(15)
        elif (m := re.match(r"pass A \(frame \d+\) elements chunk (\d+)/(\d+)", ln)):
            self._set(15 + 10 * (int(m.group(1)) - 1) / int(m.group(2)))
        elif ln.startswith("pass A done"):
            self._set(25)
        elif (m := re.match(r"pass B frame (\d+)/(\d+)", ln)):
            self._set(25 + 45 * (int(m.group(1)) - 1) / int(m.group(2)))
        elif ln.startswith("candidate frames") or ln.startswith("pass B done"):
            self._set(70)
        elif (m := re.match(r"pass C frame \d+(?: \(prev\))? \((\d+)/(\d+)\) (elements|nodes) chunk (\d+)/(\d+)", ln)):
            k, kt, ci, cn = int(m.group(1)), int(m.group(2)), int(m.group(4)), int(m.group(5))
            frac = 0.9 * (ci - 1) / cn if m.group(3) == "elements" else 0.9 + 0.1 * (ci - 1) / cn
            self._set(70 + 25 * (k - 1 + frac) / max(1, kt))
        elif (m := re.match(r"dump frame (\d+)/(\d+) (elements|nodes) chunk (\d+)/(\d+)", ln)):
            k, kt, ci, cn = int(m.group(1)), int(m.group(2)), int(m.group(4)), int(m.group(5))
            frac = 0.9 * (ci - 1) / cn if m.group(3) == "elements" else 0.9 + 0.1 * (ci - 1) / cn
            self._set(15 + 80 * (k - 1 + frac) / max(1, kt))
        elif ln.startswith("pass C done") or ln.startswith("dump done"):
            self._set(95)
        elif ln.startswith("extract done"):
            self._set(98)
        return self.pct


def dir_size_mb(out_dir: str) -> float:
    """출력 폴더(바로 아래 파일, _backup 제외)의 합계 MB."""
    total = 0
    try:
        with os.scandir(out_dir) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                except OSError:
                    pass
    except OSError:
        return 0.0
    return total / (1024 * 1024)


def backup_previous(out_dir: str) -> str | None:
    """이전 실행 산출물(done.json·*.csv)을 <out_dir>/_backup/<UTC>[_N]/ 로 옮긴다(삭제 없음) — hw 가 TCL 실행 전에 죽어도
    이전 done.json 을 이번 결과로 읽지 않게. 옮긴 폴더(없으면 None)."""
    names = [n for n in sorted(os.listdir(out_dir)) if os.path.isfile(os.path.join(out_dir, n))
             and (n == "done.json" or n == PROGRESS_LOG or n.lower().endswith(".csv"))]
    if not names:
        return None
    base = os.path.join(out_dir, "_backup", time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
    dst, k = base, 1
    while os.path.exists(dst):
        dst = f"{base}_{k}"
        k += 1
    os.makedirs(dst)
    for n in names:
        os.replace(os.path.join(out_dir, n), os.path.join(dst, n))
    return dst


PREV_CSV = "prev.csv"


def backup_prev_csv(work: str) -> str | None:
    """<work>/prev.csv(이전 추출의 누적 씬 이전 소성 CSV)를 <work>/_backup/<UTC>[_N]/ 로 옮긴다(삭제 없음)."""
    src = os.path.join(work, PREV_CSV)
    if not os.path.isfile(src):
        return None
    base = os.path.join(work, "_backup", time.strftime("%Y%m%d_%H%M%S", time.gmtime()))
    dst, k = base, 1
    while os.path.exists(os.path.join(dst, PREV_CSV)):
        dst = f"{base}_{k}"
        k += 1
    os.makedirs(dst, exist_ok=True)
    os.replace(src, os.path.join(dst, PREV_CSV))
    return dst


def strain_request(core_settings: dict | None) -> dict[str, str]:
    """h3d 변형률 결과 대체 키(계약 esl_strain_fallback.md §2) — 설정 extract.strain_sources·이름 후보 → request.txt.
    strain_sources 는 공백 구분, 이름 후보는 '|' 구분(이름에 공백 있음). strain_type·epsp_type 은 쓰지 않는다(쓰면 TCL 이
    Max_Strain 만 보는 하위 호환 모드)."""
    from . import core_adapter

    try:
        x = core_adapter.extract_source_settings(core_settings or {})
    except core_adapter.CoreError:              # 코어 없는 설치본: TCL 기본값(같은 값)
        return {}
    out = {"strain_sources": " ".join(x["strain_sources"])}
    for k, v in x["result_names"].items():
        out[f"names_{k}"] = "|".join(v)
    for k, v in x["tensor_comps"].items():
        out[f"comp_{k}"] = "|".join(v)
    out["vm_comps"] = "|".join(x["vm_comps"])
    out["scalar_comps"] = "|".join(x["scalar_comps"])
    out["layer_exclude"] = "|".join(x["tensor_layer_exclude"])
    return out


def cumulative_request(cum: dict[str, Any] | None, prev_path: str) -> dict[str, str]:
    """누적 씬이면 request 키 3개, 아니면 빈 dict(request.txt 불변)."""
    if not cum:
        return {}
    return {"prev_file": fwd(prev_path), "frame0_pass": "1", "cum_min_incr": repr(float(cum["min_increment"]))}


def read_done(out_dir: str) -> dict[str, Any] | None:
    p = os.path.join(out_dir, "done.json")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


SLIM_HINT = " — 압축 모드 h3d입니다(대상 파트·필요한 결과만 있음). 원본으로 다시 올리세요"


def evaluate(exit_code: int | None, out_dir: str, *, slim: bool = False) -> tuple[bool, str, list[str], dict[str, Any] | None]:
    """(성공, 실패 메시지, 로그에 덧붙일 줄, done). slim = 입력이 PC 압축 모드 h3d 면 실패 메시지에 원본 재업로드 힌트."""
    ok, msg, lines, done = _evaluate(exit_code, out_dir)
    if slim and not ok:
        msg += SLIM_HINT
        lines = [*lines, "[esl-worker] hint:" + SLIM_HINT]
    return ok, msg, lines, done


def _evaluate(exit_code: int | None, out_dir: str) -> tuple[bool, str, list[str], dict[str, Any] | None]:
    done = read_done(out_dir)
    lines: list[str] = []
    if done is not None and not done.get("ok"):
        lines.append(f"[esl-worker] done.json ok=false code={done.get('code')} failed_step={done.get('failed_step')}")
        if done.get("error"):
            lines.append(f"[esl-worker] error: {done.get('error')}")
        if done.get("errorInfo"):
            lines.append("[esl-worker] errorInfo:")
            lines += [f"    {ln}" for ln in str(done["errorInfo"]).splitlines()]
    if exit_code != 0 or done is None or not done.get("ok"):
        if done is None:
            msg = f"hw 추출이 done.json 을 남기지 않았습니다(종료코드 {exit_code})"
        elif not done.get("ok"):
            parts = [f"failed_step={done.get('failed_step')}" if done.get("failed_step") else "",
                     f"code={done.get('code')}" if done.get("code") else "", str(done.get("error") or "")]
            msg = "hw 추출 실패: " + ", ".join(x for x in parts if x)
        else:
            msg = f"hw 가 비정상 종료했습니다(종료코드 {exit_code}, done.json ok=true)"
        return False, msg, lines, done
    missing = [n for n in REQUIRED_OUTPUTS if not os.path.isfile(os.path.join(out_dir, n))]
    if missing:
        return False, f"hw 추출 출력이 없습니다: {', '.join(missing)}", lines, done
    return True, "", lines, done


def done_summary(done: dict[str, Any] | None) -> dict[str, Any]:
    if not done:
        return {}
    keys = ("ok", "code", "failed_step", "part_id", "part_title", "n_frames", "n_elems", "n_nodes", "hot_k", "top_n",
            "frames_D", "strain_source", "strain_source_type", "strain_mode", "strain_layers", "epsp_available",
            "strain_tried")
    out = {k: done.get(k) for k in keys if k in done}
    if done.get("error"):
        out["error"] = str(done["error"])[:300]
    if done.get("warnings"):
        out["warnings"] = [str(w)[:200] for w in list(done["warnings"])[:20]]
    return out


# ---------------------------------------------------------------- 프로세스(localproc 공통)
def start(argv: list[str], *, cwd: str, log_fh, env: dict[str, str] | None = None, preexec=None,
          priority: str = "normal"):
    """hw 시작(shell=False). 시작 실패 → H3dError(H3D_EXTRACT_FAILED)."""
    return localproc.start(argv, cwd=cwd, log_fh=log_fh, env=env, preexec=preexec, priority=priority,
                           fail_code=FAILURE, what="hw")


kill_tree = localproc.kill_tree
