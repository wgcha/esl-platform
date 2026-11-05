"""v0.16.1 select 완화 워커 시험(계약 esl_select_relax.md V-SR-10·11) — 실제 PG·백엔드 API·워커·코어·자체 솔버, 가짜 paicad
(fixed-scan 만), 합성 비드 메시(tests/doe/synth_bead.py, h 10 mm), 기본 warn 정책.

- V-SR-10 sha·이어하기: hold 없는 v0.16.0 선택 → 선택 sha 상수(v0.16.0 값), hold_fixed 1 → 다름; 기본 설정 _cfg_hash·_sel_cfg_sha =
  v0.16.0 상수; algo 없는 basis.json → 다시 미리보기에서 1회 재계산 → basis.npz 바이트·basis_sha 동일 → 다시 실행 시 안 재사용;
  v0.16.0 SKIPPED_FIXED done.json(같은 키) + warn → 워커가 재사용하지 않고 코어가 다시 판정·해석(OK), OK done.json → 재사용.
- V-SR-11 받기·보고서: 경고 안 best/<did> rad 사본 = 원본과 "첫 /NODE 앞 #ESL 주석 줄 + /NODE 좌표 칸" 외 바이트 동일(주석 ASCII·
  원본 줄바꿈), ch_r.rad 머리 주석, values.json warnings; 경고 없는 안 = 주석 없음(v0.16.0 V-BS-14 그대로); 보고서 "체결 위치
  어긋남" 절·⚠ 열, 결과 summary.best_clean.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
from doe_support import api
from doe_worker_support import doe_worker_settings
from esl_test_support import API, REPO
from test_doe_select_jobs import (  # noqa: F401 - 픽스처
    R,
    create,
    exe,
    make_bead_case,
    node_block_diff,
    preview,
    ring_selection,
    run_job,
    save_selection,
    start_run,
    strip_esl_comments,
    study,
    worker,
)

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_bead as sb  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")

# v0.16.0(ef7545c) 트리에서 같은 입력으로 계산한 값 — 기본 설정이면 v0.16.1 도 같아야 함(SR-D-13a·b, R-SR-5)
V0160_CFG_HASH = "760376b6612dbfd19306ae70ecc9b9eb03a6e746d4fd3df6d0ad56bbb75e2aa3"        # {"bead_doe": {"enabled": True}}
V0160_SEL_CFG_SHA = "f418f00122265715f642cf6df2a91c1a4dbcf15184ac13294a333244b11f0d9d"
V0160_SELECTION_SHA = "07cff387f716a81bbdcecec66feea2abd21cfd73fd0351e2019ea6d866f04b75"   # sb.selection(sb.generate(10))
B1_W_NOM = 58.7175


@pytest.fixture()
def settings_dict(tmp_path, exe):  # noqa: F811
    """받기 사본을 순위 전부에(keep_files_top·view3d.top_k 10) — 경고 안·경고 없는 안 사본을 함께 본다."""
    return doe_worker_settings(tmp_path, exe, paicad={"keep_files_top": 10}, view3d={"top_k": 10})


def test_v0160_hashes_unchanged():
    """V-SR-10(상수): 기본 설정 _cfg_hash·_sel_cfg_sha·선택 sha = v0.16.0 값, hold_fixed 1 → 선택 sha 다름."""
    from esl.doe import bead_select as bs
    from esl.doe import settings
    from esl.doe import stages as stg

    td = tempfile.mkdtemp()
    c = stg.Ctx({"stage": "bd_eval", "out": td,
                 "doe": {"id": "R1", "scenario": "select", "cfg": {"bead_doe": {"enabled": True}}, "entries": []}})
    assert stg._cfg_hash(c) == V0160_CFG_HASH and stg._sel_cfg_sha(c) == V0160_SEL_CFG_SHA
    cfg = settings({"bead_doe": {"enabled": True}})
    g = sb.generate(10.0)
    sel = sb.selection(g)
    assert bs.selection_sha256(bs.normalize_input(sel, cfg)) == V0160_SELECTION_SHA
    sel["beads"][0]["hold_fixed"] = 1
    assert bs.selection_sha256(bs.normalize_input(sel, cfg)) != V0160_SELECTION_SHA
    sel["beads"][0]["hold_fixed"] = 0                                         # 0 = 생략과 같음(SR-D-13a)
    assert bs.selection_sha256(bs.normalize_input(sel, cfg)) == V0160_SELECTION_SHA


def _job_log(client, jid, step) -> str:
    return client.get(f"{API}/jobs/{jid}/log", params={"step": step}, headers=R).text


def test_select_warn_resume_and_best_comments(client, engine, worker, esl_root, inputs_root, exe):
    w = make_bead_case(engine, esl_root, inputs_root)
    s = create(client, w["entry_ids"])
    run_job(client, worker, s["job"]["id"])
    s = save_selection(client, study(client, s["id"]), ring_selection(w["g"]))
    sel_sha = s["selection"]["sha256"]
    spec = {"method": "fullfact", "levels": 2, "params": [{"name": "B1_W", "lo": B1_W_NOM, "hi": 70.435},
                                                          {"name": "B2_W", "lo": 33.5, "hi": 42.0}]}
    p = preview(client, s, spec)
    run_job(client, worker, p["job"]["id"])
    g = study(client, s["id"])
    d = esl_root / "_doe" / s["id"]
    rev = g["doe"]["rev"]
    pv = g["doe"]["preview"]
    cells = {c["id"]: c for c in pv["cells"]}
    mx = json.loads((d / "doe" / str(rev) / "matrix.json").read_text())
    vals = {x["id"]: x["values"] for x in mx["designs"] if x["id"] != "d000"}
    clean = {i for i, v in vals.items() if abs(v["B1_W"] - B1_W_NOM) < 0.01}
    moved = set(vals) - clean
    assert len(clean) >= 1 and len(moved) == 2, vals
    assert all(c["status"] == "READY" for c in cells.values()) and pv["ok"] == len(vals) and pv["warn"] == 2
    for i in moved:
        assert [x["code"] for x in cells[i]["warnings"]] == ["SELECT_FIXED_MOVED"] and cells[i]["fixed_viol"]["n"] > 0
    # V-SR-10 algo 없는 basis.json(v0.16.0 기저) → 다시 미리보기에서 1회 재계산, 바이트·basis_sha 동일
    sdir = d / "select" / sel_sha[:12]
    bj = json.loads((sdir / "basis.json").read_text())
    assert bj["algo"] == 2
    npz0 = (sdir / "basis.npz").read_bytes()
    (sdir / "basis.json").write_text(json.dumps({k: v for k, v in bj.items() if k != "algo"}))
    p2 = preview(client, g, spec)
    j2 = run_job(client, worker, p2["job"]["id"])
    assert "기저 재사용" not in _job_log(client, j2["id"], 1)
    assert (sdir / "basis.npz").read_bytes() == npz0 and json.loads((sdir / "basis.json").read_text())["algo"] == 2
    g = study(client, s["id"])
    man2 = json.loads((d / "doe" / str(g["doe"]["rev"]) / "grid" / "grid_manifest.json").read_text())
    assert man2["basis_sha256"] == bj["basis_sha256"] and man2["rules"] == 2
    # 실행: 경고 안도 실행·순위(SR-D-11)
    r = start_run(client, g)
    j1 = run_job(client, worker, r["job"]["id"])
    res = api(client, "GET", f"/doe/studies/{s['id']}/results").json()
    assert {x["id"] for x in res["ranking"]} == set(vals)
    assert {x["id"] for x in res["ranking"] if x.get("warn")} == moved
    assert res["summary"]["best_clean"] == next(x["id"] for x in res["ranking"] if x["id"] in clean)
    # V-SR-11 받기 사본
    orig = w["rad"].read_bytes()
    eol = b"\r\n" if b"\r\n" in orig else b"\n"
    for did in vals:
        bd = d / "best" / did
        inc = (bd / "include" / w["rad"].name).read_bytes()
        chr_ = (bd / "ch_r.rad").read_bytes()
        vj = json.loads((bd / "values.json").read_text(encoding="utf-8"))
        if did in clean:
            assert b"#ESL" not in inc and b"#ESL" not in chr_ and not vj.get("warnings")
            n_moved, bad = node_block_diff(orig, inc)
            assert bad == 0 and n_moved > 0                                     # v0.16.0 V-BS-14 그대로(/NODE 좌표만)
            continue
        lines = inc.splitlines(keepends=True)
        cm = [k for k, x in enumerate(lines) if x.startswith(b"#ESL WARNING ")]
        first_node = next(k for k, x in enumerate(lines) if x.strip().upper().startswith(b"/NODE"))
        assert cm and cm == list(range(first_node - len(cm), first_node))       # 첫 /NODE 바로 앞, 연속
        assert lines[cm[0]].startswith(b"#ESL WARNING FIXED_MOVED n=") and b"check RBE2/TIE" in lines[cm[0]]
        assert all(lines[k].endswith(eol) and lines[k].isascii() for k in cm)   # 원본 줄바꿈·ASCII
        n_ids = sum(len(lines[k].split()) - 3 for k in cm[1:])
        assert 0 < n_ids <= 50 and all(len(lines[k].split()) - 3 <= 10 for k in cm[1:])
        n_moved, bad = node_block_diff(orig, strip_esl_comments(inc))
        assert bad == 0 and n_moved > 0
        assert chr_.splitlines()[1].startswith(b"#ESL WARNING FIXED_MOVED")    # ch_r.rad 머리(첫 줄 뒤)
        assert [x["code"] for x in vj["warnings"]] == ["SELECT_FIXED_MOVED"]
    rep = client.get(f"{API}/doe/studies/{s['id']}/report", headers=R)
    assert rep.status_code == 200 and "체결 위치 어긋남" in rep.text and "⚠" in rep.text

    # V-SR-10 이어하기(워커 _one_design): v0.16.0 SKIPPED_FIXED done.json(같은 키) + warn → 워커가 재사용하지 않고 코어 bd_eval
    # 이 다시 판정 → 해석(OK). OK done.json → 코어 없이 재사용(SR-D-13d)
    from esl_worker import doe_jobs, paicad_proc
    from sqlalchemy import text

    from esl.doe import stages as stg
    with engine.connect() as c:
        params = c.execute(text("SELECT params FROM jobs WHERE id=:i"), {"i": j1["id"]}).scalar()
    ex = SimpleNamespace(lib={"doe": params["doe"]}, cdir=str(d))
    calls_ = []

    def core_eval(ex_, did_, pa, procs):          # 자식 프로세스 대신 같은 코어 단계를 직접(판정·해석은 코어 그대로)
        calls_.append(did_)
        r_ = stg.run_stage({"stage": "bd_eval", "out": str(d), "doe": {**params["doe"], "design": did_, "paicad": pa}},
                           lambda m: None)
        return r_["status"], r_.get("code")
    tamper = sorted(moved)[0]
    dd = d / "run" / "designs" / tamper
    done = json.loads((dd / "done.json").read_text())
    assert done["status"] == "OK"
    (dd / "done.json").write_text(json.dumps({**done, "status": "SKIPPED_FIXED"}))
    keep = sorted(clean)[0]
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(doe_jobs, "_eval_child", core_eval)
        r_ok = doe_jobs._one_design(ex, keep, paicad_proc.Procs(), print)
        assert r_ok["reused"] and r_ok["status"] == "OK" and calls_ == []
        r_t = doe_jobs._one_design(ex, tamper, paicad_proc.Procs(), print)
        assert not r_t["reused"] and r_t["status"] == "OK" and calls_ == [tamper]
    finally:
        mp.undo()
    d2 = json.loads((dd / "done.json").read_text())
    assert d2["status"] == "OK" and d2["input_sha256"] == done["input_sha256"]
