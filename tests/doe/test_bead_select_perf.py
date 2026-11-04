"""V-BS-11 성능(perf 표지, 계약 esl_bead_select.md §5.8): 약 22만 노드 합성 판 — derive ≤ 3 s·≤ 1.5 GB, 기저 ≤ 30 s·≤ 2 GB,
안 모핑 ≤ 50 ms, 품질 ≤ 0.5 s, 썸네일 ≤ 1 s. CI 는 측정값 기록(초과 = 경고), 목표의 ``ESL_PERF_FAIL_X``(기본 5)배를 넘을
때만 실패 — 판정은 실기 체크리스트(V-BS-R1)."""
import os
import time
import tracemalloc
import warnings

import numpy as np
import pytest

import synth_bead as sb
from esl import view3d as v3
from esl.doe import bead_select as bs
from esl.doe import select_render as sr
from esl.doe import settings

CFG = settings({"bead_doe": {"enabled": True}})
FAIL_X = float(os.environ.get("ESL_PERF_FAIL_X", "5"))


def _measure(fn):
    """(결과, 시간 — tracemalloc 없이, 피크 MB — tracemalloc 로 한 번 더). tracemalloc 은 시간을 몇 배 늘리므로 따로 잰다."""
    t = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return out, dt, peak / 2 ** 20


def _check(name, dt, budget_s, mb=None, budget_mb=None, rows=None):
    msg = f"V-BS-11 {name}: {dt:.3f} s (목표 {budget_s} s)" + ("" if mb is None else f", 피크 {mb:.0f} MB (목표 {budget_mb} MB)")
    if rows is not None:
        rows.append(msg)
    if dt > budget_s or (mb is not None and mb > budget_mb):
        warnings.warn(msg + " — 이 환경 측정값(기록용)", stacklevel=2)
    assert dt <= FAIL_X * budget_s, msg
    if mb is not None:
        assert mb <= FAIL_X * budget_mb, msg


@pytest.mark.perf
def test_perf_220k():
    g = sb.generate(scale="big")
    m = g["mesh"]
    n = m["x0"].shape[0]
    assert 200_000 <= n <= 260_000, n
    norm = bs.normalize_input(sb.selection(g), CFG)
    rows = []
    ix = bs.mesh_index(m)                                   # 백엔드는 메시 sha 키로 캐시(§5.8)
    D, dt, mb = _measure(lambda: bs.derive_obj(m, norm, CFG, fixed_node_ids=g["fixed_ids"], index=ix))
    _check("derive", dt, 3.0, mb, 1536, rows)
    assert np.array_equal(D.bead("b1").slope_mask, g["label"] == "b1s")
    B, dt, mb = _measure(lambda: bs.basis(m, D, CFG))
    _check("기저", dt, 30.0, mb, 2048, rows)
    X0 = m["x0"]
    nom = B.nominal()
    vals = {"B1_D1": 24.0, "B1_W": nom["B1_W"] + 4.0, "B2_D1": 7.0}
    t = time.perf_counter()
    x = bs.morph(X0, B, vals)
    _check("안 모핑", time.perf_counter() - t, 0.05, rows=rows)
    t = time.perf_counter()
    st = bs.design_state(m, X0, x, D.fixed_mask, CFG)
    _check("품질", time.perf_counter() - t, 0.5, rows=rows)
    assert st["quality"]["n_affected"] > 0
    direction, has = bs.node_direction(B)
    tris = v3.triangulate(m["conn"], m["elem_type"])
    view = sr.view(X0, has, np.mean([b.n_hat for b in D.beads], axis=0), None, CFG["select"]["thumb"])
    t = time.perf_counter()
    png = sr.render(x, tris, sr.color_values(X0, x, direction, has), has, view, 5.0, CFG["select"]["thumb"])
    _check("썸네일", time.perf_counter() - t, 1.0, rows=rows)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    print("\n".join(rows))
