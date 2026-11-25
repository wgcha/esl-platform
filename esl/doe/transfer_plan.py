"""하중 전달 계획 표 — 모드 차이는 이 표 한 곳(계약 esl_load_transfer.md §13.3 D-0.20.0-LT-16, §13.6 LT-19).

``PLANS``(상수) · ``plan_for(scenario, select_base)`` · ``resolve(spec_lt, scenario)``(스냅샷 → 해석된 설정) · ``PLAN_VERSION``.
공용 모듈 ``load_transfer`` 를 쓰는 쪽(stages)이 이 표를 읽어 dst·재사용·identity 키·배치 종류·영역·참값·alt 를 정한다.
"""
from __future__ import annotations

import copy

from esl.errors import EslError

PLAN_VERSION = 1
SCHEMA = 1
METHODS = ("work", "cell")
SUPPORTS = ("transfer", "auto")
REGION_MODES = ("auto", "a_bbox", "largest", "all")
ALT_DESIGNS = ("auto", "on", "off")
CELL_MAX_MM = 200.0          # 셀 크기 상한 — 한 곳(backend core.config.LT_CELL_MAX_MM 가 이 값을 import)

# id: (시나리오, select_base) 열쇠 → 계획. dst: baseline(기준 메시) | design(안마다 메시) | shape(형상마다 메시).
# reuse: once(베이스라인 1회 → 모든 안 같은 노드 하중, BD-D-3) | per_target(베이스라인 포함 대상마다 같은 규칙).
# identity: 같은 메시 판정 키(work 일 때만 — LT-22). placement: global | auto(②③ frame 판정 — LT-23).
# mask: 대상 활성 요소(none | step_region = ③ 평가 영역 | compare_region = ④ LT-8). truth: 베이스라인 참값.
# sm_ref·sm_disp·sm_omega·sm_rank(esl_stiffness_metric.md §4, 결정 A 2026-11-13 — 강성 지표는 같은 메시(같은 위상) 안에서만):
#   sm_ref  = 참조 변위 base(베이스라인 d000 해 — ① 원본 하중, ②·새 ③ work 하중으로 기준 메시에서 직접 푼 해) | none(지표 미적용)
#   sm_disp = 변위 전달(베이스라인, 안) I(같은 노드) | none. interp(load_transfer.build_disp, A → 대상 C0 병진 보간)는 지표 경로에서
#             쓰지 않음: 같은 기하에서도 A 요소 경계 꺾임이 대상 메시에 가짜 굽힘·전단 에너지를 넣어 ρ 를 왜곡(성긴 대상 1.62,
#             2배 촘촘 12.3, 회전 응축 11.9 — esl_stiffness_metric.md §2.1). 코드·시험은 남김(계획 표에서 비활성).
#   sm_omega = 강체 제거·에너지 범위(all | step_region | compare_region), sm_rank = 순위 지표 metric(스냅샷 rank.metric) |
#   solve(다른 메시 비교 — 형상·안마다 work 하중 재풀이 C, 경고 SM_CROSS_MESH, 결과 metric_effective = solve).
# v0.21.0 BEAD_SHAPE 열(esl_bead_shape_v021.md §2.2 SH-2 — 값 none = 그 모드에 항목 없음):
#   bs_wpart = graph(그래프 비드 W 를 W 가능 구간 S_W 에만) | none,  bs_guard = basis(그 모드 기준 메시 위 그래프 기저로 range guard) | none,
#   bs_route = base(기준 STEP 1개 cad_relaxed 직행 판정) | shapes(형상 STEP 마다) | none,
#   bs_mq    = base(기준 메시 품질 → 결과 경고 1건) | shapes(형상마다 → 순위 행 ⚠) | none.
#   스냅샷 doe.shape_rules 가 있을 때만 쓰임(키 없음 = v0.20.0). PLAN_VERSION 은 올리지 않음(hash_view 불변) — 규칙 판은 shape_rules.schema.
PLANS = {
    "case_once": {"redrop": "node_id", "dst": "baseline", "reuse": "once", "identity": "topo", "placement": "global", "mask": "none",
                  "truth": "self_direct", "alt_designs": False,
                  "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "all", "sm_rank": "metric",
                  "bs_wpart": "graph", "bs_guard": "basis", "bs_route": "none", "bs_mq": "none",
                 "sm_jig": "base", "jig_fix": "fixed", "jig_ctx": "case", "bf": "base"},
    "bmesh_once": {"redrop": "none", "dst": "baseline", "reuse": "once", "identity": "none", "placement": "auto", "mask": "none",
                   "truth": "a_direct", "alt_designs": False,
                   "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "all", "sm_rank": "metric",
                   "bs_wpart": "graph", "bs_guard": "basis", "bs_route": "none", "bs_mq": "none",
                  "sm_jig": "base", "jig_fix": "fixed", "jig_ctx": "mesh", "bf": "base"},
    "step_once": {"redrop": "none", "dst": "baseline", "reuse": "once", "identity": "none", "placement": "auto", "mask": "step_region",
                  "truth": "a_direct", "alt_designs": False,
                  "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "step_region", "sm_rank": "metric",
                  "bs_wpart": "graph", "bs_guard": "basis", "bs_route": "base", "bs_mq": "base",
                 "sm_jig": "base", "jig_fix": "xfer", "jig_ctx": "none", "bf": "base"},
    "step_per_design": {"redrop": "none", "dst": "design", "reuse": "per_target", "identity": "none", "placement": "auto", "mask": "none",
                        "truth": "a_direct", "alt_designs": False,
                        "sm_ref": "none", "sm_disp": ("none", "none"), "sm_omega": "all", "sm_rank": "solve",
                        "bs_wpart": "none", "bs_guard": "none", "bs_route": "none", "bs_mq": "none",
                       "sm_jig": "none", "jig_fix": "grid", "jig_ctx": "shape", "bf": "none"},
    "compare_per_shape": {"redrop": "none", "dst": "shape", "reuse": "per_target", "identity": "topo+coords", "placement": "global",
                          "mask": "compare_region", "truth": "compare", "alt_designs": True,
                          "sm_ref": "none", "sm_disp": ("none", "none"), "sm_omega": "compare_region",
                          "sm_rank": "solve",
                          "bs_wpart": "none", "bs_guard": "none", "bs_route": "shapes", "bs_mq": "shapes",
                         "sm_jig": "none", "jig_fix": "grid", "jig_ctx": "shape", "bf": "none"},
}
PLAN_COLS = ("dst", "reuse", "identity", "placement", "mask", "truth", "alt_designs", "sm_ref", "sm_disp", "sm_omega",
            "sm_rank", "redrop", "bs_wpart", "bs_guard", "bs_route", "bs_mq", "sm_jig", "jig_fix", "jig_ctx", "bf")
PLAN_OF = {("same", None): "case_once", ("select", "case"): "case_once", ("mesh", None): "bmesh_once",
           ("select", "mesh"): "bmesh_once", ("select", "step"): "step_once", ("step", None): "step_per_design",
           ("compare", None): "compare_per_shape"}


def plan_for(scenario: str, select_base: str | None = None) -> dict:
    """(시나리오, select_base) → 계획 dict(+ id). 모르는 조합 = CONFIG_INVALID."""
    key = (str(scenario), select_base if scenario == "select" else None)
    pid = PLAN_OF.get(key)
    if pid is None:
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 없음: {key}")
    row = PLANS[pid]
    miss = [k for k in PLAN_COLS if row.get(k) in (None, "", ())]
    if miss:                                     # 새 계획 행은 모든 열을 채움(빈 칸 = CONFIG_INVALID)
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid} 빈 열: {miss}")
    badv = [k for k, vs in BS_VALUES.items() if row[k] not in vs]
    if badv:
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid} 형상 규칙 열 값 오류: {badv}")
    badj = [k for k, vs in JIG_VALUES.items() if row[k] not in vs]
    if badj:
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid} 지그 열 값 오류: {badj}")
    _check_jig_cols(pid, row)
    if row["bf"] not in BF_VALUES:
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid} bf 열 값 오류: {row['bf']}")
    if row["redrop"] not in RD_VALUES:
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid} redrop 열 값 오류: {row['redrop']}")
    return {"id": pid, **row}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def resolve(spec_lt: dict | None, scenario: str, defaults: dict | None = None) -> dict | None:
    """스냅샷 ``doe.load_transfer``(평면 — compare 만 support·support_tol_mm·region 포함) → 기본값 위에 합친 설정.
    None = legacy(키 없음). defaults = bead_doe 설정(없으면 DEFAULTS) — 공통 = ``load_transfer``, ④ = ``compare.load_transfer``."""
    if spec_lt is None:
        return None
    if not isinstance(spec_lt, dict):
        raise EslError("CONFIG_INVALID", "load_transfer 는 매핑이어야 함")
    if defaults is None:
        from esl.doe import DEFAULTS as defaults
    base = copy.deepcopy(defaults["load_transfer"])
    if scenario == "compare":
        base.update(copy.deepcopy(defaults["compare"]["load_transfer"]))
    lt = _merge(base, copy.deepcopy({k: v for k, v in spec_lt.items() if k != "schema"}))

    def bad(msg):
        raise EslError("CONFIG_INVALID", f"load_transfer.{msg}")
    if lt["method"] not in METHODS:
        bad("method work|cell")
    if scenario == "compare":
        if lt["support"] not in SUPPORTS:
            bad("support transfer|auto")
        if (lt.get("region") or {}).get("mode") not in REGION_MODES:
            bad("region.mode auto|a_bbox|largest|all")
    cmin = float(lt["cell_min_mm"])
    for k, v in (("cell_size_mm", lt["cell_size_mm"]), ("diag.alt_cell_size_mm", lt["diag"]["alt_cell_size_mm"])):
        if v is not None and not cmin <= float(v) <= CELL_MAX_MM:
            raise EslError("LOAD_TRANSFER_INVALID", f"load_transfer.{k} {v} 는 {cmin:g}..{CELL_MAX_MM:g} mm")
    if lt["method"] == "work":                   # work 의 해석값 cell_size_mm = null(요청 검사는 backend 422)
        lt["cell_size_mm"] = None
    if lt["diag"].get("alt_designs", "auto") not in ALT_DESIGNS:
        bad("diag.alt_designs auto|on|off")
    w = lt["work"]
    if not 1 <= int(w["knn"]) <= 64 or not 1 <= int(w["newton_iter"]) <= 50:
        bad("work.knn 1..64, newton_iter 1..50")
    if not 0.0 <= float(w["far_warn_frac"]) <= float(w["far_fail_frac"]) <= 1.0:
        bad("work 0 ≤ far_warn_frac ≤ far_fail_frac ≤ 1")
    if not float(w["fail_dist_mm"]) > 0 or not 0.0 <= float(w["fail_frac"]) <= 1.0:
        bad("work.fail_dist_mm > 0, 0 ≤ fail_frac ≤ 1")
    return lt


# v0.22.0 REDROP 열(esl_redrop_bundle.md §5.2): 재낙하 입력 좌표 치환 방식 — node_id(원 Case 노드 ID 그대로 /NODE 패치) | none(새 메시·새 ID).
RD_VALUES = ("node_id", "none")
# v0.24.0 BFORCE 열(esl_bforce.md §5.1): 경계력 ESL — base(베이스라인 1회 하중 → 같은 메시 안 비교, 결정 A) | none(다른 메시 — BF_UNSUPPORTED).
BF_VALUES = ("base", "none")
BS_VALUES = {"bs_wpart": ("graph", "none"), "bs_guard": ("basis", "none"), "bs_route": ("base", "shapes", "none"),
             "bs_mq": ("base", "shapes", "none")}
SHAPE_SCHEMA = 1
# v0.23.0 JIG 열(esl_jig_rank.md §5.2): sm_jig = base(베이스라인 1회 지그 계산 → 같은 메시 안 비교) | none, jig_fix = 지그 노드 출처
# fixed(prep/fixed) | xfer(A 체결점 이전) | none, jig_ctx = 다른 부품 deck 출처 case(원 Case) | mesh(업로드 사본) | none(패치).
# v0.24.8 JG(esl_jig_grid_map.md §2.2 D-0.24.8-JG-6): jig_fix += grid(Case 지그 골격을 형상에서 잡기 — 형상마다 격자 지그),
# jig_ctx += shape(가압 하중 문맥 = Case 맞춤 하중의 형상 셀 전달 — deck·영역 재계산 없음). grid ⇔ shape, grid ⇒ sm_jig none ∧ sm_ref none.
JIG_VALUES = {"sm_jig": ("base", "none"), "jig_fix": ("fixed", "xfer", "grid", "none"),
              "jig_ctx": ("case", "mesh", "shape", "none")}
JIG_KINDS = ("base", "grid", "none")


def _check_jig_cols(pid: str, row: dict) -> None:
    """지그 열 불변식(위반 = CONFIG_INVALID): jig_fix grid ⇔ jig_ctx shape, grid ⇒ sm_jig none ∧ sm_ref none ∧ dst ∈ {design, shape},
    sm_jig base ⇒ jig_fix ∈ {fixed, xfer} ∧ jig_ctx ∈ {case, mesh, none}."""
    g = row["jig_fix"] == "grid"
    if g != (row["jig_ctx"] == "shape"):
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid}: jig_fix grid ⇔ jig_ctx shape")
    if g and not (row["sm_jig"] == "none" and row["sm_ref"] == "none" and row["dst"] in ("design", "shape")):
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid}: jig_fix grid ⇒ sm_jig none ∧ sm_ref none ∧ dst design|shape")
    if row["sm_jig"] == "base" and not (row["jig_fix"] in ("fixed", "xfer") and row["jig_ctx"] in ("case", "mesh", "none")):
        raise EslError("CONFIG_INVALID", f"하중 전달 계획 {pid}: sm_jig base ⇒ jig_fix fixed|xfer ∧ jig_ctx case|mesh|none")


def jig_kind(plan: dict, grid_snap: bool) -> str:
    """지그 종류 판정 한 곳(코어 ``stages._jg_kind``·백엔드 jig_plan 공용 — D-0.24.8-JG-6): base = 계획 sm_jig base(같은 메시 지그),
    grid = 계획 jig_fix grid ∧ grid_snap(스냅샷 rank.jig enabled ∧ rank.jig_grid enabled), 그 밖 none(옛 스냅샷·설정 끔)."""
    if plan["sm_jig"] == "base":
        return "base"
    if plan["jig_fix"] == "grid" and bool(grid_snap):
        return "grid"
    return "none"


def resolve_shape(spec: dict | None, defaults: dict | None = None, *, flip_deg: float | None = None) -> dict | None:
    """스냅샷 ``doe.shape_rules``(또는 설정 절 ``bead_doe.shape_rules``) → 해석된 규칙. None = legacy(키 없음·꺼짐).
    defaults = bead_doe 설정(없으면 DEFAULTS). 설정 절을 넘기면(``enabled`` 키 있음) 기본 위에 합치고, 꺼짐(enabled false)이면 None.
    flip_deg = select.quality.flip_deg(None → defaults). range_guard 꺼짐 → ``range_guard`` None. 잘못된 블록 = CONFIG_INVALID."""
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise EslError("CONFIG_INVALID", "shape_rules 는 매핑이어야 함")
    if defaults is None:
        from esl.doe import DEFAULTS as defaults
    if spec.get("enabled") is False:
        return None
    base = copy.deepcopy(defaults["shape_rules"])
    sr = _merge(base, copy.deepcopy({k: v for k, v in spec.items() if k not in ("schema", "enabled")}))

    def bad(msg):
        raise EslError("CONFIG_INVALID", f"shape_rules.{msg}")

    def num(v, lo, hi, *, lo_open=True, hi_open=False):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and (v > lo if lo_open else v >= lo) and \
            (v < hi if hi_open else v <= hi)
    if not isinstance(sr.get("w_partial"), bool):
        bad("w_partial bool")
    rg = sr.get("range_guard")
    if rg is not None:
        if not isinstance(rg, dict):
            bad("range_guard 는 매핑이어야 함")
        if rg.get("enabled") is False:
            rg = None
    if rg is not None:
        rg = dict(rg)
        rg.pop("enabled", None)
        if "flip_deg" not in rg:
            rg["flip_deg"] = float(flip_deg if flip_deg is not None else defaults["select"]["quality"]["flip_deg"])
        if not num(rg["jac_min"], 0, 1, hi_open=True):
            bad("range_guard.jac_min (0, 1)")
        if not num(rg["tria_angle_min_deg"], 0, 60, hi_open=True):
            bad("range_guard.tria_angle_min_deg (0, 60)")
        if not num(rg["area_ratio_min"], 0, 1, hi_open=True):
            bad("range_guard.area_ratio_min (0, 1)")
        if rg["max_new_fail_ratio"] is not None and not num(rg["max_new_fail_ratio"], 0, 1):
            bad("range_guard.max_new_fail_ratio null | (0, 1]")
        if not isinstance(rg["steps"], int) or isinstance(rg["steps"], bool) or not 1 <= rg["steps"] <= 20:
            bad("range_guard.steps 1..20")
        if not num(rg["min_keep_frac"], 0, 1, lo_open=False, hi_open=True):
            bad("range_guard.min_keep_frac [0, 1)")
        cb = rg["combo"]
        for k, lo, hi in (("full_max_vars", 1, 8), ("samples", 1, 256), ("max_group", 2, 32)):
            if not isinstance(cb[k], int) or isinstance(cb[k], bool) or not lo <= cb[k] <= hi:
                bad(f"range_guard.combo.{k} {lo}..{hi}")
        if not isinstance(cb["enabled"], bool):
            bad("range_guard.combo.enabled bool")
        bg = rg["budget"]
        if not num(bg["prep_timeout_s"], 0, 3600) or not num(bg["matrix_timeout_s"], 0, 3600):
            bad("range_guard.budget.*_timeout_s (0, 3600]")
        for k, hi in (("max_evals", 1_000_000), ("max_vars", 2000)):
            if not isinstance(bg[k], int) or isinstance(bg[k], bool) or not 1 <= bg[k] <= hi:
                bad(f"range_guard.budget.{k} 1..{hi}")
    mr = sr["mesh_route"]
    rd = mr["relaxed_direct"]
    if not isinstance(rd["enabled"], bool):
        bad("mesh_route.relaxed_direct.enabled bool")
    if rd["min_faces"] is not None and (not isinstance(rd["min_faces"], int) or isinstance(rd["min_faces"], bool)
                                        or rd["min_faces"] < 1):
        bad("mesh_route.relaxed_direct.min_faces null | >= 1")
    if rd["min_step_mb"] is not None and not num(rd["min_step_mb"], 0, float("inf")):
        bad("mesh_route.relaxed_direct.min_step_mb null | > 0")
    rq = dict(mr["rank_quality"])
    if not num(rq["fail_ratio"], 0, 1):
        bad("mesh_route.rank_quality.fail_ratio (0, 1]")
    if rq["tria_pct"] is None:                   # null → compare.quality.tria_pct.fail 로 고정(SH-22)
        rq["tria_pct"] = float(defaults["compare"]["quality"]["tria_pct"]["fail"])
    elif not num(rq["tria_pct"], 0, 100):
        bad("mesh_route.rank_quality.tria_pct null | (0, 100]")
    return {"schema": SHAPE_SCHEMA, "w_partial": bool(sr["w_partial"]), "range_guard": rg,
            "mesh_route": {"relaxed_direct": dict(rd), "rank_quality": rq}}


def shape_hash_view(rules: dict | None) -> dict | None:
    """새 스냅샷 선택 설정 해시 기여(SH-26): schema·w_partial·range_guard 의 crit·steps·min_keep_frac·combo(budget 제외). None = 기여 없음."""
    if rules is None:
        return None
    rg = rules.get("range_guard")
    if rg is not None:
        rg = {k: rg[k] for k in sorted(rg) if k != "budget"}
    return {"schema": rules.get("schema"), "w_partial": rules.get("w_partial"), "range_guard": rg}


def metric_effective(plan: dict, metric: str, jig_ok: bool = True, kind: str | None = None) -> str:
    """순위에 실제로 쓰는 지표(결정 A): 계획 열 sm_rank = metric 이면 스냅샷 metric 그대로, solve 면 solve(다른 메시 비교).
    metric = jig 는 계획 sm_jig = base ∧ sm_rank = metric ∧ jig_ok(베이스라인 지그 status ok) 일 때만 jig, 아니면 solve(D-JIG-8).
    v0.24.8 kind(``jig_kind`` 값): None = 위 식 그대로(기존 호출 바이트 동일), "grid" ∧ metric jig ∧ jig_ok → jig(격자 지그 순위)."""
    if kind == "grid" and str(metric) == "jig" and jig_ok:
        return "jig"
    if str(metric) == "jig":
        return "jig" if plan["sm_jig"] == "base" and plan["sm_rank"] == "metric" and jig_ok else "solve"
    return str(metric) if plan["sm_rank"] == "metric" else "solve"


def cross_mesh(plan: dict) -> bool:
    """다른 메시 비교(강성 지표 미적용 — 경고 SM_CROSS_MESH) 계획인가."""
    return plan["sm_rank"] != "metric"


def method_of(lt: dict, variant: tuple | None = None, mapping_opts: dict | None = None) -> dict:
    """해석된 설정(+ variant (method, cell_size_mm)) → load_transfer Method dict."""
    m, s = variant if variant is not None else primary_variant(lt)
    return {"name": m, "cell_size_mm": None if m == "work" else s, "work": lt["work"], "mapping_opts": mapping_opts,
            "cell_min_mm": lt["cell_min_mm"]}


def primary_variant(lt: dict) -> tuple[str, float | None]:
    return str(lt["method"]), (None if lt["method"] == "work" else lt.get("cell_size_mm"))


def alt_variant(lt: dict) -> tuple[str, float | None] | None:
    """다른 방식(diag.alt): work ↔ cell(alt_cell_size_mm). 진단 끔·alt 끔 = None."""
    dg = lt.get("diag") or {}
    if not dg.get("enabled") or not dg.get("alt"):
        return None
    if lt["method"] == "work":
        return "cell", dg.get("alt_cell_size_mm")
    return "work", None


def alt_designs(lt: dict, plan: dict) -> bool:
    """안마다 score_alt(LT-20): auto = 계획 표 열(④ 켬, ①②③ 끔), on|off 강제. alt 없음 = 거짓."""
    if alt_variant(lt) is None:
        return False
    v = (lt.get("diag") or {}).get("alt_designs", "auto")
    return bool(plan["alt_designs"]) if v == "auto" else v == "on"


def variant_label(method: str, cell_size_mm) -> str:
    if method == "cell":
        return "cell:legacy" if cell_size_mm is None else f"cell:{float(cell_size_mm):g}"
    return str(method)


def sweep_variants(lt: dict) -> list[tuple[str, float | None]]:
    """베이스라인 진단 variant(중복 제거, 순서 = 주 → alt → cell_sweep_mm)."""
    dg = lt.get("diag") or {}
    out = [primary_variant(lt)]
    if not dg.get("enabled"):
        return out
    a = alt_variant(lt)
    if a is not None:
        out.append(a)
    for s in dg.get("cell_sweep_mm") or []:
        out.append(("cell", None if s is None else float(s)))
    seen, uniq = set(), []
    for m, s in out:
        k = variant_label(m, s)
        if k not in seen:
            seen.add(k)
            uniq.append((m, s))
    return uniq


def hash_view(lt: dict) -> dict:
    """이어하기 해시 대상(LT-12·LT-18 — diag 제외, ④ 키는 있을 때만, 계획 표 버전 포함)."""
    out = {k: lt.get(k) for k in ("method", "cell_size_mm", "work")}
    for k in ("support", "support_tol_mm", "region"):
        if k in lt:
            out[k] = lt.get(k)
    out["plan_version"] = PLAN_VERSION
    return out


def public(lt: dict) -> dict:
    """결과·준비 요약 {method, cell_size_mm} (+ ④ support·region_mode)."""
    out = {"method": lt["method"], "cell_size_mm": lt.get("cell_size_mm")}
    if "support" in lt:
        out.update(support=lt["support"], region_mode=(lt.get("region") or {}).get("mode"))
    return out
