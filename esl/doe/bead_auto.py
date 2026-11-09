"""비드 자동 탐지 → 직접 선택(select) 초기 선택(seed) (계약 docs/contracts/esl_bead_auto.md §4, AD-D-3·12·21, v0.16.2).

순수 numpy — DB·외부 명령 없음. 파일 쓰기는 ``write_auto_selection`` 1곳(호출자가 guard 를 넘김). 메시 출처와 무관(① Case·
② B 메시 — 노드 ID 는 paicad tag 와 같은 원 번호, AD-D-15·21).

공개 인터페이스(백엔드·워커·코어 stages 공통 — 바꾸지 않음)
- ``auto_selection(mesh, extract_doc, tag_npz, cfg) -> (selection, map_list, warnings)``
    mesh        = 기준 메시 dict(MESH_KEYS: node_id, elem_id, elem_type, conn, x0 …)
    extract_doc = paicad ``shell_features.json``(``paicad_io.read_features``) — beads[{id, bottom["F<n>"], nominal{…}}] 순서 = paicad 순서
    tag_npz     = ``paicad_io.read_tag`` 결과 또는 {node_id, kind, entity} 배열 dict(kind 1 = FACE, entity = 면 번호)
    cfg         = bead_doe 설정(``esl.doe.settings``) 또는 select 절 — DEFAULTS 위에 병합
    → selection = 정규화된 SelectionIn schema 1(``bead_select.normalize`` 결과 그대로 — 그대로 저장하면 수동 저장과 같은 sha),
                  비드 0 개면 None
      map_list  = [{bead "b<i>", paicad_id, n_floor}]
      warnings  = [{code, level?, …}] — AUTO_TOO_MANY_BEADS{n, max}·AUTO_GROUP_DROPPED{n}(info)·AUTO_BEAD_UNMAPPED{bead}·
                  AUTO_SLOPE_DIFF{bead, rel}(info)
- ``write_auto_selection(path, selection, map_list, warnings, *, mesh_sha256=None, paicad_version=None, guard=None) -> sha256``
    결정적 바이트 JSON(정렬 키·indent 1·끝 줄바꿈) ``{schema "esl/doe_auto_selection/1", selection, sha256, map, warnings,
    mesh_sha256, paicad_version}`` — 백엔드 ``GET …/select/auto`` 가 읽는 파일(prep/select/auto_selection.json).
- ``read_auto_selection(path) -> dict`` (위 문서, 백엔드·시험용) — v0.17.0: schema 2 스터디 문서
    ``esl/doe_auto_selection/2``(``bead_graph.auto_doc_v2`` — {source "graph", selection(schema 2), sha256, sym_pairs, hints,
    warnings, mesh_sha256, graph_sha256})도 그대로 돌려줌
- ``auto_from_prep(prep_dir, mesh, cfg, max_mb) -> (selection, map_list, warnings)`` : prep/extract·prep/tag 를 읽어 위 계산
    (읽기 실패 = EslError 그대로 — 호출자가 ``AUTO_DETECT_FAILED{step}`` 로 바꿈)

규칙(§4): 비드 k 의 바닥 = 모든 노드가 FACE-tag 이고 그 면이 모두 비드 k 의 bottom 면인 요소, 여기서
``features.enclosed_components`` 섬(최대 성분이 아닌 작은 둘러싸인 조각 — select.island.max_mm)을 뺌. 비드당 1단,
slope auto, blend auto, hold_fixed 0. paicad 묶음(groups)은 풀고 범위(ranges)는 가져오지 않음(AD-D-4).

계약과 다르게 정한 점(문서화): paicad tag 는 B-rep 모서리·꼭짓점 위 노드를 EDGE·VERTEX 로 분류하므로(CAD 를 따르는 메시는
바닥 가장자리 노드가 모두 모서리 위) "모든 노드 FACE" 만으로는 바닥 바깥 한 줄 요소가 늘 빠져 derive 의 사면 BFS 가 그 평행 요소에서
멈춘다. 그래서 바닥 = (모든 노드 FACE-bottom) ∪ (노드가 FACE-bottom 또는 EDGE·VERTEX 이고 FACE-bottom 노드가 1개 이상이며 요소
법선이 앞 집합의 평균 법선과 select.feature_angle_deg 안에서 평행한 요소). 다른 면에 FACE-tag 된 노드가 하나라도 있으면 제외는
그대로(필렛·사면 요소는 들어가지 않음).
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

from esl.errors import EslError
from esl.mesh import features

AUTO_SELECTION_JSON = "auto_selection.json"
AUTO_SELECTION_SCHEMA = "esl/doe_auto_selection/1"
# v0.17.0 BG-D-42: select_schema 2 스터디의 seed = 메시 분류 그래프(esl.doe.bead_graph.auto_seed — source "graph", paicad 는
# AUTO_SLOPE_DIFF 힌트만). 이 모듈의 paicad seed 경로(schema 1 스터디)는 그대로.
AUTO_SELECTION_SCHEMA_V2 = "esl/doe_auto_selection/2"


def _r(v, nd: int = 4):
    f = float(v)
    if not math.isfinite(f):
        return None
    r = round(f, nd)
    return 0.0 if r == 0 else r


def _face_of_nodes(node_id: np.ndarray, tag: dict) -> tuple[np.ndarray, np.ndarray]:
    """기준 메시 노드 인덱스별 (FACE-tag 면 번호(그 밖 = −1), EDGE·VERTEX-tag 여부). tag 의 다른 파트 노드는 무시, 중복 ID = 첫 행."""
    from esl.doe.paicad_io import TAG_KIND_EDGE, TAG_KIND_FACE, TAG_KIND_VERTEX
    out = np.full(node_id.size, -1, np.int64)
    edge = np.zeros(node_id.size, bool)
    tid = np.asarray(tag["node_id"], dtype=np.int64)
    kind = np.asarray(tag["kind"]).astype(np.int64)
    ent = np.asarray(tag["entity"]).astype(np.int64)
    if tid.size == 0 or node_id.size == 0:
        return out, edge
    _, first = np.unique(tid, return_index=True)
    first = np.sort(first)
    tid, kind, ent = tid[first], kind[first], ent[first]
    o = np.argsort(node_id, kind="stable")
    sid = node_id[o]
    p = np.searchsorted(sid, tid)
    hit = (p < sid.size) & (sid[np.minimum(p, sid.size - 1)] == tid)
    ok = hit & (kind == TAG_KIND_FACE)
    out[o[p[ok]]] = ent[ok]
    ok = hit & ((kind == TAG_KIND_EDGE) | (kind == TAG_KIND_VERTEX))
    edge[o[p[ok]]] = True
    return out, edge


def _floor_mask(ix, face: np.ndarray, edge: np.ndarray, bottom: list[int], cos_t: float) -> np.ndarray:
    """§4.2 바닥 후보(3각은 열 3 = 열 0 — MeshIndex): 모든 노드 FACE-bottom ∪ (모서리 노드 허용·평행 — 모듈 설명)."""
    if not bottom:
        return np.zeros(ix.n_elems, bool)
    onb = np.isin(face, np.asarray(bottom, np.int64))           # 노드별 FACE-bottom
    fb = onb[ix.conn]                                           # (ne, 4)
    strict = fb.all(axis=1)
    loose = (fb | edge[ix.conn]).all(axis=1) & fb.any(axis=1) & ~strict
    if not loose.any():
        return strict
    ref = strict if strict.any() else loose
    n = (ix.normal[ref] * ix.area[ref][:, None]).sum(axis=0)
    nn = float(np.linalg.norm(n))
    if nn <= 1e-300:
        return strict
    par = np.abs(ix.normal @ (n / nn)) >= cos_t
    return strict | (loose & par)


def _drop_islands(ix, cand: np.ndarray, max_mm: float) -> np.ndarray:
    """§4.3: 후보 바닥에서 섬(최대 성분이 아닌 작은 조각 — ``enclosed_components`` 규칙)을 뺀 마스크."""
    if not cand.any():
        return cand
    owner = np.zeros(ix.n_elems, np.int64)                     # 후보 밖 = 주인 하나(0)
    owner[cand] = -1
    nr = (ix.normal[cand] * ix.area[cand][:, None]).sum(axis=0)
    if float(np.linalg.norm(nr)) <= 1e-300:
        nr = np.array([0.0, 0.0, 1.0])
    r = features.enclosed_components(ix, cand, owner, ix.X, nr, max_mm=float(max_mm))
    out = cand.copy()
    for isl in r["islands"]:
        out[np.asarray(isl["elems"], np.int64)] = False
    return out


def _paicad_run(b: dict) -> float | None:
    """paicad 사면 수평 길이(입구 반경 − 바닥 반경, 없으면 깊이 / tan(사면 각)) — AD-D-12 힌트용."""
    nom = b.get("nominal") or {}
    try:
        if nom.get("entry_radius") is not None and nom.get("bottom_radius") is not None:
            v = float(nom["entry_radius"]) - float(nom["bottom_radius"])
        elif nom.get("depth") is not None and nom.get("flank_deg") is not None:
            t = math.tan(math.radians(float(nom["flank_deg"])))
            v = float(nom["depth"]) / t if t > 1e-9 else None
        else:
            v = None
    except (TypeError, ValueError):
        v = None
    return v if v is not None and math.isfinite(v) and v > 0 else None


def auto_selection(mesh: dict, extract_doc: dict, tag_npz: dict, cfg: dict | None = None):
    """→ (selection | None, map_list, warnings). 모듈 설명 참조."""
    from esl.doe import bead_select as bsel
    from esl.doe.paicad_io import face_ids
    sc = bsel._cfg(cfg)
    ix = bsel.mesh_index(mesh)
    face, edge = _face_of_nodes(np.asarray(mesh["node_id"], dtype=np.int64), tag_npz)
    cos_t = math.cos(math.radians(float(sc["feature_angle_deg"])))
    warns: list[dict] = []
    groups = [g for g in extract_doc.get("groups") or [] if isinstance(g, dict)]
    if groups:
        warns.append({"code": "AUTO_GROUP_DROPPED", "level": "info", "n": len(groups)})
    mapped = []                                                  # (paicad bead, floor mask)
    taken = np.zeros(ix.n_elems, bool)
    for b in extract_doc.get("beads") or []:
        if not isinstance(b, dict):
            continue
        F = _drop_islands(ix, _floor_mask(ix, face, edge, face_ids(b.get("bottom")), cos_t) & ~taken,
                          float(sc["island"]["max_mm"]))
        if not F.any():
            warns.append({"code": "AUTO_BEAD_UNMAPPED", "bead": str(b.get("id"))})
            continue
        taken |= F
        mapped.append((b, F))
    mx = int(sc["max_beads"])
    if len(mapped) > mx:
        warns.append({"code": "AUTO_TOO_MANY_BEADS", "n": len(mapped), "max": mx})
        mapped = mapped[:mx]
    if not mapped:
        return None, [], warns
    sel_in = {"schema_version": 1, "beads": [
        {"id": f"b{i}", "tiers": [{"k": 1, "floor": bsel.elemset_of(ix, F)}], "slope": {"mode": "auto"},
         "blend_mm": "auto", "hold_fixed": 0} for i, (_b, F) in enumerate(mapped, start=1)]}
    norm, _sha = bsel.normalize(sel_in, cfg)
    mp = [{"bead": f"b{i}", "paicad_id": str(b.get("id")), "n_floor": int(F.sum())}
          for i, (b, F) in enumerate(mapped, start=1)]
    warns += _slope_hints(mesh, norm, mapped, cfg, sc, ix)
    return norm, mp, warns


def _slope_hints(mesh: dict, norm: dict, mapped: list, cfg, sc: dict, ix) -> list[dict]:
    """AD-D-12: 유도 사면 수평 길이(``BeadDerived.run_med``) 와 paicad 사면 길이 상대 차 > select.auto.slope_diff_rel → info.
    derive 가 실패하면(선택이 유도 불가) 힌트 없음 — seed 는 그대로."""
    from esl.doe import bead_select as bsel
    lim = float(sc["auto"]["slope_diff_rel"])
    try:
        D = bsel.derive_obj(mesh, norm, cfg, index=ix, with_section=False)
    except EslError:
        return []
    out = []
    for i, ((b, _F), bd) in enumerate(zip(mapped, D.beads), start=1):
        ref = _paicad_run(b)
        run = getattr(bd, "run_med", None)
        if ref is None or run is None or not math.isfinite(float(run)):
            continue
        rel = abs(float(run) - ref) / ref
        if rel > lim:
            out.append({"code": "AUTO_SLOPE_DIFF", "level": "info", "bead": f"b{i}", "rel": _r(rel, 3)})
    return out


def auto_from_prep(prep_dir: str, mesh: dict, cfg: dict | None = None, max_mb: float = 64):
    """prep/extract(shell_features.json) + prep/tag(shell_tag.json·노드 표) → ``auto_selection``. 읽기 실패 = EslError
    (``exc.step`` = "extract" | "tag" — 호출자가 AUTO_DETECT_FAILED{step, code} 로)."""
    from esl.doe import paicad_io as pio
    try:
        doc = pio.read_features(os.path.join(prep_dir, "extract"), max_mb)
    except EslError as exc:
        exc.step = "extract"
        raise
    try:
        tag = pio.read_tag(os.path.join(prep_dir, "tag"), max_mb)
    except EslError as exc:
        exc.step = "tag"
        raise
    return auto_selection(mesh, doc, tag, cfg)


def auto_doc(selection: dict, map_list: list, warnings: list, *, mesh_sha256: str | None = None,
             paicad_version: str | None = None) -> dict:
    from esl.doe import bead_select as bsel
    return {"schema": AUTO_SELECTION_SCHEMA, "selection": selection, "sha256": bsel.selection_sha256(selection),
            "map": list(map_list), "warnings": list(warnings), "mesh_sha256": mesh_sha256,
            "paicad_version": paicad_version}


def auto_bytes(doc: dict) -> bytes:
    """결정적 바이트(정렬 키·indent 1·ensure_ascii False·끝 줄바꿈)."""
    from esl.library import _util as U
    return (json.dumps(U.jsonable(doc), ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def write_auto_selection(path: str, selection: dict, map_list: list, warnings: list, *, mesh_sha256: str | None = None,
                         paicad_version: str | None = None, guard=None) -> str:
    """auto_selection.json 쓰기(결정적 바이트) → 선택 sha256. guard = ``Writer.guard``(출력 폴더 밖 쓰기 금지)."""
    doc = auto_doc(selection, map_list, warnings, mesh_sha256=mesh_sha256, paicad_version=paicad_version)
    p = guard(path) if guard is not None else path
    with open(p, "wb") as fh:
        fh.write(auto_bytes(doc))
    return doc["sha256"]


def read_auto_selection(path: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") not in (AUTO_SELECTION_SCHEMA, AUTO_SELECTION_SCHEMA_V2):
        raise EslError("INPUT_INVALID", "auto_selection.json 형식이 아님")
    return doc


__all__ = ["auto_selection", "write_auto_selection", "read_auto_selection", "auto_from_prep", "auto_doc", "auto_bytes",
           "AUTO_SELECTION_JSON", "AUTO_SELECTION_SCHEMA", "AUTO_SELECTION_SCHEMA_V2"]
