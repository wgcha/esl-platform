"""V-BG-14 (esl part): package defaults = esl DEFAULTS select.graph, hash views unchanged for default settings."""
import copy

from _bg_util import CFG  # noqa: F401  (sys.path for the package)

from esl.doe import DEFAULTS, bead_select as bs


def _strip(d):
    d = copy.deepcopy(d)
    d.pop("enabled", None)
    return d


def test_defaults_match_package():
    """ESL 기본 = 패키지 기본. 예외(v0.17.4): limits.max_elems 600,000(beadgraph 계약 성능 상한 600k/300 s, 패키지 기본
    250,000 — 패키지 1.0.0 은 안 바꿈, 이슈 #63 현장 ① 메시 267,470 요소)."""
    import beadgraph
    pkg = copy.deepcopy(beadgraph.DEFAULTS)
    assert pkg["limits"]["max_elems"] == 250000 and DEFAULTS["select"]["graph"]["limits"]["max_elems"] == 600000
    pkg["limits"]["max_elems"] = 600000
    assert _strip(DEFAULTS["select"]["graph"]) == pkg


def test_hash_view_default_excludes_graph():
    v = bs.select_hash_view(copy.deepcopy(DEFAULTS["select"]))
    assert "graph" not in v
    sc = copy.deepcopy(DEFAULTS["select"])
    sc["graph"]["island"]["max_mm"] = 55.0
    assert bs.select_hash_view(sc)["graph"]["island"]["max_mm"] == 55.0
    # 통합 v0.17.0: 코어 구현 키 morph.w_smooth_iters 도 다른 graph 키와 같은 규칙(기본 3 = 해시 제외, 아니면 들어감)
    assert DEFAULTS["select"]["graph"]["morph"]["w_smooth_iters"] == 3
    sc = copy.deepcopy(DEFAULTS["select"])
    sc["graph"]["morph"]["w_smooth_iters"] = 5
    assert bs.select_hash_view(sc)["graph"]["morph"]["w_smooth_iters"] == 5


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
                 "BG_ISLAND_HELD", "BG_BASIS_LEAK", "BG_ACHIEVED_MISMATCH", "BG_OUTSIDE_MOVED", "GRAPH_NOT_AVAILABLE",
                 "BG_RANGE_CLAMPED"):
        assert code in m


def test_cell_state_outside():
    from esl.doe import paicad_io as pio
    assert pio.cell_state({"id": "d001", "status": "FAIL", "code": "BG_OUTSIDE_MOVED"})["state"] == "FAILED_MESH"
