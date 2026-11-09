"""``beadgraph/1`` JSON schema (contract §2.5) as a plain dict + ``validate(graph)`` (ValueError on violation).
Consumers: refuse a different major (``schema`` != beadgraph/1), ignore unknown fields."""
from __future__ import annotations

SCHEMA_MAJOR = "beadgraph/1"

_REQ = {
    "top": ("schema", "version", "rules", "morph_rules", "input", "cfg", "cfg_sha256", "frame", "root", "root_group",
            "floors", "transitions", "networks", "segments", "junctions", "junction_zones", "islands", "holes",
            "warnings"),
    "input": ("n_nodes", "n_elems", "n_tri", "n_fixed", "sha256"),
    "frame": ("n0", "e1", "e2", "h_mm"),
    "floors": ("id", "anchor", "level", "rel_height", "parent", "tier", "kind", "island", "area", "n_elems",
               "outer_free_frac", "network"),
    "transitions": ("id", "upper", "lower", "type", "child", "n_elems"),
    "networks": ("id", "floor", "segments", "junction_zones"),
    "segments": ("id", "anchor", "floor", "parent", "tier", "network", "type", "side", "rel_depth", "D", "entry_width",
                 "floor_width", "length", "open_end", "junctions", "children", "islands", "fixed_n", "n_elems",
                 "skeleton"),
    "junctions": ("id", "type", "plan", "pos", "radius", "segments", "floors", "zone"),
    "junction_zones": ("id", "anchor", "network", "reason", "junctions", "adj_segments", "n_elems"),
    "islands": ("id", "anchor", "floors", "parent", "owner_segment", "size_mm", "rel_height", "lance", "straddle",
                "touch", "fixed", "plan", "n_elems"),
    "holes": ("id", "plan", "center", "d_eq", "area", "circularity", "owner_floor", "owner_island", "lance_slot", "fixed",
              "n_nodes"),
}
ENUMS = {
    "floors.kind": ("base", "base_fragment", "bead", "area", "island"),
    "transitions.type": ("parent-child", "junction", "self", "other"),
    "segments.type": ("ring", "leg", "channel", "pocket", "flare", "corner", "tooth", "spur", "plateau", "area", "base"),
    "segments.side": ("top", "bottom", "left", "right", None),
    "junctions.type": ("T", "X", "L", "W", "Y", "step", "split"),
    "junction_zones.reason": ("junction", "corner", "short_strip", "spur", "step", "split"),
}
SCHEMA = {"$id": SCHEMA_MAJOR, "required": _REQ, "enums": ENUMS}


def validate(graph) -> None:
    def bad(msg):
        raise ValueError(f"beadgraph schema: {msg}")
    if not isinstance(graph, dict):
        bad("graph is not an object")
    sch = graph.get("schema")
    if not isinstance(sch, str) or sch.split("/")[0] != "beadgraph":
        bad(f"schema {sch!r} is not beadgraph/*")
    if sch != SCHEMA_MAJOR:
        bad(f"schema major {sch!r} != {SCHEMA_MAJOR}")
    for k in _REQ["top"]:
        if k not in graph:
            bad(f"missing {k}")
    for sect in ("input", "frame"):
        for k in _REQ[sect]:
            if k not in graph[sect]:
                bad(f"{sect}.{k} missing")
    for sect in ("floors", "transitions", "networks", "segments", "junctions", "junction_zones", "islands", "holes"):
        rows = graph[sect]
        if not isinstance(rows, list):
            bad(f"{sect} is not a list")
        for i, r in enumerate(rows):
            if r.get("id") != i:
                bad(f"{sect}[{i}].id = {r.get('id')} (ids are 0..n-1 in order)")
            for k in _REQ[sect]:
                if k not in r:
                    bad(f"{sect}[{i}].{k} missing")
            for key, allowed in ENUMS.items():
                s, f = key.split(".")
                if s == sect and r.get(f) not in allowed:
                    bad(f"{sect}[{i}].{f} = {r.get(f)!r} not in {allowed}")
    n_f, n_s, n_z = len(graph["floors"]), len(graph["segments"]), len(graph["junction_zones"])
    for s in graph["segments"]:
        if not 0 <= s["floor"] < n_f:
            bad(f"segment {s['id']} floor {s['floor']} out of range")
        if s["skeleton"] is not None and len(s["skeleton"]) > 256:
            bad(f"segment {s['id']} skeleton > 256 points")
    for j in graph["junctions"]:
        if not all(0 <= x < n_s for x in j["segments"]):
            bad(f"junction {j['id']} segment out of range")
        if not -1 <= j["zone"] < n_z:
            bad(f"junction {j['id']} zone out of range")
