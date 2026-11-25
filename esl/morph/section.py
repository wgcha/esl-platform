"""비드 깊이 단면 동작(depth_section) — 모드 무관 순수 모듈(계약 esl_bead_depth_mode.md §1.5, AGENTS.md D-0.20.0-CODE).

numpy 만 쓴다. ``esl.doe``·``beadgraph`` import 금지, 파일 IO·설정 해석 금지 — 값은 인수로 받는다.
모드 차이는 ``SECTION_PLANS`` 한 곳(행 = 변수 출처, 열 = 동작). 호출 쪽(bead_graph·bead_select·paicad_io·stages)은 열 값으로
공용 함수를 고르고 시나리오 이름으로 분기하지 않는다.

- entry_fixed = 지금 모드별 동작(입구 고정, 그래프 깊이면 축소 — main 바이트). 키 없음(옛 스냅샷) = LEGACY_DEPTH_SECTION.
- floor_fixed = 깊이면 폭 유지 + 사면 각 고정 + 입구 넓어짐(그래프 = 패키지 kind DF, elems = 조합 B_D + 2cotθ·B_W(f=0))
  + 한쪽 입구 W1 변수(그래프만).
"""
from __future__ import annotations

import math

import numpy as np

from esl.errors import EslError

DEPTH_SECTIONS = ("entry_fixed", "floor_fixed")
LEGACY_DEPTH_SECTION = "entry_fixed"        # 키 없는 옛 스냅샷의 동작 — 값 고정이 목적(D-0.24.5-VT-16 선례)

PLAN_COLUMNS = ("compose", "one_side", "theta", "feasible", "fig", "na")
# 행 = 변수 출처(행을 만드는 쪽이 아는 값). compose: pkg_df(패키지 kind DF)|select_w_f0(elems 조합)|none(= entry_fixed),
# one_side: pkg_w1(W1 변수·사유 판정)|none, theta: none(DF 가 노드마다)|run_med(elems), feasible: open_cap|none,
# fig: floor_center|stretch|none(단면 그림 ds_dD), na: none|DS_ENGINE_NATIVE(적용 안 함 정보 코드)
SECTION_PLANS = {
    "graph": {"compose": "pkg_df", "one_side": "pkg_w1", "theta": "none", "feasible": "open_cap",
              "fig": "floor_center", "na": "none"},
    "elems": {"compose": "select_w_f0", "one_side": "none", "theta": "run_med", "feasible": "open_cap",
              "fig": "stretch", "na": "none"},
    "paicad": {"compose": "none", "one_side": "none", "theta": "none", "feasible": "none", "fig": "none",
               "na": "DS_ENGINE_NATIVE"},
    "none": {"compose": "none", "one_side": "none", "theta": "none", "feasible": "none", "fig": "none", "na": "none"},
}

# W 사용 불가 사유(§4.1 — 첫 일치, 순서 고정)
W_REASON_ORDER = ("W_USER_OFF", "W_NETWORK", "W_AREA", "W_EDIT_MERGED", "W_TIE_MIXED", "W_ONE_SIDE_EDGE",
                  "W_ENTRY_NONE", "W_ENTRY_ONE_SIDE", "W_PARTIAL_OLD", "W_OPEN_BOUNDARY", "W_WIDTH_UNDEFINED",
                  "W_PAICAD_NONE")
# W 행 있음 + 기본 끔 사유(§4.1)
W_DEFAULT_OFF = ("W_SHORT", "W_GUARD_BLOCKED", "W_FIXED_SKIP", "W_PAICAD_DEFAULT_OFF")
W_ONE_SIDE = "W_ONE_SIDE"                   # W 행이 W1(한쪽) — 사유 아님, 표시용


def plan(row: str, plans: dict | None = None) -> dict:
    """계획 행 1개 — 모든 열 필수(빈 칸·모르는 행 = CONFIG_INVALID)."""
    p = (plans or SECTION_PLANS).get(row)
    if p is None:
        raise EslError("CONFIG_INVALID", f"SECTION_PLANS 에 행 {row!r} 없음")
    miss = [c for c in PLAN_COLUMNS if not p.get(c)]
    if miss:
        raise EslError("CONFIG_INVALID", f"SECTION_PLANS[{row}] 빈 열 {miss}")
    return p


def validate_plans(plans: dict | None = None) -> None:
    for r in (plans or SECTION_PLANS):
        plan(r, plans)


def resolve(value) -> str:
    """스냅샷 값 → 동작. None(키 없음) = LEGACY_DEPTH_SECTION, 모르는 값 = CONFIG_INVALID."""
    if value is None:
        return LEGACY_DEPTH_SECTION
    if value not in DEPTH_SECTIONS:
        raise EslError("CONFIG_INVALID", f"depth_section {value!r} 는 {list(DEPTH_SECTIONS)} 중 하나")
    return str(value)


def is_floor(value) -> bool:
    return resolve(value) == "floor_fixed"


def row_plan(value, row: str, plans: dict | None = None) -> dict:
    """동작 + 행 → 실제로 쓸 계획(entry_fixed 면 모든 열 none — 지금 경로·바이트)."""
    p = plan(row, plans)
    if not is_floor(value):
        return dict(SECTION_PLANS["none"])
    return dict(p)


# ---------------------------------------------------------------- θ
def _deg_of_cot(c):
    if c is None or not math.isfinite(float(c)) or float(c) <= 0.0:
        return None
    return round(math.degrees(math.atan(1.0 / float(c))), 3)


def cot_from_run(run_med, D, rules: dict) -> tuple[float | None, str | None]:
    """elems: cotθ = run_med / D. run_med ≤ 0 ∨ θ < theta_min_deg → (None, 'THETA_UNMEASURED')."""
    try:
        run, d = float(run_med), float(D)
    except (TypeError, ValueError):
        return None, "THETA_UNMEASURED"
    if not (math.isfinite(run) and math.isfinite(d)) or run <= 0.0 or d <= 0.0:
        return None, "THETA_UNMEASURED"
    cot = run / d
    if math.degrees(math.atan(1.0 / cot)) < float(rules["theta_min_deg"]):
        return None, "THETA_UNMEASURED"
    return cot, None


def theta_spread(run_lo, run_hi, D, rules: dict) -> dict | None:
    """elems: 경계 거리 5·95 백분위 run 으로 잰 θ 차 > theta_spread_deg → {min_deg, max_deg} (정보 DS_THETA_SPREAD)."""
    a, b = _deg_of_cot(float(run_hi) / float(D)) if D else None, _deg_of_cot(float(run_lo) / float(D)) if D else None
    if a is None or b is None:
        return None
    lo, hi = min(a, b), max(a, b)
    return {"min_deg": lo, "max_deg": hi} if hi - lo > float(rules["theta_spread_deg"]) else None


def cot_from_df(info: dict) -> dict:
    """패키지 DF info(cot_min/med/max) → 도(°) — θ = atan(1/cot). 측정 없음 = None."""
    return {"cot_min_deg": _deg_of_cot(info.get("cot_max")), "cot_med_deg": _deg_of_cot(info.get("cot_med")),
            "cot_max_deg": _deg_of_cot(info.get("cot_min")), "cot_med": info.get("cot_med")}


# ---------------------------------------------------------------- elems 조합(§1.2.2)
def compose(d_idx, d_vec, parts) -> tuple[np.ndarray, np.ndarray]:
    """희소 기저 합 B'_D = B_D + Σ k·B_part. parts = [(idx, vec, k)…] → (idx 정렬, vec)."""
    idx = [np.asarray(d_idx, np.int64)] + [np.asarray(p[0], np.int64) for p in parts]
    allx = np.unique(np.concatenate(idx)) if idx else np.zeros(0, np.int64)
    out = np.zeros((allx.size, 3))
    pos = np.searchsorted(allx, np.asarray(d_idx, np.int64))
    np.add.at(out, pos, np.asarray(d_vec, float))
    for i, v, k in parts:
        pos = np.searchsorted(allx, np.asarray(i, np.int64))
        np.add.at(out, pos, float(k) * np.asarray(v, float))
    keep = np.any(out != 0.0, axis=1)
    return allx[keep], out[keep]


def w_virtual_range(W_nom: float, dD_ext: float, cot: float) -> list[float]:
    """elems 조합의 입구 폭 변화 범위(진단) = W_nom ± 2·ΔD_ext·cotθ."""
    d = 2.0 * float(dD_ext) * float(cot)
    return [float(W_nom) - d, float(W_nom) + d]


# ---------------------------------------------------------------- feasible(§2.1)
def feasible_open_cap(D_nom: float, parts, cot, depth_max_rel: float, width_max_rel: float) -> float:
    """floor_fixed D 상한 = min(D_nom(1 + depth_max_rel), D_nom + W_ref·width_max_rel/(m·cot)) — 입구 확장 상한.
    parts = [(W_ref, m)…] (빈 = D_nom(1 + depth_max_rel) 만)."""
    hi = float(D_nom) * (1.0 + float(depth_max_rel))
    if cot is None or float(cot) <= 0.0:
        return hi
    for W_ref, m in parts or ():
        if W_ref is None:
            continue
        hi = min(hi, float(D_nom) + float(W_ref) * float(width_max_rel) / (float(m) * float(cot)))
    return hi


def w_lo_floor_fixed(W_nom: float, D_nom: float, cot, W_floor_min: float) -> float:
    """floor_fixed 양쪽 W 하한 = W_nom − (W_top_nom − W_floor_min), W_top_nom = W_nom − 2·D_nom·cot."""
    c = 1.0 if cot is None else float(cot)
    W_top = float(W_nom) - 2.0 * float(D_nom) * c
    return float(W_nom) - (W_top - float(W_floor_min))


def w1_feasible(W1_nom: float, F_nom: float, W_floor_min: float, width_max_rel: float) -> list[float]:
    """W1: 하한 = W1_nom − (F_nom − W_floor_min), 상한 = W1_nom·(1 + width_max_rel)."""
    return [float(W1_nom) - (float(F_nom) - float(W_floor_min)), float(W1_nom) * (1.0 + float(width_max_rel))]


# ---------------------------------------------------------------- 단면 그림(§4·§7 SectionMini)
def fig_ds_dD(s, z, D_nom, cot, row: str, R_w=None, side=None, floor_mode=True) -> list[float]:
    """단면 점(s 가로, z 깊어짐 +)의 ds/dD. ``row`` = 계획 fig 열:
    floor_center(그래프): floor_mode(DF) = 깊이면 0·사면 (1 − t)·cot 바깥·입구 cot(t = clip(z/D)), entry_fixed(D) = 깊이면
    가장자리가 안쪽으로 t·cot(입구 0); stretch(elems) = floor_mode 면 floor_center 와 같은 식, 아니면 0; none = 0.
    side = +1|−1 이면 그 쪽(s − s_c 부호)만 움직임(한쪽 비드). 바깥 판 = 0."""
    s = np.asarray(s, float)
    z = np.asarray(z, float)
    out = np.zeros(s.size)
    D = float(D_nom or 0.0)
    if row == "none" or D <= 0.0 or s.size == 0 or cot is None:
        return [0.0] * int(s.size)
    if row == "stretch" and not floor_mode:
        return [0.0] * int(s.size)
    t = np.clip(z / D, 0.0, 1.0)
    inb = z > 1e-9
    if not inb.any():
        return [0.0] * int(s.size)
    fl = z >= D - 1e-6
    sc = 0.5 * (float(s[fl].min()) + float(s[fl].max())) if fl.any() else float(np.median(s[inb]))
    sg = np.sign(s - sc)
    c = float(cot)
    if floor_mode:
        v = sg * (1.0 - t) * c
        # 입구 점(z ≈ 0) 바로 옆 판까지(R_w 안)는 입구 값을 줄여 이어 그림
        v = np.where(inb, v, 0.0)
        if R_w:
            ent_l = float(s[inb].min())
            ent_r = float(s[inb].max())
            for e, sgn in ((ent_l, -1.0), (ent_r, 1.0)):
                d = np.abs(s - e)
                band = (~inb) & (np.sign(s - e) == sgn) & (d < float(R_w))
                w = 1.0 - np.clip(d / float(R_w), 0.0, 1.0)
                v = np.where(band, sgn * c * (w * w * (3 - 2 * w)), v)
    else:
        v = np.where(inb, -sg * t * c, 0.0)
    if side in (1, -1, 1.0, -1.0):
        v = np.where(sg == float(side), v, 0.0)
    out = v
    return [round(float(x), 4) for x in out]


def fig_ds_dW1(s, z, D_nom, side) -> list[float]:
    """W1 단면 그림: 열린 쪽(s − s_c 부호 = side) 비드 구간 +1, 고정 쪽·판 0."""
    s = np.asarray(s, float)
    z = np.asarray(z, float)
    if s.size == 0 or not D_nom:
        return [0.0] * int(s.size)
    inb = z > 1e-9
    fl = z >= float(D_nom) - 1e-6
    sc = 0.5 * (float(s[fl].min()) + float(s[fl].max())) if fl.any() else (float(np.median(s[inb])) if inb.any() else 0.0)
    return [1.0 if (b and np.sign(x - sc) == float(side)) else 0.0 for x, b in zip(s, inb)]


# ---------------------------------------------------------------- W 사유(§4.1)
def w_reason(f: dict) -> str | None:
    """사실(dict) → 첫 일치 W 사용 불가 코드(없으면 None — W 행 있음). 키(없으면 거짓):
    user_off, network, area, merged, tie_mixed, floor_fixed, s2 (양쪽 W 구간 수), s1 (W1 후보 수), s1_edge (W1 후보가 모두
    판 외곽), entry_any (어느 쪽이든 입구 노드 ≥ n_min), w_partial, partial (S_2 또는 S_1 이 일부), open_boundary,
    width_undefined, paicad_none, src ('graph'|'elems'|'paicad')."""
    ff = bool(f.get("floor_fixed"))
    src = f.get("src", "graph")
    s2, s1 = int(f.get("s2") or 0), int(f.get("s1") or 0)
    if f.get("user_off"):
        return "W_USER_OFF"
    if src == "paicad":
        return "W_PAICAD_NONE" if f.get("paicad_none") else None
    if src == "elems":
        if f.get("open_boundary"):
            return "W_OPEN_BOUNDARY"
        if f.get("width_undefined"):
            return "W_WIDTH_UNDEFINED"
        return None
    if f.get("network"):
        return "W_NETWORK"
    if f.get("area"):
        return "W_AREA"
    if f.get("merged") and s2 == 0 and (s1 == 0 or not ff):
        return "W_EDIT_MERGED"
    if ff and f.get("tie_mixed"):
        return "W_TIE_MIXED"
    if s2 and (not f.get("partial") or f.get("w_partial")):
        return None
    if ff and s2 == 0:
        if s1 and f.get("partial") and not f.get("w_partial"):
            return "W_PARTIAL_OLD"
        if s1:
            return None
        if f.get("s1_edge"):
            return "W_ONE_SIDE_EDGE"
        return "W_ENTRY_NONE"
    if s2 and f.get("partial") and not f.get("w_partial"):
        return "W_PARTIAL_OLD"
    return "W_ENTRY_ONE_SIDE"


def w_reason_doc(code: str | None, messages: dict | None) -> dict | None:
    """코드 → {code, text}(문구 = resources/doe_messages.json — 호출 쪽이 읽어 넘김)."""
    if code is None:
        return None
    m = (messages or {}).get(code)
    return {"code": code, "text": m if isinstance(m, str) and m else code}


# ---------------------------------------------------------------- 복제(§6.1)
def clone_depth(orig: dict | None, req, *, rules_now: dict, w1_names=()) -> dict:
    """원 스냅샷 doe 블록(orig — depth_section·depth_section_rules·spec 키) + 요청 값 → 복제 결정(순수).
    -> {keys: {depth_section?, depth_section_rules?} | None(키 없음), from, to, changed, dropped [W1 변수 이름…]}.
    원 키 없음 + 요청 없음·entry_fixed = 키 없음, floor_fixed = 키 + rules(지금 설정), 원 floor + entry = 두 키 삭제,
    같은 값 = 원 블록 그대로. dropped = floor → entry 일 때 원 spec 변수 중 W1(w1_names)."""
    o = orig or {}
    ov = o.get("depth_section")
    frm = resolve(ov)
    if req is not None and req not in DEPTH_SECTIONS:
        raise EslError("INVALID_PARAMS", f"depth_section {req!r} 는 {list(DEPTH_SECTIONS)} 중 하나")
    to = frm if req is None else str(req)
    if to == frm:
        keys = ({"depth_section": ov, "depth_section_rules": o.get("depth_section_rules")}
                if ov is not None else None)
        if keys is not None and keys.get("depth_section_rules") is None:
            keys.pop("depth_section_rules")
    elif to == "floor_fixed":
        keys = {"depth_section": "floor_fixed", "depth_section_rules": dict(rules_now)}
    else:
        keys = None
    dropped = []
    if frm == "floor_fixed" and to == "entry_fixed":
        names = {p.get("name") for p in ((o.get("spec") or {}).get("params") or []) if isinstance(p, dict)}
        dropped = sorted(n for n in names if n in set(w1_names))
    return {"keys": keys, "from": frm, "to": to, "changed": frm != to, "dropped": dropped}


def spec_without(spec: dict | None, names) -> dict | None:
    """spec_prefill 에서 dropped 변수 제거(나머지 그대로)."""
    if not spec:
        return spec
    out = dict(spec)
    out["params"] = [p for p in (spec.get("params") or []) if p.get("name") not in set(names)]
    return out


# ---------------------------------------------------------------- 해시 보기(§5)
def hash_view(ds, rules: dict | None, has_elems: bool) -> dict | None:
    """선택 cfg 해시에 더할 값 — entry_fixed·키 없음 = None(해시 불변). floor_fixed = {ds, one_side_min_nodes}
    + elems 비드가 있을 때만 theta_min_deg·theta_spread_deg."""
    if not is_floor(ds):
        return None
    r = rules or {}
    out = {"ds": "floor_fixed", "one_side_min_nodes": int(r["one_side_min_nodes"])}
    if has_elems:
        out["theta_min_deg"] = float(r["theta_min_deg"])
        out["theta_spread_deg"] = float(r["theta_spread_deg"])
    return out
