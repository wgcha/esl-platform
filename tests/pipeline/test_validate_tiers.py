"""v0.24.5 ④ 검증 판정 단계화(PASS · 조건부 PASS · FAIL) + MAC 판정 — 코어 시험(계약 docs/contracts/esl_validate_tiers.md §5,
V-0245-VT-n). 골든 = ``vt_golden``(코어 변경 전 기록)."""
from __future__ import annotations

import os
import shutil

import pytest

import vt_golden as G


@pytest.fixture(scope="module")
def golden_runs(tmp_path_factory):
    runs = {}
    for name in G.CASES:
        root = str(tmp_path_factory.mktemp(f"vt_{name}"))
        runs[name] = G.build_case(name, root)
    raw = os.environ.get("ESL_VT_RAW_DIR")                 # 개발용: 산출물 사본(비교 디버깅)
    if raw:
        for name, r in runs.items():
            dst = os.path.join(raw, name)
            if not os.path.exists(dst):
                shutil.copytree(r["out"], dst)
    return runs


def test_v0245_vt_6_golden_record(golden_runs):
    """골든 기록(ESL_GOLDEN_RECORD=1, 파일 없을 때만) — 비교는 아래 시험들."""
    cur = {name: G.snapshot(r["out"], r["root"]) for name, r in golden_runs.items()}
    G.record_if_asked(cur)
    gold = G.load_golden()["cases"]
    assert set(gold) == set(G.CASES)
