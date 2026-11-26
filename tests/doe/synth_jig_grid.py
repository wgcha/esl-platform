"""v0.24.8 JG 합성(계약 esl_jig_grid_map.md §9): A 판(Case 메시) + 와셔 tie 묶음 + 가짜 Case ③ 지그 산출물(04_esl jig_disp·jig_spring
(·jig)) + ④ 형상 직접 비교(기준 = Case 메시, 형상 = 메시 입력 rad — gmsh 없음) · 옛 ③(scenario step — gmsh·paicad 를 가짜로) 세계.

Case 지그 = 실제 Case 와 같은 순수 함수(jig_bc.tie_rows·aux_rows·target·spring_k·build_bc·factorize·respond)로 만든다. 맞춤 하중 F =
K_A u_rel(응축 자유-자유 강성 — 자기평형)이라 Case 응답 = u_rel(재현 MAC 1) — 항등·정확도 비교의 기준이 단순하다.
골든(tests/doe/golden_v0248_c1)도 이 세계를 쓴다(옛 코드는 Case 지그를 읽지 않음)."""
from __future__ import annotations

import contextlib
import copy
import json
import os

import numpy as np
import synth_compare as scmp
import synth_doe as sd

from esl.library import _util as U

PROPS = {"t": 2.0, "E": 205000.0, "nu": 0.3}
LX, LZ = 200.0, 150.0
BOLTS = ((30.0, 25.0), (100.0, 20.0), (170.0, 25.0), (30.0, 125.0), (100.0, 130.0), (170.0, 125.0))
R_WASHER = 9.0
SOLVER = {"backend": "superlu", "drill_factor": 1e-4}
CFG_FULL = {"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}, "compare": {"mesh": {"size_mm": 5.0}}},
            "opt_run": {"solver": {"backend": "superlu"}}}
LT = {"schema": 1, "method": "work"}


# ---------------------------------------------------------------- 메시
def plate(h: float = 5.0, *, bead=None, tri_cols: int = 2, node_base: int = 1, offset=(0.0, 0.0, 0.0)) -> dict:
    return scmp.lt_plate_mesh(Lx=LX, Lz=LZ, h=h, bead=bead, n_tria_cols=tri_cols, node_base=node_base, offset=offset,
                              props=PROPS)


def delaunay_plate(h: float = 3.0, *, seed: int = 2, ring_n: int = 17, ring_r=(4.5, 9.0, 12.5), node_base: int = 300001) -> dict:
    """전삼각 Delaunay 판(v0.24.8 fix JG-23 — 독립 검증의 메시만 다른 형상): 흔든 배경 점 + 볼트마다 동심 고리(ring_n 분할), 판 평면 y = 0.
    같은 설계(평판)라 강성 차이 = 메시 차이뿐."""
    from scipy.spatial import Delaunay
    rng = np.random.default_rng(seed)
    nx, nz = round(LX / h), round(LZ / h)
    pts = []
    for i in range(nx + 1):
        for j in range(nz + 1):
            x, z = i * LX / nx, j * LZ / nz
            if 0 < i < nx:
                x += rng.uniform(-0.25, 0.25) * LX / nx
            if 0 < j < nz:
                z += rng.uniform(-0.25, 0.25) * LZ / nz
            pts.append((x, z))
    pts = np.array(pts)
    keep = np.ones(len(pts), bool)
    rmax = max(ring_r) + 0.6 * h
    for bx, bz in BOLTS:
        keep &= np.hypot(pts[:, 0] - bx, pts[:, 1] - bz) > rmax
    pl = [tuple(p) for p in pts[keep]]
    for bx, bz in BOLTS:
        pl.append((bx, bz))
        for r in ring_r:
            n = max(6, int(round(ring_n * r / max(ring_r))))
            ph = rng.uniform(0, 2 * np.pi)
            for t in np.linspace(0, 2 * np.pi, n, endpoint=False) + ph:
                pl.append((bx + r * np.cos(t), bz + r * np.sin(t)))
    pts = np.array(pl)
    tri = Delaunay(pts).simplices
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    cr = (b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0]
    tri = tri[np.abs(cr) > 2e-6 * h * h]
    cr = cr[np.abs(cr) > 2e-6 * h * h]
    tri[cr < 0] = tri[cr < 0][:, [0, 2, 1]]
    X = np.stack([pts[:, 0], np.zeros(len(pts)), pts[:, 1]], 1)
    ne = tri.shape[0]
    conn = np.concatenate([tri, -np.ones((ne, 1), np.int64)], axis=1).astype(np.int64)
    return {"node_id": node_base + np.arange(X.shape[0], dtype=np.int64), "x0": X, "elem_id": 1 + np.arange(ne, dtype=np.int64),
            "elem_type": np.full(ne, 3, dtype=np.int8), "conn": conn, "elem_pid": np.full(ne, 10, dtype=np.int64),
            "elem_mid": np.full(ne, 1, dtype=np.int64), "thickness": np.full(ne, float(PROPS["t"])),
            "E": np.full(ne, float(PROPS["E"])), "nu": np.full(ne, float(PROPS["nu"]))}


def holes(mesh: dict, which, r: float = 13.0) -> dict:
    """볼트 which(BOLTS 인덱스)의 중심 r 안 요소를 뺀 메시(와셔 면 없음 — 체결부가 Case 와 다른 형상, v0.24.8 fix JG-24)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    conn = np.asarray(mesh["conn"], dtype=np.int64)
    cen = np.array([X[[n for n in e if n >= 0]].mean(0) for e in conn])
    keep = np.ones(len(cen), bool)
    for bx, bz in [BOLTS[i] for i in which]:
        keep &= np.hypot(cen[:, 0] - bx, cen[:, 2] - bz) > r
    used = np.unique(conn[keep][conn[keep] >= 0])
    remap = -np.ones(X.shape[0], np.int64)
    remap[used] = np.arange(used.size)
    cn = conn[keep].copy()
    cn[cn >= 0] = remap[cn[cn >= 0]]
    ne = cn.shape[0]
    out = {k: np.asarray(v)[keep] for k, v in mesh.items() if k in ("elem_type", "elem_pid", "elem_mid", "thickness", "E", "nu")}
    return {**out, "node_id": np.asarray(mesh["node_id"])[used], "x0": X[used], "conn": cn, "elem_id": 1 + np.arange(ne, dtype=np.int64)}


def tie_idx(mesh: dict, bolts=BOLTS, r: float = R_WASHER) -> np.ndarray:
    """와셔 면 tie = 볼트 중심(x, z)에서 r 안 노드(판 평면 거리)."""
    X = np.asarray(mesh["x0"], dtype=np.float64)
    sel = np.zeros(X.shape[0], bool)
    for bx, bz in bolts:
        sel |= np.hypot(X[:, 0] - bx, X[:, 2] - bz) <= r + 1e-9
    return np.flatnonzero(sel)


def sup321(mesh: dict) -> list:
    """3-2-1 지지(노드 인덱스, dof 문자열) — 엔트리 지지(synth_opt.supports_321)와 같은 노드."""
    nid = np.asarray(mesh["node_id"], dtype=np.int64)
    return [(int(np.searchsorted(nid, n)), str(d)) for n, d in sd.so.supports_321(mesh)]


def u_drop(mesh: dict, k: int = 0) -> np.ndarray:
    """엔트리 k 의 낙하 변위(파트 프레임 — 매끈한 굽힘 + 국부 융기)."""
    b, loc = ((1.0, 0.3), (0.3, 1.0), (0.6, 0.6))[k % 3]
    return scmp.lt_u_drop(mesh, bend=b, local=loc, sigma=12.0, at=(0.3 + 0.3 * (k % 2), 0.5))


def forces(mesh: dict, u) -> np.ndarray:
    return scmp.lt_esl_forces(mesh, u)


# ---------------------------------------------------------------- 가짜 Case ③ 지그(실제 Case 와 같은 순수 함수)
def shell(mesh: dict):
    from esl.mech.shell import ShellModel, solver_check_kwargs
    return ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                      drill_factor=1e-4, backend="superlu", **solver_check_kwargs(SOLVER))


def case_jig(mesh: dict, u_rel, F, *, methods=("prescribed", "spring"), td: str = "normal", k_mode: str = "auto",
             alpha: float = 0.01, k_value=None, kink: float = 45.0, dup: float = 10.0, J=None, sup=None) -> dict:
    """Case 지그 산출물 {src: (npz dict, json dict)} — pipeline._jig_esl·_jig_method 와 같은 키·같은 BC 함수."""
    from esl.mech import jig_bc, kabsch
    X = np.asarray(mesh["x0"], dtype=np.float64)
    J = tie_idx(mesh) if J is None else np.asarray(J, dtype=np.int64)
    sup = sup321(mesh) if sup is None else sup
    tie = jig_bc.tie_rows(mesh, J, td, kink_deg=kink)
    aux = jig_bc.aux_rows(X, sup, tie, td, dup_deg=dup)
    sm = shell(mesh)
    fm = np.ones(X.shape[0], bool)
    out = {}
    for m in methods:
        row = jig_bc.METHODS[m]
        tg = jig_bc.target(row["frame"], X, u_rel, J, fm)
        k = None
        if row["tie_stiff"] != "hard":
            k = jig_bc.spring_k(sm, tie, mode=k_mode, alpha=alpha, value=k_value)
        BC = jig_bc.build_bc(row, tie, aux, tg["u_tgt"], k=k)
        h = jig_bc.factorize(sm, BC)
        r = jig_bc.respond(h, F, BC)
        u_val = kabsch.remove_rigid(X, r["u"][:, :3])[0]
        num = float(np.sum(u_val * u_rel)) ** 2
        den = float(np.sum(u_val * u_val)) * float(np.sum(u_rel * u_rel))
        mac = num / den if den > 0 else 0.0
        um_t, um_f = float(np.linalg.norm(u_rel, axis=1).max()), float(np.linalg.norm(u_val, axis=1).max())
        en = dict(r["energy"])
        z = {"node_id": np.asarray(mesh["node_id"], dtype=np.int64), "f": np.asarray(F, dtype=np.float64),
             "a": np.zeros(0), "u_val": u_val, **jig_bc.save_bc(BC), "jig_idx": J, "basis_sha": np.asarray("synth")}
        doc = {"schema": "esl/case_jig/1", "source": row["src"], "method": m, "method_name": row["name"], "tie_dofs": td,
               "status": "ok", "code": None, "reason": None, "fix": {"n_jig": int(J.size)},
               "fit": {"mac": mac, "umax_err": abs(um_f / um_t - 1.0) if um_t > 0 else 0.0},
               "recon": {"status": "ok", "mac": mac, "umax_err": (um_f / um_t - 1.0) if um_t > 0 else 0.0},
               "energy": {**en, "aux_reaction_rel": 0.0},
               "spring": None if k is None else {"k_mode": k_mode, "alpha": float(alpha), "k_value": k_value},
               "warnings": [], "info": []}
        out[row["src"]] = (z, doc)
    return out


def write_case(case_dir: str, mesh: dict, u_rel, jig: dict) -> str:
    d = os.path.join(case_dir, "04_esl")
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "u_rel.npz"), node_id=np.asarray(mesh["node_id"], dtype=np.int64),
                        u_rel=np.asarray(u_rel, dtype=np.float64))
    for src, (z, doc) in jig.items():
        np.savez_compressed(os.path.join(d, f"{src}.npz"), **z)
        with open(os.path.join(d, f"{src}.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    return d


def save_entry(lib: str, eid: str, mesh: dict, f, u_rel, case_dir: str | None) -> str:
    """라이브러리 항목(raw f·u_rel·3-2-1, meta source.case_dir = 가짜 Case)."""
    from esl.library import entry as en
    from esl.library import normalize as nz
    X = np.asarray(mesh["x0"], dtype=float)
    fr = nz.frame(X, None, mesh["conn"], mesh["elem_type"])
    sup = sd.so.supports_321(mesh)
    n = X.shape[0]
    raw = {**{k: np.asarray(mesh[k]) for k in ("node_id", "x0", "elem_id", "elem_type", "conn", "elem_pid", "elem_mid",
                                               "thickness", "E", "nu")},
           "f": np.asarray(f, dtype=float), "u_rel": np.asarray(u_rel, dtype=float), "is_bc": np.zeros(n, dtype=bool),
           "support_node_id": np.array([s for s, _ in sup], dtype=np.int64), "support_dof": np.array([d for _, d in sup])}
    gs = nz.grid_summary(X, raw["f"], 24, 14, fr, top_n=5, node_id=raw["node_id"])
    meta = {"entry_id": eid, "frame": fr, "grid": {"nx": 24, "ny": 14},
            "esl": {"supports": [{"node_id": int(a), "dof": d} for a, d in sup]},
            "model": {"inch": 75, "part_id": sd.PART_ID, "part_title": sd.PART_TITLE, "max_ids": {}},
            "scene": {"scene": None}, "mode": None, "source": {"case_dir": case_dir} if case_dir else {}}
    d = os.path.join(str(lib), eid)
    en.save(en.LibraryEntry(meta=meta, summary={k: gs[k] for k in en.SUMMARY_KEYS if k in gs}, raw=raw), d)
    return d


def entries(root: str, A: dict, n: int = 2, *, case: bool = True, **jkw) -> list:
    """엔트리 n 개(+ 엔트리마다 가짜 Case 지그). 반환 [{id, dir, label, case_dir}]."""
    out = []
    for k in range(n):
        u = u_drop(A, k)
        F = forces(A, u)
        cd = None
        if case:
            cd = os.path.join(root, "cases", f"c{k}")
            write_case(cd, A, u, case_jig(A, u, F, **jkw))
        d = save_entry(os.path.join(root, "lib"), f"E{k}", A, F, u, cd)
        out.append({"id": f"E{k}", "dir": d, "label": f"씬 {k}", "case_dir": cd})
    return out


# ---------------------------------------------------------------- 스냅샷
def rank_snap(*, grid: dict | bool | None = None, methods=None, metric: str = "jig") -> dict:
    """새 스터디 스냅샷 doe.rank(백엔드 rank_snapshot 과 같은 키 — 설정 기본값). grid = True → DEFAULTS rank.jig_grid 사본,
    dict → 그 블록, None/False → 키 없음(옛 = v0.24.7)."""
    from esl.doe import DEFAULTS
    r = DEFAULTS["rank"]
    out = {"metric": metric, "lin_form": r["lin_form"], "lin_valid": float(r["lin_valid"]),
           "imbalance_warn": float(r["imbalance_warn"]), "schema": 2, "jig": copy.deepcopy(r["jig"]),
           "eval_region": {"mode": "part", "free_edge_mm": 10.0, "boxes": []}}
    if methods is not None:
        out["jig"]["methods"] = list(methods)
    if grid is True:
        out["jig_grid"] = copy.deepcopy(r["jig_grid"])
    elif isinstance(grid, dict):
        out["jig_grid"] = copy.deepcopy(grid)
    return out


# ---------------------------------------------------------------- ④ 세계(기준 = Case 메시, 형상 = 메시 입력)
SHAPES_DEFAULT = (("d001", {"h": 4.0, "tri_cols": 6, "node_base": 100001}),
                  ("d002", {"h": 5.0, "bead": (60.0, 90.0, 4.0)}))


def write_shape_rad(root: str, did: str, spec: dict) -> dict:
    m = spec["mesh"] if "mesh" in spec else plate(**spec)       # v0.24.8 fix: 메시 dict 를 그대로 넣을 수 있음(전삼각 Delaunay 등)
    up = os.path.join(root, "up", did)
    os.makedirs(up, exist_ok=True)
    p = os.path.join(up, f"{did}.rad")
    sd.write_mesh_rad(p, m)
    return {"id": did, "name": f"s{did}", "file_name": os.path.basename(p), "path": p, "upload_root": up,
            "source": "mesh", "part_id": sd.PART_ID, "reference": False}


def cmp_world(root: str, *, hA: float = 5.0, shapes=SHAPES_DEFAULT, rank: dict | None = None, n_ent: int = 2,
              case: bool = True, lt: dict | None = None, sid: str = "J4", **jkw) -> tuple[dict, str, dict]:
    """④ 스터디 doe 스냅샷 + 출력 폴더. 반환 (doe, out, A)."""
    A = plate(hA)
    ents = entries(root, A, n_ent, case=case, **jkw)
    os.makedirs(os.path.join(root, "case"), exist_ok=True)
    rad = os.path.join(root, "case", "model_0000.rad")
    sd.write_mesh_rad(rad, A)
    shp = [write_shape_rad(root, did, sp) for did, sp in shapes]
    doe = {"id": sid, "scenario": "compare", "title": "jg", "cfg": copy.deepcopy(CFG_FULL),
           "entries": [{"id": e["id"], "dir": e["dir"], "label": e["label"]} for e in ents], "shapes": shp,
           "reference_source": "case", "inch": 75, "props": dict(PROPS),
           "base": {"entry_id": "E0", "case_id": "c1", "rad_path": rad, "part_title": sd.PART_TITLE,
                    "case_dir": os.path.dirname(rad)},
           "load_transfer": copy.deepcopy(LT if lt is None else lt)}
    if rank is not None:
        doe["rank"] = rank
    return doe, os.path.join(root, "run"), A


def run_stage(out: str, doe: dict, stage: str, **kw):
    from esl.doe import stages as stg
    return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, lambda m: None)


def run_cmp(doe: dict, out: str, *, post: bool = True) -> dict | None:
    for s in ("bd_input", "bd_mesh0", "bd_loads"):
        run_stage(out, doe, s)
    cmp_ = U.read_json(os.path.join(out, "prep", "compare.json"))
    for x in cmp_["shapes"]:
        if x["status"] == "READY":
            run_stage(out, doe, "bd_eval", design=x["id"])
    return run_stage(out, doe, "bd_post") if post else None


# ---------------------------------------------------------------- 옛 ③ 세계(scenario step — gmsh·paicad 가짜)
STEP_SP = {"method": "fullfact", "levels": 2, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 3.0, "hi": 6.0}]}
STEP_BASE = {"h": 6.0, "tri_cols": 3, "node_base": 500001}


def _fake_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@contextlib.contextmanager
def fake_gmsh(monkeypatch):
    """mg.available·run_isolated 를 가짜로: 입력 파일(json 명세) → plate(**명세) 메시. 메타 = run_isolated 와 같은 키."""
    from esl.doe import mesh_gmsh as mg

    def run_isolated(src, out_dir, h, cfg, props, **kw):
        spec = _fake_spec(src)
        m = plate(**spec)
        mesh = {k: m[k] for k in mg.MESH_KEYS}
        os.makedirs(out_dir, exist_ok=True)
        mg.save_npz_det(os.path.join(out_dir, mg.MESH_NPZ), mesh)
        et = np.asarray(m["elem_type"]).astype(int)
        meta = {"n_nodes": int(m["x0"].shape[0]), "n_elems": int(et.size), "quad_frac": float(np.mean(et == 4)),
                "quality": {}, "warnings": [], "seconds": 0.0, "wall_seconds": 0.0}
        U.write_json(os.path.join(out_dir, mg.MESH_JSON), {"schema": "esl/doe_mesh/1", **meta, "errors": []})
        return mesh, meta
    def export_step_isolated(*_a, **_k):
        from esl.errors import EslError
        raise EslError("MESH_FAILED", "가짜 gmsh — STEP 내보내기 없음")
    monkeypatch.setattr(mg, "available", lambda: (True, "fake"))
    monkeypatch.setattr(mg, "run_isolated", run_isolated)
    monkeypatch.setattr(mg, "export_step_isolated", export_step_isolated)
    yield


def step_world(root: str, *, hA: float = 5.0, rank: dict | None = None, n_ent: int = 2, case: bool = True,
               lt: dict | None = None, sid: str = "J3", **jkw) -> tuple[dict, str, dict]:
    A = plate(hA)
    ents = entries(root, A, n_ent, case=case, **jkw)
    up = os.path.join(root, "up")
    os.makedirs(up, exist_ok=True)
    step = os.path.join(up, "nominal.step")
    U.write_json(step, STEP_BASE)
    doe = {"id": sid, "scenario": "step", "title": "jg3", "cfg": copy.deepcopy(CFG_FULL),
           "entries": [{"id": e["id"], "dir": e["dir"], "label": e["label"]} for e in ents],
           "step": {"path": step, "file_name": "nominal.step"}, "inch": 75, "props": dict(PROPS), "mesh_size_mm": 6.0,
           "load_transfer": copy.deepcopy(LT if lt is None else lt)}
    if rank is not None:
        doe["rank"] = rank
    return doe, os.path.join(root, "run"), A


def design_spec(values: dict) -> dict:
    """옛 ③ 안 BREP(가짜 json) — 비드 깊이 변수 → 기준 메시와 같은 h 의 띠 비드."""
    d = float(next(iter(values.values()))) if values else 0.0
    return {**STEP_BASE, "bead": (60.0, 90.0, d)}


def run_step(doe: dict, out: str, A: dict, *, post: bool = True) -> dict | None:
    """bd_input → bd_mesh0 → (가짜 extract) → bd_loads → bd_matrix → bd_eval(d000 + 안, 가짜 paicad brep) → bd_post."""
    run_stage(out, doe, "bd_input")
    run_stage(out, doe, "bd_mesh0")
    t_mesh = U.load_npz(os.path.join(out, "prep", "base_mesh.npz"))
    sd.write_extract(os.path.join(out, "prep", "extract"), sd.features_doc({"x0": np.asarray(t_mesh["x0"])}, 1))
    run_stage(out, doe, "bd_loads")
    run_stage(out, doe, "bd_matrix", rev=1, spec=STEP_SP)
    m = U.read_json(os.path.join(out, "doe", "1", "matrix.json"))
    run_stage(out, doe, "bd_eval", rev=1, design="d000")
    for d in m["designs"][1:]:
        dd = os.path.join(out, "run", "designs", d["id"], "update")
        os.makedirs(dd, exist_ok=True)
        U.write_json(os.path.join(dd, "sample.brep"), design_spec(d["values"]))
        run_stage(out, doe, "bd_eval", rev=1, design=d["id"], paicad={"ok": True})
    return run_stage(out, doe, "bd_post", rev=1) if post else None


# ---------------------------------------------------------------- 순수 모듈 시험용(grid_map 입력 — stages._jg_prep·_jg_shape 와 같은 조립)
GRID_CFG = {"tie_capture_rel": 0.25, "tie_snap_rel": 0.75, "tie_normal_deg": 30.0, "tie_miss_frac_max": 0.1, "sample_nbr": 1,
            "sample_normal_deg": 45.0}


def fold_plate(h: float = 5.0, *, xf: float = 150.0, deg: float = 60.0, **kw) -> dict:
    """x > xf 부분을 꺾임선(x = xf) 둘레로 deg 만큼 돌린 판(요소 크기 유지 — 꺾임선 노드 = 법선 랭크 2, 90° = 수직 플랜지)."""
    m = plate(h, **kw)
    X = np.asarray(m["x0"], dtype=np.float64).copy()
    d = np.maximum(0.0, X[:, 0] - xf)
    th = np.radians(deg)
    X[:, 0] = np.where(X[:, 0] > xf, xf + d * np.cos(th), X[:, 0])
    X[:, 1] = X[:, 1] + d * np.sin(th)
    m["x0"] = X
    return m


def frame_of(mesh: dict) -> dict:
    from esl.library import normalize as nz
    return nz.frame(np.asarray(mesh["x0"], dtype=np.float64), None, mesh["conn"], mesh["elem_type"])


def grid_group(A: dict, us: list, cjs: list, methods, cell: float = 3.0, sup=None) -> dict:
    """엔트리들(u_rel, Case 지그) → grid_map 묶음(stages._jg_prep 과 같은 조립: tie = 스프링 출처 우선)."""
    from esl.mech import grid_map as gm
    from esl.mech import jig
    from esl.mech import jig_bc
    srcs = [jig_bc.METHODS[m]["src"] for m in methods]
    sp_src = [jig_bc.METHODS[m]["src"] for m in methods if jig_bc.METHODS[m]["tie_stiff"] != "hard"]
    rep = cjs[0][sp_src[0] if sp_src else srcs[0]][0]
    P, td, tr = gm.case_tie({k: rep[k] for k in jig_bc.BC_KEYS})
    frames = sorted({jig_bc.METHODS[m]["frame"] for m in methods})
    U = {}
    for fr in frames:
        if fr == "part":
            U[fr] = np.stack([np.asarray(u, dtype=np.float64) for u in us])
        else:
            U[fr] = np.stack([jig.target_disp(A["x0"], u, P, np.ones(len(u), bool))["u_tgt"] for u in us])
    spr = {s: (cjs[0][s][0]["sp_node"], cjs[0][s][0]["sp_k"]) for s in sp_src}
    sup = sup321(A) if sup is None else sup
    return gm.build_group(A, frame_of(A), cell, P, td, tr, U, spr, sup_x=np.asarray(A["x0"])[[n for n, _ in sup]])


def shape_loads(A: dict, mesh_S: dict, Fs: list, cell: float = 3.0, h: float = 3.0) -> list:
    """Case 맞춤 하중 → 형상 셀 전달(공용 실행기 run_transfer_plan — stages._plan_loads 와 같은 함수)."""
    from esl.doe import DEFAULTS
    from esl.doe import load_transfer as ltm
    fr_A, fr_S = frame_of(A), frame_of(mesh_S)
    dst = ltm.dst_mesh(mesh_S, fr_S, None, h)
    srcs = [ltm.src_load(f"E{k}", {k_: A[k_] for k_ in ("node_id", "x0", "conn", "elem_type")}, F, fr_A)
            for k, F in enumerate(Fs)]
    m = {"name": "cell", "cell_size_mm": cell, "work": DEFAULTS["load_transfer"]["work"], "mapping_opts": None,
         "cell_min_mm": DEFAULTS["load_transfer"]["cell_min_mm"]}
    L, info = ltm.run_transfer_plan({"identity": {"key": "none"}, "placement": {"kind": "global"}}, srcs, dst, m, {})
    return L, info
