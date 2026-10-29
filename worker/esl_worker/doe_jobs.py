"""비드 형상 DOE 작업 실행(계약 esl_bead_doe.md §4·§6·§9) — executor 가 DOE_PREP·DOE_PREVIEW·DOE_RUN step 마다 ``run_step``.

- 작업 폴더 ``<esl_root>/_doe/<bead_doe_id>/``(대상 = jobs.bead_doe_id). 로그 ``logs/<job_id>/step_NN_<KEY>.log``.
- 코어 단계(bd_input·bd_mesh0·bd_loads·bd_matrix·bd_eval(베이스라인)·bd_post) = 코어 자식 프로세스(spawn,
  core_adapter.run_doe_stage → esl.doe.stages.run_stage). 단계 반환(경고·정보)은 ``<로그>.stage.json`` → 작업 경고.
  BD_MESH0 이 ③ 아님(skipped) → step SKIPPED.
- BD_GEOM(LOCAL): paicad version(BD-D-19 — 낮음·OCP 없음 → 작업 실패) → [②③ A Case fixed-scan → prep/a_fixed/(실패는
  정보만 — 코어가 A_FASTENERS_UNKNOWN)] → [①② fixed-scan(조립) → prep/fixed/] → [①② extract 1차(조립 없이) → prep/extract0/
  → prep/body_map.json] → extract → prep/extract/ → [①② tag → prep/tag/]. 진행률 = 명령별 균등 × PAICAD PROGRESS.
  ① 조립 = 기준 Case 입력 폴더 **제자리**(읽기만, 링크·4096 MB 상한 = scenario.assem_dir_check), ② = input/mesh 사본.
- BD_GRID(LOCAL): ``shell view grid``. 셀 = doe/<rev>/cells.json + 공칭 셀 ``nominal``(values {}) → doe/<rev>/grid_cells.json
  — paicad 0.14.0 grid 는 공칭 썸네일을 따로 만들지 않으므로(grid_manifest.nominal = {bbox, view_sha256}) 공칭을 셀로
  넣어 ``grid/cells/nominal/thumb.png`` 를 얻는다(백엔드 d000 썸네일 탐색 순서에 있는 경로). ③ ``--fixed-dir ""``.
- BD_DESIGNS(LOCAL+INTERNAL): 미리보기 READY 안(+ ③ 잡음 바닥 ``noise`` = 공칭 값 update 왕복)을 id 순으로 스레드 풀
  (``evaluate.parallel_limit`` = run.parallel(기본 2) × 메모리 자동 축소). 안 1개 = [done.json 이 같은 input_sha256 이면
  재사용(paicad·해석 생략)] → paicad(①② ``shell run`` → run/designs/<id>/paicad/{update,morph,check,out_files} /
  ③ ``shell update`` → run/designs/<id>/update/) → 코어 자식 ``bd_eval``(paicad={ok,status,code,…}). 미리보기 스킵 안은
  실행하지 않는다(bd_post 가 미리보기 상태로 표시). 취소·lease 상실 → 모든 paicad·코어 자식 트리 종료, 끝난 안 유지.
- BD_POST = 코어 bd_post(순위·view3d·산출물·보고서·대형 rad 사본 정리 — 상위 keep_files_top + 베이스라인 유지).
- 등록 BD_PREP_REGISTER·BD_PREVIEW_REGISTER·BD_REGISTER = register.register_doe_*(bead_does phase·요약). 실패 시 phase 불변.
- 작업 진행률 = step 가중 ``DOE_STEP_WEIGHTS``(PREP 10·5·60·20·5, PREVIEW 5·90·5, RUN 5·85·9·1) × step 진행률.
- 쓰기는 ``_doe/<id>/`` 아래만(코어 Writer 입력 목록 = 항목·Case 입력·업로드 거부), 작은 JSON 은 core/atomic.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from esl_platform.core.atomic import write_text_atomic
from esl_platform.core.db.tables import jobs as jobs_t
from esl_platform.core.errors import DomainError
from esl_platform.core.job_types import DOE_STEP_WEIGHTS
from esl_platform.core.paths import check_input_path, doe_dir, esl_subdir
from esl_platform.core.repositories import cases as cases_repo
from esl_platform.core.repositories import doe as doe_repo
from esl_platform.core.repositories import jobs as jobs_repo
from sqlalchemy import and_, update

from . import core_adapter, paicad_proc

BASELINE = "d000"
NOISE = "noise"
NOMINAL_CELL = "nominal"
MAX_JSON_MB = 64


class PrepareFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------- 준비
def prepare(ex) -> tuple[str, dict[str, Any]]:
    """작업 폴더(_doe/<id>, 링크·탈출 검사) + spec["lib"] = {doe, kind, job_id}. 항목 폴더 존재·라이브러리 안 확인
    (STEP 업로드는 BD_INPUT 이 sha256 대조 후 input/step 으로 복사 — 이후 step 은 그 사본만 쓴다)."""
    s = ex.settings
    job = ex.job
    p = job["params"] or {}
    sid = job.get("bead_doe_id")
    if not sid or p.get("bead_doe_id") not in (None, sid) or not isinstance(p.get("doe"), dict):
        raise PrepareFailed("INPUT_INVALID", "작업 params 가 이 강성 평가 스터디의 것이 아닙니다")
    doe = dict(p["doe"])
    if doe.get("id") not in (None, sid):
        raise PrepareFailed("INPUT_INVALID", "작업 params.doe.id 가 연구 id 와 다릅니다")
    try:
        cdir = doe_dir(s, sid)
        if p.get("out_rel") and p["out_rel"] != f"_doe/{sid}":
            raise PrepareFailed("PATH_UNSAFE", "작업 params.out_rel 이 연구 폴더가 아닙니다")
        lib_root = esl_subdir(s, "_library")
        os.makedirs(cdir, exist_ok=True)
        for e in doe.get("entries") or []:
            if not os.path.isfile(os.path.join(e["dir"], "entry.json")):
                raise PrepareFailed("PREREQUISITE_MISSING", f"라이브러리 항목 폴더가 없습니다: {e['id']}")
            if not paicad_proc._within(os.path.realpath(e["dir"]), os.path.realpath(lib_root)):
                raise PrepareFailed("PATH_UNSAFE", "라이브러리 항목 폴더가 라이브러리 밖입니다")
        if not doe.get("entries"):
            raise PrepareFailed("INPUT_INVALID", "DOE 에 넣을 ESL 이 없습니다")
    except DomainError as exc:
        raise PrepareFailed(exc.code, exc.message) from None
    with ex.engine.connect() as conn:
        if doe_repo.get_study(conn, sid) is None:
            raise PrepareFailed("DOE_NOT_FOUND", "강성 평가 스터디 행이 없습니다")
    lib = {"doe": doe, "kind": p.get("kind"), "job_id": job["id"], "study_id": sid}
    return cdir, lib


# ---------------------------------------------------------------- 진행률
def job_progress(job_type: str, step_key: str, pct: float) -> float:
    done = 0.0
    for k, w in DOE_STEP_WEIGHTS[job_type].items():
        if k == step_key:
            return round(done + w * max(0.0, min(100.0, pct)) / 100.0, 2)
        done += w
    return done


def mark_job_progress(conn, ex, step_key: str, pct: float) -> None:
    conn.execute(update(jobs_t).where(and_(jobs_t.c.id == ex.job["id"], jobs_t.c.lease_token == ex.token))
                 .values(progress_pct=job_progress(ex.job["job_type"], step_key, pct)))


def set_progress(ex, st: dict[str, Any], pct: float, **step_values: Any) -> None:
    with ex._tx() as conn:
        jobs_repo.step_update(conn, ex.job["id"], ex.token, st["step_no"], progress_pct=float(pct), **step_values)
        mark_job_progress(conn, ex, st["step_key"], pct)


class _Progress:
    """단조 증가 정수 % 만 DB 에 쓴다."""

    def __init__(self, ex, st: dict[str, Any]) -> None:
        self.ex, self.st, self.shown = ex, st, -1

    def __call__(self, pct: float) -> None:
        v = int(max(0.0, min(100.0, pct)))
        if v > self.shown:
            self.shown = v
            set_progress(self.ex, self.st, float(v))


# ---------------------------------------------------------------- 공통
def _echo_fn(log_path: str):
    lock = threading.Lock()

    def echo(msg: str) -> None:
        with lock:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
    return echo


def _read_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.islink(path) or os.path.getsize(path) > MAX_JSON_MB * 1024 * 1024:
            return default
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1))


def _cfg(ex) -> tuple[dict, dict]:
    full = ex.lib["doe"].get("cfg") or {}
    return full, core_adapter.doe_settings(full)


def _in_roots(ex) -> list[str]:
    st = ex.settings.storage
    roots = list(st.input_roots)
    up = getattr(st, "upload_root", None)
    if up:
        roots.append(up)
    return roots


def _stage_warnings(ex, key: str, log_path: str) -> dict[str, Any]:
    out = _read_json(core_adapter.stage_out_path(log_path), {}) or {}
    items = [f"[{key}] {str(w)[:300]}" for w in out.get("warnings") or []]
    items += [f"[{key}] 정보 {str(w)[:300]}" for w in out.get("info") or []]
    if items:
        with ex._tx() as conn:
            jobs_repo.add_warnings(conn, ex.job["id"], ex.token, items)
    return out


def _fail(code: str, message: str, exit_code: int | None = None):
    from .executor import _StepFailed

    return _StepFailed(code, message[:480], exit_code)


def _paicad_fail(r: dict[str, Any], what: str):
    detail = f" — {r['detail']}" if r.get("detail") else ""
    msg = (f"{r.get('message') or r.get('code')} ({what}: paicad {r.get('paicad_code') or '-'}, 종료 "
           f"{'시간 초과' if r.get('timeout') else r.get('exit_code')}){detail}")
    return _fail(r.get("code") or "PAICAD_FAILED", msg, r.get("exit_code"))


def _tick(ex):
    state = {"renew": time.monotonic(), "cancel": time.monotonic()}
    return lambda: ex._wait_tick(state)


def _paicad(ex, st, key: str, values: dict[str, Any], *, cwd: str, capture: str, report: str | None, stage: str,
            echo, progress=None, tick=None, procs=None, relay: bool = True, label: str = "") -> dict[str, Any]:
    full, _ = _cfg(ex)

    def on_start(argv, pid):
        echo(f"[esl-worker] {label or key} argv: " + json.dumps(argv, ensure_ascii=False))
        if st is not None and procs is None:
            with ex._tx() as conn:
                jobs_repo.step_update(conn, ex.job["id"], ex.token, st["step_no"], command=argv)

    try:
        r = paicad_proc.run(key, dict(values), settings=ex.settings, cfg=full, out_root=ex.cdir, in_roots=_in_roots(ex),
                            cwd=cwd, capture=capture, report=report, stage=stage, lim=ex.lim, procs=procs, tick=tick,
                            on_progress=progress, on_line=(lambda ln: echo(f"  {label}{ln}")) if relay else None,
                            on_start=on_start)
    except paicad_proc.PaicadError as exc:
        raise _fail(exc.code, exc.message) from None
    echo(f"[esl-worker] {label or key}: 종료 {'시간 초과' if r['timeout'] else r['exit_code']} ({r['seconds']:.1f} s) — "
         + ("성공" if r["ok"] else f"실패 {r['code']} (paicad {r.get('paicad_code') or '-'})"))
    return r


def _rel(p: str) -> str:
    return p.replace(os.sep, "/")


# ---------------------------------------------------------------- step 실행
def run_step(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    key = st["step_key"]
    if st["core_stage"]:
        set_progress(ex, st, 0.0)
        ex.lib.pop("extra", None)
        if key == "BD_BASELINE":
            ex.lib["extra"] = {"design": BASELINE}
        try:
            ex._run_core(st, log_path)
        finally:
            ex.lib.pop("extra", None)
        out = _stage_warnings(ex, key, log_path)
        with ex._tx() as conn:
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {st["core_stage"]: _summary(out)})
        res = {"core_stage": st["core_stage"]}
        if out.get("skipped"):
            res["_skipped"] = True
            res["skipped"] = "③ 이 아님 — 기준 메시 gmsh 없음"
        return res
    if key == "BD_GEOM":
        return _geom(ex, st, log_path)
    if key == "BD_GRID":
        return _grid(ex, st, log_path)
    if key == "BD_DESIGNS":
        return _designs(ex, st, log_path)
    if key in ("BD_PREP_REGISTER", "BD_PREVIEW_REGISTER", "BD_REGISTER"):
        from . import register

        fn = {"BD_PREP_REGISTER": register.register_doe_prep, "BD_PREVIEW_REGISTER": register.register_doe_preview,
              "BD_REGISTER": register.register_doe_run}[key]
        with ex._tx() as conn:
            jobs_repo.assert_lease(conn, ex.job["id"], ex.token)
            try:
                res = fn(conn, ex.job, None, ex.cdir)
            except register.RegisterError as exc:
                raise _fail(exc.code, exc.message) from None
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"registered": _jsonable(res)})
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[esl-worker] {key}: bead_does 등록 완료 (phase {res.get('phase')})\n")
        return {"registered": True}
    raise _fail("INTERNAL_ERROR", f"알 수 없는 강성 평가 스터디 step: {key}")


def _summary(out: dict[str, Any]) -> dict[str, Any]:
    keep = ("matrix_sha256", "n_designs", "n_beads", "n_params", "boundary", "part_id", "status", "design", "h",
            "skipped")
    s = {k: out.get(k) for k in keep if k in out}
    r = out.get("result")
    if isinstance(r, dict):
        s.update({k: r.get(k) for k in ("n_ok", "n_skipped", "n_failed", "noise_floor", "cleanup_bytes")})
        s["best"] = (r.get("best") or {}).get("id")
    return _jsonable(s)


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


# ---------------------------------------------------------------- BD_GEOM
def _a_case(ex, echo) -> dict[str, Any] | None:
    """②③ A(첫 ESL)의 Case 입력 → {case_dir, part_id} 또는 None(정보만 — 코어가 A_FASTENERS_UNKNOWN)."""
    doe = ex.lib["doe"]
    e0 = (doe.get("entries") or [{}])[0]
    cid = e0.get("case")
    if not cid:
        echo("[esl-worker] A Case 없음 — A 체결점은 3-2-1 만(A_FASTENERS_UNKNOWN)")
        return None
    _, dcfg = _cfg(ex)
    try:
        with ex.engine.connect() as conn:
            case = cases_repo.get_case(conn, cid)
        if case is None or not case.get("rad_path"):
            raise DomainError("PREREQUISITE_MISSING", "Case 입력 rad 없음")
        rad = check_input_path(ex.settings, case["rad_path"], "RAD")
        d = os.path.dirname(rad)
        core_adapter.doe_assem_check(d, float(dcfg["same"]["max_assem_mb"]))
        meta = _read_json(os.path.join(e0["dir"], "entry.json"), {}) or {}
        pid = (meta.get("model") or {}).get("part_id")
        if pid is None:
            cc = ((doe.get("core") or {}).get("case")) or {}
            parts = core_adapter.list_parts(rad, int(cc.get("rad_include_max_depth") or 8), cc.get("include_path_map"))
            want = str(case.get("part_title") or "").strip().casefold()
            hit = [p for p in parts if str(p.get("title") or "").strip().casefold() == want]
            if len(hit) != 1:
                raise DomainError("PART_NOT_FOUND", f"A Case 에서 파트 '{case.get('part_title')}' 를 하나로 찾지 못함")
            pid = hit[0]["id"]
        return {"case_dir": d, "part_id": int(pid)}
    except (DomainError, core_adapter.CoreError) as exc:
        echo(f"[esl-worker] A Case 체결점 조사 생략({exc.code}: {exc.message}) — A_FASTENERS_UNKNOWN")
        return None


def _geom(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    echo = _echo_fn(log_path)
    doe = ex.lib["doe"]
    full, dcfg = _cfg(ex)
    scn = doe["scenario"]
    out = ex.cdir
    prog = _Progress(ex, st)
    prog(0)
    tick = _tick(ex)
    pc = dcfg["paicad"]
    inp = _read_json(os.path.join(out, "prep", "input.json"))
    if not isinstance(inp, dict):
        raise _fail("PREREQUISITE_MISSING", "prep/input.json 이 없습니다 — BD_INPUT 부터 다시")
    # 1) 버전(BD-D-19)
    v = paicad_proc.version_check(ex.settings, full)
    echo(f"[esl-worker] paicad version: {v.get('version')} (OCP {v.get('ocp')}, 고정 {v.get('pinned')})"
         + (f" — {v['warning']}" if v.get("warning") else ""))
    if not v.get("ready"):
        msgs = core_adapter.doe_messages().get("messages") or {}
        code = v.get("reason") or "PAICAD_CHECK_FAILED"
        raise _fail(code, msgs.get(code) or f"paicad 를 쓸 수 없습니다({code})")
    _write_json(os.path.join(out, "prep", "paicad.json"), {k: v.get(k) for k in ("version", "ocp", "pinned", "warning",
                                                                                 "checked_at")})
    if v.get("warning"):
        with ex._tx() as conn:
            jobs_repo.add_warnings(conn, ex.job["id"], ex.token, [f"[BD_GEOM] {v['warning']}"])
    opts = None
    if pc.get("options"):
        opts = os.path.join(out, "prep", "paicad_options.json")
        _write_json(opts, pc["options"])
    threads = int(pc["threads"])
    cad = os.path.join(out, *str(inp["step"]["rel"]).split("/"))
    if not os.path.isfile(cad):
        raise _fail("PREREQUISITE_MISSING", "STEP 사본(input/step)이 없습니다 — BD_INPUT 부터 다시")
    assem = None
    if scn == "same":
        b = doe.get("base") or {}
        assem = b.get("case_dir") or os.path.dirname(b["rad_path"])
        try:
            check_input_path(ex.settings, b["rad_path"], "RAD")
        except DomainError as exc:
            raise _fail(exc.code, f"기준 Case 입력을 쓸 수 없습니다: {exc.message}") from None
    elif scn == "mesh":
        assem = os.path.join(out, "input", "mesh")
    if assem is not None:
        try:
            core_adapter.doe_assem_check(assem, float(dcfg["same"]["max_assem_mb"]) if scn == "same" else 1e12)
        except core_adapter.CoreError as exc:
            raise _fail(exc.code, exc.message) from None
    a_case = _a_case(ex, echo) if scn in ("mesh", "step") else None
    plan = (["a_fixed"] if a_case else []) + (["fixed", "extract0"] if assem else []) + ["extract"] + (
        ["tag"] if assem else [])
    n = len(plan)
    done = {"i": 0}

    def progress(pct: int, _msg: str) -> None:
        prog(100.0 * (done["i"] + pct / 100.0) / n)

    def fresh(rel: str) -> str:
        try:
            return core_adapter.doe_fresh_dir(out, rel, doe)
        except core_adapter.CoreError as exc:
            raise _fail(exc.code, exc.message) from None

    pio = core_adapter.doe_paicad_io()
    prep = os.path.join(out, "prep")
    body_map = None
    outputs: dict[str, Any] = {"paicad_version": v.get("version"), "commands": []}
    for step in plan:
        if step == "a_fixed":
            d = fresh(os.path.join("prep", "a_fixed"))
            r = _paicad(ex, st, "paicad_fixed_scan", {"assem_dir": a_case["case_dir"], "parts": str(a_case["part_id"]),
                                                      "out_dir": d, "options": opts, "threads": threads},
                        cwd=prep, capture=os.path.join(prep, "a_fixed.stdout.log"),
                        report=os.path.join(d, pio.SCAN_JSON), stage="prep", echo=echo, progress=progress, tick=tick,
                        label="fixed-scan(A) ")
            if not r["ok"]:
                echo(f"[esl-worker] A Case fixed-scan 실패({r['code']}) — A 체결점은 3-2-1 만(A_FASTENERS_UNKNOWN)")
        elif step == "fixed":
            d = fresh(os.path.join("prep", "fixed"))
            r = _paicad(ex, st, "paicad_fixed_scan", {"assem_dir": assem, "parts": pio.parts_arg([inp["part_id"]]),
                                                      "out_dir": d, "options": opts, "threads": threads},
                        cwd=prep, capture=os.path.join(prep, "fixed.stdout.log"), report=os.path.join(d, pio.SCAN_JSON),
                        stage="prep", echo=echo, progress=progress, tick=tick, label="fixed-scan ")
            if not r["ok"]:
                raise _paicad_fail(r, "fixed-scan")
            fx = (r.get("report") or {}).get("fixed") or {}
            echo(f"[esl-worker] 고정 노드 {fx.get('total')} (클러스터 {len(fx.get('clusters') or [])})")
        elif step == "extract0":
            d = fresh(os.path.join("prep", "extract0"))
            r = _paicad(ex, st, "paicad_extract", {"cad": cad, "out_dir": d, "assem_dir": None, "body_map": None,
                                                   "options": opts, "threads": threads},
                        cwd=prep, capture=os.path.join(prep, "extract0.stdout.log"),
                        report=os.path.join(d, pio.EXTRACT_JSON), stage="prep", echo=echo, progress=progress,
                        tick=tick, label="extract(1차) ")
            if not r["ok"]:
                raise _paicad_fail(r, "extract 1차")
            try:
                bm = pio.body_map_doc(pio.read_json_limited(os.path.join(d, pio.EXTRACT_JSON),
                                                            float(dcfg["limits"]["max_json_mb"])), inp["part_id"])
            except Exception as exc:  # noqa: BLE001 - EslError(STEP_BODY_COUNT·PAICAD_FAILED)
                raise _fail(getattr(exc, "code", "PAICAD_FAILED"), getattr(exc, "message", str(exc))) from None
            body_map = os.path.join(prep, "body_map.json")
            _write_json(body_map, bm)
        elif step == "extract":
            d = fresh(os.path.join("prep", "extract"))
            r = _paicad(ex, st, "paicad_extract", {"cad": cad, "out_dir": d, "assem_dir": assem, "body_map": body_map,
                                                   "options": opts, "threads": threads},
                        cwd=prep, capture=os.path.join(prep, "extract.stdout.log"),
                        report=os.path.join(d, pio.EXTRACT_JSON), stage="prep", echo=echo, progress=progress,
                        tick=tick, label="extract ")
            if not r["ok"]:
                raise _paicad_fail(r, "extract")
            doc = r.get("report") or {}
            echo(f"[esl-worker] 비드 {len(doc.get('beads') or [])} · 특징 {len(doc.get('features') or [])}")
            outputs["n_beads"] = len(doc.get("beads") or [])
        else:   # tag
            d = fresh(os.path.join("prep", "tag"))
            r = _paicad(ex, st, "paicad_tag", {"cad": cad, "features": os.path.join(prep, "extract", pio.EXTRACT_JSON),
                                               "assem_dir": assem, "fixed_dir": os.path.join(prep, "fixed"),
                                               "out_dir": d, "body_map": body_map, "options": opts,
                                               "threads": threads},
                        cwd=prep, capture=os.path.join(prep, "tag.stdout.log"), report=os.path.join(d, pio.TAG_JSON),
                        stage="prep", echo=echo, progress=progress, tick=tick, label="tag ")
            if not r["ok"]:
                raise _paicad_fail(r, "tag")
        outputs["commands"].append({"step": step, "exit_code": r["exit_code"], "seconds": r["seconds"], "ok": r["ok"]})
        done["i"] += 1
        prog(100.0 * done["i"] / n)
    with ex._tx() as conn:
        jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"bd_geom": _jsonable(outputs)})
    return outputs


# ---------------------------------------------------------------- BD_GRID
def _grid(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    echo = _echo_fn(log_path)
    doe = ex.lib["doe"]
    full, dcfg = _cfg(ex)
    out = ex.cdir
    rev = str(int(doe["rev"]))
    prog = _Progress(ex, st)
    prog(0)
    inp = _read_json(os.path.join(out, "prep", "input.json"))
    rd = os.path.join(out, "doe", rev)
    cells = _read_json(os.path.join(rd, "cells.json"))
    if not isinstance(inp, dict) or not isinstance(cells, dict):
        raise _fail("PREREQUISITE_MISSING", "준비 결과(prep/input.json) 또는 doe/<rev>/cells.json 이 없습니다")
    ids = [c["id"] for c in cells.get("cells") or []]
    gc = {"schema_version": 1, "cells": list(cells.get("cells") or []) + [{"id": NOMINAL_CELL, "values": {}}]}
    gcells = os.path.join(rd, "grid_cells.json")
    _write_json(gcells, gc)
    pio = core_adapter.doe_paicad_io()
    try:
        gdir = core_adapter.doe_fresh_dir(out, os.path.join("doe", rev, "grid"), doe)
    except core_adapter.CoreError as exc:
        raise _fail(exc.code, exc.message) from None
    pc = dcfg["paicad"]
    opts = os.path.join(out, "prep", "paicad_options.json") if pc.get("options") else None
    if opts and not os.path.isfile(opts):
        _write_json(opts, pc["options"])
    fixed = os.path.join(out, "prep", "fixed") if doe["scenario"] in ("same", "mesh") else ""
    vals = {"cad": os.path.join(out, *str(inp["step"]["rel"]).split("/")),
            "features": os.path.join(out, "prep", "extract", pio.EXTRACT_JSON), "cells": gcells,
            "thumb": os.path.join(rd, "thumb_options.json"), "fixed_dir": fixed, "out_dir": gdir, "options": opts,
            "threads": int(pc["threads"])}
    r = _paicad(ex, st, "paicad_grid", vals, cwd=rd, capture=os.path.join(rd, "grid.stdout.log"),
                report=os.path.join(gdir, pio.GRID_MANIFEST), stage="prep", echo=echo,
                progress=lambda pct, _m: prog(pct), tick=_tick(ex), label="grid ")
    if not r["ok"]:
        raise _paicad_fail(r, "view grid")
    g = pio.read_grid(gdir, ids, float(dcfg["limits"]["max_json_mb"]))
    rows = [x for x in g["cells"] if x["id"] in set(ids)]
    cnt = count_states(rows)
    echo(f"[esl-worker] 미리보기 셀 {len(ids)}: OK {cnt['ok']} · 충돌 {cnt['collision']} · 고정 침범 {cnt['fixed']} · "
         f"형상 {cnt['geom']} · 썸네일 경고 {cnt['thumb_warn']}")
    return {"cells": len(ids), **cnt}


def count_states(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {"ok": sum(r["state"] == "READY" for r in rows),
            "collision": sum(r["state"] == "SKIPPED_COLLISION" for r in rows),
            "fixed": sum(r["state"] == "SKIPPED_FIXED" for r in rows),
            "geom": sum(r["state"] == "SKIPPED_GEOM" for r in rows),
            "thumb_warn": sum(r.get("warning") == "THUMB_UNAVAILABLE" for r in rows)}


# ---------------------------------------------------------------- BD_DESIGNS
def design_list(ex) -> tuple[list[str], dict[str, Any]]:
    """실행 대상 안 id(미리보기 READY, id 순) + ③ noise, 미리보기 행."""
    doe = ex.lib["doe"]
    _, dcfg = _cfg(ex)
    out = ex.cdir
    rev = str(int(doe["rev"]))
    m = _read_json(os.path.join(out, "doe", rev, "matrix.json"))
    if not isinstance(m, dict) or not isinstance(m.get("designs"), list):
        raise _fail("PREREQUISITE_MISSING", "doe/<rev>/matrix.json 이 없습니다")
    if doe.get("matrix_sha256") and m.get("matrix_sha256") != doe["matrix_sha256"]:
        raise _fail("PREVIEW_STALE", "실행 행렬 sha256 이 미리보기 행렬과 다릅니다")
    ids = sorted(d["id"] for d in m["designs"] if d["id"] != BASELINE)
    pio = core_adapter.doe_paicad_io()
    try:
        g = pio.read_grid(os.path.join(out, "doe", rev, "grid"), ids, float(dcfg["limits"]["max_json_mb"]))
    except Exception as exc:  # noqa: BLE001 - EslError(PAICAD_FAILED)
        raise _fail("PREVIEW_STALE", f"미리보기 결과를 읽지 못했습니다: {getattr(exc, 'message', exc)}") from None
    by = {r["id"]: r for r in g["cells"]}
    run = [i for i in ids if (by.get(i) or {}).get("state") == "READY"]
    if doe["scenario"] == "step":
        run.append(NOISE)
    return run, by


def parallel(ex, n_nodes: int) -> dict[str, Any]:
    full, dcfg = _cfg(ex)
    backend = (((full.get("opt_run") or {}).get("solver")) or {}).get("backend") or "auto"
    return core_adapter.doe_parallel_limit(n_nodes, int(dcfg["run"]["parallel"]), float(dcfg["run"]["memory_margin"]),
                                           str(backend))


def _designs(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    echo = _echo_fn(log_path)
    doe = ex.lib["doe"]
    out = ex.cdir
    prog = _Progress(ex, st)
    prog(0)
    ids, _pv = design_list(ex)
    base = _read_json(os.path.join(out, "prep", "base.json"), {}) or {}
    lim = parallel(ex, int(base.get("n_nodes") or 1))
    p = int(lim["parallel"])
    gb = 1024 ** 3
    echo(f"[esl-worker] BD_DESIGNS: 대상 안 {len(ids)}개(미리보기 OK{' + 잡음 바닥' if NOISE in ids else ''}), 동시 {p}"
         + (f" (요청 {lim['requested']} → 메모리 자동 축소: 추정 {lim['estimate_bytes'] / gb:.2f} GB × {p} ≤ 가용 "
            f"{(lim['available_bytes'] or 0) / gb:.1f} GB × run.memory_margin)" if lim.get("reduced") else ""))
    set_progress(ex, st, 0.0, outputs=_jsonable({"parallel": lim, "n_designs": len(ids)}))
    procs = paicad_proc.Procs()
    grace = float(ex.settings.worker.terminate_grace_s)
    stats = {"ok": 0, "reused": 0, "failed": 0, "skipped": 0, "canceled": 0}
    tick = _tick(ex)
    finished = 0
    if not ids:
        echo("[esl-worker] 실행할 안이 없습니다(미리보기 OK 0) — 순위 없음")
        return {"n_designs": 0, "parallel": lim, **stats}
    pool = ThreadPoolExecutor(max_workers=p, thread_name_prefix="esl-doe")
    futs = {pool.submit(_one_design, ex, did, procs, echo): did for did in ids}
    pending = set(futs)
    try:
        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for f in done:
                r = f.result()          # 예외 → 아래 except(전체 중단)
                finished += 1
                k = "reused" if r.get("reused") else ("ok" if r["status"] == "OK" else (
                    "skipped" if str(r["status"]).startswith("SKIPPED") else "failed"))
                stats[k] += 1
                echo(r["line"])
            if done:
                prog(100.0 * finished / len(ids))
            tick()
    except BaseException:
        procs.kill_all(grace, ex.lim)
        for f in futs:
            f.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        n_left = len(ids) - finished
        echo(f"[esl-worker] BD_DESIGNS 중단 — 끝난 안 {finished}개 유지, 진행 중·대기 안 {n_left}개 CANCELED")
        raise
    pool.shutdown(wait=True)
    echo(f"[esl-worker] BD_DESIGNS 완료: 성공 {stats['ok']} · 재사용 {stats['reused']} · 실패 {stats['failed']} · "
         f"스킵 {stats['skipped']}")
    return {"n_designs": len(ids), "parallel": lim, **stats}


def _one_design(ex, did: str, procs: paicad_proc.Procs, echo) -> dict[str, Any]:
    """안 1개(스레드): 이어하기 판단 → paicad → 코어 bd_eval 자식. 반환 {design, status, reused, line}."""
    if procs.stop.is_set():
        raise paicad_proc.PaicadCanceled()
    doe = ex.lib["doe"]
    out = ex.cdir
    scn = doe["scenario"]
    full, dcfg = _cfg(ex)
    pc = dcfg["paicad"]
    rev = str(int(doe["rev"]))
    dd = os.path.join(out, "run", "designs", did)
    try:
        sha = core_adapter.doe_design_sha(doe, out, did)
        prev = core_adapter.doe_reusable(dd, sha)
    except core_adapter.CoreError as exc:
        raise _fail(exc.code, exc.message) from None
    if prev is not None:
        return {"design": did, "status": prev.get("status"), "reused": True,
                "line": f"[{did}] 이전 결과 재사용({prev.get('status')}) — paicad·해석 생략"}
    os.makedirs(dd, exist_ok=True)
    pio = core_adapter.doe_paicad_io()
    inp = _read_json(os.path.join(out, "prep", "input.json"), {}) or {}
    opts = os.path.join(out, "prep", "paicad_options.json") if pc.get("options") else None
    vfile = os.path.join(out, "doe", rev, "values", f"{BASELINE if did == NOISE else did}.json")
    base_vals = {"cad": os.path.join(out, *str(inp["step"]["rel"]).split("/")),
                 "features": os.path.join(out, "prep", "extract", pio.EXTRACT_JSON), "values": vfile,
                 "options": opts, "threads": int(pc["threads"])}
    try:
        if scn in ("same", "mesh"):
            pd = core_adapter.doe_fresh_dir(out, os.path.join("run", "designs", did, "paicad"), doe)
            assem = ((doe.get("base") or {}).get("case_dir") or os.path.dirname((doe.get("base") or {})["rad_path"])
                     if scn == "same" else os.path.join(out, "input", "mesh"))
            bm = os.path.join(out, "prep", "body_map.json")
            vals = {**base_vals, "assem_dir": assem, "tag_dir": os.path.join(out, "prep", "tag"),
                    "fixed_dir": os.path.join(out, "prep", "fixed"), "update_dir": os.path.join(pd, "update"),
                    "morph_dir": os.path.join(pd, "morph"), "check_dir": os.path.join(pd, "check"),
                    "out_files_dir": os.path.join(pd, "out_files"), "body_map": bm if os.path.isfile(bm) else None}
            key, cwd, report = "paicad_run", pd, os.path.join(pd, "check", pio.RUN_JSON)
        else:
            ud = core_adapter.doe_fresh_dir(out, os.path.join("run", "designs", did, "update"), doe)
            vals = {**base_vals, "out_dir": ud}
            key, cwd, report = "paicad_update", dd, os.path.join(ud, pio.UPDATE_JSON)
    except core_adapter.CoreError as exc:
        raise _fail(exc.code, exc.message) from None
    r = _paicad(ex, None, key, vals, cwd=cwd, capture=os.path.join(dd, "paicad.stdout.log"), report=report,
                stage="design", echo=echo, procs=procs, relay=False, label=f"[{did}] {key[7:]} ")
    pa = {"ok": r["ok"], "status": r.get("status"), "code": r.get("code"), "paicad_code": r.get("paicad_code"),
          "message": r.get("message"), "seconds": r["seconds"]}
    status, code = _eval_child(ex, did, pa, procs)
    res = _read_json(os.path.join(dd, "result.json"), {}) or {}
    solve = res.get("solve") or {}
    if status == "OK":
        line = (f"[{did}] {key[7:]} {r['seconds']:.0f} s OK · solve {len(res.get('per_esl') or [])} ESL "
                f"{float(solve.get('seconds') or 0):.1f} s · C_max {float(res.get('C_max') or 0):.4g}")
    else:
        line = f"[{did}] {key[7:]} {r['seconds']:.0f} s → {status} {code or res.get('code') or ''}"
    return {"design": did, "status": status, "reused": False, "line": line}


def _eval_child(ex, did: str, pa: dict[str, Any], procs: paicad_proc.Procs) -> tuple[str, str | None]:
    """코어 자식(spawn) bd_eval 1개. 결과 없이 끝나면 FAILED_SOLVE 기록(재시도 대상)."""
    import multiprocessing

    from . import limiter
    from .child import child_entry

    doe = ex.lib["doe"]
    ldir = os.path.join(ex.cdir, "logs", ex.job["id"], "designs")
    os.makedirs(ldir, exist_ok=True)
    log_path = os.path.join(ldir, f"{did}.log")
    result_path = log_path[:-4] + ".result.json"
    for pth in (result_path, core_adapter.stage_out_path(log_path)):
        if os.path.exists(pth):
            os.remove(pth)
    spec = {"cfg": {}, "lib": {"doe": doe, "extra": {"design": did, "paicad": pa}}, "out": ex.cdir, "stage": "bd_eval",
            "log_path": log_path, "result_path": result_path, "priority": ex.settings.worker.priority,
            "target": ex.worker.core_target, "job_id": ex.job["id"], "tag": ex.job["id"], "parent_pid": os.getpid(),
            "progress_path": None}
    gate = limiter.prepare(ex.worker, spec, ex.lim)
    proc = multiprocessing.get_context("spawn").Process(target=child_entry, args=(spec,), name=f"esl-doe-{did}")
    proc.start()
    procs.add(proc)
    try:
        limiter.after_start(ex.worker, proc, gate)
        while proc.is_alive():
            proc.join(0.2)
            if procs.stop.is_set():
                raise paicad_proc.PaicadCanceled()
    finally:
        procs.remove(proc)
        if proc.is_alive():
            proc.terminate()
            proc.join(float(ex.settings.worker.terminate_grace_s))
            if proc.is_alive():
                proc.kill()
                proc.join(5)
    res = _read_json(result_path, None)
    so = _read_json(core_adapter.stage_out_path(log_path), None)
    if res and res.get("ok") and isinstance(so, dict):
        return str(so.get("status")), so.get("code")
    code = (res or {}).get("code") or "CORE_PROCESS_DIED"
    msg = (res or {}).get("message") or f"코어 평가 프로세스가 비정상 종료했습니다(exit {proc.exitcode})"
    try:
        core_adapter.doe_record_design(doe, ex.cdir, did, "FAILED_SOLVE", code, msg)
    except core_adapter.CoreError:
        pass
    return "FAILED_SOLVE", code
