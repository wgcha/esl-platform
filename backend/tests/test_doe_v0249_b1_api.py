"""v0.24.9 B1 — 비드 위치 변수 U·하중 공간 고정 load_follow 백엔드(계약 esl_bead_pos_u.md §1.2·§1.3·§2.2·§2.3·§3·§4, V-0249-PU-16·17·18의 백엔드 부분).

- 설정: pydantic ↔ yaml 2개 ↔ 계약 기본값(코어 DEFAULTS 에 블록이 있으면 같은 값), 범위 검사.
- 스냅샷: 새 select 스터디 params.doe.pos_u·load_follow == inputs 같은 값, enabled false·select 밖 = 키 없음, 옛 스터디 응답 = null.
- 복제: 원 블록 그대로(없던 스터디에 주입하지 않음, 설정이 바뀌어도 원 값).
- derive: 스냅샷 pos_u 를 코어에 통과(받을 때만), beads[].u_reason{code, text}(U_OFF·없음 = null).
- 변수 표: 코어가 낸 U 행 필드 통과. 행렬: type U 만 "공칭 ∈ 범위" 422, "> 0" 검사 제외, matrix.load_follow.
- 결과: load_follow{…}·경고 LOAD_FOLLOW_SPATIAL·PU_* 통과, 옛 결과 = null.
코어 ``esl.doe.bead_graph`` 는 test_doe_v0247_b1_api 와 같은 대역(fake) — U 행·u_reason 을 내는 판으로 바꿔 쓴다(계약 형식 합성 자료).
"""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from doe_support import api
from esl_test_support import REPO
from sqlalchemy import text
from test_doe_rank_metric_api import _done, cbody, shapes3  # noqa: F401
from test_doe_select_api import (  # noqa: F401 - 픽스처 재사용
    _fake_core,
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
    _fake_graph,
    derive,
    gbead,
    put,
    ready2,
    sel2,
    write_graph,
)

KW: list[dict] = []        # 코어(대역) derive_v2 가 받은 pos_u 키
U_REASONS = {"b2": "U_NETWORK", "b3": {"code": "U_ONE_SIDE"}}     # 코어가 주는 두 모양(코드 문자열 · {code})


def _fake_derive_v2(mesh, norm, cfg, graph, labels, *, frame=None, fixed_scan=None, bead=None, pos_u=None):
    """test_doe_select_graph_api.fake_derive_v2 + pos_u 기록 + params·param_beads(b1 = U 행, 나머지 = u_reason) — 계약 §1.3 형식 합성."""
    from test_doe_select_graph_api import fake_derive_v2

    KW.append({"pos_u": copy.deepcopy(pos_u)})
    d = fake_derive_v2(mesh, norm, cfg, graph, labels, frame=frame, fixed_scan=fixed_scan, bead=bead)
    params, pbeads = [], []
    for b in d["beads"]:
        if b.get("src") != "graph":
            continue
        ur = U_REASONS.get(b["id"]) if pos_u is not None else "U_OFF"        # 옛 스냅샷 = U_OFF(표시 없음)
        if pos_u is not None and b["id"] == "b1":
            ur = None
        b["u_reason"] = ur
        pbeads.append({"id": b["id"], "name": b["name"], "kind": "select", "src": "graph", "n_tiers": 1, "W_nom": b["W_nom"],
                       "u_reason": ur, "warnings": []})
        for kind in ("D", "W", "U"):
            if kind == "U" and not (pos_u is not None and b["id"] == "b1"):
                continue
            row = {"name": f"{b['id'].upper()}_{kind}", "type": kind, "bead": b["id"], "tier": 1,
                   "nominal": {"D": 4.0, "W": 40.0, "U": 0.0}[kind], "feasible": [-8.0, 8.0] if kind == "U" else [1.0, 8.0],
                   "feasible_source": "estimate", "default_range": [-3.0, 3.0] if kind == "U" else [2.0, 6.0],
                   "use_default": False if kind == "U" else True, "group_members": [f"{b['id'].upper()}_{kind}"]}
            if kind == "U":
                row.update(unit="mm", dir={"xi": 0.0, "eta": 1.0}, dir_text="+η 쪽", w_ref=40.0)
            params.append(row)
    d["params"], d["param_beads"] = params, pbeads
    return d


@pytest.fixture(autouse=True)
def _core(_fake_graph):  # noqa: F811
    _fake_graph.derive_v2 = _fake_derive_v2
    KW.clear()
    yield


def _doe(engine, st):
    return _job(engine, st["job"]["id"])["params"]["doe"]


def _legacy(engine, st):
    """v0.24.8 이전 스냅샷 흉내 — 작업·inputs 의 pos_u·load_follow 삭제(옛 스터디)."""
    with engine.begin() as cn:
        cn.execute(text("UPDATE jobs SET params = jsonb_set(params, '{doe}', (params->'doe') - 'pos_u' - 'load_follow') WHERE id=:i"),
                   {"i": st["job"]["id"]})
        cn.execute(text("UPDATE bead_does SET inputs = (inputs - 'pos_u') - 'load_follow' WHERE id=:i"), {"i": st["id"]})


def _saved(client, world, engine, esl_root, **kw):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root, **kw)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12), gbead("b3", 13))
    r = put(client, s, sel)
    assert r.status_code == 200, r.text
    return api(client, "GET", f"/doe/studies/{s['id']}").json(), sha


# ================================================================ 설정 거울 (V-0249-PU-17)
POS_U_DEFAULT = {"enabled": True, "range_rel": 0.25, "max_rel": 0.5, "gap_rel": 0.5, "hold_frac_max": 0.2}
LOAD_FOLLOW_DEFAULT = {"cell_mm": 3.0, "noise_floor_min": 0.01}


def test_pos_u_settings_mirror():
    from esl_platform.core.config import BeadDoeCfg, bead_doe_settings

    m = BeadDoeCfg().model_dump()
    assert m["pos_u"] == POS_U_DEFAULT and m["load_follow"] == LOAD_FOLLOW_DEFAULT          # 계약 §3 기본
    from esl.doe import DEFAULTS

    for k, want in (("pos_u", POS_U_DEFAULT), ("load_follow", LOAD_FOLLOW_DEFAULT)):
        if k in DEFAULTS:                                           # 코어 병합 뒤 = 같은 값(병합 전에는 pydantic 거울이 채움)
            assert DEFAULTS[k] == want
    got = bead_doe_settings(None)
    assert got["pos_u"] == POS_U_DEFAULT and got["load_follow"] == LOAD_FOLLOW_DEFAULT
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["pos_u"] == m["pos_u"] and y["load_follow"] == m["load_follow"], p
        v = BeadDoeCfg.model_validate(y).model_dump()
        assert v["pos_u"] == m["pos_u"] and v["load_follow"] == m["load_follow"]


def test_load_follow_cell_min_cross_check_and_snapshot_422():
    """cell_mm 하한 = load_transfer.cell_min_mm — 직접 적은 값은 설정 검사, 기본값이 하한 아래(v0.24.8 설정이 cell_min 을 올린 경우)는 새 스터디 스냅샷 422."""
    from esl_platform.api.services import doe as svc
    from esl_platform.core.config import BeadDoeCfg
    from esl_platform.core.errors import DomainError

    lt = {"cell_min_mm": 4.0, "cell_choices_mm": [None, 10], "diag": {"alt_cell_size_mm": 5.0, "cell_sweep_mm": []}}
    jg = {"jig_grid": {"cell_mm": 4.0, "conv_mm": [5.0, 10.0]}}
    with pytest.raises(Exception, match="cell_min_mm"):
        BeadDoeCfg.model_validate({"load_transfer": lt, "rank": jg, "load_follow": {"cell_mm": 3.0}})        # 직접 적은 값 < 하한
    ok = BeadDoeCfg.model_validate({"load_transfer": lt, "rank": jg})                                       # 기본 3.0 < 4 — 설정은 통과
    c = ok.model_dump()
    with pytest.raises(DomainError) as ei:
        svc.pos_u_snapshot(c)
    assert ei.value.status == 422 and ei.value.code == "CONFIG_INVALID"
    c["pos_u"]["enabled"] = False
    assert svc.pos_u_snapshot(c) is None
    assert BeadDoeCfg.model_validate({"load_transfer": lt, "rank": jg, "load_follow": {"cell_mm": 4.0}}).load_follow.cell_mm == 4.0


@pytest.mark.parametrize("bad", [
    {"pos_u": {"range_rel": 0}}, {"pos_u": {"range_rel": 1.5}}, {"pos_u": {"max_rel": 0.1}},          # max_rel ≥ range_rel
    {"pos_u": {"gap_rel": 0}}, {"pos_u": {"hold_frac_max": 1.1}}, {"pos_u": {"hold_frac_max": -0.1}},
    {"pos_u": {"unknown": 1}}, {"load_follow": {"cell_mm": 0}}, {"load_follow": {"cell_mm": 2.0}},    # 직접 적은 값 < load_transfer.cell_min_mm 3.0
    {"load_follow": {"cell_mm": 1e6}}, {"load_follow": {"noise_floor_min": -1}}, {"load_follow": {"noise_floor_min": 2}},
])
def test_pos_u_settings_ranges(bad):
    from esl_platform.core.config import BeadDoeCfg

    with pytest.raises(Exception):
        BeadDoeCfg.model_validate(bad)
    ok = BeadDoeCfg.model_validate({"pos_u": {"range_rel": 0.5, "max_rel": 0.5, "hold_frac_max": 0.0},
                                    "load_follow": {"cell_mm": 10.0, "noise_floor_min": 0.0}})
    assert ok.pos_u.range_rel == 0.5 and ok.load_follow.cell_mm == 10.0


def test_settings_out_pos_u(client, world):  # noqa: F811
    s = api(client, "GET", "/doe/settings").json()
    assert s["pos_u"] == POS_U_DEFAULT and s["load_follow"] == LOAD_FOLLOW_DEFAULT


# ================================================================ 스냅샷 (V-0249-PU-16)
def test_snapshot_new_select_study(client, world, engine, esl_root):  # noqa: F811
    s = _create(client, world)
    d = _doe(engine, s)
    want_pu = {"schema": 1, "range_rel": 0.25, "max_rel": 0.5, "gap_rel": 0.5, "hold_frac_max": 0.2}
    assert d["pos_u"] == want_pu and d["load_follow"] == {"schema": 1, "cell_mm": 3.0}      # noise_floor_min 은 스냅샷에 없음(해시 밖)
    assert s["inputs"]["pos_u"] == d["pos_u"] and s["inputs"]["load_follow"] == d["load_follow"]
    row = _row(engine, s["id"])["inputs"]
    assert row["pos_u"] == d["pos_u"] and row["load_follow"] == d["load_follow"]
    # 블록 값 = 설정 값 사본(설정이 바뀌면 새 스터디만 달라짐)
    assert json.dumps(d["pos_u"], sort_keys=True) == json.dumps(s["inputs"]["pos_u"], sort_keys=True)


def test_snapshot_values_follow_config(client, world, engine, esl_root, settings_dict):  # noqa: F811
    from esl_platform.api.services import doe as svc

    cfg = {"pos_u": {"enabled": True, "range_rel": 0.1, "max_rel": 0.3, "gap_rel": 0.4, "hold_frac_max": 0.0},
           "load_follow": {"cell_mm": 5.0, "noise_floor_min": 0.5}}
    pu, lf = svc.pos_u_snapshot(cfg)
    assert pu == {"schema": 1, "range_rel": 0.1, "max_rel": 0.3, "gap_rel": 0.4, "hold_frac_max": 0.0}
    assert lf == {"schema": 1, "cell_mm": 5.0}
    cfg["pos_u"]["enabled"] = False
    assert svc.pos_u_snapshot(cfg) is None                          # 꺼짐 = 두 키 다 없음(옛 동작)


def test_snapshot_absent_outside_select_and_old_study_null(client, world, engine, esl_root):  # noqa: F811
    from doe_support import upload_step

    uid = upload_step(client)
    ok = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"], world["b"]],
                                                   "step_upload_id": uid})
    assert ok.status_code == 201, ok.text
    assert "pos_u" not in ok.json()["inputs"] and "load_follow" not in ok.json()["inputs"]        # select 밖 = 키 없음
    assert "pos_u" not in _doe(engine, ok.json())
    s = _create(client, world)
    _legacy(engine, s)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["inputs"]["pos_u"] is None and g["inputs"]["load_follow"] is None                    # 옛 select = 응답만 null
    row = _row(engine, s["id"])["inputs"]
    assert "pos_u" not in row and "load_follow" not in row                                        # DB 에는 키 쓰지 않음


# ================================================================ 복제 (V-0249-PU-16 "복제 = 원 블록")
def test_clone_copies_original_block_not_current_config(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    # 원 스터디 블록을 지금 설정과 다른 값으로 바꿔 놓고(옛 설정으로 만든 스터디 흉내) 복제 → 원 값 그대로
    odd_pu = {"schema": 1, "range_rel": 0.1, "max_rel": 0.2, "gap_rel": 0.3, "hold_frac_max": 0.4}
    odd_lf = {"schema": 1, "cell_mm": 6.0}
    with engine.begin() as cn:
        cn.execute(text("UPDATE jobs SET params = jsonb_set(jsonb_set(params, '{doe,pos_u}', CAST(:p AS JSONB)), "
                        "'{doe,load_follow}', CAST(:l AS JSONB)) WHERE id=:i"),
                   {"p": json.dumps(odd_pu), "l": json.dumps(odd_lf), "i": s["job"]["id"]})
        cn.execute(text("UPDATE bead_does SET inputs = jsonb_set(jsonb_set(inputs, '{pos_u}', CAST(:p AS JSONB)), "
                        "'{load_follow}', CAST(:l AS JSONB)) WHERE id=:i"), {"p": json.dumps(odd_pu), "l": json.dumps(odd_lf), "i": s["id"]})
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert c.status_code == 201, c.text
    c = c.json()
    d = _doe(engine, c)
    assert d["pos_u"] == odd_pu and d["load_follow"] == odd_lf
    assert c["inputs"]["pos_u"] == odd_pu and c["inputs"]["load_follow"] == odd_lf
    ri = _row(engine, c["id"])["inputs"]
    assert ri["pos_u"] == odd_pu and ri["load_follow"] == odd_lf


def test_clone_does_not_inject_into_old_study(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    _legacy(engine, s)
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    for body in ({}, {"depth_section": "entry_fixed"}, {"depth_section": "floor_fixed"}):
        c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json=body)
        assert c.status_code == 201, c.text
        c = c.json()
        d = _doe(engine, c)
        assert "pos_u" not in d and "load_follow" not in d                       # 없던 스터디에 주입 금지
        ri = _row(engine, c["id"])["inputs"]
        assert "pos_u" not in ri and "load_follow" not in ri
        assert c["inputs"]["pos_u"] is None and c["inputs"]["load_follow"] is None


# ================================================================ derive 통과 · u_reason (§1.2·§4)
def test_derive_passes_snapshot_pos_u_to_core(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11))
    assert derive(client, s, sel).status_code == 200
    assert KW[-1]["pos_u"] == s["inputs"]["pos_u"] and KW[-1]["pos_u"]["schema"] == 1
    _legacy(engine, s)
    from esl_platform.api.services import doe_select

    doe_select.reset_caches()
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert derive(client, s, sel).status_code == 200
    assert KW[-1] == {"pos_u": None}                                             # 옛 스터디 = None(캐시 공유 없음)


def test_u_reason_in_derive_and_params(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12), gbead("b3", 13))
    d = derive(client, s, sel).json()
    ur = {b["id"]: b["u_reason"] for b in d["beads"]}
    assert ur["b1"] is None
    assert ur["b2"]["code"] == "U_NETWORK" and ur["b2"]["text"]                  # 코드 문자열 → {code, text}
    assert ur["b3"]["code"] == "U_ONE_SIDE" and ur["b3"]["text"]                 # {code} → {code, text}
    assert put(client, s, sel).status_code == 200
    stored = _row(engine, s["id"])["selection"]["derived"]
    assert all("text" not in (b.get("u_reason") or {}) for b in stored["beads"])    # DB 요약에는 text 를 저장하지 않음(응답 때만)
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    pb = {b["id"]: b for b in p["beads"]}
    assert pb["b1"]["u_reason"] is None and pb["b2"]["u_reason"]["code"] == "U_NETWORK" and pb["b3"]["u_reason"]["code"] == "U_ONE_SIDE"
    g = api(client, "GET", f"/doe/studies/{s['id']}/selection").json()["derived"]["beads"]
    assert {b["id"]: b.get("u_reason") for b in g}["b2"]["code"] == "U_NETWORK"


def test_u_reason_old_study_is_null(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12))
    _legacy(engine, s)
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    d = derive(client, s, sel).json()
    assert [b["u_reason"] for b in d["beads"]] == [None, None]                   # U_OFF = 표시 없음(null)
    assert put(client, s, sel).status_code == 200
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    assert all(b["u_reason"] is None for b in p["beads"])
    assert not [r for r in p["params"] if r["type"] == "U"]                      # U 행 없음


def test_u_reason_doc_unit():
    from esl_platform.api.services import doe_select as ds

    assert ds.u_reason_doc(None) is None and ds.u_reason_doc("") is None and ds.u_reason_doc("U_OFF") is None
    assert ds.u_reason_doc({"code": "U_OFF"}) is None
    assert ds.u_reason_doc("U_AREA")["code"] == "U_AREA" and ds.u_reason_doc({"code": "U_CLOSED"})["code"] == "U_CLOSED"
    assert ds.u_reason_doc({"code": "U_HELD", "text": "코어 문구"}) == {"code": "U_HELD", "text": "코어 문구"}
    beads = [{"id": "b1", "src": "graph"}, {"id": "b2", "src": "elems"}, {"id": "b3"}]
    out = ds.with_w_reason(beads, None, {"b1": "U_NETWORK"})
    assert out[0]["u_reason"]["code"] == "U_NETWORK" and "u_reason" not in out[1] and "u_reason" not in out[2]
    assert ds.pos_u_of({"inputs": {}}) == {"pos_u": None, "load_follow": None}
    assert ds.pos_u_of({"inputs": {"pos_u": {"schema": 1}, "load_follow": {"schema": 1, "cell_mm": 3.0}}})["pos_u"] == {"schema": 1}


# ================================================================ 변수 표 U 행 (§1.3·§4)
def test_params_pass_u_row_fields(client, world, engine, esl_root):  # noqa: F811
    s, sha = ready2(client, world, engine, esl_root)
    sel = sel2(sha, gbead("b1", 11), gbead("b2", 12))
    assert put(client, s, sel).status_code == 200
    p = api(client, "GET", f"/doe/studies/{s['id']}/params").json()
    u = [r for r in p["params"] if r["type"] == "U"]
    assert [r["name"] for r in u] == ["B1_U"]
    r = u[0]
    assert r["nominal"] == 0.0 and r["unit"] == "mm" and r["use_default"] is False and r["feasible"] == [-8.0, 8.0]
    assert r["default_range"] == [-3.0, 3.0] and r["dir"] == {"xi": 0.0, "eta": 1.0} and r["dir_text"] == "+η 쪽" and r["w_ref"] == 40.0
    d = [x for x in p["params"] if x["type"] == "D"]
    assert d and all("unit" not in x and "dir" not in x for x in d)             # D·W 행 불변


# ================================================================ 행렬 422 · load_follow (§1.3-5·§4)
def _matrix(client, s, *rows, method="lhs", n=4):
    spec = {"method": method, "n": n, "seed": 3, "params": [{"name": a, "lo": lo, "hi": hi} for a, lo, hi in rows]}
    return api(client, "POST", f"/doe/studies/{s['id']}/matrix", json={"version": s["version"], "spec": spec})


def test_matrix_u_nominal_in_range_422(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    for lo, hi in ((1.0, 5.0), (-5.0, -1.0), (0.5, 3.0)):                       # 공칭 0 이 범위 밖
        r = _matrix(client, s, ("B1_U", lo, hi))
        assert r.status_code == 422 and code(r) == "DOE_RANGE_INVALID", (lo, hi, r.text)
        assert "위치" in r.json()["detail"]["message"] or "0" in r.json()["detail"]["message"]
    for lo, hi in ((-3.0, 3.0), (-1.0, 5.0), (-5.0, 0.0), (0.0, 4.0)):         # 비대칭·경계 = 통과
        r = _matrix(client, s, ("B1_U", lo, hi))
        assert r.status_code == 200, (lo, hi, r.text)
    # lo = 0 이하(음수)가 "> 0" 검사에 걸리지 않음 = U 제외, D 는 그대로
    r = _matrix(client, s, ("B1_D", -1.0, 3.0))
    assert r.status_code == 422 and code(r) == "DOE_RANGE_INVALID"
    r = _matrix(client, s, ("B1_D", 3.0, 5.0), ("B1_U", -2.0, 2.0))
    assert r.status_code == 200, r.text


def test_matrix_load_follow_field(client, world, engine, esl_root):  # noqa: F811
    s, _ = _saved(client, world, engine, esl_root)
    a = _matrix(client, s, ("B1_D", 3.0, 5.0), ("B1_W", 30.0, 50.0)).json()
    assert a["load_follow"] == "node"                                          # U 변수 없음
    b = _matrix(client, s, ("B1_D", 3.0, 5.0), ("B1_U", -2.0, 2.0)).json()
    assert b["load_follow"] == "spatial"
    assert a["matrix_sha256"] != b["matrix_sha256"]
    _legacy(engine, s)
    s = api(client, "GET", f"/doe/studies/{s['id']}").json()
    c = _matrix(client, s, ("B1_D", 3.0, 5.0)).json()
    assert c["load_follow"] is None                                            # 옛 스터디 = null


# ================================================================ 결과 통과 (§2.3·§4)
def test_results_pass_load_follow_block_and_warnings(client, world, engine, esl_root):  # noqa: F811
    lf = {"mode": "spatial", "cell_mm": 3.0, "dF_max": 1e-12, "dM_max": 2e-12, "corr_rel_max": 0.01, "small_frac_max": 0.02,
          "d000_shift_rel": 0.004}
    warns = [{"code": "LOAD_FOLLOW_SPATIAL", "level": "info", "cell_mm": 3.0, "n_pos_vars": 1,
              "message": "위치 변수가 있어 하중을 공간에 고정했습니다(3 mm 셀)"},
             {"code": "PU_LIN_SKIPPED", "level": "info", "message": "선형 보조 열 생략"}]
    sid = _done(client, world, engine, esl_root, {"load_follow": lf, "warnings": warns})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["load_follow"] == lf
    assert all(w in o["warnings"] for w in warns)
    old = _done(client, world, engine, esl_root, {})
    assert api(client, "GET", f"/doe/studies/{old}/results").json()["load_follow"] is None       # 옛·node 결과 = null


# ================================================================ OpenAPI
def test_openapi_has_pos_u_fields():
    doc = json.loads((REPO / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    sch = doc["components"]["schemas"]
    assert {"pos_u", "load_follow"} <= set(sch["DoeSettingsOut"]["properties"])
    assert "load_follow" in sch["DoeResultOut"]["properties"] and "load_follow" in sch["DoeMatrixOut"]["properties"]
    assert {"kind", "dirs", "val"} <= set(sch["View3dSupport"]["properties"])
