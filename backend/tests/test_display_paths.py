"""이슈 #24: API 응답 경로 표기 통일(응답 경계)."""
import json

import pytest

from esl_platform.api.display_json import DisplayJSONResponse, display_paths


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setenv("ESL_DISPLAY_PATH_STYLE", "windows")


def test_display_paths_keys(win):
    mixed = "E:/VD_SIMULATION_WEB/esl-data" + "\\" + "Case1"
    obj = {"case_dir": mixed, "folder_path": mixed, "rad_path": "E:/in/a.rad", "rel": "06_export/a.inc",
           "path": mixed + "\\06_export\\esl_cload.inc", "dir_rel": "_analysis/ab",
           "includes": [{"path": "E:/in/inc.rad", "ok": True}],
           "params": {"h3d": {"h3d_path": "E:/x/y.h3d", "out_dir": "E:/o/p"}},
           "input_roots": ["E:/in", "E:\\up"], "detail": {"path": "E:/z\\w"}}
    out = display_paths(obj)
    assert out["case_dir"] == out["folder_path"] == "E:\\VD_SIMULATION_WEB\\esl-data\\Case1"
    assert out["path"] == "E:\\VD_SIMULATION_WEB\\esl-data\\Case1\\06_export\\esl_cload.inc"
    assert out["rel"] == "06_export/a.inc" and out["dir_rel"] == "_analysis/ab"       # 상대경로 불변
    assert out["includes"][0]["path"] == "E:\\in\\inc.rad"
    assert out["params"]["h3d"] == {"h3d_path": "E:\\x\\y.h3d", "out_dir": "E:\\o\\p"}
    assert out["input_roots"] == ["E:\\in", "E:\\up"] and out["detail"]["path"] == "E:\\z\\w"
    assert obj["case_dir"] == mixed                                                    # 원본 불변


def test_browse_relative_path_untouched(win):
    b = {"roots": [{"index": 0, "path": "E:/in"}], "root": 0, "path": "a/b", "parent": "a", "abs_path": "E:/in/a/b",
         "entries": []}
    out = display_paths(b)
    assert out["path"] == "a/b" and out["parent"] == "a"
    assert out["roots"][0]["path"] == "E:\\in" and out["abs_path"] == "E:\\in\\a\\b"


def test_response_class_renders(win):
    r = DisplayJSONResponse({"case_dir": "E:/a/b\\c"})
    assert json.loads(r.body) == {"case_dir": "E:\\a\\b\\c"}


def test_linux_posix_unchanged(monkeypatch):
    monkeypatch.setenv("ESL_DISPLAY_PATH_STYLE", "posix")
    assert display_paths({"case_dir": "/srv/a/b"}) == {"case_dir": "/srv/a/b"}
