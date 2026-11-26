"""v0.24.9 통합(INT-2): 백엔드 derive_v2 의 tie_node_ids 원천 = ``stages.pos_u_tie_ids_at``(워커 select 기저 ``_pos_u_tie_ids`` 와 같은 함수,
읽기 전용 Ctx — 스터디 폴더에 쓰지 않음). pos_u 블록 없음·지그 꺼짐 = 빈 배열."""
from __future__ import annotations

import numpy as np

from esl.doe import stages

POS_U = {"schema": 1, "range_rel": 0.25, "max_rel": 0.5, "gap_rel": 0.5, "hold_frac_max": 0.2}


def test_no_block_or_no_jig_is_empty_and_writes_nothing(tmp_path):
    mesh = {"node_id": np.arange(6)}
    assert stages.pos_u_tie_ids_at({"scenario": "select"}, str(tmp_path), mesh).size == 0
    assert stages.pos_u_tie_ids_at({"scenario": "select", "pos_u": POS_U}, str(tmp_path), mesh).size == 0   # 스냅샷 rank 없음 = 지그 없음
    assert list(tmp_path.iterdir()) == []


def test_same_function_as_worker(tmp_path, monkeypatch):
    """읽기 Ctx 도 워커 Ctx 와 같은 계획 열(jig_fix)·같은 _jig_nodes 를 부른다."""
    seen = []

    def fake_nodes(c, plan, mesh, J, infos):
        seen.append((c.scn, c.p("prep"), plan["jig_fix"], J["fix_kinds"]))
        return {"node_id": np.array([7, 3, 11])}

    monkeypatch.setattr(stages, "_jig", lambda c: {"fix_kinds": ["bolt"]})
    monkeypatch.setattr(stages, "_lt_plan", lambda c: {"jig_fix": "fixed"})
    monkeypatch.setattr(stages, "_jig_nodes", fake_nodes)
    got = stages.pos_u_tie_ids_at({"scenario": "select", "pos_u": POS_U}, str(tmp_path), {"node_id": np.arange(20)})
    assert got.tolist() == [7, 3, 11] and got.dtype == np.int64
    assert seen == [("select", str(tmp_path / "prep"), "fixed", ["bolt"])]
    monkeypatch.setattr(stages, "_lt_plan", lambda c: {"jig_fix": "none"})
    assert stages.pos_u_tie_ids_at({"scenario": "select", "pos_u": POS_U}, str(tmp_path), {"node_id": np.arange(20)}).size == 0
