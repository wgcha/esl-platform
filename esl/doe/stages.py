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
from esl.library import _util as U

STAGES = ("bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post")
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
        os.replace(tmp, path)

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
          "bd_eval": bd_eval, "bd_post": bd_post}.get(spec.get("stage"))
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
    c.fresh("prep")
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
    return U.read_json(c.p("prep", "params.json"))["params"]


def bd_matrix(spec: dict, echo=print) -> dict:
    c = Ctx(spec)
    rev = int(c.D["rev"])
    c.progress(0)
    t, _ = sc.load_base(c.p("prep"))
    tab = params_table(c)
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
    opts = c.cfg["paicad"].get("options") or {}
    if opts:
        c.write_json(os.path.join("prep", "paicad_options.json"), opts)
    echo(f"[bd_matrix] rev {rev} {m['spec']['method']} 안 {m['n_designs']}(공칭 포함, 중복 제거 {m['dropped_duplicates']}) "
         f"sha {m['matrix_sha256'][:12]}…")
    c.progress(100)
    return {"files": [f"{d}/matrix.json", f"{d}/cells.json", f"{d}/thumb_options.json"],
            "matrix_sha256": m["matrix_sha256"], "n_designs": m["n_designs"],
            "warnings": [f"{w['code']}: {w['name']}" for w in m["warnings"]]}


# ---------------------------------------------------------------- BD_EVAL (안 1개)
def _matrix(c: Ctx) -> dict:
    return U.read_json(c.p("doe", str(int(c.D["rev"])), "matrix.json"))


def _design_values(c: Ctx, did: str) -> dict:
    if did == NOISE:
        return {}
    for x in _matrix(c)["designs"]:
        if x["id"] == did:
            return dict(x["values"]) if did != BASELINE else {}
    raise EslError("INPUT_INVALID", f"행렬에 없는 안: {did}")


def _cfg_hash(c: Ctx) -> str:
    keep = {"solver": c.solver_cfg(), "mesh": c.cfg["mesh"], "solve": c.cfg["solve"], "grid": c.ocfg["grid"],
            "mapping": c.mapping_opts(), "paicad_options": c.cfg["paicad"].get("options") or {}}
    return ev.config_hash(keep)


def design_dir(c: Ctx, did: str) -> str:
    return c.p("run", "designs", did)


def _design_mesh(c: Ctx, t, did: str, inp: dict, bmeta: dict, *, fresh: bool) -> tuple[dict, list, list, dict]:
    """(안 mesh(x0 = 안 좌표), supports, loads, mesh 정보)."""
    dd = design_dir(c, did)
    if did == BASELINE:
        _, loads = sc.load_loads(c.p("prep"))
        return dict(t.mesh), list(t.supports), loads, {"n_nodes": t.n_nodes, "n_elems": t.n_elems}
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
    sha = ev.input_sha256(values, bmeta["mesh_sha256"], (inp.get("loads") or {}).get("sha256"), _cfg_hash(c),
                          c.D.get("paicad_version"))
    dd = design_dir(c, did)
    c.writer.makedirs(dd)
    prev = ev.reusable(dd, sha)
    if prev is not None:
        echo(f"[{did}] 이전 결과 재사용({prev['status']})")
        c.progress(100)
        return {"design": did, "status": prev["status"], "reused": True}
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
        mesh, sup, loads, mesh_info = _design_mesh(c, t, did, inp, bmeta, fresh=True)
        c.progress(40)
        r = ev.evaluate(mesh, sup, loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"])
        per, warns, solve = r["per_esl"], r["warnings"], r["stats"]
        ev.save_design(dd, mesh["node_id"], mesh["x0"], mesh if c.scn == "step" and did != BASELINE else None, c.writer)
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
    if status == "OK":
        echo(f"[{did}] solve {len(per)} ESL {solve['seconds']:.1f} s · C_max {doc['C_max']:.4g}")
    else:
        echo(f"[{did}] {status} {code}: {msg}")
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
    if did == BASELINE:
        mesh, sup = dict(t.mesh), list(t.supports)
        _, loads = sc.load_loads(c.p("prep"))
    else:
        dz = ev.load_design(dd)
        if c.scn == "step":
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
    for r in pv.values():
        key = {"READY": "ok", "SKIPPED_COLLISION": "collision", "SKIPPED_FIXED": "fixed", "SKIPPED_GEOM": "geom"}.get(
            r["state"])
        if key:
            cnt[key] += 1
    ctx = {"study": {"id": c.D.get("id"), "title": c.D.get("title"), "scenario": c.scn,
                     "created_at": c.D.get("created_at"), "entry_ids": [e["id"] for e in c.D["entries"]]},
           "inputs": {"step": {"file_name": os.path.basename(inp["step"]["rel"]), "sha256": inp["step"]["sha256"]},
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


__all__ = ["STAGES", "run_stage", "bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post",
           "SKIPPED", "FAILED"]
