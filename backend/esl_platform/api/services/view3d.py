"""④ ESL 3D 하중 보기 서비스(계약 esl_3d_load.md §3·§4): 입력 해석 → 캐시 키 → (없거나 달라지면) 생성 → 파일 경로.

- 파생 캐시 위치 ``<case_dir>/runs/<esl_run_id>/view3d/{manifest.json,part.glb,part_lod.glb,values.bin}``.
  코어 ``04_esl`` 에는 쓰지 않는다. 요청마다 입력 4파일 (상대경로, size, mtime_ns)로 key 를 다시 계산(stat 만)해
  manifest.key 와 다르면 재생성하고, 이전 폴더는 ``_backup/<UTC ts>/runs/<id>/view3d`` 로 **이동**한다(삭제 안 함).
- 생성은 프로세스당 세마포어 1개. 대기 ``view3d.build_wait_s`` 초과 시 503 VIEW3D_BUSY.
- 쓰기는 ``view3d.tmp-<uuid>/`` 에 모두 쓴 뒤 ``os.replace`` 로 올린다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import threading
import uuid
from typing import Any

import numpy as np

from ...core import core_outputs as co
from ...core.errors import DomainError, conflict, not_found
from ...core.repositories import cases as cases_repo
from ..context import AppContext
from .common import case_dir, load_case

BUILDER_VERSION = 1                       # esl.view3d.BUILDER_VERSION 과 같아야 함(시험이 확인)
DIR = "view3d"
FILES = {"part.glb": "model/gltf-binary", "part_lod.glb": "model/gltf-binary", "values.bin": "application/octet-stream"}
MANIFEST = "manifest.json"
_BUILD_LOCK = threading.Semaphore(1)      # 프로세스당 생성 1개(메모리 상한)
_CFG_KEYS = ("max_nodes", "max_glb_bytes", "lod_min_nodes", "lod_target_vertices", "top_max", "cluster_k_max",
             "kmeans_max_iter")


class Inputs:
    """한 요청에서 해석한 입력: 경로·run·캐시 폴더·key."""

    def __init__(self, ctx: AppContext, run: dict[str, Any], cdir: str, src: str) -> None:
        self.ctx, self.run, self.cdir, self.src = ctx, run, cdir, src
        self.f_eq = os.path.join(src, co.D_ESL, "f_eq.npz")
        self.u_rel = os.path.join(src, co.D_ESL, "u_rel.npz")
        self.support = os.path.join(src, co.D_BC, "support.json")
        self.model = os.path.join(cdir, co.D_EXTRACT, "model.npz")
        self.dir = os.path.join(cdir, co.RUNS_DIR, run["id"], DIR)
        self.key = self._key()

    def _stat(self, path: str) -> list[Any]:
        rel = os.path.relpath(path, self.cdir).replace(os.sep, "/")
        try:
            st = os.stat(path)
        except OSError:
            return [rel, None, None]
        return [rel, st.st_size, st.st_mtime_ns]

    def _key(self) -> str:
        cfg = self.ctx.settings.view3d
        doc = {"builder_version": BUILDER_VERSION, "esl_run_id": self.run["id"],
               "cfg": {k: getattr(cfg, k) for k in _CFG_KEYS}, "units": _units(self.ctx),
               "inputs": [self._stat(p) for p in (self.f_eq, self.u_rel, self.support, self.model)]}
        return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _units(ctx: AppContext) -> dict[str, str]:
    u = ((ctx.config.core or {}).get("units") or {})
    return {"length": str(u.get("length") or "mm"), "force": str(u.get("force") or "N"),
            "pressure": str(u.get("stress") or "MPa")}


# ---------------------------------------------------------------- 입력 해석(오류 판정은 /forces 와 같음)
def resolve(ctx: AppContext, run_id: str) -> Inputs:
    if not ctx.settings.view3d.enabled:
        raise not_found("VIEW3D_DISABLED", "3D 하중 보기가 설정에서 꺼져 있습니다(view3d.enabled=false)")
    with ctx.engine.connect() as conn:
        run = cases_repo.get_esl_run(conn, run_id)
        if run is None:
            raise not_found("ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다")
        case = load_case(conn, run["case_id"])
    if run.get("status") == "FAILED":
        raise conflict("ESL_RUN_FAILED", "실패한 ESL 실행입니다(3D 하중 보기를 만들 수 없음)")
    cdir = case_dir(ctx, case)
    src = co.esl_source_dir(cdir, run)
    if src is None:
        if case.get("current_esl_run_id") != run_id or co.esl_tag(cdir) is not None:
            raise conflict("ESL_RUN_NOT_CURRENT", "이 ESL 결과의 산출물이 없습니다(이후 ESL 계산으로 바뀜)")
        src = cdir                          # tag 기록 이전 형식의 현재 결과
    inp = Inputs(ctx, run, cdir, src)
    for p in (inp.f_eq, inp.u_rel, inp.model):
        if not os.path.isfile(p):
            raise conflict("PREREQUISITE_MISSING", "ESL 산출물(04_esl/f_eq.npz·u_rel.npz 또는 01_extract/model.npz)이 없습니다",
                           missing=["esl"])
    return inp


def _read_manifest(inp: Inputs) -> dict[str, Any] | None:
    """캐시가 유효(키 일치 + 파일 존재)하면 manifest dict, 아니면 None."""
    path = os.path.join(inp.dir, MANIFEST)
    if os.path.islink(inp.dir) or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("key") != inp.key:
        return None
    names = [m["geometry"]["name"], m["values"]["name"]] + ([m["lod"]["name"]] if m.get("lod") else [])
    if not all(os.path.isfile(os.path.join(inp.dir, n)) for n in names):
        return None
    return m


# ---------------------------------------------------------------- 생성
def _load(inp: Inputs) -> dict[str, Any]:
    try:
        with np.load(inp.model, allow_pickle=False) as z:
            model = {k: z[k] for k in ("node_id", "x0", "conn", "elem_type")}
        with np.load(inp.f_eq, allow_pickle=False) as z:
            fz = {"node_id": z["node_id"], "f": z["f"]}
        with np.load(inp.u_rel, allow_pickle=False) as z:
            uz = {"node_id": z["node_id"], "u_rel": z["u_rel"]}
    except (OSError, ValueError, KeyError) as exc:
        raise conflict("PREREQUISITE_MISSING", f"ESL 산출물을 읽을 수 없습니다: {exc}", missing=["esl"]) from None
    nid = np.asarray(model["node_id"], np.int64)
    if not (np.array_equal(np.asarray(fz["node_id"], np.int64), nid)
            and np.array_equal(np.asarray(uz["node_id"], np.int64), nid)):
        raise DomainError("OUTPUT_INCONSISTENT", "f_eq.npz·u_rel.npz 와 model.npz 노드가 다릅니다", status=500)
    return {"node_id": nid, "x0": np.asarray(model["x0"], np.float64), "conn": np.asarray(model["conn"], np.int64),
            "elem_type": np.asarray(model["elem_type"]), "f": np.asarray(fz["f"], np.float64),
            "u_rel": np.asarray(uz["u_rel"], np.float64)}


def _supports(inp: Inputs) -> list[dict[str, Any]]:
    """03_bc/support.json 의 supports(없거나 못 읽으면 run.supports)."""
    try:
        d = co.read_json(inp.support)
        sup = d.get("supports") if isinstance(d, dict) else None
    except (OSError, ValueError):
        sup = None
    if sup is None:
        sup = inp.run.get("supports") or []
    return [s for s in sup if isinstance(s, dict) and "node_id" in s and "dof" in s]


def _too_large(inp: Inputs, **actual: Any) -> DomainError:
    cfg = inp.ctx.settings.view3d
    return DomainError("VIEW3D_TOO_LARGE", "부품이 커서 3D 하중 보기를 만들 수 없습니다(설정 view3d.max_nodes·max_glb_bytes)",
                       status=413, limits={"max_nodes": cfg.max_nodes, "max_glb_bytes": cfg.max_glb_bytes}, **actual)


def _backup_dir(inp: Inputs) -> str:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return os.path.join(inp.cdir, co.BACKUP_DIR, ts, co.RUNS_DIR, inp.run["id"], DIR)


def _build(inp: Inputs) -> dict[str, Any]:
    from esl_worker import core_adapter

    cfg = inp.ctx.settings.view3d
    data = _load(inp)
    n = int(data["node_id"].size)
    if n > cfg.max_nodes:
        raise _too_large(inp, n_nodes=n)
    parent = os.path.dirname(inp.dir)
    tmp = os.path.join(parent, f"{DIR}.tmp-{uuid.uuid4().hex}")
    os.makedirs(tmp)
    ok = False
    try:
        m = core_adapter.view3d_build(
            tmp, node_id=data["node_id"], x0=data["x0"], conn=data["conn"], elem_type=data["elem_type"], f=data["f"],
            u_rel=data["u_rel"], supports=_supports(inp), key=inp.key, esl_run_id=inp.run["id"], units=_units(inp.ctx),
            cfg={k: getattr(cfg, k) for k in ("lod_min_nodes", "lod_target_vertices", "top_max", "cluster_k_max",
                                              "kmeans_max_iter")})
        glb = m["geometry"]["bytes"] + (m["lod"]["bytes"] if m.get("lod") else 0)
        if glb > cfg.max_glb_bytes or m["values"]["bytes"] > cfg.max_glb_bytes:
            raise _too_large(inp, n_nodes=n, glb_bytes=glb, values_bytes=m["values"]["bytes"])
        if os.path.isdir(inp.dir) or os.path.islink(inp.dir):
            if _read_manifest(inp) is not None:      # 다른 프로세스가 이미 같은 키로 만들었음(결정적 출력 → 동일)
                return m
            dest = _backup_dir(inp)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(inp.dir, dest)               # 삭제 금지: _backup 으로 이동
        os.replace(tmp, inp.dir)
        ok = True
        return m
    finally:
        if not ok and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)   # 이 호출이 만든 임시 폴더만 정리


def ensure(ctx: AppContext, run_id: str) -> tuple[Inputs, dict[str, Any]]:
    """유효한 캐시 manifest 를 돌려준다(없거나 key 가 다르면 생성). 오류는 DomainError."""
    inp = resolve(ctx, run_id)
    m = _read_manifest(inp)
    if m is not None:
        return inp, m
    if not _BUILD_LOCK.acquire(timeout=ctx.settings.view3d.build_wait_s):
        raise DomainError("VIEW3D_BUSY", "3D 하중 보기 생성 중인 요청이 있어 잠시 후 다시 시도하세요", status=503)
    from esl_worker.core_adapter import CoreError

    try:
        inp = resolve(ctx, run_id)                    # 대기 중 입력이 바뀌었을 수 있음
        m = _read_manifest(inp)                       # 대기 중 다른 요청이 만들었는지
        if m is None:
            m = _build(inp)
        return inp, m
    except CoreError as exc:
        raise DomainError(exc.code if exc.code in ("OUTPUT_INCONSISTENT", "OUTPUT_INVALID") else "OUTPUT_INVALID",
                          f"3D 하중 보기 생성 실패: {exc.message}", status=500) from None
    except (OSError, ValueError, KeyError) as exc:
        raise DomainError("OUTPUT_INVALID", f"3D 하중 보기 생성 실패: {exc}", status=500) from None
    finally:
        _BUILD_LOCK.release()


def with_urls(run_id: str, m: dict[str, Any]) -> dict[str, Any]:
    base = f"/esl-runs/{run_id}/view3d"
    d = dict(m)
    d["geometry_url"] = f"{base}/{m['geometry']['name']}"
    d["lod_url"] = f"{base}/{m['lod']['name']}" if m.get("lod") else None
    d["values_url"] = f"{base}/{m['values']['name']}"
    return d


def manifest(ctx: AppContext, run_id: str) -> tuple[dict[str, Any], str]:
    """(View3dOut 용 dict, key)."""
    inp, m = ensure(ctx, run_id)
    return with_urls(run_id, m), inp.key


def current_key(ctx: AppContext, run_id: str) -> str:
    """캐시 확인 없이 현재 입력의 key (오류 판정은 manifest 와 같음)."""
    return resolve(ctx, run_id).key


def file(ctx: AppContext, run_id: str, name: str, key: str | None) -> tuple[str, str, str]:
    """(경로, media_type, key). 캐시가 없거나 key 가 다르면 409 VIEW3D_STALE, LOD 가 없으면 404 VIEW3D_LOD_NONE.
    파일 요청은 생성하지 않는다(manifest 를 먼저 받아야 한다)."""
    if name not in FILES:                                     # 라우터가 고정 경로만 받지만 한 번 더
        raise not_found("NOT_FOUND", "찾을 수 없습니다")
    inp = resolve(ctx, run_id)
    m = _read_manifest(inp)
    if m is None or (key is not None and key != inp.key):
        raise conflict("VIEW3D_STALE", "3D 하중 보기 자료가 없거나 이후 바뀌었습니다(manifest 를 다시 받으세요)")
    if name == "part_lod.glb" and not m.get("lod"):
        raise not_found("VIEW3D_LOD_NONE", "이 부품은 저해상도(LOD) 표면이 없습니다")
    return os.path.join(inp.dir, name), FILES[name], inp.key
