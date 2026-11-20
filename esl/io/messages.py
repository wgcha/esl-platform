"""사용자 문구 읽기 — ``resources/doe_messages.json``(스터디와 같은 원본) 읽기 전용 (v0.24.4, 계약 esl_jig_case.md §4.1·§5.7).

Case 지그 경고·정보 문구가 스터디(``esl.doe.load_messages`` → ``stages._cmp_text``)와 같은 원본·같은 형식을 쓰게 한다.
``esl.doe`` 를 import 하지 않는다(Case 파이프라인 import 그래프). 쓰기 없음.
"""
from __future__ import annotations

import json
import os

from esl.errors import EslError

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resources")
MESSAGES_PATH = os.path.join(RESOURCES, "doe_messages.json")

_CACHE: dict[str, dict[str, str]] = {}


def messages(path: str | None = None) -> dict[str, str]:
    """{코드: 문구 틀} (파일 1회 읽기·캐시). 못 읽음·형식 오류 = CONFIG_INVALID."""
    p = path or MESSAGES_PATH
    if p not in _CACHE:
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            raise EslError("CONFIG_INVALID", f"doe_messages 를 읽을 수 없음: {p}: {exc}") from None
        msgs = doc.get("messages") if isinstance(doc, dict) else None
        if not isinstance(msgs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in msgs.items()):
            raise EslError("CONFIG_INVALID", "doe_messages: messages 는 {코드: 문구}")
        _CACHE[p] = dict(msgs)
    return _CACHE[p]


class _Keep(dict):
    def __missing__(self, k):                     # 자리 표시자 누락은 그대로 둠
        return "{" + k + "}"


def template(code: str, path: str | None = None) -> str:
    """코드 → 문구 틀(없으면 코드 그대로)."""
    return str(messages(path).get(code) or code)


def text(_code: str, /, **kw) -> str:
    """'CODE: 문구'(틀 자리 표시자를 kw 로 채움 — 누락은 그대로). ``stages._cmp_text`` 와 같은 형식. 파일을 못 읽으면 코드만."""
    try:
        tpl = template(_code)
    except EslError:                              # 문구 누락으로 실패하지 않음(스터디와 같은 규칙)
        tpl = _code
    return f"{_code}: {tpl.format_map(_Keep(kw))}"
