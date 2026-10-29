"""v0.10.0 라이브러리 다중 내보내기 워커(계약 esl_menu_restructure.md §6): 코어 합성 라이브러리 Case 3개(같은 모델 2·다른 모델 1)를
API 만으로 ① → ② t* 확정(자동 지지) → ③ → ④ PASS → 등록(4항목: 같은 Case 2개) → POST /library/exports → LIGHT 작업 실행.

V-MR-6·V-MR-7: Case 별 작업 1개(같은 Case 항목은 items 2개), Case 폴더 쓰기 0(실행 전후 트리 동일), 로그 _exports/<batch>/logs/,
일부 실패 → SUCCEEDED + 경고, 전부 실패 → FAILED EXPORT_ALL_FAILED. V-MR-8: 묶음 상태. V-MR-9: zip. V-MR-10: 같은 모델 ID
범위 비겹침·연속, 다른 모델 독립, 다른 Case 작업 간 순서 대기·EXPORT_ORDER_TIMEOUT.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile

import pytest
from esl_test_support import API, REPO, H, create_case, make_settings_dict

sys.path.insert(0, str(REPO / "tests" / "library"))
import synth_lib  # noqa: E402

W = H("tok-power", True)
R = H("tok-power")
# (모델, 배율, nx, ny, 패턴, orient) — 0·1 = 같은 메시(같은 topo_sha256), 2 = 다른 모델
SPECS = [("50QX10A", 1.0, 12, 8, "A", "Corner146"), ("50QX10A", 1.0, 12, 8, "B", "Edge34"),
         ("60QX10A", 1.2, 14, 10, "A", "Face3")]


@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path, library_export={"wait_s": 1}, ui={"library_export_enabled": True})


def _run(client, worker, job_id, lane="SLOT", want="SUCCEEDED"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job_id}", headers=R).json()
    assert st == want and j["state"] == want, (st, j["failure_code"], j["failure_message"])
    return j


def _job(client, cid, jt, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": jt, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _esl_validate_register(client, worker, cid):
    _run(client, worker, _job(client, cid, "ESL_SOLVE")["id"])
    rid = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": rid})["id"])
    r = client.post(f"{API}/library/entries", json={"esl_run_id": rid}, headers=W)
    assert r.status_code == 201, r.text
    assert r.json()["eligible"] is True and r.json()["quality"]["status"] == "PASS"
    return r.json()


def _case(client, worker, inputs_root, k):
    model, sc, nx, ny, pat, ori = SPECS[k]
    dt = {"C": "Corner", "E": "Edge", "F": "Face"}[ori[0]]
    h3d = f"F:/Hyper_work/VD_26y/{model}/{model}_v001_261019/FREE/{k + 1:02d}_{dt}_Drop_1st_Scene{k + 1}_{ori}_comp.h3d"
    c = synth_lib.build(str(inputs_root / f"lx{k}"), h3d, sc, nx, ny, pat, 1.0)
    r = create_case(client, {"rad": c["rad"], "csv": c["csv"]}, folder=f"lx{k}", title=f"lx{k}")
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT")["id"])
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    sel = client.get(f"{API}/cases/{cid}/tstar", headers=R).json()["selected"]
    r = client.put(f"{API}/cases/{cid}/tstar", json={"version": case["version"], "metric": sel["metric"],
                                                    "frame_index": sel["frame_index"]}, headers=W)
    assert r.status_code == 200 and r.json()["tstar"]["support_auto"]["status"] == "OK", r.text
    return cid


def _tree(d):
    out = {}
    for base, _, names in os.walk(d):
        for n in names:
            p = os.path.join(base, n)
            st = os.stat(p)
            out[os.path.relpath(p, d)] = (st.st_size, st.st_mtime_ns)
    return out


def test_library_export_worker(client, worker_factory, inputs_root, esl_root, engine):
    worker = worker_factory()
    cids = [_case(client, worker, inputs_root, k) for k in range(3)]
    a1 = _esl_validate_register(client, worker, cids[0])
    a2 = _esl_validate_register(client, worker, cids[0])           # 같은 Case 두 번째 ESL 결과
    b1 = _esl_validate_register(client, worker, cids[1])
    c1 = _esl_validate_register(client, worker, cids[2])
    assert a1["topo_sha256"] == a2["topo_sha256"] == b1["topo_sha256"] != c1["topo_sha256"]
    cdirs = [os.path.join(str(esl_root), f"lx{k}") for k in range(3)]
    before = [_tree(d) for d in cdirs]

    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1["id"], b1["id"], c1["id"],
                                                                                       a2["id"]],
                                                    "targets": ["radioss_inc", "fem", "csv"]}, headers=W)
    assert r.status_code == 202, r.text
    o = r.json()
    bid = o["batch_id"]
    assert len(o["jobs"]) == 3 and [j["case_id"] for j in o["jobs"]] == cids
    for j in o["jobs"]:
        _run(client, worker, j["job_id"], lane="LIGHT")
    g = client.get(f"{API}/library/exports/{bid}", headers=R).json()
    assert g["state"] == "SUCCEEDED" and [it["state"] for it in g["items"]] == ["DONE"] * 4, g
    rng = {it["entry_id"]: it["id_range"] for it in g["items"]}
    # 같은 모델(a1 → a2 → b1, Case 작업 순): 범위 겹침 없이 연속, 다른 모델(c1)은 독립(같은 시작)
    assert rng[a2["id"]][0] == rng[a1["id"]][1] + 1 and rng[b1["id"]][0] == rng[a2["id"]][1] + 1
    assert rng[c1["id"]][0] == rng[a1["id"]][0]
    labels = [it["label"] for it in g["items"]]
    names = {f["rel"].split("/")[1] for f in g["items"][0]["files"]}
    assert {"esl_cload.inc", "esl_bcs.inc", "esl_force.fem", "f_eq.csv", "u_rel.csv", "supports_321.csv",
            "reactions_321.csv", "validation.csv"} == names
    # Case 폴더 쓰기 0, 로그·출력 = _exports/<batch>/
    assert [_tree(d) for d in cdirs] == before
    bdir = os.path.join(str(esl_root), "_exports", bid)
    j0 = o["jobs"][0]["job_id"]
    assert os.path.isfile(os.path.join(bdir, "logs", j0, "step_01_EXPORT.log"))
    lg = client.get(f"{API}/jobs/{j0}/log", params={"step": 1}, headers=R).json()
    assert any("[export]" in ln for ln in lg["lines"]) and not any(str(esl_root) in ln for ln in lg["lines"])
    jr = client.get(f"{API}/jobs/{j0}", headers=R).json()
    reg = jr["result"]["registered"]
    assert reg["batch_id"] == bid and reg["n_items"] == 2 and [x["state"] for x in reg["items"]] == ["DONE", "DONE"]
    assert str(esl_root) not in json.dumps(jr)
    # Case ⑥ 상태·history 보존 영향 없음
    cs = client.get(f"{API}/cases/{cids[0]}", headers=R).json()
    assert cs["stage_status"]["6"]["state"] == "none" and not os.path.isdir(os.path.join(cdirs[0], "history"))
    h = client.get(f"{API}/history", params={"project_id": "p-1", "job_type": "EXPORT"}, headers=R).json()
    lib_rows = [x for x in h["items"] if x["id"] == j0]
    assert lib_rows and lib_rows[0]["summary"]["label"] == "내보내기(라이브러리)" and lib_rows[0]["summary"]["n_items"] == 2
    # zip
    z = client.get(f"{API}/library/exports/{bid}/bundle", headers=R)
    assert z.status_code == 200, z.text
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    nm = zf.namelist()
    assert nm[:2] == ["manifest.json", "README.txt"] and all(n.split("/")[0] in labels for n in nm[2:])
    assert f"{labels[0]}/esl_force.fem" in nm and not any(".." in n or n.startswith("/") for n in nm)
    man = json.loads(zf.read("manifest.json"))
    assert [i["entry_id"] for i in man["items"]] == [a1["id"], b1["id"], c1["id"], a2["id"]]
    with open(os.path.join(bdir, labels[0], "esl_force.fem"), "rb") as fh:
        assert zf.read(f"{labels[0]}/esl_force.fem") == fh.read()

    # 일부 실패(항목 폴더 raw.npz 없음) → 작업 SUCCEEDED + 경고, 묶음 PARTIAL
    raw = os.path.join(str(esl_root), *a2["dir_rel"].split("/"), "raw.npz")
    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1["id"], a2["id"]],
                                                    "targets": ["fem"], "options": {"id_policy": "independent"}},
                    headers=W)
    assert r.status_code == 202, r.text
    p2 = r.json()
    os.replace(raw, raw + ".off")
    try:
        jj = _run(client, worker, p2["jobs"][0]["job_id"], lane="LIGHT")
    finally:
        os.replace(raw + ".off", raw)
    assert any("ENTRY_FILES_MISSING" in str(w) for w in jj["warnings"])
    g = client.get(f"{API}/library/exports/{p2['batch_id']}", headers=R).json()
    assert g["state"] == "PARTIAL" and [it["state"] for it in g["items"]] == ["DONE", "FAILED"]
    assert g["items"][1]["error"]["code"] == "ENTRY_FILES_MISSING"

    # 다른 Case 작업의 앞 항목 결과를 기다리다 시간 초과(wait_s 1) → 전부 실패 → FAILED EXPORT_ALL_FAILED, 묶음 CANCELED
    r = client.post(f"{API}/library/exports", json={"project_id": "p-1", "entry_ids": [a1["id"], b1["id"]],
                                                    "targets": ["fem"]}, headers=W)
    assert r.status_code == 202, r.text
    p3 = r.json()
    cj = client.post(f"{API}/jobs/{p3['jobs'][0]['job_id']}/cancel", headers=W)
    assert cj.status_code == 200, cj.text
    if cj.json()["state"] != "CANCELED":
        worker.run_once("LIGHT")
    jb = _run(client, worker, p3["jobs"][1]["job_id"], lane="LIGHT", want="FAILED")
    assert jb["failure_code"] == "EXPORT_ALL_FAILED" and "EXPORT_ORDER_TIMEOUT" in jb["failure_message"]
    g = client.get(f"{API}/library/exports/{p3['batch_id']}", headers=R).json()
    assert g["state"] == "CANCELED" and g["items"][1]["error"]["code"] == "EXPORT_ORDER_TIMEOUT"
    lst = client.get(f"{API}/library/exports", params={"project_id": "p-1"}, headers=R).json()
    assert [b["batch_id"] for b in lst] == [p3["batch_id"], p2["batch_id"], bid]
    assert [_tree(d) for d in cdirs] == before


    # 통합 검증 지적 4f: 실패한 라이브러리 내보내기 재시도는 EXPORT 단계부터 — 앞 작업(취소) 재시도 → 뒤 작업 재시도 성공
    r1 = client.post(f"{API}/jobs/{p3['jobs'][0]['job_id']}/retry", headers=W)
    assert r1.status_code == 201, r1.text
    assert r1.json()["resume_from_step"] is None
    _run(client, worker, r1.json()["id"], lane="LIGHT")
    r2 = client.post(f"{API}/jobs/{p3['jobs'][1]['job_id']}/retry", headers=W)
    assert r2.status_code == 201, r2.text
    assert r2.json()["resume_from_step"] is None                       # 실패 step(EXP_REGISTER) 이 아니라 처음부터
    _run(client, worker, r2.json()["id"], lane="LIGHT")
    g = client.get(f"{API}/library/exports/{p3['batch_id']}", headers=R).json()
    assert g["state"] == "SUCCEEDED" and [it["state"] for it in g["items"]] == ["DONE", "DONE"], g
    ra, rb = (it["id_range"] for it in g["items"])
    assert rb[0] == ra[1] + 1                                          # 같은 모델 연속(재시도 후에도)
    assert os.path.isdir(os.path.join(str(esl_root), "_exports", p3["batch_id"], "_backup"))   # 실패 결과는 보존
    assert [_tree(d) for d in cdirs] == before
