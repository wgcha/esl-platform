"""변위 주지표 판정(계약 esl_disp_primary.md, v0.5.7) 플랫폼 E2E: 코어 합성 Case 를 API 로 ①~⑤ 완주 →
V-DP-10 워커 등록(schema 3 → 신규 컬럼, schema 2 → scheme NULL) · V-DP-11 status·/disp-field·/field flags
V-DP-12 라이브러리 등록 규칙 · V-DP-17 color_range_robust · V-DP-23 /section 확장.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest
import yaml
from esl_test_support import API, REPO, H, create_case, make_settings_dict
from sqlalchemy import text

sys.path.insert(0, str(REPO / "tests" / "library"))
import synth_lib  # noqa: E402

from esl.report import field as F  # noqa: E402

W = H("tok-power", True)
R = H("tok-power")
E2E_GRID = (6, 4)


@pytest.fixture()
def fs(request):
    return getattr(request, "param", "auto")


@pytest.fixture()
def settings_dict(tmp_path, fs):
    lib = yaml.safe_load((REPO / "config" / "library.example.yaml").read_text(encoding="utf-8"))
    lib["library"]["grid"] = {"nx": E2E_GRID[0], "ny": E2E_GRID[1]}
    lib["library"]["ista6"] = str(REPO / "config" / lib["library"]["ista6"])
    lp = tmp_path / "library.e2e.yaml"
    lp.write_text(yaml.safe_dump(lib, allow_unicode=True, sort_keys=False), encoding="utf-8")
    d = make_settings_dict(tmp_path, report={"auto": False}, library={"config_path": str(lp)})
    d["core"]["settings"]["validation"]["full_solve"] = fs
    return d


def _job(client, cid, job_type, params=None):
    r = client.post(f"{API}/cases/{cid}/jobs", json={"job_type": job_type, "params": params or {}}, headers=W)
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, worker, job):
    st = worker.run_once("SLOT")
    j = client.get(f"{API}/jobs/{job['id']}", headers=R).json()
    assert st == "SUCCEEDED" and j["state"] == "SUCCEEDED", (st, j["failure_code"], j["failure_message"])
    return j


def _through_validate(client, worker, create):
    r = create()
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _run(client, worker, _job(client, cid, "CASE_EXTRACT"))
    sug = client.post(f"{API}/cases/{cid}/support-sets/suggest", json={}, headers=W).json()
    assert client.post(f"{API}/cases/{cid}/support-sets", json={"node_ids": sug["node_ids"]}, headers=W).status_code == 201
    _run(client, worker, _job(client, cid, "ESL_SOLVE"))
    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    rid = case["current_esl_run_id"]
    _run(client, worker, _job(client, cid, "VALIDATE", {"esl_run_id": rid}))
    vid = client.get(f"{API}/cases/{cid}/validations", headers=R).json()[0]["id"]
    return cid, rid, vid


def _snap(esl_root, folder, rid, name):
    return os.path.join(str(esl_root), folder, "runs", rid, "05_val", name)


def _npz(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


# ================================================================ PASS: 등록·status·disp-field·field·section
def test_dp_pass_case_register_status_fields_section(client, synth_inputs, worker_factory, esl_root, engine):
    worker = worker_factory()
    cid, rid, vid = _through_validate(client, worker, lambda: create_case(client, synth_inputs))
    cdir = os.path.join(str(esl_root), "case01")
    vj = json.load(open(os.path.join(cdir, "05_val", "validation.json"), encoding="utf-8"))
    m = {x["metric"]: x for x in vj["metrics"]}

    # ---- V-DP-10 / V-DP-11: 등록 → API
    v = client.get(f"{API}/validations/{vid}", headers=R).json()
    assert vj["schema"] == "esl/validation/3"
    assert v["verdict"] == v["status"] == "PASS" and v["scheme"] == "disp_primary/1" and v["fail_reasons"] == []
    assert v["undetermined_reason"] is None
    assert v["disp_rms_rel"] == pytest.approx(m["disp_rms_rel"]["value"]) and v["disp_rms_rel"] < 1e-6
    assert v["disp_max_rel"] == pytest.approx(m["disp_max_rel"]["value"])
    assert v["disp_noise_rel"] == pytest.approx(m["disp_noise_rel"]["value"]) and 0 < v["disp_noise_rel"] < 1e-3
    assert v["reaction_rel"] == pytest.approx(m["reaction_rel"]["value"])
    assert v["disp"]["n_nodes"] == vj["disp"]["n_nodes"] == len(synth_inputs["node_id"]) and v["disp"]["hist"]["n"] > 0
    assert v["disp"]["top"][0]["node_id"] == v["disp"]["max_node_id"]
    sr = v["strain_ref"]
    assert sr["n_elems"] == len(synth_inputs["elem_id"]) and sr["n_exceed"] == vj["strain_ref"]["n_exceed"]
    assert sr["plastic"]["n_plastic"] > 0 and isinstance(sr["exceeded"], bool)
    assert v["criteria"]["disp_max_rel_max"] == 0.05 and v["criteria"]["disp_noise_rel_max"] == 1e-3
    # 산출물 스냅샷에 compare_disp.npz 포함(run 별 보존)
    assert os.path.isfile(_snap(esl_root, "case01", rid, "compare_disp.npz"))
    zd = _npz(_snap(esl_root, "case01", rid, "compare_disp.npz"))
    zf = _npz(_snap(esl_root, "case01", rid, "compare_field.npz"))
    N = zd["node_id"].size
    U = float(zd["U"])
    err = zd["e"] / U

    # ---- V-DP-11: /disp-field 3 레이어(전체 점, 다운샘플 없음)
    expect = {"err": err, "rel": np.linalg.norm(zd["d_rel"], axis=1), "val": np.linalg.norm(zd["d_val"], axis=1)}
    for layer, vals in expect.items():
        r = client.get(f"{API}/validations/{vid}/disp-field", params={"layer": layer}, headers=R)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["layer"] == layer and d["n_total"] == d["n_returned"] == N and d["decimated"] is False and d["cell"] is None
        assert d["U"] == pytest.approx(U) and set(d["plane"]) == {"origin", "e1", "e2"}
        pts = {p[0]: p for p in d["points"]}
        assert set(pts) == set(zd["node_id"].tolist())
        for i in (0, N // 2, N - 1):
            p = pts[int(zd["node_id"][i])]
            assert p[1] == pytest.approx(zd["ab"][i, 0]) and p[2] == pytest.approx(zd["ab"][i, 1])
            assert p[3] == pytest.approx(vals[i], rel=1e-12, abs=0) and p[4] == int(zd["is_support"][i])
        assert {p[0] for p in d["points"] if p[4] == 1} == {int(x) for x in zd["node_id"][zd["is_support"]]} and len(
            [p for p in d["points"] if p[4]]) == 3
        # V-DP-17: color_range(전체 min/max) + color_range_robust(zero, P99 올림)
        if layer == "err":
            assert d["color_range"] == {"min": 0.0, "max": pytest.approx(err.max())}
            rob_raw = float(np.percentile(err, 99))
        else:
            both = np.concatenate([expect["rel"], expect["val"]])
            assert d["color_range"] == {"min": pytest.approx(both.min()), "max": pytest.approx(both.max())}
            rob_raw = float(np.percentile(both, 99))
        rb = d["color_range_robust"]
        assert rb["min"] == 0.0 and rb["max"] == F.ceil2(rob_raw) and rb["basis"] == "p99" and rb["raw"] == pytest.approx(rob_raw)

    # ---- 다운샘플: 셀 대표 = e 최대 노드(최대 보존), robust 범위는 다운샘플과 무관(전체 집합)
    full = client.get(f"{API}/validations/{vid}/disp-field", params={"layer": "err"}, headers=R).json()
    dec = client.get(f"{API}/validations/{vid}/disp-field", params={"layer": "err", "max_points": 100}, headers=R).json()
    assert dec["decimated"] is True and dec["n_total"] == N and dec["n_returned"] <= 100 and dec["cell"]
    assert dec["color_range_robust"] == full["color_range_robust"] and dec["color_range"] == full["color_range"]
    imax = int(np.argmax(zd["e"]))
    top = [p for p in dec["points"] if p[0] == int(zd["node_id"][imax])]
    assert top and top[0][3] == pytest.approx(err.max())                  # 전체 최대 노드가 그대로 남음
    byid = {p[0]: p[3] for p in full["points"]}
    assert all(p[3] == pytest.approx(byid[p[0]]) for p in dec["points"])
    dx, dy = dec["cell"]
    amin = min(p[1] for p in full["points"])
    bmin = min(p[2] for p in full["points"])
    nx_ = int(round((max(p[1] for p in full["points"]) - amin) / dx)) or 1
    ny_ = int(round((max(p[2] for p in full["points"]) - bmin) / dy)) or 1
    cells: dict = {}
    for p in full["points"]:
        key = (min(int((p[1] - amin) // dx), nx_ - 1), min(int((p[2] - bmin) // dy), ny_ - 1))
        cells.setdefault(key, []).append(p)
    kept = {p[0] for p in dec["points"]}
    assert len(kept) == len(dec["points"]) == len(cells)                    # 셀마다 정확히 1개
    for ps in cells.values():                                              # 각 셀의 대표 = 그 셀의 e 최대 노드
        assert max(ps, key=lambda p: p[3])[0] in kept
    assert client.get(f"{API}/validations/{vid}/disp-field", params={"layer": "bad"}, headers=R).status_code == 422

    # ---- /field: flags 열(1 = 초과, 2 = 소성), color_range_robust (err sym / rad·esl minmax)
    for layer in ("err", "rad", "esl"):
        f = client.get(f"{API}/validations/{vid}/field", params={"layer": layer}, headers=R).json()
        assert all(len(p) == 6 for p in f["points"])
        eid_pos = {int(e): i for i, e in enumerate(zf["elem_id"])}
        for p in f["points"][:: max(1, len(f["points"]) // 60)]:
            i = eid_pos[p[0]]
            assert p[5] == int(zf["exceed"][i]) + 2 * int(zf["plastic"][i])
        assert any(p[5] & 2 for p in f["points"])                          # 합성 사례에는 소성 요소가 있음
        if layer == "err":
            ev = 100.0 * zf["rel_err"][zf["valid"]]
            rb = f["color_range_robust"]
            R_ = F.ceil2(float(np.percentile(np.abs(ev), 99)))
            assert rb == {"min": -R_, "max": R_, "basis": "p99", "raw": pytest.approx(np.percentile(np.abs(ev), 99))}
            assert f["color_range"]["max"] == -f["color_range"]["min"]      # 기존 키 유지
        else:
            both = np.concatenate([zf["eps_rad"][np.isfinite(zf["eps_rad"])], zf["eps_esl"][np.isfinite(zf["eps_esl"])]])
            rb = f["color_range_robust"]
            assert rb["min"] == pytest.approx(both.min()) and rb["max"] == F.ceil2(float(np.percentile(both, 99)))
    fd = client.get(f"{API}/validations/{vid}/field", params={"layer": "err", "max_points": 100}, headers=R).json()
    f0 = client.get(f"{API}/validations/{vid}/field", params={"layer": "err"}, headers=R).json()
    assert fd["decimated"] and fd["color_range_robust"] == f0["color_range_robust"]

    # ---- V-DP-23: /section (기본 axis = eta, at 에 따라 달라짐, 확장 키)
    s5 = client.get(f"{API}/validations/{vid}/section", headers=R).json()
    assert s5["axis"] == "eta" and s5["at"] == 0.5
    assert {"dw", "stats", "has_val", "line", "units", "suggest", "s", "w_rad", "w_esl", "w0", "band", "n_elems"} <= set(s5)
    s2 = client.get(f"{API}/validations/{vid}/section", params={"at": 0.2}, headers=R).json()
    s8 = client.get(f"{API}/validations/{vid}/section", params={"at": 0.8}, headers=R).json()
    assert s2["at"] == 0.2 and s8["at"] == 0.8 and s2["n_elems"] > 0 and s8["n_elems"] > 0
    assert s2["w_rad"] != s8["w_rad"] and s2["line"]["b0"] != s8["line"]["b0"]
    assert client.get(f"{API}/validations/{vid}/section", params={"at": 1.5}, headers=R).status_code == 422
    for s in (s5, s2, s8):
        assert s["has_val"] is True and s["units"] == "mm"
        assert len(s["dw"]) == len(s["s"]) == len(s["w_rad"]) == len(s["w_esl"]) == len(s["w0"]) > 2
        assert np.allclose(s["dw"], np.array(s["w_esl"]) - np.array(s["w_rad"]), atol=1e-15)
        st = s["stats"]
        assert st["U"] == pytest.approx(U) and st["dw_max_abs"] == pytest.approx(np.abs(s["dw"]).max())
        assert st["s_at_dw_max"] == pytest.approx(s["s"][int(np.argmax(np.abs(s["dw"])))])
        assert st["dw_rms"] == pytest.approx(np.sqrt(np.mean(np.square(s["dw"]))))
        assert st["dw_max_rel"] == pytest.approx(st["dw_max_abs"] / U) and st["dw_rms_rel"] == pytest.approx(st["dw_rms"] / U)
        assert st["w_max_abs"] == pytest.approx(max(np.abs(s["w_rad"]).max(), np.abs(s["w_esl"]).max()))
    xr, er = zf["xi_range"], zf["eta_range"]
    ln = s2["line"]                                                        # axis=eta: η 고정, ξ 양 끝
    assert ln["xi_range"] == pytest.approx(list(xr)) and ln["eta_range"] == pytest.approx(list(er))
    assert (ln["a0"], ln["a1"]) == (pytest.approx(xr[0]), pytest.approx(xr[1]))
    assert ln["b0"] == ln["b1"] == pytest.approx(er[0] + 0.2 * (er[1] - er[0])) and ln["band_abs"] == pytest.approx(
        s2["band"] * (er[1] - er[0]))
    sx = client.get(f"{API}/validations/{vid}/section", params={"axis": "xi", "at": 0.3}, headers=R).json()
    assert sx["axis"] == "xi" and sx["line"]["a0"] == sx["line"]["a1"] == pytest.approx(xr[0] + 0.3 * (xr[1] - xr[0]))
    assert (sx["line"]["b0"], sx["line"]["b1"]) == (pytest.approx(er[0]), pytest.approx(er[1]))
    sug = {x["key"]: x for x in s5["suggest"]}
    assert set(sug) == {"max_disp_err", "hotspot1"}
    assert sug["max_disp_err"]["id"] == int(zd["node_id"][imax])
    a, b = zd["ab"][imax]
    assert sug["max_disp_err"]["xi"] == pytest.approx(min(1.0, max(0.0, (a - xr[0]) / (xr[1] - xr[0]))))
    assert sug["max_disp_err"]["eta"] == pytest.approx(min(1.0, max(0.0, (b - er[0]) / (er[1] - er[0]))))
    h1 = v["hotspots"][0]["elem_id"]
    k = int(np.flatnonzero(zf["elem_id"] == h1)[0])
    c = zf["centroid2d"][k]
    assert sug["hotspot1"]["id"] == h1
    assert sug["hotspot1"]["xi"] == pytest.approx(min(1.0, max(0.0, (c[0] - xr[0]) / (xr[1] - xr[0]))))
    assert sug["hotspot1"]["eta"] == pytest.approx(min(1.0, max(0.0, (c[1] - er[0]) / (er[1] - er[0]))))
    assert all(x["label"] for x in s5["suggest"])

    # ---- compare_disp.npz 가 없으면(UNDETERMINED·LEGACY 와 같은 상태): disp-field 409, section has_val=false
    for p in (_snap(esl_root, "case01", rid, "compare_disp.npz"), os.path.join(cdir, "05_val", "compare_disp.npz")):
        if os.path.isfile(p):
            os.remove(p)
    r = client.get(f"{API}/validations/{vid}/disp-field", headers=R)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    assert r.json()["detail"]["missing"] == ["disp_compare"]
    sn = client.get(f"{API}/validations/{vid}/section", headers=R).json()
    assert sn["has_val"] is False and sn["dw"] == [] and [x["key"] for x in sn["suggest"]] == ["hotspot1"]
    assert sn["stats"]["w_max_abs"] is not None and all(
        sn["stats"][k] is None for k in ("dw_max_abs", "s_at_dw_max", "dw_rms", "U", "dw_max_rel", "dw_rms_rel"))
    assert len(sn["w_rad"]) == len(s5["w_rad"]) and sn["line"] == s5["line"]
    # 산출물 폴더 자체가 없어지면 기존 409 VALIDATION_FILES_GONE 규칙(여기서는 스냅샷·Case 모두 지우지 않음) — 유지 확인
    assert client.get(f"{API}/validations/{vid}/field", headers=R).status_code == 200

    # ---- 이전 판정 체계(LEGACY): scheme NULL → status LEGACY, verdict 는 당시 값 그대로
    with engine.begin() as c:
        c.execute(text("UPDATE validations SET scheme = NULL, disp = NULL, strain_ref = NULL WHERE id = :i"), {"i": vid})
    lv = client.get(f"{API}/validations/{vid}", headers=R).json()
    assert lv["status"] == "LEGACY" and lv["verdict"] == "PASS" and lv["scheme"] is None

    # ---- V-DP-10: schema 2 validation.json 등록 → scheme NULL(LEGACY)·신규 컬럼 NULL, 알 수 없는 scheme/미완 UNDETERMINED 거부
    from esl_platform.core.repositories import cases as cases_repo
    from esl_worker import register as reg

    case = client.get(f"{API}/cases/{cid}", headers=R).json()
    jobs = client.get(f"{API}/cases/{cid}/jobs", headers=R).json()
    vjob = next(j for j in jobs if j["job_type"] == "VALIDATE")
    path = os.path.join(cdir, "05_val", "validation.json")
    base = json.load(open(path, encoding="utf-8"))

    def register(mutate):
        d = json.loads(json.dumps(base))
        mutate(d)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        with engine.begin() as c:
            return reg.register_validation(c, vjob, case, cdir)

    def legacy(d):
        for k in ("verdict_scheme", "undetermined_reason", "disp", "strain_ref", "noise_source"):
            d.pop(k, None)
        d["schema"] = "esl/validation/2"
        d["metrics"] = [{k: x for k, x in mm.items() if k not in ("role", "exceeded")} for mm in d["metrics"]
                        if mm["metric"] not in ("disp_max_rel", "disp_noise_rel")] + [
            {"metric": "disp_max_rel", "value": 0.001, "criterion": None, "pass": None}]

    out = register(legacy)
    assert out["status"] == "LEGACY" and out["verdict"] == "PASS"
    with engine.connect() as c:
        row = cases_repo.get_validation(c, out["validation_id"])
    assert row["scheme"] is None and row["disp_noise_rel"] is None and row["disp"] is None and row["strain_ref"] is None
    assert row["undetermined_reason"] is None and row["disp_max_rel"] == pytest.approx(0.001)
    out3 = register(lambda d: None)                                        # schema 3 그대로
    with engine.connect() as c:
        row3 = cases_repo.get_validation(c, out3["validation_id"])
    assert out3["status"] == "PASS" and row3["scheme"] == "disp_primary/1" and row3["disp"]["n_nodes"] == N
    assert row3["disp_noise_rel"] == pytest.approx(m["disp_noise_rel"]["value"]) and row3["strain_ref"]["n_elems"] == len(
        synth_inputs["elem_id"])

    def undetermined(d):
        d["verdict"], d["undetermined_reason"], d["fail_reasons"] = "UNDETERMINED", "ZERO_DISP", []

    ud = register(undetermined)
    assert ud["status"] == "UNDETERMINED" and ud["undetermined_reason"] == "ZERO_DISP"
    for bad in (lambda d: d.update(verdict="UNDETERMINED", undetermined_reason=None),
                lambda d: d.update(verdict="UNDETERMINED", undetermined_reason="X", verdict_scheme=None),
                lambda d: d.update(verdict_scheme="future/9"), lambda d: d.update(verdict="MAYBE")):
        with pytest.raises(reg.RegisterError) as ei:
            register(bad)
        assert ei.value.code == "OUTPUT_INVALID"


# ================================================================ UNDETERMINED: full_solve never
@pytest.mark.parametrize("fs", ["never"], indirect=True)
def test_dp_undetermined_case_api(client, synth_inputs, worker_factory, esl_root):
    worker = worker_factory()
    cid, rid, vid = _through_validate(client, worker, lambda: create_case(client, synth_inputs))
    v = client.get(f"{API}/validations/{vid}", headers=R).json()
    assert v["verdict"] == v["status"] == "UNDETERMINED" and v["scheme"] == "disp_primary/1"
    assert v["undetermined_reason"] == "NO_FULL_SOLVE" and v["fail_reasons"] == []
    assert v["disp_rms_rel"] is None and v["disp_max_rel"] is None and v["reaction_rel"] is None and v["disp"] is None
    assert v["disp_noise_rel"] is not None and v["strain_ref"]["n_elems"] == len(synth_inputs["elem_id"])
    assert v["criteria"]["full_solve"] == "never"
    assert not os.path.exists(_snap(esl_root, "case01", rid, "compare_disp.npz"))
    r = client.get(f"{API}/validations/{vid}/disp-field", headers=R)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PREREQUISITE_MISSING"
    assert r.json()["detail"]["missing"] == ["disp_compare"]
    s = client.get(f"{API}/validations/{vid}/section", headers=R).json()
    assert s["has_val"] is False and s["dw"] == [] and [x["key"] for x in s["suggest"]] == ["hotspot1"]
    f = client.get(f"{API}/validations/{vid}/field", headers=R).json()                  # 변형률 참고 지도는 그대로
    assert f["n_returned"] > 0 and f["color_range_robust"] is not None
    # 이력(작업 → 검증 요약)에도 status, 검증 이력 검토(review)에 status
    hist = client.get(f"{API}/history", params={"project_id": "p-1", "case_id": cid}, headers=R)
    assert hist.status_code == 200, hist.text
    vitem = next(i for i in hist.json()["items"] if i["job_type"] == "VALIDATE")
    assert vitem["summary"]["status"] == "UNDETERMINED" and vitem["summary"]["verdict"] == "UNDETERMINED"
    assert vitem["summary"]["disp_rms_rel"] is None and vitem["summary"]["disp_max_rel"] is None


# ================================================================ V-DP-12 라이브러리 등록 규칙
def _lib_case(client, worker, inputs_root, k, esl_root):
    model, sc, nx, ny, pat, ori = ("50QX10A", 1.0, 24, 16, "A", "Corner146")
    dt = "Corner"
    h3d = f"F:/Hyper_work/VD_26y/{model}/{model}_v001_261019/FREE/{k + 1:02d}_{dt}_Drop_1st_Scene{k + 1}_{ori}_comp.h3d"
    c = synth_lib.build(str(inputs_root / f"lib{k}"), h3d, sc, nx, ny, pat, 1.0)
    return _through_validate(client, worker, lambda: create_case(client, {"rad": c["rad"], "csv": c["csv"]},
                                                                  folder=f"lib{k}", title=f"lib{k}"))


@pytest.mark.parametrize("fs", ["never"], indirect=True)
def test_dp12_library_undetermined_requires_reason(client, worker_factory, inputs_root, esl_root):
    worker = worker_factory()
    cid, rid, vid = _lib_case(client, worker, inputs_root, 0, esl_root)
    assert client.get(f"{API}/validations/{vid}", headers=R).json()["status"] == "UNDETERMINED"
    r = client.post(f"{API}/library/entries", json={"esl_run_id": rid}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_NOT_PASS"
    assert r.json()["detail"]["verdict"] == "UNDETERMINED"
    r = client.post(f"{API}/library/entries", json={"esl_run_id": rid, "force_reason": "  "}, headers=W)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_NOT_PASS"
    r = client.post(f"{API}/library/entries", json={"esl_run_id": rid, "force_reason": "전체 재해석 생략, 변형률 참고만 확인"},
                    headers=W)
    assert r.status_code == 201, r.text
    e = r.json()
    q = e["quality"]
    assert q["verdict"] == q["status"] == "UNDETERMINED" and q["scheme"] == "disp_primary/1"
    assert q["undetermined_reason"] == "NO_FULL_SOLVE" and q["fail_reasons"] == []
    assert q["confirmed_undetermined"]["reason"].startswith("전체 재해석") and q["confirmed_undetermined"]["by"] == "u-power"
    assert q["confirmed_undetermined"]["at"] and q["confirmed_fail"] is None
    assert q["strain_exceed_frac"] is not None and q["disp_max_rel"] is None
    assert e["validation_id"] == vid
    # 필터
    ids = lambda v: {x["id"] for x in client.get(f"{API}/library/entries", params={"project_id": "p-1", "verdict": v},  # noqa: E731
                                                  headers=R).json()}
    assert ids("UNDETERMINED") == {e["id"]} and ids("LEGACY") == set() and ids("PASS") == set()


def test_dp12_library_pass_and_legacy(client, worker_factory, inputs_root, esl_root, engine):
    worker = worker_factory()
    cid, rid, vid = _lib_case(client, worker, inputs_root, 0, esl_root)
    assert client.get(f"{API}/validations/{vid}", headers=R).json()["status"] == "PASS"
    r = client.post(f"{API}/library/entries", json={"esl_run_id": rid}, headers=W)       # PASS: 사유 불필요
    assert r.status_code == 201, r.text
    q = r.json()["quality"]
    assert q["status"] == q["verdict"] == "PASS" and q["scheme"] == "disp_primary/1" and q["confirmed_fail"] is None
    assert q["confirmed_undetermined"] is None and q["disp_max_rel"] is not None and q["disp_noise_rel"] is not None
    assert q["strain_exceed_frac"] is not None and q["undetermined_reason"] is None
    # 이전 판정 체계(LEGACY): schema 2 산출물 + DB scheme NULL → 당시 verdict(PASS) 규칙, quality.scheme 없음
    cid2, rid2, vid2 = _lib_case(client, worker, inputs_root, 1, esl_root)
    cdir = os.path.join(str(esl_root), "lib1")
    for p in (os.path.join(cdir, "05_val", "validation.json"), _snap(esl_root, "lib1", rid2, "validation.json")):
        d = json.load(open(p, encoding="utf-8"))
        for k in ("verdict_scheme", "undetermined_reason", "disp", "strain_ref", "noise_source"):
            d.pop(k, None)
        d["schema"] = "esl/validation/2"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    with engine.begin() as c:
        c.execute(text("UPDATE validations SET scheme = NULL WHERE id = :i"), {"i": vid2})
    assert client.get(f"{API}/validations/{vid2}", headers=R).json()["status"] == "LEGACY"
    r2 = client.post(f"{API}/library/entries", json={"esl_run_id": rid2}, headers=W)
    assert r2.status_code == 201, r2.text
    q2 = r2.json()["quality"]
    assert q2["verdict"] == "PASS" and q2["scheme"] is None and q2["status"] == "LEGACY" and q2["confirmed_fail"] is None
    ids = lambda v: {x["id"] for x in client.get(f"{API}/library/entries", params={"project_id": "p-1", "verdict": v},  # noqa: E731
                                                  headers=R).json()}
    assert ids("LEGACY") == {r2.json()["id"]} and ids("PASS") == {r.json()["id"]} and ids("UNDETERMINED") == set()
    # LEGACY FAIL(당시 FAIL)은 기존 규칙대로 사유 필수
    with engine.begin() as c:
        c.execute(text("UPDATE validations SET verdict = 'FAIL' WHERE id = :i"), {"i": vid2})
    r3 = client.post(f"{API}/library/entries/{r2.json()['id']}/retire", json={"reason": "재등록"}, headers=W)
    assert r3.status_code == 200, r3.text
    for p in (os.path.join(cdir, "05_val", "validation.json"), _snap(esl_root, "lib1", rid2, "validation.json")):
        d = json.load(open(p, encoding="utf-8"))
        d["verdict"], d["fail_reasons"] = "FAIL", ["DISP_RMS"]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    r4 = client.post(f"{API}/library/entries", json={"esl_run_id": rid2}, headers=W)
    assert r4.status_code == 422 and r4.json()["detail"]["code"] == "VALIDATION_NOT_PASS"
    r5 = client.post(f"{API}/library/entries", json={"esl_run_id": rid2, "force_reason": "당시 FAIL 확인"}, headers=W)
    assert r5.status_code == 201, r5.text
    q5 = r5.json()["quality"]
    assert q5["verdict"] == "FAIL" and q5["status"] == "LEGACY" and q5["confirmed_fail"]["reason"] == "당시 FAIL 확인"
