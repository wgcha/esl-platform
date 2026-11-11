"""v0.15.0 select — 비드 직접 선택 API(계약 esl_bead_select.md §4·§9·§14, V-BS-9·V-BS-13): 활성(paicad 무관·select 꺼짐),
입력 검사(step·mesh·shapes 금지, 같은 모델), 순서 409(PREP_NOT_READY·SELECTION_MISSING·PREVIEW_NOT_READY), 권한(조회·power·CSRF),
선택 보기 파일(허용 목록·ETag·경로 탈출), derive(저장 안 함·비드 단위·오류 코드 매핑·크기 413·시간 503), 저장(version 충돌·rev·
요약만 DB·같은 선택 = 같은 sha), 변수 표(묶음·열린 경계·고정 겹침), 행렬 = 코어 sha, 미리보기·실행 선택 sha(PREVIEW_STALE),
기저 파일, 평면도, 복제(선택 복사·SELECTION_DROPPED).

코어 ``esl.doe.bead_select``(S1)는 병렬 구현 중이라 계약 §4·§5 대로 동작하는 대역(fake)을 ``sys.modules`` 에 넣는다 — 백엔드가
기대하는 시그니처는 ``esl_platform.api.services.doe_select`` 머리말."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import threading
import types
import unicodedata
from pathlib import Path

import numpy as np
import pytest
from doe_support import (
    R,
    W,
    api,
    body,
    doe_settings_dict,
    finish_job,
    png_bytes,
    rad_mesh_bytes,
    record_paicad,
    study_dir,
    update_study,
    upload_step,
)
from esl_test_support import API, H
from opt_support import make_case, plate, seed_opt_entry, upload_files
from sqlalchemy import text

SLOW = threading.Event()
# v0.16.1 코어 대역 판(esl_select_relax.md §4.1·§4.2): None = v0.16.0 코어(algo 없음), 2 = 섬·구멍·hold·w_enabled·range_feasible
FAKE = {"algo": None}
NORM_IN: list[dict] = []


# ================================================================ 코어 대역(계약 §4.1 검증·§4.2 결과 형식)
def _err(code: str, message: str, **extra):
    from esl.errors import EslError

    e = EslError(code, message)
    e.extra = extra
    return e


def _merge(ranges, where: str) -> list[list[int]]:
    rs = []
    for r in ranges:
        if len(r) != 2 or not all(isinstance(x, int) for x in r) or r[0] < 1 or r[1] < r[0]:
            raise _err("SELECT_OVERLAP", f"{where}: 구간 형식 {r}", where=where)
        rs.append(list(r))
    rs.sort()
    out: list[list[int]] = []
    for a, b in rs:
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _ids(es) -> set[tuple[str, int]]:
    return {(t, i) for t in ("q", "t") for a, b in es[t] for i in range(a, b + 1)}


def fake_normalize(selection, cfg, *, mesh=None):
    sc = cfg["select"]
    sel = copy.deepcopy(selection)
    NORM_IN.append(copy.deepcopy(selection))
    beads = sel.get("beads") or []
    if not 1 <= len(beads) <= int(sc["max_beads"]):
        raise _err("SELECT_BEAD_ID_INVALID", "비드 수", n=len(beads))
    known = None
    if mesh is not None:
        et = np.asarray(mesh["elem_type"])
        eid = np.asarray(mesh["elem_id"])
        known = {("q", int(i)) for i in eid[et == 4]} | {("t", int(i)) for i in eid[et == 3]}
    seen_ids: set[str] = set()
    owner: dict[tuple[str, int], str] = {}
    out_beads = []
    for b in beads:
        bid = b["id"]
        if not re.fullmatch(r"b[1-9][0-9]?", bid) or bid in seen_ids or int(bid[1:]) > int(sc["max_beads"]):
            raise _err("SELECT_BEAD_ID_INVALID", f"id {bid!r}", bead=bid)
        seen_ids.add(bid)
        name = b.get("name")
        name = f"B{bid[1:]}" if name is None else name
        if not 1 <= len(name) <= 32 or any(unicodedata.category(ch).startswith("C") for ch in name):
            raise _err("SELECT_NAME_INVALID", "이름", bead=bid)
        ks = [t["k"] for t in b["tiers"]]
        if not ks or ks != list(range(1, len(ks) + 1)) or len(ks) > int(sc["max_tiers"]):
            raise _err("SELECT_TIERS_GAP", "단 번호", bead=bid, tiers=ks)
        tiers = []
        for t in b["tiers"]:
            fl = {k: _merge(t["floor"][k], bid) for k in ("q", "t")}
            if not _ids(fl):
                raise _err("SELECT_EMPTY_TIER", "빈 단", bead=bid, tier=t["k"])
            tiers.append({"k": t["k"], "floor": fl})
        slope = {"mode": b["slope"]["mode"], "add": {k: _merge(b["slope"]["add"][k], bid) for k in ("q", "t")},
                 "remove": {k: _merge(b["slope"]["remove"][k], bid) for k in ("q", "t")}}
        used = [x for g in b.get("links") or [] for x in g]
        if len(used) != len(set(used)) or any(x not in ks for x in used) or any(len(g) < 2 for g in b.get("links") or []):
            raise _err("SELECT_LINK_INVALID", "묶음", bead=bid)
        for es in [t["floor"] for t in tiers] + [slope["add"]]:
            for e in _ids(es):
                if known is not None and e not in known:
                    bad = sorted(x[1] for x in _ids(es) if x not in known)
                    raise _err("SELECT_ELEM_UNKNOWN", "없는 요소", n=len(bad), first=bad[0])
                if e in owner:
                    raise _err("SELECT_OVERLAP", "겹침", bead=bid, elems_n=1)
                owner[e] = bid
        out_beads.append({"id": bid, "name": name, "tiers": tiers, "slope": slope,
                          "blend_mm": b.get("blend_mm", "auto"),
                          "floor_follow": b["floor_follow"] if b.get("floor_follow") is not None
                          else int(sc["width"]["floor_follow"]),
                          "links": sorted(sorted(g) for g in b.get("links") or []),
                          **({"hold_fixed": 1} if b.get("hold_fixed") == 1 else {})})     # v0.16.1 SR-D-13a: 1 일 때만
    out = {"schema_version": 1, "feature_angle_deg": float(sel.get("feature_angle_deg") or sc["feature_angle_deg"]),
           "beads": sorted(out_beads, key=lambda x: int(x["id"][1:])),
           "fixed_user": {k: _merge(sel["fixed_user"][k], "fixed") for k in ("q", "t")},
           "exclude": {k: _merge(sel["exclude"][k], "exclude") for k in ("q", "t")}}
    sha = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return out, sha


CALLS: list[dict] = []


def fake_derive(mesh, selection, cfg, *, frame, fixed_scan, bead=None):
    CALLS.append({"bead": bead, "fixed_scan": [int(x) for x in fixed_scan], "frame": frame})
    if selection["beads"][0]["name"] == "slow":
        SLOW.wait(10)
    eid = {int(e): i for i, e in enumerate(np.asarray(mesh["elem_id"]))}
    conn = np.asarray(mesh["conn"])
    nid = np.asarray(mesh["node_id"])
    user_fixed = {int(nid[j]) for _t, e in _ids(selection["fixed_user"]) for j in conn[eid[e]]}
    fixed = {int(x) for x in fixed_scan} | user_fixed
    r = cfg["select"]["range"]
    beads, sugg = [], {}
    for b in selection["beads"]:
        if bead is not None and b["id"] != bead:
            continue
        tiers, warns, hit_tiers = [], [], []
        for t in b["tiers"]:
            d = 4.0 + 2.0 * (t["k"] - 1)
            nodes = {int(nid[j]) for _t, e in _ids(t["floor"]) for j in conn[eid[e]]}
            if nodes & fixed:
                hit_tiers.append(t["k"])
            tiers.append({"k": t["k"], "n_elems": len(_ids(t["floor"])), "D_nom": d, "normal": [0.0, 1.0, 0.0],
                          "planarity_mm": 0.0})
        if hit_tiers:
            warns.append({"code": "SELECT_FIXED_IN_BEAD", "n": 1, "tiers": hit_tiers})
        closed = not b["name"].startswith("edge")
        if not closed:
            warns.append({"code": "SELECT_OPEN_BOUNDARY"})
        beads.append({"id": b["id"], "name": b["name"], "n_elems": sum(x["n_elems"] for x in tiers), "n_nodes": 9,
                      "tiers": tiers, "slope": {"n_elems": 0, "elems": {"q": [], "t": []}, "suggested_n": 0, "edited": False},
                      "boundary": {"loops": [{"closed": closed, "n_nodes": 8, "length_mm": 100.0}], "n_nodes": 8},
                      "W_nom": 40.0, "W_min": 38.0, "W_max": 44.0, "sense": "concave",
                      "blend_mm": 24.0 if b["blend_mm"] == "auto" else float(b["blend_mm"]), "blend_clipped": False,
                      "fixed_in_bead_n": len(hit_tiers), "fixed_in_blend_n": 0,
                      "plan": {"ring_ab": [[[0, 0], [1, 0], [1, 1]]], "e_ab": [[[0, -1], [1, 0], [0, 1]]]},
                      "section": {"s": [0, 1], "z": [0, 4], "dz_dD": {"1": [0, 1]}, "ds_dW": [0, 0.5], "dz_dW": [0, 0]},
                      "range_default": {"D": {str(t["k"]): [t["D_nom"] * (1 - r["depth_rel"]), t["D_nom"] * (1 + r["depth_rel"])]
                                              for t in tiers},
                                        "W": [40.0 * (1 - r["width_rel"]), 40.0 * (1 + r["width_rel"])]},
                      "warnings": warns})
        sugg[b["id"]] = {"q": [[90, 90]], "t": []}
        if FAKE["algo"]:                    # v0.16.1: 관통 구멍은 열린 경계 아님(SELECT_OPEN_BOUNDARY 는 판 가장자리만)
            bd = beads[-1]
            holey = b["name"].startswith("holey")
            bd.update(islands=[{"k": 1, "n_elems": 2, "n_nodes": 6, "elems": {"q": [[95, 96]], "t": []}, "rim_n": 4,
                                "size_mm": 16.0, "free_loops": 0}] if holey else [],
                      holes={"n": 1 if holey else 0, "n_nodes": 8 if holey else 0}, inner_loops_n=0,
                      hold_fixed=int(b.get("hold_fixed", 0)),
                      hold={"n_ring_nodes": 3, "n_blend_nodes": 5, "n_fixed": 1} if b.get("hold_fixed") == 1 else None,
                      w_enabled=closed and not b["name"].startswith("nowidth"))
            if b["id"] == "b1":             # 코어가 feasible 을 직접 주는 경우(없으면 백엔드가 요약에서 계산)
                bd["range_feasible"] = {"D": {str(t["k"]): [1.0, t["D_nom"] * 2.0] for t in tiers}, "W": [30.0, 64.0]}
    src = ("scan+user" if user_fixed else "scan") if len(fixed_scan) else ("user" if user_fixed else "none")
    out = {"beads": beads, "fixed": {"scan_n": len(fixed_scan), "user_n": len(user_fixed), "source": src},
           "warnings": [], "slope_suggested": sugg}
    if FAKE["algo"]:
        out["algo"] = FAKE["algo"]
        out["islands_suggested"] = {b["id"]: b["islands"][0]["elems"] for b in beads if b.get("islands")}
    return out


def fake_plan_data(mesh, selection, derived, cfg, *, frame):
    return {"frame": {"a_range": [0.0, 300.0], "b_range": [0.0, 200.0]}, "outline": [[0, 0], [300, 0], [300, 200], [0, 200]],
            "holes": [], "elems": {"n_total": int(np.asarray(mesh["elem_id"]).size), "decimated": False, "points": []},
            "beads": [{"id": b["id"], "name": b["name"], "ring_ab": b["plan"]["ring_ab"], "e_ab": b["plan"]["e_ab"],
                       "label_ab": [1.0, 1.0], "tiers": [], "section": b["section"]} for b in derived["beads"]],
            "fixed": [{"a": 10.0, "b": 20.0}], "nodes_ab": [[0.0, 0.0], [25.0, 25.0]], "warnings": []}


@pytest.fixture(autouse=True)
def _fake_core(monkeypatch):
    from esl_platform.api.services import doe as svc
    from esl_platform.api.services import doe_select

    mod = types.ModuleType("esl.doe.bead_select")
    mod.normalize, mod.derive, mod.plan_data = fake_normalize, fake_derive, fake_plan_data
    monkeypatch.setitem(sys.modules, "esl.doe.bead_select", mod)
    svc.reset_status_cache()
    doe_select.reset_caches()
    CALLS.clear()
    NORM_IN.clear()
    SLOW.clear()
    FAKE["algo"] = None
    yield mod
    FAKE["algo"] = None
    SLOW.set()
    svc.reset_status_cache()
    doe_select.reset_caches()


@pytest.fixture()
def settings_dict(tmp_path):
    d = doe_settings_dict(tmp_path)
    d["bead_doe"]["select"] = {"derive_timeout_s": 0.5, "max_selection_kb": 64}
    return d


@pytest.fixture()
def world(engine, esl_root, inputs_root):
    make_case(engine, inputs_root, "c1")
    m = plate()
    a = seed_opt_entry(engine, esl_root, "c1", m, "bend", scene_no=1)
    b = seed_opt_entry(engine, esl_root, "c1", m, "twist", scene_no=2)
    other = seed_opt_entry(engine, esl_root, "c1", plate(node_base=5000), "bend", scene_no=3)
    record_paicad(engine)
    return {"a": a, "b": b, "other": other, "mesh": m}


def sbody(world, ids=None, **kw):
    return {"project_id": "p-1", "scenario": "select", "entry_ids": ids or [world["a"], world["b"]], **kw}


def code(r):
    return r.json()["detail"]["code"]


def _job(engine, jid):
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM jobs WHERE id=:i"), {"i": jid}).mappings().one())


def _row(engine, sid):
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM bead_does WHERE id=:i"), {"i": sid}).mappings().one())


def es(*ranges, t=()):
    return {"q": [list(r) for r in ranges], "t": [list(r) for r in t]}


def bead(bid="b1", name=None, tiers=((1, 4),), **kw):
    b = {"id": bid, "tiers": [{"k": k + 1, "floor": es(r)} for k, r in enumerate(tiers)]}
    if name is not None:
        b["name"] = name
    b.update(kw)
    return b


def selection(*beads, **kw):
    return {"schema_version": 1, "beads": list(beads) or [bead()], **kw}


def simulate_select_prep(engine, esl_root: Path, sid: str, job_id: str, mesh: dict, *, fixed: list[int] | None = None,
                         node_shift: float = 0.0, schema: int = 1) -> str:
    """워커 DOE_PREP(select) 흉내: prep/base_mesh.npz·base.json(scenario.save_base) + prep/select/ + (fixed-scan) prep/fixed/.
    v0.17.0: 새 스터디는 inputs.select_schema 2 — schema=1(기본)이면 키를 지워 v0.16.2 이전 스터디로 만든다(schema 1 회귀 V-BG-12)."""
    from esl.doe import scenario as sc
    from esl.opt import target as tg

    m = {k: np.asarray(v).copy() for k, v in mesh.items()}
    m["x0"] = m["x0"] + node_shift
    d = study_dir(esl_root, sid) / "prep"
    t = tg.Target("S1", m, {"origin": [0, 0, 0], "L_xi": 300.0, "L_eta": 200.0}, [(int(m["node_id"][0]), "123")])
    meta = sc.save_base(t, str(d), "select")
    sd = d / "select"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "part.glb").write_bytes(b"glTF\x02\x00\x00\x00")
    (sd / "select.bin").write_bytes(b"\x00\x01\x02\x03")
    (sd / "select_manifest.json").write_text(json.dumps({"schema": "esl/bead_select_view/1",
                                                         "mesh_sha256": meta["mesh_sha256"]}), encoding="utf-8")
    if fixed is not None:
        fd = d / "fixed"
        fd.mkdir(parents=True, exist_ok=True)
        (fd / "shell_scan.json").write_text(json.dumps({"status": "OK", "fixed": {"clusters": []}}), encoding="utf-8")
        n = len(fixed)
        np.savez(fd / "fixed_nodes.npz", node_id=np.asarray(fixed, dtype=np.int64), part=np.zeros(n, dtype=np.int64),
                 kind_mask=np.ones(n, dtype=np.int64), cluster=np.zeros(n, dtype=np.int64), xyz=np.zeros((n, 3)))
    finish_job(engine, job_id)
    update_study(engine, sid, phase="READY",
                 prep={"n_beads": 0, "n_params": 0, "warnings": [], "boundary": None, "n_nodes": int(m["node_id"].size),
                       "n_elems": int(m["elem_id"].size), "fixed": {"source": "scan" if fixed else "none",
                                                                     "n": len(fixed or [])}})
    if schema == 1:
        with engine.begin() as c:
            c.execute(text("UPDATE bead_does SET inputs = inputs - 'select_schema' WHERE id=:i"), {"i": sid})
    return meta["mesh_sha256"]


def _create(client, world, **kw):
    r = api(client, "POST", "/doe/studies", json=sbody(world, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def _ready(client, world, engine, esl_root, **kw):
    s = _create(client, world)
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"], **kw)
    return api(client, "GET", f"/doe/studies/{s['id']}").json()


def _save(client, s, sel=None, token="tok-power"):
    return api(client, "PUT", f"/doe/studies/{s['id']}/selection", token,
               json={"version": s["version"], "selection": sel or selection()})


def _saved(client, world, engine, esl_root, sel=None, **kw):
    s = _ready(client, world, engine, esl_root, **kw)
    r = _save(client, s, sel)
    assert r.status_code == 200, r.text
    return r.json()


SPEC = {"method": "lhs", "n": 4, "seed": 3, "params": [{"name": "B1_D1", "lo": 3.0, "hi": 5.0}]}


FV = {"n": 37, "max_mm": 0.8, "bead_vars": [{"name": "B1_D1", "bead": "b1", "n": 37, "max_mm": 0.8}], "node_idx": [0, 3]}
WARNS = [{"code": "SELECT_FIXED_MOVED", "n": 37, "max_mm": 0.8},
         {"code": "SELECT_QUALITY_WARN", "new_fail": 12, "new_fail_ratio": 0.02}]


def simulate_select_preview(engine, esl_root, sid, job_id, matrix, sel_sha, *, basis=True, fixed_first=False,
                            warn_first=False, rules=None):
    rev = 1
    base = study_dir(esl_root, sid)
    gd = base / "doe" / str(rev) / "grid"
    (gd / "nominal").mkdir(parents=True, exist_ok=True)
    (gd / "nominal" / "thumb.png").write_bytes(png_bytes())
    (base / "doe" / str(rev) / "matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
    cells = []
    for i, d in enumerate(x for x in matrix["designs"] if x["id"] != "d000"):
        (gd / "cells" / d["id"]).mkdir(parents=True, exist_ok=True)
        (gd / "cells" / d["id"] / "thumb.png").write_bytes(png_bytes())
        if fixed_first and i == 0:      # v0.15.1 코어 bd_select_grid 고정 침범 칸(fixed_viol)
            cells.append({"id": d["id"], "status": "FAIL", "code": "SELECT_FIXED_VIOLATION", "fixed_max_mm": 0.8,
                          "fixed_viol": FV})
        elif warn_first and i == 0:     # v0.16.1 warn 정책: 침범 + 새 Fail 초과여도 READY + warnings, fixed_viol 은 상태 무관
            cells.append({"id": d["id"], "status": "OK", "code": None, "fixed_viol": FV, "warnings": WARNS})
        else:
            cells.append({"id": d["id"], "status": "OK", "code": None})
    gm = {"schema_version": 1, "kind": "select", "cells": cells, "color": {"v_max": 3.0, "unit": "mm"}}
    if rules is not None:
        gm["rules"] = rules
    (gd / "grid_manifest.json").write_text(json.dumps(gm), encoding="utf-8")
    if basis:
        bd = base / "select" / sel_sha[:12]
        bd.mkdir(parents=True, exist_ok=True)
        (bd / "basis.bin").write_bytes(b"\x01\x00\x00\x00" + b"\x00" * 16)
        (bd / "basis.json").write_text(json.dumps({"schema": "esl/bead_select_basis/1", "sha256": "f" * 64,   # 코어 basis_meta 형식
                                                  "selection_sha256": sel_sha, "n_nodes": 1,
                                                  "vars": [{"name": "B1_D1", "type": "D", "bead": "b1", "nominal": 22.0,
                                                            "n": 1, "R_mm": None}]}), encoding="utf-8")
    finish_job(engine, job_id)
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        s = doe_repo.get_study(c, sid)
    doe = dict(s["doe"])
    nf = sum(c["status"] != "OK" for c in cells)
    doe["preview"] = {"rev": rev, "matrix_sha256": doe["matrix_sha256"], "ok": len(cells) - nf, "selection_sha256": sel_sha,
                      "skipped": {"collision": 0, "fixed": nf, "geom": 0, "mesh": 0}}
    update_study(engine, sid, phase="PREVIEW_READY", doe=doe)


# ================================================================ 활성(BS-D-2)
def test_settings_select_block(client, world):
    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["select"] is True and s["select_reason"] is None
    assert s["select"] == {"enabled": True, "reason": None, "feature_angle_deg": 15.0, "max_beads": 20, "max_tiers": 6,
                           "blend": {"min_mm": 15.0, "max_mm": 200.0},
                           # v0.16.1 V-SR-13(settings 키)
                           "fixed_policy": "warn", "quality_fail_policy": "warn", "hold": {"ring_mm": 3.0, "blend_mm": 8.0},
                           "island": {"max_mm": 40.0, "ring_frac": 0.9},           # 브라우저 섬 판정 거울(SR-D-26)
                           "hole": {"bridge_max_mm": 20.0},                         # v0.16.2 AD-D-7
                           # v0.17.0 BEADGRAPH(esl_beadgraph.md §5.5) — 그래프 분류·섬 상한 60(D8)·대칭 묶기 허용차
                           "graph": {"enabled": True, "island": {"max_mm": 60.0}, "sym_tol_mm": 0.5}}


def test_select_defaults_mirror_contract():
    """§10 기본값(설정 예시·BeadDoeSelectCfg·코어 DEFAULTS["select"] 가 있으면 그것과도 같음)."""
    import yaml
    from esl.doe import DEFAULTS
    from esl_platform.core.config import BeadDoeCfg, BeadDoeSelectCfg
    from esl_test_support import REPO

    want = {"enabled": True, "feature_angle_deg": 15.0, "max_beads": 20, "max_tiers": 6, "max_selection_kb": 4096,
            "normal_radius_mm": 10.0, "plane_rms_mm": 2.0, "plate_tol_mm": 1.0, "level_eps_mm": 0.5, "slope_max_mm": 80.0,
            "fixed_tol_mm": 0.01, "width": {"floor_follow": 1, "knn": 8, "end_ratio": 2.0},
            "blend": {"min_mm": 15.0, "max_mm": 200.0, "k": 8.0, "fixed_margin_mm": 3.0},
            "range": {"depth_rel": 0.3, "width_rel": 0.2, "min_step_mm": 1.0, "depth_max_rel": 1.0, "width_max_rel": 0.6,
                      "width_floor_q": 0.25, "check_steps": 5, "combo_samples": 16},
            "quality": {"max_fail_ratio": 0.01, "flip_deg": 60.0, "fail_policy": "warn", "rot_warn_deg": 45.0,
                        "area_ratio_min": 0.2, "distort_rel": 0.25, "distort_min_mm": 0.1},
            "thumb": {"w": 320, "h": 240, "supersample": 2, "view": "auto", "tilt_deg": 25.0, "margin": 1.15, "ambient": 0.35},
            "derive_cache_n": 8, "derive_timeout_s": 20,
            # v0.16.1(esl_select_relax.md §4.4)
            "fixed_policy": "warn", "island": {"max_mm": 40.0, "ring_frac": 0.9}, "hold": {"ring_mm": 3.0, "blend_mm": 8.0},
            # v0.16.1 어려운 사례 수정(SR-D-37~40)
            "cross_bead_policy": "warn", "cross_bead_tol_mm": 0.1,
            # v0.16.2(esl_bead_auto.md §3.2 — AD-D-7·12)
            "hole": {"bridge_max_mm": 20.0}, "auto": {"slope_diff_rel": 0.2},
            # v0.17.0(esl_beadgraph.md §5.5 — 계약 yaml 그대로)
            "graph": GRAPH_DEFAULTS}
    assert BeadDoeSelectCfg().model_dump() == want
    if "select" in DEFAULTS:
        from doe_support import core_view_v0161

        assert DEFAULTS["select"] == core_view_v0161({"select": want}, DEFAULTS)["select"]
    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))
        assert BeadDoeCfg.model_validate(y["bead_doe"]).select.model_dump() == want, p
    for bad in ({"feature_angle_deg": 0.5}, {"max_tiers": 10}, {"width": {"floor_follow": 2}},
                {"blend": {"min_mm": 30.0, "max_mm": 20.0}}, {"blend": {"min_mm": 0}}, {"unknown": 1},
                {"width": {"end_ratio": 1.0}},
                # v0.16.1: 정책 값·feasible 상한(≥ 기본 범위)·섬·보스
                {"fixed_policy": "drop"}, {"quality": {"fail_policy": "ignore"}},
                {"range": {"depth_max_rel": 0.2}}, {"range": {"width_max_rel": 0.1}}, {"range": {"depth_max_rel": 6}},
                {"island": {"max_mm": 0}}, {"hold": {"ring_mm": -1}}, {"hold": {"blend_mm": 0}},
                # v0.16.2
                {"hole": {"bridge_max_mm": 0}}, {"auto": {"slope_diff_rel": -0.1}},
                # v0.17.0 select.graph 검사(§5.5 표)
                *({"graph": g} for g in GRAPH_BAD)):
        with pytest.raises(ValueError):
            BeadDoeSelectCfg.model_validate(bad)


GRAPH_DEFAULTS = {"enabled": True, "feature_angle_deg": 10.0, "level_tol_mm": 0.3, "min_floor_area_mm2": 12.0,
                  "root_free_frac": 0.2, "raster_mm": 1.0, "island": {"max_mm": 60.0, "straddle_frac": 0.15},
                  "bead": {"max_width_mm": 80.0, "prune_k": 2.2, "bend_deg": 50.0, "width_jump": 0.35, "min_zone_mm": 12.0,
                           "open_ext_mm": 90.0, "absorb_len_mm": 60.0},
                  "morph": {"ramp_k": 3.0, "outside_tol_mm": 1.0e-6, "achieved_tol_mm": 1.0e-6,
                            "corner": {"area_ratio_min": 0.35, "shrink": 0.8, "iters": 40},
                            "w_smooth_iters": 3},                       # 통합 v0.17.0(§12 BG-X-5 — 코어 구현 키 거울)
                  "sym_tol_mm": 0.5, "limits": {"max_elems": 600000, "timeout_s": 180, "max_raster_px": 4000000}}
GRAPH_BAD = ({"feature_angle_deg": 0}, {"feature_angle_deg": 46}, {"level_tol_mm": 0}, {"island": {"max_mm": 0}},
             {"island": {"straddle_frac": 1.0}}, {"island": {"straddle_frac": 0}}, {"bead": {"bend_deg": 180}},
             {"bead": {"bend_deg": 0}}, {"bead": {"width_jump": 0}}, {"morph": {"ramp_k": 0.5}},
             {"morph": {"outside_tol_mm": 0}}, {"morph": {"outside_tol_mm": 2e-3}},
             {"morph": {"corner": {"area_ratio_min": 1.0}}}, {"morph": {"corner": {"shrink": 1.0}}},
             {"morph": {"corner": {"iters": 0}}}, {"morph": {"corner": {"iters": 201}}},
             {"morph": {"w_smooth_iters": -1}}, {"morph": {"w_smooth_iters": 201}}, {"limits": {"max_elems": 0}},
             {"limits": {"max_elems": 2_000_001}}, {"limits": {"timeout_s": 0}}, {"limits": {"max_raster_px": 99_999}},
             {"unknown": 1})


@pytest.mark.parametrize("case", ["paicad_missing", "no_gmsh", "select_off", "doe_off"])
def test_select_enable_rules(tmp_path, engine, fake_dashboard, clock, case):
    import httpx
    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict
    from fastapi.testclient import TestClient

    base = tmp_path / case
    base.mkdir()
    d = doe_settings_dict(base, paicad=case != "paicad_missing")
    if case == "select_off":
        d["bead_doe"]["select"] = {"enabled": False}
    if case == "doe_off":
        d["bead_doe"]["enabled"] = False
    record_paicad(engine, gmsh=case != "no_gmsh", ready=case != "paicad_missing",
                  reason="PAICAD_NOT_FOUND" if case == "paicad_missing" else None)
    want = {"paicad_missing": None, "no_gmsh": None, "select_off": "SELECT_DISABLED", "doe_off": "DOE_DISABLED"}[case]
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    app = create_app(build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        s = c.get(f"{API}/doe/settings", headers=R).json()
        assert s["scenarios"]["select"] is (want is None) and s["select"]["reason"] == want and s["select_reason"] == want
        make_case(engine, Path(d["storage"]["input_roots"][0]), "c1")
        eid = seed_opt_entry(engine, Path(d["storage"]["esl_root"]), "c1")
        r = c.post(f"{API}/doe/check-inputs", json={"project_id": "p-1", "scenario": "select", "entry_ids": [eid]},
                   headers=W)
        if want is None:                                    # paicad 없음·gmsh 없음이어도 select 가능
            assert r.status_code == 200, r.text
            assert r.json()["step"] is None and r.json()["base"]["case_id"] == "c1"
        else:
            assert r.status_code == 503 and code(r) == want


# ================================================================ 입력 검사·연구 생성
def test_check_inputs_and_create(client, world, engine, inputs_root):
    uid = upload_step(client)
    for extra in ({"step_upload_id": uid}, {"mesh_upload_id": uid}, {"part_title": "x"},
                  {"shapes": [{"upload_id": uid, "name": "a"}]}):
        r = api(client, "POST", "/doe/check-inputs", json=sbody(world, **extra))
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", extra
    for extra in ({"props": {"t": 1.0, "E": 2e5, "nu": 0.3}}, {"mesh_size_mm": 3.0}):
        r = api(client, "POST", "/doe/studies", json=sbody(world, **extra))
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", extra
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, [world["a"], world["other"]]))
    assert r.status_code == 200 and [e["ok"] for e in r.json()["entries"]] == [True, False]
    r = api(client, "POST", "/doe/studies", json=sbody(world, [world["a"], world["other"]]))
    assert r.status_code == 422 and code(r) == "MODEL_MISMATCH"
    assert client.post(f"{API}/doe/studies", json=sbody(world), headers=H("tok-general", True)).status_code == 403
    s = _create(client, world, title="75형 직접 선택")
    assert s["scenario"] == "select" and s["phase"] == "PREP" and s["selection"] is None and s["title"] == "75형 직접 선택"
    assert s["inputs"]["step"] is None and s["inputs"]["part_title"] == "Chassis rear"
    jp = _job(engine, s["job"]["id"])["params"]
    assert jp["kind"] == "PREP" and jp["doe"]["scenario"] == "select" and "step" not in jp["doe"]
    assert jp["doe"]["base"]["case_id"] == "c1" and jp["doe"]["cfg"]["bead_doe"]["select"]["feature_angle_deg"] == 15.0
    assert "rad_path" not in json.dumps(s)
    s2 = _create(client, world)
    assert "비드 직접 선택" in s2["title"]


# ================================================================ 순서·권한(V-BS-13)
def test_order_conflicts_and_permissions(client, world, engine, esl_root):
    s = _create(client, world)
    sid = s["id"]
    sel = {"version": s["version"], "selection": selection()}
    assert code(api(client, "GET", f"/doe/studies/{sid}/selection")) == "PREP_NOT_READY"
    assert code(api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": selection()})) == "PREP_NOT_READY"
    assert code(api(client, "PUT", f"/doe/studies/{sid}/selection", json=sel)) == "PREP_NOT_READY"
    assert code(api(client, "GET", f"/doe/studies/{sid}/select/view/part.glb")) == "PREP_NOT_READY"
    simulate_select_prep(engine, esl_root, sid, s["job"]["id"], world["mesh"])
    s = api(client, "GET", f"/doe/studies/{sid}").json()
    assert s["phase"] == "READY" and s["prep"]["n_nodes"] == world["mesh"]["node_id"].size
    assert s["prep"]["fixed"] == {"source": "none", "n": 0}
    assert api(client, "GET", f"/doe/studies/{sid}/selection").json() is None
    for path in ("params", "plan-view"):
        r = api(client, "GET", f"/doe/studies/{sid}/{path}")
        assert r.status_code == 409 and code(r) == "SELECTION_MISSING", path
    for path in ("matrix", "preview"):
        r = api(client, "POST", f"/doe/studies/{sid}/{path}", json={"version": s["version"], "spec": SPEC})
        assert r.status_code == 409 and code(r) == "SELECTION_MISSING", path
    r = api(client, "GET", f"/doe/studies/{sid}/select/basis")
    assert r.status_code == 409 and code(r) == "PREVIEW_NOT_READY"
    # 권한: 조회 = 멤버(general 포함), 편집·derive = power 이상, 비멤버 403, 비GET 은 X-ESL-Request 필수
    assert api(client, "GET", f"/doe/studies/{sid}/selection", "tok-general").status_code == 200
    assert api(client, "GET", f"/doe/studies/{sid}/selection", "tok-nonmember").status_code == 403
    assert api(client, "GET", f"/doe/studies/{sid}/select/view/part.glb", "tok-nonmember").status_code == 403
    assert api(client, "PUT", f"/doe/studies/{sid}/selection", "tok-general", json=sel).status_code == 403
    assert api(client, "POST", f"/doe/studies/{sid}/select/derive", "tok-general",
               json={"selection": selection()}).status_code == 403
    r = client.put(f"{API}/doe/studies/{sid}/selection", json=sel, headers=R)
    assert code(r) == "CSRF_HEADER_REQUIRED"
    assert client.get(f"{API}/doe/studies/{sid}/selection").status_code == 401
    # 다른 시나리오 스터디에는 선택 경로 없음
    uid = upload_step(client)
    o = api(client, "POST", "/doe/studies", json={"project_id": "p-1", "scenario": "same", "entry_ids": [world["a"]],
                                                   "step_upload_id": uid}).json()
    assert code(api(client, "GET", f"/doe/studies/{o['id']}/selection")) == "SCENARIO_UNSUPPORTED"
    assert code(api(client, "PUT", f"/doe/studies/{o['id']}/selection", json={**sel, "version": o["version"]})) \
        == "SCENARIO_UNSUPPORTED"
    assert o["selection"] is None


def test_view_files(client, world, engine, esl_root):
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    r = api(client, "GET", f"/doe/studies/{sid}/select/view/part.glb", "tok-general")
    assert r.status_code == 200 and r.content.startswith(b"glTF") and r.headers["content-type"] == "model/gltf-binary"
    etag = r.headers["etag"]
    man = api(client, "GET", f"/doe/studies/{sid}/select/view/select_manifest.json").json()
    assert etag == f'"{man["mesh_sha256"]}"'
    r = client.get(f"{API}/doe/studies/{sid}/select/view/select.bin", headers={**R, "If-None-Match": etag})
    assert r.status_code == 304
    assert api(client, "GET", f"/doe/studies/{sid}/select/view/select.bin").content == b"\x00\x01\x02\x03"
    for bad in ("base.json", "..%2Fbase.json", "part_lod.glb", "x%00.glb"):
        assert api(client, "GET", f"/doe/studies/{sid}/select/view/{bad}").status_code == 404, bad
    assert api(client, "GET", f"/doe/studies/{sid}/select/view/..%2F..%2Fprep%2Fbase.json").status_code == 404


# ================================================================ derive·검증(V-BS-9)
def test_derive_not_saved_and_bead_filter(client, world, engine, esl_root):
    s = _ready(client, world, engine, esl_root, fixed=[1, 2])
    sid = s["id"]
    sel = selection(bead("b1", tiers=((1, 4), (20, 22)), links=[[1, 2]]), bead("b2", "edge 비드", tiers=((40, 41),)))
    r = api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rev"] is None and len(d["sha256"]) == 64 and d["mesh_sha256"] and [b["id"] for b in d["beads"]] == ["b1", "b2"]
    assert d["slope_suggested"] == {"b1": {"q": [[90, 90]], "t": []}, "b2": {"q": [[90, 90]], "t": []}}
    assert d["beads"][0]["section"] and d["fixed"] == {"scan_n": 2, "user_n": 0, "source": "scan"}
    assert CALLS[-1]["fixed_scan"] == [1, 2] and CALLS[-1]["bead"] is None and CALLS[-1]["frame"]["L_xi"] == 300.0
    assert _row(engine, sid)["selection"] is None and api(client, "GET", f"/doe/studies/{sid}").json()["version"] == s["version"]
    d1 = api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel, "bead": "b2"}).json()
    assert [b["id"] for b in d1["beads"]] == ["b2"] and CALLS[-1]["bead"] == "b2"
    n = len(CALLS)
    assert api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel, "bead": "b2"}).status_code == 200
    assert len(CALLS) == n                                                   # 캐시(같은 sha·비드)
    r = api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel, "bead": "b9"})
    assert r.status_code == 422 and code(r) == "SELECT_BEAD_ID_INVALID"
    # 같은 선택(구간 표기·순서만 다름) = 같은 sha
    sel2 = selection(bead("b2", "edge 비드", tiers=((40, 40),), ), bead("b1", tiers=((3, 4), (20, 22)), links=[[2, 1]]))
    sel2["beads"][0]["tiers"][0]["floor"]["q"].append([41, 41])
    sel2["beads"][1]["tiers"][0]["floor"]["q"].insert(0, [1, 2])
    assert api(client, "POST", f"/doe/studies/{sid}/select/derive", json={"selection": sel2}).json()["sha256"] == d["sha256"]


@pytest.mark.parametrize("sel, status, want", [
    (selection(bead("b1", tiers=((1, 4),)), bead("b2", tiers=((4, 6),))), 422, "SELECT_OVERLAP"),
    (selection(bead("b1", tiers=((95, 120),))), 422, "SELECT_ELEM_UNKNOWN"),
    (selection({"id": "b1", "tiers": [{"k": 1, "floor": {"q": [], "t": []}}]}), 422, "SELECT_EMPTY_TIER"),
    (selection({"id": "b1", "tiers": [{"k": 1, "floor": es((1, 2))}, {"k": 3, "floor": es((5, 6))}]}), 422, "SELECT_TIERS_GAP"),
    (selection(bead("b1", tiers=((1, 2), (5, 6)), links=[[1, 3]])), 422, "SELECT_LINK_INVALID"),
    (selection(bead("x1")), 422, "SELECT_BEAD_ID_INVALID"),
    (selection(bead("b1"), bead("b1", tiers=((10, 11),))), 422, "SELECT_BEAD_ID_INVALID"),
    (selection(bead("b1", "a\x07b")), 422, "SELECT_NAME_INVALID"),
    (selection(bead("b1", "x" * 33)), 422, "SELECT_NAME_INVALID"),
    (selection(bead("b1", blend_mm="big")), 422, None),                               # 구조 오류(요청 검증)
    (selection({"id": "b1", "tiers": [{"k": 1, "floor": {"q": [[2 * i + 1, 2 * i + 1] for i in range(30000)], "t": []}}]}),
     413, "SELECT_TOO_LARGE"),
])
def test_selection_validation_errors(client, world, engine, esl_root, sel, status, want):
    s = _ready(client, world, engine, esl_root)
    for r in (api(client, "POST", f"/doe/studies/{s['id']}/select/derive", json={"selection": sel}),
              _save(client, s, sel)):
        assert r.status_code == status, r.text[:300]
        if want:
            assert code(r) == want
    if want == "SELECT_OVERLAP":
        assert r.json()["detail"]["bead"] == "b2" and r.json()["detail"]["elems_n"] == 1
    if want == "SELECT_ELEM_UNKNOWN":
        assert r.json()["detail"]["first"] == 97 and r.json()["detail"]["n"] == 24
    assert _row(engine, s["id"])["selection"] is None


def test_derive_timeout(client, world, engine, esl_root):
    s = _ready(client, world, engine, esl_root)
    r = api(client, "POST", f"/doe/studies/{s['id']}/select/derive", json={"selection": selection(bead("b1", "slow"))})
    assert r.status_code == 503 and code(r) == "SELECT_DERIVE_TIMEOUT"
    SLOW.set()


# ================================================================ 저장·조회
def test_save_get_version_and_summary(client, world, engine, esl_root):
    from esl_platform.api.services import doe_select

    s = _ready(client, world, engine, esl_root, fixed=[1])
    sid = s["id"]
    r = api(client, "PUT", f"/doe/studies/{sid}/selection", json={"version": s["version"] + 3, "selection": selection()})
    assert r.status_code == 409 and code(r) == "VERSION_CONFLICT"
    sel = selection(bead("b1", "좌 경로", tiers=((1, 4), (20, 22)), links=[[1, 2]]), fixed_user=es((50, 50)))
    out = _save(client, s, sel)
    assert out.status_code == 200, out.text
    o = out.json()
    assert o["version"] == s["version"] + 1 and o["phase"] == "READY"
    sm = o["selection"]
    assert sm["rev"] == 1 and sm["n_beads"] == 1 and sm["updated_by_name"] == "파워" and len(sm["sha256"]) == 64
    assert sm["n_warnings"] == 1                                             # SELECT_FIXED_IN_BEAD(고정 노드 1 이 단1 바닥)
    row = _row(engine, sid)["selection"]
    assert row["rev"] == 1 and row["input"]["beads"][0]["name"] == "좌 경로" and row["mesh_sha256"] == sm["mesh_sha256"]
    assert row["input"]["beads"][0]["floor_follow"] == 1 and row["input"]["feature_angle_deg"] == 15.0
    assert "section" not in row["derived"]["beads"][0] and "plan" not in row["derived"]["beads"][0]
    assert "slope_suggested" not in row["derived"] and row["derived"]["fixed"]["source"] == "scan+user"
    g = api(client, "GET", f"/doe/studies/{sid}/selection", "tok-general").json()
    assert g["rev"] == 1 and g["sha256"] == sm["sha256"] and g["input"] == row["input"]
    assert g["derived"]["beads"][0]["section"] and g["derived"]["rev"] == 1 and g["updated_by_name"] == "파워"
    doe_select.reset_caches()                                                # 캐시 없음 → 다시 계산
    n = len(CALLS)
    g2 = api(client, "GET", f"/doe/studies/{sid}/selection").json()
    assert g2["derived"]["beads"][0]["section"] == g["derived"]["beads"][0]["section"] and len(CALLS) == n + 1
    out2 = _save(client, o, sel)
    assert out2.json()["selection"]["rev"] == 2 and out2.json()["selection"]["sha256"] == sm["sha256"]
    r = _save(client, o, sel)                                                # 옛 version → 충돌
    assert r.status_code == 409 and code(r) == "VERSION_CONFLICT"
    lst = api(client, "GET", "/doe/studies?project_id=p-1").json()
    assert next(x for x in lst if x["id"] == sid)["selection"]["rev"] == 2


def test_first_save_sequence_selection_then_params(client, world, engine, esl_root):
    """v0.15.1 회귀(화면 '저장해도 변수 안 뜸'): 화면이 기대는 응답 순서 고정 — 저장 전 GET selection = null(요약 없음) →
    PUT = 상세(요약 sha) → GET selection sha 같음 → params 행(B1_D1). 화면은 저장 직후 이전 null 응답을 무효 선택으로 오판하지 않아야 한다."""
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    assert s["selection"] is None
    g0 = api(client, "GET", f"/doe/studies/{sid}/selection")
    assert g0.status_code == 200 and g0.json() is None
    r = api(client, "GET", f"/doe/studies/{sid}/params")
    assert r.status_code == 409 and code(r) == "SELECTION_MISSING" and "reason" not in r.json()["detail"]
    o = _save(client, s).json()
    sha = o["selection"]["sha256"]
    g1 = api(client, "GET", f"/doe/studies/{sid}/selection").json()
    assert g1["sha256"] == sha and g1["rev"] == 1
    p = api(client, "GET", f"/doe/studies/{sid}/params").json()
    assert [x["name"] for x in p["params"]][:1] == ["B1_D1"]


def test_params_table_and_plan_view(client, world, engine, esl_root):
    sel = selection(bead("b1", tiers=((1, 4), (20, 22), (30, 31)), links=[[1, 2]]),
                    bead("b2", "edge", tiers=((40, 41),)), bead("b3", tiers=((60, 61),)))
    s = _saved(client, world, engine, esl_root, sel, fixed=[int(world["mesh"]["node_id"][world["mesh"]["conn"][59][0]])])
    sid = s["id"]
    p = api(client, "GET", f"/doe/studies/{sid}/params", "tok-general").json()
    names = [x["name"] for x in p["params"]]
    assert names == ["B1_D1", "B1_D3", "B1_W", "B2_D1", "B3_D1", "B3_W"]       # 묶음 대표 = 가장 작은 k, 열린 경계 W 없음
    d1 = p["params"][0]
    assert d1 == {"name": "B1_D1", "type": "D", "bead": "b1", "tier": 1, "nominal": 4.0, "feasible": [2.8, 5.2],
                  "feasible_source": "estimate", "default_range": [2.8, 5.2], "use_default": True,
                  "group_members": ["B1_D1", "B1_D2"]}
    assert p["params"][1]["nominal"] == 8.0 and p["params"][2]["feasible"] == [32.0, 48.0]
    b3 = [x for x in p["params"] if x["bead"] == "b3"]
    assert [x["use_default"] for x in b3] == [False, False]                  # SELECT_FIXED_IN_BEAD → 기본 체크 해제
    assert [b["id"] for b in p["beads"]] == ["b1", "b2", "b3"] and p["beads"][0]["kind"] == "select"
    assert p["beads"][0]["n_tiers"] == 3 and p["beads"][0]["W_nom"] == 40.0 and p["beads"][0]["blend_mm"] == 24.0
    pv = api(client, "GET", f"/doe/studies/{sid}/plan-view", "tok-general").json()
    assert pv["frame"]["a_range"] == [0.0, 300.0] and [b["id"] for b in pv["beads"]] == ["b1", "b2", "b3"]
    assert pv["nodes_ab"] == [[0.0, 0.0], [25.0, 25.0]] and pv["fixed"] == [{"a": 10.0, "b": 20.0}]
    assert pv["beads"][0]["section"]["s"] == [0, 1] and pv["links"] == []


# ================================================================ 행렬·미리보기·실행(BS-D-3)
def test_matrix_preview_run_selection_sha(client, world, engine, esl_root):
    from esl.doe import matrix as mx
    from esl.doe import settings as doe_settings
    from esl_platform.api.services import doe_select

    s = _saved(client, world, engine, esl_root, selection(bead("b1", tiers=((1, 4), (20, 22)))))
    sid = s["id"]
    sel_sha = s["selection"]["sha256"]
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": s["version"], "spec": SPEC})
    assert m.status_code == 200, m.text
    m = m.json()
    tab = doe_select.params_table(_row(engine, sid)["selection"])["params"]
    core = mx.generate(copy.deepcopy(SPEC), tab, doe_settings({"bead_doe": {"enabled": True}}))
    assert m["matrix_sha256"] == core["matrix_sha256"]
    r = api(client, "POST", f"/doe/studies/{sid}/matrix",
            json={"version": 1, "spec": {**SPEC, "params": [{"name": "B9_D1", "lo": 1, "hi": 2}]}})
    assert r.status_code == 422 and code(r) == "DOE_PARAM_UNKNOWN"
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC})
    assert p.status_code == 202, p.text
    p = p.json()
    assert p["doe"]["selection_sha256"] == sel_sha and p["doe"]["matrix_sha256"] == m["matrix_sha256"]
    jp = _job(engine, p["job"]["id"])["params"]["doe"]
    assert jp["selection"]["sha256"] == sel_sha and jp["selection"]["rev"] == 1 and jp["selection"]["params"] == tab
    assert jp["selection"]["input"] == _row(engine, sid)["selection"]["input"] and jp["matrix_sha256"] == m["matrix_sha256"]
    r = _save(client, p)                                                    # 작업 중 저장 금지
    assert r.status_code == 409 and code(r) == "JOB_ACTIVE"
    simulate_select_preview(engine, esl_root, sid, p["job"]["id"], m, sel_sha)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g["phase"] == "PREVIEW_READY" and g["doe"]["preview"]["selection_sha256"] == sel_sha
    assert g["doe"]["preview"]["skipped"] == {"collision": 0, "fixed": 0, "geom": 0, "mesh": 0}
    assert all(c["status"] == "READY" and c["thumb"] for c in g["doe"]["preview"]["cells"])
    # 기저 파일(미리보기한 선택 sha)
    b = api(client, "GET", f"/doe/studies/{sid}/select/basis", "tok-general")
    assert b.status_code == 200 and b.headers["x-esl-basis-sha"] == "f" * 64 and b.content.startswith(b"\x01\x00\x00\x00")
    bm = api(client, "GET", f"/doe/studies/{sid}/select/basis?meta=1&rev=1")
    assert bm.status_code == 200 and [v["name"] for v in bm.json()["vars"]] == ["B1_D1"]
    assert api(client, "GET", f"/doe/studies/{sid}/select/basis?rev=2").status_code == 404
    # 선택을 바꾸면 미리보기 무효 → run 409 PREVIEW_STALE(행렬 sha 가 같아도)
    ch = _save(client, g, selection(bead("b1", tiers=((1, 5), (20, 22)))))
    assert ch.status_code == 200 and ch.json()["selection"]["sha256"] != sel_sha and ch.json()["selection"]["rev"] == 2
    v = ch.json()["version"]
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": v, "matrix_sha256": m["matrix_sha256"]})
    assert r.status_code == 409 and code(r) == "PREVIEW_STALE" and r.json()["detail"]["selection_sha256"] != sel_sha
    assert api(client, "GET", f"/doe/studies/{sid}/select/basis?rev=2").status_code == 404
    # 원래 선택으로 되돌리면(같은 sha) 실행 가능
    back = _save(client, ch.json(), selection(bead("b1", tiers=((1, 4), (20, 22)))))
    assert back.json()["selection"]["sha256"] == sel_sha and back.json()["selection"]["rev"] == 3
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": back.json()["version"],
                                                            "matrix_sha256": m["matrix_sha256"]})
    assert r.status_code == 202, r.text
    jr = _job(engine, r.json()["job"]["id"])["params"]["doe"]
    assert jr["selection"]["sha256"] == sel_sha and jr["run"]["solver"] == "linear"
    finish_job(engine, r.json()["job"]["id"])
    r = _save(client, api(client, "GET", f"/doe/studies/{sid}").json())
    assert r.status_code == 409 and code(r) == "ALREADY_RUN"


def test_preview_cells_fixed_viol_v0151(client, world, engine, esl_root):
    """v0.15.1: 고정 침범 칸 = SKIPPED_FIXED + 코어 fixed_viol 그대로(원인 변수·노드), 나머지 칸엔 키 없음."""
    s = _saved(client, world, engine, esl_root)
    sid = s["id"]
    sel_sha = s["selection"]["sha256"]
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": p["version"], "spec": SPEC}).json()
    simulate_select_preview(engine, esl_root, sid, p["job"]["id"], m, sel_sha, fixed_first=True)
    cells = api(client, "GET", f"/doe/studies/{sid}").json()["doe"]["preview"]["cells"]
    assert cells[0]["status"] == "SKIPPED_FIXED" and cells[0]["code"] == "SELECT_FIXED_VIOLATION" and cells[0]["fixed_viol"] == FV
    assert all("fixed_viol" not in c and c["status"] == "READY" for c in cells[1:])


def test_preview_without_selection_sha_in_preview(client, world, engine, esl_root):
    """워커 미리보기 요약에 selection_sha256 이 빠져도 미리보기 요청 시점 doe.selection_sha256 으로 판정한다."""
    s = _saved(client, world, engine, esl_root)
    sid = s["id"]
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": s["version"], "spec": SPEC}).json()
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    simulate_select_preview(engine, esl_root, sid, p["job"]["id"], m, s["selection"]["sha256"], basis=False)
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        doe = dict(doe_repo.get_study(c, sid)["doe"])
    doe["preview"] = {k: v for k, v in doe["preview"].items() if k != "selection_sha256"}
    update_study(engine, sid, doe=doe)
    g = api(client, "GET", f"/doe/studies/{sid}").json()
    assert g["doe"]["preview"]["selection_sha256"] == s["selection"]["sha256"]
    assert api(client, "GET", f"/doe/studies/{sid}/select/basis").status_code == 404     # 파일 없음
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"], "matrix_sha256": m["matrix_sha256"]})
    assert r.status_code == 202, r.text


def test_basis_rejects_non_hex_sha12(client, world, engine, esl_root):
    """basis_file: select/<sha12> 의 sha12 는 16진수 12자리만 — 경로 조각·대문자·짧은 값이면 파일이 있어도 404."""
    s = _saved(client, world, engine, esl_root)
    sid = s["id"]
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": s["version"], "spec": SPEC}).json()
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    sha = s["selection"]["sha256"]
    simulate_select_preview(engine, esl_root, sid, p["job"]["id"], m, sha)
    assert api(client, "GET", f"/doe/studies/{sid}/select/basis").status_code == 200
    from esl_platform.core.repositories import doe as doe_repo

    base = study_dir(esl_root, sid)
    for bad in ("../" + sha[:9] + "x" * 55, sha[:12].upper() + sha[12:], "zzzzzzzzzzzz" + sha[12:]):
        d = base / "select" / bad[:12]
        if "/" not in bad[:12]:
            d.mkdir(parents=True, exist_ok=True)
            for f in ("basis.bin", "basis.json"):
                (d / f).write_bytes((base / "select" / sha[:12] / f).read_bytes())
        with engine.begin() as c:
            doe = dict(doe_repo.get_study(c, sid)["doe"])
        doe["preview"] = {**doe["preview"], "selection_sha256": bad}
        update_study(engine, sid, doe=doe)
        r = api(client, "GET", f"/doe/studies/{sid}/select/basis")
        assert r.status_code == 404 and code(r) == "FILE_NOT_FOUND", (bad, r.text)


# ================================================================ 복제
def test_clone_copies_selection_or_drops(client, world, engine, esl_root):
    s = _saved(client, world, engine, esl_root, selection(bead("b1", "좌")))
    sid = s["id"]
    c1 = api(client, "POST", f"/doe/studies/{sid}/clone", json={"title": "복제 1"})
    assert c1.status_code == 201, c1.text
    c1 = c1.json()
    assert c1["scenario"] == "select" and c1["selection"]["rev"] == 1 and c1["selection"]["sha256"] == s["selection"]["sha256"]
    jp = _job(engine, c1["job"]["id"])["params"]
    assert "selection" not in jp["doe"] and "step" not in jp["doe"] and jp["warnings"] == []
    # 새 준비 메시가 같으면 선택 그대로 사용
    simulate_select_prep(engine, esl_root, c1["id"], c1["job"]["id"], world["mesh"])
    assert api(client, "GET", f"/doe/studies/{c1['id']}/selection").json()["sha256"] == s["selection"]["sha256"]
    assert api(client, "GET", f"/doe/studies/{c1['id']}/params").status_code == 200
    # 새 준비 메시가 다르면(Case 메시 변경) 선택을 쓰지 않는다
    c2 = api(client, "POST", f"/doe/studies/{sid}/clone").json()
    simulate_select_prep(engine, esl_root, c2["id"], c2["job"]["id"], world["mesh"], node_shift=1.0)
    assert api(client, "GET", f"/doe/studies/{c2['id']}/selection").json() is None
    r = api(client, "GET", f"/doe/studies/{c2['id']}/params")
    assert r.status_code == 409 and code(r) == "SELECTION_MISSING" and r.json()["detail"]["reason"] == "SELECTION_DROPPED"
    # 원 선택이 원 준비 메시와 이미 안 맞으면 복제 시 버리고 경고
    c2s = api(client, "GET", f"/doe/studies/{c2['id']}").json()
    c3 = api(client, "POST", f"/doe/studies/{c2['id']}/clone").json()
    assert c3["selection"] is None and c2s["selection"]["rev"] == 1
    w = _job(engine, c3["job"]["id"])["warnings"]
    assert [x["code"] for x in w] == ["SELECTION_DROPPED"]


# ================================================================ v0.16.1 제약 완화(esl_select_relax.md §4·§7·§9, V-SR-13)
@pytest.mark.parametrize("bad", [True, False, 2, -1, "1", 0.5])
def test_hold_fixed_invalid_422(client, world, engine, esl_root, bad):
    """hold_fixed 형식(0|1 정수만, bool 금지) → 422 SELECT_HOLD_INVALID(derive·저장 둘 다)."""
    s = _ready(client, world, engine, esl_root)
    sel = selection(bead("b1", hold_fixed=bad))
    r = api(client, "POST", f"/doe/studies/{s['id']}/select/derive", json={"selection": sel})
    assert r.status_code == 422 and code(r) == "SELECT_HOLD_INVALID", r.text
    assert any("hold_fixed" in e["loc"] for e in r.json()["detail"]["errors"])
    r = _save(client, s, sel)
    assert r.status_code == 422 and code(r) == "SELECT_HOLD_INVALID"


def test_hold_fixed_sha_and_passthrough(client, world, engine, esl_root):
    """SR-D-13a: hold_fixed 생략·null 이면 코어에 키를 넘기지 않음(기존 선택 sha 불변), 0 은 그대로(코어가 생략), 1 이면 sha 변경."""
    FAKE["algo"] = 2
    s = _ready(client, world, engine, esl_root)
    sid = s["id"]
    o0 = _save(client, s, selection(bead("b1"))).json()
    assert "hold_fixed" not in NORM_IN[-1]["beads"][0]
    o1 = _save(client, o0, selection(bead("b1", hold_fixed=None))).json()
    assert "hold_fixed" not in NORM_IN[-1]["beads"][0] and o1["selection"]["sha256"] == o0["selection"]["sha256"]
    o2 = _save(client, o1, selection(bead("b1", hold_fixed=0))).json()
    assert NORM_IN[-1]["beads"][0]["hold_fixed"] == 0 and o2["selection"]["sha256"] == o0["selection"]["sha256"]
    o3 = _save(client, o2, selection(bead("b1", hold_fixed=1))).json()
    assert o3["selection"]["sha256"] != o0["selection"]["sha256"]
    row = _row(engine, sid)["selection"]
    assert row["input"]["beads"][0]["hold_fixed"] == 1 and row["derived"]["algo"] == 2
    assert row["derived"]["beads"][0]["hold"] == {"n_ring_nodes": 3, "n_blend_nodes": 5, "n_fixed": 1}
    d = api(client, "POST", f"/doe/studies/{sid}/select/derive",
            json={"selection": selection(bead("b1", "holey"))}).json()
    assert d["algo"] == 2 and d["islands_suggested"] == {"b1": {"q": [[95, 96]], "t": []}}
    assert d["beads"][0]["holes"] == {"n": 1, "n_nodes": 8} and len(d["beads"][0]["islands"]) == 1
    assert "islands_suggested" not in row["derived"] and "slope_suggested" not in row["derived"]     # DB 요약에는 없음
    g = api(client, "GET", f"/doe/studies/{sid}/selection").json()
    assert "islands_suggested" not in g["derived"] and g["derived"]["algo"] == 2


def test_params_v0161_feasible_use_default_w(client, world, engine, esl_root):
    """V-SR-13 params: algo 2 → feasible = SR-D-10(코어 range_feasible 우선, 없으면 요약에서), default_range 불변, warn 정책이면
    비드 안 고정 노드여도 기본 체크, W 행 = 코어 w_enabled(구멍 비드는 W 있음·폭 측정 불가 비드는 없음)."""
    FAKE["algo"] = 2
    m = world["mesh"]
    sel = selection(bead("b1", "holey", tiers=((1, 4), (20, 22))), bead("b2", "nowidth", tiers=((40, 41),)),
                    bead("b3", tiers=((60, 61),)), bead("b4", "edge", tiers=((70, 71),)))
    s = _saved(client, world, engine, esl_root, sel, fixed=[int(m["node_id"][m["conn"][59][0]])])
    p = api(client, "GET", f"/doe/studies/{s['id']}/params", "tok-general").json()
    rows = {x["name"]: x for x in p["params"]}
    assert list(rows) == ["B1_D1", "B1_D2", "B1_W", "B2_D1", "B3_D1", "B3_W", "B4_D1"]
    assert rows["B1_D1"]["feasible"] == [1.0, 8.0] and rows["B1_D1"]["default_range"] == [2.8, 5.2]      # 코어 range_feasible
    assert rows["B1_W"]["feasible"] == [30.0, 64.0] and rows["B1_W"]["default_range"] == [32.0, 48.0]
    # 요약 계산: D [위 수준 + min_step, D·(1 + depth_max_rel)], W [기본 하한, W·(1 + width_max_rel)]
    assert rows["B3_D1"]["feasible"] == [1.0, 8.0] and rows["B3_W"]["feasible"] == [32.0, 64.0]
    assert rows["B3_D1"]["use_default"] is True and rows["B3_W"]["use_default"] is True          # warn: 체크 해제 안 함
    assert any(w["code"] == "SELECT_FIXED_IN_BEAD" for w in p["beads"][2]["warnings"])           # 경고는 남음
    b1 = p["beads"][0]
    assert b1["islands_n"] == 1 and b1["holes"] == {"n": 1, "n_nodes": 8} and b1["inner_loops_n"] == 0
    assert b1["hold_fixed"] == 0 and b1["fixed_in_bead_n"] == 0


def test_params_v0161_policy_skip_and_v0160_rules():
    """skip 정책 = v0.16.0 기본 체크 해제, algo 없는 derived(v0.16.0) = 정책·범위 설정과 무관하게 v0.16.0 표(바이트 불변)."""
    from esl_platform.api.services import doe_select
    from esl_platform.core.config import BeadDoeCfg

    c = BeadDoeCfg().model_dump()
    bd = {"id": "b1", "name": "B1", "tiers": [{"k": 1, "D_nom": 10.0}, {"k": 2, "D_nom": 15.0}], "W_nom": 40.0,
          "boundary": {"loops": [{"closed": True}]}, "w_enabled": True,
          "range_default": {"D": {"1": [7.0, 13.0], "2": [11.0, 19.5]}, "W": [32.0, 48.0]},
          "warnings": [{"code": "SELECT_FIXED_IN_BEAD", "tiers": [2]}]}
    doc = {"input": {"beads": [{"id": "b1"}]}, "derived": {"algo": 2, "beads": [bd]}}
    t = {r["name"]: r for r in doe_select.params_table(doc, c)["params"]}
    assert t["B1_D2"]["feasible"] == [11.0, 30.0] and t["B1_D2"]["use_default"] and t["B1_W"]["use_default"]
    skip = copy.deepcopy(c)
    skip["select"]["fixed_policy"] = "skip"
    skip["select"]["range"]["depth_max_rel"] = 0.5
    t = {r["name"]: r for r in doe_select.params_table(doc, skip)["params"]}
    assert t["B1_D1"]["use_default"] and not t["B1_D2"]["use_default"] and not t["B1_W"]["use_default"]
    assert t["B1_D2"]["feasible"] == [11.0, 22.5]
    old = {"input": doc["input"], "derived": {"beads": [bd]}}
    v0 = doe_select.params_table(old, c)
    assert v0 == doe_select.params_table(old, skip) == doe_select.params_table(old)
    t0 = {r["name"]: r for r in v0["params"]}
    assert t0["B1_D2"]["feasible"] == t0["B1_D2"]["default_range"] == [11.0, 19.5] and not t0["B1_D2"]["use_default"]
    assert "islands_n" not in v0["beads"][0]


def test_derived_algo_lazy_refresh(client, world, engine, esl_root):
    """§7.5: algo 없는 DB 요약(v0.16.0 derive) → GET selection·params·plan-view 때 다시 derive 해 요약만 갱신(rev·sha·input·
    version 불변). 코어가 algo 를 내지 않으면(병합 전) DB 를 바꾸지 않는다."""
    from esl_platform.api.services import doe_select

    s = _saved(client, world, engine, esl_root, selection(bead("b1", "holey")))
    sid = s["id"]
    row0 = _row(engine, sid)
    assert "algo" not in row0["selection"]["derived"]
    api(client, "GET", f"/doe/studies/{sid}/params")                        # 옛 코어 → 그대로
    assert _row(engine, sid)["selection"] == row0["selection"]
    FAKE["algo"] = 2                                                         # 코어 갱신(배포) 뒤
    doe_select.reset_caches()
    for path in ("params", "selection", "plan-view"):
        r = api(client, "GET", f"/doe/studies/{sid}/{path}", "tok-general")   # 조회 권한만으로도 캐시 갱신
        assert r.status_code == 200, (path, r.text)
        row = _row(engine, sid)
        assert row["version"] == row0["version"] and row["selection"]["rev"] == row0["selection"]["rev"]
        assert row["selection"]["sha256"] == row0["selection"]["sha256"]
        assert row["selection"]["input"] == row0["selection"]["input"] and row["selection"]["derived"]["algo"] == 2
        assert row["selection"]["derived"]["beads"][0]["holes"]["n"] == 1
        assert "section" not in row["selection"]["derived"]["beads"][0]
        doe_select.reset_caches()
        with engine.begin() as c:                                           # 다음 경로도 갱신하는지 — 다시 옛 요약으로
            c.execute(text("UPDATE bead_does SET selection = CAST(:s AS jsonb) WHERE id = :i"),
                      {"s": json.dumps(row0["selection"]), "i": sid})
    p = api(client, "GET", f"/doe/studies/{sid}/params").json()
    assert next(r for r in p["params"] if r["name"] == "B1_W")["feasible"] == [30.0, 64.0]   # 갱신된 요약 기준 표
    n = len(CALLS)
    api(client, "GET", f"/doe/studies/{sid}/params")                        # 이미 algo 있음 → 다시 derive 안 함
    assert len(CALLS) == n


def test_preview_cells_warnings_and_rules(client, world, engine, esl_root):
    """§4.3·§7.4: warn 정책 경고 칸 = READY + warnings + fixed_viol(상태 무관), 경고 없는 칸엔 키 없음. grid_manifest.rules 없는
    select 미리보기 → preview.rules_outdated true(실행은 막지 않음), rules 2 면 키 없음."""
    s = _saved(client, world, engine, esl_root)
    sid = s["id"]
    sel_sha = s["selection"]["sha256"]
    p = api(client, "POST", f"/doe/studies/{sid}/preview", json={"version": s["version"], "spec": SPEC}).json()
    m = api(client, "POST", f"/doe/studies/{sid}/matrix", json={"version": p["version"], "spec": SPEC}).json()
    simulate_select_preview(engine, esl_root, sid, p["job"]["id"], m, sel_sha, warn_first=True)
    g = api(client, "GET", f"/doe/studies/{sid}", "tok-general").json()
    pv = g["doe"]["preview"]
    cells = pv["cells"]
    assert cells[0]["status"] == "READY" and cells[0]["warnings"] == WARNS and cells[0]["fixed_viol"] == FV
    assert all("warnings" not in c and "fixed_viol" not in c for c in cells[1:])
    assert pv["rules_outdated"] is True
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"], "matrix_sha256": m["matrix_sha256"]})
    assert r.status_code == 202, r.text                                    # 띠만 — 실행은 막지 않음
    gd = study_dir(esl_root, sid) / "doe" / "1" / "grid" / "grid_manifest.json"
    gm = json.loads(gd.read_text(encoding="utf-8"))
    gm["rules"] = 2
    gd.write_text(json.dumps(gm), encoding="utf-8")
    pv = api(client, "GET", f"/doe/studies/{sid}").json()["doe"]["preview"]
    assert "rules_outdated" not in pv and pv["cells"][0]["warnings"] == WARNS


def test_results_best_clean_and_warn_rows(client, world, engine, esl_root):
    """SR-D-11: 순위 행 warn 그대로, 결과 summary.best_clean(코어 결과에 있을 때만)."""
    s = _saved(client, world, engine, esl_root)
    sid = s["id"]
    base = study_dir(esl_root, sid)
    (base / "post").mkdir(parents=True, exist_ok=True)
    res = {"scenario": "select", "C_ref": 10.0, "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3},
           "n_ok": 2, "n_skipped": {"collision": 0, "fixed": 0, "geom": 0, "mesh": 0}, "n_failed": {},
           "ranking": [{"id": "d001", "values": {"B1_D1": 4.0}, "score": 0.8, "rank": 1, "warn": ["FIXED_MOVED"]},
                       {"id": "d002", "values": {"B1_D1": 3.0}, "score": 0.9, "rank": 2}],
           "sensitivity": None, "boundary_warnings_n": 0, "view3d": [], "best": None, "warnings": [],
           "summary": {"best_clean": "d002"}}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    update_study(engine, sid, phase="DONE", result=res)
    o = api(client, "GET", f"/doe/studies/{sid}/results", "tok-general").json()
    assert o["ranking"][0]["warn"] == ["FIXED_MOVED"] and "warn" not in o["ranking"][1]
    assert o["summary"] == {"best_clean": "d002"}
    res.pop("summary")
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    assert api(client, "GET", f"/doe/studies/{sid}/results").json()["summary"] is None     # v0.16.0 결과 = 키 없음(null)


# ================================================================ v0.16.2 자동 탐지 seed · ② B 메시 기준 select(esl_bead_auto.md §3, V-AD-13·14)
def _auto_files(engine, esl_root, sid, *, ok=True, step=None, code_=None, sel=None, version="0.14.1"):
    """워커 BD_GEOM(prep/auto_detect.json) + 코어 BD_LOADS(prep/select/auto_selection.json) 흉내."""
    d = study_dir(esl_root, sid) / "prep"
    (d / "auto_detect.json").write_text(json.dumps({"schema": "esl/doe_auto_detect/1", "ok": ok, "step": step,
                                                    "code": code_, "paicad_version": version}), encoding="utf-8")
    if sel is not None:
        (d / "select").mkdir(parents=True, exist_ok=True)
        (d / "select" / "auto_selection.json").write_text(json.dumps({
            "schema": "esl/doe_auto_selection/1", "selection": sel,
            "map": [{"bead": b["id"], "paicad_id": f"B{i + 1}", "n_floor": 4} for i, b in enumerate(sel["beads"])],
            "warnings": [{"code": "AUTO_GROUP_DROPPED", "level": "info"}]}, sort_keys=True), encoding="utf-8")


def test_v0162_settings_select_auto_mesh(client, world, engine):
    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["select_auto"] is True and s["scenarios"]["select_mesh"] is True
    assert s["select"]["hole"] == {"bridge_max_mm": 20.0}
    # paicad 준비 안 됨 → 자동 탐지만 막힘(수동·B 메시 수동은 paicad 불필요 — BS-D-2)
    from esl_platform.api.services import doe as svc

    record_paicad(engine, ready=False, reason="PAICAD_VERSION_UNSUPPORTED")
    svc.reset_status_cache()
    s = api(client, "GET", "/doe/settings").json()
    assert s["scenarios"]["select"] is True and s["scenarios"]["select_mesh"] is True
    # v0.17.0(esl_beadgraph.md §5.5 D9): 자동 seed = 메시 분류기 → paicad 무관(select 가능 ∧ graph.enabled)
    assert s["scenarios"]["select_auto"] is True


def test_v0162_select_case_bead_source(client, world, engine):
    """V-AD-13(①): manual 은 STEP 금지, case 는 B 메시·파트 금지, select 밖 bead_source·select_base 422.
    v0.17.0(esl_beadgraph.md §5.3): auto + STEP 없음 허용(힌트 없음) — V-BG-15."""
    uid = upload_step(client)
    for extra in ({"bead_source": "manual", "step_upload_id": uid},
                  {"step_upload_id": uid}, {"select_base": "case", "mesh_upload_id": uid},
                  {"bead_source": "auto", "step_upload_id": uid, "part_title": "x"}):
        r = api(client, "POST", "/doe/check-inputs", json=sbody(world, **extra))
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", (extra, r.text)
    for extra in ({"bead_source": "manual"}, {"select_base": "case"}):
        r = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], uid, "same", **extra))
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", extra
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, bead_source="bogus"))
    assert r.status_code == 422
    r = api(client, "POST", "/doe/check-inputs", json=sbody(world, bead_source="auto", step_upload_id=uid))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["step"]["file_name"] and out["base"]["case_id"] == "c1" and out["mesh"] is None
    s = _create(client, world, bead_source="auto", step_upload_id=uid)
    assert s["scenario"] == "select" and s["inputs"]["bead_source"] == "auto" and "select_base" not in s["inputs"]
    assert s["inputs"]["step"]["upload_id"] == uid and s["inputs"]["mesh"] is None
    jp = _job(engine, s["job"]["id"])["params"]["doe"]
    assert jp["bead_source"] == "auto" and "select_base" not in jp and jp["step"]["path"].endswith(".step")
    assert jp["base"]["case_id"] == "c1"
    assert _row(engine, s["id"])["base"]["case_id"] == "c1"
    m = _create(client, world)                  # 기본 = manual(v0.16.1 과 같은 작업 params + bead_source)
    assert m["inputs"]["bead_source"] == "manual" and m["inputs"]["step"] is None
    jp = _job(engine, m["job"]["id"])["params"]["doe"]
    assert jp["bead_source"] == "manual" and "step" not in jp and "select_base" not in jp
    # v0.16.1 이전 select 스터디(inputs 에 bead_source 없음) → 응답은 manual
    with engine.begin() as c:
        c.execute(text("UPDATE bead_does SET inputs = inputs - 'bead_source' WHERE id=:i"), {"i": m["id"]})
    assert api(client, "GET", f"/doe/studies/{m['id']}").json()["inputs"]["bead_source"] == "manual"


def test_v0162_select_mesh_inputs(client, world, engine, tmp_path):
    """V-AD-13(②): mesh_upload_id 없음 422, manual + STEP 422(v0.17.0: auto + STEP 없음은 허용 — V-BG-15), 크기·인치 SIZE_MISMATCH, include 업로드 밖
    거부·파트 없음 = ② 규칙 그대로(MESH_INVALID·PART_NOT_FOUND), 같은 모델 검사 안 함. 생성 = scenario select + select_base mesh."""
    step = upload_step(client)
    mesh = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path)})
    ids = [world["a"], world["other"]]          # 다른 모델 섞임 — ② 규칙(같은 모델 검사 없음)

    def chk(**kw):
        return api(client, "POST", "/doe/check-inputs", json=sbody(world, ids, select_base="mesh", **kw))
    for kw in ({}, {"bead_source": "manual", "mesh_upload_id": mesh, "step_upload_id": step}):
        r = chk(**kw)
        assert r.status_code == 422 and code(r) == "INVALID_PARAMS", (kw, r.text)
    r = chk(mesh_upload_id=mesh, inch=55)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and all(e["ok"] for e in out["entries"]) and out["base"] is None and out["step"] is None
    assert out["mesh"]["ok"] is True and out["mesh"]["format"] == "rad" and out["size"]["inch"] == 55
    big = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path, plate(Lx=360.0))})
    assert code(chk(mesh_upload_id=big)) == "SIZE_MISMATCH"
    assert code(chk(mesh_upload_id=mesh, inch=65)) == "SIZE_MISMATCH"
    r = chk(mesh_upload_id=mesh, part_title="nothing here")
    assert r.status_code == 422 and code(r) == "PART_NOT_FOUND"
    outside = tmp_path / "outside.inc"
    outside.write_bytes(b"/SHELL/9\n         1         1         2         3         4\n")
    rb = rad_mesh_bytes(tmp_path).replace(b"/END", f"#include {outside}\n/END".encode(), 1)
    bad = upload_files(client, {"rad/B_0000.rad": rb})
    r = chk(mesh_upload_id=bad)
    # include 업로드 밖 = ② 와 같은 판정(AD-D-14 "② 입력 그대로" — 템플릿 메시 검사가 MESH_INVALID 로 거부)
    r2 = api(client, "POST", "/doe/check-inputs", json=body([world["a"]], step, "mesh", mesh_upload_id=bad))
    assert r.status_code == r2.status_code == 422 and code(r) == code(r2) and code(r) in ("MESH_INVALID", "PATH_OUTSIDE_ROOT")
    # 생성: auto(STEP 필수) — DB scenario select·base NULL·inputs.mesh, 작업 params = ② mesh + select_base·bead_source·step
    r = api(client, "POST", "/doe/studies", json=sbody(world, ids, select_base="mesh", bead_source="auto",
                                                       mesh_upload_id=mesh, step_upload_id=step, inch=55))
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["scenario"] == "select" and s["inputs"]["select_base"] == "mesh" and s["inputs"]["bead_source"] == "auto"
    assert s["inputs"]["mesh"]["upload_id"] == mesh and s["inputs"]["step"]["upload_id"] == step
    assert s["inputs"]["part_title"] == "chassis rear" and s["inputs"]["inch"] == 55 and "B 메시" in s["title"]
    row = _row(engine, s["id"])
    assert row["scenario"] == "select" and row["base"] is None and row["selection"] is None
    jp = _job(engine, s["job"]["id"])["params"]["doe"]
    assert jp["select_base"] == "mesh" and jp["bead_source"] == "auto" and "base" not in jp
    assert jp["mesh"]["path"].endswith("rad/B_0000.rad") and Path(jp["mesh"]["upload_root"]).is_dir()
    assert jp["mesh"]["part_title"] and jp["step"]["path"].endswith(".step") and jp["inch"] == 55
    assert "rad_path" not in json.dumps(s) and "upload_root" not in json.dumps(s)
    # manual(STEP 없음)
    r = api(client, "POST", "/doe/studies", json=sbody(world, ids, select_base="mesh", mesh_upload_id=mesh))
    assert r.status_code == 201, r.text
    sm = r.json()
    assert sm["inputs"]["bead_source"] == "manual" and sm["inputs"]["step"] is None
    assert "step" not in _job(engine, sm["job"]["id"])["params"]["doe"]
    # 복제 = select(mesh) 유지(B 메시 업로드 재사용), 업로드가 없어지면 409 PREREQUISITE_MISSING
    c = api(client, "POST", f"/doe/studies/{sm['id']}/clone", json={})
    assert c.status_code == 201, c.text
    c = c.json()
    assert c["scenario"] == "select" and c["inputs"]["select_base"] == "mesh"
    assert _job(engine, c["job"]["id"])["params"]["doe"]["select_base"] == "mesh"
    Path(jp["mesh"]["path"]).unlink()
    r = api(client, "POST", f"/doe/studies/{sm['id']}/clone", json={})
    assert r.status_code == 409 and code(r) == "PREREQUISITE_MISSING" and r.json()["detail"]["missing"] == ["mesh"]


def test_v0162_legacy_same_mesh_still_accepted(client, world, engine, tmp_path):
    """AD-D-23 · V-AD-14(API): 화면에서 숨겨도 API 는 same·mesh 생성을 계속 받는다(스크립트 호환)."""
    step = upload_step(client)
    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], step, "same"))
    assert r.status_code == 201 and r.json()["scenario"] == "same", r.text
    assert "bead_source" not in r.json()["inputs"]
    mesh = upload_files(client, {"rad/B_0000.rad": rad_mesh_bytes(tmp_path)})
    r = api(client, "POST", "/doe/studies", json=body([world["a"]], step, "mesh", mesh_upload_id=mesh))
    assert r.status_code == 201 and r.json()["scenario"] == "mesh", r.text
    jp = _job(engine, r.json()["job"]["id"])["params"]["doe"]
    assert "select_base" not in jp and "bead_source" not in jp


def test_v0162_select_auto_endpoint(client, world, engine, esl_root):
    """GET …/select/auto: manual 404 AUTO_NOT_AVAILABLE, 준비 전 409 PREP_NOT_READY, seed 없음(탐지 실패) 404, seed 있음 =
    {selection, sha256(= 같은 선택을 PUT 한 sha — V-AD-1 API 쪽), map, warnings, paicad_version}. 저장하지 않는다."""
    uid = upload_step(client)
    man = _ready(client, world, engine, esl_root)
    r = api(client, "GET", f"/doe/studies/{man['id']}/select/auto")
    assert r.status_code == 404 and code(r) == "AUTO_NOT_AVAILABLE"
    s = _create(client, world, bead_source="auto", step_upload_id=uid)
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == 409 and code(r) == "PREP_NOT_READY"
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"])
    _auto_files(engine, esl_root, s["id"], ok=False, step="tag", code_="GEOM_INPUT_INVALID")
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto")
    assert r.status_code == 404 and code(r) == "AUTO_NOT_AVAILABLE"
    seed = selection(bead("b1", tiers=((1, 4),)), bead("b2", tiers=((10, 12),)))
    _auto_files(engine, esl_root, s["id"], sel=seed, version="0.14.2")
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto", "tok-general")     # 조회 권한이면 읽기 가능
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["selection"] == seed and a["paicad_version"] == "0.14.2"
    assert a["map"] == [{"bead": "b1", "paicad_id": "B1", "n_floor": 4}, {"bead": "b2", "paicad_id": "B2", "n_floor": 4}]
    assert [w["code"] for w in a["warnings"]] == ["AUTO_GROUP_DROPPED"]
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["selection"] is None                                   # seed 는 저장 전 미저장(AD-D-4)
    saved = _save(client, g, seed)
    assert saved.status_code == 200, saved.text
    assert saved.json()["selection"]["sha256"] == a["sha256"]       # seed 그대로 저장 = 같은 sha
    assert api(client, "GET", "/doe/studies/nope/select/auto").status_code == 404
    r = api(client, "GET", f"/doe/studies/{s['id']}/select/auto", "tok-nonmember")
    assert r.status_code == 403


def test_v0162_prep_summary_auto_passthrough(client, world, engine, esl_root):
    """준비 요약 prep.auto{ok, step, code, available, n_beads}·select_base(워커 BD_PREP_REGISTER) → DoeStudyOut.prep 그대로."""
    uid = upload_step(client)
    s = _create(client, world, bead_source="auto", step_upload_id=uid)
    simulate_select_prep(engine, esl_root, s["id"], s["job"]["id"], world["mesh"])
    with engine.connect() as c:
        prep = dict(c.execute(text("SELECT prep FROM bead_does WHERE id=:i"), {"i": s["id"]}).scalar_one())
    prep.update(auto={"ok": False, "step": "version", "code": "PAICAD_NOT_FOUND", "available": False, "n_beads": 0},
                select_base="mesh")
    update_study(engine, s["id"], prep=prep)
    g = api(client, "GET", f"/doe/studies/{s['id']}").json()
    assert g["prep"]["auto"] == prep["auto"] and g["prep"]["select_base"] == "mesh"


def test_v0162_legacy_result_warnings_visible(client, world, engine, esl_root):
    """V-AD-7(API 쪽 · AD-D-8): 코어가 result.json warnings·순위 행 warn 에 올린 MORPH_EXTREME_ELEMENTS 는 GET …/results 에 그대로
    보인다(legacy same 결과도 — 백엔드는 거르지 않음)."""
    r = api(client, "POST", "/doe/studies", json=body([world["a"], world["b"]], upload_step(client), "same"))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    base = study_dir(esl_root, sid)
    (base / "post").mkdir(parents=True, exist_ok=True)
    ext = {"code": "MORPH_EXTREME_ELEMENTS", "n": 3, "rot_max_deg": 61.0, "area_ratio_min": 0.12, "design": "d001"}
    res = {"scenario": "same", "C_ref": 10.0, "baseline": {"id": "d000", "score": 1.0, "umax": 1.0, "epsmax": 1e-3},
           "n_ok": 1, "n_skipped": {"collision": 0, "fixed": 0, "geom": 0}, "n_failed": {},
           "ranking": [{"id": "d001", "values": {"X": 4.0}, "score": 0.8, "rank": 1, "warn": ["MORPH_EXTREME_ELEMENTS"]}],
           "sensitivity": None, "boundary_warnings_n": 0, "view3d": [], "best": None,
           "warnings": [ext, "STEP_EXPORT_SKIPPED: x"]}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    finish_job(engine, r.json()["job"]["id"])
    update_study(engine, sid, phase="DONE", result=res)
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["warnings"][0] == ext and o["warnings"][1]["code"] == "STEP_EXPORT_SKIPPED"
    assert o["ranking"][0]["warn"] == ["MORPH_EXTREME_ELEMENTS"]
