"""v0.25.2 B1 — ② t* 임의 프레임 API(계약 esl_tstar_manual_jig_force.md §6.1, V-0252-24·25), 설정 거울(V-0252-17 백엔드 쪽·27), 스터디 결과 통과(27).

계약 형식 fixture 로 시험: 01_extract·02_tstar 산출물은 손으로 심고(지표 계열 없음), 코어 frame_point 만 monkeypatch(계약 §2.3 반환
형식 — 백엔드 저장·판정 단위 시험). DECIDE·frames_have·extract_facts 는 실제 코어(esl.io.frame_fill).
실제 코어 frame_point·merge·ESL 을 거치는 PUT → ESL 은 worker/tests/test_frame_fill.py(통합 — 합성 Case 추출 산출물).
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
from esl_test_support import API, H, create_case, make_settings_dict
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")
NF = 10                                   # 프레임 0..9, 시각 = f × 0.001
D_FRAMES = [3, 6, 8]                       # 추출 때 변위·변형률을 받은 프레임(후보 = 6·3, 8 은 D 안 비후보)
AUTO = 6


@pytest.fixture()
def fake_hw(tmp_path):
    from h3d_support import write_fake_hw

    return write_fake_hw(tmp_path)


@pytest.fixture()
def settings_dict(tmp_path, fake_hw):
    d = make_settings_dict(tmp_path)
    d["altair"] = {"hw_exe_path": str(fake_hw), "max_concurrent_hw": 1}
    return d


def _seed(engine, esl_root, case, *, h3d: bool, tmp_path, dump: bool = False):
    """Case 에 추출 요약·01_extract·02_tstar 를 심고(계약 형식) 입력 종류를 정한다."""
    cdir = os.path.join(str(esl_root), case["folder_name"])
    ex, ts = os.path.join(cdir, "01_extract"), os.path.join(cdir, "02_tstar")
    os.makedirs(ex, exist_ok=True)
    os.makedirs(ts, exist_ok=True)
    fi = np.arange(NF, dtype=np.int32)
    np.savez(os.path.join(ex, "history.npz"), time=fi * 0.001, frame_index=fi, elem_id=np.array([101, 102], np.int64))
    nid = np.arange(1, 10, dtype=np.int64)
    xs = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], float) * 10.0
    np.savez(os.path.join(ex, "model.npz"), node_id=nid, x0=xs)
    dfi = np.array(D_FRAMES, np.int32)
    np.savez(os.path.join(ex, "disp.npz"), frame_index=dfi, u=np.zeros((3, 9, 3)))
    np.savez(os.path.join(ex, "strain_frames.npz"), frame_index=dfi, elem_id=np.array([101, 102], np.int64))
    meta = {"frames_D": D_FRAMES, "time_D": [f * 0.001 for f in D_FRAMES], "n_frames_h3d": NF,
            "strain_fallback": {"mode": "dump" if dump else "direct", "source": "Max_Strain"}}
    with open(os.path.join(ex, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    cands = [{"rank": 1, "frame_index": 6, "time": 0.006, "elem_id": 101, "value": 0.02, "in_D": True},
             {"rank": 2, "frame_index": 3, "time": 0.003, "elem_id": 102, "value": 0.01, "in_D": True}]
    blk = {"tstar": cands[0], "candidates": cands, "history": {"time": (fi * 0.001).tolist(), "m": [0.0] * NF}}
    with open(os.path.join(ts, "tstar.json"), "w", encoding="utf-8") as fh:
        json.dump({"metric": "max_strain", "metrics": {"max_strain": blk}, "frames_D": [{"frame_index": f, "time": f * 0.001}
                                                                                          for f in D_FRAMES]}, fh)
    sets = {"e": json.dumps({"job_id": "x", "requested_part_title": case["part_title"]}), "i": case["id"]}
    with engine.begin() as c:
        c.execute(text("UPDATE cases SET extract_summary=CAST(:e AS jsonb) WHERE id=:i"), sets)
        if h3d:
            p = tmp_path / "in.h3d"
            p.write_bytes(b"H3D")
            c.execute(text("UPDATE cases SET input_kind='H3D', h3d_path=:p WHERE id=:i"), {"p": str(p), "i": case["id"]})
    return cdir


def _fake_point(monkeypatch, calls=None):
    from esl_worker import core_adapter

    def fp(out_dir, cfg, metric, frame_index):
        if calls is not None:
            calls.append((metric, frame_index, cfg))
        return {"frame_index": frame_index, "time": frame_index * 0.001, "elem_id": 102, "value": 0.008,
                "auto": {"frame_index": AUTO, "time": 0.006, "value": 0.02}, "ratio": 0.4,
                "rel": "before" if frame_index < AUTO else ("at" if frame_index == AUTO else "after"),
                "in_D": frame_index in D_FRAMES, "have": frame_index in D_FRAMES}
    monkeypatch.setattr(core_adapter, "frame_point", fp)


@pytest.fixture()
def case_r(client, engine, esl_root, mini_inputs, tmp_path):
    c = create_case(client, mini_inputs, folder="tm0", title="결과 CSV Case").json()
    _seed(engine, esl_root, c, h3d=False, tmp_path=tmp_path)
    return c


@pytest.fixture()
def case_h(client, engine, esl_root, mini_inputs, tmp_path):
    c = create_case(client, mini_inputs, folder="tm1", title="h3d Case").json()
    _seed(engine, esl_root, c, h3d=True, tmp_path=tmp_path)
    return c


def _get(client, c):
    r = client.get(f"{API}/cases/{c['id']}/tstar", headers=R)
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, c, frame, version=None, headers=W):
    return client.put(f"{API}/cases/{c['id']}/tstar", json={"version": version or c["version"], "metric": "max_strain",
                                                            "frame_index": frame}, headers=headers)


# ---------------------------------------------------------------- V-0252-24 GET /tstar
def test_get_tstar_new_keys_results_case(client, case_r):
    j = _get(client, case_r)
    assert j["frames"] == [{"frame_index": f, "time": f * 0.001} for f in range(NF)]
    assert j["frames_have"] == D_FRAMES
    assert j["fill"]["available"] is False and j["fill"]["code"] == "NO_H3D" and "h3d 없이" in j["fill"]["text"]
    assert j["metrics"]["max_strain"]["history"]["frame_index"] == list(range(NF))
    assert j["manual_ratio_warn"] == 0.5                                            # 통합 INT: 코어 설정 tstar.manual_ratio_warn 값 그대로
    for k in ("selected", "default_metric", "metrics", "hotspots", "frames_D"):     # 기존 키 그대로
        assert k in j
    assert j["metrics"]["max_strain"]["candidates"][0]["frame_index"] == 6


def test_get_tstar_fill_available_h3d(client, case_h):
    j = _get(client, case_h)
    assert j["fill"] == {"available": True, "code": None, "text": None}


def test_get_tstar_fill_dump_and_unreadable(client, engine, esl_root, mini_inputs, tmp_path):
    c = create_case(client, mini_inputs, folder="tm2", title="덤프").json()
    _seed(engine, esl_root, c, h3d=True, tmp_path=tmp_path, dump=True)
    f = _get(client, c)["fill"]
    assert f["available"] is False and f["code"] == "DUMP_MODE"
    c2 = create_case(client, mini_inputs, folder="tm3", title="h3d 없음").json()
    _seed(engine, esl_root, c2, h3d=True, tmp_path=tmp_path)
    os.remove(tmp_path / "in.h3d")
    f = _get(client, c2)["fill"]
    assert f["code"] == "H3D_UNREADABLE" and "in.h3d" in f["text"]


def test_get_tstar_old_history_length_mismatch_omits_frame_index(client, engine, esl_root, case_r):
    p = os.path.join(str(esl_root), case_r["folder_name"], "02_tstar", "tstar.json")
    d = json.load(open(p, encoding="utf-8"))
    d["metrics"]["max_strain"]["history"] = {"time": [0.0, 0.001], "m": [0.0, 0.0]}
    json.dump(d, open(p, "w", encoding="utf-8"))
    j = _get(client, case_r)
    assert "frame_index" not in j["metrics"]["max_strain"]["history"] and len(j["frames"]) == NF


# ---------------------------------------------------------------- V-0252-25 PUT /tstar
def test_put_candidate_saved_value_unchanged(client, case_r, monkeypatch):
    calls: list = []
    _fake_point(monkeypatch, calls)
    r = _put(client, case_r, 3)
    assert r.status_code == 200, r.text
    ts = r.json()["tstar"]
    assert {k: ts[k] for k in ("metric", "frame_index", "time", "elem_id", "value", "source")} == {
        "metric": "max_strain", "frame_index": 3, "time": 0.003, "elem_id": 102, "value": 0.01, "source": "user"}
    assert "manual" not in ts and calls == []                       # 후보 경로 = 코어 frame_point 호출 0·manual 키 없음


def test_put_in_d_non_candidate_manual(client, case_r, monkeypatch):
    calls: list = []
    _fake_point(monkeypatch, calls)
    r = _put(client, case_r, 8)                                      # D 안 비후보 — 변위 있음, 채움 불필요(결과 CSV Case 라도 가능)
    assert r.status_code == 200, r.text
    ts = r.json()["tstar"]
    assert ts["frame_index"] == 8 and ts["source"] == "user" and ts["value"] == 0.008 and ts["elem_id"] == 102
    assert ts["manual"] == {"auto_frame": 6, "auto_time": 0.006, "auto_value": 0.02, "ratio": 0.4, "rel": "after",
                            "in_D": True, "have": True}
    assert calls[0][:2] == ("max_strain", 8) and calls[0][2]["case"]["part_title"] == case_r["part_title"]
    assert _get(client, case_r)["selected"]["manual"]["rel"] == "after"


def test_put_outside_d_fill_available(client, case_h, monkeypatch):
    _fake_point(monkeypatch)
    r = _put(client, case_h, 2)
    assert r.status_code == 200, r.text
    m = r.json()["tstar"]["manual"]
    assert r.json()["tstar"]["frame_index"] == 2 and m["rel"] == "before" and m["in_D"] is False and m["have"] is False


def test_put_outside_d_blocked_and_not_found(client, case_r, monkeypatch):
    _fake_point(monkeypatch)
    r = _put(client, case_r, 2)
    d = r.json()["detail"]
    assert r.status_code == 422 and d["code"] == "FRAME_NOT_EXTRACTABLE" and d["text"] == d["message"]
    assert d["reason"] == "NO_H3D" and "후보 프레임만" in d["text"]
    r = _put(client, case_r, 99)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "FRAME_NOT_FOUND"
    assert "h3d 에 없는 프레임" in r.json()["detail"]["message"]
    assert client.get(f"{API}/cases/{case_r['id']}", headers=R).json()["tstar"] is None       # 거절 = 저장 0


def test_put_rules_unchanged(client, case_h, monkeypatch):
    _fake_point(monkeypatch)
    bad = client.put(f"{API}/cases/{case_h['id']}/tstar", json={"version": case_h["version"], "metric": "nope",
                                                                "frame_index": 6}, headers=W)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_METRIC"
    assert _put(client, case_h, 2, headers=R).status_code == 403                               # 실행 권한
    assert _put(client, case_h, 2, version=case_h["version"] + 5).status_code == 409           # 버전 충돌
    assert _put(client, case_h, 2).status_code == 200


# ---------------------------------------------------------------- ESL 작업 사전 점검(§6.1)
def _support(engine, c):
    from esl_platform.core.repositories import cases as cases_repo

    with engine.begin() as conn:
        s = cases_repo.insert_support_set(conn, case_id=c["id"], node_ids=[1, 3, 7], dofs=[[0, 1, 2], [0, 1], [2]],
                                          source="auto", created_by="u")
        conn.execute(text("UPDATE cases SET current_support_set_id=:s WHERE id=:i"), {"s": s["id"], "i": c["id"]})


def test_esl_job_allows_manual_outside_d_when_fill_available(client, engine, case_h, monkeypatch):
    _fake_point(monkeypatch)
    assert _put(client, case_h, 2).status_code == 200
    _support(engine, case_h)
    r = client.post(f"{API}/cases/{case_h['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert r.status_code == 201, r.text
    with engine.connect() as c:
        p = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": r.json()["id"]}).scalar_one()
    assert p["frame_index"] == 2 and "disp_frame" not in json.dumps(p)


def test_esl_job_409_when_fill_blocked_or_not_manual(client, engine, case_h, monkeypatch):
    _fake_point(monkeypatch)
    assert _put(client, case_h, 2).status_code == 200
    _support(engine, case_h)
    with engine.connect() as c:
        os.remove(c.execute(text("SELECT h3d_path FROM cases WHERE id=:i"), {"i": case_h["id"]}).scalar_one())   # 입력 h3d 없음 → 채움 불가
    r = client.post(f"{API}/cases/{case_h['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert r.status_code == 409 and "disp_frame" in r.json()["detail"]["missing"]
    # manual 표지가 없는 t*(옛 저장 값)가 D 밖이면 지금처럼 409
    with engine.begin() as c:
        c.execute(text("UPDATE cases SET tstar = tstar - 'manual' WHERE id=:i"), {"i": case_h["id"]})
    r = client.post(f"{API}/cases/{case_h['id']}/jobs", json={"job_type": "ESL_SOLVE", "params": {}}, headers=W)
    assert r.status_code == 409 and "disp_frame" in r.json()["detail"]["missing"]


# ---------------------------------------------------------------- 설정 거울 (V-0252-17 백엔드·27)
def test_settings_mirror_and_ranges():
    from esl_platform.core.config import AltairCfg, BeadDoeCfg
    from pydantic import ValidationError

    a = AltairCfg()
    assert (a.frame_fill_timeout_s, a.frame_fill_wait_s) == (1800, 600)
    for bad in ({"frame_fill_timeout_s": 59}, {"frame_fill_wait_s": -1}):
        with pytest.raises(ValidationError):
            AltairCfg(**bad)
    d = BeadDoeCfg().model_dump()
    jg = d["rank"]["jig_grid"]
    assert jg["tie_force"] == {"enabled": True, "max_dist_mm": None, "normal_deg": 90.0}
    assert jg["tie_force_far_warn_mm"] == 10.0 and d["view3d"]["jig_force_marks_max"] == 512
    assert d["compare"]["double_sheet"] == {"enabled": True, "gap_min_t": 0.3, "gap_max_t": 3.0, "normal_deg": 15.0,
                                            "frac_warn": 0.5, "sample_max": 2000}
    from esl_platform.core.config import BeadDoeCompareDoubleSheetCfg, BeadDoeRankJigGridCfg, BeadDoeView3dCfg

    for cls, bad in ((BeadDoeRankJigGridCfg, {"tie_force": {"max_dist_mm": 0}}),
                     (BeadDoeRankJigGridCfg, {"tie_force": {"max_dist_mm": -1.0}}),
                     (BeadDoeRankJigGridCfg, {"tie_force": {"normal_deg": 0}}),
                     (BeadDoeRankJigGridCfg, {"tie_force": {"normal_deg": 91}}),
                     (BeadDoeRankJigGridCfg, {"tie_force_far_warn_mm": 0}),
                     (BeadDoeView3dCfg, {"jig_force_marks_max": 0}),
                     (BeadDoeCompareDoubleSheetCfg, {"gap_min_t": 0}),
                     (BeadDoeCompareDoubleSheetCfg, {"gap_min_t": 3.0, "gap_max_t": 3.0}),
                     (BeadDoeCompareDoubleSheetCfg, {"normal_deg": 90}),
                     (BeadDoeCompareDoubleSheetCfg, {"frac_warn": 0}),
                     (BeadDoeCompareDoubleSheetCfg, {"sample_max": 0})):
        with pytest.raises(ValidationError):
            cls(**bad)
    assert BeadDoeRankJigGridCfg(tie_force={"max_dist_mm": 20.0}).tie_force.max_dist_mm == 20.0


def test_example_yaml_mirror():
    import yaml
    from esl_platform.core.config import AltairCfg, BeadDoeCfg

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dd = BeadDoeCfg().model_dump()
    for name in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load(open(os.path.join(root, "config", name), encoding="utf-8"))
        assert y["altair"]["frame_fill_timeout_s"] == AltairCfg().frame_fill_timeout_s
        assert y["altair"]["frame_fill_wait_s"] == AltairCfg().frame_fill_wait_s
        b = y["bead_doe"]
        assert b["rank"]["jig_grid"]["tie_force"] == dd["rank"]["jig_grid"]["tie_force"]
        assert b["rank"]["jig_grid"]["tie_force_far_warn_mm"] == dd["rank"]["jig_grid"]["tie_force_far_warn_mm"]
        assert b["view3d"]["jig_force_marks_max"] == dd["view3d"]["jig_force_marks_max"]
        assert b["compare"]["double_sheet"] == dd["compare"]["double_sheet"]


def test_new_study_snapshot_carries_tie_force():
    """백엔드 rank_snapshot = jig_grid 블록 통째 복사(코드 변경 없음) — 새 스터디 스냅샷에 tie_force 가 따라온다. 옛 스냅샷 해석은 코어(LEGACY_ABSENT)."""
    from esl_platform.api.services.doe import rank_snapshot
    from esl_platform.core.config import BeadDoeCfg

    r = BeadDoeCfg().model_dump()["rank"]
    r["jig"] = {**r["jig"], "enabled": True}
    snap = rank_snapshot({"rank": r})
    assert snap["jig_grid"]["tie_force"] == {"enabled": True, "max_dist_mm": None, "normal_deg": 90.0}
    assert snap["jig_grid"]["tie_force_far_warn_mm"] == 10.0
    r["jig_grid"].pop("tie_force")
    assert "tie_force" not in rank_snapshot({"rank": r})["jig_grid"]                 # 키가 없으면 따라오지도 않음(옛 모양)


# ---------------------------------------------------------------- V-0252-27 결과·manifest 통과(스키마)
def test_result_schema_passthrough_and_absent_keys():
    from esl_platform.api.schemas import DoeJigGridOut, DoeRankViewOut, DoeResultOut, View3dOut, View3dSupport

    sup = View3dSupport(node_id=1, vertex=0, dof="xyz", x0=[0, 0, 0], via="force").model_dump()
    assert sup["via"] == "force"
    assert "via" not in View3dSupport(node_id=1, vertex=0, dof="xyz", x0=[0, 0, 0]).model_dump()
    base = dict(cell_mm=3.0, n_groups=1, n_shapes=2, n_shapes_failed=0)
    g = DoeJigGridOut(**base, n_forced_shapes=1, n_ref_shapes=1).model_dump()
    assert g["n_forced_shapes"] == 1 and g["n_ref_shapes"] == 1
    assert "n_forced_shapes" not in DoeJigGridOut(**base).model_dump()
    rv = dict(metric="solve", C_ref=1.0, baseline={}, n_ok=0, n_skipped={}, n_failed={"jd": 1}, ranking=[], per_esl_inline=False)
    v = DoeRankViewOut(**rv, n_ref=1, counts=[{"key": "ok", "label": "성공", "n": 0}]).model_dump()
    assert v["n_ref"] == 1 and v["counts"][0]["key"] == "ok"
    assert "n_ref" not in DoeRankViewOut(**rv).model_dump() and "counts" not in DoeRankViewOut(**rv).model_dump()
    top = dict(scenario=None, C_ref=1.0, baseline={}, n_ok=0, n_skipped={}, n_failed={"jd": 1}, ranking=[],
               boundary_warnings_n=0, view3d=[])
    d = DoeResultOut(**top, n_ref=2, counts=[{"key": "jd", "label": "지그 매핑 제외", "n": 1}]).model_dump()
    assert d["n_ref"] == 2 and d["counts"][0]["n"] == 1
    d0 = DoeResultOut(**top).model_dump()
    assert "n_ref" not in d0 and "counts" not in d0
    assert "tie_marks" not in View3dOut.model_json_schema().get("required", [])
    assert "tie_far_mm" not in View3dOut.model_json_schema().get("required", [])



def test_manifest_tie_far_mm_passthrough(tmp_path):
    """통합 INT(계약 §15): 실제 코어 build_view manifest — tie_marks 가 있을 때만 tie_far_mm(범례 임계), 옛 manifest = 두 키 없음."""
    import numpy as np
    from esl.view3d import build_view
    from esl_platform.api.schemas import View3dOut
    from opt_support import plate

    m = plate(nx=4, ny=3)
    f = np.zeros((m["node_id"].size, 3))
    f[:, 1] = 1.0
    urls = {"geometry_url": "g", "values_url": "v"}
    marks = [{"q": 0, "via": "force", "x": [0.0, 0.0, 0.0], "dist": 12.0, "n": 1, "far": True}]
    for sub, kw in (("new", {"tie_marks": marks, "tie_far_mm": 10.0}), ("old", {})):
        man = build_view(str(tmp_path / sub), node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], f=f,
                         u_rel=f * 0.01, supports=[{"node_id": int(m["node_id"][0]), "dof": "123"}], key="doe/d001",
                         esl_run_id="e1", created_at="2026-11-27T00:00:00Z", **kw)
        out = View3dOut.model_validate({**man, **urls}).model_dump(by_alias=True)
        if kw:
            assert out["tie_far_mm"] == 10.0 and out["tie_marks"] == marks
        else:
            assert "tie_marks" not in man and "tie_far_mm" not in man and "tie_marks" not in out and "tie_far_mm" not in out


def test_openapi_snapshot_current():
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "dump_openapi.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
