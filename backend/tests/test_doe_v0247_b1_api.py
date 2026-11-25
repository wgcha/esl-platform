"""v0.24.7 B1 — 깊이 단면 동작 depth_section 백엔드(계약 esl_bead_depth_mode.md §1.1·§4.3·§5·§5.2·§6·§6.1, V-0247-DM-15·24의 백엔드 부분).

- 요청: 모르는 값 422(생성·복제), select 밖 depth_section 422, 복제 본문 {title?, depth_section?} 모르는 키 422.
- 스냅샷: 새 select 스터디 params.doe.depth_section(+rules) == inputs 같은 값(floor_fixed 만 키 — entry_fixed 는 어떤 문서에도 키 없음).
- 복제(§6.1 표 전부): 키 결정 = section.clone_depth, spec_prefill = 원 doe.spec, dropped·DS_CLONE_NOTE, 보존 항목(선택 sha·shape_rules·
  load_transfer·rank), 깊이 동작을 안 바꾼 복제 = 지금 복제와 같은 스냅샷(spec_prefill 만 추가).
- 설정: DEFAULTS·pydantic·yaml 2개 거울, GET /doe/settings.depth_section.
- derive: 스냅샷 depth_section·section_rules 통과(코어가 받을 때만), 응답 beads[].w_reason{code, text}(옛 스터디도 응답 때).
코어 ``esl.doe.bead_graph`` 는 test_doe_select_graph_api 와 같은 대역(fake) — 여기서는 params·w_reason 을 내는 판으로 바꿔 쓴다.
"""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from doe_support import api, update_study, upload_step
from esl_test_support import REPO
from sqlalchemy import text
from test_doe_select_api import (  # noqa: F401 - 픽스처 재사용
    _fake_core,
    _job,
    _row,
    code,
    es,
    selection,
    sbody,
    settings_dict,
    simulate_select_prep,
    world,
)
from test_doe_select_graph_api import (  # noqa: F401
    _create,
    _fake_graph,
    derive,
    gbead,
    put,
    ready2,
    sel2,
    write_graph,
)

KW: list[dict] = []        # 코어(대역) derive_v2 가 받은 깊이 키


def _fake_derive_v2(mesh, norm, cfg, graph, labels, *, frame=None, fixed_scan=None, bead=None, depth_section=None,
                    section_rules=None):
    """test_doe_select_graph_api.fake_derive_v2 + 깊이 키 기록 + params·param_beads(b2 의 W = 한쪽 입구 W1) + w_reason 코드."""
    from test_doe_select_graph_api import fake_derive_v2

    KW.append({"depth_section": depth_section, "section_rules": copy.deepcopy(section_rules)})
    d = fake_derive_v2(mesh, norm, cfg, graph, labels, frame=frame, fixed_scan=fixed_scan, bead=bead)
    params, pbeads = [], []
    for b in d["beads"]:
        if b.get("src") != "graph":
            continue
        # 코어는 W 가 없는 비드에 사유 코드를 줌(여기서는 b3 = W 없음)
        b["w_reason"] = "W_ENTRY_NONE" if b["id"] == "b3" else None
        pbeads.append({"id": b["id"], "name": b["name"], "kind": "select", "src": "graph", "n_tiers": 1, "W_nom": b["W_nom"],
                       "w_reason": b["w_reason"], "warnings": []})
        for kind in ("D", "W"):
            if kind == "W" and b["id"] == "b3":
                continue
            row = {"name": f"{b['id'].upper()}_{kind}", "type": kind, "bead": b["id"], "tier": 1, "nominal": 4.0 if kind == "D" else 40.0,
                   "feasible": [1.0, 8.0], "feasible_source": "estimate", "default_range": [2.0, 6.0], "use_default": True,
                   "group_members": [f"{b['id'].upper()}_{kind}"]}
            if depth_section == "floor_fixed" and kind == "D":
                row["section"] = {"mode": "floor_fixed", "cot_deg": 45.0, "applied": True}
            if depth_section == "floor_fixed" and kind == "W" and b["id"] == "b2":
                row["w_side"] = "one"
            params.append(row)
    d["params"], d["param_beads"] = params, pbeads
    return d


@pytest.fixture(autouse=True)
def _core(_fake_graph, monkeypatch):  # noqa: F811
    _fake_graph.derive_v2 = _fake_derive_v2
    KW.clear()
    yield


def _doe(engine, st):
    return _job(engine, st["job"]["id"])["params"]["doe"]


def _full(engine, st):
    return _job(engine, st["job"]["id"])["params"]


def _saved(client, world, engine, esl_root, **kw):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root, **kw)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12), gbead("b3", 13, vars=["D"]))
    r = put(client, s, sel)
    assert r.status_code == 200, r.text
    return api(client, "GET", f"/doe/studies/{s['id']}").json(), sha


def _legacy(engine, st):
    """v0.24.6 이전 스냅샷 흉내 — 작업·inputs 의 depth 키 삭제(옛 스터디)."""
    with engine.begin() as cn:
        cn.execute(text("UPDATE jobs SET params = jsonb_set(params, '{doe}', (params->'doe') - 'depth_section' - 'depth_section_rules') "
                        "WHERE id=:i"), {"i": st["job"]["id"]})
        cn.execute(text("UPDATE bead_does SET inputs = (inputs - 'depth_section') - 'depth_section_rules' WHERE id=:i"), {"i": st["id"]})


# ================================================================ 요청 검사
def test_unknown_depth_section_422(client, world, engine, esl_root):  # noqa: F811
    for bad in ("both", "FLOOR_FIXED", "", 1, True):
        r = api(client, "POST", "/doe/studies", json=sbody(world, depth_section=bad))
        assert r.status_code == 422, (bad, r.text)
    s, _ = ready2(client, world, engine, esl_root)
    for bad in ("both", "", 1):
        r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": bad})
        assert r.status_code == 422, (bad, r.text)
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"title": "x", "mode": "floor_fixed"})
    assert r.status_code == 422                                                   # 모르는 키
    assert api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": None}).status_code == 201


def test_depth_section_outside_select_422(client, world, engine, esl_root):  # noqa: F811
    uid = upload_step(client)
    body = {"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"], world["b"]], "step_upload_id": uid}
    r = api(client, "POST", "/doe/studies", json={**body, "depth_section": "floor_fixed"})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    ok = api(client, "POST", "/doe/studies", json=body)
    assert ok.status_code == 201, ok.text
    assert "depth_section" not in ok.json()["inputs"]                              # select 밖 응답에는 키 없음
    r = api(client, "POST", f"/doe/studies/{ok.json()['id']}/clone", json={"depth_section": "entry_fixed"})
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"


# ================================================================ 스냅샷 = inputs (V-0247-DM-15)
def test_snapshot_equals_inputs_floor_default(client, world, engine, esl_root):  # noqa: F811
    cfg = api(client, "GET", "/doe/settings").json()
    assert cfg["depth_section"] == "floor_fixed"
    s = _create(client, world)                                                     # 요청 없음 = 설정(floor_fixed)
    d = _doe(engine, s)
    assert d["depth_section"] == "floor_fixed" and s["inputs"]["depth_section"] == "floor_fixed"
    assert d["depth_section_rules"] == s["inputs"]["depth_section_rules"]
    from esl_platform.core.config import BeadDoeCfg

    assert d["depth_section_rules"] == BeadDoeCfg().model_dump()["depth_section_rules"]
    row = _row(engine, s["id"])
    assert row["inputs"]["depth_section"] == "floor_fixed" and row["inputs"]["depth_section_rules"] == d["depth_section_rules"]


def test_entry_fixed_writes_no_key_anywhere(client, world, engine, esl_root):  # noqa: F811
    s = _create(client, world, depth_section="entry_fixed")                        # 명시 entry_fixed = 옛 스냅샷과 같은 모양
    p = _full(engine, s)
    assert "depth_section" not in p["doe"] and "depth_section_rules" not in p["doe"]
    assert "depth_section" not in json.dumps(p["warnings"])
    row = _row(engine, s["id"])
    assert "depth_section" not in row["inputs"] and "depth_section_rules" not in row["inputs"]
    assert s["inputs"]["depth_section"] is None and s["inputs"]["spec_prefill"] is None      # 응답만 null(옛·입구 고정 = 이전)


def test_request_overrides_setting(client, world, engine, esl_root, settings_dict):  # noqa: F811
    s = _create(client, world, depth_section="floor_fixed")
    assert _doe(engine, s)["depth_section"] == "floor_fixed"


@pytest.mark.parametrize("cfg_val", ["entry_fixed"])
def test_setting_entry_fixed_makes_old_style_snapshot(client, world, engine, esl_root, settings_dict, cfg_val):  # noqa: F811
    from esl_platform.api.services import doe as svc

    settings_dict["bead_doe"]["depth_section"] = cfg_val
    # 설정 파일을 다시 읽는 기존 시험 규칙을 따르지 않고 서비스 함수로 직접 확인(요청 없음 + 설정 entry_fixed → (None, None))
    class _B:
        scenario = "select"
        depth_section = None

    assert svc._depth_section_for_new({"depth_section": "entry_fixed", "depth_section_rules": {"x": 1}}, _B) == (None, None)
    _B.depth_section = "floor_fixed"
    assert svc._depth_section_for_new({"depth_section": "entry_fixed", "depth_section_rules": {"x": 1}}, _B) == \
        ("floor_fixed", {"x": 1})


# ================================================================ 설정 거울 (V-0247-DM-14·15 백엔드 부분)
def _flat(d, p=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{p}{k}."))
        else:
            out[f"{p}{k}"] = v
    return out


def test_depth_section_settings_mirror():
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg

    m = BeadDoeCfg().model_dump()
    assert m["depth_section"] == DEFAULTS["depth_section"] == "floor_fixed"
    assert m["depth_section_rules"] == DEFAULTS["depth_section_rules"]
    assert set(m["depth_section_rules"]) == {"theta_min_deg", "theta_spread_deg", "one_side_min_nodes", "entry_smooth_rel", "entry_gap_rel"}
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["depth_section"] == m["depth_section"], p
        assert y["depth_section_rules"] == m["depth_section_rules"], p
        got = BeadDoeCfg.model_validate(y).model_dump()
        assert got["depth_section"] == m["depth_section"] and got["depth_section_rules"] == m["depth_section_rules"]
    for bad in ({"depth_section": "both"}, {"depth_section_rules": {"one_side_min_nodes": 0}},
                {"depth_section_rules": {"one_side_min_nodes": 21}}):
        with pytest.raises(Exception):
            BeadDoeCfg.model_validate(bad)


def test_settings_out_depth_section(client, world):  # noqa: F811
    s = api(client, "GET", "/doe/settings").json()
    assert s["depth_section"] == "floor_fixed"


# ================================================================ 복제 (V-0247-DM-24)
def test_clone_unchanged_keeps_snapshot_bytes(client, world, engine, esl_root):  # noqa: F811
    """깊이 동작을 안 바꾼 복제 = 지금 복제와 같은 스냅샷(spec_prefill 만 추가). 옛(키 없음)·floor 둘 다."""
    for legacy in (True, False):
        s, _ = _saved(client, world, engine, esl_root)
        if legacy:
            _legacy(engine, s)
        spec = {"method": "lhs", "n": 4, "seed": 7, "params": [{"name": "B1_D", "lo": 3.0, "hi": 5.0}]}
        update_study(engine, s["id"], doe={"rev": 1, "spec": spec, "matrix_sha256": "a" * 64, "n_designs": 4})
        s = api(client, "GET", f"/doe/studies/{s['id']}").json()
        for body in (None, {}, {"depth_section": "floor_fixed" if not legacy else "entry_fixed"}):
            c = api(client, "POST", f"/doe/studies/{s['id']}/clone", **({} if body is None else {"json": body}))
            assert c.status_code == 201, c.text
            c = c.json()
            old, new = _doe(engine, s), _doe(engine, c)
            for k in ("depth_section", "depth_section_rules"):
                assert (k in old) == (k in new) and old.get(k) == new.get(k)
            assert (("depth_section" in new) is (not legacy))
            assert c["inputs"]["spec_prefill"] == spec
            w = _job(engine, c["job"]["id"])["warnings"]
            assert "DS_CLONE_NOTE" not in [x["code"] for x in w]
            ri = _row(engine, c["id"])["inputs"]
            assert ("depth_section" in ri) is (not legacy)
            assert {k: v for k, v in ri.items() if k != "spec_prefill"} == \
                {k: v for k, v in _row(engine, s["id"])["inputs"].items() if k not in ("spec_prefill", "rank_metric")} | \
                {"rank_metric": ri["rank_metric"]}


def test_clone_old_to_floor(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    _legacy(engine, s)
    sel0 = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": "floor_fixed"})
    assert c.status_code == 201, c.text
    c = c.json()
    d = _doe(engine, c)
    from esl_platform.core.config import BeadDoeCfg

    assert d["depth_section"] == "floor_fixed" and d["depth_section_rules"] == BeadDoeCfg().model_dump()["depth_section_rules"]
    assert c["inputs"]["depth_section"] == "floor_fixed" and c["inputs"]["depth_section_rules"] == d["depth_section_rules"]
    # 선택 문서·sha 원과 같음(보존 항목 — 같은 sha), shape_rules·load_transfer 원 블록 그대로(w_partial 주입 없음)
    assert c["selection"]["sha256"] == sel0["sha256"]
    old = _doe(engine, s)
    for k in ("shape_rules", "load_transfer", "entry_ids", "select_schema"):
        assert old.get(k) == d.get(k), k
    assert c["inputs"].get("shape_rules") == s["inputs"].get("shape_rules")
    w = [x for x in _job(engine, c["job"]["id"])["warnings"] if x["code"] == "DS_CLONE_NOTE"]
    assert len(w) == 1 and w[0]["from"] == "entry_fixed" and w[0]["to"] == "floor_fixed" and w[0]["dropped"] == []
    assert "깊이 동작만 바뀝니다" in w[0]["message"]
    # 복제의 복제(같은 값) = 경고 물려주지 않음
    c2 = api(client, "POST", f"/doe/studies/{c['id']}/clone", json={}).json()
    assert "DS_CLONE_NOTE" not in [x["code"] for x in _job(engine, c2["job"]["id"])["warnings"]]
    assert _doe(engine, c2)["depth_section"] == "floor_fixed"


def test_clone_floor_to_entry_drops_w1(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    assert _doe(engine, s)["depth_section"] == "floor_fixed"
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    assert [x["name"] for x in p["params"] if x.get("w_side") == "one"] == ["B2_W"]                 # 응답 행 w_side
    assert [x["name"] for x in p["params"] if x["type"] == "D"] and all(
        x["section"]["mode"] == "floor_fixed" for x in p["params"] if x["type"] == "D")
    spec = {"method": "lhs", "n": 4, "seed": 3, "params": [
        {"name": "B1_D", "lo": 3.0, "hi": 5.0}, {"name": "B2_W", "lo": 30.0, "hi": 50.0}, {"name": "B2_D", "lo": 3.0, "hi": 5.0}]}
    update_study(engine, s["id"], doe={"rev": 1, "spec": spec, "matrix_sha256": "b" * 64, "n_designs": 4})
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": "entry_fixed"})
    assert c.status_code == 201, c.text
    c = c.json()
    d = _doe(engine, c)
    assert "depth_section" not in d and "depth_section_rules" not in d                           # 두 키 삭제
    ri = _row(engine, c["id"])["inputs"]
    assert "depth_section" not in ri and "depth_section_rules" not in ri
    assert [x["name"] for x in c["inputs"]["spec_prefill"]["params"]] == ["B1_D", "B2_D"]       # W1 변수 제외
    assert {k: v for k, v in c["inputs"]["spec_prefill"].items() if k != "params"} == {k: v for k, v in spec.items() if k != "params"}
    w = [x for x in _job(engine, c["job"]["id"])["warnings"] if x["code"] == "DS_CLONE_NOTE"]
    assert len(w) == 1 and w[0]["from"] == "floor_fixed" and w[0]["to"] == "entry_fixed" and w[0]["dropped"] == ["B2_W"]
    assert "B2_W" in w[0]["message"] and "1개" in w[0]["message"]
    # 원 스터디 spec 은 그대로(복제는 prefill 만 자름)
    assert api(client, "GET", f"/doe/studies/{s['id']}").json()["doe"]["spec"] == spec


def test_clone_floor_to_entry_without_spec(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": "entry_fixed"}).json()
    assert c["inputs"]["spec_prefill"] is None and "spec_prefill" not in _row(engine, c["id"])["inputs"]     # spec 없던 스터디 = 키 없음
    w = [x for x in _job(engine, c["job"]["id"])["warnings"] if x["code"] == "DS_CLONE_NOTE"]
    assert len(w) == 1 and w[0]["dropped"] == []


def test_clone_rank_refresh_rule_unchanged(client, world, engine, esl_root):  # noqa: F811
    """rank·cfg 는 지금 복제 규칙 그대로(깊이 요청과 무관) — rank 키가 있으면 갱신 판정은 RANK_REFRESHED 만."""
    s, _ = _saved(client, world, engine, esl_root)
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": "entry_fixed"}).json()
    codes = [x["code"] for x in _job(engine, c["job"]["id"])["warnings"]]
    assert set(codes) <= {"DS_CLONE_NOTE", "RANK_REFRESHED"}


def test_clone_depth_pure_table():
    from esl.morph import section as sec

    r = {"theta_min_deg": 15.0, "theta_spread_deg": 5.0, "one_side_min_nodes": 3}
    a = sec.clone_depth({}, None, rules_now=r)
    assert a["keys"] is None and not a["changed"]
    b = sec.clone_depth({}, "floor_fixed", rules_now=r)
    assert b["keys"] == {"depth_section": "floor_fixed", "depth_section_rules": r} and b["changed"]
    cc = sec.clone_depth({"depth_section": "floor_fixed", "depth_section_rules": r, "spec": {"params": [{"name": "B2_W"}]}},
                         "entry_fixed", rules_now=r, w1_names=["B2_W"])
    assert cc["keys"] is None and cc["dropped"] == ["B2_W"]
    dd = sec.clone_depth({"depth_section": "floor_fixed", "depth_section_rules": {"one_side_min_nodes": 5}}, "floor_fixed", rules_now=r)
    assert dd["keys"]["depth_section_rules"] == {"one_side_min_nodes": 5} and not dd["changed"]


# ================================================================ derive 통과 · w_reason (§4.3·§6)
def test_derive_passes_snapshot_depth_to_core(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)                             # floor_fixed(설정 기본)
    sel = sel2(sha, gbead("b1", 11))
    assert derive(client, s, sel).status_code == 200
    assert KW[-1]["depth_section"] == "floor_fixed"
    assert KW[-1]["section_rules"] == s["inputs"]["depth_section_rules"]
    # 옛·입구 고정 스냅샷 = None(코어가 entry_fixed 로 해석), 캐시를 공유하지 않음
    _legacy(engine, s)
    from esl_platform.api.services import doe_select

    doe_select.reset_caches()
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert derive(client, s, sel).status_code == 200
    assert KW[-1] == {"depth_section": None, "section_rules": None}


def test_w_reason_in_derive_and_params(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), gbead("b3", 13, vars=["D"]))
    d = derive(client, s, sel).json()
    wr = {b["id"]: b["w_reason"] for b in d["beads"]}
    assert wr["b1"] is None
    assert wr["b3"]["code"] == "W_ENTRY_NONE" and wr["b3"]["text"] and wr["b3"]["text"] != "W_ENTRY_NONE"      # 문구 = doe_messages.json
    assert put(client, s, sel).status_code == 200
    # DB 요약에는 코드 문구(text)를 저장하지 않음(응답 때만)
    stored = _row(engine, s["id"])["selection"]["derived"]
    assert all(not isinstance(b.get("w_reason"), dict) for b in stored["beads"])
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    pb = {b["id"]: b for b in p["beads"]}
    assert pb["b1"]["w_reason"] is None and pb["b3"]["w_reason"]["code"] == "W_ENTRY_NONE"
    # 옛 스터디(저장 요약에 사유 없음)도 응답 때 계산: 저장 요약에서 w_reason 을 빼도 같은 응답
    with engine.begin() as cn:
        cn.execute(text("UPDATE bead_does SET selection = jsonb_set(selection, '{derived,param_beads}', "
                        "(SELECT jsonb_agg(e - 'w_reason') FROM jsonb_array_elements(selection->'derived'->'param_beads') e)) "
                        "WHERE id=:i"), {"i": s["id"]})
    from esl_platform.api.services import doe_select

    doe_select.reset_caches()
    p2 = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    assert {b["id"]: b["w_reason"] for b in p2["beads"]} == {b["id"]: b["w_reason"] for b in p["beads"]}
    g = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()["derived"]["beads"]
    assert {b["id"]: b.get("w_reason") for b in g}["b3"]["code"] == "W_ENTRY_NONE"


def test_w_reason_doc_unit():
    from esl_platform.api.services import doe_select as ds

    assert ds.w_reason_doc(None) is None and ds.w_reason_doc("") is None
    assert ds.w_reason_doc("W_NETWORK")["code"] == "W_NETWORK" and ds.w_reason_doc({"code": "W_AREA"})["code"] == "W_AREA"
    beads = [{"id": "b1", "src": "graph"}, {"id": "b2", "src": "elems"}, {"id": "b3"}]
    out = ds.with_w_reason(beads, {"b1": "W_NETWORK"})
    assert out[0]["w_reason"]["code"] == "W_NETWORK" and "w_reason" not in out[1] and "w_reason" not in out[2]


# ================================================================ OpenAPI
def test_openapi_has_depth_section():
    doc = json.loads((REPO / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sch = doc["components"]["schemas"]
    assert "depth_section" in sch["DoeSettingsOut"]["properties"]
    assert "depth_section" in sch["DoeStudyIn"]["properties"]
    ci = sch["DoeCloneIn"]
    assert set(ci["properties"]) == {"title", "depth_section"} and ci.get("additionalProperties") is False
