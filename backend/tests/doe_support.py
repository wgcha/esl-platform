"""비드 DOE(v0.9.0, 계약 esl_bead_doe.md) 백엔드 시험 도우미.

- 설정: bead_doe.enabled + 가짜 paicad 실행 파일(빈 파일 — 백엔드는 실행하지 않음) + 업로드 루트(opt_support 재사용).
- 워커 점검 기록: worker_heartbeats.info.paicad·gmsh(워커 D3 가 쓰는 형식)를 직접 넣는다.
- 워커 단계 산출물 흉내: prep/params.json·plan.json, doe/<rev>/matrix.json·grid, post/result.json … 을 연구 폴더에 쓰고
  작업을 SUCCEEDED 로, bead_does 를 워커 등록(BD_*_REGISTER)과 같은 모양으로 갱신한다.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from esl_test_support import API, H
from opt_support import opt_settings_dict, plate, upload_files
from sqlalchemy import text

W = H("tok-power", True)
R = H("tok-power")
STEP_BYTES = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ch_r mid surface'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def doe_settings_dict(base: Path, *, paicad: bool = True, **over: Any) -> dict[str, Any]:
    d = opt_settings_dict(base)
    tools = base / "tools"
    tools.mkdir(exist_ok=True)
    exe = tools / "paicad"
    if paicad:
        exe.write_text("")
    d["bead_doe"] = {"enabled": True, "paicad": {"exe": str(exe)}, "settings_cache_s": 0}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


def record_paicad(engine, *, ready: bool = True, version: str = "0.14.0", ocp: str | None = "7.8.1",
                  reason: str | None = None, warning: str | None = None, gmsh: bool = True) -> None:
    from esl_platform.core.repositories import workers as workers_repo

    info = {"claims_paused": False,
            "paicad": {"ready": ready, "version": version, "ocp": ocp, "pinned": "0.14.0", "warning": warning,
                       "reason": reason, "checked_at": "2026-10-29T00:00:00Z"},
            "gmsh": {"ready": gmsh, "version": "4.13.1" if gmsh else None}}
    with engine.begin() as c:
        workers_repo.heartbeat(c, worker_id="w-doe", host="h", pid=1, app_version="0.9.0", limiter="none", info=info)


def png_bytes(w: int = 2, h: int = 2) -> bytes:
    def chunk(t: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def upload_step(client, data: bytes = STEP_BYTES, name: str = "rad/chassis_mid.step", token: str = "tok-power") -> str:
    return upload_files(client, {name: data}, token=token)


def rad_mesh_bytes(tmp: Path, mesh: dict | None = None, part_title: str = "chassis rear") -> bytes:
    from esl.doe import export_mesh

    d = tmp / f"radmesh_{hashlib.sha1(part_title.encode()).hexdigest()[:6]}"
    m = dict(mesh if mesh is not None else plate())
    export_mesh.write(str(d), m, part_title=part_title)
    return (d / export_mesh.RAD_NAME).read_bytes()


def body(entry_ids: list[str], step_uid: str, scenario: str = "same", **kw: Any) -> dict[str, Any]:
    return {"project_id": "p-1", "scenario": scenario, "entry_ids": entry_ids, "step_upload_id": step_uid, **kw}


# ---------------------------------------------------------------- 워커 산출물·등록 흉내
def study_dir(esl_root: Path, sid: str) -> Path:
    return esl_root / "_doe" / sid


def finish_job(engine, job_id: str, state: str = "SUCCEEDED", code: str | None = None) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET state=:s, queue_seq=NULL, failure_code=:f, finished_at=now() WHERE id=:i"),
                  {"s": state, "f": code, "i": job_id})


def update_study(engine, sid: str, **values: Any) -> None:
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        doe_repo.update_study(c, sid, **values)


PARAMS = [
    {"name": "CHR_BEAD_D_1", "type": "D", "bead": "B1", "nominal": 4.0, "feasible": [2.1, 6.4],
     "feasible_source": "estimate", "default_range": [2.1, 6.4], "use_default": True, "group_members": ["CHR_BEAD_D_1"]},
    {"name": "CHR_BEAD_W_1", "type": "W", "bead": "B1", "nominal": 12.0, "feasible": [9.0, 16.0],
     "feasible_source": "estimate", "default_range": [9.0, 16.0], "use_default": True, "group_members": ["CHR_BEAD_W_1"]},
    {"name": "CHR_BEAD_U_1", "type": "U", "bead": "B1", "nominal": 0.0, "feasible": None,
     "feasible_source": "estimate", "default_range": [-5.0, 5.0], "use_default": True, "group_members": ["CHR_BEAD_U_1"]},
]


def simulate_prep(engine, esl_root: Path, sid: str, job_id: str) -> None:
    d = study_dir(esl_root, sid) / "prep"
    (d / "extract").mkdir(parents=True, exist_ok=True)
    (d / "extract" / "B1.png").write_bytes(png_bytes())
    beads = [{"id": "B1", "k": 1, "shape": "linear", "sense": "concave", "center_ab": [100.0, 50.0],
              "nominal": {"depth": 4.0, "width": 12.0, "length": 80.0}, "fixed_overlap": False, "png": "B1.png"},
             {"id": "B5", "k": None, "shape": "circular", "sense": None, "center_ab": None,
              "nominal": {"depth": 3.0, "width": 10.0}, "fixed_overlap": True, "png": None}]
    (d / "params.json").write_text(json.dumps({"beads": beads, "params": PARAMS,
                                               "warnings": [{"code": "BEAD_FIXED_OVERLAP", "bead": "B5",
                                                             "message": "고정 겹침"}]}), encoding="utf-8")
    plan = {"key": {"template_id": None, "topo_sha256": None}, "frame": {"a_range": [0, 300], "b_range": [0, 200]},
            "outline": [[0, 0], [300, 0], [300, 200], [0, 200]], "holes": [],
            "elems": {"n_total": 96, "decimated": False, "points": [[1.0, 2.0]]},
            "auto_keepout": {"hole_radius_mm": 15, "edge_band_mm": 10, "polygons": []},
            "beads": [{"id": "B1", "ring": [[0, 0], [1, 0], [1, 1]]}],
            "fixed": [{"label": "HOLE#1", "kind": "HOLE", "a": 10.0, "b": 20.0}],
            "a_points": [{"label": "RBE2#3", "kind": "RBE2", "a": 15.0, "b": 25.0}],
            "load_points": [{"entry_id": "e1", "label": "C1", "share": 0.4, "a": 50.0, "b": 60.0}],
            "links": [{"from": "RBE2#3", "to": "HOLE#1", "d_mm": 7.07, "warn": False},
                      {"from": "하중 e1 C1", "to": "HOLE#1", "d_mm": 56.6, "warn": True}],
            "warnings": []}
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    finish_job(engine, job_id)
    update_study(engine, sid, phase="READY", paicad_version="0.14.0",
                 prep={"n_beads": 2, "n_params": 3, "paicad_version": "0.14.0", "warnings": [],
                       "boundary": {"n_warn": 1, "n_info": 0}})


def simulate_preview(engine, esl_root: Path, sid: str, job_id: str, matrix: dict[str, Any]) -> None:
    rev = 1
    gd = study_dir(esl_root, sid) / "doe" / str(rev) / "grid"
    (gd / "nominal").mkdir(parents=True, exist_ok=True)
    (gd / "nominal" / "thumb.png").write_bytes(png_bytes())
    (study_dir(esl_root, sid) / "doe" / str(rev) / "matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
    cells = []
    ids = [d["id"] for d in matrix["designs"] if d["id"] != "d000"]
    for i, did in enumerate(ids):
        (gd / "cells" / did).mkdir(parents=True, exist_ok=True)
        if i == 0:
            cells.append({"id": did, "status": "FAIL", "code": "GEOM_FEATURE_COLLISION"})
        elif i == 1:
            cells.append({"id": did, "status": "ERROR", "code": "VIEW_TOO_LARGE"})
        else:
            (gd / "cells" / did / "thumb.png").write_bytes(png_bytes())
            cells.append({"id": did, "status": "OK", "code": None})
    (gd / "grid_manifest.json").write_text(json.dumps({"schema_version": 1, "cells": cells}), encoding="utf-8")
    finish_job(engine, job_id)
    from esl_platform.core.repositories import doe as doe_repo

    with engine.begin() as c:
        s = doe_repo.get_study(c, sid)
    doe = dict(s["doe"])
    doe["preview"] = {"rev": rev, "matrix_sha256": doe["matrix_sha256"], "ok": len(ids) - 1,
                      "skipped": {"collision": 1, "fixed": 0, "geom": 0}}
    update_study(engine, sid, phase="PREVIEW_READY", doe=doe)


def simulate_run(engine, esl_root: Path, sid: str, job_id: str, matrix: dict[str, Any]) -> dict[str, Any]:
    base = study_dir(esl_root, sid)
    ids = [d["id"] for d in matrix["designs"]]
    best = ids[2]
    import numpy as np
    from esl.view3d import build_view

    m = plate(nx=4, ny=3)
    f = np.zeros((m["node_id"].size, 3))
    f[:, 1] = 1.0
    for did in ("d000", best):
        od = base / "post" / "view3d" / did
        od.mkdir(parents=True, exist_ok=True)
        build_view(str(od), node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], f=f,
                   u_rel=f * 0.01, supports=[{"node_id": int(m["node_id"][0]), "dof": "123"}], key=f"doe/{did}",
                   esl_run_id="e1")
    (base / "best" / best / "include").mkdir(parents=True, exist_ok=True)
    (base / "best" / best / "values.json").write_text("{}", encoding="utf-8")
    (base / "best" / best / "include" / "chr_0001.inc").write_text("/NODE\n", encoding="utf-8")
    (base / "best" / best / "sample.brep").write_bytes(b"DBRep")
    (base / "post" / "ranking.csv").write_text("id,rank\n", encoding="utf-8")
    (base / "report.html").write_text("<html><body>보고서</body></html>", encoding="utf-8")
    (base / "run" / "designs" / best / "paicad").mkdir(parents=True, exist_ok=True)
    (base / "run" / "designs" / best / "paicad" / "paicad.log").write_text("argv …\n", encoding="utf-8")
    designs = [{"id": "d000", "status": "OK", "code": None, "score": 1.0},
               {"id": ids[1], "status": "SKIPPED_COLLISION", "code": "GEOM_FEATURE_COLLISION", "score": None},
               {"id": best, "status": "OK", "code": None, "score": 0.81}]
    designs += [{"id": i, "status": "FAILED_MORPH", "code": "GEOM_QUALITY", "score": None} for i in ids[3:4]]
    (base / "post" / "designs.json").write_text(json.dumps({"designs": designs}), encoding="utf-8")
    res = {"C_ref": 120.0, "baseline": {"id": "d000", "score": 1.0, "umax": 3.9, "epsmax": 0.0026, "umax_all": 4.0,
                                         "epsmax_all": 0.003, "worst_entry_id": "e1"},
           "n_ok": 1, "n_skipped": {"collision": 1, "fixed": 0, "geom": 0}, "n_failed": {"morph": 1, "mesh": 0, "solve": 0},
           "ranking": [{"id": best, "values": matrix["designs"][2]["values"], "score": 0.81, "improvement": 0.19,
                        "worst_entry_id": "e1", "umax": 3.4, "epsmax": 0.0021, "umax_all": 3.5, "epsmax_all": 0.0022,
                        "noise": None, "warnings_n": 0, "C": {"e1": 97.2}, "rank": 1}],
           "sensitivity": None, "sensitivity_reason": "OK 2 < 변수 2 + 2", "boundary_warnings_n": 0,
           "view3d": ["d000", best], "best": {"id": best, "files": ["values.json", "include/chr_0001.inc",
                                                                     "sample.brep"]},
           "best_all": [], "noise_floor": None, "matrix_sha256": matrix["matrix_sha256"],
           "warnings": ["STEP_EXPORT_SKIPPED: x (gmsh 없음 — BREP 만)"], "cleanup_bytes": 0}
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    finish_job(engine, job_id)
    update_study(engine, sid, phase="DONE", result={k: v for k, v in res.items() if k != "best_all"},
                 report_rel="report.html")
    return {"best": best}


def api(client, method: str, path: str, token: str = "tok-power", write: bool | None = None, **kw: Any):
    w = write if write is not None else method != "GET"
    return client.request(method, f"{API}{path}", headers=H(token, w), **kw)
