"""도메인 오류: API 응답 `{"detail": {"code", "message", ...}}` 로 변환된다."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400, **extra: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def not_found(code: str = "NOT_FOUND", message: str = "찾을 수 없습니다") -> DomainError:
    return DomainError(code, message, status=404)


def forbidden(message: str = "권한이 없습니다", code: str = "FORBIDDEN") -> DomainError:
    return DomainError(code, message, status=403)


def conflict(code: str, message: str, **extra: Any) -> DomainError:
    return DomainError(code, message, status=409, **extra)


def unprocessable(code: str, message: str, **extra: Any) -> DomainError:
    return DomainError(code, message, status=422, **extra)


class LeaseLost(RuntimeError):
    """워커가 lease를 잃음(상태를 더 쓰지 않는다)."""
