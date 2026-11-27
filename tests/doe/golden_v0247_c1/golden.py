"""V-0247-DM-9·23 골든(main 1d71d983 코드로 기록 — 다시 기록 금지). 옛 스냅샷(depth_section 키 없음)·entry_fixed 명시 스냅샷의
select 준비·행렬 산출물 바이트, 패키지 D·W 기저 바이트(H5·H6·stepboss 전 세그먼트).

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0247_c1/golden.py (main 코드에서만).
JSON 파일은 시간 키(seconds*·elapsed*)를 뺀 정규 바이트의 sha256, 그 밖은 원 바이트 sha256."""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
DOE_T = os.path.dirname(HERE)
if DOE_T not in sys.path:
    sys.path.insert(0, DOE_T)

VOLATILE = ("seconds", "elapsed", "created_at", "time_s")


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if not any(str(k).startswith(p) for p in VOLATILE)}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def file_sha(p: str) -> str:
    b = open(p, "rb").read()
    if p.endswith(".json"):
        try:
            b = json.dumps(_strip(json.loads(b)), sort_keys=True, ensure_ascii=True).encode()
        except ValueError:
            pass
    return hashlib.sha256(b).hexdigest()


def tree_sha(root: str, skip=("loads.npz", "/lib/", "/case/")) -> dict:
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if fn.endswith((".log", ".lock")) or fn.startswith(".") or "post/view3d_scene/" in rel or \
                    rel.endswith("post/scene_view.json"):          # v0.25.1 새 파일(옛 골든 비교 밖 — V-0251-10 이 확인)
                continue
            out[rel] = file_sha(p)
    return dict(sorted(out.items()))


def _study(tmp, mesh, sid, **extra):
    import synth_doe as sd
    cd = os.path.join(tmp, "case", "input")
    os.makedirs(cd, exist_ok=True)
    rad = sd.write_mesh_rad(os.path.join(cd, "model.rad"), mesh)
    dirs = [sd.save_entry(os.path.join(tmp, "lib"), "E0", mesh, "bend", 1.0, seed=0)[0]]
    return {"id": sid, "scenario": "select", "title": "t",
            "cfg": {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}},
            "entries": [{"id": "E0", "dir": dirs[0]}],
            "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": "CASE"}, **extra}


def _runner(tmp, doe):
    from esl.doe import stages as stg
    out = os.path.join(tmp, "_doe", doe["id"])

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, lambda s: None)
    return out, run


def graph_case(tmp: str, extra: dict) -> dict:
    """H5 그래프 스터디(schema 2, auto): bd_input → bd_loads → bd_matrix(D·W 변수)."""
    from _bg_util import cf, esl_mesh
    mesh = esl_mesh(cf.load_fixture("h5"))
    doe = _study(tmp, mesh, "G1", select_schema=2, bead_source="auto", **extra)
    doe["base"]["case_dir"] = os.path.join(tmp, "case", "input")
    out, run = _runner(tmp, doe)
    run("bd_input")
    run("bd_loads")
    auto = json.loads(open(os.path.join(out, "prep", "select", "auto_selection.json"), encoding="utf-8").read())
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": auto["selection"]}
    sdir = os.path.join(out, "select", auto["sha256"][:12])
    # 1st matrix: D only (derive writes params.json — pick the W rows from it for the 2nd)
    run("bd_matrix", rev=1, spec={"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 6.0, "hi": 10.0}]})
    rows = json.loads(open(os.path.join(sdir, "params.json"), encoding="utf-8").read())["params"]
    ps = [{"name": r["name"], "lo": r["default_range"][0], "hi": r["default_range"][1]} for r in rows if r.get("use_default")][:6]
    run("bd_matrix", rev=2, spec={"method": "lhs", "n": 4, "seed": 3, "params": ps})
    return tree_sha(out)


def elems_case(tmp: str, extra: dict) -> dict:
    import synth_bead as sb

    from esl.doe import bead_select as bs
    from esl.doe import settings
    cfg = settings({"bead_doe": {"enabled": True}})
    g = sb.generate()
    sel_in = sb.selection(g)
    sha = bs.selection_sha256(bs.normalize_input(sel_in, cfg))
    doe = _study(tmp, g["mesh"], "S7", **extra)
    doe["base"]["case_dir"] = os.path.join(tmp, "case", "input")
    doe["selection"] = {"rev": 1, "sha256": sha, "input": sel_in}
    out, run = _runner(tmp, doe)
    run("bd_input")
    run("bd_loads")
    run("bd_matrix", rev=1, spec={"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D1", "lo": 18.0, "hi": 26.0}]})
    rows = json.loads(open(os.path.join(out, "select", sha[:12], "params.json"), encoding="utf-8").read())["params"]
    ps = [{"name": r["name"], "lo": r["default_range"][0], "hi": r["default_range"][1]} for r in rows if r.get("use_default")][:6]
    run("bd_matrix", rev=2, spec={"method": "lhs", "n": 4, "seed": 3, "params": ps})
    return tree_sha(out)


def _bsha(B) -> str:
    h = hashlib.sha256()
    for b in B:
        h.update(b["name"].encode())
        h.update(np.float64(b["nominal"]).tobytes())
        h.update(np.ascontiguousarray(b["idx"], "<i8").tobytes())
        h.update(np.ascontiguousarray(b["vec"], "<f8").tobytes())
        h.update(np.ascontiguousarray(b["zone"], "<i8").tobytes())
    return h.hexdigest()


def package_bases(names=("h5", "stepboss", "h6")) -> dict:
    from beadgraph import basis
    from beadgraph.testing import conformance as cf
    out = {}
    for nm in names:
        g, lab, _ = cf.classified(nm)
        fx = cf.load_fixture(nm)
        X, C, F = fx["x0"], fx["conn"], fx["fixed"]
        for s in g["segments"]:
            if s["type"] == "base":
                continue
            for kind in ("D", "W"):
                if kind == "W" and s.get("entry_width") is None:
                    continue
                bl = [{"name": "v", "kind": kind, "segs": [s["id"]], "zones": [], "hold": 1}]
                B = basis(g, lab, X, bl, None, fixed=F, elems=C)
                out[f"{nm}/s{s['id']}/{kind}"] = _bsha(B)
        for n in g["networks"]:
            bl = [{"name": "n", "kind": "D", "segs": n["segments"], "zones": n["junction_zones"], "hold": 1}]
            out[f"{nm}/net{n['id']}/D"] = _bsha(basis(g, lab, X, bl, None, fixed=F, elems=C))
    return out


CASES = {
    "graph_legacy": (graph_case, {}),
    "graph_rules": (graph_case, {"shape_rules": {"schema": 1}}),
    "elems_legacy": (elems_case, {}),
    "elems_rules": (elems_case, {"shape_rules": {"schema": 1}}),
}


def compute(case: str, tmp: str, extra_doe: dict | None = None) -> dict:
    fn, extra = CASES[case]
    return fn(tmp, {**extra, **(extra_doe or {})})


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    import tempfile
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        sys.exit("set ESL_GOLDEN_RECORD=1 (main code only)")
    root = os.path.dirname(os.path.dirname(DOE_T))
    sys.path.insert(0, root)
    rec = {"recorded_from": sys.argv[1] if len(sys.argv) > 1 else "main", "cases": {}}
    for c in CASES:
        with tempfile.TemporaryDirectory() as td:
            rec["cases"][c] = compute(c, td)
        with tempfile.TemporaryDirectory() as td:
            again = compute(c, td)
        diff = [k for k in rec["cases"][c] if again.get(k) != rec["cases"][c][k]]
        if diff:
            print(c, "NONDETERMINISTIC", diff)
            for k in diff:
                rec["cases"][c].pop(k)
            rec.setdefault("dropped", {})[c] = diff
        print(c, len(rec["cases"][c]), "files")
    rec["package"] = package_bases()
    print("package", len(rec["package"]))
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
