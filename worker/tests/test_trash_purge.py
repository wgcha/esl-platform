"""v0.19.0 휴지통 영구 삭제 리퍼(계약 esl_item_delete.md §3·§7 V-DEL-14~16): worker/esl_worker/trash_purge.py + Worker.purge_trash·상주 루프."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from esl_platform.core import trash
from esl_platform.core.auth import Principal
from esl_test_support import make_settings_dict, wait_for
from sqlalchemy import text
from test_item_delete import KDIR, TABLE, _put_folder, count, deletion_row, seed_item, seed_job, trash_names

POWER = Principal(user_id="u-power", username="power", display_name="파워", is_global_admin=False, roles={"p-1": "power"})


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path)
    d["worker"]["fs_retry"] = {"attempts": 3, "max_wait_s": 0.5, "base_s": 0.001}
    d["item_delete"] = {"purge_interval_s": 0.2, "purge_batch": 20, "purge_max_attempts": 3, "summary_job_ids_max": 50}
    return d


def _set_cfg(w, **upd):
    s = w.config.settings
    w.config.settings = s.model_copy(update={"item_delete": s.item_delete.model_copy(update=upd)})


def _lock_err():
    e = PermissionError(13, "sharing violation")
    e.winerror = 32
    return e


def _delete(app_ctx, kind, iid):
    from esl_platform.api.services import item_delete

    return item_delete.delete_item(app_ctx, POWER, kind, iid)


def _put_trash(esl_root: Path, kind: str, iid: str, stamp: str = "20261112-010101") -> Path:
    """DB 항목 없이 휴지통 항목만 만든다(내부에 링크 포함 가능)."""
    p = esl_root / "_trash" / f"{stamp}_{kind}_{iid}"
    (p / "sub").mkdir(parents=True)
    (p / "a.txt").write_text("a")
    (p / "sub" / "b.bin").write_bytes(b"b" * 10)
    return p


# ---------------------------------------------------------------- V-DEL-14
def test_v14_purges_deleted_item_to_purged(app_ctx, worker_factory, engine, esl_root):
    iid = seed_item(engine, esl_root, "OPT")
    seed_job(engine, "OPT", iid)
    assert _delete(app_ctx, "OPT", iid)["purge"] == "PENDING"
    assert len(trash_names(esl_root)) == 1 and deletion_row(engine, "OPT", iid)["purge_state"] == "PENDING"
    out = worker_factory().purge_trash()
    assert out.purged == 1 and out.failed == 0
    assert trash_names(esl_root) == [] and (esl_root / "_trash").is_dir()
    row = deletion_row(engine, "OPT", iid)
    assert row["purge_state"] == "PURGED" and row["purged_at"] is not None and row["purge_attempts"] == 0
    assert row["purge_error"] is None
    assert worker_factory().purge_trash().purged == 0                    # 할 일 없음


def test_v14_study_multi_dirs_all_purged(app_ctx, worker_factory, engine, esl_root, inputs_root):
    from test_item_delete import seed_drop

    sid = seed_item(engine, esl_root, "DOE")
    seed_drop(engine, esl_root, inputs_root, sid, n=1)
    seed_drop(engine, esl_root, inputs_root, sid, n=2)
    assert _delete(app_ctx, "DOE", sid)["n_verify_drops"] == 2
    assert len(trash_names(esl_root)) == 3
    out = worker_factory().purge_trash()
    assert out.purged == 3 and trash_names(esl_root) == []
    assert deletion_row(engine, "DOE", sid)["purge_state"] == "PURGED"


def test_v14_links_inside_removed_but_targets_kept(app_ctx, worker_factory, engine, esl_root, tmp_path):
    iid = seed_item(engine, esl_root, "COMPARE")
    d = esl_root / "_compare" / iid
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (outside / "deep").mkdir()
    (outside / "deep" / "keep2.txt").write_text("keep2")
    (tmp_path / "ofile.txt").write_text("of")
    os.symlink(outside, d / "dirlink", target_is_directory=True)
    os.symlink(tmp_path / "ofile.txt", d / "sub" / "filelink")
    os.symlink(tmp_path / "missing", d / "dangling")
    _delete(app_ctx, "COMPARE", iid)
    out = worker_factory().purge_trash()
    assert out.purged == 1 and trash_names(esl_root) == []
    assert (outside / "keep.txt").read_text() == "keep" and (outside / "deep" / "keep2.txt").read_text() == "keep2"
    assert (tmp_path / "ofile.txt").read_text() == "of"
    assert deletion_row(engine, "COMPARE", iid)["purge_state"] == "PURGED"


def test_v14_purge_entry_counts_and_junction_mock(app_ctx, esl_root, tmp_path, monkeypatch):
    s = app_ctx.settings
    iid = str(uuid.uuid4())
    p = _put_trash(esl_root, "OPT", iid)
    outside = tmp_path / "o"
    outside.mkdir()
    (outside / "k.txt").write_text("k")
    os.symlink(outside, p / "lnk", target_is_directory=True)
    res = trash.purge_entry(s, p.name)
    assert res.ok and res.removed_files == 2 and res.skipped_links == 1 and res.error is None
    assert not p.exists() and (outside / "k.txt").is_file()
    # junction 모의: 실제 폴더를 링크로 취급 → 내용은 건드리지 않고 링크 객체만(여기서는 rmdir 불가 → 실패 보고)
    iid2 = str(uuid.uuid4())
    p2 = _put_trash(esl_root, "OPT", iid2)
    (p2 / "jn").mkdir()
    (p2 / "jn" / "inside.txt").write_text("i")
    real = trash.is_link_like
    monkeypatch.setattr(trash, "is_link_like", lambda x: os.path.basename(x) == "jn" or real(x))
    res = trash.purge_entry(s, p2.name)
    assert (p2 / "jn" / "inside.txt").is_file()                          # 링크로 본 폴더 안은 따라가지 않음
    assert not res.ok and res.error and "jn" in res.error and str(esl_root) not in res.error


def test_v14_purge_entry_rejects_unsafe(app_ctx, esl_root, tmp_path):
    s = app_ctx.settings
    for bad in ("", "x", "../x", "20261112-010101_DOE_not-a-uuid", f"20261112-010101_NOPE_{uuid.uuid4()}"):
        r = trash.purge_entry(s, bad)
        assert not r.ok and r.removed_files == 0
    iid = str(uuid.uuid4())
    outside = tmp_path / "ext"
    outside.mkdir()
    (outside / "keep").write_text("k")
    (esl_root / "_trash").mkdir()
    os.symlink(outside, esl_root / "_trash" / f"20261112-010101_OPT_{iid}", target_is_directory=True)
    r = trash.purge_entry(s, f"20261112-010101_OPT_{iid}")                # 최상위가 링크 → 링크만 제거
    assert r.ok and r.skipped_links == 1 and (outside / "keep").is_file()
    assert trash.purge_entry(s, f"20261112-010101_OPT_{uuid.uuid4()}").ok  # 이미 없음 = ok


def test_v14_no_deletion_row_and_no_db_row_is_purged(app_ctx, worker_factory, engine, esl_root):
    iid = str(uuid.uuid4())
    p = _put_trash(esl_root, "ANALYSIS", iid)
    out = worker_factory().purge_trash()
    assert out.purged == 1 and not p.exists()


# ---------------------------------------------------------------- V-DEL-15
def test_v15_db_row_present_is_restored_not_purged(app_ctx, worker_factory, engine, esl_root):
    iid = seed_item(engine, esl_root, "OPT", folder=False)
    p = _put_trash(esl_root, "OPT", iid)                                  # 롤백 잔여(행이 남아 있음)
    out = worker_factory().purge_trash()
    assert out.restored == 1 and out.purged == 0
    assert (esl_root / "_opt" / iid / "a.txt").read_text() == "a" and not p.exists()
    assert count(engine, "opt_runs", "id=:i", i=iid) == 1


def test_v15_db_row_present_and_origin_occupied_is_kept(app_ctx, worker_factory, engine, esl_root):
    iid = seed_item(engine, esl_root, "DOE")                              # 원래 자리가 이미 차 있음
    p = _put_trash(esl_root, "DOE", iid)
    out = worker_factory().purge_trash()
    assert out.restored == 0 and out.purged == 0 and out.skipped == 1
    assert (p / "a.txt").is_file() and (esl_root / "_doe" / iid / "report.html").is_file()   # 둘 다 그대로


def test_v15_unparsable_names_untouched(app_ctx, worker_factory, engine, esl_root):
    t = esl_root / "_trash"
    t.mkdir()
    (t / "foo").mkdir()
    (t / "foo" / "x").write_text("x")
    (t / "20261112-000000_DOE_not-a-uuid").mkdir()
    (t / "readme.txt").write_text("r")
    (t / f"20261340-000000_DOE_{uuid.uuid4()}").mkdir()
    (t / f"20261112-000000_DOE_{str(uuid.uuid4()).upper()}").mkdir()
    before = sorted(os.listdir(t))
    out = worker_factory().purge_trash()
    assert out.purged == 0 and out.skipped == 5 and sorted(os.listdir(t)) == before and (t / "foo" / "x").is_file()
    good = _put_trash(esl_root, "OPT", str(uuid.uuid4()))                 # 형식이 맞는 것만 처리(이상한 이름이 막지 않음)
    assert worker_factory().purge_trash().purged == 1 and not good.exists() and sorted(os.listdir(t)) == before


def test_v15_row_locked_by_inflight_delete_is_skipped(app_ctx, worker_factory, engine, esl_root):
    """삭제 트랜잭션이 항목 행을 잠그고 있는 동안(폴더는 이미 휴지통) 리퍼는 되돌리지도 지우지도 않는다."""
    iid = seed_item(engine, esl_root, "OPT", folder=False)
    p = _put_trash(esl_root, "OPT", iid)
    w = worker_factory()
    with engine.connect() as c, c.begin():
        c.execute(text("SELECT id FROM opt_runs WHERE id=:i FOR UPDATE"), {"i": iid})
        out = w.purge_trash()
        assert out.skipped == 1 and out.restored == 0 and out.purged == 0 and (p / "a.txt").is_file()
    assert w.purge_trash().restored == 1                                  # 롤백 뒤(행 남음) → 되돌림


def test_v15_inflight_delete_then_commit_is_purged(app_ctx, worker_factory, engine, esl_root):
    iid = seed_item(engine, esl_root, "COMPARE")
    w = worker_factory()
    from esl_platform.api.services import item_delete

    orig = item_delete.del_repo.insert_deletion

    def hook(conn, **kw):               # 폴더는 이미 휴지통, 행은 아직 안 지워진 커밋 직전에 리퍼가 돈다
        assert w.purge_trash().skipped == 1
        return orig(conn, **kw)

    item_delete.del_repo.insert_deletion = hook
    try:
        _delete(app_ctx, "COMPARE", iid)
    finally:
        item_delete.del_repo.insert_deletion = orig
    assert len(trash_names(esl_root)) == 1
    assert w.purge_trash().purged == 1 and trash_names(esl_root) == []


# ---------------------------------------------------------------- V-DEL-16
def _fail_unlink(monkeypatch, name: str):
    real = os.unlink

    def unlink(path, *a, **k):
        if os.path.basename(str(path)) == name:
            raise _lock_err()
        return real(path, *a, **k)

    monkeypatch.setattr(os, "unlink", unlink)
    return real


def test_v16_lock_failure_marks_failed_then_next_cycle_purged(app_ctx, worker_factory, engine, esl_root, monkeypatch):
    iid = seed_item(engine, esl_root, "OPT")
    _delete(app_ctx, "OPT", iid)
    w = worker_factory()
    _fail_unlink(monkeypatch, "data.bin")
    out = w.purge_trash()
    assert out.failed == 1 and out.purged == 0
    row = deletion_row(engine, "OPT", iid)
    assert row["purge_state"] == "FAILED" and row["purge_attempts"] == 1 and row["purge_error"]
    assert len(row["purge_error"]) <= 200 and str(esl_root) not in row["purge_error"] and "WinError 32" in row["purge_error"]
    assert len(trash_names(esl_root)) == 1                                # 잠기지 않은 파일은 이미 지워진 상태로 남음
    out = w.purge_trash()                                                 # 아직 잠김 → attempts 2
    assert out.failed == 1 and deletion_row(engine, "OPT", iid)["purge_attempts"] == 2
    monkeypatch.undo()
    out = w.purge_trash()                                                 # 잠금 해제 → PURGED
    assert out.purged == 1 and trash_names(esl_root) == []
    row = deletion_row(engine, "OPT", iid)
    assert row["purge_state"] == "PURGED" and row["purge_error"] is None and row["purge_attempts"] == 2


def test_v16_attempt_cap_stops_retries(app_ctx, worker_factory, engine, esl_root, monkeypatch):
    iid = seed_item(engine, esl_root, "ANALYSIS")
    _delete(app_ctx, "ANALYSIS", iid)
    w = worker_factory()                                                  # purge_max_attempts = 3
    _fail_unlink(monkeypatch, "data.bin")
    for n in (1, 2, 3):
        assert w.purge_trash().failed == 1
        assert deletion_row(engine, "ANALYSIS", iid)["purge_attempts"] == n
    monkeypatch.undo()
    out = w.purge_trash()                                                 # 상한 도달 → 재시도 중지(잠금이 풀렸어도 그대로)
    assert out.purged == 0 and out.failed == 0
    row = deletion_row(engine, "ANALYSIS", iid)
    assert row["purge_state"] == "FAILED" and row["purge_attempts"] == 3 and len(trash_names(esl_root)) == 1
    from esl_platform.core.repositories import deletions as del_repo

    with engine.connect() as c:
        assert del_repo.count_stuck(c, max_attempts=3) == 1
    _set_cfg(w, purge_max_attempts=4)                                     # 상한을 올리면 재시도
    assert w.purge_trash().purged == 1 and deletion_row(engine, "ANALYSIS", iid)["purge_state"] == "PURGED"


def test_v16_readonly_file_permission_error_chmod_retry(app_ctx, esl_root, monkeypatch):
    """PermissionError(비잠금) → chmod(S_IWRITE) 후 재시도해서 성공."""
    s = app_ctx.settings
    iid = str(uuid.uuid4())
    p = _put_trash(esl_root, "OPT", iid)
    real = os.unlink
    calls = {"n": 0}

    def unlink(path, *a, **k):
        if os.path.basename(str(path)) == "a.txt" and calls["n"] < 1:
            calls["n"] += 1
            raise PermissionError(13, "read-only")
        return real(path, *a, **k)

    chmods = []
    real_chmod = os.chmod
    monkeypatch.setattr(os, "chmod", lambda path, mode, *a, **k: (chmods.append(os.path.basename(str(path))),
                                                                  real_chmod(path, mode, *a, **k))[1])
    monkeypatch.setattr(os, "unlink", unlink)
    res = trash.purge_entry(s, p.name)
    assert res.ok and not p.exists() and "a.txt" in chmods


# ---------------------------------------------------------------- 배치·상주 루프
def test_batch_limit_per_cycle(app_ctx, worker_factory, engine, esl_root):
    ids = [seed_item(engine, esl_root, "OPT") for _ in range(3)]
    for i in ids:
        _delete(app_ctx, "OPT", i)
    w = worker_factory()
    _set_cfg(w, purge_batch=2)
    assert w.purge_trash().purged == 2 and len(trash_names(esl_root)) == 1
    assert w.purge_trash().purged == 1 and trash_names(esl_root) == []
    assert {deletion_row(engine, "OPT", i)["purge_state"] for i in ids} == {"PURGED"}


def test_batch_limit_counts_unlisted_entries_too(app_ctx, worker_factory, engine, esl_root):
    for _ in range(3):
        _put_trash(esl_root, "OPT", str(uuid.uuid4()))
    w = worker_factory()
    _set_cfg(w, purge_batch=2)
    assert w.purge_trash().purged == 2 and len(trash_names(esl_root)) == 1


def test_resident_loop_purges_every_interval(app_ctx, worker_factory, engine, esl_root):
    """Worker.start() 의 리퍼 루프가 item_delete.purge_interval_s 마다 호출한다(시험 설정 0.2 s)."""
    iid = seed_item(engine, esl_root, "COMPARE")
    _delete(app_ctx, "COMPARE", iid)
    assert len(trash_names(esl_root)) == 1
    w = worker_factory()
    assert w.settings.item_delete.purge_interval_s == 0.2
    w.start()
    try:
        wait_for(lambda: trash_names(esl_root) == [] and deletion_row(engine, "COMPARE", iid)["purge_state"] == "PURGED",
                 timeout=20)
        iid2 = seed_item(engine, esl_root, "OPT")                         # 이후에 삭제한 것도 다음 주기에
        _delete(app_ctx, "OPT", iid2)
        wait_for(lambda: trash_names(esl_root) == [], timeout=20)
    finally:
        w.stop()


def test_purge_trash_swallows_errors(app_ctx, worker_factory, monkeypatch):
    from esl_worker import trash_purge

    w = worker_factory()
    monkeypatch.setattr(trash_purge, "purge_once", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert w.purge_trash() is None
    assert w._purge_tick() is None                                        # 루프용: 항상 None(쉬지 않고 도는 것 방지)


def test_missing_or_linked_trash_dir_is_noop(app_ctx, worker_factory, esl_root, tmp_path):
    w = worker_factory()
    assert w.purge_trash().purged == 0 and not (esl_root / "_trash").exists()   # _trash 를 만들지 않음
    outside = tmp_path / "ext"
    outside.mkdir()
    (outside / "x").write_text("x")
    os.symlink(outside, esl_root / "_trash", target_is_directory=True)
    assert w.purge_trash().purged == 0 and (outside / "x").is_file()
