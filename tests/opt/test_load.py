"""V-OR-3: S1 직접 적용(노드 순서 다른 같은 모델 → 노드별 정확 일치, 매핑 미호출), S2 셀 매핑(셀 합력·합모멘트 보존)."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.library import mapping as mp
from esl.opt import target as tg


def test_s1_direct_nodal_exact_and_no_mapping(monkeypatch):
    m = so.plate(10, 6)
    sup = so.supports_321(m)
    F = so.load(m, "rand", seed=3)
    e = so.FakeEntry("E1", m, F, sup)
    # 대상 = 같은 모델, 노드 순서 뒤집음
    p = np.arange(m["node_id"].size)[::-1]
    inv = np.argsort(p)
    tm = {**m, "node_id": m["node_id"][p], "x0": m["x0"][p], "conn": np.where(m["conn"] >= 0, inv[m["conn"]], -1)}
    t = tg.Target("S1", tm, e.meta["frame"], sup)

    def boom(*a, **k):
        raise AssertionError("S1 은 매핑을 쓰지 않음")

    monkeypatch.setattr(mp, "to_target", boom)
    f, info = tg.entry_load(t, e.raw)
    assert info["method"] == "direct_nodal"
    assert np.array_equal(f, F[p])                        # 노드별 정확 일치(비트 동일)
    bad = {**e.raw, "node_id": e.raw["node_id"] + 1}
    with pytest.raises(EslError) as ei:
        tg.entry_load(t, bad)
    assert ei.value.code == "MODEL_MISMATCH"


def test_s2_cell_mapping_conserves_cell_resultants():
    src = so.plate(24, 14, Lx=480, Lz=280)
    e = so.FakeEntry("E1", src, so.load(src, "rand", seed=5), so.supports_321(src))
    tmpl = so.plate(37, 23, Lx=485, Lz=283, n_tria_cols=3)     # 다른 메시·약간 다른 크기
    arrays, meta = tg.build_template(tmpl)
    t = tg.template_target(arrays, meta)
    f, info = tg.entry_load(t, None, e.summary_for_mapping())
    assert info["method"] == "cell_mapping"
    assert info["conservation_rel_max"] <= 1e-9
    assert info["equilibrium_after"]["force_rel"] < 1e-9 and info["equilibrium_after"]["moment_rel"] < 1e-9
    # 셀(병합 그룹) 보존은 mapping 이 대상 메시에서 다시 계산한 값(conservation_rel_max) — 전체 합력도 보존
    f0, _ = mp.to_target(e.summary_for_mapping(), t.mesh["x0"], t.frame, {"equilibrate": False})
    sF = e.summary["cell_F"].reshape(-1, 3).sum(axis=0)
    scale = np.abs(e.raw["f"]).sum()
    R = np.array([t.frame["e_xi"], t.frame["e_eta"], t.frame["n"]])
    Rs = np.array([e.meta["frame"]["e_xi"], e.meta["frame"]["e_eta"], e.meta["frame"]["n"]])
    assert np.allclose(R @ f0.sum(axis=0), Rs @ sF, atol=1e-9 * scale)
    with pytest.raises(EslError):
        tg.entry_load(t, None, None)


def test_template_normals_aligned():
    m = so.plate(6, 4)
    c = m["conn"].copy()
    c[:5] = c[:5][:, [0, 3, 2, 1]]
    arrays, meta = tg.build_template({**m, "conn": c})
    assert meta["normals"]["normals_flipped"] == 5
    assert not tg.opposite_mask(arrays, meta["frame"]["n"]).any()
