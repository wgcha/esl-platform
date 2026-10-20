"""PC 업로드 클라이언트(scripts/windows/esl_upload_lib.ps1) 시험용 가짜 ESL 서버(http.server, 표준 라이브러리만).

계약 esl_p3_ux.md §1.1·§8·§9.1 의 업로드·PC 연결 API 를 흉내 낸다(접두 /esl/api):
  POST /client-tokens/exchange {code, device_name} -> {token, user, project, expires_at}
  GET  /version
  POST /uploads {project_id, name, files:[{rel,size}]} -> 201 UploadOut
  GET  /uploads/{id}, POST /uploads/{id}/files, DELETE /uploads/{id}
  PUT  /uploads/{id}/files/{index}?offset=  (octet-stream, X-Chunk-Sha256, 409 UPLOAD_OFFSET_MISMATCH detail.received)
  POST /uploads/{id}/complete -> missing_includes(설정 required_includes 중 아직 없는 rel)·state
Bearer 토큰(esl_ct_...)이 없거나 모르는 토큰이면 401.

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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PREFIX = "/esl/api"


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

    # ---- 업로드 객체(UploadOut 모양) ----
    def out(self, up: dict) -> dict:
        files = [{"index": i, "rel": f["rel"], "size": f["size"], "received": len(f["data"]), "done": f["done"],
                  "sha256": f["sha256"]} for i, f in enumerate(up["files"])]
        return {"upload_id": up["id"], "project_id": up["project_id"], "name": up["name"], "state": up["state"],
                "dir_path": "/srv/upload/" + up["id"], "chunk_size": self.chunk_size,
                "total_bytes": sum(f["size"] for f in up["files"]),
                "received_bytes": sum(len(f["data"]) for f in up["files"]), "files": files, "result": up.get("result"),
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
            for f in body["files"]:
                if f["rel"].split("/")[0] not in ("rad", "results", "h3d") or "\\" in f["rel"] or ".." in f["rel"]:
                    return self._err(422, "UPLOAD_NAME_INVALID", f"잘못된 rel: {f['rel']}")
                files.append({"rel": f["rel"], "size": int(f["size"]), "data": bytearray(), "done": False,
                              "sha256": None, "h": hashlib.sha256()})
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
        if method == "POST" and len(segs) == 3 and segs[2] == "files":
            for f in self._json()["files"]:
                nf = {"rel": f["rel"], "size": int(f["size"]), "data": bytearray(), "done": False, "sha256": None,
                      "h": hashlib.sha256()}
                self._finish_if_empty(nf)
                up["files"].append(nf)
            return self._send(200, st.out(up))
        if method == "POST" and len(segs) == 3 and segs[2] == "complete":
            pending = [f["rel"] for f in up["files"] if not f["done"]]
            if pending:
                return self._err(409, "UPLOAD_INCOMPLETE", f"아직 {len(pending)}개", pending=pending)
            rels = {f["rel"] for f in up["files"]}
            missing = [r for r in st.required_includes if r not in rels]
            ok = not missing
            res = {"ok": ok, "rad_path": "/srv/x.rad", "results_dir": "/srv/results/csv", "h3d_path": None,
                   "parts": st.parts if ok else [], "missing_includes": missing, "problems": []}
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

    def _put(self, up: dict, index: int, offset: int) -> None:
        st = self.st
        data = self._body()
        with st.lock:
            st.put_count += 1
            n = st.put_count
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


def start(host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, FakeState, str]:
    """서버를 스레드로 띄운다 -> (server, state, server_url '<http://host:port>/esl')."""
    srv = ThreadingHTTPServer((host, 0), Handler)
    srv.daemon_threads = True
    state = FakeState()
    srv.state = state  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state, f"http://{host}:{srv.server_address[1]}/esl"


if __name__ == "__main__":
    s, stt, url = start()
    stt.codes["123456"] = "p1"
    print(url, flush=True)
    threading.Event().wait()
