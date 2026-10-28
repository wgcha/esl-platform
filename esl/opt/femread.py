"""OptiStruct/Nastran ``.fem`` 쉘 메시 읽기·쓰기 (계약 esl_opt_run.md OR-D-9, §7.2).

``read_fem(path) -> dict`` (mesh: node_id·x0·elem_id·elem_type·conn·elem_pid·elem_mid·thickness·E·nu + 정보)

지원 카드: GRID, CQUAD4, CTRIA3, PSHELL, MAT1. 필드 형식:
- 자유 필드(콤마). 연속 줄 = 첫 필드가 ``+``/``*`` 로 시작하거나 빈 필드(줄이 콤마로 시작).
- 소형 고정(8칸) — 1~8열 카드 이름, 9~72열 8필드. 연속 줄 = 1열이 ``+`` 이거나 첫 8칸 공백.
- 대형 고정(16칸) — 카드 이름 끝 ``*``, 9~72열 16칸 4필드. 연속 줄 = 1열 ``*``.
- 실수 축약 ``1.5-3`` = 1.5e-3, ``2.+5`` = 2e5, ``D`` 지수 허용.
- ``BEGIN BULK`` 가 있으면 그 뒤만, 없으면 전체를 bulk 로 본다. ``ENDDATA`` 이후 무시. ``$`` 주석.
- ``INCLUDE`` 는 지원하지 않음 → ``MESH_INVALID``(템플릿은 파일 1개).
- 그 밖 카드는 무시하고 ``unsupported{카드: 수}`` 로 센다(경고). 요소 카드(CQUAD8·CTRIA6·CHEXA 등)도 여기 들어가며
  검사(mesh_check)가 비지원 요소로 오류 처리한다.
- GRID CP(좌표계) ≠ 0 은 지원하지 않음 → ``MESH_INVALID``.
"""
from __future__ import annotations

import os
import re

import numpy as np

from esl.errors import EslError

SUPPORTED = ("GRID", "CQUAD4", "CTRIA3", "PSHELL", "MAT1")
ELEMENT_CARDS = ("CQUAD8", "CQUADR", "CTRIA6", "CTRIAR", "CHEXA", "CPENTA", "CTETRA", "CBAR", "CBEAM", "CROD",
                 "CELAS1", "CELAS2", "CBUSH", "CONM2", "RBE2", "RBE3", "CSHEAR", "CQUAD", "CTRIAX6")
_REAL = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d+)$")


def _err(msg: str) -> EslError:
    return EslError("MESH_INVALID", msg)


def real(s: str, what: str = "") -> float | None:
    s = s.strip()
    if not s:
        return None
    t = s.upper().replace("D", "E")
    try:
        return float(t)
    except ValueError:
        pass
    m = _REAL.match(t)
    if m:
        return float(f"{m.group(1)}E{m.group(2)}")
    raise _err(f"실수 필드를 읽을 수 없음: '{s}' {what}")


def integer(s: str, what: str = "") -> int | None:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            v = float(s)
        except ValueError:
            raise _err(f"정수 필드를 읽을 수 없음: '{s}' {what}") from None
        if v != int(v):
            raise _err(f"정수 필드에 실수: '{s}' {what}") from None
        return int(v)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _split_line(line: str):
    """한 줄 → (형식, 이름, 데이터 필드 목록, 연속 줄인가)."""
    s = line.rstrip("\r\n")
    if "," in s[:80] or "\t" in s:
        f = [x.strip() for x in s.replace("\t", ",").split(",")]
        head = f[0]
        cont = head == "" or head.startswith("+") or head.startswith("*")
        return "free", head.upper(), f[1:], cont
    head = s[:8].strip()
    large = head.endswith("*")
    if s[:1] == "*" or (large and head == "*"):
        flds = [s[8 + 16 * k: 8 + 16 * (k + 1)] for k in range(4)]
        return "large", "*", [x.strip() for x in flds], True
    if s[:1] == "+" or head == "":
        flds = [s[8 + 8 * k: 8 + 8 * (k + 1)] for k in range(8)]
        return "small", "+", [x.strip() for x in flds], True
    if large:
        flds = [s[8 + 16 * k: 8 + 16 * (k + 1)] for k in range(4)]
        return "large", head[:-1].upper(), [x.strip() for x in flds], False
    flds = [s[8 + 8 * k: 8 + 8 * (k + 1)] for k in range(8)]
    return "small", head.upper(), [x.strip() for x in flds], False


def iter_cards(text: str):
    """bulk 카드 (이름, 필드 목록, 줄 번호) 생성. 자유 필드는 첫 줄 8필드 고정 폭으로 맞춘다."""
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().upper().startswith("BEGIN BULK") or ln.strip().upper().startswith("BEGIN,BULK"):
            start = i + 1
            break
    # 계약 §7.2: INCLUDE 는 위치와 무관하게 거부(BEGIN BULK 앞 제어·케이스 구역 포함)
    for i, ln in enumerate(lines[:start]):
        if ln.strip().upper().startswith("INCLUDE"):
            raise _err(f"줄 {i + 1}: INCLUDE 는 지원하지 않음(템플릿 .fem 은 파일 1개)")
    cur = None
    for i in range(start, len(lines)):
        ln = lines[i]
        st = ln.strip()
        if not st or st.startswith("$"):
            continue
        if "$" in ln:
            ln = ln[:ln.index("$")]
        up = st.upper()
        if up.startswith("ENDDATA"):
            break
        if up.startswith("INCLUDE"):
            raise _err(f"줄 {i + 1}: INCLUDE 는 지원하지 않음(템플릿 .fem 은 파일 1개)")
        fmt, name, flds, cont = _split_line(ln)
        if cont:
            if cur is None:
                raise _err(f"줄 {i + 1}: 앞 카드 없는 연속 줄")
            per = 4 if fmt == "large" else 8
            flds = (flds + [""] * per)[:per] if fmt != "free" else (flds + [""] * 8)[:8]
            cur[1].extend(flds)
            continue
        if cur is not None:
            yield cur
        if fmt == "free":
            flds = (flds + [""] * 8)[:8] if len(flds) <= 8 else flds[:8]
        elif fmt == "large":
            flds = (flds + [""] * 4)[:4]
        cur = [name, list(flds), i + 1]
    if cur is not None:
        yield cur


def read_fem(path) -> dict:
    path = os.fspath(path)
    try:
        with open(path, "rb") as fh:
            text = _decode(fh.read())
    except OSError as exc:
        raise _err(f".fem 을 읽을 수 없음: {path}: {exc}") from None
    grids: dict[int, tuple] = {}
    elems: list[tuple] = []
    pshell: dict[int, tuple] = {}
    mat1: dict[int, tuple] = {}
    unsupported: dict[str, int] = {}
    warns: list[str] = []
    for name, f, ln in iter_cards(text):
        w = f"(줄 {ln} {name})"
        f = f + [""] * 16
        if name == "GRID":
            gid = integer(f[0], w)
            cp = integer(f[1], w) or 0
            if gid is None:
                raise _err(f"GRID ID 없음 {w}")
            if cp != 0:
                raise _err(f"GRID {gid}: 좌표계 CP={cp} 는 지원하지 않음 {w}")
            xyz = tuple((real(f[k], w) or 0.0) for k in (2, 3, 4))
            if gid in grids:
                warns.append(f"GRID {gid} 중복 정의 — 마지막 값 사용")
            grids[gid] = xyz
        elif name in ("CQUAD4", "CTRIA3"):
            eid = integer(f[0], w)
            if eid is None:
                raise _err(f"요소 ID 없음 {w}")
            pid = integer(f[1], w)
            nn = 4 if name == "CQUAD4" else 3
            g = [integer(f[2 + k], w) for k in range(nn)]
            if any(x is None for x in g):
                raise _err(f"{name} {eid}: 노드 필드 비어 있음 {w}")
            elems.append((eid, eid if pid is None else pid, nn, g))
        elif name == "PSHELL":
            pid = integer(f[0], w)
            mid = integer(f[1], w)
            t = real(f[2], w)
            pshell[pid] = (mid, t)
        elif name == "MAT1":
            mid = integer(f[0], w)
            E, G, nu, rho = real(f[1], w), real(f[2], w), real(f[3], w), real(f[4], w)
            if E is None and G is not None and nu is not None:
                E = 2.0 * G * (1.0 + nu)
            if nu is None and E is not None and G is not None and G > 0:
                nu = E / (2.0 * G) - 1.0
            mat1[mid] = (E, nu, rho)
        else:
            unsupported[name] = unsupported.get(name, 0) + 1
    if not grids:
        raise _err("GRID 카드가 없음")
    node_id = np.array(sorted(grids), dtype=np.int64)
    x0 = np.array([grids[int(i)] for i in node_id], dtype=np.float64).reshape(-1, 3)
    elems.sort(key=lambda e: e[0])
    eids = np.array([e[0] for e in elems], dtype=np.int64)
    if eids.size > 1 and np.any(np.diff(eids) == 0):
        raise _err(f"중복 요소 ID: {eids[:-1][np.diff(eids) == 0][:5].tolist()}")
    conn = np.full((len(elems), 4), -1, dtype=np.int64)
    et = np.zeros(len(elems), dtype=np.int8)
    pid = np.zeros(len(elems), dtype=np.int64)
    for k, (eid, p, nn, g) in enumerate(elems):
        pos = np.searchsorted(node_id, g)
        pos = np.minimum(pos, node_id.size - 1)
        miss = [gg for gg, pp in zip(g, pos) if node_id[pp] != gg]
        if miss:
            raise _err(f"요소 {eid}: GRID 에 없는 노드 {miss}")
        conn[k, :nn] = pos
        et[k] = nn
        pid[k] = p
    mid = np.zeros(len(elems), dtype=np.int64)
    thk = np.zeros(len(elems))
    E = np.zeros(len(elems))
    nu = np.zeros(len(elems))
    for p in np.unique(pid).tolist():
        if p not in pshell:
            raise _err(f"PSHELL {p} 가 없음(요소가 참조)")
        m, t = pshell[p]
        if t is None:
            raise _err(f"PSHELL {p}: 두께 T 없음")
        if m not in mat1:
            raise _err(f"PSHELL {p}: MAT1 {m} 가 없음")
        Em, num, _ = mat1[m]
        if Em is None or num is None:
            raise _err(f"MAT1 {m}: E·ν 를 해석할 수 없음")
        sel = pid == p
        mid[sel], thk[sel], E[sel], nu[sel] = m, t, Em, num
    used = sorted(set(pid.tolist()))
    mats = [{"id": int(m), "law": "MAT1", "E": mat1[m][0], "nu": mat1[m][1], "rho": mat1[m][2], "source": "fem"}
            for m in sorted({pshell[p][0] for p in used})]
    return {"node_id": node_id, "x0": x0, "elem_id": eids, "elem_type": et, "conn": conn, "elem_pid": pid,
            "elem_mid": mid, "thickness": thk, "E": E, "nu": nu, "mats": mats,
            "pids": [{"pid": int(p), "title": "", "mid": int(pshell[p][0]), "thickness": float(pshell[p][1]),
                      "E": float(mat1[pshell[p][0]][0]), "nu": float(mat1[pshell[p][0]][1]),
                      "n_elems": int(np.sum(pid == p))} for p in used],
            "unsupported": dict(sorted(unsupported.items())), "warnings": warns,
            "max_ids": {"node": int(node_id.max()), "elem": int(eids.max()) if eids.size else 0,
                        "prop": max(pshell) if pshell else 0, "mat": max(mat1) if mat1 else 0},
            "part_title": None, "part_id": None, "format": "fem"}


def _r(v) -> str:
    from esl.library.optdeck import real as _real
    return _real(v)


def write_fem(path, mesh: dict, header: list[str] | None = None) -> str:
    """쉘 메시를 자유 필드 .fem(GRID/CQUAD4/CTRIA3/PSHELL/MAT1)으로. 원 ID·PID·두께·재료 유지.

    (PID, 두께) 가 요소마다 다르면 PID 별 두께 중앙값을 PSHELL 에, 다른 두께는 CQUAD4/CTRIA3 의 T 필드 대신
    (PID, T) 조합마다 새 PSHELL 을 만든다(원 PID 위에 오프셋). MAT1 은 (E, ν) 조합별.
    """
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    eid = np.asarray(mesh["elem_id"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    pid = np.asarray(mesh["elem_pid"], dtype=np.int64)
    ne = eid.size
    t = np.broadcast_to(np.asarray(mesh["thickness"], dtype=np.float64), (ne,))
    E = np.broadcast_to(np.asarray(mesh["E"], dtype=np.float64), (ne,))
    nu = np.broadcast_to(np.asarray(mesh["nu"], dtype=np.float64), (ne,))
    em = mesh.get("elem_mid")
    em = None if em is None else np.broadcast_to(np.asarray(em, dtype=np.int64), (ne,))
    mats, minv = np.unique(np.column_stack([E, nu]), axis=0, return_inverse=True)
    minv = minv.reshape(-1)
    # 원 재료 ID 유지: 재료 조합마다 그 조합을 쓰는 원 MID 가 하나뿐이면 그 ID, 아니면 새 ID
    mids: list[int] = []
    taken: set[int] = set()
    nxt = (int(em.max()) if em is not None and em.size else 0)
    for k in range(len(mats)):
        cand = sorted(set(em[minv == k].tolist())) if em is not None else []
        if len(cand) == 1 and cand[0] > 0 and cand[0] not in taken:
            mids.append(int(cand[0]))
        else:
            nxt += 1
            mids.append(nxt)
        taken.add(mids[-1])
    groups, ginv = np.unique(np.column_stack([pid.astype(np.float64), t, minv.astype(np.float64)]), axis=0,
                             return_inverse=True)
    ginv = ginv.reshape(-1)
    gp: list[int] = []
    used = set()
    off = int(pid.max()) if pid.size else 0
    for k in range(len(groups)):
        p = int(groups[k, 0])
        if p in used:
            off += 1
            p = off
        used.add(p)
        gp.append(p)
    L = [f"$ {x}" for x in (header or [])]
    L.append("BEGIN BULK")
    for i in range(nid.size):
        L.append(f"GRID,{int(nid[i])},,{_r(X[i, 0])},{_r(X[i, 1])},{_r(X[i, 2])}")
    for e in range(ne):
        n = [str(int(nid[c])) for c in conn[e, :et[e]]]
        L.append(f"{'CQUAD4' if et[e] == 4 else 'CTRIA3'},{int(eid[e])},{gp[int(ginv[e])]}," + ",".join(n))
    for k in range(len(groups)):
        L.append(f"PSHELL,{gp[k]},{mids[int(groups[k, 2])]},{_r(groups[k, 1])},{mids[int(groups[k, 2])]},,"
                 f"{mids[int(groups[k, 2])]}")
    for k, (e_, nu_) in enumerate(mats):
        L.append(f"MAT1,{mids[k]},{_r(e_)},,{_r(nu_)}")
    L.append("ENDDATA")
    path = os.fspath(path)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return path
