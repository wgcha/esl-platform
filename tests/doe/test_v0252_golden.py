"""V-0252-2·10 골든 비교(계약 esl_tstar_manual_jig_force.md §8.2) — 기록 = tests/doe/golden_v0252_c1/golden.json(393789a8 코드).

A: 자동 t*·후보 선택 Case 의 02_tstar·03_bc·04_esl·05_val·06_export·07_report 가 같음.
B·C: tie_force 키 없는 스냅샷(옛 스터디)의 스터디 출력 전부(jig_grid.json·result.json·ranking.csv·사이드카·3D·report.html)가 같음.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_v0252_c1"))
import golden_tm as GT  # noqa: E402


@pytest.mark.parametrize("case", GT.CASES)
def test_v0252_golden_bytes(tmp_path, monkeypatch, case):
    gold = GT.load()
    exp = gold["cases"][case]
    got = GT.compute(case, str(tmp_path), monkeypatch)
    for k in gold["unstable"].get(case, []):
        got.pop(k, None)
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k]]
    assert not diff, diff
