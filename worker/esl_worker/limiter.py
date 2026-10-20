"""워커 자원 제한기: 설정 `worker.limiter`(auto | windows_job | posix | none(=null)) · `max_memory_gb` ·
`max_logical_cores` · `priority`를 코어 자식 프로세스에 적용한다(같은 서버의 대시보드·physicsai 와 자원 경합 완화).

- auto → Windows 는 windows_job, 그 밖은 posix. 맞지 않는 OS 의 제한기·Job 생성 실패는 "사용 불가" 제한기가 되어
  코어 step 을 FAILED `LIMITER_FAILED`로 끝낸다(제한 없이 실행하는 경로 없음). none/null = 제한 없음.
- windows_job(esl_worker.limiter_windows): 워커 1개당 Job Object 1개 — 우선순위 클래스·Job 메모리·CPU 상한(CpuRate),
  KILL_ON_JOB_CLOSE(워커가 죽으면 OS 가 자식을 종료 — 자식의 부모 감시와 이중 보호). 부모가 자식 시작 직후 할당.
- posix: 자식 안에서 nice(below_normal +5, idle +15) · RLIMIT_AS(max_memory_gb × vm_headroom) · sched_setaffinity(현재
  허용 CPU 중 앞쪽 max_logical_cores 개)를 적용(자식마다 따로 — 메모리 한도는 프로세스 1개 기준).
  RLIMIT_AS 는 가상 주소 공간(VmPeak) 한도라 실제 사용(RSS) 보다 크게 잡힌다 — BLAS/OpenMP 스레드 스택·메모리 맵·
  할당자 예약 때문에 VmPeak 가 RSS 보다 크다(Verifier v6, 9만 요소·1 스레드: pardiso VmPeak 4.4 / VmHWM 3.8 GB,
  cholmod 4.0 / 3.7 GB — 스레드마다 glibc arena(최대 64 MB)·스택 예약이 더해져 다중 스레드에서 더 벌어짐)라
  `worker.vm_headroom`(기본 1.5) 을 곱해 max_memory_gb 가 "실사용 메모리" 의미가 되게 한다.
  Windows Job 메모리(JobMemoryLimit)는 커밋 기준(실제 확보한 메모리)이라 계수를 곱하지 않는다(1.0).
- 공통(null 제외): 자식에 OMP/MKL/OPENBLAS_NUM_THREADS 가 없으면 min(max_logical_cores, 논리 코어 수)로 정한다.
- 시작 신호(gate): 부모는 자식 spawn 직후 제한을 건 다음 Pipe 로 시작 신호(+적용 결과)를 보낸다. 자식은 신호를 받기 전에는
  코어를 import·실행하지 않는다(Windows 에서 Job 할당 전 계산 구간이 없도록 — CREATE_SUSPENDED → resume 대신).
- 적용 결과: step 로그 `[esl-worker] 자원 제한 …` 줄, 코어 step outputs.limiter(실행 중), 워커 heartbeat limiter(/status).
"""

from __future__ import annotations

import multiprocessing
import os
from dataclasses import asdict, dataclass
from typing import Any

FAILURE_CODE = "LIMITER_FAILED"
NICE_INC = {"normal": 0, "below_normal": 5, "idle": 15}
GATE_TIMEOUT_S = 120.0
THREAD_ENV = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
DEFAULT_VM_HEADROOM = 1.5


class LimiterError(Exception):
    code = FAILURE_CODE


@dataclass(frozen=True)
class Limits:
    priority: str = "normal"
    max_memory_gb: float | None = None
    max_logical_cores: int | None = None
    vm_headroom: float = DEFAULT_VM_HEADROOM     # POSIX RLIMIT_AS 에만 곱함(Windows Job 은 커밋 기준 → 1.0)

    @classmethod
    def from_cfg(cls, worker_cfg: Any) -> Limits:
        return cls(priority=worker_cfg.priority, max_memory_gb=float(worker_cfg.max_memory_gb),
                   max_logical_cores=int(worker_cfg.max_logical_cores),
                   vm_headroom=float(getattr(worker_cfg, "vm_headroom", None) or DEFAULT_VM_HEADROOM))

    def rlimit_as_gb(self) -> float | None:
        return None if not self.max_memory_gb else float(self.max_memory_gb) * float(self.vm_headroom or 1.0)


def resolve_mode(name: str | None, os_name: str | None = None) -> str:
    """설정값 → windows_job | posix | null. OS 와 맞지 않으면 LimiterError."""
    os_name = os_name or os.name
    n = (name or "auto").lower()
    if n in ("none", "null"):
        return "null"
    if n == "auto":
        return "windows_job" if os_name == "nt" else "posix"
    if n == "windows_job" and os_name != "nt":
        raise LimiterError("worker.limiter=windows_job 은 Windows 에서만 쓸 수 있습니다")
    if n == "posix" and os_name == "nt":
        raise LimiterError("worker.limiter=posix 는 Windows 에서 쓸 수 없습니다(windows_job 또는 auto)")
    if n not in ("windows_job", "posix"):
        raise LimiterError(f"알 수 없는 worker.limiter: {name}")
    return n


# ---------------------------------------------------------------- 제한기(부모 쪽)
class NullLimiter:
    mode = "null"

    def __init__(self, limits: Limits) -> None:
        self.limits = limits

    def summary(self) -> dict[str, Any]:
        return {"mode": self.mode, "text": "제한 없음(worker.limiter=none)"}

    def attach(self, proc: Any) -> dict[str, Any]:
        return self.summary()

    def close(self) -> None:
        pass


class PosixLimiter(NullLimiter):
    """부모 쪽에서는 할 일이 없다 — 자식이 시작 신호를 받은 뒤 스스로 apply_posix 를 적용한다."""

    mode = "posix"

    def summary(self) -> dict[str, Any]:
        lim = self.limits
        return {"mode": self.mode, **asdict(lim),
                "text": f"nice +{NICE_INC.get(lim.priority, 0)}({lim.priority}), 메모리 {lim.max_memory_gb:g} GB × "
                        f"{lim.vm_headroom:g} = {lim.rlimit_as_gb():g} GB(RLIMIT_AS, 가상), "
                        f"CPU 선호도 최대 {lim.max_logical_cores} 코어"}


class UnavailableLimiter(NullLimiter):
    """설정한 제한을 걸 수 없음 — 코어 step 을 실행하지 않는다."""

    def __init__(self, mode: str, limits: Limits, error: str) -> None:
        super().__init__(limits)
        self.mode = mode
        self.error = error

    def summary(self) -> dict[str, Any]:
        return {"mode": self.mode, "error": self.error, "text": f"사용 불가 — {self.error}"}

    def attach(self, proc: Any) -> dict[str, Any]:
        raise LimiterError(f"자원 제한({self.mode})을 적용할 수 없어 코어를 실행하지 않습니다: {self.error}")


def create(worker_cfg: Any, *, os_name: str | None = None, kernel32: Any = None, cpu_count: int | None = None):
    """설정 → 제한기. 예외를 내지 않는다(실패는 UnavailableLimiter)."""
    limits = Limits.from_cfg(worker_cfg)
    try:
        mode = resolve_mode(worker_cfg.limiter, os_name)
    except LimiterError as exc:
        return UnavailableLimiter(str(worker_cfg.limiter), limits, str(exc))
    if mode == "null":
        return NullLimiter(limits)
    if mode == "posix":
        return PosixLimiter(limits)
    try:
        from .limiter_windows import WindowsJobLimiter

        return WindowsJobLimiter(limits, kernel32=kernel32, cpu_count=cpu_count)
    except LimiterError as exc:
        return UnavailableLimiter(mode, limits, str(exc))
    except Exception as exc:  # noqa: BLE001 - ctypes 로드 실패 등
        return UnavailableLimiter(mode, limits, f"{type(exc).__name__}: {exc}")


def of(worker: Any):
    """워커의 제한기(없으면 설정으로 만들어 붙인다)."""
    lim = getattr(worker, "proc_limiter", None)
    if lim is None:
        lim = create(worker.settings.worker)
        worker.proc_limiter = lim
    return lim


def describe(lim: Any) -> str:
    """heartbeat·/status 용 한 줄."""
    s = lim.summary()
    return f"{s['mode']}: {s['text']}"


def plan(lim: Any) -> dict[str, Any]:
    """자식에 넘길 적용 계획(spec['limits'])."""
    return {"mode": lim.mode, **asdict(lim.limits)}


# ---------------------------------------------------------------- 부모: 자식 시작 전후 hook
def prepare(worker: Any, spec: dict[str, Any]):
    """spawn 전: spec 에 적용 계획과 시작 신호 Pipe(읽기 끝)를 넣는다. 반환값은 after_start 에 그대로 넘긴다."""
    r, w = multiprocessing.Pipe(duplex=False)
    spec["limits"] = plan(of(worker))
    spec["limit_gate"] = r
    return r, w


def after_start(worker: Any, proc: Any, gate) -> str:
    """spawn 직후: 제한(Windows Job 할당)을 걸고 자식에 시작 신호를 보낸다. 예외를 내지 않는다 — 실패는 자식에 알려
    자식이 결과 {ok: false, code: LIMITER_FAILED}를 남기고 코어 없이 끝난다. 반환 = step outputs.limiter 한 줄."""
    r, w = gate
    r.close()
    lim = of(worker)
    try:
        try:
            applied = lim.attach(proc)
            msg: dict[str, Any] = {"ok": True, "applied": applied}
            line = f"{applied['mode']}: {applied['text']}"
        except Exception as exc:  # noqa: BLE001 - 무엇이든 자식에 실패로 알린다
            msg = {"ok": False, "message": str(exc) if isinstance(exc, LimiterError) else f"{type(exc).__name__}: {exc}"}
            line = f"{lim.mode}: 실패 — {msg['message']}"
        w.send(msg)
    except OSError:
        pass  # 자식이 이미 끝남(부모는 종료 코드로 판정)
    finally:
        w.close()
    return line


# ---------------------------------------------------------------- 자식
def child_setup(spec: dict[str, Any], echo) -> dict[str, Any]:
    """자식 시작 직후(코어 import 전): 시작 신호를 기다리고 자식 쪽 제한을 건 뒤 step 로그에 한 줄 남긴다.
    실패 → LimiterError(child_entry 가 LIMITER_FAILED 결과로 끝낸다)."""
    p = spec.get("limits")
    if p is None:  # 이전 형식 spec(시험 등): priority 만 → nice
        p = {"mode": "posix" if hasattr(os, "nice") else "null", "priority": spec.get("priority", "normal")}
    gate = spec.get("limit_gate")
    parent: dict[str, Any] = {}
    if gate is not None:
        try:
            if not gate.poll(GATE_TIMEOUT_S):
                raise LimiterError(f"부모 워커의 시작 신호가 {GATE_TIMEOUT_S:g}초 안에 오지 않았습니다")
            msg = gate.recv()
        except (EOFError, OSError):
            raise LimiterError("부모 워커가 시작 신호 전에 연결을 닫았습니다") from None
        finally:
            gate.close()
        if not msg.get("ok"):
            raise LimiterError(msg.get("message") or "자원 제한 실패")
        parent = msg.get("applied") or {}
    got = apply_in_child(p)
    text = got.get("text") or parent.get("text") or ""
    if got.get("threads"):
        text += f", 스레드 {got['threads']}"
    echo(f"[esl-worker] 자원 제한 {p['mode']}: {text}")
    return {**parent, **got}


def apply_in_child(p: dict[str, Any]) -> dict[str, Any]:
    mode = p.get("mode")
    if mode == "null":
        return {"mode": "null", "text": "제한 없음(worker.limiter=none)"}
    out: dict[str, Any] = {"mode": mode}
    if mode == "posix":
        out.update(apply_posix(p))
    cores = p.get("max_logical_cores")
    if cores:
        n = str(max(1, min(int(cores), os.cpu_count() or int(cores))))
        set_ = [k for k in THREAD_ENV if not os.environ.get(k)]
        for k in set_:
            os.environ[k] = n
        if set_:
            out["threads"] = f"{'/'.join(s.split('_')[0] for s in set_)}={n}"
    return out


def apply_posix(p: dict[str, Any]) -> dict[str, Any]:
    """현재 프로세스에 nice · RLIMIT_AS · CPU 선호도. 지원하지 않는 OS 기능은 건너뛰고 text 에 적는다."""
    out: dict[str, Any] = {}
    parts: list[str] = []
    pr = p.get("priority") or "normal"
    inc = NICE_INC.get(pr, 0)
    if hasattr(os, "nice"):
        try:
            out["nice"] = os.nice(inc)
        except OSError as exc:
            raise LimiterError(f"nice 적용 실패: {exc}") from None
        parts.append(f"nice {out['nice']}({pr})")
    gb = p.get("max_memory_gb")
    if gb:
        try:
            import resource
        except ImportError:
            parts.append("메모리 한도 미지원(resource 없음)")
        else:
            hr = float(p.get("vm_headroom") or 1.0)     # 이전 형식 계획(계수 없음) = 1.0
            want = int(float(gb) * hr * 2**30)
            _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            if hard != resource.RLIM_INFINITY and hard < want:
                want = hard
            try:
                resource.setrlimit(resource.RLIMIT_AS, (want, want))
            except (ValueError, OSError) as exc:
                raise LimiterError(f"RLIMIT_AS 적용 실패: {exc}") from None
            out["rlimit_as"] = want
            parts.append(f"메모리 {float(gb):g} GB × {hr:g} = {want / 2**30:g} GB(RLIMIT_AS, 가상)")
    cores = p.get("max_logical_cores")
    if cores:
        if hasattr(os, "sched_setaffinity"):
            cur = sorted(os.sched_getaffinity(0))
            keep = cur[: int(cores)]
            if len(keep) < len(cur):
                try:
                    os.sched_setaffinity(0, keep)
                except OSError as exc:
                    raise LimiterError(f"CPU 선호도 적용 실패: {exc}") from None
            out["cpus"] = keep
            parts.append(f"CPU 선호도 {len(keep)}/{len(cur)} 코어")
        else:
            parts.append("CPU 선호도 미지원(이 OS)")
    out["text"] = ", ".join(parts) or "적용할 제한 없음"
    return out
