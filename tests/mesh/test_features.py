"""V-SR-22 메시 공통 모듈 esl.mesh.features (계약 esl_select_relax.md §5B.2, SR-D-23).

- 이동 무변경: ``bead_select.MeshIndex is features.MeshIndex``, 재노출 이름, synth_bead 선택의 derive 요약·basis.npz·basis.bin·
  판정(v0.16.0 기대값 ``tests/fixtures/bead_select/v0160_golden.json`` — skip 정책) 바이트 동일.
- 섬·구멍 분류(``enclosed_components``·``free_edge_components``)·진단(``diagnose``) = synth_bead(features=True) 정답."""
import hashlib
import json
import os
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "doe"))

import synth_bead as sb  # noqa: E402
from esl.doe import bead_select as bs  # noqa: E402
from esl.doe import settings  # noqa: E402
from esl.mesh import features as ft  # noqa: E402

GOLD = json.load(open(os.path.join(HERE, "..", "fixtures", "bead_select", "v0160_golden.json"), encoding="utf-8"))
NEW_SUMMARY_KEYS = ("algo", "islands", "holes", "inner_loops_n", "hold_fixed", "hold", "range_feasible")   # §4.2 v0.16.1 칸(비교에서 뺌)
VARIANTS = {"h8": {"h": 8.0}, "h5open": {"h": 5.0, "open_end": True}, "h6wavy": {"h": 6.0, "wavy": True}}


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _strip(summ: dict) -> dict:
    s = {k: v for k, v in summ.items() if k not in NEW_SUMMARY_KEYS}
    s["beads"] = [{k: v for k, v in b.items() if k not in NEW_SUMMARY_KEYS} for b in summ["beads"]]
    return s


def golden_values(name: str, cfg: dict) -> dict:
    """golden 과 같은 절차(v0.16.0 트리에서 만든 값과 비교)."""
    g = sb.generate(**VARIANTS[name])
    m = g["mesh"]
    norm = bs.normalize_input(sb.selection(g), cfg)
    D = bs.derive_obj(m, norm, cfg, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(m, D, cfg)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "b.npz")
        bs.save_basis(p, B)
        bnpz = _h(open(p, "rb").read())
    tab = bs.params_table(D, cfg)
    rng = np.random.default_rng(1)
    states = []
    for _k in range(8):
        vals = {}
        for r in tab:
            lo, hi = r["default_range"]
            span = hi - lo
            vals[r["name"]] = float(lo - 0.6 * span + rng.random() * 2.2 * span)
        x = bs.morph(m["x0"], B, vals)
        st = bs.design_state(m, m["x0"], x, D.fixed_mask, cfg)
        states.append({"state": st["state"], "code": st["code"], "x": _h(np.ascontiguousarray(x).tobytes()),
                       "st": st})
    summ = _strip(D.summary())
    return {"summary": _h(json.dumps(summ, sort_keys=True, ensure_ascii=True, default=str).encode()), "basis_npz": bnpz,
            "basis_bin": _h(bs.basis_bin(B)), "norm_sha": bs.selection_sha256(norm), "states": states, "D": D, "g": g,
            "params": tab}


SKIP = settings({"bead_doe": {"enabled": True, "select": {"fixed_policy": "skip", "quality": {"fail_policy": "skip"}}}})


def test_moved_names_reexported():
    assert bs.MeshIndex is ft.MeshIndex and bs.mesh_index is ft.mesh_index
    assert bs._node_graph is ft.node_graph and bs._loops is ft.boundary_loops


@pytest.mark.parametrize("name", list(VARIANTS))
def test_v0160_bytes_skip_policy(name):
    """V-SR-1·22: features 없는 메시 → derive 요약(v0.16.1 칸 제외)·기저·판정(skip 정책)이 v0.16.0 과 같음.
    판정 순서 변경(SR-D-1, §5.7): v0.16.0 SKIPPED_FIXED 이면서 뒤집힘이 있던 안만 FAILED_MESH/SELECT_MORPH_INVERTED."""
    gv = golden_values(name, SKIP)
    gd = GOLD["bead_select"][name]
    for k in ("summary", "basis_npz", "basis_bin", "norm_sha"):
        assert gv[k] == gd[k], (name, k)
    for got, exp in zip(gv["states"], gd["states"]):
        assert got["x"] == exp["x"]
        if exp["state"] == "SKIPPED_FIXED" and exp["inverted"] > 0:
            assert (got["state"], got["code"]) == ("FAILED_MESH", "SELECT_MORPH_INVERTED")
        else:
            assert (got["state"], got["code"]) == (exp["state"], exp["code"])
        assert "warnings" not in got["st"] or not got["st"]["warnings"]


def test_boundary_loops_edge_nodes_meaning():
    """edge_nodes 없으면 v0.16.0 의미(자유 모서리 하나라도), 주면 그 노드에 닿는 자유 모서리만."""
    g = sb.generate(8.0, open_end=True)
    ix = ft.mesh_index(g["mesh"])
    BM = np.isin(g["label"], ["b1t1", "b1t2", "b1s"])
    lp0, free0 = ft.boundary_loops(ix, BM)
    lp1, free1 = ft.boundary_loops(ix, BM, edge_nodes=np.zeros(0, np.int64))
    assert free0 and not free1
    assert [x["nodes"].tolist() for x in lp0] == [x["nodes"].tolist() for x in lp1]
