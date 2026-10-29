"""③ gmsh 쉘 메시 (계약 esl_bead_doe.md §7, BD-D-20, V-BD-6).

gmsh 는 Python 모듈로 **코어 하위 프로세스 안에서** 호출한다(외부 명령 아님). ``run_isolated`` 가
``multiprocessing``(spawn) 자식 프로세스를 띄워 타임아웃(``mesh.timeout_s``)·크래시를 격리하고(둘 다 ``FAILED_MESH``),
자식은 표준 출력(OCC 메시지)을 ``mesh.log`` 로 돌린 뒤 ``mesh_file`` 로 실제 메싱을 한다.

절차(§7.1): ``initialize(["-noenv"], readConfigFiles=False)``, Terminal 0, NumThreads 1, OCCSewFaces = mesh.occ_sew_faces(계약 기본 0),
``occ.importShapes`` → synchronize, 크기 MeshSizeMax = h, Min = h × min_size_factor, FromCurvature = curvature_n,
ExtendFromBoundary 1, Algorithm = mesh.algorithm(8), RecombineAll 1, RecombinationAlgorithm 1(blossom),
SubdivisionAlgorithm 0, ElementOrder 1, Smoothing 3, ``generate(2)``.
출력: 노드 1..N(gmsh 태그 순 재번호, 요소가 안 쓰는 노드 제거), 요소 1..E(gmsh 요소 태그 순, CQUAD4/CTRIA3,
면적 ≤ 1e-12·중복 노드 요소 제거), 법선을 기준 n 쪽으로 정렬(``esl.opt.target.align_normals``), PID 1, t·E·ν = props.
``mesh.npz`` 는 zip 날짜를 고정해 같은 입력 → 같은 바이트(단일 스레드 gmsh 결정성).
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
import zipfile

import numpy as np

from esl.errors import EslError

MESH_NPZ = "mesh.npz"
MESH_JSON = "mesh.json"
MESH_LOG = "mesh.log"
_AREA_MIN = 1e-12
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MESH_KEYS = ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu")


def available() -> tuple[bool, str | None]:
    """(gmsh import 가능, 버전)."""
    try:
        import gmsh  # noqa: F401
    except Exception:                                       # noqa: BLE001 - 공유 라이브러리 누락(OSError) 포함
        return False, None
    try:
        return True, str(gmsh.__version__)
    except AttributeError:
        return True, None


def save_npz_det(path: str, arrays: dict) -> str:
    """allow_pickle=False 로 읽히는 npz 를 zip 날짜 고정·키 정렬로 쓴다(바이트 결정성)."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for k in sorted(arrays):
            zi = zipfile.ZipInfo(f"{k}.npy", date_time=_ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with zf.open(zi, "w", force_zip64=True) as fh:
                np.lib.format.write_array(fh, np.ascontiguousarray(arrays[k]), allow_pickle=False)
    os.replace(tmp, path)
    return path


def check_h(h: float, mcfg: dict) -> float:
    h = float(h)
    if not (float(mcfg["size_min_mm"]) <= h <= float(mcfg["size_max_mm"])):
        raise EslError("INPUT_INVALID", f"요소 크기 {h} mm 가 범위 {mcfg['size_min_mm']}..{mcfg['size_max_mm']} 밖")
    return h


def gmsh_options(h: float, mcfg: dict) -> dict:
    return {"Mesh.MeshSizeMax": float(h), "Mesh.MeshSizeMin": float(h) * float(mcfg["min_size_factor"]),
            "Mesh.MeshSizeFromCurvature": int(mcfg["curvature_n"]), "Mesh.MeshSizeExtendFromBoundary": 1,
            "Mesh.Algorithm": int(mcfg["algorithm"]), "Mesh.RecombineAll": 1, "Mesh.RecombinationAlgorithm": 1,
            "Mesh.SubdivisionAlgorithm": 0, "Mesh.ElementOrder": 1, "Mesh.Smoothing": 3}


def _elem_area(X, conn, et):
    a = np.cross(X[conn[:, 1]] - X[conn[:, 0]], X[conn[:, 2]] - X[conn[:, 0]])
    area = 0.5 * np.linalg.norm(a, axis=1)
    q = et == 4
    if q.any():
        b = np.cross(X[conn[q, 2]] - X[conn[q, 0]], X[conn[q, 3]] - X[conn[q, 0]])
        area[q] += 0.5 * np.linalg.norm(b, axis=1)
    return area


def _extract(gmsh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags, dtype=np.int64)
    X = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    o = np.argsort(tags, kind="stable")
    tags, X = tags[o], X[o]
    etypes, etags, enodes = gmsh.model.mesh.getElements(2)
    rows, et, eg = [], [], []
    for t, tg, nd in zip(etypes, etags, enodes):
        t = int(t)
        if t == 2:
            k = 3
        elif t == 3:
            k = 4
        else:
            raise EslError("FAILED_MESH", f"gmsh 2D 요소 형식 {t} (1차 tri/quad 만)")
        nd = np.asarray(nd, dtype=np.int64).reshape(-1, k)
        c = np.full((nd.shape[0], 4), -1, dtype=np.int64)
        c[:, :k] = nd
        rows.append(c)
        et.append(np.full(nd.shape[0], k, dtype=np.int64))
        eg.append(np.asarray(tg, dtype=np.int64))
    if not rows:
        raise EslError("FAILED_MESH", "gmsh 가 2D 요소를 만들지 못함")
    C, ET, EG = np.concatenate(rows), np.concatenate(et), np.concatenate(eg)
    o = np.argsort(EG, kind="stable")
    C, ET = C[o], ET[o]
    pos = np.searchsorted(tags, np.where(C >= 0, C, tags[0]))
    if np.any(tags[np.minimum(pos, tags.size - 1)][C >= 0] != C[C >= 0]):
        raise EslError("FAILED_MESH", "gmsh 요소가 없는 노드를 참조")
    conn = np.where(C >= 0, pos, -1)
    return X, conn, ET


def build_mesh(X, conn, et, props: dict, normal_ref=None) -> tuple[dict, dict]:
    """정리(퇴화 요소 제거·미사용 노드 제거·재번호)·법선 정렬 → (mesh dict, info)."""
    from esl.library import normalize as nz
    from esl.opt.target import align_normals
    n_in = int(conn.shape[0])
    q = et == 4
    k = np.where(q, 4, 3)
    dup = np.zeros(conn.shape[0], bool)
    for a in range(4):
        for b in range(a + 1, 4):
            use = (b < k)
            dup |= use & (conn[:, a] == conn[:, b])
    area = _elem_area(X, np.where(conn >= 0, conn, conn[:, :1]), et)
    keep = ~dup & (area > _AREA_MIN)
    conn, et = conn[keep], et[keep]
    used = np.unique(conn[conn >= 0])
    remap = -np.ones(X.shape[0], dtype=np.int64)
    remap[used] = np.arange(used.size)
    conn = np.where(conn >= 0, remap[np.maximum(conn, 0)], -1)
    X = X[used]
    ne = int(conn.shape[0])
    mesh = {"node_id": np.arange(1, X.shape[0] + 1, dtype=np.int64), "x0": X,
            "elem_id": np.arange(1, ne + 1, dtype=np.int64), "elem_type": et.astype(np.int8), "conn": conn,
            "elem_pid": np.ones(ne, dtype=np.int64), "thickness": np.full(ne, float(props["t"])),
            "E": np.full(ne, float(props["E"])), "nu": np.full(ne, float(props["nu"]))}
    n = normal_ref
    if n is None:
        n = nz.frame(X, None, conn, et)["n"]
    c2, flip = align_normals(mesh, n)
    mesh["conn"] = c2
    return mesh, {"n_removed_elems": n_in - ne, "n_flipped": int(flip.sum())}


def quality(mesh: dict, cfg: dict, opt_cfg: dict) -> dict:
    """esl.opt.mesh_check 지표 + quad_frac·max_elems → {errors, warnings, metrics, quad_frac}."""
    from esl.opt import mesh_check
    mc = cfg["mesh"]
    et = np.asarray(mesh["elem_type"]).astype(int)
    ne = int(et.size)
    qf = float(np.sum(et == 4)) / ne if ne else 0.0
    if ne > int(mc["max_elems"]):
        return {"errors": [{"code": "MESH_TOO_LARGE", "message": f"요소 {ne} > 상한 {mc['max_elems']}"}],
                "warnings": [], "metrics": {"n_elems": ne}, "quad_frac": qf}
    oc = dict(opt_cfg)
    oc["template"] = dict(opt_cfg["template"], max_elems=int(mc["max_elems"]), max_tria_frac=1.0 - float(mc["min_quad_frac"]))
    r = mesh_check.check(mesh, "S2", oc)
    warns = [w for w in r["warnings"] if w["code"] not in ("NORMALS_ALIGNED", "TRIA_FRAC", "COMPONENTS")]
    errs = list(r["errors"])
    if int(r["metrics"].get("n_components") or 1) > 1:
        errs.append({"code": "MESH_DISCONNECTED", "message": f"메시 연결 성분 {r['metrics']['n_components']}개 — 면이 서로 "
                                                             "붙어 있지 않은 형상(설정 bead_doe.mesh.occ_sew_faces 1 검토)"})
    if qf < float(mc["min_quad_frac"]):
        warns.append({"code": "MESH_QUAD_FRAC", "message": f"4각 비율 {qf:.3f} < {mc['min_quad_frac']}"})
    return {"errors": errs, "warnings": warns, "metrics": r["metrics"], "quad_frac": qf}


def mesh_file(src: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None, normal_ref=None,
              out_dir: str | None = None, step_out: str | None = None) -> tuple[dict, dict]:
    """BREP/STEP → (mesh dict, mesh.json dict). out_dir 이 있으면 mesh.npz·mesh.json 을 쓴다. 이 프로세스 안에서 실행."""
    from esl.doe import opt_settings
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise EslError("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    mc = cfg["mesh"]
    h = check_h(h, mc)
    opts = gmsh_options(h, mc)
    t0 = time.monotonic()
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", int(mc.get("occ_sew_faces", 0)))
        try:
            gmsh.model.occ.importShapes(os.fspath(src))
            gmsh.model.occ.synchronize()
        except Exception as exc:                            # noqa: BLE001
            raise EslError("FAILED_MESH", f"형상 파일을 읽지 못함: {exc}") from None
        step_done = None
        if step_out:
            gmsh.write(os.fspath(step_out))
            step_done = os.path.basename(step_out)
        for k, v in opts.items():
            gmsh.option.setNumber(k, v)
        try:
            gmsh.model.mesh.generate(2)
        except Exception as exc:                            # noqa: BLE001
            raise EslError("FAILED_MESH", f"gmsh 메싱 실패: {exc}") from None
        X, conn, et = _extract(gmsh)
        ver = str(getattr(gmsh, "__version__", ""))
    finally:
        gmsh.finalize()
    mesh, info = build_mesh(X, conn, et, props, normal_ref)
    oc = opt_cfg or opt_settings(None)
    qual = quality(mesh, cfg, oc)
    meta = {"schema": "esl/doe_mesh/1", "gmsh_version": ver, "options": opts, "h": h, "props": dict(props),
            "n_nodes": int(mesh["node_id"].size), "n_elems": int(mesh["elem_id"].size), "quad_frac": qual["quad_frac"],
            "quality": qual["metrics"], "errors": qual["errors"], "warnings": qual["warnings"], **info,
            "step": step_done, "seconds": round(time.monotonic() - t0, 3)}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        save_npz_det(os.path.join(out_dir, MESH_NPZ), {k: mesh[k] for k in MESH_KEYS})
        from esl.library import _util as U
        U.write_json(os.path.join(out_dir, MESH_JSON), {k: v for k, v in meta.items() if k != "seconds"}
                     | {"seconds": meta["seconds"]})
    if qual["errors"]:
        e = qual["errors"][0]
        raise EslError("FAILED_MESH", f"메시 품질 오류 {e['code']}: {e['message']}")
    return mesh, meta


def load_mesh(d: str) -> dict:
    from esl.library import _util as U
    arr = U.load_npz(os.path.join(d, MESH_NPZ))
    return {k: arr[k] for k in MESH_KEYS}


# ---------------------------------------------------------------- 하위 프로세스 격리
def write_step(src: str, dst: str) -> str:
    """BREP/STEP → STEP(OCC 형상, 메시 없음). 이 프로세스 안에서 실행."""
    try:
        import gmsh
    except Exception:                                       # noqa: BLE001
        raise EslError("GMSH_UNAVAILABLE", "gmsh 모듈을 불러오지 못함") from None
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)
        try:
            gmsh.model.occ.importShapes(os.fspath(src))
            gmsh.model.occ.synchronize()
            gmsh.write(os.fspath(dst))
        except Exception as exc:                            # noqa: BLE001
            raise EslError("FAILED_MESH", f"STEP 내보내기 실패: {exc}") from None
    finally:
        gmsh.finalize()
    return dst


def _child(job_path: str) -> int:
    with open(job_path, "r", encoding="utf-8") as fh:
        job = json.load(fh)
    out = job["out_dir"]
    err = os.path.join(out, "mesh_error.json")
    try:
        if job.get("step_only"):
            write_step(job["src"], job["step_out"])
            return 0
        mesh_file(job["src"], job["h"], job["cfg"], job["props"], opt_cfg=job.get("opt_cfg"),
                  normal_ref=job.get("normal_ref"), out_dir=out, step_out=job.get("step_out"))
    except EslError as exc:
        with open(err, "w", encoding="utf-8") as fh:
            json.dump({"code": exc.code, "message": exc.message}, fh, ensure_ascii=False)
        return 3
    return 0


def _child_entry(job_path: str, log_path: str) -> None:
    """spawn 자식 진입점: fd 1·2 → mesh.log, 실패는 mesh_error.json + 종료코드 3."""
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    sys.exit(_child(job_path))


def _spawn(job: dict, out_dir: str, to: float) -> int:
    from esl.library import _util as U
    jp = os.path.join(out_dir, "mesh_job.json")
    U.write_json(jp, job)
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_child_entry, args=(jp, os.path.join(out_dir, MESH_LOG)), daemon=True)
    p.start()
    p.join(to)
    if p.is_alive():
        p.terminate()
        p.join(5)
        if p.is_alive():
            p.kill()
            p.join()
        raise EslError("FAILED_MESH", f"gmsh 하위 프로세스가 제한 시간 {to:g} s 안에 끝나지 않음(mesh.timeout_s)")
    ep = os.path.join(out_dir, "mesh_error.json")
    if p.exitcode != 0:
        if os.path.isfile(ep):
            e = U.read_json(ep)
            raise EslError(str(e.get("code") or "FAILED_MESH"), str(e.get("message") or ""))
        raise EslError("FAILED_MESH", f"gmsh 하위 프로세스가 비정상 종료(코드 {p.exitcode}) — {MESH_LOG} 확인")
    return 0


def export_step_isolated(src: str, dst: str, cfg: dict, timeout_s: float | None = None) -> str:
    """하위 프로세스에서 BREP → STEP (BD-D-18). gmsh 없음 → GMSH_UNAVAILABLE."""
    out_dir = os.path.dirname(os.path.abspath(dst))
    os.makedirs(out_dir, exist_ok=True)
    ep = os.path.join(out_dir, "mesh_error.json")
    if os.path.exists(ep):
        os.remove(ep)
    to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
    _spawn({"step_only": True, "src": os.path.abspath(src), "out_dir": out_dir, "step_out": os.path.abspath(dst)},
           out_dir, to)
    for name in ("mesh_job.json",):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            os.remove(p)
    return dst


def run_isolated(src: str, out_dir: str, h: float, cfg: dict, props: dict, *, opt_cfg: dict | None = None,
                 normal_ref=None, step_out: str | None = None, timeout_s: float | None = None) -> tuple[dict, dict]:
    """하위 프로세스에서 ``mesh_file`` → (mesh, mesh.json). 타임아웃·크래시 → FAILED_MESH, gmsh 없음 → GMSH_UNAVAILABLE."""
    from esl.doe import opt_settings
    from esl.library import _util as U
    os.makedirs(out_dir, exist_ok=True)
    job = {"src": os.path.abspath(src), "out_dir": os.path.abspath(out_dir), "h": float(h), "cfg": cfg,
           "props": {k: float(v) for k, v in props.items()}, "opt_cfg": opt_cfg or opt_settings(None),
           "normal_ref": None if normal_ref is None else [float(x) for x in normal_ref],
           "step_out": None if not step_out else os.path.abspath(step_out)}
    for name in (MESH_NPZ, MESH_JSON, "mesh_error.json"):
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            os.remove(p)
    to = float(timeout_s if timeout_s is not None else cfg["mesh"]["timeout_s"])
    t0 = time.monotonic()
    _spawn(job, out_dir, to)
    meta = U.read_json(os.path.join(out_dir, MESH_JSON))
    meta["wall_seconds"] = round(time.monotonic() - t0, 3)
    return load_mesh(out_dir), meta

