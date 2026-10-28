"""원자적 작은 파일 쓰기: 같은 폴더에 임시 파일을 새로 만들어(O_CREAT|O_EXCL — 기존 파일·심링크를 따라가지 않음)
쓴 뒤 os.replace. ``path + ".tmp"`` 고정 이름은 그 자리에 심링크가 있으면 링크 대상에 쓰게 되므로 쓰지 않는다."""

from __future__ import annotations

import os
import tempfile


def write_bytes_atomic(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_atomic(path: str, text: str, encoding: str = "utf-8") -> None:
    write_bytes_atomic(path, text.encode(encoding))
