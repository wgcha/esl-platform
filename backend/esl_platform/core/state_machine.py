"""작업 상태 머신(계약 esl.md §4.1, E1~E8). 표에 없는 전이는 IllegalTransition."""

from __future__ import annotations

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELED = "CANCELED"
INTERRUPTED = "INTERRUPTED"

ALL_STATES = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELED, INTERRUPTED)
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELED, INTERRUPTED})
ACTIVE = frozenset(ALL_STATES) - TERMINAL

# (from, to) → 전이 번호. from=None 은 생성.
TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, QUEUED): "E1",
    (QUEUED, RUNNING): "E2",
    (QUEUED, CANCELED): "E3",
    (RUNNING, RUNNING): "E4",
    (RUNNING, SUCCEEDED): "E5",
    (RUNNING, FAILED): "E6",
    (RUNNING, CANCELED): "E7",
    (RUNNING, INTERRUPTED): "E8",
}


class IllegalTransition(RuntimeError):
    def __init__(self, src: str | None, dst: str) -> None:
        super().__init__(f"허용되지 않는 상태 전이: {src} → {dst}")
        self.src = src
        self.dst = dst


def check_transition(src: str | None, dst: str) -> str:
    try:
        return TRANSITIONS[(src, dst)]
    except KeyError:
        raise IllegalTransition(src, dst) from None


def is_terminal(state: str) -> bool:
    return state in TERMINAL
