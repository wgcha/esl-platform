"""V-0249-PU-9·13·15(하위 호환): `pos_u` 없는 스냅샷(그래프 select case_once·step_once + 지그 순위) 전 산출물·input_sha256 과 패키지
graph.json·D·W·DF·W1 기저가 3609c921 골든(tests/doe/golden_v0249_c1/golden.json — 코드 변경 전 기록, 다시 기록 금지)과 바이트 동일.
`pos_u` 블록이 있어도 U 변수 0개면 계산 경로 = node — params.json(U 행·u_reason)·derived 요약 외 산출물 = 골든."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0249_c1"))
import golden_pu as G  # noqa: E402

def _cmp(exp, got, unstable, allow=()):
    for k in unstable:
        got.pop(k, None)
        exp = {kk: v for kk, v in exp.items() if kk != k}
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k] and not any(k.endswith(a) for a in allow)]
    assert not diff, diff


@pytest.mark.parametrize("case", sorted(G.CASES))
def test_old_snapshot_bytes(tmp_path, monkeypatch, case):
    gold = G.load()
    got = G.compute(case, str(tmp_path), monkeypatch)
    _cmp(gold["cases"][case], got, gold["unstable"].get(case, []))


# pos_u 블록이 있으면(U 변수 0개라도) 바뀌는 선택 단위 파일 — 계약 §3·§4(params U 행·u_reason, _sel_cfg_sha += pos_u 보기,
# matrix.json load_follow 키, 선택 기저에 U 기저 — work/findings.md "계약 보정 필요" PU-C1-1). 이 파일들은 pos_u 없는 같은 세계와
# 아래 키를 뺀 내용이 같아야 함.
POS_U_KEYS = {"matrix.json": ("load_follow",), "basis.json": ("cfg_sha256", "u_rules", "beadgraph_package", "sha256",
                                                              "basis_sha256", "graph_vars", "vars", "n_vars"),
              "params.json": (), "derived.json": (), "selection.json": ()}


def _strip_keys(o, keys):
    if isinstance(o, dict):
        return {k: _strip_keys(v, keys) for k, v in o.items() if k not in keys}
    if isinstance(o, list):
        return [_strip_keys(v, keys) for v in o]
    return o


def _u_free(o):
    """U 행·u_reason·U 변수를 뺀 내용(params·derived·basis graph_vars)."""
    if isinstance(o, dict):
        return {k: _u_free(v) for k, v in o.items() if k not in ("u_reason",)}
    if isinstance(o, list):
        return [_u_free(v) for v in o if not (isinstance(v, dict) and (v.get("type") == "U" or v.get("kind") == "U"))]
    return o


@pytest.mark.parametrize("case", sorted(G.CASES))
def test_pos_u_block_without_u_vars_is_node_path(tmp_path, monkeypatch, case):
    """V-0249-PU-13: pos_u 블록 + U 변수 0개 = node 경로 — 안·순위·결과·prep·3D 산출물 = 골든, 선택 단위 파일은 pos_u 키·U 행을 뺀
    내용이 같은 세계(pos_u 없음)와 같음, prep/load_follow.json 없음, matrix.json load_follow = node."""
    from esl.doe import DEFAULTS
    pu = {"schema": 1, **DEFAULTS["pos_u"]}
    lf = {"schema": 1, "cell_mm": float(DEFAULTS["load_follow"]["cell_mm"])}
    gold = G.load()
    ta, tb = tmp_path / "a", tmp_path / "b"
    ta.mkdir()
    tb.mkdir()
    _da, oa = G.CASES[case](str(ta), monkeypatch)
    _db, ob = G.CASES[case](str(tb), monkeypatch, {"pos_u": pu, "load_follow": lf})
    got = G.tree_sha(ob, str(tb))
    allow = tuple(POS_U_KEYS)
    _cmp(gold["cases"][case], dict(got), gold["unstable"].get(case, []), allow=allow + ("basis.npz", "basis.bin",
                                                                                      "derived.npz"))
    assert not any(k.endswith("load_follow.json") for k in got)
    for rel in got:
        name = rel.rsplit("/", 1)[-1]
        if name not in POS_U_KEYS or not os.path.isfile(os.path.join(oa, rel)):
            continue
        a = json.load(open(os.path.join(oa, rel), encoding="utf-8"))
        b = json.load(open(os.path.join(ob, rel), encoding="utf-8"))
        if name == "matrix.json":
            assert b.get("load_follow") == "node"
        keys = set(POS_U_KEYS[name]) | {"created_at", "seconds"}
        assert _u_free(_strip_keys(a, keys)) == _u_free(_strip_keys(b, keys)), rel


@pytest.mark.slow
def test_package_bases_unchanged():
    import beadgraph as bg
    assert bg.OUTPUT_VERSION == "1.1.0" and bg.MORPH_RULES == 2 and bg.RULES == 1
    assert bg.DF_RULES == 1 and bg.W1_RULES == 1
    gold = G.load()["package"]
    assert G.package_bases() == gold


def test_golden_recorded_before_code_change():
    gold = G.load()
    assert "3609c921" in gold["made_by"]
    assert json.dumps(gold["package"])                      # 패키지 항목 있음
