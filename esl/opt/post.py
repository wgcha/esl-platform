"""비드 후처리 산출물 (계약 esl_opt_run.md OR-D-20, §9).

입력: HyperView 배치 TCL(``resources/tcl/esl_bead_post.tcl``)이 ``<deck>_des.h3d`` Shape Change 에서 뽑은
``post/shape.csv``(node_id, dx, dy, dz). 노드 집합이 대상과 다르면 ``BEAD_POST_FAILED``.

- ``read_shape_csv(path, node_id)`` → shape (N,3) (대상 노드 순서)
- ``node_normals(mesh)`` → 면적 가중 노드 법선(덱과 같은 연결 순서 → +n 쪽이 비드 방향)
- ``write_outputs(post_dir, target, shape, …)`` → bead.npz, bead_nodes.csv, bead_map.png, bead_mesh.rad, bead_mesh.fem
  (+ history.csv 는 ``esl.opt.osout.history_csv``). 반환 요약 {height_max, area_frac, files, warnings}.
- ``assemble_result(…)`` → OptResult(§5.2) dict.
"""
from __future__ import annotations

import csv
import os

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.opt import femread, png
from esl.opt.target import elem_normals

SHAPE_COLS = ("node_id", "dx", "dy", "dz")


def read_shape_csv(path: str, node_id) -> np.ndarray:
    nid = np.asarray(node_id, dtype=np.int64)
    if not os.path.isfile(path):
        raise EslError("BEAD_POST_FAILED", f"Shape Change CSV 가 없음: {path}")
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh)
            head = [h.strip().lower() for h in next(rd)]
            idx = [head.index(c) for c in SHAPE_COLS]
            rows = [r for r in rd if r and any(x.strip() for x in r)]
        a = np.array([[float(r[i]) for i in idx] for r in rows], dtype=np.float64).reshape(-1, 4)
    except (StopIteration, ValueError, IndexError) as exc:
        raise EslError("BEAD_POST_FAILED", f"shape.csv 형식 오류({path}): {exc}") from None
    ids = a[:, 0].astype(np.int64)
    if ids.size != np.unique(ids).size:
        raise EslError("BEAD_POST_FAILED", "shape.csv 에 중복 node_id")
    o = np.argsort(ids)
    ids, vals = ids[o], a[o, 1:]
    if ids.size != nid.size or not np.array_equal(ids, np.sort(nid)):
        miss = np.setdiff1d(nid, ids)[:10].tolist()
        extra = np.setdiff1d(ids, nid)[:10].tolist()
        raise EslError("BEAD_POST_FAILED", f"shape.csv 노드가 대상과 다름(대상 {nid.size}, CSV {ids.size}, 없음 {miss}, "
                                           f"남음 {extra})")
    return vals[np.searchsorted(ids, nid)]


def node_normals(mesh: dict) -> np.ndarray:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    n = elem_normals(mesh)
    from esl.library.entry import _areas
    A = _areas(X, c, et)
    out = np.zeros_like(X)
    for k in range(4):
        ok = k < et
        np.add.at(out, c[ok, k], n[ok] * A[ok, None])
    ln = np.linalg.norm(out, axis=1)
    ln[ln == 0] = 1.0
    return out / ln[:, None]


def elem_mean(mesh: dict, v: np.ndarray) -> np.ndarray:
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    q = et == 4
    out = np.empty(c.shape[0])
    out[q] = v[c[q]].mean(axis=1)
    out[~q] = v[c[~q, :3]].mean(axis=1)
    return out


def _rad_write(path, mesh, x, source):
    from esl.rad.writer import write_rad
    warns = []
    pid = np.asarray(mesh["elem_pid"], dtype=np.int64)
    up = np.unique(pid)
    if up.size > 1:
        warns.append(f"bead_mesh.rad: PID {up.tolist()} 여러 개 — 첫 PID {int(up[0])} 하나로 씀(.fem 은 PID 유지)")
    E = np.unique(np.asarray(mesh["E"], dtype=np.float64))
    nu = np.unique(np.asarray(mesh["nu"], dtype=np.float64))
    if E.size > 1 or nu.size > 1:
        warns.append("bead_mesh.rad: 재료 여러 개 — 첫 재료로 씀(.fem 은 재료 유지)")
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    ids = np.where(c >= 0, nid[np.maximum(c, 0)], 0)
    em = mesh.get("elem_mid")
    mid = int(np.asarray(em).reshape(-1)[0]) if em is not None and np.size(em) else 1
    write_rad(path, nid, x, mesh["elem_id"], mesh["elem_type"], ids, int(source.get("part_id") or 1),
              str(source.get("part_title") or "esl_bead_mesh"), int(up[0]), np.asarray(mesh["thickness"]),
              max(mid, 1), float(E[0]), float(nu[0]), rho=float(source.get("rho") or 7.85e-9))
    return warns


def write_outputs(post_dir: str, target, shape: np.ndarray, *, design, keepout_reason, rects: list | None,
                  bead: dict, post_cfg: dict, writer: U.Writer | None = None) -> dict:
    g = writer.guard if writer is not None else (lambda p: p)
    os.makedirs(post_dir, exist_ok=True)
    m = target.mesh
    nid = np.asarray(m["node_id"], dtype=np.int64)
    X = np.asarray(m["x0"], dtype=np.float64)
    shape = np.asarray(shape, dtype=np.float64)
    nn = node_normals(m)
    h = np.sum(shape * nn, axis=1)
    des = np.asarray(design, dtype=bool)
    kr = np.asarray(keepout_reason, dtype=np.int8)
    np.savez_compressed(g(os.path.join(post_dir, "bead.npz")), node_id=nid, shape=shape, h=h, design=des,
                        keepout_reason=kr)
    with open(g(os.path.join(post_dir, "bead_nodes.csv")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("node_id,x0,y0,z0,h,dx,dy,dz\n")
        rows = np.column_stack([X, h, shape]).tolist()          # Python float → repr 왕복 정확
        for i in range(nid.size):
            fh.write(f"{int(nid[i])}," + ",".join(repr(v) for v in rows[i]) + "\n")
    he = elem_mean(m, h)
    height = float(bead["height"])
    from esl.library.entry import _areas
    A = _areas(X, np.asarray(m["conn"]), np.asarray(m["elem_type"]))
    thr = float(post_cfg["bead_area_thr_rel"]) * height
    ad = float(A[des].sum())
    area_frac = float(A[des & (np.abs(he) >= thr)].sum() / ad) if ad > 0 else 0.0
    hval = np.where(des, np.abs(he), np.nan)
    pngb = png.render_plan(m, target.frame, values=hval, vmax=height, hatch_mask=~des, rects=rects,
                           supports=target.supports, size=tuple(post_cfg["png_px"]))
    with open(g(os.path.join(post_dir, "bead_map.png")), "wb") as fh:
        fh.write(pngb)
    xn = X + shape
    warns = _rad_write(g(os.path.join(post_dir, "bead_mesh.rad")), m, xn, target.source)
    femread.write_fem(g(os.path.join(post_dir, "bead_mesh.fem")), {**m, "x0": xn},
                      header=[f"ESL bead mesh ({target.scenario}) = x0 + Shape Change, original IDs"])
    return {"height_max": float(np.max(np.abs(h))) if h.size else 0.0, "area_frac": area_frac,
            "elem_h": he, "files": ["bead.npz", "bead_nodes.csv", "bead_map.png", "bead_mesh.rad", "bead_mesh.fem"],
            "warnings": warns}


def write_keepout_png(path: str, target, keepout: dict, design, size, writer: U.Writer | None = None) -> str:
    """실행 전 금지 영역 평면도(같은 렌더러): 비설계·금지 영역 회색 빗금, 사각형 주황."""
    g = writer.guard if writer is not None else (lambda p: p)
    b = png.render_plan(target.mesh, target.frame, values=None, hatch_mask=~np.asarray(design, dtype=bool),
                        rects=keepout.get("rects"), supports=target.supports, size=tuple(size))
    with open(g(path), "wb") as fh:
        fh.write(b)
    return path


def assemble_result(*, selection: dict, parsed: dict, desmax: int, subcases: list, keepout_counts: dict,
                    n_design_elems: int, bead_summary: dict, normals: dict, solve_meta: dict,
                    warnings: list) -> dict:
    """OptResult (§5.2). objective 이력은 history 행의 objective."""
    from esl.opt import osout
    hist = osout.history(parsed, selection)
    objs = [r["objective"] for r in hist if r.get("objective") is not None]
    warns = list(warnings)
    if not parsed.get("converged"):
        warns.append(f"수렴 표식 없음(DESMAX {desmax} 도달 또는 중단) — 결과는 마지막 반복")
    nk = "normals_flipped" if normals.get("mode") == "aligned" else "normals_opposite"
    return U.jsonable({
        "load_selection": selection, "objective_norm": selection["objective_norm"], "C_ref": selection["C_ref"],
        "converged": bool(parsed.get("converged")), "iterations": parsed.get("last_iteration"), "desmax": int(desmax),
        "objective": {"initial": objs[0] if objs else None, "final": objs[-1] if objs else None, "history": objs},
        "subcases": subcases,
        "keepout": {"n_elems_auto_hole": keepout_counts.get("n_elems_auto_hole", 0),
                    "n_elems_auto_edge": keepout_counts.get("n_elems_auto_edge", 0),
                    "n_elems_rects": keepout_counts.get("n_elems_rects", 0), "n_design_elems": int(n_design_elems)},
        "bead": {"height_max": bead_summary.get("height_max"), "area_frac": bead_summary.get("area_frac")},
        nk: normals.get(nk, 0),
        "solve": {"seconds": solve_meta.get("seconds"), "license_waits": solve_meta.get("license_waits", 0),
                  "reused": bool(solve_meta.get("reused", False))},
        "warnings": warns})
