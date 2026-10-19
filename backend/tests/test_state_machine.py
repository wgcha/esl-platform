"""V-SM-1: E1~E8 허용, 그 외 IllegalTransition."""

import itertools

import pytest

from esl_platform.core.state_machine import ALL_STATES, TRANSITIONS, IllegalTransition, check_transition

ALLOWED = {(None, "QUEUED"): "E1", ("QUEUED", "RUNNING"): "E2", ("QUEUED", "CANCELED"): "E3",
           ("RUNNING", "RUNNING"): "E4", ("RUNNING", "SUCCEEDED"): "E5", ("RUNNING", "FAILED"): "E6",
           ("RUNNING", "CANCELED"): "E7", ("RUNNING", "INTERRUPTED"): "E8"}


def test_table_exact():
    assert TRANSITIONS == ALLOWED


@pytest.mark.parametrize("src,dst", list(itertools.product((None, *ALL_STATES), ALL_STATES)))
def test_all_pairs(src, dst):
    if (src, dst) in ALLOWED:
        assert check_transition(src, dst) == ALLOWED[(src, dst)]
    else:
        with pytest.raises(IllegalTransition):
            check_transition(src, dst)
