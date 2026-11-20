"""쉘·솔리드 요소 카드의 코너 노드·솔리드 면 계산 순수 부분 (v0.24.4 이동 — 원래 ``esl/doe/assem_full.py``, 계약
esl_jig_case.md §4.1·D-0.24.4-JIG-10).

paicad 스캔 사본(``esl.doe.assem_full``)과 지그 deck 표면 읽기(``esl.rad.surface``)가 함께 쓴다 — Case 파이프라인이
``esl.doe`` 를 import 하지 않게 여기에 둔다. 파일 IO·설정 해석 없음(산술·정규식만). 옛 이름은 ``esl.doe.assem_full`` 이
같은 객체로 재수출한다.
"""
from __future__ import annotations

import re

import numpy as np

# 요소 키워드 → 읽을 코너 노드 수, 솔리드 면(코너 로컬 번호, 삼각면은 3개)
ELEM_NODES = {"SHELL": 4, "SH3N": 3, "BRICK": 8, "BRIC20": 8, "TETRA4": 4, "TETRA10": 4, "PENTA6": 6}
ELEM_TOTAL = {"SHELL": 4, "SH3N": 3, "BRICK": 8, "BRIC20": 20, "TETRA4": 4, "TETRA10": 10, "PENTA6": 6}  # 카드 노드 칸 수
SHELL_KW = ("SHELL", "SH3N")
_HEX = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
_TET = [(0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)]
_PEN = [(0, 1, 2), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]
SOLID_FACES = {"BRICK": _HEX, "BRIC20": _HEX, "TETRA4": _TET, "TETRA10": _TET, "PENTA6": _PEN}


def _lead_ints(line: str, n: int) -> list[int] | None:
    """줄 앞쪽 정수 칸 최대 n 개: 10칸 고정폭(빈칸 = 0, 줄 길이까지) 또는 자유 형식 토큰. 정수가 아니면 None.
    뒤쪽 칸(실수 phi·thick 등)은 읽지 않는다."""
    body = line.rstrip()
    m = min(n, (len(body) + 9) // 10)
    try:
        vals = [int(t) if (t := body[k * 10:(k + 1) * 10].strip()) else 0 for k in range(m)]
        if vals and vals[0] != 0:
            return vals
    except ValueError:
        pass
    toks = re.findall(r"[^\s,]+", line)[:n]
    try:
        return [int(t) for t in toks]
    except ValueError:
        return None


def _faces(conn: np.ndarray, faces) -> np.ndarray:
    """(m, k) 연결 → (m·f, 4) 면(삼각면 n4 = n3)."""
    out = []
    for f in faces:
        q = conn[:, list(f) + ([f[2]] if len(f) == 3 else [])]
        out.append(q)
    return np.concatenate(out, axis=0) if out else np.zeros((0, 4), np.int64)


def _clean(F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """면 → (정리된 면(겹친 노드 제거, 삼각 n4 = n3), 정렬 키(m, 4; 삼각은 -1 채움)). 고유 노드 < 3 면 제외."""
    s = np.sort(F, axis=1)
    dup = np.zeros_like(s, dtype=bool)
    dup[:, 1:] = s[:, 1:] == s[:, :-1]
    s = np.where(dup | (s <= 0), -1, s)
    nu = (s > 0).sum(axis=1)
    ok = nu >= 3
    F, s, nu = F[ok], np.sort(s[ok], axis=1), nu[ok]
    G = F.copy()
    tri = nu == 3
    if np.any(tri):                         # 삼각면: 원래 순서의 고유 노드 3개 + n4 = n3
        for r in np.flatnonzero(tri):
            u = list(dict.fromkeys(int(x) for x in F[r] if x > 0))
            G[r] = u[:3] + [u[2]]
    return G, s
