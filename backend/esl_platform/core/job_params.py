"""작업 params 생성(API·워커 공용, 계약 esl_run_all.md RA-D-6). `services/jobs._prepare` 에서 옮김(동작 불변).

API 는 `ctx.config.core`, 일괄 실행 워커 훅은 체인 행의 `core_settings` 스냅샷을 넘긴다(워커는 코어 설정 파일을 읽지 않음).
사전조건 미충족은 409 PREREQUISITE_MISSING(+ missing), 후보 아닌 frame 은 422 FRAME_NOT_CANDIDATE.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.engine import Connection

from . import core_outputs as co
from .errors import conflict, unprocessable
from .inputs import esl_run_stale, extract_stale, inputs_hash
from .repositories import cases as cases_repo


def core_settings_for(core_cfg: dict[str, Any] | None, case: dict[str, Any], *, metric: str | None = None,
                      material_override: dict | None = None) -> dict[str, Any]:
    """코어 설정 스냅샷 + Case 값(part_title, t* 지표, 재료 override)."""
    cfg = copy.deepcopy(core_cfg or {})
    cfg.setdefault("case", {})["part_title"] = case["part_title"]
    if metric and isinstance(cfg.get("tstar"), dict) and "metric" in cfg["tstar"]:
        cfg["tstar"]["metric"] = metric
    if material_override:
        mo = dict(cfg["case"].get("material_override") or {})
        mo.update({str(k): dict(v) for k, v in material_override.items()})
        cfg["case"]["material_override"] = mo
    return cfg


def esl_solve_params(conn: Connection, core_cfg: dict[str, Any] | None, cdir: str, case: dict[str, Any], *,
                     frame_index: int | None = None, support_set_id: str | None = None,
                     material_override: dict | None = None) -> dict[str, Any]:
    missing: list[str] = []
    if not case.get("extract_summary") or extract_stale(case):
        missing.append("extract")
    ts = case.get("tstar")
    if not ts:
        missing.append("tstar")
    sid = support_set_id or case.get("current_support_set_id")
    sup = cases_repo.get_support_set(conn, sid) if sid else None
    if sup is None or sup["case_id"] != case["id"]:
        missing.append("support_set")
    frame = frame_index if frame_index is not None else (ts or {}).get("frame_index")
    if not missing and frame not in co.disp_frames(cdir):
        missing.append("disp_frame")
    if missing:
        # v0.10.0 MR-D-4: ② 지지점 자동 선택이 품질 검사에 걸렸으면 support_blocked + 사유
        auto = (ts or {}).get("support_auto") if isinstance(ts, dict) else None
        blocked = "support_set" in missing and isinstance(auto, dict) and auto.get("status") == "BLOCKED"
        extra = {"support_blocked": True, "problems": auto.get("problems") or []} if blocked else {}
        raise conflict("PREREQUISITE_MISSING", "② 지지점 자동 선택 실패 — ②에서 사유 확인" if blocked
                       else "앞 단계가 필요합니다", missing=missing, **extra)
    metric = ts.get("metric") or "max_strain"
    if frame_index is not None and frame_index != ts.get("frame_index"):
        info = co.tstar_info(cdir)
        cands = [c["frame_index"] for c in (info["metrics"].get(metric) or {}).get("candidates", [])]
        if frame_index not in cands:
            raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {frame_index} 은 후보가 아닙니다", candidates=cands)
    es = case["extract_summary"] or {}
    ih = inputs_hash(extract_job_id=es.get("job_id"), part_title=case["part_title"],
                     tstar={"frame_index": frame, "metric": metric}, support_set_id=sup["id"])
    return {"settings": core_settings_for(core_cfg, case, metric=metric, material_override=material_override),
            "frame_index": int(frame), "metric": metric, "support_set_id": sup["id"],
            "support_node_ids": list(sup["node_ids"]), "support_dofs": list(sup["dofs"]), "inputs_hash": ih,
            "material_override": material_override}


def run_ref_params(conn: Connection, core_cfg: dict[str, Any] | None, case: dict[str, Any], job_type: str,
                   esl_run_id: str | None, targets: list[str] | None = None) -> dict[str, Any]:
    """VALIDATE·EXPORT: 대상 ESL 실행이 READY·현재(VALIDATE 는 비stale)."""
    missing: list[str] = []
    run = cases_repo.get_esl_run(conn, esl_run_id) if esl_run_id else None
    if run is None or run["case_id"] != case["id"] or run["status"] != "READY":
        missing.append("esl_run")
    elif case.get("current_esl_run_id") != run["id"]:
        missing.append("current_esl_run")
    elif job_type == "VALIDATE" and esl_run_stale(case, run):
        missing.append("fresh_esl_run")
    if missing:
        raise conflict("PREREQUISITE_MISSING", "유효한 ESL 결과가 필요합니다", missing=missing)
    out = {"settings": core_settings_for(core_cfg, case, metric=run["metric"]), "esl_run_id": run["id"],
           "frame_index": run["frame_index"], "support_node_ids": None}
    sup = cases_repo.get_support_set(conn, run["support_set_id"])
    out["support_node_ids"] = list(sup["node_ids"]) if sup else None
    if job_type == "EXPORT":
        out["targets"] = list(targets or [])
        vals = cases_repo.list_validations(conn, esl_run_id=run["id"])
        out["validation_verdict"] = vals[0]["verdict"] if vals else None
    return out
