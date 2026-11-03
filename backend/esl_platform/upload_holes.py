"""업로드 손상 탐지(이슈 #50, 읽기 전용): 업로드 루트 아래 파일에서 청크 정렬 경계(k·C, C = upload.chunk_mb)부터 0 이
이어지는 구간을 찾아 보고하고, 업로드 DB 기록에 sha256 이 있으면 파일 전체를 다시 해시해 대조한다.

v0.12.4 전 프로토콜 2 업로드는 `.part` 사전 할당(Windows os.ftruncate = 0 을 써서 채움)과 다른 청크 쓰기가 겹치면, 늦게
지나가는 0 채우기가 이미 쓴 청크의 **앞부분**을 덮어썼다(k·C 부터 0). 그래서 경계에서 시작하는 0 구간을 본다:
청크 전체가 0 이면 `full`, 앞부분만이면 `head`(길이 ≥ --min-zero-kb). 텍스트 입력(.rad·.inc·.sta·.str)에는 NUL 이
없으므로 `head` 하나도 손상으로 보면 된다. 바이너리(.h3d)는 드물게 정상 0 패딩일 수 있어 sha256·원본과 비교해 확인한다.

쓰기·삭제·이동 없음(파일은 'rb' 로만 열고 DB 는 READ ONLY 트랜잭션의 SELECT 만). 심링크·junction 은 따라가지 않는다.
`_backup` 아래와 받는 중인 `.part` 는 기본 제외(--include-backup·--include-part).

  python -m esl_platform.upload_holes --runtime <런타임>                 (설치본: esl_service.py upload-holes --runtime <런타임>)
  python -m esl_platform.upload_holes --root D:\\esl-input --chunk-mb 64 --no-db
반환 코드: 0 = 의심 없음, 1 = 의심 있음(또는 sha256 불일치), 2 = 인자·설정 오류.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator

BACKUP_DIR = "_backup"
PART_SUFFIX = ".part"
_READ = 1 << 20


@dataclass
class Hole:
    chunk: int
    offset: int
    zero_bytes: int
    kind: str                          # full | head


@dataclass
class FileReport:
    path: str
    size: int
    holes: list[Hole] = field(default_factory=list)
    upload_id: str | None = None
    upload_state: str | None = None
    sha256_recorded: str | None = None
    sha256_actual: str | None = None
    sha256_ok: bool | None = None
    error: str | None = None

    @property
    def suspect(self) -> bool:
        return bool(self.holes) or self.sha256_ok is False or self.error is not None


def _is_link_like(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def iter_files(root: str, *, include_backup: bool = False, include_part: bool = False) -> Iterator[str]:
    """root 아래 일반 파일(링크·junction 은 건너뜀, 따라가지 않음). 이름순."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for d in sorted(dirnames):
            if not include_backup and dirpath == root and d == BACKUP_DIR:
                continue
            if _is_link_like(os.path.join(dirpath, d)):
                continue
            keep.append(d)
        dirnames[:] = keep
        for n in sorted(filenames):
            if not include_part and n.endswith(PART_SUFFIX):
                continue
            p = os.path.join(dirpath, n)
            if _is_link_like(p):
                continue
            try:
                if stat.S_ISREG(os.lstat(p).st_mode):
                    yield p
            except OSError:
                continue


def _zero_run(fh, offset: int, limit: int) -> int:
    """offset 부터 0 이 이어지는 길이(최대 limit)."""
    fh.seek(offset)
    n = 0
    while n < limit:
        b = fh.read(min(_READ, limit - n))
        if not b:
            break
        s = b.lstrip(b"\x00")
        if s:
            return n + (len(b) - len(s))
        n += len(b)
    return n


def scan_file(path: str, chunk: int, *, min_zero: int, want_sha: bool) -> FileReport:
    size = os.path.getsize(path)
    rep = FileReport(path=path, size=size)
    try:
        with open(path, "rb") as fh:
            for k in range((size + chunk - 1) // chunk if size else 0):
                off = k * chunk
                ln = min(chunk, size - off)
                z = _zero_run(fh, off, ln)
                if z >= ln:
                    rep.holes.append(Hole(k, off, z, "full"))
                elif z >= min_zero:
                    rep.holes.append(Hole(k, off, z, "head"))
            if want_sha:
                fh.seek(0)
                h = hashlib.sha256()
                while True:
                    b = fh.read(_READ)
                    if not b:
                        break
                    h.update(b)
                rep.sha256_actual = h.hexdigest()
    except OSError as exc:
        rep.error = f"{exc.__class__.__name__}: {exc}"
    return rep


def _key(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def db_records(url: str) -> dict[str, dict[str, Any]]:
    """업로드 기록: 파일 절대경로(normcase) → {upload_id, state, sha256}. done·뺀 파일 아님만. READ ONLY 트랜잭션."""
    from sqlalchemy import create_engine, text

    from esl_platform.core.db.engine import normalize_url

    eng = create_engine(normalize_url(url), pool_pre_ping=True)
    out: dict[str, dict[str, Any]] = {}
    try:
        with eng.connect() as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                rows = conn.execute(text("SELECT id, state, dir_path, files FROM uploads")).mappings().all()
    finally:
        eng.dispose()
    for r in rows:
        for f in r["files"] or []:
            if not isinstance(f, dict) or f.get("removed") or not f.get("done") or not f.get("rel"):
                continue
            p = os.path.join(r["dir_path"], *str(f["rel"]).split("/"))
            out[_key(p)] = {"upload_id": r["id"], "state": r["state"], "sha256": f.get("sha256")}
    return out


def run(root: str, chunk: int, *, min_zero: int, records: dict[str, dict[str, Any]] | None, check_sha: bool = True,
        include_backup: bool = False, include_part: bool = False) -> list[FileReport]:
    reps = []
    for p in iter_files(root, include_backup=include_backup, include_part=include_part):
        rec = (records or {}).get(_key(p))
        want = bool(check_sha and rec and rec.get("sha256"))
        rep = scan_file(p, chunk, min_zero=min_zero, want_sha=want)
        if rec:
            rep.upload_id, rep.upload_state, rep.sha256_recorded = rec["upload_id"], rec["state"], rec.get("sha256")
            if want and rep.sha256_actual is not None:
                rep.sha256_ok = rep.sha256_actual == str(rec["sha256"]).lower()
        reps.append(rep)
    return reps


def _fmt_bytes(n: int) -> str:
    for unit, d in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if n >= d:
            return f"{n / d:.1f} {unit}"
    return f"{n} B"


def format_report(reps: list[FileReport], root: str, chunk: int) -> str:
    bad = [r for r in reps if r.suspect]
    lines = [f"업로드 손상 탐지(읽기 전용): {root} — 파일 {len(reps)}개, 청크 {_fmt_bytes(chunk)} 정렬"]
    for r in bad:
        rel = os.path.relpath(r.path, root)
        who = f" [업로드 {r.upload_id} {r.upload_state}]" if r.upload_id else ""
        lines.append(f"! {rel} ({r.size:,} B){who}")
        for h in r.holes:
            lines.append(f"    청크 {h.chunk} @ {h.offset:,}: 0 이 {h.zero_bytes:,} B ({_fmt_bytes(h.zero_bytes)})"
                         + (" — 청크 전체" if h.kind == "full" else " — 청크 앞부분"))
        if r.sha256_ok is False:
            lines.append(f"    sha256 불일치: 기록 {r.sha256_recorded} / 실제 {r.sha256_actual}")
        if r.error:
            lines.append(f"    읽기 오류: {r.error}")
    n_sha = sum(1 for r in reps if r.sha256_ok is not None)
    lines.append(f"의심 {len(bad)}개" + (f", sha256 대조 {n_sha}개" if n_sha else "")
                 + (" — 의심 파일은 원본으로 다시 올리세요(손상 파일로 만든 Case 는 다시 만들기)" if bad else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, out: Callable[[str], None] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m esl_platform.upload_holes", description="업로드 손상(청크 경계 0 구간) 탐지 — 읽기 전용")
    ap.add_argument("--runtime", default="", help="설치 런타임 폴더(<런타임>/config/esl_platform.yaml, secrets/database_url)")
    ap.add_argument("--config", default="", help="플랫폼 설정 파일(기본: --runtime 또는 env ESL_PLATFORM_CONFIG)")
    ap.add_argument("--root", default="", help="훑을 폴더(기본: 설정 storage.upload_root)")
    ap.add_argument("--chunk-mb", type=int, default=0, help="청크 크기 MB(기본: 설정 upload.chunk_mb, 없으면 64)")
    ap.add_argument("--min-zero-kb", type=int, default=64, help="청크 앞부분 0 구간 보고 기준(KiB, 기본 64)")
    ap.add_argument("--no-db", action="store_true", help="업로드 DB 기록(sha256) 대조 생략")
    ap.add_argument("--no-sha", action="store_true", help="sha256 재계산 생략(0 구간만 — 빠름)")
    ap.add_argument("--include-backup", action="store_true", help="_backup 아래도 훑기")
    ap.add_argument("--include-part", action="store_true", help="받는 중인 .part 도 훑기(받지 않은 청크는 원래 0)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
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
    from esl_platform.check import read_runtime_db_url, resolve_config_path

    runtime = os.path.abspath(args.runtime) if args.runtime else None
    cfg = resolve_config_path(args.config or None, runtime, dict(os.environ))
    s = None
    if cfg:
        from esl_platform.core.config import load_config

        lc = load_config(cfg)
        s = lc.settings
        if s is None:
            write(f"설정 오류: {cfg}: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
            return 2
    root = args.root or (s.storage.upload_root if s is not None else "")
    if not root:
        write("훑을 폴더가 없습니다(--root 또는 설정 storage.upload_root)")
        return 2
    if not os.path.isdir(root):
        write(f"폴더가 없습니다: {root}")
        return 2
    chunk = (args.chunk_mb or (s.upload.chunk_mb if s is not None else 64)) * 1024 * 1024
    records = None
    if not args.no_db:
        url = (os.environ.get(s.database.url_env) if s is not None else "") or read_runtime_db_url(runtime)
        if not url:
            write("DB 접속 정보가 없어 sha256 대조를 건너뜁니다(--no-db 로 이 안내를 끔)")
        else:
            try:
                records = db_records(url)
            except Exception as exc:  # noqa: BLE001
                write(f"DB 읽기 실패({exc.__class__.__name__}) — sha256 대조를 건너뜁니다")
    reps = run(os.path.abspath(root), chunk, min_zero=max(1, args.min_zero_kb) * 1024, records=records,
               check_sha=not args.no_sha, include_backup=args.include_backup, include_part=args.include_part)
    if args.json:
        write(json.dumps({"root": os.path.abspath(root), "chunk_bytes": chunk, "files": len(reps),
                          "suspects": [{**asdict(r), "holes": [asdict(h) for h in r.holes]} for r in reps if r.suspect]},
                         ensure_ascii=False))
    else:
        write(format_report(reps, os.path.abspath(root), chunk))
    return 1 if any(r.suspect for r in reps) else 0


if __name__ == "__main__":
    sys.exit(main())
