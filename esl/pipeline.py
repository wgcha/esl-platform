"""ESL 파이프라인: extract → tstar → esl → validate → export (계약 esl_core.md §5).

- 각 단계는 앞 단계의 **디스크 산출물만** 읽는다 → ``stage`` 하나만 다시 돌려 재개 가능.
- 입력(rad·결과 CSV 폴더)에는 쓰지 않는다. 출력 폴더가 입력 폴더와 겹치면 ``INPUT_INVALID``.
  겹침은 ``os.path.realpath`` 기준(심볼릭 링크·``..`` 우회 차단). 보호 대상 = rad 폴더, rad 가 실제로 읽은
  include 파일의 폴더, 결과 CSV 폴더. include 목록은 단계와 무관하게 어떤 쓰기보다 먼저
  ``scan_includes``(본문 해석 없는 include 트리 스캔, 설정 로드 뒤 include_path_map 으로 재스캔)와 이전 실행
  기록(run.json·model_meta.json)의 합집합으로 정한다. 모든 쓰기(백업 이동 포함) 직전에 대상 realpath 가 출력 루트
  realpath 안이고 보호 대상 밖인지 다시 확인한다.
- S4 는 변위 저장 정밀도(``extract.disp_precision``)의 잡음 바닥을 추정해 ``esl_summary.json`` 의
  ``noise`` 에 기록한다(검증 기준 초과 시 S5 verdict FAIL, 사유 ``NOISE_FLOOR``).
- 단계 산출물 폴더에 기존 파일이 있으면 ``_backup/<UTC timestamp>/<폴더>`` 로 **이동**한 뒤 새로 쓴다
  (삭제하지 않음). ``run.json`` 도 덮어쓰기 전에 같은 곳으로 이동.
- 판정 기준·허용오차·오프셋·파트 title 은 설정(``esl.config``)에서만 읽는다.

출력 폴더::

  01_extract/  model.npz, model_meta.json, final.npz, history.npz, strain_frames.npz, disp.npz, frames.json
               (§7.3; frames.json 에 전단 규약 판정 shear 추가)
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
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

import esl
from esl import config as _config
from esl.errors import EslError
from esl.export import all_ids, dof_flags, force_mask, plan_ids
from esl.export import csvout, optistruct, radioss
from esl.io import RESULT_FILES, decide_shear, pack_results, tensor_eps
from esl.io.results_csv import METRICS
from esl.mech import kabsch, strain, supports, tstar
from esl.mech.shell import ShellModel
from esl.rad import parse_rad, scan_includes

STAGES = ("extract", "tstar", "esl", "validate", "export")
EXPORT_TARGETS = ("radioss_inc", "fem", "csv")
D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT = (
    "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export")
BACKUP_DIR = "_backup"
RUN_JSON = "run.json"
HOT_K_WARN = 1000          # extract.hot_k 상한은 없고 이보다 크면 경고
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

    def shell(self, drill_factor: float, backend: str = "auto", iter_rtol: float = 1e-10,
              iter_maxiter: int | None = None) -> ShellModel:
        return ShellModel(self.x0, self.conn, self.elem_type, self.thickness, self.E, self.nu,
                          drill_factor=drill_factor, backend=backend, iter_rtol=iter_rtol, iter_maxiter=iter_maxiter)

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
    includes: list = field(default_factory=list)
    tag: str | None = None                      # 호출자 실행 태그(esl_summary.json·validation.json 에 기록)
    export_targets: tuple = EXPORT_TARGETS      # 내보낼 대상(radioss_inc | fem | csv)

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
        """include 폴더를 보호 대상에 추가(기존 목록과 합집합)하고 출력 겹침을 다시 검사."""
        for p in includes:
            if p not in self.includes:
                self.includes.append(p)
        self.protected = protected_dirs(self.rad, self.results, self.includes)
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


def _solver_eq(eps, layers) -> np.ndarray:
    """ShellModel.strains (..., 2, 3) → ε_eq (...) — 설정 extract.layers (mid = (bottom+top)/2 = 막 z=0, 여럿이면 최대)."""
    eps = np.asarray(eps, dtype=np.float64)
    vals = []
    for lay in layers:
        if lay == "mid":
            e = 0.5 * (eps[..., 0, :] + eps[..., 1, :])
        elif lay == "bottom":
            e = eps[..., 0, :]
        elif lay == "top":
            e = eps[..., 1, :]
        else:
            raise EslError("CONFIG_INVALID", f"extract.layers: {lay}")
        vals.append(strain.eps_eq(e))
    return np.max(np.stack(vals), axis=0)


def _exclude_mask(ctx: Context, all_ids, sub_ids=None) -> np.ndarray | None:
    """tstar.exclude_elem_ids → sub_ids(기본 all_ids) 위 bool 마스크. 대상 파트에 없는 ID 는 경고."""
    ids = ctx.cfg["tstar"]["exclude_elem_ids"]
    if not ids:
        return None
    ids = np.asarray(ids, dtype=np.int64)
    known = np.isin(ids, all_ids)
    if not known.all():
        ctx.warnings.append(f"tstar.exclude_elem_ids 중 대상 파트에 없는 요소 무시: {ids[~known][:10].tolist()}")
    return np.isin(all_ids if sub_ids is None else sub_ids, ids)


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


# ---------------------------------------------------------------------- 01_extract 읽기 도구
def _frames_meta(ctx: Context) -> dict:
    return _read_json(ctx.p(D_EXTRACT, "frames.json"))


def _shear_factor(ctx: Context, meta: dict) -> float:
    sh = meta.get("shear")
    if not isinstance(sh, dict) or "factor" not in sh:
        ctx.warnings.append("frames.json 에 전단 규약(shear) 없음 — 텐서 규약으로 가정(extract 다시 실행 권장)")
        return 1.0
    return float(sh["factor"])


def _history(ctx: Context, model: StoredModel):
    """history.npz + H 의 모델 위치."""
    hz = _load_npz(ctx.p(D_EXTRACT, "history.npz"))
    hp = _lookup_pos(model.elem_id, hz["elem_id"])
    if np.any(hp < 0):
        raise EslError("ID_MISMATCH", "history.npz elem_id 중 model.npz 에 없는 요소가 있음")
    return hz, hp


def _lookup_pos(sorted_ids, ids) -> np.ndarray:
    sorted_ids = np.asarray(sorted_ids)
    ids = np.asarray(ids)
    pos = np.searchsorted(sorted_ids, ids)
    pc = np.minimum(pos, max(sorted_ids.size - 1, 0))
    return np.where(sorted_ids[pc] == ids, pc, -1)


def _metric_series(hz: dict, factor: float) -> dict:
    """지표 이력 (F,H): max_strain = ε_eq(Max_Strain 텐서, 규약 보정), plastic_strain = epsp."""
    return {"max_strain": strain.eps_eq(tensor_eps(hz["eps"], factor)),
            "plastic_strain": np.asarray(hz["epsp"], dtype=np.float64)}


# ====================================================================== S1 extract
def stage_extract(ctx: Context) -> dict:
    c = ctx.cfg["case"]
    ecfg = ctx.cfg["extract"]
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
    for fn in ("model.npz", "model_meta.json", "final.npz", "history.npz", "strain_frames.npz", "disp.npz",
               "frames.json"):
        ctx.f(d, fn)
    save_model(d, model)
    info = pack_results(ctx.results, model, d, frame_stride=ecfg["frame_stride"])
    ctx.warnings += list(getattr(model, "warnings", [])) + list(info.get("warnings", []))

    # 전단 규약(§7.1): 최종 프레임 전 요소의 HyperView vonMises 와 비교
    fz = _load_npz(os.path.join(d, "final.npz"))
    sh = decide_shear(fz["vm_hv"], fz["eps"], ecfg["shear_convention"])
    mm = sh["max_rel_mismatch"]
    if mm is None:
        ctx.warnings.append("전단 규약 판정 불가(vonMises 가 모두 0) — 텐서 규약으로 가정")
    elif mm > SHEAR_MISMATCH_WARN:
        ctx.warnings.append(f"ε_eq(§4 공식, {sh['convention']}) 와 HyperView vonMises 의 최대 상대 불일치 {mm:.3g} > "
                            f"{SHEAR_MISMATCH_WARN:g} (요소 {sh['n_used']}개, 중앙값 {sh['median'][sh['convention']]:.3g})")
    fpath = ctx.f(d, "frames.json")
    meta = _read_json(fpath)
    meta["shear"] = sh
    _write_json(fpath, meta)
    if ecfg["hot_k"] > HOT_K_WARN:
        ctx.warnings.append(f"extract.hot_k={ecfg['hot_k']} > {HOT_K_WARN}: history 이력이 n_frames×2·hot_k 행까지 커짐")
    if meta.get("hot_k") not in (None, ecfg["hot_k"]):
        ctx.warnings.append(f"TCL hot_k={meta.get('hot_k')} ≠ 설정 extract.hot_k={ecfg['hot_k']} "
                            f"(TCL 을 -hot_k {ecfg['hot_k']} 로 다시 실행하거나 설정을 맞출 것)")
    rt = meta.get("reach_rtol")
    if rt is not None and not np.isclose(float(rt), ctx.cfg["tstar"]["reach_rtol"], rtol=1e-9, atol=0.0):
        ctx.warnings.append(f"TCL reach_rtol={rt} ≠ 설정 tstar.reach_rtol={ctx.cfg['tstar']['reach_rtol']}")

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
         "n_hot": info["n_hot"], "frames_D": info["frames_D"], "candidate_frames": info["candidate_frames"],
         "shear": {"convention": sh["convention"], "mode": sh["mode"], "max_rel_mismatch": mm,
                   "median": sh["median"]},
         "mats": model.mats, "max_ids": model.max_ids}
    ctx.echo(f"[extract] 파트 {model.part_id} '{model.part_title}': 노드 {s['n_nodes']}, 요소 {s['n_elems']} "
             f"(QUAD {s['n_quad']}/TRIA {s['n_tria']}), 이력 프레임 {s['n_frames']}, H {s['n_hot']}요소, "
             f"후보 프레임 D {s['frames_D']}, 전단 {sh['convention']}"
             + (f" (vonMises 최대 불일치 {mm:.2e})" if mm is not None else ""))
    return s


# ====================================================================== S2 tstar
def _select_frame(tj: dict, frame: int | None) -> dict:
    """자동 t* 또는 --frame (후보 프레임 D 안에서만)."""
    if frame is None:
        return dict(tj["selected"])
    D = {int(x["frame_index"]): x for x in tj["frames_D"]}
    if int(frame) not in D:
        raise EslError("FRAME_NOT_CANDIDATE",
                       f"frame {frame} 은 후보 프레임 D 가 아님 (D: {sorted(D)} — 변위·변형률은 D 프레임에만 있음)")
    c = next((c for c in tj["candidates"] if int(c["frame_index"]) == int(frame)), None)
    return {"frame_index": int(frame), "time": float(D[int(frame)]["time"]),
            "elem_id": c["elem_id"] if c else None, "value": c["value"] if c else None,
            "metric": tj["metric"], "source": "user"}


def stage_tstar(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_EXTRACT}/history.npz", f"{D_EXTRACT}/frames.json", f"{D_EXTRACT}/strain_frames.npz"])
    model = load_model(ctx.out)
    meta = _frames_meta(ctx)
    factor = _shear_factor(ctx, meta)
    hz, hp = _history(ctx, model)
    tcfg = ctx.cfg["tstar"]
    metric = tcfg["metric"]
    rtol = float(tcfg["reach_rtol"])
    C = model.centroids()[hp]
    ex = _exclude_mask(ctx, model.elem_id, hz["elem_id"])
    tw = tcfg["time_window"]
    series = _metric_series(hz, factor)
    tclq = {"max_strain": np.asarray(hz["vm_hv"], np.float64), "plastic_strain": series["plastic_strain"]}
    fidx = hz["frame_index"].astype(np.int64)
    hid = hz["elem_id"]
    D = [int(x) for x in meta["frames_D"]]
    tD = dict(zip(D, meta["time_D"]))
    tcl_top_n = int(meta.get("top_n") or tcfg["top_n_times"])
    tcl_rtol = float(meta["reach_rtol"]) if meta.get("reach_rtol") is not None else rtol
    full = int(meta.get("frame_stride", 1)) == 1 and int(meta.get("n_frames_h3d", fidx.size)) == fidx.size

    out: dict[str, dict] = {}
    for m in METRICS:
        # TCL 의 D 와 같은 양(vm_hv·epsp)·규칙으로 재계산해 일치 확인
        tcl = (meta.get("candidate_frames") or {}).get(m)
        if full:
            py = [int(fidx[f]) for f, _ in tstar.candidate_frames(tclq[m], tcl_rtol, tcl_top_n)]
            match = None if tcl is None else (py == [int(x) for x in tcl])
        else:
            py, match = None, None
        check = {"tcl": tcl, "python": py, "match": match,
                 "note": None if full else "frame_stride>1: 전 프레임 이력이 아니라 비교 생략"}
        if match is False:
            ctx.warnings.append(f"[{m}] TCL 후보 프레임 {tcl} ≠ Python 재계산 {py} (history.npz float32 반올림 등)")
        try:
            r = tstar.scan_reach(hz["time"], series[m], C, tcfg["top_n_times"], tcfg["top_k_hotspots"],
                                 tcfg["hotspot_min_dist"], rtol, time_window=(tw[0], tw[1]), exclude_mask=ex)
        except EslError as exc:
            if m == metric:
                raise
            ctx.warnings.append(f"[{m}] t* 계산 불가: {exc.message}")
            out[m] = {"error": f"{exc.code}: {exc.message}", "tcl_check": check}
            continue
        cands = [{"rank": c["rank"], "frame_index": int(fidx[c["frame_pos"]]), "time": c["time"],
                  "elem_id": int(hid[c["elem_pos"]]), "value": c["value"], "eps_max": c["value"],
                  "in_D": int(fidx[c["frame_pos"]]) in tD} for c in r["candidates"]]
        ts = dict(cands[0])
        adjusted = None
        if not ts["in_D"]:
            alt = next((c for c in cands if c["in_D"]), None)
            msg = (f"[{m}] t* frame {ts['frame_index']} 이 후보 프레임 D {D} 에 없음(변위 없음)"
                   + (f" → D 안의 후보 frame {alt['frame_index']} 사용" if alt else ""))
            if alt is None and m == metric:
                raise EslError("FRAME_NOT_CANDIDATE", msg + " — TCL 을 다시 실행(-top_n 증가)하거나 --frame 으로 D 안에서 지정")
            ctx.warnings.append(msg)
            adjusted = {"from": ts["frame_index"], "to": alt["frame_index"] if alt else None}
            if alt is not None:
                ts = dict(alt)
        hots = [{"rank": h["rank"], "elem_id": int(hid[h["elem_pos"]]), "value": h["value"], "eps_eq": h["value"],
                 "rising": h["rising"], "centroid": h["centroid"]} for h in r["hotspots"]]
        out[m] = {"tstar": {k: ts[k] for k in ("frame_index", "time", "elem_id", "value")},
                  "candidates": cands, "hotspots": hots, "adjusted": adjusted, "tcl_check": check,
                  "history": {"time": r["history"]["time"], "m": r["history"]["m"]}}

    sel_m = out[metric]
    auto = {**sel_m["tstar"], "eps_eq": sel_m["tstar"]["value"], "metric": metric, "source": "auto"}
    tj = {"schema": "esl/tstar/2", "metric": metric, "reach_rtol": rtol,
          "shear": meta.get("shear", {}).get("convention"),
          "frames_D": [{"frame_index": f, "time": tD[f]} for f in D],
          "metrics": {m: {k: v for k, v in rec.items() if k != "history"} for m, rec in out.items()},
          "auto": auto, "candidates": sel_m["candidates"], "hotspots": sel_m["hotspots"],
          "settings": dict(tcfg), "created_at": _utcnow()}
    for m, rec in out.items():
        if "history" in rec:
            tj["metrics"][m]["history"] = {"time": rec["history"]["time"], "m": rec["history"]["m"]}
    tj["selected"] = auto
    tj["selected"] = _select_frame(tj, ctx.frame)

    d = ctx.fresh_dir(D_TSTAR)
    _write_json(ctx.f(d, "tstar.json"), tj)
    fmt = ctx.csvfmt()
    hist_cols = [out[m]["history"]["m"] if "history" in out[m] else np.full(fidx.size, np.nan) for m in METRICS]
    csvout.write_csv(ctx.f(d, "history.csv"), ("frame_index", "time", "m_max_strain", "m_plastic_strain"),
                     zip(fidx.tolist(), hz["time"], *hist_cols), fmt)
    csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER,
                     ((x["rank"], x["elem_id"], x["value"], *x["centroid"]) for x in sel_m["hotspots"]), fmt)
    csvout.write_csv(ctx.f(d, "candidates.csv"),
                     ("metric", "rank", "frame_index", "time", "value", "elem_id", "in_D"),
                     ((m, x["rank"], x["frame_index"], x["time"], x["value"], x["elem_id"], x["in_D"])
                      for m in METRICS for x in out[m].get("candidates", [])), fmt)
    sel = tj["selected"]
    other = [m for m in METRICS if m != metric][0]
    o = out[other].get("tstar")
    ctx.echo(f"[tstar] t* = frame {sel['frame_index']} (time {sel['time']:.6g}, {sel['source']}, {metric} "
             f"first-reach), 값 {auto['value']:.4g} @ elem {auto['elem_id']}, 후보 {len(sel_m['candidates'])}개, "
             f"hotspot {len(sel_m['hotspots'])}개; {other}: "
             + (f"t* frame {o['frame_index']} (값 {o['value']:.4g})" if o else "없음")
             + f"; D {D}")
    return {"selected": sel, "auto": auto, "metric": metric,
            "tstar_by_metric": {m: out[m].get("tstar") for m in METRICS},
            "tcl_check": {m: out[m]["tcl_check"]["match"] for m in METRICS},
            "n_candidates": len(sel_m["candidates"]), "n_hotspots": len(sel_m["hotspots"])}


# ====================================================================== 평가 hotspot·잡음 바닥
NOISE_SEED = 20240917          # 잡음 섭동 고정 시드(재현성)
_PRECISION = {"float32": np.float32, "float64": np.float64}
SHEAR_MISMATCH_WARN = 0.05     # ε_eq vs HyperView vonMises 최대 상대 불일치 경고(§7.1)


def _eval_hotspots(ctx: Context, model: StoredModel, frame_index: int):
    """프레임 frame_index 의 검증 hotspot(§7.4)과 Radioss ε_eq (E,) (strain_frames, Mid=막, 전단 규약 보정).

    hotspot = 그 프레임에서 지표(tstar.metric)가 상승 중인 H 요소(+ 그 프레임에 최종값에 처음 도달한 1위 요소),
    거리 필터 후 상위 top_k_hotspots. 각 요소의 Max_Strain ε_eq 도 상승 중이어야 비교 가능(hold 값 = 순간값),
    아니면 comparable=False, reason 기록. 비교 가능한 것 중 앞에서 hotspot_eval_count 개를 compared=True.
    """
    meta = _frames_meta(ctx)
    factor = _shear_factor(ctx, meta)
    hz, hp = _history(ctx, model)
    fh = np.flatnonzero(hz["frame_index"].astype(np.int64) == int(frame_index))
    sz = _load_npz(ctx.p(D_EXTRACT, "strain_frames.npz"))
    fd = np.flatnonzero(sz["frame_index"].astype(np.int64) == int(frame_index))
    if fh.size != 1 or fd.size != 1:
        raise EslError("FRAME_NOT_CANDIDATE", f"history.npz·strain_frames.npz 에 frame {frame_index} 이 없음")
    if not np.array_equal(sz["elem_id"], model.elem_id):
        raise EslError("ID_MISMATCH", "strain_frames.npz elem_id 가 model.npz 와 다름")
    f = int(fh[0])
    tcfg = ctx.cfg["tstar"]
    rtol = float(tcfg["reach_rtol"])
    series = _metric_series(hz, factor)
    v = series[tcfg["metric"]]
    eqh = series["max_strain"]
    ex = _exclude_mask(ctx, model.elem_id, hz["elem_id"])
    fr = tstar.first_reach(v, rtol)
    fin = v[-1]
    first = None
    for e in np.lexsort((np.arange(fin.size), -fin)):
        if fr[e] == f and fin[e] > 0 and (ex is None or not ex[e]):
            first = int(e)
            break
    C = model.centroids()
    hs = tstar.rising_hotspots(v, f, C[hp], tcfg["top_k_hotspots"], tcfg["hotspot_min_dist"], rtol,
                               exclude_mask=ex, first=first)
    eps_rad = strain.eps_eq(tensor_eps(sz["eps"][int(fd[0])], factor))          # (E,)
    n_eval = int(ctx.cfg["validation"]["hotspot_eval_count"])
    out, k = [], 0
    for h in hs:
        e = h["elem_pos"]
        mp = int(hp[e])
        rise = bool(eqh[f, e] > eqh[f - 1, e] * (1.0 + rtol)) if f > 0 else bool(eqh[f, e] > 0)
        rec = {"rank": h["rank"], "elem_pos": mp, "elem_id": int(model.elem_id[mp]), "value": h["value"],
               "eps_rad": float(eps_rad[mp]), "comparable": rise, "compared": False,
               "reason": None if rise else "Max_Strain hold 값이 이 프레임에서 상승 중이 아님(순간값 아님)",
               "centroid": C[mp].tolist()}
        if rise and k < n_eval:
            rec["compared"] = True
            k += 1
        out.append(rec)
    return out, eps_rad


def _with_rot(sm: ShellModel, u_t: np.ndarray) -> np.ndarray:
    """병진 u_t (N,3) + condensation 회전 → (N,6)."""
    return np.hstack([u_t, sm.rotations_for(u_t)])


def noise_floor(ctx: Context, sm: ShellModel, X0, u_total, u_rel, F, hot_pos) -> dict:
    """변위 저장 정밀도의 잡음 바닥.

    δ = 0.5·ulp(precision)·max|X0+u| (= eps_mach/2·max|x|; float32 → 2^-24·max|x|).
    고정 시드 균일 ±δ 섭동 n 개 → F_noise = condensed_forces(noise), ε(u_rel+noise) (회전은 condensation).
    force_rel = max_s rms(F_noise)/rms(F_eq), hotspot_strain_rel = max_s max_h |ε_eq(u_rel+n)−ε_eq(u_rel)|/ε_eq(u_rel).
    ε_eq 는 extract.layers(기본 막 z=0).
    """
    prec = ctx.cfg["extract"]["disp_precision"]
    vcfg = ctx.cfg["validation"]
    n_s = int(vcfg["noise_samples"])
    layers = ctx.cfg["extract"]["layers"]
    xmax = float(np.max(np.abs(np.asarray(X0) + np.asarray(u_total)))) if np.size(X0) else 0.0
    delta = 0.5 * float(np.finfo(_PRECISION[prec]).eps) * xmax
    rms = lambda a: float(np.sqrt(np.mean(np.sum(np.asarray(a) ** 2, axis=1)))) if np.size(a) else 0.0
    rms_f = rms(F)
    hot_pos = np.asarray(hot_pos, dtype=np.int64)
    eps_rel = sm.strains(_with_rot(sm, u_rel))
    eq0 = _solver_eq(eps_rel, layers)[hot_pos]
    rng = np.random.default_rng(NOISE_SEED)
    f_rel, s_rel = [], []
    for _ in range(n_s):
        n = rng.uniform(-delta, delta, size=np.shape(u_rel))
        fn = sm.condensed_forces(n)
        f_rel.append(rms(fn) / rms_f if rms_f > 0 else float("inf"))
        if hot_pos.size:
            eq1 = _solver_eq(eps_rel + sm.strains(_with_rot(sm, n)), layers)[hot_pos]
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


S5_ITER_RTOL_MAX = 1e-12      # S5 전체계 solve 가 반복법일 때 상대잔차 상한(esl_core §7.5)


def _shell(ctx: Context, model: StoredModel) -> ShellModel:
    scfg = ctx.cfg["solver"]
    with warnings.catch_warnings(record=True) as wl:
        warnings.simplefilter("always", RuntimeWarning)
        sm = model.shell(scfg["drill_factor"], scfg["backend"], scfg["iter_rtol"], scfg["iter_maxiter"])
    ctx.warnings.extend(str(w.message) for w in wl)
    return sm


def _solver_call(ctx: Context, fn, *args):
    """ShellModel 호출 중 RuntimeWarning(메모리 부족 → 반복법 전환, SuperLU 폴백 등)을 run 경고로 옮긴다."""
    with warnings.catch_warnings(record=True) as wl:
        warnings.simplefilter("always", RuntimeWarning)
        out = fn(*args)
    ctx.warnings.extend(str(w.message) for w in wl)
    return out


def solver_stats(sm: ShellModel) -> dict:
    """ShellModel.stats(JSON 직렬화 가능한 사본)."""
    return _jsonable(sm.stats)


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
    _require(ctx.out, [f"{D_EXTRACT}/disp.npz", f"{D_EXTRACT}/history.npz", f"{D_EXTRACT}/strain_frames.npz",
                       f"{D_EXTRACT}/frames.json", f"{D_TSTAR}/tstar.json"])
    _check_inputs_unchanged(ctx)
    model = load_model(ctx.out)
    tj = _read_json(ctx.p(D_TSTAR, "tstar.json"))
    sel = _select_frame(tj, ctx.frame)
    dz = _load_npz(ctx.p(D_EXTRACT, "disp.npz"))
    if not np.array_equal(dz["node_id"], model.node_id):
        raise EslError("ID_MISMATCH", "disp.npz node_id 가 model.npz 와 다름")
    hit = np.flatnonzero(dz["frame_index"] == int(sel["frame_index"]))
    if hit.size != 1:
        raise EslError("FRAME_NOT_CANDIDATE", f"disp.npz 에 frame {sel['frame_index']} 이 없음 "
                                              f"(D: {dz['frame_index'].tolist()})")
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
    sm = _shell(ctx, model)
    F = _solver_call(ctx, sm.condensed_forces, u_rel)
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

    # ---- 변위 정밀도 잡음 바닥 (검증 hotspot 기준)
    hs, _ = _eval_hotspots(ctx, model, int(sel["frame_index"]))
    noise = noise_floor(ctx, sm, X0, u, u_rel, F, [h["elem_pos"] for h in hs if h["compared"]])
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
            "drill_factor": ctx.cfg["solver"]["drill_factor"], "backend": ctx.cfg["solver"]["backend"],
            "solver": solver_stats(sm), "tag": ctx.tag, "created_at": _utcnow()}
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
            "moment_rel": mom_rel, "supports": sup_rec["supports"], "support_mode": mode,
            "solver": solver_stats(sm)}


# ====================================================================== S5 validate
DIRECT_BYTES_PER_ELEM = 80e3     # 직접법 인수분해 메모리 추정(SuperLU 실측 10만 요소 7.3 GB → 73 KB/요소, 보수적)
FULL_SOLVE_MEM_FRAC = 0.8


def available_memory() -> int | None:
    """가용 메모리(바이트): /proc/meminfo MemAvailable, 없으면 sysconf, 모르면 None."""
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return None


def _solver_is_direct(sm: ShellModel) -> bool:
    """ShellModel 이 직접법(SuperLU·CHOLMOD)인지. 반복법임을 밝히는 속성이 있을 때만 False."""
    flag = getattr(sm, "is_direct", None)
    if isinstance(flag, bool):
        return flag
    name = str(getattr(sm, "backend", "") or getattr(sm, "backend_name", "")).lower()
    return not any(k in name for k in ("cg", "iter", "amg", "gmres"))


def full_solve_decision(ctx: Context, sm: ShellModel, n_elems: int) -> dict:
    """validation.full_solve: always | never | auto(직접법이고 메모리 추정 ≤ 가용 × 0.8 이면 수행)."""
    mode = ctx.cfg["validation"]["full_solve"]
    need = float(DIRECT_BYTES_PER_ELEM * n_elems)
    avail = available_memory()
    direct = _solver_is_direct(sm)
    rec = {"mode": mode, "direct": direct, "mem_need_est": need, "mem_avail": avail}
    if mode == "always":
        return {**rec, "run": True, "reason": "설정 always"}
    if mode == "never":
        return {**rec, "run": False, "reason": "설정 never"}
    if not direct:
        return {**rec, "run": True, "reason": f"auto: 반복법(rtol ≤ {S5_ITER_RTOL_MAX:g}), 직접법 메모리 불필요"}
    if avail is not None and need > FULL_SOLVE_MEM_FRAC * avail:
        return {**rec, "run": False,
                "reason": f"직접법 메모리 추정 {need / 1e9:.1f} GB > 가용 {avail / 1e9:.1f} GB × {FULL_SOLVE_MEM_FRAC}"}
    return {**rec, "run": True, "reason": "auto: 직접법, 메모리 충분" if avail is not None else "auto: 가용 메모리 모름"}


_FAIL_REASON = {"disp_rms_rel": "DISP_RMS", "hotspot1_strain_rel_err": "HOTSPOT_STRAIN",
                "reaction_rel": "REACTION", "noise_hotspot_strain_rel": "NOISE_FLOOR"}


def stage_validate(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_EXTRACT}/strain_frames.npz", f"{D_EXTRACT}/history.npz", f"{D_BC}/support.json",
                       f"{D_ESL}/u_rel.npz", f"{D_ESL}/f_eq.npz", f"{D_ESL}/esl_summary.json"])
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

    sm = _shell(ctx, model)
    fs = full_solve_decision(ctx, sm, int(model.elem_id.size))
    if fs["run"]:
        # 반복법이면 전체계는 rtol = min(설정, 1e-12) (직접법이면 영향 없음)
        sm.iter_opts["rtol"] = min(float(ctx.cfg["solver"]["iter_rtol"]), S5_ITER_RTOL_MAX)
        u_val, Rr = _solver_call(ctx, sm.solve, F, spc)
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
        eps_sol = sm.strains(u_val)
    else:
        # 전체 solve 생략: S4 의 u_rel + 응축 회전(rotations_for)으로 막 변형률 → hotspot 비교만
        ctx.warnings.append(f"S5 전체 solve 생략({fs['reason']}) — hotspot 변형률만 비교, disp_rms_rel·반력 skipped")
        u_val = _solver_call(ctx, _with_rot, sm, u_rel)
        Rr = None
        disp_rms_rel = disp_max_rel = reac_abs_rel = reac_sum_rel = lin_rigid_rel = None
        eps_sol = sm.strains(u_val)

    # hotspot ε_eq: Radioss(t* 프레임, Mid) vs 검증 해 막 변형률(extract.layers)
    layers = ctx.cfg["extract"]["layers"]
    hs, eps_rad = _eval_hotspots(ctx, model, int(summ["frame"]["frame_index"]))
    eps_val = _solver_eq(eps_sol, layers)
    vcfg = ctx.cfg["validation"]
    hots, excluded = [], []
    for h in hs:
        e = h["elem_pos"]
        rec = {"rank": h["rank"], "elem_id": h["elem_id"], "metric_value": h["value"], "centroid": h["centroid"]}
        if h["compared"]:
            er, ev = float(eps_rad[e]), float(eps_val[e])
            rec.update(eps_rad=er, eps_val=ev, rel_err=abs(ev - er) / er if er > 0 else float("inf"))
            hots.append(rec)
        elif not h["comparable"]:
            rec.update(reason=h["reason"], eps_rad=float(eps_rad[e]), eps_val=float(eps_val[e]))
            excluded.append(rec)
    if excluded:
        ctx.warnings.append(f"hotspot {len(excluded)}개 비교 제외(상승 중 아님): "
                            f"{[x['elem_id'] for x in excluded][:10]}")
    h1 = hots[0]["rel_err"] if hots else float("inf")
    if not hots:
        ctx.warnings.append("비교 가능한(상승 중인) hotspot 이 없음 → hotspot 변형률 기준 FAIL")

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
            "disp_precision": noise["disp_precision"] if noise else None, "layers": list(layers),
            "metric": ctx.cfg["tstar"]["metric"], "full_solve": fs["mode"]}

    def judged(name, v, c):
        if v is None:
            return {"metric": name, "value": None, "criterion": c, "pass": None, "status": "skipped"}
        return {"metric": name, "value": v, "criterion": c, "pass": bool(v <= c)}

    metrics = [
        judged("disp_rms_rel", disp_rms_rel, crit["disp_rms_rel_max"]),
        {"metric": "hotspot1_strain_rel_err", "value": h1, "criterion": crit["hotspot_strain_rel_err_max"],
         "pass": bool(h1 <= crit["hotspot_strain_rel_err_max"])},
        judged("reaction_rel", reac_abs_rel, crit["reaction_rel_max"]),
        {"metric": "disp_max_rel", "value": disp_max_rel, "criterion": None, "pass": None},
        {"metric": "reaction_sum_rel", "value": reac_sum_rel, "criterion": None, "pass": None},
        {"metric": "u_rel_linear_rigid_rel", "value": lin_rigid_rel, "criterion": None, "pass": None},
        {"metric": "noise_hotspot_strain_rel", "value": n_strain, "criterion": crit["noise_strain_rel_max"],
         "pass": None if n_strain is None else bool(n_strain <= crit["noise_strain_rel_max"])},
        {"metric": "noise_force_rel", "value": n_force, "criterion": None, "pass": None},
    ]
    verdict = "PASS" if all(m["pass"] for m in metrics if m["pass"] is not None) else "FAIL"
    fail_reasons = [_FAIL_REASON[m["metric"]] for m in metrics if m["pass"] is False]
    reactions = [] if Rr is None else [{"node_id": int(nid[i]), "dof": d, "r": Rr[i].tolist()} for i, d in spc]
    val = {"schema": "esl/validation/2", "frame": summ["frame"], "verdict": verdict, "esl_ref": esl_ref(summ),
           "fail_reasons": fail_reasons, "criteria": crit, "noise": noise, "metrics": metrics,
           "full_solve": fs, "hotspots": hots, "hotspots_excluded": excluded, "reactions": reactions,
           "reaction_sum": None if Rr is None else Rr.sum(axis=0), "created_at": _utcnow()}

    d = ctx.fresh_dir(D_VAL)
    _write_json(ctx.f(d, "validation.json"), val)
    fmt = ctx.csvfmt()
    csvout.write_validation_csv(ctx.f(d, "validation.csv"), val, fmt)
    if fs["run"]:
        csvout.write_csv(ctx.f(d, "compare.csv"),
                         ("node_id", "ux_rel", "uy_rel", "uz_rel", "ux_val", "uy_val", "uz_val", "d_mag"),
                         ((int(nid[i]), *d_rel[i], *d_val[i], dn[i]) for i in range(nid.size)), fmt)
    if verdict != "PASS":
        ctx.warnings.append("검증 FAIL: " + ", ".join(f"{m['metric']}({_FAIL_REASON[m['metric']]})"
                                                     for m in metrics if m["pass"] is False))
    fmt_v = lambda v: "skipped" if v is None else f"{v:.2e}"
    ctx.echo(f"[validate] disp_rms_rel={fmt_v(disp_rms_rel)} (≤{crit['disp_rms_rel_max']:g}), "
             f"hotspot1 rel_err={h1:.2e} (≤{crit['hotspot_strain_rel_err_max']:g}, 막 ε_eq, 비교 {len(hots)}·"
             f"제외 {len(excluded)}), "
             f"반력 Σ|R|/Σ|F|={fmt_v(reac_abs_rel)} (≤{crit['reaction_rel_max']:g}), "
             + (f"잡음 hotspot_strain_rel={n_strain:.2e} (≤{crit['noise_strain_rel_max']:g})"
                if n_strain is not None else "잡음 N/A")
             + f" → {verdict}" + (f" {fail_reasons}" if fail_reasons else ""))
    return {"verdict": verdict, "fail_reasons": fail_reasons, "noise_hotspot_strain_rel": n_strain,
            "noise_force_rel": n_force, "disp_rms_rel": disp_rms_rel, "disp_max_rel": disp_max_rel,
            "hotspot1_rel_err": h1, "reaction_rel": reac_abs_rel, "reaction_sum_rel": reac_sum_rel,
            "n_hotspots_compared": len(hots), "n_hotspots_excluded": len(excluded),
            "full_solve": {k: fs[k] for k in ("mode", "run", "reason")}, "solver": solver_stats(sm)}

# ====================================================================== export
def esl_ref(summ: dict) -> str | None:
    """esl_summary.json 식별자: 호출자 태그(있으면) 아니면 생성 시각. validation.json 의 esl_ref 와 대조."""
    return summ.get("tag") or summ.get("created_at")


def normalize_export_targets(targets) -> tuple:
    if targets is None:
        return EXPORT_TARGETS
    if isinstance(targets, str):
        targets = [t for t in targets.replace(" ", "").split(",") if t]
    t = list(dict.fromkeys(str(x) for x in targets))
    bad = [x for x in t if x not in EXPORT_TARGETS]
    if bad or not t:
        raise EslError("INPUT_INVALID", f"export_targets 는 {list(EXPORT_TARGETS)} 중 1개 이상 (값 {list(targets)})")
    return tuple(x for x in EXPORT_TARGETS if x in t)


def stage_export(ctx: Context) -> dict:
    _require(ctx.out, [f"{D_BC}/support.json", f"{D_ESL}/u_rel.npz", f"{D_ESL}/f_eq.npz",
                       f"{D_ESL}/esl_summary.json", f"{D_TSTAR}/tstar.json"])
    targets = normalize_export_targets(ctx.export_targets)
    model = load_model(ctx.out)
    nid, X0 = model.node_id, model.x0
    ur = _load_npz(ctx.p(D_ESL, "u_rel.npz"))
    fz = _load_npz(ctx.p(D_ESL, "f_eq.npz"))
    sup = _read_json(ctx.p(D_BC, "support.json"))["supports"]
    summ = _read_json(ctx.p(D_ESL, "esl_summary.json"))
    tj = _read_json(ctx.p(D_TSTAR, "tstar.json"))
    vpath = ctx.p(D_VAL, "validation.json")
    val = _read_json(vpath) if os.path.isfile(vpath) else None
    if val is not None and "esl_ref" in val and val["esl_ref"] != esl_ref(summ):
        ctx.warnings.append("검증(05_val) 결과가 현재 ESL(04_esl) 결과의 것이 아님 — 검증 결과 없이 내보냄")
        val = None
    if val is None:
        ctx.warnings.append("검증(05_val) 결과 없음 — validation.csv·reactions_321.csv 생략")
    elif val.get("verdict") != "PASS":
        ctx.warnings.append(f"검증 {val.get('verdict')} 상태로 내보냄")
    F = fz["f"]
    ecfg = ctx.cfg["export"]
    rcfg = ecfg["radioss"]
    mask = force_mask(F, ecfg["force_zero_tol_rel"])
    want_ids = "radioss_inc" in targets or "fem" in targets
    plan = None
    lo = hi = None
    if want_ids:      # ID 범위 계획·충돌 검사는 inc·fem 을 쓸 때만(csv 는 ID 를 만들지 않음)
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
           f"generated ID range [{lo}, {hi}], used up to {plan['max_used'] if plan else None}",
           f"validation: {val['verdict'] if val else 'N/A'}"]
    d = ctx.fresh_dir(D_EXPORT)
    nf = ecfg["num_format"]
    supports_ids = [(int(s["node_id"]), s["dof"]) for s in sup]
    files: list[str] = []
    out: dict = {"targets": list(targets)}
    if "radioss_inc" in targets:
        rc = radioss.write_cload_inc(ctx.f(d, "esl_cload.inc"), nid, F, mask, plan, rcfg["func_mode"],
                                     rcfg["ramp_time"], nf,
                                     hdr + [f"/CLOAD: |F_c| > {ecfg['force_zero_tol_rel']:g}*max|F|"])
        rb = radioss.write_bcs_inc(ctx.f(d, "esl_bcs.inc"), supports_ids, plan,
                                   hdr + ["3-2-1 statically determinate supports (Tx Ty Tz flags, rotations free)"])
        files += ["esl_cload.inc", "esl_bcs.inc"]
        out.update(n_cload=rc["n_cload"], n_cload_nodes=rc["n_grnod"], n_bcs=rb["n_bcs"])
    if "fem" in targets:
        fo = optistruct.write_force_fem(ctx.f(d, "esl_force.fem"), model, F, mask, supports_ids, plan, nf,
                                        hdr + [f"SPC SID {plan['fem_spc_sid']}, LOAD SID {plan['fem_load_sid']}"])
        files += ["esl_force.fem"]
        out.update(n_force=fo["n_force"], n_pshell=fo["n_pshell"], pshell_map=fo["pshell_map"])
    if "csv" in targets:
        fmt = ctx.csvfmt()
        is_bc = fz["is_bc"]
        csvout.write_csv(ctx.f(d, "f_eq.csv"), csvout.F_EQ_HEADER, csvout.f_eq_rows(nid, X0, F, is_bc), fmt)
        csvout.write_csv(ctx.f(d, "u_rel.csv"), csvout.U_REL_HEADER,
                         ((int(nid[i]), *ur["u_rel"][i], *ur["u_total"][i]) for i in range(nid.size)), fmt)
        csvout.write_csv(ctx.f(d, "tstar_candidates.csv"), csvout.CANDIDATES_HEADER,
                         ((x["rank"], x["frame_index"], x["time"], x["eps_max"], x["elem_id"])
                          for x in tj["candidates"]), fmt)
        csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER,
                         ((x["rank"], x["elem_id"], x["eps_eq"], *x["centroid"]) for x in tj["hotspots"]), fmt)
        files += ["f_eq.csv", "u_rel.csv", "tstar_candidates.csv", "hotspots.csv"]
        if val is not None:
            rs = val["reactions"]
            tot = np.sum([r["r"] for r in rs], axis=0) if rs else np.zeros(3)
            rows = [(r["node_id"], r["dof"], *r["r"]) for r in rs] + [("SUM", None, *tot)]
            csvout.write_csv(ctx.f(d, "reactions_321.csv"), csvout.REACTIONS_HEADER, rows, fmt)
            csvout.write_validation_csv(ctx.f(d, "validation.csv"), val, fmt)
            files += ["reactions_321.csv", "validation.csv"]
    ctx.echo(f"[export] 대상 {list(targets)}, 파일 {len(files)}개"
             + (f", /CLOAD {out['n_cload']} (노드 {out['n_cload_nodes']}), /BCS {out['n_bcs']}" if "n_cload" in out else "")
             + (f", FORCE {out['n_force']}, PSHELL {out['n_pshell']}" if "n_force" in out else "")
             + (f", ID [{lo}..{plan['max_used']}] ⊂ [{lo}, {hi}]" if plan else ""))
    out.update(files=files, id_range=[lo, hi] if plan else None, id_max_used=plan["max_used"] if plan else None,
               id_plan=None if plan is None else {k: (v if not isinstance(v, list) or len(v) <= 6 else [v[0], v[-1]])
                                                  for k, v in plan.items()},
               esl_ref=esl_ref(summ), validation_used=val is not None)
    return out


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


_PRESCAN_DEPTH = 64     # 설정을 읽기 전 사전 스캔 깊이(보호 목적이므로 넉넉히)


def _scan_includes_safe(rad: str, include_path_map=None, max_depth: int = _PRESCAN_DEPTH) -> list[str]:
    """rad 의 include 트리(본문 해석 없음). rad 가 없거나 읽기 실패면 빈 목록."""
    if not os.path.isfile(rad):
        return []
    try:
        return scan_includes(rad, include_path_map=include_path_map or None, max_depth=max_depth)
    except (OSError, ValueError):
        return []


def _union(*lists) -> list[str]:
    out: list[str] = []
    for lst in lists:
        for p in lst:
            if p not in out:
                out.append(p)
    return out


def _check_paths(rad: str, results: str, out: str, includes=()) -> tuple[list, str]:
    """보호 폴더 목록과 출력 realpath. 겹치면 INPUT_INVALID."""
    prot = protected_dirs(rad, results, includes)
    return prot, check_overlap(out, prot)


def _new_record(out: str) -> dict:
    return {"schema": "esl/run/1", "esl_version": esl.__version__, "created_at": _utcnow(), "out_dir": out,
            "inputs": None, "config": None, "stages": {}, "history": [], "error": None}


def run(config_path=None, rad=None, results=None, out=None, stage: str = "all", frame: int | None = None,
        support_nodes: list[int] | None = None, cfg: dict | None = None,
        echo: Callable[[str], None] = print, argv: list[str] | None = None,
        export_targets=None, tag: str | None = None) -> dict:
    """파이프라인 실행. 실패 시 run.json 에 오류를 기록하고 EslError 를 다시 던진다.

    ``export_targets``: export 단계에서 만들 대상(``radioss_inc``·``fem``·``csv`` 의 부분집합, 기본 전부).
    ``tag``: 호출자 실행 태그 — esl 단계가 ``esl_summary.json`` 의 ``tag`` 로 기록하고, validate 가 그 값을
    ``validation.json`` 의 ``esl_ref`` 로 남긴다(export 는 esl_ref 가 다른 검증 결과를 쓰지 않음).
    """
    if out is None or rad is None or results is None:
        raise EslError("INPUT_INVALID", "--rad, --results, --out 이 모두 필요")
    targets = normalize_export_targets(export_targets)
    rad, results, out = (os.path.abspath(os.fspath(p)) for p in (rad, results, out))
    # 어떤 쓰기(폴더 생성·백업 이동·run.json)보다 먼저: rad 의 include 트리 + 이전 실행 기록의 include 를
    # 보호 대상에 넣고 출력 겹침 검사 (단계와 무관하게 항상)
    includes = _union(_scan_includes_safe(rad), _known_includes(out) if os.path.isdir(out) else [])
    prot, out_real = _check_paths(rad, results, out, includes)
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
           "export_targets": list(targets), "tag": tag,
           "rad": rad, "results": results, "argv": argv, "ok": False, "error": None}
    record.setdefault("history", []).append(inv)
    record["error"] = None
    ctx = Context(cfg=cfg or {}, config_path="", rad=rad, results=results, out=out, ts=ts, frame=frame,
                  support_nodes=support_nodes, echo=echo, record=record, protected=prot, out_real=out_real,
                  includes=list(includes), tag=tag, export_targets=targets)
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
        cc = ctx.cfg.get("case") or {}
        # 설정의 include_path_map 으로 다시 스캔(매핑 경로의 include 폴더도 보호)
        ctx.protect(_scan_includes_safe(rad, cc.get("include_path_map"),
                                        max(int(cc.get("rad_include_max_depth") or 8), _PRESCAN_DEPTH)))
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
