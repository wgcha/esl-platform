"""PC 업로드 클라이언트(scripts/windows/esl_upload_lib.ps1) 시험용 가짜 ESL 서버(http.server, 표준 라이브러리만).

계약 esl_p3_ux.md §1.1·§8·§9.1 의 업로드·PC 연결 API 를 흉내 낸다(접두 /esl/api):
  POST /client-tokens/exchange {code, device_name} -> {token, user, project, expires_at}
  GET  /version
  POST /uploads {project_id, name, files:[{rel,size}]} -> 201 UploadOut
  GET  /uploads/{id}, POST /uploads/{id}/files, DELETE /uploads/{id}
  PUT  /uploads/{id}/files/{index}?offset=  (octet-stream, X-Chunk-Sha256, 409 UPLOAD_OFFSET_MISMATCH detail.received)
  POST /uploads/{id}/complete -> missing_includes(설정 required_includes 중 아직 없는 rel)·state
Bearer 토큰(esl_ct_...)이 없거나 모르는 토큰이면 401.

업로드 프로토콜 2(계약 esl_upload_speed.md §5, state.protocol = 2; 기본 1 = 구 서버, 응답에 protocol 키 없음):
  UploadOut 에 protocol=2, chunk_size(C), max_parallel; 파일별 received(연속 앞부분 바이트)·received_total·chunks([[a,b),…])·
  n_chunks·removed·meta. PUT ?offset= 은 정렬된 청크 하나(offset = k·C, 길이 = 기대 길이)만 받고 순서 무관·동시 허용,
  이미 받은 청크는 200 duplicate:true. 같은 청크 동시 요청 409 CHUNK_IN_FLIGHT, 업로드당 동시 쓰기 > parallel_limit 이면
  429 UPLOAD_PARALLEL_LIMIT + Retry-After, 길이 불일치 422 CHUNK_LENGTH_MISMATCH. complete 는 409 UPLOAD_INCOMPLETE {pending:[{index,rel,missing}]},
  결과 h3d_meta. files[].meta 는 계약 §4.6 형식 검사(.h3d 만, 모르는 키·slim_bytes ≠ size → 422). DELETE /uploads/{id}/files/{index}.
  관측: max_inflight_seen(동시에 처리 중이던 PUT 최대), put_order([(index,k)] 도착 순서), put_bodies(PUT 본문 바이트 수 합).
  proto 2 전용 고장: put_delay(callable (index,k)->초: 처리 전 지연 = 응답 순서 뒤섞임), conflict_puts(번호 -> 409 CHUNK_IN_FLIGHT),
  ratelimit_puts(번호 -> 429), file_sha_fail_once(index: 마지막 청크 때 422 SHA256_MISMATCH 후 got 비움).

고장 흉내(시험이 속성으로 설정, PUT 요청 번호는 1부터):
  drop_after_write  : 이 번호의 PUT 은 데이터를 쓴 뒤 응답 없이 연결을 끊는다(클라이언트 재시도 -> 409 -> received 부터)
  fail_status       : {번호: 상태} 이 번호의 PUT 은 쓰지 않고 그 상태(503 등)로 응답
  fail_puts_from    : 이 번호 이후 모든 PUT 을 503 (클라이언트가 재시도를 다 쓰고 실패하게)
  corrupt_puts      : 이 번호의 PUT 은 청크 sha256 불일치(422 CHUNK_SHA256_MISMATCH)로 본다
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PREFIX = "/esl/api"

# 계약 esl_upload_speed.md §4.6: files[].meta 에 허용하는 키
META_KEYS = {"kind", "v", "source_name", "source_bytes", "source_mtime", "slim_bytes", "hvtrans_sec", "hvtrans_version",
             "cfg", "cfg_sha256", "part_id", "part_title", "results", "frames", "tool_version"}


def check_meta(f: dict) -> str:
    """POST /uploads files[i] 의 meta 검사. 문제가 있으면 사유, 없으면 ''."""
    meta = f.get("meta")
    if meta is None:
        return ""
    if not f["rel"].lower().endswith(".h3d"):
        return "meta 는 .h3d 파일에만 허용됩니다"
    if not isinstance(meta, dict) or meta.get("kind") not in ("h3d_slim", "h3d_original"):
        return "meta.kind 는 h3d_slim|h3d_original 이어야 합니다"
    extra = set(meta) - META_KEYS
    if extra:
        return f"meta 에 모르는 키: {sorted(extra)}"
    if len(json.dumps(meta, ensure_ascii=False).encode("utf-8")) > 16 * 1024:
        return "meta 가 16 KB 를 넘습니다"
    if meta["kind"] == "h3d_slim":
        if meta.get("slim_bytes") != f["size"]:
            return "meta.slim_bytes 가 파일 크기와 다릅니다"
        for k in ("source_name", "source_bytes", "source_mtime", "hvtrans_sec", "cfg", "cfg_sha256", "part_id", "part_title",
                  "results", "frames", "tool_version"):
            if k not in meta:
                return f"meta.{k} 가 없습니다"
        if len(meta["cfg"]) > 8192 or len(str(meta["part_title"])) > 200 or len(meta["source_name"]) > 255 \
                or len(meta["tool_version"]) > 32:
            return "meta 필드 길이 초과"
        if not isinstance(meta["part_id"], int) or isinstance(meta["part_id"], bool):
            return "meta.part_id 는 정수여야 합니다"
        if meta["frames"] != "all" or not isinstance(meta["results"], list) or not 0 < len(meta["results"]) <= 8:
            return "meta.frames/results 형식 오류"
        if len(meta["cfg_sha256"]) != 64:
            return "meta.cfg_sha256 은 hex64"
        if meta.get("hvtrans_version") is not None and len(str(meta["hvtrans_version"])) > 64:
            return "meta.hvtrans_version 길이 초과"
    return ""


class FakeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.chunk_size = 64 * 1024
        self.codes: dict[str, str] = {}            # code -> project_id
        self.tokens: dict[str, dict] = {}          # token -> {project_id, user}
        self.uploads: dict[str, dict] = {}
        self.required_includes: list[str] = []
        self.parts = [{"id": 1, "title": "chassis_rear"}]
        self.put_count = 0
        self.drop_after_write: set[int] = set()
        self.fail_status: dict[int, int] = {}
        self.fail_puts_from: int | None = None
        self.corrupt_puts: set[int] = set()
        self.log: list[tuple] = []                 # (method, path, status, extra)
        self.exchanges: list[dict] = []
        self.locked = False                        # 교환 잠금(429 CLIENT_CODE_LOCKED)
        # ---- 프로토콜 2 ----
        self.protocol = 1
        self.max_parallel = 4
        self.parallel_limit = 64                   # 업로드당 동시 쓰기 상한(넘으면 429)
        self.retry_after = "0"                     # 429 의 Retry-After 헤더 값(초)
        self.put_delay = None
        self.conflict_puts: set[int] = set()
        self.ratelimit_puts: set[int] = set()
        self.file_sha_fail_once: set[int] = set()
        self.max_inflight_seen = 0
        self.put_order: list[tuple[int, int]] = []
        self.put_bodies = 0
        self.inflight = 0
        self.writing: set[tuple[str, int, int]] = set()
        self.posts: list[dict] = []                # POST /uploads 요청 본문(client·files[].meta 확인용)

    def new_file(self, rel: str, size: int, meta=None) -> dict:
        f = {"rel": rel, "size": int(size), "data": bytearray(), "done": False, "sha256": None, "h": hashlib.sha256(),
             "got": set(), "meta": meta, "removed": False}
        if self.protocol >= 2:
            f["data"] = bytearray(int(size))            # 사전 할당
        return f

    @staticmethod
    def n_chunks(f: dict, c: int) -> int:
        return (f["size"] + c - 1) // c

    @staticmethod
    def expected_len(f: dict, c: int, k: int) -> int:
        return min(c, f["size"] - k * c)

    def total_got(self, f: dict) -> int:
        if f["done"]:
            return f["size"]
        return sum(self.expected_len(f, self.chunk_size, k) for k in f["got"])

    def prefix_bytes(self, f: dict) -> int:
        """앞에서부터 연속으로 받은 바이트."""
        if f["done"]:
            return f["size"]
        c, k = self.chunk_size, 0
        while k in f["got"]:
            k += 1
        return min(k * c, f["size"])

    def got_ranges(self, f: dict) -> list[list[int]]:
        out: list[list[int]] = []
        for k in sorted(f["got"]):
            if out and out[-1][1] == k:
                out[-1][1] = k + 1
            else:
                out.append([k, k + 1])
        return out

    def missing_ranges(self, f: dict) -> list[list[int]]:
        out: list[list[int]] = []
        for k in range(self.n_chunks(f, self.chunk_size)):
            if k not in f["got"]:
                if out and out[-1][1] == k:
                    out[-1][1] = k + 1
                else:
                    out.append([k, k + 1])
        return out

    # ---- 업로드 객체(UploadOut 모양) ----
    def out(self, up: dict) -> dict:
        if self.protocol < 2:
            files = [{"index": i, "rel": f["rel"], "size": f["size"], "received": len(f["data"]), "done": f["done"],
                      "sha256": f["sha256"]} for i, f in enumerate(up["files"])]
            return {"upload_id": up["id"], "project_id": up["project_id"], "name": up["name"], "state": up["state"],
                    "dir_path": "/srv/upload/" + up["id"], "chunk_size": self.chunk_size,
                    "total_bytes": sum(f["size"] for f in up["files"]),
                    "received_bytes": sum(len(f["data"]) for f in up["files"]), "files": files, "result": up.get("result"),
                    "created_at": up["created_at"], "updated_at": up["created_at"], "completed_at": None}
        files = []
        for i, f in enumerate(up["files"]):
            total = f["size"] if f["done"] else sum(self.expected_len(f, self.chunk_size, k) for k in f["got"])
            files.append({"index": i, "rel": f["rel"], "size": f["size"], "received": self.prefix_bytes(f), "received_total": total,
                          "chunks": self.got_ranges(f) if not f["done"] else [[0, self.n_chunks(f, self.chunk_size)]] if f["size"] else [],
                          "n_chunks": self.n_chunks(f, self.chunk_size), "done": f["done"], "sha256": f["sha256"],
                          "removed": f["removed"], "meta": f["meta"]})
        live = [x for x in files if not x["removed"]]
        return {"upload_id": up["id"], "project_id": up["project_id"], "name": up["name"], "state": up["state"],
                "protocol": 2, "max_parallel": self.max_parallel,
                "dir_path": "/srv/upload/" + up["id"], "chunk_size": self.chunk_size,
                "total_bytes": sum(x["size"] for x in live), "received_bytes": sum(x["received_total"] for x in live),
                "files": files, "result": up.get("result"),
                "created_at": up["created_at"], "updated_at": up["created_at"], "completed_at": None}

    def file_bytes(self, upload_id: str, rel: str) -> bytes:
        for f in self.uploads[upload_id]["files"]:
            if f["rel"] == rel:
                return bytes(f["data"])
        raise KeyError(rel)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FakeESL/1"

    def log_message(self, *args) -> None:  # 조용히
        pass

    @property
    def st(self) -> FakeState:
        return self.server.state  # type: ignore[attr-defined]

    # ---- 응답 도우미 ----
    def _send(self, status: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, code: str, message: str, **extra) -> None:
        self._send(status, {"detail": {"code": code, "message": message, **extra}})

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _auth(self) -> dict | None:
        h = self.headers.get("Authorization") or ""
        tok = h[7:] if h.startswith("Bearer ") else ""
        info = self.st.tokens.get(tok)
        if not info:
            self._err(401, "CLIENT_TOKEN_INVALID", "PC 연결 토큰이 만료되었거나 폐기되었습니다")
            return None
        return info

    def _route(self, method: str) -> None:
        u = urlparse(self.path)
        if not u.path.startswith(PREFIX):
            return self._err(404, "NOT_FOUND", "없음")
        path = u.path[len(PREFIX):]
        q = parse_qs(u.query)
        segs = [s for s in path.split("/") if s]
        st = self.st
        with st.lock:
            st.log.append((method, path, q.get("offset", [None])[0]))
        if method == "POST" and path == "/client-tokens/exchange":
            body = self._json()
            st.exchanges.append(body)
            if st.locked:
                return self._err(429, "CLIENT_CODE_LOCKED", "잠겼습니다")
            proj = st.codes.pop(str(body.get("code")), None)
            if not proj:      # 실제 서버와 같이 401 CLIENT_CODE_INVALID
                return self._err(401, "CLIENT_CODE_INVALID", "연결 코드가 맞지 않거나 만료되었습니다", remaining=4)
            tok = "esl_ct_" + uuid.uuid4().hex
            st.tokens[tok] = {"project_id": proj, "user": "kim"}
            exp = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=30)).isoformat()
            return self._send(200, {"token": tok, "token_id": uuid.uuid4().hex,
                                    "user": {"user_id": "u1", "username": "kim", "display_name": "Kim"},
                                    "project": {"id": proj, "name": proj}, "expires_at": exp})
        if method == "GET" and path == "/version":
            return self._send(200, {"version": "test"})
        if not segs or segs[0] != "uploads":
            return self._err(404, "NOT_FOUND", "없음")
        who = self._auth()
        if who is None:
            if method == "PUT":
                self._body()
            return None
        if method == "POST" and len(segs) == 1:
            body = self._json()
            if body.get("project_id") != who["project_id"]:
                return self._err(403, "FORBIDDEN", "다른 프로젝트")
            files = []
            st.posts.append(body)
            for f in body["files"]:
                if f["rel"].split("/")[0] not in ("rad", "results", "h3d") or "\\" in f["rel"] or ".." in f["rel"]:
                    return self._err(422, "UPLOAD_NAME_INVALID", f"잘못된 rel: {f['rel']}")
                bad = check_meta(f)
                if bad:
                    return self._err(422, "UPLOAD_META_INVALID", bad)
                files.append(st.new_file(f["rel"], f["size"], f.get("meta")))
            uid = "up_" + uuid.uuid4().hex[:12]
            st.uploads[uid] = {"id": uid, "project_id": who["project_id"], "name": body["name"], "state": "OPEN",
                               "files": files, "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
            for f in files:
                self._finish_if_empty(f)
            return self._send(201, st.out(st.uploads[uid]))
        up = st.uploads.get(segs[1]) if len(segs) >= 2 else None
        if up is None:
            if method == "PUT":
                self._body()
            return self._err(404, "UPLOAD_NOT_FOUND", "업로드가 없습니다")
        if method == "GET" and len(segs) == 2:
            return self._send(200, st.out(up))
        if method == "DELETE" and len(segs) == 2:
            up["state"] = "CANCELED"
            return self._send(200, st.out(up))
        if method == "DELETE" and len(segs) == 4 and segs[2] == "files":
            f = up["files"][int(segs[3])]
            f["removed"] = True
            f["got"] = set()
            return self._send(200, st.out(up))
        if method == "POST" and len(segs) == 3 and segs[2] == "files":
            for f in self._json()["files"]:
                nf = st.new_file(f["rel"], f["size"], f.get("meta"))
                self._finish_if_empty(nf)
                up["files"].append(nf)
            return self._send(200, st.out(up))
        if method == "POST" and len(segs) == 3 and segs[2] == "complete":
            live = [f for f in up["files"] if not f["removed"]]
            pending = [f["rel"] for f in live if not f["done"]]
            if pending:
                if st.protocol >= 2:
                    detail = [{"index": i, "rel": f["rel"], "missing": st.missing_ranges(f)}
                              for i, f in enumerate(up["files"]) if not f["removed"] and not f["done"]]
                    return self._err(409, "UPLOAD_INCOMPLETE", f"아직 {len(pending)}개", pending=detail)
                return self._err(409, "UPLOAD_INCOMPLETE", f"아직 {len(pending)}개", pending=pending)
            rels = {f["rel"] for f in live}
            missing = [r for r in st.required_includes if r not in rels]
            ok = not missing
            h3d = next((f for f in live if f["rel"].startswith("h3d/")), None)
            res = {"ok": ok, "rad_path": "/srv/x.rad", "results_dir": "/srv/results/csv",
                   "h3d_path": ("/srv/upload/" + up["id"] + "/" + h3d["rel"]) if h3d else None,
                   "parts": st.parts if ok else [], "missing_includes": missing, "problems": []}
            if st.protocol >= 2:
                res["h3d_meta"] = h3d["meta"] if h3d else None
            up["result"] = res
            if ok:
                up["state"] = "COMPLETED"
            return self._send(200, {"upload_id": up["id"], "state": up["state"], **res})
        if method == "PUT" and len(segs) == 4 and segs[2] == "files":
            return self._put(up, int(segs[3]), int(q["offset"][0]))
        return self._err(404, "NOT_FOUND", "없음")

    @staticmethod
    def _finish_if_empty(f: dict) -> None:
        if f["size"] == 0:
            f["done"] = True
            f["sha256"] = hashlib.sha256(b"").hexdigest()

    def _put2(self, up: dict, index: int, offset: int, data: bytes, n: int) -> None:
        """프로토콜 2 PUT: 정렬된 청크 하나를 위치 지정으로 쓴다(순서 무관·동시 허용)."""
        st = self.st
        c = st.chunk_size
        f = up["files"][index]
        if f["removed"]:
            return self._err(409, "UPLOAD_FILE_REMOVED", "목록에서 뺀 파일")
        if f["done"]:
            return self._err(409, "UPLOAD_FILE_DONE", "이미 다 받은 파일", received=f["size"])
        nch = st.n_chunks(f, c)
        if offset % c != 0 or offset // c >= nch:
            return self._err(409, "UPLOAD_OFFSET_MISMATCH", "offset 불일치", received=st.prefix_bytes(f))
        k = offset // c
        if len(data) != st.expected_len(f, c, k):
            return self._err(422, "CHUNK_LENGTH_MISMATCH", "청크 길이 불일치", expected=st.expected_len(f, c, k))
        if n in st.fail_status:
            return self._err(st.fail_status[n], "UNAVAILABLE", "잠시 후")
        if st.fail_puts_from is not None and n >= st.fail_puts_from:
            return self._err(503, "UNAVAILABLE", "잠시 후")
        if k in f["got"]:
            return self._send(200, {"index": index, "received": st.prefix_bytes(f), "received_total": st.total_got(f),
                                    "chunk": k, "duplicate": True, "done": f["done"], "sha256": f["sha256"]})
        key = (up["id"], index, k)
        with st.lock:
            conflict = n in st.conflict_puts or key in st.writing
            busy = sum(1 for w in st.writing if w[0] == up["id"])
            limited = (not conflict) and (n in st.ratelimit_puts or busy >= st.parallel_limit)
            if not conflict and not limited:
                st.writing.add(key)
                st.inflight += 1
                st.max_inflight_seen = max(st.max_inflight_seen, st.inflight)
        if conflict:
            return self._err(409, "CHUNK_IN_FLIGHT", "같은 청크를 쓰는 중")
        if limited:
            body = json.dumps({"detail": {"code": "UPLOAD_PARALLEL_LIMIT", "message": "동시 전송 한도"}}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", st.retry_after)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        try:
            if st.put_delay:
                time.sleep(float(st.put_delay(index, k)))
            sha = self.headers.get("X-Chunk-Sha256")
            if n in st.corrupt_puts or (sha is not None and hashlib.sha256(data).hexdigest() != sha.lower()):
                return self._err(422, "CHUNK_SHA256_MISMATCH", "청크 sha256 불일치")
            with st.lock:
                f["data"][offset:offset + len(data)] = data
                f["got"].add(k)
                if len(f["got"]) == nch:
                    if index in st.file_sha_fail_once:
                        st.file_sha_fail_once.discard(index)
                        f["got"] = set()
                        f["data"] = bytearray(f["size"])
                        return self._err(422, "SHA256_MISMATCH", "파일 sha256 불일치")
                    f["done"] = True
                    f["sha256"] = hashlib.sha256(bytes(f["data"])).hexdigest()
            if n in st.drop_after_write:
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return None
            return self._send(200, {"index": index, "received": st.prefix_bytes(f), "received_total": st.total_got(f),
                                    "chunk": k, "duplicate": False, "done": f["done"], "sha256": f["sha256"]})
        finally:
            with st.lock:
                st.writing.discard(key)
                st.inflight -= 1

    def _put(self, up: dict, index: int, offset: int) -> None:
        st = self.st
        data = self._body()
        with st.lock:
            st.put_count += 1
            n = st.put_count
            st.put_bodies += len(data)
            if st.protocol >= 2:
                st.put_order.append((index, offset // st.chunk_size))
        if st.protocol >= 2:
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/octet-stream":
                return self._err(415, "UNSUPPORTED_MEDIA_TYPE", "octet-stream 이어야 합니다")
            return self._put2(up, index, offset, data, n)
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/octet-stream":
            return self._err(415, "UNSUPPORTED_MEDIA_TYPE", "octet-stream 이어야 합니다")
        if st.fail_puts_from is not None and n >= st.fail_puts_from:
            return self._err(503, "UNAVAILABLE", "잠시 후")
        if n in st.fail_status:
            return self._err(st.fail_status[n], "UNAVAILABLE", "잠시 후")
        f = up["files"][index]
        if f["done"]:
            return self._err(409, "UPLOAD_FILE_DONE", "이미 다 받은 파일", received=f["size"])
        if offset != len(f["data"]):
            return self._err(409, "UPLOAD_OFFSET_MISMATCH", "offset 불일치", received=len(f["data"]))
        if len(data) > st.chunk_size:
            return self._err(413, "CHUNK_TOO_LARGE", "청크가 큽니다", limit=st.chunk_size)
        if offset + len(data) > f["size"]:
            return self._err(422, "CHUNK_OVERFLOW", "크기 초과", received=len(f["data"]))
        sha = self.headers.get("X-Chunk-Sha256")
        if n in st.corrupt_puts or (sha is not None and hashlib.sha256(data).hexdigest() != sha.lower()):
            return self._err(422, "CHUNK_SHA256_MISMATCH", "청크 sha256 불일치", received=len(f["data"]))
        f["data"] += data
        f["h"].update(data)
        if len(f["data"]) == f["size"]:
            f["done"] = True
            f["sha256"] = f["h"].hexdigest()
        if n in st.drop_after_write:      # 쓰고 나서 응답 없이 끊기(네트워크 단절 흉내)
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return None
        return self._send(200, {"index": index, "received": len(f["data"]), "done": f["done"], "sha256": f["sha256"]})

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PUT(self) -> None:
        self._route("PUT")

    def do_DELETE(self) -> None:
        self._route("DELETE")


def start(host: str = "127.0.0.1", protocol: int = 1) -> tuple[ThreadingHTTPServer, FakeState, str]:
    """서버를 스레드로 띄운다 -> (server, state, server_url '<http://host:port>/esl'). protocol 1 = 구 서버, 2 = 업로드 프로토콜 2."""
    srv = ThreadingHTTPServer((host, 0), Handler)
    srv.daemon_threads = True
    state = FakeState()
    state.protocol = protocol
    srv.state = state  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state, f"http://{host}:{srv.server_address[1]}/esl"


if __name__ == "__main__":
    s, stt, url = start()
    stt.codes["123456"] = "p1"
    print(url, flush=True)
    threading.Event().wait()
