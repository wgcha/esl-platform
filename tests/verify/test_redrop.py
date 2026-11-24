"""재낙하 입력 묶음 코어(계약 esl_redrop_bundle.md §8 V-RD-1~6): 바이트 동일(바뀐 좌표 3칸 외), 기준안 무변경, 노드 누락,
노드 집합 불일치, 기준 변경(tol), 같은 ID 다른 좌표. 합성 픽스처 tests/fixtures/redrop/."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from esl.errors import EslError
from esl.verify import redrop as rd
from esl.verify.stages import rd_prepare

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "redrop"
RELS = ["m_0000.rad", "inc/a.inc", "sub/b.inc", "m_0001.rad"]
NID = np.arange(1, 13, dtype=np.int64)
X0 = np.array([[float((i - 1) % 4) * 10, float((i - 1) // 4) * 10, 1.5] for i in range(1, 13)])


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _world(tmp_path, *, drop_node: int | None = None):
    src = tmp_path / "src"
    shutil.copytree(FIX, src)
    if drop_node is not None:
        p = src / "inc" / "a.inc"
        p.write_bytes(b"\n".join(ln for ln in p.read_bytes().split(b"\n") if not ln.startswith(b"%10d" % drop_node)))
    files = [(r, str(src / r)) for r in RELS]
    base = tmp_path / "base_mesh.npz"
    np.savez(base, node_id=NID, x0=X0)
    return src, files


def _design(tmp_path, x, nid=NID, name="design.npz"):
    p = tmp_path / name
    np.savez(p, node_id=nid, x=x)
    return str(p)


def _spec(tmp_path, files, design, **kw):
    return {"base_npz": str(tmp_path / "base_mesh.npz"), "design_npz": design, "files": files,
            "out": str(tmp_path / "tok"), "meta_out": str(tmp_path / "tok"), "max_line": None,
            "base_coord_tol_mm": 0.0,
            "manifest_extra": {"platform_version": "t", "created_at": "2026-11-16T00:00:00Z",
                               "study": {"id": "s", "title": "t", "scenario": "same", "select_base": None, "plan": "case_once"},
                               "design": {"id": "d001", "rank": 1, "status": "OK", "values": {"A": 1.0}},
                               "entry": {"id": "e", "label": "L", "is_base": True},
                               "case": {"id": "c", "title": "C", "part_title": "P", "rad_file_name": "m_0000.rad"}}, **kw}


def _out_files(spec):
    out = Path(spec["out"])
    meta = {"REDROP_README.txt", "redrop_manifest.json"}
    return sorted(r for r in (str(p.relative_to(out)).replace(os.sep, "/") for p in out.rglob("*") if p.is_file()) if r not in meta)


def _moved_design(tmp_path):
    x = X0.copy()
    x[1] += [0.5, 0.25, -0.125]          # 노드 2 (starter, 고정폭)
    x[6] += [1.0, 0.0, 2.0]              # 노드 7 (a.inc, 고정폭 + tail)
    x[10] += [0.0, 3.0, 0.5]             # 노드 11 (b.inc, 쉼표 자유형식, CRLF)
    return x, _design(tmp_path, x[::-1].copy(), NID[::-1].copy())     # 일부러 역순 — base 순서 정렬 확인


def test_rd1_byte_identical_except_coords(tmp_path):
    src, files = _world(tmp_path)
    x, dz = _moved_design(tmp_path)
    spec = _spec(tmp_path, files, dz)
    before = {r: (_sha(p), os.stat(p).st_mtime_ns) for r, p in files}
    m = rd_prepare(spec, echo=lambda *_: None)
    assert {r: (_sha(p), os.stat(p).st_mtime_ns) for r, p in files} == before          # 원본 불변
    assert m["changed"] == ["m_0000.rad", "inc/a.inc", "sub/b.inc"] and m["nodes"]["n_patched_lines"] == 3
    assert _out_files(spec) == sorted(m["changed"])                                     # 바뀐 파일만 out 에
    for rel in m["changed"]:
        o = (src / rel).read_bytes().splitlines(keepends=True)
        n = (Path(spec["out"]) / rel).read_bytes().splitlines(keepends=True)
        assert len(o) == len(n)
        diff = [(a, b) for a, b in zip(o, n) if a != b]
        assert len(diff) == 1
        a, b = diff[0]
        assert a[-2:] == b[-2:] if a.endswith(b"\r\n") else a[-1:] == b[-1:]            # 줄바꿈 보존
        if a.lstrip()[:3] == b"11,":                         # 쉼표 줄: ID·구분자 구조 유지
            assert len(b.split(b",")) == len(a.split(b","))
        else:
            assert a[:10] == b[:10] and a[70:] == b[70:]                                # ID·70자 뒤 나머지 불변
    # 움직이지 않은 대상 노드·대상 밖 노드·다른 카드는 바이트 동일: starter 에서 노드 1·101 줄과 카드들
    sb = (Path(spec["out"]) / "m_0000.rad").read_bytes()
    for ln in (src / "m_0000.rad").read_bytes().splitlines(keepends=True):
        if not ln.startswith(b"         2") or b"/" in ln[:1]:
            assert ln in sb.splitlines(keepends=True)
    assert m["nodes"]["n_moved"] == 3 and m["nodes"]["max_disp_node_id"] == 11
    assert m["nodes"]["max_disp"] == pytest.approx(float(np.linalg.norm(x - X0, axis=1).max()))
    # 패치 후 좌표 읽기 = 설계 좌표
    from esl.verify.patch import read_node_coords
    got, found = read_node_coords([(r, str(Path(spec["out"]) / r) if r in m["changed"] else p) for r, p in files], NID)
    assert found.all() and np.allclose(got, x, rtol=1e-12, atol=1e-12)


def test_rd2_base_design_changes_nothing(tmp_path):
    src, files = _world(tmp_path)
    spec = _spec(tmp_path, files, _design(tmp_path, X0))
    m = rd_prepare(spec, echo=lambda *_: None)
    assert m["changed"] == [] and m["nodes"]["n_moved"] == 0 and m["nodes"]["max_disp_node_id"] is None
    assert _out_files(spec) == []
    assert {f["rel"]: f["sha256"] for f in m["files"]} == {r: _sha(p) for r, p in files}
    assert all(f["source"] == "orig" for f in m["files"])
    assert sorted(os.listdir(tmp_path / "tok")) == ["REDROP_README.txt", "redrop_manifest.json"]      # input/ 단계 없음(v0.24.5)
    mm = json.loads((tmp_path / "tok" / "redrop_manifest.json").read_text(encoding="utf-8"))
    assert sorted(mm) == sorted(["schema", "platform_version", "created_at", "study", "design", "entry", "case", "files", "changed",
                        "nodes", "checks"]) and mm["schema"] == "esl/redrop/1"
    assert mm["checks"] == {"nodeset_equal": True, "base_max_diff": 0.0, "base_coord_tol_mm": 0.0}
    readme = (tmp_path / "tok" / "REDROP_README.txt").read_text(encoding="utf-8")
    assert "input/" not in readme and "이 폴더를 그대로 HPC 에 올려" in readme


def test_rd3_missing_node(tmp_path):
    _src, files = _world(tmp_path, drop_node=6)
    x, dz = _moved_design(tmp_path)
    spec = _spec(tmp_path, files, dz)
    with pytest.raises(EslError) as ei:
        rd_prepare(spec, echo=lambda *_: None)
    assert ei.value.code == "VD_NODES_MISSING" and "[6]" in ei.value.message
    assert _out_files(spec) == []


@pytest.mark.parametrize("kind", ["extra", "less", "dup"])
def test_rd4_nodeset_mismatch(tmp_path, kind):
    _src, files = _world(tmp_path)
    if kind == "extra":
        nid, x = np.append(NID, 999), np.vstack([X0, [0, 0, 0]])
    elif kind == "less":
        nid, x = NID[:-1], X0[:-1]
    else:
        nid, x = NID.copy(), X0.copy()
        nid[-1] = nid[0]
    spec = _spec(tmp_path, files, _design(tmp_path, x, nid))
    with pytest.raises(rd.RedropError) as ei:
        rd_prepare(spec, echo=lambda *_: None)
    assert ei.value.code == "REDROP_NODESET_MISMATCH"
    assert {"n_base", "n_design", "n_only_base", "n_only_design"} <= set(ei.value.detail)
    assert ei.value.detail["n_base"] == 12 and _out_files(spec) == []


def test_rd5_base_changed_and_tol(tmp_path):
    src, files = _world(tmp_path)
    p = src / "inc" / "a.inc"                                   # 노드 6 원본 좌표를 0.02 어긋나게
    old = p.read_bytes().split(b"\n")
    i = next(k for k, ln in enumerate(old) if ln.startswith(b"         6"))
    old[i] = (b"%10d%20.6f%20.6f%20.6f  tail" % (6, X0[5][0] + 0.02, X0[5][1], X0[5][2]))
    p.write_bytes(b"\n".join(old))
    x, dz = _moved_design(tmp_path)
    spec = _spec(tmp_path, files, dz)
    with pytest.raises(rd.RedropError) as ei:
        rd_prepare(spec, echo=lambda *_: None)
    assert ei.value.code == "REDROP_BASE_CHANGED" and ei.value.detail["n_changed"] == 1
    assert ei.value.detail["max_diff"] == pytest.approx(0.02) and _out_files(spec) == []
    spec = _spec(tmp_path, files, dz, base_coord_tol_mm=0.05)
    m = rd_prepare(spec, echo=lambda *_: None)
    assert m["checks"]["base_max_diff"] == pytest.approx(0.02) and m["checks"]["base_coord_tol_mm"] == 0.05
    a_out = Path(spec["out"]) / "inc" / "a.inc"
    got = a_out.read_bytes().split(b"\n")
    assert got[i] == old[i]                                     # 안 움직인 노드 6 = 원본 줄 그대로


def test_rd6_same_id_different_coords(tmp_path):
    src, files = _world(tmp_path)
    p = src / "sub" / "b.inc"
    p.write_bytes(p.read_bytes().replace(b"/GRNOD", b"/NODE\r\n" + b"         5%20.6f%20.6f%20.6f\r\n" % (9.0, 9.0, 9.0) + b"/GRNOD"))
    spec = _spec(tmp_path, files, _design(tmp_path, X0))
    with pytest.raises(EslError) as ei:
        rd_prepare(spec, echo=lambda *_: None)
    assert ei.value.code == "RAD_PARSE_ERROR"
    assert _out_files(spec) == []


def test_redrop_module_independent():
    src = (Path(__file__).resolve().parents[2] / "esl" / "verify" / "redrop.py").read_text(encoding="utf-8")
    imps = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert imps <= {"__future__", "numpy", "esl.errors"}, imps
    assert "open(" not in src


def test_merge_coords_and_readme():
    x, st = rd.merge_coords(NID, X0[::-1] + 1.0, X0, X0, 0.0, design_node_id=NID[::-1])
    assert np.allclose(x, X0 + 1.0) and st["n_moved"] == 12 and st["max_disp"] == pytest.approx(np.sqrt(3))


def test_rd8_meta_name_conflict_rejected(tmp_path):
    """v0.24.5: 입력 rel 이 메타 이름과 겹치면(대소문자 무시) 쓰기 전에 거부 — 폴더가 한 층이라 덮어쓰기 위험."""
    src, files = _world(tmp_path)
    (src / "redrop_manifest.json").write_bytes(b"x")
    spec = _spec(tmp_path, files + [("Redrop_Manifest.json", str(src / "redrop_manifest.json"))], _design(tmp_path, X0))
    with pytest.raises(EslError) as ei:
        rd_prepare(spec, echo=lambda *_: None)
    assert ei.value.code == "REDROP_META_NAME_CONFLICT"
    assert not (tmp_path / "tok").exists() or os.listdir(tmp_path / "tok") == []
