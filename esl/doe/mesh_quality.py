"""④ 형상 메시 품질 판정 (이슈 #53 HyperMesh 2D criteria 표 근사 — docs/reference/radioss_chr_3mm_batchmesh.md, v0.14.0).

설정 ``bead_doe.compare.quality`` = 기준별 {warn, fail} + ``max_fail_ratio``(기본 0.01). 요소마다 아래 값을 계산해
fail 한계를 넘으면 Fail, warn 한계를 넘으면 Warn(Fail 아님). 메시 전체 tria 비율은 ``tria_pct``(%). 차단하지 않는다
(Fail 비율 > max_fail_ratio → 호출자가 경고 SHAPE_QUALITY_FAIL).

정의(HyperMesh 정의의 근사 — 같은 이름, 수치는 대체로 일치하나 완전히 같지 않음):
- min_length·max_length = 요소 모서리 최소·최대 길이(mm)
- aspect = 최대 모서리 / 최소 모서리
- warpage(quad) = 두 대각선으로 나눈 삼각형 쌍 법선 각의 큰 값(°), tria 0
- skew = quad: 90 − 마주 보는 변 중점 연결선 사이 예각(°) / tria: 꼭짓점별 (90 − 중선과 반대 변의 예각) 최대
- jacobian(quad) = 국부 평면 투영 쌍선형 사상의 2×2 가우스 점 야코비안 최소 / 최대(음수 = 뒤집힘), tria 1
- quad_min_angle·quad_max_angle, tria_min_angle·tria_max_angle = 내각(°)
"""
from __future__ import annotations

import numpy as np

# 기준 → (값 키, 나쁜 쪽: "lo" = 작을수록 나쁨, "hi" = 클수록 나쁨, 적용 요소: "all"|"quad"|"tria")
CRITERIA = {
    "min_length": ("min_length", "lo", "all"), "max_length": ("max_length", "hi", "all"),
    "aspect": ("aspect", "hi", "all"), "warpage": ("warpage", "hi", "quad"), "skew": ("skew", "hi", "all"),
    "jacobian": ("jacobian", "lo", "quad"), "quad_min_angle": ("min_angle", "lo", "quad"),
    "quad_max_angle": ("max_angle", "hi", "quad"), "tria_min_angle": ("min_angle", "lo", "tria"),
    "tria_max_angle": ("max_angle", "hi", "tria"),
}


def _ang(a, b) -> np.ndarray:
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    c = np.einsum("ij,ij->i", a, b) / np.maximum(na * nb, 1e-300)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def element_metrics(x0, conn, elem_type) -> dict:
    """요소별 지표 dict(값 배열, 길이 = 요소 수)."""
    X = np.asarray(x0, dtype=np.float64)
    C = np.asarray(conn, dtype=np.int64)
    et = np.asarray(elem_type).astype(int)
    ne = C.shape[0]
    q = et == 4
    out = {k: np.zeros(ne) for k in ("min_length", "max_length", "aspect", "warpage", "skew", "min_angle", "max_angle")}
    out["jacobian"] = np.ones(ne)
    for mask, k in ((q, 4), (~q, 3)):
        if not mask.any():
            continue
        P = X[C[mask, :k]]                                       # (m, k, 3)
        E = np.roll(P, -1, axis=1) - P
        L = np.linalg.norm(E, axis=2)
        out["min_length"][mask] = L.min(axis=1)
        out["max_length"][mask] = L.max(axis=1)
        out["aspect"][mask] = L.max(axis=1) / np.maximum(L.min(axis=1), 1e-300)
        A = np.stack([_ang(np.roll(P, 1, axis=1)[:, i] - P[:, i], np.roll(P, -1, axis=1)[:, i] - P[:, i])
                      for i in range(k)], axis=1)
        out["min_angle"][mask] = A.min(axis=1)
        out["max_angle"][mask] = A.max(axis=1)
        if k == 4:
            p0, p1, p2, p3 = (P[:, i] for i in range(4))
            w1 = _ang(np.cross(p1 - p0, p2 - p0), np.cross(p2 - p0, p3 - p0))
            w2 = _ang(np.cross(p2 - p1, p3 - p1), np.cross(p3 - p1, p0 - p1))
            out["warpage"][mask] = np.maximum(w1, w2)
            M = 0.5 * (P + np.roll(P, -1, axis=1))
            t = _ang(M[:, 2] - M[:, 0], M[:, 3] - M[:, 1])
            t = np.minimum(t, 180.0 - t)
            out["skew"][mask] = 90.0 - t
            n = np.cross(p2 - p0, p3 - p1)
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
            e1 = (p1 - p0) - np.einsum("ij,ij->i", p1 - p0, n)[:, None] * n
            e1 /= np.maximum(np.linalg.norm(e1, axis=1, keepdims=True), 1e-300)
            e2 = np.cross(n, e1)
            R = P - P.mean(axis=1, keepdims=True)
            xy = np.stack([np.einsum("mkj,mj->mk", R, e1), np.einsum("mkj,mj->mk", R, e2)], axis=2)    # (m, 4, 2)
            g = 1.0 / np.sqrt(3.0)
            dets = []
            for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):        # 2×2 가우스 점(쌍선형 사상)
                dxi = 0.25 * np.array([-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)])
                deta = 0.25 * np.array([-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)])
                a = np.einsum("k,mkj->mj", dxi, xy)
                b = np.einsum("k,mkj->mj", deta, xy)
                dets.append(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
            D = np.stack(dets, axis=1)
            out["jacobian"][mask] = D.min(axis=1) / np.maximum(np.abs(D).max(axis=1), 1e-300)
        else:
            sk = []
            for i in range(3):
                v = 0.5 * (P[:, (i + 1) % 3] + P[:, (i + 2) % 3]) - P[:, i]       # 중선
                w = P[:, (i + 2) % 3] - P[:, (i + 1) % 3]                        # 반대 변
                t = _ang(v, w)
                sk.append(90.0 - np.minimum(t, 180.0 - t))
            out["skew"][mask] = np.max(np.stack(sk, axis=1), axis=1)
    out["is_quad"] = q
    return out


def summarize(mesh: dict, qcfg: dict) -> dict:
    """메시 → {n_elems, fail_elems, fail_ratio, warn_elems, warn_ratio, tria_pct, tria_level(ok|warn|fail), fail_by{기준: 수},
    warn_by, worst{기준: 값}, over_limit(bool = fail_ratio > max_fail_ratio), max_fail_ratio}."""
    m = element_metrics(mesh["x0"], mesh["conn"], mesh["elem_type"])
    q = m["is_quad"]
    ne = int(q.size)
    fail = np.zeros(ne, bool)
    warn = np.zeros(ne, bool)
    fail_by, warn_by, worst = {}, {}, {}
    for name, (key, side, app) in CRITERIA.items():
        lim = qcfg.get(name)
        if not isinstance(lim, dict):
            continue
        use = q if app == "quad" else (~q if app == "tria" else np.ones(ne, bool))
        if not use.any():
            continue
        v = m[key]
        if side == "lo":
            f = use & (v < float(lim["fail"]))
            w = use & (v < float(lim["warn"])) & ~f
            worst[name] = float(v[use].min())
        else:
            f = use & (v > float(lim["fail"]))
            w = use & (v > float(lim["warn"])) & ~f
            worst[name] = float(v[use].max())
        fail_by[name] = int(f.sum())
        warn_by[name] = int(w.sum())
        fail |= f
        warn |= w
    warn &= ~fail
    tp = 100.0 * float(np.sum(~q)) / ne if ne else 0.0
    tl = qcfg.get("tria_pct") or {}
    level = "fail" if tl and tp > float(tl["fail"]) else ("warn" if tl and tp > float(tl["warn"]) else "ok")
    fr = float(fail.sum()) / ne if ne else 0.0
    mx = float(qcfg.get("max_fail_ratio", 0.01))
    return {"n_elems": ne, "fail_elems": int(fail.sum()), "fail_ratio": fr, "warn_elems": int(warn.sum()),
            "warn_ratio": float(warn.sum()) / ne if ne else 0.0, "tria_pct": tp, "tria_level": level,
            "fail_by": fail_by, "warn_by": warn_by, "worst": worst, "max_fail_ratio": mx, "over_limit": bool(fr > mx)}
