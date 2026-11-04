"""이슈 #53 WinError 32: esl.fsutil.atomic_replace — Windows 잠금(PermissionError winerror 5/32) 지수 백오프 재시도,
끝내 실패 → FILE_LOCKED(경로 포함), 그 밖의 오류는 재시도 없이 그대로(assem_full 주입 시험 = tests/doe/test_assem_full.py)."""
from __future__ import annotations

import os

import pytest

from esl import fsutil as F
from esl.errors import EslError


def locked(winerror: int = 32) -> PermissionError:
    e = PermissionError(13, "다른 프로세스가 파일을 사용 중")
    e.winerror = winerror          # POSIX 에는 winerror 속성이 없음 — Windows 오류를 흉내
    return e


@pytest.fixture(autouse=True)
def _reset_cfg():
    F.configure(None)
    yield
    F.configure(None)


def flaky(n_fail: int, winerror: int = 32, match: str | None = None):
    """처음 n_fail 회(match 가 있으면 dst 이름에 match 가 든 호출만) 잠금 오류, 그 뒤 진짜 os.replace."""
    real = os.replace
    st = {"fail": 0, "calls": 0}

    def rep(src, dst):
        st["calls"] += 1
        if (match is None or match in os.path.basename(str(dst))) and st["fail"] < n_fail:
            st["fail"] += 1
            raise locked(winerror)
        real(src, dst)
    return rep, st


def test_retry_then_success(tmp_path):
    src, dst = tmp_path / ".a.tmp", tmp_path / "a.inc"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    rep, st = flaky(3)
    sleeps = []
    F.atomic_replace(str(src), str(dst), _replace=rep, _sleep=sleeps.append)
    assert dst.read_bytes() == b"new" and not src.exists()
    assert st["fail"] == 3 and sleeps == [0.05, 0.1, 0.2]        # base_s × 2^i


def test_access_denied_winerror5_also_retried(tmp_path):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_bytes(b"x")
    rep, st = flaky(1, winerror=5)
    F.atomic_replace(str(src), str(dst), _replace=rep, _sleep=lambda s: None)
    assert dst.read_bytes() == b"x" and st["fail"] == 1


def test_gives_up_with_file_locked(tmp_path):
    src, dst = tmp_path / ".generated_dampvrel.inc.1.tmp", tmp_path / "generated_dampvrel.inc"
    src.write_bytes(b"x")
    F.configure({"attempts": 4, "max_wait_s": 60})
    rep, st = flaky(10 ** 6)
    sleeps = []
    with pytest.raises(F.FileLocked) as ei:
        F.atomic_replace(str(src), str(dst), _replace=rep, _sleep=sleeps.append)
    e = ei.value
    assert isinstance(e, EslError) and e.code == "FILE_LOCKED"
    assert "generated_dampvrel.inc" in e.message and "백신" in e.message
    assert str(tmp_path) not in e.message                         # 사용자 문구 = 파일 이름만(서버 절대 경로는 로그에만)
    assert str(dst) in e.log_text() and str(src) in e.log_text()
    assert e.dst == str(dst) and e.src == str(src)
    assert st["calls"] == 4 and len(sleeps) == 3                  # attempts 회 시도, 사이 대기 attempts-1 회
    assert src.read_bytes() == b"x" and not dst.exists()          # 실패한 교체는 src 를 그대로 둔다


def test_total_wait_capped(tmp_path):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_bytes(b"x")
    F.configure({"attempts": 100, "max_wait_s": 0.3})
    rep, _ = flaky(10 ** 6)
    sleeps = []
    with pytest.raises(F.FileLocked):
        F.atomic_replace(str(src), str(dst), _replace=rep, _sleep=sleeps.append)
    assert sum(sleeps) == pytest.approx(0.3) and len(sleeps) < 10


def test_other_errors_not_retried(tmp_path):
    calls = []

    def rep(src, dst):
        calls.append(1)
        raise PermissionError(13, "POSIX 권한 오류")              # winerror 없음 = 잠금 아님
    with pytest.raises(PermissionError):
        F.atomic_replace("a", "b", _replace=rep, _sleep=lambda s: None)
    assert calls == [1]
    with pytest.raises(FileNotFoundError):
        F.atomic_replace(str(tmp_path / "없음"), str(tmp_path / "d"))


def test_configure_defaults_and_override():
    assert F.settings() == F.DEFAULTS
    got = F.configure({"attempts": 3, "max_wait_s": None, "unknown": 1})
    assert got == {**F.DEFAULTS, "attempts": 3}
    assert F.configure({}) == F.DEFAULTS


def test_directory_replace(tmp_path):
    a = tmp_path / "stage"
    a.mkdir()
    (a / "f").write_text("1")
    F.atomic_replace(str(a), str(tmp_path / "final"))
    assert (tmp_path / "final" / "f").read_text() == "1" and not a.exists()


def test_file_locked_message_hides_cause_path_and_user_path(tmp_path):
    """원인 PermissionError 의 문자열(절대 경로 포함)은 문구에 넣지 않음 — WinError 번호·설명만. user_path = root 기준 상대·밖이면 이름."""
    cause = PermissionError(13, "다른 프로세스가 파일을 사용 중", str(tmp_path / "secret" / "a.inc"))
    cause.winerror = 32
    e = F.FileLocked(str(tmp_path / "secret" / ".a.tmp"), str(tmp_path / "secret" / "a.inc"), 8, 10.0, cause)
    assert "secret" not in e.message and str(tmp_path) not in e.message
    assert "a.inc ← .a.tmp" in e.message and "[WinError 32: 다른 프로세스가 파일을 사용 중]" in e.message
    assert F.user_path(str(tmp_path / "secret" / "a.inc"), str(tmp_path)) == "secret/a.inc"
    assert F.user_path(str(tmp_path / "secret" / "a.inc"), str(tmp_path / "other")) == "a.inc"
    assert F.user_path(str(tmp_path / "a.inc")) == "a.inc"
