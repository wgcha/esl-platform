"""T-SEC-1: esl/ 아래 pickle, allow_pickle=True, shell=True, os.system, 드라이브 문자·POSIX 절대경로 리터럴 0건.

resources/tcl/*.tcl 도 드라이브 문자 절대경로 리터럴 0건(주석 행·README 제외).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "esl")

PATTERNS = {
    "pickle": re.compile(r"\bpickle\b|\bcPickle\b|\bdill\b"),
    "allow_pickle=True": re.compile(r"allow_pickle\s*=\s*True"),
    "shell=True": re.compile(r"shell\s*=\s*True"),
    "os.system": re.compile(r"\bos\s*\.\s*system\b|\bos\s*\.\s*popen\b"),
    # 문자열 리터럴 안의 드라이브 문자 절대경로 (C:\ , D:/ ...)
    "drive_abs_path": re.compile(r"""["'][A-Za-z]:[\\/]"""),
    # 문자열 리터럴 안의 POSIX 절대경로 (사용자·임시·데이터 마운트)
    "posix_abs_path": re.compile(r"""["'](/home/|/tmp/|/data\b|/mnt\b|/root/|/Users/)"""),
    "unc_path": re.compile(r"""["']\\\\\\\\[A-Za-z0-9]"""),
    "program_files": re.compile(r"Program Files", re.I),
}


def _py_files():
    for base, _, files in os.walk(PKG):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_no_forbidden_patterns():
    files = list(_py_files())
    assert len(files) >= 10
    hits = []
    for p in files:
        for no, line in enumerate(open(p, encoding="utf-8"), start=1):
            for name, rx in PATTERNS.items():
                if rx.search(line):
                    hits.append(f"{os.path.relpath(p, ROOT)}:{no}: {name}: {line.strip()}")
    assert hits == [], "\n".join(hits)


TCL_DIR = os.path.join(ROOT, "resources", "tcl")
# TCL 은 따옴표·중괄호·맨 단어 모두 리터럴이 될 수 있으므로 단어 경계 기준 (C:\ , D:/ ...)
TCL_DRIVE = re.compile(r"""(?<![A-Za-z0-9_$:])[A-Za-z]:[\\/]""")
TCL_POSIX = re.compile(r"""["{\s](/home/|/tmp/|/data\b|/mnt\b|/root/)""")


def _tcl_files():
    if not os.path.isdir(TCL_DIR):
        return []
    return [os.path.join(TCL_DIR, f) for f in sorted(os.listdir(TCL_DIR)) if f.lower().endswith(".tcl")]


def test_tcl_no_absolute_path_literals():
    files = _tcl_files()
    assert files, "resources/tcl/*.tcl 없음"
    hits = []
    for p in files:
        for no, line in enumerate(open(p, encoding="utf-8", errors="replace"), start=1):
            if line.lstrip().startswith("#"):            # 주석 행 제외
                continue
            for name, rx in (("drive_abs_path", TCL_DRIVE), ("posix_abs_path", TCL_POSIX)):
                if rx.search(line):
                    hits.append(f"{os.path.relpath(p, ROOT)}:{no}: {name}: {line.strip()}")
    assert hits == [], "\n".join(hits)


def test_patterns_self_check():
    """검사 정규식이 실제로 잡는지(오탐·미탐 방지)."""
    rx = PATTERNS["posix_abs_path"]
    assert rx.search('p = "/home/user/x"') and rx.search("'/tmp/a'") and rx.search('"/data"')
    assert rx.search('"/mnt/share"') and not rx.search('"a/home/b"') and not rx.search('"/database"')
    assert PATTERNS["drive_abs_path"].search('"C:\\x"') and PATTERNS["drive_abs_path"].search("'d:/x'")
    assert TCL_DRIVE.search('set p "C:/esl"') and TCL_DRIVE.search("set p {D:\\run}")
    assert TCL_DRIVE.search("open D:/x r") and not TCL_DRIVE.search("namespace eval ::esl::a {}")
    assert not TCL_DRIVE.search("set v $a:/b") and TCL_POSIX.search('set p "/tmp/x"')


def test_npz_loads_explicit_no_pickle():
    """np.load 호출은 모두 allow_pickle=False 를 명시."""
    bad = []
    for p in _py_files():
        for no, line in enumerate(open(p, encoding="utf-8"), start=1):
            if re.search(r"\bnp\.load\(", line) and "allow_pickle=False" not in line:
                bad.append(f"{os.path.relpath(p, ROOT)}:{no}: {line.strip()}")
    assert bad == [], "\n".join(bad)


def test_no_subprocess_in_core():
    """P1a 코어에는 외부 실행 자체가 없음."""
    bad = [p for p in _py_files() if re.search(r"^\s*(import|from)\s+subprocess\b", open(p, encoding="utf-8").read(), re.M)]
    assert bad == []
