"""v0.17.0 BEADGRAPH API(계약 esl_beadgraph.md §5·§6.1, V-BG-15 + V-BG-12 의 백엔드 부분).

- 설정: select.graph(pydantic·yaml 2개 거울 — test_doe_select_api.test_select_defaults_mirror_contract), GET /doe/settings
  select.graph{enabled, island.max_mm, sym_tol_mm}, scenarios.select_auto = select 가능 ∧ graph.enabled(paicad 무관).
- 입력: auto + STEP 없음 허용(schema 2), 새 select 스터디 = inputs.select_schema 2·작업 doe.select_schema 2, 복제 = 원 schema 유지.
- GET …/select/graph: 404 GRAPH_NOT_AVAILABLE(schema 1·분류 실패), 409 PREP_NOT_READY, 응답 형식·sha256(graph.json 바이트).
- graph.bin = select/view 허용 파일(ETag = graph.json sha, 304).
- 선택 schema 2: 구조 검사 422, schema 혼용 422 SELECT_SCHEMA_MISMATCH, 409 BG_GRAPH_STALE(derive·저장·저장 뒤 분류 변경), 코어 422
  코드 5종 전달, 저장·조회·변수 표(B<n>_D·B<n>_W·elems B<n>_D<k>·ties), 자동 seed(source graph·hints·sha = 저장 sha), 준비 요약 graph.
- schema 1: SelectionIn dump 바이트 불변(v0.16.2 모델과 같은 dict), schema 1 스터디 경로는 test_doe_select_api 전부(회귀).

코어 ``esl.doe.bead_graph``(Impl-Core 병렬 구현)는 계약 §8.6 시그니처 대로 동작하는 대역(fake)을 ``sys.modules`` 에 넣는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import types

import numpy as np
import pytest
from doe_support import api, finish_job, record_paicad, study_dir, update_study, upload_step
from esl_test_support import API, H
from sqlalchemy import text
from test_doe_select_api import (  # noqa: F401 - 픽스처 재사용(코어 bead_select 대역·세계)
    _err,
    _fake_core,
    _job,
    _row,
    bead,
    code,
    es,
    sbody,
    selection,
    settings_dict,
    simulate_select_prep,
    world,
)

GRAPH = {
    "schema": "beadgraph/1", "version": "1.0.0", "rules": 1, "morph_rules": 1,
    "input": {"n_nodes": 0, "n_elems": 0, "n_tri": 0, "n_fixed": 0, "sha256": "0" * 64},
    "cfg": {}, "cfg_sha256": "1" * 64, "frame": {"n0": [0, 0, 1], "e1": [1, 0, 0], "e2": [0, 1, 0], "h_mm": 10.0},
    "root": 0, "root_group": [0],
    "floors": [{"id": 0, "anchor": 0, "kind": "base"}, {"id": 1, "anchor": 1, "kind": "bead"}],
    "transitions": [], "networks": [{"id": 0, "floor": 1, "segments": [0, 1, 2], "junction_zones": [0]}],
    "segments": [{"id": 0, "anchor": 11, "floor": 1, "network": 0, "type": "ring", "side": "top", "tier": 1, "D": 4.0,
                  "entry_width": 40.0, "length": 200.0},
                 {"id": 1, "anchor": 12, "floor": 1, "network": 0, "type": "ring", "side": "bottom", "tier": 1, "D": 4.0,
                  "entry_width": 40.0, "length": 200.0},
                 {"id": 2, "anchor": 13, "floor": 1, "network": 0, "type": "leg", "side": None, "tier": 1, "D": 4.2,
                  "entry_width": 30.0, "length": 120.0}],
    "junctions": [], "junction_zones": [{"id": 0, "anchor": 20, "network": 0, "reason": "corner"}],
    "islands": [{"id": 0, "anchor": 30}], "holes": [],
    "warnings": [{"code": "GRAPH_RASTER_COARSE", "level": "info", "raster_mm": 2.0}],
}
GRAPH_BIN = b"\x10\x00\x00\x00" + b'{"n_elems":0}   ' + b"\x00" * 8
NORM2_IN: list[dict] = []
DERIVE2: list[dict] = []


# ================================================================ 코어 bead_graph 대역(계약 §5.1·§6.1 형식)
def fake_normalize_v2(sel, graph, cfg, *, mesh=None):
    NORM2_IN.append(copy.deepcopy(sel))
    anchors = {s["anchor"] for s in (graph or {}).get("segments") or []}
    nets = {f["anchor"] for f in (graph or {}).get("floors") or []} | anchors
    beads = []
    for b in sel.get("beads") or []:
        if b["src"] == "graph":
            for r in b["segs"]:
                if "anchor" in r and r["anchor"] not in anchors:
                    raise _err("BG_SEG_UNKNOWN", "앵커 없음", anchor=r["anchor"])
                if "network" in r and r["network"] not in nets:
                    raise _err("BG_SEG_UNKNOWN", "네트워크 앵커 없음", anchor=r["network"])
            if b.get("name") == "apart":
                raise _err("BG_GROUP_NOT_CONNECTED", "연결 안 됨", bead=b["id"])
            beads.append({"id": b["id"], "src": "graph", "segs": sorted(b["segs"], key=lambda r: json.dumps(r, sort_keys=True)),
                          **({"name": b["name"]} if b.get("name") else {}), **({"vars": b["vars"]} if b.get("vars") else {}),
                          **({"hold_fixed": 0} if b.get("hold_fixed") == 0 else {})})
        else:
            if b.get("name") == "overlap":
                raise _err("SELECT_OVERLAP", "겹침", bead=b["id"], elems_n=1)
            beads.append({k: v for k, v in b.items()})
    ed = ((sel.get("graph") or {}).get("edits")) or {}
    if any(t.get("anchor") not in anchors for t in ed.get("toggle") or []):
        raise _err("BG_EDIT_INVALID", "편집 앵커 없음", edit="toggle")
    for t in sel.get("ties") or []:
        if "b9" in t:
            raise _err("BG_TIE_NOMINAL", "공칭 차", beads=t)
    out = {"schema_version": 2, "feature_angle_deg": float(sel.get("feature_angle_deg") or cfg["select"]["feature_angle_deg"]),
           "graph": sel.get("graph"), "beads": sorted(beads, key=lambda x: int(x["id"][1:])), "ties": sel.get("ties") or [],
           "fixed_user": sel.get("fixed_user") or {"q": [], "t": []}, "exclude": sel.get("exclude") or {"q": [], "t": []}}
    if out["graph"] is None:
        out.pop("graph")
    sha = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return out, sha


def fake_derive_v2(mesh, norm, cfg, graph, labels, *, frame=None, fixed_scan=None, bead=None):
    DERIVE2.append({"bead": bead, "labels": sorted(labels) if isinstance(labels, dict) else None})
    segs = {s["anchor"]: s for s in (graph or {}).get("segments") or []}
    beads = []
    for b in norm["beads"]:
        if bead is not None and b["id"] != bead:
            continue
        if b["src"] == "graph":
            ss = [segs[r["anchor"]] for r in b["segs"] if "anchor" in r]
            beads.append({"id": b["id"], "src": "graph", "name": b.get("name") or b["id"].upper(),
                          "segs": [r.get("anchor", r.get("network")) for r in b["segs"]],
                          "vars": b.get("vars") or ["D", "W"], "D_nom": 4.0, "W_nom": 40.0 if ss else None, "tier": 1,
                          "warnings": [{"code": "BG_SHARED_CHILD", "level": "info", "bead": b["id"], "child": 2,
                                        "n_nodes": 12}] if b["id"] == "b1" else [],
                          "plan": {"ring_ab": []}, "section": {"s": [0, 1]}})
        else:                       # elems 비드 = schema 1 derive 결과 형식(B<n>_D<k>)
            beads.append({"id": b["id"], "name": b.get("name") or b["id"].upper(), "src": "elems", "tiers": [
                {"k": 1, "n_elems": 4, "D_nom": 6.0}], "W_nom": 30.0, "boundary": {"loops": [{"closed": True}]},
                "range_default": {"D": {"1": [4.2, 7.8]}, "W": [24.0, 36.0]}, "warnings": [], "plan": {}, "section": {}})
    return {"beads": beads, "fixed": {"scan_n": len(fixed_scan) if fixed_scan is not None else 0, "user_n": 0,
                                      "source": "none"},
            "warnings": [], "graph_algo": 1,
            "graph": {"sha256": (norm.get("graph") or {}).get("sha256"), "graph_algo": 1,
                      "edits_applied": {"toggle": 0, "merge": 0, "split": 0},
                      "segments": [{k: s[k] for k in ("id", "anchor", "type", "side", "tier", "D", "entry_width", "length",
                                                       "network")} for s in (graph or {}).get("segments") or []],
                      "junction_zones": [{"id": 0, "anchor": 20, "reason": "corner"}],
                      "beads": [{"id": b["id"], "src": b["src"]} for b in beads], "sym_pairs": [[11, 12]]}}


@pytest.fixture(autouse=True)
def _fake_graph(monkeypatch):
    mod = types.ModuleType("esl.doe.bead_graph")
    mod.normalize_v2, mod.derive_v2 = fake_normalize_v2, fake_derive_v2
    monkeypatch.setitem(sys.modules, "esl.doe.bead_graph", mod)
    NORM2_IN.clear()
    DERIVE2.clear()
    yield mod


# ================================================================ 도우미
def _create(client, world, **kw):
    r = api(client, "POST", "/doe/studies", json=sbody(world, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def write_graph(esl_root, sid, graph=None, *, labels=True, bin_=True) -> str:
    """코어 BD_LOADS prep_graph 흉내: prep/select/graph.json(결정적 바이트)·graph_labels.npz·graph.bin → graph.json sha256."""
    sd = study_dir(esl_root, sid) / "prep" / "select"
    sd.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(graph or GRAPH, sort_keys=True, separators=(",", ":")).encode()
    (sd / "graph.json").write_bytes(raw)
    if labels:
        n = 8
        np.savez(sd / "graph_labels.npz", **{k: np.full(n, -1, dtype=np.int32) for k in
                                              ("cls", "floor", "segment", "transition", "island", "junction_zone", "tier")})
    if bin_:
        (sd / "graph.bin").write_bytes(GRAPH_BIN)
    return hashlib.sha256(raw).hexdigest()


def ready2(client, world, engine, esl_root, *, graph=True, **kw):
    """schema 2 스터디(v0.17.0 새 스터디) 준비 완료 + (graph) 분류 결과 → (스터디, graph sha | None)."""
    s = _create(client, world, **kw)
    assert s["inputs"]["select_schema"] == 2
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"], schema=2)
    sha = write_graph(esl_root, s["id"]) if graph else None
    return api(client, "GET", f"/doe/studies/{s['id']}").json(), sha


def sel2(gsha, *beads, edits=None, ties=None, **kw):
    g = {"sha256": gsha, "rules": 1, **({"edits": edits} if edits else {})} if gsha else None
    b = list(beads) or [{"id": "b1", "src": "graph", "segs": [{"anchor": 11}]}]
    return {"schema_version": 2, **({"graph": g} if g else {}), "beads": b, **({"ties": ties} if ties else {}), **kw}


def gbead(bid="b1", *anchors, **kw):
    return {"id": bid, "src": "graph", "segs": [{"anchor": a} for a in (anchors or (11,))], **kw}


def ebead(bid="b2", **kw):
    b = bead(bid, tiers=((20, 23),))
    return {**b, "src": "elems", **kw}


def put(client, s, sel, token="tok-power"):
    return api(client, "PUT", f"/doe/studies/{s['id']}/selection", token, json={"version": s["version"], "selection": sel})


def derive(client, s, sel, **kw):
    return api(client, "POST", f"/doe/studies/{s['id']}/select/derive", json={"selection": sel, **kw})


# ================================================================ 설정 · 입력(V-BG-15)
def test_settings_graph_block_and_select_auto_without_paicad(client, world, engine):
    from esl_platform.api.services import doe as svc

    s = api(client, "GET", "/doe/settings").json()
    assert s["select"]["graph"] == {"enabled": True, "island": {"max_mm": 60.0}, "sym_tol_mm": 0.5}
    assert s["select"]["island"]["max_mm"] == 40.0                  # schema 1 섬 상한은 그대로(O-BG-1)
    record_paicad(engine, ready=False, reason="PAICAD_NOT_FOUND")
    svc.reset_status_cache()
    s = api(client, "GET", "/doe/settings").json()
    assert s["enabled"] is False and s["scenarios"]["select_auto"] is True      # paicad 무관(D9)


def test_settings_graph_disabled_turns_off_select_auto(tmp_path, engine, fake_dashboard, clock):
    import httpx
    from doe_support import doe_settings_dict
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.api.services import doe as svc
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["select"] = {"graph": {"enabled": False, "island": {"max_mm": 55.0}, "sym_tol_mm": 0.25}}
    record_paicad(engine)
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    svc.reset_status_cache()
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        s = api(c, "GET", "/doe/settings").json()
    svc.reset_status_cache()
    assert s["scenarios"]["select"] is True and s["scenarios"]["select_auto"] is False
    assert s["select"]["graph"] == {"enabled": False, "island": {"max_mm": 55.0}, "sym_tol_mm": 0.25}


def test_config_rejects_bad_graph_values(tmp_path):
    from doe_support import doe_settings_dict
    from esl_platform.core.config import load_config_dict

    for bad in ({"feature_angle_deg": 50}, {"island": {"straddle_frac": 1.5}}, {"morph": {"ramp_k": 0.9}},
                {"limits": {"max_raster_px": 10}}):
        d = doe_settings_dict(tmp_path)
        d["bead_doe"]["select"] = {"graph": bad}
        assert not load_config_dict(d, environ={}).ok, bad


def test_auto_without_step_allowed_and_schema2_inputs(client, world, engine):
    """BG §5.3: auto + STEP 없음 = 허용(힌트 없음), auto + STEP = 힌트, manual + STEP 은 여전히 422. 새 스터디 schema 2."""
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, bead_source="auto"))
    assert r.status_code == 200, r.text
    assert r.json()["step"] is None and r.json()["base"]["case_id"] == "c1"
    s = _create(client, world, bead_source="auto")
    assert s["inputs"]["bead_source"] == "auto" and s["inputs"]["step"] is None and s["inputs"]["select_schema"] == 2
    jp = _job(engine, s["job"]["id"])["params"]["doe"]
    assert jp["select_schema"] == 2 and jp["bead_source"] == "auto" and "step" not in jp
    uid = upload_step(client)
    h = _create(client, world, bead_source="auto", step_upload_id=uid)
    assert h["inputs"]["step"]["upload_id"] == uid
    assert _job(engine, h["job"]["id"])["params"]["doe"]["step"]["path"].endswith(".step")
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, bead_source="manual", step_upload_id=uid))
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS"
    m = _create(client, world)
    assert m["inputs"]["select_schema"] == 2 and _job(engine, m["job"]["id"])["params"]["doe"]["select_schema"] == 2
    # 같은 모델이 아닌 시나리오에는 키 없음
    st = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "same",
                                                   "entry_ids": [world["a"], world["b"]], "step_upload_id": uid})
    assert st.status_code == 201 and "select_schema" not in st.json()["inputs"]


def test_clone_keeps_schema(client, world, engine, esl_root):
    s2, _ = ready2(client, world, engine, esl_root)
    c = api(client, "POST", f"/doe/studies/{s2['id']}/clone", json={}).json()
    assert c["inputs"]["select_schema"] == 2 and _job(engine, c["job"]["id"])["params"]["doe"]["select_schema"] == 2
    s1 = _create(client, world)
    simulate_select_prep(engine, esl_root, s1["id"], s1["job"]["id"], world["mesh"])      # 옛 스터디(schema 1)
    with engine.begin() as cn:          # v0.16.2 이전 작업 스냅샷에는 select_schema 가 없음
        cn.execute(text("UPDATE jobs SET params = jsonb_set(params, '{doe}', (params->'doe') - 'select_schema') "
                        "WHERE id=:i"), {"i": s1["job"]["id"]})
    c = api(client, "POST", f"/doe/studies/{s1['id']}/clone", json={}).json()
    assert "select_schema" not in c["inputs"] and "select_schema" not in _job(engine, c["job"]["id"])["params"]["doe"]


# ================================================================ GET …/select/graph · graph.bin
def test_graph_endpoint(client, world, engine, esl_root):
    s1 = _create(client, world)
    simulate_select_prep(engine, esl_root, s1["id"], s1["job"]["id"], world["mesh"])      # schema 1
    write_graph(esl_root, s1["id"])
    r = api(client, "GET", f"/doe/studies/{s1['id']}/select/graph")
    assert r.status_code == 404 and code(r) == "GRAPH_NOT_AVAILABLE"
    s = _create(client, world)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/graph")
    assert r.status_code == 409 and code(r) == "PREP_NOT_READY"
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"], schema=2)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/graph")
    assert r.status_code == 404 and code(r) == "GRAPH_NOT_AVAILABLE"            # GRAPH_FAILED(파일 없음)
    gp = study_dir(esl_root, s["id"]) / "prep" / "select" / "graph.json"
    gp.write_text('{"schema": "beadgraph/2"}', encoding="utf-8")                # 주 번호 다름 = 거부
    assert code(api(client, "GET", f"/doe/studies/{s['id']}/select/graph")) == "GRAPH_NOT_AVAILABLE"
    sha = write_graph(esl_root, s["id"])
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/graph", "tok-general")     # 조회 권한이면 읽기
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["graph"] == GRAPH and g["sha256"] == sha and g["edits_applied"] is None
    assert (g["beadgraph_version"], g["rules"], g["morph_rules"]) == ("1.0.0", 1, 1)
    assert [w["code"] for w in g["warnings"]] == ["GRAPH_RASTER_COARSE"]
    assert hashlib.sha256(gp.read_bytes()).hexdigest() == sha
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/graph", "tok-nonmember").status_code == 403
    assert api(client, "GET", "/doe/studies/nope/select/graph").status_code == 404


def test_graph_bin_view_file_etag(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/view/graph.bin")
    assert r.status_code == 200 and r.content == GRAPH_BIN
    assert r.headers["content-type"] == "application/octet-stream" and sha in r.headers["etag"]
    r2 = client.get(f"{API}/doe/studies/{s['id']}/select/view/graph.bin", headers={**H("tok-power"),
                                                                                   "If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    sha2 = write_graph(esl_root, s["id"], {**GRAPH, "rules": 2})                 # 분류 변경 → ETag 바뀜(메시 같아도)
    r3 = client.get(f"{API}/doe/studies/{s['id']}/select/view/graph.bin", headers={**H("tok-power"),
                                                                                   "If-None-Match": r.headers["etag"]})
    assert r3.status_code == 200 and sha2 in r3.headers["etag"]
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/view/graph.json").status_code == 404      # 허용 목록 밖


# ================================================================ 선택 schema 2: 검사(V-BG-15)
@pytest.mark.parametrize("bad", [
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": 1, "network": 2}]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{}]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": []}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": -1}]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": True}]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": 11}], "vars": ["D", "D"]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": 11}], "vars": ["H"]}]},
    {"beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": 11}], "tiers": []}]},
    {"beads": [{"id": "b1", "src": "bogus", "segs": [{"anchor": 11}]}]},
    {"beads": [{"id": "b1", "segs": [{"anchor": 11}]}]},
    {"graph": {"sha256": "x" * 64, "rules": 1}},
    {"graph": {"sha256": "a" * 64, "rules": 1, "edits": {"toggle": [{"anchor": 1, "as": "plateau"}]}}},
    {"graph": {"sha256": "a" * 64, "rules": 1, "edits": {"merge": [[{"anchor": 1}]]}}},
    {"graph": {"sha256": "a" * 64, "rules": 1, "edits": {"split": [{"anchor": 1, "at": [1.0, 2.0, 3.0]}]}}},
    {"ties": [["b1"]]},
    {"extra": 1},
], ids=lambda b: json.dumps(b)[:60])
def test_schema2_structure_422(client, world, engine, esl_root, bad):
    s, sha = ready2(client, world, engine, esl_root)
    sel = {**sel2(sha), **bad}
    r = derive(client, s, sel)
    assert r.status_code == 422 and code(r) == "INVALID_PARAMS", r.text
    assert NORM2_IN == []


def test_schema2_hold_fixed_bool_code(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root)
    r = derive(client, s, sel2(sha, gbead("b1", hold_fixed=True)))
    assert r.status_code == 422 and code(r) == "SELECT_HOLD_INVALID"


def test_schema_mismatch_both_ways(client, world, engine, esl_root):
    s2, sha = ready2(client, world, engine, esl_root)
    for fn in (derive, put):
        r = fn(client, s2, selection())
        assert r.status_code == 422 and code(r) == "SELECT_SCHEMA_MISMATCH"
        assert (r.json()["detail"]["study_schema"], r.json()["detail"]["selection_schema"]) == (2, 1)
    s1 = _create(client, world)
    simulate_select_prep(engine, esl_root, s1["id"], s1["job"]["id"], world["mesh"])
    s1 = api(client, "GET", f"/doe/studies/{s1['id']}").json()
    for fn in (derive, put):
        r = fn(client, s1, sel2(sha))
        assert r.status_code == 422 and code(r) == "SELECT_SCHEMA_MISMATCH"
    assert NORM2_IN == []


def test_graph_stale_409(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root)
    other = "b" * 64
    for fn in (derive, put):
        r = fn(client, s, sel2(other))
        assert r.status_code == 409 and code(r) == "BG_GRAPH_STALE"
        assert r.json()["detail"]["saved"] == other and r.json()["detail"]["current"] == sha
    r = derive(client, s, {"schema_version": 2, "beads": [gbead()]})            # 그래프 비드 + graph 기준 없음
    assert r.status_code == 409 and r.json()["detail"]["saved"] is None
    # 분류 실패(graph.json 없음) 스터디: 그래프 비드 = 409(current null), elems 비드만 = 통과
    sf, _ = ready2(client, world, engine, esl_root, graph=False)
    r = derive(client, sf, sel2(sha))
    assert r.status_code == 409 and r.json()["detail"]["current"] is None
    r = derive(client, sf, {"schema_version": 2, "beads": [ebead("b1")]})
    assert r.status_code == 200, r.text
    assert r.json()["beads"][0]["src"] == "elems"


@pytest.mark.parametrize("sel_fn, want", [
    (lambda sha: sel2(sha, gbead("b1", 99)), "BG_SEG_UNKNOWN"),
    (lambda sha: sel2(sha, gbead("b1", 11, 13, name="apart")), "BG_GROUP_NOT_CONNECTED"),
    (lambda sha: sel2(sha, gbead("b1"), gbead("b9", 12), ties=[["b1", "b9"]]), "BG_TIE_NOMINAL"),
    (lambda sha: sel2(sha, edits={"toggle": [{"anchor": 999, "as": "island"}]}), "BG_EDIT_INVALID"),
    (lambda sha: sel2(sha, gbead("b1"), ebead("b2", name="overlap")), "SELECT_OVERLAP"),
], ids=["seg_unknown", "not_connected", "tie_nominal", "edit_invalid", "overlap"])
def test_core_422_codes_pass_through(client, world, engine, esl_root, sel_fn, want):
    s, sha = ready2(client, world, engine, esl_root)
    for fn in (derive, put):
        r = fn(client, s, sel_fn(sha))
        assert r.status_code == 422 and code(r) == want, r.text
    assert api(client, "GET", f"/doe/studies/{s['id']}").json()["selection"] is None


# ================================================================ 저장·조회·변수 표
def test_schema2_derive_save_get_params(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12), {**ebead("b3"), "name": "E3"}, gbead("b4", 13, vars=["D"]),
               edits={"toggle": [{"anchor": 11, "as": "bead"}], "merge": [[{"anchor": 12}, {"anchor": 13}]],
                      "split": [{"anchor": 11, "at": [10.0, 20.0]}]},
               ties=[["b2", "b1"]])
    r = derive(client, s, sel)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rev"] is None and d["graph_algo"] == 1 and d["graph"]["sha256"] == sha
    assert d["graph"]["sym_pairs"] == [[11, 12]] and [x["anchor"] for x in d["graph"]["segments"]] == [11, 12, 13]
    assert DERIVE2[-1]["labels"] == ["cls", "floor", "island", "junction_zone", "segment", "tier", "transition"]
    # 코어로 간 dump: as 별칭·None 생략(schema 1 dump 와 다른 규칙 — schema 2 만)
    sent = NORM2_IN[-1]
    assert sent["graph"]["edits"]["toggle"] == [{"anchor": 11, "as": "bead"}]
    assert "name" not in sent["beads"][0] and "vars" not in sent["beads"][0] and sent["beads"][2]["src"] == "elems"
    r = derive(client, s, sel, bead="b2")
    assert r.status_code == 200 and [b["id"] for b in r.json()["beads"]] == ["b2"]
    r = put(client, s, sel)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["selection"]["rev"] == 1 and out["selection"]["n_beads"] == 4
    g = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()
    assert g["input"]["schema_version"] == 2 and g["input"]["graph"]["sha256"] == sha and "graph_stale" not in g["derived"]
    assert g["sha256"] == out["selection"]["sha256"]
    row = _row(engine, s["id"])["selection"]
    assert all("plan" not in b and "section" not in b for b in row["derived"]["beads"])
    # 같은 선택 다시 저장 = 같은 sha
    s2 = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert put(client, s2, sel).json()["selection"]["sha256"] == g["sha256"]
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    names = [x["name"] for x in p["params"]]
    # elems 비드 = schema 1 행(B3_D1·B3_W), 그래프 비드 = B<n>_D·B<n>_W(k 없음), ties(b1·b2) = 대표 B1 1개씩
    assert names == ["B3_D1", "B3_W", "B1_D", "B1_W", "B4_D"], names
    row = {x["name"]: x for x in p["params"]}
    assert row["B1_D"]["group_members"] == ["B1_D", "B2_D"] and row["B1_W"]["group_members"] == ["B1_W", "B2_W"]
    assert row["B1_D"]["nominal"] == 4.0 and row["B1_D"]["default_range"] == [2.8, 5.2]       # select.range D ±30 %
    assert row["B1_W"]["default_range"] == [32.0, 48.0]                                       # W ±20 %
    assert row["B1_D"]["feasible"] == [1.0, 8.0] and row["B1_W"]["feasible"] == [14.0, 64.0]  # BG-D-22(바닥 최소 6 mm)
    assert row["B1_D"]["use_default"] is True and row["B1_D"]["tier"] == 1
    assert row["B3_D1"]["default_range"] == [4.2, 7.8]
    pb = {b["id"]: b for b in p["beads"]}
    assert pb["b1"]["src"] == "graph" and pb["b1"]["n_segs"] == 1 and pb["b3"]["src"] == "elems"
    assert [w["code"] for w in pb["b1"]["warnings"]] == ["BG_SHARED_CHILD"]


def test_schema2_core_params_passthrough_and_segment_short(client, world, engine, esl_root):
    """코어 derived 가 params 를 주면 그대로, 없으면 BG_SEGMENT_SHORT 비드는 use_default false(BG-D-24)."""
    from esl_platform.api.services import doe_select

    doc = {"input": {"schema_version": 2, "beads": [{"id": "b1", "src": "graph"}]},
           "derived": {"beads": [{"id": "b1", "src": "graph", "D_nom": 2.0, "W_nom": 20.0, "tier": 2,
                                  "warnings": [{"code": "BG_SEGMENT_SHORT", "bead": "b1", "length_mm": 20.0,
                                                "ramp_mm": 30.0}],
                                  "range_feasible": {"D": [1.0, 3.0]}}]}}
    p = doe_select.params_table(doc, None)
    assert [(x["name"], x["use_default"]) for x in p["params"]] == [("B1_D", False), ("B1_W", False)]
    assert p["params"][0]["feasible"] == [1.0, 3.0]
    doc["derived"].update(params=[{"name": "B1_D", "x": 1}], param_beads=[{"id": "b1"}])
    assert doe_select.params_table(doc, None)["params"] == [{"name": "B1_D", "x": 1}]


def test_saved_selection_goes_stale_when_graph_changes(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root)
    assert put(client, s, sel2(sha)).status_code == 200
    sha2 = write_graph(esl_root, s["id"], {**GRAPH, "rules": 2})           # 준비 재실행(분류 cfg·RULES 변경) 흉내
    g = api(client, "GET", f"/doe/studies/{s['id']}/selection")
    assert g.status_code == 200
    assert g.json()["derived"]["graph_stale"] == {"saved": sha, "current": sha2}
    r = api(client, "GET", f"/doe/studies/{s['id']}/params")
    assert r.status_code == 409 and code(r) == "BG_GRAPH_STALE" and r.json()["detail"]["current"] == sha2
    st = api(client, "GET", f"/doe/studies/{s['id']}").json()
    r = api(client, "POST", f"/doe/studies/{s['id']}/matrix",
            json={"version": st["version"], "spec": {"method": "lhs", "n": 4, "params": [{"name": "B1_D", "lo": 3, "hi": 5}]}})
    assert r.status_code == 409 and code(r) == "BG_GRAPH_STALE"
    # 다시 확인 후 저장 → 정상
    st = api(client, "GET", f"/doe/studies/{s['id']}").json()
    r = put(client, st, sel2(sha2))
    assert r.status_code == 200 and r.json()["selection"]["rev"] == 2
    assert api(client, "GET", f"/doe/studies/{s['id']}/params").status_code == 200


# ================================================================ 자동 seed(schema 2) · 준비 요약
def _auto_v2(esl_root, sid, sel, *, hints=None):
    d = study_dir(esl_root, sid) / "prep" / "select"
    d.mkdir(parents=True, exist_ok=True)
    (d / "auto_selection.json").write_text(json.dumps({
        "schema": "esl/doe_auto_selection/2", "source": "graph", "selection": sel, "sha256": "f" * 64,
        "hints": hints or [], "warnings": [{"code": "AUTO_TOO_MANY_BEADS", "n": 22, "max": 20}]}), encoding="utf-8")


def test_auto_endpoint_schema2(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root, bead_source="auto")
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == 404 and code(r) == "AUTO_NOT_AVAILABLE"
    seed = sel2(sha, gbead("b1", 11), gbead("b2", 12), gbead("b3", 13))
    hints = [{"code": "AUTO_SLOPE_DIFF", "bead": "b1", "rel": 0.31}]
    _auto_v2(esl_root, s["id"], seed, hints=hints)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto", "tok-general")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["selection"] == seed and a["source"] == "graph" and a["hints"] == hints and a["map"] == []
    assert [w["code"] for w in a["warnings"]] == ["AUTO_TOO_MANY_BEADS"]
    saved = put(client, s, seed)
    assert saved.status_code == 200 and saved.json()["selection"]["sha256"] == a["sha256"]     # seed 그대로 저장 = 같은 sha
    # 분류가 바뀐 뒤의 seed(옛 graph sha) → sha 는 파일 값(정규화 불가 — 저장 시 409)
    write_graph(esl_root, s["id"], {**GRAPH, "rules": 3})
    assert api(client, "GET", f"/doe/studies/{s['id']}/select/auto").json()["sha256"] == "f" * 64
    # schema 1 seed 파일이 schema 2 스터디에 있으면 읽지 않음
    _p = study_dir(esl_root, s["id"]) / "prep" / "select" / "auto_selection.json"
    _p.write_text(json.dumps({"schema": "esl/doe_auto_selection/1", "selection": selection()}), encoding="utf-8")
    assert code(api(client, "GET", f"/doe/studies/{s['id']}/select/auto")) == "AUTO_NOT_AVAILABLE"
    m, _ = ready2(client, world, engine, esl_root)                              # 수동 스터디 = 404
    assert code(api(client, "GET", f"/doe/studies/{m['id']}/select/auto")) == "AUTO_NOT_AVAILABLE"


def test_prep_summary_graph_passthrough(client, world, engine, esl_root):
    s, sha = ready2(client, world, engine, esl_root, bead_source="auto")
    with engine.connect() as c:
        prep = dict(c.execute(text("SELECT prep FROM bead_does WHERE id=:i"), {"i": s["id"]}).scalar_one())
    graph = {"ok": True, "code": None, "sha256": sha, "beadgraph_version": "1.0.0", "rules": 1, "morph_rules": 1,
             "n_floors": 2, "n_segments": 3, "n_junction_zones": 1, "n_islands": 1, "n_holes": 0, "n_networks": 1}
    auto = {"ok": True, "source": "graph", "step": None, "code": None, "available": True, "n_beads": 3,
            "selection_sha256": None, "hint": {"ok": False, "step": None, "code": None, "step_given": False}}
    prep.update(graph=graph, auto=auto)
    update_study(engine, s["id"], prep=prep)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["prep"]["graph"] == graph and g["prep"]["auto"] == auto
    s1 = _create(client, world)
    simulate_select_prep(engine, esl_root, s1["id"], s1["job"]["id"], world["mesh"])
    assert "graph" not in api(client, "GET", f"/doe/studies/{s1['id']}").json()["prep"]


# ================================================================ schema 1 바이트 불변(V-BG-12 백엔드 부분)
def test_schema1_dump_unchanged():
    """SelectionAny 로 받은 schema 1 본문의 dump = v0.16.2 SelectionIn dump(코어 입력·sha 바이트 불변)."""
    from esl_platform.api.schemas import DoeSelectionPutIn, SelectionIn
    from esl_platform.api.services.doe_select import selection_in

    for body in (selection(), selection(bead("b1", name="x", hold_fixed=1, blend_mm=20.0, links=[[1, 2]],
                                              tiers=((1, 4), (5, 6))), fixed_user=es((7, 8)), exclude=es((9, 9))),
                 {"beads": [bead()]}):
        new = DoeSelectionPutIn.model_validate({"version": 1, "selection": body}).selection
        assert type(new) is SelectionIn
        assert json.dumps(selection_in(new), sort_keys=True) == json.dumps(selection_in(SelectionIn.model_validate(body)),
                                                                           sort_keys=True)
    with pytest.raises(ValueError):                                            # schema 3 = schema 1 모델의 오류 그대로
        DoeSelectionPutIn.model_validate({"version": 1, "selection": {"schema_version": 3, "beads": []}})


def test_schema1_study_put_unchanged_and_no_graph(client, world, engine, esl_root):
    """schema 1 스터디: 저장 sha·코어 입력 = v0.16.2 경로(bead_graph 호출 없음), 그래프 파일이 있어도 쓰지 않음."""
    from test_doe_select_api import NORM_IN

    s = _create(client, world)
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"])
    write_graph(esl_root, s["id"])
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert "select_schema" not in s["inputs"]
    r = put(client, s, selection(bead(hold_fixed=1)))
    assert r.status_code == 200, r.text
    assert NORM_IN[-1]["beads"][0]["name"] is None and NORM_IN[-1]["beads"][0]["hold_fixed"] == 1
    assert NORM2_IN == [] and DERIVE2 == []
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    assert [x["name"] for x in p["params"]] == ["B1_D1", "B1_W"]
    finish_job(engine, s["job"]["id"])
