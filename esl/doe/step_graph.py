"""③ 다른 모델(STEP만)을 공통 비드 그래프 경로로 (계약 docs/contracts/esl_step_graph.md STEP_GRAPH v0.18.0).

새 ③ 스터디 = ``scenario "select"`` + ``inputs.select_base "step"`` (schema 2 고정): B STEP → ④ 메시 사다리(같은 설정) →
기준 메시 1개 → beadgraph 분류 → ①② 와 같은 select 흐름(기저 모핑, 하중·지지 1회). 기존 ``scenario "step"``(paicad) 은 이
모듈을 거치지 않는다(§5.3 — 바이트 불변).

STABLE INTERFACE (Backend / Frontend / worker — change only with the contract)
----------------------------------------------------------------------------------------------------------------------
Worker calls (unchanged entry point ``esl.doe.stages.run_stage(spec, echo)``; spec.doe.scenario "select",
spec.doe.select_base "step", spec.doe.select_schema 2):
  BD_INPUT  run_stage({"stage": "bd_input", …})  -> {files ["prep/input.json"], warnings, info, part_id None}
            spec.doe: step{path, file_name, sha256?} (required), props?{t, E, nu} (else A Case default ``props_default``),
            inch?, mesh_mode?, mesh_ladder?, bead_source auto|manual. input.json {select_base "step", select_schema 2,
            step{rel, sha256}, props, bead_source?}
  BD_MESH0  run_stage({"stage": "bd_mesh0", …})  -> ``mesh0(c, echo)`` (select_base step; ①② select still return
            {"skipped": True}). Returns {files, warnings[str], info[str], h, mesh{method, n_nodes, n_elems, tri_frac,
            stage_times}, region{mode, rule, n_in, n_out}}; failure = EslError MESH_FAILED (text = MESH_LADDER_FAILED) |
            MESH_TOO_LARGE | GMSH_UNAVAILABLE | SIZE_MISMATCH | SUPPORT_DEGENERATE | STEP_GRAPH_TRIA_BLOCKED.
  BD_GEOM   (worker, LOCAL) unchanged: optional A Case → prep/a_fixed/ (paicad fixed-scan), auto → extract0/extract hints.
            ``stages.select_prep_info(out)`` -> {select_base "step", bead_source, assem None, part_id None,
            part_title None, step_rel} — no B fixed-scan / grid / update for step.
  BD_LOADS  run_stage({"stage": "bd_loads", …})  -> same keys as ② select + "fixed"{source "a_transfer"|"none", n,
            xfer{method, matched, unmatched, frame_ok}} + "region"{…} + auto (manual too — seed file always written).
Files (all under the study folder, never SPDM / input folders):
  prep/mesh0/{mesh.npz, mesh.json, attempt_logs/, try_<n>/}   ④ ladder format (row id d000, C2-D-18..41)
  prep/base_mesh.npz  += "region" (bool per element; key absent when the region is the whole mesh)
  prep/base.json      scenario "select", extra {props, h, mesh_method, tri_frac, gmsh_version, region{…}}
  prep/input.json     += mesh{method, n_nodes, n_elems, tri_frac, stage_times}, region{mode, rule, n_in, n_out, out_bbox},
                         fixed{source, n, xfer{method, matched, unmatched, frame_ok}}, warnings[{code…}], info[{code…}]
  prep/select/fixed_transfer.json   schema "esl/doe_fixed_transfer/2" (§3.3 SG-D-15, deterministic bytes: sorted keys,
      floats rounded 1e-3): {schema, method "xyz_nearest"|"ab_hole_snap"|"none", mode, reason?, frame_check{d_origin_mm,
      angle_deg[3], ok, origin_tol_mm, axis_tol_deg}, tol_mm, snap_mm, frame_a_sha, frame_b_sha,
      matches[{a_label, kind, n_a, n_nodes, d_max_mm, hole, a_ab, b_ab, d_mm}], unmatched[{a_label, kind, d_mm}],
      node_id[], elems{q, t}}  — absent when fixed_transfer.enabled false (FIXED_XFER_NONE{DISABLED}).
  prep/select/graph_region.json     {schema "esl/doe_graph_region/1", segments[id], islands[id], n_in, n_out} — graph
      ids more than 50 % outside the region (out_of_region: not seeded, grey in the tree, painting allowed). Only when
      the region is not the whole mesh and the graph exists.
  prep/select/auto_selection.json   schema 2: auto = graph seed (region-filtered) + fixed_user (transfer), source "graph";
      manual (or auto with no seedable bead) = beads [] + fixed_user, source "fixed_transfer"; + "fixed"{source, method,
      n_nodes}.
Warning / info codes (resources/doe_messages.json): STEP_GRAPH_TRIA{mesh_method, tri_frac} (warning) ·
  STEP_GRAPH_TRIA_BLOCKED (BD_MESH0 failure, tria_policy block) · STEP_GRAPH_REGION{n_in, n_out, out_bbox, mode} (info) ·
  STEP_GRAPH_REGION_SMALL{frac, min_frac} (warning) · FIXED_XFER_NONE{reason A_CASE_MISSING|A_SCAN_FAILED|NO_MATCH|
  DISABLED} (info) · FIXED_XFER_UNMATCHED{label, d_mm} (info).
Functions (core-internal, stable names): mesh0(c, echo) · region_mask(mesh, a_xyz, cfg, h) · part_frame(x0, conn, et) ·
  frame_check(a_mesh, b_mesh, region, cfg) · fixed_transfer(a_fixed, frame_a, t_b, cfg, *, a_mesh, region, h,
  hole_min_perimeter, snap_default) · seed_fixed_user(mesh, groups) · tria_check(mesh, method, cfg) ·
  region_loads(t, ents, region, …) · load_region(prep_dir).
----------------------------------------------------------------------------------------------------------------------
"""
from __future__ import annotations

import copy
import hashlib
import json
import os

import numpy as np

from esl.errors import EslError
from esl.library import _util as U

XFER_JSON = "fixed_transfer.json"
XFER_SCHEMA = "esl/doe_fixed_transfer/2"
REGION_JSON = "graph_region.json"
REGION_SCHEMA = "esl/doe_graph_region/1"
REGION_KEY = "region"
ROW_ID = "d000"
METHODS_XFER = ("xyz_nearest", "ab_hole_snap", "none")
MODES_XFER = ("auto", "xyz", "hole")
REGION_MODES = ("auto", "a_bbox", "largest", "all")
TRIA_POLICIES = ("warn", "block")
TRIA_METHODS = ("tria",)


# ====================================================================== 설정
def cfg_of(cfg: dict | None) -> dict:
    """bead_doe 설정 → select.step_graph(기본값 위, §4.3 검사 — 위반 CONFIG_INVALID)."""
    from esl.doe import DEFAULTS, _deep_merge
    base = DEFAULTS["select"]["step_graph"]
    sel = (cfg or {}).get("select") if isinstance(cfg, dict) else None
    sg = _deep_merge(base, (sel or {}).get("step_graph") or {}) if isinstance(sel, dict) else copy.deepcopy(base)

    def bad(msg):
        raise EslError("CONFIG_INVALID", f"select.step_graph.{msg}")
    if not 1 <= int(sg["max_elems"]) <= 2_000_000:
        bad("max_elems 1..2e6")
    if not float(sg["timeout_s"]) > 0:
        bad("timeout_s > 0")
    if not 0 < float(sg["tria_warn_frac"]) <= 1:
        bad("tria_warn_frac (0, 1]")
    if sg["tria_policy"] not in TRIA_POLICIES:
        bad("tria_policy warn|block")
    ft, rg = sg["fixed_transfer"], sg["region"]
    if ft["mode"] not in MODES_XFER:
        bad("fixed_transfer.mode auto|xyz|hole")
    for k in ("origin_tol_mm", "axis_tol_deg"):
        if not float(ft[k]) > 0:
            bad(f"fixed_transfer.{k} > 0")
    for k, v in (("fixed_transfer.tol_mm", ft["tol_mm"]), ("fixed_transfer.snap_mm", ft["snap_mm"]),
                 ("region.pad_mm", rg["pad_mm"])):
        if v is not None and not float(v) > 0:
            bad(f"{k} null 또는 > 0")
    if rg["mode"] not in REGION_MODES:
        bad("region.mode auto|a_bbox|largest|all")
    if not 0 < float(rg["min_frac"]) <= 1:
        bad("region.min_frac (0, 1]")
    return sg


def _r3(v):
    return None if v is None else round(float(v), 3)


def _det(o):
    """결정적 JSON 값(실수 1e-3 반올림)."""
    if isinstance(o, dict):
        return {str(k): _det(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_det(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        v = round(float(o), 3)
        return 0.0 if v == 0 else v
    return o


def det_bytes(doc: dict) -> bytes:
    return json.dumps(_det(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def text(code: str, **kw) -> str:
    """'CODE: 문구'(doe_messages 틀 — 빠진 자리 표시자는 그대로)."""
    from esl.doe import load_messages
    try:
        tpl = str(load_messages()["messages"].get(code) or code)
    except Exception:                                       # noqa: BLE001 - 문구 누락으로 실패하지 않음
        tpl = code

    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return f"{code}: {tpl.format_map(_D(kw))}"


# ====================================================================== 메시 도우미
def _tris_area(mesh: dict) -> np.ndarray:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    a = 0.5 * np.linalg.norm(np.cross(X[C[:, 1]] - X[C[:, 0]], X[C[:, 2]] - X[C[:, 0]]), axis=1)
    q = et == 4
    if q.any():
        Cq = C[q]
        a[q] += 0.5 * np.linalg.norm(np.cross(X[Cq[:, 2]] - X[Cq[:, 0]], X[Cq[:, 3]] - X[Cq[:, 0]]), axis=1)
    return a


def centroids(mesh: dict) -> np.ndarray:
    X = np.asarray(mesh["x0"], dtype=np.float64)
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    k = np.where(et == 4, 4, 3)
    Cs = np.where(np.arange(4)[None, :] < k[:, None], C, C[:, :1])
    s = X[Cs].sum(axis=1) - np.where(k[:, None] == 3, X[C[:, 0]], 0.0)
    return s / k[:, None]


def _elem_nodes_csr(mesh: dict, emask: np.ndarray):
    """요소-노드 결합 행렬(선택 요소만)."""
    from scipy import sparse
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    n = np.asarray(mesh["x0"]).shape[0]
    idx = np.flatnonzero(emask)
    k = np.where(et[idx] == 4, 4, 3)
    Cm = C[idx]
    sel = np.arange(4)[None, :] < k[:, None]
    cols = Cm[sel]
    rows = np.broadcast_to(np.arange(idx.size)[:, None], Cm.shape)[sel]
    M = sparse.csr_matrix((np.ones(rows.size, np.int8), (rows, cols)), shape=(idx.size, n))
    return idx, M


def components(mesh: dict, emask: np.ndarray) -> np.ndarray:
    """선택 요소의 연결 성분 라벨(노드 공유) — 선택 밖 요소 = -1."""
    from scipy.sparse.csgraph import connected_components
    lab = np.full(np.asarray(mesh["elem_type"]).size, -1, np.int64)
    idx, M = _elem_nodes_csr(mesh, np.asarray(emask, bool))
    if idx.size == 0:
        return lab
    A = (M @ M.T).tocsr()
    _, cc = connected_components(A, directed=False)
    lab[idx] = cc
    return lab


def _largest(mesh: dict, emask: np.ndarray, area: np.ndarray) -> np.ndarray:
    lab = components(mesh, emask)
    ok = lab >= 0
    if not ok.any():
        return np.zeros(lab.size, bool)
    s = np.bincount(lab[ok], weights=area[ok])
    best = int(np.argmax(s))                                # 동률 = 작은 성분 번호(첫 요소 순서 — 결정적)
    return lab == best


def submesh(mesh: dict, emask: np.ndarray) -> dict:
    """선택 요소 + 쓰인 노드만(노드·요소 ID 유지, conn 은 새 노드 순서)."""
    em = np.asarray(emask, bool)
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    used = np.zeros(np.asarray(mesh["x0"]).shape[0], bool)
    Ce = C[em]
    k = np.where(et[em] == 4, 4, 3)
    used[Ce[np.arange(4)[None, :] < k[:, None]]] = True
    old = np.flatnonzero(used)
    new = np.full(used.size, -1, np.int64)
    new[old] = np.arange(old.size)
    Cn = np.where(Ce >= 0, new[np.maximum(Ce, 0)], -1)
    Cn[et[em] == 3, 3] = -1
    out = {}
    for k_, v in mesh.items():
        a = np.asarray(v)
        if k_ in ("node_id", "x0"):
            out[k_] = a[old]
        elif k_ == "conn":
            out[k_] = Cn.astype(a.dtype if a.dtype.kind == "i" else np.int64)
        elif a.ndim >= 1 and a.shape[0] == em.size and k_ not in ("node_id", "x0"):
            out[k_] = a[em]
    out["_node_index"] = old
    return out


# ====================================================================== 평가 영역 (SG-D-19·20)
def region_mask(mesh: dict, a_xyz, cfg: dict | None, h: float) -> tuple[np.ndarray, dict]:
    """B 기준 메시 요소 마스크(평가 영역 = 주 시트) + 정보 {mode, rule, n_in, n_out, out_bbox, frac, pad_mm}.

    auto = A part bbox(날 좌표, 각 변 pad_mm(null = 2h) 넓힘) 안에 중심이 있는 요소가 있으면 그 요소들의 연결 성분 중 최대
    성분(면적), A 정보가 없으면 메시 최대 연결 성분 | a_bbox(같음 — A 없음이면 largest) | largest | all."""
    rg = cfg_of(cfg)["region"]
    mode = str(rg["mode"])
    ne = int(np.asarray(mesh["elem_type"]).size)
    area = _tris_area(mesh)
    pad = float(rg["pad_mm"]) if rg["pad_mm"] is not None else 2.0 * float(h)
    rule = mode
    if mode == "all":
        m = np.ones(ne, bool)
    elif mode in ("auto", "a_bbox") and a_xyz is not None and np.asarray(a_xyz).size >= 9:
        A = np.asarray(a_xyz, dtype=np.float64).reshape(-1, 3)
        lo, hi = A.min(axis=0) - pad, A.max(axis=0) + pad
        c = centroids(mesh)
        inside = np.all((c >= lo) & (c <= hi), axis=1)
        if inside.any():
            m = _largest(mesh, inside, area)
            rule = "a_bbox"
        else:
            m = _largest(mesh, np.ones(ne, bool), area)
            rule = "largest"
    else:
        m = _largest(mesh, np.ones(ne, bool), area)
        rule = "largest" if mode != "all" else "all"
    n_in = int(m.sum())
    out_bbox = None
    if n_in < ne:
        c = centroids(mesh)[~m]
        out_bbox = [_r3(v) for v in np.concatenate([c.min(axis=0), c.max(axis=0)])]
    info = {"mode": mode, "rule": rule, "n_in": n_in, "n_out": ne - n_in, "out_bbox": out_bbox,
            "frac": _r3(n_in / max(ne, 1)), "pad_mm": _r3(pad)}
    return m, info


def region_messages(info: dict, cfg: dict | None) -> tuple[list[dict], list[dict]]:
    """(경고, 정보) 구조화 dict — STEP_GRAPH_REGION(영역 ≠ 전체), STEP_GRAPH_REGION_SMALL(< min_frac)."""
    rg = cfg_of(cfg)["region"]
    warns, infos = [], []
    if info["n_out"] > 0:
        infos.append({"code": "STEP_GRAPH_REGION", "n_in": info["n_in"], "n_out": info["n_out"],
                      "out_bbox": info["out_bbox"], "mode": info["mode"]})
    if float(info["n_in"]) < float(rg["min_frac"]) * float(info["n_in"] + info["n_out"]):
        warns.append({"code": "STEP_GRAPH_REGION_SMALL", "frac": info["frac"], "min_frac": float(rg["min_frac"])})
    return warns, infos


def load_region(prep_dir: str) -> np.ndarray | None:
    """prep/base_mesh.npz 의 region(요소 bool) — 없으면 None(영역 = 전체)."""
    from esl.doe import scenario as sc
    p = os.path.join(prep_dir, sc.BASE_NPZ)
    if not os.path.isfile(p):
        return None
    with np.load(p, allow_pickle=False) as z:
        return np.asarray(z[REGION_KEY], bool) if REGION_KEY in z.files else None


def region_nodes(mesh: dict, region) -> np.ndarray:
    """영역 요소가 쓰는 노드(bool, 노드별)."""
    n = np.asarray(mesh["x0"]).shape[0]
    if region is None:
        return np.ones(n, bool)
    C = np.asarray(mesh["conn"], dtype=np.int64)[np.asarray(region, bool)]
    out = np.zeros(n, bool)
    out[C[C >= 0]] = True
    return out


def region_loads(t, ents, region, mapping_opts, min_nodes_per_cell, grid) -> tuple[list, dict]:
    """SG-D-20b 하중 셀 매핑 대상 = 영역 노드(영역 밖 노드 하중 0). region None = ``sc.entry_loads`` 그대로."""
    from esl.doe import scenario as sc
    from esl.opt import target as tg
    if region is None:
        return sc.entry_loads(t, ents, mapping_opts, min_nodes_per_cell, grid)
    sub = submesh({k: t.mesh[k] for k in tg.MESH_KEYS}, region)
    idx = sub.pop("_node_index")
    st = tg.Target("S2", {k: sub[k] for k in tg.MESH_KEYS}, t.frame, [], {}, {}, [], None)
    loads, info = sc.entry_loads(st, ents, mapping_opts, min_nodes_per_cell, grid)
    n = np.asarray(t.mesh["x0"]).shape[0]
    out = []
    for eid, f in loads:
        F = np.zeros((n, 3))
        F[idx] = f
        out.append((eid, F))
    return out, info


# ====================================================================== frame 판정 (SG-D-13 (0))
def part_frame(x0, conn, elem_type) -> dict:
    """bbox 중심 + 면적 모멘트 주축(고윳값 내림차순 3개) — 날 좌표(변환 없음)."""
    from esl.library import normalize as nz
    X = np.asarray(x0, dtype=np.float64)
    _, _, C = nz.surface_moments(X, conn, elem_type)
    w, V = np.linalg.eigh(C)
    o = np.argsort(-w, kind="stable")
    return {"origin": ((X.min(axis=0) + X.max(axis=0)) / 2.0).tolist(), "axes": V[:, o].T.tolist(),
            "moments": w[o].tolist()}


def frame_sha(fr: dict) -> str:
    return hashlib.sha256(det_bytes(fr)).hexdigest()


def frame_check(a_mesh: dict, b_mesh: dict, region, cfg: dict | None) -> dict:
    """A part(첫 ESL A part 노드·요소) ↔ B 기준 메시 평가 영역의 frame 일치(원점 ≤ origin_tol_mm ∧ 세 축 ≤ axis_tol_deg,
    축 부호 무시) → {d_origin_mm, angle_deg[3], ok, origin_tol_mm, axis_tol_deg, frame_a, frame_b}."""
    ft = cfg_of(cfg)["fixed_transfer"]
    fa = part_frame(a_mesh["x0"], a_mesh["conn"], a_mesh["elem_type"])
    bm = b_mesh if region is None else submesh({k: b_mesh[k] for k in ("x0", "conn", "elem_type", "node_id")}, region)
    fb = part_frame(bm["x0"], bm["conn"], bm["elem_type"])
    d = float(np.linalg.norm(np.asarray(fa["origin"]) - np.asarray(fb["origin"])))
    ang = [float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(a, b)))))))
           for a, b in zip(np.asarray(fa["axes"]), np.asarray(fb["axes"]))]
    ok = d <= float(ft["origin_tol_mm"]) and all(x <= float(ft["axis_tol_deg"]) for x in ang)
    return {"d_origin_mm": d, "angle_deg": ang, "ok": bool(ok), "origin_tol_mm": float(ft["origin_tol_mm"]),
            "axis_tol_deg": float(ft["axis_tol_deg"]), "frame_a": fa, "frame_b": fb}


# ====================================================================== 고정점 이전 (SG-D-12~15)
def _clusters(a_fixed: dict) -> list[dict]:
    """A fixed-scan 노드 표 → 클러스터 [{label, kind, xyz (k,3), center}] (paicad_io.fixed_points 라벨 규칙)."""
    from esl.doe import paicad_io as pio
    pts = pio.fixed_points(a_fixed)
    cl = np.asarray(a_fixed["cluster"], dtype=np.int64)
    X = np.asarray(a_fixed["xyz"], dtype=np.float64).reshape(-1, 3)
    out = []
    for c, p in zip(sorted(set(cl.tolist())), pts):
        out.append({"label": p["label"], "kind": p["kind"], "xyz": X[cl == c], "center": np.asarray(p["xyz"])})
    return out


def _xyz_nearest(clusters: list[dict], b_mesh: dict, rnodes: np.ndarray, tol: float):
    from scipy.spatial import cKDTree
    X = np.asarray(b_mesh["x0"], dtype=np.float64)
    nid = np.asarray(b_mesh["node_id"], dtype=np.int64)
    cand = np.flatnonzero(rnodes)
    tree = cKDTree(X[cand])
    matches, unmatched, groups = [], [], []
    for cl in clusters:
        d, j = tree.query(cl["xyz"], k=1)
        d = np.atleast_1d(d)
        j = np.atleast_1d(j)
        ok = d <= tol
        if not ok.any():
            unmatched.append({"a_label": cl["label"], "kind": cl["kind"], "d_mm": float(d.min()) if d.size else None})
            continue
        bi = np.unique(cand[j[ok]])
        groups.append(bi)
        matches.append({"a_label": cl["label"], "kind": cl["kind"], "n_a": int(d.size), "n_nodes": int(bi.size),
                        "d_max_mm": float(d[ok].max()), "hole": None, "a_ab": None, "b_ab": None, "d_mm": None})
    return matches, unmatched, groups, nid


def _holes(b_mesh: dict, region, frame_b: dict, min_perimeter: float) -> list[dict]:
    """평가 영역 B 구멍(자유 모서리 고리, 둘레 ≥ min_perimeter) [{k(1부터), ab, nodes(B 노드 인덱스)}]."""
    from esl.opt.keepout import boundary_loops, project_ab
    keys = ("x0", "conn", "elem_type", "node_id")
    bm = {k: b_mesh[k] for k in keys}
    if region is not None:
        sm = submesh(bm, region)
        gidx = sm.pop("_node_index")
    else:
        sm, gidx = bm, np.arange(np.asarray(bm["x0"]).shape[0])
    X = np.asarray(sm["x0"], dtype=np.float64)
    lp = boundary_loops(sm, min_perimeter)
    out = []
    for k, r in enumerate(lp["holes"]):
        r = np.asarray(r, dtype=np.int64)
        out.append({"k": k + 1, "ab": project_ab(frame_b, X[r].mean(axis=0))[0], "nodes": gidx[r]})
    return out


def _hole_snap(clusters: list[dict], frame_a: dict, frame_b: dict, holes: list[dict], snap: float):
    from esl.doe import boundary as bnd
    from esl.opt.keepout import project_ab
    matches, unmatched, groups, used = [], [], [], {}
    hab = np.asarray([h["ab"] for h in holes]).reshape(-1, 2)
    for cl in clusters:
        a_ab = project_ab(frame_a, cl["center"])[0]
        b_ab = bnd.transfer(frame_a, frame_b, a_ab)[0]
        if not holes:
            unmatched.append({"a_label": cl["label"], "kind": cl["kind"], "d_mm": None})
            continue
        d = np.hypot(*(hab - b_ab).T)
        j = int(np.argmin(d))                               # 동률 = 작은 구멍 번호(argmin 첫 값)
        if d[j] > snap:
            unmatched.append({"a_label": cl["label"], "kind": cl["kind"], "d_mm": float(d[j])})
            continue
        h = holes[j]
        first = h["k"] not in used
        used.setdefault(h["k"], cl["label"])
        if first:
            groups.append(np.unique(h["nodes"]))
        matches.append({"a_label": cl["label"], "kind": cl["kind"], "n_a": int(np.asarray(cl["xyz"]).shape[0]),
                        "n_nodes": int(np.unique(h["nodes"]).size), "d_max_mm": None, "hole": int(h["k"]),
                        "a_ab": a_ab.tolist(), "b_ab": b_ab.tolist(), "d_mm": float(d[j])})
    return matches, unmatched, groups


def seed_fixed_user(mesh: dict, groups: list) -> dict:
    """SG-D-14b seed ``fixed_user`` ElemSet: 각 이전 노드 묶음(클러스터·구멍 고리)의 노드를 2개 이상 가진 요소, 묶음이 노드
    1개면 그 노드를 가진 요소. 2개 공유 요소가 하나도 없는 묶음(성긴 A 클러스터)은 그 노드를 가진 요소."""
    from esl.doe import bead_select as bs
    ix = bs.mesh_index(mesh)
    C = np.asarray(mesh["conn"], dtype=np.int64)
    em = np.zeros(C.shape[0], bool)
    n = np.asarray(mesh["x0"]).shape[0]
    for g in groups:
        g = np.unique(np.asarray(g, dtype=np.int64))
        if g.size == 0:
            continue
        on = np.zeros(n + 1, bool)
        on[g] = True
        cnt = on[np.where(C >= 0, C, n)].sum(axis=1)
        hit = cnt >= (1 if g.size == 1 else 2)
        if not hit.any():                                   # 묶음 노드가 서로 떨어져 2개 공유 요소가 없음(A 가 B 보다 성김)
            hit = cnt >= 1                                  # → 그 노드들을 가진 요소(구현 보강 — 고정이 빠지지 않게)
        em |= hit
    return bs.elemset_of(ix, em)


def fixed_transfer(a_fixed: dict | None, frame_a: dict, t_b, cfg: dict | None, *, a_mesh: dict | None, region,
                   h: float, hole_min_perimeter: float, snap_default: float, reason: str | None = None) -> dict:
    """SG-D-13 3단 이전 → fixed_transfer 문서(§3.3 SG-D-15) + 내부 키 ``_groups``(노드 인덱스 묶음, 파일에 안 씀).

    a_fixed = ``paicad_io.read_fixed(prep/a_fixed)`` (None = 없음, reason = A_CASE_MISSING | A_SCAN_FAILED);
    frame_a = 첫 ESL 의 정규화 frame(meta.frame), t_b = B 기준 Target(t.frame = B 정규화 frame); a_mesh = 첫 ESL A part
    {x0, conn, elem_type} (frame 일치 판정용)."""
    sg = cfg_of(cfg)
    ft = sg["fixed_transfer"]
    mode = str(ft["mode"])
    tol = float(ft["tol_mm"]) if ft["tol_mm"] is not None else float(h)
    snap = float(ft["snap_mm"]) if ft["snap_mm"] is not None else float(snap_default)
    mesh = t_b.mesh
    doc = {"schema": XFER_SCHEMA, "method": "none", "mode": mode, "frame_check": None, "tol_mm": tol, "snap_mm": snap,
           "frame_a_sha": None, "frame_b_sha": None, "matches": [], "unmatched": [], "node_id": [],
           "elems": {"q": [], "t": []}}
    fc = None
    if a_mesh is not None:
        fc = frame_check(a_mesh, mesh, region, cfg)
        doc["frame_check"] = {k: fc[k] for k in ("d_origin_mm", "angle_deg", "ok", "origin_tol_mm", "axis_tol_deg")}
        doc["frame_a_sha"], doc["frame_b_sha"] = frame_sha(fc["frame_a"]), frame_sha(fc["frame_b"])
    groups: list = []
    if a_fixed is None:
        doc["reason"] = reason or "A_CASE_MISSING"
        doc["_groups"] = groups
        return doc
    cls = _clusters(a_fixed)
    order = {"auto": (["xyz"] if fc is not None and fc["ok"] else []) + ["hole"], "xyz": ["xyz"],
             "hole": ["hole"]}[mode]
    for step in order:
        if step == "xyz":
            m, u, g, _ = _xyz_nearest(cls, mesh, region_nodes(mesh, region), tol)
            meth = "xyz_nearest"
        else:
            holes = _holes(mesh, region, t_b.frame, hole_min_perimeter)
            m, u, g = _hole_snap(cls, frame_a, t_b.frame, holes, snap)
            meth = "ab_hole_snap"
        if g:
            doc.update(method=meth, matches=m, unmatched=u)
            groups = g
            break
        doc["unmatched"] = u                               # 마지막 시도의 못 찾은 목록(NO_MATCH 근거)
    if not groups:
        doc["reason"] = "NO_MATCH"
    else:
        nid = np.asarray(mesh["node_id"], dtype=np.int64)
        allx = np.unique(np.concatenate(groups))
        doc["node_id"] = nid[allx].tolist()
        doc["elems"] = seed_fixed_user(mesh, groups)
    doc["_groups"] = groups
    return doc


def xfer_messages(doc: dict | None, disabled: bool = False) -> list[dict]:
    """정보 dict: FIXED_XFER_NONE{reason} | FIXED_XFER_UNMATCHED{label, d_mm}(각)."""
    if disabled:
        return [{"code": "FIXED_XFER_NONE", "reason": "DISABLED"}]
    out = []
    if doc["method"] == "none":
        out.append({"code": "FIXED_XFER_NONE", "reason": doc.get("reason") or "NO_MATCH"})
    if doc["method"] != "none" or doc.get("reason") == "NO_MATCH":
        for u in doc.get("unmatched") or []:
            out.append({"code": "FIXED_XFER_UNMATCHED", "label": u["a_label"], "d_mm": _r3(u.get("d_mm"))})
    return out


def write_transfer(path: str, doc: dict, guard=None) -> str:
    g = guard or (lambda p: p)
    blob = det_bytes({k: v for k, v in doc.items() if not k.startswith("_")})
    with open(g(path), "wb") as fh:
        fh.write(blob)
    return hashlib.sha256(blob).hexdigest()


def xfer_summary(doc: dict | None) -> dict:
    """prep/input.json fixed.xfer = {method, matched, unmatched, frame_ok}."""
    if doc is None:
        return {"method": "none", "matched": 0, "unmatched": 0, "frame_ok": None}
    return {"method": doc["method"], "matched": len(doc["matches"]), "unmatched": len(doc["unmatched"]),
            "frame_ok": None if doc.get("frame_check") is None else bool(doc["frame_check"]["ok"])}


# ====================================================================== 삼각형 메시 (SG-D-6)
def tria_check(mesh: dict, method: str | None, cfg: dict | None) -> dict | None:
    """사다리 끝 = tria(또는 삼각형 비율 > tria_warn_frac) → STEP_GRAPH_TRIA 경고 dict, tria_policy block 이면
    EslError STEP_GRAPH_TRIA_BLOCKED. 아니면 None."""
    sg = cfg_of(cfg)
    et = np.asarray(mesh["elem_type"]).astype(int)
    tf = float((et == 3).sum()) / max(et.size, 1)
    if str(method) not in TRIA_METHODS and tf <= float(sg["tria_warn_frac"]):
        return None
    if sg["tria_policy"] == "block":
        raise EslError("STEP_GRAPH_TRIA_BLOCKED", text("STEP_GRAPH_TRIA_BLOCKED", mesh_method=method).split(": ", 1)[1])
    return {"code": "STEP_GRAPH_TRIA", "mesh_method": method, "tri_frac": _r3(tf)}


def tri_frac(mesh: dict) -> float:
    et = np.asarray(mesh["elem_type"]).astype(int)
    return float((et == 3).sum()) / max(et.size, 1)


# ====================================================================== BD_MESH0 (SG-D-4·5·7·19)
def mesh_mode(c) -> tuple[str, list[str]]:
    """④ 규칙(스냅샷 mesh_mode·mesh_ladder) → 없으면 설정 compare.mesh.mode(④ 기존 스터디의 cad 기본과 다름 — SG-D-4)."""
    from esl.doe import mesh_refine as mr
    from esl.doe import stages as stg
    if c.D.get("mesh_mode"):
        return stg._cmp_mode(c)
    return str(((c.cfg.get("compare") or {}).get("mesh") or {}).get("mode") or "auto"), mr.ladder(c.cfg, None)


def method_of(r: dict) -> str:
    """사다리 결과 행 → 메시 방식 칩(cad | cad_relaxed | refine | defeature | freeform | tria | remesh)."""
    if r.get("cad_relaxed"):
        return "cad_relaxed"
    return str(r.get("fallback_stage") or r.get("mesh_method") or "cad")


def mesh0(c, echo) -> dict:
    """BD_MESH0 select_base step: ④ 사다리(``_cmp_mesh_shape``, mesh_dir = prep/mesh0) → 평가 영역 → template_base(영역)
    → save_base(scenario select) — 반환은 워커 작업 결과(STABLE INTERFACE 위)."""
    from esl.doe import mesh_gmsh as mg
    from esl.doe import scenario as sc
    from esl.doe import stages as stg
    c.progress(0)
    ok, ver = mg.available()
    if not ok:
        raise EslError("GMSH_UNAVAILABLE", "gmsh 가 없어 ③ 기준 메시를 만들 수 없음")
    inp = U.read_json(c.p("prep", "input.json"))
    props = inp.get("props") or {}
    props = {"t": float(props["t"]), "E": float(props["E"]), "nu": float(props["nu"])}
    prof = sc.compare_profile(c.cfg)
    ccfg = sc.compare_cfg(c.cfg)
    h = mg.check_h(float(prof["size_mm"]), prof)
    mode, lad = mesh_mode(c)
    remesh_ok = bool({"remesh", "freeform"} & set(lad)) and stg._remesh_ready(c)
    avail = None
    if mode == "auto" and any(s.startswith("refine_") for s in lad):
        from esl.mech.shell import available_memory_bytes
        avail = available_memory_bytes()
    d = c.fresh(os.path.join("prep", "mesh0"))
    stem = os.path.splitext(os.path.basename(inp["step"]["rel"]))[0]
    row = {"id": ROW_ID, "name": stem, "rel": inp["step"]["rel"], "source": "step", "reference": True}
    echo(f"[bd_mesh0] ③ STEP → ④ 사다리 gmsh {ver} h {h:g} mm · 메시 방식 {mode}"
         + (f" · 사다리 {' → '.join(lad)}" if mode == "auto" else ""))
    c._cmp_echo = echo
    r = stg._cmp_mesh_shape(c, row, h, ccfg, props, mode, lad, remesh_ok, avail, mesh_dir=d)
    if r.get("status") != "READY":
        code = "MESH_TOO_LARGE" if r.get("code") == "MESH_TOO_LARGE" else "MESH_FAILED"
        raise EslError(code, f"③ STEP 기준 메시 실패: {stg._ladder_fail_text(r)}")
    c.progress(60)
    mesh = mg.load_mesh(d)
    meth = method_of(r)
    warns_s: list[str] = list(r.get("warnings") or [])
    warns_s += [f"{w['code']}: {w.get('message') or ''}".rstrip() for w in r.get("warn_codes") or []]
    infos_s: list[str] = [str(x) for x in r.get("info") or []]
    warns_d: list[dict] = []
    infos_d: list[dict] = []
    tw = tria_check(mesh, meth, c.cfg)
    if tw:
        warns_d.append(tw)
    ents = c.entries(raw=True)
    a_xyz = ents[0].raw.get("x0") if ents and getattr(ents[0], "raw", None) is not None else None
    rmask, rinfo = region_mask(mesh, a_xyz, c.cfg, h)
    rw, ri = region_messages(rinfo, c.cfg)
    warns_d += rw
    infos_d += ri
    region = None if rinfo["n_out"] == 0 else rmask
    t, size_info = sc.template_base(mesh, ents, c.ocfg["size"], inch=c.D.get("inch"), region=region,
                                    source={"file_name": os.path.basename(inp["step"]["rel"]), "mesh_method": meth})
    if region is not None:
        t.mesh[REGION_KEY] = np.asarray(region, bool)
    tf = tri_frac(mesh)
    st = r.get("stage_times")
    mrec = {"method": meth, "n_nodes": int(np.asarray(mesh["node_id"]).size),
            "n_elems": int(np.asarray(mesh["elem_type"]).size), "tri_frac": _r3(tf), "stage_times": st}
    rrec = {k: rinfo[k] for k in ("mode", "rule", "n_in", "n_out", "out_bbox")}
    bm = sc.save_base(t, c.p("prep"), "select", c.writer,
                      extra={"props": props, "h": h, "mesh_method": meth, "tri_frac": _r3(tf), "gmsh_version": ver,
                             "region": rrec, "profile_sha256": _profile_sha(prof)})
    warns_s += list(size_info.get("warnings") or [])
    for w in warns_d:
        warns_s.append(text(w["code"], **{k: v for k, v in w.items() if k != "code"}))
    for x in infos_d:
        infos_s.append(text(x["code"], **{k: v for k, v in x.items() if k != "code"}))
    inp.update(size=size_info, props=props, mesh_size_mm=h, gmsh_version=ver, mesh=mrec, region=rrec)
    inp["warnings"] = list(inp.get("warnings") or []) + warns_d
    inp["info"] = list(inp.get("info") or []) + infos_d
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_mesh0] {meth} {mrec['n_elems']} 요소 · 삼각 {tf * 100:.1f} % → 기준 노드 {bm['n_nodes']} · 요소 "
         f"{bm['n_elems']}" + (f" · 평가 영역 {rinfo['n_in']}/{rinfo['n_in'] + rinfo['n_out']} 요소({rinfo['rule']})"
                              if region is not None else ""))
    c.progress(100)
    return {"files": ["prep/mesh0/mesh.npz", "prep/mesh0/mesh.json", "prep/base_mesh.npz", "prep/base.json",
                      "prep/input.json"], "warnings": warns_s, "info": infos_s, "h": h, "mesh": mrec, "region": rrec}


def _profile_sha(prof: dict) -> str:
    keep = {k: prof.get(k) for k in ("size_mm", "curvature_n", "min_size_factor", "extend_from_boundary",
                                     "occ_fix_small", "feature_angle", "algorithm", "occ_sew_faces")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()


__all__ = ["cfg_of", "mesh0", "region_mask", "region_messages", "load_region", "region_nodes", "region_loads",
           "part_frame", "frame_check", "fixed_transfer", "seed_fixed_user", "xfer_messages", "write_transfer",
           "xfer_summary", "tria_check", "tri_frac", "submesh", "components", "centroids", "XFER_JSON", "REGION_JSON",
           "REGION_KEY", "XFER_SCHEMA", "REGION_SCHEMA"]
