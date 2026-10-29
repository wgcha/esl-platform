"""비드 DOE 작업 단위 시험(계약 esl_bead_doe.md §9, V-BD-11): 병렬 상한·메모리 자동 축소, 작업 진행률 가중,
미리보기 상태 집계(공칭 셀 제외), 준비 경고 → {code, message}."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _ex(parallel=2, margin=0.7):
    cfg = {"bead_doe": {"run": {"parallel": parallel, "memory_margin": margin}}, "opt_run": {"solver": {"backend": "superlu"}}}
    return SimpleNamespace(lib={"doe": {"cfg": cfg}})


def test_parallel_limit_and_memory_reduction(monkeypatch):
    from esl.mech import shell
    from esl_worker import doe_jobs

    monkeypatch.setattr(shell, "available_memory_bytes", lambda: 512 * 1024 ** 3)
    r = doe_jobs.parallel(_ex(2), 10_000)
    assert r["parallel"] == 2 and not r["reduced"]
    r = doe_jobs.parallel(_ex(1), 10_000)
    assert r["parallel"] == 1
    est = doe_jobs.parallel(_ex(4), 220_000)["estimate_bytes"]
    monkeypatch.setattr(shell, "available_memory_bytes", lambda: int(est * 1.5 / 0.7))   # 1.5 안 분량
    r = doe_jobs.parallel(_ex(4), 220_000)
    assert r["parallel"] == 1 and r["reduced"] and r["requested"] == 4
    monkeypatch.setattr(shell, "available_memory_bytes", lambda: 1)                       # 최소 1
    assert doe_jobs.parallel(_ex(2), 220_000)["parallel"] == 1


def test_job_progress_weights():
    from esl_platform.core.job_types import DOE_STEP_WEIGHTS
    from esl_worker.doe_jobs import job_progress

    assert job_progress("DOE_RUN", "BD_BASELINE", 100) == 5.0
    assert job_progress("DOE_RUN", "BD_DESIGNS", 50) == 5 + 42.5
    assert job_progress("DOE_RUN", "BD_REGISTER", 100) == 100.0
    assert job_progress("DOE_PREP", "BD_GEOM", 0) == 15.0
    assert job_progress("DOE_PREVIEW", "BD_GRID", 100) == 95.0
    for jt, w in DOE_STEP_WEIGHTS.items():
        assert sum(w.values()) == 100, jt


def test_count_states_excludes_nominal():
    from esl_worker.doe_jobs import count_states

    rows = [{"id": "d001", "state": "READY", "warning": None}, {"id": "d002", "state": "SKIPPED_COLLISION"},
            {"id": "d003", "state": "READY", "warning": "THUMB_UNAVAILABLE"}, {"id": "d004", "state": "SKIPPED_FIXED"},
            {"id": "d005", "state": "SKIPPED_GEOM"}]
    assert count_states(rows) == {"ok": 2, "collision": 1, "fixed": 1, "geom": 1, "thumb_warn": 1}


@pytest.mark.parametrize("w,want", [
    ({"code": "BEAD_FIXED_OVERLAP", "bead": "B5", "message": "고정 겹침"}, {"code": "BEAD_FIXED_OVERLAP",
                                                                         "message": "B5: 고정 겹침"}),
    ("B_NO_FASTENERS", {"code": "B_NO_FASTENERS", "message": "B_NO_FASTENERS"}),
    ("PAICAD_VERSION_PINNED: paicad 0.15.0 ≠ 배포 고정 0.14.0",
     {"code": "PAICAD_VERSION_PINNED", "message": "paicad 0.15.0 ≠ 배포 고정 0.14.0"}),
    ("크기 차 ξ +1.2 %", {"code": "PREP_WARNING", "message": "크기 차 ξ +1.2 %"}),
    (None, None),
])
def test_prep_warning_shape(w, want):
    from esl_worker.register import _doe_warning

    assert _doe_warning(w, {}) == want
