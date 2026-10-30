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


def extract_source_settings(core_settings: dict | None = None) -> dict:
    """설정 extract 의 h3d 변형률 결과 대체 키(기본값 채운 사본, 계약 esl_strain_fallback.md §2)."""
    return _wrap(_attr("esl.config", "extract_source_settings"), core_settings or {})


def dump_settings(core_settings: dict | None = None) -> dict:
    """extract.dump_keep·dump_max_bytes(기본값 채움)."""
    return _wrap(_attr("esl.config", "dump_settings"), core_settings or {})


def cumulative_prev(rad: str, part_title: str, out_csv: str, core_settings: dict | None = None) -> dict | None:
    """누적 씬(rad include 에 상태 파일 .sta/.str) 판정 → 대상 파트 이전 소성 CSV(prev.csv) 작성(계약
    esl_cumulative_input.md §15 Worker). 상태 파일이 없거나 cumulative.enabled=off 면 None(아무것도 쓰지 않음).
    반환 {n, state_files, min_increment, agg}. 코어 오류는 CoreError."""
    cfg = core_settings or {}
    cc = cfg.get("case") or {}
    cus = _attr("esl.config", "cumulative_settings")(cfg)
    if cus.get("enabled") in ("off", False):
        return None
    refs = scan_include_refs(rad, int(cc.get("rad_include_max_depth") or 8), cc.get("include_path_map") or None)
    is_state = _attr("esl.rad.state", "is_state_file")
    if not any(r.get("found") and is_state(r["path"]) for r in refs):
        return None
    parse = _attr("esl.rad", "parse_rad")
    model = _wrap(parse, rad, part_title, match=cc.get("part_title_match") or "exact_ci",
                  max_include_depth=int(cc.get("rad_include_max_depth") or 8),
                  material_override=cc.get("material_override") or None,
                  include_path_map=cc.get("include_path_map") or None,
                  thickness_source=cus["thickness_source"])
    if getattr(model, "state", None) is None:
        return None
    n = _wrap(_attr("esl.cumulative", "write_prev_csv"), model, out_csv, cus["epsp_agg"])
    return {"n": int(n), "state_files": [f["path"] for f in model.state["files"]],
            "min_increment": float(cus["min_increment"]), "agg": cus["epsp_agg"]}


def scan_include_refs(rad: str, max_depth: int, include_path_map: dict | None = None, follow=None) -> list[dict]:
    """include 참조(원문·경로·찾음 여부). follow(path) 가 참인 파일 안으로만 더 들어간다."""
    fn = _attr("esl.rad", "scan_include_refs")
    kw: dict[str, Any] = {"max_depth": max_depth, "follow": follow}
    if include_path_map:
        kw["include_path_map"] = include_path_map
    return list(_wrap(fn, rad, **kw))


def display_path(p):
    """사용자에게 보이는 경로 표기 통일(이슈 #24, esl.display.display_path)."""
    return _attr("esl.display", "display_path")(p)


def pca_corners(x0) -> dict:
    return _wrap(_attr("esl.mech.supports", "pca_corners"), x0)


def pick_321(x0, cand_idx) -> list[tuple[int, str]]:
    out = _wrap(_attr("esl.mech.supports", "pick_321"), x0, list(cand_idx))
    return [(int(i), str(d)) for i, d in out]


# v0.10.0(esl_menu_restructure.md §5): ② t* 확정 시 3-2-1 자동 선택·수동 3노드 검사(동기 API)
def support_check_settings(core_cfg: dict | None) -> dict:
    """코어 설정의 support.auto_check(없으면 기본값) — 코어 cfg 에는 주입하지 않는다."""
    return _attr("esl.config", "support_check_settings")(core_cfg or {})


def auto_support(x0, check_cfg: dict | None) -> dict:
    return _wrap(_attr("esl.mech.supports", "auto_321"), x0, check_cfg)


def check_support(x0, idx, check_cfg: dict | None) -> dict:
    return _wrap(_attr("esl.mech.supports", "check_321"), x0, list(idx), check_cfg)


def run_lib_export(spec: dict, echo: Callable[[str], None]) -> list[dict]:
    """EXPORT library 모드(자식 프로세스, esl_menu_restructure.md §6.2): spec["lib"] = esl_worker.lib_jobs.prepare_lib_export
    의 dict → 코어 esl.export.from_entry.run_items(항목별 try, 결과 = 항목 폴더 export.json)."""
    L = spec["lib"]
    run_items = _attr("esl.export.from_entry", "run_items")
    return _wrap(run_items, L["items"], spec["out"], L["targets"], L["cfg"], wait_s=float(L.get("wait_s") or 0.0),
                 echo=echo, progress=_progress(spec))


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


def field_robust_range(values, kind: str) -> dict:
    """견고한 컬러 범위 {min, max, basis, raw}(계약 esl_disp_primary.md §14). kind = sym | zero | minmax."""
    return _wrap(_attr("esl.report.field", "robust_range"), values, kind)


def field_section_stats(s, w_rel, w_val, U) -> dict:
    """{dw, stats} — 단면 Δw 와 통계(§15.2). w_val=None 이면 dw 빈 배열."""
    return _wrap(_attr("esl.report.field", "section_stats"), s, w_rel, w_val, U)


def field_section_line(plane, xi_range, eta_range, axis: str, at: float, band: float) -> dict:
    return _wrap(_attr("esl.report.field", "section_line"), plane, xi_range, eta_range, axis, float(at), float(band))


def field_normalized_point(ab, xi_range, eta_range) -> tuple[float, float]:
    return _wrap(_attr("esl.report.field", "normalized_point"), ab, xi_range, eta_range)


def field_err_range(err_pct) -> float | None:
    """오차 % 대칭 색 범위 R(= 보고서 히스토그램 범위, P99 |오차| 의 nice ceil, 최소 1%)."""
    h = _wrap(_attr("esl.report.field", "histogram"), err_pct, 20)
    return h.get("range_pct")


# ====================================================================== 0.5.8: ④ 3D 하중 보기(계약 esl_3d_load.md §3)
def view3d_build(out_dir: str, **kw) -> dict:
    """``esl.view3d.build_view`` — out_dir 에 part.glb·(part_lod.glb)·values.bin·manifest.json 을 쓰고 manifest 를 돌려준다."""
    return _wrap(_attr("esl.view3d", "build_view"), out_dir, **kw)


def view3d_builder_version() -> int:
    return int(_attr("esl.view3d", "BUILDER_VERSION"))


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
                        scene_path: str | None = None, registered_by: str | None = None,
                        mode_cfg: dict | None = None) -> dict:
    """Case 의 run 스냅샷(runs/<run_id>/)으로 라이브러리 항목을 만들어 ``<out_root>/entries/<entry_id>/`` 에 저장.

    코어 ``entry.build`` → entry_id 를 플랫폼 id 로 바꿈(코어 결정적 id 는 ``core_entry_id``) → ``entry.save``
    (Writer: out_root 안에서만 쓰고 Case 폴더와 겹치면 거부, 이미 있으면 ENTRY_EXISTS). 반환: 항목 meta(JSON).
    v0.7.0: 등록 시 meta.topo_sha256·deform_mode(변형 모드 자동 분류, 기준값 = mode_cfg = 설정 opt_run.mode)를 함께 계산.
    """
    import os

    en = _mod("esl.library.entry")
    st = _mod("esl.library.settings")
    U = _mod("esl.library._util")
    cfg = _lib_cfg(lib_cfg)
    lib = cfg["library"]
    e = _wrap(en.build, case_dir, run_id, scene_path=scene_path, rules=st.scene_rules(cfg), nx=lib["grid"]["nx"],
              ny=lib["grid"]["ny"], axis_ref=lib["axis_ref"], top_n=lib["top_nodes"], mass=None,
              registered_by=registered_by, mode_cfg=mode_cfg)
    e.meta["core_entry_id"] = e.meta["entry_id"]
    e.meta["entry_id"] = entry_id
    w = _wrap(U.Writer, out_root, inputs=[("Case 폴더", case_dir)])
    _wrap(en.save, e, os.path.join(out_root, "entries", entry_id), w)
    return U.jsonable(e.meta)


def sort_versions(versions) -> list[str]:
    """설계 버전 자연 정렬(v2 < v10) — esl.library.compare 규칙."""
    return list(_attr("esl.library.compare", "sort_versions")(versions))


def previous_version(versions, new: str) -> str | None:
    return _attr("esl.library.compare", "previous_version")(versions, new)


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
        # v0.10.0(esl_menu_restructure.md §7.4): 판정 원본 = DB quality(재검증 전환 반영) — status·scheme 도 덮어쓴다
        for k in ("status", "scheme"):
            if k in ov:
                q[k] = ov[k]
        meta["quality"] = q


def _load_entry(d: str, ov: dict | None, raw: bool):
    en = _mod("esl.library.entry")
    e = _wrap(en.load, d, raw=raw, verify=True)
    _overlay(e, ov)
    return e


def run_library_stage(spec: dict, echo: Callable[[str], None]) -> dict:
    """LIB_ANALYZE·LIB_COMPARE 의 코어 단계 1개(자식 프로세스). spec["stage"]: lib_analyze | lib_optdeck |
    lib_report | lib_compare.

    spec["lib"] = {cfg, lib_root, entries:[{id, dir, overlay}], target:{id, dir, overlay}|None, options, filters,
    analysis_id, title}. 산출물은 spec["out"](= <esl_root>/_analysis/<id>/) 아래만(Writer: 라이브러리 폴더와 겹치면 거부,
    기존 파일은 _backup/<ts>/ 로 이동).
    """
    stage = spec["stage"]
    fn = {"lib_analyze": _lib_analyze, "lib_optdeck": _lib_optdeck, "lib_report": _lib_report,
          "lib_compare": _lib_compare}.get(stage)
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
    oc = cfg.get("optdeck") or {}
    opts["deck_cases"] = (L.get("options") or {}).get("optdeck_cases") or oc.get("cases") or "all"
    opts["max_cases"] = oc.get("max_cases") or 60
    for k in ("normalization", "n_representative", "svd_energy", "worst_case", "target_mass", "target_inch"):
        v = (L.get("options") or {}).get(k)
        if v is not None:
            opts[k] = v
    echo(f"[lib_analyze] 항목 {len(entries)}개, 대상 {tgt['id'] if tgt else '없음'}, 옵션 "
         + ", ".join(f"{k}={opts[k]}" for k in ("normalization", "n_representative", "svd_energy", "worst_case",
                                                 "deck_cases", "max_cases")))
    res, arrays = _wrap(an.run, entries, target, opts)
    res["analysis_id"] = L["analysis_id"]
    res["filters"] = L.get("filters") or {}
    res["library_root"] = L["lib_root"]
    res["config_path"] = cfg.get("_path")
    w = _writer(spec)
    w.makedirs(out)
    files = _wrap(an.save, res, arrays, out, w)
    dk = res.get("deck") or {}
    echo(f"[lib_analyze] SVD r={res['svd']['n_modes']}, 대표 "
         + ", ".join(f"{lc['label']}={lc['entry_id']}" for lc in res["load_cases"])
         + f", 덱 {dk.get('mode')} subcase {dk.get('n_subcases')}" + (" (자동 축소)" if dk.get("reduced") else "")
         + f" → {os.path.basename(out)} ({', '.join(files)})")
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
    lcs = _wrap(an.optdeck_load_cases, res, arrays)
    oc = dict(cfg["optdeck"])
    oc.pop("cases", None)
    oc.pop("max_cases", None)
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
    summ["deck_cases"] = lcli._deck_brief(res)
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


def _lib_compare(spec: dict, echo) -> dict:
    """설계 버전 비교(§12.2): spec["lib"] = {cfg, lib_root, comparison_id, model, base_version, new_version,
    base:[{id, dir, overlay}], new:[...], options, filters, title}. 산출 <esl_root>/_compare/<id>/compare.json·report.html."""
    import os

    cmp = _mod("esl.library.compare")
    L = spec["lib"]
    cfg = _lib_cfg(L["cfg"])
    out = spec["out"]
    base = [_load_entry(it["dir"], it.get("overlay"), raw=False) for it in L.get("base") or []]
    new = [_load_entry(it["dir"], it.get("overlay"), raw=False) for it in L.get("new") or []]
    crit = dict(cfg.get("convergence") or {})
    o = L.get("options") or {}
    if o.get("cos_min") is not None:
        crit["cos_min"] = o["cos_min"]
    an_cfg = cfg.get("analysis") or {}
    copts = {"n_representative": o.get("n_representative") or an_cfg.get("n_representative"),
             "seed": an_cfg.get("seed"), "n_init": an_cfg.get("n_init")}
    echo(f"[lib_compare] {L.get('model')} {L.get('base_version')}({len(base)}) → {L.get('new_version')}({len(new)}), "
         f"기준 {crit}")
    res = _wrap(cmp.compare, base, new, crit, copts)
    res.update(comparison_id=L["comparison_id"], model=L.get("model"), base_version=L.get("base_version"),
               new_version=L.get("new_version"), filters=L.get("filters") or {}, library_root=L["lib_root"])
    w = _writer(spec)
    w.makedirs(out)
    info = {"title": L["title"]} if L.get("title") else None
    files = _wrap(cmp.save, res, out, w, info)
    cv = res["convergence"]
    echo(f"[lib_compare] 짝 {res['n_paired']}개, cos 최소 {res['aggregate']['cos_min']:.4f}, 대표 동일 "
         f"{res['representatives']['rep_same']} → {cv['label']} ({os.path.basename(out)}: {', '.join(files)})")
    for x in res.get("warnings") or []:
        echo(f"  경고: {x}")
    return {"files": files}


# ====================================================================== v0.7.0 비드 최적화 OPT_RUN(계약 esl_opt_run.md §4·§6·§9)
# 코어 esl.opt(대상·하중·선정·덱·.out 해석·후처리·보고서) 조립. 산출물은 spec["out"](= <esl_root>/_opt/<id>/) 아래만 —
# Writer 입력 목록(라이브러리·템플릿·S1 Case 입력 rad 폴더)에는 쓰지 않는다. 단계 요약 JSON(target/prep.json,
# load/load.json, deck/optdeck.json)의 warnings 를 executor 가 작업 경고로 올린다.
OPT_STAGES = ("opt_prep", "opt_load", "opt_deck", "opt_post")


def opt_osout():
    """esl.opt.osout(OptiStruct .out 해석·판정) — 워커 OS_SOLVE 가 코어와 같은 판정 기준을 쓰도록."""
    return _mod("esl.opt.osout")


def _opt_inputs(L: dict) -> list[tuple[str, str]]:
    import os

    ins = [("라이브러리", L["lib_root"]), ("템플릿", L["templates_root"])]
    base = L.get("base") or {}
    if base.get("rad_path"):
        ins.append(("Case 입력", os.path.dirname(base["rad_path"])))
    return ins


def _opt_writer(out: str, L: dict):
    U = _mod("esl.library._util")
    return _wrap(U.Writer, out, inputs=_opt_inputs(L))


def opt_fresh_dir(out: str, sub: str, L: dict) -> str | None:
    """<out>/<sub> 를 비운다(이전 내용 → <out>/_backup/<UTC>/<sub>, 삭제 없음). 옮긴 경로(없으면 None)."""
    import os

    w = _opt_writer(out, L)
    d = os.path.join(out, sub)
    moved = None
    if os.path.isdir(d) and os.listdir(d):
        moved = _wrap(w.backup, d, out)
    _wrap(w.makedirs, d)
    return moved


def run_opt_stage(spec: dict, echo: Callable[[str], None]) -> dict:
    """OPT_RUN 코어 단계 1개(자식 프로세스). spec["lib"] = esl_worker.opt_jobs.prepare 의 dict."""
    fn = {"opt_prep": _opt_prep, "opt_load": _opt_load, "opt_deck": _opt_deck, "opt_post": _opt_post}.get(spec["stage"])
    if fn is None:
        raise CoreError("INPUT_INVALID", f"알 수 없는 최적화 단계: {spec['stage']}")
    return _wrap(fn, spec, echo)


def _progress(spec: dict):
    import os

    path = spec.get("progress_path")
    last = [-1]

    def put(pct: float) -> None:
        p = int(max(0.0, min(100.0, float(pct))))
        if not path or p <= last[0]:
            return
        last[0] = p
        from esl_platform.core.atomic import write_text_atomic

        write_text_atomic(path, str(p), "ascii")
    return put


def _scene_label(meta: dict) -> str | None:
    s = meta.get("scene") or {}
    parts = [s.get("seq") if s.get("seq") is not None else s.get("scene"), s.get("drop_type"), s.get("orient"),
             s.get("round")]
    txt = " ".join(str(p) for p in parts if p not in (None, ""))
    return txt or None


def _opt_cfg(L: dict) -> dict:
    return _attr("esl.opt", "settings")(L.get("cfg") or {})


def _opt_prep(spec: dict, echo) -> dict:
    """OR-1: 대상(S1 parse_rad 제자리 / S2 template.npz) → 동일성·크기 → 3-2-1 → 금지 영역·비설계 → target/."""
    import os

    U = _mod("esl.library._util")
    en = _mod("esl.library.entry")
    tg = _mod("esl.opt.target")
    ident = _mod("esl.opt.identity")
    ko = _mod("esl.opt.keepout")
    post = _mod("esl.opt.post")
    L = spec["lib"]
    out = spec["out"]
    cfg = _opt_cfg(L)
    prog = _progress(spec)
    prog(0)
    tdir = os.path.join(out, "target")
    warns: list[str] = []
    prev_sha = None
    pj = os.path.join(tdir, "target.json")
    if os.path.isfile(pj):
        try:
            prev_sha = ((U.read_json(pj).get("source") or {}).get("rad") or {}).get("sha256")
        except (OSError, ValueError):
            prev_sha = None
    w = _opt_writer(out, L)
    w.fresh_dir(tdir, out)
    ents = L["entries"]
    size_info = None
    if L["scenario"] == "S1":
        base = L["base"]
        core = L.get("core") or {}
        cc = core.get("case") or {}
        parse_kw = {"match": cc.get("part_title_match") or "exact_ci",
                    "max_include_depth": int(cc.get("rad_include_max_depth") or 8),
                    "include_path_map": cc.get("include_path_map") or None}
        tol = float(((core.get("coord_check") or {}).get("max_rel"))
                    or _attr("esl.config", "COORD_CHECK_DEFAULTS")["max_rel"])
        bdir = next((e["dir"] for e in ents if e["id"] == base["entry_id"]), None)
        if bdir is None:
            raise CoreError("INPUT_INVALID", "기준 ESL 이 선택 목록에 없음")
        be = en.load(bdir, raw=True)
        echo(f"[opt_prep] S1 기준 Case 입력 rad 제자리 읽기: {base['rad_path']} (파트 {base['part_title']})")
        t = tg.case_target(base["rad_path"], base["part_title"], be.meta, be.raw, coord_tol_rel=tol, parse_kw=parse_kw)
        prog(60)
        for e in ents:
            if e["id"] == base["entry_id"]:
                continue
            o = en.load(e["dir"], raw=True)
            rows = ident.check_entries(t.mesh, [(e["id"], o.raw)], tol)
            ident.assert_same(rows)
            t.source["identity"] = list(t.source.get("identity") or []) + rows
            del o
        sha = (t.source.get("rad") or {}).get("sha256")
        if prev_sha and sha and prev_sha != sha:
            warns.append(f"INPUT_CHANGED: 기준 Case 입력 rad 가 이전 실행 이후 바뀜(sha256 {prev_sha[:12]}… → {sha[:12]}…) "
                         "— 모델 동일성을 다시 확인하고 진행")
        echo(f"[opt_prep] 대상 노드 {t.n_nodes} · 요소 {t.n_elems}, 같은 모델 {len(t.source.get('identity') or [])}개 "
             "확인" + (f", 법선 반대 요소 {t.normals.get('normals_opposite')}개(원 연결 유지)"
                     if t.normals.get("normals_opposite") else ""))
    else:
        sz = _mod("esl.opt.size")
        tp = L["template"]
        arrs = U.load_npz(os.path.join(tp["dir"], "template.npz"))
        tmeta = U.read_json(os.path.join(tp["dir"], "template.json"))
        prog(30)
        rows = []
        for e in ents:
            m = U.read_json(os.path.join(e["dir"], "entry.json"))
            fr = m.get("frame") or {}
            g = m.get("grid") or e.get("grid") or {}
            rows.append({"entry_id": e["id"], "inch": e.get("inch"), "L_xi": float(fr.get("L_xi") or e.get("L_xi")),
                         "L_eta": float(fr.get("L_eta") or e.get("L_eta")),
                         "grid": (int(g["nx"]), int(g["ny"])) if g.get("nx") and g.get("ny") else None})
        size_info = sz.assert_ok(rows, cfg["size"], {"inch": tp.get("inch"), "L_xi": tp["L_xi"], "L_eta": tp["L_eta"]})
        warns += list(size_info["warnings"])
        sup = [(int(s["node_id"]), str(s["dof"])) for s in ((L.get("options") or {}).get("supports") or [])] or None
        t = tg.template_target(arrs, tmeta, sup, {"template_id": tp["id"], "file_name": tp.get("file_name"),
                                                  "format": tp.get("format"), "sha256": tp.get("sha256")})
        prog(60)
        echo(f"[opt_prep] S2 템플릿 {tp['id']}: 노드 {t.n_nodes} · 요소 {t.n_elems}, 크기 검사 통과(ESL {len(rows)}개)"
             + (f", 법선 정렬 {t.normals.get('normals_flipped')}개" if t.normals.get("normals_flipped") else ""))
    des_cfg = L.get("design") or {}
    k = ko.compute(t.mesh, t.frame, des_cfg.get("keepout"), cfg["keepout"])
    warns += list(k["warnings"])
    des, dinfo = tg.design_mask(t, des_cfg.get("nondesign_pids") or [], k["mask"])
    prog(90)
    warns = list(t.warnings) + warns
    t.warnings = warns
    meta = tg.save(t, tdir, w, extra={"design": des, "keepout_reason": k["reason"]})
    post.write_keepout_png(os.path.join(tdir, "keepout.png"), t, {"rects": k["rects"]}, des, cfg["post"]["png_px"], w)
    c = k["counts"]
    summ = {"scenario": t.scenario, "n_nodes": t.n_nodes, "n_elems": t.n_elems, "keepout": c, "design": dinfo,
            "normals": t.normals, "supports": meta["supports"], "topo_sha256": t.topo_sha256,
            "size": None if size_info is None else U.jsonable(size_info)}
    U.write_json(w.fresh_file(os.path.join(tdir, "prep.json"), out),
                 {"summary": U.jsonable(summ), "rects": U.jsonable(k["rects"]), "auto": k["auto"], "warnings": warns})
    echo(f"[opt_prep] 금지 영역 요소: 구멍 {c['n_elems_auto_hole']} · 가장자리 {c['n_elems_auto_edge']} · 사각형 "
         f"{c['n_elems_rects']} (구멍 루프 {c['n_holes']}개), 비설계 PID 요소 {dinfo['n_nondesign_pid']}, 설계 요소 "
         f"{dinfo['n_design_elems']}/{dinfo['n_elems']}")
    for x in warns:
        echo(f"  경고: {x}")
    prog(100)
    return {"files": ["target/target.npz", "target/target.json", "target/keepout.png", "target/prep.json"]}


def _opt_load(spec: dict, echo) -> dict:
    """OR-2: 후보 ESL 하중(S1 직접 / S2 셀 매핑) → 초기 컴플라이언스(분해 1회) → 전략 A/B/C → load/."""
    import os

    import numpy as np

    U = _mod("esl.library._util")
    en = _mod("esl.library.entry")
    tg = _mod("esl.opt.target")
    sl = _mod("esl.opt.select")
    eo = _mod("esl.opt")
    L = spec["lib"]
    out = spec["out"]
    cfg = _opt_cfg(L)
    prog = _progress(spec)
    prog(0)
    t, _extra = tg.load(os.path.join(out, "target"))
    w = _opt_writer(out, L)
    ldir = os.path.join(out, "load")
    w.fresh_dir(ldir, out)
    dirs = {e["id"]: e["dir"] for e in L["entries"]}
    cands = []
    for e in L["entries"]:
        m = U.read_json(os.path.join(e["dir"], "entry.json"))
        cands.append({"entry_id": e["id"], "mode": e.get("mode"), "scene": _scene_label(m)})

    def load_fn(eid: str):
        if t.scenario == "S1":
            e = en.load(dirs[eid], raw=True)
            f, _info = tg.entry_load(t, e.raw)
        else:
            e = en.load(dirs[eid], raw=False)
            f, _info = tg.entry_load(t, None, e.summary_for_mapping())
        return f

    def progress(k: int, K: int) -> None:
        prog(20 + 80 * k / max(1, K))
        if k:
            echo(f"[opt_load] 후보 {k}/{K}")

    o = L.get("options") or {}
    ms = eo.load_method_sources()
    strategy = o.get("load_strategy") or cfg["loads"]["default_strategy"]
    norm = o.get("objective_norm") or cfg["loads"]["default_objective_norm"]
    echo(f"[opt_load] 후보 ESL {len(cands)}개, 전략 {strategy}"
         + (f" k={o.get('k')}" if strategy == "C" else "") + f", 목표 기준 {norm}, 대상 쉘 모델 조립·분해 1회")
    u_store = os.path.join(ldir, "u_cand.npy") if strategy in ("A", "C") else None
    sel, forces, comp = sl.run(t, cands, load_fn, strategy=strategy, objective_norm=norm, k=o.get("k"), cfg=cfg,
                               u_store=w.guard(u_store) if u_store else None, sources_ref=eo.sources_ref(ms),
                               progress=progress)
    U.write_json(w.fresh_file(os.path.join(ldir, "selection.json"), out), sel)
    if u_store and os.path.isfile(u_store):
        # 후보 변위 memmap(22만 노드 × 200 ≈ 0.5 GB)은 이 단계의 작업 파일 — 결과 목록·묶음에 넣지 않도록 정리
        import gc

        gc.collect()
        try:
            os.remove(w.guard(u_store))
        except OSError as exc:
            echo(f"[opt_load] 작업 파일 u_cand.npy 를 지우지 못함(무시): {exc}")
    labs = sorted((r for r in sel["rows"] if r.get("label")), key=lambda r: r["label"])
    arrs = {"node_id": np.asarray(t.mesh["node_id"], dtype=np.int64),
            "labels": np.array([r["label"] for r in labs]), "entry_ids": np.array([r["entry_id"] for r in labs])}
    for r in labs:
        arrs[f"f_{r['label']}"] = np.asarray(forces[r["entry_id"]], dtype=np.float64)
    np.savez_compressed(w.fresh_file(os.path.join(ldir, "loads.npz"), out), **arrs)
    for r in sel["rows"]:
        echo(f"[opt_load] {r['entry_id']} 모드 {r.get('mode')} C0 {r['C0']:.4g} umax {r['umax']:.4g} → {r['status']}"
             + (f" {r['label']}" if r.get("label") else "")
             + (f" (→ {r['merged_into']}, MAC {r['mac_to_target']}, 부호 {r['sign']})" if r.get("merged_into") else ""))
    echo(f"[opt_load] 선정: ESL {sel['n_selected_esl']} → 케이스 {sel['n_cases']}, C_ref {sel['C_ref']:.4g}"
         + (f", 제외 모드 {sel['excluded_modes']}" if sel.get("excluded_modes") else ""))
    summ = {"strategy": sel["strategy"], "objective_norm": sel["objective_norm"], "n_selected_esl": sel["n_selected_esl"],
            "n_cases": sel["n_cases"], "C_ref": sel["C_ref"], "solver": comp["stats"]}
    U.write_json(w.fresh_file(os.path.join(ldir, "load.json"), out),
                 {"summary": U.jsonable(summ), "C": np.asarray(comp["C"]).tolist(),
                  "umax": np.asarray(comp["umax"]).tolist(), "entry_ids": comp["entry_ids"],
                  "warnings": list(sel.get("warnings") or [])})
    prog(100)
    return {"files": ["load/selection.json", "load/loads.npz", "load/load.json"]}


def _opt_deck(spec: dict, echo) -> dict:
    """OR-3: optdeck.write(minmax, POS = C_ref | C⁰, 비설계 = PID ∪ 금지 영역, server 카드) → deck/."""
    import os

    U = _mod("esl.library._util")
    tg = _mod("esl.opt.target")
    od = _mod("esl.library.optdeck")
    L = spec["lib"]
    out = spec["out"]
    cfg = _opt_cfg(L)
    prog = _progress(spec)
    prog(0)
    t, extra = tg.load(os.path.join(out, "target"))
    sel = U.read_json(os.path.join(out, "load", "selection.json"))
    la = U.load_npz(os.path.join(out, "load", "loads.npz"))
    forces = {str(e): la[f"f_{lab}"] for lab, e in zip(la["labels"].tolist(), la["entry_ids"].tolist())}
    lcs = tg.deck_load_cases(sel, forces)
    lib_cfg = L.get("library") or {}
    design = tg.deck_design(t, design=extra["design"], bead=(L.get("design") or {}).get("bead")
                            or cfg["bead_defaults"], run_id=L["run_id"], desmax=int(cfg["solve"]["desmax"]),
                            selection=sel, optdeck_cfg=lib_cfg.get("optdeck") or {})
    w = _opt_writer(out, L)
    ddir = os.path.join(out, "deck")
    w.fresh_dir(ddir, out)
    summ = od.write(t.mesh, lcs, t.supports, design, ddir, w)
    summ["opt_run_id"] = L["run_id"]
    summ["load_strategy"] = sel["strategy"]
    summ["objective_norm"] = sel["objective_norm"]
    summ["C_ref"] = sel["C_ref"]
    U.write_json(w.fresh_file(os.path.join(ddir, "optdeck.json"), out), summ)
    for s in summ["subcases"]:
        echo(f"[opt_deck] subcase {s['subcase']} {s['label']} = {s['entry_id']} POS {s['ref']}")
    echo(f"[opt_deck] deck/{summ['deck']} subcase {summ['n_subcases']}, 설계 요소 {summ['n_design_elems']} / 비설계 "
         f"{summ['n_nondesign_elems']}, DESMAX {cfg['solve']['desmax']}")
    prog(100)
    return {"files": [f"deck/{f}" for f in summ["files"]]}


def _opt_post(spec: dict, echo) -> dict:
    """OR-5: post/shape.csv(hw) → 비드 산출물·history.csv → opt.json(OptResult) → report.html."""
    import os

    import numpy as np

    U = _mod("esl.library._util")
    tg = _mod("esl.opt.target")
    po = _mod("esl.opt.post")
    oo = _mod("esl.opt.osout")
    rp = _mod("esl.opt.report_opt")
    eo = _mod("esl.opt")
    L = spec["lib"]
    out = spec["out"]
    cfg = _opt_cfg(L)
    prog = _progress(spec)
    prog(50)
    t, extra = tg.load(os.path.join(out, "target"))
    sel = U.read_json(os.path.join(out, "load", "selection.json"))
    dk = U.read_json(os.path.join(out, "deck", "optdeck.json"))
    prep = U.read_json(os.path.join(out, "target", "prep.json"))
    stem = os.path.splitext(dk["deck"])[0]
    pdir = os.path.join(out, "post")
    w = _opt_writer(out, L)
    shape = po.read_shape_csv(os.path.join(pdir, "shape.csv"), t.mesh["node_id"])
    echo(f"[opt_post] Shape Change 노드 {len(shape)}개")
    design = L.get("design") or {}
    bead = design.get("bead") or cfg["bead_defaults"]
    rects = prep.get("rects") or []
    bs = po.write_outputs(pdir, t, shape, design=extra["design"], keepout_reason=extra["keepout_reason"], rects=rects,
                          bead=bead, post_cfg=cfg["post"], writer=w)
    prog(70)
    with open(os.path.join(out, "solve", stem + ".out"), encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    parsed = oo.parse_out(text, cfg["solve"])
    hist = oo.history(parsed, sel)
    with open(w.fresh_file(os.path.join(pdir, "history.csv"), out), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(oo.history_csv(hist, sel))
    subcases, cwarn = oo.subcase_summary(parsed, sel, float(cfg["loads"]["c0_tol"]))
    sm = L.get("solve_meta") or {}
    warns = list(L.get("warnings") or []) + list(prep.get("warnings") or []) + list(sel.get("warnings") or []) \
        + list(bs.get("warnings") or []) + cwarn
    res = po.assemble_result(selection=sel, parsed=parsed, desmax=int(cfg["solve"]["desmax"]), subcases=subcases,
                             keepout_counts=(prep.get("summary") or {}).get("keepout") or {},
                             n_design_elems=int(np.asarray(extra["design"], dtype=bool).sum()), bead_summary=bs,
                             normals=t.normals, solve_meta=sm, warnings=warns)
    U.write_json(w.fresh_file(os.path.join(out, "opt.json"), out), res)
    prog(85)
    with open(os.path.join(out, "target", "keepout.png"), "rb") as fh:
        kpng = fh.read()
    summ = prep.get("summary") or {}
    ctx = {"run": {"id": L["run_id"], "scenario": L["scenario"], "title": L.get("title"),
                   "created_at": L.get("created_at"), "entry_ids": L.get("entry_ids") or [e["id"] for e in L["entries"]]},
           "selection": sel, "result": res,
           "target": {"n_nodes": t.n_nodes, "n_elems": t.n_elems, "source": t.source,
                      "identity": t.source.get("identity") or [], "size": (summ.get("size") or {}).get("entries"),
                      "normals": t.normals, "warnings": t.warnings},
           "keepout": {"counts": summ.get("keepout") or {}, "rects": rects, "auto": prep.get("auto") or {},
                       "cfg": cfg["keepout"]},
           "design": {"bead": bead, "nondesign_pids": design.get("nondesign_pids") or []},
           "deck": {"desmax": int(cfg["solve"]["desmax"]), "n_design_elems": dk.get("n_design_elems"),
                    "n_nondesign_elems": dk.get("n_nondesign_elems")},
           "history": hist, "bead_grid": rp.bead_grid(t.mesh, t.frame, bs["elem_h"], extra["design"],
                                                      cells=tuple(cfg["post"]["report_map_cells"])),
           "keepout_png": kpng, "sources": eo.load_method_sources()}
    rp.write(w.fresh_file(os.path.join(out, "report.html"), out), ctx)
    echo(f"[opt_post] 비드 최대 높이 {bs['height_max']:.3g} mm, 비드 면적 {bs['area_frac'] * 100:.1f} %, "
         f"{'수렴' if res['converged'] else '미수렴'} 반복 {res['iterations']}/{res['desmax']} → opt.json·report.html")
    for x in res.get("warnings") or []:
        echo(f"  경고: {x}")
    prog(100)
    return {"files": ["opt.json", "report.html"] + [f"post/{f}" for f in bs["files"]] + ["post/history.csv"]}


# ====================================================================== v0.9.0 비드 DOE(계약 esl_bead_doe.md §4·§6·§9)
# 코어 esl.doe 조립. 코어 단계(bd_*)는 자식 프로세스에서 ``esl.doe.stages.run_stage`` 1회 — 반환 dict(경고·요약)는
# ``<step 로그>.stage.json`` 으로 남겨 부모(doe_jobs)가 읽는다. paicad 판정·argv·보고 JSON 읽기(esl.doe.paicad_io)는
# 가벼운 순수 함수라 워커 부모 프로세스에서 쓴다(외부 실행은 paicad_proc). 쓰기는 spec["out"](= <esl_root>/_doe/<id>/)
# 아래만 — 코어 Writer 의 입력 목록(라이브러리 항목·① Case 입력·업로드)에는 쓰지 않는다.
DOE_STAGES = ("bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post")


def doe_paicad_io():
    """esl.doe.paicad_io(argv 템플릿·PROGRESS/RESULT·판정·버전·보고 JSON) — 워커가 코어와 같은 판정 기준을 쓰도록."""
    return _mod("esl.doe.paicad_io")


def doe_settings(cfg: dict | None) -> dict:
    """작업 스냅샷 cfg(bead_doe·opt_run·commands) → 코어 bead_doe 설정(기본값 위에 합침)."""
    return _attr("esl.doe", "settings")({"bead_doe": (cfg or {}).get("bead_doe") or {}})


def doe_stage_spec(spec: dict) -> dict:
    L = spec.get("lib") or {}
    doe = dict(L.get("doe") or {})
    doe.update(L.get("extra") or {})
    return {"stage": spec["stage"], "out": spec["out"], "progress_path": spec.get("progress_path"), "doe": doe}


def stage_out_path(log_path: str) -> str:
    return log_path[:-4] + ".stage.json" if log_path.endswith(".log") else log_path + ".stage.json"


def is_state_include(spec: str, path: str | None) -> bool:
    """include 가 Radioss 상태 파일(.sta/.str 확장자 또는 #RADIOSS STATE FILE 머리)인지 — 누적 씬 판정(esl_cumulative_input.md §2)."""
    st = _mod("esl.rad.state")
    return bool(st.has_state_ext(spec) or (path and st.is_state_file(path)))


VERIFY_STAGES = ("vd_patch", "vd_compare")       # = esl.verify.stages.STAGES(esl.pipeline.VERIFY_STAGES)


def run_verify_stage(spec: dict, echo: Callable[[str], None]) -> dict:
    """v0.12.0 검증 낙하 코어 단계 1개(자식 프로세스, 계약 esl_scx_relay.md SR6). spec["vd"] = esl.verify.stages 입력."""
    if spec.get("stage") not in VERIFY_STAGES:
        raise CoreError("INPUT_INVALID", f"알 수 없는 검증 낙하 단계: {spec.get('stage')}")
    run_stage = _attr("esl.verify.stages", "run_stage")
    vd = dict(spec.get("vd") or {})
    vd["stage"] = spec["stage"]
    _wrap(run_stage, vd, echo)
    return {}


def run_doe_stage(spec: dict, echo: Callable[[str], None]) -> dict:
    """비드 DOE 코어 단계 1개(자식 프로세스). spec["lib"] = {doe: 작업 params.doe, extra?: {design, paicad, …}}."""
    import json

    if spec.get("stage") not in DOE_STAGES:
        raise CoreError("INPUT_INVALID", f"알 수 없는 강성 평가 스터디 단계: {spec.get('stage')}")
    run_stage = _attr("esl.doe.stages", "run_stage")
    res = _wrap(run_stage, doe_stage_spec(spec), echo)
    U = _mod("esl.library._util")
    from esl_platform.core.atomic import write_text_atomic

    write_text_atomic(stage_out_path(spec["log_path"]), json.dumps(U.jsonable(res or {}), ensure_ascii=False))
    return res or {}


def doe_writer(out: str, doe: dict):
    """연구 폴더 Writer(입력 목록 = 코어 stages.Ctx 와 같음 — 항목·Case 입력·업로드 폴더 쓰기 거부)."""
    S = _mod("esl.doe.stages")
    return _wrap(lambda: S.Ctx({"doe": doe, "out": out}).writer)


def doe_fresh_dir(out: str, rel: str, doe: dict) -> str:
    """<out>/<rel> 를 빈 폴더로(이전 내용 → <out>/_backup/<UTC>/<rel>, 삭제 없음). 절대경로."""
    import os

    w = doe_writer(out, doe)
    return _wrap(w.fresh_dir, os.path.join(out, rel), out)


def doe_assem_full(out: str, doe: dict, starter: str, case_dir: str, roots: list[str], rel: str, *, max_mb: float,
                   max_depth: int, include_path_map: dict | None, engine_rad: bool, fixed_scan: dict | None) -> dict:
    """v0.12.1 모델 전체(starter include 트리) 사본 <out>/<rel>/ + 스캔 정규화(esl.doe.assem_full). 매니페스트."""
    import os

    A = _mod("esl.doe.assem_full")
    w = doe_writer(out, doe)
    _wrap(A.drop_derived, out, w.guard, (os.path.basename(rel),))     # 파생물 — _backup 에 쌓지 않고 삭제
    d = _wrap(w.makedirs, os.path.join(out, rel))
    return _wrap(A.copy_model_full, starter, case_dir, roots, d, max_mb=max_mb, include_path_map=include_path_map,
                 max_depth=max_depth, engine_rad=engine_rad, fixed_scan=fixed_scan, guard=w.guard)


def doe_assem_summary(man: dict) -> dict:
    return _mod("esl.doe.assem_full").summary(man)


def doe_restore_out_files(out: str, doe: dict, out_files_dir: str, rels: list[str], man: dict) -> int:
    """paicad run 모핑 사본 중 스캔 정규화한 파일 → 원본 + 모핑 /NODE 좌표."""
    w = doe_writer(out, doe)
    return _wrap(_mod("esl.doe.assem_full").restore_out_files, out_files_dir, rels, man, guard=w.guard)


def doe_assem_check(d: str, max_mb: float) -> dict:
    """조립 폴더(제자리) 검사: 링크·정션 거부, rad/inc 합계 상한(ASSEM_TOO_LARGE)."""
    return _wrap(_attr("esl.doe.scenario", "assem_dir_check"), d, max_mb)


def doe_design_sha(doe: dict, out: str, did: str) -> str:
    """BD-D-16 안 input_sha256(= bd_eval 이 done.json 에 쓰는 값) — 이어하기에서 paicad 를 다시 돌릴지 판단."""
    import os

    S = _mod("esl.doe.stages")
    ev = _mod("esl.doe.evaluate")
    U = _mod("esl.library._util")

    def calc() -> str:
        c = S.Ctx({"doe": doe, "out": out})
        bmeta = U.read_json(os.path.join(out, "prep", "base.json"))
        inp = U.read_json(os.path.join(out, "prep", "input.json"))
        values = S._design_values(c, did)
        return ev.input_sha256(values, bmeta["mesh_sha256"], (inp.get("loads") or {}).get("sha256"), S._cfg_hash(c),
                               doe.get("paicad_version"))
    return _wrap(calc)


def doe_record_design(doe: dict, out: str, did: str, status: str, code: str | None, message: str | None) -> None:
    """코어 평가 자식이 결과를 남기지 못하고 끝난 안(크래시·메모리) → result.json·done.json(상태 FAILED_* — 재시도 대상)."""
    import os

    S = _mod("esl.doe.stages")
    ev = _mod("esl.doe.evaluate")
    U = _mod("esl.library._util")

    def rec() -> None:
        c = S.Ctx({"doe": doe, "out": out})
        dd = S.design_dir(c, did)
        c.writer.makedirs(dd)
        doc = ev.result_doc(did, status, S._design_values(c, did), code=code, message=message)
        U.write_json(c.writer.guard(os.path.join(dd, ev.RESULT_JSON)), doc)
        ev.write_done(dd, doe_design_sha(doe, out, did), status, c.writer)
    _wrap(rec)


def doe_reusable(design_dir: str, sha: str) -> dict | None:
    return _wrap(_attr("esl.doe.evaluate", "reusable"), design_dir, sha)


def doe_parallel_limit(n_nodes: int, parallel: int, memory_margin: float, backend: str = "auto") -> dict:
    return _wrap(_attr("esl.doe.evaluate", "parallel_limit"), int(n_nodes), int(parallel), float(memory_margin), backend)


def doe_messages() -> dict:
    return _wrap(_attr("esl.doe", "load_messages"))
