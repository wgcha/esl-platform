"""V-0250-VB-18 비용(계약 esl_virtual_bead.md §13·§12-18): 합성 120×80(h 1 — 9,801 노드) 가상 비드 1·4개 — derive 추가 시간·기저
추가 시간·guard 추가 평가 수·안 1개 morph 추가 시간·basis.npz 크기 증가. 목표 = §13 추정(10만 노드 판 기준 derive 20~60 ms·
기저 30~80 ms·guard 0.1~0.5 s·morph < 1 ms)의 이 크기 비례 이내 — 시험은 넉넉한 상한(느린 CI 2배 여유)만 걸고 값은 출력."""
import os
import tempfile
import time

import numpy as np
import pytest
import synth_guard as sg
import synth_vbead as sv
from _bg_util import CFG, bgr, bs

from esl.doe import DEFAULTS
from esl.morph import virtual_bead as vbm

pytestmark = pytest.mark.slow

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}


def _world():
    m = sv.uniform(1.0, (120.0, 80.0))
    d = tempfile.mkdtemp(prefix="vb_cost_")
    st = bgr.prep_graph(m, [], CFG, d)
    assert st["ok"]
    g, lab = bgr.load_graph(d)
    return m, g, lab


def _vbs(n):
    ys = (14.0, 30.0, 46.0, 62.0)[:n]
    return [{"id": f"a{i + 1}", "p0": [20.0, y, 0.0], "p1": [100.0, y, 0.0], "w_top": 4.0, "d_max": 2.0}   # r 생략 = h(1)
            for i, y in enumerate(ys)]


def test_cost_v18(capsys):
    m, g, lab = _world()
    assert m["x0"].shape[0] == 9801
    ru = sg.rules()
    rec = {}
    base = None
    for n in (0, 1, 4):
        s = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}},
             "beads": [], "ties": [], "virtual_beads": _vbs(n)}
        if n == 0:
            continue
        norm, _ = bgr.normalize_v2(s, g, CFG, labels=lab, mesh=m)
        t0 = time.perf_counter()
        D = bgr.derive_obj_v2(m, norm, CFG, g, lab, shape_rules=ru, virtual_bead=BLK)
        t_der = time.perf_counter() - t0
        assert all(v.ok for v in D.vbeads), [v.reasons for v in D.vbeads]
        t0 = time.perf_counter()
        B = bs.basis(m, D, CFG)
        t_bas = time.perf_counter() - t0
        p = os.path.join(tempfile.mkdtemp(), "basis.npz")
        bs.save_basis(p, B)
        t0 = time.perf_counter()
        doc = bgr.guard_selection(m, D, B, CFG, only=[v["name"] for v in B.vars])
        t_g = time.perf_counter() - t0
        x0 = np.asarray(m["x0"])
        vals = {v["name"]: 1.0 for v in B.vars}
        t0 = time.perf_counter()
        for _ in range(10):
            bs.morph(x0, B, vals)
        t_m = (time.perf_counter() - t0) / 10
        rec[n] = {"derive_s": round(t_der, 4), "basis_s": round(t_bas, 4), "guard_s": round(t_g, 3),
                  "guard_evals": doc["budget"]["evals"], "morph_ms": round(t_m * 1e3, 3), "npz_kb": round(os.path.getsize(p) / 1024, 1),
                  "n_fp": [v.diag["n_fp"] for v in D.vbeads]}
        assert t_der < 4.0 * n and t_bas < 2.0 * n and t_m < 0.05
    with capsys.disabled():
        print("\nV-0250-VB-18", rec)
    _ = base
