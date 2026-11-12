"""V-BD-16 (코어분): 실 paicad 통합 — SM1(400×300 판금·비드 5·구멍 6·RBE2×6·tie 2).

별도 레인 ``ESL_TEST_PAICAD=1`` 에서만 실행(기본 레인은 가짜 paicad). 필요:
- paicad ≥ 0.15.4 (lock 의 wheel — v0.18.1) — ``ESL_PAICAD_EXE``(없으면 PATH 의 ``paicad``)
- SM1 생성물 — ``ESL_SM1_DIR``(레인 캐시, 커밋하지 않음). 없으면 ``ESL_PAICAD_SRC``(physicsai 체크아웃, 읽기 전용)의
  ``packages/paicad/tests/data/make_synthetic_shell.py OUT`` 로 생성(paicad ``test`` extra: build123d·ocp_gordon·gmsh).
워커 대신 시험이 argv(``paicad_io.command_argv``)를 ``subprocess.run(shell=False)`` 로 돌리고, 판정·읽기는 코어 함수로 한다.

v0.18.1(이슈 #63 회귀): SM1 + 구면 딤플(``SheetSpec.dimples`` — STEP 왕복 후 극점 모서리에 3D 곡선 없음) 판에서 비드 값을 바꾼
grid 셀이 ``GEOM_CAD_FAILED`` "has no 3D curve" 로 실패하지 않음(paicad 0.14.1 = B5 외 셀 전부 실패, 0.14.2+ = 전부 OK).
딤플 판은 ``ESL_PAICAD_SRC`` 의 생성기로만 만든다(``ESL_SM1_DIR`` 캐시는 SM1 원판).
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

import synth_doe as sd
from esl.doe import paicad_io as pio
from esl.doe import scenario as sc
from esl.doe import settings
from esl.doe import stages as stg
from esl.library import _util as U

pytestmark = pytest.mark.skipif(os.environ.get("ESL_TEST_PAICAD") != "1", reason="ESL_TEST_PAICAD=1 레인 전용")
CFG = settings({"bead_doe": {"enabled": True}})
FULL = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "auto"}}}
SM1_PART_ID, SM1_TITLE = 2001, "CHASSIS_REAR"
# v0.18.1: SM1 생성기(paicad tests/data)는 /MAT 카드를 쓰지 않는다(/PART mat_ID 1) — esl 기준 Case 파서는 재료가 필요하므로
# 시험용 사본(tmp)의 starter /END 앞에 /MAT/LAW1/1 을 넣는다(paicad 는 /MAT 를 읽지 않음, 원 생성물·캐시 불변).
SM1_MAT_CARD = "/MAT/LAW1/1\nSM1_STEEL\n#              RHO_I\n             7.85E-9\n#                  E                  NU\n" \
               "              210000                 0.3\n"


def _with_mat(src: str, dst) -> str:
    out = str(dst / "sm1m")
    shutil.copytree(src, out)
    p = os.path.join(out, "assem", "MODEL_0000.rad")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    if "/MAT/" not in text:
        i = text.rindex("/END")
        text = text[:i] + SM1_MAT_CARD + text[i:]
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return out


@pytest.fixture(scope="module")
def sm1(tmp_path_factory):
    d = os.environ.get("ESL_SM1_DIR")
    if d and os.path.isfile(os.path.join(d, "assem", "MODEL_0000.rad")):
        return d
    src = os.environ.get("ESL_PAICAD_SRC")
    if not src:
        pytest.skip("ESL_SM1_DIR 또는 ESL_PAICAD_SRC 필요")
    out = d or str(tmp_path_factory.mktemp("sm1"))
    gen = os.path.join(src, "packages", "paicad", "tests", "data", "make_synthetic_shell.py")
    subprocess.run([sys.executable, gen, out], check=True, shell=False, timeout=1800)
    return out


@pytest.fixture(scope="module")
def exe():
    p = os.environ.get("ESL_PAICAD_EXE") or shutil.which("paicad")
    if not p:
        pytest.skip("paicad 실행 파일 없음")
    return p


def run(exe, key, timeout=3600, **values):
    argv = pio.command_argv(key, {"paicad": exe, "threads": 2, **values})
    p = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=timeout, check=False)
    return p.returncode, p.stdout


def judge(stage, rc, out, report):
    j = pio.judge(stage, rc, out, report)
    return j


def _library(tmp, mesh):
    lib = tmp / "lib"
    return [sd.save_entry(str(lib), f"E{k}", mesh, kind, 1.0 + k, seed=k)[0]
            for k, kind in enumerate(("bend", "twist", "dent"))]


def test_version(exe):
    rc, out = run(exe, "paicad_version")
    assert rc == 0
    v = pio.check_version(pio.parse_version_json(out.strip().splitlines()[-1]), CFG)
    assert v["ready"], v


def test_sm1_same_and_step(sm1, exe, tmp_path):
    from esl.rad.parser import parse_rad
    sm1 = _with_mat(sm1, tmp_path)
    rad = os.path.join(sm1, "assem", "MODEL_0000.rad")
    rm = parse_rad(rad, SM1_TITLE)
    mesh = {"node_id": rm.node_id, "x0": rm.x0, "elem_id": rm.elem_id, "elem_type": rm.elem_type, "conn": rm.conn,
            "elem_pid": rm.elem_pid, "elem_mid": np.ones(rm.elem_id.size, np.int64), "thickness": rm.thickness,
            "E": rm.E, "nu": rm.nu}
    dirs = _library(tmp_path, mesh)
    step = os.path.join(sm1, "cad", "chassis_mid.step")
    stamp = sc.tree_stamp(os.path.join(sm1, "assem"))
    doe = {"id": "SM1", "scenario": "same", "cfg": FULL, "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": SM1_TITLE, "case_dir": os.path.join(sm1, "assem")},
           "step": {"path": step}, "paicad_version": "0.14.0"}
    out = tmp_path / "_doe" / "SM1"

    def spec(stage, **kw):
        return {"stage": stage, "out": str(out), "doe": {**doe, **kw}}
    r = stg.run_stage(spec("bd_input"), lambda s: None)
    assert r["part_id"] == SM1_PART_ID
    inp = U.read_json(str(out / "prep" / "input.json"))
    cad = str(out / inp["step"]["rel"])
    assem = os.path.join(sm1, "assem")
    rc, so_ = run(exe, "paicad_fixed_scan", assem_dir=assem, parts=pio.parts_arg([SM1_PART_ID]),
                  out_dir=str(out / "prep" / "fixed"))
    assert judge("prep", rc, so_, str(out / "prep" / "fixed" / pio.SCAN_JSON))["ok"]
    rc, so_ = run(exe, "paicad_extract", cad=cad, out_dir=str(out / "prep" / "extract0"))
    assert judge("prep", rc, so_, str(out / "prep" / "extract0" / pio.EXTRACT_JSON))["ok"]
    bm = pio.body_map_doc(pio.read_features(str(out / "prep" / "extract0")), SM1_PART_ID)
    U.write_json(str(out / "prep" / "body_map.json"), bm)
    rc, so_ = run(exe, "paicad_extract", cad=cad, out_dir=str(out / "prep" / "extract"), assem_dir=assem,
                  body_map=str(out / "prep" / "body_map.json"))
    j = judge("prep", rc, so_, str(out / "prep" / "extract" / pio.EXTRACT_JSON))
    assert j["ok"], j
    doc = pio.read_features(str(out / "prep" / "extract"))
    assert len(doc["beads"]) == 5
    # v0.18.1: paicad 비드 id 는 '<파트 제목>_B<k>'(인식 순서) — 생성기 truth 이름(B1..B5)과 중심 최근접으로 짝지음
    truth = U.read_json(os.path.join(sm1, "truth.json"))["beads"]
    bid = {t_["name"]: min(doc["beads"], key=lambda b_: sum((x - y) ** 2 for x, y in zip(b_["center"], t_["center"])))["id"]
           for t_ in truth}
    codes = {(w["code"], w["bead"]) for w in pio.extract_warnings(doc)}
    assert ("BEAD_FIXED_OVERLAP", bid["B5"]) in codes and ("BEAD_NEAR_FIXED", bid["B4"]) in codes, (codes, bid)
    rows = pio.params_table(doc)
    assert all(not r_["use_default"] for r_ in rows if r_["bead"] == bid["B5"])
    rc, so_ = run(exe, "paicad_tag", cad=cad, features=str(out / "prep" / "extract" / pio.EXTRACT_JSON), assem_dir=assem,
                  fixed_dir=str(out / "prep" / "fixed"), out_dir=str(out / "prep" / "tag"),
                  body_map=str(out / "prep" / "body_map.json"))
    assert judge("prep", rc, so_, str(out / "prep" / "tag" / pio.TAG_JSON))["ok"]
    stg.run_stage(spec("bd_loads"), lambda s: None)
    tab = U.read_json(str(out / "prep" / "params.json"))["params"]
    dname = next(r_["name"] for r_ in tab if r_["type"] == "D" and r_["use_default"])
    sp = {"method": "lhs", "n": 4, "seed": 1, "params": [{"name": dname, "lo": r_["feasible"][0], "hi": r_["feasible"][1]}
                                                        for r_ in tab if r_["name"] == dname]}
    stg.run_stage(spec("bd_matrix", rev=1, spec=sp), lambda s: None)
    dd = out / "doe" / "1"
    rc, so_ = run(exe, "paicad_grid", cad=cad, features=str(out / "prep" / "extract" / pio.EXTRACT_JSON),
                  cells=str(dd / "cells.json"), thumb=str(dd / "thumb_options.json"), fixed_dir=str(out / "prep" / "fixed"),
                  out_dir=str(dd / "grid"), timeout=7200)
    assert judge("preview", rc, so_, str(dd / "grid" / pio.GRID_MANIFEST))["ok"]
    m = U.read_json(str(dd / "matrix.json"))
    g = pio.read_grid(str(dd / "grid"), [x["id"] for x in m["designs"][1:]])
    assert stg.run_stage(spec("bd_eval", rev=1, design="d000"), lambda s: None)["status"] == "OK"
    ready = [c["id"] for c in g["cells"] if c["state"] == "READY"]
    assert ready
    did = ready[0]
    pd = out / "run" / "designs" / did / "paicad"
    rc, so_ = run(exe, "paicad_run", cad=cad, features=str(out / "prep" / "extract" / pio.EXTRACT_JSON),
                  values=str(dd / "values" / f"{did}.json"), assem_dir=assem, tag_dir=str(out / "prep" / "tag"),
                  fixed_dir=str(out / "prep" / "fixed"), update_dir=str(pd / "update"), morph_dir=str(pd / "morph"),
                  check_dir=str(pd / "check"), out_files_dir=str(pd / "out_files"),
                  body_map=str(out / "prep" / "body_map.json"))
    j = judge("design", rc, so_, str(pd / "check" / pio.RUN_JSON))
    r = stg.run_stage(spec("bd_eval", rev=1, design=did, paicad={"ok": j["ok"], "status": j["status"], "code": j["code"]}),
                      lambda s: None)
    if j["ok"]:
        assert r["status"] == "OK"
        z = U.load_npz(str(out / "run" / "designs" / did / "design.npz"))
        assert np.array_equal(z["node_id"], rm.node_id)                    # 노드 ID 불변
        fx = pio.read_fixed(str(out / "prep" / "fixed"))
        pos = {int(v): i for i, v in enumerate(rm.node_id.tolist())}
        idx = [pos[int(n)] for n in fx["node_id"] if int(n) in pos]
        assert np.allclose(z["x"][idx], rm.x0[idx])                         # 고정 노드 불변
    assert sc.tree_stamp(assem) == stamp                                     # 입력 폴더 불변
    # ③: --fixed-dir "" grid + update (고정 없음)
    g3 = out / "doe" / "1" / "grid3"
    rc, so_ = run(exe, "paicad_grid", cad=cad, features=str(out / "prep" / "extract" / pio.EXTRACT_JSON),
                  cells=str(dd / "cells.json"), thumb=str(dd / "thumb_options.json"), fixed_dir="", out_dir=str(g3),
                  timeout=7200)
    assert judge("preview", rc, so_, str(g3 / pio.GRID_MANIFEST))["ok"]
    u3 = out / "run" / "designs" / f"{did}_s3" / "update"
    rc, so_ = run(exe, "paicad_update", cad=cad, features=str(out / "prep" / "extract" / pio.EXTRACT_JSON),
                  values=str(dd / "values" / f"{did}.json"), out_dir=str(u3))
    j3 = judge("design", rc, so_, str(u3 / pio.UPDATE_JSON))
    if j3["ok"]:
        from esl.doe import mesh_gmsh as mg
        if mg.available()[0]:
            mesh3, meta3 = mg.run_isolated(str(u3 / pio.SAMPLE_BREP), str(u3.parent / "mesh"), 5.0, CFG,
                                           {"t": 1.0, "E": 2.1e5, "nu": 0.3})
            assert meta3["quad_frac"] >= 0.5 and mesh3["elem_id"].size > 0


# ---------------------------------------------------------------- v0.18.1 이슈 #63 회귀(구면 딤플 극점 = 3D 곡선 없는 degenerated edge)
DIMPLE = (150.0, 200.0, 20.0, 4.0)          # x, y, 구 반경, 깊이 — SM1 비드·구멍·고정 노드와 떨어진 자리(paicad tests/test_v0142.py 와 같음)
_GEN_DIMPLE = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from make_synthetic_shell import SheetSpec, make_all\n"
    "r = make_all(sys.argv[2], SheetSpec(dimples=(tuple(json.loads(sys.argv[3])),)))\n"
    "print(json.dumps({'step': str(r['step']), 'assem': str(r['assem'])}))\n"
)


@pytest.fixture(scope="module")
def sm1_dimple(tmp_path_factory):
    src = os.environ.get("ESL_PAICAD_SRC")
    if not src:
        pytest.skip("ESL_PAICAD_SRC 필요(딤플 판 생성기)")
    out = str(tmp_path_factory.mktemp("sm1_dimple"))
    data = os.path.join(src, "packages", "paicad", "tests", "data")
    p = subprocess.run([sys.executable, "-c", _GEN_DIMPLE, data, out, json.dumps(list(DIMPLE))], shell=False,
                       capture_output=True, text=True, timeout=1800, check=True)
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_sm1_dimple_grid_no_3d_curve_failure(sm1_dimple, exe, tmp_path):
    """#63: 딤플 판 SM1 — fixed-scan·extract(조립·body_map) 뒤 비드 값마다 셀 1개 grid. 셀 중 GEOM_CAD_FAILED 0,
    grid_health verdict ok(B5 = 고정 영역 침범 SKIPPED_FIXED 는 판정된 스킵), paicad.log 에 'has no 3D curve' 없음."""
    cad, assem = sm1_dimple["step"], sm1_dimple["assem"]
    fx, ex0, ex = tmp_path / "fixed", tmp_path / "extract0", tmp_path / "extract"
    rc, so_ = run(exe, "paicad_fixed_scan", assem_dir=assem, parts=pio.parts_arg([SM1_PART_ID]), out_dir=str(fx))
    assert judge("prep", rc, so_, str(fx / pio.SCAN_JSON))["ok"], so_[-2000:]
    rc, so_ = run(exe, "paicad_extract", cad=cad, out_dir=str(ex0))
    assert judge("prep", rc, so_, str(ex0 / pio.EXTRACT_JSON))["ok"], so_[-2000:]
    U.write_json(str(tmp_path / "body_map.json"), pio.body_map_doc(pio.read_features(str(ex0)), SM1_PART_ID))
    rc, so_ = run(exe, "paicad_extract", cad=cad, out_dir=str(ex), assem_dir=assem, body_map=str(tmp_path / "body_map.json"))
    assert judge("prep", rc, so_, str(ex / pio.EXTRACT_JSON))["ok"], so_[-2000:]
    doc = pio.read_features(str(ex))
    assert len(doc["beads"]) == 5
    cells = [{"id": f["name"].lower(), "values": {f["name"]: float(f["nominal"]) + (0.3 if f["type"] == "BEAD_DEPTH" else 1.0)}}
             for f in doc["features"]]
    assert len(cells) >= 12
    U.write_json(str(tmp_path / "cells.json"), {"schema_version": 1, "cells": cells})
    U.write_json(str(tmp_path / "thumb.json"), {"schema_version": 1, "w": 160, "h": 160})
    g = tmp_path / "grid"
    rc, so_ = run(exe, "paicad_grid", cad=cad, features=str(ex / pio.EXTRACT_JSON), cells=str(tmp_path / "cells.json"),
                  thumb=str(tmp_path / "thumb.json"), fixed_dir=str(fx), out_dir=str(g), timeout=7200)
    assert judge("preview", rc, so_, str(g / pio.GRID_MANIFEST))["ok"], so_[-2000:]
    ids = [c["id"] for c in cells]
    rows = pio.read_grid(str(g), ids)["cells"]
    bad = [(r["id"], r["state"], r["code"]) for r in rows if r["code"] == "GEOM_CAD_FAILED" or r["state"] == "SKIPPED_GEOM"]
    assert bad == [], bad                                                    # 0.14.1: B5 외 bead 셀 전부 GEOM_CAD_FAILED
    h = pio.grid_health(rows, ids, 0.5)
    assert h["verdict"] == "ok" and h["ok"] >= len(ids) - 4, h               # B5 의 D·W·U·V = SKIPPED_FIXED 만 허용
    assert all(r["state"] in ("READY", "SKIPPED_FIXED", "SKIPPED_COLLISION") for r in rows), [(r["id"], r["state"]) for r in rows]
    log = (g / "paicad.log").read_text(encoding="utf-8", errors="replace") if (g / "paicad.log").is_file() else ""
    assert "no 3D curve" not in log
