"""esl_h3d_extract.tcl(3패스, §7.2) 을 가짜 hwi(tests/io/fixtures/hwmock.tcl)로 tclsh 에서 실행 → pack_results 왕복.

실제 HyperView API 동작 검증이 아니라, TCL 문법·흐름·H·D 선택 규칙·CSV 포맷이 pack_results·Python 생성기
(write_results_csv)와 맞는지만 본다. 가짜 h3d 데이터는 실데이터 이름(Max_Strain XX YY ZZ XY vonMises,
Plastic Strain "Scalar value", layer Mid)으로 max-hold 시계열을 낸다. tclsh 가 없으면 건너뛴다.
"""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest

from esl.errors import EslError
from esl.io import max_hold, pack_results, write_results_csv
from esl.mech import strain, tstar
from esl.rad import parse_rad, write_rad

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TCL_DIR = os.path.join(ROOT, "resources", "tcl")
MOCK = os.path.join(os.path.dirname(__file__), "fixtures", "hwmock.tcl")
TCLSH = os.environ.get("ESL_TCLSH") or shutil.which("tclsh") or shutil.which("tclsh8.6")
pytestmark = pytest.mark.skipif(TCLSH is None, reason="tclsh 없음")
F = 8
NPZ = ("final.npz", "history.npz", "strain_frames.npz", "disp.npz")


def _tcl_list(items):
    return "{" + " ".join(str(i) for i in items) + "}"


def _key(*parts):
    """Tcl 정규 리스트 문자열(공백·빈 원소만 중괄호) — mock 의 [list ...] 키와 문자열이 같아야 함."""
    el = [("{" + str(p) + "}") if (str(p) == "" or " " in str(p)) else str(p) for p in parts]
    return "{" + " ".join(el) + "}"


def _series(seed=3, eng=True):
    """3×2 쿼드 6요소 max-hold 시계열: 순간 텐서 → ε_eq max-hold, Plastic = accumulate(max(0, ε_eq−y))."""
    rng = np.random.default_rng(seed)
    E = 6
    g = np.linspace(0.2, 1.0, F)[:, None, None] * rng.uniform(0.5, 1.5, (1, E, 1))
    inst = np.round(rng.normal(size=(F, E, 3)) * 1e-3 * g, 12)
    inst[0] = 0.0
    eq = strain.eps_eq(inst)
    eqh, eh = max_hold(eq, inst)
    epsp = np.maximum.accumulate(np.maximum(eq - 0.5 * eq.max(), 0.0), axis=0)
    xy = eh.copy()
    if eng:
        xy[..., 2] *= 2.0
    return eqh, xy, -(eh[..., 0] + eh[..., 1]), epsp


def _setup(tmp_path, eng=True, drop_type=None, extra_req="", mock_extra="", config=True, cli="",
           part_line="part_id\t7\n", script="esl_h3d_extract.tcl", prelude="", hot_k=2, u0=None, no_disp0=False):
    nid = np.arange(1, 13)
    xs, ys = np.meshgrid([0.0, 1, 2, 3], [0.0, 1, 2], indexing="ij")
    x0 = np.c_[xs.ravel(), ys.ravel(), 0.1 * xs.ravel() * ys.ravel()]
    n = lambda i, j: i * 3 + j + 1
    conn = np.array([[n(i, j), n(i + 1, j), n(i + 1, j + 1), n(i, j + 1)] for i in range(3) for j in range(2)])
    eid = np.array([10, 11, 12, 13, 14, 15])
    rad = write_rad(tmp_path / "m.rad", nid, x0, eid, [4] * 6, conn, 7, "plate", 1, 1.0, 1, 2e5, 0.3)
    m = parse_rad(rad, "plate")
    vm, xy, zz, ep = _series(eng=eng)
    rng = np.random.default_rng(5)
    u = rng.normal(size=(F, 12, 3))
    u[0] = 0.0 if u0 is None else u0
    xc = x0 + u[0]                                   # 프레임 0 node.coords(변형 좌표)
    t = np.arange(F) * 1e-3
    vals = []
    for f in range(F):
        for e in range(6):
            for comp, v in (("vonMises", vm[f, e]), ("XX", xy[f, e, 0]), ("YY", xy[f, e, 1]), ("ZZ", zz[f, e]),
                            ("XY", xy[f, e, 2])):
                if drop_type != "Max_Strain":
                    vals.append(f"{_key('Max_Strain', comp, 'Mid', f, eid[e])} {float(v)!r}")
            if drop_type != "Plastic Strain":
                vals.append(f"{_key('Plastic Strain', 'Scalar value', 'Mid', f, eid[e])} {float(ep[f, e])!r}")
        for k in range(12):
            if no_disp0 and f == 0:
                continue
            for c, comp in enumerate("XYZ"):
                vals.append(f"{_key('Displacement', comp, '', f, nid[k])} {float(u[f, k, c])!r}")
    data = [
        "set ::mock::sims {" + " ".join(f'"Time = {ti:.6E}"' for ti in t) + "}",
        "set ::mock::parts [dict create 7 [dict create elems {10 11 12 13 14 15} nodes {"
        + " ".join(map(str, nid)) + "}] 8 [dict create elems {99} nodes {900}]]",
        "set ::mock::names [dict create 7 chassis_rear 8 {Other Part}]",
        "set ::mock::coords [dict create " + " ".join(f"{nid[k]} {_tcl_list(xc[k].tolist())}" for k in range(12))
        + " 900 {9 9 9}]",
        "set ::mock::vals [dict create " + " ".join(vals) + "]",
        "set ::mock::econn [dict create " + " ".join(f"{eid[e]} {_tcl_list(conn[e].tolist())}" for e in range(6))
        + " 99 {900 900 900}]",
    ]
    if drop_type:
        data.append(f"dict unset ::mock::dtinfo {{{drop_type}}}")
    if mock_extra:
        data.append(mock_extra)
    (tmp_path / "data.tcl").write_text("\n".join(data) + "\n")
    req = tmp_path / "request.txt"
    req.write_text("# test\n" + part_line + f"hot_k\t{hot_k}\ntop_n\t3\n" + extra_req)
    (tmp_path / "x.h3d").write_bytes(b"")
    out = tmp_path / "csv"
    drv = tmp_path / "drv.tcl"
    drv.write_text(
        "set ::ESL_NO_EXIT 1\n" + prelude +
        f"source {{{MOCK}}}\nsource {{{tmp_path / 'data.tcl'}}}\n"
        f"set ::argv [list -input {{{tmp_path / 'x.h3d'}}} " + (f"-config {{{req}}} " if config else "")
        + f"-output {{{out}}} {cli}]\n"
        f"source {{{os.path.join(TCL_DIR, script)}}}\n"
    )
    ref = dict(vm=vm, xy=xy, zz=zz, ep=ep, u=u, t=t, x0=x0, nid=nid, eid=eid)
    return m, ref, drv, out


def _run(drv):
    return subprocess.run([TCLSH, str(drv)], capture_output=True, text=True, timeout=60)


def _load(p):
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _python_twin(tmp_path, m, ref, hot_k=2, top_n=3):
    """같은 시계열을 Python 생성기로 → pack → npz (TCL 결과와 비교 기준)."""
    d = write_results_csv(tmp_path / "py_csv", ref["t"], ref["nid"], ref["x0"], ref["u"], ref["eid"], ref["xy"],
                          vm_hv=ref["vm"], ezz=ref["zz"], epsp=ref["ep"], hot_k=hot_k, top_n=top_n)
    pack_results(d, m, tmp_path / "py_npz")
    return json.loads(open(os.path.join(d, "done.json")).read())


def _same_npz(a, b):
    for fn in NPZ:
        za, zb = _load(a / fn), _load(b / fn)
        assert set(za) == set(zb), fn
        for k in za:
            assert np.array_equal(za[k], zb[k]), (fn, k)


def test_extract_tcl_with_mock_roundtrip(tmp_path):
    m, ref, drv, out = _setup(tmp_path)
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["n_frames"] == F and done["n_elems"] == 6 and done["n_nodes"] == 12
    assert sorted(os.listdir(out)) == ["disp.csv", "done.json", "elems.csv", "final.csv", "frames.csv", "history.csv",
                                       "model.csv", "progress.log", "strain_frames.csv"]
    assert done["elems_ok"] is True and done["elems_query"] == "element.id element.connectivity" and done["n_conn"] == 6
    # H·D 규칙 = Python(esl.mech.tstar)과 동일
    H = tstar.hot_set(ref["vm"][-1], ref["ep"][-1], 2)
    assert done["n_hot"] == H.size and 2 <= H.size <= 4
    for mname, v in (("max_strain", ref["vm"]), ("plastic_strain", ref["ep"])):
        cf = tstar.candidate_frames(v[:, H], 1e-6, 3)
        assert done["candidate_frames"][mname] == [f for f, _ in cf], mname
        assert done["candidate_elems"][mname] == [int(ref["eid"][H[e]]) for _, e in cf]
    D = sorted(set(done["candidate_frames"]["max_strain"]) | set(done["candidate_frames"]["plastic_strain"]))
    assert done["frames_D"] == D and done["hot_k"] == 2 and done["top_n"] == 3
    assert {"A", "B", "C"} <= set(done["passes"]) and done["passes"]["B"]["frames"] == F
    assert done["passes"]["B"]["hot_selection"].startswith("range")
    # 패스 C: D + 직전 프레임 P = {f−1 ≥ 0} (D 에 있으면 중복 없음) 전 요소, 변위는 D 만
    P = sorted({f - 1 for f in D if f > 0})
    CF = sorted(set(D) | set(P))
    assert done["prev_frames"] == P and done["strain_frames"] == CF
    assert done["passes"]["C"]["prev_frames"] == P and done["passes"]["C"]["strain_frames"] == CF
    assert done["passes"]["C"]["rows_strain"] == 6 * len(CF) and done["passes"]["C"]["rows_disp"] == 12 * len(D)
    assert "(prev)" in r.stdout or set(P) <= set(D)
    assert "pass B frame 8/8" in r.stdout and "pass C frame" in r.stdout          # 진행률
    assert done["value_format"] == "%.17g" and done["strain_system"] == "elemental"
    assert "SetResolvedIn" in done["strain_system_call"] and "Elemental System" in done["strain_system_call"]
    assert done["backup_dir"] == ""
    # pack → npz 가 Python 생성기 경로와 비트 단위로 같음
    res = pack_results(out, m, tmp_path / "npz")
    assert res["frames_D"] == D and res["n_hot"] == H.size
    assert res["conn_check"]["checked"] and not any("CONN_CHECK" in w for w in res["warnings"])
    twin = _python_twin(tmp_path, m, ref)
    assert twin["candidate_frames"] == done["candidate_frames"]
    _same_npz(tmp_path / "npz", tmp_path / "py_npz")
    d = _load(tmp_path / "npz" / "disp.npz")
    assert np.array_equal(d["u"], ref["u"][D])          # %.17g: 질의 값이 비트 단위로 보존
    h = _load(tmp_path / "npz" / "history.npz")
    assert h["vm_hv"].shape == (F, H.size) and np.allclose(h["eps"][..., 2], ref["xy"][:, H, 2])   # exy 원값
    s = _load(tmp_path / "npz" / "strain_frames.npz")
    assert s["prev_available"].all() and s["prev_frame_index"].tolist() == [f - 1 if f > 0 else -1 for f in D]
    for i, f in enumerate(D):
        if f > 0:
            assert np.array_equal(s["prev_vm_hv"][i], ref["vm"][f - 1].astype(np.float32))


def test_extract_tcl_chunked_selection(tmp_path):
    """chunk=4: 요소 2·노드 3 청크(id 범위 선택), 결과는 청크 없는 실행과 같음."""
    m, ref, drv, out = _setup(tmp_path, extra_req="chunk\t4\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["passes"]["A"]["chunks"] == 2 and done["passes"]["C"]["node_chunks"] == 3
    assert done["chunks"]["elem"].startswith("2 chunks, range")
    pack_results(out, m, tmp_path / "npz")
    _python_twin(tmp_path, m, ref)
    _same_npz(tmp_path / "npz", tmp_path / "py_npz")


@pytest.mark.parametrize("flag,expect", [("no_range", "per_id"), ("no_id_add", "filter")])
def test_extract_tcl_id_selection_fallbacks(tmp_path, flag, expect):
    m, ref, drv, out = _setup(tmp_path, extra_req="chunk\t4\n", mock_extra=f"set ::mock::{flag} 1")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["passes"]["B"]["hot_selection"].startswith(expect)
    if flag == "no_id_add":
        assert done["chunks"]["elem"].startswith("whole") and done["passes"]["A"]["chunks"] == 1
        assert any("selection by id failed" in w for w in done["warnings"])
    pack_results(out, m, tmp_path / "npz")
    _python_twin(tmp_path, m, ref)
    _same_npz(tmp_path / "npz", tmp_path / "py_npz")


def test_extract_tcl_args_override_request(tmp_path):
    m, ref, drv, out = _setup(tmp_path, cli="-hot_k 1 -top_n 1")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["hot_k"] == 1 and done["top_n"] == 1
    assert all(len(v) <= 1 for v in done["candidate_frames"].values())
    _python_twin(tmp_path, m, ref, hot_k=1, top_n=1)
    pack_results(out, m, tmp_path / "npz")
    _same_npz(tmp_path / "npz", tmp_path / "py_npz")


@pytest.mark.parametrize("drop", ["Plastic Strain", "Max_Strain"])
def test_extract_tcl_missing_result_type_writes_failure(tmp_path, drop):
    m, ref, drv, out = _setup(tmp_path, drop_type=drop)
    assert _run(drv).returncode == 0  # ESL_NO_EXIT: 종료코드 대신 done.json 확인
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "H3D_MISSING_RESULT" and drop in done["error"]
    with pytest.raises(EslError) as ei:
        pack_results(out, m, tmp_path / "npz")
    assert ei.value.code == "H3D_MISSING_RESULT"


def test_extract_tcl_wrong_layer_name(tmp_path):
    m, ref, drv, out = _setup(tmp_path, extra_req="strain_layer\tLower\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "H3D_MISSING_RESULT" and "Mid" in done["error"]


def test_extract_tcl_without_plastic_type(tmp_path):
    """epsp_type 빈 값 → 소성 0, 경고. Plastic Strain 후보는 없음."""
    m, ref, drv, out = _setup(tmp_path, extra_req="epsp_type\t\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["candidate_frames"]["plastic_strain"] == []
    assert any("epsp_type empty" in w for w in done["warnings"])
    pack_results(out, m, tmp_path / "npz")
    assert not _load(tmp_path / "npz" / "final.npz")["epsp"].any()


def test_tcl_scripts_are_complete_ascii():
    for name in ("esl_h3d_extract.tcl", "esl_h3d_probe.tcl"):
        src = open(os.path.join(TCL_DIR, name), "rb").read()
        assert all(b < 128 for b in src), name
        chk = subprocess.run([TCLSH], input=f"puts [info complete {{{src.decode()}}}]\n",
                             capture_output=True, text=True, timeout=30)
        assert chk.stdout.strip() == "1", (name, chk.stderr)


def test_tcl_common_block_identical():
    """두 TCL 은 각자 단독 실행되도록 공통 블록(진단·세션 열기·파트 이름)을 복사해 둔다 — 내용이 같아야 함."""
    blocks = []
    for name in ("esl_h3d_extract.tcl", "esl_h3d_probe.tcl"):
        src = open(os.path.join(TCL_DIR, name), encoding="ascii").read()
        a, b = src.index("# Common block"), src.index("# end of common block")
        blocks.append(src[a:b])
    assert blocks[0] == blocks[1]


def test_probe_tcl_with_mock(tmp_path):
    m, ref, drv, out = _setup(tmp_path)
    txt = drv.read_text().replace("esl_h3d_extract.tcl", "esl_h3d_probe.tcl")
    drv.write_text(txt)
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    probe = json.loads((out / "probe.json").read_text())
    assert probe["ok"] is True
    sc = probe["subcases"][0]
    assert sc["n_simulations"] == F
    dts = {d["name"]: d for d in sc["data_types"]}
    assert dts["Max_Strain"]["layers"] == ["Mid"] and dts["Plastic Strain"]["components"] == ["Scalar value"]
    assert "XY" in dts["Max_Strain"]["components"] and "vonMises" in dts["Max_Strain"]["components"]
    sel = {s["string"]: s["size"] for s in probe["selection"]["element"]}
    assert sel["component 7"] == 6 and sel["part 7"] == -1


def test_extract_tcl_backs_up_previous_outputs(tmp_path):
    m, ref, drv, out = _setup(tmp_path)
    assert _run(drv).returncode == 0
    names = ("done.json", "frames.csv", "model.csv", "final.csv", "history.csv", "strain_frames.csv", "disp.csv")
    first = {n: (out / n).read_bytes() for n in names}
    (out / "notes.txt").write_text("user file")
    (out / "extra.csv").write_text("old,csv\n")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    bdirs = list((out / "_backup").iterdir())
    assert len(bdirs) == 1
    b = bdirs[0]
    for n, data in first.items():
        assert (b / n).read_bytes() == data          # 이전 산출물은 삭제 없이 이동
    assert (b / "extra.csv").read_text() == "old,csv\n"
    assert not (out / "extra.csv").exists()
    assert (out / "notes.txt").read_text() == "user file"   # csv/json 외 파일은 그대로
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["backup_dir"].endswith(b.name)
    assert any("moved to" in w for w in done["warnings"])
    pack_results(out, m, tmp_path / "npz")
    # 세 번째 실행: 같은 초에 실행돼도 다른 백업 폴더
    assert _run(drv).returncode == 0
    assert len(list((out / "_backup").iterdir())) == 2


def test_extract_tcl_system_call_unavailable_warns(tmp_path):
    m, ref, drv, out = _setup(tmp_path, mock_extra="set ::mock::no_system 1")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["strain_system_call"] == ""
    ws = [w for w in done["warnings"] if "result system" in w]
    assert len(ws) == 1                              # 경고는 한 번만
    res = pack_results(out, m, tmp_path / "npz")
    assert any("result system" in w for w in res["warnings"])


def test_extract_tcl_strain_system_none_and_invalid(tmp_path):
    m, ref, drv, out = _setup(tmp_path, extra_req="strain_system\tnone\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["strain_system"] == "none" and done["strain_system_call"] == ""
    (tmp_path / "b").mkdir()
    m, ref, drv, out = _setup(tmp_path / "b", extra_req="strain_system\tmaterial\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID"


def test_extract_tcl_invalid_numbers(tmp_path):
    for i, bad in enumerate(("hot_k\t0\n", "reach_rtol\t1.5\n", "chunk\tx\n", "strain_comps\tXX YY XY\n")):
        (tmp_path / str(i)).mkdir()
        m, ref, drv, out = _setup(tmp_path / str(i), extra_req=bad)
        assert _run(drv).returncode == 0
        done = json.loads((out / "done.json").read_text())
        assert done["ok"] is False and done["code"] == "INPUT_INVALID", bad


# ---------------- 진단(단계 추적·오류 기록)·대체 경로·파트 이름

def test_probe_records_failed_step_and_errorinfo(tmp_path):
    """SetClientType 의 모든 대체 값이 HyperView 식 숫자 오류 "2051" 로 실패 → probe.json 에 단계·errorInfo."""
    m, ref, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    mock_extra="set ::mock::fail_at {win_SetClientType hwc_client}")
    r = _run(drv)
    assert r.returncode == 0
    p = json.loads((out / "probe.json").read_text())
    assert p["ok"] is False and p["failed_step"] == "SetClientType"
    assert "2051" in p["error"] and "2051" in p["errorInfo"] and "SetClientType" in p["errorInfo"]
    assert "GetSessionHandle" in p["steps_done"] and any(s.startswith("GetWindowHandle") for s in p["steps_done"])
    assert "GetError: mock: win_SetClientType failed" in p["api"]["SetClientType"]
    assert p["env"]["tcl_version"] and p["env"]["input_ext"] == ".h3d" and p["env"]["input_size"] == "0"
    assert "errorCode" in p and "SetClientType/Animation" in p["traces"]
    assert "failed at step 'SetClientType'" in r.stderr


def test_probe_addmodel_falls_back_to_hwc_and_lists_components(tmp_path):
    m, ref, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    mock_extra="set ::mock::fail_at {post_AddModel}")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    p = json.loads((out / "probe.json").read_text())
    assert p["ok"] is True, p.get("errorInfo")
    assert p["api"]["AddModel"].startswith("ok: hwc_modelandresult")
    assert "2051" in p["api"]["AddModel.failed"]
    assert p["api"]["SetClientType"].startswith("ok: Animation")
    comps = {c["name"]: c for c in p["components"]}
    assert comps["chassis_rear"]["id"] == 7 and comps["chassis_rear"]["n_elems"] == 6
    assert comps["Other Part"]["n_elems"] == 1
    assert p["selection"] is None and p["part_id"] is None
    assert p["subcases"][0]["n_simulations"] == F


def test_probe_part_title_argument_and_handle_fallback(tmp_path):
    m, ref, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    cli="-part {Chassis Rear}", mock_extra="set ::mock::no_comp_query 1")
    assert _run(drv).returncode == 0
    p = json.loads((out / "probe.json").read_text())
    assert p["ok"] is True and p["part_id"] == 7
    assert p["components_source"].startswith("handles")
    sel = {s["string"]: s["size"] for s in p["selection"]["element"]}
    assert sel["component 7"] == 6


def test_probe_unwritable_output_uses_fallback(tmp_path):
    fb = tmp_path / "fb"
    m, ref, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    prelude=f"set ::ESL_FALLBACK_DIR {{{fb}}}\n")
    out.write_text("not a directory")            # 출력 폴더 생성 실패
    r = _run(drv)
    p = json.loads((fb / "esl_probe_fallback.json").read_text())
    assert p["ok"] is False and p["failed_step"] == "mkdir_output"
    assert '"failed_step":"mkdir_output"' in r.stderr


def test_extract_records_failed_step_on_2051(tmp_path):
    m, ref, drv, out = _setup(tmp_path, mock_extra="set ::mock::fail_at {post_GetModelHandle}")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "TOOL_LOG_ERROR"
    assert done["failed_step"] == "GetModelHandle" and done["error"] == "2051"
    assert "GetModelHandle" in done["errorInfo"] and "AddModel[AddModel]" in done["steps_done"]
    with pytest.raises(EslError) as ei:
        pack_results(out, m, tmp_path / "npz")
    assert ei.value.code == "TOOL_LOG_ERROR"


def test_extract_part_title_without_config(tmp_path):
    m, ref, drv, out = _setup(tmp_path, eng=False, config=False, cli="-part CHASSIS_rear")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["part_id"] == 7 and done["part_title"] == "chassis_rear" and done["n_frames"] == F
    assert done["strain_system"] == "elemental" and done["subcase"] == "1" and done["hot_k"] == 200
    res = pack_results(out, m, tmp_path / "npz")
    assert res["n_frames"] == F and res["n_hot"] == 6


def test_extract_part_priority_and_title_in_request(tmp_path):
    # -part 인자 > request.txt part_id
    m, ref, drv, out = _setup(tmp_path, cli="-part 7", part_line="part_id\t8\n")
    assert _run(drv).returncode == 0
    assert json.loads((out / "done.json").read_text())["part_id"] == 7
    (tmp_path / "b").mkdir()
    m, ref, drv, out = _setup(tmp_path / "b", part_line="part_title\tchassis rear\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["part_id"] == 7


def test_extract_without_part_lists_components(tmp_path):
    m, ref, drv, out = _setup(tmp_path, config=False)
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID" and "-part" in done["error"]
    assert {c["name"] for c in done["components"]} == {"chassis_rear", "Other Part"}
    (tmp_path / "b").mkdir()
    m, ref, drv, out = _setup(tmp_path / "b", config=False, cli="-part no_such_part")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID" and "not found" in done["error"]
    assert len(done["components"]) == 2


# ---------------- 결과 로드 순서(HyperWorks 2026.1 실기: AddModel 만으로는 "No results loaded")

def _mock_only(tmp_path, body):
    drv = tmp_path / "m.tcl"
    drv.write_text(f"source {{{MOCK}}}\n" + body)
    return subprocess.run([TCLSH, str(drv)], capture_output=True, text=True, timeout=30)


def test_mock_requires_setresult_before_result_ctrl(tmp_path):
    """mock 자체가 실기처럼 SetResult 전 GetResultCtrlHandle 을 2051 로 거부하는지."""
    (tmp_path / "x.h3d").write_bytes(b"")
    r = _mock_only(tmp_path, f"""
hwi GetSessionHandle s
s GetProjectHandle p
p GetPageHandle pg 1
pg GetWindowHandle w 1
w GetClientHandle c
c AddModel x
c GetModelHandle m 1
puts [catch {{m GetResultCtrlHandle r}} e]|$e|[s GetError]
m SetResult {{{tmp_path / 'x.h3d'}}}
puts [catch {{m GetResultCtrlHandle r}} e]
""")
    lines = r.stdout.strip().splitlines()
    assert lines[0] == "1|2051|ERROR:No results loaded.  (poIModel::GetResultCtrlHandle)", r.stderr
    assert lines[1] == "0"


@pytest.mark.parametrize("script", ["esl_h3d_probe.tcl", "esl_h3d_extract.tcl"])
def test_setresult_called_before_result_ctrl(tmp_path, script):
    m, ref, drv, out = _setup(tmp_path, script=script)
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    j = json.loads((out / ("probe.json" if "probe" in script else "done.json")).read_text())
    assert j["ok"] is True, j.get("errorInfo")
    sd = j["steps_done"]
    i_model = sd.index("GetModelHandle")
    i_set = sd.index("SetResult[SetResult]")
    i_res = sd.index("GetResultCtrlHandle")
    assert i_model < i_set < i_res
    assert sd.index("Draw") < i_res
    assert "SetResult_retry" not in j["api"]


@pytest.mark.parametrize("script", ["esl_h3d_probe.tcl", "esl_h3d_extract.tcl"])
def test_setresult_failure_is_reported(tmp_path, script):
    m, ref, drv, out = _setup(tmp_path, script=script,
                                    mock_extra="set ::mock::fail_at {model_SetResult}")
    assert _run(drv).returncode == 0
    j = json.loads((out / ("probe.json" if "probe" in script else "done.json")).read_text())
    assert j["ok"] is False and j["failed_step"] == "GetResultCtrlHandle"
    assert "2051" in j["error"] and "SetResult failed" in j["error"]
    assert "GetError: mock: model_SetResult failed" in j["api"]["SetResult"]
    assert "No results loaded" in j["api"]["GetResultCtrlHandle"]
    assert any(w.startswith("SetResult failed") for w in j["warnings"])


# ---------------- Tcl 8.5 호환(실기 HyperWorks 2026.1 의 tcl_patchLevel = 8.5.9)

_TCL86_ONLY = [
    r"\blmap\b", r"\btry\b\s*\{", r"\bthrow\b", r"\bstring\s+cat\b", r"\bfile\s+tempfile\b",
    r"\bzlib\b", r"\bcoroutine\b", r"\byield\b", r"\btailcall\b", r"\binfo\s+object\b",
    r"\binfo\s+class\b", r"\boo::", r"-stride\b", r"\bdict\s+map\b", r"\bchan\s+pipe\b",
    r"\bchan\s+(push|pop)\b", r"\bbinary\s+(en|de)code\b", r"\blsearch\b[^\n]*-bisect\b",
    r"\binfo\s+errorstack\b", r"-errorstack\b", r"\bstring\s+is\s+entier\b", r"\blpop\b",
    r"\bledit\b", r"\blseq\b", r"\blremove\b", r"\bstring\s+insert\b", r"\bfile\s+home\b",
    r"\bnextto\b", r"\btimerate\b", r"\bself\b", r"\bmy\s",
]


def test_tcl_sources_avoid_tcl86_only_features():
    import re
    for path in (os.path.join(TCL_DIR, "esl_h3d_extract.tcl"), os.path.join(TCL_DIR, "esl_h3d_probe.tcl"), MOCK):
        for no, line in enumerate(open(path, encoding="ascii"), 1):
            code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
            for pat in _TCL86_ONLY:
                assert not re.search(pat, code), f"{os.path.basename(path)}:{no}: Tcl 8.6 전용 '{pat}': {line.strip()}"


TCLSH85 = os.environ.get("ESL_TCLSH85") or shutil.which("tclsh8.5")


@pytest.mark.skipif(TCLSH85 is None, reason="tclsh8.5 없음 (ESL_TCLSH85 로 지정 가능)")
@pytest.mark.parametrize("script", ["esl_h3d_probe.tcl", "esl_h3d_extract.tcl"])
def test_tcl_scripts_run_on_tcl85(tmp_path, script):
    m, ref, drv, out = _setup(tmp_path, script=script)
    r = subprocess.run([TCLSH85, str(drv)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    j = json.loads((out / ("probe.json" if "probe" in script else "done.json")).read_text())
    assert j["ok"] is True, j.get("errorInfo")
    assert j["env"]["tcl_version"] == "8.5"
    if "extract" in script:
        assert pack_results(out, m, tmp_path / "npz")["n_frames"] == F


def test_extract_model_csv_initial_coords_from_frame0_disp(tmp_path):
    """프레임 0 node.coords 가 변형 좌표(강체 이동 + 작은 변형): model.csv x0 = coords − 프레임 0 변위 → pack 통과."""
    rng = np.random.default_rng(11)
    u0 = np.array([0.0, 0.0, -0.386]) + rng.normal(size=(12, 3)) * 1e-3
    m, ref, drv, out = _setup(tmp_path, u0=u0, extra_req="chunk\t5\n")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["model_coords"] == "coords_minus_disp_frame0" and done["frame0_time"] == 0.0
    assert done["frame0_disp_ok"] is True and abs(done["frame0_disp_max"] - np.linalg.norm(u0, axis=1).max()) < 1e-12
    lines = (out / "model.csv").read_text().splitlines()
    assert lines[0] == "node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz" and len(lines) == 13
    a = np.loadtxt(lines[1:], delimiter=",")
    o = np.argsort(a[:, 0])
    a = a[o]
    assert np.allclose(a[:, 1:4], ref["x0"], atol=1e-12) and np.array_equal(a[:, 7:10], u0)
    assert np.allclose(a[:, 4:7], ref["x0"] + u0, atol=0)
    assert "model.csv done: 12 nodes" in (out / "progress.log").read_text()
    info = pack_results(out, m, tmp_path / "npz")
    assert info["coord_deviation"] is None


def test_extract_model_csv_without_frame0_disp_warns(tmp_path):
    m, ref, drv, out = _setup(tmp_path, no_disp0=True)
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["frame0_disp_ok"] is False
    assert any("frame 0 Displacement not available" in w for w in done["warnings"])
    assert pack_results(out, m, tmp_path / "npz")["coord_deviation"] is None


def test_extract_tcl_model_csv_static():
    src = open(os.path.join(TCL_DIR, "esl_h3d_extract.tcl"), encoding="ascii").read()
    assert '"node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz"' in src
    assert '"node.id node.coords"' in src and 'model.csv frame 0 chunk' in src
    assert "frame0_time" in src and "coords_minus_disp_frame0" in src


def test_extract_tcl_elems_csv_connectivity(tmp_path):
    """elems.csv: 요소-노드 연결(쿼리 이름 후보 순서 시도, 청크), 삼각형 n4=0, progress.log 마커."""
    m, ref, drv, out = _setup(tmp_path, extra_req="chunk\t4\n",
                              mock_extra="set ::mock::conn_field nodes\n"
                                         "dict set ::mock::econn 15 {3 6 9}\n"
                                         "dict set ::mock::econn 12 {8,5,4,7}")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["elems_ok"] is True and done["elems_query"] == "element.id element.nodes" and done["n_conn"] == 6
    lines = (out / "elems.csv").read_text().splitlines()
    assert lines[0] == "elem_id,n1,n2,n3,n4" and len(lines) == 7
    rows = {int(l.split(",")[0]): l for l in lines[1:]}
    assert rows[15] == "15,3,6,9,0" and rows[12] == "12,8,5,4,7"     # 쉼표 형식·회전(같은 요소)
    plog = (out / "progress.log").read_text()
    assert "elems.csv: element connectivity" in plog and "elems.csv done: 6 elements" in plog
    # 요소 15 를 삼각형으로 바꿨으므로 rad(쿼드)와 연결이 다름 → pack ID_MISMATCH
    with pytest.raises(EslError) as ei:
        pack_results(out, m, tmp_path / "npz")
    assert ei.value.code == "ID_MISMATCH" and "요소 1/6개" in ei.value.message and "15: rad" in ei.value.message


def test_extract_tcl_elems_unavailable_warns(tmp_path):
    m, ref, drv, out = _setup(tmp_path, mock_extra="set ::mock::conn_field no_such_field")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["elems_ok"] is False and done["elems_query"] == "" and not (out / "elems.csv").exists()
    w = [x for x in done["warnings"] if x.startswith("elems.csv: element connectivity not available")]
    assert len(w) == 1 and "element.connectivity" in w[0] and "element.node_ids" in w[0]
    assert "elems.csv skipped" in (out / "progress.log").read_text()
    info = pack_results(out, m, tmp_path / "npz")
    assert any(x.startswith("CONN_CHECK_SKIPPED") and "elems_ok=false" in x for x in info["warnings"])


def test_extract_tcl_elems_csv_static():
    src = open(os.path.join(TCL_DIR, "esl_h3d_extract.tcl"), encoding="ascii").read()
    assert '"elem_id,n1,n2,n3,n4"' in src and '"element.id element.connectivity"' in src
    assert "elems_ok" in src and "elems.csv done:" in src and "elems.csv skipped" in src
