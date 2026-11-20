"""v0.24.2 경계력 원자료 ESL 때 보충 — Case 파이프라인(계약 esl_bforce_ondemand.md §4·§5, V-0242-BFD-5·6).

덤프 방식 합성 추출(strain_tensor — 01_extract 에 bforce 없음) 에 선택 프레임 t* 만 bf 전용 추출 출력처럼 만들어
esl.io.bforce_ondemand.merge 로 병합 → stage esl: 경계력 등급 contact(CONT+ACC)·full(CONT+CONT2+MASS), 내력(FINT) 계산,
같은 프레임 자료를 비덤프 추출 pack 으로 만든 Case 와 04_esl/bforce.npz·fint.npz 비트 동일. 보충 실패·생략 기록 →
경계력·내력 같은 code(BF_EXTRACT_FAILED·SKIPPED)·같은 reason, 04_esl 에 bforce·fint 파일 없음, 경고 1건, esl_summary.json
불변. 기록 없음 = BF_NO_DATA(v0.24.1 비덤프 문구 그대로, 덤프 방식은 실제 원인 문구).
"""
import json
import os
import shutil

import numpy as np
import pytest

import synth_case
from esl import pipeline
from esl.io import bforce_csv as bfc
from esl.io import bforce_ondemand as bfo
from esl.mech import bforce as bfm
from esl.mech.mass import lumped_mass
from esl.rad import parse_rad

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")
A0 = np.array([300.0, -9810.0 * 150.0, 2.0e5])
TS = synth_case.T_STAR_FRAME
NAMES = {"result_names": {"cont": ["Contact Forces"]}, "vec_comps": ["X", "Y", "Z"], "scalar_comps": ["Scalar value"]}
TYPE = {"cont": "Contact Forces", "cont2": "Tied Contact Forces", "acc": "Acceleration", "mass": "Nodal Mass",
        "fint": "Internal Forces"}
NO_DATA_OLD = "추출물에 경계력 결과 없음(v0.24.0 이전 추출이거나 bf_on 0) — h3d 추출을 다시 실행"           # v0.24.1 문구
FINT_NO_DATA_OLD = "추출물에 경계력·내력 결과 없음(v0.24.0 이전 추출이거나 bf_on 0) — h3d 추출을 다시 실행"


def _mass(c):
    model = parse_rad(c["rad"], "chassis rear")
    rho_e, _ = bfm.rho_per_elem(np.full(model.elem_id.size, model.mats[0]["id"]), model.mats, 7.85e-9)
    return lumped_mass({"x0": model.x0, "conn": model.conn, "elem_type": model.elem_type, "thickness": model.thickness},
                       rho_e)


def _kinds_at(c, m, k, kinds):
    """프레임 k 의 노드 힘(test_bforce_stage 와 같은 합성: 내력 = K u 회전, 강체 감속 A0). full = CONT·CONT2 로 나눔."""
    Q = synth_case.rot([0.3, -0.5, 0.8], np.radians(25.0) * k / synth_case.T_STAR_FRAME)
    Fint = (synth_case.A_T[k] * (c["F_app"] + c["R"]) + synth_case.B_T[k] * (c["F2"] + c["R2"])) @ Q.T
    acc = np.broadcast_to(A0, c["X0"].shape)
    full = "cont2" in kinds
    v = {"cont": (0.6 * Fint if full else Fint) + m[:, None] * acc, "cont2": 0.4 * Fint, "acc": np.array(acc),
         "mass": m, "fint": -Fint}
    return {kk: v[kk] for kk in kinds}


def _write_csvs(d, c, m, frames, kinds):
    rows = {k: [] for k in kinds}
    for f in frames:
        vals = _kinds_at(c, m, f, kinds)
        for k in kinds:
            a = vals[k]
            for i, n in enumerate(c["node_id"]):
                rows[k].append(f"{f},{n}," + (repr(float(a[i])) if k == "mass" else ",".join(repr(float(x)) for x in a[i])))
    kd = {}
    for k in bfc.KINDS:
        if k not in kinds:
            kd[k] = {"type": None, "reason": f"not in h3d: {k}"}
            continue
        hdr = "frame_index,node_id,v" if k == "mass" else "frame_index,node_id,x,y,z"
        with open(os.path.join(d, f"bf_{k}.csv"), "w", encoding="utf-8") as fh:
            fh.write(hdr + "\n" + "\n".join(rows[k]) + "\n")
        kd[k] = {"type": TYPE[k], "comps": ["Scalar value"] if k == "mass" else ["X", "Y", "Z"], "rows": len(rows[k])}
    return kd


def _fill(root, name, case, c, m, kinds):
    """bf 전용 추출(TCL bf_only) 출력 흉내: 선택 프레임만, n_frames·frame_times = 추출 frames.json 과 같은 값."""
    out = os.path.join(root, name)
    os.makedirs(out)
    meta = json.load(open(os.path.join(case, "01_extract", "frames.json"), encoding="utf-8"))
    kd = _write_csvs(out, c, m, [TS], kinds)
    json.dump({"ok": True, "mode": "bf_only", "h3d": "x.h3d", "n_frames": meta["n_frames_h3d"], "frames": [TS],
               "frame_times": [meta["time_D"][meta["frames_D"].index(TS)]],
               "bforce": {"on": True, "frames": [TS], "kinds": kd}}, open(os.path.join(out, "done.json"), "w"))
    return out


def _run(cfg, c, csv, out, stages, tag=None):
    for st in stages:
        kw = {"frame": TS, "tag": tag} if st == "esl" else {}
        pipeline.run(cfg, c["rad"], csv, out, stage=st, echo=lambda *_: None, **kw)


def _j(*p):
    return json.load(open(os.path.join(*p), encoding="utf-8"))


def _summ(out):
    return _j(out, "run.json")["stages"]["esl"]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("bfod"))
    cfg = os.path.join(root, "esl64.yaml")
    open(cfg, "w", encoding="utf-8").write(CFG64_TEXT)
    cd = synth_case.build(os.path.join(root, "dump"), source="strain_tensor")
    cn = synth_case.build(os.path.join(root, "nd"))
    m = _mass(cn)
    base = os.path.join(root, "out_dump_base")
    _run(cfg, cd, cd["csv"], base, ("extract", "tstar"))
    outs = {}
    for name in ("d_contact", "d_full", "d_failed", "d_skipped", "d_norec", "d_other"):
        outs[name] = os.path.join(root, "out_" + name)
        shutil.copytree(base, outs[name])
    # 덤프 Case + 보충 병합(같은 Case·프레임 — 다음 ESL 부터 재사용)
    res = {}
    for name, kinds in (("d_contact", ("cont", "acc", "fint")), ("d_full", ("cont", "cont2", "acc", "mass"))):
        assert not bfc.has_frame(os.path.join(outs[name], "01_extract"), TS)
        res[name] = bfo.merge(outs[name], _fill(root, "fill_" + name, outs[name], cd, m, kinds), [TS], tag="job-" + name,
                              names=NAMES)
        _run(cfg, cd, cd["csv"], outs[name], ("esl",), tag="job-" + name)
    # 보충 실패·생략 기록(이 작업 tag), 다른 작업 기록, 기록 없음
    xd = lambda n: os.path.join(outs[n], "01_extract")                    # noqa: E731
    bfo.record(xd("d_failed"), {"frame_index": TS, "job_id": "job-f", "status": "failed", "cause": "TIMEOUT",
                                "detail": "시간 초과 1800 s(altair.bf_on_demand_timeout_s)"})
    bfo.record(xd("d_skipped"), {"frame_index": TS, "job_id": "job-s", "status": "skipped", "cause": "HW_UNAVAILABLE",
                                 "detail": "서버 HyperWorks 실행 파일 또는 추출 TCL 없음(altair.hw_exe_path)"})
    bfo.record(xd("d_other"), {"frame_index": TS, "job_id": "job-old", "status": "failed", "cause": "HW_FAILED",
                               "detail": "x"})
    for name, tag in (("d_failed", "job-f"), ("d_skipped", "job-s"), ("d_norec", "job-n"), ("d_other", "job-n")):
        _run(cfg, cd, cd["csv"], outs[name], ("esl",), tag=tag)
    # 같은 프레임 자료를 비덤프 추출 pack(done.json bforce + bf CSV, 후보 프레임 D 전체)으로 만든 Case
    for name, kinds in (("n_contact", ("cont", "acc", "fint")), ("n_full", ("cont", "cont2", "acc", "mass"))):
        csv = os.path.join(root, "nd", "in", "csv_" + name)
        shutil.copytree(cn["csv"], csv)
        done = _j(csv, "done.json")
        D = list(done["frames_D"])
        assert TS in D
        done["bforce"] = {"on": True, "frames": D, "kinds": _write_csvs(csv, cn, m, D, kinds)}
        json.dump(done, open(os.path.join(csv, "done.json"), "w"))
        outs[name] = os.path.join(root, "out_" + name)
        _run(cfg, cn, csv, outs[name], ("extract", "tstar", "esl"), tag="job-" + name)
    plain = os.path.join(root, "out_plain")
    _run(cfg, cn, cn["csv"], plain, ("extract", "tstar", "esl"), tag="job-p")
    outs["plain"] = plain
    return {"outs": outs, "res": res}


def _npz_equal(a, b):
    with np.load(a, allow_pickle=False) as za, np.load(b, allow_pickle=False) as zb:
        assert sorted(za.files) == sorted(zb.files)
        for k in za.files:
            assert np.array_equal(za[k], zb[k]), k


# ------------------------------------------------------------------ V-0242-BFD-5
def test_v0242_bfd5_dump_case_filled_contact_and_fint(runs):
    o = runs["outs"]
    r = runs["res"]["d_contact"]
    assert r["added"] == [TS] and r["frames_before"] == [] and r["backup"] is None
    st = _summ(o["d_contact"])["summary"]
    assert st["bforce"]["grade"] == "contact" and st["bforce"]["recon"] == "ok" and st["bforce"]["mac"] > 0.999
    assert st["fint"]["grade"] == "fint"
    d = _j(o["d_contact"], "04_esl", "bforce.json")
    assert d["grade"] == "contact" and d["frame"]["frame_index"] == TS
    assert d["result_types"]["cont"]["frames"] == [TS]                    # 병합 문서(kinds[k].frames)
    fi = _j(o["d_contact"], "04_esl", "fint.json")
    assert fi["grade"] == "fint" and fi["recon"]["status"] == "ok"
    # 같은 프레임 자료를 비덤프 pack 으로 만든 Case 와 비트 동일
    for fn in ("bforce.npz", "fint.npz"):
        _npz_equal(os.path.join(o["d_contact"], "04_esl", fn), os.path.join(o["n_contact"], "04_esl", fn))
    assert not any(w.startswith(("BF_EXTRACT", "BF_NO_DATA")) for w in _summ(o["d_contact"])["warnings"])


def test_v0242_bfd5_dump_case_filled_full(runs):
    o = runs["outs"]
    st = _summ(o["d_full"])["summary"]
    assert st["bforce"]["grade"] == "full" and st["bforce"]["mass_source"] == "h3d"
    assert st["fint"]["grade"] == "none" and st["fint"]["code"] == "FINT_NO_DATA"   # FINT 유형 없음 = 기존 규칙
    _npz_equal(os.path.join(o["d_full"], "04_esl", "bforce.npz"), os.path.join(o["n_full"], "04_esl", "bforce.npz"))
    xd = os.path.join(o["d_full"], "01_extract")
    assert bfc.has_frame(xd, TS)                                          # 다음 ESL 부터 재사용(보충 안 함)
    assert not os.path.isfile(os.path.join(xd, "bforce_ondemand.json"))   # 기록은 워커 몫


# ------------------------------------------------------------------ V-0242-BFD-6
def _no_bf_files(out):
    return not any(os.path.isfile(os.path.join(out, "04_esl", f)) for f in ("bforce.json", "bforce.npz", "fint.json",
                                                                             "fint.npz"))


def _clean(o):
    """시각·태그·시간·메모리 측정값 제외(그 밖 내용은 바이트 동일해야 함)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k not in ("created_at", "tag")
                and not k.endswith(("_s", "_seconds", "_mb")) and not k.startswith("mem_")}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _esl_summary_core(out):
    return _clean(_j(out, "04_esl", "esl_summary.json"))


def test_v0242_bfd6_fill_failed_record(runs):
    o = runs["outs"]
    e = _summ(o["d_failed"])
    reason = ("경계력 원자료 보충 실패 — 프레임 6: 시간 초과 1800 s(altair.bf_on_demand_timeout_s). "
              "③ ESL 을 다시 계산하면 다시 시도합니다")
    assert e["summary"]["bforce"] == {"grade": "none", "code": "BF_EXTRACT_FAILED", "reason": reason}
    assert e["summary"]["fint"] == {"grade": "none", "code": "BF_EXTRACT_FAILED", "reason": reason}   # 같은 code·reason
    assert [w for w in e["warnings"] if "BF_EXTRACT" in w] == ["BF_EXTRACT_FAILED: " + reason]      # 경고 1건
    assert _no_bf_files(o["d_failed"])
    assert _esl_summary_core(o["d_failed"]) == _esl_summary_core(o["d_norec"])            # 전 노드 ESL 불변
    for fn in ("f_eq.npz", "u_rel.npz"):
        _npz_equal(os.path.join(o["d_failed"], "04_esl", fn), os.path.join(o["d_norec"], "04_esl", fn))


def test_v0242_bfd6_fill_skipped_record(runs):
    e = _summ(runs["outs"]["d_skipped"])
    reason = "경계력 원자료 보충 생략 — 프레임 6: 서버 HyperWorks 실행 파일 또는 추출 TCL 없음(altair.hw_exe_path)"
    assert e["summary"]["bforce"] == {"grade": "none", "code": "BF_EXTRACT_SKIPPED", "reason": reason}
    assert e["summary"]["fint"] == {"grade": "none", "code": "BF_EXTRACT_SKIPPED", "reason": reason}
    assert e["warnings"].count("BF_EXTRACT_SKIPPED: " + reason) == 1 and _no_bf_files(runs["outs"]["d_skipped"])


def test_v0242_bfd6_no_record_reasons(runs):
    o = runs["outs"]
    # 비덤프 옛 추출(bforce 없음) = v0.24.1 BF_NO_DATA·FINT_NO_DATA 문구 그대로, 파일 없음, 경고 없음
    p = _summ(o["plain"])
    assert p["summary"]["bforce"] == {"grade": "none", "code": "BF_NO_DATA", "reason": NO_DATA_OLD}
    assert p["summary"]["fint"] == {"grade": "none", "code": "FINT_NO_DATA", "reason": FINT_NO_DATA_OLD}
    assert _no_bf_files(o["plain"]) and not any("BF_" in w for w in p["warnings"])
    # 덤프 방식(기록 없음 — on_demand false·결과 폴더 입력 등) = 실제 원인 문구, 다른 작업의 기록은 보지 않음
    for name in ("d_norec", "d_other"):
        s = _summ(o[name])
        b, f = s["summary"]["bforce"], s["summary"]["fint"]
        assert b["code"] == "BF_NO_DATA" and "덤프 방식 추출" in b["reason"] and "bforce.on_demand" in b["reason"]
        assert f["code"] == "FINT_NO_DATA" and "덤프 방식 추출" in f["reason"]
        assert _no_bf_files(o[name]) and not any("BF_" in w for w in s["warnings"])
    assert _esl_summary_core(o["d_other"]) == _esl_summary_core(o["d_norec"])


def test_v0242_bfd6_frame_missing_after_merge(runs, tmp_path):
    """병합 뒤 다른 프레임을 고름(그 프레임 자료 없음·기록 없음) = BF_NO_DATA(선택 프레임 문구), 04_esl 에 쓰지 않음."""
    o = runs["outs"]
    out = str(tmp_path / "o")
    shutil.copytree(o["d_contact"], out)
    shutil.rmtree(os.path.join(out, "04_esl"))
    cfg = str(tmp_path / "c.yaml")
    open(cfg, "w", encoding="utf-8").write(CFG64_TEXT)
    rj = _j(out, "run.json")
    fr = [x["frame_index"] for x in _j(out, "02_tstar", "tstar.json")["frames_D"]]
    other = next(f for f in fr if f != TS)
    pipeline.run(cfg, rj["history"][0]["rad"], rj["history"][0]["results"], out, stage="esl", frame=other,
                 echo=lambda *_: None, tag="job-x")
    s = _summ(out)["summary"]
    assert s["bforce"]["code"] == "BF_NO_DATA" and f"선택 프레임 {other}" in s["bforce"]["reason"]
    assert f"[{TS}]" in s["bforce"]["reason"] and s["fint"]["code"] == "FINT_NO_DATA"
    assert _no_bf_files(out)
