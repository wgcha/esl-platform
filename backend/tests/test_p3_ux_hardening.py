"""P3-UX 보안 강화(Verifier 결함 수정): 버전 원천(VERSION/BUILD.json), complete 의 업로드 밖 include 메시지 통일,
업로드 하드 링크 거부, 찾아보기·Case 입력의 업로드 폴더 격리(본인 폴더만, `_backup` 거부).
연결 코드 잠금의 X-Forwarded-For 우회(uvicorn proxy_headers)는 tests/deploy/test_deploy_service.py(실제 uvicorn 기동)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from esl_test_support import API, REPO, H, create_case
from test_p3_ux import RESULTS, W, create, mini_rad_text, put, send_all, settings_dict, upload_root  # noqa: F401

R = H("tok-power")
R2 = H("tok-power2")
RA = H("tok-admin")


def _code(r):
    return r.json()["detail"]["code"]


# ---------------------------------------------------------------- 버전
def test_version_from_version_file_and_build_json(client, tmp_path):
    import esl_platform

    ver = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    assert esl_platform.__version__ == ver == "0.8.0"
    assert client.get(f"{API}/health").json()["version"] == ver
    assert client.get(f"{API}/openapi.json").json()["info"]["version"] == ver
    oa = json.loads((REPO / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    assert oa["info"]["version"] == ver
    # 설치 런타임: BUILD.json 우선, 없으면 VERSION, 둘 다 없으면 0.0.0
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    assert esl_platform.read_version(tmp_path) == "1.2.3"
    (tmp_path / "BUILD.json").write_text(json.dumps({"version": "2.0.0", "commit": "abc1234"}), encoding="utf-8")
    assert esl_platform.read_version(tmp_path) == "2.0.0"
    (tmp_path / "BUILD.json").write_text("{broken", encoding="utf-8")
    assert esl_platform.read_version(tmp_path) == "1.2.3"
    assert esl_platform.read_version(tmp_path / "none") == "0.0.0"


# ---------------------------------------------------------------- complete: 업로드 밖 include
def _complete_with_include(client, inc: str, name: str) -> dict:
    files = {"rad/m_0000.rad": mini_rad_text(include=inc), **RESULTS}
    up = create(client, files, name=name).json()
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)
    return c


def test_complete_outside_include_same_message(client, tmp_path):
    outside = tmp_path / "outside"
    (outside / "nest.inc").write_text(f"#include {outside / 'deeper.inc'}\n")       # 밖 파일 안은 따라가지 않음
    cases = [str(outside / "secret.txt"), str(outside / "nope.inc"), str(outside / "nest.inc"),
             "../../../../../../../../etc/hostname", "../../../../../../../../etc/nonexistent_zz"]
    results = [_complete_with_include(client, inc, f"inc{i}") for i, inc in enumerate(cases)]
    for inc, c in zip(cases, results):
        assert not c["ok"] and c["missing_includes"] == [] and c["parts"] == [], c
        assert c["problems"] == [f"업로드에 포함되지 않은 include: {inc}"], c
    # 존재 여부(secret.txt 있음 / nope.inc 없음)로 응답 모양이 달라지지 않음
    shape = [{k: v for k, v in c.items() if k not in ("problems", "upload_id", "dir_path", "rad_path", "results_dir",
                                                       "files", "created_at", "updated_at")} for c in results]
    assert all(s == shape[0] for s in shape)
    # 업로드 안의 누락 include 는 그대로 missing_includes(추가 업로드 안내)
    c = _complete_with_include(client, "inc/extra.inc", "inside")
    assert c["missing_includes"] == ["rad/inc/extra.inc"] and c["problems"] == []


def test_scan_include_refs_follow():
    from esl.rad import scan_include_refs, scan_includes

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.rad").write_text("#include b.inc\n#include none.inc\n/END\n")
        Path(d, "b.inc").write_text("#include c.inc\n")
        Path(d, "c.inc").write_text("x\n")
        refs = scan_include_refs(os.path.join(d, "a.rad"))
        assert [(r["spec"], r["found"]) for r in refs] == [("b.inc", True), ("c.inc", True), ("none.inc", False)]
        refs = scan_include_refs(os.path.join(d, "a.rad"), follow=lambda p: not p.endswith("b.inc"))
        assert [r["spec"] for r in refs] == ["b.inc", "none.inc"]
        assert scan_includes(os.path.join(d, "a.rad")) == [os.path.join(d, n) for n in ("b.inc", "c.inc", "none.inc")]


# ---------------------------------------------------------------- 하드 링크
def test_hardlink_part_and_target_rejected(client, tmp_path):
    victim = tmp_path / "outside" / "hl.txt"
    victim.write_bytes(b"abc")
    up = create(client, {"rad/sub/x.rad": b"abcdef"}, name="hl").json()
    d = Path(up["dir_path"])
    os.link(victim, d / "rad" / "sub" / "x.rad.part")
    r = put(client, up["upload_id"], 0, 0, b"PWNPWN")
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE", r.text
    assert victim.read_bytes() == b"abc"
    os.unlink(d / "rad" / "sub" / "x.rad.part")
    # 최종 이름 자리에 하드 링크 → 거부(밖 파일 그대로)
    os.link(victim, d / "rad" / "sub" / "x.rad")
    r = put(client, up["upload_id"], 0, 0, b"abcdef")
    assert r.status_code in (409, 422), r.text
    assert victim.read_bytes() == b"abc"


def test_append_chunk_excl_and_checks(tmp_path):
    from esl_platform.core import uploads as U
    from esl_platform.core.errors import DomainError

    p = tmp_path / "f.part"
    U.append_chunk(str(p), b"ab", str(tmp_path))        # 새 파일(O_EXCL)
    U.append_chunk(str(p), b"cd", str(tmp_path))        # 기존 일반 파일(링크 수 1)
    assert p.read_bytes() == b"abcd"
    other = tmp_path / "other"
    other.write_bytes(b"x")
    hl = tmp_path / "hl.part"
    os.link(other, hl)
    with pytest.raises(DomainError) as e:
        U.append_chunk(str(hl), b"y", str(tmp_path))
    assert e.value.code == "PATH_UNSAFE" and other.read_bytes() == b"x"
    fifo = tmp_path / "fifo.part"
    os.mkfifo(fifo)
    with pytest.raises(DomainError):
        U.target_path(str(tmp_path), ["fifo"])
    with pytest.raises(DomainError):
        U.target_path(str(tmp_path), ["hl"])            # hl.part 가 하드 링크


# ---------------------------------------------------------------- 찾아보기·Case 입력 격리
def _upload_root_index(client) -> int:
    return next(r["index"] for r in client.get(f"{API}/fs/browse", headers=R).json()["roots"] if r["kind"] == "upload")


def test_browse_upload_root_isolation(client, upload_root):
    for u in ("power", "power2"):
        (upload_root / u / "20260101-000000_m" / "_backup").mkdir(parents=True)
        (upload_root / u / "20260101-000000_m" / "a.rad").write_text("x")
    (upload_root / "_backup" / "power").mkdir(parents=True)
    (upload_root / "loose.txt").write_text("x")
    ui = _upload_root_index(client)
    names = lambda h, p="": [e["name"] for e in client.get(f"{API}/fs/browse", params={"root": ui, "path": p},  # noqa: E731
                                                           headers=h).json()["entries"]]
    assert names(R) == ["power"] and names(R2) == ["power2"]
    assert sorted(names(RA)) == ["loose.txt", "power", "power2"]                       # 관리자는 전체(_backup 제외)
    assert names(R, "power/20260101-000000_m") == ["a.rad"]                            # 깊은 _backup 도 목록 제외
    for h, path, code in [(R, "power2", "UPLOAD_FOLDER_FORBIDDEN"), (R, "power2/20260101-000000_m", "UPLOAD_FOLDER_FORBIDDEN"),
                          (R, "_backup", "PATH_UNSAFE"), (R, "power/20260101-000000_m/_backup", "PATH_UNSAFE"),
                          (RA, "_backup/power", "PATH_UNSAFE"), (RA, "power/20260101-000000_m/_BACKUP", "PATH_UNSAFE")]:
        r = client.get(f"{API}/fs/browse", params={"root": ui, "path": path}, headers=h)
        assert r.status_code in (403, 404, 422) and r.status_code != 200, (path, r.text)
        if r.status_code != 404:
            assert _code(r) == code, (path, r.text)
    assert names(RA, "power2/20260101-000000_m") == ["a.rad"]


def test_case_input_from_other_users_upload_rejected(client, upload_root):
    files = {"rad/m_0000.rad": mini_rad_text(), **RESULTS}
    up = create(client, files, token="tok-power2", name="p2").json()
    send_all_as(client, up, files, "tok-power2")
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=H("tok-power2", True)).json()
    assert c["ok"], c
    src = {"rad": c["rad_path"], "csv": c["results_dir"]}
    r = create_case(client, src, folder="steal", part_title="Chassis rear")                 # power → power2 폴더
    assert r.status_code == 403 and _code(r) == "UPLOAD_FOLDER_FORBIDDEN", r.text
    r = client.post(f"{API}/paths/inspect", json={"purpose": "RAD", "path": c["rad_path"]},
                    headers=W)
    assert r.status_code == 403 and _code(r) == "UPLOAD_FOLDER_FORBIDDEN", r.text
    r = create_case(client, src, folder="own", part_title="Chassis rear", token="tok-power2")  # 본인
    assert r.status_code == 201, r.text
    r = create_case(client, src, folder="adm", title="관리자", part_title="Chassis rear", token="tok-admin")
    assert r.status_code == 201, r.text                                                       # 전역 관리자
    # _backup 아래는 누구도 입력으로 못 씀
    bk = upload_root / "_backup" / "power2" / "old"
    bk.mkdir(parents=True)
    (bk / "m_0000.rad").write_bytes(mini_rad_text())
    r = create_case(client, {"rad": str(bk / "m_0000.rad"), "csv": c["results_dir"]}, folder="bk",
                    title="백업", part_title="Chassis rear", token="tok-admin")
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE", r.text


def send_all_as(client, up: dict, files: dict[str, bytes], token: str) -> None:
    for f in up["files"]:
        data = files[f["rel"]]
        r = put(client, up["upload_id"], f["index"], 0, data, token=token)
        assert r.status_code == 200 and r.json()["done"], r.text
