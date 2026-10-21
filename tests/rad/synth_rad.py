"""시험용 합성 Radioss starter 생성기(대형·여러 파트·include 중첩·주석·빈 행·CRLF·서식 변형).

``make_model(dir, n_elems, ...)`` → (rad 경로, 대상 파트 title). 대상 파트 = part 1(요소 ``target_frac``).
"""

from __future__ import annotations

import math
import os

import numpy as np


def _i10(v: int, left: bool = False) -> str:
    s = str(int(v))
    return s.ljust(10) if left else s.rjust(10)


def _f20(v: float, style: int = 0) -> str:
    if style == 1:
        s = f"{v:.12E}".replace("E", "D")          # Fortran D 지수
    elif style == 2:
        s = f"{v:.6f}".ljust(20)                     # 왼쪽 정렬
        return s[:20]
    else:
        s = repr(float(v))
    return s.rjust(20)[:20] if len(s) <= 20 else f"{v:.10E}".rjust(20)


def _node_lines(ids, xyz, rng, fancy: bool) -> list[str]:
    out = []
    for k, (nid, p) in enumerate(zip(ids.tolist(), xyz.tolist())):
        st = int(rng.integers(0, 3)) if fancy else 0
        out.append(_i10(nid) + "".join(_f20(c, st) for c in p))
        if fancy and k % 997 == 13:
            out.append("#  주석 노드 행")
        if fancy and k % 1999 == 7:
            out.append("")
    return out


def _shell_lines(kw, eids, conn, thk, fancy: bool, rng) -> list[str]:
    out = []
    for k, (e, c) in enumerate(zip(eids.tolist(), conn.tolist())):
        left = fancy and k % 5 == 1
        if kw == "SHELL":
            s = _i10(e, left) + "".join(_i10(v, left) for v in c[:3])
            n4 = c[3]
            s += _i10(n4, left) if n4 > 0 else (" " * 10 if k % 2 else _i10(c[2]))
        else:
            s = _i10(e, left) + "".join(_i10(v, left) for v in c[:3])
        if thk is not None and k % 3 == 0:
            s = s.ljust(60) + _f20(0.0) + _f20(float(thk[k]), int(rng.integers(0, 3)) if fancy else 0)
        out.append(s)
        if fancy and k % 1009 == 5:
            out.append("##---- 주석 ----")
        if fancy and k % 2003 == 11:
            out.append("   ")
    return out


def make_model(d, n_elems: int, n_parts: int = 6, target_frac: float = 0.2, nodes: str = "before",
               fancy: bool = True, crlf: bool = False, seed: int = 0, title: str = "Chassis_Rear"):
    """nodes: 'before'(노드 블록이 요소 앞) | 'after'(뒤) | 'split'(앞뒤로 나눔, 일부 중복 정의)."""
    d = os.fspath(d)
    os.makedirs(os.path.join(d, "inc", "deep"), exist_ok=True)
    rng = np.random.default_rng(seed)
    nq = max(4, int(math.ceil(math.sqrt(n_elems))) + 1)
    gi, gj = np.meshgrid(np.arange(nq), np.arange(nq), indexing="ij")
    n_nodes = nq * nq
    node_ids = 1000 + np.arange(n_nodes, dtype=np.int64) * 3          # 띄엄띄엄 ID
    xyz = np.stack([gi.ravel() * 1.25, gj.ravel() * 0.75, rng.normal(size=n_nodes) * 0.01], axis=1)
    # 요소: 격자 쿼드(일부 삼각형)
    ii, jj = np.meshgrid(np.arange(nq - 1), np.arange(nq - 1), indexing="ij")
    base = (ii * nq + jj).ravel()[:n_elems]
    conn_idx = np.stack([base, base + nq, base + nq + 1, base + 1], axis=1)
    conn = node_ids[conn_idx]
    tri = rng.random(conn.shape[0]) < 0.1
    conn[tri, 3] = 0
    ne = conn.shape[0]
    eids = 5_000_000 + rng.permutation(ne).astype(np.int64)
    thk = np.round(rng.uniform(0.5, 3.0, ne), 3)
    # 파트 배정: 대상(part 1) target_frac, 나머지 균등
    n_t = int(ne * target_frac)
    part = np.empty(ne, dtype=np.int64)
    # 대상 파트는 격자에서 연속된 영역(실모델처럼 참조 노드가 일부), 나머지는 섞어서 배정
    part[:n_t] = 1
    rest = n_t + rng.permutation(ne - n_t)
    part[rest] = 2 + (np.arange(rest.size) % (n_parts - 1))
    # 대상 파트가 참조하는 노드는 전체 노드의 일부 → 나머지는 미사용 노드

    nl = "\r\n" if crlf else "\n"

    def wfile(rel, lines):
        with open(os.path.join(d, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(nl.join(lines) + nl)

    # 노드 분할
    dup = rng.choice(n_nodes, size=max(1, n_nodes // 50), replace=False)
    if nodes == "before":
        node_first, node_last = np.arange(n_nodes), np.arange(0)
    elif nodes == "after":
        node_first, node_last = np.arange(0), np.arange(n_nodes)
    else:
        half = n_nodes // 2
        node_first, node_last = np.arange(half), np.arange(half, n_nodes)

    def node_block(idx, unit=None, shift=0.0):
        if idx.size == 0:
            return []
        hdr = "/NODE" + (f"/{unit}" if unit else "")
        return [hdr, "#  node_ID                  Xc                  Yc                  Zc"] + \
            _node_lines(node_ids[idx], xyz[idx] + shift, rng, fancy)

    def elem_blocks(sel_mask):
        out = []
        for pid in range(1, n_parts + 1):
            m = sel_mask & (part == pid)
            if not m.any():
                continue
            even = np.arange(ne) % 2 == 0
            q = m & (~tri | even)
            t = m & tri & ~even
            # 쿼드 블록을 두 조각으로 나눠 다른 블록 사이에 끼움
            qi = np.where(q)[0]
            for chunk in np.array_split(qi, 2):
                if chunk.size:
                    out += [f"/SHELL/{pid}", "#shell_ID  node_ID1  node_ID2  node_ID3  node_ID4"]
                    out += _shell_lines("SHELL", eids[chunk], conn[chunk], thk[chunk], fancy, rng)
            ti = np.where(t)[0]
            if ti.size:
                out += [f"/SH3N/{pid}", "#sh3n_ID  node_ID1  node_ID2  node_ID3"]
                out += _shell_lines("SH3N", eids[ti], conn[ti], thk[ti], fancy, rng)
        return out

    half_e = np.zeros(ne, dtype=bool)
    half_e[: ne // 2] = True
    # deep.inc: 요소 뒤쪽 절반 + (nodes='after'|'split') 노드 뒤쪽
    deep = elem_blocks(~half_e)
    deep += ["/BRICK/3", "   9999901      1000      1003      1006      1009      1012      1015      1018      1021"]
    deep += node_block(node_last, unit=7 if nodes == "split" else None)
    if nodes == "split":
        deep += ["/NODE"] + _node_lines(node_ids[dup], xyz[dup] + 0.5, rng, False)  # 뒤 정의 우선
    deep += ["/GRNOD/NODE/77", "grp"] + [_i10(v) for v in node_ids[:50].tolist()]
    wfile(os.path.join("inc", "deep", "deep.inc"), deep)
    # mid.inc: 요소 앞 절반, deep 포함(경로가 다음 비주석 행)
    mid = ["# mid include"] + elem_blocks(half_e) + ["/INCLUDE", "# 경로는 다음 행", "", "deep/deep.inc"]
    wfile(os.path.join("inc", "mid.inc"), mid)

    main = ["#RADIOSS STARTER", "/BEGIN", "synth", "      2022         0",
            "                  Mg                  mm                   s",
            "                  Mg                  mm                   s"]
    main += node_block(node_first)
    for pid in range(1, n_parts + 1):
        t = title if pid == 1 else (f"기타 파트 {pid}" if pid == 2 else f"other part {pid}")
        main += [f"/PART/{pid}", t, "#  prop_ID    mat_ID subset_ID",
                 _i10(10 + (pid % 3)) + _i10(20 + (pid % 4)) + _i10(0)]
    main += ["/PART/99", "brick part", _i10(10) + _i10(20) + _i10(0)]
    main += ['#include "inc/mid.inc"']
    for k in range(3):
        main += [f"/PROP/SHELL/{10 + k}", f"prop{k}", "        24", "#Hm..", "",
                 "#        N                         Thick", _i10(5) + " " * 10 + _f20(1.0 + k)]
    laws = ["ELAST", "LAW2", "LAW36", "PLAS_JOHNS"]
    for k in range(4):
        main += [f"/MAT/{laws[k]}/{20 + k}", f"mat{k}", _f20(7.85e-9), _f20(2.1e5 - k * 1000) + _f20(0.3)]
    main += ["/FUNCT/5", "f", _f20(0.0) + _f20(0.0), "/END"]
    rad = os.path.join(d, "synth_0000.rad")
    wfile("synth_0000.rad", main)
    return rad, title
