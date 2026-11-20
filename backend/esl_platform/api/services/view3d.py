"""④ ESL 3D 하중 보기 서비스(계약 esl_3d_load.md §3·§4, v0.24.1 출처 일반화 esl_view3d_sources.md §5.1):
입력 해석 → 캐시 키 → (없거나 달라지면) 생성 → 파일 경로.

- 하중 출처 = 코어 계획 표 ``esl.view3d_src.CASE_PLAN``(어댑터 ``view3d_src_plan``) 의 행 1개. 이 모듈은 **열만 읽고 출처 이름으로
  분기하지 않는다**(AGENTS.md). ``src`` 없음 = legacy 행 — 키 문서·폴더·URL·ETag·응답 바이트가 v0.24.0 과 같다(키 문서에 src 없음).
- 파생 캐시 위치 ``<case_dir>/runs/<esl_run_id>/<행 dir>/{manifest.json,part.glb,part_lod.glb,values.bin}``(legacy = ``view3d``),
  재현 ``<case_dir>/runs/<esl_run_id>/<행 recon_dir>/{recon.json,recon.bin}``.
  코어 ``04_esl`` 에는 쓰지 않는다. 요청마다 입력 파일 (상대경로, size, mtime_ns)로 key 를 다시 계산(stat 만)해
  key 와 다르면 재생성하고, 이전 폴더는 ``_backup/<UTC ts>/runs/<id>/<dir>`` 로 **이동**한다(삭제 안 함).
- 생성은 프로세스당 세마포어 1개(출처·재현 공통). 대기 ``view3d.build_wait_s`` 초과 시 503 VIEW3D_BUSY.
- 쓰기는 ``<dir>.tmp-<uuid>/`` 에 모두 쓴 뒤 ``os.replace`` 로 올린다.
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
from ...core.atomic import atomic_replace
from ...core.config import BeadDoeView3dCfg
from ...core.errors import DomainError, conflict, not_found
from ...core.repositories import cases as cases_repo
from ..context import AppContext
from .common import case_dir, load_case

BUILDER_VERSION = 1                       # esl.view3d.BUILDER_VERSION 과 같아야 함(시험이 확인)
DIR = "view3d"                            # legacy 행 dir(계획 표 값과 같음 — 시험이 확인)
FILES = {"part.glb": "model/gltf-binary", "part_lod.glb": "model/gltf-binary", "values.bin": "application/octet-stream"}
MANIFEST = "manifest.json"
RECON_JSON, RECON_BIN = "recon.json", "recon.bin"
_BUILD_LOCK = threading.Semaphore(1)      # 프로세스당 생성 1개(메모리 상한)
_CFG_KEYS = ("max_nodes", "max_glb_bytes", "lod_min_nodes", "lod_target_vertices", "top_max", "cluster_k_max",
             "kmeans_max_iter")
SUPPORT_FILES = {"bc": (co.D_BC, "support.json"),   # 계획 열 support 값 → ESL 산출물 기준 상대 위치
                 "jig": None}                       # v0.24.4 지그 3방식: 행 load npz 의 구속 배열(bc_node·bc_kind)이 곧 지지(esl_jig_case.md §5.4)
JIG_BC_KEYS = ("bc_node", "bc_kind")
JIG_KIND_TIE, JIG_KIND_AUX = 1, 2                   # esl.mech.jig_bc.KIND_TIE·KIND_AUX 와 같은 값(백엔드는 scipy 를 끄는 모듈을 import 하지 않음)
JIG_TIE_DOF, JIG_AUX_DOF = "123", "ij"              # 표식 dof 문자열(supportSymbol — 숫자 = 채움 기호·축 선분, 그 밖 = 글자 수로 기호("ij" 2자 = 반 채움, 축 선분 없음)): tie · 3-2-1 면내
_PREREQ_TEXT = "ESL 산출물(04_esl/f_eq.npz·u_rel.npz 또는 01_extract/model.npz)이 없습니다"


# ---------------------------------------------------------------- 출처 표(코어 — 어댑터 경유)
def _plan() -> dict[str, Any]:
    from esl_worker.core_adapter import view3d_src_plan

    return view3d_src_plan()


def source_row(src: str | None) -> dict[str, Any]:
    """출처 키 → 계획 행(None = legacy 행). 모르는 키 = 404 SOURCE_NOT_FOUND{src, keys}."""
    p = _plan()
    for r in p["rows"]:
        if (src is None and r["legacy"]) or r["key"] == src:
            return r
    raise DomainError("SOURCE_NOT_FOUND", f"모르는 하중 출처입니다: {src} (가능: {list(p['keys'])})", status=404,
                      src=src, keys=list(p["keys"]))


def _status(row: dict[str, Any], summary: Any, have: dict[str, bool], doc_reason: str | None) -> dict[str, Any]:
    from esl_worker.core_adapter import view3d_case_status

    return view3d_case_status(row=row, summary=summary if isinstance(summary, dict) else None, have=have,
                              doc_reason=doc_reason)


# ---------------------------------------------------------------- 실행·위치
class RunLoc:
    """한 요청의 ESL 실행 위치: run·case·cdir·ESL 산출물 폴더(src_dir)·검증 폴더(val_dir — 필요할 때만 찾음)."""

    def __init__(self, ctx: AppContext, run: dict[str, Any], case: dict[str, Any], cdir: str, src_dir: str) -> None:
        self.ctx, self.run, self.case, self.cdir, self.src_dir = ctx, run, case, cdir, src_dir
        self._val: tuple[str | None] | None = None

    def val_dir(self) -> str | None:
        """그 ESL 실행의 최신 검증 05_val(results.locate_validation_dir — 스냅샷 표식 → Case 05_val → _backup 표식), 없으면 None."""
        if self._val is None:
            from .results import locate_validation_dir

            with self.ctx.engine.connect() as conn:
                vals = cases_repo.list_validations(conn, esl_run_id=self.run["id"])
                latest = cases_repo.list_validations(conn, case_id=self.case["id"])
            d = None
            if vals:
                loc = locate_validation_dir(self.ctx, self.case, vals[0], latest[0]["id"] if latest else None)
                if loc is not None:
                    d, from_backup = loc
                    if from_backup and (os.path.islink(d) or not co.inside(os.path.realpath(d),
                                                                            os.path.realpath(self.cdir))):
                        d = None
            self._val = (d,)
        return self._val[0]

    def path(self, ref: tuple | list | None) -> str | None:
        """계획 열 (위치, 파일[, 배열]) → 절대경로(위치 esl = 04_esl, val = 최신 검증 05_val). 위치가 없으면 None."""
        if ref is None:
            return None
        loc, name = ref[0], ref[1]
        if loc == "esl":
            return os.path.join(self.src_dir, co.D_ESL, name)
        if loc == "val":
            d = self.val_dir()
            return None if d is None else os.path.join(d, name)
        raise DomainError("CONFIG_INVALID", f"3D 출처 계획 위치 토큰 오류: {loc}", status=500)

    def model(self) -> str:
        return os.path.join(self.cdir, co.D_EXTRACT, "model.npz")

    def stat(self, path: str | None) -> list[Any]:
        if path is None:
            return [None, None, None]
        rel = os.path.relpath(path, self.cdir).replace(os.sep, "/")
        try:
            st = os.stat(path)
        except OSError:
            return [rel, None, None]
        return [rel, st.st_size, st.st_mtime_ns]


def _run_loc(ctx: AppContext, run_id: str) -> RunLoc:
    """오류 판정(/forces·manifest 와 같음): VIEW3D_DISABLED·ESL_RUN_NOT_FOUND·ESL_RUN_FAILED·ESL_RUN_NOT_CURRENT."""
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
    return RunLoc(ctx, run, case, cdir, src)


def _has_array(path: str | None, arr: str) -> bool:
    if path is None or not os.path.isfile(path):
        return False
    try:
        with np.load(path, allow_pickle=False) as z:
            return arr in z.files
    except (OSError, ValueError):
        return False


def _summary(loc: RunLoc, row: dict[str, Any]) -> Any:
    return None if row["summary"] is None else ((loc.run.get("forces") or {}).get(row["summary"]))


def _doc_reason(loc: RunLoc, row: dict[str, Any], summary: Any) -> str | None:
    """요약 recon = skipped 일 때만 진단 json(행 doc) 의 recon.reason(작은 json)."""
    if row["doc"] is None or not isinstance(summary, dict) or summary.get("recon") != "skipped":
        return None
    try:
        d = co.read_json(loc.path(row["doc"]) or "")
    except (OSError, ValueError):
        return None
    rc = d.get("recon") if isinstance(d, dict) else None
    return str(rc["reason"]) if isinstance(rc, dict) and rc.get("reason") else None


def row_status(loc: RunLoc, row: dict[str, Any]) -> dict[str, Any]:
    """출처 행 상태(stat·요약·작은 json 만 — 파일 안 씀). load·target·model = 파일 존재, resp·recon_tgt = 파일 + 배열 존재."""
    have = {"model": os.path.isfile(loc.model())}
    for col in ("load", "target"):
        p = loc.path(row[col])
        have[col] = p is not None and os.path.isfile(p)
    for col in ("resp", "recon_tgt"):
        have[col] = row[col] is not None and _has_array(loc.path(row[col]), row[col][2])
    summ = _summary(loc, row)
    return _status(row, summ, have, _doc_reason(loc, row, summ))


def _unavailable(row: dict[str, Any], st: dict[str, Any]) -> DomainError:
    """409 V3D_SOURCE_UNAVAILABLE{src, reason_code, reason}(detail.code = 오류 코드라 출처 사유 코드는 reason_code)."""
    if st["code"] == "PREREQUISITE_MISSING":          # legacy 행 산출물 없음 = v0.24.0 오류 그대로
        return conflict("PREREQUISITE_MISSING", _PREREQ_TEXT, missing=["esl"])
    return conflict("V3D_SOURCE_UNAVAILABLE", f"{row['key']} 3D 하중 보기 불가 — {st['reason']}", src=row["key"],
                    reason_code=st["code"], reason=st["reason"])


# ---------------------------------------------------------------- 하중 보기 입력
class Inputs:
    """한 요청에서 해석한 입력: 행·경로·run·캐시 폴더·key."""

    def __init__(self, loc: RunLoc, row: dict[str, Any]) -> None:
        self.loc, self.row = loc, row
        self.ctx, self.run, self.cdir, self.src = loc.ctx, loc.run, loc.cdir, loc.src_dir
        self.legacy = bool(row["legacy"])
        self.load = loc.path(row["load"])
        self.target = loc.path(row["target"])
        sp = SUPPORT_FILES.get(row["support"]) if row["support"] else None
        self.support = os.path.join(loc.src_dir, *sp) if sp else None
        self.support_npz = self.load if (row["support"] and row["support"] in SUPPORT_FILES and sp is None) else None
        self.model = loc.model()
        self.dir = os.path.join(loc.cdir, co.RUNS_DIR, loc.run["id"], row["dir"])
        self.key = self._key()

    def _key(self) -> str:
        cfg = self.ctx.settings.view3d
        doc = {"builder_version": BUILDER_VERSION, "esl_run_id": self.run["id"],
               "cfg": {k: getattr(cfg, k) for k in _CFG_KEYS}, "units": _units(self.ctx),
               "inputs": [self.loc.stat(p) for p in (self.load, self.target, self.support, self.model)]}
        if not self.legacy:                                  # legacy 키 문서 = v0.24.0 그대로(src 없음)
            doc["src"] = self.row["key"]
        return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _units(ctx: AppContext) -> dict[str, str]:
    u = ((ctx.config.core or {}).get("units") or {})
    return {"length": str(u.get("length") or "mm"), "force": str(u.get("force") or "N"),
            "pressure": str(u.get("stress") or "MPa")}


def resolve(ctx: AppContext, run_id: str, src: str | None = None) -> Inputs:
    if not ctx.settings.view3d.enabled:
        raise not_found("VIEW3D_DISABLED", "3D 하중 보기가 설정에서 꺼져 있습니다(view3d.enabled=false)")
    row = source_row(src)
    loc = _run_loc(ctx, run_id)
    if row["load"] is None:
        raise _unavailable(row, row_status(loc, row))
    inp = Inputs(loc, row)
    if not all(p is not None and os.path.isfile(p) for p in (inp.load, inp.target, inp.model)):
        raise _unavailable(row, row_status(loc, row))
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
def _load_model(path: str) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in ("node_id", "x0", "conn", "elem_type")}


def _load(inp: Inputs) -> dict[str, Any]:
    lf, la = inp.row["load"][1], inp.row["load"][2]
    tf, ta = inp.row["target"][1], inp.row["target"][2]
    try:
        model = _load_model(inp.model)
        with np.load(inp.load or "", allow_pickle=False) as z:          # resolve 가 존재를 확인함(None 아님)
            fz = {"node_id": z["node_id"], "f": z[la]}
        with np.load(inp.target or "", allow_pickle=False) as z:
            uz = {"node_id": z["node_id"], "u_rel": z[ta]}
    except (OSError, ValueError, KeyError) as exc:
        raise conflict("PREREQUISITE_MISSING", f"ESL 산출물을 읽을 수 없습니다: {exc}", missing=["esl"]) from None
    nid = np.asarray(model["node_id"], np.int64)
    if not (np.array_equal(np.asarray(fz["node_id"], np.int64), nid)
            and np.array_equal(np.asarray(uz["node_id"], np.int64), nid)):
        raise DomainError("OUTPUT_INCONSISTENT", f"{lf}·{tf} 와 model.npz 노드가 다릅니다", status=500)
    return {"node_id": nid, "x0": np.asarray(model["x0"], np.float64), "conn": np.asarray(model["conn"], np.int64),
            "elem_type": np.asarray(model["elem_type"]), "f": np.asarray(fz["f"], np.float64),
            "u_rel": np.asarray(uz["u_rel"], np.float64)}


def jig_support_sample(x0: np.ndarray, idx: np.ndarray, m: int) -> np.ndarray:
    """지그 표식 샘플(표시만) — 최원점 샘플링 min(|idx|, m) 개(첫 점 = 가장 작은 노드 인덱스, 이후 최소 거리 최대, 동률 = 작은 인덱스,
    결정적). ``esl.mech.jig.support_sample`` 과 같은 정의(그 모듈은 scipy 를 끌어와 백엔드 import 경로에 넣지 않음 — 시험이 같음 확인)."""
    J = np.unique(np.asarray(idx, dtype=np.int64))
    m = int(m)
    if m <= 0 or J.size == 0:
        return np.zeros(0, dtype=np.int64)
    if J.size <= m:
        return J
    P = np.asarray(x0, dtype=np.float64)[J]
    pick = [0]
    d = np.linalg.norm(P - P[0], axis=1)
    for _ in range(m - 1):
        k = int(np.argmax(d))
        pick.append(k)
        d = np.minimum(d, np.linalg.norm(P - P[k], axis=1))
    return J[np.asarray(pick, dtype=np.int64)]


def _jig_supports(inp: Inputs, node_id: np.ndarray, x0: np.ndarray) -> list[dict[str, Any]]:
    """지그 행: load npz 의 bc_node(노드 인덱스)·bc_kind·sp_node(스프링) → tie 노드(최대 view3d.jig_support_max 개 샘플) + 3-2-1 면내 노드(전부, 최대 3개).
    읽지 못하면 빈 목록(표식 없음 — 3D 자체는 계속)."""
    try:
        with np.load(inp.support_npz or "", allow_pickle=False) as z:
            bn = np.asarray(z["bc_node"], dtype=np.int64)
            bk = np.asarray(z["bc_kind"]).astype(np.int64)
            sp = np.asarray(z["sp_node"], dtype=np.int64) if "sp_node" in z.files else np.zeros(0, np.int64)
    except (OSError, ValueError, KeyError):
        return []
    n = int(node_id.size)
    ok = (bn >= 0) & (bn < n)
    bd = getattr(inp.ctx.settings, "bead_doe", None)
    m = int((bd.view3d if bd is not None else BeadDoeView3dCfg()).jig_support_max)
    # tie = 구속 행의 tie + 스프링 행(sp_node — 스프링 방식은 tie 가 구속이 아니라 스프링이라 bc_node 에 없음)
    tie = jig_support_sample(x0, np.unique(np.r_[bn[ok & (bk == JIG_KIND_TIE)], sp[(sp >= 0) & (sp < n)]]), m)
    aux = np.unique(bn[ok & (bk == JIG_KIND_AUX)])
    shown = set(tie.tolist())
    return ([{"node_id": int(node_id[i]), "dof": JIG_TIE_DOF} for i in tie]
            + [{"node_id": int(node_id[i]), "dof": JIG_AUX_DOF} for i in aux if int(i) not in shown])


def _supports(inp: Inputs, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """03_bc/support.json 의 supports(없거나 못 읽으면 run.supports). 지그 행 = load npz 의 구속(_jig_supports)."""
    if inp.support_npz is not None and data is not None:
        return _jig_supports(inp, data["node_id"], data["x0"])
    sup = None
    if inp.support is not None:
        try:
            d = co.read_json(inp.support)
            sup = d.get("supports") if isinstance(d, dict) else None
        except (OSError, ValueError):
            sup = None
    if sup is None:
        sup = inp.run.get("supports") or []
    return [s for s in sup if isinstance(s, dict) and "node_id" in s and "dof" in s]


def _too_large(ctx: AppContext, **actual: Any) -> DomainError:
    cfg = ctx.settings.view3d
    return DomainError("VIEW3D_TOO_LARGE", "부품이 커서 3D 하중 보기를 만들 수 없습니다(설정 view3d.max_nodes·max_glb_bytes)",
                       status=413, limits={"max_nodes": cfg.max_nodes, "max_glb_bytes": cfg.max_glb_bytes}, **actual)


def _backup_dir(cdir: str, run_id: str, name: str) -> str:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return os.path.join(cdir, co.BACKUP_DIR, ts, co.RUNS_DIR, run_id, name)


def _publish(tmp: str, dest: str, cdir: str, run_id: str, name: str, valid) -> bool:
    """tmp → dest(이전 폴더는 _backup 이동 — 삭제 금지). 다른 프로세스가 이미 같은 키로 만들었으면(valid()) False(tmp 그대로)."""
    if os.path.isdir(dest) or os.path.islink(dest):
        if valid():
            return False
        b = _backup_dir(cdir, run_id, name)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.move(dest, b)
    atomic_replace(tmp, dest)
    return True


def _build(inp: Inputs) -> dict[str, Any]:
    from esl_worker import core_adapter

    cfg = inp.ctx.settings.view3d
    data = _load(inp)
    n = int(data["node_id"].size)
    if n > cfg.max_nodes:
        raise _too_large(inp.ctx, n_nodes=n)
    parent = os.path.dirname(inp.dir)
    tmp = os.path.join(parent, f"{inp.row['dir']}.tmp-{uuid.uuid4().hex}")
    os.makedirs(tmp)
    try:
        m = core_adapter.view3d_build(
            tmp, node_id=data["node_id"], x0=data["x0"], conn=data["conn"], elem_type=data["elem_type"], f=data["f"],
            u_rel=data["u_rel"], supports=_supports(inp, data), key=inp.key, esl_run_id=inp.run["id"], units=_units(inp.ctx),
            cfg={k: getattr(cfg, k) for k in ("lod_min_nodes", "lod_target_vertices", "top_max", "cluster_k_max",
                                              "kmeans_max_iter")})
        glb = m["geometry"]["bytes"] + (m["lod"]["bytes"] if m.get("lod") else 0)
        if glb > cfg.max_glb_bytes or m["values"]["bytes"] > cfg.max_glb_bytes:
            raise _too_large(inp.ctx, n_nodes=n, glb_bytes=glb, values_bytes=m["values"]["bytes"])
        _publish(tmp, inp.dir, inp.cdir, inp.run["id"], inp.row["dir"], lambda: _read_manifest(inp) is not None)
        return m
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)   # 이 호출이 만든 임시 폴더만 정리(올렸으면 이미 없음)


def _locked(ctx: AppContext, fn):
    """생성 세마포어(출처·재현 공통) 안에서 fn() — 대기 초과 503 VIEW3D_BUSY, 코어 오류 → 500."""
    if not _BUILD_LOCK.acquire(timeout=ctx.settings.view3d.build_wait_s):
        raise DomainError("VIEW3D_BUSY", "3D 하중 보기 생성 중인 요청이 있어 잠시 후 다시 시도하세요", status=503)
    from esl_worker.core_adapter import CoreError

    try:
        return fn()
    except CoreError as exc:
        raise DomainError(exc.code if exc.code in ("OUTPUT_INCONSISTENT", "OUTPUT_INVALID") else "OUTPUT_INVALID",
                          f"3D 하중 보기 생성 실패: {exc.message}", status=500) from None
    except (OSError, ValueError, KeyError) as exc:
        raise DomainError("OUTPUT_INVALID", f"3D 하중 보기 생성 실패: {exc}", status=500) from None
    finally:
        _BUILD_LOCK.release()


def ensure(ctx: AppContext, run_id: str, src: str | None = None) -> tuple[Inputs, dict[str, Any]]:
    """유효한 캐시 manifest 를 돌려준다(없거나 key 가 다르면 생성). 오류는 DomainError."""
    inp = resolve(ctx, run_id, src)
    m = _read_manifest(inp)
    if m is not None:
        return inp, m

    def go() -> tuple[Inputs, dict[str, Any]]:
        i = resolve(ctx, run_id, src)                 # 대기 중 입력이 바뀌었을 수 있음
        mm = _read_manifest(i)                        # 대기 중 다른 요청이 만들었는지
        return i, (mm if mm is not None else _build(i))

    return _locked(ctx, go)


def _q(row: dict[str, Any]) -> str:
    """파일 URL 의 출처 쿼리(legacy 행 = 없음 → v0.24.0 URL 그대로)."""
    return "" if row["legacy"] else f"?src={row['key']}"


def with_urls(run_id: str, m: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
    base = f"/esl-runs/{run_id}/view3d"
    q = "" if row is None else _q(row)
    d = dict(m)
    d["geometry_url"] = f"{base}/{m['geometry']['name']}{q}"
    d["lod_url"] = f"{base}/{m['lod']['name']}{q}" if m.get("lod") else None
    d["values_url"] = f"{base}/{m['values']['name']}{q}"
    return d


def manifest(ctx: AppContext, run_id: str, src: str | None = None) -> tuple[dict[str, Any], str]:
    """(View3dOut 용 dict, key)."""
    inp, m = ensure(ctx, run_id, src)
    return with_urls(run_id, m, inp.row), inp.key


def current_key(ctx: AppContext, run_id: str, src: str | None = None) -> str:
    """캐시 확인 없이 현재 입력의 key (오류 판정은 manifest 와 같음)."""
    return resolve(ctx, run_id, src).key


def _stale() -> DomainError:
    return conflict("VIEW3D_STALE", "3D 하중 보기 자료가 없거나 이후 바뀌었습니다(manifest 를 다시 받으세요)")


def file(ctx: AppContext, run_id: str, name: str, key: str | None, src: str | None = None) -> tuple[str, str, str]:
    """(경로, media_type, key). 캐시가 없거나 key 가 다르면 409 VIEW3D_STALE, LOD 가 없으면 404 VIEW3D_LOD_NONE.
    파일 요청은 생성하지 않는다(manifest 를 먼저 받아야 한다)."""
    if name not in FILES:                                     # 라우터가 고정 경로만 받지만 한 번 더
        raise not_found("NOT_FOUND", "찾을 수 없습니다")
    inp = resolve(ctx, run_id, src)
    m = _read_manifest(inp)
    if m is None or (key is not None and key != inp.key):
        raise _stale()
    if name == "part_lod.glb" and not m.get("lod"):
        raise not_found("VIEW3D_LOD_NONE", "이 부품은 저해상도(LOD) 표면이 없습니다")
    return os.path.join(inp.dir, name), FILES[name], inp.key


# ---------------------------------------------------------------- 출처 목록(§5.1 /view3d/sources)
def sources(ctx: AppContext, run_id: str) -> dict[str, Any]:
    """View3dSourcesOut: 출처 표 순서 행마다 상태. stat·요약·작은 json 만 읽음(파일 안 씀)."""
    loc = _run_loc(ctx, run_id)
    rows = []
    for r in _plan()["rows"]:
        st = row_status(loc, r)
        rows.append({"key": r["key"], **{k: st[k] for k in ("available", "code", "reason", "resp", "resp_code",
                                                             "resp_reason")}, "rigid": r["rigid"]})
    return {"esl_run_id": run_id, "default": ctx.settings.view3d.case_src_default, "rows": rows}


# ---------------------------------------------------------------- 재현(§4·§5.1 /view3d/recon)
class Recon:
    """재현 입력: 행·목표(recon_tgt)·응답(resp)·model 경로·폴더·key."""

    def __init__(self, loc: RunLoc, row: dict[str, Any], recon_version: int) -> None:
        self.loc, self.row, self.ctx, self.run, self.cdir = loc, row, loc.ctx, loc.run, loc.cdir
        self.tgt = loc.path(row["recon_tgt"])
        self.fit = loc.path(row["resp"])
        self.model = loc.model()
        self.dir = os.path.join(loc.cdir, co.RUNS_DIR, loc.run["id"], row["recon_dir"])
        doc = {"recon_version": recon_version, "esl_run_id": loc.run["id"], "src": row["key"],
               "inputs": [loc.stat(p) for p in (self.tgt, self.fit, self.model)]}
        self.key = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def recon_resolve(ctx: AppContext, run_id: str, src: str | None = None) -> Recon:
    if not ctx.settings.view3d.enabled:
        raise not_found("VIEW3D_DISABLED", "3D 하중 보기가 설정에서 꺼져 있습니다(view3d.enabled=false)")
    row = source_row(src)
    loc = _run_loc(ctx, run_id)
    st = row_status(loc, row)
    if not st["available"]:
        raise _unavailable(row, st)
    if not st["resp"]:
        raise conflict("V3D_RECON_UNAVAILABLE", f"{row['key']} 재현 비교 불가 — {st['resp_reason']}", src=row["key"],
                       reason_code=st["resp_code"], reason=st["resp_reason"])
    return Recon(loc, row, int(_plan()["recon_version"]))


def _read_recon(r: Recon) -> dict[str, Any] | None:
    path = os.path.join(r.dir, RECON_JSON)
    if os.path.islink(r.dir) or not os.path.isfile(path) or not os.path.isfile(os.path.join(r.dir, RECON_BIN)):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("key") == r.key else None


def _by_id(nid: np.ndarray, z_nid: np.ndarray, u: np.ndarray, what: str) -> np.ndarray:
    """노드 ID 로 model 순서에 맞춤(같은 순서면 그대로, 집합이 다르면 500 OUTPUT_INCONSISTENT)."""
    z_nid = np.asarray(z_nid, np.int64)
    u = np.asarray(u, np.float64)[:, :3]
    if np.array_equal(z_nid, nid):
        return u
    o = np.argsort(z_nid, kind="stable")
    pos = np.searchsorted(z_nid, nid, sorter=o).clip(0, max(z_nid.size - 1, 0))
    if z_nid.size != nid.size or not np.array_equal(z_nid[o[pos]], nid):
        raise DomainError("OUTPUT_INCONSISTENT", f"{what} 와 model.npz 노드가 다릅니다", status=500)
    return u[o[pos]]


def _build_recon(r: Recon) -> dict[str, Any]:
    from esl_worker import core_adapter

    cfg = r.ctx.settings.view3d
    try:
        nid = np.asarray(_load_model(r.model)["node_id"], np.int64)
        with np.load(r.tgt or "", allow_pickle=False) as z:              # recon_resolve 가 존재를 확인함
            ut = _by_id(nid, z["node_id"], z[r.row["recon_tgt"][2]], r.row["recon_tgt"][1])
        with np.load(r.fit or "", allow_pickle=False) as z:
            uf = _by_id(nid, z["node_id"], z[r.row["resp"][2]], r.row["resp"][1])
    except (OSError, ValueError, KeyError) as exc:
        raise conflict("PREREQUISITE_MISSING", f"재현 입력을 읽을 수 없습니다: {exc}", missing=["esl"]) from None
    if nid.size > cfg.max_nodes:
        raise _too_large(r.ctx, n_nodes=int(nid.size))
    parent = os.path.dirname(r.dir)
    tmp = os.path.join(parent, f"{r.row['recon_dir']}.tmp-{uuid.uuid4().hex}")
    os.makedirs(tmp)
    try:
        d = core_adapter.view3d_recon_build(tmp, node_id=nid, u_tgt=ut, u_fit=uf, key=r.key, src=r.row["key"],
                                            rigid=r.row["rigid"], esl_run_id=r.run["id"])
        if d["bytes"] > cfg.max_glb_bytes:
            raise _too_large(r.ctx, n_nodes=int(nid.size), values_bytes=d["bytes"])
        _publish(tmp, r.dir, r.cdir, r.run["id"], r.row["recon_dir"], lambda: _read_recon(r) is not None)
        return d
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def recon(ctx: AppContext, run_id: str, src: str | None = None) -> tuple[dict[str, Any], str]:
    """(View3dReconOut 용 dict, key). 첫 요청이 runs/<id>/<recon_dir>/ 생성."""
    r = recon_resolve(ctx, run_id, src)
    d = _read_recon(r)
    if d is None:
        def go() -> tuple[Recon, dict[str, Any]]:
            rr = recon_resolve(ctx, run_id, src)
            dd = _read_recon(rr)
            return rr, (dd if dd is not None else _build_recon(rr))

        r, d = _locked(ctx, go)
    return {**d, "values_url": f"/esl-runs/{run_id}/view3d/{RECON_BIN}{_q(r.row)}"}, r.key


def recon_file(ctx: AppContext, run_id: str, key: str | None, src: str | None = None) -> tuple[str, str, str]:
    """(recon.bin 경로, media_type, key). 캐시가 없거나 key 가 다르면 409 VIEW3D_STALE(생성 안 함)."""
    r = recon_resolve(ctx, run_id, src)
    d = _read_recon(r)
    if d is None or (key is not None and key != r.key):
        raise _stale()
    return os.path.join(r.dir, RECON_BIN), "application/octet-stream", r.key
