"""#92 기존 드라이브 폴더 이름(한글·공백·괄호 등 ASCII 밖)은 읽기(기능 A)에서 막지 않는다. 어댑터 SEGMENT_RE(ASCII — esl·대시보드가
*새로 만드는* 프로젝트·잡 폴더 이름 규칙)는 쓰기(B)의 새 구간에만. 기본 안전 검사(제어문자·`\\`·빈 구간·`..`·`/` 시작·길이)는 그대로."""

from __future__ import annotations

import pytest
from esl_test_support import API, H
from scx_support import put

from esl_platform.core.config import load_config_dict
from esl_platform.core.scx import paths

ISSUE_FAIL = "공유 폴더/pbsadmin/SPDM/SPDM/PROJ-000099_R95J개발과제"
ISSUE_OK = ("공유 폴더/junes.jeon/75r9j_case002_Linear_damp/75r9j_case002/CUMULATIVE_NODAMP/"
            "19_Corner_Drop_2nd_Scene11_Edge16_2nd/input_files")
SPDM = ["공유 폴더/pbsadmin/SPDM"]
HEALTH = {"forbidden_prefixes": SPDM, "relay_base": ""}


@pytest.fixture()
def settings_dict(settings_dict):
    d = dict(settings_dict)
    d["scx_drive"] = {**d["scx_drive"], "roots": [*d["scx_drive"]["roots"], {"key": "kor", "label": "공유", "rel": "공유 폴더"}]}
    return d


def _b(client, path="", root="kor"):
    return client.get(f"{API}/scx/browse", params={"project_id": "p-1", "root": root, "path": path}, headers=H("tok-power"))


@pytest.mark.parametrize("rel", [ISSUE_FAIL, ISSUE_OK, "홈/해석 모델(v2)/ref [1]/x"])
def test_read_allows_non_ascii_segments_per_segment(rel):
    segs = rel.split("/")
    for n in range(1, len(segs) + 1):                       # 구간 단위(이슈처럼 한 단계씩 들어가는 경로)
        assert paths.check_drive_rel("/".join(segs[:n]), HEALTH) == "/".join(segs[:n])


@pytest.mark.parametrize("bad", ["a/../b", "a\\b", "a/b\x07", "a//b", "/a/b", "~/a", "a/./b", ".hidden/a", "a/.git", "a/.숨김/b", "a/" + "한" * 256])
def test_read_still_rejects_unsafe(bad):
    with pytest.raises(Exception) as ei:
        paths.check_drive_rel(bad, HEALTH)
    assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED", bad


def test_write_new_segments_keep_segment_re_but_configured_base_may_be_non_ascii():
    new = "한글기지/p-1/VD1_20261030T000000"
    with pytest.raises(Exception) as ei:                                              # 기본(new_from 없음) = 이전 동작(전체 구간)
        paths.check_drive_rel(new, HEALTH, write=True)
    assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED"
    assert paths.check_drive_rel(new, HEALTH, write=True, new_from=1) == new          # 설정 drive_base 구간(1개)은 제외
    for bad in ("한글기지/프로젝트/VD1_20261030T000000", "한글기지/p-1/VD 1", "한글기지/p-1/VD1_한글"):
        with pytest.raises(Exception) as ei:                                          # 새 구간(프로젝트·잡)은 ASCII 규칙 그대로
            paths.check_drive_rel(bad, HEALTH, write=True, new_from=1)
        assert getattr(ei.value, "code", "") == "SCX_PATH_NOT_ALLOWED", bad
    with pytest.raises(Exception):                                                    # SPDM 쓰기 금지도 그대로
        paths.check_drive_rel("공유 폴더/pbsadmin/SPDM/p-1/VD1_20261030T000000", HEALTH, write=True, new_from=3)


def test_job_new_from_counts_drive_base_segments(monkeypatch):
    from types import SimpleNamespace

    from esl_platform.core.scx import settings as scx_settings

    for base, n in (("~", 0), ("~/esl", 1), ("~/한글/esl", 2)):
        monkeypatch.setattr(scx_settings, "scx_cfg", lambda s, base=base: SimpleNamespace(drive_base=base))
        assert paths.job_new_from(None) == n


def test_settings_root_rel_non_ascii_allowed(settings_dict):
    from esl_platform.core.scx.settings import drive_problems

    lc = load_config_dict(settings_dict, environ={})
    assert lc.ok, lc.errors()
    assert drive_problems(lc.settings) == []                                           # 한글·공백 rel 허용
    for bad in ("공유 폴더/../x", ".숨김/x", "공유 폴더/.git", "공유\\폴더"):
        d = dict(settings_dict)
        d["scx_drive"] = {**d["scx_drive"], "roots": [{"key": "x", "label": "x", "rel": bad}]}
        lc = load_config_dict(d, environ={})
        assert any("roots[0].rel" in p for p in drive_problems(lc.settings)), bad


def test_browse_issue_paths_reach_relay(client, fake_relay):
    put(fake_relay, f"{ISSUE_FAIL}/모델 (1)/a_0000.rad", b"x")
    put(fake_relay, f"{ISSUE_OK}/b_0000.rad", b"x")
    r = _b(client, "pbsadmin/SPDM/SPDM/PROJ-000099_R95J개발과제")
    assert r.status_code == 200, r.text
    assert [e["name"] for e in r.json()["entries"]] == ["모델 (1)"]
    r = _b(client, "pbsadmin/SPDM/SPDM/PROJ-000099_R95J개발과제/모델 (1)")
    assert [e["name"] for e in r.json()["entries"]] == ["a_0000.rad"] and r.json()["entries"][0]["hint"] == "rad"
    assert _b(client, ISSUE_OK.split("/", 1)[1]).status_code == 200


def test_spdm_subpath_read_is_decided_by_relay_not_esl(client, fake_relay):
    fake_relay.forbidden_prefixes = list(SPDM)
    put(fake_relay, f"{ISSUE_FAIL}/x_0000.rad", b"x")
    r = _b(client, "pbsadmin/SPDM/SPDM/PROJ-000099_R95J개발과제")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SCX_PATH_NOT_ALLOWED"
    assert fake_relay.calls("/list")                                                   # esl 이 막지 않고 relay 까지 감
    assert "형식 오류" not in r.json()["detail"]["message"]
