"""v0.6.0 대용량 h3d 업로드 속도(계약 esl_upload_speed.md): 업로드 프로토콜 2 백엔드 시험 V-US-1~11·24·32 + 이슈 #29.

정렬 청크 순서 뒤섞임·중복·누락·재시작·길이/위치·동시 제한·메모리·구 클라이언트/구 세션·보안·sha 불일치·
Windows 위치 지정 쓰기(os.pwrite 없는 경로)·메타·SLIM_PART_MISMATCH·파일 빼기·UPLOAD_LIMIT 상세.
"""

from __future__ import annotations

import hashlib
import os
import random
import socket
import threading
import time
import tracemalloc
from pathlib import Path

import httpx
import pytest
from esl_test_support import API, H, make_settings_dict
from sqlalchemy import text
from test_p3_ux import RESULTS, all_files, create, mini_rad_text, spec

W = H("tok-power", True)
R = H("tok-power")
CS = 1024 * 1024
OCT = {"Content-Type": "application/octet-stream"}


@pytest.fixture()
def settings_dict(tmp_path, request):
    chunk = 64 if request.node.get_closest_marker("chunk64") else 1
    d = make_settings_dict(tmp_path)
    d["storage"]["upload_root"] = str(tmp_path / "esl-input")
    d["upload"] = {"chunk_mb": chunk, "parallel": 4, "max_file_bytes": 2 * 1024 ** 3,
                   "max_upload_bytes": 4 * 1024 ** 3, "min_free_gb": 0}
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.txt").write_text("outside")
    return d


@pytest.fixture()
def upload_root(settings_dict) -> Path:
    return Path(settings_dict["storage"]["upload_root"])


def code(r) -> str:
    return r.json()["detail"]["code"]


def put2(client, uid, index, k, data, cs=CS, *, sha=True, token="tok-power", **hdr):
    h = {**H(token, True), **OCT, **hdr}
    if sha:
        h.setdefault("X-Chunk-Sha256", hashlib.sha256(data).hexdigest())
    return client.put(f"{API}/uploads/{uid}/files/{index}", params={"offset": k * cs}, content=data, headers=h)


def chunks_of(data: bytes, cs: int = CS) -> list[bytes]:
    return [data[i:i + cs] for i in range(0, len(data), cs)] or [b""]


def get(client, uid, token="tok-power"):
    return client.get(f"{API}/uploads/{uid}", headers=H(token)).json()


def mk(client, files, name="u", **kw):
    r = create(client, files, name=name, **kw)
    assert r.status_code == 201, r.text
    return r.json()


BIG = b"HYPER3D " + os.urandom(5 * CS + 12345)          # 6 청크(마지막 짧음)


def hdir(up) -> Path:
    return Path(up["dir_path"])


# ---------------------------------------------------------------- 기본: 프로토콜 2 응답 필드
def test_create_reports_protocol_chunk_parallel(client):
    up = mk(client, {"rad/m_0000.rad": mini_rad_text(), "h3d/a.h3d": BIG})
    assert up["protocol"] == 2 and up["chunk_size"] == CS and up["max_parallel"] == 4
    f = up["files"][1]
    assert (f["n_chunks"], f["chunks"], f["received"], f["received_total"], f["removed"], f["meta"]) == \
        (6, [], 0, 0, False, None)
    assert up["total_bytes"] == len(BIG) + len(mini_rad_text())


def test_config_defaults():
    from esl_platform.core.config import UiCfg, UploadCfg

    u = UploadCfg()
    assert (u.chunk_mb, u.parallel, u.write_buffer_kb, u.preallocate) == (64, 4, 1024, True)
    assert UiCfg.model_fields["upload_slim_hint_gb"].default == 5


def test_version_exposes_slim_hint(client):
    r = client.get(f"{API}/version", headers=R).json()
    assert r["ui"] == {"upload_slim_hint_gb": 5}


# ---------------------------------------------------------------- V-US-1 순서 뒤섞임
def test_v_us_1_shuffled_chunks(client):
    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    parts = chunks_of(BIG)
    assert len(parts) == 6
    order = [5, 2, 0, 4, 1, 3]                       # 마지막 청크 먼저
    for n, k in enumerate(order):
        r = put2(client, uid, 0, k, parts[k])
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["duplicate"] is False and j["chunk"] == k and j["done"] == (n == len(order) - 1)
        g = get(client, uid)["files"][0]
        if n == 0:
            assert g["received"] == 0 and g["received_total"] == len(parts[5]) and g["chunks"] == [[5, 6]]
        if n == 1:
            assert g["received"] == 0 and g["received_total"] == len(parts[5]) + CS and g["chunks"] == [[2, 3], [5, 6]]
        if n == 3:                                    # 5,2,0,4 → 0 만 연속
            assert g["received"] == CS and g["chunks"] == [[0, 1], [2, 3], [4, 6]]
    g = get(client, uid)["files"][0]
    assert g["done"] and g["received"] == len(BIG) == g["received_total"] and g["chunks"] == [[0, 6]]
    assert g["sha256"] == hashlib.sha256(BIG).hexdigest()
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == BIG and not list(hdir(up).rglob("*.part"))


def test_random_permutations_many(client):
    data = os.urandom(7 * CS + 1)
    rnd = random.Random(7)
    for t in range(3):
        up = mk(client, {"h3d/a.h3d": data}, name=f"p{t}")
        ks = list(range(8))
        rnd.shuffle(ks)
        parts = chunks_of(data)
        for k in ks:
            assert put2(client, up["upload_id"], 0, k, parts[k]).status_code == 200
        assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data
        client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)       # 사용자당 OPEN 한도(2) 회피


# ---------------------------------------------------------------- V-US-2 중복·동시
def test_v_us_2_duplicates_and_inflight(client):
    from esl_platform.api.services import uploads as svc

    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    parts = chunks_of(BIG)
    assert put2(client, uid, 0, 1, parts[1]).status_code == 200
    part = hdir(up) / "h3d" / "a.h3d.part"
    m0, c0 = part.stat().st_mtime_ns, part.read_bytes()
    time.sleep(0.02)
    r = put2(client, uid, 0, 1, b"\xff" * CS)                      # 받은 청크에 다른 내용 → duplicate, 쓰기 없음
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert part.stat().st_mtime_ns == m0 and part.read_bytes() == c0
    r = put2(client, uid, 0, 1, b"\xff" * CS, sha=False, **{"X-Chunk-Sha256": "0" * 64})
    assert r.status_code == 200 and r.json()["duplicate"] is True   # 손상 청크(sha 불일치)도 받은 청크는 안 덮음
    assert part.read_bytes() == c0
    # 손상 청크가 아직 안 받은 청크면 422, 표시 안 함 → 올바른 청크가 덮어씀
    r = put2(client, uid, 0, 2, os.urandom(CS), sha=False, **{"X-Chunk-Sha256": "1" * 64})
    assert r.status_code == 422 and code(r) == "CHUNK_SHA256_MISMATCH"
    assert get(client, uid)["files"][0]["chunks"] == [[1, 2]]
    assert put2(client, uid, 0, 2, parts[2]).status_code == 200
    # 같은 (index, k) 가 쓰는 중이면 409 CHUNK_IN_FLIGHT
    with svc._GUARD:
        svc._INFLIGHT.setdefault(uid, set()).add((0, 3))
    try:
        r = put2(client, uid, 0, 3, parts[3])
        assert r.status_code == 409 and code(r) == "CHUNK_IN_FLIGHT"
    finally:
        svc.reset_state()
    for k in (0, 3, 4, 5):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == BIG


def test_real_concurrent_same_chunk_one_in_flight(client, app_ctx):
    """같은 청크 동시 2요청 → 하나는 409 CHUNK_IN_FLIGHT(또는 늦은 쪽이 duplicate), 파일은 정확."""
    data = os.urandom(3 * CS)
    up = mk(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    res: list = []

    def go():
        res.append(put2(client, uid, 0, 1, parts[1]))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ok = [r for r in res if r.status_code == 200 and not r.json()["duplicate"]]
    assert len(ok) == 1, [(r.status_code, r.text[:80]) for r in res]
    assert all(r.status_code == 200 or code(r) == "CHUNK_IN_FLIGHT" for r in res)
    for k in (0, 2):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data


# ---------------------------------------------------------------- V-US-3 누락
def test_v_us_3_missing_chunks_blocks_complete(client):
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/a.h3d": BIG}
    up = mk(client, files)
    uid = up["upload_id"]
    rad = files["rad/m_0000.rad"]
    assert put2(client, uid, 0, 0, rad).status_code == 200
    parts = chunks_of(BIG)
    for k in (0, 1, 4, 5):
        put2(client, uid, 1, k, parts[k])
    r = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_INCOMPLETE"
    pend = r.json()["detail"]["pending"]
    assert pend == [{"index": 1, "rel": "h3d/a.h3d", "missing": [[2, 4]]}]
    for k in (2, 3):
        put2(client, uid, 1, k, parts[k])
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert c["ok"] and c["h3d_meta"] is None


def test_complete_detects_disk_size_mismatch(client):
    up = mk(client, {"rad/m_0000.rad": mini_rad_text(), **{"h3d/a.h3d": BIG[:CS + 5]}})
    uid = up["upload_id"]
    rad = mini_rad_text()
    put2(client, uid, 0, 0, rad)
    for k, p in enumerate(chunks_of(BIG[:CS + 5])):
        put2(client, uid, 1, k, p)
    (hdir(up) / "h3d" / "a.h3d").write_bytes(b"HYPER3D")             # 디스크 쪽 변조(크기 달라짐)
    r = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_INCOMPLETE" and r.json()["detail"]["pending"][0]["index"] == 1


# ---------------------------------------------------------------- V-US-4 재시작
def test_v_us_4_restart_midway(client):
    from esl_platform.api.services import uploads as svc

    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    parts = chunks_of(BIG)
    for k in (0, 1, 3):
        put2(client, uid, 0, k, parts[k])
    svc.reset_state()                                          # 앱 재생성: 해시 추적기·진행 중 목록 소실
    g = get(client, uid)["files"][0]
    assert g["chunks"] == [[0, 2], [3, 4]] and g["received"] == 2 * CS
    # 디스크엔 썼지만 표시 전 중단된 청크(쓰레기) → 재전송이 덮어씀
    part = hdir(up) / "h3d" / "a.h3d.part"
    with open(part, "r+b") as fh:
        fh.seek(2 * CS)
        fh.write(b"\xAA" * CS)
    for k in (2, 5, 4):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    g = get(client, uid)["files"][0]
    assert g["done"] and g["sha256"] == hashlib.sha256(BIG).hexdigest()
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == BIG


def test_all_chunks_marked_but_not_finalized_is_finalized_by_get_and_complete(client, app_ctx):
    """마지막 청크 표시 직후 마무리 전에 프로세스가 죽은 경우: GET/complete 가 멱등 마무리."""
    from esl_platform.api.services import uploads as svc

    data = os.urandom(2 * CS)
    up = mk(client, {"rad/m_0000.rad": mini_rad_text(), "h3d/a.h3d": b"HYPER3D" + data})
    uid = up["upload_id"]
    put2(client, uid, 0, 0, mini_rad_text())
    blob = b"HYPER3D" + data
    parts = chunks_of(blob)
    orig = svc._finalize_file
    try:
        svc._finalize_file = lambda *a, **k: (False, None)         # 마무리 직전 중단 흉내
        for k, p in enumerate(parts):
            put2(client, uid, 1, k, p)
    finally:
        svc._finalize_file = orig
    assert get_raw_done(app_ctx, uid, 1) in (None, "false")          # 마무리 전 상태
    g = client.get(f"{API}/uploads/{uid}", headers=R).json()["files"][1]
    assert g["done"] and g["sha256"] == hashlib.sha256(blob).hexdigest()
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == blob


def get_raw_done(ctx, uid, index):
    with ctx.engine.connect() as c:
        return c.execute(text("SELECT files->:i->>'done' FROM uploads WHERE id=:u"), {"i": index, "u": uid}).scalar()


# ---------------------------------------------------------------- V-US-5 길이·위치
def test_v_us_5_lengths_and_offsets(client):
    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    parts = chunks_of(BIG)
    # 정렬 안 된 offset / 범위 밖 k
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 7}, content=parts[0], headers={**W, **OCT})
    assert r.status_code == 409 and code(r) == "UPLOAD_OFFSET_MISMATCH"
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 6 * CS}, content=b"x", headers={**W, **OCT})
    assert r.status_code == 409 and code(r) == "UPLOAD_OFFSET_MISMATCH"
    # 길이 불일치(마지막 청크만 짧음)
    assert put2(client, uid, 0, 0, parts[0][:-1]).status_code == 422
    r = put2(client, uid, 0, 5, parts[5] + b"x")
    assert r.status_code == 422 and code(r) == "CHUNK_LENGTH_MISMATCH"
    r = put2(client, uid, 0, 0, parts[0] + b"x")                   # > C → 413
    assert r.status_code == 413 and code(r) == "CHUNK_TOO_LARGE"
    # Content-Length 없음(chunked) → 411
    def gen():
        yield parts[0]
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 0}, content=gen(), headers={**W, **OCT})
    assert r.status_code == 411 and code(r) == "LENGTH_REQUIRED"
    # 선언보다 긴 본문 → 413, 표시 없음
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 0}, content=parts[0] + b"x" * 100,
                   headers={**W, **OCT, "Content-Length": str(CS)})
    assert r.status_code == 413 and code(r) == "CHUNK_TOO_LARGE"
    assert get(client, uid)["files"][0]["chunks"] == []
    # 선언보다 짧은 본문(연결 끊김과 같음) → 표시 없음
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 0}, content=parts[0][:1000],
                   headers={**W, **OCT, "Content-Length": str(CS)})
    assert r.status_code >= 400 and get(client, uid)["files"][0]["chunks"] == []
    assert put2(client, uid, 0, 0, parts[0]).status_code == 200


def test_media_type_and_missing_file(client):
    up = mk(client, {"h3d/a.h3d": b"HYPER3D"})
    r = client.put(f"{API}/uploads/{up['upload_id']}/files/0", params={"offset": 0}, content=b"x",
                   headers={**W, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert put2(client, up["upload_id"], 9, 0, b"x").status_code == 404


# ---------------------------------------------------------------- V-US-6 동시 제한·메모리 (실제 HTTP 서버)
class Live:
    def __init__(self, app) -> None:
        import uvicorn

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error",
                                                    proxy_headers=False, lifespan="off"))
        self.t = threading.Thread(target=self.server.run, daemon=True)
        self.t.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        self.base = f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.should_exit = True
        self.t.join(10)


@pytest.fixture()
def live(app_ctx):
    from esl_platform.api.main import create_app

    lv = Live(create_app(app_ctx))
    yield lv
    lv.stop()


def stream_put(base, uid, index, k, data, cs, **hdr):
    def gen():
        for i in range(0, len(data), 1 << 20):
            yield data[i:i + (1 << 20)]
    h = {**W, **OCT, "Content-Length": str(len(data)), **hdr}
    return httpx.put(f"{base}{API}/uploads/{uid}/files/{index}", params={"offset": k * cs}, content=gen(), headers=h,
                     timeout=60)


def test_v_us_6_parallel_limit_429_retry_after(client):
    from esl_platform.api.services import uploads as svc

    data = os.urandom(8 * CS)
    up = mk(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    with svc._GUARD:
        svc._INFLIGHT[uid] = {(0, 4), (0, 5), (0, 6), (0, 7)}      # parallel=4 가 쓰는 중
    try:
        r = put2(client, uid, 0, 0, data[:CS])
        assert r.status_code == 429 and code(r) == "UPLOAD_PARALLEL_LIMIT" and r.headers.get("retry-after") == "1"
    finally:
        svc.reset_state()
    assert put2(client, uid, 0, 0, data[:CS]).status_code == 200


def test_live_parallel_four_workers_correct_and_no_429(live, client):
    data = os.urandom(12 * CS + 7)
    up = mk(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    q = list(range(len(parts)))
    lock = threading.Lock()
    errs: list = []

    def worker():
        while True:
            with lock:
                if not q:
                    return
                k = q.pop(0)
            for _ in range(20):
                r = stream_put(live.base, uid, 0, k, parts[k], CS)
                if r.status_code == 429:
                    time.sleep(0.05)
                    continue
                if r.status_code != 200:
                    errs.append((k, r.status_code, r.text[:100]))
                break

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    g = get(client, uid)["files"][0]
    assert g["done"] and g["sha256"] == hashlib.sha256(data).hexdigest()
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data


def test_live_disconnect_midway_marks_nothing(live, client):
    data = os.urandom(2 * CS)
    up = mk(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    tok = "tok-power"
    s = socket.create_connection(("127.0.0.1", live.port))
    s.sendall((f"PUT {API}/uploads/{uid}/files/0?offset=0 HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {tok}\r\n"
               f"X-ESL-Request: 1\r\nContent-Type: application/octet-stream\r\nContent-Length: {CS}\r\n\r\n").encode())
    s.sendall(data[:300_000])
    time.sleep(0.3)
    s.close()
    time.sleep(0.5)
    assert get(client, uid)["files"][0]["chunks"] == []
    from esl_platform.api.services import uploads as svc

    assert not svc._INFLIGHT.get(uid)
    assert stream_put(live.base, uid, 0, 0, data[:CS], CS).status_code == 200


@pytest.mark.chunk64
def test_v_us_6_memory_per_request_under_8mb(live, client):
    data = b"HYPER3D" + os.urandom(64 * CS - 7)                  # 64 MB 한 청크
    up = mk(client, {"h3d/a.h3d": data})
    assert up["chunk_size"] == 64 * CS and up["files"][0]["n_chunks"] == 1
    tracemalloc.start()
    try:
        base, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        r = stream_put(live.base, up["upload_id"], 0, 0, data, 64 * CS)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r.status_code == 200 and r.json()["done"]
    assert peak - base <= 8 * CS, f"요청당 메모리 {(peak - base) / CS:.1f} MB"


# ---------------------------------------------------------------- V-US-7 호환: 구 순차 클라이언트·구 세션
def test_old_sequential_client_works_on_protocol_2(client):
    """구 클라이언트: chunk_size 로 offset = received 순서. 마지막 청크 응답 done."""
    up = mk(client, {"h3d/a.h3d": BIG})
    uid, off = up["upload_id"], 0
    while off < len(BIG):
        piece = BIG[off:off + up["chunk_size"]]
        r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": off}, content=piece, headers={**W, **OCT})
        assert r.status_code == 200, r.text
        off = r.json()["received"]
    assert r.json()["done"] and r.json()["sha256"] == hashlib.sha256(BIG).hexdigest()


def _downgrade_to_v1(ctx, uid):
    """업그레이드 전 OPEN 세션 흉내: 파일 항목에서 proto·chunk·got·removed 제거."""
    with ctx.engine.begin() as c:
        files = c.execute(text("SELECT files FROM uploads WHERE id=:u"), {"u": uid}).scalar_one()
        for f in files:
            for k in ("proto", "chunk", "got", "removed"):
                f.pop(k, None)
        import json

        c.execute(text("UPDATE uploads SET files = CAST(:f AS jsonb) WHERE id=:u"), {"f": json.dumps(files), "u": uid})


def test_old_session_without_proto_keeps_append_path(client, app_ctx):
    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    _downgrade_to_v1(app_ctx, uid)
    g = get(client, uid)
    assert g["protocol"] == 1 and g["files"][0]["received"] == 0
    # append: offset = 받은 크기, 임의 길이 허용(정렬·Content-Length 요구 없음)
    sizes = [100_000, 1_000_000, 777_777]
    off = 0
    for n in sizes:
        r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": off}, content=BIG[off:off + n], headers={**W, **OCT})
        assert r.status_code == 200, r.text
        off = r.json()["received"]
    assert get(client, uid)["files"][0]["received"] == off
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 5}, content=b"x", headers={**W, **OCT})
    assert r.status_code == 409 and code(r) == "UPLOAD_OFFSET_MISMATCH" and r.json()["detail"]["received"] == off
    from esl_platform.api.services import uploads as svc

    svc.reset_state()                                          # 재시작: 받은 .part 크기 기준 이어 올리기
    while off < len(BIG):
        r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": off}, content=BIG[off:off + CS], headers={**W, **OCT})
        assert r.status_code == 200, r.text
        off = r.json()["received"]
    assert r.json()["done"] and r.json()["sha256"] == hashlib.sha256(BIG).hexdigest()
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == BIG
    # 구 세션에 파일 추가 → 같은 프로토콜 1 유지
    up2 = mk(client, {"h3d/b.h3d": b"HYPER3D"}, name="v1b")
    _downgrade_to_v1(app_ctx, up2["upload_id"])
    r = client.post(f"{API}/uploads/{up2['upload_id']}/files", headers=W, json={"files": [{"rel": "rad/x.rad", "size": 3}]})
    assert r.json()["protocol"] == 1 and "proto" not in str(r.json()["files"][1]["meta"])


# ---------------------------------------------------------------- V-US-9 보안
def test_v_us_9_security(client, upload_root, tmp_path):
    from esl_platform.api.services import uploads as svc

    data = os.urandom(2 * CS)
    up = mk(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    out = tmp_path / "outside"
    d = hdir(up)
    # .part 심링크
    os.symlink(out / "secret.txt", d / "h3d" / "a.h3d.part")
    r = put2(client, uid, 0, 0, parts[0])
    assert r.status_code == 422 and code(r) == "PATH_UNSAFE"
    os.unlink(d / "h3d" / "a.h3d.part")
    # .part 하드 링크
    os.link(out / "secret.txt", d / "h3d" / "a.h3d.part")
    r = put2(client, uid, 0, 0, parts[0])
    assert r.status_code == 422 and code(r) == "PATH_UNSAFE"
    os.unlink(d / "h3d" / "a.h3d.part")
    assert (out / "secret.txt").read_text() == "outside"
    # 폴더 바꿔치기(h3d → 바깥 링크)
    shutil_dir = d / "h3d"
    shutil_dir.rename(d / "h3d_orig")
    os.symlink(out, d / "h3d")
    r = put2(client, uid, 0, 0, parts[0])
    assert r.status_code == 422 and code(r) == "PATH_UNSAFE"
    os.unlink(d / "h3d")
    (d / "h3d_orig").rename(d / "h3d")
    assert all_files(out) == {"secret.txt"}
    # 다른 사용자 404, 토큰
    assert put2(client, uid, 0, 0, parts[0], token="tok-power2").status_code == 404
    assert client.delete(f"{API}/uploads/{uid}/files/0", headers=H("tok-power2", True)).status_code == 404
    # 대시보드 세션(CSRF 헤더 없음) → 403
    r = client.delete(f"{API}/uploads/{uid}/files/0", headers=R)
    assert r.status_code == 403 and code(r) == "CSRF_HEADER_REQUIRED"
    # 최종 이름이 이미 있으면 마무리 409
    up2 = mk(client, {"h3d/b.h3d": data}, name="ex")
    p2 = hdir(up2) / "h3d" / "b.h3d"
    p2.write_bytes(b"squat")
    r = put2(client, up2["upload_id"], 0, 0, parts[0])
    assert r.status_code == 409 and code(r) == "UPLOAD_FILE_EXISTS"
    svc.reset_state()


def test_pc_token_scope_covers_delete_file_and_csrf_exempt(client):
    from test_p3_pc_tokens import _bearer, _exchange, _new_code

    tok = _exchange(client, _new_code(client)["code"]).json()["token"]
    sp = [{"rel": "h3d/a.h3d", "size": 7}]
    up = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "pc", "files": sp}, headers=_bearer(tok)).json()
    assert up["protocol"] == 2
    r = client.delete(f"{API}/uploads/{up['upload_id']}/files/0", headers=_bearer(tok))     # Bearer: CSRF 면제
    assert r.status_code == 200 and r.json()["files"][0]["removed"] is True
    assert client.delete(f"{API}/uploads/{up['upload_id']}/files/0", headers=R).status_code == 403   # 세션은 CSRF 필요


def test_preallocation_failure_is_507(client, monkeypatch):
    import errno

    up = mk(client, {"h3d/a.h3d": BIG})

    def boom(fd, n):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "ftruncate", boom)
    r = put2(client, up["upload_id"], 0, 0, chunks_of(BIG)[0])
    assert r.status_code == 507 and code(r) == "INSUFFICIENT_STORAGE"
    assert not (hdir(up) / "h3d" / "a.h3d.part").exists()          # 만들다 만 .part 는 정리
    monkeypatch.undo()
    assert put2(client, up["upload_id"], 0, 0, chunks_of(BIG)[0]).status_code == 200


# ---------------------------------------------------------------- V-US-10 sha256_expected
def test_v_us_10_sha_mismatch_moves_to_backup_and_resets(client, upload_root):
    sp = [{"rel": "h3d/a.h3d", "size": len(BIG), "sha256": "a" * 64}]
    up = mk(client, {}, file_spec=sp)
    uid = up["upload_id"]
    parts = chunks_of(BIG)
    for k in (3, 0, 1, 2, 4):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    r = put2(client, uid, 0, 5, parts[5])
    assert r.status_code == 422 and code(r) == "SHA256_MISMATCH" and r.json()["detail"]["received"] == 0
    bk = Path(r.json()["detail"]["backup_path"])
    assert bk.is_file() and upload_root / "_backup" in bk.parents and bk.read_bytes() == BIG
    g = get(client, uid)["files"][0]
    assert g["chunks"] == [] and g["received"] == 0 and not g["done"]
    # 처음부터 다시(sha 가 기대와 다르므로 또 실패하지만 상태 머신은 정상)
    for k in range(5):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    assert code(put2(client, uid, 0, 5, parts[5])) == "SHA256_MISMATCH"


# ---------------------------------------------------------------- V-US-11 Windows 경로(os.pwrite 없음)
def test_v_us_11_no_pwrite_lseek_write_path(client, monkeypatch):
    monkeypatch.delattr(os, "pwrite")
    assert not hasattr(os, "pwrite")
    data = os.urandom(5 * CS + 3)
    up = mk(client, {"h3d/a.h3d": data})
    parts = chunks_of(data)
    res = []

    def go(k):
        res.append(put2(client, up["upload_id"], 0, k, parts[k]).status_code)

    ts = [threading.Thread(target=go, args=(k,)) for k in (5, 3, 1, 4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for k in (2, 0):
        res.append(put2(client, up["upload_id"], 0, k, parts[k]).status_code)
    assert res == [200] * 6, res
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data


def test_write_chunk_at_both_paths(tmp_path, monkeypatch):
    from esl_platform.core import uploads as U

    for use_pwrite in (True, False):
        if not use_pwrite:
            monkeypatch.delattr(os, "pwrite", raising=False)
        p = tmp_path / f"f{use_pwrite}.part"
        fd = U.open_part_for_write(str(p), 10, str(tmp_path))
        fd2 = U.open_part_for_write(str(p), 10, str(tmp_path))      # 요청별 fd 따로
        U.write_chunk_at(fd, 5, b"WORLD")
        U.write_chunk_at(fd2, 0, b"HELLO")
        os.close(fd)
        os.close(fd2)
        assert p.read_bytes() == b"HELLOWORLD"


# ---------------------------------------------------------------- V-US-24 메타·Case
SLIM_RAD_PART = 7        # mini_rad_text() 의 대상 파트(id 7, "Chassis rear")


def meta(**kw):
    m = {"kind": "h3d_slim", "v": 1, "source_name": "run.h3d", "source_bytes": 48_200_000_000,
         "slim_bytes": 19, "hvtrans_sec": 372.5, "part_id": SLIM_RAD_PART, "part_title": "Chassis rear",
         "results": [{"type": "Displacement"}, {"type": "Max_Strain", "layer": "Mid"}], "frames": "all",
         "tool_version": "0.6.0"}
    m.update(kw)
    return m


H3D_BYTES = b"HYPER3D 2026 slim 1234"        # 22 B


def mkmeta(client, m, rel="h3d/run_slim.h3d", name="m", data=H3D_BYTES, cancel=False):
    sp = [{"rel": "rad/m_0000.rad", "size": len(mini_rad_text())},
          {"rel": rel, "size": len(data), **({"meta": m} if m is not None else {})}]
    r = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": name, "files": sp}, headers=W)
    if cancel and r.status_code == 201:                      # 사용자당 OPEN 업로드 한도(2) 회피
        client.delete(f"{API}/uploads/{r.json()['upload_id']}", headers=W)
    return r


def test_v_us_24_meta_validation(client):
    m = meta(slim_bytes=len(H3D_BYTES))
    assert mkmeta(client, m, cancel=True).status_code == 201
    # .h3d 외 파일 meta → 422
    sp = [{"rel": "rad/m_0000.rad", "size": 5, "meta": {"kind": "h3d_original"}}]
    r = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "x", "files": sp}, headers=W)
    assert r.status_code == 422 and code(r) == "UPLOAD_META_INVALID"
    # 모르는 키 → 422
    assert mkmeta(client, {**m, "evil": 1}, name="y", cancel=True).status_code == 422
    # JSON 직렬화(UTF-8) 16 KB 초과 → 422 (cfg 8192자 한글 = 24 KB)
    r = mkmeta(client, {**m, "cfg": "가" * 8192}, name="z", cancel=True)
    assert r.status_code == 422 and code(r) == "UPLOAD_META_INVALID"
    assert mkmeta(client, {**m, "cfg": "x" * 8193}, name="z2", cancel=True).status_code == 422     # 필드 한도
    # slim_bytes ≠ size → 422
    r = mkmeta(client, meta(slim_bytes=999), name="z3", cancel=True)
    assert r.status_code == 422 and code(r) == "UPLOAD_META_INVALID"
    # kind 잘못·slim 에 part_id 없음
    assert mkmeta(client, {**m, "kind": "other"}, name="z4", cancel=True).status_code == 422
    m2 = dict(m)
    del m2["part_id"]
    assert code(mkmeta(client, m2, name="z5", cancel=True)) == "UPLOAD_META_INVALID"
    # original 은 kind 만으로 충분
    assert mkmeta(client, {"kind": "h3d_original"}, name="z6", cancel=True).status_code == 201


def _send_and_complete(client, up, rad, h3d):
    uid = up["upload_id"]
    assert put2(client, uid, 0, 0, rad, cs=up["chunk_size"]).status_code == 200
    assert put2(client, uid, 1, 0, h3d, cs=up["chunk_size"]).status_code == 200
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert c.status_code == 200, c.text
    return c.json()


def test_h3d_meta_in_complete_get_and_case_with_slim_mismatch(client, app_ctx):
    m = meta(slim_bytes=len(H3D_BYTES))
    up = mkmeta(client, m).json()
    assert up["files"][1]["meta"]["part_id"] == 7 and up["files"][0]["meta"] is None
    c = _send_and_complete(client, up, mini_rad_text(), H3D_BYTES)
    assert c["ok"] and c["h3d_meta"]["kind"] == "h3d_slim" and c["h3d_meta"]["hvtrans_sec"] == 372.5
    body = {"project_id": "p-1", "folder_name": "slim1", "title": "slim", "rad_path": c["rad_path"],
            "h3d_path": c["h3d_path"], "part_title": "Chassis rear"}
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["input_h3d_meta"]["kind"] == "h3d_slim" and case["input_h3d_meta"]["part_id"] == 7
    assert client.get(f"{API}/cases/{case['id']}", headers=R).json()["input_h3d_meta"]["source_name"] == "run.h3d"
    lst = client.get(f"{API}/cases", headers=R).json()
    assert [x["input_h3d_meta"]["kind"] for x in lst if x["id"] == case["id"]] == ["h3d_slim"]
    cj = Path(case["case_dir"]) / "case.json"
    assert '"h3d_mode": "slim"' in cj.read_text(encoding="utf-8")
    # UPLOAD_IN_USE: 이 업로드로 만든 Case 가 있으면 파일 빼기 거부
    r = client.delete(f"{API}/uploads/{up['upload_id']}/files/1", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_IN_USE"


def test_slim_part_mismatch_on_create_and_patch(client, tmp_path):
    from esl.rad import write_rad
    import numpy as np

    # 두 파트(7 "Chassis rear", 8 "Other") 가 있는 rad: 슬림 메타는 파트 8
    base = mini_rad_text().decode()
    extra = base.replace("Chassis rear", "Other part")
    rad = mini_rad_text()
    m = meta(slim_bytes=len(H3D_BYTES), part_id=8, part_title="Other part")
    up = mkmeta(client, m, name="mm").json()
    c = _send_and_complete(client, up, rad, H3D_BYTES)
    body = {"project_id": "p-1", "folder_name": "slimbad", "title": "slimbad", "rad_path": c["rad_path"],
            "h3d_path": c["h3d_path"], "part_title": "Chassis rear"}
    r = client.post(f"{API}/cases", json=body, headers=W)
    assert r.status_code == 422 and code(r) == "SLIM_PART_MISMATCH"
    assert "파트 8" in r.json()["detail"]["message"] and "원본 h3d" in r.json()["detail"]["message"]
    # 원본 모드 메타는 검사 없음
    up2 = mkmeta(client, {"kind": "h3d_original"}, name="orig", rel="h3d/run.h3d").json()
    c2 = _send_and_complete(client, up2, rad, H3D_BYTES)
    r = client.post(f"{API}/cases", json={**body, "folder_name": "orig1", "title": "orig", "rad_path": c2["rad_path"],
                                          "h3d_path": c2["h3d_path"]}, headers=W)
    assert r.status_code == 201 and r.json()["input_h3d_meta"]["kind"] == "h3d_original"


def test_slim_part_mismatch_on_patch_part_title(client):
    rad = mini_rad_text()
    m = meta(slim_bytes=len(H3D_BYTES), part_id=7)
    up = mkmeta(client, m, name="pp").json()
    c = _send_and_complete(client, up, rad, H3D_BYTES)
    body = {"project_id": "p-1", "folder_name": "slimpatch", "title": "slimpatch", "rad_path": c["rad_path"],
            "h3d_path": c["h3d_path"], "part_title": "Chassis rear"}
    case = client.post(f"{API}/cases", json=body, headers=W).json()
    # 메타와 같은 파트 title(정규화 동치)은 허용
    r = client.patch(f"{API}/cases/{case['id']}", json={"version": case["version"], "part_title": "chassis  REAR"}, headers=W)
    assert r.status_code == 200, r.text


def test_worker_failure_hint_for_slim():
    from esl_worker import h3d

    ok, msg, lines, _ = h3d.evaluate(1, "/nonexistent", slim=True)
    assert not ok and "압축 모드 h3d" in msg and "원본" in msg
    ok, msg, lines, _ = h3d.evaluate(1, "/nonexistent")
    assert not ok and "압축 모드" not in msg


# ---------------------------------------------------------------- V-US-32 파일 빼기
def test_v_us_32_remove_file_open_session(client, upload_root):
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/a.h3d": BIG}
    up = mk(client, files)
    uid = up["upload_id"]
    put2(client, uid, 0, 0, files["rad/m_0000.rad"])
    parts = chunks_of(BIG)
    for k in (0, 1):
        put2(client, uid, 1, k, parts[k])
    r = client.delete(f"{API}/uploads/{uid}/files/1", headers=W)
    assert r.status_code == 200, r.text
    j = r.json()
    f = j["files"][1]
    assert f["removed"] is True and f["index"] == 1 and f["received"] == 0 and f["chunks"] == []
    assert j["total_bytes"] == len(files["rad/m_0000.rad"]) and j["state"] == "OPEN" and j["result"] is None
    bk = list((upload_root / "_backup" / "power").glob("*h3d_a.h3d.removed*"))
    assert bk and bk[0].stat().st_size == len(BIG)             # 사전 할당 .part 가 그대로 이동(삭제 없음)
    assert not (hdir(up) / "h3d" / "a.h3d.part").exists()
    # 멱등
    assert client.delete(f"{API}/uploads/{uid}/files/1", headers=W).json()["files"][1]["removed"] is True
    # 그 파일 PUT → 409 UPLOAD_FILE_REMOVED
    r = put2(client, uid, 1, 2, parts[2])
    assert r.status_code == 409 and code(r) == "UPLOAD_FILE_REMOVED"
    # complete 는 제거된 파일을 검사하지 않음(여기선 rad 만 → h3d/결과 없음 문제)
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert not c["ok"] and any("h3d 파일 또는 추출 결과" in p for p in c["problems"])
    # 같은 이름으로 다시 추가 가능, index 는 뒤에 붙음, 새 항목은 프로토콜 2
    r = client.post(f"{API}/uploads/{uid}/files", headers=W, json={"files": [{"rel": "h3d/a.h3d", "size": len(BIG)}]})
    assert r.status_code == 200, r.text
    assert r.json()["files"][2]["rel"] == "h3d/a.h3d" and r.json()["files"][2]["n_chunks"] == 6
    for k in range(6):
        assert put2(client, uid, 2, k, parts[k]).status_code == 200
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert c["ok"]
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == BIG
    # 범위 밖 index
    assert client.delete(f"{API}/uploads/{uid}/files/9", headers=W).status_code == 404


def test_remove_file_busy_when_chunk_in_flight(client):
    from esl_platform.api.services import uploads as svc

    up = mk(client, {"h3d/a.h3d": BIG})
    uid = up["upload_id"]
    with svc._GUARD:
        svc._INFLIGHT[uid] = {(0, 2)}
    try:
        r = client.delete(f"{API}/uploads/{uid}/files/0", headers=W)
        assert r.status_code == 409 and code(r) == "UPLOAD_FILE_BUSY"
    finally:
        svc.reset_state()
    assert client.delete(f"{API}/uploads/{uid}/files/0", headers=W).status_code == 200


def test_remove_file_after_completed_reopens_when_no_case(client):
    rad = mini_rad_text()
    up = mkmeta(client, None, rel="h3d/run.h3d", name="rc").json()
    c = _send_and_complete(client, up, rad, H3D_BYTES)
    assert c["ok"]
    uid = up["upload_id"]
    r = client.delete(f"{API}/uploads/{uid}/files/1", headers=W)
    assert r.status_code == 200 and r.json()["state"] == "OPEN" and r.json()["result"] is None
    assert r.json()["completed_at"] is None
    # 삭제 후 취소 불가였던 COMPLETED 가 아니므로 이제 전체 취소도 가능
    assert client.delete(f"{API}/uploads/{uid}", headers=W).json()["state"] == "CANCELED"
    # CANCELED 에서 빼기 → 409 UPLOAD_CLOSED (이미 removed 면 멱등 200)
    up2 = mk(client, {"h3d/a.h3d": b"HYPER3D"}, name="rc2")
    client.delete(f"{API}/uploads/{up2['upload_id']}", headers=W)
    r = client.delete(f"{API}/uploads/{up2['upload_id']}/files/0", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_CLOSED"


# ---------------------------------------------------------------- 이슈 #29 UPLOAD_LIMIT 상세
def test_issue29_upload_limit_lists_open_sessions(client):
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/r.h3d": b"NOTH3D"}        # complete 가 문제로 실패하는 세션
    u1 = mk(client, files, name="첫째")
    for i, (rel, data) in enumerate(files.items()):
        put2(client, u1["upload_id"], i, 0, data, cs=u1["chunk_size"])
    c = client.post(f"{API}/uploads/{u1['upload_id']}/complete", headers=W).json()
    assert not c["ok"] and c["problems"]
    u2 = mk(client, {"h3d/a.h3d": BIG}, name="둘째")
    put2(client, u2["upload_id"], 0, 0, chunks_of(BIG)[0])
    r = create(client, {"h3d/c.h3d": b"HYPER3D"}, name="셋째")
    assert r.status_code == 429 and code(r) == "UPLOAD_LIMIT"
    d = r.json()["detail"]
    assert d["message"] == ("진행 중인 업로드 세션이 2개입니다(사용자당 최대 2개, 계산 대기열과 별개) — "
                            "새 Case 화면의 '진행 중인 업로드'에서 이어서 하거나 취소하세요")
    by = {o["name"]: o for o in d["open_uploads"]}
    assert set(by) == {"첫째", "둘째"} and set(by["첫째"]) == {"id", "name", "created_at", "received_bytes",
                                                           "total_bytes", "problems_count"}
    assert by["첫째"]["id"] == u1["upload_id"] and by["첫째"]["problems_count"] >= 1
    assert by["둘째"]["received_bytes"] == CS and by["둘째"]["total_bytes"] == len(BIG) and by["둘째"]["problems_count"] == 0
    # GET /uploads?state=OPEN 에도 complete 실패로 남은 세션이 문제 수와 함께 나온다
    lst = {o["name"]: o for o in client.get(f"{API}/uploads", params={"state": "OPEN"}, headers=R).json()}
    assert lst["첫째"]["problems_count"] == by["첫째"]["problems_count"] and lst["첫째"]["state"] == "OPEN"
    assert lst["첫째"]["result"]["ok"] is False
    # 취소하면 한도가 풀린다
    client.delete(f"{API}/uploads/{u2['upload_id']}", headers=W)
    assert create(client, {"h3d/c.h3d": b"HYPER3D"}, name="셋째").status_code == 201


def test_default_limit_and_stale_unchanged():
    from esl_platform.core.config import UploadCfg

    u = UploadCfg()
    assert u.max_concurrent_per_user == 2 and u.stale_hours == 72


def test_openapi_has_new_fields(client):
    spec = client.get(f"{API}/openapi.json").json()
    out = spec["components"]["schemas"]["UploadOut"]["properties"]
    assert {"protocol", "chunk_size", "max_parallel", "problems_count", "client"} <= set(out)
    fo = spec["components"]["schemas"]["UploadFileOut"]["properties"]
    assert {"received_total", "chunks", "n_chunks", "removed", "meta"} <= set(fo)
    assert "input_h3d_meta" in spec["components"]["schemas"]["CaseOut"]["properties"]
    assert "delete" in spec["paths"][f"{API}/uploads/{{upload_id}}/files/{{index}}"]


# ---------------------------------------------------------------- v0.6.0 정합: 업로드를 시작한 클라이언트(PC 도구/브라우저 구분)
def test_upload_out_reports_client_and_inherits_on_add(client):
    body = {"project_id": "p-1", "name": "pc", "files": spec({"rad/m_0000.rad": mini_rad_text()}),
            "client": {"name": "esl-pc", "version": "0.6.0"}}
    r = client.post(f"{API}/uploads", json=body, headers=W)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["client"] == {"name": "esl-pc", "version": "0.6.0"}
    r = client.post(f"{API}/uploads/{up['upload_id']}/files", json={"files": spec({"h3d/a.h3d": BIG[:CS]})}, headers=W)
    assert r.status_code == 200, r.text
    assert r.json()["client"]["name"] == "esl-pc"
    assert all("client" not in f for f in r.json()["files"])          # 파일 항목에는 노출하지 않음
    listed = client.get(f"{API}/uploads", params={"state": "OPEN"}, headers=R).json()
    assert [u["client"]["name"] for u in listed if u["upload_id"] == up["upload_id"]] == ["esl-pc"]
    # client 없이 만든 세션(구 클라이언트) → null
    plain = mk(client, {"rad/m_0000.rad": mini_rad_text()}, name="web")
    assert plain["client"] is None
