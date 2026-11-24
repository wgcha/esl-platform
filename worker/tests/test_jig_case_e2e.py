"""v0.24.4 P2b 통합(계약 esl_jig_case.md 부록 A): 가짜 paicad 로 워커 ESL_SOLVE(지그 tie 준비) → 코어 ③ 지그 3방식 → ④ 검증 →
백엔드 API(3D 출처 목록·?src=jig*·검증 출처 목록) 완주. 실제 코어·워커·백엔드가 형식을 그대로 주고받는지 확인한다.
paicad 없는 환경(설정 없음)은 기존 동작 그대로 + JIG_FIXED_SKIPPED 기록.
``JIG_E2E_DUMP=<경로>`` 이면 실제 응답을 프런트 픽스처 JSON 으로 저장(frontend/src/__tests__/fixtures/real_v0244.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from doe_worker_support import calls, doe_worker_settings, write_fake_paicad
from esl_test_support import API, H, create_case, legacy_sources, make_settings_dict

W = H("tok-power", True)
R = H("tok-power")
JIG = ("jig", "jig_disp", "jig_spring")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")


@pytest.fixture()
def fake_paicad(tmp_path) -> Path:
    return write_fake_paicad(tmp_path)


@pytest.fixture()
def settings_dict(request, tmp_path, fake_paicad):
    if "no_paicad" in request.node.name:
        return legacy_sources(make_settings_dict(tmp_path, report={"auto": False}))
    d = doe_worker_settings(tmp_path, fake_paicad)
    d["worker"]["slots"] = 2
    d["report"] = {**(d.get("report") or {}), "auto": False}
    legacy_sources(d)                                               # v0.24.5 §12: 지그 고정·경계력은 기본 끔 — v0.24.4 와 같은 6 출처로 되돌려 시험
    d["core"]["settings"]["jig"]["fix_kinds"] = ["RBE2"]            # 가짜 paicad 는 RBE2 종류 클러스터를 돌려줌(실제는 INTER_TYPE2)
    return d


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job):
    st = worker.run_once("SLOT")
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _through_validate(client, worker, synth, folder="case01"):
    r = create_case(client, synth, folder=folder)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    jesl = _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    rid = client.get(f"{API}/cases/{cid}", headers=R).json()["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": rid}))
    vid = client.get(f"{API}/cases/{cid}/validations", headers=R).json()[0]["id"]
    return cid, rid, vid, jesl


def _dump(out: dict) -> None:
    path = os.environ.get("JIG_E2E_DUMP")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), default=str)


def test_fake_paicad_esl_to_validation_to_api(client, synth_inputs, worker_factory, esl_root, fake_paicad):
    worker = worker_factory()
    cid, rid, vid, jesl = _through_validate(client, worker, synth_inputs)
    cd = Path(str(esl_root)) / "case01"
    out: dict = {}
    # ---- 워커 준비 → 코어가 그대로 읽음: 01_extract/jig_fixed + jig_prep.json(ok) → 지그 3방식 계산됨
    assert len(calls(fake_paicad, "fixed-scan")) == 1
    rec = json.loads((cd / "01_extract" / "jig_prep.json").read_text(encoding="utf-8"))
    assert rec["status"] == "ok" and (cd / "01_extract" / "jig_fixed" / "fixed_nodes.npz").is_file()
    esum = json.loads((cd / "04_esl" / "esl_summary.json").read_text(encoding="utf-8")) if (
        cd / "04_esl" / "esl_summary.json").is_file() else {}
    for k in JIG:
        assert (cd / "04_esl" / f"{k}.npz").is_file() and (cd / "04_esl" / f"{k}.json").is_file(), (k, sorted(os.listdir(cd / "04_esl")))
        doc = json.loads((cd / "04_esl" / f"{k}.json").read_text(encoding="utf-8"))
        assert doc.get("status") == "ok", (k, doc.get("code"), doc.get("detail"))
    out["esl_summary_keys"] = sorted(esum)
    # ---- 3D 출처 목록(Case ③)
    s3 = client.get(f"{API}/esl-runs/{rid}/view3d/sources", headers=R)
    assert s3.status_code == 200, s3.text
    rows3 = {r["key"]: r for r in s3.json()["rows"]}
    assert list(rows3) == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    for k in JIG:
        assert rows3[k]["available"] is True, (k, rows3[k])
    out["view3d_sources"] = s3.json()
    # ---- ?src=jig* 하중 보기(응답 JSON — 파서 대조용)
    for k in JIG:
        v = client.get(f"{API}/esl-runs/{rid}/view3d", params={"src": k}, headers=R)
        assert v.status_code == 200, (k, v.text)
        out[f"view3d_{k}"] = v.json()
        dofs = {x["dof"] for x in v.json()["supports"]}
        assert dofs == {"123", "ij"}, (k, dofs)                 # tie "123"(채움 기호) · 3-2-1 면내 "ij"(빈 기호) — 스프링 행도 tie 표식
    # ---- ④ 검증 출처
    sj = json.loads((cd / "05_val" / "sources.json").read_text(encoding="utf-8"))
    assert [r["key"] for r in sj["rows"]] == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    sv = client.get(f"{API}/validations/{vid}/sources", headers=R).json()
    rowsv = {r["key"]: r for r in sv["rows"]}
    for k in JIG:
        assert rowsv[k]["available"] is True and rowsv[k]["reaction_role"] == "info", (k, rowsv[k])
        assert rowsv[k]["status"] in ("PASS", "FAIL", "UNDETERMINED", "CAUTION"), rowsv[k]["status"]
    out["val_sources"] = sv
    for k in JIG:
        v = client.get(f"{API}/validations/{vid}", params={"src": k}, headers=R)
        assert v.status_code == 200, (k, v.text)
        out[f"validation_{k}"] = v.json()
    hist = client.get(f"{API}/cases/{cid}/validations/sources", headers=R).json()
    assert hist["items"][0]["rows"] == sv["rows"]
    out["val_hist"] = hist
    out["ids"] = {"case": cid, "esl_run": rid, "validation": vid}
    _dump(out)


def test_no_paicad_env_esl_unchanged_with_skipped_record(client, synth_inputs, worker_factory, esl_root):
    """paicad 설정 없음: ESL 은 성공·기존 산출물 그대로, 지그 3행 = JIG_FIXED_SKIPPED(기록 1건·로그 1줄), 산출물 등록에 jig_prep.json."""
    worker = worker_factory()
    cid, rid, vid, jesl = _through_validate(client, worker, synth_inputs)
    cd = Path(str(esl_root)) / "case01"
    rec = json.loads((cd / "01_extract" / "jig_prep.json").read_text(encoding="utf-8"))
    assert rec["status"] == "skipped" and rec["code"] == "JIG_FIXED_SKIPPED"
    assert not (cd / "01_extract" / "jig_fixed").exists()
    assert (cd / "04_esl" / "f_eq.npz").is_file() and (cd / "04_esl" / "u_rel.npz").is_file()
    for k in JIG:
        assert not (cd / "04_esl" / f"{k}.npz").exists()
    s3 = client.get(f"{API}/esl-runs/{rid}/view3d/sources", headers=R).json()
    rows3 = {r["key"]: r for r in s3["rows"]}
    for k in JIG:
        assert rows3[k]["available"] is False and rows3[k]["code"] == "JIG_FIXED_SKIPPED", rows3[k]
    assert rows3["full"]["available"] is True
    sv = {r["key"]: r for r in client.get(f"{API}/validations/{vid}/sources", headers=R).json()["rows"]}
    for k in JIG:
        assert sv[k]["available"] is False and sv[k]["code"] == "JIG_FIXED_SKIPPED", sv[k]
    assert sv["full"]["available"] is True
    log = client.get(f"{API}/jobs/{jesl['id']}/log", params={"step": next(s for s in jesl["steps"] if s["step_key"] == "ESL")["step_no"]},
                     headers=R).json()["lines"]
    assert sum(ln.startswith("[esl-worker] 지그 tie") for ln in log) == 1, [ln for ln in log if "지그" in ln]
    arts = client.get(f"{API}/cases/{cid}/artifacts", headers=R).json()
    arts = arts if isinstance(arts, list) else arts.get("items", [])
    assert any(str(a.get("rel_path") or a.get("path")).endswith("01_extract/jig_prep.json") for a in arts)
