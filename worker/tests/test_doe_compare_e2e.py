"""v0.14.0 ④ 형상 직접 비교 워커 E2E(계약 esl_step_compare.md V-SC-1·3·7) — 실제 PG·워커·코어·gmsh·자체 솔버, paicad 미사용.

- V-SC-1: 합성 STEP 3개(gmsh OCC: 300×200 평판 / + 직선 비드 1 / + 비드 2, 한 업로드 세션) + 합성 자기평형 ESL 2개 →
  DOE_PREP(BD_GEOM SKIPPED, 준비 형상 상태·요소 수·품질) → DOE_RUN(matrix_sha256 없이) → 순위 비드 2 < 비드 1 < 기준, 개선율·
  ESL별 ratio·pareto, 행 shape.name, 민감도 생략, 메시 산출물·보고서, 업로드·Case 폴더 불변.
- V-SC-7: paicad 호출 0(heartbeat version 외), 형상 1개 메시 실패 → 나머지 OK, 기준 메시 실패 → 준비 작업 실패(phase 파생 FAILED),
  준비 재시도 → 이어서 실행 성공.
- V-SC-3: 기준 미지정 → 첫 ESL Case 메시 d000 + COMPARE_REF_CASE_MESH(준비·결과).
gmsh 없으면 skip. 시험 속도용으로 compare.mesh.size_mm = 6(기본 3 mm 는 코어·설정 시험)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from doe_support import api
from doe_worker_support import calls, doe_worker_settings, set_control, write_fake_paicad
from esl_test_support import API, REPO, H
from opt_support import tree, upload_files
from test_opt_e2e import make_s1

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_compare as scmp  # noqa: E402


def _gmsh_ok() -> bool:
    try:
        import gmsh  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


pytestmark = [pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트"),
              pytest.mark.skipif(not _gmsh_ok(), reason="gmsh 없음")]
R = H("tok-power")
PROPS = {"t": 2.0, "E": 205000.0, "nu": 0.3}


@pytest.fixture()
def exe(tmp_path):
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, exe):
    d = doe_worker_settings(tmp_path, exe, mesh={"occ_sew_faces": 1})
    d["bead_doe"]["compare"] = {"mesh": {"size_mm": 6.0}}
    return d


@pytest.fixture()
def worker(worker_factory, exe):
    set_control(exe, rules=[])
    w = worker_factory()
    w.heartbeat_once()
    return w


def get_job(client, jid) -> dict[str, Any]:
    return client.get(f"{API}/jobs/{jid}", headers=R).json()


def run_job(client, worker, jid, expect="SUCCEEDED") -> dict[str, Any]:
    st = worker.run_once("SLOT")
    j = get_job(client, jid)
    assert st == expect and j["state"] == expect, (st, j["state"], j.get("failure_code"), j.get("failure_message"),
                                                   [(s["step_key"], s["state"], s.get("failure_code")) for s in j["steps"]])
    return j


def steps(tmp_path: Path, specs: list[tuple[str, int, dict]]) -> dict[str, bytes]:
    out = {}
    for name, n, kw in specs:
        p = scmp.plate_step(tmp_path / "gen" / f"{name}.step", n, Lx=300.0, Lz=200.0, depth=5.0, **kw)
        out[f"rad/{name}.step"] = Path(p).read_bytes()
    return out


def study(client, sid) -> dict[str, Any]:
    r = api(client, "GET", f"/doe/studies/{sid}")
    assert r.status_code == 200, r.text
    return r.json()


def create(client, entry_ids, shapes) -> dict[str, Any]:
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "compare", "entry_ids": entry_ids,
                                                  "shapes": shapes, "props": PROPS, "title": "④ E2E"})
    assert r.status_code == 201, r.text
    return r.json()


def test_compare_e2e_ranking(client, engine, worker, esl_root, inputs_root, exe, tmp_path, settings_dict):
    s1 = make_s1(engine, esl_root, inputs_root, kinds=(("bend", 2.0), ("twist", 1.5)))
    files = steps(tmp_path, [("flat", 0, {}), ("bead1", 1, {}), ("bead2", 2, {})])
    uid = upload_files(client, files)
    up_root = Path(settings_dict["storage"]["upload_root"])
    up_before, in_before = tree(up_root), tree(inputs_root)
    names = {"rad/flat.step": "기준 평판", "rad/bead1.step": "비드 1안", "rad/bead2.step": "비드 2안"}
    s = create(client, s1["entry_ids"], [{"upload_id": uid, "rel": r, "name": n, "reference": r == "rad/flat.step"}
                                         for r, n in names.items()])
    sid = s["id"]
    n_ver = len(calls(exe, "version"))
    j = run_job(client, worker, s["job"]["id"])
    assert [(x["step_key"], x["state"]) for x in j["steps"]] == [
        ("BD_INPUT", "SUCCEEDED"), ("BD_MESH0", "SUCCEEDED"), ("BD_GEOM", "SKIPPED"), ("BD_LOADS", "SUCCEEDED"),
        ("BD_PREP_REGISTER", "SUCCEEDED")]
    g = study(client, sid)
    assert g["phase"] == "READY" and g["prep"]["n_shapes"] == 3 and g["prep"]["n_ready"] == 3 and g["prep"]["failed"] == []
    assert g["prep"]["reference_source"] == "step" and g["prep"]["paicad_version"] is None
    for x in g["prep"]["shapes"]:
        assert x["status"] == "READY" and x["n_elems"] > 1000 and 0.9 <= x["quad_ratio"] <= 1.0
        assert set(x["quality"]) >= {"fail_elems", "fail_ratio", "warn_elems"}
    log = client.get(f"{API}/jobs/{s['job']['id']}/log", params={"step": 2}, headers=R).text
    assert "[d002 비드 2안] mesh 6 mm" in log and "OCC 정리 1" in log
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"]})
    assert r.status_code == 202, r.text
    j = run_job(client, worker, r.json()["job"]["id"])
    assert [x["step_key"] for x in j["steps"]] == ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"]
    assert j["progress_pct"] == 100.0
    log = client.get(f"{API}/jobs/{j['id']}/log", params={"step": 2}, headers=R).text
    assert "대상 형상 2개" in log and "[d001 비드 1안]" in log and "C_max" in log
    # paicad 미호출(V-SC-7): heartbeat 의 version 외 0
    assert len(calls(exe, "version")) == n_ver and len(calls(exe)) == n_ver
    res = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert res["scenario"] == "compare" and res["sensitivity"] is None and res["sensitivity_reason"] == "COMPARE_NO_PARAMS"
    rk = res["ranking"]
    assert [x["id"] for x in rk] == ["d002", "d001"] and rk[0]["score"] < rk[1]["score"] < 1.0
    assert [x["shape"]["name"] for x in rk] == ["비드 2안", "비드 1안"] and res["baseline"]["shape"]["name"] == "기준 평판"
    assert all(x["improvement"] > 0 and x.get("worst_ratio") is not None and "pareto" in x for x in rk)
    pe = api(client, "GET", f"/doe/studies/{sid}/results/per-esl").json()
    assert {d["id"]: d["name"] for d in pe["designs"]} == {"d001": "비드 1안", "d002": "비드 2안"}
    assert all(len(d["per_esl"]) == 2 and all("ratio" in p for p in d["per_esl"]) for d in pe["designs"])
    rels = {f["rel"] for f in api(client, "GET", f"/doe/studies/{sid}/files").json()}
    for did in ("d000", "d001", "d002"):
        assert f"best/{did}/ch_r.rad" in rels and f"best/{did}/ch_r.fem" in rels
    assert {"report.html", "post/ranking.csv", "prep/compare.json", "prep/shapes.json"} <= rels
    rep = client.get(f"{API}/doe/studies/{sid}/report", headers=R)
    assert rep.status_code == 200 and "비드 2안" in rep.text and "④ 형상 직접 비교" in rep.text
    m = api(client, "GET", f"/doe/studies/{sid}/view3d/d002/manifest.json")
    assert m.status_code == 200, m.text
    assert tree(up_root) == up_before and tree(inputs_root) == in_before            # 업로드·Case 폴더 불변


def test_compare_failures_and_case_reference(client, engine, worker, esl_root, inputs_root, exe, tmp_path):
    s1 = make_s1(engine, esl_root, inputs_root, kinds=(("bend", 2.0), ("twist", 1.5)))
    files = steps(tmp_path, [("bead1", 1, {}), ("bead2", 2, {})])
    files["rad/junk.step"] = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    uid = upload_files(client, files)
    # 기준 미지정(Case 메시) + 형상 1개 메시 실패 → 나머지 진행
    s = create(client, s1["entry_ids"], [{"upload_id": uid, "rel": "rad/bead1.step", "name": "B1"},
                                         {"upload_id": uid, "rel": "rad/junk.step", "name": "망가진 STEP"},
                                         {"upload_id": uid, "rel": "rad/bead2.step", "name": "B2"}])
    run_job(client, worker, s["job"]["id"])
    g = study(client, s["id"])
    st = {x["id"]: x for x in g["prep"]["shapes"]}
    assert g["prep"]["reference_source"] == "case" and st["d000"]["name"] == "Case 메시" and st["d000"]["status"] == "READY"
    assert st["d002"]["status"] == "FAILED_MESH" and st["d002"]["code"] == "MESH_FAILED"
    assert g["prep"]["failed"] == [{"id": "d002", "status": "FAILED_MESH", "code": "MESH_FAILED"}]
    assert any(w["code"] == "COMPARE_REF_CASE_MESH" for w in g["prep"]["warnings"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/run", json={"version": g["version"]})
    run_job(client, worker, r.json()["job"]["id"])
    res = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
    assert res["reference_source"] == "case" and res["n_failed"]["mesh"] == 1
    assert {x["id"] for x in res["ranking"]} == {"d001", "d003"} and res["baseline"]["shape"]["source"] == "case"
    assert res["excluded"][0]["id"] == "d002" and res["excluded"][0]["shape"]["name"] == "망가진 STEP"
    assert any(w["code"] == "COMPARE_REF_CASE_MESH" for w in res["warnings"])
    # 기준 STEP 메시 실패 → 준비 작업 실패(phase 파생 FAILED), 재시도도 같은 실패
    s2 = create(client, s1["entry_ids"], [{"upload_id": uid, "rel": "rad/junk.step", "name": "기준(망가짐)", "reference": True},
                                          {"upload_id": uid, "rel": "rad/bead1.step", "name": "B1"}])
    j = run_job(client, worker, s2["job"]["id"], expect="FAILED")
    assert j["failure_code"] == "MESH_FAILED" and study(client, s2["id"])["phase"] == "FAILED"
    assert [x["state"] for x in j["steps"]][:2] == ["SUCCEEDED", "FAILED"]
    assert len([c for c in calls(exe) if c["cmd"] != "version"]) == 0
