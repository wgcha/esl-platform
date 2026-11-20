"""v0.24.2 통합 시험(계약 esl_bforce_ondemand.md V-0242-BFD 통합 7) — 가짜 코어 없이 실제 A 함수(esl.io.bforce_*)와
실제 TCL(tclsh + hwmock, 가짜 hw 가 bf 전용 request 를 실제 esl_h3d_extract.tcl 로 처리).

덤프 방식 Case(strain_tensor, bforce 없음) → ③ ESL_SOLVE → 보충(hw 1회) → 01_extract/bforce.* 병합·등록
→ 04_esl 경계력 등급 contact, 내력 none(FINT 결과 유형 없음) → 같은 ESL 재실행 시 hw 호출 0.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
import synth_case
from esl_test_support import API, H, wait_for  # noqa: F401
from h3d_support import write_fake_hw, write_h3d, write_tcl_bf_env

W = H("tok-power", True)
R = H("tok-power")
TCLSH = os.environ.get("ESL_TCLSH") or shutil.which("tclsh") or shutil.which("tclsh8.6")
pytestmark = [pytest.mark.skipif(os.name == "nt", reason="가짜 hw 는 POSIX 실행 스크립트"),
              pytest.mark.skipif(TCLSH is None, reason="tclsh 없음")]


@pytest.fixture()
def fake_hw(tmp_path) -> Path:
    return write_fake_hw(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, fake_hw):
    from esl_test_support import make_settings_dict

    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(fake_hw), "max_concurrent_hw": 1}
    d["worker"]["slots"] = 2
    return d


@pytest.fixture()
def dump_inputs(inputs_root) -> dict:
    return synth_case.build(str(inputs_root), source="strain_tensor")


def _setup(client, worker, dump, monkeypatch, tmp_path, *, types=None, extra="", folder="case01"):
    env, vals = write_tcl_bf_env(tmp_path, dump, types=types, extra=extra)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FAKE_HW_SRC", dump["csv"])
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    h3d = write_h3d(Path(dump["rad"]).parent / f"{folder}_drop.h3d")
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": folder, "title": "dump", "rad_path": dump["rad"],
                                          "h3d_path": str(h3d)}, headers=W)
    assert r.status_code == 201, r.text
    case = r.json()
    j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    assert worker.run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{j['id']}", headers=R).json()
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]},
                       headers=W).status_code == 201
    return case, vals


def _esl(client, worker, case) -> dict:
    j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert j.status_code == 201, j.text
    worker.run_once("SLOT")
    return client.get(f"{API}/jobs/{j.json()['id']}", headers=R).json()


def _argvs(esl_root, folder="case01"):
    return sorted((Path(esl_root) / "_h3d" / folder / "bf_ondemand").glob("argv_*.json"))


def _summary(client, case) -> dict:
    """ESL 실행 forces(= 단계 요약 bforce·fint) — 화면·API 가 읽는 값(계약 §1.4 코어 요약 code)."""
    c = client.get(f"{API}/cases/{case['id']}", headers=R).json()
    runs = {r["id"]: r for r in client.get(f"{API}/cases/{case['id']}/esl-runs", headers=R).json()}
    return runs[c["current_esl_run_id"]]["forces"]


def _log(client, j, step=1):
    return client.get(f"{API}/jobs/{j['id']}/log", params={"step": step}, headers=R).json()["lines"]


def test_integration7_dump_fill_merge_reuse(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path, engine):
    from sqlalchemy import text

    w = worker_factory()
    case, vals = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    ext = Path(esl_root) / "case01" / "01_extract"
    assert not (ext / "bforce.json").exists()                      # 덤프 방식 추출 = 경계력 없음
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED", (j["failure_code"], j["failure_message"], _log(client, j))
    t = synth_case.T_STAR_FRAME
    # hw 1회, request = A 의 bf_only 키
    av = _argvs(esl_root)
    assert len(av) == 1
    req = (Path(esl_root) / "_h3d" / "case01" / "bf_ondemand" / "request.txt").read_text()
    assert "bf_only\t1\n" in req and f"bf_frames\t{t}\n" in req and "bf_on\t1\n" in req
    # 실제 TCL 출력(요청 프레임 행만) → 실제 병합
    raw = Path(esl_root) / "_h3d" / "case01" / "bf_ondemand" / "raw"
    done = json.loads((raw / "done.json").read_text())
    assert done["ok"] is True and done["mode"] == "bf_only" and done["frames"] == [t] and done["value_format"]
    assert sorted(p.name for p in raw.iterdir() if p.is_file()) == ["bf_acc.csv", "bf_cont.csv", "done.json", "progress.log"]
    bj = json.loads((ext / "bforce.json").read_text())
    assert bj["frames"] == [t] and bj["on"] is True and bj["fills"][0]["job_id"] == j["id"]
    assert bj["kinds"]["cont"]["type"] == "Contact Forces" and bj["kinds"]["acc"]["type"] == "Acceleration"
    assert bj["kinds"]["cont2"]["type"] is None and bj["kinds"]["fint"]["type"] is None
    with np.load(ext / "bforce.npz") as z:
        nid = np.load(ext / "model.npz")["node_id"]
        order = [int(n) for n in dump_inputs["node_id"]]
        idx = [order.index(int(n)) for n in nid]
        assert np.array_equal(z["cont"][0], vals["Contact Forces"][t][idx])           # %.17g 비트 보존
        assert np.array_equal(z["acc"][0], vals["Acceleration"][t][idx][:, :3])
    # 시도 기록·step outputs·result
    at = json.loads((ext / "bforce_ondemand.json").read_text())["attempts"]
    assert len(at) == 1 and at[0]["status"] == "ok" and at[0]["code"] is None and at[0]["job_id"] == j["id"]
    assert at[0]["kinds"]["cont"] == "Contact Forces" and at[0]["merge"]["added"] == [t]
    bf = j["result"]["bf_ondemand"]
    assert bf["status"] == "ok" and bf["added"] == [t] and bf["kinds"]["cont"] == "Contact Forces"
    with engine.connect() as c:
        o1 = c.execute(text("SELECT outputs FROM job_steps WHERE job_id = :j AND step_no = 1"), {"j": j["id"]}).scalar_one()
    assert o1["bf_ondemand"]["status"] == "ok"
    # 등급: 경계력 contact(CONT+ACC), 내력 none(FINT 없음) + 사유
    s = _summary(client, case)
    assert s["bforce"]["grade"] == "contact" and not s["bforce"].get("code"), s["bforce"]
    assert s["fint"]["grade"] == "none" and s["fint"]["reason"], s["fint"]
    assert (Path(esl_root) / "case01" / "04_esl" / "bforce.npz").is_file()
    assert not (Path(esl_root) / "case01" / "04_esl" / "fint.npz").exists()
    # 산출물 등록: 실제 bforce.* 가 이 ESL 작업으로 등록
    arts = client.get(f"{API}/cases/{case['id']}/artifacts", headers=R).json()
    arts = arts if isinstance(arts, list) else arts.get("items", [])
    by = {a.get("rel_path") or a.get("path"): a for a in arts}
    for name in ("bforce.npz", "bforce.json", "bforce_ondemand.json"):
        a = by.get(str(ext / name))
        assert a is not None and a["job_id"] == j["id"], (name, sorted(by))
    # 같은 ESL 재실행 = hw 호출 0, 요약 같음
    before = _summary(client, case)
    j2 = _esl(client, w, case)
    assert j2["state"] == "SUCCEEDED" and len(_argvs(esl_root)) == 1
    assert "bf_ondemand" not in (j2["result"] or {})
    assert any("있음 — 보충 안 함" in ln for ln in _log(client, j2))
    assert _summary(client, case)["bforce"]["grade"] == before["bforce"]["grade"] == "contact"
    # 병합 이전 파일이 없었으므로 백업 없음, 같은 프레임 재병합 없음
    assert not (Path(esl_root) / "case01" / "_backup").exists() or not list((Path(esl_root) / "case01" / "_backup").glob("*/01_extract/bforce.*"))


def test_integration_no_fint_types_then_no_types_skip(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    """h3d 에 경계력 유형이 하나도 없음 = 보충 ok(종류 전부 null) → 프레임 '있음' → 다음 ESL 호출 0, 등급 none 기존 사유."""
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path, types={"Displacement": ["X", "Y", "Z", "Mag"]})
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED", (j["failure_code"], j["failure_message"], _log(client, j))
    assert j["result"]["bf_ondemand"]["status"] == "ok"
    assert all(v is None for v in j["result"]["bf_ondemand"]["kinds"].values())
    s = _summary(client, case)
    assert s["bforce"]["grade"] == "none" and s["fint"]["grade"] == "none"
    j2 = _esl(client, w, case)
    assert len(_argvs(esl_root)) == 1 and j2["state"] == "SUCCEEDED"


def test_integration_hw_failures_real_tcl(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    """실제 TCL 실패(done.json ok false, mode bf_only) → HW_FAILED·BF_EXTRACT_FAILED·내력 같은 code, ESL 성공,
    다음 ESL 때 다시 시도. 라이선스 문구 → LICENSE."""
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path, extra="set ::mock::fail_at {hwi_GetSessionHandle}")
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED"
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "failed" and b["cause"] == "HW_FAILED", b
    raw = Path(esl_root) / "_h3d" / "case01" / "bf_ondemand" / "raw"
    dj = json.loads((raw / "done.json").read_text())
    assert dj["ok"] is False and dj["mode"] == "bf_only"
    s = _summary(client, case)
    assert s["bforce"]["code"] == "BF_EXTRACT_FAILED" and s["fint"]["code"] == "BF_EXTRACT_FAILED"
    assert s["bforce"]["reason"] == s["fint"]["reason"] and "HyperView 추출 실패" in s["bforce"]["reason"]
    assert not (Path(esl_root) / "case01" / "04_esl" / "bforce.npz").exists()
    assert sum("BF_EXTRACT_FAILED" in x for x in j["warnings"]) == 1
    # 실패는 다음 ESL 때 다시 시도(데이터 정상화 후 성공)
    (tmp_path / "tcl_bf_data.tcl").write_text((tmp_path / "tcl_bf_data.tcl").read_text().replace(
        "set ::mock::fail_at {hwi_GetSessionHandle}", "set ::mock::fail_at {}"))
    j2 = _esl(client, w, case)
    assert j2["result"]["bf_ondemand"]["status"] == "ok" and len(_argvs(esl_root)) == 2
    assert _summary(client, case)["bforce"]["grade"] == "contact"


def test_integration_skip_hw_unavailable_real_core(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    object.__setattr__(w.settings.altair, "hw_exe_path", str(tmp_path / "nohw"))
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED"
    b = j["result"]["bf_ondemand"]
    assert b["status"] == "skipped" and b["cause"] == "HW_UNAVAILABLE"
    s = _summary(client, case)
    assert s["bforce"]["code"] == "BF_EXTRACT_SKIPPED" and s["fint"]["code"] == "BF_EXTRACT_SKIPPED"
    assert _argvs(esl_root) == []
    assert not (Path(esl_root) / "case01" / "04_esl" / "bforce.npz").exists()


def test_integration_license_real_core(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    monkeypatch.setenv("FAKE_HW_MODE", "license")
    j = _esl(client, w, case)
    b = j["result"]["bf_ondemand"]
    assert j["state"] == "SUCCEEDED" and b["status"] == "failed" and b["cause"] == "LICENSE", b
    s = _summary(client, case)
    assert s["bforce"]["code"] == "BF_EXTRACT_FAILED" and "라이선스" in s["bforce"]["reason"]


def test_integration_mismatch_real_core(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    """다른 h3d(프레임 수가 다름) → 실제 병합 BF_FILL_MISMATCH → worker cause MISMATCH, 01_extract bforce.* 쓰지 않음."""
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    data = tmp_path / "tcl_bf_data.tcl"
    txt = data.read_text()
    first = txt.split("\n", 1)[0]
    data.write_text(txt.replace(first, first[:-1] + ' "Time = 99"}', 1))     # 프레임 12 개 — 추출(11)과 다름
    j = _esl(client, w, case)
    b = j["result"]["bf_ondemand"]
    assert j["state"] == "SUCCEEDED" and b["status"] == "failed" and b["cause"] == "MISMATCH", b
    ext = Path(esl_root) / "case01" / "01_extract"
    assert not (ext / "bforce.json").exists() and not (ext / "bforce.npz").exists()
    assert json.loads((ext / "bforce_ondemand.json").read_text())["attempts"][0]["code"] == "BF_EXTRACT_FAILED"


def test_integration_timeout_real_core(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    monkeypatch.setenv("FAKE_HW_MODE", "hang")
    monkeypatch.setenv("FAKE_HW_PIDS", str(tmp_path / "hw.pids"))
    object.__setattr__(w.settings.altair, "bf_on_demand_timeout_s", 2)
    j = _esl(client, w, case)
    b = j["result"]["bf_ondemand"]
    assert j["state"] == "SUCCEEDED" and b["cause"] == "TIMEOUT", b
    s = _summary(client, case)
    assert s["bforce"]["code"] == "BF_EXTRACT_FAILED" and s["fint"]["code"] == "BF_EXTRACT_FAILED"
    assert "시간 초과 2 s" in s["bforce"]["reason"] and s["bforce"]["reason"].endswith("③ ESL 을 다시 계산하면 다시 시도합니다")


def test_integration_has_frame_core_error_row4a(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    """DECIDE 행 4a: 코어 has_frame CoreError = 보충 없이 v0.24.1 동작(hw 0, 기록 없음, BF_NO_DATA)."""
    from esl_worker import core_adapter

    def boom(*a, **k):
        raise core_adapter.CoreError("INTERNAL", "boom")

    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    monkeypatch.setattr(core_adapter, "bforce_has_frame", boom)
    j = _esl(client, w, case)
    assert j["state"] == "SUCCEEDED" and _argvs(esl_root) == [] and "bf_ondemand" not in (j["result"] or {})
    assert not (Path(esl_root) / "case01" / "01_extract" / "bforce_ondemand.json").exists()
    assert _summary(client, case)["bforce"]["code"] == "BF_NO_DATA"


def test_integration_no_types_before_real_core(tmp_path):
    """판정 5 — B 가 쓰는 attempt(attempt_record)·names(names_from)로 실제 record·no_types_before 왕복."""
    from esl_worker import bf_ondemand as b
    from esl_worker import core_adapter

    ext = tmp_path / "01_extract"
    ext.mkdir()
    names = b.names_from({})
    att = b.attempt_record(frame=6, job_id="j1", cause=None, detail="", seconds=1.0, h3d_path="x.h3d",
                           out_rel="_h3d/c/bf_ondemand/raw", names=names, kinds={"cont": None, "acc": None},
                           merge={"added": [6], "dup": [], "backup": None})
    core_adapter.bforce_record(str(ext), att)
    hit = core_adapter.bforce_no_types_before(str(ext), names)
    assert hit is not None and hit["at"] == att["at"]
    other = b.names_from({"bforce": {"result_names": {"cont": ["KF"]}}})
    assert core_adapter.bforce_no_types_before(str(ext), other) is None
    from esl_worker.bf_ondemand import Facts, decide
    f = Facts(enabled=True, on_demand=True, input_kind="H3D", has_frame=False, h3d_ok=True, hw_ok=True, no_types=hit)
    d = decide(f)
    assert (d.action, d.cause) == ("skip", "NO_TYPES")
    assert att["at"] in b.detail_text("NO_TYPES", at=hit["at"])


def test_integration_nondump_bf_present_no_hw_bytes_same(client, synth_inputs, worker_factory, esl_root, monkeypatch,
                                                         tmp_path):
    """V-0242-BFD-11: 비덤프 + 경계력 있음 Case ESL → hw 호출 0(판정 4), on_demand false(v0.24.1 동작)와 04_esl 바이트 동일."""
    import hashlib

    from esl_worker import core_adapter

    src = tmp_path / "csv_bf"
    shutil.copytree(synth_inputs["csv"], src)
    done = json.loads((src / "done.json").read_text())
    D = done["frames_D"]
    nid = [int(n) for n in synth_inputs["node_id"]]
    rng = np.random.default_rng(3)
    kinds = {}
    for k, ty in (("cont", "Contact Forces"), ("acc", "Acceleration")):
        rows = ["frame_index,node_id,x,y,z"]
        for f in D:
            for n in nid:
                rows.append(f"{f},{n}," + ",".join("%.17g" % x for x in rng.normal(size=3)))
        (src / f"bf_{k}.csv").write_text("\n".join(rows) + "\n")
        kinds[k] = {"type": ty, "comps": ["X", "Y", "Z"], "rows": len(D) * len(nid)}
    done["bforce"] = {"on": True, "frames": D, "kinds": kinds}
    (src / "done.json").write_text(json.dumps(done))
    synth = {**synth_inputs, "csv": str(src)}
    w = worker_factory()
    monkeypatch.setenv("FAKE_HW_SRC", str(src))
    monkeypatch.setenv("FAKE_HW_MODE", "ok")
    h3d = write_h3d(Path(synth["rad"]).parent / "case01_drop.h3d")
    case = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": "case01", "title": "nd",
                                             "rad_path": synth["rad"], "h3d_path": str(h3d)}, headers=W).json()
    j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    assert w.run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{j['id']}", headers=R).json()
    sug = client.post(f"{API}/cases/{case['id']}/support-sets/suggest", json={}, headers=W).json()
    client.post(f"{API}/cases/{case['id']}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W)

    def sha(name):
        return hashlib.sha256((Path(esl_root) / "case01" / "04_esl" / name).read_bytes()).hexdigest()

    j1 = _esl(client, w, case)
    assert j1["state"] == "SUCCEEDED" and _argvs(esl_root) == [] and "bf_ondemand" not in (j1["result"] or {})
    assert _summary(client, case)["bforce"]["grade"] == "contact"
    h1 = {n: sha(n) for n in ("bforce.npz", "bforce.json", "u_rel.npz", "f_eq.npz")}
    real = core_adapter.bforce_settings
    monkeypatch.setattr(core_adapter, "bforce_settings", lambda s=None: {**real(s), "on_demand": False})
    j2 = _esl(client, w, case)
    assert j2["state"] == "SUCCEEDED" and _argvs(esl_root) == []
    assert {n: sha(n) for n in h1} == h1


def test_integration_reextract_backs_up_filled(client, dump_inputs, worker_factory, esl_root, monkeypatch, tmp_path):
    """계약 §7: 다시 추출 = 01_extract 전체(보충분 bforce.*·기록 포함)가 Case _backup 으로, 새 추출은 bforce 없음 → 다음 ESL 이 다시 보충."""
    w = worker_factory()
    case, _ = _setup(client, w, dump_inputs, monkeypatch, tmp_path)
    assert _esl(client, w, case)["state"] == "SUCCEEDED"
    ext = Path(esl_root) / "case01" / "01_extract"
    assert (ext / "bforce.json").is_file()
    j = client.post(f"{API}/cases/{case['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W).json()
    assert w.run_once("SLOT") == "SUCCEEDED", client.get(f"{API}/jobs/{j['id']}", headers=R).json()
    assert not (ext / "bforce.json").exists() and not (ext / "bforce_ondemand.json").exists()
    bk = list((Path(esl_root) / "case01" / "_backup").glob("*/01_extract/bforce.json"))
    assert len(bk) == 1 and list(bk[0].parent.glob("bforce_ondemand.json"))
