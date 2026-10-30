"""physicsai 패키지 wheel 수집·대조(계약 esl_bead_doe.md §6.4·BD-D-19 paicad, esl_scx_relay.md §13·SR-D-2 simdash_adapters).
표준 라이브러리만 쓴다. lock 하나 = 패키지 하나: 패키지 이름 = lock.subdir 마지막 구간(packages/paicad → paicad,
packages/simdash_adapters → simdash_adapters), wheel 이름 = <패키지>-<version>-py3-none-any.whl. v0.11.0: console_script 는
null 허용(simdash_adapters — 실행 명령 없음), check 는 console_script 가 없으면 --module(기본 = lock 패키지)을 import 확인.
파일 이름(paicad_wheel.py)은 호출부 호환을 위해 유지한다.

  python paicad_wheel.py collect --lock deploy/paicad.lock --out-dir <wheels> [--repo <physicsai 저장소>] [--wheel <파일>]
                                 [--work <임시 폴더>] [--python <빌드 Python>]
      lock 의 커밋(physicsai-platform, packages/paicad)을 git archive 로 꺼내(줄 끝 변환 없음) pip wheel --no-deps 로 빌드하고
      정규화(아래)한 뒤 버전·sha256 을 lock 과 대조해 <wheels>/<lock.wheel> 로 둔다. 불일치면 종료 1(묶음 중단).
      --repo 가 없으면 lock.source(GitHub)에서 그 커밋만 얕게 받는다(--work 아래, 원 저장소·physicsai 폴더에는 쓰지 않음).
      --wheel 이 있으면 빌드하지 않고 그 wheel 을 정규화·대조만 한다(physicsai 묶음의 wheel 재사용 등).
  python paicad_wheel.py verify --lock deploy/paicad.lock --wheel <파일>      대조만(설치 전 — 종료 0 일치, 1 불일치)
  python paicad_wheel.py digest --wheel <파일>                                 정규화 sha256 출력(lock 갱신용)
  python paicad_wheel.py check --lock deploy/paicad.lock [--exe <venv>/Scripts/paicad.exe] [--wheel deploy/wheels/<lock.wheel>]
                               [--min-version X.Y.Z]
      설치 확인: paicad version --json(paicad ≥ min, ocp 있음 — 사유 코드 PAICAD_*), gmsh import(없으면 경고 GMSH_UNAVAILABLE).
      설치 venv 의 Python 으로 실행한다(gmsh 는 그 Python 으로 확인). --wheel(v0.10.1): 저장소 동봉 wheel(deploy/wheels) 등
      wheel 파일도 lock 과 대조(PAICAD_WHEEL_NOT_FOUND·PAICAD_WHEEL_MISMATCH). --exe·--wheel 중 하나 이상 — --wheel 만이면 파일 대조만.
  python paicad_wheel.py check --lock deploy/simdash_adapters.lock [--module simdash_adapters.hpc] [--wheel <파일>]
      console_script 가 null 인 lock(v0.11.0): 설치 venv 의 Python 으로 실행 — 별도 프로세스에서 모듈 import·버전 = lock 확인
      (사유 코드 SCX_ADAPTER_*), simdash_adapters.hpc 면 ScxHpcGateway·ScxRadiossRequest 존재까지. --wheel 은 파일 대조.

정규화: wheel(zip)을 같은 항목·같은 내용으로 다시 쓴다 — 무압축(ZIP_STORED, zlib 판 차이 없음), 시각 1980-01-01, 권한 0644,
이름 순(.dist-info 는 끝, RECORD 는 맨 끝). 빌드 OS·시각·umask 와 무관하게 같은 소스 + 같은 setuptools(lock.build_requires)면
같은 바이트가 되므로 lock 의 sha256 하나로 Windows·Linux 준비 PC 결과를 대조할 수 있다. RECORD(파일별 해시)는 바꾸지 않는다.
결과 JSON 한 줄을 표준 출력에 쓴다(PowerShell 이 읽음). 경로·비밀값은 lock 에 없다.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

LOCK_KEYS = ("version", "source", "branch", "commit", "subdir", "wheel", "sha256", "build_requires", "console_script",
             "runtime_requires")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
_PIN = re.compile(r"^[A-Za-z0-9_.\-]+==[0-9][0-9A-Za-z.\-+]*$")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644


class LockError(ValueError):
    pass


def read_lock(path: str | os.PathLike) -> dict[str, Any]:
    """deploy/<패키지>.lock(JSON) 읽기·형식 검사(paicad.lock·simdash_adapters.lock)."""
    name = Path(path).name
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LockError(f"{name} 을 읽을 수 없습니다: {path} ({exc})") from exc
    if not isinstance(d, dict):
        raise LockError(f"{name} 최상위가 객체가 아닙니다")
    miss = [k for k in LOCK_KEYS if k not in d]
    if miss:
        raise LockError(f"{name} 키 없음: {', '.join(miss)}")
    errs = []
    pkg = package_name(d)
    if not _SEMVER.match(str(d["version"])):
        errs.append("version")
    if not _REPO.match(str(d["source"])):
        errs.append("source")
    if not _HEX40.match(str(d["commit"])):
        errs.append("commit(40자 소문자 16진)")
    if not _HEX64.match(str(d["sha256"])):
        errs.append("sha256(64자 소문자 16진)")
    if not pkg or str(d["subdir"]).strip("/") != f"packages/{pkg}":
        errs.append("subdir(packages/<패키지>)")
    if d["wheel"] != f"{pkg}-{d['version']}-py3-none-any.whl":
        errs.append("wheel(<패키지>-<version>-py3-none-any.whl)")
    if not isinstance(d["build_requires"], list) or not d["build_requires"] or not all(_PIN.match(str(x)) for x in d["build_requires"]):
        errs.append("build_requires(정확 고정 목록)")
    if pkg == "paicad":
        if d["console_script"] != "paicad":
            errs.append("console_script")
    elif d["console_script"] is not None and not _SCRIPT.match(str(d["console_script"])):
        errs.append("console_script(이름 또는 null)")
    if not isinstance(d["runtime_requires"], list):
        errs.append("runtime_requires")
    if errs:
        raise LockError(f"{name} 형식 오류: {', '.join(errs)}")
    return d


_PKG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCRIPT = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def package_name(lock: dict[str, Any]) -> str:
    """lock.subdir 마지막 구간(= import 이름 = wheel 파일 이름 앞부분). 형식이 아니면 ""."""
    last = str(lock.get("subdir") or "").strip("/").rsplit("/", 1)[-1]
    return last if _PKG.match(last) else ""


def _order(name: str) -> tuple[int, str]:
    top = name.split("/", 1)[0]
    if top.endswith(".dist-info"):
        return (2, name) if name.endswith("/RECORD") else (1, name)
    return (0, name)


def normalize_bytes(data: bytes) -> bytes:
    """wheel 바이트 → 정규화 wheel 바이트(내용 불변)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    names = [i.filename for i in src.infolist() if not i.is_dir()]
    if len(set(names)) != len(names):
        raise ValueError("wheel 안에 같은 이름 항목이 두 번 있습니다")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as dst:
        for n in sorted(names, key=_order):
            zi = zipfile.ZipInfo(n, date_time=ZIP_DATE)
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 3
            zi.external_attr = FILE_MODE << 16
            dst.writestr(zi, src.read(n))
    return out.getvalue()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def wheel_meta(data: bytes) -> dict[str, Any]:
    """METADATA 의 Name·Version·Requires-Dist, entry_points 의 console script 이름."""
    z = zipfile.ZipFile(io.BytesIO(data))
    meta_name = next((n for n in z.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)), None)
    if not meta_name:
        raise ValueError("wheel 에 METADATA 가 없습니다")
    meta = z.read(meta_name).decode("utf-8", "replace")
    head = meta.split("\n\n", 1)[0]
    get = lambda k: [ln.split(":", 1)[1].strip() for ln in head.splitlines() if ln.lower().startswith(k.lower() + ":")]  # noqa: E731
    ep_name = meta_name.rsplit("/", 1)[0] + "/entry_points.txt"
    scripts: list[str] = []
    if ep_name in z.namelist():
        sec = ""
        for ln in z.read(ep_name).decode("utf-8", "replace").splitlines():
            s = ln.strip()
            if s.startswith("["):
                sec = s
            elif sec == "[console_scripts]" and "=" in s:
                scripts.append(s.split("=", 1)[0].strip())
    return {"name": (get("Name") or [""])[0], "version": (get("Version") or [""])[0],
            "requires": get("Requires-Dist"), "console_scripts": scripts}


def verify_bytes(data: bytes, lock: dict[str, Any]) -> dict[str, Any]:
    norm = normalize_bytes(data)
    m = wheel_meta(norm)
    sha = sha256_bytes(norm)
    problems = []
    pkg = package_name(lock)
    if re.sub(r"[-_.]+", "_", m["name"].lower()) != pkg:
        problems.append(f"이름 {m['name']!r} ≠ {pkg}")
    if m["version"] != lock["version"]:
        problems.append(f"버전 {m['version']} ≠ lock {lock['version']}")
    if lock["console_script"] is not None and lock["console_script"] not in m["console_scripts"]:
        problems.append(f"실행 명령 {lock['console_script']} 없음")
    if sha != lock["sha256"]:
        problems.append(f"sha256 {sha} ≠ lock {lock['sha256']}")
    return {"ok": not problems, "problems": problems, "sha256": sha, "version": m["version"],
            "console_scripts": m["console_scripts"], "requires": m["requires"], "normalized": norm}


def _run(argv: list[str], cwd: str | None = None) -> None:
    print("+ " + " ".join(argv), file=sys.stderr)
    r = subprocess.run(argv, cwd=cwd, stdout=sys.stderr, stderr=sys.stderr)   # 표준 출력은 결과 JSON 전용
    if r.returncode != 0:
        raise RuntimeError(f"실패(종료코드 {r.returncode}): {' '.join(argv)}")


def export_source(lock: dict[str, Any], work: Path, repo: str | None) -> Path:
    """lock 커밋의 packages/<패키지> 를 work/src 로 꺼낸다(git archive, core.autocrlf=false — 줄 끝 그대로). 원 저장소에는 쓰지 않는다."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git 이 없습니다(패키지 소스를 꺼내려면 git 필요 — 또는 --wheel 로 빌드된 wheel 을 주세요)")
    commit, sub = lock["commit"], str(lock["subdir"]).strip("/")
    if repo:
        gd = repo
        r = subprocess.run([git, "-C", gd, "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"저장소 {repo} 에 lock 커밋 {commit[:12]} 이 없습니다 — 그 저장소에서 git fetch 후 다시 실행"
                               f"(브랜치 {lock.get('branch')}). 이 스크립트는 저장소를 바꾸지 않습니다")
    else:
        gd = str(work / "repo")
        os.makedirs(gd, exist_ok=True)
        _run([git, "-C", gd, "init", "-q"])
        _run([git, "-C", gd, "fetch", "-q", "--depth", "1", f"https://github.com/{lock['source']}", commit])
    tar = work / "src.tar"
    _run([git, "-c", "core.autocrlf=false", "-C", gd, "archive", "--format=tar", "-o", str(tar), commit, sub])
    dest = work / "src"
    with tarfile.open(tar) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            tf.extractall(dest)
    src = dest / sub
    if not (src / "pyproject.toml").is_file():
        raise RuntimeError(f"커밋 {commit[:12]} 에 {sub}/pyproject.toml 이 없습니다")
    return src


def build_wheel(src: Path, work: Path, lock: dict[str, Any], python: str) -> bytes:
    """빌드용 venv(work/bvenv, lock.build_requires 고정)에서 pip wheel --no-deps --no-build-isolation."""
    venv = work / "bvenv"
    _run([python, "-m", "venv", str(venv)])
    vpy = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run([str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "-q", *lock["build_requires"]])
    out = work / "whl"
    _run([str(vpy), "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "--no-build-isolation",
          "-w", str(out), str(src)])
    whl = sorted(out.glob(f"{package_name(lock)}-*.whl"))
    if len(whl) != 1:
        raise RuntimeError(f"빌드 결과 wheel 이 1개가 아닙니다: {[w.name for w in whl]}")
    return whl[0].read_bytes()


def collect(args: argparse.Namespace) -> dict[str, Any]:
    lock = read_lock(args.lock)
    out_dir = Path(args.out_dir)
    tmp_own = not args.work
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix=f"{package_name(lock) or 'pkg'}_build_"))
    try:
        if args.wheel:
            data = Path(args.wheel).read_bytes()
            how = "wheel"
        else:
            if work.exists() and any(work.iterdir()):
                raise RuntimeError(f"작업 폴더가 비어 있지 않습니다: {work}")
            work.mkdir(parents=True, exist_ok=True)
            src = export_source(lock, work, args.repo or None)
            data = build_wheel(src, work, lock, args.python or sys.executable)
            how = "build"
        v = verify_bytes(data, lock)
        res = {k: v[k] for k in ("ok", "problems", "sha256", "version")}
        res.update({"how": how, "commit": lock["commit"], "wheel": None})
        if v["ok"]:
            out_dir.mkdir(parents=True, exist_ok=True)
            dst = out_dir / lock["wheel"]
            dst.write_bytes(v["normalized"])
            res["wheel"] = str(dst)
        return res
    finally:
        if tmp_own:
            shutil.rmtree(work, ignore_errors=True)


def _vt(s: Any) -> tuple[int, ...]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(s or ""))
    return tuple(int(x) for x in m.groups()) if m else (-1,)


CODE_PREFIX = {"paicad": "PAICAD", "simdash_adapters": "SCX_ADAPTER"}


def code_prefix(lock: dict[str, Any]) -> str:
    pkg = package_name(lock)
    return CODE_PREFIX.get(pkg, pkg.upper() or "WHEEL")


def check_wheel(lock: dict[str, Any], path: str) -> dict[str, Any]:
    """wheel 파일(저장소 동봉 deploy/wheels 등) ↔ lock 대조. {path, ok, sha256, problems(사유 코드 <PFX>_WHEEL_* —
    paicad = PAICAD_WHEEL_*, simdash_adapters = SCX_ADAPTER_WHEEL_*)}."""
    pfx = code_prefix(lock)
    out: dict[str, Any] = {"path": path, "ok": False, "sha256": None, "problems": []}
    if not path or not os.path.isfile(path):
        out["problems"].append(f"{pfx}_WHEEL_NOT_FOUND: wheel 파일 없음({path})")
        return out
    try:
        v = verify_bytes(Path(path).read_bytes(), lock)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        out["problems"].append(f"{pfx}_WHEEL_MISMATCH: wheel 을 읽을 수 없음({exc})")
        return out
    out["sha256"] = v["sha256"]
    out["problems"] = [f"{pfx}_WHEEL_MISMATCH: {p}" for p in v["problems"]]
    out["ok"] = v["ok"]
    return out


# 모듈 확인(별도 프로세스, -I): import → __version__(없으면 배포 메타데이터) 출력, simdash_adapters.hpc 는 SCX 이름 존재까지
_MODULE_PROBE = (
    "import importlib, importlib.metadata as md, json, sys\n"
    "m = importlib.import_module(sys.argv[1])\n"
    "top = sys.argv[1].split('.')[0]\n"
    "v = getattr(importlib.import_module(top), '__version__', None)\n"
    "try:\n    v = v or md.version(sys.argv[2])\nexcept Exception:\n    pass\n"
    "need = sys.argv[3].split(',') if len(sys.argv) > 3 and sys.argv[3] else []\n"
    "print(json.dumps({'version': v, 'missing': [n for n in need if not hasattr(m, n)]}))\n"
)
MODULE_NEEDS = {"simdash_adapters.hpc": ("ScxHpcGateway", "ScxRadiossRequest")}


def check_module(lock: dict[str, Any], module: str | None = None, *, python: str | None = None, timeout: float = 60.0,
                 wheel: str | None = None) -> dict[str, Any]:
    """console_script 가 없는 lock(v0.11.0 simdash_adapters)의 설치 확인: 설치 venv 의 Python(-I, 별도 프로세스)으로 module
    (기본 = lock 패키지) import → 버전 = lock(아니면 <PFX>_VERSION_MISMATCH), MODULE_NEEDS 이름 존재(<PFX>_MISSING).
    wheel 을 주면 파일 대조도(check_wheel). shell=False, 인자 고정."""
    pfx = code_prefix(lock)
    mod = module or package_name(lock)
    res: dict[str, Any] = {"ok": False, "module": mod, "version": None, "pinned": lock["version"], "commit": lock["commit"],
                           "problems": [], "warnings": []}
    if wheel is not None:
        w = check_wheel(lock, wheel)
        res["wheel"] = {k: w[k] for k in ("path", "ok", "sha256")}
        res["problems"].extend(w["problems"])
    py = python or sys.executable
    dist = package_name(lock).replace("_", "-")
    try:
        r = subprocess.run([py, "-I", "-c", _MODULE_PROBE, mod, dist, ",".join(MODULE_NEEDS.get(mod, ()))],
                           capture_output=True, text=True, timeout=timeout)
        out = json.loads((r.stdout or "").strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        out = None
        res["problems"].append(f"{pfx}_MISSING: {mod} 확인 실패({type(exc).__name__})")
    else:
        if not isinstance(out, dict):
            tail = ((r.stderr or "").strip().splitlines() or [""])[-1][:200]
            res["problems"].append(f"{pfx}_MISSING: {mod} 를 불러오지 못함({tail})")
    if isinstance(out, dict):
        res["version"] = out.get("version")
        if out.get("missing"):
            res["problems"].append(f"{pfx}_MISSING: {mod} 에 {', '.join(out['missing'])} 없음")
        if res["version"] != lock["version"]:
            res["problems"].append(f"{pfx}_VERSION_MISMATCH: {res['version']} ≠ lock {lock['version']}")
    res["ok"] = not res["problems"]
    return res


def check(lock: dict[str, Any], exe: str | None, *, min_version: str | None = None, python: str | None = None,
          timeout: float = 60.0, wheel: str | None = None) -> dict[str, Any]:
    """설치 확인(BD-D-19·20): `<exe> version --json` → paicad ≥ min(기본 lock.version) 그리고 ocp 가 null 아님,
    lock.version 과 다르면 경고. gmsh = 이 Python(설치 venv)으로 별도 프로세스에서 import(③ 만 — 없으면 경고).
    ok 는 paicad 판정만(gmsh 없음은 ③ 만 비활성). shell=False, 인자 고정.
    wheel(v0.10.1): 주면 그 파일도 lock 과 대조(check_wheel — 결과 res.wheel). exe 가 없고 wheel 만이면 파일 대조만 한다."""
    res: dict[str, Any] = {"ok": False, "paicad": None, "ocp": None, "gmsh": None, "exe": exe, "pinned": lock["version"],
                           "problems": [], "warnings": []}
    if wheel is not None:
        w = check_wheel(lock, wheel)
        res["wheel"] = {k: w[k] for k in ("path", "ok", "sha256")}
        res["problems"].extend(w["problems"])
        if not exe:
            res["ok"] = not res["problems"]
            return res
    if not exe or not os.path.isfile(exe):
        res["problems"].append(f"PAICAD_NOT_FOUND: paicad 실행 파일 없음({exe})")
    else:
        try:
            r = subprocess.run([exe, "version", "--json"], capture_output=True, text=True, timeout=timeout)
            v = json.loads((r.stdout or "").strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            v, r = None, None
            res["problems"].append(f"PAICAD_CHECK_FAILED: {exc}")
        if not isinstance(v, dict):
            if r is not None:
                res["problems"].append(f"PAICAD_CHECK_FAILED: paicad version --json 실패(종료코드 {r.returncode})")
        else:
            res["paicad"], res["ocp"] = v.get("paicad"), v.get("ocp")
            if _vt(res["paicad"]) < _vt(min_version or lock["version"]):
                res["problems"].append(f"PAICAD_VERSION_LOW: paicad {res['paicad']} < {min_version or lock['version']}")
            if res["ocp"] in (None, ""):
                res["problems"].append("PAICAD_OCP_MISSING: OCP(cadquery-ocp)를 불러오지 못함")
            if res["paicad"] != lock["version"]:
                res["warnings"].append(f"paicad {res['paicad']} ≠ 배포 고정 {lock['version']}(deploy/paicad.lock)")
    py = python or sys.executable
    try:
        g = subprocess.run([py, "-I", "-c", "import gmsh; print(gmsh.__version__)"], capture_output=True, text=True,
                           timeout=timeout)
        if g.returncode == 0 and g.stdout.strip():
            res["gmsh"] = g.stdout.strip().splitlines()[-1]
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not res["gmsh"]:
        res["warnings"].append("GMSH_UNAVAILABLE: gmsh 를 불러오지 못함 — ③(STEP 만) 시나리오·STEP 내보내기만 비활성")
    res["ok"] = not res["problems"]
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paicad_wheel.py")
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collect")
    c.add_argument("--lock", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--repo", default="")
    c.add_argument("--wheel", default="")
    c.add_argument("--work", default="")
    c.add_argument("--python", default="")
    v = sp.add_parser("verify")
    v.add_argument("--lock", required=True)
    v.add_argument("--wheel", required=True)
    d = sp.add_parser("digest")
    d.add_argument("--wheel", required=True)
    k = sp.add_parser("check")
    k.add_argument("--lock", required=True)
    k.add_argument("--exe", default="")
    k.add_argument("--wheel", default=None)
    k.add_argument("--min-version", default="")
    k.add_argument("--module", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "collect":
            res = collect(a)
        elif a.cmd == "check" and (a.module or read_lock(a.lock)["console_script"] is None):
            res = check_module(read_lock(a.lock), a.module or None, wheel=a.wheel)
        elif a.cmd == "check":
            if not a.exe and a.wheel is None:
                raise ValueError("check 에는 --exe 또는 --wheel 이 필요합니다")
            res = check(read_lock(a.lock), a.exe or None, min_version=a.min_version or None, wheel=a.wheel)
        elif a.cmd == "verify":
            vv = verify_bytes(Path(a.wheel).read_bytes(), read_lock(a.lock))
            res = {k: vv[k] for k in ("ok", "problems", "sha256", "version", "console_scripts")}
        else:
            data = normalize_bytes(Path(a.wheel).read_bytes())
            res = {"ok": True, "sha256": sha256_bytes(data), **{k: wheel_meta(data)[k] for k in ("name", "version")}}
    except (LockError, RuntimeError, OSError, ValueError, zipfile.BadZipFile) as exc:
        res = {"ok": False, "problems": [str(exc)]}
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    if not res.get("ok"):
        for p in res.get("problems") or []:
            print(f"paicad wheel: {p}", file=sys.stderr)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
