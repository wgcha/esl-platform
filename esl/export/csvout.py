"""CSV 쓰기 (UTF-8, BOM 없음, 헤더 1줄, 설정 export.csv 의 구분자·실수 서식)."""
from __future__ import annotations

import numbers
from typing import Iterable, Sequence

import numpy as np


class CsvFormat:
    def __init__(self, delimiter: str, float_format: str):
        self.delimiter = delimiter
        self.float_format = float_format

    def cell(self, v) -> str:
        if v is None:
            return ""
        if isinstance(v, (bool, np.bool_)):
            return "1" if v else "0"
        if isinstance(v, (numbers.Integral, np.integer)):
            return str(int(v))
        if isinstance(v, (numbers.Real, np.floating)):
            return self.float_format.format(float(v))
        s = str(v)
        if self.delimiter in s or '"' in s or "\n" in s:
            s = '"' + s.replace('"', '""') + '"'
        return s

    def line(self, row: Sequence) -> str:
        return self.delimiter.join(self.cell(v) for v in row) + "\n"


def write_csv(path: str, header: Sequence[str], rows: Iterable[Sequence], fmt: CsvFormat) -> str:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(fmt.line(header))
        for r in rows:
            fh.write(fmt.line(r))
    return path


def f_eq_rows(node_id, x0, f, is_bc):
    mag = np.linalg.norm(f, axis=1)
    for i in range(len(node_id)):
        yield (int(node_id[i]), x0[i, 0], x0[i, 1], x0[i, 2], f[i, 0], f[i, 1], f[i, 2], mag[i], bool(is_bc[i]))


F_EQ_HEADER = ("node_id", "x0", "y0", "z0", "fx", "fy", "fz", "mag", "is_bc")
U_REL_HEADER = ("node_id", "ux", "uy", "uz", "ux_total", "uy_total", "uz_total")
REACTIONS_HEADER = ("node_id", "dof", "rx", "ry", "rz")
CANDIDATES_HEADER = ("rank", "frame_index", "time", "eps_max", "elem_id")
HOTSPOTS_HEADER = ("rank", "elem_id", "eps_eq", "cx", "cy", "cz")
HISTORY_HEADER = ("time", "eps_max", "eps_hotspot1")
VALIDATION_HEADER = ("metric", "value", "criterion", "pass", "role")
VALIDATION_HOT_HEADER = ("elem_id", "eps_rad", "eps_val", "rel_err")


def write_validation_csv(path: str, validation: dict, fmt: CsvFormat) -> str:
    """``metric,value,criterion,pass,role`` — 첫 행 ``verdict``, 이어서 지표 행 + 빈 줄 + hotspot 표.

    role = judge(판정) | reference(참고 — pass 열은 초과 여부 ``exceeded``) | info. 예전(schema 2) validation.json 은 role 빈칸.
    """
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(fmt.line(VALIDATION_HEADER))
        v = validation["verdict"]
        fh.write(fmt.line(("verdict", v, None, v == "PASS", "judge")))
        for m in validation["metrics"]:
            role = m.get("role", "")
            flag = m.get("exceeded") if role == "reference" else m["pass"]
            fh.write(fmt.line((m["metric"], m["value"], m["criterion"], flag, role)))
        fh.write("\n")
        fh.write(fmt.line(VALIDATION_HOT_HEADER))
        for h in validation["hotspots"]:
            fh.write(fmt.line((int(h["elem_id"]), h["eps_rad"], h["eps_val"], h["rel_err"])))
    return path
