"""Windows 자원 제한: 워커 1개당 Job Object 1개(ctypes kernel32, pywin32 미사용). Linux 에서도 import 안전.

- 한도: KILL_ON_JOB_CLOSE | JOB_MEMORY | PRIORITY_CLASS | DIE_ON_UNHANDLED_EXCEPTION(BREAKAWAY 불허 → 손자도 Job 안).
  메모리 = `worker.max_memory_gb`(Job 안 모든 코어 자식의 커밋 합계 — SLOT·LIGHT 동시 실행분 포함),
  우선순위 클래스 = `worker.priority`(below_normal → BELOW_NORMAL_PRIORITY_CLASS),
  CPU = CpuRateControl HARD_CAP(`max_logical_cores` / 논리 코어 수 × 10000; 코어 수 이상이면 설정하지 않음).
- 코어 자식(multiprocessing spawn)은 시작 직후 `attach`로 Job 에 넣는다. 자식은 부모의 시작 신호(gate)를 받기 전까지
  코어를 import·실행하지 않으므로(esl_worker.limiter.child_setup) 제한 없이 계산하는 구간이 없다. 할당 실패 → 자식 종료,
  step FAILED `LIMITER_FAILED`(제한 없이 실행하는 경로 없음).
- Job 핸들은 워커가 끝까지 쥔다: 워커 프로세스가 어떻게 끝나든(kill·크래시 포함) OS 가 핸들을 닫고 KILL_ON_JOB_CLOSE 로
  자식이 강제 종료된다(자식의 부모 감시 스레드와 이중 보호).
- kernel32 는 주입 가능(Linux 단위 시험에서 가짜로 인자 검증).
- 메모리 한도에 worker.vm_headroom 을 곱하지 않는다: JobMemoryLimit 은 Job 안 프로세스의 커밋(실제 확보한 사설
  메모리) 합계라 POSIX RLIMIT_AS(가상 주소 공간 — 예약만 한 영역 포함)와 달리 실사용에 가깝다(계수 1.0).
- 구조체는 64비트 Windows 고정 크기로 정의한다(DWORD = uint32, SIZE_T·ULONG_PTR = uint64, LARGE_INTEGER = int64):
  Linux 에서도 같은 배치가 되어 시험이 Windows 배치(basic 64 B, extended 144 B, JobMemoryLimit 오프셋 120,
  CPU rate 8 B)를 단언할 수 있다. 32비트 Python 에서는 Job 을 만들지 않는다(LimiterError).
"""

from __future__ import annotations

import ctypes
import os
from typing import Any

# 64비트 Windows 고정 폭 형식(wintypes 는 Linux 에서 DWORD=c_ulong 64비트라 배치가 달라짐)
DWORD = ctypes.c_uint32
SIZE_T = ctypes.c_uint64
ULONG_PTR = ctypes.c_uint64
ULONGLONG = ctypes.c_uint64
LARGE_INTEGER = ctypes.c_int64

JobObjectExtendedLimitInformation = 9
JobObjectCpuRateControlInformation = 15

JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
PRIORITY_CLASS = {"idle": IDLE_PRIORITY_CLASS, "below_normal": BELOW_NORMAL_PRIORITY_CLASS,
                  "normal": NORMAL_PRIORITY_CLASS}

LIMIT_FLAGS = (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_PRIORITY_CLASS
               | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", LARGE_INTEGER),     # 0
        ("PerJobUserTimeLimit", LARGE_INTEGER),         # 8
        ("LimitFlags", DWORD),                          # 16 (+4 정렬)
        ("MinimumWorkingSetSize", SIZE_T),              # 24
        ("MaximumWorkingSetSize", SIZE_T),              # 32
        ("ActiveProcessLimit", DWORD),                  # 40 (+4 정렬)
        ("Affinity", ULONG_PTR),                        # 48
        ("PriorityClass", DWORD),                       # 56
        ("SchedulingClass", DWORD),                     # 60 → 64 B
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ULONGLONG) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                              "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),   # 0
        ("IoInfo", IO_COUNTERS),                                        # 64 (48 B)
        ("ProcessMemoryLimit", SIZE_T),                                 # 112
        ("JobMemoryLimit", SIZE_T),                                     # 120
        ("PeakProcessMemoryUsed", SIZE_T),                              # 128
        ("PeakJobMemoryUsed", SIZE_T),                                  # 136 → 144 B
    ]


class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    _fields_ = [("ControlFlags", DWORD), ("CpuRate", DWORD)]          # CpuRate 는 union 첫 멤버 → 8 B


def load_kernel32() -> Any:
    from ctypes import wintypes

    from .limiter import LimiterError

    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise LimiterError("Job Object 제한은 64비트 Python 에서만 지원합니다")
    k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _last_error() -> int:
    get = getattr(ctypes, "get_last_error", None)
    try:
        return int(get()) if get else 0
    except Exception:  # noqa: BLE001 - 진단용
        return 0


def cpu_rate(max_cores: int, total: int | None) -> int | None:
    """CpuRate(1/100 %, 1..10000). 한도가 논리 코어 수 이상이면 None(상한 없음)."""
    if not total or max_cores >= total:
        return None
    return max(1, min(10000, round(10000 * max_cores / total)))


class WindowsJobLimiter:
    mode = "windows_job"

    def __init__(self, limits: Any, kernel32: Any = None, cpu_count: int | None = None) -> None:
        from .limiter import LimiterError

        self.limits = limits
        self.k = kernel32 if kernel32 is not None else load_kernel32()
        self.total_cores = cpu_count if cpu_count is not None else (os.cpu_count() or 0)
        self.rate = cpu_rate(limits.max_logical_cores, self.total_cores)
        job = self.k.CreateJobObjectW(None, None)
        if not job:
            raise LimiterError(f"Job Object 를 만들 수 없습니다(CreateJobObjectW, 오류 {_last_error()})")
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        ext.BasicLimitInformation.LimitFlags = LIMIT_FLAGS
        ext.BasicLimitInformation.PriorityClass = PRIORITY_CLASS[limits.priority]
        ext.JobMemoryLimit = int(limits.max_memory_gb * 2**30)
        if not self.k.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(ext),
                                              ctypes.sizeof(ext)):
            err = _last_error()
            self.k.CloseHandle(job)
            raise LimiterError(f"Job 메모리·우선순위 한도 설정 실패(SetInformationJobObject, 오류 {err})")
        if self.rate is not None:
            cpu = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
            cpu.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            cpu.CpuRate = self.rate
            if not self.k.SetInformationJobObject(job, JobObjectCpuRateControlInformation, ctypes.byref(cpu),
                                                  ctypes.sizeof(cpu)):
                err = _last_error()
                self.k.CloseHandle(job)
                raise LimiterError(f"Job CPU 상한 설정 실패(CpuRateControl, 오류 {err})")
        self.job = job

    def summary(self) -> dict[str, Any]:
        lim = self.limits
        cpu = (f"CPU 상한 {lim.max_logical_cores}/{self.total_cores} 코어({self.rate / 100:.2f}%)" if self.rate
               else f"CPU 상한 없음({lim.max_logical_cores} ≥ 논리 코어 {self.total_cores})")
        return {"mode": self.mode, "priority": lim.priority, "max_memory_gb": lim.max_memory_gb,
                "max_logical_cores": lim.max_logical_cores, "logical_cores": self.total_cores,
                "cpu_rate": self.rate, "kill_on_close": True,
                "text": f"Job Object: 우선순위 {lim.priority}, 메모리 {lim.max_memory_gb:g} GB, {cpu}, 워커 종료 시 강제 종료"}

    def attach(self, proc: Any) -> dict[str, Any]:
        """spawn 직후의 자식(multiprocessing.Process)을 Job 에 넣는다. Windows 에서 Process.sentinel = 프로세스 핸들."""
        from .limiter import LimiterError

        if not self.job:
            raise LimiterError("Job Object 가 닫혀 있습니다")
        handle = getattr(proc, "sentinel", None)
        if not self.k.AssignProcessToJobObject(self.job, handle):
            raise LimiterError(f"코어 프로세스를 Job Object 에 넣지 못했습니다(AssignProcessToJobObject, 오류 {_last_error()})")
        return self.summary()

    def close(self) -> None:
        """핸들을 닫는다(KILL_ON_JOB_CLOSE — 남은 코어 자식도 종료)."""
        job, self.job = self.job, None
        if job:
            self.k.CloseHandle(job)
