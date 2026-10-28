"""V-OR-7 금지 영역 세트 API(계약 esl_opt_run.md OR-D-11·12, §5.1·§7.5): 템플릿/topo 키 저장·불러오기, version 충돌 409,
frame 차이 경고, 사각형 검사(KEEPOUT_INVALID), 실행 스냅샷이 이후 세트 수정에 영향 없음, 템플릿 삭제 시 세트 삭제·보관 시 유지."""

from __future__ import annotations

import pytest
from esl_test_support import API, H
from opt_support import R, W, make_case, opt_settings_dict, plate, register_template, run_body, seed_opt_entry
from sqlalchemy import text

RECT = {"name": "PCB", "corner": "a0b0", "x_mm": 120.0, "y_mm": 80.0, "w_mm": 100.0, "h_mm": 60.0}


@pytest.fixture()
def settings_dict(tmp_path):
    return opt_settings_dict(tmp_path)


def _topo(client, eid):
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [eid]}, headers=W)
    assert r.status_code == 200, r.text
    return r.json()["base"]["topo_sha256"]


def test_topo_set_save_load_version_conflict(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    topo = _topo(client, eid)
    g = client.get(f"{API}/opt/keepouts", params={"topo": topo}, headers=R)
    assert g.status_code == 404 and g.json()["detail"]["code"] == "KEEPOUT_NOT_FOUND"
    body = {"topo_sha256": topo, "rects": [RECT], "auto": {"hole": True, "edge": False}}
    assert client.put(f"{API}/opt/keepouts", json=body, headers=H("tok-general", True)).status_code == 403
    assert client.put(f"{API}/opt/keepouts", json=body, headers=H("tok-nonmember", True)).status_code == 403
    r = client.put(f"{API}/opt/keepouts", json=body, headers=W)
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["version"] == 1 and k["key"] == {"template_id": None, "topo_sha256": topo}
    assert k["rects"] == [RECT] and k["auto"] == {"hole": True, "edge": False} and k["updated_by_name"] == "파워"
    assert k["frame"]["a_range"] == pytest.approx([-150.0, 150.0]) and k["warnings"] == []
    got = client.get(f"{API}/opt/keepouts", params={"topo": topo}, headers=H("tok-general")).json()
    assert got["rects"] == [RECT] and got["version"] == 1
    assert client.get(f"{API}/opt/keepouts", params={"topo": topo}, headers=H("tok-nonmember")).status_code == 404
    # 갱신: version 필수·일치
    r = client.put(f"{API}/opt/keepouts", json={**body, "rects": []}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    r = client.put(f"{API}/opt/keepouts", json={**body, "rects": [], "version": 1}, headers=W)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["rects"] == []
    r = client.put(f"{API}/opt/keepouts", json={**body, "version": 1}, headers=H("tok-power2", True))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "VERSION_CONFLICT"
    # frame 차이 경고(저장 frame 을 2 mm 옮김)
    with engine.begin() as c:
        c.execute(text("UPDATE opt_keepouts SET frame = '{\"a_range\": [-152.0, 150.0], \"b_range\": [-100.0, 100.0]}'"))
    w = client.get(f"{API}/opt/keepouts", params={"topo": topo}, headers=R).json()["warnings"]
    assert w and "모델 경계가 달라짐" in w[0]
    # 키 검사
    assert client.put(f"{API}/opt/keepouts", json={"rects": []}, headers=W).status_code == 422
    assert client.get(f"{API}/opt/keepouts", headers=R).status_code == 422
    r = client.put(f"{API}/opt/keepouts", json={"topo_sha256": "0" * 64, "rects": []}, headers=W)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "ENTRY_NOT_FOUND"


def test_rect_validation(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    topo = _topo(client, eid)
    bad = [{**RECT, "x_mm": -1}, {**RECT, "w_mm": 0}, {**RECT, "corner": "zz"}, {**RECT, "name": "x" * 41},
           {**RECT, "x_mm": 400.0}]                                            # 마지막: 경계 밖 완전 이탈
    for rect in bad:
        r = client.put(f"{API}/opt/keepouts", json={"topo_sha256": topo, "rects": [rect]}, headers=W)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "KEEPOUT_INVALID", (rect, r.text)
    r = client.put(f"{API}/opt/keepouts", json={"topo_sha256": topo, "rects": [RECT] * 21}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "KEEPOUT_INVALID"
    # 일부만 밖: 저장 + 경고, 4 기준 모서리 모두 허용
    part = [{**RECT, "corner": c, "name": c, "x_mm": 250.0} for c in ("a0b0", "a1b0", "a0b1", "a1b1")]
    r = client.put(f"{API}/opt/keepouts", json={"topo_sha256": topo, "rects": part}, headers=W)
    assert r.status_code == 200 and len(r.json()["warnings"]) == 4
    # 실행 생성도 같은 검사
    r = client.post(f"{API}/opt/runs", json=run_body([eid], design={"keepout": {"rects": [bad[0]]}}), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "KEEPOUT_INVALID"


def test_run_snapshot_independent_of_later_set_changes(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    topo = _topo(client, eid)
    client.put(f"{API}/opt/keepouts", json={"topo_sha256": topo, "rects": [RECT]}, headers=W)
    run = client.post(f"{API}/opt/runs", json=run_body([eid], design={"keepout": {"rects": [RECT],
                                                                                    "auto": {"hole": False}}}),
                      headers=W).json()
    assert run["design"]["keepout"] == {"rects": [RECT], "auto": {"hole": False, "edge": True}}
    r = client.put(f"{API}/opt/keepouts", json={"topo_sha256": topo, "rects": [], "version": 1}, headers=W)
    assert r.status_code == 200
    again = client.get(f"{API}/opt/runs/{run['id']}", headers=R).json()
    assert again["design"]["keepout"]["rects"] == [RECT]
    with engine.connect() as c:
        p = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": run["job"]["id"]}).scalar_one()
    assert p["design"]["keepout"]["rects"] == [RECT]


def test_template_set_deleted_with_template_kept_when_archived(client, engine, esl_root, inputs_root, tmp_path):
    t1 = register_template(client, tmp_path, title="미사용")
    t2 = register_template(client, tmp_path, title="사용")
    for t in (t1, t2):
        r = client.put(f"{API}/opt/keepouts", json={"template_id": t["id"], "rects": [RECT]},
                       headers=H("tok-power2", True))                      # 템플릿 세트 = 아무 프로젝트 power
        assert r.status_code == 200, r.text
    assert client.put(f"{API}/opt/keepouts", json={"template_id": t1["id"], "rects": []},
                      headers=H("tok-general", True)).status_code == 403
    got = client.get(f"{API}/opt/keepouts", params={"template_id": t1["id"]}, headers=H("tok-nonmember"))
    assert got.status_code == 200 and got.json()["rects"] == [RECT]          # 템플릿 세트 조회 = 누구나
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    assert client.post(f"{API}/opt/runs", json=run_body([eid], "S2", template_id=t2["id"]), headers=W).status_code == 201
    assert client.delete(f"{API}/opt/templates/{t1['id']}", headers=W).json() == {"deleted": True, "archived": False}
    assert client.delete(f"{API}/opt/templates/{t2['id']}", headers=W).json() == {"deleted": False, "archived": True}
    with engine.connect() as c:
        keys = {r[0] for r in c.execute(text("SELECT template_id FROM opt_keepouts"))}
    assert keys == {t2["id"]}
    g = client.get(f"{API}/opt/keepouts", params={"template_id": t2["id"]}, headers=R)
    assert g.status_code == 200 and g.json()["rects"] == [RECT]
    r = client.put(f"{API}/opt/keepouts", json={"template_id": t2["id"], "rects": [], "version": 1}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TEMPLATE_ARCHIVED"
    assert client.get(f"{API}/opt/keepouts", params={"template_id": t1["id"]}, headers=R).status_code == 404


def test_template_plan_view_matches_preview(client, tmp_path):
    from esl.library import normalize as nz
    from esl.opt import keepout, settings

    t = register_template(client, tmp_path, mesh=plate())
    pv = client.get(f"{API}/opt/plan-view", params={"template_id": t["id"]}, headers=H("tok-nonmember"))
    assert pv.status_code == 200, pv.text
    m = plate()
    exp = keepout.plan_view(m, nz.frame(m["x0"], None, m["conn"], m["elem_type"]), settings()["keepout"], 20000)
    got = pv.json()
    assert got["key"] == {"template_id": t["id"], "topo_sha256": None}
    assert got["auto_keepout"]["counts"] == exp["auto_keepout"]["counts"] and got["elems"]["n_total"] == 96
    assert client.get(f"{API}/opt/plan-view", params={"template_id": "nope"}, headers=R).status_code == 404
