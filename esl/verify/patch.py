"""노드 ID 기준 ``/NODE`` 좌표 패치(계약 esl_scx_relay.md SR-D-13, V-SR-16).

원 Case 입력 세트(starter rad + include 폐포 + 엔진 rad)의 모든 파일에서 ``/NODE`` 블록 안 노드 줄 중 ``coords`` 에 있는 ID 의
좌표 필드만 고쳐 쓴다. 대상 파트(Ch/R) 노드가 어느 include 에 있든 같은 형상이 된다.

- **원본은 읽기만**: 바뀐 파일만 ``out_dir/<rel>`` 에 새로 쓴다(나머지는 원본 경로 그대로 — 호출자가 원본을 올림).
- **바뀐 줄만**: 좌표 값이 이미 같은 줄(그 노드가 모핑에서 움직이지 않음)은 바이트 그대로. ID 필드·다른 줄·다른 카드·줄바꿈
  (``\\r\\n``/``\\n``)·주석은 불변.
- 형식: 고정폭 I10 + F20×3(Radioss) — ID 필드(앞 10자)와 70자 뒤 나머지는 그대로, 좌표 3칸만 ``%20.13E``.
  쉼표가 있으면 자유 형식(같은 구분자, ``%.13E``), 고정폭 해석이 안 되는 공백 구분 줄(``id x y z``)은 같은 공백 구분 형식.
  해석 규칙 = ``esl.doe.nodes``(줄 길이 상한 ``bounded_readline``, ``#``·``$`` 주석, 다음 ``/`` 키워드에서 블록 끝).
- 반환 ``{files[{rel, path, source orig|patched, n_patched, size, sha256}], n_patched, found, missing[]}``.
  ``required`` 의 노드가 세트에 하나라도 없으면 ``VD_NODES_MISSING``(개수·상위 10) — 쓰기 전에 판정(부분 산출물 없음).
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable

from esl.errors import EslError
from esl.rad.parser import _decode, _f, _i, bounded_readline

FIX_FMT = "%20.13E"
FREE_FMT = "%.13E"


def _is_node_header(raw: bytes) -> bool | None:
    """'/' 키워드 줄이면 /NODE 여부, 아니면 None."""
    if raw[:1] != b"/":
        return None
    toks = raw[1:].split(b"/")[0].split()
    return bool(toks) and toks[0].upper() == b"NODE"


def _parse(line: str) -> tuple[str, int, list[float]] | None:
    """노드 줄 → (형식 fixed|comma|space, id, xyz). 해석 불가 → None(그 줄은 건드리지 않음)."""
    try:
        if "," in line:
            f = [x.strip() for x in line.split(",")]
            nid = _i(f[0])
            xyz = [(_f(f[k]) or 0.0) if k < len(f) else 0.0 for k in (1, 2, 3)]
            return ("comma", nid, xyz) if nid is not None else None
        nid = _i(line[0:10])
        xyz = [_f(line[10:30]) or 0.0, _f(line[30:50]) or 0.0, _f(line[50:70]) or 0.0]
        return ("fixed", nid, xyz) if nid is not None else None
    except ValueError:
        pass
    toks = line.split()
    if len(toks) == 4:
        try:
            nid = _i(toks[0])
            xyz = [float(_f(t) or 0.0) for t in toks[1:]]
            return ("space", nid, xyz) if nid is not None else None
        except ValueError:
            return None
    return None


def _fix(v: float) -> str:
    s = FIX_FMT % v
    return s if len(s) == 20 else ("%20.12E" % v)[:20]


def _rewrite(line: str, kind: str, xyz) -> str:
    if kind == "fixed":
        return line[:10].ljust(10) + "".join(_fix(float(v)) for v in xyz) + line[70:]
    if kind == "comma":
        f = line.split(",")
        while len(f) < 4:
            f.append("")
        for k in range(3):
            f[k + 1] = FREE_FMT % float(xyz[k])
        return ",".join(f)
    lead = line[: len(line) - len(line.lstrip())]
    return lead + " ".join([line.split()[0], *(FREE_FMT % float(v) for v in xyz)])


def _eol(raw: bytes) -> tuple[bytes, bytes]:
    if raw.endswith(b"\r\n"):
        return raw[:-2], b"\r\n"
    if raw.endswith(b"\n"):
        return raw[:-1], b"\n"
    return raw, b""


def _scan(path: str, want: dict[int, tuple], max_line: int | None):
    """1차 읽기: (sha256, size, 찾은 ID 집합, 바뀌어야 할 줄 수)."""
    h = hashlib.sha256()
    size = 0
    found: set[int] = set()
    change = 0
    in_node = False
    with open(path, "rb") as fh:
        readline = bounded_readline(fh, path, max_line)
        while True:
            raw = readline()
            if not raw:
                break
            h.update(raw)
            size += len(raw)
            if raw[:1] in (b"#", b"$"):
                continue
            hd = _is_node_header(raw)
            if hd is not None:
                in_node = hd
                continue
            if not in_node:
                continue
            body, _ = _eol(raw)
            if not body.strip():
                continue
            p = _parse(_decode(body))
            if p is None or p[1] not in want:
                continue
            found.add(p[1])
            if [float(x) for x in p[2]] != [float(x) for x in want[p[1]]]:
                change += 1
    return h.hexdigest(), size, found, change


def _write(src: str, dst: str, want: dict[int, tuple], max_line: int | None) -> tuple[str, int, int]:
    h = hashlib.sha256()
    size = 0
    n = 0
    in_node = False
    tmp = dst + ".vdtmp"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        readline = bounded_readline(fi, src, max_line)
        while True:
            raw = readline()
            if not raw:
                break
            out = raw
            if raw[:1] not in (b"#", b"$"):
                hd = _is_node_header(raw)
                if hd is not None:
                    in_node = hd
                elif in_node:
                    body, eol = _eol(raw)
                    if body.strip():
                        line = _decode(body)
                        p = _parse(line)
                        if p is not None and p[1] in want and [float(x) for x in p[2]] != [float(x) for x in want[p[1]]]:
                            out = _rewrite(line, p[0], want[p[1]]).encode("ascii") + eol
                            n += 1
            fo.write(out)
            h.update(out)
            size += len(out)
    os.replace(tmp, dst)
    return h.hexdigest(), size, n


def patch_node_files(files: Iterable[tuple[str, str]], coords: dict[int, tuple], out_dir: str, *,
                     required: Iterable[int] | None = None, max_line: int | None = None,
                     guard: Callable[[str], str] | None = None) -> dict:
    """files = [(rel, 원본 절대경로)], coords = {node_id: (x, y, z)}(모핑 좌표). 바뀐 파일만 out_dir/<rel> 에 쓴다."""
    want = {int(k): tuple(float(x) for x in v) for k, v in coords.items()}
    req = set(int(x) for x in (required if required is not None else want))
    items = list(files)
    scans = []
    found: set[int] = set()
    for rel, path in items:
        if not os.path.isfile(path):
            raise EslError("INPUT_INVALID", f"검증 낙하 입력 파일이 없음: {rel}")
        sha, size, f, change = _scan(path, want, max_line)
        found |= f
        scans.append((rel, path, sha, size, change))
    missing = sorted(req - found)
    if missing:
        raise EslError("VD_NODES_MISSING", f"원 Case 입력 세트에서 대상 파트 노드 {len(missing)}개를 찾지 못함"
                                           f"(상위 10: {missing[:10]})")
    out_root = os.path.realpath(out_dir)
    res = []
    total = 0
    for rel, path, sha, size, change in scans:
        if not change:
            res.append({"rel": rel, "path": path, "source": "orig", "n_patched": 0, "size": size, "sha256": sha})
            continue
        dst = os.path.join(out_dir, *rel.split("/"))
        if guard is not None:
            dst = guard(dst)
        rp = os.path.realpath(os.path.dirname(dst))
        if not (rp == out_root or rp.startswith(out_root + os.sep)):
            raise EslError("PATH_OUTSIDE_ROOT", f"패치 출력 경로가 출력 폴더 밖: {rel}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        psha, psize, n = _write(path, dst, want, max_line)
        total += n
        res.append({"rel": rel, "path": dst, "source": "patched", "n_patched": n, "size": psize, "sha256": psha})
    return {"files": res, "n_patched": total, "found": len(found), "missing": []}


__all__ = ["patch_node_files", "FIX_FMT"]
