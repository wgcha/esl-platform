"""V-CI-W1: 워커 H3D_EXTRACT 누적 씬(계약 esl_cumulative_input.md §6.5·§15 Worker).

- 누적 씬(rad 가 상태 파일 #include): <esl_root>/_h3d/<Case>/prev.csv(대상 파트 E 행) + request 키 3개
  (prev_file·frame0_pass·cum_min_incr), 등록 extract_summary.cumulative, 재추출 시 이전 prev.csv 는 _backup.
- 비누적: request.txt 는 v0.7.2 와 같은 내용(키 추가 없음), prev.csv 없음.
- include 검사(input_roots)는 상태 파일에도 그대로.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from esl_test_support import API, H
from h3d_support import write_fake_hw, write_h3d

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "cumulative"))
import synth_cum  # noqa: E402

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트")


@pytest.fixture()
def settings_dict(tmp_path):
    from esl_test_support import make_settings_dict
    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(write_fake_hw(tmp_path)), "max_concurrent_hw": 1}
    return d


def _case(client, rad, folder):
    h3d = write_h3d(Path(rad).parent / f"{folder}.h3d")
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": folder, "title": folder,
                                          "rad_path": rad, "h3d_path": str(h3d)}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _extract(client, cid):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def test_w1_cumulative_h3d_extract_writes_prev_and_request_keys(client, inputs_root, worker_factory, esl_root,
                                                                 monkeypatch):
    c = synth_cum.build(str(inputs_root / "cum"))
    monkeypatch.setenv("FAKE_HW_SRC", c["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    case = _case(client, c["rad"], "cum01")
    job = _extract(client, case["id"])
    assert worker_factory().run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    work = Path(esl_root) / "_h3d" / "cum01"
    req = (work / "request.txt").read_text()
    prev = work / "prev.csv"
    assert f"prev_file\t{prev.as_posix()}" in req and "frame0_pass\t1" in req and "cum_min_incr\t1e-05" in req
    rows = prev.read_text().strip().split("\n")
    assert rows[0] == "elem_id,prev_epsp,prev_eq" and len(rows) == 1 + c["elem_id"].size   # = parse_rad E
    assert not (work / "raw" / "prev.csv").exists()                                         # raw 출력 폴더 밖
    cs = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    cu = cs["extract_summary"]["cumulative"]
    assert cu["enabled"] is True and cu["eq_mode"] == "incremental" and cu["epsp_mode"] == "cumulative"
    assert [f["name"] for f in cu["files"]] == [c["str"], c["sta"]]
    t = client.get(f"{API}/cases/{case['id']}/tstar", headers=R).json()
    assert t["selected"]["frame_index"] == 3
    # 입력 지문 = include(상태 파일 포함)
    assert {os.path.basename(i["path"]) for i in cs["input_fingerprint"]["includes"]} == {c["str"], c["sta"]}
    # 재추출: 이전 prev.csv → _backup
    job2 = _extract(client, case["id"])
    assert worker_factory().run_once("SLOT") == "SUCCEEDED", job2
    assert list((work / "_backup").glob("*/prev.csv")) and prev.is_file()


def test_w1_noncumulative_request_unchanged(client, synth_inputs, worker_factory, esl_root, monkeypatch):
    monkeypatch.setenv("FAKE_HW_SRC", synth_inputs["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    case = _case(client, synth_inputs["rad"], "plain01")
    _extract(client, case["id"])
    assert worker_factory().run_once("SLOT") == "SUCCEEDED"
    work = Path(esl_root) / "_h3d" / "plain01"
    req = (work / "request.txt").read_text()
    assert req.startswith("# ESL 서버 h3d 추출 요청(워커가 작성)\npart_title\tchassis rear\nhot_k\t200\ntop_n\t5\n")
    # v0.12.1: 변형률 결과 대체 키(strain_sources·이름 후보)만 추가 — 누적 씬 키는 없음
    keys = [ln.split("\t", 1)[0] for ln in req.splitlines()[4:]]
    assert keys[0] == "strain_sources" and not {"prev_file", "frame0_pass", "cum_min_incr"} & set(keys)
    assert not (work / "prev.csv").exists()
    cs = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    assert "cumulative" not in cs["extract_summary"]


def test_w1_state_include_outside_input_roots_rejected(client, inputs_root, tmp_path):
    c = synth_cum.build(str(inputs_root / "cum2"))
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    os.replace(os.path.join(c["din"], c["sta"]), outside / c["sta"])
    txt = Path(c["rad"]).read_text().replace(f"#include {c['sta']}", f"#include {(outside / c['sta']).as_posix()}")
    Path(c["rad"]).write_text(txt)
    h3d = write_h3d(Path(c["rad"]).parent / "cum2.h3d")
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": "cum02", "title": "x",
                                          "rad_path": c["rad"], "h3d_path": str(h3d)}, headers=W)
    if r.status_code == 201:
        r = client.post(f"{API}/cases/{r.json()['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}},
                        headers=W)
    assert r.status_code == 422 and "PATH_OUTSIDE_ROOT" in r.text and c["sta"] in r.text
