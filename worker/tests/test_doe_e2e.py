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
from esl_test_support import API, H, past_ttl_s, wait_for
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
    assert g["prep"]["n_beads"] == 2 and g["prep"]["n_params"] == 8 and g["prep"]["paicad_version"] == "0.15.4"
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


# ---------------------------------------------------------------- v0.18.1 paicad 0.15.x: check 피처 강체성 실패
def test_same_model_feature_distorted(client, engine, worker, esl_root, inputs_root, exe):
    """paicad 0.15.x shell run 의 check 단계 SHELL_FEATURE_DISTORTED(종료 11) → 안 FAILED_MORPH, result.json 에 원 코드·전용 문구.
    가짜 paicad: RULES 의 morph 실패(GEOM_QUALITY) 자리를 check 실패로 바꿈 — 나머지 안 수·스킵은 같음."""
    rules = [dict(r, code="SHELL_FEATURE_DISTORTED") if r["code"] == "GEOM_QUALITY" else r for r in RULES]
    set_control(exe, rules=rules)
    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"], title="① 피처 강체성")
    out = full_flow(client, engine, worker, esl_root, s, expect_ok=5,
                    expect_skip={"collision": 1, "fixed": 1, "geom": 1}, expect_morph=1)
    d = out["dir"]
    morph = [k for k, v in out["designs"].items() if v["status"] == "FAILED_MORPH"]
    assert len(morph) == 1 and out["designs"][morph[0]]["code"] == "FAILED_MORPH"
    res = json.loads((d / "run" / "designs" / morph[0] / "result.json").read_text(encoding="utf-8"))
    assert res["status"] == "FAILED_MORPH" and res["paicad"]["paicad_code"] == "SHELL_FEATURE_DISTORTED"
    assert "강체" in (res.get("message") or ""), res
    ck = json.loads((d / "run" / "designs" / morph[0] / "paicad" / "check" / "shell_check.json").read_text())
    assert ck["status"] == "FAIL" and ck["code"] == "SHELL_FEATURE_DISTORTED" and ck["checks"]["feature"]["status"] == "FAIL"
    ok = next(k for k, v in out["designs"].items() if v["status"] == "OK" and k != "d000")
    ck = json.loads((d / "run" / "designs" / ok / "paicad" / "check" / "shell_check.json").read_text())
    assert ck["status"] == "PASS" and ck["checks"]["feature"] == {"status": "SKIPPED"}       # 섬 없는 비드 = SKIPPED


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
    # v0.17.2 D-0.17.2-AFIXED: A Case fixed-scan(prep/a_fixed)이 있어도 ③ grid·update 는 고정 없음(A 모델 좌표 ≠ B STEP)
    assert (d / "prep" / "a_fixed" / "shell_scan.json").is_file()
    assert all("--assem-dir" not in r["argv"] for r in calls(exe, "extract"))     # ③ 조립 없음
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

    set_control(exe, version="0.15.4", ocp=None)
    w = worker_factory()
    w.heartbeat_once()
    with engine.connect() as c:
        rec = doe_repo.paicad_record(c)
    assert rec["paicad"]["ready"] is False and rec["paicad"]["reason"] == "PAICAD_OCP_MISSING"
    assert rec["gmsh"]["ready"] is _gmsh_ok()
    s = api(client, "GET", "/doe/settings").json()
    assert s["enabled"] is False and s["reason"] == "PAICAD_OCP_MISSING"
    set_control(exe, version="0.15.5")
    w.doe_status(force=True)
    w.heartbeat_once()
    with engine.connect() as c:
        rec = doe_repo.paicad_record(c)
    assert rec["paicad"]["ready"] is True and rec["paicad"]["version"] == "0.15.5"
    assert "PAICAD_VERSION_PINNED" in (rec["paicad"]["warning"] or "") and rec["paicad"]["checked_at"]


# ---------------------------------------------------------------- v0.12.3(#44) 모델 전체 사본 중 lease 유지·취소
def _slow_copy(monkeypatch, seconds: float, started: threading.Event | None = None) -> None:
    """esl.doe.assem_full.copy_model_full 앞에 seconds 동안 guard 를 부르며 잠(시험 설정 lease_ttl_s 보다 길게)."""
    import time as _t

    import esl.doe.assem_full as A

    real = A.copy_model_full

    def slow(starter, case_dir, roots, dest_dir, **kw):
        if started is not None:
            started.set()
        end = _t.monotonic() + seconds
        while _t.monotonic() < end:
            kw["guard"](os.path.join(dest_dir, "probe.tmp"))     # 협조적 중단 지점(Writer.guard 감싼 것)
            _t.sleep(0.05)
        return real(starter, case_dir, roots, dest_dir, **kw)

    monkeypatch.setattr(A, "copy_model_full", slow)


@pytest.mark.short_lease
def test_prep_slow_assem_full_keeps_lease(client, engine, worker, esl_root, inputs_root, exe, monkeypatch,
                                          loaded_config):
    s1 = make_s1(engine, esl_root, inputs_root)
    _slow_copy(monkeypatch, past_ttl_s(loaded_config))   # > worker.lease_ttl_s — v0.12.1 이면 LEASE_LOST
    s = create(client, s1["entry_ids"])
    j = run_job(client, worker, s["job"]["id"])
    assert [x["state"] for x in j["steps"]] == ["SUCCEEDED", "SKIPPED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED"]
    lg = client.get(f"{API}/jobs/{s['job']['id']}/log", params={"step": 3}, headers=R).text
    assert "모델 전체 사본 prep/assem_full 시작" in lg, lg[-2000:]
    assert "모델 전체 사본 prep/assem_full 끝(" in lg and "파일 쓰기" in lg
    assert "모델 전체 사본 prep/assem_full: 파일 " in lg
    assert study(client, s["id"])["phase"] == "READY"


@pytest.mark.short_lease
def test_prep_cancel_during_assem_full(client, engine, worker, esl_root, inputs_root, exe, monkeypatch, loaded_config):
    import time as _t

    s1 = make_s1(engine, esl_root, inputs_root)
    started = threading.Event()
    _slow_copy(monkeypatch, 60.0, started)
    s = create(client, s1["entry_ids"])
    jid = s["job"]["id"]
    res: dict[str, Any] = {}
    th = threading.Thread(target=lambda: res.update(state=worker.run_once("SLOT")))
    th.start()
    assert started.wait(60)
    end = _t.monotonic() + past_ttl_s(loaded_config, 1.2)
    while _t.monotonic() < end:                     # 설정 lease_ttl_s 넘게 — 그동안 워커 heartbeat(워커 기록)도 갱신됨
        worker.heartbeat_once()
        _t.sleep(0.3)
    assert get_job(client, jid)["state"] == "RUNNING"           # lease 갱신 중
    assert client.get(f"{API}/status", headers=R).json()["worker"]["online"] is True
    r = client.post(f"{API}/jobs/{jid}/cancel", headers=W)
    assert r.status_code in (200, 202), r.text
    th.join(30)
    assert not th.is_alive() and res.get("state") == "CANCELED"
    assert get_job(client, jid)["state"] == "CANCELED"
    lg = client.get(f"{API}/jobs/{jid}/log", params={"step": 3}, headers=R).text
    assert "모델 전체 사본 prep/assem_full 취소로 중단" in lg, lg[-2000:]


# ---------------------------------------------------------------- 이슈 #53 WinError 32: prep/assem_full 교체 잠금
def _lock_assem(monkeypatch, n_fail: int) -> dict:
    """prep/assem_full/ 안 대상 파일로의 os.replace 를 처음 n_fail 회 Windows 공유 위반(WinError 32)으로."""
    import esl.fsutil as F

    real = os.replace
    st = {"fail": 0}
    mark = os.sep + "assem_full" + os.sep

    def rep(src, dst):
        if mark in str(dst) and st["fail"] < n_fail:
            st["fail"] += 1
            e = PermissionError(13, "다른 프로세스가 파일을 사용 중")
            e.winerror = 32
            raise e
        real(src, dst)
    monkeypatch.setattr(os, "replace", rep)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    return st


def test_prep_assem_full_lock_retry_then_file_locked(client, engine, worker, esl_root, inputs_root, exe, monkeypatch):
    import esl.fsutil as F

    s1 = make_s1(engine, esl_root, inputs_root)
    st = _lock_assem(monkeypatch, 3)                  # 잠깐 잠김 → 재시도로 성공
    s = create(client, s1["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    assert st["fail"] == 3 and study(client, s["id"])["phase"] == "READY"
    F.configure({"attempts": 2})                      # 끝내 잠김 → BD_GEOM FAILED FILE_LOCKED(파일 이름만)
    try:
        _lock_assem(monkeypatch, 10 ** 6)
        s2 = create(client, s1["entry_ids"])
        j = run_job(client, worker, s2["job"]["id"], "FAILED")
    finally:
        F.configure(None)
    assert j["failure_code"] == "FILE_LOCKED", j["failure_message"]
    assert "백신" in j["failure_message"] and str(esl_root) not in j["failure_message"]   # 파일 이름만(서버 절대 경로 없음)
    assert os.sep + "assem_full" + os.sep not in j["failure_message"]
    assert [x["failure_code"] for x in j["steps"] if x["state"] == "FAILED"] == ["FILE_LOCKED"]


def test_worker_side_file_locked_not_internal_error(client, engine, worker, esl_root, inputs_root, exe, monkeypatch):
    import esl.fsutil as F
    from esl_worker import doe_jobs

    def boom(ex, st, log_path):
        raise F.FileLocked(os.path.join(ex.cdir, ".x.tmp"), os.path.join(ex.cdir, "x.json"), 8, 10.0)
    monkeypatch.setattr(doe_jobs, "run_step", boom)
    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"])
    j = run_job(client, worker, s["job"]["id"], "FAILED")
    assert j["failure_code"] == "FILE_LOCKED" and "x.json ← .x.tmp" in j["failure_message"]
    assert str(esl_root) not in j["failure_message"] and os.sep + "x.json" not in j["failure_message"]


# ---------------------------------------------------------------- v0.17.2 grid 셀 대부분 실패(이슈 #63)
ALL_FAIL = [{"when": {"CHASSIS_REAR_BEAD_D_1": [0.0, 100.0]}, "code": "GEOM_CAD_FAILED"}]


def _db_phase(engine, sid) -> str:
    from esl_platform.core.repositories import doe as doe_repo
    with engine.connect() as c:
        return doe_repo.get_study(c, sid)["phase"]


def test_grid_all_cells_failed_is_step_failure(client, engine, worker, esl_root, inputs_root, exe):
    """paicad grid RESULT OK·종료 0 + 셀 전부 GEOM_CAD_FAILED → BD_GRID 실패 GRID_ALL_FAILED, PREVIEW_READY 아님."""
    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    set_control(exe, rules=ALL_FAIL)
    s = preview(client, study(client, s["id"]))
    j = run_job(client, worker, s["job"]["id"], "FAILED")
    assert j["failure_code"] == "GRID_ALL_FAILED", j["failure_message"]
    assert "9개 중 실행 가능 0개" in j["failure_message"] and "GEOM_CAD_FAILED 9" in j["failure_message"]
    assert {x["step_key"]: x["state"] for x in j["steps"]}["BD_PREVIEW_REGISTER"] != "SUCCEEDED"
    gr = calls(exe, "grid")
    assert gr and gr[-1]["argv"][gr[-1]["argv"].index("--fixed-dir") + 1] == str(sdir(esl_root, s["id"]) / "prep" / "fixed")
    assert _db_phase(engine, s["id"]) != "PREVIEW_READY"


def test_register_refuses_zero_ok_preview(client, engine, worker, esl_root, inputs_root, exe, monkeypatch):
    """이중 안전: 워커 grid 판정을 건너뛰어도(이전 워커 흉내) READY 0 은 BD_PREVIEW_REGISTER 가 GRID_ALL_FAILED."""
    from esl_worker import doe_jobs

    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    set_control(exe, rules=ALL_FAIL)
    monkeypatch.setattr(doe_jobs, "check_grid_health", lambda *a, **k: {"verdict": "ok"})
    s = preview(client, study(client, s["id"]))
    j = run_job(client, worker, s["job"]["id"], "FAILED")
    assert j["failure_code"] == "GRID_ALL_FAILED", j["failure_message"]
    st = {x["step_key"]: x["state"] for x in j["steps"]}
    assert st["BD_GRID"] == "SUCCEEDED" and st["BD_PREVIEW_REGISTER"] == "FAILED"
    assert _db_phase(engine, s["id"]) != "PREVIEW_READY"


def test_grid_partial_failure_ready_with_warning(client, engine, worker, esl_root, inputs_root, exe):
    """형상 실패 3/9(판정 6/9 ≥ 0.5) → PREVIEW_READY + 작업 경고 GRID_CELLS_FAILED(코드별 수)."""
    s1 = make_s1(engine, esl_root, inputs_root)
    s = create(client, s1["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    D1 = "CHASSIS_REAR_BEAD_D_1"
    set_control(exe, rules=[{"when": {D1: [2.4, 2.6]}, "code": "GEOM_CAD_FAILED"}])
    s = preview(client, study(client, s["id"]))
    j = run_job(client, worker, s["job"]["id"])
    assert any("GRID_CELLS_FAILED" in w and "GEOM_CAD_FAILED 3" in w for w in j["warnings"]), j["warnings"]
    g = study(client, s["id"])
    assert g["phase"] == "PREVIEW_READY" and g["doe"]["preview"]["ok"] == 6
