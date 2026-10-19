"""ESL 파이프라인: extract → tstar → esl → validate → export (계약 esl_core.md §5).

- 각 단계는 앞 단계의 **디스크 산출물만** 읽는다 → ``stage`` 하나만 다시 돌려 재개 가능.
- 입력(rad·결과 CSV 폴더)에는 쓰지 않는다. 출력 폴더가 입력 폴더와 겹치면 ``INPUT_INVALID``.
  겹침은 ``os.path.realpath`` 기준(심볼릭 링크·``..`` 우회 차단). 보호 대상 = rad 폴더, rad 가 실제로 읽은
  include 파일의 폴더, 결과 CSV 폴더. 모든 쓰기(백업 이동 포함) 직전에 대상 realpath 가 출력 루트
  realpath 안이고 보호 대상 밖인지 다시 확인한다.
- S4 는 변위 저장 정밀도(``extract.disp_precision``)의 잡음 바닥을 추정해 ``esl_summary.json`` 의
  ``noise`` 에 기록한다(검증 기준 초과 시 S5 verdict FAIL, 사유 ``NOISE_FLOOR``).
- 단계 산출물 폴더에 기존 파일이 있으면 ``_backup/<UTC timestamp>/<폴더>`` 로 **이동**한 뒤 새로 쓴다
  (삭제하지 않음). ``run.json`` 도 덮어쓰기 전에 같은 곳으로 이동.
- 판정 기준·허용오차·오프셋·파트 title 은 설정(``esl.config``)에서만 읽는다.

출력 폴더::

  01_extract/  model.npz, model_meta.json, strain_tensor.npz, disp.npz, frames.json
  02_tstar/    tstar.json, history.csv, hotspots.csv, candidates.csv
  03_bc/       support.json
  04_esl/      u_rel.npz, u_rel.csv, f_eq.npz, f_eq.csv, esl_summary.json
  05_val/      validation.json, validation.csv, compare.csv
  06_export/   esl_cload.inc, esl_bcs.inc, esl_force.fem, f_eq.csv, u_rel.csv, reactions_321.csv,
               tstar_candidates.csv, hotspots.csv, validation.csv
  run.json
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

import esl
from esl import config as _config
from esl.errors import EslError
from esl.export import all_ids, dof_flags, force_mask, plan_ids
from esl.export import csvout, optistruct, radioss
from esl.io import pack_results
from esl.mech import kabsch, strain, supports, tstar
from esl.mech.shell import ShellModel
from esl.rad import parse_rad

STAGES = ("extract", "tstar", "esl", "validate", "export")
D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT = (
    "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export")
BACKUP_DIR = "_backup"
RUN_JSON = "run.json"
RESULT_FILES = ("frames.csv", "model.csv", "strain.csv", "disp.csv", "done.json")
_HASH_CHUNK = 4 * 1024 * 1024


# ====================================================================== 공통 도구
def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: str) -> str:
    """청크 단위 sha256 (대용량 파일도 전체를 메모리에 올리지 않음)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(_HASH_CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _fingerprint(path: str, with_hash: bool) -> dict:
    st = os.stat(path)
    d = {"path": path, "size": int(st.st_size), "mtime": float(st.st_mtime)}
    if with_hash:
        d["sha256"] = sha256_file(path)
    return d


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if np.isfinite(v) else str(v)
    if isinstance(o, float) and not np.isfinite(o):
        return str(o)
    return o


def _write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(_jsonable(obj), fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_npz(path: str) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _is_within(child: str, parent: str) -> bool:
    child, parent = os.path.normcase(child), os.path.normcase(parent)
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:      # 다른 드라이브
        return False


def real_path(path: str) -> str:
    """심볼릭 링크를 푼 실제 경로. 존재하지 않는 경로는 존재하는 가장 가까운 조상의 realpath + 나머지."""
    p = os.path.abspath(os.fspath(path))
    rest: list[str] = []
    cur = p
    while not os.path.lexists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        rest.append(os.path.basename(cur))
        cur = parent
    r = os.path.realpath(cur)
    for part in reversed(rest):
        r = os.path.join(r, part)
    return os.path.normpath(r)


def protected_dirs(rad: str, results: str, includes=()) -> list[tuple[str, str]]:
    """(이름, realpath) 보호 폴더 목록: rad 폴더, include 파일 폴더, 결과 CSV 폴더 (링크 전·후 모두)."""
    out: list[tuple[str, str]] = []

    def add(name, d):
        r = real_path(d)
        if all(r != x for _, x in out):
            out.append((name, r))

    add("결과 CSV 폴더", results)
    for name, f in [("rad 폴더", rad)] + [("include 폴더", p) for p in includes]:
        f = os.path.abspath(os.fspath(f))
        add(name, os.path.dirname(f))
        add(name, os.path.dirname(real_path(f)))
    return out


def check_overlap(out: str, prot: list[tuple[str, str]]) -> str:
    """출력 폴더 realpath 가 보호 폴더 안이거나 보호 폴더를 포함하면 INPUT_INVALID. 출력 realpath 반환."""
    ro = real_path(out)
    for name, p in prot:
        if _is_within(ro, p) or _is_within(p, ro):
            raise EslError("INPUT_INVALID", f"출력 폴더 {out} (실제 경로 {ro}) 가 입력({name} {p})과 겹침 "
                                            f"— 입력 폴더에는 쓰지 않음")
    return ro


# ====================================================================== 모델(디스크)
@dataclass
class StoredModel:
    node_id: np.ndarray
    x0: np.ndarray
    elem_id: np.ndarray
    elem_type: np.ndarray
    conn: np.ndarray
    elem_pid: np.ndarray
    elem_mid: np.ndarray
    thickness: np.ndarray
    E: np.ndarray
    nu: np.ndarray
    part_id: int
    part_title: str
    units_label: str
    mats: list = field(default_factory=list)
    max_ids: dict = field(default_factory=dict)
    includes: list = field(default_factory=list)

    def shell(self, drill_factor: float) -> ShellModel:
        return ShellModel(self.x0, self.conn, self.elem_type, self.thickness, self.E, self.nu,
                          drill_factor=drill_factor)

    def centroids(self) -> np.ndarray:
        q = self.elem_type == 4
        c = np.empty((self.conn.shape[0], 3))
        c[q] = self.x0[self.conn[q]].mean(axis=1)
        c[~q] = self.x0[self.conn[~q, :3]].mean(axis=1)
        return c


def save_model(d: str, m) -> None:
    mid = int(m.mats[0]["id"]) if m.mats else -1
    np.savez_compressed(
        os.path.join(d, "model.npz"),
        node_id=np.asarray(m.node_id, np.int64), x0=np.asarray(m.x0, np.float64),
        elem_id=np.asarray(m.elem_id, np.int64), elem_type=np.asarray(m.elem_type, np.int8),
        conn=np.asarray(m.conn, np.int64), elem_pid=np.asarray(m.elem_pid, np.int64),
        elem_mid=np.full(np.asarray(m.elem_id).size, mid, np.int64),
        thickness=np.asarray(m.thickness, np.float64), E=np.asarray(m.E, np.float64),
        nu=np.asarray(m.nu, np.float64))
    pids, cnt = np.unique(np.asarray(m.elem_pid), return_counts=True)
    meta = {
        "schema": "esl/model/1", "part_id": int(m.part_id), "part_title": m.part_title,
        "units_label": m.units_label, "n_nodes": int(np.asarray(m.node_id).size),
        "n_elems": int(np.asarray(m.elem_id).size),
        "n_quad": int(np.sum(np.asarray(m.elem_type) == 4)), "n_tria": int(np.sum(np.asarray(m.elem_type) == 3)),
        "mats": m.mats, "props": [{"id": int(p), "n_elems": int(c)} for p, c in zip(pids, cnt)],
        "thickness_range": [float(np.min(m.thickness)), float(np.max(m.thickness))],
        "max_ids": m.max_ids, "includes": list(m.includes), "warnings": list(getattr(m, "warnings", [])),
        "created_at": _utcnow(),
    }
    _write_json(os.path.join(d, "model_meta.json"), meta)


def load_model(out: str) -> StoredModel:
    d = os.path.join(out, D_EXTRACT)
    _require(out, [f"{D_EXTRACT}/model.npz", f"{D_EXTRACT}/model_meta.json"])
    z = _load_npz(os.path.join(d, "model.npz"))
    meta = _read_json(os.path.join(d, "model_meta.json"))
    return StoredModel(
        node_id=z["node_id"], x0=z["x0"], elem_id=z["elem_id"], elem_type=z["elem_type"].astype(np.int8),
        conn=z["conn"], elem_pid=z["elem_pid"], elem_mid=z["elem_mid"], thickness=z["thickness"],
        E=z["E"], nu=z["nu"], part_id=int(meta["part_id"]), part_title=meta["part_title"],
        units_label=meta.get("units_label", ""), mats=meta["mats"], max_ids=meta["max_ids"],
        includes=meta.get("includes", []))


def _require(out: str, rels: list[str]) -> None:
    miss = [r for r in rels if not os.path.isfile(os.path.join(out, r))]
    if miss:
        raise EslError("PREREQUISITE_MISSING", f"앞 단계 산출물이 없음: {miss} (해당 단계를 먼저 실행)")


# ====================================================================== 실행 문맥
@dataclass
class Context:
    cfg: dict
    config_path: str
    rad: str
    results: str
    out: str
    ts: str
    frame: int | None
    support_nodes: list[int] | None
    echo: Callable[[str], None]
    record: dict
    warnings: list = field(default_factory=list)
    protected: list = field(default_factory=list)
    out_real: str = ""

    def p(self, *parts) -> str:
        return os.path.join(self.out, *parts)

    def guard(self, path: str) -> str:
        """쓰기 직전 검사: realpath 가 출력 루트 realpath 안이고 보호(입력) 폴더 밖이어야 함."""
        r = real_path(path)
        if not self.out_real or not _is_within(r, self.out_real):
            raise EslError("INPUT_INVALID", f"쓰기 대상 {path} 의 실제 경로 {r} 가 출력 폴더 {self.out_real} 밖 "
                                            f"(심볼릭 링크 의심) — 쓰지 않음")
        for name, p in self.protected:
            if _is_within(r, p):
                raise EslError("INPUT_INVALID", f"쓰기 대상 {path} 의 실제 경로 {r} 가 입력({name} {p}) 안 — 쓰지 않음")
        return path

    def f(self, d: str, name: str) -> str:
        """단계 폴더 d 안 파일 경로(쓰기 전 guard)."""
        return self.guard(os.path.join(d, name))

    def protect(self, includes) -> None:
        """rad 가 실제로 읽은 include 폴더를 보호 대상에 추가하고 출력 겹침을 다시 검사."""
        self.protected = protected_dirs(self.rad, self.results, includes)
        self.out_real = check_overlap(self.out, self.protected)

    def fresh_dir(self, sub: str) -> str:
        """단계 폴더 준비: 기존 내용이 있으면 _backup/<ts>/<sub> 로 이동 후 빈 폴더."""
        d = self.guard(self.p(sub))
        if os.path.isdir(d) and os.listdir(d):
            dst = self._backup_target(sub)
            os.replace(d, dst)
        os.makedirs(d, exist_ok=True)
        return self.guard(d)

    def backup_file(self, name: str) -> None:
        src = self.guard(self.p(name))
        if os.path.exists(src):
            os.replace(src, self._backup_target(name))

    def _backup_target(self, name: str) -> str:
        root = self.guard(self.p(BACKUP_DIR, self.ts))
        os.makedirs(root, exist_ok=True)
        self.guard(root)
        dst = os.path.join(root, name)
        k = 1
        while os.path.lexists(dst):
            dst = os.path.join(root, f"{name}.{k}")
            k += 1
        return self.guard(dst)

    def csvfmt(self) -> csvout.CsvFormat:
        c = self.cfg["export"]["csv"]
        return csvout.CsvFormat(c["delimiter"], c["float_format"])


def _eq_by_layer(eps, mode: str) -> np.ndarray:
    """eps (..., 2, 3) → ε_eq (...) — 설정 extract.shell_layer."""
    if mode == "max":
        return strain.eps_eq_max_layer(eps)
    if mode == "bottom":
        return strain.eps_eq(eps[..., 0, :])
    if mode == "top":
        return strain.eps_eq(eps[..., 1, :])
    raise EslError("CONFIG_INVALID", f"extract.shell_layer: {mode}")


def _exclude_mask(ctx: Context, elem_id) -> np.ndarray | None:
    ids = ctx.cfg["tstar"]["exclude_elem_ids"]
    if not ids:
        return None
    ids = np.asarray(ids, dtype=np.int64)
    known = np.isin(ids, elem_id)
    if not known.all():
        ctx.warnings.append(f"tstar.exclude_elem_ids 중 대상 파트에 없는 요소 무시: {ids[~known][:10].tolist()}")
    return np.isin(elem_id, ids)


def _ids_to_idx(sorted_ids: np.ndarray, ids, what: str) -> np.ndarray:
    ids = np.asarray(ids, dtype=np.int64)
    pos = np.searchsorted(sorted_ids, ids)
    pc = np.minimum(pos, sorted_ids.size - 1)
    ok = sorted_ids[pc] == ids
    if not ok.all():
        raise EslError("NODE_NOT_IN_PART", f"{what}: 대상 파트에 없는 노드 ID {ids[~ok].tolist()}")
    return pc


def _check_inputs_unchanged(ctx: Context) -> None:
    inp = ctx.record.get("inputs") or {}
    olds = []
    if inp.get("rad"):
        olds.append(inp["rad"])
    olds += list((inp.get("results_files") or {}).values())
    for fp in olds:
        p = fp.get("path")
        if not p or not os.path.isfile(p):
            ctx.warnings.append(f"입력 파일이 없어짐(추출 이후): {p}")
            continue
        st = os.stat(p)
        if int(st.st_size) != fp.get("size") or float(st.st_mtime) != fp.get("mtime"):
            ctx.warnings.append(f"입력 파일이 추출 이후 바뀜(size/mtime): {p} — extract 부터 다시 실행 권장")


# ====================================================================== S1 extract
def stage_extract(ctx: Context) -> dict:
    c = ctx.cfg["case"]
    if not os.path.isfile(ctx.rad):
        raise EslError("INPUT_INVALID", f"rad 파일이 없음: {ctx.rad}")
    if not os.path.isdir(ctx.results):
        raise EslError("INPUT_INVALID", f"결과 CSV 폴더가 없음: {ctx.results}")
    model = parse_rad(ctx.rad, c["part_title"], match=c["part_title_match"],
                      max_include_depth=c["rad_include_max_depth"],
                      material_override=c["material_override"] or None,
                      include_path_map=c["include_path_map"] or None)
    ctx.protect(list(model.includes))          # include 폴더도 보호 → 겹치면 쓰기 전에 INPUT_INVALID
    d = ctx.fresh_dir(D_EXTRACT)
    for fn in ("model.npz", "model_meta.json", "strain_tensor.npz", "disp.npz", "frames.json"):
        ctx.f(d, fn)
    save_model(d, model)
    info = pack_results(ctx.results, model, d, frame_stride=ctx.cfg["extract"]["frame_stride"])
    ctx.warnings += list(getattr(model, "warnings", [])) + list(info.get("warnings", []))

    # 입력 지문(sha256 청크 해시)
    inputs = {"rad": _fingerprint(ctx.rad, True),
              "includes": [_fingerprint(p, True) for p in model.includes if os.path.isfile(p)],
              "results_dir": ctx.results, "results_files": {}}
    for name in RESULT_FILES:
        p = os.path.join(ctx.results, name)
        if os.path.isfile(p):
            inputs["results_files"][name] = _fingerprint(p, True)
    ctx.record["inputs"] = inputs
    et = np.asarray(model.elem_type)
    s = {"part_id": model.part_id, "part_title": model.part_title, "units_label": model.units_label,
         "n_nodes": int(model.node_id.size), "n_elems": int(model.elem_id.size),
         "n_quad": int(np.sum(et == 4)), "n_tria": int(np.sum(et == 3)), "n_frames": info["n_frames"],
         "mats": model.mats, "max_ids": model.max_ids}
    ctx.echo(f"[extract] 파트 {model.part_id} '{model.part_title}': 노드 {s['n_nodes']}, 요소 {s['n_elems']} "
             f"(QUAD {s['n_quad']}/TRIA {s['n_tria']}), 프레임 {s['n_frames']}")
    return s


# ====================================================================== S2 tstar
def _select_frame(tj: dict, frame: int | None) -> dict:
    if frame is None:
        return dict(tj["selected"])
    for cnd in tj["candidates"]:
        if int(cnd["frame_index"]) == int(frame):
            return {"frame_index": int(cnd["frame_index"]), "time": cnd["time"], "elem_id": cnd["elem_id"],
                    "eps_eq": cnd["eps_max"], "source": "user"}
    raise EslError("FRAME_NOT_CANDIDATE",
                   f"frame {frame} 은 후보 시점이 아님 (후보 frame_index: {[c['frame_index'] for c in tj['candidates']]})")


def stage_tstar(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_EXTRACT}/strain_tensor.npz"])
    model = load_model(ctx.out)
    st = _load_npz(ctx.p(D_EXTRACT, "strain_tensor.npz"))
    if not np.array_equal(st["elem_id"], model.elem_id):
        raise EslError("ID_MISMATCH", "strain_tensor.npz elem_id 가 model.npz 와 다름")
    tcfg = ctx.cfg["tstar"]
    mode = ctx.cfg["extract"]["shell_layer"]
    eq = _eq_by_layer(st["eps"], mode)                    # (F,E)
    C = model.centroids()
    tw = tcfg["time_window"]
    res = tstar.scan(st["time"], eq, C, tcfg["top_n_times"], tcfg["top_k_hotspots"], tcfg["hotspot_min_dist"],
                     time_window=(tw[0], tw[1]), exclude_mask=_exclude_mask(ctx, model.elem_id))
    fidx = st["frame_index"]
    eid = model.elem_id
    ts = res["tstar"]
    auto = {"frame_index": int(fidx[ts["frame_pos"]]), "time": ts["time"], "elem_id": int(eid[ts["elem_pos"]]),
            "eps_eq": ts["eps_eq"], "source": "auto"}
    cands = [{"rank": c["rank"], "frame_index": int(fidx[c["frame_pos"]]), "time": c["time"],
              "eps_max": c["eps_max"], "elem_id": int(eid[c["elem_pos"]])} for c in res["candidates"]]
    hots = [{"rank": h["rank"], "elem_id": int(eid[h["elem_pos"]]), "eps_eq": h["eps_eq"],
             "centroid": h["centroid"]} for h in res["hotspots"]]
    tj = {"schema": "esl/tstar/1", "shell_layer": mode, "auto": auto, "candidates": cands, "hotspots": hots,
          "settings": dict(tcfg), "created_at": _utcnow()}
    tj["selected"] = _select_frame({"selected": auto, "candidates": cands}, ctx.frame)

    d = ctx.fresh_dir(D_TSTAR)
    _write_json(ctx.f(d, "tstar.json"), tj)
    fmt = ctx.csvfmt()
    h = res["history"]
    csvout.write_csv(ctx.f(d, "history.csv"), csvout.HISTORY_HEADER,
                     zip(h["time"], h["eps_max"], h["eps_hotspot1"]), fmt)
    csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER,
                     ((x["rank"], x["elem_id"], x["eps_eq"], *x["centroid"]) for x in hots), fmt)
    csvout.write_csv(ctx.f(d, "candidates.csv"), csvout.CANDIDATES_HEADER,
                     ((x["rank"], x["frame_index"], x["time"], x["eps_max"], x["elem_id"]) for x in cands), fmt)
    sel = tj["selected"]
    ctx.echo(f"[tstar] t* = frame {sel['frame_index']} (time {sel['time']:.6g}, {sel['source']}), "
             f"ε_eq max {sel['eps_eq']:.4g} @ elem {sel['elem_id']}, 후보 {len(cands)}개, hotspot {len(hots)}개")
    return {"selected": sel, "auto": auto, "n_candidates": len(cands), "n_hotspots": len(hots)}


# ====================================================================== 평가 hotspot·잡음 바닥
NOISE_SEED = 20240917          # 잡음 섭동 고정 시드(재현성)
_PRECISION = {"float32": np.float32, "float64": np.float64}


def _eval_hotspots(ctx: Context, model: StoredModel, st: dict, frame_index: int, time: float):
    """t* 프레임 Radioss ε_eq 기준 평가 hotspot(상위 validation.hotspot_eval_count) 과 ε_rad (E,)."""
    hit = np.flatnonzero(st["frame_index"] == int(frame_index))
    if hit.size != 1:
        raise EslError("FRAME_NOT_CANDIDATE", f"strain_tensor.npz 에 frame {frame_index} 이 없음")
    mode = ctx.cfg["extract"]["shell_layer"]
    eps_rad = _eq_by_layer(st["eps"][int(hit[0])], mode)            # (E,)
    hs = tstar.scan(np.array([float(time)]), eps_rad[None, :], model.centroids(), 1,
                    ctx.cfg["validation"]["hotspot_eval_count"], ctx.cfg["tstar"]["hotspot_min_dist"],
                    exclude_mask=_exclude_mask(ctx, model.elem_id))["hotspots"]
    return hs, eps_rad


def _with_rot(sm: ShellModel, u_t: np.ndarray) -> np.ndarray:
    """병진 u_t (N,3) + condensation 회전 → (N,6)."""
    return np.hstack([u_t, sm.rotations_for(u_t)])


def noise_floor(ctx: Context, sm: ShellModel, X0, u_total, u_rel, F, hot_pos) -> dict:
    """변위 저장 정밀도의 잡음 바닥.

    δ = 0.5·ulp(precision)·max|X0+u| (= eps_mach/2·max|x|; float32 → 2^-24·max|x|).
    고정 시드 균일 ±δ 섭동 n 개 → F_noise = condensed_forces(noise), ε(u_rel+noise) (회전은 condensation).
    force_rel = max_s rms(F_noise)/rms(F_eq), hotspot_strain_rel = max_s max_h |ε_eq(u_rel+n)−ε_eq(u_rel)|/ε_eq(u_rel).
    """
    prec = ctx.cfg["extract"]["disp_precision"]
    vcfg = ctx.cfg["validation"]
    n_s = int(vcfg["noise_samples"])
    mode = ctx.cfg["extract"]["shell_layer"]
    xmax = float(np.max(np.abs(np.asarray(X0) + np.asarray(u_total)))) if np.size(X0) else 0.0
    delta = 0.5 * float(np.finfo(_PRECISION[prec]).eps) * xmax
    rms = lambda a: float(np.sqrt(np.mean(np.sum(np.asarray(a) ** 2, axis=1)))) if np.size(a) else 0.0
    rms_f = rms(F)
    hot_pos = np.asarray(hot_pos, dtype=np.int64)
    eps_rel = sm.strains(_with_rot(sm, u_rel))
    eq0 = _eq_by_layer(eps_rel, mode)[hot_pos]
    rng = np.random.default_rng(NOISE_SEED)
    f_rel, s_rel = [], []
    for _ in range(n_s):
        n = rng.uniform(-delta, delta, size=np.shape(u_rel))
        fn = sm.condensed_forces(n)
        f_rel.append(rms(fn) / rms_f if rms_f > 0 else float("inf"))
        if hot_pos.size:
            eq1 = _eq_by_layer(eps_rel + sm.strains(_with_rot(sm, n)), mode)[hot_pos]
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(eq0 > 0, np.abs(eq1 - eq0) / np.where(eq0 > 0, eq0, 1.0), np.inf)
            s_rel.append(float(np.max(r)))
    return {"disp_precision": prec, "delta": delta, "x_abs_max": xmax, "n_samples": n_s, "seed": NOISE_SEED,
            "force_rel": float(max(f_rel)) if f_rel else 0.0,
            "hotspot_strain_rel": float(max(s_rel)) if s_rel else 0.0,
            "force_rel_samples": f_rel, "hotspot_strain_rel_samples": s_rel,
            "hotspot_elem_pos": hot_pos.tolist(),
            "criteria": {"noise_force_rel_warn": vcfg["noise_force_rel_warn"],
                         "noise_strain_rel_max": vcfg["noise_strain_rel_max"]}}


# ====================================================================== S3+S4 esl
def _support_candidates(ctx: Context, model: StoredModel):
    if ctx.support_nodes:
        return "cli", _ids_to_idx(model.node_id, ctx.support_nodes, "--support-nodes"), None
    scfg = ctx.cfg["support"]
    if scfg["candidates"] == "node_ids":
        return "config", _ids_to_idx(model.node_id, scfg["node_ids"], "support.node_ids"), None
    pc = supports.pca_corners(model.x0)
    return "pca4", np.asarray(pc["idx"], dtype=np.int64), pc["plane"]


def stage_esl(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_EXTRACT}/disp.npz", f"{D_EXTRACT}/strain_tensor.npz", f"{D_TSTAR}/tstar.json"])
    _check_inputs_unchanged(ctx)
    model = load_model(ctx.out)
    tj = _read_json(ctx.p(D_TSTAR, "tstar.json"))
    sel = _select_frame(tj, ctx.frame)
    dz = _load_npz(ctx.p(D_EXTRACT, "disp.npz"))
    if not np.array_equal(dz["node_id"], model.node_id):
        raise EslError("ID_MISMATCH", "disp.npz node_id 가 model.npz 와 다름")
    hit = np.flatnonzero(dz["frame_index"] == int(sel["frame_index"]))
    if hit.size != 1:
        raise EslError("FRAME_NOT_CANDIDATE", f"disp.npz 에 frame {sel['frame_index']} 이 없음")
    fpos = int(hit[0])
    X0 = model.x0
    nid = model.node_id

    # ---- 3-2-1 지지
    mode, cand_idx, plane = _support_candidates(ctx, model)
    sup = supports.pick_321(X0, cand_idx)
    sup_rec = {"schema": "esl/support/1", "mode": mode,
               "candidates": [{"node_id": int(nid[i]), "x0": X0[i].tolist()} for i in cand_idx],
               "plane": plane,
               "supports": [{"node_id": int(nid[i]), "dof": d, "flags": dof_flags(d), "x0": X0[i].tolist()}
                            for i, d in sup],
               "created_at": _utcnow()}

    # ---- S3 강체 제거, S4 F_eq
    u = dz["u"][fpos]
    u_rel, R, t, kinfo = kabsch.remove_rigid(X0, u)
    sm = model.shell(ctx.cfg["solver"]["drill_factor"])
    F = sm.condensed_forces(u_rel)
    mag = np.linalg.norm(F, axis=1)
    sum_abs = float(mag.sum())
    sumF = F.sum(axis=0)
    ctr = X0.mean(axis=0)
    M = np.cross(X0 - ctr, F).sum(axis=0)
    Lb = float(np.linalg.norm(X0.max(axis=0) - X0.min(axis=0)))
    eq_rel = float(np.linalg.norm(sumF) / sum_abs) if sum_abs > 0 else 0.0
    mom_rel = float(np.linalg.norm(M) / (sum_abs * Lb)) if sum_abs > 0 and Lb > 0 else 0.0
    warn = ctx.cfg["solver"]["equilibrium_warn_rel"]
    if eq_rel > warn:
        ctx.warnings.append(f"F_eq 힘 평형 오차 {eq_rel:.3e} > {warn:g}")
    if mom_rel > warn:
        ctx.warnings.append(f"F_eq 모멘트 평형 오차 {mom_rel:.3e} > {warn:g}")
    if sum_abs == 0.0:
        ctx.warnings.append("F_eq 가 전부 0 (변형 없음)")
    is_bc = np.zeros(nid.size, dtype=bool)
    is_bc[[i for i, _ in sup]] = True

    # ---- 변위 정밀도 잡음 바닥
    hs, _ = _eval_hotspots(ctx, model, _load_npz(ctx.p(D_EXTRACT, "strain_tensor.npz")),
                           int(sel["frame_index"]), float(sel["time"]))
    noise = noise_floor(ctx, sm, X0, u, u_rel, F, [h["elem_pos"] for h in hs])
    noise["hotspot_elem_id"] = [int(model.elem_id[e]) for e in noise.pop("hotspot_elem_pos")]
    vcfg = ctx.cfg["validation"]
    if noise["force_rel"] > vcfg["noise_force_rel_warn"]:
        ctx.warnings.append(f"변위 정밀도({noise['disp_precision']}) 잡음 바닥: rms(F_noise)/rms(F_eq) = "
                            f"{noise['force_rel']:.3e} > {vcfg['noise_force_rel_warn']:g} — F_eq 가 잡음에 민감")
    if noise["hotspot_strain_rel"] > vcfg["noise_strain_rel_max"]:
        ctx.warnings.append(f"변위 정밀도({noise['disp_precision']}) 잡음 바닥: hotspot ε_eq 상대 변화 "
                            f"{noise['hotspot_strain_rel']:.3e} > {vcfg['noise_strain_rel_max']:g} "
                            f"→ 검증 FAIL(NOISE_FLOOR)")

    dbc = ctx.fresh_dir(D_BC)
    _write_json(ctx.f(dbc, "support.json"), sup_rec)
    d = ctx.fresh_dir(D_ESL)
    np.savez_compressed(ctx.f(d, "u_rel.npz"), node_id=nid, u_rel=u_rel, u_total=u, R=R, t=t,
                        time=np.float64(sel["time"]), frame_index=np.int64(sel["frame_index"]))
    np.savez_compressed(ctx.f(d, "f_eq.npz"), node_id=nid, f=F, is_bc=is_bc)
    fmt = ctx.csvfmt()
    csvout.write_csv(ctx.f(d, "u_rel.csv"), csvout.U_REL_HEADER,
                     ((int(nid[i]), *u_rel[i], *u[i]) for i in range(nid.size)), fmt)
    csvout.write_csv(ctx.f(d, "f_eq.csv"), csvout.F_EQ_HEADER, csvout.f_eq_rows(nid, X0, F, is_bc), fmt)
    imax = int(np.argmax(mag)) if mag.size else 0
    summ = {"frame": sel, "kabsch": {"R": R, "t": t, **kinfo},
            "forces": {"sum_f": sumF, "sum_f_norm": float(np.linalg.norm(sumF)), "sum_abs_f": sum_abs,
                       "equilibrium_rel": eq_rel, "moment_rel": mom_rel, "moment_center": ctr, "L_bbox": Lb,
                       "max_f": {"node_id": int(nid[imax]), "mag": float(mag[imax])},
                       "n_nodes_nonzero": int(np.sum(mag > 0))},
            "supports": sup_rec["supports"], "support_mode": mode, "noise": noise,
            "drill_factor": ctx.cfg["solver"]["drill_factor"], "created_at": _utcnow()}
    _write_json(ctx.f(d, "esl_summary.json"), summ)
    ctx.echo(f"[esl] frame {sel['frame_index']}: 강체회전 {kinfo['rot_deg']:.2f}°, ΣF=|{np.linalg.norm(sumF):.3e}|, "
             f"Σ|F|={sum_abs:.3e}, 평형 오차 {eq_rel:.2e} (모멘트 {mom_rel:.2e}), "
             f"3-2-1 {[(int(nid[i]), dd) for i, dd in sup]} ({mode})")
    ctx.echo(f"[esl] 잡음 바닥({noise['disp_precision']}, δ={noise['delta']:.3e}, n={noise['n_samples']}): "
             f"force_rel={noise['force_rel']:.3e} (경고 >{vcfg['noise_force_rel_warn']:g}), "
             f"hotspot_strain_rel={noise['hotspot_strain_rel']:.3e} (≤{vcfg['noise_strain_rel_max']:g})")
    noise_short = {k: noise[k] for k in ("disp_precision", "delta", "n_samples", "force_rel", "hotspot_strain_rel")}
    return {"noise": noise_short, "frame": sel, "rot_deg": kinfo["rot_deg"], "rms_def": kinfo["rms_def"], "max_def": kinfo["max_def"],
            "sum_f_norm": float(np.linalg.norm(sumF)), "sum_abs_f": sum_abs, "equilibrium_rel": eq_rel,
            "moment_rel": mom_rel, "supports": sup_rec["supports"], "support_mode": mode}


# ====================================================================== S5 validate
_FAIL_REASON = {"disp_rms_rel": "DISP_RMS", "hotspot1_strain_rel_err": "HOTSPOT_STRAIN",
                "reaction_rel": "REACTION", "noise_hotspot_strain_rel": "NOISE_FLOOR"}


def stage_validate(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_EXTRACT}/strain_tensor.npz", f"{D_BC}/support.json", f"{D_ESL}/u_rel.npz",
                       f"{D_ESL}/f_eq.npz", f"{D_ESL}/esl_summary.json"])
    model = load_model(ctx.out)
    nid, X0 = model.node_id, model.x0
    ur = _load_npz(ctx.p(D_ESL, "u_rel.npz"))
    fz = _load_npz(ctx.p(D_ESL, "f_eq.npz"))
    sup = _read_json(ctx.p(D_BC, "support.json"))["supports"]
    summ = _read_json(ctx.p(D_ESL, "esl_summary.json"))
    if not (np.array_equal(ur["node_id"], nid) and np.array_equal(fz["node_id"], nid)):
        raise EslError("ID_MISMATCH", "04_esl 산출물의 node_id 가 model.npz 와 다름")
    u_rel, F = ur["u_rel"], fz["f"]
    spc = [(int(i), s["dof"]) for i, s in zip(_ids_to_idx(nid, [s["node_id"] for s in sup], "support.json"), sup)]

    sm = model.shell(ctx.cfg["solver"]["drill_factor"])
    u_val, Rr = sm.solve(F, spc)
    # 미소 강체 제거 후 비교(양쪽 모두 같은 사영 → 선형 왕복의 수치 일관성)
    d_val, _, _ = kabsch.remove_linear_rigid(X0, u_val[:, :3])
    d_rel, a_rel, w_rel = kabsch.remove_linear_rigid(X0, u_rel)
    delta = d_val - d_rel
    umax = float(np.max(np.linalg.norm(u_rel, axis=1)))
    dn = np.linalg.norm(delta, axis=1)
    disp_rms_rel = float(np.sqrt(np.mean(dn ** 2)) / umax) if umax > 0 else float("inf")
    disp_max_rel = float(dn.max() / umax) if umax > 0 else float("inf")
    sum_abs = float(np.linalg.norm(F, axis=1).sum())
    reac_abs_rel = float(np.linalg.norm(Rr, axis=1).sum() / sum_abs) if sum_abs > 0 else 0.0
    reac_sum_rel = float(np.linalg.norm(Rr.sum(axis=0)) / sum_abs) if sum_abs > 0 else 0.0
    lin_rigid_rel = float(np.max(np.linalg.norm(u_rel - d_rel, axis=1)) / umax) if umax > 0 else 0.0

    # hotspot ε_eq: Radioss(t* 프레임) vs 검증 해
    st = _load_npz(ctx.p(D_EXTRACT, "strain_tensor.npz"))
    mode = ctx.cfg["extract"]["shell_layer"]
    hs, eps_rad = _eval_hotspots(ctx, model, st, int(summ["frame"]["frame_index"]), float(summ["frame"]["time"]))
    eps_val = _eq_by_layer(sm.strains(u_val), mode)
    vcfg = ctx.cfg["validation"]
    hots = []
    for h in hs:
        e = h["elem_pos"]
        er, ev = float(eps_rad[e]), float(eps_val[e])
        hots.append({"rank": h["rank"], "elem_id": int(model.elem_id[e]), "eps_rad": er, "eps_val": ev,
                     "rel_err": abs(ev - er) / er if er > 0 else float("inf"), "centroid": h["centroid"]})
    h1 = hots[0]["rel_err"] if hots else float("inf")

    noise = summ.get("noise")
    if noise is None:
        ctx.warnings.append("esl_summary.json 에 잡음 바닥(noise) 없음 — esl 단계를 다시 실행 권장")
    n_strain = float(noise["hotspot_strain_rel"]) if noise else None
    n_force = float(noise["force_rel"]) if noise else None
    crit = {"disp_rms_rel_max": vcfg["disp_rms_rel_max"],
            "hotspot_strain_rel_err_max": vcfg["hotspot_strain_rel_err_max"],
            "reaction_rel_max": vcfg["reaction_rel_max"], "hotspot_eval_count": vcfg["hotspot_eval_count"],
            "noise_strain_rel_max": vcfg["noise_strain_rel_max"],
            "noise_force_rel_warn": vcfg["noise_force_rel_warn"],
            "disp_precision": noise["disp_precision"] if noise else None, "shell_layer": mode}
    metrics = [
        {"metric": "disp_rms_rel", "value": disp_rms_rel, "criterion": crit["disp_rms_rel_max"],
         "pass": bool(disp_rms_rel <= crit["disp_rms_rel_max"])},
        {"metric": "hotspot1_strain_rel_err", "value": h1, "criterion": crit["hotspot_strain_rel_err_max"],
         "pass": bool(h1 <= crit["hotspot_strain_rel_err_max"])},
        {"metric": "reaction_rel", "value": reac_abs_rel, "criterion": crit["reaction_rel_max"],
         "pass": bool(reac_abs_rel <= crit["reaction_rel_max"])},
        {"metric": "disp_max_rel", "value": disp_max_rel, "criterion": None, "pass": None},
        {"metric": "reaction_sum_rel", "value": reac_sum_rel, "criterion": None, "pass": None},
        {"metric": "u_rel_linear_rigid_rel", "value": lin_rigid_rel, "criterion": None, "pass": None},
        {"metric": "noise_hotspot_strain_rel", "value": n_strain, "criterion": crit["noise_strain_rel_max"],
         "pass": None if n_strain is None else bool(n_strain <= crit["noise_strain_rel_max"])},
        {"metric": "noise_force_rel", "value": n_force, "criterion": None, "pass": None},
    ]
    verdict = "PASS" if all(m["pass"] for m in metrics if m["pass"] is not None) else "FAIL"
    fail_reasons = [_FAIL_REASON[m["metric"]] for m in metrics if m["pass"] is False]
    reactions = [{"node_id": int(nid[i]), "dof": d, "r": Rr[i].tolist()} for i, d in spc]
    val = {"schema": "esl/validation/1", "frame": summ["frame"], "verdict": verdict,
           "fail_reasons": fail_reasons, "criteria": crit, "noise": noise, "metrics": metrics,
           "hotspots": hots, "reactions": reactions, "reaction_sum": Rr.sum(axis=0),
           "created_at": _utcnow()}

    d = ctx.fresh_dir(D_VAL)
    _write_json(ctx.f(d, "validation.json"), val)
    fmt = ctx.csvfmt()
    csvout.write_validation_csv(ctx.f(d, "validation.csv"), val, fmt)
    csvout.write_csv(ctx.f(d, "compare.csv"),
                     ("node_id", "ux_rel", "uy_rel", "uz_rel", "ux_val", "uy_val", "uz_val", "d_mag"),
                     ((int(nid[i]), *d_rel[i], *d_val[i], dn[i]) for i in range(nid.size)), fmt)
    if verdict != "PASS":
        ctx.warnings.append("검증 FAIL: " + ", ".join(f"{m['metric']}({_FAIL_REASON[m['metric']]})"
                                                     for m in metrics if m["pass"] is False))
    ctx.echo(f"[validate] disp_rms_rel={disp_rms_rel:.2e} (≤{crit['disp_rms_rel_max']:g}), "
             f"hotspot1 rel_err={h1:.2e} (≤{crit['hotspot_strain_rel_err_max']:g}), "
             f"반력 Σ|R|/Σ|F|={reac_abs_rel:.2e} (≤{crit['reaction_rel_max']:g}), "
             + (f"잡음 hotspot_strain_rel={n_strain:.2e} (≤{crit['noise_strain_rel_max']:g})"
                if n_strain is not None else "잡음 N/A")
             + f" → {verdict}" + (f" {fail_reasons}" if fail_reasons else ""))
    return {"verdict": verdict, "fail_reasons": fail_reasons, "noise_hotspot_strain_rel": n_strain,
            "noise_force_rel": n_force, "disp_rms_rel": disp_rms_rel, "disp_max_rel": disp_max_rel,
            "hotspot1_rel_err": h1, "reaction_rel": reac_abs_rel, "reaction_sum_rel": reac_sum_rel}


# ====================================================================== export
def stage_export(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_BC}/support.json", f"{D_ESL}/u_rel.npz", f"{D_ESL}/f_eq.npz",
                       f"{D_ESL}/esl_summary.json", f"{D_TSTAR}/tstar.json"])
    model = load_model(ctx.out)
    nid, X0 = model.node_id, model.x0
    ur = _load_npz(ctx.p(D_ESL, "u_rel.npz"))
    fz = _load_npz(ctx.p(D_ESL, "f_eq.npz"))
    sup = _read_json(ctx.p(D_BC, "support.json"))["supports"]
    summ = _read_json(ctx.p(D_ESL, "esl_summary.json"))
    tj = _read_json(ctx.p(D_TSTAR, "tstar.json"))
    vpath = ctx.p(D_VAL, "validation.json")
    val = _read_json(vpath) if os.path.isfile(vpath) else None
    if val is None:
        ctx.warnings.append("검증(05_val) 결과 없음 — validation.csv·reactions_321.csv 생략")
    elif val.get("verdict") != "PASS":
        ctx.warnings.append(f"검증 {val.get('verdict')} 상태로 내보냄")
    F = fz["f"]
    ecfg = ctx.cfg["export"]
    rcfg = ecfg["radioss"]
    mask = force_mask(F, ecfg["force_zero_tol_rel"])
    groups, _ = optistruct.pshell_groups(model.elem_pid, model.thickness)
    plan = plan_ids(rcfg["id_offset"], model.max_ids, len(sup), len(groups),
                    int(mask.any(axis=1).sum()), int(mask.sum()))
    lo, hi = plan["range"]
    ids = all_ids(plan)
    assert all(lo <= v <= hi for v in ids)

    fr = summ["frame"]
    units = ctx.cfg["units"]
    hdr = [f"ESL export (esl {esl.__version__})  generated {_utcnow()}",
           f"part {model.part_id} '{model.part_title}'  frame {fr['frame_index']}  t* = {fr['time']!r} ({fr['source']})",
           f"units: {units['label']} (force {units['force']}, length {units['length']}); rad /BEGIN: '{model.units_label}'",
           f"generated ID range [{lo}, {hi}], used up to {plan['max_used']}",
           f"validation: {val['verdict'] if val else 'N/A'}"]
    d = ctx.fresh_dir(D_EXPORT)
    nf = ecfg["num_format"]
    supports_ids = [(int(s["node_id"]), s["dof"]) for s in sup]
    rc = radioss.write_cload_inc(ctx.f(d, "esl_cload.inc"), nid, F, mask, plan, rcfg["func_mode"],
                                 rcfg["ramp_time"], nf, hdr + [f"/CLOAD: |F_c| > {ecfg['force_zero_tol_rel']:g}*max|F|"])
    rb = radioss.write_bcs_inc(ctx.f(d, "esl_bcs.inc"), supports_ids, plan,
                               hdr + ["3-2-1 statically determinate supports (Tx Ty Tz flags, rotations free)"])
    fo = optistruct.write_force_fem(ctx.f(d, "esl_force.fem"), model, F, mask, supports_ids, plan, nf,
                                    hdr + [f"SPC SID {plan['fem_spc_sid']}, LOAD SID {plan['fem_load_sid']}"])
    fmt = ctx.csvfmt()
    is_bc = fz["is_bc"]
    csvout.write_csv(ctx.f(d, "f_eq.csv"), csvout.F_EQ_HEADER, csvout.f_eq_rows(nid, X0, F, is_bc), fmt)
    csvout.write_csv(ctx.f(d, "u_rel.csv"), csvout.U_REL_HEADER,
                     ((int(nid[i]), *ur["u_rel"][i], *ur["u_total"][i]) for i in range(nid.size)), fmt)
    csvout.write_csv(ctx.f(d, "tstar_candidates.csv"), csvout.CANDIDATES_HEADER,
                     ((x["rank"], x["frame_index"], x["time"], x["eps_max"], x["elem_id"]) for x in tj["candidates"]),
                     fmt)
    csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER,
                     ((x["rank"], x["elem_id"], x["eps_eq"], *x["centroid"]) for x in tj["hotspots"]), fmt)
    files = ["esl_cload.inc", "esl_bcs.inc", "esl_force.fem", "f_eq.csv", "u_rel.csv",
             "tstar_candidates.csv", "hotspots.csv"]
    if val is not None:
        rs = val["reactions"]
        tot = np.sum([r["r"] for r in rs], axis=0) if rs else np.zeros(3)
        rows = [(r["node_id"], r["dof"], *r["r"]) for r in rs] + [("SUM", None, *tot)]
        csvout.write_csv(ctx.f(d, "reactions_321.csv"), csvout.REACTIONS_HEADER, rows, fmt)
        csvout.write_validation_csv(ctx.f(d, "validation.csv"), val, fmt)
        files += ["reactions_321.csv", "validation.csv"]
    ctx.echo(f"[export] 파일 {len(files)}개, /CLOAD {rc['n_cload']} (노드 {rc['n_grnod']}), /BCS {rb['n_bcs']}, "
             f"FORCE {fo['n_force']}, PSHELL {fo['n_pshell']}, ID [{lo}..{plan['max_used']}] ⊂ [{lo}, {hi}]")
    return {"files": files, "id_range": [lo, hi], "id_max_used": plan["max_used"], "n_cload": rc["n_cload"],
            "n_cload_nodes": rc["n_grnod"], "n_bcs": rb["n_bcs"], "n_force": fo["n_force"],
            "n_pshell": fo["n_pshell"], "pshell_map": fo["pshell_map"],
            "id_plan": {k: (v if not isinstance(v, list) or len(v) <= 6 else [v[0], v[-1]])
                        for k, v in plan.items()}}


_STAGE_FN = {"extract": stage_extract, "tstar": stage_tstar, "esl": stage_esl,
             "validate": stage_validate, "export": stage_export}


# ====================================================================== 진입점
def _known_includes(out: str) -> list[str]:
    """이전 실행이 기록한 include 경로(run.json inputs, 01_extract/model_meta.json). 읽기 실패는 무시."""
    paths: list[str] = []
    try:
        inc = (_read_json(os.path.join(out, RUN_JSON)).get("inputs") or {}).get("includes") or []
        paths += [x["path"] for x in inc if isinstance(x, dict) and x.get("path")]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        paths += [p for p in _read_json(os.path.join(out, D_EXTRACT, "model_meta.json")).get("includes") or []
                  if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        pass
    return paths


def _check_paths(rad: str, results: str, out: str, includes=()) -> tuple[list, str]:
    """보호 폴더 목록과 출력 realpath. 겹치면 INPUT_INVALID."""
    prot = protected_dirs(rad, results, includes)
    return prot, check_overlap(out, prot)


def _new_record(out: str) -> dict:
    return {"schema": "esl/run/1", "esl_version": esl.__version__, "created_at": _utcnow(), "out_dir": out,
            "inputs": None, "config": None, "stages": {}, "history": [], "error": None}


def run(config_path=None, rad=None, results=None, out=None, stage: str = "all", frame: int | None = None,
        support_nodes: list[int] | None = None, cfg: dict | None = None,
        echo: Callable[[str], None] = print, argv: list[str] | None = None) -> dict:
    """파이프라인 실행. 실패 시 run.json 에 오류를 기록하고 EslError 를 다시 던진다."""
    if out is None or rad is None or results is None:
        raise EslError("INPUT_INVALID", "--rad, --results, --out 이 모두 필요")
    rad, results, out = (os.path.abspath(os.fspath(p)) for p in (rad, results, out))
    prot, out_real = _check_paths(rad, results, out)
    if os.path.isdir(out):
        prot, out_real = _check_paths(rad, results, out, _known_includes(out))
    if stage != "all" and stage not in STAGES:
        raise EslError("INPUT_INVALID", f"--stage 는 {list(STAGES) + ['all']} 중 하나 (값 {stage})")
    rj = os.path.join(out, RUN_JSON)
    record = _new_record(out)
    if os.path.isfile(rj):
        try:
            record = _read_json(rj)
        except (OSError, ValueError):
            record = _new_record(out)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    inv = {"started_at": _utcnow(), "stage": stage, "frame": frame, "support_nodes": support_nodes,
           "rad": rad, "results": results, "argv": argv, "ok": False, "error": None}
    record.setdefault("history", []).append(inv)
    record["error"] = None
    ctx = Context(cfg=cfg or {}, config_path="", rad=rad, results=results, out=out, ts=ts, frame=frame,
                  support_nodes=support_nodes, echo=echo, record=record, protected=prot, out_real=out_real)
    cur = "config"
    try:
        ctx.guard(rj)               # run.json 이 밖을 가리키는 링크면 아무 단계도 실행하지 않음
        if cfg is None:
            cp = _config.resolve_config_path(config_path)
            ctx.cfg = _config.load_config(cp)
            ctx.config_path = os.path.abspath(cp)
        else:
            ctx.cfg = _config.validate_settings(cfg)
            ctx.config_path = os.path.abspath(config_path) if config_path else ""
        snap = _config.redacted_settings(ctx.cfg)
        csha = hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        record["config"] = {"path": ctx.config_path, "sha256": csha, "snapshot": snap}
        todo = list(STAGES) if stage == "all" else [stage]
        for st in todo:
            cur = st
            ctx.warnings = []
            t0 = _time.perf_counter()
            started = _utcnow()
            summary = _STAGE_FN[st](ctx)
            el = _time.perf_counter() - t0
            record["stages"][st] = {"status": "done", "started_at": started, "finished_at": _utcnow(),
                                    "elapsed_s": round(el, 4), "config_sha256": csha, "summary": summary,
                                    "warnings": list(ctx.warnings), "stale": False}
            for w in ctx.warnings:
                echo(f"  경고: {w}")
            for later in STAGES[STAGES.index(st) + 1:]:
                if later in record["stages"] and later not in todo:
                    record["stages"][later]["stale"] = True
        inv["ok"] = True
        return record
    except EslError as exc:
        err = {"code": exc.code, "message": exc.message, "stage": cur, "at": _utcnow()}
        inv["error"] = err
        record["error"] = err
        if cur in STAGES:
            record["stages"][cur] = {"status": "failed", "finished_at": _utcnow(), "error": err,
                                     "warnings": list(ctx.warnings)}
        raise
    except Exception as exc:  # 예기치 않은 오류도 run.json 에 남긴다
        err = {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}", "stage": cur, "at": _utcnow()}
        inv["error"] = err
        record["error"] = err
        if cur in STAGES:
            record["stages"][cur] = {"status": "failed", "finished_at": _utcnow(), "error": err}
        raise
    finally:
        inv["finished_at"] = _utcnow()
        record["updated_at"] = _utcnow()
        try:
            ctx.guard(rj)
        except EslError:
            if inv["ok"]:       # (도중에 바뀐 경우) 성공으로 끝내지 않음
                raise
            # 출력이 입력과 겹침(include 등) → run.json 도 쓰지 않음(원래 오류가 전파됨)
        else:
            os.makedirs(ctx.guard(out), exist_ok=True)
            ctx.backup_file(RUN_JSON)
            _write_json(ctx.guard(rj), record)
