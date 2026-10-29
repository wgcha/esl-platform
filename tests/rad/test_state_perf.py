"""V-CI-P5: /INISHE/EPSP_F 스트리밍 성능 — 대상 20 %, NPT=5·NPG=4.

기본(전체 시험)은 합성 약 60 MB 로 시간·메모리를 1 GB 목표(≤ 15 s, 추가 ≤ 150 MB)에 비례 환산해 확인한다.
ESL_TEST_PERF_GB=1 이면 그 크기(GB)로 만들어 목표 그대로 확인(시간·메모리 출력).
메모리는 별도 프로세스의 ru_maxrss 증가분(호출 전 → 후 최대)으로 잰다.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REC_BYTES = 51 + 4 * 101          # 헤더 + 값 4행(5×20 + 개행)
TARGET_S_PER_GB = 15.0
TARGET_MB = 150.0

_GEN = r'''
import sys
path, n = sys.argv[1], int(sys.argv[2])
hdr = ["#---1----|", "/INISHE/EPSP_F", "#  SHELLID, NPT, NPG, THK"]
z = " 0.0000000000000E+00" * 5 + "\n"
v = " 1.2500000000000E-02 2.5000000000000E-02 3.7500000000000E-02 5.0000000000000E-02 0.0000000000000E+00\n"
with open(path, "w", newline="\n") as fh:
    fh.write("\n".join(hdr) + "\n")
    blk = []
    for i in range(n):
        blk.append(f"{1000000 + i:10d}         5         4 1.1995980739594E+00\n")
        blk.append(v if i % 7 == 0 else z)
        blk.append(z); blk.append(z); blk.append(z)
        if len(blk) > 200000:
            fh.write("".join(blk)); blk.clear()
    fh.write("".join(blk))
'''

_RUN = r'''
import json, os, resource, sys, time
import numpy as np
from esl.rad.state import read_epsp_f
path, n = sys.argv[1], int(sys.argv[2])
ids = 1000000 + np.arange(0, n, 5, dtype=np.int64)            # 대상 20 %
nl = sum(1 for _ in open(path, "rb")) - 2
seg = [(path, len("#---1----|\n/INISHE/EPSP_F\n".encode()), 3, nl)]
r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
t = time.perf_counter()
ep = read_epsp_f(seg, ids)
dt = time.perf_counter() - t
r1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
ok = bool(ep.has.all()) and abs(float(ep.agg["max"][0]) - 0.05) < 1e-12 and int(ep.n_records) == n
print(json.dumps({"seconds": dt, "extra_mb": (r1 - r0) / 1024.0, "ok": ok, "n_target": int(ids.size),
                  "bytes": os.path.getsize(path)}))
'''


def _run(tmp_path, n):
    path = str(tmp_path / "big.sta")
    subprocess.run([sys.executable, "-c", _GEN, path, str(n)], check=True)
    env = dict(os.environ, PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.run([sys.executable, "-c", _RUN, path, str(n)], capture_output=True, text=True, env=env, cwd=ROOT)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_p5_epsp_streaming_scaled(tmp_path):
    gb = float(os.environ.get("ESL_TEST_PERF_GB") or 0)
    n = int((gb * 1024 ** 3 if gb else 60 * 1024 ** 2) / REC_BYTES)
    r = _run(tmp_path, n)
    assert r["ok"], r
    scale = r["bytes"] / 1024 ** 3
    print(f"\nV-CI-P5: {r['bytes'] / 1e6:.0f} MB, 대상 {r['n_target']}, {r['seconds']:.2f} s "
          f"(1 GB 환산 {r['seconds'] / scale:.1f} s), 추가 메모리 {r['extra_mb']:.1f} MB")
    assert r["seconds"] / scale <= TARGET_S_PER_GB
    assert r["extra_mb"] <= TARGET_MB
