"""v0.24.2 TCL bf 전용 모드(계약 esl_bforce_ondemand.md §2, V-0242-BFD-1·2·3) — 가짜 hwi(hwmock.tcl)로 tclsh 실행.

request `bf_on 1·bf_only 1·bf_frames "f …"` → 노드 선택·경계력 질의만(요소 선택·변형률·변위·랭킹·덤프 없음),
출력 = bf_<kind>.csv(요청 프레임 행만)·done.json(mode bf_only)·progress.log. bf_only 없음 = 기존 출력 바이트 동일
(패스 C 경계력 루프를 공용 proc ::esl::bf_chunk 로 뺀 전후 — v0.24.1 TCL 골든). tclsh 없으면 건너뜀.
"""
import hashlib
import json
import os

import numpy as np
import pytest

import test_tcl_bforce as tb
import test_tcl_mock as tm

pytestmark = pytest.mark.skipif(tm.TCLSH is None, reason="tclsh 없음")

TYPES = {"Contact Forces": (["X", "Y", "Z"], False), "Acceleration": (["X", "Y", "Z", "Mag"], False)}
NID = np.arange(1, 13)


def _calls(drv, tmp_path):
    """드라이버 끝에 가짜 hwi 호출 기록(선택 집합 종류·SetDataType·SetCurrentSimulation)을 파일로 쓰게 한다."""
    p = tmp_path / "calls.txt"
    drv.write_text(drv.read_text() +
                   f"set fh [open {{{p}}} w]\n"
                   "foreach x $::mock::addset_calls { puts $fh \"S\\t$x\" }\n"
                   "foreach x $::mock::dtype_calls { puts $fh \"D\\t$x\" }\n"
                   "foreach x $::mock::sim_calls { puts $fh \"F\\t$x\" }\n"
                   "close $fh\n")
    return p


def _read_calls(p):
    out = {"S": [], "D": [], "F": []}
    for line in p.read_text().splitlines():
        k, v = line.split("\t", 1)
        out[k].append(v)
    return out


def _bf_only(tmp_path, frames="5 2", extra="", types=TYPES, mock_more=""):
    mock, vals = tb._bf_mock(types, NID)
    req = f"bf_on\t1\nbf_only\t1\nbf_frames\t{frames}\n" + extra
    m, ref, drv, out = tm._setup(tmp_path, mock_extra=mock + ("\n" + mock_more if mock_more else ""), extra_req=req)
    cp = _calls(drv, tmp_path)
    r = tm._run(drv)
    return r, out, ref, vals, cp


def _rows(path):
    lines = path.read_text().splitlines()
    return lines[0], [ln.split(",") for ln in lines[1:]]


# ------------------------------------------------------------------ V-0242-BFD-1
def test_v0242_bfd1_bf_only_outputs(tmp_path):
    r, out, ref, vals, cp = _bf_only(tmp_path)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["mode"] == "bf_only" and done["frames"] == [2, 5]               # 오름차순 처리
    assert done["frame_times"] == [float(f"{ref['t'][f]:.6E}") for f in (2, 5)]  # frames.csv 와 같은 sim_time %.17g
    assert done["n_frames"] == tm.F and done["n_nodes"] == 12 and done["part_id"] == 7
    assert done["part_title"] == "chassis_rear" and done["subcase"] == "1"
    assert done["node_selection"] == "component 7" and done["chunks"] == {"node": "single"}
    bfd = done["bforce"]
    assert bfd["on"] is True and bfd["frames"] == [2, 5]
    assert bfd["kinds"]["cont"] == {"type": "Contact Forces", "comps": ["X", "Y", "Z"], "rows": 24}
    assert bfd["kinds"]["acc"] == {"type": "Acceleration", "comps": ["X", "Y", "Z"], "rows": 24}
    for k in ("cont2", "mass", "fint"):                                       # 없는 종류 = 실패 아님
        assert bfd["kinds"][k]["type"] is None and "not in h3d" in bfd["kinds"][k]["reason"]
    assert list(done["passes"]) == ["BF"]
    bp = done["passes"]["BF"]
    assert bp["frames"] == [2, 5] and bp["node_chunks"] == 1 and bp["rows"] == 48
    for k in ("strain_source", "strain_mode", "frames_D", "candidate_frames", "hot_k", "n_elems", "elems_ok"):
        assert k not in done, k                                               # 변형률·랭킹 멤버 없음
    # 출력 = bf CSV·done.json·progress.log 만(frames/model/elems/strain/disp CSV 없음)
    assert sorted(os.listdir(out)) == ["bf_acc.csv", "bf_cont.csv", "done.json", "progress.log"]
    for k, name in (("cont", "Contact Forces"), ("acc", "Acceleration")):
        hdr, rows = _rows(out / f"bf_{k}.csv")
        assert hdr == "frame_index,node_id,x,y,z" and len(rows) == 24
        assert sorted({int(r_[0]) for r_ in rows}) == [2, 5]
        for r_ in rows:                                                       # %.17g 비트 보존
            f, n = int(r_[0]), int(r_[1])
            assert [float(x) for x in r_[2:]] == vals[name][f, n - 1, :3].tolist()
    # 가짜 hwi 호출: 요소 선택 없음, SetDataType = 경계력 종류만, 요청 프레임만
    calls = _read_calls(cp)
    assert "element" not in calls["S"] and set(calls["S"]) <= {"component", "node"}
    assert set(calls["D"]) == {"Contact Forces", "Acceleration"}
    assert calls["F"] == ["2", "5"]
    log = (out / "progress.log").read_text()
    assert "bf-only: part 7 (chassis_rear): 12 nodes, 8 frames, frames {2 5}" in log
    assert "bforce: cont = Contact Forces {X Y Z}" in log
    assert "bf-only frame 5 (2/2) nodes chunk 1/1" in log and "bf-only done (" in log
    assert "extract done: bf-only mode (frames {2 5}), 12 nodes" in log
    assert log.isascii()


def test_v0242_bfd1_bf_only_chunked_and_query_failure(tmp_path):
    """노드 청크 3개(chunk 4) = 같은 행 집합, 한 종류 쿼리 실패 = 그 종류만 type null·CSV 삭제(실패 아님)."""
    r, out, _ref, vals, _cp = _bf_only(tmp_path, frames="3", extra="chunk\t4\n",
                                       mock_more="set ::mock::fail_query_dtype {Acceleration}")
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["passes"]["BF"]["node_chunks"] == 3
    assert done["chunks"]["node"].startswith("3 chunks")
    assert done["bforce"]["kinds"]["cont"]["rows"] == 12
    acc = done["bforce"]["kinds"]["acc"]
    assert acc["type"] is None and acc["reason"].startswith("query failed")
    assert done["passes"]["BF"]["rows"] == 12
    assert sorted(f for f in os.listdir(out) if f.startswith("bf_")) == ["bf_cont.csv"]
    _hdr, rows = _rows(out / "bf_cont.csv")
    assert {(int(a[0]), int(a[1])) for a in rows} == {(3, int(n)) for n in NID}
    assert any("bforce acc (Acceleration): query failed" in w for w in done["warnings"])


def test_v0242_bfd1_bf_only_no_types(tmp_path):
    """결과 유형이 하나도 없음 = ok true, 종류 전부 null, CSV 없음, 프레임 질의 없음."""
    r, out, _ref, _vals, cp = _bf_only(tmp_path, frames="1", types={})
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["mode"] == "bf_only" and done["frames"] == [1]
    assert all(v["type"] is None for v in done["bforce"]["kinds"].values())
    assert done["passes"]["BF"]["rows"] == 0
    assert sorted(os.listdir(out)) == ["done.json", "progress.log"]
    assert _read_calls(cp)["F"] == []


# ------------------------------------------------------------------ V-0242-BFD-2
@pytest.mark.parametrize("req,code,msg", [
    ("bf_only\t1\nbf_frames\t3\n", "INPUT_INVALID", "bf_only needs bf_on 1"),
    ("bf_on\t1\nbf_only\t1\n", "INPUT_INVALID", "bf_frames is empty"),
    ("bf_on\t1\nbf_only\t1\nbf_frames\t\n", "INPUT_INVALID", "bf_frames is empty"),
    ("bf_on\t1\nbf_only\t1\nbf_frames\t3 1 3\n", "INPUT_INVALID", "frame 3 twice"),
    ("bf_on\t1\nbf_only\t1\nbf_frames\t2 x\n", "INPUT_INVALID", "not a frame index"),
    ("bf_on\t1\nbf_only\t1\nbf_frames\t-1\n", "INPUT_INVALID", "not a frame index"),
    ("bf_on\t1\nbf_only\t1\nbf_frames\t2 8\n", "H3D_MISSING_RESULT", "bf_frames: frame 8 not in subcase 1 (8 frames)"),
])
def test_v0242_bfd2_bf_only_validation(tmp_path, req, code, msg):
    mock, _ = tb._bf_mock(TYPES, NID)
    _m, _ref, drv, out = tm._setup(tmp_path, mock_extra=mock, extra_req=req)
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr                         # ESL_NO_EXIT 드라이버(실패는 done.json)
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == code and msg in done["error"], done.get("error")
    assert done["mode"] == "bf_only"
    assert not any(f.endswith(".csv") for f in os.listdir(out))
    if code == "H3D_MISSING_RESULT":
        assert done["failed_step"] == "check_frames"


def test_v0242_bfd2_bf_only_value_invalid(tmp_path):
    mock, _ = tb._bf_mock(TYPES, NID)
    _m, _ref, drv, out = tm._setup(tmp_path, mock_extra=mock, extra_req="bf_on\t1\nbf_only\t2\nbf_frames\t1\n")
    assert tm._run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID" and "bf_only must be 0 or 1" in done["error"]
    assert "mode" not in done                                  # bf 전용 요청이 아님


# ------------------------------------------------------------------ V-0242-BFD-3 (v0.24.1 TCL 골든 — 공용화 전 기록)
# 정규화: CSV = 원 바이트 sha256, done.json = 시간·경로·핸들 이름(env·api·h3d·backup_dir·*_s·seconds) 을 뺀 정렬 직렬화.
GOLD_V0241 = {
    "default": {"disp.csv": "acd16d2c06160019", "done.json": "e989a1e062fb586f", "elems.csv": "caf31a79d53e8df5",
                "final.csv": "62f59ab280adc9be", "frames.csv": "a9f09a95bf01360f", "history.csv": "64d902f50911e56c",
                "model.csv": "e610e9ff32b99e35", "strain_frames.csv": "6a1ac49b3897d795"},
    "bf_on": {"bf_acc.csv": "0d30c6e7a0c00c3f", "bf_cont.csv": "8525ed4de0522fec", "disp.csv": "acd16d2c06160019",
              "done.json": "a3866114dffccab3", "elems.csv": "caf31a79d53e8df5", "final.csv": "62f59ab280adc9be",
              "frames.csv": "a9f09a95bf01360f", "history.csv": "64d902f50911e56c", "model.csv": "e610e9ff32b99e35",
              "strain_frames.csv": "6a1ac49b3897d795"},
    "bf_on_chunk": {"bf_acc.csv": "0d30c6e7a0c00c3f", "bf_cont.csv": "8525ed4de0522fec",
                    "disp.csv": "acd16d2c06160019", "done.json": "fe8c5f512dba31ff", "elems.csv": "caf31a79d53e8df5",
                    "final.csv": "62f59ab280adc9be", "frames.csv": "a9f09a95bf01360f",
                    "history.csv": "64d902f50911e56c", "model.csv": "e610e9ff32b99e35",
                    "strain_frames.csv": "6a1ac49b3897d795"},
    "dump_bf_on": {"disp.csv": "0bf7447a8dadf16c", "done.json": "d7e086fea73869d8", "elems.csv": "caf31a79d53e8df5",
                   "frames.csv": "a9f09a95bf01360f", "model.csv": "e610e9ff32b99e35",
                   "strain_raw.csv": "1a76ee381c328172"},
}
VOLATILE = {"env", "backup_dir", "h3d", "seconds", "created_at", "started_at", "finished_at", "elapsed_s", "api"}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()
                if k not in VOLATILE and not k.endswith(("_s", "_seconds", "_mb", "mtime")) and not k.startswith("mem_")}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _digest(out):
    d = {f: hashlib.sha256((out / f).read_bytes()).hexdigest()[:16] for f in sorted(os.listdir(out)) if f.endswith(".csv")}
    done = json.loads((out / "done.json").read_text())
    d["done.json"] = hashlib.sha256(json.dumps(_clean(done), sort_keys=True).encode()).hexdigest()[:16]
    return d


def _scenario(name):
    extra, _ = tb._bf_mock(TYPES, NID)
    t, stored, eq = tm._inst(eng=True)
    dump_extra = (tm._dtinfo(tm.REAL_TYPES, {"Strain": ["Lower", "Upper", "Max", "Min"]}) + "\n"
                  + tm._strain_lines(stored, eq, [10, 11, 12, 13, 14, 15]))
    return {"default": {}, "bf_on": dict(mock_extra=extra, extra_req="bf_on\t1\n"),
            "bf_on_chunk": dict(mock_extra=extra, extra_req="bf_on\t1\nchunk\t4\n"),
            "dump_bf_on": dict(mock_extra=dump_extra, extra_req="bf_on\t1\n")}[name]


@pytest.mark.parametrize("name", sorted(GOLD_V0241))
def test_v0242_bfd3_outputs_unchanged_without_bf_only(tmp_path, name):
    _m, _ref, drv, out = tm._setup(tmp_path, **_scenario(name))
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    assert _digest(out) == GOLD_V0241[name]


def test_v0242_bfd3_bf_only_zero_is_default(tmp_path):
    """bf_only 0 을 명시해도 bf_only 없는 실행과 같은 출력(바이트 동일)."""
    kw = _scenario("bf_on")
    _m, _ref, drv, out = tm._setup(tmp_path, mock_extra=kw["mock_extra"], extra_req=kw["extra_req"] + "bf_only\t0\n")
    assert tm._run(drv).returncode == 0
    assert _digest(out) == GOLD_V0241["bf_on"]
