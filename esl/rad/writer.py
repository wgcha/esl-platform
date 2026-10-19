"""합성 Radioss starter 생성기(시험·E2E 용). ``parse_rad`` 와 왕복 일치.

열 레이아웃은 parser.py 머리 주석과 같다(I10 / F20).
"""

from __future__ import annotations

import os

import numpy as np

_RULER = "#---1----|----2----|----3----|----4----|----5----|----6----|----7----|----8----|----9----|---10----|"


def _r20(x: float) -> str:
    """F20 필드. 짧은 repr 이 들어가면 그대로(정확 왕복), 아니면 유효 14자리."""
    x = float(x)
    s = repr(x)
    if len(s) > 20 or "inf" in s or "nan" in s:
        s = f"{x:.13E}"
    if len(s) > 20:
        raise ValueError(f"F20 필드에 들어가지 않는 값: {x}")
    return s.rjust(20)


def _i10(v: int) -> str:
    s = str(int(v))
    if len(s) > 10:
        raise ValueError(f"I10 필드에 들어가지 않는 값: {v}")
    return s.rjust(10)


def _mat_law1(mid: int, title: str, rho: float, E: float, nu: float) -> list[str]:
    return [
        f"/MAT/LAW1/{int(mid)}", title,
        "#              RHO_I", _r20(rho),
        "#                  E                  nu", _r20(E) + _r20(nu),
        _RULER,
    ]


def _prop_shell(pid: int, title: str, thick: float) -> list[str]:
    return [
        f"/PROP/SHELL/{int(pid)}", title,
        "#   Ishell    Ismstr     Ish3n    Idrill    Ipinch                  P_Thick_Fail",
        _i10(24) + _i10(0),
        "#                 Hm                  Hf                  Hr                  Dm                  Dn",
        "",
        "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
        _i10(5) + _i10(0) + _r20(thick) + " " * 20 + " " * 10 + _i10(1) + _i10(1),
        _RULER,
    ]


def _part(part_id: int, title: str, pid: int, mid: int) -> list[str]:
    return [
        f"/PART/{int(part_id)}", "#part_title", title,
        "#  prop_ID    mat_ID subset_ID               Thick",
        _i10(pid) + _i10(mid) + _i10(0),
        _RULER,
    ]


def _shell_rows(eids, etypes, conn_ids, thk) -> tuple[list[str], list[str]]:
    q, t = [], []
    for k in range(len(eids)):
        th = "" if thk is None else " " * 10 + " " * 20 + _r20(thk[k])
        if int(etypes[k]) == 4:
            q.append(_i10(eids[k]) + "".join(_i10(n) for n in conn_ids[k][:4]) + th)
        else:
            t.append(_i10(eids[k]) + "".join(_i10(n) for n in conn_ids[k][:3]) + (" " * 10 + th if th else ""))
    return q, t


def write_rad(path, node_id, x0, elem_id, elem_type, conn_ids, part_id, part_title, pid, thickness,
              mid, E, nu, rho=7.85e-9, extra_parts=0) -> str:
    """대상 쉘 파트 1개(+ 더미 파트 ``extra_parts`` 개)를 담은 rad 파일을 쓴다.

    - ``conn_ids``: (E,4) 노드 **ID**, TRIA 의 4번째는 -1 또는 0.
    - ``elem_type``: 3=TRIA(/SH3N), 4=QUAD(/SHELL).
    - ``thickness``: 스칼라면 /PROP/SHELL Thick 만, (E,) 배열이고 값이 다르면 요소 카드 Thick 에 기록.
    - 재료는 /MAT/LAW1. 더미 파트는 새 노드 4개·쿼드 1개씩, ID 는 대상보다 큼.
    반환: 쓴 경로.
    """
    node_id = np.asarray(node_id, dtype=np.int64)
    x0 = np.asarray(x0, dtype=np.float64).reshape(-1, 3)
    elem_id = np.asarray(elem_id, dtype=np.int64)
    elem_type = np.asarray(elem_type).astype(int)
    conn_ids = np.asarray(conn_ids, dtype=np.int64).reshape(-1, 4)
    th = np.asarray(thickness, dtype=np.float64)
    if th.ndim == 0:
        prop_thk, elem_thk = float(th), None
    else:
        th = th.reshape(-1)
        if np.all(th == th[0]):
            prop_thk, elem_thk = float(th[0]), None
        else:
            prop_thk, elem_thk = float(np.median(th)), th

    L: list[str] = [
        "#RADIOSS STARTER",
        "# ESL 합성 rad (esl.rad.writer)",
        "/BEGIN",
        "#Runname",
        "esl_synthetic",
        "#   Invers      Irun",
        _i10(2024) + _i10(0),
        "#    Input_mass_unit   Input_length_unit     Input_time_unit",
        "Mg".rjust(20) + "mm".rjust(20) + "s".rjust(20),
        "#     Work_mass_unit    Work_length_unit      Work_time_unit",
        "Mg".rjust(20) + "mm".rjust(20) + "s".rjust(20),
        _RULER,
        "/NODE",
        "#  node_ID                  Xc                  Yc                  Zc",
    ]
    for k in range(node_id.size):
        L.append(_i10(node_id[k]) + _r20(x0[k, 0]) + _r20(x0[k, 1]) + _r20(x0[k, 2]))

    # 더미 파트용 노드
    extra = []
    nmax = int(node_id.max()) if node_id.size else 0
    emax = int(elem_id.max()) if elem_id.size else 0
    ext = (x0.max(axis=0) if x0.size else np.zeros(3))
    for j in range(int(extra_parts)):
        base = nmax + 4 * j
        nids = [base + 1, base + 2, base + 3, base + 4]
        ox = float(ext[0]) + 10.0 * (j + 1)
        pts = [(ox, 0.0, 0.0), (ox + 1.0, 0.0, 0.0), (ox + 1.0, 1.0, 0.0), (ox, 1.0, 0.0)]
        for n, p in zip(nids, pts):
            L.append(_i10(n) + _r20(p[0]) + _r20(p[1]) + _r20(p[2]))
        extra.append((int(part_id) + j + 1, f"extra_part_{j + 1}", int(pid) + j + 1, int(mid) + j + 1,
                      emax + j + 1, nids))
    L.append(_RULER)

    L += _mat_law1(mid, f"mat_{int(mid)}", rho, E, nu)
    L += _prop_shell(pid, f"prop_{int(pid)}", prop_thk)
    L += _part(part_id, part_title, pid, mid)
    q, t = _shell_rows(elem_id, elem_type, conn_ids, elem_thk)
    hdr = "#shell_ID  node_ID1  node_ID2  node_ID3  node_ID4                           Phi               Thick"
    if q:
        L += [f"/SHELL/{int(part_id)}", hdr] + q + [_RULER]
    if t:
        L += [f"/SH3N/{int(part_id)}",
              "# sh3n_ID  node_ID1  node_ID2  node_ID3                                     Phi               Thick"] + t + [_RULER]

    for (xpart, xtitle, xpid, xmid, xeid, nids) in extra:
        L += _mat_law1(xmid, f"mat_{xmid}", rho, E, nu)
        L += _prop_shell(xpid, f"prop_{xpid}", prop_thk)
        L += _part(xpart, xtitle, xpid, xmid)
        L += [f"/SHELL/{xpart}", hdr, _i10(xeid) + "".join(_i10(n) for n in nids), _RULER]
    L.append("/END")

    path = os.fspath(path)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path
