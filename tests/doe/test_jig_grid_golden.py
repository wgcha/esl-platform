"""V-0248-JG-11(하위 호환): 옛 스냅샷(rank.jig_grid 없음)의 ④ 형상 직접 비교·옛 ③ 산출물(result.json·ranking.csv·per_esl.json·
designs.json·report.html·안 result.json·done.json input_sha256·prep 전부)이 v0.24.7 머지 헤드 골든(tests/doe/golden_v0248_c1/golden.json —
코드 변경 전에 기록, 다시 기록 금지)과 바이트 동일."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0248_c1"))
import golden_jg as G  # noqa: E402


# v0.25.1(계약 esl_view3d_scene_legend.md V-0251-10 개정·§5.9 INT): 새로 만든 report.html 은 색·범례 문구만 바뀜 — 바이트 비교에서 뺌
# (파일 목록에는 그대로 있어야 함, 색 외 내용 = V-0251-43·44). 다른 파일 바이트 비교는 그대로.
PICTURE_V0251 = ("report.html",)


@pytest.mark.parametrize("case", G.CASES)
def test_old_snapshot_bytes(tmp_path, monkeypatch, case):
    gold = G.load()
    exp = gold["cases"][case]
    got = G.compute(case, str(tmp_path), monkeypatch)
    for k in gold.get("unstable", {}).get(case, []):
        got.pop(k, None)
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k] and not k.endswith(PICTURE_V0251)]
    assert not diff, diff
