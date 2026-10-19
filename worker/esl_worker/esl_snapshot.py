"""ESL 실행별 산출물 스냅샷(runs/<esl_run_id>/{03_bc,04_esl}) 저장·복원.

설계: 코어 출력 폴더 스키마(01_extract~06_export)는 그대로 두고, ESL_SOLVE 등록 시 그 실행의 03_bc·04_esl 을
`runs/<esl_run_id>/` 로 **복사**해 보존한다(하드링크는 사용자가 04_esl 파일을 제자리 편집하면 스냅샷도 바뀌므로
쓰지 않음; 용량은 실행당 03_bc+04_esl 크기 — 노드 수에 비례, 프레임 수와 무관).
검증·내보내기 직전에 디스크 04_esl 의 tag(= ESL_SOLVE 작업 id)가 대상 실행과 다르면 스냅샷에서 되돌린다
(현재 03_bc·04_esl 은 `_backup/<ts>/` 로 이동, 삭제 없음).
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
from typing import Any

from esl_platform.core import core_outputs as co


def _copy_tree(src: str, dst: str) -> None:
    if os.path.islink(src) or not os.path.isdir(src):
        raise FileNotFoundError(src)
    shutil.copytree(src, dst, symlinks=True, copy_function=shutil.copy2,
                    ignore=lambda d, names: [n for n in names if os.path.islink(os.path.join(d, n))])


def _inside(cdir: str, path: str) -> str:
    real_c = os.path.realpath(cdir)
    real_p = os.path.realpath(path)
    if os.path.commonpath([real_c, real_p]) != real_c:
        raise OSError(f"Case 폴더 밖 경로: {path}")
    return path


def save(cdir: str, run_id: str) -> str:
    """현재 03_bc·04_esl → runs/<run_id>/ (이미 있으면 그대로). 반환: 스냅샷 상대경로."""
    snap = _inside(cdir, co.run_snapshot_dir(cdir, run_id))
    if not os.path.isdir(snap):
        tmp = snap + ".tmp"
        if os.path.lexists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        for sub in co.SNAPSHOT_DIRS:
            _copy_tree(_inside(cdir, os.path.join(cdir, sub)), os.path.join(tmp, sub))
        os.replace(tmp, snap)
    return f"{co.RUNS_DIR}/{run_id}"


def ensure_on_disk(cdir: str, run: dict[str, Any]) -> str:
    """디스크 03_bc·04_esl 을 ESL 실행 run 의 것으로 맞춘다.

    반환: "current"(이미 같음) | "restored"(스냅샷에서 되돌림) | "legacy"(tag 기록 이전 실행·스냅샷 없음 → 그대로).
    맞출 수 없으면 LookupError.
    """
    want = run["job_id"]
    disk = co.esl_tag(cdir)
    if disk == want:
        return "current"
    snap = co.run_snapshot_dir(cdir, run["id"])
    if co.esl_tag(snap) != want:
        if disk is None and not os.path.isdir(snap) and os.path.isfile(os.path.join(cdir, co.D_ESL, "f_eq.npz")):
            return "legacy"
        raise LookupError(f"ESL 결과 {run['id']} 의 산출물이 디스크에 없습니다(04_esl tag={disk})")
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    bdir = _inside(cdir, os.path.join(cdir, "_backup", ts))
    for sub in co.SNAPSHOT_DIRS:
        cur = _inside(cdir, os.path.join(cdir, sub))
        if os.path.lexists(cur):
            os.makedirs(bdir, exist_ok=True)
            os.replace(cur, os.path.join(bdir, sub))
        _copy_tree(os.path.join(snap, sub), cur)
    if co.esl_tag(cdir) != want:  # pragma: no cover - 방어
        raise LookupError("스냅샷 복원 후에도 04_esl tag 가 다릅니다")
    return "restored"
