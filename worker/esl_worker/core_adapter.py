"""코어(`esl`) 호출 어댑터 — 플랫폼에서 코어를 부르는 **유일한** 곳.

- 계산은 `esl.pipeline.run(...)` 단일 진입점(계약 esl_platform_p1b.md §2). 코어 시그니처가 바뀌는 중일 수 있어
  `inspect.signature`로 받는 인자만 골라 넘긴다(설정은 `cfg=`(dict) 또는 `config_path_or_dict`/`config_path`).
- 동기 API(지지점 제안·저장, 경로 확인)에 필요한 소규모 보조 함수(`list_parts`, `scan_includes`,
  `pca_corners`, `pick_321`, 설정 검증, `/status` 용 솔버 백엔드 조회)도 여기서만 import 한다. 없으면 `CoreUnavailable`.
- 코어 오류(`esl.errors.EslError`)는 `CoreError(code, message)`로 바꿔 플랫폼 코드가 코어 예외 타입에 묶이지 않게 한다.
- P2(계약 esl_p2_library.md §7·§11) 예외 목록 확장: Case 보고서는 `esl.pipeline.run(stage="report")`(기존 진입점).
  전 요소 비교 API 용 `esl.report.field`(downsample·section·normalize·histogram·REASONS), 라이브러리
  `esl.library`(settings·entry·analysis·optdeck·report_analysis·scene_meta·_util.Writer, cli.reference_compliance)
  — 라이브러리 코어에는 플랫폼용 단일 진입점이 없어(파일 색인 기반 CLI) 등록·분석·덱·보고서 순서 조립을 여기서 한다.
"""

from __future__ import annotations

import copy
import importlib
import inspect
from collections.abc import Callable
from typing import Any

DEFAULT_STAGES = ("extract", "tstar", "esl", "validate", "export")


class CoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class CoreUnavailable(CoreError):
    def __init__(self, what: str) -> None:
        super().__init__("CORE_UNAVAILABLE", f"코어 기능을 찾을 수 없습니다: {what}")


def _mod(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:  # pragma: no cover - 배포 오류
        raise CoreUnavailable(f"{name} ({exc})") from None


def _attr(module: str, name: str):
    m = _mod(module)
    fn = getattr(m, name, None)
    if fn is None:
        raise CoreUnavailable(f"{module}.{name}")
    return fn


def _esl_error_type():
    try:
        return importlib.import_module("esl.errors").EslError
    except (ImportError, AttributeError):  # pragma: no cover
        return ()


def _wrap(fn: Callable, *args, **kwargs):
    err = _esl_error_type()
    try:
        return fn(*args, **kwargs)
    except CoreError:
        raise
    except Exception as exc:
        if err and isinstance(exc, err):
            raise CoreError(getattr(exc, "code", "CORE_ERROR"), getattr(exc, "message", str(exc))) from None
        raise


# ---------------------------------------------------------------- 정보
def core_version() -> str:
    return str(getattr(_mod("esl"), "__version__", "unknown"))


def stages() -> tuple[str, ...]:
    return tuple(getattr(_mod("esl.pipeline"), "STAGES", DEFAULT_STAGES))


def solver_backends(core_cfg: dict | None) -> dict[str, Any]:
    """`GET /status` tools: 코어 ShellModel 과 같은 규칙(esl.mech.shell)으로 해석한 solver.backend 와 사용 가능 목록.

    - ``solver_backend``: 설정 값을 ``resolve_backend`` 로 해석한 값(= ShellModel.stats["backend"]; auto → 설치된
      직접법 1순위). 설정 백엔드가 미설치면 설정 값 그대로.
    - ``solver_backends_available``: ``available_backends()`` (우선순위 순) + ``iterative``(항상 가능).
    """
    requested = str(((core_cfg or {}).get("solver") or {}).get("backend") or "auto")
    shell = _mod("esl.mech.shell")
    avail = list(shell.available_backends())
    if "iterative" not in avail:
        avail.append("iterative")
    try:
        backend = shell.resolve_backend(requested)
    except Exception:  # 미설치 백엔드 지정 → 작업 실행 시 코어가 INPUT_INVALID
        backend = requested
    return {"solver_backend": backend, "solver_backends_available": avail}


# ---------------------------------------------------------------- 설정
def validate_core_settings(cfg: Any) -> dict:
    fn = _attr("esl.config", "validate_settings")
    return _wrap(fn, copy.deepcopy(cfg))


def load_core_config(path: str) -> dict:
    fn = _attr("esl.config", "load_config")
    return _wrap(fn, path)


# ---------------------------------------------------------------- 파이프라인
def run_signature() -> list[str]:
    return list(inspect.signature(_attr("esl.pipeline", "run")).parameters)


def run_pipeline(
    cfg: dict,
    rad: str,
    results: str,
    out: str,
    stage: str,
    *,
    frame: int | None = None,
    support_nodes: list[int] | None = None,
    echo: Callable[[str], None] | None = None,
    export_targets: list[str] | None = None,
    tag: str | None = None,
) -> dict:
    """`esl.pipeline.run` 1회 호출. 받지 않는 인자는 넘기지 않는다(시그니처 검사)."""
    fn = _attr("esl.pipeline", "run")
    params = inspect.signature(fn).parameters
    kw: dict[str, Any] = {}
    if "cfg" in params:
        kw["cfg"] = copy.deepcopy(cfg)
    elif "config_path_or_dict" in params:
        kw["config_path_or_dict"] = copy.deepcopy(cfg)
    elif "config" in params:
        kw["config"] = copy.deepcopy(cfg)
    else:
        raise CoreUnavailable("esl.pipeline.run 이 설정 dict 를 받지 않음")
    for name, value in (("rad", rad), ("results", results), ("out", out), ("stage", stage)):
        if name not in params:
            raise CoreUnavailable(f"esl.pipeline.run 인자 {name}")
        kw[name] = value
    if frame is not None:
        if "frame" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 frame")
        kw["frame"] = int(frame)
    if support_nodes is not None:
        if "support_nodes" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 support_nodes")
        kw["support_nodes"] = [int(n) for n in support_nodes]
    if echo is not None and "echo" in params:
        kw["echo"] = echo
    if export_targets is not None:
        if "export_targets" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 export_targets")
        kw["export_targets"] = [str(t) for t in export_targets]
    if tag is not None:
        if "tag" not in params:
            raise CoreUnavailable("esl.pipeline.run 인자 tag")
        kw["tag"] = str(tag)
    rec = _wrap(fn, **kw)
    return rec if isinstance(rec, dict) else {}


# ---------------------------------------------------------------- 동기 API 보조
def list_parts(rad: str, max_depth: int, include_path_map: dict | None = None) -> list[dict]:
    fn = _attr("esl.rad", "list_parts")
    kw: dict[str, Any] = {}
    params = inspect.signature(fn).parameters
    if "max_include_depth" in params:
        kw["max_include_depth"] = max_depth
    if "include_path_map" in params and include_path_map:
        kw["include_path_map"] = include_path_map
    return list(_wrap(fn, rad, **kw))


def scan_includes(rad: str, max_depth: int, include_path_map: dict | None = None) -> list[str]:
    fn = _attr("esl.rad", "scan_includes")
    kw: dict[str, Any] = {}
    params = inspect.signature(fn).parameters
    if "max_depth" in params:
        kw["max_depth"] = max_depth
    if "include_path_map" in params and include_path_map:
        kw["include_path_map"] = include_path_map
    return list(_wrap(fn, rad, **kw))


def pca_corners(x0) -> dict:
    return _wrap(_attr("esl.mech.supports", "pca_corners"), x0)


def pick_321(x0, cand_idx) -> list[tuple[int, str]]:
    out = _wrap(_attr("esl.mech.supports", "pick_321"), x0, list(cand_idx))
    return [(int(i), str(d)) for i, d in out]


# ====================================================================== P2: 전 요소 비교(§7) — 동기 API 보조
def field_reasons() -> dict[int, str]:
    return {int(k): str(v) for k, v in _attr("esl.report.field", "REASONS").items()}


def field_downsample(xi, eta, eps_rad, valid, max_points: int):
    """(idx 오름차순, cell(dx,dy) 또는 None). esl.report.field.downsample 그대로."""
    return _wrap(_attr("esl.report.field", "downsample"), xi, eta, eps_rad, valid, int(max_points))


def field_normalize(v, rng):
    return _wrap(_attr("esl.report.field", "normalize"), v, rng)


def field_section(fixed_norm, along, n0, w_rel, w_val, at: float, band: float) -> dict:
    return _wrap(_attr("esl.report.field", "section"), fixed_norm, along, n0, w_rel, w_val, float(at), float(band))


def field_err_range(err_pct) -> float | None:
    """오차 % 대칭 색 범위 R(= 보고서 히스토그램 범위, P99 |오차| 의 nice ceil, 최소 1%)."""
    h = _wrap(_attr("esl.report.field", "histogram"), err_pct, 20)
    return h.get("range_pct")


# ====================================================================== P2: 라이브러리(§1~§5, §11)
def _lib_cfg(cfg: dict) -> dict:
    """JSON 왕복(작업 params) 뒤의 라이브러리 설정 정리: ISTA 6 면 번호 키를 정수로."""
    cfg = copy.deepcopy(cfg)
    if cfg.get("_ista6"):
        cfg["_ista6"] = _wrap(_attr("esl.library.settings", "load_ista6_dict"), cfg["_ista6"])
    return cfg


def load_library_config(path: str) -> dict:
    return _wrap(_attr("esl.library.settings", "load"), path)


def validate_library_settings(d: Any, base_dir: str) -> dict:
    """설정 dict 검증(esl.library.settings 스키마) + ista6 표 읽기(상대경로는 base_dir 기준)."""
    import os

    import yaml

    st = _mod("esl.library.settings")
    cfg = _wrap(st.validate, copy.deepcopy(d))
    cfg["_path"] = None
    cfg["_ista6"] = None
    ip = (cfg.get("library") or {}).get("ista6")
    if ip:
        ip = ip if os.path.isabs(ip) else os.path.join(base_dir, ip)
        if not os.path.isfile(ip):
            raise CoreError("CONFIG_INVALID", f"library.ista6: 파일 없음 {ip}")
        with open(ip, encoding="utf-8-sig") as fh:
            cfg["_ista6"] = _wrap(st.load_ista6_dict, yaml.safe_load(fh), ip)
    return cfg


def interpret_orient(orient: str | None, drop_type: str | None, lib_cfg: dict) -> tuple[dict, list[str]]:
    """ISTA 6 orient 해석(면 목록·낙하 분류) — 메타 수정(PATCH) 시 drop_class 재계산."""
    cfg = _lib_cfg(lib_cfg)
    return _wrap(_attr("esl.library.scene_meta", "interpret_orient"), orient, drop_type, cfg.get("_ista6"))


def build_library_entry(case_dir: str, run_id: str, out_root: str, entry_id: str, lib_cfg: dict, *,
                        scene_path: str | None = None, registered_by: str | None = None) -> dict:
    """Case 의 run 스냅샷(runs/<run_id>/)으로 라이브러리 항목을 만들어 ``<out_root>/entries/<entry_id>/`` 에 저장.

    코어 ``entry.build`` → entry_id 를 플랫폼 id 로 바꿈(코어 결정적 id 는 ``core_entry_id``) → ``entry.save``
    (Writer: out_root 안에서만 쓰고 Case 폴더와 겹치면 거부, 이미 있으면 ENTRY_EXISTS). 반환: 항목 meta(JSON).
    """
    import os

    en = _mod("esl.library.entry")
    st = _mod("esl.library.settings")
    U = _mod("esl.library._util")
    cfg = _lib_cfg(lib_cfg)
    lib = cfg["library"]
    e = _wrap(en.build, case_dir, run_id, scene_path=scene_path, rules=st.scene_rules(cfg), nx=lib["grid"]["nx"],
              ny=lib["grid"]["ny"], axis_ref=lib["axis_ref"], top_n=lib["top_nodes"], mass=None,
              registered_by=registered_by)
    e.meta["core_entry_id"] = e.meta["entry_id"]
    e.meta["entry_id"] = entry_id
    w = _wrap(U.Writer, out_root, inputs=[("Case 폴더", case_dir)])
    _wrap(en.save, e, os.path.join(out_root, "entries", entry_id), w)
    return U.jsonable(e.meta)


def _overlay(entry, ov: dict | None) -> None:
    """DB 메타(사용자 수정 가능)를 항목 meta 에 덮어쓴다: 분석·보고서가 DB 값을 쓰도록."""
    if not ov:
        return
    meta = entry.meta
    if ov.get("entry_id"):
        meta["entry_id"] = ov["entry_id"]
    m = dict(meta.get("model") or {})
    om = ov.get("model") or {}
    for k_db, k_core in (("name", "product"), ("inch", "inch"), ("version", "version"), ("date", "date")):
        if k_db in om:
            m[k_core] = om[k_db]
    if "product_mass" in om:
        pm = om["product_mass"]
        m["mass"] = {"value": pm, "source": "user"} if pm is not None else {"value": None, "source": None}
    meta["model"] = m
    s = dict(meta.get("scene") or {})
    for k_db, k_core in (("project", "project"), ("scenario", "scenario"), ("seq", "seq"), ("drop_type", "drop_type"),
                         ("drop_class", "drop_class"), ("round", "round"), ("scene_no", "scene"),
                         ("orient", "orient"), ("suffix", "suffix"), ("variant", "variant")):
        if k_db in (ov.get("scene") or {}):
            s[k_core] = ov["scene"][k_db]
    meta["scene"] = s
    if ov.get("verdict") is not None:
        q = dict(meta.get("quality") or {})
        q["verdict"] = ov["verdict"]
        meta["quality"] = q


def _load_entry(d: str, ov: dict | None, raw: bool):
    en = _mod("esl.library.entry")
    e = _wrap(en.load, d, raw=raw, verify=True)
    _overlay(e, ov)
    return e


def run_library_stage(spec: dict, echo: Callable[[str], None]) -> dict:
    """LIB_ANALYZE 의 코어 단계 1개(자식 프로세스에서 호출). spec["stage"]: lib_analyze | lib_optdeck | lib_report.

    spec["lib"] = {cfg, lib_root, entries:[{id, dir, overlay}], target:{id, dir, overlay}|None, options, filters,
    analysis_id, title}. 산출물은 spec["out"](= <esl_root>/_analysis/<id>/) 아래만(Writer: 라이브러리 폴더와 겹치면 거부,
    기존 파일은 _backup/<ts>/ 로 이동).
    """
    stage = spec["stage"]
    fn = {"lib_analyze": _lib_analyze, "lib_optdeck": _lib_optdeck, "lib_report": _lib_report}.get(stage)
    if fn is None:
        raise CoreError("INPUT_INVALID", f"알 수 없는 라이브러리 단계: {stage}")
    return _wrap(fn, spec, echo)


def _writer(spec: dict):
    U = _mod("esl.library._util")
    return _wrap(U.Writer, spec["out"], inputs=[("라이브러리", spec["lib"]["lib_root"])])


def _lib_analyze(spec: dict, echo) -> dict:
    import os

    an = _mod("esl.library.analysis")
    L = spec["lib"]
    cfg = _lib_cfg(L["cfg"])
    out = spec["out"]
    tgt = L.get("target")
    target = _load_entry(tgt["dir"], tgt.get("overlay"), raw=True) if tgt else None
    entries = []
    for it in L["entries"]:
        e = _load_entry(it["dir"], it.get("overlay"), raw=False)
        if target is not None and e.meta.get("mesh_sha256") == target.meta.get("mesh_sha256"):
            e = _load_entry(it["dir"], it.get("overlay"), raw=True)
        entries.append(e)
    opts = dict(cfg["analysis"])
    for k in ("normalization", "n_representative", "svd_energy", "worst_case", "target_mass", "target_inch"):
        v = (L.get("options") or {}).get(k)
        if v is not None:
            opts[k] = v
    echo(f"[lib_analyze] 항목 {len(entries)}개, 대상 {tgt['id'] if tgt else '없음'}, 옵션 "
         + ", ".join(f"{k}={opts[k]}" for k in ("normalization", "n_representative", "svd_energy", "worst_case")))
    res, arrays = _wrap(an.run, entries, target, opts)
    res["analysis_id"] = L["analysis_id"]
    res["filters"] = L.get("filters") or {}
    res["library_root"] = L["lib_root"]
    res["config_path"] = cfg.get("_path")
    w = _writer(spec)
    w.makedirs(out)
    files = _wrap(an.save, res, arrays, out, w)
    echo(f"[lib_analyze] SVD r={res['svd']['n_modes']}, 대표 "
         + ", ".join(f"{lc['label']}={lc['entry_id']}" for lc in res["load_cases"]) + f" → {os.path.basename(out)} "
         f"({', '.join(files)})")
    for x in res.get("warnings") or []:
        echo(f"  경고: {x}")
    return {"files": files}


def _read_analysis(out: str):
    import os

    U = _mod("esl.library._util")
    p = os.path.join(out, "analysis.json")
    if not os.path.isfile(p):
        raise CoreError("PREREQUISITE_MISSING", f"분석 결과가 없음: {p}")
    return U.read_json(p), U.load_npz(os.path.join(out, "mapped_loads.npz"))


def _lib_optdeck(spec: dict, echo) -> dict:
    import os

    import numpy as np

    od = _mod("esl.library.optdeck")
    lcli = _mod("esl.library.cli")
    U = _mod("esl.library._util")
    L = spec["lib"]
    cfg = _lib_cfg(L["cfg"])
    out = spec["out"]
    res, arrays = _read_analysis(out)
    if not res.get("target") or not L.get("target"):
        raise CoreError("INPUT_INVALID", "대상 모델 없는 분석은 덱을 만들 수 없음")
    tgt = _load_entry(L["target"]["dir"], L["target"].get("overlay"), raw=True)
    mesh = tgt.mesh()
    if not np.array_equal(np.asarray(arrays["node_id"]), np.asarray(mesh["node_id"])):
        raise CoreError("ID_MISMATCH", "mapped_loads.npz node_id 가 대상 메시와 다름")
    sup = [(s["node_id"], s["dof"]) for s in tgt.meta["esl"]["supports"]]
    an = _mod("esl.library.analysis")
    cases = res["cases"]
    lcs = []
    for lc, f in zip(res["load_cases"], _wrap(an.load_case_forces, res, arrays)):
        c = cases[lc["case_index"]]
        lcs.append({"label": f"{lc['label']}_{c.get('drop_class') or ''}{c.get('orient') or ''}",
                    "entry_id": lc["entry_id"], "f": f, "weight": 1.0})
    oc = dict(cfg["optdeck"])
    obj = (L.get("options") or {}).get("objective")
    if obj:
        oc["objective"] = obj
    mode = oc.pop("reference_compliance")
    solver = oc.pop("solver")
    if mode == "solve":
        refs = _wrap(lcli.reference_compliance, mesh, sup, [x["f"] for x in lcs], solver)
        for x, rv in zip(lcs, refs):
            x["ref"] = rv
    oc["header"] = [f"analysis {L['analysis_id']} target {tgt.entry_id} ({res['target']['model'].get('product')})",
                    f"load cases: {', '.join(x['label'] + '=' + x['entry_id'] for x in lcs)}",
                    f"reference compliance: {mode}"]
    w = _writer(spec)
    od_dir = os.path.join(out, "opt")
    w.fresh_dir(od_dir, out)
    summ = _wrap(od.write, mesh, lcs, sup, oc, od_dir, w)
    summ["reference_compliance"] = mode
    summ["analysis_id"] = L["analysis_id"]
    U.write_json(w.fresh_file(os.path.join(od_dir, "optdeck.json"), out), summ)
    echo(f"[lib_optdeck] opt/{summ['deck']} subcase {summ['n_subcases']}, 설계 요소 {summ['n_design_elems']} / "
         f"비설계 {summ['n_nondesign_elems']}, 목적 {summ['objective']}")
    return {"files": summ["files"]}


def _lib_report(spec: dict, echo) -> dict:
    import os

    ra = _mod("esl.library.report_analysis")
    U = _mod("esl.library._util")
    L = spec["lib"]
    out = spec["out"]
    res, arrays = _read_analysis(out)
    op = os.path.join(out, "opt", "optdeck.json")
    opt = U.read_json(op) if os.path.isfile(op) else None
    w = _writer(spec)
    html = w.fresh_file(os.path.join(out, "report.html"), out)
    info = {"analysis_id": L["analysis_id"], "filters": res.get("filters") or {}}
    if L.get("title"):
        info["title"] = L["title"]
    _wrap(ra.write, res, html, arrays, opt, info)
    echo(f"[lib_report] report.html ({os.path.getsize(html) / 1024:.0f} KB)")
    return {"files": ["report.html"]}
