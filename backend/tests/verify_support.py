"""v0.12.0 검증 낙하(계약 esl_scx_relay.md 기능 B) 시험 공용: 기능 B 설정, 강성 평가 스터디(① same·DONE)·ESL 항목·Case 를 DB 와
폴더에 직접 심는다(계산 없이). backend/tests/scx·worker/tests 가 같이 쓴다.

- 씬 Case: input_roots 아래 `<name>/model_0000.rad`(+ include `inc/part.inc`, 엔진 `model_0001.rad`), 추출 완료 표시
  (extract_summary + `<esl_root>/<folder>/01_extract/model.npz`) — 실제 추출 산출물이 필요한 워커 시험은 real_case 로 대체.
- DOE 폴더: post/result.json(ranking 행 per_esl), run/designs/d000/result.json(베이스라인 per_esl), best/<did>/include/<rel>.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import insert, text

from scx_support import scx_settings


def verify_settings(base: Path, relay, **over: Any) -> dict[str, Any]:
    d = scx_settings(base, relay)
    d["verify_drop"] = {"enabled": True, "max_scenes": 3, "default_worst_n": 2, "poll_s": 0.05, "max_wait_h": 1,
                        "lost_after_polls": 3, "est_hours_per_scene": 3}
    d["scx_drive"]["retry_wait_s"] = 0
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


def write_case_inputs(inputs_root: Path, name: str, *, engine_rad: bool = True, includes: list[str] | None = None,
                      extra_files: dict[str, bytes] | None = None) -> str:
    from scx_support import mini_rad

    d = inputs_root / name
    (d / "inc").mkdir(parents=True, exist_ok=True)
    incs = includes if includes is not None else ["inc/part.inc"]
    (d / "model_0000.rad").write_bytes(mini_rad(incs))
    (d / "inc" / "part.inc").write_bytes(b"# part include\n")
    if engine_rad:
        (d / "model_0001.rad").write_bytes(b"/RUN/model/1\n0.01\n/END\n")
    for k, v in (extra_files or {}).items():
        p = d / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(v)
    return str(d / "model_0000.rad")


def seed_case(engine, esl_root: Path, inputs_root: Path, name: str, *, extract: bool = True, cumulative: bool = False,
              **kw: Any) -> dict[str, Any]:
    from esl_platform.core.db.tables import cases
    from esl_platform.core.inputs import fingerprint

    rad = write_case_inputs(inputs_root, name, **kw)
    cid = str(uuid.uuid4())
    folder = f"vd_{name}"
    fp = fingerprint(rad, str(inputs_root / name), [])
    es = {"requested_part_title": "Chassis rear", "job_id": None, **({"cumulative": {"n": 1}} if cumulative else {})}
    with engine.begin() as c:
        c.execute(insert(cases).values(id=cid, project_id="p-1", folder_name=folder, title=f"씬 {name}", rad_path=rad,
                                       results_dir=str(inputs_root / name), input_fingerprint=fp,
                                       part_title="Chassis rear", extract_summary=es if extract else None,
                                       created_by="u-power", created_by_name="파워"))
    if extract:
        ed = esl_root / folder / "01_extract"
        ed.mkdir(parents=True, exist_ok=True)
        xs = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], float) * 10.0
        np.savez(ed / "model.npz", node_id=np.arange(1, 10), x0=xs)
    return {"id": cid, "rad": rad, "folder": folder, "title": f"씬 {name}"}


def seed_entry_for(engine, case_id: str, *, scene_no: int = 1) -> str:
    from p2_support import seed_entry, seed_run

    run = seed_run(engine, case_id)
    return seed_entry(engine, case_id, run["run_id"], scene_no=scene_no)


def seed_study(engine, esl_root: Path, entries: list[str], *, scenario: str = "same", phase: str = "DONE",
               ratios: dict[str, float] | None = None, did: str = "d007", rank: int = 1, best_files: bool = True,
               best_nodes: dict[int, tuple] | None = None, inline: bool = True) -> str:
    """강성 평가 스터디 행 + DOE 결과 폴더. ratios = {entry_id: r_c}(umax·epsmax 비 = r_c·0.9 / r_c·1.1)."""
    from esl_platform.core.repositories import doe as doe_repo

    sid = str(uuid.uuid4())
    ratios = ratios or {e: 0.9 for e in entries}
    base = esl_root / "_doe" / sid
    per = [{"entry_id": e, "C": 100.0 * r, "ratio": r, "umax": 2.0 * r * 0.9, "epsmax": 0.01 * r * 1.1}
           for e, r in ratios.items()]
    bper = [{"entry_id": e, "C": 100.0, "umax": 2.0, "epsmax": 0.01} for e in ratios]
    row = {"id": did, "rank": rank, "score": 0.8, "values": {}, "worst_ratio": max(ratios.values())}
    if inline:
        row["per_esl"] = per
    res = {"C_ref": 100.0, "baseline": {"id": "d000"}, "n_ok": 1, "ranking": [row], "per_esl_inline": inline,
           "best": {"id": did, "files": ["values.json"]}, "best_all": [{"id": did, "files": ["values.json"]}],
           "warnings": []}
    (base / "post").mkdir(parents=True)
    (base / "post" / "result.json").write_text(json.dumps(res), encoding="utf-8")
    (base / "post" / "per_esl.json").write_text(json.dumps({"designs": {did: per}}), encoding="utf-8")
    (base / "run" / "designs" / "d000").mkdir(parents=True)
    (base / "run" / "designs" / "d000" / "result.json").write_text(json.dumps({"id": "d000", "status": "OK",
                                                                              "per_esl": bper}), encoding="utf-8")
    if best_files:
        inc = base / "best" / did / "include"
        inc.mkdir(parents=True)
        nodes = best_nodes or {5: (10.0, 10.0, 1.5)}
        (inc / "model_0000.rad").write_text("/NODE\n" + "".join(f"{k:10d}{v[0]:20.6f}{v[1]:20.6f}{v[2]:20.6f}\n"
                                                                for k, v in nodes.items()), encoding="utf-8")
    with engine.begin() as c:
        doe_repo.insert_study(c, id=sid, project_id="p-1", scenario=scenario, title="스터디", entry_ids=entries,
                              base={"entry_id": entries[0]} if scenario == "same" else None, inputs={}, phase=phase,
                              dir_rel=f"_doe/{sid}", created_by="u-power", created_by_name="파워",
                              result={"ranking": []} if phase == "DONE" else None)
    return sid


def counts(engine) -> tuple[int, int]:
    with engine.connect() as c:
        return (int(c.execute(text("SELECT count(*) FROM verify_drops")).scalar_one()),
                int(c.execute(text("SELECT count(*) FROM jobs WHERE job_type='VERIFY_DROP'")).scalar_one()))
