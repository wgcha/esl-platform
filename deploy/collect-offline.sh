#!/usr/bin/env bash
# 인터넷 되는 준비 PC에서 Windows 폐쇄망 설치 묶음(esl-offline-<version>.zip)을 만든다(physicsai deploy/collect-offline.sh와 같은 구성).
# 사용: bash deploy/collect-offline.sh [--dry-run] [--out <폴더>] [--no-download] [--frontend-dist <빌드 폴더>]
#                                      [--physicsai-repo <physicsai 저장소>] [--paicad-wheel <wheel>] [--no-paicad]
#   --dry-run        : 실행할 명령만 출력하고 아무것도 실행하지 않는다.
#   --out <폴더>     : 작업 폴더(기본 dist/bundle). 묶음 zip은 그 부모 폴더(기본 dist/)에 만든다. dist/에는 '*' .gitignore를 둔다(git 제외).
#   --no-download    : Windows 휠을 내려받지 않고 wheels/DOWNLOAD-LIST.txt(= requirements.lock)만 둔다(구조 시험·네트워크 없는 PC).
#                      이 묶음으로는 설치할 수 없다(install.ps1이 wheels에서 패키지를 찾지 못함).
#   --frontend-dist  : 이미 빌드한 프런트 폴더(index.html)를 그대로 묶는다(npm 빌드 생략).
#   비드 DOE 형상 엔진 paicad(v0.9.0, 계약 esl_bead_doe.md §6.4): deploy/paicad.lock 의 physicsai 커밋 packages/paicad 를
#   deploy/paicad_wheel.py 로 빌드(pip wheel --no-deps, setuptools 고정)·정규화하고 버전·sha256 을 lock 과 대조해 wheels/ 에 넣는다(불일치 중단).
#   --physicsai-repo : 그 커밋이 있는 로컬 physicsai 저장소(읽기만 — 없으면 GitHub 에서 그 커밋만 얕게 받음).
#   --paicad-wheel   : 이미 빌드된 paicad wheel 을 대조만 해서 넣는다.  --no-paicad : paicad 를 넣지 않는다(묶음은 비드 DOE 비활성).
#   --no-download 이면 paicad 도 건너뛴다. OCP(cadquery-ocp)·gmsh 휠은 requirements.lock 의 bead_doe 절로 함께 받는다.
# 산출 구조: wheels/*.whl(win_amd64 cp312, deploy/requirements.lock — pypardiso·MKL·OCP·gmsh 포함 + paicad-<ver>-py3-none-any.whl), frontend/(vite build, base /esl/),
#   app/(esl, backend/esl_platform, worker/esl_worker, migrations, resources(tcl·opt_method_sources.json·doe_messages.json·doe_method_sources.json), alembic.ini, pyproject.toml, VERSION, CHANGELOG.md, BUILD.json, esl_service.py),
#   config/(esl_platform.prod.example.yaml, esl_platform.example.yaml, esl.example.yaml, library.example.yaml, ista6.yaml), deploy/
# 시연 모드(deploy/demo)는 합성 Case를 스스로 만들므로 추가 자원이 없다.
set -euo pipefail
DRY=0
NODL=0
OUTDIR="dist/bundle"
FE_DIST=""
PAICAD_REPO=""
PAICAD_WHEEL=""
NOPAICAD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --no-download) NODL=1 ;;
    --out) OUTDIR="$2"; shift ;;
    --frontend-dist) FE_DIST="$2"; shift ;;
    --physicsai-repo) PAICAD_REPO="$2"; shift ;;
    --paicad-wheel) PAICAD_WHEEL="$2"; shift ;;
    --no-paicad) NOPAICAD=1 ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
  shift
done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
case "$OUTDIR" in /*) ;; *) OUTDIR="$ROOT/$OUTDIR" ;; esac
case "$FE_DIST" in ""|/*) ;; *) FE_DIST="$ROOT/$FE_DIST" ;; esac
OUT="$(dirname "$OUTDIR")/esl-offline-${VERSION}.zip"
# 작업 폴더는 비우고 다시 만든다 → 루트·저장소·홈·소스 폴더는 거부
case "${OUTDIR%/}" in ""|/|"$ROOT"|"${HOME:-/}"|"$ROOT"/deploy*|"$ROOT"/esl|"$ROOT"/esl/*|"$ROOT"/backend*|"$ROOT"/worker*|"$ROOT"/frontend*|"$ROOT"/config*|"$ROOT"/migrations*)
  echo "작업 폴더로 쓸 수 없는 위치입니다(비우고 다시 만드는 폴더): $OUTDIR" >&2; exit 2 ;;
esac

run() {
  echo "+ $*"
  if [ "$DRY" -eq 0 ]; then
    eval "$@"
  fi
}

run "rm -rf '$OUTDIR'"
run "mkdir -p '$(dirname "$OUTDIR")'"
if [ "$(dirname "$OUTDIR")" = "$ROOT/dist" ] && [ ! -f "$ROOT/dist/.gitignore" ]; then
  run "printf '*\\n' > '$ROOT/dist/.gitignore'"
fi
run "mkdir -p '$OUTDIR/wheels' '$OUTDIR/frontend' '$OUTDIR/app/backend' '$OUTDIR/app/worker' '$OUTDIR/config' '$OUTDIR/deploy'"
if [ "$NODL" -eq 1 ]; then
  run "cp deploy/requirements.lock '$OUTDIR/wheels/DOWNLOAD-LIST.txt'"
else
  run "$PY -m pip download --disable-pip-version-check -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.12 -d '$OUTDIR/wheels'"
fi
# 비드 DOE paicad wheel(lock 커밋 빌드·정규화·sha256 대조 — 불일치면 여기서 중단)
if [ "$NODL" -eq 1 ] || [ "$NOPAICAD" -eq 1 ]; then
  echo "paicad wheel 생략(--no-download/--no-paicad) — 이 묶음으로 설치하면 비드 DOE 는 비활성"
else
  PAICAD_ARGS=""
  [ -z "$PAICAD_REPO" ] || PAICAD_ARGS="$PAICAD_ARGS --repo '$PAICAD_REPO'"
  [ -z "$PAICAD_WHEEL" ] || PAICAD_ARGS="$PAICAD_ARGS --wheel '$PAICAD_WHEEL'"
  run "$PY -I deploy/paicad_wheel.py collect --lock deploy/paicad.lock --out-dir '$OUTDIR/wheels'$PAICAD_ARGS"
fi
# 프런트: --frontend-dist가 있으면 그대로, 아니면 frontend에서 npm ci && npm run build(Node 22)
if [ -n "$FE_DIST" ]; then
  [ "$DRY" -eq 1 ] || [ -f "$FE_DIST/index.html" ] || { echo "프런트 빌드에 index.html이 없습니다: $FE_DIST" >&2; exit 1; }
  run "cp -r '$FE_DIST/.' '$OUTDIR/frontend/'"
else
  run "(cd frontend && npm ci --no-audit --no-fund && npm run build)"
  run "cp -r frontend/dist/. '$OUTDIR/frontend/'"
fi
run "cp -r esl '$OUTDIR/app/esl'"
run "cp -r backend/esl_platform '$OUTDIR/app/backend/esl_platform'"
run "cp -r worker/esl_worker '$OUTDIR/app/worker/esl_worker'"
run "cp -r migrations '$OUTDIR/app/migrations'"
run "mkdir -p '$OUTDIR/app/resources'"
run "cp -r resources/tcl resources/opt_method_sources.json resources/doe_messages.json resources/doe_method_sources.json '$OUTDIR/app/resources/'"
run "cp alembic.ini pyproject.toml VERSION CHANGELOG.md '$OUTDIR/app/'"
# 코드 스냅샷 버전 기록(계약 esl_p3_ux.md §3): BUILD.json {version, commit, built_at}
APP_VER="$(tr -d ' \r\n' < VERSION)"
APP_COMMIT="$(git rev-parse --short=7 HEAD 2>/dev/null || true)"
APP_BUILT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$APP_COMMIT" ]; then APP_COMMIT_JSON="\"$APP_COMMIT\""; else APP_COMMIT_JSON=null; fi
run "printf '{\"version\": \"%s\", \"commit\": %s, \"built_at\": \"%s\"}\\n' '$APP_VER' '$APP_COMMIT_JSON' '$APP_BUILT' > '$OUTDIR/app/BUILD.json'"
run "cp deploy/esl_service.py '$OUTDIR/app/esl_service.py'"
run "cp config/esl_platform.prod.example.yaml config/esl_platform.example.yaml config/esl.example.yaml config/library.example.yaml config/ista6.yaml '$OUTDIR/config/'"
run "cp -r deploy/. '$OUTDIR/deploy/'"
run "find '$OUTDIR' -name __pycache__ -type d -prune -exec rm -rf {} +"
run "rm -f '$OUT'"
run "(cd '$OUTDIR' && $PY -m zipfile -c '$OUT' wheels frontend app config deploy)"
echo "묶음: $OUT"
