"""V-BG-14 (esl part): package defaults = esl DEFAULTS select.graph, hash views unchanged for default settings."""
import copy

from _bg_util import CFG  # noqa: F401  (sys.path for the package)

from esl.doe import DEFAULTS, bead_select as bs


def _strip(d):
    d = copy.deepcopy(d)
    d.pop("enabled", None)
    return d


def test_defaults_match_package():
    import beadgraph
    assert _strip(DEFAULTS["select"]["graph"]) == beadgraph.DEFAULTS


def test_hash_view_default_excludes_graph():
    v = bs.select_hash_view(copy.deepcopy(DEFAULTS["select"]))
    assert "graph" not in v
    sc = copy.deepcopy(DEFAULTS["select"])
    sc["graph"]["island"]["max_mm"] = 55.0
    assert bs.select_hash_view(sc)["graph"]["island"]["max_mm"] == 55.0


def test_schema1_island_unchanged():
    assert DEFAULTS["select"]["island"]["max_mm"] == 40.0          # O-BG-1: schema 1 keeps 40
    assert DEFAULTS["select"]["graph"]["island"]["max_mm"] == 60.0  # D8: graph path 60
    assert bs.ALGO == 3 and bs.RULES == 3 and bs.SCHEMA_VERSIONS == (1, 2)


def test_messages_for_codes():
    from esl.doe import load_messages
    m = load_messages()["messages"]
    for code in ("GRAPH_FAILED", "GRAPH_RASTER_COARSE", "AUTO_HINT_UNAVAILABLE", "BG_GROUP_NOT_CONNECTED",
                 "BG_TIE_NOMINAL", "BG_SEG_UNKNOWN", "BG_EDIT_INVALID", "SELECT_SCHEMA_MISMATCH", "BG_GRAPH_STALE",
                 "BG_GROUP_NOMINAL_SPREAD", "BG_SEGMENT_SHORT", "BG_RAMP_SHORT", "BG_SHARED_CHILD", "BG_CORNER_GUARD",
                 "BG_ISLAND_HELD", "BG_BASIS_LEAK", "BG_ACHIEVED_MISMATCH", "BG_OUTSIDE_MOVED", "GRAPH_NOT_AVAILABLE"):
        assert code in m


def test_cell_state_outside():
    from esl.doe import paicad_io as pio
    assert pio.cell_state({"id": "d001", "status": "FAIL", "code": "BG_OUTSIDE_MOVED"})["state"] == "FAILED_MESH"
