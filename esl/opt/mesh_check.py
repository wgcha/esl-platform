"""메시 검사 — 템플릿(S2)·대상(S1) 공통 (계약 esl_opt_run.md §7.2 OR-8, §5.2 MeshCheckOut).

- ``load_mesh(path, part_title=None)``: ``.fem`` → ``femread.read_fem``, ``.rad``·``.inc`` → ``parse_rad``(대상 파트만).
  rad 파트가 여러 개이고 part_title 이 없으면 요소가 가장 많은 쉘 파트를 쓰고 경고.
- ``check(mesh, scenario, cfg, …)`` → {errors[], warnings[], metrics{}} (오류 = 실행 불가, 경고 = 정보).
- ``check_file(path, part_title, cfg, …)`` → MeshCheckOut dict. 업로드 폴더에는 쓰지 않는다(읽기만).
"""
from __future__ import annotations

import os

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from esl.errors import EslError
from esl.library import _util as U
from esl.library import normalize as nz
from esl.opt import femread

RAD_EXT = (".rad", ".inc")
FEM_EXT = (".fem",)


def _rad_mesh(rm) -> dict:
    ne = rm.elem_id.size
    return {"node_id": rm.node_id, "x0": rm.x0, "elem_id": rm.elem_id, "elem_type": rm.elem_type, "conn": rm.conn,
            "elem_pid": rm.elem_pid, "thickness": rm.thickness, "E": rm.E, "nu": rm.nu,
            "elem_mid": np.full(ne, int(rm.mats[0]["id"]) if rm.mats else 0, dtype=np.int64),
            "mats": rm.mats, "unsupported": {}, "warnings": list(rm.warnings), "part_title": rm.part_title,
            "part_id": rm.part_id, "max_ids": dict(rm.max_ids), "format": "rad",
            "pids": [{"pid": int(p), "title": "", "thickness": float(np.median(rm.thickness[rm.elem_pid == p])),
                      "E": float(rm.E[0]), "nu": float(rm.nu[0]), "n_elems": int(np.sum(rm.elem_pid == p))}
                     for p in np.unique(rm.elem_pid).tolist()]}


def load_mesh(path: str, part_title: str | None = None, *, max_include_depth: int = 8,
              include_path_map: dict | None = None) -> tuple[dict, dict]:
    """반환 (mesh, info{format, file_name, parts[], part_title, warnings[]})."""
    ext = os.path.splitext(path)[1].lower()
    info = {"format": None, "file_name": os.path.basename(path), "parts": [], "part_title": None, "warnings": []}
    if ext in FEM_EXT:
        m = femread.read_fem(path)
        info.update(format="fem")
        info["warnings"] += m["warnings"]
        return m, info
    if ext in RAD_EXT:
        from esl.rad.parser import list_parts, parse_rad
        try:
            parts = list_parts(path, max_include_depth, include_path_map)
        except EslError as exc:
            raise EslError("MESH_INVALID", f"rad 를 읽지 못함: {exc.message}") from None
        info.update(format="rad", parts=parts)
        title = part_title
        if title is None:
            cand = [p for p in parts if p["n_elems"] > 0]
            if not cand:
                raise EslError("MESH_INVALID", "요소가 있는 /PART 가 없음")
            best = sorted(cand, key=lambda p: (-p["n_elems"], p["id"]))[0]
            title = best["title"]
            if len(cand) > 1:
                info["warnings"].append(f"파트 {len(cand)}개 — 요소가 가장 많은 '{title}' 사용(part_title 로 지정 가능)")
        try:
            rm = parse_rad(path, title, max_include_depth=max_include_depth, include_path_map=include_path_map)
        except EslError as exc:
            if exc.code in ("PART_NOT_FOUND", "PART_AMBIGUOUS"):
                raise
            raise EslError("MESH_INVALID", f"rad 파트 '{title}' 를 읽지 못함: {exc.message}") from None
        info["part_title"] = rm.part_title
        m = _rad_mesh(rm)
        info["warnings"] += m["warnings"]
        return m, info
    raise EslError("MESH_FORMAT_UNSUPPORTED", f"지원하지 않는 형식 '{ext}' (.rad·.inc·.fem)")


# ---------------------------------------------------------------- 형상 지표
def _edge_lengths(X, conn, et):
    """(E,4) 모서리 길이(삼각형 4번째 = nan)."""
    q = et == 4
    d = lambda i, j: np.linalg.norm(X[conn[:, i]] - X[conn[:, j]], axis=1)   # noqa: E731
    L = np.full((et.size, 4), np.nan)
    L[:, 0], L[:, 1] = d(0, 1), d(1, 2)
    c = np.maximum(conn, 0)
    L[q, 2] = np.linalg.norm(X[c[q, 3]] - X[c[q, 2]], axis=1)
    L[q, 3] = np.linalg.norm(X[c[q, 0]] - X[c[q, 3]], axis=1)
    L[~q, 2] = np.linalg.norm(X[c[~q, 0]] - X[c[~q, 2]], axis=1)
    return L


def _warp_deg(X, conn, et):
    q = np.flatnonzero(et == 4)
    w = np.zeros(et.size)
    if q.size:
        c = conn[q]
        n1 = np.cross(X[c[:, 1]] - X[c[:, 0]], X[c[:, 2]] - X[c[:, 0]])
        n2 = np.cross(X[c[:, 2]] - X[c[:, 0]], X[c[:, 3]] - X[c[:, 0]])
        l1, l2 = np.linalg.norm(n1, axis=1), np.linalg.norm(n2, axis=1)
        ok = (l1 > 0) & (l2 > 0)
        cs = np.ones(q.size)
        cs[ok] = np.sum(n1[ok] * n2[ok], axis=1) / (l1[ok] * l2[ok])
        w[q] = np.degrees(np.arccos(np.clip(cs, -1, 1)))
    return w


def check(mesh: dict, scenario: str, cfg: dict, *, frame: dict | None = None, bead: dict | None = None,
          supports=None, normals_changed: int | None = None) -> dict:
    errors: list[dict] = []
    warns: list[dict] = []
    met: dict = {}

    def err(code, msg):
        errors.append({"code": code, "message": msg})

    def warn(code, msg):
        warns.append({"code": code, "message": msg})

    tc = cfg["template"]
    cc = cfg["check"]
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    ne = int(et.size)
    met.update(n_nodes=int(X.shape[0]), n_elems=ne, n_quad=int(np.sum(et == 4)), n_tria=int(np.sum(et == 3)))
    uns = {k: v for k, v in (mesh.get("unsupported") or {}).items() if k in femread.ELEMENT_CARDS}
    if uns:
        err("ELEMENT_UNSUPPORTED", f"QUAD4/TRIA3 외 요소: {uns}")
    other = {k: v for k, v in (mesh.get("unsupported") or {}).items() if k not in femread.ELEMENT_CARDS}
    if other:
        warn("CARDS_IGNORED", f"지원하지 않는 카드 무시: {sum(other.values())}개 {dict(list(other.items())[:8])}")
    if ne == 0:
        err("NO_ELEMENTS", "요소가 0")
        return {"errors": errors, "warnings": warns, "metrics": met}
    if scenario == "S2" and ne > int(tc["max_elems"]):
        err("TOO_MANY_ELEMS", f"요소 {ne} > 템플릿 상한 {tc['max_elems']}")
    tf = met["n_tria"] / ne
    met["tria_frac"] = tf
    if tf > float(tc["max_tria_frac"]):
        warn("TRIA_FRAC", f"TRIA3 비율 {tf * 100:.1f} % > {float(tc['max_tria_frac']) * 100:g} %")
    t = np.asarray(mesh["thickness"], dtype=np.float64)
    if np.any(~(t > 0)):
        err("THICKNESS", f"두께 ≤ 0 요소 {int(np.sum(~(t > 0)))}개")
    E = np.broadcast_to(np.asarray(mesh["E"], dtype=np.float64), (ne,))
    nu = np.broadcast_to(np.asarray(mesh["nu"], dtype=np.float64), (ne,))
    if np.any(~(E > 0)) or np.any(~((nu > -1) & (nu < 0.5))):
        err("MATERIAL", "E > 0, −1 < ν < 0.5 아닌 재료")
    # 연결 성분·일치 노드
    q = et == 4
    rows = [conn[:, 0], conn[:, 1], np.where(q, conn[:, 2], conn[:, 2])]
    cols = [conn[:, 1], conn[:, 2], np.where(q, conn[:, 3], conn[:, 0])]
    r, c = np.concatenate(rows), np.concatenate(cols)
    G = coo_matrix((np.ones(r.size), (r, c)), shape=(X.shape[0],) * 2)
    ncomp, _ = connected_components(G, directed=False)
    met["n_components"] = int(ncomp)
    if ncomp > 1:
        warn("COMPONENTS", f"연결 성분 {ncomp}개")
    diag = float(np.linalg.norm(X.max(axis=0) - X.min(axis=0))) or 1.0
    pairs = cKDTree(X).query_pairs(1e-6 * diag)
    met["n_coincident_pairs"] = len(pairs)
    if pairs:
        warn("COINCIDENT_NODES", f"일치 노드 쌍 {len(pairs)}개(연결 안 된 이음새?)")
    # 평탄도·frame
    try:
        fr = frame or nz.frame(X, None, conn, et)
    except EslError as exc:
        err("FRAME", exc.message)
        return {"errors": errors, "warnings": warns, "metrics": met}
    met["L_xi"], met["L_eta"] = fr["L_xi"], fr["L_eta"]
    zr = float(fr["z_range"][1] - fr["z_range"][0])
    met["flatness"] = zr / max(fr["L_xi"], fr["L_eta"])
    if scenario == "S2" and met["flatness"] > float(tc["flat_tol_rel"]):
        warn("NOT_FLAT", f"평탄도 z_range/L = {met['flatness']:.3f} > {tc['flat_tol_rel']}")
    # 법선
    from esl.opt.target import opposite_mask
    nopp = int(opposite_mask(mesh, fr["n"]).sum())
    met["normals_opposite"] = nopp
    if scenario == "S2":
        nf = nopp if normals_changed is None else int(normals_changed)
        if nf:
            warn("NORMALS_ALIGNED", f"법선을 n 쪽으로 정렬할 요소 {nf}개(연결 순서 뒤집음)")
    elif nopp:
        warn("NORMALS_OPPOSITE", f"법선이 n 과 반대인 요소 {nopp}개 — 원 연결 유지(비드 방향이 그 요소 법선 쪽)")
    # 요소 크기·비드 폭
    L = _edge_lengths(X, conn, et)
    h_med = float(np.nanmedian(L))
    met["elem_size_median"] = h_med
    if bead is not None and float(bead["min_width"]) < float(cc["bead_width_elem_factor"]) * h_med:
        warn("BEAD_WIDTH", f"비드 폭 {bead['min_width']} mm < {cc['bead_width_elem_factor']} × 요소 크기 중앙값 "
                           f"{h_med:.2f} mm")
    # 매핑 해상도(S2)
    if scenario == "S2":
        nx, ny = int(cfg["grid"]["nx"]), int(cfg["grid"]["ny"])
        i, j, _ = nz.cell_index(fr, X, nx, ny)
        cnt = np.bincount(i * ny + j, minlength=nx * ny)
        med = float(np.median(cnt[cnt > 0])) if np.any(cnt > 0) else 0.0
        met["nodes_per_cell_median"] = med
        if med < float(cc["min_nodes_per_cell"]):
            warn("MAPPING_RESOLUTION", f"셀당 노드 중앙값 {med:.0f} < {cc['min_nodes_per_cell']} ({nx}×{ny} 셀)")
    # 형상
    with np.errstate(invalid="ignore", divide="ignore"):
        ar = np.nanmax(L, axis=1) / np.nanmin(L, axis=1)
    n_ar = int(np.sum(ar > float(cc["max_aspect"])))
    wp = _warp_deg(X, conn, et)
    n_wp = int(np.sum(wp > float(cc["max_warp_deg"])))
    met.update(n_aspect_bad=n_ar, n_warp_bad=n_wp, aspect_max=float(np.nanmax(ar)), warp_max_deg=float(wp.max()))
    if n_ar:
        warn("ASPECT", f"종횡비 > {cc['max_aspect']} 요소 {n_ar}개(최대 {met['aspect_max']:.1f})")
    if n_wp:
        warn("WARP", f"뒤틀림 > {cc['max_warp_deg']}° 요소 {n_wp}개(최대 {met['warp_max_deg']:.1f}°)")
    # 3-2-1
    if supports is not None:
        from esl.opt.target import support_check
        try:
            sr = support_check(mesh, supports)
            met["support_rank"] = sr["rank"]
            if sr["rank"] < 6:
                err("SUPPORT_DEGENERATE", f"3-2-1 rank {sr['rank']} < 6")
        except EslError as exc:
            err(exc.code, exc.message)
    return {"errors": errors, "warnings": warns, "metrics": met}


def check_file(path: str, part_title: str | None, cfg: dict, *, bead: dict | None = None,
               max_include_depth: int = 8, include_path_map: dict | None = None) -> dict:
    """템플릿 검사(MeshCheckOut). 형식·파싱 실패는 MESH_INVALID/MESH_FORMAT_UNSUPPORTED/PART_* 예외."""
    from esl.opt.target import align_normals, auto_supports
    mesh, info = load_mesh(path, part_title, max_include_depth=max_include_depth, include_path_map=include_path_map)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"])
    et = np.asarray(mesh["elem_type"])
    fr = None
    sup = []
    n_flip = None
    try:
        fr = nz.frame(X, None, conn, et)
        _, flip = align_normals(mesh, fr["n"])
        n_flip = int(flip.sum())
        sup = auto_supports(mesh)
    except EslError as exc:
        info["warnings"].append(exc.message)
    q = check(mesh, "S2", cfg, frame=fr, bead=bead, supports=sup or None, normals_changed=n_flip)
    if not sup:
        q["errors"].append({"code": "SUPPORT_DEGENERATE", "message": "자동 3-2-1 을 정하지 못함"})
    q["warnings"] = [{"code": "INFO", "message": w} for w in info["warnings"]] + q["warnings"]
    return U.jsonable({
        "ok": not q["errors"], "sha256": U.sha256_file(path), "format": info["format"], "file_name": info["file_name"],
        "parts": info["parts"], "part_title": info["part_title"],
        "mesh": {"n_nodes": int(X.shape[0]), "n_elems": int(et.size), "n_quad": int(np.sum(et == 4)),
                 "n_tria": int(np.sum(et == 3)), "unsupported": mesh.get("unsupported") or {}},
        "pids": mesh.get("pids") or [],
        "frame": {"L_xi": fr["L_xi"] if fr else None, "L_eta": fr["L_eta"] if fr else None,
                  "z_range": fr["z_range"] if fr else None, "warnings": fr["warnings"] if fr else []},
        "quality": q, "supports_auto": [{"node_id": n, "dof": d} for n, d in sup]})
