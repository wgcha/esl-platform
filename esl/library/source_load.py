"""하위 작업 하중 출처 찾기 — 스터디(``esl.doe.stages._ns_find``)·비드 최적화(워커 OPT_LOAD·OPT_PREP) 공용
(계약 docs/contracts/esl_jig_case.md §9, 결정 D-0.24.4-JIG-14·D-0.24.3-VAL-16).

``find(key, meta, raw) -> (dir | None, doc | None, f | None, bc | None, why)``

- 출처 이름으로 분기하지 않는다: 이 모듈의 표 ``SOURCES``(열 accept·code·hint) + ``esl.view3d_src.CASE_PLAN``(열 load·doc·support)만 읽는다.
  accept 열 — ``raw`` = 엔트리 자신의 하중(라이브러리 raw ``f`` = 전 노드 ESL F_eq, Case 탐색 없음 — dir·doc None),
  ``grade`` = Case 진단 json 의 grade ∉ (None, "none")(경계력·내력), ``status`` = Case 진단 json status "ok"(지그 3방식).
- 탐색(스터디 ``_ns_find`` 와 같은 순서·조건 — 그 함수가 이 함수를 부르므로 스터디 산출물 바이트 동일): 엔트리 스냅샷 04_esl → 같은 Case
  ``runs/*/04_esl``(하중 npz mtime 최근순) → Case ``04_esl``. 후보 조건 = ``u_rel.npz`` 의 노드 ID 가 같고 값이 1e-9 상대로 같음.
- ``f`` = 하중 npz ``f``(엔트리 raw 노드 순서 (N,3) — 같은 노드 ID 확인), ``bc`` = CASE_PLAN support 열이 ``jig`` 인 행만:
  npz 구속 배열에서 **bc_node·sp_node 를 노드 ID** 로 바꾼 사전(bc_dir·bc_val·bc_kind·sp_dir·sp_k·sp_g 그대로), 그 밖 None.
- ``why`` = 없음 사유 ``"<코드>: <문구>"``(찾으면 빈 문자열).

import = numpy · esl.errors · esl.library._util · esl.view3d_src(가벼움 — 백엔드 API 프로세스에서도 scipy 를 끌지 않음).
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from esl import view3d_src as v3s
from esl.errors import EslError
from esl.library import _util as U

_HINT_ESL = "Case 에서 h3d 추출(v0.24.0)·ESL 을 다시 실행"
_HINT_JIG = "Case ③ ESL 을 다시 계산(v0.24.4 — 지그 tie 준비 포함)"
# 출처 표(열만 읽음 — 행 = view3d_src.KEYS 와 같은 키). accept = 찾은 결과 판정, code = 없음 사유 코드 접두, hint = 사유 문구 끝(해결 방법)
SOURCES: dict[str, dict[str, str]] = {
    "jig": {"accept": "status", "code": "JIG", "hint": _HINT_JIG},
    "jig_disp": {"accept": "status", "code": "JIG", "hint": _HINT_JIG},
    "jig_spring": {"accept": "status", "code": "JIG", "hint": _HINT_JIG},
    "full": {"accept": "raw", "code": "ESL", "hint": _HINT_ESL},
    "bforce": {"accept": "grade", "code": "BF", "hint": _HINT_ESL},
    "fint": {"accept": "grade", "code": "FINT", "hint": _HINT_ESL},
}
ACCEPT = ("raw", "grade", "status")
BC_ID_KEYS = ("bc_node", "sp_node")
BC_KEYS = ("bc_node", "bc_dir", "bc_val", "bc_kind", "sp_node", "sp_dir", "sp_k", "sp_g")


def _plan_row(key: str) -> dict[str, Any]:
    for r in v3s.CASE_PLAN:
        if r["key"] == key:
            return r
    raise EslError("INPUT_INVALID", f"모르는 하중 출처: {key!r} — {list(v3s.KEYS)}")


def check_plan() -> None:
    """표 키 = view3d_src.KEYS, 모든 열 채움·accept 허용 값(빈 칸·모르는 값 = CONFIG_INVALID)."""
    if tuple(SOURCES) != tuple(v3s.KEYS):
        raise EslError("CONFIG_INVALID", f"source_load.SOURCES 키 {tuple(SOURCES)} ≠ view3d_src.KEYS {v3s.KEYS}")
    for k, row in SOURCES.items():
        if any(not row.get(c) for c in ("accept", "code", "hint")) or row["accept"] not in ACCEPT:
            raise EslError("CONFIG_INVALID", f"source_load.SOURCES[{k}] 열 오류 {row}")


def row(key: str) -> dict[str, Any]:
    """출처 키 → 표 행 + 파일 이름(CASE_PLAN load·doc)·support 열."""
    if key not in SOURCES:
        raise EslError("INPUT_INVALID", f"모르는 하중 출처: {key!r} — {list(SOURCES)}")
    p = _plan_row(key)
    return {"key": key, **SOURCES[key], "npz": p["load"][1], "npz_key": p["load"][2],
            "json": None if p["doc"] is None else p["doc"][1], "support": p["support"]}


def _name(key: str) -> str:
    from esl.val_src import LABEL  # 화면 이름 원본 한 곳(지연 import)
    return str(LABEL.get(key, key))


def _accepted(rw: dict, jd: Any) -> bool:
    if not isinstance(jd, dict):
        return False
    if rw["accept"] == "grade":
        return jd.get("grade") not in (None, "none")
    return jd.get("status") == "ok"


def _bc_ids(z, node_id) -> dict[str, np.ndarray]:
    """npz 구속 배열(노드 인덱스) → 노드 ID 사전(없는 키 = 길이 0)."""
    nid = np.asarray(node_id, dtype=np.int64)
    out: dict[str, np.ndarray] = {}
    for k in BC_KEYS:
        a = np.asarray(z[k]) if k in z else np.zeros(0)
        if k in BC_ID_KEYS:
            out[k] = nid[np.asarray(a, dtype=np.int64).reshape(-1)]
        elif k in ("bc_dir", "sp_dir"):
            out[k] = np.asarray(a, dtype=np.float64).reshape(-1, 3)
        elif k == "bc_kind":
            out[k] = np.asarray(a, dtype=np.int8).reshape(-1)
        else:
            out[k] = np.asarray(a, dtype=np.float64).reshape(-1)
    return out


def _load_f(path: str, npz_key: str, raw_node_id) -> tuple[np.ndarray, Any]:
    z = U.load_npz(path)
    f = np.asarray(z[npz_key], dtype=np.float64)
    want = np.asarray(raw_node_id, dtype=np.int64)
    have = np.asarray(z["node_id"], dtype=np.int64) if "node_id" in z else want
    if not np.array_equal(have, want):                       # 엔트리 raw 노드 순서로(같은 노드 집합이어야 함)
        o = np.argsort(have)
        pos = o[np.searchsorted(have, want, sorter=o).clip(0, max(have.size - 1, 0))]
        if have.size == 0 or not np.array_equal(have[pos], want):
            raise EslError("MODEL_MISMATCH", f"출처 하중 노드 ID 가 엔트리와 다름: {os.path.basename(path)}")
        f = f[pos]
    return f, z


def find(key: str, meta: dict, raw: dict, *, code: str | None = None, name: str | None = None, load: bool = True):
    """엔트리(meta·raw)의 출처 하중 → (04_esl 폴더 | None, 진단 json | None, f (N,3) | None, bc | None, 사유).

    code·name = 사유 문구의 코드 접두·출처 이름(기본 = 표 code·val_src.LABEL — 스터디는 자기 표 값을 넘겨 문구 바이트 동일).
    load = False 이면 f·bc 를 읽지 않음(None — 스터디 탐색만). 찾지 못함 = (None, 마지막 진단 json | None, None, None, 사유)."""
    rw = row(key)
    if rw["accept"] == "raw":                                # 엔트리 자신(전 노드 ESL) — Case 탐색 없음(비드 최적화 지금 동작 그대로)
        f = np.asarray(raw["f"], dtype=np.float64).copy() if load else None
        return None, None, f, None, ""
    code = code or rw["code"]
    name = name or _name(key)
    fj, fz = rw["json"], rw["npz"]
    src = meta.get("source") or {}
    cd = src.get("case_dir")
    cands = []
    if src.get("snapshot_dir"):
        cands.append(os.path.join(src["snapshot_dir"], "04_esl"))
    if cd and os.path.isdir(os.path.join(cd, "runs")):
        rs = [os.path.join(cd, "runs", r, "04_esl") for r in sorted(os.listdir(os.path.join(cd, "runs")))]
        rs = [d for d in rs if os.path.isfile(os.path.join(d, fz))]
        cands += sorted(rs, key=lambda d: os.path.getmtime(os.path.join(d, fz)), reverse=True)
    if cd:
        cands.append(os.path.join(cd, "04_esl"))
    nid = np.asarray(raw["node_id"], dtype=np.int64)
    ur = np.asarray(raw["u_rel"], dtype=np.float64)
    tol = 1e-9 * max(float(np.abs(ur).max()) if ur.size else 0.0, 1e-30)
    why, jd_none = f"{code}_NOT_FOUND: Case 에 {name} 결과가 없음 — {rw['hint']}", None
    seen = set()
    for d in cands:
        if d in seen or not os.path.isdir(d):
            continue
        seen.add(d)
        try:
            uz = U.load_npz(os.path.join(d, "u_rel.npz"))
            if not np.array_equal(np.asarray(uz["node_id"], dtype=np.int64), nid) or \
                    not np.allclose(np.asarray(uz["u_rel"], dtype=np.float64), ur, rtol=0.0, atol=tol):
                continue
            jp = os.path.join(d, fj)
            jd = U.read_json(jp) if os.path.isfile(jp) else None
        except (EslError, OSError, KeyError, ValueError):
            continue
        if os.path.isfile(os.path.join(d, fz)) and _accepted(rw, jd):
            if not load:
                return d, jd, None, None, ""
            f, z = _load_f(os.path.join(d, fz), rw["npz_key"], nid)
            bc = None
            if rw["support"] == "jig":                       # 열 값(지지 = 하중 파일의 구속 배열)
                bc = _bc_ids(z, np.asarray(z["node_id"], dtype=np.int64) if "node_id" in z else nid)
            return d, jd, f, bc, ""
        if isinstance(jd, dict) and jd_none is None:
            jd_none = jd
            why = f"{jd.get('code') or code + '_NO_DATA'}: {jd.get('reason') or name + ' 자료 없음'}"
    return None, jd_none, None, None, why


def summary_for_mapping(entry, f, top_n: int | None = None) -> dict:
    """S2 셀 매핑용: 출처 하중 f(엔트리 raw 노드 순서)로 셀 요약을 다시 만든다(등록 때와 같은 ``normalize.grid_summary``·같은 격자·프레임).
    반환 = ``LibraryEntry.summary_for_mapping()`` 과 같은 형식."""
    from esl.library import entry as en
    from esl.library import normalize as nz
    g = entry.meta["grid"]
    tn = int(top_n) if top_n is not None else (len(entry.summary["top_node_id"]) if "top_node_id" in entry.summary else 50)
    gs = nz.grid_summary(entry.raw["x0"], np.asarray(f, dtype=np.float64), int(g["nx"]), int(g["ny"]), entry.meta["frame"],
                         top_n=tn, node_id=entry.raw["node_id"])
    return {**entry.summary, **{k: gs[k] for k in en.SUMMARY_KEYS if k in gs}, "nx": g["nx"], "ny": g["ny"],
            "frame": entry.meta["frame"]}


check_plan()
