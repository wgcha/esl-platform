"""강성 평가 스터디 select — 비드 직접 선택(계약 esl_bead_select.md §4·§9, v0.15.0): 선택 보기 파일, derive(저장 안 함),
선택 조회·저장(낙관적 잠금 version), 변수 표(선택 → DOE 변수), 평면도(select 판), 기저 파일.

경계(§17): 코어 ``esl.doe.bead_select`` 의 ``normalize``·``derive``·``plan_data`` 만 쓴다(어댑터 ``core.opt_core``). 기저·모핑·
품질·렌더는 워커 몫. 백엔드는 ``_doe/<id>/`` 에 파일을 쓰지 않는다(DB ``bead_does.selection`` 이 선택 원본, BS-D-4).

코어 함수(S1 구현, 이 파일이 기대하는 시그니처)::

    normalize(selection: dict, cfg: dict, *, mesh: dict | None = None) -> tuple[dict, str]
        SelectionIn(API 모델 dump) → (정규화 SelectionIn — 구간 병합·정렬·기본값 채움, sha256(정렬 키 JSON)).
        cfg = bead_doe 설정 dict(cfg["select"]). mesh(MESH_KEYS) 를 주면 요소 ID 존재 검사.
        실패 = EslError(code ∈ SELECT_OVERLAP·SELECT_ELEM_UNKNOWN·SELECT_EMPTY_TIER·SELECT_TIERS_GAP·SELECT_LINK_INVALID·
        SELECT_BEAD_ID_INVALID·SELECT_NAME_INVALID·SELECT_TOO_LARGE), 세부 값은 선택 속성 ``exc.extra``(dict).
    derive(mesh: dict, selection: dict, cfg: dict, *, frame: dict, fixed_scan: np.ndarray, bead: str | None = None) -> dict
        정규화 선택 → {beads: [BeadDerived §4.2 — section·plan 포함], fixed: {scan_n, user_n, source}, warnings: [...],
        slope_suggested: {bead id: ElemSet}} (rev·sha256·mesh_sha256 은 이 파일이 붙인다). 결정적. bead 주면 그 비드만.
    plan_data(mesh: dict, selection: dict, derived: dict, cfg: dict, *, frame: dict) -> dict
        §7.1 평면도 select 판 {frame, outline, holes, elems, beads[{id, name, ring_ab, e_ab, label_ab, tiers, section}],
        fixed[{a, b}], nodes_ab, warnings} (DoePlanOut 키).

입력 = 준비 산출물 ``prep/base_mesh.npz``·``base.json``(``esl.doe.scenario.load_base``) + ``prep/fixed/``(paicad fixed-scan,
있으면 ``paicad_io.read_fixed`` — 없으면 빈 고정, BS-D-8).

DB ``bead_does.selection`` = {rev, sha256, mesh_sha256, input(정규화 SelectionIn), derived(요약 — 비드의 section·plan 제외),
updated_by_name, updated_at}. 그림 자료(section·plan)는 프로세스 메모리 LRU(키 = (sha256, mesh_sha256, bead),
``select.derive_cache_n``)에 두고, 없으면 다시 계산한다(≤ 3 s).

작업 params(DOE_PREVIEW·DOE_RUN, 워커 S3): ``doe.selection = {rev, sha256, mesh_sha256, input, params}`` — params = 이 파일
``params_table`` 의 DOE 변수 표(행렬 생성과 같은 표 → 같은 matrix_sha256).
"""

from __future__ import annotations

import collections
import concurrent.futures
import copy
import datetime as _dt
import hashlib
import json
import os
import re
import threading
from typing import Any

from ...core.auth import Principal
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.paths import safe_case_file
from ...core.repositories import doe as doe_repo
from ..context import AppContext
from .common import require_config_ok, require_execute

SELECT_VIEW_FILES = {"part.glb": "model/gltf-binary", "select.bin": "application/octet-stream",
                     "select_manifest.json": "application/json"}
_SHA12_RE = re.compile(r"[0-9a-f]{12}")
BASIS_FILES = {"bin": ("basis.bin", "application/octet-stream"), "meta": ("basis.json", "application/json")}
SUMMARY_DROP = ("section", "plan")            # DB 요약에서 빼는 그림 자료(§4.3)
_LOAD_N = 2


# ---------------------------------------------------------------- 공통
def _svc():
    from . import doe as svc

    return svc


def _bs():
    """코어 esl.doe.bead_select(S1). 없으면 503 SELECT_DISABLED(배포 누락)."""
    from ...core import opt_core

    try:
        return opt_core.doe_bead_select
    except ImportError:
        raise DomainError("SELECT_DISABLED", "비드 직접 선택 코어(esl.doe.bead_select)가 설치되지 않았습니다(관리자 문의)",
                          status=503) from None


def scfg(c: dict[str, Any]) -> dict[str, Any]:
    return c["select"]


def sel_error(exc) -> DomainError:
    """코어 EslError → API 오류(§14): SELECT_TOO_LARGE 413, SELECT_DERIVE_TIMEOUT 503, 그 밖 422."""
    code = str(getattr(exc, "code", "") or "SELECT_INVALID")
    extra = getattr(exc, "extra", None)
    extra = dict(extra) if isinstance(extra, dict) else {}
    extra = {k: v for k, v in extra.items() if k not in ("code", "message", "status")}
    status = 413 if code == "SELECT_TOO_LARGE" else 503 if code == "SELECT_DERIVE_TIMEOUT" else 422
    if not code.startswith("SELECT_"):
        code = "SELECT_INVALID"
    return DomainError(code, str(getattr(exc, "message", "") or exc), status=status, **_svc()._jsonable(extra))


def require_select(s: dict[str, Any]) -> None:
    if s.get("scenario") != "select":
        raise conflict("SCENARIO_UNSUPPORTED", "비드 직접 선택(select) 스터디에서만 쓸 수 있습니다", scenario=s.get("scenario"))


def _prep_dir(ctx: AppContext, s: dict[str, Any]) -> str:
    return os.path.join(_svc().study_dir(ctx, s), "prep")


# ---------------------------------------------------------------- 준비 산출물 읽기(기준 메시·고정 노드)
_LOAD_CACHE: "collections.OrderedDict[tuple, dict[str, Any]]" = collections.OrderedDict()
_LOAD_LOCK = threading.Lock()


def load_inputs(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """{mesh, frame, mesh_sha256, fixed_scan(node_id int64)} — prep/base_mesh.npz·base.json + prep/fixed/. 없으면 409."""
    import numpy as np

    from ...core.opt_core import EslError
    from ...core.opt_core import doe_paicad_io as pio
    from ...core.opt_core import doe_scenario

    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    pd = _prep_dir(ctx, s)
    npz = os.path.join(pd, doe_scenario.BASE_NPZ)
    try:
        st = os.stat(npz)
    except OSError:
        raise conflict("PREP_NOT_READY", "준비 결과(prep/base_mesh.npz)가 없습니다") from None
    if os.path.islink(npz):
        raise conflict("PREP_NOT_READY", "준비 결과(prep/base_mesh.npz)가 없습니다")
    fdir = os.path.join(pd, "fixed")
    try:
        fst = os.stat(os.path.join(fdir, pio.FIXED_NPZ))
        fkey = (fst.st_mtime_ns, fst.st_size)
    except (OSError, AttributeError):
        fkey = None
    key = (os.path.realpath(npz), st.st_mtime_ns, st.st_size, fkey)
    with _LOAD_LOCK:
        hit = _LOAD_CACHE.get(key)
        if hit is not None:
            _LOAD_CACHE.move_to_end(key)
            return hit
    try:
        t, meta = doe_scenario.load_base(pd)
    except (EslError, OSError, KeyError, ValueError):
        raise conflict("PREP_NOT_READY", "준비 결과(기준 메시)를 읽지 못했습니다") from None
    fixed = np.zeros(0, dtype=np.int64)
    if os.path.isdir(fdir) and not os.path.islink(fdir):
        try:
            fixed = np.asarray(pio.read_fixed(fdir, _svc()._max_mb(c))["node_id"], dtype=np.int64)
        except (EslError, OSError, KeyError, ValueError):
            fixed = np.zeros(0, dtype=np.int64)            # fixed-scan 실패 = 고정 없음(FIXED_INFO_MISSING 는 준비 경고)
    out = {"mesh": t.mesh, "frame": dict(t.frame or meta.get("frame") or {}), "mesh_sha256": meta.get("mesh_sha256"),
           "fixed_scan": fixed}
    with _LOAD_LOCK:
        _LOAD_CACHE[key] = out
        while len(_LOAD_CACHE) > _LOAD_N:
            _LOAD_CACHE.popitem(last=False)
    return out


def prep_mesh_sha(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> str | None:
    """준비된 기준 메시 sha(prep/base.json — 메시를 읽지 않음). 없으면 None."""
    meta = _svc()._read_json(os.path.join(_prep_dir(ctx, s), "base.json"), _svc()._max_mb(c))
    v = meta.get("mesh_sha256") if isinstance(meta, dict) else None
    return v if isinstance(v, str) else None


# ---------------------------------------------------------------- 정규화·derive(캐시·시간 상한)
_DERIVE_CACHE: "collections.OrderedDict[tuple, dict[str, Any]]" = collections.OrderedDict()
_DERIVE_LOCK = threading.Lock()
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="esl-select-derive")


def reset_caches() -> None:
    with _DERIVE_LOCK:
        _DERIVE_CACHE.clear()
    with _LOAD_LOCK:
        _LOAD_CACHE.clear()


def canonical_bytes(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def normalize(c: dict[str, Any], selection: dict[str, Any], mesh: dict | None) -> tuple[dict[str, Any], str]:
    """코어 normalize + 크기 상한(정규화 JSON > select.max_selection_kb → 413 SELECT_TOO_LARGE, BS-D-4)."""
    from ...core.opt_core import EslError

    limit = float(scfg(c)["max_selection_kb"]) * 1024
    if len(canonical_bytes(selection)) > limit * 4:        # 정규화 전 터무니없이 큰 본문은 코어에 넘기지 않음
        raise DomainError("SELECT_TOO_LARGE", f"선택 자료가 상한 {scfg(c)['max_selection_kb']:g} KB 를 넘습니다", status=413,
                          limit_kb=float(scfg(c)["max_selection_kb"]))
    try:
        norm, sha = _bs().normalize(selection, c, mesh=mesh)
    except EslError as exc:
        raise sel_error(exc) from None
    size = len(canonical_bytes(norm))
    if size > limit:
        raise DomainError("SELECT_TOO_LARGE", f"선택 자료 {size / 1024:.0f} KB > 상한 {scfg(c)['max_selection_kb']:g} KB "
                          "(bead_doe.select.max_selection_kb)", status=413, size_kb=round(size / 1024, 1),
                          limit_kb=float(scfg(c)["max_selection_kb"]))
    return norm, str(sha)


def derive(c: dict[str, Any], inputs: dict[str, Any], norm: dict[str, Any], sha: str,
           bead: str | None = None) -> dict[str, Any]:
    """코어 derive(백엔드 동기, ≤ select.derive_timeout_s — 넘으면 503 SELECT_DERIVE_TIMEOUT) + sha·mesh_sha. 캐시."""
    from ...core.opt_core import EslError

    sc = scfg(c)
    n = int(sc["derive_cache_n"])
    key = (sha, inputs.get("mesh_sha256"), bead)
    if n > 0:
        with _DERIVE_LOCK:
            hit = _DERIVE_CACHE.get(key)
            if hit is not None:
                _DERIVE_CACHE.move_to_end(key)
                return copy.deepcopy(hit)
    bs = _bs()
    fut = _POOL.submit(bs.derive, inputs["mesh"], norm, c, frame=inputs["frame"], fixed_scan=inputs["fixed_scan"],
                       bead=bead)
    try:
        r = fut.result(timeout=float(sc["derive_timeout_s"]))
    except concurrent.futures.TimeoutError:
        raise DomainError("SELECT_DERIVE_TIMEOUT", f"사면·경계 계산이 {float(sc['derive_timeout_s']):g} 초를 넘었습니다 — 비드별로 "
                          "나눠 계산하거나 선택을 줄이세요", status=503) from None
    except EslError as exc:
        raise sel_error(exc) from None
    if not isinstance(r, dict) or not isinstance(r.get("beads"), list):
        raise DomainError("SELECT_DERIVE_FAILED", "사면·경계 계산 결과 형식이 잘못되었습니다", status=500)
    out = _svc()._jsonable({**r, "sha256": sha, "mesh_sha256": inputs.get("mesh_sha256")})
    out.setdefault("fixed", {"scan_n": 0, "user_n": 0, "source": "none"})
    out.setdefault("warnings", [])
    if n > 0:
        with _DERIVE_LOCK:
            _DERIVE_CACHE[key] = copy.deepcopy(out)
            while len(_DERIVE_CACHE) > n:
                _DERIVE_CACHE.popitem(last=False)
    return out


def summary(derived: dict[str, Any]) -> dict[str, Any]:
    """DB 요약: 비드의 section·plan(그림 자료)과 slope_suggested 제외."""
    d = {k: copy.deepcopy(v) for k, v in derived.items() if k != "slope_suggested"}
    d["beads"] = [{k: v for k, v in b.items() if k not in SUMMARY_DROP} for b in d.get("beads") or []
                  if isinstance(b, dict)]
    return d


# ---------------------------------------------------------------- 현재 선택(DB)
def current(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any] | None:
    """유효한 저장 선택 또는 None. 준비 메시 sha 가 선택의 mesh_sha256 과 다르면(복제 뒤 Case 메시 변경) None(BS 복제 규칙)."""
    doc = s.get("selection")
    if not isinstance(doc, dict) or not isinstance(doc.get("input"), dict) or not doc.get("sha256"):
        return None
    ms = prep_mesh_sha(ctx, s, c)
    if ms is not None and doc.get("mesh_sha256") and doc["mesh_sha256"] != ms:
        return None
    return doc


def require_selection(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    doc = current(ctx, s, c)
    if doc is None:
        dropped = isinstance(s.get("selection"), dict)
        raise conflict("SELECTION_MISSING", "비드 선택을 저장한 뒤에 하세요" + (" — 기준 메시가 바뀌어 저장된 선택을 쓸 수 없습니다"
                                                                  if dropped else ""),
                       **({"reason": "SELECTION_DROPPED"} if dropped else {}))
    return doc


def selection_summary(s: dict[str, Any]) -> dict[str, Any] | None:
    """DoeStudyOut.selection(목록·상세 공통, 파일 읽기 없음)."""
    doc = s.get("selection")
    if s.get("scenario") != "select" or not isinstance(doc, dict):
        return None
    d = doc.get("derived") or {}
    n_w = len(d.get("warnings") or []) + sum(len(b.get("warnings") or []) for b in d.get("beads") or [] if isinstance(b, dict))
    return {"rev": int(doc.get("rev") or 0), "sha256": doc.get("sha256"), "mesh_sha256": doc.get("mesh_sha256"),
            "n_beads": len((doc.get("input") or {}).get("beads") or []), "n_warnings": n_w,
            "updated_by_name": doc.get("updated_by_name"), "updated_at": doc.get("updated_at")}


def full_derived(ctx: AppContext, s: dict[str, Any], c: dict[str, Any], doc: dict[str, Any],
                 inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """저장 선택의 전체 derive(그림 자료 포함) — 캐시 또는 재계산."""
    inputs = inputs or load_inputs(ctx, s, c)
    d = derive(c, inputs, doc["input"], doc["sha256"])
    d["rev"] = int(doc.get("rev") or 0)
    return d


# ---------------------------------------------------------------- DOE 변수 표(선택 → 변수, §9 params)
def _pair(v: Any) -> list[float] | None:
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return [float(v[0]), float(v[1])]
    return None


def _code(w: Any) -> str | None:
    return w.get("code") if isinstance(w, dict) else None


def params_table(doc: dict[str, Any]) -> dict[str, Any]:
    """{beads, params, warnings} (DoeParamsOut select 판). 변수 이름 <비드 id 대문자>_D<k>·_W(예 B1_D2), 묶음 대표 = 가장 작은 k.

    - D: 단마다(묶음은 1개, group_members = 묶인 단 이름). W: 비드마다, 경계 고리가 모두 닫혔을 때만(SELECT_OPEN_BOUNDARY 면 없음).
    - SELECT_FIXED_IN_BEAD{tiers} → 그 단 D·그 비드 W 기본 체크 해제(tiers 없으면 비드 전체, §5.6).
    - feasible = default_range = derive range_default(source estimate, §5.7). 범위가 없으면 [공칭, 공칭](사용자 입력 필요)."""
    inp = {str(b.get("id")): b for b in (doc.get("input") or {}).get("beads") or [] if isinstance(b, dict)}
    d = doc.get("derived") or {}
    beads, params = [], []
    for bd in d.get("beads") or []:
        if not isinstance(bd, dict) or "id" not in bd:
            continue
        bid = str(bd["id"])
        pref = bid.upper()
        links = [sorted({int(k) for k in g}) for g in (inp.get(bid) or {}).get("links") or [] if g]
        rep: dict[int, int] = {}
        for g in links:
            for k in g:
                rep[k] = g[0]
        warns = [w for w in bd.get("warnings") or [] if isinstance(w, dict)]
        fixed_all, fixed_tiers = False, set()
        for w in warns:
            if _code(w) == "SELECT_FIXED_IN_BEAD":
                ts = w.get("tiers")
                if isinstance(ts, list) and ts:
                    fixed_tiers |= {int(t) for t in ts}
                else:
                    fixed_all = True
        rd = bd.get("range_default") or {}
        rdD = rd.get("D") or {}
        tiers = sorted((t for t in bd.get("tiers") or [] if isinstance(t, dict) and "k" in t), key=lambda t: int(t["k"]))
        ks = [int(t["k"]) for t in tiers]
        for t in tiers:
            k = int(t["k"])
            if rep.get(k, k) != k:
                continue
            members = [kk for kk in ks if rep.get(kk, kk) == k]
            nom = float(t.get("D_nom") or 0.0)
            fe = _pair(rdD.get(str(k), rdD.get(k) if isinstance(rdD, dict) else None)) or [nom, nom]
            params.append({"name": f"{pref}_D{k}", "type": "D", "bead": bid, "tier": k, "nominal": nom, "feasible": fe,
                           "feasible_source": "estimate", "default_range": list(fe),
                           "use_default": not (fixed_all or any(kk in fixed_tiers for kk in members)),
                           "group_members": [f"{pref}_D{kk}" for kk in members]})
        loops = ((bd.get("boundary") or {}).get("loops")) or []
        open_b = any(isinstance(lp, dict) and not lp.get("closed") for lp in loops) or \
            any(_code(w) == "SELECT_OPEN_BOUNDARY" for w in warns)
        if not open_b and isinstance(bd.get("W_nom"), (int, float)):
            nom = float(bd["W_nom"])
            fe = _pair(rd.get("W")) or [nom, nom]
            params.append({"name": f"{pref}_W", "type": "W", "bead": bid, "tier": None, "nominal": nom, "feasible": fe,
                           "feasible_source": "estimate", "default_range": list(fe),
                           "use_default": not (fixed_all or fixed_tiers), "group_members": [f"{pref}_W"]})
        beads.append({"id": bid, "name": str(bd.get("name") or (inp.get(bid) or {}).get("name") or pref), "kind": "select",
                      "n_tiers": len(tiers), "W_nom": bd.get("W_nom"), "W_min": bd.get("W_min"), "W_max": bd.get("W_max"),
                      "blend_mm": bd.get("blend_mm"), "warnings": warns})
    return _svc()._jsonable({"beads": beads, "params": params,
                             "warnings": [w for w in d.get("warnings") or [] if isinstance(w, dict)]})


def job_selection(doc: dict[str, Any]) -> dict[str, Any]:
    """작업 params.doe.selection(워커 S3: 기저·모핑·이어하기 sha)."""
    return {"rev": int(doc.get("rev") or 0), "sha256": doc["sha256"], "mesh_sha256": doc.get("mesh_sha256"),
            "input": copy.deepcopy(doc["input"]), "params": params_table(doc)["params"]}


# ---------------------------------------------------------------- 엔드포인트
def _load_viewable(ctx: AppContext, principal: Principal, sid: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    s, job = _svc()._viewable(ctx, principal, sid)
    require_select(s)
    return s, job


def view_file(ctx: AppContext, principal: Principal, sid: str, name: str) -> tuple[str, str, str | None]:
    """GET …/select/view/{file}: prep/select/ 의 허용 파일만(경로 탈출·링크 거부). (경로, media, ETag)."""
    if name not in SELECT_VIEW_FILES:
        raise not_found("FILE_NOT_FOUND", "선택 보기 파일이 없습니다")
    c = _svc().cfg(ctx)
    s, _job = _load_viewable(ctx, principal, sid)
    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    base = os.path.join(_prep_dir(ctx, s), "select")
    p = safe_case_file(base, name)
    if not os.path.isfile(p) or os.path.islink(p) or os.path.islink(base):
        raise not_found("FILE_NOT_FOUND", "선택 보기 파일이 없습니다")
    man = _svc()._read_json(os.path.join(base, "select_manifest.json"), _svc()._max_mb(c))
    etag = man.get("mesh_sha256") if isinstance(man, dict) and isinstance(man.get("mesh_sha256"), str) else None
    return p, SELECT_VIEW_FILES[name], etag


def _editable_prechecks(ctx: AppContext, principal: Principal, sid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    svc = _svc()
    c = svc.cfg(ctx)
    with ctx.engine.connect() as conn:
        s = svc.load_study(conn, sid)
    require_execute(principal, s["project_id"])
    require_select(s)
    require_config_ok(ctx)
    svc.require_enabled(ctx, "select")
    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    return s, c


def derive_out(ctx: AppContext, principal: Principal, sid: str, body) -> dict[str, Any]:
    """POST …/select/derive: 저장 안 함(rev null). bead 주면 그 비드만."""
    s, c = _editable_prechecks(ctx, principal, sid)
    inputs = load_inputs(ctx, s, c)
    norm, sha = normalize(c, body.selection.model_dump(), inputs["mesh"])
    if body.bead is not None and body.bead not in {str(b.get("id")) for b in norm.get("beads") or []}:
        raise unprocessable("SELECT_BEAD_ID_INVALID", f"선택에 없는 비드입니다: {body.bead!r}", bead=body.bead)
    d = derive(c, inputs, norm, sha, bead=body.bead)
    d["rev"] = None
    d.setdefault("slope_suggested", {})
    return d


def selection_get(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any] | None:
    c = _svc().cfg(ctx)
    s, _job = _load_viewable(ctx, principal, sid)
    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    doc = current(ctx, s, c)
    if doc is None:
        return None
    try:
        derived = full_derived(ctx, s, c, doc)
    except DomainError:
        derived = {**(doc.get("derived") or {}), "rev": int(doc.get("rev") or 0)}     # 그림 자료 없이 요약만
    derived.pop("slope_suggested", None)
    return {"rev": int(doc["rev"]), "sha256": doc["sha256"], "input": doc["input"], "derived": derived,
            "updated_by_name": doc.get("updated_by_name") or "", "updated_at": str(doc.get("updated_at") or "")}


def selection_put(ctx: AppContext, principal: Principal, sid: str, body) -> dict[str, Any]:
    """PUT …/selection: 서버 재계산·검증 → 저장(rev + 1, version + 1). READY·PREVIEW_READY 에서만(BS-D-3)."""
    svc = _svc()
    s0, c = _editable_prechecks(ctx, principal, sid)
    inputs = load_inputs(ctx, s0, c)
    norm, sha = normalize(c, body.selection.model_dump(), inputs["mesh"])
    derived = derive(c, inputs, norm, sha)
    with ctx.engine.begin() as conn:
        s, job = svc._lock(conn, sid, body.version)
        if job is not None and job["state"] not in svc.TERMINAL:
            raise conflict("JOB_ACTIVE", "이 강성 평가 스터디의 작업이 대기 중이거나 실행 중입니다")
        if s.get("run") is not None or s["phase"] in ("RUN", "DONE"):
            raise conflict("ALREADY_RUN", "이미 실행한 연구입니다 — 선택을 바꾸려면 복제하세요")
        if svc._derived_phase(s, job) not in ("READY", "PREVIEW_READY") or s.get("prep") is None:
            raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
        old = s.get("selection") if isinstance(s.get("selection"), dict) else {}
        doc = {"rev": int(old.get("rev") or 0) + 1, "sha256": sha, "mesh_sha256": inputs.get("mesh_sha256"),
               "input": norm, "derived": summary({**derived, "rev": int(old.get("rev") or 0) + 1}),
               "updated_by_name": principal.display_name,
               "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
        s = doe_repo.update_study(conn, sid, selection=svc._jsonable(doc))
        return svc.study_out(ctx, conn, s, job, c=c)


def plan_view(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any]:
    """GET …/plan-view (select): prep/plan.json(있으면) 위에 코어 plan_data(§7.1)."""
    from ...core.opt_core import EslError

    svc = _svc()
    c = svc.cfg(ctx)
    s, _job = _load_viewable(ctx, principal, sid)
    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    doc = require_selection(ctx, s, c)
    inputs = load_inputs(ctx, s, c)
    derived = full_derived(ctx, s, c, doc, inputs)
    try:
        pd = _bs().plan_data(inputs["mesh"], doc["input"], derived, c, frame=inputs["frame"])
    except EslError as exc:
        raise sel_error(exc) from None
    base = svc._read_json(os.path.join(_prep_dir(ctx, s), "plan.json"), svc._max_mb(c))
    p = {**(base if isinstance(base, dict) else {}), **svc._jsonable(pd)}
    if "frame" not in p:
        raise conflict("PREP_NOT_READY", "평면도 자료가 없습니다")
    limit = int(ctx.settings.view3d.max_nodes)
    n = (p.get("elems") or {}).get("n_total")
    if isinstance(n, int) and n > limit:
        raise DomainError("PLAN_VIEW_TOO_LARGE", f"요소 {n} > 상한 {limit}", status=413)
    p["links"] = svc._link_coords(p)
    p["warnings"] = [w if isinstance(w, str) else str(_code(w) or w) for w in p.get("warnings") or []]
    return p


def basis_file(ctx: AppContext, principal: Principal, sid: str, rev: int | None, meta: bool) -> tuple[str, str, dict]:
    """GET …/select/basis: 미리보기한 선택 sha 의 기저(select/<sha12>/basis.bin | basis.json). 없으면 409 PREVIEW_NOT_READY."""
    svc = _svc()
    c = svc.cfg(ctx)
    s, _job = _load_viewable(ctx, principal, sid)
    doe = s.get("doe") or {}
    pv = doe.get("preview") if isinstance(doe.get("preview"), dict) else None
    sha = (pv or {}).get("selection_sha256") or (doe.get("selection_sha256") if pv else None)
    if not pv or not isinstance(sha, str) or len(sha) < 12:
        raise conflict("PREVIEW_NOT_READY", "기저가 없습니다 — 미리보기를 먼저 하세요")
    if not _SHA12_RE.fullmatch(sha[:12]):                # 폴더 이름 select/<sha12> — 16진수 12자리만(경로 조각 거부)
        raise not_found("FILE_NOT_FOUND", "기저 파일이 없습니다(선택 sha 형식이 아님)")
    doc = current(ctx, s, c)
    if rev is not None and (doc is None or int(doc.get("rev") or 0) != int(rev) or doc.get("sha256") != sha):
        raise not_found("FILE_NOT_FOUND", "그 선택 rev 의 기저가 없습니다(선택이 바뀌었으면 다시 미리보기)")
    name, media = BASIS_FILES["meta" if meta else "bin"]
    d = safe_case_file(svc.study_dir(ctx, s), f"select/{sha[:12]}")
    p = os.path.join(d, name)
    if os.path.islink(d) or not os.path.isfile(p) or os.path.islink(p):
        raise not_found("FILE_NOT_FOUND", "기저 파일이 없습니다")
    bj = svc._read_json(os.path.join(d, "basis.json"), svc._max_mb(c))
    bsha = bj.get("sha256") if isinstance(bj, dict) and isinstance(bj.get("sha256"), str) else None
    if bsha is None:
        h = hashlib.sha256()
        with open(os.path.join(d, "basis.bin") if os.path.isfile(os.path.join(d, "basis.bin")) else p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        bsha = h.hexdigest()
    return p, media, {"X-ESL-Basis-Sha": bsha, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


def clone_selection(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> tuple[dict[str, Any] | None, list]:
    """복제: 원 선택이 원 준비 메시와 맞으면 rev 1 로 복사(같은 sha), 아니면 선택 없이 + 경고 SELECTION_DROPPED.
    새 연구 준비 메시가 다르면 이후 사용 시 current() 가 None(SELECTION_MISSING reason SELECTION_DROPPED)."""
    doc = s.get("selection")
    if s.get("scenario") != "select" or not isinstance(doc, dict):
        return None, []
    if current(ctx, s, c) is None:
        return None, [{"code": "SELECTION_DROPPED", "message": "원 스터디의 비드 선택이 기준 메시와 맞지 않아 복사하지 않았습니다"}]
    new = copy.deepcopy(doc)
    new["rev"] = 1
    if isinstance(new.get("derived"), dict):
        new["derived"]["rev"] = 1
    return new, []


__all__ = ["view_file", "derive_out", "selection_get", "selection_put", "plan_view", "basis_file", "params_table",
           "job_selection", "current", "require_selection", "selection_summary", "clone_selection", "reset_caches"]
