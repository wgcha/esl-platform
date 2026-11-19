"""v0.24.2 경계력 원자료 보충 병합·시도 기록(계약 esl_bforce_ondemand.md §1.3·§4, V-0242-BFD-4).

esl.io.bforce_ondemand.merge: bf 전용 추출 출력(done.json mode bf_only + bf_<kind>.csv) → Case 01_extract/bforce.* 병합 —
(a) 자료 없음 → 새 json/npz (b) 기존 D ∪ f, 기존 배열 비트 동일, 이전 파일 _backup (c) 같은 프레임 = 덮어쓰지 않음(dup)
(d) 종류 집합이 다름 → kinds[k].frames·frame_data (e) 같은 h3d 아님 → BF_FILL_MISMATCH·아무것도 안 씀 (f) 남은 tmp 무시
(g) record·note·no_types_before. 끝으로 TCL(가짜 hwi) 비덤프 추출 + bf 전용 추출 → 병합 왕복(시간 정확 일치).
"""
import ast
import hashlib
import json
import os

import numpy as np
import pytest

from esl.errors import EslError
from esl.io import bforce_csv as bfc
from esl.io import bforce_ondemand as bfo
from esl.io.backup import BACKUP_TS_FMT

NID = np.array([10, 20, 30, 40, 50], dtype=np.int64)
F = 6
T = [0.0, 1.0e-3, 2.0e-3, 3.0000000000000001e-3, 4.0e-3, 5.0e-3]
NAMES = {"result_names": {"cont": ["Contact Forces"], "acc": ["Acceleration"]}, "vec_comps": ["X", "Y", "Z"],
         "scalar_comps": ["Scalar value"]}
TYPE = {"cont": "Contact Forces", "cont2": "Tied Contact Forces", "acc": "Acceleration", "mass": "Nodal Mass",
        "fint": "Internal Forces"}


def _vals(seed=1):
    rng = np.random.default_rng(seed)
    v = {k: rng.normal(size=(F, NID.size, 3)) for k in ("cont", "cont2", "acc", "fint")}
    v["mass"] = rng.uniform(1.0, 2.0, size=(F, NID.size))
    return v


VALS = _vals()


def _csvs(d, frames, kinds, vals=VALS, skip_node=None):
    os.makedirs(d, exist_ok=True)
    out = {}
    for k in bfc.KINDS:
        if k not in kinds:
            out[k] = {"type": None, "reason": f"not in h3d: {k}"}
            continue
        vec = k != "mass"
        rows = []
        for f in frames:
            for i, n in enumerate(NID):
                if skip_node is not None and n == skip_node:
                    continue
                v = vals[k][f, i]
                rows.append(f"{f},{n}," + (",".join(repr(float(x)) for x in v) if vec else repr(float(v))))
        rows.append(f"{frames[0]},999,1,2,3" if vec else f"{frames[0]},999,1")    # 대상 파트 밖 노드 = 무시
        hdr = "frame_index,node_id,x,y,z" if vec else "frame_index,node_id,v"
        with open(os.path.join(d, f"bf_{k}.csv"), "w", encoding="utf-8") as fh:
            fh.write(hdr + "\n" + "\n".join(rows) + "\n")
        out[k] = {"type": TYPE[k], "comps": ["X", "Y", "Z"] if vec else ["Scalar value"], "rows": len(rows)}
    return out


def _case(tmp_path, D=None, kinds=("cont", "acc"), frames_D=None):
    """Case 폴더: 01_extract/model.npz·frames.json(+ D 가 있으면 추출 pack 의 bforce.*)."""
    case = tmp_path / "case"
    xd = case / "01_extract"
    xd.mkdir(parents=True)
    np.savez_compressed(xd / "model.npz", node_id=NID)
    fD = list(frames_D if frames_D is not None else range(F))
    (xd / "frames.json").write_text(json.dumps({"schema": "esl/frames/2", "n_frames_h3d": F, "frame_index": list(range(F)),
                                                "time": T, "frames_D": fD, "time_D": [T[f] for f in fD]}))
    if D is not None:
        raw = tmp_path / "raw_extract"
        kd = _csvs(str(raw), D, kinds)
        (raw / "done.json").write_text(json.dumps({"ok": True, "frames_D": D,
                                                   "bforce": {"on": True, "frames": D, "kinds": kd}}))
        assert bfc.pack_bforce(str(raw), NID, str(xd)) is not None
    return str(case), str(xd)


def _fill(tmp_path, frames, kinds=("cont", "acc"), name="fill", n_frames=F, times=None, mode="bf_only", ok=True,
          skip_node=None):
    out = tmp_path / name
    kd = _csvs(str(out), sorted(frames), kinds, skip_node=skip_node)
    fs = sorted(frames)
    done = {"ok": ok, "h3d": "/in/x.h3d", "mode": mode, "n_frames": n_frames, "n_nodes": NID.size, "frames": fs,
            "frame_times": times if times is not None else [T[f] for f in fs],
            "bforce": {"on": True, "frames": fs, "kinds": kd}, "passes": {"BF": {"frames": fs}}}
    (out / "done.json").write_text(json.dumps(done))
    return str(out)


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _snap(d):
    return {f: _sha(os.path.join(d, f)) for f in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, f))}


# ------------------------------------------------------------------ (a) 자료 없음 → 새 문서
def test_v0242_bfd4a_merge_into_empty(tmp_path):
    case, xd = _case(tmp_path)
    assert not bfc.has_frame(xd, 3)
    res = bfo.merge(case, _fill(tmp_path, [3]), [3], tag="job-1", names=NAMES)
    assert res["frames_before"] == [] and res["frames_after"] == [3] and res["added"] == [3] and res["dup"] == []
    assert res["kinds"] == {"cont": "Contact Forces", "cont2": None, "acc": "Acceleration", "mass": None, "fint": None}
    assert res["rows"] == {"cont": 5, "acc": 5} and res["backup"] is None
    assert not os.path.isdir(os.path.join(case, "_backup"))                 # 이전 파일 없음 = 백업 없음
    doc = json.load(open(os.path.join(xd, "bforce.json"), encoding="utf-8"))
    assert doc["schema"] == "esl/bforce_extract/1" and doc["on"] is True and doc["frames"] == [3]
    assert doc["kinds"]["cont"] == {"type": "Contact Forces", "comps": ["X", "Y", "Z"], "rows": 5, "n_missing": 0,
                                    "frames": [3]}
    assert doc["kinds"]["fint"]["type"] is None and doc["kinds"]["fint"]["reason"]
    assert doc["fills"][0]["frames"] == [3] and doc["fills"][0]["job_id"] == "job-1" and doc["fills"][0]["names"] == NAMES
    assert bfc.has_frame(xd, 3) and not bfc.has_frame(xd, 2)
    dat, _ = bfc.frame_data(xd, 3)
    assert np.array_equal(dat["cont"], VALS["cont"][3]) and np.array_equal(dat["acc"], VALS["acc"][3])   # 비트 보존
    assert dat["cont2"] is None and dat["mass"] is None and dat["fint"] is None
    with np.load(os.path.join(xd, "bforce.npz")) as z:
        assert z["frame_index"].tolist() == [3] and np.array_equal(z["node_id"], NID)


# ------------------------------------------------------------------ (b) 비덤프 D + f∉D
def test_v0242_bfd4b_merge_union_keeps_old_and_backs_up(tmp_path):
    case, xd = _case(tmp_path, D=[1, 4])
    before = _snap(xd)
    with np.load(os.path.join(xd, "bforce.npz")) as z:
        old = {k: z[k].copy() for k in z.files}
    res = bfo.merge(case, _fill(tmp_path, [3]), [3], tag="j", names=NAMES)
    assert res["frames_before"] == [1, 4] and res["frames_after"] == [1, 3, 4] and res["added"] == [3]
    with np.load(os.path.join(xd, "bforce.npz")) as z:
        assert z["frame_index"].tolist() == [1, 3, 4]
        for k in ("cont", "acc"):
            assert np.array_equal(z[k][[0, 2]], old[k])                     # 기존 프레임 배열 비트 동일
            assert np.array_equal(z[k][1], VALS[k][3])
    doc = json.load(open(os.path.join(xd, "bforce.json"), encoding="utf-8"))
    assert doc["frames"] == [1, 3, 4] and doc["kinds"]["cont"]["frames"] == [1, 3, 4]
    assert doc["kinds"]["cont"]["rows"] == 15 and len(doc["fills"]) == 1
    # 이전 파일 → <case>/_backup/<UTC>/01_extract/ (내용 그대로)
    assert res["backup"].startswith("_backup/") and res["backup"].endswith("/01_extract")
    bdir = os.path.join(case, res["backup"])
    ts = res["backup"].split("/")[1]
    import datetime as dt
    dt.datetime.strptime(ts, BACKUP_TS_FMT)
    assert _snap(bdir) == {k: before[k] for k in ("bforce.json", "bforce.npz")}
    # 01_extract 의 그 밖 파일은 바이트 동일, 임시 파일 없음
    after = _snap(xd)
    assert {k: after[k] for k in ("model.npz", "frames.json")} == {k: before[k] for k in ("model.npz", "frames.json")}
    assert not [f for f in os.listdir(xd) if ".tmp-" in f]
    for f in (1, 4):
        dat, _ = bfc.frame_data(xd, f)
        assert np.array_equal(dat["cont"], VALS["cont"][f])


# ------------------------------------------------------------------ (c) 같은 프레임 = 덮어쓰지 않음
def test_v0242_bfd4c_existing_frame_not_overwritten(tmp_path):
    case, xd = _case(tmp_path, D=[1, 4])
    before = _snap(xd)
    other = _vals(seed=9)
    fill = _fill(tmp_path, [4])
    with open(os.path.join(fill, "bf_cont.csv"), "w", encoding="utf-8") as fh:   # 다른 값이어도 기존 유지
        fh.write("frame_index,node_id,x,y,z\n" + "\n".join(
            f"4,{n},{other['cont'][4, i, 0]!r},0,0" for i, n in enumerate(NID)) + "\n")
    res = bfo.merge(case, fill, [4], tag="j", names=NAMES)
    assert res["added"] == [] and res["dup"] == [4] and res["frames_after"] == [1, 4]
    assert any(w.startswith("BF_FILL_DUP") for w in res["warnings"])
    assert _snap(xd) == before and not os.path.isdir(os.path.join(case, "_backup"))


# ------------------------------------------------------------------ (d) 종류 집합이 다름
def test_v0242_bfd4d_kind_sets_differ(tmp_path):
    case, xd = _case(tmp_path, D=[1, 4], kinds=("cont", "acc"))
    bfo.merge(case, _fill(tmp_path, [3], kinds=("cont", "fint", "mass")), [3], tag="j", names=NAMES)
    doc = json.load(open(os.path.join(xd, "bforce.json"), encoding="utf-8"))
    k = doc["kinds"]
    assert k["cont"]["frames"] == [1, 3, 4] and k["acc"]["frames"] == [1, 4] and k["fint"]["frames"] == [3]
    assert k["mass"]["frames"] == [3] and k["mass"]["comps"] == ["Scalar value"] and k["cont2"]["type"] is None
    d3, _ = bfc.frame_data(xd, 3)
    assert d3["acc"] is None and np.array_equal(d3["fint"], VALS["fint"][3]) and np.array_equal(d3["mass"], VALS["mass"][3])
    d1, _ = bfc.frame_data(xd, 1)
    assert d1["fint"] is None and d1["mass"] is None and np.array_equal(d1["acc"], VALS["acc"][1])
    # 새 프레임에서 종류를 하나도 못 찾음 → json 만(새 프레임 "있음"), npz 그대로(옛 프레임 자료)
    npz_before = _sha(os.path.join(xd, "bforce.npz"))
    res = bfo.merge(case, _fill(tmp_path, [5], kinds=(), name="fill_none"), [5], tag="j2", names=NAMES)
    assert res["added"] == [5] and res["kinds"] == {k_: None for k_ in bfc.KINDS} and res["rows"] == {}
    assert _sha(os.path.join(xd, "bforce.npz")) == npz_before
    assert bfc.has_frame(xd, 5) and bfc.frame_data(xd, 5)[0] == {}
    assert json.load(open(os.path.join(xd, "bforce.json"), encoding="utf-8"))["frames"] == [1, 3, 4, 5]
    d3b, _ = bfc.frame_data(xd, 3)
    assert np.array_equal(d3b["fint"], VALS["fint"][3])


def test_v0242_bfd4d_missing_nodes_zero(tmp_path):
    case, xd = _case(tmp_path)
    res = bfo.merge(case, _fill(tmp_path, [2], skip_node=30), [2], tag="j", names=NAMES)
    assert any(w.startswith("BF_FILL_MISSING: cont") for w in res["warnings"])
    doc = json.load(open(os.path.join(xd, "bforce.json"), encoding="utf-8"))
    assert doc["kinds"]["cont"]["n_missing"] == 1 and doc["kinds"]["cont"]["rows"] == 4
    dat, _ = bfc.frame_data(xd, 2)
    assert not dat["cont"][2].any() and np.array_equal(dat["cont"][0], VALS["cont"][2, 0])


# ------------------------------------------------------------------ (e) 같은 h3d 아님 · bf 전용 출력 아님
@pytest.mark.parametrize("kw,code,msg", [
    (dict(n_frames=F + 1), "BF_FILL_MISMATCH", f"h3d 프레임 {F + 1} ≠ 추출 {F}"),
    (dict(times=[3.1e-3]), "BF_FILL_MISMATCH", "프레임 3 시간"),
    (dict(mode="full"), "BF_FILL_OUTPUT", "bf 전용 추출 출력이 아님"),
    (dict(ok=False), "BF_FILL_OUTPUT", "성공이 아님"),
])
def test_v0242_bfd4e_mismatch_writes_nothing(tmp_path, kw, code, msg):
    case, xd = _case(tmp_path, D=[1, 4])
    before = _snap(xd)
    with pytest.raises(EslError) as e:
        bfo.merge(case, _fill(tmp_path, [3], **kw), [3], tag="j", names=NAMES)
    assert e.value.code == code and msg in e.value.message
    assert _snap(xd) == before and not os.path.isdir(os.path.join(case, "_backup"))


def test_v0242_bfd4e_requested_frame_not_in_fill(tmp_path):
    case, xd = _case(tmp_path)
    with pytest.raises(EslError) as e:
        bfo.merge(case, _fill(tmp_path, [2]), [3], tag="j", names=NAMES)
    assert e.value.code == "BF_FILL_OUTPUT" and "[3]" in e.value.message
    assert not os.path.isfile(os.path.join(xd, "bforce.json"))


# ------------------------------------------------------------------ (f) 남은 tmp 무시·덮어씀
def test_v0242_bfd4f_leftover_tmp_ignored(tmp_path):
    case, xd = _case(tmp_path, D=[1])
    stale = os.path.join(xd, "bforce.json.tmp-99999999")
    open(stale, "w").write("garbage")
    open(os.path.join(xd, f"bforce.npz.tmp-{os.getpid()}"), "wb").write(b"old tmp")
    bfo.merge(case, _fill(tmp_path, [2]), [2], tag="j", names=NAMES)
    assert open(stale).read() == "garbage"                                  # 다른 프로세스 tmp = 그대로
    assert not os.path.exists(os.path.join(xd, f"bforce.npz.tmp-{os.getpid()}"))
    assert bfc.has_frame(xd, 2) and bfc.has_frame(xd, 1)
    with np.load(os.path.join(xd, "bforce.npz")) as z:
        assert z["frame_index"].tolist() == [1, 2]


# ------------------------------------------------------------------ (g) 시도 기록
def _att(frame, job, status, **kw):
    a = {"frame_index": frame, "job_id": job, "status": status, "cause": kw.pop("cause", None),
         "detail": kw.pop("detail", ""), "names": kw.pop("names", NAMES), "kinds": kw.pop("kinds", None)}
    a.update(kw)
    return a


def test_v0242_bfd4g_record_note_no_types(tmp_path):
    case, xd = _case(tmp_path)
    assert bfo.note(xd, 3, "A") is None and bfo.no_types_before(xd, NAMES) is None
    bfo.record(xd, _att(3, "A", "failed", cause="TIMEOUT", detail="시간 초과 1800 s(altair.bf_on_demand_timeout_s)"))
    bfo.record(xd, _att(3, "B", "skipped", cause="WAIT", detail="대기"))
    bfo.record(xd, _att(5, "A", "ok", kinds={"cont": "Contact Forces"}))
    doc = json.load(open(os.path.join(xd, "bforce_ondemand.json"), encoding="utf-8"))
    assert doc["schema"] == "esl/bforce_ondemand/1" and len(doc["attempts"]) == 3
    assert doc["attempts"][0]["code"] == "BF_EXTRACT_FAILED" and doc["attempts"][2]["code"] is None
    assert all(a["at"] for a in doc["attempts"])
    assert bfo.note(xd, 3, "A") == {"code": "BF_EXTRACT_FAILED", "cause": "TIMEOUT",
                                    "detail": "시간 초과 1800 s(altair.bf_on_demand_timeout_s)"}
    assert bfo.note(xd, 3, "B")["code"] == "BF_EXTRACT_SKIPPED"
    assert bfo.note(xd, 5, "A") is None and bfo.note(xd, 3, "C") is None and bfo.note(xd, 3, None) is None
    bfo.record(xd, _att(3, "A", "ok", kinds={"cont": "Contact Forces"}))     # 마지막 시도 기준
    assert bfo.note(xd, 3, "A") is None
    # 판정 5: 같은 이름 후보의 가장 최근 성공 시도가 종류 0
    none_k = {k: None for k in bfc.KINDS}
    bfo.record(xd, _att(4, "D", "ok", kinds=none_k))
    hit = bfo.no_types_before(xd, json.loads(json.dumps(NAMES)))
    assert hit is not None and hit["job_id"] == "D" and hit["at"]
    other = {**NAMES, "vec_comps": ["X|x", "Y", "Z"]}
    assert bfo.no_types_before(xd, other) is None                          # 이름 후보가 바뀜 = 다시 시도
    bfo.record(xd, _att(4, "E", "ok", kinds={"cont": "Contact Forces"}))
    assert bfo.no_types_before(xd, NAMES) is None                          # 최근 시도가 종류를 찾음
    with pytest.raises(EslError):
        bfo.record(xd, {"frame_index": 1, "status": "maybe"})


def test_v0242_bfd4g_corrupt_record_backed_up(tmp_path):
    case, xd = _case(tmp_path)
    open(os.path.join(xd, "bforce_ondemand.json"), "w").write("{not json")
    assert bfo.note(xd, 3, "A") is None
    bfo.record(xd, _att(3, "A", "skipped", cause="HW_UNAVAILABLE", detail="x"))
    assert bfo.note(xd, 3, "A")["code"] == "BF_EXTRACT_SKIPPED"
    bk = [os.path.join(b, f) for b, _d, fs in os.walk(os.path.join(case, "_backup")) for f in fs]
    assert len(bk) == 1 and open(bk[0]).read() == "{not json"               # 깨진 기록 = 지우지 않고 백업


def test_v0242_bfd4_module_independent():
    p = os.path.join(os.path.dirname(bfo.__file__), "bforce_ondemand.py")
    mods = set()
    for n in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    esl_mods = {m for m in mods if m.startswith("esl")}
    assert esl_mods <= {"esl.errors", "esl.io", "esl.io.bforce_csv", "esl.io.results_csv", "esl.io.backup"}, esl_mods
    assert not any(m.startswith(("esl.pipeline", "esl.doe", "esl.config", "yaml")) for m in mods)


# ------------------------------------------------------------------ TCL(가짜 hwi) 왕복: 비덤프 추출 D + bf 전용 f∉D
def test_v0242_bfd4_tcl_roundtrip(tmp_path):
    tm = pytest.importorskip("test_tcl_mock")
    tb = pytest.importorskip("test_tcl_bforce")
    if tm.TCLSH is None:
        pytest.skip("tclsh 없음")
    from esl.io import pack_results
    types = {"Contact Forces": (["X", "Y", "Z"], False), "Acceleration": (["X", "Y", "Z", "Mag"], False)}
    nid = np.arange(1, 13)
    mock, vals = tb._bf_mock(types, nid)
    (tmp_path / "x").mkdir()
    m, ref, drv, out = tm._setup(tmp_path / "x", mock_extra=mock, extra_req="bf_on\t1\n")
    assert tm._run(drv).returncode == 0
    case = tmp_path / "case"
    xd = case / "01_extract"
    pack_results(out, m, xd)
    np.savez_compressed(xd / "model.npz", node_id=np.asarray(m.node_id, dtype=np.int64))
    bfc.pack_bforce(str(out), m.node_id, str(xd))
    D = json.load(open(xd / "bforce.json"))["frames"]
    f = next(i for i in range(tm.F) if i not in D)
    meta = json.load(open(xd / "frames.json"))
    meta["frames_D"], meta["time_D"] = meta["frames_D"] + [f], meta["time_D"] + [meta["time"][meta["frame_index"].index(f)]]
    (xd / "frames.json").write_text(json.dumps(meta))          # 덤프 방식처럼 f 도 후보(시간은 frames.csv 그대로)
    (tmp_path / "y").mkdir()
    _m, _r, drv2, fill = tm._setup(tmp_path / "y", mock_extra=mock,
                                   extra_req=f"bf_on\t1\nbf_only\t1\nbf_frames\t{f}\n")
    assert tm._run(drv2).returncode == 0
    res = bfo.merge(str(case), str(fill), [f], tag="esl-job", names=NAMES)   # 시간 정확 일치(MISMATCH 아님)
    assert res["added"] == [f] and res["frames_after"] == sorted(D + [f])
    dat, _ = bfc.frame_data(str(xd), f)
    assert np.array_equal(dat["cont"], vals["Contact Forces"][f]) and np.array_equal(dat["acc"], vals["Acceleration"][f][:, :3])
    for g in D:
        dg, _ = bfc.frame_data(str(xd), g)
        assert np.array_equal(dg["cont"], vals["Contact Forces"][g])
