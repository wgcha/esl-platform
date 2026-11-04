"""v0.15.0 select 비드 직접 선택 E2E(계약 esl_bead_select.md V-BS-15) — 실제 PG·백엔드 API·워커·코어·자체 솔버.

합성 비드 메시(tests/doe/synth_bead.py, h 10 mm)를 Case 로 등록 + 같은 메시의 자기평형 ESL 2개(굽힘·뒤틀림) → DOE_PREP →
선택 derive·저장(API) → 변수 표 → 미리보기(D1 4수준) → 실행 → D1 깊어질수록 score 단조 감소, 보고서·받기 파일·검증 낙하 계획 진입
(가짜 SCX 릴레이 — 시나리오·안 산출물 검사 통과 후 씬 판정).
"""

from __future__ import annotations

import os
import sys

import pytest
from doe_support import api
from esl_test_support import API, REPO
from opt_support import tree
from doe_worker_support import doe_worker_settings
from test_doe_select_jobs import (  # noqa: F401 - 픽스처
    R,
    create,
    exe,
    get_job,
    make_bead_case,
    preview,
    run_job,
    save_selection,
    start_run,
    study,
    worker,
)

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_bead as sb  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")


@pytest.fixture()
def fake_relay(tmp_path):
    from scx_support import start_relay

    f = start_relay(tmp_path / "drive")
    try:
        yield f
    finally:
        f.stop()


@pytest.fixture()
def settings_dict(tmp_path, exe, fake_relay):  # noqa: F811
    """DOE(가짜 paicad) + 검증 낙하(가짜 SCX 릴레이) — 검증 낙하 계획 진입(§8.4)만 본다."""
    from verify_support import verify_settings

    d = doe_worker_settings(tmp_path, exe)
    v = verify_settings(tmp_path, fake_relay)
    for k in ("hpc", "scx_drive", "verify_drop"):
        d[k] = v[k]
    return d


def test_select_e2e_depth_ranking(client, engine, worker, esl_root, inputs_root, exe):  # noqa: F811
    w = make_bead_case(engine, esl_root, inputs_root)
    in_before = tree(inputs_root)
    s = create(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    s = study(client, s["id"])
    sid = s["id"]
    assert s["phase"] == "READY" and s["selection"] is None
    # 선택 보기 자료 → derive(저장 안 함) → 저장
    assert api(client, "GET", f"/doe/studies/{sid}/select/view/select_manifest.json").status_code == 200
    sel = sb.selection(w["g"])
    dv = api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel})
    assert dv.status_code == 200, dv.text
    assert dv.json()["rev"] is None and [b["id"] for b in dv.json()["beads"]] == ["b1", "b2"]
    s = save_selection(client, s, sel)
    assert s["selection"]["rev"] == 1
    tab = {x["name"]: x for x in api(client, "GET", f"/doe/studies/{sid}/params").json()["params"]}
    assert abs(tab["B1_D1"]["nominal"] - 22.0) < 0.5 and abs(tab["B1_D2"]["nominal"] - 14.0) < 0.5
    spec = {"method": "fullfact", "levels": 4, "params": [{"name": "B1_D1", "lo": 18.0, "hi": 26.0}]}
    p = preview(client, s, spec)
    run_job(client, worker, p["job"]["id"])
    g = study(client, sid)
    assert g["phase"] == "PREVIEW_READY" and g["doe"]["preview"]["ok"] == 4
    assert g["doe"]["preview"]["selection_sha256"] == s["selection"]["sha256"]
    # v0.15.1 "미리보기 했는데 안 보임": select grid_manifest(kind select) → 셀 4개·썸네일 있음, 썸네일·공칭 PNG 200
    cells = g["doe"]["preview"]["cells"]
    assert [c["status"] for c in cells] == ["READY"] * 4 and all(c["thumb"] for c in cells), cells
    for did in ("d000", cells[0]["id"]):
        th = api(client, "GET", f"/doe/studies/{sid}/preview/thumb/{did}")
        assert th.status_code == 200 and th.content[:4] == b"\x89PNG", (did, th.status_code)
    r = start_run(client, g)
    j = run_job(client, worker, r["job"]["id"])
    assert j["progress_pct"] == 100.0
    g = study(client, sid)
    assert g["phase"] == "DONE"
    res = api(client, "GET", f"/doe/studies/{sid}/results").json()
    rk = sorted(res["ranking"], key=lambda x: x["values"]["B1_D1"])
    d1 = [x["values"]["B1_D1"] for x in rk]
    assert len(rk) == 4 and d1[0] == 18.0 and d1[-1] == 26.0
    scores = [x["score"] for x in rk]
    assert all(a > b for a, b in zip(scores, scores[1:])), scores        # 깊어질수록 강성 ↑ → score ↓
    assert scores[0] > 1.0 > scores[-1]                                  # 공칭(22) = 베이스라인 사이
    rels = {f["rel"] for f in api(client, "GET", f"/doe/studies/{sid}/files").json()}
    best = rk[-1]["id"]
    assert {f"best/{best}/ch_r.rad", f"best/{best}/ch_r.fem", f"best/{best}/selection.json",
            f"best/{best}/include/{w['rad'].name}", "report.html"} <= rels
    rep = client.get(f"{API}/doe/studies/{sid}/report", headers=R)
    assert rep.status_code == 200 and "B1_D1" in rep.text
    vd = api(client, "POST", "/verify-drops/plan", json={"bead_doe_id": sid, "design_id": best, "mode": "all"})
    # §8.4 검증 낙하 진입: 시나리오·안 산출물(best/<did>/include) 검사 통과 → 씬 판정까지 간다(합성 Case 는 ① 추출 결과가
    # 없어 VD_CASE_NOT_READY 로 제외 — VD_SCENARIO_UNSUPPORTED·VD_DESIGN_NO_FILES 가 아님)
    det = vd.json()["detail"] if vd.status_code != 200 else {}
    assert vd.status_code == 200 or (vd.status_code == 409 and det["code"] == "VD_NO_SCENES"), vd.text
    if det:
        assert [x["code"] for x in det["excluded"]] == ["VD_CASE_NOT_READY"]
    assert tree(inputs_root) == in_before
    assert get_job(client, j["id"])["state"] == "SUCCEEDED"
