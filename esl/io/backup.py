"""Case 폴더 백업 규칙 공용(계약 esl_bforce_ondemand.md §4.4, D-0.24.2-BFD-5) — 정보 삭제 없이 `<Case>/_backup/<UTC ts>/…`.

pipeline(`Context.fresh_dir`·`backup_file`)과 경계력 보충 병합(`esl.io.bforce_ondemand`)이 같은 폴더 이름·시각 형식·
이름 충돌 규칙(`name`, `name.1`, …)을 쓴다. 이 모듈은 설정을 해석하지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil

from esl.fsutil import atomic_replace

BACKUP_DIR = "_backup"
BACKUP_TS_FMT = "%Y%m%dT%H%M%S_%fZ"          # 예 20261119T055012_123456Z (UTC)


def utc_stamp(now: _dt.datetime | None = None) -> str:
    """백업 폴더 이름(UTC, BACKUP_TS_FMT)."""
    return (now or _dt.datetime.now(_dt.timezone.utc)).strftime(BACKUP_TS_FMT)


def free_target(root: str, name: str) -> str:
    """root/name — 이미 있으면 root/name.1, name.2 … (덮어쓰지 않음)."""
    dst = os.path.join(root, name)
    k = 1
    while os.path.lexists(dst):
        dst = os.path.join(root, f"{name}.{k}")
        k += 1
    return dst


def replace(src: str, dst: str) -> None:
    """os.replace(src, dst) — Windows 잠금은 재시도(esl.fsutil.atomic_replace)."""
    atomic_replace(src, dst)


def keep_copy(src: str, dst_dir: str) -> str:
    """src 파일의 사본을 dst_dir 에 남긴다(하드 링크 우선, 안 되면 복사 — 원본은 그대로). 반환 = 사본 경로.

    교체 직전에 부르고 원본 자리는 tmp → replace 로 바꾸면, 원래 자리에는 늘 완전한 파일 하나가 있고(중간 실패에도
    옛 파일 그대로) 이전 내용은 백업 폴더에 남는다(이동과 같은 결과)."""
    os.makedirs(dst_dir, exist_ok=True)
    dst = free_target(dst_dir, os.path.basename(src))
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst
