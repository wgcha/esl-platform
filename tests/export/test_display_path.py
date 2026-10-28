"""이슈 #24: 경로 표기 통일(display_path)."""
import os

import pytest

from esl.display import display_path


def test_windows_mixed_unified():
    p = "E:/VD_SIMULATION_WEB/esl-data" + "\\" + "85U8000H_9_Face_Drop_Scene06_Face3_1st"
    assert display_path(p, style="windows") == "E:\\VD_SIMULATION_WEB\\esl-data\\85U8000H_9_Face_Drop_Scene06_Face3_1st"
    assert display_path("E:/a//b/./c/", style="windows") == "E:\\a\\b\\c"
    assert display_path("//srv/share/x/y", style="windows") == "\\\\srv\\share\\x\\y"
    assert display_path("d:\\a\\b", style="windows") == "d:\\a\\b"           # 드라이브 문자 유지


def test_passthrough_and_posix():
    assert display_path(None, style="windows") is None and display_path("", style="windows") == ""
    assert display_path(5, style="windows") == 5
    assert display_path("/data/a\\b", style="posix") == "/data/a\\b"


def test_env_force(monkeypatch):
    monkeypatch.setenv("ESL_DISPLAY_PATH_STYLE", "windows")
    assert display_path("E:/a/b") == "E:\\a\\b"
    monkeypatch.setenv("ESL_DISPLAY_PATH_STYLE", "posix")
    assert display_path("E:/a\\b") == "E:/a\\b"
    monkeypatch.delenv("ESL_DISPLAY_PATH_STYLE")
    assert display_path("a/b") == ("a\\b" if os.name == "nt" else "a/b")
