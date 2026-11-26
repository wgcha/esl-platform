"""V-0250-VB-2·5·7·9·14 골든(release/v0.25.0 b1e52fad = release/v0.24.9 C1 ab5e46f3 + v0.25.0 계약, 코드 변경 전에 기록 —
다시 기록 금지).

- cases: 가상 비드 없는 select 스터디 전 산출물(prep·select·doe·run·post·view3d)
  · g247_graph_rules: H5 그래프 스터디 + shape_rules(range guard 켬 — 준비·선택 range_guard.json·params guard)
  · sel_case_jig / sel_step_jig: v0.24.9 골든 세계(지그 순위, case_once·step_once)
  · sel_step_jig_pu: 같은 step_once + pos_u·load_follow 블록(v0.24.9 U 스터디)
- guard: H5·H6 준비 range_guard 표(``range_guard_table``) 정규 바이트, H6 자동 seed 의 선택 점검(``guard_selection``) 문서·
  params 행(guard 포함), 합성 포켓(synth_guard) 선택 점검 문서 — 기존 D·W 범위 판정 표(V-0250-VB-9).
- select: 정규화 sha(H5·H6 자동 seed schema 2, synth_bead schema 1) — V-0250-VB-5.
- morph: H5·H6 자동 seed 선택 기저 ``bead_select.morph`` 결과(기본 범위 끝 값) sha, basis.npz·basis.bin·basis.json 바이트 —
  V-0250-VB-2·7(linear 경로 바이트 동일).

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0250_c1/golden_vb.py (b1e52fad 코드에서만)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
DOE_T = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(DOE_T))
for p in (DOE_T, os.path.join(DOE_T, "golden_v0249_c1"), os.path.join(DOE_T, "golden_v0247_c1"),
          os.path.join(ROOT, "packages", "beadgraph", "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _js(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=True, default=float).encode()).hexdigest()


# ---------------------------------------------------------------- 스터디 세계
def _g247(tmp, mp, extra=None):
    import golden as G7
    from golden_pu import tree_sha
    G7.graph_case(tmp, {"shape_rules": {"schema": 1}, **(extra or {})})
    out = os.path.join(tmp, "_doe", "G1")
    return out


def _pu_blocks():
    from esl.doe import DEFAULTS
    return {"pos_u": {"schema": 1, **DEFAULTS["pos_u"]},
            "load_follow": {"schema": 1, "cell_mm": float(DEFAULTS["load_follow"]["cell_mm"])}}


def _case(name):
    import golden_pu as GP

    def run(tmp, mp, extra=None):
        if name == "g247_graph_rules":
            return _g247(tmp, mp, extra)
        if name == "sel_case_jig":
            return GP.sel_case_jig(tmp, mp, extra)[1]
        if name == "sel_step_jig":
            return GP.sel_step_jig(tmp, mp, extra)[1]
        if name == "sel_step_jig_pu":
            return GP.sel_step_jig(tmp, mp, {**_pu_blocks(), **(extra or {})})[1]
        raise KeyError(name)
    return run


CASES = ("g247_graph_rules", "sel_case_jig", "sel_step_jig", "sel_step_jig_pu")


def compute(case: str, tmp: str, mp, extra: dict | None = None) -> dict:
    from golden_pu import tree_sha
    out = _case(case)(tmp, mp, extra)
    return tree_sha(out, tmp)


# ---------------------------------------------------------------- 표·선택·모핑
def guard_docs() -> dict:
    import synth_guard as sg
    from _bg_util import CFG, bgr, bs, prepared
    ru = sg.rules()
    out = {}
    for nm in ("h5", "h6"):
        mesh, g, lab, fx, _d = prepared(nm)
        doc = bgr.range_guard_table(mesh, g, lab, fx, CFG, ru)
        blob = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        out[f"{nm}/prep"] = hashlib.sha256(blob).hexdigest()
        sel, _s, _w = bgr.auto_seed(g, lab, CFG)
        norm, _sha = bgr.normalize_v2(sel, g, CFG, labels=lab, mesh=mesh, shape_rules=ru)
        D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, shape_rules=ru, range_guard=doc)
        out[f"{nm}/derive_params"] = _js(bgr.params_rows_v2(D, CFG))
        B = bs.basis(mesh, D, CFG)
        sd = bgr.guard_selection(mesh, D, B, CFG, only=[v["name"] for v in B.vars])
        out[f"{nm}/selection"] = _js(sd)
        out[f"{nm}/selection_params"] = _js(bgr.params_rows_v2(D, CFG))
        out[f"{nm}/warnings"] = _js([[b.id, b.warnings] for b in D.beads] + [D.warnings])
    return out


def select_shas() -> dict:
    import synth_bead as sb
    from _bg_util import CFG, bgr, bs, prepared
    out = {}
    for nm in ("h5", "h6", "stepboss"):
        mesh, g, lab, _fx, _d = prepared(nm)
        sel, _s, _w = bgr.auto_seed(g, lab, CFG)
        norm, sha = bgr.normalize_v2(sel, g, CFG, labels=lab, mesh=mesh)
        out[f"{nm}/schema2"] = sha
        out[f"{nm}/schema2_json"] = hashlib.sha256(bs.canonical_json(norm).encode()
                                                   if isinstance(bs.canonical_json(norm), str)
                                                   else bs.canonical_json(norm)).hexdigest()
    gsb = sb.generate()
    out["synth_bead/schema1"] = bs.selection_sha256(bs.normalize_input(sb.selection(gsb), CFG))
    return out


def morph_shas() -> dict:
    from _bg_util import CFG, bgr, bs, prepared
    out = {}
    for nm in ("h5", "h6"):
        mesh, g, lab, fx, _d = prepared(nm)
        sel, _s, _w = bgr.auto_seed(g, lab, CFG)
        norm, _sha = bgr.normalize_v2(sel, g, CFG, labels=lab, mesh=mesh)
        D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx)
        B = bs.basis(mesh, D, CFG)
        rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
        x0 = np.asarray(mesh["x0"], np.float64)
        for k, pick in enumerate((0, 1)):
            vals = {n: float(r["default_range"][pick]) for n, r in rows.items()}
            x = bs.morph(x0, B, vals)
            out[f"{nm}/morph{k}"] = hashlib.sha256(np.ascontiguousarray(x, "<f8").tobytes()).hexdigest()
        td = tempfile.mkdtemp(prefix=f"g0250_{nm}_")
        p = os.path.join(td, "basis.npz")
        bs.save_basis(p, B)
        out[f"{nm}/basis.npz"] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        out[f"{nm}/basis.bin"] = hashlib.sha256(bs.basis_bin(B)).hexdigest()
        out[f"{nm}/basis.json"] = _js(bs.basis_meta(B, "x"))
        lb = bs.load_basis(p)
        out[f"{nm}/load_morph"] = hashlib.sha256(np.ascontiguousarray(
            bs.morph(x0, lb, {n: float(r["default_range"][1]) for n, r in rows.items()}), "<f8").tobytes()).hexdigest()
    return out


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _record():
    import shutil

    import pytest
    got, unstable = {}, {}
    for case in CASES:
        runs = []
        for _ in range(2):
            tmp = tempfile.mkdtemp(prefix=f"g0250_{case}_")
            with pytest.MonkeyPatch.context() as mp:
                runs.append(compute(case, tmp, mp))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = runs
        uns = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        got[case] = {k: v for k, v in a.items() if k not in uns}
        unstable[case] = uns
        print(case, len(a), "files", "unstable", uns, flush=True)
    doc = {"made_by": "tests/doe/golden_v0250_c1/golden_vb.py (release/v0.25.0 b1e52fad — 코드 변경 전)",
           "cases": got, "unstable": unstable, "guard": guard_docs(), "select": select_shas(), "morph": morph_shas()}
    print("guard", len(doc["guard"]), "select", len(doc["select"]), "morph", len(doc["morph"]))
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        raise SystemExit("ESL_GOLDEN_RECORD=1 로만 기록(옛 코드에서)")
    sys.path.insert(0, ROOT)
    _record()
