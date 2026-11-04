"""원자적 작은 파일 쓰기: 같은 폴더에 임시 파일을 새로 만들어(O_CREAT|O_EXCL — 기존 파일·심링크를 따라가지 않음)
쓴 뒤 교체. ``path + ".tmp"`` 고정 이름은 그 자리에 심링크가 있으면 링크 대상에 쓰게 되므로 쓰지 않는다.

교체 = ``atomic_replace``(코어 ``esl.fsutil`` 공통 함수 — Windows 잠금 WinError 5/32 지수 백오프 재시도, 끝내 실패하면
``FileLocked``(code ``FILE_LOCKED``)). 재시도 설정 = ``worker.fs_retry``(``configure_fs_retry(settings)``)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from .opt_core import fsutil as _F      # 코어는 어댑터(opt_core)로만 import(test_core_called_only_via_adapter)

FileLocked = _F.FileLocked
atomic_replace = _F.atomic_replace
is_lock_error = _F.is_lock_error
_configure = _F.configure


def fs_retry_dict(settings: Any) -> dict[str, Any]:
    """설정 → esl.fsutil.configure 인자(worker.fs_retry; 워커 섹션이 없으면 빈 dict = DEFAULTS)."""
    w = getattr(settings, "worker", None)
    fr = getattr(w, "fs_retry", None) if w is not None else None
    return fr.model_dump() if fr is not None else {}


def configure_fs_retry(settings: Any) -> dict[str, Any]:
    """이 프로세스의 atomic_replace 재시도 설정을 settings.worker.fs_retry 로. 적용값 사본."""
    return _configure(fs_retry_dict(settings))


def write_bytes_atomic(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        atomic_replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_atomic(path: str, text: str, encoding: str = "utf-8") -> None:
    write_bytes_atomic(path, text.encode(encoding))
