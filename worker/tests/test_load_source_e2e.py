"""v0.24.4 P3 통합(계약 esl_jig_case.md §9·부록 A.6): 하중 출처 선택 실연동 — 실제 PG·백엔드 API·워커·코어(A3 source_load·Target.supports)·
자체 솔버, 가짜 OptiStruct/hw·paicad. 입력 = 실제 형식의 Case 04_esl(코어 jig_bc 로 만든 지그 3방식 npz·bc 배열, 경계력 npz) + 항목 검증
05_val/sources.json(B3 가 읽는 형식).

(b) 비드 최적화: load_source 없음(옛 요청과 바이트 동일)·full(= 지금)·jig(translation+fixed → 지그 tie 123 지지)·jig_disp(422 UNSUPPORTED)·
    bforce FAIL(422 UNCONFIRMED → load_source_ack 재요청 성공)·하중 없음(422 UNAVAILABLE).
(a) 스터디: load_source jig_spring·bforce·없음 → 순위 기준·result.json load_source·metric_default·CSV·보고서.
``P3_E2E_DUMP=<경로>`` 이면 실제 응답을 프런트 픽스처 JSON 으로 저장(frontend/src/__tests__/fixtures/real_v0244_p3.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from esl_test_support import API, H
from sqlalchemy import text
from test_opt_e2e import create_run as _create_run_ok  # noqa: F401  (fixture 모듈 로드: tools·settings_dict)
from test_opt_e2e import make_s1, opt_settings, run_dir, run_job, tree, write_fake_tools  # noqa: F401
from test_val_src_api import FULL_ROW, sj_row

W = H("tok-power", True)
R = H("tok-power")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 OptiStruct/hw 는 POSIX 실행 스크립트")
JIG = ("jig", "jig_disp", "jig_spring")
OUT: dict[str, Any] = {}


@pytest.fixture()
def tools(tmp_path):
    return write_fake_tools(tmp_path)


@pytest.fixture()
def settings_dict(request, tmp_path, tools):
    if "study" in request.node.name:
        from doe_worker_support import doe_worker_settings, write_fake_paicad

        d = doe_worker_settings(tmp_path, write_fake_paicad(tmp_path))
        d["bead_doe"]["rank"] = {"jig": {"fix_kinds": ["RBE2"]}}      # 가짜 paicad 는 RBE2 종류 클러스터를 돌려줌
        d["bead_doe"]["bforce"] = {"enabled": True}                   # v0.24.5 §12: 기본 끔 — 경계력 출처 시험은 켠다
        return d
    return opt_settings(tmp_path, tools)


# ---------------------------------------------------------------- 실제 형식의 Case 출처 자료
def _entry_raw(esl_root: Path, eid: str) -> dict[str, np.ndarray]:
    z = np.load(esl_root / "_library" / "entries" / eid / "raw.npz")
    return {k: z[k] for k in z.files}


def _tie_nodes(x0: np.ndarray) -> np.ndarray:
    return np.array(sorted({int(np.argmin(np.linalg.norm(x0 - c, axis=1))) for c in
                            (x0.min(0), np.array([x0[:, 0].max(), 0.0, x0[:, 2].min()]),
                             np.array([x0[:, 0].min(), 0.0, x0[:, 2].max()]), x0.max(0))}), dtype=np.int64)


def write_case_esl(d: Path, raw: dict[str, np.ndarray], *, tie_dofs: str = "translation", bforce_scale: float = 1.1,
                   methods=("fixed", "prescribed", "spring")) -> np.ndarray:
    """Case 04_esl 흉내(코어 jig_bc 로 실제 구속 배열): u_rel.npz + 지그 방식 npz·json + bforce npz·json. f 는 항목 raw f 에 방식별 배율."""
    from esl.library import _util as U
    from esl.mech import jig_bc

    d.mkdir(parents=True, exist_ok=True)
    nid = np.asarray(raw["node_id"], dtype=np.int64)
    ur = np.asarray(raw["u_rel"], dtype=np.float64)
    np.savez(d / "u_rel.npz", node_id=nid, u_rel=ur)
    J = _tie_nodes(raw["x0"])
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    sup = [(pos[int(n)], str(dd)) for n, dd in zip(raw["support_node_id"], raw["support_dof"])]
    tie = jig_bc.tie_rows(raw, J, tie_dofs, kink_deg=45.0)
    aux = jig_bc.aux_rows(raw["x0"], sup, tie, tie_dofs, dup_deg=10.0)
    for k, m in enumerate(methods):
        row = jig_bc.METHODS[m]
        kk = np.full(np.asarray(tie["node"]).size, 50.0) if row["tie_stiff"] != "hard" else None
        BC = jig_bc.build_bc(row, tie, aux, ur, k=kk)
        np.savez(d / f"{row['src']}.npz", node_id=nid, f=np.asarray(raw["f"]) * (1.0 + 0.05 * k), u_val=ur,
                 **jig_bc.save_bc(BC), jig_idx=J)
        U.write_json(str(d / f"{row['src']}.json"), {"schema": "esl/case_jig/1", "source": row["src"], "method": m,
                                                      "tie_dofs": tie_dofs, "status": "ok", "code": None})
    np.savez(d / "bforce.npz", node_id=nid, f=np.asarray(raw["f"]) * bforce_scale, u_val=ur)
    U.write_json(str(d / "bforce.json"), {"grade": "full", "code": None, "reason": None})
    return J


def rows_for(**over):
    """항목 검증 출처 행(6): full PASS · bforce PASS 비교 가능 · 지그 3행 PASS · fint 결과 없음."""
    ok = dict(verdict="PASS", comparable=True)
    r = {"full": sj_row("full", **FULL_ROW), "bforce": sj_row("bforce", **ok),
         "fint": sj_row("fint", "unavailable", code="FINT_NO_DATA", reason="내력 하중 자료 없음"),
         "jig": sj_row("jig", **ok), "jig_disp": sj_row("jig_disp", verdict="PASS", comparable=True,
                                                         limits=["JIG_DISP_FROM_TARGET"], limit_text=["tie 변위를 낙하 결과에서 강제"]),
         "jig_spring": sj_row("jig_spring", **ok)}
    for k, v in over.items():
        r[k] = sj_row(k, **v)
    return [r[k] for k in ("jig", "jig_disp", "jig_spring", "full", "bforce", "fint")]


def seed_sources(engine, esl_root: Path, s1: dict, *, rows=None, **kw) -> dict[str, np.ndarray]:
    """S1 항목마다: 항목 meta source.case_dir, runs/<esl_run_id>/04_esl 출처 자료, 05_val/sources.json, library_entries.validation_id."""
    cdir = esl_root / "f_c1"
    for eid in s1["entry_ids"]:
        raw = _entry_raw(esl_root, eid)
        with engine.connect() as c:
            run_id, vid = c.execute(text("SELECT e.esl_run_id, v.id FROM library_entries e JOIN validations v ON "
                                         "v.esl_run_id = e.esl_run_id WHERE e.id=:i").bindparams(i=eid)).one()
        write_case_esl(cdir / "runs" / run_id / "04_esl", raw, **kw)
        snap = cdir / "runs" / run_id / "05_val"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "sources.json").write_text(json.dumps({"schema": "esl/val_sources/1", "default": "full", "enabled": True,
                                                        "rows": rows if rows is not None else rows_for()}), encoding="utf-8")
        (snap / "platform_validation_id.txt").write_text(vid, encoding="utf-8")
        with engine.begin() as c:
            c.execute(text("UPDATE library_entries SET validation_id=:v WHERE id=:i"), {"v": vid, "i": eid})
            c.execute(text("UPDATE validations SET scheme='disp_primary/1' WHERE id=:v"), {"v": vid})
        ej = esl_root / "_library" / "entries" / eid / "entry.json"
        meta = json.loads(ej.read_text(encoding="utf-8"))
        meta["source"] = {"case_dir": str(cdir), "run_id": run_id}
        ej.write_text(json.dumps(meta), encoding="utf-8")
    return _entry_raw(esl_root, s1["entry_ids"][0])


def _code(r):
    return r.json()["detail"]["code"]


def _post_opt(client, ids, **kw):
    return client.post(f"{API}/opt/runs", json={"project_id": "p-1", "scenario": "S1", "entry_ids": ids, **kw}, headers=W)


def _params(engine, jid):
    with engine.connect() as c:
        return c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": jid}).scalar_one()


def _dump() -> None:
    path = os.environ.get("P3_E2E_DUMP")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(OUT, fh, ensure_ascii=False, separators=(",", ":"), default=str)


# ================================================================ (b) 비드 최적화
def test_opt_load_source_e2e(client, engine, worker_factory, esl_root, inputs_root, tools):
    OUT.clear()
    s1 = make_s1(engine, esl_root, inputs_root)
    ids = s1["entry_ids"]
    seed_sources(engine, esl_root, s1)
    w = worker_factory()
    # ---- 묶음 판정(실제 응답)
    b = client.get(f"{API}/library/entries/sources", params={"ids": ",".join(ids)}, headers=R)
    assert b.status_code == 200, b.text
    OUT["entries_sources"] = b.json()
    by = {s["key"]: s for s in b.json()["sources"]}
    assert by["full"]["worst"] == "PASS" and by["jig"]["worst"] == "PASS" and by["bforce"]["unavailable_entry_ids"] == []
    assert by["jig_disp"]["worst"] == "caution" and by["jig_disp"]["needs_confirm"] is True      # JIG_DISP_FROM_TARGET = 주의
    assert by["fint"]["unavailable_entry_ids"] == ids                                           # 하중 파일 없음
    # ---- (0) load_source 없음: 옛 요청과 같은 params(load_source 키 없음) · 스냅샷 없음 · 3-2-1 지지
    r0 = _post_opt(client, ids)
    assert r0.status_code == 201, r0.text
    p0 = _params(engine, r0.json()["job_id"])
    assert "load_source" not in p0 and "load_source" not in p0["options"] and "load_source_check" not in r0.json()["options"]
    j = run_job(client, w, r0.json()["job_id"])
    t0 = json.loads((run_dir(esl_root, r0.json()["id"]) / "target" / "target.json").read_text())
    assert "load_source" not in (t0.get("source") or {}) and {s["dof"] for s in t0["supports"]} != {"123"}
    loads0 = np.load(run_dir(esl_root, r0.json()["id"]) / "load" / "loads.npz")
    f0 = {k: loads0[k].copy() for k in loads0.files}
    # ---- (1) full 명시 = 지금 동작: 하중 같음(load_source 스냅샷만 추가)
    r1 = _post_opt(client, ids, load_source="full")
    assert r1.status_code == 201, r1.text
    assert _params(engine, r1.json()["job_id"])["load_source"] == "full"
    assert r1.json()["options"]["load_source"] == "full" and r1.json()["options"]["load_source_check"]["worst"] == "PASS"
    run_job(client, w, r1.json()["job_id"])
    loads1 = np.load(run_dir(esl_root, r1.json()["id"]) / "load" / "loads.npz")
    assert set(loads1.files) == set(f0) and all(np.array_equal(loads1[k], f0[k]) for k in f0)
    OUT["opt_full"] = client.get(f"{API}/opt/runs/{r1.json()['id']}", headers=R).json()
    # ---- (2) jig(translation + fixed) → 지그 tie 123 지지가 Target.supports·덱 SPC1 로
    r2 = _post_opt(client, ids, load_source="jig")
    assert r2.status_code == 201, r2.text
    run_job(client, w, r2.json()["job_id"])
    rd2 = run_dir(esl_root, r2.json()["id"])
    t2 = json.loads((rd2 / "target" / "target.json").read_text())
    J = sorted(int(n) for n in _entry_raw(esl_root, ids[0])["node_id"][_tie_nodes(_entry_raw(esl_root, ids[0])["x0"])])
    assert [(s["node_id"], s["dof"]) for s in t2["supports"]] == [(n, "123") for n in J]
    assert t2["source"]["load_source"] == {"key": "jig", "support": "jig"}
    deck = "\n".join(p.read_text() for p in (rd2 / "deck").glob("*") if p.is_file())
    spc = sorted(int(x.split(",")[3]) for x in deck.splitlines() if x.startswith("SPC1,") and x.split(",")[2] == "123")
    assert spc == J                                                     # 선정·덱 같은 지지(Target.supports 한 곳)
    OUT["opt_jig"] = client.get(f"{API}/opt/runs/{r2.json()['id']}", headers=R).json()
    assert OUT["opt_jig"]["options"]["load_source"] == "jig"
    # ---- (3) jig_disp(prescribed) → 422 UNSUPPORTED, 확인(주의)보다 먼저
    r3 = _post_opt(client, ids, load_source="jig_disp")
    assert r3.status_code == 422 and _code(r3) == "LOAD_SOURCE_UNSUPPORTED", r3.text
    assert r3.json()["detail"]["reason"] and set(r3.json()["detail"]["entry_ids"]) == set(ids)
    OUT["err_unsupported"] = r3.json()
    # ---- (4) 하중 없음(fint) 422 UNAVAILABLE
    r4 = _post_opt(client, ids, load_source="fint")
    assert r4.status_code == 422 and _code(r4) == "LOAD_SOURCE_UNAVAILABLE", r4.text
    OUT["err_unavailable"] = r4.json()
    # ---- (5) 모르는 출처 422 INVALID_PARAMS
    assert _code(_post_opt(client, ids, load_source="nope")) == "INVALID_PARAMS"


def test_opt_fail_source_needs_ack_then_runs(client, engine, worker_factory, esl_root, inputs_root, tools):
    s1 = make_s1(engine, esl_root, inputs_root)
    ids = s1["entry_ids"]
    seed_sources(engine, esl_root, s1, rows=rows_for(bforce=dict(verdict="FAIL", fail_reasons=["DISP_RMS"], comparable=False,
                                                                 limits=["BF_TIE_MISSING"], limit_text=["tie 체결력 미포함"])))
    w = worker_factory()
    r = _post_opt(client, ids, load_source="bforce")
    assert r.status_code == 422 and _code(r) == "LOAD_SOURCE_UNCONFIRMED", r.text
    d = r.json()["detail"]
    assert d["worst"] == "FAIL" and {e["entry_id"] for e in d["entries"]} == set(ids)
    assert all(e["status"] == "FAIL" and e["comparable"] is False and e["grade"] == "FAIL" for e in d["entries"])
    OUT["err_unconfirmed"] = r.json()
    r2 = _post_opt(client, ids, load_source="bforce", load_source_ack=True)
    assert r2.status_code == 201, r2.text
    assert r2.json()["options"]["load_source"] == "bforce" and r2.json()["options"]["load_source_check"]["worst"] == "FAIL"
    run_job(client, w, r2.json()["job_id"])
    t = json.loads((run_dir(esl_root, r2.json()["id"]) / "target" / "target.json").read_text())
    assert t["source"]["load_source"]["key"] == "bforce"
    OUT["opt_bforce_ack"] = client.get(f"{API}/opt/runs/{r2.json()['id']}", headers=R).json()
    # 설정 노출(C3 가 읽음)
    OUT["opt_settings"] = client.get(f"{API}/opt/settings", headers=R).json()
    assert OUT["opt_settings"]["load_source_default"] == "full"
    _dump()


# ================================================================ (a) 스터디
from doe_support import api  # noqa: E402
from doe_worker_support import RULES, doe_worker_settings, set_control, write_fake_paicad  # noqa: E402
from test_doe_e2e import create as _doe_create  # noqa: E402
from test_doe_e2e import full_flow as _doe_full_flow  # noqa: E402
from test_doe_e2e import study as _doe_study  # noqa: E402


@pytest.fixture()
def exe(settings_dict):
    return Path(settings_dict["bead_doe"]["paicad"]["exe"])


def _study_flow(client, engine, worker_factory, esl_root, inputs_root, exe, **kw):
    set_control(exe, rules=RULES)
    w = worker_factory()
    w.heartbeat_once()
    s1 = make_s1(engine, esl_root, inputs_root)
    seed_sources(engine, esl_root, s1)
    s = _doe_create(client, s1["entry_ids"], title="P3 출처", **kw)
    out = _doe_full_flow(client, engine, w, esl_root, s, expect_ok=5, expect_skip={"collision": 1, "fixed": 1, "geom": 1},
                         expect_morph=1)
    return s, out, s1


@pytest.mark.parametrize("src", [None, "jig_spring", "bforce"])
def test_study_load_source_e2e(src, client, engine, worker_factory, esl_root, inputs_root, exe):
    kw = {"load_source": src} if src else {}
    if src == "bforce":
        kw["load_source_ack"] = True
    s, out, _s1 = _study_flow(client, engine, worker_factory, esl_root, inputs_root, exe, **kw)
    d = out["dir"]
    g = _doe_study(client, s["id"])
    res = json.loads((d / "post" / "result.json").read_text(encoding="utf-8"))
    csv = (d / "post" / "ranking.csv").read_text(encoding="utf-8-sig").splitlines()
    rep = api(client, "GET", f"/doe/studies/{s['id']}/report").text
    rr = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
    OUT[f"study_{src or 'none'}"] = {"study": {k: g[k] for k in ("id", "scenario", "inputs", "phase", "result_ready")},
                                     "result": {k: rr.get(k) for k in ("metric", "metric_effective", "load_source", "metric_default",
                                                                        "n_ok", "warnings")}}
    OUT["doe_settings"] = api(client, "GET", "/doe/settings").json()
    if src is None:
        # 옛 요청: 스냅샷·결과에 load_source 없음
        assert "load_source" not in g["inputs"] and "load_source" not in res and "metric_default" not in res
        OUT["study_none_metric"] = res.get("metric")
    else:
        assert g["inputs"]["load_source"] == src and g["inputs"]["load_source_check"]["key"] == src
        assert res["load_source"] == src and res.get("metric_default"), res.keys()
        assert rr["load_source"] == src and rr["metric_default"] == res["metric_default"], rr       # API 가 통과(B3)
        want = {"jig_spring": "js", "bforce": "bf"}[src]
        assert res["metric"] == want, (res["metric"], res.get("metric_default"), [w for w in res.get("warnings", []) if "LOAD_SOURCE" in str(w)])
        assert csv[0].split(",")[0]            # CSV 머리 존재
    if src == "jig_spring":
        ms = res["jig"]["methods"]
        assert "jig_spring" in ms and ms["jig_spring"]["status"] == "ok", ms
        assert "C_js" in csv[0].split(",")
        assert all(r.get("score") is not None for r in res["ranking"] if r.get("status", "OK") == "OK")
    assert rep and "<html" in rep.lower()
    _dump()
