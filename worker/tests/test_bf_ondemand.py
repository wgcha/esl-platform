"""v0.24.2 경계력 원자료 ESL 때 보충(계약 esl_bforce_ondemand.md V-0242-BFD-7~11) — 워커 판정·실행·세마포어·실패 처리.

코어(묶음 A)의 병합·기록·프레임 확인(esl.io.bforce_*)은 core_adapter 래퍼를 가짜로 바꿔 시험한다(통합 시험은 병합 뒤).
가짜 hw(h3d_support) = bf 전용 흉내(FAKE_HW_BF_SRC).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
import synth_case
from esl_test_support import API, H, create_case, wait_for
from esl_test_support import make_settings_dict
from h3d_support import alive, write_fake_hw, write_h3d

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")

BF_CSV = "frame_index,node_id,x,y,z\n" + "".join(f"{f},{n},1.5,0.25,-3.0\n" for f in (0, synth_case.T_STAR_FRAME)
                                                   for n in (1, 2))


@pytest.fixture()
def fake_hw(tmp_path) -> Path:
    return write_fake_hw(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, fake_hw):
    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(fake_hw), "max_concurrent_hw": 1}
    d["worker"]["slots"] = 2
    return d


@pytest.fixture()
def bf_src(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "bf_src"
    d.mkdir()
    (d / "bf_cont.csv").write_text(BF_CSV, encoding="utf-8")
    monkeypatch.setenv("FAKE_HW_BF_SRC", str(d))
    monkeypatch.setenv("FAKE_HW_BF_NFRAMES", "61")
    return d


class FakeCore:
    """묶음 A 의 esl.io.bforce_* 계약 서명 흉내: 병합 = 01_extract/bforce_fake.json 에 프레임 추가,
    기록 = bforce_ondemand.json 누적(§4.6)."""

    def __init__(self, extract_root_hint=None):
        self.merges: list[dict] = []
        self.has_calls = 0
        self.hw_in_use_at_merge: list[int] = []
        self.engine = None
        self.merge_error: Exception | None = None

    # 파일 규칙
    @staticmethod
    def _frames(extract_dir):
        p = os.path.join(extract_dir, "bforce_fake.json")
        if not os.path.isfile(p):
            return []
        return json.load(open(p, encoding="utf-8"))["frames"]

    def has_frame(self, extract_dir, frame):
        self.has_calls += 1
        return int(frame) in self._frames(extract_dir)

    def merge(self, case_dir, fill_out, frames, *, tag, names):
        from esl_platform.core.repositories import jobs as jobs_repo

        if self.engine is not None:
            with self.engine.connect() as c:
                self.hw_in_use_at_merge.append(jobs_repo.hw_in_use(c))
        if self.merge_error is not None:
            raise self.merge_error
        done = json.load(open(os.path.join(fill_out, "done.json"), encoding="utf-8"))
        assert done["mode"] == "bf_only"
        ed = os.path.join(case_dir, "01_extract")
        before = self._frames(ed)
        after = sorted(set(before) | set(frames))
        json.dump({"frames": after}, open(os.path.join(ed, "bforce_fake.json"), "w"))
        r = {"frames_before": before, "frames_after": after, "added": [f for f in frames if f not in before],
             "dup": [], "kinds": {k: v["type"] for k, v in done["bforce"]["kinds"].items()}, "rows": {},
             "backup": None, "warnings": []}
        self.merges.append({"tag": tag, "names": names, "frames": list(frames), "out": fill_out})
        return r

    def record(self, extract_dir, attempt):
        p = os.path.join(extract_dir, "bforce_ondemand.json")
        d = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {"schema": "esl/bforce_ondemand/1",
                                                                              "attempts": []}
        d["attempts"].append(attempt)
        json.dump(d, open(p, "w", encoding="utf-8"))

    def no_types_before(self, extract_dir, names):
        p = os.path.join(extract_dir, "bforce_ondemand.json")
        if not os.path.isfile(p):
            return None
        for a in reversed(json.load(open(p, encoding="utf-8"))["attempts"]):
            if a["status"] == "ok" and a["names"] == names and all(v is None for v in (a["kinds"] or {}).values()):
                return a
            if a["status"] == "ok":
                return None
        return None


@pytest.fixture()
def fcore(monkeypatch, engine):
    from esl_worker import core_adapter

    fc = FakeCore()
    fc.engine = engine
    monkeypatch.setattr(core_adapter, "bforce_has_frame", fc.has_frame)
    monkeypatch.setattr(core_adapter, "bforce_merge", fc.merge)
    monkeypatch.setattr(core_adapter, "bforce_record", fc.record)
    monkeypatch.setattr(core_adapter, "bforce_no_types_before", fc.no_types_before)
    return fc


def _h3d_case(client, synth, folder="case01"):
    h3d = write_h3d(Path(synth["rad"]).parent / f"{folder}_drop.h3d")
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": folder, "title": "h3d", "rad_path": synth["rad"],
                                          "h3d_path": str(h3d)}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, jid):
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def _ready(client, worker, synth, monkeypatch, folder="case01") -> dict:
    """h3d Case 추출(가짜 hw, bforce 없음) + 지지점 → ESL 직전."""
    monkeypatch.setenv("FAKE_HW_SRC", synth["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    case = _h3d_case(client, synth, folder)
    assert worker.run_once("SLOT") is None or True
    j = _job(client, case["id"], "CASE_EXTRACT")
    assert worker.run_once("SLOT") == "SUCCEEDED", _get(client, j["id"])
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]},
                       headers=W).status_code == 201
    return case


def _esl(client, worker, case) -> dict:
    j = _job(client, case["id"], "ESL_SOLVE")
    worker.run_once("SLOT")
    return _get(client, j["id"])


def _outputs(engine, j, step_no=1) -> dict:
    from sqlalchemy import text

    with engine.connect() as c:
        return c.execute(text("SELECT outputs FROM job_steps WHERE job_id = :j AND step_no = :n"),
                         {"j": j["id"], "n": step_no}).scalar_one() or {}


def _log(client, j, step=1):
    return client.get(f"{API}/jobs/{j['id']}/log", params={"step": step}, headers=R).json()["lines"]


def _argvs(esl_root, folder="case01"):
    return sorted((Path(esl_root) / "_h3d" / folder / "bf_ondemand").glob("argv_*.json"))


def _attempts(esl_root, folder="case01"):
    p = Path(esl_root) / folder / "01_extract" / "bforce_ondemand.json"
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


# ---------------------------------------------------------------- V-0242-BFD-7 E2E
def test_fill_e2e_and_reuse(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src, engine):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED", (j["failure_code"], j["failure_message"], _log(client, j))
    t = synth_case.T_STAR_FRAME
    # 가짜 hw 1회: argv -output …/bf_ondemand/raw, request bf_only 1·bf_frames t*
    av = _argvs(esl_root)
    assert len(av) == 1
    rec = json.loads(av[0].read_text())["argv"]
    out = rec[rec.index("-output") + 1]
    assert out == str(Path(esl_root) / "_h3d" / "case01" / "bf_ondemand" / "raw")
    assert rec[rec.index("-hot_k") + 1] == "1" and rec[rec.index("-top_n") + 1] == "1"
    req = (Path(esl_root) / "_h3d" / "case01" / "bf_ondemand" / "request.txt").read_text()
    assert "bf_only\t1\n" in req and f"bf_frames\t{t}\n" in req and "bf_on\t1\n" in req
    assert "bf_names_cont\tContact Forces|Contact Force|CONT" in req and "bf_vec_comps\tX Y Z" in req
    assert "scalar_comps\t" in req
    # 요청 프레임 행만(가짜 hw) + 병합 호출(tag = ESL 작업 id)
    assert "0,1," not in (Path(out) / "bf_cont.csv").read_text() and f"{t},1,1.5" in (Path(out) / "bf_cont.csv").read_text()
    assert fcore.merges[0]["tag"] == j["id"] and fcore.merges[0]["frames"] == [t]
    assert fcore.merges[0]["names"]["vec_comps"] == ["X", "Y", "Z"]
    # step outputs·result·시도 기록·산출물
    s1 = j["steps"][0]
    o1 = _outputs(engine, j)
    assert o1["bf_ondemand"]["status"] == "ok" and o1["bf_ondemand"]["frame"] == t and o1["core_stage"] == "esl"
    assert o1["bf_ondemand"]["kinds"] == {"cont": "Contact Forces"} and o1["bf_ondemand"]["added"] == [t]
    assert "hw_acquired" not in o1 or o1["hw_acquired"] is False
    assert j["result"]["bf_ondemand"]["status"] == "ok"
    at = _attempts(esl_root)
    assert len(at) == 1 and at[0]["status"] == "ok" and at[0]["job_id"] == j["id"] and at[0]["code"] is None
    assert at[0]["out_dir"] == "_h3d/case01/bf_ondemand/raw"
    arts = client.get(f"{API}/cases/{case['id']}/artifacts", headers=R).json()
    arts = arts if isinstance(arts, list) else arts.get("items", [])
    by = {a.get("rel_path") or a.get("path"): a for a in arts}
    # (실제 bforce.npz·json 등록은 병합 뒤 통합 시험 — 가짜 병합은 기록 파일만 만든다. 등록 목록은 존재하는 파일만)
    rel = str(Path(esl_root) / "case01" / "01_extract" / "bforce_ondemand.json")
    assert rel in by, sorted(by)
    assert by[rel]["job_id"] == j["id"]
    log = _log(client, j)
    assert any("경계력 원자료 보충 시작: 프레임" in ln for ln in log) and any("보충 완료" in ln for ln in log)
    assert any(ln.startswith("[esl-worker] argv:") for ln in log) and any("hw pid" in ln and "시간 한도 1800 s" in ln for ln in log)
    assert s1["progress_pct"] == 100.0       # 끝난 뒤 값(보충 중에는 0 유지 — 코어 진행률과 섞이지 않음)
    # V-0242-BFD-8: 같은 프레임 두 번째 ESL = 가짜 hw 호출 0 · 로그 "있음"
    j2 = _esl(client, w, case)
    assert j2["state"] == "SUCCEEDED" and len(_argvs(esl_root)) == 1
    assert any("있음 — 보충 안 함" in ln for ln in _log(client, j2))
    assert "bf_ondemand" not in _outputs(engine, j2) and "bf_ondemand" not in (j2["result"] or {})


# ---------------------------------------------------------------- V-0242-BFD-8 생략
@pytest.mark.parametrize("over", [{"enabled": False}, {"on_demand": False}])
def test_disabled_no_call(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src, over):
    from esl_worker import core_adapter

    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    real = core_adapter.bforce_settings
    monkeypatch.setattr(core_adapter, "bforce_settings", lambda s=None: {**real(s), **over})
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED" and _argvs(esl_root) == [] and fcore.has_calls == 0
    assert _attempts(esl_root) == []
    assert not any("보충" in ln for ln in _log(client, j))


def test_results_case_no_call(client, synth_inputs, worker_factory, esl_root, fcore):
    w = worker_factory()
    cid = create_case(client, synth_inputs).json()["id"]
    _job(client, cid, "CASE_EXTRACT")
    assert w.run_once("SLOT") == "SUCCEEDED"
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)
    j = _job(client, cid, "ESL_SOLVE")
    assert w.run_once("SLOT") == "SUCCEEDED"
    assert fcore.has_calls == 0 and _argvs(esl_root) == []
    assert "bf_ondemand" not in (_get(client, j["id"])["result"] or {})


def test_hw_unavailable_skipped(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src, tmp_path):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    object.__setattr__(w.settings.altair, "hw_exe_path", str(tmp_path / "nohw"))
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED"
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "skipped" and b["cause"] == "HW_UNAVAILABLE" and "altair.hw_exe_path" in b["detail"]
    at = _attempts(esl_root)
    assert at[0]["code"] == "BF_EXTRACT_SKIPPED" and at[0]["cause"] == "HW_UNAVAILABLE"
    assert any("보충 생략(HW_UNAVAILABLE)" in ln for ln in _log(client, j)) and _argvs(esl_root) == []


def test_h3d_unreadable_skipped(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    from esl_worker import core_adapter  # noqa: F401  (입력 지문 확인을 피하려고 판정만 호출)
    from esl_worker import bf_ondemand

    f = bf_ondemand.Facts(enabled=True, on_demand=True, input_kind="H3D", has_frame=False, h3d_ok=False, hw_ok=True)
    d = bf_ondemand.decide(f)
    assert (d.action, d.cause) == ("skip", "H3D_UNREADABLE")


def test_wait_skipped_when_semaphore_busy(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    object.__setattr__(w.settings.altair, "bf_on_demand_wait_s", 1)
    monkeypatch.setattr(jobs_repo, "acquire_hw", lambda *a, **k: False)      # 다른 작업이 한도를 모두 잡음
    t0 = time.time()
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED" and time.time() - t0 < 60
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "skipped" and b["cause"] == "WAIT" and "동시 실행 한도 1개가 1 s" in b["detail"]
    assert _argvs(esl_root) == [] and _attempts(esl_root)[0]["code"] == "BF_EXTRACT_SKIPPED"
    assert any("hw 동시 실행 한도 1개(altair.max_concurrent_hw) — 최대 1 s" in ln for ln in _log(client, j))


def test_no_types_before_skips_second_time(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    """종류 없음 확인된 h3d(같은 이름 후보)는 다음 ESL 때 생략(NO_TYPES)."""
    (bf_src / "bf_cont.csv").unlink()           # 가짜 hw: 종류 없음 → ok true·kinds 비어 있음
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    # 가짜 병합은 frames 에 넣으므로 has_frame 이 참이 되지 않게 프레임 기록을 지운다(실제 코어는 종류 0 프레임도 "있음")
    orig = fcore.merge

    def merge_no_frames(*a, **k):
        r = orig(*a, **k)
        os.remove(os.path.join(a[0], "01_extract", "bforce_fake.json"))
        return r

    monkeypatch.setattr(fcore, "merge", merge_no_frames)
    from esl_worker import core_adapter

    monkeypatch.setattr(core_adapter, "bforce_merge", merge_no_frames)
    j1 = _esl(client, w, case)
    assert j1["result"]["bf_ondemand"]["status"] == "ok" and j1["result"]["bf_ondemand"]["kinds"] == {}
    j2 = _esl(client, w, case)
    b = j2["result"]["bf_ondemand"]
    assert b["status"] == "skipped" and b["cause"] == "NO_TYPES" and len(_argvs(esl_root)) == 1


# ---------------------------------------------------------------- V-0242-BFD-9 실패
@pytest.mark.parametrize("mode,cause,txt", [("fail", "HW_FAILED", "HyperView 추출 실패"),
                                            ("nodone", "HW_FAILED", "done.json 없음"),
                                            ("license", "LICENSE", "라이선스 확인 실패 의심")])
def test_hw_failures_esl_continues(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src,
                                   mode, cause, txt):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    monkeypatch.setenv("FAKE_HW_MODE", mode)
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED", j
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "failed" and b["cause"] == cause and txt in b["detail"], b
    at = _attempts(esl_root)
    assert at[-1]["code"] == "BF_EXTRACT_FAILED" and at[-1]["cause"] == cause and fcore.merges == []
    log = _log(client, j)
    assert any(f"보충 실패({cause})" in ln for ln in log)
    # 실패한 보충은 다음 ESL 때 다시 시도(프레임 없음 → 판정 9)
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    j2 = _esl(client, w, case)
    assert j2["result"]["bf_ondemand"]["status"] == "ok" and len(_argvs(esl_root)) == 2


def test_not_bf_only_output_is_failure(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    monkeypatch.setenv("FAKE_HW_BF_NOFRAMES", "1")      # done.json bforce.frames 가 요청 프레임을 포함하지 않음
    j = _esl(client, w, case)
    b = j["result"]["bf_ondemand"]
    assert j["state"] == "SUCCEEDED" and b["cause"] == "HW_FAILED" and "bforce.frames" in b["detail"]


def test_hang_timeout_kills_tree(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src, tmp_path):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    pids = tmp_path / "hw.pids"
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(pids))
    object.__setattr__(w.settings.altair, "bf_on_demand_timeout_s", 2)
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED"
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "failed" and b["cause"] == "TIMEOUT" and "시간 초과 2 s" in b["detail"]
    hw_pid, child = map(int, pids.read_text().split())
    wait_for(lambda: not alive(hw_pid) and not alive(child), timeout=10)
    assert _attempts(esl_root)[0]["code"] == "BF_EXTRACT_FAILED"


def test_merge_errors(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    from esl_worker import core_adapter

    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    fcore.merge_error = core_adapter.CoreError("BF_FILL_MISMATCH", "h3d 프레임 61 ≠ 추출 60")
    j = _esl(client, w, case)
    b = j["result"]["bf_ondemand"]
    assert j["state"] == "SUCCEEDED" and b["cause"] == "MISMATCH" and "추출 60" in b["detail"] and "① 추출부터 다시" in b["detail"]
    fcore.merge_error = core_adapter.CoreError("BF_FILL_OUTPUT", "x")
    b = _esl(client, w, case)["result"]["bf_ondemand"]
    assert b["cause"] == "MERGE" and "병합 실패" in b["detail"]


def test_cancel_during_fill(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src, tmp_path,
                            engine):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
    pids = tmp_path / "hw.pids"
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(pids))
    j = _job(client, case["id"], "ESL_SOLVE")
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("state", w.run_once("SLOT")))
    t.start()
    wait_for(lambda: pids.is_file() and len(pids.read_text().split()) == 2)
    hw_pid, child = map(int, pids.read_text().split())
    assert _outputs(engine, j).get("bf_ondemand", {}).get("state") == "running"
    assert client.post(f"{API}/jobs/{j['id']}/cancel", headers=W).status_code == 200
    t.join(30)
    assert not t.is_alive() and out["state"] == "CANCELED"
    wait_for(lambda: not alive(hw_pid) and not alive(child), timeout=10)
    assert _get(client, j["id"])["state"] == "CANCELED" and _attempts(esl_root) == [] and fcore.merges == []


def test_semaphore_held_only_during_fill(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src,
                                         engine):
    from esl_platform.core.repositories import jobs as jobs_repo

    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)
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
        assert w.run_once("SLOT") == "SUCCEEDED"
    finally:
        stop.set()
        th.join()
    assert 1 in seen and seen[-1] == 0, seen[-5:]          # 보충 중 1 → 끝나면 0(코어 풀이·등록 동안 비어 있음)
    assert fcore.hw_in_use_at_merge == [0]
    assert _outputs(engine, j).get("hw_acquired") in (False, None)
    # 코어 단계 동안 다른 H3D_EXTRACT 가 hw 를 잡을 수 있음 = hw_in_use 0 (위)


def test_record_failure_warning(client, synth_inputs, worker_factory, esl_root, monkeypatch, fcore, bf_src):
    w = worker_factory()
    case = _ready(client, w, synth_inputs, monkeypatch)

    def bad(*a, **k):
        raise OSError("disk full")

    from esl_worker import core_adapter

    monkeypatch.setattr(core_adapter, "bforce_record", bad)
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED" and any(x.startswith("BF_ONDEMAND_RECORD_FAILED") for x in j["warnings"])


# ---------------------------------------------------------------- V-0242-BFD-10 CoreError 경고
def test_bforce_request_core_error_warns(client, synth_inputs, worker_factory, esl_root, monkeypatch):
    from esl_worker import core_adapter

    def boom(s=None):
        raise core_adapter.CoreError("CONFIG_INVALID", "bforce 설정 오류")

    monkeypatch.setattr(core_adapter, "bforce_settings", boom)
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    w = worker_factory()
    case = _h3d_case(client, synth_inputs)
    j = _job(client, case["id"], "CASE_EXTRACT")
    assert w.run_once("SLOT") == "SUCCEEDED"
    jj = _get(client, j["id"])
    ws = [x for x in jj["warnings"] if x.startswith("BF_REQUEST_DEFAULTED")]
    assert len(ws) == 1 and "CONFIG_INVALID" in ws[0]
    assert any(ln.startswith("[esl-worker] 경고: BF_REQUEST_DEFAULTED") for ln in _log(client, jj))
    req = (Path(esl_root) / "_h3d" / "case01" / "request.txt").read_text()
    assert "bf_on" not in req and "bf_names" not in req


def test_bforce_request_unit():
    from esl_worker import core_adapter, h3d

    warn: list[str] = []
    out = h3d.bforce_request({}, warn)
    assert out["bf_on"] == "1" and "bf_names_cont" in out and warn == []
    assert h3d.bforce_request({"bforce": {"result_names": {"cont": []}}}) is not None
    try:
        core_adapter.bforce_settings({"bforce": {"nope": 1}})
    except core_adapter.CoreError:
        warn2: list[str] = []
        assert h3d.bforce_request({"bforce": {"nope": 1}}, warn2) == {} and warn2[0].startswith("BF_REQUEST_DEFAULTED")


# ---------------------------------------------------------------- 순수 함수
def test_decide_table_order():
    from esl_worker.bf_ondemand import Facts, decide

    base = dict(enabled=True, on_demand=True, input_kind="H3D", has_frame=False, h3d_ok=True, hw_ok=True)
    assert decide(Facts(**base)).action == "fill"
    assert decide(Facts(**{**base, "enabled": False})).row == "1"
    assert decide(Facts(**{**base, "on_demand": False})).row == "2"
    assert decide(Facts(**{**base, "input_kind": "RESULTS"})).row == "3"
    d = decide(Facts(**{**base, "has_frame": True}))
    assert d.row == "4" and d.note == "have"
    assert decide(Facts(**{**base, "no_types": {"at": "x"}})).cause == "NO_TYPES"
    assert decide(Facts(**{**base, "h3d_ok": False})).cause == "H3D_UNREADABLE"
    assert decide(Facts(**{**base, "hw_ok": False})).cause == "HW_UNAVAILABLE"
    assert decide(Facts(**{**base, "settings_error": "X"})).cause == "SETTINGS"
    # 위에서부터 첫 일치: enabled false 가 프레임 있음보다 먼저
    assert decide(Facts(**{**base, "enabled": False, "has_frame": True})).row == "1"


def test_evaluate_pure(tmp_path):
    from esl_worker import bf_ondemand as b

    out = tmp_path
    assert b.evaluate(0, str(out), [3])[:2] == (False, "HW_FAILED")
    (out / "done.json").write_text(json.dumps({"ok": True, "mode": "bf_only", "bforce": {"frames": [3, 4]}}))
    assert b.evaluate(0, str(out), [3])[0] is True
    assert b.evaluate(1, str(out), [3])[0] is False
    assert b.evaluate(0, str(out), [5])[0] is False
    (out / "done.json").write_text(json.dumps({"ok": False, "error": "x", "errorInfo": "no License"}))
    ok, cause, detail, _ = b.evaluate(1, str(out), [3])
    assert not ok and cause == "LICENSE" and len(detail) <= 300
    (out / "done.json").write_text(json.dumps({"ok": False, "error": "x"}))
    assert b.evaluate(1, str(out), [3], "FlexLM licence error")[1] == "LICENSE"


def test_cause_text_complete():
    from esl_worker import bf_ondemand as b

    assert set(b.CAUSE_TEXT) == set(b.SKIPPED_CAUSES) | set(b.FAILED_CAUSES)
