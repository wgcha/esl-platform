"""V-0250-VB-2·5·7·9·14(하위 호환): 가상 비드 없는 선택(옛 스냅샷·블록 있는 새 스냅샷 + 가상 비드 0) 전 산출물·input_sha256·
range guard 표(준비·선택·params guard)·정규화 sha·morph·basis 바이트가 b1e52fad 골든(tests/doe/golden_v0250_c1/golden.json —
코드 변경 전 기록, 다시 기록 금지)과 같음."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0250_c1"))
import golden_vb as G  # noqa: E402


# v0.25.1(계약 esl_view3d_scene_legend.md V-0251-10 개정·§5.9 INT): 새로 만든 report.html 은 색·범례 문구만 바뀜 — 바이트 비교에서 뺌
# (파일 목록에는 그대로 있어야 함, 색 외 내용 = V-0251-43·44). 다른 파일 바이트 비교는 그대로.
PICTURE_V0251 = ("report.html",)


def _cmp(exp, got, unstable):
    exp = {k: v for k, v in exp.items() if k not in unstable}
    got = {k: v for k, v in got.items() if k not in unstable}
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k] and not k.endswith(PICTURE_V0251)]
    assert not diff, diff


def _vb_block():
    from esl.doe import DEFAULTS
    from esl.morph import virtual_bead as vbm
    vc = DEFAULTS["virtual_bead"]
    return {"virtual_bead": {"schema": 1, **{k: vc[k] for k in vbm.HASH_KEYS}}}


@pytest.mark.parametrize("case", G.CASES)
@pytest.mark.parametrize("block", [False, True], ids=["old", "vb_block"])
def test_no_virtual_beads_bytes(tmp_path, monkeypatch, case, block):
    """V-0250-VB-14: virtual_beads 없는 선택 — 옛 스냅샷·블록 있는 새 스냅샷 모두 골든 바이트."""
    gold = G.load()
    got = G.compute(case, str(tmp_path), monkeypatch, _vb_block() if block else None)
    _cmp(gold["cases"][case], got, gold["unstable"].get(case, []))


@pytest.mark.slow
def test_guard_tables_unchanged():
    """V-0250-VB-9: 기존 D·W 범위 판정 표(준비 range_guard 표·선택 guard_selection 문서·params guard) = 골든(한쪽 보정 무영향)."""
    assert G.guard_docs() == G.load()["guard"]


def test_selection_sha_unchanged():
    """V-0250-VB-5: 키 없음 → 정규화 JSON·sha = 골든(H5·H6·stepboss schema 2, synth_bead schema 1)."""
    assert G.select_shas() == G.load()["select"]


def test_morph_basis_bytes_unchanged():
    """V-0250-VB-2·7: linear 항 morph(basis_term 경유) 결과·basis.npz·basis.bin·basis.json 바이트 = 골든."""
    assert G.morph_shas() == G.load()["morph"]


def test_golden_recorded_before_code_change():
    assert "b1e52fad" in G.load()["made_by"]
