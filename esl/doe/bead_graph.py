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
  normalize_v2(sel, graph, cfg, *, labels, mesh=None, current_sha=None) -> (norm, sha256)   422 / 409 codes below
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
          "beadgraph_version": bg.__version__, "n_segments": 0, "n_junction_zones": 0, "n_islands": 0,
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


def _cfg_key(cfg) -> str:
    """sha of the select settings the W basis and the inversion judgement read (range · quality · graph · hold · blend),
    numbers as floats (API and worker settings dicts may spell 1 / 1.0 differently): a table made under another setting
    is not applied."""
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
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _seg_keys(g: dict, ids) -> list:
    return [[int(g["segments"][s]["anchor"]), int(g["segments"][s]["n_elems"])] for s in ids]


def _inward(v: float, nom: float) -> float:
    """round a usable end to 1e-4 toward the nominal (a rounded end never lands on the inverting side)."""
    q = v * 1e4
    return float((np.ceil(q - 1e-9) if v < nom else np.floor(q + 1e-9)) / 1e4)


def w_clamp_table(mesh: dict, graph: dict, labels: dict, fixed_ids, cfg: dict | None) -> dict:
    """Verifier fix v0.17.0 (§12 BG-X-1): before any matrix exists, find for every W-capable graph bead candidate — each
    segment with an entry width + each auto-seed W group (channel + flare) — the non-inverting part of its default W
    range, exactly as BD_MATRIX ``range_check`` would (same basis: package ``basis`` through ``basis_v2``, ramp frozen
    at the original default range; same inversion rule ``design_state``; ``range.check_steps`` bisections). Only
    candidates whose default range inverts get an entry. Deterministic."""
    from esl.doe import bead_select as bs
    sc = select_cfg(cfg)
    doc = {"schema": W_CLAMP_SCHEMA, "graph_sha256": graph_sha_of(graph), "cfg_sha256": _cfg_key(cfg),
           "hold": 1, "entries": []}
    steps = int(sc["range"]["check_steps"] or 0)
    if steps <= 0:
        return doc
    cands, seen = [], set()
    for s in graph["segments"]:
        if s["type"] != "base" and s.get("entry_width") is not None:
            cands.append([s["id"]])
    sel, _sym, _aw = auto_seed(graph, labels, cfg)
    for b in sel["beads"]:
        ids, _z, net = _resolve_segs(graph, labels, b["segs"], b["id"])
        if not net and len(ids) > 1 and all(graph["segments"][x]["entry_width"] is not None for x in ids):
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
    D = derive_obj_v2(mesh, norm, cfg, graph, labels, fixed_node_ids=fixed_ids)
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


def write_w_clamp(path: str, doc: dict, guard=None) -> str:
    g = guard or (lambda p: p)
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    with open(g(path), "wb") as fh:
        fh.write(blob)
    return hashlib.sha256(blob).hexdigest()


def _apply_w_clamp(D, norm: dict, w_clamp: dict | None, cfg, user_free: bool) -> None:
    """derive: graph beads whose W default range was found to invert in BD_LOADS (``w_clamp_table``) get the usable
    range as default and the inverting side of ``feasible`` clamped, + info BG_RANGE_CLAMPED (§12 BG-X-1) — so the
    first matrix never carries an inverting W design. Applied only when the table matches (same graph sha, same select
    settings, no toggle edit, no fixed_user / exclude, bead hold 1, same segments and default range); otherwise the
    BD_MATRIX clamp (``clamp_w_ranges``) still applies. Tied beads: the carrier's range = the members' common Δ."""
    if not w_clamp or not w_clamp.get("entries") or not user_free:
        return
    ng = norm.get("graph") or {}
    if (ng.get("edits") or {}).get("toggle") or w_clamp.get("graph_sha256") != ng.get("sha256") or \
            w_clamp.get("cfg_sha256") != _cfg_key(cfg):
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


def _possible_vars(graph, seg_ids) -> list[str]:
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
                 mesh: dict | None = None, current_sha: str | None = None) -> tuple[dict, str]:
    """SelectionIn schema 2 -> (normalized, sha256). Graph beads are validated against the edited graph.
    graph None (GRAPH_FAILED) = elems beads only (a graph bead -> BG_SEG_UNKNOWN); labels are required with a graph."""
    from esl.doe import bead_select as bs
    sc = select_cfg(cfg)
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
    if not isinstance(beads, list) or not 1 <= len(beads) <= int(sc["max_beads"]):
        _bad("SELECT_EMPTY_TIER", f"beads 는 1..{sc['max_beads']} 개")
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
        poss = ["D"] if net else _possible_vars(g2, ids)
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
        _check_ties(g2, l2, out_beads, ties, sc)
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
    js = bs.canonical_json(norm)
    if len(js) > int(sc["max_selection_kb"]) * 1024:
        _bad("SELECT_TOO_LARGE", f"정규화 선택 {len(js) // 1024} KB")
    return norm, bs.selection_sha256(norm)


def _bead_nominals(g, l, b):
    ids, _z, net = _resolve_segs(g, l, b["segs"], b["id"])
    lens = np.array([float(g["segments"][s]["length"] or 1.0) for s in ids])
    D = float(np.sum(lens * np.array([float(g["segments"][s]["D"]) for s in ids])) / lens.sum())
    ws = [g["segments"][s]["entry_width"] for s in ids]
    W = None if net or any(w is None for w in ws) else float(np.sum(lens * np.array(ws, float)) / lens.sum())
    return D, W


def _check_ties(g, l, beads, ties, sc):
    tol = float(sc["graph"]["sym_tol_mm"])
    by = {b["id"]: b for b in beads}
    for grp in ties:
        if any(by[x]["src"] != "graph" for x in grp):
            _bad("BG_TIE_NOMINAL", "대칭 묶기는 그래프 비드만", beads=grp)
        nom = [_bead_nominals(g, l, by[x]) for x in grp]
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
              fixed_scan=(), bead: str | None = None, index=None, w_clamp: dict | None = None) -> dict:
    """(Backend API) normalized schema 2 selection -> SelectionDerived dict: beads, fixed, warnings, graph block
    (§6.1), graph_algo, slope_suggested, islands_suggested, fixed_ab, params (DoeParamsOut rows) + param_beads.
    ``bead`` is accepted for signature parity (the whole selection is derived — graph beads are cheap)."""
    from esl.doe import bead_select as bs
    D = derive_obj_v2(mesh, norm, cfg, graph, labels, fixed_node_ids=fixed_scan, index=index, w_clamp=w_clamp)
    doc = D.summary(frame)
    for k in ("rev", "sha256", "mesh_sha256"):
        doc.pop(k, None)
    doc["slope_suggested"] = D.slope_suggested()
    doc["islands_suggested"] = D.islands_suggested()
    doc["fixed_ab"] = bs._fixed_ab(D, frame) if frame is not None else []
    doc["params"] = params_rows_v2(D, cfg)
    doc["param_beads"] = param_beads(D)
    return doc


def param_beads(D) -> list[dict]:
    """params.json ``beads`` rows (same shape as the core BD_MATRIX file)."""
    return [{"id": b.id, "name": b.name, "kind": "select", "src": getattr(b, "src", "elems"),
             "n_tiers": len(b.tiers), "W_nom": _r(getattr(b, "W_nom", None)), "W_min": _r(getattr(b, "W_min", None)),
             "W_max": _r(getattr(b, "W_max", None)), "blend_mm": _r(getattr(b, "blend_mm", None)),
             "warnings": b.warnings} for b in D.beads]


def derive_obj_v2(mesh: dict, norm: dict, cfg: dict | None, graph: dict | None, labels: dict | None, *,
                  fixed_node_ids=(), index=None, mesh_sha256: str | None = None,
                  w_clamp: dict | None = None) -> GraphDerived:
    """normalized schema 2 selection -> GraphDerived (arrays — worker basis / tests)."""
    from esl.doe import bead_select as bs
    from esl.mesh import features
    sc = select_cfg(cfg)
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
                           with_section=False)
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
        gb.tier = int(g2["segments"][ids[0]]["tier"])
        gb.vars = b.get("vars") or (["D"] if net else _possible_vars(g2, ids))
        gb.hold_fixed = int(b.get("hold_fixed", 1))
        D, W = _bead_nominals(g2, l2, b)
        gb.D_nom, gb.W_nom = D, (W if "W" in gb.vars else None)
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
    _apply_w_clamp(D, norm, w_clamp, cfg, user_free=not excl.any() and np.asarray(fu_nodes).size == 0)
    D.fixed_mask = fixed_mask
    D.exclude_mask = excl
    D.norm_cfg_tol = float(sc["graph"]["sym_tol_mm"])
    D.cfg1 = cfg1
    return D


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
            nom = b.D_nom if typ == "D" else b.W_nom
            out.append({"name": var_name(b.id, typ), "type": typ, "bead": b.id, "tier": b.tier, "nominal": _r(nom),
                        "feasible": list(b.range_feasible[typ]), "feasible_source": "estimate",
                        "default_range": list(b.range_default[typ]),
                        "use_default": not any(w.get("code") == "BG_SEGMENT_SHORT" and w.get("var") ==
                                               var_name(b.id, typ) for w in b.warnings),
                        "group_members": [var_name(x, typ) for x in (grp or [b.id])]})
    out.sort(key=lambda r: r["name"])
    return out


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
        for typ in b.vars:
            pk_list.append({"name": var_name(b.id, typ), "kind": typ, "segs": b.seg_ids, "zones": b.zone_ids,
                            "hold": b.hold_fixed, "bead": b.id})
    ranges = {}
    for p in pk_list:
        b0 = by[p["bead"]]
        carrier = (tie.get(b0.id) or [b0.id])[0]
        r = rows[var_name(carrier, p["kind"])]
        nom = b0.D_nom if p["kind"] == "D" else b0.W_nom
        rb = (getattr(by.get(carrier), "range_basis", None) or {}).get(p["kind"])
        lo, hi = (float(v) for v in (rb or r["default_range"]))   # original default range (BD_LOADS clamp keeps L)
        ext = max(abs(hi - float(r["nominal"])), abs(lo - float(r["nominal"])))
        ranges[p["name"]] = [nom - ext, nom + ext]
    gB = bg.basis(g, lx, X, pk_list, ranges, cfg=mc, fixed=fx, elems=C) if pk_list else []
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
        if v["info"].get("short"):
            b0.warnings.append({"code": "BG_SEGMENT_SHORT", "bead": b0.id, "var": v["name"],
                                "length_mm": _r(sum(float(g["segments"][s]["length"] or 0.0) for s in b0.seg_ids)),
                                "ramp_mm": _r(v["info"]["ramp_mm"])})
            continue
        lo, hi = ranges[v["name"]]
        for end in (lo, hi):
            x = bg.morph(X, [v], {v["name"]: end})
            err = achieved(g, lx, X, x, [v], {v["name"]: end}).get(v["name"])
            lim = tol if v["kind"] == "D" else 1e-3
            if err is not None and err > lim:
                _bad("BG_ACHIEVED_MISMATCH", f"{v['name']}: 달성 오차 {err:.3g} mm", var=v["name"], err_mm=err)
    derived.graph_basis = gB
    # wrap: ties -> one variable = sum of the tied beads' bases (same delta)
    n = X.shape[0]
    by_name = {v["name"]: v for v in gB}
    for name, row in rows.items():
        if row["bead"] not in by or by[row["bead"]].src != "graph":
            continue
        members = row["group_members"]
        full = np.zeros((n, 3))
        zone = np.zeros(n, bool)
        allowed = np.zeros(n, bool)
        for m in members:
            v = by_name.get(m)
            if v is None:
                continue
            full[v["idx"]] += v["vec"]
            zone[v["zone"]] = True
            allowed |= strict[m]
        idx = np.flatnonzero(np.any(full != 0.0, axis=1))
        b0 = by[row["bead"]]
        vars_.append({"name": name, "type": row["type"], "bead": row["bead"], "tier": row["tier"],
                      "members": members, "nominal": float(row["nominal"]), "n_hat": b0.n_hat,
                      "R": (by_name[name]["info"].get("blend_mm") if name in by_name else None),
                      "idx": idx.astype(np.int32), "vec": full[idx], "zone": np.flatnonzero(zone).astype(np.int64),
                      "allowed": np.flatnonzero(allowed).astype(np.int64)})
    vars_.sort(key=lambda v: v["name"])
    B = bs.Basis(vars_, n, derived.sha256)
    B.graph_algo = GRAPH_ALGO
    return B


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
