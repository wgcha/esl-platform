"""서버 h3d 추출(계약 esl_p3_ux.md §6, 명령 규칙 esl.md §4.4) — CASE_EXTRACT 첫 step H3D_EXTRACT(LOCAL).

- argv 는 설정 `commands.h3d_extract` 템플릿에서만 만든다. argv[0] = `{hw}` → `altair.hw_exe_path`(설정 검증이 보장),
  `subprocess` shell=False. 치환값에 제어문자·cmd 메타문자 `& | < > ^ % ! "`(hw 가 .bat/.cmd 면 `; , = ( )` 추가)가 있으면
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
import signal
import subprocess
import time
from typing import Any

FAILURE = "H3D_EXTRACT_FAILED"
META = re.compile(r'[&|<>^%!"\x00-\x1f\x7f]')
BAT_META = re.compile(r"[;,=()]")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
REQUIRED_OUTPUTS = ("done.json", "frames.csv", "model.csv")
BATCH_EXT = frozenset({"bat", "cmd"})      # 배치 파일이면 cmd 가 다시 해석하는 문자도 거부


class H3dError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def fwd(p: str) -> str:
    return str(p).replace("\\", "/")


def values_for(*, hw: str, tcl: str, h3d: str, request: str, out_dir: str, part: str, hot_k: int,
               top_n: int) -> dict[str, str]:
    return {"hw": hw, "extract_tcl": tcl, "extract_tcl_fwd": fwd(tcl), "h3d": h3d, "h3d_fwd": fwd(h3d),
            "request": request, "request_fwd": fwd(request), "request_json": request, "request_json_fwd": fwd(request),
            "out_dir": out_dir, "out_dir_fwd": fwd(out_dir), "part": str(part), "hot_k": str(int(hot_k)),
            "top_n": str(int(top_n))}


def build_argv(template: list[str], values: dict[str, str]) -> list[str]:
    """템플릿 → argv. argv[0] 은 {hw} 만(설정 검증과 이중), 치환값 메타문자 거부(INPUT_INVALID)."""
    if not template or template[0] != "{hw}":
        raise H3dError("CONFIG_INVALID", "commands.h3d_extract argv[0] 은 {hw} 여야 합니다")
    is_bat = os.path.splitext(values.get("hw", ""))[1].lower().lstrip(".") in BATCH_EXT
    out: list[str] = []
    for i, tok in enumerate(template):
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in values:
                raise H3dError("CONFIG_INVALID", f"commands.h3d_extract 의 알 수 없는 placeholder {{{name}}}")
            v = values[name]
            if i == 0:
                bad = META.search(v)
            else:
                bad = META.search(v) or (is_bat and BAT_META.search(v))
            if bad:
                raise H3dError("INPUT_INVALID", f"{{{name}}} 값에 쓸 수 없는 문자({bad.group(0)!r})가 있습니다: {v}")
            return v
        out.append(PLACEHOLDER.sub(sub, tok))
    return out


def write_request(path: str, *, part: str, hot_k: int, top_n: int) -> None:
    """request.txt(key<TAB>value, TCL 고급 옵션). -part·-hot_k·-top_n 인자가 우선이지만 인자 전달이 안 되는 설치본 대비."""
    lines = ["# ESL 서버 h3d 추출 요청(워커가 작성)", f"part_title\t{part}", f"hot_k\t{int(hot_k)}", f"top_n\t{int(top_n)}"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


PROGRESS_LOG = "progress.log"      # TCL(::esl::progress)이 출력 폴더에 append 하는 진행 로그
PROGRESS_HEARTBEAT_S = 60.0        # 새 줄이 없을 때 하트비트 간격 기본값(worker.progress_heartbeat_s 가 있으면 그것)
PROGRESS_POLL_S = 1.0              # progress.log 확인 주기


class ProgressTail:
    """<out_dir>/progress.log 의 새 줄만 돌려준다. 파일이 늦게 생겨도 되고, 줄 중간까지만 쓰였으면 완성될 때까지 보류,
    인코딩이 깨져도 대체문자로 읽는다. flush=True 는 끝에 개행이 없는 마지막 줄도 내보낸다(종료 후)."""

    def __init__(self, out_dir: str) -> None:
        self.path = os.path.join(out_dir, PROGRESS_LOG)
        self.pos = 0
        self.buf = b""

    def poll(self, flush: bool = False) -> list[str]:
        try:
            size = os.path.getsize(self.path)
            if size < self.pos:                       # 잘렸거나 교체됨 → 처음부터
                self.pos, self.buf = 0, b""
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                data = fh.read()
        except OSError:
            return []
        self.pos += len(data)
        self.buf += data
        parts = self.buf.split(b"\n")
        self.buf = parts.pop()
        if flush and self.buf:
            parts.append(self.buf)
            self.buf = b""
        out = []
        for raw in parts:
            ln = raw.decode("utf-8", errors="replace").rstrip("\r")
            if ln.strip():
                out.append(ln)
        return out


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
        elif ln.startswith("pass C done"):
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
            "frames_D")
    out = {k: done.get(k) for k in keys if k in done}
    if done.get("error"):
        out["error"] = str(done["error"])[:300]
    if done.get("warnings"):
        out["warnings"] = [str(w)[:200] for w in list(done["warnings"])[:20]]
    return out


# ---------------------------------------------------------------- 프로세스
def start(argv: list[str], *, cwd: str, log_fh, env: dict[str, str] | None = None, preexec=None,
          priority: str = "normal") -> subprocess.Popen:
    """hw 시작(shell=False). 시작 실패(파일 없음·권한·자원 제한 preexec 실패) → H3dError."""
    try:
        if os.name == "nt":  # pragma: no cover - Windows 전용
            prio = {"idle": 0x00000040, "below_normal": 0x00004000}.get(priority, 0)
            flags = 0x00000200 | prio | 0x08000000      # CREATE_NEW_PROCESS_GROUP | 우선순위 | CREATE_NO_WINDOW
            return subprocess.Popen(argv, shell=False, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log_fh,
                                    stderr=subprocess.STDOUT, env=env, creationflags=flags)
        return subprocess.Popen(argv, shell=False, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log_fh,
                                stderr=subprocess.STDOUT, env=env, start_new_session=True, preexec_fn=preexec)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise H3dError(FAILURE, f"hw 를 시작할 수 없습니다: {type(exc).__name__}: {exc}") from None


def kill_tree(proc: subprocess.Popen, grace_s: float, lim: Any = None) -> None:
    """hw 와 그 자식 전부 종료. 이미 끝났으면 아무것도 하지 않는다(POSIX 는 그룹에 남은 자식도 정리)."""
    if os.name == "nt":  # pragma: no cover - Windows 전용
        term = getattr(lim, "terminate", None)
        if term is not None:
            try:
                term(1)
            except Exception:  # noqa: BLE001 - 보조 수단으로 이어감
                pass
        if proc.poll() is None:
            cmd = ["taskkill", "/PID", str(proc.pid), "/T", "/F"]
            subprocess.run(cmd, shell=False, capture_output=True)
        try:
            proc.wait(grace_s)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        pgid = proc.pid
    for sig, wait in ((signal.SIGTERM, grace_s), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            break
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if proc.poll() is not None and not _group_alive(pgid):
                return
            time.sleep(0.05)
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True
