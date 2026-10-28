import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from esl_test_support import *  # noqa: E402,F401,F403


def pytest_configure(config):
    config.addinivalue_line("markers", "chunk64: 업로드 청크 크기 64 MB 설정으로 앱을 만든다(test_upload_speed)")
