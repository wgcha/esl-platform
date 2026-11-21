"""지그 준비 심링크 가드(v0.24.4) — 01_extract·_backup·_jig·_jig/fixed_tmp·jig_fixed 가 밖을 가리키는 링크여도 밖 내용 불변."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from test_jig_prep import _fake_ex, _scan_ok, patched  # noqa: F401 (patched = fixture)


def _tree(p) -> dict[str, str]:
    out = {}
    for d, _, fs in os.walk(p):
        for f in fs:
            q = os.path.join(d, f)
            with open(q, "rb") as fh:
                out[os.path.relpath(q, p)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _setup(monkeypatch, ex, patched_):
    from esl_worker import core_adapter, doe_jobs

    rad = ex.case["rad_path"]
    from esl_worker import jig_prep as jp
    monkeypatch.setattr(jp.doe_jobs.inproc, "call", lambda ex_, fn, **kw: fn())
    monkeypatch.setattr(core_adapter, "jig_model_files", lambda starter, roots, **k: [rad])
    monkeypatch.setattr(doe_jobs, "_fixed_scan", _scan_ok(patched_))


def _victim(tmp_path, meta=False):
    v = tmp_path / "victim"
    (v / "sub").mkdir(parents=True)
    (v / "sub" / "keep").write_text("keep")
    if meta:
        (v / "model_meta.json").write_text(json.dumps({"part_id": 7}))
    return v


def test_normal_then_backup_move(tmp_path, patched, monkeypatch):
    from esl_worker import jig_prep as jp

    ex = _fake_ex(tmp_path)
    _setup(monkeypatch, ex, patched)
    assert jp.run(ex, None, lambda m: None)["status"] == "ok"
    fd = Path(ex.cdir) / "01_extract" / "jig_fixed"
    assert sorted(p.name for p in fd.iterdir()) == ["fixed_nodes.json", "fixed_nodes.npz", "shell_scan.json"]
    os.utime(ex.case["rad_path"], ns=(1, 1))
    out2 = jp.run(ex, None, lambda m: None)
    assert out2["status"] == "ok" and any((Path(ex.cdir) / "_backup").rglob("jig_fixed"))


@pytest.mark.parametrize("link", ["01_extract", "_backup", "_jig", "_jig/fixed_tmp", "01_extract/jig_fixed"])
def test_links_leave_outside_untouched(tmp_path, patched, monkeypatch, link):
    from esl_worker import jig_prep as jp

    ex = _fake_ex(tmp_path)
    _setup(monkeypatch, ex, patched)
    cd = Path(ex.cdir)
    if link == "_backup":                       # 낡은 캐시가 있어야 백업 이동을 시도
        (cd / "01_extract" / "jig_fixed").mkdir()
        (cd / "01_extract" / "jig_fixed" / "old.json").write_text("{}")
    v = _victim(tmp_path, meta=(link == "01_extract"))
    tgt = cd / link
    if tgt.exists():
        shutil.rmtree(tgt)
    tgt.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(v, tgt)
    before = _tree(v)
    out = jp.run(ex, None, lambda m: None)
    assert _tree(v) == before
    if link == "01_extract":                    # jig_fixed 없음 + 01_extract 가 밖 링크: 실패 코드(사유 = 심링크) — ESL 은 계속
        assert out["status"] == "failed" and out["cause"] == "SYMLINK_PATH" and "심링크" in out["detail"]
        assert not (v / "jig_fixed").exists()
