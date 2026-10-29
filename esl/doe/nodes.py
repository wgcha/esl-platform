"""paicad check 사본(``out_files/<rel>``)의 ``/NODE`` 좌표 읽기 (계약 BD-D-10, V-BD-4).

paicad ``shell run`` 은 check PASS 일 때 **노드가 바뀐 파일만** ``--out-files-dir/<rel>`` 로 내고, 그 사본은 원본에서
``/NODE`` 좌표 필드만 바꾼 것이다(ID·연결 불변). 여기서는 대상 파트 node_id 의 좌표만 읽어 x_d 를 만든다.
사본에 없는 대상 노드는 원 좌표 그대로(그 노드가 있던 파일은 바뀌지 않음).

- 줄 길이 상한: ``esl.rad.parser.bounded_readline``(설정 case.rad_max_line_kb) — 줄바꿈 없는 거대 파일 방지.
- 형식: 고정 칸 I10·F20·F20·F20(Radioss), 쉼표가 있으면 자유 형식. ``#``·``$`` 주석, 다음 ``/`` 키워드에서 블록 끝.
- 오류: rel 이 out_files 밖 → PATH_OUTSIDE_ROOT, 목록의 파일 없음 → MORPH_NODES_MISSING, 같은 노드가 다른 좌표로 두 번
  → RAD_PARSE_ERROR, morph 가 노드를 옮겼다는데(moved > 0) 사본에서 대상 노드를 하나도 못 찾음 → MORPH_NODES_MISSING.
"""
from __future__ import annotations

import os

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.rad.parser import _decode, _f, _i, bounded_readline


def _parse_node_line(line: str, path: str, lineno: int):
    try:
        if "," in line:
            f = [x.strip() for x in line.split(",")]
            nid = _i(f[0])
            xyz = [(_f(f[k]) or 0.0) if k < len(f) else 0.0 for k in (1, 2, 3)]
        else:
            nid = _i(line[0:10])
            xyz = [_f(line[10:30]) or 0.0, _f(line[30:50]) or 0.0, _f(line[50:70]) or 0.0]
    except ValueError as exc:
        raise EslError("RAD_PARSE_ERROR", f"/NODE 행 해석 실패 ({os.path.basename(path)}:{lineno}): {exc}") from None
    if nid is None:
        raise EslError("RAD_PARSE_ERROR", f"/NODE 행에 노드 ID 가 없음 ({os.path.basename(path)}:{lineno})")
    return nid, xyz


def read_nodes(path: str, wanted=None, max_line: int | None = None) -> dict:
    """파일 1개의 /NODE 블록 → {node_id: (x, y, z)} (wanted 가 주어지면 그 ID 만)."""
    want = None if wanted is None else set(int(x) for x in wanted)
    out: dict[int, tuple] = {}
    in_node = False
    with open(path, "rb") as fh:
        readline = bounded_readline(fh, path, max_line)
        lineno = 0
        while True:
            raw = readline()
            if not raw:
                break
            lineno += 1
            if raw[:1] in (b"#", b"$"):
                continue
            if raw[:1] == b"/":
                toks = raw[1:].split(b"/")[0].split()
                in_node = bool(toks) and toks[0].upper() == b"NODE"
                continue
            if not in_node:
                continue
            line = _decode(raw)
            if not line.strip():
                continue
            nid, xyz = _parse_node_line(line, path, lineno)
            if want is not None and nid not in want:
                continue
            t = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
            if nid in out and out[nid] != t:
                raise EslError("RAD_PARSE_ERROR", f"노드 {nid} 가 {os.path.basename(path)} 에 다른 좌표로 두 번 있음")
            out[nid] = t
    return out


def morphed_coords(out_files_dir: str, rels: list[str], node_id, x_base, *, expected_moved: int | None = None,
                   max_line: int | None = None) -> tuple[np.ndarray, dict]:
    """대상 노드 순서 좌표 x_d (N,3)와 정보 {n_found, n_moved, max_disp, files}."""
    nid = np.asarray(node_id, dtype=np.int64)
    X = np.array(x_base, dtype=np.float64, copy=True)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    root = U.real_path(out_files_dir)
    found: dict[int, tuple] = {}
    files = []
    for rel in rels:
        p = U.real_path(os.path.join(out_files_dir, rel))
        if not U.is_within(p, root):
            raise EslError("PATH_OUTSIDE_ROOT", f"모핑 사본 경로가 out_files 밖: {rel}")
        if not os.path.isfile(p):
            raise EslError("MORPH_NODES_MISSING", f"모핑 사본 파일이 없음: {rel}")
        got = read_nodes(p, pos.keys(), max_line)
        for k, v in got.items():
            if k in found and found[k] != v:
                raise EslError("RAD_PARSE_ERROR", f"노드 {k} 가 모핑 사본 여러 파일에 다른 좌표로 있음")
            found[k] = v
        files.append({"rel": rel, "n_nodes": len(got)})
    if expected_moved and expected_moved > 0 and not found:
        raise EslError("MORPH_NODES_MISSING", f"paicad 가 노드 {expected_moved}개를 옮겼다는데 모핑 사본에서 대상 파트 노드를 "
                                              "찾지 못함")
    for k, v in found.items():
        X[pos[k]] = v
    d = np.linalg.norm(X - np.asarray(x_base, dtype=np.float64), axis=1) if X.size else np.zeros(0)
    return X, {"n_found": len(found), "n_moved": int(np.sum(d > 0)), "max_disp": float(d.max()) if d.size else 0.0,
               "files": files}
