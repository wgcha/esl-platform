"""v0.25.2 A — t* 임의 프레임(계약 esl_tstar_manual_jig_force.md §2, V-0252-1·3~9 코어).

합성 Case(synth_case — 판, 패턴 1 피크 frame 6·패턴 2 피크 frame 3, 11 프레임, 강체 대회전):
  base = 기본 추출(D = [3, 6]), full = 같은 결과를 D = 전 프레임으로 추출(처음부터 추출 — 시험 5 대조).
채움 출력(TCL fr_only 흉내) = full 의 CSV 에서 프레임 f·f−1 행만 뽑은 disp.csv·strain_frames.csv + done.json(mode fr_only).
"""
import functools
import json
import os
import shutil

import numpy as np
import pytest

import synth_case
from esl import cli, pipeline
from esl.errors import EslError
from esl.io import frame_fill as ff
from esl.mech import tstar

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
F_BEFORE, F_AFTER, F_LOW = 5, 8, 1           # D 밖: 자동(6) 앞 ratio≈0.70 · 뒤(max-hold 평탄) · ratio≈0.30


def _cfg_text(extra: str = "") -> str:
    t = open(os.path.join(ROOT, "config", "esl.example.yaml"), encoding="utf-8").read()
    return t.replace("disp_precision: float32", "disp_precision: float64") + extra


def _run(c, out, stage, frame=None):
    pipeline.run(config_path=c["cfg"], rad=c["rad"], results=c["csv"], out=out, stage=stage, frame=frame,
                 echo=lambda s: None, tag="t")


def _build(root, full: bool, mp=None):
    os.makedirs(root, exist_ok=True)
    if full:
        orig = synth_case.write_results_csv
        synth_case.write_results_csv = functools.partial(orig, frames_D=list(range(synth_case.A_T.size)))
        try:
            ex = synth_case.build(root)
        finally:
            synth_case.write_results_csv = orig
    else:
        ex = synth_case.build(root)
    cfg = os.path.join(root, "cfg.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(_cfg_text())
    c = {**ex, "cfg": cfg, "out": os.path.join(root, "case")}
    for st in ("extract", "tstar"):
        _run(c, c["out"], st)
    return c


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    r = tmp_path_factory.mktemp("tm")
    base = _build(str(r / "base"), False)
    full = _build(str(r / "full"), True)
    return {"base": base, "full": full, "root": str(r)}


def _copy(c, dst):
    out = os.path.join(dst, "case")
    shutil.copytree(c["out"], out)
    return {**c, "out": out}


def make_fill_out(full_csv: str, f: int, dst: str, n_frames: int | None = None, time_shift: float = 0.0) -> str:
    """TCL fr_only 출력 흉내: full CSV 의 f·f−1 행(같은 텍스트 = 같은 값) + done.json(mode fr_only)."""
    os.makedirs(dst, exist_ok=True)
    rows = {}
    for name, frames in (("disp.csv", {f}), ("strain_frames.csv", {f, f - 1} if f > 0 else {f})):
        with open(os.path.join(full_csv, name), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        with open(os.path.join(dst, name), "w", encoding="utf-8") as fh:
            fh.write(lines[0] + "\n")
            for ln in lines[1:]:
                if ln and int(ln.split(",", 1)[0]) in frames:
                    fh.write(ln + "\n")
        rows[name] = frames
    times = {}
    with open(os.path.join(full_csv, "frames.csv"), encoding="utf-8") as fh:
        for ln in fh.read().splitlines()[1:]:
            a, b = ln.split(",")
            times[int(a)] = float(b)
    done = {"ok": True, "mode": "fr_only", "n_frames": n_frames or len(times), "frames": [f],
            "prev_frames": [f - 1] if f > 0 else [],
            "frame_times": {str(g): times[g] + time_shift for g in sorted(rows["strain_frames.csv"])},
            "strain_source": "max_strain"}
    with open(os.path.join(dst, "done.json"), "w", encoding="utf-8") as fh:
        json.dump(done, fh)
    return dst


def _npz(p):
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ V-0252-1
def test_v0252_1_point_at():
    v = np.array([[1.0, 5.0, 5.0, 2.0], [0.0, np.nan, 7.0, 7.0], [3.0, 1.0, 1.0, 9.0]])
    assert tstar.point_at(v, 0) == {"elem_pos": 1, "value": 5.0}                       # 동률 = 작은 인덱스
    assert tstar.point_at(v, 1) == {"elem_pos": 2, "value": 7.0}                       # NaN = −inf
    assert tstar.point_at(v, 2, np.array([False, False, False, True])) == {"elem_pos": 0, "value": 3.0}   # 제외
    with pytest.raises(EslError):
        tstar.point_at(v, 3)
    with pytest.raises(EslError):
        tstar.point_at(v, 0, np.ones(4, bool))


def test_v0252_1_frame_point_values(world):
    out = world["base"]["out"]
    tj = _j(out, "02_tstar", "tstar.json")
    auto = tj["metrics"]["max_strain"]["tstar"]
    p = pipeline.frame_point(out, None, "max_strain", F_BEFORE)
    assert p["frame_index"] == F_BEFORE and p["in_D"] is False and p["have"] is False and p["rel"] == "before"
    assert p["auto"] == {"frame_index": auto["frame_index"], "time": auto["time"], "value": auto["value"]}
    assert p["ratio"] == pytest.approx(p["value"] / auto["value"]) and 0.5 < p["ratio"] < 0.9
    assert pipeline.frame_point(out, None, "max_strain", 6)["rel"] == "at"
    assert pipeline.frame_point(out, None, "max_strain", F_AFTER)["rel"] == "after"
    assert pipeline.frame_point(out, None, "max_strain", 3)["in_D"] is True
    with pytest.raises(EslError) as ei:
        pipeline.frame_point(out, None, "max_strain", 99)
    assert ei.value.code == "FRAME_NOT_FOUND"
    # 제외 요소(tstar.exclude_elem_ids) = 그 프레임 최대 요소가 바뀜
    e0 = p["elem_id"]
    p2 = pipeline.frame_point(out, {"tstar": {"exclude_elem_ids": [e0]}}, "max_strain", F_BEFORE)
    assert p2["elem_id"] != e0 and p2["value"] <= p["value"]


# ------------------------------------------------------------------ V-0252-3
def test_v0252_3_merge_append_invariants(world, tmp_path):
    c = _copy(world["base"], str(tmp_path))
    xd = os.path.join(c["out"], "01_extract")
    d0, s0, m0 = _npz(os.path.join(xd, "disp.npz")), _npz(os.path.join(xd, "strain_frames.npz")), _j(xd, "frames.json")
    fo = make_fill_out(world["full"]["csv"], F_BEFORE, str(tmp_path / "fill"))
    r = ff.merge(xd, fo, F_BEFORE, job_id="J1")
    assert r["added"] is True and r["frame"] == F_BEFORE
    d1, s1, m1 = _npz(os.path.join(xd, "disp.npz")), _npz(os.path.join(xd, "strain_frames.npz")), _j(xd, "frames.json")
    assert set(d1) == set(d0) and set(s1) == set(s0)
    for z0, z1 in ((d0, d1), (s0, s1)):
        for k in z0:
            assert z1[k].dtype == z0[k].dtype, k
            if k in ("node_id", "elem_id"):
                assert np.array_equal(z1[k], z0[k])
            else:
                assert z1[k].shape[0] == z0[k].shape[0] + 1 and np.array_equal(z1[k][:-1], z0[k]), k   # 기존 행 불변
    assert d1["frame_index"][-1] == F_BEFORE and s1["frame_index"][-1] == F_BEFORE
    assert s1["prev_frame_index"][-1] == F_BEFORE - 1 and bool(s1["prev_available"][-1])
    # 값 = 처음부터 D 로 추출한 full 의 그 프레임 행(정확 일치)
    fd, fs = _npz(os.path.join(world["full"]["out"], "01_extract", "disp.npz")), \
        _npz(os.path.join(world["full"]["out"], "01_extract", "strain_frames.npz"))
    i = int(np.flatnonzero(fd["frame_index"] == F_BEFORE)[0])
    j = int(np.flatnonzero(fs["frame_index"] == F_BEFORE)[0])
    assert np.array_equal(d1["u"][-1], fd["u"][i]) and d1["time"][-1] == fd["time"][i]
    for k in s1:
        if k not in ("frame_index", "time", "elem_id"):
            assert np.array_equal(s1[k][-1], fs[k][j]), k
    # frames.json: frames_D·time_D·candidate_frames 불변, frames_fill 새 키
    for k in m0:
        assert m1[k] == m0[k], k
    assert [e["frame_index"] for e in m1["frames_fill"]] == [F_BEFORE] and m1["frames_fill"][0]["job_id"] == "J1"
    bk = os.path.join(c["out"], "_backup")
    assert os.path.isdir(bk) and any("disp.npz" in fns for _dp, _dn, fns in os.walk(bk))
    # 두 번 병합 = 한 번(멱등 — 파일 바이트 그대로)
    before = {n: open(os.path.join(xd, n), "rb").read() for n in ("disp.npz", "strain_frames.npz", "frames.json")}
    assert ff.merge(xd, fo, F_BEFORE, job_id="J2")["added"] is False
    assert all(open(os.path.join(xd, n), "rb").read() == b for n, b in before.items())
    assert ff.have_frame(xd, F_BEFORE) and ff.frames_have(xd) == sorted({3, 6, F_BEFORE})
    assert ff.fill_entry(xd, F_BEFORE)["frame_index"] == F_BEFORE and ff.fill_entry(xd, 3) is None


@pytest.mark.parametrize("bad", ["n_frames", "time", "mode", "frame"])
def test_v0252_3_merge_mismatch_writes_nothing(world, tmp_path, bad):
    c = _copy(world["base"], str(tmp_path))
    xd = os.path.join(c["out"], "01_extract")
    kw = {"n_frames": 12} if bad == "n_frames" else ({"time_shift": 1e-9} if bad == "time" else {})
    fo = make_fill_out(world["full"]["csv"], F_BEFORE, str(tmp_path / "fill"), **kw)
    if bad == "mode":
        d = _j(fo, "done.json")
        d["mode"] = "bf_only"
        json.dump(d, open(os.path.join(fo, "done.json"), "w"))
    snap = {n: open(os.path.join(xd, n), "rb").read() for n in sorted(os.listdir(xd))}
    bk = os.path.join(c["out"], "_backup")
    bk0 = sorted(dp for dp, _dn, _f in os.walk(bk))
    with pytest.raises(EslError) as ei:
        ff.merge(xd, fo, F_BEFORE if bad != "frame" else F_AFTER)
    assert ei.value.code == {"n_frames": "FRAME_FILL_MISMATCH", "time": "FRAME_FILL_MISMATCH",
                             "mode": "FRAME_FILL_OUTPUT", "frame": "FRAME_FILL_OUTPUT"}[bad]
    assert {n: open(os.path.join(xd, n), "rb").read() for n in sorted(os.listdir(xd))} == snap
    assert sorted(dp for dp, _dn, _f in os.walk(bk)) == bk0                 # 백업 폴더도 새로 안 생김


def test_v0252_3_record_and_decide_facts(tmp_path):
    xd = str(tmp_path / "01_extract")
    ff.record(xd, {"frame": 5, "job_id": "A", "status": "failed", "cause": "TIMEOUT", "detail": "hw 1800 s", "seconds": 1800})
    ff.record(xd, {"frame": 5, "job_id": "B", "status": "ok", "seconds": 200.5})
    doc = ff.read_record(xd)
    assert doc["schema"] == "esl/frame_fill/1" and [a["status"] for a in doc["attempts"]] == ["failed", "ok"]
    assert ff.last_attempt(xd, 5)["job_id"] == "B" and ff.last_attempt(xd, 5, "A")["cause"] == "TIMEOUT"
    assert ff.last_attempt(xd, 6) is None
    with pytest.raises(EslError):
        ff.record(xd, {"frame": 5, "status": "skipped"})
    assert ff.request_keys({"strain_fallback": {"source": "plastic_strain", "mode": "maxhold"}}, 7) == \
        {"fr_only": "1", "fr_frames": "7", "strain_sources": "plastic_strain"}
    assert ff.request_keys({}, 0)["strain_sources"] == "max_strain" and ff.fill_frames(0) == ([0], [])
    with pytest.raises(EslError):
        ff.request_keys({"strain_fallback": {"source": "strain_tensor", "mode": "dump"}}, 3)


# ------------------------------------------------------------------ V-0252-9 판정 표
@pytest.mark.parametrize("facts,row,code", [
    (dict(have=True, csv_input=True, dump_mode=True, h3d_readable=False, hw_available=False), 1, None),
    (dict(have=False, csv_input=True, dump_mode=True), 2, "NO_H3D"),
    (dict(have=False, dump_mode=True, h3d_readable=False), 3, "DUMP_MODE"),
    (dict(have=False, h3d_readable=False, hw_available=False, h3d_name="x.h3d"), 4, "H3D_UNREADABLE"),
    (dict(have=False, hw_available=False), 5, "HW_UNAVAILABLE"),
    (dict(have=False), 6, None),
])
def test_v0252_9_decide_table(facts, row, code):
    d = ff.decide(ff.Facts(**facts))
    assert d["row"] == row and d["code"] == code
    assert d["action"] == {1: "have", 6: "fill"}.get(row, "block")
    assert (d["text"] is None) == (row in (1, 6))
    if row == 4:
        assert d["text"] == "입력 h3d 를 읽을 수 없습니다(x.h3d)"
    assert [r["row"] for r in ff.DECIDE] == [1, 2, 3, 4, 5, 6]


def test_v0252_9_extract_facts(world, tmp_path):
    xd = os.path.join(world["base"]["out"], "01_extract")
    assert ff.extract_facts(xd, 3) == {"have": True, "dump_mode": False}
    assert ff.extract_facts(xd, F_BEFORE) == {"have": False, "dump_mode": False}


# ------------------------------------------------------------------ V-0252-4·5·6 물리
@pytest.fixture(scope="module")
def esl_runs(world, tmp_path_factory):
    r = tmp_path_factory.mktemp("esl")
    filled = _copy(world["base"], str(r / "filled"))
    fo = make_fill_out(world["full"]["csv"], F_BEFORE, str(r / "fill"))
    ff.merge(os.path.join(filled["out"], "01_extract"), fo, F_BEFORE, job_id="J")
    for st in ("esl", "validate", "report"):
        _run(filled, filled["out"], st, frame=F_BEFORE)
    fullc = _copy(world["full"], str(r / "full"))
    _run(fullc, fullc["out"], "esl", frame=F_BEFORE)
    return {"filled": filled, "full": fullc}


def test_v0252_4_arbitrary_frame_esl_physics(world, esl_runs):
    c = esl_runs["filled"]
    out = c["out"]
    f = np.load(os.path.join(out, "04_esl", "f_eq.npz"), allow_pickle=False)["f"]
    a, b = synth_case.A_T[F_BEFORE], synth_case.B_T[F_BEFORE]
    expect = a * (c["F_app"] + c["R"]) + b * (c["F2"] + c["R2"])          # 알려진 하중(+ 3-2-1 반력)
    rel = np.abs(f - expect).max() / np.abs(expect).max()
    assert rel < 1e-6, rel
    summ = _j(out, "04_esl", "esl_summary.json")
    warn = 1e-6
    assert summ["forces"]["equilibrium_rel"] <= warn and summ["forces"]["moment_rel"] <= warn
    assert summ["frame"]["frame_index"] == F_BEFORE and summ["frame"]["source"] == "user"
    tm = summ["tstar_manual"]
    assert tm["filled"] is True and tm["in_D"] is False and tm["rel"] == "before" and tm["auto_frame"] == 6
    assert tm["ratio"] == pytest.approx(pipeline.frame_point(out, None, "max_strain", F_BEFORE)["ratio"])
    assert [n["code"] for n in tm["notes"]][0] == "TSTAR_MANUAL"
    # F_eq 로 3-2-1 전체 풀이 → u_rel(f) 재현(④ 변위 지표 통과, MAC ≥ 0.999)
    v = _j(out, "05_val", "validation.json")
    assert v["verdict"] == "PASS", v.get("fail_reasons")
    mt = {m["metric"]: m["value"] for m in v["metrics"]}
    assert mt["mac"] >= 0.999 and mt["disp_rms_rel"] < 1e-9 and mt["reaction_rel"] < 1e-9, mt
    # 보고서: t* 줄 뒤 직접 고른 t* 1줄
    html = open(os.path.join(out, "07_report", "report.html"), encoding="utf-8").read()
    assert "직접 고른 t*" in html and "자동 t*(프레임 6" in html


def test_v0252_5_fill_equals_full_extraction(esl_runs):
    a, b = esl_runs["filled"]["out"], esl_runs["full"]["out"]
    for fn in ("u_rel.npz", "f_eq.npz"):
        za, zb = _npz(os.path.join(a, "04_esl", fn)), _npz(os.path.join(b, "04_esl", fn))
        assert set(za) == set(zb)
        for k in za:
            assert za[k].dtype == zb[k].dtype and np.array_equal(za[k], zb[k]), (fn, k)


def test_v0252_6_d_noncandidate_no_fill(esl_runs):
    out = esl_runs["full"]["out"]
    xd = os.path.join(out, "01_extract")
    assert ff.read_record(xd) is None and "frames_fill" not in _j(xd, "frames.json")
    tm = _j(out, "04_esl", "esl_summary.json")["tstar_manual"]
    assert tm["in_D"] is True and tm["filled"] is False


def test_v0252_2_candidate_record_unchanged(world, tmp_path):
    """후보 ∧ D 프레임(--frame 3) = 옛 레코드(manual 없음). D 밖·안 채움 = FRAME_NOT_CANDIDATE(채움 필요)."""
    c = _copy(world["base"], str(tmp_path))
    _run(c, c["out"], "tstar", frame=3)
    sel = _j(c["out"], "02_tstar", "tstar.json")["selected"]
    assert set(sel) == {"frame_index", "time", "elem_id", "value", "metric", "source"} and sel["source"] == "user"
    with pytest.raises(EslError) as ei:
        _run(c, c["out"], "esl", frame=4)
    assert ei.value.code == "FRAME_NOT_CANDIDATE" and "채움 필요" in ei.value.message


def test_v0252_2_tstar_stage_manual_selected(world, tmp_path):
    c = _copy(world["base"], str(tmp_path))
    fo = make_fill_out(world["full"]["csv"], F_BEFORE, str(tmp_path / "fill"))
    ff.merge(os.path.join(c["out"], "01_extract"), fo, F_BEFORE)
    _run(c, c["out"], "tstar", frame=F_BEFORE)
    tj = _j(c["out"], "02_tstar", "tstar.json")
    assert tj["selected"]["manual"]["have"] is True and tj["selected"]["manual"]["in_D"] is False
    assert tj["frames_D"] == [{"frame_index": 3, "time": tj["frames_D"][0]["time"]},
                              {"frame_index": 6, "time": tj["frames_D"][1]["time"]}]
    assert tj["auto"]["frame_index"] == 6                   # 자동 t* 재계산 결과 불변


# ------------------------------------------------------------------ V-0252-7 경고
def test_v0252_7_manual_notes(world, tmp_path):
    c = _copy(world["base"], str(tmp_path))
    xd = os.path.join(c["out"], "01_extract")
    for f in (F_AFTER, F_LOW):
        ff.merge(xd, make_fill_out(world["full"]["csv"], f, str(tmp_path / f"fill{f}")), f)
    _run(c, c["out"], "esl", frame=F_AFTER)
    tm = _j(c["out"], "04_esl", "esl_summary.json")["tstar_manual"]
    codes = [n["code"] for n in tm["notes"]]
    assert tm["rel"] == "after" and tm["ratio"] == pytest.approx(1.0)
    assert codes == ["TSTAR_MANUAL", "TSTAR_MANUAL_AFTER", "TSTAR_MANUAL_NO_RISING"]      # max-hold 평탄 = 상승 0
    noise = _j(c["out"], "04_esl", "esl_summary.json")["noise"]
    assert noise["hotspot_elem_id"] == []                    # hotspot 비교 생략
    _run(c, c["out"], "validate", frame=F_AFTER)             # ④ 판정(변위 4지표) 가능
    assert _j(c["out"], "05_val", "validation.json")["verdict"] in ("PASS", "CONDITIONAL", "FAIL")
    _run(c, c["out"], "esl", frame=F_LOW)
    run = _j(c["out"], "run.json")
    tm = _j(c["out"], "04_esl", "esl_summary.json")["tstar_manual"]
    assert tm["ratio"] < 0.5 and "TSTAR_MANUAL_LOW" in [n["code"] for n in tm["notes"]]
    assert any(w.startswith("TSTAR_MANUAL_LOW:") for w in run["stages"]["esl"]["warnings"])
    assert run["stages"]["esl"]["summary"]["tstar_manual"]["rel"] == "before"
    # 임계 설정(tstar.manual_ratio_warn) — 0.2 면 LOW 아님(계산 불변)
    c2 = {**c, "cfg": str(tmp_path / "cfg2.yaml")}
    with open(c2["cfg"], "w", encoding="utf-8") as fh:
        fh.write(_cfg_text().replace("manual_ratio_warn: 0.5", "manual_ratio_warn: 0.2"))
    f_a = _npz(os.path.join(c["out"], "04_esl", "f_eq.npz"))["f"]
    _run(c2, c["out"], "esl", frame=F_LOW)
    tm2 = _j(c["out"], "04_esl", "esl_summary.json")["tstar_manual"]
    assert "TSTAR_MANUAL_LOW" not in [n["code"] for n in tm2["notes"]]
    assert np.array_equal(_npz(os.path.join(c["out"], "04_esl", "f_eq.npz"))["f"], f_a)


def test_v0252_7_config_manual_ratio_warn_range(tmp_path):
    from esl import config as C
    assert C.TSTAR_MANUAL_DEFAULTS == {"manual_ratio_warn": 0.5}
    cfg = C.load_config(os.path.join(ROOT, "config", "esl.example.yaml"))
    assert C.tstar_manual_settings(cfg)["manual_ratio_warn"] == 0.5
    cfg["tstar"].pop("manual_ratio_warn")
    assert C.tstar_manual_settings(C.validate_settings(cfg))["manual_ratio_warn"] == 0.5    # 선택 키
    cfg["tstar"]["manual_ratio_warn"] = 1.5
    with pytest.raises(EslError) as ei:
        C.validate_settings(cfg)
    assert ei.value.code == "CONFIG_INVALID"


def test_v0252_cli_help_text():
    p = cli.build_parser()
    sub = next(a for a in p._actions if a.dest == "cmd").choices["run"]
    h = next(a for a in sub._actions if a.dest == "frame").help
    assert h == "t* 수동 지정(frame_index — 변위가 있는 프레임)"


# ------------------------------------------------------------------ V-0252-8 누적 씬
def test_v0252_8_cumulative_manual_frame(tmp_path):
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tests", "cumulative"))
    import synth_cum
    from esl import cumulative as cumod
    orig = synth_cum.write_results_csv
    synth_cum.write_results_csv = functools.partial(orig, frames_D=list(range(synth_case.A_T.size)))
    try:
        cc = synth_cum.build(str(tmp_path))
    finally:
        synth_cum.write_results_csv = orig
    cfg = str(tmp_path / "c.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(_cfg_text().replace("hot_k: 200 ", "hot_k: 5000"))
    c = {"cfg": cfg, "rad": cc["rad"], "csv": cc["csv"]}
    out = str(tmp_path / "out")
    for st in ("extract", "tstar"):
        _run(c, out, st)
    tj = _j(out, "02_tstar", "tstar.json")
    cands = {x["frame_index"] for x in tj["candidates"]}
    f = next(g for g in range(1, synth_case.A_T.size) if g not in cands and g != tj["auto"]["frame_index"])
    p = pipeline.frame_point(out, None, tj["metric"], f)
    # 값 = 누적 계열(이전 + 이번) — 같은 요소의 raw(이번만) 값 이상, 자동 값도 누적
    ctx = pipeline.Context(cfg={"tstar": {"exclude_elem_ids": []}}, config_path="", rad="", results="", out=out, ts="",
                           frame=None, support_nodes=None, echo=lambda s: None, record={})
    model = pipeline.load_model(out)
    meta = pipeline._frames_meta(ctx)
    hz, hp = pipeline._history(ctx, model)
    cst = pipeline._cum_state(ctx, model)
    assert cst is not None
    raw = pipeline._metric_series(hz, pipeline._shear_factor(ctx, meta), pipeline._source(meta))[tj["metric"]]
    cum_v, _inc = cumod.series(raw, cst["prev"][hp], cst["modes"][tj["metric"]])
    k = int(np.flatnonzero(hz["elem_id"] == p["elem_id"])[0])
    fpos = int(np.flatnonzero(hz["frame_index"] == f)[0])
    assert p["value"] == pytest.approx(float(cum_v[fpos, k]))
    assert p["auto"]["value"] == pytest.approx(tj["auto"]["value"])
    # ESL = 이번 낙하분(자동과 같은 규칙 — u_rel = 그 프레임 변위의 강체 제거), 직접 고른 t* 요약
    _run(c, out, "esl", frame=f)
    summ = _j(out, "04_esl", "esl_summary.json")
    assert summ["tstar_manual"]["in_D"] is True and summ["frame"]["frame_index"] == f
    u = _npz(os.path.join(out, "04_esl", "u_rel.npz"))
    dz = _npz(os.path.join(out, "01_extract", "disp.npz"))
    assert np.array_equal(u["u_total"], dz["u"][int(np.flatnonzero(dz["frame_index"] == f)[0])])
