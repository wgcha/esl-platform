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


def test_dotdot_component_rejected_even_when_lexically_inside(tmp_path):
    """root/01_extract/../x 는 abspath 로 root/x 가 되어 통과했음 — 링크 뒤의 .. 는 실제로 다른 곳이므로 거부."""
    v = _victim(tmp_path)
    root = tmp_path / "case"
    root.mkdir()
    os.symlink(v / "x", root / "01_extract")                     # 01_extract → victim/x, 그 상위(..) = victim
    for fn in (safe_fs.checked_target, safe_fs.checked_path):
        with pytest.raises(safe_fs.UnsafePath):
            fn(str(root), str(root / "01_extract" / ".." / "newfile"))
        with pytest.raises(safe_fs.UnsafePath):
            fn(str(root), os.path.join(str(root), "sub", "..", "other"))     # 링크가 없어도 .. 는 쓰기 대상에 허용 안 함
    assert sorted(p.name for p in v.iterdir()) == ["x"]


def test_dotdot_normal_paths_unchanged(tmp_path):
    root = tmp_path / "case"
    (root / "a").mkdir(parents=True)
    assert safe_fs.checked_target(str(root), str(root / "a" / "new.txt")) == str(root / "a" / "new.txt")
    assert safe_fs.checked_path(str(root), str(root / "a")) == str(root / "a")
    assert safe_fs.checked_target(str(root), str(root / "a..b" / "x..")) == str(root / "a..b" / "x..")   # 이름 안의 점 두 개는 허용


# ---- safe_fs `..` 검사: root 자신의 .. 는 허용, root 뒤 꼬리의 .. 는 거부 (v0.24.4 재검증 3) ----
def _dd_tree(tmp_path):
    (tmp_path / "esl" / "case" / "01_extract").mkdir(parents=True)
    (tmp_path / "sub").mkdir()
    return tmp_path


def test_root_with_dotdot_normal_paths_pass(tmp_path):
    t = _dd_tree(tmp_path)
    root = os.path.join(t, "sub", "..", "esl", "case")
    assert safe_fs.checked_path(root, os.path.join(root, "01_extract"))
    assert safe_fs.checked_target(root, os.path.join(root, "01_extract", "jig_fixed", "f.json"))
    assert safe_fs.checked_path(root + "/", os.path.join(root, "01_extract") + "/")


def test_tail_dotdot_rejected(tmp_path):
    t = _dd_tree(tmp_path)
    for root in (os.path.join(t, "esl", "case"), os.path.join(t, "sub", "..", "esl", "case")):
        with pytest.raises(safe_fs.UnsafePath):
            safe_fs.checked_target(root, os.path.join(root, "01_extract", "..", "x"))
        with pytest.raises(safe_fs.UnsafePath):
            safe_fs.checked_path(root, os.path.join(root, "..", "case", "01_extract"))


def test_path_not_from_root_checked_whole(tmp_path):
    t = _dd_tree(tmp_path)
    root = os.path.join(t, "esl", "case")
    with pytest.raises(safe_fs.UnsafePath):
        safe_fs.checked_path(root, os.path.join(t, "sub", "..", "esl", "case", "01_extract"))


def test_dotdot_inside_name_allowed(tmp_path):
    t = _dd_tree(tmp_path)
    root = os.path.join(t, "esl", "case")
    assert safe_fs.checked_target(root, os.path.join(root, "a..b", "x"))
    assert safe_fs.checked_target(root, os.path.join(root, "..x"))
