"""V-OR-9 템플릿 API(계약 esl_opt_run.md OR-D-8·9, §5.1·§7.2): 검사(업로드 result.purpose = template·COMPLETED·업로드
폴더 불변), 등록 복사(sha256)·파생 파일, 공개 목록, 삭제 권한, 사용 중 ARCHIVED, 미사용 삭제 + _backup, 보관 템플릿 새 실행
거부·retry 허용, PLATE_CHANGED, UPLOAD_NOT_READY, 형식 오류, 업로드 밖 include 거부."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from esl_test_support import API, H
from opt_support import (
    R,
    W,
    fem_bytes,
    make_case,
    opt_settings_dict,
    register_template,
    run_body,
    seed_opt_entry,
    tree,
    upload_files,
)
from sqlalchemy import text


@pytest.fixture()
def settings_dict(tmp_path):
    return opt_settings_dict(tmp_path)


def _check(client, uid, token="tok-power", **kw):
    return client.post(f"{API}/opt/templates/check", json={"project_id": "p-1", "upload_id": uid, **kw},
                       headers=H(token, True))


def test_check_register_copy_and_public_list(client, engine, esl_root, tmp_path):
    data = fem_bytes(tmp_path)
    uid = upload_files(client, {"rad/plate.fem": data})
    with engine.connect() as c:
        up_dir = Path(c.execute(text("SELECT dir_path FROM uploads WHERE id=:i"), {"i": uid}).scalar_one())
    before = tree(up_dir)
    r = _check(client, uid)
    assert r.status_code == 200, r.text
    chk = r.json()
    assert chk["ok"] and chk["format"] == "fem" and chk["file_name"] == "plate.fem" and chk["upload_id"] == uid
    assert chk["sha256"] == hashlib.sha256(data).hexdigest()
    assert chk["mesh"]["n_nodes"] == 117 and chk["mesh"]["n_elems"] == 96 and chk["pids"][0]["pid"] == 10
    assert len(chk["supports_auto"]) == 3
    with engine.connect() as c:
        st, res = c.execute(text("SELECT state, result FROM uploads WHERE id=:i"), {"i": uid}).one()
    assert st == "COMPLETED" and res["purpose"] == "template" and res["ok"] and res["sha256"] == chk["sha256"]
    # 다른 사용자의 업로드는 없음 취급, general 은 power 아님
    assert _check(client, uid, "tok-power2").status_code == 404
    assert _check(client, uid, "tok-general").status_code == 403
    body = {"project_id": "p-1", "upload_id": uid, "sha256": chk["sha256"], "title": "  75형 평판 v1 ", "inch": 75,
            "description": "설명"}
    r = client.post(f"{API}/opt/templates", json=body, headers=W)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] == "75형 평판 v1" and t["inch"] == 75 and t["status"] == "ACTIVE" and t["n_runs"] == 0
    assert t["format"] == "fem" and t["n_nodes"] == 117 and t["n_elems"] == 96 and t["can_delete"] is True
    assert t["L_xi"] == pytest.approx(300.0) and t["L_eta"] == pytest.approx(200.0) and len(t["supports_auto"]) == 3
    tdir = esl_root / "_templates" / t["id"]
    assert (tdir / "input" / "rad" / "plate.fem").read_bytes() == data
    meta = json.loads((tdir / "template.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == chk["sha256"] and meta["frame"]["L_xi"] == pytest.approx(300.0)
    assert meta["input_rel"] == "input/rad/plate.fem" and meta["format"] == "fem" and meta["template_id"] == t["id"]
    with np.load(tdir / "template.npz") as z:
        assert set(z.files) >= {"node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu"}
    assert json.loads((tdir / "preview.json").read_text(encoding="utf-8"))["elems"]["n_total"] == 96
    assert tree(up_dir) == before                                         # 업로드 폴더 쓰기 없음
    # 공개 목록: 모든 사용자 조회, 삭제 버튼은 등록자·관리자만
    for tok, can in (("tok-power", True), ("tok-power2", False), ("tok-general", False), ("tok-nonmember", False),
                     ("tok-admin", True)):
        lst = client.get(f"{API}/opt/templates", headers=H(tok)).json()
        assert [x["id"] for x in lst] == [t["id"]] and lst[0]["can_delete"] is can
    assert client.get(f"{API}/opt/templates", params={"q": "75형"}, headers=R).json()[0]["id"] == t["id"]
    assert client.get(f"{API}/opt/templates", params={"q": "없는"}, headers=R).json() == []
    assert client.get(f"{API}/opt/templates/{t['id']}", headers=H("tok-nonmember")).status_code == 200
    assert client.get(f"{API}/opt/templates/nope", headers=R).json()["detail"]["code"] == "TEMPLATE_NOT_FOUND"


def test_plate_changed_and_upload_not_ready(client, engine, tmp_path):
    data = fem_bytes(tmp_path)
    uid = upload_files(client, {"rad/plate.fem": data})
    sha = _check(client, uid).json()["sha256"]
    r = client.post(f"{API}/opt/templates", json={"project_id": "p-1", "upload_id": uid, "sha256": "0" * 64,
                                                  "title": "x"}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLATE_CHANGED"
    with engine.connect() as c:
        up_dir = Path(c.execute(text("SELECT dir_path FROM uploads WHERE id=:i"), {"i": uid}).scalar_one())
    (up_dir / "rad" / "plate.fem").write_bytes(data[:-2] + b"$\n")             # 검사 뒤 파일이 바뀜(크기 같음)
    r = client.post(f"{API}/opt/templates", json={"project_id": "p-1", "upload_id": uid, "sha256": sha, "title": "x"},
                    headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLATE_CHANGED"
    # 다 받지 않은 업로드
    uid2 = upload_files(client, {"rad/plate.fem": data}, complete_files=False)
    r = _check(client, uid2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "UPLOAD_NOT_READY"
    assert _check(client, "nope").json()["detail"]["code"] == "UPLOAD_NOT_FOUND"
    # 취소된 업로드
    client.delete(f"{API}/uploads/{uid2}", headers=W)
    assert _check(client, uid2).json()["detail"]["code"] == "UPLOAD_NOT_READY"


def test_format_errors_and_outside_include(client, tmp_path):
    uid = upload_files(client, {"rad/notes.txt": b"hello"})
    r = _check(client, uid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MESH_FORMAT_UNSUPPORTED"
    uid = upload_files(client, {"rad/a.fem": fem_bytes(tmp_path), "rad/b.fem": fem_bytes(tmp_path)})
    assert _check(client, uid).json()["detail"]["code"] == "MESH_INVALID"
    uid = upload_files(client, {"rad/bad.fem": b"BEGIN BULK\nINCLUDE 'other.fem'\nENDDATA\n"})
    r = _check(client, uid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MESH_INVALID"
    # rad: 업로드 밖 include 거부(존재 여부 무관 같은 메시지)
    outside = tmp_path / "outside.inc"
    outside.write_text("/NODE\n")
    rad = f"#RADIOSS STARTER\n#include {outside}\n/END\n".encode()
    uid = upload_files(client, {"rad/model_0000.rad": rad})
    r = _check(client, uid)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MESH_INVALID"
    assert "업로드에 포함되지 않은 include" in r.json()["detail"]["message"]


def test_delete_permissions_archive_and_backup(client, engine, esl_root, inputs_root, tmp_path):
    t_unused = register_template(client, tmp_path, title="미사용")
    t_used = register_template(client, tmp_path, title="사용")
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    run = client.post(f"{API}/opt/runs", json=run_body([eid], "S2", template_id=t_used["id"]), headers=W)
    assert run.status_code == 201, run.text
    for tok in ("tok-power2", "tok-general", "tok-nonmember"):
        r = client.delete(f"{API}/opt/templates/{t_unused['id']}", headers=H(tok, True))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "NOT_TEMPLATE_OWNER"
    assert client.delete(f"{API}/opt/templates/nope", headers=W).status_code == 404
    r = client.delete(f"{API}/opt/templates/{t_unused['id']}", headers=H("tok-admin", True))   # 전역 관리자
    assert r.json() == {"deleted": True, "archived": False}
    assert not (esl_root / "_templates" / t_unused["id"]).exists()
    backups = list((esl_root / "_templates" / "_backup").iterdir())
    assert len(backups) == 1 and backups[0].name.endswith(t_unused["id"]) and (backups[0] / "template.npz").is_file()
    assert client.get(f"{API}/opt/templates/{t_unused['id']}", headers=R).status_code == 404
    r = client.delete(f"{API}/opt/templates/{t_used['id']}", headers=W)
    assert r.json() == {"deleted": False, "archived": True}
    g = client.get(f"{API}/opt/templates/{t_used['id']}", headers=R).json()
    assert g["status"] == "ARCHIVED" and g["n_runs"] == 1 and g["archived_at"]
    assert (esl_root / "_templates" / t_used["id"] / "template.npz").is_file()      # 보관 = 파일 유지
    assert client.delete(f"{API}/opt/templates/{t_used['id']}", headers=W).json() == {"deleted": False, "archived": True}
    assert [x["id"] for x in client.get(f"{API}/opt/templates", params={"status": "ACTIVE"}, headers=R).json()] == []
    # 보관 템플릿: 새 실행 거부, retry 허용
    r = client.post(f"{API}/opt/runs", json=run_body([eid], "S2", template_id=t_used["id"]), headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TEMPLATE_ARCHIVED"
    jid = run.json()["job"]["id"]
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state='FAILED', queue_seq=NULL, failure_code='OS_SOLVE_FAILED', "
                       "finished_at=now() WHERE id=:i"), {"i": jid})
    rt = client.post(f"{API}/jobs/{jid}/retry", headers=W)
    assert rt.status_code == 201 and rt.json()["params"]["template"]["id"] == t_used["id"]


def test_upload_stale_after_register_does_not_matter(client, engine, esl_root, inputs_root, tmp_path):
    """V-OR-14(백엔드 부분): 등록 뒤 업로드가 _backup 으로 옮겨져도 템플릿(복사본)으로 실행 생성 가능."""
    t = register_template(client, tmp_path)
    with engine.connect() as c:
        rows = c.execute(text("SELECT id FROM uploads")).all()
    for (uid,) in rows:
        with engine.begin() as c:
            c.execute(text("UPDATE uploads SET state='OPEN' WHERE id=:i"), {"i": uid})
        client.delete(f"{API}/uploads/{uid}", headers=W)
    make_case(engine, inputs_root, "c1")
    eid = seed_opt_entry(engine, esl_root, "c1")
    r = client.post(f"{API}/opt/runs", json=run_body([eid], "S2", template_id=t["id"]), headers=W)
    assert r.status_code == 201, r.text
