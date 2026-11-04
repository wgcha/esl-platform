"""이슈 #53 WinError 32: worker.fs_retry 설정(기본 = esl.fsutil.DEFAULTS, 범위 검사) → 백엔드 기동 시 esl.fsutil 설정,
write_bytes_atomic 의 잠금 재시도·끝내 FILE_LOCKED(임시 파일 정리), API 응답 503 FILE_LOCKED(경로 포함)."""

from __future__ import annotations

import os

import pytest
from esl_test_support import make_settings_dict
from fastapi.testclient import TestClient

from esl import fsutil as F
from esl_platform.core import atomic
from esl_platform.core.config import FsRetryCfg, load_config_dict


@pytest.fixture(autouse=True)
def _reset():
    F.configure(None)
    yield
    F.configure(None)


def _locked_replace(n_fail: int):
    real = os.replace
    st = {"fail": 0}

    def rep(src, dst):
        if st["fail"] < n_fail:
            st["fail"] += 1
            e = PermissionError(13, "다른 프로세스가 파일을 사용 중")
            e.winerror = 32
            raise e
        real(src, dst)
    return rep, st


def test_defaults_match_core():
    assert FsRetryCfg().model_dump() == F.DEFAULTS


def test_config_and_context_configure(tmp_path):
    from esl_platform.api.context import build_context

    d = make_settings_dict(tmp_path)
    assert load_config_dict(d, environ={}).settings.worker.fs_retry.model_dump() == F.DEFAULTS   # 키 없음 = 기본
    d["worker"]["fs_retry"] = {"attempts": 3, "max_wait_s": 2}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    build_context(lc, None)
    assert F.settings() == {**F.DEFAULTS, "attempts": 3, "max_wait_s": 2.0}
    for bad in ({"attempts": 0}, {"max_wait_s": -1}, {"unknown": 1}):
        d["worker"]["fs_retry"] = bad
        lc = load_config_dict(d, environ={})
        assert not lc.ok and any(k.startswith("worker.fs_retry") for k in lc.error_keys()), lc.errors()


def test_write_atomic_retry_and_give_up(tmp_path, monkeypatch):
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    p = tmp_path / "a.json"
    rep, st = _locked_replace(2)
    monkeypatch.setattr(os, "replace", rep)
    atomic.write_text_atomic(str(p), "{}")
    assert p.read_text() == "{}" and st["fail"] == 2
    F.configure({"attempts": 2})
    rep, _ = _locked_replace(10 ** 6)
    monkeypatch.setattr(os, "replace", rep)
    with pytest.raises(atomic.FileLocked) as ei:
        atomic.write_text_atomic(str(p), "{\"b\": 1}")
    assert ei.value.code == "FILE_LOCKED" and str(p) in ei.value.message
    assert p.read_text() == "{}" and not list(tmp_path.glob("*.tmp"))       # 기존 파일 그대로, 임시 파일 정리


def test_api_file_locked_503(tmp_path):
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app

    lc = load_config_dict(make_settings_dict(tmp_path), environ={})
    app = create_app(build_context(lc, None))

    def boom():
        raise F.FileLocked("/x/.a.tmp", "/x/a.inc", 8, 10.0)
    app.add_api_route("/__locked", boom)
    r = TestClient(app).get("/__locked")
    assert r.status_code == 503
    det = r.json()["detail"]
    assert det["code"] == "FILE_LOCKED" and det["path"] == "/x/a.inc" and "/x/a.inc" in det["message"]
