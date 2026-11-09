import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)), "backend", "tests"))

from esl_test_support import *  # noqa: E402,F401,F403


def pytest_configure(config):
    config.addinivalue_line("markers", "short_lease: 워커 lease ttl 을 짧게(esl_test_support.SHORT_LEASE) — ttl 을 넘겨 "
                                       "기다리며 lease 갱신 자체를 확인하는 시험")
    config.addinivalue_line("markers", "select_schema2: v0.17.0 새 select 스터디(선택 schema 2 — esl_beadgraph.md BG-D-35)를 "
                                       "그대로 만든다. 표지가 없으면 v0.16.2 이전 스터디(schema 1)로 만든다(V-BG-12 회귀)")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _select_schema_legacy(request, monkeypatch):
    """v0.17.0: 새 select 스터디 = inputs·작업 doe.select_schema 2. 기존(schema 1) 시험은 v0.16.2 이전 스터디 그대로 —
    ``select_schema2`` 표지가 없으면 생성 상수를 1 로(작업 스냅샷 select_schema 1 = 키 없음과 같은 경로)."""
    if request.node.get_closest_marker("select_schema2") is None:
        from esl_platform.api.services import doe as svc

        monkeypatch.setattr(svc, "SELECT_SCHEMA_NEW", 1)
    yield
