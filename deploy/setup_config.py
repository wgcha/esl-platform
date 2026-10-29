"""ESL 설치(deploy/setup.ps1 — git 폴더, deploy/install.ps1 — 오프라인 묶음)의 설정 파일 계획·작성. 설치 venv의 Python으로 부른다.

  python setup_config.py plan  --inputs <inputs.json> [--out <결과.json>]   계획만 계산해 JSON으로 출력(파일을 바꾸지 않음)
  python setup_config.py write --inputs <inputs.json> [--out <결과.json>]   계획대로 deploy.json(git 폴더 설치만)·설정 파일을 쓰고
                                                       (바뀌는 기존 파일은 먼저 <런타임>\\_backup\\<UTC>로 복사) esl_root 폴더를 만든 뒤
                                                       설정 검증 결과(esl_platform.core.config.load_config)를 JSON으로 출력

입력(JSON): mode(repo|bundle), source_root(config/*.example.yaml 이 있는 저장소·묶음 루트), code_root(검증용 코드 — backend·worker·esl),
  runtime_dir, stamp, deploy_path(bundle: 사용자가 쓴 deploy.json — 이 파일은 바꾸지 않음), deploy_defaults, deploy_explicit,
  dashboard_web_base_path(선택 — 없으면 대시보드 .env 의 WINDOWS_WEB_BASE_PATH 한 줄만 읽음).

규칙(physicsai-platform deploy/setup_config.py 와 같은 원칙)
- 이미 있는 파일은 보존한다: 사용자가 고친 값은 덮어쓰지 않고, 빠진 키(또는 비어 있는 storage 경로)만 보충한다.
- 새 esl_platform.yaml 은 config/esl_platform.prod.example.yaml(주석 유지)에서 만들고 storage.esl_root·input_roots·spdm_roots(deploy.json),
  auth.dashboard_public_login_url(대시보드 웹 경로)을 넣는다. git 폴더 설치(mode repo)는 server.frontend_root(프런트 배치 폴더 —
  백엔드가 /esl/ 직접 서빙, 대시보드 Vite 프록시 기본 구성) = deploy.json caddy_frontend_root(기본 <런타임>/frontend)를 키가 없을 때만
  넣는다(사용자가 바꾼 값·null 은 유지). 묶음 설치(mode bundle)는 Caddy 기준이라 넣지 않는다(예시 값 null). 같은 폴더에 코어 설정 esl.yaml·라이브러리 설정 library.yaml·ista6.yaml 을
  없을 때만 예시에서 복사한다(설정이 가리키는 상대 경로일 때만).
- 경로 검사: 절대경로, 공백·& | < > ^ % ! " 없음, esl_root 가 input_roots·spdm_roots 와 겹치지 않음(SPDM 밖), input_roots 존재.
  문제가 있으면 경고하고 그 폴더는 만들지 않는다(최종 판정은 플랫폼 설정 검증).
- P3-UX §6·§9.1: 서버 h3d 추출(altair.hw_exe_path·max_concurrent_hw), 동시 실행(worker.slots), PC 연결 토큰(client_token.ttl_days)
  키가 기존 설정에 없으면 예시 값으로 보충한다(있으면 유지). 추출 TCL 은 코드 스냅샷(resources/tcl)이라 설정 없음.
  솔버 의존성(pypardiso·MKL)은 requirements.lock.
- 대시보드 .env(git 폴더 설치만): VITE_ESL_TARGET=http://127.0.0.1:<server.port>·SIMDASH_ESL_ENABLED=true 를 **없을 때만 끝에 추가**한다
  (이미 있으면 "이미 있음", 다른 값이면 그대로 두고 경고 — 기존 값·다른 줄·인코딩(BOM)·줄 끝은 보존). 바꾸기 전에 <런타임>/_backup/<UTC>/dashboard.env
  로 복사한다. 추가했으면 대시보드를 다시 시작해야 반영된다. .env 가 없으면 만들지 않고 안내만 한다.
- v0.8.0(0.7.2 규칙 완화, 계약 esl_cumulative_input.md §12): 기존 설정에서 altair.hw_exe_path 파일이 있으면 그 상위 폴더를 최대
  6단계 올라가며 같은 Altair 설치의 hwsolvers/scripts/optistruct.bat 을 찾아 **실제 있을 때만** altair.optistruct_path(키가 없거나
  null·빈 값일 때만)와 opt_run.enabled: true(opt_run 섹션이 없거나 enabled 키가 없을 때만 — 명시 enabled: false 는 불변)를 추가한다.
  기존 값은 파일이 없어도 바꾸지 않는다. 바뀌면 기존 규칙대로 <런타임>/_backup/<UTC>/esl_platform.yaml 로 복사 후 쓰고 콘솔 1줄
  (write 결과 opt_autodetect.line). 그래도 비활성이면 경고 1줄(OPT_RUN_HINT, 후보 없으면 자동 감지 결과 덧붙임). 라이선스는 보지 않는다.
- v0.8.0 §9.1: 기존 설정이 upload.allowed_ext 를 명시했고 .sta·.str 이 없으면 이 두 확장자만 1회 덧붙인다(다른 항목·순서 불변).
  설치 상태 파일 <런타임>/state/ext_supplement.json 에 {"0.8.0": [".sta", ".str"]} 를 기록하고, 기록이 있으면 다시 넣지 않는다
  (사용자가 뺀 경우와 구분할 수 없으므로).
- v0.9.0 비드 DOE(계약 esl_bead_doe.md §6.4, BD-D-19): 검증할 코드(code_root)의 설정 스키마에 bead_doe 가 있을 때만(코드보다 설정이 앞서
  검증 오류가 나지 않게) <런타임>/venv/Scripts/paicad.exe 가 **실제 있으면** bead_doe.paicad.exe(키가 없거나 null·빈 값일 때만)와
  bead_doe.enabled: true(섹션이 없거나 enabled 키가 없을 때만 — 명시 false 는 불변, 경고 1줄)를 추가한다. 기존 값은 파일이 없어도 바꾸지 않는다.
  바뀌면 같은 백업 규칙·콘솔 1줄(write 결과 doe_autodetect.line), 감지 못 하면 안내 1줄(doe_autodetect.hint — 경고 아님).
  commands.paicad_* 는 쓰지 않는다(코드 기본 argv, argv[0] {paicad} = bead_doe.paicad.exe). upload.allowed_ext 를 명시한 기존 설정에는
  .step·.stp 를 1회 보충(상태 파일 키 "0.9.0", 0.8.0 과 같은 규칙).
- 비밀번호·DB URL 은 다루지 않는다.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONFIG_NAME = "esl_platform.yaml"
PROD_EXAMPLE = "esl_platform.prod.example.yaml"
# 설정 폴더에 함께 두는 파일: (설정 키 경로, 기본 파일 이름, 원본 예시)
COMPANIONS = ((("core", "config_path"), "esl.yaml", "esl.example.yaml"),
              (("library", "config_path"), "library.yaml", "library.example.yaml"))
ISTA6 = ("ista6.yaml", "ista6.yaml")   # library.yaml 의 library.ista6 기본값(같은 폴더)
DEPLOY_KEY_ORDER = ("install_mode", "repo_root", "install_root", "dashboard_root", "python_exe", "pg_bin", "pg_host", "pg_port",
                    "db_name", "db_role", "config_path", "service_user", "run_mode", "caddy_frontend_root",
                    "esl_root", "upload_root", "input_roots", "spdm_roots")
LIST_KEYS = ("input_roots", "spdm_roots")
# 기존 설정에 없으면 예시(prod) 값으로 보충하는 키(P3-UX §6 서버 h3d 추출·동시 실행, §9.1 PC 연결 토큰)
SUPPLEMENT_KEYS = (("altair", "hw_exe_path"), ("altair", "max_concurrent_hw"), ("worker", "slots"),
                   ("client_token", "ttl_days"))
OPT_RUN_HINT = "비드 최적화를 쓰려면 opt_run.enabled·altair.optistruct_path 설정(지금은 비활성 — 설정 파일은 자동으로 바꾸지 않음)"
OPT_AUTODETECT_NOTE = "setup이 보충 — v0.8.0 OptiStruct 자동 감지"
OPT_AUTODETECT_NONE = " (자동 감지: hw 경로 기준 hwsolvers/scripts/optistruct.bat 없음)"
OPT_AUTODETECT_LEVELS = 6
OPTISTRUCT_REL = ("hwsolvers", "scripts", "optistruct.bat")
EXT_SUPPLEMENT_VERSION = "0.8.0"
EXT_SUPPLEMENT = (".sta", ".str")            # 누적 낙하 씬 상태 파일(계약 esl_cumulative_input.md §9.1)
EXT_SUPPLEMENT_STATE = ("state", "ext_supplement.json")
# 버전별 1회 보충: (상태 파일 키, 확장자, 코드 스키마에 있어야 하는 설정 절 | None, 표의 설명)
EXT_SUPPLEMENTS = ((EXT_SUPPLEMENT_VERSION, EXT_SUPPLEMENT, None, ".sta·.str — 누적 낙하 씬"),
                   ("0.9.0", (".step", ".stp"), "bead_doe", ".step·.stp — 강성 평가 스터디 시트 STEP"))
DOE_AUTODETECT_NOTE = "setup이 보충 — v0.9.0 paicad 자동 감지"
PAICAD_REL = ("venv", "Scripts", "paicad.exe")     # 설치 venv 의 console script(paicad.lock console_script)
DOE_HINT = ("강성 평가 스터디 비활성 — 형상 엔진 paicad 가 설치되지 않음(<런타임>\\venv\\Scripts\\paicad.exe 없음). "
            "설치 스크립트의 'paicad' 경고를 확인하세요(관리자 매뉴얼 paicad 절)")
_UNSAFE = re.compile(r'[\s\x00-\x1f\x7f&|<>^%!"]')
_WIN_ABS = re.compile(r"^[A-Za-z]:[/\\]|^[\\/]{2}[^\\/]+[\\/][^\\/]+")


# ---------------------------------------------------------------------------
# 공용
# ---------------------------------------------------------------------------

def fwd(p: str) -> str:
    return p.replace("\\", "/") if p else p


def unsafe(p: str) -> bool:
    return bool(_UNSAFE.search(p))


def is_abs(p: str) -> bool:
    return bool(_WIN_ABS.match(p)) or (os.name != "nt" and p.startswith("/"))


def _norm(p: str) -> str:
    return fwd(p).rstrip("/").casefold()


def overlaps(a: str, b: str) -> bool:
    """대소문자 무시(Windows 규칙)로 a 가 b 안이거나 b 가 a 안."""
    x, y = _norm(a), _norm(b)
    return x == y or x.startswith(y + "/") or y.startswith(x + "/")


def as_list(v: Any) -> list[str]:
    """문자열 또는 목록(PowerShell 5.1 ConvertTo-Json 은 원소 1개 배열을 문자열로 낼 수 있음) → 빈 값 뺀 목록."""
    if v is None:
        return []
    if isinstance(v, dict) and "value" in v:   # PowerShell 5.1 이 PSObject 로 감싼 배열을 {"value": [...], "Count": n} 로 낼 때
        v = v["value"]
    items = [v] if isinstance(v, str) else list(v)
    return [fwd(str(x).strip()) for x in items if str(x).strip()]


def _yaml():
    import yaml  # 설치 venv에 있음(requirements.lock)

    return yaml


UPLOAD_DIR_NAME = "esl-input"


def default_upload_root(esl_root: str) -> str:
    """업로드 저장 위치 기본값: <esl_root 부모>/esl-input (계약 esl_p3_ux.md §1.1·§6)."""
    if not esl_root or not is_abs(esl_root):
        return ""
    parent = fwd(esl_root).rstrip("/").rsplit("/", 1)[0]
    return f"{parent}/{UPLOAD_DIR_NAME}" if parent else ""


def check_upload_root(upload_root: str, esl_root: str, spdm_roots: list[str]) -> tuple[list[str], bool]:
    """업로드 위치 검사 → (경고, 폴더를 만들어도 되는지). 절대경로·문자·esl_root/SPDM 겹침."""
    if not upload_root:
        return ["업로드 위치(upload_root)가 비어 있습니다 — 브라우저 업로드를 쓸 수 없습니다(설정 storage.upload_root)"], False
    warn: list[str] = []
    ok = True
    if not is_abs(upload_root) or unsafe(upload_root):
        warn.append(f"업로드 위치가 절대경로가 아니거나 공백·특수문자가 있습니다: {upload_root}")
        ok = False
    if esl_root and overlaps(upload_root, esl_root):
        warn.append(f"업로드 위치가 ESL 루트({esl_root})와 겹칩니다 — 다른 폴더를 쓰세요")
        ok = False
    for r in spdm_roots:
        if overlaps(upload_root, r):
            warn.append(f"업로드 위치가 SPDM 루트({r})와 겹칩니다 — SPDM 밖에 두세요")
            ok = False
    return warn, ok


def check_paths(esl_root: str, input_roots: list[str], spdm_roots: list[str]) -> tuple[list[str], bool]:
    """경로 검사 → (경고 목록, esl_root 를 만들어도 되는지)."""
    warn: list[str] = []
    ok_root = bool(esl_root)
    if not esl_root:
        warn.append("ESL 루트(esl_root)가 비어 있습니다 — 설정 검증에 실패해 워커가 작업을 받지 않습니다(-EslRoot 또는 deploy.json esl_root)")
    else:
        if not is_abs(esl_root):
            warn.append(f"ESL 루트가 절대경로가 아닙니다: {esl_root}")
            ok_root = False
        if unsafe(esl_root):
            warn.append(f"ESL 루트 경로에 공백·특수문자가 있습니다(쓸 수 없음): {esl_root}")
            ok_root = False
    for key, roots in (("input_roots", input_roots), ("spdm_roots", spdm_roots)):
        for r in roots:
            if not is_abs(r) or unsafe(r):
                warn.append(f"{key} 경로가 절대경로가 아니거나 공백·특수문자가 있습니다: {r}")
            if esl_root and overlaps(esl_root, r):
                warn.append(f"ESL 루트가 {key}({r})와 겹칩니다 — 산출물은 입력·SPDM 폴더 밖에 둡니다")
                ok_root = False
    for r in input_roots:
        if is_abs(r) and not unsafe(r) and not os.path.isdir(r):
            warn.append(f"입력 루트 폴더가 없습니다(공유 연결·이름 확인): {r}")
    if not input_roots:
        warn.append("입력 루트(input_roots)가 비어 있습니다 — 서버 폴더 선택은 업로드 위치(upload_root)만 가능합니다"
                    "(공유 폴더를 쓰려면 설정 파일 storage.input_roots에 추가)")
    return warn, ok_root


# ---------------------------------------------------------------------------
# YAML 텍스트 편집(주석·순서 유지). 결과는 항상 다시 읽어 검증한다(physicsai setup_config.py 와 같은 방식).
# ---------------------------------------------------------------------------

_VALUE = re.compile(r"""^(?P<pre>[ \t]*[^:#\s][^:]*:[ \t]*)(?P<val>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^#\r\n]*?)(?P<post>[ \t]+#.*)?$""")


def literal(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = "" if v is None else str(v)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", s) and s.lower() not in ("true", "false", "null", "yes", "no", "on", "off", "y", "n"):
        return s
    return json.dumps(s, ensure_ascii=False)


def _block(lines: list[str], section: str) -> tuple[int, int, str] | None:
    hdr = re.compile(rf"^{re.escape(section)}:[ \t]*(#.*)?$")
    for i, ln in enumerate(lines):
        if hdr.match(ln):
            end = len(lines)
            indent = ""
            for j in range(i + 1, len(lines)):
                s = lines[j]
                if re.match(r"^[^\s#]", s):
                    end = j
                    break
                if not indent and s.strip() and not s.lstrip().startswith("#"):
                    indent = s[: len(s) - len(s.lstrip())]
            return i, end, indent or "  "
    return None


def set_yaml_value(text: str, path: tuple[str, ...], value: Any, note: str = "") -> str:
    """path(최상위 또는 2단계)의 값을 바꾸거나(줄 끝 주석 유지) 없으면 넣는다."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    lit = literal(value)
    comment = f"  # {note}" if note else ""
    if len(path) == 1:
        rx = re.compile(rf"^{re.escape(path[0])}:")
        for i, ln in enumerate(lines):
            if rx.match(ln):
                m = _VALUE.match(ln)
                lines[i] = m.group("pre") + lit + (m.group("post") or "") if m else f"{path[0]}: {lit}"
                return nl.join(lines)
        insert_at = next((i for i, ln in enumerate(lines) if re.match(r"^[^\s#]", ln)), len(lines))
        lines.insert(insert_at, f"{path[0]}: {lit}{comment}")
        return nl.join(lines)
    section, key = path
    b = _block(lines, section)
    if b is None:
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{section}:", f"  {key}: {lit}{comment}", ""]
        return nl.join(lines)
    start, end, indent = b
    rx = re.compile(rf"^{re.escape(indent)}{re.escape(key)}:")
    for i in range(start + 1, end):
        if rx.match(lines[i]):
            m = _VALUE.match(lines[i])
            lines[i] = m.group("pre") + lit + (m.group("post") or "") if m else f"{indent}{key}: {lit}"
            return nl.join(lines)
    lines.insert(start + 1, f"{indent}{key}: {lit}{comment}")
    return nl.join(lines)


def set_yaml_nested(text: str, path: tuple[str, str, str], value: Any, note: str = "") -> str:
    """3단계 path(절 → 하위 블록 → 키) 값을 바꾸거나 넣는다(블록 표기만). 절이 없으면 끝에 새 블록, 하위 블록이 없으면 절 머리 다음에
    넣는다. 하위가 흐름 표기(`paicad: {...}`)면 바꾸지 않고 그대로 돌려준다(호출자의 결과 검증이 '직접 고치세요'로 안내)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    section, sub, key = path
    lit = literal(value)
    comment = f"  # {note}" if note else ""
    b = _block(lines, section)
    if b is None:
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{section}:", f"  {sub}:", f"    {key}: {lit}{comment}", ""]
        return nl.join(lines)
    start, end, indent = b
    hdr = re.compile(rf"^{re.escape(indent)}{re.escape(sub)}:[ \t]*(#.*)?$")
    any_sub = re.compile(rf"^{re.escape(indent)}{re.escape(sub)}:")
    si = next((i for i in range(start + 1, end) if hdr.match(lines[i])), None)
    if si is None:
        if any(any_sub.match(lines[i]) for i in range(start + 1, end)):
            return text                                   # 흐름 표기·스칼라 — 자동으로 고치지 않음
        lines[start + 1:start + 1] = [f"{indent}{sub}:", f"{indent}{indent}{key}: {lit}{comment}"]
        return nl.join(lines)
    send, sub_indent = end, ""
    for j in range(si + 1, end):
        s = lines[j]
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        lead = s[: len(s) - len(s.lstrip())]
        if len(lead) <= len(indent):
            send = j
            break
        if not sub_indent:
            sub_indent = lead
    sub_indent = sub_indent or indent + indent
    rx = re.compile(rf"^{re.escape(sub_indent)}{re.escape(key)}:")
    for i in range(si + 1, send):
        if rx.match(lines[i]):
            m = _VALUE.match(lines[i])
            lines[i] = m.group("pre") + lit + (m.group("post") or "") if m else f"{sub_indent}{key}: {lit}"
            return nl.join(lines)
    lines.insert(si + 1, f"{sub_indent}{key}: {lit}{comment}")
    return nl.join(lines)


def find_paicad(runtime: Path) -> str | None:
    """<런타임>/venv/Scripts/paicad.exe 가 실제 있으면 그 경로(fwd), 없으면 None(계약 §6.4 — 있을 때만 채움)."""
    p = Path(runtime).joinpath(*PAICAD_REL)
    return fwd(str(p)) if p.is_file() else None


def code_supports(section: str, code_root: str | None) -> bool:
    """검증할 코드(esl_platform.core.config.Settings)의 최상위 설정 절에 section 이 있는지 — 없으면 그 절을 쓰지 않는다
    (extra=forbid 라 코드보다 앞선 설정은 검증 오류)."""
    root = Path(code_root) if code_root else HERE.parent
    for p in (root / "worker", root / "backend", root):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from esl_platform.core import config as mod
    except ImportError:  # pragma: no cover - 설치 venv·코드에는 있음
        return False
    fields = getattr(getattr(mod, "Settings", None), "model_fields", None) or {}
    return section in fields


def duplicate_top_keys(text: str) -> list[str]:
    """최상위 키가 두 번 나오면(흐름 표기 `storage: {...}` 옆에 블록을 덧붙인 경우 등) 그 이름들. YAML 은 뒤 값으로 덮어써 검증을 속인다."""
    seen: set[str] = set()
    dup: list[str] = []
    for ln in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w\-]*)\s*:", ln)
        if m:
            if m.group(1) in seen:
                dup.append(m.group(1))
            seen.add(m.group(1))
    return dup


def _get(data: Any, path: tuple[str, ...]) -> tuple[bool, Any]:
    for k in path:
        if not isinstance(data, dict) or k not in data:
            return False, None
        data = data[k]
    return True, data


def _set(data: dict, path: tuple[str, ...], value: Any) -> None:
    for k in path[:-1]:
        if data.get(k) is None:
            data[k] = {}
        data = data[k]
    data[path[-1]] = value


def find_optistruct(hw_exe: str, levels: int = OPT_AUTODETECT_LEVELS) -> str | None:
    """hw 실행 파일의 상위 폴더(1..levels 단계)에서 처음 존재하는 <조상>/hwsolvers/scripts/optistruct.bat (fwd) — 같은 설치만.

    예 C:/Program Files/Altair/2026.1/hwdesktop/hw/bin/win64/hw.exe → C:/Program Files/Altair/2026.1/hwsolvers/scripts/
    optistruct.bat, 구형 <root>/hw/bin/win64/hw.exe → <root>/hwsolvers/…. 드라이브 루트에서 멈춘다."""
    if not hw_exe or not os.path.isfile(hw_exe):
        return None
    d = os.path.dirname(os.path.abspath(hw_exe))
    for _ in range(int(levels)):
        c = os.path.join(d, *OPTISTRUCT_REL)
        if os.path.isfile(c):
            return fwd(c)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def read_ext_supplement(runtime: Path) -> dict[str, Any]:
    p = runtime.joinpath(*EXT_SUPPLEMENT_STATE)
    try:
        v = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    except (OSError, ValueError):
        v = {}
    return v if isinstance(v, dict) else {}


# 대시보드 웹 경로: 운영 대시보드는 Vite가 WINDOWS_WEB_BASE_PATH(기본 /home/)에서 열린다(physicsai phase3 D3-38과 같은 규칙).
LOGIN_URL_PATH = ("auth", "dashboard_public_login_url")
LOGIN_URL_OLD_DEFAULTS = ("/", "", None)
DASHBOARD_WEB_BASE_KEY = "WINDOWS_WEB_BASE_PATH"
DASHBOARD_WEB_BASE_DEFAULT = "/home/"
_WEB_BASE_OK = re.compile(r"^/(?:[A-Za-z0-9._~\-]+/)*$")


def read_dashboard_env_value(dashboard_root: str, key: str) -> str | None:
    """대시보드 <root>/.env에서 key 한 줄의 값만 읽는다(따옴표 제거). 파일·키가 없으면 None. 다른 줄은 보관하지 않는다."""
    if not dashboard_root:
        return None
    env = Path(dashboard_root) / ".env"
    if not env.is_file():
        return None
    rx = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=\s*(.*?)\s*$")
    for line in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = rx.match(line)
        if m:
            v = m.group(1)
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            return v.strip()
    return None


def normalize_web_base(raw: str | None) -> tuple[str, str | None]:
    v = (raw or "").strip()
    if not v:
        return DASHBOARD_WEB_BASE_DEFAULT, None
    v = "/" + v.strip("/") + "/" if v.strip("/") else "/"
    if not _WEB_BASE_OK.match(v) or any(seg in (".", "..") for seg in v.split("/")):
        return "", f"대시보드 .env의 {DASHBOARD_WEB_BASE_KEY} 값을 링크 경로로 쓸 수 없습니다(영숫자·._~-·/만) — auth.dashboard_public_login_url을 직접 정하세요"
    return v, None


def dashboard_login_url(inputs: dict[str, Any], dashboard_root: str) -> tuple[str, str | None]:
    given = inputs.get("dashboard_web_base_path")
    raw = given if isinstance(given, str) else read_dashboard_env_value(dashboard_root, DASHBOARD_WEB_BASE_KEY)
    return normalize_web_base(raw)


# 대시보드 Vite 프록시 연결(physicsai VITE_PHYSICSAI_TARGET·SIMDASH_PHYSICSAI_ENABLED 와 같은 패턴)
ENV_TARGET_KEY = "VITE_ESL_TARGET"
ENV_ENABLED_KEY = "SIMDASH_ESL_ENABLED"
_TRUE = ("true", "1", "yes", "on")


def _env_unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    return v.strip()


def plan_dashboard_env(dashboard_root: str, port: Any) -> dict[str, Any] | None:
    """대시보드 .env 연결 키 계획 → {path, exists, rows[{key, want, value, action}], add[줄], warnings}. dashboard_root 가 없으면 None.

    action: "추가"(없음 — 끝에 넣음) | "이미 있음"(같은 값) | "유지(다른 값)"(바꾸지 않음 — 경고)."""
    if not dashboard_root:
        return None
    env = Path(dashboard_root) / ".env"
    target = f"http://127.0.0.1:{port}"
    wants = ((ENV_TARGET_KEY, target), (ENV_ENABLED_KEY, "true"))
    out: dict[str, Any] = {"path": str(env), "exists": env.is_file(), "rows": [], "add": [], "warnings": []}
    if not env.is_file():
        out["warnings"].append(f"대시보드 .env가 없습니다: {env} — {ENV_TARGET_KEY}={target}, {ENV_ENABLED_KEY}=true 를 직접 넣고 대시보드를 다시 시작하세요")
        for k, w in wants:
            out["rows"].append({"key": k, "want": w, "value": None, "action": "없음(.env 없음)"})
        return out
    found: dict[str, str] = {}
    for line in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and m.group(1) in (ENV_TARGET_KEY, ENV_ENABLED_KEY) and m.group(1) not in found:
            found[m.group(1)] = _env_unquote(m.group(2))
    for k, w in wants:
        cur = found.get(k)
        if cur is None:
            out["rows"].append({"key": k, "want": w, "value": None, "action": "추가"})
            out["add"].append(f"{k}={w}")
            continue
        same = cur.rstrip("/") == w if k == ENV_TARGET_KEY else cur.lower() in _TRUE
        out["rows"].append({"key": k, "want": w, "value": cur, "action": "이미 있음" if same else "유지(다른 값)"})
        if not same:
            out["warnings"].append(f"대시보드 .env의 {k}={cur} 는 그대로 둡니다(이 설치 값 {w}) — 다르면 직접 고치고 대시보드를 다시 시작하세요")
    return out


def write_dashboard_env(env_path: str, lines: list[str]) -> None:
    """.env 끝에 줄을 덧붙인다 — 기존 바이트(BOM·인코딩·다른 줄)는 그대로, 줄 끝은 파일 방식(CRLF/LF)을 따른다."""
    raw = Path(env_path).read_bytes()
    nl = b"\r\n" if b"\r\n" in raw or b"\n" not in raw else b"\n"
    add = b"" if not raw or raw.endswith(b"\n") else nl
    add += nl.join(ln.encode("utf-8") for ln in lines) + nl
    with open(env_path, "ab") as f:
        f.write(add)


def _read_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------------
# deploy.json
# ---------------------------------------------------------------------------

def merge_deploy(existing: dict[str, Any] | None, defaults: dict[str, Any], explicit: dict[str, Any]) -> tuple[dict, list, list]:
    """명시 인자 > 기존 파일 > 파생 기본값(기존 값은 덮어쓰지 않음). (deploy, 보충 키, 인자로 바꾼 키)."""
    deploy = dict(existing or {})
    added, overridden = [], []
    for k in list(DEPLOY_KEY_ORDER) + [k for k in defaults if k not in DEPLOY_KEY_ORDER]:
        if k in explicit:
            if k in deploy and deploy[k] != explicit[k]:
                overridden.append(k)
            elif k not in deploy:
                added.append(k)
            deploy[k] = explicit[k]
        elif (k not in deploy or deploy[k] in (None, "")) and k in defaults and defaults[k] not in (None, ""):
            if k not in deploy:
                added.append(k)
            deploy[k] = defaults[k]
    for k in LIST_KEYS:
        if k in deploy:
            deploy[k] = as_list(deploy[k])
    ordered = {k: deploy[k] for k in DEPLOY_KEY_ORDER if k in deploy}
    ordered.update({k: v for k, v in deploy.items() if k not in ordered})
    return ordered, added, overridden


# ---------------------------------------------------------------------------
# 계획
# ---------------------------------------------------------------------------

def opt_run_hint(cfg: Any) -> str | None:
    """비드 최적화가 설정상 꺼져 있으면(opt_run 섹션 없음·enabled 아님·altair.optistruct_path 없음) 안내 1줄, 켜져 있으면 None."""
    if not isinstance(cfg, dict):
        return OPT_RUN_HINT
    o, alt = cfg.get("opt_run"), cfg.get("altair")
    if not isinstance(o, dict) or o.get("enabled") is not True:
        return OPT_RUN_HINT
    if not isinstance(alt, dict) or not alt.get("optistruct_path"):
        return OPT_RUN_HINT
    return None


def plan(inputs: dict[str, Any]) -> dict[str, Any]:
    yaml = _yaml()
    src = Path(inputs.get("source_root") or HERE.parent)
    runtime = Path(inputs["runtime_dir"])
    mode = str(inputs.get("mode") or "repo")
    warnings: list[str] = []

    # ---- deploy.json --------------------------------------------------------------------------------
    deploy_path = Path(inputs.get("deploy_path") or (runtime / "deploy.json"))
    existing = _read_json(deploy_path)
    deploy, added, overridden = merge_deploy(existing, dict(inputs.get("deploy_defaults") or {}),
                                             dict(inputs.get("deploy_explicit") or {}))
    deploy_write = mode == "repo"   # 묶음 설치는 사용자가 쓴 deploy.json 을 바꾸지 않는다(메모리에서만 기본값 보충)
    deploy_changed = deploy_write and (existing is None or deploy != existing)

    esl_root = fwd(str(deploy.get("esl_root") or ""))
    input_roots = as_list(deploy.get("input_roots"))
    spdm_roots = as_list(deploy.get("spdm_roots"))
    path_warn, root_ok = check_paths(esl_root, input_roots, spdm_roots)
    warnings += path_warn
    # 업로드 위치: 명시 > deploy.json > <esl_root 부모>/esl-input. input_roots 에는 플랫폼 설정 로더가 자동 포함
    upload_root = fwd(str(deploy.get("upload_root") or "")) or default_upload_root(esl_root)
    if upload_root and deploy.get("upload_root") != upload_root:
        if "upload_root" not in deploy:
            added.append("upload_root")
        deploy["upload_root"] = upload_root
        deploy, _, _ = merge_deploy(deploy, {}, {})
        deploy_changed = deploy_write and (existing is None or deploy != existing)
    up_warn, upload_ok = check_upload_root(upload_root, esl_root, spdm_roots)
    warnings += up_warn

    # ---- esl_platform.yaml ----------------------------------------------------------------------------
    example_path = src / "config" / PROD_EXAMPLE
    example_text = example_path.read_text(encoding="utf-8")
    example = yaml.safe_load(example_text) or {}
    config_path = Path(deploy.get("config_path") or (runtime / "config" / CONFIG_NAME))
    config_bom = False
    if config_path.is_file():
        # 줄 끝(CRLF/LF)·BOM 보존(v0.8.0): 줄 끝 변환 없이 읽고, BOM 이 있었으면 쓸 때 다시 붙인다
        raw = config_path.read_bytes()
        config_bom = raw.startswith(b"\xef\xbb\xbf")
        with open(config_path, encoding="utf-8-sig", newline="") as fh:
            source, base_text = "existing", fh.read()
    else:
        source, base_text = "example", example_text
    try:
        base = yaml.safe_load(base_text) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"설정 파일 YAML 형식 오류 — 직접 고친 뒤 다시 실행하세요: {config_path} ({exc})")
    if not isinstance(base, dict):
        raise SystemExit(f"설정 파일 최상위가 매핑이 아닙니다: {config_path}")
    new_file = source == "example"

    desired: dict[tuple[str, ...], Any] = {("profile",): "prod"}
    for k in ("host", "port", "base_path"):
        desired[("server", k)] = (example.get("server") or {}).get(k)
    if mode == "repo" or str(deploy.get("backend_serves_frontend")).lower() in ("true", "1", "yes"):
        # 백엔드가 /esl/ 를 직접 서빙(대시보드 Vite 프록시 기본 구성). 프런트 배치 폴더 = deploy.json caddy_frontend_root(기본 <런타임>/frontend).
        # 기존 파일에 키가 없을 때만 보충 — 사용자가 null(Caddy 등 외부 서빙)이나 다른 경로로 바꾼 값은 유지.
        # 묶음 설치는 Caddy 기준이라 넣지 않는다 — 단 이전 deploy.json "backend_serves_frontend": true(작업 인자 --frontend 방식)는 이 키로 이어받는다
        desired[("server", "frontend_root")] = fwd(str(deploy.get("caddy_frontend_root") or (runtime / "frontend")))
    desired[("storage", "esl_root")] = esl_root
    desired[("storage", "input_roots")] = input_roots
    desired[("storage", "spdm_roots")] = spdm_roots
    desired[("storage", "upload_root")] = upload_root if upload_ok else ""
    # 비어 있으면 채워도 되는 키(경로 값). 사용자가 넣은 다른 값은 보존
    fill_empty = {("storage", "esl_root"), ("storage", "input_roots"), ("storage", "spdm_roots"),
                  ("storage", "upload_root")}

    text = base_text
    rows, changed = [], []
    for path, want in desired.items():
        key = ".".join(path)
        has, cur = _get(base, path)
        if new_file:
            if want is None or (has and cur == want):
                rows.append({"key": key, "value": cur, "action": "예시 값"})
                continue
            if path in fill_empty and want in ("", []):
                rows.append({"key": key, "value": cur, "action": "예시 값(지정 없음)"})
                continue
            text = set_yaml_value(text, path, want)
            rows.append({"key": key, "value": want, "action": "새로 씀"})
            changed.append(key)
        elif not has:
            if want in (None, "", []):
                rows.append({"key": key, "value": cur, "action": "없음"})
                continue
            text = set_yaml_value(text, path, want, "setup이 보충")
            rows.append({"key": key, "value": want, "action": "보충"})
            changed.append(key)
        elif path in fill_empty and cur in (None, "", []) and want not in (None, "", []):
            text = set_yaml_value(text, path, want)
            rows.append({"key": key, "value": want, "action": "빈 값 채움"})
            changed.append(key)
        else:
            note = "유지" if cur == want or want in (None, "", []) else "유지(설정 파일 값 — 바꾸려면 파일을 직접 수정)"
            rows.append({"key": key, "value": cur, "action": note})
    upgraded: dict[tuple[str, ...], Any] = {}
    # 이전 설정에 library 블록이 없으면(P2 이전) 같은 폴더 library.yaml 로 보충 — 라이브러리 쓰기 API 가 503 이 되지 않게
    if not new_file and "library" not in base:
        text = set_yaml_value(text, ("library", "config_path"), "library.yaml", "setup이 보충 — P2 라이브러리")
        upgraded[("library", "config_path")] = "library.yaml"
        rows.append({"key": "library.config_path", "value": "library.yaml", "action": "보충(새 설정 절)"})
    # P3-UX §6·§9.1: 서버 h3d 추출·동시 실행·PC 토큰 키 — 기존 설정에 없을 때만 예시 값으로 보충(사용자 값 유지)
    if not new_file:
        for path in SUPPLEMENT_KEYS:
            has_k, _ = _get(base, path)
            ok_ex, want_v = _get(example, path)
            if has_k or not ok_ex or want_v is None:
                continue
            text = set_yaml_value(text, path, want_v, "setup이 보충 — P3-UX")
            upgraded[path] = want_v
            rows.append({"key": ".".join(path), "value": want_v, "action": "보충(새 설정 키)"})
    # v0.8.0 §12: OptiStruct 경로 자동 감지 — hw 실행 파일과 같은 설치에 optistruct.bat 이 실제 있을 때만 추가(기존 값 불변)
    opt_auto: dict[str, Any] = {"added": {}, "candidate": None, "hw_exists": False, "kept_disabled": False}
    if not new_file:
        cur = yaml.safe_load(text) or {}
        _, hw = _get(cur, ("altair", "hw_exe_path"))
        if isinstance(hw, str) and hw.strip() and os.path.isfile(hw):
            opt_auto["hw_exists"] = True
            cand = find_optistruct(hw)
            opt_auto["candidate"] = cand
            has_os, cur_os = _get(cur, ("altair", "optistruct_path"))
            valid = None
            if cand and (not has_os or cur_os in (None, "")):
                text = set_yaml_value(text, ("altair", "optistruct_path"), cand, OPT_AUTODETECT_NOTE)
                upgraded[("altair", "optistruct_path")] = cand
                opt_auto["added"]["altair.optistruct_path"] = cand
                rows.append({"key": "altair.optistruct_path", "value": cand, "action": "보충(OptiStruct 자동 감지)"})
                valid = cand
            elif isinstance(cur_os, str) and cur_os and os.path.isfile(cur_os):
                valid = cur_os
            if valid:
                has_or, orun = _get(cur, ("opt_run",))
                if not has_or or orun is None or (isinstance(orun, dict) and "enabled" not in orun):
                    text = set_yaml_value(text, ("opt_run", "enabled"), True, OPT_AUTODETECT_NOTE)
                    upgraded[("opt_run", "enabled")] = True
                    opt_auto["added"]["opt_run.enabled"] = True
                    rows.append({"key": "opt_run.enabled", "value": True, "action": "보충(OptiStruct 자동 감지)"})
                elif isinstance(orun, dict) and orun.get("enabled") is False:
                    opt_auto["kept_disabled"] = True
                    warnings.append(f"비드 최적화는 설정 opt_run.enabled: false 로 꺼져 있어 그대로 둡니다(OptiStruct: {valid}) "
                                    "— 쓰려면 true 로 직접 바꾸세요")
    # v0.8.0 §9.1: upload.allowed_ext 를 명시한 기존 설정에 .sta·.str 1회 보충(기록이 있으면 다시 넣지 않음)
    # v0.9.0: .step·.stp 도 같은 규칙(키 "0.9.0") — 코드 스키마에 bead_doe 가 있을 때만
    code_root = inputs.get("code_root")
    ext_sup: dict[str, Any] = {"added": [], "record": False, "records": []}
    if not new_file:
        rec = read_ext_supplement(runtime)
        has_ae, ae = _get(base, ("upload", "allowed_ext"))
        if has_ae and isinstance(ae, list):
            new_ae, labels = list(ae), []
            for ver, exts, gate, label in EXT_SUPPLEMENTS:
                if ver in rec or (gate and not code_supports(gate, code_root)):
                    continue
                low = [str(x).lower() for x in new_ae]
                add = [e for e in exts if e not in low]
                ext_sup["records"].append(ver)
                if add:
                    new_ae += add
                    ext_sup["added"] += add
                    labels.append(label)
            ext_sup["record"] = bool(ext_sup["records"])
            if ext_sup["added"]:
                text = set_yaml_value(text, ("upload", "allowed_ext"), new_ae)
                upgraded[("upload", "allowed_ext")] = new_ae
                rows.append({"key": "upload.allowed_ext", "value": new_ae, "action": f"보충({' / '.join(labels)})"})
    # v0.9.0 §6.4: 비드 DOE paicad 경로 자동 감지 — <런타임>/venv/Scripts/paicad.exe 가 실제 있을 때만(기존 값 불변)
    doe: dict[str, Any] = {"added": {}, "candidate": None, "supported": False, "hint": None}
    if code_supports("bead_doe", code_root):
        doe["supported"] = True
        cur = yaml.safe_load(text) or {}
        cand = find_paicad(runtime)
        doe["candidate"] = cand
        has_bd, bd = _get(cur, ("bead_doe",))
        _, cur_exe = _get(cur, ("bead_doe", "paicad", "exe"))
        if has_bd and bd is not None and not isinstance(bd, dict):
            warnings.append("설정 bead_doe 가 매핑이 아니라 paicad 경로를 자동으로 넣지 않았습니다 — 직접 고치세요")
        elif cand and cur_exe in (None, ""):
            if not has_bd or bd is None or "enabled" not in bd:
                text = set_yaml_value(text, ("bead_doe", "enabled"), True, DOE_AUTODETECT_NOTE)
                upgraded[("bead_doe", "enabled")] = True
                doe["added"]["bead_doe.enabled"] = True
                rows.append({"key": "bead_doe.enabled", "value": True, "action": "보충(paicad 자동 감지)"})
            elif bd.get("enabled") is False:
                warnings.append(f"강성 평가 스터디 는 설정 bead_doe.enabled: false 로 꺼져 있어 그대로 둡니다(paicad: {cand}) "
                                "— 쓰려면 true 로 직접 바꾸세요")
            text = set_yaml_nested(text, ("bead_doe", "paicad", "exe"), cand, DOE_AUTODETECT_NOTE)
            upgraded[("bead_doe", "paicad", "exe")] = cand
            doe["added"]["bead_doe.paicad.exe"] = cand
            rows.append({"key": "bead_doe.paicad.exe", "value": cand, "action": "보충(paicad 자동 감지)"})
        elif not cand and cur_exe in (None, ""):
            doe["hint"] = DOE_HINT
    # 로그인·"대시보드로" 링크: 키가 없거나 이전 기본값 "/"일 때만 대시보드 웹 경로로, 사용자 값은 보존
    login_want, login_warn = dashboard_login_url(inputs, str(deploy.get("dashboard_root") or ""))
    if login_warn:
        warnings.append(login_warn)
    has, cur = _get(base, LOGIN_URL_PATH)
    if login_want and (new_file or not has or cur in LOGIN_URL_OLD_DEFAULTS) and cur != login_want:
        text = set_yaml_value(text, LOGIN_URL_PATH, login_want, "" if has else "setup이 보충")
        upgraded[LOGIN_URL_PATH] = login_want
        rows.append({"key": ".".join(LOGIN_URL_PATH), "value": login_want, "action": "대시보드 웹 경로로 맞춤"})
    else:
        rows.append({"key": ".".join(LOGIN_URL_PATH), "value": cur,
                     "action": "유지" if cur == login_want or not has else "유지(설정 파일 값 — 바꾸려면 파일을 직접 수정)"})
    if new_file:
        hdr = ("# ESL 플랫폼 설정 — deploy/setup_config.py 가 config/esl_platform.prod.example.yaml 에서 생성. "
               "값은 이 파일에서 직접 고친다(다시 설치·업데이트해도 덮어쓰지 않음).")
        nl = "\r\n" if "\r\n" in text else "\n"
        first, _, rest = text.partition(nl)
        text = (hdr + nl + rest) if first.startswith("#") else (hdr + nl + text)

    # 편집 결과 검증: 바꾼 키는 원하는 값, 나머지는 원본과 같아야 한다(아니면 쓰지 않고 안내)
    config_ok = True
    try:
        after = yaml.safe_load(text) or {}
        expect = copy.deepcopy(base)
        for key in changed:
            _set(expect, tuple(key.split(".")), desired[tuple(key.split("."))])
        for path, want in upgraded.items():
            _set(expect, path, want)
        if after != expect or duplicate_top_keys(text):
            config_ok = False
    except yaml.YAMLError:
        config_ok = False
    if not config_ok:
        warnings.append(f"설정 파일을 자동으로 보충하지 못했습니다(형식이 예상과 다름 — 흐름 표기 등) — 다음 키를 직접 고치세요: "
                        f"{', '.join(changed + ['.'.join(p) for p in upgraded])}")
        text, changed, upgraded = base_text, [], {}
        opt_auto["added"], ext_sup["added"], ext_sup["record"], ext_sup["records"] = {}, [], False, []
        doe["added"] = {}
    changed += [".".join(p) for p in upgraded]
    config_changed = new_file or bool(changed)

    # ---- 함께 두는 파일(코어·라이브러리·ISTA6): 설정이 같은 폴더의 상대 이름을 가리킬 때만, 없을 때만 복사 -----------------
    final = yaml.safe_load(text) or {}
    hint = opt_run_hint(final)
    if hint:
        if opt_auto["hw_exists"] and not opt_auto["candidate"] and not opt_auto["kept_disabled"]:
            hint += OPT_AUTODETECT_NONE
        if not opt_auto["kept_disabled"]:
            warnings.append(hint)
    cfg_dir = config_path.parent
    companions: list[dict[str, Any]] = []
    for path, default_name, example_name in COMPANIONS:
        has, rel = _get(final, path)
        if not has or not isinstance(rel, str) or not rel:
            continue
        target = Path(rel) if os.path.isabs(rel) or _WIN_ABS.match(rel) else cfg_dir / rel
        exists = target.is_file()
        relative = not (os.path.isabs(rel) or _WIN_ABS.match(rel))
        companions.append({"key": ".".join(path), "path": str(target), "source": str(src / "config" / example_name),
                           "exists": exists, "copy": (not exists) and relative})
        if path[0] == "library" and relative:
            ista_target = cfg_dir / ISTA6[0]
            companions.append({"key": "library.ista6", "path": str(ista_target), "source": str(src / "config" / ISTA6[1]),
                               "exists": ista_target.is_file(), "copy": not ista_target.is_file()})
        if not exists and not relative:
            warnings.append(f"{'.'.join(path)} 파일이 없습니다: {rel}")
    # ---- 대시보드 .env(Vite 프록시 연결 — git 폴더 설치만) -------------------------------------------------------
    dash_env = None
    if mode == "repo":
        port = ((final.get("server") or {}) if isinstance(final, dict) else {}).get("port") or 8110
        dash_env = plan_dashboard_env(str(deploy.get("dashboard_root") or ""), port)
        if dash_env:
            warnings += dash_env["warnings"]
    return {
        "dashboard_env": dash_env,
        "mode": mode, "deploy_path": str(deploy_path), "deploy_exists": existing is not None, "deploy": deploy,
        "deploy_write": deploy_write, "deploy_added": added if existing is not None else [], "deploy_overridden": overridden,
        "deploy_changed": deploy_changed, "config_path": str(config_path), "config_source": source,
        "config_changed": config_changed, "config_rows": rows, "config_changed_keys": changed, "config_text": text,
        "config_bom": config_bom,
        "companions": companions, "esl_root": esl_root, "esl_root_ok": root_ok, "input_roots": input_roots,
        "upload_root": upload_root, "upload_root_ok": upload_ok,
        "spdm_roots": spdm_roots, "warnings": warnings,
        "opt_autodetect": {"added": opt_auto["added"], "candidate": opt_auto["candidate"]},
        "ext_supplement": ext_sup,
        "doe_autodetect": doe,
    }


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------

def _backup(p: Path, runtime: Path, stamp: str, name: str = "") -> str:
    dest = runtime / "_backup" / stamp / (name or p.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    return str(dest)


def write(inputs: dict[str, Any], pl: dict[str, Any]) -> dict[str, Any]:
    runtime = Path(inputs["runtime_dir"])
    stamp = str(inputs.get("stamp") or "backup")
    out: dict[str, Any] = {"backups": [], "written": [], "created": []}
    for sub in ("config", "logs", "state"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)
    deploy_path = Path(pl["deploy_path"])
    if pl["deploy_write"] and pl["deploy_changed"]:
        if deploy_path.is_file():
            out["backups"].append(_backup(deploy_path, runtime, stamp))
        deploy_path.parent.mkdir(parents=True, exist_ok=True)
        deploy_path.write_text(json.dumps(pl["deploy"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out["written"].append(str(deploy_path))
    cfg = Path(pl["config_path"])
    cfg_backup = None
    if pl["config_changed"]:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        if cfg.is_file():
            cfg_backup = _backup(cfg, runtime, stamp)
            out["backups"].append(cfg_backup)
        with open(cfg, "w", encoding="utf-8-sig" if pl.get("config_bom") else "utf-8", newline="") as f:
            f.write(pl["config_text"])
        out["written"].append(str(cfg))
    oa = (pl.get("opt_autodetect") or {}).get("added") or {}
    out["opt_autodetect"] = {"added": oa, "backup": cfg_backup, "line": None}
    if oa:
        kv = ", ".join(f"{k} = {literal(v)}" for k, v in oa.items())
        out["opt_autodetect"]["line"] = (f"비드 최적화 자동 설정: {kv} 추가"
                                         + (f" (백업 {cfg_backup})" if cfg_backup else ""))
    es = pl.get("ext_supplement") or {}
    out["ext_supplement"] = {"added": list(es.get("added") or []), "line": None}
    if es.get("record"):
        sp = runtime.joinpath(*EXT_SUPPLEMENT_STATE)
        rec = read_ext_supplement(runtime)
        for ver, exts, _gate, _label in EXT_SUPPLEMENTS:
            if ver in (es.get("records") or [EXT_SUPPLEMENT_VERSION]):
                rec[ver] = list(exts)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        if es.get("added"):
            out["ext_supplement"]["line"] = (f"업로드 허용 확장자 보충: upload.allowed_ext 에 {' '.join(es['added'])} 추가"
                                             + (f" (백업 {cfg_backup})" if cfg_backup else ""))
    da = (pl.get("doe_autodetect") or {}).get("added") or {}
    out["doe_autodetect"] = {"added": da, "backup": cfg_backup, "line": None}
    if da:
        kv = ", ".join(f"{k} = {literal(v)}" for k, v in da.items())
        out["doe_autodetect"]["line"] = (f"강성 평가 스터디 자동 설정: {kv} 추가" + (f" (백업 {cfg_backup})" if cfg_backup else ""))
    for c in pl["companions"]:
        if c["copy"] and not os.path.exists(c["path"]):
            Path(c["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(c["source"], c["path"])
            out["written"].append(c["path"])
    de = pl.get("dashboard_env")
    out["dashboard_env"] = {"added": [], "backup": None}
    if de and de["exists"] and de["add"]:
        env = Path(de["path"])
        bk = _backup(env, runtime, stamp, "dashboard.env")
        out["backups"].append(bk)
        write_dashboard_env(str(env), de["add"])
        out["written"].append(str(env))
        out["dashboard_env"] = {"added": [ln.split("=", 1)[0] for ln in de["add"]], "backup": bk}
    root = pl["esl_root"]
    if root and pl["esl_root_ok"] and not os.path.isdir(root):
        Path(root).mkdir(parents=True, exist_ok=True)
        out["created"].append(root)
    up = pl.get("upload_root")
    if up and pl.get("upload_root_ok") and not os.path.isdir(up):
        Path(up).mkdir(parents=True, exist_ok=True)
        out["created"].append(up)
    out["validation"] = validate(str(cfg), inputs.get("code_root"))
    return out


def validate(config_path: str, code_root: str | None = None) -> dict[str, Any]:
    root = Path(code_root) if code_root else HERE.parent
    for p in (root / "worker", root / "backend", root):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from esl_platform.core.config import load_config
    except ImportError as exc:  # pragma: no cover - 설치 venv·코드에는 있음
        return {"ok": None, "issues": [f"(검증 생략: {exc})"], "warnings": []}
    lc = load_config(config_path, environ={})
    return {"ok": lc.ok, "issues": [f"{i.key}: {i.message}" for i in lc.issues], "warnings": []}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="setup_config.py")
    ap.add_argument("action", choices=("plan", "write"))
    ap.add_argument("--inputs", required=True, help="입력 JSON 파일(setup.ps1·install.ps1 이 만든다)")
    ap.add_argument("--out", default="", help="결과 JSON 파일(UTF-8). 비우면 표준 출력")
    args = ap.parse_args(argv)
    inputs = _read_json(Path(args.inputs)) or {}
    pl = plan(inputs)
    if args.action == "write":
        pl["write"] = write(inputs, pl)
    pl.pop("config_text", None)
    pl.pop("config_bom", None)
    data = json.dumps(pl, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(data, encoding="utf-8")  # PowerShell 5.1은 -Encoding UTF8로 읽는다
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
