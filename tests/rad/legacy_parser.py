"""[시험 기준 구현] 0.5.1 esl/rad/parser.py 사본 — 수정 금지(test_rad_target_part.py 동일성 비교용).

Radioss starter(_0000.rad) 블록 포맷(2017+) 파서.

계약: docs/contracts/esl_core.md §3.1. 대상 파트(쉘) 하나의 메시·두께·재료만 꺼내고,
그 외 키워드는 본문을 건너뛰되 ID만 ``max_ids``에 반영한다.

카드 레이아웃(10자 셀, 정수 I10 = 1셀, 실수 F20 = 2셀) — 매뉴얼 기준:
  /NODE                 node_ID(I10) Xc(F20) Yc(F20) Zc(F20)
  /SHELL/part_ID        shell_ID n1 n2 n3 n4 (I10×5) [빈 셀 51-60] Phi(F20, 61-80) Thick(F20, 81-100)
  /SH3N/part_ID         sh3n_ID n1 n2 n3 (I10×4) [빈 셀 41-60] Phi(F20, 61-80) Thick(F20, 81-100)
                        (※ /SH3N 의 Phi·Thick 열 위치는 /SHELL 과 같다고 가정 — 확신 없음, 보고 참조)
  /PART/part_ID         part_title(100자) / prop_ID mat_ID subset_ID (I10×3) Thick(F20)
  /PROP/SHELL(/TYPE1)   title / Ishell Ismstr Ish3n Idrill Ipinch .. P_Thick_Fail
                        / Hm Hf Hr Dm Dn (F20×5) / N(I10) Istrain(I10) Thick(F20, 21-40) Ashear(F20) ...
  /MAT/LAW1|ELAST       title / RHO_I(F20) / E(F20) nu(F20)
  /MAT/LAW2|PLAS_JOHNS  title / RHO_I(F20) / E(F20) nu(F20) Iflag(I10) ...
  /MAT/LAW36|PLAS_TAB   title / RHO_I(F20) / E(F20) nu(F20) Eps_p_max Eps_t Eps_m ...
  /BEGIN                Runname / Invers Irun / 입력 단위(질량·길이·시간, 20자×3) / 작업 단위

주석 행(``#``, ``##``)은 카드 행 위치에 포함하지 않는다. 주석이 아닌 빈 행은 위치를 차지한다.
인클루드: ``/INCLUDE "경로"``(같은 줄 또는 다음 비주석 행) 및 ``#include 경로``.
"""

from __future__ import annotations

import math
import os
import re
from array import array
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from esl.errors import EslError

CELL = 10

# 대상 파트에 있으면 UNSUPPORTED_ELEMENT 가 되는 (비쉘) 요소 키워드. 헤더 ID = part_ID, 행 첫 I10 = 요소 ID.
_OTHER_ELEM_KW = frozenset({
    "BRICK", "TETRA4", "TETRA10", "PENTA6", "BRIC20", "SHEL16", "BEAM", "TRUSS", "SPRING",
    "QUAD", "TRIA", "SPHCEL", "RIVET", "XELEM",
})
_SHELL_KW = frozenset({"SHELL", "SH3N"})

_MAX_ID_KEYS = ("node", "elem", "part", "prop", "mat", "func", "grnod", "load", "bcs")
# 헤더 마지막 숫자 ID 를 max_ids 어느 키에 반영할지.
_HEADER_ID_KEY = {
    "PART": "part", "PROP": "prop", "MAT": "mat",
    "FUNCT": "func", "FUNCT_SMOOTH": "func", "TABLE": "func", "MOVE_FUNCT": "func",
    "GRNOD": "grnod",
    "CLOAD": "load", "PLOAD": "load", "GRAV": "load", "IMPVEL": "load", "IMPDISP": "load",
    "IMPACC": "load", "LOAD": "load", "PFLUID": "load", "INIVEL": "load",
    "BCS": "bcs",
}

# 재료 law 정규화: subtype → (라벨, E·ν 행 위치(타이틀 다음 0-기준), RHO 행 위치)
_LAW = {
    "LAW1": "LAW1", "ELAST": "LAW1",
    "LAW2": "LAW2", "PLAS_JOHNS": "LAW2",
    "LAW36": "LAW36", "PLAS_TAB": "LAW36",
}

_FORTRAN_EXP = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d+)$")
_WS = re.compile(r"\s+")
_TITLE_SEP = re.compile(r"[\s_-]+")


_INT_RE = re.compile(r"[+-]?\d+")
# 헤더의 '첫 번째 숫자' 가 ID 가 아닌 키워드 → 숫자 토큰 중 ID 위치(없으면 None), unit 위치.
#   /NODE/unit_ID, /TABLE/dim/table_ID(/unit_ID)
_HEADER_NUM_LAYOUT = {"NODE": (None, 0), "CNODE": (None, 0), "TABLE": (1, 2)}


def _split_header(pieces: list[str]) -> tuple[str, str | None, int | None, int | None]:
    """키워드 헤더 ``/KW[/SUB...]/<ID>[/<unit_ID>]`` → (kw, sub, id, unit_id).

    Radioss 2017+ 규약: 영문 subtype 뒤 첫 정수 = 카드 ID, 둘째 정수 = unit_ID
    (예 /MAT/LAW1/mat_ID/unit_ID, /PROP/SHELL/prop_ID/unit_ID, /PART/part_ID/unit_ID,
    /SHELL/part_ID, /GRNOD/NODE/grnod_ID, /CLOAD/load_ID/unit_ID).
    예외: /NODE/unit_ID (ID 없음), /TABLE/1/table_ID (첫 정수 = 차원).
    """
    kw = pieces[0].upper() if pieces else ""
    sub = None
    nums: list[int] = []
    for p in pieces[1:]:
        if _INT_RE.fullmatch(p):
            nums.append(int(p))
        elif not nums and sub is None:
            sub = p.upper()
    id_pos, unit_pos = _HEADER_NUM_LAYOUT.get(kw, (0, 1))
    hid = nums[id_pos] if id_pos is not None and len(nums) > id_pos else None
    unit = nums[unit_pos] if len(nums) > unit_pos else None
    return kw, sub, hid, unit


_WIN_ABS = re.compile(r"^(?:[A-Za-z]:/|//)")


def _is_windows_abs(p: str) -> bool:
    """``C:/..``, ``C:\\..``(구분자 정규화 후), UNC ``\\\\srv\\share``."""
    return bool(_WIN_ABS.match(p.replace("\\", "/")))


def _norm_prefix(p: str) -> str:
    p = p.replace("\\", "/")
    while "//" in p[2:]:
        p = p[:2] + p[2:].replace("//", "/")
    return p.rstrip("/")


def _map_path(name: str, path_map: dict | None) -> str | None:
    """include_path_map 접두 치환(대소문자 무시, 구분자 정규화, 가장 긴 접두 우선). 해당 없으면 None."""
    if not path_map:
        return None
    n = _norm_prefix(name)
    nl = n.casefold()
    best = None
    for k, v in path_map.items():
        kp = _norm_prefix(str(k))
        if not kp:
            continue
        kl = kp.casefold()
        if nl == kl or nl.startswith(kl + "/"):
            if best is None or len(kp) > len(best[0]):
                best = (kp, str(v))
    if best is None:
        return None
    rest = n[len(best[0]):].lstrip("/")
    return os.path.join(best[1], *rest.split("/")) if rest else best[1]


def _err(msg: str) -> EslError:
    return EslError("RAD_PARSE_ERROR", msg)


def _f(text: str) -> float | None:
    """F20 등 실수 필드. 빈 칸 → None. Fortran D 지수·'1.0-5' 형식 허용."""
    s = text.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    s2 = s.replace("D", "E").replace("d", "e")
    try:
        return float(s2)
    except ValueError:
        m = _FORTRAN_EXP.match(s2)
        if m:
            return float(f"{m.group(1)}e{m.group(2)}")
    raise ValueError(f"실수 필드를 읽을 수 없음: {s!r}")


def _i(text: str) -> int | None:
    s = text.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        v = float(s.replace("D", "E").replace("d", "e"))
        if not v.is_integer():
            raise ValueError(f"정수 필드가 정수가 아님: {s!r}")
        return int(v)


def _cell(line: str, start_cell: int, ncell: int = 1) -> str:
    a = start_cell * CELL
    return line[a:a + ncell * CELL]


def _norm_title(t: str, match: str) -> str:
    if match == "exact":
        return t.rstrip()
    return _TITLE_SEP.sub(" ", t).strip().casefold()


def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc).rstrip("\r\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1").rstrip("\r\n")


@dataclass
class RadModel:
    node_id: np.ndarray
    x0: np.ndarray
    elem_id: np.ndarray
    elem_type: np.ndarray
    conn: np.ndarray
    elem_pid: np.ndarray
    thickness: np.ndarray
    E: np.ndarray
    nu: np.ndarray
    part_id: int
    part_title: str
    units_label: str
    mats: list = field(default_factory=list)
    max_ids: dict = field(default_factory=dict)
    includes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _include_spec(line: str) -> str:
    return line.strip().strip('"').strip("'").strip()


def _resolve_include(orig: str, root_dir: str, src: str, path_map: dict | None):
    """include 경로 해석(parse_rad·scan_includes 공용).

    반환 (찾은 경로 | None, 파일명 대체 여부, 후보 경로들, Windows 절대 여부, 매핑 결과).
    순서: include_path_map 접두 치환 → 절대 경로 → rad 폴더·포함하는 파일 폴더 기준 상대 경로
    → (절대·매핑 경로를 못 찾으면) 파일명만으로 rad 폴더·포함하는 파일 폴더.
    """
    name = orig.replace("\\", "/")
    src_dir = os.path.dirname(os.path.abspath(src))
    win_abs = _is_windows_abs(name)
    mapped = _map_path(name, path_map)
    if mapped is not None:
        cands = [mapped]
    elif os.path.isabs(name) or win_abs:
        cands = [name]
    else:
        cands = [os.path.join(root_dir, name), os.path.join(src_dir, name)]
    for c in cands:
        if os.path.isfile(c):
            return c, False, cands, win_abs, mapped
    base = name.rstrip("/").rsplit("/", 1)[-1]
    if base and (win_abs or os.path.isabs(name) or mapped is not None):
        for d in dict.fromkeys((root_dir, src_dir)):
            c = os.path.join(d, base)
            if os.path.isfile(c):
                return c, True, cands, win_abs, mapped
    return None, False, cands, win_abs, mapped


def _read_include_specs(path: str) -> list[str] | None:
    """파일의 ``/INCLUDE``·``#include`` 원문 목록(본문 해석 없음). 읽을 수 없으면 None."""
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    specs: list[str] = []
    with fh:
        pending = False
        for raw in fh:
            line = _decode(raw)
            if pending:
                if not line.strip() or line.startswith("#"):
                    continue
                pending = False
                specs.append(_include_spec(line))
                continue
            if line.startswith("#"):
                if line[:8].lower() == "#include":
                    specs.append(_include_spec(line[8:]))
                continue
            if line.startswith("/"):
                head = line.split()[0] if line.split() else line
                pieces = [x for x in head.split("/") if x]
                kw = pieces[0].upper() if pieces else ""
                if kw == "END":
                    break
                if kw == "INCLUDE":
                    rest = line.strip()[len("/INCLUDE"):].strip()
                    if rest:
                        specs.append(_include_spec(rest))
                    else:
                        pending = True
    return specs


def scan_includes(rad_path, include_path_map: dict[str, str] | None = None, max_depth: int = 8) -> list[str]:
    """본문을 해석하지 않고 ``/INCLUDE``·``#include`` 줄만 따라가 include 파일 경로 목록을 돌려준다.

    출력 폴더 보호(입력 폴더 쓰기 금지)용 가벼운 스캐너. 경로 해석 규칙은 parse_rad 와 같다.
    오류를 던지지 않는다: 읽을 수 없는 파일은 건너뛰고, 찾지 못한 include 는 후보 경로를 그대로
    넣어(그 폴더도 보호) 돌려준다. 순환·깊이 초과는 더 따라가지 않는다.
    """
    out: list[str] = []
    for ref in scan_include_refs(rad_path, include_path_map, max_depth):
        for p in ([ref["path"]] if ref["found"] else ref["candidates"]):
            if p not in out:
                out.append(p)
    return out


def scan_include_refs(rad_path, include_path_map: dict[str, str] | None = None, max_depth: int = 8,
                      follow=None) -> list[dict]:
    """include 참조 목록: ``{spec(원문), path(찾은 경로 | 첫 후보), candidates, found, src}`` (중첩 순서대로, 경로는 정규화).

    ``follow(path) -> bool`` 이 주어지면 그 값이 참인 파일 안으로만 더 들어간다(예: 업로드 폴더 밖 파일은 읽지 않음).
    오류를 던지지 않는다(읽을 수 없는 파일은 건너뜀). 순환·깊이 초과는 더 따라가지 않는다.
    """
    root = os.path.abspath(os.fspath(rad_path))
    root_dir = os.path.dirname(root)
    out: list[dict] = []
    seen: set[str] = set()

    def norm(p: str) -> str:
        return os.path.normpath(os.path.abspath(p))

    def walk(path: str, depth: int) -> None:
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            return
        seen.add(key)
        specs = _read_include_specs(path)
        if specs is None:
            return
        for orig in specs:
            if not orig:
                continue
            found, _, cands, _, _ = _resolve_include(orig, root_dir, path, include_path_map)
            cn = list(dict.fromkeys(norm(c) for c in cands))
            if found is None:
                out.append({"spec": orig, "path": cn[0] if cn else "", "candidates": cn, "found": False, "src": path})
                continue
            fp = norm(found)
            out.append({"spec": orig, "path": fp, "candidates": cn, "found": True, "src": path})
            if depth + 1 <= max_depth and (follow is None or follow(fp)):
                walk(fp, depth + 1)

    walk(root, 0)
    return out


@dataclass
class _Card:
    kw: str
    sub: str | None
    hid: int | None
    file: str
    line: int
    rows: list = field(default_factory=list)
    unit: int | None = None


class _Deck:
    """한 번의 순차 스캔으로 필요한 카드만 수집."""

    def __init__(self, max_depth: int, path_map: dict | None = None):
        self.max_depth = max_depth
        self.path_map = dict(path_map) if path_map else None
        self.node_id = array("q")
        self.node_xyz = array("d")
        self.node_unit = array("q")     # 각 노드 정의가 속한 /NODE 블록의 unit_ID (없으면 0)
        # 쉘: id, part, n1..n4 (6개씩), 두께, 타입
        self.sh_int = array("q")
        self.sh_thk = array("d")
        self.sh_type = array("b")
        self.other_elem_parts: dict[int, int] = {}
        self.parts: dict[int, dict] = {}
        self.props: dict[int, dict] = {}
        self.mats: dict[int, dict] = {}
        self.units_label = ""
        self.max_ids = {k: 0 for k in _MAX_ID_KEYS}
        self.includes: list[str] = []
        self.warnings: list[str] = []
        self.root_dir = ""

    # ------------------------------------------------------------ 스캔
    def scan(self, path: str, depth: int = 0) -> None:
        if depth == 0:
            self.root_dir = os.path.dirname(os.path.abspath(path))
        if not os.path.isfile(path):
            raise _err(f"파일을 찾을 수 없음: {path}")
        cur: _Card | None = None
        pending_include = False
        with open(path, "rb") as fh:
            for lineno, raw in enumerate(fh, start=1):
                line = _decode(raw)
                if pending_include:
                    if not line.strip() or line.startswith("#"):
                        continue
                    pending_include = False
                    self._include(line, path, depth, lineno)
                    continue
                if line.startswith("#"):
                    low = line[:8].lower()
                    if low == "#include":
                        if cur is not None:
                            self._finish(cur)
                            cur = None
                        self._include(line[8:], path, depth, lineno)
                    continue
                if line.startswith("/"):
                    if cur is not None:
                        self._finish(cur)
                        cur = None
                    head = line.split()[0] if line.split() else line
                    pieces = [p for p in head.split("/") if p]
                    kw = pieces[0].upper() if pieces else ""
                    if kw == "END":
                        return
                    if kw == "INCLUDE":
                        rest = line.strip()[len("/INCLUDE"):].strip()
                        if rest:
                            self._include(rest, path, depth, lineno)
                        else:
                            pending_include = True
                        continue
                    cur = self._new_card(pieces, path, lineno)
                    continue
                if cur is None:
                    continue
                self._row(cur, line, lineno)
        if cur is not None:
            self._finish(cur)
        if pending_include:
            raise _err(f"/INCLUDE 다음에 경로가 없음: {path}")

    def _include(self, spec: str, src: str, depth: int, lineno: int) -> None:
        orig = _include_spec(spec)
        if not orig:
            raise _err(f"인클루드 경로가 비어 있음 ({src}:{lineno})")
        if depth + 1 > self.max_depth:
            raise _err(f"인클루드 깊이 제한({self.max_depth}) 초과 ({src}:{lineno}): {orig}")
        found, by_base, cands, win_abs, mapped = _resolve_include(orig, self.root_dir, src, self.path_map)
        if found is not None:
            if by_base:
                self.warnings.append(
                    f"인클루드 경로 {orig!r} 를 찾지 못해 파일명으로 대체: {os.path.normpath(found)} "
                    f"({src}:{lineno}) — include_path_map 확인 권장")
            self._enter(found, depth)
            return
        hint = ""
        if win_abs or mapped is not None:
            hint = (" — Windows 절대 경로면 include_path_map={'<드라이브>:/원래/접두': '/리눅스/경로'} 로 매핑하거나 "
                    "include 파일을 rad 폴더에 두십시오"
                    + (f" (매핑 결과 {mapped!r} 도 없음)" if mapped is not None else ""))
        raise _err(f"인클루드 파일을 찾을 수 없음 ({src}:{lineno}): {orig}{hint}")

    def _enter(self, c: str, depth: int) -> None:
        full = os.path.normpath(c)
        self.includes.append(full)
        self.scan(full, depth + 1)

    def _new_card(self, pieces: list[str], path: str, lineno: int) -> _Card:
        kw, sub, hid, unit = _split_header(pieces)
        card = _Card(kw, sub, hid, path, lineno, unit=unit)
        key = _HEADER_ID_KEY.get(kw)
        if key is not None and hid is not None and kw not in _SHELL_KW and kw not in _OTHER_ELEM_KW:
            if hid > self.max_ids[key]:
                self.max_ids[key] = hid
        if kw in _SHELL_KW or kw in _OTHER_ELEM_KW:
            if hid is None:
                raise _err(f"/{kw} 카드에 part_ID 가 없음 ({path}:{lineno})")
        if kw in ("MAT", "PROP", "PART") and hid is not None:
            reg = {"MAT": self.mats, "PROP": self.props, "PART": self.parts}[kw]
            if hid in reg:
                self.warnings.append(f"/{kw} ID {hid} 가 중복 정의됨 — 뒤의 정의 사용 ({path}:{lineno})")
        return card

    def _row(self, c: _Card, line: str, lineno: int) -> None:
        kw = c.kw
        try:
            if kw == "NODE":
                if not line.strip():
                    return
                nid = _i(line[0:10])
                x, y, z = (_f(line[10:30]) or 0.0), (_f(line[30:50]) or 0.0), (_f(line[50:70]) or 0.0)
                self.node_id.append(nid)
                self.node_xyz.extend((x, y, z))
                self.node_unit.append(int(c.unit or 0))
                if nid > self.max_ids["node"]:
                    self.max_ids["node"] = nid
            elif kw in _SHELL_KW:
                if not line.strip():
                    return
                eid = _i(line[0:10])
                n1, n2, n3 = _i(line[10:20]), _i(line[20:30]), _i(line[30:40])
                if kw == "SHELL":
                    n4 = _i(line[40:50]) or 0
                else:
                    n4 = 0
                thk = _f(line[80:100]) if len(line) > 80 else None
                et = 4
                if n4 == 0 or n4 == n3:
                    et, n4 = 3, 0
                if None in (eid, n1, n2, n3):
                    raise ValueError("요소 ID·노드 ID 누락")
                self.sh_int.extend((eid, c.hid, n1, n2, n3, n4))
                self.sh_thk.append(thk if thk is not None else 0.0)
                self.sh_type.append(et)
                if eid > self.max_ids["elem"]:
                    self.max_ids["elem"] = eid
            elif kw in _OTHER_ELEM_KW:
                if not line.strip():
                    return
                eid = _i(line[0:10])
                if eid is not None:
                    self.other_elem_parts[c.hid] = self.other_elem_parts.get(c.hid, 0) + 1
                    if eid > self.max_ids["elem"]:
                        self.max_ids["elem"] = eid
            elif kw in ("PART", "PROP", "MAT", "BEGIN"):
                c.rows.append(line)
        except ValueError as exc:
            raise _err(f"/{kw} 행 해석 실패 ({c.file}:{lineno}): {exc}") from None

    def _finish(self, c: _Card) -> None:
        try:
            if c.kw == "PART" and c.hid is not None:
                rows = c.rows
                title = rows[0][:100].rstrip() if rows else ""
                data = next((r for r in rows[1:] if r.strip()), "")
                self.parts[c.hid] = {
                    "title": title,
                    "prop_id": _i(_cell(data, 0)),
                    "mat_id": _i(_cell(data, 1)),
                    "file": c.file, "line": c.line, "unit": c.unit,
                }
            elif c.kw == "PROP" and c.hid is not None:
                sub = c.sub or ""
                thick = None
                if sub in ("SHELL", "TYPE1") and len(c.rows) >= 4:
                    thick = _f(c.rows[3][20:40])
                self.props[c.hid] = {"type": sub, "thick": thick, "file": c.file, "line": c.line,
                                     "unit": c.unit}
            elif c.kw == "MAT" and c.hid is not None:
                sub = c.sub or ""
                law = _LAW.get(sub)
                ent: dict[str, Any] = {"law": law or sub, "supported": law is not None,
                                       "E": None, "nu": None, "rho": None,
                                       "file": c.file, "line": c.line, "unit": c.unit,
                                       "sub": sub}
                if law is not None:
                    rows = c.rows
                    if len(rows) >= 2:
                        ent["rho"] = _f(rows[1][0:20])
                    if len(rows) >= 3:
                        ent["E"] = _f(rows[2][0:20])
                        ent["nu"] = _f(rows[2][20:40])
                self.mats[c.hid] = ent
            elif c.kw == "BEGIN" and not self.units_label:
                if len(c.rows) >= 3:
                    r = c.rows[2]
                    units = [r[k * 20:(k + 1) * 20].strip() for k in range(3)]
                    self.units_label = " ".join(u for u in units if u)
        except ValueError as exc:
            raise _err(f"/{c.kw}/{c.sub or ''}/{c.hid} 카드 해석 실패 ({c.file}:{c.line}): {exc}") from None


def _resolve_override(material_override: dict | None, mid: int) -> dict | None:
    if not material_override:
        return None
    for k, v in material_override.items():
        try:
            if int(k) == mid:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _valid_E_nu(E: Any, nu: Any) -> bool:
    try:
        E = float(E)
        nu = float(nu)
    except (TypeError, ValueError):
        return False
    return math.isfinite(E) and E > 0 and math.isfinite(nu) and -1.0 < nu < 0.5


def parse_rad(path, part_title, match="exact_ci", max_include_depth=8, material_override=None,
              include_path_map: dict[str, str] | None = None) -> RadModel:
    """Radioss starter 를 읽어 대상 쉘 파트의 RadModel 을 만든다."""
    if match not in ("exact_ci", "exact"):
        raise EslError("CONFIG_INVALID", f"알 수 없는 title 비교 방식: {match}")
    path = os.fspath(path)
    deck = _Deck(max_include_depth, include_path_map)
    deck.scan(path)

    # ---------------- 파트 해석
    want = _norm_title(str(part_title), match)
    hits = [pid for pid, p in deck.parts.items() if _norm_title(p["title"], match) == want]
    if not hits:
        raise EslError("PART_NOT_FOUND", f"title 이 '{part_title}' 인 /PART 가 없음 (파트 {len(deck.parts)}개 검사)")
    if len(hits) > 1:
        raise EslError("PART_AMBIGUOUS", f"title 이 '{part_title}' 인 /PART 가 {len(hits)}개: {sorted(hits)}")
    part_id = hits[0]
    part = deck.parts[part_id]

    if deck.other_elem_parts.get(part_id, 0) > 0:
        raise EslError("UNSUPPORTED_ELEMENT",
                       f"대상 파트 {part_id} 에 쉘이 아닌 요소 {deck.other_elem_parts[part_id]}개가 있음")

    # ---------------- 요소
    sh = np.frombuffer(deck.sh_int, dtype=np.int64).reshape(-1, 6) if len(deck.sh_int) else np.zeros((0, 6), np.int64)
    sel = sh[:, 1] == part_id
    if not np.any(sel):
        raise _err(f"대상 파트 {part_id} 에 /SHELL·/SH3N 요소가 없음")
    sh = sh[sel]
    thk_card = np.frombuffer(deck.sh_thk, dtype=np.float64)[sel]
    etype = np.frombuffer(deck.sh_type, dtype=np.int8)[sel]
    order = np.argsort(sh[:, 0], kind="stable")
    sh, thk_card, etype = sh[order], thk_card[order], etype[order]
    elem_id = sh[:, 0].copy()
    if elem_id.size > 1 and np.any(np.diff(elem_id) == 0):
        raise _err(f"대상 파트에 중복 요소 ID 가 있음: {elem_id[:-1][np.diff(elem_id) == 0][:5].tolist()}")
    conn_ids = sh[:, 2:6].copy()

    # ---------------- 노드 (중복 ID 는 마지막 정의 우선)
    all_nid = np.frombuffer(deck.node_id, dtype=np.int64)
    all_xyz = np.frombuffer(deck.node_xyz, dtype=np.float64).reshape(-1, 3)
    rev_u, rev_idx = np.unique(all_nid[::-1], return_index=True)
    src_idx = all_nid.size - 1 - rev_idx  # rev_u 순서(오름차순)의 마지막 정의 위치
    used = conn_ids[conn_ids > 0]
    node_id = np.unique(used)
    pos = np.searchsorted(rev_u, node_id)
    if rev_u.size == 0:
        missing = np.ones(node_id.size, dtype=bool)
    else:
        missing = rev_u[np.minimum(pos, rev_u.size - 1)] != node_id
    if np.any(missing):
        raise _err(f"요소가 참조하는 노드가 /NODE 에 없음: {node_id[missing][:10].tolist()}")
    x0 = all_xyz[src_idx[pos]].copy()
    conn = np.full((elem_id.size, 4), -1, dtype=np.int64)
    m = conn_ids > 0
    conn[m] = np.searchsorted(node_id, conn_ids[m])
    conn[etype == 3, 3] = -1

    # ---------------- 두께
    prop_id = part["prop_id"]
    prop = deck.props.get(prop_id) if prop_id is not None else None
    thickness = thk_card.copy()
    need = ~(thickness > 0)
    if np.any(need):
        if prop is None:
            raise _err(f"파트 {part_id} 의 속성 /PROP/{prop_id} 가 없음(요소 두께도 없음)")
        if prop["type"] not in ("SHELL", "TYPE1"):
            raise EslError("UNSUPPORTED_ELEMENT",
                           f"파트 {part_id} 속성 /PROP/{prop['type']}/{prop_id} 는 지원하지 않음(/PROP/SHELL 만)")
        if prop["thick"] is None or not prop["thick"] > 0:
            raise _err(f"/PROP/SHELL/{prop_id} 두께(Thick)가 없거나 0 이하")
        thickness[need] = prop["thick"]

    # ---------------- 재료
    mat_id = part["mat_id"]
    mat = deck.mats.get(mat_id) if mat_id is not None else None
    ov = _resolve_override(material_override, mat_id) if mat_id is not None else None
    if ov is not None:
        E, nu = ov.get("E"), ov.get("nu")
        if not _valid_E_nu(E, nu):
            raise EslError("MATERIAL_UNRESOLVED", f"재료 {mat_id} override 의 E·ν 가 유효하지 않음: {ov}")
        rho = ov.get("rho", mat["rho"] if mat else None)
        mrec = {"id": int(mat_id), "law": mat["law"] if mat else "", "E": float(E), "nu": float(nu),
                "rho": None if rho is None else float(rho), "source": "override"}
    else:
        if mat is None:
            raise EslError("MATERIAL_UNRESOLVED", f"파트 {part_id} 의 재료 /MAT/../{mat_id} 가 없음 — material_override 필요")
        if not mat["supported"]:
            raise EslError("MATERIAL_UNRESOLVED",
                           f"재료 {mat_id} 의 law({mat['law']})는 지원하지 않음(LAW1/2/36) — material_override 필요")
        if not _valid_E_nu(mat["E"], mat["nu"]):
            raise EslError("MATERIAL_UNRESOLVED", f"재료 {mat_id} 의 E·ν 를 읽지 못함 — material_override 필요")
        mrec = {"id": int(mat_id), "law": mat["law"], "E": float(mat["E"]), "nu": float(mat["nu"]),
                "rho": mat["rho"], "source": "rad"}

    # ---------------- unit_ID (변환하지 않음 → 경고만)
    unit_warn: list[str] = []

    def _uw(card: str, unit) -> None:
        if unit:
            unit_warn.append(f"UNIT_ID_IGNORED: {card} unit={int(unit)} — 단위 변환 없이 값 그대로 사용")

    _uw(f"/PART/{part_id}", part.get("unit"))
    if prop is not None:
        _uw(f"/PROP/{prop['type']}/{prop_id}", prop.get("unit"))
    if mat is not None and ov is None:
        _uw(f"/MAT/{mat.get('sub') or mat['law']}/{mat_id}", mat.get("unit"))
    if len(deck.node_unit):
        nu_all = np.frombuffer(deck.node_unit, dtype=np.int64)[src_idx[pos]]
        for u in np.unique(nu_all[nu_all != 0]).tolist():
            _uw("/NODE", u)

    ne = elem_id.size
    return RadModel(
        node_id=node_id.astype(np.int64),
        x0=x0.astype(np.float64),
        elem_id=elem_id.astype(np.int64),
        elem_type=etype.astype(np.int8),
        conn=conn,
        elem_pid=np.full(ne, -1 if prop_id is None else prop_id, dtype=np.int64),
        thickness=thickness.astype(np.float64),
        E=np.full(ne, mrec["E"]),
        nu=np.full(ne, mrec["nu"]),
        part_id=int(part_id),
        part_title=part["title"],
        units_label=deck.units_label,
        mats=[mrec],
        max_ids=dict(deck.max_ids),
        includes=list(deck.includes),
        warnings=list(deck.warnings) + unit_warn,
    )


def list_parts(path, max_include_depth=8, include_path_map: dict[str, str] | None = None) -> list[dict]:
    """모든 /PART 의 {id, title, n_elems} (플랫폼 /paths/inspect 용 보조)."""
    deck = _Deck(max_include_depth, include_path_map)
    deck.scan(os.fspath(path))
    sh = np.frombuffer(deck.sh_int, dtype=np.int64).reshape(-1, 6) if len(deck.sh_int) else np.zeros((0, 6), np.int64)
    ids, counts = np.unique(sh[:, 1], return_counts=True)
    cnt = dict(zip(ids.tolist(), counts.tolist()))
    return [{"id": pid, "title": p["title"],
             "n_elems": cnt.get(pid, 0) + deck.other_elem_parts.get(pid, 0)}
            for pid, p in sorted(deck.parts.items())]
