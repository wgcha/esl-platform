"""내보내기: Radioss inc, OptiStruct .fem, CSV (계약 esl_core.md §5, esl.md §8).

ID 규칙: 생성 ID 는 모두 ``[id_offset, id_offset+999999]``. rad 모델의 같은 종류 최대 ID
(``RadModel.max_ids``)가 ``id_offset`` 이상이면 범위가 겹칠 수 있으므로 ``ID_RANGE_COLLISION``.
(max_ids 는 최대값만 알기 때문에 보수적으로 판정한다.)

배정 순서(결정적, ``id_offset+1`` 부터 연속):
  /FUNCT 1개 → .fem SPC SID → .fem LOAD SID → 3-2-1 /GRNOD n_support개 → /BCS n_support개
  → PSHELL n_pshell개 → /CLOAD 용 /GRNOD(하중 노드 수) → /CLOAD(비영 성분 수)
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

ID_SPAN = 999_999
# 생성 ID 종류 → max_ids 키. (.fem SID 는 Radioss 덱에 들어가지 않으므로 검사 대상 아님)
_CHECK_KEYS = ("func", "grnod", "load", "bcs", "prop")


def plan_ids(id_offset: int, max_ids: dict, n_support: int, n_pshell: int,
             n_load_nodes: int, n_load_comps: int) -> dict:
    off = int(id_offset)
    lo, hi = off, off + ID_SPAN
    hits = {k: int(max_ids.get(k, 0) or 0) for k in _CHECK_KEYS if int(max_ids.get(k, 0) or 0) >= lo}
    if hits:
        raise EslError("ID_RANGE_COLLISION",
                       f"생성 ID 범위 [{lo}, {hi}] 가 rad 기존 ID 와 겹칠 수 있음(최대 ID {hits}) "
                       f"— export.radioss.id_offset 를 더 크게")
    cur = off + 1

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
    last = cur - 1
    if last > hi:
        raise EslError("ID_RANGE_COLLISION",
                       f"생성 ID {last - off}개가 범위 폭 {ID_SPAN} 를 넘음 (하중 노드 {n_load_nodes}, 성분 {n_load_comps})")
    plan["range"] = [lo, hi]
    plan["max_used"] = last
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


__all__ = ["plan_ids", "all_ids", "force_mask", "dof_flags", "ascii_text", "ID_SPAN"]
