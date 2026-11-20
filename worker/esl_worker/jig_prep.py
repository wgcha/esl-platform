"""Case ③ ESL 지그 3방식의 tie 준비(계약 esl_jig_case.md §5.1·§11, D-0.24.4-JIG-11) — 워커.

ESL_SOLVE 의 ESL step 안, 코어 자식 시작 전(v0.24.2 ``_bf_ondemand`` 다음)에 paicad ``shell fixed-scan``(대상 파트)을 Case 폴더
``01_extract/jig_fixed/`` 에 준비한다. 새 작업 유형·step 없음. 코어(``pipeline._jig_esl``)는 그 폴더와 시도 기록
``01_extract/jig_prep.json`` 을 읽어 지그 세 행을 계산(없음·실패 = 세 행 unavailable + 같은 code)한다. deck 표면 캐시
(``01_extract/jig_surf.npz``)는 코어가 만든다(§5.2 — 워커는 tie 만).

- ``DECIDE``: 판정 표(위에서 첫 일치). ``run`` 은 결과(action·cause)만 읽고 시나리오 이름으로 분기하지 않는다.
- 쓰기 = Case 폴더 안만: ``01_extract/jig_fixed``·``01_extract/jig_prep.json``·``_jig/``(작업 사본·로그). 입력·SPDM 쓰기 없음.
- 캐시 키 = starter include 트리 매니페스트(경로·크기·mtime_ns·sha256) + 파트 id + fix_kinds. 키가 같으면 fixed-scan 0회.
- 실패·시간 초과·paicad 없음 = 기록 후 ESL 계속(취소·lease 상실만 전파). 지그 끔이면 hw·fixed-scan 호출 0(기록도 없음).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import core_adapter, doe_jobs, inproc, paicad_proc

SCHEMA = "esl/jig_fixed/1"
EXTRACT = "01_extract"
FIXED_SUB = "jig_fixed"
NODES_JSON = "fixed_nodes.json"          # 캐시 키·메타(paicad 산출 shell_scan.json·fixed_nodes.npz 옆)
RECORD = "jig_prep.json"                 # <01_extract>/ 시도 기록
WORK = "_jig"                            # Case 폴더 안 작업 폴더(사본·로그·임시 출력)
ASSEM_SUB = "assem_full"
TMP_SUB = "fixed_tmp"
CODE_SKIPPED = "JIG_FIXED_SKIPPED"
CODE_FAILED = "JIG_FIXED_FAILED"
HASH_CHUNK = 1 << 20
DETAIL_MAX = 300

SKIPPED_CAUSES = ("PAICAD_UNAVAILABLE", "NO_INPUT", "SETTINGS")
FAILED_CAUSES = ("TIMEOUT", "SCAN_FAILED", "READ_FAILED", "EXCEPTION")

# 원인 → 상세 문구(기록 detail — 코어가 지그 세 행 사유로 씀) 한 곳.
CAUSE_TEXT: dict[str, str] = {
    "PAICAD_UNAVAILABLE": "paicad 를 쓸 수 없음({reason}) — bead_doe.paicad.exe 설정을 확인",
    "NO_INPUT": "tie 준비 입력을 찾지 못함({msg})",
    "SETTINGS": "지그 설정을 읽지 못함({msg})",
    "TIMEOUT": "fixed-scan 시간 초과 {timeout:g} s(bead_doe.case_jig.timeout_s·bead_doe.paicad.timeout_s.fixed_scan)",
    "SCAN_FAILED": "fixed-scan 실패({msg})",
    "READ_FAILED": "fixed-scan 결과를 읽지 못함({msg})",
    "EXCEPTION": "tie 준비 오류({msg})",
}

# ESL step 로그 문구 한 곳.
LOG: dict[str, str] = {
    "have": "[esl-worker] 지그 tie: 캐시 일치({key}) — fixed-scan 안 함(01_extract/jig_fixed)",
    "start": "[esl-worker] 지그 tie 준비 시작: 파트 {part}, 종류 {kinds}, 모델 {assem}({mode}) → {out}",
    "stage": "[esl-worker] 지그 tie 준비: include 가 Case 폴더 밖이라 모델 전체 사본 {dest} 를 만듭니다(paicad --assem-dir 는 그 아래만 읽음)",
    "retry": "[esl-worker] 지그 tie 준비: 제자리 fixed-scan 이 모델 해석 실패({code}) — 정규화한 사본으로 다시 시도",
    "ok": "[esl-worker] 지그 tie 준비 완료: 고정 노드 {n}개, {sec:.1f} s → 01_extract/jig_fixed (키 {key})",
    "failed": "[esl-worker] 지그 tie 준비 실패({cause}): {detail} — ESL 은 계속(지그 세 행 unavailable, JIG_FIXED_FAILED)",
    "skipped": "[esl-worker] 지그 tie 준비 생략({cause}): {detail} — ESL 은 계속(지그 세 행 unavailable, JIG_FIXED_SKIPPED)",
}


def detail_text(cause: str, **kw: Any) -> str:
    base = {"reason": "", "msg": "", "timeout": 0.0}
    base.update(kw)
    return CAUSE_TEXT[cause].format(**base)[:DETAIL_MAX]


# ---------------------------------------------------------------- 판정
@dataclass
class Facts:
    """판정에 쓰는 사실(호출부가 모음 — 판정은 순수). None = 알 수 없음/아직 안 구함."""

    case_enabled: bool | None = None       # bead_doe.case_jig.enabled
    core_enabled: bool | None = None       # 코어 jig.enabled
    cache_have: bool | None = None         # 01_extract/jig_fixed/fixed_nodes.json 의 키 일치
    paicad_ready: bool | None = None       # paicad 버전 점검 통과(캐시 있으면 구하지 않음 = None)
    input_error: str | None = None         # starter·파트 id·include 트리를 못 구한 사유
    settings_error: str | None = None      # 지그 설정을 못 읽은 코어 오류 code


@dataclass(frozen=True)
class Decision:
    action: str                            # none | skip | fill
    cause: str | None = None
    row: str = ""
    note: str | None = None                # none 일 때 작업 로그 키(LOG[...])


# (행, 조건, 동작, 원인, 로그 키) — 위에서부터 첫 일치.
DECIDE: tuple[tuple[str, Callable[[Facts], bool], str, str | None, str | None], ...] = (
    ("1", lambda f: f.case_enabled is False, "none", None, None),
    ("2", lambda f: f.core_enabled is False, "none", None, None),
    ("2a", lambda f: f.settings_error is not None, "skip", "SETTINGS", None),
    ("2b", lambda f: f.input_error is not None, "skip", "NO_INPUT", None),
    ("3", lambda f: f.cache_have is True, "none", None, "have"),
    ("4", lambda f: f.paicad_ready is False, "skip", "PAICAD_UNAVAILABLE", None),
    ("5", lambda f: True, "fill", None, None),
)


def decide(f: Facts) -> Decision:
    for row, pred, action, cause, note in DECIDE:
        if pred(f):
            return Decision(action, cause, row=row, note=note)
    raise AssertionError("DECIDE 마지막 행은 항상 일치")      # pragma: no cover


# ---------------------------------------------------------------- 캐시 키
def file_row(path: str, root: str) -> dict[str, Any]:
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
            h.update(chunk)
    ap = os.path.normpath(os.path.abspath(path))
    rp = os.path.normpath(os.path.abspath(root))
    inside = ap == rp or ap.startswith(rp.rstrip(os.sep) + os.sep)
    return {"path": os.path.relpath(ap, rp).replace(os.sep, "/") if inside else ap.replace(os.sep, "/"),
            "size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "sha256": h.hexdigest()}


def manifest_of(files: list[str], root: str) -> list[dict[str, Any]]:
    """include 트리 파일 매니페스트(순서 = 호출자 순서 — starter 먼저)."""
    return [file_row(f, root) for f in files]


def cache_key(manifest: list[dict[str, Any]], part_id: int, fix_kinds: list[str]) -> str:
    doc = {"schema": SCHEMA, "files": manifest, "part_id": int(part_id), "fix_kinds": sorted(str(k) for k in fix_kinds)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def fixed_dir(cdir: str) -> str:
    return os.path.join(cdir, EXTRACT, FIXED_SUB)


def has_cache(cdir: str, key: str) -> bool:
    """캐시 폴더에 키가 같은 fixed_nodes.json + paicad 산출(shell_scan.json·fixed_nodes.npz)이 모두 있나."""
    d = fixed_dir(cdir)
    try:
        with open(os.path.join(d, NODES_JSON), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return False
    return (isinstance(doc, dict) and doc.get("key") == key
            and all(os.path.isfile(os.path.join(d, n)) for n in ("shell_scan.json", "fixed_nodes.npz")))


# ---------------------------------------------------------------- 기록
def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_of(cause: str | None) -> str:
    return "ok" if cause is None else ("skipped" if cause in SKIPPED_CAUSES else "failed")


def code_of(status: str) -> str | None:
    return {"failed": CODE_FAILED, "skipped": CODE_SKIPPED}.get(status)


def attempt_record(*, job_id: str, cause: str | None, detail: str, seconds: float | None, key: str | None,
                   part_id: int | None, fix_kinds: list[str], assem: str | None, n_nodes: int | None,
                   paicad: dict | None = None) -> dict[str, Any]:
    st = status_of(cause)
    return {"schema": "esl/jig_prep/1", "job_id": job_id, "status": st, "code": code_of(st), "cause": cause,
            "detail": detail, "at": utc_now(), "seconds": None if seconds is None else round(float(seconds), 1),
            "key": key, "part_id": part_id, "fix_kinds": list(fix_kinds), "assem": assem, "n_nodes": n_nodes,
            "paicad": paicad}


def summary_of(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec.get(k) for k in ("status", "code", "cause", "detail", "seconds", "assem", "n_nodes")}


def write_record(cdir: str, rec: dict[str, Any]) -> None:
    from esl_platform.core.atomic import write_text_atomic

    d = os.path.join(cdir, EXTRACT)
    os.makedirs(d, exist_ok=True)
    write_text_atomic(os.path.join(d, RECORD), json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


# ---------------------------------------------------------------- 쓰기 경로 검사(Case 폴더 안 허용 위치만)
def make_guard(cdir: str) -> Callable[[str], str]:
    """``_jig/`` 와 ``01_extract/jig_fixed``·``01_extract/jig_prep.json`` 아래만 쓰기 허용(입력·다른 산출물 쓰기 거부)."""
    allowed = [os.path.realpath(os.path.join(cdir, WORK)), os.path.realpath(fixed_dir(cdir)),
               os.path.realpath(os.path.join(cdir, EXTRACT, RECORD))]

    def guard(p: str) -> str:
        rp = os.path.realpath(p)
        if not any(rp == a or rp.startswith(a.rstrip(os.sep) + os.sep) for a in allowed):
            raise core_adapter.CoreError("PATH_OUTSIDE_ROOT", f"지그 준비 쓰기 경로가 허용 폴더 밖입니다: {os.path.basename(p)}")
        return p
    return guard


def _within(p: str, root: str) -> bool:
    rp, rr = os.path.realpath(p), os.path.realpath(root)
    return rp == rr or rp.startswith(rr.rstrip(os.sep) + os.sep)


def _backup_move(cdir: str, rel: str) -> str | None:
    """Case 폴더 안 rel 이 있으면 ``_backup/<UTC>/<rel>`` 로 옮김(삭제 없음)."""
    p = os.path.join(cdir, *rel.split("/"))
    if not os.path.lexists(p):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    dest = os.path.join(cdir, "_backup", ts, *rel.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(p, dest)
    return dest


# ---------------------------------------------------------------- 실행(워커 executor 가 부름)
def _inputs(ex, core_settings: dict) -> dict[str, Any]:
    """starter·Case 폴더·파트 id·include 트리·매니페스트. 못 구하면 ValueError(msg)."""
    case = ex.case
    rad = case.get("rad_path")
    if not rad:
        raise ValueError("Case 입력 rad 없음")
    try:
        rad = doe_jobs.check_input_path(ex.settings, rad, "RAD")
    except doe_jobs.DomainError as exc:
        raise ValueError(f"입력 rad 를 쓸 수 없음: {exc.message}") from None
    try:
        with open(os.path.join(ex.cdir, EXTRACT, "model_meta.json"), encoding="utf-8") as fh:
            part_id = int(json.load(fh)["part_id"])
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("01_extract/model_meta.json 의 파트 id 를 읽지 못함 — ① 추출부터") from None
    cc = (core_settings or {}).get("case") or {}
    case_dir = os.path.dirname(os.path.abspath(rad))
    roots = list(doe_jobs._in_roots(ex)) + [case_dir]
    try:
        files = core_adapter.jig_model_files(rad, roots, include_path_map=cc.get("include_path_map"),
                                             max_depth=int(cc.get("rad_include_max_depth") or 8))
        man = manifest_of(files, case_dir)
    except (core_adapter.CoreError, OSError) as exc:
        raise ValueError(f"include 트리를 읽지 못함({getattr(exc, 'code', type(exc).__name__)}: "
                         f"{getattr(exc, 'message', exc)})") from None
    return {"rad": rad, "case_dir": case_dir, "part_id": part_id, "files": files, "manifest": man, "cc": cc}


def gather(ex, core_settings: dict, jcfg_out: dict) -> tuple[Facts, dict[str, Any] | None]:
    """판정 사실 모으기(DB 없음). 끔이면 입력·해시·paicad 점검을 구하지 않는다(비용 0). 반환 (Facts, 입력 묶음|None)."""
    f = Facts()
    bd = getattr(ex.settings, "bead_doe", None)
    cj = getattr(bd, "case_jig", None)
    f.case_enabled = bool(getattr(cj, "enabled", True))
    if f.case_enabled is False:
        return f, None
    try:
        jcfg = core_adapter.jig_settings(core_settings)
    except core_adapter.CoreError as exc:
        f.settings_error = f"{exc.code}: {exc.message}"[:200]
        return f, None
    jcfg_out.update(jcfg)
    f.core_enabled = bool(jcfg.get("enabled", True))
    if f.core_enabled is False:
        return f, None
    try:
        inp = _inputs(ex, core_settings)
    except ValueError as exc:
        f.input_error = str(exc)[:200]
        return f, None
    inp["key"] = cache_key(inp["manifest"], inp["part_id"], list(jcfg["fix_kinds"]))
    f.cache_have = has_cache(ex.cdir, inp["key"])
    if not f.cache_have:
        full = paicad_proc._settings_cfg(ex.settings)
        v = paicad_proc.version_check(ex.settings, full)
        f.paicad_ready = bool(v.get("ready"))
        inp["paicad"] = {k: v.get(k) for k in ("version", "ocp", "pinned", "reason", "warning")}
    return f, inp


def run(ex, st: dict[str, Any] | None, echo: Callable[[str], None]) -> dict[str, Any] | None:
    """Case ③ ESL 앞 tie 준비 1회. 반환 = step outputs 요약(끔·캐시 일치 = None). 취소·lease 상실만 전파 — 나머지는 기록 후 계속."""
    from esl_platform.core.errors import LeaseLost

    from .executor import _Canceled, _StepFailed

    if ex.case is None:
        return None
    core_settings = (ex.job["params"] or {}).get("settings") or {}
    jcfg: dict[str, Any] = {}
    facts, inp = gather(ex, core_settings, jcfg)
    dec = decide(facts)
    kinds = list(jcfg.get("fix_kinds") or [])
    if dec.action == "none":
        if dec.note == "have":
            echo(LOG["have"].format(key=(inp or {}).get("key", "")[:12]))
        return None
    key = (inp or {}).get("key")
    part_id = (inp or {}).get("part_id")
    t0 = time.time()
    cause: str | None = dec.cause
    detail = ""
    n_nodes: int | None = None
    assem_mode: str | None = None
    if dec.action == "skip":
        detail = detail_text(cause, reason=(inp or {}).get("paicad", {}).get("reason") or "paicad 점검 실패",
                             msg=facts.input_error or facts.settings_error or "")
    else:
        try:
            cause, detail, n_nodes, assem_mode = _fill(ex, inp, jcfg, echo)
        except (_Canceled, LeaseLost):
            raise
        except _StepFailed as exc:          # paicad 시작 실패(미설정·경로·메타문자) — ESL 은 계속
            cause, detail = "SCAN_FAILED", detail_text("SCAN_FAILED", msg=f"{exc.code}: {exc.message}"[:200])
        except Exception as exc:  # noqa: BLE001 - 준비 오류는 ESL 을 막지 않는다
            cause, detail = "EXCEPTION", detail_text("EXCEPTION", msg=f"{type(exc).__name__}: {exc}"[:200])
    seconds = None if dec.action == "skip" else time.time() - t0
    rec = attempt_record(job_id=ex.job["id"], cause=cause, detail=detail, seconds=seconds, key=key, part_id=part_id,
                         fix_kinds=kinds, assem=assem_mode, n_nodes=n_nodes, paicad=(inp or {}).get("paicad"))
    try:
        write_record(ex.cdir, rec)
    except OSError as exc:
        echo(f"[esl-worker] JIG_PREP_RECORD_FAILED: 지그 준비 기록을 쓰지 못함({exc})")
    if cause is None:
        echo(LOG["ok"].format(n=n_nodes, sec=seconds or 0.0, key=(key or "")[:12]))
    else:
        echo(LOG[rec["status"]].format(cause=cause, detail=detail))
    return summary_of(rec)


def _fill(ex, inp: dict[str, Any], jcfg: dict[str, Any], echo) -> tuple[str | None, str, int | None, str | None]:
    """fixed-scan 실행 1회(제자리 또는 정규화 사본). 반환 (cause|None, detail, n_nodes, assem 방식)."""
    cdir = ex.cdir
    work = os.path.join(cdir, WORK)
    guard = make_guard(cdir)
    full = paicad_proc._settings_cfg(ex.settings)
    dcfg = core_adapter.doe_settings(full)
    pc = dcfg["paicad"]
    bd = getattr(ex.settings, "bead_doe", None)
    tmo = getattr(getattr(bd, "case_jig", None), "timeout_s", None)
    cfg = full
    if tmo is not None:                                  # case_jig.timeout_s 가 null 이 아니면 fixed-scan 한도를 이 값으로
        cfg = json.loads(json.dumps(full))
        cfg.setdefault("bead_doe", {}).setdefault("paicad", {}).setdefault("timeout_s", {})["fixed_scan"] = float(tmo)
    limit = float(((cfg.get("bead_doe") or {}).get("paicad") or {}).get("timeout_s", {}).get("fixed_scan") or 3600)
    os.makedirs(work, exist_ok=True)
    opts = None
    if pc.get("options"):
        opts = os.path.join(work, "paicad_options.json")
        core_json_write(opts, pc["options"])
    threads = int(pc["threads"])
    tmp_out = os.path.join(work, TMP_SUB)
    if os.path.lexists(tmp_out):
        shutil.rmtree(guard(tmp_out))                   # 이전 시도 임시 출력(파생물 — 성공분만 최종 폴더로 옮김)
    pio = core_adapter.doe_paicad_io()
    tick = doe_jobs._tick(ex)
    parts = pio.parts_arg([inp["part_id"]])
    kinds = list(jcfg.get("fix_kinds") or [])
    inplace = all(_within(f, inp["case_dir"]) for f in inp["files"])

    def scan(assem_dir: str, label: str) -> dict[str, Any]:
        if os.path.lexists(tmp_out):
            shutil.rmtree(guard(tmp_out))
        os.makedirs(guard(tmp_out))                     # 스터디 BD_GEOM 의 fresh_dir 와 같이 빈 출력 폴더를 미리 만들어 줌
        return doe_jobs._fixed_scan(ex, None, assem_dir=assem_dir, parts=parts, out_dir=tmp_out, cwd=work,
                                    capture=os.path.join(work, "fixed_scan.stdout.log"), opts=opts, threads=threads,
                                    echo=echo, tick=tick, label=label, cfg=cfg)

    def stage() -> str:
        dest_dir = os.path.join(work, ASSEM_SUB)
        if os.path.lexists(dest_dir):
            shutil.rmtree(guard(dest_dir))              # 이전 사본(파생물 — 같은 Case 에서 다시 만들 수 있음)
        echo(LOG["stage"].format(dest=os.path.relpath(dest_dir, cdir)))
        d, _man = doe_jobs._stage_full(ex, inp["rad"], inp["case_dir"], ASSEM_SUB, echo, label="지그 ", out=work,
                                       guard=guard, man_path=os.path.join(work, ASSEM_SUB + ".json"), dcfg=dcfg,
                                       cc=inp["cc"])
        return d

    mode = "in_place" if inplace else "staged"
    assem = inp["case_dir"] if inplace else stage()
    echo(LOG["start"].format(part=inp["part_id"], kinds=",".join(kinds), assem=os.path.relpath(assem, cdir)
                             if _within(assem, cdir) else assem, mode=mode, out=os.path.join(EXTRACT, FIXED_SUB)))
    if inplace:
        doe_jobs.inproc.call(ex, lambda: core_adapter.doe_assem_check(assem, float(dcfg["same"]["max_assem_mb"])),
                             label="지그 입력 폴더 검사")
    r = scan(assem, "지그 fixed-scan ")
    if not r["ok"] and inplace and r.get("code") == "FIXED_PARSE_FAILED":
        echo(LOG["retry"].format(code=r["code"]))      # 제자리 = 정규화 안 한 원본 — 사본(스캔 정규화)로 한 번 더
        assem = stage()
        mode = "staged"
        r = scan(assem, "지그 fixed-scan(사본) ")
    if not r["ok"]:
        if r.get("timeout"):
            return "TIMEOUT", detail_text("TIMEOUT", timeout=limit), None, mode
        msg = f"{r.get('message') or r.get('code')}: paicad {r.get('paicad_code') or '-'}, 종료 {r.get('exit_code')}"
        if r.get("detail"):
            msg += f" — {r['detail']}"
        return "SCAN_FAILED", detail_text("SCAN_FAILED", msg=msg[:240]), None, mode
    try:
        summ = core_adapter.fixed_scan_summary(tmp_out, float((dcfg.get("limits") or {}).get("max_json_mb") or 64))
    except core_adapter.CoreError as exc:
        return "READ_FAILED", detail_text("READ_FAILED", msg=f"{exc.code}: {exc.message}"[:240]), None, mode
    # 성공분만 최종 위치로(이전 캐시는 _backup 으로 옮김 — 삭제 없음), 키·메타 기록
    prev = _backup_move(cdir, f"{EXTRACT}/{FIXED_SUB}")
    if prev:
        echo(f"[esl-worker] 이전 지그 tie 캐시를 옮김: {prev}")
    final = fixed_dir(cdir)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    shutil.move(tmp_out, final)
    meta = {"schema": SCHEMA, "key": inp["key"], "part_id": inp["part_id"], "fix_kinds": sorted(kinds),
            "n_files": len(inp["manifest"]), "assem": mode, "n_nodes": summ["n_nodes"], "n_clusters": summ["n_clusters"],
            "kinds": summ["kinds"], "job_id": ex.job["id"], "at": utc_now()}
    core_json_write(os.path.join(final, NODES_JSON), meta)
    return None, "", summ["n_nodes"], mode


def core_json_write(path: str, obj: Any) -> None:
    from esl_platform.core.atomic import write_text_atomic

    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
