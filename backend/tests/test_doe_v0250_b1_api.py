"""v0.25.0 B1 — 가상 비드("추가 비드", 변수 종류 A) 백엔드(계약 esl_virtual_bead.md §2.1·§7·§8·§19.4·§19.7·§19.9, V-0250-VB-16·17·25·28·33 의 백엔드 부분).

- 설정: pydantic ↔ 코어 DEFAULTS ↔ yaml 2개(11키), 범위, θ 상한 ≤ select.quality.flip_deg 는 코어 ``check_virtual_bead`` 를 부른다(같은 판정).
- 스냅샷: 새 select 스터디 params.doe.virtual_bead == inputs 같은 블록(해시 안 6키 + schema), enabled false·select 밖 = 키 없음, 옛 = null. 복제 = 원 블록.
- 입력: ``VirtualBeadIn``(side 키 없음 — 422, flip 비 bool 422, r 0 은 키 유지, None·flip false·빈 목록은 코어에 안 넘김), VB_* 코드 통과.
- derive: 블록·계획 열·tie 집합을 가상 비드 있는 선택만 코어에 전달, 응답 virtual_beads·vb_frame(없으면 키 없음), DB 요약에는 preview 없음.
- 변수 표: A 행 guard.warp n > 0 이면 text(VB_WARP_INFO), 가상 비드 행 warnings·vb_reason text.
- 코어 e2e(대역 아님): 합성 평판 세계에서 normalize → derive 를 백엔드 서비스로(``doe_select``) — 응답 모양·flip·r·스냅샷 θ.
코어 ``esl.doe.bead_graph`` 는 test_doe_select_graph_api 의 대역(계약 형식 합성 자료) — 가상 비드 항목을 내는 판으로 바꿔 쓴다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from doe_support import api
from esl_test_support import REPO
from sqlalchemy import text
from test_doe_select_api import (  # noqa: F401 - 픽스처 재사용
    _job,
    _row,
    code,
    es,
    sbody,
    selection,
    settings_dict,
    simulate_select_prep,
    world,
)
from test_doe_select_graph_api import (  # noqa: F401
    _create,
    _err,
    _fake_graph,
    derive,
    fake_derive_v2,
    fake_normalize_v2,
    gbead,
    put,
    ready2,
    sel2,
)

NORM_KW: list[dict] = []      # 대역 normalize_v2 가 받은 cfg 의 virtual_bead 절 · 스냅샷 블록 인수(INT-2)
KW: list[dict] = []           # 대역 derive_v2 가 받은 가상 비드 인수

VB = {"id": "a1", "p0": [60.0, 140.0, 0.0], "p1": [180.0, 140.0, 0.0], "w_top": 10.0, "d_max": 6.0}
WARP = {"limit_deg": 15.0, "n": 3, "max_deg": 22.5, "at": 6.0}


def _fake_normalize(sel, graph, cfg, *, mesh=None, virtual_bead=None):
    """대역 normalize + virtual_beads(id 정렬 · flip false 키 없음) · side 키 422 · 개수 상한 = cfg max_count — 계약 §2.1·§19.9.2 형식 합성."""
    vbs = sel.get("virtual_beads") or []
    NORM_KW.append({"vb": copy.deepcopy(cfg.get("virtual_bead")), "n": len(vbs), "block": copy.deepcopy(virtual_bead)})
    mx = int(cfg["virtual_bead"]["max_count"])
    if len(vbs) > mx:
        raise _err("VB_MAX_COUNT", f"추가 비드는 {mx}개까지", n=len(vbs), max=mx)
    for v in vbs:
        if "side" in v:
            raise _err("VB_INPUT_INVALID", "side 는 없어진 키", vbead=v["id"], key="side")
        if float(v.get("r", 0.0)) > 9.0:
            raise _err("VB_INPUT_INVALID", "r 너무 큼", vbead=v["id"], key="r", r_max=9.0)
    base = {k: v for k, v in sel.items() if k != "virtual_beads"}
    out, _sha = fake_normalize_v2(base, graph, cfg, mesh=mesh)
    if vbs:
        out["virtual_beads"] = sorted(copy.deepcopy(vbs), key=lambda v: v["id"])
    sha = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return out, sha


def _vb_row(v: dict, big: bool = False) -> dict:
    row = {"id": v["id"], "name": v.get("name") or f"추가 비드 {v['id'][1:]}", "p0": v["p0"], "p1_resolved": v.get("p1") or [1.0, 2.0, 0.0],
           "len_mm": 120.0, "angle_deg": 0.0, "side_resolved": "-" if v.get("flip") else "+", "ok": True, "reasons": [],
           "warnings": [{"code": "VB_R_CLAMPED", "level": "info", "vbead": v["id"], "r": 2.0, "r_h": 3.0, "text": "코어 문구"}],
           "h": 3.0, "n_wall": 2.0, "n_top": 3.3, "r_resolved": v.get("r", 3.0), "r_source": "user" if "r" in v else "default",
           "host": "base", "host_floor": 0, "preview": {"idx": [1, 2, 3], "vec": [[0, 0, 1.0]] * 3, "g": [0.0, 0.5, 1.0], "c": 1.2}}
    return row


def _fake_derive(mesh, norm, cfg, graph, labels, *, frame=None, fixed_scan=None, bead=None, virtual_bead=None, vb_plan=None, tie_node_ids=None):
    KW.append({"virtual_bead": copy.deepcopy(virtual_bead), "vb_plan": vb_plan,
               "tie": None if tie_node_ids is None else [int(x) for x in tie_node_ids], "has_frame": frame is not None})
    d = fake_derive_v2(mesh, norm, cfg, graph, labels, frame=frame, fixed_scan=fixed_scan, bead=bead)
    vbs = norm.get("virtual_beads") or []
    params, pbeads = [], []
    for b in d["beads"]:
        if b.get("src") == "graph":
            pbeads.append({"id": b["id"], "name": b["name"], "kind": "select", "src": "graph", "n_tiers": 1, "W_nom": b["W_nom"], "warnings": []})
            for kind in ("D", "W"):
                params.append({"name": f"{b['id'].upper()}_{kind}", "type": kind, "bead": b["id"], "tier": 1, "nominal": 4.0, "feasible": [1.0, 8.0],
                               "feasible_source": "estimate", "default_range": [2.0, 6.0], "use_default": True,
                               "group_members": [f"{b['id'].upper()}_{kind}"]})
    if vbs or virtual_bead is not None:                 # INT-4: 블록 있는 스터디 = 비드 0개여도 vb_frame(코어 derive_v2 와 같은 모양)
        d["vb_frame"] = {"origin": [0.0, 0.0, 0.0], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 1.0, 0.0], "n_h": [0.0, 0.0, 1.0]}
    if vbs:
        d["virtual_beads"] = [_vb_row(v) for v in vbs]
        for v in vbs:
            n = v["id"][1:]
            params.append({"name": f"A{n}_A", "type": "A", "bead": v["id"], "tier": None, "form": "hinge", "nominal": 0.0, "unit": "mm",
                           "feasible": [0.0, v["d_max"]], "feasible_source": "user", "default_range": [0.0, v["d_max"]], "use_default": True,
                           "group_members": [f"A{n}_A"], "label": f"추가 비드 {n} · 깊이", "wall_elems": 2.0,
                           "vb": {"w_top": v["w_top"], "theta_deg": 45.0, "side": "+", "n_wall": 2.0, "n_top": 3.3, "len_mm": 120.0,
                                  "angle_deg": 0.0, "r": 3.0, "r_source": "default", "host": "base"},
                           "acc_hint": None, "guard": {"A": {"state": "ok"}, "warp": dict(WARP)}})
            pbeads.append({"id": v["id"], "name": f"추가 비드 {n}", "kind": "virtual",
                           "warnings": [{"code": "VB_WARP_INFO", "level": "info", "vbead": v["id"], "n": 3, "max": 22.5, "d": 6.0}],
                           "vb_reason": {"code": "VB_OVER_BEAD"} if v.get("name") == "bad" else None})
    d["params"], d["param_beads"] = params, pbeads
    return d


@pytest.fixture(autouse=True)
def _core(_fake_graph):  # noqa: F811
    _fake_graph.normalize_v2 = _fake_normalize
    _fake_graph.derive_v2 = _fake_derive
    from esl_platform.api.services import doe_select

    doe_select.reset_caches()                  # derive 캐시가 앞 시험의 같은 키를 돌려주지 않게
    NORM_KW.clear()
    KW.clear()
    yield


def _doe(engine, st):
    return _job(engine, st["job"]["id"])["params"]["doe"]


def _legacy(engine, st):
    """v0.25.0 이전 스냅샷 흉내 — 작업·inputs 의 virtual_bead 삭제(옛 스터디)."""
    with engine.begin() as cn:
        cn.execute(text("UPDATE jobs SET params = jsonb_set(params, '{doe}', (params->'doe') - 'virtual_bead') WHERE id=:i"), {"i": st["job"]["id"]})
        cn.execute(text("UPDATE bead_does SET inputs = inputs - 'virtual_bead' WHERE id=:i"), {"i": st["id"]})


# ================================================================ 설정 거울 (V-0250-VB-16)
VB_DEFAULT = {"enabled": True, "max_count": 4, "min_wall_elems": 2.0, "margin_mm": 3.0, "theta_default_deg": 45.0,
              "theta_range_deg": [15.0, 60.0], "r_default_h_mult": 1.0, "d_max_limit_mm": 30.0, "default_on": True,
              "warp_max_deg": 15.0, "preview_max_nodes": 50000}


def test_vb_settings_mirror_11_keys():
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg, bead_doe_settings

    assert len(VB_DEFAULT) == 11
    m = BeadDoeCfg().model_dump()["virtual_bead"]
    assert m == VB_DEFAULT and DEFAULTS["virtual_bead"] == VB_DEFAULT                   # 코어 DEFAULTS = pydantic (계약 §7.1)
    assert bead_doe_settings(None)["virtual_bead"] == VB_DEFAULT
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["virtual_bead"] == VB_DEFAULT, p                                       # 4곳 같은 이름·값
        assert BeadDoeCfg.model_validate(y).model_dump()["virtual_bead"] == VB_DEFAULT  # yaml 기본값 검증 통과(θ 상한 60 ≤ flip_deg 60)


@pytest.mark.parametrize("bad", [
    {"max_count": 0}, {"max_count": 10}, {"min_wall_elems": 0.5}, {"min_wall_elems": 11}, {"margin_mm": -1}, {"margin_mm": 51},
    {"theta_default_deg": 0.5}, {"theta_default_deg": 90}, {"r_default_h_mult": -0.1}, {"r_default_h_mult": 4.5},
    {"d_max_limit_mm": 0}, {"d_max_limit_mm": 201}, {"warp_max_deg": 0}, {"warp_max_deg": 90}, {"preview_max_nodes": 999},
    {"preview_max_nodes": 1_000_001}, {"unknown": 1}, {"theta_range_deg": [15.0]}, {"theta_range_deg": [15.0, 30.0, 60.0]},
    {"theta_range_deg": [60.0, 15.0]}, {"theta_range_deg": [0.5, 60.0]}, {"theta_range_deg": [15.0, 90.0]},
])
def test_vb_settings_ranges(bad):
    from esl_platform.core.config import BeadDoeCfg

    with pytest.raises(Exception):
        BeadDoeCfg.model_validate({"virtual_bead": bad})
    ok = BeadDoeCfg.model_validate({"virtual_bead": {"max_count": 9, "min_wall_elems": 10, "margin_mm": 0, "theta_default_deg": 20.0,
                                                     "theta_range_deg": [10.0, 30.0], "r_default_h_mult": 0, "d_max_limit_mm": 200,
                                                     "warp_max_deg": 89.9, "preview_max_nodes": 1000, "enabled": False, "default_on": False}})
    assert ok.virtual_bead.max_count == 9 and ok.virtual_bead.theta_range_deg == [10.0, 30.0]


def test_vb_theta_vs_flip_deg_uses_core_check_v25():
    """V-0250-VB-25(백엔드): θ 상한 > select.quality.flip_deg → 오류(문구 VB_THETA_FLIP). 판정 = 코어 ``esl.doe.check_virtual_bead`` — pydantic 이 같은 결과."""
    from esl.doe import check_virtual_bead
    from esl.errors import EslError
    from esl_platform.core.config import BeadDoeCfg

    def both(vb, flip):
        cfg = {"virtual_bead": {**VB_DEFAULT, **vb}, "select": {"quality": {"flip_deg": flip}}}
        try:
            check_virtual_bead(cfg)
            core = None
        except EslError as exc:
            core = exc
        try:
            BeadDoeCfg.model_validate({"virtual_bead": vb, "select": {"quality": {"flip_deg": flip}}})
            pyd = None
        except Exception as exc:  # noqa: BLE001
            pyd = exc
        return core, pyd

    c, p = both({"theta_range_deg": [15.0, 61.0]}, 60.0)                                  # 상한 61 ∧ flip 60 → 오류
    assert c is not None and p is not None and c.code == "CONFIG_INVALID" and str(c.message) in str(p)
    assert "추가 비드 사면 각 상한(61°)" in str(p) and "select.quality.flip_deg(60°)" in str(p)    # VB_THETA_FLIP 문구 그대로
    assert both({"theta_range_deg": [15.0, 60.0]}, 60.0) == (None, None)                  # 같아도 통과
    c, p = both({}, 50.0)                                                                 # flip 을 50 으로 내리면 기본 [15, 60] 오류
    assert c is not None and p is not None
    c, p = both({"theta_default_deg": 70.0, "theta_range_deg": [15.0, 60.0]}, 60.0)      # default 가 범위 밖
    assert c is not None and p is not None


def test_vb_theta_violation_makes_config_invalid_on_load(tmp_path):
    """설정 로더 = CONFIG_INVALID(설정 스키마 오류 — 같은 pydantic 검증)."""
    from esl_platform.core.config import load_config_dict

    y = yaml.safe_load((REPO / "config" / "esl_platform.example.yaml").read_text(encoding="utf-8"))
    y["bead_doe"]["virtual_bead"]["theta_range_deg"] = [15.0, 61.0]
    lc = load_config_dict(y, environ={})
    assert lc.settings is None and any("bead_doe" in k for k in lc.error_keys())


def test_vb_settings_out(client, world):  # noqa: F811
    s = api(client, "GET", "/doe/settings").json()
    assert s["virtual_bead"] == {"enabled": True, "max_count": 4, "theta_default_deg": 45.0, "theta_range_deg": [15.0, 60.0],
                                 "d_max_limit_mm": 30.0, "min_wall_elems": 2.0, "r_default_h_mult": 1.0}   # §8·§19.7(7키)


# ================================================================ 스냅샷 (§7.2)
BLOCK = {"schema": 1, "min_wall_elems": 2.0, "margin_mm": 3.0, "theta_default_deg": 45.0, "theta_range_deg": [15.0, 60.0],
         "warp_max_deg": 15.0, "r_default_h_mult": 1.0}


def test_snapshot_new_select_study(client, world, engine, esl_root):  # noqa: F811
    s = _create(client, world)
    d = _doe(engine, s)
    assert d["virtual_bead"] == BLOCK and s["inputs"]["virtual_bead"] == BLOCK                   # 해시 안 6키 + schema, 해시 밖 키 없음
    assert _row(engine, s["id"])["inputs"]["virtual_bead"] == BLOCK
    assert set(d["virtual_bead"]) == {"schema", *__import__("esl.morph.virtual_bead", fromlist=["x"]).HASH_KEYS}


def test_snapshot_values_follow_config_and_enabled():
    from esl_platform.api.services import doe as svc

    c = {"virtual_bead": {**VB_DEFAULT, "min_wall_elems": 3.0, "margin_mm": 5.0, "theta_default_deg": 30.0, "theta_range_deg": [20, 50],
                          "warp_max_deg": 10.0, "r_default_h_mult": 2.0, "max_count": 9, "d_max_limit_mm": 99.0}}
    assert svc.vbead_snapshot(c) == {"schema": 1, "min_wall_elems": 3.0, "margin_mm": 5.0, "theta_default_deg": 30.0,
                                     "theta_range_deg": [20.0, 50.0], "warp_max_deg": 10.0, "r_default_h_mult": 2.0}
    c["virtual_bead"]["enabled"] = False
    assert svc.vbead_snapshot(c) is None                                                        # 꺼짐 = 키 없음(그 스터디 = VB_SCOPE)


def test_snapshot_absent_outside_select_and_old_study_null(client, world, engine, esl_root):  # noqa: F811
    from doe_support import upload_step

    uid = upload_step(client)
    ok = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"], world["b"]],
                                                   "step_upload_id": uid})
    assert ok.status_code == 201, ok.text
    assert "virtual_bead" not in ok.json()["inputs"] and "virtual_bead" not in _doe(engine, ok.json())
    s = _create(client, world)
    _legacy(engine, s)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["inputs"]["virtual_bead"] is None                                                  # 옛 select = 응답만 null
    assert "virtual_bead" not in _row(engine, s["id"])["inputs"]                                # DB 에는 키 쓰지 않음


# ================================================================ 복제 (원 블록 그대로)
def test_clone_copies_original_block_not_current_config(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    assert put(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    odd = {"schema": 1, "min_wall_elems": 3.0, "margin_mm": 4.0, "theta_default_deg": 30.0, "theta_range_deg": [20.0, 45.0],
           "warp_max_deg": 9.0, "r_default_h_mult": 0.0}
    with engine.begin() as cn:
        cn.execute(text("UPDATE jobs SET params = jsonb_set(params, '{doe,virtual_bead}', CAST(:p AS JSONB)) WHERE id=:i"),
                   {"p": json.dumps(odd), "i": s["job"]["id"]})
        cn.execute(text("UPDATE bead_does SET inputs = jsonb_set(inputs, '{virtual_bead}', CAST(:p AS JSONB)) WHERE id=:i"),
                   {"p": json.dumps(odd), "i": s["id"]})
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert c.status_code == 201, c.text
    c = c.json()
    assert _doe(engine, c)["virtual_bead"] == odd and c["inputs"]["virtual_bead"] == odd             # 지금 설정(기본)이 아니라 원 값
    assert _row(engine, c["id"])["inputs"]["virtual_bead"] == odd
    orig_sel = _row(engine, s["id"])["selection"]
    new_sel = _row(engine, c["id"])["selection"]
    assert new_sel and new_sel["sha256"] == orig_sel["sha256"] and new_sel["input"]["virtual_beads"] == orig_sel["input"]["virtual_beads"]


def test_clone_does_not_inject_into_old_study(client, world, engine, esl_root):  # noqa: F811
    s, _ = ready2(client, world, engine, esl_root)
    _legacy(engine, s)
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    for body in ({}, {"depth_section": "entry_fixed"}, {"depth_section": "floor_fixed"}):
        c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json=body)
        assert c.status_code == 201, c.text
        c = c.json()
        assert "virtual_bead" not in _doe(engine, c) and "virtual_bead" not in _row(engine, c["id"])["inputs"]    # 없던 스터디에 주입 금지
        assert c["inputs"]["virtual_bead"] is None


# ================================================================ 입력 스키마 · 오류 코드 (V-0250-VB-17·33)
def test_selection_in_drops_empty_list_none_and_flip_false():
    from esl_platform.api.services import doe_select as ds
    from esl_platform.api.schemas import SelectionInV2

    base = {"schema_version": 2, "beads": []}
    assert "virtual_beads" not in ds.selection_in(SelectionInV2.model_validate(base))                     # 옛 선택 바이트 동일
    assert "virtual_beads" not in ds.selection_in(SelectionInV2.model_validate({**base, "virtual_beads": []}))
    d = ds.selection_in(SelectionInV2.model_validate({**base, "virtual_beads": [
        {**VB, "flip": False, "r": 0, "name": None, "end": None, "theta_deg": None},
        {**VB, "id": "a2", "flip": True, "r": 2.5, "end": "square", "theta_deg": 30.0, "name": "x"},
        {"id": "a3", "p0": [0, 0, 0], "length": 50, "angle_deg": 30, "w_top": 8, "d_max": 4}]}))
    v1, v2, v3 = d["virtual_beads"]
    assert "flip" not in v1 and v1["r"] == 0.0 and set(v1) == {"id", "p0", "p1", "w_top", "d_max", "r"}     # None 은 빠지고 r 0 은 남음
    assert v2["flip"] is True and v2["r"] == 2.5 and v2["end"] == "square"
    assert "r" not in v3 and v3["length"] == 50.0 and "p1" not in v3                                       # r 생략 = 키 없음(요소 크기 기본)


@pytest.mark.parametrize("bad", [
    {"side": "+"}, {"side": "-"}, {"flip": 1}, {"flip": "yes"}, {"foo": 1}, {"p0": [0, 0]}, {"p1": [1, 2, 3, 4]},
    {"w_top": "x"}, {"end": "flat"}, {"id": "a" * 17},
])
def test_put_pydantic_shape_errors_are_vb_input_invalid(client, world, engine, esl_root, bad):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    v = {**VB, **bad}
    r = derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[v]))
    assert r.status_code == 422 and code(r) == "VB_INPUT_INVALID", r.text
    assert not NORM_KW                                                                                      # 코어까지 가지 않음


def test_flip_bool_ok_and_other_fields_required(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    for flip in (True, False):
        assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[{**VB, "flip": flip}])).status_code == 200
    for k in ("id", "p0", "w_top", "d_max"):
        v = {a: b for a, b in VB.items() if a != k}
        r = derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[v]))
        assert r.status_code == 422 and code(r) == "VB_INPUT_INVALID"


def test_core_codes_pass_through_with_detail(client, world, engine, esl_root):  # noqa: F811
    """코어가 내는 VB_INPUT_INVALID·VB_MAX_COUNT(detail vbead·key·r_max)는 SELECT_INVALID 로 바뀌지 않는다."""
    s, sha = ready2(client, world, engine, esl_root)
    many = [{**VB, "id": f"a{i}"} for i in range(1, 6)]                                                     # 5 > max_count 4 (pydantic 상한 9 안)
    r = derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=many))
    assert r.status_code == 422 and code(r) == "VB_MAX_COUNT" and r.json()["detail"]["max"] == 4, r.text
    r = put(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[{**VB, "r": 12.0}]))
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "VB_INPUT_INVALID" and d["key"] == "r" and d["r_max"] == 9.0 and d["vbead"] == "a1"
    r = derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[{**VB, "id": f"a{i}"} for i in range(1, 11)]))     # 10 > 9
    assert r.status_code == 422 and code(r) in ("VB_INPUT_INVALID", "VB_MAX_COUNT")


def test_sel_error_code_prefixes():
    from esl_platform.api.services.doe_select import sel_error
    from esl.errors import EslError

    for c in ("VB_INPUT_INVALID", "VB_MAX_COUNT", "SELECT_OVERLAP", "BG_TIE_NOMINAL"):
        assert sel_error(EslError(c, "m")).code == c
    assert sel_error(EslError("FOO", "m")).code == "SELECT_INVALID"
    assert sel_error(EslError("VB_X", "m")).status == 422


# ================================================================ derive (코어 인수·응답 키)
def test_derive_passes_block_plan_and_tie_only_with_virtual_beads(client, world, engine, esl_root):  # noqa: F811
    from esl_platform.api.services import doe_select

    s, sha = ready2(client, world, engine, esl_root)
    sel0 = sel2(sha, gbead("b1", 11))
    d0 = derive(client, s, sel0)
    assert d0.status_code == 200 and (KW[-1]["virtual_bead"], KW[-1]["vb_plan"]) == (BLOCK, "plate")  # INT-4: 블록 있는 스터디 = 블록 전달
    assert "virtual_beads" not in d0.json() and set(d0.json()["vb_frame"]) == {"origin", "e_xi", "e_eta", "n_h"}   # 비드 0개 = frame 만
    d1 = derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB]))
    assert d1.status_code == 200, d1.text
    assert KW[-1]["virtual_bead"] == BLOCK == s["inputs"]["virtual_bead"]
    assert KW[-1]["vb_plan"] == "plate" and KW[-1]["tie"] is not None                             # 계획 열 vbead(코어 plan_for) · tie 집합(코어 함수)
    doe_select.reset_caches()
    _legacy(engine, s)
    s2 = api(client, "GET", f"/doe/studies/{s['id']}").json()
    r = derive(client, s2, sel2(sha, gbead("b1", 11), virtual_beads=[VB]))
    assert r.status_code == 200 and KW[-1]["virtual_bead"] is None and KW[-1]["vb_plan"] is None        # 옛 스터디 = 블록 없음(코어가 VB_SCOPE)
    r0 = derive(client, s2, sel0)
    assert r0.status_code == 200 and "vb_frame" not in r0.json() and "virtual_beads" not in r0.json()   # 옛 스터디 비드 0개 = 옛 응답 모양


def test_vb_plan_from_core_plan_table_not_scenario_name(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    from esl_platform.api.services import doe as svc

    s, sha = ready2(client, world, engine, esl_root)
    monkeypatch.setattr(svc, "_study_plan", lambda st: {"vbead": "none"})
    assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    assert KW[-1]["vb_plan"] == "none"
    src = (REPO / "backend" / "esl_platform" / "api" / "services" / "doe_select.py").read_text(encoding="utf-8")
    assert 'scenario == "select"' not in src.split("def vbead_of")[1].split("def _ids_sha")[0]          # 시나리오 이름 분기 없음(정적)


def test_tie_ids_come_from_core_function(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    from esl_platform.api.services import doe_select
    from esl_platform.core import opt_core

    s, sha = ready2(client, world, engine, esl_root)
    seen = {}

    def fake(doe, out_dir, mesh):
        seen.update(doe=doe, n=len(mesh["node_id"]))
        return [7, 3]

    monkeypatch.setattr(opt_core, "doe_jig_tie_ids", fake, raising=False)
    doe_select.reset_caches()
    assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    assert KW[-1]["tie"] == [7, 3] and seen["doe"]["virtual_bead"] == BLOCK


@pytest.mark.parametrize("pos_u", ["absent", "off", "on"])
def test_tie_ids_same_as_worker_regardless_of_pos_u(client, world, engine, esl_root, monkeypatch, pos_u):  # noqa: F811
    """INT-1: 가상 비드 있는 선택의 derive tie_node_ids = 코어 ``jig_tie_ids_at``(워커 ``_pos_u_tie_ids`` 와 같은 함수) — 스터디 pos_u 블록
    없음·enabled false·켬 세 경우 모두 같은 집합(옛 동작: pos_u 없으면 빈 배열 → VB_FIXED 가 워커와 달랐음)."""
    from esl.doe import stages
    from esl_platform.api.services import doe_select

    monkeypatch.setattr(stages, "_jig", lambda c: {"fix_kinds": ["bolt"]})
    monkeypatch.setattr(stages, "_lt_plan", lambda c: {"jig_fix": "fixed", "vbead": "plate"})
    monkeypatch.setattr(stages, "_jig_nodes", lambda c, plan, mesh, J, infos: {"node_id": np.array([7, 3, 11])})
    s, sha = ready2(client, world, engine, esl_root)
    blk = {"absent": None, "off": {"schema": 1, "enabled": False}, "on": {"schema": 1, "range_rel": 0.25}}[pos_u]
    with engine.begin() as cn:
        if blk is None:
            cn.execute(text("UPDATE bead_does SET inputs = inputs - 'pos_u' WHERE id=:i"), {"i": s["id"]})
        else:
            cn.execute(text("UPDATE bead_does SET inputs = jsonb_set(inputs, '{pos_u}', CAST(:p AS JSONB)) WHERE id=:i"),
                       {"p": json.dumps(blk), "i": s["id"]})
    doe_select.reset_caches()
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    worker = stages._pos_u_tie_ids(stages._ReadCtx({"scenario": "select"}, str(esl_root)), {"node_id": np.arange(3)})
    assert KW[-1]["tie"] == worker.tolist() == [7, 3, 11]


def test_derive_response_keys_and_cache_key(client, world, engine, esl_root):  # noqa: F811
    from esl_platform.api.services import doe_select

    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), virtual_beads=[VB, {**VB, "id": "a2", "flip": True, "r": 0}])
    r = derive(client, s, sel)
    assert r.status_code == 200, r.text
    d = r.json()
    a1, a2 = d["virtual_beads"]
    for k in ("id", "name", "p0", "p1_resolved", "len_mm", "angle_deg", "side_resolved", "ok", "reasons", "warnings", "h", "n_wall", "n_top",
              "r_resolved", "r_source", "host", "host_floor", "preview"):
        assert k in a1, k
    assert "depth_max_mm" not in a1 and "depth_max_mm" not in json.dumps(d)                          # 개정 3 — 키 없음
    assert a1["r_source"] == "default" and a2["r_source"] == "user" and a2["r_resolved"] == 0.0 and a2["side_resolved"] == "-"
    assert a1["host"] == "base" and a1["warnings"][0]["text"] and set(d["vb_frame"]) == {"origin", "e_xi", "e_eta", "n_h"}
    n = len(KW)
    assert derive(client, s, sel).status_code == 200 and len(KW) == n                                # 같은 입력 = 캐시
    assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200 and len(KW) == n + 1   # 다른 선택 = 다른 sha
    with engine.begin() as cn:                                                                       # 블록이 다르면 다른 derive(같은 선택)
        odd = {**BLOCK, "margin_mm": 9.0}
        cn.execute(text("UPDATE bead_does SET inputs = jsonb_set(inputs, '{virtual_bead}', CAST(:p AS JSONB)) WHERE id=:i"),
                   {"p": json.dumps(odd), "i": s["id"]})
    s2 = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert derive(client, s2, sel).status_code == 200 and len(KW) == n + 2 and KW[-1]["virtual_bead"] == odd


def test_snapshot_block_passed_to_core_normalize(client, world, engine, esl_root):  # noqa: F811
    """§19.4-3·INT-2: 가상 비드 θ 기본·범위는 스냅샷 블록 값 — 백엔드는 블록을 코어 normalize_v2(virtual_bead=)에 그대로 넘기고 cfg 는 덮어쓰지
    않음(설정이 바뀌어도 선택 sha 같게 — 해석은 코어 vb_block 한 곳)."""
    s, sha = ready2(client, world, engine, esl_root)
    odd = {**BLOCK, "theta_default_deg": 30.0, "theta_range_deg": [20.0, 45.0]}
    with engine.begin() as cn:
        cn.execute(text("UPDATE bead_does SET inputs = jsonb_set(inputs, '{virtual_bead}', CAST(:p AS JSONB)) WHERE id=:i"),
                   {"p": json.dumps(odd), "i": s["id"]})
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert derive(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    assert NORM_KW[-1]["block"] == odd                                                                # 블록 그대로
    assert NORM_KW[-1]["vb"]["theta_default_deg"] == 45.0 and NORM_KW[-1]["vb"]["theta_range_deg"] == [15.0, 60.0]   # cfg 덮어쓰기 없음
    assert NORM_KW[-1]["vb"]["max_count"] == 4
    src = (REPO / "backend" / "esl_platform" / "api" / "services" / "doe_select.py").read_text(encoding="utf-8")
    assert "_vb_norm_cfg" not in src                                                                  # 우회 제거(정적)


def test_vbead_only_selection_allowed(client, world, engine, esl_root):  # noqa: F811
    """beads 0 + virtual_beads ≥ 1 — 백엔드 스키마가 막지 않음(규칙은 코어)."""
    s, sha = ready2(client, world, engine, esl_root)
    sel = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1}, "beads": [], "virtual_beads": [VB]}
    r = put(client, s, sel)
    assert r.status_code == 200, r.text
    g = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()
    assert g["input"]["virtual_beads"][0]["id"] == "a1" and g["derived"]["virtual_beads"][0]["preview"]      # 조회 = 지금 derive(미리보기 있음)


# ================================================================ 저장 · 변수 표 (§5.1·§19.2-3·§19.7)
def test_db_summary_has_no_preview_but_get_does(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    assert put(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    stored = _row(engine, s["id"])["selection"]["derived"]
    assert stored["virtual_beads"] and all("preview" not in v for v in stored["virtual_beads"])        # DB 요약에는 큰 미리보기 자료 없음
    assert stored["virtual_beads"][0]["r_resolved"] == 3.0 and stored["vb_frame"]
    sel = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()
    assert sel["derived"]["virtual_beads"][0]["preview"]["idx"] == [1, 2, 3]


def test_params_a_row_warp_text_and_bead_text(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    assert put(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB, {**VB, "id": "a2", "name": "bad"}])).status_code == 200
    stored = _row(engine, s["id"])["selection"]["derived"]
    arow = [r for r in stored["params"] if r["type"] == "A"][0]
    assert "text" not in arow["guard"]["warp"]                                                         # DB 에는 문구를 저장하지 않음(응답 때만)
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    rows = {r["name"]: r for r in p["params"]}
    a = rows["A1_A"]
    assert a["type"] == "A" and a["form"] == "hinge" and a["nominal"] == 0.0 and a["feasible"] == [0.0, 6.0] and a["label"] == "추가 비드 1 · 깊이"
    assert a["vb"]["r"] == 3.0 and a["vb"]["r_source"] == "default" and a["vb"]["host"] == "base" and "depth_max_mm" not in a["vb"]
    assert a["guard"]["warp"]["n"] == 3 and a["guard"]["warp"]["text"] == "깊이 6.0 mm 에서 뒤틀린 사각 요소 3 개(최대 22.5°) — 꺾인 모서리가 요소를 비스듬히 지나서 생김. 범위는 줄이지 않음"
    assert a["guard"]["A"] == {"state": "ok"}
    beads = {b["id"]: b for b in p["beads"]}
    assert beads["a1"]["kind"] == "virtual" and beads["a1"]["warnings"][0]["text"] == a["guard"]["warp"]["text"]
    assert beads["a2"]["vb_reason"]["code"] == "VB_OVER_BEAD" and beads["a2"]["vb_reason"]["text"] == "기존 비드와 겹침"


def test_params_warp_zero_has_no_text_and_no_vb_untouched():
    from esl_platform.api.services import doe_select as ds

    t = {"params": [{"name": "A1_A", "type": "A", "guard": {"warp": {"n": 0, "max_deg": 3.0, "at": 4.0, "limit_deg": 15.0}}}],
         "beads": [{"id": "a1", "kind": "virtual", "warnings": [], "vb_reason": None}]}
    o = ds.with_vb_text(t)
    assert "text" not in o["params"][0]["guard"]["warp"] and o["beads"][0]["vb_reason"] is None
    plain = {"params": [{"name": "B1_D", "type": "D"}], "beads": [{"id": "b1", "kind": "select"}]}
    assert ds.with_vb_text(plain) is plain                                                            # 가상 비드 없는 표 = 같은 객체
    assert t["params"][0]["guard"]["warp"].get("text") is None                                        # 입력 불변


def test_job_params_selection_has_no_response_text(client, world, engine, esl_root):  # noqa: F811
    """작업 params(워커 기저·행렬 해시 입력)에는 응답용 문구가 섞이지 않는다."""
    from esl_platform.api.services import doe_select as ds

    s, sha = ready2(client, world, engine, esl_root)
    assert put(client, s, sel2(sha, gbead("b1", 11), virtual_beads=[VB])).status_code == 200
    doc = _row(engine, s["id"])["selection"]
    jp = ds.job_selection(doc)
    arow = [r for r in jp["params"] if r["type"] == "A"][0]
    assert "text" not in arow["guard"]["warp"] and jp["input"]["virtual_beads"][0]["id"] == "a1"


# ================================================================ 코어 e2e (대역 아님, V-0250-VB-33·28)
_CORE_TESTS = str(Path(__file__).resolve().parents[2] / "tests" / "doe")
if _CORE_TESTS not in sys.path:
    sys.path.insert(0, _CORE_TESTS)


@pytest.fixture()
def real_core(monkeypatch):
    """대역을 걷어내고 실제 ``esl.doe.bead_graph`` (autouse _fake_graph 가 sys.modules 에 끼운 것을 되돌림)."""
    import importlib

    monkeypatch.delitem(sys.modules, "esl.doe.bead_graph", raising=False)
    mod = importlib.import_module("esl.doe.bead_graph")
    from esl_platform.api.services import doe_select

    doe_select.reset_caches()
    return mod


@pytest.fixture(scope="module")
def vworld():
    import synth_vbead as sv

    m, g, lab, fx, _d = sv.graph_world()
    return m, g, lab, fx, sv.frame_of()


def _e2e(vworld, vbs, *, block=None, plan="plate", c=None, beads=True):
    from esl.doe import bead_graph as bgr
    from esl_platform.api.services import doe_select as ds
    from esl_platform.core.config import bead_doe_settings

    m, g, lab, fx, fr = vworld
    c = c or bead_doe_settings(None)
    blk = block if block is not None else BLOCK
    gd = {"graph": g, "labels": lab, "sha256": bgr.graph_sha_of(g), "w_clamp": None, "range_guard": None, "shape_rules": None,
          "virtual_bead": blk, "vb_plan": plan, "tie_node_ids": []}
    sel = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}},
           "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": int(g["segments"][1]["anchor"])}]}] if beads else [],
           "virtual_beads": vbs}
    norm, sha = ds.normalize(c, sel, m, gd)
    inputs = {"mesh": m, "frame": fr, "fixed_scan": fx, "graph": gd, "mesh_sha256": "m" * 64}
    return ds.derive(c, inputs, norm, sha), norm, sha


def test_core_e2e_derive_response_shape(real_core, vworld):  # noqa: F811
    from esl_platform.api.schemas import SelectionDerived
    from esl_platform.api.services import doe_select as ds
    from esl_platform.core.config import bead_doe_settings

    d, norm, sha = _e2e(vworld, [VB])
    assert norm["virtual_beads"][0]["id"] == "a1"
    v = d["virtual_beads"][0]
    assert v["ok"] is True and v["reasons"] == [] and v["host"] == "base" and v["r_source"] == "default" and v["r_resolved"] > 0
    assert v["side_resolved"] in ("+", "-") and "depth_max_mm" not in v and v["preview"]["idx"] and v["outline_ab"]
    assert v["p0_resolved"] == pytest.approx(VB["p0"], abs=1e-6)                                    # INT-8: 판 위 시작점(평판 z 0 = 입력 그대로)
    assert set(d["vb_frame"]) == {"origin", "e_xi", "e_eta", "n_h"}
    out = SelectionDerived.model_validate(d).model_dump()                                           # 응답 모델이 두 키를 버리지 않음
    assert out["virtual_beads"][0]["id"] == "a1" and out["vb_frame"]
    arow = [r for r in d["params"] if r["type"] == "A"][0]
    assert arow["name"] == "A1_A" and arow["form"] == "hinge" and arow["label"] == "추가 비드 1 · 깊이" and arow["feasible"] == [0.0, 6.0]
    assert arow["vb"]["host"] == "base" and arow["vb"]["r_source"] == "default" and "depth_max_mm" not in arow["vb"]
    assert any(b["id"] == "a1" and b["kind"] == "virtual" for b in d["param_beads"])
    nov, _, _ = _e2e(vworld, [])                                                                    # 가상 비드 없음 = virtual_beads 키 없음
    assert "virtual_beads" not in nov and set(nov["vb_frame"]) == {"origin", "e_xi", "e_eta", "n_h"}   # INT-4: 켜진 스터디 = 첫 비드 전 frame
    vf0, vf1 = nov["vb_frame"], d["vb_frame"]
    o0, n0 = np.asarray(vf0["origin"]), np.asarray(vf0["n_h"])
    p0 = np.asarray(VB["p0"])
    lev = float(np.median(np.asarray(vworld[0]["x0"]) @ n0))                                          # 합성 평판(평평) 높이
    assert abs(float(o0 @ n0) - lev) < 1e-6                                                           # origin = 판 위(법선 성분 = 판 높이)
    a0 = [float((p0 - o0) @ np.asarray(vf0[k])) for k in ("e_xi", "e_eta")]
    a1 = [float((p0 - np.asarray(vf1["origin"])) @ np.asarray(vf1[k])) for k in ("e_xi", "e_eta")]
    assert np.allclose(a0, a1, atol=1e-6)                                                             # 평평한 판: 첫 비드 전후 ξ·η 같음(이 세계의 사실)
    nob = ds.derive(bead_doe_settings(None), {"mesh": vworld[0], "frame": vworld[4], "fixed_scan": vworld[3],
                                              "graph": {**_e2e_gd(vworld), "virtual_bead": None}, "mesh_sha256": "m" * 64}, *_norm0(vworld))
    assert "vb_frame" not in nob                                                                      # 블록 없음 = 키 없음
    assert "vb_frame" not in ds.summary(nov)                                                          # DB 요약 모양 그대로(비드 0개)
    assert "virtual_beads" not in SelectionDerived.model_validate(nov).model_dump()


def test_core_e2e_flip_r_and_scope(real_core, vworld):  # noqa: F811
    auto, _, sha0 = _e2e(vworld, [VB])
    flp, nflip, sha1 = _e2e(vworld, [{**VB, "flip": True}])
    a, f = auto["virtual_beads"][0], flp["virtual_beads"][0]
    assert a["side_resolved"] != f["side_resolved"] and sha0 != sha1                                  # flip = 자동의 반대, 선택 sha 달라짐
    assert nflip["virtual_beads"][0]["flip"] is True
    _, nf, sha2 = _e2e(vworld, [{**VB, "flip": False}])
    assert "flip" not in nf["virtual_beads"][0] and sha2 == sha0                                      # flip false = 키 없음 = sha 같음
    r0, n0, s3 = _e2e(vworld, [{**VB, "r": 0}])
    assert n0["virtual_beads"][0]["r"] == 0.0 and s3 != sha0                                           # r 0 은 키 유지
    assert r0["virtual_beads"][0]["r_source"] == "user" and r0["virtual_beads"][0]["r_resolved"] == 0.0
    sc, _, _ = _e2e(vworld, [VB], block={})                                                          # 블록 비어 있음 아님 — None 과 다름
    assert sc["virtual_beads"][0]["ok"] in (True, False)
    d_none, _, _ = _e2e_noblock(vworld)
    v = d_none["virtual_beads"][0]
    assert v["ok"] is False and [x["code"] for x in v["reasons"]] == ["VB_SCOPE"] and v["reasons"][0]["text"]       # 블록 없는 옛 스터디 = VB_SCOPE


def _e2e_gd(vworld):
    from esl.doe import bead_graph as bgr

    _m, g, lab, _fx, _fr = vworld
    return {"graph": g, "labels": lab, "sha256": bgr.graph_sha_of(g), "w_clamp": None, "range_guard": None, "shape_rules": None}


def _norm0(vworld):
    """가상 비드 없는 선택(_e2e 와 같은 그래프 비드 1개 — virtual_beads 키 없음)."""
    from esl_platform.api.services import doe_select as ds
    from esl_platform.core.config import bead_doe_settings

    m, g = vworld[0], vworld[1]
    gd = {**_e2e_gd(vworld), "virtual_bead": BLOCK}
    sel = {"schema_version": 2, "graph": {"sha256": gd["sha256"], "rules": int(g["rules"]), "edits": {}},
           "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": int(g["segments"][1]["anchor"])}]}]}
    return ds.normalize(bead_doe_settings(None), sel, m, gd)


def _e2e_noblock(vworld):
    from esl.doe import bead_graph as bgr
    from esl_platform.api.services import doe_select as ds
    from esl_platform.core.config import bead_doe_settings

    m, g, lab, fx, fr = vworld
    c = bead_doe_settings(None)
    gd = {"graph": g, "labels": lab, "sha256": bgr.graph_sha_of(g), "w_clamp": None, "range_guard": None, "shape_rules": None,
          "virtual_bead": None}
    sel = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}}, "beads": [],
           "virtual_beads": [VB]}
    norm, sha = ds.normalize(c, sel, m, gd)
    return ds.derive(c, {"mesh": m, "frame": fr, "fixed_scan": fx, "graph": gd, "mesh_sha256": "m" * 64}, norm, sha), norm, sha


def test_core_e2e_snapshot_theta_and_422(real_core, vworld):  # noqa: F811
    from esl_platform.api.services import doe_select as ds
    from esl_platform.core.errors import DomainError as EslError

    narrow = {**BLOCK, "theta_range_deg": [20.0, 40.0], "theta_default_deg": 30.0}
    _e2e(vworld, [{**VB, "theta_deg": 40.0}], block=narrow)                                          # 스냅샷 상한 40 통과
    with pytest.raises(EslError) as ei:
        _e2e(vworld, [{**VB, "theta_deg": 50.0}], block=narrow)                                      # 지금 설정은 60 이지만 스냅샷 40 — 422
    de = ei.value
    assert de.status == 422 and de.code == "VB_INPUT_INVALID" and de.detail()["key"] == "theta_deg"
    _, n, _ = _e2e(vworld, [VB], block=narrow)
    assert "theta_deg" not in n["virtual_beads"][0]                                                   # 기본 θ = 스냅샷 기본(30) — 입력에 없으므로 키 없음
    with pytest.raises(EslError) as ei:
        _e2e(vworld, [{**VB, "side": "+"}])
    assert ei.value.detail()["key"] == "side"
    with pytest.raises(EslError) as ei:
        _e2e(vworld, [{**VB, "id": f"a{i}"} for i in range(1, 6)])
    assert ei.value.code == "VB_MAX_COUNT"


def test_core_e2e_vbead_only_and_params_text(real_core, vworld):  # noqa: F811
    from esl_platform.api.services import doe_select as ds

    d, norm, _ = _e2e(vworld, [VB], beads=False)
    assert norm["beads"] == [] and d["virtual_beads"][0]["ok"] is True and d["beads"] == []
    doc = {"input": norm, "derived": ds.summary(d)}
    assert all("preview" not in v for v in doc["derived"]["virtual_beads"])
    t = ds.params_table(doc)
    a = [r for r in t["params"] if r["type"] == "A"]
    assert len(a) == 1 and a[0]["name"] == "A1_A"
    t2 = ds.with_vb_text({**t, "params": [{**a[0], "guard": {"warp": dict(WARP)}}]})
    assert "뒤틀린 사각 요소 3 개" in t2["params"][0]["guard"]["warp"]["text"]
