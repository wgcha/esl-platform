"""OptiStruct 자유형식(콤마) 덱 esl_force.fem (계약 esl_core.md §5, esl.md §7).

구성: SUBCASE(SPC/LOAD, DISPLACEMENT·SPCFORCE·STRAIN 출력) / BEGIN BULK /
GRID, CQUAD4·CTRIA3(노드·요소 = Radioss ID 그대로), (원 PID, 두께) 조합별 PSHELL(PID 는 생성 ID),
MAT1(MID = Radioss MID), FORCE(전 노드 비영, 작은 성분 0), SPC1(3-2-1, 노드별 1줄) / ENDDATA.

※ 확신 없는 부분: 자유형식 필드 길이. ``{:.9E}`` 음수는 17자(-1.234567890E+03)로 고전 Nastran 의
   8자 제한을 넘는다. OptiStruct 는 자유형식에서 긴 필드를 읽는 것으로 알고 있으나 실행 검증 미수행.
"""
from __future__ import annotations

import numpy as np

from esl.export import ascii_text


def pshell_groups(elem_pid, thickness):
    """(원 PID, 두께) 고유 조합(정렬) 과 요소별 그룹 번호."""
    keys = np.column_stack([np.asarray(elem_pid, dtype=np.float64), np.asarray(thickness, dtype=np.float64)])
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    return [(int(p), float(t)) for p, t in uniq], inv.reshape(-1)


def write_force_fem(path, model, f, mask, supports, plan: dict, num_format: str, header_lines) -> dict:
    """model: node_id, x0, elem_id, elem_type, conn(행 인덱스), elem_pid, thickness, mats[0]{id,E,nu}.

    supports = [(node_id, dofs)], mask = (N,3) 비영 성분.
    """
    g = num_format.format
    node_id = np.asarray(model.node_id, dtype=np.int64)
    x0 = np.asarray(model.x0, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    groups, ginv = pshell_groups(model.elem_pid, model.thickness)
    if len(plan["pshell"]) != len(groups):
        raise ValueError("PSHELL ID 배정 수가 (PID, 두께) 조합 수와 다름")
    mat = model.mats[0]
    mid = int(mat["id"])
    spc, load = plan["fem_spc_sid"], plan["fem_load_sid"]

    L = [f"$ {ascii_text(ln)}" if ln else "$" for ln in header_lines]
    L += [
        "SUBCASE 1",
        "  LABEL ESL_FORCE",
        f"  SPC = {spc}",
        f"  LOAD = {load}",
        "  DISPLACEMENT(H3D,PUNCH) = ALL",
        "  SPCFORCE(H3D,PUNCH) = ALL",
        "  STRAIN(H3D) = ALL",
        "BEGIN BULK",
        "$ ---- GRID (Radioss node ID)",
    ]
    for i in range(node_id.size):
        L.append(f"GRID,{int(node_id[i])},,{g(x0[i, 0])},{g(x0[i, 1])},{g(x0[i, 2])}")
    L.append("$ ---- elements (Radioss element ID), PID = generated ID per (Radioss PID, thickness)")
    conn = np.asarray(model.conn, dtype=np.int64)
    et = np.asarray(model.elem_type).astype(int)
    for e in range(conn.shape[0]):
        pid = plan["pshell"][int(ginv[e])]
        n = [int(node_id[c]) for c in conn[e, :et[e]]]
        card = "CQUAD4" if et[e] == 4 else "CTRIA3"
        L.append(f"{card},{int(model.elem_id[e])},{pid}," + ",".join(str(v) for v in n))
    L.append("$ ---- PSHELL: generated PID <- (Radioss PID, thickness)")
    for k, (opid, t) in enumerate(groups):
        L.append(f"$ PSHELL {plan['pshell'][k]} <- Radioss PID {opid}, T={g(t)}")
        L.append(f"PSHELL,{plan['pshell'][k]},{mid},{g(t)},{mid},,{mid}")
    L.append(f"MAT1,{mid},{g(mat['E'])},,{g(mat['nu'])}")
    L.append("$ ---- FORCE (F_eq, external force applied to the structure)")
    n_force = 0
    for i in np.flatnonzero(mask.any(axis=1)):
        fx, fy, fz = (f[i, c] if mask[i, c] else 0.0 for c in range(3))
        L.append(f"FORCE,{load},{int(node_id[i])},0,{g(1.0)},{g(fx)},{g(fy)},{g(fz)}")
        n_force += 1
    L.append("$ ---- SPC1 (3-2-1 statically determinate supports)")
    for nid, dofs in supports:
        L.append(f"SPC1,{spc},{dofs},{int(nid)}")
    L.append("ENDDATA")
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return {"n_grid": int(node_id.size), "n_elem": int(conn.shape[0]), "n_pshell": len(groups),
            "n_force": n_force, "n_spc1": len(supports),
            "pshell_map": [{"pid": plan["pshell"][k], "rad_pid": p, "t": t} for k, (p, t) in enumerate(groups)]}
