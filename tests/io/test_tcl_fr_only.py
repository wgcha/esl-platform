"""v0.25.2 TCL 채움 모드 fr_only(계약 esl_tstar_manual_jig_force.md §2.4, V-0252-3·9) — 가짜 hwi(hwmock.tcl)로 tclsh 실행.

request `fr_only 1·fr_frames "f"` → 변위 f·전 요소 변형률 f·f−1(+ bf_on 1 이면 경계력 f)만, done.json mode fr_only. 전체 추출 →
pack → frame_fill.merge 왕복이 h3d 값을 비트 단위로 보존(%.17g). fr_only 없음 = 출력 바이트 불변(v0.24.1 TCL 골든·정적 확인 —
fr_only 표식 구간을 빼면 393789a8 파일과 같은 글자). tclsh 없으면 건너뜀.
"""
import hashlib
import json
import os
import re

import numpy as np
import pytest

import test_tcl_bforce as tb
import test_tcl_bforce_only as tbo
import test_tcl_mock as tm
from esl.errors import EslError
from esl.io import bforce_ondemand as bfod
from esl.io import frame_fill as ff
from esl.io import pack_results

pytestmark = pytest.mark.skipif(tm.TCLSH is None, reason="tclsh 없음")
NID = np.arange(1, 13)
# release/v0.25.1 393789a8 의 resources/tcl/esl_h3d_extract.tcl sha256(fr_only 표식 구간을 뺀 지금 파일과 같아야 함)
TCL_V0251_SHA = "bd2c7bf64aaf502eab5d66596ea28a816dd1061f8a3c5e1eef8bf5934091f76f"
_MARK = re.compile(r"[ \t]*# >>> v0\.25\.2 fr_only\n.*?# <<< v0\.25\.2 fr_only\n", re.S)


def _full(tmp_path, **kw):
    m, ref, drv, out = tm._setup(_mk(tmp_path / "full"), **kw)
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    xd = tmp_path / "case" / "01_extract"
    pack_results(out, m, xd)
    return m, ref, xd, json.loads((out / "done.json").read_text())


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fr(tmp_path, frames, extra="", **kw):
    m, ref, drv, out = tm._setup(_mk(tmp_path / "fr"), extra_req=f"fr_only\t1\nfr_frames\t{frames}\n" + extra, **kw)
    r = tm._run(drv)
    return r, out, ref


# ------------------------------------------------------------------ 출력·왕복
def test_v0252_9_fr_only_outputs_and_merge_roundtrip(tmp_path):
    m, ref, xd, done0 = _full(tmp_path)
    D = done0["frames_D"]
    f = next(g for g in range(2, tm.F) if g not in D)
    r, out, _ref = _fr(tmp_path, str(f))
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["mode"] == "fr_only", done.get("errorInfo")
    assert sorted(os.listdir(out)) == ["disp.csv", "done.json", "progress.log", "strain_frames.csv"]
    assert done["frames"] == [f] and done["prev_frames"] == [f - 1] and done["strain_frames"] == [f - 1, f]
    assert done["n_frames"] == tm.F and done["n_nodes"] == 12 and done["n_elems"] == 6
    assert done["strain_source"] == "max_strain" and done["passes"]["FR"]["rows_disp"] == 12
    assert done["passes"]["FR"]["rows_strain"] == 12 and set(done["frame_times"]) == {str(f), str(f - 1)}
    for k in ("candidate_frames", "frames_D", "n_hot"):
        assert k not in done                                           # 순위·H·D 계산 없음
    rows = (out / "disp.csv").read_text().splitlines()
    assert rows[0] == "frame_index,node_id,ux,uy,uz" and {ln.split(",")[0] for ln in rows[1:]} == {str(f)}
    # 병합 → 끝에 덧붙음, 값 = h3d 값(비트)
    res = ff.merge(str(xd), str(out), f, job_id="T")
    assert res["added"] is True
    with np.load(xd / "disp.npz") as z:
        assert z["frame_index"].tolist() == D + [f] and np.array_equal(z["u"][-1], ref["u"][f])
    with np.load(xd / "strain_frames.npz") as z:
        assert z["frame_index"][-1] == f and np.array_equal(z["vm_hv"][-1], ref["vm"][f].astype(np.float32))
        assert z["prev_frame_index"][-1] == f - 1 and np.array_equal(z["prev_vm_hv"][-1], ref["vm"][f - 1].astype(np.float32))
        assert np.array_equal(z["epsp"][-1], ref["ep"][f].astype(np.float32))


def test_v0252_9_fr_only_frame0_and_plastic_source(tmp_path):
    r, out, ref = _fr(tmp_path, "0")
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["frames"] == [0] and done["prev_frames"] == [] and done["strain_frames"] == [0]
    r2, out2, _ = _fr(tmp_path / "p", "4", extra="strain_sources\tplastic_strain\n")
    d2 = json.loads((out2 / "done.json").read_text())
    assert r2.returncode == 0 and d2["strain_source"] == "plastic_strain" and d2["strain_type"] == "Plastic Strain"


def test_v0252_9_fr_only_bforce_same_run(tmp_path):
    mock, vals = tb._bf_mock(tbo.TYPES, NID)
    r, out, _ref = _fr(tmp_path, "5", extra="bf_on\t1\n", mock_extra=mock)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["bforce"]["on"] is True and done["bforce"]["frames"] == [5]
    assert {"bf_cont.csv", "bf_acc.csv"} <= set(os.listdir(out))
    lines = (out / "bf_cont.csv").read_text().splitlines()[1:]
    assert lines and {ln.split(",")[0] for ln in lines} == {"5"}
    assert bfod._fill_done(str(out), [5])["mode"] == "fr_only"        # 경계력 보충 병합이 같은 출력을 받음(TM-C1-1)


@pytest.mark.parametrize("req,code,msg", [
    ("fr_only\t2\n", "INPUT_INVALID", "fr_only must be 0 or 1"),
    ("fr_only\t1\nfr_frames\t\n", "INPUT_INVALID", "fr_frames is empty"),
    ("fr_only\t1\nfr_frames\t-1\n", "INPUT_INVALID", "not a frame index"),
    ("fr_only\t1\nfr_frames\t3 3\n", "INPUT_INVALID", "twice"),
    ("fr_only\t1\nfr_frames\t3\nbf_on\t1\nbf_only\t1\nbf_frames\t3\n", "INPUT_INVALID", "cannot both be 1"),
    ("fr_only\t1\nfr_frames\t99\n", "H3D_MISSING_RESULT", "not in subcase"),
])
def test_v0252_9_fr_only_validation(tmp_path, req, code, msg):
    m, ref, drv, out = tm._setup(tmp_path, extra_req=req)
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr                         # ESL_NO_EXIT 드라이버(실패는 done.json)
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == code and msg in done["error"], done.get("error")
    assert not any(f.endswith(".csv") for f in os.listdir(out))
    if req.startswith("fr_only\t1"):
        assert done["mode"] == "fr_only"
    else:
        assert "mode" not in done


def test_v0252_9_fr_only_dump_source_rejected(tmp_path):
    t, stored, eq = tm._inst(eng=True)
    extra = (tm._dtinfo(tm.REAL_TYPES, {"Strain": ["Lower", "Upper", "Max", "Min"]}) + "\n"
             + tm._strain_lines(stored, eq, [10, 11, 12, 13, 14, 15]))
    r, out, _ = _fr(tmp_path, "3", extra="strain_sources\tstrain_tensor\n", mock_extra=extra)
    done = json.loads((out / "done.json").read_text())
    assert r.returncode == 0 and done["ok"] is False and done["code"] == "INPUT_INVALID" and "dump" in done["error"]
    assert done["mode"] == "fr_only"


# ------------------------------------------------------------------ 불변
def test_v0252_9_tcl_static_unchanged_without_fr_only():
    s = open(os.path.join(tm.TCL_DIR, "esl_h3d_extract.tcl"), encoding="ascii").read()
    stripped = _MARK.sub("", s)
    assert hashlib.sha256(stripped.encode()).hexdigest() == TCL_V0251_SHA
    assert s.count("# >>> v0.25.2 fr_only") == s.count("# <<< v0.25.2 fr_only") >= 5


@pytest.mark.parametrize("name", ["default", "bf_on"])
def test_v0252_9_fr_only_zero_outputs_unchanged(tmp_path, name):
    kw = tbo._scenario(name)
    _m, _ref, drv, out = tm._setup(tmp_path, mock_extra=kw.get("mock_extra", ""),
                                   extra_req=kw.get("extra_req", "") + "fr_only\t0\n")
    assert tm._run(drv).returncode == 0
    assert tbo._digest(out) == tbo.GOLD_V0241[name]


def test_v0252_3_merge_rejects_wrong_h3d(tmp_path):
    m, ref, xd, done0 = _full(tmp_path)
    f = next(g for g in range(2, tm.F) if g not in done0["frames_D"])
    r, out, _ = _fr(tmp_path, str(f))
    d = json.loads((out / "done.json").read_text())
    d["frame_times"][str(f)] += 1e-3
    (out / "done.json").write_text(json.dumps(d))
    with pytest.raises(EslError) as ei:
        ff.merge(str(xd), str(out), f)
    assert ei.value.code == "FRAME_FILL_MISMATCH"
