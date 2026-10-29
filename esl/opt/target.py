"""최적화 대상 준비·하중·덱 입력 (계약 esl_opt_run.md OR-D-2·3·6·9·10, §6.2 OR-1·OR-3).

대상 어댑터
- S1 ``case_target(rad_path, part_title, base_meta, base_raw, …)``: 기준 ESL Case 입력 rad 를 ``parse_rad`` 로
  **제자리 읽기**(복사·쓰기 없음, 대상 파트만 해석). 기준 ESL raw 와 동일성(0.5.5) 확인, frame = 기준 ESL
  ``meta.frame``, 지지 = 기준 ESL 3-2-1. 법선은 원 연결 유지 — frame n 과 반대인 요소 수·위치는 경고만.
- S2 ``build_template(mesh)`` → template.npz 배열 + template.json(frame, 법선 정렬 수, 자동 3-2-1),
  ``template_target(arrays, meta, supports=None)``: 템플릿 법선을 n 쪽으로 정렬한 연결(덱에 그대로).

하중(``entry_load``)
- S1 = 원본 F_eq 를 node_id 로 대상 노드 순서에 재배열(셀 매핑·평형 보정 없음).
- S2 = ``esl.library.mapping.to_target``(24×14 셀 합력·합모멘트, moment_scale preserve, 평형 보정) — 매핑 알고리즘 변경 0.

덱 입력: ``design_mask`` (비설계 PID ∪ 금지 영역, 설계 0 → KEEPOUT_ALL), ``deck_design``·``deck_load_cases`` →
``esl.library.optdeck.write``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import mapping as mp
from esl.library import normalize as nz
from esl.mech import supports as msup
from esl.opt import identity

MESH_KEYS = ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu")


@dataclass
class Target:
    scenario: str
    mesh: dict
    frame: dict
    supports: list
    normals: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    topo_sha256: str | None = None

    @property
    def n_nodes(self) -> int:
        return int(np.asarray(self.mesh["node_id"]).size)

    @property
    def n_elems(self) -> int:
        return int(np.asarray(self.mesh["elem_id"]).size)


# ---------------------------------------------------------------- 법선
def elem_normals(mesh: dict) -> np.ndarray:
    """요소 법선(단위): QUAD (x3−x1)×(x4−x2), TRIA (x2−x1)×(x3−x1) — 쉘 솔버·OptiStruct 와 같은 연결 순서 규약."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    c = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    q = et == 4
    n = np.empty((c.shape[0], 3))
    n[q] = np.cross(X[c[q, 2]] - X[c[q, 0]], X[c[q, 3]] - X[c[q, 1]])
    n[~q] = np.cross(X[c[~q, 1]] - X[c[~q, 0]], X[c[~q, 2]] - X[c[~q, 0]])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    return n / ln[:, None]


def opposite_mask(mesh: dict, n) -> np.ndarray:
    return elem_normals(mesh) @ np.asarray(n, dtype=np.float64) < 0


def align_normals(mesh: dict, n) -> tuple[np.ndarray, np.ndarray]:
    """법선이 n 과 반대인 요소의 연결 순서를 뒤집은 conn, 뒤집은 요소 마스크."""
    c = np.array(mesh["conn"], dtype=np.int64, copy=True)
    et = np.asarray(mesh["elem_type"]).astype(int)
    flip = opposite_mask(mesh, n)
    q = flip & (et == 4)
    t = flip & (et != 4)
    c[q] = c[q][:, [0, 3, 2, 1]]
    c[t, :3] = c[t][:, [0, 2, 1]]
    return c, flip


def _normal_info(mesh, frame, mask, mode) -> dict:
    eid = np.asarray(mesh["elem_id"], dtype=np.int64)
    ab = None
    if mask.any():
        from esl.opt.keepout import centroids, project_ab
        ab = project_ab(frame, centroids(mesh)[mask])
    key = "normals_flipped" if mode == "aligned" else "normals_opposite"
    return {"mode": mode, key: int(mask.sum()), "elem_ids": eid[mask][:50].tolist(),
            "ab_mean": None if ab is None else ab.mean(axis=0).tolist()}


# ---------------------------------------------------------------- 3-2-1
def auto_supports(mesh: dict) -> list:
    """PCA 4꼭지점 → pick_321 → [(node_id, dof)] (코어 Case 3-2-1 과 같은 규칙)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pc = msup.pca_corners(X)
    return [(int(nid[i]), str(d)) for i, d in msup.pick_321(X, pc["idx"])]


def support_check(mesh: dict, supports) -> dict:
    from esl.library.optdeck import support_rank
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    miss = [int(n) for n, _ in supports if int(n) not in pos]
    if miss:
        raise EslError("NODE_NOT_IN_PART", f"3-2-1 노드 {miss} 가 대상 메시에 없음")
    return support_rank(np.asarray(mesh["x0"], dtype=np.float64), [pos[int(n)] for n, _ in supports],
                        [str(d) for _, d in supports])


# ---------------------------------------------------------------- S1
def _rad_mesh(rm) -> dict:
    return {"node_id": rm.node_id, "x0": rm.x0, "elem_id": rm.elem_id, "elem_type": rm.elem_type, "conn": rm.conn,
            "elem_pid": rm.elem_pid, "thickness": rm.thickness, "E": rm.E, "nu": rm.nu,
            "elem_mid": np.full(rm.elem_id.size, int(rm.mats[0]["id"]) if rm.mats else 0, dtype=np.int64)}


def file_stamp(path: str) -> dict:
    st = os.stat(path)
    return {"path": path, "sha256": U.sha256_file(path), "size": int(st.st_size), "mtime": float(st.st_mtime)}


def case_target(rad_path: str, part_title: str, base_meta: dict, base_raw: dict, *, coord_tol_rel: float,
                parse_kw: dict | None = None, others: list | None = None) -> Target:
    """S1 대상. others = [(entry_id, raw)] 선택 ESL(기준 포함 가능) — 전부 대상과 같은 모델이어야 함."""
    from esl.rad.parser import parse_rad
    if not rad_path or not os.path.isfile(rad_path):
        raise EslError("PREREQUISITE_MISSING", f"기준 Case 입력 rad 가 없음: {rad_path} (Case 입력 다시 올리기 또는 "
                                               "템플릿 최적화)")
    try:
        rm = parse_rad(rad_path, part_title, **(parse_kw or {}))
    except EslError as exc:
        if exc.code in ("PART_NOT_FOUND", "PART_AMBIGUOUS", "UNSUPPORTED_ELEMENT", "MATERIAL_UNRESOLVED"):
            raise
        raise EslError("PREREQUISITE_MISSING", f"기준 Case 입력 rad 를 읽지 못함: {exc}") from None
    mesh = _rad_mesh(rm)
    rows = identity.check_entries(mesh, [(base_meta.get("entry_id"), base_raw)] + list(others or []),
                                  coord_tol_rel)
    identity.assert_same(rows)
    frame = base_meta["frame"]
    opp = opposite_mask(mesh, frame["n"])
    warns = list(rm.warnings)
    if opp.any():
        warns.append(f"법선이 frame n 과 반대인 요소 {int(opp.sum())}개 — 원 연결 유지(비드는 그 요소 법선 쪽), 위치 확인")
    sup = [(int(s["node_id"]), str(s["dof"])) for s in base_meta["esl"]["supports"]]
    support_check(mesh, sup)
    return Target("S1", mesh, frame, sup, _normal_info(mesh, frame, opp, "kept"),
                  {"rad": file_stamp(rad_path), "part_title": rm.part_title, "part_id": rm.part_id,
                   "rho": rm.mats[0].get("rho") if rm.mats else None,
                   "base_entry_id": base_meta.get("entry_id"), "identity": rows},
                  warns, identity.topo_sha256(mesh))


# ---------------------------------------------------------------- S2
def build_template(mesh: dict, axis_ref: dict | None = None) -> tuple[dict, dict]:
    """템플릿 메시 → (template.npz 배열, template.json 메타). 법선은 frame n 쪽으로 정렬."""
    m = {k: np.asarray(mesh[k]) for k in MESH_KEYS}
    m["elem_mid"] = np.asarray(mesh.get("elem_mid", np.zeros(m["elem_id"].size, np.int64)))
    fr = nz.frame(m["x0"], axis_ref, m["conn"], m["elem_type"])
    conn, flip = align_normals(m, fr["n"])
    m["conn"] = conn
    sup = auto_supports(m)
    meta = {"schema": "esl/opt_template/1", "frame": fr, "normals": _normal_info(m, fr, flip, "aligned"),
            "supports_auto": [{"node_id": n, "dof": d} for n, d in sup], "topo_sha256": identity.topo_sha256(m),
            "n_nodes": int(m["node_id"].size), "n_elems": int(m["elem_id"].size)}
    return m, U.jsonable(meta)


def template_target(arrays: dict, meta: dict, supports=None, source: dict | None = None) -> Target:
    mesh = {k: np.asarray(arrays[k]) for k in MESH_KEYS}
    if "elem_mid" in arrays:
        mesh["elem_mid"] = np.asarray(arrays["elem_mid"])
    sup = [(int(n), str(d)) for n, d in supports] if supports else \
        [(int(s["node_id"]), str(s["dof"])) for s in meta["supports_auto"]]
    sr = support_check(mesh, sup)
    if sr["rank"] < 6 or sr["sigma_ratio"] < msup.DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 지지가 강체 6모드를 구속하지 못함: {sup}")
    return Target("S2", mesh, meta["frame"], sup, dict(meta.get("normals") or {}), dict(source or {}), [],
                  meta.get("topo_sha256"))


# ---------------------------------------------------------------- 하중
def entry_load(target: Target, raw: dict | None, summary_for_mapping: dict | None = None,
               mapping_opts: dict | None = None) -> tuple[np.ndarray, dict]:
    """ESL 1개 → 대상 노드 순서 하중 (N,3). S1 직접(raw f·node_id), S2 셀 매핑(summary)."""
    tn = np.asarray(target.mesh["node_id"], dtype=np.int64)
    if target.scenario == "S1":
        if raw is None:
            raise EslError("INPUT_INVALID", "S1 직접 적용에는 항목 raw(f, node_id) 필요")
        sn = np.asarray(raw["node_id"], dtype=np.int64)
        order = np.argsort(sn, kind="stable")
        pos = np.searchsorted(sn[order], tn)
        pos = np.minimum(pos, sn.size - 1)
        if not np.array_equal(sn[order][pos], tn):
            raise EslError("MODEL_MISMATCH", "S1 직접 적용: 대상 노드 ID 가 ESL 노드 ID 와 다름")
        f = np.asarray(raw["f"], dtype=np.float64)[order][pos]
        return f.copy(), {"method": "direct_nodal", "self": True}
    if summary_for_mapping is None:
        raise EslError("INPUT_INVALID", "S2 셀 매핑에는 항목 요약(summary) 필요")
    o = {"moment_scale": "preserve", "equilibrate": True}
    o.update(mapping_opts or {})
    f, info = mp.to_target(summary_for_mapping, np.asarray(target.mesh["x0"], dtype=np.float64), target.frame, o)
    info = dict(info)
    info.pop("F_cells", None)
    info["method"] = "cell_mapping"
    return np.asarray(f, dtype=np.float64), info


# ---------------------------------------------------------------- 설계/비설계
def design_mask(target: Target, nondesign_pids, keepout_mask) -> tuple[np.ndarray, dict]:
    pid = np.asarray(target.mesh["elem_pid"], dtype=np.int64)
    nd_pid = np.isin(pid, np.asarray(list(nondesign_pids or []), dtype=np.int64))
    ko = np.zeros(pid.size, bool) if keepout_mask is None else np.asarray(keepout_mask, dtype=bool)
    des = ~(nd_pid | ko)
    info = {"n_nondesign_pid": int(nd_pid.sum()), "n_keepout": int(ko.sum()), "n_design_elems": int(des.sum()),
            "n_elems": int(pid.size)}
    if not des.any():
        raise EslError("KEEPOUT_ALL", f"금지 영역·비설계 PID 를 빼면 설계 요소가 0 (요소 {pid.size}, 비설계 PID "
                                      f"{int(nd_pid.sum())}, 금지 영역 {int(ko.sum())})")
    return des, info


def deck_load_cases(selection: dict, forces: dict) -> list[dict]:
    """LoadSelection(선정 행 label·pos) + {entry_id: F (N,3)} → optdeck load_cases (라벨 순 = C 내림차순)."""
    rows = sorted((r for r in selection["rows"] if r.get("label")), key=lambda r: r["label"])
    out = []
    for r in rows:
        if r["entry_id"] not in forces:
            raise EslError("INPUT_INVALID", f"선정 하중 {r['label']} ({r['entry_id']}) 의 하중 배열이 없음")
        out.append({"label": r["label"], "entry_id": r["entry_id"], "f": forces[r["entry_id"]], "ref": r["pos"]})
    return out


def deck_design(target: Target, *, design: np.ndarray, bead: dict, run_id, desmax: int, selection: dict,
                optdeck_cfg: dict | None = None) -> dict:
    """optdeck.write 의 design dict (minmax, 비설계 = PID ∪ 금지 영역 요소, server 카드)."""
    oc = optdeck_cfg or {}
    eid = np.asarray(target.mesh["elem_id"], dtype=np.int64)
    d = {"objective": "minmax", "nondesign_elem_ids": eid[~np.asarray(design, dtype=bool)].tolist(),
         "bead": {"min_width": float(bead["min_width"]), "angle": float(bead["angle"]), "height": float(bead["height"]),
                  "bounds": [0.0, 1.0]},
         "server": {"opt_run_id": run_id, "scenario": target.scenario, "desmax": int(desmax)},
         "header": [f"objective_norm {selection['objective_norm']} C_ref {selection['C_ref']!r}",
                    f"load_strategy {selection['strategy']}" + (f" k {selection['k']}" if selection.get("k") else ""),
                    "subcases: " + ", ".join(f"{r['label']}={r['entry_id']}" for r in
                                             sorted((r for r in selection["rows"] if r.get("label")),
                                                    key=lambda r: r["label"]))]}
    for k in ("id_offset", "card_format", "num_format", "force_zero_tol_rel", "nt", "dtpg"):
        if oc.get(k) is not None:
            d[k] = oc[k]
    return d


# ---------------------------------------------------------------- 저장
def save(target: Target, d: str, writer: U.Writer | None = None, extra: dict | None = None) -> dict:
    """target.npz(메시 + extra 배열: design, keepout_reason …) + target.json."""
    g = writer.guard if writer is not None else (lambda p: p)
    os.makedirs(d, exist_ok=True)
    arrs = {k: np.asarray(v) for k, v in target.mesh.items()}
    arrs.update({k: np.asarray(v) for k, v in (extra or {}).items()})
    np.savez_compressed(g(os.path.join(d, "target.npz")), **arrs)
    meta = {"schema": "esl/opt_target/1", "scenario": target.scenario, "frame": target.frame,
            "supports": [{"node_id": n, "dof": dof} for n, dof in target.supports], "normals": target.normals,
            "source": target.source, "warnings": target.warnings, "topo_sha256": target.topo_sha256,
            "n_nodes": target.n_nodes, "n_elems": target.n_elems}
    U.write_json(g(os.path.join(d, "target.json")), meta)
    return U.jsonable(meta)


def load(d: str) -> tuple[Target, dict]:
    arrs = U.load_npz(os.path.join(d, "target.npz"))
    meta = U.read_json(os.path.join(d, "target.json"))
    mesh = {k: arrs[k] for k in MESH_KEYS}
    if "elem_mid" in arrs:
        mesh["elem_mid"] = arrs["elem_mid"]
    extra = {k: v for k, v in arrs.items() if k not in mesh}
    t = Target(meta["scenario"], mesh, meta["frame"], [(int(s["node_id"]), str(s["dof"])) for s in meta["supports"]],
               meta.get("normals") or {}, meta.get("source") or {}, meta.get("warnings") or [], meta.get("topo_sha256"))
    return t, extra
