"""P2 시험 도우미: DB 에 ESL 실행·검증·라이브러리 항목 행을 직접 심는다(계산 없이 API 권한·오류 코드 시험용)."""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from typing import Any

import numpy as np
from esl_platform.core.db.tables import (
    esl_runs,
    jobs,
    library_entries,
    support_sets,
    validations,
)
from sqlalchemy import insert


def seed_run(engine, case_id: str, *, project_id: str = "p-1", verdict: str | None = "PASS",
             field: dict | None = None, val_extra: dict | None = None) -> dict[str, Any]:
    jid, sid, rid = (str(uuid.uuid4()) for _ in range(3))
    with engine.begin() as c:
        c.execute(insert(jobs).values(id=jid, case_id=case_id, project_id=project_id, job_type="ESL_SOLVE", stage=4,
                                      lane="SLOT", state="SUCCEEDED", holds_slot=False, params={}, created_by="u-power",
                                      created_by_name="파워"))
        c.execute(insert(support_sets).values(id=sid, case_id=case_id, node_ids=[1, 2, 3], dofs=["123", "13", "1"],
                                              source="auto", created_by="u-power"))
        c.execute(insert(esl_runs).values(id=rid, case_id=case_id, job_id=jid, frame_index=0, metric="max_strain",
                                          support_set_id=sid, dir_rel=f"runs/{rid}", status="READY",
                                          inputs_hash="0" * 64))
        vid = None
        if verdict:
            vid = str(uuid.uuid4())
            c.execute(insert(validations).values(id=vid, esl_run_id=rid, case_id=case_id, job_id=jid, hotspots=[],
                                                 verdict=verdict, criteria={}, field=field, dir_rel="05_val",
                                                 **(val_extra or {})))
    return {"job_id": jid, "run_id": rid, "validation_id": vid, "support_set_id": sid}


def seed_entry(engine, case_id: str, run_id: str, *, esl_root: str | None = None, project_id: str = "p-1",
               registered_by: str = "u-power", name: str = "55QX10A", inch: int = 55, drop_type: str = "Corner",
               orient: str = "146", verdict: str = "PASS", grid: tuple[int, int] = (24, 14),
               product_mass: float | None = None, status: str = "ACTIVE", version: str | None = None,
               scene_no: int = 1, registered_at: _dt.datetime | None = None,
               quality_extra: dict | None = None) -> str:
    eid = str(uuid.uuid4())
    dir_rel = f"_library/entries/{eid}"
    if esl_root:
        d = os.path.join(esl_root, *dir_rel.split("/"))
        os.makedirs(d)
        with open(os.path.join(d, "entry.json"), "w", encoding="utf-8") as fh:
            json.dump({"entry_id": eid}, fh)
    with engine.begin() as c:
        c.execute(insert(library_entries).values(
            id=eid, project_id=project_id, case_id=case_id, esl_run_id=run_id, status=status,
            model={"name": name, "inch": inch, "product_mass": product_mass, "version": version},
            scene={"drop_type": drop_type, "drop_class": drop_type, "orient": orient, "scenario": "FREE",
                   "scene_no": scene_no, "warnings": []},
            quality={"verdict": verdict, "fail_reasons": [], **(quality_extra or {})}, summary={"grid": {"nx": grid[0], "ny": grid[1]}},
            dir_rel=dir_rel, summary_rel=f"{dir_rel}/summary.npz", sha256="0" * 64,
            registered_by=registered_by, registered_by_name=registered_by,
            retired_at=None if status == "ACTIVE" else _dt.datetime(2026, 10, 19, tzinfo=_dt.timezone.utc),
            **({"registered_at": registered_at} if registered_at else {})))
    return eid


def write_compare_field(path_dir: str, n: int, seed: int = 0) -> dict[str, np.ndarray]:
    """코어 compare_field.npz 와 같은 키의 합성 배열(n 요소, 평면 300×200 위 무작위 중심)."""
    rng = np.random.default_rng(seed)
    c2 = np.column_stack([rng.uniform(-150, 150, n), rng.uniform(-100, 100, n)])
    er = rng.uniform(1e-4, 1e-2, n)
    ee = er * (1 + rng.normal(0, 0.05, n))
    rel = (ee - er) / er
    reason = rng.choice([0, 0, 0, 1, 2], n).astype(np.int8)
    valid = reason == 0
    arr = dict(
        elem_id=np.arange(1, n + 1, dtype=np.int64) * 2 + 1000, centroid2d=c2, centroid3d=np.column_stack([c2, 0 * er]),
        eps_rad=er, eps_esl=ee, rel_err=rel, valid=valid, rising=reason != 1, reason=reason, elem_size=np.full(n, 2.0),
        n0=0.01 * c2[:, 0], w_rel=1e-3 * np.cos(c2[:, 0] / 50), w_val=1.01e-3 * np.cos(c2[:, 0] / 50),
        plane_origin=np.array([0.0, 800.0, 300.0]), plane_e1=np.array([1.0, 0, 0]), plane_e2=np.array([0, 0, 1.0]),
        plane_n=np.array([0, -1.0, 0]), xi_range=np.array([-150.0, 150.0]), eta_range=np.array([-100.0, 100.0]),
        frame_index=np.int64(6), prev_frame_index=np.int64(5), sec_band=np.array([0.02, 0.02]))
    os.makedirs(path_dir, exist_ok=True)
    np.savez_compressed(os.path.join(path_dir, "compare_field.npz"), **arr)
    return arr
