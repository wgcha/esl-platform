"""경계력 ESL 원자료 패킹: TCL bf_<kind>.csv → 01_extract/bforce.npz·bforce.json (계약 esl_bforce.md §1·§2, v0.24.0).

done.json 에 ``bforce`` 키가 없으면(이전 TCL) 아무것도 쓰지 않는다(옛 추출물 = 01_extract 바이트 동일).
값 없는 노드 = 0(행 없음) + 종류별 n_missing. 대상 파트 밖 노드·후보 프레임 밖 행은 무시. 결과 유형이 없거나 쿼리가 실패한
종류는 type null(실패 아님).
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
    D, N = len(frames), nid.size
    fpos = {f: i for i, f in enumerate(frames)}
    arrays: dict = {}
    for k in KINDS:
        rec = (bfd.get("kinds") or {}).get(k)
        if not isinstance(rec, dict) or not rec.get("type"):
            doc["kinds"][k] = {"type": None, "reason": (rec or {}).get("reason") if isinstance(rec, dict) else "not dumped"}
            continue
        path = os.path.join(results_dir, f"bf_{k}.csv")
        vec = k != "mass"
        cols = ["frame_index", "node_id"] + (["x", "y", "z"] if vec else ["v"])
        try:
            fh, idx = _open_csv(path, cols)
        except EslError as exc:
            doc["kinds"][k] = {"type": None, "reason": f"{exc.code}: {exc.message}"}
            continue
        a = np.zeros((D, N, 3) if vec else (D, N))
        seen = np.zeros((D, N), dtype=bool)
        try:
            _read_into(fh, idx, path, nid, fpos, vec, a, seen)
        except EslError as exc:                       # 형식 오류 = 그 종류만 없음(추출 실패 아님)
            doc["kinds"][k] = {"type": None, "reason": f"{exc.code}: {exc.message}"[:500]}
            continue
        rows = int(seen.sum())
        arrays[k] = a
        doc["kinds"][k] = {"type": rec.get("type"), "comps": list(rec.get("comps") or []), "rows": rows,
                           "n_missing": int((~seen).sum())}
    if arrays:
        os.makedirs(out_dir, exist_ok=True)
        savez_stream(os.path.join(out_dir, NPZ), frame_index=np.asarray(frames, dtype=np.int32), node_id=nid, **arrays)
    _write(out_dir, doc)
    return doc


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


def frame_data(extract_dir: str, frame_index: int) -> tuple[dict, dict | None]:
    """01_extract → (선택 프레임 자료 {kind: 배열|None}, bforce.json 문서|None). 자료 없음 = ({}, doc|None)."""
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
        return {k: (np.asarray(z[k][i], dtype=np.float64) if k in z.files else None) for k in KINDS}, doc
