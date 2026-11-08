"""V-AD-1·3(·12 코어): 비드 자동 탐지 → select 초기 선택(계약 esl_bead_auto.md §4, AD-D-3·5·12·21, v0.16.2).

합성 = ``synth_bead.generate`` (b1 경로형 2단, b2 원형 1단) + 가짜 paicad tag: 노드에 붙은 요소 표지가 하나면 FACE(그 표지의 면
번호), 여럿이면 EDGE(실 paicad 처럼 B-rep 모서리 위 노드). 가짜 extract = 비드 B1(bottom F101 = b1 단1), B2(bottom F202)."""
import json
import os

import numpy as np
import pytest

import synth_bead as sb
from esl.doe import bead_auto as ba
from esl.doe import bead_select as bs
from esl.doe import paicad_io as pio
from esl.doe import settings
from esl.doe import stages as stg

CFG = settings({"bead_doe": {"enabled": True}})
FACE_OF = {"plate": 1, "b1t1": 101, "b1t2": 102, "b1s": 103, "b2t1": 202, "b2s": 203}


def fake_tag(g, label_face=FACE_OF, shift_ids: int = 0):
    m, lab = g["mesh"], g["label"]
    C = np.asarray(m["conn"], np.int64)
    et = np.asarray(m["elem_type"]).astype(int)
    n = m["x0"].shape[0]
    faces: list[set] = [set() for _ in range(n)]
    for e in range(C.shape[0]):
        f = label_face.get(str(lab[e]), 9)
        for v in C[e, :4 if et[e] == 4 else 3]:
            faces[int(v)].add(f)
    kind = np.array([1 if len(s) == 1 else 2 for s in faces], np.int8)
    ent = np.array([next(iter(s)) if len(s) == 1 else 0 for s in faces], np.int32)
    return {"node_id": np.asarray(m["node_id"], np.int64) + shift_ids, "kind": kind, "entity": ent}


def fake_extract(beads=(("B1", ["F101"]), ("B2", ["F202"])), groups=None, nominal=None):
    return {"schema_version": 1, "kind": "shell", "parts": [], "features": [], "groups": groups or [],
            "beads": [{"id": bid, "k": k, "bottom": bot, "nominal": dict(nominal or {})}
                      for k, (bid, bot) in enumerate(beads, start=1)]}


@pytest.fixture(scope="module")
def G():
    g = sb.generate()
    return g, fake_tag(g)


def _floor(sel, ix, bid):
    b = next(x for x in sel["beads"] if x["id"] == bid)
    assert len(b["tiers"]) == 1 and b["slope"]["mode"] == "auto" and b["blend_mm"] == "auto" and "hold_fixed" not in b
    return bs.elems_of(ix, b["tiers"][0]["floor"])


# ---------------------------------------------------------------- V-AD-1 결정성·등가
def test_seed_floor_truth_and_map(G):
    g, tag = G
    sel, mp, warns = ba.auto_selection(g["mesh"], fake_extract(), tag, CFG)
    ix = bs.mesh_index(g["mesh"])
    lab = g["label"]
    f1, f2 = _floor(sel, ix, "b1"), _floor(sel, ix, "b2")
    assert np.array_equal(f2, lab == "b2t1")                     # 바닥 가장자리(EDGE 노드) 요소도 바닥
    assert not (f1 & (lab != "b1t1")).any() and f1.sum() >= 0.97 * (lab == "b1t1").sum()
    assert mp == [{"bead": "b1", "paicad_id": "B1", "n_floor": int(f1.sum())},
                  {"bead": "b2", "paicad_id": "B2", "n_floor": int(f2.sum())}]
    assert not [w for w in warns if w.get("level") != "info"]
    assert sel == bs.normalize_input(sel, CFG)                    # 정규화 결과 그대로(멱등)


def test_seed_bytes_deterministic_and_manual_sha(G, tmp_path):
    g, tag = G
    docs = []
    for k in range(2):
        sel, mp, warns = ba.auto_selection(g["mesh"], fake_extract(), tag, CFG)
        p = tmp_path / f"a{k}.json"
        sha = ba.write_auto_selection(str(p), sel, mp, warns, mesh_sha256="m" * 64, paicad_version="0.14.1")
        docs.append((p.read_bytes(), sha))
    assert docs[0] == docs[1]
    doc = ba.read_auto_selection(str(tmp_path / "a0.json"))
    assert doc["schema"] == "esl/doe_auto_selection/1" and doc["sha256"] == docs[0][1]
    assert set(doc) == {"schema", "selection", "sha256", "map", "warnings", "mesh_sha256", "paicad_version"}
    assert docs[0][0] == (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    # seed 를 고치지 않고 저장 = 같은 선택을 수동으로 저장한 sha
    ix = bs.mesh_index(g["mesh"])
    manual = {"schema_version": 1, "beads": [
        {"id": b["id"], "tiers": [{"k": 1, "floor": bs.elemset_of(ix, _floor(doc["selection"], ix, b["id"]))}],
         "slope": {"mode": "auto"}, "blend_mm": "auto"} for b in doc["selection"]["beads"]]}
    assert bs.normalize(manual, CFG, mesh=g["mesh"])[1] == doc["sha256"]
    assert bs.normalize(doc["selection"], CFG, mesh=g["mesh"])[1] == doc["sha256"]


def test_seed_warnings(G):
    g, tag = G
    grp = [{"id": "G1", "type": "BEAD_DEPTH", "parameter": "X_1", "members": ["X_1", "X_2"]}]
    sel, mp, warns = ba.auto_selection(g["mesh"], fake_extract(beads=(("B1", ["F101"]), ("B9", ["F999"]), ("B2", ["F202"])),
                                                               groups=grp), tag, CFG)
    codes = [w["code"] for w in warns]
    assert {"code": "AUTO_GROUP_DROPPED", "level": "info", "n": 1} in warns
    assert {"code": "AUTO_BEAD_UNMAPPED", "bead": "B9"} in warns
    assert [b["id"] for b in sel["beads"]] == ["b1", "b2"] and [x["paicad_id"] for x in mp] == ["B1", "B2"]
    cfg1 = settings({"bead_doe": {"enabled": True, "select": {"max_beads": 1}}})
    sel1, mp1, w1 = ba.auto_selection(g["mesh"], fake_extract(), tag, cfg1)
    assert {"code": "AUTO_TOO_MANY_BEADS", "n": 2, "max": 1} in w1 and [b["id"] for b in sel1["beads"]] == ["b1"]
    # tag 가 비면(STEP·메시 어긋남 — R-AD-6) 선택 없음 + 비드별 UNMAPPED
    empty = {"node_id": tag["node_id"], "kind": np.full(tag["kind"].size, -1, np.int8), "entity": tag["entity"]}
    s0, m0, w0 = ba.auto_selection(g["mesh"], fake_extract(), empty, CFG)
    assert s0 is None and m0 == [] and [w["code"] for w in w0] == ["AUTO_BEAD_UNMAPPED"] * 2
    # 다른 파트 노드 ID(tag 의 B 원 ID 와 다름) → 매핑 없음
    s1, _, _ = ba.auto_selection(g["mesh"], fake_extract(), fake_tag(g, shift_ids=10 ** 7), CFG)
    assert s1 is None
    assert "AUTO_SLOPE_DIFF" not in codes


def test_slope_hint_info_only(G):
    g, tag = G
    sel0, _, _ = ba.auto_selection(g["mesh"], fake_extract(), tag, CFG)
    sel, _, warns = ba.auto_selection(g["mesh"], fake_extract(nominal={"entry_radius": 400.0, "bottom_radius": 1.0}), tag, CFG)
    hints = [w for w in warns if w["code"] == "AUTO_SLOPE_DIFF"]
    assert hints and all(w["level"] == "info" and w["rel"] > CFG["select"]["auto"]["slope_diff_rel"] for w in hints)
    assert sel == sel0                                            # 힌트만 — seed 불변(AD-D-12)


def test_island_fragment_dropped(G):
    """§4.3 섬 제외: 바닥 면 tag 가 떨어진 작은 조각(판 위 몇 요소)에도 붙으면 그 조각은 seed 에서 빠짐."""
    g, tag = G
    t2 = {k: v.copy() for k, v in tag.items()}
    lab = g["label"]
    C = np.asarray(g["mesh"]["conn"])
    plate = np.flatnonzero(lab == "plate")
    e0 = plate[len(plate) // 3]
    t2["entity"][C[e0]] = 202                                      # 판 위 한 요소 노드를 b2 바닥 면으로(노이즈)
    t2["kind"][C[e0]] = 1
    sel, _, _ = ba.auto_selection(g["mesh"], fake_extract(), t2, CFG)
    ix = bs.mesh_index(g["mesh"])
    assert np.array_equal(_floor(sel, ix, "b2"), lab == "b2t1")


# ---------------------------------------------------------------- V-AD-3 자동 경로 코어 점검(SR-D-37/38/33/39/40)
def test_core_checks_same_as_manual(G):
    """auto seed 선택의 derive·기저·range_check·design_state 가 같은 바닥의 수동 선택과 같은 코드·상태(메시 출처·seed 무관)."""
    g, tag = G
    sel, _, _ = ba.auto_selection(g["mesh"], fake_extract(), tag, CFG)
    ix = bs.mesh_index(g["mesh"])
    manual = {"schema_version": 1, "beads": [
        {"id": b["id"], "name": b["name"], "tiers": [{"k": 1, "floor": bs.elemset_of(ix, _floor(sel, ix, b["id"]))}],
         "slope": {"mode": "auto"}, "blend_mm": "auto"} for b in sel["beads"]]}
    out = []
    for s in (sel, bs.normalize_input(manual, CFG)):
        D = bs.derive_obj(g["mesh"], s, CFG, fixed_node_ids=g["fixed_ids"])
        B = bs.basis(g["mesh"], D, CFG)
        rc = bs.range_check(g["mesh"], D, B, CFG)
        chk = bs.design_checks(D, B)
        x0 = g["mesh"]["x0"]
        sts = []
        for row in bs.params_table(D, CFG):
            for v in row["default_range"]:
                vals = {row["name"]: float(v)}
                st = bs.design_state(g["mesh"], x0, bs.morph(x0, B, vals), D.fixed_mask, CFG, checks=chk, values=vals)
                sts.append((row["name"], st["state"], st["code"], [w["code"] for w in st["warnings"]]))
        out.append((D.summary(with_figures=False), [w["code"] for w in rc], sts, bs.basis_bin(B)))
    assert out[0] == out[1]
    assert out[0][0]["algo"] == bs.ALGO == 3


# ---------------------------------------------------------------- 코어 단계: BD_LOADS 자동 탐지(성공·실패 = READY)
def _write_tag(d, tag):
    os.makedirs(d, exist_ok=True)
    np.savez(os.path.join(d, pio.TAG_NPZ), **tag)
    with open(os.path.join(d, pio.TAG_JSON), "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "kind": "shell", "status": "OK", "files": {"nodes": pio.TAG_NPZ}}, fh)


def _auto_detect(d, ok, step=None, code=None):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, pio.AUTO_DETECT_JSON), "w", encoding="utf-8") as fh:
        json.dump({"schema": pio.AUTO_DETECT_SCHEMA, "ok": ok, "step": step, "code": code, "paicad_version": "0.14.1"}, fh)


def test_stage_auto_seed_and_failure(tmp_path, G):
    import synth_doe as sd
    g, tag = G
    m = g["mesh"]
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True)
    rad = sd.write_mesh_rad(str(cd / "model.rad"), m)
    lib = tmp_path / "lib"
    dirs = [sd.save_entry(str(lib), "E0", m, "bend", 1.0, seed=0)[0]]
    step = tmp_path / "up" / "b.step"
    step.parent.mkdir()
    step.write_text("ISO-10303-21;\n")
    full = {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}}
    doe = {"id": "S8", "scenario": "select", "title": "t", "cfg": full, "bead_source": "auto",
           "entries": [{"id": "E0", "dir": dirs[0]}], "step": {"path": str(step), "file_name": "b.step"},
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": str(cd)}}
    out = tmp_path / "_doe" / "S8"

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, lambda s: None)
    run("bd_input")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["bead_source"] == "auto" and inp["step"]["rel"] == "input/step/b.step"
    assert stg.select_prep_info(str(out)) == {"select_base": "case", "bead_source": "auto", "assem": "case",
                                              "part_id": sd.PART_ID, "part_title": inp["part_title"],
                                              "step_rel": "input/step/b.step"}
    # 1) 워커 결과 없음/실패 → 준비 계속 + AUTO_DETECT_FAILED, seed 파일 없음
    r = run("bd_loads")
    assert any(w.startswith("AUTO_DETECT_FAILED") for w in r["warnings"]) and not r["auto"]["ok"]
    assert not (out / "prep" / "select" / ba.AUTO_SELECTION_JSON).exists()
    _auto_detect(str(out / "prep"), False, "extract", "NO_BEADS")
    r = run("bd_loads")
    assert r["auto"]["step"] == "extract" and r["auto"]["warnings"][0] == {"code": "AUTO_DETECT_FAILED", "step": "extract",
                                                                           "detail": "NO_BEADS"}
    # 2) OK → seed 파일(결정적 바이트) = auto_selection 결과
    _auto_detect(str(out / "prep"), True)
    sd.write_extract(str(out / "prep" / "extract"), fake_extract())
    _write_tag(str(out / "prep" / "tag"), tag)
    r = run("bd_loads")
    p = out / "prep" / "select" / ba.AUTO_SELECTION_JSON
    assert r["auto"]["ok"] and r["auto"]["n_beads"] == 2 and "prep/select/auto_selection.json" in r["files"]
    b0 = p.read_bytes()
    sel, mp, w = ba.auto_selection(m, fake_extract(), tag, stg.Ctx({"stage": "x", "out": str(out), "doe": doe}).cfg)
    bm = json.loads((out / "prep" / "base.json").read_text(encoding="utf-8"))["mesh_sha256"]
    assert b0 == ba.auto_bytes(ba.auto_doc(sel, mp, w, mesh_sha256=bm, paicad_version="0.14.1"))
    run("bd_loads")
    assert p.read_bytes() == b0
    # 3) tag 가 비면 AUTO_DETECT_FAILED{tag} + 파일 없음
    _write_tag(str(out / "prep" / "tag"), {**tag, "kind": np.full(tag["kind"].size, -1, np.int8)})
    r = run("bd_loads")
    assert r["auto"]["step"] == "tag" and not p.exists()
    # 수동(bead_source 없음) = v0.16.1 input.json 그대로(키 추가 없음 — AD-D-22)
    doe.pop("bead_source")
    doe.pop("step")
    run("bd_input")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert "bead_source" not in inp and inp["step"] is None and "select_base" not in inp
    r = run("bd_loads")
    assert "auto" not in r
