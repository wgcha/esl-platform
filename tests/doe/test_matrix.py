"""V-BD-1 (코어): DOE 생성 — LHS·Halton·풀 팩토리얼 범위·층 성질, 결정성(입력 순서 섞기 10회), 반올림·중복·공칭 제거,
max_designs 경계, D·W 하한·lo≥hi 422 코드, feasible 밖 경고, 미리보기 입력(cells·thumb_options)."""
import random

import numpy as np
import pytest

from esl.doe import matrix as mx
from esl.doe import settings
from esl.errors import EslError

CFG = settings()


def table():
    rows = []
    for k in (1, 2):
        rows += [
            {"name": f"CR_BEAD_D_{k}", "type": "D", "nominal": 4.0, "feasible": [2.0, 6.5], "use_default": True},
            {"name": f"CR_BEAD_W_{k}", "type": "W", "nominal": 12.0, "feasible": [9.0, 16.0], "use_default": True},
            {"name": f"CR_BEAD_U_{k}", "type": "U", "nominal": 0.0, "feasible": [-10.0, 10.0], "use_default": True},
        ]
    return rows


def spec(method="lhs", n=20, seed=7, params=None, **kw):
    p = params or [{"name": "CR_BEAD_D_1", "lo": 3.0, "hi": 6.0}, {"name": "CR_BEAD_W_1", "lo": 10.0, "hi": 16.0},
                   {"name": "CR_BEAD_D_2", "lo": 2.5, "hi": 5.5}]
    s = {"method": method, "seed": seed, "params": p, **kw}
    if method != "fullfact":
        s["n"] = n
    return s


@pytest.mark.parametrize("method", ["lhs", "halton", "fullfact"])
def test_ranges_and_nominal(method):
    m = mx.generate(spec(method, levels=3) if method == "fullfact" else spec(method), table(), CFG)
    assert m["designs"][0]["id"] == "d000"
    assert m["designs"][0]["values"] == {"CR_BEAD_D_1": 4.0, "CR_BEAD_D_2": 4.0, "CR_BEAD_W_1": 12.0}
    lims = {p["name"]: (p["lo"], p["hi"]) for p in m["spec"]["params"]}
    for d in m["designs"][1:]:
        for k, v in d["values"].items():
            assert lims[k][0] - 1e-9 <= v <= lims[k][1] + 1e-9
            assert abs(v / 0.01 - round(v / 0.01)) < 1e-6          # round_mm 격자
    ids = [d["id"] for d in m["designs"]]
    assert ids == [f"d{i:03d}" for i in range(len(ids))]
    assert m["n_designs"] == len(ids)


def test_lhs_one_point_per_stratum():
    s, _ = mx.normalize_spec(spec("lhs", n=25), table(), CFG)
    u = mx.unit_samples(s)
    assert u.shape == (25, 3)
    for j in range(3):
        strata = np.floor(u[:, j] * 25).astype(int)
        assert sorted(strata.tolist()) == list(range(25))


def test_determinism_shuffled_inputs():
    base = spec("lhs", n=30, seed=11)
    ref = mx.generate(base, table(), CFG)
    rng = random.Random(0)
    for _ in range(10):
        p = list(base["params"])
        rng.shuffle(p)
        tb = table()
        rng.shuffle(tb)
        m = mx.generate(dict(base, params=p), tb, CFG)
        assert m["matrix_sha256"] == ref["matrix_sha256"]
        assert m["designs"] == ref["designs"]
    h1 = mx.generate(spec("halton", n=16, seed=3), table(), CFG)
    h2 = mx.generate(spec("halton", n=16, seed=3), table(), CFG)
    assert h1["matrix_sha256"] == h2["matrix_sha256"]
    assert mx.generate(spec("lhs", n=30, seed=12), table(), CFG)["matrix_sha256"] != ref["matrix_sha256"]


def test_fullfact_dedup_nominal_and_count():
    # 수준 3: D_1 ∈ {3, 4.5, 6}, W_1 ∈ {10, 12, 14} — (D 공칭 4 아님) 중복 없음 → 9안
    p = [{"name": "CR_BEAD_D_1", "lo": 3.0, "hi": 6.0}, {"name": "CR_BEAD_W_1", "lo": 10.0, "hi": 14.0}]
    m = mx.generate({"method": "fullfact", "levels": 3, "params": p}, table(), CFG)
    assert m["n_designs"] == 10 and m["dropped_duplicates"] == 0
    # 공칭이 격자점이면 그 안은 제거(d000 과 같음): D_1 [2, 6] 수준 3 → {2, 4, 6}, W_1 [10, 14] → {10, 12, 14}
    p2 = [{"name": "CR_BEAD_D_1", "lo": 2.0, "hi": 6.0}, {"name": "CR_BEAD_W_1", "lo": 10.0, "hi": 14.0}]
    m2 = mx.generate({"method": "fullfact", "levels": 3, "params": p2}, table(), CFG)
    assert m2["n_designs"] == 9 and m2["dropped_duplicates"] == 1
    vals = [tuple(sorted(d["values"].items())) for d in m2["designs"]]
    assert len(set(vals)) == len(vals)


def test_rounding_creates_duplicates_dropped():
    cfg = settings({"bead_doe": {"doe": {"round_mm": 1.0}}})
    p = [{"name": "CR_BEAD_D_1", "lo": 3.0, "hi": 4.4}]
    m = mx.generate({"method": "lhs", "n": 40, "seed": 1, "params": p}, table(), cfg)
    # 1 mm 격자: 값 3·4(=공칭 → 제거) 만 가능 → d000 + 3.0 한 안
    assert [d["values"]["CR_BEAD_D_1"] for d in m["designs"]] == [4.0, 3.0]
    assert m["dropped_duplicates"] == 39


def test_max_designs_boundary():
    cfg = settings({"bead_doe": {"max_designs": 10}})
    mx.generate(spec("lhs", n=9), table(), cfg)                      # 9 + 1 = 10 허용
    with pytest.raises(EslError) as ei:
        mx.generate(spec("lhs", n=10), table(), cfg)
    assert ei.value.code == "DOE_TOO_LARGE"
    with pytest.raises(EslError) as ei:                                # 3^3 + 1 = 28 > 10
        mx.generate({"method": "fullfact", "levels": 3, "params": spec()["params"]}, table(), cfg)
    assert ei.value.code == "DOE_TOO_LARGE"


@pytest.mark.parametrize("bad,code", [
    ({"name": "CR_BEAD_D_1", "lo": 0.0, "hi": 5.0}, "DOE_RANGE_INVALID"),
    ({"name": "CR_BEAD_W_1", "lo": -1.0, "hi": 5.0}, "DOE_RANGE_INVALID"),
    ({"name": "CR_BEAD_D_1", "lo": 5.0, "hi": 5.0}, "DOE_RANGE_INVALID"),
    ({"name": "CR_BEAD_D_1", "lo": 6.0, "hi": 5.0}, "DOE_RANGE_INVALID"),
    ({"name": "CR_BEAD_X_9", "lo": 1.0, "hi": 5.0}, "DOE_PARAM_UNKNOWN"),
])
def test_validation_codes(bad, code):
    with pytest.raises(EslError) as ei:
        mx.generate(spec(params=[bad]), table(), CFG)
    assert ei.value.code == code


def test_position_may_be_negative_and_other_errors():
    mx.generate(spec(params=[{"name": "CR_BEAD_U_1", "lo": -5.0, "hi": 5.0}]), table(), CFG)
    with pytest.raises(EslError) as ei:
        mx.generate({"method": "lhs", "n": 5, "params": []}, table(), CFG)
    assert ei.value.code == "DOE_NO_PARAMS"
    for s in (spec(method="sobol"), spec(n=1), spec(seed=-1), spec(seed=2 ** 32),
              {"method": "fullfact", "levels": 10, "params": spec()["params"]},
              {"method": "fullfact", "levels": 1, "params": spec()["params"]}):
        with pytest.raises(EslError) as ei:
            mx.generate(s, table(), CFG)
        assert ei.value.code == "DOE_RANGE_INVALID"


def test_feasible_warning_not_blocking():
    m = mx.generate(spec(params=[{"name": "CR_BEAD_D_1", "lo": 1.0, "hi": 7.0},
                                 {"name": "CR_BEAD_W_1", "lo": 10.0, "hi": 12.0}]), table(), CFG)
    assert m["warnings"] == [{"code": "RANGE_OUTSIDE_FEASIBLE", "name": "CR_BEAD_D_1", "feasible": [2.0, 6.5]}]


def test_default_spec_and_preview_files():
    tb = table()
    tb[0]["use_default"] = False
    ds = mx.default_spec(tb, CFG)
    names = [p["name"] for p in ds["params"]]
    assert names == ["CR_BEAD_D_2", "CR_BEAD_W_1", "CR_BEAD_W_2"]          # U 기본 제외, use_default false 제외
    assert ds["params"][0]["lo"] == 2.0 and ds["params"][0]["hi"] == 6.5     # 기본 범위 = feasible
    assert ds["method"] == "lhs" and ds["n"] == 30 and ds["seed"] == 1
    m = mx.generate(ds, tb, CFG)
    cells = mx.cells_doc(m)
    assert cells["schema_version"] == 1 and all(c["id"] != "d000" for c in cells["cells"])
    assert len(cells["cells"]) == m["n_designs"] - 1
    fr = {"n": [0.0, 1.0, 0.0], "e_eta": [0.0, 0.0, 1.0]}
    th = mx.thumb_options(CFG, fr, m["spec"], tb)
    assert th["w"] == 320 and th["h"] == 240 and th["colormap"] == "turbo16"
    assert abs(np.linalg.norm(th["view_dir"]) - 1) < 1e-12
    assert th["view_dir"][2] < 0 and th["view_dir"][1] > 0.9                 # n 을 −η 쪽으로 20°
    assert th["disp_range_mm"] == [0.0, 2.5]                                 # D_2 max(|6.5−4|, |2−4|)
    assert mx.values_doc({"b": 1, "a": 2.5}) == {"schema_version": 1, "values": {"a": 2.5, "b": 1.0}}
    assert mx.param_type("CHASSIS_REAR_BEAD_W_3") == "W" and mx.param_type("X") is None
