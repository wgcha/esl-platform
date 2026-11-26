"""select schema 2 — bead-network graph (계약 docs/contracts/esl_beadgraph.md BEADGRAPH v0.17.0 §3·§5·§6·§8.6).

The classifier / segment morph is the shared package ``beadgraph`` (packages/beadgraph, numpy/scipy only); this module is
the esl side: preparation files, selection schema 2, derive, params, basis (wrapped as ``bead_select.Basis``), design
checks, auto seed. Schema-1 studies never reach this module (byte-identical, BG-D-39).

STABLE INTERFACE (Backend / Frontend / worker — change only with the contract)
----------------------------------------------------------------------------------------------------------------------
Files (written by the core stage BD_LOADS, ``stages._sel_loads`` → ``prep_graph``; never under SPDM / input folders):
  prep/select/graph.json          beadgraph/1 graph (canonical bytes: sorted keys, compact, ASCII)  — GRAPH_JSON
  prep/select/graph_labels.npz    per-element int32 labels {cls, floor, segment, transition, island, junction_zone,
                                  tier}, allow_pickle=False, element order = base mesh order                — GRAPH_LABELS
  prep/select/graph.bin           browser view (§6.1): uint32 LE header length L | header JSON (L bytes, ASCII)
                                  {n_elems, arrays[{name, offset}]} | int32 LE arrays cls, segment, junction_zone,
                                  island, floor, tier. OFFSET CONVENTION: offset = bytes measured from the END OF THE
                                  HEADER (start of the array block = 4 + L), not from the file start; each array
                                  n_elems long, element order = select.bin element order                  — GRAPH_BIN
  prep/input.json  "graph": {ok, code, sha256, rules, morph_rules, beadgraph_version, n_segments, n_junction_zones,
                   n_islands, seconds}  (code = None | ERROR | TIMEOUT | TOO_LARGE | DISABLED | NO_FLOOR)
  prep/select/auto_selection.json (schema 2 + auto): {schema "esl/doe_auto_selection/2", source "graph", selection
                   (schema 2, normalized), sha256, sym_pairs, hints[], warnings[], mesh_sha256, graph_sha256}
Worker / stage entry point (BD_LOADS, select_schema 2 only):
  prep_graph(mesh, fixed_ids, cfg, out_dir, guard=None) -> status dict (above "graph"; never raises — failure =
  GRAPH_FAILED{code} warning, preparation stays READY)
Backend API helpers:
  load_graph(prep_dir) -> (graph, labels)               EslError GRAPH_NOT_AVAILABLE (404) when missing
  graph_sha256(prep_dir) -> str | None                  sha256 of graph.json bytes (selection graph.sha256)
  normalize_v2(sel, graph, cfg, *, labels, mesh=None, current_sha=None, shape_rules=None, virtual_bead=None) -> (norm, sha256)   422 / 409 codes below
      graph None (GRAPH_FAILED) = elems beads only, normalized selection then has no "graph" block
  derive_v2(mesh, norm, cfg, graph, labels, *, frame=None, fixed_scan=(), bead=None) -> SelectionDerived dict
      (+ graph block, graph_algo, params = DoeParamsOut rows, param_beads = params.json beads rows)
  derive_obj_v2(mesh, norm, cfg, graph, labels, *, fixed_node_ids=(), index=None, mesh_sha256=None) -> GraphDerived
  Graph edits: toggle / merge / split anchors = any element id of the segment / island / floor (the frontend sends the
  segment or island anchor); the core resolves an element to its floor (island element -> the island's root floor).
  GraphDerived.summary() -> SelectionDerived (+ "graph" block of §6.1, graph_algo)
  auto_seed(graph, labels, cfg) -> (selection schema 2 normalized, sym_pairs, warnings)
Selection schema 2 (SelectionIn, BG-D-36):
  {schema_version 2, feature_angle_deg, graph{sha256, rules, edits{toggle[{anchor, as}], merge[[{anchor}…]],
   split[{anchor, at[x, y]}]}}, beads[{id, name?, src "graph", segs[{anchor}|{network: anchor}], vars?["D","W"],
   hold_fixed? 0} | {id, name?, src "elems", tiers, slope, blend_mm, floor_follow, links, hold_fixed?}], ties[[id…]],
   fixed_user, exclude}       (split "at" = plan coordinates of the graph frame, like segment skeletons)
Variable names: graph beads B<n>_D / B<n>_W (no k — never collide with schema 1 B<n>_D<k>); tie = smallest id.
Codes: 422 BG_GROUP_NOT_CONNECTED{bead} · BG_TIE_NOMINAL{beads} · BG_SEG_UNKNOWN{anchor} · BG_EDIT_INVALID{edit} ·
  SELECT_OVERLAP · SELECT_SCHEMA_MISMATCH; 409 BG_GRAPH_STALE{saved, current}; 404 GRAPH_NOT_AVAILABLE;
  warnings GRAPH_FAILED{code} · GRAPH_RASTER_COARSE{raster_mm} · AUTO_HINT_UNAVAILABLE{step, code} ·
  BG_GROUP_NOMINAL_SPREAD{bead, min, max} · BG_SEGMENT_SHORT{bead, length_mm, ramp_mm} · BG_RAMP_SHORT{var, L_mm,
  need_mm}; info BG_SHARED_CHILD{bead, child, n_nodes} · BG_CORNER_GUARD{bead, n_nodes, flank_max_deg} ·
  BG_ISLAND_HELD{island} · BG_RANGE_CLAMPED{bead, var, from, to, inverted} (integration: default W range clamped to
  range_check usable); BD_MATRIX errors BG_BASIS_LEAK{var, n, max_mm} · BG_ACHIEVED_MISMATCH{var, err_mm};
  cell FAILED_MESH BG_OUTSIDE_MOVED{n, max_mm, vars}.
----------------------------------------------------------------------------------------------------------------------
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import time

import numpy as np

from esl.errors import EslError

GRAPH_JSON = "graph.json"
GRAPH_LABELS = "graph_labels.npz"
GRAPH_BIN = "graph.bin"
W_CLAMP_JSON = "w_clamp.json"            # Verifier fix v0.17.0 (BG-X-1): W default-range clamp computed in BD_LOADS
W_CLAMP_SCHEMA = "esl/bg_w_clamp/1"
RANGE_GUARD_JSON = "range_guard.json"   # v0.21.0 SH-13·18: prep/select/range_guard.json · select/<sha12>/range_guard.json
RANGE_GUARD_SCHEMA = "esl/range_guard/1"   # = esl.morph.range_guard.SCHEMA
GRAPH_BIN_ARRAYS = ("cls", "segment", "junction_zone", "island", "floor", "tier")
GRAPH_ALGO = 1                          # esl graph-path basis rules (basis.json.graph_algo — BG-D-39)
GRAPH_RULES = 1                         # graph-path design-check rules (grid_manifest.graph_rules)
SCHEMA_VERSION = 2
AUTO_SCHEMA_V2 = "esl/doe_auto_selection/2"      # = bead_auto.AUTO_SELECTION_SCHEMA_V2
FAIL_CODES = ("ERROR", "TIMEOUT", "TOO_LARGE", "DISABLED", "NO_FLOOR")


def _bg():
    import beadgraph
    return beadgraph


def _bad(code: str, msg: str, **detail):
    e = EslError(code, msg)
    e.extra = detail
    e.detail = detail
    raise e


def _r(v, nd: int = 4):
    from esl.doe.bead_select import _r as r
    return r(v, nd)


# ====================================================================== cfg
def select_cfg(cfg: dict | None) -> dict:
    from esl.doe.bead_select import _cfg
    return _cfg(cfg)


def graph_cfg(cfg: dict | None) -> dict:
    """select.graph without the esl-only ``enabled`` switch — passed whole to ``beadgraph.classify`` (R-BG-7)."""
    g = copy.deepcopy(select_cfg(cfg)["graph"])
    g.pop("enabled", None)
    return g


def morph_cfg(cfg: dict | None) -> dict:
    """graph cfg + the select sections the morph reuses (hold SR-D-9, blend R_auto, quality.flip_deg)."""
    sc = select_cfg(cfg)
    g = graph_cfg(cfg)
    g["hold"] = {"ring_mm": float(sc["hold"]["ring_mm"]), "blend_mm": float(sc["hold"]["blend_mm"])}
    g["blend"] = {"min_mm": float(sc["blend"]["min_mm"]), "k": float(sc["blend"]["k"])}
    g["quality"] = {"flip_deg": float(sc["quality"]["flip_deg"])}
    return g


# ====================================================================== preparation (BD_LOADS)
def _labels_npz(path: str, labels: dict, guard=None) -> None:
    from esl.doe.mesh_gmsh import save_npz_det
    g = guard or (lambda p: p)
    save_npz_det(g(path), {k: np.asarray(v, dtype="<i4") for k, v in labels.items()})


def graph_bin(labels: dict) -> bytes:
    n = int(np.asarray(labels["cls"]).size)
    arrays, off = [], 0
    for name in GRAPH_BIN_ARRAYS:
        arrays.append({"name": name, "offset": off})
        off += 4 * n
    head = json.dumps({"n_elems": n, "arrays": arrays}, sort_keys=True, separators=(",", ":")).encode("ascii")
    body = b"".join(np.ascontiguousarray(labels[k], dtype="<i4").tobytes() for k in GRAPH_BIN_ARRAYS)
    return struct.pack("<I", len(head)) + head + body


def read_graph_bin(blob: bytes) -> dict:
    (L,) = struct.unpack_from("<I", blob, 0)
    head = json.loads(blob[4:4 + L].decode("ascii"))
    base = 4 + L
    n = head["n_elems"]
    return {a["name"]: np.frombuffer(blob, "<i4", count=n, offset=base + a["offset"]) for a in head["arrays"]}


def prep_graph(mesh: dict, fixed_ids, cfg: dict | None, out_dir: str, guard=None, *, limits: dict | None = None) -> dict:
    """BD_LOADS (select_schema 2): classify the base mesh -> prep/select/graph.json · graph_labels.npz · graph.bin.
    fixed_ids = fixed node IDs (paicad fixed-scan; v0.18.0 select_base step = A fixed points transferred to B, SG-D-14a);
    out_dir = prep/select. limits (v0.18.0 SG-D-16, step only) = {max_elems, timeout_s} raising the graph limits
    (None = select.graph.limits as is — schema 2 ①② bytes unchanged). Never raises: failure -> {ok False, code}."""
    bg = _bg()
    sc = select_cfg(cfg)
    gc = graph_cfg(cfg)
    if limits:                                         # SG-D-16 (i): max(graph.limits, step_graph) per key
        gl = dict(gc["limits"])
        for k in ("max_elems", "timeout_s"):
            if limits.get(k) is not None:
                gl[k] = type(gl[k])(max(float(gl[k]), float(limits[k])))
        gc["limits"] = gl
    g = guard or (lambda p: p)
    st = {"ok": False, "code": None, "sha256": None, "rules": bg.RULES, "morph_rules": bg.MORPH_RULES,
          "beadgraph_version": bg.OUTPUT_VERSION, "n_segments": 0, "n_junction_zones": 0, "n_islands": 0,
          "seconds": 0.0, "warnings": []}
    if not sc["graph"].get("enabled", True):
        st["code"] = "DISABLED"
        return st
    ne = int(np.asarray(mesh["elem_type"]).size)
    if ne > int(gc["limits"]["max_elems"]):
        st["code"] = "TOO_LARGE"
        return st
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C = _conn(mesh)
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    fx = np.flatnonzero(np.isin(nid, np.asarray(list(fixed_ids), dtype=np.int64))) if len(fixed_ids) else \
        np.zeros(0, np.int64)
    t0 = time.perf_counter()
    try:
        graph, labels = bg.classify(X, C, fx, gc)
    except bg.BeadgraphError as exc:
        st["code"] = exc.code if exc.code in FAIL_CODES else "ERROR"
        if st["code"] != exc.code:                     # INVALID_INPUT etc. -> ERROR + the package detail (§8.2)
            st["error"] = str(exc)[:300]
        st["seconds"] = round(time.perf_counter() - t0, 3)
        return st
    except Exception as exc:  # noqa: BLE001 — classification failure never blocks the preparation (BG-D-40)
        st["code"] = "ERROR"
        st["error"] = f"{type(exc).__name__}: {exc}"[:300]
        st["seconds"] = round(time.perf_counter() - t0, 3)
        return st
    blob = bg.graph_bytes(graph)
    with open(g(os.path.join(out_dir, GRAPH_JSON)), "wb") as fh:
        fh.write(blob)
    _labels_npz(os.path.join(out_dir, GRAPH_LABELS), labels, guard)
    with open(g(os.path.join(out_dir, GRAPH_BIN)), "wb") as fh:
        fh.write(graph_bin(labels))
    st.update(ok=True, sha256=hashlib.sha256(blob).hexdigest(), n_segments=len(graph["segments"]),
              n_junction_zones=len(graph["junction_zones"]), n_islands=len(graph["islands"]),
              seconds=round(time.perf_counter() - t0, 3), warnings=list(graph.get("warnings") or []))
    return st


def _conn(mesh: dict) -> np.ndarray:
    C = np.asarray(mesh["conn"], dtype=np.int64).copy()
    et = np.asarray(mesh["elem_type"]).astype(int)
    C[et == 3, 3] = -1
    return C


def load_graph(prep_dir: str) -> tuple[dict, dict]:
    """prep/ (or prep/select/) -> (graph, labels). EslError GRAPH_NOT_AVAILABLE when the files are missing."""
    d = prep_dir if os.path.isfile(os.path.join(prep_dir, GRAPH_JSON)) else os.path.join(prep_dir, "select")
    pj, pl = os.path.join(d, GRAPH_JSON), os.path.join(d, GRAPH_LABELS)
    if not (os.path.isfile(pj) and os.path.isfile(pl)):
        raise EslError("GRAPH_NOT_AVAILABLE", "분류 그래프가 없음(schema 1 스터디 또는 GRAPH_FAILED)")
    with open(pj, "rb") as fh:
        graph = json.loads(fh.read().decode("ascii"))
    with np.load(pl, allow_pickle=False) as z:
        labels = {k: np.asarray(z[k], dtype=np.int32) for k in z.files}
    return graph, labels


def load_w_clamp(prep_dir: str) -> dict | None:
    """prep/ (or prep/select/) -> the BD_LOADS W clamp table (``w_clamp_table``) or None (missing / other schema)."""
    d = prep_dir if os.path.isfile(os.path.join(prep_dir, GRAPH_JSON)) else os.path.join(prep_dir, "select")
    p = os.path.join(d, W_CLAMP_JSON)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "rb") as fh:
            doc = json.loads(fh.read().decode("ascii"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == W_CLAMP_SCHEMA else None


def _ds_view(depth_section, section_rules) -> dict | None:
    """v0.24.7 DM §2.2·§5: 표 머리(range_guard·w_clamp) cfg_sha256 에 더할 값 — floor_fixed 만(entry_fixed·키 없음 = None, 해시 불변)."""
    from esl.morph import section as sec
    if not sec.is_floor(depth_section):
        return None
    return sec.hash_view(depth_section, section_rules, has_elems=False)


def _cfg_key(cfg, ds_view: dict | None = None) -> str:
    """sha of the select settings the W basis and the inversion judgement read (range · quality · graph · hold · blend),
    numbers as floats (API and worker settings dicts may spell 1 / 1.0 differently): a table made under another setting
    is not applied. v0.24.7: ds_view(floor_fixed 만) 가 있으면 보기에 ``ds`` 키."""
    sc = select_cfg(cfg)

    def canon(v):
        if isinstance(v, dict):
            return {str(k): canon(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [canon(x) for x in v]
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v)
        return str(v)
    view = canon({k: sc.get(k) for k in ("range", "quality", "graph", "hold", "blend")})
    if ds_view is not None:
        view["ds"] = canon(ds_view)
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _seg_keys(g: dict, ids) -> list:
    return [[int(g["segments"][s]["anchor"]), int(g["segments"][s]["n_elems"])] for s in ids]


def _inward(v: float, nom: float) -> float:
    """round a usable end to 1e-4 toward the nominal (a rounded end never lands on the inverting side)."""
    q = v * 1e4
    return float((np.ceil(q - 1e-9) if v < nom else np.floor(q + 1e-9)) / 1e4)


def w_clamp_table(mesh: dict, graph: dict, labels: dict, fixed_ids, cfg: dict | None,
                  shape_rules: dict | None = None, depth_section: str | None = None,
                  section_rules: dict | None = None) -> dict:
    """Verifier fix v0.17.0 (§12 BG-X-1): before any matrix exists, find for every W-capable graph bead candidate — each
    segment with an entry width + each auto-seed W group (channel + flare) — the non-inverting part of its default W
    range, exactly as BD_MATRIX ``range_check`` would (same basis: package ``basis`` through ``basis_v2``, ramp frozen
    at the original default range; same inversion rule ``design_state``; ``range.check_steps`` bisections). Only
    candidates whose default range inverts get an entry. Deterministic.
    v0.21.0 §2.1: shape_rules 의 w_partial(range_guard 꺼짐)이면 자동 seed 후보 = S_W 가 있는 묶음(W 는 S_W 에만).
    v0.24.7 DM §2.2: depth_section floor_fixed(키 전달 = floor_fixed 만) → 한쪽 입구 세그먼트(S_1) 후보 W1 추가, 머리 cfg += ds."""
    from esl.doe import bead_select as bs
    sc = select_cfg(cfg)
    wp = _w_partial(shape_rules)
    dsv = _ds_view(depth_section, section_rules)
    if dsv is not None and section_rules is None:
        section_rules = _section_rules_now(cfg)
    dskw = {"depth_section": depth_section, "section_rules": section_rules} if dsv is not None else {}
    doc = {"schema": W_CLAMP_SCHEMA, "graph_sha256": graph_sha_of(graph), "cfg_sha256": _cfg_key(cfg, dsv),
           "hold": 1, "entries": []}
    steps = int(sc["range"]["check_steps"] or 0)
    if steps <= 0:
        return doc
    cands, seen = [], set()
    for s in graph["segments"]:
        if s["type"] != "base" and s.get("entry_width") is not None:
            cands.append([s["id"]])
    if dsv is not None:                                 # v0.24.7 DM: S_1 단일 세그먼트(W1)
        osd = _one_side_all(mesh, graph, labels, section_rules)
        cands += [[sid] for sid in sorted(osd) if graph["segments"][sid]["entry_width"] is None and osd[sid]["ok"]]
    sel, _sym, _aw = auto_seed(graph, labels, cfg)
    for b in sel["beads"]:
        ids, _z, net = _resolve_segs(graph, labels, b["segs"], b["id"])
        if not net and len(ids) > 1 and (w_segs(graph, ids) if wp else
                                         all(graph["segments"][x]["entry_width"] is not None for x in ids)):
            cands.append(sorted(ids))
    out = []
    for grp in cands:
        k = tuple(grp)
        if k not in seen:
            seen.add(k)
            out.append(grp)
    if not out:
        return doc
    beads = [{"id": f"b{i + 1}", "name": f"W{i + 1}", "src": "graph", "vars": ["W"],
              "segs": [{"anchor": int(graph["segments"][x]["anchor"])} for x in grp]} for i, grp in enumerate(out)]
    sc_fa = float(sc["feature_angle_deg"])
    norm = {"schema_version": SCHEMA_VERSION, "feature_angle_deg": sc_fa, "beads": beads, "ties": [],
            "fixed_user": bs._norm_set(None, "fixed_user", 10_000_000), "exclude": bs._norm_set(None, "exclude", 10_000_000),
            "graph": {"sha256": doc["graph_sha256"], "rules": int(graph["rules"]), "edits": {}}}
    D = derive_obj_v2(mesh, norm, cfg, graph, labels, fixed_node_ids=fixed_ids,
                      shape_rules=_no_guard(shape_rules) if wp else None, **dskw)
    B = bs.basis(mesh, D, cfg)
    x0 = np.asarray(mesh["x0"], dtype=np.float64)

    def inv(name, v):
        st = bs.design_state(mesh, x0, bs.morph(x0, B, {name: float(v)}), D.fixed_mask, cfg)
        return int(st["quality"]["inverted"]) if st["code"] == "SELECT_MORPH_INVERTED" else 0
    by = {b.id: b for b in D.beads}
    for row in params_rows_v2(D, cfg):
        if row["type"] != "W":
            continue
        lo, hi = (float(v) for v in row["default_range"])
        nom = float(row["nominal"])
        res = []
        for end in (lo, hi):
            k = inv(row["name"], end)
            good = end
            if k:
                a, b2 = nom, end
                for _ in range(steps):
                    m = 0.5 * (a + b2)
                    if inv(row["name"], m):
                        b2 = m
                    else:
                        a = m
                good = _inward(a, nom)
            res.append((k, good))
        if res[0][0] or res[1][0]:
            b = by[row["bead"]]
            doc["entries"].append({"segs": _seg_keys(graph, b.seg_ids), "from": [_r(lo), _r(hi)],
                                   "usable": [res[0][1], res[1][1]], "inverted": [res[0][0], res[1][0]]})
    doc["entries"].sort(key=lambda e: e["segs"])
    return doc


def _section_rules_now(cfg) -> dict:
    from esl.doe import settings as _settings
    return _settings(cfg if isinstance(cfg, dict) and "select" in cfg else None)["depth_section_rules"]


def _one_side_all(mesh: dict, graph: dict, labels: dict, section_rules: dict) -> dict:
    """v0.24.7 DM: 그래프 비 base 세그먼트 전부의 ``beadgraph.one_side``(W1 후보 판정 — range_guard·w_clamp 후보)."""
    sids = [int(s["id"]) for s in graph["segments"] if s["type"] != "base" and int(s["anchor"]) >= 0]
    if not sids:
        return {}
    return _bg().one_side(graph, labels, np.asarray(mesh["x0"], np.float64), _conn(mesh), sids,
                          min_nodes=int(section_rules["one_side_min_nodes"]))


def _w1_possible(graph: dict, ids, osd: dict, wp: bool, net: bool) -> bool:
    """§1.6.1: S_2 = ∅ ∧ S_1 ≠ ∅ ∧ (w_partial ∨ S_1 = S) ∧ 네트워크 아님 — ``_floor_fixed_bead`` 의 W1 조건(측정 osd 공용)."""
    if net or w_segs(graph, ids):
        return False
    s1 = [x for x in ids if graph["segments"][x]["entry_width"] is None and (osd.get(x) or {}).get("ok")]
    return bool(s1) and (wp or len(s1) == len(ids))


def write_w_clamp(path: str, doc: dict, guard=None) -> str:
    g = guard or (lambda p: p)
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    with open(g(path), "wb") as fh:
        fh.write(blob)
    return hashlib.sha256(blob).hexdigest()


def _apply_w_clamp(D, norm: dict, w_clamp: dict | None, cfg, user_free: bool, ds_view: dict | None = None) -> None:
    """derive: graph beads whose W default range was found to invert in BD_LOADS (``w_clamp_table``) get the usable
    range as default and the inverting side of ``feasible`` clamped, + info BG_RANGE_CLAMPED (§12 BG-X-1) — so the
    first matrix never carries an inverting W design. Applied only when the table matches (same graph sha, same select
    settings, no toggle edit, no fixed_user / exclude, bead hold 1, same segments and default range); otherwise the
    BD_MATRIX clamp (``clamp_w_ranges``) still applies. Tied beads: the carrier's range = the members' common Δ."""
    if not w_clamp or not w_clamp.get("entries") or not user_free:
        return
    ng = norm.get("graph") or {}
    if (ng.get("edits") or {}).get("toggle") or w_clamp.get("graph_sha256") != ng.get("sha256") or \
            w_clamp.get("cfg_sha256") != _cfg_key(cfg, ds_view):
        return
    table = {json.dumps(e["segs"]): e for e in w_clamp["entries"]}
    hit = {}
    for b in D.beads:
        if getattr(b, "src", None) != "graph" or "W" not in (b.vars or []) or b.W_nom is None:
            continue
        e = table.get(json.dumps(_seg_keys(D.graph, b.seg_ids)))
        if e is None or int(b.hold_fixed) != int(w_clamp.get("hold", 1)) or \
                [float(x) for x in e["from"]] != [float(x) for x in b.range_default["W"]]:
            continue
        u = [float(x) for x in e["usable"]]
        if not (u[0] < float(b.W_nom) < u[1]):
            continue                                    # degenerate: keep SELECT_RANGE_INVERTS (BD_MATRIX)
        old = list(b.range_default["W"])
        b.range_default["W"] = [_r(u[0]), _r(u[1])]
        fe = list(b.range_feasible["W"])
        if e["inverted"][0]:
            fe[0] = max(fe[0], _r(u[0]))
        if e["inverted"][1]:
            fe[1] = min(fe[1], _r(u[1]))
        b.range_feasible["W"] = fe
        b.warnings.append({"code": "BG_RANGE_CLAMPED", "level": "info", "bead": b.id, "var": var_name(b.id, "W"),
                           "from": old, "to": list(b.range_default["W"]), "inverted": list(e["inverted"])})
        hit[b.id] = True
    by = {b.id: b for b in D.beads}
    for grp in norm.get("ties") or []:
        mem = [by[x] for x in grp if x in by and "W" in (by[x].vars or []) and by[x].W_nom is not None]
        if len(mem) < 2 or not any(m.id in hit for m in mem):
            continue
        car = by[grp[0]]
        dlo = max(float(m.range_default["W"][0]) - float(m.W_nom) for m in mem)
        dhi = min(float(m.range_default["W"][1]) - float(m.W_nom) for m in mem)
        if dlo < 0.0 < dhi:
            car.range_default["W"] = [_inward(float(car.W_nom) + dlo, float(car.W_nom)),
                                      _inward(float(car.W_nom) + dhi, float(car.W_nom))]
            car.range_feasible["W"] = [max(car.range_feasible["W"][0], car.range_default["W"][0]),
                                       min(car.range_feasible["W"][1], car.range_default["W"][1])]


def graph_sha256(prep_dir: str) -> str | None:
    d = prep_dir if os.path.isfile(os.path.join(prep_dir, GRAPH_JSON)) else os.path.join(prep_dir, "select")
    p = os.path.join(d, GRAPH_JSON)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def graph_sha_of(graph: dict) -> str:
    return hashlib.sha256(_bg().graph_bytes(graph)).hexdigest()


# ====================================================================== selection schema 2 (BG-D-35..38)
def _anchor(x, where):
    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
        _bad("BG_EDIT_INVALID", f"{where}: anchor 는 0 이상 정수", edit=where)
    return int(x)


def _norm_edits(ed) -> dict:
    ed = ed or {}
    if not isinstance(ed, dict) or set(ed) - {"toggle", "merge", "split"}:
        _bad("BG_EDIT_INVALID", "edits 는 {toggle, merge, split}", edit=ed)
    tog = []
    for e in ed.get("toggle") or []:
        if not isinstance(e, dict) or e.get("as") not in ("bead", "island"):
            _bad("BG_EDIT_INVALID", "toggle 은 {anchor, as: bead|island}", edit=e)
        tog.append({"anchor": _anchor(e.get("anchor"), "toggle"), "as": e["as"]})
    mer = []
    for grp in ed.get("merge") or []:
        if not isinstance(grp, list) or len(grp) < 2:
            _bad("BG_EDIT_INVALID", "merge 는 [{anchor}, {anchor}…] 2개 이상", edit=grp)
        mer.append(sorted({_anchor((x or {}).get("anchor"), "merge") for x in grp}))
    spl = []
    for e in ed.get("split") or []:
        at = (e or {}).get("at")
        if not isinstance(at, (list, tuple)) or len(at) != 2 or not all(isinstance(v, (int, float)) for v in at):
            _bad("BG_EDIT_INVALID", "split 은 {anchor, at: [x, y]}", edit=e)
        spl.append({"anchor": _anchor(e.get("anchor"), "split"), "at": [round(float(at[0]), 3), round(float(at[1]), 3)]})
    out = {}
    if tog:
        out["toggle"] = sorted(tog, key=lambda e: (e["anchor"], e["as"]))
    if mer:
        out["merge"] = sorted([[{"anchor": a} for a in g] for g in mer], key=lambda g: [x["anchor"] for x in g])
    if spl:
        out["split"] = sorted(spl, key=lambda e: (e["anchor"], e["at"]))
    return out


def edited_graph(graph: dict, labels: dict, edits: dict | None, mesh: dict | None = None):
    """apply the selection's graph edits (BG-D-37). EditError -> 422 BG_EDIT_INVALID, KeyError -> BG_SEG_UNKNOWN."""
    bg = _bg()
    if not edits:
        return graph, labels
    from beadgraph.edits import EditError
    X = np.asarray(mesh["x0"], dtype=np.float64) if mesh is not None else None
    C = _conn(mesh) if mesh is not None else None
    try:
        return bg.apply_edits(graph, labels, edits, X, C)
    except EditError as exc:
        _bad("BG_EDIT_INVALID", str(exc), edit=exc.detail.get("edit"))
    except KeyError as exc:
        ref = exc.args[0] if exc.args else None
        _bad("BG_SEG_UNKNOWN", f"앵커 {ref} 를 그래프에서 찾을 수 없음", anchor=(ref or {}).get("anchor")
             if isinstance(ref, dict) else ref)


def w_segs(graph, seg_ids) -> list[int]:
    """v0.21.0 SH-4: S_W = 비드 세그먼트 중 ``entry_width`` 가 있는 것(정렬)."""
    return sorted(int(s) for s in seg_ids if graph["segments"][s]["entry_width"] is not None)


def _w_partial(rules) -> bool:
    """새 스냅샷 ``shape_rules.w_partial``(None = v0.20.0 규칙 — W 는 모든 세그먼트에 폭이 있을 때만)."""
    return bool(rules) and bool(rules.get("w_partial"))


def _possible_vars(graph, seg_ids, w_partial: bool = False) -> list[str]:
    if w_partial:                                      # SH-4: |S_W| ≥ 1 이면 W 가능
        return ["D", "W"] if w_segs(graph, seg_ids) else ["D"]
    ws = [graph["segments"][s]["entry_width"] for s in seg_ids]
    return ["D", "W"] if ws and all(w is not None for w in ws) else ["D"]


def _resolve_segs(graph, labels, segs, bid) -> tuple[list[int], list[int], bool]:
    """segs refs -> (segment ids, extra zone ids, network?). 422 BG_SEG_UNKNOWN / BG_GROUP_NOT_CONNECTED."""
    bg = _bg()
    ids, zones, net = set(), set(), False
    for ref in segs:
        try:
            if "network" in ref:
                n = bg.resolve(graph, labels, {"network": int(ref["network"])})
                ids |= set(graph["networks"][n]["segments"])
                zones |= set(graph["networks"][n]["junction_zones"])
                net = True
            else:
                ids.add(bg.resolve(graph, labels, {"anchor": int(ref["anchor"])}))
        except KeyError:
            _bad("BG_SEG_UNKNOWN", f"{bid}: 앵커 {ref} 를 그래프에서 찾을 수 없음",
                 anchor=ref.get("anchor", ref.get("network")))
    ids = sorted(ids)
    floors = {graph["segments"][s]["floor"] for s in ids}
    if len(floors) != 1:
        _bad("BG_GROUP_NOT_CONNECTED", f"{bid}: 세그먼트가 서로 다른 바닥(네트워크)에 있음", bead=bid)
    if not net and len(ids) > 1:                     # connected through junction zones (BG-D-17)
        par = {s: s for s in ids}

        def find(a):
            while par[a] != a:
                a = par[a]
            return a
        for z in graph["junction_zones"]:
            m = sorted(set(z["adj_segments"]) & set(ids))
            for a, b in zip(m, m[1:]):
                par[find(b)] = find(a)
        if len({find(s) for s in ids}) != 1:
            _bad("BG_GROUP_NOT_CONNECTED", f"{bid}: 세그먼트가 접합 구역으로 이어지지 않음", bead=bid)
    return ids, sorted(zones), net


def normalize_v2(sel, graph: dict | None, cfg: dict | None = None, *, labels: dict | None = None,
                 mesh: dict | None = None, current_sha: str | None = None,
                 shape_rules: dict | None = None, virtual_bead: dict | None = None) -> tuple[dict, str]:
    """SelectionIn schema 2 -> (normalized, sha256). Graph beads are validated against the edited graph.
    graph None (GRAPH_FAILED) = elems beads only (a graph bead -> BG_SEG_UNKNOWN); labels are required with a graph.
    shape_rules (v0.21.0 스냅샷 ``doe.shape_rules`` 해석값, None = v0.20.0): ``w_partial`` 이면 W 가능 = |S_W| ≥ 1(SH-4).
    virtual_bead (v0.25.0 INT-2 — 스냅샷 ``doe.virtual_bead`` 블록, None = 설정값): 가상 비드 θ 기본·범위 등 해시 안 키 = 블록 값
    (``vb_block`` — derive 와 같은 해석, 설정이 스터디 생성 뒤 바뀌어도 선택 sha 같음)."""
    from esl.doe import bead_select as bs
    sc = select_cfg(cfg)
    wp = _w_partial(shape_rules)
    if not isinstance(sel, dict) or sel.get("schema_version") != 2:
        _bad("SELECT_SCHEMA_MISMATCH", "schema 2 선택이 아님")
    gin = sel.get("graph") or {}
    if not isinstance(gin, dict):
        _bad("BG_EDIT_INVALID", "graph 는 객체", edit=gin)
    if graph is not None and labels is None:
        raise EslError("GRAPH_NOT_AVAILABLE", "분류 라벨(graph_labels.npz)이 없음")
    cur = (current_sha or graph_sha_of(graph)) if graph is not None else None
    if graph is not None and gin.get("sha256") != cur:
        _bad("BG_GRAPH_STALE", "분류 결과가 바뀌었습니다 — 다시 확인 후 저장", saved=gin.get("sha256"), current=cur)
    edits = _norm_edits(gin.get("edits")) if graph is not None else {}
    g2, l2 = edited_graph(graph, labels, edits, mesh) if graph is not None else (None, None)
    beads = sel.get("beads")
    vbs = normalize_vbeads(sel.get("virtual_beads"), cfg, vb_flip_deg(cfg, shape_rules) if sel.get("virtual_beads")
                           else None, block=virtual_bead)   # v0.25.0 VB §2.1·§19(없음·빈 목록 = [] — 키 안 씀), INT-2 블록 값
    if not isinstance(beads, list) or not (1 if not vbs else 0) <= len(beads) <= int(sc["max_beads"]):
        _bad("SELECT_EMPTY_TIER", f"beads 는 1..{sc['max_beads']} 개")   # VB-15: beads + virtual_beads ≥ 1
    elem_beads = [b for b in beads if isinstance(b, dict) and b.get("src") == "elems"]
    graph_beads = [b for b in beads if isinstance(b, dict) and b.get("src", "graph") == "graph"]
    if len(elem_beads) + len(graph_beads) != len(beads):
        _bad("SELECT_BEAD_ID_INVALID", "비드 src 는 graph | elems")
    # elems beads = schema 1 bead bodies (normalized by the schema 1 rules)
    s1 = None
    if elem_beads:
        s1in = {"schema_version": 1, "feature_angle_deg": sel.get("feature_angle_deg"),
                "beads": [{k: v for k, v in b.items() if k != "src"} for b in elem_beads],
                "fixed_user": sel.get("fixed_user"), "exclude": sel.get("exclude")}
        s1 = bs.normalize_input(s1in, cfg)
    seen = {b["id"] for b in (s1["beads"] if s1 else [])}
    out_beads = []
    for b in (s1["beads"] if s1 else []):
        nb = dict(b)
        nb["src"] = "elems"
        out_beads.append(nb)
    seg_owner = {}
    if graph_beads and graph is None:
        _bad("BG_SEG_UNKNOWN", "분류 결과가 없음(GRAPH_FAILED) — 요소 비드(src elems)만 가능", anchor=None)
    for b in graph_beads:
        bid = b.get("id")
        if not isinstance(bid, str) or not bs.BEAD_ID_RE.match(bid) or int(bid[1:]) > int(sc["max_beads"]) or \
                bid in seen:
            _bad("SELECT_BEAD_ID_INVALID", f"비드 id {bid!r} 는 b1..b{sc['max_beads']} 고유")
        seen.add(bid)
        name = b.get("name")
        if name is None:
            name = f"B{bid[1:]}"
        if not isinstance(name, str) or not 1 <= len(name) <= 32 or bs._CTRL_RE.search(name):
            _bad("SELECT_NAME_INVALID", f"{bid}: 이름은 1..32자, 제어문자 금지")
        segs = b.get("segs")
        if not isinstance(segs, list) or not segs or not all(isinstance(x, dict) and (set(x) == {"anchor"} or
                                                                                         set(x) == {"network"})
                                                              for x in segs):
            _bad("BG_SEG_UNKNOWN", f"{bid}: segs 는 [{{anchor}} | {{network}}] 1개 이상", anchor=None)
        nsegs = sorted(({"network": _anchor(x["network"], bid)} if "network" in x else {"anchor": _anchor(x["anchor"], bid)}
                        for x in segs), key=lambda x: (0 if "anchor" in x else 1, x.get("anchor", x.get("network"))))
        ids, _z, net = _resolve_segs(g2, l2, nsegs, bid)
        for s in ids:
            if s in seg_owner:
                _bad("SELECT_OVERLAP", f"세그먼트 {s} 가 {seg_owner[s]}·{bid} 에 겹침", bead=bid, elems_n=0)
            seg_owner[s] = bid
        poss = ["D"] if net else _possible_vars(g2, ids, wp)
        nb = {"id": bid, "name": name, "src": "graph", "segs": nsegs}
        vs = b.get("vars")
        if vs is not None:
            if not isinstance(vs, list) or not vs or any(v not in ("D", "W") for v in vs):
                _bad("BG_EDIT_INVALID", f"{bid}: vars 는 D|W 목록", edit=vs)
            vs = sorted(set(vs))
            if any(v not in poss for v in vs):
                _bad("BG_EDIT_INVALID", f"{bid}: 이 세그먼트는 {poss} 만 가능", edit=vs)
            if vs != poss:
                nb["vars"] = vs
        hf = b.get("hold_fixed", 1)
        if hf not in (0, 1) or isinstance(hf, bool):
            _bad("SELECT_HOLD_INVALID", f"{bid}: hold_fixed 는 0|1", bead=bid)
        if int(hf) == 0:                                # BG-D-36: written only when it differs from the default (1)
            nb["hold_fixed"] = 0
        out_beads.append(nb)
    out_beads.sort(key=lambda b: int(b["id"][1:]))
    # graph beads vs elems beads element overlap (SELECT_OVERLAP)
    if elem_beads and graph_beads:
        ids_by = {b["id"]: _resolve_segs(g2, l2, b["segs"], b["id"]) for b in out_beads if b["src"] == "graph"}
        gmask = np.isin(l2["segment"], sorted({s for v in ids_by.values() for s in v[0]}))
        eid = np.asarray(mesh["elem_id"]) if mesh is not None else None
        if eid is not None:
            q = np.asarray(mesh["elem_type"]).astype(int) == 4
            for b in s1["beads"]:
                for typ, m in (("q", q), ("t", ~q)):
                    ids = bs.ids_from_ranges([r for t in b["tiers"] for r in t["floor"][typ]] +
                                             list(b["slope"]["add"][typ]))
                    if ids.size and (gmask & m & np.isin(eid, ids)).any():
                        _bad("SELECT_OVERLAP", f"{b['id']} 요소가 그래프 비드와 겹침", bead=b["id"], elems_n=1)
    ties = []
    ids_all = {b["id"] for b in out_beads}
    used = set()
    for grp in sel.get("ties") or []:
        if not isinstance(grp, list) or len(grp) < 2 or len(set(grp)) != len(grp) or any(x not in ids_all for x in grp) \
                or used & set(grp):
            _bad("BG_TIE_NOMINAL", f"ties {grp!r} 는 서로 다른 비드 2개 이상, 겹침 없음", beads=grp)
        used |= set(grp)
        ties.append(sorted(grp, key=lambda x: int(x[1:])))
    ties.sort(key=lambda g: int(g[0][1:]))
    if ties:
        _check_ties(g2, l2, out_beads, ties, sc, wp)
    fa = sel.get("feature_angle_deg")
    fa = float(sc["feature_angle_deg"]) if fa is None else fa
    if isinstance(fa, bool) or not isinstance(fa, (int, float)) or not 1.0 <= float(fa) <= 45.0:
        _bad("SELECT_EMPTY_TIER", f"feature_angle_deg 는 1..45 (값 {fa!r})")
    norm = {"schema_version": SCHEMA_VERSION, "feature_angle_deg": float(fa),
            "beads": out_beads, "ties": ties,
            "fixed_user": s1["fixed_user"] if s1 else bs._norm_set(sel.get("fixed_user"), "fixed_user", 10_000_000),
            "exclude": s1["exclude"] if s1 else bs._norm_set(sel.get("exclude"), "exclude", 10_000_000)}
    if graph is not None:                               # GRAPH_FAILED: no graph block (elems beads only)
        norm["graph"] = {"sha256": cur, "rules": int(graph["rules"]), "edits": edits}
    if vbs:                                             # v0.25.0 VB: 있을 때만 키(옛 sha·산출물 바이트 불변)
        norm["virtual_beads"] = vbs
    js = bs.canonical_json(norm)
    if len(js) > int(sc["max_selection_kb"]) * 1024:
        _bad("SELECT_TOO_LARGE", f"정규화 선택 {len(js) // 1024} KB")
    return norm, bs.selection_sha256(norm)


def _bead_nominals(g, l, b, w_partial: bool = False):
    ids, _z, net = _resolve_segs(g, l, b["segs"], b["id"])
    lens = np.array([float(g["segments"][s]["length"] or 1.0) for s in ids])
    D = float(np.sum(lens * np.array([float(g["segments"][s]["D"]) for s in ids])) / lens.sum())
    if w_partial:                                      # SH-5: W_nom = S_W 길이 가중 평균 entry_width
        sw = w_segs(g, ids)
        if net or not sw:
            return D, None
        lw = np.array([float(g["segments"][s]["length"] or 1.0) for s in sw])
        return D, float(np.sum(lw * np.array([float(g["segments"][s]["entry_width"]) for s in sw])) / lw.sum())
    ws = [g["segments"][s]["entry_width"] for s in ids]
    W = None if net or any(w is None for w in ws) else float(np.sum(lens * np.array(ws, float)) / lens.sum())
    return D, W


def _check_ties(g, l, beads, ties, sc, w_partial: bool = False):
    tol = float(sc["graph"]["sym_tol_mm"])
    by = {b["id"]: b for b in beads}
    for grp in ties:
        if any(by[x]["src"] != "graph" for x in grp):
            _bad("BG_TIE_NOMINAL", "대칭 묶기는 그래프 비드만", beads=grp)
        nom = [_bead_nominals(g, l, by[x], w_partial) for x in grp]
        Ds = [n[0] for n in nom]
        Ws = [n[1] for n in nom]
        if len({w is None for w in Ws}) != 1 or max(Ds) - min(Ds) > tol or \
                (Ws[0] is not None and max(Ws) - min(Ws) > 2.0 * tol):
            _bad("BG_TIE_NOMINAL", f"묶을 비드의 공칭이 다름 D {Ds} W {Ws}", beads=grp)


# ====================================================================== derive
class GraphBead:
    """one graph bead (schema 2 src graph) — attributes used by the shared select pipeline."""

    def __init__(self, bid, name):
        self.id, self.name, self.src = bid, name, "graph"
        self.warnings: list[dict] = []
        self.islands, self.holes, self.features = [], [], []
        self.loops: list[dict] = []
        self.tiers: list = []
        self.section = None


class GraphDerived:
    def __init__(self, norm, sha, beads, fixed, warnings, index, mesh_sha256, graph, labels, d1):
        self.norm, self.sha256, self.beads, self.fixed, self.warnings = norm, sha, beads, fixed, warnings
        self.index, self.mesh_sha256 = index, mesh_sha256
        self.graph, self.labels, self.d1 = graph, labels, d1
        self.schema_version = 2

    def bead(self, bid):
        return next(b for b in self.beads if b.id == bid)

    def summary(self, frame=None, *, rev=None, with_figures=True) -> dict:
        from esl.doe import bead_select as bs
        rows = []
        s1 = {r["id"]: r for r in (self.d1.summary(frame, rev=rev, with_figures=with_figures)["beads"]
                                   if self.d1 is not None else [])}
        for b in self.beads:
            if b.src == "elems":
                r = dict(s1[b.id])
                r["src"] = "elems"
                rows.append(r)
                continue
            rows.append({"id": b.id, "name": b.name, "src": "graph", "segs": [self.graph["segments"][s]["anchor"]
                                                                          for s in b.seg_ids],
                         "n_elems": int(b.bead_mask.sum()), "n_nodes": int(b.bead_nodes.size), "vars": b.vars,
                         "D_nom": _r(b.D_nom), "W_nom": _r(b.W_nom), "tier": b.tier,
                         "range_default": b.range_default, "range_feasible": b.range_feasible,
                         "warnings": b.warnings, "hold_fixed": b.hold_fixed, "network": b.network,
                         "n_segments": len(b.seg_ids), "n_junction_zones": len(b.zone_ids)})
            if getattr(b, "w_cover", None) is not None:   # v0.21.0 §3.2: W 부분일 때만
                rows[-1]["w_segs"] = [self.graph["segments"][s]["anchor"] for s in b.w_seg_ids]
                rows[-1]["w_cover"] = b.w_cover
        g = self.graph
        ng = self.norm.get("graph") or {"sha256": None, "edits": {}}
        doc = {"rev": rev, "sha256": self.sha256, "mesh_sha256": self.mesh_sha256, "beads": rows, "fixed": self.fixed,
               "warnings": self.warnings, "algo": bs.ALGO, "graph_algo": GRAPH_ALGO, "schema_version": 2,
               "graph": {"sha256": ng["sha256"], "graph_algo": GRAPH_ALGO,
                         "edits_applied": {k: len(ng["edits"].get(k) or [])
                                           for k in ("toggle", "merge", "split")},
                         "segments": [{k: s[k] for k in ("id", "anchor", "type", "side", "tier", "D", "entry_width",
                                                         "length", "network")} for s in g["segments"]],
                         "junction_zones": [{k: z[k] for k in ("id", "anchor", "reason")} for z in g["junction_zones"]],
                         "beads": [{"id": b.id, "src": b.src,
                                    "segs": [g["segments"][s]["anchor"] for s in getattr(b, "seg_ids", [])],
                                    "vars": getattr(b, "vars", None), "D_nom": _r(getattr(b, "D_nom", None)),
                                    "W_nom": _r(getattr(b, "W_nom", None)), "tier": getattr(b, "tier", None)}
                                   for b in self.beads],
                         "sym_pairs": [[g["segments"][a]["anchor"], g["segments"][b]["anchor"]]
                                       for a, b in sym_pairs(g, self.norm_cfg_tol)]}}
        return doc

    norm_cfg_tol = 0.5

    def slope_suggested(self):
        return self.d1.slope_suggested() if self.d1 is not None else {}

    def islands_suggested(self):
        return self.d1.islands_suggested() if self.d1 is not None else {}


def sym_pairs(graph, tol):
    from beadgraph.edits import sym_pairs as sp
    return sp(graph, tol)


def derive_v2(mesh: dict, norm: dict, cfg: dict | None, graph: dict | None, labels: dict | None, *, frame=None,
              fixed_scan=(), bead: str | None = None, index=None, w_clamp: dict | None = None,
              range_guard: dict | None = None, shape_rules: dict | None = None, depth_section: str | None = None,
              section_rules: dict | None = None, pos_u: dict | None = None, tie_node_ids=(),
              virtual_bead: dict | None = None, vb_plan: str = "plate") -> dict:
    """(Backend API) normalized schema 2 selection -> SelectionDerived dict: beads, fixed, warnings, graph block
    (§6.1), graph_algo, slope_suggested, islands_suggested, fixed_ab, params (DoeParamsOut rows) + param_beads.
    ``bead`` is accepted for signature parity (the whole selection is derived — graph beads are cheap).
    v0.21.0: shape_rules(스냅샷 해석값)·range_guard(prep/select/range_guard.json) → ``derive_obj_v2``.
    v0.24.7 DM: depth_section·section_rules(스냅샷 값) → ``derive_obj_v2``, beads[].w_reason{code, text}(옛 스터디도 계산)."""
    from esl.doe import bead_select as bs
    dskw = {"depth_section": depth_section, "section_rules": section_rules} if depth_section is not None else {}
    if pos_u is not None:                                  # v0.24.9 PU: 스냅샷 pos_u 블록(없음 = 호출 불변)
        dskw.update(pos_u=pos_u, tie_node_ids=tie_node_ids)
    if norm.get("virtual_beads"):                          # v0.25.0 VB: 가상 비드 있을 때만(없음 = 호출 불변)
        dskw.update(virtual_bead=virtual_bead, vb_plan=vb_plan, frame=frame, tie_node_ids=tie_node_ids)
    D = derive_obj_v2(mesh, norm, cfg, graph, labels, fixed_node_ids=fixed_scan, index=index, w_clamp=w_clamp,
                      range_guard=range_guard, shape_rules=shape_rules, **dskw)
    doc = D.summary(frame)
    for k in ("rev", "sha256", "mesh_sha256"):
        doc.pop(k, None)
    doc["slope_suggested"] = D.slope_suggested()
    doc["islands_suggested"] = D.islands_suggested()
    doc["fixed_ab"] = bs._fixed_ab(D, frame) if frame is not None else []
    doc["params"] = params_rows_v2(D, cfg)
    doc["param_beads"] = param_beads(D)
    _graph_figures(mesh, D, cfg, doc, frame)               # v0.18.2 BG-D-46 그래프 비드 평면도·단면 자료
    w_reason_rows(D, doc["beads"])
    u_reason_rows(D, doc["beads"])
    if getattr(D, "vbeads", None):                         # v0.25.0 VB §8: 가상 비드 있을 때만 키
        doc["virtual_beads"], vfr = vb_derive_doc(D, cfg, frame)
        if vfr is not None:
            doc["vb_frame"] = vfr
    return doc


def u_reason_rows(D, rows: list[dict]) -> None:
    """v0.24.9 PU §1.2·§4: 비드 행에 u_reason{code, text}(U 행 없을 때만 — U_OFF·pos_u 없음 = 키 없음)."""
    from esl.doe import load_messages
    from esl.morph import section as sec
    msgs = load_messages()["messages"]
    by = {b.id: b for b in D.beads}
    for r in rows:
        b = by.get(r.get("id"))
        if b is None:
            continue
        doc = sec.u_reason_doc(getattr(b, "u_reason", None), msgs, point=bool(getattr(b, "u_point", False)))
        if doc is not None:
            r["u_reason"] = doc


def w_reason_rows(D, rows: list[dict]) -> None:
    """§4.3: derive 응답 비드 행에 w_reason{code, text}(사유 있을 때만 — 문구 = resources/doe_messages.json)."""
    from esl.doe import load_messages
    from esl.morph import section as sec
    msgs = load_messages()["messages"]
    by = {b.id: b for b in D.beads}
    for r in rows:
        b = by.get(r.get("id"))
        if b is None:
            continue
        doc = sec.w_reason_doc(w_reason_of(D, b), msgs)
        if doc is not None:
            r["w_reason"] = doc


# ====================================================================== v0.18.2 평면도·단면 자료(BG-D-46)
def _graph_figures(mesh: dict, D, cfg: dict | None, doc: dict, frame) -> None:
    """derive_v2 문서의 그래프 비드 행에 schema 1 과 같은 그림 자료를 붙임: plan{ring_ab, e_ab, label_ab, tiers}(frame 이 있을 때)·
    section{s, z, dz_dD, ds_dW, dz_dW}(코어 plan_data 가 읽는 키 — esl_beadgraph.md BG-D-46). 단면 미분은 기하 근사(그래프 기저를
    풀지 않음 — 실측 h6 104k 요소 기저 3.9 s 가 derive 시간 제한을 먹음). 그림 자료 실패는 선택 저장·평면도를 막지 않음(비드별 None)."""
    from types import SimpleNamespace

    from esl.doe import bead_select as bs
    ix = D.index
    rows = {r["id"]: r for r in doc.get("beads") or []}
    gbs = [b for b in D.beads if b.src == "graph"]
    if not gbs:
        return
    for b in gbs:
        r = rows.get(b.id)
        if r is None:
            continue
        if frame is not None:
            try:
                r["plan"] = bs._plan_bead(ix, frame, SimpleNamespace(loops=b.loops, bead_mask=b.bead_mask,
                                                                     tiers=[{"k": int(b.tier), "mask": b.floor_mask}]))
            except Exception:                               # noqa: BLE001 - 그림 자료 실패 = 빈 자료
                r["plan"] = {"ring_ab": [], "e_ab": [], "label_ab": None, "tiers": []}
        try:
            r["section"] = graph_section(ix, b, D.graph)
        except Exception:                                   # noqa: BLE001
            r["section"] = None


def _seg_frame(graph: dict, b, ix):
    """단면 기준(BG-D-46): 비드 대표 세그먼트(길이 가장 긴 것, 같으면 작은 id)의 skeleton(그래프 평면 좌표 — p2 = [X·e1, X·e2] − origin)
    호 길이 중점 → (x0 = 그 점에 가장 가까운 비드 바닥 요소 중심, ê_L = 중점 접선(±2 h 구간) 3D). skeleton 이 없으면(plateau 등)
    비드 요소 중심의 평면 주축. 반환 (x0, ê_L, 대표 세그먼트 dict)."""
    fr = graph["frame"]
    n = np.asarray(fr["n0"], dtype=np.float64)
    n = n / max(np.linalg.norm(n), 1e-300)
    e1, e2 = np.asarray(fr["e1"], float), np.asarray(fr["e2"], float)
    org = np.asarray(fr.get("origin", [0.0, 0.0]), float)
    segs = [graph["segments"][i] for i in (b.w_seg_ids if getattr(b, "w_cover", None) is not None else b.seg_ids)]
    rep = sorted(segs, key=lambda sg: (-float(sg.get("length") or 0.0), int(sg["id"])))[0]
    m = np.asarray(b.bead_mask, bool)
    fl = np.asarray(b.floor_mask, bool) if np.asarray(b.floor_mask, bool).any() else m
    Fc = ix.centroid[fl]
    sk = np.asarray(rep.get("skeleton") or [], dtype=np.float64).reshape(-1, 2)
    if sk.shape[0] >= 2:
        d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(sk, axis=0), axis=1))]
        mid = 0.5 * d[-1]
        pm = np.array([np.interp(mid, d, sk[:, 0]), np.interp(mid, d, sk[:, 1])])
        h = float(fr.get("h_mm") or ix.h_med)
        a = np.array([np.interp(max(0.0, mid - 2 * h), d, sk[:, k]) for k in (0, 1)])
        c = np.array([np.interp(min(d[-1], mid + 2 * h), d, sk[:, k]) for k in (0, 1)])
        t2 = c - a
        if np.linalg.norm(t2) > 1e-9:
            eL = t2[0] * e1 + t2[1] * e2
            eL = eL - (eL @ n) * n
            eL /= max(np.linalg.norm(eL), 1e-300)
            P2 = np.c_[Fc @ e1, Fc @ e2] - org
            k = int(np.argmin(np.linalg.norm(P2 - pm, axis=1) + 1e-12 * np.arange(P2.shape[0])))
            return Fc[k], eL, rep, n
    C = ix.centroid[m]
    c_mean = C.mean(axis=0)
    P = C - c_mean
    P = P - np.outer(P @ n, n)
    _w, V = np.linalg.eigh(P.T @ P)
    eL = V[:, 2] - (V[:, 2] @ n) * n
    eL /= max(np.linalg.norm(eL), 1e-300)
    if eL[int(np.argmax(np.abs(eL)))] < 0:
        eL = -eL
    t = (Fc - c_mean) @ eL
    k = int(np.argmin(np.abs(t - np.median(t)) + 1e-9 * np.arange(t.size)))
    return Fc[k], eL, rep, n


def graph_section(ix, b, graph: dict | None = None) -> dict | None:
    """그래프 비드 단면(schema 1 ``bead_select._section`` 과 같은 키 — BG-D-46): ``_seg_frame`` 의 점 x0 를 지나고 ê_L 에 수직인
    평면과 메시의 교선 → s(mm, ê_W = n̂ × ê_L, x0 = 0) · z(mm, 깊어짐 + = 대표 세그먼트 부모 바닥 level 에서 비드 바닥 level 쪽으로).
    범위 = x0 를 지나는 비드 요소 교선 연속 구간(틈 ≤ 3 h) ± 3 h, |z| ≤ 3 D + 10 h. 미분 = 그림용 기하 근사(기저 아님): 비드 구간
    안 점 dz_dD[tier] = clip(z / D_nom, 0, 1)(바닥 1·사면 비례·판 0), W 가 변수면 ds_dW = 비드 구간 안 점 ½·clip((s − s_c)/(½ 바닥 폭),
    −1, 1)(바닥 폭 = 바닥 깊이 점 구간, s_c = 그 중앙)·dz_dW = 0. 비드 요소가 없으면 None."""
    m = np.asarray(b.bead_mask, bool)
    if not m.any() or graph is None:
        return None
    x0, eL, rep, n = _seg_frame(graph, b, ix)
    eW = np.cross(n, eL)
    fls = {int(f["id"]): f for f in graph.get("floors") or []}
    lv_b = float((fls.get(int(rep["floor"])) or {}).get("level", x0 @ n))
    par = int(rep.get("parent", -1))
    lv_p = float((fls.get(int(graph["segments"][par]["floor"])) or {}).get("level", lv_b)) if par >= 0 else lv_b
    sign = 1.0 if lv_b >= lv_p else -1.0
    nd = sign * n
    from esl.view3d import triangulate
    tris = triangulate(ix.conn, np.where(ix.is_quad, 4, 3)).astype(np.int64)
    X = ix.X
    sd = (X - x0) @ eL
    a, bb, c = sd[tris[:, 0]], sd[tris[:, 1]], sd[tris[:, 2]]
    cross = (np.minimum(np.minimum(a, bb), c) < 0) & (np.maximum(np.maximum(a, bb), c) > 0)
    tri_e = np.repeat(np.arange(ix.conn.shape[0]), np.where(ix.is_quad, 2, 1))
    tt, te = tris[cross], tri_e[cross]
    pts, wts, inb = [], [], []
    for (i0, i1) in ((0, 1), (1, 2), (2, 0)):
        u, v = tt[:, i0], tt[:, i1]
        su, sv = sd[u], sd[v]
        mm = (su < 0) != (sv < 0)
        pts.append(np.column_stack([u[mm], v[mm]]))
        wts.append(su[mm] / (su[mm] - sv[mm]))
        inb.append(m[te[mm]])
    E = np.vstack(pts)
    L = np.concatenate(wts)
    IB = np.concatenate(inb)
    if not E.shape[0]:
        return None
    key = np.minimum(E[:, 0], E[:, 1]) * (1 << 32) + np.maximum(E[:, 0], E[:, 1])
    order = np.lexsort((~IB, key))                          # 같은 모서리 = 비드 요소 쪽 우선
    key, E, L, IB = key[order], E[order], L[order], IB[order]
    _u, first = np.unique(key, return_index=True)
    E, L, IB = E[first], L[first], IB[first]
    Q = X[E[:, 0]] * (1 - L[:, None]) + X[E[:, 1]] * L[:, None]
    s = (Q - x0) @ eW
    h = float(ix.h_med)
    sb = np.sort(s[IB])
    if not sb.size:
        return None
    i0 = int(np.argmin(np.abs(sb)))                         # x0 를 지나는 비드 연속 구간(틈 ≤ 3 h)
    lo = hi = i0
    while lo > 0 and sb[lo] - sb[lo - 1] <= 3.0 * h:
        lo -= 1
    while hi < sb.size - 1 and sb[hi + 1] - sb[hi] <= 3.0 * h:
        hi += 1
    smin, smax = float(sb[lo]) - 3.0 * h, float(sb[hi]) + 3.0 * h
    z = sign * (Q @ n - lv_p)
    lim = 3.0 * float(b.D_nom or 0.0) + 10.0 * h
    keep = (s >= smin) & (s <= smax) & (np.abs(z) <= lim)
    E, L, s, z = E[keep], L[keep], s[keep], z[keep]
    o = np.lexsort((z, s))
    E, L, s, z = E[o], L[o], s[o], z[o]
    out = {"s": [_r(v, 3) for v in s], "z": [_r(v, 3) for v in z], "at_node_id": None, "at_ab": None, "dz_dD": {},
           "ds_dW": [], "dz_dW": []}
    Dn = float(b.D_nom or 0.0)
    inb = (s >= smin + 3.0 * h - 1e-9) & (s <= smax - 3.0 * h + 1e-9)
    if Dn > 0 and "D" in (b.vars or []):
        out["dz_dD"][str(int(b.tier))] = [_r(x, 4) for x in np.where(inb, np.clip(z / Dn, 0.0, 1.0), 0.0)]
        # v0.24.7 DM-12 그림 교정: 평면 성분 ds_dD — DF = 깊이면 0·입구 cotθ 바깥, D(입구 고정) = 깊이면 가장자리 안쪽
        from esl.morph import section as sec
        bz = inb & (z > 1e-9)
        flz = inb & (z >= Dn - 0.25 * h)
        cot = None
        if bz.any() and flz.any():
            cot = max(((float(s[bz].max()) - float(s[bz].min())) - (float(s[flz].max()) - float(s[flz].min())))
                      / (2.0 * Dn), 0.0)
        fside = _fig_side(graph, b, rep, n)
        out["ds_dD"] = {str(int(b.tier)): sec.fig_ds_dD(s, np.where(inb, z, 0.0),
                                                       Dn, cot, sec.SECTION_PLANS["graph"]["fig"],
                                                       side=fside if getattr(b, "depth_kind", "D") == "DF" else None,
                                                       floor_mode=getattr(b, "depth_kind", "D") == "DF")}
    if "W" in (b.vars or []) and Dn > 0 and getattr(b, "w_side", None) == "one":   # v0.24.7 W1: 열린 쪽 +1·고정 쪽 0
        from esl.morph import section as sec
        fside = _fig_side(graph, b, rep, n)
        if fside is not None:
            out["ds_dW"] = sec.fig_ds_dW1(s, np.where(inb, z, 0.0), Dn, fside)
            out["dz_dW"] = [0.0] * int(s.size)
    elif "W" in (b.vars or []) and Dn > 0:
        fl = inb & (z >= Dn - 0.25 * h)
        if fl.any():
            a0, a1 = float(s[fl].min()), float(s[fl].max())
            sc, hw = 0.5 * (a0 + a1), max(0.5 * (a1 - a0), 1e-9)
            out["ds_dW"] = [_r(x, 4) for x in np.where(inb, 0.5 * np.clip((s - sc) / hw, -1.0, 1.0), 0.0)]
            out["dz_dW"] = [0.0] * int(s.size)
    return out


def _fig_side(graph: dict, b, rep: dict, n) -> int | None:
    """단면 그림 s 축(ê_W = n̂ × ê_L, ê_L = 대표 세그먼트 골격 진행 방향)에서 열린 쪽 부호: 골격 σ(+1 = 진행 방향 왼쪽) ×
    (판 평면 e1 × e2 와 n̂ 같은 방향이면 +1). 대표 세그먼트가 한쪽 입구가 아니면 None(양쪽)."""
    sd = (getattr(b, "seg_side", None) or {}).get(int(rep["id"]))
    if not sd:
        return None
    fr = graph["frame"]
    hand = float(np.cross(np.asarray(fr["e1"], float), np.asarray(fr["e2"], float)) @ np.asarray(n, float))
    return int(sd) * (1 if hand >= 0 else -1)


def param_beads(D) -> list[dict]:
    """params.json ``beads`` rows (same shape as the core BD_MATRIX file)."""
    return [{"id": b.id, "name": b.name, "kind": "select", "src": getattr(b, "src", "elems"),
             "n_tiers": len(b.tiers), "W_nom": _r(getattr(b, "W_nom", None)), "W_min": _r(getattr(b, "W_min", None)),
             "W_max": _r(getattr(b, "W_max", None)), "blend_mm": _r(getattr(b, "blend_mm", None)),
             "warnings": b.warnings} for b in D.beads] + vb_bead_rows(D)


def derive_obj_v2(mesh: dict, norm: dict, cfg: dict | None, graph: dict | None, labels: dict | None, *,
                  fixed_node_ids=(), index=None, mesh_sha256: str | None = None,
                  w_clamp: dict | None = None, range_guard: dict | None = None,
                  shape_rules: dict | None = None, depth_section: str | None = None,
                  section_rules: dict | None = None, pos_u: dict | None = None, tie_node_ids=(),
                  virtual_bead: dict | None = None, vb_plan: str = "plate", frame=None) -> GraphDerived:
    """normalized schema 2 selection -> GraphDerived (arrays — worker basis / tests).
    v0.24.7 DM: depth_section(스냅샷 값, None = 옛 = entry_fixed)·section_rules(스냅샷 depth_section_rules) — floor_fixed 면
    계획 표 graph 행(esl.morph.section) 열로 D = 패키지 kind DF(입구 노드 없으면 D + DS_FALLBACK), W 없는 한쪽 입구 비드 = W1.
    v0.21.0(새 스냅샷만): shape_rules.w_partial → W 를 S_W 에만(SH-4~9), shape_rules.range_guard 가 있으면 range_guard 표
    (``range_guard_table``)를 맞는 변수에 적용(SH-15·16) — 맞지 않으면 guard.state unchecked + RG_UNCHECKED."""
    from esl.doe import bead_select as bs
    from esl.mesh import features
    from esl.morph import section as sec
    sc = select_cfg(cfg)
    wp = _w_partial(shape_rules)
    ds = sec.resolve(depth_section)
    spl = sec.row_plan(ds, "graph")
    if sec.is_floor(ds) and section_rules is None:      # 스냅샷 rules 없음 = 지금 설정(DEFAULTS 거울)
        from esl.doe import settings as _settings
        section_rules = (_settings(cfg if isinstance(cfg, dict) and "select" in cfg else None)
                         ["depth_section_rules"])
    elif sec.is_floor(ds):
        section_rules = _rules_full(section_rules)
    ix = index or bs.mesh_index(mesh)
    if graph is not None and labels is not None:
        g2, l2 = edited_graph(graph, labels, (norm.get("graph") or {}).get("edits"), mesh)
    else:
        g2, l2 = _empty_graph(mesh)
    # elems beads: schema 1 derive (island limit = graph value 60 — BG-D-36), same fixed / exclude
    elem = [b for b in norm["beads"] if b["src"] == "elems"]
    d1 = None
    cfg1 = _island_cfg(cfg, float(sc["graph"]["island"]["max_mm"]))
    if elem:
        n1 = {"schema_version": 1, "feature_angle_deg": norm["feature_angle_deg"],
              "beads": [{k: v for k, v in b.items() if k != "src"} for b in elem],
              "fixed_user": norm["fixed_user"], "exclude": norm["exclude"]}
        d1 = bs.derive_obj(mesh, n1, cfg1, fixed_node_ids=fixed_node_ids, index=ix, mesh_sha256=mesh_sha256,
                           with_section=False,
                           **({"depth_section": ds, "section_rules": section_rules} if sec.is_floor(ds) else {}))
        fixed_mask = d1.fixed_mask
        fixed = d1.fixed
        warns = list(d1.warnings)
    else:
        nid = ix.node_id
        fids = np.asarray(list(fixed_node_ids), dtype=np.int64)
        fixed_scan = np.isin(nid, fids) if fids.size else np.zeros(ix.n_nodes, bool)
        fu = bs.elems_of(ix, norm["fixed_user"], where="fixed_user")
        fixed_user = np.zeros(ix.n_nodes, bool)
        fixed_user[ix.elem_nodes(fu)] = True
        fixed_mask = fixed_scan | fixed_user
        src = ("scan+user" if fixed_scan.any() and fixed_user.any() else "scan" if fixed_scan.any()
               else "user" if fixed_user.any() else "none")
        fixed = {"scan_n": int(fixed_scan.sum()), "user_n": int(fixed_user.sum()), "source": src}
        warns = []
    excl = bs.elems_of(ix, norm["exclude"], where="exclude")
    rg = sc["range"]
    h = float(g2["frame"]["h_mm"])
    wfl = max(2.0 * h, 6.0)
    beads = []
    d1b = {b.id: b for b in (d1.beads if d1 is not None else [])}
    for b in norm["beads"]:
        if b["src"] == "elems":
            bd = d1b[b["id"]]
            bd.src = "elems"
            beads.append(bd)
            continue
        ids, zones, net = _resolve_segs(g2, l2, b["segs"], b["id"])
        gb = GraphBead(b["id"], b["name"])
        gb.seg_ids, gb.zone_ids, gb.network = ids, zones, int(g2["segments"][ids[0]]["network"])
        gb.is_net = bool(net)
        gb.tier = int(g2["segments"][ids[0]]["tier"])
        gb.vars = b.get("vars") or (["D"] if net else _possible_vars(g2, ids, wp))
        gb.hold_fixed = int(b.get("hold_fixed", 1))
        D, W = _bead_nominals(g2, l2, b, wp)
        gb.D_nom, gb.W_nom = D, (W if "W" in gb.vars else None)
        gb.w_seg_ids, gb.w_cover = (w_segs(g2, ids) if wp else list(ids)) if gb.W_nom is not None else [], None
        if wp and gb.W_nom is not None and len(gb.w_seg_ids) < len(ids):   # SH-5·§3.2: W 부분 비드
            ln = {s: float(g2["segments"][s]["length"] or 1.0) for s in ids}
            gb.w_cover = _r(sum(ln[s] for s in gb.w_seg_ids) / sum(ln.values()))
            gb.warnings.append({"code": "BG_W_PARTIAL", "level": "info", "bead": b["id"], "n_w": len(gb.w_seg_ids),
                                "n_seg": len(ids), "cover": gb.w_cover,
                                "no_w": sorted(int(g2["segments"][s]["anchor"]) for s in ids if s not in gb.w_seg_ids)})
        Ds = [float(g2["segments"][s]["D"]) for s in ids]
        if max(Ds) - min(Ds) > float(sc["graph"]["sym_tol_mm"]):
            gb.warnings.append({"code": "BG_GROUP_NOMINAL_SPREAD", "bead": b["id"], "min": _r(min(Ds)), "max": _r(max(Ds))})
        lo = max(D * (1.0 - float(rg["depth_rel"])), float(rg["min_step_mm"]))
        hi = D * (1.0 + float(rg["depth_rel"]))
        gb.range_default = {"D": [_r(min(lo, hi)), _r(hi)], "W": None}
        fd_hi = D * (1.0 + float(rg["depth_max_rel"]))
        if gb.W_nom is not None:
            fd_hi = min(fd_hi, (gb.W_nom - wfl) / 2.0)
        gb.range_feasible = {"D": [_r(min(float(rg["min_step_mm"]), min(lo, hi))), _r(max(fd_hi, hi))], "W": None}
        if gb.W_nom is not None:
            Wn = gb.W_nom
            gb.range_default["W"] = [_r(Wn * (1.0 - float(rg["width_rel"]))), _r(Wn * (1.0 + float(rg["width_rel"])))]
            gb.range_feasible["W"] = [_r(min(2.0 * D + wfl, Wn * (1.0 - float(rg["width_rel"])))),
                                      _r(max(Wn * (1.0 + float(rg["width_rel"])), Wn * (1.0 + float(rg["width_max_rel"]))))]
        gb.depth_kind, gb.w_side, gb.section, gb.w_reason = "D", None, None, None
        if spl["compose"] != "none" or spl["one_side"] != "none":     # v0.24.7 DM floor_fixed(계획 열)
            _floor_fixed_bead(gb, b, g2, l2, mesh, spl, sec, section_rules or {}, sc, wp, net, wfl, D, lo, hi)
        gb.range_basis = copy.deepcopy(gb.range_default)   # ramp / corner guard frozen here (BG-D-24), even if clamped
        sm = np.isin(l2["segment"], ids) | (np.isin(l2["junction_zone"], zones) & (l2["junction_zone"] >= 0))
        sm &= ~excl
        gb.bead_mask = sm
        gb.floor_mask = sm & (l2["cls"] == 0)
        gb.bead_nodes = ix.elem_nodes(sm)
        gb.n_hat = np.asarray(g2["frame"]["n0"], float)
        loops, _ = features.boundary_loops(ix, sm)
        gb.loops = loops
        gb.blend_mm = 0.0
        gb.w_enabled = gb.W_nom is not None
        gb.fixed_in_bead_n = int(fixed_mask[gb.bead_nodes].sum())
        gb.boundary_nodes = np.unique(np.concatenate([lp["nodes"] for lp in loops])) if loops else np.zeros(0, np.int64)
        beads.append(gb)
    D = GraphDerived(norm, bs.selection_sha256(norm), beads, fixed, warns, ix, mesh_sha256, g2, l2, d1)
    fu_nodes = ix.elem_nodes(bs.elems_of(ix, norm["fixed_user"], where="fixed_user"))
    _apply_w_clamp(D, norm, w_clamp, cfg, user_free=not excl.any() and np.asarray(fu_nodes).size == 0,
                   ds_view=_ds_view(depth_section, section_rules))
    D.fixed_mask = fixed_mask
    D.exclude_mask = excl
    D.norm_cfg_tol = float(sc["graph"]["sym_tol_mm"])
    D.cfg1 = cfg1
    D.shape_rules = shape_rules
    D.df_guard_q = _df_guard_q(_guard_rules(shape_rules))   # DM-35(floor_fixed DF 항목만 씀)
    D.depth_section = depth_section                    # 스냅샷 값 그대로(None = 키 없음)
    D.section_rules = section_rules
    D.section_plan = spl
    if spl["one_side"] != "none":
        _tie_mixed(D, sc)
    # v0.24.9 PU §1: 위치 변수 U(스냅샷 pos_u 블록 + 계획 표 pos 열 = pkg_u 일 때만 — 블록 없음 = 속성 없음·바이트 불변)
    D.pos_u = _pos_u_block(pos_u)
    D.tie_idx = np.zeros(0, np.int64)
    if pos_u is not None:
        for gb in beads:
            if getattr(gb, "src", "graph") == "graph" and hasattr(gb, "seg_ids"):
                gb.u_ok, gb.u_reason = False, "U_OFF"
    if D.pos_u is not None and sec.pos_plan("graph") == "pkg_u" and graph is not None:
        tids = np.asarray(tie_node_ids if tie_node_ids is not None else (), np.int64).reshape(-1)
        D.tie_idx = np.flatnonzero(np.isin(ix.node_id, tids)) if tids.size else np.zeros(0, np.int64)
        _pos_u_beads(D, mesh, sc, cfg)
    if _guard_rules(shape_rules) is not None:          # v0.21.0 SH-14·15: 준비 표 적용(맞지 않는 변수 = unchecked)
        apply_range_guard(D, range_guard, cfg)
    if norm.get("virtual_beads"):                      # v0.25.0 VB §2~4(가상 비드 있을 때만 — 없음 = 속성 없음·바이트 불변)
        tids = np.asarray(tie_node_ids if tie_node_ids is not None else (), np.int64).reshape(-1)
        tix = np.flatnonzero(np.isin(ix.node_id, tids)) if tids.size else np.zeros(0, np.int64)
        D.vb_blk = vb_block(virtual_bead, cfg)
        virtual_beads(D, mesh, D.vb_blk, vb_plan=vb_plan, frame=frame, tie_idx=tix, flip_deg=vb_flip_deg(cfg, shape_rules),
                      cfg=cfg)
        if _guard_rules(shape_rules) is not None:      # 준비 표 후보 아님 — BD_MATRIX guard_selection 이 켜진 A 만 점검
            for vb in D.vbeads:
                if vb.ok:
                    vb.guard = {VB_TYPE: _unchecked(vb.range_basis[VB_TYPE])}
    return D


def _pos_u_block(pos_u) -> dict | None:
    """스냅샷 pos_u 블록 → 해석값(enabled 거짓·블록 없음 = None). 빠진 키 = 지금 설정(DEFAULTS 거울)."""
    if not isinstance(pos_u, dict) or pos_u.get("enabled") is False:
        return None
    from esl.doe import DEFAULTS
    return {**DEFAULTS["pos_u"], **{k: v for k, v in pos_u.items() if k != "schema"}}


def _nom(b, typ: str) -> float:
    """v0.24.9 PU §1.3-1: 변수 공칭 — D → D_nom, W → W_nom, U → 0.0(위치 — 지금 형상)."""
    if typ == "U":
        return 0.0
    return b.D_nom if typ == "D" else b.W_nom


def _types(b) -> list[str]:
    """비드의 변수 종류: 선택 vars(D·W) + U(행 있을 때 — 선택 vars 로 켜고 끄지 않음, PU-10)."""
    return list(b.vars or []) + (["U"] if getattr(b, "u_ok", False) else [])


def _pos_u_beads(D, mesh, sc, cfg) -> None:
    """§1.2·§1.3 그래프 비드마다 U 사유(첫 일치)·W_ref·feasible(부호별)·기본 범위·dir·dir_text 코드·도심 → 대칭 묶기 거울(PU-11)."""
    from beadgraph.morph import u_closed, u_gaps, u_orient
    from beadgraph.zones import Mesh, bead_zones
    from scipy.spatial import cKDTree

    from esl.morph import section as sec
    pu = D.pos_u
    g2, l2 = D.graph, D.labels
    X = np.asarray(mesh["x0"], np.float64)
    C = _conn(mesh)
    h = float(g2["frame"]["h_mm"])
    M = Mesh(g2, l2, X, C)
    fx_idx = np.flatnonzero(D.fixed_mask)
    held_set = np.union1d(fx_idx, D.tie_idx)
    rng = float(sc["hold"]["ring_mm"]) + float(sc["hold"]["blend_mm"])
    segs = g2["segments"]
    for gb in D.beads:
        if getattr(gb, "src", "graph") != "graph" or not hasattr(gb, "seg_ids"):
            continue
        ids = gb.seg_ids
        net = bool(getattr(gb, "is_net", False))
        sk_n = {s_: len(segs[s_].get("skeleton") or []) for s_ in ids}
        area_t = all(segs[s_]["type"] in ("area", "plateau") for s_ in ids)
        point = not area_t and all(sk_n[s_] < 2 for s_ in ids)
        s2 = [s_ for s_ in ids if segs[s_]["entry_width"] is not None and sk_n[s_] >= 2]
        facts = {"network": net, "area": area_t or point, "s2": len(s2),
                 "closed": any(u_closed(segs[s_], h) for s_ in s2)}
        if not s2 and not facts["network"] and not facts["area"]:
            osd = _bg().one_side(g2, l2, X, C, ids, min_nodes=3)
            facts["s1"] = sum(1 for s_ in ids if osd[s_]["ok"])
        if s2 and not facts["closed"] and held_set.size:
            E = bead_zones(M, s2, gb.zone_ids, "D")["E"]
            if E.any():
                d_, _ = cKDTree(M.P[held_set]).query(M.P[E])
                facts["held"] = float((d_ < rng).mean()) > float(pu["hold_frac_max"])
        code = sec.u_reason(facts)
        gb.u_ok, gb.u_reason, gb.u_point = code is None, code, bool(point)
        if code is not None:
            continue
        gp = u_gaps(g2, l2, X, C, s2, gb.zone_ids, fixed=fx_idx, hold_nodes=D.tie_idx,
                    range_rel=float(pu["range_rel"]), cfg=morph_cfg(cfg))
        W_ref = float(gp["w_ref"])
        fe = sec.u_feasible(W_ref, gp["g_plus"], gp["g_minus"], float(pu["max_rel"]), float(pu["gap_rel"]))
        de = sec.u_default(W_ref, fe, float(pu["range_rel"]))
        gb.range_default["U"] = [_r(de[0]), _r(de[1])]
        gb.range_feasible["U"] = [_r(fe[0]), _r(fe[1])]
        gb.range_basis["U"] = [_r(de[0]), _r(de[1])]
        orient = u_orient({s_["id"]: s_ for s_ in segs}, s2)
        turn = sum(float(orient.get(s_, 1)) * sec.skeleton_turn_deg(segs[s_]["skeleton"]) for s_ in s2)
        gb.u_seg_ids, gb.u_w_ref, gb.u_dir = list(s2), W_ref, gp["dir"]
        gb.u_dir_code = sec.u_dir_code(gp["dir"] or [1.0, 0.0], turn)
        gb.u_c = sec.u_centroid([segs[s_]["skeleton"] for s_ in s2])
        gb.u_gaps = {"g_plus": gp["g_plus"], "g_minus": gp["g_minus"]}
        if len(s2) < len(ids):
            ln = {s_: float(segs[s_]["length"] or 1.0) for s_ in ids}
            gb.warnings.append({"code": "PU_PARTIAL", "level": "info", "bead": gb.id,
                                "cover": _r(sum(ln[s_] for s_ in s2) / sum(ln.values()))})
    _tie_u(D, h)


def _tie_u(D, h: float) -> None:
    """PU-11 대칭 묶음 U: 구성원 모두 U 가능 ∧ 쌍별 거울 |내적| ≥ cos 30° ∧ 도심 거리 ≥ h → 대표 비드 u_signs, 아니면 묶음 전체 U 없음 +
    대표 비드 u_reason U_TIE_MIXED."""
    from esl.morph import section as sec
    by = {b.id: b for b in D.beads}
    for grp in D.norm.get("ties") or []:
        bs_ = [by[x] for x in grp if x in by]
        if not bs_ or not any(getattr(b, "u_ok", False) for b in bs_):
            continue
        ok = all(getattr(b, "u_ok", False) for b in bs_)
        signs = sec.u_mirror_signs([(getattr(b, "u_c", None), getattr(b, "u_dir", None)) for b in bs_], h) if ok else None
        if signs is None:
            for b in bs_:
                b.u_ok = False
                b.u_reason = None if b is not bs_[0] else "U_TIE_MIXED"
                for k in ("range_default", "range_feasible", "range_basis"):
                    getattr(b, k).pop("U", None)
            if bs_[0].u_reason is None:
                bs_[0].u_reason = "U_TIE_MIXED"
            continue
        bs_[0].u_signs = {var_name(b.id, "U"): int(sg) for b, sg in zip(bs_, signs)}


def _entry_any(g2, l2, mesh, ids, zones) -> bool:
    """비드 입구 노드(E = 벽 ∩ 부모 바닥) ≥ 1 — DF 적용 조건(§1.4)."""
    from beadgraph.zones import Mesh, bead_zones
    M = Mesh(g2, l2, np.asarray(mesh["x0"], np.float64), _conn(mesh))
    return bool(bead_zones(M, ids, zones, "D")["E"].any())


def _floor_fixed_bead(gb, b, g2, l2, mesh, spl, sec, rules, sc, wp, net, wfl, D, lo, hi) -> None:
    """v0.24.7 DM(§1.2.1·§1.6·§2.1·§4) 그래프 비드 1개: D 종류(DF|대체 D), W1(S_2 = ∅ ∧ S_1), floor_fixed feasible, W 사유."""
    bg = _bg()
    rg = sc["range"]
    ids, zones = gb.seg_ids, gb.zone_ids
    mn = int(rules["one_side_min_nodes"])
    osd = bg.one_side(g2, l2, np.asarray(mesh["x0"], np.float64), _conn(mesh), ids, min_nodes=mn)
    runs = [float(osd[s_]["run"]) / max(float(g2["segments"][s_]["D"]), 1e-9) for s_ in ids
            if osd[s_]["run"] is not None and osd[s_]["run"] > 0]
    cot = float(np.median(runs)) if runs else None
    entry = _entry_any(g2, l2, mesh, ids, zones) if spl["compose"] == "pkg_df" else False
    gb.depth_kind = "DF" if entry else "D"
    applied = gb.depth_kind == "DF"
    gb.section = {"mode": "floor_fixed", "cot_deg": (sec._deg_of_cot(cot) if cot else None), "applied": applied}
    if not applied:
        gb.section["reason"] = "W_ENTRY_NONE"
        gb.warnings.append({"code": "DS_FALLBACK", "bead": b["id"], "var": var_name(b["id"], "D"),
                            "reason": "W_ENTRY_NONE"})
    # W: S_2 (지금 규칙) / W1 (S_2 = ∅ 일 때만)
    s2 = w_segs(g2, ids)
    ln = {s_: float(g2["segments"][s_]["length"] or 1.0) for s_ in ids}
    s1 = [s_ for s_ in ids if g2["segments"][s_]["entry_width"] is None and osd[s_]["ok"]]
    s1_edge = [s_ for s_ in ids if osd[s_]["reason"] == "EDGE"]
    user_vars = b.get("vars")
    one = False
    if spl["one_side"] == "pkg_w1" and not net and not s2 and s1 and gb.W_nom is None and \
            (user_vars is None or "W" in user_vars) and (wp or len(s1) == len(ids)):
        one = True
        lw = np.array([ln[s_] for s_ in s1])
        W1 = float(np.sum(lw * np.array([float(osd[s_]["width"]) for s_ in s1])) / lw.sum())
        F1 = float(np.sum(lw * np.array([float(osd[s_]["floor"]) for s_ in s1])) / lw.sum())
        gb.vars = sorted(set(gb.vars) | {"W"})
        gb.W_nom, gb.F_nom, gb.w_side = W1, F1, "one"
        gb.w_seg_ids = sorted(s1)
        gb.w_cover = _r(sum(ln[s_] for s_ in s1) / sum(ln.values())) if len(s1) < len(ids) else None
        gb.one_side = {int(g2["segments"][s_]["anchor"]): osd[s_] for s_ in s1}
        Wr = float(rg["width_rel"])
        gb.range_default["W"] = [_r(W1 * (1.0 - Wr)), _r(W1 * (1.0 + Wr))]
        f_lo, f_hi = sec.w1_feasible(W1, F1, wfl, float(rg["width_max_rel"]))
        gb.range_feasible["W"] = [_r(min(f_lo, W1 * (1.0 - Wr))), _r(max(f_hi, W1 * (1.0 + Wr)))]
    if not one and gb.W_nom is None and "W" in gb.vars:     # 사용자 W 지정이지만 W·W1 모두 불가(후보 표 시험 포함)
        gb.vars = [v for v in gb.vars if v != "W"]
    # feasible D (입구 확장 상한)
    if gb.W_nom is not None and gb.w_side is None:
        parts = [(gb.W_nom, 2.0)]
        Wn = gb.W_nom
        gb.range_feasible["W"][0] = _r(min(sec.w_lo_floor_fixed(Wn, D, cot, wfl), Wn * (1.0 - float(rg["width_rel"]))))
    elif one:
        parts = [(gb.W_nom, 1.0)]
    else:
        parts = []
    fd_hi = sec.feasible_open_cap(D, parts, cot, float(rg["depth_max_rel"]), float(rg["width_max_rel"]))
    gb.range_feasible["D"] = [gb.range_feasible["D"][0], _r(max(fd_hi, hi))]
    one_segs = [s_ for s_ in ids if osd[s_]["ok"]]
    gb.seg_side = {int(s_): int(osd[s_]["side"]) for s_ in one_segs}           # 그림 fig side·W1 ds_dW
    geo_segs = sorted(s1) if one else one_segs
    gb.open_c, gb.open_v = sec.open_side_geo([(g2["segments"][s_].get("skeleton") or [], osd[s_]["side"])
                                              for s_ in geo_segs])             # §4.4 거울·DS_ONE_SIDE 방위
    if one or (applied and one_segs):
        fx = {k: int(sum(osd[s_]["fixed"][k] for s_ in one_segs)) for k in ("child", "shared", "junction", "own_wall")}
        gb.warnings.append({"code": "DS_ONE_SIDE", "level": "info", "bead": b["id"],
                            "segs": sorted(int(g2["segments"][s_]["anchor"]) for s_ in one_segs),
                            "open_side_deg": sec.open_side_deg(gb.open_v), "fixed": fx, "steep_deg": None})
    facts = {"src": "graph", "floor_fixed": True, "user_off": user_vars is not None and "W" not in user_vars,
             "network": net, "area": all(g2["segments"][s_]["type"] in ("area", "plateau") for s_ in ids),
             "merged": any(g2["segments"][s_].get("merged") for s_ in ids), "s2": len(s2), "s1": len(s1),
             "s1_edge": bool(s1_edge) and not s1, "w_partial": wp,
             "partial": (0 < len(s2) < len(ids)) if s2 else (0 < len(s1) < len(ids))}
    gb.w_reason = None if "W" in gb.vars else sec.w_reason(facts)


def _tie_mixed(D, sc) -> None:
    """§4.4(DM-15·DM-C1-5) floor_fixed 대칭 묶음: 구성원 W 종류(양쪽·한쪽·없음)가 다르거나, 모두 W1 인데 열린 쪽이 대칭 거울이
    아니거나(``section.tie_mirror_ok`` — 대표·구성원 골격 도심 차 m 에 대한 거울 내적 ≥ cos 30°, 도심 거리 < h = 판정 불가) W1 공칭
    차 > 2·sym_tol → 그 묶음 W 없음 + W_TIE_MIXED(422 아님, D 묶음 유지)."""
    from esl.morph import section as sec
    tol = float(sc["graph"]["sym_tol_mm"])
    h = float(D.graph["frame"]["h_mm"])
    by = {b.id: b for b in D.beads}
    for grp in D.norm.get("ties") or []:
        bs_ = [by[x] for x in grp if x in by]
        kinds = {("W" in b.vars, getattr(b, "w_side", None)) for b in bs_}
        mixed = len(kinds) > 1
        if not mixed and all(getattr(b, "w_side", None) == "one" for b in bs_):
            ws = [b.W_nom for b in bs_]
            mixed = max(ws) - min(ws) > 2.0 * tol or \
                not sec.tie_mirror_ok([(getattr(b, "open_c", None), getattr(b, "open_v", None)) for b in bs_], h)
        if mixed and any(getattr(b, "w_side", None) == "one" for b in bs_):
            for b in bs_:
                b.vars = [v for v in b.vars if v != "W"]
                b.W_nom, b.w_side, b.w_reason = None, None, "W_TIE_MIXED"
                b.range_default["W"] = b.range_feasible["W"] = None


def w_reason_of(derived, bead) -> str | None:
    """API·params.json 용 W 사유(§4.3): floor_fixed 비드는 derive 값, 그 밖(entry_fixed·옛 스터디)은 지금 조건으로 계산."""
    from esl.morph import section as sec
    if getattr(bead, "src", "graph") != "graph" or not hasattr(bead, "seg_ids"):   # elems(schema 1 포함 — §4.1)
        if getattr(bead, "w_reason", None) is not None or getattr(bead, "w_enabled", False):
            return getattr(bead, "w_reason", None)
        return sec.w_reason({"src": "elems", "open_boundary": bool(getattr(bead, "open", False)),
                             "width_undefined": not bool(getattr(bead, "open", False))})
    if getattr(bead, "w_reason", None) is not None or "W" in (bead.vars or []):
        return getattr(bead, "w_reason", None)
    g = derived.graph
    ids = bead.seg_ids
    s2 = w_segs(g, ids)
    user = (next((b for b in derived.norm["beads"] if b["id"] == bead.id), {}) or {}).get("vars")
    facts = {"src": "graph", "floor_fixed": False, "user_off": user is not None and "W" not in user,
             "network": any("network" in x for x in next((b for b in derived.norm["beads"] if b["id"] == bead.id),
                                                          {}).get("segs", [])),
             "area": all(g["segments"][s_]["type"] in ("area", "plateau") for s_ in ids),
             "merged": any(g["segments"][s_].get("merged") for s_ in ids), "s2": len(s2), "s1": 0,
             "w_partial": _w_partial(getattr(derived, "shape_rules", None)), "partial": 0 < len(s2) < len(ids)}
    return sec.w_reason(facts)


def _empty_graph(mesh):
    """GRAPH_FAILED stand-in: no segments (elems beads only)."""
    m = int(np.asarray(mesh["elem_type"]).size)
    lab = {k: np.full(m, -1, np.int32) for k in ("cls", "floor", "segment", "transition", "island", "junction_zone",
                                                  "tier")}
    g = {"segments": [], "junction_zones": [], "networks": [], "islands": [], "rules": 0,
         "frame": {"h_mm": 1.0, "n0": [0.0, 0.0, 1.0]}}
    return g, lab


def _island_cfg(cfg, max_mm):
    """bead_doe settings (or a select section) with select.island.max_mm = the graph value (elems beads of schema 2)."""
    from esl.doe import _deep_merge
    if cfg is not None and isinstance(cfg.get("select"), dict):
        c = copy.deepcopy(cfg)
    else:
        c = {"select": copy.deepcopy(cfg or {})}
    c["select"] = _deep_merge(c["select"], {"island": {"max_mm": float(max_mm)}})
    return c


# ====================================================================== params / basis / checks
def var_name(bid: str, typ: str) -> str:
    return f"{bid.upper()}_{typ}"


def _tie_of(norm) -> dict:
    out = {}
    for grp in norm.get("ties") or []:
        for x in grp:
            out[x] = grp
    return out


def params_rows_v2(derived: GraphDerived, cfg: dict | None = None) -> list[dict]:
    from esl.doe import bead_select as bs
    out = []
    if derived.d1 is not None:
        out += bs.params_table(derived.d1, getattr(derived, "cfg1", cfg))
    tie = _tie_of(derived.norm)
    for b in derived.beads:
        if b.src != "graph":
            continue
        grp = tie.get(b.id)
        if grp and grp[0] != b.id:
            continue                                   # tied: the smallest id carries the variable
        for typ in b.vars:
            nom = _nom(b, typ)
            out.append({"name": var_name(b.id, typ), "type": typ, "bead": b.id, "tier": b.tier, "nominal": _r(nom),
                        "feasible": list(b.range_feasible[typ]), "feasible_source": "estimate",
                        "default_range": list(b.range_default[typ]),
                        "use_default": not any(w.get("code") == "BG_SEGMENT_SHORT" and w.get("var") ==
                                               var_name(b.id, typ) for w in b.warnings),
                        "group_members": [var_name(x, typ) for x in (grp or [b.id])]})
            gd = (getattr(b, "guard", None) or {}).get(typ)
            if gd is not None:                         # v0.21.0 SH-16(새 스냅샷 그래프 변수만)
                out[-1]["guard"] = copy.deepcopy(gd)
                if gd.get("state") == "blocked":
                    out[-1]["use_default"] = False
            if typ == "W" and getattr(b, "w_cover", None) is not None:
                out[-1]["w_segs"] = [derived.graph["segments"][s]["anchor"] for s in b.w_seg_ids]
                out[-1]["w_cover"] = b.w_cover
            if typ == "D" and getattr(b, "section", None) is not None:      # v0.24.7 DM(floor_fixed 만)
                out[-1]["section"] = copy.deepcopy(b.section)
            if typ == "W" and getattr(b, "w_side", None) == "one":
                out[-1]["w_side"] = "one"
        if getattr(b, "u_ok", False):                  # v0.24.9 PU §1.3·§4: U 행(공칭 0, 기본 꺼짐)
            out.append(u_row(b, grp))
    for vb in getattr(derived, "vbeads", None) or []:  # v0.25.0 VB §5.1: A 행(놓을 수 있는 가상 비드만)
        if vb.ok:
            out.append(vb_row(vb, cfg))
    out.sort(key=lambda r: r["name"])
    return out


def u_row(b, grp) -> dict:
    """params[] U 행 {name, type U, bead, tier, nominal 0, unit mm, feasible, feasible_source, default_range, use_default false,
    group_members, dir{xi, eta}, dir_text, w_ref, (group_signs), (guard)}."""
    from esl.doe import message
    d = list(getattr(b, "u_dir", None) or [0.0, 0.0])
    r = {"name": var_name(b.id, "U"), "type": "U", "bead": b.id, "tier": b.tier, "nominal": 0.0, "unit": "mm",
         "feasible": list(b.range_feasible["U"]), "feasible_source": "estimate",
         "default_range": list(b.range_default["U"]), "use_default": False,
         "group_members": [var_name(x, "U") for x in (grp or [b.id])],
         "dir": {"xi": _r(d[0]), "eta": _r(d[1])}, "dir_text": message(b.u_dir_code), "w_ref": _r(b.u_w_ref)}
    if getattr(b, "u_signs", None):
        r["group_signs"] = dict(b.u_signs)
    gd = (getattr(b, "guard", None) or {}).get("U")
    if gd is not None:
        r["guard"] = copy.deepcopy(gd)
    return r


def basis_v2(mesh: dict, derived: GraphDerived, cfg: dict | None = None):
    """-> bead_select.Basis (same npz / bin formats). Graph variables carry ``zone`` (allowed nodes, BG-D-34) and
    ``graph_info``; BD_MATRIX errors BG_BASIS_LEAK / BG_ACHIEVED_MISMATCH raise EslError."""
    from beadgraph.checks import achieved, basis_leak, strict_allowed_nodes

    from esl.doe import bead_select as bs
    bg = _bg()
    mc = morph_cfg(cfg)
    vars_ = []
    if derived.d1 is not None:
        B1 = bs.basis(mesh, derived.d1, getattr(derived, "cfg1", cfg), index=derived.index)
        vars_ += B1.vars
    rows = {r["name"]: r for r in params_rows_v2(derived, cfg)}
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C = _conn(mesh)
    fx = np.flatnonzero(derived.fixed_mask)
    g, l = derived.graph, derived.labels
    excl = getattr(derived, "exclude_mask", np.zeros(C.shape[0], bool))
    lx = {k: np.where(excl, -1, v).astype(np.int32) if k in ("segment", "junction_zone") else v for k, v in l.items()}
    tie = _tie_of(derived.norm)
    by = {b.id: b for b in derived.beads}
    pk_list = []
    for b in derived.beads:
        if b.src != "graph":
            continue
        for typ in _types(b):
            pk = _pkg_item(derived, b, typ)                                   # v0.24.7 DM: DF·W1(floor_fixed)
            pk["typ"] = typ
            pk_list.append(pk)
    ranges = {}
    for p in pk_list:
        b0 = by[p["bead"]]
        carrier = (tie.get(b0.id) or [b0.id])[0]
        r = rows[var_name(carrier, p["typ"])]
        nom = _nom(b0, p["typ"])
        rb = (getattr(by.get(carrier), "range_basis", None) or {}).get(p["typ"])
        lo, hi = (float(v) for v in (rb or r["default_range"]))   # original default range (BD_LOADS clamp keeps L)
        if p["typ"] == "U":                            # PU §1.3-3: 공칭 0, 부호별(비대칭) 범위 그대로 — 간격 κ·가드가 끝을 봄
            ranges[p["name"]] = [lo, hi]
            continue
        ext = max(abs(hi - float(r["nominal"])), abs(lo - float(r["nominal"])))
        ranges[p["name"]] = [nom - ext, nom + ext]
    gB = bg.basis(g, lx, X, [{k: v for k, v in p.items() if k != "typ"} for p in pk_list], ranges, cfg=mc,
                  fixed=fx, elems=C) if pk_list else []
    # Verifier fix v0.17.0: allowed nodes from the graph labels (not the basis zone) — a node of an element outside A_v
    # is outside (BG-D-32 leak check here, BG-D-34 design check via design_checks_v2)
    strict = strict_allowed_nodes(g, lx, X, C, gB) if gB else {}
    leak = basis_leak(gB, g, lx, X, C) if gB else []
    if leak:
        w = leak[0]
        _bad("BG_BASIS_LEAK", f"{w['var']}: 허용 구역 밖 기저 {w['n']}개(최대 {w['max_mm']:.3g})", var=w["var"], n=w["n"],
             max_mm=w["max_mm"])
    tol = float(mc["morph"]["achieved_tol_mm"])
    for v in gB:
        b0 = by[next(p["bead"] for p in pk_list if p["name"] == v["name"])]
        for ww in v["info"]["warnings"]:
            ww = dict(ww)
            ww.pop("level", None)
            ww["bead"] = b0.id
            if ww not in b0.warnings:
                b0.warnings.append(ww)
        if v["kind"] in ("DF", "W1"):                   # v0.24.7 DM §1.6.3·§2.4: steep_deg(DF 뒤)·DS_HOLD_PINCH
            if v["kind"] == "DF" and v["info"].get("steep_deg") is not None:
                for ww in b0.warnings:
                    if ww.get("code") == "DS_ONE_SIDE":
                        ww["steep_deg"] = list(v["info"]["steep_deg"])
            pn = int(v["info"].get("hold_pinch_n") or 0)
            if pn > 0:
                hp = {"code": "DS_HOLD_PINCH", "level": "info", "bead": b0.id, "var": v["name"], "n": pn}
                if hp not in b0.warnings:
                    b0.warnings.append(hp)
        if v["info"].get("short"):
            ws_ = {"code": "BG_SEGMENT_SHORT", "bead": b0.id, "var": v["name"],
                   "length_mm": _r(sum(float(g["segments"][s]["length"] or 0.0)
                                       for s in _var_segs(b0, {"W1": "W", "DF": "D"}.get(v["kind"], v["kind"])))),
                   "ramp_mm": _r(v["info"]["ramp_mm"])}
            b0.warnings.append(ws_)
            from esl.morph import section as _sec
            if v["kind"] == "U" and _sec.u_short_seg(True, ws_["length_mm"], ws_["ramp_mm"]):   # v0.24.9 INT-8: U 행에도
                b0.warnings.append({"code": "U_SHORT_SEG", "level": "info", "bead": b0.id, "var": v["name"],
                                    "length_mm": ws_["length_mm"], "ramp_mm": ws_["ramp_mm"],
                                    "ratio": _r(_sec.u_motion_ratio(v["vec"]))})
            continue
        lo, hi = ranges[v["name"]]
        for end in (lo, hi):
            x = bg.morph(X, [v], {v["name"]: end})
            err = achieved(g, lx, X, x, [v], {v["name"]: end}).get(v["name"])
            lim = tol if v["kind"] in ("D", "DF") else 1e-3
            if err is not None and err > lim:
                _bad("BG_ACHIEVED_MISMATCH", f"{v['name']}: 달성 오차 {err:.3g} mm", var=v["name"], err_mm=err)
        if v["kind"] == "U" and float(v["info"].get("tie_max") or 0.0) > 1e-6:   # PU-14: 강제 hold 뒤에도 tie 이동
            _bad("BG_ACHIEVED_MISMATCH", f"{v['name']}: 지그 tie 노드 이동 {v['info']['tie_max']:.3g}", var=v["name"],
                 err_mm=float(v["info"]["tie_max"]))
    derived.graph_basis = gB
    # wrap: ties -> one variable = sum of the tied beads' bases (same delta)
    n = X.shape[0]
    by_name = {v["name"]: v for v in gB}
    for name, row in rows.items():
        if row["bead"] not in by or by[row["bead"]].src != "graph":
            continue
        members = row["group_members"]
        sgn = row.get("group_signs") or {}                 # PU-11 대칭 U 묶음: 구성원 부호 합(거울 대칭 이동)
        full = np.zeros((n, 3))
        zone = np.zeros(n, bool)
        allowed = np.zeros(n, bool)
        for m in members:
            v = by_name.get(m)
            if v is None:
                continue
            full[v["idx"]] += float(sgn.get(m, 1)) * v["vec"]
            zone[v["zone"]] = True
            allowed |= strict[m]
        idx = np.flatnonzero(np.any(full != 0.0, axis=1))
        b0 = by[row["bead"]]
        vars_.append({"name": name, "type": row["type"], "bead": row["bead"], "tier": row["tier"],
                      "members": members, "nominal": float(row["nominal"]), "n_hat": b0.n_hat,
                      "R": (by_name[name]["info"].get("blend_mm") if name in by_name else None),
                      "idx": idx.astype(np.int32), "vec": full[idx], "zone": np.flatnonzero(zone).astype(np.int64),
                      "allowed": np.flatnonzero(allowed).astype(np.int64)})
    vars_ += vb_basis_vars(derived)                    # v0.25.0 VB §4.2: hinge 변수(가상 비드 있을 때만)
    vars_.sort(key=lambda v: v["name"])
    B = bs.Basis(vars_, n, derived.sha256)
    B.graph_algo = GRAPH_ALGO
    return B


def _var_segs(b, typ: str) -> list:
    """기저에 넘길 세그먼트: W = S_W(SH-6 — v0.20.0 규칙에서는 S 전체와 같음), D = S."""
    if typ == "W" and getattr(b, "w_seg_ids", None):
        return b.w_seg_ids
    if typ == "U" and getattr(b, "u_seg_ids", None):              # v0.24.9 PU: S_U(양쪽 입구 구간)
        return b.u_seg_ids
    return b.seg_ids


def clamp_w_ranges(derived, rc_warnings: list[dict]) -> list[dict]:
    """통합 v0.17.0(계약 §12 BG-X-1): 그래프 비드(src graph) **W** 변수의 기본 범위 끝이 뒤집히면(``bead_select.range_check`` 의
    ``SELECT_RANGE_INVERTS{var, usable}``) 기본 범위를 그 usable 로 줄이고, 그 비드의 SELECT_RANGE_INVERTS 를 정보
    ``BG_RANGE_CLAMPED{bead, var, from[lo, hi], to[lo, hi], inverted[lo, hi], level info}`` 로 바꾼다. 기저·램프(기본 범위 끝에서
    고정, BG-D-24)·feasible 은 그대로(줄인 범위는 원래 범위 안). usable 이 공칭을 포함하지 못하면(한쪽 끝이 공칭에 붙음) 줄이지 않고
    SELECT_RANGE_INVERTS 를 그대로 둔다. elems 비드·D 변수·schema 1 = 손대지 않음. rc_warnings 는 제자리(줄인 변수 항목 제거).
    반환 = 단 BG_RANGE_CLAMPED 목록."""
    tie = _tie_of(derived.norm)
    by = {b.id: b for b in derived.beads if getattr(b, "src", None) == "graph"}
    names = {}
    for b in by.values():
        if "W" in (b.vars or []) and (b.range_default or {}).get("W"):
            grp = tie.get(b.id)
            if not grp or grp[0] == b.id:
                names[var_name(b.id, "W")] = b
    out, keep = [], []
    for w in rc_warnings:
        b = names.get(w.get("var")) if w.get("code") == "SELECT_RANGE_INVERTS" else None
        u = w.get("usable") if b is not None else None
        if b is None or not (isinstance(u, list) and len(u) == 2 and float(u[0]) < float(b.W_nom) < float(u[1])):
            keep.append(w)
            continue
        old = list(b.range_default["W"])
        b.range_default["W"] = [_r(float(u[0])), _r(float(u[1]))]
        c = {"code": "BG_RANGE_CLAMPED", "level": "info", "bead": b.id, "var": w["var"], "from": old,
             "to": list(b.range_default["W"]), "inverted": list(w.get("inverted") or [])}
        b.warnings[:] = [x for x in b.warnings if x is not w and not (x.get("code") == "SELECT_RANGE_INVERTS"
                                                                       and x.get("var") == w["var"])]
        b.warnings.append(c)
        out.append(c)
    rc_warnings[:] = keep + out
    return out


def ramp_short(graph_vars: list[dict], spec_params: list[dict], cfg: dict | None = None) -> list[dict]:
    """BG_RAMP_SHORT{var, L_mm, need_mm}: a user range end beyond the default range the ramp was frozen for (warning,
    runs anyway — min 3h kept). graph_vars = basis.json graph_vars [{name, kind, nominal, ramp_mm}]."""
    k = float(graph_cfg(cfg)["morph"]["ramp_k"])
    gv = {v["name"]: v for v in graph_vars or []}
    out = []
    for p in spec_params or []:
        v = gv.get(p.get("name"))
        if v is None:
            continue
        need_ext = max(abs(float(p["hi"]) - v["nominal"]), abs(float(p["lo"]) - v["nominal"]))
        if v["kind"] == "W":
            need_ext /= 2.0
        need = k * need_ext
        if need > float(v["ramp_mm"]) + 1e-9:
            out.append({"code": "BG_RAMP_SHORT", "var": p["name"], "L_mm": _r(v["ramp_mm"]), "need_mm": _r(need)})
    return out


def design_checks_v2(derived: GraphDerived, B) -> dict:
    """SR-D-37 features (elems beads + graph islands rim / interior), SR-D-38 cross (W bases on other beads) and the
    BG-D-34 allowed-zone masks per graph variable (``outside`` — chk_o*)."""
    from esl.doe import bead_select as bs
    from esl.morph import core as mc
    out: dict = {}
    feats = []
    if derived.d1 is not None:
        feats += [{"bead": b.id, "k": f["k"], "rim": np.asarray(f["rim"], np.int64),
                   "interior": np.asarray(f["interior"], np.int64)} for b in derived.d1.beads
                  for f in getattr(b, "features", [])]
    if feats:
        out["features"] = feats
    ix = derived.index
    if len(derived.beads) >= 2:
        reg = {}
        for b in derived.beads:
            if b.src == "graph":
                reg[b.id] = np.union1d(b.boundary_nodes, ix.elem_nodes(b.floor_mask))
            else:
                reg[b.id] = np.union1d(b.boundary_nodes, ix.elem_nodes(b.floor_mask))
        cross = mc.cross_footprint(B.vars, reg)
        if cross:
            out["cross"] = cross
    # BG-D-34 allowed nodes per variable (Verifier fix v0.17.0): graph variables = the label-based strict set
    # (``allowed`` — independent of the basis zone; ``zone`` only for a basis built before the fix); elems variables
    # (schema 1 derive inside schema 2) = their own basis support, so a design that changes both kinds is judged on the
    # union (no spurious BG_OUTSIDE_MOVED on the elems bead's nodes).
    o = []
    graph_vars = any("allowed" in v or "zone" in v for v in B.vars)
    for v in B.vars if graph_vars else ():          # elems beads only: no outside check (chk_o* bytes as before)
        if "allowed" in v or "zone" in v:
            z = np.asarray(v["allowed"] if "allowed" in v else v["zone"], np.int64)
        else:
            z = np.unique(np.asarray(v["idx"], np.int64))
        o.append({"var": v["name"], "nominal": float(v["nominal"]), "zone": z, "n": B.n_nodes})
    if o:
        out["outside"] = o
    _ = bs
    return out


# ====================================================================== auto seed (BG-D-20)
def auto_seed(graph: dict, labels: dict, cfg: dict | None = None, *, exclude_segs=None):
    """-> (selection schema 2 normalized, sym_pairs [[anchor, anchor]], warnings). Beads: each ring side; each leg /
    comb / channel / pocket segment (vertical channels separately — D5); a flare goes with the channel of its floor
    (the Y zone between them included); area floors (plateaus) D only; islands, lances, junction zones, base: none.
    Order (tier, anchor); beyond max_beads dropped with AUTO_TOO_MANY_BEADS. Ties are only suggested (sym_pairs).
    exclude_segs (v0.18.0 SG-D-20d) = segment ids outside the evaluation region — never seeded (None = all, as before)."""
    sc = select_cfg(cfg)
    ex = set(int(x) for x in exclude_segs or ())
    segs = [s for s in graph["segments"] if s["type"] != "base" and s["id"] not in ex]
    used = set()
    groups = []
    by_side = {}
    for s in segs:
        if s["side"]:
            by_side.setdefault((s["floor"], s["side"]), []).append(s["id"])
    for (_f, _side), ids in by_side.items():
        groups.append(sorted(ids))
        used |= set(ids)
    for s in segs:
        if s["id"] in used:
            continue
        if s["type"] == "flare":
            ch = [x["id"] for x in segs if x["floor"] == s["floor"] and x["type"] == "channel" and x["id"] not in used]
            if ch:
                continue                                 # joined with the channel below
        grp = [s["id"]]
        if s["type"] == "channel":
            grp += [x["id"] for x in segs if x["floor"] == s["floor"] and x["type"] == "flare" and x["id"] not in used]
        groups.append(sorted(grp))
        used |= set(grp)
    groups.sort(key=lambda g: (graph["segments"][g[0]]["tier"], min(graph["segments"][x]["anchor"] for x in g)))
    warns = []
    mx = int(sc["max_beads"])
    if len(groups) > mx:
        warns.append({"code": "AUTO_TOO_MANY_BEADS", "n": len(groups), "max": mx})
        groups = groups[:mx]
    beads = []
    for i, gids in enumerate(groups, start=1):
        beads.append({"id": f"b{i}", "src": "graph",
                      "segs": [{"anchor": graph["segments"][x]["anchor"]} for x in gids]})
    sel = {"schema_version": 2, "graph": {"sha256": graph_sha_of(graph), "rules": graph["rules"], "edits": {}},
           "beads": beads, "ties": []}
    sp = [[graph["segments"][a]["anchor"], graph["segments"][b]["anchor"]]
          for a, b in sym_pairs(graph, float(sc["graph"]["sym_tol_mm"]))]
    return sel, sp, warns


def auto_doc_v2(selection_norm: dict, sha: str, sym: list, hints: list, warnings: list, *, mesh_sha256=None,
                graph_sha=None, source: str = "graph", fixed: dict | None = None) -> dict:
    """auto_selection.json (schema 2). v0.18.0 select_base step: source "graph" (auto) | "fixed_transfer" (manual seed =
    no beads + fixed_user, SG-D-16 iii) and ``fixed`` = {source "a_transfer"|"none", method, n_nodes} — keys only for step."""
    doc = {"schema": AUTO_SCHEMA_V2, "source": source, "selection": selection_norm, "sha256": sha, "sym_pairs": sym,
           "hints": hints, "warnings": warnings, "mesh_sha256": mesh_sha256, "graph_sha256": graph_sha}
    if fixed is not None:
        doc["fixed"] = fixed
    return doc


def fixed_seed_v2(graph: dict | None, fixed_user: dict, cfg: dict | None = None) -> tuple[dict, str]:
    """v0.18.0 SG-D-14b·16 iii seed without beads (manual, or auto with no seedable bead): schema 2 selection
    {beads [], ties [], fixed_user, exclude {}} (+ graph block when classified). Not passed through ``normalize_v2``
    (that needs ≥ 1 bead) — the frontend adds beads and saves through the normal path. sha = canonical selection sha.
    ``cfg`` = the study's bead_doe settings (feature_angle_deg = the study's select value, not the default)."""
    from esl.doe import bead_select as bs
    sc = select_cfg(cfg)
    sel = {"schema_version": SCHEMA_VERSION, "feature_angle_deg": float(sc["feature_angle_deg"]), "beads": [],
           "ties": [], "fixed_user": bs._norm_set(fixed_user, "fixed_user", 10_000_000),
           "exclude": bs._norm_set(None, "exclude", 10_000_000)}
    if graph is not None:
        sel["graph"] = {"sha256": graph_sha_of(graph), "rules": int(graph["rules"]), "edits": {}}
    return sel, bs.selection_sha256(sel)


def wall_islands(graph: dict, labels: dict, mesh: dict, max_mm: float) -> list[dict]:
    """v0.18.0 SG-X-2 (V-SG-R1): island-sized raised floor pieces that the classifier did NOT make islands (kind "area",
    island -1, area ≤ max_mm²) and whose neighbours are wall elements owned by a segment — a boss straddling a channel
    wall swallowed into the wall. Morphing that segment moves the boss with the wall, so ``BG_OUTSIDE_MOVED`` cannot see
    it. -> [{floor, segments[], plan[2]}] (sorted by floor id). Cheap: only the few small "area" pieces are examined."""
    cand = [f for f in graph.get("floors") or [] if f.get("kind") == "area" and int(f.get("island", -1)) < 0
            and float(f.get("area") or 0.0) <= float(max_mm) ** 2]
    if not cand:
        return []
    C = np.asarray(_conn(mesh), dtype=np.int64)
    cls, fl, seg = (np.asarray(labels[k]) for k in ("cls", "floor", "segment"))
    n = np.asarray(mesh["x0"]).shape[0]
    X = np.asarray(mesh["x0"], dtype=np.float64)
    out = []
    for f in cand:
        e = fl == int(f["id"])
        if not e.any():
            continue
        on = np.zeros(n + 1, bool)
        Ce = C[e]
        on[Ce[Ce >= 0]] = True
        nb = on[np.where(C >= 0, C, n)].any(axis=1) & ~e
        w = nb & (cls == 1) & (seg >= 0)                    # CLS wall = 1, owned by a segment
        if not w.any() or w.sum() < 0.5 * nb.sum():
            continue
        p = X[Ce[Ce >= 0]].mean(axis=0)
        out.append({"floor": int(f["id"]), "segments": sorted({int(s) for s in seg[w]}),
                    "plan": [round(float(p[0]), 3), round(float(p[1]), 3)]})
    return out


def region_marks(graph: dict, labels: dict, region, frac: float = 0.5) -> dict:
    """v0.18.0 SG-D-20d: segments / islands (lances included) whose elements are more than ``frac`` outside the
    evaluation region (bool per element) -> {segments[id], islands[id]} (sorted) — excluded from the auto seed and shown
    grey in the tree; painting them by hand stays allowed."""
    r = np.asarray(region, bool)
    out = {}
    for key, lab in (("segments", "segment"), ("islands", "island")):
        L = np.asarray(labels[lab])
        ids = []
        for v in np.unique(L[L >= 0]):
            m = L == v
            if float((~r[m]).sum()) > float(frac) * float(m.sum()):
                ids.append(int(v))
        out[key] = sorted(ids)
    return out


def write_auto_v2(path: str, doc: dict, guard=None) -> str:
    from esl.doe.bead_auto import auto_bytes
    g = guard or (lambda p: p)
    with open(g(path), "wb") as fh:
        fh.write(auto_bytes(doc))
    return doc["sha256"]


def slope_hints(graph: dict, extract_doc: dict | None, mesh: dict, labels: dict) -> list[dict]:
    """AUTO_SLOPE_DIFF hints (paicad flanks — never prefilled): the graph bead nearest each paicad bead bottom centre,
    relative difference of the flank width (entry − floor) / 2 vs paicad nominal flank."""
    if not extract_doc:
        return []
    out = []
    fr = graph["frame"]
    e1, e2 = np.asarray(fr["e1"]), np.asarray(fr["e2"])
    o = np.asarray(fr.get("origin", [0.0, 0.0]))
    segs = [s for s in graph["segments"] if s["skeleton"] and s["entry_width"] and s["floor_width"]]
    for k, b in enumerate(extract_doc.get("beads") or [], start=1):
        nomv = b.get("nominal") or {}
        flank = nomv.get("flank_width") or nomv.get("flank") or nomv.get("slope_width")
        c = b.get("center") or nomv.get("center")
        if not flank or not c or not segs:
            continue
        p = np.array([np.asarray(c, float) @ e1, np.asarray(c, float) @ e2]) - o
        best = min(segs, key=lambda s: float(np.min(np.hypot(*(np.asarray(s["skeleton"]) - p).T))))
        mine = (float(best["entry_width"]) - float(best["floor_width"])) / 2.0
        rel = abs(mine - float(flank)) / max(float(flank), 1e-9)
        out.append({"code": "AUTO_SLOPE_DIFF", "level": "info", "bead": b.get("id", f"p{k}"),
                    "segment_anchor": best["anchor"], "rel": _r(rel, 3)})
    return out


def report_line(derived_doc: dict) -> list[str]:
    """보고서 select 절 한 줄(§6.3): 그래프 비드는 "세그먼트 n·접합 구역 m·묶음 출처(그래프)"."""
    out = []
    for b in derived_doc.get("beads") or []:
        if b.get("src") == "graph":
            out.append(f"{b['id']} {b.get('name') or ''}: 세그먼트 {b.get('n_segments', 0)} · 접합 구역 "
                       f"{b.get('n_junction_zones', 0)} · 묶음 출처(그래프)")
    return out


# ====================================================================== v0.21.0 range guard (esl_bead_shape_v021.md §4)
# 판정·이분·조합·예산·진단 = 모드 무관 ``esl.morph.range_guard``(원본), 영향 요소 품질 = ``mesh_quality.guard_probe``.
# 이 절은 그래프 비드 쪽 연결만: 후보 기저(BD_LOADS 표) · derive 표 적용 · BD_MATRIX 보충 · 파일. 새 스냅샷
# (shape_rules.range_guard 있음)에서만 불린다 — 키 없는 스냅샷은 w_clamp·clamp_w_ranges·range_check 그대로(SH-25).
def _guard_rules(rules) -> dict | None:
    """해석된 shape_rules 의 range_guard 블록(꺼짐·없음 = None)."""
    rg = rules.get("range_guard") if isinstance(rules, dict) else None
    if not isinstance(rg, dict) or rg.get("enabled") is False:
        return None
    return rg


def _no_guard(rules):
    if not rules:
        return rules
    r = dict(rules)
    r["range_guard"] = None
    return r


def _crit(rg: dict, cfg) -> dict:
    """accept 기준(SH-10): flip_deg = 블록 값(해석 때 select.quality.flip_deg 복사), 없으면 select.quality.flip_deg."""
    flip = rg.get("flip_deg")
    if flip is None:
        flip = select_cfg(cfg)["quality"]["flip_deg"]
    return {"flip_deg": float(flip), "jac_min": rg.get("jac_min"), "tria_angle_min_deg": rg.get("tria_angle_min_deg"),
            "area_ratio_min": rg.get("area_ratio_min"), "max_new_fail_ratio": rg.get("max_new_fail_ratio")}


def _canon(v):
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    return str(v)


def _guard_cfg_key(cfg, rules, ds_view: dict | None = None) -> str:
    """표 머리 cfg_sha256(§4.3): select 설정 키(``_cfg_key``) + 형상 규칙(w_partial·기준·steps·min_keep_frac·combo — 예산 제외).
    v0.24.7 DM §2.2: floor_fixed 면 ``ds``(section.hash_view) 키 추가(entry_fixed = 보기·sha 불변)."""
    rg = _guard_rules(rules) or {}
    view = {"select": _cfg_key(cfg), "w_partial": _w_partial(rules),
            "range_guard": _canon({"crit": _crit(rg, cfg) if rg else None, "steps": rg.get("steps"),
                                   "min_keep_frac": rg.get("min_keep_frac"), "combo": rg.get("combo")})}
    if ds_view is not None:
        view["ds"] = _canon(ds_view)
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _mask_sha(mask) -> str:
    idx = np.flatnonzero(np.asarray(mask, bool)).astype("<i8")
    return hashlib.sha256(idx.tobytes()).hexdigest()


def _var_key(g: dict, b, typ: str) -> dict:
    """표 항목 key{kind, segs[[앵커, 요소 수]…], w_segs(W 만), hold}. v0.24.7 DM: floor_fixed 비드(section 있음) = + ds,
    한쪽 입구 W = kind W1."""
    if typ == VB_TYPE:                                  # v0.25.0 VB: 가상 비드 항목 key(선택 표에만 — 준비 표 후보 아님)
        return {"kind": VB_TYPE, "vbead": b.id}
    kind = "W1" if typ == "W" and getattr(b, "w_side", None) == "one" else typ
    k = {"kind": kind, "segs": _seg_keys(g, b.seg_ids), "hold": int(b.hold_fixed) if typ != "U" else 1}
    if typ == "W":
        k["w_segs"] = _seg_keys(g, _var_segs(b, "W"))
    if typ == "U":                                      # v0.24.9 PU §1.3-4: U 후보 key(+ u_segs)
        k["u_segs"] = _seg_keys(g, _var_segs(b, "U"))
    if getattr(b, "section", None) is not None:
        k["ds"] = "floor_fixed"
    return k


def _pkg_item(D, b, typ: str) -> dict:
    """패키지 basis() 항목(basis_v2·후보 기저 공용): kind = D|W, floor_fixed 면 DF(깊이면 폭 유지)·W1(한쪽 입구)."""
    kind = typ
    if typ == "D" and getattr(b, "depth_kind", "D") == "DF":
        kind = "DF"
    elif typ == "W" and getattr(b, "w_side", None) == "one":
        kind = "W1"
    pk = {"name": var_name(b.id, typ), "kind": kind, "segs": _var_segs(b, typ), "zones": b.zone_ids,
          "hold": b.hold_fixed, "bead": b.id}
    if kind == "U":                                     # v0.24.9 PU §1.1·PU-14: hold 강제 + 지그 tie(hold_nodes)·간격·가드 기준
        pu = getattr(D, "pos_u", None) or {}
        pk.update(hold=1, hold_nodes=[int(i) for i in np.asarray(getattr(D, "tie_idx", ()), np.int64)],
                  range_rel=float(pu["range_rel"]), gap_rel=float(pu["gap_rel"]))
        q = getattr(D, "df_guard_q", None)              # 품질 기준 = range guard 기준(켬일 때만 — DF 와 같은 장치)
        if q:
            pk.update(q)
        return pk
    if kind == "W1":
        pk.update(ramp="end", min_nodes=int(D.section_rules["one_side_min_nodes"]))
    if kind == "DF":                                    # DM-30·31 입구 평활·이웃 간격(스냅샷 depth_section_rules)
        r = _rules_full(D.section_rules)
        pk.update(entry_smooth_rel=float(r["entry_smooth_rel"]), entry_gap_rel=float(r["entry_gap_rel"]))
        q = getattr(D, "df_guard_q", None)              # DM-35 입구 가드 품질 기준 = range guard 기준(켬일 때만)
        if q:
            pk.update(q)
    return pk


def _df_guard_q(rg) -> dict | None:
    """DF 입구 가드에 넘기는 품질 기준(DM-35): range guard 블록(켬)의 jac_min·tria_angle_min_deg → 패키지 DF 항목 키
    guard_jac_min·guard_tri_angle_min_deg(값 None 인 키는 뺌). 꺼짐·없음 = None(가드 = 뒤집힘·넓이 비·오목만)."""
    if not isinstance(rg, dict):
        return None
    q = {"guard_jac_min": rg.get("jac_min"), "guard_tri_angle_min_deg": rg.get("tria_angle_min_deg")}
    q = {k: float(v) for k, v in q.items() if v is not None and not isinstance(v, bool)}
    return q or None


def _rules_full(rules) -> dict:
    """스냅샷 depth_section_rules + 빠진 키는 지금 설정(DEFAULTS 거울) — 개정 전 키 없는 스냅샷 호환."""
    return {**_section_rules_now(None), **(rules or {})}


def _kj(k) -> str:
    return json.dumps(k, sort_keys=True, separators=(",", ":"))


class _Local:
    __slots__ = ("C", "E", "base", "et", "vs", "x0")

    def __init__(self, E, x0, C, et, vs, base):
        self.E, self.x0, self.C, self.et, self.vs, self.base = E, x0, C, et, vs, base


class _Prober:
    """시험 모핑(x = x0 + Σ Δ·B_v — ``bead_select.morph`` 와 같은 덧셈) + 영향 요소(노드 변위 > U_EPS 인 노드를 가진 요소 —
    ``affected_elems`` 규칙) 품질 탐침을 기저 지지 둘레 국부 메시에서."""

    def __init__(self, mesh: dict, crit: dict, qcfg: dict | None):
        from esl.doe.bead_select import U_EPS
        self.eps = float(U_EPS)
        self.X = np.asarray(mesh["x0"], dtype=np.float64)
        self.C = np.asarray(mesh["conn"], dtype=np.int64)
        self.et = np.asarray(mesh["elem_type"]).astype(int)
        self.q = self.et == 4
        self.crit, self.qcfg = crit, qcfg

    def support(self, idxs) -> np.ndarray:
        mk = np.zeros(self.X.shape[0], bool)
        for idx in idxs:
            mk[np.asarray(idx, np.int64)] = True
        C = self.C
        m = mk[C[:, 0]] | mk[C[:, 1]] | mk[C[:, 2]]
        m[self.q] |= mk[C[self.q, 3]]
        return np.flatnonzero(m)

    def local(self, vs) -> _Local:
        from esl.doe import mesh_quality as mq
        E = self.support([v[0] for v in vs])
        Ce, ete = self.C[E], self.et[E]
        qe = ete == 4
        nodes = np.unique(np.concatenate([Ce[:, :3].ravel(), Ce[qe, 3]]))
        loc = np.full(self.X.shape[0], -1, np.int64)
        loc[nodes] = np.arange(nodes.size)
        Cl = np.empty_like(Ce)
        Cl[:, :3] = loc[Ce[:, :3]]
        Cl[:, 3] = np.where(qe, loc[np.maximum(Ce[:, 3], 0)], Cl[:, 2])
        x0l = self.X[nodes]
        lv = []
        for item in vs:
            idx, vec = item[0], item[1]
            li = loc[np.asarray(idx, np.int64)]
            k = li >= 0                                   # 요소 없는 노드는 품질과 무관
            t = {"idx": li[k], "vec": np.asarray(vec, np.float64)[k], "nominal": 0.0}
            if len(item) > 2 and item[2] is not None:      # v0.25.0 VB: hinge 항(g, c, v₀) — 탐침 값 = v₀ + Δ
                g, c, v0 = item[2]
                t.update(form="hinge", g=np.asarray(g, np.float64)[k], c=float(c), nominal=float(v0))
            lv.append(t)
        return _Local(E, x0l, Cl, ete, lv, mq.guard_base(x0l, Cl, ete, np.arange(E.size), self.qcfg))

    def ok(self, L: _Local, dvs) -> tuple:
        from esl.morph import range_guard as rgm
        pr = self.probe(L, dvs)
        c = self.crit
        ok, reason, value = rgm.accept(pr, c)
        n = {"inverted": pr["inverted"], "jac": pr["jac_bad_new"], "tri_angle": pr["tri_bad_new"],
             "warp": pr.get("warp_bad_new")}.get(reason)
        return ok, reason, (None if value is None else _r(value, 6)), n

    def probe(self, L: _Local, dvs, warp_max_deg=None) -> dict:
        """시험 모핑 1회 → ``guard_probe`` 결과(warp_max_deg 를 주면 warp_bad_new·warp_max 도 — v0.25.0 VB 정보, 판정 안 씀)."""
        from esl.doe import mesh_quality as mq
        from esl.morph import core as mcore
        x = np.array(L.x0, dtype=np.float64, copy=True)
        for t, dv in zip(L.vs, dvs):
            if dv != 0.0 and t["idx"].size:
                li, du = mcore.basis_term(t, t["nominal"] + dv)   # 항 함수 한 곳(linear = dv·vec 바이트 같음)
                x[li] += du
        u = np.linalg.norm(x - L.x0, axis=1) > self.eps
        C = L.C
        q = L.et == 4
        am = u[C[:, 0]] | u[C[:, 1]] | u[C[:, 2]]
        am[q] |= u[C[q, 3]]
        idx = np.flatnonzero(am)
        c = self.crit
        wkw = {"warp_max_deg": float(warp_max_deg)} if warp_max_deg is not None else {}
        return mq.guard_probe(L.x0, x, C, L.et, idx, flip_deg=c["flip_deg"], jac_min=c["jac_min"],
                              tria_angle_min_deg=c["tria_angle_min_deg"], qcfg=self.qcfg,
                              base=L.base if idx.size == am.size else None, **wkw)


def _pv(v) -> tuple:
    """기저 변수 → 탐침 항목 (idx, vec[, (g, c, v₀)]) — hinge(v0.25.0 VB)만 셋째 값."""
    if v.get("form") == "hinge":
        return (v["idx"], v["vec"], (v["g"], float(v.get("c") or 0.0), float(v["nominal"])))
    return (v["idx"], v["vec"])


def _qcfg_for(rg: dict, cfg) -> dict | None:
    if rg.get("max_new_fail_ratio") is None:
        return None
    from esl.doe.bead_select import _qcfg
    return _qcfg(cfg)


def _candidate_bases(mesh: dict, D, cfg) -> dict:
    """후보 변수 기저(``basis_v2`` 와 같은 패키지 호출·램프·검사 — 타이 없음) → {이름: {"v": 기저} | {"error", "detail"}}.
    한 변수의 실패(누출·달성 오차·짧음·예외)는 그 변수만 건너뜀(``skipped``)."""
    from beadgraph.checks import achieved, basis_leak
    bg = _bg()
    mc = morph_cfg(cfg)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C = _conn(mesh)
    fx = np.flatnonzero(D.fixed_mask)
    g, l = D.graph, D.labels
    excl = getattr(D, "exclude_mask", np.zeros(C.shape[0], bool))
    lx = {k: np.where(excl, -1, v).astype(np.int32) if k in ("segment", "junction_zone") else v for k, v in l.items()}
    pk_list, ranges = [], {}
    for b in D.beads:
        if b.src != "graph":
            continue
        for typ in b.vars:
            name = var_name(b.id, typ)
            pk_list.append(_pkg_item(D, b, typ))
            nom = _nom(b, typ)
            lo, hi = (float(v) for v in b.range_basis[typ])
            ext = max(abs(hi - float(_r(nom))), abs(lo - float(_r(nom))))
            ranges[name] = [nom - ext, nom + ext]
    out: dict = {}
    if not pk_list:
        return out
    try:
        gB = bg.basis(g, lx, X, pk_list, ranges, cfg=mc, fixed=fx, elems=C)
    except Exception:                                   # noqa: BLE001 — 하나씩 다시(실패한 변수만 basis_error)
        gB = []
        for p in pk_list:
            try:
                gB += bg.basis(g, lx, X, [p], ranges, cfg=mc, fixed=fx, elems=C)
            except Exception as exc:                    # noqa: BLE001
                out[p["name"]] = {"error": "basis_error", "detail": f"{type(exc).__name__}: {exc}"[:200]}
    leak = {w["var"]: w for w in (basis_leak(gB, g, lx, X, C) if gB else [])}
    tol = float(mc["morph"]["achieved_tol_mm"])
    for v in gB:
        if v["name"] in leak:
            w = leak[v["name"]]
            out[v["name"]] = {"error": "basis_error", "detail": f"BG_BASIS_LEAK n={w['n']} max={w['max_mm']:.3g}"}
            continue
        if np.asarray(v["idx"]).size == 0:              # 기저 지지 없음(짧은 비드 — BG_SEGMENT_SHORT 는 기저가 있으면 점검)
            out[v["name"]] = {"error": "short", "detail": None}
            continue
        if v["info"].get("short"):                     # basis_v2 와 같이 달성 검사 없이 기저 그대로
            out[v["name"]] = {"v": v}
            continue
        bad = None
        for end in ranges[v["name"]]:
            x = bg.morph(X, [v], {v["name"]: end})
            err = achieved(g, lx, X, x, [v], {v["name"]: end}).get(v["name"])
            if err is not None and err > (tol if v["kind"] in ("D", "DF") else 1e-3):
                bad = f"BG_ACHIEVED_MISMATCH err={err:.3g}"
                break
        out[v["name"]] = {"error": "basis_error", "detail": bad} if bad else {"v": v}
    return out


def range_guard_table(mesh: dict, graph: dict, labels: dict, fixed_ids, cfg: dict | None, rules: dict, *,
                      seed: dict | None = None, exclude_segs=None, clock=None, depth_section: str | None = None,
                      section_rules: dict | None = None) -> dict:
    """BD_LOADS(§4.3 SH-13, scope prep): 후보 변수 = ① seed 선택(None = ``auto_seed``)의 그래프 비드 변수 → ② 그 밖의 단일
    세그먼트 D·W((tier, 앵커) 순, exclude_segs 제외). 후보 기저(램프 = 원래 기본 범위) → 단일 점검(``range_guard.single``) →
    seed 의 상호작용 묶음 조합 점검(``range_guard.combo``). 예산 = budget.max_evals·prep_timeout_s(기저 계산 포함)·max_vars.
    반환 = ``esl/range_guard/1`` 문서(멈추지 않으면 같은 입력에서 바이트 같음). rules = 해석된 shape_rules(range_guard 있음).
    v0.24.7 DM §2.2(depth_section 키 = floor_fixed 만): 깊이 후보 = DF, 한쪽 입구 후보(S_1) = W1, 머리 cfg·항목 key += ds."""
    from esl.doe import bead_select as bs
    from esl.morph import range_guard as rgm
    rg = _guard_rules(rules)
    if rg is None:
        raise ValueError("range_guard_table: shape_rules.range_guard 가 없음(꺼짐)")
    crit = _crit(rg, cfg)
    bc = rg["budget"]
    bud = rgm.Budget(bc.get("max_evals"), bc.get("prep_timeout_s"), clock or time.monotonic)
    steps, mkf = int(rg["steps"]), rg.get("min_keep_frac")
    sc = select_cfg(cfg)
    if seed is None:
        seed = auto_seed(graph, labels, cfg, exclude_segs=exclude_segs)[0]
    ex = {int(x) for x in exclude_segs or ()}
    wp = _w_partial(rules)
    dsv = _ds_view(depth_section, section_rules)
    if dsv is not None and section_rules is None:
        section_rules = _section_rules_now(cfg)
    dskw = {"depth_section": depth_section, "section_rules": section_rules} if dsv is not None else {}
    osd = _one_side_all(mesh, graph, labels, section_rules) if dsv is not None else {}

    def _pv(ids, net):                                  # 후보 변수: 지금 규칙 + floor_fixed 한쪽 입구 W1
        vs = ["D"] if net else _possible_vars(graph, ids, wp)
        if dsv is not None and "W" not in vs and _w1_possible(graph, ids, osd, wp, net):
            vs = vs + ["W"]
        return vs
    beads, order = [], []                               # order = [(bead id, typ, src)]
    covered: dict[int, set] = {}
    for b in seed.get("beads") or []:
        if b.get("src", "graph") != "graph":
            continue
        nb = {"id": b["id"], "name": b.get("name") or f"B{b['id'][1:]}", "src": "graph", "segs": b["segs"]}
        if b.get("vars"):
            nb["vars"] = list(b["vars"])
        if int(b.get("hold_fixed", 1)) == 0:
            nb["hold_fixed"] = 0
        ids, _z, net = _resolve_segs(graph, labels, b["segs"], b["id"])
        vs = nb.get("vars") or _pv(ids, net)
        beads.append(nb)
        order += [(b["id"], t, "seed") for t in vs]
        if len(ids) == 1 and not net and int(b.get("hold_fixed", 1)) == 1:
            covered[ids[0]] = set(vs)
    singles = sorted((s for s in graph["segments"] if s["type"] != "base" and int(s["id"]) not in ex
                      and int(s["anchor"]) >= 0),
                     key=lambda s: (int(s["tier"]), int(s["anchor"])))
    for s in singles:
        vs = [t for t in _pv([s["id"]], False) if t not in covered.get(int(s["id"]), set())]
        if not vs:
            continue
        bid = f"s{int(s['id'])}"
        beads.append({"id": bid, "name": bid.upper(), "src": "graph", "segs": [{"anchor": int(s["anchor"])}],
                      "vars": vs})
        order += [(bid, t, "segment") for t in vs]
    mx = int(bc.get("max_vars") or len(order))
    trimmed = order[mx:]
    order = order[:mx]
    if trimmed:
        bud.stop("vars")
    keep_ids = {o[0] for o in order}
    kept = []
    for nb in beads:
        if nb["id"] not in keep_ids:
            continue
        vs = [t for (i, t, _s) in order if i == nb["id"]]
        nb = dict(nb)
        nb["vars"] = vs
        kept.append(nb)
    norm = {"schema_version": SCHEMA_VERSION,
            "feature_angle_deg": float(seed.get("feature_angle_deg") or sc["feature_angle_deg"]), "beads": kept,
            "ties": [], "fixed_user": seed.get("fixed_user") or bs._norm_set(None, "fixed_user", 10_000_000),
            "exclude": seed.get("exclude") or bs._norm_set(None, "exclude", 10_000_000),
            "graph": {"sha256": graph_sha_of(graph), "rules": int(graph["rules"]), "edits": {}}}
    D = derive_obj_v2(mesh, norm, cfg, graph, labels, fixed_node_ids=fixed_ids, shape_rules=_no_guard(rules), **dskw)
    D.df_guard_q = _df_guard_q(rg)                      # DM-35: 행렬 기저(derive 의 shape_rules)와 같은 기준
    by = {b.id: b for b in D.beads}
    skipped = []
    for bid, typ, _src in trimmed:
        if bid.startswith("s"):
            ids = [int(bid[1:])]
            hold = 1
        else:
            src = next(b for b in beads if b["id"] == bid)
            ids, _z, _n = _resolve_segs(graph, labels, src["segs"], bid)
            hold = int(src.get("hold_fixed", 1))
        one = typ == "W" and dsv is not None and not w_segs(graph, ids)
        k = {"kind": "W1" if one else typ, "segs": _seg_keys(graph, ids), "hold": hold}
        if typ == "W":
            k["w_segs"] = _seg_keys(graph, sorted(x for x in ids if (osd.get(x) or {}).get("ok")) if one else
                                    (w_segs(graph, ids) if wp else ids))
        if dsv is not None:
            k["ds"] = "floor_fixed"
        skipped.append({"key": k, "reason": "budget", "detail": "max_vars"})
    order = [o for o in order if o[1] in by[o[0]].vars]   # floor_fixed: W1 이 생기지 않은 후보 W 는 빠짐
    bases = _candidate_bases(mesh, D, cfg) if order else {}
    P = _Prober(mesh, crit, _qcfg_for(rg, cfg))
    entries, by_name, supports = [], {}, {}
    for bid, typ, src in order:
        b = by[bid]
        name = var_name(bid, typ)
        key = _var_key(D.graph, b, typ)
        r = bases.get(name) or {"error": "basis_error", "detail": None}
        if "error" in r:
            skipped.append({"key": key, "reason": r["error"], "detail": r.get("detail")})
            continue
        v = r["v"]
        nom = float(_r(_nom(b, typ)))
        lo, hi = (float(x) for x in b.range_basis[typ])
        L = P.local([(v["idx"], v["vec"])])
        res = rgm.single(name, nom, lo, hi, lambda val, L=L, nom=nom: P.ok(L, [val - nom]), steps=steps, budget=bud,
                         min_keep_frac=mkf)
        if res.get("skipped"):
            skipped.append({"key": key, "reason": "budget", "detail": None})
            continue
        e = {"key": key, "var": name if src == "seed" else None, "src": src, "nominal": res["nominal"],
             "from": res["from"], "usable": res["usable"], "state": res["state"], "ends": res["ends"]}
        entries.append(e)
        if src == "seed":
            by_name[name] = (e, v)
            supports[name] = L.E
    combos = []
    cc = rg.get("combo") or {}
    if cc.get("enabled", True) and by_name:
        for grp in rgm.interacting(supports):
            _combo_one(P, rgm, grp, {n: by_name[n] for n in grp}, cc, steps, bud, combos, skipped,
                       lambda n: by_name[n][0]["key"])
    meta = {"graph_sha256": norm["graph"]["sha256"], "cfg_sha256": _guard_cfg_key(cfg, rules, dsv),
            "fixed_sha256": _mask_sha(D.fixed_mask), "exclude_sha256": _mask_sha(D.exclude_mask),
            "selection_sha256": None, "steps": steps, "min_keep_frac": mkf, "max_vars": bc.get("max_vars")}
    return rgm.doc("prep", entries, combos, skipped, bud, crit, meta)


def _combo_one(P, rgm, grp, items, cc, steps, bud, combos, skipped, keyf):
    """조합 점검 1묶음: items{이름: (항목{nominal, usable|default}, 기저 dict)} → combos/skipped 에 추가, 결과 반환."""
    names = sorted(grp)
    tup = [(n, items[n][0]["nominal"], items[n][0]["usable"][0], items[n][0]["usable"][1]) for n in names]
    L = P.local([_pv(items[n][1]) for n in names])
    noms = [t[1] for t in tup]
    res = rgm.combo(tup, lambda vals: P.ok(L, [vals[n] - v0 for n, v0 in zip(names, noms)]),
                    full_max=int(cc["full_max_vars"]), samples=int(cc["samples"]), steps=steps, budget=bud,
                    max_group=cc.get("max_group"))
    if res is None:
        return None
    members = [keyf(n) for n in names]
    if res.get("skipped"):
        skipped.append({"key": {"combo": members}, "reason": res["skipped"],
                        "detail": {"n": res.get("n", len(names)), "vars": names}})
        return res
    c = {"members": members, "vars": names, "corners": res["corners"], "bad_n": res["bad_n"], "scale": res["scale"],
         "reason": res["reason"], "value": res["value"], "usable": res["usable"]}
    combos.append(c)
    return c


def _unchecked(frm) -> dict:
    return {"state": "unchecked", "from": [float(x) for x in frm], "usable": None, "reason": None, "value": None,
            "combo_scale": None}


def _apply_single(b, typ: str, e: dict, nom: float) -> None:
    """§4.4 SH-15: 항목(state·usable·ends) → 변수 행 guard + 기본 범위·feasible(위반 쪽) + RG_RANGE_LIMITED / RG_VAR_BLOCKED."""
    from esl.morph import range_guard as rgm
    name = var_name(b.id, typ)
    frm = [float(x) for x in b.range_basis[typ]]
    u = [float(x) for x in e["usable"]]
    bad = [x for x in e["ends"] if not x["ok"]]
    g = {"state": e["state"], "from": frm, "usable": u, "reason": bad[0]["reason"] if bad else None,
         "value": bad[0]["value"] if bad else None, "combo_scale": None}
    b.guard[typ] = g
    b.warnings[:] = [w for w in b.warnings if not (w.get("code") == "RG_UNCHECKED" and w.get("var") == name)]
    us = e.get("u_sat")
    if us is not None:                                  # v0.24.9 INT-7: 정보 U_SATURATED(변수 표 회색 꼬리표 — 문구 doe_messages)
        b.warnings[:] = [w for w in b.warnings if not (w.get("code") == U_SAT_CODE and w.get("var") == name)]
        b.warnings.append({"code": U_SAT_CODE, "level": "info", "bead": b.id, "var": name, "ratio": us["ratio"],
                           "from": frm, "usable": list(us["usable"]), "lo_mm": us["usable"][0], "hi_mm": us["usable"][1]})
        if all(x.get("reason") == U_SAT_CODE for x in bad):
            return                                      # 포화만 = 기저가 기본 범위로 고정(선형) — 기본 범위를 줄이면 이동이 더 줄어 그대로
    if e["state"] == "ok":
        return
    sides = [x["side"] for x in bad]
    if e["state"] == "limited" and rgm.side_stuck(nom, frm, u):   # v0.25.0 VB-16: 폭 > 0 인 쪽만(양쪽 범위 = ¬(u_lo < nom < u_hi))
        g["state"] = "blocked"                          # 한쪽이 공칭에 붙음(그쪽 keep 0) — 축소 범위로 쓸 수 없어 막힘으로
    if g["state"] == "blocked":
        if u[0] < u[1]:
            b.range_default[typ] = [_r(u[0]), _r(u[1])]
        b.warnings.append({"code": "RG_VAR_BLOCKED", "level": "warning", "bead": b.id, "var": name, "usable": u,
                           "reason": g["reason"]})
        return
    old = list(b.range_default[typ])
    b.range_default[typ] = [_r(u[0]), _r(u[1])]
    fe = list(b.range_feasible[typ])
    if "lo" in sides:
        fe[0] = max(fe[0], _r(u[0]))
    if "hi" in sides:
        fe[1] = min(fe[1], _r(u[1]))
    b.range_feasible[typ] = fe
    b.warnings.append({"code": "RG_RANGE_LIMITED", "level": "info", "bead": b.id, "var": name, "from": old,
                       "to": list(b.range_default[typ]), "side": sides[0] if len(sides) == 1 else "both",
                       "reason": g["reason"], "value": g["value"]})


def _tie_entry(members, own, typ, nom_c) -> dict:
    """타이 대표 = 구성원 공통 Δ(BG-X-11 규칙): usable = 공칭 + [max Δlo, min Δhi](inward), state = 가장 나쁜 것."""
    from esl.morph import range_guard as rgm
    es = [own[(m.id, typ)] for m in members]
    dlo = max(float(e["usable"][0]) - float(e["nominal"]) for e in es)
    dhi = min(float(e["usable"][1]) - float(e["nominal"]) for e in es)
    rank = {"ok": 0, "limited": 1, "blocked": 2}
    st = max((e["state"] for e in es), key=lambda s: rank.get(s, 0))
    ends = [x for e in es for x in e["ends"] if not x["ok"]] or es[0]["ends"]
    return {"state": st, "usable": [rgm.inward(nom_c + dlo, nom_c), rgm.inward(nom_c + dhi, nom_c)], "ends": ends}


def apply_range_guard(D, table: dict | None, cfg) -> None:
    """derive(API·BD_MATRIX 같은 코드, SH-14·15·16): 표 머리(graph·cfg·fixed·exclude sha, toggle 없음)와 항목 key·from 이 맞는
    그래프 변수에 §4.4 적용, 맞지 않으면 guard.state unchecked + 정보 RG_UNCHECKED{var}. 조합은 구성원이 모두 맞을 때만."""
    rules = getattr(D, "shape_rules", None)
    ng = D.norm.get("graph") or {}
    ok_hdr = (isinstance(table, dict) and table.get("schema") == RANGE_GUARD_SCHEMA and
              table.get("graph_sha256") == ng.get("sha256") and not (ng.get("edits") or {}).get("toggle") and
              table.get("cfg_sha256") == _guard_cfg_key(cfg, rules, _ds_view(getattr(D, "depth_section", None),
                                                                              getattr(D, "section_rules", None))) and
              table.get("fixed_sha256") == _mask_sha(D.fixed_mask) and
              table.get("exclude_sha256") == _mask_sha(D.exclude_mask))
    ents = {_kj(e["key"]): e for e in (table.get("entries") or [])} if ok_hdr else {}
    tie = _tie_of(D.norm)
    by = {b.id: b for b in D.beads if b.src == "graph"}
    own = {}
    for b in by.values():
        b.guard = {}
        for typ in _types(b):
            e = ents.get(_kj(_var_key(D.graph, b, typ)))
            if e is not None and [float(x) for x in e["from"]] == [float(x) for x in b.range_basis[typ]]:
                own[(b.id, typ)] = e
    car = {}
    for b in by.values():
        grp = tie.get(b.id)
        if grp and grp[0] != b.id:
            continue
        for typ in _types(b):
            members = [by[x] for x in (grp or [b.id]) if x in by]
            nom = float(_r(_nom(b, typ)))
            if any((m.id, typ) not in own for m in members):
                b.guard[typ] = _unchecked(b.range_basis[typ])
                if typ != "U":                              # PU §1.3-4: U 는 준비 표에 없음 — BD_MATRIX 가 켜진 U 만 점검
                    b.warnings.append({"code": "RG_UNCHECKED", "level": "info", "bead": b.id,
                                       "var": var_name(b.id, typ)})
                continue
            e = own[(b.id, typ)] if len(members) == 1 else _tie_entry(members, own, typ, nom)
            _apply_single(b, typ, e, nom)
            if len(members) == 1:
                car[_kj(_var_key(D.graph, b, typ))] = (b, typ)
    for c in (table.get("combos") or []) if ok_hdr else []:
        tg = [car.get(_kj(k)) for k in c["members"]]
        if any(t is None for t in tg):
            continue
        _apply_combo(tg, c)


def _apply_combo(targets, c: dict) -> None:
    """조합 scale < 1 → 묶음 변수 default_range 만 조합 usable 로(feasible 불변) + 정보 RG_COMBO_LIMITED(첫 구성원 비드)."""
    names = []
    for (b, typ), vn in zip(targets, c["vars"]):
        u = [float(x) for x in c["usable"][vn]]
        nom = float(_r(_nom(b, typ)))
        g = b.guard.get(typ) or {}
        if u[0] < nom < u[1]:
            b.range_default[typ] = [_r(u[0]), _r(u[1])]
        old = g.get("combo_scale")
        g["combo_scale"] = float(c["scale"]) if old is None else float(old) * float(c["scale"])
        names.append(var_name(b.id, typ))
    b0 = targets[0][0]
    b0.warnings.append({"code": "RG_COMBO_LIMITED", "level": "info", "vars": names, "corners": c["corners"],
                        "bad_n": c["bad_n"], "scale": c["scale"], "reason": c["reason"]})


U_SAT_CODE = "U_SATURATED"      # v0.24.9 INT-7 정보 코드(range guard U 포화 — 끝 reason 과 같은 값)


def _u_sat_min(cfg) -> float:
    """포화 판정 비율 = 설정 pos_u.sat_ratio_min(해시 밖 — 빠지면 DEFAULTS 거울)."""
    from esl.doe import DEFAULTS
    return float({**DEFAULTS["pos_u"], **(((cfg or {}).get("pos_u")) or {})}["sat_ratio_min"])


def _u_sat_entry(e: dict, v: dict, lo: float, hi: float, ratio_min: float) -> None:
    """range guard U 항목 e 에 포화(실제/요청 이동 비 < ratio_min — ``section.u_saturation``)를 반영(제자리): u_sat{ratio, usable},
    품질 점검이 ok 였으면 state limited·usable = 포화 전 범위(lo·ratio, hi·ratio — 0 을 포함할 때만)·끝 reason U_SATURATED·value ratio.
    품질 점검이 이미 줄였으면 그 결과 그대로(정보만 더함). 기저·결과 불변."""
    from esl.morph import section as sec
    sat = sec.u_saturation(v["vec"], lo, hi, ratio_min)
    if sat is None:
        return
    r = _r(sat["ratio"])
    u = [_r(sat["usable"][0]), _r(sat["usable"][1])]
    nom = float(e["nominal"])
    e["u_sat"] = {"ratio": r, "usable": u}
    if e["state"] != "ok" or not (u[0] < nom < u[1]):
        return
    e["state"], e["usable"] = "limited", u
    e["ends"] = [{**x, "ok": False, "reason": U_SAT_CODE, "value": r} for x in e["ends"]]


def guard_selection(mesh: dict, D, B, cfg: dict | None, *, only=None, clock=None) -> dict | None:
    """BD_MATRIX(SH-14, scope selection): 선택의 그래프 변수 중 unchecked(또는 only 이름)만 단일 점검(선택 기저 B — 타이 =
    구성원 합) → §4.4 적용 + 선택 전체 상호작용 묶음 조합 점검(현재 기본 범위 기준) → 문서. D 의 범위·guard·경고를 제자리 수정
    (이번 행렬은 sha 고정 — 호출자가 params.json 에 반영). 예산 = max_evals·matrix_timeout_s, 넘으면 남은 변수 unchecked +
    D.warnings RG_BUDGET. shape_rules.range_guard 가 없으면 None."""
    from esl.morph import range_guard as rgm
    rules = getattr(D, "shape_rules", None)
    rg = _guard_rules(rules)
    if rg is None:
        return None
    crit = _crit(rg, cfg)
    bc = rg["budget"]
    bud = rgm.Budget(bc.get("max_evals"), bc.get("matrix_timeout_s"), clock or time.monotonic)
    steps, mkf = int(rg["steps"]), rg.get("min_keep_frac")
    tie = _tie_of(D.norm)
    by = {b.id: b for b in D.beads if b.src == "graph"}
    bv = {v["name"]: v for v in B.vars}
    P = _Prober(mesh, crit, _qcfg_for(rg, cfg))
    vbs = [vb for vb in getattr(D, "vbeads", None) or [] if vb.ok]
    warp_lim = float((getattr(D, "vb_blk", None) or vb_cfg(cfg))["warp_max_deg"])   # §19.2: A warp = 정보(세는 기준)
    carriers = []
    for b in by.values():
        grp = tie.get(b.id)
        if grp and grp[0] != b.id:
            continue
        if not hasattr(b, "guard"):
            b.guard = {}
        for typ in _types(b):
            if var_name(b.id, typ) in bv:
                carriers.append((var_name(b.id, typ), b, typ, grp))
    for vb in vbs:                                      # v0.25.0 VB §6.1: 켜진(기저 있는) A 변수
        if var_name(vb.id, VB_TYPE) in bv:
            carriers.append((var_name(vb.id, VB_TYPE), vb, VB_TYPE, None))
    carriers.sort(key=lambda t: t[0])
    want = set(only) if only is not None else None
    entries, skipped, total, done = [], [], 0, 0
    for name, b, typ, grp in carriers:
        st = (b.guard.get(typ) or {}).get("state", "unchecked")
        if (want is not None and name not in want) or (want is None and st != "unchecked"):
            continue
        total += 1
        key = _var_key(D.graph, b, typ)
        if grp:
            key["tie"] = [_var_key(D.graph, by[x], typ) for x in grp if x in by]
        v = bv[name]
        nom = float(v["nominal"])
        lo, hi = (float(x) for x in b.range_basis[typ])
        L = P.local([_pv(v)])
        res = rgm.single(name, nom, lo, hi, lambda val, L=L, nom=nom: P.ok(L, [val - nom]), steps=steps, budget=bud,
                         min_keep_frac=mkf)
        if res.get("skipped"):
            skipped.append({"key": key, "reason": "budget", "detail": None})
            if (b.guard.get(typ) or {}).get("state") is None:
                b.guard[typ] = _unchecked(b.range_basis[typ])
            continue
        done += 1
        e = {"key": key, "var": name, "src": "selection", "nominal": res["nominal"], "from": res["from"],
             "usable": res["usable"], "state": res["state"], "ends": res["ends"]}
        if typ == "U":                                  # v0.24.9 INT-7: 실제/요청 이동 비 → 포화면 limited(보고만)
            _u_sat_entry(e, v, lo, hi, _u_sat_min(cfg))
        wd = None
        if typ == VB_TYPE:                              # §19.2: usable 상한(막힘 = d_max)에서 warp 측정 — 판정에 안 씀
            at = float(res["from"][1]) if res["state"] == "blocked" else float(res["usable"][1])
            pr = P.probe(L, [at - nom], warp_max_deg=warp_lim)
            wd = {"limit_deg": warp_lim, "n": int(pr.get("warp_bad_new") or 0),
                  "max_deg": None if pr.get("warp_max") is None else _r(float(pr["warp_max"]), 3), "at": _r(at)}
            e["warp"] = wd
        entries.append(e)
        _apply_single(b, typ, e, nom)
        if wd is not None:
            b.guard[typ]["warp"] = dict(wd)
            if wd["n"] > 0:
                b.warnings.append({"code": "VB_WARP_INFO", "level": "info", "vbead": b.id, "n": wd["n"],
                                   "max": wd["max_deg"], "d": wd["at"]})
    combos = []
    cc = rg.get("combo") or {}
    if cc.get("enabled", True):
        sup, items = {}, {}
        for name, b, typ, _grp in carriers:
            g = b.guard.get(typ) or {}
            if g.get("state", "unchecked") == "unchecked":
                continue
            v = bv[name]
            sup[name] = P.support([v["idx"]])
            items[name] = ({"nominal": float(v["nominal"]), "usable": [float(x) for x in b.range_default[typ]]}, v)
        keyof = {name: _var_key(D.graph, b, typ) for name, b, typ, _g in carriers}
        tgt = {name: (b, typ) for name, b, typ, _g in carriers}
        for grp_ in rgm.interacting(sup):
            va = [n for n in grp_ if tgt[n][1] == VB_TYPE]
            if va and len(va) < len(grp_):               # v0.25.0 VB §6.1: 그래프 비드 띠와 A 지지 겹침 = 정보
                for n in va:
                    tgt[n][0].warnings.append({"code": "VB_BAND_OVERLAP", "level": "info", "vbead": tgt[n][0].id,
                                               "vars": [x for x in grp_ if x != n]})
            c = _combo_one(P, rgm, grp_, items, cc, steps, bud, combos, skipped, lambda n: keyof[n])
            if c is not None and "scale" in c:
                _apply_combo([tgt[n] for n in c["vars"]], c)
            elif c is not None and c.get("skipped") == "max_group":
                D.warnings.append({"code": "RG_COMBO_SKIPPED", "level": "info", "vars": c["vars"], "n": c["n"]})
    if bud.stopped is not None:
        D.warnings.append({"code": "RG_BUDGET", "level": "info", "done": done, "total": total, "evals": bud.evals,
                           "stopped": bud.stopped})
    meta = {"graph_sha256": (D.norm.get("graph") or {}).get("sha256"),
            "cfg_sha256": _guard_cfg_key(cfg, rules, _ds_view(getattr(D, "depth_section", None),
                                                             getattr(D, "section_rules", None))),
            "fixed_sha256": _mask_sha(D.fixed_mask), "exclude_sha256": _mask_sha(D.exclude_mask),
            "selection_sha256": D.sha256, "steps": steps, "min_keep_frac": mkf, "max_vars": bc.get("max_vars")}
    return rgm.doc("selection", entries, combos, skipped, bud, crit, meta)


def guard_info(doc: dict | None) -> list[dict]:
    """준비 표 → 준비 정보(§8): RG_BUDGET{done, total, evals, stopped}(멈췄을 때) · RG_COMBO_SKIPPED{vars, n}(묶음 초과)."""
    if not doc:
        return []
    out = []
    for s in doc.get("skipped") or []:
        if s.get("reason") == "max_group":
            dt = s.get("detail") or {}
            out.append({"code": "RG_COMBO_SKIPPED", "level": "info", "vars": dt.get("vars") or [], "n": dt.get("n")})
    b = doc.get("budget") or {}
    if b.get("stopped") is not None:
        n_sk = sum(1 for s in doc.get("skipped") or [] if s.get("reason") == "budget")
        done = len(doc.get("entries") or [])
        out.append({"code": "RG_BUDGET", "level": "info", "done": done, "total": done + n_sk, "evals": b.get("evals"),
                    "stopped": b.get("stopped")})
    return out


def guard_result(doc: dict | None, seconds: float | None = None) -> dict | None:
    """작업 결과·prep/input.json 의 range_guard 요약 {entries, limited, blocked, combos, evals, seconds, stopped}."""
    if not doc:
        return None
    es = doc.get("entries") or []
    return {"entries": len(es), "limited": sum(1 for e in es if e["state"] == "limited"),
            "blocked": sum(1 for e in es if e["state"] == "blocked"), "combos": len(doc.get("combos") or []),
            "evals": (doc.get("budget") or {}).get("evals"),
            "seconds": None if seconds is None else round(float(seconds), 3),
            "stopped": (doc.get("budget") or {}).get("stopped")}


def outside_guard(rows: list[dict], values: dict) -> dict | None:
    """미리보기 셀(SH-14 BD_SELECT_GRID): 안 값이 변수 행 guard.usable 밖 → 경고 RG_OUTSIDE_GUARD{vars[{name, value, usable}]}
    (경고만 — 상태 불변). guard 없는 행(옛 스냅샷·elems 변수)·unchecked 는 보지 않음."""
    out = []
    for r in rows or []:
        g = r.get("guard") or {}
        u = g.get("usable")
        if not u or r.get("name") not in values:
            continue
        v = float(values[r["name"]])
        if v < float(u[0]) - 1e-9 or v > float(u[1]) + 1e-9:
            out.append({"name": r["name"], "value": _r(v), "usable": [float(u[0]), float(u[1])]})
    return {"code": "RG_OUTSIDE_GUARD", "level": "warning", "vars": out} if out else None


def write_range_guard(path: str, doc: dict, guard=None) -> str:
    """정렬·compact·ASCII(graph_bytes 와 같은 직렬화) → sha256."""
    g = guard or (lambda p: p)
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    with open(g(path), "wb") as fh:
        fh.write(blob)
    return hashlib.sha256(blob).hexdigest()


def load_range_guard(prep_dir: str) -> dict | None:
    """prep/ (또는 prep/select/, 또는 select/<sha12>/ 처럼 파일이 바로 있는 폴더) → 표(스키마 확인) | None."""
    d = prep_dir
    if not os.path.isfile(os.path.join(d, RANGE_GUARD_JSON)):
        d = prep_dir if os.path.isfile(os.path.join(prep_dir, GRAPH_JSON)) else os.path.join(prep_dir, "select")
    p = os.path.join(d, RANGE_GUARD_JSON)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "rb") as fh:
            doc = json.loads(fh.read().decode("ascii"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == RANGE_GUARD_SCHEMA else None


# ====================================================================== v0.25.0 VB — 가상 비드("추가 비드", esl_virtual_bead.md)
VB_ID_RE = __import__("re").compile(r"^a[1-9]$")
VB_KEYS = ("id", "name", "p0", "p1", "length", "angle_deg", "w_top", "theta_deg", "d_max", "end", "r", "flip")
VB_TYPE = "A"
VB_NAME_RE = __import__("re").compile(r"^A[1-9]_A$")     # 가상 비드 변수 이름(var_name("a<n>", "A"))


def vb_cfg(cfg) -> dict:
    """설정 ``bead_doe.virtual_bead``(settings dict 의 절 — 없으면 DEFAULTS 거울)."""
    from esl.doe import DEFAULTS
    vc = cfg.get("virtual_bead") if isinstance(cfg, dict) else None
    return {**copy.deepcopy(DEFAULTS["virtual_bead"]), **(vc or {})}


def vb_block(block, cfg) -> dict | None:
    """스냅샷 ``doe.virtual_bead`` 블록 → 해석값(블록 없음 = None — 옛 스터디 VB_SCOPE). 해시 안 키 = 블록 값, 그 밖 = 지금 설정.
    §19.1-7: 블록에 r_default_h_mult 가 없으면 0.0(없던 규칙 주입 안 함)."""
    if not isinstance(block, dict):
        return None
    out = {**vb_cfg(cfg), **{k: v for k, v in block.items() if k != "schema"}}
    if "r_default_h_mult" not in block:
        out["r_default_h_mult"] = 0.0
    return out


def vb_flip_deg(cfg, shape_rules=None) -> float:
    """뒤집힘 기준 flip_deg — 스냅샷 range guard 블록 값(``_crit`` 와 같은 값), 없으면 select.quality.flip_deg."""
    rg = _guard_rules(shape_rules)
    if rg is not None:
        return float(_crit(rg, cfg)["flip_deg"])
    return float(select_cfg(cfg)["quality"]["flip_deg"])


def _vbnum(x) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and np.isfinite(float(x))


def _vb_bad(vid, msg: str, **kw):
    _bad("VB_INPUT_INVALID", f"추가 비드 {vid}: {msg}", vbead=vid, **kw)


def normalize_vbeads(vbs, cfg, flip_deg: float | None = None, block: dict | None = None) -> list[dict]:
    """§2.1·§19 선택 키 virtual_beads 정규화(형식 오류 = 422 VB_INPUT_INVALID, 개수 초과 = VB_MAX_COUNT). 입력 형식 그대로((a) p0·p1 |
    (b) p0·length·angle_deg), 숫자 1e-4 반올림, id 정렬, 기본값 키 생략(name·theta_deg = theta_default_deg·end round·flip false).
    r 은 준 값이면 0 도 키 유지(§19.1-5), r > r_cap + 1e-4 = 422(key r, r_max). θ 상한 = min(theta_range_deg[1], flip_deg)(§19.4-3).
    side 키 = 422(개정 3 삭제). 없음·빈 목록 = [] (호출자가 키를 쓰지 않음). block = 스냅샷 블록(INT-2 — 있으면 ``vb_block`` 해석값, 없음 = 설정)."""
    from esl.morph import virtual_bead as vbm
    if vbs is None:
        return []
    vc = vb_block(block, cfg) if isinstance(block, dict) else vb_cfg(cfg)
    if not isinstance(vbs, list):
        _bad("VB_INPUT_INVALID", "virtual_beads 는 목록")
    mx = int(vc["max_count"])
    if len(vbs) > mx:
        _bad("VB_MAX_COUNT", f"추가 비드는 {mx}개까지 (값 {len(vbs)})", n=len(vbs), max=mx)
    th_lo, th_hi = (float(x) for x in vc["theta_range_deg"])
    flip = float(select_cfg(cfg)["quality"]["flip_deg"]) if flip_deg is None else float(flip_deg)
    th_hi = min(th_hi, flip)
    th_def = float(vc["theta_default_deg"])
    dlim = float(vc["d_max_limit_mm"])
    from esl.doe import bead_select as bs
    out, seen = [], set()
    for v in vbs:
        if not isinstance(v, dict):
            _bad("VB_INPUT_INVALID", "추가 비드 항목은 객체")
        vid = v.get("id")
        if not isinstance(vid, str) or not VB_ID_RE.match(vid) or int(vid[1:]) > mx or vid in seen:
            _bad("VB_INPUT_INVALID", f"추가 비드 id {vid!r} 는 a1..a{mx} 고유", vbead=vid)
        seen.add(vid)
        if "side" in v:
            _vb_bad(vid, "side 는 없어진 키 — 방향은 자동, 반대는 flip: true", key="side")
        extra = sorted(set(v) - set(VB_KEYS))
        if extra:
            _vb_bad(vid, f"모르는 키 {extra}", key=extra[0])
        nb = {"id": vid}
        name = v.get("name")
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name) <= 32 or bs._CTRL_RE.search(name):
                _vb_bad(vid, "이름은 1..32자, 제어문자 금지", key="name")
            if name != f"추가 비드 {vid[1:]}":
                nb["name"] = name

        def pt(k):
            p = v.get(k)
            if not isinstance(p, (list, tuple)) or len(p) != 3 or not all(_vbnum(x) for x in p):
                _vb_bad(vid, f"{k} 는 [x, y, z] 유한한 수", key=k)
            return [_r(float(x)) for x in p]
        nb["p0"] = pt("p0")
        has_b = v.get("length") is not None or v.get("angle_deg") is not None
        if v.get("p1") is not None:
            if has_b:
                _vb_bad(vid, "p1 과 length·angle_deg 는 함께 쓸 수 없음", key="p1")
            nb["p1"] = pt("p1")
            if float(np.linalg.norm(np.subtract(nb["p1"], nb["p0"]))) < 1e-6:
                _vb_bad(vid, "길이 0(p0 = p1)", key="p1")
        else:
            ln, an = v.get("length"), v.get("angle_deg")
            if not (_vbnum(ln) and float(ln) > 0):
                _vb_bad(vid, "length > 0 필요(또는 p1)", key="length")
            if not (_vbnum(an) and -180.0 < float(an) <= 180.0):
                _vb_bad(vid, "angle_deg 는 (−180, 180]", key="angle_deg")
            nb["length"], nb["angle_deg"] = _r(float(ln)), _r(float(an))
        wt = v.get("w_top")
        if not (_vbnum(wt) and float(wt) > 0):
            _vb_bad(vid, "w_top > 0", key="w_top")
        nb["w_top"] = _r(float(wt))
        th = v.get("theta_deg")
        if th is not None:
            if not (_vbnum(th) and th_lo <= float(th) <= th_hi):
                _vb_bad(vid, f"theta_deg 는 {th_lo:g}..{th_hi:g}", key="theta_deg")
            if _r(float(th)) != _r(th_def):
                nb["theta_deg"] = _r(float(th))
        dm = v.get("d_max")
        if not (_vbnum(dm) and 0.0 < float(dm) <= dlim):
            _vb_bad(vid, f"d_max 는 (0, {dlim}]", key="d_max")
        nb["d_max"] = _r(float(dm))
        en = v.get("end")
        if en is not None:
            if en not in ("round", "square"):
                _vb_bad(vid, "end 는 round | square", key="end")
            if en != "round":
                nb["end"] = en
        rr = v.get("r")
        if rr is not None:
            if not (_vbnum(rr) and float(rr) >= 0):
                _vb_bad(vid, "r ≥ 0", key="r")
            rc = vbm.r_cap(nb["w_top"], float(nb.get("theta_deg", th_def)), nb["d_max"])
            if float(rr) > rc + 1e-4:
                _vb_bad(vid, f"r ≤ {rc:.4f}(이 단면의 모서리 둥글기 상한)", key="r", r_max=_r(rc))
            nb["r"] = _r(float(rr))                        # §19.1-5: 0 도 키 유지(키 없음 = 요소 크기 기본)
        fl = v.get("flip")
        if fl is not None:
            if not isinstance(fl, bool):
                _vb_bad(vid, "flip 은 true | false", key="flip")
            if fl:
                nb["flip"] = True                          # §19.9.2-1: true 만 키(false = 생략)
        out.append(nb)
    out.sort(key=lambda x: int(x["id"][1:]))
    return out


class VirtualBead:
    """가상 비드 1개(derive) — guard·params·basis 가 쓰는 그래프 비드와 같은 이름의 속성(range_*·guard·warnings·vars)."""

    def __init__(self, spec: dict, blk: dict | None):
        self.id = spec["id"]
        self.name = spec.get("name") or f"추가 비드 {self.id[1:]}"
        self.src = "virtual"
        self.spec = spec
        self.tier = None
        self.hold_fixed = 1
        self.vars: list[str] = []
        self.reasons: list[str] = []
        self.warnings: list[dict] = []
        self.guard: dict = {}
        self.w_top = float(spec["w_top"])
        self.theta = float(spec.get("theta_deg", (blk or {}).get("theta_default_deg", 45.0)))
        self.theta_f = self.theta
        self.d_max = float(spec["d_max"])
        self.end = spec.get("end", "round")
        self.r_user = spec.get("r")
        self.r = float(self.r_user) if self.r_user is not None else 0.0
        self.r_source = "user" if self.r_user is not None else "default"
        self.flip = bool(spec.get("flip", False))
        self.range_default = {"A": [0.0, _r(self.d_max)]}
        self.range_feasible = {"A": [0.0, _r(self.d_max)]}
        self.range_basis = {"A": [0.0, _r(self.d_max)]}
        self.field = None
        self.h = self.n_wall = self.n_top = None
        self.p0 = list(spec["p0"])
        self.p1 = self.t = self.L = self.angle = self.plane = None
        self.side = None
        self.diag = None
        self.chk = None
        self.d_move = None
        self.n_hat = None
        self.host = None
        self.host_floor = None

    @property
    def ok(self) -> bool:
        return not self.reasons and self.field is not None


def _vb_majority(D, X, ph, nh) -> int:
    """§2.3 그래프 비드 다수결(비드 바닥 노드의 host 판 평면 부호 거리 중앙값 부호 — VB-C1-2). 동률·없음 = 0."""
    votes = 0
    for b in D.beads:
        if getattr(b, "src", "") != "graph" or not hasattr(b, "floor_mask"):
            continue
        nd = D.index.elem_nodes(b.floor_mask)
        if not np.asarray(nd).size:
            continue
        off = float(np.median((X[nd] - ph) @ nh))
        if abs(off) > 1e-9:
            votes += 1 if off > 0 else -1
    return 0 if votes == 0 else (1 if votes > 0 else -1)


def _vb_side_auto(D, X, ph, nh, frame_n, host_type, floor) -> int:
    """§19.9.2-4 자동 방향 s_auto(n_h 기준): ① 평탄부 host ∧ |level(f) − level(parent)| > 1e-6 → 그 부호(n0 기준 — n_h 는 n0 쪽)
    ② 그래프 비드 다수결 ③ frame n 반대."""
    from esl.morph import virtual_bead as vbm
    if host_type in ("area", "plateau") and floor is not None:
        fl = {int(f["id"]): f for f in D.graph.get("floors") or []}
        f = fl.get(int(floor))
        par = fl.get(int(f.get("parent", -1))) if f is not None else None
        if f is not None and par is not None and f.get("level") is not None and par.get("level") is not None:
            dl = float(f["level"]) - float(par["level"])
            if abs(dl) > vbm.LEVEL_EPS:
                return 1 if dl > 0 else -1
    m = _vb_majority(D, X, ph, nh)
    if m:
        return m
    return -1 if float(np.dot(frame_n, nh)) >= 0.0 else 1


def _vb_outline(q0, q1, t, nh, rad, end: str, frame) -> list | None:
    """발자국 윤곽(이동 띠 d_move) → frame (a, b) 꺾은선(닫힘, 3 자리) — 3D 강조용. frame 없음 = None."""
    if frame is None:
        return None
    from esl.opt.keepout import project_ab
    ey = np.cross(nh, t)
    if end == "square":
        pts = [q0 - rad * t - rad * ey, q1 + rad * t - rad * ey, q1 + rad * t + rad * ey, q0 - rad * t + rad * ey]
    else:
        a = np.linspace(-np.pi / 2, np.pi / 2, 9)
        pts = [q1 + rad * (np.cos(x) * t + np.sin(x) * ey) for x in a] + \
              [q0 + rad * (-np.cos(x) * t - np.sin(x) * ey) for x in a]
    pts.append(pts[0])
    return [{"a": a_, "b": b_} for a_, b_ in project_ab(frame, np.asarray(pts)).round(3).tolist()]


def virtual_beads(D, mesh, blk: dict | None, *, vb_plan: str = "plate", frame=None, tie_idx=None, flip_deg=None,
                  cfg=None) -> None:  # noqa: C901
    """§2.2~§4·§19 derive: 선택 virtual_beads → D.vbeads[VirtualBead](사유 목록·경고·기저 장). 범위 밖(블록 없음·계획·출처) =
    VB_SCOPE. host = 세그먼트 종류 ∈ VB_HOST_SEG_TYPES(부모 바닥·평탄부)의 floor 요소(씨앗 floor 만, wall_islands floor 제외),
    평탄부 바깥 테두리 transition = VB_PLATE_EDGE(§19.3). r 생략 = min(r_default_h_mult·h, r_cap)(h = r 0 발자국 — 2-pass, §19.1),
    장 각 θ_f = min(θ, flip_deg − ε)(§19.4-4), 방향 = 자동(§19.9.2) × flip."""
    from esl.morph import section as sec
    from esl.morph import virtual_bead as vbm
    specs = D.norm.get("virtual_beads") or []
    D.vbeads = [VirtualBead(sp, blk) for sp in specs]
    if not specs:
        return
    host_row = "graph" if D.norm.get("graph") is not None else "none"
    if blk is None or not sec.vb_allowed(vb_plan, host_row):
        for vb in D.vbeads:
            vb.reasons = ["VB_SCOPE"]
        return
    from esl.mesh import features
    ix = D.index
    g2, l2 = D.graph, D.labels
    X = np.asarray(mesh["x0"], np.float64)
    C = _conn(mesh)
    et = np.asarray(mesh["elem_type"]).astype(int)
    excl = np.asarray(getattr(D, "exclude_mask", np.zeros(C.shape[0], bool)), bool)
    seg = np.asarray(l2["segment"])
    stype = np.array([s["type"] for s in g2["segments"]] or ["base"], dtype=object)
    etype = np.where(seg >= 0, stype[np.clip(seg, 0, stype.size - 1)], None)
    host_t = np.array([t in vbm.VB_HOST_SEG_TYPES for t in etype.tolist()], bool)
    area_t = np.array([t in vbm.VB_HOST_SEG_TYPES and t != "base" for t in etype.tolist()], bool)
    cls = np.asarray(l2["cls"])
    floor = np.asarray(l2["floor"])
    jz, isl, tr = (np.asarray(l2[k]) for k in ("junction_zone", "island", "transition"))
    max_mm = float(select_cfg(cfg)["graph"]["island"]["max_mm"]) if cfg is not None else 60.0
    wi = {int(w["floor"]) for w in wall_islands(g2, l2, mesh, max_mm)} if g2.get("floors") else set()
    wi_mask = np.isin(floor, sorted(wi)) if wi else np.zeros(C.shape[0], bool)
    host_all = (cls == 0) & host_t & (jz < 0) & (isl < 0) & ~excl & ~wi_mask
    island = (isl >= 0) | (cls == 2) | (cls == 3) | wi_mask
    free = np.zeros(X.shape[0], bool)
    fe = ix.edge_nodes[ix.edge_count == 1]
    free[fe.ravel()] = True
    outer = np.zeros(X.shape[0], bool)
    outer[np.asarray(features.plate_edge_nodes(ix), np.int64)] = True
    holes = free & ~outer
    fixed = np.asarray(D.fixed_mask, bool).copy()
    if tie_idx is not None and np.asarray(tie_idx).size:
        fixed[np.asarray(tie_idx, np.int64)] = True
    fr = g2.get("frame") or {}
    n0 = np.asarray(fr.get("n0") or [0.0, 0.0, 1.0], np.float64)
    if frame is not None:
        e_xi, e_eta = (np.asarray(frame[k], np.float64) for k in ("e_xi", "e_eta"))
        frame_n = np.asarray(frame.get("n") or np.cross(e_xi, e_eta), np.float64)
    else:                                               # ESL frame 없음(시험·옛 호출) = 그래프 frame 축
        e_xi = np.asarray(fr.get("e1") or [1.0, 0.0, 0.0], np.float64)
        e_eta = np.asarray(fr.get("e2") or [0.0, 1.0, 0.0], np.float64)
        frame_n = n0
    floors = {int(f["id"]): f for f in g2.get("floors") or []}
    trans = g2.get("transitions") or []
    h_g = float(fr.get("h_mm") or 1.0)
    margin = float(blk["margin_mm"])
    mult = float(blk.get("r_default_h_mult", 0.0))
    cen = (X[C[:, 0]] + X[C[:, 1]] + X[C[:, 2]]) / 3.0
    q = et == 4
    cen[q] = (X[C[q, 0]] + X[C[q, 1]] + X[C[q, 2]] + X[C[q, 3]]) / 4.0
    hidx = np.flatnonzero(host_all)
    for vb in D.vbeads:
        sp = vb.spec
        vb.theta_f = vbm.theta_field(vb.theta, flip_deg)
        if not hidx.size:
            vb.reasons = ["VB_NOT_ON_PLATE"]
            continue
        p0 = np.asarray(sp["p0"], np.float64)
        seed = hidx[int(np.argmin(np.linalg.norm(cen[hidx] - p0, axis=1)))]
        f = int(floor[seed])
        H = host_all & (floor == f)
        vb.host, vb.host_floor = str(etype[seed]), f
        if "p1" in sp:
            p1r = np.asarray(sp["p1"], np.float64)
            Lr = float(np.linalg.norm(p1r - p0))
        else:
            al = np.radians(float(sp["angle_deg"]))
            Lr = float(sp["length"])
            p1r = p0 + Lr * (np.cos(al) * e_xi + np.sin(al) * e_eta)
        th = np.radians(vb.theta)
        rad = Lr / 2.0 + (vb.w_top + 2.0 * vb.d_max / np.tan(th)) / 2.0 + margin
        hn = ix.elem_nodes(H)
        near = hn[np.linalg.norm(X[hn] - 0.5 * (p0 + p1r), axis=1) <= rad]
        if near.size < 3:
            near = np.unique(C[seed][C[seed] >= 0])
        ph, nh, _rms = mcore_plane_fit(X[near])
        if float(np.dot(nh, n0)) < 0.0:
            nh = -nh
        vb.plane = (ph, nh)
        try:
            q0, q1, t, L = vbm.resolve_line(p0, sp.get("p1"), sp.get("length"), sp.get("angle_deg"), (e_xi, e_eta),
                                            (ph, nh))
        except ValueError:
            vb.reasons = ["VB_INPUT_INVALID"]
            continue
        vb.p1, vb.t, vb.L = q1, t, L
        ex, ey = vbm.frame_in_plane((e_xi, e_eta), nh)
        vb.angle = float(np.degrees(np.arctan2(float(t @ ey), float(t @ ex))))
        far = max(vbm.plane_dist(p0, (ph, nh)), vbm.plane_dist(p1r if "p1" in sp else q1, (ph, nh))) > margin + 2.0 * h_g
        line = (q0, q1, t, L, nh)
        # §19.1-2·3: ① r 0 발자국 → h(한 번) ② r 생략 = min(mult·h, r_cap) ③ 그 r 로 발자국
        fp0 = vbm.footprint(X, line, vb.w_top, vb.theta_f, vb.d_max, vb.end, 0.0, margin)
        efp0 = vbm.chk_elems(C, et, fp0["move_mask"]) & H
        vb.h = vbm.edge_median(X, C, et, efp0) if efp0.any() else None
        if vb.r_user is None and vb.h is not None:
            rh = mult * float(vb.h)
            rc = vbm.r_cap(vb.w_top, vb.theta_f, vb.d_max)
            vb.r = _r(min(rh, rc))
            if rh > rc + 1e-4:
                vb.warnings.append({"code": "VB_R_CLAMPED", "level": "info", "vbead": vb.id, "r": _r(vb.r), "r_h": _r(rh)})
        fp = vbm.footprint(X, line, vb.w_top, vb.theta_f, vb.d_max, vb.end, vb.r, margin)
        vb.d_move = fp["d_move"]
        vb.fp = fp
        vb.chk = vbm.chk_elems(C, et, fp["chk_mask"])
        vb.H = H
        vb.far = far
        # §19.3-2 평탄부 바깥 테두리 transition(child == f)·그 너머 부모 floor
        edge_tr = [int(x["id"]) for x in trans if int(x.get("child", -1)) == f]
        vb.edge = np.isin(tr, edge_tr) if edge_tr else np.zeros(C.shape[0], bool)
        par = int((floors.get(f) or {}).get("parent", -1))
        vb.skip = (floor == par) & (par >= 0) if edge_tr else np.zeros(C.shape[0], bool)
        vb.bead = ((seg >= 0) & ~host_t) | (area_t & (floor != f)) | (jz >= 0) | ((tr >= 0) & ~vb.edge)
        s_auto = _vb_side_auto(D, X, ph, nh, frame_n, vb.host, f)
        vb.side = -s_auto if vb.flip else s_auto
    for vb in D.vbeads:
        if vb.reasons or vb.chk is None:
            continue
        other = np.zeros(C.shape[0], bool)
        for o in D.vbeads:
            if o is not vb and o.chk is not None:      # 겹침 = 둘 다 VB_OVER_VBEAD(§12-3)
                other |= o.chk
        codes = vbm.host_check(C, vb.chk, {"host": vb.H, "bead": vb.bead, "island": island, "exclude": excl,
                                           "other_vb": other, "edge": vb.edge, "skip": vb.skip, "hole_nodes": holes,
                                           "edge_nodes": outer, "fixed_nodes": fixed})
        if vb.far and "VB_NOT_ON_PLATE" not in codes:
            codes.insert(0, "VB_NOT_ON_PLATE")
        h = vb.h
        if h is None:
            if "VB_NOT_ON_PLATE" not in codes:
                codes.insert(0, "VB_NOT_ON_PLATE")
        else:
            rs = vbm.resolution(h, vb.w_top, vb.theta, vb.d_max, float(blk["min_wall_elems"]))
            vb.n_wall, vb.n_top = rs["n_wall"], rs["n_top"]
            codes += rs["codes"]
            for w in rs["warns"]:
                vb.warnings.append({**w, "level": "warning", "vbead": vb.id})
        vb.reasons = sorted(set(codes), key=vbm.REASONS.index)
        if vb.reasons:
            continue
        idx = np.flatnonzero(vb.fp["move_mask"]).astype(np.int64)
        nrm = vbm.node_normals(X, C, et, vb.H, vb.plane[1])[idx]
        vb.field = vbm.field(vb.fp["d"][idx], nrm, vb.side, vb.w_top, vb.theta_f, vb.r, idx=idx)
        vb.diag = vbm.diag(X, C, et, vb.field, vb.d_max)
        vb.n_hat = np.asarray(vb.plane[1], np.float64)
        vb.vars = [VB_TYPE]
        vb.warnings.append({"code": "VB_EDGE_SMEAR", "level": "info", "vbead": vb.id, "h": _r(h)})


def mcore_plane_fit(P):
    from esl.morph import core as mcore
    return mcore.plane_fit(P)


def vb_row(vb, cfg=None) -> dict:
    """§5.1·§19.7 params[] A 행."""
    name = var_name(vb.id, VB_TYPE)
    dm = _r(vb.d_max)
    blk_on = bool(vb_cfg(cfg).get("default_on", True))
    r = {"name": name, "type": VB_TYPE, "bead": vb.id, "tier": None, "form": "hinge", "nominal": 0.0, "unit": "mm",
         "feasible": list(vb.range_feasible[VB_TYPE]), "feasible_source": "user",
         "default_range": list(vb.range_default[VB_TYPE]), "use_default": blk_on, "group_members": [name],
         "label": f"추가 비드 {vb.id[1:]} · 깊이", "wall_elems": _r(vb.n_wall, 2),
         "vb": {"w_top": _r(vb.w_top), "theta_deg": _r(vb.theta), "side": "+" if vb.side > 0 else "-",
                "n_wall": _r(vb.n_wall, 2), "n_top": _r(vb.n_top, 2), "len_mm": _r(vb.L), "angle_deg": _r(vb.angle, 3),
                "d_max": dm, "r": _r(vb.r), "r_source": vb.r_source, "host": vb.host}}
    r["acc_hint"] = vb_acc_hint(vb.h, vb.d_max, vb.theta, r_user=vb.r_user, r_resolved=vb.r)
    gd = vb.guard.get(VB_TYPE)
    if gd is not None:
        r["guard"] = copy.deepcopy(gd)
        if gd.get("state") == "blocked":
            r["use_default"] = False
    return r


_ACC_CACHE: dict = {}


def load_vbead_accuracy(path: str | None = None) -> dict | None:
    """resources/vbead_accuracy.json(정확도 표 — 문구 자료, 설정 아님 · V-0250-VB-11·27 측정값). 없으면 None."""
    from esl.doe import RESOURCES
    p = path or os.path.join(RESOURCES, "vbead_accuracy.json")
    if p not in _ACC_CACHE:
        try:
            with open(p, encoding="utf-8") as fh:
                _ACC_CACHE[p] = json.load(fh)
        except (OSError, ValueError):
            _ACC_CACHE[p] = None
    return _ACC_CACHE[p]


def vb_acc_hint(h, d_max, theta, table: dict | None = None, *, r_user=None, r_resolved=None) -> dict | None:
    """§9·§19.5-5: 정확도 표에서 (h, D_max, θ) 에 가장 가까운 칸 {h, d, theta, r, c_err_pct, pi_err_pct}(상대 거리 최소 — 표 범위의
    1/1.25..1.25 배 밖 = None). 칸 목록: r 생략 → cells(r 기본), 준 r 0 → cells_r0, 그 밖의 준 r → 해석된 r 이 고른 칸 r 의
    1/1.25..1.25 배 안일 때만 cells(아니면 None). 표 없음 = None."""
    tab = table if table is not None else load_vbead_accuracy()
    if not tab or h is None:
        return None
    if r_user is not None and float(r_user) == 0.0 and tab.get("cells_r0") is not None:
        src = tab["cells_r0"]
    else:
        src = tab.get("cells") or []
    cells = [c for c in src if c.get("c_err_pct") is not None]
    if not cells:
        return None
    hs = [float(c["h"]) for c in cells]
    ds = [float(c["d"]) for c in cells]
    ts = [float(c["theta"]) for c in cells]

    def out(v, vs):
        return v < min(vs) / 1.25 - 1e-9 or v > max(vs) * 1.25 + 1e-9
    if out(float(h), hs) or out(float(d_max), ds) or out(float(theta), ts):
        return None
    best = min(cells, key=lambda c: (abs(np.log(float(h) / float(c["h"]))) + abs(np.log(float(d_max) / float(c["d"]))) +
                                     abs(np.log(float(theta) / float(c["theta"]))), float(c["h"]), float(c["d"]),
                                     float(c["theta"])))
    rc = best.get("r")
    if r_user is not None and float(r_user) != 0.0 and src is tab.get("cells"):
        rr = float(r_resolved if r_resolved is not None else r_user)
        if rc is None or float(rc) <= 0 or not (float(rc) / 1.25 - 1e-9 <= rr <= float(rc) * 1.25 + 1e-9):
            return None
    return {"h": float(best["h"]), "d": float(best["d"]), "theta": float(best["theta"]),
            "r": None if rc is None else float(rc), "c_err_pct": best.get("c_err_pct"), "pi_err_pct": best.get("pi_err_pct")}


def vb_reason_doc(vb) -> dict | None:
    """비드 행 vb_reason{code, text}(첫 사유 — 회색 1줄)."""
    if not vb.reasons:
        return None
    from esl.doe import message
    return {"code": vb.reasons[0], "text": message(vb.reasons[0])}


def vb_bead_rows(D) -> list[dict]:
    """params.json·derive param_beads 의 kind virtual 행 {id, name, kind, warnings, vb_reason?}."""
    out = []
    for vb in getattr(D, "vbeads", None) or []:
        r = {"id": vb.id, "name": vb.name, "kind": "virtual", "warnings": vb.warnings}
        rd = vb_reason_doc(vb)
        if rd is not None:
            r["vb_reason"] = rd
        out.append(r)
    return out


def vb_basis_vars(D) -> list[dict]:
    """§4.2 기저 변수(hinge): {name, type A, bead, tier None, members, nominal 0, n_hat, R None, idx, vec, form, g, c}."""
    out = []
    for vb in getattr(D, "vbeads", None) or []:
        if not vb.ok:
            continue
        f = vb.field
        name = var_name(vb.id, VB_TYPE)
        out.append({"name": name, "type": VB_TYPE, "bead": vb.id, "tier": None, "members": [name], "nominal": 0.0,
                    "n_hat": vb.n_hat, "R": None, "idx": np.asarray(f["idx"], np.int32),
                    "vec": np.asarray(f["vec"], np.float64), "form": "hinge", "g": np.asarray(f["g"], np.float64),
                    "c": float(f["c"])})
    return out


def vb_text(w: dict, msgs: dict) -> str:
    """경고·정보 dict → 문구(자리표시 {키} 를 그 dict 값으로 — 없으면 문구 그대로)."""
    t = msgs.get(w.get("code"), w.get("code"))
    try:
        return t.format(**{k: (f"{v:g}" if isinstance(v, float) else v) for k, v in w.items()})
    except (KeyError, IndexError, ValueError):
        return t


def vb_derive_doc(D, cfg=None, frame=None) -> tuple[list[dict], dict | None]:
    """§8 derive 응답 virtual_beads[…]·vb_frame(가상 비드 있을 때만 — 호출자가 키를 씀)."""
    from esl.doe import load_messages
    from esl.morph import virtual_bead as vbm
    msgs = load_messages()["messages"]
    vc = vb_cfg(cfg)
    rows, vfr = [], None
    for vb in getattr(D, "vbeads", None) or []:
        r = {"id": vb.id, "name": vb.name, "p0": list(vb.spec["p0"]),
             "p1_resolved": None if vb.p1 is None else [_r(float(x)) for x in vb.p1],
             "len_mm": None if vb.L is None else _r(vb.L), "angle_deg": None if vb.angle is None else _r(vb.angle, 3),
             "side_resolved": None if vb.side is None else ("+" if vb.side > 0 else "-"), "ok": bool(vb.ok),
             "reasons": [{"code": c, "text": msgs.get(c, c)} for c in vb.reasons],
             "warnings": [{**w, "text": vb_text(w, msgs)} for w in vb.warnings],
             "h": None if vb.h is None else _r(vb.h), "n_wall": None if vb.n_wall is None else _r(vb.n_wall, 2),
             "n_top": None if vb.n_top is None else _r(vb.n_top, 2),
             "r_resolved": _r(vb.r), "r_source": vb.r_source, "host": vb.host, "host_floor": vb.host_floor}
        if vb.diag is not None:
            r.update(stretch_max=vb.diag["stretch_max"], n_fp=vb.diag["n_fp"], n_elems_fp=vb.diag["n_elems_fp"])
        if vb.p1 is not None and vb.plane is not None and vb.d_move is not None:
            ol = _vb_outline(np.asarray(vb.p1) - vb.L * vb.t, vb.p1, vb.t, vb.plane[1], vb.d_move, vb.end, frame)
            if ol is not None:
                r["outline_ab"] = ol
        if vb.ok:
            f = vb.field
            if f["idx"].size > int(vc["preview_max_nodes"]):
                r["warnings"].append({"code": "VB_PREVIEW_SKIPPED", "level": "info", "vbead": vb.id,
                                      "n": int(f["idx"].size), "text": msgs.get("VB_PREVIEW_SKIPPED", "")})
            else:
                r["preview"] = {"idx": [int(i) for i in f["idx"]], "vec": np.round(f["vec"], 6).tolist(),
                                "g": np.round(f["g"], 6).tolist(), "c": float(f["c"])}
        rows.append(r)
        if vfr is None and vb.plane is not None:
            ph, nh = vb.plane
            fr = getattr(D, "graph", {}).get("frame") or {}
            exa = np.asarray(frame["e_xi"] if frame else fr.get("e1") or [1, 0, 0], float)
            eya = np.asarray(frame["e_eta"] if frame else fr.get("e2") or [0, 1, 0], float)
            ex, ey = vbm.frame_in_plane((exa, eya), nh)
            org = np.asarray(frame["origin"], float) if frame and frame.get("origin") is not None and \
                len(frame["origin"]) == 3 else ph
            vfr = {"origin": [_r(float(x)) for x in org], "e_xi": [round(float(x), 9) for x in ex],
                   "e_eta": [round(float(x), 9) for x in ey], "n_h": [round(float(x), 9) for x in nh]}
    return rows, vfr
