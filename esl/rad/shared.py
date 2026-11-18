"""공유 노드 · 회전 연결 노드 진단 (계약 docs/contracts/esl_fint.md §2, D-0.24.0-BF-14).

원 Case deck(주 파일 + include)에서 대상 파트 노드 중 **다른 부품 요소가 참조하는 노드**(공유 노드 — 노드 내력 FINT 에 다른
부품 요소 힘이 섞이는 노드)와 **회전 연결 노드**(SPRING·BEAM·RIVET 요소 노드, /RBODY 주 노드·/GRNOD/NODE 종속 노드 — 노드
모멘트가 크게 남을 수 있는 노드)를 찾는다. 표시용 진단 — 계산은 바꾸지 않는다. /INTER/TYPE2 tie 는 노드가 분리돼 해당 없음.

읽기만, 파서 ``_Deck.scan``(요소 블록 위치) 재사용. esl.doe import 없음.
"""
from __future__ import annotations

import os
import re

import numpy as np

from esl.errors import EslError
from esl.rad import parser as rp

# 키워드 → (id 뒤 노드 칸 수, 여러 줄 카드, 회전 연결). BEAM 방향 노드 n3 은 연결이 아니라 뺌. 그 밖(SHEL16·SPHCEL·XELEM) = 건너뜀.
KW_NODES = {
    "SHELL": (4, False, False), "SH3N": (3, False, False), "QUAD": (4, False, False), "TRIA": (3, False, False),
    "BRICK": (8, False, False), "TETRA4": (4, False, False), "PENTA6": (6, False, False),
    "TETRA10": (10, True, False), "BRIC20": (20, True, False),
    "SPRING": (2, False, True), "BEAM": (2, False, True), "RIVET": (2, False, True), "TRUSS": (2, False, False),
}
CAP = 50                      # 노드 ID 목록 상한(위치 요약)


def _ints(raw: bytes, n: int) -> list[int] | None:
    """줄 앞쪽 I10 정수 칸 최대 n 개(빈칸 = 0), 실패 = 자유 형식 토큰. 정수가 아니면 None."""
    line = rp._decode(raw).rstrip("\r\n")
    body = line.rstrip()
    m = min(n, (len(body) + 9) // 10)
    try:
        return [int(t) if (t := body[k * 10:(k + 1) * 10].strip()) else 0 for k in range(m)]
    except ValueError:
        pass
    toks = re.findall(r"[^\s,]+", line)[:n]
    try:
        return [int(t) for t in toks]
    except ValueError:
        return None


def _seg_nodes(fh, seg, k: int, multi: bool) -> np.ndarray:
    """요소 블록 1개 → (m, k) 노드 ID(0 = 빈칸)."""
    rows: list[list[int]] = []
    buf: list[int] = []
    for _ln, raw in rp._Deck._seg_iter(fh, seg):
        if not raw.strip():
            continue
        if not multi:
            v = _ints(raw, 1 + k)
            if v is None or not v or v[0] == 0:
                continue
            rows.append((v[1:] + [0] * k)[:k])
            continue
        v = _ints(raw, 1 + k - len(buf) if buf else 10)
        if v is None:
            continue
        buf += v
        if len(buf) >= 1 + k:
            rows.append(buf[1:1 + k])
            buf = []
    return np.asarray(rows, dtype=np.int64).reshape(-1, k)


def _cards(path: str, max_line: int):
    """파일의 (키워드 경로 대문자 조각, 본문 행 목록[주석 제외]) — /RBODY·/GRNOD 만."""
    out = []
    cur = None
    with open(path, "rb") as fh:
        readline = rp.bounded_readline(fh, path, max_line)
        for raw in iter(readline, b""):
            line = rp._decode(raw).rstrip("\r\n")
            if line.startswith("/"):
                if cur is not None:
                    out.append(cur)
                head = [x.strip().upper() for x in line[1:].split("/")]
                cur = (head, []) if head and head[0] in ("RBODY", "GRNOD") else None
                continue
            if cur is None or line.startswith("#") or line.startswith("$"):
                continue
            cur[1].append(line)
    if cur is not None:
        out.append(cur)
    return out


def _rbody(files: list[str], max_line: int) -> dict:
    """/RBODY 주 노드·grnd_ID, /GRNOD/NODE 목록 → {main[], groups{id: [노드]}, rb_grnd[], other_groups{id}}."""
    mains, grnds, groups, other = [], [], {}, set()
    for p in files:
        if not os.path.isfile(p):
            continue
        for head, body in _cards(p, max_line):
            if head[0] == "RBODY":
                if len(body) < 2:
                    continue
                v = _ints(body[1].encode(), 4)
                if v and v[0] > 0:
                    mains.append(int(v[0]))
                try:
                    g = body[1][60:70].strip()
                    grnds.append(int(g) if g else 0)
                except ValueError:
                    grnds.append(0)
            elif head[0] == "GRNOD":
                kind = head[1] if len(head) > 1 else ""
                try:
                    gid = int(head[2]) if len(head) > 2 else 0
                except ValueError:
                    continue
                if kind == "NODE":
                    ids: list[int] = []
                    for ln in body[1:]:                        # 첫 행 = 제목
                        v = _ints(ln.encode(), 10) or []
                        ids += [x for x in v if x > 0]
                    groups[gid] = groups.get(gid, []) + ids
                else:
                    other.add(gid)
    return {"main": mains, "rb_grnd": grnds, "groups": groups, "other_groups": other}


def node_links(rad_path, part_id: int, node_ids, *, include_path_map: dict | None = None, max_include_depth: int = 8,
               max_line_bytes: int | None = None, cap: int = CAP) -> dict:
    """대상 파트(part_id) 노드(node_ids) 중 공유·회전 연결 노드 요약.

    반환 {status: "ok", n_shared, by_part{pid: n}, by_kw{kw: n}, node_ids[:cap], bbox: null(호출자가 좌표로 채움), n_rot,
    rot{spring, beam, rivet, rbody_main, rbody_secondary}, rot_node_ids[:cap], rbody_unresolved, n_skipped_kw{kw: 줄 수},
    _all(전체 공유 노드 — safe_node_links 가 상자 계산 후 뺌)}. 못 읽음 = EslError(호출자가 status failed 로)."""
    path = os.fspath(rad_path)
    deck = rp._Deck(int(max_include_depth), include_path_map, max_line_bytes)
    deck.scan(path)
    tgt = np.unique(np.asarray(node_ids, dtype=np.int64))
    pid0 = int(part_id)
    shared: set[int] = set()
    by_part: dict[int, set] = {}
    by_kw: dict[str, set] = {}
    rot = {"spring": set(), "beam": set(), "rivet": set(), "rbody_main": set(), "rbody_secondary": set()}
    skipped: dict[str, int] = {}
    files: dict = {}
    try:
        for seg in list(deck.shell_segs) + list(deck.elem_segs):
            if seg.state:
                continue
            kw = seg.kw
            if kw in rp._SHELL_KW and int(seg.hid or 0) == pid0:
                continue
            if kw not in KW_NODES:
                skipped[kw] = skipped.get(kw, 0) + int(seg.nlines)
                continue
            k, multi, is_rot = KW_NODES[kw]
            fh = files.get(seg.file) or files.setdefault(seg.file, open(seg.file, "rb"))
            arr = _seg_nodes(fh, seg, k, multi)
            if not arr.size:
                continue
            hit = np.unique(arr[np.isin(arr, tgt)])
            if not hit.size:
                continue
            hs = set(hit.tolist())
            shared |= hs
            by_part.setdefault(int(seg.hid or 0), set()).update(hs)
            by_kw.setdefault(kw, set()).update(hs)
            if is_rot:
                rot[kw.lower()].update(hs)
    finally:
        for fh in files.values():
            fh.close()
    rb = _rbody([path] + [p for p in deck.includes if p != path], deck.max_line)
    tset = set(tgt.tolist())
    rot["rbody_main"] = {n for n in rb["main"] if n in tset}
    unres = 0
    for g in rb["rb_grnd"]:
        if g in rb["groups"]:
            rot["rbody_secondary"].update(n for n in rb["groups"][g] if n in tset)
        elif g:
            unres += 1
    rot_all = set().union(*rot.values())
    sh = sorted(shared)
    ra = sorted(rot_all)
    return {"status": "ok", "n_shared": len(sh), "by_part": {str(p): len(v) for p, v in sorted(by_part.items())},
            "by_kw": {k: len(v) for k, v in sorted(by_kw.items())}, "node_ids": sh[:int(cap)], "bbox": None,
            "n_rot": len(ra), "rot": {k: len(v) for k, v in rot.items()}, "rot_node_ids": ra[:int(cap)],
            "rbody_unresolved": unres, "n_skipped_kw": skipped, "_all": sh}


def safe_node_links(rad_path, part_id: int, node_ids, x0=None, **kw) -> dict:
    """node_links + 공유 노드 상자(bbox — x0 가 node_ids 순서 좌표면). 실패 = {status: failed, reason}(예외 없음)."""
    try:
        out = node_links(rad_path, part_id, node_ids, **kw)
    except EslError as exc:
        return {"status": "failed", "reason": f"{exc.code}: {exc.message}"[:300]}
    except (OSError, ValueError) as exc:
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:300]}
    allv = out.pop("_all", out["node_ids"])
    if x0 is not None and out["n_shared"]:                    # 전체 공유 노드 상자(목록 cap 과 무관)
        m = np.isin(np.asarray(node_ids, dtype=np.int64), np.asarray(allv, dtype=np.int64))
        if m.any():
            X = np.asarray(x0, dtype=np.float64)
            out["bbox"] = {"lo": X[m].min(axis=0).tolist(), "hi": X[m].max(axis=0).tolist()}
    return out
