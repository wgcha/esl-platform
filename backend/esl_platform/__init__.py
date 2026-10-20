"""ESL 플랫폼(P1b): API·DB·워커. 계산은 전부 코어 `esl` 패키지(esl.pipeline.run)."""

from __future__ import annotations

import json
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]     # .../backend/esl_platform → 코드 루트(저장소 또는 <런타임>/app)


def read_version(root: Path = _CODE_ROOT) -> str:
    """코드 루트의 BUILD.json{version}(설치 런타임) → 없으면 VERSION 파일(저장소) → 둘 다 없으면 0.0.0."""
    try:
        d = json.loads((root / "BUILD.json").read_text(encoding="utf-8-sig"))
        if isinstance(d, dict) and str(d.get("version") or "").strip():
            return str(d["version"]).strip()
    except (OSError, ValueError):
        pass
    try:
        return (root / "VERSION").read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


__version__ = read_version()
