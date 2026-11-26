"""V-0247-DM-9·23: 옛 스냅샷(depth_section 키 없음)·entry_fixed 명시 스냅샷의 select 준비·행렬 산출물과 패키지 D·W 기저가
main 1d71d983 골든(tests/doe/golden_v0247_c1/golden.json — main 코드로 기록, 다시 기록 금지)과 바이트 동일 — 패키지 1.2.0 설치 상태 — v0.24.9 부터 1.3.0(kind U 추가, 출력 판·D·W 기저 불변)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0247_c1"))
import golden as G  # noqa: E402


@pytest.mark.parametrize("case", sorted(G.CASES))
@pytest.mark.parametrize("ds", [None, "entry_fixed"])
def test_old_bytes(tmp_path, case, ds):
    gold = G.load()
    got = G.compute(case, str(tmp_path), {} if ds is None else {"depth_section": ds})
    exp = gold["cases"][case]
    for k in gold.get("dropped", {}).get(case, []):
        got.pop(k, None)
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k]]
    assert not diff, diff


@pytest.mark.slow
def test_package_bases_unchanged():
    import beadgraph as bg
    assert bg.__version__ == "1.3.0" and bg.OUTPUT_VERSION == "1.1.0" and bg.MORPH_RULES == 2
    gold = G.load()["package"]
    got = G.package_bases()
    assert got == gold
