"""v0.25.2 TM D 밖 프레임 채움 워커 훅(계약 esl_tstar_manual_jig_force.md §2.4, V-0252-26) — 가짜 hw(h3d_support fr_only 모드).

코어(C1)의 ``frame_fill.merge`` 는 아직 껍데기라 core_adapter.frame_fill_merge 만 계약 서명의 가짜(disp.npz·strain_frames.npz 끝에
프레임 덧붙임 + frames.json frames_fill)로 바꾼다. 판정(DECIDE)·사실(extract_facts)·기록(record)·``frame_point`` 는 실제 코어 접점.
ESL 코어 단계(``_select_frame`` 의 임의 프레임 허용 — C1)는 아직 없으므로 ``Executor._run_core`` 를 가로채 "채움이 코어 앞에서
끝났는지(변위 프레임 있음·hw 세마포어 0)"만 본다. 통합(코어 ESL 성공)은 C1 병합 뒤.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import synth_case
from esl_test_support import API, H, make_settings_dict
from h3d_support import write_fake_hw, write_h3d

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")


@pytest.fixture()
def fake_hw(tmp_path) -> Path:
    return write_fake_hw(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, fake_hw):
    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(fake_hw), "max_concurrent_hw": 1}
    d["worker"]["slots"] = 2
    return d


class FakeMerge:
    """계약 서명 ``merge(extract_dir, fill_out, frame, *, job_id)`` 의 시험용 구현 — 끝에 덧붙임·멱등·frames_fill 기록."""

    def __init__(self, engine):
        self.engine = engine
        self.calls: list[dict] = []
        self.hw_in_use: list[int] = []
        self.error: Exception | None = None

    def __call__(self, extract_dir, fill_out, frame, *, job_id=None):
        from esl_platform.core.repositories import jobs as jobs_repo
        from esl_worker import core_adapter

        with self.engine.connect() as c:
            self.hw_in_use.append(jobs_repo.hw_in_use(c))
        if self.error is not None:
            raise self.error
        done = json.load(open(os.path.join(fill_out, "done.json"), encoding="utf-8"))
        assert done["mode"] == "fr_only" and done["frames"] == [frame]
        added = False
        for name in ("disp.npz", "strain_frames.npz"):
            p = os.path.join(extract_dir, name)
            z = dict(np.load(p, allow_pickle=False))
            fi = z["frame_index"]
            if frame in fi.tolist():
                continue
            added = True
            z["frame_index"] = np.append(fi, np.int32(frame))
            if "u" in z:
                z["u"] = np.concatenate([z["u"], z["u"][:1]], axis=0)
            np.savez(p, **z)
        mp = os.path.join(extract_dir, "frames.json")
        meta = json.load(open(mp, encoding="utf-8"))
        if added:
            meta.setdefault("frames_fill", []).append({"frame_index": frame, "time": frame * 0.001, "at": "x", "job_id": job_id})
            json.dump(meta, open(mp, "w", encoding="utf-8"))
        self.calls.append({"frame": frame, "job_id": job_id, "out": fill_out})
        return {"frame": frame, "time": frame * 0.001, "added": added}


@pytest.fixture()
def fmerge(monkeypatch, engine):
    from esl_worker import core_adapter

    fm = FakeMerge(engine)
    monkeypatch.setattr(core_adapter, "frame_fill_merge", fm)
    return fm


@pytest.fixture()
def core_stub(monkeypatch):
    """코어 ESL 단계를 가로챔 — 호출 시점의 변위 프레임·hw 세마포어를 기록하고 단계를 멈춘다(TEST_STOP)."""
    from esl_worker import executor as ex

    seen: list[dict] = []
    orig = ex.Executor._run_core

    def stub(self, st, log_path, spec_over=None, extra_outputs=None):
        if st["core_stage"] != "esl":                 # 추출·t* 단계는 실제 코어
            return orig(self, st, log_path, spec_over, extra_outputs)
        seen.append({"disp": ex.core_adapter_disp_frames(os.path.join(self.cdir, "01_extract")),
                     "extra": dict(extra_outputs or {})})
        raise ex._StepFailed("TEST_STOP", "코어 단계 앞까지 시험")
    monkeypatch.setattr(ex.Executor, "_run_core", stub)
    return seen


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def _log(client, j, step=1):
    return client.get(f"{API}/jobs/{j['id']}/log", params={"step": step}, headers=R).json()["lines"]


def _extract(client, w, case):
    j = _job(client, case["id"], "CASE_EXTRACT")
    assert w.run_once("SLOT") == "SUCCEEDED", _get(client, j["id"])


def _manual_case(client, synth, w, monkeypatch, folder="case01"):
    """h3d Case 추출 → 실제 코어 frame_point 로 D 밖 프레임을 직접 t* 로 확정 → 지지점. 반환 (case, frame)."""
    monkeypatch.setenv("FAKE_HW_SRC", synth["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    h3d = write_h3d(Path(synth["rad"]).parent / f"{folder}_drop.h3d")
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": folder, "title": "h3d", "rad_path": synth["rad"],
                                          "h3d_path": str(h3d)}, headers=W)
    assert r.status_code == 201, r.text
    case = r.json()
    _extract(client, w, case)
    case = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    tj = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()
    out = [f["frame_index"] for f in tj["frames"] if f["frame_index"] not in tj["frames_have"]]
    assert out, (tj["frames_have"], len(tj["frames"]))
    f = out[0]
    assert tj["fill"]["available"] is True
    r = client.put(f"{API}/cases/{case['id']}/tstar", json={"version": case["version"], "metric": tj["default_metric"],
                                                            "frame_index": f}, headers=W)
    assert r.status_code == 200, r.text
    assert r.json()["tstar"]["frame_index"] == f and r.json()["tstar"]["manual"]["have"] is False
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    s = client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    assert s.status_code == 201, s.text
    return client.get(f"{API}/cases/{case['id']}", headers=R).json(), f


def _esl(client, w, case):
    j = _job(client, case["id"], "ESL_SOLVE")
    w.run_once("SLOT")
    return _get(client, j["id"])


def _argvs(esl_root, folder="case01"):
    return sorted((Path(esl_root) / "_h3d" / folder / "frame_fill").glob("argv_*.json"))


def _attempts(esl_root, folder="case01"):
    p = Path(esl_root) / folder / "01_extract" / "frame_fill.json"
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


def _outputs(engine, j, step_no=1) -> dict:
    from sqlalchemy import text

    with engine.connect() as c:
        return c.execute(text("SELECT outputs FROM job_steps WHERE job_id = :j AND step_no = :n"),
                         {"j": j["id"], "n": step_no}).scalar_one() or {}


# ---------------------------------------------------------------- V-0252-26 채움 · 재사용 · 세마포어
def test_fill_before_core_then_reuse(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, engine):
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    j = _esl(client, w, case)
    # 채움은 코어 앞에서 끝남: 코어 호출 시점에 변위 프레임에 f 가 있고 hw 세마포어 0
    assert len(core_stub) == 1 and f in core_stub[0]["disp"] and fmerge.hw_in_use == [0]
    assert core_stub[0]["extra"]["frame_fill"]["status"] == "ok"
    assert j["state"] == "FAILED" and j["steps"][0]["failure_code"] == "TEST_STOP"      # 시험이 코어에서 멈춤(채움은 성공)
    # 가짜 hw 1회: request fr_only 1·fr_frames f·strain_sources, bf 키는 설정(기본 끔)
    av = _argvs(esl_root)
    assert len(av) == 1
    rec = json.loads(av[0].read_text())["argv"]
    assert rec[rec.index("-output") + 1] == str(Path(esl_root) / "_h3d" / "case01" / "frame_fill" / "raw")
    req = (Path(esl_root) / "_h3d" / "case01" / "frame_fill" / "request.txt").read_text()
    assert "fr_only\t1\n" in req and f"fr_frames\t{f}\n" in req and "strain_sources\t" in req and "bf_only" not in req
    assert len(req.split("strain_sources\t")[1].split("\n")[0].split()) == 1       # 추출 때 source 하나로 고정
    # 병합 호출(job_id = ESL 작업 id)·시도 기록(실제 코어 record)·결과 키
    assert fmerge.calls[0]["frame"] == f and fmerge.calls[0]["job_id"] == j["id"]
    at = _attempts(esl_root)
    assert len(at) == 1 and at[0]["status"] == "ok" and at[0]["frame"] == f and at[0]["job_id"] == j["id"]
    fi = j["result"]["frame_fill"]
    assert fi["status"] == "ok" and fi["frame"] == f and fi["seconds"] is not None and "cause" not in fi
    # step outputs 는 코어 단계 성공 때 extras(frame_fill 포함)로 한 번에 기록됨 — 여기서는 코어가 가로채여 extra_outputs 로 확인(위)
    log = _log(client, j)
    assert any(f"직접 고른 t*: 프레임 {f}" in ln for ln in log) and any("프레임 채움 완료" in ln for ln in log)
    assert any("hw pid" in ln and "시간 한도 1800 s" in ln for ln in log)
    # 두 번째 ESL = hw 0 · frame_fill 키 없음(이미 채운 프레임 재사용)
    j2 = _esl(client, w, case)
    assert len(_argvs(esl_root)) == 1 and len(fmerge.calls) == 1 and len(core_stub) == 2
    assert "frame_fill" not in (j2["result"] or {}) and "frame_fill" not in core_stub[1]["extra"]
    assert len(_attempts(esl_root)) == 1


def test_auto_tstar_no_fill_no_log(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub):
    """자동 t*(변위 있음) = 훅이 아무것도 안 함: hw 0·frame_fill 키 없음(옛 경로 그대로)."""
    w = worker_factory()
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    h3d = write_h3d(Path(synth_inputs["rad"]).parent / "a_drop.h3d")
    case = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": "case01", "title": "h3d",
                                             "rad_path": synth_inputs["rad"], "h3d_path": str(h3d)}, headers=W).json()
    _extract(client, w, case)
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    j = _esl(client, w, case)
    assert j["steps"][0]["failure_code"] == "TEST_STOP" and "frame_fill" not in (j["result"] or {})
    assert _argvs(esl_root) == [] and fmerge.calls == [] and _attempts(esl_root) == []
    assert not any("프레임 채움" in ln for ln in _log(client, j))


# ---------------------------------------------------------------- 실패 = ESL 단계 실패
@pytest.mark.parametrize("env,cause", [({"FAKE_HW_FR_MODE": "wrongmode"}, "HW_FAILED"), ({"FAKE_HW_FR_MODE": "nofiles"}, "HW_FAILED"),
                                       ({"FAKE_HW_MODE": "fail"}, "HW_FAILED"), ({"FAKE_HW_MODE": "license"}, "LICENSE")])
def test_hw_failures_fail_step_and_retry(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, env, cause):
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    j = _esl(client, w, case)
    st = j["steps"][0]
    assert j["state"] == "FAILED" and st["failure_code"] == "TSTAR_FRAME_FILL_FAILED" and st["failure_message"]
    assert core_stub == [] and fmerge.calls == []                                        # 코어 단계까지 가지 않음
    fi = j["result"]["frame_fill"]
    assert fi["status"] == "failed" and fi["cause"] == cause and fi["detail"] == st["failure_message"]
    a = _attempts(esl_root)[-1]
    assert a["status"] == "failed" and a["cause"] == cause and a["frame"] == f
    assert any("프레임 채움 실패" in ln and "TSTAR_FRAME_FILL_FAILED" in ln for ln in _log(client, j))
    # 다시 실행 = 재시도(정상 hw)
    for k in env:
        monkeypatch.delenv(k)
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    j2 = _esl(client, w, case)
    assert len(core_stub) == 1 and f in core_stub[0]["disp"] and j2["result"]["frame_fill"]["status"] == "ok"
    assert [x["status"] for x in _attempts(esl_root)] == ["failed", "ok"]


def test_merge_mismatch_and_semaphore_released(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub,
                                               engine):
    from esl_platform.core.repositories import jobs as jobs_repo
    from esl_worker import core_adapter

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    fmerge.error = core_adapter.CoreError("FRAME_FILL_MISMATCH", "프레임 수가 추출 때와 다름")
    j = _esl(client, w, case)
    st = j["steps"][0]
    assert st["failure_code"] == "TSTAR_FRAME_FILL_FAILED" and j["result"]["frame_fill"]["cause"] == "MISMATCH"
    assert "① 추출부터 다시" in st["failure_message"]
    fmerge.error = core_adapter.CoreError("FRAME_FILL_MERGE", "읽기 실패")
    j = _esl(client, w, case)
    assert j["result"]["frame_fill"]["cause"] == "MERGE"
    with engine.connect() as c:
        assert jobs_repo.hw_in_use(c) == 0                                               # 세마포어 반납
    assert core_stub == []


def test_wait_fails_when_semaphore_busy(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    object.__setattr__(w.settings.altair, "frame_fill_wait_s", 1)
    monkeypatch.setattr(jobs_repo, "acquire_hw", lambda *a, **k: False)
    t0 = time.time()
    j = _esl(client, w, case)
    assert time.time() - t0 < 60 and j["steps"][0]["failure_code"] == "TSTAR_FRAME_FILL_FAILED"
    fi = j["result"]["frame_fill"]
    assert fi["cause"] == "WAIT" and "동시 실행 한도 1개가 1 s" in fi["detail"] and "frame_fill_wait_s" in fi["detail"]
    assert _argvs(esl_root) == [] and any("hw 동시 실행 한도 1개" in ln for ln in _log(client, j))


def test_hang_timeout(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, tmp_path):
    from h3d_support import alive
    from esl_test_support import wait_for

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    pids = tmp_path / "hw.pids"
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(pids))
    object.__setattr__(w.settings.altair, "frame_fill_timeout_s", 2)
    j = _esl(client, w, case)
    fi = j["result"]["frame_fill"]
    assert fi["cause"] == "TIMEOUT" and "시간 초과 2 s" in fi["detail"] and "frame_fill_timeout_s" in fi["detail"]
    hw_pid, child = map(int, pids.read_text().split())
    wait_for(lambda: not alive(hw_pid) and not alive(child), timeout=10)


def test_blocked_at_worker_time_no_hw(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub):
    """API 가 허용한 뒤 판정이 막힘으로 바뀌면(행 3 덤프 방식) 워커는 hw 를 띄우지 않고 단계 실패 — 기록 status blocked."""
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    from esl_platform.core import job_params

    monkeypatch.setattr(job_params, "_fill_ok", lambda *a, **k: True)
    mp = Path(esl_root) / "case01" / "01_extract" / "frames.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["strain_fallback"] = {**(meta.get("strain_fallback") or {}), "mode": "dump"}
    mp.write_text(json.dumps(meta), encoding="utf-8")
    j = _esl(client, w, case)
    st = j["steps"][0]
    assert st["failure_code"] == "TSTAR_FRAME_FILL_FAILED" and "덤프 방식" in st["failure_message"], (j["failure_code"], st)
    fi = j["result"]["frame_fill"]
    assert fi["status"] == "blocked" and fi["cause"] == "DUMP_MODE"
    assert _argvs(esl_root) == [] and _attempts(esl_root)[-1]["status"] == "blocked" and core_stub == []
    assert any("프레임 채움 불가(DUMP_MODE)" in ln for ln in _log(client, j))


def test_reextract_then_fill_again(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub):
    """① 재추출 = 01_extract 가 새로 → 채운 프레임이 사라져 다음 ESL 에서 자동으로 다시 채움(판정 행 6)."""
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    _esl(client, w, case)
    assert len(_argvs(esl_root)) == 1
    _extract(client, w, case)
    c2 = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    tj = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()
    assert f not in tj["frames_have"]
    r = client.put(f"{API}/cases/{case['id']}/tstar", json={"version": c2["version"], "metric": tj["default_metric"],
                                                            "frame_index": f}, headers=W)
    assert r.status_code == 200, r.text
    j = _esl(client, w, client.get(f"{API}/cases/{case['id']}", headers=R).json())
    assert j["result"]["frame_fill"]["status"] == "ok" and len(fmerge.calls) == 2 and len(_argvs(esl_root)) == 2


def test_semaphore_held_only_during_fill(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, engine):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    monkeypatch.setenv("FAKE_HW_DELAY", "2")
    j = _job(client, case["id"], "ESL_SOLVE")
    seen: list[int] = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            with engine.connect() as c:
                seen.append(jobs_repo.hw_in_use(c))
            time.sleep(0.05)

    th = threading.Thread(target=poll)
    th.start()
    try:
        w.run_once("SLOT")
    finally:
        stop.set()
        th.join()
    assert 1 in seen and seen[-1] == 0 and fmerge.hw_in_use == [0], seen[-5:]


def test_fill_log_and_bf_merge_same_run(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub):
    """경계력 켬 + 같은 실행에 bforce 키가 있으면 같은 fill_out 으로 경계력 병합(실패해도 채움 성공)."""
    from esl_worker import core_adapter

    calls: list[tuple] = []
    monkeypatch.setattr(core_adapter, "bforce_merge", lambda cd, fo, fr, *, tag, names: calls.append((fr, tag)) or {"kinds": {"cont": "Contact Forces"}})
    monkeypatch.setenv("FAKE_HW_FR_BF", "1")
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch)
    j = _esl(client, w, case)
    assert j["result"]["frame_fill"]["status"] == "ok"
    assert calls == [([f], j["id"])] and any("경계력 원자료도 병합" in ln for ln in _log(client, j))
    # 경계력 병합이 오류여도 채움은 성공
    def boom(*a, **k):
        raise core_adapter.CoreError("BF_FILL_MISMATCH", "x")
    monkeypatch.setattr(core_adapter, "bforce_merge", boom)
    _extract(client, w, case)       # 01_extract 새로 → 다시 채움
    c2 = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    tj = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()
    assert client.put(f"{API}/cases/{case['id']}/tstar", json={"version": c2["version"], "metric": tj["default_metric"],
                                                               "frame_index": f}, headers=W).status_code == 200
    j2 = _esl(client, w, client.get(f"{API}/cases/{case['id']}", headers=R).json())
    assert j2["result"]["frame_fill"]["status"] == "ok" and any("경계력 원자료 병합 생략" in ln for ln in _log(client, j2))


# ---------------------------------------------------------------- 순수 함수
def test_evaluate_pure(tmp_path):
    from esl_worker import frame_fill as ff

    out = tmp_path
    assert ff.evaluate(0, str(out), 3)[:2] == (False, "HW_FAILED")
    (out / "done.json").write_text(json.dumps({"ok": True, "mode": "fr_only", "frames": [3]}))
    assert ff.evaluate(0, str(out), 3)[0] is False                                       # csv 없음
    (out / "disp.csv").write_text("x")
    (out / "strain_frames.csv").write_text("x")
    assert ff.evaluate(0, str(out), 3)[0] is True
    assert ff.evaluate(1, str(out), 3)[0] is False and ff.evaluate(0, str(out), 4)[0] is False
    (out / "done.json").write_text(json.dumps({"ok": True, "mode": "full", "frames": [3]}))
    assert ff.evaluate(0, str(out), 3)[0] is False
    (out / "done.json").write_text(json.dumps({"ok": False, "error": "x", "errorInfo": "no License"}))
    ok, cause, detail, _ = ff.evaluate(1, str(out), 3)
    assert not ok and cause == "LICENSE" and len(detail) <= 300
    assert ff.evaluate(1, str(out), 3, "FlexLM licence error")[1] == "LICENSE"


def test_cause_text_and_summary():
    from esl_worker import frame_fill as ff

    for c in ff.FAILED_CAUSES:
        ff.detail_text(c, limit=1, wait=1.0, timeout=1.0, msg="m")
    a = ff.attempt_record(frame=5, job_id="j", cause="TIMEOUT", detail="d", seconds=1.234)
    assert a["status"] == "failed" and a["seconds"] == 1.2
    assert ff.summary_of(a) == {"status": "failed", "frame": 5, "seconds": 1.2, "cause": "TIMEOUT", "detail": "d"}
    ok = ff.attempt_record(frame=5, job_id="j", cause=None, detail="", seconds=2.0)
    assert ff.summary_of(ok) == {"status": "ok", "frame": 5, "seconds": 2.0}
    assert ff.attempt_record(frame=5, job_id="j", cause="NO_H3D", detail="x", seconds=None, blocked=True)["status"] == "blocked"


def test_request_extra_keys():
    from esl_worker import frame_fill as ff

    meta = {"strain_fallback": {"mode": "direct", "source": "Max_Strain"}}
    keys = ff.request_extra({}, meta, 7)
    assert keys["fr_only"] == "1" and keys["fr_frames"] == "7" and keys["strain_sources"] and " " not in keys["strain_sources"]
    assert "bf_only" not in keys and "bf_on" in keys
    with pytest.raises(Exception):                                                      # 덤프 방식 = INPUT_INVALID(행 3 이 먼저 막음)
        ff.request_extra({}, {"strain_fallback": {"mode": "dump"}}, 7)


def test_facts_and_fill_state(tmp_path):
    from esl_worker import frame_fill as ff

    h3d = tmp_path / "a.h3d"
    h3d.write_bytes(b"x")
    ex = tmp_path / "01_extract"
    ex.mkdir()
    case = {"input_kind": "H3D", "h3d_path": str(h3d)}
    assert ff.fill_state(case, str(ex)) == {"available": True, "code": None, "text": None}
    s = ff.fill_state({"input_kind": "RESULTS", "h3d_path": None}, str(ex))
    assert s["available"] is False and s["code"] == "NO_H3D"
    assert ff.fill_state({**case, "h3d_path": str(tmp_path / "none.h3d")}, str(ex))["code"] == "H3D_UNREADABLE"
    assert "none.h3d" in ff.fill_state({**case, "h3d_path": str(tmp_path / "none.h3d")}, str(ex))["text"]
