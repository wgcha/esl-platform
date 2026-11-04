"""v0.16.0 메시 입력 시험용 작은 Radioss 덱 쓰기(esl_compare_mesh_options.md V-C2-5·6). 10자 정수·20자 실수 칸."""
from __future__ import annotations

import os

import numpy as np


def begin(length: str | None = "mm") -> list[str]:
    if length is None:
        return []
    return ["/BEGIN", "mesh_in", f"{2017:10d}{0:10d}", f"{'Mg':>20}{length:>20}{'s':>20}", f"{'Mg':>20}{'mm':>20}{'s':>20}"]


def nodes(ids, X) -> list[str]:
    out = ["/NODE"]
    for i, (x, y, z) in zip(ids, X):
        out.append(f"{int(i):10d}{x:20.6f}{y:20.6f}{z:20.6f}")
    return out


def shells(pid: int, eids, conn) -> list[str]:
    out = [f"/SHELL/{pid}"]
    for e, c in zip(eids, conn):
        out.append(f"{int(e):10d}" + "".join(f"{int(n):10d}" for n in c))
    return out


def sh3n(pid: int, eids, conn) -> list[str]:
    out = [f"/SH3N/{pid}"]
    for e, c in zip(eids, conn):
        out.append(f"{int(e):10d}" + "".join(f"{int(n):10d}" for n in c[:3]))
    return out


def part(pid: int, title: str, prop: int = 1, mat: int = 1) -> list[str]:
    return [f"/PART/{pid}", title, f"{prop:10d}{mat:10d}"]


def grid(nx: int, ny: int, dx: float, dy: float, x0: float = 0.0, y0: float = 0.0, nid0: int = 1, eid0: int = 1):
    """nx×ny 쿼드 격자 → (노드 ID, 좌표, 요소 ID, 연결(노드 ID))."""
    ii, jj = np.meshgrid(np.arange(nx + 1), np.arange(ny + 1), indexing="ij")
    X = np.stack([x0 + ii.ravel() * dx, y0 + jj.ravel() * dy, np.zeros(ii.size)], 1)
    ids = nid0 + np.arange(ii.size)
    idx = (np.arange(nx)[:, None] * (ny + 1) + np.arange(ny)[None, :]).ravel()
    conn = np.stack([idx, idx + ny + 1, idx + ny + 2, idx + 1], 1)
    return ids, X, eid0 + np.arange(conn.shape[0]), ids[conn]


def write(path, lines: list[str]) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return str(path)
