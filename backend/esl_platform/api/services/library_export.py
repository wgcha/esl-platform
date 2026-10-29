"""라이브러리 다중 내보내기(계약 esl_menu_restructure.md §6, v0.10.0).

- ``POST /library/exports``: 선택 항목(1..library_export.max_entries) → 묶음(batch) 1개 = 서로 다른 Case 마다 EXPORT 작업 1개
  (``params.origin = "library"``, 같은 Case 항목은 한 작업의 ``items``). 새 job_type·migration 없음(MR-D-5) — Case 당 비종료
  EXPORT 1개 제약(``ux_jobs_case_type_active``)에 걸리면 전체 롤백 + 409 CASE_JOB_BUSY {case_ids}.
- 원본 = 라이브러리 항목 폴더(raw.npz·entry.json), 출력·로그 = ``<esl_root>/_exports/<batch_id>/``(Case 폴더 쓰기 없음, MR-D-6).
- ID 배정(Q3 B): ``per_model_sequential``(기본) = 같은 topo_sha256 항목을 선택 순서로 줄 세워 첫 항목만 시작 오프셋,
  나머지는 ``"after:<앞 entry_id>"``(워커가 앞 항목 export.json 의 id_next 로 이어 배정). ``independent`` = 전부 같은 시작.
- 조회 ``GET /library/exports/{batch_id}``: batch.json + 작업(같은 batch_id, Case 별 최신 — 재시도 포함) + 항목 폴더
  export.json 으로 상태 계산. 목록 ``GET /library/exports``: jobs(project_id·EXPORT·origin library, created_at desc)를
  batch_id 로 묶음(인덱스 ix_jobs_project_created). zip ``GET …/bundle``: manifest.json·README.txt·``<NN>_<label>/``.
- 응답에 서버 절대경로 없음(항목 dir_rel·라벨 상대경로만).
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from ...core.atomic import write_text_atomic
from ...core.auth import Principal
from ...core.config import is_within
from ...core.db.tables import jobs as jobs_t
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.paths import EXPORTS_DIR, esl_subdir
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ...core.repositories import row_dict
from ...core.state_machine import CANCELED, QUEUED, RUNNING, SUCCEEDED, TERMINAL
from ..context import AppContext
from .common import require_config_ok, require_execute, require_library_config

EXPORT_TARGETS = ("radioss_inc", "fem", "csv")      # 기존 Case EXPORT 대상(esl.pipeline.EXPORT_TARGETS)과 같은 3종
BATCH_JSON = "batch.json"
EXPORT_JSON = "export.json"                          # 코어 esl.export.from_entry.EXPORT_JSON
LABEL_MAX = 60
_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _require_view(principal: Principal, project_id: str) -> None:
    if principal.role(project_id) is None and not principal.is_global_admin:
        raise forbidden("이 프로젝트의 조회 권한이 없습니다")


def _label_text(e: dict[str, Any]) -> str:
    m = e.get("model") or {}
    sc = e.get("scene") or {}
    parts = [m.get("name"), sc.get("drop_class") or sc.get("drop_type"),
             f"S{sc['scene_no']}" if sc.get("scene_no") is not None else None, sc.get("orient")]
    txt = "_".join(_SAFE.sub("-", str(p)).strip("-") for p in parts if p not in (None, ""))
    txt = re.sub(r"_+", "_", txt).strip("_-")[:LABEL_MAX].rstrip("_-")
    return txt or "ESL"


def make_label(k: int, e: dict[str, Any]) -> str:
    """<NN>_<모델_씬(파일명 안전 문자, ≤ 60자)>_<entry_id 앞 8자>."""
    return f"{k + 1:02d}_{_label_text(e)}_{_SAFE.sub('', e['id'])[:8]}"


def batch_dir(ctx: AppContext, batch_id: str) -> str:
    return esl_subdir(ctx.settings, EXPORTS_DIR, batch_id)


def _bad_batch_id(batch_id: str) -> bool:
    try:
        return str(uuid.UUID(batch_id)) != batch_id
    except (ValueError, AttributeError, TypeError):
        return True


def _bundle_limit(ctx: AppContext) -> int:
    le = ctx.settings.library_export
    return int(le.max_bundle_bytes or ctx.settings.ui.max_bundle_bytes)


# ---------------------------------------------------------------- 생성
def plan_offsets(rows: list[dict[str, Any]], labels: list[str], start, policy: str) -> list[dict[str, Any]]:
    """항목별 {id_offset, after_label?}. per_model_sequential: 같은 topo_sha256 은 앞 항목 뒤로 이어서(topo 없으면 독립).

    줄 세우는 순서 = (Case 작업 순 = 그 Case 의 첫 선택 순, 선택 순). 작업은 이 순서로 큐에 들어가(LIGHT 레인 FIFO) 앞 항목이
    항상 같은 작업의 앞쪽이거나 먼저 큐에 든 작업에 있으므로 작업 간 대기가 서로 막히지 않는다(같은 Case 안은 선택 순 그대로)."""
    case_rank: dict[str, int] = {}
    for e in rows:
        case_rank.setdefault(e["case_id"], len(case_rank))
    order = sorted(range(len(rows)), key=lambda k: (case_rank[rows[k]["case_id"]], k))
    out: list[dict[str, Any]] = [{} for _ in rows]
    last: dict[str, tuple[str, str]] = {}
    for k in order:
        e, lab = rows[k], labels[k]
        topo = e.get("topo_sha256")
        if policy == "per_model_sequential" and topo and topo in last:
            pid, plab = last[topo]
            out[k] = {"id_offset": f"after:{pid}", "after_label": plab}
        else:
            out[k] = {"id_offset": start}
        if topo:
            last[topo] = (e["id"], lab)
    return out


def create_batch(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    from .library import backfill_opt_meta, eligibility, entry_folder

    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    require_library_config(ctx)
    lim = ctx.settings.library_export
    ids = list(body.entry_ids)
    if not ids:
        raise unprocessable("INVALID_PARAMS", "entry_ids 가 비었습니다")
    if len(set(ids)) != len(ids):
        raise unprocessable("INVALID_PARAMS", "entry_ids 에 중복이 있습니다")
    if not body.targets or any(t not in EXPORT_TARGETS for t in body.targets) or len(set(body.targets)) != len(body.targets):
        raise unprocessable("INVALID_PARAMS", f"targets 는 {list(EXPORT_TARGETS)} 중 1개 이상(중복 없음)",
                            targets=list(body.targets))
    if len(ids) > int(lim.max_entries):
        raise unprocessable("TOO_MANY_ENTRIES", f"한 번에 내보낼 수 있는 ESL 은 최대 {lim.max_entries}개입니다",
                            max=int(lim.max_entries))
    targets = [t for t in EXPORT_TARGETS if t in body.targets]
    opts = body.options.model_dump()
    core = ctx.config.core or {}
    ecfg = copy.deepcopy(core.get("export") or {})
    start = (ecfg.get("radioss") or {}).get("id_offset", "auto") if opts["id_offset"] == "auto" else int(opts["id_offset"])
    with ctx.engine.connect() as conn:
        rows = lib_repo.list_entries(conn, project_id=body.project_id, status="ACTIVE", ids=ids)
    by = {e["id"]: e for e in rows}
    miss = [i for i in ids if i not in by]
    if miss:
        raise unprocessable("ENTRY_NOT_FOUND", "이 프로젝트의 활성 라이브러리 항목이 아닙니다", entry_ids=miss)
    rows = backfill_opt_meta(ctx, [by[i] for i in ids])         # topo_sha256(같은 모델 판정) 지연 백필
    nofile = []
    for e in rows:
        d = entry_folder(ctx, e)
        if not all(os.path.isfile(os.path.join(d, n)) and not os.path.islink(os.path.join(d, n))
                   for n in ("raw.npz", "entry.json")):
            nofile.append(e["id"])
    if nofile:
        raise conflict("ENTRY_FILES_MISSING", "라이브러리 항목 폴더(raw.npz·entry.json)가 없습니다", entry_ids=nofile)
    labels = [make_label(k, e) for k, e in enumerate(rows)]
    offs = plan_offsets(rows, labels, start, opts["id_policy"])
    batch_id = str(uuid.uuid4())
    bdir = batch_dir(ctx, batch_id)
    items = []
    for e, lab, off in zip(rows, labels, offs):
        items.append({"entry_id": e["id"], "esl_run_id": e["esl_run_id"], "validation_id": e.get("validation_id"),
                      "dir_rel": e["dir_rel"], "label": lab, "case_id": e["case_id"],
                      "legacy": not eligibility(e.get("quality"))[0], "topo_sha256": e.get("topo_sha256"), **off})
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        groups.setdefault(it["case_id"], []).append(it)
    settings = {"export": ecfg, "units": copy.deepcopy(core.get("units") or {})}
    job_ids: list[str] = []
    with ctx.engine.begin() as conn:
        busy = [r[0] for r in conn.execute(select(jobs_t.c.case_id).where(and_(
            jobs_t.c.case_id.in_(list(groups)), jobs_t.c.job_type == "EXPORT",
            jobs_t.c.state.notin_(list(TERMINAL))))).all()]
        if busy:
            raise conflict("CASE_JOB_BUSY", "같은 Case 의 내보내기 작업이 대기 중이거나 실행 중입니다 — 잠시 후 다시 시도하세요",
                           case_ids=sorted(set(busy)))
        for cid, its in groups.items():
            params = {"origin": "library", "batch_id": batch_id, "targets": targets, "options": opts,
                      "items": [{k: it[k] for k in ("entry_id", "esl_run_id", "validation_id", "dir_rel", "label",
                                                     "id_offset") if k in it}
                                | ({"after_label": it["after_label"]} if it.get("after_label") else {})
                                for it in its],
                      "settings": settings}
            try:
                with conn.begin_nested():
                    j = jobs_repo.insert_job(conn, case_id=cid, project_id=body.project_id, job_type="EXPORT",
                                             params=params, created_by=principal.user_id,
                                             created_by_name=principal.display_name)
            except IntegrityError:
                raise conflict("CASE_JOB_BUSY", "같은 Case 의 내보내기 작업이 대기 중이거나 실행 중입니다 — 잠시 후 다시 "
                               "시도하세요", case_ids=[cid]) from None
            job_ids.append(j["id"])
        doc = {"batch_id": batch_id, "project_id": body.project_id, "created_by": principal.user_id,
               "created_by_name": principal.display_name, "created_at": _now_iso(), "entry_ids": ids,
               "labels": labels, "targets": targets, "options": opts, "job_ids": job_ids,
               "items": [{k: it.get(k) for k in ("entry_id", "label", "case_id", "esl_run_id", "validation_id",
                                                   "legacy", "topo_sha256", "id_offset", "after_label")} for it in items]}
        os.makedirs(bdir, exist_ok=True)
        write_text_atomic(os.path.join(bdir, BATCH_JSON), json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    return get_batch(ctx, principal, batch_id)


# ---------------------------------------------------------------- 조회
def _read_batch(ctx: AppContext, batch_id: str) -> tuple[dict[str, Any], str]:
    if _bad_batch_id(batch_id):
        raise not_found("EXPORT_NOT_FOUND", "내보내기 묶음을 찾을 수 없습니다")
    bdir = batch_dir(ctx, batch_id)
    p = os.path.join(bdir, BATCH_JSON)
    try:
        if os.path.islink(p):
            raise OSError("link")
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        raise not_found("EXPORT_NOT_FOUND", "내보내기 묶음을 찾을 수 없습니다") from None
    return doc, bdir


def _batch_jobs(conn, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """같은 batch_id 작업(재시도 포함) → Case 별 최신 1개, 묶음의 Case 순서(= 큐에 넣은 순서)."""
    rows = [row_dict(r) for r in conn.execute(select(jobs_t).where(and_(
        jobs_t.c.project_id == doc["project_id"], jobs_t.c.job_type == "EXPORT",
        jobs_t.c.params["origin"].astext == "library",
        jobs_t.c.params["batch_id"].astext == doc["batch_id"])).order_by(jobs_t.c.created_at, jobs_t.c.queue_seq)).all()]
    latest: dict[str, dict[str, Any]] = {}
    for j in rows:
        latest[j["case_id"]] = j
    rank: dict[str, int] = {}
    for it in doc.get("items") or []:
        rank.setdefault(it.get("case_id"), len(rank))
    return sorted(latest.values(), key=lambda j: rank.get(j["case_id"], len(rank)))


def _item_record(bdir: str, label: str) -> dict[str, Any] | None:
    p = os.path.join(bdir, label, EXPORT_JSON)
    try:
        if os.path.islink(p) or not is_within(os.path.realpath(p), os.path.realpath(bdir)):
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _item_files(bdir: str, label: str, names: list[str]) -> list[tuple[str, str, int]]:
    """(절대경로, 묶음 기준 '/' 상대경로, 크기) — 심링크·탈출·이상한 이름 제외."""
    out = []
    real = os.path.realpath(bdir)
    for n in names or []:
        if not isinstance(n, str) or "/" in n or "\\" in n or n in ("", ".", ".."):
            continue
        p = os.path.join(bdir, label, n)
        if os.path.islink(p) or not os.path.isfile(p) or not is_within(os.path.realpath(p), real):
            continue
        out.append((p, f"{label}/{n}", os.path.getsize(p)))
    return out


def _state(jobs: list[dict[str, Any]], n_done: int, n_items: int) -> str:
    if not jobs:
        return "FAILED"
    if all(j["state"] in TERMINAL for j in jobs):
        if any(j["state"] == CANCELED for j in jobs):
            return "CANCELED"
        if all(j["state"] == SUCCEEDED for j in jobs) and n_done == n_items:
            return "SUCCEEDED"
        return "PARTIAL" if n_done > 0 else "FAILED"
    return RUNNING if any(j["state"] == RUNNING for j in jobs) else QUEUED


def batch_out(ctx: AppContext, conn, doc: dict[str, Any], bdir: str) -> dict[str, Any]:
    jobs = _batch_jobs(conn, doc)
    job_by_case = {j["case_id"]: j for j in jobs}
    items, n_done, size = [], 0, 0
    for it in doc.get("items") or []:
        rec = _item_record(bdir, it["label"])
        job = job_by_case.get(it.get("case_id"))
        st, files, err, rng, warns = "PENDING", [], None, None, []
        if rec is not None:
            if rec.get("ok"):
                st = "DONE"
                fl = _item_files(bdir, it["label"], rec.get("files") or [])
                files = [{"rel": rel, "size": sz} for _, rel, sz in fl]
                size += sum(sz for _, _, sz in fl)
                n_done += 1
            else:
                st, err = "FAILED", rec.get("error")
            rng, warns = rec.get("id_range"), [str(w) for w in rec.get("warnings") or []]
        elif job is None or job["state"] in TERMINAL:
            st = "FAILED"
            err = {"code": (job or {}).get("failure_code") or "EXPORT_NOT_RUN",
                   "message": (job or {}).get("failure_message") or "내보내기가 실행되지 않았습니다"}
        items.append({"entry_id": it["entry_id"], "label": it["label"], "case_id": it.get("case_id"),
                      "legacy": bool(it.get("legacy")), "state": st, "files": files, "id_range": rng,
                      "warnings": warns, "error": err})
    state = _state(jobs, n_done, len(items))
    ready = bool(jobs) and all(j["state"] in TERMINAL for j in jobs) and n_done > 0
    return {"batch_id": doc["batch_id"], "project_id": doc["project_id"], "created_by": doc.get("created_by") or "",
            "created_by_name": doc.get("created_by_name"), "created_at": doc.get("created_at"),
            "targets": list(doc.get("targets") or []), "options": dict(doc.get("options") or {}), "state": state,
            "jobs": [{"job_id": j["id"], "case_id": j["case_id"], "state": j["state"],
                      "progress_pct": j.get("progress_pct"), "failure_code": j.get("failure_code"),
                      "failure_message": j.get("failure_message")} for j in jobs],
            "items": items, "bundle": {"ready": ready, "bytes": size if ready else None}}


def get_batch(ctx: AppContext, principal: Principal, batch_id: str) -> dict[str, Any]:
    doc, bdir = _read_batch(ctx, batch_id)
    _require_view(principal, doc["project_id"])
    with ctx.engine.connect() as conn:
        return batch_out(ctx, conn, doc, bdir)


def list_batches(ctx: AppContext, principal: Principal, project_id: str, limit: int) -> list[dict[str, Any]]:
    _require_view(principal, project_id)
    limit = max(1, min(int(limit), 100))
    scan = min(5000, limit * int(ctx.settings.library_export.max_entries))
    with ctx.engine.connect() as conn:
        rows = [row_dict(r) for r in conn.execute(select(jobs_t).where(and_(
            jobs_t.c.project_id == project_id, jobs_t.c.job_type == "EXPORT",
            jobs_t.c.params["origin"].astext == "library")).order_by(jobs_t.c.created_at.desc()).limit(scan)).all()]
        order: list[str] = []
        for j in rows:
            b = str((j.get("params") or {}).get("batch_id") or "")
            if b and b not in order:
                order.append(b)
        out = []
        for b in order[:limit]:
            try:
                doc, bdir = _read_batch(ctx, b)
            except DomainError:
                continue
            o = batch_out(ctx, conn, doc, bdir)
            js = [j for j in rows if (j.get("params") or {}).get("batch_id") == b]
            out.append({"batch_id": b, "project_id": project_id, "created_by": o["created_by"],
                        "created_by_name": o["created_by_name"], "created_at": min(j["created_at"] for j in js),
                        "targets": o["targets"], "n_items": len(o["items"]), "state": o["state"],
                        "job_ids": [j["job_id"] for j in o["jobs"]]})
        return out


# ---------------------------------------------------------------- zip
README_KO = """ESL 내보내기 묶음 (라이브러리)

폴더 구조
  manifest.json            묶음 요약 + 항목별 정보(entry_id, 라벨, Case, ESL 결과, 판정 상태, 생성 ID 범위, 파일, 경고)
  README.txt               이 파일
  <NN>_<라벨>/             선택 순서 NN 의 ESL 1개
    esl_cload.inc          Radioss /FUNCT·/GRNOD·/CLOAD (등가정적하중)
    esl_bcs.inc            Radioss /GRNOD·/BCS (3-2-1 정정 지지)
    esl_force.fem          OptiStruct 자유형식 덱(GRID·요소·PSHELL·MAT1·FORCE·SPC1)
    f_eq.csv · u_rel.csv · supports_321.csv [· reactions_321.csv · validation.csv]

ID 배정
  {id_policy}

판정 표시
  manifest.json 의 legacy = true 는 현재 판정 기준(변위 기준) PASS 가 아닌 항목(LEGACY 또는 이전 사유 등록 FAIL·판정 불가)입니다.
  하중 자체는 등록 당시 그대로이며 판정 체계만 다릅니다 — 라이브러리에서 [재검증] 후 사용을 권장합니다.
  u_rel.csv 의 *_total 열은 라이브러리 항목에 없어 비어 있습니다(Case 결과 zip 참고).
"""
POLICY_KO = {"per_model_sequential": "같은 모델(같은 메시 위상) ESL 은 생성 ID 가 겹치지 않도록 이어서 배정했습니다 "
                                     "(순서 = Case 작업 순서(각 Case 의 첫 선택 순) → 그 안의 선택 순서, manifest.json id_range 참고). "
                                     "다른 모델은 각자 시작 ID 부터 배정합니다.",
             "independent": "모든 ESL 을 같은 시작 ID 부터 배정했습니다(서로 다른 덱에서 따로 쓸 때)."}


def bundle(ctx: AppContext, principal: Principal, batch_id: str) -> dict[str, Any]:
    doc, bdir = _read_batch(ctx, batch_id)
    _require_view(principal, doc["project_id"])
    with ctx.engine.connect() as conn:
        o = batch_out(ctx, conn, doc, bdir)
        ents = {e["id"]: e for e in lib_repo.list_entries(conn, ids=[i["entry_id"] for i in o["items"]])}
    if not o["jobs"] or any(j["state"] not in TERMINAL for j in o["jobs"]):
        raise conflict("EXPORT_NOT_READY", "내보내기가 아직 진행 중입니다")
    done = [it for it in o["items"] if it["state"] == "DONE"]
    if not done:
        raise conflict("EXPORT_FAILED", "성공한 항목이 없어 받을 파일이 없습니다")
    files: list[tuple[str, str]] = []
    for it in done:
        rec = _item_record(bdir, it["label"]) or {}
        files += [(p, rel) for p, rel, _ in _item_files(bdir, it["label"], rec.get("files") or [])]
    total = sum(os.path.getsize(p) for p, _ in files)
    limit = _bundle_limit(ctx)
    if total > limit:
        raise DomainError("BUNDLE_TOO_LARGE", f"받을 파일이 상한({limit} B)보다 큽니다 — 폴더를 직접 여세요: {bdir}",
                          status=413, path=bdir, size=total, limit=limit)
    by_label = {i["label"]: i for i in doc.get("items") or []}
    man_items = []
    for it in o["items"]:
        e = ents.get(it["entry_id"]) or {}
        q = e.get("quality") or {}
        man_items.append({"entry_id": it["entry_id"], "label": it["label"], "case_id": it["case_id"],
                          "esl_run_id": (by_label.get(it["label"]) or {}).get("esl_run_id"),
                          "validation": {"status": q.get("status") or ("LEGACY" if not q.get("scheme") else q.get("verdict")),
                                         "verdict": q.get("verdict"), "scheme": q.get("scheme")},
                          "legacy": it["legacy"], "state": it["state"], "id_range": it["id_range"],
                          "files": [f["rel"] for f in it["files"]], "warnings": it["warnings"], "error": it["error"]})
    manifest = {"batch_id": doc["batch_id"], "project_id": doc["project_id"], "created_by_name": doc.get("created_by_name"),
                "created_at": doc.get("created_at"), "targets": o["targets"], "options": o["options"],
                "state": o["state"], "items": man_items}
    mp, rp = os.path.join(bdir, "manifest.json"), os.path.join(bdir, "README.txt")
    write_text_atomic(mp, json.dumps(manifest, ensure_ascii=False, indent=1, default=str))
    write_text_atomic(rp, README_KO.format(id_policy=POLICY_KO.get(o["options"].get("id_policy"), "")))
    files = [(mp, "manifest.json"), (rp, "README.txt")] + files
    try:
        ts = _dt.datetime.fromisoformat(str(doc.get("created_at"))).strftime("%Y%m%d-%H%M")
    except ValueError:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M")
    return {"files": files, "prefix": "", "filename": f"esl_export_{ts}_{len(done)}.zip",
            "size": sum(os.path.getsize(p) for p, _ in files)}
