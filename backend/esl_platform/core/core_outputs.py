"""코어 산출물(Case 폴더) 읽기·정규화. 코어 형식 변화(esl_core.md §7)를 이 파일 한 곳에서 흡수한다.

- 배열은 `np.load(..., allow_pickle=False)`만. 코어 모듈은 import 하지 않는다(파일 계약만 의존).
- tstar.json: §7.4 지표별 형식(`metrics` 또는 최상위 `max_strain`/`plastic_strain`)과 이전 단일 지표 형식
  (`auto`/`candidates`/`hotspots` + history.csv)을 모두 읽어 API 형식 `{metrics:{name:{tstar,candidates,history}},
  hotspots, default_metric}`으로 바꾼다.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any

import numpy as np

D_EXTRACT, D_TSTAR, D_BC, D_ESL, D_VAL, D_EXPORT = "01_extract", "02_tstar", "03_bc", "04_esl", "05_val", "06_export"
D_REPORT = "07_report"
REPORT_HTML = "report.html"
RUN_JSON = "run.json"
METRICS = ("max_strain", "plastic_strain")
STAGE_DIRS = {"extract": D_EXTRACT, "tstar": D_TSTAR, "esl": D_ESL, "validate": D_VAL, "export": D_EXPORT,
              "report": D_REPORT}
VAL_SNAPSHOT = "05_val"                    # runs/<esl_run_id>/05_val (그 실행의 최신 검증)
VAL_MARKER = "platform_validation_id.txt"  # 스냅샷 05_val 이 어느 검증(DB id)의 것인지


class OutputMissing(RuntimeError):
    def __init__(self, rel: str) -> None:
        super().__init__(f"코어 산출물이 없습니다: {rel}")
        self.rel = rel


def _p(case_dir: str, *parts: str) -> str:
    return os.path.join(case_dir, *parts)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_json_rel(case_dir: str, *parts: str) -> Any:
    p = _p(case_dir, *parts)
    if not os.path.isfile(p):
        raise OutputMissing("/".join(parts))
    return read_json(p)


def load_npz(case_dir: str, *parts: str) -> dict[str, np.ndarray]:
    p = _p(case_dir, *parts)
    if not os.path.isfile(p):
        raise OutputMissing("/".join(parts))
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def run_record(case_dir: str) -> dict[str, Any]:
    p = _p(case_dir, RUN_JSON)
    if not os.path.isfile(p):
        return {}
    try:
        d = read_json(p)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def stage_record(case_dir: str, stage: str) -> dict[str, Any]:
    return dict((run_record(case_dir).get("stages") or {}).get(stage) or {})


# ---------------------------------------------------------------- 모델·변위
def model_nodes(case_dir: str) -> tuple[np.ndarray, np.ndarray]:
    m = load_npz(case_dir, D_EXTRACT, "model.npz")
    return np.asarray(m["node_id"], np.int64), np.asarray(m["x0"], np.float64)


def disp_frame(case_dir: str, frame_index: int) -> np.ndarray | None:
    """(N,3) 변위 또는 해당 프레임 없으면 None."""
    try:
        d = load_npz(case_dir, D_EXTRACT, "disp.npz")
    except OutputMissing:
        return None
    hit = np.flatnonzero(np.asarray(d["frame_index"]) == int(frame_index))
    if hit.size != 1:
        return None
    return np.asarray(d["u"][int(hit[0])], np.float64)


def disp_frames(case_dir: str) -> list[int]:
    try:
        d = load_npz(case_dir, D_EXTRACT, "disp.npz")
    except OutputMissing:
        return []
    return [int(v) for v in np.asarray(d["frame_index"]).tolist()]


# ---------------------------------------------------------------- t*
def _num(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pt(d: dict) -> dict[str, Any]:
    return {"frame_index": _int(d.get("frame_index")), "time": _num(d, "time"),
            "elem_id": _int(d.get("elem_id")), "value": _num(d, "value", "eps_eq", "eps_max", "max")}


def _history(h: Any) -> dict[str, list[float]]:
    if not isinstance(h, dict):
        return {"time": [], "value": []}
    t = h.get("time") or []
    for k in ("value", "m", "eps_max", "max"):
        if h.get(k) is not None:
            return {"time": [float(x) for x in t], "value": [float(x) for x in h[k]]}
    return {"time": [float(x) for x in t], "value": []}


def _history_csv(case_dir: str) -> dict[str, list[float]]:
    p = _p(case_dir, D_TSTAR, "history.csv")
    out: dict[str, list[float]] = {"time": [], "value": []}
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        head = next(rd, None) or []
        if "time" not in head:
            return out
        it = head.index("time")
        iv = next((head.index(k) for k in ("eps_max", "value", "m") if k in head), None)
        if iv is None:
            return out
        for row in rd:
            try:
                out["time"].append(float(row[it]))
                out["value"].append(float(row[iv]))
            except (ValueError, IndexError):
                continue
    return out


def _metric_block(m: dict) -> dict[str, Any]:
    ts = m.get("tstar") or m.get("auto") or m.get("selected") or {}
    cands = []
    for i, c in enumerate(m.get("candidates") or []):
        row = {"rank": _int(c.get("rank")) or i + 1, **_pt(c)}
        row["in_D"] = None if c.get("in_D") is None else bool(c["in_D"])
        cands.append(row)
    out = {"tstar": _pt(ts) if ts else None, "candidates": cands, "history": _history(m.get("history"))}
    if m.get("hotspots") is not None:
        out["hotspots"] = _hotspots(m.get("hotspots"))
    if m.get("error"):
        out["error"] = str(m["error"])
    return out


def _hotspots(raw: Any) -> list[dict[str, Any]]:
    out = []
    for i, h in enumerate(raw or []):
        if not isinstance(h, dict):
            continue
        rising = h.get("rising")
        out.append({"rank": _int(h.get("rank")) or i + 1, "elem_id": _int(h.get("elem_id")),
                    "value": _num(h, "value", "eps_eq", "eps_rad"), "centroid": h.get("centroid"),
                    "rising": None if rising is None else bool(rising)})
    return out


def tstar_info(case_dir: str) -> dict[str, Any]:
    tj = read_json_rel(case_dir, D_TSTAR, "tstar.json")
    metrics: dict[str, dict[str, Any]] = {}
    hotspots_raw = tj.get("hotspots")
    if isinstance(tj.get("metrics"), dict):
        src = tj["metrics"]
    else:
        src = {k: tj[k] for k in METRICS if isinstance(tj.get(k), dict)}
    if src:
        for name, m in src.items():
            if isinstance(m, dict):
                metrics[name] = _metric_block(m)
    else:  # 이전 단일 지표 형식
        blk = _metric_block(tj)
        if not blk["history"]["time"]:
            blk["history"] = _history_csv(case_dir)
        metrics["max_strain"] = blk
    default = tj.get("metric") if tj.get("metric") in metrics else None
    if default is None:
        default = "max_strain" if "max_strain" in metrics else next(iter(metrics), None)
    hots = _hotspots(hotspots_raw)
    if not hots and default and metrics[default].get("hotspots"):
        hots = metrics[default]["hotspots"]
    for blk in metrics.values():
        blk.setdefault("hotspots", hots)
    frames_d = [_int(x.get("frame_index")) for x in (tj.get("frames_D") or []) if isinstance(x, dict)]
    return {"metrics": metrics, "hotspots": hots, "default_metric": default, "frames_D": frames_d}


# ---------------------------------------------------------------- 지지점·ESL·검증
def esl_summary(case_dir: str) -> dict[str, Any]:
    return read_json_rel(case_dir, D_ESL, "esl_summary.json")


def f_eq(case_dir: str) -> dict[str, np.ndarray]:
    return load_npz(case_dir, D_ESL, "f_eq.npz")


def validation_json(case_dir: str) -> dict[str, Any]:
    return read_json_rel(case_dir, D_VAL, "validation.json")


def metric_value(val: dict[str, Any], name: str) -> float | None:
    for m in val.get("metrics") or []:
        if isinstance(m, dict) and m.get("metric") == name:
            v = m.get("value")
            return None if v is None else float(v)
    v = val.get(name)
    return None if v is None else float(v)


# ---------------------------------------------------------------- ESL 실행 스냅샷(runs/<esl_run_id>/)
# 코어 04_esl·03_bc 는 ESL 계산마다 새로 쓰인다(이전 것은 _backup 으로 이동). 등록 시 그 내용을
# runs/<esl_run_id>/{03_bc,04_esl} 로 보존(하드링크, 안 되면 복사)해 두고, 검증·내보내기 직전에 디스크의
# 04_esl 이 그 실행의 것인지(esl_summary.json tag = ESL_SOLVE 작업 id) 확인한다. 다르면 스냅샷에서 되돌린다.
RUNS_DIR = "runs"
SNAPSHOT_DIRS = (D_BC, D_ESL)


def run_snapshot_dir(case_dir: str, run_id: str) -> str:
    return _p(case_dir, RUNS_DIR, run_id)


def esl_tag(esl_dir_parent: str) -> str | None:
    """<parent>/04_esl/esl_summary.json 의 tag(없거나 못 읽으면 None)."""
    try:
        return read_json(_p(esl_dir_parent, D_ESL, "esl_summary.json")).get("tag")
    except (OSError, ValueError, AttributeError):
        return None


def esl_source_dir(case_dir: str, run: dict[str, Any]) -> str | None:
    """ESL 실행 run 의 04_esl 이 있는 상위 폴더: 스냅샷(우선) 또는 Case 폴더(디스크 tag 가 같을 때). 없으면 None."""
    snap = run_snapshot_dir(case_dir, run["id"])
    if esl_tag(snap) == run["job_id"]:
        return snap
    if esl_tag(case_dir) == run["job_id"]:
        return case_dir
    return None


def val_snapshot_dir(case_dir: str, run_id: str) -> str:
    return _p(case_dir, RUNS_DIR, run_id, VAL_SNAPSHOT)


def val_marker(d: str) -> str | None:
    try:
        with open(os.path.join(d, VAL_MARKER), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None
