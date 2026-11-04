"""비드 직접 선택·규칙 모핑 코어 (계약 docs/contracts/esl_bead_select.md §4·§5, v0.15.0 S1).

순수 numpy·scipy — DB·외부 명령·파일 쓰기 없음(파일은 호출자 ``stages``). 입력 = (기준 메시 dict ``MESH_KEYS``,
선택 ``SelectionIn``, 고정 노드 ID) 만 — 메시 출처와 무관(BS-D-17, ③ 모핑 전환에서 재사용).

공개 함수(백엔드·워커·S3 공통)
- ``normalize(selection, cfg, *, mesh=None) -> (norm, sha256)`` : SelectionIn 검증·정규화(구간 병합·정렬·기본값, None →
                                              기본값) + 선택 sha. 오류 EslError(SELECT_*), 세부 ``exc.extra`` (백엔드 S2 API)
- ``normalize_input(sel, cfg) -> dict``       : 위의 정규화만(sha 없음)
- ``selection_sha256(norm) -> str``           : 정규화 JSON(정렬 키) sha256 (같은 선택 = 같은 sha, V-BS-9)
- ``mesh_index(mesh) -> MeshIndex``           : 요소 인접 CSR(모서리 공유)·모서리 표·요소 법선·면적·중심(메시 sha 키로 캐시 가능)
- ``derive(mesh, selection, cfg, *, frame, fixed_scan, bead=None) -> dict`` (백엔드 S2 API)
                                              : {beads(§4.2, section·plan 포함), fixed, warnings, slope_suggested, fixed_ab}
- ``derive_obj(mesh, norm, cfg, *, fixed_node_ids=(), …) -> Derived`` : 같은 계산의 객체판(배열 포함 — 워커 기저·시험)
- ``Derived.summary(frame=None) -> dict``     : SelectionDerived JSON(§4.2, section·plan 포함)
- ``params_table(derived, cfg) -> list``      : DoeParamsOut.params 행(matrix.generate 입력, 이름 ``B1_D1``·``B1_W``)
- ``basis(mesh, derived, cfg, *, index=None) -> Basis`` : 변수별 선형 기저 B_v(영향 노드 idx int32 + float64 (n,3))
- ``morph(x0, basis, values) -> ndarray``     : x_d = x0 + Σ (v − v_nom)·B_v (공칭과 같은 변수는 건너뜀 → 비영향 노드 바이트 불변)
- ``fixed_violation(x0, x, fixed_idx, tol)``  : 고정 노드 최대 변위·침범 여부(BS-D-10)
- ``affected_elems(mesh, x0, x)``             : 노드 하나라도 ‖u‖ > 1e-9 mm 인 요소 마스크(§6)
- ``save_basis/load_basis``·``basis_bin``    : basis.npz(결정적)·브라우저용 basis.bin([n:u32][idx:u32×n][vec:f32×3n])
- ``plan_data(mesh, selection, derived, cfg, *, frame) -> dict`` : 평면도 select 판(DoePlanOut 전체 키, §7.1)
- ``elems_of(index, elemset)``·``elemset_of(index, mask)``·``edit_line(index, bead_mask, op)`` : 요소 집합 도구

정의는 계약 §5 를 따른다. 계약과 다르게 정한 점(문서화):
- 폭 기저의 접평면 사영(§5.4 끝): 비드 노드(경계·사면·바닥)는 비드 기준면(법선 n̂_b) 안으로, 블렌딩 노드는 노드 법선
  (``view3d.node_geometry``) 접평면으로 사영 — 경계 노드를 꺾인 노드 법선으로 사영하면 상판 가장자리가 면외로 움직이므로.
- 경계 바깥 방향 ê_j 부호 = 그 노드에 붙은 비드 요소 중심의 반대쪽(무게중심 대신 국부 — 꺾인 경로에서도 정확).
- 국부 폭 w_j 에서 끝단 반직선(경로를 따라 맞은편 끝단에 닿음)은 ``WIDTH_END_RATIO``(설정 ``select.width.end_ratio`` 가
  있으면 그 값) × 중앙값 초과로 제외.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.sparse import linalg as spla
from scipy.spatial import cKDTree

from esl.errors import EslError

SCHEMA_VERSION = 1
BEAD_ID_RE = re.compile(r"^b[1-9][0-9]?$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
U_EPS = 1e-9                       # 영향 판정(§6, mm)
WIDTH_END_RATIO = 2.0              # §5.7 끝단 반직선 제외(국부 폭 중앙값 배수) — 설정 select.width.end_ratio 로 덮어씀(§10 밖 구현 키)
_EPS = 1e-12


def _cfg(cfg: dict | None) -> dict:
    """bead_doe 설정(``settings`` 결과) 또는 select 절 → select 설정(기본값 위)."""
    from esl.doe import DEFAULTS, _deep_merge
    if cfg is None:
        return copy.deepcopy(DEFAULTS["select"])
    if "select" in cfg and isinstance(cfg.get("select"), dict):
        return _deep_merge(DEFAULTS["select"], cfg["select"])
    return _deep_merge(DEFAULTS["select"], cfg)


def _qcfg(cfg: dict | None) -> dict:
    from esl.doe import DEFAULTS
    if cfg is not None and isinstance(cfg.get("compare"), dict) and isinstance(cfg["compare"].get("quality"), dict):
        return cfg["compare"]["quality"]
    return DEFAULTS["compare"]["quality"]


def _bad(code: str, msg: str, **detail):
    e = EslError(code, msg)
    e.extra = detail                    # 백엔드 sel_error 가 오류 세부로 싣는다
    e.detail = detail
    raise e


# ====================================================================== 구간·정규화 (§4.1)
def ranges_from_ids(ids) -> list[list[int]]:
    """정수 ID → 정렬·병합 닫힌 구간 [[first, last], …] (인접 병합)."""
    a = np.unique(np.asarray(ids, dtype=np.int64).ravel())
    if a.size == 0:
        return []
    brk = np.flatnonzero(np.diff(a) != 1)
    starts = np.concatenate([[0], brk + 1])
    ends = np.concatenate([brk, [a.size - 1]])
    return [[int(a[s]), int(a[e])] for s, e in zip(starts, ends)]


def ids_from_ranges(r) -> np.ndarray:
    if not r:
        return np.zeros(0, np.int64)
    parts = [np.arange(int(f), int(l) + 1, dtype=np.int64) for f, l in r]
    return np.unique(np.concatenate(parts))


def _norm_ranges(r, where: str, max_ids: int) -> list[list[int]]:
    if r is None:
        return []
    if not isinstance(r, list):
        _bad("SELECT_ELEM_UNKNOWN", f"{where}: 구간 목록이어야 함", n=0, first=None)
    pairs, total = [], 0
    for x in r:
        if (not isinstance(x, (list, tuple)) or len(x) != 2 or any(isinstance(v, bool) or not isinstance(v, int)
                                                                     for v in x)):
            _bad("SELECT_ELEM_UNKNOWN", f"{where}: 구간은 [first, last] 정수", n=0, first=None)
        f, l = int(x[0]), int(x[1])
        if f < 1 or l < f:
            _bad("SELECT_ELEM_UNKNOWN", f"{where}: 구간 [{f}, {l}] 는 1 ≤ first ≤ last", n=1, first=f)
        total += l - f + 1
        if total > max_ids:
            _bad("SELECT_TOO_LARGE", f"{where}: 요소 수가 상한 {max_ids} 초과")
        pairs.append((f, l))
    pairs.sort()
    out: list[list[int]] = []
    for f, l in pairs:                                # 겹침·인접 병합
        if out and f <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], l)
        else:
            out.append([f, l])
    return out


def _norm_set(s, where: str, max_ids: int) -> dict:
    if s is None:
        s = {}
    if not isinstance(s, dict) or set(s) - {"q", "t"}:
        _bad("SELECT_ELEM_UNKNOWN", f"{where}: ElemSet 은 {{q, t}}", n=0, first=None)
    return {"q": _norm_ranges(s.get("q"), where, max_ids), "t": _norm_ranges(s.get("t"), where, max_ids)}


def _set_count(s: dict) -> int:
    return sum(l - f + 1 for k in ("q", "t") for f, l in s[k])


def normalize_input(sel, cfg: dict | None = None) -> dict:
    """SelectionIn → 정규화 dict(결정적). 오류 코드: SELECT_BEAD_ID_INVALID·SELECT_NAME_INVALID·SELECT_EMPTY_TIER·
    SELECT_TIERS_GAP·SELECT_LINK_INVALID·SELECT_OVERLAP·SELECT_ELEM_UNKNOWN(형식)·SELECT_TOO_LARGE(413)."""
    sc = _cfg(cfg)
    if not isinstance(sel, dict):
        _bad("SELECT_EMPTY_TIER", "선택은 객체")
    if sel.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        _bad("SELECT_EMPTY_TIER", f"schema_version 은 {SCHEMA_VERSION}")
    max_ids = 10_000_000
    fa = sel.get("feature_angle_deg")
    if fa is None:
        fa = sc["feature_angle_deg"]
    if isinstance(fa, bool) or not isinstance(fa, (int, float)) or not 1.0 <= float(fa) <= 45.0:
        _bad("SELECT_EMPTY_TIER", f"feature_angle_deg 는 1..45 (값 {fa!r})")
    beads = sel.get("beads")
    if not isinstance(beads, list) or not 1 <= len(beads) <= int(sc["max_beads"]):
        _bad("SELECT_EMPTY_TIER", f"beads 는 1..{sc['max_beads']} 개")
    seen = set()
    out_beads = []
    for b in beads:
        if not isinstance(b, dict):
            _bad("SELECT_BEAD_ID_INVALID", "비드 항목은 객체")
        bid = b.get("id")
        if not isinstance(bid, str) or not BEAD_ID_RE.match(bid) or int(bid[1:]) > int(sc["max_beads"]) or bid in seen:
            _bad("SELECT_BEAD_ID_INVALID", f"비드 id {bid!r} 는 b1..b{sc['max_beads']} 고유")
        seen.add(bid)
        name = b.get("name")
        if name is None:
            name = f"B{bid[1:]}"
        if not isinstance(name, str) or not 1 <= len(name) <= 32 or _CTRL_RE.search(name):
            _bad("SELECT_NAME_INVALID", f"{bid}: 이름은 1..32자, 제어문자 금지")
        tiers = b.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            _bad("SELECT_EMPTY_TIER", f"{bid}: 단(tiers)이 1개 이상 필요", bead=bid)
        tl = []
        for t in tiers:
            if not isinstance(t, dict) or isinstance(t.get("k"), bool) or not isinstance(t.get("k"), int):
                _bad("SELECT_TIERS_GAP", f"{bid}: 단 번호 k 는 정수", bead=bid)
            fl = _norm_set(t.get("floor"), f"{bid} 단 {t['k']}", max_ids)
            if _set_count(fl) < 1:
                _bad("SELECT_EMPTY_TIER", f"{bid}: 단 {t['k']} 바닥 요소가 없음", bead=bid, tier=t["k"])
            tl.append({"k": int(t["k"]), "floor": fl})
        tl.sort(key=lambda t: t["k"])
        ks = [t["k"] for t in tl]
        if ks != list(range(1, len(ks) + 1)) or len(ks) > int(sc["max_tiers"]):
            _bad("SELECT_TIERS_GAP", f"{bid}: 단 번호는 1..{sc['max_tiers']} 연속 (값 {ks})", bead=bid)
        sl = b.get("slope") or {}
        if not isinstance(sl, dict) or sl.get("mode", "auto") not in ("auto", "edited"):
            _bad("SELECT_EMPTY_TIER", f"{bid}: slope.mode 는 auto|edited", bead=bid)
        slope = {"mode": sl.get("mode", "auto"), "add": _norm_set(sl.get("add"), f"{bid} 사면 add", max_ids),
                 "remove": _norm_set(sl.get("remove"), f"{bid} 사면 remove", max_ids)}
        bm = b.get("blend_mm")
        bm = "auto" if bm is None else bm
        if bm != "auto":
            if isinstance(bm, bool) or not isinstance(bm, (int, float)) or not 0.0 <= float(bm) <= float(
                    sc["blend"]["max_mm"]):
                _bad("SELECT_EMPTY_TIER", f"{bid}: blend_mm 는 auto 또는 0..{sc['blend']['max_mm']}", bead=bid)
            bm = float(bm)
        ff = b.get("floor_follow")
        if ff is None:
            ff = int(sc["width"]["floor_follow"])
        if ff not in (0, 1) or isinstance(ff, bool):
            _bad("SELECT_EMPTY_TIER", f"{bid}: floor_follow 는 0|1", bead=bid)
        links = b.get("links") or []
        if not isinstance(links, list):
            _bad("SELECT_LINK_INVALID", f"{bid}: links 는 목록", bead=bid)
        used, ln = set(), []
        for g in links:
            if (not isinstance(g, list) or len(g) < 2 or any(isinstance(k, bool) or not isinstance(k, int) for k in g)
                    or len(set(g)) != len(g) or any(k not in ks for k in g) or used & set(g)):
                _bad("SELECT_LINK_INVALID", f"{bid}: 묶음 {g!r} 는 서로 다른 단 번호 2개 이상, 겹침 없음", bead=bid)
            used |= set(g)
            ln.append(sorted(int(k) for k in g))
        ln.sort()
        out_beads.append({"id": bid, "name": name, "tiers": tl, "slope": slope, "blend_mm": bm,
                          "floor_follow": int(ff), "links": ln})
    out_beads.sort(key=lambda b: int(b["id"][1:]))
    norm = {"schema_version": SCHEMA_VERSION, "feature_angle_deg": float(fa), "beads": out_beads,
            "fixed_user": _norm_set(sel.get("fixed_user"), "fixed_user", max_ids),
            "exclude": _norm_set(sel.get("exclude"), "exclude", max_ids)}
    # 겹침(한 요소 = 최대 1 비드·1 층) — 사면 add 는 층(remove 는 편집 표지라 제외)
    for typ in ("q", "t"):
        arrs, owner = [], []
        for b in out_beads:
            for t in b["tiers"]:
                a = ids_from_ranges(t["floor"][typ])
                arrs.append(a)
                owner.append(b["id"])
            a = ids_from_ranges(b["slope"]["add"][typ])
            arrs.append(a)
            owner.append(b["id"])
        if arrs:
            allv = np.concatenate(arrs) if arrs else np.zeros(0, np.int64)
            u, cnt = np.unique(allv, return_counts=True)
            if (cnt > 1).any():
                dup = u[cnt > 1]
                bead = next(o for a, o in zip(arrs, owner) if np.isin(dup[:1], a).any())
                _bad("SELECT_OVERLAP", f"요소 {int(dup[0])}({typ}) 등 {dup.size}개가 여러 비드·층에 겹침", bead=bead,
                     elems_n=int(dup.size))
    js = canonical_json(norm)
    if len(js) > int(sc["max_selection_kb"]) * 1024:
        _bad("SELECT_TOO_LARGE", f"정규화 선택 {len(js) // 1024} KB > 상한 {sc['max_selection_kb']} KB")
    return norm


def normalize(selection, cfg: dict | None = None, *, mesh: dict | None = None) -> tuple[dict, str]:
    """(백엔드·워커 공통 API) SelectionIn → (정규화 선택, sha256). mesh(MESH_KEYS)를 주면 요소 ID 존재 검사
    (SELECT_ELEM_UNKNOWN{n, first}). 실패 = EslError(SELECT_*), 세부 = ``exc.extra``."""
    norm = normalize_input(selection, cfg)
    if mesh is not None:
        check_elems(mesh, norm)
    return norm, selection_sha256(norm)


def check_elems(mesh: dict, norm: dict) -> None:
    """선택의 모든 요소 ID 가 기준 메시에 있는지(인접 색인 없이 ID 표만)."""
    eid = np.asarray(mesh["elem_id"], dtype=np.int64)
    q = np.asarray(mesh["elem_type"]).astype(int) == 4
    have = {"q": np.unique(eid[q]), "t": np.unique(eid[~q])}
    sets = [("fixed_user", norm["fixed_user"]), ("exclude", norm["exclude"])]
    for b in norm["beads"]:
        sets += [(f"{b['id']} 단 {t['k']}", t["floor"]) for t in b["tiers"]]
        sets += [(f"{b['id']} 사면 add", b["slope"]["add"]), (f"{b['id']} 사면 remove", b["slope"]["remove"])]
    for where, es in sets:
        for typ in ("q", "t"):
            ids = ids_from_ranges(es.get(typ) or [])
            if ids.size == 0:
                continue
            bad = ids[~np.isin(ids, have[typ])]
            if bad.size:
                _bad("SELECT_ELEM_UNKNOWN", f"{where}: 기준 메시에 없는 요소 ID {int(bad[0])}({typ}) 등 {bad.size}개",
                     n=int(bad.size), first=int(bad[0]))


def canonical_json(norm: dict) -> bytes:
    return json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def selection_sha256(norm: dict) -> str:
    return hashlib.sha256(canonical_json(norm)).hexdigest()


# ====================================================================== 메시 색인 (§5.1)
class MeshIndex:
    """요소 인접 CSR(int32)·모서리 표·요소 기하. 노드 인덱스 기반(ID 아님)."""

    def __init__(self, mesh: dict):
        X = np.asarray(mesh["x0"], dtype=np.float64)
        C = np.asarray(mesh["conn"], dtype=np.int64)
        et = np.asarray(mesh["elem_type"]).astype(np.int64)
        self.n_nodes, self.n_elems = int(X.shape[0]), int(C.shape[0])
        self.is_quad = et == 4
        self.nv = np.where(self.is_quad, 4, 3)
        self.elem_id = np.asarray(mesh["elem_id"], dtype=np.int64)
        self.node_id = np.asarray(mesh["node_id"], dtype=np.int64)
        c4 = C[:, :4].copy() if C.shape[1] >= 4 else np.column_stack([C, C[:, :1]])
        c4[~self.is_quad, 3] = c4[~self.is_quad, 0]
        self.conn = c4
        # 모서리
        e_list, own = [], []
        for i in range(4):
            m = np.ones(self.n_elems, bool) if i < 3 else self.is_quad     # 3각: (0,1)(1,2)(2,0=열3)
            e_list.append(np.column_stack([c4[m, i], c4[m, (i + 1) % 4]]))
            own.append(np.flatnonzero(m))
        E = np.concatenate(e_list)
        O = np.concatenate(own)
        lo, hi = np.minimum(E[:, 0], E[:, 1]), np.maximum(E[:, 0], E[:, 1])
        key = lo * (1 << 32) + hi
        order = np.lexsort((O, key))
        key, O, lo, hi = key[order], O[order], lo[order], hi[order]
        start = np.flatnonzero(np.concatenate([[True], key[1:] != key[:-1]]))
        self.edge_nodes = np.column_stack([lo[start], hi[start]])          # (U,2)
        self.edge_ptr = np.concatenate([start, [key.size]]).astype(np.int64)
        self.edge_elems = O.astype(np.int64)                               # 모서리별 요소(CSR)
        cnt = np.diff(self.edge_ptr)
        self.edge_count = cnt
        # 요소 인접(공유 모서리 — 3개 이상 공유도 이웃)
        rows, cols = [], []
        two = np.flatnonzero(cnt == 2)
        a0, a1 = O[self.edge_ptr[two]], O[self.edge_ptr[two] + 1]
        rows += [a0, a1]
        cols += [a1, a0]
        for u in np.flatnonzero(cnt > 2):
            g = O[self.edge_ptr[u]:self.edge_ptr[u + 1]]
            ii, jj = np.meshgrid(g, g)
            m = ii != jj
            rows.append(ii[m])
            cols.append(jj[m])
        r = np.concatenate(rows) if rows else np.zeros(0, np.int64)
        cc = np.concatenate(cols) if cols else np.zeros(0, np.int64)
        A = sparse.csr_matrix((np.ones(r.size, np.int8), (r, cc)), shape=(self.n_elems, self.n_elems))
        A.sum_duplicates()
        A.indices = A.indices.astype(np.int32)
        A.indptr = A.indptr.astype(np.int32) if A.nnz < 2 ** 31 else A.indptr
        self.adj = A
        self.refresh(X)

    def refresh(self, X: np.ndarray) -> None:
        """기하 갱신(좌표만 — 위상 불변)."""
        self.X = np.asarray(X, dtype=np.float64)
        c4 = self.conn
        a, b, c, d = (self.X[c4[:, i]] for i in range(4))
        w = np.cross(b - a, c - a)
        q = self.is_quad
        if q.any():
            w[q] = np.cross(c[q] - a[q], d[q] - b[q])
        nrm = np.linalg.norm(w, axis=1)
        self.area = 0.5 * nrm
        self.normal = w / np.maximum(nrm, 1e-300)[:, None]
        cen = (a + b + c)
        cen[q] += d[q]
        self.centroid = cen / self.nv[:, None]
        el = np.linalg.norm(self.X[self.edge_nodes[:, 0]] - self.X[self.edge_nodes[:, 1]], axis=1)
        self.edge_len = el
        self.h_med = float(np.median(el)) if el.size else 1.0

    # ------------------------------------------------------------------ 집합 도구
    def elem_nodes(self, mask: np.ndarray) -> np.ndarray:
        """요소 마스크 → 노드 인덱스(정렬 unique)."""
        e = np.flatnonzero(mask)
        if e.size == 0:
            return np.zeros(0, np.int64)
        c = self.conn[e]
        return np.unique(np.concatenate([c[:, :3].ravel(), c[self.is_quad[e], 3]]))

    def node_count(self, mask: np.ndarray) -> np.ndarray:
        """노드별 마스크 요소 수."""
        e = np.flatnonzero(mask)
        cnt = np.zeros(self.n_nodes, np.int64)
        c = self.conn[e]
        for i in range(3):
            cnt += np.bincount(c[:, i], minlength=self.n_nodes)
        cnt += np.bincount(c[self.is_quad[e], 3], minlength=self.n_nodes)
        return cnt

    def edge_in_count(self, mask: np.ndarray) -> np.ndarray:
        """모서리별 마스크 요소 수."""
        v = mask[self.edge_elems].astype(np.int64)
        return np.add.reduceat(v, self.edge_ptr[:-1]) if v.size else np.zeros(0, np.int64)


def mesh_index(mesh: dict) -> MeshIndex:
    return MeshIndex(mesh)


def _elem_lookup(index: MeshIndex):
    if not hasattr(index, "_lookup"):
        tbl = {}
        for typ, m in (("q", index.is_quad), ("t", ~index.is_quad)):
            idx = np.flatnonzero(m)
            ids = index.elem_id[idx]
            o = np.argsort(ids, kind="stable")
            tbl[typ] = (ids[o], idx[o])
        index._lookup = tbl
    return index._lookup


def elems_of(index: MeshIndex, es: dict, *, where: str = "") -> np.ndarray:
    """ElemSet → 요소 마스크. 없는 ID → SELECT_ELEM_UNKNOWN{n, first}."""
    tbl = _elem_lookup(index)
    mask = np.zeros(index.n_elems, bool)
    for typ in ("q", "t"):
        ids = ids_from_ranges(es.get(typ) or [])
        if ids.size == 0:
            continue
        sid, sidx = tbl[typ]
        pos = np.searchsorted(sid, ids)
        ok = (pos < sid.size) & (sid[np.minimum(pos, max(sid.size - 1, 0))] == ids) if sid.size else np.zeros(ids.size,
                                                                                                                bool)
        if not ok.all():
            bad = ids[~ok]
            _bad("SELECT_ELEM_UNKNOWN", f"{where}: 기준 메시에 없는 요소 ID {int(bad[0])}({typ}) 등 {bad.size}개",
                 n=int(bad.size), first=int(bad[0]))
        mask[sidx[pos]] = True
    return mask


def elemset_of(index: MeshIndex, mask: np.ndarray) -> dict:
    """요소 마스크 → ElemSet(구간 압축)."""
    m = np.asarray(mask, bool)
    return {"q": ranges_from_ids(index.elem_id[m & index.is_quad]), "t": ranges_from_ids(index.elem_id[m & ~index.is_quad])}


def edit_line(index: MeshIndex, bead_mask: np.ndarray, op: str) -> np.ndarray:
    """±1줄(§5.2-6, 브라우저와 같은 규칙): op '+' = 비드 밖 요소 중 경계 노드를 쓰는 요소(사면 add 후보),
    '-' = 비드 요소 중 경계 노드를 쓰는 요소(사면 remove 후보 — 호출자가 바닥 제외)."""
    bm = np.asarray(bead_mask, bool)
    bnd = (index.node_count(bm) > 0) & (index.node_count(~bm) > 0)
    use = bnd[index.conn].any(axis=1)
    return use & (~bm if op == "+" else bm)


# ====================================================================== derive (§5.1·5.2·5.6·5.7)
class BeadDerived:
    """비드 1개 재계산 결과(배열 + 요약)."""

    def __init__(self, bid: str, name: str):
        self.id, self.name = bid, name
        self.warnings: list[dict] = []


class Derived:
    def __init__(self, norm: dict, sha: str, beads: list, fixed: dict, warnings: list, index: MeshIndex,
                 mesh_sha256: str | None):
        self.norm, self.sha256, self.beads, self.fixed, self.warnings = norm, sha, beads, fixed, warnings
        self.index, self.mesh_sha256 = index, mesh_sha256

    def bead(self, bid: str) -> BeadDerived:
        return next(b for b in self.beads if b.id == bid)

    def summary(self, frame: dict | None = None, *, rev: int | None = None, with_figures: bool = True) -> dict:
        """SelectionDerived(§4.2). frame 이 있으면 plan(ring_ab·e_ab) 포함, with_figures False 면 section·plan 제외(DB 요약)."""
        out = []
        for b in self.beads:
            r = {"id": b.id, "name": b.name, "n_elems": int(b.bead_mask.sum()), "n_nodes": int(b.bead_nodes.size),
                 "tiers": [{"k": t["k"], "n_elems": int(t["mask"].sum()), "D_nom": _r(t["D_nom"]),
                            "normal": [_r(v, 9) for v in t["normal"]], "planarity_mm": _r(t["planarity"])}
                           for t in b.tiers],
                 "slope": {"n_elems": int(b.slope_mask.sum()), "elems": elemset_of(self.index, b.slope_mask),
                           "suggested_n": int(b.slope_auto.sum()), "edited": b.edited},
                 "boundary": {"loops": [{"closed": lp["closed"], "n_nodes": int(lp["nodes"].size),
                                         "length_mm": _r(lp["length"])} for lp in b.loops],
                              "n_nodes": int(b.boundary_nodes.size)},
                 "W_nom": _r(b.W_nom), "W_min": _r(b.W_min), "W_max": _r(b.W_max), "sense": b.sense,
                 "blend_mm": _r(b.blend_mm), "blend_clipped": b.blend_clipped,
                 "fixed_in_bead_n": b.fixed_in_bead_n, "fixed_in_blend_n": b.fixed_in_blend_n,
                 "range_default": b.range_default, "warnings": b.warnings,
                 "w_enabled": b.w_enabled, "floor_follow": b.floor_follow}
            if with_figures:
                r["section"] = b.section
                if frame is not None:
                    r["plan"] = _plan_bead(self.index, frame, b)
            out.append(r)
        doc = {"rev": rev, "sha256": self.sha256, "mesh_sha256": self.mesh_sha256, "beads": out, "fixed": self.fixed,
               "warnings": self.warnings}
        return doc

    def slope_suggested(self) -> dict:
        return {b.id: elemset_of(self.index, b.slope_auto) for b in self.beads}


def _r(v, nd: int = 4):
    if v is None:
        return None
    f = float(v)
    if not math.isfinite(f):
        return None
    r = round(f, nd)
    return 0.0 if r == 0 else r


def _orient(normals: np.ndarray, ref: np.ndarray) -> np.ndarray:
    s = np.where(normals @ ref < 0, -1.0, 1.0)
    return normals * s[:, None]


def _mean_normal(index: MeshIndex, mask: np.ndarray, ref: np.ndarray | None = None) -> np.ndarray:
    e = np.flatnonzero(mask)
    n = index.normal[e]
    if ref is None:
        ref = n[int(np.argmax(index.area[e]))] if e.size else np.array([0.0, 0.0, 1.0])
    v = (_orient(n, ref) * index.area[e][:, None]).sum(axis=0)
    nn = np.linalg.norm(v)
    return v / nn if nn > _EPS else np.asarray(ref, dtype=np.float64)


def _loops(index: MeshIndex, bead_mask: np.ndarray) -> tuple[list[dict], bool]:
    """경계 모서리(비드 1 + 밖 1 이상) 고리. 반환 ([{nodes(idx 순서), closed}], 자유 모서리 존재)."""
    nin = index.edge_in_count(bead_mask)
    nout = index.edge_count - nin
    bedge = (nin >= 1) & (nout >= 1)
    free = (nin >= 1) & (index.edge_count == 1)
    E = index.edge_nodes[bedge]
    if E.size == 0:
        return [], bool(free.any())
    # 노드 → 이웃(경계 그래프)
    nodes = np.unique(E.ravel())
    pos = {int(v): i for i, v in enumerate(nodes.tolist())}
    nbr: list[list[int]] = [[] for _ in nodes]
    for a, b in E.tolist():
        nbr[pos[a]].append(b)
        nbr[pos[b]].append(a)
    for lst in nbr:
        lst.sort()
    used_edge = set()
    loops = []
    # 시작 = 끝점(차수 1) 먼저(열린 사슬), 그다음 최소 노드
    deg = np.array([len(x) for x in nbr])
    order = list(nodes[deg == 1]) + list(nodes[deg != 1])
    for s in order:
        s = int(s)
        avail = [b for b in nbr[pos[s]] if (min(s, b), max(s, b)) not in used_edge]
        if not avail:
            continue
        chain = [s]
        cur, nxt = s, avail[0]
        closed = False
        while True:
            used_edge.add((min(cur, nxt), max(cur, nxt)))
            if nxt == s:
                closed = True
                break
            chain.append(nxt)
            cand = [b for b in nbr[pos[nxt]] if (min(nxt, b), max(nxt, b)) not in used_edge]
            if not cand:
                break
            cur, nxt = nxt, cand[0]
        loops.append({"nodes": np.asarray(chain, np.int64), "closed": closed})
    return loops, bool(free.any())


def _plane(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    p = X.mean(axis=0)
    if X.shape[0] < 3:
        return p, np.array([0.0, 0.0, 1.0]), 0.0
    _, s, vt = np.linalg.svd(X - p, full_matrices=False)
    m = vt[-1]
    rms = float(np.sqrt(np.mean(((X - p) @ m) ** 2)))
    return p, m / np.linalg.norm(m), rms


def _basis2(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = a - (a @ n) * n
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def _node_graph(index: MeshIndex, emask: np.ndarray) -> sparse.csr_matrix:
    """요소 마스크의 모서리 그래프(가중 = 모서리 길이, 노드 인덱스 전체 크기)."""
    nin = index.edge_in_count(emask)
    sel = nin >= 1
    E = index.edge_nodes[sel]
    w = np.maximum(index.edge_len[sel], 1e-9)
    n = index.n_nodes
    G = sparse.csr_matrix((np.concatenate([w, w]), (np.concatenate([E[:, 0], E[:, 1]]),
                                                    np.concatenate([E[:, 1], E[:, 0]]))), shape=(n, n))
    return G


def _dist_from(G: sparse.csr_matrix, sub: np.ndarray, src: np.ndarray) -> np.ndarray:
    """sub(노드 인덱스) 부분 그래프에서 src(전역 인덱스) 다중 출발 최단거리 → sub 순서 배열."""
    if src.size == 0:
        return np.full(sub.size, np.inf)
    loc = np.searchsorted(sub, src)
    Gs = G[sub][:, sub]
    d = csgraph.dijkstra(Gs, directed=False, indices=loc, min_only=True)
    return np.asarray(d, dtype=np.float64)


def derive(mesh: dict, selection: dict, cfg: dict | None = None, *, frame: dict | None = None, fixed_scan=(),
           bead: str | None = None, index: MeshIndex | None = None) -> dict:
    """(백엔드 API) 정규화 선택 → {beads: [BeadDerived §4.2 — section·plan 포함], fixed{scan_n, user_n, source},
    warnings, slope_suggested{bead: ElemSet}, fixed_ab[{a, b}]}. rev·sha256·mesh_sha256 은 호출자가 붙인다.
    bead 를 주면 그 비드만 계산(다른 비드 층은 침범 금지로만 씀). 결정적."""
    if isinstance(selection, dict) and "schema_version" not in selection:
        selection = normalize_input(selection, cfg)
    D = derive_obj(mesh, selection, cfg, fixed_node_ids=fixed_scan, index=index, only=bead)
    doc = D.summary(frame)
    for k in ("rev", "sha256", "mesh_sha256"):
        doc.pop(k, None)
    doc["slope_suggested"] = D.slope_suggested()
    doc["fixed_ab"] = _fixed_ab(D, frame) if frame is not None else []
    return doc


def _fixed_ab(D: "Derived", frame: dict) -> list:
    from esl.opt.keepout import project_ab
    fm = D.fixed_mask
    if not fm.any():
        return []
    return [{"a": a, "b": b} for a, b in project_ab(frame, D.index.X[fm]).round(3).tolist()]


def derive_obj(mesh: dict, norm: dict, cfg: dict | None = None, *, fixed_node_ids=(), index: MeshIndex | None = None,
               with_section: bool = True, mesh_sha256: str | None = None, only: str | None = None) -> Derived:
    """선택(정규화) → Derived 객체(배열 포함, 결정적 — 워커 기저·시험용). cfg = bead_doe 설정(``settings``) — select 절."""
    sc = _cfg(cfg)
    ix = index or mesh_index(mesh)
    theta = float(norm["feature_angle_deg"])
    cos_t = math.cos(math.radians(theta))
    h = ix.h_med
    # 고정 노드
    nid = ix.node_id
    o = np.argsort(nid, kind="stable")
    fixed_scan = np.zeros(ix.n_nodes, bool)
    fids = np.asarray(list(fixed_node_ids), dtype=np.int64)
    if fids.size:
        p = np.searchsorted(nid[o], fids)
        ok = (p < nid.size) & (nid[o][np.minimum(p, nid.size - 1)] == fids)
        fixed_scan[o[p[ok]]] = True
    fu_mask = elems_of(ix, norm["fixed_user"], where="fixed_user")
    fixed_user = np.zeros(ix.n_nodes, bool)
    fixed_user[ix.elem_nodes(fu_mask)] = True
    fixed = fixed_scan | fixed_user
    src = ("scan+user" if fixed_scan.any() and fixed_user.any() else "scan" if fixed_scan.any()
           else "user" if fixed_user.any() else "none")
    excl = elems_of(ix, norm["exclude"], where="exclude")
    # 비드별 바닥·add 마스크(다른 비드 침범 금지)
    floors, adds = {}, {}
    for b in norm["beads"]:
        floors[b["id"]] = [elems_of(ix, t["floor"], where=f"{b['id']} 단 {t['k']}") for t in b["tiers"]]
        adds[b["id"]] = elems_of(ix, b["slope"]["add"], where=f"{b['id']} 사면 add")
    taken = np.zeros(ix.n_elems, bool)
    for b in norm["beads"]:
        for m in floors[b["id"]]:
            taken |= m
        taken |= adds[b["id"]]
    warns: list[dict] = []
    if (fu_mask & taken).any():
        warns.append({"code": "SELECT_FIXED_LAYER_OVERLAP", "n": int((fu_mask & taken).sum())})
    beads = []
    bead_owner = np.full(ix.n_elems, -1, np.int64)
    if only is not None and only not in {b["id"] for b in norm["beads"]}:
        _bad("SELECT_BEAD_ID_INVALID", f"선택에 없는 비드 {only!r}")
    for bi, b in enumerate(norm["beads"]):
        if only is not None and b["id"] != only:
            continue
        bd = _derive_bead(ix, b, floors[b["id"]], adds[b["id"]], taken, excl, bead_owner, fixed, sc, cos_t, h, mesh)
        bead_owner[bd.bead_mask & (bead_owner < 0)] = bi
        beads.append(bd)
    # 블렌딩 겹침(다른 비드의 블렌딩·비드 영역)
    for i, a in enumerate(beads):
        for j, b in enumerate(beads):
            if j <= i:
                continue
            if _regions_touch(ix, a, b):
                a.warnings.append({"code": "SELECT_BLEND_OVERLAP", "with": b.id})
                b.warnings.append({"code": "SELECT_BLEND_OVERLAP", "with": a.id})
    D = Derived(norm, selection_sha256(norm), beads, {"scan_n": int(fixed_scan.sum()), "user_n": int(fixed_user.sum()),
                                                       "source": src}, warns, ix, mesh_sha256)
    D.fixed_mask = fixed
    if with_section:
        for bd in beads:
            bd.section = _section(ix, D, bd, sc)
    else:
        for bd in beads:
            bd.section = None
    return D


def _regions_touch(ix: MeshIndex, a: BeadDerived, b: BeadDerived) -> bool:
    if a.bead_nodes.size == 0 or b.bead_nodes.size == 0:
        return False
    ra = a.blend_mm if a.w_enabled else 0.0
    rb = b.blend_mm if b.w_enabled else 0.0
    if ra <= 0 and rb <= 0:
        return False
    ta = cKDTree(ix.X[a.boundary_nodes]) if a.boundary_nodes.size else None
    tb = cKDTree(ix.X[b.boundary_nodes]) if b.boundary_nodes.size else None
    if ta is None or tb is None:
        return False
    d, _ = ta.query(ix.X[b.bead_nodes], k=1)
    if ra > 0 and np.any(d < ra):
        return True
    d, _ = tb.query(ix.X[a.bead_nodes], k=1)
    return bool(rb > 0 and np.any(d < rb))


def _derive_bead(ix: MeshIndex, b: dict, floor_masks: list, add_mask: np.ndarray, taken: np.ndarray, excl: np.ndarray,
                 bead_owner: np.ndarray, fixed: np.ndarray, sc: dict, cos_t: float, h: float, mesh: dict) -> BeadDerived:
    bd = BeadDerived(b["id"], b["name"])
    bd.floor_follow = int(b["floor_follow"])
    bd.links = [list(g) for g in b["links"]]
    F = np.zeros(ix.n_elems, bool)
    for m in floor_masks:
        F |= m
    n_bar = _mean_normal(ix, F)
    # §5.2 사면 BFS(측지 = 요소 중심 경로, 평행이면 멈춤)
    own = taken & ~F & ~add_mask                    # 다른 비드 층
    par = np.abs(ix.normal @ n_bar) >= cos_t
    allowed = ~F & ~excl & ~own & ~par & (bead_owner < 0)
    sub = np.flatnonzero(F | allowed)
    A = ix.adj[sub][:, sub].tocoo()
    w = np.linalg.norm(ix.centroid[sub[A.row]] - ix.centroid[sub[A.col]], axis=1)
    G = sparse.csr_matrix((np.maximum(w, 1e-9), (A.row, A.col)), shape=(sub.size, sub.size))
    src = np.flatnonzero(F[sub])
    lim = float(sc["slope_max_mm"])
    d = csgraph.dijkstra(G, directed=False, indices=src, min_only=True, limit=lim)
    S_auto = np.zeros(ix.n_elems, bool)
    S_auto[sub[np.isfinite(d) & (d <= lim)]] = True
    S_auto &= ~F
    # 새는 사면: S_auto 이웃 중 허용인데 거리 초과
    nb = ix.adj[np.flatnonzero(S_auto)].indices if S_auto.any() else np.zeros(0, np.int64)
    leak = np.unique(nb[allowed[nb] & ~S_auto[nb]]) if nb.size else nb
    if leak.size:
        bd.warnings.append({"code": "SELECT_SLOPE_LEAK", "n_elems": int(leak.size), "limit_mm": lim})
    rem = elems_of(ix, b["slope"]["remove"], where=f"{b['id']} 사면 remove")
    S = (S_auto | add_mask) & ~rem & ~excl & ~F
    bd.slope_auto, bd.slope_mask = S_auto, S
    bd.edited = bool(b["slope"]["mode"] == "edited" or add_mask.any() or rem.any())
    BM = F | S
    bd.bead_mask = BM
    bd.floor_mask = F
    # 경계(노드 기준) · 고리
    cin, cout = ix.node_count(BM), ix.node_count(~BM)
    bnd = (cin > 0) & (cout > 0)
    bd.boundary_nodes = np.flatnonzero(bnd)
    bd.bead_nodes = np.flatnonzero(cin > 0)
    loops, free = _loops(ix, BM)
    # 평면(가장 긴 고리) → n̂_b
    X = ix.X
    for lp in loops:
        P = X[lp["nodes"]]
        seg = np.linalg.norm(np.diff(np.vstack([P, P[:1]]) if lp["closed"] else P, axis=0), axis=1)
        lp["length"] = float(seg.sum())
    if loops:
        main = max(range(len(loops)), key=lambda i: (loops[i]["length"], -i))
        pts = X[loops[main]["nodes"]]
    else:
        pts = X[bd.boundary_nodes] if bd.boundary_nodes.size else X[ix.elem_nodes(F)]
    p_b, m_b, rms = _plane(pts)
    cF = ix.centroid[F].mean(axis=0)
    if (cF - p_b) @ m_b < 0:
        m_b = -m_b
    bd.p_b, bd.n_hat = p_b, m_b
    bd.nonplanar = rms > float(sc["plane_rms_mm"])
    if bd.nonplanar:
        bd.warnings.append({"code": "SELECT_NONPLANAR_BASE", "rms_mm": _r(rms)})
    from esl.view3d import plate_normal
    pn = plate_normal(X)
    bd.sense = "convex" if float(m_b @ pn) > 0 else "concave"
    # 고리 방향(n̂_b 기준 반시계)·시작 = 최소 노드 ID
    e1, e2 = _basis2(m_b)
    bd.e1, bd.e2 = e1, e2
    for lp in loops:
        nodes = lp["nodes"]
        if lp["closed"]:
            P = (X[nodes] - p_b)
            u, v = P @ e1, P @ e2
            area = 0.5 * float(np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v))
            if area < 0:
                nodes = nodes[::-1]
            k = int(np.argmin(ix.node_id[nodes]))
            nodes = np.roll(nodes, -k)
        else:
            if ix.node_id[nodes[-1]] < ix.node_id[nodes[0]]:
                nodes = nodes[::-1]
        lp["nodes"] = nodes
    loops.sort(key=lambda lp: (not lp["closed"], int(ix.node_id[lp["nodes"]].min())))
    bd.loops = loops
    bd.open = bool(free) or any(not lp["closed"] for lp in loops) or not loops
    if bd.open:
        bd.warnings.append({"code": "SELECT_OPEN_BOUNDARY", "n_loops": len(loops)})
    # 연결성
    if BM.any():
        sb = np.flatnonzero(BM)
        ncomp, _ = csgraph.connected_components(ix.adj[sb][:, sb], directed=False)
        if ncomp > 1:
            bd.warnings.append({"code": "SELECT_DISCONNECTED", "parts": int(ncomp)})
    # 깊이 좌표
    z_node = (X - p_b) @ m_b
    bd.z_node = z_node
    # 단별: 법선·노드 집합·D_nom
    rn = float(sc["normal_radius_mm"])
    assigned = bnd.copy()
    tiers = []
    for k, Fk in enumerate(floor_masks, start=1):
        nk = _mean_normal(ix, Fk, m_b)
        if nk @ m_b < 0:
            nk = -nk
        nodes = ix.elem_nodes(Fk)
        nodes = nodes[~assigned[nodes]]
        assigned[nodes] = True
        ek = np.flatnonzero(Fk)
        en = _orient(ix.normal[ek], nk) * ix.area[ek][:, None]
        tree = cKDTree(ix.centroid[ek])
        nn = np.zeros((nodes.size, 3))
        if nodes.size:                       # 반경 r_n 안 요소 면적 가중 법선 합(희소 행렬 곱 — 노드 루프 없음)
            M = cKDTree(X[nodes]).sparse_distance_matrix(tree, rn, output_type="coo_matrix")
            W = sparse.csr_matrix((np.ones(M.nnz), (M.row, M.col)), shape=(nodes.size, ek.size))
            W.sum_duplicates()
            v = np.asarray(W @ en)
            nv = np.linalg.norm(v, axis=1)
            ok = nv > _EPS
            nn[ok] = v[ok] / nv[ok, None]
            nn[~ok] = nk
            nn = _orient(nn, nk)
        zk = z_node[ix.elem_nodes(Fk)]
        tiers.append({"k": k, "mask": Fk, "normal": nk, "nodes": nodes, "node_normal": nn,
                      "D_nom": float(np.median(zk)) if zk.size else 0.0,
                      "planarity": float(np.percentile(zk, 95) - np.percentile(zk, 5)) if zk.size else 0.0})
    bd.tiers = tiers
    # 멈춘 평행 요소: 상판 / 빠진 단
    stop = np.zeros(ix.n_elems, bool)
    if BM.any():
        nb = ix.adj[np.flatnonzero(BM)].indices
        stop[nb] = True
    stop &= ~BM & par & ~excl
    zs = ((ix.centroid[stop] - p_b) @ m_b)
    tol = float(sc["plate_tol_mm"])
    dmin = min((t["D_nom"] for t in tiers), default=0.0)
    miss = (zs > tol) & (zs < dmin - tol)
    if miss.any():
        bd.warnings.append({"code": "SELECT_TIER_MISSING", "z_mm": _r(float(np.median(zs[miss]))),
                            "n_elems": int(miss.sum())})
    # 사면 노드 수준 보간(§5.3)
    slope_nodes = ix.elem_nodes(S)
    slope_nodes = slope_nodes[~assigned[slope_nodes]]
    bd.slope_nodes = slope_nodes
    _slope_levels(ix, bd, S, sc)
    # 고정 노드
    bd.fixed_in_bead_n = int(fixed[bd.bead_nodes].sum())
    bd.fixed_tiers = {t["k"]: bool(fixed[np.concatenate([ix.elem_nodes(t["mask"]), bd.slope_nodes,
                                                          bd.boundary_nodes])].any()) for t in tiers}
    if bd.fixed_in_bead_n:              # tiers = 기본 체크 해제할 단(백엔드 params_table 과 같은 규칙, W 는 전부)
        tl = sorted(k for k, v in bd.fixed_tiers.items() if v)
        bd.warnings.append({"code": "SELECT_FIXED_IN_BEAD", "n": bd.fixed_in_bead_n, "tiers": tl})
    # 폭(§5.4·5.7)
    _width(ix, bd, sc, mesh)
    _ranges_blend(ix, bd, fixed, sc, h, b["blend_mm"])
    return bd


def _slope_levels(ix: MeshIndex, bd: BeadDerived, S: np.ndarray, sc: dict) -> None:
    """사면 노드마다 (a, b, s, s', kf): 가까운 서로 다른 두 수준과 높이(거리) 비율, 폭용 경계↔바닥 비율."""
    sn = bd.slope_nodes
    bd.lv_a = np.zeros(sn.size, np.int64)
    bd.lv_b = np.zeros(sn.size, np.int64)
    bd.lv_s = np.zeros(sn.size)
    bd.w_s = np.zeros(sn.size)
    bd.w_kf = np.zeros(sn.size, np.int64)
    if sn.size == 0:
        return
    G = _node_graph(ix, S)
    sub = np.unique(np.concatenate([sn, ix.elem_nodes(S)]))
    pos = np.searchsorted(sub, sn)
    levels = [0] + [t["k"] for t in bd.tiers]
    anchors = {0: bd.boundary_nodes}
    for t in bd.tiers:
        anchors[t["k"]] = t["nodes"]
    zlev = {0: 0.0, **{t["k"]: t["D_nom"] for t in bd.tiers}}
    g = np.full((len(levels), sn.size), np.inf)
    for i, lv in enumerate(levels):
        a = anchors[lv]
        a = a[np.isin(a, sub)]
        if a.size:
            g[i] = _dist_from(G, sub, a)[pos]
    order = np.argsort(g, axis=0, kind="stable")
    z = bd.z_node[sn]
    eps = float(sc["level_eps_mm"])
    for j in range(sn.size):
        i1, i2 = order[0, j], order[1, j] if len(levels) > 1 else order[0, j]
        if not np.isfinite(g[i1, j]):
            a = b = 0
            s = 0.0
        elif len(levels) < 2 or not np.isfinite(g[i2, j]):
            a = b = levels[i1]
            s = 1.0
        else:
            la, lb = levels[i1], levels[i2]
            ga, gb = g[i1, j], g[i2, j]
            if zlev[la] > zlev[lb]:
                la, lb, ga, gb = lb, la, gb, ga
            a, b = la, lb
            if abs(zlev[b] - zlev[a]) < eps or bd.nonplanar:
                s = ga / max(ga + gb, 1e-300)
            else:
                s = float(np.clip((z[j] - zlev[a]) / (zlev[b] - zlev[a]), 0.0, 1.0))
        bd.lv_a[j], bd.lv_b[j], bd.lv_s[j] = a, b, s
        # 폭: 경계(0) ↔ 가장 가까운 바닥 수준
        fl = [(g[i, j], levels[i]) for i in range(1, len(levels)) if np.isfinite(g[i, j])]
        g0 = g[0, j]
        if not fl:
            bd.w_s[j], bd.w_kf[j] = 0.0, 0
        elif not np.isfinite(g0):
            kf = min(fl)[1]
            bd.w_s[j], bd.w_kf[j] = 1.0, kf
        else:
            gk, kf = min(fl)
            bd.w_kf[j] = kf
            dz = zlev[kf]
            if abs(dz) < eps or bd.nonplanar:
                bd.w_s[j] = g0 / max(g0 + gk, 1e-300)
            else:
                bd.w_s[j] = float(np.clip(z[j] / dz, 0.0, 1.0))


def _width(ix: MeshIndex, bd: BeadDerived, sc: dict, mesh: dict) -> None:
    X = ix.X
    bd.w_enabled = (not bd.open) and bool(bd.loops)
    bd.e_hat = {}
    bd.W_nom = bd.W_min = bd.W_max = None
    bd.w_j = np.zeros(0)
    bd.w_jnodes = np.zeros(0, np.int64)
    if not bd.w_enabled:
        return
    n_b = bd.n_hat
    outside = ~bd.bead_mask
    # 상판 국부 법선 m_j(비드 밖 요소 면적 가중) — ê = t × m
    all_nodes, all_e = [], []
    for lp in bd.loops:
        nodes = lp["nodes"]
        P = X[nodes]
        t = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
        t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-300)
        m = _node_normals_of(ix, nodes, outside, n_b)
        e = np.cross(t, m)
        e -= (e @ n_b)[:, None] * n_b[None, :]
        e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-300)
        # 부호: 붙은 비드 요소 중심 반대쪽
        cb = _adjacent_centroid(ix, nodes, bd.bead_mask)
        flip = np.einsum("ij,ij->i", e, cb - P) > 0
        e[flip] *= -1.0
        lp["e_hat"] = e
        all_nodes.append(nodes)
        all_e.append(e)
    bn = np.concatenate(all_nodes)
    be = np.concatenate(all_e)
    bd.wb_nodes, bd.wb_e = bn, be
    # 국부 폭(§5.7): −ê 방향 반직선과 고리 선분(평면 투영) 첫 교차
    p = X[bn] - bd.p_b
    uv = np.column_stack([p @ bd.e1, p @ bd.e2])
    dv = np.column_stack([-(be @ bd.e1), -(be @ bd.e2)])
    segA, segB, segI, segJ = [], [], [], []
    off = 0
    for lp in bd.loops:
        n = lp["nodes"].size
        idx = np.arange(n) + off
        segA.append(idx)
        segB.append(np.roll(idx, -1))
        off += n
    sa, sb = np.concatenate(segA), np.concatenate(segB)
    A2, B2 = uv[sa], uv[sb]
    w = np.full(bn.size, np.inf)
    blk = 512
    for s0 in range(0, bn.size, blk):
        o2 = uv[s0:s0 + blk, None, :]
        d2 = dv[s0:s0 + blk, None, :]
        r = B2[None] - A2[None]
        q = A2[None] - o2
        den = d2[..., 0] * r[..., 1] - d2[..., 1] * r[..., 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (q[..., 0] * r[..., 1] - q[..., 1] * r[..., 0]) / den
            uu = (q[..., 0] * d2[..., 1] - q[..., 1] * d2[..., 0]) / den
        ii = np.arange(s0, min(s0 + blk, bn.size))[:, None]
        ok = (np.abs(den) > 1e-12) & (tt > 1e-6) & (uu >= 0) & (uu <= 1) & (sa[None] != ii) & (sb[None] != ii)
        tt = np.where(ok, tt, np.inf)
        w[s0:s0 + blk] = tt.min(axis=1)
    fin = np.isfinite(w)
    if fin.any():
        med = float(np.median(w[fin]))
        keep = fin & (w <= float(sc["width"].get("end_ratio", WIDTH_END_RATIO)) * med)
    else:
        keep = fin
    bd.w_j, bd.w_jnodes = w[keep], bn[keep]
    if keep.any():
        bd.W_nom = float(np.median(w[keep]))
        bd.W_min = float(np.percentile(w[keep], 5))
        bd.W_max = float(np.percentile(w[keep], 95))
    else:
        bd.w_enabled = False
        bd.warnings.append({"code": "SELECT_WIDTH_UNDEFINED"})
        return
    seg_len = np.linalg.norm(X[bn[sb]] - X[bn[sa]], axis=1)
    bd.sigma = 2.0 * float(np.median(seg_len)) if seg_len.size else ix.h_med * 2
    bd.wtree = cKDTree(X[bn])
    # 바닥 가장자리 → 경계 평면 거리(사면 수평 길이) — 하한용
    fe = np.intersect1d(ix.elem_nodes(bd.floor_mask), ix.elem_nodes(bd.slope_mask))
    if fe.size:
        pe = X[fe] - bd.p_b
        t2 = cKDTree(uv)
        dd, _ = t2.query(np.column_stack([pe @ bd.e1, pe @ bd.e2]), k=1)        # 평면 거리
        bd.run_med = float(np.median(dd))
    else:
        bd.run_med = 0.0


def _node_normals_of(ix: MeshIndex, nodes: np.ndarray, emask: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """노드별 emask 요소 면적 가중 법선(ref 쪽)."""
    e = np.flatnonzero(emask)
    acc = np.zeros((ix.n_nodes, 3))
    v = _orient(ix.normal[e], ref) * ix.area[e][:, None]
    c = ix.conn[e]
    for i in range(4):
        m = np.ones(e.size, bool) if i < 3 else ix.is_quad[e]
        for k in range(3):
            acc[:, k] += np.bincount(c[m, i], weights=v[m, k], minlength=ix.n_nodes)
    r = acc[nodes]
    nr = np.linalg.norm(r, axis=1)
    r[nr < _EPS] = ref
    return r / np.maximum(np.linalg.norm(r, axis=1, keepdims=True), 1e-300)


def _adjacent_centroid(ix: MeshIndex, nodes: np.ndarray, emask: np.ndarray) -> np.ndarray:
    e = np.flatnonzero(emask)
    acc = np.zeros((ix.n_nodes, 3))
    cnt = np.zeros(ix.n_nodes)
    c = ix.conn[e]
    cen = ix.centroid[e]
    for i in range(4):
        m = np.ones(e.size, bool) if i < 3 else ix.is_quad[e]
        for k in range(3):
            acc[:, k] += np.bincount(c[m, i], weights=cen[m, k], minlength=ix.n_nodes)
        cnt += np.bincount(c[m, i], minlength=ix.n_nodes)
    return acc[nodes] / np.maximum(cnt[nodes], 1)[:, None]


def _ranges_blend(ix: MeshIndex, bd: BeadDerived, fixed: np.ndarray, sc: dict, h: float, user) -> None:
    rg = sc["range"]
    rd = {"D": {}, "W": None}
    zs = sorted([0.0] + [t["D_nom"] for t in bd.tiers])
    for t in bd.tiers:
        D = t["D_nom"]
        above = max([z for z in zs if z < D - 1e-9], default=0.0)
        lo = max(D * (1.0 - float(rg["depth_rel"])), above + float(rg["min_step_mm"]))
        hi = D * (1.0 + float(rg["depth_rel"]))
        lo = min(lo, hi)
        rd["D"][str(t["k"])] = [_r(lo), _r(hi)]
    if bd.w_enabled:
        W = bd.W_nom
        lo, hi = W * (1.0 - float(rg["width_rel"])), W * (1.0 + float(rg["width_rel"]))
        if bd.floor_follow == 1:
            floor_min = (bd.W_min or W) - 2.0 * bd.run_med
            lo = max(lo, W - (floor_min - h))
        rd["W"] = [_r(lo), _r(hi)]
    bd.range_default = rd
    # 블렌딩 반경(§5.6)
    bl = sc["blend"]
    bd.blend_clipped = False
    bd.blend_nodes = np.zeros(0, np.int64)
    bd.blend_d = np.zeros(0)
    if not bd.w_enabled:
        bd.blend_mm = 0.0
        bd.fixed_in_blend_n = 0
        return
    lo, hi = rd["W"]
    move = max(abs(hi - bd.W_nom), abs(lo - bd.W_nom)) / 2.0
    R_auto = max(float(bl["min_mm"]), float(bl["k"]) * move, 3.0 * h)
    outside_nodes = np.setdiff1d(np.arange(ix.n_nodes), bd.bead_nodes)
    fx_out = outside_nodes[fixed[outside_nodes]]
    if fx_out.size:
        df, _ = bd.wtree.query(ix.X[fx_out], k=1)
        d_f = float(df.min())
    else:
        d_f = math.inf
    bd.d_fixed = d_f
    if user is None or user == "auto":
        R = R_auto
        margin = float(bl["fixed_margin_mm"])
        if R > d_f - margin:
            R = max(0.5 * float(bl["min_mm"]), d_f - margin)
            bd.blend_clipped = True
            bd.warnings.append({"code": "SELECT_BLEND_CLIPPED", "R_auto_mm": _r(R_auto), "R_mm": _r(R),
                                "d_fixed_mm": _r(d_f)})
    else:
        R = float(user)
    bd.blend_mm = float(R)
    bd.R_auto = R_auto
    # 블렌딩 노드
    if R > 0:
        dd, _ = bd.wtree.query(ix.X[outside_nodes], k=1, distance_upper_bound=R)
        m = dd < R
        bd.blend_nodes, bd.blend_d = outside_nodes[m], np.asarray(dd)[m]
    bd.fixed_in_blend_n = int(fixed[bd.blend_nodes].sum())
    if bd.fixed_in_blend_n:
        bd.warnings.append({"code": "SELECT_FIXED_IN_BLEND", "n": bd.fixed_in_blend_n})


# ====================================================================== 기저 (§5.3·5.4·5.5)
def _wendland(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=np.float64)
    return np.where(t < 1.0, (1.0 - t) ** 4 * (4.0 * t + 1.0), 0.0)


def _w_field(ix: MeshIndex, bd: BeadDerived, pts: np.ndarray, sc: dict) -> np.ndarray:
    """경계 변위장 w(x) = ½ Σ ω ê / Σ ω (kNN, 가우스 가중 — 최소 거리 기준으로 정규화해 언더플로 방지)."""
    if pts.shape[0] == 0:
        return np.zeros((0, 3))
    k = min(int(sc["width"]["knn"]), bd.wb_nodes.size)
    d, j = bd.wtree.query(pts, k=k)
    if k == 1:
        d, j = d[:, None], j[:, None]
    s2 = bd.sigma ** 2
    om = np.exp(-(d ** 2 - (d[:, :1] ** 2)) / s2)
    v = np.einsum("ij,ijk->ik", om, bd.wb_e[j]) / om.sum(axis=1, keepdims=True)
    return 0.5 * v


class Basis:
    """변수 목록 vars[{name, type, bead, tier, members, nominal, idx(int32), vec(float64 (n,3))}] + 노드별 비드 방향."""

    def __init__(self, vars_: list[dict], n_nodes: int, sha_sel: str):
        self.vars, self.n_nodes, self.selection_sha256 = vars_, n_nodes, sha_sel

    def by_name(self) -> dict:
        return {v["name"]: v for v in self.vars}

    def nominal(self) -> dict:
        return {v["name"]: float(v["nominal"]) for v in self.vars}

    def affected_nodes(self) -> np.ndarray:
        if not self.vars:
            return np.zeros(0, np.int64)
        return np.unique(np.concatenate([v["idx"].astype(np.int64) for v in self.vars]))


def var_name(bid: str, typ: str, k: int | None = None) -> str:
    return f"{bid.upper()}_{typ}{k if k is not None else ''}"


def _groups(bd: BeadDerived) -> list[list[int]]:
    ks = [t["k"] for t in bd.tiers]
    linked = {k for g in bd.links for k in g}
    gs = [list(g) for g in bd.links] + [[k] for k in ks if k not in linked]
    return sorted(gs, key=lambda g: min(g))


def params_table(derived: Derived, cfg: dict | None = None) -> list[dict]:
    """DoeParamsOut.params 행(select): {name, type, bead, tier, nominal, feasible, feasible_source 'estimate',
    default_range, use_default, group_members}. 고정 침범 비드는 기본 체크 해제(§5.6)."""
    out = []
    for bd in derived.beads:
        for g in _groups(bd):
            k = min(g)
            t = next(x for x in bd.tiers if x["k"] == k)
            rng = bd.range_default["D"][str(k)]
            use = not any(bd.fixed_tiers.get(kk) for kk in g)
            out.append({"name": var_name(bd.id, "D", k), "type": "D", "bead": bd.id, "tier": k,
                        "nominal": _r(t["D_nom"]), "feasible": list(rng), "feasible_source": "estimate",
                        "default_range": list(rng), "use_default": bool(use),
                        "group_members": [var_name(bd.id, "D", kk) for kk in g]})
        if bd.w_enabled:
            rng = bd.range_default["W"]
            out.append({"name": var_name(bd.id, "W"), "type": "W", "bead": bd.id, "tier": None,
                        "nominal": _r(bd.W_nom), "feasible": list(rng), "feasible_source": "estimate",
                        "default_range": list(rng), "use_default": bd.fixed_in_bead_n == 0,
                        "group_members": [var_name(bd.id, "W")]})
    out.sort(key=lambda r: r["name"])
    return out


def _depth_basis(ix: MeshIndex, bd: BeadDerived, k: int) -> dict:
    """B_{D_k}: 단 k 바닥 노드 = n_i^k, 사면 = 수준 보간 × n^k(가장 가까운 단 k 바닥 노드), 경계·다른 단 = 0."""
    t = next(x for x in bd.tiers if x["k"] == k)
    out_idx = [t["nodes"]]
    out_vec = [t["node_normal"]]
    if bd.slope_nodes.size and t["nodes"].size:
        wa = np.where(bd.lv_a == k, 1.0 - bd.lv_s, 0.0) + np.where(bd.lv_b == k, bd.lv_s, 0.0)
        wa = np.where((bd.lv_a == k) & (bd.lv_b == k), 1.0, wa)
        m = wa != 0
        if m.any():
            tree = cKDTree(ix.X[t["nodes"]])
            _, j = tree.query(ix.X[bd.slope_nodes[m]], k=1)
            out_idx.append(bd.slope_nodes[m])
            out_vec.append(wa[m, None] * t["node_normal"][j])
    return {"idx": np.concatenate(out_idx), "vec": np.vstack(out_vec)}


def _width_basis(ix: MeshIndex, bd: BeadDerived, sc: dict, node_n: np.ndarray) -> dict:
    X = ix.X
    f = float(bd.floor_follow)
    n_b = bd.n_hat
    parts_i, parts_v = [], []
    # 경계 노드 = ½ ê_j
    parts_i.append(bd.wb_nodes)
    parts_v.append(0.5 * bd.wb_e)
    # 사면
    sn = bd.slope_nodes
    if sn.size:
        wv = _w_field(ix, bd, X[sn], sc)
        fac = 1.0 - bd.w_s * (1.0 - f)
        parts_i.append(sn)
        parts_v.append(fac[:, None] * wv)
    # 바닥
    fn = np.concatenate([t["nodes"] for t in bd.tiers]) if bd.tiers else np.zeros(0, np.int64)
    if f == 1.0 and fn.size:
        parts_i.append(fn)
        parts_v.append(_floor_harmonic(ix, bd, fn, sc))
    idx = np.concatenate(parts_i)
    vec = np.vstack(parts_v)
    vec = vec - (vec @ n_b)[:, None] * n_b[None, :]                  # 비드 노드 = 기준면 안
    # 블렌딩
    if bd.blend_nodes.size:
        bn = bd.blend_nodes
        wv = _w_field(ix, bd, X[bn], sc) * _wendland(bd.blend_d / bd.blend_mm)[:, None]
        nu = node_n[bn]
        wv = wv - np.einsum("ij,ij->i", wv, nu)[:, None] * nu
        idx = np.concatenate([idx, bn])
        vec = np.vstack([vec, wv])
    return {"idx": idx, "vec": vec}


def _floor_harmonic(ix: MeshIndex, bd: BeadDerived, fn: np.ndarray, sc: dict) -> np.ndarray:
    """바닥 노드: 가장자리(사면·경계 공유) = w(x) 디리클레, 내부 = 그래프 라플라시안 조화 확장(가중 1/길이)."""
    X = ix.X
    edge_nodes = np.intersect1d(fn, np.concatenate([ix.elem_nodes(bd.slope_mask), bd.boundary_nodes]))
    nb = np.isin(fn, edge_nodes)
    out = np.zeros((fn.size, 3))
    if nb.any():
        out[nb] = _w_field(ix, bd, X[fn[nb]], sc)
    inner = ~nb
    if not inner.any():
        return out
    G = _node_graph(ix, bd.floor_mask)
    sub = np.unique(np.concatenate([fn, ix.elem_nodes(bd.floor_mask)]))
    Gs = G[sub][:, sub].tocsr()
    Gs.data = 1.0 / np.maximum(Gs.data, 1e-9)
    deg = np.asarray(Gs.sum(axis=1)).ravel()
    L = (sparse.diags(deg) - Gs).tocsc()
    pf = np.searchsorted(sub, fn)
    ii = pf[inner]
    bb = pf[nb]
    # 디리클레 없는 성분 = 장 값(특이 방지)
    Lii = L[ii][:, ii].tocsc()
    ncomp, lab = csgraph.connected_components(Gs[ii][:, ii], directed=False)
    has_b = np.zeros(ncomp, bool)
    if bb.size:
        cross = (Gs[ii][:, bb].getnnz(axis=1) > 0)
        has_b[np.unique(lab[cross])] = True
    ok = has_b[lab]
    vals = np.zeros((ii.size, 3))
    if (~ok).any():
        vals[~ok] = _w_field(ix, bd, X[fn[inner][~ok]], sc)
    if ok.any():
        oi = np.flatnonzero(ok)
        Lk = Lii[oi][:, oi].tocsc()
        rhs = -(L[ii[oi]][:, bb] @ out[nb])
        lu = spla.splu(Lk)
        for c in range(3):
            vals[oi, c] = lu.solve(np.ascontiguousarray(rhs[:, c]))
    out[inner] = vals
    return out


def basis(mesh: dict, derived: Derived, cfg: dict | None = None, *, index: MeshIndex | None = None) -> Basis:
    """선택 rev 기저(§5, BS-D-9). 변수 순서 = 이름 정렬(params_table 과 같음)."""
    sc = _cfg(cfg)
    ix = index or derived.index
    from esl.view3d import node_geometry
    geo = node_geometry(ix.X, ix.conn, np.where(ix.is_quad, 4, 3))
    tab = {r["name"]: r for r in params_table(derived, cfg)}
    vars_ = []
    for bd in derived.beads:
        for g in _groups(bd):
            parts = [_depth_basis(ix, bd, k) for k in g]
            v = _compact(np.concatenate([p["idx"] for p in parts]), np.vstack([p["vec"] for p in parts]), ix.n_nodes)
            name = var_name(bd.id, "D", min(g))
            vars_.append({"name": name, "type": "D", "bead": bd.id, "tier": min(g), "members": list(g),
                          "nominal": float(tab[name]["nominal"]), "n_hat": bd.n_hat, **v})
        if bd.w_enabled:
            p = _width_basis(ix, bd, sc, geo.n)
            v = _compact(p["idx"], p["vec"], ix.n_nodes)
            name = var_name(bd.id, "W")
            vars_.append({"name": name, "type": "W", "bead": bd.id, "tier": None, "members": [],
                          "nominal": float(tab[name]["nominal"]), "n_hat": bd.n_hat, "R": bd.blend_mm, **v})
    vars_.sort(key=lambda v: v["name"])
    return Basis(vars_, ix.n_nodes, derived.sha256)


def _compact(idx: np.ndarray, vec: np.ndarray, n: int) -> dict:
    """중복 노드 합산 → 정렬 idx(int32)·vec(float64), 0 행 제거."""
    if idx.size == 0:
        return {"idx": np.zeros(0, np.int32), "vec": np.zeros((0, 3))}
    u, inv = np.unique(idx, return_inverse=True)
    acc = np.zeros((u.size, 3))
    for c in range(3):
        acc[:, c] = np.bincount(inv, weights=vec[:, c], minlength=u.size)
    nz = np.any(acc != 0.0, axis=1)
    return {"idx": u[nz].astype(np.int32), "vec": acc[nz]}


def morph(x0, B: Basis, values: dict) -> np.ndarray:
    """x_d = x0 + Σ (v − v_nom)·B_v. values 에 없는 변수 = 공칭. 같은 값 → 그 변수 건너뜀(바이트 불변)."""
    X = np.array(x0, dtype=np.float64, copy=True)
    for v in B.vars:
        if v["name"] not in values:
            continue
        dv = float(values[v["name"]]) - float(v["nominal"])
        if dv == 0.0 or v["idx"].size == 0:
            continue
        X[v["idx"]] += dv * v["vec"]
    return X


def fixed_violation(x0, x, fixed_mask_or_idx, tol: float) -> dict:
    fm = np.asarray(fixed_mask_or_idx)
    idx = np.flatnonzero(fm) if fm.dtype == bool else fm.astype(np.int64)
    if idx.size == 0:
        return {"n_fixed": 0, "max_mm": 0.0, "n_violated": 0, "violated": False}
    d = np.linalg.norm(np.asarray(x)[idx] - np.asarray(x0)[idx], axis=1)
    nv = int(np.sum(d > tol))
    return {"n_fixed": int(idx.size), "max_mm": float(d.max()), "n_violated": nv, "violated": nv > 0}


def affected_elems(mesh: dict, x0, x, eps: float = U_EPS) -> np.ndarray:
    u = np.linalg.norm(np.asarray(x) - np.asarray(x0), axis=1) > eps
    C = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    m = u[C[:, 0]] | u[C[:, 1]] | u[C[:, 2]]
    q = et == 4
    m[q] |= u[C[q, 3]]
    return m


def design_state(mesh: dict, x0, x, fixed_mask, cfg: dict | None = None) -> dict:
    """안 1개 판정(미리보기·실행 공통): 고정 침범 → SKIPPED_FIXED(SELECT_FIXED_VIOLATION), 뒤집힘 → FAILED_MESH
    (SELECT_MORPH_INVERTED), 새 Fail 비율 초과 → FAILED_MESH(SELECT_QUALITY_FAIL), 그 밖 READY."""
    from esl.doe import mesh_quality as mq
    sc = _cfg(cfg)
    fx = fixed_violation(x0, x, fixed_mask, float(sc["fixed_tol_mm"]))
    am = affected_elems(mesh, x0, x)
    q = mq.affected_quality(mesh, x, am, _qcfg(cfg), flip_deg=float(sc["quality"]["flip_deg"]),
                            max_fail_ratio=float(sc["quality"]["max_fail_ratio"]))
    if fx["violated"]:
        st, code = "SKIPPED_FIXED", "SELECT_FIXED_VIOLATION"
    elif q["inverted"] > 0:
        st, code = "FAILED_MESH", "SELECT_MORPH_INVERTED"
    elif q["over_limit"]:
        st, code = "FAILED_MESH", "SELECT_QUALITY_FAIL"
    else:
        st, code = "READY", None
    return {"state": st, "code": code, "fixed": fx, "quality": q}


# ====================================================================== 저장·직렬화
def save_basis(path: str, B: Basis, guard=None) -> str:
    """basis.npz(결정적): names, types, nominal, ptr, idx(int32), vec(float64), n_hat(var,3), R."""
    from esl.doe.mesh_gmsh import save_npz_det
    g = guard or (lambda p: p)
    ptr = np.concatenate([[0], np.cumsum([v["idx"].size for v in B.vars])]).astype(np.int64)
    arr = {"names": np.asarray([v["name"] for v in B.vars], dtype="U32"),
           "types": np.asarray([v["type"] for v in B.vars], dtype="U1"),
           "beads": np.asarray([v["bead"] for v in B.vars], dtype="U4"),
           "nominal": np.asarray([v["nominal"] for v in B.vars], dtype=np.float64),
           "R": np.asarray([float(v.get("R") or 0.0) for v in B.vars], dtype=np.float64),
           "n_hat": np.asarray([v["n_hat"] for v in B.vars], dtype=np.float64).reshape(-1, 3),
           "ptr": ptr,
           "idx": (np.concatenate([v["idx"] for v in B.vars]) if B.vars else np.zeros(0)).astype(np.int32),
           "vec": (np.vstack([v["vec"] for v in B.vars]) if B.vars else np.zeros((0, 3))).astype(np.float64),
           "meta": np.asarray([B.n_nodes], dtype=np.int64),
           "selection_sha256": np.asarray([B.selection_sha256], dtype="U64")}
    save_npz_det(g(path), arr)
    return path


def load_basis(path: str) -> Basis:
    with np.load(path, allow_pickle=False) as z:
        a = {k: np.asarray(z[k]) for k in z.files}
    vars_ = []
    for i, name in enumerate(a["names"].tolist()):
        s, e = int(a["ptr"][i]), int(a["ptr"][i + 1])
        vars_.append({"name": name, "type": str(a["types"][i]), "bead": str(a["beads"][i]),
                      "nominal": float(a["nominal"][i]), "R": float(a["R"][i]), "n_hat": a["n_hat"][i],
                      "idx": a["idx"][s:e], "vec": a["vec"][s:e]})
    return Basis(vars_, int(a["meta"][0]), str(a["selection_sha256"][0]))


def basis_bin(B: Basis) -> bytes:
    """브라우저 basis.bin: 변수 순서 = basis.json, 각 [n:u32][idx:u32×n][vec:f32×3n] (리틀 엔디안)."""
    out = []
    for v in B.vars:
        n = int(v["idx"].size)
        out.append(struct.pack("<I", n))
        out.append(np.ascontiguousarray(v["idx"], dtype="<u4").tobytes())
        out.append(np.ascontiguousarray(v["vec"], dtype="<f4").tobytes())
    return b"".join(out)


def basis_meta(B: Basis, sha_npz: str | None = None) -> dict:
    return {"schema": "esl/bead_select_basis/1", "selection_sha256": B.selection_sha256, "basis_sha256": sha_npz,
            "n_nodes": B.n_nodes,
            "vars": [{"name": v["name"], "type": v["type"], "bead": v["bead"], "nominal": float(v["nominal"]),
                      "n": int(v["idx"].size), "R_mm": (float(v["R"]) if v.get("R") else None)} for v in B.vars]}


def node_direction(B: Basis) -> tuple[np.ndarray, np.ndarray]:
    """썸네일 색(§7.2): 노드별 비드 방향 n̂_b(영향 노드 — 비드 id 순서 첫 비드 우선)와 영향 마스크."""
    n = B.n_nodes
    dirv = np.zeros((n, 3))
    has = np.zeros(n, bool)
    for v in sorted(B.vars, key=lambda v: (int(str(v["bead"])[1:]), v["name"])):
        idx = v["idx"].astype(np.int64)
        new = idx[~has[idx]]
        dirv[new] = np.asarray(v["n_hat"], dtype=np.float64)
        has[new] = True
    return dirv, has


# ====================================================================== 단면·평면도 (§7.1)
def _section(ix: MeshIndex, D: Derived, bd: BeadDerived, sc: dict) -> dict | None:
    """공칭 폭 중앙값 위치 경계 노드에서 −ê 방향 평면(ê, n̂_b)과 메시 교선 → s(mm)·z(mm, 깊어짐 +) + 기저 미분."""
    if not bd.w_enabled or bd.w_j.size == 0:
        return None
    j = int(np.argmin(np.abs(bd.w_j - bd.W_nom) + 1e-9 * np.arange(bd.w_j.size)))
    node = int(bd.w_jnodes[j])
    k = int(np.flatnonzero(bd.wb_nodes == node)[0])
    e = bd.wb_e[k]
    x0 = ix.X[node]
    qn = np.cross(e, bd.n_hat)
    qn /= np.linalg.norm(qn)
    R = bd.blend_mm or 0.0
    smin, smax = -(R + 2 * ix.h_med), float(bd.w_j[j]) + R + 2 * ix.h_med
    from esl.view3d import triangulate
    tris = triangulate(ix.conn, np.where(ix.is_quad, 4, 3)).astype(np.int64)
    P = ix.X
    sd = (P - x0) @ qn
    a, b, c = sd[tris[:, 0]], sd[tris[:, 1]], sd[tris[:, 2]]
    cross = (np.minimum(np.minimum(a, b), c) < 0) & (np.maximum(np.maximum(a, b), c) > 0)
    tt = tris[cross]
    pts, wts = [], []
    for (i0, i1) in ((0, 1), (1, 2), (2, 0)):
        u, v = tt[:, i0], tt[:, i1]
        su, sv = sd[u], sd[v]
        m = (su < 0) != (sv < 0)
        lam = su[m] / (su[m] - sv[m])
        pts.append(np.column_stack([u[m], v[m]]))
        wts.append(lam)
    if not pts:
        return None
    E = np.vstack(pts)
    L = np.concatenate(wts)
    key = np.minimum(E[:, 0], E[:, 1]) * (1 << 32) + np.maximum(E[:, 0], E[:, 1])
    _, first = np.unique(key, return_index=True)
    E, L = E[first], L[first]
    X = P[E[:, 0]] * (1 - L[:, None]) + P[E[:, 1]] * L[:, None]
    s = (X - x0) @ (-e)
    z = (X - bd.p_b) @ bd.n_hat
    # 같은 평면의 먼 부분 제외: s 범위 + 평면 안 측방향(ê 수직) 거리
    m = (s >= smin) & (s <= smax) & (np.abs(z) <= 3 * max(t["D_nom"] for t in bd.tiers) + 10 * ix.h_med)
    if not m.any():
        return None
    E, L, s, z = E[m], L[m], s[m], z[m]
    o = np.lexsort((z, s))
    E, L, s, z = E[o], L[o], s[o], z[o]
    out = {"s": [_r(v, 3) for v in s], "z": [_r(v, 3) for v in z], "at_node_id": int(ix.node_id[node]),
           "at_ab": None, "dz_dD": {}, "ds_dW": None, "dz_dW": None}
    try:
        B = basis(None, D, {"select": sc}, index=ix) if not hasattr(D, "_basis_cache") else D._basis_cache
    except Exception:              # 단면 그림 실패는 선택 저장을 막지 않음
        return out
    D._basis_cache = B
    for v in B.vars:
        if v["bead"] != bd.id:
            continue
        full = np.zeros((ix.n_nodes, 3))
        full[v["idx"]] = v["vec"]
        g = full[E[:, 0]] * (1 - L[:, None]) + full[E[:, 1]] * L[:, None]
        if v["type"] == "D":
            out["dz_dD"][str(v["tier"])] = [_r(x, 4) for x in g @ bd.n_hat]
        else:
            out["ds_dW"] = [_r(x, 4) for x in g @ (-e)]
            out["dz_dW"] = [_r(x, 4) for x in g @ bd.n_hat]
    return out


def _loops_of_mask(ix: MeshIndex, mask: np.ndarray) -> list[np.ndarray]:
    loops, _ = _loops(ix, mask)
    return [lp["nodes"] for lp in loops]


def _plan_bead(ix: MeshIndex, frame: dict, bd: BeadDerived) -> dict:
    from esl.opt.keepout import project_ab
    ex, ee = np.asarray(frame["e_xi"], float), np.asarray(frame["e_eta"], float)
    ring = [project_ab(frame, ix.X[lp["nodes"]]).round(3).tolist() for lp in bd.loops]
    eab = [np.column_stack([lp["e_hat"] @ ex, lp["e_hat"] @ ee]).round(5).tolist() if "e_hat" in lp else []
           for lp in bd.loops]
    tiers = [{"k": t["k"], "ring_ab": [project_ab(frame, ix.X[n]).round(3).tolist()
                                        for n in _loops_of_mask(ix, t["mask"])]} for t in bd.tiers]
    lab = project_ab(frame, ix.centroid[bd.bead_mask].mean(axis=0))[0].round(3).tolist() if bd.bead_mask.any() else None
    return {"ring_ab": ring, "e_ab": eab, "label_ab": lab, "tiers": tiers}


def plan_data(mesh: dict, selection: dict, derived, cfg: dict | None = None, *, frame: dict) -> dict:
    """(백엔드 API) 평면도 select 판(§7.1) = DoePlanOut 전체 키: frame·outline·holes·elems(``keepout.plan_view``, opt_run 기본값)
    + beads[{id, name, ring_ab, e_ab, label_ab, tiers, section}] + fixed[{a, b}] + nodes_ab + warnings.
    derived = ``derive`` 결과 dict(비드 plan 포함) 또는 ``derive_obj`` 결과."""
    from esl.doe import opt_settings
    from esl.opt.keepout import plan_view, project_ab
    if isinstance(derived, Derived):
        ix = derived.index
        beads = [{"id": b.id, "name": b.name, **_plan_bead(ix, frame, b), "section": b.section} for b in derived.beads]
        fixed = _fixed_ab(derived, frame)
        warns = list(derived.warnings) + [w for b in derived.beads for w in b.warnings]
    else:
        beads = []
        for b in derived.get("beads") or []:
            pl = b.get("plan") or {}
            beads.append({"id": b["id"], "name": b.get("name"), "ring_ab": pl.get("ring_ab", []),
                          "e_ab": pl.get("e_ab", []), "label_ab": pl.get("label_ab"), "tiers": pl.get("tiers", []),
                          "section": b.get("section")})
        fixed = list(derived.get("fixed_ab") or [])
        warns = list(derived.get("warnings") or []) + [w for b in derived.get("beads") or [] for w in b.get("warnings") or []]
    oc = opt_settings()
    pv = plan_view(mesh, frame, oc["keepout"], int(oc["ui"]["max_preview_points"]))
    nab = project_ab(frame, np.asarray(mesh["x0"], dtype=np.float64)).round(2).tolist()
    pv.update(beads=beads, fixed=fixed, nodes_ab=nab, warnings=list(pv.get("warnings") or []) + warns, a_points=[],
              load_points=[], links=[])
    return pv


# ====================================================================== 선택 보기 자료 (§8.1 prep/select/)
def view_files(mesh: dict, fixed_mask: np.ndarray) -> tuple[bytes, dict]:
    """select.bin 바이트와 배치 정보: tri2elem uint32[T] · elem_id uint32[E] · elem_type uint8[E] · fixed uint8[N]."""
    from esl.view3d import triangulate
    et = np.asarray(mesh["elem_type"]).astype(int)
    q = et == 4
    tri2elem = np.repeat(np.arange(et.size, dtype=np.uint32), 1 + q.astype(np.int64))
    T = triangulate(np.asarray(mesh["conn"]), et).shape[0]
    assert tri2elem.size == T
    parts = [("tri2elem", tri2elem.astype("<u4")), ("elem_id", np.asarray(mesh["elem_id"]).astype("<u4")),
             ("elem_type", et.astype(np.uint8)), ("fixed", np.asarray(fixed_mask, bool).astype(np.uint8))]
    layout, buf, off = [], [], 0
    for name, a in parts:
        b = a.tobytes()
        pad = (-len(b)) % 4
        layout.append({"name": name, "dtype": str(a.dtype.str).replace("|", ""), "offset": off, "count": int(a.size)})
        buf.append(b + b"\x00" * pad)
        off += len(b) + pad
    return b"".join(buf), {"layout": layout, "n_tris": int(T)}
