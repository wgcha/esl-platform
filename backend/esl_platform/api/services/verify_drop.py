"""Radioss 검증 낙하(계약 esl_scx_relay.md 기능 B — SR-D-10~16, §7·§9.2) — 계획·생성·조회·[잡 ID 연결]/[포기]·파일.

경계: 백엔드는 가벼운 검사만(DB·DOE 결과 JSON·Case 입력 include 줄 스캔·폴더 목록). 패치·올리기·제출·폴링·회수는 워커
VERIFY_DROP(XFER, worker/esl_worker/scx_verify.py), 추출·비교는 VERIFY_POST(SLOT, verify_post.py). 어댑터 쓰기 호출(resolve 포함)은
scx_verify 모듈 하나만(정적 시험) — 여기서는 그 모듈 함수를 부른다.

씬 선택(SR-D-10, Q4): 대상 = 강성 평가 스터디 ① same·phase DONE, 안 = best/<did>/include 가 있는 안(순위 1~paicad.keep_files_top).
씬 = 스터디 ESL 항목의 출처 Case(같은 Case 의 ESL 이 여럿이면 r_c 최대 1개). r = 그 안의 ESL별 비(v0.10.0 §11.4):
r_c = C_{d,i}/C_{d000,i}, r_umax·r_epsmax = 같은 ESL 의 umax·epsmax 비(베이스라인 d000 result.json 대비).
mode worst = 제외되지 않은 씬을 r_c 큰 순(동률 entry_id 순)으로 N개, all = 제외되지 않은 씬 전부. 합계 ≤ verify_drop.max_scenes.
씬별 제외(오류 아님, excluded[]): VD_CASE_NOT_READY(추출 없음·최신 아님) → VD_CUMULATIVE_EXCLUDED(상태 파일 .sta/.str 또는 누적
추출) → VD_INCLUDE_LAYOUT(include 가 rad 폴더 밖·절대경로·못 찾음·include_path_map) → VD_ENGINE_MISSING → VD_ALREADY_ACTIVE.

쓰기: DB(verify_drops·jobs·scx_submissions)만. _verify/<id>/ 는 워커가 만든다. Case 입력·DOE 폴더는 읽기만.
"""

from __future__ import annotations

import copy
import json
import os
import statistics
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from ...core.auth import Principal
from ...core.config import bead_doe_settings
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.inputs import extract_stale
from ...core.paths import VERIFY_DIR, doe_dir, esl_subdir, verify_dir
from ...core.repositories import cases as cases_repo
from ...core.repositories import doe as doe_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ...core.repositories import verify as vd_repo
from ...core.repositories.cases import VersionConflict
from ...core.scx import messages
from ...core.scx import paths as scx_paths
from ...core.scx import status as scx_status
from ...core.scx.settings import engine_names, run_stem, scx_cfg
from ..context import AppContext
from .common import job_out, require_config_ok, require_execute

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
RESULT_FILES = ("stage.json", "compare.json", "compare.csv")
# 재시도 시작 step → 검증 phase(실패·취소 뒤 재시도로 비종료 phase 로 되돌림)
RETRY_PHASE = {"VERIFY_DROP": {1: "PREP", 2: "STAGING", 3: "STAGING", 4: "SUBMITTED", 5: "RUNNING"},
               "VERIFY_POST": {1: "POST", 2: "POST", 3: "POST", 4: "POST"}}


def vcfg(ctx: AppContext):
    return ctx.settings.verify_drop


def _view(principal: Principal, project_id: str) -> None:
    from .doe import require_view

    require_view(principal, project_id)


def _read_json(path: str, max_mb: float = 64) -> Any:
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > max_mb * 1024 * 1024:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- 원 Case 입력 세트(백엔드·워커 공용 — SR-D-13·14·15)
def core_case_cfg(core: dict[str, Any] | None) -> dict[str, Any]:
    c = (core or {}).get("case") or {}
    return {"rad_include_max_depth": int(c.get("rad_include_max_depth") or 8),
            "include_path_map": dict(c.get("include_path_map") or {}), "rad_max_line_kb": c.get("rad_max_line_kb")}


def input_set(settings, core: dict[str, Any] | None, case: dict[str, Any]) -> dict[str, Any]:
    """원 Case 입력 세트: {rad, rad_dir, files[(rel, 절대경로)], engines[이름], problems[(code, reason)]}.
    files = starter + include 폐포(rad 폴더 기준 상대 배치) + 엔진 rad. include 본문은 읽지 않는다(include 줄만)."""
    from esl_worker import core_adapter

    cc = core_case_cfg(core)
    rad = case["rad_path"]
    rdir = os.path.dirname(os.path.abspath(rad))
    rreal = os.path.realpath(rdir)
    probs: list[tuple[str, str]] = []
    files: list[tuple[str, str]] = [(os.path.basename(rad), rad)]
    if (case.get("extract_summary") or {}).get("cumulative"):
        probs.append(("VD_CUMULATIVE_EXCLUDED", messages.text("VD_CUMULATIVE_EXCLUDED") + "(누적 추출 Case)"))
    if cc["include_path_map"]:
        probs.append(("VD_INCLUDE_LAYOUT", messages.text("VD_INCLUDE_LAYOUT") + " — 설정 case.include_path_map 사용 중"))
    bad: list[str] = []
    state: list[str] = []
    try:
        refs = core_adapter.scan_include_refs(rad, cc["rad_include_max_depth"], cc["include_path_map"] or None)
    except core_adapter.CoreError as exc:
        refs = []
        probs.append(("VD_INCLUDE_LAYOUT", f"include 스캔 실패({exc.code})"))
    seen = {os.path.normcase(os.path.realpath(rad))}
    for ref in refs:
        spec = str(ref.get("spec") or "")
        sp = spec.replace("\\", "/")
        if core_adapter.is_state_include(spec, ref["path"] if ref.get("found") else None):
            state.append(os.path.basename(sp))
        if sp.startswith("/") or (len(sp) > 1 and sp[1] == ":"):
            bad.append(f"{os.path.basename(sp)}(절대경로)")
            continue
        if not ref.get("found"):
            bad.append(f"{os.path.basename(sp)}(없음)")
            continue
        real = os.path.realpath(ref["path"])
        if not (real == rreal or real.startswith(rreal + os.sep)):
            bad.append(f"{os.path.basename(sp)}(rad 폴더 밖)")
            continue
        key = os.path.normcase(real)
        if key in seen:
            continue
        seen.add(key)
        files.append((os.path.relpath(os.path.abspath(ref["path"]), rdir).replace(os.sep, "/"), ref["path"]))
    if state:
        probs.insert(0, ("VD_CUMULATIVE_EXCLUDED", messages.text("VD_CUMULATIVE_EXCLUDED") + f"(상태 파일 {', '.join(state[:5])})"))
    if bad:
        probs.append(("VD_INCLUDE_LAYOUT", messages.text("VD_INCLUDE_LAYOUT") + f": {', '.join(bad[:10])}"))
    stem = run_stem(os.path.basename(rad))
    engines: list[str] = []
    if stem is not None:
        try:
            names = sorted(n for n in os.listdir(rdir) if os.path.isfile(os.path.join(rdir, n)))
        except OSError:
            names = []
        engines = [n for n in engine_names(stem, names, list(settings.verify_drop.engine_globs))
                   if n.casefold() != os.path.basename(rad).casefold()]
    if not engines:
        probs.append(("VD_ENGINE_MISSING", messages.text("VD_ENGINE_MISSING")))
    for n in engines:
        files.append((n, os.path.join(rdir, n)))
    return {"rad": rad, "rad_dir": rdir, "files": files, "engines": engines, "problems": probs}


def extract_ready(settings, case: dict[str, Any]) -> bool:
    if not case.get("extract_summary") or extract_stale(case):
        return False
    try:
        d = esl_subdir(settings, case["folder_name"])
    except DomainError:
        return False
    return os.path.isfile(os.path.join(d, "01_extract", "model.npz"))


# ---------------------------------------------------------------- DOE 안·ESL별 비
def _design(ctx: AppContext, s: dict[str, Any], did: str) -> dict[str, Any]:
    """안 검사(Q2: best/<did>/include 가 있는 순위 1~keep_files_top) + ESL별 비 {entry_id: {r_c, r_umax, r_epsmax}}."""
    from .doe import _result_doc, cfg as doe_cfg

    c = doe_cfg(ctx)
    r = _result_doc(ctx, s, c)
    if not isinstance(r, dict):
        raise conflict("RESULT_NOT_READY", "DOE 실행 결과(post/result.json)가 없습니다")
    base = doe_dir(ctx.settings, s["id"])
    keep = int(bead_doe_settings(ctx.settings)["paicad"]["keep_files_top"])
    row = next((x for x in r.get("ranking") or [] if isinstance(x, dict) and x.get("id") == did), None)
    best_ids = {b.get("id") for b in r.get("best_all") or [] if isinstance(b, dict)}
    if isinstance(r.get("best"), dict):
        best_ids.add(r["best"].get("id"))
    inc = os.path.join(base, "best", did, "include")
    rels: list[str] = []
    if row is not None and os.path.isdir(inc) and not os.path.islink(inc):
        for root, dirs, names in os.walk(inc):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
            for n in sorted(names):
                p = os.path.join(root, n)
                if os.path.isfile(p) and not os.path.islink(p):
                    rels.append(os.path.relpath(p, inc).replace(os.sep, "/"))
    rank = int(row.get("rank") or 0) if row else 0
    if row is None or did not in best_ids or not rels or not 1 <= rank <= max(1, keep):
        raise unprocessable("VD_DESIGN_NO_FILES", messages.text("VD_DESIGN_NO_FILES"), design_id=did)
    per = row.get("per_esl")
    if not isinstance(per, list):
        pe = _read_json(os.path.join(base, "post", "per_esl.json")) or {}
        per = (pe.get("designs") or {}).get(did) or []
    b = _read_json(os.path.join(base, "run", "designs", "d000", "result.json")) or {}
    bper = {p.get("entry_id"): p for p in b.get("per_esl") or [] if isinstance(p, dict)}
    ratios: dict[str, dict[str, float | None]] = {}
    for p in per:
        if not isinstance(p, dict) or not p.get("entry_id"):
            continue
        bp = bper.get(p["entry_id"]) or {}

        def rr(k: str) -> float | None:
            try:
                v, w = float(p.get(k)), float(bp.get(k))
            except (TypeError, ValueError):
                return None
            return v / w if w > 0 else None

        rc = p.get("ratio")
        ratios[p["entry_id"]] = {"r_c": float(rc) if isinstance(rc, (int, float)) else None, "r_umax": rr("umax"),
                                 "r_epsmax": rr("epsmax")}
    return {"rank": rank, "ratios": ratios, "best_rel": f"best/{did}/include", "best_rels": rels}


# ---------------------------------------------------------------- 계획(POST /verify-drops/plan 과 생성 공용)
def _scene_label(e: dict[str, Any]) -> str:
    from .doe import _entry_label

    return _entry_label(e)


def _est_hours(conn, ctx: AppContext, project_id: str) -> float:
    hs = vd_repo.completed_hours(conn, project_id)
    return round(float(statistics.median(hs)), 2) if hs else float(vcfg(ctx).est_hours_per_scene)


def _plan(ctx: AppContext, conn, principal: Principal, body) -> dict[str, Any]:
    from .doe import _derived_phase

    s = doe_repo.get_study(conn, body.bead_doe_id)
    if s is None:
        raise not_found("DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다")
    _view(principal, s["project_id"])
    require_execute(principal, s["project_id"])
    if s["scenario"] != "same":
        raise unprocessable("VD_SCENARIO_UNSUPPORTED", messages.text("VD_SCENARIO_UNSUPPORTED"), scenario=s["scenario"])
    if _derived_phase(s, doe_repo.latest_job(conn, s["id"])) != "DONE":
        raise conflict("RESULT_NOT_READY", "DOE 실행 결과가 아직 없습니다")
    vc = vcfg(ctx)
    mx = int(vc.max_scenes)
    n = int(body.n if body.n is not None else vc.default_worst_n)
    if body.mode == "worst" and n > mx:
        raise unprocessable("VD_TOO_MANY_SCENES", messages.text("VD_TOO_MANY_SCENES") + f"(요청 {n} > {mx})", n=n, max_scenes=mx)
    dz = _design(ctx, s, body.design_id)
    core = copy.deepcopy(ctx.config.core or {})
    # 씬 후보 = 스터디 ESL 의 출처 Case(같은 Case 는 r_c 최대 1개)
    cands: dict[str, dict[str, Any]] = {}
    for eid in s["entry_ids"]:
        e = lib_repo.get_entry(conn, eid)
        if e is None or e["project_id"] != s["project_id"]:
            continue
        r = dz["ratios"].get(eid) or {"r_c": None, "r_umax": None, "r_epsmax": None}
        cur = cands.get(e["case_id"])
        key = (-(r["r_c"] if r["r_c"] is not None else float("-inf")), eid)
        if cur is None or key < cur["_key"]:
            cands[e["case_id"]] = {"entry_id": eid, "case_id": e["case_id"], "label": _scene_label(e), **r, "_key": key}
    order = sorted(cands.values(), key=lambda x: x["_key"])
    active = vd_repo.active_keys(conn, s["id"], body.design_id)
    scenes, excluded = [], []
    for c in order:
        case = cases_repo.get_case(conn, c["case_id"])
        title = case["title"] if case else None
        code = reason = None
        info = None
        if case is None or case["project_id"] != s["project_id"] or case.get("status") != "ACTIVE":
            code, reason = "VD_CASE_NOT_READY", "원 Case 가 없거나 보관됨"
        elif not extract_ready(ctx.settings, case):
            code, reason = "VD_CASE_NOT_READY", messages.text("VD_CASE_NOT_READY")
        else:
            info = input_set(ctx.settings, core, case)
            if info["problems"]:
                code, reason = info["problems"][0]
            elif c["case_id"] in active:
                code, reason = "VD_ALREADY_ACTIVE", messages.text("VD_ALREADY_ACTIVE")
        row = {k: c[k] for k in ("entry_id", "case_id", "label", "r_c", "r_umax", "r_epsmax")} | {"case_title": title}
        if code:
            excluded.append({"entry_id": c["entry_id"], "case_id": c["case_id"], "case_title": title, "code": code,
                             "reason": scx_mask(reason)})
        else:
            scenes.append({**row, "_case": case, "_info": info})
    if body.mode == "all" and len(scenes) > mx:
        raise unprocessable("VD_TOO_MANY_SCENES", messages.text("VD_TOO_MANY_SCENES") + f"(씬 {len(scenes)} > {mx})",
                            n=len(scenes), max_scenes=mx)
    if body.mode == "worst":
        scenes = scenes[:n]
    sc = scx_cfg(ctx.settings)
    return {"study": s, "design": dz, "scenes": scenes, "excluded": excluded, "core": core,
            "out": {"design_id": body.design_id, "mode": body.mode,
                    "scenes": [{k: v for k, v in x.items() if not k.startswith("_")} for x in scenes],
                    "excluded": excluded, "n_submit": len(scenes), "est_hours": _est_hours(conn, ctx, s["project_id"]),
                    "max_scenes": mx, "default_worst_n": int(vc.default_worst_n), "default_n": int(vc.default_worst_n),
                    "designs": _designs(ctx, s),
                    "hpc": {"version": getattr(sc, "version", None), "ncpu": getattr(sc, "ncpu", None)},
                    "hpc_default": {"version": getattr(sc, "version", None), "ncpu": getattr(sc, "ncpu", None)}}}


def _designs(ctx: AppContext, s: dict[str, Any]) -> list[dict[str, Any]]:
    """검증 가능한 안(best/<did>/include 가 남은 순위 1~keep_files_top) [{id, rank}] — 대화상자 안 선택."""
    out = []
    from .doe import _result_doc, cfg as doe_cfg

    r = _result_doc(ctx, s, doe_cfg(ctx)) or {}
    for row in r.get("ranking") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        try:
            dz = _design(ctx, s, str(row["id"]))
        except DomainError:
            continue
        out.append({"id": str(row["id"]), "rank": int(dz["rank"])})
    return sorted(out, key=lambda x: (x["rank"], x["id"]))


def scx_mask(text: Any) -> str:
    from ...core.scx.mask import mask_text

    return mask_text(text, 400)


def plan(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.connect() as conn:
        p = _plan(ctx, conn, principal, body)
    scx_status.require_verify(ctx.settings, p["study"]["project_id"])
    if not p["scenes"]:
        raise conflict("VD_NO_SCENES", messages.text("VD_NO_SCENES"), excluded=p["excluded"])
    return p["out"]


# ---------------------------------------------------------------- 생성
def _extract_snapshot(ctx: AppContext, conn, case: dict[str, Any]) -> dict[str, Any]:
    """원 Case 추출 작업 설정(같은 추출 TCL·설정 — SR-D-16): 코어 설정 스냅샷 + h3d hot_k·top_n."""
    from .jobs import core_settings_for

    es = case.get("extract_summary") or {}
    j = jobs_repo.get_job(conn, es["job_id"]) if es.get("job_id") else None
    p = (j or {}).get("params") or {}
    settings = p.get("settings") if isinstance(p.get("settings"), dict) else core_settings_for(ctx, case)
    h = p.get("h3d") or {}
    hot_k = int(h.get("hot_k") or (settings.get("extract") or {}).get("hot_k") or 200)
    top_n = int(h.get("top_n") or (settings.get("tstar") or {}).get("top_n_times") or 5)
    return {"settings": settings, "h3d": {"part": case["part_title"], "hot_k": hot_k, "top_n": top_n, "slim": False}}


def create(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.connect() as conn:
        pid = _plan(ctx, conn, principal, body)["study"]["project_id"]
    scx_status.require_verify(ctx.settings, pid)
    hpc = body.hpc.model_dump(exclude_none=True) if body.hpc is not None else {}
    with ctx.engine.begin() as conn:
        p = _plan(ctx, conn, principal, body)
        s, dz = p["study"], p["design"]
        if not p["scenes"]:
            raise conflict("VD_NO_SCENES", messages.text("VD_NO_SCENES"), excluded=p["excluded"])
        batch = str(uuid.uuid4())
        drops, excluded = [], list(p["excluded"])
        for sc in p["scenes"]:
            case, info = sc["_case"], sc["_info"]
            did = str(uuid.uuid4())
            verify_dir(ctx.settings, did)                   # 경로 안전성(실제 생성은 워커)
            title = (body.title or "").strip() or f"검증 낙하 {body.design_id} · {case['title']}"[:200]
            pred = {"r_c": sc["r_c"], "r_umax": sc["r_umax"], "r_epsmax": sc["r_epsmax"]}
            snap = _extract_snapshot(ctx, conn, case)
            params = {"verify_drop_id": did, "bead_doe_id": s["id"], "design_id": body.design_id, "case_id": case["id"],
                      "entry_id": sc["entry_id"], "input_fingerprint": case["input_fingerprint"],
                      "core_case": core_case_cfg(p["core"]), "best_rel": dz["best_rel"], "best_rels": dz["best_rels"],
                      "files": [list(x) for x in info["files"]], "hpc": hpc, **snap}
            try:
                with conn.begin_nested():
                    d = vd_repo.insert_drop(conn, id=did, batch_id=batch, project_id=s["project_id"], bead_doe_id=s["id"],
                                            design_id=body.design_id, case_id=case["id"], entry_id=sc["entry_id"],
                                            title=title, phase="PREP", params={"hpc": hpc, "mode": body.mode,
                                                                                "n": body.n, "rank": dz["rank"]},
                                            files=[], predicted=pred, dir_rel=f"{VERIFY_DIR}/{did}",
                                            created_by=principal.user_id, created_by_name=principal.display_name)
                    jobs_repo.insert_job(conn, case_id=None, verify_drop_id=did, project_id=s["project_id"],
                                         job_type="VERIFY_DROP", params=params, created_by=principal.user_id,
                                         created_by_name=principal.display_name)
            except IntegrityError:
                excluded.append({"entry_id": sc["entry_id"], "case_id": case["id"], "case_title": case["title"],
                                 "code": "VD_ALREADY_ACTIVE", "reason": messages.text("VD_ALREADY_ACTIVE")})
                continue
            drops.append(d)
        if not drops:
            raise conflict("VD_NO_SCENES", messages.text("VD_NO_SCENES"), excluded=excluded)
        return {"batch_id": batch, "drops": [drop_out(ctx, conn, d) for d in drops], "excluded": excluded}


# ---------------------------------------------------------------- 조회
def drop_out(ctx: AppContext, conn, d: dict[str, Any]) -> dict[str, Any]:
    case = cases_repo.get_case(conn, d["case_id"])
    sub = vd_repo.latest_submission(conn, d["id"])
    js = vd_repo.drop_jobs(conn, d["id"])
    files = d.get("files") or []
    res = d.get("result") if isinstance(d.get("result"), dict) else None
    return {**{k: d[k] for k in ("id", "batch_id", "project_id", "bead_doe_id", "design_id", "case_id", "entry_id", "title",
                                 "phase", "version", "scx_job_id", "scx_status", "predicted", "created_by_name",
                                 "created_at", "updated_at")},
            "case_title": case["title"] if case else None,
            "drive_dir_display": scx_paths.display(ctx.settings, d.get("drive_dir_rel")) if d.get("drive_dir_rel") else None,
            "submission": None if sub is None else {k: sub[k] for k in ("request_id", "state", "attempt", "error_code",
                                                                       "error_message")},
            "files_n": len(files), "files_bytes": sum(int(f.get("size") or 0) for f in files if isinstance(f, dict)),
            "result": None if res is None else {k: res.get(k) for k in ("rows", "hot", "warnings", "tstar")},
            "job_ids": [j["id"] for j in js], "job": job_out(conn, js[-1], with_steps=True) if js else None}


def _load(conn, did: str, *, for_update: bool = False) -> dict[str, Any]:
    d = vd_repo.get_drop(conn, did, for_update=for_update)
    if d is None:
        raise not_found("VD_NOT_FOUND", messages.text("VD_NOT_FOUND"))
    return d


def list_drops(ctx: AppContext, principal: Principal, bead_doe_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        s = doe_repo.get_study(conn, bead_doe_id)
        if s is None:
            raise not_found("DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다")
        _view(principal, s["project_id"])
        return [drop_out(ctx, conn, d) for d in vd_repo.list_drops(conn, bead_doe_id=bead_doe_id)]


def get_drop(ctx: AppContext, principal: Principal, did: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        d = _load(conn, did)
        _view(principal, d["project_id"])
        return drop_out(ctx, conn, d)


def result_file(ctx: AppContext, principal: Principal, did: str, name: str) -> str:
    """compare.csv·stage.json·compare.json·result/<out> — _verify/<id> 안 파일(링크·탈출 거부)."""
    with ctx.engine.connect() as conn:
        d = _load(conn, did)
        _view(principal, d["project_id"])
    base = verify_dir(ctx.settings, did)
    if name in RESULT_FILES:
        p = os.path.join(base, name)
    else:
        if not name or "/" in name or "\\" in name or name.startswith(".") or not name.casefold().endswith(".out"):
            raise not_found("NOT_FOUND", "파일이 없습니다")
        p = os.path.join(base, "result", name)
    real = os.path.realpath(p)
    if os.path.islink(p) or not real.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(p):
        if name == "compare.csv" or name == "compare.json":
            raise conflict("RESULT_NOT_READY", "비교 결과가 아직 없습니다")
        raise not_found("NOT_FOUND", "파일이 없습니다")
    return p


# ---------------------------------------------------------------- [잡 ID 연결]·[포기](SR-D-11)
def resolve(ctx: AppContext, principal: Principal, did: str, body) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.connect() as conn:
        d = _load(conn, did)
        _view(principal, d["project_id"])
        require_execute(principal, d["project_id"])
        if int(d["version"]) != int(body.version):
            raise conflict("VERSION_CONFLICT", "다른 곳에서 바뀌었습니다 — 새로 고친 뒤 다시 하세요", version=d["version"])
        sub = vd_repo.latest_submission(conn, did)
        if sub is None or sub["state"] != "UNKNOWN":
            raise conflict("VD_NOT_UNKNOWN", messages.text("VD_NOT_UNKNOWN"), state=None if sub is None else sub["state"])
        if body.action == "attach":                     # 화면 'link' 도 같은 뜻(스키마에서 attach 로 정규화)
            if not body.scx_job_id:
                raise unprocessable("INVALID_PARAMS", "잡 ID 연결에는 scx_job_id 가 필요합니다")
            if vd_repo.job_id_in_use(conn, body.scx_job_id, sub["request_id"]):
                raise conflict("SCX_JOB_ID_IN_USE", messages.text("SCX_JOB_ID_IN_USE"))
        busy = [j for j in vd_repo.drop_jobs(conn, did) if j["state"] not in TERMINAL]
        if busy:
            raise conflict("JOB_ACTIVE", "이 검증 낙하의 작업이 대기 중이거나 실행 중입니다", job_id=busy[0]["id"])
    gw, _h = scx_status.require_verify(ctx.settings, d["project_id"])
    from esl_worker import scx_verify

    out = scx_verify.resolve_submission(gw, sub["request_id"], body.action, body.scx_job_id)   # DomainError(404·409) 그대로
    with ctx.engine.begin() as conn:
        d = _load(conn, did, for_update=True)
        if int(d["version"]) != int(body.version):
            raise conflict("VERSION_CONFLICT", "다른 곳에서 바뀌었습니다 — 새로 고친 뒤 다시 하세요", version=d["version"])
        from sqlalchemy import func

        if body.action == "abandon":
            vd_repo.update_submission(conn, sub["request_id"], state="ABANDONED", resolved_at=func.now(),
                                      resolved_by=principal.user_id)
            d = vd_repo.update_drop(conn, did, scx_status=None)
            return drop_out(ctx, conn, d)
        job = (out or {}).get("job") or {}
        vd_repo.update_submission(conn, sub["request_id"], state="ATTACHED", scx_job_id=body.scx_job_id,
                                  resolved_at=func.now(), resolved_by=principal.user_id)
        last = vd_repo.latest_job(conn, did, "VERIFY_DROP")
        try:
            with conn.begin_nested():
                d = vd_repo.update_drop(conn, did, phase="SUBMITTED", scx_job_id=body.scx_job_id,
                                        scx_status=str(job.get("status") or "")[:64] or None)
                if last is not None:
                    jobs_repo.insert_job(conn, case_id=None, verify_drop_id=did, project_id=d["project_id"],
                                         job_type="VERIFY_DROP", params=dict(last["params"]), created_by=principal.user_id,
                                         created_by_name=principal.display_name, retry_of_job_id=last["id"],
                                         resume_from_step=4)          # VD_WAIT 부터(폴링)
        except IntegrityError:
            raise conflict("VD_ALREADY_ACTIVE", messages.text("VD_ALREADY_ACTIVE")) from None
        return drop_out(ctx, conn, vd_repo.get_drop(conn, did))


# ---------------------------------------------------------------- 재시도(POST /jobs/{id}/retry — jobs 서비스가 부름)
def retry_job(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    d = _load(conn, job["verify_drop_id"], for_update=True)
    start = jobs_repo.first_failed_step(conn, job["id"])
    if job["job_type"] == "VERIFY_DROP":
        sub = vd_repo.latest_submission(conn, d["id"])
        if sub is not None and sub["state"] == "UNKNOWN":
            raise conflict("SCX_SUBMISSION_UNKNOWN", messages.text("SCX_SUBMISSION_UNKNOWN"),
                           request_id=sub["request_id"])
    if job["failure_code"] == "INPUT_CHANGED":
        raise conflict("INPUT_CHANGED", "원 Case 입력이 바뀌었습니다 — 새로 검증 낙하를 요청하세요")
    try:
        with conn.begin_nested():
            if d["phase"] in vd_repo.DROP_TERMINAL:
                vd_repo.update_drop(conn, d["id"], phase=RETRY_PHASE[job["job_type"]].get(start, "PREP"))
            new = jobs_repo.insert_job(conn, case_id=None, verify_drop_id=d["id"], project_id=job["project_id"],
                                       job_type=job["job_type"], params=dict(job["params"]), created_by=principal.user_id,
                                       created_by_name=principal.display_name, retry_of_job_id=job["id"],
                                       resume_from_step=start if start > 1 else None)
    except (IntegrityError, VersionConflict):
        raise conflict("VD_ALREADY_ACTIVE", messages.text("VD_ALREADY_ACTIVE")) from None
    return job_out(conn, new, with_steps=True)


__all__ = ["plan", "create", "list_drops", "get_drop", "resolve", "result_file", "retry_job", "input_set", "extract_ready",
           "core_case_cfg", "drop_out"]
