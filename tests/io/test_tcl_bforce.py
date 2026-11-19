"""v0.24.0 경계력 ESL TCL 덤프(계약 esl_bforce.md §1·§2, V-0240-f) — 가짜 hwi(hwmock.tcl)로 tclsh 실행 → pack_bforce.

결과 유형 이름은 설정 목록(대체 이름)으로 찾고, 없는 유형은 type null(실패 아님). tclsh 없으면 건너뜀.
"""
import json
import os

import numpy as np
import pytest

import test_tcl_mock as tm
from esl.io.bforce_csv import frame_data, pack_bforce

pytestmark = pytest.mark.skipif(tm.TCLSH is None, reason="tclsh 없음")


def _bf_mock(types: dict, nid, F=tm.F, seed=11):
    """types = {표시명: (comps, scalar)} → mock_extra(dtinfo + 값) 와 값 사전."""
    rng = np.random.default_rng(seed)
    lines, vals = [], {}
    for name, (comps, scalar) in types.items():
        lines.append(f"dict set ::mock::dtinfo {{{name}}} {{comps {{{' '.join('{' + c + '}' for c in comps)}}} layers {{}}}}")
        v = rng.normal(size=(F, len(nid), len(comps)))
        vals[name] = v
        kv = []
        for f in range(F):
            for k, n in enumerate(nid):
                for c, comp in enumerate(comps):
                    kv.append(f"{tm._key(name, comp, '', f, n)} {float(v[f, k, c])!r}")
        lines.append("set ::mock::vals [dict merge $::mock::vals [dict create " + " ".join(kv) + "]]")
    return "\n".join(lines), vals


def test_v0240_f_tcl_bforce_default_names(tmp_path):
    nid = np.arange(1, 13)
    extra, vals = _bf_mock({"Contact Forces": (["X", "Y", "Z"], False), "Acceleration": (["X", "Y", "Z", "Mag"], False)},
                           nid)
    m, ref, drv, out = tm._setup(tmp_path, mock_extra=extra, extra_req="bf_on\t1\n")   # 워커는 bf_on 1 + 이름 목록을 보냄
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    done = json.loads((out / "done.json").read_text())
    assert done["ok"] is True, done.get("errorInfo")
    bfd = done["bforce"]
    assert bfd["on"] is True and bfd["frames"] == done["frames_D"]
    assert bfd["kinds"]["cont"] == {"type": "Contact Forces", "comps": ["X", "Y", "Z"], "rows": 12 * len(bfd["frames"])}
    assert bfd["kinds"]["acc"]["type"] == "Acceleration"
    for k in ("cont2", "mass", "fint"):                                   # 없는 유형 = 실패 아님
        assert bfd["kinds"][k]["type"] is None and "not in h3d" in bfd["kinds"][k]["reason"]
    assert sorted(f for f in os.listdir(out) if f.startswith("bf_")) == ["bf_acc.csv", "bf_cont.csv"]
    doc = pack_bforce(str(out), nid, str(tmp_path / "x"))
    assert doc["kinds"]["cont"]["n_missing"] == 0 and doc["kinds"]["cont2"]["type"] is None
    D = bfd["frames"]
    dat, _ = frame_data(str(tmp_path / "x"), D[-1])
    assert np.array_equal(dat["cont"], vals["Contact Forces"][D[-1]])     # %.17g 비트 보존
    assert np.array_equal(dat["acc"], vals["Acceleration"][D[-1]][:, :3])
    assert dat["cont2"] is None and dat["mass"] is None
    # 기존 산출물은 그대로(경계력 파일만 추가)
    res = tm.pack_results(out, m, tmp_path / "npz")
    assert res["frames_D"] == D


def test_v0240_f_tcl_bforce_alt_names_and_off(tmp_path):
    nid = np.arange(1, 13)
    extra, vals = _bf_mock({"KontaktKraft": (["x", "y", "z"], False), "Node Mass": (["Scalar value"], True)}, nid)
    req = ("bf_on\t1\nbf_names_cont\tFoo|kontakt_kraft\n"                          # 대소문자·밑줄 무시 일치
           "bf_names_mass\tNode Mass\n"
           "bf_vec_comps\tX|x Y|y Z|z\n")
    m, ref, drv, out = tm._setup(tmp_path, mock_extra=extra, extra_req=req)
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    k = json.loads((out / "done.json").read_text())["bforce"]["kinds"]
    assert k["cont"]["type"] == "KontaktKraft" and k["cont"]["comps"] == ["x", "y", "z"]
    assert k["mass"]["type"] == "Node Mass" and k["mass"]["comps"] == ["Scalar value"]
    doc = pack_bforce(str(out), nid, str(tmp_path / "x"))
    D = doc["frames"]
    dat, _ = frame_data(str(tmp_path / "x"), D[0])
    assert np.array_equal(dat["mass"], vals["Node Mass"][D[0], :, 0])
    # request 에 bf 키 없음(기본 bf_on 0) → done.json 에 bforce 없음·bf 파일 없음(이전 출력과 같음 — v0.7.2 TCL 골든)
    tmp2 = tmp_path / "off"
    tmp2.mkdir()
    m, ref, drv, out = tm._setup(tmp2, mock_extra=extra)
    assert tm._run(drv).returncode == 0
    assert "bforce" not in json.loads((out / "done.json").read_text())
    assert not any(f.startswith("bf_") for f in os.listdir(out))


def test_v0240_f_pack_without_bforce_key(tmp_path):
    """이전 TCL(done.json 에 bforce 없음) → 아무것도 쓰지 않음(옛 추출물 바이트 동일)."""
    (tmp_path / "done.json").write_text(json.dumps({"ok": True}))
    assert pack_bforce(str(tmp_path), np.arange(3), str(tmp_path / "x")) is None
    assert not (tmp_path / "x").exists()
