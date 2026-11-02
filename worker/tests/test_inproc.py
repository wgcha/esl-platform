"""v0.12.2(#44) inproc.call — 워커 프로세스 안 장시간 호출 중 lease 유지·취소·예외 전파(DB 없는 가짜 실행기).

가짜 실행기는 Executor._wait_tick 을 그대로 쓰고 _renew·_cancel_requested 만 바꾼다. 시험용 lease_ttl 0.5 s,
heartbeat 0.05 s — 느린 함수(1.2 s ≫ ttl)가 도는 동안 갱신 간격이 ttl 을 넘지 않는지 확인.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from esl_platform.core.errors import LeaseLost
from esl_worker import inproc
from esl_worker.executor import Executor, _Canceled

TTL = 0.5
HB = 0.05


class FakeEx:
    _wait_tick = Executor._wait_tick

    def __init__(self, *, cancel_after: float | None = None, lose_after: float | None = None) -> None:
        self.settings = SimpleNamespace(worker=SimpleNamespace(
            heartbeat_interval_s=HB, lease_ttl_s=TTL, cancel_check_interval_s=0.05, terminate_grace_s=2.0,
            progress_heartbeat_s=0.3))
        self.job = {"id": "job-inproc-test"}
        self.t0 = time.monotonic()
        self.renews: list[float] = []
        self.threads: set[str] = set()
        self.cancel_after = cancel_after
        self.lose_after = lose_after

    def _renew(self) -> None:
        self.threads.add(threading.current_thread().name)
        now = time.monotonic()
        if self.lose_after is not None and now - self.t0 >= self.lose_after:
            raise LeaseLost(self.job["id"])
        self.renews.append(now)

    def _cancel_requested(self) -> bool:
        self.threads.add(threading.current_thread().name)
        return self.cancel_after is not None and time.monotonic() - self.t0 >= self.cancel_after

    def max_gap(self, end: float) -> float:
        pts = [self.t0] + self.renews + [end]
        return max(b - a for a, b in zip(pts, pts[1:]))


def test_slow_call_keeps_lease_and_returns():
    ex = FakeEx()
    lines: list[str] = []
    seen: dict = {}

    def slow():
        seen["thread"] = threading.current_thread().name
        time.sleep(1.2)                      # > 2 × ttl
        return 42

    assert inproc.call(ex, slow, label="느린 사본", echo=lines.append, detail=lambda: "파일 3개") == 42
    end = time.monotonic()
    assert len(ex.renews) >= 4                         # 0.2 s 폴링마다(≥ heartbeat) 갱신
    assert ex.max_gap(end) < TTL                       # 갱신 간격이 ttl 을 넘지 않음
    assert ex.threads == {threading.current_thread().name}   # DB(갱신·취소 확인)는 호출 스레드에서만
    assert seen["thread"].startswith("esl-inproc-") and seen["thread"] != threading.current_thread().name
    assert lines[0] == "[esl-worker] 느린 사본 시작"
    assert any("진행 중… 경과" in ln and "파일 3개" in ln for ln in lines)
    assert lines[-1].startswith("[esl-worker] 느린 사본 끝(") and "파일 3개" in lines[-1]


def test_exception_propagates():
    ex = FakeEx()

    class Boom(Exception):
        pass

    def bad():
        time.sleep(0.3)
        raise Boom("x")

    with pytest.raises(Boom):
        inproc.call(ex, bad, label="실패")
    assert ex.renews                                    # 실행 중 갱신은 했음


def test_cancel_cooperative_stops_thread_before_raise():
    ex = FakeEx(cancel_after=0.3)
    stop = threading.Event()
    cnt = {"files": 0}
    g = inproc.stop_guard(stop, None, cnt)
    state = {"done": False, "interrupted": False}

    def copy():
        try:
            for i in range(1000):                       # 파일 1000개 × 10 ms — 0.3 s 뒤 취소
                g(f"/x/f{i}.rad")
                time.sleep(0.01)
        except inproc.Interrupted:
            state["interrupted"] = True
            raise
        finally:
            state["done"] = True

    t0 = time.monotonic()
    with pytest.raises(_Canceled):
        inproc.call(ex, copy, label="사본", stop=stop)
    assert time.monotonic() - t0 < 2.0                  # 끝까지(10 s) 기다리지 않음
    assert stop.is_set() and state["interrupted"] and state["done"]    # 스레드가 끝난 뒤에야 _Canceled
    assert 5 <= cnt["files"] < 1000


def test_cancel_non_cooperative_waits_and_keeps_renewing():
    ex = FakeEx(cancel_after=0.2)
    state = {"done": False}

    def hashing():
        time.sleep(1.2)                                 # stop 을 보지 않는 함수(sha256 등)
        state["done"] = True

    t0 = time.monotonic()
    with pytest.raises(_Canceled):
        inproc.call(ex, hashing, label="해시")
    end = time.monotonic()
    assert state["done"] and end - t0 >= 1.2            # 완료 대기 후 _Canceled
    assert ex.max_gap(end) < TTL                        # 취소 후 대기 중에도 lease 갱신(CANCELED 를 쓸 수 있게)
    assert any(r - t0 > 0.6 for r in ex.renews)


def test_lease_lost_propagates_and_sets_stop():
    ex = FakeEx(lose_after=0.3)
    stop = threading.Event()
    g = inproc.stop_guard(stop)

    def copy():
        while True:
            g("/x/a.rad")
            time.sleep(0.01)

    with pytest.raises(LeaseLost):
        inproc.call(ex, copy, label="사본", stop=stop)
    assert stop.is_set()


def test_renew_only_tick_ignores_cancel():
    ex = FakeEx(cancel_after=0.0)
    assert inproc.call(ex, lambda: time.sleep(0.4) or "ok", label="보존", tick=inproc.renew_only(ex)) == "ok"
    assert ex.renews


def test_worker_heartbeat_thread_keeps_running_during_cpu_bound_call():
    """runtime 의 heartbeat 루프(별도 스레드)는 호출 스레드가 inproc.call 로 대기하고 작업 스레드가 순수 파이썬
    CPU 작업(rad 스캔 같은)을 하는 동안에도 heartbeat_interval_s 간격을 지킨다(GIL 전환)."""
    ex = FakeEx()
    beats: list[float] = []
    stop_hb = threading.Event()

    def hb_loop():                                       # WorkerRuntime._loop(heartbeat_once, heartbeat_interval_s)
        while not stop_hb.is_set():
            beats.append(time.monotonic())
            stop_hb.wait(HB)

    def cpu():
        end = time.monotonic() + 1.2
        n = 0
        while time.monotonic() < end:
            n += sum(i * i for i in range(2000))
        return n

    th = threading.Thread(target=hb_loop, daemon=True)
    th.start()
    t0 = time.monotonic()
    try:
        assert inproc.call(ex, cpu, label="rad 스캔") > 0
    finally:
        stop_hb.set()
        th.join(2)
    end = time.monotonic()
    pts = [t0] + [b for b in beats if b >= t0] + [end]
    assert max(b - a for a, b in zip(pts, pts[1:])) < TTL       # 워커 기록 갱신이 멈추지 않음
    assert ex.max_gap(end) < TTL                                 # lease 갱신도
