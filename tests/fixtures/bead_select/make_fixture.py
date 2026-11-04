"""비드 직접 선택 프런트 시험용 고정 픽스처 생성(계약 esl_bead_select.md §8.1·§9, V-BS-FMT).

코어가 실제로 쓰는 함수로 만든다 — ``bead_select.view_files``(select.bin + bin.layout), ``basis_bin``·``basis_meta``(basis.bin·basis.json).
합성 메시 = ``tests/doe/synth_bead.generate(h=8)``: n_elems 3925·n_nodes 4029(둘 다 4의 배수가 아님 → 섹션 채움 시험).

다시 만들기(저장소 루트에서): ``python tests/fixtures/bead_select/make_fixture.py``
출력: select.bin · select_manifest.json(bin 항목 + n_*) · basis.bin · basis.json · expected.json(프런트 대조값)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests", "doe")]

import synth_bead as sb  # noqa: E402
from esl.doe import bead_select as bs  # noqa: E402
from esl.doe import settings  # noqa: E402

H_MM = 8.0


def main() -> None:
    cfg = settings({"bead_doe": {"enabled": True}})
    g = sb.generate(H_MM)
    m = g["mesh"]
    nid = np.asarray(m["node_id"], dtype=np.int64)
    fixed = np.isin(nid, np.asarray(g["fixed_ids"], dtype=np.int64))
    blob, lay = bs.view_files(m, fixed)
    n_elems, n_nodes = int(len(m["elem_id"])), int(nid.size)
    assert n_elems % 4 and n_nodes % 4, "채움 시험용 — n_elems·n_nodes 가 4의 배수가 아니어야 함"
    man = {"schema": "esl/bead_select_view/1", "n_nodes": n_nodes, "n_elems": n_elems, "n_tris": lay["n_tris"],
           "bin": {"name": "select.bin", "bytes": len(blob), "layout": lay["layout"]}}
    D = bs.derive_obj(m, bs.normalize_input(sb.selection(g), cfg), cfg, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(m, D, cfg)
    bb = bs.basis_bin(B)
    meta = bs.basis_meta(B, None)
    meta["sha256"] = hashlib.sha256(bb).hexdigest()
    et = np.asarray(m["elem_type"]).astype(int)
    tri2elem = np.repeat(np.arange(n_elems), 1 + (et == 4).astype(np.int64))
    vals = {v["name"]: float(v["nominal"]) + (1.5 if v["type"] == "D" else -2.0) for v in B.vars}
    u = bs.morph(np.asarray(m["x0"], dtype=np.float64), B, vals) - np.asarray(m["x0"], dtype=np.float64)
    beads = sorted({str(v["bead"]) for v in B.vars})
    n_hat = {b: [float(x) for x in next(v["n_hat"] for v in B.vars if v["bead"] == b)] for b in beads}
    exp = {"h_mm": H_MM, "elem_id_first": int(m["elem_id"][0]), "elem_id_last": int(m["elem_id"][-1]),
           "elem_id_sum": int(np.asarray(m["elem_id"], dtype=np.int64).sum()), "n_sh3n": int((et == 3).sum()),
           "fixed_n": int(fixed.sum()), "tri2elem_last": int(tri2elem[-1]), "values": vals,
           "u_max_abs": float(np.abs(u).max()), "u_sum": [float(x) for x in u.sum(axis=0)], "n_hat": n_hat}
    files = {"select.bin": blob, "basis.bin": bb}
    for name, b in files.items():
        with open(os.path.join(HERE, name), "wb") as fh:
            fh.write(b)
    for name, d in (("select_manifest.json", man), ("basis.json", meta), ("expected.json", exp)):
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    print(f"select.bin {len(blob)} B · basis.bin {len(bb)} B · vars {[v['name'] for v in B.vars]}")


if __name__ == "__main__":
    main()
