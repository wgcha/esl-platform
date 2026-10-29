"""HyperView TCL 출력 CSV 폴더 → npz 패킹 (계약 esl_core.md §7.2·§7.3, 검사 규칙은 §3.3 유지).

TCL 3패스 출력::

  frames.csv         frame_index,time                                   전 프레임
  model.csv          node_id,x0,y0,z0[,cx,cy,cz,dx,dy,dz]              초기 좌표 x0 = 프레임 0 node.coords(c)
                                                                        − 프레임 0 변위(d) (구형: x0,y0,z0 만)
  elems.csv          elem_id,n1,n2,n3,n4                                대상 파트 요소-노드 연결(삼각형 n4=0·빈칸,
                                                                        0.5.5; 없거나 done.json elems_ok=false 면 생략)
  final.csv          elem_id,vm_hv,exx,eyy,ezz,exy,epsp                 (A) 마지막 프레임, 파트 전 요소
  history.csv        frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp     (B) 전 프레임, 집합 H
  strain_frames.csv  frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp     (C) 후보 프레임 D + 직전 프레임
                                                                        P = {f−1 ≥ 0 : f∈D}, 파트 전 요소
  disp.csv           frame_index,node_id,ux,uy,uz                       (C) 후보 프레임 D, 파트 전 노드
  done.json          {"ok":true, "candidate_frames":{"max_strain":[..],"plastic_strain":[..]}, "frames_D",
                      "prev_frames", "strain_frames", "hot_k", ...}

strain_frames.npz 의 ``prev_*`` (계약 esl_p2_library.md §7.1): D 의 각 f 에 대해 f−1 프레임 값(전 요소 "상승 중"
마스크용). f=0 이면 prev_frame_index=−1·값 0. 예전 TCL 출력(직전 프레임 행 없음)이면 prev_available=False·값 0 +
경고(이 경우 비교는 history 의 H 요소만 상승 여부를 안다).

exy 는 h3d 값 그대로(전단 규약은 pipeline 이 ``decide_shear`` 로 판정). CSV 는 ``csv`` 모듈로 청크(기본 20만 행)
단위로 읽어 사전할당 배열에 채운다(22만 요소 × D ≤ 10 프레임 = 220만 행도 파일 전체를 메모리에 올리지 않음).
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
_DONE_CODES = {"H3D_MISSING_RESULT", "ID_MISMATCH", "TOOL_OUTPUT_MISSING", "INPUT_INVALID"}
SCOLS = ["vm_hv", "exx", "eyy", "ezz", "exy", "epsp"]          # CSV 값 열 순서
METRICS = ("max_strain", "plastic_strain")
RESULT_FILES = ("frames.csv", "model.csv", "elems.csv", "final.csv", "history.csv", "strain_frames.csv", "disp.csv",
                "done.json")


def _open_csv(path: str, required: list[str], missing_code: str = "TOOL_OUTPUT_MISSING", optional=None):
    """(파일 핸들(헤더 다음 줄), 필요한 열 위치). optional 열 이름 목록을 주면 셋째 값 = 그중 헤더에 모두 있으면 True."""
    if not os.path.isfile(path):
        raise EslError(missing_code, f"TCL 출력 파일이 없음: {path}")
    fh = open(path, "r", encoding="utf-8-sig", newline="")
    header = [h.strip().lower() for h in next(csv.reader([fh.readline()]), [])]
    if not header or header == [""]:
        fh.close()
        raise EslError("TOOL_OUTPUT_MISSING", f"CSV 가 비어 있음(헤더 없음): {path}")
    miss = [c for c in required if c not in header]
    if miss:
        fh.close()
        raise EslError("TOOL_OUTPUT_MISSING", f"CSV 헤더에 열 {miss} 가 없음: {path}")
    if optional is not None:
        if all(c in header for c in optional):
            return fh, [header.index(c) for c in list(required) + list(optional)], True
        return fh, [header.index(c) for c in required], False
    return fh, [header.index(c) for c in required]


def _chunks(fh, cols: list[int], path: str) -> Iterator[np.ndarray]:
    """CHUNK_ROWS 줄씩 읽어 필요한 열만 (n, len(cols)) float64 로 돌려준다(빈 줄 무시).

    한 청크의 문자열(줄)과 그 숫자 배열만 메모리에 있다 → 22만~수십만 요소 × D 프레임도 결과 배열 + 청크 수준.
    ID 는 float64 로 읽은 뒤 int64 로 바꾼다(2^53 미만 정확).
    """
    while True:
        lines = list(itertools.islice(fh, CHUNK_ROWS))
        if not lines:
            return
        try:
            a = np.loadtxt(lines, delimiter=",", usecols=cols, ndmin=2, dtype=np.float64)
        except ValueError as exc:
            raise EslError("TOOL_OUTPUT_MISSING", f"CSV 를 읽을 수 없음(열 수·숫자 형식): {path}: {exc}") from None
        if a.shape[0]:
            yield a


def _lookup(sorted_ids: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """sorted_ids 안의 위치, 없으면 -1."""
    if sorted_ids.size == 0:
        return np.full(ids.shape, -1, dtype=np.int64)
    pos = np.searchsorted(sorted_ids, ids)
    pos_c = np.minimum(pos, sorted_ids.size - 1)
    return np.where(sorted_ids[pos_c] == ids, pos_c, -1)


def _id(col: np.ndarray) -> np.ndarray:
    return col.astype(np.int64)


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


def _alloc6(shape) -> dict:
    """[vm,exx,eyy,ezz,exy,epsp] 값을 담을 npz 필드 배열(f4) — 저장 시 복사 없음."""
    return {"vm_hv": np.zeros(shape, np.float32), "eps": np.zeros(shape + (3,), np.float32),
            "ezz": np.zeros(shape, np.float32), "epsp": np.zeros(shape, np.float32)}


def _put6(dst: dict, idx, v: np.ndarray) -> None:
    dst["vm_hv"][idx] = v[:, 0]
    dst["eps"][idx] = v[:, [1, 2, 4]]
    dst["ezz"][idx] = v[:, 3]
    dst["epsp"][idx] = v[:, 5]


_SAVE_CHUNK = 1024 * 1024


def savez_stream(path: str, **arrays) -> None:
    """np.savez_compressed 와 같은 .npz(ZIP_DEFLATED, .npy v1/2) 를 배열 복사 없이 1 MiB 조각으로 쓴다.

    (np.savez_compressed 는 배열 전체를 bytes 로 복사한 뒤 압축 → 큰 배열에서 메모리 피크가 배 가까이 늘어남.)
    np.load(allow_pickle=False) 로 그대로 읽힌다.
    """
    import zipfile

    from numpy.lib import format as npf

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for name, a in arrays.items():
            a = np.asarray(a)
            if a.dtype.hasobject:
                raise EslError("INPUT_INVALID", f"object 배열은 저장하지 않음: {name}")
            if not a.flags.c_contiguous:
                a = np.ascontiguousarray(a)
            with zf.open(name + ".npy", "w", force_zip64=True) as fp:
                npf.write_array_header_2_0(fp, npf.header_data_from_array_1_0(a))
                if a.size:
                    mv = memoryview(a.reshape(-1)).cast("B")
                    for i in range(0, mv.nbytes, _SAVE_CHUNK):
                        fp.write(mv[i:i + _SAVE_CHUNK])


def _missing_msg(name, got, ids, frames, what="요소"):
    miss_e = ~np.all(got, axis=0)
    miss_f = ~np.all(got, axis=1)
    return (f"{name} 에 대상 파트 {what} 값 누락: {what} {int(miss_e.sum())}개 (예 {ids[miss_e][:10].tolist()}), "
            f"프레임 {int(miss_f.sum())}개 (예 {frames[miss_f][:5].tolist()})")


def _read_frame_table(path, frames, ids, key, what, name, optional=None):
    """frame_index,<key>,<값> 표 → 사전할당 배열에 청크 단위로 채움 + 전부 채워졌는지 검사.

    key=elem_id → _alloc6 사전(f4), key=node_id → u (len(frames), len(ids), 3) f8.
    optional (len(frames),) bool: 이 프레임은 행이 하나도 없어도 됨(일부만 있으면 ID_MISMATCH).
    optional 을 주면 (값, 프레임별 존재 여부) 를 돌려준다.
    """
    six = key == "elem_id"
    fh, cols = _open_csv(path, ["frame_index", key] + (SCOLS if six else ["ux", "uy", "uz"]), "H3D_MISSING_RESULT")
    out = _alloc6((frames.size, ids.size)) if six else np.zeros((frames.size, ids.size, 3), np.float64)
    got = np.zeros((frames.size, ids.size), dtype=bool)
    n_rows = 0
    with fh:
        for a in _chunks(fh, cols, path):
            n_rows += a.shape[0]
            fp = _lookup(frames, _id(a[:, 0]))
            ip = _lookup(ids, _id(a[:, 1]))
            k = (fp >= 0) & (ip >= 0)
            if not np.any(k):
                continue
            v = a[k, 2:]
            if not np.all(np.isfinite(v)):
                raise EslError("H3D_MISSING_RESULT", f"{name} 값에 NaN·Inf 가 있음")
            if six:
                _put6(out, (fp[k], ip[k]), v)
            else:
                out[fp[k], ip[k]] = v
            got[fp[k], ip[k]] = True
    if n_rows == 0:
        raise EslError("H3D_MISSING_RESULT", f"{name} 에 데이터가 없음")
    if optional is None:
        if not np.all(got):
            raise EslError("ID_MISMATCH", _missing_msg(name, got, ids, frames, what))
        return out
    opt = np.asarray(optional, dtype=bool)
    present = got.any(axis=1)
    need = ~opt | present                     # 필수 프레임 + 일부라도 있는 선택 프레임은 전부 있어야 함
    if not np.all(got[need]):
        g = got.copy()
        g[~need] = True
        raise EslError("ID_MISMATCH", _missing_msg(name, g, ids, frames, what))
    return out, present


def _kabsch(xm, x0):
    """x0 → xm Kabsch 강체 정합(회전+평행이동): (노드별 잔차 (N,), 회전 행렬 R)."""
    c0, cm = x0.mean(axis=0), xm.mean(axis=0)
    A, B = x0 - c0, xm - cm
    U, _, Vt = np.linalg.svd(A.T @ B)
    s = np.sign(np.linalg.det(U @ Vt)) or 1.0
    R = (U @ np.diag([1.0, 1.0, s]) @ Vt).T                    # B ≈ A R^T
    return np.linalg.norm(A @ R.T - B, axis=1), R


def coord_diagnostics(xm, x0, tol) -> dict:
    """h3d 좌표 xm ↔ rad 좌표 x0 (N,3) 편차 요약: 평균 편차 벡터(강체 평행이동), 축별 표준편차,
    Kabsch 강체 정합(회전+평행이동) 후 잔차 최대값·회전각. rigid = 정합 후 잔차 ≤ tol(편차가 강체 운동뿐)."""
    xm = np.asarray(xm, dtype=np.float64)
    x0 = np.asarray(x0, dtype=np.float64)
    d = xm - x0
    res, R = _kabsch(xm, x0)
    ang = float(np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))))
    rmax = float(res.max()) if res.size else 0.0
    return {"mean_dev": d.mean(axis=0).tolist(), "std_dev": d.std(axis=0).tolist(), "rigid_residual_max": rmax,
            "rigid_rotation_deg": ang, "rigid": bool(rmax <= tol)}


def _coord_diag_text(g: dict) -> str:
    v = lambda a: "[" + ", ".join(f"{x:.4g}" for x in a) + "]"
    t = (f"진단: 평균 편차 {v(g['mean_dev'])}, 표준편차 {v(g['std_dev'])}, 강체 정합 후 잔차 최대 "
         f"{g['rigid_residual_max']:.3g}(회전 {g['rigid_rotation_deg']:.3g}°), frame 0 time {g['frame0_time']:.6g}")
    if g.get("frame0_disp_max") is not None:
        t += f", frame 0 변위 최대 {g['frame0_disp_max']:.3g}"
    return t + f", 비교 좌표 {g['coord_source']}"


# ---------------------------------------------------------------- 요소 연결(모델 동일성, §3.3)
ELEMS_COLS = ["elem_id", "n1", "n2", "n3", "n4"]


def canon_conn(a) -> np.ndarray:
    """요소 노드 ID (E,4) → 비교용 정규형 (E,4). 0·음수 = 없음.

    서로 다른 노드 4개(쿼드): 순환 회전·방향 반전을 같은 것으로(최소 ID 를 앞에, 이웃 중 작은 쪽 방향).
    그 밖(삼각형, n4=0·n4=n3 등 중복 노드 표현): 고유 노드 ID 오름차순 + 0 채움(삼각형은 어느 순서든 회전·반전).
    """
    a = np.where(np.asarray(a, dtype=np.int64) > 0, np.asarray(a, dtype=np.int64), 0)
    s = np.sort(a, axis=1)
    dup = np.zeros(s.shape, dtype=bool)
    dup[:, 1:] = s[:, 1:] == s[:, :-1]
    s[dup] = 0
    nu = (s > 0).sum(axis=1)
    big = np.iinfo(np.int64).max
    t = np.where(s > 0, s, big)
    t.sort(axis=1)
    t[t == big] = 0
    quad = nu == 4
    if np.any(quad):
        q = a[quad]
        k = np.argmin(q, axis=1)
        r = q[np.arange(q.shape[0])[:, None], (k[:, None] + np.arange(4)[None, :]) % 4]
        flip = r[:, 3] < r[:, 1]
        r[flip] = r[flip][:, [0, 3, 2, 1]]
        t[quad] = r
    return t


def _read_elems(path: str, elem_id: np.ndarray):
    """elems.csv → (대상 파트 요소별 노드 ID (E,4), 행 있음 (E,) bool). n4 빈칸 = 0(삼각형)."""
    fh, cols = _open_csv(path, ELEMS_COLS)
    conn = np.zeros((elem_id.size, 4), dtype=np.int64)
    got = np.zeros(elem_id.size, dtype=bool)
    with fh:
        while True:
            lines = list(itertools.islice(fh, CHUNK_ROWS))
            if not lines:
                break
            fixed = []
            for ln in lines:
                ln = ln.rstrip("\r\n")
                if ln.strip():
                    fixed.append(",".join(c if c.strip() else "0" for c in ln.split(",")))
            if not fixed:
                continue
            try:
                a = np.loadtxt(fixed, delimiter=",", usecols=cols, ndmin=2, dtype=np.float64)
            except ValueError as exc:
                raise EslError("TOOL_OUTPUT_MISSING", f"CSV 를 읽을 수 없음(열 수·숫자 형식): {path}: {exc}") from None
            p = _lookup(elem_id, _id(a[:, 0]))
            k = p >= 0
            conn[p[k]] = a[k, 1:5].astype(np.int64)
            got[p[k]] = True
    return conn, got


def _check_conn(results_dir: str, done: dict, model, elem_id, node_id, warnings: list) -> dict:
    """대상 파트 요소마다 rad 노드 ID 목록 = h3d(elems.csv) 노드 ID 목록인지(§3.3). 다르면 ID_MISMATCH."""
    path = os.path.join(results_dir, "elems.csv")
    E = int(elem_id.size)
    why = None
    if done.get("elems_ok") is False:
        why = "TCL 이 요소 연결을 추출하지 못함(done.json elems_ok=false)"
    elif not os.path.isfile(path):
        why = "elems.csv 없음(이전 TCL 추출물)"
    elif getattr(model, "conn", None) is None:
        why = "rad 모델에 요소 연결 정보가 없음"
    if why is not None:
        warnings.append(f"CONN_CHECK_SKIPPED: {why} — rad·h3d 요소 연결 동일성 검사 생략(노드 ID·좌표 개략 확인만 함). "
                        f"TCL 을 다시 실행하면 검사됨")
        return {"checked": False, "reason": why, "n_elems": E, "n_mismatch": None}
    conn = np.asarray(model.conn, dtype=np.int64)
    rad_ids = np.where(conn >= 0, node_id[np.maximum(conn, 0)], 0)
    h3d_ids, got = _read_elems(path, elem_id)
    bad = ~got | np.any(canon_conn(rad_ids) != canon_conn(h3d_ids), axis=1)
    nb = int(bad.sum())
    if nb:
        idx = np.flatnonzero(bad)[:10]
        lst = "; ".join(f"{int(elem_id[i])}: rad {[int(v) for v in rad_ids[i] if v > 0]} / h3d "
                        + (str([int(v) for v in h3d_ids[i] if v > 0]) if got[i] else "없음") for i in idx)
        raise EslError("ID_MISMATCH", f"rad 와 h3d 의 요소 연결(요소별 노드 ID)이 다름: 요소 {nb}/{E}개 — 같은 모델이 "
                                      f"아님(rad·h3d 짝 확인). 상위 {idx.size}개: {lst}")
    return {"checked": True, "reason": None, "n_elems": E, "n_mismatch": 0}


def pack_results(results_dir, model, out_dir, frame_stride=1, coord_check=None) -> dict:
    """TCL CSV 폴더 → ``final.npz``·``history.npz``·``strain_frames.npz``·``disp.npz``·``frames.json`` (§7.3).

    frame_stride: history 의 프레임 간격(후보 프레임 D 는 항상 포함). coord_check: {max_rel}
    (None = esl.config.COORD_CHECK_DEFAULTS, 알 수 없는 키 무시). 반환 {n_frames(history), n_elems, n_nodes,
    n_hot, frames_D, candidate_frames, warnings, coord_deviation, conn_check}.

    모델 동일성(§3.3): 노드 ID 집합(대상 파트 노드가 h3d 에 모두 있음) + 요소 연결(elems.csv) 이 기준이고,
    좌표는 Kabsch 강체 정합 후 잔차 ≤ max_rel·bbox 인지 개략 확인만 한다. 계산 좌표는 항상 rad.
    """
    results_dir = os.fspath(results_dir)
    out_dir = os.fspath(out_dir)
    if int(frame_stride) < 1:
        raise EslError("CONFIG_INVALID", f"frame_stride 는 1 이상이어야 함: {frame_stride}")
    frame_stride = int(frame_stride)
    from esl.config import COORD_CHECK_DEFAULTS
    cc = dict(COORD_CHECK_DEFAULTS)
    if isinstance(coord_check, dict) and coord_check.get("max_rel") is not None:
        cc["max_rel"] = coord_check["max_rel"]
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
    fh, cols = _open_csv(path, ["frame_index", "time"])
    fi_l, t_l = [], []
    with fh:
        for a in _chunks(fh, cols, path):
            fi_l.append(_id(a[:, 0]))
            t_l.append(a[:, 1])
    if not fi_l:
        raise EslError("H3D_MISSING_RESULT", "frames.csv 에 프레임이 없음")
    all_fi = np.concatenate(fi_l)
    all_t = np.concatenate(t_l)
    o = np.argsort(all_fi, kind="stable")
    all_fi, all_t = all_fi[o], all_t[o]
    if np.any(np.diff(all_fi) == 0):
        raise EslError("TOOL_OUTPUT_MISSING", "frames.csv 에 중복 frame_index 가 있음")

    # ---------------- D (후보 프레임): done.json candidate_frames 합집합
    cf = done.get("candidate_frames")
    cand: dict[str, list[int]] = {}
    if isinstance(cf, dict):
        for m in METRICS:
            cand[m] = [int(x) for x in (cf.get(m) or [])]
        D = np.array(sorted({x for v in cand.values() for x in v}), dtype=np.int64)
        if isinstance(done.get("frames_D"), list) and done["frames_D"]:
            D = np.array(sorted({int(x) for x in done["frames_D"]} | set(D.tolist())), dtype=np.int64)
    else:
        warnings.append("done.json 에 candidate_frames 없음 → disp.csv 의 frame_index 로 D 를 정함")
        D = _scan_frames(os.path.join(results_dir, "disp.csv"))
    if D.size == 0:
        raise EslError("H3D_MISSING_RESULT", "후보 프레임 D 가 비어 있음(done.json candidate_frames)")
    if np.any(_lookup(all_fi, D) < 0):
        raise EslError("ID_MISMATCH", f"후보 프레임 {D.tolist()} 중 frames.csv 에 없는 것이 있음")
    t_of = dict(zip(all_fi.tolist(), all_t.tolist()))
    tD = np.array([t_of[int(f)] for f in D], dtype=np.float64)
    # history 프레임 = stride 표본 ∪ D (마지막 프레임 포함)
    hsel = set(all_fi[::frame_stride].tolist()) | set(D.tolist()) | {int(all_fi[-1])}
    hist_fi = np.array(sorted(hsel), dtype=np.int64)
    hist_t = np.array([t_of[int(f)] for f in hist_fi], dtype=np.float64)

    # ---------------- model.csv: 노드 ID 집합 + 좌표 개략 확인(강체 정합 후 잔차 ≤ max_rel·bbox). 계산은 rad 좌표
    path = os.path.join(results_dir, "model.csv")
    fh, cols, has_raw = _open_csv(path, ["node_id", "x0", "y0", "z0"], optional=["cx", "cy", "cz", "dx", "dy", "dz"])
    xm = np.full((N, 3), np.nan)
    xr = np.full((N, 3), np.nan) if has_raw else None
    d0max = 0.0
    seen = np.zeros(N, dtype=bool)
    with fh:
        for a in _chunks(fh, cols, path):
            p = _lookup(node_id, _id(a[:, 0]))
            k = p >= 0
            xm[p[k]] = a[k, 1:4]
            if has_raw:
                xr[p[k]] = a[k, 4:7]
                if k.any():
                    d0max = max(d0max, float(np.linalg.norm(a[k, 7:10], axis=1).max()))
            seen[p[k]] = True
    if not np.all(seen):
        raise EslError("ID_MISMATCH", f"model.csv 에 대상 파트 노드 {int((~seen).sum())}개가 없음: "
                                      f"{node_id[~seen][:10].tolist()}")
    if not np.all(np.isfinite(xm)):
        raise EslError("TOOL_OUTPUT_MISSING", "model.csv 좌표에 NaN·Inf 가 있음")
    bbox = float(np.linalg.norm(x0.max(axis=0) - x0.min(axis=0))) if N else 0.0
    # TCL·h3d 좌표는 float32 일 수 있음 → 반올림 수준(tol) 이하 차이는 "같음"으로 본다(기록도 안 함).
    xmax = float(np.abs(x0).max()) if N else 0.0
    tol = max(1e-6 * bbox, 2.0 * float(np.finfo(np.float32).eps) * xmax * np.sqrt(3.0), 1e-300)
    thr = max(float(cc["max_rel"]) * bbox, tol)
    t0 = done.get("frame0_time")
    t0 = float(t0) if isinstance(t0, (int, float)) else float(all_t[0])
    coord_source = "x0" if has_raw else "x0 (구형 model.csv: 변위 보정 열 없음)"
    res, _R = _kabsch(xm, x0) if N else (np.zeros(0), np.eye(3))
    if has_raw and d0max > 0.0 and N and float(res.max()) > tol:
        res_raw, _ = _kabsch(xr, x0)
        if float(res_raw.max()) < float(res.max()):
            # node.coords 가 이미 변형 전 좌표였던 경우(변위를 빼면 오히려 어긋남) → 원 좌표로 비교
            warnings.append(f"model.csv: 프레임 0 변위(최대 {d0max:.3g})를 뺀 좌표보다 node.coords 원값이 rad 와 더 "
                            f"잘 맞음 → 원값(cx,cy,cz)으로 비교")
            xm, res, coord_source = xr, res_raw, "cx (node.coords 원값)"
    _st = getattr(model, "state", None)
    if isinstance(_st, dict) and (_st.get("coord") or {}).get("n_nodes_state"):
        coord_source = f"{coord_source} ↔ rad:state"      # 누적 씬: 비교 기준 = 상태 파일(.str) 변형 좌표
    dev = np.linalg.norm(xm - x0, axis=1)
    coord_dev = None
    if N and (float(dev.max()) > tol or float(res.max()) > tol):
        diag = coord_diagnostics(xm, x0, tol)
        diag.update({"frame0_time": t0, "frame0_disp_max": float(d0max) if has_raw else None,
                     "coord_source": coord_source})
        rmax = float(res.max())
        if rmax > thr:
            order = np.argsort(-res)[:10]
            top = ", ".join(f"{int(node_id[i])}({res[i]:.3g})" for i in order)
            raise EslError("ID_MISMATCH", f"rad 와 h3d 형상이 다름: 강체 정합 후 잔차 최대 {rmax:.3g} > 허용 {thr:.3g}"
                                          f"(coord_check.max_rel {float(cc['max_rel']):g} × bbox {bbox:.4g}) — 같은 "
                                          f"모델이 아님. 잔차 상위 노드: {top}; {_coord_diag_text(diag)}")
        over = dev > tol
        order = np.argsort(-dev)[:10]
        top = [{"node_id": int(node_id[i]), "dev": float(dev[i])} for i in order if over[i]]
        coord_dev = {"n_dev": int(over.sum()), "n_nodes": int(N), "max_dev": float(dev.max()), "tol": float(tol),
                     "max_rel": float(cc["max_rel"]), "bbox": bbox, "threshold": float(thr), "top": top, **diag}
    del xm, xr, dev, res, seen

    # ---------------- elems.csv: 요소 연결(대상 파트 요소별 노드 ID 목록) 동일성
    conn_check = _check_conn(results_dir, done, model, elem_id, node_id, warnings)

    # ---------------- final.csv (A)
    path = os.path.join(results_dir, "final.csv")
    fh, cols = _open_csv(path, ["elem_id"] + SCOLS, "H3D_MISSING_RESULT")
    fin6 = _alloc6((E,))
    gotf = np.zeros(E, dtype=bool)
    with fh:
        for a in _chunks(fh, cols, path):
            p = _lookup(elem_id, _id(a[:, 0]))
            k = p >= 0
            if not np.all(np.isfinite(a[k, 1:])):
                raise EslError("H3D_MISSING_RESULT", "final.csv 값에 NaN·Inf 가 있음")
            _put6(fin6, p[k], a[k, 1:])
            gotf[p[k]] = True
    if not np.all(gotf):
        raise EslError("ID_MISMATCH", f"final.csv 에 대상 파트 요소 {int((~gotf).sum())}개가 없음: "
                                      f"{elem_id[~gotf][:10].tolist()}")

    # ---------------- history.csv (B): H = 행에 나온 대상 파트 요소
    path = os.path.join(results_dir, "history.csv")
    fh, cols = _open_csv(path, ["frame_index", "elem_id"], "H3D_MISSING_RESULT")
    hset: set[int] = set()
    with fh:
        for a in _chunks(fh, cols, path):
            e = np.unique(_id(a[:, 1]))
            hset.update(e[_lookup(elem_id, e) >= 0].tolist())
    hist_id = np.array(sorted(hset), dtype=np.int64)
    if hist_id.size == 0:
        raise EslError("H3D_MISSING_RESULT", "history.csv 에 대상 파트 요소가 없음")
    hv = _read_frame_table(path, hist_fi, hist_id, "elem_id", "요소", "history.csv")
    if done.get("n_hot") not in (None, int(hist_id.size)):
        warnings.append(f"done.json n_hot={done.get('n_hot')} ≠ history.csv 대상 파트 요소 {hist_id.size}")

    # ---------------- strain_frames.csv / disp.csv (C): D + 직전 프레임 P (§P2 7.1)
    # 직전 프레임 = frames.csv 순서에서 바로 앞 프레임(TCL 은 0..F−1 연속이라 f−1), 첫 프레임이면 −1
    dpos_all = _lookup(all_fi, D)
    prevD = np.where(dpos_all > 0, all_fi[np.maximum(dpos_all - 1, 0)], -1).astype(np.int64)
    P = np.array(sorted(set(prevD[prevD >= 0].tolist())), dtype=np.int64)
    if np.any(_lookup(all_fi, P) < 0):
        raise EslError("ID_MISMATCH", f"직전 프레임 {P.tolist()} 중 frames.csv 에 없는 것이 있음")
    U = np.array(sorted(set(D.tolist()) | set(P.tolist())), dtype=np.int64)
    sv_all, present = _read_frame_table(os.path.join(results_dir, "strain_frames.csv"), U, elem_id, "elem_id",
                                        "요소", "strain_frames.csv", optional=~np.isin(U, D))
    du = _lookup(U, D)
    sv = {k: a[du] for k, a in sv_all.items()}
    prev_ok = np.ones(D.size, dtype=bool)
    prev = {k: np.zeros_like(a) for k, a in sv.items()}
    for i, pf in enumerate(prevD.tolist()):
        if pf < 0:
            continue
        j = int(_lookup(U, np.array([pf]))[0])
        if present[j]:
            for k in prev:
                prev[k][i] = sv_all[k][j]
        else:
            prev_ok[i] = False
    del sv_all
    if not prev_ok.all():
        miss = prevD[~prev_ok].tolist()
        warnings.append(f"strain_frames.csv 에 직전 프레임 {miss} 의 행이 없음(예전 TCL 출력) — 전 요소 '상승 중' "
                        f"마스크를 만들 수 없어 재현 정확도 비교는 history(H) 요소만 가능. TCL 을 다시 실행할 것")
    prev_frames_done = done.get("prev_frames")
    if isinstance(prev_frames_done, list) and sorted(int(x) for x in prev_frames_done) != P.tolist():
        warnings.append(f"done.json prev_frames={prev_frames_done} ≠ D 에서 계산한 직전 프레임 {P.tolist()}")
    u = _read_frame_table(os.path.join(results_dir, "disp.csv"), D, node_id, "node_id", "노드", "disp.csv")

    for key, val in (("n_elems", E), ("n_nodes", N)):
        if key in done and done[key] not in (None, val):
            warnings.append(f"done.json {key}={done[key]} ≠ 대상 파트 {val} (다른 파트 행은 무시함)")
    # 최종 프레임 일관성: history 마지막 프레임 = final
    hp = _lookup(elem_id, hist_id)
    if not all(np.array_equal(hv[k][-1], fin6[k][hp]) for k in hv):
        warnings.append("history.csv 마지막 프레임 값이 final.csv 와 다름")

    # ---------------- frame0.csv (누적 씬 F0 패스, 선택 — esl_cumulative_input.md §6.5): 대상 파트 전 요소 frame 0
    f0 = None
    p0 = os.path.join(results_dir, "frame0.csv")
    if os.path.isfile(p0):
        fh, cols = _open_csv(p0, ["elem_id", "vm_hv", "epsp"])
        f0 = {"vm_hv": np.full(E, np.nan), "epsp": np.full(E, np.nan)}
        with fh:
            for a in _chunks(fh, cols, p0):
                p = _lookup(elem_id, _id(a[:, 0]))
                k = p >= 0
                f0["vm_hv"][p[k]] = a[k, 1]
                f0["epsp"][p[k]] = a[k, 2]
        nmiss = int(np.sum(~np.isfinite(f0["epsp"])))
        if nmiss:
            warnings.append(f"frame0.csv 에 대상 파트 요소 {nmiss}개가 없음(누적 판정에서 제외)")

    # ---------------- 쓰기
    os.makedirs(out_dir, exist_ok=True)
    if f0 is not None:
        savez_stream(os.path.join(out_dir, "frame0.npz"), elem_id=elem_id, **f0)
    savez_stream(os.path.join(out_dir, "final.npz"), elem_id=elem_id, **fin6)
    savez_stream(os.path.join(out_dir, "history.npz"), time=hist_t, frame_index=hist_fi.astype(np.int32),
                 elem_id=hist_id, **hv)
    savez_stream(os.path.join(out_dir, "strain_frames.npz"), frame_index=D.astype(np.int32), time=tD,
                 elem_id=elem_id, **sv, prev_frame_index=prevD.astype(np.int32), prev_vm_hv=prev["vm_hv"],
                 prev_eps=prev["eps"], prev_epsp=prev["epsp"], prev_available=prev_ok)
    del sv, prev
    savez_stream(os.path.join(out_dir, "disp.npz"), frame_index=D.astype(np.int32), time=tD, node_id=node_id, u=u)
    meta = {
        "schema": "esl/frames/2",
        "frame_index": hist_fi.tolist(), "time": hist_t.tolist(), "frame_stride": frame_stride,
        "n_frames_h3d": int(all_fi.size), "n_frames": int(hist_fi.size),
        "frames_D": D.tolist(), "time_D": tD.tolist(), "candidate_frames": cand,
        "prev_frame_index": prevD.tolist(), "prev_available": prev_ok.tolist(),
        "candidate_elems": done.get("candidate_elems"),
        "hot_k": done.get("hot_k"), "top_n": done.get("top_n"), "reach_rtol": done.get("reach_rtol"),
        "n_hot": int(hist_id.size), "n_elems": int(E), "n_nodes": int(N),
        "h3d": done.get("h3d"), "results": {k: done.get(k) for k in ("strain_type", "strain_layer", "epsp_type",
                                                                       "epsp_layer", "disp_type")},
        "units_label": getattr(model, "units_label", ""),
        "layer": "mid", "value_columns": SCOLS, "eps_components": ["exx", "eyy", "exy"], "exy": "raw (h3d)",
        "frame0_time": t0, "model_coords": done.get("model_coords", "legacy"),
        "warnings": warnings, "coord_deviation": coord_dev, "conn_check": conn_check,
    }
    if isinstance(done.get("cumulative"), dict):          # 누적 씬 TCL 출력만(비누적은 키 없음)
        meta["tcl_cumulative"] = {**done["cumulative"],
                                  "candidate_frames_prev": done.get("candidate_frames_prev"),
                                  "candidate_elems_prev": done.get("candidate_elems_prev")}
    with open(os.path.join(out_dir, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return {"n_frames": int(hist_fi.size), "n_elems": int(E), "n_nodes": int(N), "n_hot": int(hist_id.size),
            "frames_D": D.tolist(), "prev_frames": P.tolist(), "prev_available": bool(prev_ok.all()),
            "candidate_frames": cand, "warnings": warnings, "coord_deviation": coord_dev,
            "conn_check": conn_check, "frame0": f0 is not None}


def _scan_frames(path: str) -> np.ndarray:
    fh, cols = _open_csv(path, ["frame_index"], "H3D_MISSING_RESULT")
    s: set[int] = set()
    with fh:
        for a in _chunks(fh, cols, path):
            s.update(np.unique(_id(a[:, 0])).tolist())
    return np.array(sorted(s), dtype=np.int64)


# ====================================================================== 전단 규약 판정 (§7.1)
def decide_shear(vm_hv, eps, mode: str = "auto", rel_floor: float = 1e-2) -> dict:
    """h3d exy 가 텐서(γ/2)인지 공학(γ)인지: HyperView vonMises(vm_hv)와 ε_eq(§4 공식)를 비교.

    mode = tensor | engineering 이면 그대로, auto 면 vm_hv ≥ rel_floor·max(vm_hv) 인 요소에서 상대 불일치
    중앙값이 작은 쪽. 반환 {convention, factor(exy 에 곱할 값: 1 또는 0.5), mismatch:{tensor, engineering}
    (최대 상대 불일치), median:{...}, n_used}.
    """
    from esl.mech import strain

    vm = np.asarray(vm_hv, dtype=np.float64)
    e = np.asarray(eps, dtype=np.float64)
    use = np.isfinite(vm) & (vm > 0)
    if use.any():
        use &= vm >= rel_floor * vm[use].max()
    stats: dict[str, dict] = {"mismatch": {}, "median": {}}
    for conv, fac in (("tensor", 1.0), ("engineering", 0.5)):
        if use.any():
            ee = e[use].copy()
            ee[:, 2] *= fac
            r = np.abs(strain.eps_eq(ee) - vm[use]) / vm[use]
            stats["mismatch"][conv] = float(r.max())
            stats["median"][conv] = float(np.median(r))
        else:
            stats["mismatch"][conv] = None
            stats["median"][conv] = None
    if mode in ("tensor", "engineering"):
        conv = mode
    elif mode == "auto":
        mt, me = stats["median"]["tensor"], stats["median"]["engineering"]
        conv = "engineering" if (mt is not None and me is not None and me < mt) else "tensor"
    else:
        raise EslError("CONFIG_INVALID", f"extract.shear_convention: {mode}")
    return {"mode": mode, "convention": conv, "factor": 1.0 if conv == "tensor" else 0.5,
            "max_rel_mismatch": stats["mismatch"][conv], **stats, "n_used": int(use.sum()),
            "rel_floor": rel_floor}


def tensor_eps(eps, factor: float) -> np.ndarray:
    """h3d exy → 텐서 전단(exy·factor). eps (...,3) 사본(f8)."""
    e = np.array(eps, dtype=np.float64, copy=True)
    e[..., 2] *= float(factor)
    return e


# ====================================================================== 합성용 생성기
def max_hold(eq_inst, *arrays):
    """요소별 max-hold: 매 프레임 지금까지 eq 최대(처음 도달한 프레임)의 값을 유지.

    eq_inst (F,E) 순간 지표, arrays = (F,E,...) 같은 프레임에서 함께 유지할 값(예: 텐서).
    반환 (eq_hold, *arrays_hold).
    """
    eq = np.asarray(eq_inst, dtype=np.float64)
    F, E = eq.shape
    src = np.zeros((F, E), dtype=np.int64)
    best = eq[0].copy()
    cur = np.zeros(E, dtype=np.int64)
    for f in range(1, F):
        up = eq[f] > best
        best = np.where(up, eq[f], best)
        cur = np.where(up, f, cur)
        src[f] = cur
    cols = np.arange(E)[None, :]
    out = [eq[src, cols]]
    for a in arrays:
        a = np.asarray(a)
        out.append(a[src, cols])
    return tuple(out)


def write_results_csv(dir, frames_time, node_id, x0, u, elem_id, eps, vm_hv=None, ezz=None, epsp=None,
                      frame_index=None, h3d="synthetic.h3d", write_done=True, extra_nodes=None, extra_elems=None,
                      hot_k=200, top_n=5, reach_rtol=1e-6, frames_D=None, write_prev=True,
                      legacy_model=False, elem_nodes=None) -> str:
    """TCL 3패스 출력(§7.2) 생성기. 시험·E2E 용 — H·D 는 TCL 과 같은 규칙(esl.mech.tstar)으로 정한다.

    - ``eps``: (F,E,3) h3d 에 저장된 [exx,eyy,exy] (이미 max-hold 된 Max_Strain 텐서; exy 규약은 호출자 몫).
    - ``vm_hv``: (F,E) HyperView vonMises(기본 ε_eq(eps) 텐서 규약), ``ezz`` 기본 −(exx+eyy), ``epsp`` 기본 0.
    - ``u``: (F,N,3) 전 프레임 변위(D 프레임만 쓴다). ``frames_D`` 를 주면 D 를 그것으로 강제.
    - ``extra_nodes``/``extra_elems``: 다른 파트 행 흉내용 추가 ID (값은 0).
    - ``write_prev``: strain_frames.csv 에 직전 프레임 P = {f−1 ≥ 0 : f∈D} 행도 씀(TCL 패스 C 와 같음).
      False 면 예전 TCL 출력(직전 프레임 없음) 흉내.
    - model.csv: TCL 과 같이 ``x0`` = 프레임 0 node.coords(``cx`` = x0 + u[0]) − 프레임 0 변위(``dx`` = u[0]).
      ``legacy_model=True`` 면 예전 형식(node_id,x0,y0,z0 만).
    - ``elem_nodes``: (E,3|4) 요소별 노드 ID(0·음수 = 없음 → 삼각형 n4=0)를 주면 elems.csv + done.json
      ``elems_ok: true`` (TCL 0.5.5 와 같음). None 이면 elems.csv 를 쓰지 않음(예전 TCL 출력 흉내).
    """
    from esl.mech import strain, tstar

    d = os.fspath(dir)
    os.makedirs(d, exist_ok=True)
    t = np.asarray(frames_time, dtype=np.float64).reshape(-1)
    F = t.size
    fi = np.arange(F) if frame_index is None else np.asarray(frame_index, dtype=np.int64)
    node_id = np.asarray(node_id, dtype=np.int64)
    x0 = np.asarray(x0, dtype=np.float64).reshape(-1, 3)
    u = np.asarray(u, dtype=np.float64).reshape(F, node_id.size, 3)
    elem_id = np.asarray(elem_id, dtype=np.int64)
    E = elem_id.size
    eps = np.asarray(eps, dtype=np.float64).reshape(F, E, 3)
    vm = strain.eps_eq(eps) if vm_hv is None else np.asarray(vm_hv, dtype=np.float64).reshape(F, E)
    zz = -(eps[..., 0] + eps[..., 1]) if ezz is None else np.asarray(ezz, dtype=np.float64).reshape(F, E)
    ep = np.zeros((F, E)) if epsp is None else np.asarray(epsp, dtype=np.float64).reshape(F, E)
    vals = np.stack([vm, eps[..., 0], eps[..., 1], zz, eps[..., 2], ep], axis=-1)     # (F,E,6) SCOLS 순
    xn = [] if extra_nodes is None else [int(v) for v in extra_nodes]
    xe = [] if extra_elems is None else [int(v) for v in extra_elems]
    g = "{:.17g}".format

    H = tstar.hot_set(vm[-1], ep[-1], hot_k)
    cand = {}
    cel = {}
    for m, v in (("max_strain", vm[:, H]), ("plastic_strain", ep[:, H])):
        cf = tstar.candidate_frames(v, reach_rtol, top_n)
        cand[m] = [int(fi[f]) for f, _ in cf]
        cel[m] = [int(elem_id[H[e]]) for _, e in cf]
    if frames_D is None:
        Dset = sorted({x for v in cand.values() for x in v})
    else:                                   # D 강제: D 밖 후보는 버림(시험용)
        Dset = sorted(int(x) for x in frames_D)
        for m in cand:
            keep = [i for i, f in enumerate(cand[m]) if f in Dset]
            cand[m] = [cand[m][i] for i in keep]
            cel[m] = [cel[m][i] for i in keep]
    dpos = [int(np.flatnonzero(fi == f)[0]) for f in Dset]
    Pset = sorted({int(fi[k - 1]) for k in dpos if k > 0})          # 직전 프레임(frames 순서)
    CF = sorted(set(Dset) | set(Pset)) if write_prev else list(Dset)
    spos = [int(np.flatnonzero(fi == f)[0]) for f in CF]

    def row(a):
        return ",".join(g(x) for x in a)

    with open(os.path.join(d, "frames.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,time\n")
        for k in range(F):
            fh.write(f"{int(fi[k])},{g(t[k])}\n")
    with open(os.path.join(d, "model.csv"), "w", encoding="utf-8", newline="") as fh:
        if legacy_model:
            fh.write("node_id,x0,y0,z0\n")
            for k in range(node_id.size):
                fh.write(f"{int(node_id[k])},{row(x0[k])}\n")
            for n in xn:
                fh.write(f"{n},0,0,0\n")
        else:
            fh.write("node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz\n")
            c0 = x0 + u[0]
            for k in range(node_id.size):
                fh.write(f"{int(node_id[k])},{row(c0[k] - u[0, k])},{row(c0[k])},{row(u[0, k])}\n")
            for n in xn:
                fh.write(f"{n},0,0,0,0,0,0,0,0,0\n")
    if elem_nodes is not None:
        en = np.asarray(elem_nodes, dtype=np.int64).reshape(E, -1)
        en = np.where(en > 0, en, 0)
        if en.shape[1] < 4:
            en = np.c_[en, np.zeros((E, 4 - en.shape[1]), np.int64)]
        with open(os.path.join(d, "elems.csv"), "w", encoding="utf-8", newline="") as fh:
            fh.write(",".join(ELEMS_COLS) + "\n")
            for e in range(E):
                fh.write(f"{int(elem_id[e])}," + ",".join(str(int(v)) for v in en[e, :4]) + "\n")
            for e in xe:
                fh.write(f"{e},1,2,3,0\n")
    zero6 = ",".join(["0"] * 6)
    with open(os.path.join(d, "final.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("elem_id," + ",".join(SCOLS) + "\n")
        for e in range(E):
            fh.write(f"{int(elem_id[e])},{row(vals[-1, e])}\n")
        for e in xe:
            fh.write(f"{e},{zero6}\n")
    with open(os.path.join(d, "history.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,elem_id," + ",".join(SCOLS) + "\n")
        for k in range(F):
            for e in H:
                fh.write(f"{int(fi[k])},{int(elem_id[e])},{row(vals[k, e])}\n")
    with open(os.path.join(d, "strain_frames.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,elem_id," + ",".join(SCOLS) + "\n")
        for k in spos:
            for e in range(E):
                fh.write(f"{int(fi[k])},{int(elem_id[e])},{row(vals[k, e])}\n")
            for e in xe:
                fh.write(f"{int(fi[k])},{e},{zero6}\n")
    with open(os.path.join(d, "disp.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("frame_index,node_id,ux,uy,uz\n")
        for k in dpos:
            for n in range(node_id.size):
                fh.write(f"{int(fi[k])},{int(node_id[n])},{row(u[k, n])}\n")
            for n in xn:
                fh.write(f"{int(fi[k])},{n},0,0,0\n")
    if write_done:
        done: dict[str, Any] = {
            "ok": True, "n_frames": int(F), "n_elems": int(E + len(xe)), "n_nodes": int(node_id.size + len(xn)),
            "n_hot": int(H.size), "hot_k": int(hot_k), "top_n": int(top_n), "reach_rtol": float(reach_rtol),
            "candidate_frames": cand, "candidate_elems": cel, "frames_D": Dset, "h3d": h3d,
            **({"prev_frames": Pset, "strain_frames": CF} if write_prev else {}),
            "strain_type": "Max_Strain", "strain_layer": "Mid", "epsp_type": "Plastic Strain", "epsp_layer": "Mid",
            "disp_type": "Displacement", "frame0_time": float(t[0]),
            **({} if legacy_model else {"model_coords": "coords_minus_disp_frame0"}),
            **({} if elem_nodes is None else {"elems_ok": True, "n_conn": int(E + len(xe))}), "warnings": []}
        with open(os.path.join(d, "done.json"), "w", encoding="utf-8") as fh:
            json.dump(done, fh)
    return d
