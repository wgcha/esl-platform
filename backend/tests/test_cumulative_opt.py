"""OPT S1 기준 Case 가 누적 씬이면 정보 경고 S1_BASE_CUMULATIVE(실행 허용) — 계약 esl_cumulative_input.md §10."""
from __future__ import annotations

import json

import pytest
from esl_test_support import API
from opt_support import W, make_case, opt_settings_dict, plate, seed_opt_entry
from sqlalchemy import text


@pytest.fixture()
def settings_dict(tmp_path):
    return opt_settings_dict(tmp_path)


def test_s1_check_warns_cumulative_base(client, engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    a = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [a]}, headers=W)
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []
    with engine.begin() as c:
        es = c.execute(text("SELECT extract_summary FROM cases WHERE id='c1'")).scalar_one() or {}
        es["cumulative"] = {"enabled": True, "eq_mode": "incremental"}
        c.execute(text("UPDATE cases SET extract_summary = CAST(:e AS JSONB) WHERE id='c1'"), {"e": json.dumps(es)})
    out = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [a]}, headers=W).json()
    assert [w["code"] for w in out["warnings"]] == ["S1_BASE_CUMULATIVE"] and "_cumulative" not in out["base"]
