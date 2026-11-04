"""④ 메시 입력(계약 esl_compare_mesh_options.md C2-D-2~8): 형상마다 STEP 대신 사용자가 만든 Radioss 메시(.rad/.inc)를 그대로 쓴다.

``read_shape_mesh(dir, main_rel, part_id, props, cfg) → (mesh, meta)``: 복사본 폴더(``input/shapes/<did>/`` — BD_INPUT 이
``scenario.copy_mesh_upload`` 로 만든 것) 안 주 파일 + include 를 ``esl.rad.parser.parse_rad_part`` 로 읽어 gmsh 출력과 같은
mesh dict(``mesh_gmsh.build_mesh`` — 번호 1..N·법선 정렬·props 물성)로 만든다. 원 ID ↔ 새 번호는 meta["id_map"]
(``write_id_map`` 이 id_map.npz 로). gmsh 를 부르지 않음(in-process, 파싱만). 구멍 메움·폴백 없음.

검사: 형식(mesh_input.formats) → MESH_FORMAT_UNSUPPORTED, 주·include 가 폴더 밖·링크 → PATH_OUTSIDE_ROOT, include 못 찾음 →
MESH_INPUT_INVALID, 합계 > max_mb → MESH_INPUT_TOO_LARGE, /BEGIN 길이 단위 mm 아님 → MESH_INPUT_UNIT(없으면 mm 로 보고 info),
요소 수 > mesh.max_elems → MESH_TOO_LARGE. 경고: MESH_INPUT_SIZE_DIFF(모서리 중앙값 e50 이 [h/r, h·r] 밖 또는 기준 d000 대비
비 > r), MESH_INPUT_DISCONNECTED(연결 성분 ≥ 2). 원본·입력 폴더에는 쓰지 않는다(읽기만).
"""
from __future__ import annotations

import os

import numpy as np

from esl.errors import EslError

ID_MAP_NPZ = "id_map.npz"
LENGTH_MM = ("mm", "millimeter", "millimetre")
_MM_IN_M = 1e-3


def _mcfg(cfg: dict) -> dict:
    from esl.doe import DEFAULTS, _deep_merge
    over = ((cfg.get("compare") or {}).get("mesh_input")) if isinstance(cfg, dict) else None
    return _deep_merge(DEFAULTS["compare"]["mesh_input"], over if isinstance(over, dict) else {})


def _real(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def _within(p: str, root: str) -> bool:
    rp, rr = _real(p), _real(root)
    try:
        return os.path.commonpath([rp, rr]) == rr
    except ValueError:
        return False


def input_files(root: str, main_rel: str, cfg: dict) -> list[dict]:
    """주 파일 + include(폴더 안만, 깊이 = max_include_depth, include false 면 주 파일만) → [{rel, path, size}].
    규칙 위반은 EslError(MESH_FORMAT_UNSUPPORTED·PATH_OUTSIDE_ROOT·MESH_INPUT_INVALID·MESH_INPUT_TOO_LARGE)."""
    from esl.rad.parser import scan_include_refs
    mi = _mcfg(cfg)
    fmts = [str(x).lower() for x in mi["formats"]]
    main = os.path.join(root, str(main_rel))
    if os.path.splitext(main)[1].lower() not in fmts:
        raise EslError("MESH_FORMAT_UNSUPPORTED", f"메시 형식 {os.path.splitext(main)[1]!r} 은 지원하지 않음({', '.join(fmts)})")
    if os.path.islink(main) or not _within(main, root):
        raise EslError("PATH_OUTSIDE_ROOT", f"메시 주 파일이 입력 폴더 밖이거나 링크임: {main_rel}")
    if not os.path.isfile(main):
        raise EslError("MESH_INPUT_INVALID", f"메시 주 파일이 없음: {main_rel}")
    files = [main]
    if mi.get("include", True):
        refs = scan_include_refs(main, None, int(mi["max_include_depth"]), follow=lambda p: _within(p, root))
        for r in refs:
            if not r["found"]:
                raise EslError("MESH_INPUT_INVALID", f"메시 include 를 찾지 못함: {r['spec']}")
            if os.path.islink(r["path"]) or not _within(r["path"], root):
                raise EslError("PATH_OUTSIDE_ROOT", f"메시 include 가 입력 폴더 밖이거나 링크임: {r['spec']}")
            if all(_real(r["path"]) != _real(f) for f in files):
                files.append(r["path"])
    out = [{"rel": os.path.relpath(f, root).replace(os.sep, "/"), "path": f, "size": os.path.getsize(f)} for f in files]
    tot = sum(x["size"] for x in out)
    if tot > float(mi["max_mb"]) * 1024 * 1024:
        raise EslError("MESH_INPUT_TOO_LARGE", f"메시 파일 합계 {tot / 2 ** 20:.1f} MB > 상한 {mi['max_mb']} MB")
    return out


def length_unit(begin: list | None) -> dict:
    """/BEGIN 행 → {unit(원문|None), ok(mm 인가|None = /BEGIN 없음)}. 길이 단위 = 입력 단위 행(3번째)의 두 번째 20자 칸.
    문자열이면 mm 계열, 숫자면 m 기준 배율 1e-3 이어야 mm."""
    from esl.rad.state import begin_values
    if not begin:
        return {"unit": None, "ok": None}
    b = begin_values(list(begin))
    u = b.get("units_in")
    if not u or len(u) < 2 or u[1] in (None, ""):
        return {"unit": None, "ok": None}
    v = u[1]
    if not isinstance(v, (int, float)):
        from esl.rad.state import parse_real
        try:
            v = float(parse_real(str(v)))
        except ValueError:
            pass
    if isinstance(v, (int, float)):
        return {"unit": v, "ok": abs(float(v) - _MM_IN_M) <= 1e-9}
    return {"unit": str(v), "ok": str(v).strip().lower() in LENGTH_MM}


def edge_median(mesh: dict) -> float:
    from esl.opt.mesh_check import _edge_lengths
    L = _edge_lengths(np.asarray(mesh["x0"]), np.asarray(mesh["conn"]), np.asarray(mesh["elem_type"]).astype(int))
    return float(np.nanmedian(L)) if L.size else 0.0


def n_components(mesh: dict) -> int:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    c = np.asarray(mesh["conn"], dtype=np.int64)
    n = int(np.asarray(mesh["x0"]).shape[0])
    if not n:
        return 0
    rows, cols = [], []
    for a in range(4):
        b = (a + 1) % 4
        ok = (c[:, a] >= 0) & (c[:, b] >= 0)
        rows.append(c[ok, a])
        cols.append(c[ok, b])
    r, k = np.concatenate(rows), np.concatenate(cols)
    g = coo_matrix((np.ones(r.size), (r, k)), shape=(n, n))
    return int(connected_components(g, directed=False)[0])


def read_shape_mesh(dir: str, main_rel: str, part_id: int | None, props: dict, cfg: dict, *,  # noqa: A002 - 계약 서명
                    opt_cfg: dict | None = None, normal_ref=None, ref_e50: float | None = None,
                    out_dir: str | None = None) -> tuple[dict, dict]:
    """메시 입력 형상 1개 → (mesh dict, meta). cfg = ④ cfg(``scenario.compare_cfg`` — compare.mesh_input·compare.mesh.size_mm·
    mesh.max_elems). ref_e50 = 기준 d000 모서리 중앙값(있으면 비 검사). out_dir 이 있으면 mesh.npz·mesh.json·id_map.npz."""
    from esl.doe import mesh_gmsh as mg
    from esl.doe import opt_settings
    from esl.rad.parser import parse_rad_part
    mi = _mcfg(cfg)
    files = input_files(dir, main_rel, cfg)
    try:
        rm = parse_rad_part(files[0]["path"], part_id, need_props=False,
                            max_include_depth=int(mi["max_include_depth"]) if mi.get("include", True) else 0)
    except EslError as exc:
        if exc.code.startswith("MESH_INPUT_") or exc.code == "MESH_TOO_LARGE":
            raise
        raise EslError("MESH_INPUT_INVALID", f"메시 파일을 읽지 못함({exc.code}): {exc.message}") from None
    infos: list[dict] = []
    warns: list[dict] = []
    lu = length_unit(rm.begin)
    if lu["ok"] is False:
        raise EslError("MESH_INPUT_UNIT", f"/BEGIN 입력 길이 단위 {lu['unit']!r} 가 mm 가 아님(변환하지 않음)")
    if lu["ok"] is None:
        infos.append({"code": "MESH_INPUT_UNIT_ASSUMED", "message": "/BEGIN 길이 단위가 없어 mm 로 봄"})
    for w in rm.warnings:
        code, _sep, msg = str(w).partition(": ")
        rec = {"code": code if _sep and code.isupper() else "INFO", "message": msg if _sep and code.isupper() else str(w)}
        (infos if rec["code"] == "MESH_INPUT_PART_CARD_MISSING" else warns).append(rec)
    mc = cfg["mesh"]
    ne_in = int(rm.elem_id.size)
    if ne_in > int(mc["max_elems"]):
        raise EslError("MESH_TOO_LARGE", f"요소 {ne_in} > 상한 mesh.max_elems {mc['max_elems']}")
    X = np.asarray(rm.x0, dtype=np.float64)
    conn = np.asarray(rm.conn, dtype=np.int64)
    et = np.where(np.asarray(rm.elem_type).astype(int) == 4, 4, 3).astype(np.int64)
    # build_mesh 와 같은 정리(퇴화 요소 제거·미사용 노드 제거)를 하며 원 ID 를 따라가기 위해 keep·used 를 다시 계산
    k = np.where(et == 4, 4, 3)
    dup = np.zeros(conn.shape[0], bool)
    for a in range(4):
        for b in range(a + 1, 4):
            dup |= (b < k) & (conn[:, a] == conn[:, b])
    area = mg._elem_area(X, np.where(conn >= 0, conn, conn[:, :1]), et)
    keep = ~dup & (area > mg._AREA_MIN)
    used = np.unique(conn[keep][conn[keep] >= 0])
    mesh, info = mg.build_mesh(X, conn, et, props, normal_ref)
    id_map = {"node_id_orig": np.asarray(rm.node_id)[used].astype(np.int64),
              "elem_id_orig": np.asarray(rm.elem_id)[keep].astype(np.int64)}
    oc = opt_cfg or opt_settings(None)
    qual = mg.quality(mesh, cfg, oc)
    errs = [e for e in qual["errors"] if e["code"] != "MESH_DISCONNECTED"]
    e50 = edge_median(mesh)
    ncomp = n_components(mesh)
    h = float(((cfg.get("compare") or {}).get("mesh") or {}).get("size_mm") or mc.get("size_mm") or 0.0)
    r = float(mi["size_warn_ratio"])
    if h > 0 and not (h / r <= e50 <= h * r):
        warns.append({"code": "MESH_INPUT_SIZE_DIFF",
                      "message": f"요소 크기 중앙값 {e50:.2f} mm 가 기준 {h:g} mm 의 [1/{r:g}, ×{r:g}] 밖"})
    elif ref_e50 and max(e50 / float(ref_e50), float(ref_e50) / e50) > r:
        warns.append({"code": "MESH_INPUT_SIZE_DIFF",
                      "message": f"요소 크기 중앙값 {e50:.2f} mm 가 기준 형상 {float(ref_e50):.2f} mm 와 ×{r:g} 넘게 다름"})
    if ncomp > 1:
        warns.append({"code": "MESH_INPUT_DISCONNECTED", "message": f"메시 연결 성분 {ncomp}개(조각난 메시)"})
    meta = {"schema": "esl/doe_mesh/1", "method": "mesh_input", "source": "mesh", "main_rel": files[0]["rel"],
            "files": [{"rel": f["rel"], "size": f["size"]} for f in files], "part_id": int(rm.part_id),
            "part_title": rm.part_title, "length_unit": lu["unit"], "props": dict(props),
            "n_nodes": int(mesh["node_id"].size), "n_elems": int(mesh["elem_id"].size), "quad_frac": qual["quad_frac"],
            "quality": qual["metrics"], "errors": errs, "warnings": list(qual["warnings"]) + warns, "infos": infos,
            "edge_median_mm": round(e50, 6), "n_components": ncomp, **info}
    if out_dir:
        from esl.library import _util as U
        os.makedirs(out_dir, exist_ok=True)
        mg.save_npz_det(os.path.join(out_dir, mg.MESH_NPZ), {k_: mesh[k_] for k_ in mg.MESH_KEYS})
        mg.save_npz_det(os.path.join(out_dir, ID_MAP_NPZ), id_map)
        U.write_json(os.path.join(out_dir, mg.MESH_JSON), meta)
    meta["id_map"] = id_map
    if errs:
        e = errs[0]
        raise EslError("MESH_TOO_LARGE" if e["code"] == "MESH_TOO_LARGE" else "MESH_INPUT_INVALID",
                       f"메시 품질 오류 {e['code']}: {e['message']}")
    return mesh, meta


def scan_parts(dir: str, main_rel: str, cfg: dict, limit: int = 50) -> list[dict]:  # noqa: A002
    """check-inputs 용 쉘 파트 목록 [{id, title, n_shells}] (≤ limit, ``deck.scan`` 만 — 숫자 블록은 읽지 않음)."""
    from esl.rad.parser import shell_parts
    mi = _mcfg(cfg)
    files = input_files(dir, main_rel, cfg)
    ps = shell_parts(files[0]["path"], int(mi["max_include_depth"]) if mi.get("include", True) else 0)
    return [{"id": p["id"], "title": p["title"], "n_shells": p["n_shells"]} for p in ps[:int(limit)]]
