"""v0.12.0 L1: 오류 문구·detail 의 서버 절대경로를 일반 사용자에게 가린다(전역 관리자는 원문).

대상: POST /paths/inspect·Case 생성·작업 생성/재시도(include 가 입력 루트 밖 — PATH_OUTSIDE_ROOT)·비드 최적화/강성 평가 스터디의
기준 Case 입력 검사(PREREQUISITE_MISSING 문구에 경로 포함). 서비스 함수 시그니처 (ctx, principal, ...) 에 데코레이터로 붙인다.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from ...core.errors import DomainError


def mask_error(ctx, principal, exc: DomainError) -> DomainError:
    """일반 사용자면 경로를 가린 새 DomainError(바뀐 것이 없으면 exc 그대로). 관리자·주체 없음이면 exc 그대로."""
    if principal is None or getattr(principal, "is_global_admin", False):
        return exc
    from .jobs import _root_labels, mask_server_paths

    roots = _root_labels(ctx)
    msg = mask_server_paths(exc.message, roots)
    extra = {k: (mask_server_paths(v, roots) if isinstance(v, str) else v) for k, v in exc.extra.items()}
    if msg == exc.message and extra == exc.extra:
        return exc
    return DomainError(exc.code, msg, status=exc.status, headers=exc.headers, **extra)


def masks_paths(fn: Callable[..., Any]) -> Callable[..., Any]:
    """(ctx, principal, ...) 서비스 함수의 DomainError 경로 가림."""

    @functools.wraps(fn)
    def wrapper(ctx, principal, *a, **kw):
        try:
            return fn(ctx, principal, *a, **kw)
        except DomainError as exc:
            new = mask_error(ctx, principal, exc)
            if new is exc:
                raise
            raise new from None

    return wrapper


__all__ = ["mask_error", "masks_paths"]
