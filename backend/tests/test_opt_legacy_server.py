"""v0.7.2 재현 시험: v0.6.0 서버를 update-repo 로 v0.7.0 에 올린 운영 상태에서 새 비드 최적화(/opt/new) 빈 화면.

운영 상태 = 설정에 opt_run 섹션·altair.optistruct_path 없음, 코드 스냅샷에 resources/opt_method_sources.json 없음(배포 목록 누락),
라이브러리 항목은 v0.7.0 이전 등록(topo_sha256·deform_mode 지연 백필 대상, 일부 항목 폴더 형식 이상).
- GET /opt/settings 는 200 이고 method_sources = {"error"} — 프런트 LoadStrategy 가 src.strategies.A 를 읽다 TypeError(빈 화면).
  프런트 시험(src/__tests__/opt_legacy.test.tsx)이 같은 응답으로 화면이 정상 표시되는지 고정한다.
- 지연 백필 예외는 항목 단위로 격리(목록·s1-check 500 없음, 경고 로그).
"""

from __future__ import annotations

import logging

import pytest
from esl_test_support import API, H, make_settings_dict
from opt_support import R, W, make_case, plate, seed_opt_entry
from sqlalchemy import text

ADMIN = H("tok-admin")


@pytest.fixture()
def settings_dict(tmp_path):
    d = make_settings_dict(tmp_path)
    d.pop("opt_run", None)                                            # v0.6.0 설정: 섹션 없음
    d["altair"] = {k: v for k, v in d["altair"].items() if k != "optistruct_path"}
    return d


@pytest.fixture(autouse=True)
def _fresh_backfill():
    from esl_platform.api.services import library as lib_svc

    lib_svc._BACKFILL_FAILED.clear()
    yield
    lib_svc._BACKFILL_FAILED.clear()


@pytest.fixture()
def legacy(engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    ids = [seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1),
           seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2),
           seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=3, raw=False)]     # raw.npz 없음
    with engine.begin() as c:
        c.execute(text("UPDATE library_entries SET topo_sha256 = NULL, deform_mode = NULL"))
    return ids


def test_settings_without_opt_run_section(client):
    s = client.get(f"{API}/opt/settings", headers=R).json()
    assert s["enabled"] is False and s["solver_ready"] is False
    assert s["solver_reason"] == "비드 최적화가 꺼져 있습니다 — 관리자 문의"          # 일반 사용자 = 설정 키 없이
    sa = client.get(f"{API}/opt/settings", headers=ADMIN).json()
    assert "opt_run.enabled" in sa["solver_reason"]                                    # 관리자 = 원문
    assert {"A", "B", "C"} <= set(s["method_sources"]["strategies"])
    assert s["loads"]["default_strategy"] == "A" and s["bead_defaults"]["angle"] == 45.0


def test_settings_method_sources_missing_is_error_not_500(client, monkeypatch, tmp_path, caplog):
    """빈 화면 원인: 코드 스냅샷에 resources/opt_method_sources.json 이 없을 때 응답 형태(프런트 opt_legacy 시험의 입력)."""
    monkeypatch.setattr("esl.opt.METHOD_SOURCES_PATH", str(tmp_path / "nope" / "opt_method_sources.json"))
    with caplog.at_level(logging.WARNING, logger="esl_platform.api"):
        r = client.get(f"{API}/opt/settings", headers=R)
    assert r.status_code == 200, r.text
    ms = r.json()["method_sources"]
    assert set(ms) == {"error"} and "관리자 문의" in ms["error"] and "nope" not in ms["error"]     # 일반 사용자 = 경로 없음
    assert "nope" in client.get(f"{API}/opt/settings", headers=ADMIN).json()["method_sources"]["error"]
    assert any("방법·출처" in m for m in caplog.messages)


def test_backfill_unexpected_error_isolated_per_entry(client, legacy, esl_root, caplog):
    """항목 폴더 형식 이상(entry.json 이 객체가 아님 → AttributeError)도 그 항목만 건너뛴다(이전에는 목록 500)."""
    a, b, c = legacy
    (esl_root / "_library" / "entries" / b / "entry.json").write_text("[1, 2]", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="esl_platform.api"):
        r = client.get(f"{API}/library/entries", params={"project_id": "p-1"}, headers=R)
    assert r.status_code == 200, r.text
    by = {e["id"]: e for e in r.json()}
    assert by[a]["topo_sha256"] and by[a]["deform_mode"]["effective"] == "bend"
    assert by[b]["topo_sha256"] is None and by[b]["deform_mode"] is None               # 격리
    assert by[c]["topo_sha256"] is None                                                # raw 없음
    assert sum("지연 백필" in m for m in caplog.messages) == 2
    # s1-check: 기준 정상 + 이상 항목 → 200(모델 정보 없음), 기준이 이상 항목 → 409(500 아님)
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [a, b, c]}, headers=W)
    assert r.status_code == 200, r.text
    rows = {x["entry_id"]: x for x in r.json()["entries"]}
    assert rows[a]["same_model"] is True and rows[b]["reason"] == "MODEL_INFO_MISSING" and rows[c]["reason"] == "MODEL_INFO_MISSING"
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": [b]}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING", r.text
    r = client.get(f"{API}/opt/plan-view", params={"entry_id": b}, headers=R)
    assert r.status_code == 409, r.text


def test_backfill_db_write_failure_isolated(client, legacy, monkeypatch):
    """백필 결과 DB 저장이 실패해도(예: 잠금·연결) 목록은 200, 그 항목은 백필 전 값."""
    from esl_platform.api.services import library as lib_svc

    real = lib_svc.update

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(lib_svc, "update", boom)
    r = client.get(f"{API}/library/entries", params={"project_id": "p-1"}, headers=R)
    assert r.status_code == 200, r.text
    assert all(e["topo_sha256"] is None for e in r.json())
    monkeypatch.setattr(lib_svc, "update", real)


def test_case_rad_missing_s1_check_409(client, legacy, inputs_root):
    """케이스 입력 rad 가 원본 경로에 없음 → s1-check 409 PREREQUISITE_MISSING(화면은 사유 표시 + S2 로)."""
    (inputs_root / "c1_0000.rad").unlink()
    r = client.post(f"{API}/opt/s1-check", json={"project_id": "p-1", "entry_ids": legacy[:2]}, headers=W)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING", r.text
    assert "case_input" in r.text
