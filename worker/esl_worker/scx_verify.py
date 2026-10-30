"""VERIFY_DROP(XFER 레인, 계약 esl_scx_relay.md §9.2·SR-D-11~15): 원 Case 입력 사본 패치 → SCX 드라이브 올리기 → Radioss 제출 →
대기 → 결과(h3d·out) 회수. **어댑터 쓰기 메서드(ensure_new_dir·upload·submit_radioss·cancel·resolve)를 부르는 esl 모듈은 이것 하나**
(정적 시험 tests/test_static_scx.py) — 백엔드 [잡 ID 연결]·[포기]도 `resolve_submission` 을 부른다.

- 대상 = jobs.verify_drop_id. esl 이 쓰는 곳 = `<esl_root>/_verify/<id>/` 뿐: stage/<rel>(패치한 파일만), patch.json, morph.npz,
  stage.json(파일 rel·size·sha256·source — 절대경로 없음), submit_a<n>.json(제출 본문), scx_job.json(잡 상태·output_rel),
  result/(h3d·out), fetch.json, logs/<job_id>/. 원 Case 입력·DOE best/ 는 읽기만(VD_PREP 전후 sha·mtime 불변 — V-SR-14).
- VD_PREP : 재검사(입력 지문 INPUT_CHANGED, 추출 VD_CASE_NOT_READY, 누적·include 배치·엔진 rad) → 코어 자식 vd_patch → stage.json,
  합계 ≤ hpc.scx.max_stage_bytes.
- VD_STAGE: health(기능 B 사용 가능 재확인) → 드라이브 폴더 `<drive_base>/<프로젝트>/VD<no>_<UTC>`(ensure_new_dir — 재시도는 같은
  폴더) → 파일마다 upload(request_id `esl-vd-<id>-a1:f<i>`, 멱등) → 묶음 폴링(DONE 까지, PAUSED = 재로그인 대기, CONFLICT 실패,
  hpc.scx.stage_timeout_s).
- VD_SUBMIT: scx_submissions SUBMITTING 커밋 → submit_radioss(같은 request_id 로만 replay) → SUBMITTED | UNKNOWN(FAILED
  SCX_SUBMISSION_UNKNOWN — 자동 진행 금지) | FAILED. SUBMITTING 이 남아 있으면 같은 request_id·같은 본문으로 다시 보냄.
  최근 제출이 ABANDONED·FAILED 면 새 attempt(새 request_id).
- VD_WAIT : status 폴링(verify_drop.poll_s), SCX_JOB_NOT_FOUND 연속 lost_after_polls 회 → SCX_JOB_LOST, max_wait_h → VD_WAIT_TIMEOUT
  (SCX 잡은 종료하지 않음), Failed → SCX_RADIOSS_FAILED(마스킹 200자), Aborted·취소 계열 → CANCELED.
- VD_FETCH: output_rel(null → SCX_OUTPUT_UNRESOLVED) list → result_globs 파일(h3d 1개 — 여럿이면 starter stem 우선, out) 내려받기
  (sha256, 파일 단위 재시도) → out 판정(VD_RADIOSS_ABNORMAL) → 작업 성공 전이와 같은 트랜잭션에서 VERIFY_POST(SLOT) 큐.
- 취소: VD_STAGE = 폴링 중단(대기열 항목은 대시보드가 계속 올림), VD_WAIT(잡 ID 있음) = cancel(job_id) **1회** 후 CANCELED,
  VD_SUBMIT 중 취소 = 제출 결과가 정해진 뒤 처리.
- 외부 명령 없음(HTTP 만 — 노드 패치는 코어 자식 프로세스).
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import threading
import time
from typing import Any

from sqlalchemy import and_, func, select, update

from esl_platform.core.atomic import write_text_atomic
from esl_platform.core.db.tables import jobs as jobs_t
from esl_platform.core.db.tables import verify_drops as vd_t
from esl_platform.core.errors import DomainError, conflict, not_found
from esl_platform.core.inputs import changed_inputs, sha256_file
from esl_platform.core.job_types import VERIFY_STEP_WEIGHTS
from esl_platform.core.paths import doe_dir, esl_subdir, verify_dir
from esl_platform.core.repositories import cases as cases_repo
from esl_platform.core.repositories import doe as doe_repo
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import verify as vd_repo
from esl_platform.core.scx import messages
from esl_platform.core.scx import paths as scx_paths
from esl_platform.core.scx import status as scx_status
from esl_platform.core.scx.mask import mask_text
from esl_platform.core.scx.settings import run_stem, scx_cfg

POLL_S = 0.2
PROGRESS_S = 1.0
STAGE_JSON = "stage.json"
JOB_JSON = "scx_job.json"
FETCH_JSON = "fetch.json"
PART = ".part"
FINAL_OK = ("FINISHED",)


class PrepareFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class _Abort(Exception):
    """전송 스레드 중단(취소·lease 상실)."""


def _fail(code: str, message: str):
    from .executor import _StepFailed

    return _StepFailed(code, mask_text(message, 480))


def _gw_error():
    from esl_platform.core.scx.gateway import gateway_error

    return gateway_error()


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


# ---------------------------------------------------------------- 진행률(VERIFY_STEP_WEIGHTS 가중)
def job_progress(job_type: str, step_key: str, pct: float) -> float:
    done = 0.0
    for k, w in VERIFY_STEP_WEIGHTS.get(job_type, {}).items():
        if k == step_key:
            return done + w * max(0.0, min(100.0, pct)) / 100.0
        done += w
    return done


def mark_job_progress(conn, ex, step_key: str, pct: float) -> None:
    conn.execute(update(jobs_t).where(and_(jobs_t.c.id == ex.job["id"], jobs_t.c.lease_token == ex.token))
                 .values(progress_pct=job_progress(ex.job["job_type"], step_key, pct)))


# ---------------------------------------------------------------- 준비(VERIFY_DROP·VERIFY_POST 공용)
def prepare(ex) -> tuple[str, dict[str, Any]]:
    """작업 폴더 = <esl_root>/_verify/<id>(링크·탈출 검사). 검증·Case·스터디 행."""
    did = ex.job["verify_drop_id"]
    with ex.engine.connect() as conn:
        d = vd_repo.get_drop(conn, did)
        case = cases_repo.get_case(conn, d["case_id"]) if d else None
        study = doe_repo.get_study(conn, d["bead_doe_id"]) if d else None
    if d is None:
        raise PrepareFailed("VD_NOT_FOUND", messages.text("VD_NOT_FOUND"))
    if case is None or study is None:
        raise PrepareFailed("VD_CASE_NOT_READY", "원 Case 또는 강성 평가 스터디가 없습니다")
    try:
        cdir = verify_dir(ex.settings, did)
        os.makedirs(cdir, exist_ok=True)
        verify_dir(ex.settings, did)                    # 만든 뒤 다시(링크 탈출)
    except DomainError as exc:
        raise PrepareFailed(exc.code, exc.message) from None
    return cdir, {"drop": d, "case": case, "study": study}


def safe_path(cdir: str, *parts: str) -> str:
    """_verify/<id> 안 경로(성분 링크 거부, realpath ⊂ cdir)."""
    p = os.path.join(cdir, *parts)
    root = os.path.realpath(cdir)
    cur = cdir
    for seg in parts[:-1]:
        cur = os.path.join(cur, seg)
        if os.path.islink(cur):
            raise _fail("PATH_UNSAFE", "검증 폴더 안 심볼릭 링크는 허용하지 않습니다")
    if os.path.islink(p):
        raise _fail("PATH_UNSAFE", "검증 폴더 안 심볼릭 링크는 허용하지 않습니다")
    rp = os.path.realpath(os.path.dirname(p))
    if not (rp == root or rp.startswith(root + os.sep)):
        raise _fail("PATH_UNSAFE", "검증 폴더 밖 경로")
    return p


def _read(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path: str, obj: Any) -> None:
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=str))


# ---------------------------------------------------------------- 실행
def run_step(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    v = _Verify(ex, st, log_path)
    fn = {"VD_PREP": v.vd_prep, "VD_STAGE": v.vd_stage, "VD_SUBMIT": v.vd_submit, "VD_WAIT": v.vd_wait,
          "VD_FETCH": v.vd_fetch}.get(st["step_key"])
    if fn is None:
        raise _fail("INTERNAL_ERROR", f"알 수 없는 step {st['step_key']}")
    try:
        return fn()
    except DomainError as exc:
        v.echo(f"[esl-worker] {st['step_key']}: {exc.code} — {exc.message}")
        raise _fail(exc.extra.get("reason_code") or exc.code, exc.message) from None


class _Verify:
    def __init__(self, ex, st: dict[str, Any], log_path: str) -> None:
        self.ex, self.st, self.log_path = ex, st, log_path
        self.s = ex.settings
        self.p = ex.job["params"] or {}
        self.cdir = ex.cdir
        self.d = ex.lib["drop"]
        self.case = ex.lib["case"]
        self.study = ex.lib["study"]
        self.tick = {"renew": time.monotonic(), "cancel": time.monotonic()}
        self.gw = None
        self.health: dict[str, Any] = {}

    # ---- 공통
    def echo(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(mask_text(msg, None, paths=False) + "\n")

    def progress(self, pct: float, label: str | None) -> None:
        with self.ex._tx() as conn:
            jobs_repo.step_update(conn, self.ex.job["id"], self.ex.token, self.st["step_no"], progress_pct=float(pct))
            jobs_repo.set_progress(conn, self.ex.job["id"], self.ex.token,
                                   job_progress("VERIFY_DROP", self.st["step_key"], pct), label)

    def drop(self, **values: Any) -> dict[str, Any]:
        with self.ex._tx() as conn:
            jobs_repo.assert_lease(conn, self.ex.job["id"], self.ex.token)
            self.d = vd_repo.update_drop(conn, self.d["id"], **values)
        return self.d

    def reload(self) -> dict[str, Any]:
        with self.ex.engine.connect() as conn:
            self.d = vd_repo.get_drop(conn, self.d["id"])
        return self.d

    def wait(self, seconds: float, *, cancel: bool = True) -> None:
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            time.sleep(min(POLL_S, max(0.0, end - time.monotonic())))
            self._tick(cancel)

    def _tick(self, cancel: bool) -> None:
        if cancel:
            self.ex._wait_tick(self.tick)
            return
        w = self.s.worker
        now = time.monotonic()
        if now - self.tick["renew"] >= w.heartbeat_interval_s:
            self.ex._renew()
            self.tick["renew"] = now

    def connect(self) -> None:
        """health·기능 B 사용 가능 재확인(설정 변경·대시보드 다운 → 그 사유 코드)."""
        try:
            self.gw, self.health = scx_status.require_verify(self.s, self.ex.job["project_id"], force=True)
        except DomainError as exc:
            raise _fail(exc.extra.get("reason_code") or exc.code, exc.message) from None

    def call(self, what: str, fn, *, retries: int | None = None):
        """어댑터 호출 1회 + 재시도 가능한 오류(전송·SCX_BUSY 등)는 scx_drive.file_retries 회(대기 retry_wait_s)."""
        sd = self.s.scx_drive
        tries = 1 + int(sd.file_retries if retries is None else retries)
        for i in range(tries):
            try:
                return fn()
            except _gw_error() as exc:
                f = messages.classify(exc)
                if not f.retryable or i == tries - 1:
                    raise _fail(f.code, f"{f.message} — {what}") from None
                self.echo(f"[esl-worker] {what}: {f.code} — {float(sd.retry_wait_s):g}s 뒤 다시({i + 1}/{tries - 1})")
                self.wait(float(sd.retry_wait_s))
        raise _fail("SCX_UNAVAILABLE", what)                         # pragma: no cover

    def threaded(self, fn, *, label: str, size: int | None = None, cancel: bool = True, lo: float = 0.0,
                 hi: float = 100.0):
        """fn(on_chunk) 을 별도 스레드에서 — 이 스레드는 lease 갱신·취소 확인·진행률. 취소면 다음 청크에서 끊음."""
        stt: dict[str, Any] = {"got": 0, "abort": False, "done": False, "res": None, "err": None}

        def cb(n: int) -> None:
            stt["got"] += n
            if stt["abort"]:
                raise _Abort()

        def run() -> None:
            try:
                stt["res"] = fn(cb)
            except BaseException as exc:  # noqa: BLE001 - 주 스레드로
                stt["err"] = exc
            finally:
                stt["done"] = True

        t = threading.Thread(target=run, name=f"scx-vd-{self.ex.job['id'][:8]}", daemon=True)
        t0 = last = time.monotonic()
        t.start()
        try:
            while not stt["done"]:
                t.join(POLL_S)
                self._tick(cancel)
                now = time.monotonic()
                if now - last >= PROGRESS_S:
                    last = now
                    if size and stt["got"]:
                        self.progress(lo + (hi - lo) * min(1.0, stt["got"] / size), f"{label} {_amount(stt['got'], size)}")
                    else:
                        el = int(now - t0)
                        self.progress(lo, f"{label} {el // 60:02d}:{el % 60:02d}")
        except BaseException:
            stt["abort"] = True
            raise
        if stt["err"] is not None:
            raise stt["err"]
        return stt["res"], stt["got"]

    # ---- VD_PREP
    def vd_prep(self) -> dict[str, Any]:
        from esl_platform.api.services.verify_drop import extract_ready, input_set

        changed = changed_inputs(self.p.get("input_fingerprint") or self.case["input_fingerprint"])
        if changed:
            raise _fail("INPUT_CHANGED", f"원 Case 입력 파일이 바뀌었습니다: {[os.path.basename(x) for x in changed[:3]]}")
        if not extract_ready(self.s, self.case):
            raise _fail("VD_CASE_NOT_READY", messages.text("VD_CASE_NOT_READY"))
        core = {"case": dict(self.p.get("core_case") or {})}
        info = input_set(self.s, core, self.case)
        if info["problems"]:
            code, reason = info["problems"][0]
            raise _fail(code, reason)
        best = os.path.join(doe_dir(self.s, self.study["id"]), *str(self.p["best_rel"]).split("/"))
        if not os.path.isdir(best) or os.path.islink(best):
            raise _fail("VD_DESIGN_NO_FILES", messages.text("VD_DESIGN_NO_FILES"))
        model = os.path.join(esl_subdir(self.s, self.case["folder_name"]), "01_extract", "model.npz")
        stage = safe_path(self.cdir, "stage")
        if os.path.lexists(stage):                     # 이전 시도 산출물 → _backup(지우지 않음)
            bk = safe_path(self.cdir, "_backup", _now().strftime("%Y%m%dT%H%M%S%f"))
            os.makedirs(os.path.dirname(bk), exist_ok=True)
            os.replace(stage, bk)
        self.echo(f"[esl-worker] VD_PREP: 원 Case 입력 {len(info['files'])}개(starter·include·엔진 {info['engines']}), "
                  f"안 {self.d['design_id']} 모핑 사본 {len(self.p.get('best_rels') or [])}개")
        mx = int((self.p.get("core_case") or {}).get("rad_max_line_kb") or 0) * 1024 or None
        vd = {"model_npz": model, "best_dir": best, "best_rels": list(self.p.get("best_rels") or []),
              "files": [list(x) for x in info["files"]], "out": stage,
              "result_out": safe_path(self.cdir, "patch.json"), "morph_out": safe_path(self.cdir, "morph.npz"),
              "max_line": mx}
        self.progress(10.0, "원 Case 입력 사본 패치 중")
        self.ex._run_core({**self.st, "core_stage": "vd_patch"}, self.log_path, {"stage": "vd_patch", "vd": vd})
        res = _read(vd["result_out"]) or {}
        files = []
        for f in res.get("files") or []:
            files.append({"rel": f["rel"], "size": int(f["size"]), "sha256": f["sha256"],
                          "source": "patched" if f["source"] == "patched" else "orig", "n_patched": int(f["n_patched"])})
        total = sum(f["size"] for f in files)
        lim = int(scx_cfg(self.s).max_stage_bytes)
        if total > lim:
            raise _fail("SCX_FILE_TOO_LARGE", f"올릴 파일 합계 {total} B 가 상한 {lim} B 를 넘습니다 — 관리자: hpc.scx.max_stage_bytes")
        doc = {"version": 1, "verify_drop_id": self.d["id"], "starter": os.path.basename(info["rad"]),
               "engines": list(info["engines"]), "files": files, "morph": res.get("morph"),
               "n_patched": int(res.get("n_patched") or 0), "total_bytes": total}
        _write(safe_path(self.cdir, STAGE_JSON), doc)
        self.drop(files=files)
        self.echo(f"[esl-worker] VD_PREP: 파일 {len(files)}개 {total} B — 고친 파일 "
                  f"{sum(1 for f in files if f['source'] == 'patched')}개(/NODE {doc['n_patched']}줄)")
        return {"files": len(files), "bytes": total, "n_patched": doc["n_patched"]}

    def stage_doc(self) -> dict[str, Any]:
        doc = _read(safe_path(self.cdir, STAGE_JSON))
        if not isinstance(doc, dict) or not isinstance(doc.get("files"), list):
            raise _fail("PREREQUISITE_MISSING", "stage.json 이 없습니다(VD_PREP 부터 다시)")
        return doc

    def local_path(self, f: dict[str, Any]) -> str:
        if f["source"] == "patched":
            p = safe_path(self.cdir, "stage", *f["rel"].split("/"))
        else:
            rdir = os.path.dirname(os.path.abspath(self.case["rad_path"]))
            p = os.path.join(rdir, *f["rel"].split("/"))
            # 업로드 직전 재검사(v0.12.0 M1): 링크로 바뀌었거나 realpath 가 rad 폴더 밖이면 올리지 않음
            from esl_platform.api.services.verify_drop import inside_rad_dir

            if not inside_rad_dir(p, os.path.realpath(rdir)):
                raise _fail("INPUT_CHANGED", f"올릴 파일이 링크이거나 rad 폴더 밖입니다: {f['rel']}")
        if not os.path.isfile(p) or os.path.getsize(p) != int(f["size"]):
            raise _fail("INPUT_CHANGED", f"올릴 파일이 VD_PREP 기록과 다릅니다: {f['rel']}")
        return p

    # ---- VD_STAGE
    def drive_dir(self) -> str:
        if self.d.get("drive_dir_rel"):
            return self.d["drive_dir_rel"]
        parent = scx_paths.verify_job_parent(self.s, self.ex.job["project_id"])
        with self.ex.engine.connect() as conn:
            no = conn.execute(select(func.count()).select_from(vd_t).where(and_(
                vd_t.c.project_id == self.d["project_id"], vd_t.c.created_at <= self.d["created_at"]))).scalar_one()
        name = f"VD{int(no)}_{_now().strftime('%Y%m%dT%H%M%S')}"
        got = self.call("드라이브 폴더 이름", lambda: self.gw.ensure_new_dir(parent, name))
        rel = scx_paths.check_drive_rel(f"{parent}/{got}", self.health, write=True)   # 쓰기(B) — SPDM 상위 폴더 규칙 포함
        self.drop(drive_dir_rel=rel, phase="STAGING")
        self.echo(f"[esl-worker] VD_STAGE: 드라이브 폴더 {scx_paths.display(self.s, rel)}")
        return rel

    def vd_stage(self) -> dict[str, Any]:
        self.connect()
        doc = self.stage_doc()
        ddir = self.drive_dir()
        if self.d["phase"] != "STAGING":
            self.drop(phase="STAGING")
        cfg = scx_cfg(self.s)
        files = doc["files"]
        total = max(1, sum(int(f["size"]) for f in files))
        sent = 0
        batches: list[tuple[str, str]] = []
        for i, f in enumerate(files):
            local = self.local_path(f)
            sub, _, name = f["rel"].rpartition("/")
            rel_dir = f"{ddir}/{sub}" if sub else ddir
            rid = f"{vd_repo.request_id(self.d['id'], 1)}:f{i}"
            lo, hi = 90.0 * sent / total, 90.0 * (sent + int(f["size"])) / total

            def up(cb, local=local, rel_dir=rel_dir, name=name, f=f, rid=rid):
                return self.gw.upload(local, rel_dir, name, f["sha256"], rid, size=int(f["size"]), on_chunk=cb)

            bid, _got = self.call(f"올리기 {f['rel']}",
                                  lambda up=up, f=f, lo=lo, hi=hi: self.threaded(up, label=f"올리는 중 {f['rel']}",
                                                                                 size=int(f["size"]), lo=lo, hi=hi))
            batches.append((f["rel"], str(bid)))
            sent += int(f["size"])
        self.echo(f"[esl-worker] VD_STAGE: 대시보드 대기열 {len(batches)}개 — 끝날 때까지 기다림")
        t0 = time.monotonic()
        pend = dict(batches)
        while pend:
            for rel, bid in list(pend.items()):
                b = self.call(f"대기열 {rel}", lambda bid=bid: self.gw.batch(bid))
                st = str(b.get("state") or "")
                if st == "DONE":
                    pend.pop(rel)
                elif st == "CONFLICT":
                    raise _fail("SCX_STAGE_CONFLICT", messages.text("SCX_STAGE_CONFLICT") + f": {rel}")
                elif st in ("FAILED", "PARTIAL", "CANCELLED"):
                    items = [x for x in b.get("items") or [] if x.get("error_code")]
                    why = (items[0].get("error_code") if items else None) or st
                    raise _fail("SCX_STAGE_FAILED", f"SCX 드라이브 올리기 실패({why}): {rel}")
                elif st == "PAUSED" or b.get("paused"):
                    self.progress(90.0, "대시보드 SCX 재로그인 필요(대기열 일시 정지)")
            if not pend:
                break
            if time.monotonic() - t0 > float(cfg.stage_timeout_s):
                raise _fail("VD_STAGE_TIMEOUT", messages.text("VD_STAGE_TIMEOUT") + f" — 남은 {len(pend)}개")
            done = len(batches) - len(pend)
            self.progress(90.0 + 10.0 * done / max(1, len(batches)), f"대시보드가 SCX에 올리는 중 {done}/{len(batches)}")
            self.wait(float(cfg.stage_poll_s))
        self.progress(100.0, f"올리기 끝 {len(batches)}개")
        return {"files": len(batches), "drive_dir": scx_paths.display(self.s, ddir)}

    # ---- VD_SUBMIT
    def request_body(self, rid: str, doc: dict[str, Any], ddir: str) -> dict[str, Any]:
        cfg = scx_cfg(self.s)
        hpc = dict(self.p.get("hpc") or {})
        starter = doc["starter"]
        engines = list(doc.get("engines") or [])
        rest = [f["rel"] for f in doc["files"] if f["rel"] != starter and f["rel"] not in engines]
        return {"request_id": rid, "input_path": f"{ddir}/{starter}",
                "engine_paths": [f"{ddir}/{e}" for e in engines], "additional_paths": [f"{ddir}/{r}" for r in rest],
                "version": str(hpc.get("version") or cfg.version),
                "resources": {"appliance": cfg.appliance, "ncpu": int(hpc.get("ncpu") or cfg.ncpu),
                              "memory_gb": cfg.memory_gb, "queue_type": cfg.queue_type},
                "run_type": cfg.run_type, "mpi": cfg.mpi, "single_precision": bool(cfg.single_precision),
                "client_ref": {"app": "esl", "verify_drop_id": self.d["id"], "design_id": self.d["design_id"],
                               "case_id": self.d["case_id"]}}

    def vd_submit(self) -> dict[str, Any]:
        from esl_platform.core.scx.gateway import radioss_request

        self.connect()
        doc = self.stage_doc()
        ddir = self.reload().get("drive_dir_rel")
        if not ddir:
            raise _fail("PREREQUISITE_MISSING", "드라이브 폴더가 없습니다(VD_STAGE 부터 다시)")
        with self.ex._tx() as conn:
            jobs_repo.assert_lease(conn, self.ex.job["id"], self.ex.token)
            sub = vd_repo.latest_submission(conn, self.d["id"], for_update=True)
            if sub is not None and sub["state"] in ("SUBMITTED", "ATTACHED") and sub.get("scx_job_id"):
                self.echo(f"[esl-worker] VD_SUBMIT: 이미 제출됨({sub['request_id']} → 잡 {sub['scx_job_id']}) — 건너뜀")
                return {"request_id": sub["request_id"], "scx_job_id": sub["scx_job_id"], "reused": True}
            if sub is not None and sub["state"] == "UNKNOWN":
                raise _fail("SCX_SUBMISSION_UNKNOWN", messages.text("SCX_SUBMISSION_UNKNOWN"))
            if sub is not None and sub["state"] == "SUBMITTING":
                rid = sub["request_id"]
                body = _read(safe_path(self.cdir, f"submit_a{sub['attempt']}.json"))
                if not isinstance(body, dict) or _sha_json(body) != sub["request_sha256"]:
                    body = self.request_body(rid, doc, ddir)
                    if _sha_json(body) != sub["request_sha256"]:
                        raise _fail("SCX_SUBMIT_FAILED", "남은 제출 기록(SUBMITTING)과 본문이 달라 같은 request_id 로 다시 보낼 수"
                                    " 없습니다 — 관리자 확인")
                self.echo(f"[esl-worker] VD_SUBMIT: 이전 제출 기록 SUBMITTING({rid}) — 같은 request_id 로 다시 보냄(replay)")
            else:
                attempt = (int(sub["attempt"]) + 1) if sub is not None else 1
                rid = vd_repo.request_id(self.d["id"], attempt)
                body = self.request_body(rid, doc, ddir)
                _write(safe_path(self.cdir, f"submit_a{attempt}.json"), body)
                vd_repo.insert_submission(conn, verify_drop_id=self.d["id"], attempt=attempt, request_sha256=_sha_json(body))
        self.progress(20.0, "SCX 제출 중")
        req = radioss_request(body)
        out, _ = self.threaded(lambda _cb: self.gw.submit_radioss(req), label="SCX 제출 중", cancel=False)
        with self.ex._tx() as conn:
            if out.state == "SUBMITTED":
                vd_repo.update_submission(conn, rid, state="SUBMITTED", scx_job_id=out.job_id)
                self.d = vd_repo.update_drop(conn, self.d["id"], phase="SUBMITTED", scx_job_id=out.job_id,
                                             scx_status=(out.status or "")[:64] or None)
            elif out.state == "UNKNOWN":
                vd_repo.update_submission(conn, rid, state="UNKNOWN", error_code=out.code or "SUBMISSION_UNKNOWN",
                                          error_message=mask_text(out.message, 200))
            else:
                vd_repo.update_submission(conn, rid, state="FAILED", error_code=out.code,
                                          error_message=mask_text(out.message, 200))
        if out.state == "UNKNOWN":
            self.echo(f"[esl-worker] VD_SUBMIT: 결과 모름({rid}, replay {out.replays}회) — 사람 확인 필요")
            raise _fail("SCX_SUBMISSION_UNKNOWN", messages.text("SCX_SUBMISSION_UNKNOWN"))
        if out.state != "SUBMITTED":
            raise _fail("SCX_SUBMIT_FAILED", messages.text("SCX_SUBMIT_FAILED", out.code) + " — " + mask_text(out.message, 200))
        _write(safe_path(self.cdir, JOB_JSON), {"job_id": out.job_id, "status": out.status, "output_rel": out.output_rel})
        self.echo(f"[esl-worker] VD_SUBMIT: {rid} → SCX 잡 {out.job_id}(replay {out.replays}회)")
        return {"request_id": rid, "scx_job_id": out.job_id, "replays": out.replays}

    # ---- VD_WAIT
    def vd_wait(self) -> dict[str, Any]:
        from .executor import _Canceled

        self.connect()
        jid = self.reload().get("scx_job_id")
        if not jid:
            raise _fail("PREREQUISITE_MISSING", "SCX 잡 ID 가 없습니다(VD_SUBMIT 부터 다시)")
        vc = self.s.verify_drop
        t0 = time.monotonic()
        lost = 0
        last_raw = None
        rec = _read(safe_path(self.cdir, JOB_JSON)) or {}
        while True:
            try:
                h = self.gw.status(jid)
            except _gw_error() as exc:
                f = messages.classify(exc)
                if not f.retryable:
                    raise _fail(f.code, f"{f.message} — 잡 상태 조회") from None
                self.echo(f"[esl-worker] VD_WAIT: 상태 조회 {f.code} — 다음 폴링에서 다시")
                h = None
            if h is not None:
                if h.raw_state == "SCX_JOB_NOT_FOUND":
                    lost += 1
                    if lost >= int(vc.lost_after_polls):
                        raise _fail("SCX_JOB_LOST", messages.text("SCX_JOB_LOST") + f" — 잡 {jid}")
                else:
                    lost = 0
                    rec.update(job_id=jid, status=h.raw_state, output_rel=h.output_rel or rec.get("output_rel"),
                               error_message=mask_text(h.error_message, 200) if h.error_message else None)
                    if h.raw_state != last_raw:
                        last_raw = h.raw_state
                        _write(safe_path(self.cdir, JOB_JSON), rec)
                        ph = "RUNNING" if h.state in ("RUNNING", "FINISHED") else self.d["phase"]
                        self.drop(scx_status=(h.raw_state or "")[:64] or None, phase=ph)
                        self.echo(f"[esl-worker] VD_WAIT: SCX 잡 {jid} 상태 {h.raw_state}")
                    if h.state == "FINISHED":
                        if h.outcome == "SUCCEEDED":
                            self.progress(100.0, f"SCX {h.raw_state}")
                            return {"scx_job_id": jid, "status": h.raw_state, "output_rel_known": bool(rec.get("output_rel"))}
                        if h.outcome == "CANCELED":
                            raise _Canceled(f"SCX 잡이 SCX 에서 종료되었습니다({h.raw_state})")
                        raise _fail("SCX_RADIOSS_FAILED", messages.text("SCX_RADIOSS_FAILED", h.raw_state)
                                    + (f" — {mask_text(h.error_message, 200)}" if h.error_message else ""))
            el = time.monotonic() - t0
            if el > float(vc.max_wait_h) * 3600.0:
                raise _fail("VD_WAIT_TIMEOUT", messages.text("VD_WAIT_TIMEOUT"))
            e = int(el)
            self.progress(min(95.0, 100.0 * el / max(1.0, float(vc.max_wait_h) * 3600.0)),
                          f"SCX 대기 {last_raw or '?'} {e // 3600:02d}:{e % 3600 // 60:02d}:{e % 60:02d}")
            self.wait(float(vc.poll_s))

    # ---- VD_FETCH
    def vd_fetch(self) -> dict[str, Any]:
        self.connect()
        vc = self.s.verify_drop
        rec = _read(safe_path(self.cdir, JOB_JSON)) or {}
        out_rel = rec.get("output_rel")
        if not out_rel:
            raise _fail("SCX_OUTPUT_UNRESOLVED", messages.text("SCX_OUTPUT_UNRESOLVED"))
        try:
            out_rel = scx_paths.check_drive_rel(out_rel, None)
        except DomainError as exc:
            raise _fail(exc.code, exc.message) from None
        ents = self.call("결과 폴더 목록", lambda: self.gw.list(out_rel, int(self.s.scx_drive.list_max_entries)))
        files = {str(e.get("name")): e for e in ents if e.get("kind") == "file" and e.get("name")}
        globs = vc.result_globs or {}

        def match(kind: str) -> list[str]:
            pats = [g.casefold() for g in globs.get(kind) or []]
            return sorted(n for n in files if any(fnmatch.fnmatchcase(n.casefold(), p) for p in pats))

        h3ds, outs = match("h3d"), match("out")
        doc = self.stage_doc()
        stem = run_stem(doc["starter"]) or os.path.splitext(doc["starter"])[0]
        if len(h3ds) > 1:
            pref = [n for n in h3ds if os.path.splitext(n)[0].casefold() in (stem.casefold(), f"{stem}_0001".casefold())]
            h3ds = pref if len(pref) == 1 else h3ds
        if len(h3ds) != 1:
            raise _fail("VD_RESULT_MISSING", messages.text("VD_RESULT_MISSING") + f"(h3d {len(h3ds)}개: {h3ds[:5]})")
        from esl_platform.api.services.scx_drive import download_limit_info

        lim, key = download_limit_info(self.s, self.health, upload=False)
        if int(vc.max_result_bytes) < lim:
            lim, key = int(vc.max_result_bytes), "verify_drop.max_result_bytes"
        want = h3ds + outs
        from esl_platform.core.uploads import check_segment

        for n in want:                                   # v0.12.0 L4: 릴레이가 준 이름을 로컬 파일 이름으로 쓰기 전 검사
            if "/" in n or "\\" in n:
                raise _fail("PATH_UNSAFE", f"결과 파일 이름이 올바르지 않습니다: {n[:80]}")
            try:
                check_segment(n, "결과 파일")
            except DomainError as exc:
                raise _fail("PATH_UNSAFE", exc.message) from None
        sizes = {n: int(files[n].get("size") or 0) for n in want}
        for n in want:
            if sizes[n] > lim:
                raise _fail("SCX_FILE_TOO_LARGE", messages.text("SCX_FILE_TOO_LARGE", f"{lim} B") + f" — 관리자: {key} ({n} "
                            f"{sizes[n]} B)")
        self.check_free(sum(sizes.values()))
        rdir = os.path.join(self.cdir, "result")
        if os.path.islink(rdir):
            raise _fail("PATH_UNSAFE", "검증 폴더 안 심볼릭 링크는 허용하지 않습니다")
        os.makedirs(rdir, exist_ok=True)
        man = _read(safe_path(self.cdir, FETCH_JSON)) or {}
        man = man if isinstance(man, dict) and man.get("out_rel") == out_rel else {"out_rel": out_rel, "files": {}}
        total = max(1, sum(sizes.values()))
        doneb = 0
        for n in want:
            dst = safe_path(self.cdir, "result", n)
            r0 = man["files"].get(n)
            if r0 and os.path.isfile(dst) and os.path.getsize(dst) == int(r0["size"]) and sha256_file(dst) == r0["sha256"]:
                doneb += sizes[n]
                continue
            part = dst + PART
            if os.path.islink(part):
                raise _fail("PATH_UNSAFE", "결과 임시 파일이 링크입니다")
            lo, hi = 100.0 * doneb / total, 100.0 * (doneb + sizes[n]) / total
            src = f"{out_rel}/{n}"

            def dl(cb, src=src, part=part):
                return self.gw.download(src, part, lim, on_chunk=cb)

            def once(dl=dl, n=n, lo=lo, hi=hi):
                from .scx_fetch import interrupted_or

                try:
                    (got, sha), _ = self.threaded(dl, label=f"결과 받는 중 {n}", size=sizes[n], lo=lo, hi=hi)
                except _gw_error() as exc:
                    raise interrupted_or(exc, os.path.getsize(part) if os.path.isfile(part) else 0, sizes[n]) from None
                return got, sha

            got, sha = self.call(f"내려받기 {n}", once)
            if os.path.islink(part) or os.path.islink(dst):
                raise _fail("PATH_UNSAFE", "결과 파일이 링크입니다")
            os.replace(part, dst)
            man["files"][n] = {"size": int(got), "sha256": sha}
            _write(safe_path(self.cdir, FETCH_JSON), man)
            doneb += sizes[n]
            self.echo(f"[esl-worker] VD_FETCH: {n} {got} B sha256 {sha[:12]}…")
        warns = self.judge_out(outs)
        man["h3d"] = h3ds[0]
        man["outs"] = outs
        man["warnings"] = warns
        _write(safe_path(self.cdir, FETCH_JSON), man)
        self.drop(phase="FETCHED")
        if warns:
            with self.ex._tx() as conn:
                jobs_repo.add_warnings(conn, self.ex.job["id"], self.ex.token, warns)
        self.progress(100.0, f"결과 받음 h3d {h3ds[0]} · out {len(outs)}개")
        return {"h3d": h3ds[0], "outs": outs}

    def judge_out(self, outs: list[str]) -> list[str]:
        vc = self.s.verify_drop
        if not outs:
            raise _fail("VD_RADIOSS_ABNORMAL", messages.text("VD_RADIOSS_ABNORMAL") + "(out 파일 없음)")
        ok_any = False
        for n in outs:
            p = safe_path(self.cdir, "result", n)
            with open(p, "rb") as fh:
                size = os.path.getsize(p)
                if size > 64 * 1024 * 1024:            # 큰 out: 앞 8 MB + 끝 56 MB
                    head = fh.read(8 * 1024 * 1024)
                    fh.seek(size - 56 * 1024 * 1024)
                    data = head + b"\n" + fh.read()
                else:
                    data = fh.read()
            text = data.decode("utf-8", errors="replace")
            for pat in vc.out_error_patterns:
                m = re.search(pat, text)
                if m:
                    a = text.rfind("\n", 0, m.start()) + 1
                    b = text.find("\n", m.end())
                    line = text[a: b if b >= 0 else len(text)]
                    raise _fail("VD_RADIOSS_ABNORMAL", messages.text("VD_RADIOSS_ABNORMAL") + f" — {n}: {line.strip()[:160]}")
            if any(re.search(pat, text) for pat in vc.out_ok_patterns):
                ok_any = True
        if not ok_any:
            raise _fail("VD_RADIOSS_ABNORMAL", messages.text("VD_RADIOSS_ABNORMAL") + "(정상 종료 표시 없음)")
        return []

    def check_free(self, need: int) -> None:
        import shutil

        try:
            free = shutil.disk_usage(self.cdir).free
        except OSError:
            return
        reserve = int(self.s.upload.min_free_gb * 1024 ** 3)
        if free < need + reserve:
            raise _fail("INSUFFICIENT_STORAGE", f"esl_root 여유 공간 부족(필요 {need} B + 여유 {self.s.upload.min_free_gb} GB, "
                        f"현재 {free} B)")


def _amount(got: int, size: int) -> str:
    if size >= 1024 ** 3:
        return f"{got / 1024 ** 3:.1f} / {size / 1024 ** 3:.1f} GB"
    return f"{got / 1024 ** 2:.1f} / {size / 1024 ** 2:.1f} MB"


def _sha_json(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- 종료·취소 hook(executor)
def on_cancel(ex, exc: BaseException | None = None) -> str | None:
    """실행 중 취소: SCX 잡 ID 가 있고 SCX 쪽이 아직 끝나지 않았으면 cancel(job_id) **1회**(SR §8). 반환 = 작업 실패 문구."""
    remote = str(exc) if exc is not None and str(exc) else None
    if remote:                                           # SCX 에서 이미 종료(Aborted 등) — terminate 하지 않음
        return remote
    try:
        with ex.engine.connect() as conn:
            d = vd_repo.get_drop(conn, ex.job["verify_drop_id"])
        jid = (d or {}).get("scx_job_id")
        if not jid:
            return "사용자 취소"
        raw = str(d.get("scx_status") or "").strip().casefold()
        from esl_platform.core.scx.gateway import status_map

        if status_map().get(raw, ("", None))[0] == "FINISHED":
            return f"사용자 취소(SCX 잡 {jid} 은 이미 {d.get('scx_status')})"
        gw, _h = scx_status.require_verify(ex.settings, ex.job["project_id"])
        gw.cancel(jid)
        with ex._tx() as conn:
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"scx_terminated": jid})
        return f"사용자 취소 — SCX 잡 {jid} 종료 요청"
    except Exception as e:  # noqa: BLE001 - 취소 처리 자체는 계속
        msg = messages.classify(e).message if isinstance(e, _gw_error()) else (
            e.message if isinstance(e, DomainError) else type(e).__name__)
        return mask_text(f"사용자 취소 — SCX 잡 종료 요청 실패({msg}): SCX 화면에서 직접 종료하세요", 450)


def on_finish(ex, conn, state: str, code: str | None, message: str | None) -> None:
    """작업 종료 전이와 같은 트랜잭션: 검증 phase 갱신. VERIFY_DROP 성공 → VERIFY_POST(SLOT) 큐 + phase POST."""
    did = ex.job["verify_drop_id"]
    d = vd_repo.get_drop(conn, did, for_update=True)
    if d is None:
        return
    if state == "SUCCEEDED":
        if ex.job["job_type"] == "VERIFY_DROP":
            params = dict(ex.job["params"] or {})
            man = _read(os.path.join(ex.cdir, FETCH_JSON)) or {}
            params["h3d"] = {**(params.get("h3d") or {}), "h3d_path": os.path.join(ex.cdir, "result", man.get("h3d") or ""),
                             "out_dir": os.path.join(ex.cdir, "h3dwork", "raw")}
            params["warnings_fetch"] = list(man.get("warnings") or [])
            jobs_repo.insert_job(conn, case_id=None, verify_drop_id=did, project_id=ex.job["project_id"],
                                 job_type="VERIFY_POST", params=params, created_by=ex.job["created_by"],
                                 created_by_name=ex.job["created_by_name"])
            vd_repo.update_drop(conn, did, phase="POST")
        return
    if state in ("FAILED", "CANCELED") and d["phase"] not in vd_repo.DROP_TERMINAL:
        vd_repo.update_drop(conn, did, phase="CANCELED" if state == "CANCELED" else "FAILED")


# ---------------------------------------------------------------- 백엔드 [잡 ID 연결]·[포기](어댑터 쓰기 호출 = 이 모듈만)
def resolve_submission(gw, request_id: str, action: str, job_id: str | None) -> dict[str, Any]:
    """릴레이 `/submissions/{rid}/resolve`. 오류 → DomainError(404 SCX_JOB_NOT_FOUND·409 SCX_JOB_ID_IN_USE·409 VD_NOT_UNKNOWN·503)."""
    try:
        return gw.resolve(request_id, action, job_id if action == "attach" else None)
    except _gw_error() as exc:
        f = messages.classify(exc)
        if f.code == "SCX_JOB_NOT_FOUND":
            raise not_found("SCX_JOB_NOT_FOUND", messages.text("SCX_JOB_NOT_FOUND")) from None
        if f.code in ("SCX_JOB_ID_IN_USE", "VD_NOT_UNKNOWN"):
            raise conflict(f.code, messages.text(f.code)) from None
        raise DomainError("SCX_UNAVAILABLE", f.message, status=503, reason_code=f.code) from None


__all__ = ["prepare", "run_step", "on_cancel", "on_finish", "resolve_submission", "mark_job_progress", "job_progress",
           "PrepareFailed", "safe_path"]
