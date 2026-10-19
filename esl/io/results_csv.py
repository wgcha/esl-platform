"""HyperView TCL 출력 CSV 폴더 → npz 패킹 (계약 esl_core.md §3.2·§3.3).

CSV 는 ``csv`` 모듈로 청크(기본 20만 행) 단위로 읽어 사전할당 배열에 채운다.
파일 전체를 한 번에 메모리에 올리지 않는다.
"""

from __future__ import annotations

import csv
import itertools
import json
import os
from typing import Any, Iterator

import numpy as np

from esl.errors import EslError

CHUNK_ROWS = 200_000
_LAYER_POS = {"bottom": 0, "top": 1}
_DONE_CODES = {"H3D_MISSING_RESULT", "ID_MISMATCH", "TOOL_OUTPUT_MISSING", "INPUT_INVALID"}


def _open_csv(path: str, required: list[str]):
    if not os.path.isfile(path):
        raise EslError("TOOL_OUTPUT_MISSING", f"TCL 출력 파일이 없음: {path}")
    fh = open(path, "r", encoding="utf-8-sig", newline="")
    rd = csv.reader(fh)
    try:
        header = [h.strip().lower() for h in next(rd)]
    except StopIteration:
        fh.close()
        raise EslError("TOOL_OUTPUT_MISSING", f"CSV 가 비어 있음(헤더 없음): {path}") from None
    miss = [c for c in required if c not in header]
    if miss:
        fh.close()
        raise EslError("TOOL_OUTPUT_MISSING", f"CSV 헤더에 열 {miss} 가 없음: {path}")
    cols = [header.index(c) for c in required]
    return fh, rd, cols


def _chunks(rd, cols: list[int], path: str) -> Iterator[list[list[str]]]:
    """필요한 열만 열 단위 리스트로 묶어 청크씩 돌려준다."""
    width = max(cols) + 1
    while True:
        block = list(itertools.islice(rd, CHUNK_ROWS))
        if not block:
            return
        block = [r for r in block if r and any(s.strip() for s in r)]
        if not block:
            continue
        bad = next((r for r in block if len(r) < width), None)
        if bad is not None:
            raise EslError("TOOL_OUTPUT_MISSING", f"CSV 행의 열 수가 부족함: {path}: {bad}")
        yield [[r[c] for r in block] for c in cols]


def _num(col: list[str], dtype, path: str) -> np.ndarray:
    try:
        return np.asarray(col, dtype=np.float64).astype(dtype) if dtype is not np.float64 \
            else np.asarray(col, dtype=np.float64)
    except ValueError as exc:
        raise EslError("TOOL_OUTPUT_MISSING", f"CSV 숫자 열을 읽을 수 없음: {path}: {exc}") from None


def _lookup(sorted_ids: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """sorted_ids 안의 위치, 없으면 -1."""
    if sorted_ids.size == 0:
        return np.full(ids.shape, -1, dtype=np.int64)
    pos = np.searchsorted(sorted_ids, ids)
    pos_c = np.minimum(pos, sorted_ids.size - 1)
    return np.where(sorted_ids[pos_c] == ids, pos_c, -1)


def _read_done(results_dir: str) -> dict:
    p = os.path.join(results_dir, "done.json")
    if not os.path.isfile(p):
        raise EslError("TOOL_OUTPUT_MISSING", f"done.json 이 없음(TCL 미완료 또는 실패): {results_dir}")
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            done = json.load(fh)
    except (OSError, ValueError) as exc:
        raise EslError("TOOL_OUTPUT_MISSING", f"done.json 을 읽을 수 없음: {exc}") from None
    if not isinstance(done, dict):
        raise EslError("TOOL_OUTPUT_MISSING", "done.json 형식 오류(객체 아님)")
    if done.get("ok") is not True:
        code = done.get("code")
        code = code if code in _DONE_CODES else "TOOL_LOG_ERROR"
        raise EslError(code, f"TCL 추출 실패(done.json ok=false): {done.get('error', '')}")
    return done


def pack_results(results_dir, model, out_dir, frame_stride=1) -> dict:
    """TCL CSV 폴더를 ``strain_tensor.npz``·``disp.npz``·``frames.json`` 으로 패킹."""
    results_dir = os.fspath(results_dir)
    out_dir = os.fspath(out_dir)
    if int(frame_stride) < 1:
        raise EslError("CONFIG_INVALID", f"frame_stride 는 1 이상이어야 함: {frame_stride}")
    frame_stride = int(frame_stride)
    done = _read_done(results_dir)
    warnings: list[str] = [str(w) for w in (done.get("warnings") or [])]

    node_id = np.asarray(model.node_id, dtype=np.int64)
    elem_id = np.asarray(model.elem_id, dtype=np.int64)
    x0 = np.asarray(model.x0, dtype=np.float64)
    if np.any(np.diff(node_id) <= 0) or np.any(np.diff(elem_id) <= 0):
        raise EslError("INPUT_INVALID", "model 의 node_id·elem_id 는 오름차순·중복 없음이어야 함")
    N, E = node_id.size, elem_id.size

    # ---------------- frames.csv
    path = os.path.join(results_dir, "frames.csv")
    fh, rd, cols = _open_csv(path, ["frame_index", "time"])
    fi_l, t_l = [], []
    with fh:
        for fi, t in _chunks(rd, cols, path):
            fi_l.append(_num(fi, np.int64, path))
            t_l.append(_num(t, np.float64, path))
    if not fi_l:
        raise EslError("H3D_MISSING_RESULT", "frames.csv 에 프레임이 없음")
    all_fi = np.concatenate(fi_l)
    all_t = np.concatenate(t_l)
    o = np.argsort(all_fi, kind="stable")
    all_fi, all_t = all_fi[o], all_t[o]
    if np.any(np.diff(all_fi) == 0):
        raise EslError("TOOL_OUTPUT_MISSING", "frames.csv 에 중복 frame_index 가 있음")
    frame_index = all_fi[::frame_stride]
    time = all_t[::frame_stride]
    F = frame_index.size

    # ---------------- model.csv (좌표 검증)
    path = os.path.join(results_dir, "model.csv")
    fh, rd, cols = _open_csv(path, ["node_id", "x0", "y0", "z0"])
    xm = np.full((N, 3), np.nan)
    seen = np.zeros(N, dtype=bool)
    with fh:
        for nid, a, b, c in _chunks(rd, cols, path):
            p = _lookup(node_id, _num(nid, np.int64, path))
            k = p >= 0
            xm[p[k]] = np.column_stack([_num(a, np.float64, path), _num(b, np.float64, path),
                                        _num(c, np.float64, path)])[k]
            seen[p[k]] = True
    if not np.all(seen):
        raise EslError("ID_MISMATCH", f"model.csv 에 대상 파트 노드 {int((~seen).sum())}개가 없음: "
                                      f"{node_id[~seen][:10].tolist()}")
    bbox = float(np.linalg.norm(x0.max(axis=0) - x0.min(axis=0))) if N else 0.0
    # TCL·h3d 좌표는 float32 일 수 있음 → 원점에서 먼 소형 파트는 절대 반올림 오차가 bbox 기준을 넘는다.
    xmax = float(np.abs(x0).max()) if N else 0.0
    tol = max(1e-6 * bbox, 2.0 * float(np.finfo(np.float32).eps) * xmax * np.sqrt(3.0), 1e-300)
    dev = np.linalg.norm(xm - x0, axis=1)
    if np.any(dev > tol):
        bad = np.argsort(-dev)[:5]
        raise EslError("ID_MISMATCH", f"model.csv 좌표가 rad 와 다름(허용 {tol:.3g}): 최대 {dev.max():.3g}, "
                                      f"노드 {node_id[bad].tolist()}")

    # ---------------- strain.csv
    path = os.path.join(results_dir, "strain.csv")
    if not os.path.isfile(path):
        raise EslError("H3D_MISSING_RESULT", f"strain.csv 가 없음(변형률 텐서 결과 누락): {path}")
    fh, rd, cols = _open_csv(path, ["frame_index", "elem_id", "layer", "exx", "eyy", "exy"])
    eps = np.zeros((F, E, 2, 3), dtype=np.float32)
    got = np.zeros((F, E, 2), dtype=bool)
    unknown_layers: set[str] = set()
    n_rows = 0
    with fh:
        for fi, eid, lay, exx, eyy, exy in _chunks(rd, cols, path):
            n_rows += len(fi)
            fp = _lookup(frame_index, _num(fi, np.int64, path))
            ep = _lookup(elem_id, _num(eid, np.int64, path))
            lay_a = np.char.lower(np.char.strip(np.asarray(lay, dtype=str)))
            lp = np.full(lay_a.shape, -1, dtype=np.int64)
            lp[lay_a == "bottom"] = 0
            lp[lay_a == "top"] = 1
            odd = set(np.unique(lay_a[(lp < 0) & (lay_a != "mid")]).tolist())
            unknown_layers |= odd
            k = (fp >= 0) & (ep >= 0) & (lp >= 0)
            if not np.any(k):
                continue
            vals = np.column_stack([_num(exx, np.float64, path), _num(eyy, np.float64, path),
                                    _num(exy, np.float64, path)])[k]
            eps[fp[k], ep[k], lp[k]] = vals
            got[fp[k], ep[k], lp[k]] = True
    if unknown_layers:
        warnings.append(f"strain.csv 의 알 수 없는 layer 무시: {sorted(unknown_layers)[:5]}")
    if n_rows == 0:
        raise EslError("H3D_MISSING_RESULT", "strain.csv 에 데이터가 없음")
    for li, lname in enumerate(("bottom", "top")):
        if not np.any(got[:, :, li]):
            raise EslError("H3D_MISSING_RESULT", f"strain.csv 에 layer '{lname}' 가 없음(bottom·top 필수)")
    if not np.all(got):
        miss_e = ~np.all(got, axis=(0, 2))
        miss_f = ~np.all(got, axis=(1, 2))
        raise EslError("ID_MISMATCH", f"strain.csv 에 대상 파트 요소 값 누락: 요소 {int(miss_e.sum())}개 "
                                      f"(예 {elem_id[miss_e][:10].tolist()}), 프레임 {int(miss_f.sum())}개 "
                                      f"(예 {frame_index[miss_f][:5].tolist()})")
    del got

    # ---------------- disp.csv
    path = os.path.join(results_dir, "disp.csv")
    if not os.path.isfile(path):
        raise EslError("H3D_MISSING_RESULT", f"disp.csv 가 없음(변위 결과 누락): {path}")
    fh, rd, cols = _open_csv(path, ["frame_index", "node_id", "ux", "uy", "uz"])
    u = np.zeros((F, N, 3), dtype=np.float64)
    gotn = np.zeros((F, N), dtype=bool)
    n_rows = 0
    with fh:
        for fi, nid, ux, uy, uz in _chunks(rd, cols, path):
            n_rows += len(fi)
            fp = _lookup(frame_index, _num(fi, np.int64, path))
            npos = _lookup(node_id, _num(nid, np.int64, path))
            k = (fp >= 0) & (npos >= 0)
            if not np.any(k):
                continue
            u[fp[k], npos[k]] = np.column_stack([_num(ux, np.float64, path), _num(uy, np.float64, path),
                                                 _num(uz, np.float64, path)])[k]
            gotn[fp[k], npos[k]] = True
    if n_rows == 0:
        raise EslError("H3D_MISSING_RESULT", "disp.csv 에 데이터가 없음")
    if not np.all(gotn):
        miss_n = ~np.all(gotn, axis=0)
        miss_f = ~np.all(gotn, axis=1)
        raise EslError("ID_MISMATCH", f"disp.csv 에 대상 파트 노드 값 누락: 노드 {int(miss_n.sum())}개 "
                                      f"(예 {node_id[miss_n][:10].tolist()}), 프레임 {int(miss_f.sum())}개")
    if not (np.all(np.isfinite(eps)) and np.all(np.isfinite(u))):
        raise EslError("H3D_MISSING_RESULT", "strain/disp 값에 NaN·Inf 가 있음")

    for key, val in (("n_elems", E), ("n_nodes", N)):
        if key in done and done[key] not in (None, val):
            warnings.append(f"done.json {key}={done[key]} ≠ 대상 파트 {val} (다른 파트 행은 무시함)")

    # ---------------- 쓰기
    os.makedirs(out_dir, exist_ok=True)
    fi32 = frame_index.astype(np.int32)
    np.savez_compressed(os.path.join(out_dir, "strain_tensor.npz"),
                        time=time.astype(np.float64), frame_index=fi32,
                        elem_id=elem_id.astype(np.int64), eps=eps)
    np.savez_compressed(os.path.join(out_dir, "disp.npz"),
                        time=time.astype(np.float64), frame_index=fi32,
                        node_id=node_id.astype(np.int64), u=u)
    meta = {
        "schema": "esl/frames/1",
        "frame_index": fi32.tolist(),
        "time": time.tolist(),
        "frame_stride": frame_stride,
        "n_frames": int(F), "n_elems": int(E), "n_nodes": int(N),
        "h3d": done.get("h3d"),
        "units_label": getattr(model, "units_label", ""),
        "layers": ["bottom", "top"],
        "strain_components": ["exx", "eyy", "exy"],
        "warnings": warnings,
    }
    with open(os.path.join(out_dir, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return {"n_frames": int(F), "n_elems": int(E), "n_nodes": int(N), "warnings": warnings}


def write_results_csv(dir, frames_time, node_id, x0, u, elem_id, eps, frame_index=None,
                      h3d="synthetic.h3d", write_done=True, extra_nodes=None, extra_elems=None,
                      layer_names=("bottom", "top")) -> str:
    """TCL 출력 포맷(§3.2) 생성기. 시험·E2E 용.

    - ``u``: (F,N,3), ``eps``: (F,E,2,3) layer 0=bottom, 1=top, 성분 exx,eyy,exy(텐서).
    - ``frame_index``: 기본 0..F-1.
    - ``extra_nodes``/``extra_elems``: 다른 파트 행 흉내용 추가 ID (값은 0).
    """
    d = os.fspath(dir)
    os.makedirs(d, exist_ok=True)
    t = np.asarray(frames_time, dtype=np.float64).reshape(-1)
    F = t.size
    fi = np.arange(F) if frame_index is None else np.asarray(frame_index, dtype=np.int64)
    node_id = np.asarray(node_id, dtype=np.int64)
    x0 = np.asarray(x0, dtype=np.float64).reshape(-1, 3)
    u = np.asarray(u, dtype=np.float64).reshape(F, node_id.size, 3)
    elem_id = np.asarray(elem_id, dtype=np.int64)
    eps = np.asarray(eps, dtype=np.float64).reshape(F, elem_id.size, 2, 3)
    xn = [] if extra_nodes is None else [int(v) for v in extra_nodes]
    xe = [] if extra_elems is None else [int(v) for v in extra_elems]
    g = "{:.17g}".format

    with open(os.path.join(d, "frames.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,time\n")
        for k in range(F):
            fh.write(f"{int(fi[k])},{g(t[k])}\n")
    with open(os.path.join(d, "model.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("node_id,x0,y0,z0\n")
        for k in range(node_id.size):
            fh.write(f"{int(node_id[k])},{g(x0[k, 0])},{g(x0[k, 1])},{g(x0[k, 2])}\n")
        for n in xn:
            fh.write(f"{n},0,0,0\n")
    with open(os.path.join(d, "strain.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,elem_id,layer,exx,eyy,exy\n")
        for k in range(F):
            for li, ln in enumerate(layer_names):
                for e in range(elem_id.size):
                    a = eps[k, e, li]
                    fh.write(f"{int(fi[k])},{int(elem_id[e])},{ln},{g(a[0])},{g(a[1])},{g(a[2])}\n")
                for e in xe:
                    fh.write(f"{int(fi[k])},{e},{ln},0,0,0\n")
    with open(os.path.join(d, "disp.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,node_id,ux,uy,uz\n")
        for k in range(F):
            for n in range(node_id.size):
                a = u[k, n]
                fh.write(f"{int(fi[k])},{int(node_id[n])},{g(a[0])},{g(a[1])},{g(a[2])}\n")
            for n in xn:
                fh.write(f"{int(fi[k])},{n},0,0,0\n")
    if write_done:
        done: dict[str, Any] = {"ok": True, "n_frames": int(F), "n_elems": int(elem_id.size + len(xe)),
                                "n_nodes": int(node_id.size + len(xn)), "h3d": h3d, "warnings": []}
        with open(os.path.join(d, "done.json"), "w", encoding="utf-8") as fh:
            json.dump(done, fh)
    return d
