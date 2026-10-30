import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from scx_support import scx_settings, start_relay  # noqa: E402


@pytest.fixture()
def fake_relay(tmp_path):
    f = start_relay(tmp_path / "drive")
    try:
        yield f
    finally:
        f.stop()


@pytest.fixture()
def settings_dict(tmp_path, fake_relay):
    return scx_settings(tmp_path, fake_relay)


@pytest.fixture(autouse=True)
def _scx_reset():
    from esl_platform.core.scx import gateway

    gateway.reset()
    yield
    gateway.reset()
