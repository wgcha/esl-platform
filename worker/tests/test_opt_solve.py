"""V-OR-11: OS_SOLVE 가짜 솔버(tests/fake_optistruct.py) — 정상·-check 실패·라이선스 2회 후 성공·소진·종료코드 1·메모리·
미수렴·시간 초과·취소(프로세스 트리 종료), argv 검사(localproc), OptiStruct 세마포어(PG, max_concurrent_os) 대기·해제.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest
from esl_test_support import API, wait_for
from sqlalchemy import select
from test_opt_e2e import (
    W,
    calls,
    create_run,
    get_job,
    make_s1,
    opt_settings,
    os_in_use,
    run_dir,
    run_job,
    set_control,
    step_outputs,
    write_fake_tools,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 OptiStruct/hw 는 POSIX 실행 스크립트")


@pytest.fixture()
def tools(tmp_path):
    return write_fake_tools(tmp_path)


# 시험별 설정 덮어쓰기(opt_run 키 + worker·altair)
OVERRIDES = {"test_timeout_kills_tree": {"solve": {"timeout_h": 0.0008}},
             "test_os_semaphore_serializes": {"worker": {"slots": 2}, "altair": {"max_concurrent_os": 1}}}


@pytest.fixture()
def settings_dict(tmp_path, tools, request):
    kw = dict(OVERRIDES.get(request.node.name, {}))
    worker = kw.pop("worker", None)
    altair = kw.pop("altair", None)
    d = opt_settings(tmp_path, tools, **kw)
    if worker:
        d["worker"] = {**d["worker"], **worker}
    if altair:
        d["altair"] = {**d["altair"], **altair}
    return d


def _s1_run(client, engine, esl_root, inputs_root, cid="c1"):
    s1 = make_s1(engine, esl_root, inputs_root, cid=cid)
    return s1, create_run(client, s1["entry_ids"])


def _step(j, key):
    return next(s for s in j["steps"] if s["step_key"] == key)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:   # 좀비(부모가 아직 거두지 않음)는 죽은 것으로
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False


def test_check_fail_deck_invalid(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, mode="check_fail")
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    assert j["failure_code"] == "OS_DECK_INVALID" and "fake deck error" in j["failure_message"]
    assert _step(j, "OS_SOLVE")["state"] == "FAILED" and _step(j, "OPT_POST")["state"] == "SKIPPED"
    assert len(calls(tools, "optistruct")) == 1 and "-check" in calls(tools, "optistruct")[0]["argv"]
    sj = json.loads((run_dir(esl_root, run["id"]) / "solve" / "solve.json").read_text())
    assert sj["ok"] is False and sj["exit_code"] == 1
    assert os_in_use(engine) == 0 and step_outputs(engine, run["job_id"], 4)["os_acquired"] is False


def test_check_1485_detail(client, engine, worker_factory, esl_root, inputs_root, tools):
    """이슈 #35: -check 종료코드 0 + ERROR # 1485 → OS_DECK_INVALID, 상세(필드·카드·덱 줄·인용) 한 번만 + os_errors.txt."""
    set_control(tools, mode="check_1485")
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    msg = j["failure_message"]
    assert j["failure_code"] == "OS_DECK_INVALID" and msg.startswith("OptiStruct -check 실패(종료코드 0): ")
    assert ("ERROR # 1485 in the input data: Field 0 contains unrecognized/unexpected label. — DTPG,9000006 연속 줄 1, 덱 줄 446378: "
            '"+,BEAD,60.,45.,10.,YES,BC"') in msg and msg.count("1485") == 1 and len(msg) <= 480
    sd = run_dir(esl_root, run["id"]) / "solve"
    txt = (sd / "os_errors.txt").read_text()
    assert "Field 0 contains unrecognized/unexpected label." in txt and "continuation line 1 of DTPG,9000006" in txt
    sj = json.loads((sd / "solve.json").read_text())
    assert sj["exit_code"] == 0 and sj["errors"][0]["card"] == "DTPG" and sj["errors"][0]["deck_line_no"] == 446378
    rels = {f["rel"] for f in client.get(f"{API}/opt/runs/{run['id']}/files", headers=W).json()}
    assert {"solve/os_errors.txt", "solve/esl_bead.out", "deck/esl_bead.fem"} <= rels
    log = (run_dir(esl_root, run["id"]) / "logs" / run["job_id"] / "step_04_OS_SOLVE.log").read_text()
    assert "OptiStruct 오류 1건" in log and '"+,BEAD,60.,45.,10.,YES,BC"' in log


def test_generated_deck_passes_dtpg_check(client, engine, worker_factory, esl_root, inputs_root, tools):
    """가짜 -check 의 DTPG 비드 줄 공식 형식 검사를 실제 생성 덱이 통과(비드 줄 = MW ANG BF HGT NORM - - SKIP)."""
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    run_job(client, worker_factory(), run["job_id"])
    fem = (run_dir(esl_root, run["id"]) / "deck" / "esl_bead.fem").read_text()
    lines = fem.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("DTPG,"))
    assert lines[k + 1] == "+,60.,45.,YES,10.,NORM,,,BC" and ",BEAD," not in fem


def test_license_twice_then_success(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, license=2)
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"])
    oc = calls(tools, "optistruct")
    assert ["-check" in c["argv"] for c in oc] == [True, False, False, False]
    res = client.get(f"{API}/opt/runs/{run['id']}", headers=W).json()["result"]
    assert res["solve"]["license_waits"] == 2 and res["converged"] is True
    log = (run_dir(esl_root, run["id"]) / "logs" / run["job_id"] / "step_04_OS_SOLVE.log").read_text()
    assert log.count("라이선스 부족") == 2
    # 이전 시도의 .out 은 지우지 않고 이름을 바꿔 둔다
    assert sorted(p.name for p in (run_dir(esl_root, run["id"]) / "solve").glob("esl_bead.out*")) == \
        ["esl_bead.out", "esl_bead.out.check", "esl_bead.out.try1", "esl_bead.out.try2"]
    assert j["progress_pct"] == 100.0 and os_in_use(engine) == 0


def test_license_exhausted(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, license=10)
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    assert j["failure_code"] == "OS_LICENSE_UNAVAILABLE"
    assert [("-check" in c["argv"]) for c in calls(tools, "optistruct")] == [True] + [False] * 4    # 1 + 재시도 3
    sj = json.loads((run_dir(esl_root, run["id"]) / "solve" / "solve.json").read_text())
    assert sj["ok"] is False and sj["license_waits"] == 3
    assert os_in_use(engine) == 0


@pytest.mark.parametrize("mode,code", [("exit1", "OS_SOLVE_FAILED"), ("fail", "OS_SOLVE_FAILED"),
                                       ("nodes", "OS_SOLVE_FAILED"), ("memory", "SOLVER_OUT_OF_MEMORY")])
def test_solver_failures(client, engine, worker_factory, esl_root, inputs_root, tools, mode, code):
    set_control(tools, mode=mode)
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    assert j["failure_code"] == code, j["failure_message"]
    assert os_in_use(engine) == 0


def test_not_converged_is_warning(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, mode="nonconv")
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"])
    res = client.get(f"{API}/opt/runs/{run['id']}", headers=W).json()["result"]
    assert res["converged"] is False and res["iterations"] == 5 == res["desmax"]
    assert any("수렴 표식 없음" in w for w in res["warnings"])
    assert any("수렴 표식 없음" in w for w in j["warnings"])


def test_timeout_kills_tree(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, mode="hang")
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    assert j["failure_code"] == "OS_TIMEOUT"
    pids = [int(x) for x in (tools["dir"] / "fake_os_pids").read_text().split()]
    wait_for(lambda: not any(_alive(p) for p in pids), timeout=10)
    assert os_in_use(engine) == 0


def test_cancel_kills_tree_and_releases(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, mode="hang")
    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    w = worker_factory()
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("st", w.run_once("SLOT")))
    t.start()
    pid_file = tools["dir"] / "fake_os_pids"
    wait_for(pid_file.exists, timeout=60)
    assert os_in_use(engine) == 1
    pids = [int(x) for x in pid_file.read_text().split()]
    r = client.post(f"{API}/jobs/{run['job_id']}/cancel", headers=W)
    assert r.status_code in (200, 202), r.text
    t.join(60)
    assert out.get("st") == "CANCELED"
    j = get_job(client, run["job_id"])
    assert j["state"] == "CANCELED" and _step(j, "OS_SOLVE")["state"] == "CANCELED"
    wait_for(lambda: not any(_alive(p) for p in pids), timeout=10)
    assert os_in_use(engine) == 0


def test_argv_and_command_saved(client, engine, worker_factory, esl_root, inputs_root, tools):
    from esl_platform.core.db.tables import job_steps
    from esl_worker import localproc

    _s1, run = _s1_run(client, engine, esl_root, inputs_root)
    run_job(client, worker_factory(), run["job_id"])
    rd = run_dir(esl_root, run["id"])
    with engine.connect() as c:
        cmd = c.execute(select(job_steps.c.command).where(job_steps.c.job_id == run["job_id"],
                                                          job_steps.c.step_no == 4)).scalar()
    assert cmd == [str(tools["optistruct"]), str(rd / "solve" / "esl_bead.fem"), "-nt", "2", "-tmpdir",
                   str(rd / "solve" / "tmp")]
    # job_steps.command 는 전역 관리자만 응답에 보임
    st = next(s for s in client.get(f"{API}/jobs/{run['job_id']}", headers=W).json()["steps"] if s["step_no"] == 4)
    assert "command" not in st or st["command"] is None
    # argv 템플릿 규칙: argv[0] = {optistruct}, 메타문자 거부, 알 수 없는 placeholder
    vals = {"optistruct": "/opt/os/optistruct", "fem": "/w/a.fem"}
    assert localproc.build_argv(["{optistruct}", "{fem}"], vals, exe="optistruct", what="t") == ["/opt/os/optistruct",
                                                                                               "/w/a.fem"]
    for tpl, v, code in ((["{hw}", "{fem}"], vals, "CONFIG_INVALID"), (["{optistruct}", "{nope}"], vals, "CONFIG_INVALID"),
                         (["{optistruct}", "{fem}"], {**vals, "fem": "/w/a&b.fem"}, "INPUT_INVALID"),
                         (["{optistruct}", "{fem}"], {"optistruct": "/x/os.bat", "fem": "/w/a(1).fem"}, "INPUT_INVALID")):
        with pytest.raises(localproc.ProcError) as ei:
            localproc.build_argv(tpl, v, exe="optistruct", what="t")
        assert ei.value.code == code


def test_os_semaphore_serializes(client, engine, worker_factory, esl_root, inputs_root, tools):
    set_control(tools, iter_delay=0.4)
    _a, ra = _s1_run(client, engine, esl_root, inputs_root, cid="ca")
    _b, rb = _s1_run(client, engine, esl_root, inputs_root, cid="cb")
    w = worker_factory()
    res = {}
    ths = [threading.Thread(target=lambda k=k: res.setdefault(k, w.run_once("SLOT"))) for k in ("x", "y")]
    for t in ths:
        t.start()
        time.sleep(0.2)
    for t in ths:
        t.join(180)
    assert sorted(res.values()) == ["SUCCEEDED", "SUCCEEDED"], res
    rows = [json.loads(ln) for ln in (tools["dir"] / "fake_os_calls.jsonl").read_text().splitlines()]
    span = {}
    for r in rows:
        if r["role"].startswith("optistruct"):
            k = r["cwd"]
            lo, hi = span.get(k, (r["t"], r["t"]))
            span[k] = (min(lo, r["t"]), max(hi, r["t"]))
    assert len(span) == 2
    (_a0, a1), (b0, _b1) = sorted(span.values())
    assert a1 <= b0, span                                     # OptiStruct 구간(-check ~ 본 실행 끝)이 겹치지 않음
    logs = [(run_dir(esl_root, r["id"]) / "logs" / r["job_id"] / "step_04_OS_SOLVE.log").read_text() for r in (ra, rb)]
    assert any("동시 실행 한도 1개" in t for t in logs)
    assert os_in_use(engine) == 0


def test_solve_env_whitelist_only(monkeypatch):
    """통합(Verifier, 계약 §8.1): env_passthrough 가 비어도 환경 전체를 넘기지 않음 — 기본 OS 키 + solve.env 만."""
    from types import SimpleNamespace

    from esl_worker.os_solve import solve_env

    monkeypatch.setenv("ESL_SECRET_TOKEN", "x")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("MY_KEY", "1")
    s = SimpleNamespace(worker=SimpleNamespace(env_passthrough=[]),
                        opt_run=SimpleNamespace(solve=SimpleNamespace(env={"ALTAIR_LICENSE_PATH": "6200@lic"})))
    env = solve_env(s)
    assert "ESL_SECRET_TOKEN" not in env and "MY_KEY" not in env
    assert env["PATH"] == "/usr/bin" and env["ALTAIR_LICENSE_PATH"] == "6200@lic"
    s.worker.env_passthrough = ["MY_KEY"]
    assert solve_env(s)["MY_KEY"] == "1"
