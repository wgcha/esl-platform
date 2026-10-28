"""Case 출력 폴더 → 라이브러리 항목 (계약 esl_p2_library.md §1 저장 3층).

``build(case_dir, run_id=None, **opts) -> LibraryEntry``: Case 폴더를 **읽기만** 한다.

- run_id 가 있으면 플랫폼 스냅샷 ``<case>/runs/<run_id>/{03_bc,04_esl[,05_val]}`` 를, 없으면 현재
  ``03_bc``·``04_esl`` 을 쓴다. 메시는 ``01_extract/model.npz``.
- 검증: ``05_val/validation.json``(run 스냅샷에 있으면 그것) 의 ``esl_ref`` 가 이 ESL 결과(esl_summary 의 tag 또는
  created_at)와 같을 때만 품질로 채택. 다르면 verdict=None + 경고.
- 3층: ``raw``(원본: 메시·F_eq·u_rel·3-2-1, 등록 시점 스냅샷 배열), ``summary``(정규화 격자 요약 npz),
  ``meta``(모델·씬·품질·t*·원본 경로·sha256 등 JSON).
- 씬 경로 후보: scene_path 인자 > frames.json 의 h3d > run.json 의 결과 폴더 > Case 폴더. 각 후보를
  ``scene_meta.parse`` 해서 null 필수 필드가 가장 적은 것(동률은 앞 순서)을 쓴다.

저장: ``save(entry, dir)`` → ``entry.json``, ``raw.npz``, ``summary.npz``. 읽기: ``load(dir, raw=True)``.

v0.7.0(esl_opt_run.md §7.3·§7.4): 등록 시 ``meta.topo_sha256``(노드 ID + 요소 연결, 좌표 제외 — S1 모델 키)와
``meta.deform_mode``(변형 모드 자동 분류 레코드 {auto, metrics, user: None, …, rule_version})를 함께 기록한다.
분류 기준값은 ``mode_cfg``(설정 ``opt_run.mode``, 없으면 ``esl.opt.DEFAULTS``). 분류 실패는 경고만(None).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import normalize as nz
from esl.library import scene_meta

SCHEMA = "esl/library_entry/1"
RAW_KEYS = ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "elem_mid", "thickness", "E", "nu",
            "f", "u_rel", "is_bc", "support_node_id", "support_dof")
SUMMARY_KEYS = ("cell_F", "cell_M", "cell_F_loc", "cell_M_loc", "cell_n", "cell_center", "total_F", "total_M",
                "total_F_loc", "total_M_loc", "sum_abs_f", "top_node_id", "top_xi", "top_eta", "top_f", "top_f_loc",
                "top_mag")


@dataclass
class LibraryEntry:
    meta: dict
    summary: dict = field(default_factory=dict)
    raw: dict | None = None

    @property
    def entry_id(self) -> str:
        return self.meta["entry_id"]

    def summary_for_mapping(self) -> dict:
        return {**self.summary, "nx": self.meta["grid"]["nx"], "ny": self.meta["grid"]["ny"],
                "frame": self.meta["frame"]}

    def mesh(self) -> dict:
        if self.raw is None:
            raise EslError("INPUT_INVALID", f"항목 {self.entry_id}: 원본(raw) 배열을 읽지 않음")
        return {k: self.raw[k] for k in ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness",
                                         "E", "nu")} | {"max_ids": self.meta["model"].get("max_ids") or {},
                                                        "part_id": self.meta["model"].get("part_id"),
                                                        "part_title": self.meta["model"].get("part_title")}


def _req(path: str) -> str:
    if not os.path.isfile(path):
        raise EslError("PREREQUISITE_MISSING", f"Case 산출물이 없음: {path}")
    return path


def _areas(x0, conn, et):
    conn = np.asarray(conn)
    q = np.asarray(et) == 4
    A = np.zeros(conn.shape[0])
    a, b, c = x0[conn[:, 0]], x0[conn[:, 1]], x0[conn[:, 2]]
    A += 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if q.any():
        d = x0[conn[q, 3]]
        A[q] += 0.5 * np.linalg.norm(np.cross(c[q] - a[q], d - a[q]), axis=1)
    return A


def part_mass(raw: dict, mats: list) -> float | None:
    """Σ ρ·t·A (요소 재료 rho 가 모두 있을 때). 모델 단위계 질량."""
    rho = {int(m["id"]): m.get("rho") for m in (mats or [])}
    mids = np.asarray(raw["elem_mid"])
    vals = []
    for m in mids:
        r = rho.get(int(m))
        if r is None or not np.isfinite(float(r)) or float(r) <= 0:
            return None
        vals.append(float(r))
    A = _areas(raw["x0"], raw["conn"], raw["elem_type"])
    return float(np.sum(np.asarray(vals) * np.asarray(raw["thickness"]) * A))


def _scene(cands: list[tuple[str, str]], rules) -> tuple[dict, str]:
    best, best_n, src = None, None, None
    for kind, p in cands:
        if not p:
            continue
        r = scene_meta.parse(p, rules)
        n = sum(1 for w in r["warnings"] if "찾지 못함" in w)
        if best is None or n < best_n:
            best, best_n, src = r, n, kind
    return best, src


def _field_summary(val: dict) -> dict | None:
    fld = val.get("field")
    if not isinstance(fld, dict):
        return None
    out = {}
    for k, v in fld.items():
        if v is None or isinstance(v, (int, float, str, bool)):
            out[k] = v
        elif isinstance(v, dict) and all(x is None or isinstance(x, (int, float, str, bool)) for x in v.values()):
            out[k] = v
    return out


def build(case_dir: str, run_id: str | None = None, *, scene_path: str | None = None, rules: dict | None = None,
          nx: int = 24, ny: int = 14, axis_ref: dict | None = None, top_n: int = 50, mass: float | None = None,
          registered_by: str | None = None, mode_cfg: dict | None = None) -> LibraryEntry:
    case_dir = os.path.abspath(case_dir)
    if not os.path.isdir(case_dir):
        raise EslError("INPUT_INVALID", f"Case 폴더가 없음: {case_dir}")
    base = os.path.join(case_dir, "runs", str(run_id)) if run_id else case_dir
    if run_id and not os.path.isdir(base):
        raise EslError("PREREQUISITE_MISSING", f"run 스냅샷이 없음: {base}")
    warns: list[str] = []
    files: dict[str, str] = {
        "model.npz": _req(os.path.join(case_dir, "01_extract", "model.npz")),
        "model_meta.json": _req(os.path.join(case_dir, "01_extract", "model_meta.json")),
        "support.json": _req(os.path.join(base, "03_bc", "support.json")),
        "f_eq.npz": _req(os.path.join(base, "04_esl", "f_eq.npz")),
        "u_rel.npz": _req(os.path.join(base, "04_esl", "u_rel.npz")),
        "esl_summary.json": _req(os.path.join(base, "04_esl", "esl_summary.json")),
    }
    for name, p in (("frames.json", os.path.join(case_dir, "01_extract", "frames.json")),
                    ("tstar.json", os.path.join(case_dir, "02_tstar", "tstar.json")),
                    ("run.json", os.path.join(case_dir, "run.json"))):
        if os.path.isfile(p):
            files[name] = p
    vp = os.path.join(base, "05_val", "validation.json")
    if not os.path.isfile(vp):
        vp = os.path.join(case_dir, "05_val", "validation.json")
    if os.path.isfile(vp):
        files["validation.json"] = vp

    mz = U.load_npz(files["model.npz"])
    mmeta = U.read_json(files["model_meta.json"])
    fz = U.load_npz(files["f_eq.npz"])
    uz = U.load_npz(files["u_rel.npz"])
    summ = U.read_json(files["esl_summary.json"])
    sup = U.read_json(files["support.json"])["supports"]
    if not (np.array_equal(fz["node_id"], mz["node_id"]) and np.array_equal(uz["node_id"], mz["node_id"])):
        raise EslError("ID_MISMATCH", "04_esl node_id 가 01_extract/model.npz 와 다름")
    raw = {k: mz[k] for k in ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "elem_mid", "thickness",
                              "E", "nu")}
    raw["f"] = np.asarray(fz["f"], dtype=np.float64)
    raw["u_rel"] = np.asarray(uz["u_rel"], dtype=np.float64)
    raw["is_bc"] = np.asarray(fz["is_bc"], dtype=bool)
    raw["support_node_id"] = np.array([int(s["node_id"]) for s in sup], dtype=np.int64)
    raw["support_dof"] = np.array([str(s["dof"]) for s in sup])

    # ---- 품질(검증)
    ref = summ.get("tag") or summ.get("created_at")
    quality = {"verdict": None, "status": None, "scheme": None, "undetermined_reason": None, "fail_reasons": [],
               "hotspot1_rel_err": None, "disp_rms_rel": None, "disp_max_rel": None, "disp_noise_rel": None,
               "strain_exceed_frac": None, "reaction_rel": None, "noise": summ.get("noise"), "field": None, "hotspots": [], "esl_ref": ref}
    val = U.read_json(files["validation.json"]) if "validation.json" in files else None
    if val is None:
        warns.append("검증 결과(05_val/validation.json) 없음")
    elif val.get("esl_ref") is not None and val.get("esl_ref") != ref:
        warns.append(f"검증 결과의 esl_ref({val.get('esl_ref')}) 가 이 ESL 결과({ref}) 의 것이 아님 — 품질 미채택")
        val = None
    fr = nz.frame(raw["x0"], axis_ref, raw["conn"], raw["elem_type"])
    warns += [f"frame: {w}" for w in fr["warnings"]]
    if val is not None:
        mets = {m["metric"]: m.get("value") for m in val.get("metrics", [])}
        scheme = val.get("verdict_scheme")           # 0.5.7 이전(schema 2) 검증은 scheme 없음 = LEGACY
        sref = val.get("strain_ref") if isinstance(val.get("strain_ref"), dict) else {}
        quality.update(verdict=val.get("verdict"), scheme=scheme, status=val.get("verdict") if scheme else "LEGACY",
                       undetermined_reason=val.get("undetermined_reason"),
                       strain_exceed_frac=sref.get("frac_exceed"),
                       disp_max_rel=mets.get("disp_max_rel"), disp_noise_rel=mets.get("disp_noise_rel"),
                       fail_reasons=list(val.get("fail_reasons") or []),
                       hotspot1_rel_err=mets.get("hotspot1_strain_rel_err"), disp_rms_rel=mets.get("disp_rms_rel"),
                       reaction_rel=mets.get("reaction_rel"), field=_field_summary(val))
        hs = []
        for h in val.get("hotspots") or []:
            c = h.get("centroid")
            if c is None:
                continue
            loc = nz.local_coords(fr, np.asarray(c, dtype=float))[0]
            hs.append({"rank": h.get("rank"), "elem_id": h.get("elem_id"), "xi": float(loc[0]), "eta": float(loc[1]),
                       "eps_rad": h.get("eps_rad"), "eps_val": h.get("eps_val"), "rel_err": h.get("rel_err")})
        quality["hotspots"] = hs

    # ---- 정규화 요약
    gs = nz.grid_summary(raw["x0"], raw["f"], nx, ny, fr, top_n=top_n, node_id=raw["node_id"])
    summary = {k: gs[k] for k in SUMMARY_KEYS}

    # ---- 씬 메타
    fmeta = U.read_json(files["frames.json"]) if "frames.json" in files else {}
    runj = U.read_json(files["run.json"]) if "run.json" in files else {}
    res_dir = ((runj.get("inputs") or {}).get("results_dir")) if isinstance(runj, dict) else None
    cands = [("scene_path", scene_path), ("h3d", fmeta.get("h3d")), ("results_dir", res_dir), ("case_dir", case_dir)]
    scene, scene_src = _scene(cands, rules)
    scene["path_kind"] = scene_src
    warns += [f"scene: {w}" for w in scene["warnings"]]

    # ---- 모델·질량
    pm = part_mass(raw, mmeta.get("mats") or [])
    if mass is not None:
        mrec = {"value": float(mass), "source": "user"}
    elif pm is not None:
        mrec = {"value": pm, "source": "part", "note": "대상 파트 질량(Σρ·t·A) — 제품 질량이 아님"}
    else:
        mrec = {"value": None, "source": None}
        warns.append("질량 없음(rho 미정·사용자 입력 없음) — normalization=mass 불가")
    mesh_sha = U.sha256_arrays(raw["node_id"], raw["x0"], raw["conn"], raw["elem_type"])
    load_sha = U.sha256_arrays(raw["f"])
    entry_id = "E" + U.sha256_arrays(np.frombuffer((mesh_sha + load_sha + str(run_id or "")).encode(), np.uint8))[:12]
    src_files = {}
    for k, p in files.items():
        st = os.stat(p)
        src_files[k] = {"path": p, "sha256": U.sha256_file(p), "size": int(st.st_size)}
    magn = np.linalg.norm(raw["f"], axis=1)
    sumabs = float(magn.sum())
    topo, dmode = opt_meta(raw, fr, mode_cfg, warns)
    meta = {
        "schema": SCHEMA, "entry_id": entry_id, "status": "active", "registered_at": U.utcnow(),
        "registered_by": registered_by,
        "source": {"case_dir": case_dir, "run_id": run_id, "snapshot_dir": base, "files": src_files},
        "mesh_sha256": mesh_sha, "load_sha256": load_sha, "topo_sha256": topo, "deform_mode": dmode,
        "model": {"product": scene.get("model"), "inch": scene.get("inch"), "version": scene.get("version"),
                  "date": scene.get("date"), "project": scene.get("project"),
                  "part_id": mmeta.get("part_id"), "part_title": mmeta.get("part_title"),
                  "units_label": mmeta.get("units_label"), "n_nodes": int(raw["node_id"].size),
                  "n_elems": int(raw["elem_id"].size), "max_ids": mmeta.get("max_ids") or {},
                  "mats": mmeta.get("mats") or [], "mass": mrec, "part_mass": pm},
        "scene": scene,
        "quality": quality,
        "tstar": summ.get("frame"),
        "esl": {"kabsch": {k: (summ.get("kabsch") or {}).get(k) for k in ("rot_deg", "rms_def", "max_def")},
                "forces": summ.get("forces"), "support_mode": summ.get("support_mode"),
                "supports": [{"node_id": int(s["node_id"]), "dof": s["dof"]} for s in sup]},
        "frame": fr,
        "grid": {"nx": int(nx), "ny": int(ny), "top_n": int(top_n)},
        "summary": {"total_F": gs["total_F"], "total_M": gs["total_M"], "total_F_loc": gs["total_F_loc"],
                    "total_M_loc": gs["total_M_loc"], "sum_abs_f": sumabs, "max_f": float(magn.max()) if magn.size else 0.0,
                    "n_cells_loaded": int(np.sum(np.linalg.norm(gs["cell_F"], axis=2) > 0)),
                    "top": [{"node_id": int(gs["top_node_id"][k]), "xi": float(gs["top_xi"][k]),
                             "eta": float(gs["top_eta"][k]), "f": gs["top_f"][k], "f_loc": gs["top_f_loc"][k]}
                            for k in range(min(10, gs["top_node_id"].size))]},
        "warnings": warns,
    }
    return LibraryEntry(meta=U.jsonable(meta), summary=summary, raw=raw)


def opt_meta(raw: dict, fr: dict, mode_cfg: dict | None = None, warns: list | None = None):
    """(topo_sha256, deform_mode 레코드) — 등록 시·지연 백필 공용."""
    from esl.opt import DEFAULTS
    from esl.opt import identity, modes
    topo = identity.topo_sha256(raw)
    mc = mode_cfg or DEFAULTS["mode"]
    try:
        res = modes.classify_raw(raw, fr, mc)
        if warns is not None:
            warns += [f"deform_mode: {w}" for w in res["warnings"]]
        dm = modes.record(res)
    except EslError as exc:
        if warns is not None:
            warns.append(f"deform_mode: 분류 실패 {exc.message}")
        dm = {"auto": None, "metrics": {}, "user": None, "user_by": None, "user_at": None,
              "rule_version": int(mc["rule_version"])}
    return topo, dm


def save(entry: LibraryEntry, d: str, writer: U.Writer | None = None) -> str:
    """항목 폴더에 entry.json, summary.npz, raw.npz 를 쓴다(폴더가 이미 있으면 ENTRY_EXISTS — 수정 불가)."""
    if os.path.exists(d):
        raise EslError("ENTRY_EXISTS", f"항목 폴더가 이미 있음: {d} (항목은 수정 불가 — 정정은 새 등록 + retire)")
    if writer is not None:
        writer.makedirs(d)
        g = writer.guard
    else:
        os.makedirs(d)
        g = lambda p: p   # noqa: E731
    np.savez_compressed(g(os.path.join(d, "summary.npz")), **{k: np.asarray(v) for k, v in entry.summary.items()})
    np.savez_compressed(g(os.path.join(d, "raw.npz")), **{k: np.asarray(entry.raw[k]) for k in RAW_KEYS})
    meta = dict(entry.meta)
    meta["files"] = {n: {"sha256": U.sha256_file(os.path.join(d, n))} for n in ("summary.npz", "raw.npz")}
    U.write_json(g(os.path.join(d, "entry.json")), meta)
    entry.meta = meta
    return d


def load(d: str, raw: bool = True, verify: bool = False) -> LibraryEntry:
    meta = U.read_json(_req(os.path.join(d, "entry.json")))
    if verify:
        for n, rec in (meta.get("files") or {}).items():
            if U.sha256_file(os.path.join(d, n)) != rec.get("sha256"):
                raise EslError("ENTRY_CORRUPT", f"{d}/{n} sha256 불일치")
    summary = U.load_npz(_req(os.path.join(d, "summary.npz")))
    r = U.load_npz(_req(os.path.join(d, "raw.npz"))) if raw else None
    return LibraryEntry(meta=meta, summary=summary, raw=r)
