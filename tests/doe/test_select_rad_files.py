"""BS-D-14·§8.3: select 산출물 rad 사본 대상(``stages._sel_rad_files``)·쓰기(``stages._sel_best``).

- 파일 집합 = ``prep/assem_full.json`` 매니페스트(있으면) | 기준 rad include 트리(``include_path_map`` 반영) — Case 폴더를
  os.walk 로 훑지 않으므로 Case 폴더 안 관계없는 .rad 사본(대상 노드를 가져도)은 복사되지 않는다.
- Case 폴더 밖 include(대상 노드 있음)도 원본을 읽어 ``include/_ext/…`` 로 복사.
- 쓰기는 작업 폴더(best/<did>/) 사본에만 — 원본(Case·밖 include)은 바이트·mtime 그대로.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pytest

from esl.doe import stages as S
from esl.errors import EslError

NIDS = (1, 2, 3, 4)


def _node_block(ids, z=0.0) -> str:
    rows = "".join(f"{i:10d}{float(i):20.13E}{0.0:20.13E}{z:20.13E}\n" for i in ids)
    return "/NODE\n" + rows


def _tree(root) -> dict:
    out = {}
    for r, _d, files in os.walk(root):
        for f in files:
            p = os.path.join(r, f)
            st = os.stat(p)
            out[os.path.relpath(p, root)] = (hashlib.sha256(open(p, "rb").read()).hexdigest(), st.st_mtime_ns)
    return out


@pytest.fixture()
def world(tmp_path):
    inp = tmp_path / "inputs"
    case = inp / "case"
    (case / "inc").mkdir(parents=True)
    (inp / "shared").mkdir()
    (inp / "mapped").mkdir()
    rad = case / "m_0000.rad"
    rad.write_text("#RADIOSS STARTER\n/BEGIN\nm\n#include inc/part.inc\n#include ../shared/far.inc\n"
                   "#include D:/old/proj/mapped.inc\n/END\n", encoding="latin-1")
    (case / "inc" / "part.inc").write_text(_node_block(NIDS[:2]) + "/SHELL/10\n", encoding="latin-1")
    (inp / "shared" / "far.inc").write_text("# outside case\n" + _node_block(NIDS[2:3]), encoding="latin-1")
    (inp / "mapped" / "mapped.inc").write_text(_node_block(NIDS[3:]), encoding="latin-1")
    (inp / "shared" / "other.inc").write_text(_node_block(NIDS), encoding="latin-1")          # 참조 안 됨
    (case / "old_copy.rad").write_text(_node_block(NIDS), encoding="latin-1")               # 관계없는 사본
    (case / "inc" / "backup_part.inc").write_text(_node_block(NIDS[:2]), encoding="latin-1")  # 관계없는 사본
    out = tmp_path / "out"
    out.mkdir()
    doe = {"scenario": "select", "rev": 1, "cfg": {},
           "base": {"rad_path": str(rad), "case_dir": str(case), "part_title": "ChR"},
           "core": {"case": {"include_path_map": {"D:/old/proj": str(inp / "mapped")}}},
           "input_roots": [["입력", str(inp)]]}
    return {"inp": inp, "case": case, "rad": rad, "out": out, "doe": doe}


def _ctx(w) -> S.Ctx:
    return S.Ctx({"doe": json.loads(json.dumps(w["doe"])), "out": str(w["out"])})


def test_include_tree_only_and_outside_include(world):
    c = _ctx(world)
    got = S._sel_rad_files(c, np.array(NIDS, dtype=np.int64))
    rels = [r for r, _ in got]
    assert rels == ["_ext/mapped/mapped.inc", "_ext/shared/far.inc", "inc/part.inc"]
    assert "old_copy.rad" not in rels and "inc/backup_part.inc" not in rels                  # 관계없는 사본 제외
    src = dict(got)
    assert src["_ext/shared/far.inc"] == os.path.normpath(str(world["inp"] / "shared" / "far.inc"))   # Case 밖 원본
    assert src["_ext/mapped/mapped.inc"] == os.path.normpath(str(world["inp"] / "mapped" / "mapped.inc"))  # path_map
    assert c._sel_rad_source == "include"


def test_manifest_preferred(world):
    from esl.library import _util as U
    (world["out"] / "prep" / "assem_full").mkdir(parents=True)
    far = os.path.normpath(str(world["inp"] / "shared" / "far.inc"))
    part = os.path.normpath(str(world["case"] / "inc" / "part.inc"))
    man = {"schema": "esl/doe_assem_full/1", "files": [
        {"rel": "m_0000.rad", "src": str(world["rad"]), "sha256": U.sha256_file(str(world["rad"]))},
        {"rel": "inc/part.inc", "src": part, "sha256": U.sha256_file(part)},
        {"rel": "_ext1/shared/far.inc", "src": far, "sha256": U.sha256_file(far)}]}
    (world["out"] / "prep" / "assem_full.json").write_text(json.dumps(man), encoding="utf-8")
    c = _ctx(world)
    got = S._sel_rad_files(c, np.array(NIDS, dtype=np.int64))
    assert [r for r, _ in got] == ["_ext1/shared/far.inc", "inc/part.inc"] and c._sel_rad_source == "assem_full"
    # 준비 뒤 원본이 바뀌면 INPUT_CHANGED
    with open(far, "a", encoding="latin-1") as fh:
        fh.write("# changed\n")
    with pytest.raises(EslError) as ei:
        S._sel_rad_files(_ctx(world), np.array(NIDS, dtype=np.int64))
    assert ei.value.code == "INPUT_CHANGED"


def test_missing_include_fails(world):
    world["rad"].write_text("/BEGIN\nm\n#include inc/nope.inc\n#include inc/part.inc\n/END\n", encoding="latin-1")
    with pytest.raises(EslError) as ei:
        S._sel_rad_files(_ctx(world), np.array(NIDS, dtype=np.int64))
    assert ei.value.code == "RAD_PARSE_ERROR"


def test_best_writes_only_work_copies(world, monkeypatch):
    """_sel_best: 사본은 best/<did>/include/<rel> 에만, 원본(Case·Case 밖·관계없는 파일) 무쓰기."""
    import types

    from esl.doe import evaluate as ev
    from esl.doe import export_mesh
    from esl.doe import scenario as sc
    nid = np.array(NIDS, dtype=np.int64)
    x0 = np.column_stack([nid.astype(float), np.zeros(4), np.zeros(4)])
    x1 = x0.copy()
    x1[:, 2] = -1.5
    mesh = {"node_id": nid, "x0": x0, "elem_id": np.array([1]), "elem_type": np.array([4]),
            "conn": np.array([[0, 1, 2, 3]]), "elem_pid": np.array([10]), "thickness": np.array([1.0]),
            "E": np.array([2e5]), "nu": np.array([0.3])}
    monkeypatch.setattr(sc, "load_base", lambda _p: (types.SimpleNamespace(mesh=mesh), None))
    monkeypatch.setattr(ev, "load_design", lambda _d: {"x": x1})
    monkeypatch.setattr(export_mesh, "write", lambda bd, m, **kw: [])
    monkeypatch.setattr(S, "_sel_rev_doc", lambda c: {"selection_sha256": "a" * 64, "basis_sha256": "b" * 64})
    before = _tree(world["inp"])
    c = _ctx(world)
    bd = str(world["out"] / "best" / "d001")
    os.makedirs(bd)
    files = S._sel_best(c, "d001", bd)
    assert files == ["include/_ext/mapped/mapped.inc", "include/_ext/shared/far.inc", "include/inc/part.inc",
                     "selection.json"]
    assert _tree(world["inp"]) == before                                                   # 원본 무쓰기
    far = (world["out"] / "best" / "d001" / "include" / "_ext" / "shared" / "far.inc").read_text(encoding="latin-1")
    assert far.startswith("# outside case\n/NODE\n") and "-1.5000000000000E+00" in far
    written = {os.path.relpath(os.path.join(r, f), world["out"]) for r, _d, fs in os.walk(world["out"]) for f in fs}
    assert all(p.startswith(os.path.join("best", "d001")) for p in written), written
    assert not any("old_copy" in p or "backup_part" in p for p in written)
