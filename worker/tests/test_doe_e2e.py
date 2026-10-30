"""v0.9.0 비드 DOE 워커 E2E(계약 esl_bead_doe.md §4·§6·§9, V-BD-11·14·15) — 실제 PG·워커·코어·자체 솔버, 가짜 paicad
(tests/fake_paicad.py), ③ 은 실제 gmsh(없으면 skip).

- ① 같은 모델: DOE_PREP(fixed-scan·extract 1차·body_map·extract·tag) → DOE_PREVIEW(grid, 공칭 셀 → d000 썸네일,
  충돌·고정·형상 스킵 표시) → DOE_RUN(병렬 ≤ 2, morph 실패 안 FAILED_MORPH, 순위·민감도·view3d·산출물·보고서,
  상위 3 + 베이스라인 외 out_files 정리) → bead_does phase·요약, 입력 폴더 불변(V-BD-14), paicad 출력 경로가 _doe 안.
- ② 다른 모델 + B 메시: 조립 = input/mesh 사본, A Case fixed-scan(prep/a_fixed) → 경계 경고.
- ③ STEP 만: --fixed-dir "" grid, shell update → gmsh, 잡음 바닥 design noise.
- 취소: 실행 중 paicad·코어 자식 트리 종료, 끝난 안 유지 → 재시도 이어하기(done.json 같은 안은 paicad 재실행 없음).
- 준비 실패(비드 없음 → NO_BEADS, paicad 낮은 버전 → PAICAD_VERSION_LOW) 시 phase 불변, Case 폴더 링크 거부.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from doe_support import api, rad_mesh_bytes, upload_step
from doe_worker_support import (
    RULES,
    SPEC,
    calls,
    doe_worker_settings,
    max_overlap,
    pid_alive,
    plate_step,
    set_control,
    started_pids,
    write_fake_paicad,
)
from esl_test_support import API, H, wait_for
from opt_support import plate, tree, upload_files
from sqlalchemy import select
from test_opt_e2e import make_s1

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")
W = H("tok-power", True)
R = H("tok-power")


def _gmsh_ok() -> bool:
    try:
        import gmsh  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@pytest.fixture()
def exe(tmp_path):
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, exe):
    return doe_worker_settings(tmp_path, exe)


@pytest.fixture()
def worker(worker_factory, exe):
    set_control(exe, rules=RULES)
    w = worker_factory()
    w.heartbeat_once()                     # info.paicad·gmsh → /doe/settings 활성
    return w


def get_job(client, jid) -> dict[str, Any]:
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def run_job(client, worker, jid, expect="SUCCEEDED") -> dict[str, Any]:
    st = worker.run_once("SLOT")
    j = get_job(client, jid)
    assert st == expect and j["state"] == expect, (st, j["state"], j.get("failure_code"), j.get("failure_message"),
                                                   [(s["step_key"], s["state"], s.get("failure_code")) for s in j["steps"]])
    return j


def study(client, sid) -> dict[str, Any]:
    r = api(client, "GET", f"/doe/studies/{sid}")
    assert r.status_code == 200, r.text
    return r.json()


def sdir(esl_root: Path, sid: str) -> Path:
    return esl_root / "_doe" / sid


def create(client, entry_ids, scenario="same", **kw) -> dict[str, Any]:
    uid = kw.pop("step_uid", None) or upload_step(client)
    body = {"project_id": "p-1", "scenario": scenario, "entry_ids": entry_ids, "step_upload_id": uid, **kw}
    r = api(client, "POST", "/doe/studies", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def preview(client, s) -> dict[str, Any]:
    r = api(client, "POST", f"/doe/studies/{s['id']}/preview", json={"version": s["version"], "spec": SPEC})
    assert r.status_code == 202, r.text
    return r.json()


def start_run(client, s) -> dict[str, Any]:
    r = api(client, "POST", f"/doe/studies/{s['id']}/run",
            json={"version": s["version"], "matrix_sha256": s["doe"]["matrix_sha256"]})
    assert r.status_code == 202, r.text
    return r.json()


def outside_paths(rows: list[dict[str, Any]], root: Path) -> list[str]:
    """paicad 출력 인자(--out-dir 류)가 연구 폴더 밖이면 그 값."""
    bad = []
    for r in rows:
        a = r["argv"]
        for i, t in enumerate(a[:-1]):
            if t in ("--out-dir", "--update-dir", "--morph-dir", "--check-dir", "--out-files-dir"):
                if not os.path.realpath(a[i + 1]).startswith(os.path.realpath(root) + os.sep):
                    bad.append(a[i + 1])
    return bad


def full_flow(client, engine, worker, esl_root, s, *, expect_ok: int, expect_skip: dict, expect_morph: int):
    sid = s["id"]
    d = sdir(esl_root, sid)
    prep_jid = s["job"]["id"]
    j = run_job(client, worker, prep_jid)
    assert [x["step_key"] for x in j["steps"]] == ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"]
    # 작업 로그(paicad argv): 일반 사용자 응답에는 서버 절대경로 없음(‹ESL_ROOT›·‹…›/파일명), 전역 관리자는 원문(§15, 검증 지적)
    lg = client.get(f"{API}/jobs/{prep_jid}/log", params={"step": 3}, headers=R)
    assert lg.status_code == 200 and "argv:" in lg.text, lg.text[-1500:]
    flat = lg.text.replace("\\\\", "/").replace("\\", "/")
    assert str(esl_root) not in flat and os.path.dirname(str(esl_root)) not in flat, lg.text[-1500:]
    assert "‹ESL_ROOT›/_doe/" in lg.text and "‹…›/paicad" in lg.text
    la = client.get(f"{API}/jobs/{prep_jid}/log", params={"step": 3}, headers=H("tok-admin"))
    assert str(esl_root) in la.text.replace("\\\\", "/").replace("\\", "/")
    assert j["progress_pct"] == 100.0
    g = study(client, sid)
    assert g["phase"] == "READY", g
    assert g["prep"]["n_beads"] == 2 and g["prep"]["n_params"] == 8 and g["prep"]["paicad_version"] == "0.14.0"
    assert any(w["code"] == "BEAD_NEAR_FIXED" for w in g["prep"]["warnings"])
    assert api(client, "GET", f"/doe/studies/{sid}/params").status_code == 200
    for rel in ("prep/extract/shell_features.json", "prep/paicad.json", "prep/params.json", "prep/plan.json"):
        assert (d / rel).is_file(), rel
    # 미리보기
    s = preview(client, g)
    j = run_job(client, worker, s["job"]["id"])
    assert [x["step_key"] for x in j["steps"]] == ["BD_MATRIX", "BD_GRID", "BD_PREVIEW_REGISTER"]
    g = study(client, sid)
    pv = g["doe"]["preview"]
    assert g["phase"] == "PREVIEW_READY" and pv["matrix_sha256"] == g["doe"]["matrix_sha256"]
    assert pv["skipped"] == expect_skip and pv["ok"] == 9 - sum(expect_skip.values()), pv
    st = {c["id"]: c["status"] for c in pv["cells"]}
    assert len(st) == 9 and "nominal" not in st
    th = api(client, "GET", f"/doe/studies/{sid}/preview/thumb/d000")          # 공칭 셀 → d000 썸네일
    assert th.status_code == 200 and th.content[:8] == b"\x89PNG\r\n\x1a\n"
    ok_id = next(k for k, v in st.items() if v == "READY")
    assert api(client, "GET", f"/doe/studies/{sid}/preview/thumb/{ok_id}").status_code == 200
    # 실행
    s = start_run(client, g)
    jid = s["job"]["id"]
    j = run_job(client, worker, jid)
    assert [x["step_key"] for x in j["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    assert j["progress_pct"] == 100.0 and all(x["progress_pct"] == 100.0 for x in j["steps"])
    g = study(client, sid)
    assert g["phase"] == "DONE" and g["result_ready"] is True
    res = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert res["n_ok"] == expect_ok, res
    assert res["n_skipped"] == expect_skip
    assert res["n_failed"]["morph"] == expect_morph
    assert res["ranking"][0]["rank"] == 1 and res["best"]["id"] == res["ranking"][0]["id"]
    designs = json.loads((d / "post" / "designs.json").read_text())["designs"]
    by = {x["id"]: x for x in designs}
    for k, v in st.items():
        if v.startswith("SKIPPED"):
            assert by[k]["status"] == v                              # 미리보기 스킵 = 실행 안 함, 상태 표시
            assert not (d / "run" / "designs" / k / "paicad").exists() and not (d / "run" / "designs" / k / "update").exists()
    rep = api(client, "GET", f"/doe/studies/{sid}/report")
    assert rep.status_code == 200 and "방법·출처" in rep.text
    log = client.get(f"{API}/jobs/{jid}/log", params={"step": 2}, headers=R)
    assert log.status_code == 200 and "BD_DESIGNS 완료" in log.text, log.text[-2000:]
    return {"designs": by, "result": res, "jid": jid, "dir": d, "cells": st}


# ---------------------------------------------------------------- ① 같은 모델
def test_same_model_e2e(client, engine, worker, esl_root, inputs_root, exe, settings_dict):
    s1 = make_s1(engine, esl_root, inputs_root)
    before_inputs, before_lib = tree(inputs_root), tree(esl_root / "_library")
    up_root = Path(settings_dict["storage"]["upload_root"])
    s = create(client, s1["entry_ids"], title="① 같은 모델")
    before_up = tree(up_root)
    out = full_flow(client, engine, worker, esl_root, s, expect_ok=5,
                    expect_skip={"collision": 1, "fixed": 1, "geom": 1}, expect_morph=1)
    d = out["dir"]
    # paicad 호출: ① 조립 = Case 입력 폴더 제자리, body_map, 출력은 모두 _doe/<id> 안
    fs = calls(exe, "fixed-scan")
    full = d / "prep" / "assem_full"                    # v0.12.1 모델 전체 사본(starter include 트리)
    assert len(fs) == 1 and fs[0]["argv"][fs[0]["argv"].index("--assem-dir") + 1] == str(full)
    man = json.loads((d / "prep" / "assem_full.json").read_text())
    src_rels = sorted(str(p.relative_to(inputs_root)).replace(os.sep, "/") for p in inputs_root.rglob("*")
                      if p.suffix.lower() in (".rad", ".inc"))
    assert sorted(f["rel"] for f in man["files"]) == src_rels and man["n_outside"] == 0
    for r in calls(exe, "tag") + calls(exe, "run"):
        assert r["argv"][r["argv"].index("--assem-dir") + 1] == str(full)
    for did in ("d001", "d002", "d003"):                # 모핑 대상 파일 rel = Case 폴더 기준(기존과 같음)
        of = d / "run" / "designs" / did / "paicad" / "out_files"
        if of.is_dir():
            assert {str(p.relative_to(of)).replace(os.sep, "/") for p in of.rglob("*") if p.is_file()} <= set(src_rels)
    assert fs[0]["argv"][fs[0]["argv"].index("--parts") + 1] == "7"
    ex = calls(exe, "extract")
    assert len(ex) == 2 and "--assem-dir" not in ex[0]["argv"] and "--body-map" in ex[1]["argv"]
    assert json.loads((d / "prep" / "body_map.json").read_text()) == {"schema_version": 1, "map": {"SHEET": "PART:7"}}
    gr = calls(exe, "grid")
    assert len(gr) == 1 and gr[0]["argv"][gr[0]["argv"].index("--fixed-dir") + 1] == str(d / "prep" / "fixed")
    runs = calls(exe, "run")
    assert len(runs) == 6                                           # 미리보기 OK 안만
    assert max_overlap(runs) <= 2                                   # run.parallel 2
    assert outside_paths(calls(exe), d) == []
    allowed = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "PYTHONUTF8", "PYTHONIOENCODING"}
    for r in calls(exe):
        assert set(r["env"]) <= allowed | {"LC_CTYPE"}, r["env"]       # env 최소(PYTHONPATH 등 없음)
        assert "PYTHONPATH" not in r["env"]
    # morph 실패 안·순위·정리
    morph = [k for k, v in out["designs"].items() if v["status"] == "FAILED_MORPH"]
    assert len(morph) == 1 and out["designs"][morph[0]]["code"] == "FAILED_MORPH"
    top = [x["id"] for x in out["result"]["ranking"][:3]]
    for did, v in out["designs"].items():
        of = d / "run" / "designs" / did / "paicad" / "out_files"
        if v["status"] == "OK" and did != "d000":
            assert of.is_dir() == (did in top), did                  # 상위 3 만 대형 rad 사본 유지
            assert (d / "run" / "designs" / did / "design.npz").is_file()
    best = d / "best" / out["result"]["best"]["id"]
    assert (best / "values.json").is_file() and list((best / "include").rglob("*.rad"))
    # 입력 폴더·라이브러리·업로드 불변(V-BD-14)
    assert tree(inputs_root) == before_inputs
    assert tree(esl_root / "_library") == before_lib
    assert tree(up_root) == before_up
    # 이력·알림
    from esl_platform.core.db.tables import notifications

    with engine.connect() as c:
        ev = [r.event for r in c.execute(select(notifications.c.event).where(notifications.c.job_id == out["jid"]))]
    assert "JOB_SUCCEEDED" in ev


# ---------------------------------------------------------------- ② 다른 모델 + B 메시
def test_mesh_scenario_e2e(client, engine, worker, esl_root, inputs_root, exe, tmp_path):
    s1 = make_s1(engine, esl_root, inputs_root)
    mesh_uid = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path, plate(14, 10, Lx=303.0, Lz=198.0))})
    before_inputs = tree(inputs_root)
    s = create(client, s1["entry_ids"], "mesh", mesh_upload_id=mesh_uid, title="② B 메시")
    out = full_flow(client, engine, worker, esl_root, s, expect_ok=5,
                    expect_skip={"collision": 1, "fixed": 1, "geom": 1}, expect_morph=1)
    d = out["dir"]
    fs = calls(exe, "fixed-scan")
    assem = [r["argv"][r["argv"].index("--assem-dir") + 1] for r in fs]
    assert str(d / "prep" / "a_assem_full") in assem and str(d / "input" / "mesh") in assem   # A Case 전체 사본 + B 사본
    assert (d / "prep" / "a_fixed" / "shell_scan.json").is_file() and (d / "prep" / "boundary.json").is_file()
    for r in calls(exe, "run"):
        assert r["argv"][r["argv"].index("--assem-dir") + 1] == str(d / "input" / "mesh")
    g = study(client, s["id"])
    assert g["prep"]["boundary"] is not None
    assert tree(inputs_root) == before_inputs
    assert outside_paths(calls(exe), d) == []


# ---------------------------------------------------------------- ③ STEP 만
@pytest.mark.skipif(not _gmsh_ok(), reason="gmsh 없음")
def test_step_scenario_e2e(client, engine, worker, esl_root, inputs_root, exe, tmp_path):
    set_control(exe, rules=RULES, brep="gmsh")
    s1 = make_s1(engine, esl_root, inputs_root)
    step = upload_step(client, plate_step(tmp_path / "plate.step"), name="rad/plate.step")
    s = create(client, s1["entry_ids"], "step", step_uid=step, mesh_size_mm=20, title="③ STEP 만")
    out = full_flow(client, engine, worker, esl_root, s, expect_ok=7, expect_skip={"collision": 1, "fixed": 0, "geom": 1},
                    expect_morph=0)
    d = out["dir"]
    gr = calls(exe, "grid")
    assert gr[0]["argv"][gr[0]["argv"].index("--fixed-dir") + 1] == ""          # BD-D-11
    assert calls(exe, "run") == [] and calls(exe, "tag") == []
    ups = calls(exe, "update")
    assert len(ups) == 8 and all("--fixed-dir" not in r["argv"] for r in ups)   # 안 7 + noise
    assert (d / "run" / "designs" / "noise" / "result.json").is_file()
    assert out["result"].get("noise_floor") is not None
    assert (d / "prep" / "mesh0" / "mesh.npz").is_file()


# ---------------------------------------------------------------- 취소 → 재시도 이어하기
def test_cancel_kills_tree_and_retry_resumes(client, engine, worker_factory, esl_root, inputs_root, exe):
    set_control(exe, rules=RULES)
    w = worker_factory()
    w.heartbeat_once()
    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"])
    run_job(client, w, s["job"]["id"])
    s = preview(client, study(client, s["id"]))
    run_job(client, w, s["job"]["id"])
    g = study(client, s["id"])
    from doe_worker_support import D2
    set_control(exe, rules=RULES, sleep={"run": 60}, sleep_when={D2: [4.4, 4.6]})
    s = start_run(client, g)
    jid = s["job"]["id"]
    d = sdir(esl_root, s["id"])
    res: dict[str, Any] = {}
    th = threading.Thread(target=lambda: res.update(state=w.run_once("SLOT")))
    th.start()
    n0 = len(started_pids(exe))
    wait_for(lambda: len(list((d / "run" / "designs").glob("d*/done.json"))) >= 3, timeout=120)   # 베이스라인 + 빠른 안
    wait_for(lambda: len(started_pids(exe)) > n0 and any(
        pid_alive(p) for p in started_pids(exe)), timeout=60)                                      # 잠든 paicad 실행 중
    r = client.post(f"{API}/jobs/{jid}/cancel", headers=W)
    assert r.status_code in (200, 202), r.text
    th.join(60)
    assert res.get("state") == "CANCELED"
    assert not any(pid_alive(p) for p in started_pids(exe))        # paicad 프로세스 트리 종료
    j = get_job(client, jid)
    assert j["state"] == "CANCELED"
    done_before = {p.parent.name for p in (d / "run" / "designs").glob("d*/done.json")}
    assert "d000" in done_before and len(done_before) >= 2
    runs_before = {r["argv"][r["argv"].index("--values") + 1] for r in calls(exe, "run")}
    # 재시도: 잠 없이 → BD_DESIGNS 부터, 끝난 안은 재사용(paicad 재실행 없음)
    set_control(exe, rules=RULES)
    r = client.post(f"{API}/jobs/{jid}/retry", headers=W)
    assert r.status_code in (200, 201), r.text
    j2 = run_job(client, w, r.json()["id"])
    stp = {x["step_key"]: x["state"] for x in j2["steps"]}
    assert stp["BD_DESIGNS"] == "SUCCEEDED" and stp["BD_REGISTER"] == "SUCCEEDED"
    reran = [r["argv"][r["argv"].index("--values") + 1] for r in calls(exe, "run")]
    again = [v for v in reran if Path(v).stem in done_before and Path(v).stem != "d000"]
    assert len(again) == sum(1 for v in runs_before if Path(v).stem in done_before)   # 끝난 안 재실행 없음
    log = client.get(f"{API}/jobs/{r.json()['id']}/log", params={"step": 2}, headers=R).text
    assert "이전 결과 재사용" in log
    assert study(client, s["id"])["phase"] == "DONE"


# ---------------------------------------------------------------- 준비 실패·phase 불변·링크 거부
def test_prep_failures_keep_phase(client, engine, worker, esl_root, inputs_root, exe):
    s1 = make_s1(engine, esl_root, inputs_root)
    set_control(exe, rules=RULES, fail={"extract": {"exit": 13, "code": "GEOM_EXTRACT_EMPTY"}})
    s = create(client, s1["entry_ids"])
    j = run_job(client, worker, s["job"]["id"], "FAILED")
    assert j["failure_code"] == "NO_BEADS", j["failure_message"]
    g = study(client, s["id"])
    assert g["phase"] == "FAILED" and g["prep"] is None                      # DB phase 는 PREP 그대로(파생 FAILED)
    with engine.connect() as c:
        from esl_platform.core.repositories import doe as doe_repo
        assert doe_repo.get_study(c, s["id"])["phase"] == "PREP"
    # 낮은 버전 → PAICAD_VERSION_LOW
    set_control(exe, rules=RULES, version="0.13.9")
    s = create(client, s1["entry_ids"])
    j = run_job(client, worker, s["job"]["id"], "FAILED")
    assert j["failure_code"] == "PAICAD_VERSION_LOW"
    # Case 입력 폴더 안 링크 → 거부(paicad 재귀 수집이 링크를 따라가지 않게)
    set_control(exe, rules=RULES)
    s = create(client, s1["entry_ids"])
    (inputs_root / "evil_link").symlink_to(esl_root)
    try:
        j = run_job(client, worker, s["job"]["id"], "FAILED")
        assert j["failure_code"] == "PATH_OUTSIDE_ROOT"
    finally:
        (inputs_root / "evil_link").unlink()


def test_heartbeat_records_paicad_and_gmsh(client, engine, worker_factory, exe):
    from esl_platform.core.repositories import doe as doe_repo

    set_control(exe, version="0.14.0", ocp=None)
    w = worker_factory()
    w.heartbeat_once()
    with engine.connect() as c:
        rec = doe_repo.paicad_record(c)
    assert rec["paicad"]["ready"] is False and rec["paicad"]["reason"] == "PAICAD_OCP_MISSING"
    assert rec["gmsh"]["ready"] is _gmsh_ok()
    s = api(client, "GET", "/doe/settings").json()
    assert s["enabled"] is False and s["reason"] == "PAICAD_OCP_MISSING"
    set_control(exe, version="0.14.1")
    w.doe_status(force=True)
    w.heartbeat_once()
    with engine.connect() as c:
        rec = doe_repo.paicad_record(c)
    assert rec["paicad"]["ready"] is True and rec["paicad"]["version"] == "0.14.1"
    assert "PAICAD_VERSION_PINNED" in (rec["paicad"]["warning"] or "") and rec["paicad"]["checked_at"]
