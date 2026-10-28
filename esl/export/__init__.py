"""내보내기: Radioss inc, OptiStruct .fem, CSV (계약 esl_core.md §5, esl.md §8).

ID 규칙(0.5.6): 생성 ID 는 ``off+1`` 부터 필요한 개수만큼 연속 배정한다(고정 폭 없음).
``off`` = ``export.radioss.id_offset``: 정수면 그 값, ``auto``(기본)면 ``AUTO_BASE``(9,000,000)에서 시작하되
rad 모델의 같은 종류 최대 ID(``RadModel.max_ids`` 의 func·grnod·load·bcs·prop)가 ``off`` 이상이면
최대 ID 보다 큰 가장 작은 10의 거듭제곱으로 올린다. 정수 지정이 모델 ID 와 겹칠 수 있으면(최대 ID ≥ off+1)
``ID_RANGE_COLLISION``. 마지막 ID 가 Radioss ID 상한(``ID_LIMIT`` = 2^31-1, I10 칸 안)을 넘어도 같은 오류.
(max_ids 는 최대값만 알기 때문에 보수적으로 판정한다.)

배정 순서(결정적, ``off+1`` 부터 연속):
  /FUNCT 1개 → .fem SPC SID → .fem LOAD SID → 3-2-1 /GRNOD n_support개 → /BCS n_support개
  → PSHELL n_pshell개 → /CLOAD 용 /GRNOD(하중 노드 수; 노드의 성분들이 1개 공유) → /CLOAD(비영 성분 수)
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

AUTO_BASE = 9_000_000
ID_LIMIT = 2_147_483_647          # Radioss·OptiStruct 정수 ID 상한(2^31-1, I10 안)
# 생성 ID 종류 → max_ids 키. (.fem SID 는 Radioss 덱에 들어가지 않으므로 검사 대상 아님)
_CHECK_KEYS = ("func", "grnod", "load", "bcs", "prop")


def _pow10_above(v: int) -> int:
    return 10 ** len(str(int(v)))


def plan_ids(id_offset, max_ids: dict, n_support: int, n_pshell: int,
             n_load_nodes: int, n_load_comps: int) -> dict:
    need = 3 + 2 * int(n_support) + int(n_pshell) + int(n_load_nodes) + int(n_load_comps)
    mx = {k: int(max_ids.get(k, 0) or 0) for k in _CHECK_KEYS}
    top = max(mx.values())
    auto = isinstance(id_offset, str)
    if auto:
        if id_offset != "auto":
            raise EslError("CONFIG_INVALID", f"export.radioss.id_offset: 'auto' 또는 정수 (값 {id_offset!r})")
        off = AUTO_BASE if top < AUTO_BASE else _pow10_above(top)
    else:
        off = int(id_offset)
    lo, last = off + 1, off + need
    if last > ID_LIMIT:
        raise EslError("ID_RANGE_COLLISION",
                       f"필요한 생성 ID 범위 [{lo}, {last}] ({need}개; 하중 노드 {n_load_nodes}, 성분 {n_load_comps}) 가 "
                       f"Radioss ID 상한 {ID_LIMIT} 을 넘음 — export.radioss.id_offset 를 더 작게(또는 auto)")
    hits = {k: v for k, v in mx.items() if v >= lo}
    if hits:
        raise EslError("ID_RANGE_COLLISION",
                       f"필요한 생성 ID 범위 [{lo}, {last}] ({need}개) 가 rad 기존 ID 와 겹칠 수 있음(충돌 최대 ID {hits}) "
                       f"— export.radioss.id_offset 를 {_pow10_above(top)} 이상 또는 auto 로")
    cur = lo

    def take(n):
        nonlocal cur
        out = list(range(cur, cur + int(n)))
        cur += int(n)
        return out

    plan = {
        "func": take(1)[0],
        "fem_spc_sid": take(1)[0],
        "fem_load_sid": take(1)[0],
        "bcs_grnod": take(n_support),
        "bcs": take(n_support),
        "pshell": take(n_pshell),
        "cload_grnod": take(n_load_nodes),
        "cload": take(n_load_comps),
    }
    assert cur - 1 == last
    plan["range"] = [lo, last]
    plan["max_used"] = last
    plan["id_offset"] = off
    plan["id_offset_auto"] = auto
    plan["n_ids"] = need
    return plan


def all_ids(plan: dict) -> list[int]:
    out = [plan["func"], plan["fem_spc_sid"], plan["fem_load_sid"]]
    for k in ("bcs_grnod", "bcs", "pshell", "cload_grnod", "cload"):
        out += list(plan[k])
    return out


def force_mask(f, zero_tol_rel: float) -> np.ndarray:
    """(N,3) 비영 성분 마스크: |F_c| > zero_tol_rel·max_i|F_i| (노드 합력 크기 최대 기준)."""
    f = np.asarray(f, dtype=np.float64)
    ref = float(np.max(np.linalg.norm(f, axis=1))) if f.size else 0.0
    if ref == 0.0:
        return np.zeros(f.shape, dtype=bool)
    return np.abs(f) > float(zero_tol_rel) * ref


def ascii_text(s) -> str:
    """inc·fem 주석/title 용 ASCII 전용 문자열(비 ASCII 는 \\uXXXX 로 치환)."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def dof_flags(dofs: str) -> str:
    """'13' → '101' (Tx Ty Tz 순)."""
    return "".join("1" if str(k) in str(dofs) else "0" for k in (1, 2, 3))


__all__ = ["plan_ids", "all_ids", "force_mask", "dof_flags", "ascii_text", "AUTO_BASE", "ID_LIMIT"]
