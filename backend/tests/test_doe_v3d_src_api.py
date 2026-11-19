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


def regen_trace(client, world, engine, esl_root, path_of) -> dict:
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


def test_regenerate_equals_v0240_golden(client, world, engine, esl_root):  # noqa: F811
    cur = regen_trace(client, world, engine, esl_root, lambda sid: f"/doe/studies/{sid}/view3d/regenerate")
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not GOLDEN.is_file():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps({"recorded_at_commit": "f29eeec0 (= v0.24.0 regenerate)", "trace": cur}, indent=1,
                                     sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))["trace"]
    assert cur == gold
    assert gold["no_run"]["code"] == gold["needs_jig"]["code"] == "VIEW3D_REGEN_UNAVAILABLE"
