"""SCX_FETCH(XFER 레인, 계약 esl_scx_relay.md §9.1·SR-D-6·7·8): SCX 드라이브 → 기존 업로드 세션 폴더로 내려받기.

- 대상 = jobs.upload_id(OPEN 세션, POST /scx/fetches 가 만듦). esl 이 쓰는 곳 = 그 세션 폴더뿐:
  `<up>/_scx/stage/<루트 기준 드라이브 경로>`(임시 배치 — include 해석용), `<up>/_scx/fetch.json`(받은 파일 기록 — 재시도에서 건너뜀),
  `<up>/_scx/logs/<job_id>/…`(step 로그), 최종 `<up>/rad/<공통 조상 C 기준 상대>`·`<up>/h3d/<이름>`.
- SF_RAD: health·범위 재검사 → rad·h3d 크기(부모 list)·상한·여유 공간 → rad 받기 → 같은 폴더 엔진 rad(scx_drive.engine_globs,
  starter 가 `<stem>_0000.rad` 일 때만) → include 반복 수집(코어 scan_include_refs — 못 찾은 참조의 후보 경로를 드라이브 경로로 바꿔
  같은 루트 안·허용 확장자·드라이브에 있으면 받고 다시 스캔, 깊이 case.rad_include_max_depth, 파일 수 scx_drive.max_files).
  절대경로·루트 밖·드라이브에 없음·확장자 밖·이름 규칙 밖 = 받지 않고 result.scx.missing_specs 로(기존 complete 누락 표시).
  끝나면 공통 조상 C 기준으로 rad/ 아래에 옮기고(원문 수정 없음 — `../` include 유지) uploads.files[] 에 source scx 항목.
- SF_H3D: h3d → `h3d/<이름>.part`(진행률 = 받은 바이트, 첫 바이트 전 "대시보드가 SCX에서 받는 중") → sha256 대조 → 이름 바꿈.
- SF_REGISTER: 기존 inspect_upload → uploads.result(+ scx), ok 면 COMPLETED.
- 이어받기 = 파일 단위(릴레이 Range 없음): sha256 이 확인된 파일은 건너뜀, 받다 끊긴 `.part` 는 덮어 새로 받음. 재시도 가능한 오류
  (전송·SCX_BUSY·SCX_DASHBOARD_DISK·SCX_HASH_MISMATCH)는 파일마다 scx_drive.file_retries 회, 대기 retry_wait_s.
- 전송은 별도 스레드(어댑터 download — 첫 바이트까지 수 시간 막힐 수 있음), 이 스레드는 lease 갱신·취소 확인·진행률만.
  취소·lease 상실이면 전송 스레드에 중단 표시(다음 청크에서 끊김) 후 바로 돌아간다(.part 는 남김).
- 외부 명령 없음(HTTP 만). 어댑터 쓰기 메서드(upload·mkdirs·submit)는 부르지 않는다.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import posixpath
import threading
import time
from types import SimpleNamespace
from typing import Any

from sqlalchemy import and_, select, update

from esl_platform.core import uploads as U
from esl_platform.core.atomic import write_text_atomic
from esl_platform.core.config import is_within
from esl_platform.core.db.tables import jobs as jobs_t
from esl_platform.core.db.tables import uploads as uploads_t
from esl_platform.core.errors import DomainError
from esl_platform.core.inputs import sha256_file
from esl_platform.core.job_types import SCX_STEP_WEIGHTS
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.scx import messages, paths
from esl_platform.core.scx import status as scx_status
from esl_platform.core.scx.gateway import ADAPTER_COMMIT
from esl_platform.core.scx.mask import mask_text
from esl_platform.core.scx.settings import engine_names, run_stem

SCX_DIR = "_scx"
STAGE = "stage"
MANIFEST = "fetch.json"
CLIENT = {"name": "scx-relay", "version": ADAPTER_COMMIT[:12]}
POLL_S = 0.2
PROGRESS_S = 1.0


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


def interrupted_or(exc: BaseException, got: int, size: int | None) -> BaseException:
    """v0.12.0 L2: 본문을 다 받기 전에 연결이 끊기면 어댑터는 '크기·해시 불일치'(HASH_MISMATCH)로 알린다 → 받은 바이트가 기대
    크기보다 작으면 전송 오류(SCX_TRANSFER_INTERRUPTED, 재시도 대상)로 바꾼다. 크기가 다 왔는데 해시가 다르면 그대로."""
    E = _gw_error()
    if isinstance(exc, E) and getattr(exc, "relay_code", None) == "HASH_MISMATCH" and size is not None and got < int(size):
        return E("UNAVAILABLE", f"전송이 중간에 끊겼습니다({got} / {size} B 받음)", relay_code="TRANSFER_INTERRUPTED",
                 transport=True)
    return exc


# ---------------------------------------------------------------- 진행률(SCX_STEP_WEIGHTS 가중)
def job_progress(step_key: str, pct: float) -> float:
    done = 0.0
    for k, w in SCX_STEP_WEIGHTS.items():
        if k == step_key:
            return done + w * max(0.0, min(100.0, pct)) / 100.0
        done += w
    return done


def mark_job_progress(conn, ex, step_key: str, pct: float) -> None:
    conn.execute(update(jobs_t).where(and_(jobs_t.c.id == ex.job["id"], jobs_t.c.lease_token == ex.token))
                 .values(progress_pct=job_progress(step_key, pct)))


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f}"


def _mb(n: int) -> str:
    return f"{n / 1024 ** 2:.1f} MB"


def _amount(got: int, size: int) -> str:
    """진행 라벨 'x / y GB'(계약 §7.1 예). 1 GiB 미만 파일은 MB 로(0.0 / 0.0 GB 방지)."""
    if size >= 1024 ** 3:
        return f"{_gb(got)} / {_gb(size)} GB"
    return f"{got / 1024 ** 2:.1f} / {size / 1024 ** 2:.1f} MB"


# ---------------------------------------------------------------- 준비
def _upload(conn, upload_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(uploads_t).where(uploads_t.c.id == upload_id)
    if for_update:
        q = q.with_for_update()
    r = conn.execute(q).mappings().first()
    return dict(r) if r else None


def prepare(ex) -> tuple[str, dict[str, Any]]:
    """작업 폴더 = <세션>/_scx(로그·기록·임시 배치). 세션 OPEN·폴더 안전(링크·junction·탈출 없음) 확인."""
    s = ex.settings
    root = s.storage.upload_root
    if not root:
        raise PrepareFailed("UPLOAD_DISABLED", "업로드 저장 위치(storage.upload_root)가 설정되지 않았습니다")
    with ex.engine.connect() as conn:
        up = _upload(conn, ex.job["upload_id"])
    if up is None:
        raise PrepareFailed("UPLOAD_NOT_FOUND", "업로드 세션이 없습니다")
    if up["state"] != "OPEN":
        raise PrepareFailed("UPLOAD_CLOSED", f"업로드 세션이 이미 끝났습니다({up['state']})")
    d = up["dir_path"]
    try:
        U.check_upload_dir(root, d)
        if not os.path.isdir(d):
            raise PrepareFailed("UPLOAD_NOT_FOUND", "업로드 세션 폴더가 없습니다")
        cdir = os.path.join(d, SCX_DIR)
        _safe_mkdir(d, cdir)
    except DomainError as exc:
        raise PrepareFailed(exc.code, exc.message) from None
    return cdir, {"upload": up, "root": root}


def _safe_mkdir(up_dir: str, path: str) -> None:
    U._no_links_below(up_dir, path)
    os.makedirs(path, exist_ok=True)
    U._no_links_below(up_dir, path)


# ---------------------------------------------------------------- 실행
def run_step(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    f = _Fetch(ex, st, log_path)
    key = st["step_key"]
    fn = {"SF_RAD": f.sf_rad, "SF_H3D": f.sf_h3d, "SF_REGISTER": f.sf_register}.get(key)
    if fn is None:
        raise _fail("INTERNAL_ERROR", f"알 수 없는 step {key}")
    try:
        return fn()
    except DomainError as exc:                    # 경로·링크 검사(PATH_UNSAFE 등) — 그 코드로 step 실패
        f.echo(f"[esl-worker] {key}: {exc.code} — {exc.message}")
        raise _fail(exc.code, exc.message) from None


class _Fetch:
    def __init__(self, ex, st: dict[str, Any], log_path: str) -> None:
        self.ex = ex
        self.st = st
        self.log_path = log_path
        self.s = ex.settings
        self.p = ex.job["params"] or {}
        self.root_dir = ex.lib["root"]
        self.up = ex.lib["upload"]
        self.up_dir = self.up["dir_path"]
        self.scx_dir = os.path.join(self.up_dir, SCX_DIR)
        self.stage = os.path.join(self.scx_dir, STAGE)
        self.root_rel = str(self.p["root_rel"])
        self.tick = {"renew": time.monotonic(), "cancel": time.monotonic()}
        self.gw = None
        self.health: dict[str, Any] = {}
        self._list_cache: dict[str, dict[str, dict[str, Any]] | None] = {}
        self._live_rel: str | None = None          # 받는 중인 h3d 의 uploads.files[].rel(파일별 진행률 scx_got 갱신)

    # ---- 공통
    def echo(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(mask_text(msg, None, paths=False) + "\n")

    def progress(self, pct: float, label: str | None, *, got: int | None = None) -> None:
        """작업·step 진행 + 업로드 세션 updated_at. got 이 있고 받는 중인 h3d 항목이 있으면 그 항목의 scx_got(받은 바이트)도
        — GET /uploads/{id} 의 files[].received·received_total 이 파일별 진행률을 보이게(§7.1)."""
        with self.ex._tx() as conn:
            jobs_repo.step_update(conn, self.ex.job["id"], self.ex.token, self.st["step_no"], progress_pct=float(pct))
            jobs_repo.set_progress(conn, self.ex.job["id"], self.ex.token, job_progress(self.st["step_key"], pct), label)
            vals: dict[str, Any] = {"updated_at": _now()}
            if got is not None and self._live_rel is not None:
                up = _upload(conn, self.up["id"], for_update=True)
                if up is not None and up["state"] == "OPEN":
                    files = [dict(x) for x in up["files"]]
                    for x in files:
                        if x["rel"] == self._live_rel and x.get("source") == "scx" and not x.get("done"):
                            x["scx_got"] = max(0, min(int(x["size"]), int(got)))
                    vals["files"] = files
            conn.execute(update(uploads_t).where(uploads_t.c.id == self.up["id"]).values(**vals))

    def wait(self, seconds: float) -> None:
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            time.sleep(min(POLL_S, max(0.0, end - time.monotonic())))
            self.ex._wait_tick(self.tick)

    def connect(self) -> None:
        """health·기능 A 사용 가능 재확인(설정 변경·대시보드 다운 → 그 사유 코드로 실패)."""
        try:
            self.gw, self.health = scx_status.require_fetch(self.s, self.ex.job["project_id"], force=True)
        except DomainError as exc:
            raise _fail(exc.extra.get("reason_code") or exc.code, exc.message) from None
        try:
            root = paths.find_root(self.s, self.ex.job["project_id"], self.p["root"])
        except DomainError:
            raise _fail("SCX_PATH_NOT_ALLOWED", "SCX 드라이브 루트 설정이 바뀌었습니다(이 프로젝트에 허용되지 않음)") from None
        if not paths.within(self.root_rel, root.rel) or not paths.within(root.rel, self.root_rel):
            raise _fail("SCX_PATH_NOT_ALLOWED", "SCX 드라이브 루트 경로 설정이 바뀌었습니다")
        for rel in (self.p["rad_rel"], self.p["h3d_rel"]):
            self.check_rel(rel)

    def check_rel(self, rel: str) -> str:
        try:
            r = paths.check_drive_rel(rel, self.health)
        except DomainError as exc:
            raise _fail(exc.code, exc.message) from None
        if not paths.within(r, self.root_rel):
            raise _fail("SCX_PATH_NOT_ALLOWED", "루트 밖 경로입니다")
        return r

    def limit(self) -> int:
        return self.limit_info()[0]

    def limit_info(self) -> tuple[int, str]:
        from esl_platform.api.services.scx_drive import download_limit_info

        return download_limit_info(self.s, self.health)

    def too_large(self, what: str) -> str:
        from esl_platform.api.services.scx_drive import too_large_text

        return too_large_text(*self.limit_info()) + f" ({what})"

    def with_retries(self, what: str, fn):
        """재시도 가능한 오류(SR-D-7)는 scx_drive.file_retries 회, 대기 retry_wait_s. 마지막 오류 → step 실패."""
        sd = self.s.scx_drive
        tries = 1 + int(sd.file_retries)
        for i in range(tries):
            try:
                return fn()
            except _gw_error() as exc:
                f = messages.classify(exc)
                if f.code == "SCX_FILE_TOO_LARGE":
                    raise _fail(f.code, self.too_large(what)) from None
                if not f.retryable or i == tries - 1:
                    raise _fail(f.code, f"{f.message} — {what}") from None
                self.echo(f"[esl-worker] {what}: {f.code} — {float(sd.retry_wait_s):g}s 뒤 다시({i + 1}/{tries - 1})")
                self.wait(float(sd.retry_wait_s))
        raise _fail("SCX_UNAVAILABLE", what)                   # pragma: no cover

    # ---- 드라이브 목록(폴더별 캐시)
    def entries(self, dir_rel: str) -> dict[str, dict[str, Any]] | None:
        """폴더 항목 {이름: entry}. 폴더가 없으면 None."""
        if dir_rel in self._list_cache:
            return self._list_cache[dir_rel]

        def call():
            try:
                return self.gw.list(dir_rel, int(self.s.scx_drive.list_max_entries))
            except _gw_error() as exc:
                if messages.classify(exc).code == "SCX_PATH_NOT_FOUND":
                    return None
                raise

        ents = self.with_retries(f"목록 {paths.root_sub(dir_rel, self.root_rel) or '.'}", call)
        out = None if ents is None else {str(e.get("name") or ""): e for e in ents if e.get("name")}
        self._list_cache[dir_rel] = out
        return out

    def drive_file(self, rel: str) -> dict[str, Any] | None:
        """드라이브 파일 항목(같은 이름이 없으면 대소문자 무시로 — SCX·Windows 는 대소문자 구분 없음). 실제 이름 = `_name`."""
        parent, _, name = rel.rpartition("/")
        ents = self.entries(parent) or {}
        e = ents.get(name)
        if e is None:
            low = name.casefold()
            hits = [v for k, v in ents.items() if k.casefold() == low]
            e = hits[0] if len(hits) == 1 else None
        if e is None or e.get("kind") != "file":
            return None
        return {**e, "_name": str(e.get("name") or name)}

    # ---- 전송(별도 스레드)
    def download(self, rel: str, part: str, size: int, label: str, *, pct_of: tuple[float, float] = (0.0, 100.0)) -> tuple[int, str]:
        lim = self.limit()
        if size > lim:
            raise _fail("SCX_FILE_TOO_LARGE", self.too_large(f"{rel.rsplit('/', 1)[-1]} {size} B"))

        def once() -> tuple[int, str]:
            stt: dict[str, Any] = {"got": 0, "abort": False, "done": False, "res": None, "err": None}

            def cb(n: int) -> None:
                stt["got"] += n
                if stt["abort"]:
                    raise _Abort()

            def run() -> None:
                try:
                    stt["res"] = self.gw.download(rel, part, lim, on_chunk=cb)
                except BaseException as exc:  # noqa: BLE001 - 주 스레드로 넘김
                    stt["err"] = exc
                finally:
                    stt["done"] = True

            t = threading.Thread(target=run, name=f"scx-dl-{self.ex.job['id'][:8]}", daemon=True)
            t0 = time.monotonic()
            last = 0.0
            t.start()
            try:
                while not stt["done"]:
                    t.join(POLL_S)
                    self.ex._wait_tick(self.tick)
                    now = time.monotonic()
                    if now - last >= PROGRESS_S:
                        last = now
                        got = stt["got"]
                        lo, hi = pct_of
                        if got <= 0:
                            el = int(now - t0)
                            self.progress(lo, f"{label}: 대시보드가 SCX에서 받는 중 {el // 60:02d}:{el % 60:02d}")
                        else:
                            frac = min(1.0, got / size) if size else 1.0
                            self.progress(lo + (hi - lo) * frac, f"{label} {_amount(got, size)}", got=got)
            except BaseException:
                stt["abort"] = True               # 취소·lease 상실: 다음 청크에서 끊김(.part 남김 — 재시도 때 덮어씀)
                raise
            if stt["err"] is not None:
                raise interrupted_or(stt["err"], stt["got"], size)
            return stt["res"]

        got, sha = self.with_retries(f"내려받기 {rel.rsplit('/', 1)[-1]}", once)
        if got != size:
            self.echo(f"[esl-worker] 크기가 목록({size} B)과 다릅니다({got} B) — 받은 값(sha256 확인됨)을 씁니다")
        return got, sha

    # ---- 업로드 행
    def save_files(self, new: list[dict[str, Any]]) -> None:
        with self.ex._tx() as conn:
            jobs_repo.assert_lease(conn, self.ex.job["id"], self.ex.token)
            up = _upload(conn, self.up["id"], for_update=True)
            if up is None or up["state"] != "OPEN":
                raise _fail("UPLOAD_CLOSED", "업로드 세션이 이미 끝났습니다")
            files = [dict(x) for x in up["files"]]
            keys = {x["rel"].casefold(): i for i, x in enumerate(files) if not x.get("removed")}
            for f in new:
                i = keys.get(f["rel"].casefold())
                if i is None:
                    files.append(f)
                elif files[i].get("source") == "scx":
                    files[i] = f
                else:
                    raise _fail("UPLOAD_FILE_EXISTS", f"세션에 같은 경로 파일이 이미 있습니다(덮어쓰지 않음): {f['rel']}")
            conn.execute(update(uploads_t).where(uploads_t.c.id == self.up["id"]).values(
                files=files, total_bytes=sum(int(x["size"]) for x in files if not x.get("removed")), updated_at=_now(),
                result=None))
            self.up = _upload(conn, self.up["id"])

    def drop_pending(self, rel: str) -> None:
        """받는 중(done=False) SCX 항목을 files[] 에서 뺀다 — 실패 뒤 세션은 이전처럼 받은 파일만 보인다(최선 노력)."""
        try:
            with self.ex._tx() as conn:
                up = _upload(conn, self.up["id"], for_update=True)
                if up is None or up["state"] != "OPEN":
                    return
                files = [dict(x) for x in up["files"]
                         if not (x["rel"] == rel and x.get("source") == "scx" and not x.get("done"))]
                if len(files) != len(up["files"]):
                    conn.execute(update(uploads_t).where(uploads_t.c.id == self.up["id"]).values(
                        files=files, total_bytes=sum(int(x["size"]) for x in files if not x.get("removed")), updated_at=_now()))
        except Exception as exc:  # noqa: BLE001 - 원래 오류를 가리지 않음
            self.echo(f"[esl-worker] 받는 중 항목 정리 실패(무시): {type(exc).__name__}")

    def file_entry(self, rel: str, size: int, sha: str, drive_rel: str, **extra: Any) -> dict[str, Any]:
        c = int(self.s.upload.chunk_bytes)
        n = (size + c - 1) // c
        return {"rel": rel, "size": int(size), "sha256_expected": sha, "sha256": sha, "done": True, "proto": 2, "chunk": c,
                "got": [[0, n]] if n else [], "removed": False, "source": "scx",
                "drive_rel": paths.root_sub(drive_rel, self.root_rel), "client": dict(CLIENT), **extra}

    # ---- 기록(fetch.json)
    def manifest(self) -> dict[str, Any]:
        p = os.path.join(self.scx_dir, MANIFEST)
        try:
            U.check_existing_file(p, self.up_dir)
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict) and d.get("rad_rel") == self.p["rad_rel"] and isinstance(d.get("files"), dict):
                return d
        except (OSError, ValueError, DomainError):
            pass
        return {"version": 1, "rad_rel": self.p["rad_rel"], "root_rel": self.root_rel, "files": {}, "missing": [],
                "placed": False}

    def save_manifest(self, m: dict[str, Any]) -> None:
        p = os.path.join(self.scx_dir, MANIFEST)
        U._no_links_below(self.up_dir, self.scx_dir)
        if os.path.lexists(p):
            U.check_existing_file(p, self.up_dir)
        write_text_atomic(p, json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True))

    # ---- 로컬 경로
    def stage_path(self, rel: str, *, create: bool) -> str:
        """드라이브 경로 → 임시 배치 경로(세션 폴더 안, 성분 이름 규칙·링크 검사). 규칙 밖이면 DomainError."""
        sub = paths.root_sub(rel, self.root_rel)
        segs = [SCX_DIR, STAGE, *sub.split("/")]
        for g in segs:
            U.check_segment(g, sub)
        return U.target_path(self.up_dir, segs, create_parents=create, upload_root=self.root_dir)

    def stage_to_drive(self, p: str) -> str | None:
        """임시 배치 안 로컬 경로 → 드라이브 경로(밖이면 None)."""
        pn = os.path.normpath(p)
        if not is_within(pn, self.stage) or os.path.normcase(pn) == os.path.normcase(os.path.normpath(self.stage)):
            return None
        sub = os.path.relpath(pn, self.stage).replace(os.sep, "/")
        return "/".join([self.root_rel.strip("/"), sub])

    def inside_stage(self, p: str) -> bool:
        return self.stage_to_drive(p) is not None and is_within(os.path.realpath(p), os.path.realpath(self.stage))

    def fetch_to_stage(self, rel: str, kind: str, m: dict[str, Any], *, size: int | None = None) -> bool:
        """드라이브 파일 하나를 임시 배치로(기록이 있고 로컬 크기·sha256 이 같으면 건너뜀). 받았으면 True."""
        rec = m["files"].get(rel)
        dst = self.stage_path(rel, create=True)
        if rec and os.path.isfile(dst) and os.path.getsize(dst) == int(rec["size"]) and sha256_file(dst) == rec["sha256"]:
            return False
        src = rel
        if size is None:
            e = self.drive_file(rel)
            if e is None:
                raise _fail("SCX_PATH_NOT_FOUND", f"드라이브에 없는 경로입니다(이동·삭제됨): {rel.rsplit('/', 1)[-1]}")
            size = int(e.get("size") or 0)
            src = f"{rel.rpartition('/')[0]}/{e['_name']}"        # 드라이브의 실제 이름(대소문자)으로 요청
        part = dst + U.PART_SUFFIX
        if os.path.lexists(part):
            U.check_existing_file(part, self.up_dir)          # 자기 임시 파일만 덮어씀(링크·하드 링크 거부)
        n = len(m["files"])
        got, sha = self.download(src, part, size, f"{kind} {rel.rsplit('/', 1)[-1]}",
                                 pct_of=(min(90.0, 5.0 * n), min(95.0, 5.0 * n + 5)))
        U.check_existing_file(part, self.up_dir)
        if os.path.lexists(dst):
            U.check_existing_file(dst, self.up_dir)
        os.replace(part, dst)
        m["files"][rel] = {"size": got, "sha256": sha, "kind": kind}
        self.save_manifest(m)
        self.echo(f"[esl-worker] {kind}: {paths.root_sub(rel, self.root_rel)} ({_mb(got)}, sha256 {sha[:12]}…)")
        return True

    # ---- SF_RAD
    def sf_rad(self) -> dict[str, Any]:
        self.connect()
        rad, h3d = self.p["rad_rel"], self.p["h3d_rel"]
        m = self.manifest()
        if m.get("placed"):
            self.echo("[esl-worker] SF_RAD: 이전 작업에서 rad·include 를 이미 받아 배치했습니다(건너뜀)")
            return {"files": len(m["files"]), "missing": len(m.get("missing") or []), "reused": True}
        r_ent = self.drive_file(rad)
        h_ent = self.drive_file(h3d)
        if r_ent is None or h_ent is None:
            gone = rad if r_ent is None else h3d
            raise _fail("SCX_PATH_NOT_FOUND", f"드라이브에 없는 경로입니다(이동·삭제됨): {gone.rsplit('/', 1)[-1]}")
        rsz, hsz = int(r_ent.get("size") or 0), int(h_ent.get("size") or 0)
        lim = self.limit()
        for nm, sz in ((rad, rsz), (h3d, hsz)):
            if sz > lim:
                raise _fail("SCX_FILE_TOO_LARGE", self.too_large(f"{nm.rsplit('/', 1)[-1]} {sz} B"))
        self.check_free(rsz + hsz)
        self.echo(f"[esl-worker] SCX_FETCH: 루트 {self.p['root']} — rad {paths.root_sub(rad, self.root_rel)} ({_mb(rsz)}), "
                  f"h3d {paths.root_sub(h3d, self.root_rel)} ({_gb(hsz)} GB)")
        self.progress(0.0, "rad 받는 중")
        self.fetch_to_stage(rad, "rad", m, size=rsz)
        starts = [rad]
        # 엔진 rad(같은 폴더, <stem>_0001.rad …)
        parent, _, rname = rad.rpartition("/")
        stem = run_stem(rname)
        if stem is None:
            self.echo(f"[esl-worker] starter 이름이 '<이름>_0000.rad' 가 아니라 엔진 rad 를 찾지 않습니다: {rname}")
            with self.ex._tx() as conn:                 # 화면(JobProgress 경고)에도 — 탭은 *_0000.rad 만 고르게 하므로 API 직접 호출 때만
                jobs_repo.add_warnings(conn, self.ex.job["id"], self.ex.token,
                                       [f"starter 이름이 '<이름>_0000.rad' 가 아니라 엔진 rad(_0001.rad…)를 찾지 않았습니다: {rname}"])
        else:
            for nm in sorted(engine_names(stem, [n for n, e in (self.entries(parent) or {}).items() if e.get("kind") == "file"],
                                          list(self.s.scx_drive.engine_globs))):
                if nm.casefold() == rname.casefold():
                    continue
                erel = f"{parent}/{nm}"
                self.limit_files(m)
                self.fetch_to_stage(erel, "engine", m)
                starts.append(erel)
        missing = self.collect_includes(m, starts)
        m["missing"] = missing
        self.save_manifest(m)
        placed = self.place(m)
        m["placed"] = True
        m["placement"] = placed
        self.save_manifest(m)
        self.progress(100.0, f"rad·include {len(m['files'])}개 받음")
        if missing:
            with self.ex._tx() as conn:
                jobs_repo.add_warnings(conn, self.ex.job["id"], self.ex.token,
                                       [f"SCX 에서 받지 못한 include {len(missing)}개 — 내려받기가 끝나면 SCX 탭의 [추가로 올리기]로 같은 세션에 추가하세요"])
        return {"files": len(m["files"]), "missing": len(missing)}

    def check_free(self, need: int) -> None:
        from esl_platform.api.services.uploads import disk_free

        free = disk_free(self.root_dir)
        reserve = int(self.s.upload.min_free_gb * 1024 ** 3)
        if free is not None and free < need + reserve:
            raise _fail("INSUFFICIENT_STORAGE", f"업로드 위치의 여유 공간이 부족합니다(필요 {need} B + 여유 {self.s.upload.min_free_gb} GB, "
                        f"현재 여유 {free} B)")

    def limit_files(self, m: dict[str, Any]) -> None:
        if len(m["files"]) >= int(self.s.scx_drive.max_files):
            raise _fail("SCX_TOO_MANY_FILES", messages.text("SCX_TOO_MANY_FILES") + f"({self.s.scx_drive.max_files}개)")

    def collect_includes(self, m: dict[str, Any], starts: list[str]) -> list[dict[str, Any]]:
        """include 폐포(SR-D-8): 스캔 → 못 찾은 참조의 후보(rad 폴더·참조한 파일 폴더 기준) 중 루트 안·허용 확장자·드라이브에 있는
        것을 받고 다시 스캔. 못 받은 참조는 {spec, src, reason} 목록."""
        from . import core_adapter

        depth = int(self.p.get("include_max_depth") or 8)
        tried: dict[str, str] = {}                 # 드라이브 경로 → 못 받은 사유(다음 스캔에서 같은 사유)
        missing: dict[tuple[str, str], dict[str, Any]] = {}
        for _round in range(int(self.s.scx_drive.max_files) + 1):
            got_new = False
            for srel in starts:
                local = self.stage_path(srel, create=False)
                try:
                    refs = core_adapter.scan_include_refs(local, depth, None, follow=self.inside_stage)
                except core_adapter.CoreError as exc:
                    self.echo(f"[esl-worker] include 스캔 실패({exc.code}) — {paths.root_sub(srel, self.root_rel)}")
                    continue
                for ref in refs:
                    if ref["found"] and self.inside_stage(ref["path"]):
                        continue
                    src_drive = self.stage_to_drive(ref["src"]) or ""
                    key = (ref["spec"], src_drive)
                    spec = str(ref["spec"]).replace("\\", "/")
                    if ref["found"] or posixpath.isabs(spec) or (len(spec) > 1 and spec[1] == ":"):
                        missing[key] = self._miss(ref, src_drive, "절대경로(드라이브 밖) — 받지 않음")
                        continue
                    cands = [c for c in (ref.get("candidates") or []) if self.stage_to_drive(c)]
                    if not cands:
                        missing[key] = self._miss(ref, src_drive, "SCX 드라이브 루트 밖 — 받지 않음")
                        continue
                    reason = "SCX 드라이브에 없음"
                    fetched = False
                    for c in cands:
                        drel = self.stage_to_drive(c)
                        if drel in tried:
                            reason = tried[drel]
                            continue
                        why = self._why_not(drel)
                        if why is not None:
                            tried[drel] = reason = why
                            continue
                        drel = paths.check_drive_rel(drel, self.health)
                        self.limit_files(m)
                        self.fetch_to_stage(drel, "include", m)
                        fetched = got_new = True
                        missing.pop(key, None)
                        break
                    if not fetched:
                        missing[key] = self._miss(ref, src_drive, reason)
            if not got_new:
                break
        out = list(missing.values())
        for x in out:
            self.echo(f"[esl-worker] include 받지 않음: {x['spec']} ({x['reason']})")
        return out

    def _why_not(self, drel: str) -> str | None:
        """include 후보(드라이브 경로)를 받을 수 없는 사유 — 받을 수 있으면 None."""
        ext = os.path.splitext(drel)[1].lower()
        if ext not in [e.lower() for e in self.s.upload.allowed_ext]:
            return f"허용되지 않는 확장자({ext or '없음'}) — 받지 않음"
        try:
            r = paths.check_drive_rel(drel, self.health)
            self.stage_path(r, create=False)
        except DomainError as exc:
            return f"경로 규칙 밖({exc.message[:80]}) — 받지 않음"
        if not paths.within(r, self.root_rel):
            return "SCX 드라이브 루트 밖 — 받지 않음"
        if self.drive_file(r) is None:
            return "SCX 드라이브에 없음"
        return None

    def _miss(self, ref: dict[str, Any], src_drive: str, reason: str) -> dict[str, Any]:
        return {"spec": str(ref["spec"])[:400], "src": paths.root_sub(src_drive, self.root_rel) if src_drive else None,
                "reason": reason}

    def place(self, m: dict[str, Any]) -> dict[str, str]:
        """임시 배치 → rad/<공통 조상 C 기준 상대>(os.replace, 원문 그대로) + uploads.files[] 항목. 다시 실행해도 같은 결과."""
        rels = sorted(m["files"])
        dirs = [r.rsplit("/", 1)[0] for r in rels]
        common = posixpath.commonpath(dirs) if dirs else self.root_rel
        allowed = list(self.s.upload.allowed_ext)
        placed: dict[str, str] = {}
        plan: list[tuple[str, list[str], str]] = []
        for r in rels:
            rec = m["files"][r]
            local_rel = "rad/" + posixpath.relpath(r, common)
            try:
                plan.append((r, U.check_rel(local_rel, allowed), local_rel))
            except DomainError as exc:
                if rec["kind"] == "rad":
                    raise _fail(exc.code, exc.message) from None
                m["missing"].append({"spec": paths.root_sub(r, self.root_rel), "src": None,
                                     "reason": f"업로드 경로 규칙 밖({exc.message[:80]}) — 받지 않음"})
        entries: list[dict[str, Any]] = []
        for r, segs, local_rel in plan:
            rec = m["files"][r]
            dst = U.target_path(self.up_dir, segs, create_parents=True, upload_root=self.root_dir)
            src = self.stage_path(r, create=False)
            if os.path.lexists(dst):
                U.check_existing_file(dst, self.up_dir)
                if not (os.path.getsize(dst) == int(rec["size"]) and sha256_file(dst) == rec["sha256"]):
                    raise _fail("UPLOAD_FILE_EXISTS", f"세션에 같은 경로의 다른 파일이 있습니다(덮어쓰지 않음): {local_rel}")
            else:
                U.check_existing_file(src, self.up_dir)
                os.replace(src, dst)
            placed[r] = local_rel
            extra = {"scx_session": self.scx_meta(m)} if rec["kind"] == "rad" else {}
            entries.append(self.file_entry(local_rel, int(rec["size"]), rec["sha256"], r, **extra))
        self.save_files(entries)
        self.echo(f"[esl-worker] 배치: 공통 폴더 {paths.root_sub(common, self.root_rel) or '.'} 기준 rad/ 아래 {len(entries)}개")
        return placed

    def scx_meta(self, m: dict[str, Any]) -> dict[str, Any]:
        return {"root": self.p["root"], "rad_rel": paths.root_sub(self.p["rad_rel"], self.root_rel),
                "h3d_rel": paths.root_sub(self.p["h3d_rel"], self.root_rel), "missing_specs": list(m.get("missing") or [])}

    # ---- SF_H3D
    def sf_h3d(self) -> dict[str, Any]:
        self.connect()
        h3d = self.p["h3d_rel"]
        name = h3d.rsplit("/", 1)[-1]
        rel = f"h3d/{name}"
        try:
            segs = U.check_rel(rel, list(self.s.upload.allowed_ext))
        except DomainError as exc:
            raise _fail(exc.code, exc.message) from None
        dst = U.target_path(self.up_dir, segs, create_parents=True, upload_root=self.root_dir)
        with self.ex.engine.connect() as conn:
            up = _upload(conn, self.up["id"])
        have = next((f for f in up["files"] if f["rel"] == rel and f.get("source") == "scx" and f.get("done")), None)
        if have and os.path.isfile(dst) and os.path.getsize(dst) == int(have["size"]):
            self.echo(f"[esl-worker] SF_H3D: 이미 받은 h3d({_gb(int(have['size']))} GB, sha256 {have['sha256'][:12]}…) — 건너뜀")
            return {"size": int(have["size"]), "sha256": have["sha256"], "reused": True}
        if os.path.lexists(dst):
            raise _fail("UPLOAD_FILE_EXISTS", f"세션에 같은 경로 파일이 이미 있습니다(덮어쓰지 않음): {rel}")
        e = self.drive_file(h3d)
        if e is None:
            raise _fail("SCX_PATH_NOT_FOUND", f"드라이브에 없는 경로입니다(이동·삭제됨): {name}")
        size = int(e.get("size") or 0)
        self.check_free(size)
        part = dst + U.PART_SUFFIX
        if os.path.lexists(part):
            U.check_existing_file(part, self.up_dir)
        # 받는 중 항목(done=False, scx_got) — 화면이 파일별 진행률을 보이게. 끝나면 같은 rel 의 완료 항목으로 바꾼다(save_files)
        pending = self.file_entry(rel, size, "", h3d)
        pending.update(done=False, sha256=None, sha256_expected=None, got=[], scx_got=0)
        self.save_files([pending])
        self._live_rel = rel
        self.progress(0.0, "h3d: 대시보드가 SCX에서 받는 중", got=0)
        t0 = time.monotonic()
        try:
            got, sha = self.download(h3d, part, size, "h3d")
        except BaseException:
            self.drop_pending(rel)                # 실패·취소: 받는 중 항목을 뺀다(.part 는 남김 — 재시도 때 덮어씀)
            raise
        finally:
            self._live_rel = None
        U.check_existing_file(part, self.up_dir)
        if os.path.lexists(dst):
            raise _fail("UPLOAD_FILE_EXISTS", f"세션에 같은 경로 파일이 이미 있습니다(덮어쓰지 않음): {rel}")
        os.replace(part, dst)
        self.save_files([self.file_entry(rel, got, sha, h3d)])
        self.echo(f"[esl-worker] h3d: {name} {_gb(got)} GB, sha256 {sha[:12]}… ({time.monotonic() - t0:.1f}s)")
        self.progress(100.0, f"h3d {_amount(got, got)}")
        return {"size": got, "sha256": sha}

    # ---- SF_REGISTER
    def sf_register(self) -> dict[str, Any]:
        from esl_platform.api.services.uploads import inspect_upload

        ctx = SimpleNamespace(config=self.ex.worker.config, settings=self.s)
        m = self.manifest()
        with self.ex._tx() as conn:
            jobs_repo.assert_lease(conn, self.ex.job["id"], self.ex.token)
            up = _upload(conn, self.up["id"], for_update=True)
            if up is None or up["state"] != "OPEN":
                raise _fail("UPLOAD_CLOSED", "업로드 세션이 이미 끝났습니다")
            res = inspect_upload(ctx, up)
            res["scx"] = self.scx_meta(m)
            vals: dict[str, Any] = {"result": res, "updated_at": _now()}
            if res["ok"]:
                vals.update(state="COMPLETED", completed_at=_now())
            conn.execute(update(uploads_t).where(uploads_t.c.id == up["id"]).values(**vals))
            jobs_repo.patch_result(conn, self.ex.job["id"], self.ex.token,
                                   {"upload_ok": bool(res["ok"]), "missing_includes": len(res.get("missing_includes") or []),
                                    "problems": len(res.get("problems") or [])})
            if not res["ok"]:
                jobs_repo.add_warnings(conn, self.ex.job["id"], self.ex.token,
                                       ["업로드 검사에 문제가 있습니다(누락 include 등) — 새 Case 화면에서 확인하세요"])
        self.echo(f"[esl-worker] SF_REGISTER: 업로드 검사 {'통과(COMPLETED)' if res['ok'] else '문제 있음(OPEN 유지)'} — "
                  f"누락 include {len(res.get('missing_includes') or [])}개, 문제 {len(res.get('problems') or [])}개")
        return {"upload_ok": bool(res["ok"])}


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


__all__ = ["prepare", "run_step", "mark_job_progress", "job_progress", "PrepareFailed"]
