"""재낙하 입력 묶음 공용 계산(계약 esl_redrop_bundle.md §5.1, v0.22.0 REDROP) — 모드 무관 독립 모듈.

- numpy·``esl.errors`` 만 import(``esl.doe``·플랫폼·워커 import 금지), 파일 IO·설정 해석 없음 — 필요한 값은 인수로 받는다
  (AGENTS.md "공용 계산은 독립 모듈"). 파일 읽기·쓰기는 ``esl.verify.stages.rd_prepare``, 패치 자체는 ``esl.verify.patch``.
- ``check_nodeset``  : I-1 design.npz 노드 집합 = base_mesh 노드 집합(중복 없음).
- ``merge_coords``   : I-2 기준 일치(원본 좌표 ≈ base ``x0``) 판정 + I-3 패치 좌표 합성(움직인 노드 = 설계 좌표, 그 밖 = 원본 좌표).
- ``manifest``·``readme_text`` : 순수 dict·문자열 생성(§2.1·§2.2).
"""
from __future__ import annotations

import numpy as np

from esl.errors import EslError

SCHEMA = "esl/redrop/1"
MANIFEST_NAME = "redrop_manifest.json"
README_NAME = "REDROP_README.txt"


class RedropError(EslError):
    """``EslError`` + 응답 detail(수치) — 백엔드가 ``detail`` 을 그대로 API 오류에 싣는다."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__(code, message)
        self.detail = detail


def check_nodeset(base_nid, design_nid) -> None:
    """I-1: 두 노드 ID 배열이 중복 없이 같은 집합이어야 함. 아니면 ``REDROP_NODESET_MISMATCH``(detail n_base·n_design·n_only_base·n_only_design)."""
    b = np.asarray(base_nid, dtype=np.int64).ravel()
    d = np.asarray(design_nid, dtype=np.int64).ravel()
    ub, ud = np.unique(b), np.unique(d)
    dup_b, dup_d = int(b.size - ub.size), int(d.size - ud.size)
    only_b = int(np.setdiff1d(ub, ud).size)
    only_d = int(np.setdiff1d(ud, ub).size)
    if dup_b or dup_d or only_b or only_d or b.size != d.size:
        raise RedropError("REDROP_NODESET_MISMATCH",
                          f"안의 노드 집합이 기준 메시와 다름(기준 {b.size}, 안 {d.size}, 기준에만 {only_b}, 안에만 {only_d}"
                          f"{', 중복 ID 있음' if dup_b or dup_d else ''})",
                          n_base=int(b.size), n_design=int(d.size), n_only_base=only_b, n_only_design=only_d)


def align_design(base_nid, design_nid, x_design) -> np.ndarray:
    """design.npz 좌표를 base 노드 순서로 맞춘다(집합이 같다고 이미 확인된 뒤)."""
    b = np.asarray(base_nid, dtype=np.int64)
    d = np.asarray(design_nid, dtype=np.int64)
    x = np.asarray(x_design, dtype=np.float64)
    order = np.argsort(d, kind="stable")
    idx = order[np.searchsorted(d[order], b)]
    return x[idx]


def merge_coords(node_id, x_design, x0, x_file, tol: float, *, design_node_id=None) -> tuple[np.ndarray, dict]:
    """패치 좌표 합성(I-2·I-3). node_id·x0·x_file 은 base 순서, x_design 은 ``design_node_id`` 순서(None = 이미 base 순서).

    - ``x_file`` 의 NaN 행 = 입력 세트에서 못 찾은 노드: I-2 판정에서 빼고(패치 단계가 ``VD_NODES_MISSING`` 으로 거부) 설계 좌표를 넣는다.
    - I-2: 찾은 노드의 ``max|x_file − x0|`` > ``tol`` → ``REDROP_BASE_CHANGED``(detail n_changed·max_diff).
    - I-3: ‖x_design − x0‖ > 0 인 노드 = ``x_design``, 그 밖 = ``x_file``(원본 줄이 바이트 그대로 남도록).
    - stats = {n_moved, max_disp, max_disp_node_id, base_max_diff}."""
    nid = np.asarray(node_id, dtype=np.int64)
    x0 = np.asarray(x0, dtype=np.float64)
    xf = np.asarray(x_file, dtype=np.float64)
    xd = np.asarray(x_design, dtype=np.float64)
    if design_node_id is not None:
        xd = align_design(nid, design_node_id, xd)
    present = ~np.isnan(xf).any(axis=1)
    diff = np.zeros(nid.size, dtype=np.float64)
    if present.any():
        diff[present] = np.abs(xf[present] - x0[present]).max(axis=1)
    max_diff = float(diff.max()) if nid.size else 0.0
    bad = diff > float(tol)
    if bad.any():
        raise RedropError("REDROP_BASE_CHANGED",
                          f"원본 입력의 대상 노드 좌표가 스터디 기준 메시와 다름(노드 {int(bad.sum())}개, 최대 차 {max_diff:.6g}) — "
                          "스터디를 만든 뒤 Case 입력이 바뀐 것으로 보임",
                          n_changed=int(bad.sum()), max_diff=max_diff)
    disp = np.linalg.norm(xd - x0, axis=1)
    moved = disp > 0
    out = np.where(moved[:, None] | ~present[:, None], xd, xf)
    k = int(np.argmax(disp)) if nid.size else 0
    return out, {"n_moved": int(moved.sum()), "max_disp": float(disp[k]) if nid.size else 0.0,
                 "max_disp_node_id": int(nid[k]) if moved.any() else None, "base_max_diff": max_diff}


def check_meta_names(rels) -> None:
    """v0.24.5: 입력 파일과 메타 2개가 한 폴더에 놓이므로 rel 이 메타 이름과 같으면(대소문자 무시) ``REDROP_META_NAME_CONFLICT``."""
    meta = {MANIFEST_NAME.casefold(), README_NAME.casefold()}
    bad = sorted(r for r in rels if r.casefold() in meta)
    if bad:
        raise RedropError("REDROP_META_NAME_CONFLICT",
                          f"입력 파일 이름이 재낙하 메타 파일({README_NAME}·{MANIFEST_NAME})과 겹침: {', '.join(bad)}", rels=bad)


def manifest(extra: dict, patch_res: dict, stats: dict, *, n_target: int, tol: float) -> dict:
    """``redrop_manifest.json`` 내용(§2.1, 고정 키 순서). extra = {platform_version, created_at, study, design, entry, case}."""
    files = [{"rel": f["rel"], "source": f["source"], "n_patched": int(f["n_patched"]), "size": int(f["size"]),
              "sha256": f["sha256"]} for f in patch_res["files"]]
    return {"schema": SCHEMA, "platform_version": extra.get("platform_version"), "created_at": extra.get("created_at"),
            "study": extra.get("study"), "design": extra.get("design"), "entry": extra.get("entry"),
            "case": extra.get("case"), "files": files,
            "changed": [f["rel"] for f in files if f["source"] == "patched"],
            "nodes": {"n_target": int(n_target), "n_moved": int(stats["n_moved"]),
                      "n_patched_lines": int(patch_res["n_patched"]), "max_disp": float(stats["max_disp"]),
                      "max_disp_node_id": stats["max_disp_node_id"], "units": "model"},
            "checks": {"nodeset_equal": True, "base_max_diff": float(stats["base_max_diff"]),
                       "base_coord_tol_mm": float(tol)}}


def readme_text(m: dict) -> str:
    """``REDROP_README.txt`` 본문(한국어 평문, ``\\n``) — manifest 만으로 만든다."""
    st, ds, en, cs, nd = m["study"] or {}, m["design"] or {}, m["entry"] or {}, m["case"] or {}, m["nodes"]
    vals = ds.get("values") or {}
    lines = [
        "재낙하 입력 묶음 (ESL 플랫폼 REDROP)",
        "",
        f"스터디   : {st.get('title')} ({st.get('id')})",
        f"시나리오 : {st.get('scenario')} / 계획 {st.get('plan')}",
        f"안       : {ds.get('id')}" + (f" (순위 {ds.get('rank')})" if ds.get("rank") is not None else "")
        + (f" 상태 {ds.get('status')}" if ds.get("status") else ""),
        f"엔트리   : {en.get('label')}" + (" (기준 엔트리)" if en.get("is_base") else ""),
        f"원 Case  : {cs.get('title')} — starter {cs.get('rad_file_name')}",
        "",
        "변수 값",
    ]
    lines += [f"  {k} = {vals[k]}" for k in sorted(vals)] or ["  (없음)"]
    lines += [
        "",
        f"대상 노드 {nd['n_target']}개 중 {nd['n_moved']}개가 기준 형상에서 움직임(최대 이동량 {nd['max_disp']:.6g}"
        + (f", 노드 {nd['max_disp_node_id']}" if nd.get("max_disp_node_id") is not None else "") + ", 모델 단위).",
        f"바뀐 입력 파일 {len(m['changed'])}개, /NODE 줄 {nd['n_patched_lines']}개를 고침." if m["changed"]
        else "바뀐 입력 파일 없음(기준안 — 모든 파일이 원본과 같음).",
    ]
    lines += [f"  - {r}" for r in m["changed"]]
    lines += [
        "",
        "사용법",
        f"  1. 이 폴더를 그대로 HPC 에 올려 starter rad({cs.get('rad_file_name')})로 제출합니다(README·manifest 는 해석에 쓰이지 않음).",
        "  2. 원본 낙하 결과와 비교하려면 같은 엔진·버전으로 돌립니다.",
        f"  3. 파일별 sha256·바뀐 줄 수는 {MANIFEST_NAME} 에 있습니다.",
        "",
        "이 묶음은 플랫폼이 만들었고 원본 입력 폴더는 바꾸지 않았습니다(원본 파일은 읽기만 함).",
        "",
    ]
    return "\n".join(lines)


__all__ = ["check_nodeset", "align_design", "merge_coords", "manifest", "readme_text", "RedropError", "SCHEMA",
           "MANIFEST_NAME", "README_NAME", "check_meta_names"]
