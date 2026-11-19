"""경계력 원자료 ESL 때 보충 — bf 전용 추출 결과 병합·시도 기록(계약 esl_bforce_ondemand.md §4, D-0.24.2-BFD-5·6).

덤프 방식 등 01_extract 에 선택 프레임의 경계력 원자료가 없으면 워커가 그 프레임만 HyperView bf 전용 추출(TCL bf_only)로
읽어 `fill_out`(= `<esl_root>/_h3d/<Case 폴더>/bf_ondemand/raw`) 에 쓰고, 이 모듈이 Case `01_extract/bforce.npz`·
`bforce.json` 에 병합한다(다음 ESL 부터 재사용). 시도 기록(`01_extract/bforce_ondemand.json`)은 워커가 쓰고(record)
코어 ESL 단계가 읽는다(note) — 형식 소유는 이 모듈 한 곳.

규칙: 프레임 = 기존 ∪ 새 프레임(오름차순), 기존 프레임 자료 우선(덮어쓰지 않음 — dup), 노드 = model.npz 순서, 종류별
`kinds[k].frames`(그 종류 자료가 있는 프레임), 같은 h3d 확인(서브케이스 프레임 수·프레임 시간 정확 일치 — 아니면
BF_FILL_MISMATCH, 아무것도 쓰지 않음). 쓰기 = 임시 파일 → 이전 파일 사본을 `<Case>/_backup/<UTC>/01_extract/` 에 남김
→ os.replace(npz → json, json 의 frames 가 "있음" 기준이라 마지막). 설정을 해석하지 않는다(이름 후보는 names 인수).
독립 모듈: numpy·esl.errors·esl.io.bforce_csv·esl.io.results_csv·esl.io.backup 만 import(esl.pipeline·esl.doe 금지).
"""
from __future__ import annotations

import datetime as _dt
import json
import os

import numpy as np

from esl.errors import EslError
from esl.io import backup as _bk
from esl.io import bforce_csv as _bf
from esl.io.results_csv import _lookup, savez_stream

EXTRACT = "01_extract"
RECORD = "bforce_ondemand.json"
RECORD_SCHEMA = "esl/bforce_ondemand/1"
STATUSES = ("ok", "failed", "skipped")
CODE_OF = {"failed": "BF_EXTRACT_FAILED", "skipped": "BF_EXTRACT_SKIPPED"}   # 시도 status → 코어 요약 code
FILL_MODE = "bf_only"                     # TCL bf 전용 done.json mode
MERGE_TRIES = 3                           # 병합 직전 bforce.json 재확인이 다르면 처음부터 다시(동시성 방어, §4.4-2)


def _utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _write_json_atomic(path: str, doc: dict) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    _bk.replace(tmp, path)


def _norm_names(names) -> str:
    """names 비교용 정규 문자열(튜플·리스트 차이 무시)."""
    return json.dumps(names, sort_keys=True, ensure_ascii=False, default=list)


# ====================================================================== 병합
def _fill_done(fill_out: str, frames: list[int]) -> dict:
    """bf 전용 추출 done.json(성공·mode bf_only·bforce·요청 프레임 포함) — 아니면 BF_FILL_OUTPUT."""
    p = os.path.join(fill_out, "done.json")
    try:
        done = _read_json(p)
    except (OSError, ValueError) as exc:
        raise EslError("BF_FILL_OUTPUT", f"bf 전용 추출 done.json 을 읽을 수 없음: {p}: {exc}") from None
    if not isinstance(done, dict) or done.get("ok") is not True:
        raise EslError("BF_FILL_OUTPUT", f"bf 전용 추출이 성공이 아님(done.json ok {None if not isinstance(done, dict) else done.get('ok')})")
    if done.get("mode") != FILL_MODE:
        raise EslError("BF_FILL_OUTPUT", f"bf 전용 추출 출력이 아님(done.json mode {done.get('mode')!r})")
    bfd = done.get("bforce")
    if not isinstance(bfd, dict) or not bfd.get("on"):
        raise EslError("BF_FILL_OUTPUT", "bf 전용 추출 done.json 에 bforce 가 없음")
    got = {int(f) for f in (bfd.get("frames") or [])}
    miss = sorted(set(frames) - got)
    if miss:
        raise EslError("BF_FILL_OUTPUT", f"bf 전용 추출에 요청 프레임 {miss} 이 없음(있는 프레임 {sorted(got)})")
    return done


def _same_h3d(xd: str, done: dict, frames: list[int]) -> None:
    """서브케이스 프레임 수 = 추출 frames.json n_frames_h3d, 요청 프레임 시간 = 추출 때 시간(정확 일치 — 같은 TCL sim_time
    %.17g). 다르면 BF_FILL_MISMATCH."""
    p = os.path.join(xd, "frames.json")
    try:
        meta = _read_json(p)
    except (OSError, ValueError) as exc:
        raise EslError("BF_FILL_MERGE", f"01_extract/frames.json 을 읽을 수 없음: {exc}") from None
    n_x = meta.get("n_frames_h3d")
    n_f = done.get("n_frames")
    if n_x is None or n_f is None or int(n_x) != int(n_f):
        raise EslError("BF_FILL_MISMATCH", f"h3d 프레임 {n_f} ≠ 추출 {n_x}")
    t_of = {}
    for fs, ts in ((meta.get("frame_index"), meta.get("time")), (meta.get("frames_D"), meta.get("time_D"))):
        if isinstance(fs, list) and isinstance(ts, list):
            t_of.update({int(f): float(t) for f, t in zip(fs, ts)})
    dfr = [int(f) for f in (done.get("frames") or [])]
    dts = list(done.get("frame_times") or [])
    for f in frames:
        if f not in t_of:
            raise EslError("BF_FILL_MISMATCH", f"프레임 {f} 이 추출 프레임 목록에 없음")
        if f not in dfr or dfr.index(f) >= len(dts):
            raise EslError("BF_FILL_MISMATCH", f"bf 전용 추출 done.json 에 프레임 {f} 시간이 없음")
        t_new = float(dts[dfr.index(f)])
        if t_new != t_of[f]:
            raise EslError("BF_FILL_MISMATCH", f"프레임 {f} 시간 {t_new!r} ≠ {t_of[f]!r}")


def _node_ids(xd: str) -> np.ndarray:
    p = os.path.join(xd, "model.npz")
    try:
        with np.load(p, allow_pickle=False) as z:
            return np.asarray(z["node_id"], dtype=np.int64)
    except (OSError, KeyError, ValueError) as exc:
        raise EslError("BF_FILL_MERGE", f"01_extract/model.npz node_id 를 읽을 수 없음: {exc}") from None


def _old_arrays(xd: str, doc: dict | None, old_frames: list[int], nid: np.ndarray) -> tuple[dict, dict]:
    """기존 bforce.npz → ({kind: (len(old_frames), N[,3]) 배열}, {kind: 자료가 있는 old 프레임}). bforce.json frames 의
    프레임만 읽고(그 밖 행 무시) 노드는 nid 순서로(없는 노드 = 0)."""
    zp = os.path.join(xd, _bf.NPZ)
    arrs: dict = {}
    have: dict = {}
    if not old_frames or not os.path.isfile(zp):
        return arrs, have
    kd = (doc or {}).get("kinds") or {}
    with np.load(zp, allow_pickle=False) as z:
        zf = np.asarray(z["frame_index"]).astype(np.int64)
        zn = np.asarray(z["node_id"]).astype(np.int64)
        rows = [int(np.flatnonzero(zf == f)[0]) if np.any(zf == f) else -1 for f in old_frames]
        same = np.array_equal(zn, nid)
        pos = _lookup(zn, nid)                                        # nid → 기존 npz 노드 위치
        okn = pos >= 0
        for k in _bf.KINDS:
            rec = kd.get(k)
            if k not in z.files or not isinstance(rec, dict) or not rec.get("type"):
                continue
            src = np.asarray(z[k])
            a = np.zeros((len(old_frames), nid.size) + src.shape[2:], dtype=np.float64)
            fl = rec.get("frames")
            want = set(int(f) for f in fl) if isinstance(fl, list) else set(old_frames)
            got = []
            for i, (f, r) in enumerate(zip(old_frames, rows)):
                if r < 0 or f not in want:
                    continue
                if same:
                    a[i] = src[r]
                else:
                    a[i][okn] = src[r][pos[okn]]
                got.append(f)
            if got:
                arrs[k] = a
                have[k] = got
    return arrs, have


def _combine(old_doc, old_frames, old_arr, old_have, add, new_kinds, new_arr, nid):
    """기존 + 새 프레임 → (frames_after, kinds 문서, 배열)."""
    after = sorted(set(old_frames) | set(add))
    pos = {f: i for i, f in enumerate(after)}
    okd = (old_doc or {}).get("kinds") or {}
    kinds: dict = {}
    arrays: dict = {}
    for k in _bf.KINDS:
        orec = okd.get(k) if isinstance(okd.get(k), dict) else {}
        nrec = new_kinds.get(k) if isinstance(new_kinds.get(k), dict) else {}
        fr_k = sorted(set(old_have.get(k, [])) | (set(add) if k in new_arr else set()))
        if not fr_k:
            reason = nrec.get("reason") or orec.get("reason") or "not dumped"
            kinds[k] = {"type": None, "reason": reason}
            continue
        src = nrec if nrec.get("type") and k in new_arr else orec      # 가장 최근 non-null
        o_rows = int(orec.get("rows") or 0) if k in old_have else 0
        o_miss = int(orec.get("n_missing") or 0) if k in old_have else 0
        n_rows = int(nrec.get("rows") or 0) if k in new_arr else 0
        n_miss = int(nrec.get("n_missing") or 0) if k in new_arr else 0
        kinds[k] = {"type": src.get("type"), "comps": list(src.get("comps") or []), "rows": o_rows + n_rows,
                    "n_missing": o_miss + n_miss, "frames": fr_k}
        ref = old_arr.get(k) if k in old_arr else new_arr[k]
        a = np.zeros((len(after), nid.size) + ref.shape[2:], dtype=np.float64)
        if k in old_arr:
            for i, f in enumerate(old_frames):
                if f in old_have[k]:
                    a[pos[f]] = old_arr[k][i]
        if k in new_arr:
            for i, f in enumerate(add):
                a[pos[f]] = new_arr[k][i]
        arrays[k] = a
    return after, kinds, arrays


def _merge(case_dir: str, fill_out: str, frames, *, tag: str | None, names: dict | None) -> dict:
    """bf 전용 추출 출력(fill_out) → Case 01_extract/bforce.npz·bforce.json 병합(계약 §4.1·§4.2).

    반환 {frames_before, frames_after, added, dup, kinds: {k: type|null}(이번 추출), rows: {k: n}(이번 행),
    backup: <case 기준 상대경로>|null, warnings}. 오류 = EslError(BF_FILL_OUTPUT: bf 전용 성공 출력이 아님,
    BF_FILL_MISMATCH: 같은 h3d 아님, BF_FILL_MERGE: 01_extract 읽기·동시 변경) — 이때 01_extract 에 아무것도 쓰지 않음."""
    frames = sorted({int(f) for f in frames})
    if not frames:
        raise EslError("BF_FILL_OUTPUT", "병합할 프레임이 없음")
    xd = os.path.join(case_dir, EXTRACT)
    done = _fill_done(fill_out, frames)
    _same_h3d(xd, done, frames)
    nid = _node_ids(xd)
    bfd = done["bforce"]
    fill_kinds = {k: ((bfd.get("kinds") or {}).get(k) or {}).get("type") for k in _bf.KINDS}
    for _ in range(MERGE_TRIES):
        old_doc = _bf.read_doc(xd)
        old_frames = _bf.doc_frames(old_doc)
        add = [f for f in frames if f not in old_frames]
        dup = [f for f in frames if f in old_frames]
        warnings = []
        if dup:
            warnings.append(f"BF_FILL_DUP: 프레임 {dup} 은 이미 01_extract 에 있음 — 기존 자료 유지(덮어쓰지 않음)")
        res = {"frames_before": old_frames, "frames_after": sorted(set(old_frames) | set(add)), "added": add,
               "dup": dup, "kinds": fill_kinds, "rows": {}, "backup": None, "warnings": warnings}
        if not add:
            return res
        new_kinds, new_arr = _bf._pack_kinds(fill_out, nid, add, bfd)
        res["kinds"] = {k: v.get("type") for k, v in new_kinds.items()}
        res["rows"] = {k: int(v.get("rows") or 0) for k, v in new_kinds.items() if v.get("type")}
        for k, v in new_kinds.items():
            if v.get("type") and int(v.get("n_missing") or 0):
                warnings.append(f"BF_FILL_MISSING: {k} 값 없는 (프레임, 노드) {v['n_missing']}개 = 0")
        old_arr, old_have = _old_arrays(xd, old_doc, old_frames, nid)
        after, kinds, arrays = _combine(old_doc, old_frames, old_arr, old_have, add, new_kinds, new_arr, nid)
        fills = list((old_doc or {}).get("fills") or []) if (old_doc or {}).get("on") else []
        fills.append({"frames": add, "job_id": tag, "at": _utc(), "kinds": res["kinds"], "h3d": done.get("h3d"),
                      "names": names})
        write_npz = bool(new_arr)                     # 새 프레임 종류 없음 = npz 그대로(옛 프레임 자료), json 만
        doc = {"schema": _bf.SCHEMA, "on": True, "kinds": kinds, "frames": after, "fills": fills}
        jp, zp = os.path.join(xd, _bf.JSON), os.path.join(xd, _bf.NPZ)
        jtmp, ztmp = f"{jp}.tmp-{os.getpid()}", f"{zp}.tmp-{os.getpid()}"
        try:
            if write_npz:                                 # 1) 임시 파일
                savez_stream(ztmp, frame_index=np.asarray(after, dtype=np.int32), node_id=nid, **arrays)
            with open(jtmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=1)
            cur = _bf.read_doc(xd)
            if _bf.doc_frames(cur) != old_frames or (cur is None) != (old_doc is None):
                for t in (jtmp, ztmp):                     # 2) 그사이 바뀜 → 처음부터 다시(임시 파일만 지움)
                    if os.path.isfile(t):
                        os.remove(t)
                continue
            olds = [p for p in ((zp, jp) if write_npz else (jp,)) if os.path.isfile(p)]
            if olds:                                      # 3) 이전 파일 사본 → <Case>/_backup/<UTC>/01_extract/
                bdir = os.path.join(case_dir, _bk.BACKUP_DIR, _bk.utc_stamp(), EXTRACT)
                for p in olds:
                    _bk.keep_copy(p, bdir)
                res["backup"] = os.path.relpath(bdir, case_dir).replace(os.sep, "/")
            if write_npz:                                 # 4) npz → json 순 교체
                _bk.replace(ztmp, zp)
            _bk.replace(jtmp, jp)
            return res
        finally:                                      # 실패·재시도로 남은 이번 호출(pid)의 임시 파일만 지움(이전 파일은 건드리지 않음)
            for t in (jtmp, ztmp):
                try:
                    if os.path.isfile(t):
                        os.remove(t)
                except OSError:
                    pass
    raise EslError("BF_FILL_MERGE", f"01_extract/bforce.json 이 병합 중 계속 바뀜({MERGE_TRIES}회) — 다시 계산하면 재시도")


def merge(case_dir: str, fill_out: str, frames, *, tag: str | None, names: dict | None) -> dict:
    """_merge + EslError 가 아닌 예외(npz 손상 BadZipFile·ValueError·KeyError 등)는 BF_FILL_MERGE 로 분류(워커는 MERGE)."""
    try:
        return _merge(case_dir, fill_out, frames, tag=tag, names=names)
    except EslError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EslError("BF_FILL_MERGE", f"병합 중 예기치 않은 오류 {type(exc).__name__}: {str(exc)[:200]}") from None


# ====================================================================== 시도 기록

def _record_path(extract_dir: str) -> str:
    return os.path.join(extract_dir, RECORD)


def read_record(extract_dir: str) -> dict | None:
    """01_extract/bforce_ondemand.json(없거나 읽기·형식 오류 = None)."""
    p = _record_path(extract_dir)
    if not os.path.isfile(p):
        return None
    try:
        doc = _read_json(p)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("attempts"), list):
        return None
    return doc


def attempts(extract_dir: str) -> list[dict]:
    doc = read_record(extract_dir)
    return [a for a in (doc or {}).get("attempts", []) if isinstance(a, dict)]


def record(extract_dir: str, attempt: dict) -> None:
    """시도 기록 1건 추가(누적, tmp → replace). attempt = 계약 §4.6 항목(frame_index·job_id·status 필수, code 가 없으면
    status 로 채움, at 이 없으면 지금). 기존 파일이 읽히지 않으면 <Case>/_backup/<UTC>/01_extract/ 로 옮긴 뒤 새로 시작."""
    if not isinstance(attempt, dict) or attempt.get("status") not in STATUSES:
        raise EslError("INPUT_INVALID", f"보충 시도 기록 status 는 {STATUSES} 중 하나: {attempt!r:.200}")
    try:
        int(attempt.get("frame_index"))
    except (TypeError, ValueError):
        raise EslError("INPUT_INVALID", "보충 시도 기록에 frame_index 가 없음") from None
    a = dict(attempt)
    a["frame_index"] = int(a["frame_index"])
    if not a.get("code"):
        a["code"] = CODE_OF.get(a["status"])
    a.setdefault("at", _utc())
    p = _record_path(extract_dir)
    doc = read_record(extract_dir)
    if doc is None and os.path.isfile(p):             # 깨진 기록 = 지우지 않고 백업
        bdir = os.path.join(os.path.dirname(extract_dir), _bk.BACKUP_DIR, _bk.utc_stamp(), EXTRACT)
        os.makedirs(bdir, exist_ok=True)
        _bk.replace(p, _bk.free_target(bdir, RECORD))
    if doc is None:
        doc = {"schema": RECORD_SCHEMA, "attempts": []}
    doc["attempts"].append(a)
    os.makedirs(extract_dir, exist_ok=True)
    _write_json_atomic(p, doc)


def note(extract_dir: str, frame: int, tag: str | None) -> dict | None:
    """이 작업(tag)·이 프레임의 마지막 시도가 failed·skipped 면 {code, cause, detail}, 아니면 None(tag 없음 = None)."""
    if tag is None:
        return None
    last = None
    for a in attempts(extract_dir):
        try:
            if str(a.get("job_id")) == str(tag) and int(a.get("frame_index")) == int(frame):
                last = a
        except (TypeError, ValueError):
            continue
    if last is None or last.get("status") not in CODE_OF:
        return None
    return {"code": last.get("code") or CODE_OF[last["status"]], "cause": last.get("cause"),
            "detail": str(last.get("detail") or "")}


def no_types_before(extract_dir: str, names) -> dict | None:
    """판정 5: 같은 이름 후보(names)로 한 가장 최근 성공 시도가 종류를 하나도 못 찾았으면 그 시도, 아니면 None."""
    want = _norm_names(names)
    last = None
    for a in attempts(extract_dir):
        if a.get("status") == "ok" and _norm_names(a.get("names")) == want:
            last = a
    if last is None:
        return None
    kinds = last.get("kinds")
    if isinstance(kinds, dict) and kinds and all(v is None for v in kinds.values()):
        return last
    return None
