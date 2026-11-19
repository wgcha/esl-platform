"""v0.24.1 V-0241-V3D-3 회귀 골든 — ``esl.view3d.build_view``·``pack_values`` 바이트가 v0.24.0(main 9d8b7168) 과 같음.

계약 esl_view3d_sources.md §3·§9 V-3: 고정 합성 입력의 part.glb·part_lod.glb·values.bin·manifest.json sha256 = 변경 전 기록값.
골든은 v0.24.1 코어 변경 **전**(계약 커밋 f29eeec0 = v0.24.0 코드)에 ``ESL_GOLDEN_RECORD=1`` 로 기록했다
(``tests/fixtures/view3d/golden_v0240.json``). created_at 은 고정값으로 넣어 manifest 전체 바이트를 비교한다(계약은 created_at 제외 —
더 강한 조건). 다시 기록하면 안 된다: 이 시험이 깨지면 build_view/pack_values 가 바뀐 것이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

from esl import view3d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from gen_view3d_fixture import synth_mesh  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "fixtures", "view3d", "golden_v0240.json")
CREATED_AT = "2026-11-19T00:00:00Z"
CASES = {
    # 이름: (메시 인자, cfg 덮어쓰기)
    "lod": ({"nx": 11, "ny": 7, "bend": 0.4, "tri_every": 7, "seed": 7},
            {"lod_min_nodes": 0, "lod_target_vertices": 40, "top_max": 100, "cluster_k_max": 5, "kmeans_max_iter": 50}),
    "plain": ({"nx": 14, "ny": 9, "bend": 0.25, "tri_every": 5, "seed": 11, "load_frac": 0.6},
              {"lod_min_nodes": 10 ** 9, "top_max": 30, "cluster_k_max": 4}),
}


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _mesh(name: str) -> dict:
    mk = CASES[name][0]
    return synth_mesh(mk["nx"], mk["ny"], **{k: v for k, v in mk.items() if k not in ("nx", "ny")})


def _build(td: str, name: str) -> dict[str, str]:
    cfg = CASES[name][1]
    m = _mesh(name)
    nid = m["node_id"]
    sup = [{"node_id": int(nid[0]), "dof": "123"}, {"node_id": int(nid[8]), "dof": "13"}, {"node_id": int(nid[20]), "dof": "3"}]
    out = os.path.join(td, name)
    view3d.build_view(out, node_id=nid, x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], f=m["f"], u_rel=m["u_rel"],
                      supports=sup, cfg=cfg, key=f"golden-{name}", esl_run_id="golden-run", created_at=CREATED_AT)
    return {f: _sha(os.path.join(out, f)) for f in sorted(os.listdir(out))}


def _pack(name: str) -> str:
    m = _mesh(name)
    rng = np.random.default_rng(5)
    n = m["node_id"].size
    b, arrays = view3d.pack_values(rng.random(n) * 3.0, rng.normal(size=n), rng.random(n) * 9.0, m["u_rel"])
    return hashlib.sha256(b + json.dumps(arrays, sort_keys=True).encode()).hexdigest()


def _current(tmp_path) -> dict:
    return {"build_view": {name: _build(str(tmp_path), name) for name in CASES},
            "pack_values": {name: _pack(name) for name in CASES}}


def test_build_view_bytes_equal_v0240_golden(tmp_path):
    cur = _current(tmp_path)
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not os.path.isfile(GOLDEN):
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump({"recorded_at_commit": "f29eeec0 (= v0.24.0 view3d code)", **cur}, fh, indent=1, sort_keys=True)
            fh.write("\n")
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)
    assert cur["build_view"] == gold["build_view"]
    assert cur["pack_values"] == gold["pack_values"]
    assert set(gold["build_view"]["lod"]) == {"manifest.json", "part.glb", "part_lod.glb", "values.bin"}
