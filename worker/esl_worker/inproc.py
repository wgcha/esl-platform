"""v0.12.3 워커 프로세스 안 장시간 호출(파일 사본·해시·rad 스캔 등) — lease 를 잃지 않게 작업 스레드에서 실행(이슈 #44).

``call(ex, fn, label=…)``: fn()(인자 없음)을 작업 스레드에서 실행하고, 호출한(메인) 스레드는 끝날 때까지
``ex._wait_tick``(lease 갱신 heartbeat_interval_s · 취소 확인 cancel_check_interval_s) 루프로 기다린다.

- DB 연결은 메인 스레드에서만(fn 은 파일만 다룬다 — DB·ex._tx 금지).
- fn 의 예외는 메인 스레드로 그대로 다시 던진다(CoreError·_StepFailed 등).
- 취소(_Canceled): ``stop`` 을 세운다(협조적 중단 — ``stop_guard`` 로 감싼 Writer.guard 가 다음 파일 쓰기 전에
  ``Interrupted``). 스레드가 끝날 때까지 lease 는 계속 갱신한 뒤 _Canceled — 작업 폴더에 쓰는 스레드를 남기지 않는다.
- lease 상실·tick 오류(DB 오류 등)·기타: stop 을 세우고 작업 스레드가 끝날 때까지 기다린 뒤 다시 던진다(상태는 쓰지 않음).
  기다리는 동안 lease 갱신은 시도하되 실패해도 대기 유지(같은 Case 새 작업이 이 폴더에 쓰는 스레드와 겹치지 않게).
  무한 대기 방지: ``worker.inproc_join_max_s``(기본 3600 s) 뒤에는 로그를 남기고 진행.
- ``echo`` 가 있으면 시작·끝(경과)과 ``progress_heartbeat_s``(기본 30 s)마다 진행 중 줄(``detail()`` 반환값 덧붙임).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

POLL_S = 0.2
HEARTBEAT_S = 30.0
JOIN_MAX_S = 3600.0

log = logging.getLogger(__name__)


class Interrupted(Exception):
    """작업 스레드 안 협조적 중단(stop 이 섰음) — call() 이 취소·lease 상실로 바꿔 던진다."""


def stop_guard(stop: threading.Event, guard: Callable[[str], str] | None = None,
               count: dict[str, int] | None = None) -> Callable[[str], str]:
    """Writer.guard 감싸기: 쓰기 경로마다 stop 확인(섰으면 Interrupted), count["files"] = 최종 파일 쓰기 수(.tmp 제외)."""
    def g(p: str) -> str:
        if stop.is_set():
            raise Interrupted()
        if count is not None and not str(p).endswith(".tmp"):
            count["files"] = count.get("files", 0) + 1
        return guard(p) if guard is not None else p
    return g


def renew_only(ex) -> Callable[[], None]:
    """취소를 받지 않는 구간(등록 커밋 뒤 등)용 tick — lease 갱신만."""
    st = {"renew": float("-inf")}

    def tick() -> None:
        now = time.monotonic()
        if now - st["renew"] >= ex.settings.worker.heartbeat_interval_s:
            ex._renew()
            st["renew"] = now
    return tick


def call(ex, fn: Callable[[], Any], *, label: str, echo: Callable[[str], None] | None = None,
         stop: threading.Event | None = None, tick: Callable[[], None] | None = None,
         detail: Callable[[], str] | None = None, poll_s: float = POLL_S) -> Any:
    """fn() 을 작업 스레드에서, 이 스레드는 tick(기본 ex._wait_tick) 루프. fn 의 반환값."""
    from esl_platform.core.errors import LeaseLost

    from .executor import _Canceled

    stop = stop or threading.Event()
    if tick is None:
        st = {"renew": float("-inf"), "cancel": time.monotonic()}     # 첫 tick 에 바로 갱신(직전 갱신 시각 모름)
        tick = lambda: ex._wait_tick(st)  # noqa: E731
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["res"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 메인 스레드로 넘김
            box["err"] = exc

    w = ex.settings.worker
    hb = float(getattr(w, "progress_heartbeat_s", HEARTBEAT_S) or HEARTBEAT_S)
    t = threading.Thread(target=run, name=f"esl-inproc-{str(ex.job['id'])[:8]}", daemon=True)
    t0 = last = time.monotonic()
    if echo:
        echo(f"[esl-worker] {label} 시작")
    t.start()
    try:
        while True:
            t.join(poll_s)
            if not t.is_alive():
                break
            tick()
            now = time.monotonic()
            if echo and now - last >= hb:
                last = now
                more = detail() if detail else ""
                echo(f"[esl-worker] {label} 진행 중… 경과 {now - t0:.0f} s" + (f", {more}" if more else ""))
    except _Canceled:
        stop.set()
        lost = _drain(ex, t, poll_s, label)
        if echo:
            echo(f"[esl-worker] {label} 취소로 중단({time.monotonic() - t0:.1f} s)")
        if lost is not None:
            raise lost from None
        raise
    except BaseException as exc:
        stop.set()
        _drain(ex, t, poll_s, label)
        if echo:
            echo(f"[esl-worker] {label} 중단({type(exc).__name__}, {time.monotonic() - t0:.1f} s)")
        raise
    err = box.get("err")
    if isinstance(err, Interrupted):            # stop 은 위에서만 세운다 — 여기 오면 fn 이 직접 던진 것
        raise LeaseLost(ex.job["id"])
    if err is not None:
        raise err
    if echo:
        echo(f"[esl-worker] {label} 끝({time.monotonic() - t0:.1f} s"
             + (f", {detail()}" if detail else "") + ")")
    return box.get("res")


def _drain(ex, t: threading.Thread, poll_s: float, label: str = "") -> BaseException | None:
    """stop 뒤: 작업 스레드가 끝날 때까지 기다리며 lease 갱신을 시도(heartbeat_interval_s). 갱신 실패(LeaseLost·DB 오류)
    여도 대기는 유지하고, 첫 LeaseLost 를 돌려준다(그 뒤 갱신은 하지 않음 — 다른 오류는 다음 간격에 다시 시도).
    worker.inproc_join_max_s(기본 3600 s)를 넘으면 경고 로그 후 반환(스레드는 daemon 으로 남음)."""
    from esl_platform.core.errors import LeaseLost

    w = ex.settings.worker
    cap = float(getattr(w, "inproc_join_max_s", JOIN_MAX_S) or JOIN_MAX_S)
    start = last = time.monotonic()
    lost: BaseException | None = None
    while t.is_alive():
        t.join(poll_s)
        now = time.monotonic()
        if not t.is_alive():
            break
        if now - start >= cap:
            log.warning("작업 %s: %s 작업 스레드가 %.0f s 안에 끝나지 않아 기다리지 않고 진행", ex.job["id"], label, cap)
            break
        if lost is None and now - last >= w.heartbeat_interval_s:
            last = now
            try:
                ex._renew()
            except LeaseLost as exc:
                lost = exc
            except Exception:  # noqa: BLE001 - 갱신 실패여도 스레드 종료까지 대기
                log.warning("작업 %s: %s 대기 중 lease 갱신 실패", ex.job["id"], label, exc_info=True)
    return lost
