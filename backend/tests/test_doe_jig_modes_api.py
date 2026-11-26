"""v0.24.5 #88 후속 — 강성 스터디 모든 모드에서 지그 변위·스프링 순위 보기가 결과 API 응답까지 가는지(백엔드 층).

픽스처 backend/tests/fixtures/jig_modes_v0245.json = 실제 코어 산출(tests/doe/test_jig_modes.py 가 JIG_MODES_DUMP 로 생성 — 모드마다
post/result.json·post/jig_view.json, sm_jig none 모드는 그 계획의 BD_POST 지그·지표 블록). 모드 = 계획 표 행(시나리오·select_base)이고
기대값은 계획 열 sm_jig 로만 고른다(모드 이름 분기 없음).

- sm_jig base: 사이드카의 모든 rank_views 키가 응답에 그대로(jig_disp·jig_spring·full — #88 은 스키마 필드 누락으로 빠졌음), jig_plan base.
- sm_jig none: 보기 없음·jig_plan none(화면이 "이 모드는 지그 ESL 을 계산하지 않음" 사유를 이 값으로 고름)·지그 블록 unsupported.
``JIG_MODES_API_DUMP=<경로>`` 이면 모드별 실제 응답을 프런트 픽스처로 저장(frontend/src/__tests__/fixtures/real_v0245_modes.json).
"""

from __future__ import annotations

import copy
import json
import os

import pytest
from doe_support import api, study_dir, update_study
from esl_test_support import REPO
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
from test_doe_rank_metric_api import _done

FIXTURE = REPO / "backend" / "tests" / "fixtures" / "jig_modes_v0245.json"
FE_FIXTURE = REPO / "frontend" / "src" / "__tests__" / "fixtures" / "real_v0245_modes.json"
MODES = json.loads(FIXTURE.read_text(encoding="utf-8"))["modes"]


def _study(client, world, engine, esl_root, m: dict) -> str:
    sid = _done(client, world, engine, esl_root, {})
    base = study_dir(esl_root, sid)
    (base / "post" / "result.json").write_text(json.dumps(m["result"]), encoding="utf-8")
    if m["side"] is not None:
        (base / "post" / "jig_view.json").write_text(json.dumps(m["side"]), encoding="utf-8")
    s = api(client, "GET", f"/doe/studies/{sid}").json()
    base_row = {"entry_id": s["entry_ids"][0], "case_id": "c-1", "part_title": "chassis rear"} if m["scenario"] == "same" else None
    update_study(engine, sid, scenario=m["scenario"], inputs={**s["inputs"], **m["inputs"]}, result=m["result"],
                 **({"base": base_row} if base_row else {}))
    if m["sm_jig"] == "none":          # 픽스처 = v0.24.5 결과(지그 unsupported) = 옛 스냅샷 — v0.24.8 새 스냅샷의 jig_grid 를 뺀다(그러면 jig_plan none)
        from test_doe_v0248_b1_api import _jobs, _set_params

        for jid, params in _jobs(engine, sid):
            p = copy.deepcopy(params)
            p["doe"]["rank"].pop("jig_grid", None)
            _set_params(engine, jid, p)
    return sid


def _sig(o: dict) -> dict:
    return {"jig_plan": o.get("jig_plan"), "metric_effective": o.get("metric_effective"),
            "jig": [(o.get("jig") or {}).get("status"), (o.get("jig") or {}).get("code")],
            "views": sorted((k, v["metric"]) for k, v in (o.get("rank_views") or {}).items() if v is not None)}


def test_fixture_covers_every_plan():
    from esl_platform.core.opt_core import doe_transfer_plan as tp

    assert set(MODES) == set(tp.PLANS)
    for pid, m in MODES.items():                                  # 픽스처의 (시나리오, select_base) = 계획 표 열쇠
        assert tp.plan_for(m["scenario"], m["inputs"].get("select_base") or "case")["id"] == pid
        assert m["sm_jig"] == tp.PLANS[pid]["sm_jig"]


@pytest.mark.parametrize("pid", sorted(MODES))
def test_jig_views_reach_results_api(client, world, engine, esl_root, pid):
    from esl_platform.api.services.doe import RANK_VIEWS

    m = MODES[pid]
    sid = _study(client, world, engine, esl_root, m)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["scenario"] == m["scenario"] and o["jig_plan"] == m["sm_jig"]
    side_views = (m["side"] or {}).get("rank_views") or {}
    got = {k: v for k, v in (o["rank_views"] or {}).items() if v is not None}
    assert set(got) == set(side_views) and set(side_views) <= set(RANK_VIEWS)      # 사이드카 보기 = 응답 보기(빠짐 없음)
    for k, v in side_views.items():
        assert got[k] == v, k                                                         # 순위·기준·민감도·인라인 per_esl 그대로
    if m["sm_jig"] == "base":
        srcs = [s for s, row in m["result"]["jig"]["methods"].items() if row["status"] == "ok"]   # 코어 방식 상태(응답 jig.methods = v0.24.6)
        assert {"jig_disp", "jig_spring"} <= set(srcs) <= set(got)                   # 계산된 방식 = 응답 보기
        assert got["jig_disp"]["metric"] == "jd" and got["jig_spring"]["metric"] == "js" and got["full"]["metric"] == "solve"
        assert all(r["per_esl"] and all(p["C"] is not None for p in r["per_esl"]) for r in got["jig_disp"]["ranking"])
        assert o["metric_effective"] == "jd"
    else:
        assert o["rank_views"] is None and o["jig"]["status"] == "unsupported" and o["jig"]["code"] == "JIG_UNSUPPORTED"
        assert o["metric_effective"] == "solve" and o["cross_mesh"] is True
    dump = os.environ.get("JIG_MODES_API_DUMP")
    if dump:
        doc = json.loads(open(dump, encoding="utf-8").read()) if os.path.isfile(dump) else {
            "schema": 1, "made_by": "backend/tests/test_doe_jig_modes_api.py (JIG_MODES_API_DUMP)", "modes": {}}
        doc["modes"][pid] = {"scenario": m["scenario"], "sm_jig": m["sm_jig"], "result": o}
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    if FE_FIXTURE.is_file():                                                          # 프런트 픽스처 낡음 대조
        fe = json.loads(FE_FIXTURE.read_text(encoding="utf-8"))["modes"]
        assert pid in fe and _sig(fe[pid]["result"]) == _sig(o), \
            "응답 구조가 프런트 픽스처와 다름 — JIG_MODES_API_DUMP=frontend/src/__tests__/fixtures/real_v0245_modes.json 로 다시 생성"


def test_rank_views_fields_cover_core_sources():
    """응답 모델 DoeRankViewsOut 필드 ⊇ 코어 출처 표 RANK_SOURCES 키(extra=ignore 로 조용히 빠지는 키 방지 — #88)."""
    from esl.doe import stages as stg
    from esl_platform.api.schemas import DoeRankViewsOut, DoeRankViewOut

    assert {s["key"] for s in stg.RANK_SOURCES} <= set(DoeRankViewsOut.model_fields)
    assert set(stg.VIEW_KEYS) <= set(DoeRankViewOut.model_fields)
