"""P3-UX(계약 esl_p3_ux.md §5): 브라우저 분할 업로드·서버 폴더 찾아보기·결과 zip·버전.

업로드: 청크 순서·이어 올리기·청크/파일 sha256·용량·여유 공간·확장자·이름 공격(.., 절대경로, 예약어, 심링크)·권한·CSRF·
업로드 폴더 밖 쓰기 0·complete 검사(누락 include, h3d)·stale 정리(_backup 이동)·취소.
browse: 루트 밖 탈출 불가·심링크·숨김·페이지네이션·hint·spdm 옵션. bundle: zip 내용·raw·크기 상한·경로 탈출.
버전: VERSION↔CHANGELOG 최상단 일치, BUILD.json·git 해시, API.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest
from esl_test_support import API, REPO, H, create_case, make_settings_dict
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path, ui={"max_bundle_bytes": 50_000, "browse_page_max": 50})
    d["storage"]["upload_root"] = str(tmp_path / "esl-input")
    d["upload"] = {"chunk_mb": 1, "max_file_bytes": 3_000_000, "max_upload_bytes": 5_000_000, "min_free_gb": 0}
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.txt").write_text("outside")
    return d


@pytest.fixture()
def upload_root(settings_dict) -> Path:
    return Path(settings_dict["storage"]["upload_root"])


def _code(r):
    return r.json()["detail"]["code"]


# ---------------------------------------------------------------- 입력 만들기
def mini_rad_text(include: str | None = None) -> bytes:
    from esl.rad import write_rad

    import tempfile

    xs = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], float) * 10.0
    conn = np.array([[1, 4, 5, 2], [2, 5, 6, 3], [4, 7, 8, 5], [5, 8, 9, 6]], dtype=np.int64)
    with tempfile.TemporaryDirectory() as d:
        p = write_rad(os.path.join(d, "m_0000.rad"), np.arange(1, 10), xs, np.arange(101, 105),
                      np.full(4, 4, np.int8), conn, 7, "Chassis rear", 70, 2.0, 700, 2.1e5, 0.3)
        lines = Path(p).read_text().splitlines()
    if include:
        i = next(k for k, ln in enumerate(lines) if ln.startswith("/END"))
        lines.insert(i, f"#include {include}")
    return ("\n".join(lines) + "\n").encode()


RESULTS = {
    "results/out/done.json": json.dumps({"ok": True, "n_frames": 2, "part_id": 7, "warnings": []}).encode(),
    "results/out/frames.csv": b"frame_index,time\n0,0.0\n1,0.001\n",
    "results/out/model.csv": b"node_id,x0,y0,z0\n" + b"".join(
        f"{i + 1},{(i // 3) * 10.0},{(i % 3) * 10.0},0.0\n".encode() for i in range(9)),
}


def spec(files: dict[str, bytes], sha: bool = True) -> list[dict]:
    return [{"rel": k, "size": len(v), **({"sha256": hashlib.sha256(v).hexdigest()} if sha else {})}
            for k, v in files.items()]


def create(client, files: dict[str, bytes], name: str = "모델 A", token: str = "tok-power", **kw):
    body = {"project_id": "p-1", "name": name, "files": kw.pop("file_spec", None) or spec(files)}
    return client.post(f"{API}/uploads", json=body, headers=H(token, True))


def put(client, uid: str, index: int, offset: int, data: bytes, token: str = "tok-power", chunk_sha: bool = True,
        **hdr):
    h = {**H(token, True), "Content-Type": "application/octet-stream", **hdr}
    if chunk_sha:
        h["X-Chunk-Sha256"] = hashlib.sha256(data).hexdigest()
    return client.put(f"{API}/uploads/{uid}/files/{index}", params={"offset": offset}, content=data, headers=h)


def send_all(client, up: dict, files: dict[str, bytes]) -> None:
    cs = up["chunk_size"]
    for f in up["files"]:
        data = files[f["rel"]]
        off = f["received"]
        while off < len(data) or (not data and not f["done"]):
            r = put(client, up["upload_id"], f["index"], off, data[off:off + cs])
            assert r.status_code == 200, r.text
            off = r.json()["received"]
            if r.json()["done"]:
                break


def all_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- 업로드: 정상 흐름 → Case 생성
def test_upload_happy_path_and_case(client, upload_root, tmp_path):
    files = {"rad/m_0000.rad": mini_rad_text(), **RESULTS}
    r = create(client, files)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["state"] == "OPEN" and up["chunk_size"] == 1024 * 1024 and len(up["files"]) == 4
    d = Path(up["dir_path"])
    assert d.parent == upload_root / "power" and d.name.endswith("_모델_A") and d.name[:8].isdigit()
    send_all(client, up, files)
    g = client.get(f"{API}/uploads/{up['upload_id']}", headers=R).json()
    assert all(f["done"] and f["received"] == f["size"] for f in g["files"])
    assert g["files"][0]["sha256"] == hashlib.sha256(files["rad/m_0000.rad"]).hexdigest()
    r = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["ok"] and c["state"] == "COMPLETED" and c["missing_includes"] == [] and c["problems"] == []
    assert c["rad_path"] == str(d / "rad" / "m_0000.rad") and c["results_dir"] == str(d / "results" / "out")
    assert [p["title"] for p in c["parts"]] == ["Chassis rear"]
    assert not list(d.rglob("*.part"))
    # 완료 후 다시 complete = 같은 결과, PUT·DELETE 는 거부
    assert client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()["ok"]
    assert _code(put(client, up["upload_id"], 0, 0, b"x")) == "UPLOAD_CLOSED"
    assert _code(client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)) == "UPLOAD_COMPLETED"
    # 업로드 폴더는 input_roots 에 자동 포함 → 그대로 Case 입력
    r = create_case(client, {"rad": c["rad_path"], "csv": c["results_dir"]}, folder="upcase", part_title="Chassis rear")
    assert r.status_code == 201, r.text
    # 업로드 루트 밖에는 아무것도 쓰지 않음
    assert all_files(tmp_path / "outside") == {"secret.txt"}


def test_chunk_order_resume_and_chunk_sha(client):
    data = os.urandom(2_500_000)
    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/run.h3d": b"HYPER3D " + data}
    up = create(client, files).json()
    uid = up["upload_id"]
    h3d = files["h3d/run.h3d"]
    cs = up["chunk_size"]
    j = put(client, uid, 1, 0, h3d[:cs]).json()
    assert (j["index"], j["received"], j["received_total"], j["done"], j["duplicate"]) == (1, cs, cs, False, False)
    r = put(client, uid, 1, 0, h3d[:cs])                       # 같은 청크 다시 → 200 duplicate(프로토콜 2, 쓰지 않음)
    assert r.status_code == 200 and r.json()["duplicate"] is True and r.json()["received"] == cs
    r = put(client, uid, 1, cs + 10, h3d[cs + 10:cs + 20])     # 정렬 안 된 offset 거부
    assert r.status_code == 409 and _code(r) == "UPLOAD_OFFSET_MISMATCH" and r.json()["detail"]["received"] == cs
    # 청크 sha256 불일치 → 쓰지 않음
    r = put(client, uid, 1, cs, h3d[cs:2 * cs], chunk_sha=False, **{"X-Chunk-Sha256": "0" * 64})
    assert r.status_code == 422 and _code(r) == "CHUNK_SHA256_MISMATCH"
    # 중단 후 이어 올리기: 서버 해시 상태를 잃어도(재시작 흉내) 받은 크기에서 이어감
    from esl_platform.api.services import uploads as svc

    svc._HASHES.clear()
    g = client.get(f"{API}/uploads/{uid}", headers=R).json()
    assert g["files"][1]["received"] == cs and g["received_bytes"] == cs
    off = cs
    while off < len(h3d):
        r = put(client, uid, 1, off, h3d[off:off + cs])
        assert r.status_code == 200, r.text
        off = r.json()["received"]
    assert r.json()["done"] and r.json()["sha256"] == hashlib.sha256(h3d).hexdigest()
    # 청크 크기 초과
    up2 = create(client, {"rad/x_0000.rad": b"x" * 10}, name="b").json()
    r = put(client, up2["upload_id"], 0, 0, b"x" * (cs + 1))
    assert r.status_code == 413 and _code(r) == "CHUNK_TOO_LARGE"
    r = put(client, up2["upload_id"], 0, 0, b"x" * 11)
    assert r.status_code == 422 and _code(r) == "CHUNK_LENGTH_MISMATCH"
    r = client.put(f"{API}/uploads/{up2['upload_id']}/files/0", params={"offset": 0}, content=b"x",
                   headers={**W, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert put(client, up2["upload_id"], 5, 0, b"x").status_code == 404


def test_file_sha256_mismatch_moves_to_backup(client, upload_root):
    good = mini_rad_text()
    sp = [{"rel": "rad/m_0000.rad", "size": len(good), "sha256": "a" * 64}]
    up = create(client, {}, file_spec=sp).json()
    r = put(client, up["upload_id"], 0, 0, good)
    assert r.status_code == 422 and _code(r) == "SHA256_MISMATCH" and r.json()["detail"]["received"] == 0
    bk = Path(r.json()["detail"]["backup_path"])
    assert bk.is_file() and bk.read_bytes() == good and upload_root / "_backup" in bk.parents
    g = client.get(f"{API}/uploads/{up['upload_id']}", headers=R).json()
    assert g["files"][0]["received"] == 0 and not g["files"][0]["done"]


def test_limits_ext_and_free_space(client, app_ctx, monkeypatch):
    big = [{"rel": "h3d/a.h3d", "size": 3_000_001}]
    r = create(client, {}, file_spec=big)
    assert r.status_code == 413 and _code(r) == "UPLOAD_TOO_LARGE"
    tot = [{"rel": f"h3d/a{i}.h3d", "size": 2_000_000} for i in range(3)]
    assert _code(create(client, {}, file_spec=tot)) == "UPLOAD_TOO_LARGE"
    for rel in ("rad/a.exe", "rad/a.bat", "rad/noext", "results/x.npz"):
        r = create(client, {}, file_spec=[{"rel": rel, "size": 1}])
        assert r.status_code == 422 and _code(r) == "UPLOAD_EXT_NOT_ALLOWED", rel
    assert create(client, {}, file_spec=[{"rel": "h3d/ok.h3d", "size": 1}]).status_code == 201
    dup = [{"rel": "rad/A.rad", "size": 1}, {"rel": "rad/a.RAD", "size": 1}]
    assert _code(create(client, {}, file_spec=dup)) == "UPLOAD_FILE_DUPLICATE"
    from esl_platform.api.services import uploads as svc

    monkeypatch.setattr(svc, "disk_free", lambda root: 100)
    r = create(client, {}, file_spec=[{"rel": "rad/x.rad", "size": 1000}])
    assert r.status_code == 507 and _code(r) == "INSUFFICIENT_STORAGE"


@pytest.mark.parametrize("rel", ["../x.rad", "rad/../../x.rad", "/etc/x.rad", "C:/x.rad", "rad\\x.rad",
                                 "rad/CON.rad", "rad/aux.inc", "rad/lpt1", "rad/a\x00.rad", "rad//a.rad",
                                 "rad/./a.rad", "rad/a .rad ", "rad/a|b.rad", "x.rad", "other/x.rad", "rad/a.rad."])
def test_name_attacks_rel(client, rel):
    r = create(client, {}, file_spec=[{"rel": rel, "size": 1}])
    assert r.status_code == 422, (rel, r.text)
    assert _code(r) in ("UPLOAD_NAME_INVALID", "UPLOAD_EXT_NOT_ALLOWED", "INVALID_PARAMS")


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "NUL", "con.txt", "a\x01b", "   "])
def test_name_attacks_upload_name(client, name):
    r = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": name,
                                            "files": [{"rel": "rad/a.rad", "size": 1}]}, headers=W)
    assert r.status_code == 422 and _code(r) in ("UPLOAD_NAME_INVALID", "INVALID_PARAMS"), (name, r.text)


def test_symlink_inside_upload_dir_never_writes_outside(client, tmp_path):
    out = tmp_path / "outside"
    files = {"rad/m_0000.rad": mini_rad_text()}
    up = create(client, files).json()
    d = Path(up["dir_path"])
    os.symlink(out, d / "results")                       # 업로드 폴더 안에 바깥을 가리키는 링크가 생겼다고 가정
    r = client.post(f"{API}/uploads/{up['upload_id']}/files", headers=W,
                    json={"files": [{"rel": "results/done.json", "size": 2}]})
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE"
    os.symlink(out / "secret.txt", d / "rad" / "m_0000.rad.part")     # .part 자리에 바깥 파일 링크
    r = put(client, up["upload_id"], 0, 0, files["rad/m_0000.rad"])
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE"
    assert (out / "secret.txt").read_text() == "outside" and all_files(out) == {"secret.txt"}


def test_permissions_and_csrf(client):
    files = {"rad/m_0000.rad": b"x"}
    assert create(client, files, token="tok-general").status_code == 403
    assert create(client, files, token="tok-nonmember").status_code == 403
    r = client.post(f"{API}/uploads", json={"project_id": "p-1", "name": "a", "files": spec(files)}, headers=R)
    assert r.status_code == 403 and _code(r) == "CSRF_HEADER_REQUIRED"
    assert client.post(f"{API}/uploads", json={}, headers={"X-ESL-Request": "1"}).status_code == 401
    up = create(client, files).json()
    uid = up["upload_id"]
    r = client.put(f"{API}/uploads/{uid}/files/0", params={"offset": 0}, content=b"x",
                   headers={**R, "Content-Type": "application/octet-stream"})
    assert _code(r) == "CSRF_HEADER_REQUIRED"
    assert client.get(f"{API}/uploads/{uid}", headers=H("tok-power2")).status_code == 404     # 남의 업로드
    assert put(client, uid, 0, 0, b"x", token="tok-power2").status_code == 404
    assert client.delete(f"{API}/uploads/{uid}", headers=H("tok-power2", True)).status_code == 404
    assert client.get(f"{API}/uploads/{uid}", headers=H("tok-admin")).status_code == 200      # 전역 관리자
    assert [u["upload_id"] for u in client.get(f"{API}/uploads", headers=R).json()] == [uid]
    assert client.get(f"{API}/uploads", headers=H("tok-power2")).json() == []


def test_concurrent_limit(client):
    for i in range(2):
        assert create(client, {"rad/a.rad": b"x"}, name=f"n{i}").status_code == 201
    r = create(client, {"rad/a.rad": b"x"}, name="n3")
    assert r.status_code == 429 and _code(r) == "UPLOAD_LIMIT"
    assert create(client, {"rad/a.rad": b"x"}, name="other", token="tok-power2").status_code == 201


def test_complete_missing_include_then_add(client):
    rad = mini_rad_text(include="inc/extra.inc")
    files = {"rad/m_0000.rad": rad, **RESULTS}
    up = create(client, files).json()
    uid = up["upload_id"]
    r = client.post(f"{API}/uploads/{uid}/complete", headers=W)
    assert r.status_code == 409 and _code(r) == "UPLOAD_INCOMPLETE" and len(r.json()["detail"]["pending"]) == 4
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert not c["ok"] and c["state"] == "OPEN" and c["missing_includes"] == ["rad/inc/extra.inc"]
    inc = b"# extra\n"
    up = client.post(f"{API}/uploads/{uid}/files", headers=W, json={"files": spec({"rad/inc/extra.inc": inc})}).json()
    assert up["files"][4]["rel"] == "rad/inc/extra.inc" and up["result"] is None
    assert put(client, uid, 4, 0, inc).json()["done"]
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert c["ok"] and c["state"] == "COMPLETED" and c["parts"][0]["id"] == 7
    # 덮어쓰기 없음: 같은 이름 추가 거부
    assert client.post(f"{API}/uploads/{uid}/files", headers=W, json={"files": spec({"rad/x.inc": b"1"})}
                       ).status_code == 409


def test_complete_requires_rad_and_h3d_or_results(client):
    h3d_bad = {"rad/m_0000.rad": mini_rad_text(), "h3d/r.h3d": b"NOTH3D"}
    up = create(client, h3d_bad).json()
    send_all(client, up, h3d_bad)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert not c["ok"] and any("HYPER3D" in p for p in c["problems"])
    only_rad = {"rad/m_0000.rad": mini_rad_text()}
    up = create(client, only_rad, name="r2").json()
    send_all(client, up, only_rad)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert not c["ok"] and any("h3d" in p for p in c["problems"])
    client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)
    ok = {"rad/m_0000.rad": mini_rad_text(), "h3d/r.h3d": b"HYPER3D 2026"}
    up = create(client, ok, name="r3").json()
    send_all(client, up, ok)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert c["ok"] and c["h3d_path"].endswith("r.h3d") and c["results_dir"] is None


def test_cancel_and_stale_move_to_backup(client, app_ctx, upload_root):
    from esl_platform.api.services import uploads as svc

    files = {"rad/m_0000.rad": mini_rad_text(), "h3d/a.h3d": b"HYPER3D" + os.urandom(1_500_000)}
    up = create(client, files).json()
    cs = up["chunk_size"]
    assert put(client, up["upload_id"], 1, 0, files["h3d/a.h3d"][:cs]).status_code == 200
    r = client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)
    assert r.status_code == 200 and r.json()["state"] == "CANCELED"
    bk = Path(r.json()["backup_path"])
    assert not Path(up["dir_path"]).exists()
    assert (bk / "h3d" / "a.h3d.part").read_bytes()[:cs] == files["h3d/a.h3d"][:cs]     # 사전 할당된 .part 가 그대로 이동
    assert bk.parent == upload_root / "_backup" / "power"
    assert _code(client.delete(f"{API}/uploads/{up['upload_id']}", headers=W)) == "UPLOAD_CLOSED"
    # stale
    up2 = create(client, files, name="old").json()
    up3 = create(client, files, name="new").json()
    with app_ctx.engine.begin() as c:
        c.execute(text("UPDATE uploads SET updated_at = now() - interval '73 hours' WHERE id = :i"),
                  {"i": up2["upload_id"]})
    assert svc.cleanup_stale(app_ctx) == [up2["upload_id"]]
    g2 = client.get(f"{API}/uploads/{up2['upload_id']}", headers=R).json()
    g3 = client.get(f"{API}/uploads/{up3['upload_id']}", headers=R).json()
    assert g2["state"] == "STALE" and Path(g2["backup_path"]).is_dir() and not Path(up2["dir_path"]).exists()
    assert g3["state"] == "OPEN" and Path(up3["dir_path"]).is_dir()


def test_upload_disabled_without_root(tmp_path, client, app_ctx):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    lc = load_config_dict(d, environ={})
    assert lc.ok and lc.settings.storage.upload_root is None
    app_ctx.config = lc
    r = create(client, {"rad/a.rad": b"x"})
    assert r.status_code == 503 and _code(r) == "UPLOAD_DISABLED"


def test_config_upload_root_rules(tmp_path):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d["storage"]["upload_root"] = str(tmp_path / "esl-input")
    lc = load_config_dict(d, environ={})
    assert lc.ok and str(tmp_path / "esl-input") in lc.settings.storage.input_roots
    assert lc.settings.storage.browse_spdm is False and lc.settings.upload.chunk_bytes == 64 * 1024 * 1024
    assert lc.settings.upload.max_file_bytes == 64 * 1024 ** 3 and ".h3d" in lc.settings.upload.allowed_ext
    d2 = make_settings_dict(tmp_path)
    d2["storage"]["upload_root"] = str(tmp_path / "esl_root" / "up")
    assert "storage.upload_root" in load_config_dict(d2, environ={}).error_keys()
    d3 = make_settings_dict(tmp_path)
    d3["storage"]["upload_root"] = str(tmp_path / "inputs" / "up")     # 이미 입력 루트 안 → 그대로
    lc3 = load_config_dict(d3, environ={})
    assert lc3.ok and lc3.settings.storage.input_roots == [str(tmp_path / "inputs")]
    d4 = make_settings_dict(tmp_path)
    d4["upload"] = {"allowed_ext": ["exe"]}
    assert "upload.allowed_ext[0]" in load_config_dict(d4, environ={}).error_keys()


# ---------------------------------------------------------------- browse
def test_browse_roots_entries_hints(client, inputs_root, upload_root, tmp_path):
    (inputs_root / "m").mkdir()
    (inputs_root / "m" / "a_0000.rad").write_text("x")
    (inputs_root / "m" / "run.h3d").write_bytes(b"HYPER3D")
    (inputs_root / "m" / "out").mkdir()
    (inputs_root / "m" / "out" / "done.json").write_text("{}")
    (inputs_root / "m" / ".hidden").write_text("x")
    (inputs_root / "m" / "desktop.ini").write_text("x")
    os.symlink(tmp_path / "outside", inputs_root / "m" / "link")
    r = client.get(f"{API}/fs/browse", headers=R).json()
    kinds = [x["kind"] for x in r["roots"]]
    assert kinds == ["input", "upload"] and r["entries"] == []          # spdm 은 기본 제외
    r = client.get(f"{API}/fs/browse", params={"root": 0, "path": "m"}, headers=R).json()
    assert [(e["name"], e["type"], e["hint"]) for e in r["entries"]] == [
        ("out", "dir", "results"), ("a_0000.rad", "file", "rad"), ("run.h3d", "file", "h3d")]
    assert r["parent"] == "" and r["abs_path"] == str(inputs_root / "m")
    r = client.get(f"{API}/fs/browse", params={"root": 0, "path": "m/out"}, headers=R).json()
    assert r["hint"] == "results" and r["entries"][0]["name"] == "done.json"
    for bad in ("../", "m/../..", "/etc", "C:/x", "m/a|b"):
        r = client.get(f"{API}/fs/browse", params={"root": 0, "path": bad}, headers=R)
        assert r.status_code == 422 and _code(r) == "PATH_UNSAFE", bad
    r = client.get(f"{API}/fs/browse", params={"root": 0, "path": "m/link"}, headers=R)
    assert r.status_code == 422 and _code(r) == "PATH_UNSAFE"
    assert client.get(f"{API}/fs/browse", params={"root": 9}, headers=R).status_code == 404
    assert client.get(f"{API}/fs/browse", params={"root": 0, "path": "nope"}, headers=R).status_code == 404
    assert client.get(f"{API}/fs/browse").status_code == 401


def test_browse_pagination_and_upload_backup_hidden(client, inputs_root, upload_root):
    (inputs_root / "many").mkdir()
    for i in range(120):
        (inputs_root / "many" / f"f{i:03d}.csv").write_text("x")
    r = client.get(f"{API}/fs/browse", params={"root": 0, "path": "many"}, headers=R).json()
    assert r["total"] == 120 and len(r["entries"]) == 50 and r["limit"] == 50 and r["truncated"]
    r = client.get(f"{API}/fs/browse", params={"root": 0, "path": "many", "offset": 100, "limit": 30},
                   headers=R).json()
    assert [e["name"] for e in r["entries"]][0] == "f100.csv" and len(r["entries"]) == 20 and not r["truncated"]
    (upload_root / "_backup").mkdir(parents=True)
    (upload_root / "power").mkdir()
    (upload_root / "power" / "x.rad.part").parent.mkdir(exist_ok=True)
    (upload_root / "power" / "x.rad.part").write_text("p")
    r = client.get(f"{API}/fs/browse", params={"root": 1}, headers=R).json()
    assert [e["name"] for e in r["entries"]] == ["power"]
    r = client.get(f"{API}/fs/browse", params={"root": 1, "path": "power"}, headers=R).json()
    assert r["entries"] == []


def test_browse_spdm_option(tmp_path, engine, fake_dashboard, clock):
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    d = make_settings_dict(tmp_path)
    d["storage"]["browse_spdm"] = True
    (tmp_path / "spdm").mkdir()
    (tmp_path / "spdm" / "a.h3d").write_bytes(b"HYPER3D")
    ctx = build_context(load_config_dict(d, environ={}), engine,
                        transport=httpx.MockTransport(fake_dashboard.handler), clock=clock)
    with TestClient(create_app(ctx), base_url="http://127.0.0.1") as c:
        r = c.get(f"{API}/fs/browse", params={"root": 1}, headers=R).json()
    assert r["roots"][1]["kind"] == "spdm" and not r["roots"][1]["writable"]
    assert r["entries"][0]["hint"] == "h3d"


# ---------------------------------------------------------------- bundle
@pytest.fixture()
def case(client, mini_inputs, esl_root):
    r = create_case(client, mini_inputs)
    assert r.status_code == 201, r.text
    c = r.json()
    c["dir"] = Path(esl_root) / c["folder_name"]
    return c


def _zip(r) -> zipfile.ZipFile:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_case_bundle_contents_raw_and_escape(client, case, tmp_path):
    d = case["dir"]
    for rel, body in {"06_export/esl_loads.inc": b"*LOAD", "07_report/report.html": b"<html>",
                      "01_extract/summary.json": b"{}", "01_extract/model.npz": b"NPZ" * 10,
                      "04_esl/forces.csv": b"a,b", "_backup/old.inc": b"old", "06_export/tmp.tmp": b"t"}.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(body)
    os.symlink(tmp_path / "outside" / "secret.txt", d / "06_export" / "leak.txt")
    os.symlink(tmp_path / "outside", d / "06_export" / "leakdir")
    z = _zip(client.get(f"{API}/cases/{case['id']}/bundle", headers=R))
    names = set(z.namelist())
    p = case["folder_name"]
    assert {f"{p}/06_export/esl_loads.inc", f"{p}/07_report/report.html", f"{p}/01_extract/summary.json",
            f"{p}/04_esl/forces.csv", f"{p}/case.json"} <= names
    assert not any(n.endswith((".npz", "secret.txt", "leak.txt", ".tmp", "old.inc")) or ".." in n for n in names)
    assert z.read(f"{p}/06_export/esl_loads.inc") == b"*LOAD"
    z = _zip(client.get(f"{API}/cases/{case['id']}/bundle", params={"parts": "export"}, headers=R))
    assert {n.split("/", 1)[1].split("/")[0] for n in z.namelist()} == {"06_export"}
    z = _zip(client.get(f"{API}/cases/{case['id']}/bundle", params={"parts": "summary,raw"}, headers=R))
    assert f"{p}/01_extract/model.npz" in z.namelist()
    r = client.get(f"{API}/cases/{case['id']}/bundle", params={"parts": "export,../x"}, headers=R)
    assert r.status_code == 422
    assert client.get(f"{API}/cases/nope/bundle", headers=R).status_code == 404


def test_case_bundle_size_limit_and_empty(client, case):
    r = client.get(f"{API}/cases/{case['id']}/bundle", params={"parts": "export"}, headers=R)
    assert r.status_code == 404 and _code(r) == "BUNDLE_EMPTY"
    (case["dir"] / "06_export").mkdir(exist_ok=True)
    (case["dir"] / "06_export" / "big.inc").write_bytes(b"0" * 60_000)
    r = client.get(f"{API}/cases/{case['id']}/bundle", headers=R)
    assert r.status_code == 413 and _code(r) == "BUNDLE_TOO_LARGE"
    assert r.json()["detail"]["path"] == str(case["dir"]) and r.json()["detail"]["limit"] == 50_000


def test_stream_zip_large_and_zip64_ok(tmp_path):
    from esl_platform.api.services import bundle

    src = tmp_path / "s"
    src.mkdir()
    data = os.urandom(3 * bundle.READ_CHUNK + 7)
    (src / "a.npz").write_bytes(data)
    (src / "b.csv").write_text("x,y\n" * 1000)
    chunks = list(bundle.stream_zip(list(bundle._walk(str(src))), "p"))
    assert len(chunks) > 2
    z = zipfile.ZipFile(io.BytesIO(b"".join(chunks)))
    assert z.testzip() is None and z.read("p/a.npz") == data


def test_analysis_bundle(client, engine, esl_root):
    import uuid

    from esl_platform.core.db.tables import analysis_runs
    from sqlalchemy import insert

    aid = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(insert(analysis_runs).values(id=aid, project_id="p-1", filters={}, options={}, entry_ids=["e1"],
                                               dir_rel=f"_analysis/{aid}", created_by="u-power",
                                               created_by_name="파워"))
    a = Path(esl_root) / "_analysis" / aid
    (a / "opt").mkdir(parents=True)
    (a / "report.html").write_text("<html>")
    (a / "opt" / "deck.fem").write_text("deck")
    (a / "envelope.csv").write_text("a")
    (a / "mapped_loads.npz").write_bytes(b"N")
    (a / "logs").mkdir()
    (a / "logs" / "x.log").write_text("l")
    z = _zip(client.get(f"{API}/library/analyses/{aid}/bundle", headers=R))
    assert set(z.namelist()) == {f"analysis_{aid}/report.html", f"analysis_{aid}/opt/deck.fem",
                                 f"analysis_{aid}/envelope.csv"}
    z = _zip(client.get(f"{API}/library/analyses/{aid}/bundle", params={"parts": "raw"}, headers=R))
    assert set(z.namelist()) == {f"analysis_{aid}/mapped_loads.npz"}


# ---------------------------------------------------------------- 버전
def test_version_matches_changelog_top():
    from esl_platform.api.services import version

    ver = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    assert version.SEMVER.match(ver), ver
    log = version.parse_changelog((REPO / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert log and log[0]["version"] == ver, "VERSION 과 CHANGELOG.md 최상단 버전이 같아야 합니다"
    assert log[0]["date"] and any(log[0]["sections"][s] for s in version.SECTIONS)
    vs = [tuple(int(x) for x in e["version"].split(".")) for e in log]
    assert vs == sorted(vs, reverse=True) and len(set(vs)) == len(vs)       # 최신이 위, 중복 없음


def test_parse_changelog_and_build_info(tmp_path):
    from esl_platform.api.services import version

    log = version.parse_changelog("# x\n\n## [1.2.0] - 2026-10-21\n### 추가\n- 가\n- 나\n### 수정\n* 다\n"
                                  "## [1.1.0] - 2026-10-01\n### 기타\n- 라\n")
    assert log[0] == {"version": "1.2.0", "date": "2026-10-21", "sections": {"추가": ["가", "나"], "변경": [],
                                                                             "수정": ["다"]}}
    assert log[1]["sections"]["기타"] == ["라"]
    (tmp_path / "VERSION").write_text("0.9.1\n")
    g = tmp_path / ".git"
    (g / "refs" / "heads").mkdir(parents=True)
    (g / "HEAD").write_text("ref: refs/heads/main\n")
    (g / "refs" / "heads" / "main").write_text("abcdef1234567890abcdef1234567890abcdef12\n")
    assert version.build_info(tmp_path) == {"version": "0.9.1", "commit": "abcdef1", "built_at": None}
    (g / "refs" / "heads" / "main").unlink()
    (g / "packed-refs").write_text("# pack\n1234567890abcdef1234567890abcdef12345678 refs/heads/main\n")
    assert version.build_info(tmp_path)["commit"] == "1234567"
    (tmp_path / "BUILD.json").write_text(json.dumps({"version": "0.9.2", "commit": "fff0000",
                                                     "built_at": "2026-10-20T01:02:03Z"}))
    assert version.build_info(tmp_path) == {"version": "0.9.2", "commit": "fff0000", "built_at": "2026-10-20T01:02:03Z"}


def test_version_api(client):
    ver = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    r = client.get(f"{API}/version", headers=R)
    assert r.status_code == 200 and r.json()["version"] == ver
    r = client.get(f"{API}/changelog", headers=R)
    assert r.status_code == 200 and r.json()[0]["version"] == ver and "추가" in r.json()[0]["sections"]
    assert client.get(f"{API}/version").status_code == 401
