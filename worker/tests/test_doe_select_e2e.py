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
from doe_worker_support import calls, doe_worker_settings
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
    # v0.20.0: 새 스터디 순위 = 1차 강성 지표(lin·ritz). 깊이 ±4 mm(공칭 22)는 1차 근사 범위 밖(|ρ−1| ≫ lin_valid — 고정 변형을
    # 바뀐 비드 벽에 주면 양쪽 모두 막 변형에너지가 커져 ρ > 1)이라 단조 검사는 재풀이 C(score_solve)로 한다(미해결 R-SM-1 기록).
    assert res["metric"] == "lin" and all(x.get("score_solve") is not None for x in rk)
    lv = res["rank"]["lin_valid"]
    assert max(abs(x["rho_max"] - 1.0) for x in (rk[0], rk[-1])) > lv          # 양 끝 안 = SM_LIN_RANGE 범위 밖
    scores = [x["score_solve"] for x in rk]
    assert all(a > b for a, b in zip(scores, scores[1:])), scores        # 깊어질수록 강성 ↑ → 재풀이 score ↓
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


# ================================================================ v0.16.2 자동 탐지 seed · ② B 메시 기준 select(esl_bead_auto.md V-AD-2·10·11)
import json  # noqa: E402

from test_doe_select_jobs import (  # noqa: E402,F401
    CORE_MESH_BASE,
    b_mesh_upload,
    create_select,
    needs_core_mesh,
)

SPEC2 = {"method": "fullfact", "levels": 3, "params": [{"name": "B1_D1", "lo": 18.0, "hi": 26.0}]}


def _flow(client, worker, s, sel, spec=SPEC2) -> dict:
    """준비된 select 스터디: 선택 저장 → 미리보기 → 실행 → DONE 스터디."""
    s = save_selection(client, study(client, s["id"]), sel)
    p = preview(client, s, spec)
    run_job(client, worker, p["job"]["id"])
    r = start_run(client, study(client, s["id"]))
    run_job(client, worker, r["job"]["id"])
    g = study(client, s["id"])
    assert g["phase"] == "DONE", g["phase"]
    return g


def _norm(o, ids: dict[str, str]):
    """비교용: 스터디 id·제목·시각을 지운 사본(V-AD-2 '타임스탬프 제외')."""
    t = json.dumps(o, sort_keys=True, ensure_ascii=False)
    for k, v in ids.items():
        t = t.replace(k, v)
    d = json.loads(t)

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return strip(d)


VOLATILE = ("created_at", "finished_at", "started_at", "generated_at", "seconds", "job_id", "elapsed_s", "t0", "t1",
            "cleanup_bytes", "title")


def _report(d, sid: str) -> str:
    """보고서 비교용: 스터디 id·생성 시각 + 입력 CAD 행(auto = '자동 탐지 초기 선택 입력' STEP 이름 — 입력 출처 표기, 결과 아님)을 지움."""
    import re

    t = (d / "report.html").read_text(encoding="utf-8").replace(sid, "SID")
    t = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?", "T", t)
    return re.sub(r"<td>[^<]*산출물에 CAD 없음\)</td>", "<td>CAD</td>", t)


def _artifacts(esl_root, client, sid) -> dict:
    d = esl_root / "_doe" / sid
    res = api(client, "GET", f"/doe/studies/{sid}/results").json()
    per = json.loads((d / "post" / "per_esl.json").read_text())
    return {"results": res, "per_esl": per, "result": json.loads((d / "post" / "result.json").read_text())}


def test_v0162_auto_saved_equals_manual(client, engine, worker, esl_root, inputs_root, exe):  # noqa: F811
    """V-AD-2: seed 를 편집해 저장한 auto 스터디 = 같은 선택의 수동 스터디 — 결과·순위·ESL별 지표·보고서 동일(id·시각·입력 CAD 행 제외). seed 는
    출처일 뿐 design_sha·선택 sha 에 들어가지 않는다(AD-D-22)."""
    w = make_bead_case(engine, esl_root, inputs_root)
    a = create_select(client, w["entry_ids"], auto=True)
    run_job(client, worker, a["job"]["id"])
    m = create_select(client, w["entry_ids"])
    run_job(client, worker, m["job"]["id"])
    seed = api(client, "GET", f"/doe/studies/{a['id']}/select/auto")
    sel = sb.selection(w["g"])
    if seed.status_code == 200 and seed.json()["selection"].get("beads"):     # 코어 병합 후: seed 를 편집(사용자 = 정답 선택)
        assert seed.json()["sha256"]
    ga = _flow(client, worker, a, sel)
    gm = _flow(client, worker, m, sel)
    assert ga["selection"]["sha256"] == gm["selection"]["sha256"]
    xa, xm = _artifacts(esl_root, client, a["id"]), _artifacts(esl_root, client, m["id"])
    ids = {a["id"]: "SID", m["id"]: "SID"}
    assert _norm(xa, ids) == _norm(xm, ids)
    da, dm = esl_root / "_doe" / a["id"], esl_root / "_doe" / m["id"]
    for did in [r["id"] for r in xa["results"]["ranking"]] + ["d000"]:
        ra = json.loads((da / "run" / "designs" / did / "done.json").read_text())
        rm = json.loads((dm / "run" / "designs" / did / "done.json").read_text())
        assert ra.get("input_sha256") == rm.get("input_sha256"), did
    assert _report(da, a["id"]) == _report(dm, m["id"])             # 보고서 = 생성 시각·입력 CAD 행 외 같음


@needs_core_mesh
def test_v0162_select_mesh_auto_equals_manual(client, engine, worker, esl_root, inputs_root, exe, tmp_path):  # noqa: F811
    """V-AD-10: ② select(mesh) — auto(가짜 paicad extract·tag on B) seed → 편집 → 저장 → 미리보기 → 실행 = 같은 선택의 수동
    select(mesh) 스터디와 결과·순위·보고서 동일(id·시각 제외)."""
    w = make_bead_case(engine, esl_root, inputs_root)
    uid = b_mesh_upload(client, tmp_path, w["mesh"])
    a = create_select(client, w["entry_ids"], auto=True, mesh_uid=uid)
    run_job(client, worker, a["job"]["id"])
    m = create_select(client, w["entry_ids"], mesh_uid=uid)
    run_job(client, worker, m["job"]["id"])
    da, dm = esl_root / "_doe" / a["id"], esl_root / "_doe" / m["id"]
    tag = calls(exe, "tag")
    assert tag and tag[-1]["argv"][tag[-1]["argv"].index("--assem-dir") + 1] == str(da / "input" / "mesh")
    sel = sb.selection(w["g"])
    ga, gm = _flow(client, worker, a, sel), _flow(client, worker, m, sel)
    assert ga["selection"]["sha256"] == gm["selection"]["sha256"]
    ids = {a["id"]: "SID", m["id"]: "SID"}
    assert _norm(_artifacts(esl_root, client, a["id"]), ids) == _norm(_artifacts(esl_root, client, m["id"]), ids)
    assert _report(da, a["id"]) == _report(dm, m["id"])


@needs_core_mesh
def test_v0162_select_mesh_eval_matches_legacy_mesh(client, engine, worker, esl_root, inputs_root, exe, tmp_path):  # noqa: F811
    """V-AD-11: select(mesh) d000 = legacy ② d000 — prep/loads.npz 바이트·base.json supports·frame 같음, d000 per_esl(C·umax·
    epsmax) 같음, 모든 안 loads sha·supports 같음(하중·지지는 베이스라인 1회 재사용 — AD-D-19)."""
    from doe_support import upload_step
    from doe_worker_support import D1

    w = make_bead_case(engine, esl_root, inputs_root)
    uid = b_mesh_upload(client, tmp_path, w["mesh"])
    sm = create_select(client, w["entry_ids"], mesh_uid=uid)
    run_job(client, worker, sm["job"]["id"])
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "mesh", "entry_ids": w["entry_ids"],
                                                  "step_upload_id": upload_step(client), "mesh_upload_id": uid})
    assert r.status_code == 201, r.text
    lg = r.json()
    run_job(client, worker, lg["job"]["id"])
    ds, dl = esl_root / "_doe" / sm["id"], esl_root / "_doe" / lg["id"]
    assert (ds / "prep" / "loads.npz").read_bytes() == (dl / "prep" / "loads.npz").read_bytes()
    bs, bl = (json.loads((d / "prep" / "base.json").read_text()) for d in (ds, dl))
    assert bs["supports"] == bl["supports"] and bs["frame"] == bl["frame"] and bs["target"] == bl["target"] == "S2"
    assert bs["mesh_sha256"] == bl["mesh_sha256"]
    _flow(client, worker, sm, sb.selection(w["g"]))
    s = study(client, lg["id"])
    p = preview(client, s, {"method": "fullfact", "levels": 2, "params": [{"name": D1, "lo": 3.5, "hi": 4.5}]})
    run_job(client, worker, p["job"]["id"])
    r = start_run(client, study(client, lg["id"]))
    run_job(client, worker, r["job"]["id"])
    rs, rl = (json.loads((d / "run" / "designs" / "d000" / "result.json").read_text()) for d in (ds, dl))
    keep = ("entry_id", "C", "umax", "epsmax")
    assert [{k: x.get(k) for k in keep} for x in rs["per_esl"]] == [{k: x.get(k) for k in keep} for x in rl["per_esl"]]
