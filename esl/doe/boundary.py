"""경계 매핑 경고 (계약 esl_bead_doe.md BD-D-14, §8.2, V-BD-10). 차단 없음 — 경고·정보와 평면도 자료만.

좌표: 점 p 의 A 정규화 (ξ, η) = ((a − a_min)/L_xi, (b − b_min)/L_eta)_A → B 평면 (a, b) = (a_min + ξ·L_xi,
b_min + η·L_eta)_B. 거리 = B 평면 (a, b) 유클리드 mm. (a, b) = ``keepout.project_ab``(frame 원점 기준).

- A 체결점 = A fixed-scan 클러스터 노드 평균(라벨 RBE2·RBE3·RBODY·INTER_TYPE2·BCS…) ∪ A ESL 3-2-1(라벨 S321).
  A fixed-scan 없음 → 3-2-1 만 + 정보 A_FASTENERS_UNKNOWN.
- B 체결 후보 = (②) B fixed-scan 클러스터 중심 ∪ B 구멍 중심(외곽 아닌 자유 모서리 루프, 둘레 ≥ hole_min_perimeter_mm)
  / (③) B 구멍 중심만.
- 규칙 (1) A 체결점마다 최근접 B 후보 d > fastener_warn_mm → BOUNDARY_FASTENER_FAR (후보 0 → 전부 경고)
  (2) 선택 ESL 마다 |F| 가중 군집(view3d.clusters, K = limits.cluster_k_max) 중 합력 비율(Σ|f| 비) ≥ load_share_min
      군집 중심 → B 로 옮겨 최근접 후보 d > load_warn_mm → BOUNDARY_LOAD_UNSUPPORTED
  (3) B 자동 3-2-1 과 옮긴 A 3-2-1 의 대응(같은 순서) 거리 > fastener_warn_mm → 정보 SUPPORT_SHIFT.
"""
from __future__ import annotations

import math

import numpy as np

from esl.opt.keepout import boundary_loops, project_ab


def to_unit(frame: dict, ab) -> np.ndarray:
    ab = np.asarray(ab, dtype=np.float64).reshape(-1, 2)
    a0, b0 = float(frame["a_range"][0]), float(frame["b_range"][0])
    return np.column_stack([(ab[:, 0] - a0) / float(frame["L_xi"]), (ab[:, 1] - b0) / float(frame["L_eta"])])


def from_unit(frame: dict, xe) -> np.ndarray:
    xe = np.asarray(xe, dtype=np.float64).reshape(-1, 2)
    a0, b0 = float(frame["a_range"][0]), float(frame["b_range"][0])
    return np.column_stack([a0 + xe[:, 0] * float(frame["L_xi"]), b0 + xe[:, 1] * float(frame["L_eta"])])


def transfer(frame_a: dict, frame_b: dict, ab_a) -> np.ndarray:
    """A 평면 (a, b) → B 평면 (a, b) (정규화 좌표 경유)."""
    return from_unit(frame_b, to_unit(frame_a, ab_a))


def a_fastener_points(frame_a: dict, a_fixed_points: list[dict] | None, a_supports_xyz: list[dict]) -> list[dict]:
    """[{label, kind, ab_a}] — a_fixed_points = paicad_io.fixed_points(read_fixed(A)) (None = 모름)."""
    out = []
    for p in a_fixed_points or []:
        out.append({"label": f"A {p['label']}", "kind": p["kind"], "ab_a": project_ab(frame_a, p["xyz"])[0].tolist()})
    for k, s in enumerate(a_supports_xyz):
        out.append({"label": f"A S321-{k + 1}({s.get('dof', '')})", "kind": "S321",
                    "ab_a": project_ab(frame_a, s["xyz"])[0].tolist()})
    return out


def hole_centers(mesh: dict, frame: dict, min_perimeter: float) -> list[dict]:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    lp = boundary_loops(mesh, min_perimeter)
    out = []
    for k, r in enumerate(lp["holes"]):
        c = X[np.asarray(r, dtype=np.int64)].mean(axis=0)
        ab = project_ab(frame, c)[0]
        per = float(lp["perimeters"]["holes"][k]) if lp.get("perimeters") else None
        out.append({"label": f"B 구멍 {k + 1}", "kind": "HOLE", "ab": ab.tolist(), "perimeter": per})
    return out


def b_candidates(frame_b: dict, b_mesh: dict, b_fixed_points: list[dict] | None, min_perimeter: float) -> list[dict]:
    out = [{"label": f"B {p['label']}", "kind": p["kind"], "ab": project_ab(frame_b, p["xyz"])[0].tolist()}
           for p in b_fixed_points or []]
    return out + hole_centers(b_mesh, frame_b, min_perimeter)


def load_points(entries_xf: list[tuple], frame_a: dict, share_min: float, k_max: int) -> list[dict]:
    """entries_xf = [(entry_id, node_id, x0, f)] (A 메시, 같은 frame_a) → [{entry_id, share, ab_a, frame}]
    (share = 군집 Σ|f| / 전체 Σ|f| ≥ share_min 인 군집 중심). ESL 마다 frame 이 다르면 ESL 별로 부른다."""
    from esl.view3d import clusters
    out = []
    for eid, nid, x0, f in entries_xf:
        f = np.asarray(f, dtype=np.float64)
        tot = float(np.linalg.norm(f, axis=1).sum())
        if tot <= 0:
            continue
        k = max(2, int(k_max))
        cl = clusters(np.asarray(nid, dtype=np.int64), np.asarray(x0, dtype=np.float64), f, np.zeros_like(f), k)
        rows = cl[str(k)]["rows"]
        for r in rows:
            share = float(r["sum_abs"]) / tot
            if share >= float(share_min):
                out.append({"entry_id": eid, "label": r["label"], "share": share,
                            "ab_a": project_ab(frame_a, r["center"])[0].tolist(), "frame": frame_a})
    return out


def _nearest(p, cands) -> tuple[int | None, float]:
    if not cands:
        return None, math.inf
    P = np.asarray([c["ab"] for c in cands], dtype=np.float64)
    d = np.linalg.norm(P - np.asarray(p, dtype=np.float64)[None, :], axis=1)
    i = int(np.argmin(d))
    return i, float(d[i])


def check(frame_a: dict, frame_b: dict, a_points: list[dict], loads: list[dict], b_cands: list[dict], cfg: dict, *,
          a_fastener_known: bool = True, a_supports_ab: list | None = None, b_supports_ab: list | None = None) -> dict:
    """규칙 (1)(2)(3) → {warnings[], info[], links[], a_points[{label, a, b}], load_points[{entry_id, share, a, b}],
    fixed[{label, kind, a, b}], n_warn, n_info}. a_points·loads 의 좌표는 B 평면으로 옮겨 기록."""
    bc = cfg["boundary"]
    fw, lw = float(bc["fastener_warn_mm"]), float(bc["load_warn_mm"])
    warns, info, links, ap, lp = [], [], [], [], []
    if not a_fastener_known:
        info.append({"code": "A_FASTENERS_UNKNOWN"})
    for p in a_points:
        ab = transfer(p.get("frame") or frame_a, frame_b, p["ab_a"])[0]
        ap.append({"label": p["label"], "kind": p.get("kind"), "a": float(ab[0]), "b": float(ab[1])})
        i, d = _nearest(ab, b_cands)
        far = d > fw
        if far:
            warns.append({"code": "BOUNDARY_FASTENER_FAR", "label": p["label"],
                          "d_mm": None if math.isinf(d) else d, "limit_mm": fw})
        if i is not None:
            links.append({"from": p["label"], "to": b_cands[i]["label"], "d_mm": d, "warn": far})
    for q in loads:
        ab = transfer(q.get("frame") or frame_a, frame_b, q["ab_a"])[0]
        lp.append({"entry_id": q["entry_id"], "label": q.get("label"), "share": q["share"], "a": float(ab[0]),
                   "b": float(ab[1])})
        i, d = _nearest(ab, b_cands)
        if d > lw:
            warns.append({"code": "BOUNDARY_LOAD_UNSUPPORTED", "entry_id": q["entry_id"], "share": q["share"],
                          "d_mm": None if math.isinf(d) else d, "limit_mm": lw})
            if i is not None:
                links.append({"from": f"하중 {q['entry_id']} {q.get('label') or ''}".strip(), "to": b_cands[i]["label"],
                              "d_mm": d, "warn": True})
    if a_supports_ab and b_supports_ab:
        for k, (sa, sb) in enumerate(zip(a_supports_ab, b_supports_ab)):
            ab = transfer(frame_a, frame_b, sa)[0]
            d = float(np.linalg.norm(ab - np.asarray(sb, dtype=np.float64)))
            if d > fw:
                info.append({"code": "SUPPORT_SHIFT", "index": k + 1, "d_mm": d, "limit_mm": fw})
    fixed = [{"label": c["label"], "kind": c["kind"], "a": float(c["ab"][0]), "b": float(c["ab"][1])} for c in b_cands]
    return {"warnings": warns, "info": info, "links": links, "a_points": ap, "load_points": lp, "fixed": fixed,
            "n_warn": len(warns), "n_info": len(info)}


def bead_rings(features_doc: dict, frame: dict, n_circle: int = 24) -> list[dict]:
    """평면도 비드 윤곽(근사): 선형 = core 첫·끝점 선분 ± 폭/2 사각형, 원형·점 = 지름 폭 원."""
    out = []
    for b in features_doc.get("beads") or []:
        w = float((b.get("nominal") or {}).get("width") or 0.0)
        core = [c for c in (b.get("core") or []) if c is not None]
        pts = project_ab(frame, core) if core else project_ab(frame, b.get("center") or [0, 0, 0])
        if len(pts) >= 2 and np.linalg.norm(pts[-1] - pts[0]) > 0:
            p0, p1 = pts[0], pts[-1]
            t = (p1 - p0) / np.linalg.norm(p1 - p0)
            nrm = np.array([-t[1], t[0]]) * 0.5 * w
            ring = [p0 + nrm, p1 + nrm, p1 - nrm, p0 - nrm]
        else:
            c = pts.mean(axis=0)
            r = 0.5 * w
            ring = [c + r * np.array([math.cos(2 * math.pi * i / n_circle), math.sin(2 * math.pi * i / n_circle)])
                    for i in range(n_circle)]
        out.append({"id": b["id"], "ring": [[float(x), float(y)] for x, y in ring]})
    return out


def plan(mesh: dict, frame: dict, kcfg: dict, max_points: int, *, features_doc: dict | None = None,
         result: dict | None = None) -> dict:
    """DoePlanOut = v0.7.0 PlanViewOut(frame·outline·holes·elems) + beads·fixed·a_points·load_points·links.
    워커 판정과 같은 ``check`` 결과(result)를 그대로 싣는다."""
    from esl.opt.keepout import plan_view
    pv = plan_view(mesh, frame, kcfg, max_points)
    r = result or {}
    pv.update(beads=bead_rings(features_doc, frame) if features_doc else [], fixed=r.get("fixed", []),
              a_points=r.get("a_points", []), load_points=r.get("load_points", []), links=r.get("links", []))
    return pv
