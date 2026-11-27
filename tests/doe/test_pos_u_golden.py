"""V-0249-PU-9·13·15(하위 호환): `pos_u` 없는 스냅샷(그래프 select case_once·step_once + 지그 순위) 전 산출물·input_sha256 과 패키지
graph.json·D·W·DF·W1 기저가 3609c921 골든(tests/doe/golden_v0249_c1/golden.json — 코드 변경 전 기록, 다시 기록 금지)과 바이트 동일.
`pos_u` 블록이 있어도 U 변수 0개면 계산 경로 = node — params.json(U 행·u_reason)·derived 요약 외 산출물 = 골든."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0249_c1"))
import golden_pu as G  # noqa: E402

# v0.25.1(계약 esl_view3d_scene_legend.md V-0251-10 개정·§5.9 INT): 새로 만든 report.html 은 색·범례 문구만 바뀜 — 바이트 비교에서 뺌
# (파일 목록에는 그대로 있어야 함, 색 외 내용 = V-0251-43·44). 다른 파일 바이트 비교는 그대로.
PICTURE_V0251 = ("report.html",)


def _cmp(exp, got, unstable, allow=()):
    for k in unstable:
        got.pop(k, None)
        exp = {kk: v for kk, v in exp.items() if kk != k}
    assert sorted(got) == sorted(exp)
    diff = [k for k in exp if got[k] != exp[k] and not any(k.endswith(a) for a in allow) and not k.endswith(PICTURE_V0251)]
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


# ---------------------------------------------------------------- v0.24.9 §5-13 정정(INT-6·PU-C1-1): U 가능한 비드가 있는 모형(채널)
# pos_u 블록 + U 변수 0개 vs pos_u 없음 — 안·순위·결과·prep·3D 같음, 아래 파일만 다름(허용 차이 목록 — 이 목록 밖 차이 = 실패).
# done.json input_sha256·selection.json basis_sha256 = U 기저가 선택 기저(basis)에 들어가서(sha 가 달라짐 — 결과·순위 동일),
# report.html = 변수 표 U 행 + 그 비드 경고 칸의 SELECT_BLEND_CLIPPED(U 기저 계산 정보). 옛 스냅샷(pos_u 없음) 바이트 = test_old_snapshot_bytes.
CHANNEL_U0_ALLOWED = {
    r"run/designs/d\d{3}/done\.json": ("input_sha256",),
    r"doe/1/selection\.json": ("basis_sha256",),
    r"best/d\d{3}/selection\.json": ("basis_sha256",),
    r"doe/1/matrix\.json": ("load_follow",),
    r"select/[0-9a-f]{12}/(basis\.json|params\.json|derived\.json)": None,      # pos_u 키·U 행을 뺀 내용 같음
    r"select/[0-9a-f]{12}/(basis\.npz|basis\.bin|derived\.npz)": None,          # U 기저 배열
    r"report\.html": None,                                                     # U 행 + SELECT_BLEND_CLIPPED
}
# params.json·derived.json 의 U 관련 차이(허용): U 행·u_reason·range_default/feasible["U"], 비드 경고 SELECT_BLEND_CLIPPED(U 기저 띠 자름
# 정보), 선택 경고 SELECT_RANGE_COMBO 의 조합 점검에 U 변수가 끼어 vars·corners·inverted_n·usable[B*_U] 가 바뀜(D·W usable 은 같음).
CHANNEL_U0_INFO = ("SELECT_BLEND_CLIPPED",)
CHANNEL_U0_COMBO = ("SELECT_RANGE_COMBO", ("corners", "inverted_n"))
CHANNEL_UNSTABLE = {"prep/base.json": ("mtime", "path"), "post/jig_view.json": ("view3d_src_seconds",)}   # 실행 시각·초·폴더


def _channel_tree(tmp: str, extra: dict | None):
    import synth_pos_u as W
    from esl.library import _util as U
    os.makedirs(tmp, exist_ok=True)
    doe, out, run, _mesh = W.world(tmp, extra=extra)
    run("bd_matrix", rev=1, spec={"method": "fullfact", "levels": 3, "params": [{"name": "B1_D", "lo": 8.0, "hi": 12.0}]})
    for x in U.read_json(os.path.join(out, "doe", "1", "matrix.json"))["designs"]:
        assert run("bd_eval", rev=1, design=x["id"])["status"] == "OK"
    run("bd_post", rev=1)
    return out, W.params(out, doe)


def _u0_norm(o):
    """params·derived 의 허용 차이(CHANNEL_U0_INFO·CHANNEL_U0_COMBO·U 범위 키)를 뺀 내용."""
    isu = (lambda v: isinstance(v, str) and v.endswith("_U"))
    if isinstance(o, dict):
        if o.get("code") == CHANNEL_U0_COMBO[0]:
            o = {k: v for k, v in o.items() if k not in CHANNEL_U0_COMBO[1]}
            o["vars"] = [v for v in o.get("vars") or [] if not isu(v)]
            o["usable"] = {k: v for k, v in (o.get("usable") or {}).items() if not isu(k)}
        out = {}
        for k, v in o.items():
            if k in ("range_default", "range_feasible", "range_basis") and isinstance(v, dict):
                v = {kk: vv for kk, vv in v.items() if kk != "U"}
            out[k] = _u0_norm(v)
        return out
    if isinstance(o, list):
        return [_u0_norm(v) for v in o if not (isinstance(v, dict) and v.get("code") in CHANNEL_U0_INFO)]
    return o


def _jload(p, drop=()):
    return _strip_keys(G._strip(json.load(open(p, encoding="utf-8"))), set(drop))


def test_channel_pos_u_block_u0_allowed_diffs(tmp_path):
    """§5-13(정정): U 가능한 비드(채널 B1 — U 행 있음)가 있는 모형에서 pos_u 켜짐·U 변수 0개 = 안·순위·결과·prep·3D·post 바이트 같음,
    다른 파일 = CHANNEL_U0_ALLOWED 목록과 정확히 같고 각 파일 차이는 목록의 키(·U 행)뿐."""
    import re

    from esl.doe import DEFAULTS
    pu = {"schema": 1, **DEFAULTS["pos_u"]}
    lf = {"schema": 1, "cell_mm": float(DEFAULTS["load_follow"]["cell_mm"])}
    ta, tb = str(tmp_path / "a"), str(tmp_path / "b")
    oa, _pa = _channel_tree(ta, None)
    ob, pb = _channel_tree(tb, {"pos_u": pu, "load_follow": lf})
    assert any(p["name"] == "B1_U" for p in pb["params"])                  # U 가능한 비드 실재(U 변수는 행렬에 0개)
    a, b = G.tree_sha(oa, ta), G.tree_sha(ob, tb)
    assert sorted(a) == sorted(b)
    for rel, drop in CHANNEL_UNSTABLE.items():
        assert _jload(os.path.join(oa, rel), drop) == _jload(os.path.join(ob, rel), drop), rel
    diff = sorted(k for k in a if a[k] != b[k] and k not in CHANNEL_UNSTABLE)
    pats = [re.compile(p + "$") for p in CHANNEL_U0_ALLOWED]
    assert not [k for k in diff if not any(p.match(k) for p in pats)], diff
    hit = {p.pattern for p in pats if any(p.match(k) for k in diff)}
    assert hit == {p.pattern for p in pats}, set(CHANNEL_U0_ALLOWED) - {h[:-1] for h in hit}   # 목록이 실제와 같음(고정)
    for k in ("post/result.json", "post/ranking.csv", "post/designs.json", "post/per_esl.json"):
        assert k in a and a[k] == b[k], k                                    # 결과·순위 같음
    for rel in diff:
        drop = next(v for p, v in CHANNEL_U0_ALLOWED.items() if re.match(p + "$", rel))
        pa_, pb_ = os.path.join(oa, rel), os.path.join(ob, rel)
        if drop is not None:
            ja, jb = _jload(pa_), _jload(pb_)
            assert {k for k in set(ja) | set(jb) if ja.get(k) != jb.get(k)} == set(drop), rel   # 다른 최상위 키 = 목록 그대로
            assert _strip_keys(ja, set(drop)) == _strip_keys(jb, set(drop)), rel
        elif rel.endswith(".json"):
            name = rel.rsplit("/", 1)[-1]
            keys = set(POS_U_KEYS[name]) | {"created_at", "seconds"}
            assert _u0_norm(_u_free(_strip_keys(_jload(pa_), keys))) == _u0_norm(_u_free(_strip_keys(_jload(pb_), keys))), rel
        elif rel == "report.html":
            ha = open(pa_, encoding="utf-8").read().replace(ta, "<ROOT>")
            hb = open(pb_, encoding="utf-8").read().replace(tb, "<ROOT>")
            hb = re.sub(r"<tr>\s*<td>B1_U</td>.*?</tr>\s*", "", hb, flags=re.S).replace(", SELECT_BLEND_CLIPPED", "")
            sec = re.compile(r"[0-9]+\.[0-9]+ ?s\b")
            assert sec.sub("<S>", ha) == sec.sub("<S>", hb)
