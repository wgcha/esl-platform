"""V-SR-8 검증 낙하 생성 검사(계약 esl_scx_relay.md SR-D-10·13·14·15, §7): ②③ 422, best 없는 안 422, 씬 선택 worst N(r 큰 순·동률
entry_id 순·같은 Case 합침)·all, 상한 422, 누적 씬·엔진 없음·include 배치·추출 없음·활성 중 씬 = excluded, 0개 409, plan = 생성과
같은 씬(저장 안 함), 권한(power 이상·조회 멤버), 기능 꺼짐 503, 조회·응답 키·params 에 서버 경로 없음, 대기 중 취소 → CANCELED."""

from __future__ import annotations

import pytest
from esl_test_support import API, H
from verify_support import counts, seed_case, seed_entry_for, seed_study, verify_settings

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def settings_dict(tmp_path, fake_relay):
    return verify_settings(tmp_path, fake_relay)


def _code(r):
    return r.json()["detail"]["code"]


def body(sid, mode="worst", **kw):
    return {"bead_doe_id": sid, "design_id": "d007", "mode": mode, **kw}


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    """씬 Case 5개: a·b·c 정상, d 누적, e 엔진 없음 + 같은 Case a 의 ESL 2개(합침)."""
    cs = {n: seed_case(engine, esl_root, inputs_root, n) for n in ("a", "b", "c")}
    cs["d"] = seed_case(engine, esl_root, inputs_root, "d", cumulative=True)
    cs["e"] = seed_case(engine, esl_root, inputs_root, "e", engine_rad=False)
    ents = {n: seed_entry_for(engine, c["id"]) for n, c in cs.items()}
    ents["a2"] = seed_entry_for(engine, cs["a"]["id"], scene_no=2)
    r = {ents["a"]: 0.95, ents["a2"]: 1.20, ents["b"]: 0.80, ents["c"]: 1.05, ents["d"]: 1.50, ents["e"]: 1.40}
    sid = seed_study(engine, esl_root, list(r), ratios=r)
    return {"cases": cs, "ents": ents, "sid": sid}


def test_plan_worst_all_and_create(client, world, engine):
    sid, ents, cs = world["sid"], world["ents"], world["cases"]
    r = client.post(f"{API}/verify-drops/plan", json=body(sid), headers=W)
    assert r.status_code == 200, r.text
    p = r.json()
    # r 큰 순: d(1.5 누적 제외), e(1.4 엔진 없음 제외), a(a2 1.2 로 합침), c(1.05), b(0.8) → N=2(기본) = a, c
    assert [s["case_id"] for s in p["scenes"]] == [cs["a"]["id"], cs["c"]["id"]]
    assert p["scenes"][0]["entry_id"] == ents["a2"] and p["scenes"][0]["r_c"] == pytest.approx(1.2)
    assert p["scenes"][0]["r_umax"] == pytest.approx(1.2 * 0.9) and p["scenes"][0]["r_epsmax"] == pytest.approx(1.2 * 1.1)
    assert {x["case_id"]: x["code"] for x in p["excluded"]} == {cs["d"]["id"]: "VD_CUMULATIVE_EXCLUDED",
                                                                 cs["e"]["id"]: "VD_ENGINE_MISSING"}
    assert p["n_submit"] == 2 and p["est_hours"] == 3 and p["max_scenes"] == 3 and p["default_worst_n"] == 2
    assert p["hpc"] == {"version": "2026.1", "ncpu": 16}
    assert counts(engine) == (0, 0)                                          # plan 은 저장 안 함
    pa = client.post(f"{API}/verify-drops/plan", json=body(sid, "all"), headers=W).json()
    assert [s["case_id"] for s in pa["scenes"]] == [cs["a"]["id"], cs["c"]["id"], cs["b"]["id"]]
    assert client.post(f"{API}/verify-drops/plan", json=body(sid, n=1), headers=W).json()["n_submit"] == 1
    # 생성 = plan 과 같은 씬, 씬마다 행 1개·VERIFY_DROP 1개, batch 로 묶음
    r = client.post(f"{API}/verify-drops", json=body(sid, hpc={"version": "2025.1", "ncpu": 8}), headers=W)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [d["case_id"] for d in out["drops"]] == [s["case_id"] for s in p["scenes"]]
    assert {d["batch_id"] for d in out["drops"]} == {out["batch_id"]} and len(out["excluded"]) == 2
    d0 = out["drops"][0]
    assert d0["phase"] == "PREP" and d0["predicted"]["r_c"] == pytest.approx(1.2) and d0["submission"] is None
    assert d0["job"]["job_type"] == "VERIFY_DROP" and d0["job"]["lane"] == "XFER" and d0["job"]["stage"] == 13
    assert [s["step_key"] for s in d0["job"]["steps"]] == ["VD_PREP", "VD_STAGE", "VD_SUBMIT", "VD_WAIT", "VD_FETCH"]
    assert d0["job"]["verify_drop_id"] == d0["id"] and set(d0["job"]["params"]) <= {"verify_drop_id", "bead_doe_id",
                                                                                   "design_id", "case_id"}
    assert str(cs["a"]["rad"]) not in r.text                                  # 서버 경로 없음
    assert counts(engine) == (2, 2)
    # 같은 (스터디, 안, Case) 비종료 1개 → 다시 요청하면 활성 씬은 제외, 남은 씬(b)만
    p2 = client.post(f"{API}/verify-drops/plan", json=body(sid, "all"), headers=W).json()
    assert [s["case_id"] for s in p2["scenes"]] == [cs["b"]["id"]]
    assert {x["code"] for x in p2["excluded"]} >= {"VD_ALREADY_ACTIVE"}
    # 조회
    lst = client.get(f"{API}/verify-drops", params={"bead_doe_id": sid}, headers=H("tok-general")).json()
    assert {d["id"] for d in lst} == {d["id"] for d in out["drops"]}
    g = client.get(f"{API}/verify-drops/{d0['id']}", headers=R).json()
    assert set(g) >= {"id", "batch_id", "bead_doe_id", "design_id", "case_id", "entry_id", "title", "phase", "version",
                      "drive_dir_display", "scx_job_id", "scx_status", "submission", "files_n", "files_bytes", "predicted",
                      "result", "job_ids", "created_by_name", "created_at", "updated_at"}
    assert client.get(f"{API}/verify-drops/nope", headers=R).status_code == 404
    assert client.get(f"{API}/verify-drops/{d0['id']}", headers=H("tok-nonmember")).status_code == 403
    assert client.get(f"{API}/verify-drops/{d0['id']}/compare.csv", headers=R).status_code == 409
    # 대기 중 취소 → 작업 CANCELED + 검증 phase CANCELED(SCX 호출 없음)
    c = client.post(f"{API}/jobs/{d0['job']['id']}/cancel", headers=W)
    assert c.status_code == 200 and c.json()["state"] == "CANCELED"
    assert client.get(f"{API}/verify-drops/{d0['id']}", headers=R).json()["phase"] == "CANCELED"


def test_scene_limits_and_errors(client, world, engine, esl_root, inputs_root):
    sid = world["sid"]
    r = client.post(f"{API}/verify-drops/plan", json=body(sid, n=4), headers=W)
    assert r.status_code == 422 and _code(r) == "VD_TOO_MANY_SCENES"
    r = client.post(f"{API}/verify-drops/plan", json=body(sid, design_id="d099"), headers=W)
    assert r.status_code == 422 and _code(r) == "VD_DESIGN_NO_FILES"
    r = client.post(f"{API}/verify-drops/plan", json=body("nope"), headers=W)
    assert r.status_code == 404 and _code(r) == "DOE_NOT_FOUND"
    r = client.post(f"{API}/verify-drops/plan", json=body(sid, mode="best"), headers=W)
    assert r.status_code == 422
    # ②③ 거부
    e = world["ents"]["a"]
    for scn in ("mesh", "step"):
        s2 = seed_study(engine, esl_root, [e], scenario=scn)
        r = client.post(f"{API}/verify-drops", json=body(s2), headers=W)
        assert r.status_code == 422 and _code(r) == "VD_SCENARIO_UNSUPPORTED"
    # DONE 아님 → 409, best 없음 → 422
    s3 = seed_study(engine, esl_root, [e], phase="RUN")
    assert _code(client.post(f"{API}/verify-drops/plan", json=body(s3), headers=W)) == "RESULT_NOT_READY"
    s4 = seed_study(engine, esl_root, [e], best_files=False)
    assert _code(client.post(f"{API}/verify-drops/plan", json=body(s4), headers=W)) == "VD_DESIGN_NO_FILES"
    s5 = seed_study(engine, esl_root, [e], rank=4)                               # keep_files_top 3 밖
    assert _code(client.post(f"{API}/verify-drops/plan", json=body(s5), headers=W)) == "VD_DESIGN_NO_FILES"
    # 전부 제외 → 409 VD_NO_SCENES(excluded 동봉)
    d = world["ents"]["d"]
    s6 = seed_study(engine, esl_root, [d])
    r = client.post(f"{API}/verify-drops", json=body(s6), headers=W)
    assert r.status_code == 409 and _code(r) == "VD_NO_SCENES" and r.json()["detail"]["excluded"][0]["code"] == \
        "VD_CUMULATIVE_EXCLUDED"
    # all 이 상한 넘음
    more = [seed_case(engine, esl_root, inputs_root, n) for n in ("f", "g", "h")]
    ents = [world["ents"][k] for k in ("a", "b", "c")] + [seed_entry_for(engine, c["id"]) for c in more]
    s7 = seed_study(engine, esl_root, ents)
    r = client.post(f"{API}/verify-drops/plan", json=body(s7, "all"), headers=W)
    assert r.status_code == 422 and _code(r) == "VD_TOO_MANY_SCENES"
    # per_esl 이 순위 행에 없으면 post/per_esl.json
    s8 = seed_study(engine, esl_root, [world["ents"]["b"]], ratios={world["ents"]["b"]: 0.7}, inline=False)
    p = client.post(f"{API}/verify-drops/plan", json=body(s8), headers=W).json()
    assert p["scenes"][0]["r_c"] == pytest.approx(0.7)
    assert counts(engine) == (0, 0)


def test_layout_extract_and_include_exclusions(client, engine, esl_root, inputs_root):
    ok = seed_case(engine, esl_root, inputs_root, "ok")
    out = seed_case(engine, esl_root, inputs_root, "out", includes=["../shared/x.inc"],
                    extra_files={"../shared/x.inc": b"# outside rad folder\n"})
    absi = seed_case(engine, esl_root, inputs_root, "abs", includes=["/etc/hosts"])
    st = seed_case(engine, esl_root, inputs_root, "st", includes=["prev.sta"], extra_files={"prev.sta": b"#RADIOSS STATE FILE\n"})
    nox = seed_case(engine, esl_root, inputs_root, "nox", extract=False)
    cs = [ok, out, absi, st, nox]
    ents = [seed_entry_for(engine, c["id"]) for c in cs]
    sid = seed_study(engine, esl_root, ents, ratios={e: 1.0 + i * 0.01 for i, e in enumerate(ents)})
    p = client.post(f"{API}/verify-drops/plan", json=body(sid, "all"), headers=W).json()
    assert [s["case_id"] for s in p["scenes"]] == [ok["id"]]
    ex = {x["case_id"]: x for x in p["excluded"]}
    assert ex[out["id"]]["code"] == "VD_INCLUDE_LAYOUT" and "rad 폴더 밖" in ex[out["id"]]["reason"]
    assert ex[absi["id"]]["code"] == "VD_INCLUDE_LAYOUT" and "절대경로" in ex[absi["id"]]["reason"]
    assert ex[st["id"]]["code"] == "VD_CUMULATIVE_EXCLUDED"
    assert ex[nox["id"]]["code"] == "VD_CASE_NOT_READY"
    assert str(inputs_root) not in str(p)


def test_permissions_and_disabled(client, world, fake_relay, settings_dict):
    sid = world["sid"]
    assert client.post(f"{API}/verify-drops/plan", json=body(sid), headers=H("tok-general", True)).status_code == 403
    assert client.post(f"{API}/verify-drops", json=body(sid), headers=H("tok-nonmember", True)).status_code == 403
    assert client.post(f"{API}/verify-drops", json=body(sid), headers=R).status_code == 403     # CSRF 헤더 없음
    fake_relay.writes_active = False
    r = client.post(f"{API}/verify-drops", json=body(sid), headers=W)
    assert r.status_code == 503 and _code(r) == "SCX_UNAVAILABLE" and r.json()["detail"]["reason_code"] == "SCX_WRITES_OFF"
    fake_relay.writes_active = True
    st = client.get(f"{API}/scx/status", params={"project_id": "p-1"}, headers=R).json()
    assert st["verify"] == {"enabled": True, "reason_code": None, "reason": None}

