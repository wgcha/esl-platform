"""P2 플랫폼 E2E(계약 esl_p2_library.md §11): 코어 합성 라이브러리 Case(tests/library/synth_lib.py) 3개를 API 만으로
①~⑤ → CASE_REPORT 자동 큐·보고서(CSP) → 겹쳐보기 field(다운샘플) → 라이브러리 등록 → LIB_ANALYZE(대상 있음/없음)
→ 요약·보고서·덱 다운로드. 입력 폴더·Case 폴더는 등록·분석으로 바뀌지 않는다.
LIB_ANALYZE 취소(자식 프로세스 종료)·재시도.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import threading

import pytest
from esl_test_support import API, REPO, H, create_case, make_settings_dict, wait_for
from p2_support import seed_entry, seed_run

sys.path.insert(0, str(REPO / "tests" / "library"))
import synth_lib

W = H("tok-power", True)
R = H("tok-power")
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
# (모델, 배율, nx, ny, 하중 패턴, orient)
SPECS = [("50QX10A", 1.0, 24, 16, "A", "Corner146"), ("60QX10A", 1.2, 30, 20, "B", "Edge34"),
         ("50QX10A", 1.0, 30, 20, "A", "Face3")]


@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path, report={"auto": True}, ui={"max_preview_points": 200})


def _snapshot(d):
    out = {}
    for base, _, files in os.walk(d):
        for f in files:
            p = os.path.join(base, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job_id, lane="SLOT"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job_id}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _case_through_validate(client, worker, inputs_root, k):
    model, sc, nx, ny, pat, ori = SPECS[k]
    dt = {"C": "Corner", "E": "Edge", "F": "Face"}[ori[0]]
    h3d = f"F:/Hyper_work/VD_26y/{model}/{model}_v001_261019/FREE/{k + 1:02d}_{dt}_Drop_1st_Scene{k + 1}_{ori}_comp.h3d"
    c = synth_lib.build(str(inputs_root / f"lib{k}"), h3d, sc, nx, ny, pat, 1.0)
    r = create_case(client, {"rad": c["rad"], "csv": c["csv"]}, folder=f"lib{k}", title=f"lib{k}")
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["h3d_path"] == h3d
    _run(client, worker, _job(client, cid, "CASE_EXTRACT")["id"])
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]},
                       headers=W).status_code == 201
    _run(client, worker, _job(client, cid, "ESL_SOLVE")["id"])
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    vj = _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": case["current_esl_run_id"]})["id"])
    return cid, case["current_esl_run_id"], vj


def test_p2_e2e_register_analyze_report_deck(client, worker_factory, inputs_root, esl_root):
    worker = worker_factory()
    cases = []
    for k in range(len(SPECS)):
        cid, rid, vj = _case_through_validate(client, worker, inputs_root, k)
        cases.append({"id": cid, "run_id": rid, "dir": os.path.join(str(esl_root), f"lib{k}")})
        # VALIDATE 성공 → CASE_REPORT(LIGHT) 자동 큐
        rj = vj["result"]["report_job_id"]
        rep = client.get(f"{API}/jobs/{rj}", headers=R).json()
        assert rep["job_type"] == "CASE_REPORT" and rep["lane"] == "LIGHT" and rep["state"] == "QUEUED"
        assert rep["params"]["auto"] is True and rep["params"]["validation_id"]
        _run(client, worker, rj, lane="LIGHT")
        cases[-1]["validation_id"] = rep["params"]["validation_id"]
    c0 = cases[0]
    inputs_before = _snapshot(str(inputs_root))

    # Case 보고서(CSP, 자체 완결)
    r = client.get(f"{API}/cases/{c0['id']}/report", headers=R)
    assert r.status_code == 200 and r.headers["content-security-policy"] == CSP
    assert r.text.lstrip().lower().startswith("<!doctype html") and not re.search(r"(src|href)=\"https?://", r.text)
    with open(os.path.join(c0["dir"], "07_report", "report.html"), encoding="utf-8") as fh:
        assert fh.read() == r.text
    arts = {a["rel"]: a for a in client.get(f"{API}/cases/{c0['id']}/artifacts", headers=R).json()}
    assert arts["07_report/report.html"]["kind"] == "REPORT"

    # 검증: field 요약 + 겹쳐보기 API(다운샘플 ≤ 200) + 단면선
    v = client.get(f"{API}/validations/{c0['validation_id']}", headers=R).json()
    assert v["verdict"] == "PASS" and v["field"]["n_valid"] > 0 and v["field"]["max"]["abs_err_pct"] is not None
    f = client.get(f"{API}/validations/{v['id']}/field", params={"layer": "err"}, headers=R).json()
    assert f["n_total"] == v["field"]["n_elems"] > 200 and f["decimated"] and f["n_returned"] <= 200
    assert os.path.isfile(os.path.join(c0["dir"], "runs", c0["run_id"], "05_val", "compare_field.npz"))
    sec = client.get(f"{API}/validations/{v['id']}/section", params={"axis": "xi"}, headers=R).json()
    assert sec["n_elems"] > 0 and len(sec["s"]) == len(sec["w_rad"]) == len(sec["w_esl"]) > 2

    # 라이브러리 등록(run 스냅샷 고정, Case 폴더 읽기만)
    case_before = [_snapshot(c["dir"]) for c in cases]
    entries = []
    for c in cases:
        r = client.post(f"{API}/library/entries", json={"esl_run_id": c["run_id"], "note": "합성"}, headers=W)
        assert r.status_code == 201, r.text
        entries.append(r.json())
    assert [_snapshot(c["dir"]) for c in cases] == case_before
    e0 = entries[0]
    assert (e0["model"]["name"], e0["model"]["inch"], e0["model"]["version"]) == ("50QX10A", 50, "v001")
    assert (e0["scene"]["drop_class"], e0["scene"]["orient"], e0["scene"]["scenario"], e0["scene"]["scene_no"]) == \
        ("Corner", "146", "FREE", 1)
    assert e0["quality"]["verdict"] == "PASS" and e0["quality"]["field_max_err_pct"] is not None
    assert e0["validation_id"] == c0["validation_id"] and e0["status"] == "ACTIVE" and e0["note"] == "합성"
    assert e0["summary"]["grid"]["nx"] == 24 and e0["summary"]["grid"]["ny"] == 14 and e0["summary"]["mesh_sha256"]
    edir = os.path.join(str(esl_root), *e0["dir_rel"].split("/"))
    assert sorted(os.listdir(edir)) == ["entry.json", "raw.npz", "summary.npz"]
    assert _sha(os.path.join(edir, "summary.npz")) == e0["sha256"]
    assert entries[1]["scene"]["drop_class"] == "Edge" and entries[1]["model"]["inch"] == 60
    r = client.post(f"{API}/library/entries", json={"esl_run_id": c0["run_id"]}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ENTRY_EXISTS"

    # 종합분석(대상 = 0번, 대표 2개) → 덱 + 보고서
    r = client.post(f"{API}/library/analyses", json={"project_id": "p-1", "title": "합성 분석",
                                                     "target_entry_id": e0["id"],
                                                     "options": {"n_representative": 2, "objective": "minmax"}},
                    headers=W)
    assert r.status_code == 201, r.text
    a = r.json()
    _run(client, worker, a["job"]["id"])
    a = client.get(f"{API}/library/analyses/{a['id']}", headers=R).json()
    assert a["status"] == "SUCCEEDED" and a["n_entries"] == 3
    res = a["result"]
    assert res["n_cases"] == 3 and res["target"]["entry_id"] == e0["id"] and len(res["load_cases"]) == 2
    reps = {lc["entry_id"] for lc in res["load_cases"]}
    pat = {e["id"]: SPECS[k][4] for k, e in enumerate(entries)}
    assert {pat[x] for x in reps} == {"A", "B"}                   # 두 하중 패턴이 각각 대표됨
    assert res["optdeck"]["n_subcases"] == 2 and res["optdeck"]["objective"] == "minmax"
    assert res["mapping"]["n_self"] >= 1 and res["mapping"]["conservation_rel_max"] < 1e-6
    assert a["report_rel"] == f"_analysis/{a['id']}/report.html" and a["optdeck_rel"] == f"_analysis/{a['id']}/opt"
    adir = a["folder_path"]
    for n in ("analysis.json", "mapped_loads.npz", "envelope.csv", "representatives.csv", "report.html"):
        assert os.path.isfile(os.path.join(adir, n)), n
    rp = client.get(f"{API}/library/analyses/{a['id']}/report", headers=H("tok-general"))
    assert rp.status_code == 200 and rp.headers["content-security-policy"] == CSP
    assert not re.search(r"(src|href)=\"https?://", rp.text) and e0["id"] in rp.text
    rd = client.get(f"{API}/library/analyses/{a['id']}/report", params={"download": 1}, headers=R)
    assert rd.headers["content-disposition"].startswith("attachment;")
    files = client.get(f"{API}/library/analyses/{a['id']}/files", headers=R).json()
    rels = {x["rel"]: x for x in files}
    assert files[0]["rel"] == "report.html" and rels["opt/esl_bead.fem"]["kind"] == "optdeck"
    for n in ("opt/esl_loads.inc", "opt/run_optistruct.bat", "opt/README.txt", "opt/optdeck.json"):
        assert n in rels, n
    dl = client.get(f"{API}/library/analyses/{a['id']}/download", params={"rel": "opt/esl_bead.fem"}, headers=R)
    assert dl.status_code == 200
    with open(os.path.join(adir, "opt", "esl_bead.fem"), "rb") as fh:
        deck = fh.read()
    assert dl.content == deck and b"DTPG" in deck
    lg = client.get(f"{API}/jobs/{a['job']['id']}/log", params={"step": 1}, headers=R).json()
    assert lg["eof"] and any("[lib_analyze]" in ln for ln in lg["lines"])

    # 대상 없는 분석(정규화 격자 통계): OPTDECK step SKIPPED, 덱 없음
    r = client.post(f"{API}/library/analyses", json={"project_id": "p-1", "options": {"n_representative": 2}},
                    headers=W)
    assert r.status_code == 201, r.text
    j = _run(client, worker, r.json()["job"]["id"])
    assert [s["state"] for s in j["steps"]] == ["SUCCEEDED", "SKIPPED", "SUCCEEDED", "SUCCEEDED"]
    a2 = client.get(f"{API}/library/analyses/{r.json()['id']}", headers=R).json()
    assert a2["result"]["target"] is None and a2["optdeck_rel"] is None and a2["result"]["optdeck"] is None
    assert not any(x["kind"] == "optdeck" for x in client.get(f"{API}/library/analyses/{a2['id']}/files",
                                                               headers=R).json())
    # retire 후 분석 대상에서 빠짐, 재등록 가능
    assert client.post(f"{API}/library/entries/{entries[2]['id']}/retire", json={"reason": "정정"},
                       headers=W).status_code == 200
    r = client.post(f"{API}/library/entries", json={"esl_run_id": cases[2]["run_id"]}, headers=W)
    assert r.status_code == 201 and r.json()["id"] != entries[2]["id"]
    # 입력 폴더 불변
    assert _snapshot(str(inputs_root)) == inputs_before


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return "zombie" not in fh.read()
    except OSError:
        return False


def test_lib_analyze_cancel_and_retry(client, engine, mini_inputs, worker_factory, esl_root):
    cid = create_case(client, mini_inputs).json()["id"]
    e = [seed_entry(engine, cid, seed_run(engine, cid)["run_id"], esl_root=str(esl_root)) for _ in range(2)]
    r = client.post(f"{API}/library/analyses", json={"project_id": "p-1", "target_entry_id": e[0]}, headers=W)
    assert r.status_code == 201, r.text
    a = r.json()
    job = a["job"]
    worker = worker_factory(core_target="slow_core:run")
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("state", worker.run_once("SLOT")))
    t.start()
    pid_path = os.path.join(str(esl_root), "_analysis", a["id"], "logs", job["id"], "slow_core.pid")
    wait_for(lambda: os.path.isfile(pid_path) and open(pid_path).read().strip())
    pid = int(open(pid_path).read())
    assert _alive(pid)
    cur = client.get(f"{API}/library/analyses/{a['id']}", headers=R).json()
    assert cur["status"] == "RUNNING" and cur["job"]["steps"][0]["state"] == "RUNNING"
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=H("tok-power2", True))       # 다른 사용자
    assert r.status_code == 403
    r = client.post(f"{API}/jobs/{job['id']}/cancel", headers=W)
    assert r.status_code == 200 and r.json()["cancel_requested"] is True
    t.join(30)
    assert not t.is_alive() and out["state"] == "CANCELED"
    assert not _alive(pid)
    cur = client.get(f"{API}/library/analyses/{a['id']}", headers=R).json()
    assert cur["status"] == "CANCELED" and [s["state"] for s in cur["job"]["steps"]] == ["CANCELED"] * 4
    lg = client.get(f"{API}/jobs/{job['id']}/log", params={"step": 1}, headers=R).json()
    assert any("slow_core" in ln for ln in lg["lines"])
    # 슬롯 해제 → 재시도 작업이 큐에 들어가고 분석의 현재 작업이 바뀜
    nr = client.post(f"{API}/jobs/{job['id']}/retry", headers=W)
    assert nr.status_code == 201 and nr.json()["retry_of_job_id"] == job["id"]
    cur = client.get(f"{API}/library/analyses/{a['id']}", headers=R).json()
    assert cur["job_id"] == nr.json()["id"] and cur["status"] == "QUEUED"
    # 항목 폴더가 사라지면 FAILED PREREQUISITE_MISSING(lease 만료 대기 없이)
    import shutil

    shutil.rmtree(os.path.join(str(esl_root), "_library", "entries", e[1]))
    assert worker_factory().run_once("SLOT") == "FAILED"
    j = client.get(f"{API}/jobs/{nr.json()['id']}", headers=R).json()
    assert j["failure_code"] == "PREREQUISITE_MISSING"
