"""ESL 파이프라인: extract → tstar → esl → validate → export (계약 esl_core.md §5).

- 각 단계는 앞 단계의 **디스크 산출물만** 읽는다 → ``stage`` 하나만 다시 돌려 재개 가능.
- 입력(rad·결과 CSV 폴더)에는 쓰지 않는다. 출력 폴더가 입력 폴더와 겹치면 ``INPUT_INVALID``.
  겹침은 ``os.path.realpath`` 기준(심볼릭 링크·``..`` 우회 차단). 보호 대상 = rad 폴더, rad 가 실제로 읽은
  include 파일의 폴더, 결과 CSV 폴더. include 목록은 단계와 무관하게 어떤 쓰기보다 먼저
  ``scan_includes``(본문 해석 없는 include 트리 스캔, 설정 로드 뒤 include_path_map 으로 재스캔)와 이전 실행
  기록(run.json·model_meta.json)의 합집합으로 정한다. 모든 쓰기(백업 이동 포함) 직전에 대상 realpath 가 출력 루트
  realpath 안이고 보호 대상 밖인지 다시 확인한다.
- S4 는 변위 저장 정밀도(``extract.disp_precision``)의 잡음 바닥을 추정해 ``esl_summary.json`` 의
  ``noise`` 에 기록한다(0.5.7: 변형률 기반 잡음 지표는 참고, 판정은 변위 잡음 ``disp_noise_rel`` = δ/U).
- 단계 산출물 폴더에 기존 파일이 있으면 ``_backup/<UTC timestamp>/<폴더>`` 로 **이동**한 뒤 새로 쓴다
  (삭제하지 않음). ``run.json`` 도 덮어쓰기 전에 같은 곳으로 이동.
- 판정 기준·허용오차·오프셋·파트 title 은 설정(``esl.config``)에서만 읽는다.

출력 폴더::

  01_extract/  model.npz, model_meta.json, final.npz, history.npz, strain_frames.npz, disp.npz, frames.json
               (§7.3; frames.json 에 전단 규약 판정 shear 추가). 누적 씬(상태 파일 include)이면 + state.npz,
               state_summary.json, frame0.npz(F0 패스) — 계약 esl_cumulative_input.md §7
  02_tstar/    tstar.json, history.csv, hotspots.csv, candidates.csv
  03_bc/       support.json
  04_esl/      u_rel.npz, u_rel.csv, f_eq.npz, f_eq.csv, esl_summary.json
  05_val/      validation.json(schema esl/validation/3, 판정 = 변위 4지표; + field: 전 요소 재현 정확도 요약,
               strain_ref, disp), validation.csv, compare.csv, compare_field.npz (계약 esl_p2_library.md §7.2),
               compare_disp.npz (full_solve 수행 시, 계약 esl_disp_primary.md §4);
               v0.24.3 출처별(esl_validate_sources.md §4.5·§6): sources.json(esl/val_sources/1 인덱스),
               <출처 dir>/(bforce·fint — 같은 파일 세트, validation.json 끝 src 블록). 루트 = 전 노드(legacy) 그대로
  06_export/   esl_cload.inc, esl_bcs.inc, esl_force.fem, f_eq.csv, u_rel.csv, reactions_321.csv,
               tstar_candidates.csv, hotspots.csv, validation.csv
  07_report/   report.html (자체 완결 Case 보고서, §5·§7.3)
  run.json

``--stage all`` 에서 report 단계가 실패해도 앞 단계 산출물·성공 상태는 유지된다(run.json stages.report = failed + 경고).
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
from esl import cumulative as _cum
from esl import val_metrics as _vm
from esl import val_src as _vs
from esl.errors import EslError
from esl.export import AUTO_BASE, all_ids, dof_flags, force_mask, plan_ids
from esl.export import csvout, optistruct, radioss
from esl.fsutil import atomic_replace
from esl.io import RESULT_FILES, SCALAR_SOURCES, decide_shear, pack_results, rad_eq, strain_source_of
from esl.io.results_csv import METRICS
from esl.io import bforce_csv as _bfcsv
from esl.io import bforce_ondemand as _bfod
from esl.io.backup import BACKUP_DIR, BACKUP_TS_FMT
from esl.mech import kabsch, strain, supports, tstar
from esl.mech.shell import ShellModel, solver_check_kwargs
from esl.rad import parse_rad, scan_includes
from esl.rad.parser import max_line_bytes_of
from esl.report import field as _field

STAGES = ("extract", "tstar", "esl", "validate", "export", "report")
# v0.12.0 검증 낙하(esl_scx_relay.md SR6): Case 파이프라인 밖 단계 — 워커가 esl.verify.stages.run_stage 로 실행
VERIFY_STAGES = ("vd_patch", "vd_compare")
EXPORT_TARGETS = ("radioss_inc", "fem", "csv")
D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT, D_REPORT = (
    "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report")
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
              iter_maxiter: int | None = None, **check) -> ShellModel:
        """check = solver_check_kwargs(solver 설정) — 해 수용 검사(resid_rel_cap·equil_tol_rel), 없으면 기본값."""
        return ShellModel(self.x0, self.conn, self.elem_type, self.thickness, self.E, self.nu,
                          drill_factor=drill_factor, backend=backend, iter_rtol=iter_rtol, iter_maxiter=iter_maxiter,
                          **check)

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
            atomic_replace(d, dst)
        os.makedirs(d, exist_ok=True)
        return self.guard(d)

    def backup_file(self, name: str) -> None:
        src = self.guard(self.p(name))
        if os.path.exists(src):
            atomic_replace(src, self._backup_target(name))

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


def _metric_series(hz: dict, factor: float, source: str = "max_strain") -> dict:
    """지표 이력 (F,H): max_strain = ε_eq(Max_Strain 텐서, 규약 보정), plastic_strain = epsp.
    대체 source(esl_strain_fallback.md §4): plastic_strain·max_stress 이면 max_strain 계열 = vm_hv 열(epsp·σ_vM)."""
    return {"max_strain": rad_eq(hz["eps"], hz["vm_hv"], factor, source),
            "plastic_strain": np.asarray(hz["epsp"], dtype=np.float64)}


STRAIN_FROM_STRESS = ("STRAIN_FROM_STRESS: h3d 에 변형률 결과가 없어 응력(Max_Stress σ_vM)으로 순위·t* 를 정함 — 판정 신뢰 낮음, "
                      "변형률 참고 지표(hotspot·전 요소 ε 비교·잡음 바닥 ε)는 생략")


def _source(meta: dict | None) -> str:
    """01_extract frames.json 의 strain source(옛 자료 = max_strain)."""
    return strain_source_of(meta)


def _esl_layers(ctx: Context, meta: dict | None = None) -> list:
    """검증 해 ε_eq 층: strain_tensor 의 외피 층(Lower/Upper·Layer n)이면 [bottom, top], 아니면 extract.layers (§4)."""
    if meta is None:
        try:
            meta = _frames_meta(ctx)
        except (EslError, OSError, ValueError):
            meta = {}
    sf = (meta or {}).get("strain_fallback") if isinstance(meta, dict) else None
    lay = sf.get("esl_layers") if isinstance(sf, dict) else None
    return list(lay) if lay else list(ctx.cfg["extract"]["layers"])


# ====================================================================== 누적 씬 (esl_cumulative_input.md §6·§7)
STATE_SCHEMA = "esl/state/1"
CUM_EPSP_FLOOR = 1e-6          # 소성 바닥: 비누적 안전망(h3d frame 0 소성 최대 > 이 값 → 경고, §6.2)·증분 소성 요소 수(§6.6)
_STATE_ARRAYS = ("node_from_state", "elem_from_state", "thk_state", "t0", "epsp")


def _warn_codes(ws) -> list[str]:
    out = []
    for w in ws:
        c = str(w).split(":", 1)[0].strip()
        if c.isupper() and c not in out:
            out.append(c)
    return out


def _extract_cumulative(ctx: Context, d: str, model, info: dict, factor: float) -> dict:
    """extract 끝(pack 후) 누적 진단 1회 → state.npz·state_summary.json (§6.1·§6.2·§7). 반환 요약."""
    st = model.state
    cu = _config.cumulative_settings(ctx.cfg)
    det = cu["detect"]
    eid = np.asarray(model.elem_id, np.int64)
    E = eid.size
    ep = st.get("epsp")
    aggs = {a: (np.asarray(ep.agg[a], np.float64) if ep is not None else np.zeros(E)) for a in _cum.AGGS}
    fz = _load_npz(os.path.join(d, "final.npz"))
    fin_ep = np.asarray(fz["epsp"], np.float64)
    fin_vm = np.asarray(fz["vm_hv"], np.float64)
    h0_ep = np.full(E, np.nan)
    h0_vm = np.full(E, np.nan)
    f0src = None
    p0 = os.path.join(d, "frame0.npz")
    if os.path.isfile(p0):
        z0 = _load_npz(p0)
        h0_ep, h0_vm = np.asarray(z0["epsp"], np.float64), np.asarray(z0["vm_hv"], np.float64)
        f0src = "frame0.csv"
    else:
        hz = _load_npz(os.path.join(d, "history.npz"))
        if hz["frame_index"].size and int(hz["frame_index"][0]) == 0:
            hp = _lookup_pos(eid, hz["elem_id"])
            ok = hp >= 0
            h0_ep[hp[ok]] = np.asarray(hz["epsp"][0], np.float64)[ok]
            h0_vm[hp[ok]] = np.asarray(hz["vm_hv"][0], np.float64)[ok]
            f0src = "history"
    agg, dg_ep = _cum.choose(aggs, h0_ep, fin_ep, det, cu["epsp_agg"], cu["h3d_epsp_mode"])
    prev = aggs[agg]
    dg_eq = _cum.diagnose(prev, h0_vm, fin_vm, det, cu["h3d_eq_mode"])
    ws = list(st.get("warnings") or [])
    for name, dg in (("소성(Plastic Strain)", dg_ep), ("총변형률(Max_Strain ε_eq)", dg_eq)):
        if dg["ambiguous"] and not dg["forced"]:
            ws.append(f"CUMULATIVE_AMBIGUOUS: h3d {name} 누적 여부 판정 불확실(r0={dg['r0']:.3g}, 일치 비율 "
                      f"{dg['mono']:.3g}, |S|={dg['n_S']}) — 증분으로 보고 이전 값을 더함(보수적)")
    if dg_ep["detected"] == "incremental" or dg_eq["detected"] == "cumulative":
        ws.append(f"CUMULATIVE_INFO: h3d 판정이 예상(소성 = 누적, 총변형률 = 증분)과 다름 — 소성 "
                  f"{dg_ep['detected']}, 총변형률 {dg_eq['detected']}")
    if f0src is None and ep is not None:
        ws.append("CUMULATIVE_INFO: frame 0 값이 없어(F0 패스·history frame 0 없음) 누적 판정 생략 — trivial/설정값")
    if info.get("frame0") is False and f0src == "history":
        ws.append("CUMULATIVE_INFO: frame0.csv 없음(PC 추출 등) — history H 요소의 frame 0 으로 판정")
    npz = {"elem_id": eid, "has": ep.has if ep is not None else np.zeros(E, bool),
           "npt": ep.npt if ep is not None else np.zeros(E, np.int16),
           "npg": ep.npg if ep is not None else np.zeros(E, np.int16),
           "thk_sta": ep.thk if ep is not None else np.full(E, np.nan),
           **{f"prev_{a}": aggs[a] for a in _cum.AGGS},
           "thk_state": np.asarray(st["thk_state"], np.float64), "t0": np.asarray(st["t0"], np.float64),
           "node_from_state": np.asarray(st["node_from_state"], bool),
           "elem_from_state": np.asarray(st["elem_from_state"], bool)}
    np.savez_compressed(ctx.f(d, "state.npz"), **npz)
    pos = prev[prev > 0]
    epsp_init = {"n_has": int(npz["has"].sum()), "n_missing": int(E - npz["has"].sum()),
                 "max": float(prev.max()) if E else 0.0, "p99": float(np.percentile(prev, 99)) if E else 0.0,
                 "prev_max": float(aggs["max"].max()) if E else 0.0, "n_pos": int(pos.size),
                 "inishe_subs": st.get("inishe_subs") or []}
    files = []
    for f in st["files"]:
        rec = dict(f)
        rec["sha256"] = sha256_file(f["path"]) if os.path.isfile(f["path"]) else None
        files.append(rec)
    summ = {"schema": STATE_SCHEMA, "files": files, "begin": st["begin"], "coord": {**st["coord"],
            "rad_coord_source": "rad:state"}, "elems": st["elems"], "thickness": st["thickness"],
            "thk_sta_mismatch": st.get("thk_sta_mismatch"), "epsp_init": epsp_init,
            "diagnosis": {"epsp": dg_ep, "eq": dg_eq}, "agg": agg, "frame0_source": f0src,
            "min_increment": float(cu["min_increment"]), "parse": st.get("parse"),
            "warnings": ws, "warning_codes": _warn_codes(ws), "created_at": _utcnow()}
    _write_json(ctx.f(d, "state_summary.json"), summ)
    ctx.warnings += [w for w in ws if w not in (st.get("warnings") or [])]
    short = {"enabled": True, "files": [{"name": os.path.basename(f["path"]), "kinds": f["kinds"],
                                         "runname": f.get("runname"), "size": f.get("size")} for f in files],
             "epsp_mode": dg_ep["mode"], "eq_mode": dg_eq["mode"], "agg": agg, "n_prev_elems": int(pos.size),
             "prev_max": epsp_init["max"], "prev_p99": epsp_init["p99"], "coord_source": st["coord"]["source"],
             "n_nodes_state": st["coord"]["n_nodes_state"], "n_nodes_rad": st["coord"]["n_nodes_rad"],
             "thickness": st["thickness"],
             "diagnosis": {k: {x: dg.get(x) for x in ("mode", "detected", "r0", "mono", "n_S", "forced")}
                           for k, dg in (("epsp", dg_ep), ("eq", dg_eq))},
             "warning_codes": summ["warning_codes"]}
    return {"short": short, "frames": {k: short[k] for k in ("enabled", "epsp_mode", "eq_mode", "agg",
                                                               "n_prev_elems")}, "frame0_source": f0src,
            "files": files}


def _cum_state(ctx: Context, model) -> dict | None:
    """tstar·validate 용 누적 정보(01_extract 파일만 읽음 — 단계 재개 규칙). 비누적이면 None."""
    sp = ctx.p(D_EXTRACT, "state_summary.json")
    zp = ctx.p(D_EXTRACT, "state.npz")
    if not (os.path.isfile(sp) and os.path.isfile(zp)):
        return None
    ss = _read_json(sp)
    z = _load_npz(zp)
    if not np.array_equal(z["elem_id"], model.elem_id):
        raise EslError("ID_MISMATCH", "state.npz elem_id 가 model.npz 와 다름 — extract 다시 실행")
    prev = _cum.prev_values(z, ss["agg"])
    return {"summary": ss, "prev": prev, "prev_eq": prev, "agg": ss["agg"],
            "modes": {"plastic_strain": ss["diagnosis"]["epsp"]["mode"],
                      "max_strain": ss["diagnosis"]["eq"]["mode"]},
            "min_increment": float(ss.get("min_increment", _config.cumulative_settings(ctx.cfg)["min_increment"]))}


# ====================================================================== S1 extract
def stage_extract(ctx: Context) -> dict:
    c = ctx.cfg["case"]
    ecfg = ctx.cfg["extract"]
    if not os.path.isfile(ctx.rad):
        raise EslError("INPUT_INVALID", f"rad 파일이 없음: {ctx.rad}")
    if not os.path.isdir(ctx.results):
        raise EslError("INPUT_INVALID", f"결과 CSV 폴더가 없음: {ctx.results}")
    cu = _config.cumulative_settings(ctx.cfg)
    model = parse_rad(ctx.rad, c["part_title"], match=c["part_title_match"],
                      max_include_depth=c["rad_include_max_depth"],
                      material_override=c["material_override"] or None,
                      include_path_map=c["include_path_map"] or None,
                      thickness_source=cu["thickness_source"], read_initial=cu["enabled"] != "off",
                      max_line_bytes=max_line_bytes_of(c),
                      state_max_npt=int(cu["max_npt"]), state_max_npg=int(cu["max_npg"]))
    cum_on = model.state is not None and cu["enabled"] != "off"
    ctx.protect(list(model.includes))          # include 폴더도 보호 → 겹치면 쓰기 전에 INPUT_INVALID
    d = ctx.fresh_dir(D_EXTRACT)
    for fn in ("model.npz", "model_meta.json", "final.npz", "history.npz", "strain_frames.npz", "disp.npz",
               "frames.json") + (("state.npz", "state_summary.json", "frame0.npz") if cum_on else ()):
        ctx.f(d, fn)
    save_model(d, model)
    info = pack_results(ctx.results, model, d, frame_stride=ecfg["frame_stride"],
                        coord_check=ctx.cfg.get("coord_check"), shear_convention=ecfg["shear_convention"],
                        dump=_config.dump_settings(ctx.cfg))
    ctx.warnings += list(getattr(model, "warnings", [])) + list(info.get("warnings", []))
    # v0.24.0 경계력 ESL 원자료(esl_bforce.md §2): done.json 에 bforce 가 있을 때만 01_extract/bforce.* (옛 추출물 = 쓰지 않음)
    bfx = _bfcsv.pack_bforce(ctx.results, model.node_id, d) if _config.bforce_settings(ctx.cfg)["enabled"] else None
    sfb = info.get("strain_fallback") or {}
    src = info.get("strain_source") or "max_strain"

    # 전단 규약(§7.1): 최종 프레임 전 요소의 HyperView vonMises 와 비교
    fz = _load_npz(os.path.join(d, "final.npz"))
    if src in SCALAR_SOURCES:
        # 텐서 열이 0(소성) 또는 응력 → 판정 생략(factor=1, 기록) — esl_strain_fallback.md §4
        sh = {"mode": ecfg["shear_convention"], "convention": "tensor", "factor": 1.0, "max_rel_mismatch": None,
              "mismatch": {"tensor": None, "engineering": None}, "median": {"tensor": None, "engineering": None},
              "n_used": 0, "rel_floor": None, "skipped": f"strain_source={src}"}
    else:
        sh = decide_shear(fz["vm_hv"], fz["eps"], ecfg["shear_convention"])
        if isinstance(sfb.get("shear"), dict):        # dump: 코어가 층별 원자료로 판정한 규약을 그대로(같은 결과)
            sh["dump"] = sfb["shear"]
    if src == "max_stress":
        ctx.warnings.append(STRAIN_FROM_STRESS)
    mm = sh["max_rel_mismatch"]
    if src in SCALAR_SOURCES:
        pass
    elif mm is None:
        ctx.warnings.append("전단 규약 판정 불가(vonMises 가 모두 0) — 텐서 규약으로 가정")
    elif mm > SHEAR_MISMATCH_WARN:
        ctx.warnings.append(f"ε_eq(§4 공식, {sh['convention']}) 와 HyperView vonMises 의 최대 상대 불일치 {mm:.3g} > "
                            f"{SHEAR_MISMATCH_WARN:g} (요소 {sh['n_used']}개, 중앙값 {sh['median'][sh['convention']]:.3g})")
    fpath = ctx.f(d, "frames.json")
    meta = _read_json(fpath)
    meta["shear"] = sh
    cs = None
    if cum_on:
        cs = _extract_cumulative(ctx, d, model, info, sh["factor"])
        meta["cumulative"] = cs["frames"]
        meta["frame0_source"] = cs["frame0_source"]
    _write_json(fpath, meta)
    if cum_on:
        mpath = ctx.f(d, "model_meta.json")
        mmeta = _read_json(mpath)
        mmeta.update(cumulative=True, state_summary="state_summary.json")
        _write_json(mpath, mmeta)
    elif model.state is not None:
        ctx.warnings.append("cumulative.enabled=off: 상태 파일을 일반 include 로 취급(좌표·두께 규칙만, 변형률 보정 없음)")
    else:
        hz0 = _load_npz(os.path.join(d, "history.npz"))
        if hz0["frame_index"].size and int(hz0["frame_index"][0]) == 0 and hz0["epsp"].size \
                and float(np.max(hz0["epsp"][0])) > CUM_EPSP_FLOOR:
            ctx.warnings.append(f"CUMULATIVE_STATE_NOT_INCLUDED: h3d 시작 시점(frame 0)에 소성 변형률이 있음(최대 "
                                f"{float(np.max(hz0['epsp'][0])):.3g}) — 누적 씬이면 rad 에 이전 런 상태 파일"
                                f"(.sta/.str) #include 필요")
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
    dump_mode = sfb.get("mode") == "dump"
    for name in RESULT_FILES + ("strain_raw.csv",) + _bfcsv.BF_FILES:
        p = os.path.join(ctx.results, name)
        if os.path.isfile(p):
            # dump 원자료(수십 GB 가능)는 크기·mtime 만(done.json 은 해시) — esl_strain_fallback.md Med2
            inputs["results_files"][name] = _fingerprint(p, not (dump_mode and name in ("strain_raw.csv", "disp.csv")))
    if cs is not None:
        inputs["state_files"] = [{"path": f["path"], "sha256": f["sha256"], "kinds": f["kinds"]} for f in cs["files"]]
    ctx.record["inputs"] = inputs
    et = np.asarray(model.elem_type)
    s = {"part_id": model.part_id, "part_title": model.part_title, "units_label": model.units_label,
         "n_nodes": int(model.node_id.size), "n_elems": int(model.elem_id.size),
         "n_quad": int(np.sum(et == 4)), "n_tria": int(np.sum(et == 3)), "n_frames": info["n_frames"],
         "n_hot": info["n_hot"], "frames_D": info["frames_D"], "candidate_frames": info["candidate_frames"],
         "shear": {"convention": sh["convention"], "mode": sh["mode"], "max_rel_mismatch": mm,
                   "median": sh["median"]},
         "mats": model.mats, "max_ids": model.max_ids, "coord_deviation": info.get("coord_deviation"),
         "conn_check": info.get("conn_check"), "strain_source": src,
         "strain_fallback": {k: sfb.get(k) for k in ("source", "type", "mode", "layers", "epsp_available", "dt_out",
                                                     "esl_layers")}}
    if cs is not None:
        s["cumulative"] = cs["short"]
    if bfx is not None:                           # v0.24.0: 찾은 경계력 결과 유형(없는 종류 = null)
        s["bforce"] = {k: (v.get("type") if isinstance(v, dict) else None) for k, v in (bfx.get("kinds") or {}).items()}
        ctx.echo(f"[extract] 경계력 ESL 결과 유형: {s['bforce']}")
    ctx.echo(f"[extract] 파트 {model.part_id} '{model.part_title}': 노드 {s['n_nodes']}, 요소 {s['n_elems']} "
             f"(QUAD {s['n_quad']}/TRIA {s['n_tria']}), 이력 프레임 {s['n_frames']}, H {s['n_hot']}요소, "
             f"후보 프레임 D {s['frames_D']}, 전단 {sh['convention']}, 변형률 source {src}"
             + (f" (vonMises 최대 불일치 {mm:.2e})" if mm is not None else ""))
    if cs is not None:
        k = cs["short"]
        ctx.echo(f"[extract] 누적 씬: 상태 파일 {[f['name'] for f in k['files']]}, 좌표 {k['coord_source']}, "
                 f"이전 소성 요소 {k['n_prev_elems']} (최대 {k['prev_max']:.4g}, 집계 {k['agg']}), h3d 소성 "
                 f"{k['epsp_mode']}·총변형률 {k['eq_mode']}")
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
    series = _metric_series(hz, factor, _source(meta))
    tclq = {"max_strain": np.asarray(hz["vm_hv"], np.float64), "plastic_strain": series["plastic_strain"]}
    fidx = hz["frame_index"].astype(np.int64)
    hid = hz["elem_id"]
    D = [int(x) for x in meta["frames_D"]]
    tD = dict(zip(D, meta["time_D"]))
    tcl_top_n = int(meta.get("top_n") or tcfg["top_n_times"])
    tcl_rtol = float(meta["reach_rtol"]) if meta.get("reach_rtol") is not None else rtol
    full = int(meta.get("frame_stride", 1)) == 1 and int(meta.get("n_frames_h3d", fidx.size)) == fidx.size
    cst = _cum_state(ctx, model)

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
            if cst is None:
                r = tstar.scan_reach(hz["time"], series[m], C, tcfg["top_n_times"], tcfg["top_k_hotspots"],
                                     tcfg["hotspot_min_dist"], rtol, time_window=(tw[0], tw[1]), exclude_mask=ex)
            else:
                cum_v, inc_v = _cum.series(series[m], cst["prev"][hp], cst["modes"][m])
                r = tstar.scan_reach_cum(hz["time"], cum_v, inc_v, C, tcfg["top_n_times"], tcfg["top_k_hotspots"],
                                         tcfg["hotspot_min_dist"], rtol, time_window=(tw[0], tw[1]),
                                         exclude_mask=ex, min_increment=cst["min_increment"])
        except EslError as exc:
            if m == metric:
                raise
            ctx.warnings.append(f"[{m}] t* 계산 불가: {exc.message}")
            out[m] = {"error": f"{exc.code}: {exc.message}", "tcl_check": check}
            continue
        cands = [{"rank": c["rank"], "frame_index": int(fidx[c["frame_pos"]]), "time": c["time"],
                  "elem_id": int(hid[c["elem_pos"]]), "value": c["value"], "eps_max": c["value"],
                  "in_D": int(fidx[c["frame_pos"]]) in tD,
                  **({"value_inc": c["value_inc"], "value_prev": c["value_prev"]} if cst is not None else {})}
                 for c in r["candidates"]]
        ts = dict(cands[0])
        adjusted = None
        if not ts["in_D"]:
            alt = next((c for c in cands if c["in_D"]), None)
            msg = (("CUMULATIVE_FRAME_NOT_EXTRACTED: " if cst is not None else "")
                   + f"[{m}] t* frame {ts['frame_index']} 이 후보 프레임 D {D} 에 없음(변위 없음)"
                   + (f" → D 안의 후보 frame {alt['frame_index']} 사용" if alt else ""))
            if alt is None and m == metric:
                raise EslError("FRAME_NOT_CANDIDATE", msg + " — TCL 을 다시 실행(-top_n 증가)하거나 --frame 으로 D 안에서 지정")
            ctx.warnings.append(msg)
            adjusted = {"from": ts["frame_index"], "to": alt["frame_index"] if alt else None}
            if alt is not None:
                ts = dict(alt)
        hots = [{"rank": h["rank"], "elem_id": int(hid[h["elem_pos"]]), "value": h["value"], "eps_eq": h["value"],
                 "rising": h["rising"], "centroid": h["centroid"],
                 **({"value_inc": h["value_inc"], "value_prev": h["value_prev"]} if cst is not None else {})}
                for h in r["hotspots"]]
        tkeys = ("frame_index", "time", "elem_id", "value") + (("value_inc", "value_prev") if cst is not None else ())
        out[m] = {"tstar": {k: ts[k] for k in tkeys},
                  "candidates": cands, "hotspots": hots, "adjusted": adjusted, "tcl_check": check,
                  "history": {"time": r["history"]["time"], "m": r["history"]["m"],
                              **({"m_inc": r["history"]["m_inc"]} if cst is not None else {})}}
        if cst is not None:
            n_x = int(r["n_excluded_no_increment"])
            out[m]["cumulative"] = {"mode": cst["modes"][m], "n_excluded_no_increment": n_x}

    sel_m = out[metric]
    auto = {**sel_m["tstar"], "eps_eq": sel_m["tstar"]["value"], "metric": metric, "source": "auto"}
    tj = {"schema": "esl/tstar/2", "metric": metric, "reach_rtol": rtol,
          "shear": meta.get("shear", {}).get("convention"),
          "frames_D": [{"frame_index": f, "time": tD[f]} for f in D],
          "metrics": {m: {k: v for k, v in rec.items() if k != "history"} for m, rec in out.items()},
          "auto": auto, "candidates": sel_m["candidates"], "hotspots": sel_m["hotspots"],
          "settings": dict(tcfg), "created_at": _utcnow()}
    if cst is not None:
        tj["cumulative"] = {"enabled": True, "epsp_mode": cst["modes"]["plastic_strain"],
                            "eq_mode": cst["modes"]["max_strain"], "agg": cst["agg"],
                            "n_prev_elems": int(np.sum(cst["prev"] > 0)), "min_increment": cst["min_increment"],
                            "basis": {"rank": "cumulative", "first_reach": "increment"}}
    for m, rec in out.items():
        if "history" in rec:
            tj["metrics"][m]["history"] = {"time": rec["history"]["time"], "m": rec["history"]["m"]}
            if "m_inc" in rec["history"]:
                tj["metrics"][m]["history"]["m_inc"] = rec["history"]["m_inc"]
    tj["selected"] = auto
    tj["selected"] = _select_frame(tj, ctx.frame)

    d = ctx.fresh_dir(D_TSTAR)
    _write_json(ctx.f(d, "tstar.json"), tj)
    fmt = ctx.csvfmt()
    hist_cols = [out[m]["history"]["m"] if "history" in out[m] else np.full(fidx.size, np.nan) for m in METRICS]
    if cst is None:
        csvout.write_csv(ctx.f(d, "history.csv"), ("frame_index", "time", "m_max_strain", "m_plastic_strain"),
                         zip(fidx.tolist(), hz["time"], *hist_cols), fmt)
        csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER,
                         ((x["rank"], x["elem_id"], x["value"], *x["centroid"]) for x in sel_m["hotspots"]), fmt)
        csvout.write_csv(ctx.f(d, "candidates.csv"),
                         ("metric", "rank", "frame_index", "time", "value", "elem_id", "in_D"),
                         ((m, x["rank"], x["frame_index"], x["time"], x["value"], x["elem_id"], x["in_D"])
                          for m in METRICS for x in out[m].get("candidates", [])), fmt)
    else:                                   # 누적 씬: 누적(value)·이전·이번(증분) 열 추가(§7)
        inc_cols = [out[m]["history"].get("m_inc", np.full(fidx.size, np.nan)) if "history" in out[m]
                    else np.full(fidx.size, np.nan) for m in METRICS]
        csvout.write_csv(ctx.f(d, "history.csv"), ("frame_index", "time", "m_max_strain", "m_plastic_strain",
                                                   "m_inc_max_strain", "m_inc_plastic_strain"),
                         zip(fidx.tolist(), hz["time"], *hist_cols, *inc_cols), fmt)
        csvout.write_csv(ctx.f(d, "hotspots.csv"), csvout.HOTSPOTS_HEADER + ("value_inc", "value_prev"),
                         ((x["rank"], x["elem_id"], x["value"], *x["centroid"], x["value_inc"], x["value_prev"])
                          for x in sel_m["hotspots"]), fmt)
        csvout.write_csv(ctx.f(d, "candidates.csv"),
                         ("metric", "rank", "frame_index", "time", "value", "elem_id", "in_D", "value_inc",
                          "value_prev"),
                         ((m, x["rank"], x["frame_index"], x["time"], x["value"], x["elem_id"], x["in_D"],
                           x["value_inc"], x["value_prev"])
                          for m in METRICS for x in out[m].get("candidates", [])), fmt)
    sel = tj["selected"]
    other = [m for m in METRICS if m != metric][0]
    o = out[other].get("tstar")
    ctx.echo(f"[tstar] t* = frame {sel['frame_index']} (time {sel['time']:.6g}, {sel['source']}, {metric} "
             f"first-reach), 값 {auto['value']:.4g} @ elem {auto['elem_id']}, 후보 {len(sel_m['candidates'])}개, "
             f"hotspot {len(sel_m['hotspots'])}개; {other}: "
             + (f"t* frame {o['frame_index']} (값 {o['value']:.4g})" if o else "없음")
             + f"; D {D}")
    if cst is not None:
        ts_ = sel_m["tstar"]
        ctx.echo(f"[tstar] 누적 기준: 누적 {ts_['value']:.4g} (이전 {ts_['value_prev']:.4g} + 이번 "
                 f"{ts_['value_inc']:.4g}), 이전 손상만(이번 증가 없음) "
                 f"{sel_m['cumulative']['n_excluded_no_increment']}개 제외")
    res = {"selected": sel, "auto": auto, "metric": metric,
           "tstar_by_metric": {m: out[m].get("tstar") for m in METRICS},
           "tcl_check": {m: out[m]["tcl_check"]["match"] for m in METRICS},
           "n_candidates": len(sel_m["candidates"]), "n_hotspots": len(sel_m["hotspots"])}
    if cst is not None:
        res["cumulative"] = {m: out[m].get("cumulative") for m in METRICS}
    return res


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
    src = _source(meta)
    series = _metric_series(hz, factor, src)
    v = series[tcfg["metric"]]
    eqh = series["max_strain"]
    ex = _exclude_mask(ctx, model.elem_id, hz["elem_id"])
    cst = _cum_state(ctx, model)
    eps_rad = rad_eq(sz["eps"][int(fd[0])], sz["vm_hv"][int(fd[0])], factor, src)          # (E,)
    if cst is not None:
        # 누적 씬(§6.6, Q3 가정 확정 A): ESL u_rel 은 이번 낙하분 → Radioss 쪽도 증분 계열로 비교
        cum_v, v = _cum.series(v, cst["prev"][hp], cst["modes"][tcfg["metric"]])
        _, eqh = _cum.series(eqh, cst["prev_eq"][hp], cst["modes"]["max_strain"])
        _, eps_rad = _cum.series(eps_rad, cst["prev_eq"], cst["modes"]["max_strain"])
        no_inc = ~(v[-1] > cst["min_increment"])
        ex = no_inc if ex is None else (ex | no_inc)
        fin = cum_v[-1]
    else:
        fin = v[-1]
    fr = tstar.first_reach(v, rtol)
    first = None
    for e in np.lexsort((np.arange(fin.size), -fin)):
        if fr[e] == f and fin[e] > 0 and (ex is None or not ex[e]):
            first = int(e)
            break
    C = model.centroids()
    hs = tstar.rising_hotspots(v, f, C[hp], tcfg["top_k_hotspots"], tcfg["hotspot_min_dist"], rtol,
                               exclude_mask=ex, first=first)
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
    layers = _esl_layers(ctx)
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
        sm = model.shell(scfg["drill_factor"], scfg["backend"], scfg["iter_rtol"], scfg["iter_maxiter"],
                         **solver_check_kwargs(scfg))
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
                            f"(참고 기준 초과)")

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
            "solver": solver_stats(sm), "strain_source": _source(_frames_meta(ctx)), "tag": ctx.tag,
            "created_at": _utcnow()}
    _write_json(ctx.f(d, "esl_summary.json"), summ)
    ctx.echo(f"[esl] frame {sel['frame_index']}: 강체회전 {kinfo['rot_deg']:.2f}°, ΣF=|{np.linalg.norm(sumF):.3e}|, "
             f"Σ|F|={sum_abs:.3e}, 평형 오차 {eq_rel:.2e} (모멘트 {mom_rel:.2e}), "
             f"3-2-1 {[(int(nid[i]), dd) for i, dd in sup]} ({mode})")
    ctx.echo(f"[esl] 잡음 바닥({noise['disp_precision']}, δ={noise['delta']:.3e}, n={noise['n_samples']}): "
             f"force_rel={noise['force_rel']:.3e} (경고 >{vcfg['noise_force_rel_warn']:g}), "
             f"hotspot_strain_rel={noise['hotspot_strain_rel']:.3e} (≤{vcfg['noise_strain_rel_max']:g})")
    noise_short = {k: noise[k] for k in ("disp_precision", "delta", "n_samples", "force_rel", "hotspot_strain_rel")}
    plastic = _plastic_diag(ctx, model, int(sel["frame_index"]))       # v0.24.0 소성 진단(esl_fint.md §4 — 계산 변경 없음)
    bshort = _bforce_esl(ctx, model, d, sel, u, u_rel, R, sup, sm, F, plastic)   # v0.24.0 경계력 ESL(기존 파일 불변 — 새 파일만)
    fshort = _fint_esl(ctx, model, d, sel, u, u_rel, R, sup, sm, F, plastic)     # v0.24.0 내력 ESL(esl_fint.md §3)
    jshort = _jig_esl(ctx, model, d, sel, u_rel, sup, sm)                         # v0.24.4 지그 ESL 3방식(esl_jig_case.md §5.2)
    return {**jshort, "bforce": bshort, "fint": fshort, "plastic": plastic, "noise": noise_short, "frame": sel, "rot_deg": kinfo["rot_deg"], "rms_def": kinfo["rms_def"], "max_def": kinfo["max_def"],
            "sum_f_norm": float(np.linalg.norm(sumF)), "sum_abs_f": sum_abs, "equilibrium_rel": eq_rel,
            "moment_rel": mom_rel, "supports": sup_rec["supports"], "support_mode": mode,
            "solver": solver_stats(sm), "strain_source": summ["strain_source"]}


# ====================================================================== v0.24.0 경계력 ESL (esl_bforce.md §4)
BF_JSON, BF_NPZ = "bforce.json", "bforce.npz"


def _bf_text(code: str, **kw) -> str:
    msg = {"BF_RHO_DEFAULT": "재료 밀도 없음 → 설정 default_rho {rho:g} 로 deck 질량 근사(재료 {mats})",
           "BF_MASS_APPROX": "deck 밀도·두께로 근사한 질량으로 관성 항 계산 — 질량 스케일링 추가 질량 미포함",
           "BF_NO_ACC": "가속도 결과 없음 — 관성 항 없이 접촉력만",
           "BF_NO_MASS": "질량 없음 — 관성 항 생략",
           "BF_RECON_POOR": "기준 재현 미달: MAC {mac} (기준 ≥ {mac_min:g}), umax 오차 {err} (기준 ≤ {err_max:g})",
           "BF_REACTION": "3-2-1 반력 합 / Σ|F| = {rel:.3g} > {th:g} (하중 불평형)",
           "BF_FINT_CHECK": "FINT 검산 상대 오차 {rel:.3g} > {th:g}",
           "BF_SIGN_SUSPECT": "CONT 부호 의심: 불평형 ‖ΣF‖/Σ‖F‖ {rel:.3g} (부호 반전 시 {rel_flip:.3g}), ā {ag} g (반전 시 {ag_flip} g) — "
                              "bead_doe.bforce.signs.cont 확인(결과는 바꾸지 않음)",
           "BF_FAILED": "경계력 ESL 계산 실패({err}) — 전 노드 ESL 결과는 그대로",
           # v0.24.0 보완 내력 ESL(esl_fint.md §1·§2)
           "FINT_UNBALANCED": "내력 합 잔차 ‖ΣF‖/Σ‖F‖ {rel:.3g} · 모멘트 {mrel:.3g} > 허용치 {tol:g} — 공유 노드 혼입·추출 누락 의심{relief}",
           "FINT_SHARED_NODES": "대상 파트 노드 {n}개를 다른 부품 요소가 공유(파트 {parts}) — 그 노드 내력에 다른 부품 힘이 섞임(그대로 사용)",
           "FINT_NO_MASS": "질량 없음 — 관성 이완 생략",
           "FINT_RECON_POOR": "기준 재현 미달: MAC {mac} (기준 ≥ {mac_min:g}), umax 오차 {err} (기준 ≤ {err_max:g})",
           "FINT_REACTION": "3-2-1 반력 합 / Σ|F| = {rel:.3g} > {th:g} (기준 형상 잔차)",
           "FINT_FAILED": "내력 ESL 계산 실패({err}) — 전 노드 ESL 결과는 그대로",
           # v0.24.2 경계력 원자료 ESL 때 보충(esl_bforce_ondemand.md §5) — 경계력·내력 같은 code·reason, detail = 워커 CAUSE_TEXT
           "BF_EXTRACT_FAILED": "경계력 원자료 보충 실패 — 프레임 {frame}: {detail}. ③ ESL 을 다시 계산하면 다시 시도합니다",
           "BF_EXTRACT_SKIPPED": "경계력 원자료 보충 생략 — 프레임 {frame}: {detail}"}.get(code, code)
    return f"{code}: " + msg.format(**kw)


# 선택 프레임 경계력 원자료가 01_extract 에 없고 보충 기록도 없을 때(BF_NO_DATA·FINT_NO_DATA) 사유 — 실제 원인별(v0.24.2).
# old = 비덤프 추출인데 bforce 자료 없음(v0.24.0 이전 TCL·bf_on 0 — v0.24.1 문구 그대로), dump = 덤프 방식 추출(TCL 덤프 경로는
# 경계력을 추출하지 않음), frame = 경계력 자료는 있으나 선택 프레임이 없음(보충 병합 뒤 다른 프레임 선택 등).
_BF_NO_DATA_WHY = {
    ("bforce", "old"): "추출물에 경계력 결과 없음(v0.24.0 이전 추출이거나 bf_on 0) — h3d 추출을 다시 실행",
    ("fint", "old"): "추출물에 경계력·내력 결과 없음(v0.24.0 이전 추출이거나 bf_on 0) — h3d 추출을 다시 실행",
    ("bforce", "dump"): "덤프 방식 추출(변형률 텐서 전 프레임)에는 경계력 결과가 없음 — h3d 입력 Case 는 ③ ESL 계산 때 "
                        "선택 프레임만 보충(bforce.on_demand)",
    ("fint", "dump"): "덤프 방식 추출(변형률 텐서 전 프레임)에는 경계력·내력 결과가 없음 — h3d 입력 Case 는 ③ ESL 계산 때 "
                      "선택 프레임만 보충(bforce.on_demand)",
    ("bforce", "frame"): "선택 프레임 {frame} 의 경계력 결과가 추출물에 없음(있는 프레임 {frames}) — h3d 입력 Case 는 ③ ESL "
                         "계산 때 보충(bforce.on_demand)",
    ("fint", "frame"): "선택 프레임 {frame} 의 경계력·내력 결과가 추출물에 없음(있는 프레임 {frames}) — h3d 입력 Case 는 ③ ESL "
                       "계산 때 보충(bforce.on_demand)",
}


def _bf_missing(ctx: Context, frame: int) -> dict | None:
    """선택 프레임의 경계력 원자료 "없음" 판정(경계력·내력 공용 — esl_bforce_ondemand.md §5). 있으면 None.

    없으면 {code, reason(경계력)|why(원인 키), warn}: 이 작업(ctx.tag)의 보충 시도가 실패·생략이면 그 code
    (BF_EXTRACT_FAILED·SKIPPED)·문구(경계력·내력 같은 reason, warn = 경고 문구), 기록이 없으면 BF_NO_DATA 계열(원인 키 why)."""
    xd = ctx.p(D_EXTRACT)
    if _bfcsv.has_frame(xd, frame):
        return None
    n = _bfod.note(xd, frame, ctx.tag)
    if n is not None and n["code"] in ("BF_EXTRACT_FAILED", "BF_EXTRACT_SKIPPED"):
        w = _bf_text(n["code"], frame=frame, detail=n["detail"])
        return {"code": n["code"], "reason": w[len(n["code"]) + 2:], "warn": w}
    doc = _bfcsv.read_doc(xd)
    if doc is not None and _bfcsv.doc_frames(doc):
        why = "frame"
    else:
        try:
            dump = ((_frames_meta(ctx).get("strain_fallback") or {}).get("mode")) == "dump"
        except (OSError, ValueError):
            dump = False
        why = "dump" if dump else "old"
    return {"code": None, "why": why, "frames": _bfcsv.doc_frames(doc)}


def _bf_no_data_why(kind: str, miss: dict, frame: int) -> str:
    return _BF_NO_DATA_WHY[(kind, miss["why"])].format(frame=frame, frames=miss["frames"])


def _plastic_diag(ctx: Context, model: StoredModel, frame_index: int) -> dict:
    """소성 진단(esl_fint.md §4): strain_frames.npz epsp(t*) → 면적 비율·최대(εᵖ > bforce.plastic_eps_min). 없음 = status none."""
    from esl.mech import bforce as bfm
    from esl.mech.mass import elem_area_normal
    try:
        eps_min = float(_config.bforce_settings(ctx.cfg)["plastic_eps_min"])
        p = ctx.p(D_EXTRACT, "strain_frames.npz")
        if not os.path.isfile(p) or ((_frames_meta(ctx).get("strain_fallback") or {}).get("epsp_available")) is False:
            return {"status": "none"}
        with np.load(p, allow_pickle=False) as z:
            if "epsp" not in z.files:
                return {"status": "none"}
            hit = np.flatnonzero(np.asarray(z["frame_index"]).astype(np.int64) == int(frame_index))
            if hit.size != 1:
                return {"status": "none"}
            ep = np.asarray(z["epsp"][int(hit[0])], dtype=np.float64)
        A, _ = elem_area_normal(model.x0, model.conn, model.elem_type)
        return bfm.plastic_diag(ep, A, eps_min)
    except (EslError, OSError, KeyError, ValueError) as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _nodal_recon(ctx: Context, bc: dict, model: StoredModel, sm: ShellModel, sup, u_rel, F_bal, doc: dict, texts: list,
                 pre: str):
    """기준 재현(경계력·내력 공용 — 같은 3-2-1·같은 설정): K₀ u = F_bal → 파트 전 노드 Kabsch 강체 제거 → u_rel 과 MAC·umax 오차·반력.
    doc["recon"]·경고(<pre>_RECON_POOR·<pre>_REACTION)를 채우고 u_val(생략이면 None)을 돌려준다."""
    from esl.mech import bforce as bfm
    fs = full_solve_decision(ctx, sm, int(model.elem_id.size))
    if not fs["run"]:
        doc["recon"] = {"status": "skipped", "reason": fs["reason"]}
        return None
    u6, Rr = _solver_call(ctx, sm.solve, F_bal, list(sup))
    u_val, _, _, _ = kabsch.remove_rigid(model.x0, u6[:, :3])
    rep = bfm.recon_report(u_rel, u_val, Rr, F_bal)
    poor = (rep["mac"] is None or rep["mac"] < float(bc["recon_mac_min"])
            or rep["umax_err"] is None or abs(rep["umax_err"]) > float(bc["recon_umax_err_max"]))
    doc["recon"] = {"status": "poor" if poor else "ok", "mac_min": float(bc["recon_mac_min"]), **rep}
    if poor:
        doc["warnings"].append({"code": f"{pre}_RECON_POOR"})
        texts.append(_bf_text(f"{pre}_RECON_POOR", mac="–" if rep["mac"] is None else f"{rep['mac']:.3f}",
                              mac_min=float(bc["recon_mac_min"]),
                              err="–" if rep["umax_err"] is None else f"{rep['umax_err']:+.1%}",
                              err_max=float(bc["recon_umax_err_max"])))
    if rep["reaction_rel"] > float(bc["reaction_warn_rel"]):
        doc["warnings"].append({"code": f"{pre}_REACTION", "rel": rep["reaction_rel"]})
        texts.append(_bf_text(f"{pre}_REACTION", rel=rep["reaction_rel"], th=float(bc["reaction_warn_rel"])))
    return u_val


def _bforce_esl(ctx: Context, model: StoredModel, d: str, sel: dict, u, u_rel, R, sup, sm: ShellModel, F_full,
                plastic: dict | None = None) -> dict:
    """선택 프레임의 경계력 원자료 → 04_esl/bforce.json(esl/bforce/1)·bforce.npz + 기준 재현(같은 3-2-1). 예외는 ESL 단계를
    실패시키지 않는다(BF_FAILED). 반환 = 단계 요약(ESL 실행 forces.bforce). v0.24.0 보완: 접촉력 전용(FINT 는 full 검산만 —
    D-0.24.0-BF-12), plastic = 소성 진단(json 에 그대로)."""
    from esl.mech import bforce as bfm
    from esl.mech.mass import lumped_mass
    bc = _config.bforce_settings(ctx.cfg)
    if not bc["enabled"]:
        return {"grade": None, "code": "BF_DISABLED"}
    fi = int(sel["frame_index"])
    miss = _bf_missing(ctx, fi)
    if miss is not None:                          # 선택 프레임 원자료 없음 = 04_esl 에 쓰지 않음(산출물 집합 불변)
        if miss["code"]:                          # v0.24.2 보충 실패·생략(경고 1번 — 내력은 넣지 않음)
            ctx.warnings.append(miss["warn"])
            return {"grade": "none", "code": miss["code"], "reason": miss["reason"]}
        return {"grade": "none", "code": "BF_NO_DATA", "reason": _bf_no_data_why("bforce", miss, fi)}
    data, xdoc = _bfcsv.frame_data(ctx.p(D_EXTRACT), fi)
    have = sorted(k for k, v in data.items() if v is not None)
    if bfm.grade_of(have) == "none":
        why = f"접촉력 결과 유형이 h3d 에 없음(있는 종류 {have})"
        doc = {"schema": bfm.SCHEMA, "grade": "none", "code": "BF_NO_DATA", "reason": why,
               "kinds": {k: data.get(k) is not None for k in bfm.KINDS},
               "result_types": None if xdoc is None else xdoc.get("kinds")}
        _write_json(ctx.f(d, BF_JSON), doc)
        return {"grade": "none", "code": "BF_NO_DATA", "reason": why}
    try:
        mesh = {"x0": model.x0, "conn": model.conn, "elem_type": model.elem_type, "thickness": model.thickness}
        rho_e, miss = bfm.rho_per_elem(model.elem_mid, model.mats, float(bc["default_rho"]))
        m_deck = lumped_mass(mesh, rho_e)
        out = bfm.build(model.x0, u, data, m_deck, R=R, u_rel=u_rel, use_inertia=bool(bc["use_inertia"]),
                        signs=bc["signs"], balance=bc["balance"], g=float(bc["g_mm_s2"]), F_full=F_full)
        doc = out["doc"]
        doc["rho_default_mats"] = miss
        doc["mass_deck_total"] = float(m_deck.sum())
        doc["frame"] = {"frame_index": int(sel["frame_index"]), "time": float(sel["time"])}
        doc["rot_deg"] = float(kabsch.rotation_deg(R))
        doc["result_types"] = None if xdoc is None else xdoc.get("kinds")
        nid = model.node_id
        doc["max_f"] = {"node_id": int(nid[doc["max_f"]["idx"]]), "mag": doc["max_f"]["mag"]}
        texts = []
        if miss and doc["mass_source"] == "deck":
            doc["warnings"].append({"code": "BF_RHO_DEFAULT", "mats": miss})
            texts.append(_bf_text("BF_RHO_DEFAULT", rho=float(bc["default_rho"]), mats=miss))
        texts += [_bf_text(w["code"]) for w in doc["warnings"] if w["code"] in ("BF_MASS_APPROX", "BF_NO_ACC", "BF_NO_MASS")]
        for w in doc["warnings"]:
            if w["code"] == bfm.CODE_SIGN:
                f_ = lambda v: "–" if v is None else f"{v:.3g}"      # noqa: E731
                texts.append(_bf_text(w["code"], rel=w["force_rel"], rel_flip=w["force_rel_flip"], ag=f_(w["abar_g"]),
                                      ag_flip=f_(w["abar_g_flip"])))
        if doc["fint_check_rel"] is not None and doc["fint_check_rel"] > float(bc["fint_check_warn_rel"]):
            doc["warnings"].append({"code": "BF_FINT_CHECK", "rel": doc["fint_check_rel"]})
            texts.append(_bf_text("BF_FINT_CHECK", rel=doc["fint_check_rel"], th=float(bc["fint_check_warn_rel"])))
        # 기준 재현: 같은 3-2-1 로 K₀ u = F_bal → 파트 전 노드 Kabsch 강체 제거 → u_rel 과 비교
        u_val = _nodal_recon(ctx, bc, model, sm, sup, u_rel, out["F_bal"], doc, texts, "BF")
        doc["plastic"] = plastic if plastic is not None else {"status": "none"}
        ctx.warnings += texts
        _write_json(ctx.f(d, BF_JSON), doc)
        z = {"node_id": nid, "f": out["F_bal"], "f_raw": out["F_raw"], "m": out["m"] if out["m"] is not None
             else np.zeros(nid.size)}
        if u_val is not None:
            z["u_val"] = u_val
        np.savez_compressed(ctx.f(d, BF_NPZ), **z)
    except Exception as exc:                                    # noqa: BLE001 — 경계력 때문에 ESL 단계 실패 금지
        err = exc.code if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"[:300]
        ctx.warnings.append(_bf_text("BF_FAILED", err=err))
        _write_json(ctx.f(d, BF_JSON), {"schema": "esl/bforce/1", "grade": bfm.grade_of(have), "code": "BF_FAILED",
                                        "reason": err})
        return {"grade": bfm.grade_of(have), "code": "BF_FAILED", "reason": err}
    rc = doc.get("recon") or {}
    ctx.echo(f"[esl] 경계력 ESL 등급 {doc['grade']}({doc['formula']}), 질량 {doc['mass_source']}, Σ|F| {doc['sum_abs']:.3e}"
             f" (전 노드 ×{(doc['sum_abs_ratio_full'] or 0):.3g}), ā {doc['abar_g']:.3g} g·보정 {doc['corr_rel']:.1%}, "
             f"재현 {rc.get('status')} MAC {rc.get('mac')}")
    return {"grade": doc["grade"], "mass_source": doc["mass_source"], "sum_abs": doc["sum_abs"],
            "sum_abs_ratio_full": doc["sum_abs_ratio_full"], "abar_g": doc["abar_g"], "corr_rel": doc["corr_rel"],
            "eq_force_rel": doc["eq_raw"]["ref"]["force_rel"], "eq_moment_rel": doc["eq_raw"]["ref"]["moment_rel"],
            "recon": rc.get("status"), "mac": rc.get("mac"), "umax_err": rc.get("umax_err"),
            "reaction_rel": rc.get("reaction_rel"), "limits": list(doc["limits"]),
            "limit_text": bfm.limit_text(doc["limits"]),
            "sign_suspect": bool((doc.get("sign_check") or {}).get("suspect"))}


# ====================================================================== v0.24.0 내력 ESL (esl_fint.md §1~§3)
FI_JSON, FI_NPZ = "fint.json", "fint.npz"
FINT_NO_DATA_TEXT = "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가"


def _fint_esl(ctx: Context, model: StoredModel, d: str, sel: dict, u, u_rel, R, sup, sm: ShellModel, F_full,
              plastic: dict | None = None) -> dict:
    """선택 프레임 FINT → 04_esl/fint.json(esl/bforce/1 + source fint)·fint.npz + 기준 재현(같은 3-2-1). 경계력 ESL 과 독립 —
    예외는 ESL 단계를 실패시키지 않는다(FINT_FAILED). 반환 = 단계 요약(ESL 실행 forces.fint)."""
    from esl.mech import bforce as bfm
    from esl.mech.mass import lumped_mass
    from esl.rad.shared import safe_node_links
    bc = _config.bforce_settings(ctx.cfg)
    fc = bc["fint"]
    if not bc["enabled"] or not fc["enabled"]:
        return {"grade": None, "code": "FINT_DISABLED"}
    fi = int(sel["frame_index"])
    miss = _bf_missing(ctx, fi)
    if miss is not None:                          # 선택 프레임 원자료 없음 = 04_esl 에 쓰지 않음(산출물 집합 불변)
        if miss["code"]:                          # v0.24.2 보충 실패·생략 = 경계력과 같은 code·reason
            return {"grade": "none", "code": miss["code"], "reason": miss["reason"]}
        return {"grade": "none", "code": "FINT_NO_DATA", "reason": _bf_no_data_why("fint", miss, fi)}
    data, xdoc = _bfcsv.frame_data(ctx.p(D_EXTRACT), fi)
    kinds = {k: data.get(k) is not None for k in bfm.KINDS}
    if data.get("fint") is None:
        _write_json(ctx.f(d, FI_JSON), {"schema": bfm.SCHEMA, "source": bfm.FINT_SCHEMA_SOURCE, "grade": "none",
                                        "code": "FINT_NO_DATA", "reason": FINT_NO_DATA_TEXT, "kinds": kinds,
                                        "result_types": xdoc.get("kinds"), "plastic": plastic or {"status": "none"}})
        return {"grade": "none", "code": "FINT_NO_DATA", "reason": FINT_NO_DATA_TEXT}
    try:
        links = {"status": "skipped"}
        if fc["shared_nodes"]:
            c = ctx.cfg["case"]
            links = safe_node_links(ctx.rad, model.part_id, model.node_id, model.x0,
                                    include_path_map=c["include_path_map"] or None,
                                    max_include_depth=c["rad_include_max_depth"], max_line_bytes=max_line_bytes_of(c))
        m, msrc, miss = None, None, []
        if fc["balance"] == "inertia_relief":            # 질량은 관성 이완을 쓸 때만(h3d MASS > deck 근사)
            if data.get("mass") is not None:
                m, msrc = data["mass"], "h3d"
            else:
                rho_e, miss = bfm.rho_per_elem(model.elem_mid, model.mats, float(bc["default_rho"]))
                m = lumped_mass({"x0": model.x0, "conn": model.conn, "elem_type": model.elem_type,
                                 "thickness": model.thickness}, rho_e)
                msrc = "deck"
        out = bfm.fint_build(model.x0, u, data["fint"], m, mass_source=msrc, R=R, u_rel=u_rel, sign=bc["signs"]["fint"],
                             balance=fc["balance"], tol_force=float(fc["unbalanced_force_rel"]),
                             tol_moment=float(fc["unbalanced_moment_rel"]), links=links, kinds=kinds,
                             g=float(bc["g_mm_s2"]), F_full=F_full)
        doc = out["doc"]
        nid = model.node_id
        doc["frame"] = {"frame_index": int(sel["frame_index"]), "time": float(sel["time"])}
        doc["rot_deg"] = float(kabsch.rotation_deg(R))
        doc["result_types"] = xdoc.get("kinds")
        doc["max_f"] = {"node_id": int(nid[doc["max_f"]["idx"]]), "mag": doc["max_f"]["mag"]}
        if msrc == "deck" and doc["fint"]["balance_applied"] == "inertia_relief":
            doc["rho_default_mats"] = miss
        texts = []
        for w in doc["warnings"]:
            if w["code"] == bfm.CODE_UNBAL:
                texts.append(_bf_text(w["code"], rel=w["force_rel"], mrel=w["moment_rel"], tol=w["tol_force"],
                                      relief=" — 관성 이완 적용" if doc["fint"]["balance_applied"] == "inertia_relief" else ""))
            elif w["code"] == bfm.CODE_SHARED:
                texts.append(_bf_text(w["code"], n=w["n"], parts=",".join(sorted((w.get("by_part") or {}).keys()))))
            elif w["code"] == "FINT_NO_MASS":
                texts.append(_bf_text(w["code"]))
        u_val = _nodal_recon(ctx, bc, model, sm, sup, u_rel, out["F_bal"], doc, texts, "FINT")
        doc["plastic"] = plastic if plastic is not None else {"status": "none"}
        ctx.warnings += texts
        _write_json(ctx.f(d, FI_JSON), doc)
        z = {"node_id": nid, "f": out["F_bal"], "f_raw": out["F_raw"],
             "m": out["m"] if out["m"] is not None else np.zeros(nid.size)}
        if u_val is not None:
            z["u_val"] = u_val
        np.savez_compressed(ctx.f(d, FI_NPZ), **z)
    except Exception as exc:                                    # noqa: BLE001 — 내력 ESL 때문에 ESL 단계 실패 금지
        err = exc.code if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"[:300]
        ctx.warnings.append(_bf_text("FINT_FAILED", err=err))
        _write_json(ctx.f(d, FI_JSON), {"schema": bfm.SCHEMA, "source": bfm.FINT_SCHEMA_SOURCE, "grade": "fint",
                                        "code": "FINT_FAILED", "reason": err})
        return {"grade": "fint", "code": "FINT_FAILED", "reason": err}
    rc = doc.get("recon") or {}
    fi = doc["fint"]
    ctx.echo(f"[esl] 내력 ESL ({doc['formula']}, s {doc['signs']['fint']:+g} {doc['fint_sign_source']}), Σ|F| {doc['sum_abs']:.3e}, "
             f"잔차 {fi['residual']['force_rel']:.2e}/{fi['residual']['moment_rel']:.2e}, 공유 노드 "
             f"{(fi['shared_nodes'] or {}).get('n_shared', '–')}, 재현 {rc.get('status')} MAC {rc.get('mac')}")
    return {"grade": "fint", "sum_abs": doc["sum_abs"], "sum_abs_ratio_full": doc["sum_abs_ratio_full"],
            "abar_g": doc["abar_g"], "corr_rel": doc["corr_rel"],
            "eq_force_rel": doc["eq_raw"]["ref"]["force_rel"], "eq_moment_rel": doc["eq_raw"]["ref"]["moment_rel"],
            "res_force_rel": fi["residual"]["force_rel"], "res_moment_rel": fi["residual"]["moment_rel"],
            "unbalanced": fi["unbalanced"], "balance_applied": fi["balance_applied"],
            "shared_status": (fi["shared_nodes"] or {}).get("status"),
            "n_shared": (fi["shared_nodes"] or {}).get("n_shared"), "n_rot": fi["rot_nodes"]["n"],
            "recon": rc.get("status"), "mac": rc.get("mac"), "umax_err": rc.get("umax_err"),
            "reaction_rel": rc.get("reaction_rel"), "limits": list(doc["limits"]),
            "limit_text": bfm.limit_text(doc["limits"]), "sign": doc["signs"]["fint"]}


# ====================================================================== v0.24.4 지그 ESL 3방식 (esl_jig_case.md §5)
JIG_FIXED_DIR, JIG_PREP_JSON, JIG_SURF_NPZ, JIG_BASIS_NPZ = "jig_fixed", "jig_prep.json", "jig_surf.npz", "jig_basis.npz"
CASE_JIG_SCHEMA, CASE_JIG_BASIS_SCHEMA, JIG_SURF_SCHEMA = "esl/case_jig/1", "esl/case_jig_basis/1", "esl/case_jig_surf/1"
JIG_PREP_CODE = {"failed": "JIG_FIXED_FAILED", "skipped": "JIG_FIXED_SKIPPED", "disabled": "JIG_DISABLED"}
_JIG_SURF_ARRAYS = ("x", "node_id", "tri", "tri_part", "tri_thick")


class _JigStop(Exception):
    """공유 단계에서 세 행을 같은 code 로 멈춤(unavailable — 계산 예외 JIG_FAILED 와 구별). files = 진단 json 을 쓸지."""

    def __init__(self, code: str, reason: str, files: bool, extra: dict | None = None):
        super().__init__(code)
        self.code, self.reason, self.files, self.extra = code, reason, files, extra or {}


def _jig_text(code: str, **kw) -> str:
    from esl.io import messages as _msg
    return _msg.text(code, **kw)


def _jig_reason(code: str, **kw) -> str:
    """문구(resources/doe_messages.json — 스터디와 같은 원본)의 사유 부분(코드 접두 없음)."""
    return _jig_text(code, **kw)[len(code) + 2:]


def _jig_prep_note(ctx: Context) -> dict | None:
    """워커 tie 준비 시도 기록(01_extract/jig_prep.json — esl_jig_case.md §5.1, bf_ondemand 기록과 같은 형식
    {attempts: [{job_id, status, code, detail}]}, 단일 사전도 허용). 이 작업(tag — 없으면 마지막 시도)의 마지막 시도가 ok 가 아니면
    {code, detail}(code = 기록 code, 없으면 status → JIG_PREP_CODE), 아니면 None."""
    p = ctx.p(D_EXTRACT, JIG_PREP_JSON)
    if not os.path.isfile(p):
        return None
    try:
        doc = _read_json(p)
    except (OSError, ValueError):
        return None
    atts = doc.get("attempts") if isinstance(doc, dict) else None
    atts = [a for a in (atts if isinstance(atts, list) else [doc]) if isinstance(a, dict)]
    if ctx.tag is not None:
        atts = [a for a in atts if str(a.get("job_id", a.get("tag"))) == str(ctx.tag)]
    if not atts or atts[-1].get("status") == "ok":
        return None
    a = atts[-1]
    code = str(a.get("code") or JIG_PREP_CODE.get(str(a.get("status")), "JIG_FIXED_FAILED"))
    return {"code": code, "detail": str(a.get("detail") or a.get("status") or "")}


def _jig_mesh(model: StoredModel) -> dict:
    return {"x0": model.x0, "conn": model.conn, "elem_type": model.elem_type, "thickness": model.thickness, "E": model.E,
            "nu": model.nu, "node_id": model.node_id}


def _jig_surface(ctx: Context, model: StoredModel, J: dict, fit, warns: list):
    """deck 다른 부품 표면(``esl.rad.surface.other_surfaces`` — 읽기만) + 캐시 01_extract/jig_surf.npz(키 = starter·include stat·
    part·상자·여유·상한). 읽기 실패·상한 초과 = 경고 후 패치로(스터디 _jig_surface 와 같은 규칙). 반환 (surf | None, 사유, 요약)."""
    from esl.mech import jig as jg
    from esl.rad import surface as srf
    t0 = _time.perf_counter()
    X = model.x0[np.asarray(fit, bool)]
    pad = float(J["contact_gap_mm"]) + jg.max_edge(_jig_mesh(model))
    cc = ctx.cfg["case"]
    files = []
    for f in [ctx.rad, *model.includes]:
        try:
            st = os.stat(f)
            files.append([os.path.abspath(f), int(st.st_size), int(st.st_mtime_ns)])
        except OSError:
            files.append([os.path.abspath(f), None, None])
    key = json.dumps({"schema": JIG_SURF_SCHEMA, "files": files, "part": int(model.part_id),
                      "lo": [float(v) for v in X.min(axis=0)], "hi": [float(v) for v in X.max(axis=0)], "pad": pad,
                      "max_tris": int(J["max_surf_tris"]), "include_path_map": cc.get("include_path_map") or None,
                      "depth": int(cc["rad_include_max_depth"])}, sort_keys=True, ensure_ascii=False)
    cpath = ctx.p(D_EXTRACT, JIG_SURF_NPZ)
    surf, cached = None, False
    if os.path.isfile(cpath):
        try:
            with np.load(cpath, allow_pickle=False) as z:
                if str(z["key"]) == key:
                    surf = {k: np.asarray(z[k]) for k in _JIG_SURF_ARRAYS}
                    surf.update(json.loads(str(z["meta"])))
                    cached = True
        except (OSError, ValueError, KeyError):
            surf = None
    if surf is None:
        try:
            surf = srf.other_surfaces(ctx.rad, int(model.part_id), X.min(axis=0), X.max(axis=0),
                                      include_path_map=cc.get("include_path_map") or None,
                                      max_include_depth=int(cc["rad_include_max_depth"]),
                                      max_line_bytes=max_line_bytes_of(cc), max_tris=int(J["max_surf_tris"]), pad_mm=pad)
        except EslError as exc:
            code = "JIG_SURF_TOO_LARGE" if exc.code == "JIG_SURF_TOO_LARGE" else "JIG_SURF_UNAVAILABLE"
            warns.append(_jig_text(code, err=exc.code))
            return None, "surf_failed", {"status": "failed", "code": code, "err": exc.code}
        except (OSError, KeyError, ValueError) as exc:
            warns.append(_jig_text("JIG_SURF_UNAVAILABLE", err=type(exc).__name__))
            return None, "surf_failed", {"status": "failed", "code": "JIG_SURF_UNAVAILABLE", "err": type(exc).__name__}
        try:                                               # 캐시 쓰기(실패해도 계산은 계속 — 다음 ESL 이 다시 읽음)
            tmp = ctx.guard(ctx.p(D_EXTRACT, "jig_surf.tmp.npz"))
            meta = {k: surf[k] for k in ("thickness_known", "n_parts", "n_shell", "n_solid_faces", "n_skipped", "seconds")
                    if k in surf}
            np.savez_compressed(tmp, key=np.asarray(key), meta=np.asarray(json.dumps(_jsonable(meta))),
                                **{k: np.asarray(surf[k]) for k in _JIG_SURF_ARRAYS})
            atomic_replace(tmp, ctx.guard(cpath))
        except OSError as exc:
            ctx.warnings.append(f"지그 deck 표면 캐시를 쓰지 못함({type(exc).__name__}) — 다음 ESL 때 다시 읽음")
    info = {"status": "ok", "cached": cached, "n_tris": int(np.asarray(surf["tri"]).shape[0]),
            "n_parts": surf.get("n_parts"), "n_shell": surf.get("n_shell"), "n_solid_faces": surf.get("n_solid_faces"),
            "thickness_known": surf.get("thickness_known"), "seconds": round(_time.perf_counter() - t0, 3)}
    return surf, None, info


def _arr_sha(z: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(z):
        a = np.ascontiguousarray(z[k])
        h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
        h.update(a.tobytes())
    return h.hexdigest()


def _jig_shared(ctx: Context, model: StoredModel, J: dict, sup, sm: ShellModel, warns: list, infos: list,
                tm: dict) -> dict:
    """공유 단계(§5.2-2·3): tie 노드 J → 구속 법선·3-2-1 면내 → rigid_free → deck 표면·영역 → 공유 분해(열 factor own ∧ hard)·모드·
    하중 기저·기저 응답(+ 3-2-1 면내 반력) → 04_esl/jig_basis.npz 배열. 세 행 공통으로 멈출 사유 = _JigStop."""
    from esl.io import fixed_scan as fxs
    from esl.mech import jig as jg
    from esl.mech import jig_bc
    t0 = _time.perf_counter()
    mesh = _jig_mesh(model)
    X0, nid = model.x0, model.node_id
    N = nid.size
    fdir = ctx.p(D_EXTRACT, JIG_FIXED_DIR)
    if not os.path.isfile(os.path.join(fdir, fxs.SCAN_JSON)):
        note = _jig_prep_note(ctx)
        if note is None:
            raise _JigStop("JIG_NOT_PREPARED", _jig_reason("JIG_NOT_PREPARED"), False)
        raise _JigStop(note["code"], _jig_reason(note["code"], detail=note["detail"]), False)
    try:
        fx = fxs.read_fixed(fdir)
    except EslError as exc:
        raise _JigStop("JIG_FIXED_FAILED", _jig_reason("JIG_FIXED_FAILED", detail=f"{exc.code}: {exc.message}"[:300]),
                       False) from None
    bits = 0
    for k in J["fix_kinds"]:
        bits |= 1 << fxs.FIXED_KINDS.index(k)
    selj = jg.select_jig_nodes(mesh, np.asarray(fx["node_id"], dtype=np.int64),
                               kind_mask=np.asarray(fx["kind_mask"], dtype=np.int64), kind_bits=bits)
    det = selj["detail"] or {}
    fix = {"source": "fixed_scan", "kinds": list(J["fix_kinds"]), "n_jig": int(selj["idx"].size),
           "n_comp": int(selj["n_comp"]), "n_missing": int(det.get("n_missing", 0))}
    if selj["code"] is not None:
        raise _JigStop(selj["code"], _jig_reason(selj["code"], n_comp=det.get("n_comp", selj["n_comp"]),
                                                 bad_comp_nodes=det.get("bad_comp_nodes", [])), True, {"fix": fix})
    Jidx = np.asarray(selj["idx"], dtype=np.int64)
    spread = jg.support_spread(X0, Jidx)
    fix.update(jig_std=spread["jig_std"], part_std=spread["part_std"])
    omega = np.ones(N, bool)
    fit = omega.copy()
    fit[Jidx] = False
    td = str(J["tie_dofs"])
    tie = jig_bc.tie_rows(mesh, Jidx, td, kink_deg=float(J["normal_kink_deg"]))
    aux = jig_bc.aux_rows(X0, [(int(i), str(dd)) for i, dd in sup], tie, td, dup_deg=float(J["aux321_dup_deg"]))
    bm = jig_bc.basis_method()
    BC0 = jig_bc.build_bc(jig_bc.METHODS[bm], tie, aux, np.zeros((N, 3)))
    rf = jig_bc.rigid_free(X0, jig_bc.components(mesh), BC0)
    if rf["rigid_free"] > 0:
        bad = [c for c in rf["per_comp"] if c["free"] > 0]
        raise _JigStop("JIG_SUPPORT_DEGENERATE",
                       _jig_reason("JIG_SUPPORT_DEGENERATE", n_comp=len(rf["per_comp"]),
                                   bad_comp_nodes=[c["n_nodes"] for c in bad]) + f" — rigid_free {rf['rigid_free']}",
                       True, {"fix": fix, "rigid_free": int(rf["rigid_free"])})
    tm["tie"] = round(_time.perf_counter() - t0, 3)
    if spread["tie_spread"] is not None and spread["tie_spread"] < float(J["tie_spread_min"]):
        warns.append(_jig_text("JIG_SUPPORT_WEAK", tie_spread=f"{spread['tie_spread']:.3g}",
                               tie_spread_min=f"{float(J['tie_spread_min']):g}"))
    surf, why, surf_info = _jig_surface(ctx, model, J, fit, warns)
    tm["surf"] = (surf_info or {}).get("seconds")
    t1 = _time.perf_counter()
    wts = jg.node_weights(mesh)
    rs = jg.select_regions(mesh, fit, Jidx, surf, gap_mm=float(J["contact_gap_mm"]), knn=int(J["knn"]),
                           chunk_nodes=int(J["chunk_nodes"]), max_regions=int(J["max_regions"]),
                           min_regions=int(J["min_regions"]), min_nodes=int(J["min_region_nodes"]),
                           min_area_mm2=float(J["min_region_area_mm2"]), patch_count=int(J["patch_count"]), weights=wts,
                           surf_reason=why)
    tm["regions"] = round(_time.perf_counter() - t1, 3)
    if rs["fill_reason"] is not None:
        warns.append(_jig_text("JIG_REGION_FALLBACK", reason=rs["fill_reason"], n_contact=rs["n_contact"],
                               n_patch=rs["n_patch"]))
    t1 = _time.perf_counter()
    h0 = _solver_call(ctx, jig_bc.factorize, sm, BC0)
    tm["factor"] = round(_time.perf_counter() - t1, 3)
    t1 = _time.perf_counter()
    n_req = int(J["n_modes"])
    mdoc: dict[str, Any] = {"n_req": n_req, "n_conv": 0, "sigma": float(J["modes_sigma"]), "lam": [], "hz": [],
                            "rho_t_used": float(J["rho_t_mm3"]), "hz_321": None, "hz_ratio": None, "ok": True}
    g = lam = None
    if n_req > 0:
        try:
            md = _solver_call(ctx, lambda: jig_bc.modes(h0, wts, n_req, float(J["rho_t_mm3"]), sigma=float(J["modes_sigma"]),
                                                        tol=float(J["modes_tol"]), maxiter=int(J["modes_maxiter"])))
            g, lam = md["g"], np.asarray(md["lam"], dtype=np.float64)
            mdoc.update(n_conv=int(md["n_conv"]), lam=[float(v) for v in lam], hz=[float(v) for v in md["hz"]])
            if not md.get("ok", True):
                mdoc.update(ok=False, err=str(md.get("err")))
                infos.append(_jig_text("JIG_MODES_FAILED", stage="jig", err=md.get("err"), n_conv=int(md["n_conv"])))
        except EslError as exc:
            if exc.code != "JIG_MODES_FAILED":
                raise
            d_ = getattr(exc, "detail", None) or {}
            mdoc.update(ok=False, err=str(d_.get("err") or exc.code))
            infos.append(_jig_text("JIG_MODES_FAILED", stage="jig", err=d_.get("err") or exc.code,
                                   n_conv=int(d_.get("n_conv", 0))))
    if bool(J["modes_ref321"]) and lam is not None and lam.size:
        try:                                               # 정보: 3-2-1 구속 모드 대비 지그 모드 주파수(스터디 _jig_modes 와 같은 뜻)
            m_ = jg.lumped_mass(wts, float(J["rho_t_mm3"]))
            f3 = np.unique(np.asarray([6 * int(p) + int(ch) - 1 for p, dd in sup for ch in str(dd)], dtype=np.int64))
            m3 = jg.jig_modes(sm.K(), jg.mass_diag6(m_), f3, n_req, float(J["modes_sigma"]), tol=float(J["modes_tol"]),
                              maxiter=int(J["modes_maxiter"]))
            mdoc["hz_321"] = [float(v) for v in m3["hz"]]
            mdoc["hz_ratio"] = float(mdoc["hz"][0] / mdoc["hz_321"][0]) if mdoc["hz"] and mdoc["hz_321"][0] > 0 else None
        except EslError as exc:
            if exc.code != "JIG_MODES_FAILED":
                raise
            infos.append(_jig_text("JIG_MODES_FAILED", stage="321", err=exc.code, n_conv=0))
    tm["modes"] = round(_time.perf_counter() - t1, 3)
    t1 = _time.perf_counter()
    basis = jg.load_basis(mesh, rs["regions"], wts, omega, body_force=bool(J["body_force"]),
                          tangential=bool(J["basis_tangential"]), modes=g)
    BR0 = _solver_call(ctx, jig_bc.basis_response, h0, basis, fit, BC0)
    tm["basis"] = round(_time.perf_counter() - t1, 3)
    if basis["n_normal_free"]:
        infos.append(_jig_text("JIG_NORMAL_FREE", n=int(basis["n_normal_free"])))
    if BR0["null_cols"]:
        infos.append(_jig_text("JIG_BASIS_NULL", n=len(BR0["null_cols"])))
    z = {"node_id": nid, "jig_idx": Jidx, "omega": omega, "tie_node": np.asarray(tie["node"], dtype=np.int64),
         "tie_dir": np.asarray(tie["dir"], dtype=np.float64).reshape(-1, 3),
         "aux_node": np.asarray(aux["node"], dtype=np.int64), "aux_dir": np.asarray(aux["dir"], dtype=np.float64).reshape(-1, 3),
         "col_kind": np.asarray(basis["col_kind"], dtype=np.int8), "reg_ptr": basis["reg_ptr"], "reg_node": basis["reg_node"],
         "reg_w": basis["reg_w"], "reg_dir": basis["reg_dir"], "reg_sign": basis["reg_sign"], "reg_kind": basis["reg_kind"],
         "reg_part": basis["reg_part"], "node_area": np.asarray(wts["area"], dtype=np.float64)}
    if basis["body_w"] is not None:
        z["body_w"] = np.asarray(basis["body_w"], dtype=np.float64)
    if basis["mode_f"] is not None:
        z["mode_f"] = np.asarray(basis["mode_f"], dtype=np.float64)
        z["mode_lam"] = np.asarray(lam, dtype=np.float64)
        z["mode_rho_t"] = np.asarray([float(J["rho_t_mm3"])], dtype=np.float64)
    regs = []
    for k, rg in enumerate(rs["regions"]):
        contact = int(rg["kind"]) == jg.REGION_CONTACT
        regs.append({"id": k, "kind": jg.KIND_NAME.get(int(rg["kind"]), str(rg["kind"])),
                     "part": int(rg["part"]) if contact else None, "n_nodes": int(np.asarray(rg["nodes"]).size),
                     "area_mm2": float(rg["area"]), "center": [float(v) for v in rg["center"]],
                     "normal": [float(v) for v in basis["reg_dir"][k][0]], "sign": int(basis["reg_sign"][k])})
    an = np.asarray(aux["node"], dtype=np.int64)
    shared = {
        "fix": fix, "tie_spread": spread["tie_spread"], "normals": tie["normals"],
        "aux321": {"nodes": [int(nid[i]) for i in aux["nodes"]], "rows": [[int(nid[n]), [float(v) for v in dd]]
                                                                           for n, dd in zip(an, np.asarray(aux["dir"]))],
                   "n_dup": int(aux["n_dup"]), "plane": aux["plane"]},
        "rigid_free": int(rf["rigid_free"]), "regions_from": rs["regions_from"], "n_contact": int(rs["n_contact"]),
        "n_patch": int(rs["n_patch"]),
        "surf": None if surf_info is None else {**surf_info, "n_contact_nodes": int(rs["n_contact_nodes"]),
                                                "n_found": int(rs.get("n_found", rs["n_contact"]))},
        "fill_reason": rs["fill_reason"], "regions": regs, "nb": int(basis["nb"]), "modes": mdoc,
        "basis_cfg": {"body_force": bool(J["body_force"]), "tangential": bool(J["basis_tangential"]),
                      "w_inplane": float(J["w_inplane"]), "reg_force": float(J["reg_force"]),
                      "reg_modes": float(J["reg_modes"]), "ridge": float(J["ridge"])}}
    return {"mesh": mesh, "J": Jidx, "fit": fit, "omega": omega, "tie": tie, "aux": aux, "BC0": BC0, "h0": h0, "BR0": BR0,
            "basis": basis, "wts": wts, "z": z, "doc": shared, "td": td}


def _jig_bc_text(td: str, sh: dict) -> dict:
    """진단 json bc 블록(④ 조건 문구 SUPPORT_TEXT["jig"] 자리 값 — val_src.support_text)."""
    from esl.mech import jig_bc
    return {"tie_dofs": td, "tie_text": jig_bc.TIE_DOFS[td]["text"], "n_jig": int(sh["J"].size),
            "n_tie_rows": int(np.asarray(sh["tie"]["node"]).size), "n_aux": int(np.asarray(sh["aux"]["node"]).size)}


def _jig_method(ctx: Context, model: StoredModel, d: str, J: dict, m: str, sh: dict, u_rel, sm: ShellModel,
                h, BR, BC, tg: dict, k) -> tuple[dict, dict]:
    """한 방식(§5.2-4·5): 맞춤(3-2-1 면내 반력 0 제약)·응답·재현(파트 Kabsch vs u_rel)·판정 → 04_esl/<src>.json·.npz. 반환 (요약, doc)."""
    from esl.mech import bforce as bfm
    from esl.mech import jig_bc
    t0 = _time.perf_counter()
    row = jig_bc.METHODS[m]
    src = row["src"]
    X0, nid = model.x0, model.node_id
    r = _solver_call(ctx, lambda: jig_bc.run_method(
        h, sh["basis"], BR["U"], tg["u_tgt"], BC, sh["fit"], sh["wts"], jig_idx=sh["J"], ridge=float(J["ridge"]),
        w_inplane=float(J["w_inplane"]), reg_force=float(J["reg_force"]), reg_modes=float(J["reg_modes"]),
        active_tol=float(J["active_tol"]), rc_basis=BR["rc_aux"]))
    t_fit = _time.perf_counter() - t0
    u_val, _, _, _ = kabsch.remove_rigid(X0, r["u"][:, :3])
    Rt = np.array(r["R"], dtype=np.float64, copy=True)
    if np.asarray(BC["sp_node"]).size:
        np.add.at(Rt, np.asarray(BC["sp_node"], dtype=np.int64), np.asarray(r["fs"])[:, None] * np.asarray(BC["sp_dir"]))
    rec = bfm.recon_report(u_rel, u_val, Rt, r["F"])
    rep = r["report"]
    fl = jig_bc.flags(m, rep, aux_rel=float(r["aux_reaction_rel"]), th=J)
    label = _vs.LABEL.get(src, src)
    limits = list(fl["limits"]) + [c for c in fl["info"] if _vs.LIMIT_CLASS.get(c)]
    lkw = {"aux_reaction_rel": f"{r['aux_reaction_rel']:.3g}", "aux_reaction_warn": f"{float(J['aux_reaction_warn']):g}"}
    limit_text = [_jig_reason(c, **lkw) for c in limits]
    texts = []
    for w in fl["warnings"]:
        if w == "JIG_FIT_POOR":
            texts.append(_jig_text(w, detail=f"{label}: MAC {rep['mac']:.3f}(기준 ≥ {float(J['mac_min']):g}), umax 오차 "
                                             f"{rep['umax_err']:.1%}(기준 ≤ {float(J['umax_err_max']):g})"))
        elif w == "JIG_TIE_RELATIVE":
            texts.append(_jig_text(w, tie_rel=f"{rep['tie_rel']:.3g}", tie_rel_warn=f"{float(J['tie_rel_warn']):g}"))
        else:
            texts.append(_jig_text(w, label=label, work_eff=f"{rep['work_eff']:.3g}", F_sum_abs=f"{rep['F_sum_abs']:.4g}"))
    info = [_jig_text(c, **lkw) for c in fl["info"]]
    en = {**r["energy"], "aux_reaction_rel": float(r["aux_reaction_rel"])}
    sp = None
    if row["tie_stiff"] == "spring":
        kk = np.asarray(BC["sp_k"], dtype=np.float64)
        sp = {"k_mode": J["spring_k_mode"], "alpha": float(J["spring_alpha"]), "k_value": J["spring_k_value"],
              "k_stats": {"min": float(kk.min()), "median": float(np.median(kk)), "max": float(kk.max())} if kk.size else None,
              "alpha_scan": []}
    fit = {kk_: rep[kk_] for kk_ in ("mac", "umax_tgt", "umax_fit", "umax_err", "err_p95", "resid_rel", "work_eff",
                                      "cancel_rel", "F_sum_abs", "n_active")}
    fit.update(tie_rel=rep["tie_rel"] if row["tie_rel_warn"] else None, rot_deg=float(tg["rot_deg"]),
               with_modes=rep["with_modes"], without_modes=rep["without_modes"], modes=rep["modes"], body=rep["body"],
               forces=[{kk_: f[kk_] for kk_ in ("region", "F_n", "F_t1", "F_t2", "F", "active")} for f in rep["forces"]],
               aux_eq=r["aux_eq"], n_bound_active=int(r["fit"]["n_bound_active"]))
    recon = {"status": "ok" if (rec["mac"] is not None and rec["mac"] >= float(J["mac_min"]) and rec["umax_err"] is not None
                                and abs(rec["umax_err"]) <= float(J["umax_err_max"])) else "poor",
             "mac_min": float(J["mac_min"]), **rec,
             "support_rel": float(np.linalg.norm(Rt, axis=1).sum() / max(float(np.linalg.norm(r["F"], axis=1).sum()), 1e-300))}
    t_tot = round(_time.perf_counter() - t0, 3)
    doc = {"schema": CASE_JIG_SCHEMA, "source": src, "method": m, "method_name": row["name"], "tie_dofs": sh["td"],
           "status": "ok", "code": None, "reason": None, **sh["doc"], "bc": _jig_bc_text(sh["td"], sh),
           "fit": fit, "recon": recon, "energy": en, "spring": sp, "limits": limits, "limit_text": limit_text,
           "warnings": [t.split(":", 1)[0] for t in texts], "warning_text": texts, "info": [t.split(":", 1)[0] for t in info],
           "info_text": info, "seconds": {"fit": round(t_fit, 3), "total": t_tot}}
    _write_json(ctx.f(d, f"{src}.json"), doc)
    zz = {"node_id": nid, "f": np.asarray(r["F"], dtype=np.float64), "a": np.asarray(r["a"], dtype=np.float64),
          "u_val": np.asarray(u_val, dtype=np.float64), **jig_bc.save_bc(BC), "jig_idx": sh["J"],
          "basis_sha": np.asarray(sh["basis_sha"])}
    np.savez_compressed(ctx.f(d, f"{src}.npz"), **zz)
    ctx.warnings.extend(texts)
    ctx.echo(f"[esl] {label}({jig_bc.TIE_DOFS[sh['td']]['text']} {int(sh['J'].size)} + 3-2-1 면내 "
             f"{int(np.asarray(sh['aux']['node']).size)}): 맞춤 MAC {rep['mac']:.3f}, 재현 MAC "
             f"{'–' if rec['mac'] is None else format(rec['mac'], '.3f')}, umax 오차 "
             f"{'–' if rec['umax_err'] is None else format(rec['umax_err'], '+.1%')}, 3-2-1 면내 반력비 "
             f"{r['aux_reaction_rel']:.2e}, C_mix {en['C_mix']:.4g}" + (f" · 한계 {limits}" if limits else ""))
    summ = {"status": "ok", "code": None, "reason": None, "method": m, "tie_dofs": sh["td"], "n_jig": int(sh["J"].size),
            "n_regions": len(sh["doc"]["regions"]), "n_contact": sh["doc"]["n_contact"], "n_patch": sh["doc"]["n_patch"],
            "mac": rec["mac"], "umax_err": rec["umax_err"], "fit_mac": rep["mac"], "work_eff": rep["work_eff"],
            "rigid_free": sh["doc"]["rigid_free"], "aux_reaction_rel": float(r["aux_reaction_rel"]),
            "C_mix": en["C_mix"], "E": en["E"], "recon": recon["status"], "limits": limits, "limit_text": limit_text,
            "seconds": t_tot}
    return summ, doc


def _jig_unavail(code: str, reason: str, *, m: str, td: str | None) -> dict:
    return {"status": "unavailable", "code": code, "reason": reason, "method": m, "tie_dofs": td}


def _jig_esl(ctx: Context, model: StoredModel, d: str, sel: dict, u_rel, sup, sm: ShellModel) -> dict:
    """Case 지그 ESL 3방식(esl_jig_case.md §5.2): 설정·tie 준비 → 공유 단계(J·법선·3-2-1 면내·영역·분해·모드·기저) → 방식마다
    (METHODS 열로 BC·분해 선택 — 같은 구속 패턴이면 공유 분해) → 04_esl/jig_basis.npz·<src>.json·<src>.npz. 반환 = {src: 요약}
    (ESL 실행 forces.<src>). 실패 격리: 준비·공유 단계 = 세 행 같은 code, 방식 단계 = 그 행만 JIG_FAILED, 예외가 ESL 단계·
    full·bforce·fint 를 바꾸지 않는다(새 파일만)."""
    from esl.mech import jig_bc
    t_all = _time.perf_counter()
    J = _config.jig_settings(ctx.cfg)
    rows = list(jig_bc.METHODS)
    td = str(J.get("tie_dofs"))
    if not J["enabled"]:
        rs_ = _jig_reason("JIG_DISABLED", detail="jig.enabled")
        return {jig_bc.METHODS[m]["src"]: _jig_unavail("JIG_DISABLED", rs_, m=m, td=td) for m in rows}
    methods = [m for m in jig_bc.methods_of(J) if m in jig_bc.METHODS]
    out: dict[str, dict] = {}
    for m in rows:
        if m not in methods:
            out[jig_bc.METHODS[m]["src"]] = _jig_unavail("JIG_DISABLED", _jig_reason("JIG_DISABLED", detail="jig.methods"),
                                                         m=m, td=td)
    if not methods:
        return {jig_bc.METHODS[m]["src"]: out[jig_bc.METHODS[m]["src"]] for m in rows}
    warns: list[str] = []
    infos: list[str] = []
    tm: dict[str, Any] = {}
    sh = None
    try:
        jig_bc.check_cfg(J)
        sh = _jig_shared(ctx, model, J, sup, sm, warns, infos, tm)
    except _JigStop as st:
        ctx.warnings.extend(warns)
        for m in methods:
            src = jig_bc.METHODS[m]["src"]
            out[src] = _jig_unavail(st.code, st.reason, m=m, td=td)
            if st.files:
                _write_json(ctx.f(d, f"{src}.json"), {"schema": CASE_JIG_SCHEMA, "source": src, "method": m,
                                                      "tie_dofs": td, "status": "unavailable", "code": st.code,
                                                      "reason": st.reason, **st.extra, "warnings": [], "info": []})
        ctx.echo(f"[esl] 지그 ESL 불가 {st.code}: {st.reason}")
        return {jig_bc.METHODS[m]["src"]: out[jig_bc.METHODS[m]["src"]] for m in rows}
    except Exception as exc:                                    # noqa: BLE001 — 지그 때문에 ESL 단계 실패 금지
        err = exc.code if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"[:300]
        reason = _jig_reason("JIG_FAILED", stage="shared", err=err)
        ctx.warnings.extend(warns)
        ctx.warnings.append(_jig_text("JIG_FAILED", stage="shared", err=err))
        for m in methods:
            src = jig_bc.METHODS[m]["src"]
            out[src] = _jig_unavail("JIG_FAILED", reason, m=m, td=td)
            _write_json(ctx.f(d, f"{src}.json"), {"schema": CASE_JIG_SCHEMA, "source": src, "method": m, "tie_dofs": td,
                                                  "status": "unavailable", "code": "JIG_FAILED", "reason": reason,
                                                  "warnings": [], "info": []})
        return {jig_bc.METHODS[m]["src"]: out[jig_bc.METHODS[m]["src"]] for m in rows}
    ctx.warnings.extend(warns)
    z = sh.pop("z")
    sh["basis_sha"] = _arr_sha(z)
    np.savez_compressed(ctx.f(d, JIG_BASIS_NPZ), schema=np.asarray(CASE_JIG_BASIS_SCHEMA), **z,
                        sha256=np.asarray(sh["basis_sha"]))
    sh["doc"]["info"] = infos
    sh["doc"]["shared_warnings"] = [t.split(":", 1)[0] for t in warns]
    sh["doc"]["seconds_shared"] = tm
    sha0 = jig_bc.pattern_sha(sh["BC0"])
    prep = []
    for m in methods:                                          # BC(값·스프링) 먼저 — 공유 분해를 쓰는 방식부터 풀고 분해를 놓음
        row = jig_bc.METHODS[m]
        try:
            tg = jig_bc.target(row["frame"], model.x0, u_rel, sh["J"], sh["fit"])
            k = None
            if row["tie_stiff"] == "spring":
                k = jig_bc.spring_k(sm, sh["tie"], mode=str(J["spring_k_mode"]), alpha=float(J["spring_alpha"]),
                                    value=J["spring_k_value"])
            BC = jig_bc.build_bc(row, sh["tie"], sh["aux"], tg["u_tgt"], k=k)
            prep.append((m, tg, BC, k, jig_bc.pattern_sha(BC) == sha0, None))
        except Exception as exc:                                # noqa: BLE001
            prep.append((m, None, None, None, True, exc))
    prep.sort(key=lambda x: 0 if x[4] else 1)
    for m, tg, BC, k, shared, err0 in prep:
        src = jig_bc.METHODS[m]["src"]
        h = None
        try:
            if err0 is not None:
                raise err0
            if shared:
                h, BR = sh["h0"], sh["BR0"]
            else:
                if sh.get("h0") is not None:                   # 공유 분해 방식은 끝남 — 메모리 피크 = 분해 1개
                    sh["h0"] = None
                t1 = _time.perf_counter()
                h = _solver_call(ctx, jig_bc.factorize, sm, BC)
                BR = _solver_call(ctx, jig_bc.basis_response, h, sh["basis"], sh["fit"], BC)
                tm[f"factor_{src}"] = round(_time.perf_counter() - t1, 3)
            out[src], _doc = _jig_method(ctx, model, d, J, m, sh, u_rel, sm, h, BR, BC, tg, k)
        except Exception as exc:                                # noqa: BLE001 — 그 방식 행만
            err = exc.code if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"[:300]
            reason = _jig_reason("JIG_FAILED", stage=m, err=err)
            ctx.warnings.append(_jig_text("JIG_FAILED", stage=m, err=err))
            out[src] = _jig_unavail("JIG_FAILED", reason, m=m, td=sh["td"])
            for f_ in (f"{src}.npz",):                         # 부분 파일 없음(json 이 상태 원본)
                p_ = ctx.p(D_ESL, f_)
                if os.path.isfile(p_):
                    os.remove(ctx.guard(p_))
            _write_json(ctx.f(d, f"{src}.json"), {"schema": CASE_JIG_SCHEMA, "source": src, "method": m,
                                                  "tie_dofs": sh["td"], "status": "unavailable", "code": "JIG_FAILED",
                                                  "reason": reason, **{k_: sh["doc"][k_] for k_ in ("fix", "rigid_free")},
                                                  "warnings": [], "info": []})
        finally:
            h = None
    sh["h0"] = None
    tot = round(_time.perf_counter() - t_all, 3)
    for m in methods:
        out[jig_bc.METHODS[m]["src"]]["seconds_shared"] = tm
        out[jig_bc.METHODS[m]["src"]]["seconds_all"] = tot
    return {jig_bc.METHODS[m]["src"]: out[jig_bc.METHODS[m]["src"]] for m in rows}


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


VERDICT_SCHEME = _vm.VERDICT_SCHEME          # 계약 esl_disp_primary.md: 판정 = 변위 4지표, 변형률은 참고(값 원본 = val_metrics)
VALIDATION_SCHEMA = _vm.VALIDATION_SCHEMA
_FAIL_REASON = _vm.FAIL_REASON


def _disp_noise_delta(ctx: Context, noise: dict | None, model: StoredModel, frame_index: int):
    """변위 잡음 δ (계약 §3.2). S4 ``noise.delta`` 를 그대로 쓰고, 없으면(예전 S4) 같은 식을 model.x0 + t* 프레임
    변위로 다시 계산한다(추가 해석 없음). 반환 (δ 또는 None, "esl_summary"|"recomputed"|"unavailable")."""
    if noise and noise.get("delta") is not None:
        return float(noise["delta"]), "esl_summary"
    u_tot = None
    try:
        dz = _load_npz(ctx.p(D_EXTRACT, "disp.npz"))
        hit = np.flatnonzero(dz["frame_index"] == int(frame_index))
        if hit.size == 1:
            u_tot = np.asarray(dz["u"][int(hit[0])], dtype=np.float64)
    except (OSError, KeyError, ValueError, EslError):
        u_tot = None
    if u_tot is None:
        try:
            u_tot = np.asarray(_load_npz(ctx.p(D_ESL, "u_rel.npz"))["u_total"], dtype=np.float64)
        except (OSError, KeyError, ValueError, EslError):
            return None, "unavailable"
    prec = ctx.cfg["extract"]["disp_precision"]
    xmax = float(np.max(np.abs(np.asarray(model.x0) + u_tot))) if u_tot.size else 0.0
    return 0.5 * float(np.finfo(_PRECISION[prec]).eps) * xmax, "recomputed"


def _field_base(ctx: Context, model: StoredModel, frame_index: int, eps_rad) -> dict:
    """전 요소 재현 정확도 비교(계약 esl_p2_library.md §7.2)의 Radioss 쪽(출처 무관 — v0.24.3 검증 출처마다 같은 값):
    상승 중 마스크·valid·사유·소성 영역·기하(PCA 평면·단면 띠). IO·경고는 여기서 1회, 출처 해와의 비교는 순수
    ``val_metrics.field_compare``.

    eps_rad = t* 프레임 Max_Strain ε_eq(전단 규약 보정, strain_frames).
    상승 중 마스크: strain_frames.npz 의 prev_*(직전 프레임) → 없으면(예전 TCL 출력) history.npz 의 H 요소만.
    """
    meta = _frames_meta(ctx)
    factor = _shear_factor(ctx, meta)
    src = _source(meta)
    rtol = float(ctx.cfg["tstar"]["reach_rtol"])
    ccfg = ctx.cfg["compare"]
    E = int(model.elem_id.size)
    with np.load(ctx.p(D_EXTRACT, "strain_frames.npz"), allow_pickle=False) as z:
        files = set(z.files)
        fd = int(np.flatnonzero(z["frame_index"].astype(np.int64) == int(frame_index))[0])
        epsp = np.asarray(z["epsp"][fd], dtype=np.float64) if "epsp" in files else None     # 소성 영역(참고)
        if "prev_eps" in files:
            pfi = int(z["prev_frame_index"][fd])
            pok = bool(z["prev_available"][fd]) if "prev_available" in files else True
            prev_eps = z["prev_eps"][fd] if (pok and pfi >= 0) else None
            prev_vm = z["prev_vm_hv"][fd] if (pok and pfi >= 0 and "prev_vm_hv" in files) else None
        else:
            pfi, pok, prev_eps, prev_vm = int(frame_index) - 1, False, None, None
    if ((meta.get("strain_fallback") or {}).get("epsp_available")) is False:
        epsp = None                         # h3d 에 소성 결과 없음(H3D_NO_EPSP) → 소성 영역 정보 미상(null)
    known = None
    cst = _cum_state(ctx, model)
    if cst is not None and epsp is not None:
        _, epsp = _cum.series(epsp, cst["prev"], cst["modes"]["plastic_strain"])      # 증분 기준(§6.6)
    if pfi < 0 and pok:
        rising = _field.rising_mask(eps_rad, None, rtol)
        prev_source = "first_frame"
    elif pok:
        pe = rad_eq(prev_eps, prev_vm, factor, src)
        if cst is not None:
            _, pe = _cum.series(pe, cst["prev_eq"], cst["modes"]["max_strain"])
        rising = _field.rising_mask(eps_rad, pe, rtol)
        prev_source = "strain_frames"
    else:
        # 예전 TCL 출력: H 요소만 history 로 판정(f−1 이 history 에 있을 때)
        hz, hp = _history(ctx, model)
        hfi = hz["frame_index"].astype(np.int64)
        rising = np.zeros(E, bool)
        known = np.zeros(E, bool)
        jf = np.flatnonzero(hfi == int(frame_index))
        jp = np.flatnonzero(hfi == pfi)
        if jf.size == 1 and jp.size == 1:
            eqh = rad_eq(hz["eps"], hz["vm_hv"], factor, src)
            if cst is not None:
                _, eqh = _cum.series(eqh, cst["prev_eq"][hp], cst["modes"]["max_strain"])
            rising[hp] = _field.rising_mask(eps_rad[hp], eqh[int(jp[0])], rtol)
            known[hp] = True
        prev_source = "history_H"
        ctx.warnings.append(f"직전 프레임(frame {pfi}) 전 요소 값이 없음(예전 TCL 출력) — 상승 중 판정은 history H "
                            f"요소 {int(known.sum())}개만, 나머지는 비교 불가(NO_PREV). TCL 을 다시 실행할 것")
    ex = _exclude_mask(ctx, model.elem_id)
    valid, reason, max_rad, imax = _field.classify(eps_rad, rising, ccfg["min_rel"], exclude=ex, known=known)

    # 기하: PCA 평면 실좌표(ξ, η), 면외 n, 단면선
    C3 = model.centroids()
    pl = _field.plane_coords(model.x0, C3)
    c2 = np.stack([pl["xi"], pl["eta"]], axis=1)
    size = _field.elem_size(model.x0, model.conn, model.elem_type)
    bx, by = _field.section_band(ccfg["section_band"], size, pl["xi_range"], pl["eta_range"])
    xin = _field.normalize(pl["xi"], pl["xi_range"])
    etn = _field.normalize(pl["eta"], pl["eta_range"])
    return {"eps_rad": eps_rad, "rising": rising, "valid": valid, "reason": reason, "max_rad": max_rad, "imax": imax,
            "epsp": epsp, "frame_index": int(frame_index), "prev_frame_index": pfi, "prev_source": prev_source,
            "rtol": rtol, "plane": pl, "C3": C3, "c2": c2, "size": size, "band": (bx, by), "xin": xin, "etn": etn}


_LOC_DIR = {"esl": D_ESL}             # 검증 계획 표(esl.val_src) 위치 토큰 → Case 폴더


def _plan_file(ctx: Context, ref) -> str:
    """계획 표 파일 열 (위치, 파일[, 배열]) → Case 경로."""
    return ctx.p(_LOC_DIR[ref[0]], ref[1])


def _plan_rel(ref) -> str:
    return f"{_LOC_DIR[ref[0]]}/{ref[1]}"


def _spc_bc321(ctx: Context, model: StoredModel) -> list:
    """지지 집합 bc321 = 03_bc/support.json 3-2-1 → spc [(노드 인덱스, dof)]."""
    sup = _read_json(ctx.p(D_BC, "support.json"))["supports"]
    return [(int(i), s["dof"]) for i, s in zip(_ids_to_idx(model.node_id, [s["node_id"] for s in sup], "support.json"), sup)]


@dataclass
class _Support:
    """검증 지지 집합(계획 열 support 값 → ``_SUPPORT_FN``): key = 분해 묶음 키(같으면 분해 1회 공유 — bc321 = "bc321",
    jig = ("jig", 구속 패턴 sha) — §3.9), show = [(노드 인덱스, 표시 dof)](검증 문서 reactions·지지 표시), factor(sm) → 분해,
    solve(분해, F) → (u (N,6), R (N,3) 지지력 — 스프링 힘 포함). 분해는 패턴만으로 정해지고 값·바닥은 solve 가 행마다 넣는다."""
    key: Any
    show: list
    factor: Callable
    solve: Callable


def _sup_bc321(ctx: Context, model: StoredModel, row=None) -> _Support:
    spc = _spc_bc321(ctx, model)
    return _Support("bc321", spc, lambda sm: sm.factorize(spc), lambda h, F: h.solve(F))


def _sup_jig(ctx: Context, model: StoredModel, row) -> _Support:
    """지지 집합 jig = 행 load 파일(04_esl/<src>.npz)의 bc 배열(tie 구속·스프링 + 3-2-1 면내 — esl_jig_case.md §3.9). 응답 = 같은
    경계(값·바닥·k)로 재풀이, 지지력 = 구속 반력 + 스프링 힘."""
    from esl.mech import jig_bc
    z = _load_npz(_plan_file(ctx, row["load"]))
    if "node_id" not in z or not np.array_equal(z["node_id"], model.node_id):
        raise EslError("ID_MISMATCH", f"{_plan_rel(row['load'])} node_id 가 model.npz 와 다름")
    BC = jig_bc.load_bc(z)
    kind = np.asarray(BC["bc_kind"]).astype(np.int64)
    seen: dict[int, str] = {}
    for n, kk in zip(np.asarray(BC["bc_node"], dtype=np.int64).tolist(), kind.tolist()):
        seen.setdefault(int(n), "tie" if kk == jig_bc.KIND_TIE else "aux321")
    for n in np.asarray(BC["sp_node"], dtype=np.int64).tolist():
        seen.setdefault(int(n), "spring")

    def solve(h, F):
        u, R, _rc, fs = jig_bc.solve(h, F, BC)
        Rt = np.array(R, dtype=np.float64, copy=True)
        if np.asarray(BC["sp_node"]).size:
            np.add.at(Rt, np.asarray(BC["sp_node"], dtype=np.int64), np.asarray(fs)[:, None] * np.asarray(BC["sp_dir"]))
        return u, Rt
    return _Support(("jig", jig_bc.pattern_sha(BC)), sorted(seen.items()), lambda sm: jig_bc.factorize(sm, BC), solve)


# 계획 열 값 → 함수(출처 이름 분기 없음): support → 지지 집합(_Support), fallback → 변형률 참고용 변위
_SUPPORT_FN: dict[str, Callable] = {"bc321": _sup_bc321, "jig": _sup_jig}
_FALLBACK_FN: dict[str, Callable] = {"u_rel_condensed": lambda ctx, sm, u_rel: _solver_call(ctx, _with_rot, sm, u_rel)}


def _err_code(exc: BaseException) -> str:
    return exc.code if isinstance(exc, EslError) else type(exc).__name__


def _err_text(exc: BaseException) -> str:
    t = f"{exc.code}: {exc.message}" if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"
    return t[:_vs.FAILED_DETAIL_MAX]


def _val_src_failed(ctx: Context, ent: dict, exc: BaseException) -> None:
    """출처 행 실패 격리(§6.1-6): 행 failed + VAL_SRC_FAILED, 단계 경고 1줄 — full·다른 출처 무영향."""
    ent["st"] = _vs.failed_status(_err_text(exc))
    ent["u6"] = ent["R"] = None
    ctx.warnings.append(f"VAL_SRC_FAILED: {ent['row']['key']} {_err_code(exc)}")


def _val_src_prepare(ctx: Context, model: StoredModel, enabled: bool) -> list[dict]:
    """legacy 외 계획 행 준비(§6.1-2): 설정 끔 → disabled, 아니면 진단 json·하중(node_id 일치)·ESL 요약 forces.<summary>
    로 ``val_src.row_status``(done 후보 | unavailable | na). 준비 중 예외(손상 파일·node_id 불일치) = 그 행 failed."""
    esl_sum = (((ctx.record or {}).get("stages") or {}).get("esl") or {}).get("summary") or {}
    out = []
    for row in _vs.VAL_PLAN:
        if row["legacy"]:
            continue
        ent: dict[str, Any] = {"row": row, "doc": None, "F": None, "u6": None, "R": None}
        out.append(ent)
        if not enabled:
            ent["st"] = _vs.disabled_status()
            continue
        if row["load"] is None:
            ent["st"] = _vs.row_status(row, False)
            continue
        try:
            if row["doc"] is not None:
                dp = _plan_file(ctx, row["doc"])
                ent["doc"] = _read_json(dp) if os.path.isfile(dp) else None
            lp = _plan_file(ctx, row["load"])
            F_s = None
            if os.path.isfile(lp):
                z = _load_npz(lp)
                if row["load"][2] in z:
                    if "node_id" not in z or not np.array_equal(z["node_id"], model.node_id):
                        raise EslError("ID_MISMATCH", f"{_plan_rel(row['load'])} node_id 가 model.npz 와 다름")
                    F_s = np.asarray(z[row["load"][2]], dtype=np.float64)
                    if not np.all(np.isfinite(F_s)):
                        bad = int(np.count_nonzero(~np.isfinite(F_s)))
                        raise EslError("INPUT_INVALID", f"입력 하중 {_plan_rel(row['load'])} 에 비유한값(NaN·Inf) {bad}개 — "
                                                        "ESL 단계 산출물을 확인")
            s = esl_sum.get(row["summary"]) if row["summary"] else None
            ent["st"] = _vs.row_status(row, F_s is not None, ent["doc"], s if isinstance(s, dict) else None)
            ent["F"] = F_s
        except Exception as exc:                                # noqa: BLE001 — 출처 때문에 검증 단계 실패 금지
            _val_src_failed(ctx, ent, exc)
    return out


def _val_solve(ctx: Context, model: StoredModel, sm: ShellModel, legacy: dict, spc, F, ents: list, srec: dict):
    """지지 묶음마다 분해 1회 + 출처마다 해 1회(§4.1, D-0.24.3-VAL-3). legacy 묶음 먼저: legacy 해 = 지금과 같은
    ``sm.solve``(그 분해를 ``keep_factor`` 로 남김 — 산술·통계 v0.24.2 그대로), 같은 묶음 출처 해 = 그 분해 재사용.
    v0.24.4(esl_jig_case.md §3.9): 묶음 키 = 지지 집합 key(bc321 = 지지 이름, jig = (지지 이름, 구속 패턴 sha) — jig+jig_disp 1,
    jig_spring 1). 지지 집합 읽기·분해·해 예외 = 그 행(묶음) failed. 반환 (u_val, R, 단계 요약 solver = legacy 해 직후 solver_stats)."""
    out = None
    for sup in (legacy["support"], *(s for s in _vs.SUPPORTS if s != legacy["support"])):
        mem = [e for e in ents if e["st"]["status"] == "done" and e["row"]["support"] == sup]
        is_leg = sup == legacy["support"]
        if not mem and not is_leg:
            continue
        groups: dict[Any, list] = {}
        for e in mem:
            try:
                e["sup"] = _SUPPORT_FN[sup](ctx, model, e["row"])
                e["show"] = e["sup"].show
            except Exception as exc:                            # noqa: BLE001
                _val_src_failed(ctx, e, exc)
                continue
            groups.setdefault(e["sup"].key, []).append(e)
        keys = list(groups) or [sup]
        if is_leg and sup not in groups:
            keys = [sup, *keys] if groups else [sup]
        for gk in keys:
            gm = groups.get(gk, [])
            g_leg = is_leg and gk == sup
            if not gm and not g_leg:
                continue
            g: dict[str, Any] = {"support": sup, "keys": [], "factor_s": None, "solve_s": {}}
            if isinstance(gk, tuple):
                g["pattern"] = str(gk[1])[:16]
            srec["groups"].append(g)
            h: Any = None
            if g_leg:
                t0 = _time.perf_counter()
                sm.keep_factor = bool(gm)
                try:
                    u_val, Rr = _solver_call(ctx, sm.solve, F, spc)
                finally:
                    sm.keep_factor = False
                    h, sm.kept_factor = sm.kept_factor, None
                stats = solver_stats(sm)
                out = (u_val, Rr, stats)
                kff = stats.get("K_ff") or {}
                fac, asm = float(kff.get("factor_s") or 0.0), float(stats.get("assembly_s") or 0.0)
                g.update(factor_s=round(fac, 4), assembly_s=round(asm, 4))
                g["solve_s"][legacy["key"]] = round(max(_time.perf_counter() - t0 - fac - asm, 0.0), 4)
                g["keys"].append(legacy["key"])
            if gm and h is None:
                try:
                    t0 = _time.perf_counter()
                    h = _solver_call(ctx, gm[0]["sup"].factor, sm)
                    g["factor_s"] = round((g["factor_s"] or 0.0) + _time.perf_counter() - t0, 4)
                except Exception as exc:                        # noqa: BLE001
                    for e in gm:
                        _val_src_failed(ctx, e, exc)
                    continue
            for e in gm:
                try:
                    t0 = _time.perf_counter()
                    solve = e["sup"].solve if not g_leg else (lambda hh, FF: hh.solve(FF))
                    e["u6"], e["R"] = _solver_call(ctx, solve, h, e["F"])
                    g["solve_s"][e["row"]["key"]] = round(_time.perf_counter() - t0, 4)
                    g["keys"].append(e["row"]["key"])
                except Exception as exc:                        # noqa: BLE001
                    _val_src_failed(ctx, e, exc)
            del h
    return out


def _cum_plastic(ctx: Context, model: StoredModel, frame_index: int) -> dict | None:
    """누적 씬 소성 요약(strain_ref 에 더함 — Radioss 쪽, 출처 무관). 비누적 = None."""
    cst = _cum_state(ctx, model)
    if cst is None:
        return None
    with np.load(ctx.p(D_EXTRACT, "strain_frames.npz"), allow_pickle=False) as z:
        fd_ = int(np.flatnonzero(z["frame_index"].astype(np.int64) == int(frame_index))[0])
        ep_raw = np.asarray(z["epsp"][fd_], np.float64) if "epsp" in z.files else np.zeros(model.elem_id.size)
    ep_cum, ep_inc = _cum.series(ep_raw, cst["prev"], cst["modes"]["plastic_strain"])
    return {"basis": "increment", "n_plastic_cum": int(np.sum(ep_cum > 0)),
            "n_plastic_inc": int(np.sum(ep_inc > CUM_EPSP_FLOOR)),
            "cum_max": float(np.max(ep_cum)) if ep_cum.size else 0.0,
            "inc_max": float(np.max(ep_inc)) if ep_inc.size else 0.0}


def _write_val_files(ctx: Context, d: str, ev: dict, nid) -> None:
    """검증 파일 세트(legacy 루트·출처 폴더 공통 — §4.5): validation.json·compare_field.npz·compare_disp.npz·validation.csv·
    compare.csv(풀이 있을 때만). 쓰는 순서 = v0.24.2."""
    _write_json(ctx.f(d, "validation.json"), ev["doc"])
    if ev["field_arrays"] is not None:
        np.savez_compressed(ctx.f(d, "compare_field.npz"), **ev["field_arrays"])
    if ev["disp_arrays"] is not None:
        np.savez_compressed(ctx.f(d, "compare_disp.npz"), **ev["disp_arrays"])
    fmt = ctx.csvfmt()
    csvout.write_validation_csv(ctx.f(d, "validation.csv"), ev["doc"], fmt)
    if ev["compare"] is not None:
        d_rel, d_val, dn = ev["compare"]
        csvout.write_csv(ctx.f(d, "compare.csv"),
                         ("node_id", "ux_rel", "uy_rel", "uz_rel", "ux_val", "uy_val", "uz_val", "d_mag"),
                         ((int(nid[i]), *d_rel[i], *d_val[i], dn[i]) for i in range(nid.size)), fmt)


def _src_tmp_cleanup(ctx: Context, path: str) -> None:
    import shutil
    if os.path.lexists(path):
        shutil.rmtree(ctx.guard(path), ignore_errors=True)


def stage_validate(ctx: Context) -> dict:
    """S5 검증 (계약 esl_disp_primary.md). 판정 = 변위 4지표(disp_rms_rel·disp_max_rel·reaction_rel·disp_noise_rel),
    변형률 지표는 참고(role=reference, 초과 여부만). 전체 재해석을 못 하면 UNDETERMINED(변형률로 대신 판정하지 않음).

    v0.24.3(esl_validate_sources.md §6): 계획 표 ``esl.val_src.VAL_PLAN`` 의 출처마다 같은 정의·같은 기준으로 검증 —
    legacy(full) = 05_val 루트(v0.24.2 와 바이트 동일), 출처 = 05_val/<dir>/ 같은 파일 세트, 인덱스 05_val/sources.json.
    응답 = 지지 집합마다 분해 1회 + 출처마다 해 1회. 출처 예외는 그 행만 failed(full 판정·다른 출처 무영향)."""
    legacy = _vs.plan(None)
    _require(ctx.out, [f"{D_EXTRACT}/strain_frames.npz", f"{D_EXTRACT}/history.npz", f"{D_BC}/support.json",
                       _plan_rel(legacy["target"]), *(_plan_rel(r["load"]) for r in _vs.VAL_PLAN if r["required"]),
                       f"{D_ESL}/esl_summary.json"])
    model = load_model(ctx.out)
    nid, X0 = model.node_id, model.x0
    ur = _load_npz(_plan_file(ctx, legacy["target"]))
    fz = _load_npz(_plan_file(ctx, legacy["load"]))
    summ = _read_json(ctx.p(D_ESL, "esl_summary.json"))
    if not (np.array_equal(ur["node_id"], nid) and np.array_equal(fz["node_id"], nid)):
        raise EslError("ID_MISMATCH", "04_esl 산출물의 node_id 가 model.npz 와 다름")
    u_rel, F = ur[legacy["target"][2]], fz[legacy["load"][2]]
    spc = _SUPPORT_FN[legacy["support"]](ctx, model, legacy).show
    frame_index = int(summ["frame"]["frame_index"])
    umax = float(np.max(np.linalg.norm(u_rel, axis=1))) if u_rel.size else 0.0      # 정규화 U = max|u_rel|

    sm = _shell(ctx, model)
    fs = full_solve_decision(ctx, sm, int(model.elem_id.size))
    solved = bool(fs["run"]) and umax > 0
    enabled = bool(_config.validation_sources_settings(ctx.cfg)["enabled"])
    ents = _val_src_prepare(ctx, model, enabled)
    srec: dict[str, Any] = {"groups": [], "decision": {k: fs[k] for k in ("mode", "run", "reason")}, "eval_s": {}}
    solver_sum = None
    Rr = None
    if solved:
        # 반복법이면 전체계는 rtol = min(설정, 1e-12) (직접법이면 영향 없음)
        sm.iter_opts["rtol"] = min(float(ctx.cfg["solver"]["iter_rtol"]), S5_ITER_RTOL_MAX)
        u_val, Rr, solver_sum = _val_solve(ctx, model, sm, legacy, spc, F, ents, srec)
    else:
        # 판정 불가(UNDETERMINED): 변형률은 참고용으로만 — u_rel + 응축 회전(rotations_for) 막 변형률(계획 열 fallback)
        if not fs["run"]:
            ctx.warnings.append(f"S5 전체 solve 생략({fs['reason']}) — 판정 불가(UNDETERMINED, NO_FULL_SOLVE). "
                                "변형률 참고 지표만 계산")
        else:
            ctx.warnings.append("u_rel 이 전부 0 (변형 없음) — 판정 불가(UNDETERMINED, ZERO_DISP)")
        u_val = None if legacy["fallback"] is None else _FALLBACK_FN[legacy["fallback"]](ctx, sm, u_rel)
    t_eps = _time.perf_counter()
    eps_sol = None if u_val is None else sm.strains(u_val)
    t_eps = _time.perf_counter() - t_eps                    # legacy 변형률 회복 시간(eval_s 에 더함 — 출처와 같은 범위)

    # Radioss 쪽 한 번(출처 무관): hotspot ε_eq(t* 프레임, Mid)·전 요소 비교 기반·잡음 — 경고 1회
    fmeta = _frames_meta(ctx)
    src = _source(fmeta)
    layers = _esl_layers(ctx, fmeta)
    hs, eps_rad = _eval_hotspots(ctx, model, frame_index)
    excl = [h["elem_id"] for h in hs if not h["compared"] and not h["comparable"]]
    if excl:
        ctx.warnings.append(f"hotspot {len(excl)}개 비교 제외(상승 중 아님): {excl[:10]}")
    base = _field_base(ctx, model, frame_index, eps_rad)
    vcfg = ctx.cfg["validation"]
    ccfg = ctx.cfg["compare"]
    noise = summ.get("noise")
    if noise is None:
        ctx.warnings.append("esl_summary.json 에 잡음 바닥(noise) 없음 — esl 단계를 다시 실행 권장")
    n_strain = float(noise["hotspot_strain_rel"]) if noise else None
    if src == "max_stress":
        n_strain = None
        if STRAIN_FROM_STRESS not in ctx.warnings:
            ctx.warnings.append(STRAIN_FROM_STRESS)
    n_force = float(noise["force_rel"]) if noise else None

    # 변위 잡음 바닥 δ/U (추가 해석 없음)
    delta_noise, noise_source = _disp_noise_delta(ctx, noise, model, frame_index)
    disp_noise_rel = (delta_noise / umax) if (delta_noise is not None and umax > 0) else None

    crit = {"disp_rms_rel_max": vcfg["disp_rms_rel_max"], "disp_max_rel_max": vcfg["disp_max_rel_max"],
            "reaction_rel_max": vcfg["reaction_rel_max"], "disp_noise_rel_max": vcfg["disp_noise_rel_max"],
            "hotspot_strain_rel_err_max": vcfg["hotspot_strain_rel_err_max"],
            "hotspot_eval_count": vcfg["hotspot_eval_count"],
            "noise_strain_rel_max": vcfg["noise_strain_rel_max"],
            "noise_force_rel_warn": vcfg["noise_force_rel_warn"],
            "disp_precision": noise["disp_precision"] if noise else ctx.cfg["extract"]["disp_precision"],
            "layers": list(layers), "metric": ctx.cfg["tstar"]["metric"], "full_solve": fs["mode"],
            "field_max_err_pct_max": ccfg["max_err_pct_max"], "field_p90_err_max": ccfg["p90_err_max"],
            "field_min_rel": ccfg["min_rel"]}
    undetermined_reason = None
    if not fs["run"]:
        undetermined_reason = "NO_FULL_SOLVE"
    elif umax <= 0:
        undetermined_reason = "ZERO_DISP"
    common = {"X0": X0, "node_id": nid, "u_rel": u_rel, "U": umax, "solved": solved,
              "undetermined_reason": undetermined_reason, "spc": spc, "hs": hs, "eps_rad": eps_rad, "base": base,
              "model_arrays": {"elem_id": model.elem_id, "conn": model.conn, "elem_type": model.elem_type},
              "layers_text": "·".join(_esl_layers(ctx, fmeta)), "strain_source": src,
              "strain_skipped": src == "max_stress", "ccfg": ccfg, "crit": crit, "disp_top_n": vcfg["disp_top_n"],
              "disp_hist_bins": vcfg["disp_hist_bins"], "noise": noise, "noise_source": noise_source,
              "n_strain": n_strain, "n_force": n_force, "disp_noise_rel": disp_noise_rel,
              "cum_plastic": _cum_plastic(ctx, model, frame_index), "frame": summ["frame"], "esl_ref": esl_ref(summ),
              "full_solve": fs}

    # ---- legacy(full) 행: 지표·문서·파일(05_val 루트, v0.24.2 와 같은 순서·경고·echo) — 이 시점에 full 결과 완결
    t0 = _time.perf_counter()
    ev = _vm.evaluate(common, F=F, u_val6=u_val if solved else None, R=Rr,
                      eps_val=None if eps_sol is None else _solver_eq(eps_sol, layers),
                      reaction_role=legacy["reaction_role"], noise_force=legacy["noise_force"], created_at=_utcnow())
    val, metrics = ev["doc"], ev["doc"]["metrics"]
    verdict, fail_reasons = val["verdict"], val["fail_reasons"]
    hots, excluded, sref, fsum = ev["hots"], ev["excluded"], ev["sref"], ev["fsum"]
    vv = ev["values"]
    disp_rms_rel, disp_max_rel, reac_abs_rel = vv["disp_rms_rel"], vv["disp_max_rel"], vv["reaction_rel"]
    h1, f_max, f_p90 = vv["hotspot1_strain_rel_err"], vv["field_max_err_pct"], vv["field_p90_err_pct"]

    d = ctx.fresh_dir(D_VAL)
    _write_val_files(ctx, d, ev, nid)
    srec["eval_s"][legacy["key"]] = round(_time.perf_counter() - t0 + t_eps, 4)
    if verdict == "FAIL":
        ctx.warnings.append("검증 FAIL: " + ", ".join(f"{m['metric']}({_FAIL_REASON[m['metric']]})"
                                                     for m in metrics if m["role"] == "judge" and m["pass"] is False))
    fmt_v = lambda v: "skipped" if v is None else f"{v:.2e}"
    ctx.echo(f"[validate] 변위 RMS={fmt_v(disp_rms_rel)} (≤{crit['disp_rms_rel_max']:g}), "
             f"변위 최대={fmt_v(disp_max_rel)} (≤{crit['disp_max_rel_max']:g}), "
             f"반력 Σ|R|/Σ|F|={fmt_v(reac_abs_rel)} (≤{crit['reaction_rel_max']:g}), "
             f"변위 잡음 δ/U={fmt_v(disp_noise_rel)} (≤{crit['disp_noise_rel_max']:g}, {noise_source}) → {verdict}"
             + (f" {fail_reasons}" if fail_reasons else "")
             + (f" ({undetermined_reason})" if undetermined_reason else ""))
    fa = fsum["abs_err_pct"]
    _g = lambda v, f: "skipped" if v is None else format(v, f)
    ctx.echo(f"[validate] 변형률 참고(source {src}): hotspot1 rel_err={_g(h1, '.2e')} "
             f"(참고 ≤{crit['hotspot_strain_rel_err_max']:g}, "
             f"비교 {len(hots)}·제외 {len(excluded)}), 최대변형률 요소 오차 {_g(f_max, '.3g')}% "
             f"(≤{ccfg['max_err_pct_max']:g}), "
             f"|오차| P90 {_g(f_p90, '.3g')}% (≤{ccfg['p90_err_max']:g}), 기준 초과 요소 {_g(sref['n_exceed'], 'd')}/{sref['n_elems']} "
             f"({_g(None if sref['frac_exceed'] is None else 100 * sref['frac_exceed'], '.3g')}%)"
             + ("" if sref["plastic"] is None else f", 소성 영역 {sref['plastic']['n_plastic']}")
             + f", valid {fsum['n_valid']}/{fsum['n_elems']} (상승 {fsum['n_rising']}, hold {fsum['n_hold']}, "
             f"low {fsum['n_low']})" + (f", ≤10% 비율 {fsum['frac_within']['10']:.1%}" if fa else "")
             + (" [참고 초과]" if sref["exceeded"] else ""))

    # ---- 출처 행(§6.1-6): 같은 계산 → 05_val/<dir>.tmp → <dir>(원자적), 예외 = 그 행 failed(tmp 정리)
    rows_out: list[dict] = []
    ssum: dict[str, Any] = {}
    for e in ents:
        row = e["row"]
        if e["st"]["status"] == "done":
            tmp = ctx.guard(os.path.join(d, f"{row['dir']}.tmp"))
            try:
                t0 = _time.perf_counter()
                if solved and e["u6"] is None:
                    raise EslError("VAL_SRC_FAILED", "출처 응답 풀이 결과 없음")
                eps_s = None
                if solved:
                    eps_s = _solver_eq(sm.strains(e["u6"]), layers)
                sum_abs = float(np.linalg.norm(e["F"], axis=1).sum())
                # 출처별 반력 허용치(계획 열 reaction_tol_key; None = 공통 기준) — 문서 criteria·판정 모두 이 값
                tol = _config.source_reaction_tol(ctx.cfg, row["reaction_tol_key"], row["key"])
                if tol is None:
                    tol = crit["reaction_rel_max"]
                warn = _config.source_reaction_tol(ctx.cfg, row["reaction_warn_key"], row["key"])
                crit_s = {**crit, "reaction_rel_max": tol, **({} if warn is None else {"reaction_warn_rel": warn})}
                cs = {**common, "crit": crit_s, **({} if e.get("show") is None else {"spc": e["show"]})}
                evs = _vm.evaluate(cs, F=e["F"], u_val6=e["u6"], R=e["R"], eps_val=eps_s,
                                   reaction_role=row["reaction_role"], noise_force=row["noise_force"],
                                   created_at=_utcnow(), criteria={**crit_s, "reaction_role": row["reaction_role"]},
                                   src=_vs.src_block(row, e["doc"], sum_abs))
                _src_tmp_cleanup(ctx, tmp)
                os.makedirs(tmp)
                _write_val_files(ctx, tmp, evs, nid)
                atomic_replace(tmp, ctx.guard(os.path.join(d, row["dir"])))
                srec["eval_s"][row["key"]] = round(_time.perf_counter() - t0, 4)
                e["ev"] = evs
            except Exception as exc:                            # noqa: BLE001 — 출처 때문에 검증 단계 실패 금지
                _src_tmp_cleanup(ctx, tmp)
                _val_src_failed(ctx, e, exc)
        if e["st"]["status"] == "done":
            r = _vs.done_row(row, e["ev"]["doc"], e["doc"])
            vs = e["ev"]["values"]
            wtxt = "" if r["reaction_warn"] is None else f", 주의 {r['reaction_warn']:g}"
            ctx.echo(f"[validate] {row['key']}: 변위 RMS={fmt_v(vs['disp_rms_rel'])}, 변위 최대={fmt_v(vs['disp_max_rel'])}, "
                     f"반력 Σ|R|/Σ|F|={fmt_v(vs['reaction_rel'])}({row['reaction_role']}, 허용치 {r['reaction_tol']:g}{wtxt}) → {r['verdict']}"
                     + (f" {r['fail_reasons']}" if r["fail_reasons"] else "")
                     + (f" ({r['undetermined_reason']})" if r["undetermined_reason"] else "")
                     + (f" · 한계 {r['limits']}" if r["limits"] else ""))
        else:
            r = _vs.empty_row(row, e["st"])
            ctx.echo(f"[validate] {row['key']}: 불가 {r['code']}")
        rows_out.append(r)
        ssum[row["key"]] = {"status": r["status"], "verdict": r["verdict"], "fail_reasons": r["fail_reasons"],
                            "undetermined_reason": r["undetermined_reason"], "code": r["code"],
                            **{k: (r["metrics"] or {}).get(k) for k in ("disp_rms_rel", "disp_max_rel", "reaction_rel")}}
    leg_row = _vs.done_row(legacy, val, None)
    rows_all = [leg_row if row["legacy"] else next(x for x in rows_out if x["key"] == row["key"])
                for row in _vs.VAL_PLAN]
    _write_json(ctx.f(d, _vs.SOURCES_JSON),
                {"schema": _vs.SCHEMA_SOURCES, "esl_ref": esl_ref(summ), "default": legacy["key"], "enabled": enabled,
                 "solve": srec, "rows": rows_all, "created_at": _utcnow()})

    if solver_sum is None:
        solver_sum = solver_stats(sm)
    field_short = {"max_err_pct": f_max, "p90_err_pct": f_p90, "n_valid": fsum["n_valid"],
                   "n_rising": fsum["n_rising"], "n_elems": fsum["n_elems"], "prev_source": fsum["prev_source"]}
    strain_short = {k: sref[k] for k in ("n_exceed", "frac_exceed", "frac_exceed_valid", "p99_err_pct", "exceeded")}
    strain_short["n_plastic"] = None if sref["plastic"] is None else sref["plastic"]["n_plastic"]
    if "basis" in sref:
        strain_short.update({k: sref[k] for k in ("basis", "n_plastic_cum", "n_plastic_inc", "cum_max", "inc_max")})
    return {"verdict": verdict, "fail_reasons": fail_reasons, "undetermined_reason": undetermined_reason,
            "field": field_short, "strain_ref": strain_short, "noise_source": noise_source,
            "noise_hotspot_strain_rel": n_strain,
            "noise_force_rel": n_force, "disp_rms_rel": disp_rms_rel, "disp_max_rel": disp_max_rel,
            "disp_noise_rel": disp_noise_rel,
            "hotspot1_rel_err": h1, "reaction_rel": reac_abs_rel, "reaction_sum_rel": vv["reaction_sum_rel"],
            "n_hotspots_compared": len(hots), "n_hotspots_excluded": len(excluded),
            "full_solve": {k: fs[k] for k in ("mode", "run", "reason")}, "solver": solver_sum,
            "strain_source": src, "sources": ssum}


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
        with_inc = "radioss_inc" in targets      # .fem 만이면 /GRNOD·/BCS·/CLOAD ID 는 필요 없음
        plan = plan_ids(rcfg["id_offset"], model.max_ids, len(sup) if with_inc else 0, len(groups),
                        int(mask.any(axis=1).sum()) if with_inc else 0, int(mask.sum()) if with_inc else 0)
        lo, hi = plan["range"]
        ids = all_ids(plan)
        assert all(lo <= v <= hi for v in ids) and len(set(ids)) == len(ids)
        if plan["id_offset_auto"] and plan["id_offset"] != AUTO_BASE:
            ctx.warnings.append(f"export.radioss.id_offset=auto: rad 기존 ID 와 겹치지 않도록 생성 ID 를 "
                                f"{plan['id_offset'] + 1} 부터 배정")

    fr = summ["frame"]
    units = ctx.cfg["units"]
    hdr = [f"ESL export (esl {esl.__version__})  generated {_utcnow()}",
           f"part {model.part_id} '{model.part_title}'  frame {fr['frame_index']}  t* = {fr['time']!r} ({fr['source']})",
           f"units: {units['label']} (force {units['force']}, length {units['length']}); rad /BEGIN: '{model.units_label}'",
           f"generated ID range [{lo}, {hi}] ({plan['n_ids'] if plan else 0} IDs, id_offset {plan['id_offset'] if plan else None})",
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
             + (f", ID [{lo}..{hi}] ({plan['n_ids']}개)" if plan else ""))
    out.update(files=files, id_range=[lo, hi] if plan else None, id_max_used=plan["max_used"] if plan else None,
               id_plan=None if plan is None else {k: (v if not isinstance(v, list) or len(v) <= 6 else [v[0], v[-1]])
                                                  for k, v in plan.items()},
               esl_ref=esl_ref(summ), validation_used=val is not None)
    return out


# ====================================================================== report
def stage_report(ctx: Context) -> dict:
    """Case HTML 보고서 07_report/report.html (있는 산출물만으로 생성, 없는 절은 "자료 없음")."""
    from esl.report import case_report

    _require(ctx.out, [f"{D_EXTRACT}/model.npz", f"{D_EXTRACT}/model_meta.json"])
    rcfg = ctx.cfg["report"]
    doc, info = case_report.build_case_report(ctx.out, record=ctx.record, max_points=rcfg["max_points"],
                                              top_forces=rcfg["top_forces"])
    d = ctx.fresh_dir(D_REPORT)
    path = ctx.f(d, case_report.REPORT_NAME)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    size = os.path.getsize(path)
    if info["missing"]:
        ctx.warnings.append(f"보고서: 없는 산출물 {info['missing']} — 해당 절은 '자료 없음'")
    ctx.echo(f"[report] {os.path.join(D_REPORT, case_report.REPORT_NAME)} ({size / 1024:.0f} KB), 판정 "
             f"{info['verdict'] or 'N/A'}, 2D 점 {info['n_points']}"
             + (f"/{info['n_elems']} (다운샘플)" if info.get("downsampled") else ""))
    return {"path": f"{D_REPORT}/{case_report.REPORT_NAME}", "bytes": size, **info}


_STAGE_FN = {"extract": stage_extract, "tstar": stage_tstar, "esl": stage_esl,
             "validate": stage_validate, "export": stage_export, "report": stage_report}


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
    ts = _dt.datetime.now(_dt.timezone.utc).strftime(BACKUP_TS_FMT)
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
            if st == "report" and stage == "all":
                # 보고서는 부가 산출물: 실패해도 앞 단계 산출물·성공 상태 유지(run.json 에 failed + 경고)
                try:
                    summary = _STAGE_FN[st](ctx)
                except Exception as exc:  # noqa: BLE001
                    code = exc.code if isinstance(exc, EslError) else "INTERNAL_ERROR"
                    msg = exc.message if isinstance(exc, EslError) else f"{type(exc).__name__}: {exc}"
                    err = {"code": code, "message": msg, "stage": st, "at": _utcnow()}
                    record["stages"][st] = {"status": "failed", "finished_at": _utcnow(), "error": err,
                                            "warnings": list(ctx.warnings)}
                    echo(f"  경고: 보고서 생성 실패(앞 단계 결과는 유지): {code}: {msg}")
                    continue
            else:
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
