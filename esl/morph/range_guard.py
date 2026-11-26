"""Range guard — 품질 기반 변수 범위 제한의 모드 무관 계산(계약 esl_bead_shape_v021.md §2.3·§4, SH-10~18).

모드(①②③)·파일·설정을 모른다: 판정 함수(``ok_fn`` / ``ok_multi``)·기준(``crit``)·예산(``Budget``)을 인수로 받아
단일 변수 끝 점검·이분 축소(``single``), 상호작용 묶음(``interacting``), 꼭짓점(``corners``), 조합 공통 비율 이분(``combo``),
막힘 판정(``blocked``), 진단 문서(``doc`` — 스키마 ``esl/range_guard/1``)를 만든다. 호출 = ``esl.doe.bead_graph``
(``range_guard_table``·``guard_selection``). import 는 math·time·numpy 만(D-0.20.0-CODE, SH-3).

STABLE INTERFACE
  SCHEMA = "esl/range_guard/1";  CRITERIA = ("inverted", "jac", "tri_angle", "area_ratio", "new_fail")
  Budget(max_evals, timeout_s, clock=time.monotonic).take() -> bool · .stop(reason) · .stopped · .evals
  accept(probe, crit) -> (ok, reason | None, value | None)
  single(name, nominal, lo, hi, ok_fn, *, steps, budget, min_keep_frac=None) -> dict   (skipped → {"skipped": "budget"})
  interacting(supports) -> [[name…]…];  corners(n, *, full_max, samples) -> int8 (m, n)
  combo(group[(name, nominal, lo, hi)], ok_multi, *, full_max, samples, steps, budget, max_group=None) -> dict | None
  blocked(nominal, frm, usable, min_keep_frac) -> (lo_blocked, hi_blocked);  inward(v, nominal) -> float
  all_blocked(nominal, frm, usable, min_keep_frac) -> bool;  side_stuck(nominal, frm, usable, tol=1e-4) -> bool (v0.25.0)
  doc(scope, entries, combos, skipped, budget, crit, meta) -> dict
"""
from __future__ import annotations

import time

import numpy as np

SCHEMA = "esl/range_guard/1"
CRITERIA = ("inverted", "jac", "tri_angle", "area_ratio", "new_fail")      # accept 의 판정·보고 순서
CRIT_KEYS = ("flip_deg", "jac_min", "tria_angle_min_deg", "area_ratio_min", "max_new_fail_ratio")
_ROUND = 1e4                                                               # inward 반올림 격자(1e-4 mm)


class Budget:
    """시험 모핑 예산: 남았으면 ``take()`` 가 1 차감하고 True. 시계는 주입(기본 ``time.monotonic``).
    ``stopped`` = None | "evals" | "time" | "vars"(호출자가 ``stop("vars")``)."""

    def __init__(self, max_evals: int | None, timeout_s: float | None, clock=time.monotonic):
        self.max_evals = None if max_evals is None else int(max_evals)
        self.timeout_s = None if timeout_s is None else float(timeout_s)
        self.clock = clock
        self.t0 = clock()
        self.evals = 0
        self.stopped: str | None = None
        self.halted = False                    # evals·time 로 멈춤(이후 take 는 늘 False) — "vars" 는 기록만

    def take(self) -> bool:
        if self.halted:
            return False
        if self.max_evals is not None and self.evals >= self.max_evals:
            return self._halt("evals")
        if self.timeout_s is not None and self.clock() - self.t0 > self.timeout_s:
            return self._halt("time")
        self.evals += 1
        return True

    def _halt(self, reason: str) -> bool:
        self.halted = True
        self.stop(reason)
        return False

    def stop(self, reason: str) -> None:
        """멈춘 사유 기록(처음 것만). "vars"(후보 수 상한)는 시험 모핑을 막지 않는다."""
        if self.stopped is None:
            self.stopped = reason

    def seconds(self) -> float:
        return float(self.clock() - self.t0)


def _on(v) -> bool:
    return v is not None and not isinstance(v, bool)


def accept(probe: dict, crit: dict) -> tuple[bool, str | None, float | None]:
    """guard_probe 결과 → (통과, 첫 위반 기준, 그 값). 기준 값이 None 이면 그 기준은 끔(뒤집힘은 늘 봄)."""
    if int(probe.get("inverted") or 0) > 0:
        return False, "inverted", float(probe["inverted"])
    if _on(crit.get("jac_min")) and int(probe.get("jac_bad_new") or 0) > 0:
        return False, "jac", _f(probe.get("jac_min"))
    if _on(crit.get("tria_angle_min_deg")) and int(probe.get("tri_bad_new") or 0) > 0:
        return False, "tri_angle", _f(probe.get("tri_angle_min"))
    a = probe.get("area_ratio_min")
    if _on(crit.get("area_ratio_min")) and a is not None and float(a) < float(crit["area_ratio_min"]):
        return False, "area_ratio", float(a)
    nf = probe.get("new_fail_ratio")
    if _on(crit.get("max_new_fail_ratio")) and nf is not None and float(nf) > float(crit["max_new_fail_ratio"]):
        return False, "new_fail", float(nf)
    if _on(crit.get("warp_max_deg")) and int(probe.get("warp_bad_new") or 0) > 0:   # v0.25.0 VB: A 항목 crit 에만 키
        return False, "warp", _f(probe.get("warp_max"))
    return True, None, None


def _f(v):
    return None if v is None else float(v)


def inward(v, nominal) -> float:
    """1e-4 격자로 공칭 쪽 반올림(반올림된 끝이 위반 쪽에 떨어지지 않음 — ``bead_graph._inward`` 와 같은 식, 이곳이 원본)."""
    v = float(v)
    q = v * _ROUND
    return float((np.ceil(q - 1e-9) if v < float(nominal) else np.floor(q + 1e-9)) / _ROUND)


def _unpack(r):
    """ok_fn 반환 (ok, reason, value[, n]) → (ok, reason, value, n | None)."""
    ok, reason, value = bool(r[0]), r[1], r[2]
    n = r[3] if len(r) > 3 else None
    return ok, reason, value, n


def blocked(nominal, frm, usable, min_keep_frac) -> tuple[bool, bool]:
    """(lo 쪽 막힘, hi 쪽 막힘): keep = |usable − v₀| / |from − v₀| < min_keep_frac(원래 폭 0 이면 막힘 아님)."""
    v0 = float(nominal)
    out = []
    for f, u in zip(frm, usable):
        span = abs(float(f) - v0)
        keep = 1.0 if span <= 0.0 else abs(float(u) - v0) / span
        out.append(bool(keep < float(min_keep_frac)))
    return out[0], out[1]


def all_blocked(nominal, frm, usable, min_keep_frac) -> bool:
    """v0.25.0 VB §6.2(D-0.25.0-VB-16): "모든 쪽이 막힘" = 폭 > 0 인 쪽이 모두 막힘(폭 0 인 쪽 — 공칭 = 범위 끝 — 은 판정에서 뺌).
    양쪽 범위(공칭이 안쪽)는 ``blocked`` 두 값의 and 와 같음(바이트 불변). 폭 > 0 인 쪽이 없으면 False."""
    v0 = float(nominal)
    bl = blocked(v0, frm, usable, min_keep_frac)
    sides = [b for f, b in zip(frm, bl) if abs(float(f) - v0) > 0.0]
    return bool(sides) and all(sides)


def side_stuck(nominal, frm, usable, tol: float = 1e-4) -> bool:
    """v0.25.0 VB §6.2 SH-28 보정: 폭 > 0 인 쪽 중 usable 이 공칭에 붙은(또는 넘은) 쪽이 있음. 양쪽 범위 = 지금 식
    ¬(u_lo < v₀ < u_hi) 그대로(정확 비교 — 바이트 불변), 한쪽 범위(한쪽 폭 0) = 폭 > 0 인 쪽 |u − v₀| ≤ tol(계약 A: usable_hi ≤ 0 + 1e-4)."""
    v0 = float(nominal)
    u = [float(x) for x in usable]
    spans = [abs(float(f) - v0) > 0.0 for f in frm]
    if all(spans):
        return not (u[0] < v0 < u[1])
    if spans[0] and u[0] >= v0 - tol:
        return True
    if spans[1] and u[1] <= v0 + tol:
        return True
    return False


def single(name, nominal, lo, hi, ok_fn, *, steps, budget, min_keep_frac=None) -> dict:
    """§4.2 단일 변수: 끝마다 ok_fn(end) → 위반이면 [공칭, 끝] 을 steps 회 이분(매 회 budget.take) → usable = inward(통과 쪽).
    예산이 끝나면 이 변수 전체를 {"var", "skipped": "budget"} 로(반쯤 줄인 값은 쓰지 않음).
    반환 {var, nominal, from[lo, hi], usable[lo, hi], state ok|limited|blocked, ends[{side, end, ok, reason, value, n?, evals}]}."""
    v0 = float(nominal)
    frm = [float(lo), float(hi)]
    ends, usable = [], []
    for side, end in (("lo", frm[0]), ("hi", frm[1])):
        if not budget.take():
            return {"var": name, "skipped": "budget"}
        ok, reason, value, n = _unpack(ok_fn(end))
        e = {"side": side, "end": end, "ok": ok, "reason": reason, "value": value, "evals": 1}
        if n is not None:
            e["n"] = int(n)
        if ok:
            usable.append(end)
        else:
            a, b = v0, end
            for _ in range(int(steps)):
                if not budget.take():
                    return {"var": name, "skipped": "budget"}
                m = 0.5 * (a + b)
                e["evals"] += 1
                if _unpack(ok_fn(m))[0]:
                    a = m
                else:
                    b = m
            usable.append(inward(a, v0))
        ends.append(e)
    state = "ok" if all(e["ok"] for e in ends) else "limited"
    if state == "limited" and min_keep_frac is not None:
        if all_blocked(v0, frm, usable, min_keep_frac):     # v0.25.0 VB-16: 폭 > 0 인 쪽만(양쪽 범위 = 지금과 같음)
            state = "blocked"
    return {"var": name, "nominal": v0, "from": frm, "usable": usable, "state": state, "ends": ends}


def interacting(supports: dict) -> list[list[str]]:
    """변수 → 영향 요소 index. 요소를 공유하는 변수끼리 union-find → 크기 ≥ 2 묶음(이름 정렬, 묶음은 첫 이름 순)."""
    names = sorted(supports)
    par = {n: n for n in names}

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    owner: dict[int, str] = {}
    for n in names:
        for e in np.unique(np.asarray(supports[n], dtype=np.int64)).tolist():
            o = owner.get(e)
            if o is None:
                owner[e] = n
            else:
                ra, rb = find(o), find(n)
                if ra != rb:
                    if ra < rb:
                        par[rb] = ra
                    else:
                        par[ra] = rb
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    out = [sorted(g) for g in groups.values() if len(g) >= 2]
    out.sort(key=lambda g: g[0])
    return out


def corners(n: int, *, full_max: int, samples: int) -> np.ndarray:
    """int8 (m, n) 꼭짓점 비트(1 = hi): n ≤ full_max → 2^n 전부(i 의 j 번째 비트), 아니면 default_rng(0) 표본 samples 개."""
    n = int(n)
    if n <= int(full_max):
        return np.array([[(i >> j) & 1 for j in range(n)] for i in range(2 ** n)], np.int8).reshape(2 ** n, n)
    return np.random.default_rng(0).integers(0, 2, size=(int(samples), n), dtype=np.int8)


def combo(group, ok_multi, *, full_max, samples, steps, budget, max_group=None) -> dict | None:
    """§4.2 조합: group[(name, nominal, usable_lo, usable_hi)](이름 정렬 — 입력 순서 무관). s = 1 에서 모든 꼭짓점 통과 → None.
    아니면 s ∈ [0, 1] 을 steps 회 이분(첫 위반에서 조기 종료) → {vars, corners, bad_n, scale, reason, value, usable{name: [lo, hi]}}.
    묶음 > max_group → {vars, skipped "max_group", n}, 예산 끝 → {vars, skipped "budget"}."""
    g = sorted(((str(nm), float(v0), float(lo), float(hi)) for nm, v0, lo, hi in group), key=lambda t: t[0])
    names = [t[0] for t in g]
    if max_group is not None and len(g) > int(max_group):
        return {"vars": names, "skipped": "max_group", "n": len(g)}
    if len(g) < 2:
        return None
    bits = corners(len(g), full_max=full_max, samples=samples)

    def vals(row, s):
        return {nm: v0 + s * ((hi if bt else lo) - v0) for (nm, v0, lo, hi), bt in zip(g, row)}

    bad_n, first = 0, None
    for row in bits:
        if not budget.take():
            return {"vars": names, "skipped": "budget"}
        ok, reason, value, _n = _unpack(ok_multi(vals(row, 1.0)))
        if not ok:
            bad_n += 1
            if first is None:
                first = (reason, value)
    if not bad_n:
        return None
    a, b = 0.0, 1.0
    for _ in range(int(steps)):
        m = 0.5 * (a + b)
        bad = False
        for row in bits:
            if not budget.take():
                return {"vars": names, "skipped": "budget"}
            if not _unpack(ok_multi(vals(row, m)))[0]:
                bad = True
                break
        if bad:
            b = m
        else:
            a = m
    use = {nm: [inward(v0 + a * (lo - v0), v0), inward(v0 + a * (hi - v0), v0)] for nm, v0, lo, hi in g}
    return {"vars": names, "corners": int(bits.shape[0]), "bad_n": int(bad_n), "scale": float(a),
            "reason": first[0], "value": first[1], "usable": use}


def doc(scope, entries, combos, skipped, budget, crit, meta) -> dict:
    """§4.6 진단 문서(키 순서 결정적 — 파일은 정렬·compact·ASCII 로 직렬화). meta = {graph_sha256, cfg_sha256, fixed_sha256,
    exclude_sha256, selection_sha256, steps, min_keep_frac, max_vars}. 시간 값은 넣지 않는다(``budget.stopped`` 만)."""
    meta = meta or {}
    b = {"max_evals": getattr(budget, "max_evals", None), "timeout_s": getattr(budget, "timeout_s", None),
         "max_vars": meta.get("max_vars"), "evals": int(getattr(budget, "evals", 0)),
         "stopped": getattr(budget, "stopped", None)}
    if b["timeout_s"] is not None and float(b["timeout_s"]).is_integer():
        b["timeout_s"] = int(b["timeout_s"])
    return {"schema": SCHEMA, "scope": scope,
            "graph_sha256": meta.get("graph_sha256"), "cfg_sha256": meta.get("cfg_sha256"),
            "fixed_sha256": meta.get("fixed_sha256"), "exclude_sha256": meta.get("exclude_sha256"),
            "selection_sha256": meta.get("selection_sha256"),
            "crit": {k: (None if crit.get(k) is None else float(crit[k])) for k in CRIT_KEYS},
            "steps": int(meta.get("steps", 0)), "min_keep_frac": _f(meta.get("min_keep_frac")),
            "budget": b, "entries": list(entries), "combos": list(combos), "skipped": list(skipped)}
