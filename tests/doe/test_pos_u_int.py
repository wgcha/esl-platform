"""v0.24.9 통합(INT-2): 백엔드 derive_v2 의 tie_node_ids 원천 = ``stages.pos_u_tie_ids_at``(워커 select 기저 ``_pos_u_tie_ids`` 와 같은 함수,
읽기 전용 Ctx — 스터디 폴더에 쓰지 않음). pos_u 블록 없음·지그 꺼짐 = 빈 배열."""
from __future__ import annotations

import numpy as np
import pytest

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


VB_BLOCK = {"schema": 1, "min_wall_elems": 2.0, "margin_mm": 3.0, "theta_default_deg": 45.0, "theta_range_deg": [15.0, 60.0],
            "warp_max_deg": 15.0, "r_default_h_mult": 1.0}


@pytest.mark.parametrize("pos_u", [None, {**POS_U, "enabled": False}, POS_U], ids=["no_pos_u", "pos_u_off", "pos_u_on"])
def test_tie_set_same_source_as_worker_regardless_of_pos_u(tmp_path, monkeypatch, pos_u):
    """v0.25.0 INT-1: 가상 비드 VB_FIXED 의 지그 tie 집합 — 백엔드 derive 원천(``jig_tie_ids_at``) = 워커 select 기저(``_pos_u_tie_ids`` —
    BD_MATRIX 가 가상 비드 선택에 pos_u 유무와 무관하게 부름). pos_u 없음·enabled false·켬 세 경우 모두 같은 집합(빈 배열 아님)."""
    monkeypatch.setattr(stages, "_jig", lambda c: {"fix_kinds": ["bolt"]})
    monkeypatch.setattr(stages, "_lt_plan", lambda c: {"jig_fix": "fixed", "vbead": "plate"})
    monkeypatch.setattr(stages, "_jig_nodes", lambda c, plan, mesh, J, infos: {"node_id": np.array([7, 3, 11])})
    doe = {"scenario": "select", "virtual_bead": VB_BLOCK, **({"pos_u": pos_u} if pos_u is not None else {})}
    mesh = {"node_id": np.arange(20)}
    backend = stages.jig_tie_ids_at(doe, str(tmp_path), mesh)
    worker = stages._pos_u_tie_ids(stages._ReadCtx(doe, str(tmp_path)), mesh)
    assert backend.tolist() == worker.tolist() == [7, 3, 11] and backend.dtype == np.int64
    assert stages.pos_u_tie_ids_at is stages.jig_tie_ids_at                                     # v0.24.9 계약 이름 = 같은 함수
    assert list(tmp_path.iterdir()) == []


def test_worker_vbead_path_uses_same_tie_function_static():
    """워커 BD_MATRIX 가상 비드 분기의 tie_node_ids = ``_pos_u_tie_ids``(pos_u 조건 밖) — 백엔드 원천과 같은 함수(정적)."""
    import inspect
    src = inspect.getsource(stages)
    blk = src.split('if norm.get("virtual_beads"):           # v0.25.0 VB')[1].split("if sr is None")[0]
    assert "tie_node_ids=_pos_u_tie_ids(c, t.mesh)" in blk and "_pos_u(c)" not in blk
    assert "return _pos_u_tie_ids(_ReadCtx(doe, out_dir), mesh)" in inspect.getsource(stages.jig_tie_ids_at)
