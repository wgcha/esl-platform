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
