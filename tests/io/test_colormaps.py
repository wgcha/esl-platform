"""v0.25.1 색 지도 공용 자원(계약 esl_view3d_scene_legend.md §5.8) — V-0251-37·38·39 파이썬 쪽.

37 자원 한 곳: 파이썬 esl/backend/worker 에 색 정점 리터럴 없음, ``colormaps.json`` 을 여는 곳 = ``esl/io/colormaps.py`` 1개.
38 정점 일치: ``table(map, 256)`` 768바이트 sha256 = 자원 ``check``(지도 3개 — TS 쪽도 같은 값을 통과해야 함).
39 보간 규칙: 정점 정확·div 0.5 = 흰·자름·NaN = 0·floor(x + 0.5)(x.5 경계)·div 정점 짝수/center 없음 = CONFIG_INVALID.
"""
import copy
import hashlib
import json
import os
import re

import numpy as np
import pytest

from esl.errors import EslError
from esl.io import colormaps as cm

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "resources", "colormaps.json")


def _raw():
    with open(RES, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- V-0251-38
@pytest.mark.parametrize("role,name", [("seq", "rainbow"), ("div", "diverge"), ("region", "blues")])
def test_v0251_38_check_hash(role, name):
    m = cm.map_for(role)
    assert m["name"] == name
    tab = cm.table(m, 256)
    assert tab.shape == (256, 3) and tab.dtype == np.uint8 and tab.nbytes == 768
    assert hashlib.sha256(tab.tobytes()).hexdigest() == _raw()["maps"][name]["check"]


# ---------------------------------------------------------------- V-0251-39
def test_v0251_39_interp_rules():
    raw = _raw()
    for role in ("seq", "div", "region"):
        m = cm.map_for(role)
        st = raw["maps"][m["name"]]["stops"]
        n = len(st)
        got = cm.rgb(m, np.arange(n) / (n - 1))                           # 정점 위치 = 정점 그대로
        assert got.tolist() == st
        assert cm.rgb(m, 0.0).tolist() == st[0] and cm.rgb(m, 1.0).tolist() == st[-1]
        assert cm.rgb(m, -3.0).tolist() == st[0] and cm.rgb(m, 7.5).tolist() == st[-1]     # 범위 밖 = 자름
        assert cm.rgb(m, np.nan).tolist() == st[0]                                          # NaN = t 0
        assert cm.rgb(m, np.inf).tolist() == st[-1] and cm.rgb(m, -np.inf).tolist() == st[0]
    d = cm.map_for("div")
    assert cm.rgb(d, 0.5).tolist() == [247, 247, 247] and d["center"] == 0.5
    s = cm.map_for("seq")
    assert cm.rgb(s, 0.5).tolist() == [0, 255, 0]                          # 레인보우 가운데 = 초록
    assert cm.rgb(s, 0.0).tolist() == [0, 0, 255] and cm.rgb(s, 1.0).tolist() == [255, 0, 0]
    # 반올림 = floor(x + 0.5) — x.5 는 올림(파이썬 round 의 짝수 반올림 아님)
    m2 = {"stops": [[0, 0, 0], [1, 3, 5]]}
    assert cm.rgb(m2, 0.5).tolist() == [1, 2, 3]                           # 0.5→1, 1.5→2, 2.5→3 (round 이면 0, 2, 2)
    assert cm.rgb(m2, 0.25).tolist() == [0, 1, 1]                          # 0.25→0, 0.75→1, 1.25→1
    # 배열 입력 모양
    assert cm.rgb(s, np.zeros((2, 3))).shape == (2, 3, 3)
    assert cm.css(s, 1.0) == "rgb(255,0,0)" and cm.css(d, 0.5) == "rgb(247,247,247)"
    assert cm.special("nan") == (154, 161, 171) and cm.special("out") == (90, 96, 106)
    assert cm.special("none") == (200, 200, 200)
    js = cm.as_json(("seq", "div"))
    assert js["seq"]["stops"] == raw["maps"]["rainbow"]["stops"] and js["div"]["stops"] == raw["maps"]["diverge"]["stops"]
    assert js["div"]["center"] == 0.5 and js["interp"] == "srgb-linear"


@pytest.mark.parametrize("mut", [
    lambda d: d["maps"]["diverge"]["stops"].pop(),                        # div 정점 짝수
    lambda d: d["maps"]["diverge"].pop("center"),                         # div center 없음
    lambda d: d["maps"]["diverge"].__setitem__("center", 0.4),
    lambda d: d.__setitem__("schema", "esl/colormaps/2"),
    lambda d: d["maps"]["rainbow"]["stops"].__setitem__(0, [0, 0, 256]),  # 채널 범위
    lambda d: d["maps"]["rainbow"]["stops"].__setitem__(0, [0, 0]),
    lambda d: d["maps"]["rainbow"].__setitem__("stops", [[0, 0, 0]]),     # 정점 1개
    lambda d: d["maps"]["rainbow"].__setitem__("kind", "rainbow"),
    lambda d: d["roles"].__setitem__("seq", "viridis"),                   # roles → 없는 지도
    lambda d: d["special"].pop("none"),
    lambda d: d["maps"]["rainbow"].__setitem__("check", "x"),
    lambda d: d.pop("text"),                                              # 색 칸 글자 대비(통합 INT)
    lambda d: d["text"].__setitem__("dark_lum", 1.5),
    lambda d: d["text"].__setitem__("dark_lum", True),
    lambda d: d["text"].__setitem__("on_dark", [0, 0]),
    lambda d: d["text"].pop("on_light"),
])
def test_v0251_39_invalid_resource(tmp_path, mut):
    d = copy.deepcopy(_raw())
    mut(d)
    p = tmp_path / "cm.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(EslError) as ei:
        cm.load(str(p))
    assert ei.value.code == "CONFIG_INVALID"


def test_v0251_39_unreadable_and_unknown_role(tmp_path):
    with pytest.raises(EslError) as ei:
        cm.load(str(tmp_path / "none.json"))
    assert ei.value.code == "CONFIG_INVALID"
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(EslError):
        cm.load(str(tmp_path / "bad.json"))
    with pytest.raises(EslError) as ei:
        cm.map_for("heat")
    assert ei.value.code == "CONFIG_INVALID"


# ---------------------------------------------------------------- V-0251-37
_LITERALS = [r"\b_SEQ\b", r"\bVIR\s*=", r"\bDIV\s*=", r"\bBLUE\s*=", r"\bRED\s*=", r"\bWHITE\s*=",
             r"viridis", r"VIRIDIS", r"RDBU", r"BLUES9",
             r"68,\s*1,\s*84", r"253,\s*231,\s*37", r"49,\s*54,\s*149", r"165,\s*0,\s*38",   # viridis·옛 발산 정점
             r"33(?:\.0)?,\s*102(?:\.0)?,\s*172", r"178(?:\.0)?,\s*24(?:\.0)?,\s*43",         # 옛 썸네일 파랑·빨강
             r"rgba\(22,\s*163,\s*74", r"rgba\(220,\s*38,\s*38"]                               # 옛 개선율 초록·빨강


def _py_files():
    for top in ("esl", "backend", "worker"):
        for dp, dns, fns in os.walk(os.path.join(ROOT, top)):
            dns[:] = [d for d in dns if d not in ("tests", "__pycache__", "node_modules", ".venv")]
            for f in fns:
                if f.endswith(".py"):
                    yield os.path.join(dp, f)


def test_v0251_37_single_resource_python():
    hits, opens = [], []
    for p in _py_files():
        src = open(p, encoding="utf-8").read()
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        for pat in _LITERALS:
            if re.search(pat, src):
                hits.append((rel, pat))
        if re.search(r"[\"'][^\"'\n]*colormaps\.json[\"']", src):     # 문자열 리터럴로 자원 경로를 가진 곳(설명 글 제외)
            opens.append(rel)
    assert hits == []
    assert opens == ["esl/io/colormaps.py"]
    # 자원 원본은 1개(resources/colormaps.json), 파이썬 모듈은 정점 리터럴 없이 역할로만 고름
    src = open(os.path.join(ROOT, "esl", "io", "colormaps.py"), encoding="utf-8").read()
    assert not re.search(r"\[\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\]", src)
    assert not re.search(r"^\s*(?:from|import)\s+esl\.(?:doe|view3d)\b", src, re.M)
