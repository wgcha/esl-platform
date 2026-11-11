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


# ---------------------------------------------------------------- V-SG-10 (v0.18.0 STEP_GRAPH 해시)
V0160_CFG_HASH = "760376b6612dbfd19306ae70ecc9b9eb03a6e746d4fd3df6d0ad56bbb75e2aa3"     # {"bead_doe": {"enabled": True}}
V0160_SEL_CFG_SHA = "f418f00122265715f642cf6df2a91c1a4dbcf15184ac13294a333244b11f0d9d"


def _ctx(tmp_path, bead_doe, **doe):
    from esl.doe import stages as stg
    return stg.Ctx({"stage": "bd_eval", "out": str(tmp_path),
                    "doe": {"id": "R1", "scenario": "select", "cfg": {"bead_doe": bead_doe}, "entries": [], **doe}})


def test_step_graph_hash_v0180(tmp_path):
    """기본 설정 ①② 해시 = 상수, step_graph 를 바꿔도 ①② 불변, select_base step 스터디만 바뀜(기본값이면 같음)."""
    from esl.doe import stages as stg
    on = {"enabled": True}
    alt = {"enabled": True, "select": {"step_graph": {"timeout_s": 400, "region": {"mode": "all"}}}}
    for base in (None, "mesh"):
        kw = {"select_base": base} if base else {}
        for bd in (on, alt):
            c = _ctx(tmp_path, bd, **kw)
            assert stg._cfg_hash(c) == V0160_CFG_HASH and stg._sel_cfg_sha(c) == V0160_SEL_CFG_SHA
    c0 = _ctx(tmp_path, on, select_base="step")
    c1 = _ctx(tmp_path, alt, select_base="step")
    assert stg._cfg_hash(c0) == V0160_CFG_HASH and stg._sel_cfg_sha(c0) == V0160_SEL_CFG_SHA
    assert stg._cfg_hash(c1) != V0160_CFG_HASH and stg._sel_cfg_sha(c1) != V0160_SEL_CFG_SHA
    assert "step_graph" not in bs.select_hash_view(copy.deepcopy(DEFAULTS["select"]), step=True)
    assert bs.HASH_NEW_KEYS_V0180 == ("step_graph",)


def test_step_graph_cfg_checks():
    import pytest

    from esl.doe import step_graph as sg
    from esl.errors import EslError
    assert sg.cfg_of({"select": {}})["max_elems"] == 600000 and sg.cfg_of(None)["tria_policy"] == "warn"
    for bad in ({"tria_policy": "x"}, {"max_elems": 0}, {"tria_warn_frac": 0}, {"fixed_transfer": {"mode": "z"}},
                {"fixed_transfer": {"tol_mm": -1}}, {"region": {"mode": "q"}}, {"region": {"min_frac": 1.5}},
                {"timeout_s": 0}, {"fixed_transfer": {"frame_min_holes": 0}},
                {"fixed_transfer": {"frame_match_mm": 0}}, {"fixed_transfer": {"frame_resid_mm": -0.5}}):
        with pytest.raises(EslError) as ei:
            sg.cfg_of({"select": {"step_graph": bad}})
        assert ei.value.code == "CONFIG_INVALID"
