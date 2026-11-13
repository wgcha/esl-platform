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
CELL_MAX_MM = 200.0

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
PLANS = {
    "case_once": {"dst": "baseline", "reuse": "once", "identity": "topo", "placement": "global", "mask": "none",
                  "truth": "self_direct", "alt_designs": False,
                  "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "all", "sm_rank": "metric"},
    "bmesh_once": {"dst": "baseline", "reuse": "once", "identity": "none", "placement": "auto", "mask": "none",
                   "truth": "a_direct", "alt_designs": False,
                   "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "all", "sm_rank": "metric"},
    "step_once": {"dst": "baseline", "reuse": "once", "identity": "none", "placement": "auto", "mask": "step_region",
                  "truth": "a_direct", "alt_designs": False,
                  "sm_ref": "base", "sm_disp": ("I", "I"), "sm_omega": "step_region", "sm_rank": "metric"},
    "step_per_design": {"dst": "design", "reuse": "per_target", "identity": "none", "placement": "auto", "mask": "none",
                        "truth": "a_direct", "alt_designs": False,
                        "sm_ref": "none", "sm_disp": ("none", "none"), "sm_omega": "all", "sm_rank": "solve"},
    "compare_per_shape": {"dst": "shape", "reuse": "per_target", "identity": "topo+coords", "placement": "global",
                          "mask": "compare_region", "truth": "compare", "alt_designs": True,
                          "sm_ref": "none", "sm_disp": ("none", "none"), "sm_omega": "compare_region",
                          "sm_rank": "solve"},
}
PLAN_COLS = ("dst", "reuse", "identity", "placement", "mask", "truth", "alt_designs", "sm_ref", "sm_disp", "sm_omega",
            "sm_rank")
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
    if not float(w.get("fail_dist_mm", 20.0)) > 0 or not 0.0 <= float(w.get("fail_frac", 0.2)) <= 1.0:
        bad("work.fail_dist_mm > 0, 0 ≤ fail_frac ≤ 1")
    return lt


def metric_effective(plan: dict, metric: str) -> str:
    """순위에 실제로 쓰는 지표(결정 A): 계획 열 sm_rank = metric 이면 스냅샷 metric 그대로, solve 면 solve(다른 메시 비교)."""
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
