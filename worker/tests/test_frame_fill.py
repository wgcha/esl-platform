"""v0.25.2 TM D 밖 프레임 채움 워커 훅(계약 esl_tstar_manual_jig_force.md §2.4, V-0252-26) — 가짜 hw(h3d_support fr_only 모드).

가짜 hw 의 채움 출력 = 같은 합성 결과를 전 프레임 D 로 쓴 CSV(``FAKE_HW_FR_SRC``)의 f·f−1 행 → **실제 코어** ``frame_fill.merge``
(같은 h3d 확인·끝에 덧붙임·frames_fill)·판정(DECIDE)·사실(extract_facts)·기록(record)·``frame_point``·코어 ESL 단계
(``_select_frame`` 임의 프레임)를 그대로 쓴다(통합 — B1 이 C1 껍데기 시점에 둔 가짜 merge·코어 가로채기 제거).
``fmerge`` = 실제 merge 를 부르는 관찰자(호출 시점 hw 세마포어 기록 · 시험이 ``error`` 를 주면 그 오류를 냄 — FRAME_FILL_MERGE 경로만).
``core_spy`` = 코어 단계 호출 시점의 변위 프레임을 기록하고 실제 코어를 그대로 부른다.
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


@pytest.fixture(scope="module")
def full_csv(tmp_path_factory) -> str:
    """같은 합성 결과(synth_case — 결정적)를 전 프레임 D 로 쓴 결과 CSV 폴더(가짜 hw 채움 출력의 원본 — 처음부터 추출과 같은 값)."""
    import functools

    orig = synth_case.write_results_csv
    synth_case.write_results_csv = functools.partial(orig, frames_D=list(range(synth_case.A_T.size)))
    try:
        return synth_case.build(str(tmp_path_factory.mktemp("full")))["csv"]
    finally:
        synth_case.write_results_csv = orig


class MergeSpy:
    """실제 코어 ``merge(extract_dir, fill_out, frame, *, job_id)`` 를 부르며 호출·호출 시점 hw 세마포어를 기록."""

    def __init__(self, engine, real):
        self.engine = engine
        self.real = real
        self.calls: list[dict] = []
        self.hw_in_use: list[int] = []
        self.error: Exception | None = None

    def __call__(self, extract_dir, fill_out, frame, *, job_id=None):
        from esl_platform.core.repositories import jobs as jobs_repo

        with self.engine.connect() as c:
            self.hw_in_use.append(jobs_repo.hw_in_use(c))
        if self.error is not None:
            raise self.error
        r = self.real(extract_dir, fill_out, frame, job_id=job_id)
        self.calls.append({"frame": frame, "job_id": job_id, "out": fill_out, "added": r["added"]})
        return r


@pytest.fixture()
def fmerge(monkeypatch, engine):
    from esl_worker import core_adapter

    fm = MergeSpy(engine, core_adapter.frame_fill_merge)
    monkeypatch.setattr(core_adapter, "frame_fill_merge", fm)
    return fm


@pytest.fixture()
def core_stub(monkeypatch):
    """코어 ESL 단계 관찰 — 호출 시점의 변위 프레임·추가 출력(frame_fill)을 기록하고 실제 코어를 부른다."""
    from esl_worker import executor as ex

    seen: list[dict] = []
    orig = ex.Executor._run_core

    def spy(self, st, log_path, spec_over=None, extra_outputs=None):
        if st["core_stage"] == "esl":
            seen.append({"disp": ex.core_adapter_disp_frames(os.path.join(self.cdir, "01_extract")),
                         "extra": dict(extra_outputs or {})})
        return orig(self, st, log_path, spec_over, extra_outputs)
    monkeypatch.setattr(ex.Executor, "_run_core", spy)
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


def _manual_case(client, synth, w, monkeypatch, full_csv, folder="case01"):
    """h3d Case 추출 → 실제 코어 frame_point 로 D 밖 프레임을 직접 t* 로 확정 → 지지점. 반환 (case, frame)."""
    monkeypatch.setenv("FAKE_HW_SRC", synth["csv"])
    monkeypatch.setenv("FAKE_HW_FR_SRC", full_csv)
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
def test_fill_before_core_then_reuse(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, engine, full_csv):
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
    j = _esl(client, w, case)
    # 채움은 코어 앞에서 끝남: 코어 호출 시점에 변위 프레임에 f 가 있고 hw 세마포어 0 → 실제 코어 ESL 성공
    assert len(core_stub) == 1 and f in core_stub[0]["disp"] and fmerge.hw_in_use == [0]
    assert core_stub[0]["extra"]["frame_fill"]["status"] == "ok"
    assert j["state"] == "SUCCEEDED", (j["state"], j["steps"][0].get("failure_code"), j["steps"][0].get("failure_message"))
    assert fmerge.calls[0]["added"] is True                                              # 실제 병합이 끝에 덧붙임
    xd = Path(esl_root) / "case01" / "01_extract"
    meta = json.loads((xd / "frames.json").read_text(encoding="utf-8"))
    assert [e["frame_index"] for e in meta["frames_fill"]] == [f] and f not in meta["frames_D"]
    assert meta["frames_fill"][0]["job_id"] == j["id"]
    with np.load(xd / "disp.npz") as z:
        assert int(z["frame_index"][-1]) == f                                            # 끝에 덧붙음
    summ = json.loads((Path(esl_root) / "case01" / "04_esl" / "esl_summary.json").read_text(encoding="utf-8"))
    tm = summ["tstar_manual"]
    assert tm["filled"] is True and tm["in_D"] is False and tm["auto_frame"] == synth_case.T_STAR_FRAME
    assert _outputs(engine, j)["frame_fill"]["status"] == "ok"                           # step outputs(코어 단계 성공 때 extras)
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
    log = _log(client, j)
    assert any(f"직접 고른 t*: 프레임 {f}" in ln for ln in log) and any("프레임 채움 완료" in ln for ln in log)
    assert any("hw pid" in ln and "시간 한도 1800 s" in ln for ln in log)
    # 두 번째 ESL = hw 0 · frame_fill 키 없음(이미 채운 프레임 재사용)
    j2 = _esl(client, w, case)
    assert j2["state"] == "SUCCEEDED" and len(_argvs(esl_root)) == 1 and len(fmerge.calls) == 1 and len(core_stub) == 2
    assert "frame_fill" not in (j2["result"] or {}) and "frame_fill" not in core_stub[1]["extra"]
    assert "frame_fill" not in _outputs(engine, j2)
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
    assert j["state"] == "SUCCEEDED" and "frame_fill" not in (j["result"] or {})
    assert _argvs(esl_root) == [] and fmerge.calls == [] and _attempts(esl_root) == []
    assert not any("프레임 채움" in ln for ln in _log(client, j))


# ---------------------------------------------------------------- 실패 = ESL 단계 실패
@pytest.mark.parametrize("env,cause", [({"FAKE_HW_FR_MODE": "wrongmode"}, "HW_FAILED"), ({"FAKE_HW_FR_MODE": "nofiles"}, "HW_FAILED"),
                                       ({"FAKE_HW_MODE": "fail"}, "HW_FAILED"), ({"FAKE_HW_MODE": "license"}, "LICENSE")])
def test_hw_failures_fail_step_and_retry(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, env, cause, full_csv):
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
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
    assert j2["state"] == "SUCCEEDED"
    assert [x["status"] for x in _attempts(esl_root)] == ["failed", "ok"]


def test_merge_mismatch_and_semaphore_released(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub,
                                               engine, full_csv):
    from esl_platform.core.repositories import jobs as jobs_repo
    from esl_worker import core_adapter

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
    xd = Path(esl_root) / "case01" / "01_extract"
    before = {n: (xd / n).read_bytes() for n in ("disp.npz", "strain_frames.npz", "frames.json")}
    monkeypatch.setenv("FAKE_HW_FR_NFRAMES", "99")                     # 다른 h3d(프레임 수) → 실제 코어 FRAME_FILL_MISMATCH
    j = _esl(client, w, case)
    st = j["steps"][0]
    assert st["failure_code"] == "TSTAR_FRAME_FILL_FAILED" and j["result"]["frame_fill"]["cause"] == "MISMATCH"
    assert "① 추출부터 다시" in st["failure_message"]
    assert {n: (xd / n).read_bytes() for n in before} == before                            # 아무것도 안 씀
    monkeypatch.delenv("FAKE_HW_FR_NFRAMES")
    fmerge.error = core_adapter.CoreError("FRAME_FILL_MERGE", "읽기 실패")
    j = _esl(client, w, case)
    assert j["result"]["frame_fill"]["cause"] == "MERGE"
    with engine.connect() as c:
        assert jobs_repo.hw_in_use(c) == 0                                               # 세마포어 반납
    assert core_stub == []


def test_wait_fails_when_semaphore_busy(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, full_csv):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
    object.__setattr__(w.settings.altair, "frame_fill_wait_s", 1)
    monkeypatch.setattr(jobs_repo, "acquire_hw", lambda *a, **k: False)
    t0 = time.time()
    j = _esl(client, w, case)
    assert time.time() - t0 < 60 and j["steps"][0]["failure_code"] == "TSTAR_FRAME_FILL_FAILED"
    fi = j["result"]["frame_fill"]
    assert fi["cause"] == "WAIT" and "동시 실행 한도 1개가 1 s" in fi["detail"] and "frame_fill_wait_s" in fi["detail"]
    assert _argvs(esl_root) == [] and any("hw 동시 실행 한도 1개" in ln for ln in _log(client, j))


def test_hang_timeout(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, tmp_path, full_csv):
    from h3d_support import alive
    from esl_test_support import wait_for

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
    pids = tmp_path / "hw.pids"
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(pids))
    object.__setattr__(w.settings.altair, "frame_fill_timeout_s", 2)
    j = _esl(client, w, case)
    fi = j["result"]["frame_fill"]
    assert fi["cause"] == "TIMEOUT" and "시간 초과 2 s" in fi["detail"] and "frame_fill_timeout_s" in fi["detail"]
    hw_pid, child = map(int, pids.read_text().split())
    wait_for(lambda: not alive(hw_pid) and not alive(child), timeout=10)


def test_blocked_at_worker_time_no_hw(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, full_csv):
    """API 가 허용한 뒤 판정이 막힘으로 바뀌면(행 3 덤프 방식) 워커는 hw 를 띄우지 않고 단계 실패 — 기록 status blocked."""
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
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


def test_reextract_then_fill_again(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, full_csv):
    """① 재추출 = 01_extract 가 새로 → 채운 프레임이 사라져 다음 ESL 에서 자동으로 다시 채움(판정 행 6)."""
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
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
    assert j["state"] == "SUCCEEDED" and all(c["added"] for c in fmerge.calls)


def test_semaphore_held_only_during_fill(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, engine, full_csv):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
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


def test_fill_log_and_bf_merge_same_run(client, synth_inputs, worker_factory, esl_root, monkeypatch, fmerge, core_stub, full_csv):
    """경계력 켬 + 같은 실행에 bforce 키가 있으면 같은 fill_out 으로 경계력 병합(실패해도 채움 성공)."""
    from esl_worker import core_adapter

    calls: list[tuple] = []
    monkeypatch.setattr(core_adapter, "bforce_merge", lambda cd, fo, fr, *, tag, names: calls.append((fr, tag)) or {"kinds": {"cont": "Contact Forces"}})
    monkeypatch.setenv("FAKE_HW_FR_BF", "1")
    w = worker_factory()
    case, f = _manual_case(client, synth_inputs, w, monkeypatch, full_csv)
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
