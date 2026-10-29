"""OptiStruct 비드(topography, DTPG) 최적화 덱 (계약 esl_p2_library.md §4).

``write(target_mesh, load_cases, support_321, design, out_dir, writer=None) -> dict``

생성 파일(``out_dir``):
- ``<deck>.fem``  : Case control(DESOBJ, SUBCASE별 SPC·LOAD) + BEGIN BULK(INCLUDE 하중, GRID, CQUAD4/CTRIA3,
                    (원 PID, 두께, 재료, 설계여부)별 PSHELL, (E,ν)별 MAT1, SPC1(3-2-1), DTPG, DRESP1, DOBJREF ...)
- ``esl_loads.inc``: subcase별 FORCE (LOAD SID 별)
- ``run_optistruct.bat`` (CRLF): ``%OPTISTRUCT_BAT%`` 또는 ``%ALTAIR_HOME%\\hwsolvers\\scripts\\optistruct.bat`` 호출
- ``README.txt``  : 카드 설명·확신도·실행·확인 항목

카드 형식 (OptiStruct Reference Guide 기준, 이 환경에서 OptiStruct 실행 검증은 불가 → 확신도 표기):
- 자유형식(콤마) 기본. 데이터 필드 8개를 넘으면 ``+,`` 로 시작하는 연속 줄. ``card_format: fixed`` 면 최적화 카드
  (DTPG·DRESP1·DOBJREF·DCONSTR)를 8칸 고정형식(연속 줄 첫 칸 ``+``)으로 쓴다(메시·하중 카드는 항상 자유형식).
- DTPG (OptiStruct Reference Guide DTPG, help.altair.com …/os/dtpg_bulk_r.htm, 2025·2026):
  ``DTPG, ID, PSHELL, PID1..PID6`` / ``+, , PID7..PID13`` (PID 연속 줄은 3번째 칸부터) /
  ``+, MW, ANG, BF, HGT, NORM, , , SKIP`` (비드 줄: **플래그 없음** — 2번째 칸이 MW) / ``+, BOUNDS, LB, UB``.
  v0.8.0 이전 덱의 ``+,BEAD,MW,ANG,BH,BUFFZONE,SKIP`` 은 OptiStruct 2026.1 이 ``ERROR # 1485`` (Field 0
  unrecognized label) 로 거부(이슈 #35). 비드 줄 칸 배치·플래그·PID 연속 시작 칸은 설정 ``optdeck.dtpg.*``.
  SKIP 은 명시적으로 ``BC``: 이 덱은 **전 노드에 FORCE** 가 있으므로 LOAD/BOTH 를 쓰면 설계 노드가 모두 빠진다.
- ``DRESP1, RID, COMP, COMP`` (PTYPE 비움 = 모델 전체 컴플라이언스, subcase 별 응답).  [확신도: 상]
- minmax: case control 최상단 ``MINMAX = DOID`` + subcase마다 ``DOBJREF, DOID, RID, SID, (NEGREF), POSREF``
  (Reference Guide minmax_maxmin_sub_r·dobjref_bulk_r 2025: DESOBJ 의 type 은 MIN/MAX/MINP/MAXP 뿐이라 v0.8.0 이전
  ``DESOBJ(MINMAX) = OID``·``DOBJREF, OID, RID, , POS, LOADSUB``(SID 칸 비움 → 5번째 칸 NEGREF 에 양수) 는 공식 형식과 다름).
  POS = 기준 컴플라이언스(주면 상대값 minmax, 없으면 1.0 = 절대 컴플라이언스).  [확신도: 중상]
- weighted: ``DRESP1, RID, WCOMP, WCOMP`` + ``DESOBJ(MIN) = RID`` + subcase마다 ``WEIGHT = w``.  [확신도: 중]
- BEADFRAC(선택): ``DRESP1, BID, BEADF, BEADFRAC, DTPG, , , DTPG_ID`` + ``DCONSTR, CID, BID, , UB`` + ``DESGLB = CID``.
  [확신도: 중하 — 실행 확인 전 기본 꺼짐]
- 3-2-1 지지: 강체 6모드 구속 행렬 rank 6·σmin/σmax ≥ 1e-6 아니면 ``SUPPORT_DEGENERATE``.
- 비설계 영역: ``nondesign_pids``, ``design_pids``(주면 그 밖은 비설계), ``nondesign_node_ids`` 반경
  ``nondesign_radius`` 안 노드를 쓰는 요소, ``nondesign_elem_ids``(요소 ID 목록 — OPT_RUN 비드 금지 영역) →
  별도 PSHELL(비설계)로 분리해 DTPG 목록에서 제외.
- 서버 실행(OPT_RUN, esl_opt_run.md §8.2): ``design["server"] = {opt_run_id, scenario, desmax}`` 가 있을 때만
  헤더 ``opt_run <id> <scenario>``, I/O 절 ``OUTPUT,H3D,ALL``, bulk ``DOPTPRM,DESMAX,<desmax>`` 를 넣는다.
  ``server`` 가 없으면 LIB_ANALYZE 덱과 바이트가 같다(골든 불변).
"""
from __future__ import annotations

import os

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.mech import supports as msup

DEFAULT_DESIGN = {
    "design_pids": None, "nondesign_pids": [], "nondesign_node_ids": [], "nondesign_radius": 0.0,
    "bead": {"min_width": 10.0, "height": 3.0, "angle": 60.0, "buffzone": True, "skip": "BC", "bounds": [0.0, 1.0]},
    "objective": "minmax", "beadfrac_max": None, "id_offset": 9000000, "num_format": "{:.9E}",
    "force_zero_tol_rel": 1e-9, "card_format": "free", "deck_name": "esl_bead", "nt": 4,
    "nondesign_elem_ids": None, "server": None, "dtpg": None,
}
# DTPG 비드 줄 칸 배치(2..9번째 칸, 공식 형식 MW ANG BF HGT NORM/XD YD ZD SKIP). 토큰: MW ANG BF HGT DRAW SKIP '-'(빈 칸)
DTPG_DEFAULT = {"bead_flag": "", "bead_fields": ["MW", "ANG", "BF", "HGT", "DRAW", "-", "-", "SKIP"], "draw": "NORM",
                "pid_cont_col": 3}
DTPG_TOKENS = ("MW", "ANG", "BF", "HGT", "DRAW", "SKIP", "-")
DTPG_REQUIRED = ("MW", "ANG", "BF", "HGT", "SKIP")
SKIP_VALUES = ("BC", "LOAD", "BOTH", "NONE")
CONFIDENCE = {
    "mesh_force_spc_cards": "상 (GRID/CQUAD4/CTRIA3/PSHELL/MAT1/FORCE/SPC1 = 기존 esl_force.fem 과 같은 형식)",
    "DTPG": "중상 (비드 줄 MW, ANG, BF, HGT, NORM, -, -, SKIP / BOUNDS: LB, UB — 2025·2026 레퍼런스 형식표)",
    "DRESP1_COMP": "상",
    "DESOBJ_MINMAX_DOBJREF": "중상 (MINMAX = DOID, DOBJREF: DOID, RID, SID, NEGREF, POSREF 순 — 2025 레퍼런스 형식표)",
    "WCOMP_WEIGHT": "중 (weighted compliance 응답과 subcase WEIGHT 문)",
    "BEADFRAC": "중하 (응답 PTYPE/ATT 위치 확인 필요, 기본 사용 안 함)",
    "free_format_continuation": "중상 ('+,' 연속 줄; 실패 시 card_format: fixed 로 다시 생성)",
}
CONFIDENCE_EN = {
    "mesh/FORCE/SPC1 cards": "high",
    "DTPG bead line (MW ANG BF HGT NORM - - SKIP, no flag; BOUNDS LB UB)": "medium-high",
    "DRESP1 COMP": "high", "MINMAX + DOBJREF (DOID RID SID NEGREF POSREF)": "medium-high",
    "WCOMP + subcase WEIGHT": "medium", "BEADFRAC response": "medium-low",
    "free-format continuation '+,'": "medium-high (regenerate with card_format: fixed if rejected)",
}


# ---------------------------------------------------------------- 카드 서식
def real(v, width: int | None = None) -> str:
    """실수 필드(소수점 보장). width 가 있으면 그 폭 이하로 줄인다(고정형식)."""
    v = float(v)
    if not np.isfinite(v):
        raise EslError("INPUT_INVALID", f"실수 필드에 비유한 값 {v}")
    for p in range(9, 0, -1):
        s = f"{v:.{p}g}"
        if "e" in s:
            m, e = s.split("e")
            if "." not in m:
                m += "."
            s = f"{m}E{int(e):+d}"
        elif "." not in s:
            s += "."
        if width is None or len(s) <= width:
            return s
    raise EslError("INPUT_INVALID", f"실수 {v} 를 {width}자에 쓸 수 없음")


def card(name: str, fields: list, fmt: str = "free") -> list[str]:
    """카드 → 줄 목록. 첫 줄 데이터 8개, 연속 줄 8개씩."""
    f = ["" if x is None else str(x) for x in fields]
    chunks = [f[:8]] + [f[k:k + 8] for k in range(8, len(f), 8)]
    out = []
    for n, ch in enumerate(chunks):
        while ch and ch[-1] == "":
            ch = ch[:-1]
        head = name if n == 0 else "+"
        if fmt == "free":
            out.append(",".join([head] + ch))
        elif fmt == "fixed":
            for x in [head] + ch:
                if len(x) > 8:
                    raise EslError("INPUT_INVALID", f"고정형식 8칸 초과 필드 '{x}' ({name})")
            out.append(f"{head:<8}" + "".join(f"{x:>8}" for x in ch))
        else:
            raise EslError("INPUT_INVALID", f"card_format: free|fixed (값 {fmt!r})")
    return out


def _merge(base: dict, over: dict | None) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update({kk: vv for kk, vv in v.items() if vv is not None})
        elif v is not None or k in ("design_pids", "beadfrac_max", "server", "nondesign_elem_ids", "dtpg"):
            out[k] = v
    return out


def design_mask(mesh: dict, d: dict) -> tuple[np.ndarray, dict]:
    """요소별 설계 여부 (E,) bool + 사유 집계."""
    pid = np.asarray(mesh["elem_pid"], dtype=np.int64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    et = np.asarray(mesh["elem_type"]).astype(int)
    des = np.ones(pid.size, dtype=bool)
    why = {"by_pid": 0, "by_design_pids": 0, "by_radius": 0}
    if d.get("nondesign_pids"):
        m = np.isin(pid, np.asarray(d["nondesign_pids"], dtype=np.int64))
        why["by_pid"] = int(m.sum())
        des &= ~m
    if d.get("design_pids") is not None:
        m = ~np.isin(pid, np.asarray(d["design_pids"], dtype=np.int64))
        why["by_design_pids"] = int((m & des).sum())
        des &= ~m
    ids = d.get("nondesign_node_ids") or []
    rad = float(d.get("nondesign_radius") or 0.0)
    if ids:
        nid = np.asarray(mesh["node_id"], dtype=np.int64)
        pos = np.searchsorted(nid, ids)
        pos = np.minimum(pos, nid.size - 1)
        bad = [i for i, p in zip(ids, pos) if nid[p] != i]
        if bad:
            raise EslError("NODE_NOT_IN_PART", f"nondesign_node_ids 중 대상 메시에 없는 노드 {bad[:10]}")
        X = np.asarray(mesh["x0"], dtype=np.float64)
        near = np.zeros(nid.size, dtype=bool)
        for p in pos:
            near |= np.linalg.norm(X - X[p], axis=1) <= rad
        en = np.zeros(pid.size, dtype=bool)
        for k in range(4):
            col = conn[:, k]
            ok = (k < et)
            en |= ok & near[np.maximum(col, 0)]
        why["by_radius"] = int((en & des).sum())
        des &= ~en
    if d.get("nondesign_elem_ids") is not None:
        eid = np.asarray(mesh["elem_id"], dtype=np.int64)
        want = np.asarray(d["nondesign_elem_ids"], dtype=np.int64).reshape(-1)
        bad = np.setdiff1d(want, eid)
        if bad.size:
            raise EslError("INPUT_INVALID", f"nondesign_elem_ids 중 대상 메시에 없는 요소 {bad[:10].tolist()}")
        m = np.isin(eid, want)
        why["by_elems"] = int((m & des).sum())
        des &= ~m
    return des, why


def support_rank(X: np.ndarray, sup_pos: list[int], dofs: list[str]) -> dict:
    """3-2-1 지지의 강체 6모드 구속 행렬 (구속 dof 행 × [병진 3, 회전 3]) rank·σmin/σmax.

    회전 열은 지지점 중심 기준·최대 거리 L 로 무차원화(``esl.mech.supports`` 와 같은 규약), 회전 dof(4-6)는 1/L 행.
    """
    P = np.asarray(X, dtype=np.float64)[sup_pos]
    ctr = P.mean(axis=0)
    L = max(float(np.max(np.linalg.norm(P - ctr, axis=1))), 1e-300)
    rows = []
    for p, ds in zip(P, dofs):
        r = (p - ctr) / L
        for ch in ds:
            d = int(ch) - 1
            row = np.zeros(6)
            if d < 3:
                row[d] = 1.0
                for i in range(3):
                    w = np.zeros(3)
                    w[i] = 1.0
                    row[3 + i] = np.cross(w, r)[d]
            else:
                row[d] = 1.0 / L
            rows.append(row)
    A = np.array(rows).reshape(-1, 6)
    s = np.linalg.svd(A, compute_uv=False) if A.size else np.zeros(0)
    ratio = float(s[5] / s[0]) if s.size >= 6 and s[0] > 0 else 0.0
    rank = int(np.sum(s > msup.DEGENERATE_RATIO * s[0])) if s.size and s[0] > 0 else 0
    return {"rank": rank, "sigma_ratio": ratio, "n_rows": int(A.shape[0])}


def dtpg_layout(over: dict | None) -> dict:
    """DTPG 비드 줄 배치(설정 ``optdeck.dtpg``) 검증 + 기본값."""
    tp = {**DTPG_DEFAULT, **{k: v for k, v in (over or {}).items() if v is not None}}
    unknown = set(tp) - set(DTPG_DEFAULT)
    if unknown:
        raise EslError("INPUT_INVALID", f"optdeck.dtpg 알 수 없는 키 {sorted(unknown)}")
    f = [str(x).upper() for x in tp["bead_fields"]]
    flag = str(tp["bead_flag"] or "").strip().upper()
    bad = [x for x in f if x not in DTPG_TOKENS]
    if bad or any(f.count(x) != 1 for x in DTPG_REQUIRED) or f.count("DRAW") > 1 or len(f) + bool(flag) > 8:
        raise EslError("INPUT_INVALID", f"optdeck.dtpg.bead_fields: {list(DTPG_TOKENS)} 토큰, MW·ANG·BF·HGT·SKIP 각 1번, "
                                        f"플래그 포함 8칸 이하 (값 {tp['bead_fields']})")
    if not (flag == "" or flag.isalpha()):
        raise EslError("INPUT_INVALID", f"optdeck.dtpg.bead_flag: 빈 값 또는 영문 라벨 (값 {tp['bead_flag']!r})")
    draw = str(tp["draw"] or "").strip().upper()
    if draw not in ("", "NORM"):
        raise EslError("INPUT_INVALID", f"optdeck.dtpg.draw: NORM 또는 빈 값 (값 {tp['draw']!r})")
    col = tp["pid_cont_col"]
    if isinstance(col, bool) or not isinstance(col, int) or col not in (2, 3):
        raise EslError("INPUT_INVALID", f"optdeck.dtpg.pid_cont_col: 2|3 (값 {col!r})")
    return {"bead_flag": flag, "bead_fields": f, "draw": draw, "pid_cont_col": col}


def _ascii(s) -> str:
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def write(target_mesh: dict, load_cases: list[dict], support_321, design: dict | None, out_dir: str,
          writer: U.Writer | None = None) -> dict:
    d = _merge(DEFAULT_DESIGN, design)
    if d["objective"] not in ("minmax", "weighted"):
        raise EslError("INPUT_INVALID", f"objective: minmax|weighted (값 {d['objective']!r})")
    b = d["bead"]
    skip = str(b["skip"]).upper()
    if skip not in SKIP_VALUES:
        raise EslError("INPUT_INVALID", f"bead.skip: {SKIP_VALUES}")
    if skip in ("LOAD", "BOTH"):
        raise EslError("INPUT_INVALID", "bead.skip=LOAD/BOTH 는 전 노드 FORCE 덱에서 설계 노드를 모두 제외함 — BC 또는 NONE")
    if not load_cases:
        raise EslError("INPUT_INVALID", "하중 케이스가 없음")
    dtpg_layout(d.get("dtpg"))
    srv = d.get("server")
    if srv is not None:
        if not isinstance(srv, dict) or int(srv.get("desmax") or 0) < 1:
            raise EslError("INPUT_INVALID", "server.desmax ≥ 1 필요")
    fmt = d["card_format"]
    g = d["num_format"].format
    nid = np.asarray(target_mesh["node_id"], dtype=np.int64)
    X = np.asarray(target_mesh["x0"], dtype=np.float64)
    conn = np.asarray(target_mesh["conn"], dtype=np.int64)
    et = np.asarray(target_mesh["elem_type"]).astype(int)
    eid = np.asarray(target_mesh["elem_id"], dtype=np.int64)
    N = nid.size
    for lc in load_cases:
        if np.asarray(lc["f"]).shape != (N, 3):
            raise EslError("INPUT_INVALID", f"하중 케이스 {lc.get('label')}: f 는 (N,3)")
    sup = [(int(n), str(dof)) for n, dof in support_321]
    miss = [n for n, _ in sup if n not in set(nid.tolist())]
    if miss:
        raise EslError("NODE_NOT_IN_PART", f"3-2-1 노드 {miss} 가 대상 메시에 없음")
    bad_dof = [(n, dof) for n, dof in sup if not dof or any(c not in "123456" for c in dof)]
    if bad_dof:
        raise EslError("INPUT_INVALID", f"3-2-1 dof 는 1-6 숫자 문자열: {bad_dof}")
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    sr = support_rank(X, [pos[n] for n, _ in sup], [dof for _, dof in sup])
    if sr["rank"] < 6 or sr["sigma_ratio"] < msup.DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 지지가 강체 6모드를 구속하지 못함 (rank {sr['rank']}, "
                                             f"σmin/σmax={sr['sigma_ratio']:.2e}): {sup}")

    des, why = design_mask(target_mesh, d)
    if not des.any():
        raise EslError("INPUT_INVALID", "설계 요소가 없음(비설계 설정 확인)")
    # 재료 (E, nu) → MAT1, (원 PID, t, 재료, 설계) → PSHELL
    E = np.broadcast_to(np.asarray(target_mesh["E"], dtype=np.float64), eid.shape)
    nu = np.broadcast_to(np.asarray(target_mesh["nu"], dtype=np.float64), eid.shape)
    mats, minv = np.unique(np.column_stack([E, nu]), axis=0, return_inverse=True)
    minv = minv.reshape(-1)
    keys = np.column_stack([np.asarray(target_mesh["elem_pid"], dtype=np.float64),
                            np.asarray(target_mesh["thickness"], dtype=np.float64), minv.astype(np.float64),
                            (~des).astype(np.float64)])
    groups, ginv = np.unique(keys, axis=0, return_inverse=True)
    ginv = ginv.reshape(-1)

    cur = [int(d["id_offset"])]

    def take(n=1):
        out = list(range(cur[0] + 1, cur[0] + 1 + n))
        cur[0] += n
        return out

    spc_sid = take()[0]
    load_sids = take(len(load_cases))
    mids = take(len(mats))
    pids = take(len(groups))
    dtpg_id = take()[0]
    comp_rid = take()[0]
    obj_id = take()[0]
    bf_rid = bf_cid = None
    if d["beadfrac_max"] is not None:
        bf_rid, bf_cid = take()[0], take()[0]
    design_pids = [pids[k] for k in range(len(groups)) if groups[k, 3] == 0.0]
    nondesign_pids = [pids[k] for k in range(len(groups)) if groups[k, 3] == 1.0]

    deck = d["deck_name"]
    hdr = [f"ESL bead topography deck (OptiStruct 2026.1, {fmt} format for optimization cards)",
           f"generated by esl.library.optdeck; nodes/elements = Radioss IDs; generated IDs from {d['id_offset'] + 1}"]
    if srv is not None:
        hdr.append(f"opt_run {srv.get('opt_run_id')} {srv.get('scenario')}")
    hdr += [str(x) for x in (d.get("header") or [])]
    L = [f"$ {_ascii(x)}" for x in hdr]
    L += [f"$ confidence (not executed by generator): {k} = {v}" for k, v in CONFIDENCE_EN.items()]
    if srv is not None:
        L.append("$ confidence: OUTPUT,H3D,ALL = medium-high, DOPTPRM DESMAX = high (V-OR-R1)")
        L.append("OUTPUT,H3D,ALL")
    if d["objective"] == "minmax":
        L.append(f"MINMAX = {obj_id}")
    else:
        L.append(f"DESOBJ(MIN) = {comp_rid}")
    if bf_cid is not None:
        L.append(f"DESGLB = {bf_cid}")
    L += ["DISPLACEMENT(H3D) = ALL", "SPCFORCE(H3D) = ALL"]
    for k, lc in enumerate(load_cases):
        L += [f"SUBCASE {k + 1}", f"  LABEL {_ascii(lc.get('label') or f'LC{k + 1}')[:56]}",
              f"  SPC = {spc_sid}", f"  LOAD = {load_sids[k]}"]
        if d["objective"] == "weighted":
            w = lc.get("weight")
            L.append(f"  WEIGHT = {real(1.0 if w is None else w)}")
    L += ["BEGIN BULK", "INCLUDE 'esl_loads.inc'", "$ ---- GRID (Radioss node ID)"]
    for i in range(N):
        L.append(f"GRID,{int(nid[i])},,{g(X[i, 0])},{g(X[i, 1])},{g(X[i, 2])}")
    L.append("$ ---- shell elements (Radioss element ID)")
    for e in range(eid.size):
        n = [str(int(nid[c])) for c in conn[e, :et[e]]]
        L.append(f"{'CQUAD4' if et[e] == 4 else 'CTRIA3'},{int(eid[e])},{pids[int(ginv[e])]}," + ",".join(n))
    L.append("$ ---- PSHELL: generated PID <- (Radioss PID, T, material, design flag)")
    pmap = []
    for k in range(len(groups)):
        opid, t, mk, nd = groups[k]
        mid = mids[int(mk)]
        L.append(f"$ PSHELL {pids[k]} <- Radioss PID {int(opid)}, T={g(t)}, {'NON-DESIGN' if nd else 'design'}")
        L.append(f"PSHELL,{pids[k]},{mid},{g(t)},{mid},,{mid}")
        pmap.append({"pid": pids[k], "rad_pid": int(opid), "t": float(t), "mid": mid, "design": not bool(nd),
                     "n_elems": int(np.sum(ginv == k))})
    for k, (e_, nu_) in enumerate(mats):
        L.append(f"MAT1,{mids[k]},{g(e_)},,{g(nu_)}")
    L.append("$ ---- SPC1 (3-2-1 statically determinate supports; loads are self-equilibrated)")
    for n, dof in sup:
        L.append(f"SPC1,{spc_sid},{dof},{n}")
    tp = dtpg_layout(d.get("dtpg"))
    L.append("$ ---- DTPG: bead (topography) design on design PSHELLs; bead line = "
             + " ".join(x if x != "DRAW" else (tp["draw"] or "-") for x in
                        ([tp["bead_flag"]] if tp["bead_flag"] else []) + tp["bead_fields"]))
    L += card("DTPG", [dtpg_id, "PSHELL"] + design_pids[:6], fmt)
    rest = design_pids[6:]
    lead = [""] * (int(tp["pid_cont_col"]) - 2)
    per = 8 - len(lead)
    for k in range(0, len(rest), per):
        L += [ln for ln in card("X", [""] * 8 + lead + rest[k:k + per], fmt)[1:]]
    bw = 8 if fmt == "fixed" else None
    val = {"MW": real(b["min_width"], bw), "ANG": real(b["angle"], bw), "HGT": real(b["height"], bw),
           "BF": "YES" if b["buffzone"] else "NO", "SKIP": skip, "DRAW": tp["draw"], "-": ""}
    bead_line = ([tp["bead_flag"]] if tp["bead_flag"] else []) + [val[x] for x in tp["bead_fields"]]
    L += card("X", [""] * 8 + bead_line, fmt)[1:]
    lb, ub = b["bounds"]
    L += card("X", [""] * 8 + ["BOUNDS", real(lb, bw), real(ub, bw)], fmt)[1:]
    L.append("$ ---- responses / objective")
    refs = []
    if d["objective"] == "minmax":
        L += card("DRESP1", [comp_rid, "COMP", "COMP"], fmt)
        for k, lc in enumerate(load_cases):
            ref = lc.get("ref")
            ref = 1.0 if ref is None or not float(ref) > 0 else float(ref)
            refs.append(ref)
            L += card("DOBJREF", [obj_id, comp_rid, k + 1, "", real(ref, bw)], fmt)   # DOID RID SID NEGREF POSREF
    else:
        L += card("DRESP1", [comp_rid, "WCOMP", "WCOMP"], fmt)
    if bf_rid is not None:
        L += card("DRESP1", [bf_rid, "BEADF", "BEADFRAC", "DTPG", "", "", "", dtpg_id], fmt)
        L += card("DCONSTR", [bf_cid, bf_rid, "", real(d["beadfrac_max"], bw)], fmt)
    if srv is not None:
        L += card("DOPTPRM", ["DESMAX", int(srv["desmax"])], fmt)
    L.append("ENDDATA")

    # ---- 하중 inc
    tol = float(d["force_zero_tol_rel"])
    LI = [f"$ ESL load cases for {deck}.fem (FORCE, CID 0, external force on structure)"]
    n_force = []
    for k, lc in enumerate(load_cases):
        f = np.asarray(lc["f"], dtype=np.float64)
        ref = float(np.max(np.linalg.norm(f, axis=1))) if f.size else 0.0
        mask = np.abs(f) > tol * ref if ref > 0 else np.zeros(f.shape, bool)
        LI.append(f"$ LOAD SID {load_sids[k]} = SUBCASE {k + 1} {_ascii(lc.get('label') or '')} "
                  f"{_ascii(lc.get('entry_id') or '')} sum|F|={g(float(np.linalg.norm(f, axis=1).sum()))}")
        cnt = 0
        for i in np.flatnonzero(mask.any(axis=1)):
            fx, fy, fz = (f[i, c] if mask[i, c] else 0.0 for c in range(3))
            LI.append(f"FORCE,{load_sids[k]},{int(nid[i])},0,{real(1.0)},{g(fx)},{g(fy)},{g(fz)}")
            cnt += 1
        n_force.append(cnt)

    bat = ["@echo off", "setlocal",
           f"rem ESL bead topography - OptiStruct 2026.1 ({deck}.fem)",
           "rem OPTISTRUCT_BAT = optistruct.bat path, or ALTAIR_HOME = Altair install root.",
           "rem Extra arguments are passed through (e.g. run_optistruct.bat -check).",
           'cd /d "%~dp0"',
           'if not defined OPTISTRUCT_BAT set "OPTISTRUCT_BAT=%ALTAIR_HOME%\\hwsolvers\\scripts\\optistruct.bat"',
           'if not exist "%OPTISTRUCT_BAT%" (',
           '  echo [ERROR] optistruct.bat not found: "%OPTISTRUCT_BAT%"',
           "  echo Set OPTISTRUCT_BAT or ALTAIR_HOME and run again.",
           "  exit /b 1",
           ")",
           f'call "%OPTISTRUCT_BAT%" "{deck}.fem" -nt {int(d["nt"])} %*',
           "exit /b %ERRORLEVEL%"]

    readme = _readme(d, deck, load_cases, refs, design_pids, nondesign_pids, why, des, spc_sid, load_sids,
                     dtpg_id, comp_rid, obj_id, bf_rid, bf_cid, sup)

    def path(n):
        p = os.path.join(out_dir, n)
        if writer is not None:
            return writer.fresh_file(p, os.path.dirname(out_dir.rstrip(os.sep)) or out_dir)
        os.makedirs(out_dir, exist_ok=True)
        return p

    with open(path(f"{deck}.fem"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    with open(path("esl_loads.inc"), "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(LI) + "\n")
    with open(path("run_optistruct.bat"), "w", encoding="ascii", newline="\r\n") as fh:
        fh.write("\n".join(bat) + "\n")
    with open(path("README.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(readme)
    return U.jsonable({
        "files": [f"{deck}.fem", "esl_loads.inc", "run_optistruct.bat", "README.txt"],
        "deck": f"{deck}.fem", "card_format": fmt, "objective": d["objective"],
        "n_subcases": len(load_cases), "subcases": [{"subcase": k + 1, "label": lc.get("label"),
                                                    "entry_id": lc.get("entry_id"), "load_sid": load_sids[k],
                                                    "n_force": n_force[k], "ref": refs[k] if refs else None,
                                                    "weight": lc.get("weight")}
                                                   for k, lc in enumerate(load_cases)],
        "ids": {"spc_sid": spc_sid, "load_sids": load_sids, "mids": mids, "pids": pids, "dtpg": dtpg_id,
                "dresp_comp": comp_rid, "dobjref": obj_id if d["objective"] == "minmax" else None,
                "dresp_beadfrac": bf_rid, "dconstr_beadfrac": bf_cid, "max_used": cur[0]},
        "design_pids": design_pids, "nondesign_pids": nondesign_pids, "pshell_map": pmap,
        "n_design_elems": int(des.sum()), "n_nondesign_elems": int((~des).sum()), "nondesign_reasons": why,
        "bead": {**b, "skip": skip}, "beadfrac_max": d["beadfrac_max"], "supports": sup, "server": srv,
        "support_check": sr, "confidence": CONFIDENCE})


def _readme(d, deck, load_cases, refs, design_pids, nondesign_pids, why, des, spc_sid, load_sids, dtpg_id, comp_rid,
            obj_id, bf_rid, bf_cid, sup) -> str:
    b = d["bead"]
    lines = [
        f"ESL 비드(topography) 최적화 덱 — {deck}.fem (OptiStruct 2026.1)",
        "=" * 60, "",
        "파일",
        f"  {deck}.fem          메시(GRID/CQUAD4/CTRIA3/PSHELL/MAT1) + 3-2-1 SPC1 + DTPG + 응답/목적",
        "  esl_loads.inc       subcase별 FORCE (ESL 등가정적하중, 대상 메시로 매핑·정규화된 값)",
        "  run_optistruct.bat  실행 배치 (OPTISTRUCT_BAT 또는 ALTAIR_HOME 환경변수 필요, 인자 전달: -check 등)",
        "",
        "구성",
        f"  subcase {len(load_cases)}개 (SPC {spc_sid}, LOAD SID {load_sids[0]}..{load_sids[-1]})",
    ]
    for k, lc in enumerate(load_cases):
        lines.append(f"    SUBCASE {k + 1}: {lc.get('label')}  entry {lc.get('entry_id')}"
                     + (f"  POS(ref compliance)={refs[k]:.6g}" if refs else "")
                     + (f"  WEIGHT={lc.get('weight') if lc.get('weight') is not None else 1.0}"
                        if d['objective'] == 'weighted' else ""))
    lines += [
        f"  3-2-1 지지: {sup}  (하중은 자기평형 → 반력 ≈ 0 이어야 정상. SPCFORCE 로 확인)",
        f"  DTPG {dtpg_id}: 설계 PSHELL {design_pids}",
        f"    비드 최소폭 MW={b['min_width']}, 각도 ANG={b['angle']} deg, 높이 HGT={b['height']}, "
        f"버퍼 BF={'YES' if b['buffzone'] else 'NO'}, SKIP={str(b['skip']).upper()}, BOUNDS={b['bounds']}",
        "    비드 줄 칸 = " + " ".join(dtpg_layout(d.get("dtpg"))["bead_fields"])
        + " (설정 optdeck.dtpg). 방향 = 요소 법선(NORM). 단위는 모델 단위(길이).",
        f"  비설계 PSHELL {nondesign_pids} (요소 {int((~des).sum())}개: PID {why['by_pid']}, "
        f"design_pids 밖 {why['by_design_pids']}, 노드 반경 {why['by_radius']}"
        + (f", 금지 영역 요소 {why['by_elems']}" if "by_elems" in why else "") + ")",
    ]
    srv = d.get("server")
    if srv is not None:
        lines.append(f"  서버 실행 opt_run {srv.get('opt_run_id')} {srv.get('scenario')}: DOPTPRM DESMAX={srv['desmax']}, "
                     "OUTPUT,H3D,ALL")
    if d["objective"] == "minmax":
        lines.append(f"  목적: MINMAX = {obj_id} → DOBJREF {obj_id} × {len(load_cases)} (subcase별 DRESP1 "
                     f"{comp_rid} COMP / POS). 최대 (컴플라이언스/기준값) 최소화.")
    else:
        lines.append(f"  목적: DESOBJ(MIN) = {comp_rid} (WCOMP, subcase WEIGHT 가중합)")
    if bf_rid is not None:
        lines.append(f"  제약: BEADFRAC ≤ {d['beadfrac_max']} (DRESP1 {bf_rid}, DCONSTR {bf_cid}, DESGLB)")
    lines += [
        "",
        "확신도(이 환경에서 OptiStruct 실행 불가 — 사용자 실행으로 확인)",
    ]
    lines += [f"  {k}: {v}" for k, v in CONFIDENCE.items()]
    lines += [
        "",
        "실행",
        "  1) run_optistruct.bat -check   (문법 검사만)  → .out 에 오류 없는지",
        "  2) run_optistruct.bat          (최적화)",
        "  카드 오류가 나면 설정 optdeck.card_format: fixed 로 다시 생성하거나 .out 의 오류 카드명을 알려 주십시오.",
        "",
        "확인 항목",
        "  - 첫 반복(iteration 0)의 subcase별 컴플라이언스, SPCFORCE 반력이 하중 대비 작음(자기평형)",
        "  - 비드 패턴이 비설계 영역(마운트 주변)에 생기지 않음",
        "  - 한계: 선형 ESL(소성·접촉 비선형 무시), 인치 간 정규화 좌표 매핑 근사(기하 비례 가정)",
        "",
    ]
    return "\n".join(lines)
