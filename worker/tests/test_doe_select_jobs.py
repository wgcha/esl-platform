"""v0.15.0 select 비드 직접 선택 워커 작업(계약 esl_bead_select.md §8, V-BS-14) — 실제 PG·워커·코어·자체 솔버, 가짜 paicad
(fixed-scan 만), 합성 비드 메시(tests/doe/synth_bead.py, h 10 mm).

- PREP: BD_MESH0 SKIPPED, BD_GEOM = 모델 전체 사본 + fixed-scan 만(extract·tag 없음) → prep/fixed/, 준비 요약 n_nodes·n_elems·fixed.
  paicad 버전 불가·fixed-scan 실패 → BD_GEOM SKIPPED + FIXED_INFO_MISSING(준비 성공).
- PREVIEW: BD_GRID = 코어 bd_select_grid(paicad grid 호출 없음), grid_manifest 가 paicad grid 형식 키(cells[id, status, code,
  thumb], nominal), 셀 상태 SELECT_FIXED_VIOLATION → SKIPPED_FIXED·SELECT_MORPH_INVERTED → FAILED_MESH, doe.preview
  selection_sha256·skipped.mesh.
- RUN: READY 안만 실행(paicad 없음), 이어하기(재시도 → 재사용, done.json input_sha256 = 선택·기저 sha 포함), 산출물 rad 사본 =
  원본과 /NODE 좌표 칸 외 바이트 동일·ID 불변, 입력 폴더·라이브러리 불변.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from doe_support import api
from doe_worker_support import calls, doe_worker_settings, set_control, write_fake_paicad
from esl_test_support import API, REPO, H
from opt_support import tree
from sqlalchemy import insert
from test_opt_e2e import PART, seed_entry, write_case_rad

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_bead as sb  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")
R = H("tok-power")
H_MM = 10.0


# ---------------------------------------------------------------- 도우미(E2E 와 공용)
@pytest.fixture()
def exe(tmp_path):
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, exe):
    return doe_worker_settings(tmp_path, exe)


@pytest.fixture()
def worker(worker_factory, exe):
    set_control(exe, rules=[])
    w = worker_factory()
    w.heartbeat_once()
    return w


def make_bead_case(engine, esl_root: Path, inputs_root: Path, kinds=(("bend", 2.0), ("twist", 1.5)),
                   cid: str = "c1") -> dict[str, Any]:
    """합성 비드 메시를 Case(rad 1개)로 등록 + 같은 메시의 ESL 항목(자기평형 하중 굽힘·뒤틀림)."""
    from esl_platform.core.db.tables import cases

    g = sb.generate(H_MM)
    mesh = g["mesh"]
    rad = inputs_root / f"{cid}_0000.rad"
    write_case_rad(rad, mesh)
    with engine.begin() as c:
        c.execute(insert(cases).values(id=cid, project_id="p-1", folder_name=f"f_{cid}", title=f"Case {cid}",
                                       rad_path=str(rad), results_dir=str(inputs_root),
                                       input_fingerprint={"includes": []}, part_title=PART,
                                       created_by="u-power", created_by_name="파워"))
    ids = [seed_entry(engine, esl_root, cid, mesh, k, a, scene=i + 1) for i, (k, a) in enumerate(kinds)]
    return {"case_id": cid, "rad": rad, "entry_ids": ids, "mesh": mesh, "g": g}


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


def create(client, entry_ids) -> dict[str, Any]:
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "select", "entry_ids": entry_ids,
                                                  "title": "select"})
    assert r.status_code == 201, r.text
    return r.json()


def save_selection(client, s, sel) -> dict[str, Any]:
    r = api(client, "PUT", f"/doe/studies/{s['id']}/selection", json={"version": s["version"], "selection": sel})
    assert r.status_code == 200, r.text
    return r.json()


def preview(client, s, spec) -> dict[str, Any]:
    r = api(client, "POST", f"/doe/studies/{s['id']}/preview", json={"version": s["version"], "spec": spec})
    assert r.status_code == 202, r.text
    return r.json()


def start_run(client, s) -> dict[str, Any]:
    r = api(client, "POST", f"/doe/studies/{s['id']}/run",
            json={"version": s["version"], "matrix_sha256": s["doe"]["matrix_sha256"]})
    assert r.status_code == 202, r.text
    return r.json()


def ring_selection(g) -> dict[str, Any]:
    """정답 바닥 + b1 블렌딩 24 mm + 비드 경계 18 mm 고리(고정 노드 집합 0)를 사용자 고정 층으로 칠함 → W 변화는 고정 침범."""
    m = g["mesh"]
    ring = set(int(x) for x in g["fixed_groups"][0])
    nid = m["node_id"]
    touch = np.array([any(c >= 0 and int(nid[c]) in ring for c in row) for row in m["conn"]])
    sel = sb.selection(g, blend_mm=24.0)
    sel["fixed_user"] = sb.elemset(m, touch)
    return sel


def node_block_diff(a: bytes, b: bytes) -> tuple[int, int]:
    """두 rad 의 줄 비교: (바뀐 /NODE 줄 수, /NODE 밖 또는 ID 칸이 바뀐 줄 수)."""
    la, lb = a.split(b"\n"), b.split(b"\n")
    assert len(la) == len(lb)
    in_node, moved, bad = False, 0, 0
    for x, y in zip(la, lb):
        if x.startswith(b"/"):
            in_node = x.strip().upper().startswith(b"/NODE")
        if x == y:
            continue
        if in_node and not x.startswith(b"#") and x[:10] == y[:10] and len(x) == len(y):
            moved += 1
        else:
            bad += 1
    return moved, bad


# ---------------------------------------------------------------- PREP
def test_select_prep_fixed_scan(client, engine, worker, esl_root, inputs_root, exe):
    w = make_bead_case(engine, esl_root, inputs_root)
    in_before = tree(inputs_root)
    s = create(client, w["entry_ids"])
    j = run_job(client, worker, s["job"]["id"])
    assert [(x["step_key"], x["state"]) for x in j["steps"]] == [
        ("BD_INPUT", "SUCCEEDED"), ("BD_MESH0", "SKIPPED"), ("BD_GEOM", "SUCCEEDED"), ("BD_LOADS", "SUCCEEDED"),
        ("BD_PREP_REGISTER", "SUCCEEDED")]
    cmds = [c["cmd"] for c in calls(exe) if c["cmd"] != "version"]
    assert cmds == ["fixed-scan"]                                  # extract·tag·grid 없음
    d = esl_root / "_doe" / s["id"]
    assert (d / "prep" / "fixed" / "shell_scan.json").is_file() and (d / "prep" / "assem_full").is_dir()
    for f in ("part.glb", "select.bin", "select_manifest.json"):
        assert (d / "prep" / "select" / f).is_file()
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["n_nodes"] == int(w["mesh"]["node_id"].size)
    assert g["prep"]["n_elems"] == int(w["mesh"]["elem_id"].size)
    assert g["prep"]["fixed"]["source"] == "scan" and g["prep"]["fixed"]["n"] > 0
    assert not any(x["code"] == "FIXED_INFO_MISSING" for x in g["prep"]["warnings"])
    assert tree(inputs_root) == in_before


@pytest.mark.parametrize("ctl", [{"version": "0.1.0"}, {"fail": {"fixed-scan": {"code": "FIXED_PARSE_FAILED", "exit": 3}}}],
                         ids=["paicad_unusable", "fixed_scan_failed"])
def test_select_prep_without_fixed_info(client, engine, worker, esl_root, inputs_root, exe, ctl):
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create(client, w["entry_ids"])
    set_control(exe, rules=[], **ctl)
    j = run_job(client, worker, s["job"]["id"])
    st = {x["step_key"]: x["state"] for x in j["steps"]}
    assert st["BD_GEOM"] == "SKIPPED" and st["BD_LOADS"] == "SUCCEEDED" and st["BD_MESH0"] == "SKIPPED"
    assert any("FIXED_INFO_MISSING" in x for x in j["warnings"])
    d = esl_root / "_doe" / s["id"]
    assert not (d / "prep" / "fixed" / "shell_scan.json").exists()
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["fixed"] == {"source": "none", "n": 0}
    assert any(x["code"] == "FIXED_INFO_MISSING" for x in g["prep"]["warnings"])
    log = client.get(f"{API}/jobs/{j['id']}/log", params={"step": 3}, headers=R).text
    assert "FIXED_INFO_MISSING" in log


# ---------------------------------------------------------------- PREVIEW → RUN
def test_select_preview_states_run_resume(client, engine, worker, esl_root, inputs_root, exe):
    w = make_bead_case(engine, esl_root, inputs_root)
    in_before = tree(inputs_root)
    lib_before = tree(esl_root / "_library")
    s = create(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    s = save_selection(client, study(client, s["id"]), ring_selection(w["g"]))
    sel_sha = s["selection"]["sha256"]
    names = [x["name"] for x in api(client, "GET", f"/doe/studies/{s['id']}/params").json()["params"]]
    assert {"B1_D1", "B1_W", "B2_W"} <= set(names)
    # B1_W 3수준(가운데 = 공칭) → 바깥 2수준 = 고정 침범, B2_W 25 → 사면 겹침(뒤집힘)
    spec = {"method": "fullfact", "levels": 3, "params": [{"name": "B1_W", "lo": 47.0, "hi": 70.435},
                                                          {"name": "B2_W", "lo": 25.0, "hi": 42.0}]}
    n_grid = len(calls(exe, "view"))
    p = preview(client, s, spec)
    j = run_job(client, worker, p["job"]["id"])
    assert [(x["step_key"], x["state"]) for x in j["steps"]] == [
        ("BD_MATRIX", "SUCCEEDED"), ("BD_GRID", "SUCCEEDED"), ("BD_PREVIEW_REGISTER", "SUCCEEDED")]
    assert len(calls(exe, "view")) == n_grid                       # paicad grid 호출 없음
    d = esl_root / "_doe" / s["id"]
    g = study(client, s["id"])
    rev = g["doe"]["rev"]
    man = json.loads((d / "doe" / str(rev) / "grid" / "grid_manifest.json").read_text())
    assert man["kind"] == "select" and man["selection_sha256"] == sel_sha and man["basis_sha256"]
    assert {"schema_version", "cells", "nominal"} <= set(man)
    assert all({"id", "status", "code", "thumb"} <= set(c) for c in man["cells"])
    assert (d / "doe" / str(rev) / "grid" / "cells" / "nominal" / "thumb.png").is_file()
    mx = json.loads((d / "doe" / str(rev) / "matrix.json").read_text())
    vals = {x["id"]: x["values"] for x in mx["designs"] if x["id"] != "d000"}
    pv = g["doe"]["preview"]
    cells = {c["id"]: c for c in pv["cells"]}
    fixed = {i for i, v in vals.items() if abs(v["B1_W"] - 58.7175) > 0.01}
    inverted = {i for i, v in vals.items() if i not in fixed and abs(v["B2_W"] - 25.0) < 1e-9}
    assert len(fixed) == 6 and len(inverted) == 1
    for i in fixed:
        assert cells[i]["status"] == "SKIPPED_FIXED", (i, cells[i])
    for i in inverted:
        assert cells[i]["status"] == "FAILED_MESH", (i, cells[i])
    ready = {i for i, c in cells.items() if c["status"] == "READY"}
    assert ready == set(vals) - fixed - inverted and len(ready) == 2
    assert pv["selection_sha256"] == sel_sha
    assert pv["skipped"] == {"collision": 0, "fixed": 6, "geom": 0, "mesh": 1} and pv["ok"] == 2
    # 실행: READY 안만, paicad 없음
    n_before = len([c for c in calls(exe) if c["cmd"] != "version"])
    r = start_run(client, g)
    j = run_job(client, worker, r["job"]["id"])
    assert [x["step_key"] for x in j["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    assert len([c for c in calls(exe) if c["cmd"] != "version"]) == n_before
    ran = {p.name for p in (d / "run" / "designs").iterdir() if (p / "done.json").is_file()}
    assert ran == {"d000"} | ready
    log = client.get(f"{API}/jobs/{j['id']}/log", params={"step": 2}, headers=R).text
    assert "대상 안 2개" in log and "모핑 · solve 2 ESL" in log
    res = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
    assert {x["id"] for x in res["ranking"]} == ready
    # 이어하기 키 = 선택·기저 sha 포함(BS-D-13)
    from esl_worker import core_adapter

    from esl_worker import doe_jobs, paicad_proc
    from sqlalchemy import text

    from esl.doe import evaluate as ev
    with engine.connect() as c:
        params = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": j["id"]}).scalar()
    did = sorted(ready)[0]
    sha = core_adapter.doe_design_sha(params["doe"], str(d), did)
    done = json.loads((d / "run" / "designs" / did / "done.json").read_text())
    assert done["input_sha256"] == sha and done["status"] == "OK"
    doe2 = json.loads(json.dumps(params["doe"]))
    (d / "doe" / str(rev) / "selection.json").write_text(json.dumps(
        {**json.loads((d / "doe" / str(rev) / "selection.json").read_text()), "basis_sha256": "0" * 64}))
    assert core_adapter.doe_design_sha(doe2, str(d), did) != sha              # 기저 sha 가 바뀌면 다른 키
    (d / "doe" / str(rev) / "selection.json").write_text(json.dumps(
        {**json.loads((d / "doe" / str(rev) / "selection.json").read_text()), "basis_sha256": man["basis_sha256"]}))
    assert core_adapter.doe_design_sha(doe2, str(d), did) == sha and ev.reusable(str(d / "run" / "designs" / did), sha)
    # 이어하기(워커 _one_design): done.json 이 같은 키 → 코어 자식 없이 재사용, 기저가 바뀌면 다시 평가
    ex = SimpleNamespace(lib={"doe": params["doe"]}, cdir=str(d))

    def no_eval(*_a, **_k):
        raise AssertionError("재사용 안이 다시 평가됨")
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(doe_jobs, "_eval_child", no_eval)
        r1 = doe_jobs._one_design(ex, did, paicad_proc.Procs(), print)
        assert r1["reused"] and r1["status"] == "OK"
        evals = []
        mp.setattr(doe_jobs, "_eval_child", lambda ex_, did_, pa, procs: evals.append((did_, pa)) or ("OK", None))
        sj = d / "doe" / str(rev) / "selection.json"
        keep = sj.read_text()
        sj.write_text(json.dumps({**json.loads(keep), "basis_sha256": "0" * 64}))
        r2 = doe_jobs._one_design(ex, did, paicad_proc.Procs(), print)
        assert not r2["reused"] and evals == [(did, None)]                  # select = paicad 없음(pa None)
        sj.write_text(keep)
    finally:
        mp.undo()
    # 산출물 rad 사본: /NODE 좌표 칸 외 바이트 동일, ID 불변
    best = res["best"]["id"] if isinstance(res.get("best"), dict) else res["ranking"][0]["id"]
    inc = d / "best" / best / "include" / w["rad"].name
    assert inc.is_file() and (d / "best" / best / "selection.json").is_file()
    moved, bad = node_block_diff(w["rad"].read_bytes(), inc.read_bytes())
    assert bad == 0 and moved > 0
    assert tree(inputs_root) == in_before and tree(esl_root / "_library") == lib_before


# ---------------------------------------------------------------- BD_GRID(bd_select_grid) lease 유지·취소
def _grid_ready(client, engine, worker, esl_root, inputs_root):
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    s = save_selection(client, study(client, s["id"]), sb.selection(w["g"]))
    spec = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D1", "lo": 21.0, "hi": 23.0}]}
    return w, s, spec


def _pid_file(esl_root, sid, jid) -> Path:
    return esl_root / "_doe" / sid / "logs" / jid / "slow_grid.pid"


def test_select_grid_slow_keeps_lease(client, engine, worker_factory, esl_root, inputs_root, exe, monkeypatch):
    """코어 자식 bd_select_grid 가 lease_ttl(시험 3 s)보다 오래 걸려도 executor._run_core 가 lease 를 갱신 → 성공."""
    set_control(exe, rules=[])
    monkeypatch.setenv("ESL_TEST_SLOW_GRID_S", "4.5")
    wk = worker_factory(core_target="slow_core:slow_select_grid")
    wk.heartbeat_once()
    _w, s, spec = _grid_ready(client, engine, wk, esl_root, inputs_root)
    p = preview(client, s, spec)
    j = run_job(client, wk, p["job"]["id"])
    assert [(x["step_key"], x["state"]) for x in j["steps"]] == [
        ("BD_MATRIX", "SUCCEEDED"), ("BD_GRID", "SUCCEEDED"), ("BD_PREVIEW_REGISTER", "SUCCEEDED")]
    assert _pid_file(esl_root, s["id"], j["id"]).is_file()
    lg = client.get(f"{API}/jobs/{j['id']}/log", params={"step": 2}, headers=R).text
    assert "[slow_select_grid] 대기 끝" in lg and "[bd_select_grid]" in lg, lg[-2000:]
    assert study(client, s["id"])["phase"] == "PREVIEW_READY"


def test_select_grid_cancel_kills_core_and_retry(client, engine, worker_factory, esl_root, inputs_root, exe,
                                                 monkeypatch):
    """BD_GRID 중 취소 → 코어 자식 종료·CANCELED(lease 는 그동안 갱신), 재시도 → BD_GRID 부터 성공."""
    import threading
    import time as _t

    from esl_test_support import wait_for
    set_control(exe, rules=[])
    monkeypatch.setenv("ESL_TEST_SLOW_GRID_S", "600")
    wk = worker_factory(core_target="slow_core:slow_select_grid")
    wk.heartbeat_once()
    _w, s, spec = _grid_ready(client, engine, wk, esl_root, inputs_root)
    p = preview(client, s, spec)
    jid = p["job"]["id"]
    res: dict[str, Any] = {}
    th = threading.Thread(target=lambda: res.update(state=wk.run_once("SLOT")))
    th.start()
    pf = _pid_file(esl_root, s["id"], jid)
    wait_for(lambda: pf.is_file() and pf.read_text().strip(), timeout=120)
    pid = int(pf.read_text())
    for _ in range(12):                             # ttl(3 s) 넘게 — lease 갱신 중이면 RUNNING 유지
        wk.heartbeat_once()
        _t.sleep(0.3)
    j = get_job(client, jid)
    assert j["state"] == "RUNNING" and {x["step_key"]: x["state"] for x in j["steps"]}["BD_GRID"] == "RUNNING"
    r = client.post(f"{API}/jobs/{jid}/cancel", headers=H("tok-power", True))
    assert r.status_code in (200, 202), r.text
    th.join(60)
    assert not th.is_alive() and res.get("state") == "CANCELED"
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    assert not alive                                # 코어 자식 종료
    j = get_job(client, jid)
    assert j["state"] == "CANCELED"
    st = {x["step_key"]: x["state"] for x in j["steps"]}
    assert st["BD_MATRIX"] == "SUCCEEDED" and st["BD_GRID"] == "CANCELED"
    rev = study(client, s["id"])["doe"]["rev"]
    assert not (esl_root / "_doe" / s["id"] / "doe" / str(rev) / "grid" / "grid_manifest.json").exists()
    monkeypatch.setenv("ESL_TEST_SLOW_GRID_S", "0")
    r = client.post(f"{API}/jobs/{jid}/retry", headers=H("tok-power", True))
    assert r.status_code in (200, 201), r.text
    j2 = run_job(client, wk, r.json()["id"])
    assert {x["step_key"]: x["state"] for x in j2["steps"]}["BD_GRID"] == "SUCCEEDED"
    assert study(client, s["id"])["phase"] == "PREVIEW_READY"
