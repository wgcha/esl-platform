"""환경 점검 check_scx(계약 esl_scx_relay.md §13): 어댑터·lock 일치, hpc.scx 검증, 비밀 파일 형식·권한(값 출력 없음), 릴레이
health·max_download_bytes 경고, XFER 레인 수. 설정이 없으면 SKIP."""

from __future__ import annotations

import json
import os

from esl_platform.check import FAIL, OK, SKIP, WARN, check_scx, secret_acl_wide
from esl_platform.core.config import load_config_dict


def _s(d):
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    return lc.settings


def test_check_scx_ok_and_warnings(settings_dict, fake_relay, tmp_path):
    sec = settings_dict["hpc"]["scx"]["secret_file"]
    os.chmod(sec, 0o600)
    items = {i.key: i for i in check_scx(_s(settings_dict), "linux")}
    assert items["scx.adapter"].status == OK and "a363a89e8f93" in items["scx.adapter"].detail
    assert items["hpc.scx"].status == OK and items["hpc.scx.secret_file"].status == OK
    assert items["scx.relay"].status == OK and items["worker.xfer_lanes"].status == OK
    # 대시보드 상한(20 GiB) < hpc.scx.max_download_bytes(64 GiB) → 경고
    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["scx"]["max_download_bytes"] = 64 * 1024 ** 3
    items = {i.key: i for i in check_scx(_s(d), "linux")}
    assert items["scx.relay.max_download_bytes"].status == WARN
    # 비밀 파일 권한 넓음 → 경고(값은 출력하지 않음)
    os.chmod(sec, 0o644)
    items = check_scx(_s(settings_dict), "linux")
    it = next(i for i in items if i.key == "hpc.scx.secret_file")
    assert it.status == WARN and "SCX_SECRET_ACL_WIDE" in it.detail
    assert all(fake_relay.secret not in i.detail for i in items)
    assert not any(i.status == FAIL for i in items)
    assert secret_acl_wide(sec, "linux")[0] is True


def test_check_scx_skip_and_down(settings_dict, fake_relay):
    d = json.loads(json.dumps(settings_dict))
    d.pop("hpc")
    d["scx_drive"]["enabled"] = False
    assert [i.status for i in check_scx(_s(d), "linux")] == [SKIP]
    fake_relay.stop()
    items = {i.key: i for i in check_scx(_s(settings_dict), "linux")}
    assert items["scx.relay"].status == WARN and "SCX_RELAY_UNREACHABLE" in items["scx.relay"].detail


def test_check_scx_both_disabled_skips_relay_and_drive_line(settings_dict, fake_relay):
    """scx_drive·verify_drop 둘 다 꺼짐 → evaluate 가 릴레이를 시험하지 않으므로 scx.relay = SKIP(VD_DISABLED WARN 아님)."""
    d = json.loads(json.dumps(settings_dict))
    d["scx_drive"]["enabled"] = False
    d.setdefault("verify_drop", {})["enabled"] = False
    items = {i.key: i for i in check_scx(_s(d), "linux")}
    assert items["scx.relay"].status == SKIP
    assert items["scx.relay"].detail == "SCX 드라이브·검증 낙하 모두 꺼짐(scx_drive.enabled·verify_drop.enabled)"
    assert all("_DISABLED" not in i.detail for i in items.values())
    n = len(d["scx_drive"].get("roots") or [])
    assert items["scx_drive.enabled"].status == OK and items["scx_drive.enabled"].detail.startswith(f"꺼짐 — roots {n}개")


def test_check_scx_relay_down_reports_common_cause_not_disabled(settings_dict, fake_relay):
    """하나라도 켜져 있으면 켜진 쪽의 실제 공통 원인(SCX_RELAY_UNREACHABLE)을 표시 — *_DISABLED 코드는 쓰지 않는다."""
    fake_relay.stop()
    for fetch_on, verify_on in ((True, False), (False, True), (True, True)):
        d = json.loads(json.dumps(settings_dict))
        d["scx_drive"]["enabled"] = fetch_on
        d.setdefault("verify_drop", {})["enabled"] = verify_on
        items = {i.key: i for i in check_scx(_s(d), "linux")}
        rel = items["scx.relay"]
        assert rel.status == WARN and rel.detail.startswith("SCX_RELAY_UNREACHABLE:"), (fetch_on, verify_on, rel.detail)
        assert "_DISABLED" not in rel.detail
        assert items["scx_drive.enabled"].detail.startswith("켜짐" if fetch_on else "꺼짐")


def test_misplaced_top_level_keys_under_hpc_warn(settings_dict, tmp_path):
    """hpc(extra ignore) 밑에 들여쓴 esl 최상위 키(hpc.scx_drive·hpc.scx.verify_drop)는 조용히 무시되므로 설정 검증·환경 점검
    config.valid 에 WARN. physicsai 공용 키(hpc.mode·hpc.scx.mpi 등)는 계속 무시(경고 없음)."""
    import importlib.util
    import pathlib

    import yaml

    from esl_platform import check
    from esl_platform.core.config import misplaced_top_keys

    d = json.loads(json.dumps(settings_dict))
    d["hpc"]["mode"] = "local"                         # physicsai 공용 키 → 무시
    assert misplaced_top_keys(d) == [] and _s(d) is not None
    d["hpc"]["scx_drive"] = d.pop("scx_drive")          # 실서버 사례: 최상위 키를 hpc 밑에 들여씀
    d["hpc"]["scx"]["verify_drop"] = {"enabled": True}
    lc = load_config_dict(d, environ={})
    assert lc.ok                                       # 기동·검증은 통과(무시됨) — 경고만
    assert [w.key for w in lc.warnings] == ["hpc.scx_drive", "hpc.scx.verify_drop"]
    assert lc.warnings[0].message == "hpc.scx_drive 는 최상위 키입니다 — 들여쓰기를 없애세요(지금은 무시됨)"
    assert lc.settings.scx_drive.enabled is False      # 무시되어 기본값
    p = tmp_path / "esl_platform.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    items = {i.key: i for i in check.run_checks(str(p), use_db=False, platform="linux")}
    assert items["config.valid"].status == WARN and "hpc.scx_drive 는 최상위 키입니다" in items["config.valid"].detail
    # 설치 스크립트용 설정 검증 JSON(setup_config.py validate)에도 warnings
    sp = pathlib.Path(__file__).resolve().parents[3] / "deploy" / "setup_config.py"
    import sys

    spec = importlib.util.spec_from_file_location("setup_config_t", sp)
    mod = importlib.util.module_from_spec(spec)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True      # deploy/ 에 __pycache__ 를 남기지 않음(정적 시험)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    v = mod.validate(str(p))
    assert any(w.startswith("hpc.scx_drive: ") for w in v["warnings"])
