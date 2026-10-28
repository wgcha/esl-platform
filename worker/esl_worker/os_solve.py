"""OPT_RUN OS_SOLVE(LOCAL) — 서버 OptiStruct 실행(계약 esl_opt_run.md §8, OR-D-17·18·19).

흐름
1. 재사용(OR-D-19): ``solve/solve.json`` 이 ok 이고 deck_sha256(= deck/<deck>.fem + esl_loads.inc 바이트) 이 같고
   ``<deck>.out``·``<deck>_des.h3d`` 가 있으면 실행하지 않고 SKIPPED(outputs.reused). solve/ 는 건드리지 않는다.
2. ``solve/`` fresh_dir(이전 내용·tmp → ``_backup/<UTC>/``) → 덱 2개 복사, 스크래치 ``solve/tmp/``.
3. OptiStruct 세마포어 ``jobs_repo.acquire_os``(altair.max_concurrent_os, step outputs.os_acquired) — 잡을 때까지 대기
   (lease 갱신·취소 확인 계속).
4. ``commands.os_check``(-check) → 성공 시 ``commands.os_solve``. argv 템플릿(localproc: argv[0] {optistruct}, 메타문자
   거부, shell=False), cwd = solve/, env = 워커 환경(``worker.env_passthrough`` 가 비어 있지 않으면 그 키 + 기본 OS 키만)
   + ``opt_run.solve.env``. argv 는 job_steps.command 에 저장(관리자만 응답에 보임).
5. 실행 중 ``<deck>.out`` 을 step 로그로 중계(``log_tail_lines`` 줄까지) + 진행률 check 5 % + 반복 n/DESMAX × 95 %.
   ``timeout_h`` 초과 → 프로세스 트리 종료, OS_TIMEOUT.
6. 판정 = esl.opt.osout.classify(종료코드·오류 패턴·출력 파일): 라이선스 부족(종료코드≠0 + license_patterns) →
   세마포어 반납, ``license_retry.wait_s`` 대기(취소 즉시) 후 다시(최대 ``license_retry.max`` 번), 소진 →
   OS_LICENSE_UNAVAILABLE. -check 실패 → OS_DECK_INVALID, 메모리 → SOLVER_OUT_OF_MEMORY, 그 밖 OS_SOLVE_FAILED.
   최대 반복 도달(수렴 표식 없음)은 실패 아님(converged=false, 후처리가 경고).
7. ``solve/solve.json`` {deck_sha256, argv, exit_code, seconds, iterations, converged, license_waits, ok} — 실패여도 기록.
   세마포어는 성공·실패·취소 모두 반납(finally).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from esl_platform.core.repositories import jobs as jobs_repo

from . import localproc

CHECK_SHARE = 5.0          # 진행률: -check 5 % + 반복 n/DESMAX × 95 %
BASE_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOME",
                 "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL")


class SolveFailed(Exception):
    def __init__(self, code: str, message: str, exit_code: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.exit_code = exit_code


def deck_sha256(deck_dir: str, deck: str) -> str:
    h = hashlib.sha256()
    for name in (deck, "esl_loads.inc"):
        p = os.path.join(deck_dir, name)
        h.update(name.encode("ascii") + b"\0")
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        h.update(b"\0")
    return h.hexdigest()


def solve_env(settings) -> dict[str, str]:
    pt = list(settings.worker.env_passthrough or [])
    extra = dict((settings.opt_run.solve.env if settings.opt_run else {}) or {})
    if pt:
        return localproc.child_env(list(BASE_ENV_KEYS) + pt, extra)
    env = dict(os.environ)
    env.update({str(k): str(v) for k, v in extra.items()})
    return env


def reusable(solve_dir: str, sha: str, stem: str) -> dict[str, Any] | None:
    try:
        with open(os.path.join(solve_dir, "solve.json"), encoding="utf-8") as fh:
            sj = json.load(fh)
    except (OSError, ValueError):
        return None
    if not (isinstance(sj, dict) and sj.get("ok") and sj.get("deck_sha256") == sha):
        return None
    for ext in (".out", "_des.h3d"):
        if not os.path.isfile(os.path.join(solve_dir, stem + ext)):
            return None
    return sj


class _Runner:
    def __init__(self, ex, st: dict[str, Any], log_path: str) -> None:
        self.ex = ex
        self.st = st
        self.no = st["step_no"]
        self.log_path = log_path
        s = ex.settings
        self.s = s
        o = (ex.lib or {}).get("cfg") or {}
        self.cfg = o.get("solve") or {}
        self.tick = {"renew": time.monotonic(), "cancel": time.monotonic()}
        self.out: dict[str, Any] = {"os_acquired": False, "license_waits": 0}
        self.relayed = 0
        self.prev_label = ""
        self.n_solve = 0
        self.shown = -1

    # ------------------------------------------------------------ 도우미
    def echo(self, msg: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")

    def outputs(self, **kw: Any) -> None:
        self.out.update(kw)
        with self.ex._tx() as conn:
            jobs_repo.step_update(conn, self.ex.job["id"], self.ex.token, self.no, outputs=dict(self.out))

    def progress(self, pct: float) -> None:
        if int(pct) <= self.shown:
            return
        self.shown = int(pct)
        from .opt_jobs import set_progress

        set_progress(self.ex, self.st, float(self.shown))

    def acquire(self) -> None:
        limit = int(self.s.altair.max_concurrent_os)
        waited = False
        while True:
            with self.ex._tx() as conn:
                if jobs_repo.acquire_os(conn, self.ex.job["id"], self.ex.token, self.no, limit):
                    break
            if not waited:
                self.echo(f"[esl-worker] OptiStruct 동시 실행 한도 {limit}개(altair.max_concurrent_os) — 다른 최적화가 "
                          "끝나기를 기다립니다")
                waited = True
            time.sleep(min(0.5, self.s.worker.claim_interval_s))
            self.ex._wait_tick(self.tick)
        if waited:
            self.echo("[esl-worker] OptiStruct 실행 권한을 얻었습니다")
        self.out["os_acquired"] = True

    def release(self) -> None:
        if not self.out.get("os_acquired"):
            return
        self.out["os_acquired"] = False
        try:
            with self.ex._tx() as conn:
                jobs_repo.release_os(conn, self.ex.job["id"], self.ex.token, self.no)
                jobs_repo.step_update(conn, self.ex.job["id"], self.ex.token, self.no, outputs=dict(self.out))
        except Exception:  # noqa: BLE001 - lease 상실·취소 종료 중: step 이 RUNNING 이 아니게 되면 세마포어는 자동으로 풀린다
            pass

    def wait_license(self, n: int, mx: int, wait_s: float) -> None:
        self.release()
        self.out["license_waits"] = n
        self.outputs(license_wait=True)
        self.echo(f"[esl-worker] 라이선스 부족 — {wait_s:g}초 후 다시 시도합니다({n}/{mx})")
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            time.sleep(min(0.2, max(0.01, end - time.monotonic())))
            self.ex._wait_tick(self.tick)
        self.out.pop("license_wait", None)
        self.acquire()
        self.outputs()

    # ------------------------------------------------------------ 프로세스 1회
    def run_once(self, argv: list[str], cwd: str, out_path: str, *, check: bool, desmax: int,
                 deadline: float) -> tuple[int | None, str]:
        from . import limiter

        ex = self.ex
        it_re = re.compile(self.cfg.get("iteration_pattern") or r"(?m)^\s*ITERATION\s+(\d+)")
        max_lines = int(self.cfg.get("log_tail_lines") or 2000)
        with ex._tx() as conn:
            jobs_repo.step_update(conn, ex.job["id"], ex.token, self.no, command=argv)
        self.echo("[esl-worker] argv: " + json.dumps(argv, ensure_ascii=False))
        if os.path.exists(out_path) and self.prev_label:   # 이전 시도(-check·라이선스 실패)의 .out 은 이름을 바꿔 보존
            os.replace(out_path, f"{out_path}.{self.prev_label}")
        if check:
            self.prev_label = "check"
        else:
            self.n_solve += 1
            self.prev_label = f"try{self.n_solve}"
        code = None
        with open(self.log_path, "ab") as log_fh:
            try:
                ex.hw_proc = localproc.start(argv, cwd=cwd, log_fh=log_fh, env=solve_env(self.s),
                                             preexec=limiter.posix_preexec(ex.lim), priority=self.s.worker.priority,
                                             fail_code="OS_SOLVE_FAILED", what="OptiStruct")
            except localproc.ProcError as exc:
                raise SolveFailed(exc.code, exc.message) from None
            try:
                applied = limiter.attach_popen(ex.lim, ex.hw_proc)
            except limiter.LimiterError as exc:
                localproc.kill_tree(ex.hw_proc, self.s.worker.terminate_grace_s, ex.lim)
                ex.hw_proc = None
                raise SolveFailed(limiter.FAILURE_CODE, str(exc)) from None
            self.outputs(pid=ex.hw_proc.pid, phase="check" if check else "solve", limiter=applied)
            tail = localproc.FileTail(out_path)
            last = 0.0
            try:
                while ex.hw_proc.poll() is None:
                    time.sleep(0.1)
                    ex._wait_tick(self.tick)
                    if time.monotonic() > deadline:
                        localproc.kill_tree(ex.hw_proc, self.s.worker.terminate_grace_s, ex.lim)
                        ex.hw_proc = None
                        raise SolveFailed("OS_TIMEOUT", f"OptiStruct 가 시간 한도 {self.cfg.get('timeout_h')} 시간"
                                          "(opt_run.solve.timeout_h)을 넘어 중단했습니다")
                    if time.monotonic() - last >= 0.5:
                        last = time.monotonic()
                        self._relay(tail, it_re, check, desmax, max_lines)
                code = ex.hw_proc.returncode
                self._relay(tail, it_re, check, desmax, max_lines, flush=True)
            finally:
                if ex.hw_proc is not None:
                    localproc.kill_tree(ex.hw_proc, self.s.worker.terminate_grace_s, ex.lim)
                    ex.hw_proc = None
        ex._renew()
        try:
            with open(out_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        return code, text

    def _relay(self, tail, it_re, check: bool, desmax: int, max_lines: int, flush: bool = False) -> None:
        lines = tail.poll(flush=flush)
        for ln in lines:
            if self.relayed < max_lines:
                self.echo("[os] " + ln)
            elif self.relayed == max_lines:
                self.echo(f"[esl-worker] .out 중계 {max_lines}줄 도달(opt_run.solve.log_tail_lines) — 이후는 solve/ 의 .out")
            self.relayed += 1
            if not check:
                m = it_re.search(ln)
                if m:
                    it = int(m.group(1))
                    self.out["iteration"] = it
                    self.progress(CHECK_SHARE + (100.0 - CHECK_SHARE) * min(it, desmax) / max(1, desmax))


def run(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    from . import core_adapter

    r = _Runner(ex, st, log_path)
    s = ex.settings
    cdir = ex.cdir
    cfg = r.cfg
    deck_dir = os.path.join(cdir, "deck")
    solve_dir = os.path.join(cdir, "solve")
    try:
        with open(os.path.join(deck_dir, "optdeck.json"), encoding="utf-8") as fh:
            deck = json.load(fh)["deck"]
    except (OSError, ValueError, KeyError):
        raise SolveFailed("PREREQUISITE_MISSING", "덱(deck/optdeck.json)이 없습니다 — OPT_DECK 부터 다시") from None
    stem = os.path.splitext(deck)[0]
    try:
        sha = deck_sha256(deck_dir, deck)
    except OSError as exc:
        raise SolveFailed("PREREQUISITE_MISSING", f"덱 파일을 읽을 수 없습니다: {exc}") from None
    prev = reusable(solve_dir, sha, stem)
    if prev is not None:
        r.echo(f"[esl-worker] OS_SOLVE 재사용: solve/solve.json 덱 sha256 {sha[:12]}… 이 같고 성공 표식이 있어 OptiStruct "
               f"를 다시 실행하지 않습니다(반복 {prev.get('iterations')}, 수렴 {prev.get('converged')})")
        return {"_skipped": True, "reused": True, "deck_sha256": sha, "seconds": prev.get("seconds"),
                "license_waits": prev.get("license_waits", 0), "iterations": prev.get("iterations"),
                "converged": prev.get("converged"), "exit_code": prev.get("exit_code"), "os_acquired": False,
                "skipped": "이전 해석 재사용(덱 sha256 동일)"}
    exe = s.altair.optistruct_path
    if not exe or not os.path.isfile(exe):
        raise SolveFailed("SOLVER_NOT_CONFIGURED", f"OptiStruct 실행 파일이 없습니다(altair.optistruct_path): {exe}")
    try:
        old = core_adapter.opt_fresh_dir(cdir, "solve", ex.lib)
    except core_adapter.CoreError as exc:
        raise SolveFailed(exc.code, exc.message) from None
    if old:
        r.echo(f"[esl-worker] 이전 solve/ 를 옮김: {old}")
    import shutil

    for name in (deck, "esl_loads.inc"):
        shutil.copyfile(os.path.join(deck_dir, name), os.path.join(solve_dir, name))
    scratch = os.path.join(solve_dir, "tmp")
    os.makedirs(scratch, exist_ok=True)
    fem = os.path.join(solve_dir, deck)
    mem_mb = str(int(float(getattr(s.worker, "per_job_memory_gb", None) or s.worker.max_memory_gb) * 1024))
    vals = {"optistruct": exe, "fem": fem, "fem_fwd": localproc.fwd(fem), "nt": str(int(cfg.get("nt") or 1)),
            "work_dir": solve_dir, "scratch": scratch, "mem_mb": mem_mb}
    try:
        argv_check = localproc.build_argv(list(s.commands.os_check), vals, exe="optistruct", what="commands.os_check")
        argv_solve = localproc.build_argv(list(s.commands.os_solve), vals, exe="optistruct", what="commands.os_solve")
    except localproc.ProcError as exc:
        raise SolveFailed(exc.code, exc.message) from None
    desmax = int(cfg.get("desmax") or 30)
    lr = cfg.get("license_retry") or {}
    lic_max, lic_wait = int(lr.get("max", 3)), float(lr.get("wait_s", 300))
    deadline = time.monotonic() + float(cfg.get("timeout_h") or 12) * 3600.0
    out_path = os.path.join(solve_dir, stem + ".out")
    t0 = time.time()
    rec: dict[str, Any] = {"deck_sha256": sha, "argv": argv_solve, "exit_code": None, "seconds": None,
                           "iterations": None, "converged": False, "license_waits": 0, "ok": False}

    def write_rec() -> None:
        rec["seconds"] = round(time.time() - t0, 3)
        rec["license_waits"] = r.out["license_waits"]
        tmp = os.path.join(solve_dir, "solve.json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(solve_dir, "solve.json"))

    osout = core_adapter.opt_osout()   # 코어 .out 해석(가벼운 순수 함수) — 판정 기준을 코어와 하나로

    try:
        r.acquire()
        r.outputs()
        r.echo(f"[esl-worker] OS_SOLVE: {deck} (DESMAX {desmax}, nt {vals['nt']}, deck sha256 {sha[:12]}…)")
        n_lic = 0
        phase = "check"
        while True:
            check = phase == "check"
            r.echo(f"[esl-worker] OptiStruct {'-check(문법 검사)' if check else '본 실행'} 시작")
            try:
                code, text = r.run_once(argv_check if check else argv_solve, solve_dir, out_path, check=check,
                                        desmax=desmax, deadline=deadline)
            except SolveFailed:
                write_rec()
                raise
            rec["exit_code"] = code
            have = True if check else all(os.path.isfile(os.path.join(solve_dir, stem + e)) for e in (".out", "_des.h3d"))
            verdict = osout.classify(code if code is not None else -1, text, cfg, have)
            if verdict == "OS_LICENSE_UNAVAILABLE":
                if n_lic >= lic_max:
                    write_rec()
                    raise SolveFailed("OS_LICENSE_UNAVAILABLE", f"OptiStruct 라이선스 부족 — {lic_max}회 × {lic_wait:g}초 "
                                      "재시도 후에도 실패했습니다(opt_run.solve.license_retry)", code)
                n_lic += 1
                r.wait_license(n_lic, lic_max, lic_wait)
                continue
            if verdict is not None:
                p = osout.parse_out(text, cfg)
                detail = "; ".join(p["errors"][:3]) or ("출력 파일(.out/_des.h3d) 없음" if not have else "")
                write_rec()
                if check and verdict != "SOLVER_OUT_OF_MEMORY":
                    raise SolveFailed("OS_DECK_INVALID", f"OptiStruct -check 실패(종료코드 {code}): {detail}"[:450], code)
                msg = {"SOLVER_OUT_OF_MEMORY": "OptiStruct 메모리 부족"}.get(verdict, "OptiStruct 실패")
                raise SolveFailed(verdict, f"{msg}(종료코드 {code}): {detail}"[:450], code)
            if check:
                r.echo("[esl-worker] -check 통과")
                r.progress(CHECK_SHARE)
                phase = "solve"
                continue
            p = osout.parse_out(text, cfg)
            rec.update(ok=True, iterations=p["last_iteration"], converged=bool(p["converged"]))
            write_rec()
            r.echo(f"[esl-worker] OptiStruct 완료: 반복 {p['last_iteration']}/{desmax}, "
                   + ("수렴" if p["converged"] else "수렴 표식 없음(최대 반복 도달 — 미수렴 경고)")
                   + f", {rec['seconds']:.1f}s, 라이선스 대기 {r.out['license_waits']}회")
            break
    finally:
        r.release()
    return {"os_acquired": False, "reused": False, "deck_sha256": sha, "seconds": rec["seconds"],
            "license_waits": r.out["license_waits"], "iterations": rec["iterations"], "converged": rec["converged"],
            "exit_code": rec["exit_code"]}
