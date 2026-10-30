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
