"""v0.10.0 라이브러리 내보내기 기본 숨김(사용자 확정 2026-10-29): 설정 ui.library_export_enabled 기본 false →
GET /version ui 로 전달, /library/exports API 4개는 전역 관리자만(그 외 403 EXPORT_DISABLED). true 일 때 동작은
test_menu_restructure.py·worker/tests/test_lib_export.py 가 확인한다."""

from __future__ import annotations

from esl_test_support import API, H


def test_export_disabled_by_default(client, app_ctx):
    assert app_ctx.settings.ui.library_export_enabled is False
    assert client.get(f"{API}/version", headers=H("tok-power")).json()["ui"]["library_export_enabled"] is False
    body = {"project_id": "p-1", "entry_ids": ["x"], "targets": ["fem"]}
    for method, path, kw in (("POST", "/library/exports", {"json": body}),
                             ("GET", "/library/exports", {"params": {"project_id": "p-1"}}),
                             ("GET", "/library/exports/00000000-0000-0000-0000-000000000000", {}),
                             ("GET", "/library/exports/00000000-0000-0000-0000-000000000000/bundle", {})):
        r = client.request(method, f"{API}{path}", headers=H("tok-power", method != "GET"), **kw)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "EXPORT_DISABLED", (path, r.text)
    # 전역 관리자는 꺼져 있어도 사용(다음 검사로 진행 — 없는 항목 422, 없는 묶음 404)
    r = client.post(f"{API}/library/exports", json=body, headers=H("tok-admin", True))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ENTRY_NOT_FOUND", r.text
    r = client.get(f"{API}/library/exports/00000000-0000-0000-0000-000000000000", headers=H("tok-admin"))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "EXPORT_NOT_FOUND", r.text
    assert client.get(f"{API}/library/exports", params={"project_id": "p-1"}, headers=H("tok-admin")).status_code == 200
