"""v0.24.6 통합 — 실제 코어 산출물(esl.doe.stages BD_POST·3D 다시 만들기)이 백엔드 병합·응답까지 이어지는지(합성 사이드카 아님).

코어 시험 도구(tests/doe/test_jig_stages — 합성 판·가짜 paicad)로 BD_POST 를 돌리고, 그 post/result.json 의 지그 블록·순위 행과
post/jig_view.json 을 그대로 스터디 폴더에 놓은 뒤 GET /doe/studies/{id}/results 를 확인한다.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_CORE_TESTS = str(Path(__file__).resolve().parents[2] / "tests" / "doe")
if _CORE_TESTS not in sys.path:
    sys.path.insert(0, _CORE_TESTS)

import test_jig_stages as T  # noqa: E402
from doe_support import api, study_dir  # noqa: E402
from test_doe_compare_api import (  # noqa: E402,F401  (픽스처 재사용)
    _app,
    _fresh_cache,
    _job,
    cbody,
    doe_settings_dict,
    multi_upload,
    settings_dict,
    shapes3,
    world,
)
from test_doe_jig_view_api import _run_job  # noqa: E402
from test_doe_rank_metric_api import _done  # noqa: E402

from esl.doe import DEFAULTS  # noqa: E402
from esl.doe import stages as stg  # noqa: E402
from esl.library import _util as U  # noqa: E402

SRC_KEYS = ("view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref")


def _core(base: Path, *, jig_diag: bool = True, view3d_jig: bool = True):
    mesh, doe = T.build_same(base)
    view3d = {k: v for k, v in (("jig_diag", jig_diag), ("jig", view3d_jig)) if v is False}
    if view3d:
        doe["cfg"] = {**T.CFG_FULL, "bead_doe": {"enabled": True, "view3d": view3d}}
    rank = T.rank_snap(jig=copy.deepcopy(DEFAULTS["rank"]["jig"]))        # v0.24.5 기본 — 법선·[prescribed, spring]
    out, post, _ids = T.run(str(base / "o"), doe, mesh, rank=rank)
    sp = Path(out) / "post" / stg.JIG_VIEW_JSON
    side = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else None
    return out, post, side, doe, rank


def _api_study(client, world, engine, esl_root, post, side):  # noqa: F811
    keep = {k: post[k] for k in ("metric", "metric_effective", "cross_mesh", "jig") if k in post}
    sid = _done(client, world, engine, esl_root, keep, post["ranking"])
    if side is not None:
        (study_dir(esl_root, sid) / "post" / "jig_view.json").write_text(json.dumps(side), encoding="utf-8")
    _run_job(engine, sid)
    r = api(client, "GET", f"/doe/studies/{sid}/results")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def core_on(tmp_path_factory):
    return _core(tmp_path_factory.mktemp("e2e_on"))


def test_core_sidecar_keys_reach_api(client, world, engine, esl_root, core_on):  # noqa: F811
    out, post, side, _doe, _rank = core_on
    assert all(k in side for k in SRC_KEYS) and set(side["view3d_src_seconds"]) == {"jd", "js"}
    assert not [w for w in side["warnings"] if "VIEW3D_FAILED" in w] and not any(k in post for k in SRC_KEYS)   # result.json 에는 없음
    o = _api_study(client, world, engine, esl_root, post, side)
    for k in SRC_KEYS:
        assert o[k] == side[k] and o[k], k                       # 키·값 그대로(코어 {did: 폴더}·{did: entry}·{entry: 폴더})
    for did, folder in o["view3d_jd"].items():                   # 폴더 이름이 코어 산출물과 실제로 일치
        assert (Path(out) / "post" / "view3d" / folder).is_dir()
    for folder in o["view3d_js_ref"].values():
        assert (Path(out) / "post" / "view3d" / folder).is_dir()
    assert "view3d_src_seconds" not in o                          # 사이드카 전용(응답 필드 아님)
    # 지그 블록: methods·tie_dofs 가 코어 값 그대로(F2 는 result.data.jig.tie_dofs·methods 를 읽음)
    assert o["jig"]["tie_dofs"] == post["jig"]["tie_dofs"] == "normal"
    assert set(o["jig"]["methods"]) == {"jig_disp", "jig_spring"} and all(m["status"] == "ok" for m in o["jig"]["methods"].values())
    # SOURCE_ADD 행(src 열) ↔ 코어 v3d_store=sidecar 행 ↔ methods 키
    from esl_platform.api.services.doe import SOURCE_ADD

    side_rows = {r["key"] for r in stg.RANK_SOURCES if r["v3d_store"] == "sidecar"}
    assert {r["src"] for r in SOURCE_ADD.values() if r.get("src")} == side_rows == set(o["jig"]["methods"])
    assert o["source_add"]["jig_disp"]["available"] and o["source_add"]["jig_spring"]["available"]


def test_regen_carry_keys_match_backend_rows(core_on, tmp_path):
    """SOURCE_ADD(src) ↔ 코어 다시 만들기 옮겨 적기(v3_src): 사이드카에서 jd·js 키를 빼면 다시 만들기가 같은 키를 되살린다."""
    out, _post, side, doe, rank = core_on
    outr = str(tmp_path / "_doe")
    shutil.copytree(out, outr)
    sp = os.path.join(outr, "post", stg.JIG_VIEW_JSON)
    U.write_json(sp, {k: v for k, v in side.items() if k not in (*SRC_KEYS, "view3d_src_seconds")})
    stg.run_stage({"stage": "bd_post", "out": outr, "doe": {**doe, "rank": rank, "rev": 1, "post_mode": "view3d"}}, lambda s: None)
    again = U.read_json(sp)
    assert all(again[k] == side[k] for k in SRC_KEYS) and set(again["view3d_src_seconds"]) == {"jd", "js"}


def test_view3d_jig_diag_off_no_sidecar_no_src_3d(client, world, engine, esl_root, tmp_path):  # noqa: F811
    out, post, side, _doe, _rank = _core(tmp_path, jig_diag=False)
    assert side is None and not [n for n in os.listdir(os.path.join(out, "post", "view3d")) if n.endswith(("_jd", "_js"))]
    o = _api_study(client, world, engine, esl_root, post, side)
    assert all(o[k] is None for k in SRC_KEYS) and o["rank_views"] is None and o["jig_diag"] is None
    # 지그 방식은 계산됐으므로 응답 구조는 methods ok — 화면은 rank_views 없음 = no_view 사유로 보이고 3D 칸·다시 만들기 안내는 없다
    assert all(m["status"] == "ok" for m in o["jig"]["methods"].values())
    print("source_add(jig_diag off):", o.get("source_add"))
