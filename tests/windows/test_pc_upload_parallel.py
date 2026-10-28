"""PC 업로드 클라이언트의 병렬 전송(업로드 프로토콜 2) 실제 실행 시험 — 계약 esl_upload_speed.md §5.5·§8 V-US-8·V-US-13.

pwsh(Linux 도 가능)로 esl_upload_lib.ps1 을 dot-source 하고, tests/windows/esl_fake_upload_server.py(protocol=2)를 상대로 실행한다:
동시 전송(max_inflight_seen)·응답 순서 뒤섞임·중복(duplicate)·429/409 CHUNK_IN_FLIGHT/5xx/sha 불일치/연결 끊김/파일 sha 불일치 재시도,
중단 후 다시 실행하면 서버가 받은 청크만 보냄, 구 서버(protocol 없음)는 순차, ServicePointManager 연결 수 상향.
"""
import hashlib
import os
import random

import pytest

import pc_support as ps
from pc_support import fake, kv, make_case, run_ps

pytestmark = pytest.mark.skipif(ps.PWSH is None, reason="pwsh 없음")


@pytest.fixture()
def server2():
    srv, state, url = fake.start(protocol=2)
    state.chunk_size = 64 * 1024
    yield state, url
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def server1():
    srv, state, url = fake.start(protocol=1)
    yield state, url
    srv.shutdown()
    srv.server_close()


UPLOAD = """
$ctx = New-EslContext '{url}' $null {par}
"limit=" + [Net.ServicePointManager]::DefaultConnectionLimit
$plan = Get-EslUploadPlan '{res}' '{rad}'
try {{
    $r = Invoke-EslPcUpload $ctx $plan 'drop' (Get-EslUploadKey '{anchor}')
    "ok=" + $r.Ok
    "upload_id=" + $r.UploadId
}}
catch {{ "error=" + $_.Exception.Message }}
"""


def _setup(tmp_path, state, big=1_500_000):
    state.codes["123456"] = "p1"
    res, rad = make_case(tmp_path, big=big)
    anchor = tmp_path / "drop.h3d"
    anchor.write_bytes(b"HYPER3D" + b"0" * 64)
    return res, rad, anchor


def _check_files(state, uid, res, rad):
    for f in state.uploads[uid]["files"]:
        rel = f["rel"]
        local = res / rel[len("results/csv/"):] if rel.startswith("results/csv/") else rad.parent / rel[len("rad/"):]
        assert f["done"], rel
        assert bytes(f["data"]) == local.read_bytes(), rel
        assert f["sha256"] == hashlib.sha256(local.read_bytes()).hexdigest(), rel


def _go(tmp_path, url, res, rad, anchor, par=4, inputs=("123456",)):
    return run_ps(tmp_path, UPLOAD.format(url=url, res=res, rad=rad, anchor=anchor, par=par), inputs=list(inputs))


def test_parallel_out_of_order_responses(tmp_path, server2):
    """동시 4개로 보내고 서버가 청크마다 다른 시간에 응답(= 완료 순서 뒤섞임) -> 파일 바이트·sha 일치, 중복 전송 없음."""
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state)
    rnd = random.Random(7)
    delays = {}
    state.put_delay = lambda index, k: delays.setdefault((index, k), rnd.choice([0.02, 0.25, 0.1, 0.4]))
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    _check_files(state, out["upload_id"], res, rad)
    assert int(out["limit"]) >= 4 * 2 + 2                       # ServicePointManager.DefaultConnectionLimit 상향
    assert 2 <= state.max_inflight_seen <= 4, state.max_inflight_seen   # 실제로 겹쳐 보냄, 상한 N 이하
    c = state.chunk_size
    total = sum((f["size"] + c - 1) // c for f in state.uploads[out["upload_id"]]["files"])
    assert len(state.put_order) == total                        # 오류가 없으면 청크마다 정확히 한 번
    big = [k for i, k in state.put_order if state.uploads[out["upload_id"]]["files"][i]["size"] > 1_000_000]
    assert len(big) == len(set(big))
    assert all(abs(k - j) <= 6 for j, k in enumerate(big)), big   # 번호 순서로 내보냄(동시 창 안에서만 뒤섞임)
    assert "×" in r.stdout and "병렬" in r.stdout and "남은 시간" in r.stdout    # 진행 줄에 동시 전송 수
    assert state.uploads[out["upload_id"]]["state"] == "COMPLETED"
    # POST /uploads 에 client 정보
    assert state.posts[0]["client"]["name"] == "esl-pc"


def test_parallel_with_every_fault(tmp_path, server2):
    """409 CHUNK_IN_FLIGHT·429·503·청크 sha 불일치·연결 끊김(쓴 뒤 응답 없음 -> 재전송은 duplicate)·파일 sha 불일치(처음부터)."""
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state, big=900_000)
    state.conflict_puts = {3}
    state.ratelimit_puts = {5}
    state.fail_status = {7: 503}
    state.corrupt_puts = {9}
    state.drop_after_write = {11}
    state.put_delay = lambda index, k: 0.03
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    _check_files(state, out["upload_id"], res, rad)
    so = r.stdout
    assert "CHUNK_IN_FLIGHT" in so and "429" in so and "서버 응답 503" in so
    assert "청크 sha256 불일치" in so and "네트워크 오류" in so
    # 끊김 뒤 재전송이 duplicate 로 받아들여졌는지: 같은 청크가 두 번 도착한 것이 있다
    assert len(state.put_order) > len(set(state.put_order))


def test_file_sha_mismatch_restarts_file_once(tmp_path, server2):
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state, big=400_000)
    state.codes["123456"] = "p1"
    idx = None
    # elem_hist.csv 의 index 는 plan 순서(done.json, elem_hist.csv, ...)를 따른다: 이름으로 찾기 위해 먼저 계획을 본다
    state.file_sha_fail_once = {1}
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    assert "처음부터 다시 올립니다" in r.stdout
    _check_files(state, out["upload_id"], res, rad)
    assert idx is None


def test_resume_sends_only_missing_chunks(tmp_path, server2):
    """도중에 서버가 계속 503 -> 클라이언트 포기(받은 청크는 서버에 남음). 다시 실행하면 서버 chunks 의 빠진 청크만 보낸다."""
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state)
    state.fail_puts_from = 12
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert "error" in out and "다시 실행하면 이어 올립니다" in out["error"], (r.stdout, r.stderr)
    (uid,) = state.uploads
    c = state.chunk_size
    files = state.uploads[uid]["files"]
    got_before = sum(len(f["got"]) for f in files if not f["done"]) + sum(
        (f["size"] + c - 1) // c for f in files if f["done"])
    total = sum((f["size"] + c - 1) // c for f in files)
    assert 0 < got_before < total
    state.fail_puts_from = None
    n_before = len(state.put_order)
    r2 = _go(tmp_path, url, res, rad, anchor, inputs=())
    out2 = kv(r2)
    assert out2.get("ok") == "True" and out2["upload_id"] == uid, (r2.stdout, r2.stderr)
    assert "이전 업로드를 이어 갑니다" in r2.stdout and len(state.uploads) == 1
    assert len(state.put_order) - n_before == total - got_before     # 빠진 청크만(재전송 0)
    _check_files(state, uid, res, rad)


def test_parallel_one_is_sequential_on_protocol2(tmp_path, server2):
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state, big=500_000)
    state.put_delay = lambda index, k: 0.03
    r = _go(tmp_path, url, res, rad, anchor, par=1)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    assert state.max_inflight_seen == 1
    _check_files(state, out["upload_id"], res, rad)


def test_parallel_capped_by_server_max_parallel(tmp_path, server2):
    state, url = server2
    state.max_parallel = 2
    res, rad, anchor = _setup(tmp_path, state, big=900_000)
    state.put_delay = lambda index, k: 0.1
    r = _go(tmp_path, url, res, rad, anchor, par=8)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    assert state.max_inflight_seen == 2
    assert "병렬 ×2" in r.stdout


def test_server_parallel_limit_429_not_counted_as_retry(tmp_path, server2):
    """서버가 업로드당 2개만 허용하면(429) 클라이언트는 Retry-After 뒤 다시 보낸다 - 재시도 횟수(5)에 안 셈."""
    state, url = server2
    state.max_parallel = 8                    # 서버가 알려 주는 값은 크지만 실제 한도는 2
    state.parallel_limit = 2
    res, rad, anchor = _setup(tmp_path, state, big=1_300_000)
    state.put_delay = lambda index, k: 0.15
    r = _go(tmp_path, url, res, rad, anchor, par=6)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    assert "429" in r.stdout and state.max_inflight_seen <= 2
    _check_files(state, out["upload_id"], res, rad)


def test_old_server_without_protocol_uses_sequential_path(tmp_path, server1):
    """V-US-8: 새 클라이언트 + 구 서버(응답에 protocol 없음) -> 기존 순차 경로."""
    state, url = server1
    res, rad, anchor = _setup(tmp_path, state, big=400_000)
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    assert "(순차)" in r.stdout and "병렬" not in r.stdout
    # 순차: PUT offset 이 파일마다 0 부터 증가
    puts = [(e[1], int(e[2])) for e in state.log if e[0] == "PUT"]
    per_file = {}
    for path, off in puts:
        per_file.setdefault(path, []).append(off)
    assert all(v == sorted(v) for v in per_file.values())
    _check_files(state, out["upload_id"], res, rad)


def test_zero_byte_and_single_chunk_files(tmp_path, server2):
    state, url = server2
    res, rad, anchor = _setup(tmp_path, state, big=10)
    r = _go(tmp_path, url, res, rad, anchor)
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    _check_files(state, out["upload_id"], res, rad)
    assert os.path.getsize(res / "empty.txt") == 0
