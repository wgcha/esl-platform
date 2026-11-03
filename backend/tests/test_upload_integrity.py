"""v0.12.5 업로드 무결성(이슈 #50): 프로토콜 2 청크가 0 으로 남은 채 done 되던 결함의 재현·수정·방어 시험.

근본 원인: `.part` 를 처음 만든 요청이 사전 할당(os.ftruncate)하는 동안 다른 청크 요청이 같은 파일을 열어 먼저 썼다.
Windows 의 os.ftruncate(UCRT _chsize_s)는 늘리는 구간을 0 으로 **써서** 채우므로, 늦게 지나가는 0 채우기가 이미 쓴
청크(4병렬이면 4번째 청크 앞부분)를 덮어썼다. 리눅스 ftruncate 는 메타데이터만 바꾸므로 시험은 _chsize_s 를 흉내 낸다.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
import time
from pathlib import Path

import pytest
from esl_test_support import API, H
from test_upload_speed import CS, chunks_of, code, get, hdir, mk, put2, settings_dict, upload_root  # noqa: F401 (fixture)

W = H("tok-power", True)
ZEROS = bytes(64 * 1024)


class WinChsize:
    """UCRT _chsize_s 흉내: 늘릴 때 현재 끝부터 자기 fd 로 0 을 순차 write. pause_at 에 이르면 멈추고 go 를 기다린다."""

    def __init__(self, pause_at: int | None) -> None:
        self.pause_at = pause_at
        self.reached = threading.Event()
        self.go = threading.Event()
        self.calls = 0

    def __call__(self, fd: int, length: int) -> None:
        self.calls += 1
        end = os.fstat(fd).st_size
        if length <= end:                              # 줄이기는 이 시험에서 쓰지 않음
            return
        os.lseek(fd, end, os.SEEK_SET)
        pos = end
        while pos < length:
            if self.pause_at is not None and pos >= self.pause_at and not self.reached.is_set():
                self.reached.set()
                self.go.wait(10)
            n = os.write(fd, ZEROS[:min(len(ZEROS), length - pos)])
            pos += n


def nospec(files: dict[str, bytes]) -> list[dict]:
    """브라우저처럼 파일 전체 sha256 없이."""
    return [{"rel": r, "size": len(b)} for r, b in files.items()]


def mk_nosha(client, files, name="u"):
    return mk(client, files, name=name, file_spec=nospec(files))


def raw_files(ctx, uid):
    from esl_platform.api.services import uploads as svc

    with ctx.engine.connect() as c:
        return svc._row(c, uid)["files"]


# ---------------------------------------------------------------- 근본 원인 재현(수정 전 실패 · 수정 후 통과)
def test_issue50_prealloc_zero_fill_race_does_not_zero_a_written_chunk(client, monkeypatch):
    """청크 0 요청이 .part 를 만들어 사전 할당하는 중(0 채우기가 3·C 에 이름)에 청크 3 요청이 같은 파일을 연다.
    수정 전: 청크 3 이 먼저 쓰이고 표시된 뒤 0 채우기가 덮어써 3·C 부터 0 인 채로 done(sha256 은 디스크 기준이라 통과).
    수정 후: 만들기·사전 할당이 끝날 때까지 다른 요청은 열기를 기다린다 → 파일 정확."""
    data = os.urandom(6 * CS)
    files = {"h3d/a.h3d": data}
    up = mk_nosha(client, files)
    uid = up["upload_id"]
    parts = chunks_of(data)
    ch = WinChsize(pause_at=3 * CS)
    monkeypatch.setattr(os, "ftruncate", ch)
    res: dict[int, object] = {}

    def go(k):
        res[k] = put2(client, uid, 0, k, parts[k])

    a = threading.Thread(target=go, args=(0,))
    a.start()
    assert ch.reached.wait(10), "사전 할당이 시작되지 않음"
    b = threading.Thread(target=go, args=(3,))
    b.start()
    b.join(1.0)                                       # 수정 전: 여기서 이미 청크 3 이 쓰이고 표시됨
    ch.go.set()
    a.join(20)
    b.join(20)
    monkeypatch.undo()
    assert res[0].status_code == 200 and res[3].status_code == 200, (res[0].text, res[3].text)
    for k in (1, 2, 4, 5):
        r = put2(client, uid, 0, k, parts[k])
        assert r.status_code == 200, r.text
    g = get(client, uid)["files"][0]
    assert g["done"], g
    out = (hdir(up) / "h3d" / "a.h3d").read_bytes()
    assert out[3 * CS:3 * CS + 64] != bytes(64), "청크 3 앞부분이 0 — 사전 할당 0 채우기가 덮어씀"
    assert out == data and g["sha256"] == hashlib.sha256(data).hexdigest()
    assert ch.calls == 1


@pytest.mark.noprealloc
def test_default_no_preallocate_parallel_puts_not_blocked_and_lock_table_drained(client, monkeypatch):
    """기본 upload.preallocate=false: ftruncate 를 부르지 않음 → 사전 할당 0 채우기로 다른 PUT 이 기다리지 않는다.
    열기 잠금 항목은 열기가 끝나면 사전에서 빠진다."""
    from esl_platform.core import uploads as U
    from esl_platform.core.config import UploadCfg

    assert UploadCfg().preallocate is False
    ch = WinChsize(pause_at=0)                         # 불리면 멈춤(go 안 줌) → 부르면 시험이 실패
    monkeypatch.setattr(os, "ftruncate", ch)
    data = os.urandom(5 * CS + 3)
    up = mk_nosha(client, {"h3d/a.h3d": data})
    parts = chunks_of(data)
    res: list = []
    ts = [threading.Thread(target=lambda k=k: res.append(put2(client, up["upload_id"], 0, k, parts[k])))
          for k in (3, 0, 5, 1)]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    for k in (2, 4):
        res.append(put2(client, up["upload_id"], 0, k, parts[k]))
    assert [r.status_code for r in res] == [200] * 6 and ch.calls == 0
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data
    assert U._CREATE_LOCKS == {}


# ---------------------------------------------------------------- 방어: 잠금이 없어도(다른 경로의 손상) 완료 재해시가 잡는다
def test_finalize_rehash_catches_zeroed_chunk_and_requests_only_it(client, app_ctx, monkeypatch):
    """원인 수정(만들기 잠금)을 끈 채 같은 경합 → 마지막 청크 응답이 422 UPLOAD_CHUNK_CORRUPT{chunks:[3]}, 받은 범위에서
    청크 3 만 빠짐 → 청크 3 만 다시 보내면 정확히 done."""
    from esl_platform.core import uploads as U

    monkeypatch.setattr(U, "_create_lock", lambda path: contextlib.nullcontext())
    data = os.urandom(6 * CS)
    up = mk_nosha(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    ch = WinChsize(pause_at=3 * CS)
    monkeypatch.setattr(os, "ftruncate", ch)
    res: dict[int, object] = {}

    def go(k):
        res[k] = put2(client, uid, 0, k, parts[k])

    a = threading.Thread(target=go, args=(0,))
    a.start()
    assert ch.reached.wait(10)
    go(3)                                              # 잠금이 없으니 바로 쓰고 표시
    assert res[3].status_code == 200
    ch.go.set()
    a.join(20)
    monkeypatch.setattr(os, "ftruncate", ch.__class__(None))
    for k in (1, 2, 4):
        assert put2(client, uid, 0, k, parts[k]).status_code == 200
    r = put2(client, uid, 0, 5, parts[5])
    assert r.status_code == 422 and code(r) == "UPLOAD_CHUNK_CORRUPT", r.text
    d = r.json()["detail"]
    assert d["chunks"] == [3] and d["rel"] == "h3d/a.h3d" and d["received"] == 3 * CS
    g = get(client, uid)["files"][0]
    assert not g["done"] and g["chunks"] == [[0, 3], [4, 6]]
    r = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_INCOMPLETE"
    assert r.json()["detail"]["pending"][0]["missing"] == [[3, 4]]
    r = put2(client, uid, 0, 3, parts[3])
    assert r.status_code == 200 and r.json()["done"], r.text
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data
    f = raw_files(app_ctx, uid)[0]
    assert f["sha256"] == hashlib.sha256(data).hexdigest()
    assert f["chunks_sha256"] == hashlib.sha256("".join(hashlib.sha256(p).hexdigest() for p in parts).encode()).hexdigest()


def _corrupt_on_disk(part: Path, k: int) -> None:
    with open(part, "r+b") as fh:
        fh.seek(k * CS)
        fh.write(bytes(4096))


def test_chunk_mismatch_three_times_is_upload_corrupt(client, app_ctx):
    """디스크 내용이 계속 어긋나면(같은 청크 3회) 422 UPLOAD_CORRUPT — 그 뒤 그 청크 PUT 도 UPLOAD_CORRUPT."""
    from esl_platform.api.services import uploads as svc

    data = os.urandom(3 * CS)
    up = mk_nosha(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    part = hdir(up) / "h3d" / "a.h3d.part"
    orig = svc._finalize_file

    def corrupt_then_finalize(ctx, upload_id, index):
        _corrupt_on_disk(part, 1)
        return orig(ctx, upload_id, index)

    svc._finalize_file = corrupt_then_finalize
    try:
        for k in (0, 1):
            assert put2(client, uid, 0, k, parts[k]).status_code == 200
        r = put2(client, uid, 0, 2, parts[2])
        assert code(r) == "UPLOAD_CHUNK_CORRUPT" and r.json()["detail"]["attempt"] == 1
        r = put2(client, uid, 0, 1, parts[1])
        assert code(r) == "UPLOAD_CHUNK_CORRUPT" and r.json()["detail"]["attempt"] == 2
        r = put2(client, uid, 0, 1, parts[1])
        assert r.status_code == 422 and code(r) == "UPLOAD_CORRUPT", r.text
        assert r.json()["detail"]["chunk"] == 1 and r.json()["detail"]["rel"] == "h3d/a.h3d"
    finally:
        svc._finalize_file = orig
    r = put2(client, uid, 0, 1, parts[1])
    assert r.status_code == 422 and code(r) == "UPLOAD_CORRUPT"
    assert not get(client, uid)["files"][0]["done"]


def test_readback_after_write_mismatch_is_not_marked(client, monkeypatch):
    """쓴 직후 디스크에서 다시 읽은 청크 해시가 받은 본문과 다르면 표시하지 않고 422 CHUNK_VERIFY_FAILED(같은 청크 재전송)."""
    from esl_platform.core import uploads as U

    data = os.urandom(2 * CS)
    up = mk_nosha(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    real = U.write_chunk_at
    state = {"n": 0}

    def flaky(fd, pos, buf):
        state["n"] += 1
        if state["n"] == 1:                       # 첫 쓰기 하나를 0 으로(디스크·드라이버 손상 흉내)
            buf = bytes(len(buf))
        return real(fd, pos, buf)

    monkeypatch.setattr(U, "write_chunk_at", flaky)
    r = put2(client, uid, 0, 0, parts[0])
    assert r.status_code == 422 and code(r) == "CHUNK_VERIFY_FAILED", r.text
    assert get(client, uid)["files"][0]["chunks"] == []
    assert put2(client, uid, 0, 0, parts[0]).status_code == 200
    assert put2(client, uid, 0, 1, parts[1]).json()["done"]
    assert (hdir(up) / "h3d" / "a.h3d").read_bytes() == data


def test_complete_refuses_done_file_without_full_got(client, app_ctx):
    """done 이어도 got 이 [0, n) 전체가 아니면 complete 는 누락으로 거부(기록 불일치 방어)."""
    from sqlalchemy import update

    from esl_platform.api.services import uploads as svc
    from esl_platform.core.db.tables import uploads
    from test_p3_ux import mini_rad_text

    rad = mini_rad_text()
    blob = b"HYPER3D" + os.urandom(2 * CS)
    files = {"rad/m_0000.rad": rad, "h3d/a.h3d": blob}
    up = mk_nosha(client, files)
    uid = up["upload_id"]
    assert put2(client, uid, 0, 0, rad).status_code == 200
    for k, p in enumerate(chunks_of(blob)):
        assert put2(client, uid, 1, k, p).status_code == 200
    with app_ctx.engine.begin() as c:
        fs = [dict(x) for x in svc._row(c, uid)["files"]]
        fs[1]["got"] = [[0, 1], [2, 3]]
        c.execute(update(uploads).where(uploads.c.id == uid).values(files=fs))
    r = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert r.status_code == 409 and code(r) == "UPLOAD_INCOMPLETE"
    assert r.json()["detail"]["pending"][0]["missing"] == [[1, 2]]


def test_old_session_chunks_without_hash_still_finalize(client, app_ctx):
    """업그레이드 전에 받은 청크(청크 해시 기록 없음)는 대조할 것이 없어 건너뛰고, 나머지는 대조해 마무리(하위 호환)."""
    from sqlalchemy import update

    from esl_platform.api.services import uploads as svc
    from esl_platform.core.db.tables import uploads

    data = os.urandom(3 * CS)
    up = mk_nosha(client, {"h3d/a.h3d": data})
    uid = up["upload_id"]
    parts = chunks_of(data)
    assert put2(client, uid, 0, 0, parts[0]).status_code == 200
    with app_ctx.engine.begin() as c:
        fs = [dict(x) for x in svc._row(c, uid)["files"]]
        fs[0].pop("csha", None)
        c.execute(update(uploads).where(uploads.c.id == uid).values(files=fs))
    assert put2(client, uid, 0, 2, parts[2]).status_code == 200
    r = put2(client, uid, 0, 1, parts[1], sha=False)             # 헤더 없는 클라이언트(비보안 http 브라우저)
    assert r.status_code == 200 and r.json()["done"]
    f = raw_files(app_ctx, uid)[0]
    assert f["sha256"] == hashlib.sha256(data).hexdigest() and f.get("chunks_sha256") is None


# ---------------------------------------------------------------- 대용량 합성(희소 파일 500 MB+)
@pytest.mark.chunk64
def test_large_sparse_upload_with_four_parallel_and_prealloc_race(client, monkeypatch):
    """561,333,509 B(이슈 #50 크기), 64 MiB 청크·4병렬. 청크 3 머리에 표지를 둔 희소 내용 — 시작 4청크를 동시에 보내며
    _chsize_s 흉내 사전 할당을 끼워 넣는다. 결과 파일의 청크 경계 표지·전체 sha256 이 맞아야 한다."""
    size = 561_333_509
    c = 64 * CS
    n = (size + c - 1) // c

    def chunk_bytes(k: int) -> bytes:
        ln = min(c, size - k * c)
        b = bytearray(ln)
        tag = f"#chunk {k} head\n".encode()
        b[:len(tag)] = tag
        b[-len(tag):] = tag
        return bytes(b)

    up = mk(client, {}, name="big", file_spec=[{"rel": "rad/run_0001.sta", "size": size}])
    uid = up["upload_id"]
    assert up["chunk_size"] == c and up["files"][0]["n_chunks"] == n == 9
    ch = WinChsize(pause_at=3 * c)
    monkeypatch.setattr(os, "ftruncate", ch)
    res: dict[int, object] = {}

    def go(k):
        res[k] = put2(client, uid, 0, k, chunk_bytes(k), cs=c)

    ts = [threading.Thread(target=go, args=(k,)) for k in range(4)]
    ts[0].start()
    assert ch.reached.wait(30)
    for t in ts[1:]:
        t.start()
    time.sleep(1.0)
    ch.go.set()
    [t.join(120) for t in ts]
    monkeypatch.undo()
    assert all(res[k].status_code == 200 for k in range(4)), {k: res[k].text[:120] for k in res}
    for k in range(4, n):
        r = put2(client, uid, 0, k, chunk_bytes(k), cs=c)
        assert r.status_code == 200, r.text
    assert r.json()["done"]
    p = hdir(up) / "rad" / "run_0001.sta"
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for k in range(n):
            b = fh.read(c)
            assert b == chunk_bytes(k), f"청크 {k} 내용 불일치"
            h.update(b)
    assert get(client, uid)["files"][0]["sha256"] == h.hexdigest()


# ---------------------------------------------------------------- 기존 손상 탐지(읽기 전용)
def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def test_upload_holes_detects_head_and_full_zero_chunks_read_only(tmp_path):
    import json

    from esl_platform import upload_holes as UH

    root = tmp_path / "esl-input"
    d = root / "user" / "20261102-000000_x" / "rad"
    d.mkdir(parents=True)
    good = b"#RADIOSS STATE FILE\n" + b"x" * (3 * CS)
    (d / "good.sta").write_bytes(good)
    head = bytearray(b"y" * (4 * CS + 10))
    head[3 * CS:3 * CS + CS // 2] = bytes(CS // 2)                 # 이슈 #50 모양: 청크 3 앞부분 0
    (d / "head.sta").write_bytes(bytes(head))
    full = bytearray(b"z" * (3 * CS))
    full[CS:2 * CS] = bytes(CS)
    (d / "full.inc").write_bytes(bytes(full))
    small = bytearray(b"w" * (2 * CS))
    small[CS:CS + 1000] = bytes(1000)                              # 기준(64 KiB) 미만 — 보고 안 함
    (d / "small.inc").write_bytes(bytes(small))
    (d / "recv.sta.part").write_bytes(bytes(2 * CS))               # 받는 중(.part) — 기본 제외
    bk = root / "_backup" / "user"
    bk.mkdir(parents=True)
    (bk / "old.sta").write_bytes(bytes(CS))                        # _backup — 기본 제외
    (d / "link.sta").symlink_to(d / "head.sta")                    # 링크 — 따라가지 않음
    before = _snapshot(root)
    lines: list[str] = []
    rc = UH.main(["--root", str(root), "--chunk-mb", "1", "--no-db"], out=lines.append)
    assert rc == 1
    txt = "\n".join(lines)
    assert "head.sta" in txt and "청크 3 @ 3,145,728: 0 이 524,288 B" in txt and "청크 앞부분" in txt
    assert "full.inc" in txt and "청크 1 @ 1,048,576" in txt and "청크 전체" in txt
    assert "good.sta" not in txt and "small.inc" not in txt and "recv.sta.part" not in txt
    assert "old.sta" not in txt and "link.sta" not in txt and "의심 2개" in txt
    reps = UH.run(str(root), CS, min_zero=64 * 1024, records=None, include_backup=True, include_part=True)
    names = {Path(r.path).name: r for r in reps if r.suspect}
    assert set(names) == {"head.sta", "full.inc", "recv.sta.part", "old.sta"}
    assert [(h.chunk, h.kind) for h in names["recv.sta.part"].holes] == [(0, "full"), (1, "full")]
    lines.clear()
    assert UH.main(["--root", str(root / "user"), "--chunk-mb", "1", "--no-db", "--json"], out=lines.append) == 1
    j = json.loads(lines[-1])
    assert j["chunk_bytes"] == CS and len(j["suspects"]) == 2
    assert _snapshot(root) == before                               # 쓰기·삭제 없음
    clean = tmp_path / "clean"
    (clean / "u").mkdir(parents=True)
    (clean / "u" / "a.rad").write_bytes(b"/BEGIN\n")
    assert UH.main(["--root", str(clean), "--no-db"], out=lines.append) == 0
    assert UH.main(["--root", str(tmp_path / "nope"), "--no-db"], out=lines.append) == 2


def test_upload_holes_compares_db_sha256(client, app_ctx, upload_root):
    """DB 기록 sha256 대조: 완료 뒤 디스크에서 바뀐 파일은 sha256 불일치로 보고(0 구간이 없어도)."""
    from esl_platform import upload_holes as UH

    data = os.urandom(2 * CS + 5)
    up = mk_nosha(client, {"rad/run_0001.sta": data})
    uid = up["upload_id"]
    for k, p in enumerate(chunks_of(data)):
        assert put2(client, uid, 0, k, p).status_code == 200
    target = hdir(up) / "rad" / "run_0001.sta"
    url = app_ctx.engine.url.render_as_string(hide_password=False)
    rec = UH.db_records(url)
    assert rec[UH._key(str(target))]["sha256"] == hashlib.sha256(data).hexdigest()
    reps = UH.run(str(upload_root), CS, min_zero=64 * 1024, records=rec)
    r = next(x for x in reps if x.path == str(target))
    assert r.sha256_ok is True and not r.suspect and r.upload_id == uid
    with open(target, "r+b") as fh:                                # 완료 뒤 변조(한 바이트)
        fh.seek(CS + 7)
        fh.write(b"\x01" if data[CS + 7] != 1 else b"\x02")
    reps = UH.run(str(upload_root), CS, min_zero=64 * 1024, records=rec)
    r = next(x for x in reps if x.path == str(target))
    assert r.sha256_ok is False and r.suspect and not r.holes
    assert "sha256 불일치" in UH.format_report(reps, str(upload_root), CS)
    reps = UH.run(str(upload_root), CS, min_zero=64 * 1024, records=rec, check_sha=False)
    assert next(x for x in reps if x.path == str(target)).sha256_ok is None
