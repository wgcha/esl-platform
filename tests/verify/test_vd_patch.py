"""V-SR-16 노드 ID 기준 /NODE 좌표 패치(계약 esl_scx_relay.md SR-D-13): Ch/R 노드가 rad 본문·여러 include 에 흩어진 경우,
고정폭·쉼표·공백 구분 줄, 다른 줄 바이트 불변(줄바꿈 CRLF 포함), 바뀐 파일만 출력, 원본 sha·mtime 불변, 못 찾은 노드 VD_NODES_MISSING,
패치 후 parse_rad 좌표 = 모핑 좌표(1e-9 상대), vd_patch 단계(모핑 사본 → 패치)."""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pytest

from esl.errors import EslError
from esl.rad import parse_rad, write_rad
from esl.verify.patch import patch_node_files


def _sha(p) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _fix(nid, x, y, z) -> str:
    return f"{nid:10d}{x:20.6f}{y:20.6f}{z:20.6f}"


def _model(tmp_path, free: bool = True):
    """starter(노드 1~6 본문) + inc/a.inc(노드 7~9, 고정폭 CRLF) + inc/b.inc(노드 10~12 쉼표·공백 구분 + 다른 카드)."""
    d = tmp_path / "in"
    (d / "inc").mkdir(parents=True)
    xs = np.array([[x, y, 0.0] for y in range(4) for x in range(3)], float) * 10.0      # 12 노드
    nid = np.arange(1, 13)
    conn = np.array([[1, 2, 5, 4], [2, 3, 6, 5], [4, 5, 8, 7], [5, 6, 9, 8], [7, 8, 11, 10], [8, 9, 12, 11]])
    rad = write_rad(str(d / "m_0000.rad"), nid, xs, np.arange(101, 107), np.full(6, 4, np.int8), conn, 7,
                    "Chassis rear", 70, 2.0, 700, 2.1e5, 0.3)
    text = open(rad, encoding="utf-8").read().splitlines()
    # 본문 /NODE 블록에서 7~12 를 빼 include 로 옮긴다
    s = text.index("/NODE")
    e = next(i for i in range(s + 1, len(text)) if text[i].startswith("/"))
    body = [ln for ln in text[s + 1:e] if not ln.strip() or ln.startswith("#") or int(ln[:10]) <= 6]
    lines = text[:s + 1] + body + text[e:]
    endi = lines.index("/END")
    lines[endi:endi] = ["#include inc/a.inc", "#include inc/b.inc"]
    open(rad, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    a = ["# a include", "/NODE"] + [_fix(i, *xs[i - 1]) for i in (7, 8, 9)] + ["/BCS/1", "bc", "       111       000         0"]
    (d / "inc" / "a.inc").write_bytes(("\r\n".join(a) + "\r\n").encode())
    b = ["$ b include", "/NODE",
         f"10, {xs[9][0]}, {xs[9][1]}, {xs[9][2]}" if free else _fix(10, *xs[9]),
         f"   11   {xs[10][0]}   {xs[10][1]}   {xs[10][2]}" if free else _fix(11, *xs[10]),
         _fix(12, *xs[11]),
         "#  comment inside", "/GRNOD/NODE/9", "grp", "         1         2"]
    (d / "inc" / "b.inc").write_bytes(("\n".join(b) + "\n").encode())
    files = [("m_0000.rad", str(d / "m_0000.rad")), ("inc/a.inc", str(d / "inc" / "a.inc")),
             ("inc/b.inc", str(d / "inc" / "b.inc"))]
    return d, files, nid, xs


def test_patch_scattered_nodes_formats_and_bytes(tmp_path):
    d, files, nid, xs = _model(tmp_path)
    before = {r: (_sha(p), os.stat(p).st_mtime_ns) for r, p in files}
    X = xs.copy()
    moved = {2: (10.5, 0.25, 1.125), 8: (10.0, 30.0, -2.5), 10: (0.0, 30.0, 3.0), 11: (10.0, 30.0, 3.5)}
    for k, v in moved.items():
        X[k - 1] = v
    coords = {int(nid[i]): tuple(X[i]) for i in range(nid.size)}
    out = tmp_path / "stage"
    res = patch_node_files(files, coords, str(out), required=nid.tolist())
    by = {f["rel"]: f for f in res["files"]}
    assert res["n_patched"] == 4 and res["found"] == 12
    assert {r: f["source"] for r, f in by.items()} == {"m_0000.rad": "patched", "inc/a.inc": "patched", "inc/b.inc": "patched"}
    assert by["m_0000.rad"]["n_patched"] == 1 and by["inc/a.inc"]["n_patched"] == 1 and by["inc/b.inc"]["n_patched"] == 2
    # 원본 불변(sha·mtime), 출력은 stage 아래에만
    assert {r: (_sha(p), os.stat(p).st_mtime_ns) for r, p in files} == before
    assert sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == ["inc/a.inc", "inc/b.inc", "m_0000.rad"]
    for r, f in by.items():
        assert f["path"] == str(out / r) and f["sha256"] == _sha(f["path"]) and f["size"] == os.path.getsize(f["path"])
    # 바뀐 줄만: 줄 수·줄바꿈 같고 노드 2·8·10·11 줄만 다름
    for r, p in files:
        o = open(p, "rb").read().splitlines(keepends=True)
        n = open(by[r]["path"], "rb").read().splitlines(keepends=True)
        assert len(o) == len(n)
        diff = [(x, y) for x, y in zip(o, n) if x != y]
        assert all(x[-2:] == y[-2:] for x, y in diff)                      # CRLF/LF 보존
        ids = sorted(int(x.split(b",")[0]) if b"," in x else int(x.split()[0]) for x, _ in diff)
        assert ids == sorted(k for k in moved if (r == "m_0000.rad" and k <= 6) or (r == "inc/a.inc" and 7 <= k <= 9)
                             or (r == "inc/b.inc" and k >= 10))
        for _, y in diff:
            t = y.rstrip(b"\r\n").decode()
            if "," in t:
                assert t.startswith("10,") and t.count(",") == 3
            elif t.split()[0] == "11" and not t.startswith(" " * 8):
                assert len(t.split()) == 4                                  # 공백 구분 그대로
            else:
                assert len(t) == 70 and t[10:30].strip().endswith(("E+00", "E+01", "E-01", "E+02"))
    # 다른 카드 그대로(/BCS·/GRNOD 의 숫자 줄)
    nb = open(by["inc/b.inc"]["path"], "rb").read()
    assert b"/GRNOD/NODE/9\ngrp\n         1         2\n" in nb
    # 쉼표 줄은 esl.doe.nodes 로 다시 읽어 모핑 좌표(공백 줄은 직접)
    from esl.doe.nodes import _parse_node_line

    t10 = next(ln for ln in nb.decode().splitlines() if ln.startswith("10,"))
    np.testing.assert_allclose(_parse_node_line(t10, "b", 3)[1], X[9], rtol=1e-12)
    t11 = next(ln for ln in nb.decode().splitlines() if ln.split() and ln.split()[0] == "11")
    np.testing.assert_allclose([float(v) for v in t11.split()[1:]], X[10], rtol=1e-12)


def test_patched_set_parses_to_morph_coords(tmp_path):
    """고정폭 세트: 패치 후 parse_rad 좌표 = 모핑 좌표(1e-9 상대), 다른 노드 그대로."""
    d, files, nid, xs = _model(tmp_path, free=False)
    X = xs.copy()
    X[1] = (10.123456789012, 0.5, -0.75)
    X[7] = (10.0, 31.0, 2.0)
    X[11] = (20.0, 29.5, -1.0e-3)
    res = patch_node_files(files, {int(nid[i]): tuple(X[i]) for i in range(nid.size)}, str(tmp_path / "stage"))
    by = {f["rel"]: f for f in res["files"]}
    assert res["n_patched"] == 3
    # 원 폴더 구조 그대로 다시 맞춘 사본(패치 파일 + 원본)으로 파싱
    import shutil

    chk = tmp_path / "chk"
    for r, f in by.items():
        (chk / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f["path"], chk / r)
    m = parse_rad(str(chk / "m_0000.rad"), "Chassis rear")
    got = {int(i): m.x0[k] for k, i in enumerate(m.node_id)}
    for k in range(nid.size):
        np.testing.assert_allclose(got[int(nid[k])], X[k], rtol=1e-9, atol=1e-12)
    m0 = parse_rad(files[0][1], "Chassis rear")
    assert m0.node_id.tolist() == m.node_id.tolist() and m0.elem_id.tolist() == m.elem_id.tolist()
    np.testing.assert_array_equal(m0.conn, m.conn)


def test_unchanged_files_stay_orig_and_missing_nodes(tmp_path):
    d, files, nid, xs = _model(tmp_path)
    coords = {int(nid[i]): tuple(xs[i]) for i in range(nid.size)}
    coords[3] = (21.0, 0.0, 0.0)
    out = tmp_path / "stage"
    res = patch_node_files(files, coords, str(out), required=nid.tolist())
    src = {f["rel"]: f["source"] for f in res["files"]}
    assert src == {"m_0000.rad": "patched", "inc/a.inc": "orig", "inc/b.inc": "orig"}
    orig = next(f for f in res["files"] if f["rel"] == "inc/a.inc")
    assert orig["path"] == files[1][1] and orig["sha256"] == _sha(files[1][1])
    assert not (out / "inc").exists()
    # 세트에 없는 노드 → VD_NODES_MISSING(개수·상위 10), 아무것도 쓰지 않음
    out2 = tmp_path / "stage2"
    with pytest.raises(EslError) as ei:
        patch_node_files(files[:2], coords, str(out2), required=nid.tolist())
    assert ei.value.code == "VD_NODES_MISSING" and "3개" in ei.value.message and "[10, 11, 12]" in ei.value.message
    assert not out2.exists()


def test_vd_patch_stage_from_morph_copy(tmp_path):
    from esl.verify import stages

    d, files, nid, xs = _model(tmp_path)
    best = tmp_path / "best" / "d007" / "include"
    (best / "inc").mkdir(parents=True)
    # paicad 사본: /NODE 좌표만 바뀐 include 1개(노드 8 이동)
    (best / "inc" / "a.inc").write_text("/NODE\n" + _fix(7, *xs[6]) + "\n" + _fix(8, 10.0, 30.0, -4.0) + "\n"
                                        + _fix(9, *xs[8]) + "\n")
    mz = tmp_path / "model.npz"
    np.savez(mz, node_id=nid, x0=xs)
    res = stages.vd_patch({"model_npz": str(mz), "best_dir": str(best), "best_rels": ["inc/a.inc"], "files": files,
                           "out": str(tmp_path / "stage"), "result_out": str(tmp_path / "patch.json"),
                           "morph_out": str(tmp_path / "morph.npz")}, echo=lambda *_: None)
    assert res["morph"]["n_moved"] == 1 and res["n_patched"] == 1
    assert [f["rel"] for f in res["files"] if f["source"] == "patched"] == ["inc/a.inc"]
    z = np.load(tmp_path / "morph.npz")
    assert z["node_id"].tolist() == [8] and z["x"].tolist() == [[10.0, 30.0, -4.0]]
    with pytest.raises(EslError) as ei:
        stages.vd_patch({"model_npz": str(mz), "best_dir": str(best), "best_rels": [], "files": files,
                         "out": str(tmp_path / "s3"), "result_out": str(tmp_path / "p3.json"),
                         "morph_out": str(tmp_path / "m3.npz")}, echo=lambda *_: None)
    assert ei.value.code == "VD_DESIGN_NO_FILES"


def test_patch_non_ascii_node_line_is_vd_patch_encoding(tmp_path):
    """v0.12.0 L2: 고칠 /NODE 줄에 ASCII 가 아닌 문자(줄 끝 한글 메모 등) → EslError VD_PATCH_ENCODING, 임시·출력 파일 없음."""
    d, files, nid, xs = _model(tmp_path)
    a = d / "inc" / "a.inc"
    raw = a.read_bytes().split(b"\r\n")
    k = next(i for i, ln in enumerate(raw) if ln[:10].strip() == b"7")
    raw[k] = raw[k] + "  메모".encode("utf-8")
    a.write_bytes(b"\r\n".join(raw))
    X = xs.copy()
    X[6] += 0.5                                                        # 노드 7(그 줄) 좌표 바꿈
    out = tmp_path / "out"
    with pytest.raises(EslError) as ei:
        patch_node_files(files, {int(n): X[i] for i, n in enumerate(nid)}, str(out))
    assert ei.value.code == "VD_PATCH_ENCODING" and "a.inc" in ei.value.message
    assert not (out / "inc" / "a.inc").exists()                       # 최종 출력 파일은 만들지 않음
