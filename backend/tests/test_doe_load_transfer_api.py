"""v0.20.0 하중 전달 API·설정(계약 esl_load_transfer.md §4·§5·§13.6, V-LT-10·19): 최상위 bead_doe.load_transfer 설정 검사(경계값)·
거울(compare.load_transfer = ④ 전용 support·region), 요청 두 키 모든 시나리오 허용·검사 순서·코드, 해석된 스냅샷
`params.doe.load_transfer`(compare 만 ④ 키 평면 합침)·`inputs.load_transfer`(모드별 키), 옛 스터디 응답(키 없음), 복제 규칙(LT-11),
settings 최상위 블록, 결과 진단 요약·view3d_ref 통과."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from doe_support import api, doe_settings_dict, finish_job, study_dir, update_study
from esl_test_support import API, REPO, make_settings_dict
from opt_support import make_case, seed_opt_entry
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    R,
    W,
    _app,
    _fresh_cache,
    _job,
    cbody,
    code,
    multi_upload,
    settings_dict,
    shapes3,
    world,
)

LT_COMMON = {"method": "work", "cell_size_mm": None}                                          # ①②③ 요약
LT_DEFAULT = {**LT_COMMON, "support": "transfer", "region_mode": "auto"}                      # ④ 요약


# ================================================================ 설정(§4.1·§13.6)
def _cfg(**over):
    from esl_platform.core.config import BeadDoeLoadTransferCfg

    return BeadDoeLoadTransferCfg(**over)


CMP_DEFAULT = {"support": "transfer", "support_tol_mm": None, "region": {"mode": "auto", "pad_mm": None, "min_frac": 0.5}}


def test_defaults_and_mirror():
    """새 스터디 기본 = work·진단 켬(사용자 확정 2026-11-13), 지지 이전·영역 auto 는 ④ 전용(compare.load_transfer).
    예시 yaml 2개 = pydantic 기본(거울)."""
    from esl_platform.core.config import BeadDoeCfg

    d = _cfg().model_dump()
    assert d == {"method": "work", "cell_size_mm": None, "cell_choices_mm": [None, 10.0, 5.0, 3.0], "cell_min_mm": 3.0,
                 "work": {"knn": 8, "proj_tol_mm": 3.0, "newton_iter": 10, "far_warn_frac": 0.01, "far_fail_frac": 0.2,
                          "fail_dist_mm": 20.0, "fail_frac": 0.2},
                 "diag": {"enabled": True, "alt": True, "alt_cell_size_mm": 3.0, "alt_designs": "auto",
                          "cell_sweep_mm": [None, 10.0, 5.0, 3.0]}}
    dump = BeadDoeCfg().model_dump()
    assert dump["load_transfer"] == d and dump["compare"]["load_transfer"] == CMP_DEFAULT
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["load_transfer"] == d, p
        assert y["compare"]["load_transfer"] == CMP_DEFAULT, p
    from esl.doe import DEFAULTS

    if "load_transfer" in DEFAULTS:                                   # 코어 병합 후 — 키 이름·값 거울
        assert DEFAULTS["load_transfer"] == d
    if "load_transfer" in (DEFAULTS.get("compare") or {}):
        assert DEFAULTS["compare"]["load_transfer"] == CMP_DEFAULT


def test_settings_mirror_into_core_view():
    """bead_doe_settings 가 코어 DEFAULTS 에 아직 없어도 load_transfer 를 pydantic 기본으로 채움(워커 스냅샷 cfg)."""
    from esl_platform.core.config import bead_doe_settings

    s = bead_doe_settings(None)
    assert s["load_transfer"]["method"] == "work" and s["compare"]["load_transfer"]["support"] == "transfer"
    assert "method" not in s["compare"]["load_transfer"]


@pytest.mark.parametrize("bad", [
    {"method": "morph"}, {"cell_size_mm": 2.9}, {"cell_size_mm": 200.1}, {"cell_size_mm": 0},
    {"cell_min_mm": 0.5}, {"cell_min_mm": 200.5},
    {"cell_choices_mm": []}, {"cell_choices_mm": [None, 10.0, 10.0]}, {"cell_choices_mm": [2.0, 5.0]},
    {"cell_choices_mm": [None] + [float(x) for x in range(10, 18)]},                       # 길이 9 > 8
    {"cell_choices_mm": [201.0]},
    {"diag": {"cell_sweep_mm": [5.0, 5.0]}}, {"diag": {"cell_sweep_mm": [1.0]}}, {"diag": {"alt_cell_size_mm": 1.0}},
    {"diag": {"cell_sweep_mm": [float(x) for x in range(10, 19)]}}, {"diag": {"alt_designs": "yes"}},
    {"work": {"knn": 0}}, {"work": {"knn": 65}}, {"work": {"proj_tol_mm": 0}}, {"work": {"newton_iter": 0}},
    {"work": {"newton_iter": 51}}, {"work": {"far_warn_frac": 0.3}}, {"work": {"far_fail_frac": 1.1}},
    {"work": {"far_warn_frac": -0.1}}, {"work": {"fail_dist_mm": 0}}, {"work": {"fail_frac": 1.1}},
    {"work": {"fail_frac": -0.1}}, {"unknown": 1},
    {"support": "transfer"}, {"region": {"mode": "all"}},                 # 최상위에서는 ④ 전용 키 금지(별칭 없음)
])
def test_config_rejects(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "load_transfer": bad}
    lc = load_config_dict(d, environ={})
    assert not lc.ok
    assert any(k.startswith("bead_doe.load_transfer") for k in lc.error_keys()), lc.errors()


@pytest.mark.parametrize("bad", [
    {"support": "nearest"}, {"support_tol_mm": 0}, {"region": {"mode": "bbox"}}, {"region": {"pad_mm": 0}},
    {"region": {"min_frac": 0}}, {"region": {"min_frac": 1.01}}, {"unknown": 1},
    {"method": "work"}, {"cell_size_mm": 5.0}, {"diag": {"enabled": False}},   # compare 쪽에는 방식·셀·진단 없음(이동)
])
def test_config_rejects_compare(tmp_path, bad):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "compare": {"load_transfer": bad}}
    lc = load_config_dict(d, environ={})
    assert not lc.ok
    assert any(k.startswith("bead_doe.compare.load_transfer") for k in lc.error_keys()), lc.errors()


@pytest.mark.parametrize("good", [
    {"method": "cell"}, {"cell_size_mm": 3.0}, {"cell_size_mm": 200.0}, {"cell_min_mm": 1.0, "cell_choices_mm": [1.0]},
    {"cell_choices_mm": [None]}, {"diag": {"cell_sweep_mm": []}}, {"diag": {"alt_cell_size_mm": None}},
    {"diag": {"alt_designs": "on"}}, {"diag": {"alt_designs": "off"}},
    {"work": {"proj_tol_mm": None, "far_warn_frac": 0.0, "far_fail_frac": 0.0}},
    {"work": {"far_warn_frac": 1.0, "far_fail_frac": 1.0}}, {"work": {"fail_dist_mm": 0.5, "fail_frac": 0.0}},
    {"cell_choices_mm": [None] + [float(x) for x in range(10, 17)]},                      # 길이 8
])
def test_config_accepts(tmp_path, good):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "load_transfer": good}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()


@pytest.mark.parametrize("good", [
    {"support": "auto", "support_tol_mm": 5.0}, {"region": {"mode": "all", "pad_mm": 2.0, "min_frac": 1.0}},
])
def test_config_accepts_compare(tmp_path, good):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "compare": {"load_transfer": good}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()


# ================================================================ settings 블록
def test_settings_block(client, world):
    s = api(client, "GET", "/doe/settings").json()
    assert s["load_transfer"] == {"method": "work", "cell_size_mm": None,
                                  "cell_choices_mm": [None, 10.0, 5.0, 3.0], "cell_min_mm": 3.0}
    assert "load_transfer" not in s["compare"]                      # 미출시라 별칭 없이 최상위로 이동


# ================================================================ 요청 검사(§4.2)
def check(client, world, shapes, **kw):
    return api(client, "POST", "/doe/check-inputs", json=cbody(world, shapes, **kw))


def test_check_default_and_overrides(client, world):
    sh = shapes3(client)
    r = check(client, world, sh)
    assert r.status_code == 200, r.text
    assert r.json()["load_transfer"] == LT_DEFAULT
    cases = [
        ({"load_transfer": "work"}, LT_DEFAULT),
        ({"load_transfer": "work", "cell_size_mm": None}, LT_DEFAULT),
        ({"load_transfer": "cell"}, {**LT_DEFAULT, "method": "cell"}),                       # 생략 = 설정 cell_size_mm(null)
        ({"load_transfer": "cell", "cell_size_mm": None}, {**LT_DEFAULT, "method": "cell"}),
        ({"load_transfer": "cell", "cell_size_mm": 5.0}, {**LT_DEFAULT, "method": "cell", "cell_size_mm": 5.0}),
        ({"load_transfer": "cell", "cell_size_mm": 3}, {**LT_DEFAULT, "method": "cell", "cell_size_mm": 3.0}),   # 하한 포함
        ({"load_transfer": "cell", "cell_size_mm": 200}, {**LT_DEFAULT, "method": "cell", "cell_size_mm": 200.0}),  # 상한 포함
        ({"load_transfer": None}, LT_DEFAULT),
    ]
    for kw, want in cases:
        r = check(client, world, sh, **kw)
        assert r.status_code == 200, (kw, r.text)
        assert r.json()["load_transfer"] == want, kw


@pytest.mark.parametrize("kw, extra", [
    ({"load_transfer": "work", "cell_size_mm": 5.0}, {}),                    # work + 값
    ({"cell_size_mm": 5.0}, {}),                                             # 설정 method = work + 값
    ({"load_transfer": "cell", "cell_size_mm": 2.99}, {"min": 3.0, "max": 200.0}),
    ({"load_transfer": "cell", "cell_size_mm": 200.01}, {"min": 3.0, "max": 200.0}),
    ({"load_transfer": "cell", "cell_size_mm": 0}, {"min": 3.0, "max": 200.0}),
    ({"load_transfer": "cell", "cell_size_mm": -1}, {"min": 3.0, "max": 200.0}),
])
def test_check_invalid(client, world, kw, extra):
    r = check(client, world, shapes3(client), **kw)
    assert r.status_code == 422 and code(r) == "LOAD_TRANSFER_INVALID", r.text
    for k, v in extra.items():
        assert r.json()["detail"][k] == v


def test_check_invalid_value_and_scenarios(client, world):
    sh = shapes3(client)
    r = check(client, world, sh, load_transfer="morph")                      # pydantic Literal → 422(스키마)
    assert r.status_code == 422
    r = check(client, world, sh, cell_size_mm="x")
    assert r.status_code == 422


def _same(client, world, **kw):
    from doe_support import body, upload_step

    return body([world["a"], world["b"]], upload_step(client), **kw)


def test_other_scenarios_accept_keys(client, world, engine):
    """§13.6: 두 키는 모든 시나리오에서 허용(compare 전용 422 폐지) — ①(same)·select(case)·select(manual) 요약 = {method, cell_size_mm}."""
    for extra, want in (({}, LT_COMMON), ({"load_transfer": "work"}, LT_COMMON),
                        ({"load_transfer": "cell"}, {**LT_COMMON, "method": "cell"}),
                        ({"load_transfer": "cell", "cell_size_mm": 5.0}, {"method": "cell", "cell_size_mm": 5.0}),
                        ({"load_transfer": "cell", "cell_size_mm": None}, {"method": "cell", "cell_size_mm": None}),
                        ({"cell_size_mm": None}, LT_COMMON)):
        r = api(client, "POST", "/doe/check-inputs", json=_same(client, world, **extra))
        assert r.status_code == 200, (extra, r.text)
        assert r.json()["load_transfer"] == want, extra
    # 검사 코드·범위는 ④ 와 같음
    for extra, ex in (({"load_transfer": "work", "cell_size_mm": 5.0}, {}),
                      ({"cell_size_mm": 5.0}, {}),
                      ({"load_transfer": "cell", "cell_size_mm": 2.99}, {"min": 3.0, "max": 200.0}),
                      ({"load_transfer": "cell", "cell_size_mm": 200.5}, {"min": 3.0, "max": 200.0})):
        for path in ("/doe/check-inputs", "/doe/studies"):
            r = api(client, "POST", path, json=_same(client, world, **extra))
            assert r.status_code == 422 and code(r) == "LOAD_TRANSFER_INVALID", (extra, r.text)
            for k, v in ex.items():
                assert r.json()["detail"][k] == v
    r = api(client, "POST", "/doe/check-inputs", json=_same(client, world, load_transfer="morph"))
    assert r.status_code == 422
    # select(case) 도 같은 규칙
    sel = {"project_id": "p-1", "scenario": "select", "entry_ids": [world["a"], world["b"]], "load_transfer": "cell",
           "cell_size_mm": 10.0}
    r = api(client, "POST", "/doe/check-inputs", json=sel)
    assert r.status_code == 200, r.text
    assert r.json()["load_transfer"] == {"method": "cell", "cell_size_mm": 10.0}


def test_other_scenario_snapshot_and_clone(client, world, engine):
    r = api(client, "POST", "/doe/studies", json=_same(client, world, load_transfer="cell", cell_size_mm=5.0))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["load_transfer"] == {"method": "cell", "cell_size_mm": 5.0}     # compare 키(support·region_mode) 없음
    spec = _job(engine, s["job"]["id"])["params"]["doe"]["load_transfer"]
    assert spec == {**_cfg().model_dump(), "schema": 1, "method": "cell", "cell_size_mm": 5.0}   # ④ 키 합치지 않음
    assert "support" not in spec and "region" not in spec
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})
    assert r.status_code == 201, r.text
    assert r.json()["inputs"]["load_transfer"] == {"method": "cell", "cell_size_mm": 5.0}
    lt = _job(engine, r.json()["job"]["id"])["params"]["doe"]["load_transfer"]
    assert lt["method"] == "cell" and lt["cell_size_mm"] == 5.0 and "support" not in lt
    # 기본 요청 = work
    r = api(client, "POST", "/doe/studies", json=_same(client, world))
    assert r.json()["inputs"]["load_transfer"] == LT_COMMON


def test_check_order_after_existing(client, world):
    """기존 검사(SHAPES_EMPTY 등)가 먼저 — load_transfer 오류는 그 뒤."""
    r = check(client, world, [], load_transfer="work", cell_size_mm=5.0)
    assert r.status_code == 422 and code(r) == "SHAPES_EMPTY"


# ================================================================ 스냅샷(LT-11)
def test_study_snapshot_default(client, world, engine):
    sh = shapes3(client)
    r = api(client, "POST", "/doe/studies", json=cbody(world, sh))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["load_transfer"] == LT_DEFAULT
    spec = _job(engine, s["job"]["id"])["params"]["doe"]["load_transfer"]
    assert spec == {**_cfg().model_dump(), **CMP_DEFAULT, "schema": 1}        # compare 만 ④ 키(support·region)를 평면으로 합침
    assert [x["step_key"] for x in s["job"]["steps"]] == ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"]
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["inputs"]["load_transfer"] == LT_DEFAULT


def test_study_snapshot_override_cell(client, world, engine):
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client), load_transfer="cell", cell_size_mm=5.0))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["inputs"]["load_transfer"] == {**LT_DEFAULT, "method": "cell", "cell_size_mm": 5.0}
    spec = _job(engine, s["job"]["id"])["params"]["doe"]["load_transfer"]
    want = {**_cfg().model_dump(), **CMP_DEFAULT, "schema": 1, "method": "cell", "cell_size_mm": 5.0}
    assert spec == want                                  # 덮어쓰기는 method·cell_size_mm 두 개뿐
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client), load_transfer="cell", cell_size_mm=2.0))
    assert r.status_code == 422 and code(r) == "LOAD_TRANSFER_INVALID"


def test_snapshot_uses_configured_values(tmp_path, engine, fake_dashboard, clock):
    """설정이 바뀌면 새 스터디 스냅샷이 그 값을 따르고(기본 method cell·cell_size 10·support auto·region all·diag 끔), 요청 덮어쓰기는
    method·cell_size_mm 만. 스냅샷 이후 설정 변경은 기존 스터디에 영향 없음(작업 spec 고정)."""
    from test_doe_compare_api import record_paicad

    lt = {"method": "cell", "cell_size_mm": 10.0, "work": {"knn": 4}, "diag": {"enabled": False, "cell_sweep_mm": []}}
    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["load_transfer"] = lt
    d["bead_doe"]["compare"] = {"load_transfer": {"support": "auto", "support_tol_mm": 4.0, "region": {"mode": "all"}}}
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid],
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/check-inputs", json=b, headers=W)
        assert r.status_code == 200, r.text
        assert r.json()["load_transfer"] == {"method": "cell", "cell_size_mm": 10.0, "support": "auto", "region_mode": "all"}
        r = c.post(f"{API}/doe/check-inputs", json={**b, "cell_size_mm": None}, headers=W)       # 명시적 null = 기존 격자
        assert r.json()["load_transfer"]["cell_size_mm"] is None
        r = c.post(f"{API}/doe/check-inputs", json={**b, "load_transfer": "work"}, headers=W)    # work 는 셀 크기 없음
        assert r.json()["load_transfer"] == {"method": "work", "cell_size_mm": None, "support": "auto", "region_mode": "all"}
        r = c.post(f"{API}/doe/studies", json={**b, "load_transfer": "work"}, headers=W)
        assert r.status_code == 201, r.text
        spec = _job(engine, r.json()["job"]["id"])["params"]["doe"]["load_transfer"]
        assert spec["method"] == "work" and spec["cell_size_mm"] is None and spec["support_tol_mm"] == 4.0
        assert spec["work"]["knn"] == 4 and spec["diag"]["enabled"] is False and spec["schema"] == 1
        r = c.post(f"{API}/doe/check-inputs", json={**b, "load_transfer": "cell", "cell_size_mm": 2.5}, headers=W)
        assert r.status_code == 422 and code(r) == "LOAD_TRANSFER_INVALID"


# ================================================================ 옛 스터디·복제(LT-11)
def _legacy_study(client, world, engine):
    """키 없는 옛 스냅샷 스터디(작업 spec·inputs 에서 load_transfer 제거)."""
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client)))
    assert r.status_code == 201, r.text
    s = r.json()
    with engine.begin() as c:
        from sqlalchemy import text

        job = _job(engine, s["job"]["id"])
        params = copy.deepcopy(job["params"])
        params["doe"].pop("load_transfer")
        c.execute(text("UPDATE jobs SET params=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(params), "i": job["id"]})
        inp = copy.deepcopy(s["inputs"])
        inp.pop("load_transfer")
        c.execute(text("UPDATE bead_does SET inputs=CAST(:p AS JSONB) WHERE id=:i"), {"p": json.dumps(inp), "i": s["id"]})
    return s


def test_legacy_study_no_key(client, world, engine):
    s = _legacy_study(client, world, engine)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert "load_transfer" not in g["inputs"]                                 # 옛 스터디 = 키 없음
    finish_job(engine, s["job"]["id"])
    r = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={})        # 복제도 키 주입 없음(legacy 유지)
    assert r.status_code == 201, r.text
    assert "load_transfer" not in r.json()["inputs"]
    assert "load_transfer" not in _job(engine, r.json()["job"]["id"])["params"]["doe"]


def test_clone_keeps_method_refreshes_diag(tmp_path, engine, fake_dashboard, clock):
    """복제 = 원 스터디의 method·cell_size_mm·support·region 유지, diag 만 지금 설정."""
    from test_doe_compare_api import record_paicad

    d = doe_settings_dict(tmp_path)
    record_paicad(engine)
    with _app(tmp_path, engine, fake_dashboard, clock, d) as c:
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        uid, rels = multi_upload(c, 2)
        b = {"project_id": "p-1", "scenario": "compare", "entry_ids": [eid], "load_transfer": "cell", "cell_size_mm": 5.0,
             "shapes": [{"upload_id": uid, "rel": rels[0], "name": "A", "reference": True},
                        {"upload_id": uid, "rel": rels[1], "name": "B"}]}
        r = c.post(f"{API}/doe/studies", json=b, headers=W)
        assert r.status_code == 201, r.text
        s = r.json()
        assert _job(engine, s["job"]["id"])["params"]["doe"]["load_transfer"]["diag"]["enabled"] is True
        finish_job(engine, s["job"]["id"])
    d2 = copy.deepcopy(d)
    d2["bead_doe"]["load_transfer"] = {"method": "work", "diag": {"enabled": False}}
    d2["bead_doe"]["compare"] = {"load_transfer": {"support": "auto"}}
    with _app(tmp_path, engine, fake_dashboard, clock, d2) as c:
        r = c.post(f"{API}/doe/studies/{s['id']}/clone", json={}, headers=W)
        assert r.status_code == 201, r.text
        assert r.json()["inputs"]["load_transfer"] == {**LT_DEFAULT, "method": "cell", "cell_size_mm": 5.0}
        lt = _job(engine, r.json()["job"]["id"])["params"]["doe"]["load_transfer"]
        assert lt["method"] == "cell" and lt["cell_size_mm"] == 5.0 and lt["support"] == "transfer"
        assert lt["diag"]["enabled"] is False                                  # diag 만 현재 설정


# ================================================================ 결과(§5)
DIAG = {"method": "work", "cell_size_mm": None, "support": "transfer", "region_mode": "auto",
        "alt": {"method": "cell", "cell_size_mm": 3.0}, "truth": "direct_nodal",
        "summary": [{"variant": "work", "umax_ratio": [1.0, 1.0], "C_ratio": [1.0, 1.0], "mac_min": 1.0, "load_corr_min": 1.0}],
        "rank_alt_same": True, "warnings_n": 0}


def _done_study(client, world, engine, esl_root, extra):
    r = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client)))
    s = r.json()
    finish_job(engine, s["job"]["id"])
    base = study_dir(esl_root, s["id"])
    (base / "post").mkdir(parents=True)
    res = {"scenario": "compare", "reference_source": "step", "C_ref": 10.0,
           "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3},
           "n_ok": 0, "n_skipped": {}, "n_failed": {}, "ranking": [], "sensitivity": None,
           "sensitivity_reason": "COMPARE_NO_PARAMS", "boundary_warnings_n": 0, "view3d": ["d000", "d001"], "best": None,
           "noise_floor": None, "ratio_tol": 1e-6, "per_esl_inline": False, "esl": [], "warnings": [], **extra}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (base / "post" / "designs.json").write_text(json.dumps({"designs": [{"id": "d000", "status": "OK"}]}), encoding="utf-8")
    update_study(engine, s["id"], phase="DONE", result=res)
    return s["id"], base


def test_results_expose_diag(client, world, engine, esl_root):
    ref = {"e1": "d000_e00", "e2": "d000_e02"}
    esl = {"d001": "e1", "d002": "e2"}
    sid, base = _done_study(client, world, engine, esl_root,
                            {"load_transfer": DIAG, "view3d_ref": ref, "view3d_esl": esl})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["load_transfer"] == DIAG and o["view3d_ref"] == ref and o["view3d_esl"] == esl
    assert o["view3d"] == ["d000", "d001"]                                    # 목록 불변(d000_e* 안 들어감)
    # d000_e<kk> 는 DID_RE 를 통과 — 파일·manifest 가 있으면 같은 view3d 엔드포인트로
    d = base / "post" / "view3d" / "d000_e00"
    d.mkdir(parents=True)
    r = api(client, "GET", f"/doe/studies/{sid}/view3d/d000_e00/manifest.json")
    assert r.status_code == 404 and code(r) == "VIEW3D_NOT_FOUND"             # 파일 없음 — 라우팅·검사는 통과(400 아님)
    r = api(client, "GET", f"/doe/studies/{sid}/view3d/d000_E00/manifest.json")
    assert r.status_code == 404


def test_results_legacy_no_keys(client, world, engine, esl_root):
    sid, _ = _done_study(client, world, engine, esl_root, {})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["load_transfer"] is None and o["view3d_ref"] is None and o["view3d_esl"] is None


def test_openapi_has_keys():
    p = Path(REPO) / "docs" / "contracts" / "openapi_p1b.json"
    spec = json.loads(p.read_text(encoding="utf-8"))
    sc = spec["components"]["schemas"]
    for name, keys in (("DoeCheckIn", ("load_transfer", "cell_size_mm")), ("DoeStudyIn", ("load_transfer", "cell_size_mm")),
                       ("DoeCheckOut", ("load_transfer",)), ("DoeResultOut", ("load_transfer", "view3d_ref", "view3d_esl"))):
        for k in keys:
            assert k in sc[name]["properties"], (name, k)


def test_diag_file_download(client, world, engine, esl_root):
    """post/load_transfer_diag.json 은 기존 download 규칙(스터디 폴더 안 실파일·링크 아님)으로 읽힘 — 화이트리스트 변경 없음."""
    sid, base = _done_study(client, world, engine, esl_root, {"load_transfer": DIAG})
    (base / "post" / "load_transfer_diag.json").write_text(json.dumps({"schema": "esl/doe_load_transfer_diag/1"}), encoding="utf-8")
    r = api(client, "GET", f"/doe/studies/{sid}/download", params={"rel": "post/load_transfer_diag.json"})
    assert r.status_code == 200 and r.json()["schema"] == "esl/doe_load_transfer_diag/1"
    r = api(client, "GET", f"/doe/studies/{sid}/download", params={"rel": "post/../../x.json"})
    assert r.status_code in (400, 404, 422)
