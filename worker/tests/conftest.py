import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)), "backend", "tests"))

from esl_test_support import *  # noqa: E402,F401,F403


def pytest_configure(config):
    config.addinivalue_line("markers", "short_lease: 워커 lease ttl 을 짧게(esl_test_support.SHORT_LEASE) — ttl 을 넘겨 "
                                       "기다리며 lease 갱신 자체를 확인하는 시험")
