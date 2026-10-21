"""서버 h3d 추출 진행 표시: TCL 이 출력 폴더에 쓰는 progress.log 를 워커가 step 로그로 옮김(hw 가 Tcl stdout 을 내보내지 않는
설치 대비), 무변화 하트비트, 진행률(step.progress_pct) 계산. TCL 변경은 정적 시험."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from esl_test_support import API, H
from test_h3d_extract import _get, _h3d_case, _job, fake_hw, settings_dict  # noqa: F401  (fixtures)

R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")

PLINES = ["2026-10-21 10:00:00 open session and load model/results (can take minutes for a large h3d)",
          "2026-10-21 10:00:01 model load done (1.0 s)",
          "2026-10-21 10:00:02 part 7 (chassis_rear): 223415 elements, 900 nodes, 4 frames",
          "2026-10-21 10:00:03 pass A done (0.5 s)",
          "2026-10-21 10:00:04 pass B frame 2/4 (10 elements)",
          "2026-10-21 10:00:05 pass C done (1.0 s)",
          "2026-10-21 10:00:06 extract done: 1 elements"]


def _env(monkeypatch, synth_inputs, **extra):
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "progress")
    monkeypatch.setenv("FAKE_HW_PLINES", "|".join(PLINES))
    monkeypatch.setenv("FAKE_HW_PLINE_DELAY", "0.25")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_progress_log_relayed_without_stdout(client, synth_inputs, worker_factory, monkeypatch):
    from esl_worker import h3d as h3dmod

    monkeypatch.setattr(h3dmod, "PROGRESS_POLL_S", 0.1)
    monkeypatch.setattr(h3dmod, "PROGRESS_HEARTBEAT_S", 0.5)
    _env(monkeypatch, synth_inputs, FAKE_HW_PLOG_LATE="0.6", FAKE_HW_TAIL_PAUSE="1.0")  # 늦게 생김 + 무변화 구간
    case = _h3d_case(client, synth_inputs)
    job = _job(client, case["id"])
    assert worker_factory().run_once("SLOT") == "SUCCEEDED"
    log = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()["lines"]
    txt = "\n".join(log)
    assert not any("fake hw start" in ln for ln in log)                         # stdout 은 비어 있었다
    for want in ("model load done (1.0 s)", "part 7 (chassis_rear): 223415 elements", "pass B frame 2/4",
                 "extract done: 1 elements"):
        assert want in txt, want
    assert any("추출 진행 중" in ln and "출력 폴더 크기" in ln for ln in log)         # 하트비트
    assert any("bad bytes" in ln for ln in log)                                 # 깨진 바이트도 안전하게
    assert sum("model load done" in ln for ln in log) == 1                      # 중복 없음
    assert log.index(next(ln for ln in log if "pass B frame" in ln)) < log.index(
        next(ln for ln in log if "extract done: 1" in ln))
    assert any("extract done -> pack" in ln for ln in log)                      # 종료 후 잔여 줄까지 옮긴 뒤
    assert _get(client, job["id"])["steps"][0]["state"] == "SUCCEEDED"


def test_progress_tail_partial_late_and_remainder(tmp_path):
    from esl_worker import h3d as h3dmod

    t = h3dmod.ProgressTail(str(tmp_path))
    assert t.poll() == []                                   # 파일 없음
    f = tmp_path / "progress.log"
    f.write_bytes(b"a\nb")                                 # 마지막 줄 미완성
    assert t.poll() == ["a"]
    with open(f, "ab") as fh:
        fh.write(b"c\n\xff\xfe\n")
    assert t.poll() == ["bc", "��"]
    with open(f, "ab") as fh:
        fh.write(b"tail")
    assert t.poll() == []
    assert t.poll(flush=True) == ["tail"] and t.poll(flush=True) == []


def test_progress_tracker_monotonic_and_weights():
    from esl_worker import h3d as h3dmod

    tr = h3dmod.ProgressTracker(100.0, now=0.0)
    assert tr.tick(50.0) == pytest.approx(7.25)               # 로드 중: 경과시간 기반, 15% 미만
    assert tr.tick(1000.0) == pytest.approx(14.5)
    seq = [("part 7 (x): 10 elements, 5 nodes, 4 frames", 15), ("pass A (frame 3) elements chunk 1/2 (5)", 15),
           ("pass A done (1.0 s)", 25), ("pass B frame 1/4 (3 elements)", 25), ("pass B frame 3/4 (3 elements)", 47.5),
           ("candidate frames: a", 70), ("pass C frame 1 (1/2) elements chunk 1/2", 70),
           ("pass C frame 2 (2/2) nodes chunk 1/1", 70 + 25 * (1 + .9) / 2), ("pass C done (1 s)", 95),
           ("extract done: 1", 98)]
    prev = 0.0
    for ln, want in seq:
        got = tr.feed("2026-10-21 10:00:00 " + ln)
        assert got >= prev and got == pytest.approx(max(prev, want)), (ln, got, want)
        prev = got
    assert tr.feed("pass B frame 1/4 (3 elements)") == prev          # 되감기 없음
    tr.feed("step write_done")
    assert tr.last_step == "write_done" and tr.pct < 100


def test_progress_pct_written_to_step(client, synth_inputs, worker_factory, monkeypatch):
    from esl_platform.core.repositories import jobs as jobs_repo
    from esl_worker import h3d as h3dmod

    seen: list[float] = []
    orig = jobs_repo.step_update

    def spy(conn, job_id, token, step_no, **values):
        if "progress_pct" in values and step_no == 1:
            seen.append(values["progress_pct"])
        return orig(conn, job_id, token, step_no, **values)

    monkeypatch.setattr(jobs_repo, "step_update", spy)
    monkeypatch.setattr(h3dmod, "PROGRESS_POLL_S", 0.1)
    _env(monkeypatch, synth_inputs)
    case = _h3d_case(client, synth_inputs)
    _job(client, case["id"])
    assert worker_factory().run_once("SLOT") == "SUCCEEDED"
    mid = [x for x in seen if 0 < x < 100]
    assert mid and mid == sorted(mid) and max(mid) >= 25          # 단계별로 차오르고 되감기 없음


def test_tcl_progress_log_static():
    src = (Path(__file__).resolve().parents[2] / "resources" / "tcl" / "esl_h3d_extract.tcl").read_text(encoding="ascii")
    assert "proc ::esl::plog " in src and "progress.log" in src and "-buffering line" in src and "flush $plog_fh" in src
    assert "done.json progress.log *.csv" in src                                   # 이전 로그도 _backup 으로
    assert src.index("::esl::backup_outputs $out") < src.index("set ::esl::plog_on 1")  # 백업 후에 켠다
    for want in ('"$label done (${sec} s)$bad"', "pass A start", "pass B done", "pass C start", "disp done",
                 "extract done:", "trace add execution ::esl::alt enter"):
        assert want in src, want
    assert "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]" in src
