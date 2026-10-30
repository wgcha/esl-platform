"""VERIFY_POST(SLOT 레인, 계약 esl_scx_relay.md §9.3·SR-D-16): 검증 낙하 결과 h3d → 서버 추출 → 원 낙하와 비교 → 등록.

- H3D_EXTRACT(LOCAL): 실행기 기존 hw 실행(altair.max_concurrent_hw 세마포어·자원 제한·취소) — 작업 폴더 `_verify/<id>/h3dwork`,
  출력 `h3dwork/raw`(params.h3d = VERIFY_DROP 성공 때 큐에 넣으며 채움). 같은 추출 TCL·hot_k·top_n(원 Case 추출 작업 설정).
- VD_EXTRACT: 코어 extract(자식) — rad = 원 Case rad(읽기만, 위상·ID 같음), results = h3dwork/raw, out = `_verify/<id>/work`.
  모핑 좌표 때문에 rad↔h3d 좌표 확인 허용치(coord_check.max_rel)를 모핑 최대 이동량만큼 넓힌다(위상 검사는 비교에서).
- VD_COMPARE: 코어 vd_compare(자식) — 원 Case 01_extract vs work/01_extract, 검증 쪽 기준 좌표 = morph.npz(VD_PREP), t* = 원 Case
  확정 t* 프레임 시각, 예측 = verify_drops.predicted → compare.json·compare.csv.
- VD_REGISTER: verify_drops.result(rows·hot·warnings·tstar) + phase DONE. artifacts 는 쓰지 않는다(artifacts.rel 은 Case 폴더
  기준이고 검증 산출물은 _verify/<id> 에만 있음 — 받기는 /verify-drops/{id}/compare.csv·/files/{name}).
쓰기 = `_verify/<id>/` 아래만. Case 폴더·입력은 읽기만.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

import numpy as np

from esl_platform.core.paths import esl_subdir
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import verify as vd_repo

from .scx_verify import _fail, _read, safe_path


def h3d_work(ex) -> str:
    work = safe_path(ex.cdir, "h3dwork")
    os.makedirs(work, exist_ok=True)
    return work


def _case_dir(ex) -> str:
    return esl_subdir(ex.settings, ex.case["folder_name"])


def run_step(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    key = st["step_key"]
    if key == "H3D_EXTRACT":
        out = ex._run_h3d(st, log_path)
        with ex._tx() as conn:
            jobs_repo.patch_result(conn, ex.job["id"], ex.token, {"h3d_extract": out.get("done")})
        return out
    if key == "VD_EXTRACT":
        return _extract(ex, st, log_path)
    if key == "VD_COMPARE":
        return _compare(ex, st, log_path)
    if key == "VD_REGISTER":
        return _register(ex, log_path)
    raise _fail("INTERNAL_ERROR", f"알 수 없는 step {key}")


def _coord_rel(ex) -> float:
    """coord_check.max_rel(검증): 기본값 + 2 × 모핑 최대 이동 / 대상 파트 bbox 대각."""
    cfg = (ex.job["params"] or {}).get("settings") or {}
    base = float(((cfg.get("coord_check") or {}).get("max_rel")) or 0.005)
    st = _read(os.path.join(ex.cdir, "stage.json")) or {}
    md = float(((st.get("morph") or {}).get("max_disp")) or 0.0)
    try:
        with np.load(os.path.join(_case_dir(ex), "01_extract", "model.npz"), allow_pickle=False) as z:
            x = np.asarray(z["x0"], dtype=np.float64)
        diag = float(np.linalg.norm(x.max(axis=0) - x.min(axis=0))) if x.size else 0.0
    except (OSError, KeyError, ValueError):
        diag = 0.0
    return base + (2.0 * md / diag if diag > 0 else 0.0)


def _extract(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    p = ex.job["params"] or {}
    raw = (p.get("h3d") or {}).get("out_dir")
    if not raw or os.path.normcase(os.path.normpath(raw)) != os.path.normcase(os.path.join(ex.cdir, "h3dwork", "raw")):
        raise _fail("PATH_UNSAFE", "검증 추출 입력 폴더가 _verify/<id>/h3dwork/raw 가 아닙니다")
    work = safe_path(ex.cdir, "work")
    os.makedirs(work, exist_ok=True)
    cfg = copy.deepcopy(p.get("settings") or {})
    rel = _coord_rel(ex)
    cfg["coord_check"] = {**(cfg.get("coord_check") or {}), "max_rel": rel}
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"[esl-worker] VD_EXTRACT: 원 Case rad(위상) + 검증 h3d 추출 결과 → _verify/{ex.job['verify_drop_id']}/work"
                 f" (coord_check.max_rel {rel:.4g} — 모핑 허용)\n")
    ex._run_core(st, log_path, {"stage": "extract", "cfg": cfg, "rad": ex.case["rad_path"], "results": raw, "out": work})
    from esl_platform.core.core_outputs import stage_record

    rec = stage_record(work, "extract")
    warns = [f"[검증 추출] {w}" for w in rec.get("warnings") or []]
    if warns:
        with ex._tx() as conn:
            jobs_repo.add_warnings(conn, ex.job["id"], ex.token, warns[:20])
    return {"core_stage": "extract", "warnings": len(warns)}


def _tstar_time(ex) -> float | None:
    ts = ex.case.get("tstar") or {}
    fi = ts.get("frame_index")
    if fi is None:
        return None
    try:
        with np.load(os.path.join(_case_dir(ex), "01_extract", "strain_frames.npz"), allow_pickle=False) as z:
            fr, t = np.asarray(z["frame_index"]), np.asarray(z["time"], dtype=np.float64)
    except (OSError, KeyError, ValueError):
        return None
    k = np.nonzero(fr == int(fi))[0]
    return float(t[k[0]]) if k.size else None


def _compare(ex, st: dict[str, Any], log_path: str) -> dict[str, Any]:
    with ex.engine.connect() as conn:
        d = vd_repo.get_drop(conn, ex.job["verify_drop_id"])
    vc = ex.settings.verify_drop.compare
    vd = {"orig_out": _case_dir(ex), "verify_out": safe_path(ex.cdir, "work"), "tstar_time": _tstar_time(ex),
          "predicted": d.get("predicted") or {}, "same_tol": float(vc.same_tol), "hot_n": int(vc.hot_n),
          "morph_npz": safe_path(ex.cdir, "morph.npz"), "out_json": safe_path(ex.cdir, "compare.json"),
          "out_csv": safe_path(ex.cdir, "compare.csv")}
    ex._run_core(st, log_path, {"stage": "vd_compare", "vd": vd})
    res = _read(vd["out_json"]) or {}
    return {"rows": len(res.get("rows") or []), "tstar_time": vd["tstar_time"]}


def _register(ex, log_path: str) -> dict[str, Any]:
    res = _read(os.path.join(ex.cdir, "compare.json"))
    if not isinstance(res, dict) or not isinstance(res.get("rows"), list):
        raise _fail("PREREQUISITE_MISSING", "compare.json 이 없습니다(VD_COMPARE 부터 다시)")
    p = ex.job["params"] or {}
    with ex.engine.connect() as conn:
        job = jobs_repo.get_job(conn, ex.job["id"])
    warns = list(res.get("warnings") or []) + [str(w) for w in p.get("warnings_fetch") or []]
    warns += [str(w) for w in (job or {}).get("warnings") or [] if str(w).startswith("[검증 추출]")]
    out = {"rows": res["rows"], "hot": res.get("hot") or {}, "warnings": warns[:50], "tstar": res.get("tstar") or {},
           "same_tol": res.get("same_tol"), "job_id": ex.job["id"]}
    with ex._tx() as conn:
        jobs_repo.assert_lease(conn, ex.job["id"], ex.token)
        vd_repo.update_drop(conn, ex.job["verify_drop_id"], result=json.loads(json.dumps(out)), phase="DONE")
        jobs_repo.patch_result(conn, ex.job["id"], ex.token,
                               {"registered": {"rows": len(out["rows"]), "warnings": len(warns)}})
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"[esl-worker] VD_REGISTER: 비교 {len(out['rows'])}행 등록 — 검증 낙하 완료(DONE)\n")
    return {"registered": True}


__all__ = ["run_step", "h3d_work"]
