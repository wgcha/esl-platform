"""esl_h3d_extract.tcl 을 가짜 hwi(tests/io/fixtures/hwmock.tcl)로 tclsh 에서 실행 → pack_results 왕복.

실제 HyperView API 동작 검증이 아니라, TCL 문법·흐름·CSV 포맷이 pack_results 와 맞는지만 본다.
tclsh 가 없으면 건너뛴다.
"""
import json
import os
import shutil
import subprocess

import numpy as np
import pytest

from esl.errors import EslError
from esl.io import pack_results
from esl.rad import parse_rad, write_rad

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TCL_DIR = os.path.join(ROOT, "resources", "tcl")
MOCK = os.path.join(os.path.dirname(__file__), "fixtures", "hwmock.tcl")
TCLSH = shutil.which("tclsh") or shutil.which("tclsh8.6")
pytestmark = pytest.mark.skipif(TCLSH is None, reason="tclsh 없음")


def _tcl_list(items):
    return "{" + " ".join(str(i) for i in items) + "}"


def _setup(tmp_path, eng=True, drop_layer=None, extra_req="", mock_extra="", config=True, cli="",
           part_line="part_id\t7\n", script="esl_h3d_extract.tcl", prelude=""):
    nid = np.array([1, 2, 3, 4, 5, 6])
    x0 = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0.25]], float)
    eid = np.array([10, 11])
    conn = np.array([[1, 2, 5, 4], [2, 3, 6, 5]])
    rad = write_rad(tmp_path / "m.rad", nid, x0, eid, [4, 4], conn, 7, "plate", 1, 1.0, 1, 2e5, 0.3)
    m = parse_rad(rad, "plate")
    F = 5
    rng = np.random.default_rng(3)
    eps = np.round(rng.normal(size=(F, 2, 2, 3)) * 1e-3, 9)
    u = np.round(rng.normal(size=(F, 6, 3)), 9)
    u[0] = 0.0
    t = np.arange(F) * 1e-3
    vals = []
    for f in range(F):
        for li, lay in enumerate(("Lower", "Upper")):
            if lay == drop_layer:
                continue
            for e in range(2):
                for c, comp in enumerate(("XX", "YY", "XY")):
                    v = eps[f, e, li, c] * (2 if (eng and comp == "XY") else 1)
                    vals.append(f"{{Strain {comp} {lay} {f} {eid[e]}}} {float(v)!r}")
        for n in range(6):
            for c, comp in enumerate("XYZ"):
                vals.append(f"{{Displacement {comp} {{}} {f} {nid[n]}}} {float(u[f, n, c])!r}")
    # 다른 파트(8) 요소·노드도 h3d 에 있음
    data = [
        "set ::mock::sims {" + " ".join(f'"Time = {ti:.6E}"' for ti in t) + "}",
        "set ::mock::parts [dict create 7 [dict create elems {10 11} nodes {1 2 3 4 5 6}] "
        "8 [dict create elems {99} nodes {900}]]",
        "set ::mock::names [dict create 7 chassis_rear 8 {Other Part}]",
        "set ::mock::coords [dict create " + " ".join(f"{nid[n]} {_tcl_list(x0[n].tolist())}" for n in range(6))
        + " 900 {9 9 9}]",
        "set ::mock::vals [dict create " + " ".join(vals) + "]",
    ]
    if mock_extra:
        data.append(mock_extra)
    (tmp_path / "data.tcl").write_text("\n".join(data) + "\n")
    req = tmp_path / "request.txt"
    req.write_text("# test\n" + part_line + "frame_stride\t2\nshear_is_engineering\t" + ("1" if eng else "0") + "\n" + extra_req)
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
    return m, t, eps, u, drv, out


def _run(drv):
    return subprocess.run([TCLSH, str(drv)], capture_output=True, text=True, timeout=60)


def test_extract_tcl_with_mock_roundtrip(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path)
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["n_frames"] == 3 and done["n_elems"] == 2 and done["n_nodes"] == 6
    res = pack_results(out, m, tmp_path / "npz")
    assert res["n_frames"] == 3
    with np.load(tmp_path / "npz" / "strain_tensor.npz", allow_pickle=False) as z:
        assert z["frame_index"].tolist() == [0, 2, 4]
        assert np.allclose(z["time"], t[::2])
        assert np.allclose(z["eps"], eps[::2].astype(np.float32))   # XY 공학전단 → /2
    with np.load(tmp_path / "npz" / "disp.npz", allow_pickle=False) as z:
        assert np.allclose(z["u"], u[::2])
        assert np.array_equal(z["u"], u[::2])   # %.17g: 질의 값이 비트 단위로 보존
    assert done["disp_value_format"] == "%.17g"
    assert done["strain_system"] == "elemental"
    assert "SetResolvedIn" in done["strain_system_call"] and "Elemental System" in done["strain_system_call"]
    assert done["backup_dir"] == ""
    assert not (out / "_backup").exists()


def test_extract_tcl_missing_layer_writes_failure(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, drop_layer="Upper")
    r = _run(drv)
    assert r.returncode == 0  # ESL_NO_EXIT: 종료코드 대신 done.json 확인
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "H3D_MISSING_RESULT"
    with pytest.raises(EslError) as ei:
        pack_results(out, m, tmp_path / "npz")
    assert ei.value.code == "H3D_MISSING_RESULT"


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
    m, t, eps, u, drv, out = _setup(tmp_path)
    txt = drv.read_text().replace("esl_h3d_extract.tcl", "esl_h3d_probe.tcl")
    drv.write_text(txt)
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    probe = json.loads((out / "probe.json").read_text())
    assert probe["ok"] is True
    sc = probe["subcases"][0]
    assert sc["n_simulations"] == 5
    dts = {d["name"]: d for d in sc["data_types"]}
    assert dts["Strain"]["layers"] == ["Lower", "Upper", "Max", "Min"]
    assert "XY" in dts["Strain"]["components"]
    sel = {s["string"]: s["size"] for s in probe["selection"]["element"]}
    assert sel["component 7"] == 2 and sel["part 7"] == -1


def test_extract_tcl_backs_up_previous_outputs(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path)
    assert _run(drv).returncode == 0
    first = {n: (out / n).read_bytes() for n in ("done.json", "frames.csv", "model.csv", "strain.csv", "disp.csv")}
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
    m, t, eps, u, drv, out = _setup(tmp_path, mock_extra="set ::mock::no_system 1")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["strain_system_call"] == ""
    ws = [w for w in done["warnings"] if "result system" in w]
    assert len(ws) == 1                              # 경고는 한 번만
    res = pack_results(out, m, tmp_path / "npz")
    assert any("result system" in w for w in res["warnings"])


def test_extract_tcl_strain_system_none_and_invalid(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, extra_req="strain_system\tnone\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["strain_system"] == "none" and done["strain_system_call"] == ""
    (tmp_path / "b").mkdir()
    m, t, eps, u, drv, out = _setup(tmp_path / "b", extra_req="strain_system\tmaterial\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID"


# ---------------- 진단(단계 추적·오류 기록)·대체 경로·파트 이름

def test_probe_records_failed_step_and_errorinfo(tmp_path):
    """SetClientType 의 모든 대체 값이 HyperView 식 숫자 오류 "2051" 로 실패 → probe.json 에 단계·errorInfo."""
    m, t, eps, u, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
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
    m, t, eps, u, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    mock_extra="set ::mock::fail_at {post_AddModel}")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    p = json.loads((out / "probe.json").read_text())
    assert p["ok"] is True, p.get("errorInfo")
    assert p["api"]["AddModel"].startswith("ok: hwc_modelandresult")
    assert "2051" in p["api"]["AddModel.failed"]
    assert p["api"]["SetClientType"].startswith("ok: Animation")
    comps = {c["name"]: c for c in p["components"]}
    assert comps["chassis_rear"]["id"] == 7 and comps["chassis_rear"]["n_elems"] == 2
    assert comps["Other Part"]["n_elems"] == 1
    assert p["selection"] is None and p["part_id"] is None
    assert p["subcases"][0]["n_simulations"] == 5


def test_probe_part_title_argument_and_handle_fallback(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    cli="-part {Chassis Rear}", mock_extra="set ::mock::no_comp_query 1")
    assert _run(drv).returncode == 0
    p = json.loads((out / "probe.json").read_text())
    assert p["ok"] is True and p["part_id"] == 7
    assert p["components_source"].startswith("handles")
    sel = {s["string"]: s["size"] for s in p["selection"]["element"]}
    assert sel["component 7"] == 2


def test_probe_unwritable_output_uses_fallback(tmp_path):
    fb = tmp_path / "fb"
    m, t, eps, u, drv, out = _setup(tmp_path, script="esl_h3d_probe.tcl", config=False,
                                    prelude=f"set ::ESL_FALLBACK_DIR {{{fb}}}\n")
    out.write_text("not a directory")            # 출력 폴더 생성 실패
    r = _run(drv)
    p = json.loads((fb / "esl_probe_fallback.json").read_text())
    assert p["ok"] is False and p["failed_step"] == "mkdir_output"
    assert '"failed_step":"mkdir_output"' in r.stderr


def test_extract_records_failed_step_on_2051(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, mock_extra="set ::mock::fail_at {post_GetModelHandle}")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "TOOL_LOG_ERROR"
    assert done["failed_step"] == "GetModelHandle" and done["error"] == "2051"
    assert "GetModelHandle" in done["errorInfo"] and "AddModel[AddModel]" in done["steps_done"]
    with pytest.raises(EslError) as ei:
        pack_results(out, m, tmp_path / "npz")
    assert ei.value.code == "TOOL_LOG_ERROR"


def test_extract_part_title_without_config(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, eng=False, config=False, cli="-part CHASSIS_rear")
    r = _run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    assert done["part_id"] == 7 and done["part_title"] == "chassis_rear" and done["n_frames"] == 5
    assert done["strain_system"] == "elemental" and done["subcase"] == "1"
    res = pack_results(out, m, tmp_path / "npz")
    assert res["n_frames"] == 5


def test_extract_part_priority_and_title_in_request(tmp_path):
    # -part 인자 > request.txt part_id
    m, t, eps, u, drv, out = _setup(tmp_path, cli="-part 7", part_line="part_id\t8\n")
    assert _run(drv).returncode == 0
    assert json.loads((out / "done.json").read_text())["part_id"] == 7
    (tmp_path / "b").mkdir()
    m, t, eps, u, drv, out = _setup(tmp_path / "b", part_line="part_title\tchassis rear\n")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True and done["part_id"] == 7


def test_extract_without_part_lists_components(tmp_path):
    m, t, eps, u, drv, out = _setup(tmp_path, config=False)
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID" and "-part" in done["error"]
    assert {c["name"] for c in done["components"]} == {"chassis_rear", "Other Part"}
    (tmp_path / "b").mkdir()
    m, t, eps, u, drv, out = _setup(tmp_path / "b", config=False, cli="-part no_such_part")
    assert _run(drv).returncode == 0
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is False and done["code"] == "INPUT_INVALID" and "not found" in done["error"]
    assert len(done["components"]) == 2
