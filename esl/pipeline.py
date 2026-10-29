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
               compare_disp.npz (full_solve 수행 시, 계약 esl_disp_primary.md §4)
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
from esl.errors import EslError
from esl.export import AUTO_BASE, all_ids, dof_flags, force_mask, plan_ids
from esl.export import csvout, optistruct, radioss
from esl.io import RESULT_FILES, decide_shear, pack_results, tensor_eps
from esl.io.results_csv import METRICS
from esl.mech import kabsch, strain, supports, tstar
from esl.mech.shell import ShellModel
from esl.rad import parse_rad, scan_includes
from esl.rad.parser import max_line_bytes_of
from esl.report import field as _field

STAGES = ("extract", "tstar", "esl", "validate", "export", "report")
EXPORT_TARGETS = ("radioss_inc", "fem", "csv")
D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT, D_REPORT = (
    "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report")
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
                        coord_check=ctx.cfg.get("coord_check"))
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
    for name in RESULT_FILES:
        p = os.path.join(ctx.results, name)
        if os.path.isfile(p):
            inputs["results_files"][name] = _fingerprint(p, True)
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
         "conn_check": info.get("conn_check")}
    if cs is not None:
        s["cumulative"] = cs["short"]
    ctx.echo(f"[extract] 파트 {model.part_id} '{model.part_title}': 노드 {s['n_nodes']}, 요소 {s['n_elems']} "
             f"(QUAD {s['n_quad']}/TRIA {s['n_tria']}), 이력 프레임 {s['n_frames']}, H {s['n_hot']}요소, "
             f"후보 프레임 D {s['frames_D']}, 전단 {sh['convention']}"
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
    series = _metric_series(hz, factor)
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
    series = _metric_series(hz, factor)
    v = series[tcfg["metric"]]
    eqh = series["max_strain"]
    ex = _exclude_mask(ctx, model.elem_id, hz["elem_id"])
    cst = _cum_state(ctx, model)
    eps_rad = strain.eps_eq(tensor_eps(sz["eps"][int(fd[0])], factor))          # (E,)
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


VERDICT_SCHEME = "disp_primary/1"      # 계약 esl_disp_primary.md: 판정 = 변위 4지표, 변형률은 참고
VALIDATION_SCHEMA = "esl/validation/3"
_FAIL_REASON = {"disp_rms_rel": "DISP_RMS", "disp_max_rel": "DISP_MAX", "reaction_rel": "REACTION",
                "disp_noise_rel": "DISP_NOISE"}


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


def _field_compare(ctx: Context, model: StoredModel, frame_index: int, eps_rad, eps_esl, d_rel, d_val):
    """전 요소 재현 정확도 비교(계약 esl_p2_library.md §7.2) → (npz 배열 dict, validation.json field 요약).

    eps_rad = t* 프레임 Max_Strain ε_eq(전단 규약 보정, strain_frames), eps_esl = 검증 해 ε_eq(extract.layers, 기본 막).
    상승 중 마스크: strain_frames.npz 의 prev_*(직전 프레임) → 없으면(예전 TCL 출력) history.npz 의 H 요소만.
    d_rel·d_val (N,3): 단면선용 변위(전체 solve 면 양쪽 미소 강체 제거, 아니면 둘 다 u_rel).
    """
    meta = _frames_meta(ctx)
    factor = _shear_factor(ctx, meta)
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
        else:
            pfi, pok, prev_eps = int(frame_index) - 1, False, None
    known = None
    cst = _cum_state(ctx, model)
    if cst is not None and epsp is not None:
        _, epsp = _cum.series(epsp, cst["prev"], cst["modes"]["plastic_strain"])      # 증분 기준(§6.6)
    if pfi < 0 and pok:
        rising = _field.rising_mask(eps_rad, None, rtol)
        prev_source = "first_frame"
    elif pok:
        pe = strain.eps_eq(tensor_eps(prev_eps, factor))
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
            eqh = strain.eps_eq(tensor_eps(hz["eps"], factor))
            if cst is not None:
                _, eqh = _cum.series(eqh, cst["prev_eq"][hp], cst["modes"]["max_strain"])
            rising[hp] = _field.rising_mask(eps_rad[hp], eqh[int(jp[0])], rtol)
            known[hp] = True
        prev_source = "history_H"
        ctx.warnings.append(f"직전 프레임(frame {pfi}) 전 요소 값이 없음(예전 TCL 출력) — 상승 중 판정은 history H "
                            f"요소 {int(known.sum())}개만, 나머지는 비교 불가(NO_PREV). TCL 을 다시 실행할 것")
    ex = _exclude_mask(ctx, model.elem_id)
    valid, reason, max_rad, imax = _field.classify(eps_rad, rising, ccfg["min_rel"], exclude=ex, known=known)
    rel = _field.rel_error(eps_esl, eps_rad)
    sref = _field.strain_reference(rel, valid, epsp, E, ccfg["max_err_pct_max"])

    # 기하: PCA 평면 실좌표(ξ, η), 면외 n, 단면선
    C3 = model.centroids()
    pl = _field.plane_coords(model.x0, C3)
    c2 = np.stack([pl["xi"], pl["eta"]], axis=1)
    n = pl["n"]
    w_rel = _field.elem_mean(model.conn, model.elem_type, np.asarray(d_rel) @ n)
    w_val = _field.elem_mean(model.conn, model.elem_type, np.asarray(d_val) @ n)
    size = _field.elem_size(model.x0, model.conn, model.elem_type)
    bx, by = _field.section_band(ccfg["section_band"], size, pl["xi_range"], pl["eta_range"])
    xin = _field.normalize(pl["xi"], pl["xi_range"])
    etn = _field.normalize(pl["eta"], pl["eta_range"])
    sec_xi = _field.section(xin, pl["eta"], pl["n0"], w_rel, w_val, 0.5, bx)      # ξ=0.5 고정, η 방향
    sec_eta = _field.section(etn, pl["xi"], pl["n0"], w_rel, w_val, 0.5, by)     # η=0.5 고정, ξ 방향

    summ = _field.summarize(model.elem_id, eps_rad, eps_esl, rel, valid, reason, rising, imax,
                            ccfg["top_n"], ccfg["hist_bins"], c2=c2)
    summ.update(schema="esl/field/1", frame_index=int(frame_index), prev_frame_index=pfi, prev_source=prev_source,
                rtol=rtol, min_rel=float(ccfg["min_rel"]), max_rad=max_rad,
                reason_codes={str(k): v for k, v in _field.REASONS.items()}, reason_text=_field.REASON_TEXT,
                definition={"rel_err": "(eps_esl - eps_rad)/eps_rad", "abs_err_pct": "100*|rel_err| (valid 요소)",
                            "max_err_pct": "max.abs_err_pct: t* 상승 요소 중 ε_rad 최대 요소의 오차",
                            "valid": "rising ∧ eps_rad ≥ min_rel·max_rad ∧ 제외 아님",
                            "rising": "v[t*] > v[t*−1]·(1+rtol), t*=첫 프레임이면 v>0 (v = Max_Strain ε_eq)",
                            "eps_esl": f"검증 해 ε_eq({'·'.join(ctx.cfg['extract']['layers'])}, 막 z=0 기본)"},
                plane={k: pl[k].tolist() for k in ("origin", "e1", "e2", "n", "xi_range", "eta_range")},
                sections={"xi": {"at": 0.5, "band": bx, "n_elems": sec_xi["n_elems"]},
                          "eta": {"at": 0.5, "band": by, "n_elems": sec_eta["n_elems"]}},
                note=_field.SEMANTIC_NOTE)
    arrays = dict(
        elem_id=model.elem_id.astype(np.int64), centroid2d=c2, centroid3d=C3,
        eps_rad=np.asarray(eps_rad, np.float64), eps_esl=np.asarray(eps_esl, np.float64), rel_err=rel,
        valid=valid, rising=rising, reason=reason.astype(np.int8), elem_size=size,
        epsp=np.full(E, np.nan) if epsp is None else epsp,
        plastic=np.zeros(E, bool) if sref["plastic"] is None else sref["plastic"], exceed=sref["exceed"],
        n0=pl["n0"], w_rel=w_rel, w_val=w_val,
        plane_origin=pl["origin"], plane_e1=pl["e1"], plane_e2=pl["e2"], plane_n=n,
        xi_range=pl["xi_range"], eta_range=pl["eta_range"],
        frame_index=np.int64(frame_index), prev_frame_index=np.int64(pfi),
        **{f"sec_xi_{k}": sec_xi[k] for k in ("s", "n0", "w_rel", "w_val")},
        **{f"sec_eta_{k}": sec_eta[k] for k in ("s", "n0", "w_rel", "w_val")},
        sec_band=np.array([bx, by]))
    summ["strain_ref_base"] = sref["ref"]
    return arrays, summ


def stage_validate(ctx: Context) -> dict:
    """S5 검증 (계약 esl_disp_primary.md). 판정 = 변위 4지표(disp_rms_rel·disp_max_rel·reaction_rel·disp_noise_rel),
    변형률 지표는 참고(role=reference, 초과 여부만). 전체 재해석을 못 하면 UNDETERMINED(변형률로 대신 판정하지 않음)."""
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
    frame_index = int(summ["frame"]["frame_index"])
    umax = float(np.max(np.linalg.norm(u_rel, axis=1))) if u_rel.size else 0.0      # 정규화 U = max|u_rel|

    sm = _shell(ctx, model)
    fs = full_solve_decision(ctx, sm, int(model.elem_id.size))
    solved = bool(fs["run"]) and umax > 0
    disp_an = None
    disp_rms_rel = disp_max_rel = reac_abs_rel = reac_sum_rel = lin_rigid_rel = None
    Rr = None
    if solved:
        # 반복법이면 전체계는 rtol = min(설정, 1e-12) (직접법이면 영향 없음)
        sm.iter_opts["rtol"] = min(float(ctx.cfg["solver"]["iter_rtol"]), S5_ITER_RTOL_MAX)
        u_val, Rr = _solver_call(ctx, sm.solve, F, spc)
        # 미소 강체 제거 후 비교(양쪽 독립 → 선형 왕복의 수치 일관성). 노드 집합 = 전 노드(3-2-1 포함)
        d_val, _, _ = kabsch.remove_linear_rigid(X0, u_val[:, :3])
        d_rel, a_rel, w_rel = kabsch.remove_linear_rigid(X0, u_rel)
        delta = d_val - d_rel
        dn = np.linalg.norm(delta, axis=1)
        disp_rms_rel = float(np.sqrt(np.mean(dn ** 2)) / umax)
        disp_max_rel = float(dn.max() / umax)
        sum_abs = float(np.linalg.norm(F, axis=1).sum())
        reac_abs_rel = float(np.linalg.norm(Rr, axis=1).sum() / sum_abs) if sum_abs > 0 else 0.0
        reac_sum_rel = float(np.linalg.norm(Rr.sum(axis=0)) / sum_abs) if sum_abs > 0 else 0.0
        lin_rigid_rel = float(np.max(np.linalg.norm(u_rel - d_rel, axis=1)) / umax)
        eps_sol = sm.strains(u_val)
        is_sup = np.zeros(nid.size, dtype=bool)
        is_sup[[i for i, _ in spc]] = True
        dcfg = ctx.cfg["validation"]
        disp_an = _field.disp_analysis(nid, X0, d_rel, d_val, umax, is_sup, dcfg["disp_top_n"], dcfg["disp_hist_bins"])
    else:
        # 판정 불가(UNDETERMINED): 변형률은 참고용으로만 — u_rel + 응축 회전(rotations_for) 막 변형률
        if not fs["run"]:
            ctx.warnings.append(f"S5 전체 solve 생략({fs['reason']}) — 판정 불가(UNDETERMINED, NO_FULL_SOLVE). "
                                "변형률 참고 지표만 계산")
        else:
            ctx.warnings.append("u_rel 이 전부 0 (변형 없음) — 판정 불가(UNDETERMINED, ZERO_DISP)")
        u_val = _solver_call(ctx, _with_rot, sm, u_rel)
        d_rel = d_val = u_rel
        eps_sol = sm.strains(u_val)

    # hotspot ε_eq: Radioss(t* 프레임, Mid) vs 검증 해 막 변형률(extract.layers) — 참고
    layers = ctx.cfg["extract"]["layers"]
    hs, eps_rad = _eval_hotspots(ctx, model, frame_index)
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

    # 전 요소 재현 정확도(참고)
    ccfg = ctx.cfg["compare"]
    farr, fsum = _field_compare(ctx, model, frame_index, eps_rad, eps_val, d_rel, d_val)
    f_max = fsum["max"]["abs_err_pct"] if fsum["max"] else float("inf")
    f_p90 = fsum["abs_err_pct"]["p90"] if fsum["abs_err_pct"] else float("inf")
    fsum["criteria"] = {"max_err_pct_max": ccfg["max_err_pct_max"], "p90_err_max": ccfg["p90_err_max"]}
    sref = fsum.pop("strain_ref_base")

    noise = summ.get("noise")
    if noise is None:
        ctx.warnings.append("esl_summary.json 에 잡음 바닥(noise) 없음 — esl 단계를 다시 실행 권장")
    n_strain = float(noise["hotspot_strain_rel"]) if noise else None
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

    def judged(name, v, c):
        if v is None:
            return {"metric": name, "value": None, "criterion": c, "pass": None, "status": "skipped", "role": "judge"}
        return {"metric": name, "value": v, "criterion": c, "pass": bool(v <= c), "role": "judge"}

    def ref(name, v, c):
        return {"metric": name, "value": v, "criterion": c, "pass": None, "role": "reference",
                "exceeded": bool(v is not None and not v <= c)}

    def info(name, v):
        return {"metric": name, "value": v, "criterion": None, "pass": None, "role": "info"}

    metrics = [
        judged("disp_rms_rel", disp_rms_rel, crit["disp_rms_rel_max"]),
        judged("disp_max_rel", disp_max_rel, crit["disp_max_rel_max"]),
        judged("reaction_rel", reac_abs_rel, crit["reaction_rel_max"]),
        judged("disp_noise_rel", disp_noise_rel, crit["disp_noise_rel_max"]),
        ref("hotspot1_strain_rel_err", h1, crit["hotspot_strain_rel_err_max"]),
        ref("field_max_err_pct", f_max, ccfg["max_err_pct_max"]),
        ref("field_p90_err_pct", f_p90, ccfg["p90_err_max"]),
        ref("noise_hotspot_strain_rel", n_strain, crit["noise_strain_rel_max"]),
        info("reaction_sum_rel", reac_sum_rel),
        info("u_rel_linear_rigid_rel", lin_rigid_rel),
        info("noise_force_rel", n_force),
    ]
    sref["exceeded"] = any(m["exceeded"] for m in metrics if m["role"] == "reference")
    sref["exceeded_metrics"] = [m["metric"] for m in metrics if m["role"] == "reference" and m["exceeded"]]
    cst = _cum_state(ctx, model)
    if cst is not None:
        with np.load(ctx.p(D_EXTRACT, "strain_frames.npz"), allow_pickle=False) as z:
            fd_ = int(np.flatnonzero(z["frame_index"].astype(np.int64) == int(frame_index))[0])
            ep_raw = np.asarray(z["epsp"][fd_], np.float64) if "epsp" in z.files else np.zeros(model.elem_id.size)
        ep_cum, ep_inc = _cum.series(ep_raw, cst["prev"], cst["modes"]["plastic_strain"])
        sref.update(basis="increment", n_plastic_cum=int(np.sum(ep_cum > 0)),
                    n_plastic_inc=int(np.sum(ep_inc > CUM_EPSP_FLOOR)),
                    cum_max=float(np.max(ep_cum)) if ep_cum.size else 0.0,
                    inc_max=float(np.max(ep_inc)) if ep_inc.size else 0.0)

    undetermined_reason = None
    if not fs["run"]:
        undetermined_reason = "NO_FULL_SOLVE"
    elif umax <= 0:
        undetermined_reason = "ZERO_DISP"
    if undetermined_reason:
        verdict, fail_reasons = "UNDETERMINED", []
    else:
        judge = [m for m in metrics if m["role"] == "judge"]
        verdict = "PASS" if all(m["pass"] is True for m in judge) else "FAIL"
        fail_reasons = [_FAIL_REASON[m["metric"]] for m in judge if m["pass"] is not True]
    reactions = [] if Rr is None else [{"node_id": int(nid[i]), "dof": d, "r": Rr[i].tolist()} for i, d in spc]
    val = {"schema": VALIDATION_SCHEMA, "frame": summ["frame"], "verdict": verdict, "verdict_scheme": VERDICT_SCHEME,
           "undetermined_reason": undetermined_reason, "esl_ref": esl_ref(summ),
           "fail_reasons": fail_reasons, "criteria": crit, "noise": noise, "noise_source": noise_source,
           "metrics": metrics, "full_solve": fs, "hotspots": hots, "hotspots_excluded": excluded,
           "reactions": reactions, "reaction_sum": None if Rr is None else Rr.sum(axis=0),
           "disp": None if disp_an is None else disp_an["summary"], "strain_ref": sref, "field": fsum,
           "created_at": _utcnow()}

    d = ctx.fresh_dir(D_VAL)
    _write_json(ctx.f(d, "validation.json"), val)
    np.savez_compressed(ctx.f(d, "compare_field.npz"), **farr)
    if disp_an is not None:
        np.savez_compressed(ctx.f(d, "compare_disp.npz"), **disp_an["arrays"])
    fmt = ctx.csvfmt()
    csvout.write_validation_csv(ctx.f(d, "validation.csv"), val, fmt)
    if solved:
        csvout.write_csv(ctx.f(d, "compare.csv"),
                         ("node_id", "ux_rel", "uy_rel", "uz_rel", "ux_val", "uy_val", "uz_val", "d_mag"),
                         ((int(nid[i]), *d_rel[i], *d_val[i], dn[i]) for i in range(nid.size)), fmt)
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
    ctx.echo(f"[validate] 변형률 참고: hotspot1 rel_err={h1:.2e} (참고 ≤{crit['hotspot_strain_rel_err_max']:g}, "
             f"비교 {len(hots)}·제외 {len(excluded)}), 최대변형률 요소 오차 {f_max:.3g}% (≤{ccfg['max_err_pct_max']:g}), "
             f"|오차| P90 {f_p90:.3g}% (≤{ccfg['p90_err_max']:g}), 기준 초과 요소 {sref['n_exceed']}/{sref['n_elems']} "
             f"({100 * sref['frac_exceed']:.3g}%)"
             + ("" if sref["plastic"] is None else f", 소성 영역 {sref['plastic']['n_plastic']}")
             + f", valid {fsum['n_valid']}/{fsum['n_elems']} (상승 {fsum['n_rising']}, hold {fsum['n_hold']}, "
             f"low {fsum['n_low']})" + (f", ≤10% 비율 {fsum['frac_within']['10']:.1%}" if fa else "")
             + (" [참고 초과]" if sref["exceeded"] else ""))
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
