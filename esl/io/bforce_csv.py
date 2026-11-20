"""경계력 ESL 원자료 패킹: TCL bf_<kind>.csv → 01_extract/bforce.npz·bforce.json (계약 esl_bforce.md §1·§2, v0.24.0).

done.json 에 ``bforce`` 키가 없으면(이전 TCL) 아무것도 쓰지 않는다(옛 추출물 = 01_extract 바이트 동일).
값 없는 노드 = 0(행 없음) + 종류별 n_missing. 대상 파트 밖 노드·후보 프레임 밖 행은 무시. 결과 유형이 없거나 쿼리가 실패한
종류는 type null(실패 아님).

v0.24.2(esl_bforce_ondemand.md §1.3·§4): has_frame("있음" 판정), _pack_kinds(추출 pack·보충 병합 공용 CSV → 배열),
frame_data 는 병합 문서의 kinds[k].frames 를 따른다. 병합 자체는 esl.io.bforce_ondemand.
"""
from __future__ import annotations

import json
import os

import numpy as np

from esl.errors import EslError
from esl.io.results_csv import _chunks, _lookup, _open_csv, savez_stream

SCHEMA = "esl/bforce_extract/1"
KINDS = ("cont", "cont2", "acc", "mass", "fint")
BF_FILES = tuple(f"bf_{k}.csv" for k in KINDS)
NPZ = "bforce.npz"
JSON = "bforce.json"


def _done(results_dir: str) -> dict | None:
    p = os.path.join(results_dir, "done.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def pack_bforce(results_dir: str, node_id, out_dir: str) -> dict | None:
    """반환 = bforce.json 문서(쓰지 않았으면 None). node_id = 모델 노드 ID(오름차순, model.npz 순서)."""
    done = _done(results_dir)
    bfd = None if done is None else done.get("bforce")
    if not isinstance(bfd, dict):
        return None
    nid = np.asarray(node_id, dtype=np.int64)
    doc: dict = {"schema": SCHEMA, "on": bool(bfd.get("on", True)), "kinds": {}, "frames": []}
    if not doc["on"]:
        _write(out_dir, doc)
        return doc
    frames = [int(f) for f in (bfd.get("frames") or done.get("frames_D") or [])]
    doc["frames"] = frames
    doc["kinds"], arrays = _pack_kinds(results_dir, nid, frames, bfd)
    if arrays:
        os.makedirs(out_dir, exist_ok=True)
        savez_stream(os.path.join(out_dir, NPZ), frame_index=np.asarray(frames, dtype=np.int32), node_id=nid, **arrays)
    _write(out_dir, doc)
    return doc


def _pack_kinds(results_dir: str, nid, frames, bfd: dict) -> tuple[dict, dict]:
    """bf_<kind>.csv(results_dir) → ({kind: bforce.json kinds 항목}, {kind: 배열}) — 추출 pack·보충 병합 공용(v0.24.2).

    frames = 배열 행 순서(이 밖 프레임 행은 무시), nid = 모델 노드 ID(오름차순, 이 밖 노드 행은 무시, 값 없는 노드 = 0 +
    n_missing). bfd = done.json bforce(종류별 type·comps). 없는 유형·CSV 오류 = 그 종류만 type null(실패 아님)."""
    nid = np.asarray(nid, dtype=np.int64)
    D, N = len(frames), nid.size
    fpos = {int(f): i for i, f in enumerate(frames)}
    kinds: dict = {}
    arrays: dict = {}
    for k in KINDS:
        rec = (bfd.get("kinds") or {}).get(k)
        if not isinstance(rec, dict) or not rec.get("type"):
            kinds[k] = {"type": None, "reason": (rec or {}).get("reason") if isinstance(rec, dict) else "not dumped"}
            continue
        path = os.path.join(results_dir, f"bf_{k}.csv")
        vec = k != "mass"
        cols = ["frame_index", "node_id"] + (["x", "y", "z"] if vec else ["v"])
        try:
            fh, idx = _open_csv(path, cols)
        except EslError as exc:
            kinds[k] = {"type": None, "reason": f"{exc.code}: {exc.message}"}
            continue
        a = np.zeros((D, N, 3) if vec else (D, N))
        seen = np.zeros((D, N), dtype=bool)
        try:
            _read_into(fh, idx, path, nid, fpos, vec, a, seen)
        except EslError as exc:                       # 형식 오류 = 그 종류만 없음(추출 실패 아님)
            kinds[k] = {"type": None, "reason": f"{exc.code}: {exc.message}"[:500]}
            continue
        rows = int(seen.sum())
        arrays[k] = a
        kinds[k] = {"type": rec.get("type"), "comps": list(rec.get("comps") or []), "rows": rows,
                    "n_missing": int((~seen).sum())}
    return kinds, arrays


def _read_into(fh, idx, path, nid, fpos, vec, a, seen) -> None:
    fr = np.asarray(sorted(fpos), dtype=np.int64)
    fmap = np.asarray([fpos[int(f)] for f in fr], dtype=np.int64)
    with fh:
        for ch in _chunks(fh, idx, path):
            p = _lookup(nid, ch[:, 1].astype(np.int64))
            q = _lookup(fr, ch[:, 0].astype(np.int64))
            ok = (p >= 0) & (q >= 0)
            fp = fmap[q[ok]]
            if vec:
                a[fp, p[ok]] = ch[ok, 2:5]
            else:
                a[fp, p[ok]] = ch[ok, 2]
            seen[fp, p[ok]] = True


def _write(out_dir: str, doc: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, JSON), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)


def read_doc(extract_dir: str) -> dict | None:
    """01_extract/bforce.json 문서(없거나 읽기 오류·형식 오류 = None)."""
    jp = os.path.join(extract_dir, JSON)
    if not os.path.isfile(jp):
        return None
    try:
        with open(jp, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def doc_frames(doc: dict | None) -> list[int]:
    """bforce.json 의 "있음" 프레임(on 이 참일 때 frames, 그 밖 = [])."""
    if not isinstance(doc, dict) or not doc.get("on"):
        return []
    try:
        return [int(f) for f in (doc.get("frames") or [])]
    except (TypeError, ValueError):
        return []


def has_frame(extract_dir: str, frame: int) -> bool:
    """선택 프레임의 경계력 원자료가 01_extract 에 "있음"(계약 esl_bforce_ondemand.md §1.3, v0.24.2).

    bforce.json 이 있고 on 이 참이고 frames 에 frame 이 있으면 참 — 종류를 하나도 못 찾은 프레임(npz 없음·kinds 전부 null)도
    "있음"(같은 프레임을 다시 보충하지 않음). 파일 읽기 오류 = 없음."""
    return int(frame) in doc_frames(read_doc(extract_dir))


def frame_data(extract_dir: str, frame_index: int) -> tuple[dict, dict | None]:
    """01_extract → (선택 프레임 자료 {kind: 배열|None}, bforce.json 문서|None). 자료 없음 = ({}, doc|None).

    v0.24.2 보충 병합 문서(kinds[k].frames 가 있음)는 그 목록 밖 프레임에서 그 종류 = None(없는 프레임 칸 = 0 이므로).
    목록이 없으면(추출 pack 문서) 지금처럼 npz 의 전 프레임."""
    jp = os.path.join(extract_dir, JSON)
    doc = None
    if os.path.isfile(jp):
        with open(jp, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    zp = os.path.join(extract_dir, NPZ)
    if not os.path.isfile(zp):
        return {}, doc
    with np.load(zp, allow_pickle=False) as z:
        fr = np.asarray(z["frame_index"]).tolist()
        if int(frame_index) not in fr:
            return {}, doc
        i = fr.index(int(frame_index))
        out = {k: (np.asarray(z[k][i], dtype=np.float64) if k in z.files else None) for k in KINDS}
    kd = (doc or {}).get("kinds") if isinstance(doc, dict) else None
    for k in KINDS:
        rec = kd.get(k) if isinstance(kd, dict) else None
        if isinstance(rec, dict) and (not rec.get("type") or (isinstance(rec.get("frames"), list)
                                                          and int(frame_index) not in [int(f) for f in rec["frames"]])):
            out[k] = None
    return out, doc
