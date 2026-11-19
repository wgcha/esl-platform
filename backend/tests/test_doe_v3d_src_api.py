"""v0.24.1 스터디 자료 만들기 일반화(계약 esl_view3d_sources.md §5.2, V-0241-V3D-14).

골든: v0.24.0 `POST /doe/studies/{sid}/view3d/regenerate` 의 409·403 상세(code·message)·202 본문(ID·시각 정규화)·작업 params·단계를
변경 **전**(f29eeec0)에 ``ESL_GOLDEN_RECORD=1`` 로 ``backend/tests/fixtures/doe_regen_v0240.json`` 에 기록했다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from doe_support import api, finish_job
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    _app,
    _fresh_cache,
    _job,
    cbody,
    code,
    doe_settings_dict,
    multi_upload,
    settings_dict,
    shapes3,
    world,
)
from test_doe_jig_view_api import _jig_done, _run_job
from test_doe_rank_metric_api import _done

GOLDEN = Path(__file__).parent / "fixtures" / "doe_regen_v0240.json"
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _norm(v, ids: dict[str, str]):
    """스터디·작업 ID → 자리표시, 그 밖 UUID → <uuid>, ISO 시각 → <ts>(실행마다 다른 값만 정규화)."""
    if isinstance(v, dict):
        return {k: _norm(x, ids) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x, ids) for x in v]
    if isinstance(v, str):
        for k, name in ids.items():
            v = v.replace(k, name)
        return "<ts>" if _TS.match(v) else _UUID.sub("<uuid>", v)
    return v


def _detail(r) -> dict:
    d = r.json()["detail"]
    return {"status": r.status_code, **{k: d[k] for k in sorted(d) if k != "request_id"}}


def regen_trace(client, world, engine, esl_root, path_of) -> dict:  # noqa: F811
    """v0.24.0 regenerate 시험(test_regenerate_queues_run_from_post·needs_jig) 순서를 그대로 따라 응답을 모은다.
    path_of(sid) = 요청 경로(옛 /view3d/regenerate 또는 새 /sources/jig)."""
    from esl_platform.core.repositories import jobs as jobs_repo

    out: dict = {}
    sid = _jig_done(client, world, engine, esl_root, run=False)
    out["no_run"] = _detail(api(client, "POST", path_of(sid)))
    _run_job(engine, sid)
    out["power2"] = _detail(api(client, "POST", path_of(sid), token="tok-power2"))
    out["general"] = _detail(api(client, "POST", path_of(sid), token="tok-general"))
    r = api(client, "POST", path_of(sid))
    assert r.status_code == 202, r.text
    jid = r.json()["job"]["id"]
    with engine.connect() as c:
        job = jobs_repo.get_job(c, jid)
        steps = jobs_repo.get_steps(c, jid)
    ids = {sid: "<sid>", jid: "<jid>"}
    out["accepted"] = {"status": r.status_code, "body": _norm(r.json(), ids)}
    out["params"] = _norm(job["params"], ids)
    out["job_type"] = job["job_type"]
    out["steps"] = [[x["step_key"], x["state"]] for x in steps]
    out["active"] = _detail(api(client, "POST", path_of(sid)))
    finish_job(engine, jid)
    sid2 = _done(client, world, engine, esl_root, {})
    _run_job(engine, sid2)
    out["needs_jig"] = _detail(api(client, "POST", path_of(sid2)))
    return out


def test_regenerate_equals_v0240_golden(client, world, engine, esl_root):  # noqa: F811 — 픽스처
    cur = regen_trace(client, world, engine, esl_root, lambda sid: f"/doe/studies/{sid}/view3d/regenerate")
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not GOLDEN.is_file():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps({"recorded_at_commit": "f29eeec0 (= v0.24.0 regenerate)", "trace": cur}, indent=1,
                                     sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))["trace"]
    assert cur == gold
    assert gold["no_run"]["code"] == gold["needs_jig"]["code"] == "VIEW3D_REGEN_UNAVAILABLE"


# ---------------------------------------------------------------- V-14 sources/jig ≡ regenerate
def test_sources_jig_equals_regenerate_golden(client, world, engine, esl_root):  # noqa: F811
    cur = regen_trace(client, world, engine, esl_root, lambda sid: f"/doe/studies/{sid}/sources/jig")
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))["trace"]
    assert cur == gold                                                       # 409·403 상세·202 본문·params·단계 동일


def test_sources_full_404_and_unknown(client, world, engine, esl_root):  # noqa: F811
    sid = _jig_done(client, world, engine, esl_root)
    for src in ("full", "xyz"):
        r = api(client, "POST", f"/doe/studies/{sid}/sources/{src}")
        assert r.status_code == 404 and code(r) == "SOURCE_NOT_FOUND" and r.json()["detail"]["source"] == src


def test_source_add_mirrors_legacy_keys(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    from test_doe_bforce_api import _bf_done

    from esl_platform.api.services import doe as svc

    # 지그 결과 + 같은 메시 계획(bf base) → jig·bforce·fint 모두
    sid = _jig_done(client, world, engine, esl_root)
    monkeypatch.setattr(svc, "_plan_col", lambda s, col: "base")
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert list(o["source_add"]) == ["jig", "bforce", "fint"]
    for k, legacy in (("jig", "view3d_regen"), ("bforce", "bforce_add"), ("fint", "fint_add")):
        assert o["source_add"][k] == o[legacy] and o[legacy]["available"] is True and o[legacy]["allowed"] is True
    o2 = api(client, "GET", f"/doe/studies/{sid}/results", token="tok-power2").json()
    assert o2["view3d_regen"]["reason"] == "관리자 또는 이 스터디 작성자만 3D 를 다시 만들 수 있습니다"
    assert "경계력 ESL 을 계산할" in o2["bforce_add"]["reason"] and o2["source_add"]["fint"] == o2["fint_add"]
    # 지그 없음 + 다른 메시 계획 → 행 없음(null), 옛 키 null
    monkeypatch.setattr(svc, "_plan_col", lambda s, col: "none")
    sid2 = _done(client, world, engine, esl_root, {})
    _run_job(engine, sid2)
    o3 = api(client, "GET", f"/doe/studies/{sid2}/results").json()
    assert o3["source_add"] is None and o3["view3d_regen"] is None and o3["bforce_add"] is None and o3["fint_add"] is None
    assert o3["view3d_bf_recon"] is None and o3["view3d_fi_recon"] is None
    # 노드 힘 사이드카의 재현 키 통과(사이드카에 있을 때만)
    monkeypatch.setattr(svc, "_plan_col", lambda s, col: "base")
    from test_doe_bforce_api import BSIDE

    sid3 = _bf_done(client, world, engine, esl_root, monkeypatch, side={**BSIDE, "view3d_bf_recon": {"e1": "d000_bf_e00"}})
    o4 = api(client, "GET", f"/doe/studies/{sid3}/results").json()
    assert o4["view3d_bf_recon"] == {"e1": "d000_bf_e00"} and o4["view3d_fi_recon"] is None
    assert o4["source_add"]["bforce"] == o4["bforce_add"] and "jig" not in o4["source_add"]


def test_sources_bforce_job_params_unchanged(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    """POST /sources/bforce 작업 params = v0.24.0(kind BFORCE·post_mode bforce·bforce_cfg 사본), 지그 행은 cfg 키 없음."""
    from test_doe_bforce_api import _bf_done

    from esl_platform.core.repositories import jobs as jobs_repo

    sid = _bf_done(client, world, engine, esl_root, monkeypatch)
    r = api(client, "POST", f"/doe/studies/{sid}/sources/bforce")
    assert r.status_code == 202, r.text
    with engine.connect() as c:
        p = jobs_repo.get_job(c, r.json()["job"]["id"])["params"]
    assert p["kind"] == "BFORCE" and p["doe"]["post_mode"] == "bforce" and isinstance(p["doe"]["bforce_cfg"], dict)
    assert "fint_cfg" not in p["doe"] and "None_cfg" not in p["doe"]


def test_recon_files_served(client, world, engine, esl_root):  # noqa: F811
    from doe_support import study_dir

    sid = _jig_done(client, world, engine, esl_root)
    d = study_dir(esl_root, sid) / "post" / "view3d" / "d000_bf_e00"
    d.mkdir(parents=True)
    (d / "recon.json").write_text(json.dumps({"schema": "esl/view3d_recon/1"}), encoding="utf-8")
    (d / "recon.bin").write_bytes(b"\x00\x01\x02\x03")
    r = api(client, "GET", f"/doe/studies/{sid}/view3d/d000_bf_e00/recon.json")
    assert r.status_code == 200 and r.json()["schema"] == "esl/view3d_recon/1"
    assert r.headers["content-type"].startswith("application/json")
    r = api(client, "GET", f"/doe/studies/{sid}/view3d/d000_bf_e00/recon.bin")
    assert r.status_code == 200 and r.content == b"\x00\x01\x02\x03"
