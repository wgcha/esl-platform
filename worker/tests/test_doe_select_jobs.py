"""v0.15.0 select 비드 직접 선택 워커 작업(계약 esl_bead_select.md §8, V-BS-14) — 실제 PG·워커·코어·자체 솔버, 가짜 paicad
(fixed-scan 만), 합성 비드 메시(tests/doe/synth_bead.py, h 10 mm).

- PREP: BD_MESH0 SKIPPED, BD_GEOM = 모델 전체 사본 + fixed-scan 만(extract·tag 없음) → prep/fixed/, 준비 요약 n_nodes·n_elems·fixed.
  paicad 버전 불가·fixed-scan 실패 → BD_GEOM SKIPPED + FIXED_INFO_MISSING(준비 성공).
- PREVIEW: BD_GRID = 코어 bd_select_grid(paicad grid 호출 없음), grid_manifest 가 paicad grid 형식 키(cells[id, status, code,
  thumb], nominal), 셀 상태 SELECT_FIXED_VIOLATION → SKIPPED_FIXED·SELECT_MORPH_INVERTED → FAILED_MESH, doe.preview
  selection_sha256·skipped.mesh.
- RUN: READY 안만 실행(paicad 없음), 이어하기(재시도 → 재사용, done.json input_sha256 = 선택·기저 sha 포함), 산출물 rad 사본 =
  원본과 /NODE 좌표 칸 외 바이트 동일·ID 불변, 입력 폴더·라이브러리 불변.
- v0.16.1(esl_select_relax.md, 기본 warn 정책): 고정 침범 안 = READY + SELECT_FIXED_MOVED(셀 warnings·fixed_viol), 뒤집힘이 먼저
  (침범 + 뒤집힘 = FAILED_MESH), doe.preview warn·rules, 경고 안도 실행·순위(행 warn, summary.best_clean). V-SR-10·11 은
  ``test_doe_select_relax_jobs.py``.
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
from esl_test_support import API, REPO, H, past_ttl_s
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


def strip_esl_comments(b: bytes) -> bytes:
    """v0.16.1 SR-D-12 받기 경고 주석 줄(#ESL WARNING …) 제거 — 원본 줄바꿈 그대로."""
    return b"".join(x for x in b.splitlines(keepends=True) if not x.startswith(b"#ESL WARNING "))


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
    # SR-D-1: 뒤집힘 판정이 먼저 — B2_W 25(사면 겹침)·B1_W 47(고정 고리 안쪽으로 좁힘 = 고정 층 둘레 요소 뒤집힘)
    inverted = {i for i, v in vals.items() if abs(v["B2_W"] - 25.0) < 1e-9 or abs(v["B1_W"] - 47.0) < 1e-9}
    moved = fixed - inverted
    assert len(fixed) == 6 and len(inverted) == 5 and len(moved) == 2
    for i in inverted:
        assert (cells[i]["status"], cells[i]["code"]) == ("FAILED_MESH", "SELECT_MORPH_INVERTED"), (i, cells[i])
    for i in moved:                                                                   # warn 정책: 실행 대상 + 경고
        assert cells[i]["status"] == "READY", (i, cells[i])
        assert [w["code"] for w in cells[i]["warnings"]] == ["SELECT_FIXED_MOVED"], (i, cells[i])
        assert cells[i]["warnings"][0]["n"] == cells[i]["fixed_viol"]["n"] > 0
    ready = {i for i, c in cells.items() if c["status"] == "READY"}
    assert ready == set(vals) - inverted and len(ready) == 4
    assert all("warnings" not in cells[i] for i in ready - moved)
    assert pv["selection_sha256"] == sel_sha and "rules_outdated" not in pv
    assert pv["skipped"] == {"collision": 0, "fixed": 0, "geom": 0, "mesh": 5} and pv["ok"] == 4 and pv["warn"] == 2
    from esl_platform.core.db.tables import bead_does
    from sqlalchemy import select as sa_select
    with engine.connect() as c:
        dpv = c.execute(sa_select(bead_does.c.doe).where(bead_does.c.id == s["id"])).scalar()["preview"]
    assert dpv["warn"] == 2 and dpv["rules"] == 3
    # 실행: READY 안만, paicad 없음
    n_before = len([c for c in calls(exe) if c["cmd"] != "version"])
    r = start_run(client, g)
    j = run_job(client, worker, r["job"]["id"])
    assert [x["step_key"] for x in j["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    assert len([c for c in calls(exe) if c["cmd"] != "version"]) == n_before
    ran = {p.name for p in (d / "run" / "designs").iterdir() if (p / "done.json").is_file()}
    assert ran == {"d000"} | ready
    log = client.get(f"{API}/jobs/{j['id']}/log", params={"step": 2}, headers=R).text
    assert "대상 안 4개" in log and "모핑 · solve 2 ESL" in log
    res = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
    assert {x["id"] for x in res["ranking"]} == ready                                 # 경고 안도 순위(SR-D-11)
    assert {x["id"] for x in res["ranking"] if x.get("warn")} == moved
    assert all(x["warn"] == ["FIXED_MOVED"] for x in res["ranking"] if x.get("warn"))
    assert res["summary"]["best_clean"] == next(x["id"] for x in res["ranking"] if not x.get("warn"))
    # 이어하기 키 = 선택·기저 sha 포함(BS-D-13)
    from esl_worker import core_adapter

    from esl_worker import doe_jobs, paicad_proc
    from sqlalchemy import text

    from esl.doe import evaluate as ev
    with engine.connect() as c:
        params = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": j["id"]}).scalar()
    did = sorted(ready - moved)[0]
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
    raw = inc.read_bytes()
    assert (b"#ESL WARNING FIXED_MOVED" in raw) == (best in moved)                    # SR-D-12 경고 안만 주석
    n_moved, bad = node_block_diff(w["rad"].read_bytes(), strip_esl_comments(raw))
    assert bad == 0 and n_moved > 0
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


@pytest.mark.short_lease
def test_select_grid_slow_keeps_lease(client, engine, worker_factory, esl_root, inputs_root, exe, monkeypatch,
                                      loaded_config):
    """코어 자식 bd_select_grid 가 설정 lease_ttl_s 보다 오래 걸려도 executor._run_core 가 lease 를 갱신 → 성공."""
    set_control(exe, rules=[])
    monkeypatch.setenv("ESL_TEST_SLOW_GRID_S", str(past_ttl_s(loaded_config)))
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


@pytest.mark.short_lease
def test_select_grid_cancel_kills_core_and_retry(client, engine, worker_factory, esl_root, inputs_root, exe,
                                                 monkeypatch, loaded_config):
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
    end = _t.monotonic() + past_ttl_s(loaded_config, 1.2)
    while _t.monotonic() < end:                     # 설정 lease_ttl_s 넘게 — lease 갱신 중이면 RUNNING 유지
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


# ================================================================ v0.16.2 자동 탐지 · ② B 메시 기준 select(esl_bead_auto.md AD-D-2·16·17)
# 코어(Impl-Core) 병합 전에는 BD_INPUT 이 select 의 STEP 사본·B 메시 기준을 만들지 않는다 — 그 단계에 기대는 시험만 건너뛴다.
def _core_v0162() -> tuple[bool, bool]:
    import importlib.util

    from esl.doe import stages

    return importlib.util.find_spec("esl.doe.bead_auto") is not None, hasattr(stages, "_mesh_base")


CORE_AUTO, CORE_MESH_BASE = _core_v0162()
needs_core_auto = pytest.mark.skipif(not CORE_AUTO, reason="코어 esl.doe.bead_auto·select STEP 사본(v0.16.2 Impl-Core) 병합 후")
needs_core_mesh = pytest.mark.skipif(not CORE_MESH_BASE, reason="코어 stages._mesh_base(v0.16.2 Impl-Core) 병합 후")
AUTO_CMDS = ["extract", "extract", "tag"]       # extract0(1차) · extract · tag (가짜 paicad 명령 이름)


def create_select(client, entry_ids, *, auto=False, mesh_uid=None, **kw) -> dict[str, Any]:
    from doe_support import upload_step

    b = {"project_id": "p-1", "scenario": "select", "entry_ids": entry_ids, "title": "select v0.16.2", **kw}
    if auto:
        b.update(bead_source="auto", step_upload_id=upload_step(client))
    if mesh_uid:
        b.update(select_base="mesh", mesh_upload_id=mesh_uid)
    r = api(client, "POST", "/doe/studies", json=b)
    assert r.status_code == 201, r.text
    return r.json()


def b_mesh_upload(client, tmp_path, mesh, node_base: int = 100000) -> str:
    """B 메시 = 같은 형상, 노드 ID 만 다른 rad(A 체결점 ID 와 겹치지 않게 — O-1 고정 확인용)."""
    from doe_support import rad_mesh_bytes
    from opt_support import upload_files

    m = dict(mesh)
    m["node_id"] = np.asarray(mesh["node_id"]) + node_base
    return upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path, m, part_title=PART)})


def auto_doc(esl_root, sid) -> dict[str, Any]:
    return json.loads((esl_root / "_doe" / sid / "prep" / "auto_detect.json").read_text())


def test_v0162_auto_prep_paicad_unusable_manual_continues(client, engine, worker, esl_root, inputs_root, exe):
    """V-AD-4: paicad 불가 + auto → 준비 READY + AUTO_DETECT_FAILED{step: version} + FIXED_INFO_MISSING + 빈 seed(GET …/select/auto
    404), 수동 저장·미리보기·실행은 그대로."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=True)
    set_control(exe, rules=[], version="0.1.0")
    j = run_job(client, worker, s["job"]["id"])
    st = {x["step_key"]: x["state"] for x in j["steps"]}
    assert st["BD_GEOM"] == "SKIPPED" and st["BD_LOADS"] == "SUCCEEDED"
    assert [c["cmd"] for c in calls(exe) if c["cmd"] != "version"] == []
    ad = auto_doc(esl_root, s["id"])
    assert ad["schema"] == "esl/doe_auto_detect/1" and ad["ok"] is False and ad["step"] == "version"
    assert isinstance(ad["code"], str) and ad["code"] and ad["paicad_version"] is None
    assert any("AUTO_DETECT_FAILED" in x for x in j["warnings"]) and any("FIXED_INFO_MISSING" in x for x in j["warnings"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["inputs"]["bead_source"] == "auto" and "select_base" not in g["prep"]
    assert g["prep"]["auto"] == {"ok": False, "step": "version", "code": ad["code"], "available": False, "n_beads": 0,
                                 "selection_sha256": None}
    codes = [x["code"] for x in g["prep"]["warnings"]]
    assert "AUTO_DETECT_FAILED" in codes and "FIXED_INFO_MISSING" in codes and codes.count("AUTO_DETECT_FAILED") == 1
    adw = next(x for x in g["prep"]["warnings"] if x["code"] == "AUTO_DETECT_FAILED")
    assert (adw["step"], adw["detail"]) == ("version", ad["code"])           # 안쪽 코드 = detail(경고 code 와 겹치지 않게)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "AUTO_NOT_AVAILABLE"
    s = save_selection(client, g, sb.selection(w["g"]))
    p = preview(client, s, {"method": "fullfact", "levels": 2, "params": [{"name": "B1_D1", "lo": 20.0, "hi": 24.0}]})
    run_job(client, worker, p["job"]["id"])
    r = start_run(client, study(client, s["id"]))
    run_job(client, worker, r["job"]["id"])
    g = study(client, s["id"])
    assert g["phase"] == "DONE" and g["result_ready"] is True


def test_v0162_auto_prep_case_plan(client, engine, worker, esl_root, inputs_root, exe):
    """AD-D-17 ① plan: assem_full → fixed → extract0 → extract → tag(조립 = prep/assem_full). 코어가 STEP 사본을 남기기 전
    (병합 전)에는 extract0 앞에서 AUTO_DETECT_FAILED{extract0, PREREQUISITE_MISSING} — 어느 쪽이든 준비 READY."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=True)
    j = run_job(client, worker, s["job"]["id"])
    st = {x["step_key"]: x["state"] for x in j["steps"]}
    assert st["BD_GEOM"] == "SUCCEEDED" and st["BD_MESH0"] == "SKIPPED"
    d = esl_root / "_doe" / s["id"]
    inp = json.loads((d / "prep" / "input.json").read_text())
    cmds = [c for c in calls(exe) if c["cmd"] != "version"]
    ad = auto_doc(esl_root, s["id"])
    assert ad["paicad_version"] == "0.15.4"
    if inp.get("step"):
        assert [c["cmd"] for c in cmds] == ["fixed-scan"] + AUTO_CMDS
        assert ad["ok"] is True and ad["step"] is None and ad["code"] is None
        for c in cmds[2:]:          # extract(2차)·tag 조립 = 모델 전체 사본
            i = c["argv"].index("--assem-dir")
            assert c["argv"][i + 1].endswith(os.path.join("prep", "assem_full"))
        assert (d / "prep" / "tag" / "shell_tag.json").is_file() and (d / "prep" / "body_map.json").is_file()
    else:
        assert [c["cmd"] for c in cmds] == ["fixed-scan"]
        assert ad == {"schema": "esl/doe_auto_detect/1", "ok": False, "step": "extract0", "code": "PREREQUISITE_MISSING",
                      "paicad_version": "0.15.4"}
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["fixed"]["source"] == "scan"
    pa = g["prep"]["auto"]          # 준비 요약 = 코어 BD_LOADS 결과(탐지 OK 여도 seed 가 없으면 ok false — 가짜 tag 는 노드 tag 없음)
    assert pa["ok"] is pa["available"] and (pa["n_beads"] > 0) is pa["available"]
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == (200 if pa["available"] else 404)
    if pa["available"]:
        assert r.json()["sha256"] and r.json()["selection"]["beads"]
    else:
        assert pa["step"] == (ad["step"] or "tag")
    # 수동 스터디는 auto_detect.json 을 쓰지 않고 plan 도 그대로(fixed-scan 만 — v0.16.1 바이트 동일 경로)
    m = create_select(client, w["entry_ids"])
    run_job(client, worker, m["job"]["id"])
    assert not (esl_root / "_doe" / m["id"] / "prep" / "auto_detect.json").exists()
    assert "auto" not in study(client, m["id"])["prep"]


@needs_core_auto
@pytest.mark.parametrize("ctl, step, code", [
    ({"fail": {"extract": {"code": "GEOM_CAD_FAILED", "exit": 10}}}, "extract0", "GEOM_CAD_FAILED"),
    ({"fail": {"tag": {"code": "GEOM_INPUT_INVALID", "exit": 3}}}, "tag", "GEOM_INPUT_INVALID"),
    ({"fail": {"fixed-scan": {"code": "FIXED_PARSE_FAILED", "exit": 3}}}, "tag", "FIXED_INFO_MISSING"),
], ids=["extract_failed", "tag_failed", "fixed_failed_no_tag"])
def test_v0162_auto_prep_step_failures(client, engine, worker, esl_root, inputs_root, exe, ctl, step, code):
    """V-AD-4: extract0·extract·tag 실패 = AUTO_DETECT_FAILED{step, code} + 빈 seed, fixed-scan 실패 = FIXED_INFO_MISSING(tag 는
    고정 결과가 입력이라 실행하지 않음). 준비는 READY."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=True)
    set_control(exe, rules=[], **ctl)
    j = run_job(client, worker, s["job"]["id"])
    ad = auto_doc(esl_root, s["id"])
    assert (ad["ok"], ad["step"], ad["code"]) == (False, step, code)
    cmds = [c["cmd"] for c in calls(exe) if c["cmd"] != "version"]
    if step == "extract0":
        assert cmds == ["fixed-scan", "extract"]
    else:
        assert cmds == ["fixed-scan", "extract", "extract"] + (["tag"] if code != "FIXED_INFO_MISSING" else [])
    assert any("AUTO_DETECT_FAILED" in x for x in j["warnings"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["auto"]["available"] is False
    adw = [x for x in g["prep"]["warnings"] if x["code"] == "AUTO_DETECT_FAILED"]
    assert [(x["step"], x["detail"]) for x in adw] == [(step, code)]
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/auto").status_code == 404


@needs_core_mesh
def test_v0162_select_mesh_prep_fixed(client, engine, worker, esl_root, inputs_root, exe, tmp_path):
    """V-AD-12(워커): select(mesh) plan = a_fixed(A Case) → fixed(assem = input/mesh, B part_id) → prep/fixed 는 B 원 노드 ID 만
    (A 체결점은 고정 노드에 없음 — O-1), base.json scenario select·target S2, 준비 요약 select_base mesh·fixed scan."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], mesh_uid=b_mesh_upload(client, tmp_path, w["mesh"]))
    j = run_job(client, worker, s["job"]["id"])
    assert {x["step_key"]: x["state"] for x in j["steps"]}["BD_GEOM"] == "SUCCEEDED"
    cmds = [c for c in calls(exe) if c["cmd"] != "version"]
    assert [c["cmd"] for c in cmds] == ["fixed-scan", "fixed-scan"]           # A(a_fixed) → B(fixed), extract·tag 없음
    d = esl_root / "_doe" / s["id"]
    b_argv = cmds[1]["argv"]
    assert b_argv[b_argv.index("--assem-dir") + 1] == str(d / "input" / "mesh")
    assert not (d / "prep" / "assem_full").exists()
    fx = np.load(d / "prep" / "fixed" / "fixed_nodes.npz")["node_id"]
    ax = np.load(d / "prep" / "a_fixed" / "fixed_nodes.npz")["node_id"]
    assert fx.size > 0 and (fx >= 100000).all() and not set(ax.tolist()) & set(fx.tolist())
    base = json.loads((d / "prep" / "base.json").read_text())
    assert base["scenario"] == "select" and base["target"] == "S2"
    inp = json.loads((d / "prep" / "input.json").read_text())
    assert inp["select_base"] == "mesh" and inp["assem"] == "input/mesh"
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["select_base"] == "mesh" and g["prep"]["fixed"]["source"] == "scan"
    assert "auto" not in g["prep"] and not (d / "prep" / "auto_detect.json").exists()


@needs_core_mesh
@pytest.mark.parametrize("auto, ctl", [(False, {"fail": {"fixed-scan": {"code": "FIXED_PARSE_FAILED", "exit": 3}}}),
                                       (True, {"version": "0.1.0"})], ids=["fixed_failed", "paicad_unusable_auto"])
def test_v0162_select_mesh_prep_without_fixed(client, engine, worker, esl_root, inputs_root, exe, tmp_path, auto, ctl):
    """V-AD-12: B fixed-scan 실패·paicad 없음 → FIXED_INFO_MISSING(② 의 준비 실패가 아니라 select 규칙) + READY + fixed_user 지정
    가능, auto 면 AUTO_DETECT_FAILED{version}."""
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create_select(client, w["entry_ids"], auto=auto, mesh_uid=b_mesh_upload(client, tmp_path, w["mesh"]))
    set_control(exe, rules=[], **ctl)
    j = run_job(client, worker, s["job"]["id"])
    assert {x["step_key"]: x["state"] for x in j["steps"]}["BD_GEOM"] == "SKIPPED"
    assert any("FIXED_INFO_MISSING" in x for x in j["warnings"])
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["fixed"] == {"source": "none", "n": 0}
    if auto:
        assert auto_doc(esl_root, s["id"])["step"] == "version" and g["prep"]["auto"]["ok"] is False
    sel = sb.selection(w["g"])
    sel["fixed_user"] = sb.elemset(w["mesh"], np.arange(w["mesh"]["elem_id"].size) < 4)
    s = save_selection(client, g, sel)
    assert s["selection"]["rev"] == 1
