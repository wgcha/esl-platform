"""V-H-9(워커 쪽): EXPORT·CASE_REPORT 성공 때 <case>/history/<job_id>/ 보존(H-5) — 실제 코어 합성 Case 로 ①~⑥·보고서.
이후 내보내기가 06_export 를 덮어써도 이전 작업의 파일을 받을 수 있고, 복사 실패는 작업을 실패시키지 않는다(warning)."""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from esl_test_support import API, H, create_case

W = H("tok-power", True)
R = H("tok-power")


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job, lane="SLOT"):
    st = worker.run_once(lane)
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _validated_case(client, worker, synth):
    case = create_case(client, synth).json()
    cid = case["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    run_id = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": run_id}))
    return cid, run_id


def _read_dir(d):
    return {n: open(os.path.join(d, n), "rb").read() for n in sorted(os.listdir(d))}


def test_export_and_report_archived_per_job(client, synth_inputs, worker_factory, esl_root):
    worker = worker_factory()
    cid, run_id = _validated_case(client, worker, synth_inputs)
    cdir = os.path.join(str(esl_root), "case01")
    e1 = _run(client, worker, _job(client, cid, "EXPORT", {"esl_run_id": run_id, "targets": ["radioss_inc", "csv"]}),
              "LIGHT")
    h1 = os.path.join(cdir, "history", e1["id"])
    assert os.path.isdir(os.path.join(h1, "06_export")) and not os.path.exists(h1 + ".tmp")
    first = _read_dir(os.path.join(h1, "06_export"))
    assert first == _read_dir(os.path.join(cdir, "06_export")) and "esl_cload.inc" in first and "f_eq.csv" in first
    assert not any(w.startswith("HISTORY_ARCHIVE_FAILED") for w in e1["warnings"]), e1["warnings"]
    # 보존 파일 API
    fl = client.get(f"{API}/jobs/{e1['id']}/files", headers=R).json()
    assert [f["name"] for f in fl] == sorted(first) and all(f["downloadable"] for f in fl)
    # 두 번째 내보내기(다른 대상)가 06_export 를 덮어쓴다 → 첫 작업 파일은 그대로 받을 수 있다
    e2 = _run(client, worker, _job(client, cid, "EXPORT", {"esl_run_id": run_id, "targets": ["fem"]}), "LIGHT")
    cur = _read_dir(os.path.join(cdir, "06_export"))
    assert set(cur) == {"esl_force.fem"} and cur != first
    assert _read_dir(os.path.join(cdir, "history", e1["id"], "06_export")) == first
    assert [f["name"] for f in client.get(f"{API}/jobs/{e2['id']}/files", headers=R).json()] == ["esl_force.fem"]
    d = client.get(f"{API}/jobs/{e1['id']}/files/esl_cload.inc/download", headers=R)
    assert d.status_code == 200 and d.content == first["esl_cload.inc"]
    assert client.get(f"{API}/jobs/{e1['id']}/files/esl_force.fem/download", headers=R).status_code == 404
    # review: 첫 작업은 과거 + 파일 있음(full), 둘째는 현재
    rv1 = client.get(f"{API}/jobs/{e1['id']}/review", headers=R).json()["result"]
    rv2 = client.get(f"{API}/jobs/{e2['id']}/review", headers=R).json()["result"]
    assert rv1["state"] == "past" and rv1["availability"] == "full" and rv2["state"] == "current"
    assert {f["name"] for f in rv1["past"]["files"]} == set(first) and rv1["past"]["targets"] == ["radioss_inc", "csv"]
    assert {d["key"] for d in rv1["diff"]} >= {"targets", "files"}
    # history 는 artifacts·bundle 에 들어가지 않는다
    arts = client.get(f"{API}/cases/{cid}/artifacts", headers=R).json()
    assert not any(a["rel"].startswith("history/") for a in arts)
    z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/cases/{cid}/bundle", headers=R).content))
    assert not any("/history/" in n for n in z.namelist())
    # CASE_REPORT
    r1 = _run(client, worker, _job(client, cid, "CASE_REPORT"), "LIGHT")
    hp = os.path.join(cdir, "history", r1["id"], "report.html")
    assert os.path.isfile(hp)
    with open(hp, "rb") as a, open(os.path.join(cdir, "07_report", "report.html"), "rb") as b:
        body1 = a.read()
        assert body1 == b.read()
    r2 = _run(client, worker, _job(client, cid, "CASE_REPORT"), "LIGHT")
    assert os.path.isfile(os.path.join(cdir, "history", r2["id"], "report.html"))
    rep = client.get(f"{API}/jobs/{r1['id']}/report", headers=R)
    assert rep.status_code == 200 and rep.content == body1
    assert "content-security-policy" in rep.headers
    assert client.get(f"{API}/jobs/{r1['id']}/review", headers=R).json()["result"]["availability"] == "full"
    # history 폴더명은 코어 출력 폴더와 겹치지 않는다
    core_dirs = {"01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report", "runs", "logs",
                 "_backup"}
    assert "history" not in core_dirs and "history" in os.listdir(cdir)
    # 이력 목록 요약(내보내기 한 줄)
    items = {i["id"]: i for i in client.get(f"{API}/history", params={"project_id": "p-1", "case_id": cid},
                                            headers=R).json()["items"]}
    assert items[e1["id"]]["summary"] == {"targets": ["radioss_inc", "csv"], "n_files": len(first)}
    assert items[e1["id"]]["result_state"] == "past" and items[e2["id"]]["result_state"] == "current"
    assert items[r2["id"]]["result_state"] == "current" and items[r1["id"]]["result_state"] == "past"


def test_archive_failure_keeps_job_succeeded_with_warning(client, synth_inputs, worker_factory, esl_root, monkeypatch):
    from esl_worker import register

    worker = worker_factory()
    cid, run_id = _validated_case(client, worker, synth_inputs)

    def boom(*a, **k):
        raise OSError("디스크가 가득 참")

    monkeypatch.setattr(register, "archive_history", boom)
    e = _run(client, worker, _job(client, cid, "EXPORT", {"esl_run_id": run_id, "targets": ["csv"]}), "LIGHT")
    assert any(w.startswith("HISTORY_ARCHIVE_FAILED") and "디스크가 가득 참" in w for w in e["warnings"]), e["warnings"]
    assert client.get(f"{API}/jobs/{e['id']}/files", headers=R).status_code == 404
    rv = client.get(f"{API}/jobs/{e['id']}/review", headers=R).json()
    assert rv["result"]["availability"] == "summary" and "파일 보존 안 됨" in rv["result"]["files_note"]
    assert any("HISTORY_ARCHIVE_FAILED" in w for w in rv["error"]["warnings"])
    # 코어 산출물·DB 등록은 정상(내보내기 파일 있음)
    assert os.path.isfile(os.path.join(str(esl_root), "case01", "06_export", "f_eq.csv"))
    assert not os.path.exists(os.path.join(str(esl_root), "case01", "history", e["id"]))


def test_archive_disabled_by_setting(client, synth_inputs, worker_factory, esl_root, app_ctx):
    object.__setattr__(app_ctx.settings.history, "archive_files", False)
    worker = worker_factory()
    cid, run_id = _validated_case(client, worker, synth_inputs)
    e = _run(client, worker, _job(client, cid, "EXPORT", {"esl_run_id": run_id, "targets": ["csv"]}), "LIGHT")
    assert not os.path.exists(os.path.join(str(esl_root), "case01", "history"))
    assert client.get(f"{API}/jobs/{e['id']}/files", headers=R).status_code == 404
    assert e["warnings"] == [] or not any("HISTORY" in w for w in e["warnings"])


# ---------------------------------------------------------------- archive_history 단위
def test_archive_history_unit(tmp_path):
    from esl_worker import register

    cdir = tmp_path / "case"
    exp = cdir / "06_export"
    exp.mkdir(parents=True)
    (exp / "a.inc").write_text("A")
    (exp / "b.csv").write_text("B")
    outside = tmp_path / "secret.txt"
    outside.write_text("S")
    os.symlink(outside, exp / "evil.csv")                  # 심링크는 복사하지 않는다
    assert register.archive_history(str(cdir), "EXPORT", "job-1") == 2
    dst = cdir / "history" / "job-1" / "06_export"
    assert sorted(os.listdir(dst)) == ["a.inc", "b.csv"] and not (cdir / "history" / "job-1.tmp").exists()
    assert register.archive_history(str(cdir), "EXPORT", "job-1") == 0          # 이미 있으면 그대로
    (exp / "a.inc").write_text("CHANGED")
    assert register.archive_history(str(cdir), "EXPORT", "job-1") == 0
    assert (dst / "a.inc").read_text() == "A"
    # 원본 없음 → 오류, 잔여 .tmp 없음
    with pytest.raises(OSError):
        register.archive_history(str(cdir), "CASE_REPORT", "job-2")
    assert not (cdir / "history" / "job-2.tmp").exists() and not (cdir / "history" / "job-2").exists()
    rep = cdir / "07_report"
    rep.mkdir()
    (rep / "report.html").write_text("<html/>")
    assert register.archive_history(str(cdir), "CASE_REPORT", "job-2") == 1
    assert (cdir / "history" / "job-2" / "report.html").read_text() == "<html/>"
    assert register.archive_history(str(cdir), "ESL_SOLVE", "job-3") == 0
    # 예전 .tmp 찌꺼기는 지우고 다시 만든다
    (cdir / "history" / "job-4.tmp").mkdir()
    (cdir / "history" / "job-4.tmp" / "junk").write_text("x")
    assert register.archive_history(str(cdir), "CASE_REPORT", "job-4") == 1
    assert sorted(os.listdir(cdir / "history" / "job-4")) == ["report.html"]
    # history 가 심링크면 거부
    cdir2 = tmp_path / "case2"
    (cdir2 / "06_export").mkdir(parents=True)
    (cdir2 / "06_export" / "a.inc").write_text("A")
    os.symlink(tmp_path / "elsewhere", cdir2 / "history")
    (tmp_path / "elsewhere").mkdir()
    with pytest.raises(OSError):
        register.archive_history(str(cdir2), "EXPORT", "job-1")
    assert os.listdir(tmp_path / "elsewhere") == []
