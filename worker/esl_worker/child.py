"""코어 실행 자식 프로세스(multiprocessing spawn 대상).

- stdout·stderr(파일 기술자 1·2 포함)를 step 로그 파일로 돌리고 코어 `echo`도 같은 파일에 쓴다.
- 결과는 `result_path`에 JSON `{ok, code?, message?}`로 남긴다(부모가 읽음). 종료코드 0 = 성공, 1 = 실패.
- 취소는 부모가 이 프로세스를 terminate/kill 한다(코어는 외부 프로그램을 띄우지 않으므로 손자 프로세스 없음).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
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


def _lower_priority(priority: str) -> None:
    if priority == "normal" or not hasattr(os, "nice"):
        return
    try:
        os.nice(5 if priority == "below_normal" else 15)
    except OSError:
        pass


def _write_result(path: str, d: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, path)


def run_core(spec: dict[str, Any], echo) -> dict[str, Any]:
    """기본 대상: 어댑터로 esl.pipeline.run 1회."""
    from esl_worker import core_adapter

    rec = core_adapter.run_pipeline(spec["cfg"], spec["rad"], spec["results"], spec["out"], spec["stage"],
                                    frame=spec.get("frame"), support_nodes=spec.get("support_nodes"), echo=echo)
    return {"error": (rec or {}).get("error")}


def _resolve(target: str):
    mod, _, fn = target.partition(":")
    return getattr(importlib.import_module(mod), fn)


def child_entry(spec: dict[str, Any]) -> None:
    fh = _redirect(spec["log_path"])
    _lower_priority(spec.get("priority", "normal"))

    def echo(msg: str) -> None:
        fh.write(str(msg) + "\n")
        fh.flush()

    t0 = time.time()
    echo(f"[esl-worker] pid {os.getpid()} stage={spec.get('stage')} 시작")
    code = 0
    try:
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
    except BaseException as exc:  # noqa: BLE001 - 자식 프로세스 최상위
        traceback.print_exc(file=fh)
        _write_result(spec["result_path"], {"ok": False, "code": "INTERNAL_ERROR",
                                            "message": f"{type(exc).__name__}: {exc}"[:450]})
        code = 1
    finally:
        fh.flush()
    os._exit(code)
