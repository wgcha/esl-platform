"""paicad ``--assem-dir`` 용 **모델 전체** 사본 ``prep/assem_full/``(v0.12.1, 계약 esl_bead_doe.md §파이프라인).

paicad 0.14.0 ``shell fixed-scan``·``tag``·``run`` 은 ``--assem-dir`` 아래 ``*.rad``·``*.inc`` 만 재귀로 읽는다. Case 입력
폴더를 제자리로 넘기면 폴더 밖 include(상위·형제 폴더)의 /SURF·/GRNOD 를 못 찾는다(FIXED_PARSE_FAILED). 그래서

- 기준 starter rad(``*_0000.rad``)의 include 트리를 끝까지 해석(``esl.rad.parser.scan_include_refs`` — 상대경로·중첩·
  대소문자·순환 방지)해 전체 파일 집합을 구하고, 허용 입력 루트(storage.input_roots·upload_root·Case 폴더) 밖이면
  PATH_OUTSIDE_ROOT(파일을 읽지 않음), 링크 → PATH_OUTSIDE_ROOT, 못 찾은 include → RAD_PARSE_ERROR.
- rad/inc 만 복사(원본은 읽기만, 복사 전후 sha256 같아야 함, 임시 파일 + os.replace). 합계 > ``same.max_assem_mb`` →
  ASSEM_TOO_LARGE. 엔진 rad(``<stem>_NNNN.rad``, NNNN≠0000)는 ``same.engine_rad`` 가 참일 때만.
- 배치: Case 폴더 안 = Case 폴더 기준 상대경로 그대로(→ paicad run 의 out_files rel = 기존과 같음), 밖 =
  ``_ext/<Case 폴더와 밖 파일 공통 조상 기준 상대경로>``(원래 상대 구조 보존, Case 폴더에 ``_ext`` 가 있으면 ``_ext1``…).
- 스캔 입력 정규화(``bead_doe.fixed_scan``, 아래 절): 사본에서 paicad 미지원 집합 카드 정의만 같은 의미의 지원 형태로
  재작성(/NODE 는 건드리지 않음). paicad run 모핑 사본(out_files) 중 정규화한 파일은 ``restore_out_files`` 가
  **원본 + 모핑 /NODE 좌표**로 되돌린다 — 모핑 결과 파일 = 원본에서 /NODE 좌표만 바뀐 것(기존과 같음).
"""
from __future__ import annotations

import os
import re
import shutil

import numpy as np

from esl.errors import EslError
from esl.library import _util as U

MESH_EXT = (".rad", ".inc")
DIR = "assem_full"
A_DIR = "a_assem_full"
EXT_DIR = "_ext"
_ENGINE_RE = re.compile(r"^(?P<stem>.+)_(?P<n>\d{4})\.rad$", re.IGNORECASE)


def _isjunction(p: str) -> bool:
    f = getattr(os.path, "isjunction", None)
    return bool(f and f(p))


def _is_engine(path: str) -> bool:
    m = _ENGINE_RE.match(os.path.basename(path))
    return bool(m and m.group("n") != "0000")


def _within_roots(p: str, roots: list[str]) -> bool:
    """lexical·realpath 둘 다 허용 루트 안(심링크 탈출 거부)."""
    ap = os.path.normpath(os.path.abspath(p))
    rp = U.real_path(ap)
    return any(U.is_within(ap, os.path.normpath(os.path.abspath(r))) for r in roots) and \
        any(U.is_within(rp, U.real_path(r)) for r in roots)


def model_closure(starter: str, roots: list[str], *, include_path_map: dict | None = None, max_depth: int = 8,
                  engine_rad: bool = False) -> list[str]:
    """starter include 트리 전체 파일(정규화 절대경로, 첫 항목 = starter, 실제 경로 기준 중복 없음)."""
    from esl.rad.parser import scan_include_refs
    starts = [os.path.normpath(os.path.abspath(starter))]
    m = _ENGINE_RE.match(os.path.basename(starts[0]))
    if engine_rad and m and m.group("n") == "0000":
        d = os.path.dirname(starts[0])
        for name in sorted(os.listdir(d)):
            mm = _ENGINE_RE.match(name)
            if mm and mm.group("n") != "0000" and mm.group("stem").casefold() == m.group("stem").casefold() \
                    and os.path.isfile(os.path.join(d, name)):
                starts.append(os.path.join(d, name))
    out: list[str] = []
    seen: set[str] = set()

    def add(p: str, spec: str) -> None:
        if os.path.islink(p) or _isjunction(p):
            raise EslError("PATH_OUTSIDE_ROOT", f"모델 파일이 링크임 — 거부: {spec}")
        if not _within_roots(p, roots):
            raise EslError("PATH_OUTSIDE_ROOT", "rad 의 include 가 허용된 입력 루트(storage.input_roots·업로드·Case "
                                                f"폴더) 밖입니다: {spec}")
        key = os.path.normcase(U.real_path(p))
        if key not in seen:
            seen.add(key)
            out.append(p)

    for s in starts:
        add(s, os.path.basename(s))
        for r in scan_include_refs(s, include_path_map, max_depth, follow=lambda p: _within_roots(p, roots)):
            if not r["found"]:
                raise EslError("RAD_PARSE_ERROR", f"인클루드 파일을 찾을 수 없음 ({os.path.basename(r['src'])}): "
                                                  f"{r['spec']}")
            add(r["path"], r["spec"])
    if not engine_rad:
        out = [out[0]] + [p for p in out[1:] if not _is_engine(p)]
    return out


def layout(files: list[str], case_dir: str) -> dict[str, str]:
    """{원본: 사본 상대경로} (모듈 설명의 배치 규칙)."""
    cd = os.path.normpath(os.path.abspath(case_dir))
    inside = {f: os.path.relpath(f, cd) for f in files if U.is_within(f, cd)}
    outside = [f for f in files if f not in inside]
    used_top = {os.path.normcase(r.split(os.sep, 1)[0]) for r in inside.values()}
    ext, k = EXT_DIR, 0
    while os.path.normcase(ext) in used_top:
        k += 1
        ext = f"{EXT_DIR}{k}"
    lay = dict(inside)
    if outside:
        try:
            anchor = os.path.commonpath([cd] + [os.path.dirname(f) for f in outside])
        except ValueError:                       # Windows 드라이브가 다름
            anchor = None
        for f in outside:
            if anchor is not None:
                rel = os.path.relpath(f, anchor)
            else:
                drv, rest = os.path.splitdrive(f)
                rel = os.path.join(re.sub(r"[^A-Za-z0-9_]", "", drv) or "root", rest.lstrip("\\/"))
            lay[f] = os.path.join(ext, rel)
    return lay


# ---------------------------------------------------------------- 스캔 사본 정규화(카드 정의만 재작성)
# paicad 0.14.0 이 읽는 집합 = /GRNOD/{NODE,PART,GRNOD}/<id>, /SURF/{PART,SEG,SURF}/<id>(id = kw[2]). 그 밖 형태를 같은
# 의미의 지원 형태로 바꾼다: (a) 키워드 규칙 [from, to](기본 SURF/PART/EXT|ALL → SURF/PART, 데이터 그대로)
# (b) /SURF/SUBSET/<EXT|ALL>/<id>·/GRNOD/SUBSET/<id> → /SUBSET 트리(하위 subset·/PART 의 subset_ID, 순환 방지)를 모델
# 전체에서 펼친 파트 목록의 /SURF/PART/<id>·/GRNOD/PART/<id> (c) /GRNOD/GENE/<id>(시작 끝 증분) → /GRNOD/NODE/<id>
# (d) /SURF/PART[/EXT|ALL]·/SURF/SUBSET[/EXT|ALL] 이 솔리드 파트를 포함하면 /SURF/SEG/<id>(쉘 = 요소, 솔리드 = 면:
# EXT·옵션 없음 = 파트 안에서 공유되지 않는 외곽 면, ALL = 모든 면 중복 제거) — shell-shell·shell-solid tie 모두 스캔.
MAX_EXPAND = 5_000_000


def _is_comment(line: str) -> bool:
    return line.startswith(("#", "$"))


def _ints(line: str) -> list[int] | None:
    """데이터 줄 정수(paicad 와 같은 규칙: 10칸 고정폭 전부 정수면 그것, 아니면 공백·쉼표 토큰)."""
    vals, ok = [], True
    body = line.rstrip()
    for k in range(0, len(body), 10):
        t = body[k:k + 10].strip()
        if not t:
            continue
        try:
            vals.append(int(t))
        except ValueError:
            ok = False
            break
    if ok:
        return vals
    try:
        return [int(t) for t in re.findall(r"[^\s,]+", line)]
    except ValueError:
        return None


def _fields(line: str, cols: list[tuple[int, int]]) -> list[int | None]:
    """고정 칸 정수(빈칸 None) — 칸이 정수가 아니면 자유 형식 토큰."""
    out = []
    try:
        for a, b in cols:
            t = line[a:b].strip()
            out.append(int(t) if t else None)
        return out
    except ValueError:
        toks = re.findall(r"[^\s,]+", line)
        return [int(toks[i]) if i < len(toks) and re.fullmatch(r"-?\d+", toks[i]) else None for i in range(len(cols))]


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """[(키워드 줄 번호, 다음 키워드 줄 번호)] — 키워드 = '/' 로 시작."""
    idx = [i for i, ln in enumerate(lines) if ln.startswith("/")]
    return [(a, idx[k + 1] if k + 1 < len(idx) else len(lines)) for k, a in enumerate(idx)]


def _kw(line: str) -> list[str]:
    return [x.strip() for x in line.rstrip().split("/")[1:]]


def _title_data(lines: list[str], a: int, b: int) -> tuple[int | None, list[int]]:
    """(제목 줄 번호 | None, 데이터 줄 번호들) — 주석 다음 첫 비주석 줄 = 제목(paicad 규칙)."""
    j = a + 1
    while j < b and _is_comment(lines[j]):
        j += 1
    t = j if j < b else None
    data = [k for k in range((t + 1) if t is not None else b, b) if lines[k].strip() and not _is_comment(lines[k])]
    return t, data


class Model:
    """모델 전체의 /SUBSET(하위 목록)·/PART subset_ID(3번째 칸) — 정규화 (b) 용."""

    def __init__(self) -> None:
        self.subsets: dict[int, list[int]] = {}
        self.part_subset: dict[int, int] = {}
        self.parts: set[int] = set()
        self.surf_parts: set[int] = set()          # /SURF/PART* 가 직접 가리키는 파트
        self.surf_subsets: set[int] = set()        # /SURF/SUBSET* 가 가리키는 subset
        self.elems: dict[int, dict[str, list]] = {}    # 파트 → {키워드: [연결 행]} (필요한 파트만)

    def needed_parts(self) -> set[int]:
        out = set(self.surf_parts)
        for s in self.surf_subsets:
            try:
                out |= set(self.subset_parts(s, "/SURF/SUBSET"))
            except EslError:
                pass                                # 펼칠 때 카드 id 와 함께 다시 오류
        return out

    def scan_elems(self, lines: list[str], need: set[int]) -> None:
        """필요한 파트의 요소 연결(코너 노드) — 요소 ID 는 쓰지 않음(세그먼트 = 노드)."""
        for a, b in _blocks(lines):
            kw = _kw(lines[a])
            if len(kw) < 2 or not kw[1].isdigit():
                continue
            head = kw[0].upper()
            k = ELEM_NODES.get(head)
            if k is None or int(kw[1]) not in need:
                continue
            rows = self.elems.setdefault(int(kw[1]), {}).setdefault(head, [])
            for i in range(a + 1, b):
                ln = lines[i]
                if not ln.strip() or _is_comment(ln):
                    continue
                v = _ints(ln)
                if not v or len(v) < (5 if head == "TETRA10" else 2):
                    continue                                    # TETRA10 연속 줄 등
                c = v[1:1 + k]
                if head == "SH3N" or (head == "SHELL" and len(c) == 3):
                    c = c[:3] + [c[2]]
                rows.append((c + [0] * 4)[:max(k, 4)] if head in ("SHELL", "SH3N") else (c + [0] * k)[:k])

    def scan(self, lines: list[str]) -> None:
        for a, b in _blocks(lines):
            kw = _kw(lines[a])
            head = kw[0].upper() if kw else ""
            if head == "SURF" and len(kw) >= 3 and kw[1].upper() in ("PART", "SUBSET"):
                n = 3 if len(kw) >= 4 and kw[2].upper() in ("EXT", "ALL") else 2
                if len(kw) > n and kw[n].isdigit():
                    _t, data = _title_data(lines, a, b)
                    ids = [x for k in data for x in (_ints(lines[k]) or []) if x > 0]
                    (self.surf_parts if kw[1].upper() == "PART" else self.surf_subsets).update(ids)
            if head == "SUBSET" and len(kw) >= 2 and kw[1].isdigit():
                _t, data = _title_data(lines, a, b)
                ids: list[int] = []
                for k in data:
                    v = _ints(lines[k])
                    if v is None:
                        raise EslError("FIXED_PARSE_FAILED", f"/SUBSET/{kw[1]}: 줄을 읽지 못함 {lines[k][:40]!r}")
                    ids += [x for x in v if x > 0]
                self.subsets[int(kw[1])] = ids
            elif head == "PART" and len(kw) >= 2 and kw[1].isdigit():
                pid = int(kw[1])
                self.parts.add(pid)
                _t, data = _title_data(lines, a, b)
                if data:
                    f = _fields(lines[data[0]], [(0, 10), (10, 20), (20, 30)])
                    if f[2]:
                        self.part_subset[pid] = int(f[2])

    def subset_parts(self, sid: int, label: str) -> list[int]:
        """subset → 파트 id(/PART subset_ID ∪ 하위 subset 재귀, 순환 방지). 목록 id 가 subset 이 아니고 파트면 파트(구형)."""
        out: list[int] = []
        seen: set[int] = set()

        def walk(s: int) -> None:
            if s in seen:
                return
            seen.add(s)
            if s not in self.subsets:
                raise EslError("FIXED_PARSE_FAILED", f"{label}: /SUBSET {s} 정의 없음")
            out.extend(p for p, ss in self.part_subset.items() if ss == s)
            for c in self.subsets[s]:
                if c in self.subsets:
                    walk(c)
                elif c in self.parts:
                    out.append(c)
                else:
                    raise EslError("FIXED_PARSE_FAILED", f"{label}: /SUBSET {s} 의 하위 {c} 가 subset·파트 아님")
        walk(sid)
        res = sorted(set(out))
        if not res:
            raise EslError("FIXED_PARSE_FAILED", f"{label}: /SUBSET {sid} 에 파트 없음")
        return res


# 요소 키워드 → 읽을 코너 노드 수, 솔리드 면(코너 로컬 번호, 삼각면은 3개)
ELEM_NODES = {"SHELL": 4, "SH3N": 3, "BRICK": 8, "BRIC20": 8, "TETRA4": 4, "TETRA10": 4, "PENTA6": 6}
SHELL_KW = ("SHELL", "SH3N")
_HEX = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
_TET = [(0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3)]
_PEN = [(0, 1, 2), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]
SOLID_FACES = {"BRICK": _HEX, "BRIC20": _HEX, "TETRA4": _TET, "TETRA10": _TET, "PENTA6": _PEN}


def _faces(conn: np.ndarray, faces) -> np.ndarray:
    """(m, k) 연결 → (m·f, 4) 면(삼각면 n4 = n3)."""
    out = []
    for f in faces:
        q = conn[:, list(f) + ([f[2]] if len(f) == 3 else [])]
        out.append(q)
    return np.concatenate(out, axis=0) if out else np.zeros((0, 4), np.int64)


def _clean(F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """면 → (정리된 면(겹친 노드 제거, 삼각 n4 = n3), 정렬 키(m, 4; 삼각은 -1 채움)). 고유 노드 < 3 면 제외."""
    s = np.sort(F, axis=1)
    dup = np.zeros_like(s, dtype=bool)
    dup[:, 1:] = s[:, 1:] == s[:, :-1]
    s = np.where(dup | (s <= 0), -1, s)
    nu = (s > 0).sum(axis=1)
    ok = nu >= 3
    F, s, nu = F[ok], np.sort(s[ok], axis=1), nu[ok]
    G = F.copy()
    tri = nu == 3
    if np.any(tri):                         # 삼각면: 원래 순서의 고유 노드 3개 + n4 = n3
        for r in np.flatnonzero(tri):
            u = list(dict.fromkeys(int(x) for x in F[r] if x > 0))
            G[r] = u[:3] + [u[2]]
    return G, s


def solid_segments(model: Model, pids: list[int], mode: str, label: str) -> list[list[int]]:
    """파트 목록 → 세그먼트 [n1..n4]. 쉘 = 요소 자체(paicad /SURF/PART 와 같음), 솔리드 = 면(EXT = 그 파트의 다른 요소와
    공유되지 않는 외곽 면, ALL = 모든 면 중복 제거). 혼합 파트는 합침."""
    segs: list[np.ndarray] = []
    for pid in pids:
        el = model.elems.get(int(pid)) or {}
        if not any(el.values()):
            raise EslError("FIXED_PARSE_FAILED", f"{label}: 파트 {pid} 요소 없음")
        for kwd in SHELL_KW:
            if el.get(kwd):
                segs.append(np.asarray(el[kwd], dtype=np.int64)[:, :4])
        F = [_faces(np.asarray(el[k], dtype=np.int64), SOLID_FACES[k]) for k in SOLID_FACES if el.get(k)]
        if not F:
            continue
        G, key = _clean(np.concatenate(F, axis=0))
        _, first, inv, cnt = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
        inv = inv.reshape(-1)
        if mode == "ALL":
            segs.append(G[np.sort(first)])
        else:
            segs.append(G[cnt[inv] == 1])
    if not segs:
        return []
    return np.concatenate(segs, axis=0).tolist()


def _id_lines(ids: list[int]) -> list[str]:
    return ["".join(f"{v:10d}" for v in ids[k:k + 8]) for k in range(0, len(ids), 8)]


def norm_cfg(fs: dict | None) -> dict:
    """bead_doe.fixed_scan → {enabled, rules[(from 성분, to 성분)], expand_subset, expand_gene}."""
    from esl.doe import DEFAULTS
    fs = {**DEFAULTS["fixed_scan"], **(fs or {})}
    return {"enabled": bool(fs.get("enabled", True)),
            "rules": [([x.upper() for x in str(r[0]).split("/")], str(r[1]).split("/")) for r in fs.get("rules") or []],
            "expand_subset": bool(fs.get("expand_subset", True)), "expand_gene": bool(fs.get("expand_gene", True)),
            "expand_solid": bool(fs.get("expand_solid", True))}


def normalize_lines(lines: list[str], cfg: dict, model: Model, rel: str) -> tuple[list[str] | None, dict]:
    """한 파일 줄(EOL 제외) → (바뀐 줄 | None, 건수 {변환: n}). 해당 카드(키워드·데이터)만, 다른 줄 불변."""
    if not cfg["enabled"]:
        return None, {}
    out: list[str] = []
    counts: dict[str, int] = {}
    pos = 0
    for a, b in _blocks(lines):
        kw = _kw(lines[a])
        up = [k.upper() for k in kw]

        def tail(n: int) -> str:
            return ("/" + "/".join(kw[n:])) if len(kw) > n else ""
        new: list[str] | None = None
        key = ""
        if cfg["expand_solid"] and len(up) >= 3 and up[0] == "SURF" and up[1] in ("PART", "SUBSET") and (
                up[1] == "PART" or cfg["expand_subset"]):
            n = 3 if len(up) >= 4 and up[2] in ("EXT", "ALL") else 2
            if len(kw) > n and kw[n].isdigit():
                label = f"/{'/'.join(kw[:n + 1])} ({rel})"
                t, data = _title_data(lines, a, b)
                ids: list[int] = []
                for i in data:
                    v = _ints(lines[i])
                    if v is None:
                        raise EslError("FIXED_PARSE_FAILED", f"{label}: 줄을 읽지 못함 {lines[i][:40]!r}")
                    ids += [x for x in v if x > 0]
                pids = ids if up[1] == "PART" else sorted({p for s_ in ids for p in model.subset_parts(s_, label)})
                solid = [p for p in pids if any(model.elems.get(p, {}).get(k) for k in SOLID_FACES)]
                if solid:
                    mode = "ALL" if n == 3 and up[2] == "ALL" else "EXT"
                    sg = solid_segments(model, pids, mode, label)
                    keep = lines[a + 1:data[0] if data else b]
                    new = ["/SURF/SEG" + tail(n)] + keep + [f"{k + 1:10d}" + "".join(f"{x:10d}" for x in s_)
                                                             for k, s_ in enumerate(sg)]
                    key = f"SURF/{up[1]}{'/' + up[2] if n == 3 else ''}(솔리드)→SURF/SEG"
        for frm, to in ([] if new is not None else cfg["rules"]):
            n = len(frm)
            if len(kw) > n and up[:n] == frm and kw[n].lstrip("-").isdigit():
                new = ["/" + "/".join(to) + tail(n)] + lines[a + 1:b]
                key = "/".join(frm) + "→" + "/".join(to)
                break
        if new is None and cfg["expand_subset"] and len(up) >= 3 and up[1] == "SUBSET" and up[0] in ("SURF", "GRNOD"):
            n = 3 if up[0] == "SURF" and len(up) >= 4 and up[2] in ("EXT", "ALL") else 2
            if len(kw) > n and kw[n].isdigit():
                label = f"/{'/'.join(kw[:n + 1])} ({rel})"
                t, data = _title_data(lines, a, b)
                subs: list[int] = []
                for i in data:
                    v = _ints(lines[i])
                    if v is None:
                        raise EslError("FIXED_PARSE_FAILED", f"{label}: 줄을 읽지 못함 {lines[i][:40]!r}")
                    subs += [x for x in v if x > 0]
                if not subs:
                    raise EslError("FIXED_PARSE_FAILED", f"{label}: subset 목록 없음")
                pids = sorted({p for s_ in subs for p in model.subset_parts(s_, label)})
                keep = lines[a + 1:data[0] if data else b]
                new = [f"/{up[0]}/PART" + tail(n)] + keep + _id_lines(pids)
                key = f"{up[0]}/SUBSET→{up[0]}/PART"
        if new is None and cfg["expand_gene"] and len(up) >= 3 and up[:2] == ["GRNOD", "GENE"] and kw[2].isdigit():
            label = f"/GRNOD/GENE/{kw[2]} ({rel})"
            t, data = _title_data(lines, a, b)
            ids: list[int] = []
            for i in data:
                v = _ints(lines[i])
                if not v or len(v) < 2:
                    raise EslError("FIXED_PARSE_FAILED", f"{label}: 시작·끝·증분 줄을 읽지 못함 {lines[i][:40]!r}")
                s0, s1, inc = v[0], v[1], (v[2] if len(v) > 2 and v[2] else 1)
                if inc <= 0 or s1 < s0:
                    raise EslError("FIXED_PARSE_FAILED", f"{label}: 범위 오류 {s0} {s1} {inc}")
                ids.extend(range(s0, s1 + 1, inc))
                if len(ids) > MAX_EXPAND:
                    raise EslError("FIXED_PARSE_FAILED", f"{label}: 노드 {MAX_EXPAND}개 초과")
            if not ids:
                raise EslError("FIXED_PARSE_FAILED", f"{label}: 범위 줄 없음")
            new = ["/GRNOD/NODE" + tail(2)] + \
                lines[a + 1:data[0] if data else b] + _id_lines(ids)
            key = "GRNOD/GENE→GRNOD/NODE"
        if new is not None:
            out += lines[pos:a] + new
            pos = b
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None, {}
    return out + lines[pos:], counts


def _read_lines(p: str) -> tuple[list[str], str]:
    with open(p, "rb") as fh:
        data = fh.read().decode("latin-1")
    eol = "\r\n" if "\r\n" in data[:65536] else "\n"
    return data.splitlines(), eol


def copy_model_full(starter: str, case_dir: str, roots: list[str], dest_dir: str, *, max_mb: float,
                    include_path_map: dict | None = None, max_depth: int = 8, engine_rad: bool = False,
                    fixed_scan: dict | None = None, guard=None) -> dict:
    """모델 전체 rad/inc → ``dest_dir``(빈 폴더) + 스캔 정규화. 반환 매니페스트
    {schema, starter, case_dir, n_files, total_mb, n_outside, n_normalized, normalized{변환: 건수}, skipped, files[…]}.
    정규화 해석 불가 → FIXED_PARSE_FAILED(카드 id·사유)."""
    g = guard or (lambda p: p)
    cfg = norm_cfg(fixed_scan)
    files = model_closure(starter, list(roots) + [case_dir], include_path_map=include_path_map, max_depth=max_depth,
                          engine_rad=engine_rad)
    mesh = [f for f in files if os.path.splitext(f)[1].lower() in MESH_EXT]
    skipped = [os.path.basename(f) for f in files if f not in mesh]
    mb = sum(os.path.getsize(f) for f in mesh) / (1024 * 1024)
    if mb > float(max_mb):
        raise EslError("ASSEM_TOO_LARGE", f"모델 전체 rad/inc 합계 {mb:.0f} MB > 상한 {float(max_mb):g} MB "
                                          "(bead_doe.same.max_assem_mb) — '다른 모델(메시 있음)'으로 Ch/R 주변만 올려 주세요")
    lay = layout(mesh, case_dir)
    cd = os.path.normpath(os.path.abspath(case_dir))
    rows = []
    model = Model()
    for src in mesh:                                   # 1) 그대로 복사(원본 sha 전후 대조) + 모델 subset 정보
        rel = lay[src]
        dst = os.path.join(dest_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        s0 = U.sha256_file(src)
        tmp = os.path.join(os.path.dirname(dst), f".{os.path.basename(dst)}.{os.getpid()}.tmp")
        shutil.copyfile(src, g(tmp))
        if U.sha256_file(src) != s0 or U.sha256_file(tmp) != s0:
            os.remove(tmp)
            raise EslError("INPUT_CHANGED", f"모델 파일이 복사 중 바뀜(sha256 불일치): {os.path.basename(src)}")
        os.replace(tmp, g(dst))
        if cfg["enabled"] and (cfg["expand_subset"] or cfg["expand_solid"]):
            model.scan(_read_lines(dst)[0])
        rows.append({"rel": rel.replace(os.sep, "/"), "src": src, "sha256": s0, "size": os.path.getsize(dst),
                     "outside": not U.is_within(src, cd), "staged_sha256": s0, "normalized": {}})
    need = model.needed_parts() if cfg["enabled"] and cfg["expand_solid"] else set()
    if need:                                           # 2) /SURF 가 가리키는 파트의 요소(솔리드 면 → /SURF/SEG)
        for r in rows:
            model.scan_elems(_read_lines(os.path.join(dest_dir, *r["rel"].split("/")))[0], need)
    counts: dict[str, int] = {}
    for r in rows:                                     # 3) 스캔 사본만 카드 정의 재작성
        dst = os.path.join(dest_dir, *r["rel"].split("/"))
        lines, eol = _read_lines(dst)
        new, c = normalize_lines(lines, cfg, model, r["rel"])
        if new is None:
            continue
        tmp = os.path.join(os.path.dirname(dst), f".{os.path.basename(dst)}.{os.getpid()}.tmp")
        with open(g(tmp), "wb") as fh:
            fh.write((eol.join(new) + eol).encode("latin-1"))
        os.replace(tmp, g(dst))
        r.update(staged_sha256=U.sha256_file(dst), normalized=c)
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v
    return {"schema": "esl/doe_assem_full/1", "starter": os.path.normpath(os.path.abspath(starter)), "case_dir": cd,
            "n_files": len(rows), "total_mb": round(mb, 3), "n_outside": sum(1 for r in rows if r["outside"]),
            "engine_rad": bool(engine_rad), "n_normalized": sum(counts.values()), "normalized": counts,
            "skipped": skipped, "files": rows}


def summary(man: dict) -> dict:
    """로그·작업 결과용 요약(파일 목록 제외)."""
    return {k: man.get(k) for k in ("n_files", "total_mb", "n_outside", "n_normalized", "normalized", "skipped",
                                    "engine_rad")}


def _node_blocks(lines: list[bytes]) -> list[tuple[int, int]]:
    """/NODE 블록의 (데이터 시작, 끝) 줄 범위."""
    idx = [i for i, ln in enumerate(lines) if ln[:1] == b"/"]
    out = []
    for k, a in enumerate(idx):
        parts = lines[a].rstrip().split(b"/")
        if len(parts) > 1 and parts[1].strip().upper() == b"NODE":
            out.append((a + 1, idx[k + 1] if k + 1 < len(idx) else len(lines)))
    return out


def restore_out_files(out_files_dir: str, rels: list[str], man: dict, guard=None) -> int:
    """paicad run 모핑 사본(out_files/<rel>) 중 스캔 정규화한 파일을 **원본 + 모핑 /NODE 좌표**로 되돌린다.

    원본(매니페스트 src, sha256 대조)의 /NODE 블록 데이터 줄을 모핑 사본의 같은 순서·같은 줄 수 블록으로 교체한다.
    블록 수·줄 수가 다르면 PAICAD_FAILED, 원본이 바뀌었으면 INPUT_CHANGED. 되돌린 파일 수."""
    g = guard or (lambda p: p)
    by = {r["rel"]: r for r in man.get("files") or [] if r.get("staged_sha256") != r.get("sha256")}
    root = U.real_path(out_files_dir)
    n = 0
    for rel in rels:
        row = by.get(rel)
        if row is None:
            continue
        p = os.path.join(out_files_dir, *rel.split("/"))
        if os.path.islink(p) or not U.is_within(U.real_path(p), root):
            raise EslError("PATH_OUTSIDE_ROOT", f"모핑 사본 경로가 out_files 밖: {rel}")
        if U.sha256_file(row["src"]) != row["sha256"]:
            raise EslError("INPUT_CHANGED", f"원본 모델 파일이 준비 후 바뀜: {os.path.basename(row['src'])}")
        with open(row["src"], "rb") as fh:
            orig = fh.read().splitlines(keepends=True)
        with open(p, "rb") as fh:
            mor = fh.read().splitlines(keepends=True)
        bo, bm = _node_blocks(orig), _node_blocks(mor)
        if len(bo) != len(bm) or any((b - a) != (d - c) for (a, b), (c, d) in zip(bo, bm)):
            raise EslError("PAICAD_FAILED", f"모핑 사본 {rel} 의 /NODE 블록이 원본과 다름 — 원본 기준 복원 불가")
        res, pos = [], 0
        for (a, b), (c, d) in zip(bo, bm):
            res += orig[pos:a] + mor[c:d]
            pos = b
        res += orig[pos:]
        tmp = os.path.join(os.path.dirname(p), f".{os.path.basename(p)}.{os.getpid()}.tmp")
        with open(g(tmp), "wb") as fh:
            fh.write(b"".join(res))
        os.replace(tmp, g(p))
        n += 1
    return n


