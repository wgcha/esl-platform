"""③ 최적 안 메시 산출물 (계약 esl_bead_doe.md BD-D-18): ``ch_r.rad``(/NODE·/SHELL·/SH3N·/PART·/PROP(SHELL=TYPE1)·
/MAT/LAW1, ID 1부터) + ``ch_r.fem``(GRID·CQUAD4·CTRIA3·PSHELL·MAT1). 기존 작성기 재사용:
``esl.rad.writer.write_rad``(parse_rad 왕복 일치), ``esl.opt.femread.write_fem``.
"""
from __future__ import annotations

import os

import numpy as np

from esl.opt.femread import write_fem
from esl.rad.writer import write_rad

RAD_NAME = "ch_r.rad"
FEM_NAME = "ch_r.fem"


def _conn_ids(mesh: dict) -> np.ndarray:
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    ids = np.where(c >= 0, nid[np.maximum(c, 0)], 0)
    ids[np.asarray(mesh["elem_type"]).astype(int) == 3, 3] = 0
    return ids


def write(out_dir: str, mesh: dict, *, part_title: str = "ch_r", rho: float = 7.85e-9, header: list | None = None,
          guard=None) -> list[str]:
    """out_dir 에 ch_r.rad·ch_r.fem → 파일 이름 목록. mesh 는 ID 1부터(gmsh 재번호) 쉘 메시."""
    g = guard or (lambda p: p)
    os.makedirs(out_dir, exist_ok=True)
    et = np.asarray(mesh["elem_type"]).astype(int)
    E = float(np.median(np.asarray(mesh["E"], dtype=np.float64)))
    nu = float(np.median(np.asarray(mesh["nu"], dtype=np.float64)))
    pid = int(np.asarray(mesh["elem_pid"], dtype=np.int64)[0]) if et.size else 1
    write_rad(g(os.path.join(out_dir, RAD_NAME)), mesh["node_id"], mesh["x0"], mesh["elem_id"], et, _conn_ids(mesh),
              1, part_title, pid, np.asarray(mesh["thickness"], dtype=np.float64), 1, E, nu, rho=rho)
    m = dict(mesh)
    m.setdefault("elem_mid", np.ones(et.size, dtype=np.int64))
    write_fem(g(os.path.join(out_dir, FEM_NAME)), m, header=list(header or ["esl bead DOE (scenario step)"]))
    return [RAD_NAME, FEM_NAME]
