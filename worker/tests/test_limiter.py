"""워커 자원 제한기(esl_worker.limiter): POSIX 실제 적용(자식에서 확인), Windows Job Object(가짜 kernel32 로 인자 검증),
null 모드, 시작 신호(gate) 실패 처리, 환경 점검 행."""

from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import sys
from types import SimpleNamespace

import pytest
from esl_worker import limiter
from esl_worker import limiter_windows as lw
from esl_worker.child import child_entry

_SPAWN = multiprocessing.get_context("spawn")
GB = 2**30


def _cfg(**kw):
    d = {"limiter": "auto", "max_logical_cores": 16, "max_memory_gb": 32.0, "priority": "below_normal"}
    d.update(kw)
    return SimpleNamespace(**d)


def _worker(lim):
    return SimpleNamespace(proc_limiter=lim, settings=SimpleNamespace(worker=None))


def probe(spec, echo):
    """자식 안에서 실제 적용 상태를 기록(spec['out'] 파일)."""
    import resource

    d = {"nice": os.nice(0), "rlimit_as": list(resource.getrlimit(resource.RLIMIT_AS)),
         "cpus": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
         "omp": os.environ.get("OMP_NUM_THREADS")}
    with open(spec["out"], "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    echo("probe 완료")


def _run_child(tmp_path, lim, name="step_01_X"):
    log = tmp_path / f"{name}.log"
    spec = {"log_path": str(log), "result_path": str(log) + ".result.json", "target": "test_limiter:probe",
            "stage": "extract", "parent_pid": os.getpid(), "out": str(tmp_path / f"{name}.probe.json")}
    w = _worker(lim)
    gate = limiter.prepare(w, spec)
    p = _SPAWN.Process(target=child_entry, args=(spec,))
    p.start()
    applied = limiter.after_start(w, p, gate)
    p.join(60)
    assert not p.is_alive()
    res = json.loads((tmp_path / f"{name}.log.result.json").read_text(encoding="utf-8"))
    probe_p = tmp_path / f"{name}.probe.json"
    got = json.loads(probe_p.read_text(encoding="utf-8")) if probe_p.is_file() else None
    return p.exitcode, res, got, log.read_text(encoding="utf-8"), applied


# ---------------------------------------------------------------- 모드 해석
def test_resolve_mode():
    assert limiter.resolve_mode("auto", "nt") == "windows_job"
    assert limiter.resolve_mode("auto", "posix") == "posix"
    assert limiter.resolve_mode("none", "posix") == limiter.resolve_mode("null", "nt") == "null"
    with pytest.raises(limiter.LimiterError):
        limiter.resolve_mode("windows_job", "posix")
    with pytest.raises(limiter.LimiterError):
        limiter.resolve_mode("posix", "nt")
    bad = limiter.create(_cfg(limiter="windows_job"), os_name="posix")
    assert isinstance(bad, limiter.UnavailableLimiter) and "사용 불가" in limiter.describe(bad)
    with pytest.raises(limiter.LimiterError):
        bad.attach(SimpleNamespace(sentinel=1))


# ---------------------------------------------------------------- POSIX 실제 적용
@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "sched_setaffinity"), reason="Linux 전용")
def test_posix_applied_in_child(tmp_path, monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    base_nice = os.nice(0)
    cpus = sorted(os.sched_getaffinity(0))
    cores = max(1, len(cpus) - 1)
    lim = limiter.create(_cfg(max_logical_cores=cores, max_memory_gb=3), os_name="posix")
    assert isinstance(lim, limiter.PosixLimiter)
    code, res, got, log, applied = _run_child(tmp_path, lim)
    assert code == 0 and res == {"ok": True}, log
    assert got["nice"] == min(19, base_nice + 5)
    assert got["rlimit_as"] == [3 * GB, 3 * GB]
    assert got["cpus"] == cpus[:cores]
    assert got["omp"] == str(cores)
    assert applied.startswith("posix: nice +5(below_normal)")
    line = next(ln for ln in log.splitlines() if "자원 제한" in ln)
    assert line.startswith("[esl-worker] 자원 제한 posix: nice") and "메모리 3 GB(RLIMIT_AS)" in line
    assert f"CPU 선호도 {cores}/{len(cpus)} 코어" in line
    # 부모(워커)에는 영향 없음
    assert os.nice(0) == base_nice and sorted(os.sched_getaffinity(0)) == cpus


@pytest.mark.skipif(os.name == "nt", reason="POSIX 전용")
def test_null_mode_applies_nothing(tmp_path, monkeypatch):
    import resource

    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    lim = limiter.create(_cfg(limiter="none"))
    assert isinstance(lim, limiter.NullLimiter) and lim.mode == "null"
    code, res, got, log, applied = _run_child(tmp_path, lim)
    assert code == 0 and res == {"ok": True}
    assert got["nice"] == os.nice(0)
    assert got["rlimit_as"] == list(resource.getrlimit(resource.RLIMIT_AS))
    assert got["cpus"] == (sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None)
    assert got["omp"] is None
    assert "[esl-worker] 자원 제한 null: 제한 없음" in log and applied.startswith("null:")


def test_attach_failure_stops_child_before_core(tmp_path):
    """제한을 걸 수 없으면 자식은 코어(probe)를 실행하지 않고 LIMITER_FAILED 로 끝난다."""
    lim = limiter.UnavailableLimiter("windows_job", limiter.Limits("below_normal", 32, 16), "Job 생성 실패(시험)")
    code, res, got, log, applied = _run_child(tmp_path, lim)
    assert code == 1 and got is None
    assert res["ok"] is False and res["code"] == "LIMITER_FAILED" and "Job 생성 실패(시험)" in res["message"]
    assert "실패 LIMITER_FAILED" in log and "실패" in applied


# ---------------------------------------------------------------- Windows Job Object(가짜 kernel32)
class FakeKernel32:
    JOB = 0x1234

    def __init__(self, *, create_ok=True, set_ok=(True, True), assign_ok=True):
        self.calls: list[tuple] = []
        self.create_ok = create_ok
        self.set_ok = list(set_ok)
        self.assign_ok = assign_ok

    def CreateJobObjectW(self, attrs, name):
        self.calls.append(("CreateJobObjectW", attrs, name))
        return self.JOB if self.create_ok else None

    def SetInformationJobObject(self, job, cls, ref, size):
        obj = ref._obj
        copy = type(obj).from_buffer_copy(obj)
        self.calls.append(("SetInformationJobObject", job, cls, copy, size))
        return self.set_ok.pop(0)

    def AssignProcessToJobObject(self, job, handle):
        self.calls.append(("AssignProcessToJobObject", job, handle))
        return self.assign_ok

    def CloseHandle(self, h):
        self.calls.append(("CloseHandle", h))
        return True

    def names(self):
        return [c[0] for c in self.calls]


def test_windows_job_arguments():
    k = FakeKernel32()
    lim = limiter.create(_cfg(limiter="windows_job"), os_name="nt", kernel32=k, cpu_count=64)
    assert isinstance(lim, lw.WindowsJobLimiter)
    assert k.calls[0] == ("CreateJobObjectW", None, None)
    _, job, cls, ext, size = k.calls[1]
    assert (job, cls, size) == (k.JOB, 9, ctypes.sizeof(lw.JOBOBJECT_EXTENDED_LIMIT_INFORMATION))
    flags = ext.BasicLimitInformation.LimitFlags
    for f in (lw.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, lw.JOB_OBJECT_LIMIT_JOB_MEMORY, lw.JOB_OBJECT_LIMIT_PRIORITY_CLASS,
              lw.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION):
        assert flags & f
    assert not flags & 0x00000800  # BREAKAWAY_OK 없음(손자도 Job 안)
    assert ext.BasicLimitInformation.PriorityClass == lw.BELOW_NORMAL_PRIORITY_CLASS == 0x4000
    assert ext.JobMemoryLimit == 32 * GB
    _, job, cls, cpu, size = k.calls[2]
    assert (job, cls, size) == (k.JOB, 15, ctypes.sizeof(lw.JOBOBJECT_CPU_RATE_CONTROL_INFORMATION))
    assert cpu.ControlFlags == lw.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | lw.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP == 0x5
    assert cpu.CpuRate == 2500  # 16/64 코어 = 25.00 %
    s = lim.attach(SimpleNamespace(sentinel=777))
    assert k.calls[3] == ("AssignProcessToJobObject", k.JOB, 777)
    assert s["mode"] == "windows_job" and s["kill_on_close"] and "CPU 상한 16/64 코어(25.00%)" in s["text"]
    assert limiter.describe(lim).startswith("windows_job: Job Object: 우선순위 below_normal, 메모리 32 GB")
    lim.close()
    lim.close()
    assert k.calls[-1] == ("CloseHandle", k.JOB) and k.names().count("CloseHandle") == 1
    with pytest.raises(limiter.LimiterError):
        lim.attach(SimpleNamespace(sentinel=777))


def test_windows_job_idle_no_cpu_cap_when_cores_enough():
    k = FakeKernel32()
    lim = limiter.create(_cfg(limiter="auto", priority="idle", max_logical_cores=16, max_memory_gb=8), os_name="nt",
                         kernel32=k, cpu_count=8)
    assert k.names() == ["CreateJobObjectW", "SetInformationJobObject"]  # CpuRate 생략
    assert k.calls[1][3].BasicLimitInformation.PriorityClass == lw.IDLE_PRIORITY_CLASS
    assert k.calls[1][3].JobMemoryLimit == 8 * GB
    assert "CPU 상한 없음" in lim.summary()["text"]


@pytest.mark.parametrize("kw, closed", [({"create_ok": False}, False), ({"set_ok": (False,)}, True),
                                        ({"set_ok": (True, False)}, True)])
def test_windows_job_setup_failures(kw, closed):
    k = FakeKernel32(**kw)
    lim = limiter.create(_cfg(limiter="windows_job"), os_name="nt", kernel32=k, cpu_count=64)
    assert isinstance(lim, limiter.UnavailableLimiter) and lim.mode == "windows_job"
    assert ("CloseHandle", k.JOB) in k.calls if closed else "CloseHandle" not in k.names()
    with pytest.raises(limiter.LimiterError, match="적용할 수 없어"):
        lim.attach(SimpleNamespace(sentinel=1))


def test_windows_assign_failure_raises():
    k = FakeKernel32(assign_ok=False)
    lim = limiter.create(_cfg(limiter="windows_job"), os_name="nt", kernel32=k, cpu_count=64)
    with pytest.raises(limiter.LimiterError, match="AssignProcessToJobObject"):
        lim.attach(SimpleNamespace(sentinel=5))


def test_windows_gate_with_real_child(tmp_path, monkeypatch):
    """Windows 경로의 시작 신호: 부모가 Job 할당(가짜) 뒤 신호 → 자식은 Job 적용 결과를 로그에 남기고 코어 실행."""
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    k = FakeKernel32()
    lim = limiter.create(_cfg(limiter="windows_job", max_logical_cores=2), os_name="nt", kernel32=k, cpu_count=8)
    code, res, got, log, applied = _run_child(tmp_path, lim)
    assert code == 0 and res == {"ok": True}
    pid_handles = [c for c in k.calls if c[0] == "AssignProcessToJobObject"]
    assert len(pid_handles) == 1 and pid_handles[0][2] is not None
    assert "[esl-worker] 자원 제한 windows_job: Job Object: 우선순위 below_normal, 메모리 32 GB, CPU 상한 2/8 코어" in log
    assert got["omp"] == str(min(2, os.cpu_count() or 2))
    assert applied.startswith("windows_job: Job Object")


def test_import_safe_without_windll():
    assert not hasattr(ctypes, "WinDLL") or sys.platform == "win32"
    if sys.platform != "win32":
        lim = limiter.create(_cfg(limiter="windows_job"), os_name="nt")  # 실제 kernel32 없음 → 사용 불가
        assert isinstance(lim, limiter.UnavailableLimiter)


# ---------------------------------------------------------------- 환경 점검 행·워커 상태
def test_check_limiter_rows():
    from esl_platform import check

    it = check.check_limiter(_cfg(), "linux")
    assert it.key == "worker.limiter" and it.status == "OK" and "auto → posix" in it.detail
    assert check.check_limiter(_cfg(limiter="none"), "linux").status == "WARN"
    assert check.check_limiter(_cfg(limiter="windows_job"), "linux").status == "FAIL"
    k = FakeKernel32()
    ok = check.check_limiter(_cfg(), "win32", kernel32=k, cpu_count=64)
    assert ok.status == "OK" and "auto → windows_job: Job Object" in ok.detail
    assert k.calls[-1] == ("CloseHandle", k.JOB)          # 시험용 Job 은 닫는다
    bad = check.check_limiter(_cfg(), "win32", kernel32=FakeKernel32(create_ok=False), cpu_count=64)
    assert bad.status == "FAIL" and "LIMITER_FAILED" in bad.detail


def test_worker_status_shows_limiter(worker_factory):
    """/status worker.limiter 는 최신 heartbeat 의 limiter 한 줄(workers_repo.latest)."""
    from esl_platform.core.repositories import workers as workers_repo

    w = worker_factory()
    w.heartbeat_once()
    with w.engine.connect() as conn:
        hb = workers_repo.latest(conn)
    assert hb["limiter"] == w.limiter and hb["limiter"].startswith("posix: nice +5(below_normal)")
    assert hb["info"]["limits"]["mode"] == "posix" and hb["info"]["limits"]["max_memory_gb"] == 32
