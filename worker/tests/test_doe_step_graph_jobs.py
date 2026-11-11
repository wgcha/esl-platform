"""v0.18.0 STEP_GRAPH 워커(계약 esl_step_graph.md §2·§4·SG-D-12~18, V-SG-7 의 워커 부분).

- BD_GEOM(select_base step): plan = [a_fixed(A Case 있으면)] + (auto ∧ STEP 사본) extract(힌트만) — B 조립·fixed-scan·extract0·tag·
  grid·update 없음. paicad 없음 = 힌트·A 고정 없이 계속(FIXED_INFO_MISSING 경고 없음 — 코어 FIXED_XFER_NONE{A_SCAN_FAILED}).
  단위 시험은 가짜 ex·paicad 로 ``_geom_select`` 만 돌린다(코어 불필요).
- run_step BD_MESH0 SKIPPED 문구(기준 출처별).
- BD_PREP_REGISTER 준비 요약: select_base step → mesh{method, …}·fixed.xfer{method, matched, unmatched, frame_ok}·region.
- E2E(BD_INPUT·BD_MESH0 사다리·BD_LOADS 그래프·이전 → 저장 → 미리보기 → 실행 → 받기)는 코어 esl.doe.step_graph(Impl-Core) 병합 후.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import types
from pathlib import Path
from typing import Any

import pytest

CORE_STEP_GRAPH = importlib.util.find_spec("esl.doe.step_graph") is not None
needs_core = pytest.mark.skipif(not CORE_STEP_GRAPH, reason="코어 esl.doe.step_graph(v0.18.0 Impl-Core) 병합 후")


# ================================================================ BD_GEOM 단위(가짜 ex·paicad)
class FakeEx:
    def __init__(self, cdir: Path, doe: dict[str, Any]) -> None:
        self.cdir = str(cdir)
        self.lib = {"doe": doe}
        self.settings = None
        self.job = {"id": "j-1"}
        self.token = "t"

    @contextlib.contextmanager
    def _tx(self):
        yield None


def _geom_env(monkeypatch, tmp_path: Path, *, a_case: bool = True, ready: bool = True, step_copy: bool = True,
              extract_ok: bool = True, doe_extra: dict[str, Any] | None = None):
    from esl_worker import doe_jobs as dj

    out = tmp_path / "doe"
    prep = out / "prep"
    prep.mkdir(parents=True)
    inp = {"select_base": "step", "bead_source": (doe_extra or {}).get("bead_source", "manual"),
           "step": {"rel": "input/step/b.step"}, "part_id": None}
    (prep / "input.json").write_text(json.dumps(inp), encoding="utf-8")
    if step_copy:
        (out / "input" / "step").mkdir(parents=True)
        (out / "input" / "step" / "b.step").write_bytes(b"ISO-10303-21;")
    doe = {"scenario": "select", "select_base": "step", "select_schema": 2, "bead_source": "manual",
           "entries": [{"id": "e1", "dir": str(tmp_path), "case": "c1" if a_case else None}],
           "cfg": {"bead_doe": {"paicad": {"threads": 1, "options": None},
                                "limits": {"max_json_mb": 64}, "same": {"max_assem_mb": 4096}}},
           **(doe_extra or {})}
    rec: dict[str, Any] = {"cmds": [], "warnings": [], "result": {}}

    def fake_paicad(ex, st, key, values, **kw):
        rec["cmds"].append((key, values))
        ok = key != "paicad_extract" or extract_ok
        return {"ok": ok, "code": None if ok else "GEOM_CAD_FAILED", "paicad_code": None if ok else "E",
                "exit_code": 0 if ok else 10, "seconds": 0.1, "report": {"beads": [{}], "features": []}}

    def fresh(o, rel, d):
        p = os.path.join(o, rel)
        os.makedirs(p, exist_ok=True)
        return p

    jr = types.SimpleNamespace(
        step_update=lambda *a, **k: None,
        add_warnings=lambda conn, jid, tok, items: rec["warnings"].extend(items),
        patch_result=lambda conn, jid, tok, d: rec["result"].update(d))
    monkeypatch.setattr(dj, "jobs_repo", jr)
    monkeypatch.setattr(dj, "_paicad", fake_paicad)
    monkeypatch.setattr(dj, "_tick", lambda ex: None)
    monkeypatch.setattr(dj, "set_progress", lambda ex, st, pct, **kw: None)
    monkeypatch.setattr(dj, "_a_case", lambda ex, echo: {"case_dir": "/a", "part_id": 21, "man": None} if a_case else None)
    monkeypatch.setattr(dj.paicad_proc, "version_check", lambda s, full: (
        {"ready": True, "version": "0.14.1", "ocp": "7.8.1", "pinned": "0.14.1"} if ready
        else {"ready": False, "reason": "PAICAD_NOT_FOUND"}))
    monkeypatch.setattr(dj.core_adapter, "doe_select_prep_info", lambda o: {})
    monkeypatch.setattr(dj.core_adapter, "doe_fresh_dir", fresh)
    monkeypatch.setattr(dj.core_adapter, "doe_paicad_io",
                        lambda: types.SimpleNamespace(SCAN_JSON="shell_scan.json", EXTRACT_JSON="extract.json"))

    def assem_forbidden(*a, **k):
        raise AssertionError("STEP 기준에는 조립 검사·사본이 없어야 함")
    monkeypatch.setattr(dj.core_adapter, "doe_assem_check", assem_forbidden)
    monkeypatch.setattr(dj, "_stage_full", assem_forbidden)
    ex = FakeEx(out, doe)
    st = {"step_key": "BD_GEOM", "step_no": 3, "core_stage": None}
    return dj, ex, st, rec, out


def _keys(rec) -> list[str]:
    return [k for k, _ in rec["cmds"]]


def test_geom_step_manual_plan_a_fixed_only(monkeypatch, tmp_path):
    dj, ex, st, rec, out = _geom_env(monkeypatch, tmp_path)
    res = dj.run_step(ex, st, str(tmp_path / "geom.log"))
    assert _keys(rec) == ["paicad_fixed_scan"]                         # A Case fixed-scan 만(B fixed-scan 없음)
    assert rec["cmds"][0][1]["parts"] == "21" and rec["cmds"][0][1]["assem_dir"] == "/a"
    assert not res.get("_skipped") and rec["result"]["bd_geom"]["fixed"] is None
    assert not (out / "prep" / "auto_detect.json").exists()
    assert not any("FIXED_INFO_MISSING" in w for w in rec["warnings"])
    assert "기준 STEP" in (tmp_path / "geom.log").read_text(encoding="utf-8")


def test_geom_step_auto_hint_extract_only(monkeypatch, tmp_path):
    dj, ex, st, rec, out = _geom_env(monkeypatch, tmp_path, doe_extra={"bead_source": "auto"})
    dj.run_step(ex, st, str(tmp_path / "geom.log"))
    assert _keys(rec) == ["paicad_fixed_scan", "paicad_extract"]       # extract0·tag·fixed(B) 없음
    ext = rec["cmds"][1][1]
    assert ext["assem_dir"] is None and ext["body_map"] is None and ext["cad"].endswith("b.step")
    ad = json.loads((out / "prep" / "auto_detect.json").read_text())
    assert (ad["role"], ad["ok"], ad["step_given"]) == ("hint", True, True)
    assert rec["result"]["bd_geom"]["n_beads"] == 1 and not rec["warnings"]


def test_geom_step_auto_extract_fail_is_hint_info(monkeypatch, tmp_path):
    dj, ex, st, rec, out = _geom_env(monkeypatch, tmp_path, extract_ok=False, a_case=False,
                                     doe_extra={"bead_source": "auto"})
    res = dj.run_step(ex, st, str(tmp_path / "geom.log"))
    assert _keys(rec) == ["paicad_extract"] and not res.get("_skipped")
    ad = json.loads((out / "prep" / "auto_detect.json").read_text())
    assert (ad["ok"], ad["step"]) == (False, "extract")
    assert [w for w in rec["warnings"] if "AUTO_HINT_UNAVAILABLE" in w]
    assert not any("AUTO_DETECT_FAILED" in w or "FIXED_INFO_MISSING" in w for w in rec["warnings"])


def test_geom_step_auto_no_step_copy(monkeypatch, tmp_path):
    dj, ex, st, rec, out = _geom_env(monkeypatch, tmp_path, step_copy=False, doe_extra={"bead_source": "auto"})
    dj.run_step(ex, st, str(tmp_path / "geom.log"))
    assert _keys(rec) == ["paicad_fixed_scan"]
    ad = json.loads((out / "prep" / "auto_detect.json").read_text())
    assert (ad["ok"], ad["step"], ad["code"]) == (False, "extract", "PREREQUISITE_MISSING")


@pytest.mark.parametrize("auto", [False, True])
def test_geom_step_without_paicad_continues(monkeypatch, tmp_path, auto):
    """SG-D-18: 새 ③ 은 paicad 없이도 동작 — BD_GEOM SKIPPED, FIXED_INFO_MISSING 경고 없음(이전 없음은 코어 정보)."""
    dj, ex, st, rec, out = _geom_env(monkeypatch, tmp_path, ready=False,
                                     doe_extra={"bead_source": "auto" if auto else "manual"})
    res = dj.run_step(ex, st, str(tmp_path / "geom.log"))
    assert res["_skipped"] is True and "PAICAD_NOT_FOUND" in res["skipped"] and rec["cmds"] == []
    assert not any("FIXED_INFO_MISSING" in w for w in rec["warnings"])
    assert rec["result"]["bd_geom"]["fixed"]["source"] == "none"
    if auto:
        ad = json.loads((out / "prep" / "auto_detect.json").read_text())
        assert (ad["ok"], ad["step"]) == (False, "version")
        assert [w for w in rec["warnings"] if "AUTO_HINT_UNAVAILABLE" in w]
    else:
        assert not (out / "prep" / "auto_detect.json").exists() and not rec["warnings"]


def test_skipped_text_by_base():
    from esl_worker.doe_jobs import skipped_text

    assert "③ 이 아님" in skipped_text({"scenario": "same"})
    assert "Case 메시" in skipped_text({"scenario": "select"})
    assert "B 메시" in skipped_text({"scenario": "select", "select_base": "mesh"})
    assert "STEP 기준" in skipped_text({"scenario": "select", "select_base": "step"})


# ================================================================ 등록(BD_PREP_REGISTER) 단위
def test_register_step_prep_unit():
    from esl_worker import register as rg

    assert rg._select_step_prep({"inputs": {"select_base": "mesh"}}, {}, {"source": "scan", "n": 3}) == {}
    assert rg._select_step_prep({"inputs": {}}, {}, {}) == {}
    fixed = {"source": "a_transfer", "n": 12}
    inp = {"select_base": "step",
           "mesh": {"method": "cad", "n_nodes": 1000, "n_elems": 950, "tri_frac": 0.02,
                    "stage_times": {"cad": 3.5}, "extra": "x"},
           "fixed": {"source": "a_transfer", "n": 12,
                     "xfer": {"method": "xyz_nearest", "matched": 4, "unmatched": 1, "frame_ok": True}},
           "region": {"mode": "auto", "n_in": 900, "n_out": 50, "out_bbox": [0, 1]}}
    out = rg._select_step_prep({"inputs": {"select_base": "step"}}, inp, fixed)
    assert out == {"select_base": "step",
                   "mesh": {"method": "cad", "n_nodes": 1000, "n_elems": 950, "tri_frac": 0.02,
                            "stage_times": {"cad": 3.5}},
                   "region": {"mode": "auto", "n_in": 900, "n_out": 50}}
    assert fixed["xfer"] == {"method": "xyz_nearest", "matched": 4, "unmatched": 1, "frame_ok": True}
    # 이전 없음(FIXED_XFER_NONE{reason}) · 형식 이상 값은 안전한 값으로
    fixed = {"source": "none", "n": 0}
    inp = {"fixed": {"source": "none", "n": 0, "xfer": {"method": "bogus", "matched": "3", "reason": "A_CASE_MISSING"}}}
    out = rg._select_step_prep({"inputs": {"select_base": "step"}}, inp, fixed)
    assert out["mesh"] == {"method": None, "n_nodes": None, "n_elems": None, "tri_frac": None, "stage_times": None}
    assert "region" not in out
    assert fixed["xfer"] == {"method": "none", "matched": 0, "unmatched": 0, "frame_ok": None, "reason": "A_CASE_MISSING"}


# ================================================================ E2E(코어 병합 후 — V-SG-7)
@needs_core
@pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트")
def test_e2e_step_prep_ready_with_fake_paicad(client, engine, worker_factory, esl_root, inputs_root, tmp_path):
    """V-SG-7(준비): STEP 기준 select → BD_INPUT·BD_MESH0(사다리)·BD_GEOM(a_fixed + 힌트)·BD_LOADS(그래프·이전) → READY,
    준비 요약 select_base step·mesh.method, paicad 호출에 B fixed-scan·grid·update 없음."""
    gmsh = pytest.importorskip("gmsh")
    del gmsh
    import sys

    from doe_support import api, upload_step
    from doe_worker_support import calls, set_control, write_fake_paicad
    from esl_test_support import REPO
    from test_doe_select_jobs import make_bead_case, run_job, study

    sys.path.insert(0, str(REPO / "tests" / "doe"))
    synth = pytest.importorskip("synth_step_graph")
    exe = write_fake_paicad(tmp_path)
    set_control(exe, rules=[])
    w = make_bead_case(engine, esl_root, inputs_root)
    step = synth.h5_step_bytes() if hasattr(synth, "h5_step_bytes") else None
    if step is None:
        pytest.skip("합성 STEP 생성기 인터페이스(h5_step_bytes) 확인 후")
    uid = upload_step(client, data=step, name="rad/b.step")
    r = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "select", "entry_ids": w["entry_ids"],
                                                  "select_base": "step", "step_upload_id": uid, "bead_source": "auto"})
    assert r.status_code == 201, r.text
    s = r.json()
    wk = worker_factory()
    wk.heartbeat_once()
    run_job(client, wk, s["job"]["id"])
    cmds = [c["cmd"] for c in calls(exe) if c["cmd"] != "version"]
    assert "grid" not in cmds and "update" not in cmds and cmds.count("fixed-scan") <= 1
    g = study(client, s["id"])
    assert g["phase"] == "READY" and g["prep"]["select_base"] == "step" and g["prep"]["mesh"]["method"]
