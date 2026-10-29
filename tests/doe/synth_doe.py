"""비드 DOE 코어 시험용 합성 도구: 판 메시·라이브러리 항목 폴더·가짜 paicad 출력(fixture JSON·npz·모핑 사본).

실제 paicad·gmsh 없이 코어 판정·해석 흐름을 시험한다(V-BD-16 실 paicad 는 ESL_TEST_PAICAD=1 레인).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "opt"))
import synth_opt as so  # noqa: E402

from esl.library import entry as en  # noqa: E402
from esl.library import normalize as nz  # noqa: E402
from esl.rad.writer import write_rad  # noqa: E402

PART_ID, PART_TITLE, PID, MID = 7, "chassis rear", 10, 1


def plate(**kw):
    kw.setdefault("nx", 12)
    kw.setdefault("ny", 8)
    return so.plate(**kw)


def conn_ids(mesh):
    nid = np.asarray(mesh["node_id"])
    c = np.asarray(mesh["conn"])
    ids = np.where(c >= 0, nid[np.maximum(c, 0)], 0)
    ids[np.asarray(mesh["elem_type"]).astype(int) == 3, 3] = 0
    return ids


def write_mesh_rad(path, mesh, x=None, title=PART_TITLE):
    t = np.asarray(mesh["thickness"], dtype=float)
    return write_rad(path, mesh["node_id"], mesh["x0"] if x is None else x, mesh["elem_id"], mesh["elem_type"],
                     conn_ids(mesh), PART_ID, title, PID, t, MID, float(mesh["E"][0]), float(mesh["nu"][0]))


def fake_entry(eid, mesh, kind="bend", amp=1.0, inch=75, seed=0):
    sup = so.supports_321(mesh)
    F = so.load(mesh, kind, amp, seed)
    return so.FakeEntry(eid, mesh, F, sup, inch=inch), sup


def save_entry(root, eid, mesh, kind="bend", amp=1.0, inch=75, seed=0):
    fe, sup = fake_entry(eid, mesh, kind, amp, inch, seed)
    raw = dict(fe.raw)
    n = raw["node_id"].size
    raw["is_bc"] = np.zeros(n, dtype=bool)
    raw["support_node_id"] = np.array([s for s, _ in sup], dtype=np.int64)
    raw["support_dof"] = np.array([d for _, d in sup])
    X = mesh["x0"]
    gs = nz.grid_summary(X, raw["f"], 24, 14, fe.meta["frame"], top_n=5, node_id=raw["node_id"])
    summary = {k: gs[k] for k in en.SUMMARY_KEYS if k in gs}
    meta = dict(fe.meta)
    meta["model"] = {"inch": inch, "part_id": PART_ID, "part_title": PART_TITLE, "max_ids": {}}
    d = os.path.join(root, eid)
    en.save(en.LibraryEntry(meta=meta, summary=summary, raw=raw), d)
    return d, fe


# ---------------------------------------------------------------- 가짜 paicad 출력
def bead_ids_and_centers(mesh, n_beads=2):
    """판 위 비드 중심(전역 좌표) — x 방향으로 고르게."""
    X = mesh["x0"]
    lo, hi = X.min(axis=0), X.max(axis=0)
    out = []
    for k in range(n_beads):
        cx = lo[0] + (k + 1) * (hi[0] - lo[0]) / (n_beads + 1)
        cz = 0.5 * (lo[2] + hi[2])
        out.append((f"B{k + 1}", k + 1, [float(cx), 0.0, float(cz)]))
    return out


def features_doc(mesh, n_beads=2, comp="CHASSIS_REAR", mirror=False, fixed_overlap_last=False):
    beads, feats, groups = [], [], []
    for bid, k, c in bead_ids_and_centers(mesh, n_beads):
        ov = "inside" if (fixed_overlap_last and k == n_beads) else "none"
        beads.append({"id": bid, "k": k, "body": "SHEET", "shape": "linear", "sense": "down", "center": c,
                      "axis": [0, 0, 1], "normal": [0, 1, 0], "core": [[c[0], 0.0, c[2] - 40.0], [c[0], 0.0, c[2] + 40.0]],
                      "nominal": {"depth": 4.0, "width": 12.0, "length": 80.0}, "fixed_overlap": ov,
                      "fixed_clearance_mm": None})
        for t, abbr, nom, fe in (("BEAD_DEPTH", "D", 4.0, (2.0, 6.5)), ("BEAD_POS_U", "U", 0.0, (-10.0, 10.0)),
                                 ("BEAD_POS_V", "V", 0.0, (-8.0, 8.0)), ("BEAD_WIDTH", "W", 12.0, (9.0, 16.0))):
            feats.append({"name": f"{comp}_BEAD_{abbr}_{k}", "type": t, "bead": bid, "body": "SHEET", "nominal": nom,
                          "unit": "mm", "range": {"min": fe[0], "max": fe[1], "ratio": 0.3},
                          "feasible": {"min": fe[0], "max": fe[1], "limited_by": "x", "source": "estimate"},
                          "group": None, "use_default": ov != "inside", "png": f"beads/{comp}_BEAD_{abbr}_{k}.png"})
    if mirror and n_beads >= 2:
        for abbr, t in (("D", "BEAD_DEPTH"), ("W", "BEAD_WIDTH")):
            mem = [f"{comp}_BEAD_{abbr}_1", f"{comp}_BEAD_{abbr}_2"]
            gid = f"G{len(groups) + 1}"
            groups.append({"id": gid, "type": t, "parameter": mem[0], "members": mem})
            for f in feats:
                if f["name"] in mem:
                    f["group"] = gid
    return {"schema_version": 1, "kind": "shell", "engine": "native", "engine_version": "0.14.0",
            "unit_system": "mm-ton-s", "parts": [{"body": "SHEET", "part_id": PART_ID, "title": PART_TITLE}],
            "beads": beads, "features": feats, "groups": groups, "warnings": [
                {"code": "BEAD_NEAR_FIXED", "bead": "B1", "message": "near"}]}


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def write_extract(d, doc):
    write_json(os.path.join(d, "shell_features.json"), doc)


def write_fixed(d, mesh, node_idx_groups, kinds=("RBE2",)):
    """fixed-scan 출력: 클러스터별 노드 인덱스 목록 → fixed_nodes.npz + shell_scan.json."""
    from esl.doe.paicad_io import FIXED_KINDS
    os.makedirs(d, exist_ok=True)
    nid, part, km, cl, xyz = [], [], [], [], []
    clusters = []
    for c, grp in enumerate(node_idx_groups):
        bit = FIXED_KINDS.index(kinds[c % len(kinds)])
        for i in grp:
            nid.append(int(mesh["node_id"][i]))
            part.append(PART_ID)
            km.append(1 << bit)
            cl.append(c)
            xyz.append(mesh["x0"][i])
        if grp:
            clusters.append({"id": c, "nodes": len(grp), "center": np.mean([mesh["x0"][i] for i in grp], axis=0).tolist(),
                             "kinds": [kinds[c % len(kinds)]]})
    np.savez(os.path.join(d, "fixed_nodes.npz"), node_id=np.array(nid, dtype=np.int64), part=np.array(part, np.int32),
             kind_mask=np.array(km, np.int16), cluster=np.array(cl, np.int32), xyz=np.array(xyz, float).reshape(-1, 3))
    write_json(os.path.join(d, "shell_scan.json"), {"schema_version": 1, "kind": "shell", "status": "OK", "code": None,
                                                    "fixed": {"total": len(nid), "clusters": clusters}, "warnings": []})


def write_grid(d, states: dict):
    """states = {cell id: (status, code)}."""
    cells = [{"id": k, "status": s, "code": c} for k, (s, c) in sorted(states.items())]
    write_json(os.path.join(d, "grid_manifest.json"), {"schema_version": 1, "kind": "shell", "cells": cells})


def morph_x(mesh, values, comp="CHASSIS_REAR"):
    """가짜 모핑: 비드 k 깊이 D_k 를 공칭 4 에서 바꾸면 그 비드 띠 노드를 면외(Y)로 (D_k − 4)·bump 이동."""
    X = np.array(mesh["x0"], dtype=float, copy=True)
    for bid, k, c in bead_ids_and_centers(mesh):
        D = float(values.get(f"{comp}_BEAD_D_{k}", 4.0))
        W = float(values.get(f"{comp}_BEAD_W_{k}", 12.0))
        r = np.abs(X[:, 0] - c[0])
        bump = np.exp(-(r / max(W, 1e-6)) ** 2) * (np.abs(X[:, 2] - c[2]) < 60.0)
        bump[bump < 1e-6] = 0.0
        X[:, 1] += (D - 4.0) * bump * 2.0
    return np.round(X, 9)


def write_run(design_dir, mesh, values, rel="model.rad", status="PASS", moved=None):
    """paicad shell run 출력(①②): check/shell_run.json, morph/shell_morph.json, out_files/<rel>."""
    pd = os.path.join(design_dir, "paicad")
    x = morph_x(mesh, values)
    n_moved = int(np.sum(np.linalg.norm(x - mesh["x0"], axis=1) > 0)) if moved is None else moved
    rels = []
    if status == "PASS":
        os.makedirs(os.path.join(pd, "out_files"), exist_ok=True)
        write_mesh_rad(os.path.join(pd, "out_files", rel), mesh, x)
        rels = [rel]
    write_json(os.path.join(pd, "morph", "shell_morph.json"), {"status": "OK", "kind": "shell", "files": [
        {"rel": rel, "moved_nodes": n_moved}]})
    write_json(os.path.join(pd, "check", "shell_run.json"), {"schema_version": 1, "kind": "shell", "status": status,
                                                             "code": None, "out_files": rels})
    os.makedirs(os.path.join(pd, "update"), exist_ok=True)
    with open(os.path.join(pd, "update", "sample.brep"), "w") as fh:
        fh.write("fake brep\n")
    return x
