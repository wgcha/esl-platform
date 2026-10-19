"""Radioss 2017+ 블록 포맷 include 파일 (esl_cload.inc, esl_bcs.inc).

열 규약: 정수 I10(10자 오른쪽 정렬), 실수 F20(20자 오른쪽 정렬, ``export.num_format``).
카드 레이아웃(Radioss Reference Guide 2017+ 기준, 각 카드: 헤더 / title / 데이터 행):

  /FUNCT/fct_ID         title / (X F20, Y F20) 점 행
  /GRNOD/NODE/grnd_ID   title / node_ID I10 × 최대 10개/행
  /CLOAD/load_ID        title / funct_IDT  Dir  skew_ID  sens_ID  grnd_ID (I10×5, Dir 은 'X'|'Y'|'Z' 를
                        10자 칸에 오른쪽 정렬) + Ascale_x(F20) + Fscale_Y(F20)
  /BCS/bcs_ID           title / "Tra rot" 10자 칸(Tra = 4~6열, rot = 8~10열, 예 '   111 000')
                        + skew_ID(I10) + grnd_ID(I10)

※ 확신 없는 부분(실행 검증 미수행): /BCS 첫 칸의 Tra·rot 열 위치(위 가정), /CLOAD 의 Dir 칸 정렬
   (오른쪽 정렬로 씀; Radioss 는 칸 안 공백을 무시하는 것으로 알고 있음), /CLOAD 에 unit_ID 생략.
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError
from esl.export import ascii_text

_RULER = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"
_DIR = ("X", "Y", "Z")


def i10(v) -> str:
    s = str(int(v))
    if len(s) > 10:
        raise EslError("ID_RANGE_COLLISION", f"ID {v} 가 Radioss I10 칸(10자리)을 넘음 — 노드·요소 ID 또는 "
                                             f"export.radioss.id_offset 확인")
    return s.rjust(10)


def f20(x, num_format: str) -> str:
    s = num_format.format(float(x))
    if len(s) > 20:
        raise EslError("CONFIG_INVALID", f"export.num_format: 실수 '{s}' 가 F20 칸(20자)을 넘음")
    return s.rjust(20)


def a10(s: str) -> str:
    return str(s).rjust(10)


def _comment_header(lines) -> list[str]:
    return ["#" + (" " + ascii_text(ln) if ln else "") for ln in lines]


def funct_card(fid: int, func_mode: str, ramp_time: float, num_format: str) -> list[str]:
    if func_mode == "ramp":
        pts = [(0.0, 0.0), (ramp_time, 1.0), (1.0e30, 1.0)]
    elif func_mode == "constant":
        pts = [(0.0, 1.0), (1.0e30, 1.0)]
    else:
        raise ValueError(f"func_mode: {func_mode}")
    L = [f"/FUNCT/{int(fid)}", f"ESL_{func_mode}",
         "#                  X                   Y"]
    L += [f20(x, num_format) + f20(y, num_format) for x, y in pts]
    return L


def grnod_node_card(gid: int, title: str, node_ids) -> list[str]:
    L = [f"/GRNOD/NODE/{int(gid)}", ascii_text(title), "#  node_ID1  node_ID2  node_ID3  node_ID4  node_ID5"
         "  node_ID6  node_ID7  node_ID8  node_ID9 node_ID10"]
    ids = [int(n) for n in node_ids]
    for k in range(0, len(ids), 10):
        L.append("".join(i10(n) for n in ids[k:k + 10]))
    return L


def cload_card(lid: int, title: str, fct_id: int, comp: int, grnd_id: int, value: float,
               num_format: str) -> list[str]:
    return [
        f"/CLOAD/{int(lid)}", ascii_text(title),
        "#funct_IDT       Dir   skew_ID   sens_ID   grnd_ID            Ascale_x            Fscale_Y",
        i10(fct_id) + a10(_DIR[comp]) + i10(0) + i10(0) + i10(grnd_id)
        + f20(1.0, num_format) + f20(value, num_format),
    ]


def bcs_card(bid: int, title: str, tra: str, grnd_id: int) -> list[str]:
    if len(tra) != 3 or set(tra) - {"0", "1"}:
        raise ValueError(f"Tra 플래그: {tra}")
    return [
        f"/BCS/{int(bid)}", ascii_text(title),
        "#  Tra rot   skew_ID  grnod_ID",
        f"   {tra} 000" + i10(0) + i10(grnd_id),
    ]


def write_cload_inc(path, node_id, f, mask, plan: dict, func_mode: str, ramp_time: float,
                    num_format: str, header_lines) -> dict:
    """비영 성분(mask)마다 /CLOAD 1장. 하중 노드마다 /GRNOD/NODE 1장(노드 1개). 반환 카운트."""
    node_id = np.asarray(node_id, dtype=np.int64)
    f = np.asarray(f, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    loaded = np.flatnonzero(mask.any(axis=1))
    if len(plan["cload_grnod"]) != loaded.size or len(plan["cload"]) != int(mask.sum()):
        raise ValueError("ID 배정 수가 하중 노드·성분 수와 다름")
    L = _comment_header(header_lines)
    L += ["#", _RULER]
    L += funct_card(plan["func"], func_mode, ramp_time, num_format)
    L.append(_RULER)
    k_load = 0
    for k_node, i in enumerate(loaded):
        nid = int(node_id[i])
        gid = plan["cload_grnod"][k_node]
        L += grnod_node_card(gid, f"ESL_N{nid}", [nid])
        for c in range(3):
            if mask[i, c]:
                L += cload_card(plan["cload"][k_load], f"ESL_N{nid}_F{_DIR[c]}", plan["func"], c, gid,
                                f[i, c], num_format)
                k_load += 1
    L.append(_RULER)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return {"n_cload": k_load, "n_grnod": int(loaded.size)}


def write_bcs_inc(path, supports, plan: dict, header_lines) -> dict:
    """supports = [(node_id, dofs '123' 부분집합)] → 노드별 /GRNOD/NODE + /BCS (회전 000)."""
    from esl.export import dof_flags

    if len(plan["bcs_grnod"]) != len(supports) or len(plan["bcs"]) != len(supports):
        raise ValueError("ID 배정 수가 지지 노드 수와 다름")
    L = _comment_header(header_lines)
    L += ["#", _RULER]
    for k, (nid, dofs) in enumerate(supports):
        gid, bid = plan["bcs_grnod"][k], plan["bcs"][k]
        L += grnod_node_card(gid, f"ESL_321_N{int(nid)}", [int(nid)])
        L += bcs_card(bid, f"ESL_321_N{int(nid)}_DOF{dofs}", dof_flags(dofs), gid)
    L.append(_RULER)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return {"n_bcs": len(supports)}
