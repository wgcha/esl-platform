"""v0.10.0 MR5 배포(계약 esl_menu_restructure.md §13): 새 런타임 파일이 코드 스냅샷 수집 목록에 들어가는지.

- install-common.ps1 $EslAppItems(설치·업데이트 app 복사), collect-offline.sh·collect-offline.ps1(폐쇄망 묶음 app/) 세 곳이
  같은 상위 항목을 복사해야 하고, v0.10.0 새 파일(esl/export/from_entry.py — 라이브러리 내보내기 코어 어댑터,
  backend/esl_platform/api/services/library_export.py)은 그 상위 폴더 아래에 있어야 한다.
- 코드가 여는 resources/ 파일은 모두 세 목록에 있어야 한다(v0.7.0 opt_method_sources.json 누락 재발 방지).
"""

from __future__ import annotations

import re

from conftest import ROOT

NEW_RUNTIME_FILES = (
    "esl/export/from_entry.py",
    "esl/mech/supports.py",
    "backend/esl_platform/api/services/library_export.py",
    "worker/esl_worker/register.py",
)


def _app_items() -> list[str]:
    common = (ROOT / "deploy" / "install-common.ps1").read_text(encoding="utf-8-sig")
    items = re.search(r"\$EslAppItems = @\(([^)]*)\)", common).group(1)
    return re.findall(r"'([^']+)'", items)


def _covered(rel: str, items: list[str]) -> bool:
    return any(rel == it or rel.startswith(it.rstrip("/") + "/") for it in items)


def test_new_runtime_files_in_app_items():
    items = _app_items()
    for rel in NEW_RUNTIME_FILES:
        assert (ROOT / rel).is_file(), rel
        assert _covered(rel, items), f"{rel} 이 $EslAppItems 로 복사되지 않음"


def test_collect_offline_copies_same_top_items():
    sh = (ROOT / "deploy" / "collect-offline.sh").read_text(encoding="utf-8")
    ps = (ROOT / "deploy" / "collect-offline.ps1").read_text(encoding="utf-8-sig")
    for it in _app_items():
        if it in ("alembic.ini", "pyproject.toml", "VERSION", "CHANGELOG.md"):
            assert it in sh and f"'{it}'" in ps, it
            continue
        assert it in sh, f"collect-offline.sh 에 {it} 없음"
        assert "'" + it.replace("/", "\\") + "'" in ps, f"collect-offline.ps1 에 {it} 없음"


def test_resources_used_by_code_are_collected():
    items = _app_items()
    used: set[str] = set()
    for base in ("esl", "backend/esl_platform", "worker/esl_worker"):
        for p in (ROOT / base).rglob("*.py"):
            for m in re.finditer(r"""["']((?:doe|opt)_[a-z_]+\.json)["']""", p.read_text(encoding="utf-8")):
                if (ROOT / "resources" / m.group(1)).is_file():
                    used.add("resources/" + m.group(1))
    assert "resources/doe_messages.json" in used
    for rel in sorted(used):
        assert _covered(rel, items), f"{rel} 이 $EslAppItems 에 없음"


def test_version_is_0_12_1():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.12.1"
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.12.1]" in log and "## [0.12.0]" in log and "## [0.11.0]" in log and "## [0.10.1]" in log and "## [0.10.0]" in log
