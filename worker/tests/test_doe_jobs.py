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


# ---------------------------------------------------------------- v0.17.2 grid 건강·fixed-dir(이슈 #63)
class _Tx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def _hex(monkeypatch, min_ok_frac=None):
    from esl_worker import doe_jobs

    got = {"warnings": [], "result": {}}
    monkeypatch.setattr(doe_jobs.jobs_repo, "add_warnings", lambda _c, _j, _t, items: got["warnings"].extend(items))
    monkeypatch.setattr(doe_jobs.jobs_repo, "patch_result", lambda _c, _j, _t, d: got["result"].update(d))
    ex = SimpleNamespace(job={"id": "j1"}, token="t", _tx=_Tx)
    from esl.doe import settings
    dcfg = settings({"bead_doe": {"grid": {"min_ok_frac": min_ok_frac}} if min_ok_frac is not None else {}})
    return ex, dcfg, got


def _cells(spec):
    return [{"id": f"d{i + 1:03d}", "state": s, "code": c, "warning": None} for i, (s, c) in enumerate(spec)]


def test_grid_all_failed_raises(monkeypatch):
    from esl_worker import doe_jobs
    from esl_worker.executor import _StepFailed

    ex, dcfg, got = _hex(monkeypatch)
    rows = _cells([("SKIPPED_GEOM", "GEOM_CAD_FAILED")] * 29 + [("SKIPPED_GEOM", "GEOM_INTERNAL")])
    ids = [r["id"] for r in rows]
    lines = []
    with pytest.raises(_StepFailed) as ei:
        doe_jobs.check_grid_health(ex, rows, ids, dcfg, lines.append)
    assert ei.value.code == "GRID_ALL_FAILED"
    assert "30개 중 실행 가능 0개" in ei.value.message and "GEOM_CAD_FAILED 29 · GEOM_INTERNAL 1" in ei.value.message
    h = got["result"]["bd_grid_health"]
    assert (h["ok"], h["total"], h["top_codes"]) == (0, 30, [["GEOM_CAD_FAILED", 29], ["GEOM_INTERNAL", 1]])
    assert any("GRID_ALL_FAILED" in x for x in lines)


def test_grid_partial_warns_and_threshold_from_config(monkeypatch):
    from esl_worker import doe_jobs
    from esl_worker.executor import _StepFailed

    rows = _cells([("READY", None)] * 6 + [("SKIPPED_COLLISION", "GEOM_FEATURE_COLLISION")]
                  + [("SKIPPED_GEOM", "GEOM_CAD_FAILED")] * 2 + [("SKIPPED_GEOM", "GEOM_INTERNAL")])
    ids = [r["id"] for r in rows]
    ex, dcfg, got = _hex(monkeypatch)                               # 기본 0.5: 판정 7/10 → READY + 경고
    h = doe_jobs.check_grid_health(ex, rows, ids, dcfg, lambda _m: None)
    assert h["verdict"] == "partial"
    assert got["warnings"] == ["[BD_GRID] GRID_CELLS_FAILED: 미리보기 셀 10개 중 3개 형상 실패(스킵) — "
                               "GEOM_CAD_FAILED 2 · GEOM_INTERNAL 1"]
    ex, dcfg, got = _hex(monkeypatch, 0.8)                          # 설정 0.8: 7/10 < 0.8 → 실패
    with pytest.raises(_StepFailed) as ei:
        doe_jobs.check_grid_health(ex, rows, ids, dcfg, lambda _m: None)
    assert ei.value.code == "GRID_TOO_FEW_OK" and got["warnings"] == []
    ex, dcfg, got = _hex(monkeypatch)                               # 실패 없음 → 경고·결과 없음
    ok = _cells([("READY", None)] * 3)
    assert doe_jobs.check_grid_health(ex, ok, [r["id"] for r in ok], dcfg, lambda _m: None)["verdict"] == "ok"
    assert got == {"warnings": [], "result": {}}


def test_grid_fixed_dir_by_scenario(tmp_path):
    """①② = prep/fixed, ③ = "" — prep/a_fixed(A 모델 좌표)가 있어도 B STEP 고정으로 쓰지 않음(D-0.17.2-AFIXED)."""
    from esl_worker.doe_jobs import grid_fixed_dir

    (tmp_path / "prep" / "a_fixed").mkdir(parents=True)
    (tmp_path / "prep" / "a_fixed" / "shell_scan.json").write_text("{}")
    assert grid_fixed_dir(str(tmp_path), "same") == str(tmp_path / "prep" / "fixed")
    assert grid_fixed_dir(str(tmp_path), "mesh") == str(tmp_path / "prep" / "fixed")
    assert grid_fixed_dir(str(tmp_path), "step") == ""
