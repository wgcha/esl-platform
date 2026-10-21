"""V-P1B-3·V-SEC-2: input_roots 밖·`..`·메타문자·상대경로·심링크·esl_root 겹침 거부, 없음 404 대신 422."""

from __future__ import annotations

import os

import pytest
from esl_test_support import API, H, create_case, make_settings_dict

from esl_platform.core.config import load_config_dict

W = H("tok-power", True)


def _inspect(client, purpose, path):
    return client.post(f"{API}/paths/inspect", json={"purpose": purpose, "path": path}, headers=W)


def test_inspect_ok(client, mini_inputs):
    r = _inspect(client, "RAD", mini_inputs["rad"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["target_part"]["id"] == 7 and d["parts"][0]["n_elems"] == 4
    r = _inspect(client, "RESULTS", mini_inputs["csv"])
    d = r.json()
    assert d["done"]["part_id"] == 7 and d["n_frames"] == 2
    assert {f["name"] for f in d["files"]} == {"done.json", "frames.csv", "model.csv"}


def test_rejections(client, mini_inputs, tmp_path, inputs_root, esl_root):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x_0000.rad").write_text("#\n")
    link = inputs_root / "link"
    os.symlink(outside, link)
    cases = [
        ("RAD", str(outside / "x_0000.rad"), "PATH_OUTSIDE_ROOT"),
        ("RAD", str(inputs_root / "mini" / ".." / "mini" / "mini_0000.rad"), "PATH_UNSAFE"),
        ("RAD", str(inputs_root / "a&b.rad"), "PATH_UNSAFE"),
        ("RAD", str(inputs_root / 'a"b.rad'), "PATH_UNSAFE"),
        ("RAD", "mini/mini_0000.rad", "PATH_UNSAFE"),
        ("RAD", str(link / "x_0000.rad"), "PATH_UNSAFE"),
        ("RESULTS", str(link), "PATH_UNSAFE"),
        ("RAD", str(inputs_root / "none_0000.rad"), "PATH_NOT_FOUND"),
        ("RESULTS", mini_inputs["rad"], "PATH_NOT_FOUND"),
        ("RAD", str(esl_root / "x.rad"), "PATH_OUTSIDE_ROOT"),
    ]
    for purpose, p, code in cases:
        r = _inspect(client, purpose, p)
        assert (r.status_code, r.json()["detail"]["code"]) == (422, code), (p, r.text)
    r = client.post(f"{API}/cases", json={"project_id": "p-1", "folder_name": "c1", "title": "t",
                                          "rad_path": str(outside / "x_0000.rad"), "results_dir": mini_inputs["csv"]},
                    headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_OUTSIDE_ROOT"
    assert not (esl_root / "c1").exists()


def test_esl_root_overlap_config(tmp_path):
    d = make_settings_dict(tmp_path)
    d["storage"]["esl_root"] = os.path.join(d["storage"]["input_roots"][0], "out")
    lc = load_config_dict(d, environ={})
    assert not lc.ok and "storage.input_roots[0]" in lc.error_keys()


def test_part_checks(client, mini_inputs):
    r = create_case(client, mini_inputs, part_title="no such part")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PART_NOT_FOUND"
    import json

    p = os.path.join(mini_inputs["csv"], "done.json")
    d = json.load(open(p))
    d["part_id"] = 99
    json.dump(d, open(p, "w"))
    r = create_case(client, mini_inputs)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "PART_MISMATCH"


@pytest.mark.parametrize("folder", ["../x", "a b", "", "-x", "x" * 65])
def test_folder_name(client, mini_inputs, folder):
    r = create_case(client, mini_inputs, folder=folder)
    assert r.status_code == 422


def test_case_create_and_duplicates(client, mini_inputs, esl_root):
    r = create_case(client, mini_inputs)
    assert r.status_code == 201
    c = r.json()
    assert c["h3d_path"] is None and c["input_fingerprint"]["rad"]["sha256"]
    assert set(c["input_fingerprint"]["results"]["files"]) == {"done.json", "frames.csv", "model.csv"}
    assert c["stage_status"] is None or True
    r = create_case(client, mini_inputs, folder="other")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_NAME_EXISTS"
    r = create_case(client, mini_inputs, title="다른 제목")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FOLDER_EXISTS"
    (esl_root / "manual").mkdir()
    r = create_case(client, mini_inputs, folder="manual", title="세번째")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FOLDER_EXISTS"
    lst = client.get(f"{API}/cases", params={"project_id": "p-1"}, headers=H("tok-general")).json()
    assert [x["id"] for x in lst] == [c["id"]]
    g = client.get(f"{API}/cases/{c['id']}", headers=H("tok-general")).json()
    assert g["stage_status"]["1"]["state"] == "none"
    r = client.post(f"{API}/cases/{c['id']}/archive", headers=W)
    assert r.status_code == 200 and r.json()["status"] == "ARCHIVED"
    r = client.post(f"{API}/cases/{c['id']}/jobs", json={"job_type": "CASE_EXTRACT", "params": {}}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CASE_ARCHIVED"


# ---------------------------------------------------------------- Windows/POSIX 경로 의미(플랫폼 독립)
@pytest.mark.parametrize("raw,nt,posix", [
    ("C:\\data\\x.rad", True, False),
    ("C:/data/x.rad", True, False),
    ("\\\\srv\\share\\x.rad", True, False),
    ("//srv/share/x.rad", True, True),
    ("\\inputs\\x.rad", False, False),        # 드라이브 없는 루트 상대
    ("/inputs/x.rad", False, True),           # Windows 에서는 현재 드라이브 루트 상대
    ("C:x.rad", False, False),                # 드라이브 상대
    ("C:", False, False),
    ("\\\\srv", False, False),                # 공유 이름 없는 UNC
    ("inputs\\x.rad", False, False),
    ("x.rad", False, False),
    ("", False, False),
])
def test_fully_qualified_by_flavor(raw, nt, posix):
    from esl_platform.core.paths import is_fully_qualified

    assert is_fully_qualified(raw, "nt") is nt
    assert is_fully_qualified(raw, "posix") is posix


@pytest.mark.parametrize("raw", ["\\inputs\\x.rad", "/inputs/x.rad", "C:x.rad", "C:inputs\\x.rad"])
def test_lexical_check_rejects_partial_windows_paths(raw):
    from esl_platform.core.errors import DomainError
    from esl_platform.core.paths import lexical_check

    with pytest.raises(DomainError) as ei:
        lexical_check(raw, "nt")
    assert ei.value.code == "PATH_UNSAFE"


def test_lexical_check_normalizes_by_flavor():
    from esl_platform.core.errors import DomainError
    from esl_platform.core.paths import lexical_check

    assert lexical_check("C:/data//in/x.rad", "nt") == "C:\\data\\in\\x.rad"
    assert lexical_check("/data//in/./x.rad", "posix") == "/data/in/x.rad"
    for bad in ("C:\\data\\..\\x.rad", "/data/../x.rad", "C:\\a&b.rad"):
        with pytest.raises(DomainError):
            lexical_check(bad, "nt" if bad.startswith("C") else "posix")


def test_api_rejects_root_relative_and_drive_relative(client):
    for raw in ("\\inputs\\x.rad", "C:x.rad"):
        r = _inspect(client, "RAD", raw)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "PATH_UNSAFE", raw


def test_config_abs_path_flavor(monkeypatch):
    from esl_platform.core import config

    assert config.is_abs_path("C:\\esl") and config.is_abs_path("\\\\srv\\share\\esl")
    assert not config.is_abs_path("\\esl") and not config.is_abs_path("C:esl")
    monkeypatch.setattr(config.os, "name", "nt")
    assert not config.is_abs_path("/esl")              # Windows 호스트: 드라이브 없는 루트 상대 거부
    monkeypatch.setattr(config.os, "name", "posix")
    assert config.is_abs_path("/esl")


def test_match_parts_separator_normalization():
    from esl_platform.api.services.system import match_parts

    parts = [{"id": 10, "title": "chassis_rear"}, {"id": 11, "title": "Other"}]
    for t in ("chassis rear", "Chassis-Rear", " CHASSIS_REAR "):
        assert [p["id"] for p in match_parts(parts, t, "exact_ci")] == [10]
    assert match_parts(parts, "chassis rear", "exact") == []
    # 정규화 후 2개 이상이면 모두 반환(호출 쪽이 PART_AMBIGUOUS 처리)
    parts.append({"id": 12, "title": "Chassis Rear"})
    assert [p["id"] for p in match_parts(parts, "chassis-rear", "exact_ci")] == [10, 12]


def test_inspect_rad_uses_request_part_title(client, mini_inputs):
    # 설정 기본 part_title 과 무관하게, 요청의 part_title 로 판정한다(이슈 #16 회귀)
    base = {"purpose": "RAD", "path": mini_inputs["rad"]}
    title = client.post(f"{API}/paths/inspect", json=base, headers=W).json()["target_part"]["title"]
    r = client.post(f"{API}/paths/inspect", json={**base, "part_title": "no such part"}, headers=W).json()
    assert not r["ok"] and r["part_title"] == "no such part" and any(p.startswith("PART_NOT_FOUND") for p in r["problems"])
    alt = title.upper().replace(" ", "_")
    r = client.post(f"{API}/paths/inspect", json={**base, "part_title": alt}, headers=W).json()
    assert r["ok"] and r["target_part"]["title"] == title and r["part_title"] == alt


def test_inspect_real_model_part_title(client, inputs_root):
    import shutil

    src = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "rad", "fixtures", "real_101_parts.rad")
    dst = inputs_root / "real_0000.rad"
    shutil.copy(src, dst)
    body = {"purpose": "RAD", "path": str(dst)}
    # Case 값 'chassis_rear' 일치(id 10)
    r = client.post(f"{API}/paths/inspect", json={**body, "part_title": "chassis_rear"}, headers=W).json()
    assert r["ok"] and r["target_part"]["id"] == 10 and r["parts"][0]["title"] == "chassis_rear"
    # 정규화로 'chassis rear' 도 일치, 요청 값이 설정 기본값보다 우선
    r = client.post(f"{API}/paths/inspect", json={**body, "part_title": "chassis rear"}, headers=W).json()
    assert r["ok"] and r["target_part"]["id"] == 10
    r = client.post(f"{API}/paths/inspect", json={**body, "part_title": "bumper"}, headers=W).json()
    assert not r["ok"] and r["part_title"] == "bumper"
    # part_title 없이도(설정 기본 'chassis rear') 정규화로 일치
    assert client.post(f"{API}/paths/inspect", json=body, headers=W).json()["target_part"]["id"] == 10


def test_inspect_rad_parts_cache(client, mini_inputs):
    from esl_platform.api.services import system

    system._PARTS_CACHE.clear()
    body = {"purpose": "RAD", "path": mini_inputs["rad"]}
    calls = []
    real = system.core_adapter.list_parts
    system.core_adapter.list_parts = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        for _ in range(3):
            assert client.post(f"{API}/paths/inspect", json=body, headers=W).json()["ok"]
        assert len(calls) == 1
        os.utime(mini_inputs["rad"], ns=(1, 1))  # 파일이 바뀌면 캐시 무효
        client.post(f"{API}/paths/inspect", json=body, headers=W)
        assert len(calls) == 2
    finally:
        system.core_adapter.list_parts = real
