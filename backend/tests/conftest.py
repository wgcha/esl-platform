import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from esl_test_support import *  # noqa: E402,F401,F403


def pytest_configure(config):
    config.addinivalue_line("markers", "short_lease: 워커 lease ttl 을 짧게(esl_test_support.SHORT_LEASE) — ttl 을 넘겨 "
                                       "기다리며 lease 갱신 자체를 확인하는 시험")
    config.addinivalue_line("markers", "chunk64:업로드 청크 크기 64 MB 설정으로 앱을 만든다(test_upload_speed)")
    config.addinivalue_line("markers", "noprealloc: 업로드 설정 preallocate 기본값(false)으로 앱을 만든다(test_upload_speed)")
