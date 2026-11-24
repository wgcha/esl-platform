"""v0.24.5 §12 출처 계산 제외(사용자 2026-11-24 — 계약 docs/contracts/esl_validate_tiers.md §12, V-0245-VT-16 코어·Case).

기본 설정(예시 yaml, bforce·jig 절 없음): 경계력·내력·지그 고정은 계산하지 않음(산출물·④ 풀이·추출 bf_on 0·보충 추출 없음),
full·jig_disp·jig_spring 은 그대로. 설정으로 다시 켜면 v0.24.4 와 같은 산출물 = 골든(``test_validate_tiers`` V-6 이 되돌림 설정으로
비교). 소요 시간(합성) = 기본 vs 다시 켬.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time

import pytest

import synth_case
import vt_golden as G
from esl import config as cfgm
from esl import pipeline
from esl import val_src as vs
from esl.doe import DEFAULTS
from esl.mech import jig as jigm
from esl.mech import jig_bc

OFF_SRCS = {"bforce": "BF_DISABLED", "fint": "FINT_DISABLED", "jig": "JIG_DISABLED"}
ON_SRCS = ("full", "jig_disp", "jig_spring")


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def test_v0245_vt_16_defaults_keys():
    """기본값 원본 한 곳 + 거울: Case BFORCE_DEFAULTS·JIG_DEFAULTS, 스터디 DEFAULTS(bforce·fint·rank.jig.methods)."""
    assert cfgm.BFORCE_DEFAULTS["enabled"] is False and cfgm.bforce_settings({})["enabled"] is False
    assert cfgm.BFORCE_DEFAULTS["fint"]["enabled"] is True                     # 하위 스위치는 그대로(bforce.enabled 가 막음)
    assert jigm.JIG_DEFAULTS["methods"] == ["prescribed", "spring"] == cfgm.jig_settings({})["methods"]
    assert DEFAULTS["rank"]["jig"]["methods"] == jigm.JIG_DEFAULTS["methods"]   # 거울
    assert DEFAULTS["bforce"]["enabled"] is False and DEFAULTS["fint"]["enabled"] is False
    assert jig_bc.LEGACY_ABSENT["methods"] == ("fixed",)                       # 옛 스냅샷 뜻 불변
    assert cfgm.bforce_settings({"bforce": {"enabled": True}})["enabled"] is True   # 설정으로 되돌림
    ex = cfgm.load_config(os.path.join(G.ROOT, "config", "esl.example.yaml"))
    assert "bforce" not in ex and "jig" not in ex                               # 예시 = 주석(절 없음 → 기본값)


def test_v0245_vt_16_worker_request_bf_off():
    """① 추출 request bf_on 0(HyperWorks TCL 이 경계력 결과를 읽지 않음), ③ 보충 추출 판정 = 없음(행 1 enabled false)."""
    sys.path.insert(0, os.path.join(G.ROOT, "worker"))
    from esl_worker import bf_ondemand, h3d

    assert h3d.bforce_request({})["bf_on"] == "0"
    assert h3d.bforce_request({"bforce": {"enabled": True}})["bf_on"] == "1"
    f = bf_ondemand.Facts(enabled=cfgm.bforce_settings({})["enabled"], on_demand=True, input_kind="H3D", has_frame=False,
                          h3d_ok=True, hw_ok=True)
    d = bf_ondemand.decide(f)
    assert (d.action, d.row) == ("none", "1")


def _case(root: str, reenable: bool) -> dict:
    """합성 지그 Case(경계력·내력 자료 + 이웃 판 + tie 9노드) — 기본 설정 또는 §12 되돌림 설정으로 ESL·검증까지."""
    from test_bforce_stage import _add_bforce
    from test_jig_case import add_neighbor, tie_index, write_fixed

    c = synth_case.build(root, source="max_strain")
    _add_bforce(c, c["csv"], fint_sign=-1.0)
    add_neighbor(c)
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(G.cfg_text(reenable=reenable))
    out = os.path.join(root, "out")
    kw = {"config_path": cfg, "rad": c["rad"], "results": c["csv"], "out": out, "frame": synth_case.T_STAR_FRAME,
          "echo": lambda *_: None, "tag": "vt16"}
    pipeline.run(stage="extract", **kw)
    write_fixed(out, c, tie_index())
    pipeline.run(stage="tstar", **kw)
    t = {}
    for st in ("esl", "validate"):
        t0 = time.perf_counter()
        rec = pipeline.run(stage=st, **kw)
        t[st] = time.perf_counter() - t0
        t[f"{st}_rec"] = rec
    return {"out": out, "t": t}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return {k: _case(str(tmp_path_factory.mktemp(f"vt16_{k}")), k == "on") for k in ("off", "on")}


def test_v0245_vt_16_case_default_excludes_sources(runs):
    out = runs["off"]["out"]
    esl_files = set(os.listdir(os.path.join(out, pipeline.D_ESL)))
    for k in OFF_SRCS:                                                          # 끈 출처 산출물 0
        assert not {f"{k}.json", f"{k}.npz"} & esl_files, k
    for k in ("jig_disp", "jig_spring"):
        assert {f"{k}.json", f"{k}.npz"} <= esl_files, k
    summ = runs["off"]["t"]["esl_rec"]["stages"]["esl"]["summary"]
    for k, code in OFF_SRCS.items():
        assert summ[k]["code"] == code, (k, summ[k])
    sj = _j(out, pipeline.D_VAL, vs.SOURCES_JSON)
    rows = {r["key"]: r for r in sj["rows"]}
    for k, code in OFF_SRCS.items():                                            # ④ 불가 행(풀이 없음)
        assert rows[k]["status"] == "unavailable" and rows[k]["code"] == code and rows[k]["dir"] is None
        assert not os.path.exists(os.path.join(out, pipeline.D_VAL, k))
    for k in ON_SRCS:
        assert rows[k]["status"] == "done", k
    keys = [x for g in sj["solve"]["groups"] for x in g["keys"]]
    assert sorted(keys) == sorted(ON_SRCS) and not set(OFF_SRCS) & set(sj["solve"]["eval_s"])   # 풀이 0
    # 다시 켠 Case: 여섯 출처 모두 계산(v0.24.4 와 같음 — 값은 골든 V-6 이 비교)
    rows_on = {r["key"]: r for r in _j(runs["on"]["out"], pipeline.D_VAL, vs.SOURCES_JSON)["rows"]}
    assert all(r["status"] == "done" for r in rows_on.values())
    on_esl = set(os.listdir(os.path.join(runs["on"]["out"], pipeline.D_ESL)))
    assert {f"{k}.json" for k in OFF_SRCS} <= on_esl
    # full·jig_disp·jig_spring 의 ④ 값은 켜고 끔과 무관(같은 계산)
    for k in ON_SRCS:
        a = _j(out, pipeline.D_VAL, rows[k]["dir"] or "", "validation.json")
        b = _j(runs["on"]["out"], pipeline.D_VAL, rows_on[k]["dir"] or "", "validation.json")
        assert [m["value"] for m in a["metrics"]] == [m["value"] for m in b["metrics"]], k


def test_v0245_vt_16_extract_pack_skipped(runs):
    """① 추출: 경계력 자료 꾸러미(01_extract bforce)는 켰을 때만."""
    off = set(os.listdir(os.path.join(runs["off"]["out"], pipeline.D_EXTRACT)))
    on = set(os.listdir(os.path.join(runs["on"]["out"], pipeline.D_EXTRACT)))
    extra = on - off
    assert extra and all("bforce" in f or f.startswith("bf") for f in extra), extra


def test_v0245_vt_16_time_saving(runs, capsys):
    """소요 시간(합성): 기본(끔) ESL·검증 < 다시 켬 — 기록값은 반환 보고에 씀."""
    off, on = runs["off"]["t"], runs["on"]["t"]
    rec = {k: (round(off[k], 3), round(on[k], 3)) for k in ("esl", "validate")}
    with capsys.disabled():
        print(f"\n[VT-16 time] off/on seconds: {rec}")
    assert off["esl"] + off["validate"] < on["esl"] + on["validate"]


def test_v0245_vt_16_old_snapshot_meaning_unchanged():
    """옛 스냅샷(rank.jig methods 키 없음) = fixed 만, v0.24.4 스냅샷(세 방식 명시) = 그대로 — 기본값 변경과 무관."""
    assert jig_bc.methods_of({}) == ("fixed",)
    j = copy.deepcopy(DEFAULTS["rank"]["jig"])
    j["methods"] = ["fixed", "prescribed", "spring"]
    assert jig_bc.methods_of(j) == ("fixed", "prescribed", "spring")
