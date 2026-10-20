"""버전 표기·업데이트 내역(계약 esl_p3_ux.md §3).

원천: 코드 루트(저장소 또는 설치 스냅샷 `<런타임>/app`)의 `BUILD.json`{version, commit, built_at}(배포 시 기록) →
없으면 `VERSION` 파일 + git 짧은 해시(.git 파일을 직접 읽음 — 외부 프로그램 실행 없음).
`CHANGELOG.md`: `## [x.y.z] - YYYY-MM-DD` + `### 추가|변경|수정` + `- 항목`(최신이 위).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[4]     # .../backend/esl_platform/api/services → 코드 루트
SECTIONS = ("추가", "변경", "수정")
_VER_H = re.compile(r"^##\s+\[(?P<v>[^\]]+)\](?:\s*-\s*(?P<d>\d{4}-\d{2}-\d{2}))?\s*$")
_SEC_H = re.compile(r"^###\s+(?P<s>.+?)\s*$")
_ITEM = re.compile(r"^\s*[-*]\s+(?P<t>.+?)\s*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8-sig")
    except OSError:
        return None


def git_commit(root: Path) -> str | None:
    """.git/HEAD → ref 파일 또는 packed-refs 에서 커밋 해시(짧게 7자). 없으면 None."""
    g = root / ".git"
    if g.is_file():                           # worktree: "gitdir: <경로>"
        t = _read(g) or ""
        if t.startswith("gitdir:"):
            g = (root / t.split(":", 1)[1].strip()).resolve()
    head = _read(g / "HEAD")
    if not head:
        return None
    head = head.strip()
    sha = None
    if head.startswith("ref:"):
        ref = head[4:].strip()
        sha = (_read(g / ref) or "").strip() or None
        if sha is None:
            common = _read(g / "commondir")
            gc = (g / common.strip()).resolve() if common else g
            sha = (_read(gc / ref) or "").strip() or None
            for line in (_read(gc / "packed-refs") or "").splitlines():
                parts = line.split()
                if sha is None and len(parts) == 2 and parts[1] == ref:
                    sha = parts[0]
    else:
        sha = head
    return sha[:7] if sha and re.fullmatch(r"[0-9a-f]{7,64}", sha) else None


def build_info(root: Path = CODE_ROOT) -> dict[str, Any]:
    b = _read(root / "BUILD.json")
    if b:
        try:
            d = json.loads(b)
            if isinstance(d, dict) and d.get("version"):
                return {"version": str(d["version"]), "commit": d.get("commit") or None,
                        "built_at": d.get("built_at") or None}
        except ValueError:
            pass
    ver = (_read(root / "VERSION") or "").strip() or "0.0.0"
    return {"version": ver, "commit": git_commit(root), "built_at": None}


def parse_changelog(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    sec: str | None = None
    for line in text.splitlines():
        m = _VER_H.match(line)
        if m:
            cur = {"version": m.group("v").strip(), "date": m.group("d"), "sections": {s: [] for s in SECTIONS}}
            out.append(cur)
            sec = None
            continue
        if line.startswith("## "):
            cur, sec = None, None
            continue
        if cur is None:
            continue
        m = _SEC_H.match(line)
        if m:
            sec = m.group("s")
            cur["sections"].setdefault(sec, [])
            continue
        m = _ITEM.match(line)
        if m and sec:
            cur["sections"][sec].append(m.group("t"))
    return out


def changelog(root: Path = CODE_ROOT) -> list[dict[str, Any]]:
    return parse_changelog(_read(root / "CHANGELOG.md") or "")
