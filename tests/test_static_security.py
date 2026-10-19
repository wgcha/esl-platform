"""T-SEC-1: esl/ 아래 pickle, allow_pickle=True, shell=True, os.system, 드라이브 문자 절대경로 리터럴 0건."""
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
