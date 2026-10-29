"""Radioss starter(_0000.rad) 블록 포맷(2017+) 파서.

계약: docs/contracts/esl_core.md §3.1. 대상 파트(쉘) 하나의 메시·두께·재료만 꺼내고,
그 외 키워드는 본문을 건너뛰되 ID만 ``max_ids``에 반영한다.
0.5.2: 2단계 스캔 — 다른 파트 요소 블록은 행 수·최대 ID만, 노드는 대상 요소가 참조하는 것만 좌표 해석
(기존 결과와 동일; 기준 구현 tests/rad/legacy_parser.py).

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
from esl.rad import state as _st

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


def _head_pieces(line: str) -> list[str]:
    """블록 헤더 행 → 조각 목록(계약 esl_cumulative_input.md §3.2, CI-D-3).

    ``#`` 이후는 버리고, 첫 토큰이 ``/`` 로 끝나면 뒤따르는 정수 토큰을 이어 붙인다
    (``/SHELL/         2`` → ``/SHELL/2``, ``.str`` 상태 파일의 오른쪽 정렬 ID). 그 외는 첫 토큰만.
    """
    toks = line.split("#", 1)[0].split()
    if not toks:
        return []
    head = toks[0]
    if head.endswith("/"):
        ints = []
        for t in toks[1:]:
            if not _INT_RE.fullmatch(t):
                break
            ints.append(t)
        if ints:
            head = head + "/".join(ints)
    return [p for p in head.split("/") if p]


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


# 한 줄 바이트 상한(설정 case.rad_max_line_kb, 없으면 이 값). 줄바꿈 없는 거대 파일을 통째로 메모리에 올리지 않게
# readline(상한 + 2) 로 읽고(CRLF 여유), 상한을 넘는 줄이면 rad = RAD_PARSE_ERROR, 상태 파일 = STATE_PARSE_ERROR.
DEFAULT_MAX_LINE_BYTES = 1024 * 1024


def max_line_bytes_of(case_cfg: dict | None) -> int:
    """설정 case 절의 rad_max_line_kb(선택) → 바이트. 없으면 DEFAULT_MAX_LINE_BYTES."""
    kb = (case_cfg or {}).get("rad_max_line_kb") if isinstance(case_cfg, dict) else None
    return int(kb) * 1024 if kb else DEFAULT_MAX_LINE_BYTES


def bounded_readline(fh, path: str, max_line: int | None = None, state: bool = False):
    """``fh.readline`` 대신 쓰는 함수: 한 줄이 max_line 바이트를 넘으면(줄바꿈 없이 상한 + 2 를 채움) EslError."""
    lim = int(max_line or DEFAULT_MAX_LINE_BYTES) + 2
    rl = fh.readline

    def readline() -> bytes:
        raw = rl(lim)
        if len(raw) == lim and raw[-1:] != b"\n":
            code = "STATE_PARSE_ERROR" if state else "RAD_PARSE_ERROR"
            raise EslError(code, f"한 줄이 {lim - 2} 바이트를 넘음({path}, 바이트 위치 {fh.tell() - lim}) — 줄바꿈 없는 "
                                 f"파일이거나 Radioss 입력 형식이 아님(설정 case.rad_max_line_kb)")
        return raw
    return readline


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
    state: dict | None = None          # 누적 씬(상태 파일 include) 정보 — 없으면 None (esl_cumulative_input.md)


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


def _read_include_specs(path: str, max_line: int | None = None) -> list[str] | None:
    """파일의 ``/INCLUDE``·``#include`` 원문 목록(본문 해석 없음). 읽을 수 없거나 한 줄이 상한을 넘으면 None
    (스캐너는 오류를 던지지 않음 — 이 파일 안 include 는 더 따라가지 않고, 본 해석 parse_rad 가 오류를 낸다)."""
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    specs: list[str] = []
    with fh:
        pending = False
        readline = bounded_readline(fh, path, max_line)
        try:
            for raw in _iter_lines(readline):
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
                    pieces = _head_pieces(line)
                    kw = pieces[0].upper() if pieces else ""
                    if kw == "END":
                        break
                    if kw == "INCLUDE":
                        rest = line.strip()[len("/INCLUDE"):].strip()
                        if rest:
                            specs.append(_include_spec(rest))
                        else:
                            pending = True
        except EslError:
            return None
    return specs


def _iter_lines(readline):
    while True:
        raw = readline()
        if not raw:
            return
        yield raw


def scan_includes(rad_path, include_path_map: dict[str, str] | None = None, max_depth: int = 8,
                  max_line_bytes: int | None = None) -> list[str]:
    """본문을 해석하지 않고 ``/INCLUDE``·``#include`` 줄만 따라가 include 파일 경로 목록을 돌려준다.

    출력 폴더 보호(입력 폴더 쓰기 금지)용 가벼운 스캐너. 경로 해석 규칙은 parse_rad 와 같다.
    오류를 던지지 않는다: 읽을 수 없는 파일은 건너뛰고, 찾지 못한 include 는 후보 경로를 그대로
    넣어(그 폴더도 보호) 돌려준다. 순환·깊이 초과는 더 따라가지 않는다.
    """
    out: list[str] = []
    for ref in scan_include_refs(rad_path, include_path_map, max_depth, max_line_bytes=max_line_bytes):
        for p in ([ref["path"]] if ref["found"] else ref["candidates"]):
            if p not in out:
                out.append(p)
    return out


def scan_include_refs(rad_path, include_path_map: dict[str, str] | None = None, max_depth: int = 8,
                      follow=None, max_line_bytes: int | None = None) -> list[dict]:
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
        specs = _read_include_specs(path, max_line_bytes)
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
    state: dict | None = None       # 상태 파일에서 읽은 카드면 그 파일 정보


@dataclass
class _Seg:
    """1차 스캔에서 본문을 해석하지 않고 위치만 기억한 데이터 블록(/NODE, /SHELL·/SH3N)."""
    kw: str
    hid: int | None
    unit: int | None
    file: str
    off: int        # 헤더 다음 행의 바이트 위치
    line0: int      # 헤더 다음 행의 행 번호(1-기준)
    nlines: int     # 블록이 차지하는 물리 행 수(주석·빈 행 포함, 끝 헤더 제외)
    state: bool = False     # 상태 파일(.str/.sta) 블록 — 좌표·요소 우선 규칙(§4)
    sub: str | None = None


_B_HASH = b"#"
_B_SLASH = b"/"
_B_INCLUDE = b"#include"


def _fast_int(raw: bytes) -> int | None:
    """행 첫 I10 셀(ID). 빠른 경로 실패 시 기존 규칙(_i)으로, 그래도 실패하면 None."""
    try:
        return int(raw[0:10])
    except ValueError:
        pass
    try:
        return _i(_decode(raw)[0:10])
    except ValueError:
        return None


class _Deck:
    """2단계 스캔.

    1차(``scan``): 헤더·/PART·/PROP·/MAT·/BEGIN 카드만 읽고, /NODE·/SHELL·/SH3N 블록은 위치(_Seg)만
    기억하며 요소 블록은 숫자 해석 없이 행 수·최대 요소 ID 만 센다. 그 외 키워드 본문은 건너뛴다.
    2차: 대상 파트의 쉘 블록(``load_shells``)과, 그 요소가 참조하는 노드 좌표(``load_nodes``)만 해석.
    /PROP·/MAT 는 원문 행만 보관하고 대상 파트 것만 해석(``prop``·``mat``).
    """

    def __init__(self, max_depth: int, path_map: dict | None = None, max_line: int | None = None):
        self.max_depth = max_depth
        self.max_line = int(max_line or DEFAULT_MAX_LINE_BYTES)
        self.path_map = dict(path_map) if path_map else None
        self.node_segs: list[_Seg] = []
        self.shell_segs: list[_Seg] = []
        self.inishe_segs: list[_Seg] = []
        self.state_files: list[dict] = []
        self.main_begin: list[str] | None = None
        self.sh_state = array("b")
        self.node_state = np.zeros(0, bool)
        self.node_dup = self.node_sdup = 0
        self.shell_count: dict[int, int] = {}
        # 대상 파트 쉘: id, part, n1..n4 (6개씩), 두께, 타입 (load_shells 후)
        self.sh_int = array("q")
        self.sh_thk = array("d")
        self.sh_type = array("b")
        self.other_elem_parts: dict[int, int] = {}
        self.parts: dict[int, dict] = {}
        self.props: dict[int, _Card] = {}
        self.mats: dict[int, _Card] = {}
        self.units_label = ""
        self.max_ids = {k: 0 for k in _MAX_ID_KEYS}
        self.includes: list[str] = []
        self.warnings: list[str] = []
        self.root_dir = ""

    # ------------------------------------------------------------ 1차 스캔
    def scan(self, path: str, depth: int = 0, state: dict | None = None) -> None:
        if depth == 0:
            self.root_dir = os.path.dirname(os.path.abspath(path))
        if not os.path.isfile(path):
            raise _err(f"파일을 찾을 수 없음: {path}")
        cur: _Card | None = None
        pending_include = False
        lineno = 0
        back: bytes | None = None
        with open(path, "rb") as fh:
            readline = bounded_readline(fh, path, self.max_line, state is not None)
            while True:
                if back is not None:
                    raw, back = back, None
                else:
                    raw = readline()
                    if not raw:
                        break
                lineno += 1
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
                    pieces = _head_pieces(line)
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
                    cur.state = state
                    if cur.kw in ("PART", "PROP", "MAT", "BEGIN"):
                        continue
                    # 데이터 블록·기타 키워드: 다음 헤더(또는 #include)까지 빠르게 소비
                    seg = _Seg(cur.kw, cur.hid, cur.unit, path, fh.tell(), lineno + 1, 0,
                               state=state is not None, sub=cur.sub)
                    if cur.kw in _SHELL_KW or cur.kw in _OTHER_ELEM_KW:
                        back, seg.nlines, cnt = self._consume_elems(readline)
                        if cur.kw in _SHELL_KW:
                            self.shell_segs.append(seg)
                            self.shell_count[cur.hid] = self.shell_count.get(cur.hid, 0) + cnt
                            if state is not None:
                                state["kinds_set"].add("geometry")
                        elif cnt:
                            self.other_elem_parts[cur.hid] = self.other_elem_parts.get(cur.hid, 0) + cnt
                    else:
                        back, seg.nlines = self._consume(readline)
                        if cur.kw == "NODE":
                            self.node_segs.append(seg)
                            if state is not None:
                                state["kinds_set"].add("geometry")
                        elif cur.kw == "INISHE":
                            self.inishe_segs.append(seg)
                            if state is not None:
                                state["kinds_set"].add("initial")
                                sub = cur.sub or ""
                                if sub not in state["inishe_subs"]:
                                    state["inishe_subs"].append(sub)
                        elif state is not None and cur.kw.startswith("INI"):
                            name = f"/{cur.kw}/{cur.sub}" if cur.sub else f"/{cur.kw}"
                            if name not in state["other_blocks"]:
                                state["other_blocks"].append(name)
                    lineno += seg.nlines
                    cur = None
                    continue
                if cur is None:
                    continue
                cur.rows.append(line)
        if cur is not None:
            self._finish(cur)
        if pending_include:
            raise _err(f"/INCLUDE 다음에 경로가 없음: {path}")

    @staticmethod
    def _consume(readline) -> tuple[bytes | None, int]:
        """블록 본문을 해석 없이 건너뜀. 반환 (끝낸 행(헤더·#include) | None, 소비한 행 수). readline = bounded_readline."""
        n = 0
        for raw in iter(readline, b""):
            c = raw[:1]
            if c == _B_SLASH or (c == _B_HASH and raw[:8].lower() == _B_INCLUDE):
                return raw, n
            n += 1
        return None, n

    def _consume_elems(self, readline) -> tuple[bytes | None, int, int]:
        """요소 블록: 숫자 해석 없이 요소 행 수(빈·주석 행 제외)와 최대 요소 ID 만 갱신. readline = bounded_readline."""
        n = cnt = 0
        mx = self.max_ids["elem"]
        for raw in iter(readline, b""):
            c = raw[:1]
            if c == _B_HASH:
                if raw[:8].lower() == _B_INCLUDE:
                    self.max_ids["elem"] = mx
                    return raw, n, cnt
                n += 1
                continue
            if c == _B_SLASH:
                self.max_ids["elem"] = mx
                return raw, n, cnt
            n += 1
            try:
                eid = int(raw[0:10])
            except ValueError:
                if not _decode(raw).strip():
                    continue
                eid = _fast_int(raw)
                if eid is None:
                    continue
            cnt += 1
            if eid > mx:
                mx = eid
        self.max_ids["elem"] = mx
        return None, n, cnt

    @staticmethod
    def _seg_iter(fh, seg: _Seg):
        """2차: 블록의 (행 번호, 원문 bytes) — 주석 행 제외(1차에서 센 물리 행 수만큼)."""
        fh.seek(seg.off)
        readline = fh.readline
        lineno = seg.line0 - 1
        for _ in range(seg.nlines):
            raw = readline()
            lineno += 1
            if not raw:
                return
            if raw[:1] != _B_HASH:
                yield lineno, raw

    @staticmethod
    def _line(raw: bytes) -> str:
        # ASCII 행은 _decode 와 같은 결과를 더 싸게
        return raw.decode("ascii").rstrip("\r\n") if raw.isascii() else _decode(raw)

    # ------------------------------------------------------------ 2차: 대상 파트 쉘
    def load_shells(self, part_id: int) -> None:
        files: dict[str, Any] = {}
        try:
            for seg in self.shell_segs:
                if seg.hid != part_id:
                    continue
                fh = files.get(seg.file) or files.setdefault(seg.file, open(seg.file, "rb"))
                c = _Card(seg.kw, None, seg.hid, seg.file, seg.line0 - 1, unit=seg.unit)
                n0 = len(self.sh_type)
                for lineno, raw in self._seg_iter(fh, seg):
                    self._shell_row(c, self._line(raw), lineno)
                self.sh_state.extend([1 if seg.state else 0] * (len(self.sh_type) - n0))
        finally:
            for fh in files.values():
                fh.close()

    def _shell_row(self, c: _Card, line: str, lineno: int) -> None:
        kw = c.kw
        try:
            if not line.strip():
                return
            try:                                     # 빠른 경로(일반 정수 셀); 실패 시 _i 규칙
                eid, n1, n2, n3 = int(line[0:10]), int(line[10:20]), int(line[20:30]), int(line[30:40])
            except ValueError:
                eid, n1, n2, n3 = _i(line[0:10]), _i(line[10:20]), _i(line[20:30]), _i(line[30:40])
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
        except ValueError as exc:
            raise _err(f"/{kw} 행 해석 실패 ({c.file}:{lineno}): {exc}") from None

    # ------------------------------------------------------------ 2차: 참조 노드
    def load_nodes(self, node_id: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """참조 노드(오름차순 고유 ``node_id``)만 좌표 해석 → (xyz (n,3), unit (n,), found (n,) bool).

        중복 ID 는 마지막 정의 우선 — 단 상태 파일(.str) 정의는 rad 정의보다 항상 우선(파일 순서 무관, 계약
        esl_cumulative_input.md §4). 상태 정의 여부는 ``self.node_state``(n,) bool, rad↔상태 중복 수는
        ``self.node_dup``(상태끼리 ``node_sdup``). 모든 /NODE 행의 ID 는 읽어 ``max_ids['node']`` 를 갱신한다.
        """
        n = int(node_id.size)
        want = dict(zip(node_id.tolist(), range(n)))
        X, Y, Z = [0.0] * n, [0.0] * n, [0.0] * n
        U = [0] * n
        seen = bytearray(n)
        src = bytearray(n)              # 1 = 상태 파일 정의
        dup = sdup = 0
        mx = self.max_ids["node"]
        files: dict[str, Any] = {}
        get = want.get
        try:
            for seg in self.node_segs:
                fh = files.get(seg.file) or files.setdefault(seg.file, open(seg.file, "rb"))
                unit = int(seg.unit or 0)
                st = seg.state
                fh.seek(seg.off)
                readline = fh.readline
                for i in range(seg.nlines):        # _seg_iter 를 펼친 형태(노드 행이 가장 많음)
                    raw = readline()
                    if not raw:
                        break
                    if raw[:1] == _B_HASH:
                        continue
                    lineno = seg.line0 + i
                    try:
                        nid = int(raw[0:10])
                    except ValueError:
                        line = _decode(raw)
                        if not line.strip():
                            continue
                        try:
                            nid = _i(line[0:10])
                            if nid is None:
                                raise ValueError("노드 ID 누락")
                        except ValueError as exc:
                            raise _err(f"/NODE 행 해석 실패 ({seg.file}:{lineno}): {exc}") from None
                    if nid > mx:
                        mx = nid
                    k = get(nid)
                    if k is None:
                        continue
                    if seen[k] and (st or src[k]):
                        if src[k] and st:
                            sdup += 1               # 상태 파일끼리: include 순서상 마지막 우선
                        else:
                            dup += 1                # rad ↔ 상태 파일
                            if not st:
                                continue            # 이미 상태 정의 → rad 정의 버림
                    line = self._line(raw)
                    try:
                        try:
                            x, y, z = (float(line[10:30]) or 0.0), (float(line[30:50]) or 0.0), \
                                (float(line[50:70]) or 0.0)
                        except ValueError:
                            x, y, z = (_f(line[10:30]) or 0.0), (_f(line[30:50]) or 0.0), (_f(line[50:70]) or 0.0)
                    except ValueError as exc:
                        raise _err(f"/NODE 행 해석 실패 ({seg.file}:{lineno}): {exc}") from None
                    X[k] = x
                    Y[k] = y
                    Z[k] = z
                    U[k] = unit
                    seen[k] = 1
                    if st:
                        src[k] = 1
        finally:
            for fh in files.values():
                fh.close()
        self.max_ids["node"] = mx
        self.node_state = np.frombuffer(bytes(src), dtype=np.uint8).astype(bool)
        self.node_dup = dup
        self.node_sdup = sdup
        xyz = np.empty((n, 3), dtype=np.float64)
        xyz[:, 0], xyz[:, 1], xyz[:, 2] = X, Y, Z
        return xyz, np.array(U, dtype=np.int64), np.frombuffer(bytes(seen), dtype=np.uint8).astype(bool)

    # ------------------------------------------------------------ include·카드
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
            self._enter(found, depth, orig)
            return
        hint = ""
        if win_abs or mapped is not None:
            hint = (" — Windows 절대 경로면 include_path_map={'<드라이브>:/원래/접두': '/리눅스/경로'} 로 매핑하거나 "
                    "include 파일을 rad 폴더에 두십시오"
                    + (f" (매핑 결과 {mapped!r} 도 없음)" if mapped is not None else ""))
        if _st.has_state_ext(orig):
            raise EslError("STATE_INCLUDE_MISSING",
                           f"누적 해석 상태 파일 include 를 찾을 수 없음 ({src}:{lineno}): {orig} — 이전 낙하 해석 "
                           f"폴더의 .sta/.str 을 함께 두십시오 (후보: {[os.path.normpath(c) for c in cands]}){hint}")
        raise _err(f"인클루드 파일을 찾을 수 없음 ({src}:{lineno}): {orig}{hint}")

    def _enter(self, c: str, depth: int, spec: str = "") -> None:
        full = os.path.normpath(c)
        self.includes.append(full)
        st = None
        by_ext = _st.has_state_ext(full)
        by_head = _st.read_state_header(full, self.max_line)
        if by_ext or by_head:
            st = {"path": full, "spec": spec, "by_header": bool(by_head), "by_ext": bool(by_ext),
                  "kinds_set": set(), "inishe_subs": [], "other_blocks": [], "begin": None,
                  "size": os.path.getsize(full) if os.path.isfile(full) else None}
            self.state_files.append(st)
        self.scan(full, depth + 1, st)

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
                self.props[c.hid] = c          # 해석은 대상 파트 것만(prop())
            elif c.kw == "MAT" and c.hid is not None:
                self.mats[c.hid] = c           # 해석은 대상 파트 것만(mat())
            elif c.kw == "BEGIN" and c.state is not None:
                if c.state.get("begin") is None:
                    c.state["begin"] = list(c.rows)     # 상태 파일 /BEGIN 은 units_label 을 바꾸지 않음(§3.5)
            elif c.kw == "BEGIN" and not self.units_label:
                if self.main_begin is None:
                    self.main_begin = list(c.rows)
                if len(c.rows) >= 3:
                    r = c.rows[2]
                    units = [r[k * 20:(k + 1) * 20].strip() for k in range(3)]
                    self.units_label = " ".join(u for u in units if u)
        except ValueError as exc:
            raise _err(f"/{c.kw}/{c.sub or ''}/{c.hid} 카드 해석 실패 ({c.file}:{c.line}): {exc}") from None

    def prop(self, pid: int) -> dict | None:
        c = self.props.get(pid)
        if c is None:
            return None
        try:
            sub = c.sub or ""
            thick = None
            if sub in ("SHELL", "TYPE1") and len(c.rows) >= 4:
                thick = _f(c.rows[3][20:40])
            return {"type": sub, "thick": thick, "file": c.file, "line": c.line, "unit": c.unit}
        except ValueError as exc:
            raise _err(f"/{c.kw}/{c.sub or ''}/{c.hid} 카드 해석 실패 ({c.file}:{c.line}): {exc}") from None

    def mat(self, mid: int) -> dict | None:
        c = self.mats.get(mid)
        if c is None:
            return None
        try:
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
            return ent
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
              include_path_map: dict[str, str] | None = None, thickness_source: str = "state",
              read_initial: bool = True, max_line_bytes: int | None = None,
              state_max_npt: int = _st.DEFAULT_MAX_NPT, state_max_npg: int = _st.DEFAULT_MAX_NPG) -> RadModel:
    """Radioss starter 를 읽어 대상 쉘 파트의 RadModel 을 만든다.

    누적 씬(include 그래프에 상태 파일 .str/.sta — esl_cumulative_input.md §2): 대상 노드·쉘은 상태 파일 정의
    우선(§4), K_L 두께 = 상태 THK(``thickness_source='prop'`` 이면 원두께, §5), ``read_initial`` 이면
    /INISHE/EPSP_F 를 대상 요소만 해석해 ``RadModel.state['epsp']`` 에 둔다. 상태 파일이 없으면 state=None.
    """
    if thickness_source not in ("state", "prop"):
        raise EslError("CONFIG_INVALID", f"cumulative.thickness_source: {thickness_source}")
    if match not in ("exact_ci", "exact"):
        raise EslError("CONFIG_INVALID", f"알 수 없는 title 비교 방식: {match}")
    path = os.fspath(path)
    deck = _Deck(max_include_depth, include_path_map, max_line_bytes)
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
    deck.load_shells(part_id)           # 2차: 대상 파트 쉘 블록만 숫자 해석

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
    sh_state = np.frombuffer(deck.sh_state, dtype=np.int8)[sel].astype(bool)
    order = np.argsort(sh[:, 0], kind="stable")
    sh, thk_card, etype, sh_state = sh[order], thk_card[order], etype[order], sh_state[order]
    rad_thk = np.where(sh_state, np.nan, thk_card)         # rad 본문 요소 카드 두께(원두께 대체용)
    elem_id = sh[:, 0].copy()
    n_elem_dup = n_elem_sdup = 0
    if elem_id.size > 1 and np.any(np.diff(elem_id) == 0):
        dmask = np.diff(elem_id) == 0
        if not sh_state.any():
            raise _err(f"대상 파트에 중복 요소 ID 가 있음: {elem_id[:-1][dmask][:5].tolist()}")
        # 상태 파일 정의 우선(§4): 같은 ID 묶음에서 상태 행(마지막) 하나만 남김. rad 끼리만 중복이면 기존 오류
        keep = np.ones(elem_id.size, dtype=bool)
        starts = np.flatnonzero(np.r_[True, ~dmask])
        ends = np.r_[starts[1:], elem_id.size]
        multi = np.flatnonzero(ends - starts > 1)
        bad = []
        for gi in multi.tolist():
            a, b = int(starts[gi]), int(ends[gi])
            st_rows = [i for i in range(a, b) if sh_state[i]]
            rd_rows = [i for i in range(a, b) if not sh_state[i]]
            if not st_rows:
                bad.append(int(elem_id[a]))
                continue
            keep[a:b] = False
            keep[st_rows[-1]] = True
            if rd_rows:
                n_elem_dup += 1
                rad_thk[st_rows[-1]] = thk_card[rd_rows[-1]]
            n_elem_sdup += len(st_rows) - 1
        if bad:
            raise _err(f"대상 파트에 중복 요소 ID 가 있음: {bad[:5]}")
        sh, thk_card, etype, sh_state, rad_thk = sh[keep], thk_card[keep], etype[keep], sh_state[keep], rad_thk[keep]
        elem_id = sh[:, 0].copy()
    conn_ids = sh[:, 2:6].copy()

    # ---------------- 노드: 대상 요소가 참조하는 것만 좌표 해석(2차, 중복 ID 는 마지막 정의 우선)
    used = conn_ids[conn_ids > 0]
    node_id = np.unique(used)
    x0, node_unit, found = deck.load_nodes(node_id)
    node_state = deck.node_state
    missing = ~found
    if np.any(missing):
        raise _err(f"요소가 참조하는 노드가 /NODE 에 없음: {node_id[missing][:10].tolist()}")
    conn = np.full((elem_id.size, 4), -1, dtype=np.int64)
    m = conn_ids > 0
    conn[m] = np.searchsorted(node_id, conn_ids[m])
    conn[etype == 3, 3] = -1

    # ---------------- 두께
    prop_id = part["prop_id"]
    prop = deck.prop(prop_id) if prop_id is not None else None
    thickness = thk_card.copy()
    prop_thk = None
    if prop is not None and prop["type"] in ("SHELL", "TYPE1") and prop["thick"] is not None and prop["thick"] > 0:
        prop_thk = float(prop["thick"])
    if deck.state_files and thickness_source == "prop" and prop_thk is not None:
        thickness[sh_state] = prop_thk                  # 교차검증용: 상태 요소도 원두께로 K_L
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
    mat = deck.mat(mat_id) if mat_id is not None else None
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
    if deck.node_segs:
        for u in np.unique(node_unit[node_unit != 0]).tolist():
            _uw("/NODE", u)

    ne = elem_id.size
    st_info = None
    if deck.state_files:
        st_info = _state_summary(deck, elem_id, node_id, node_state, sh_state, thickness, thk_card, rad_thk,
                                 prop_thk, thickness_source, n_elem_dup, n_elem_sdup, read_initial,
                                 (state_max_npt, state_max_npg))
        unit_warn += st_info["warnings"]
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
        state=st_info,
    )


def _top(ids, n=10) -> list[int]:
    return [int(x) for x in np.asarray(ids)[:n].tolist()]


def _state_summary(deck: _Deck, elem_id, node_id, node_state, sh_state, thickness, thk_card, rad_thk, prop_thk,
                   thickness_source, n_elem_dup, n_elem_sdup, read_initial,
                   npt_npg_max: tuple[int, int] = (_st.DEFAULT_MAX_NPT, _st.DEFAULT_MAX_NPG)) -> dict:
    """누적 씬 상태 정보(계약 esl_cumulative_input.md §2~§5). 배열 키(node_from_state 등)는 state.npz 용."""
    warns: list[str] = []
    geo = any("geometry" in f["kinds_set"] for f in deck.state_files)
    files = []
    main_b = _st.begin_values(deck.main_begin) if deck.main_begin else None
    begin_cmp = []
    for f in deck.state_files:
        b = _st.begin_values(f["begin"]) if f["begin"] else None
        rec = {"path": f["path"], "spec": f["spec"], "kinds": sorted(f["kinds_set"]),
               "has_begin": f["begin"] is not None, "runname": b["runname"] if b else None,
               "size": f["size"], "by_header": f["by_header"], "inishe_subs": list(f["inishe_subs"]),
               "other_blocks": list(f["other_blocks"])}
        files.append(rec)
        if b is not None:
            c = _st.compare_begin(main_b, b)
            begin_cmp.append({"path": f["path"], "compared": c["compared"], "same": c["same"],
                              "units_in": b.get("units_in"), "units_work": b.get("units_work")})
            if c["compared"] and c["same"] is False:
                warns.append(f"STATE_UNIT_MISMATCH: 상태 파일 {os.path.basename(f['path'])} /BEGIN 단위 배율 "
                             f"{b.get('units_in')} / {b.get('units_work')} ≠ rad {main_b.get('units_in')} / "
                             f"{main_b.get('units_work')}")
    n_ns = int(np.sum(node_state))
    n_es = int(np.sum(sh_state))
    if deck.node_dup or n_elem_dup or deck.node_sdup or n_elem_sdup:
        warns.append(f"STATE_DUP_DEFINITION: 상태 파일과 rad 에 같은 ID 중복 정의 — 노드 {deck.node_dup}·요소 "
                     f"{n_elem_dup}개(상태 파일 정의 사용), 상태 파일끼리 노드 {deck.node_sdup}·요소 {n_elem_sdup}개"
                     f"(include 순서상 마지막 사용)")
    if geo and (n_ns < node_id.size or n_es < elem_id.size):
        warns.append(f"STATE_PARTIAL: 형상 상태 파일에 대상 파트 노드 {node_id.size - n_ns}/{node_id.size}·요소 "
                     f"{elem_id.size - n_es}/{elem_id.size}개 없음(rad 정의 사용) — 노드 "
                     f"{_top(node_id[~node_state])}, 요소 {_top(elem_id[~sh_state])}")
    # 원두께 t0: /PROP/SHELL Thick → rad 본문 요소 카드 두께
    t0 = np.full(elem_id.size, np.nan)
    if prop_thk is not None:
        t0[:] = prop_thk
    else:
        ok = np.isfinite(rad_thk) & (rad_thk > 0)
        t0[ok] = rad_thk[ok]
    thk_state = np.where(sh_state & (thk_card > 0), thk_card, np.nan)
    th = _st.thickness_stats(elem_id, np.where(sh_state & (thk_card > 0), thk_card, np.nan), t0,
                             sh_state & (thk_card > 0), "state" if n_es else "rad")
    th["k_l_source"] = thickness_source if n_es else "rad"
    epsp = None
    inishe_subs = sorted({x for f in deck.state_files for x in f["inishe_subs"]})
    if read_initial:
        segs = [(sg.file, sg.off, sg.line0, sg.nlines) for sg in deck.inishe_segs
                if sg.state and (sg.sub or "").upper() == "EPSP_F"]
        if segs:
            epsp = _st.read_epsp_f(segs, elem_id, *npt_npg_max)
            miss = ~epsp.has
            if miss.any():
                warns.append(f"STATE_PARTIAL: 초기 상태(/INISHE/EPSP_F)에 대상 요소 {int(miss.sum())}/{elem_id.size}개 "
                             f"없음(이전 소성 0) — {_top(elem_id[miss])}")
            if epsp.n_dup:
                warns.append(f"STATE_DUP_DEFINITION: /INISHE/EPSP_F 같은 SHELLID {epsp.n_dup}개 중복(마지막 사용) — "
                             f"{epsp.dup_ids}")
            if epsp.nonfinite or epsp.width_suspect:
                warns.append(f"STATE_NUMBER_SUSPECT: /INISHE/EPSP_F 숫자 의심 — 비유한값(NaN·Inf) {epsp.nonfinite}개, "
                             f"칸 폭 이상(20자 칸 경계에 공백 없음·붙은 실수) {epsp.width_suspect}개. 값은 기존 규칙대로 "
                             f"사용했으니 상태 파일 출력 형식을 확인하십시오")
    if "STRA_F" in inishe_subs:
        warns.append("STATE_INFO: 이전 총변형률 카드(/INISHE/STRA_F)가 있으나 사용하지 않음(Q1: 이전 소성 = 잔류)")
    thk_mis = None
    if epsp is not None:
        both = epsp.has & sh_state & (thk_card > 0)
        thk_mis = int(np.sum(np.abs(epsp.thk[both] - thk_card[both]) > 1e-4 * np.abs(thk_card[both])))
    src = "state" if n_ns == node_id.size else ("rad" if n_ns == 0 else "state+rad")
    return {
        "files": files, "begin": {"main": main_b, "files": begin_cmp},
        "coord": {"source": src, "n_nodes_state": n_ns, "n_nodes_rad": int(node_id.size - n_ns),
                  "n_dup": int(deck.node_dup), "n_dup_state": int(deck.node_sdup)},
        "elems": {"n_state": n_es, "n_rad": int(elem_id.size - n_es), "n_dup": int(n_elem_dup),
                  "n_dup_state": int(n_elem_sdup)},
        "thickness": th, "thk_sta_mismatch": thk_mis, "inishe_subs": inishe_subs,
        "parse": {"fallback_rows": int(epsp.fallback_rows) if epsp else 0,
                  "resync_lines": int(epsp.resync_lines) if epsp else 0,
                  "n_records": int(epsp.n_records) if epsp else 0,
                  **({"nonfinite": int(epsp.nonfinite), "width_suspect": int(epsp.width_suspect)}
                     if epsp is not None and (epsp.nonfinite or epsp.width_suspect) else {})},
        "warnings": warns, "epsp": epsp,
        "node_from_state": np.asarray(node_state, bool), "elem_from_state": np.asarray(sh_state, bool),
        "thk_state": thk_state, "t0": t0,
    }


def list_parts(path, max_include_depth=8, include_path_map: dict[str, str] | None = None,
               max_line_bytes: int | None = None) -> list[dict]:
    """모든 /PART 의 {id, title, n_elems} (플랫폼 /paths/inspect 용 보조)."""
    deck = _Deck(max_include_depth, include_path_map, max_line_bytes)
    deck.scan(os.fspath(path))          # 요소 블록은 행 수만 셈(숫자 해석 없음)
    return [{"id": pid, "title": p["title"],
             "n_elems": deck.shell_count.get(pid, 0) + deck.other_elem_parts.get(pid, 0)}
            for pid, p in sorted(deck.parts.items())]
