"""업로드 complete 의 상태 파일 판정(_state_probe)이 줄바꿈 없는 거대 파일에서도 앞 upload.state_scan_kb 만 읽는지(v0.8.0 검증 반영)."""
import os
import subprocess
import sys

import pytest

from esl_platform.api.services import uploads
from esl_platform.core.config import UploadCfg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BIG = 200 * 1024 * 1024


def _write(path, data: bytes, size: int | None = None) -> str:
    with open(path, "wb") as fh:
        fh.write(data)
        if size:
            fh.truncate(size)
    return str(path)


def test_normal_state_files_unchanged(tmp_path):
    a = _write(tmp_path / "a.str", b"#RADIOSS STATE FILE a.str\n/BEGIN\nx\n/NODE\n 1 0 0 0\n/SHELL/1\n 1 1 1 2 3 4\n")
    b = _write(tmp_path / "b.sta", b"\n#RADIOSS STATE FILE b.sta\n/INISHE/EPSP_F\n")
    c = _write(tmp_path / "c.inc", b"# deck\n/NODE\n")
    assert uploads._state_probe(a) == (True, ["geometry"])
    assert uploads._state_probe(b) == (True, ["initial"])
    assert uploads._state_probe(b, header_only=True) == (True, [])
    assert uploads._state_probe(c) == (False, ["geometry"])
    assert UploadCfg().state_scan_kb == 4096


def test_huge_line_stops_at_scan_budget(tmp_path):
    f = _write(tmp_path / "huge.sta", b"", BIG)                   # 줄바꿈 없음(0 바이트)
    assert uploads._state_probe(f) == (False, [])
    g = _write(tmp_path / "huge2.sta", b"#RADIOSS STATE FILE x\n/NODE\n", BIG)
    assert uploads._state_probe(g) == (True, ["geometry"])       # 헤더·블록은 보고 긴 줄에서 멈춤
    h = _write(tmp_path / "late.sta", b"#RADIOSS STATE FILE x\n" + b"#" * 8192 + b"\n/INISHE/EPSP_F\n")
    assert uploads._state_probe(h, scan_bytes=4096) == (True, [])   # 예산(설정) 밖 블록은 보지 않음
    assert uploads._state_probe(h) == (True, ["initial"])


@pytest.mark.skipif(sys.platform != "linux", reason="ru_maxrss 단위는 Linux 기준")
def test_huge_line_memory_bounded(tmp_path):
    f = _write(tmp_path / "huge.sta", b"", BIG)
    prog = ("import resource, sys\n"
            f"sys.path[:0] = {[os.path.join(ROOT, 'backend'), os.path.join(ROOT, 'worker'), ROOT]!r}\n"
            "from esl_platform.api.services import uploads\n"
            "r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
            f"uploads._state_probe({f!r})\n"
            "r1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
            "print((r1 - r0) / 1024)\n")
    out = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    d = float(out.stdout.strip().splitlines()[-1])
    assert d <= 4 + 24, d          # 앞 4 MB + 여유(예전 for raw in fh 는 +405 MB)
