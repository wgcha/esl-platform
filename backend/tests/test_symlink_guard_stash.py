"""library._stash·safe_fs 심링크 가드(v0.24.4) — 원본·대상(_backup) 모두 링크면 이동 0, 밖 폴더 불변."""
from __future__ import annotations

import os

import pytest

from esl_platform.api.services import library as lib
from esl_platform.core import safe_fs


def _victim(tmp_path):
    v = tmp_path / "victim"
    (v / "x").mkdir(parents=True)
    (v / "x" / "keep").write_text("keep")
    return v


def test_stash_symlink_entry_not_moved(tmp_path):
    v = _victim(tmp_path)
    lr = tmp_path / "lib"
    lr.mkdir()
    os.symlink(v / "x", lr / "entryX")
    lib._stash(str(lr), str(lr / "entryX"))
    assert (v / "x" / "keep").exists() and os.path.islink(lr / "entryX") and not (lr / "_backup").exists()


def test_stash_normal_moves(tmp_path):
    lr = tmp_path / "lib"
    (lr / "real").mkdir(parents=True)
    (lr / "real" / "a").write_text("a")
    lib._stash(str(lr), str(lr / "real"))
    assert not (lr / "real").exists() and len(list((lr / "_backup").iterdir())) == 1


def test_stash_backup_symlink_not_followed(tmp_path):
    v = _victim(tmp_path)
    lr = tmp_path / "lib2"
    lr.mkdir()
    os.symlink(v, lr / "_backup")
    (lr / "e").mkdir()
    lib._stash(str(lr), str(lr / "e"))
    assert (lr / "e").exists() and sorted(p.name for p in v.iterdir()) == ["x"]


def test_checked_path_reason_is_symlink(tmp_path):
    v = _victim(tmp_path)
    cd = tmp_path / "case"
    cd.mkdir()
    os.symlink(v, cd / "runs")
    with pytest.raises(safe_fs.UnsafePath, match="심링크 경로를 거칩니다"):
        safe_fs.checked_path(str(cd), str(cd / "runs" / "x"))
    with pytest.raises(safe_fs.UnsafePath, match="심링크 경로를 거칩니다"):
        safe_fs.checked_target(str(cd), str(cd / "runs" / "new" / "deep"))
    (cd / "ok").mkdir()
    assert safe_fs.checked_target(str(cd), str(cd / "ok" / "new" / "deep")).endswith("deep")
