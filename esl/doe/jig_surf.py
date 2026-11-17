"""지그 순위용 deck 표면 읽기 — 대상 파트 밖 부품의 표면 삼각형(변형 전 좌표) (계약 esl_jig_rank.md §5.4, D-0.23.0-JIG-3·9).

IO 모듈(파일을 읽기만 함 — 입력 폴더·SPDM 에 쓰지 않음). 모드 무관: 호출자가 deck 경로(원 Case starter | 업로드 사본)와
대상 파트 id·상자를 넘기고, 계획 열 이름은 모른다. 접촉 판정·영역 선택은 순수 모듈 ``esl.doe.jig`` 가 한다(이 모듈은 삼각형만 만듦).

1. ``_Deck.scan``(위치만) → 2. ``load_nodes_box``(상자 ⊕ pad) → 3. 대상 파트 밖 ``shell_segs``·``elem_segs`` 에서 상자 안
노드가 1개 이상인 요소만 보관(여러 줄 카드 = ``assem_full.ELEM_TOTAL``, 코너 = ``ELEM_NODES``) → 4. 솔리드는 파트마다
``assem_full._faces``·``_clean`` 으로 면을 만들고 공유되지 않는 면(EXT)만 → 5. 면·쉘을 삼각형으로(쿼드 (0,1,2)(0,2,3), 퇴화 제거),
상자 밖 노드를 참조하는 요소의 노드는 ``load_nodes`` 로 보충 → 6. 삼각형 수 > ``max_tris`` = ``JIG_SURF_TOO_LARGE``.
"""
from __future__ import annotations

import os
import time

import numpy as np

from esl.doe import assem_full as af
from esl.errors import EslError
from esl.rad import parser as rp

SHELL_KW = ("SHELL", "SH3N")


def _row_ints(raw: bytes, n: int) -> list[int] | None:
    """한 줄 앞쪽 정수 칸 최대 n 개(10칸 고정폭 빠른 경로 → ``assem_full._lead_ints``)."""
    try:
        if len(raw.rstrip()) >= 10 * n or n == 1:
            v = [int(raw[k:k + 10]) for k in range(0, 10 * n, 10)]
            if v and v[0] != 0:
                return v
    except ValueError:
        pass
    return af._lead_ints(raw.decode("ascii", "replace") if raw.isascii() else rp._decode(raw), n)


def _read_elems(fh, seg, kw: str, in_box) -> list[list[int]]:
    """블록 1개의 요소 → 코너 노드 ID 목록(상자 안 노드가 1개 이상인 요소만). 여러 줄 카드는 노드 칸이 찰 때까지 모음."""
    k, total = af.ELEM_NODES[kw], af.ELEM_TOTAL[kw]
    out: list[list[int]] = []
    buf: list[int] = []
    for _ln, raw in rp._Deck._seg_iter(fh, seg):
        if not raw.strip():
            continue
        v = _row_ints(raw, 1 + total - len(buf))
        if v is None:
            raise EslError("RAD_PARSE_ERROR", f"/{kw}/{seg.hid} 요소 줄을 읽지 못함 ({seg.file}:{_ln})")
        buf += v
        if len(buf) < 1 + total:
            continue
        c = buf[1:1 + k]
        buf = []
        if kw == "SH3N":
            c = c[:3] + [c[2]]
        elif kw == "SHELL" and (len(c) < 4 or c[3] == 0):
            c = c[:3] + [c[2]]
        if any(in_box(n) for n in c):
            out.append(c)
    if buf:
        raise EslError("RAD_PARSE_ERROR", f"/{kw}/{seg.hid} 마지막 요소 줄이 모자람 ({seg.file})")
    return out


def _tris_of(quad: np.ndarray) -> np.ndarray:
    """(m,4) 노드 ID 면(삼각 = n4 == n3) → (t,3) 삼각형(쿼드 (0,1,2)(0,2,3), 노드 겹침 퇴화 제거)."""
    q = np.asarray(quad, dtype=np.int64).reshape(-1, 4)
    t1 = q[:, [0, 1, 2]]
    isq = q[:, 3] != q[:, 2]
    t2 = q[isq][:, [0, 2, 3]]
    t = np.concatenate([t1, t2], axis=0)
    bad = (t[:, 0] == t[:, 1]) | (t[:, 1] == t[:, 2]) | (t[:, 0] == t[:, 2]) | (t.min(axis=1) <= 0)
    return t[~bad]


def other_surfaces(rad_path, target_part_id: int, box_lo, box_hi, *, include_path_map: dict | None = None,
                   max_include_depth: int = 8, max_line_bytes: int | None = None, max_tris: int = 20_000_000,
                   pad_mm: float = 0.0) -> dict:
    """deck(``rad_path`` + include) → 대상 파트(``target_part_id``) 밖 표면 삼각형.

    box_lo·box_hi = 대상 평가 노드 상자(+ ``pad_mm`` = contact_gap_mm + 대상 최대 요소 크기, 호출자가 계산해 넘김).
    반환 ``{"x": (P,3), "node_id": (P,), "tri": (T,3) int64(x 의 로컬 행), "tri_part": (T,) int64, "n_parts", "n_shell",
    "n_solid_faces", "n_skipped", "seconds"}`` (삼각형 0 개면 T = 0). 못 읽음 = ``RAD_PARSE_ERROR``·``PATH_OUTSIDE_ROOT``(파서),
    T > max_tris = ``JIG_SURF_TOO_LARGE``. 지원 요소 SHELL·SH3N·BRICK·BRIC20·TETRA4·TETRA10·PENTA6, 그 밖은 무시(``n_skipped`` =
    그 요소 줄 수)."""
    t0 = time.monotonic()
    path = os.fspath(rad_path)
    deck = rp._Deck(int(max_include_depth), include_path_map, max_line_bytes)
    deck.scan(path)
    lo = np.asarray(box_lo, dtype=np.float64).reshape(3) - float(pad_mm)
    hi = np.asarray(box_hi, dtype=np.float64).reshape(3) + float(pad_mm)
    bid, bxyz = deck.load_nodes_box(lo, hi)
    bset = set(bid.tolist())
    in_box = bset.__contains__
    tgt = int(target_part_id)
    n_skipped = 0
    shell_tris: list[np.ndarray] = []
    shell_part: list[np.ndarray] = []
    solid_faces: dict[int, list[np.ndarray]] = {}
    n_shell = n_ntri = 0
    files: dict = {}
    try:
        for seg in list(deck.shell_segs) + list(deck.elem_segs):
            if seg.hid == tgt:
                continue
            kw = seg.kw
            if kw not in af.ELEM_NODES:
                n_skipped += int(seg.nlines)
                continue
            fh = files.get(seg.file) or files.setdefault(seg.file, open(seg.file, "rb"))
            el = _read_elems(fh, seg, kw, in_box)
            if not el:
                continue
            conn = np.asarray(el, dtype=np.int64)
            if kw in SHELL_KW:
                t = _tris_of(conn)
                shell_tris.append(t)
                shell_part.append(np.full(t.shape[0], int(seg.hid or 0), dtype=np.int64))
                n_shell += conn.shape[0]
                n_ntri += t.shape[0]
            else:
                solid_faces.setdefault(int(seg.hid or 0), []).append(af._faces(conn, af.SOLID_FACES[kw]))
                n_ntri += 6 * conn.shape[0]           # 외곽 면 수의 상한 추정(공유 면 제거 전) — 조기 중단용
            if n_ntri > 8 * int(max_tris):            # 메모리 폭주 방지(정확한 판정은 끝에서)
                raise EslError("JIG_SURF_TOO_LARGE", f"표면 삼각형이 상한({int(max_tris)})을 크게 넘음")
    finally:
        for fh in files.values():
            fh.close()
    tris, parts = list(shell_tris), list(shell_part)
    n_solid = 0
    for pid in sorted(solid_faces):
        F = np.concatenate(solid_faces[pid], axis=0)
        G, key = af._clean(F)
        if G.shape[0] == 0:
            continue
        _, _first, inv, cnt = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
        G = G[cnt[inv.reshape(-1)] == 1]               # EXT: 파트 안에서 공유되지 않는 면
        n_solid += int(G.shape[0])
        t = _tris_of(G)
        tris.append(t)
        parts.append(np.full(t.shape[0], pid, dtype=np.int64))
    T = np.concatenate(tris, axis=0) if tris else np.zeros((0, 3), np.int64)
    TP = np.concatenate(parts, axis=0) if parts else np.zeros(0, np.int64)
    # 노드 좌표: 상자 안(load_nodes_box) + 상자 밖 참조(load_nodes 로 보충)
    ref = np.unique(T) if T.size else np.zeros(0, np.int64)
    miss = ref[~np.isin(ref, bid)] if ref.size else ref
    ids = bid
    xyz = bxyz
    if miss.size:
        mx, _u, found = deck.load_nodes(miss)
        ids = np.concatenate([bid, miss[found]])
        xyz = np.concatenate([bxyz, mx[found]], axis=0)
        o = np.argsort(ids, kind="mergesort")
        ids, xyz = ids[o], xyz[o]
    if T.size:                                         # 노드 못 찾은 삼각형 제거
        pos = np.searchsorted(ids, T).clip(0, max(ids.size - 1, 0))
        ok = (ids[pos] == T).all(axis=1) if ids.size else np.zeros(T.shape[0], bool)
        T, TP = T[ok], TP[ok]
    if T.shape[0] > int(max_tris):
        raise EslError("JIG_SURF_TOO_LARGE", f"표면 삼각형 {T.shape[0]} > 상한 {int(max_tris)}")
    used = np.unique(T) if T.size else np.zeros(0, np.int64)         # 쓰이는 노드만, 로컬 행으로
    lx = xyz[np.searchsorted(ids, used)] if used.size else np.zeros((0, 3))
    tri = np.searchsorted(used, T) if T.size else np.zeros((0, 3), np.int64)
    return {"x": lx.astype(np.float64).reshape(-1, 3), "node_id": used.astype(np.int64), "tri": tri.astype(np.int64),
            "tri_part": TP.astype(np.int64), "n_parts": int(np.unique(TP).size), "n_shell": int(n_shell),
            "n_solid_faces": int(n_solid), "n_skipped": int(n_skipped), "seconds": round(time.monotonic() - t0, 3)}
