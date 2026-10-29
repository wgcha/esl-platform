"""V-CI-U1(로더 기본 확장자)·U2(complete 상태 파일 include 검사) — 계약 esl_cumulative_input.md §9."""
from __future__ import annotations

from pathlib import Path

import pytest
from esl_test_support import API, H, make_settings_dict
from test_p3_ux import RESULTS, create, mini_rad_text, send_all, spec

W = H("tok-power", True)

STR = (b"#RADIOSS STATE FILE prev_0002.sta\n/BEGIN\nprev\n      2024         0\n"
       b"/SHELL/         7\n       101         1         4         5         2\n/NODE\n         1 0.0 0.0 0.0\n")
STA = b"/BEGIN\nprev\n/INISHE/EPSP_F\n#  SHELLID, NPT, NPG, THK\n       101         0         1 2.0000000000000E+00\n" \
      b" 1.0000000000000E-02\n"


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path)
    d["storage"]["upload_root"] = str(tmp_path / "esl-input")
    d["upload"] = {"chunk_mb": 1, "max_file_bytes": 3_000_000, "max_upload_bytes": 5_000_000, "min_free_gb": 0}
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "prev_0002.sta").write_bytes(STA)
    return d


def test_u1_loader_default_allows_state_ext():
    from esl_platform.core.config import UPLOAD_EXT_DEFAULT, UploadCfg

    assert ".sta" in UPLOAD_EXT_DEFAULT and ".str" in UPLOAD_EXT_DEFAULT
    assert {".sta", ".str"} <= set(UploadCfg().allowed_ext)
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        import yaml
        root = Path(__file__).resolve().parents[2]
        y = yaml.safe_load((root / "config" / p).read_text(encoding="utf-8"))
        assert {".sta", ".str"} <= set(y["upload"]["allowed_ext"]), p


def _rad_with(*incs: str) -> bytes:
    txt = mini_rad_text().decode()
    for inc in incs:
        txt = txt.replace("/END", f"#include {inc}\n/END")
    return txt.encode()


def test_u2_state_include_missing_then_added(client):
    files = {"rad/m_0000.rad": _rad_with("prev/prev_0002.str", "prev/prev_0002.sta"),
             "rad/prev/prev_0002.str": STR, **RESULTS}
    up = create(client, files).json()
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert not c["ok"] and c["missing_includes"] == ["rad/prev/prev_0002.sta"]
    assert any(p.startswith("STATE_INCLUDE_MISSING:") and "prev/prev_0002.sta" in p for p in c["problems"])
    st = {s["rel"]: s for s in c["state_includes"]}
    assert st["rad/prev/prev_0002.str"]["found"] and st["rad/prev/prev_0002.str"]["kinds"] == ["geometry"]
    assert st["rad/prev/prev_0002.sta"]["found"] is False
    uid = up["upload_id"]
    up = client.post(f"{API}/uploads/{uid}/files", headers=W,
                     json={"files": spec({"rad/prev/prev_0002.sta": STA})}).json()
    from test_p3_ux import put
    idx = next(f["index"] for f in up["files"] if f["rel"] == "rad/prev/prev_0002.sta")
    assert put(client, uid, idx, 0, STA).json()["done"]
    c = client.post(f"{API}/uploads/{uid}/complete", headers=W).json()
    assert not any(p.startswith("STATE_INCLUDE_MISSING") for p in c["problems"]) and c["missing_includes"] == []
    st = {s["rel"]: s for s in c["state_includes"]}
    assert st["rad/prev/prev_0002.sta"]["kinds"] == ["initial"] and st["rad/prev/prev_0002.sta"]["found"]


def test_u2_state_by_header_and_outside_upload(client, tmp_path):
    files = {"rad/m_0000.rad": _rad_with("geo.inc", str(tmp_path / "outside" / "prev_0002.sta")),
             "rad/geo.inc": STR, **RESULTS}
    up = create(client, files).json()
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    st = {s["rel"]: s for s in c["state_includes"]}
    assert st["rad/geo.inc"]["kinds"] == ["geometry"]                   # 확장자 아님 — 헤더로 식별
    # 업로드 밖 상태 파일: 기존 메시지 그대로(존재 여부 노출 없음), 상태 목록에도 없음
    assert any(p.startswith("업로드에 포함되지 않은 include:") for p in c["problems"])
    assert not any("STATE_INCLUDE_MISSING" in p for p in c["problems"]) and len(st) == 1


def test_u2_plain_upload_has_empty_state_includes(client):
    files = {"rad/m_0000.rad": mini_rad_text(), **RESULTS}
    up = create(client, files).json()
    send_all(client, up, files)
    c = client.post(f"{API}/uploads/{up['upload_id']}/complete", headers=W).json()
    assert c["ok"] and c["state_includes"] == []
