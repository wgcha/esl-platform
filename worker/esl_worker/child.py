"""코어 실행 자식 프로세스(multiprocessing spawn 대상).

- stdout·stderr(파일 기술자 1·2 포함)를 step 로그 파일로 돌리고 코어 `echo`도 같은 파일에 쓴다.
- 결과는 `result_path`에 JSON `{ok, code?, message?}`로 남긴다(부모가 읽음). 종료코드 0 = 성공, 1 = 실패.
- 취소는 부모가 이 프로세스를 terminate/kill 한다(코어는 외부 프로그램을 띄우지 않으므로 손자 프로세스 없음).
- 자원 제한(esl_worker.limiter): 코어 import 전에 부모의 시작 신호를 기다리고(Windows 는 그 전에 Job Object 에 들어감)
  POSIX 는 nice·RLIMIT_AS·CPU 선호도를 스스로 건다. 적용 결과는 로그 `[esl-worker] 자원 제한 …` 줄. 실패 → `LIMITER_FAILED`.
- 고아 방지: 부모(워커)가 비정상 종료하면(kill·크래시) 감시 스레드가 `PARENT_CHECK_S` 안에 이 프로세스를
  끝낸다(`os._exit(PARENT_LOST_EXIT)`). 판정 = multiprocessing 부모 sentinel 닫힘(Windows·POSIX 공통) 또는
  POSIX 에서 getppid() 가 spec.parent_pid 와 달라짐(재부모화).
"""

from __future__ import annotations

import importlib
import json
import multiprocessing
import os
import sys
import threading
import time
import traceback
from typing import Any


def _redirect(log_path: str):
    fh = open(log_path, "a", encoding="utf-8", buffering=1)
    try:
        os.dup2(fh.fileno(), 1)
        os.dup2(fh.fileno(), 2)
    except OSError:
        pass
    sys.stdout = fh
    sys.stderr = fh
    return fh


def _write_result(path: str, d: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, path)


def run_core(spec: dict[str, Any], echo) -> dict[str, Any]:
    """기본 대상: 어댑터로 esl.pipeline.run 1회. 라이브러리 단계(lib_*)는 어댑터의 run_library_stage."""
    from esl_worker import core_adapter

    if str(spec.get("stage") or "").startswith("lib_"):
        core_adapter.run_library_stage(spec, echo)
        return {"error": None}

    rec = core_adapter.run_pipeline(spec["cfg"], spec["rad"], spec["results"], spec["out"], spec["stage"],
                                    frame=spec.get("frame"), support_nodes=spec.get("support_nodes"), echo=echo,
                                    export_targets=spec.get("export_targets"), tag=spec.get("tag"))
    return {"error": (rec or {}).get("error")}


PARENT_CHECK_S = 0.5
PARENT_LOST_EXIT = 3


def parent_alive(parent_pid: int | None) -> bool:
    pp = multiprocessing.parent_process()
    if pp is not None and not pp.is_alive():
        return False
    if parent_pid and os.name != "nt" and os.getppid() != parent_pid:
        return False
    return True


def start_parent_watch(parent_pid: int | None, on_lost=None, interval: float = PARENT_CHECK_S) -> threading.Thread:
    def watch() -> None:
        while True:
            time.sleep(interval)
            if not parent_alive(parent_pid):
                if on_lost is not None:
                    on_lost()
                os._exit(PARENT_LOST_EXIT)

    t = threading.Thread(target=watch, name="esl-parent-watch", daemon=True)
    t.start()
    return t


def _resolve(target: str):
    mod, _, fn = target.partition(":")
    return getattr(importlib.import_module(mod), fn)


def child_entry(spec: dict[str, Any]) -> None:
    fh = _redirect(spec["log_path"])

    def echo(msg: str) -> None:
        fh.write(str(msg) + "\n")
        fh.flush()

    start_parent_watch(spec.get("parent_pid"),
                       on_lost=lambda: echo("[esl-worker] 부모 워커 프로세스가 사라져 코어 실행을 중단합니다"))
    t0 = time.time()
    echo(f"[esl-worker] pid {os.getpid()} stage={spec.get('stage')} 시작")
    code = 0
    try:
        from esl_worker import limiter

        try:  # 부모 시작 신호(Windows Job 할당 뒤) 대기 + 자식 쪽 제한(POSIX nice·RLIMIT_AS·CPU 선호도) — 코어 import 전
            limiter.child_setup(spec, echo)
        except limiter.LimiterError as exc:
            echo(f"[esl-worker] 실패 {exc.code}: {exc}")
            _write_result(spec["result_path"], {"ok": False, "code": exc.code, "message": str(exc)[:450]})
            fh.flush()
            os._exit(1)
        from esl_worker.core_adapter import CoreError

        try:
            fn = _resolve(spec.get("target") or "esl_worker.child:run_core")
            fn(spec, echo)
            _write_result(spec["result_path"], {"ok": True})
            echo(f"[esl-worker] 완료 ({time.time() - t0:.2f}s)")
        except CoreError as exc:
            echo(f"[esl-worker] 실패 {exc.code}: {exc.message}")
            _write_result(spec["result_path"], {"ok": False, "code": exc.code, "message": exc.message})
            code = 1
        except MemoryError as exc:  # 코어가 EslError 로 바꾸지 못한 메모리 부족(솔버 밖 대형 배열 등) — 특이·내부 오류와 구분
            msg = f"코어 처리 중 메모리 부족(MemoryError: {str(exc)[:200]}) — worker.max_memory_gb·vm_headroom·서버 메모리 확인"
            echo(f"[esl-worker] 실패 SOLVER_OUT_OF_MEMORY: {msg}")
            _write_result(spec["result_path"], {"ok": False, "code": "SOLVER_OUT_OF_MEMORY", "message": msg})
            code = 1
    except BaseException as exc:  # noqa: BLE001 - 자식 프로세스 최상위
        traceback.print_exc(file=fh)
        _write_result(spec["result_path"], {"ok": False, "code": "INTERNAL_ERROR",
                                            "message": f"{type(exc).__name__}: {exc}"[:450]})
        code = 1
    finally:
        fh.flush()
    os._exit(code)
