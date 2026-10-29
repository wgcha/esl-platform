"""V-MR-11·V-MR-10(코어): 라이브러리 항목 → 내보내기(esl.export.from_entry).

합성 Case 1개를 코어 run --stage all(06_export 포함)로 계산 → 라이브러리 항목 저장 → export_entry 출력이
같은 run 의 stage_export 출력과 inc·fem 바이트 동일(헤더 첫 줄 생성 시각 제외), f_eq.csv 동일, u_rel.csv u_total 빈 열 + 경고.
run_items: 같은 모델 항목의 ID 연속 배정(after:), 앞 항목 실패 → EXPORT_ORDER_PREV_FAILED, 대기 시간 초과.
"""
import csv
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "library"))
import synth_lib  # noqa: E402

from esl import cli as core_cli  # noqa: E402
from esl.config import load_config  # noqa: E402
from esl.export import from_entry  # noqa: E402
from esl.library import entry as lib_entry  # noqa: E402

H3D = "F:/Hyper_work/VD_26y/50QX10A/50QX10A_v001_261019/FREE/01_Corner_Drop_1st_Scene1_Corner146_comp.h3d"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = str(tmp_path_factory.mktemp("from_entry"))
    cfg_path = synth_lib.config64(os.path.join(base, "esl64.yaml"))
    c = synth_lib.build(os.path.join(base, "case"), H3D, 1.0, 12, 8, "A", 1.0)
    out = os.path.join(base, "case", "out")
    assert core_cli.main(["run", "--config", cfg_path, "--rad", c["rad"], "--results", c["csv"], "--out", out,
                          "--stage", "all"]) == 0
    ent = lib_entry.build(out)
    edir = os.path.join(base, "lib", "entries", "e1")
    os.makedirs(os.path.dirname(edir))
    lib_entry.save(ent, edir)
    return {"base": base, "out": out, "edir": edir, "cfg": load_config(cfg_path)}


def _body(path):
    with open(path, encoding="ascii") as fh:
        lines = fh.read().split("\n")
    assert "generated" in lines[0]
    return lines[1:]


def test_export_entry_bytes_equal_stage_export(built, tmp_path):
    d = str(tmp_path / "x")
    os.makedirs(d)
    res = from_entry.export_entry(built["edir"], d, ["radioss_inc", "fem", "csv"], built["cfg"],
                                  built["cfg"]["export"]["radioss"]["id_offset"])
    ref = os.path.join(built["out"], "06_export")
    for n in ("esl_cload.inc", "esl_bcs.inc", "esl_force.fem"):
        assert _body(os.path.join(d, n)) == _body(os.path.join(ref, n)), n
    with open(os.path.join(d, "f_eq.csv"), "rb") as a, open(os.path.join(ref, "f_eq.csv"), "rb") as b:
        assert a.read() == b.read()
    rows = list(csv.reader(open(os.path.join(d, "u_rel.csv"), encoding="utf-8")))
    ref_rows = list(csv.reader(open(os.path.join(ref, "u_rel.csv"), encoding="utf-8")))
    assert rows[0] == ref_rows[0] and len(rows) == len(ref_rows)
    assert all(r[4:] == ["", "", ""] and r[:4] == q[:4] for r, q in zip(rows[1:], ref_rows[1:]))
    assert from_entry.U_TOTAL_WARNING in res["warnings"]
    sup = list(csv.reader(open(os.path.join(d, "supports_321.csv"), encoding="utf-8")))
    assert sup[0] == ["node_id", "dof"] and [len(r[1]) for r in sup[1:]] == [3, 2, 1]
    assert res["validation_used"] and {"reactions_321.csv", "validation.csv"} <= set(res["files"])
    assert "tstar_candidates.csv" not in res["files"] and "hotspots.csv" not in res["files"]
    with open(os.path.join(d, "validation.csv"), "rb") as a, open(os.path.join(ref, "validation.csv"), "rb") as b:
        assert a.read() == b.read()
    with open(os.path.join(built["out"], "run.json"), encoding="utf-8") as fh:
        ex = json.load(fh)["stages"]["export"]["summary"]
    assert res["id_range"] == ex["id_range"] and res["id_max_used"] == ex["id_max_used"]


def test_run_items_sequential_ids_and_failures(built, tmp_path):
    out = str(tmp_path / "batch")
    os.makedirs(out)
    items = [{"entry_id": "a", "dir": built["edir"], "label": "01_a", "id_offset": "auto"},
             {"entry_id": "b", "dir": built["edir"], "label": "02_b", "id_offset": "after:a", "after_label": "01_a"},
             {"entry_id": "c", "dir": str(tmp_path / "missing"), "label": "03_c", "id_offset": "auto"},
             {"entry_id": "d", "dir": built["edir"], "label": "04_d", "id_offset": "after:c", "after_label": "03_c"},
             {"entry_id": "e", "dir": built["edir"], "label": "05_e", "id_offset": "auto"}]
    seen = []
    res = from_entry.run_items(items, out, ["radioss_inc", "fem"], built["cfg"], wait_s=1, poll_s=0.05,
                               progress=seen.append)
    a, b, c, dd, e = res
    assert a["ok"] and b["ok"] and e["ok"] and not c["ok"] and not dd["ok"]
    assert b["id_range"][0] == a["id_range"][1] + 1                       # 같은 모델: 겹침 없이 연속
    assert e["id_range"] == a["id_range"]                                  # 독립 = 같은 시작
    assert c["error"]["code"] == "ENTRY_FILES_MISSING" and dd["error"]["code"] == "EXPORT_ORDER_PREV_FAILED"
    for r in res:
        with open(os.path.join(out, r["label"], "export.json"), encoding="utf-8") as fh:
            j = json.load(fh)
        assert j["ok"] == r["ok"] and j["entry_id"] == r["entry_id"]
    assert seen[-1] == 100.0
    # 앞 항목 결과가 없으면 대기 → 시간 초과
    t = from_entry.run_items([{"entry_id": "z", "dir": built["edir"], "label": "09_z", "id_offset": "after:y",
                               "after_label": "08_y"}], out, ["fem"], built["cfg"], wait_s=0.2, poll_s=0.05)
    assert t[0]["error"]["code"] == "EXPORT_ORDER_TIMEOUT"
    # 같은 라벨 재실행 → 이전 내용은 _backup 으로(삭제 없음)
    from_entry.run_items(items[:1], out, ["fem"], built["cfg"])
    assert os.path.isdir(os.path.join(out, "_backup"))
