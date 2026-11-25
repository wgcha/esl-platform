"""v0.24.7 통합 — 백엔드 ↔ 실제 코어(대역 아님): 합성 한쪽 입구 그래프 → floor_fixed 스터디 → 변수 표 응답.

B1 은 derive 호출에 depth_section·section_rules 를 넘기고(floor_fixed 스냅샷만), 코어(esl.doe.bead_graph)가 이제 받는다.
여기서는 코어 분류(prep_graph)로 만든 실제 graph.json·라벨로 선택 저장·GET /params 까지 이어져 D 행 section·W1 행 w_side·
beads[].w_reason 이 실제 값으로 오는지, entry_fixed·옛 스터디는 호출 인수가 변하지 않는지(코어 입장에서 같은 결과) 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from doe_support import api, study_dir
from test_doe_select_api import (  # noqa: F401 - 픽스처 재사용
    _row,
    code,
    es,
    sbody,
    settings_dict,
    simulate_select_prep,
    world,
)
from test_doe_select_graph_api import _create, derive, put  # noqa: F401

_CORE_TESTS = str(Path(__file__).resolve().parents[2] / "tests" / "doe")
if _CORE_TESTS not in sys.path:
    sys.path.insert(0, _CORE_TESTS)

from _bg_util import CFG, esl_mesh  # noqa: E402


@pytest.fixture(scope="module")
def one_side():
    from beadgraph.testing import synth_oneside as so

    c = so.oneside("b")
    return esl_mesh({"x0": c["nodes"], "conn": c["conn"], "fixed": c["fixed"]}), (c["fixed"] + 1).tolist()


def _study(client, world, engine, esl_root, one_side, **kw):  # noqa: F811
    from esl.doe import bead_graph as bgr

    mesh, fixed = one_side
    s = _create(client, world, **kw)
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], mesh, fixed=fixed, schema=2)
    bj = study_dir(esl_root, s["id"]) / "prep" / "base.json"          # 합성 판 frame — 기준 평면 축(simulate_select_prep 의 frame 은 축 없음)
    meta = json.loads(bj.read_text(encoding="utf-8"))
    meta["frame"] = {**meta["frame"], "e_xi": [1.0, 0.0, 0.0], "e_eta": [0.0, 1.0, 0.0], "n": [0.0, 0.0, 1.0]}
    bj.write_text(json.dumps(meta), encoding="utf-8")
    sd = study_dir(esl_root, s["id"]) / "prep" / "select"
    assert bgr.prep_graph(mesh, fixed, CFG, str(sd))["ok"]
    g, _lab = bgr.load_graph(str(sd))
    gsha = bgr.graph_sha_of(g)
    ids = [x for x in g["segments"] if x["type"] != "base"]
    sel = {"schema_version": 2, "graph": {"sha256": gsha, "rules": g["rules"]},
           "beads": [{"id": f"b{i + 1}", "name": f"B{i + 1}", "src": "graph", "segs": [{"anchor": x["anchor"]}]}
                     for i, x in enumerate(ids)]}
    return api(client, "GET", f"/doe/studies/{s['id']}").json(), sel


def _params(client, s, sel):
    r = put(client, s, sel)
    assert r.status_code == 200, r.text
    p = api(client, "GET", f"/doe/studies/{s['id']}/params")
    assert p.status_code == 200, p.text
    return p.json()


def test_floor_fixed_reaches_params_with_real_core(client, world, engine, esl_root, one_side):  # noqa: F811
    s, sel = _study(client, world, engine, esl_root, one_side, depth_section="floor_fixed")
    d = derive(client, s, sel)
    assert d.status_code == 200, d.text
    p = _params(client, s, sel)
    rows = p["params"]
    dr = [r for r in rows if r["type"] == "D"]
    wr = [r for r in rows if r["type"] == "W"]
    assert dr and all(r["section"]["mode"] == "floor_fixed" and "applied" in r["section"] and "cot_deg" in r["section"] for r in dr)
    assert wr and all(r["w_side"] == "one" for r in wr)                      # 한쪽 입구 W1(코어가 만든 행)
    assert all(b["w_reason"] is None for b in p["beads"] if b.get("src") == "graph")   # W 가 있으니 불가 사유 없음


def test_entry_fixed_has_no_w_and_real_reason(client, world, engine, esl_root, one_side):  # noqa: F811
    s, sel = _study(client, world, engine, esl_root, one_side, depth_section="entry_fixed")
    p = _params(client, s, sel)
    assert not [r for r in p["params"] if r["type"] == "W"]
    assert not any("section" in r or "w_side" in r for r in p["params"])
    gb = [b for b in p["beads"] if b.get("src") == "graph"]
    assert gb and all(b["w_reason"]["code"] == "W_ENTRY_ONE_SIDE" and b["w_reason"]["text"] != "W_ENTRY_ONE_SIDE" for b in gb)


def test_call_args_only_for_floor_fixed(client, world, engine, esl_root, one_side, monkeypatch):  # noqa: F811
    from esl_platform.api.services import doe_select as ds

    seen = []
    orig = ds._graph_call

    def spy(name, *a, **kw):
        if name == "derive_v2":
            seen.append({k: kw.get(k) for k in ("depth_section", "section_rules")})
        return orig(name, *a, **kw)

    monkeypatch.setattr(ds, "_graph_call", spy)
    for ds_val, want in (("floor_fixed", "floor_fixed"), ("entry_fixed", None)):
        seen.clear()
        ds.reset_caches()
        s, sel = _study(client, world, engine, esl_root, one_side, depth_section=ds_val)
        assert derive(client, s, sel).status_code == 200
        assert seen and all(x["depth_section"] == want for x in seen)
        assert all((x["section_rules"] is not None) == (want is not None) for x in seen)


def test_ds_warning_messages_and_settings_notes(client, world, engine, esl_root, one_side):  # noqa: F811
    """응답의 DS_* 경고에 message(bead·var 채움, 영문 꼬리 없음), settings.depth_section_notes = doe_messages.json 원문(꼬리 없이)."""
    from esl_platform.api.services import doe_select as ds

    s, sel = _study(client, world, engine, esl_root, one_side, depth_section="floor_fixed")
    p = _params(client, s, sel)
    ones = [w for b in p["beads"] for w in b["warnings"] if w["code"] == "DS_ONE_SIDE"]
    assert ones and all(w["message"].startswith(f"비드 {w['bead']}:") and "Info" not in w["message"] for w in ones)
    fb = ds.with_ds_text([{"code": "DS_FALLBACK", "bead": "b3", "var": "B3_D", "reason": "W_ENTRY_NONE"}])[0]
    assert fb["message"].startswith("비드 b3 B3_D: ") and "W_ENTRY_NONE" in fb["message"] and "Info" not in fb["message"]
    assert ds.with_ds_text([{"code": "DS_FALLBACK", "message": "x"}])[0]["message"] == "x"
    st = api(client, "GET", "/doe/settings").json()
    n = st["depth_section_notes"]
    assert set(n) == {"DS_CLONE_NOTE", "DS_CLONE_NOTE_ENTRY", "DS_CLONE_NOTE_ENTRY_NONE"}
    assert all(v and "Info" not in v for v in n.values()) and "{n}" in n["DS_CLONE_NOTE_ENTRY"] and "{names}" in n["DS_CLONE_NOTE_ENTRY"]
    c = api(client, "POST", f"/doe/studies/{s['id']}/clone", json={"depth_section": "entry_fixed"})
    assert c.status_code == 201, c.text
    from test_doe_select_api import _job

    w = [x for x in _job(engine, c.json()["job"]["id"])["warnings"] if x["code"] == "DS_CLONE_NOTE"]
    assert len(w) == 1 and w[0]["dropped"] == [] and w[0]["message"].startswith(n["DS_CLONE_NOTE_ENTRY_NONE"][:12])
