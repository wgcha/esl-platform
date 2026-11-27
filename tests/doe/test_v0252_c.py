"""v0.25.2 C — #96 표시 개선 + B 스터디 통합(계약 esl_tstar_manual_jig_force.md §3·§4, V-0252-18~23).

#96 재현 합성(synth_tm.issue96_shape): ④ 형상 직접 비교, 기준 = Case 메시, 형상 d001 = 판 앞뒷면 두 장 + Case 체결부 6곳 중 4곳 자리에
구멍(체결 위치 어긋남). 강제 끔(옛 스냅샷 — tie_force 키 없음) = 지그 순위 0·n_failed.jd 1·전 노드 보기 순위 1행(지금 화면에서 안 보이던
것), 강제 켬(새 스냅샷) = 형상이 지그 순위에 들어가고 참고용·3D 표식 자료.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

import synth_jig_grid as G
import synth_tm as T
from esl.doe import DEFAULTS, rank as rk
from esl.doe import report_doe
from esl.errors import EslError
from esl.library import _util as U
from esl.mesh import double_sheet as ds

DS = DEFAULTS["compare"]["double_sheet"]


def _det(m, t=2.0, **kw):
    a = {k: DS[k] for k in ("gap_min_t", "gap_max_t", "normal_deg", "sample_max")}
    return ds.detect(m, t, **{**a, **kw})


# ------------------------------------------------------------------ V-0252-19 개수 줄
def test_v0252_19_count_items_and_report_tail():
    R = {"n_ok": 0, "n_skipped": {"collision": 0, "fixed": 0, "geom": 0},
         "n_failed": {"mesh": 0, "size": 0, "solve": 0, "jd": 1}}
    items = rk.count_items(R)
    assert items == [{"key": "ok", "label": "성공", "n": 0}, {"key": "jd", "label": "지그 매핑 제외", "n": 1}]
    assert report_doe.count_tail(R, report_doe.COUNT_SHOWN_COMPARE) == " · 지그 매핑 제외 1"
    R0 = {"n_ok": 3, "n_skipped": {"collision": 1}, "n_failed": {"mesh": 2, "size": 0, "solve": 0}}
    assert report_doe.count_tail(R0, report_doe.COUNT_SHOWN_MAIN) == ""                # 덧붙일 키 없음 = 지금 줄 그대로
    assert report_doe.count_tail({**R0, "n_skipped": {}}, report_doe.COUNT_SHOWN_COMPARE) == ""
    assert report_doe.count_tail(R0, report_doe.COUNT_SHOWN_COMPARE) == " · 스킵(충돌) 1"   # ④ 줄이 안 찍던 키
    assert report_doe.count_tail({**R0, "n_ref": 2}, report_doe.COUNT_SHOWN_MAIN) == " · 참고용 2"
    assert [x["key"] for x in rk.count_items({"n_ok": 1, "n_failed": {"zz": 1, "bf": 2, "sm": 1}})] == ["ok", "bf", "sm", "zz"]
    assert set(rk.COUNT_LABELS) >= {"mesh", "size", "solve", "morph", "collision", "fixed", "geom", "jig", "jd", "js", "bf",
                                    "fi", "sm", "ref"}
    R2 = {"ranking": [{"id": "d001"}, {"id": "d002"}]}
    assert rk.mark_ref(R2, "C_jd", {"d002"})["n_ref"] == 1 and R2["ranking"][1]["jig_ref"] is True
    assert "jig_ref" not in R2["ranking"][0]
    R3 = {"ranking": [{"id": "d001"}]}
    assert "n_ref" not in rk.mark_ref(R3, "C", {"d001"}) and "jig_ref" not in R3["ranking"][0]    # 전 노드 순위엔 안 붙음


# ------------------------------------------------------------------ V-0252-21 두 장 감지
def test_v0252_21_double_sheet_detect():
    one = G.plate(5.0)
    r1 = _det(one)
    assert r1["frac"] == 0.0 and r1["gap_mm"] is None and r1["n_sample"] == one["conn"].shape[0]
    two = T.double_sheet(one, 2.0)
    r2 = _det(two)
    assert r2["frac"] >= 0.9 and r2["gap_mm"] == pytest.approx(2.0, abs=1e-9)
    assert _det(two) == r2                                                       # 결정적
    rib = G.plate(5.0, bead=(60.0, 90.0, 4.0))                                   # 리브(비드) 있는 한 장
    assert _det(rib)["frac"] < 0.5
    assert _det(T.double_sheet(one, 10.0))["frac"] == 0.0                         # 간격 5t = 안 걸림
    r_s = _det(two, sample_max=50)
    assert r_s["n_sample"] == 50 and r_s["frac"] >= 0.9
    with pytest.raises(EslError):
        _det(one, t=0.0)


def test_v0252_21_double_sheet_settings_range():
    from esl.doe import settings
    for bad in ({"gap_min_t": 0.0}, {"gap_max_t": 0.2}, {"normal_deg": 90.0}, {"frac_warn": 1.5}, {"sample_max": 0},
                {"enabled": "yes"}):
        with pytest.raises(EslError) as ei:
            settings({"bead_doe": {"compare": {"double_sheet": bad}}})
        assert ei.value.code == "CONFIG_INVALID"
    assert DS == {"enabled": True, "gap_min_t": 0.3, "gap_max_t": 3.0, "normal_deg": 15.0, "frac_warn": 0.5, "sample_max": 2000}


# ------------------------------------------------------------------ V-0252-22·23 #96 재현(④)
def _world(root, force: bool, cfg_over: dict | None = None):
    doe, out, A = G.cmp_world(str(root), shapes=(("d001", {"mesh": T.issue96_shape()}),),
                              rank=G.rank_snap(grid=True, force=force))
    if cfg_over:
        doe["cfg"]["bead_doe"].update(cfg_over)
    G.run_cmp(doe, out)
    return out


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def w96(tmp_path_factory):
    r = tmp_path_factory.mktemp("w96")
    return {"off": _world(r / "off", False), "on": _world(r / "on", True)}


def test_v0252_22_issue96_force_off(w96, capsys):
    out = w96["off"]
    res = _j(out, "post", "result.json")
    assert res["ranking"] == [] and res["n_failed"].get("jd") == 1, (res["n_failed"], res.get("metric_effective"))
    assert "counts" not in res and "n_ref" not in res                            # 옛 스냅샷 = 새 키 없음
    assert any(str(w).startswith("NO_FEASIBLE_DESIGNS") or (isinstance(w, dict) and w.get("code") == "NO_FEASIBLE_DESIGNS")
               for w in res["warnings"])
    jg = _j(out, "run", "designs", "d001", "jig_grid.json")
    tie = jg["map"]["tie"]
    assert tie["n_miss"] == 4 and tie["n_clusters"] == 6 and "n_force" not in tie
    assert all(m["code"] == "JIG_GRID_TIE_MISS" for m in jg["methods"].values())
    views = _j(out, "post", "jig_view.json")["rank_views"]
    assert len(views["full"]["ranking"]) == 1 and views["full"]["ranking"][0]["id"] == "d001"   # 전 노드 순위는 이미 있음
    assert views["jig_disp"]["ranking"] == []
    html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
    assert "· 지그 매핑 제외 1</p>" in html and "다른 하중 출처 순위: 전 노드" in html
    # 판 앞뒷면 두 장 경고(형상 계속 실행) + 형상 행 double_sheet
    cmp_ = _j(out, "prep", "compare.json")
    row = next(s for s in cmp_["shapes"] if s["id"] == "d001")
    assert row["status"] == "READY" and row["double_sheet"]["frac"] >= 0.9 and row["double_sheet"]["gap_mm"] == pytest.approx(2.0)
    assert not any("double_sheet" in s for s in cmp_["shapes"] if s["id"] != "d001")
    assert any(str(w).startswith("SHAPE_DOUBLE_SHEET: d001") for w in cmp_.get("warnings") or [])
    with capsys.disabled():
        print(f"\nV0252-22 #96 off: n_failed {res['n_failed']} · full view rows {len(views['full']['ranking'])} · "
              f"double_sheet {row['double_sheet']}")


def test_v0252_23_issue96_force_on(w96, capsys):
    out = w96["on"]
    res = _j(out, "post", "result.json")
    ids = [x["id"] for x in res["ranking"]]
    assert ids == ["d001"] and res["ranking"][0]["jig_ref"] is True and res["n_ref"] == 1
    keys = {c_["key"]: c_["n"] for c_ in res["counts"]}
    assert keys == {"ok": 1, "ref": 1} and res["counts"] == rk.count_items(res)
    jg = _j(out, "run", "designs", "d001", "jig_grid.json")
    tie = jg["map"]["tie"]
    assert tie["n_force"] == 4 and tie["n_miss"] == 0 and tie["ref"] is True and len(tie["marks"]) == 4
    assert all(m["status"] == "ok" for m in jg["methods"].values())
    for mk in tie["marks"]:                                                     # Case 체결부 자리 = 볼트 중심(형상 좌표)
        d = min(np.hypot(mk["x"][0] - bx, mk["x"][2] - bz) for bx, bz in G.BOLTS)
        assert mk["via"] == "force" and d < 1.0 and mk["n"] >= 1 and mk["dist"] > 1.0
    codes = [str(w).split(":", 1)[0] for w in jg["warnings"]]
    assert "JIG_GRID_TIE_FORCED" in codes and "JIG_GRID_TIE_MISS" not in codes
    grid = res["jig"]["grid"]
    assert grid["n_forced_shapes"] == 1 and grid["n_ref_shapes"] == 1
    wc = [w.get("code") if isinstance(w, dict) else str(w).split(":", 1)[0] for w in res["warnings"]]
    assert "JIG_GRID_TIE_FORCED" in wc and "JIG_GRID_TIE_HINT" in wc
    views = _j(out, "post", "jig_view.json")["rank_views"]
    assert views["jig_disp"]["ranking"][0]["jig_ref"] is True and views["jig_disp"]["n_ref"] == 1
    assert "jig_ref" not in views["full"]["ranking"][0] and "n_ref" not in views["full"]
    html = open(os.path.join(out, "report.html"), encoding="utf-8").read()
    assert "· 참고용 1</p>" in html and "다른 하중 출처 순위" not in html
    # 3D: 지그 변위 응답 manifest — 강제 지지 via force, Case 체결부 자리 tie_marks
    mf = [os.path.join(dp, "manifest.json") for dp, _d, fs in os.walk(os.path.join(out, "post", "view3d"))
          if "manifest.json" in fs and os.path.basename(dp).startswith("d001_jd")]
    assert mf, "d001 지그 변위 3D 없음"
    man = _j(mf[0])
    assert man["tie_marks"] == tie["marks"] and any(s.get("via") == "force" for s in man["supports"])
    assert man["tie_far_mm"] == tie["force"]["far_mm"]                          # 통합 INT: 범례 임계 = marks[].far 를 정한 값
    with capsys.disabled():
        f = tie["force"]
        print(f"\nV0252-23 #96 on: force {tie['n_force']}/{tie['n_clusters']} dist {f['dist_min_mm']:.2f}/"
              f"{f['dist_med_mm']:.2f}/{f['dist_max_mm']:.2f} far {tie['n_far']} area {tie['area_ratio_min']:.2f}~"
              f"{tie['area_ratio_max']:.2f} · score {res['ranking'][0]['score']:.4f}")


def test_v0252_double_sheet_disabled(tmp_path):
    out = _world(tmp_path, False, cfg_over={"compare": {**G.CFG_FULL["bead_doe"]["compare"],
                                                        "double_sheet": {**DS, "enabled": False}}})
    cmp_ = _j(out, "prep", "compare.json")
    assert not any("double_sheet" in s for s in cmp_["shapes"])
    assert not any(str(w).startswith("SHAPE_DOUBLE_SHEET") for w in cmp_.get("warnings") or [])


# ------------------------------------------------------------------ V-0252-18 옛 ③(step_per_design) 같은 함수·같은 키
@pytest.mark.parametrize("force", [False, True])
def test_v0252_18_step_per_design(tmp_path, monkeypatch, force):
    doe, out, A = G.step_world(str(tmp_path), rank=G.rank_snap(grid=True, force=force))
    with G.fake_gmsh(monkeypatch):
        G.run_step(doe, out, A)
    runs = [U.read_json(os.path.join(out, "run", "designs", d, "jig_grid.json"))
            for d in sorted(os.listdir(os.path.join(out, "run", "designs")))
            if os.path.isfile(os.path.join(out, "run", "designs", d, "jig_grid.json"))]
    assert runs
    for rd in runs:
        tie = (rd.get("map") or {}).get("tie") or {}
        assert ("n_force" in tie) is force and ("marks" in tie) is force
        if force:
            assert set(tie["force"]) == {"dist_min_mm", "dist_med_mm", "dist_max_mm", "shift_max_mm", "far_mm", "limit_mm"}
    res = _j(out, "post", "result.json")
    assert ("counts" in res) is force and ("n_forced_shapes" in res["jig"]["grid"]) is force
