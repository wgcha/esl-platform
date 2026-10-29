"""시나리오 ①②③ 기준 메시·frame·지지·하중 (계약 esl_bead_doe.md BD-D-2·3·4·12·13·22, §8.1).

- ① ``same``: 기준 ESL Case 입력 rad 를 제자리 읽기(``esl.opt.target.case_target`` — topo 동일성·다른 모델
  MODEL_MISMATCH), frame = 기준 ESL meta.frame, 지지 = 기준 ESL 3-2-1, 하중 = 원본 F_eq 를 node_id 로 재배열(직접).
  조립 폴더(Case 입력 폴더) rad/inc 합계 > ``same.max_assem_mb`` → ASSEM_TOO_LARGE(Q1 A), 심링크·정션 → PATH_OUTSIDE_ROOT.
- ② ``mesh``: B 메시(업로드 사본 ``input/mesh/``) → ``build_template``(frame = B, 법선 정렬, 자동 3-2-1) → 크기 규칙
  (B 를 템플릿 자리로 ``size.assert_ok``) → 하중 = B 베이스라인에서 **1회** 셀 매핑(모든 안 재사용).
- ③ ``step``: gmsh 베이스라인 메시 → ②와 같은 template 규칙. 안마다 ``design_target``(frame = 베이스라인 고정,
  지지 = 안 메시 자동 3-2-1) + 셀 매핑.
- 쉘 물성 기본값(Q2 A): A Ch/R 면적 가중 두께 중앙값·주 PID E·ν. 요소 크기 기본값 = A 모서리 길이 중앙값.

저장: ``prep/base_mesh.npz``(MESH_KEYS + elem_mid) + ``prep/base.json``(scenario, frame, supports, topo, source).
"""
from __future__ import annotations

import os
import shutil

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import normalize as nz
from esl.opt import identity
from esl.opt import size as sz
from esl.opt import target as tg

BASE_NPZ = "base_mesh.npz"
BASE_JSON = "base.json"
LOADS_NPZ = "loads.npz"
MESH_EXT = (".rad", ".inc")
STATE_EXT = (".str", ".sta")
SCN_TARGET = {"same": "S1", "mesh": "S2", "step": "S2"}


# ---------------------------------------------------------------- 입력 보호·조립 폴더
def _isjunction(p: str) -> bool:
    f = getattr(os.path, "isjunction", None)
    return bool(f and f(p))


def assem_dir_check(d: str, max_mb: float) -> dict:
    """① 조립 폴더(제자리) 검사: 심링크·정션 거부, ``*.rad``·``*.inc`` 합계 상한(BD-D-13). 반환 {total_mb, n_files}."""
    if not os.path.isdir(d):
        raise EslError("PREREQUISITE_MISSING", f"기준 Case 입력 폴더가 없음: {os.path.basename(d)}")
    if os.path.islink(d) or _isjunction(d):
        raise EslError("PATH_OUTSIDE_ROOT", "기준 Case 입력 폴더가 링크임 — 거부")
    total, n = 0, 0
    for root, dirs, files in os.walk(d, followlinks=False):
        for name in list(dirs) + list(files):
            p = os.path.join(root, name)
            if os.path.islink(p) or _isjunction(p):
                raise EslError("PATH_OUTSIDE_ROOT", f"Case 입력 폴더 안에 링크가 있음: {os.path.relpath(p, d)} — 거부"
                                                    "(형상 엔진 재귀 수집이 링크를 따라가지 않게)")
        for name in files:
            if os.path.splitext(name)[1].lower() in MESH_EXT:
                total += os.path.getsize(os.path.join(root, name))
                n += 1
    mb = total / (1024 * 1024)
    if mb > float(max_mb):
        raise EslError("ASSEM_TOO_LARGE", f"Case 폴더 rad/inc 합계 {mb:.0f} MB > 상한 {float(max_mb):g} MB "
                                          "(bead_doe.same.max_assem_mb) — '다른 모델(메시 있음)'으로 Ch/R 주변만 올려 주세요")
    return {"total_mb": round(mb, 3), "n_files": n}


def is_cumulative(rad_path: str, parse_kw: dict | None = None) -> bool:
    """include 그래프에 상태 파일(.str/.sta)이 있으면 누적 씬(BD-D-22)."""
    from esl.rad.parser import scan_includes
    kw = parse_kw or {}
    incs = scan_includes(rad_path, kw.get("include_path_map"), int(kw.get("max_include_depth") or 8))
    return any(os.path.splitext(p)[1].lower() in STATE_EXT for p in incs)


def tree_stamp(d: str) -> dict:
    """{상대경로: (크기, mtime_ns, sha256)} — 입력 폴더 불변 확인용(V-BD-14)."""
    out = {}
    for root, _dirs, files in os.walk(d, followlinks=False):
        for name in files:
            p = os.path.join(root, name)
            st = os.stat(p, follow_symlinks=False)
            out[os.path.relpath(p, d)] = (int(st.st_size), int(st.st_mtime_ns), U.sha256_file(p))
    return out


def copy_mesh_upload(main_path: str, upload_root: str, dest_dir: str, writer: U.Writer | None = None,
                     max_depth: int = 8) -> list[dict]:
    """② B 메시 rad + include 를 ``dest_dir`` 로 복사(업로드 폴더 안 include 만, 복사 후 sha256 재확인, BD-D-12).

    반환 [{rel, sha256, size}] (rel = 업로드 루트 기준). include 가 업로드 밖 → PATH_OUTSIDE_ROOT, 못 찾음 → MESH_INVALID."""
    from esl.rad.parser import scan_include_refs
    root = U.real_path(upload_root)
    main = U.real_path(main_path)
    if not U.is_within(main, root):
        raise EslError("PATH_OUTSIDE_ROOT", "B 메시가 업로드 폴더 밖")
    refs = scan_include_refs(main, None, max_depth, follow=lambda p: U.is_within(U.real_path(p), root))
    files = [main]
    for r in refs:
        if not r["found"]:
            raise EslError("MESH_INVALID", f"B 메시 include 를 찾지 못함: {r['spec']}")
        rp = U.real_path(r["path"])
        if not U.is_within(rp, root):
            raise EslError("PATH_OUTSIDE_ROOT", f"B 메시 include 가 업로드 폴더 밖: {r['spec']}")
        if rp not in files:
            files.append(rp)
    out = []
    g = writer.guard if writer is not None else (lambda p: p)
    for src in files:
        if os.path.islink(src):
            raise EslError("PATH_OUTSIDE_ROOT", f"B 메시 파일이 링크임: {os.path.basename(src)}")
        rel = os.path.relpath(src, root)
        dst = os.path.join(dest_dir, rel)
        if writer is not None:
            writer.makedirs(os.path.dirname(dst))
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        sha = U.sha256_file(src)
        shutil.copyfile(src, g(dst))
        if U.sha256_file(dst) != sha:
            raise EslError("MESH_INVALID", f"B 메시 복사본 sha256 불일치: {rel}")
        out.append({"rel": rel.replace(os.sep, "/"), "sha256": sha, "size": os.path.getsize(dst)})
    return out


# ---------------------------------------------------------------- 기준 메시
def size_rows(entries) -> list[dict]:
    """선택 ESL → size 규칙 행 {entry_id, inch, L_xi, L_eta, grid}."""
    rows = []
    for e in entries:
        m = e.meta
        fr = m.get("frame") or {}
        g = m.get("grid") or {}
        rows.append({"entry_id": m.get("entry_id", getattr(e, "entry_id", None)),
                     "inch": (m.get("model") or {}).get("inch"), "L_xi": float(fr["L_xi"]), "L_eta": float(fr["L_eta"]),
                     "grid": (int(g["nx"]), int(g["ny"])) if g.get("nx") and g.get("ny") else None})
    return rows


def same_base(rad_path: str, part_title: str, base_entry, others=(), *, coord_tol_rel: float,
              parse_kw: dict | None = None) -> tuple[tg.Target, list[str]]:
    """① 기준 메시(제자리 읽기 + 동일성). others = 기준 외 선택 ESL(LibraryEntry, raw 포함)."""
    t = tg.case_target(rad_path, part_title, dict(base_entry.meta), base_entry.raw, coord_tol_rel=coord_tol_rel,
                       parse_kw=parse_kw)
    for o in others:
        if o.meta.get("entry_id") == base_entry.meta.get("entry_id"):
            continue
        rows = identity.check_entries(t.mesh, [(o.meta.get("entry_id"), o.raw)], coord_tol_rel)
        identity.assert_same(rows)
        t.source["identity"] = list(t.source.get("identity") or []) + rows
    info = []
    try:
        if is_cumulative(rad_path, parse_kw):
            info.append("BD_BASE_CUMULATIVE")
    except EslError:
        pass
    return t, info


def template_base(mesh: dict, entries, size_cfg: dict, *, inch=None, axis_ref: dict | None = None,
                  source: dict | None = None) -> tuple[tg.Target, dict]:
    """②③ 기준 메시: B 메시 → build_template(frame·법선 정렬·자동 3-2-1) → 크기 규칙(B = 템플릿). (Target, size 정보)."""
    if axis_ref is None and entries:
        axis_ref = (entries[0].meta.get("frame") or {}).get("axis_ref")
    arrays, meta = tg.build_template(mesh, axis_ref)
    fr = meta["frame"]
    info = sz.assert_ok(size_rows(entries), size_cfg, {"inch": inch, "L_xi": fr["L_xi"], "L_eta": fr["L_eta"]})
    t = tg.template_target(arrays, meta, None, source)
    t.warnings = list(info["warnings"])
    return t, U.jsonable(info)


def design_target(mesh: dict, base_frame: dict) -> tg.Target:
    """③ 안 메시 대상: frame = 베이스라인 고정(BD-D-3), 지지 = 안 메시 자동 3-2-1(BD-D-4)."""
    m = {k: np.asarray(mesh[k]) for k in tg.MESH_KEYS}
    sup = tg.auto_supports(m)
    sr = tg.support_check(m, sup)
    from esl.mech import supports as msup
    if sr["rank"] < 6 or sr["sigma_ratio"] < msup.DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 지지가 강체 6모드를 구속하지 못함: {sup}")
    return tg.Target("S2", m, base_frame, sup, {}, {}, [], identity.topo_sha256(m))


def save_base(t: tg.Target, d: str, scenario: str, writer: U.Writer | None = None, extra: dict | None = None) -> dict:
    g = writer.guard if writer is not None else (lambda p: p)
    os.makedirs(d, exist_ok=True)
    arrs = {k: np.asarray(v) for k, v in t.mesh.items() if isinstance(v, np.ndarray) or k in tg.MESH_KEYS}
    from esl.doe.mesh_gmsh import save_npz_det
    save_npz_det(g(os.path.join(d, BASE_NPZ)), arrs)
    meta = {"schema": "esl/doe_base/1", "scenario": scenario, "target": t.scenario, "frame": t.frame,
            "supports": [{"node_id": int(n), "dof": str(dof)} for n, dof in t.supports], "normals": t.normals,
            "source": t.source, "warnings": t.warnings, "topo_sha256": t.topo_sha256, "n_nodes": t.n_nodes,
            "n_elems": t.n_elems, "mesh_sha256": U.sha256_file(os.path.join(d, BASE_NPZ)), **(extra or {})}
    U.write_json(g(os.path.join(d, BASE_JSON)), meta)
    return U.jsonable(meta)


def load_base(d: str) -> tuple[tg.Target, dict]:
    arrs = U.load_npz(os.path.join(d, BASE_NPZ))
    meta = U.read_json(os.path.join(d, BASE_JSON))
    mesh = {k: arrs[k] for k in tg.MESH_KEYS}
    if "elem_mid" in arrs:
        mesh["elem_mid"] = arrs["elem_mid"]
    t = tg.Target(meta["target"], mesh, meta["frame"], [(int(s["node_id"]), str(s["dof"])) for s in meta["supports"]],
                  meta.get("normals") or {}, meta.get("source") or {}, meta.get("warnings") or [], meta.get("topo_sha256"))
    return t, meta


# ---------------------------------------------------------------- 하중
def entry_loads(t: tg.Target, entries, mapping_opts: dict | None = None, min_nodes_per_cell: int | None = None,
                grid: tuple | None = None) -> tuple[list[tuple[str, np.ndarray]], dict]:
    """선택 ESL 전부 → [(entry_id, F (N,3))] (S1 직접 / S2 셀 매핑 + 평형 보정), 정보 {method, per_entry, warnings}."""
    out, per, warns = [], [], []
    for e in entries:
        eid = e.meta.get("entry_id")
        if t.scenario == "S1":
            f, info = tg.entry_load(t, e.raw)
        else:
            f, info = tg.entry_load(t, None, e.summary_for_mapping(), mapping_opts)
        out.append((eid, np.asarray(f, dtype=np.float64)))
        per.append({"entry_id": eid, **{k: v for k, v in info.items() if k in (
            "method", "conservation_rel_max", "equilibrate_correction_rel", "n_cells_loaded", "n_cells_empty_loaded")}})
    if t.scenario == "S2" and min_nodes_per_cell is not None and grid is not None:
        nx, ny = int(grid[0]), int(grid[1])
        i, j, _ = nz.cell_index(t.frame, np.asarray(t.mesh["x0"], dtype=np.float64), nx, ny)
        cnt = np.bincount(i * ny + j, minlength=nx * ny)
        med = float(np.median(cnt[cnt > 0])) if np.any(cnt > 0) else 0.0
        if med < float(min_nodes_per_cell):
            warns.append(f"MAPPING_RESOLUTION: 셀당 노드 중앙값 {med:.0f} < {min_nodes_per_cell} ({nx}×{ny} 셀)")
    return out, {"method": "direct_nodal" if t.scenario == "S1" else "cell_mapping", "per_entry": U.jsonable(per),
                 "warnings": warns}


def save_loads(d: str, node_id, loads, writer: U.Writer | None = None) -> str:
    """prep/loads.npz: node_id, entry_ids, F (K,N,3) float64 (①②, BD-D-3)."""
    g = writer.guard if writer is not None else (lambda p: p)
    from esl.doe.mesh_gmsh import save_npz_det
    p = os.path.join(d, LOADS_NPZ)
    F = np.stack([f for _, f in loads]) if loads else np.zeros((0, 0, 3))
    save_npz_det(g(p), {"node_id": np.asarray(node_id, dtype=np.int64),
                        "entry_ids": np.asarray([str(e) for e, _ in loads]), "F": F.astype(np.float64)})
    return U.sha256_file(p)


def load_loads(d: str) -> tuple[np.ndarray, list[tuple[str, np.ndarray]]]:
    a = U.load_npz(os.path.join(d, LOADS_NPZ))
    return a["node_id"], [(str(e), a["F"][k]) for k, e in enumerate(a["entry_ids"].tolist())]


def supports_ab(t: tg.Target) -> list[dict]:
    from esl.opt.keepout import project_ab
    nid = np.asarray(t.mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    X = np.asarray(t.mesh["x0"], dtype=np.float64)
    return [{"node_id": int(n), "dof": str(d), "xyz": X[pos[int(n)]].tolist(),
             "ab": project_ab(t.frame, X[pos[int(n)]])[0].tolist()} for n, d in t.supports]


# ---------------------------------------------------------------- 기본값 (Q2 A, §7.1)
def _areas(raw: dict) -> np.ndarray:
    from esl.library.entry import _areas as areas
    return np.asarray(areas(np.asarray(raw["x0"], dtype=np.float64), np.asarray(raw["conn"]),
                            np.asarray(raw["elem_type"])), dtype=np.float64)


def weighted_median(v, w) -> float:
    v = np.asarray(v, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    o = np.argsort(v, kind="stable")
    c = np.cumsum(w[o])
    if c.size == 0 or c[-1] <= 0:
        return float(np.median(v)) if v.size else float("nan")
    return float(v[o][int(np.searchsorted(c, 0.5 * c[-1]))])


def props_default(raw: dict) -> dict:
    """③ 쉘 물성 기본값 {t, E, nu}: 면적 가중 두께 중앙값, 주 PID(면적 최대, 동률 작은 PID)의 E·ν 중앙값."""
    A = _areas(raw)
    ne = A.size
    t = np.broadcast_to(np.asarray(raw["thickness"], dtype=np.float64), (ne,))
    E = np.broadcast_to(np.asarray(raw["E"], dtype=np.float64), (ne,))
    nu = np.broadcast_to(np.asarray(raw["nu"], dtype=np.float64), (ne,))
    pid = np.asarray(raw.get("elem_pid", np.zeros(ne, np.int64)), dtype=np.int64)
    ups = np.unique(pid)
    pa = [(-float(A[pid == p].sum()), int(p)) for p in ups]
    main = min(pa)[1]
    m = pid == main
    return {"t": weighted_median(t, A), "E": float(np.median(E[m])), "nu": float(np.median(nu[m])), "pid": main}


def mesh_size_default(raw: dict, mcfg: dict) -> float:
    """요소 크기 기본값 = A 메시 모서리 길이 중앙값(``mesh.size_min_mm``..``size_max_mm`` 로 자름)."""
    from esl.opt.mesh_check import _edge_lengths
    L = _edge_lengths(np.asarray(raw["x0"], dtype=np.float64), np.asarray(raw["conn"], dtype=np.int64),
                      np.asarray(raw["elem_type"]).astype(int))
    h = float(np.nanmedian(L))
    return float(min(max(h, float(mcfg["size_min_mm"])), float(mcfg["size_max_mm"])))
