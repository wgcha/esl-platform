"""v0.24.6 B1 — 스터디 결과 응답: 지그 방식 상태(jig.methods·tie_dofs)·지그 변위·스프링 3D 키·SOURCE_ADD jd·js(계약 esl_viewer_hv.md V-0246-VW-20).

코어 사이드카(post/jig_view.json)는 계약 §8 형식의 합성 파일로 시험한다(코어 구현 C1 은 병행).
"""

from __future__ import annotations

import json

from doe_support import api, study_dir
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
from test_doe_jig_view_api import JIG_BLOCK, JIG_ROW, SIDE, _jig_done, _run_job
from test_doe_rank_metric_api import _done

M_OK = {"method": "prescribed", "method_name": "강제 변위", "tie_dofs": "normal", "status": "ok", "code": None, "detail": None,
        "fit_mac_min": 0.99, "fit_umax_err_max": 0.12, "warnings": [], "limits": ["JIG_DISP_FROM_TARGET"], "n_jig": 10,
        "bc": {"n_aux": 3, "n_jig": 10, "tie_text": "tie 면외(법선)"}, "spring": None}
M_SPR = {**M_OK, "method": "spring", "method_name": "스프링", "limits": [], "bc": {"n_aux": 3}, "spring": {"k": 12.5}}
M_FAIL = {**M_OK, "status": "fallback", "code": "JIG_NO_TIE", "detail": "tie 접촉 노드가 없습니다", "fit_mac_min": None,
          "fit_umax_err_max": None, "n_jig": None, "bc": None}
# 지그 고정을 끈 스터디: 상위 jig 블록 = fallback, 방식은 ok
JIG_FIXED_OFF = {**JIG_BLOCK, "status": "fallback", "code": "JIG_SKIPPED", "tie_dofs": "normal",
                 "methods": {"jig_disp": M_OK, "jig_spring": M_SPR}}
V3D_SIDE = {**SIDE, "view3d_jd": {"d001": "d001_jd"}, "view3d_jd_esl": {"d001": "e1"}, "view3d_jd_ref": {"e1": "d000_jd_e00"},
            "view3d_js": {"d001": "d001_js"}, "view3d_js_esl": {"d001": "e1"}, "view3d_js_ref": {"e1": "d000_js_e00"}}
NEW_KEYS = ("view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref")


def _study(client, world, engine, esl_root, jig, side):  # noqa: F811
    sid = _done(client, world, engine, esl_root, {"metric": "jig", "metric_effective": "jig", "cross_mesh": False, "jig": jig}, [JIG_ROW])
    if side is not None:
        (study_dir(esl_root, sid) / "post" / "jig_view.json").write_text(json.dumps(side), encoding="utf-8")
    _run_job(engine, sid)
    return sid


def _res(client, sid, **kw):
    r = api(client, "GET", f"/doe/studies/{sid}/results", **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_jig_methods_and_tie_dofs_pass_through(client, world, engine, esl_root):  # noqa: F811
    jig = {**JIG_BLOCK, "tie_dofs": "translation", "methods": {"jig_disp": M_OK, "jig_spring": M_SPR, "jig": M_FAIL}}
    o = _res(client, _study(client, world, engine, esl_root, jig, SIDE))
    assert o["jig"]["tie_dofs"] == "translation"
    got = o["jig"]["methods"]
    assert set(got) == {"jig_disp", "jig_spring", "jig"}
    assert got["jig_disp"] == M_OK and got["jig_spring"] == M_SPR                      # 값 그대로(bc·spring dict 포함)
    assert got["jig"]["status"] == "fallback" and got["jig"]["code"] == "JIG_NO_TIE" and got["jig"]["detail"] == M_FAIL["detail"]


def test_old_jig_block_has_null_methods(client, world, engine, esl_root):  # noqa: F811
    o = _res(client, _jig_done(client, world, engine, esl_root))
    assert o["jig"]["methods"] is None and o["jig"]["tie_dofs"] is None
    assert o["jig"]["status"] == JIG_BLOCK["status"]                                    # 기존 키 값 그대로
    assert all(o[k] is None for k in NEW_KEYS)


def test_v3d_jd_js_sidecar_merge(client, world, engine, esl_root):  # noqa: F811
    o = _res(client, _study(client, world, engine, esl_root, JIG_FIXED_OFF, V3D_SIDE))
    assert o["view3d_jd"] == {"d001": "d001_jd"} and o["view3d_jd_esl"] == {"d001": "e1"} and o["view3d_jd_ref"] == {"e1": "d000_jd_e00"}
    assert o["view3d_js"] == {"d001": "d001_js"} and o["view3d_js_esl"] == {"d001": "e1"} and o["view3d_js_ref"] == {"e1": "d000_js_e00"}
    assert o["view3d_jig"] == {"d001": "d001_jig"}                                      # 기존 지그 3D 병합 유지


def test_v3d_result_json_wins_for_jig_and_old_sidecar_keeps_old_values(client, world, engine, esl_root):  # noqa: F811
    jig = {**JIG_BLOCK, "methods": {"jig_disp": M_OK}}
    sid = _study(client, world, engine, esl_root, jig, {**V3D_SIDE, "view3d_jig": {"d001": "from_side"}})
    base = study_dir(esl_root, sid) / "post"
    res = json.loads((base / "result.json").read_text(encoding="utf-8"))
    res["view3d_jig"] = {"d001": "from_result"}
    (base / "result.json").write_text(json.dumps(res), encoding="utf-8")
    from doe_support import update_study

    update_study(engine, sid, result=res)
    o = _res(client, sid)
    assert o["view3d_jig"] == {"d001": "from_result"} and o["view3d_jd"] == {"d001": "d001_jd"}
    # v0.24.5 사이드카(새 키 없음) = 기존 키 값 그대로, 새 키 null
    o2 = _res(client, _jig_done(client, world, engine, esl_root))
    assert o2["view3d_jig"] == SIDE["view3d_jig"] and o2["view3d_jig_ref"] == SIDE["view3d_jig_ref"]
    assert all(o2[k] is None for k in NEW_KEYS)


def test_rank_v3d_mirrors_models_and_nodal():
    from esl_platform.api.schemas import DoeResultOut, DoeRankViewsOut
    from esl_platform.api.services.doe import BF_VIEWS, NODAL_SOURCES, RANK_V3D, RANK_VIEWS

    assert tuple(RANK_V3D) == RANK_VIEWS and set(DoeRankViewsOut.model_fields) == set(RANK_VIEWS)
    flat = [k for v in RANK_V3D.values() for k in (v or ())]
    assert len(flat) == len(set(flat)) and set(flat) <= set(DoeResultOut.model_fields)   # 모델 필드와 같음(빠짐·중복 없음)
    for key in BF_VIEWS:
        assert RANK_V3D[key] == NODAL_SOURCES[key]["v3d"][:3]
    assert set(NEW_KEYS) <= set(flat)
    assert RANK_V3D["full"] is None


def test_rank_v3d_mirrors_core_column():
    """코어 RANK_SOURCES 열 v3d(C1)와 실제 대조 — 모든 행에 열이 있고 값(응답 키 3개 | None)이 거울과 같다. 열 v3d_store·v3d_tag 도 확인."""
    from esl.doe import stages as stg
    from esl_platform.api.services.doe import RANK_V3D

    assert [s["key"] for s in stg.RANK_SOURCES] == list(RANK_V3D)
    for row in stg.RANK_SOURCES:
        assert "v3d" in row and "v3d_tag" in row and "v3d_store" in row, row["key"]          # 열 없음 = 대조 건너뜀 금지
        assert (tuple(row["v3d"]) if row["v3d"] else None) == RANK_V3D[row["key"]], row["key"]
        assert (row["v3d"] is None) == (row["v3d_tag"] is None), row["key"]


def test_methods_model_mirrors_core_fields():
    from esl_platform.api.schemas import DoeJigMethodOut

    assert set(DoeJigMethodOut.model_fields) == {"method", "method_name", "tie_dofs", "status", "code", "detail", "fit_mac_min",
                                                 "fit_umax_err_max", "warnings", "limits", "n_jig", "bc", "spring"}


def test_source_add_jd_js_listed_and_202(client, world, engine, esl_root):  # noqa: F811
    from esl_platform.core.repositories import jobs as jobs_repo

    sid = _study(client, world, engine, esl_root, JIG_FIXED_OFF, V3D_SIDE)
    o = _res(client, sid)
    assert "jig" not in o["source_add"] and o["view3d_regen"] is None                  # 지그 고정 꺼짐 = 고정 행만 불가
    assert o["source_add"]["jig_disp"] == o["source_add"]["jig_spring"] == {"available": True, "allowed": True, "reason": None}
    for src in ("jig_disp", "jig_spring"):
        r = api(client, "POST", f"/doe/studies/{sid}/sources/{src}")
        assert r.status_code == 202, r.text
        with engine.connect() as c:
            job = jobs_repo.get_job(c, r.json()["job"]["id"])
            p = job["params"]
        assert p["kind"] == "VIEW3D" and p["doe"]["post_mode"] == "view3d"
        assert "bforce_cfg" not in p["doe"] and "fint_cfg" not in p["doe"] and "None_cfg" not in p["doe"]
        from doe_support import finish_job

        finish_job(engine, job["id"])


def test_source_add_jig_still_409_when_fixed_off(client, world, engine, esl_root):  # noqa: F811
    sid = _study(client, world, engine, esl_root, JIG_FIXED_OFF, V3D_SIDE)
    r = api(client, "POST", f"/doe/studies/{sid}/sources/jig")
    assert r.status_code == 409 and code(r) == "VIEW3D_REGEN_UNAVAILABLE"              # v0.24.5 동작 유지


def test_source_add_jd_409_when_method_missing_or_failed(client, world, engine, esl_root):  # noqa: F811
    jig = {**JIG_BLOCK, "methods": {"jig_disp": M_OK, "jig_spring": {**M_FAIL, "method": "spring"}}}
    sid = _study(client, world, engine, esl_root, jig, V3D_SIDE)
    o = _res(client, sid)
    assert list(o["source_add"]) == ["jig", "jig_disp"]                                # 실패 방식 = 행 없음
    r = api(client, "POST", f"/doe/studies/{sid}/sources/jig_spring")
    assert r.status_code == 409 and code(r) == "VIEW3D_REGEN_UNAVAILABLE"
    old = _jig_done(client, world, engine, esl_root)                                   # 옛 스냅샷(methods 없음)
    for src in ("jig_disp", "jig_spring"):
        r = api(client, "POST", f"/doe/studies/{old}/sources/{src}")
        assert r.status_code == 409 and code(r) == "VIEW3D_REGEN_UNAVAILABLE"
    assert list(_res(client, old)["source_add"]) == ["jig"]


def test_source_add_jd_404_unknown_and_full_and_403(client, world, engine, esl_root):  # noqa: F811
    sid = _study(client, world, engine, esl_root, JIG_FIXED_OFF, V3D_SIDE)
    for src in ("full", "jig_x"):
        assert api(client, "POST", f"/doe/studies/{sid}/sources/{src}").status_code == 404
    r = api(client, "POST", f"/doe/studies/{sid}/sources/jig_disp", token="tok-power2")
    assert r.status_code == 403
    assert _res(client, sid, token="tok-power2")["source_add"]["jig_disp"]["allowed"] is False
