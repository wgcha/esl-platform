"""Radioss 상태 파일(.str 형상·.sta 초기 상태) 보조 (계약 esl_cumulative_input.md §2·§3.4·§3.5·§5).

- ``is_state_file(path)``: 첫 비어 있지 않은 행이 ``#RADIOSS STATE FILE`` 이거나 확장자 .sta/.str.
- ``read_epsp_f(segs, elem_id_sorted)``: ``/INISHE/EPSP_F`` 블록에서 대상 요소만 숫자 해석(스트리밍) → EpspInit.
- ``compare_begin(main, state)``: /BEGIN 단위 배율 비교.
- ``thickness_stats(...)``: t/t₀ 통계.

레코드(EPSP_F): 헤더 ``SHELLID(I10) NPT(I10) NPG(I10) THK(F20)`` + 값 ``max(1,NPT)·NPG`` 개를 20자 필드 5개씩
흘려 쓴 행들(``EPSP(IPG,IPT)``, IPG 가 빠름). 대상 밖 레코드는 숫자 해석 없이 행 수만큼 건너뛴다.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field

import numpy as np

from esl.errors import EslError

STATE_EXT = (".sta", ".str")
STATE_HEADER = "#radioss state file"
NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?")
_FORTRAN_EXP = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d+)$")
# 값을 모아 한 번에 해석하는 묶음(레코드 수) — 메모리 상한(≈ 묶음 × 20값 × 20 B)
FLUSH_RECORDS = 20_000
AGGS = ("mid_mean", "mid_max", "max", "mean")


def has_state_ext(path: str) -> bool:
    return os.path.splitext(str(path).replace("\\", "/").rstrip("/"))[1].lower() in STATE_EXT


def read_state_header(path: str) -> bool:
    """첫 비어 있지 않은 행이 #RADIOSS STATE FILE 로 시작하면 True(읽기 실패 False)."""
    try:
        with open(path, "rb") as fh:
            for _ in range(200):
                raw = fh.readline()
                if not raw:
                    return False
                s = raw.lstrip(b"\xef\xbb\xbf").strip()
                if s:
                    return s[:len(STATE_HEADER)].decode("latin-1").lower() == STATE_HEADER
    except OSError:
        return False
    return False


def is_state_file(path: str) -> bool:
    return has_state_ext(path) or read_state_header(path)


def state_err(msg: str) -> EslError:
    return EslError("STATE_PARSE_ERROR", msg)


def parse_real(text) -> float:
    """F20 실수(빈 칸 0 아님 → 오류). Fortran D 지수·'1.0-3' 허용."""
    s = text.decode("latin-1").strip() if isinstance(text, (bytes, bytearray)) else str(text).strip()
    if not s:
        raise ValueError("빈 실수 필드")
    try:
        return float(s)
    except ValueError:
        pass
    s2 = s.replace("D", "E").replace("d", "e")
    try:
        return float(s2)
    except ValueError:
        m = _FORTRAN_EXP.match(s2)
        if m:
            return float(f"{m.group(1)}e{m.group(2)}")
    raise ValueError(f"실수 필드를 읽을 수 없음: {s!r}")


def split_reals(line: str) -> list[float]:
    """공백 구분 토큰(Fortran '1.0-3'·D 지수 포함), 토큰 안에 붙은 실수(-4.45E+01-4.72E+01)는 정규식으로 분리(§3.1)."""
    out = []
    for tok in line.split():
        try:
            out.append(parse_real(tok))
        except ValueError:
            parts = NUM_RE.findall(tok)
            if not parts or "".join(parts) != tok:
                raise ValueError(f"실수 토큰을 읽을 수 없음: {tok!r}") from None
            out += [float(x.replace("D", "E").replace("d", "e")) for x in parts]
    return out


def _header(raw: bytes):
    """헤더 행이면 (sid, npt, npg, thk), 아니면 None."""
    try:
        sid, npt, npg = int(raw[0:10]), int(raw[10:20]), int(raw[20:30])
    except ValueError:
        return None
    t = raw[30:50]
    try:
        thk = float(t)
    except ValueError:
        try:
            thk = parse_real(t)
        except ValueError:
            return None
    return sid, npt, npg, thk


@dataclass
class EpspInit:
    elem_id: np.ndarray
    has: np.ndarray
    npt: np.ndarray
    npg: np.ndarray
    thk: np.ndarray
    agg: dict = field(default_factory=dict)
    n_records: int = 0
    n_dup: int = 0
    dup_ids: list = field(default_factory=list)
    resync_lines: int = 0
    fallback_rows: int = 0


def _flush(buf: list, recs: list, out_agg: dict, path_of) -> None:
    """recs = [(pos, P, G, nvals_offset, file, line)] · buf = 값 필드 문자열(20자 고정폭으로 맞춤) 조각."""
    if not recs:
        return
    data = b"".join(buf)
    n = len(data) // 20
    try:
        vals = np.frombuffer(data, dtype="S20", count=n).astype(np.float64)
    except ValueError:
        vals = np.empty(n, dtype=np.float64)
        for i in range(n):
            try:
                vals[i] = parse_real(data[20 * i:20 * (i + 1)])
            except ValueError as exc:
                # 어느 레코드인지 찾기
                rec = next(r for r in reversed(recs) if r[3] <= i)
                raise state_err(f"/INISHE/EPSP_F 값 해석 실패 ({rec[4]}:{rec[5]}): {exc}") from None
    pos = np.array([r[0] for r in recs], dtype=np.int64)
    P = np.array([r[1] for r in recs], dtype=np.int64)
    G = np.array([r[2] for r in recs], dtype=np.int64)
    off = np.array([r[3] for r in recs], dtype=np.int64)
    for p_, g_ in set(zip(P.tolist(), G.tolist())):
        sel = (P == p_) & (G == g_)
        idx = off[sel][:, None] + np.arange(p_ * g_)[None, :]
        v = vals[idx].reshape(-1, p_, g_)                 # [rec, IPT, IPG]
        if p_ % 2:
            mid = v[:, p_ // 2, :]
        else:
            mid = 0.5 * (v[:, p_ // 2 - 1, :] + v[:, p_ // 2, :])
        ps = pos[sel]
        out_agg["mid_mean"][ps] = mid.mean(axis=1)
        out_agg["mid_max"][ps] = mid.max(axis=1)
        out_agg["max"][ps] = v.reshape(v.shape[0], -1).max(axis=1)
        out_agg["mean"][ps] = v.reshape(v.shape[0], -1).mean(axis=1)
    buf.clear()
    recs.clear()


def read_epsp_f(segs, elem_id_sorted) -> EpspInit:
    """``segs`` = [(file, off, line0, nlines)] (/INISHE/EPSP_F 블록 본문 위치), elem_id_sorted (E,) 오름차순.

    대상 요소 레코드는 값 개수·형식을 엄격히 확인(STATE_PARSE_ERROR 파일:행), 대상 밖은 행만 건너뛴다.
    같은 SHELLID 가 여러 번 나오면 마지막 우선(n_dup·dup_ids 기록). 원값 배열은 보관하지 않는다.
    """
    eid = np.asarray(elem_id_sorted, dtype=np.int64)
    E = eid.size
    want = dict(zip(eid.tolist(), range(E)))
    get = want.get
    has = np.zeros(E, dtype=bool)
    npt = np.zeros(E, dtype=np.int16)
    npg = np.zeros(E, dtype=np.int16)
    thk = np.zeros(E, dtype=np.float64)
    agg = {k: np.zeros(E, dtype=np.float64) for k in AGGS}
    buf: list[bytes] = []
    recs: list = []
    nvals = 0
    n_rec = n_dup = resync = fallback = 0
    dup_ids: list[int] = []
    files: dict = {}
    try:
        for (path, off, line0, nlines) in segs:
            fh = files.get(path) or files.setdefault(path, open(path, "rb"))
            fh.seek(off)
            readline = fh.readline
            i = 0
            lineno = line0 - 1
            back = None
            while i < nlines or back is not None:
                if back is not None:
                    raw, back = back, None
                else:
                    raw = readline()
                    i += 1
                    lineno += 1
                if not raw:
                    break
                c = raw[:1]
                if c == b"#":
                    continue
                if not raw.strip():
                    continue
                h = _header(raw)
                if h is None:
                    resync += 1                 # 대상 밖 레코드 형식 차이 → 다음 헤더까지 건너뜀
                    continue
                sid, p_raw, g, t = h
                k = get(sid)
                if g < 1 or p_raw < 0:
                    if k is not None:
                        raise state_err(f"/INISHE/EPSP_F 헤더 NPT={p_raw}·NPG={g} 이상 ({path}:{lineno})")
                    resync += 1
                    continue
                p = max(1, p_raw)
                kv = p * g
                n_rec += 1
                if k is None:
                    # 대상 밖: 숫자 해석 없이 값 행만 건너뜀(5개/행 흐름, 주석·빈 행은 세지 않음)
                    left = -(-kv // 5)
                    while left > 0 and i < nlines:
                        raw2 = readline()
                        i += 1
                        lineno += 1
                        if not raw2:
                            break
                        if raw2[:1] == b"#" or not raw2.strip():
                            continue
                        if len(raw2.rstrip()) <= 50 and _header(raw2) is not None:
                            back = raw2             # 값이 모자란 비대상 레코드: 다음 헤더부터 다시
                            resync += 1
                            break
                        left -= 1
                    continue
                # 대상 요소: 값 kv 개(행당 ceil(len/20) 개, 마지막 행 나머지)
                got = 0
                pieces = []
                l0 = lineno
                while got < kv:
                    if i >= nlines:
                        raise state_err(f"/INISHE/EPSP_F 요소 {sid} 값 {kv}개 중 {got}개만 있음 ({path}:{l0})")
                    raw2 = readline()
                    i += 1
                    lineno += 1
                    if not raw2:
                        raise state_err(f"/INISHE/EPSP_F 요소 {sid} 값이 파일 끝에서 끊김 ({path}:{lineno})")
                    if raw2[:1] == b"#" or not raw2.strip():
                        continue
                    ln = raw2.rstrip()
                    if len(ln) <= 50 and _header(ln) is not None:
                        raise state_err(f"/INISHE/EPSP_F 요소 {sid} 값 {kv}개 중 {got}개 뒤에 다음 헤더 "
                                        f"({path}:{lineno})")
                    L = len(ln)
                    if L % 20 == 0 and len(ln.split()) <= L // 20:
                        nf = L // 20                    # 표준 고정폭(오른쪽 정렬) — 묶음 해석은 _flush
                        fixed = ln
                    else:
                        nf = -(-L // 20)
                        try:                            # 왼쪽 정렬·Fortran 지수 고정폭
                            vv = [parse_real(ln[20 * j:20 * (j + 1)]) for j in range(nf)]
                        except ValueError:
                            try:
                                vv = split_reals(ln.decode("latin-1"))     # 공백 구분·붙은 실수
                            except ValueError:
                                vv = []
                            if not vv:
                                raise state_err(f"/INISHE/EPSP_F 요소 {sid} 값 행 해석 실패 ({path}:{lineno})") \
                                    from None
                        fallback += 1
                        nf = len(vv)
                        fixed = b"".join(f"{x:20.12E}".encode() for x in vv)
                    if got + nf > kv:
                        raise state_err(f"/INISHE/EPSP_F 요소 {sid} 값 개수 초과({got + nf} > {kv}) ({path}:{lineno})")
                    pieces.append(fixed)
                    got += nf
                if not t > 0:
                    raise state_err(f"/INISHE/EPSP_F 요소 {sid} THK={t} ≤ 0 ({path}:{l0})")
                if has[k]:
                    n_dup += 1
                    if len(dup_ids) < 10:
                        dup_ids.append(int(sid))
                has[k] = True
                npt[k] = p_raw
                npg[k] = g
                thk[k] = t
                buf.extend(pieces)
                recs.append((k, p, g, nvals, path, l0))
                nvals += kv
                if len(recs) >= FLUSH_RECORDS:
                    _flush(buf, recs, agg, None)
                    nvals = 0
        _flush(buf, recs, agg, None)
    finally:
        for fh in files.values():
            fh.close()
    return EpspInit(elem_id=eid, has=has, npt=npt, npg=npg, thk=thk, agg=agg, n_records=n_rec, n_dup=n_dup,
                    dup_ids=dup_ids, resync_lines=resync, fallback_rows=fallback)


def begin_values(rows: list[str]) -> dict:
    """/BEGIN 카드 행(runname / Invers Irun / 입력 단위 / 작업 단위) → {runname, units_in, units_work, numeric}."""
    def units(r):
        cells = [r[k * 20:(k + 1) * 20].strip() for k in range(3)]
        try:
            return [float(c) for c in cells], True
        except ValueError:
            try:
                return [parse_real(c) for c in cells], True
            except ValueError:
                return cells, False
    out = {"runname": rows[0].strip() if rows else ""}
    if len(rows) >= 3:
        out["units_in"], n1 = units(rows[2])
    else:
        out["units_in"], n1 = None, False
    if len(rows) >= 4:
        out["units_work"], n2 = units(rows[3])
    else:
        out["units_work"], n2 = None, False
    out["numeric"] = bool(n1 and (len(rows) < 4 or n2))
    return out


def compare_begin(main: dict | None, st: dict | None, rtol: float = 1e-6) -> dict:
    """§3.5: 둘 다 숫자 배율이면 상대 rtol 비교 → {compared, same, main, state}."""
    if not main or not st or not main.get("numeric") or not st.get("numeric"):
        return {"compared": False, "same": None, "main": main, "state": st}
    same = True
    for key in ("units_in", "units_work"):
        a, b = main.get(key), st.get(key)
        if a is None or b is None:
            continue
        for x, y in zip(a, b):
            if not math.isclose(float(x), float(y), rel_tol=rtol, abs_tol=0.0):
                same = False
    return {"compared": True, "same": same, "main": main, "state": st}


def thickness_stats(elem_id, thk_used, t0, from_state, source: str) -> dict:
    """§5 통계: t/t₀ (min, p01, mean, p99, max), |t/t₀−1| > 1 % 요소 수, 최대 감육."""
    elem_id = np.asarray(elem_id)
    t = np.asarray(thk_used, dtype=np.float64)
    t0 = np.asarray(t0, dtype=np.float64)
    ok = np.isfinite(t0) & (t0 > 0) & np.asarray(from_state, dtype=bool)
    out = {"source": source, "n_elems": int(elem_id.size), "n_state": int(np.sum(from_state))}
    if not ok.any():
        out.update(t0=None, ratio=None, n_changed=None, max_thinning_pct=None, elem_max_thinning=None)
        return out
    r = t[ok] / t0[ok]
    u = np.unique(t0[ok])
    imin = int(np.argmin(r))
    out.update(t0=float(u[0]) if u.size == 1 else [float(u.min()), float(u.max())],
               ratio={"min": float(r.min()), "p01": float(np.percentile(r, 1)), "mean": float(r.mean()),
                      "p99": float(np.percentile(r, 99)), "max": float(r.max())},
               n_changed=int(np.sum(np.abs(r - 1.0) > 0.01)),
               max_thinning_pct=float(max(0.0, (1.0 - r.min()) * 100.0)),
               elem_max_thinning=int(elem_id[ok][imin]))
    return out
