# 출처: wgcha/physicsai-platform release/v0.2.14 a363a89e8f93d3acfe90a9601318bf4f6cade0a7
#       packages/simdash_adapters/tests/fake_scx_relay.py (계약 esl_scx_relay.md §13 — 시험 가짜 릴레이 사본).
# esl 사본 변경(이 파일에서만): 다운로드 주입 drop_download(본문 절반 뒤 끊기 횟수)·download_delay_s(첫 바이트 전 대기 —
# 대시보드가 SCX 에서 받는 시간 흉내)·download_gate(threading.Event — 설정되면 첫 바이트 전 그것을 기다림), files_served 기록,
# download_mid_gate(본문 절반 뒤 대기)·download_rate_bps(나눠 보내기).
"""가짜 SCX relay(phase3 §16.12) — `http.server`를 127.0.0.1 임의 포트에 띄워 scx_relay.md §5를 임시 폴더("드라이브")로 흉내.

대시보드·SCX 없이 PhysicsAI의 업로드 → 제출 → 상태 → 회수를 시험한다. `backend/tests`·`worker/tests`가 같은 가짜를 쓴다.

- 드라이브: `drive_dir`(= 공용 계정 홈). 경로 규칙(§4)·SPDM 금지(`forbidden_prefixes`)·키 검사(401)를 relay처럼 한다.
- 업로드 대기열: `/mkdirs`·`/files`는 묶음을 만들고 `GET /batches`마다 `batch_steps`를 하나씩 진행한다(마지막이 DONE이면 그때 드라이브에 씀).
  같은 이름·다른 내용이 드라이브에 있으면 CONFLICT(덮어쓰기 없음).
- 잡: `POST /jobs/radioss`는 request_id별 기록(replay는 어댑터 호출 없음 — `adapter_calls`로 확인). 상태는 `GET /jobs/{id}`마다
  `status_seq`를 하나씩 진행하고, `Completed`가 되면 `outputs`(이름 → 바이트)를 결과 폴더(`output_rel`)에 쓴다.
- 주입(시험이 속성을 바꾼다): `job_api`, `writes_active`, `submit_mode`("ok"|"unknown"|"fail:<CODE>"|"in_progress"),
  `submit_mode_seq`(제출마다 하나씩), `drop_submit`(응답 없이 끊는 횟수 — 기록은 남음), `drop_all`, `busy_status`(상태 조회 503 횟수), `hash_mismatch`(다운로드 잘못된 해시 횟수),
  `batch_steps`, `status_seq`, `output_mode`("job_dir"|"sub"|"none"), `resolve_mode`.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

PREFIX = "/internal/scx-relay/v1"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
SECRET = "k" * 22 + "-_" + "A1b2C3d4E5f6G7h8I9j0K"  # 43자 base64url(시험 전용)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


class FakeRelay:
    def __init__(self, drive_dir: Path, secret: str = SECRET) -> None:
        self.drive = Path(drive_dir)
        self.drive.mkdir(parents=True, exist_ok=True)
        self.secret = secret
        self.lock = threading.RLock()
        # 설정·주입
        self.job_api = True
        self.writes_active = True
        self.forbidden_prefixes = ["SPDM"]
        self.max_upload_bytes = 4 * 1024**3
        self.max_download_bytes = 20 * 1024**3
        self.batch_steps: list[str] = ["RUNNING", "DONE"]
        self.status_seq: list[str] = ["Queued", "Running", "Completed"]
        self.submit_mode = "ok"
        self.submit_mode_seq: list[str] = []  # 새 제출(어댑터 호출)마다 앞에서 하나씩 — 비면 submit_mode
        self.drop_submit = 0
        self.drop_all = False
        self.busy_status = 0
        self.hash_mismatch = 0
        self.drop_download = 0          # esl: 본문 절반을 보낸 뒤 연결을 끊는 횟수(중간 끊김)
        self.download_delay_s = 0.0     # esl: 첫 바이트 전 대기(대시보드가 SCX 에서 임시로 받는 시간)
        self.download_gate = None       # esl: threading.Event — 있으면 첫 바이트 전 set 될 때까지 대기
        self.download_mid_gate = None   # esl: threading.Event — 있으면 본문 절반을 보낸 뒤 set 될 때까지 대기(파일별 진행률 확인)
        self.download_rate_bps = 0      # esl: >0 이면 본문을 이 속도로 나눠 보냄(e2e 진행률 화면)
        self.files_served: list[str] = []
        self.output_mode = "job_dir"
        self.outputs: dict[str, bytes] = {}
        self.resolve_mode = "ok"
        # 기록
        self.requests: list[dict[str, Any]] = []
        self.headers_seen: list[dict[str, str]] = []
        self.batches: dict[str, dict[str, Any]] = {}
        self.batch_by_rid: dict[str, str] = {}
        self.submissions: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.adapter_calls: list[dict[str, Any]] = []
        self.terminated: list[str] = []
        self.resolves: list[dict[str, Any]] = []
        self._next_job = 1000
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    # ---- 수명 ----
    def start(self) -> FakeRelay:
        relay = self

        class H(_Handler):
            fake = relay

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def config_mapping(self, secret_file: str, **over: Any) -> dict[str, Any]:
        """이 relay를 가리키는 `hpc.scx` 설정 dict(시험용 짧은 대기·시간 한도)."""
        d: dict[str, Any] = {
            "relay_url": self.url, "secret_file": secret_file, "drive_base": "~", "home_display": "/Users/vd.dashboard",
            "appliance": "radioss-app", "version": "2026.1", "ncpu": 16, "memory_gb": None, "queue_type": "implicit",
            "run_type": "both - use starter and engine files", "mpi": "SMP (default)", "single_precision": False,
            "poll_interval_s": None, "max_download_bytes": 21474836480, "stage_patterns": ["*.rad", "*.inc", "*.csv"],
            "list_additional_paths": True, "max_stage_bytes": 21474836480, "stage_poll_s": 1, "stage_timeout_s": 60,
            "submit_replay_attempts": 3, "submit_replay_wait_s": 1, "http_timeout_s": 5, "transfer_timeout_s": 30,
            "collect_max_depth": 2, "health_ttl_s": 30,
        }
        d.update(over)
        return d

    def write_secret(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.secret + "\n", encoding="utf-8")
        return path

    # ---- 시험 도우미 ----
    def calls(self, path_prefix: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["path"].startswith(path_prefix)]

    def drive_file(self, rel: str) -> Path:
        return self.drive.joinpath(*rel.split("/"))

    def set_job_status(self, job_id: str, seq: list[str]) -> None:
        with self.lock:
            self.jobs[job_id]["seq"] = list(seq)

    # ---- 경로 규칙(§4) ----
    def path_error(self, rel: str, *, write: bool, min_depth: int = 1) -> tuple[int, str] | None:
        if not rel or rel.startswith(("/", "~")) or "\\" in rel or any(ord(c) < 0x20 or ord(c) == 0x7F for c in rel):
            return 400, "INVALID_PATH"
        parts = rel.split("/")
        if any(p in ("", ".", "..") or len(p) > 255 for p in parts) or len(rel) > 1024:
            return 400, "INVALID_PATH"
        if parts[0].startswith("."):
            return 403, "PATH_NOT_ALLOWED"
        p = _fold(rel)
        for s in self.forbidden_prefixes:
            s2 = _fold(s)
            if p == s2 or p.startswith(s2 + "/"):
                return 403, "PATH_NOT_ALLOWED"
        if write and len(parts) < min_depth:
            return 403, "PATH_NOT_ALLOWED"
        return None

    # ---- 묶음 ----
    def new_batch(self, request_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        bid = uuid.uuid4().hex
        b = {"batch_id": bid, "request_id": request_id, "state": "QUEUED", "steps": list(self.batch_steps), "items": items}
        self.batches[bid] = b
        self.batch_by_rid[request_id] = bid
        return b

    def batch_view(self, b: dict[str, Any]) -> dict[str, Any]:
        st = b["state"]
        return {"batch_id": b["batch_id"], "request_id": b["request_id"], "state": st,
                "finished": st in ("DONE", "PARTIAL", "CONFLICT", "FAILED", "CANCELLED"), "paused": st == "PAUSED",
                "items": [{k: v for k, v in it.items() if k != "data"} for it in b["items"]]}

    def advance_batch(self, b: dict[str, Any]) -> None:
        if b["state"] in ("DONE", "PARTIAL", "CONFLICT", "FAILED", "CANCELLED") or not b["steps"]:
            return
        nxt = b["steps"].pop(0)
        if nxt == "DONE":
            for it in b["items"]:
                dst = self.drive_file(it["target"])
                if it["kind"] == "MKDIR":
                    dst.mkdir(parents=True, exist_ok=True)
                    it["state"] = "DONE"
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and _sha(dst.read_bytes()) != it["sha256"]:
                    it["state"] = "CONFLICT"
                    nxt = "CONFLICT"
                    continue
                if not dst.exists():
                    dst.write_bytes(it["data"])
                it["state"] = "DONE"
        elif nxt in ("CONFLICT", "FAILED", "CANCELLED", "PARTIAL"):
            for it in b["items"]:
                it["state"] = "CONFLICT" if nxt == "CONFLICT" else "FAILED"
        b["state"] = nxt

    # ---- 잡 ----
    def output_rel_for(self, job_dir: str) -> str | None:
        if self.output_mode == "none":
            return None
        return job_dir + "/results" if self.output_mode == "sub" else job_dir

    def job_view(self, j: dict[str, Any]) -> dict[str, Any]:
        out_rel = j["output_rel"]
        return {"job_id": j["job_id"], "solver": "radioss", "status": j["status"],
                "output_path": ("/Users/vd.dashboard/" + out_rel) if out_rel else None, "output_rel": out_rel,
                "error_message": j.get("error_message")}

    def advance_job(self, j: dict[str, Any]) -> None:
        if j["seq"]:
            j["status"] = j["seq"].pop(0)
        if j["status"] == "Completed" and not j.get("written") and j["output_rel"]:
            base = self.drive_file(j["output_rel"])
            for name, data in self.outputs.items():
                p = base.joinpath(*name.split("/"))
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            j["written"] = True
        if j["status"] == "Failed":
            j["error_message"] = "solver error (Bearer abc.def.ghi)"


def _q(qs: dict[str, list[str]], k: str) -> str | None:
    v = qs.get(k)
    return v[0] if v else None


class _Handler(BaseHTTPRequestHandler):
    fake: FakeRelay
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # 시험 출력 조용히
        pass

    # ---- 응답 ----
    def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _err(self, status: int, code: str, message: str = "", retryable: bool = False) -> None:
        self._send(status, {"code": code, "message": message or code, "retryable": retryable, "retry_after": None, "adapter_code": None})

    def _drop(self) -> None:
        self.close_connection = True
        try:
            self.connection.shutdown(2)
        except OSError:
            pass

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self) -> Any:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else None

    def _route(self, method: str) -> None:
        f = self.fake
        u = urlsplit(self.path)
        path = u.path
        qs = parse_qs(u.query)
        with f.lock:
            f.requests.append({"method": method, "path": path[len(PREFIX):] if path.startswith(PREFIX) else path, "query": qs})
            f.headers_seen.append({k.lower(): v for k, v in self.headers.items()})
        if f.drop_all:
            self._body()
            return self._drop()
        if not path.startswith(PREFIX + "/"):
            return self._err(404, "NOT_FOUND")
        if self.headers.get("X-SCX-Relay-Key") != f.secret:
            self._body()
            return self._err(401, "RELAY_UNAUTHORIZED")
        sub = path[len(PREFIX):]
        handler = getattr(self, "_" + method.lower(), None)
        if handler is None:
            return self._err(405, "INVALID_REQUEST")
        return handler(sub, qs)

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    # ---- GET ----
    def _get(self, sub: str, qs: dict[str, list[str]]) -> None:
        f = self.fake
        if sub == "/health":
            return self._send(200, {"relay_version": 1, "drive_mode": "scx", "writes_active": f.writes_active, "job_api": f.job_api,
                                    "adapter_version": "0.3.0" if f.job_api else "0.2.0", "drive": None, "queue_paused": False,
                                    "relay_base": "", "forbidden_prefixes": list(f.forbidden_prefixes),
                                    "home_display": "/Users/vd.dashboard", "job_path_form": "rel",
                                    "max_upload_bytes": f.max_upload_bytes, "max_download_bytes": f.max_download_bytes})
        if sub.startswith("/batches/"):
            bid = unquote(sub[len("/batches/"):])
            with f.lock:
                b = f.batches.get(bid)
                if b is None:
                    return self._err(404, "NOT_FOUND")
                f.advance_batch(b)
                return self._send(200, f.batch_view(b))
        if sub == "/list":
            rel = _q(qs, "path") or ""
            err = f.path_error(rel, write=False)
            if err:
                return self._err(*err)
            d = f.drive_file(rel)
            if not d.is_dir():
                return self._err(404, "NOT_FOUND")
            mx = int(_q(qs, "max_entries") or 5000)
            ents = sorted(d.iterdir(), key=lambda p: p.name)
            if len(ents) > mx:
                return self._err(413, "LIMIT")
            return self._send(200, {"path": rel, "entries": [
                {"name": p.name, "rel_path": f"{rel}/{p.name}", "kind": "dir" if p.is_dir() else "file",
                 "size": None if p.is_dir() else p.stat().st_size, "modified_at": None, "sha1": None} for p in ents]})
        if sub == "/files":
            rel = _q(qs, "path") or ""
            err = f.path_error(rel, write=False)
            if err:
                return self._err(*err)
            p = f.drive_file(rel)
            if not p.is_file():
                return self._err(404, "NOT_FOUND")
            data = p.read_bytes()
            mx = min(int(_q(qs, "max_bytes") or f.max_download_bytes), f.max_download_bytes)
            if len(data) > mx:
                return self._err(413, "TOO_LARGE")
            sha = _sha(data)
            drop = False
            with f.lock:
                f.files_served.append(rel)
                if f.hash_mismatch > 0:
                    f.hash_mismatch -= 1
                    sha = "0" * 64
                if f.drop_download > 0:
                    f.drop_download -= 1
                    drop = True
            if f.download_delay_s:
                import time as _time

                _time.sleep(f.download_delay_s)
            if f.download_gate is not None:
                f.download_gate.wait(30)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-SHA256", sha)
            self.end_headers()
            if drop:
                self.wfile.write(data[: len(data) // 2])
                self.wfile.flush()
                return self._drop()
            if f.download_mid_gate is not None or f.download_rate_bps:
                import time as _time

                half = len(data) // 2
                step = max(1, int(f.download_rate_bps) // 10) if f.download_rate_bps else half or 1
                off = 0
                gated = False
                while off < len(data):
                    if not gated and off >= half and f.download_mid_gate is not None:
                        gated = True
                        self.wfile.flush()
                        f.download_mid_gate.wait(30)
                    n = min(step, len(data) - off)
                    if not gated and f.download_mid_gate is not None and off < half:
                        n = min(n, half - off)             # 절반에서 멈추도록
                    self.wfile.write(data[off:off + n])
                    off += n
                    if f.download_rate_bps:
                        self.wfile.flush()
                        _time.sleep(0.1)
                return None
            self.wfile.write(data)
            return None
        if sub.startswith("/jobs/"):
            jid = unquote(sub[len("/jobs/"):])
            with f.lock:
                j = f.jobs.get(jid)
                if j is None:
                    return self._err(404, "JOB_NOT_FOUND")
                if f.busy_status > 0:
                    f.busy_status -= 1
                    return self._err(503, "DRIVE_BUSY", retryable=True)
                f.advance_job(j)
                if j["status"] == "__SCX_NOT_FOUND__":
                    return self._err(404, "SCX_JOB_NOT_FOUND")
                return self._send(200, f.job_view(j))
        return self._err(404, "NOT_FOUND")

    # ---- POST ----
    def _post(self, sub: str, qs: dict[str, list[str]]) -> None:
        f = self.fake
        if sub == "/mkdirs":
            body = self._json() or {}
            if not f.writes_active:
                return self._err(409, "DRIVE_WRITE_DISABLED")
            rel = body.get("path") or ""
            err = f.path_error(rel, write=True, min_depth=1)
            if err:
                return self._err(*err)
            with f.lock:
                rid = str(body.get("request_id") or "")
                if rid in f.batch_by_rid:
                    return self._send(200, f.batch_view(f.batches[f.batch_by_rid[rid]]))
                b = f.new_batch(rid, [{"kind": "MKDIR", "target": rel, "state": "PENDING", "size": None, "attempts": 0,
                                        "next_attempt_at": None, "error_code": None, "error_message": None}])
                return self._send(202, f.batch_view(b))
        if sub == "/files":
            if self.headers.get("Content-Length") is None:
                return self._err(411, "LENGTH_REQUIRED")
            data = self._body()
            if not f.writes_active:
                return self._err(409, "DRIVE_WRITE_DISABLED")
            d, name = _q(qs, "dir") or "", _q(qs, "name") or ""
            if not name or any(c in name for c in "/\\:") or name in (".", ".."):
                return self._err(400, "INVALID_PATH")
            err = f.path_error(d, write=True, min_depth=2)
            if err:
                return self._err(*err)
            if len(data) > f.max_upload_bytes:
                return self._err(413, "TOO_LARGE")
            sha = (self.headers.get("X-Content-SHA256") or "").lower()
            rid = self.headers.get("X-Request-Id") or ""
            if not REQUEST_ID_RE.match(rid):  # scx_relay.md §5.3
                return self._err(400, "INVALID_REQUEST", "X-Request-Id 형식 오류")
            if sha != _sha(data):
                return self._err(400, "HASH_MISMATCH", retryable=True)
            with f.lock:
                if rid in f.batch_by_rid:
                    b = f.batches[f.batch_by_rid[rid]]
                    it = b["items"][-1]
                    if it["target"] != f"{d}/{name}" or it["sha256"] != sha:
                        return self._err(409, "REQUEST_ID_REUSED")
                    return self._send(200, f.batch_view(b))
                b = f.new_batch(rid, [
                    {"kind": "MKDIR", "target": d, "state": "PENDING", "size": None, "attempts": 0, "next_attempt_at": None,
                     "error_code": None, "error_message": None},
                    {"kind": "FILE", "target": f"{d}/{name}", "state": "PENDING", "size": len(data), "attempts": 0,
                     "next_attempt_at": None, "error_code": None, "error_message": None, "sha256": sha, "data": data}])
                return self._send(202, f.batch_view(b))
        if sub == "/jobs/radioss":
            raw = self._body()
            if not f.job_api:
                return self._err(501, "JOB_API_UNAVAILABLE")
            body = json.loads(raw.decode("utf-8"))
            return self._submit(body, _sha(raw))
        if sub.startswith("/jobs/") and sub.endswith("/terminate"):
            self._body()
            jid = unquote(sub[len("/jobs/"):-len("/terminate")])
            with f.lock:
                j = f.jobs.get(jid)
                if j is None:
                    return self._err(404, "JOB_NOT_FOUND")
                f.terminated.append(jid)
                j["seq"] = ["Aborted"]
                return self._send(200, {"job_id": jid, "requested": True})
        if sub.startswith("/submissions/") and sub.endswith("/resolve"):
            body = self._json() or {}
            rid = unquote(sub[len("/submissions/"):-len("/resolve")])
            with f.lock:
                f.resolves.append({"request_id": rid, **body})
                s = f.submissions.get(rid)
                if f.resolve_mode != "ok":
                    return self._err(503, f.resolve_mode, retryable=True)
                if s is None or s["state"] != "UNKNOWN":
                    return self._err(409, "NOT_UNKNOWN")
                if body.get("action") == "abandon":
                    s["state"] = "ABANDONED"
                    return self._send(200, {"request_id": rid, "state": "ABANDONED"})
                jid = str(body.get("job_id") or "")
                if jid not in f.jobs:
                    return self._err(404, "SCX_JOB_NOT_FOUND")
                if any(x.get("job_id") == jid for x in f.submissions.values()):
                    return self._err(409, "JOB_ID_IN_USE")
                s.update(state="ATTACHED", job_id=jid)
                return self._send(200, {"request_id": rid, "state": "ATTACHED", "job": f.job_view(f.jobs[jid])})
        return self._err(404, "NOT_FOUND")

    def _submit(self, body: dict[str, Any], sha: str) -> None:
        f = self.fake
        rid = str(body.get("request_id") or "")
        with f.lock:
            s = f.submissions.get(rid)
            if s is not None:
                if s["sha"] != sha:
                    return self._err(409, "REQUEST_ID_REUSED")
                if f.drop_submit > 0:
                    f.drop_submit -= 1
                    return self._drop()
                if s["state"] in ("SUBMITTED", "ATTACHED"):
                    return self._send(200, {"request_id": rid, "state": s["state"], "replayed": True,
                                            "job": f.job_view(f.jobs[s["job_id"]])})
                if s["state"] == "UNKNOWN":
                    return self._err(409, "SUBMISSION_UNKNOWN")
                if s["state"] == "ABANDONED":
                    return self._err(409, "SUBMISSION_ABANDONED")
                if s["state"] == "SUBMITTING":
                    return self._err(409, "SUBMISSION_IN_PROGRESS", retryable=True)
                return self._err(502, s["code"], "제출 실패(기록)")
            inp = str(body.get("input_path") or "")
            err = f.path_error(inp, write=True, min_depth=3)
            if err:
                return self._err(*err)
            job_dir = inp.rsplit("/", 1)[0]
            for p in [*body.get("engine_paths", []), *body.get("additional_paths", [])]:
                if not str(p).startswith(job_dir + "/"):
                    return self._err(422, "INVALID_REQUEST")
            if not f.drive_file(inp).is_file():
                return self._err(404, "NOT_FOUND")
            f.adapter_calls.append(body)
            mode = f.submit_mode_seq.pop(0) if f.submit_mode_seq else f.submit_mode
            if mode == "in_progress":
                f.submissions[rid] = {"sha": sha, "state": "SUBMITTING"}
                return self._err(409, "SUBMISSION_IN_PROGRESS", retryable=True)
            if mode == "unknown":
                f.submissions[rid] = {"sha": sha, "state": "UNKNOWN"}
                return self._err(409, "SUBMISSION_UNKNOWN")
            if mode.startswith("fail:"):
                code = mode.split(":", 1)[1]
                f.submissions[rid] = {"sha": sha, "state": "FAILED", "code": code}
                return self._err(502, code, "제출 실패")
            f._next_job += 1
            jid = f"scx-{f._next_job}"
            f.jobs[jid] = {"job_id": jid, "status": "Queued", "seq": list(f.status_seq), "output_rel": f.output_rel_for(job_dir),
                           "request_id": rid, "body": body}
            f.submissions[rid] = {"sha": sha, "state": "SUBMITTED", "job_id": jid}
            if f.drop_submit > 0:  # 기록은 남기고 응답 없이 끊음(전송 오류 → replay)
                f.drop_submit -= 1
                return self._drop()
            return self._send(201, {"request_id": rid, "state": "SUBMITTED", "replayed": False, "job": f.job_view(f.jobs[jid])})


def add_remote_job(f: FakeRelay, job_dir: str, status_seq: list[str] | None = None) -> str:
    """SCX 화면에서 사용자가 찾을 잡(attach 시험용)을 만든다 — relay 기록(submissions)에는 없음."""
    with f.lock:
        f._next_job += 1
        jid = f"scx-{f._next_job}"
        f.jobs[jid] = {"job_id": jid, "status": "Queued", "seq": list(status_seq or f.status_seq),
                       "output_rel": f.output_rel_for(job_dir), "request_id": None, "body": None}
        return jid


def secret_file(tmp: Path, f: FakeRelay) -> str:
    return str(f.write_secret(tmp / "secrets" / "scx_relay_key"))

