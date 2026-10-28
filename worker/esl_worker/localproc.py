"""워커 LOCAL step 외부 프로그램 실행 공통(명령 규칙 esl.md §4.4) — hw 추출(h3d.py)·OptiStruct(os_solve.py)·비드 후처리.

- argv 는 설정 argv 템플릿에서만 만든다. argv[0] = `{<exe>}`(설정 검증이 보장, 여기서 한 번 더 확인), shell=False.
  치환값에 제어문자·cmd 메타문자 `& | < > ^ % ! "`(실행 파일이 .bat/.cmd 면 `; , = ( )` 추가)가 있으면 실행 전 거부
  (`INPUT_INVALID`). `*_fwd` = `/` 구분 경로(TCL 용).
- 프로세스 트리 종료(취소·lease 상실·시간 초과): POSIX 는 새 세션(프로세스 그룹) killpg(TERM → grace → KILL), Windows 는
  작업별 Job Object TerminateJobObject + taskkill /T /F 보조.
- 환경변수: ``child_env(passthrough, extra)`` — 워커 설정 ``worker.env_passthrough`` 키만 + 추가 키(OptiStruct 는
  ``opt_run.solve.env``). hw 추출은 기존대로 os.environ 전체(호환).
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from typing import Any

META = re.compile(r'[&|<>^%!"\x00-\x1f\x7f]')
BAT_META = re.compile(r"[;,=()]")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
BATCH_EXT = frozenset({"bat", "cmd"})      # 배치 파일이면 cmd 가 다시 해석하는 문자도 거부


class ProcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def fwd(p: str) -> str:
    return str(p).replace("\\", "/")


def build_argv(template: list[str], values: dict[str, str], *, exe: str, what: str) -> list[str]:
    """템플릿 → argv. argv[0] 은 {exe} 만(설정 검증과 이중), 치환값 메타문자 거부(INPUT_INVALID).
    what = 설정 키 이름(오류 메시지용, 예 commands.os_solve)."""
    if not template or template[0] != "{" + exe + "}":
        raise ProcError("CONFIG_INVALID", f"{what} argv[0] 은 {{{exe}}} 여야 합니다")
    is_bat = os.path.splitext(values.get(exe, ""))[1].lower().lstrip(".") in BATCH_EXT
    out: list[str] = []
    for i, tok in enumerate(template):
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in values:
                raise ProcError("CONFIG_INVALID", f"{what} 의 알 수 없는 placeholder {{{name}}}")
            v = values[name]
            if i == 0:
                bad = META.search(v)
            else:
                bad = META.search(v) or (is_bat and BAT_META.search(v))
            if bad:
                raise ProcError("INPUT_INVALID", f"{{{name}}} 값에 쓸 수 없는 문자({bad.group(0)!r})가 있습니다: {v}")
            return v
        out.append(PLACEHOLDER.sub(sub, tok))
    return out


def child_env(passthrough: list[str] | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """passthrough 키만 os.environ 에서 + extra. Windows 실행에 필요한 SYSTEMROOT 등은 passthrough 설정이 책임."""
    env = {k: os.environ[k] for k in (passthrough or []) if k in os.environ}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


def start(argv: list[str], *, cwd: str, log_fh, env: dict[str, str] | None = None, preexec=None,
          priority: str = "normal", fail_code: str = "LOCAL_PROCESS_FAILED", what: str = "외부 프로그램") -> subprocess.Popen:
    """시작(shell=False). 시작 실패(파일 없음·권한·자원 제한 preexec 실패) → ProcError(fail_code)."""
    try:
        if os.name == "nt":  # pragma: no cover - Windows 전용
            prio = {"idle": 0x00000040, "below_normal": 0x00004000}.get(priority, 0)
            flags = 0x00000200 | prio | 0x08000000      # CREATE_NEW_PROCESS_GROUP | 우선순위 | CREATE_NO_WINDOW
            return subprocess.Popen(argv, shell=False, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log_fh,
                                    stderr=subprocess.STDOUT, env=env, creationflags=flags)
        return subprocess.Popen(argv, shell=False, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log_fh,
                                stderr=subprocess.STDOUT, env=env, start_new_session=True, preexec_fn=preexec)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ProcError(fail_code, f"{what} 를 시작할 수 없습니다: {type(exc).__name__}: {exc}") from None


def kill_tree(proc: subprocess.Popen, grace_s: float, lim: Any = None) -> None:
    """프로세스와 그 자식 전부 종료. 이미 끝났으면 아무것도 하지 않는다(POSIX 는 그룹에 남은 자식도 정리)."""
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


class FileTail:
    """파일의 새 줄만 돌려준다(늦게 생겨도 됨, 줄 중간까지만 쓰였으면 보류, 깨진 인코딩은 대체문자).
    flush=True 는 끝에 개행이 없는 마지막 줄도 내보낸다(종료 후). 파일이 줄어들면(교체) 처음부터."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.pos = 0
        self.buf = b""

    def poll(self, flush: bool = False) -> list[str]:
        try:
            size = os.path.getsize(self.path)
            if size < self.pos:
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
