"""비드 최적화 OPT_RUN 작업 실행(계약 esl_opt_run.md §4·§6·§8·§9) — executor 가 OPT_RUN step 마다 ``run_step`` 을 부른다.

- 작업 폴더 ``<esl_root>/_opt/<opt_run_id>/``(대상 = jobs.opt_run_id, case_id NULL). step 별 하위 폴더 target/·load/·deck/·
  solve/·post/ 는 코어(core_adapter)가 fresh_dir(이전 내용 ``_backup/<UTC>/``, 삭제 없음)로 만든다. 로그
  ``logs/<job_id>/step_NN_<KEY>.log``.
- OPT_PREP·OPT_LOAD·OPT_DECK = 코어 자식 프로세스(spawn, core_adapter.run_opt_stage). 끝나면 단계 요약 JSON 의 경고를 작업
  경고로, OPT_LOAD 뒤에는 ``opt_runs.result = {load_selection, stage:"load"}``(화면 선정 표는 이때부터).
- OS_SOLVE = os_solve.run(LOCAL, OptiStruct 세마포어·라이선스 재시도·덱 sha256 같으면 재사용 → SKIPPED).
- OPT_POST = hw 배치 TCL(``commands.bead_post``, hw 세마포어 공유 — step outputs.hw_acquired) → post/shape.csv → 코어 자식
  opt_post(비드 산출물·history·opt.json·report.html).
- OPT_REGISTER = register.register_opt_run(opt_runs.result = OptResult + files, report_rel). artifacts 테이블은 쓰지 않는다
  (artifacts.case_id NOT NULL — 결과는 실행 폴더 파일 + opt_runs.result, 백엔드 services/opt.py 가 같은 위치를 읽음).
- 작업 진행률 = step 가중 ``OPT_STEP_WEIGHTS``(1·4·1·82·10·2) × step 진행률.
- 입력 보호: 라이브러리 항목·템플릿 폴더·S1 Case 입력 rad 는 읽기만(코어 Writer 의 입력 목록으로 쓰기 거부).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from esl_platform.core.config import default_bead_post_tcl
from esl_platform.core.db.tables import jobs as jobs_t
from esl_platform.core.errors import DomainError
from esl_platform.core.job_types import OPT_STEP_WEIGHTS
from esl_platform.core.paths import (
    LIBRARY_DIR,
    TEMPLATE_DIR,
    check_includes,
    check_input_path,
    esl_subdir,
    opt_run_dir,
)
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import opt as opt_repo
from sqlalchemy import and_, update

from . import localproc, os_solve

STEP_ORDER = ("OPT_PREP", "OPT_LOAD", "OPT_DECK", "OS_SOLVE", "OPT_POST", "OPT_REGISTER")
STAGE_JSON = {"opt_prep": ("target", "prep.json"), "opt_load": ("load", "load.json"),
              "opt_deck": ("deck", "optdeck.json")}
BEAD_FAILURE = "BEAD_POST_FAILED"
POST_HW_SHARE = 50.0          # OPT_POST 진행률: hw 50 · 후처리 50 (계약 §6.3)


class PrepareFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------- 준비
def prepare(ex) -> tuple[str, dict[str, Any]]:
    """작업 폴더 + 코어에 넘길 spec["lib"]. 항목·템플릿 폴더 존재, S1 Case 입력 경로 재검사(읽지 않음)."""
    s = ex.settings
    job = ex.job
    p = job["params"] or {}
    rid = job["opt_run_id"]
    if not rid or p.get("opt_run_id") not in (None, rid):
        raise PrepareFailed("INPUT_INVALID", "작업 params 가 이 최적화 실행의 것이 아닙니다")
    try:
        cdir = opt_run_dir(s, rid)
        lib_root = esl_subdir(s, LIBRARY_DIR)
        tpl_root = esl_subdir(s, TEMPLATE_DIR)
        os.makedirs(cdir, exist_ok=True)
        entries = []
        for it in p.get("entries") or []:
            d = esl_subdir(s, *it["dir_rel"].split("/"))
            if not os.path.isfile(os.path.join(d, "entry.json")):
                raise PrepareFailed("PREREQUISITE_MISSING", f"라이브러리 항목 폴더가 없습니다: {it['dir_rel']}")
            entries.append({**it, "dir": d})
        if not entries:
            raise PrepareFailed("INPUT_INVALID", "최적화에 넣을 ESL 이 없습니다")
        base = dict(p["base"]) if p.get("base") else None
        tpl = dict(p["template"]) if p.get("template") else None
        if p.get("scenario") == "S1":
            if base is None:
                raise PrepareFailed("INPUT_INVALID", "S1 기준 정보(base)가 없습니다")
            try:
                base["rad_path"] = check_input_path(s, base["rad_path"], "RAD")
            except DomainError as exc:
                raise PrepareFailed("PREREQUISITE_MISSING", f"기준 Case 입력 rad 경로를 쓸 수 없습니다({exc.code}: "
                                    f"{exc.message}) — Case 입력을 다시 올리거나 템플릿 최적화를 쓰세요") from None
            # include 도 매번 다시 검사(CASE_EXTRACT 사전조건과 같음): input_roots 밖 include 는 읽기 전에 거부
            from . import core_adapter

            cc = (((p.get("settings") or {}).get("core") or {}).get("case")) or {}
            roots = [os.path.realpath(r) for r in s.storage.input_roots]

            def inside(fp: str) -> bool:      # 밖 파일은 열지 않는다(중첩 include 를 찾으려 읽지도 않음)
                rp = os.path.realpath(fp)
                return any(rp == r or rp.startswith(r.rstrip(os.sep) + os.sep) for r in roots)

            try:
                refs = core_adapter.scan_include_refs(base["rad_path"], int(cc.get("rad_include_max_depth") or 8),
                                                      cc.get("include_path_map") or None, follow=inside)
                incs = [r["path"] for r in refs if r.get("path")]
            except core_adapter.CoreError as exc:
                raise PrepareFailed("INPUT_INVALID", f"기준 Case 입력 rad 의 include 를 확인할 수 없습니다({exc.code}: "
                                    f"{exc.message})") from None
            check_includes(s, incs)        # 밖이면 DomainError PATH_OUTSIDE_ROOT → 아래에서 PrepareFailed
        else:
            if tpl is None:
                raise PrepareFailed("INPUT_INVALID", "S2 템플릿 정보(template)가 없습니다")
            d = esl_subdir(s, *tpl["dir_rel"].split("/"))
            if not (os.path.isfile(os.path.join(d, "template.npz")) and os.path.isfile(os.path.join(d, "template.json"))):
                raise PrepareFailed("TEMPLATE_NOT_FOUND", f"템플릿 파일이 없습니다: {tpl['dir_rel']}")
            tpl["dir"] = d
    except DomainError as exc:
        raise PrepareFailed(exc.code, exc.message) from None
    with ex.engine.begin() as conn:
        r = opt_repo.get_run(conn, rid, for_update=True)
        if r is None:
            raise PrepareFailed("OPT_RUN_NOT_FOUND", "최적화 실행 행이 없습니다")
        # 재시도: 이전 결과는 이번 실행이 다시 채운다(OPT_LOAD 뒤 선정 표, OPT_REGISTER 뒤 결과)
        if r.get("result") is not None or r.get("report_rel"):
            opt_repo.update_run(conn, rid, result=None, report_rel=None)
    st = p.get("settings") or {}
    lib = {"run_id": rid, "scenario": p.get("scenario"), "title": p.get("title"), "cfg": st.get("opt_run") or {},
           "core": st.get("core") or {}, "library": st.get("library") or {}, "lib_root": lib_root,
           "templates_root": tpl_root, "entries": entries, "base": base, "template": tpl,
           "design": p.get("design") or {}, "options": p.get("options") or {}, "warnings": list(p.get("warnings") or []),
           "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
           "entry_ids": list(r.get("entry_ids") or []), "job_id": job["id"], "retry": bool(job.get("retry_of_job_id"))}
    return cdir, lib


# ---------------------------------------------------------------- 진행률
def job_progress(step_key: str, pct: float) -> float:
    done = 0.0
    for k in STEP_ORDER:
        if k == step_key:
            return round(done + OPT_STEP_WEIGHTS[k] * max(0.0, min(100.0, pct)) / 100.0, 2)
        done += OPT_STEP_WEIGHTS[k]
    return done


def mark_job_progress(conn, ex, step_key: str, pct: float) -> None:
    conn.execute(update(jobs_t).where(and_(jobs_t.c.id == ex.job["id"], jobs_t.c.lease_token == ex.token))
                 .values(progress_pct=job_progress(step_key, pct)))


def set_progress(ex, st: dict[str, Any], pct: float, **step_values: Any) -> None:
    """step 진행률 + 작업 진행률(가중). lease 확인."""
    with ex._tx() as conn:
        jobs_repo.step_update(conn, ex.job["id"], ex.token, st["step_no"], progress_pct=float(pct), **step_values)
        mark_job_progress(conn, ex, st["step_key"], pct)


# ---------------------------------------------------------------- step 실행
def run_step(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    from .executor import _StepFailed

    key = st["step_key"]
    if key in ("OPT_PREP", "OPT_LOAD", "OPT_DECK"):
        set_progress(ex, st, 0.0)
        ex._run_core(st, log_path)
        rec = _stage_record(ex.cdir, st["core_stage"])
        with ex._tx() as conn:
            if rec.get("warnings"):
                jobs_repo.add_warnings(conn, ex.job["id"], ex.token, [f"[{key}] {w}" for w in rec["warnings"]])
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {st["core_stage"]: rec.get("summary") or {}})
            if key == "OPT_LOAD":
                sel = _read_json(os.path.join(ex.cdir, "load", "selection.json"))
                opt_repo.update_run(conn, ex.job["opt_run_id"], result=_jsonable({"stage": "load", "load_selection": sel}))
        return {"core_stage": st["core_stage"]}
    if key == "OS_SOLVE":
        try:
            out = os_solve.run(ex, st, log_path)
        except os_solve.SolveFailed as exc:
            raise _StepFailed(exc.code, exc.message, exc.exit_code) from None
        ex.lib["solve_meta"] = {k: out.get(k) for k in ("seconds", "license_waits", "reused", "iterations",
                                                         "converged", "exit_code")}
        with ex._tx() as conn:
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"os_solve": _jsonable(ex.lib["solve_meta"])})
        return out
    if key == "OPT_POST":
        set_progress(ex, st, 0.0)
        hw = _bead_hw(ex, st, log_path)
        set_progress(ex, st, POST_HW_SHARE, outputs={"hw_acquired": False, "hw": hw})
        if "solve_meta" not in ex.lib:          # OS_SOLVE 가 이 실행에서 돌지 않음(이론상 없음) — solve.json 으로
            sj = _read_json(os.path.join(ex.cdir, "solve", "solve.json"), {})
            ex.lib["solve_meta"] = {"seconds": sj.get("seconds"), "license_waits": sj.get("license_waits", 0),
                                    "reused": True}
        ex._run_core(st, log_path)
        return {"core_stage": "opt_post", "hw": hw}
    if key == "OPT_REGISTER":
        from . import register

        with ex._tx() as conn:
            jobs_repo.assert_lease(conn, ex.job["id"], ex.token)
            try:
                res = register.register_opt_run(conn, ex.job, None, ex.cdir)
            except register.RegisterError as exc:
                raise _StepFailed(exc.code, exc.message) from None
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"registered": _jsonable(res)})
            r = res.get("warnings") or []
            if r:
                jobs_repo.add_warnings(conn, ex.job["id"], ex.token, [f"[OPT_POST] {w}" for w in r])
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[esl-worker] OPT_REGISTER: opt_runs.result 등록 완료 (파일 {res.get('n_files')}개, "
                     f"수렴 {res.get('converged')}, 반복 {res.get('iterations')})\n")
        return {"registered": True}
    raise _StepFailed("INTERNAL_ERROR", f"알 수 없는 OPT_RUN step: {key}")


def _read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        if default is not None:
            return default
        raise


def _stage_record(cdir: str, stage: str) -> dict[str, Any]:
    sub, name = STAGE_JSON[stage]
    rec = _read_json(os.path.join(cdir, sub, name), {})
    summ = rec.get("summary") if isinstance(rec.get("summary"), dict) else {
        k: rec.get(k) for k in ("deck", "n_subcases", "n_design_elems", "n_nondesign_elems", "objective")}
    return {"warnings": [str(w)[:300] for w in rec.get("warnings") or []], "summary": summ}


# ---------------------------------------------------------------- OPT_POST hw(비드 Shape Change → shape.csv)
def _bead_hw(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    from . import core_adapter, limiter
    from .executor import _StepFailed

    s = ex.settings
    no = st["step_no"]

    def echo(msg: str) -> None:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")

    tcl = default_bead_post_tcl()
    if not os.path.isfile(tcl):
        raise _StepFailed("TOOL_OUTPUT_MISSING", f"비드 후처리 TCL 이 코드 스냅샷에 없습니다: {tcl}")
    hw = s.altair.hw_exe_path
    if not hw or not os.path.isfile(hw):
        raise _StepFailed(BEAD_FAILURE, f"hw 실행 파일이 없습니다(altair.hw_exe_path): {hw}")
    deck = _read_json(os.path.join(ex.cdir, "deck", "optdeck.json"), {}).get("deck") or "esl_bead.fem"
    stem = os.path.splitext(deck)[0]
    h3d = os.path.join(ex.cdir, "solve", f"{stem}_des.h3d")
    if not os.path.isfile(h3d):
        raise _StepFailed(BEAD_FAILURE, f"설계 이력 h3d 가 없습니다: solve/{stem}_des.h3d")
    post = os.path.join(ex.cdir, "post")
    try:
        prev = core_adapter.opt_fresh_dir(ex.cdir, "post", ex.lib)
    except core_adapter.CoreError as exc:
        raise _StepFailed(exc.code, exc.message) from None
    if prev:
        echo(f"[esl-worker] 이전 후처리 산출물을 옮김: {prev}")
    request = os.path.join(post, "request.txt")
    with open(request, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# ESL 비드 후처리 요청(워커가 작성)\nshape_type\tShape Change\nshape_comps\tX Y Z\n")
    vals = {"hw": hw, "post_tcl": tcl, "post_tcl_fwd": localproc.fwd(tcl), "h3d": h3d, "h3d_fwd": localproc.fwd(h3d),
            "out_dir": post, "out_dir_fwd": localproc.fwd(post), "request": request, "request_fwd": localproc.fwd(request)}
    try:
        argv = localproc.build_argv(list(s.commands.bead_post), vals, exe="hw", what="commands.bead_post")
    except localproc.ProcError as exc:
        raise _StepFailed(exc.code, exc.message) from None
    tick = {"renew": time.monotonic(), "cancel": time.monotonic()}
    limit = s.altair.max_concurrent_hw
    waited = False
    while True:
        with ex._tx() as conn:
            if jobs_repo.acquire_hw(conn, ex.job["id"], ex.token, no, limit):
                break
        if not waited:
            echo(f"[esl-worker] hw 동시 실행 한도 {limit}개(altair.max_concurrent_hw) — 다른 hw 작업이 끝나기를 기다립니다")
            waited = True
        time.sleep(min(0.5, s.worker.claim_interval_s))
        ex._wait_tick(tick)
    with ex._tx() as conn:
        jobs_repo.step_update(conn, ex.job["id"], ex.token, no, command=argv)
    echo(f"[esl-worker] OPT_POST hw: {h3d} → post/ (Shape Change)")
    echo("[esl-worker] argv: " + json.dumps(argv, ensure_ascii=False))
    env = dict(os.environ)
    env.update({"ESL_INPUT": localproc.fwd(h3d), "ESL_OUTPUT": localproc.fwd(post), "ESL_CONFIG": localproc.fwd(request)})
    t0 = time.time()
    try:
        with open(log_path, "ab") as log_fh:
            try:
                ex.hw_proc = localproc.start(argv, cwd=post, log_fh=log_fh, env=env,
                                             preexec=limiter.posix_preexec(ex.lim), priority=s.worker.priority,
                                             fail_code=BEAD_FAILURE, what="hw")
            except localproc.ProcError as exc:
                raise _StepFailed(exc.code, exc.message) from None
            try:
                applied = limiter.attach_popen(ex.lim, ex.hw_proc)
            except limiter.LimiterError as exc:
                raise _StepFailed(limiter.FAILURE_CODE, str(exc)) from None
            with ex._tx() as conn:
                jobs_repo.step_update(conn, ex.job["id"], ex.token, no,
                                      outputs={"hw_acquired": True, "pid": ex.hw_proc.pid, "limiter": applied})
            tail = localproc.FileTail(os.path.join(post, "progress.log"))
            last = time.monotonic()
            shown = 0
            while ex.hw_proc.poll() is None:
                time.sleep(0.1)
                ex._wait_tick(tick)
                if time.monotonic() - last >= 1.0:
                    last = time.monotonic()
                    for ln in tail.poll():
                        echo(ln)
                    pct = int(min(45.0, (time.time() - t0) / 6.0))      # hw 는 진행 신호가 거의 없어 경과 기반(최대 45)
                    if pct > shown:
                        shown = pct
                        set_progress(ex, st, float(pct))
            code = ex.hw_proc.returncode
            for ln in tail.poll(flush=True):
                echo(ln)
            localproc.kill_tree(ex.hw_proc, s.worker.terminate_grace_s, ex.lim)
            ex.hw_proc = None
    finally:
        if ex.hw_proc is not None:
            localproc.kill_tree(ex.hw_proc, s.worker.terminate_grace_s, ex.lim)
            ex.hw_proc = None
    ex._renew()
    done = _read_json(os.path.join(post, "done.json"), {}) or None
    ok = code == 0 and bool(done and done.get("ok")) and os.path.isfile(os.path.join(post, "shape.csv"))
    echo(f"[esl-worker] hw 종료코드 {code} ({time.time() - t0:.1f}s) — {'성공' if ok else '실패'}")
    if not ok:
        if done and not done.get("ok"):
            msg = f"비드 후처리 실패: failed_step={done.get('failed_step')}, {done.get('error') or ''}"
        elif done is None:
            msg = f"비드 후처리(hw)가 done.json 을 남기지 않았습니다(종료코드 {code})"
        elif not os.path.isfile(os.path.join(post, "shape.csv")):
            msg = "비드 후처리 출력 shape.csv 가 없습니다"
        else:
            msg = f"hw 가 비정상 종료했습니다(종료코드 {code})"
        raise _StepFailed(BEAD_FAILURE, msg[:450], code)
    return {k: done.get(k) for k in ("subcase", "simulation", "n_simulations", "n_nodes", "shape_type")}


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))
