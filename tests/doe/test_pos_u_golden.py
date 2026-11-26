"""V-0249-PU-9·13·15(하위 호환): `pos_u` 없는 스냅샷(그래프 select case_once·step_once + 지그 순위) 전 산출물·input_sha256 과 패키지
graph.json·D·W·DF·W1 기저가 3609c921 골든(tests/doe/golden_v0249_c1/golden.json — 코드 변경 전 기록, 다시 기록 금지)과 바이트 동일.
`pos_u` 블록이 있어도 U 변수 0개면 계산 경로 = node — params.json(U 행·u_reason)·derived 요약 외 산출물 = 골든."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0249_c1"))
import golden_pu as G  # noqa: E402

# pos_u 블록이 있는 스냅샷에서 바뀌어도 되는 파일(계약 §3 — params.json 의 U 행·u_reason 과 그것을 담는 선택 요약)
POS_U_CHANGED = ("params.json", "derived.json", "prep/input.json")


def _cmp(exp, got, unstable, allow=()):
    for k in unstable:
        got.pop(k, None)
        exp = {kk: v for kk, v in exp.items() if kk != k}
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k] and not any(k.endswith(a) for a in allow)]
    assert not diff, diff


@pytest.mark.parametrize("case", sorted(G.CASES))
def test_old_snapshot_bytes(tmp_path, monkeypatch, case):
    gold = G.load()
    got = G.compute(case, str(tmp_path), monkeypatch)
    _cmp(gold["cases"][case], got, gold["unstable"].get(case, []))


@pytest.mark.parametrize("case", sorted(G.CASES))
def test_pos_u_block_without_u_vars_is_node_path(tmp_path, monkeypatch, case):
    from esl.doe import DEFAULTS
    pu = {"schema": 1, **DEFAULTS["pos_u"]}
    lf = {"schema": 1, "cell_mm": float(DEFAULTS["load_follow"]["cell_mm"])}
    gold = G.load()
    got = G.compute(case, str(tmp_path), monkeypatch, extra={"pos_u": pu, "load_follow": lf})
    _cmp(gold["cases"][case], got, gold["unstable"].get(case, []), allow=POS_U_CHANGED)
    assert not any(k.endswith("load_follow.json") for k in got)


@pytest.mark.slow
def test_package_bases_unchanged():
    import beadgraph as bg
    assert bg.OUTPUT_VERSION == "1.1.0" and bg.MORPH_RULES == 2 and bg.RULES == 1
    assert bg.DF_RULES == 1 and bg.W1_RULES == 1
    gold = G.load()["package"]
    assert G.package_bases() == gold


def test_golden_recorded_before_code_change():
    gold = G.load()
    assert "3609c921" in gold["made_by"]
    assert json.dumps(gold["package"])                      # 패키지 항목 있음
