"""워커 진입점 (계약 esl_bead_doe.md §4·§9): ``run_stage(spec, echo)`` → bd_input·bd_mesh0·bd_loads·bd_matrix·bd_eval·bd_post.

워커(D3 core_adapter)가 자식 프로세스에서 부른다. paicad 는 실행하지 않는다(LOCAL step 은 워커, 여기서는 결과 읽기만).
쓰기는 ``spec["out"]`` (= ``<esl_root>/_doe/<id>/``) 아래만 — Writer 입력 목록(라이브러리 항목·① Case 입력 폴더·
업로드 폴더)에는 쓰지 않는다. 반환 dict 의 ``warnings``·``info`` 를 워커가 작업 경고로 올린다.

spec
- ``stage``, ``out``, ``progress_path?``(진행률 0..100 정수 파일)
- ``doe``: {id, scenario, title?, created_at?, cfg(전체 설정: bead_doe·opt_run·commands …), core?(코어 설정: case·coord_check),
  mapping?(라이브러리 셀 매핑 옵션), entries[{id, dir, label?, case?}], base?{entry_id, rad_path, part_title, case_dir}(①),
  step{path, file_name, sha256?}, mesh?{path, upload_root, part_title?}(②), inch?, props?{t,E,nu}(③), mesh_size_mm?(③),
  rev?(bd_matrix·bd_eval·bd_post), spec?(DoeSpec, bd_matrix), matrix_sha256?(bd_matrix 대조), paicad_version?,
  design?(bd_eval 안 id 또는 "noise"), paicad?{ok, code, status, message, seconds}(bd_eval: 워커 paicad 판정),
  input_roots?[(이름, 경로)](추가 입력 보호)}

폴더(§4): input/{step/, mesh/} · prep/{base_mesh.npz, base.json, input.json, mesh0/, loads.npz, params.json, plan.json,
boundary.json, extract/, fixed/, a_fixed/, tag/ (paicad 출력은 워커)} · doe/<rev>/{matrix.json, cells.json,
thumb_options.json, values/<did>.json, grid/} · run/designs/<did>/{paicad/{update,morph,check,out_files} | update/,
mesh/, design.npz, result.json, done.json} · post/ · best/<did>/ · report.html · doe.json.
"""
from __future__ import annotations

import csv
import io
import os
import shutil

import numpy as np

from esl.doe import FAILED, SKIPPED, load_method_sources, opt_settings, settings
from esl.doe import boundary as bnd
from esl.doe import evaluate as ev
from esl.doe import matrix as mx
from esl.doe import mesh_gmsh as mg
from esl.doe import nodes as nd
from esl.doe import paicad_io as pio
from esl.doe import rank as rk
from esl.doe import scenario as sc
from esl.errors import EslError
from esl.fsutil import atomic_replace
from esl.library import _util as U

STAGES = ("bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post", "bd_select_grid")
BASELINE = "d000"
NOISE = "noise"
FAILED_SOLVE_CODES = ("SUPPORT_DEGENERATE", "SOLVER_SINGULAR", "SOLVER_OUT_OF_MEMORY", "NODE_NOT_IN_PART",
                      "MAPPING_DEGENERATE", "INPUT_INVALID", "UNSUPPORTED_ELEMENT")
FAILED_MORPH_CODES = ("MORPH_NODES_MISSING", "RAD_PARSE_ERROR", "PATH_OUTSIDE_ROOT")


# ---------------------------------------------------------------- 공통
class Ctx:
    def __init__(self, spec: dict):
        self.spec = spec
        self.D = spec["doe"]
        self.out = os.path.abspath(spec["out"])
        self.full_cfg = self.D.get("cfg") or {}
        self.cfg = settings({"bead_doe": self.full_cfg.get("bead_doe") or {}})
        self.ocfg = opt_settings(self.full_cfg)
        self.scn = self.D["scenario"]
        self.writer = U.Writer(self.out, inputs=self.inputs())
        self.max_mb = float(self.cfg["limits"]["max_json_mb"])
        self._prog_last = -1

    def inputs(self) -> list:
        ins = [("라이브러리 항목", e["dir"]) for e in self.D.get("entries") or []]
        b = self.D.get("base") or {}
        if b.get("case_dir") or b.get("rad_path"):
            ins.append(("Case 입력", b.get("case_dir") or os.path.dirname(b["rad_path"])))
        m = self.D.get("mesh") or {}
        if m.get("upload_root"):
            ins.append(("업로드", m["upload_root"]))
        st = self.D.get("step") or {}
        if st.get("path"):
            ins.append(("STEP 업로드", os.path.dirname(st["path"])))
        for sh in self.D.get("shapes") or []:          # ④ 형상 STEP 업로드(읽기만)
            if sh.get("path"):
                ins.append(("STEP 업로드", os.path.dirname(sh["path"])))
        ins += [tuple(x) for x in self.D.get("input_roots") or []]
        return ins

    def p(self, *parts) -> str:
        return os.path.join(self.out, *parts)

    def progress(self, pct: float) -> None:
        path = self.spec.get("progress_path")
        v = int(max(0.0, min(100.0, float(pct))))
        if not path or v <= self._prog_last:
            return
        self._prog_last = v
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="ascii") as fh:
            fh.write(str(v))
        atomic_replace(tmp, path)

    def write_json(self, rel: str, obj) -> str:
        p = self.p(rel)
        self.writer.makedirs(os.path.dirname(p))
        U.write_json(self.writer.guard(p), obj)
        return rel

    def fresh(self, rel: str) -> str:
        return self.writer.fresh_dir(self.p(rel), self.out)

    def entries(self, raw: bool = True) -> list:
        from esl.library.entry import load
        return [load(e["dir"], raw=raw) for e in self.D["entries"]]

    def parse_kw(self) -> dict:
        cc = (self.D.get("core") or {}).get("case") or {}
        return {"match": cc.get("part_title_match") or "exact_ci",
                "max_include_depth": int(cc.get("rad_include_max_depth") or 8),
                "include_path_map": cc.get("include_path_map") or None}

    def coord_tol(self) -> float:
        from esl.config import COORD_CHECK_DEFAULTS
        return float(((self.D.get("core") or {}).get("coord_check") or {}).get("max_rel")
                     or COORD_CHECK_DEFAULTS["max_rel"])

    def max_line(self):
        from esl.rad.parser import max_line_bytes_of
        return max_line_bytes_of((self.D.get("core") or {}).get("case"))

    def solver_cfg(self) -> dict:
        return self.ocfg["solver"]

    def mapping_opts(self) -> dict | None:
        return self.D.get("mapping") or None


def run_stage(spec: dict, echo=print) -> dict:
    fn = {"bd_input": bd_input, "bd_mesh0": bd_mesh0, "bd_loads": bd_loads, "bd_matrix": bd_matrix,
          "bd_eval": bd_eval, "bd_post": bd_post, "bd_select_grid": bd_select_grid}.get(spec.get("stage"))
    if fn is None:
        raise EslError("INPUT_INVALID", f"알 수 없는 강성 평가 스터디 단계: {spec.get('stage')}")
    return fn(spec, echo)


def _copy_verified(src: str, dst: str, writer: U.Writer, sha: str | None = None) -> str:
    s0 = U.sha256_file(src)
    if sha and s0 != sha:
        raise EslError("STEP_INVALID", "업로드 STEP sha256 이 등록값과 다름")
    writer.makedirs(os.path.dirname(dst))
    shutil.copyfile(src, writer.guard(dst))
    if U.sha256_file(dst) != s0:
        raise EslError("STEP_INVALID", "STEP 복사본 sha256 불일치")
    return s0


# ---------------------------------------------------------------- 1 BD_INPUT
def bd_input(spec: dict, echo=print) -> dict:
    c = Ctx(spec)
    D = c.D
    c.progress(0)
    c.fresh("input")
    from esl.doe.assem_full import drop_derived
    drop_derived(c.out, c.writer.guard)          # prep/assem_full·a_assem_full = 재생성 파생물(_backup 제외)
    c.fresh("prep")
    if c.scn == "compare":
        return _cmp_input(c, echo)
    if c.scn == "select":
        return _sel_input(c, echo)
    st = D["step"]
    step_rel = os.path.join("input", "step", os.path.basename(st.get("file_name") or st["path"]))
    step_sha = _copy_verified(st["path"], c.p(step_rel), c.writer, st.get("sha256"))
    warns, info = [], []
    inp = {"schema": "esl/doe_input/1", "scenario": c.scn, "step": {"rel": step_rel.replace(os.sep, "/"),
                                                                    "sha256": step_sha}, "entries": [e["id"] for e in D["entries"]]}
    ents = c.entries(raw=c.scn == "same")
    c.progress(10)
    if c.scn == "same":
        b = D["base"]
        assem = sc.assem_dir_check(b.get("case_dir") or os.path.dirname(b["rad_path"]),
                                   c.cfg["same"]["max_assem_mb"])
        be = next((e for e in ents if e.meta["entry_id"] == b["entry_id"]), None)
        if be is None:
            raise EslError("INPUT_INVALID", "기준 ESL 이 선택 목록에 없음")
        echo(f"[bd_input] ① 기준 Case 입력 rad 제자리 읽기 (파트 {b['part_title']}, 조립 {assem['n_files']}개 파일 "
             f"{assem['total_mb']:.1f} MB)")
        t, inf = sc.same_base(b["rad_path"], b["part_title"], be, [e for e in ents if e is not be],
                              coord_tol_rel=c.coord_tol(), parse_kw=c.parse_kw())
        info += inf
        inp.update(assem="case", assem_info=assem, part_id=int(t.source["part_id"]), part_title=t.source["part_title"],
                   base_entry_id=b["entry_id"])
        meta = sc.save_base(t, c.p("prep"), c.scn, c.writer)
    elif c.scn == "mesh":
        m = D["mesh"]
        files = sc.copy_mesh_upload(m["path"], m["upload_root"], c.p("input", "mesh"), c.writer)
        main_rel = os.path.relpath(U.real_path(m["path"]), U.real_path(m["upload_root"]))
        from esl.opt.mesh_check import load_mesh
        mesh, minfo = load_mesh(c.p("input", "mesh", main_rel), m.get("part_title") or c.cfg["part_title"])
        warns += list(minfo.get("warnings") or [])
        if mesh.get("part_id") is None:
            raise EslError("MESH_INVALID", "B 메시에서 파트 id 를 얻지 못함(rad/inc 만 지원)")
        c.progress(60)
        t, size_info = sc.template_base(mesh, ents, c.ocfg["size"], inch=D.get("inch"),
                                        source={"file_name": os.path.basename(m["path"]), "files": files})
        warns += list(size_info.get("warnings") or [])
        inp.update(assem="input/mesh", mesh={"main": main_rel.replace(os.sep, "/"), "files": files},
                   part_id=int(mesh.get("part_id")), part_title=mesh.get("part_title"), size=size_info)
        meta = sc.save_base(t, c.p("prep"), c.scn, c.writer)
    else:
        inp.update(assem=None)
        meta = None
    c.progress(90)
    inp.update(warnings=warns, info=info)
    c.write_json(os.path.join("prep", "input.json"), inp)
    if meta:
        echo(f"[bd_input] 기준 메시 노드 {meta['n_nodes']} · 요소 {meta['n_elems']} · topo {str(meta['topo_sha256'])[:12]}…")
    for w in warns:
        echo(f"  경고: {w}")
    c.progress(100)
    return {"files": ["prep/input.json"] + (["prep/base_mesh.npz", "prep/base.json"] if meta else []),
            "warnings": warns, "info": info, "part_id": inp.get("part_id")}


# ---------------------------------------------------------------- 2 BD_MESH0 (③)
def _step_props(c: Ctx, base_raw: dict | None) -> tuple[dict, float]:
    props = c.D.get("props") or (sc.props_default(base_raw) if base_raw is not None else None)
    if not props:
        raise EslError("INPUT_INVALID", "③ 쉘 물성(props)이 없음")
    props = {"t": float(props["t"]), "E": float(props["E"]), "nu": float(props["nu"])}
    h = c.D.get("mesh_size_mm")
    if h is None:
        if base_raw is None:
            raise EslError("INPUT_INVALID", "③ 요소 크기가 없음")
        h = sc.mesh_size_default(base_raw, c.cfg["mesh"])
    return props, float(h)


def bd_mesh0(spec: dict, echo=print) -> dict:
    c = Ctx(spec)
    if c.scn == "compare":
        return _cmp_mesh0(c, echo)
    if c.scn != "step":
        return {"skipped": True, "files": [], "warnings": []}
    c.progress(0)
    ok, ver = mg.available()
    if not ok:
        raise EslError("GMSH_UNAVAILABLE", "gmsh 가 없어 ③ 베이스라인 메시를 만들 수 없음")
    inp = U.read_json(c.p("prep", "input.json"))
    ents = c.entries(raw=True)
    props, h = _step_props(c, ents[0].raw)
    d = c.fresh(os.path.join("prep", "mesh0"))
    try:
        mesh, meta = mg.run_isolated(c.p(inp["step"]["rel"]), d, h, c.cfg, props, opt_cfg=c.ocfg)
    except EslError as exc:
        if exc.code == "GMSH_UNAVAILABLE":
            raise
        mj = os.path.join(d, mg.MESH_JSON)
        errs = U.read_json(mj).get("errors") if os.path.isfile(mj) else []
        if any(e.get("code") == "MESH_TOO_LARGE" for e in errs or []):
            raise EslError("MESH_TOO_LARGE", exc.message) from None
        raise EslError("MESH_FAILED", exc.message) from None
    c.progress(80)
    t, size_info = sc.template_base(mesh, ents, c.ocfg["size"], inch=c.D.get("inch"),
                                    source={"file_name": os.path.basename(inp["step"]["rel"]), "gmsh": meta})
    bm = sc.save_base(t, c.p("prep"), c.scn, c.writer, extra={"props": props, "h": h, "gmsh_version": ver})
    warns = list(size_info.get("warnings") or []) + [w["message"] for w in meta.get("warnings") or []]
    inp.update(size=size_info, props=props, mesh_size_mm=h, gmsh_version=ver)
    c.write_json(os.path.join("prep", "input.json"), inp)
    c.write_json(os.path.join("prep", "mesh0.json"), meta)
    echo(f"[bd_mesh0] gmsh {ver} h {h:g} mm → 노드 {bm['n_nodes']} · 요소 {bm['n_elems']} · quad {meta['quad_frac']:.3f}")
    c.progress(100)
    return {"files": ["prep/mesh0/mesh.npz", "prep/mesh0.json", "prep/base_mesh.npz", "prep/base.json"],
            "warnings": warns, "props": props, "h": h}


# ---------------------------------------------------------------- 4 BD_LOADS
def _features(c: Ctx) -> dict:
    return pio.read_features(c.p("prep", "extract"), c.max_mb)


def _params_out(c: Ctx, doc: dict, frame: dict) -> dict:
    opts = c.cfg["paicad"].get("options") or {}
    return {"beads": pio.beads_table(doc, frame), "params": pio.params_table(doc, opts),
            "warnings": pio.extract_warnings(doc)}


def bd_loads(spec: dict, echo=print) -> dict:
    c = Ctx(spec)
    if c.scn == "compare":
        return _cmp_loads(c, echo)
    if c.scn == "select":
        return _sel_loads(c, echo)
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    ents = c.entries(raw=True)
    warns, info = [], []
    loads, linfo = sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"],
                                  (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]))
    warns += linfo["warnings"]
    loads_sha = sc.save_loads(c.p("prep"), t.mesh["node_id"], loads, c.writer)
    c.progress(80)
    doc = _features(c)
    params = _params_out(c, doc, t.frame)
    c.write_json(os.path.join("prep", "params.json"), params)
    res = None
    if c.scn in ("mesh", "step"):
        res = _boundary(c, t, ents, info)
        warns += [f"{w['code']}: {w.get('label') or w.get('entry_id')} {w.get('d_mm')}" for w in res["warnings"]]
        c.write_json(os.path.join("prep", "boundary.json"), res)
    plan = bnd.plan(t.mesh, t.frame, c.ocfg["keepout"], int(c.ocfg["ui"]["max_preview_points"]), features_doc=doc,
                    result=res)
    c.write_json(os.path.join("prep", "plan.json"), plan)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(loads={"sha256": loads_sha, **linfo}, n_beads=len(params["beads"]), n_params=len(params["params"]))
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_loads] ESL {len(loads)}개 하중({linfo['method']}), 비드 {len(params['beads'])} · 변수 {len(params['params'])}"
         + (f", 경계 경고 {res['n_warn']} · 정보 {res['n_info']}" if res else ""))
    c.progress(100)
    return {"files": ["prep/loads.npz", "prep/params.json", "prep/plan.json"] + (["prep/boundary.json"] if res else []),
            "warnings": warns, "info": info, "boundary": None if res is None else {"n_warn": res["n_warn"],
                                                                                 "n_info": res["n_info"]},
            "n_beads": len(params["beads"]), "n_params": len(params["params"])}


def _boundary(c: Ctx, t, ents, info: list) -> dict:
    """②③ 경계 매핑 경고(§8.2). A = 선택 ESL 기준 항목(첫 항목), B = 기준 메시."""
    bc = c.cfg
    a = ents[0]
    fa = a.meta["frame"]
    raw = a.raw
    nid = np.asarray(raw["node_id"], dtype=np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    sup = [{"node_id": int(s["node_id"]), "dof": s["dof"], "xyz": np.asarray(raw["x0"])[pos[int(s["node_id"])]].tolist()}
           for s in (a.meta.get("esl") or {}).get("supports") or [] if int(s["node_id"]) in pos]
    a_known = os.path.isfile(c.p("prep", "a_fixed", pio.SCAN_JSON))
    a_fx = None
    if a_known:
        try:
            a_fx = pio.fixed_points(pio.read_fixed(c.p("prep", "a_fixed"), c.max_mb))
        except EslError:
            a_known = False
    a_pts = bnd.a_fastener_points(fa, a_fx, sup)
    b_fx = None
    if c.scn == "mesh" and os.path.isfile(c.p("prep", "fixed", pio.SCAN_JSON)):
        fx = pio.read_fixed(c.p("prep", "fixed"), c.max_mb)
        b_fx = pio.fixed_points(fx)
        if not b_fx:
            info.append("B_NO_FASTENERS")
    cands = bnd.b_candidates(t.frame, t.mesh, b_fx, c.ocfg["keepout"]["hole_min_perimeter_mm"])
    lps = []
    for e in ents:
        lps += bnd.load_points([(e.meta["entry_id"], e.raw["node_id"], e.raw["x0"], e.raw["f"])], e.meta["frame"],
                               bc["boundary"]["load_share_min"], bc["limits"]["cluster_k_max"])
    from esl.opt.keepout import project_ab
    a_sab = [project_ab(fa, s["xyz"])[0].tolist() for s in sup]
    b_sab = [s["ab"] for s in sc.supports_ab(t)]
    res = bnd.check(fa, t.frame, a_pts, lps, cands, bc, a_fastener_known=a_known, a_supports_ab=a_sab,
                    b_supports_ab=b_sab)
    for x in res["info"]:
        info.append(x["code"])
    for q in res["load_points"]:
        q.pop("frame", None)
    return U.jsonable(res)


# ---------------------------------------------------------------- BD_MATRIX
def params_table(c: Ctx) -> list:
    if c.scn == "select":
        return U.read_json(os.path.join(_sel_dir(c, _sel_rev_doc(c)["selection_sha256"]), "params.json"))["params"]
    return U.read_json(c.p("prep", "params.json"))["params"]


def bd_matrix(spec: dict, echo=print) -> dict:
    c = Ctx(spec)
    rev = int(c.D["rev"])
    c.progress(0)
    t, _ = sc.load_base(c.p("prep"))
    sel_doc = _sel_prepare(c, t, echo) if c.scn == "select" else None
    tab = sel_doc["params"] if sel_doc else params_table(c)
    m = mx.generate(c.D["spec"], tab, c.cfg)
    want = c.D.get("matrix_sha256")
    if want and want != m["matrix_sha256"]:
        raise EslError("MATRIX_MISMATCH", f"워커 행렬 sha256 {m['matrix_sha256'][:12]}… ≠ API {str(want)[:12]}…")
    d = os.path.join("doe", str(rev))
    c.fresh(d)
    c.write_json(os.path.join(d, "matrix.json"), m)
    c.write_json(os.path.join(d, "cells.json"), mx.cells_doc(m))
    c.write_json(os.path.join(d, "thumb_options.json"), mx.thumb_options(c.cfg, t.frame, m["spec"], tab))
    for x in m["designs"]:
        c.write_json(os.path.join(d, "values", f"{x['id']}.json"), mx.values_doc(x["values"] if x["id"] != BASELINE
                                                                                 else {}))
    if sel_doc:
        c.write_json(os.path.join(d, SEL_REV_JSON), sel_doc["rev_doc"])
    opts = c.cfg["paicad"].get("options") or {}
    if opts:
        c.write_json(os.path.join("prep", "paicad_options.json"), opts)
    echo(f"[bd_matrix] rev {rev} {m['spec']['method']} 안 {m['n_designs']}(공칭 포함, 중복 제거 {m['dropped_duplicates']}) "
         f"sha {m['matrix_sha256'][:12]}…")
    c.progress(100)
    out = {"files": [f"{d}/matrix.json", f"{d}/cells.json", f"{d}/thumb_options.json"],
           "matrix_sha256": m["matrix_sha256"], "n_designs": m["n_designs"],
           "warnings": [f"{w['code']}: {w['name']}" for w in m["warnings"]]}
    if sel_doc:
        out.update(selection_sha256=sel_doc["rev_doc"]["selection_sha256"],
                   basis_sha256=sel_doc["rev_doc"]["basis_sha256"])
        out["files"].append(f"{d}/{SEL_REV_JSON}")
        out["warnings"] += sel_doc["warnings"]
    return out


# ---------------------------------------------------------------- BD_EVAL (안 1개)
def _matrix(c: Ctx) -> dict:
    return U.read_json(c.p("doe", str(int(c.D["rev"])), "matrix.json"))


def _design_values(c: Ctx, did: str) -> dict:
    if did == NOISE or c.scn == "compare":       # ④ 변수 없음
        return {}
    for x in _matrix(c)["designs"]:
        if x["id"] == did:
            return dict(x["values"]) if did != BASELINE else {}
    raise EslError("INPUT_INVALID", f"행렬에 없는 안: {did}")


def _cfg_hash(c: Ctx) -> str:
    keep = {"solver": c.solver_cfg(), "mesh": c.cfg["mesh"], "solve": c.cfg["solve"], "grid": c.ocfg["grid"],
            "mapping": c.mapping_opts(), "paicad_options": c.cfg["paicad"].get("options") or {}}
    if c.scn == "select":                       # 판정 설정도 이어하기 키에(select 만 — ①②③④ 해시 불변)
        keep.update(select=c.cfg["select"], quality=c.cfg["compare"]["quality"])
    return ev.config_hash(keep)


def design_dir(c: Ctx, did: str) -> str:
    return c.p("run", "designs", did)


def design_sha(c: Ctx, did: str) -> str:
    """BD-D-16 안 input_sha256(bd_eval 이 done.json 에 쓰는 값 — 워커 이어하기도 같은 함수). ④ = 형상 기준
    (STEP sha, 형상 메시 sha, 기준 frame sha, 물성·프로필·설정 해시)."""
    if c.scn == "compare":
        return _cmp_sha(c, did)
    bmeta = U.read_json(c.p("prep", "base.json"))
    inp = U.read_json(c.p("prep", "input.json"))
    if c.scn == "select":                       # BS-D-13: paicad 자리 = 선택 sha + 기저 sha
        r = _sel_rev_doc(c)
        return ev.input_sha256(_design_values(c, did), bmeta["mesh_sha256"], (inp.get("loads") or {}).get("sha256"),
                               _cfg_hash(c), f"select:{r['selection_sha256']}:{r['basis_sha256']}")
    return ev.input_sha256(_design_values(c, did), bmeta["mesh_sha256"], (inp.get("loads") or {}).get("sha256"),
                           _cfg_hash(c), c.D.get("paicad_version"))


def _design_mesh(c: Ctx, t, did: str, inp: dict, bmeta: dict, *, fresh: bool) -> tuple[dict, list, list, dict]:
    """(안 mesh(x0 = 안 좌표), supports, loads, mesh 정보)."""
    dd = design_dir(c, did)
    if did == BASELINE:
        _, loads = sc.load_loads(c.p("prep"))
        return dict(t.mesh), list(t.supports), loads, {"n_nodes": t.n_nodes, "n_elems": t.n_elems}
    if c.scn == "select":
        x, st = _sel_design(c, t, did)
        m = dict(t.mesh)
        m["x0"] = x
        _, loads = sc.load_loads(c.p("prep"))
        return m, list(t.supports), loads, {"n_nodes": t.n_nodes, "n_elems": t.n_elems, "quality": st["quality"],
                                            "fixed_max_mm": st["fixed"]["max_mm"]}
    if c.scn in ("same", "mesh"):
        pd = os.path.join(dd, "paicad")
        rels, _ = pio.run_out_files(os.path.join(pd, "check"), c.max_mb)
        moved = pio.morph_moved(os.path.join(pd, "morph"), c.max_mb)
        x, ninfo = nd.morphed_coords(os.path.join(pd, "out_files"), rels, t.mesh["node_id"], t.mesh["x0"],
                                     expected_moved=moved, max_line=c.max_line())
        m = dict(t.mesh)
        m["x0"] = x
        _, loads = sc.load_loads(c.p("prep"))
        return m, list(t.supports), loads, {"n_nodes": t.n_nodes, "n_elems": t.n_elems, **ninfo}
    # ③: 안 BREP → gmsh(베이스라인과 같은 h·옵션) → frame 고정 매핑
    brep = os.path.join(dd, "update", pio.SAMPLE_BREP)
    if not os.path.isfile(brep):
        raise EslError("FAILED_MESH", "안 sample.brep 가 없음(paicad update 결과)")
    md = os.path.join(dd, "mesh")
    if fresh:
        c.writer.fresh_dir(md, c.out)
    mesh, meta = mg.run_isolated(brep, md, float(bmeta["h"]), c.cfg, bmeta["props"], opt_cfg=c.ocfg,
                                 normal_ref=t.frame["n"])
    dt = sc.design_target(mesh, t.frame)
    loads, _ = sc.entry_loads(dt, c.entries(raw=False), c.mapping_opts())
    return dt.mesh, list(dt.supports), loads, {"n_nodes": meta["n_nodes"], "n_elems": meta["n_elems"],
                                                "quad_frac": meta["quad_frac"], "quality": meta["quality"],
                                                "seconds": meta.get("seconds")}


def bd_eval(spec: dict, echo=print) -> dict:
    """안 1개 평가 → run/designs/<did>/{design.npz, result.json, done.json}. 베이스라인 실패 → BASELINE_FAILED."""
    c = Ctx(spec)
    did = str(c.D["design"])
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    inp = U.read_json(c.p("prep", "input.json"))
    values = _design_values(c, did)
    sha = design_sha(c, did)
    dd = design_dir(c, did)
    c.writer.makedirs(dd)
    prev = ev.reusable(dd, sha)
    if prev is not None:
        echo(f"[{did}] 이전 결과 재사용({prev['status']})")
        c.progress(100)
        return {"design": did, "status": prev["status"], "reused": True}
    if c.scn == "select" and did != BASELINE:
        _, st = _sel_design(c, t, did)
        if st["state"] != "READY":              # 고정 침범·품질(미리보기와 같은 함수)
            doc = ev.result_doc(did, st["state"], values, mesh={"n_nodes": t.n_nodes, "n_elems": t.n_elems,
                                                                "quality": st["quality"],
                                                                "fixed_max_mm": st["fixed"]["max_mm"]},
                                code=st["code"], message=_sel_msg(st["code"]))
            U.write_json(c.writer.guard(os.path.join(dd, ev.RESULT_JSON)), doc)
            ev.write_done(dd, sha, st["state"], c.writer)
            echo(f"[{did}] {st['state']} {st['code']}")
            c.progress(100)
            return {"design": did, "status": st["state"], "reused": False, "code": st["code"]}
    pa = c.D.get("paicad")
    if pa is not None and not pa.get("ok", False) and did not in (BASELINE,):
        status = pa.get("status") or "FAILED_MORPH"
        doc = ev.result_doc(did, status, values, paicad={"code": pa.get("code"), "seconds": pa.get("seconds"),
                                                         "paicad_code": pa.get("paicad_code")},
                            code=pa.get("code"), message=pa.get("message"))
        U.write_json(c.writer.guard(os.path.join(dd, ev.RESULT_JSON)), doc)
        ev.write_done(dd, sha, status, c.writer)
        echo(f"[{did}] paicad {status} {pa.get('code') or ''}")
        return {"design": did, "status": status, "reused": False}
    status, code, msg, per, warns, mesh_info, solve = "OK", None, None, None, [], None, None
    try:
        if c.scn == "compare":
            mesh, sup, loads, mesh_info = _cmp_design_mesh(c, t, did)
        else:
            mesh, sup, loads, mesh_info = _design_mesh(c, t, did, inp, bmeta, fresh=True)
        c.progress(40)
        r = ev.evaluate(mesh, sup, loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"])
        per, warns, solve = r["per_esl"], r["warnings"], r["stats"]
        keep_mesh = (c.scn == "step" and did != BASELINE) or c.scn == "compare"
        ev.save_design(dd, mesh["node_id"], mesh["x0"], mesh if keep_mesh else None, c.writer)
    except EslError as exc:
        code, msg = exc.code, exc.message
        if exc.code in ("FAILED_MESH", "GMSH_UNAVAILABLE"):
            status = "FAILED_MESH"
        elif exc.code in FAILED_MORPH_CODES or exc.code in ("PAICAD_FAILED",):
            status = "FAILED_MORPH"
        else:
            status = "FAILED_SOLVE"
        if did == BASELINE:
            raise EslError("BASELINE_FAILED", f"베이스라인 평가 실패 {exc.code}: {exc.message}") from None
    paicad = None if pa is None else {"code": pa.get("code"), "seconds": pa.get("seconds")}
    doc = ev.result_doc(did, status, values, paicad=paicad, mesh=mesh_info, solve=solve, per_esl=per, warnings=warns,
                        code=code, message=msg)
    U.write_json(c.writer.guard(os.path.join(dd, ev.RESULT_JSON)), doc)
    ev.write_done(dd, sha, status, c.writer)
    tag = f"[{did} {_cmp_name(c, did)}]" if c.scn == "compare" else f"[{did}]"      # 이름은 로그 표시만
    if status == "OK":
        echo(f"{tag} solve {len(per)} ESL {solve['seconds']:.1f} s · C_max {doc['C_max']:.4g}")
    else:
        echo(f"{tag} {status} {code}: {msg}")
    c.progress(100)
    return {"design": did, "status": status, "reused": False, "code": code, "warnings": warns}


# ---------------------------------------------------------------- BD_POST
def _preview_states(c: Ctx, ids: list[str]) -> dict:
    gd = c.p("doe", str(int(c.D["rev"])), "grid")
    if not os.path.isfile(os.path.join(gd, pio.GRID_MANIFEST)):
        return {}
    g = pio.read_grid(gd, ids, c.max_mb)
    want = set(ids)          # 워커가 넣는 공칭 셀(nominal — 공칭 썸네일용)은 안이 아님
    return {r["id"]: r for r in g["cells"] if r["id"] in want}


def _collect(c: Ctx, m: dict) -> tuple[list[dict], dict]:
    ids = [x["id"] for x in m["designs"]]
    pv = _preview_states(c, [i for i in ids if i != BASELINE])
    out = []
    for x in m["designs"]:
        p = os.path.join(design_dir(c, x["id"]), ev.RESULT_JSON)
        if os.path.isfile(p):
            out.append(U.read_json(p))
            continue
        st = (pv.get(x["id"]) or {}).get("state") or "CANCELED"
        if st == "READY":
            st = "CANCELED"
        out.append(ev.result_doc(x["id"], st, x["values"], code=(pv.get(x["id"]) or {}).get("code")))
    return out, pv


PER_ESL_COLS = ["worst_ratio", "min_improvement", "all_improved", "n_improved", "n_worsened", "geo_mean_improvement",
                "pareto"]


def _ranking_csv(rank: dict, results: list[dict], names: list[str], entry_ids: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "rank", "status"] + names + ["score", "improvement", "worst", "umax", "epsmax"]
               + [f"C_{e}" for e in entry_ids] + PER_ESL_COLS + [f"ratio_{e}" for e in entry_ids])
    rr = {x["id"]: x for x in rank["ranking"]}
    for r in sorted(results, key=lambda x: x["id"]):
        x = rr.get(r["id"])
        C = {p["entry_id"]: p["C"] for p in r.get("per_esl") or []}
        extra = [""] * (len(PER_ESL_COLS) + len(entry_ids))
        if r["id"] == BASELINE:
            row = [r["id"], "", r["status"]] + [r["values"].get(n, "") for n in names] + [1.0, 0.0,
                   rank["baseline"]["worst_entry_id"], rank["baseline"]["umax"], rank["baseline"]["epsmax"]]
            extra = [1.0, 0.0, False, 0, 0, 0.0, ""] + [1.0 if e in C else "" for e in entry_ids]
        elif x is not None:
            row = [r["id"], x["rank"], r["status"]] + [r["values"].get(n, "") for n in names] + [
                x["score"], x["improvement"], x["worst_entry_id"], x["umax"], x["epsmax"]]
            ratio = {p["entry_id"]: p["ratio"] for p in x.get("per_esl") or []}
            extra = [x.get(k, "") if x.get(k) is not None else "" for k in PER_ESL_COLS] + [ratio.get(e, "")
                                                                                       for e in entry_ids]
        else:
            row = [r["id"], "", r["status"]] + [r["values"].get(n, "") for n in names] + ["", "", "", "", ""]
        w.writerow(row + [C.get(e, "") for e in entry_ids] + extra)
    return buf.getvalue()


def _view3d(c: Ctx, t, bmeta, did: str, inp: dict, res: dict) -> str | None:
    """안(또는 베이스라인)의 최악 ESL 로 view3d 파일 → post/view3d/<did>/."""
    from esl.view3d import build_view
    dd = design_dir(c, did)
    if did == BASELINE and c.scn != "compare":
        mesh, sup = dict(t.mesh), list(t.supports)
        _, loads = sc.load_loads(c.p("prep"))
    else:
        dz = ev.load_design(dd)
        if c.scn in ("step", "compare"):
            mesh = {"node_id": dz["node_id"], "x0": dz["x"], "conn": dz["conn"], "elem_type": dz["type"],
                    "elem_pid": dz["pid"], "elem_id": np.arange(1, dz["conn"].shape[0] + 1, dtype=np.int64)}
            ne = mesh["conn"].shape[0]
            pr = bmeta["props"]
            mesh.update(thickness=np.full(ne, float(pr["t"])), E=np.full(ne, float(pr["E"])),
                        nu=np.full(ne, float(pr["nu"])))
            dt = sc.design_target(mesh, t.frame)
            mesh, sup = dt.mesh, list(dt.supports)
            loads, _ = sc.entry_loads(dt, c.entries(raw=False), c.mapping_opts())
        else:
            mesh = dict(t.mesh)
            mesh["x0"] = dz["x"]
            sup = list(t.supports)
            _, loads = sc.load_loads(c.p("prep"))
    worst_id = res.get("worst_entry_id")
    sel = [(e, f) for e, f in loads if e == worst_id] or loads[:1]
    r = ev.evaluate(mesh, sup, sel, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"], keep_u=[sel[0][0]])
    od = c.writer.fresh_dir(c.p("post", "view3d", did), c.out)
    build_view(od, node_id=mesh["node_id"], x0=mesh["x0"], conn=mesh["conn"], elem_type=mesh["elem_type"], f=sel[0][1],
               u_rel=r["u"][sel[0][0]], supports=[{"node_id": n, "dof": d} for n, d in sup], key=f"doe/{did}",
               esl_run_id=str(sel[0][0]))
    return did


def _copy_tree(src: str, dst: str, writer: U.Writer) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(src, followlinks=False):
        for name in sorted(files):
            s = os.path.join(root, name)
            if os.path.islink(s):
                continue
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            writer.makedirs(os.path.dirname(d))
            shutil.copyfile(s, writer.guard(d))
            out.append(rel.replace(os.sep, "/"))
    return out


def _best(c: Ctx, did: str, values: dict, warns: list) -> list[str]:
    """BD-D-18 산출물 → best/<did>/ (파일 목록, best/<did> 기준 상대경로)."""
    dd = design_dir(c, did)
    bd = c.writer.fresh_dir(c.p("best", did), c.out)
    files = []
    U.write_json(c.writer.guard(os.path.join(bd, "values.json")), mx.values_doc(values))
    files.append("values.json")
    if c.scn == "select":
        return files + _sel_best(c, did, bd)
    if c.scn in ("same", "mesh"):
        src = os.path.join(dd, "paicad", "out_files")
        if os.path.isdir(src):
            files += ["include/" + r for r in _copy_tree(src, os.path.join(bd, "include"), c.writer)]
        brep = os.path.join(dd, "paicad", "update", pio.SAMPLE_BREP)
    else:
        dz = ev.load_design(dd)
        _, bmeta = sc.load_base(c.p("prep"))
        ne = dz["conn"].shape[0]
        pr = bmeta["props"]
        mesh = {"node_id": dz["node_id"], "x0": dz["x"], "conn": dz["conn"], "elem_type": dz["type"],
                "elem_pid": dz["pid"], "elem_id": np.arange(1, ne + 1, dtype=np.int64),
                "thickness": np.full(ne, float(pr["t"])), "E": np.full(ne, float(pr["E"])),
                "nu": np.full(ne, float(pr["nu"]))}
        from esl.doe import export_mesh
        files += export_mesh.write(bd, mesh, guard=c.writer.guard)
        brep = os.path.join(dd, "update", pio.SAMPLE_BREP)
    if os.path.isfile(brep):
        shutil.copyfile(brep, c.writer.guard(os.path.join(bd, pio.SAMPLE_BREP)))
        files.append(pio.SAMPLE_BREP)
        ok, _ = mg.available()
        if ok:
            try:
                mg.export_step_isolated(os.path.join(bd, pio.SAMPLE_BREP), os.path.join(bd, "sample.step"), c.cfg)
                files.append("sample.step")
            except EslError as exc:
                warns.append(f"STEP_EXPORT_SKIPPED: {did} {exc.message}")
        else:
            warns.append(f"STEP_EXPORT_SKIPPED: {did} (gmsh 없음 — BREP 만)")
        for junk in ("mesh.log", "mesh_error.json"):
            p = os.path.join(bd, junk)
            if os.path.exists(p):
                os.remove(c.writer.guard(p))
    return files


def _cleanup(c: Ctx, keep: set[str]) -> int:
    """BD-D-17: 상위 k·베이스라인 외 안의 paicad morph/files·out_files 삭제(워커가 만든 중간 파일). 지운 바이트."""
    root = c.p("run", "designs")
    freed = 0
    if not os.path.isdir(root):
        return 0
    for did in sorted(os.listdir(root)):
        if did in keep:
            continue
        for sub in (("paicad", "morph", "files"), ("paicad", "out_files")):
            p = os.path.join(root, did, *sub)
            if os.path.isdir(p) and not os.path.islink(p):
                c.writer.guard(p)
                for r, _d, fs in os.walk(p):
                    freed += sum(os.path.getsize(os.path.join(r, f)) for f in fs)
                shutil.rmtree(p)
    return freed


def bd_post(spec: dict, echo=print) -> dict:
    """순위·민감도 → post/, view3d(베이스라인 + 상위 k), 산출물 best/, report.html, 파일 정리 → post/result.json."""
    c = Ctx(spec)
    if c.scn == "compare":
        return _cmp_post(c, echo)
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    inp = U.read_json(c.p("prep", "input.json"))
    m = _matrix(c)
    results, pv = _collect(c, m)
    noise = None
    npth = os.path.join(design_dir(c, NOISE), ev.RESULT_JSON)
    if c.scn == "step" and os.path.isfile(npth):
        nr = U.read_json(npth)
        b = next(r for r in results if r["id"] == BASELINE)
        if nr.get("status") == "OK" and b.get("status") == "OK":
            noise = abs(float(nr["C_max"]) / float(b["C_max"]) - 1.0)
    R = rk.rank(results, noise_floor=noise, tol=float(c.cfg["rank"]["ratio_tol"]))
    labels = {e["id"]: e.get("label") or e["id"][:8] for e in c.D["entries"]}
    for x in R["ranking"]:
        for p in x["per_esl"]:
            p["label"] = labels.get(p["entry_id"], p["entry_id"][:8])
    by = {x["id"]: x for x in R["ranking"]}
    for r in results:
        if r["id"] == BASELINE:
            r["score"] = 1.0
        elif r["id"] in by:
            r["score"] = by[r["id"]]["score"]
        p = os.path.join(design_dir(c, r["id"]), ev.RESULT_JSON)
        if os.path.isfile(p):
            U.write_json(c.writer.guard(p), r)
    sp = m["spec"]
    nom = mx.nominal_values(sp, params_table(c))
    samples = [{"values": {**nom, **(r["values"] if r["id"] != BASELINE else {})}, "score": r["score"]}
               for r in results if r.get("status") == "OK"]
    sens = rk.sensitivity(samples, sp["params"], method=sp["method"], levels=sp.get("levels"),
                          round_mm=c.cfg["doe"]["round_mm"])
    c.progress(20)
    c.writer.makedirs(c.p("post"))
    names = [p["name"] for p in sp["params"]]
    with open(c.writer.guard(c.p("post", "ranking.csv")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_ranking_csv(R, results, names, [e["id"] for e in c.D["entries"]]))
    c.write_json(os.path.join("post", "designs.json"), {"designs": [{"id": r["id"], "status": r["status"],
                                                                    "code": r.get("code"), "score": r.get("score")}
                                                                   for r in results]})
    warns = [w["code"] for w in R["warnings"]]
    k = int(c.cfg["view3d"]["top_k"])
    top = [x["id"] for x in R["ranking"][:k]]
    v3 = []
    for did in [BASELINE] + top:
        res = next(r for r in results if r["id"] == did)
        try:
            v3.append(_view3d(c, t, bmeta, did, inp, res))
        except EslError as exc:
            warns.append(f"VIEW3D_FAILED: {did} {exc.code}")
    c.progress(60)
    keep_k = int(c.cfg["paicad"]["keep_files_top"])
    best_ids = [x["id"] for x in R["ranking"][:max(1, min(k, keep_k))]]
    best_files = {}
    for did in best_ids:
        best_files[did] = _best(c, did, by[did]["values"], warns)
    c.progress(85)
    bfile = c.p("prep", "boundary.json")
    boundary = U.read_json(bfile) if os.path.isfile(bfile) else None
    inline = len(R["ranking"]) * len(R["esl_order"]) <= int(c.cfg["rank"]["per_esl_inline_max"])
    c.write_json(os.path.join("post", "per_esl.json"),
                 {"esl": [{"entry_id": e, "label": labels.get(e, e[:8])} for e in R["esl_order"]],
                  "ratio_tol": R["ratio_tol"], "designs": {x["id"]: x["per_esl"] for x in R["ranking"]}})
    out = {"C_ref": R["C_ref"], "baseline": R["baseline"], "n_ok": R["n_ok"], "n_skipped": R["n_skipped"],
           "n_failed": R["n_failed"],
           # ESL별 개선 지표(§11.4): per_esl 은 안 수 × ESL 수 ≤ rank.per_esl_inline_max 일 때만 행에, 전부는 post/per_esl.json
           "ranking": [{kk: v for kk, v in x.items() if kk != "C" and (kk != "per_esl" or inline)} for x in R["ranking"]],
           "per_esl_inline": inline, "ratio_tol": R["ratio_tol"],
           "esl": [{"entry_id": e, "label": labels.get(e, e[:8])} for e in R["esl_order"]],
           "sensitivity": None if sens.get("null") else sens, "sensitivity_reason": sens.get("reason"),
           "boundary_warnings_n": 0 if boundary is None else int(boundary.get("n_warn") or 0),
           "view3d": v3, "best": None if not best_ids else {"id": best_ids[0], "files": best_files[best_ids[0]]},
           "best_all": [{"id": i, "files": best_files[i]} for i in best_ids], "noise_floor": noise,
           "matrix_sha256": m["matrix_sha256"], "warnings": warns}
    ms = load_method_sources()
    pjson = c.p("prep", "plan.json")
    cnt = {"ok": 0, "collision": 0, "fixed": 0, "geom": 0}
    if c.scn == "select":
        cnt["mesh"] = 0                          # v0.15.0 select: 품질 실패(FAILED_MESH) 셀
    for r in pv.values():
        key = {"READY": "ok", "SKIPPED_COLLISION": "collision", "SKIPPED_FIXED": "fixed", "SKIPPED_GEOM": "geom",
               "FAILED_MESH": "mesh" if c.scn == "select" else None}.get(r["state"])
        if key:
            cnt[key] += 1
    ctx = {"study": {"id": c.D.get("id"), "title": c.D.get("title"), "scenario": c.scn,
                     "created_at": c.D.get("created_at"), "entry_ids": [e["id"] for e in c.D["entries"]]},
           "inputs": {"step": None if inp.get("step") is None else {"file_name": os.path.basename(inp["step"]["rel"]),
                                                                    "sha256": inp["step"]["sha256"]},
                      "mesh": inp.get("mesh"), "part_title": inp.get("part_title"), "inch": c.D.get("inch"),
                      "props": bmeta.get("props"), "mesh_size_mm": bmeta.get("h"),
                      "entries": [{"entry_id": e["id"], "label": e.get("label"), "case": e.get("case")}
                                  for e in c.D["entries"]]},
           "versions": {"paicad": c.D.get("paicad_version"), "gmsh": bmeta.get("gmsh_version")},
           "params": params_table(c), "spec": sp, "matrix_sha256": m["matrix_sha256"], "n_designs": m["n_designs"],
           "dropped_duplicates": m.get("dropped_duplicates"), "preview": {"counts": cnt, "cells": list(pv.values())},
           "result": {**R, "sensitivity": sens}, "boundary": boundary,
           "plan": U.read_json(pjson) if os.path.isfile(pjson) else None,
           "best": None if not best_ids else {"id": best_ids[0], "values": by[best_ids[0]]["values"],
                                              "files": best_files[best_ids[0]]},
           "sources": ms, "ranking_rows": c.cfg["limits"]["ranking_report_rows"], "esl": out["esl"]}
    if c.scn == "select":
        ctx["selection"] = _sel_report(c, results)
    from esl.doe import report_doe
    report_doe.write(c.writer.guard(c.p("report.html")), ctx)
    freed = _cleanup(c, {BASELINE, NOISE} | set(x["id"] for x in R["ranking"][:keep_k]))
    out["cleanup_bytes"] = freed
    c.write_json(os.path.join("post", "result.json"), out)
    echo(f"[bd_post] 성공 {R['n_ok']} · 최적 {best_ids[0] if best_ids else '-'}"
         + (f" score {R['ranking'][0]['score']:.4f}" if R["ranking"] else "") + f" · 정리 {freed} B")
    c.progress(100)
    return {"files": ["post/result.json", "post/ranking.csv", "post/designs.json", "post/per_esl.json", "report.html"],
            "warnings": warns,
            "result": out}


# ---------------------------------------------------------------- ④ 형상 직접 비교 (v0.14.0, esl_step_compare.md §5)
# 폴더: input/shapes/<did>.step · prep/{shapes.json, shapes/<did>/mesh/, base.json, base_mesh.npz, loads.npz, compare.json}
# · run/designs/<did>/ · post/ · best/<did>/(형상 메시 ch_r.rad·ch_r.fem) · report.html. paicad 단계 없음(BD_GEOM SKIPPED).
REF_CASE_MSG = "기준이 낙하 메시(다른 메싱 방식)라 개선율에 메시 차이가 섞입니다"
LIMIT_MSG = ("형상마다 새 메시 — 작은 차이는 메시 차이일 수 있음(잡음 바닥 미측정)", "모든 STEP 이 같은 좌표계·같은 위치라는 전제"
             "(어긋난 형상은 정렬 검사로 제외)", "형상 단순화는 작은 구멍 메움만(면적 < compare.defeature.min_hole_area_mm2, "
             "enabled: false 면 없음) — 필렛 제거·비드 억제(min_bead_height_mm, 기록만) 없음, 그 외는 gmsh 설정만 같게")


def _cmp_shapes(c: Ctx) -> list[dict]:
    return list(U.read_json(c.p("prep", sc.SHAPES_JSON))["shapes"])


def _cmp_by(c: Ctx) -> dict:
    if not hasattr(c, "_cmp_by_cache"):
        try:
            c._cmp_by_cache = {s["id"]: s for s in _cmp_shapes(c)}
        except (OSError, ValueError, KeyError):
            c._cmp_by_cache = {}
    return c._cmp_by_cache


def _cmp_name(c: Ctx, did: str) -> str:
    return str((_cmp_by(c).get(did) or {}).get("name") or did)


def _cmp_props(c: Ctx) -> dict:
    p = c.D.get("props")
    if not p:
        raise EslError("INPUT_INVALID", "④ 쉘 물성(props)이 없음")
    return {"t": float(p["t"]), "E": float(p["E"]), "nu": float(p["nu"])}


def _cmp_mesh_dir(c: Ctx, did: str) -> str:
    return c.p("prep", "shapes", did, "mesh")


def _cmp_doc(c: Ctx) -> dict:
    return U.read_json(c.p("prep", sc.COMPARE_JSON))


def _cmp_input(c: Ctx, echo) -> dict:
    """BD_INPUT ④: 형상 STEP → input/shapes/<did>.step(sha256 재확인) + prep/shapes.json. 기준 미지정 = 첫 ESL Case 메시 → d000."""
    D = c.D
    shapes = list(D.get("shapes") or [])
    src = D.get("reference_source") or ("step" if any(s.get("reference") for s in shapes) else "case")
    rows, warns, info = [], [], []
    for k, s in enumerate(shapes):
        did = str(s["id"])
        if not did.startswith("d") or not did[1:].isdigit() or len(did) != 4:
            raise EslError("INPUT_INVALID", f"형상 id 형식: {did}")
        rel = os.path.join("input", "shapes", f"{did}.step")
        sha = _copy_verified(s["path"], c.p(rel), c.writer, s.get("sha256"))
        rows.append({"id": did, "name": str(s["name"]), "file_name": s.get("file_name"), "sha256": sha,
                     "reference": bool(s.get("reference")), "rel": rel.replace(os.sep, "/"), "source": "step",
                     "size_mb": round(os.path.getsize(c.p(rel)) / (1024 * 1024), 3)})
        c.progress(5 + 60 * (k + 1) / max(len(shapes), 1))
    case_info = None
    if src == "case":
        b = D.get("base") or {}
        ents = c.entries(raw=True)
        be = next((e for e in ents if e.meta.get("entry_id") == b.get("entry_id")), ents[0])
        mesh, case_info = sc.case_ref_mesh(b["rad_path"], b["part_title"], be, _cmp_props(c), coord_tol_rel=c.coord_tol(),
                                           parse_kw=c.parse_kw())
        d = _cmp_mesh_dir(c, BASELINE)
        c.writer.makedirs(d)
        mg.save_npz_det(c.writer.guard(os.path.join(d, mg.MESH_NPZ)), {k: mesh[k] for k in mg.MESH_KEYS})
        U.write_json(c.writer.guard(os.path.join(d, mg.MESH_JSON)),
                     {"schema": "esl/doe_mesh/1", "source": "case", "case_id": b.get("case_id"),
                      "entry_id": b.get("entry_id"), **case_info, "errors": [], "options": None, "h": None})
        rows.insert(0, {"id": BASELINE, "name": "Case 메시", "file_name": None, "sha256": None, "reference": True,
                        "rel": None, "source": "case", "case_id": b.get("case_id"), "entry_id": b.get("entry_id")})
        warns.append(f"COMPARE_REF_CASE_MESH: {REF_CASE_MSG}")
        echo(f"[bd_input] ④ 기준 = 첫 ESL Case 메시(파트 {case_info.get('part_title')}, 노드 {case_info['n_nodes']} · 요소 "
             f"{case_info['n_elems']}) — {REF_CASE_MSG}")
    seen: dict[str, str] = {}
    for r in rows:
        if r.get("sha256"):
            if r["sha256"] in seen:
                warns.append(f"SHAPE_DUPLICATE_FILE: {r['id']} 와 {seen[r['sha256']]} 가 같은 STEP 파일(sha256)")
            seen.setdefault(r["sha256"], r["id"])
    if not any(r["id"] == BASELINE for r in rows):
        raise EslError("INPUT_INVALID", "④ 기준 형상(d000)이 없음")
    c.write_json(os.path.join("prep", sc.SHAPES_JSON), {"schema": "esl/doe_shapes/1", "reference_source": src,
                                                        "shapes": rows})
    inp = {"schema": "esl/doe_input/1", "scenario": "compare", "step": None, "assem": None, "reference_source": src,
           "entries": [e["id"] for e in D["entries"]], "shapes": [{k: r.get(k) for k in ("id", "rel", "sha256")}
                                                                 for r in rows],
           "case_mesh": case_info, "warnings": warns, "info": info}
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_input] ④ 형상 {len(rows)}개(기준 {'STEP' if src == 'step' else 'Case 메시'}) 복사·sha256 확인")
    for w in warns:
        echo(f"  경고: {w}")
    c.progress(100)
    return {"files": ["prep/input.json", f"prep/{sc.SHAPES_JSON}"], "warnings": warns, "info": info,
            "n_shapes": len(rows), "reference_source": src}


def _cmp_mesh_one(c: Ctx, row: dict, h: float, ccfg: dict, props: dict) -> dict:
    """형상 1개 gmsh(spawn 격리, ④ 프로필). 반환 {id, status READY|FAILED_MESH, code, message, n_nodes, n_elems, …}."""
    did = row["id"]
    d = _cmp_mesh_dir(c, did)
    c.writer.makedirs(d)
    try:
        mesh, meta = mg.run_isolated(c.p(row["rel"]), d, h, ccfg, props, opt_cfg=c.ocfg)
    except EslError as exc:
        if exc.code == "GMSH_UNAVAILABLE":
            raise
        mj = os.path.join(d, mg.MESH_JSON)
        errs = U.read_json(mj).get("errors") if os.path.isfile(mj) else []
        code = "MESH_TOO_LARGE" if any(e.get("code") == "MESH_TOO_LARGE" for e in errs or []) else "MESH_FAILED"
        return {"id": did, "status": "FAILED_MESH", "code": code, "message": exc.message}
    dfi = meta.get("defeature") or {}
    qy = _cmp_quality(c, mesh)
    out = {"id": did, "status": "READY", "code": None, "message": None, "n_nodes": meta["n_nodes"],
           "n_elems": meta["n_elems"], "quad_ratio": meta["quad_frac"], "seconds": meta.get("wall_seconds"),
           "quality": qy, "defeature": dfi or None,
           "warnings": [w.get("message") for w in meta.get("warnings") or []] + list(dfi.get("warnings") or [])}
    fb = meta.get("mesh_fallback")
    if fb:                                               # v0.14.1 면 폴백(정상 형상은 키 없음 — 결과 바이트 불변)
        ids = [int(f["failed_id"]) for f in fb["faces"]]
        qy.update(fallback_faces=len(ids), fallback_face_ids=ids)
        out["mesh_fallback"] = fb
    return out


def _cmp_quality(c: Ctx, mesh: dict) -> dict:
    """이슈 #53 criteria 품질 요약(bead_doe.compare.quality) — 차단 안 함."""
    from esl.doe import mesh_quality as mq
    return mq.summarize(mesh, c.cfg["compare"]["quality"])


def _cmp_mesh0(c: Ctx, echo) -> dict:
    """BD_MESH0 ④: 모든 STEP 같은 gmsh 프로필(SC-D-5)·형상별 병렬(run.parallel, SC-D-9). 기준 실패 → 작업 실패
    (MESH_FAILED·MESH_TOO_LARGE), 기준 크기(SC-D-7a) 불일치 → SIZE_MISMATCH. 그 밖 형상 실패 → FAILED_MESH(진행)."""
    from concurrent.futures import ThreadPoolExecutor
    c.progress(0)
    shapes = _cmp_shapes(c)
    steps = [r for r in shapes if r.get("rel")]
    ver = None
    if steps:
        ok, ver = mg.available()
        if not ok:
            raise EslError("GMSH_UNAVAILABLE", "gmsh 가 없어 ④ 형상 메시를 만들 수 없음")
    props = _cmp_props(c)
    prof = sc.compare_profile(c.cfg)
    ccfg = sc.compare_cfg(c.cfg)
    h = mg.check_h(float(prof["size_mm"]), prof)
    par = max(1, min(int(c.cfg["run"]["parallel"]), len(steps) or 1))
    echo(f"[bd_mesh0] ④ gmsh {ver or '-'} 프로필 h {h:g} mm · 최소 {h * float(prof['min_size_factor']):g} mm · 곡률 "
         f"{int(prof['curvature_n'])} · 경계 확장 {prof.get('extend_from_boundary')} · OCC 정리 {prof.get('occ_fix_small')} — "
         f"형상 {len(steps)}개 동시 {par}")
    res: dict[str, dict] = {}
    done = [0]
    if steps:
        with ThreadPoolExecutor(max_workers=par, thread_name_prefix="esl-cmp-mesh") as pool:
            futs = {pool.submit(_cmp_mesh_one, c, r, h, ccfg, props): r["id"] for r in steps}   # 기준이 먼저(id 순)
            for f, did in futs.items():
                r = f.result()
                res[did] = r
                done[0] += 1
                nm = _cmp_name(c, did)
                if r["status"] == "READY":
                    qy = r["quality"]
                    df = r.get("defeature") or {}
                    echo(f"[{did} {nm}] mesh {h:g} mm {float(r.get('seconds') or 0):.0f} s {r['n_elems']} 요소 · quad "
                         f"{r['quad_ratio']:.3f} · 품질 Fail {qy['fail_elems']}({qy['fail_ratio'] * 100:.2f} %) Warn "
                         f"{qy['warn_elems']} · 구멍 메움 {df.get('filled', 0)}·둘레 조정 {df.get('hole_sized', 0)}"
                         + (f" · 폴백 면 {qy['fallback_faces']}개(id {', '.join(map(str, qy['fallback_face_ids']))})"
                            if qy.get("fallback_faces") else ""))
                    for f in (r.get("mesh_fallback") or {}).get("faces") or []:
                        cc = f.get("center") or [0, 0, 0]
                        echo(f"[{did} {nm}]   면 {f['failed_id']}({f['type']}, 중심 {cc[0]:g},{cc[1]:g},{cc[2]:g} mm) → "
                             f"{f['algorithm_name']}{'(제약 해제)' if f['relaxed'] else ''} · 처음 오류: {f['errors'][0]}")
                else:
                    echo(f"[{did} {nm}] {r['status']} {r['code']}: {r['message']}")
                if did == BASELINE and r["status"] != "READY":
                    for g in futs:
                        g.cancel()
                    raise EslError(r["code"], f"기준 형상 메시 실패: {r['message']}")
                c.progress(5 + 75 * done[0] / len(steps))
    ref = next(r for r in shapes if r["id"] == BASELINE)
    if ref["source"] == "case":
        mj = U.read_json(os.path.join(_cmp_mesh_dir(c, BASELINE), mg.MESH_JSON))
        res[BASELINE] = {"id": BASELINE, "status": "READY", "code": None, "message": None, "n_nodes": mj["n_nodes"],
                         "n_elems": mj["n_elems"], "quad_ratio": mj["quad_frac"], "seconds": None,
                         "quality": _cmp_quality(c, mg.load_mesh(_cmp_mesh_dir(c, BASELINE))), "defeature": None,
                         "warnings": []}
    ents = c.entries(raw=False)
    ref_mesh = mg.load_mesh(_cmp_mesh_dir(c, BASELINE))
    t, size_info = sc.template_base(ref_mesh, ents, c.ocfg["size"], inch=c.D.get("inch"),
                                    source={"reference": ref["source"], "name": ref["name"]})
    prof_rec = {k: prof.get(k) for k in ("size_mm", "curvature_n", "min_size_factor", "extend_from_boundary",
                                         "occ_fix_small", "feature_angle", "algorithm", "occ_sew_faces")}
    prof_rec["defeature"] = dict(c.cfg["compare"].get("defeature") or {})
    bm = sc.save_base(t, c.p("prep"), "compare", c.writer,
                      extra={"props": props, "h": h, "gmsh_version": ver, "reference_source": ref["source"],
                             "profile": prof_rec, "profile_sha256": ev.config_hash(prof_rec)})
    warns = list(size_info.get("warnings") or [])
    for r in shapes:
        x = res[r["id"]]
        qy = x.get("quality")
        if qy and qy["over_limit"]:
            warns.append(f"SHAPE_QUALITY_FAIL: {r['id']} {r['name']} 품질 Fail 요소 {qy['fail_elems']}개 "
                         f"({qy['fail_ratio'] * 100:.2f} % > {qy['max_fail_ratio'] * 100:g} %) — 차단 아님")
        if qy and qy.get("fallback_faces"):
            warns.append(f"MESH_FACE_FALLBACK: {r['id']} {r['name']} 면 {qy['fallback_faces']}개(gmsh 면 id "
                         f"{', '.join(map(str, qy['fallback_face_ids']))})를 다른 2D 알고리즘·제약 해제로 메시 — "
                         "그 면 주변 요소 모양이 다른 형상과 다를 수 있음(mesh.json mesh_fallback)")
    doc = {"schema": "esl/doe_compare/1", "reference_source": ref["source"], "profile": prof_rec, "h": h,
           "gmsh_version": ver, "frame_sha256": ev.config_hash(t.frame),
           "shapes": [{"id": r["id"], "name": r["name"], "file_name": r.get("file_name"), "reference": r["reference"],
                       "source": r["source"], **{k: v for k, v in res[r["id"]].items() if k != "id"}} for r in shapes]}
    doc["warnings"] = warns
    c.write_json(os.path.join("prep", sc.COMPARE_JSON), doc)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(size=size_info, props=props, mesh_size_mm=h, gmsh_version=ver)
    inp["warnings"] = list(inp.get("warnings") or []) + warns
    c.write_json(os.path.join("prep", "input.json"), inp)
    nf = sum(1 for r in doc["shapes"] if r["status"] != "READY")
    echo(f"[bd_mesh0] 기준 d000 노드 {bm['n_nodes']} · 요소 {bm['n_elems']}, 형상 메시 실패 {nf}개")
    c.progress(100)
    return {"files": [f"prep/{sc.COMPARE_JSON}", "prep/base_mesh.npz", "prep/base.json"], "warnings": warns,
            "h": h, "n_failed": nf}


def _cmp_loads(c: Ctx, echo) -> dict:
    """BD_LOADS ④: 기준 frame 고정(prep/base.json), d000 하중(셀 매핑) → loads.npz, 형상별 크기·정렬(SC-D-7b) →
    FAILED_SIZE(그 형상만), 셀당 노드 경고 → prep/compare.json."""
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    ents = c.entries(raw=True)
    loads, linfo = sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"],
                                  (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]))
    loads_sha = sc.save_loads(c.p("prep"), t.mesh["node_id"], loads, c.writer)
    warns = list(linfo["warnings"])
    doc = _cmp_doc(c)
    ccfg = c.cfg["compare"]
    grid = (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"])
    n = len(doc["shapes"])
    for k, r in enumerate(doc["shapes"]):
        if r["id"] == BASELINE or r["status"] != "READY":
            continue
        mesh = mg.load_mesh(_cmp_mesh_dir(c, r["id"]))
        chk = sc.shape_check(mesh, t.frame, ents, c.ocfg["size"], ccfg, inch=c.D.get("inch"))
        r.update(size=chk["size"], align=chk["align"])
        if not chk["ok"]:
            r.update(status="FAILED_SIZE", code=chk["code"], message=chk["message"])
            echo(f"[{r['id']} {r['name']}] FAILED_SIZE {chk['code']}: {chk['message']}")
            continue
        w = sc.mapping_resolution(mesh, t.frame, grid, c.ocfg["check"]["min_nodes_per_cell"])
        if w:
            r.setdefault("warnings", []).append(w)
            warns.append(f"{w} — {r['id']}")
        c.progress(10 + 80 * (k + 1) / n)
    doc["loads"] = {"sha256": loads_sha, **linfo}
    c.write_json(os.path.join("prep", sc.COMPARE_JSON), doc)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(loads={"sha256": loads_sha, **linfo}, n_beads=0, n_params=0)
    c.write_json(os.path.join("prep", "input.json"), inp)
    ready = [r["id"] for r in doc["shapes"] if r["status"] == "READY"]
    echo(f"[bd_loads] ④ 기준 frame 고정 · ESL {len(loads)}개 셀 매핑 · 실행 대상 형상 {len(ready)}/{n}")
    c.progress(100)
    return {"files": ["prep/loads.npz", f"prep/{sc.COMPARE_JSON}"], "warnings": warns, "info": [],
            "n_ready": len(ready), "n_shapes": n}


def _cmp_sha(c: Ctx, did: str) -> str:
    """④ input_sha256 = (STEP sha, 형상 메시 sha, 기준 frame sha, 물성·메시 프로필·설정 해시) — 같으면 재사용."""
    bmeta = U.read_json(c.p("prep", "base.json"))
    sh = _cmp_by(c).get(did) or {}
    mesh_sha = bmeta["mesh_sha256"] if did == BASELINE else U.sha256_file(os.path.join(_cmp_mesh_dir(c, did), mg.MESH_NPZ))
    cfg = ev.config_hash({"cfg": _cfg_hash(c), "props": bmeta.get("props"), "profile": bmeta.get("profile"),
                          "step": sh.get("sha256"), "source": sh.get("source")})
    return ev.input_sha256({}, mesh_sha, ev.config_hash(bmeta["frame"]), cfg, None)


def _cmp_design_mesh(c: Ctx, t, did: str) -> tuple[dict, list, list, dict]:
    """④ 형상(기준 d000 포함 같은 규칙): 메시 → compare_target(frame 고정·auto_supports) → 셀 매핑 하중."""
    mesh = dict(t.mesh) if did == BASELINE else mg.load_mesh(_cmp_mesh_dir(c, did))
    dt = sc.compare_target(mesh, t.frame)
    loads, _ = sc.entry_loads(dt, c.entries(raw=False), c.mapping_opts())
    et = np.asarray(dt.mesh["elem_type"]).astype(int)
    return dt.mesh, list(dt.supports), loads, {"n_nodes": dt.n_nodes, "n_elems": dt.n_elems,
                                               "quad_frac": float(np.sum(et == 4)) / max(et.size, 1)}


def _cmp_ranking_csv(rank: dict, results: list[dict], shapes: dict, entry_ids: list[str]) -> str:
    """④ ranking.csv: 변수 열 대신 name·file_name."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "rank", "status", "name", "file_name", "score", "improvement", "worst", "umax", "epsmax"]
               + [f"C_{e}" for e in entry_ids] + PER_ESL_COLS + [f"ratio_{e}" for e in entry_ids])
    rr = {x["id"]: x for x in rank["ranking"]}
    for r in sorted(results, key=lambda x: x["id"]):
        x = rr.get(r["id"])
        sh = shapes.get(r["id"]) or {}
        head = [r["id"], "", r["status"], sh.get("name") or "", sh.get("file_name") or ""]
        C = {p["entry_id"]: p["C"] for p in r.get("per_esl") or []}
        extra = [""] * (len(PER_ESL_COLS) + len(entry_ids))
        if r["id"] == BASELINE:
            row = head + [1.0, 0.0, rank["baseline"]["worst_entry_id"], rank["baseline"]["umax"], rank["baseline"]["epsmax"]]
            extra = [1.0, 0.0, False, 0, 0, 0.0, ""] + [1.0 if e in C else "" for e in entry_ids]
        elif x is not None:
            head[1] = x["rank"]
            row = head + [x["score"], x["improvement"], x["worst_entry_id"], x["umax"], x["epsmax"]]
            ratio = {p["entry_id"]: p["ratio"] for p in x.get("per_esl") or []}
            extra = [x.get(k, "") if x.get(k) is not None else "" for k in PER_ESL_COLS] + [ratio.get(e, "")
                                                                                       for e in entry_ids]
        else:
            row = head + ["", "", "", "", ""]
        w.writerow(row + [C.get(e, "") for e in entry_ids] + extra)
    return buf.getvalue()


def _cmp_export(c: Ctx, did: str, props: dict) -> list[str]:
    """SC-D-11 형상 메시 산출물 → best/<did>/{ch_r.rad, ch_r.fem}(전 OK 형상, keep_files_top 무관)."""
    dz = ev.load_design(design_dir(c, did))
    ne = dz["conn"].shape[0]
    mesh = {"node_id": dz["node_id"], "x0": dz["x"], "conn": dz["conn"], "elem_type": dz["type"], "elem_pid": dz["pid"],
            "elem_id": np.arange(1, ne + 1, dtype=np.int64), "thickness": np.full(ne, float(props["t"])),
            "E": np.full(ne, float(props["E"])), "nu": np.full(ne, float(props["nu"]))}
    bd = c.writer.fresh_dir(c.p("best", did), c.out)
    from esl.doe import export_mesh
    return export_mesh.write(bd, mesh, guard=c.writer.guard)


def _cmp_post(c: Ctx, echo) -> dict:
    """BD_POST ④: 순위·ESL별 지표(§11·§11.4 그대로), 민감도 생략(COMPARE_NO_PARAMS), 형상 이름, view3d(기준 + 상위 k),
    메시 산출물(전 OK 형상), report.html → post/result.json."""
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    doc = _cmp_doc(c)
    shapes = {r["id"]: r for r in doc["shapes"]}
    results = []
    for r in doc["shapes"]:
        p = os.path.join(design_dir(c, r["id"]), ev.RESULT_JSON)
        if r["status"] == "READY" and os.path.isfile(p):
            results.append(U.read_json(p))
        elif r["status"] == "READY":
            results.append(ev.result_doc(r["id"], "CANCELED", {}))
        else:
            results.append(ev.result_doc(r["id"], r["status"], {}, code=r.get("code"), message=r.get("message")))
    R = rk.rank(results, noise_floor=None, tol=float(c.cfg["rank"]["ratio_tol"]), extra_failed={"FAILED_SIZE": "size"})
    rk.attach_shapes(R, shapes)
    labels = {e["id"]: e.get("label") or e["id"][:8] for e in c.D["entries"]}
    for x in R["ranking"]:
        for p in x["per_esl"]:
            p["label"] = labels.get(p["entry_id"], p["entry_id"][:8])
    by = {x["id"]: x for x in R["ranking"]}
    for r in results:
        if r["id"] == BASELINE:
            r["score"] = 1.0
        elif r["id"] in by:
            r["score"] = by[r["id"]]["score"]
        p = os.path.join(design_dir(c, r["id"]), ev.RESULT_JSON)
        if os.path.isfile(p):
            U.write_json(c.writer.guard(p), r)
    c.progress(20)
    c.writer.makedirs(c.p("post"))
    eids = [e["id"] for e in c.D["entries"]]
    with open(c.writer.guard(c.p("post", "ranking.csv")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_cmp_ranking_csv(R, results, shapes, eids))

    def shp(did):
        s = shapes.get(did) or {}
        return {"name": s.get("name"), "file_name": s.get("file_name"), "reference": bool(s.get("reference"))}
    c.write_json(os.path.join("post", "designs.json"), {"designs": [{"id": r["id"], "status": r["status"],
                                                                    "code": r.get("code"), "score": r.get("score"),
                                                                    "shape": shp(r["id"])} for r in results]})
    warns = [w["code"] for w in R["warnings"]]
    inp = U.read_json(c.p("prep", "input.json"))
    if doc["reference_source"] == "case":
        warns.append(f"COMPARE_REF_CASE_MESH: {REF_CASE_MSG}")
    k = int(c.cfg["view3d"]["top_k"])
    top = [x["id"] for x in R["ranking"][:k]]
    v3 = []
    for did in [BASELINE] + top:
        res = next(r for r in results if r["id"] == did)
        try:
            v3.append(_view3d(c, t, bmeta, did, inp, res))
        except EslError as exc:
            warns.append(f"VIEW3D_FAILED: {did} {exc.code}")
    c.progress(60)
    props = bmeta["props"]
    best_files: dict[str, list[str]] = {}
    for r in results:
        if r.get("status") == "OK":
            best_files[r["id"]] = _cmp_export(c, r["id"], props)
    c.progress(85)
    inline = len(R["ranking"]) * len(R["esl_order"]) <= int(c.cfg["rank"]["per_esl_inline_max"])
    esl = [{"entry_id": e, "label": labels.get(e, e[:8])} for e in R["esl_order"]]
    c.write_json(os.path.join("post", "per_esl.json"),
                 {"esl": esl, "ratio_tol": R["ratio_tol"], "designs": {x["id"]: x["per_esl"] for x in R["ranking"]},
                  "names": {x["id"]: x["shape"]["name"] for x in R["ranking"]}})
    best_id = R["ranking"][0]["id"] if R["ranking"] else None
    out = {"scenario": "compare", "reference_source": doc["reference_source"], "C_ref": R["C_ref"],
           "baseline": R["baseline"], "n_ok": R["n_ok"], "n_skipped": R["n_skipped"], "n_failed": R["n_failed"],
           "ranking": [{kk: v for kk, v in x.items() if kk != "C" and (kk != "per_esl" or inline)} for x in R["ranking"]],
           "per_esl_inline": inline, "ratio_tol": R["ratio_tol"], "esl": esl, "sensitivity": None,
           "sensitivity_reason": "COMPARE_NO_PARAMS", "boundary_warnings_n": 0, "view3d": v3,
           "best": None if best_id is None else {"id": best_id, "files": best_files.get(best_id, [])},
           "best_all": [{"id": i, "files": f} for i, f in sorted(best_files.items())], "noise_floor": None,
           "matrix_sha256": None, "profile": doc.get("profile"), "warnings": warns}
    ms = load_method_sources()
    ctx = {"study": {"id": c.D.get("id"), "title": c.D.get("title"), "scenario": "compare",
                     "created_at": c.D.get("created_at"), "entry_ids": eids},
           "inputs": {"inch": c.D.get("inch"), "props": props, "mesh_size_mm": bmeta.get("h"),
                      "entries": [{"entry_id": e["id"], "label": e.get("label"), "case": e.get("case")}
                                  for e in c.D["entries"]]},
           "versions": {"paicad": None, "gmsh": bmeta.get("gmsh_version")}, "shapes": doc["shapes"],
           "profile": doc.get("profile"), "reference_source": doc["reference_source"],
           "result": {**R, "sensitivity": None}, "sources": ms, "ranking_rows": c.cfg["limits"]["ranking_report_rows"],
           "esl": esl, "limits_extra": list(LIMIT_MSG), "warnings": warns,
           "best": None if best_id is None else {"id": best_id, "files": best_files.get(best_id, [])}}
    from esl.doe import report_doe
    report_doe.write(c.writer.guard(c.p("report.html")), ctx)
    out["cleanup_bytes"] = 0
    c.write_json(os.path.join("post", "result.json"), out)
    echo(f"[bd_post] ④ 성공 {R['n_ok']} · 최적 {best_id or '-'}"
         + (f" ({_cmp_name(c, best_id)}) score {R['ranking'][0]['score']:.4f}" if best_id else ""))
    c.progress(100)
    return {"files": ["post/result.json", "post/ranking.csv", "post/designs.json", "post/per_esl.json", "report.html"],
            "warnings": warns, "result": out}


# ---------------------------------------------------------------- v0.15.0 비드 직접 선택 select (esl_bead_select.md §8)
# 폴더: prep/{base_mesh.npz, base.json, input.json(STEP 없음), fixed/(워커 fixed-scan, 없을 수 있음), loads.npz, params.json(빈 표),
# plan.json, select/{part.glb, select.bin, select_manifest.json}} · select/<sel_sha12>/{derived.json, derived.npz, basis.npz,
# basis.json, params.json} · doe/<rev>/{matrix.json, …, selection.json, grid/{grid_manifest.json, cells/<id>/thumb.png}} ·
# run/designs/<did>/ · best/<did>/{values.json, selection.json, include/<rel>(/NODE 좌표만 교체), ch_r.rad, ch_r.fem}.
# 코어는 paicad 를 쓰지 않는다(BS-D-15). 선택(SelectionIn)은 spec doe.selection = {rev, sha256, input} 로 받는다.
SEL_REV_JSON = "selection.json"
SEL_VIEW_SCHEMA = "esl/bead_select_view/1"


def _sel_dir(c: Ctx, sha: str) -> str:
    return c.p("select", str(sha)[:12])


def _sel_rev_doc(c: Ctx) -> dict:
    p = c.p("doe", str(int(c.D["rev"])), SEL_REV_JSON)
    if not os.path.isfile(p):
        raise EslError("PREVIEW_NOT_READY", "선택 기저(doe/<rev>/selection.json)가 없음 — 미리보기(행렬) 먼저")
    return U.read_json(p)


def _sel_norm(c: Ctx) -> tuple[dict, str]:
    from esl.doe import bead_select as bsel
    s = c.D.get("selection") or {}
    if not isinstance(s, dict) or not s.get("input"):
        raise EslError("SELECTION_MISSING", "비드 선택이 저장되지 않음")
    norm, sha = bsel.normalize(s["input"], c.cfg)
    if s.get("sha256") and s["sha256"] != sha:
        raise EslError("PREVIEW_STALE", f"선택 sha256 불일치(저장 {str(s['sha256'])[:12]}… ≠ 계산 {sha[:12]}…)")
    return norm, sha


def _sel_fixed_ids(c: Ctx) -> tuple[np.ndarray, str | None]:
    """paicad fixed-scan(prep/fixed — 워커 BD_GEOM, 있으면) 노드 ID. 없음/실패 → (빈, 경고 코드)."""
    d = c.p("prep", "fixed")
    if not os.path.isfile(os.path.join(d, pio.SCAN_JSON)):
        return np.zeros(0, np.int64), "FIXED_INFO_MISSING"
    try:
        fx = pio.read_fixed(d, c.max_mb)
    except EslError:
        return np.zeros(0, np.int64), "FIXED_INFO_MISSING"
    return np.asarray(fx["node_id"], dtype=np.int64), None


def _sel_input(c: Ctx, echo) -> dict:
    """BD_INPUT select: ① 과 같은 기준 Case 제자리 읽기·동일성(STEP 없음)."""
    D = c.D
    b = D["base"]
    inp = {"schema": "esl/doe_input/1", "scenario": "select", "step": None, "entries": [e["id"] for e in D["entries"]]}
    ents = c.entries(raw=True)
    c.progress(10)
    assem = sc.assem_dir_check(b.get("case_dir") or os.path.dirname(b["rad_path"]), c.cfg["same"]["max_assem_mb"])
    be = next((e for e in ents if e.meta["entry_id"] == b["entry_id"]), None)
    if be is None:
        raise EslError("INPUT_INVALID", "기준 ESL 이 선택 목록에 없음")
    echo(f"[bd_input] select 기준 Case 입력 rad 제자리 읽기 (파트 {b['part_title']}, 조립 {assem['n_files']}개 파일 "
         f"{assem['total_mb']:.1f} MB)")
    t, info = sc.same_base(b["rad_path"], b["part_title"], be, [e for e in ents if e is not be],
                           coord_tol_rel=c.coord_tol(), parse_kw=c.parse_kw())
    inp.update(assem="case", assem_info=assem, part_id=int(t.source["part_id"]), part_title=t.source["part_title"],
               base_entry_id=b["entry_id"])
    meta = sc.save_base(t, c.p("prep"), c.scn, c.writer)
    c.progress(90)
    inp.update(warnings=[], info=info)
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_input] 기준 메시 노드 {meta['n_nodes']} · 요소 {meta['n_elems']} · topo {str(meta['topo_sha256'])[:12]}…")
    c.progress(100)
    return {"files": ["prep/input.json", "prep/base_mesh.npz", "prep/base.json"], "warnings": [], "info": info,
            "part_id": inp["part_id"]}


def _sel_loads(c: Ctx, echo) -> dict:
    """BD_LOADS select: ① 하중(노드 직접)·지지 + 선택 보기 자료 prep/select/(part.glb·select.bin·manifest)."""
    from esl.doe import bead_select as bsel
    from esl import view3d as v3
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    ents = c.entries(raw=True)
    warns, info = [], []
    loads, linfo = sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"],
                                  (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]))
    warns += linfo["warnings"]
    loads_sha = sc.save_loads(c.p("prep"), t.mesh["node_id"], loads, c.writer)
    c.progress(50)
    params = {"beads": [], "params": [], "warnings": []}            # 변수 = 선택 저장 후(select/<sha>/params.json)
    c.write_json(os.path.join("prep", "params.json"), params)
    plan = bnd.plan(t.mesh, t.frame, c.ocfg["keepout"], int(c.ocfg["ui"]["max_preview_points"]))
    c.write_json(os.path.join("prep", "plan.json"), plan)
    fids, fw = _sel_fixed_ids(c)
    if fw:
        warns.append(fw)
    m = t.mesh
    nid = np.asarray(m["node_id"], dtype=np.int64)
    fixed = np.isin(nid, fids)
    sd = c.fresh(os.path.join("prep", "select"))
    X = np.asarray(m["x0"], dtype=np.float64)
    tris = v3.triangulate(np.asarray(m["conn"]), np.asarray(m["elem_type"]))
    lo, hi = X.min(axis=0), X.max(axis=0)
    center, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    q = v3.quantize_positions(X, center, half)
    extras = {"units": "mm", "up": "Z", "generator": f"esl bead_select view {v3.BUILDER_VERSION}"}
    gbytes = v3.write_glb(c.writer.guard(os.path.join(sd, "part.glb")), q, center, half, "_NODE_ID",
                          nid.astype(np.uint32), tris, extras)
    blob, lay = bsel.view_files(m, fixed)
    with open(c.writer.guard(os.path.join(sd, "select.bin")), "wb") as fh:
        fh.write(blob)
    ix = bsel.mesh_index(m)
    man = {"schema": SEL_VIEW_SCHEMA, "n_nodes": t.n_nodes, "n_elems": t.n_elems, "n_tris": lay["n_tris"],
           "mesh_sha256": bmeta["mesh_sha256"], "h_med": float(ix.h_med), "plate_normal": v3.plate_normal(X).tolist(),
           "fixed": {"scan_n": int(fixed.sum()), "source": "none" if fw else "scan"},
           "glb": {"name": "part.glb", "bytes": int(gbytes)}, "bin": {"name": "select.bin", "bytes": len(blob),
                                                                      "layout": lay["layout"]}}
    c.write_json(os.path.join("prep", "select", "select_manifest.json"), man)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(loads={"sha256": loads_sha, **linfo}, n_beads=0, n_params=0,
               fixed={"source": "none" if fw else "scan", "n": int(fixed.sum())})
    inp["warnings"] = list(inp.get("warnings") or []) + ([fw] if fw else [])
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_loads] select ESL {len(loads)}개 하중({linfo['method']}), 고정 노드 {int(fixed.sum())}"
         + (" — 체결 정보 없음(FIXED_INFO_MISSING)" if fw else ""))
    c.progress(100)
    return {"files": ["prep/loads.npz", "prep/params.json", "prep/plan.json", "prep/select/part.glb",
                      "prep/select/select.bin", "prep/select/select_manifest.json"],
            "warnings": warns, "info": info, "boundary": None, "n_beads": 0, "n_params": 0,
            "fixed": {"source": "none" if fw else "scan", "n": int(fixed.sum())}}


def _sel_prepare(c: Ctx, t, echo) -> dict:
    """BD_MATRIX select: 선택 정규화·sha 확인 → derive → 기저 → select/<sha12>/ (같은 sha 면 재사용)."""
    from esl.doe import bead_select as bsel
    norm, sha = _sel_norm(c)
    bmeta = U.read_json(c.p("prep", "base.json"))
    d = _sel_dir(c, sha)
    pb, pj, pp = os.path.join(d, "basis.npz"), os.path.join(d, "basis.json"), os.path.join(d, "params.json")
    if all(os.path.isfile(p) for p in (pb, pj, pp, os.path.join(d, "basis.bin"))):
        bj = U.read_json(pj)
        if bj.get("selection_sha256") == sha and bj.get("mesh_sha256") == bmeta["mesh_sha256"] and \
                bj.get("basis_sha256") == U.sha256_file(pb) and bj.get("cfg_sha256") == _sel_cfg_sha(c):
            echo(f"[bd_matrix] select 기저 재사용 {sha[:12]}…")
            return {"params": U.read_json(pp)["params"], "warnings": [],
                    "rev_doc": _sel_rev(c, sha, bj["basis_sha256"])}
    fids, _ = _sel_fixed_ids(c)
    ms = (c.D.get("selection") or {}).get("mesh_sha256")
    if ms and ms != bmeta["mesh_sha256"]:
        raise EslError("PREVIEW_STALE", "선택의 mesh_sha256 이 준비 기준 메시와 다름(SELECTION_DROPPED)")
    D = bsel.derive_obj(t.mesh, norm, c.cfg, fixed_node_ids=fids, mesh_sha256=bmeta["mesh_sha256"],
                        with_section=False)
    B = bsel.basis(t.mesh, D, c.cfg)
    tab = bsel.params_table(D, c.cfg)
    c.writer.makedirs(d)
    bsel.save_basis(pb, B, guard=c.writer.guard)
    bsha = U.sha256_file(pb)
    blob = bsel.basis_bin(B)                    # 브라우저 3D 보기(§7.3, GET …/select/basis)
    with open(c.writer.guard(os.path.join(d, "basis.bin")), "wb") as fh:
        fh.write(blob)
    _sel_save_derived(c, os.path.join(d, "derived.npz"), D)
    c.write_json(os.path.relpath(os.path.join(d, "derived.json"), c.out), D.summary(with_figures=False))
    c.write_json(os.path.relpath(pp, c.out), {"beads": [{"id": b.id, "name": b.name, "kind": "select",
                                                         "n_tiers": len(b.tiers), "W_nom": b.W_nom, "W_min": b.W_min,
                                                         "W_max": b.W_max, "blend_mm": b.blend_mm,
                                                         "warnings": b.warnings} for b in D.beads],
                                              "params": tab, "warnings": D.warnings})
    meta = bsel.basis_meta(B, bsha)
    import hashlib
    meta.update(sha256=hashlib.sha256(blob).hexdigest(), mesh_sha256=bmeta["mesh_sha256"], cfg_sha256=_sel_cfg_sha(c))
    c.write_json(os.path.relpath(pj, c.out), meta)
    warns = [f"{w['code']}: {b.id}" for b in D.beads for w in b.warnings]
    echo(f"[bd_matrix] select {sha[:12]}… 비드 {len(D.beads)} · 변수 {len(B.vars)} · 기저 sha {bsha[:12]}…")
    return {"params": tab, "warnings": warns, "rev_doc": _sel_rev(c, sha, bsha)}


def _sel_cfg_sha(c: Ctx) -> str:
    import hashlib
    import json
    s = json.dumps({"select": c.cfg["select"], "quality": c.cfg["compare"]["quality"]}, sort_keys=True,
                   separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sel_rev(c: Ctx, sha: str, bsha: str) -> dict:
    return {"schema": "esl/doe_selection_rev/1", "selection_sha256": sha, "basis_sha256": bsha,
            "selection_rev": (c.D.get("selection") or {}).get("rev"), "dir": f"select/{sha[:12]}"}


def _sel_save_derived(c: Ctx, path: str, D) -> None:
    from esl.doe.mesh_gmsh import save_npz_det
    arr = {"fixed": np.asarray(D.fixed_mask, dtype=np.uint8)}
    for b in D.beads:
        lp = [lp["nodes"] for lp in b.loops]
        arr[f"{b.id}_loops"] = np.concatenate(lp).astype(np.int64) if lp else np.zeros(0, np.int64)
        arr[f"{b.id}_ptr"] = np.concatenate([[0], np.cumsum([x.size for x in lp])]).astype(np.int64)
        arr[f"{b.id}_nodes"] = b.bead_nodes.astype(np.int64)
        arr[f"{b.id}_nhat"] = np.asarray(b.n_hat, dtype=np.float64)
    save_npz_det(c.writer.guard(path), arr)


def _sel_loaded(c: Ctx) -> dict:
    """(기저, 고정 마스크, 고리) — 안 반복에서 1회만 읽음."""
    if not hasattr(c, "_sel_cache"):
        from esl.doe import bead_select as bsel
        r = _sel_rev_doc(c)
        d = c.p(*r["dir"].split("/"))
        pb = os.path.join(d, "basis.npz")
        if U.sha256_file(pb) != r["basis_sha256"]:
            raise EslError("PREVIEW_STALE", "basis.npz sha256 이 미리보기 기록과 다름")
        z = U.load_npz(os.path.join(d, "derived.npz"))
        loops, nh = [], []
        for k in sorted(z):
            if k.endswith("_ptr"):
                bid = k[:-4]
                L, P = z[f"{bid}_loops"], z[k]
                loops += [L[P[i]:P[i + 1]] for i in range(P.size - 1)]
                nh.append(z[f"{bid}_nhat"])
        c._sel_cache = {"B": bsel.load_basis(pb), "fixed": z["fixed"].astype(bool), "loops": loops, "rev": r,
                        "n_hat": np.mean(nh, axis=0) if nh else np.array([0.0, 0.0, 1.0])}
    return c._sel_cache


def _sel_design(c: Ctx, t, did: str) -> tuple[np.ndarray, dict]:
    from esl.doe import bead_select as bsel
    L = _sel_loaded(c)
    x0 = np.asarray(t.mesh["x0"], dtype=np.float64)
    x = bsel.morph(x0, L["B"], _design_values(c, did))
    return x, bsel.design_state(t.mesh, x0, x, L["fixed"], c.cfg)


def _sel_msg(code: str | None) -> str | None:
    if not code:
        return None
    from esl.doe import message
    return message(code)


def bd_select_grid(spec: dict, echo=print) -> dict:
    """BS-D-11 미리보기(select): 안마다 기저 모핑 → 고정·뒤집힘·품질 → 3D 썸네일 → doe/<rev>/grid/(paicad grid 와 같은 형식).

    grid_manifest.json = {schema_version 1, kind 'select', cells[{id, status OK|FAIL, code, thumb, quality, fixed_max_mm, fixed_viol?}],
    nominal{thumb}, color{v_max, unit}, selection_sha256, basis_sha256}. 셀 FAIL 코드 = SELECT_*(→ paicad_io.cell_state)."""
    from esl import view3d as v3
    from esl.doe import bead_select as bsel
    from esl.doe import select_render as sr
    c = Ctx(spec)
    rev = int(c.D["rev"])
    c.progress(0)
    t, _ = sc.load_base(c.p("prep"))
    L = _sel_loaded(c)
    m = _matrix(c)
    x0 = np.asarray(t.mesh["x0"], dtype=np.float64)
    gd_rel = os.path.join("doe", str(rev), "grid")
    gd = c.fresh(gd_rel)
    tcfg = c.cfg["select"]["thumb"]
    designs = [x for x in m["designs"] if x["id"] != BASELINE]
    direction, has = bsel.node_direction(L["B"])
    states, vmax = {}, 0.0
    for k, x in enumerate(designs):
        xd = bsel.morph(x0, L["B"], x["values"])
        st = bsel.design_state(t.mesh, x0, xd, L["fixed"], c.cfg)
        states[x["id"]] = st
        if st["state"] == "READY":
            cv = sr.color_values(x0, xd, direction, has)
            vmax = max(vmax, float(np.abs(cv).max()) if cv.size else 0.0)
        c.progress(5 + 30 * (k + 1) / max(len(designs), 1))
    V = vmax if vmax > 0 else float(c.cfg["limits"]["min_disp_range_mm"])
    view = sr.view(x0, has, L["n_hat"], t.frame, tcfg)
    tris = v3.triangulate(np.asarray(t.mesh["conn"]), np.asarray(t.mesh["elem_type"]))
    os.makedirs(c.writer.guard(os.path.join(gd, "cells", "nominal")), exist_ok=True)
    with open(c.writer.guard(os.path.join(gd, "cells", "nominal", "thumb.png")), "wb") as fh:
        fh.write(sr.render(x0, tris, None, None, view, V, tcfg, loops=L["loops"]))
    cells = []
    for k, x in enumerate(designs):
        xd = bsel.morph(x0, L["B"], x["values"])
        cv = sr.color_values(x0, xd, direction, has)
        rel = f"cells/{x['id']}/thumb.png"
        c.writer.makedirs(os.path.join(gd, "cells", x["id"]))
        with open(c.writer.guard(os.path.join(gd, *rel.split("/"))), "wb") as fh:
            fh.write(sr.render(xd, tris, cv, has, view, V, tcfg, loops=L["loops"]))
        st = states[x["id"]]
        q = st["quality"]
        cell = {"id": x["id"], "status": "OK" if st["state"] == "READY" else "FAIL", "code": st["code"],
                "thumb": rel, "fixed_max_mm": st["fixed"]["max_mm"],
                "quality": {kk: q[kk] for kk in ("n_affected", "new_fail", "new_fail_ratio", "inverted",
                                                 "max_flip_deg", "fail_by")}}
        if st["state"] == "SKIPPED_FIXED":       # v0.15.1 침범 원인(변수·노드) — 고정 침범 칸만(그 밖 칸 바이트 그대로)
            cell["fixed_viol"] = bsel.fixed_violation_detail(x0, xd, L["fixed"], L["B"], x["values"],
                                                             float(bsel._cfg(c.cfg)["fixed_tol_mm"]))
        cells.append(cell)
        c.progress(35 + 60 * (k + 1) / max(len(designs), 1))
    man = {"schema_version": 1, "kind": "select", "cells": cells, "nominal": {"thumb": "cells/nominal/thumb.png"},
           "color": {"v_max": V, "unit": "mm"}, "selection_sha256": L["rev"]["selection_sha256"],
           "basis_sha256": L["rev"]["basis_sha256"]}
    c.write_json(os.path.join(gd_rel, pio.GRID_MANIFEST), U.jsonable(man))
    cnt = {"ok": sum(x["status"] == "OK" for x in cells),
           "fixed": sum(x["code"] == "SELECT_FIXED_VIOLATION" for x in cells),
           "mesh": sum(x["code"] in ("SELECT_QUALITY_FAIL", "SELECT_MORPH_INVERTED") for x in cells)}
    echo(f"[bd_select_grid] rev {rev} 안 {len(cells)} · OK {cnt['ok']} · 고정 침범 {cnt['fixed']} · 품질 실패 "
         f"{cnt['mesh']} · V {V:.3g} mm")
    c.progress(100)
    return {"files": [f"{gd_rel}/{pio.GRID_MANIFEST}".replace(os.sep, "/")], "counts": cnt,
            "selection_sha256": L["rev"]["selection_sha256"], "warnings": []}


def _sel_rad_files(c: Ctx, nid: np.ndarray) -> list[tuple[str, str]]:
    """BS-D-14·§8.3: 모델 파일 중 대상 파트 노드(/NODE)를 가진 rad/include [(사본 rel, 원본 경로)] (rel 정렬).

    파일 집합 = ``prep/assem_full.json`` 매니페스트(paicad 준비분, 있으면 — rel 은 매니페스트 배치 그대로, 원본은 매니페스트
    sha256 과 같아야 함) | 없으면 기준 rad 의 include 트리(``include_path_map`` 반영, ``assem_full.layout`` 배치: Case 폴더 안 =
    Case 기준 상대경로, 밖 = ``_ext/…``). Case 폴더의 관계없는 rad 는 보지 않고, Case 밖 include 도 원본을 읽는다(읽기만)."""
    if hasattr(c, "_sel_rad"):
        return c._sel_rad
    from esl.doe import assem_full as af
    from esl.rad.parser import scan_include_refs
    b = c.D.get("base") or {}
    rad = os.path.normpath(os.path.abspath(b["rad_path"]))
    root = b.get("case_dir") or os.path.dirname(rad)
    man = U.read_json(c.p("prep", af.DIR + ".json")) if os.path.isfile(c.p("prep", af.DIR + ".json")) else None
    cands: list[tuple[str, str, str | None]] = []
    if isinstance(man, dict) and isinstance(man.get("files"), list) and os.path.isdir(c.p("prep", af.DIR)):
        for r in man["files"]:
            cands.append((str(r["rel"]).replace(os.sep, "/"), str(r["src"]), r.get("sha256")))
        source = "assem_full"
    else:
        kw = c.parse_kw()
        files = [rad]
        for ref in scan_include_refs(rad, kw["include_path_map"], kw["max_include_depth"], max_line_bytes=c.max_line()):
            if not ref["found"]:
                raise EslError("RAD_PARSE_ERROR", f"인클루드 파일을 찾을 수 없음: {ref['spec']}")
            if all(os.path.normcase(U.real_path(ref["path"])) != os.path.normcase(U.real_path(f)) for f in files):
                files.append(ref["path"])
        lay = af.layout(files, root)
        cands = [(lay[f].replace(os.sep, "/"), f, None) for f in files]
        source = "include"
    want = set(int(v) for v in nid.tolist())
    out = []
    for rel, src, sha in cands:
        if os.path.islink(src) or os.path.splitext(src)[1].lower() not in sc.MESH_EXT or not os.path.isfile(src):
            continue
        if nd.read_nodes(src, want, c.max_line()):
            if sha and U.sha256_file(src) != sha:
                raise EslError("INPUT_CHANGED", f"모델 파일이 준비 뒤 바뀜(sha256 불일치): {os.path.basename(src)}")
            out.append((rel, src))
    out.sort()
    c._sel_rad = out
    c._sel_rad_source = source
    return out


def _sel_best(c: Ctx, did: str, bd: str) -> list[str]:
    """BS-D-14: rad/include 사본(/NODE 좌표만) + ch_r.rad·ch_r.fem + selection.json (best/<did> 상대경로)."""
    from esl.doe import export_mesh
    t, _ = sc.load_base(c.p("prep"))
    dz = ev.load_design(design_dir(c, did))
    nid = np.asarray(t.mesh["node_id"], dtype=np.int64)
    files = []
    for rel, src in _sel_rad_files(c, nid):
        dst = os.path.join(bd, "include", *rel.split("/"))
        c.writer.makedirs(os.path.dirname(dst))
        nd.write_morphed(src, dst, nid, dz["x"], t.mesh["x0"], max_line=c.max_line(), guard=c.writer.guard)
        files.append("include/" + rel)
    mesh = {k: t.mesh[k] for k in ("node_id", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu")}
    mesh["x0"] = dz["x"]
    files += export_mesh.write(bd, mesh, part_title=str(c.D.get("base", {}).get("part_title") or "ch_r"),
                               header=["esl bead DOE (scenario select)"], guard=c.writer.guard)
    s = c.D.get("selection") or {}
    r = _sel_rev_doc(c)
    U.write_json(c.writer.guard(os.path.join(bd, "selection.json")),
                 {"schema": "esl/doe_selection/1", "rev": s.get("rev"), "sha256": r["selection_sha256"],
                  "basis_sha256": r["basis_sha256"], "input": s.get("input")})
    files.append("selection.json")
    return files


def _sel_report(c: Ctx, results: list) -> dict:
    r = _sel_rev_doc(c)
    dj = c.p(*r["dir"].split("/"), "derived.json")
    der = U.read_json(dj) if os.path.isfile(dj) else {}
    q = []
    for x in results:
        mi = x.get("mesh") or {}
        qq = mi.get("quality") or {}
        if x["id"] != BASELINE and qq:
            q.append({"id": x["id"], "state": x["status"], "new_fail": qq.get("new_fail"),
                      "n_affected": qq.get("n_affected"), "fixed_max_mm": mi.get("fixed_max_mm")})
    return {"sha256": r["selection_sha256"], "beads": der.get("beads") or [], "fixed": der.get("fixed") or {},
            "quality": q}


__all__ = ["STAGES", "run_stage", "bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post",
           "bd_select_grid", "SKIPPED", "FAILED"]
