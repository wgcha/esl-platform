"""paicad 외부 명령 실행(계약 esl_bead_doe.md §6.1·§6.2·§6.5, BD-D-19) — 워커 LOCAL step(BD_GEOM·BD_GRID·BD_DESIGNS)만.

- argv = 작업 스냅샷 ``commands.paicad_*`` 템플릿 → ``esl.doe.paicad_io.command_argv``(선택 쌍 규칙: ``{name?}`` 가 None
  이면 앞 플래그와 함께 제거, 빈 문자열 유지 — ③ ``--fixed-dir ""``). argv[0] ``{paicad}`` = 워커 설정
  ``bead_doe.paicad.exe``(없으면 스냅샷 값). 치환값의 제어문자·cmd 메타문자는 실행 전 거부(``INPUT_INVALID``,
  localproc 규칙과 같음). 경로 값은 realpath 가 허용 루트 안이어야 한다(출력 = ``_doe/<id>/`` 안, 입력 = 그 안 또는
  storage.input_roots — 링크 성분 거부). 사용자 문자열(제목·파트 제목)은 넣지 않는다(파트 = id).
- 실행: ``localproc.start``(shell=False, POSIX 새 세션 / Windows 새 프로세스 그룹), cwd = 호출자가 정한 폴더(출력 폴더의
  부모), stdout·stderr → ``capture`` 파일(호출마다 새 파일). 타임아웃(``bead_doe.paicad.timeout_s.<명령>``)·취소
  (``stop`` Event 또는 ``tick`` 예외)·lease 상실 시 **프로세스 트리 종료**(``localproc.kill_tree``).
- 환경 변수(최소, v0.8.0 os_solve 와 같은 방식): 기본 OS 키 + paicad·OCP 가 쓰는 키(``PAICAD_ENV_KEYS``) +
  ``worker.env_passthrough`` + ``bead_doe.paicad.env`` + 고정 ``PYTHONUTF8=1``·``PYTHONIOENCODING=utf-8``(콘솔 스크립트
  stdout 을 UTF-8 로 — PROGRESS 메시지 깨짐 방지). 워커의 PYTHONPATH 등 나머지는 넘기지 않는다.
- stdout ``PAICAD PROGRESS n msg`` → ``on_progress(n, msg)``, 전 줄 → ``on_line``(로그 중계). 끝나면
  ``paicad_io.judge``(§6.2: 종료 0 + RESULT OK/PASS + 보고 JSON status OK/PASS = 성공, 코드 분류 §6.3).
- 버전 점검(§6.5): ``version_check`` = ``{paicad} version --json`` → ``paicad_io.check_version`` + checked_at,
  ``gmsh_check`` = 별도 python 프로세스에서 ``import gmsh``(공유 라이브러리 누락도 잡음). 워커 heartbeat
  ``info.paicad``·``info.gmsh`` 로 기록(백엔드는 실행하지 않고 읽기만).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import threading
import time
from typing import Any, Callable

from . import localproc
from .os_solve import BASE_ENV_KEYS

PAICAD_ENV_KEYS = ("TMPDIR", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "ProgramData")   # OCP·Python 임시·캐시 폴더
FIXED_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
TIMEOUT_KEY = {"paicad_version": "version", "paicad_fixed_scan": "fixed_scan", "paicad_extract": "extract",
               "paicad_tag": "tag", "paicad_grid": "grid", "paicad_run": "run", "paicad_update": "update"}
OUT_KEYS = ("out_dir", "update_dir", "morph_dir", "check_dir", "out_files_dir")
POLL_S = 0.1


class PaicadError(Exception):
    """실행 전·시작 실패(설정·경로·메타문자·exe 없음) — 호출자가 작업 실패 코드로."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class PaicadCanceled(Exception):
    """stop Event 로 중단(프로세스 트리는 이미 종료)."""


# ---------------------------------------------------------------- 설정
def _pio():
    from . import core_adapter

    return core_adapter.doe_paicad_io()


def exe_path(settings, cfg: dict | None = None) -> str | None:
    bd = getattr(settings, "bead_doe", None)
    p = bd.paicad.exe if bd is not None else None
    if not p:
        p = (((cfg or {}).get("bead_doe") or {}).get("paicad") or {}).get("exe")
    return p or None


def child_env(settings) -> dict[str, str]:
    bd = getattr(settings, "bead_doe", None)
    extra = dict(FIXED_ENV)
    extra.update({str(k): str(v) for k, v in ((bd.paicad.env if bd is not None else None) or {}).items()})
    keys = list(BASE_ENV_KEYS) + list(PAICAD_ENV_KEYS) + list(settings.worker.env_passthrough or [])
    return localproc.child_env(keys, extra)


def timeout_s(dcfg: dict, key: str) -> float:
    return float((dcfg.get("paicad") or {}).get("timeout_s", {}).get(TIMEOUT_KEY[key]) or 3600)


# ---------------------------------------------------------------- 경로·argv
def _within(p: str, root: str) -> bool:
    p, root = os.path.normcase(p), os.path.normcase(root)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def _no_links(p: str, root: str) -> None:
    """root 아래 p 까지의 기존 성분에 심링크·정션이 없어야 함."""
    rel = os.path.relpath(os.path.abspath(p), os.path.abspath(root))
    cur = os.path.abspath(root)
    for comp in [] if rel == "." else rel.split(os.sep):
        cur = os.path.join(cur, comp)
        if os.path.islink(cur) or (hasattr(os.path, "isjunction") and os.path.isjunction(cur)):
            raise PaicadError("PATH_OUTSIDE_ROOT", f"paicad 경로에 링크가 있습니다: {os.path.basename(cur)}")


def check_paths(values: dict[str, Any], out_root: str, in_roots: list[str]) -> None:
    """경로 값 realpath 검사(§6.1 값 출처): 출력 = out_root 안, 입력 = out_root 또는 in_roots 안. 빈 문자열(③ fixed_dir)·
    None(선택 자리)은 건너뜀."""
    pio = _pio()
    out_real = os.path.realpath(out_root)
    ins = [os.path.realpath(r) for r in in_roots]
    for k in pio.PATH_KEYS:
        v = values.get(k)
        if v in (None, ""):
            continue
        r = os.path.realpath(str(v))
        if k in OUT_KEYS:
            if not _within(r, out_real):
                raise PaicadError("PATH_OUTSIDE_ROOT", f"paicad 출력 경로({k})가 연구 폴더 밖입니다")
            _no_links(str(v), out_root)
            continue
        if _within(r, out_real):
            _no_links(str(v), out_root)
            continue
        root = next((x for x in ins if _within(r, x)), None)
        if root is None:
            raise PaicadError("PATH_OUTSIDE_ROOT", f"paicad 입력 경로({k})가 허용 루트 밖입니다")


def build_argv(key: str, values: dict[str, Any], cfg: dict, exe: str | None) -> list[str]:
    if not exe:
        raise PaicadError("PAICAD_NOT_CONFIGURED", "paicad 실행 파일(bead_doe.paicad.exe)이 설정되지 않았습니다")
    if not os.path.isfile(exe):
        raise PaicadError("PAICAD_NOT_FOUND", "paicad 실행 파일(bead_doe.paicad.exe)이 없습니다")
    try:
        argv = _pio().command_argv(key, {**values, "paicad": exe}, cfg)
    except Exception as exc:          # EslError(CONFIG_INVALID) — 코어 예외 타입에 묶이지 않게
        raise PaicadError(getattr(exc, "code", "CONFIG_INVALID"), getattr(exc, "message", str(exc))) from None
    is_bat = os.path.splitext(exe)[1].lower().lstrip(".") in localproc.BATCH_EXT
    for i, tok in enumerate(argv):
        bad = localproc.META.search(tok) or (i > 0 and is_bat and localproc.BAT_META.search(tok))
        if bad:
            raise PaicadError("INPUT_INVALID", f"paicad 인자에 쓸 수 없는 문자({bad.group(0)!r})가 있습니다")
    return argv


# ---------------------------------------------------------------- 실행
class Procs:
    """동시 실행 중인 paicad·코어 자식 프로세스 목록(취소·lease 상실 시 한꺼번에 트리 종료)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: set = set()
        self.stop = threading.Event()

    def add(self, p) -> None:
        with self.lock:
            self.items.add(p)

    def remove(self, p) -> None:
        with self.lock:
            self.items.discard(p)

    def kill_all(self, grace_s: float, lim: Any = None) -> None:
        self.stop.set()
        with self.lock:
            items = list(self.items)
        for p in items:
            try:
                if hasattr(p, "poll"):           # Popen(paicad)
                    localproc.kill_tree(p, grace_s, lim)
                elif p.is_alive():               # multiprocessing.Process(코어)
                    p.terminate()
                    p.join(grace_s)
                    if p.is_alive():
                        p.kill()
                        p.join(5)
            except Exception:  # noqa: BLE001 - 종료 중 오류는 무시(이미 끝난 프로세스)
                pass


def run(key: str, values: dict[str, Any], *, settings, cfg: dict, out_root: str, in_roots: list[str], cwd: str,
        capture: str, report: str | None, stage: str, lim: Any = None, procs: Procs | None = None,
        tick: Callable[[], None] | None = None, on_progress: Callable[[int, str], None] | None = None,
        on_line: Callable[[str], None] | None = None, on_start: Callable[[list[str], int], None] | None = None
        ) -> dict[str, Any]:
    """paicad 명령 1회 → {ok, code, status, message, paicad_code, exit_code, timeout, seconds, argv, warnings, report}.

    stage = paicad_io.judge 단계(prep|preview|design). tick = 주 스레드 주기 작업(lease 갱신·취소 — 예외를 내면 트리
    종료 후 그대로 전파), procs.stop = 다른 스레드 취소 신호(→ PaicadCanceled)."""
    from . import limiter

    dcfg = cfg.get("bead_doe") or {}
    exe = exe_path(settings, cfg)
    argv = build_argv(key, values, cfg, exe)
    check_paths(values, out_root, in_roots)
    os.makedirs(cwd, exist_ok=True)
    to = timeout_s(dcfg, key)
    grace = float(settings.worker.terminate_grace_s)
    t0 = time.monotonic()
    timed_out = False
    pio = _pio()
    lines: list[str] = []
    with open(capture, "wb") as fh:                 # 호출마다 새 내용(판정은 이 명령의 stdout 만)
        try:
            proc = localproc.start(argv, cwd=cwd, log_fh=fh, env=child_env(settings), preexec=limiter.posix_preexec(lim),
                                   priority=settings.worker.priority, fail_code="PAICAD_FAILED", what="paicad")
        except localproc.ProcError as exc:
            raise PaicadError(exc.code, exc.message) from None
        if procs is not None:
            procs.add(proc)
        try:
            if lim is not None:
                try:
                    limiter.attach_popen(lim, proc)
                except limiter.LimiterError as exc:
                    raise PaicadError(limiter.FAILURE_CODE, str(exc)) from None
            if on_start is not None:
                on_start(argv, proc.pid)
            tail = localproc.FileTail(capture)

            def drain(flush: bool = False) -> None:
                for ln in tail.poll(flush=flush):
                    lines.append(ln)
                    if on_line is not None:
                        on_line(ln)
                    p = pio.parse_line(ln)
                    if p is not None and p[0] == "progress" and on_progress is not None:
                        on_progress(int(p[1]), str(p[2]))

            while proc.poll() is None:
                time.sleep(POLL_S)
                drain()
                if procs is not None and procs.stop.is_set():
                    raise PaicadCanceled()
                if tick is not None:
                    tick()
                if time.monotonic() - t0 > to:
                    timed_out = True
                    break
            if timed_out:
                localproc.kill_tree(proc, grace, lim)
            drain(flush=True)
        except BaseException:
            localproc.kill_tree(proc, grace, lim)
            raise
        finally:
            if procs is not None:
                procs.remove(proc)
        localproc.kill_tree(proc, grace, lim)      # 그룹에 남은 자식 정리(이미 끝났으면 아무것도 안 함)
    code = None if timed_out else proc.returncode
    j = pio.judge(stage, code, "\n".join(lines), report, timeout=timed_out,
                     max_mb=float((dcfg.get("limits") or {}).get("max_json_mb") or 64))
    return {"ok": bool(j["ok"]), "code": j.get("code"), "status": j.get("status"), "message": j.get("message"),
            "paicad_code": j.get("paicad_code"), "detail": j.get("detail"), "exit_code": code, "timeout": timed_out,
            "seconds": round(time.monotonic() - t0, 3), "argv": argv, "warnings": list(j.get("warnings") or []),
            "report": j.get("report")}


# ---------------------------------------------------------------- 점검(§6.5)
def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def version_check(settings, cfg: dict | None = None) -> dict[str, Any]:
    """{ready, version, ocp, pinned, warning, reason, checked_at} (= paicad_io.check_version + 시각).
    exe 없음 → PAICAD_NOT_CONFIGURED·PAICAD_NOT_FOUND, 실행 실패·JSON 아님 → PAICAD_CHECK_FAILED."""
    from . import core_adapter

    dcfg = core_adapter.doe_settings(cfg if cfg is not None else _settings_cfg(settings))
    full = cfg if cfg is not None else _settings_cfg(settings)
    pinned = (dcfg.get("paicad") or {}).get("pinned_version")
    base = {"ready": False, "version": None, "ocp": None, "pinned": pinned, "warning": None, "checked_at": _now()}
    exe = exe_path(settings, full)
    if not exe:
        return {**base, "reason": "PAICAD_NOT_CONFIGURED"}
    if not os.path.isfile(exe):
        return {**base, "reason": "PAICAD_NOT_FOUND"}
    try:
        argv = build_argv("paicad_version", {}, full, exe)
        code, out = localproc.run_capture(argv, cwd=os.path.dirname(exe), env=child_env(settings),
                                          timeout_s=timeout_s(dcfg, "paicad_version"), what="paicad version")
        if code != 0:
            return {**base, "reason": "PAICAD_CHECK_FAILED"}
        pio = _pio()
        v = pio.check_version(pio.parse_version_json(out.decode("utf-8", errors="replace").strip()), dcfg)
    except (localproc.ProcError, PaicadError, core_adapter.CoreError):
        return {**base, "reason": "PAICAD_CHECK_FAILED"}
    except Exception as exc:  # noqa: BLE001 - EslError(PAICAD_CHECK_FAILED) 등
        return {**base, "reason": getattr(exc, "code", "PAICAD_CHECK_FAILED")}
    return {**v, "checked_at": base["checked_at"]}


def gmsh_check(timeout: float = 60.0) -> dict[str, Any]:
    """{ready, version} — 별도 python 프로세스에서 import(공유 라이브러리 누락·크래시가 워커에 영향 없음)."""
    code = "import json, gmsh; print(json.dumps({'version': str(getattr(gmsh, '__version__', '') or '') or None}))"
    try:
        rc, out = localproc.run_capture([sys.executable, "-c", code], cwd=None, env=None, timeout_s=timeout, what="gmsh")
        if rc != 0:
            return {"ready": False, "version": None}
        return {"ready": True, "version": json.loads(out.decode("utf-8", errors="replace").strip()).get("version")}
    except (localproc.ProcError, ValueError):
        return {"ready": False, "version": None}


def _settings_cfg(settings) -> dict:
    """워커 설정 → 작업 스냅샷과 같은 모양의 cfg(bead_doe·commands)."""
    from esl_platform.core.config import bead_doe_commands, bead_doe_settings

    return {"bead_doe": bead_doe_settings(settings), "commands": bead_doe_commands(settings)}


class StatusCache:
    """heartbeat 용 paicad·gmsh 점검 캐시(``bead_doe.paicad.check_interval_s`` 마다 다시)."""

    def __init__(self) -> None:
        self.at = 0.0
        self.value: dict[str, Any] | None = None
        self.lock = threading.Lock()

    def get(self, settings, *, force: bool = False) -> dict[str, Any] | None:
        bd = getattr(settings, "bead_doe", None)
        if bd is None or not bd.enabled:
            return None
        iv = float(bd.paicad.check_interval_s)
        with self.lock:
            if not force and self.value is not None and time.monotonic() - self.at < iv:
                return self.value
            self.value = {"paicad": version_check(settings), "gmsh": gmsh_check()}
            self.at = time.monotonic()
            return self.value
