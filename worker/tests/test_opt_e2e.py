"""v0.7.0 비드 최적화 OPT_RUN 워커 E2E(계약 esl_opt_run.md §4·§6·§8·§9, V-OR-12·14·17) — 실제 PG·워커·코어,
가짜 OptiStruct/hw(tests/fake_optistruct.py).

- V-OR-17 S1: 같은 모델 ESL 3개(모드 굽힘·뒤틀림), 사각형 금지 영역 1개 → 선정·덱·OptiStruct(-check → 본 실행)·후처리·
  등록(opt_runs.result·report_rel), 파일 목록·보고서·비드 맵 API, 진행률 100, 세마포어 해제, 이력·알림.
- V-OR-17 S2: 템플릿 등록(API) → 금지 영역 세트 저장 → 실행(전략 C·목표 rel) → 결과.
- V-OR-14: S1 Case 입력·라이브러리 항목 폴더·S2 업로드 폴더 실행 전후 불변, 업로드 폴더를 치운 뒤에도 실행·retry 성공.
- V-OR-12: retry → OS_SOLVE SKIPPED(재사용, OptiStruct 호출 없음), 덱 sha 다르면 재실행, S1 Case rad 변경 →
  INPUT_CHANGED 경고, retry 는 실행 스냅샷(params) 그대로.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from esl_test_support import API, REPO, H
from opt_support import opt_settings_dict, register_template, tree
from p2_support import seed_run
from sqlalchemy import insert, select

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 OptiStruct/hw 는 POSIX 실행 스크립트")
PART = "Chassis rear"

WRAPPER = '''#!{python}
import os, runpy, sys
os.environ["FAKE_OS_SELF"] = os.path.abspath(__file__)
sys.argv[0] = os.path.abspath(__file__)
runpy.run_path({fake!r}, run_name="__main__")
'''


# ---------------------------------------------------------------- 가짜 솔버·설정
def write_fake_tools(base: Path) -> dict[str, Path]:
    tools = base / "fake_altair"
    tools.mkdir(exist_ok=True)
    out = {}
    for name in ("optistruct", "hw"):
        p = tools / name
        p.write_text(WRAPPER.format(python=sys.executable, fake=str(REPO / "tests" / "fake_optistruct.py")))
        p.chmod(0o755)
        out[name] = p
    out["dir"] = tools
    return out


def set_control(tools: dict[str, Path], **ctl: Any) -> None:
    (tools["dir"] / "fake_os_control.json").write_text(json.dumps(ctl))


def calls(tools: dict[str, Path], role: str | None = None) -> list[dict[str, Any]]:
    p = tools["dir"] / "fake_os_calls.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    return [r for r in rows if role is None or r["role"] == role]


def opt_settings(base: Path, tools: dict[str, Path], **opt_over: Any) -> dict[str, Any]:
    d = opt_settings_dict(base)
    d["altair"] = {**d["altair"], "optistruct_path": str(tools["optistruct"]), "hw_exe_path": str(tools["hw"])}
    solve = {"desmax": 5, "license_retry": {"max": 3, "wait_s": 0.2}, "nt": 2}
    solve.update(opt_over.pop("solve", {}))
    d["opt_run"] = {"enabled": True, "solve": solve, **opt_over}
    return d


@pytest.fixture()
def tools(tmp_path):
    return write_fake_tools(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, tools):
    return opt_settings(tmp_path, tools)


# ---------------------------------------------------------------- 합성 판·항목·Case
def plate(nx: int = 12, ny: int = 8, Lx: float = 300.0, Lz: float = 200.0) -> dict[str, np.ndarray]:
    xs = np.linspace(0.0, Lx, nx + 1)
    zs = np.linspace(0.0, Lz, ny + 1)
    X = np.array([[x, 0.0, z] for x in xs for z in zs])
    conn = np.array([[i * (ny + 1) + j, (i + 1) * (ny + 1) + j, (i + 1) * (ny + 1) + j + 1, i * (ny + 1) + j + 1]
                     for i in range(nx) for j in range(ny)], dtype=np.int64)
    ne = conn.shape[0]
    return {"node_id": 1 + np.arange(X.shape[0], dtype=np.int64), "x0": X,
            "elem_id": 1 + np.arange(ne, dtype=np.int64), "elem_type": np.full(ne, 4, dtype=np.int8), "conn": conn,
            "elem_pid": np.full(ne, 10, dtype=np.int64), "elem_mid": np.full(ne, 1, dtype=np.int64),
            "thickness": np.full(ne, 1.5), "E": np.full(ne, 2.1e5), "nu": np.full(ne, 0.3)}


def supports_321(mesh) -> list[dict[str, Any]]:
    from esl.mech import supports as msup

    pc = msup.pca_corners(mesh["x0"])
    return [{"node_id": int(mesh["node_id"][i]), "dof": d} for i, d in msup.pick_321(mesh["x0"], pc["idx"])]


def esl_load(mesh, kind: str, amp: float) -> np.ndarray:
    from esl.library import normalize as nz

    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    loc = nz.local_coords(fr, mesh["x0"])
    s, t = 2 * loc[:, 0] - 1, 2 * loc[:, 1] - 1
    q = {"bend": 0.5 * (3 * s ** 2 - 1), "twist": s * t}[kind]
    A = nz.node_areas(mesh["x0"], mesh["conn"], mesh["elem_type"])
    return amp * (q * A)[:, None] * np.asarray(fr["n"])[None, :]


def write_entry(esl_root: Path, eid: str, mesh: dict, kind: str, amp: float, *, inch: int | None = 55,
                scene: int = 1) -> dict[str, Any]:
    """실제 형식의 라이브러리 항목 폴더(entry.json·summary.npz(셀 합력·합모멘트)·raw.npz(f = F_eq, u_rel = 자체 솔버))."""
    from esl.library import normalize as nz
    from esl.mech.shell import ShellModel

    d = esl_root / "_library" / "entries" / eid
    d.mkdir(parents=True, exist_ok=True)
    X = mesh["x0"]
    fr = nz.frame(X, None, mesh["conn"], mesh["elem_type"])
    sup = supports_321(mesh)
    F = esl_load(mesh, kind, amp)
    nid = mesh["node_id"]
    sm = ShellModel(X, mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], backend="superlu")
    u, _ = sm.solve(F, [(int(np.searchsorted(nid, s["node_id"])), s["dof"]) for s in sup])
    gs = nz.grid_summary(X, F, 24, 14, fr, top_n=5, node_id=nid)
    np.savez_compressed(d / "summary.npz", **{k: np.asarray(gs[k]) for k in ("cell_F_loc", "cell_M_loc", "cell_F",
                                                                             "cell_M")})
    np.savez_compressed(d / "raw.npz", **{k: np.asarray(v) for k, v in mesh.items()}, f=F, u_rel=u[:, :3],
                        is_bc=np.zeros(nid.size, bool), support_node_id=np.array([s["node_id"] for s in sup]),
                        support_dof=np.array([s["dof"] for s in sup]))
    meta = {"schema": "esl/library_entry/1", "entry_id": eid, "frame": fr, "grid": {"nx": 24, "ny": 14},
            "model": {"product": "55QX10A", "inch": inch, "n_nodes": int(nid.size), "n_elems": int(mesh["elem_id"].size)},
            "scene": {"seq": scene, "drop_type": "Corner", "orient": "146"}, "esl": {"supports": sup}}
    (d / "entry.json").write_text(json.dumps(meta, default=lambda x: x.tolist()), encoding="utf-8")
    return {"frame": fr}


def seed_entry(engine, esl_root: Path, case_id: str, mesh: dict, kind: str, amp: float = 1.0, *, scene: int = 1,
               inch: int | None = 55) -> str:
    from esl_platform.core.db.tables import library_entries

    run = seed_run(engine, case_id)
    eid = str(uuid.uuid4())
    fr = write_entry(esl_root, eid, mesh, kind, amp, inch=inch, scene=scene)["frame"]
    dir_rel = f"_library/entries/{eid}"
    with engine.begin() as c:
        c.execute(insert(library_entries).values(
            id=eid, project_id="p-1", case_id=case_id, esl_run_id=run["run_id"], status="ACTIVE",
            model={"name": "55QX10A", "inch": inch, "n_nodes": int(mesh["node_id"].size),
                   "n_elems": int(mesh["elem_id"].size)},
            scene={"drop_type": "Corner", "scene_no": scene, "warnings": []}, quality={"verdict": "PASS", "status": "PASS", "scheme": "disp_primary/1",
                                                                                    "fail_reasons": []},
            summary={"grid": {"nx": 24, "ny": 14}, "frame": {"L_xi": fr["L_xi"], "L_eta": fr["L_eta"]}},
            dir_rel=dir_rel, summary_rel=f"{dir_rel}/summary.npz", sha256="0" * 64, registered_by="u-power",
            registered_by_name="파워"))
    return eid


def write_case_rad(path: Path, mesh: dict) -> None:
    from esl.rad import write_rad

    ids = np.where(mesh["conn"] >= 0, mesh["node_id"][np.maximum(mesh["conn"], 0)], 0)
    write_rad(str(path), mesh["node_id"], mesh["x0"], mesh["elem_id"], mesh["elem_type"], ids, 7, PART, 10, 1.5, 1,
              2.1e5, 0.3, extra_parts=1)


def make_s1(engine, esl_root: Path, inputs_root: Path, kinds=(("bend", 2.0), ("bend", 1.0), ("twist", 1.5)),
            cid: str = "c1") -> dict[str, Any]:
    from esl_platform.core.db.tables import cases

    mesh = plate()
    rad = inputs_root / f"{cid}_0000.rad"
    write_case_rad(rad, mesh)
    with engine.begin() as c:
        c.execute(insert(cases).values(id=cid, project_id="p-1", folder_name=f"f_{cid}", title=f"Case {cid}",
                                       rad_path=str(rad), results_dir=str(inputs_root),
                                       input_fingerprint={"includes": []}, part_title=PART,
                                       created_by="u-power", created_by_name="파워"))
    ids = [seed_entry(engine, esl_root, cid, mesh, k, a, scene=i + 1) for i, (k, a) in enumerate(kinds)]
    return {"case_id": cid, "rad": rad, "entry_ids": ids, "mesh": mesh}


RECT = {"name": "PCB", "corner": "a0b0", "x_mm": 120.0, "y_mm": 60.0, "w_mm": 60.0, "h_mm": 50.0}


def create_run(client, entry_ids, scenario="S1", **kw) -> dict[str, Any]:
    body = {"project_id": "p-1", "scenario": scenario, "entry_ids": entry_ids, **kw}
    r = client.post(f"{API}/opt/runs", json=body, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def get_job(client, jid) -> dict[str, Any]:
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def run_job(client, worker, jid, expect="SUCCEEDED") -> dict[str, Any]:
    st = worker.run_once("SLOT")
    j = get_job(client, jid)
    assert st == expect and j["state"] == expect, (st, j["state"], j.get("failure_code"), j.get("failure_message"),
                                                   [(s["step_key"], s["state"], s.get("failure_code")) for s in j["steps"]])
    return j


def os_in_use(engine) -> int:
    from esl_platform.core.repositories import jobs as jobs_repo

    with engine.connect() as c:
        return jobs_repo.os_in_use(c)


def step_outputs(engine, jid: str, no: int) -> dict[str, Any]:
    from esl_platform.core.db.tables import job_steps

    with engine.connect() as c:
        return c.execute(select(job_steps.c.outputs).where(job_steps.c.job_id == jid, job_steps.c.step_no == no)).scalar()


def run_dir(esl_root: Path, rid: str) -> Path:
    return esl_root / "_opt" / rid


# ---------------------------------------------------------------- V-OR-17 S1 + V-OR-14
def test_s1_e2e(client, engine, worker_factory, esl_root, inputs_root, tools):
    s1 = make_s1(engine, esl_root, inputs_root)
    before_inputs = tree(inputs_root)
    before_lib = tree(esl_root / "_library")
    run = create_run(client, s1["entry_ids"], title="S1 강건 비드",
                     design={"keepout": {"rects": [RECT], "auto": {"hole": True, "edge": True}}})
    jid = run["job_id"]
    j = run_job(client, worker_factory(), jid)
    assert [s["step_key"] for s in j["steps"]] == ["OPT_PREP", "OPT_LOAD", "OPT_DECK", "OS_SOLVE", "OPT_POST",
                                                   "OPT_REGISTER"]
    assert [s["state"] for s in j["steps"]] == ["SUCCEEDED"] * 6
    assert j["progress_pct"] == 100.0
    rd = run_dir(esl_root, run["id"])
    for rel in ("target/target.npz", "target/target.json", "target/keepout.png", "load/selection.json", "load/loads.npz",
                "deck/esl_bead.fem", "deck/esl_loads.inc", "deck/run_optistruct.bat", "solve/esl_bead.out",
                "solve/esl_bead_des.h3d", "solve/solve.json", "post/shape.csv", "post/bead.npz", "post/bead_map.png",
                "post/bead_nodes.csv", "post/history.csv", "post/bead_mesh.rad", "post/bead_mesh.fem", "opt.json",
                "report.html", f"logs/{jid}/step_04_OS_SOLVE.log"):
        assert (rd / rel).is_file(), rel
    # OptiStruct: -check → 본 실행, cwd = solve/, argv[0] = 설정 경로, 세마포어 해제
    os_calls = calls(tools, "optistruct")
    assert len(os_calls) == 2 and "-check" in os_calls[0]["argv"] and "-check" not in os_calls[1]["argv"]
    assert os_calls[1]["argv"][1] == str(rd / "solve" / "esl_bead.fem") and os_calls[1]["cwd"] == str(rd / "solve")
    assert os_calls[1]["argv"][2:4] == ["-nt", "2"]
    assert os_in_use(engine) == 0
    solve = json.loads((rd / "solve" / "solve.json").read_text())
    assert solve["ok"] and solve["converged"] and solve["iterations"] == 3 and solve["license_waits"] == 0
    # 덱: 금지 영역(가장자리·사각형) 요소는 비설계, server 카드
    deck = (rd / "deck" / "esl_bead.fem").read_text()
    assert f"opt_run {run['id']} S1" in deck and "DOPTPRM,DESMAX,5" in deck
    # 결과 등록: opt_runs.result = OptResult + files, report_rel
    r = client.get(f"{API}/opt/runs/{run['id']}", headers=R).json()
    res = r["result"]
    assert r["report_ready"] and r["state"] == "SUCCEEDED"
    assert {"load_selection", "objective_norm", "C_ref", "converged", "iterations", "desmax", "objective", "subcases",
            "keepout", "bead", "solve", "warnings", "files"} <= set(res)
    sel = res["load_selection"]
    assert sel["strategy"] == "A" and sel["objective_norm"] == "abs" and sel["n_selected_esl"] == 3
    assert res["converged"] is True and res["iterations"] == 3 and res["desmax"] == 5
    assert res["keepout"]["n_elems_rects"] > 0 and res["keepout"]["n_elems_auto_edge"] > 0
    assert res["solve"]["reused"] is False and res["bead"]["height_max"] > 0
    assert not any("OptiStruct 초기 컴플라이언스" in w for w in res["warnings"])      # 가짜 C⁰ = 자체 솔버 C⁰
    modes = {row["mode"] for row in sel["rows"]}
    assert {"bend", "twist"} <= modes
    rels = {f["rel"] for f in res["files"]}
    assert {"opt.json", "report.html", "post/bead_map.png", "deck/esl_bead.fem", "solve/esl_bead.out"} <= rels
    # 금지 영역 안 요소는 비드 최적화 설계 요소가 아님(target.npz design)
    tz = np.load(rd / "target" / "target.npz")
    assert not tz["design"][tz["keepout_reason"] > 0].any()
    # 백엔드 파일·보고서·비드 맵 API 가 같은 위치를 읽는다
    files = client.get(f"{API}/opt/runs/{run['id']}/files", headers=R).json()
    assert {"report.html", "opt.json", "post/bead_map.png"} <= {f["rel"] for f in files}
    rep = client.get(f"{API}/opt/runs/{run['id']}/report", headers=R)
    assert rep.status_code == 200 and "방법·출처" in rep.text
    png = client.get(f"{API}/opt/runs/{run['id']}/bead-map.png", headers=R)
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    # 로그(OS_SOLVE: argv·.out 중계), 진행률 step 100
    log = client.get(f"{API}/jobs/{jid}/log", params={"step": 4}, headers=R)
    assert log.status_code == 200, log.text
    assert "ITERATION" in log.text and "-check 통과" in log.text
    assert all(s["progress_pct"] == 100.0 for s in j["steps"])
    # 이력·알림
    from esl_platform.core.db.tables import notifications

    with engine.connect() as c:
        ev = [r.event for r in c.execute(select(notifications.c.event).where(notifications.c.job_id == jid))]
    assert "JOB_SUCCEEDED" in ev
    hist = client.get(f"{API}/history", params={"project_id": "p-1", "job_type": "OPT_RUN"}, headers=R)
    assert hist.status_code == 200 and jid in hist.text, hist.text
    item = next(x for x in hist.json()["items"] if x["id"] == jid)
    # 통합: 이력 요약 = 시나리오·전략·케이스 수·수렴(프런트 summaryText 키), 링크 = 최적화 상세
    assert item["summary"]["scenario"] == "S1" and item["summary"]["load_strategy"] == "A"
    assert item["summary"]["n_cases"] >= 1 and item["summary"]["converged"] in (True, False)
    # V-OR-14: 입력 폴더·라이브러리 항목 불변
    assert tree(inputs_root) == before_inputs
    assert tree(esl_root / "_library") == before_lib


# ---------------------------------------------------------------- V-OR-12 재시도 재사용·INPUT_CHANGED·스냅샷
def test_retry_reuse_and_input_changed(client, engine, worker_factory, esl_root, inputs_root, tools):
    s1 = make_s1(engine, esl_root, inputs_root)
    run = create_run(client, s1["entry_ids"])
    w = worker_factory()
    set_control(tools, hw_mode="fail")                      # 1차: 후처리(hw) 실패 → OS_SOLVE 결과는 남음
    j1 = run_job(client, w, run["job_id"], "FAILED")
    assert j1["failure_code"] == "BEAD_POST_FAILED"
    assert {s["step_key"]: s["state"] for s in j1["steps"]}["OS_SOLVE"] == "SUCCEEDED"
    n_os = len(calls(tools, "optistruct"))
    rd = run_dir(esl_root, run["id"])
    assert os_in_use(engine) == 0
    # 생성 이후 모드 수정은 재시도에 반영되지 않음(실행 스냅샷)
    e0 = client.get(f"{API}/library/entries/{s1['entry_ids'][0]}", headers=R).json()
    r = client.patch(f"{API}/library/entries/{s1['entry_ids'][0]}", json={"version": e0["version"], "deform_mode": "dent"},
                     headers=W)
    assert r.status_code == 200, r.text
    # 2차: S1 Case rad 변경(같은 모델) → INPUT_CHANGED 경고, 덱 sha 가 다르면(solve.json 조작) OptiStruct 재실행
    with open(s1["rad"], "a") as fh:
        fh.write("# changed after run\n")
    sj = rd / "solve" / "solve.json"
    d = json.loads(sj.read_text())
    d["deck_sha256"] = "0" * 64
    sj.write_text(json.dumps(d))
    r = client.post(f"{API}/jobs/{run['job_id']}/retry", headers=W)
    assert r.status_code in (200, 201), r.text
    j2 = run_job(client, w, r.json()["id"], "FAILED")
    assert j2["params"] == j1["params"]
    assert any("INPUT_CHANGED" in x for x in j2["warnings"])
    assert {s["step_key"]: s["state"] for s in j2["steps"]}["OS_SOLVE"] == "SUCCEEDED"
    assert len(calls(tools, "optistruct")) == n_os + 2              # -check + 본 실행
    n_os += 2
    # 3차: 덱 sha 같음 + 성공 표식 → OS_SOLVE SKIPPED(재사용), OptiStruct 호출 없음
    set_control(tools, hw_mode="ok")
    r = client.post(f"{API}/jobs/{j2['id']}/retry", headers=W)
    j3id = r.json()["id"]
    j3 = run_job(client, w, j3id)
    assert j3["params"] == j1["params"]
    st = {s["step_key"]: s for s in j3["steps"]}
    assert st["OS_SOLVE"]["state"] == "SKIPPED" and st["OPT_PREP"]["state"] == "SUCCEEDED"
    assert step_outputs(engine, j3id, 4)["reused"] is True
    assert len(calls(tools, "optistruct")) == n_os
    res = client.get(f"{API}/opt/runs/{run['id']}", headers=R).json()["result"]
    assert res["solve"]["reused"] is True and res["job_id"] == j3id
    assert all(row["mode"] != "dent" for row in res["load_selection"]["rows"])
    assert (rd / "_backup").is_dir()                                 # 이전 산출물은 삭제 없이 _backup
    assert os_in_use(engine) == 0


# ---------------------------------------------------------------- 통합: S1 include 재검사(input_roots 밖 거부, 밖 파일 미읽음)
def test_s1_include_outside_roots_rejected(client, engine, worker_factory, esl_root, inputs_root, tools, tmp_path,
                                           monkeypatch):
    from esl.rad import parser as rp

    s1 = make_s1(engine, esl_root, inputs_root)
    run = create_run(client, s1["entry_ids"])
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / "evil.inc"
    evil.write_text("#include nested_should_not_be_seen.inc\n")
    lines = s1["rad"].read_text().splitlines(keepends=True)   # 실행 생성 뒤 Case rad 에 밖 include 가 생김(/END 앞)
    s1["rad"].write_text("".join(lines[:1] + [f"#include {evil}\n"] + lines[1:]))
    read: list[str] = []
    orig = rp._read_include_specs

    def spy(path, *a, **kw):
        read.append(os.path.realpath(path))
        return orig(path, *a, **kw)

    monkeypatch.setattr(rp, "_read_include_specs", spy)
    j = run_job(client, worker_factory(), run["job_id"], "FAILED")
    assert j["failure_code"] == "PATH_OUTSIDE_ROOT", (j["failure_code"], j["failure_message"])
    assert str(evil.resolve()) not in read                # 밖 파일은 열지 않음
    assert os.path.realpath(s1["rad"]) in read
    assert not (run_dir(esl_root, run["id"]) / "target" / "target.npz").exists()
    assert calls(tools, "optistruct") == []


# ---------------------------------------------------------------- V-OR-17 S2 + V-OR-14(업로드)
def test_s2_e2e_template_keepout_set(client, engine, worker_factory, esl_root, inputs_root, tools, tmp_path,
                                     settings_dict):
    from esl_platform.core.db.tables import cases

    with engine.begin() as c:
        c.execute(insert(cases).values(id="c2", project_id="p-1", folder_name="f_c2", title="Case c2",
                                       rad_path=str(inputs_root / "x.rad"), results_dir=str(inputs_root),
                                       input_fingerprint={"includes": []}, part_title=PART, created_by="u-power",
                                       created_by_name="파워"))
    src = plate(16, 10)                                  # ESL 메시(같은 크기, 다른 이산화)
    ids = [seed_entry(engine, esl_root, "c2", src, k, a, scene=i + 1)
           for i, (k, a) in enumerate((("bend", 2.0), ("twist", 1.0), ("bend", 0.5)))]
    tpl = register_template(client, tmp_path, mesh=plate(12, 8), title="평판 템플릿")
    up_root = Path(settings_dict["storage"]["upload_root"])
    before_up = tree(up_root)
    r = client.put(f"{API}/opt/keepouts", json={"template_id": tpl["id"], "rects": [RECT]}, headers=W)
    assert r.status_code == 200, r.text
    run = create_run(client, ids, "S2", template_id=tpl["id"], title="S2 템플릿",
                     design={"keepout": {"rects": [RECT]}, "bead": {"angle": 50, "min_width": 55, "height": 8}},
                     options={"load_strategy": "C", "k": 2, "objective_norm": "rel"})
    # 업로드 폴더를 치워도(stale 정리) 템플릿 복사본으로 실행
    shutil.move(str(up_root), str(tmp_path / "uploads_moved"))
    w = worker_factory()
    j = run_job(client, w, run["job_id"])
    assert [s["state"] for s in j["steps"]] == ["SUCCEEDED"] * 6
    res = client.get(f"{API}/opt/runs/{run['id']}", headers=R).json()["result"]
    sel = res["load_selection"]
    assert sel["strategy"] == "C" and sel["k"] == 2 and sel["objective_norm"] == "rel" and sel["n_cases"] == 2
    assert res["objective_norm"] == "rel" and res["keepout"]["n_elems_rects"] > 0
    rd = run_dir(esl_root, run["id"])
    tj = json.loads((rd / "target" / "target.json").read_text())
    assert tj["scenario"] == "S2" and tj["source"]["template_id"] == tpl["id"]
    deck = (rd / "deck" / "esl_bead.fem").read_text()
    pos = sorted({ln.split(",")[5] for ln in deck.splitlines() if ln.startswith("DOBJREF,")})
    assert len(pos) == 2                                         # rel: subcase 별 POS = 각자 C⁰
    # 업로드 폴더 없이 retry 도 성공(재사용): 실패 작업을 만들기 위해 결과 등록 직전 hw 실패
    set_control(tools, hw_mode="fail")
    run2 = create_run(client, ids, "S2", template_id=tpl["id"], design={"keepout": {"rects": [RECT]}})
    run_job(client, w, run2["job_id"], "FAILED")
    set_control(tools, hw_mode="ok")
    r = client.post(f"{API}/jobs/{run2['job_id']}/retry", headers=W)
    j2 = run_job(client, w, r.json()["id"])
    assert {s["step_key"]: s["state"] for s in j2["steps"]}["OS_SOLVE"] == "SKIPPED"
    shutil.move(str(tmp_path / "uploads_moved"), str(up_root))
    assert tree(up_root) == before_up
