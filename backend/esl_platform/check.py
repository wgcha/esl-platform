"""ESL 플랫폼 환경 점검 CLI: `python -m esl_platform.check [--runtime <런타임>] [--config <설정>] [--json]`.

관리 화면의 환경 점검이 없으므로(`GET /status`는 설정·워커·솔버 요약만) 설치·업데이트·설정 변경 뒤 이 표로 확인한다.
항목: Python 버전, 설정 검증(스키마·의미·코어·라이브러리), 프런트 정적 서빙(server.frontend_root — 폴더·index.html, null 이면 SKIP), esl_root 쓰기·여유 공간,
upload_root(브라우저 업로드) 쓰기·여유 공간, input_roots·spdm_roots 읽기,
worker.state_dir 쓰기, 워커 자원 제한기(worker.limiter — Windows 는 Job Object 생성·한도 설정 시험), DB 접속·migration head·워커 heartbeat, 솔버 백엔드(설정값 해석·사용 가능 목록)·pypardiso(MKL)·
scikit-sparse(Windows 제외)·pyamg·psutil.

- DB URL: 환경변수(설정 `database.url_env`, 기본 ESL_DATABASE_URL) → 없으면 `--runtime`의 `secrets/database_url`.
  값은 출력하지 않는다(접속 대상 host:port/db 만).
- `--runtime <폴더>`: 설치 런타임(deploy/setup.ps1·install.ps1). 설정 기본값 `<런타임>/config/esl_platform.yaml`,
  상대 `worker.state_dir`는 `<런타임>` 기준(작업 스케줄러 작업 폴더와 같음).
- 종료코드: 0 = FAIL 없음(WARN 허용), 1 = FAIL 있음, 2 = 사용법 오류.
- 코어(`esl`)는 `esl_worker.core_adapter` 를 통해서만 부른다(플랫폼 규칙). 외부 프로그램을 실행하지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))   # 저장소 루트 또는 설치 app 폴더(backend/, worker/, esl/, migrations/)
for _p in (os.path.join(_ROOT, "backend"), os.path.join(_ROOT, "worker"), _ROOT):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
CONFIG_NAME = "esl_platform.yaml"
SECRET_REL = ("secrets", "database_url")
PY_WANT = (3, 12)          # 대시보드(simulation_workbench)와 같은 Python 3.12(3.12.13)


@dataclass
class Item:
    key: str
    status: str
    detail: str


# ---------------------------------------------------------------- 경로·입력
def runtime_secret_path(runtime: str) -> str:
    return os.path.join(runtime, *SECRET_REL)


def read_runtime_db_url(runtime: str | None) -> str:
    """`<런타임>/secrets/database_url`(UTF-8, BOM·줄바꿈 무시). 없으면 빈 문자열."""
    if not runtime:
        return ""
    p = runtime_secret_path(runtime)
    try:
        with open(p, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def resolve_config_path(config: str | None, runtime: str | None, environ: dict[str, str]) -> str | None:
    if config:
        return os.path.abspath(config)
    if runtime:
        return os.path.join(os.path.abspath(runtime), "config", CONFIG_NAME)
    p = environ.get("ESL_PLATFORM_CONFIG")
    return os.path.abspath(p) if p else None


def describe_url(url: str) -> str:
    """비밀번호 없이 host:port/db 만."""
    from sqlalchemy.engine import make_url

    try:
        u = make_url(url)
    except Exception:  # noqa: BLE001
        return "(해석 불가)"
    return f"{u.username or '?'}@{u.host or '?'}:{u.port or 5432}/{u.database or '?'}"


# ---------------------------------------------------------------- 개별 점검
def check_python() -> Item:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) == PY_WANT:
        return Item("python", OK, f"Python {ver} ({sys.executable})")
    return Item("python", WARN, f"Python {ver} — 기준은 대시보드와 같은 3.12(3.12.13)")


def check_dir_write(key: str, path: str) -> Item:
    if not path:
        return Item(key, FAIL, "경로 없음")
    if not os.path.isdir(path):
        return Item(key, FAIL, f"폴더가 없습니다: {path}")
    probe = os.path.join(path, f".esl_check_{uuid.uuid4().hex[:12]}.tmp")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("esl check\n")
        os.remove(probe)
    except OSError as exc:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
        return Item(key, FAIL, f"쓰기 실패: {path} ({exc})")
    return Item(key, OK, f"쓰기 가능: {path}")


def check_free(key: str, path: str, min_free_gb: float) -> Item:
    try:
        free = shutil.disk_usage(path).free / 2 ** 30
    except OSError as exc:
        return Item(key, SKIP, f"여유 공간 확인 불가: {exc}")
    if free < min_free_gb:
        return Item(key, WARN, f"여유 {free:.1f} GB < 기준 {min_free_gb:g} GB: {path}")
    return Item(key, OK, f"여유 {free:.1f} GB (기준 {min_free_gb:g} GB)")


def check_read_roots(key: str, roots: list[str], *, empty_status: str, empty_msg: str, missing_status: str) -> Item:
    if not roots:
        return Item(key, empty_status, empty_msg)
    bad, ok = [], []
    for r in roots:
        try:
            if not os.path.isdir(r):
                bad.append(f"없음 {r}")
                continue
            os.listdir(r)
            ok.append(r)
        except OSError as exc:
            bad.append(f"읽기 실패 {r} ({exc.__class__.__name__})")
    if bad:
        return Item(key, missing_status, "; ".join(bad) + (f" (정상 {len(ok)}개)" if ok else ""))
    return Item(key, OK, f"읽기 가능 {len(ok)}개: " + ", ".join(ok))


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_solver(core_cfg: dict | None, platform: str) -> list[Item]:
    """솔버 백엔드: 코어와 같은 규칙(core_adapter.solver_backends)으로 해석한다."""
    from esl_worker import core_adapter

    out: list[Item] = []
    try:
        sb = core_adapter.solver_backends(core_cfg)
    except core_adapter.CoreError as exc:
        return [Item("solver.backend", FAIL, f"코어를 불러올 수 없습니다: {exc.code}: {exc.message}")]
    avail = list(sb.get("solver_backends_available") or [])
    requested = str(((core_cfg or {}).get("solver") or {}).get("backend") or "auto")
    resolved = str(sb.get("solver_backend"))
    if requested not in ("auto", "iterative") and requested not in avail:
        out.append(Item("solver.backend", FAIL, f"설정 solver.backend={requested} 미설치(사용 가능: {', '.join(avail)}) — "
                                                 "작업이 INPUT_INVALID 로 실패합니다"))
    else:
        out.append(Item("solver.backend", OK, f"설정 {requested} → {resolved} (사용 가능: {', '.join(avail)})"))
    win = platform == "win32"
    pv = _dist_version("pypardiso")
    mv = _dist_version("mkl")
    if "pardiso" in avail:
        out.append(Item("solver.pypardiso", OK, f"pypardiso {pv or '?'} · MKL {mv or '?'} (mkl_rt 로드 가능)"))
    elif pv:
        msg = f"pypardiso {pv} 설치됨, MKL(mkl_rt) 로드 실패 — mkl 휠 설치 확인(PYPARDISO_MKL_RT)"
        out.append(Item("solver.pypardiso", FAIL if win else WARN, msg))
    else:
        msg = "pypardiso 미설치 — 대규모 쉘(22만 요소) 직접법이 SuperLU 로 느리고 메모리를 많이 씀"
        out.append(Item("solver.pypardiso", FAIL if win else WARN,
                        msg + (" (설치 묶음 wheels 에 포함되어야 함)" if win else "")))
    if win:
        out.append(Item("solver.cholmod", SKIP, "scikit-sparse 는 Windows 제외(휠 없음) — pardiso 사용"))
    elif "cholmod" in avail:
        out.append(Item("solver.cholmod", OK, f"scikit-sparse {_dist_version('scikit-sparse') or '?'}"))
    else:
        out.append(Item("solver.cholmod", SKIP, "scikit-sparse 미설치(선택, libsuitesparse 필요)"))
    for mod, why in (("pyamg", "직접법 메모리 부족 시 반복법(CG+AMG) 전처리"), ("psutil", "가용 메모리 추정·RSS 기록")):
        v = _dist_version(mod)
        out.append(Item(f"solver.{mod}", OK if v else WARN, f"{mod} {v}" if v else f"{mod} 미설치 — {why}"))
    return out


def check_limiter(worker_cfg, platform: str, *, kernel32=None, cpu_count: int | None = None) -> Item:
    """워커 자원 제한기(worker.limiter): 이 OS 에서 쓸 모드를 해석하고, windows_job 이면 Job Object 를 실제로 만들어
    한도(우선순위·메모리·CPU 상한)를 설정해 본 뒤 닫는다(프로세스는 실행하지 않음). none = WARN(제한 없음)."""
    from esl_worker import limiter

    os_name = "nt" if platform.startswith("win") else "posix"
    lim = limiter.create(worker_cfg, os_name=os_name, kernel32=kernel32, cpu_count=cpu_count)
    try:
        s = lim.summary()
    finally:
        lim.close()
    line = f"{worker_cfg.limiter} → {s['mode']}: {s['text']}"
    if s.get("error"):
        return Item("worker.limiter", FAIL, line + " — 코어 step 이 LIMITER_FAILED 로 실패합니다")
    if s["mode"] == "null":
        return Item("worker.limiter", WARN, line + " — 대시보드·physicsai 와 CPU·메모리 경합 가능")
    if s["mode"] == "posix" and not hasattr(os, "sched_setaffinity"):
        return Item("worker.limiter", WARN, line + " — 이 OS 는 CPU 선호도 미지원")
    return Item("worker.limiter", OK, line)


def check_db(url: str, heartbeat_interval_s: float | None) -> list[Item]:
    from sqlalchemy import create_engine, text

    from esl_platform.core.db.engine import normalize_url

    where = describe_url(url)
    out: list[Item] = []
    try:
        eng = create_engine(normalize_url(url), pool_pre_ping=True)
    except Exception as exc:  # noqa: BLE001
        return [Item("db.connection", FAIL, f"URL 해석 실패: {exc.__class__.__name__}")]
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
            ver = conn.execute(text("SHOW server_version")).scalar()
            out.append(Item("db.connection", OK, f"{where} (PostgreSQL {ver})"))
            major = int(str(ver).split(".")[0]) if str(ver).split(".")[0].isdigit() else 0
            if major and major != 18:
                out.append(Item("db.server_version", WARN, f"PostgreSQL {ver} — 기준은 대시보드와 같은 18"))
            head = migration_head()
            try:
                cur = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:  # noqa: BLE001
                cur = None
            if cur is None:
                out.append(Item("db.migration_head", FAIL, f"migration 미적용(alembic_version 없음) — head {head}"))
            elif head and cur != head:
                out.append(Item("db.migration_head", FAIL, f"현재 {cur} ≠ head {head} — alembic upgrade head"))
            else:
                out.append(Item("db.migration_head", OK, f"{cur}" + ("" if head else " (head 확인 불가)")))
            if cur is not None:
                out.append(_heartbeat(conn, heartbeat_interval_s))
    except Exception as exc:  # noqa: BLE001 - 접속 실패 메시지에 비밀값이 섞이지 않게 종류만
        out.append(Item("db.connection", FAIL, f"{where} 접속 실패({exc.__class__.__name__}) — 서버·역할·비밀번호 확인"))
    finally:
        eng.dispose()
    return out


def _heartbeat(conn, interval: float | None) -> Item:
    from esl_platform.core.repositories import workers as workers_repo

    try:
        hb = workers_repo.latest(conn)
    except Exception as exc:  # noqa: BLE001
        return Item("worker.heartbeat", SKIP, f"조회 실패({exc.__class__.__name__})")
    if not hb:
        return Item("worker.heartbeat", WARN, "워커 기록 없음(워커가 아직 시작되지 않음)")
    age = hb["age"].total_seconds()
    lim = 3 * float(interval or 10)
    if age <= lim:
        return Item("worker.heartbeat", OK, f"{hb.get('host')} pid {hb.get('pid')} — {age:.0f}초 전, limiter {hb.get('limiter')}")
    return Item("worker.heartbeat", WARN, f"마지막 {age:.0f}초 전(> {lim:g}초) — 워커 오프라인(ESL-Worker 작업 확인)")


def migration_head() -> str | None:
    """`<app>/migrations` 의 head revision(alembic ScriptDirectory). 찾지 못하면 None."""
    mig = os.path.join(_ROOT, "migrations")
    if not os.path.isdir(mig):
        return None
    try:
        from alembic.script import ScriptDirectory

        return ScriptDirectory(mig).get_current_head()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 전체
def run_checks(config_path: str | None, *, runtime: str | None = None, environ: dict[str, str] | None = None,
               use_db: bool = True, min_free_gb: float = 20.0, platform: str | None = None) -> list[Item]:
    from esl_platform.core.config import load_config

    env = dict(os.environ if environ is None else environ)
    plat = platform or sys.platform
    items: list[Item] = [check_python()]
    if not config_path:
        items.append(Item("config.valid", FAIL, "설정 파일 경로가 없습니다(--config, --runtime 또는 env ESL_PLATFORM_CONFIG)"))
        return items
    lc = load_config(config_path, environ=env)
    s = lc.settings
    if s is None:
        items.append(Item("config.valid", FAIL, f"{config_path}: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues)))
        return items
    if lc.issues or lc.core is None:
        items.append(Item("config.valid", FAIL, "; ".join(f"{i.key}: {i.message}" for i in lc.issues) or "코어 설정 없음"))
    else:
        items.append(Item("config.valid", OK, f"{config_path} (profile {s.profile}, {s.server.host}:{s.server.port}{s.api_prefix})"))
    if s.auth.mode == "dev_static":
        items.append(Item("config.auth", WARN if s.profile == "dev" else FAIL, "auth.mode=dev_static(개발·시연 전용)"))
    else:
        items.append(Item("config.auth", OK, f"dashboard {s.auth.dashboard_internal_url} (쿠키 {s.auth.cookie_name})"))
    from esl_platform.api.frontend_static import root_status

    fe_status, fe_msg = root_status(s.server.frontend_root, s.server.base_path)
    items.append(Item("server.frontend_root", fe_status, fe_msg))
    if s.library is None:
        items.append(Item("config.library", WARN, "library 블록 없음 — 라이브러리·분석 쓰기 API 503(LIBRARY_CONFIG_MISSING)"))
    elif lc.library is not None:
        items.append(Item("config.library", OK, "라이브러리 설정 검증 통과"))

    st = s.storage
    items.append(check_dir_write("storage.esl_root.write", st.esl_root))
    if os.path.isdir(st.esl_root):
        items.append(check_free("storage.esl_root.free", st.esl_root, min_free_gb))
    items.append(check_read_roots("storage.input_roots", list(st.input_roots), empty_status=WARN,
                                  empty_msg="비어 있음 — rad·결과 폴더를 고를 수 없음(Case 생성 불가)", missing_status=FAIL))
    if st.upload_root:
        items.append(check_dir_write("storage.upload_root.write", st.upload_root))
        if os.path.isdir(st.upload_root):
            items.append(check_free("storage.upload_root.free", st.upload_root,
                                    max(min_free_gb, s.upload.min_free_gb)))
    else:
        items.append(Item("storage.upload_root", WARN, "없음 — 브라우저 업로드를 쓸 수 없음(설정 storage.upload_root)"))
    items.append(check_read_roots("storage.spdm_roots", list(st.spdm_roots), empty_status=OK,
                                  empty_msg="없음(겹침 검사만 하는 목록)", missing_status=WARN))
    sd = s.worker.state_dir
    if not os.path.isabs(sd):
        sd = os.path.normpath(os.path.join(os.path.abspath(runtime) if runtime else os.getcwd(), sd))
    if os.path.isdir(sd):
        items.append(check_dir_write("worker.state_dir", sd))
    else:
        items.append(Item("worker.state_dir", WARN, f"폴더 없음(워커가 만듦): {sd}"))
    items.append(check_limiter(s.worker, plat))

    items += check_solver(lc.core, plat)

    if use_db:
        url = env.get(s.database.url_env) or read_runtime_db_url(runtime)
        if not url:
            src = f"환경변수 {s.database.url_env}" + (f" 또는 {runtime_secret_path(runtime)}" if runtime else "")
            items.append(Item("db.connection", FAIL, f"DB 접속 정보 없음({src})"))
        else:
            items += check_db(url, s.worker.heartbeat_interval_s)
    else:
        items.append(Item("db.connection", SKIP, "--no-db"))
    return items


def format_table(items: list[Item]) -> str:
    w_key = max([len("항목")] + [len(i.key) for i in items])
    lines = [f"{'항목':<{w_key}}  결과  내용", f"{'-' * w_key}  ----  {'-' * 40}"]
    lines += [f"{i.key:<{w_key}}  {i.status:<4}  {i.detail}" for i in items]
    n = {k: sum(1 for i in items if i.status == k) for k in (OK, WARN, FAIL, SKIP)}
    lines.append(f"요약: OK {n[OK]} · WARN {n[WARN]} · FAIL {n[FAIL]} · SKIP {n[SKIP]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, out: Callable[[str], None] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m esl_platform.check", description="ESL 플랫폼 환경 점검")
    ap.add_argument("--runtime", default="", help="설치 런타임 폴더(<런타임>/config/esl_platform.yaml, secrets/database_url)")
    ap.add_argument("--config", default="", help="플랫폼 설정 파일(기본: --runtime 또는 env ESL_PLATFORM_CONFIG)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    ap.add_argument("--no-db", action="store_true", help="DB 점검 생략")
    ap.add_argument("--min-free-gb", type=float, default=20.0, help="esl_root 여유 공간 경고 기준(GB, 기본 20)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) and 2
    write = out or (lambda s: print(s, flush=True))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    runtime = os.path.abspath(args.runtime) if args.runtime else None
    cfg = resolve_config_path(args.config or None, runtime, dict(os.environ))
    items = run_checks(cfg, runtime=runtime, use_db=not args.no_db, min_free_gb=args.min_free_gb)
    if args.json:
        write(json.dumps({"config": cfg, "items": [asdict(i) for i in items],
                          "ok": not any(i.status == FAIL for i in items)}, ensure_ascii=False))
    else:
        write(format_table(items))
    return 1 if any(i.status == FAIL for i in items) else 0


if __name__ == "__main__":
    sys.exit(main())
