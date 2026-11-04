"""v0.14.0 ④ 형상 직접 비교 BD_DESIGNS 작업 단위 시험(계약 esl_step_compare.md V-SC-7): 병렬 상한·메모리 자동 축소
(가장 큰 형상 기준), 취소(진행 중·대기 형상 중단, 끝난 형상 유지), 이어하기(done.json 같은 input_sha256 → 재사용).

코어 자식(bd_eval)·DB 는 가짜로 바꾼다 — 실제 PG·gmsh·코어 경로는 test_doe_compare_e2e.py."""

from __future__ import annotations

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

GB = 1024 ** 3


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _log(out: str) -> str:
    with open(os.path.join(out, "designs.log"), encoding="utf-8") as fh:
        return fh.read()


def _case(tmp_path, n_nodes: dict[str, int], parallel: int = 3):
    """④ 작업 폴더: prep/base.json·prep/compare.json(d000 기준 + 형상들, 하나는 FAILED_SIZE = 실행 제외)."""
    out = str(tmp_path / "doe")
    _write(os.path.join(out, "prep", "base.json"), {"n_nodes": 100})
    rows = [{"id": "d000", "name": "기준", "status": "READY", "n_nodes": 100}]
    rows += [{"id": k, "name": f"형상 {k}", "status": "READY", "n_nodes": v} for k, v in n_nodes.items()]
    rows.append({"id": "d099", "name": "크기 불일치", "status": "FAILED_SIZE", "n_nodes": 10})
    _write(os.path.join(out, "prep", "compare.json"), {"shapes": rows})
    cfg = {"bead_doe": {"run": {"parallel": parallel, "memory_margin": 0.7}}, "opt_run": {"solver": {"backend": "superlu"}}}
    ex = SimpleNamespace(lib={"doe": {"scenario": "compare", "cfg": cfg}}, cdir=out, lim=None,
                         settings=SimpleNamespace(worker=SimpleNamespace(terminate_grace_s=0.1)),
                         _wait_tick=lambda state: None)
    return ex, out


class FakeEval:
    """가짜 코어 자식 bd_eval: 동시 실행 수 기록, result.json·done.json 기록. ``block`` 형상은 취소(procs.stop)까지 대기."""

    def __init__(self, hold: float = 0.15, block=()):
        self.lock = threading.Lock()
        self.running = 0
        self.max_running = 0
        self.calls: list[str] = []
        self.hold = hold
        self.block = set(block)
        self.finished: list[str] = []

    def __call__(self, ex, did, pa, procs):
        from esl_worker import paicad_proc

        assert pa is None                                     # ④ paicad 없음
        with self.lock:
            self.calls.append(did)
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            t_end = time.monotonic() + self.hold
            while time.monotonic() < t_end or did in self.block:
                if procs.stop.is_set():
                    raise paicad_proc.PaicadCanceled()
                time.sleep(0.01)
            dd = os.path.join(ex.cdir, "run", "designs", did)
            _write(os.path.join(dd, "result.json"), {"status": "OK", "C_max": 1.0, "per_esl": [{}],
                                                      "solve": {"seconds": 0.1}, "mesh": {"n_elems": 10}})
            _write(os.path.join(dd, "done.json"), {"input_sha256": f"sha-{did}", "status": "OK", "at": "t"})
            with self.lock:
                self.finished.append(did)
            return "OK", None
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture()
def patched(monkeypatch):
    from esl_worker import core_adapter, doe_jobs

    from esl.mech import shell

    prog: list[float] = []
    monkeypatch.setattr(doe_jobs, "set_progress", lambda ex, st, pct, **kw: prog.append((pct, kw)))
    monkeypatch.setattr(core_adapter, "doe_design_sha", lambda doe, out, did: f"sha-{did}")
    monkeypatch.setattr(shell, "available_memory_bytes", lambda: 512 * GB)
    return SimpleNamespace(doe_jobs=doe_jobs, shell=shell, prog=prog, mp=monkeypatch)


def _run(p, ex, out, fake):
    p.mp.setattr(p.doe_jobs, "_eval_child", fake)
    st = {"step_no": 1, "step_key": "BD_DESIGNS"}
    return p.doe_jobs._designs(ex, st, os.path.join(out, "designs.log"))


def test_compare_parallel_cap(tmp_path, patched):
    """요청 run.parallel = 3 → 동시 실행 ≤ 3(형상 6개), FAILED_SIZE·d000 은 실행 안 함."""
    ids = {f"d00{k}": 1000 for k in range(1, 7)}
    ex, out = _case(tmp_path, ids, parallel=3)
    fake = FakeEval(hold=0.2)
    r = _run(patched, ex, out, fake)
    assert r["n_designs"] == 6 and r["ok"] == 6 and r["failed"] == 0 and r["parallel"]["parallel"] == 3
    assert sorted(fake.calls) == sorted(ids) and "d099" not in fake.calls and "d000" not in fake.calls
    assert 2 <= fake.max_running <= 3
    outputs = [kw["outputs"] for _, kw in patched.prog if kw.get("outputs")]
    assert outputs and outputs[0]["n_designs"] == 6


def test_compare_parallel_memory_reduction_uses_largest_shape(tmp_path, patched):
    """메모리 자동 축소 = 가장 큰 형상 n_nodes 기준(BD-D-15): 큰 형상 1개가 있으면 동시 1."""
    from esl_worker import doe_jobs

    big = 220_000
    est = doe_jobs.parallel(_case(tmp_path / "probe", {"d001": 1})[0], big)["estimate_bytes"]
    patched.mp.setattr(patched.shell, "available_memory_bytes", lambda: int(est * 1.5 / 0.7))   # 큰 형상 1.5개 분량
    ex, out = _case(tmp_path, {"d001": 1000, "d002": big, "d003": 1000}, parallel=4)
    fake = FakeEval(hold=0.1)
    r = _run(patched, ex, out, fake)
    lim = r["parallel"]
    assert lim["requested"] == 4 and lim["parallel"] == 1 and lim["reduced"]
    assert fake.max_running == 1 and r["ok"] == 3
    assert "메모리 자동 축소" in _log(out)


def test_compare_cancel_then_resume(tmp_path, patched):
    """취소: 끝난 형상(done.json) 유지·진행 중 형상 중단(결과 없음) → 이어하기: 끝난 형상 재사용(코어 자식 생략), 나머지만 실행."""
    from esl_worker.executor import _Canceled

    ids = {f"d00{k}": 1000 for k in range(1, 6)}
    ex, out = _case(tmp_path, ids, parallel=2)
    fake = FakeEval(hold=0.05, block={"d003", "d004", "d005"})

    def tick(state):
        if len(fake.finished) >= 2 and fake.running > 0:
            raise _Canceled()
    ex._wait_tick = tick
    with pytest.raises(_Canceled):
        _run(patched, ex, out, fake)
    done = sorted(d for d in ids if os.path.isfile(os.path.join(out, "run", "designs", d, "done.json")))
    assert done == ["d001", "d002"] == sorted(fake.finished)
    assert fake.running == 0                                  # 진행 중 형상 모두 중단됨
    assert "BD_DESIGNS 중단" in _log(out)

    ex._wait_tick = lambda state: None
    fake2 = FakeEval(hold=0.02)
    r = _run(patched, ex, out, fake2)
    assert r["reused"] == 2 and r["ok"] == 3 and r["failed"] == 0 and r["n_designs"] == 5
    assert sorted(fake2.calls) == ["d003", "d004", "d005"]     # 재사용 형상은 코어 자식 호출 없음
    log = _log(out)
    assert "[d001] 이전 결과 재사용(OK)" in log and "[d002] 이전 결과 재사용(OK)" in log


def test_compare_resume_ignores_stale_or_failed_done(tmp_path, patched):
    """done.json 의 input_sha256 이 다르거나(형상·설정 변경) 상태가 재시도 대상(FAILED_*)이면 다시 실행."""
    ids = {"d001": 1000, "d002": 1000, "d003": 1000}
    ex, out = _case(tmp_path, ids, parallel=2)
    _write(os.path.join(out, "run", "designs", "d001", "done.json"), {"input_sha256": "sha-old", "status": "OK"})
    _write(os.path.join(out, "run", "designs", "d001", "result.json"), {"status": "OK"})
    _write(os.path.join(out, "run", "designs", "d002", "done.json"), {"input_sha256": "sha-d002", "status": "FAILED_SOLVE"})
    _write(os.path.join(out, "run", "designs", "d003", "done.json"), {"input_sha256": "sha-d003", "status": "OK"})
    _write(os.path.join(out, "run", "designs", "d003", "result.json"), {"status": "OK"})
    fake = FakeEval(hold=0.01)
    r = _run(patched, ex, out, fake)
    assert sorted(fake.calls) == ["d001", "d002"] and r["reused"] == 1 and r["ok"] == 2
