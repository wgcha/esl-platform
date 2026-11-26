"""v0.24.9 PU 합성 세계(esl_bead_pos_u.md §5): 직선 채널 판(beadgraph synth_oneside.channel — 정렬 quad, 600×300, D 10·W 40·45°)을
새 ③ case_once 그래프 select 스터디로(기준 Case rad, 엔트리 2개, fixed-scan tie = 판 네 귀퉁이 근처 묶음, 지그 순위 새 스냅샷 기본).
U 변수 1개(+ D)를 켠 행렬 → BD_EVAL 전 안 → BD_POST. 시험이 읽는 함수: ``world`` · ``run_u``."""
from __future__ import annotations

import copy
import os

import numpy as np
import synth_doe as sd
from _bg_util import esl_mesh  # noqa: F401

from esl.doe import DEFAULTS
from esl.doe import stages as stg
from esl.library import _util as U


def channel_mesh(**kw) -> dict:
    from beadgraph.testing import synth_oneside as so
    c = so.channel(**kw)
    return esl_mesh({"x0": c["nodes"], "conn": c["conn"]})


def tie_groups(mesh, n_per=4):
    """네 귀퉁이(판 가장자리에서 30 mm 안) 근처 노드 묶음 — 채널·띠에서 멀리."""
    X = np.asarray(mesh["x0"])
    out = []
    for cx in (30.0, X[:, 0].max() - 30.0):
        for cy in (30.0, X[:, 1].max() - 30.0):
            d = np.hypot(X[:, 0] - cx, X[:, 1] - cy)
            out.append([int(i) for i in np.argsort(d, kind="stable")[:n_per]])
    return out


def rank_snap() -> dict:
    r = DEFAULTS["rank"]
    return {"metric": r["metric"], "lin_form": r["lin_form"], "lin_valid": float(r["lin_valid"]),
            "imbalance_warn": float(r["imbalance_warn"]), "schema": 2, "jig": copy.deepcopy(r["jig"]),
            "eval_region": {"mode": "part", "free_edge_mm": 10.0, "boxes": []}}


def pos_u_snap(**over) -> dict:
    return {"schema": 1, **DEFAULTS["pos_u"], **over}


def lf_snap(cell_mm=None) -> dict:
    return {"schema": 1, "cell_mm": float(DEFAULTS["load_follow"]["cell_mm"] if cell_mm is None else cell_mm)}


def world(tmp: str, *, mesh=None, extra: dict | None = None, rank=True, groups=None):
    mesh = channel_mesh() if mesh is None else mesh
    cd = os.path.join(tmp, "case", "input")
    os.makedirs(cd, exist_ok=True)
    rad = sd.write_mesh_rad(os.path.join(cd, "model.rad"), mesh)
    dirs = [sd.save_entry(os.path.join(tmp, "lib"), f"E{k}", mesh, kind, 1.0 + k, seed=k)[0]
            for k, kind in enumerate(("bend", "dent"))]
    doe = {"id": "PU", "scenario": "select", "select_schema": 2, "bead_source": "auto", "title": "t",
           "cfg": {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": cd},
           **({"rank": rank_snap()} if rank else {}), **(extra or {})}
    out = os.path.join(tmp, "_doe")
    gr = tie_groups(mesh) if groups is None else groups

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, lambda s: None)
    run("bd_input")
    sd.write_fixed(os.path.join(out, "prep", "fixed"), mesh, gr, kinds=("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"))
    run("bd_loads")
    auto = U.read_json(os.path.join(out, "prep", "select", "auto_selection.json"))
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": auto["selection"]}
    return doe, out, run, mesh


def params(out: str, doe: dict) -> dict:
    return U.read_json(os.path.join(out, "select", doe["selection"]["sha256"][:12], "params.json"))


def run_u(doe, out, run, *, rev=1, u=True, d=True, n=3, u_range=None, levels=None):
    """행렬(D·U 중 켠 것) → 전 안 BD_EVAL → BD_POST. 반환 (matrix, post result)."""
    run("bd_matrix", rev=rev, spec={"method": "lhs", "n": 2, "seed": 1, "params": [{"name": "B1_D", "lo": 8.0,
                                                                                      "hi": 12.0}]})
    rows = {p["name"]: p for p in params(out, doe)["params"]}
    ps = []
    if d:
        ps.append({"name": "B1_D", "lo": 8.0, "hi": 12.0})
    if u:
        lo, hi = u_range or rows["B1_U"]["default_range"]
        ps.append({"name": "B1_U", "lo": float(lo), "hi": float(hi)})
    spec = {"method": "fullfact", "levels": levels or 2, "params": ps} if levels else \
        {"method": "lhs", "n": n, "seed": 1, "params": ps}
    run("bd_matrix", rev=rev, spec=spec)
    m = U.read_json(os.path.join(out, "doe", str(rev), "matrix.json"))
    for x in m["designs"]:
        r = run("bd_eval", rev=rev, design=x["id"])
        assert r["status"] == "OK", r
    run("bd_post", rev=rev)
    return m, U.read_json(os.path.join(out, "post", "result.json"))
