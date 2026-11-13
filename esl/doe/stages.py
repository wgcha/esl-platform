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
import json
import os
import shutil
import time

import numpy as np

from esl.doe import FAILED, SKIPPED, load_method_sources, opt_settings, settings
from esl.doe import boundary as bnd
from esl.doe import evaluate as ev
from esl.doe import compare_lt as clt
from esl.doe import load_transfer as ltm
from esl.doe import matrix as mx
from esl.doe import mesh_gmsh as mg
from esl.doe import nodes as nd
from esl.doe import paicad_io as pio
from esl.doe import rank as rk
from esl.doe import scenario as sc
from esl.doe import stiffness_metric as smm
from esl.doe import transfer_plan as tp
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
            if sh.get("source") == "mesh" and sh.get("upload_root"):    # v0.16.0 메시 형상 = 업로드 폴더 전체(주 + include)
                ins.append(("메시 업로드", sh["upload_root"]))
            elif sh.get("path"):
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
def select_base(c: Ctx) -> str:
    """v0.16.2 AD-D-13: select 기준 메시 출처 ``case``(① Case 제자리, 기본) | ``mesh``(② B 메시 업로드) | v0.18.0 SG-D-1
    ``step``(③ STEP → ④ 사다리 메시). 스펙 ``doe.select_base``(백엔드가 ``inputs.select_base`` 를 그대로 넣음), 없으면 준비 결과
    ``prep/input.json`` 의 값, 그것도 없으면 case."""
    v = c.D.get("select_base")
    if v is None and os.path.isfile(c.p("prep", "input.json")):
        v = U.read_json(c.p("prep", "input.json")).get("select_base")
    return v if v in ("mesh", "step") else "case"


def _is_step_base(c: Ctx) -> bool:
    """v0.18.0 새 ③(select + select_base step — esl_step_graph.md). legacy ``scenario step`` 은 아님."""
    return c.scn == "select" and select_base(c) == "step"


def select_schema(c: Ctx) -> int:
    """v0.17.0 BG-D-35: select 선택 형식 1 | 2(그래프). 스펙 ``doe.select_schema``(백엔드가 ``inputs.select_schema`` 를
    그대로 넣음), 없으면 준비 결과 prep/input.json 의 값, 그것도 없으면 1(키 없음 = 1 — 기존 스터디 불변)."""
    v = c.D.get("select_schema")
    if v is None and os.path.isfile(c.p("prep", "input.json")):
        v = U.read_json(c.p("prep", "input.json")).get("select_schema")
    return 2 if v == 2 else 1


def _is_mesh_base(c: Ctx) -> bool:
    """② B 메시 기준(legacy ``mesh`` 시나리오 또는 select + select_base mesh — AD-D-18)."""
    return c.scn == "mesh" or (c.scn == "select" and select_base(c) == "mesh")


def bead_source(c: Ctx) -> str:
    """v0.16.2 AD-D-1: select 초기 선택 출처 ``auto`` | ``manual``(기본). 스펙 ``doe.bead_source``(백엔드가 ``inputs.bead_source``
    를 그대로 넣음), 없으면 ``prep/input.json`` 의 값."""
    v = c.D.get("bead_source")
    if v is None and os.path.isfile(c.p("prep", "input.json")):
        v = U.read_json(c.p("prep", "input.json")).get("bead_source")
    return "auto" if v == "auto" else "manual"


def _mesh_base(c: Ctx, ents, inp: dict, warns: list, scenario: str) -> dict:
    """② B 메시 기준(BD-D-12·AD-D-15 — legacy ``mesh`` 와 select + select_base mesh 공통): 업로드 rad/inc → input/mesh 사본·sha
    → ``load_mesh``(B 파트, 원 노드 ID 유지) → ``sc.template_base``(frame = B, 법선 정렬, 자동 3-2-1, 크기 규칙 B = 템플릿)
    → prep/base_mesh.npz·base.json(scenario = ``scenario``). inp(input.json)·warns 를 채우고 base 메타를 돌려준다."""
    D = c.D
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
    return sc.save_base(t, c.p("prep"), scenario, c.writer)


def select_prep_info(out_dir: str) -> dict:
    """(워커 BD_GEOM select 용, AD-D-17) 준비 폴더의 prep/input.json → {select_base, bead_source, assem("case" | "input/mesh"),
    part_id, part_title, step_rel | None}. BD_INPUT 뒤에만 의미."""
    inp = U.read_json(os.path.join(out_dir, "prep", "input.json"))
    st = inp.get("step") or None
    return {"select_base": inp.get("select_base") or "case", "bead_source": inp.get("bead_source") or "manual",
            "assem": inp.get("assem"), "part_id": inp.get("part_id"), "part_title": inp.get("part_title"),
            "step_rel": st.get("rel") if isinstance(st, dict) else None}


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
        meta = _mesh_base(c, ents, inp, warns, c.scn)
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
    if _is_step_base(c):                         # v0.18.0 SG-D-4 새 ③ = ④ 사다리 기준 메시
        from esl.doe import step_graph as sg
        return sg.mesh0(c, echo)
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
    if _lt(c) is not None:                       # v0.20.0 하중 전달 계획(①②③ 베이스라인 — 공용 실행기)
        loads, linfo = _lt_base_loads(c, t, bmeta, ents)
    else:
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
    if getattr(c, "_lt_inp_rec", None):          # v0.20.0 LT-19 계획 id·배치·fast_path
        inp["load_transfer"] = c._lt_inp_rec
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_loads] ESL {len(loads)}개 하중({linfo['method']}), 비드 {len(params['beads'])} · 변수 {len(params['params'])}"
         + (f", 경계 경고 {res['n_warn']} · 정보 {res['n_info']}" if res else ""))
    c.progress(100)
    return {"files": ["prep/loads.npz", "prep/params.json", "prep/plan.json"] + (["prep/boundary.json"] if res else []),
            "warnings": warns, "info": info, "boundary": None if res is None else {"n_warn": res["n_warn"],
                                                                                 "n_info": res["n_info"]},
            "n_beads": len(params["beads"]), "n_params": len(params["params"])}


def _boundary(c: Ctx, t, ents, info: list, region=None) -> dict:
    """②③ 경계 매핑 경고(§8.2). A = 선택 ESL 기준 항목(첫 항목), B = 기준 메시. v0.18.0 region(새 ③) = B 구멍 후보를
    평가 영역 부분 메시에서만(SG-D-20c) — None = 지금 동작."""
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
    if _is_mesh_base(c) and os.path.isfile(c.p("prep", "fixed", pio.SCAN_JSON)):   # AD-D-18 select_base mesh 도
        fx = pio.read_fixed(c.p("prep", "fixed"), c.max_mb)
        b_fx = pio.fixed_points(fx)
        if not b_fx:
            info.append("B_NO_FASTENERS")
    bmesh = t.mesh
    if region is not None:
        from esl.doe import step_graph as sg
        bmesh = sg.submesh({k: t.mesh[k] for k in ("node_id", "x0", "conn", "elem_type")}, region)
        bmesh.pop("_node_index")
    cands = bnd.b_candidates(t.frame, bmesh, b_fx, c.ocfg["keepout"]["hole_min_perimeter_mm"])
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
        bj = U.read_json(os.path.join(_sel_dir(c, sel_doc["rev_doc"]["selection_sha256"]), "basis.json"))
        if bj.get("graph_vars"):                 # v0.17.0 BG-D-24 사용자 범위 > 기본 범위 → BG_RAMP_SHORT(경고, 실행 계속)
            rs = _bgr().ramp_short(bj["graph_vars"], m["spec"]["params"], c.cfg)
            out["warnings"] += [_sel_warn_text(w) for w in rs]
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
    if c.scn != "compare" and _lt(c) is not None:   # v0.20.0 하중 전달 스냅샷만(legacy 해시 불변 — ①②③ select 포함)
        keep["load_transfer"] = ev.config_hash(tp.hash_view(_lt(c)))
    if c.scn != "compare" and _sm(c) is not None:   # v0.20.0 SM-6 강성 지표 스키마(스냅샷에 키 있을 때만, metric 은 해시 밖)
        keep["stiffness"] = SM_SCHEMA
    if c.scn == "select":                       # 판정 설정도 이어하기 키에(select 만 — ①②③④ 해시 불변)
        from esl.doe import bead_select as bsel  # v0.16.1 새 키는 기본값이면 빠짐(SR-D-13b — v0.16.0 해시 그대로)
        keep.update(select=bsel.select_hash_view(c.cfg["select"], step=_is_step_base(c)),
                    quality=c.cfg["compare"]["quality"])
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
        info = {"n_nodes": t.n_nodes, "n_elems": t.n_elems, **ninfo}
        from esl.morph import core as mcore           # SR-D-44 자동 탐지 기본 모핑(paicad 안 좌표)도 공통 모핑 코어 사후 점검
        sq = c.cfg["select"]["quality"]                # (극단 요소 — 해당 없으면 키 없음: 기존 결과 바이트 불변)
        mw = mcore.post_morph_warnings(t.mesh, t.mesh["x0"], x, sq, flip_deg=float(sq["flip_deg"]))
        if mw:
            info["morph_warnings"] = mw
        return m, list(t.supports), loads, info
    # SR-D-44·BG-D-45(③ STEP 모핑): 새 ③ = select_base step 으로 해소(v0.18.0 esl_step_graph.md — 위 select 분기, 기준 메시
    # 기저 모핑). 아래는 legacy scenario step(paicad update → 안 BREP 재메시) 그대로.
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
    if _lt(c) is not None:                       # v0.20.0 ③ 계획 per_target: A → 안 메시
        loads = _lt_target_loads(c, did, dt, None, _lt_h(c, bmeta, dt.mesh))
    else:
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
    st = xs = None
    if c.scn == "select" and did != BASELINE:    # v0.16.1 SR-D-13d: 재사용 전에 판정을 다시(규칙이 바뀌었을 수 있음)
        xs, st = _sel_design(c, t, did)
        if prev is not None and (st["state"] != "READY" or prev.get("status") not in ("OK", "FAILED_SOLVE")):
            prev = None                          # 지금 스킵 = 스킵 문서 새로, v0.16.0 SKIPPED_FIXED → 지금 READY(경고) = 해석
    if prev is not None:
        echo(f"[{did}] 이전 결과 재사용({prev['status']})")
        c.progress(100)
        return {"design": did, "status": prev["status"], "reused": True}
    if st is not None:
        if st["state"] != "READY":              # 뒤집힘·skip 정책 고정 침범·품질(미리보기와 같은 함수)
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
        rkw = {}
        if _is_step_base(c):                     # v0.18.0 SG-D-20e umax·epsmax = 평가 영역(영역 = 전체면 인자 없음)
            from esl.doe import step_graph as sg
            reg = sg.load_region(c.p("prep"))
            if reg is not None:
                rkw["region"] = reg
        reg_e = (getattr(c, "_lt_last", None) or {}).get("region") if _lt_plan(c)["mask"] == "compare_region" \
            else rkw.get("region")                # 평가 영역: 계획 열 mask(④ = LT-8 영역, 그 밖 = ③ 영역 또는 없음)
        if _lt(c) is not None:                   # v0.20.0 LT-10·20: 주 방식 + 진단 풀이(인수분해 1회, 모든 모드)
            r = _lt_eval(c, t, did, mesh, sup, loads, reg_e, dd, _lt_h(c, bmeta, mesh))
        elif _sm(c) is not None:
            r = _ev(c, mesh, sup, loads, rkw.get("region"), six=did == BASELINE)
        else:
            r = ev.evaluate(mesh, sup, loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"], **rkw)
        if _sm(c) is not None:                   # v0.20.0 SM-1·6: 강성 지표(재풀이 없음) — per_esl 키 추가
            sm_w = _sm_apply(c, t, did, mesh, loads, reg_e, _lt_h(c, bmeta, mesh), r)
            r["warnings"] = list(r["warnings"]) + sm_w
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
    mw = list((mesh_info or {}).get("morph_warnings") or [])
    if mw:                                       # v0.16.2 AD-D-8: 공통 코어 극단 요소(MORPH_EXTREME_ELEMENTS)도 result.json warnings
        warns = list(warns) + [_sel_warn_text(w) for w in mw]
    sw = list((st or {}).get("warnings") or [])
    if sw:                                       # v0.16.1 select 경고 안(SR-D-11): 문자열은 warnings, 원본 dict 는 select_warnings
        warns = list(warns) + [_sel_warn_text(w) for w in sw]
    doc = ev.result_doc(did, status, values, paicad=paicad, mesh=mesh_info, solve=solve, per_esl=per, warnings=warns,
                        code=code, message=msg)
    S_ = _sm(c)
    if S_ is not None and status == "OK":       # v0.20.0 §6 행 밖 sm{metric, lin_form, ref, disp, C_ref}
        p_ = _lt_plan(c)
        doc["sm"] = {"metric": S_["metric"], "lin_form": S_["lin_form"], "ref": p_["sm_ref"],
                     "disp": p_["sm_disp"][0 if did == BASELINE else 1], "C_ref": getattr(c, "_sm_cref", None)}
    if mw:
        doc["morph_warnings"] = mw
    if sw:
        doc["select_warnings"] = sw
        if any(w["code"] == "SELECT_FIXED_MOVED" for w in sw):  # 보고서 '체결 위치 어긋남' 원인 변수(상위 3)
            from esl.doe import bead_select as bsel
            L = _sel_loaded(c)
            det = bsel.fixed_violation_detail(np.asarray(t.mesh["x0"], dtype=np.float64), xs, L["fixed"], L["B"],
                                              values, float(bsel._cfg(c.cfg)["fixed_tol_mm"]), cap=0)
            doc["select_fixed_viol"] = {"n": det["n"], "max_mm": det["max_mm"], "bead_vars": det["bead_vars"][:3]}
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


SM_CSV_MID = ["score", "improvement", "worst", "metric", "score_solve", "imbalance_max", "rho_min", "rho_max", "umax_def",
              "epsmax"]


def _sm_csv(rank: dict, r: dict, x: dict | None, entry_ids: list[str], sm_key: str) -> list:
    """강성 지표 스냅샷 CSV 가운데 열(§6): SM_CSV_MID + C_<i>(metric 값) + C_solve_<i>(재풀이 C)."""
    pe = {p["entry_id"]: p for p in r.get("per_esl") or []}
    met = rank.get("metric") or "lin"
    if r["id"] == BASELINE:
        b = rank["baseline"]
        mid = [1.0, 0.0, b.get("worst_entry_id"), met, b.get("score_solve"), b.get("imbalance_max"), b.get("rho_min"),
               b.get("rho_max"), b.get("umax_def"), b.get("epsmax")]
    elif x is not None:
        mid = [x["score"], x["improvement"], x["worst_entry_id"], met, x.get("score_solve"), x.get("imbalance_max"),
               x.get("rho_min"), x.get("rho_max"), x.get("umax_def"), x["epsmax"]]
    else:
        mid = [""] * len(SM_CSV_MID)
    mid = ["" if v is None else v for v in mid]
    cm = [("" if (pe.get(e) or {}).get(sm_key) is None else pe[e][sm_key]) for e in entry_ids]
    cs = [(pe.get(e) or {}).get("C", "") for e in entry_ids]
    return mid + cm + cs


def _ranking_csv(rank: dict, results: list[dict], names: list[str], entry_ids: list[str],
                 lt_cols: dict | None = None, sm_key: str | None = None) -> str:
    """①②③ ranking.csv. v0.20.0 LT-13·20 lt_cols(새 스냅샷만) = 끝 열 lt_method·lt_far_frac·lt_dM_rel·score_alt.
    sm_key(강성 지표 스냅샷 — per_esl 의 metric 키) = 가운데 열 SM_CSV_MID·C_<i>(metric)·C_solve_<i>(§6)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    mid_h = (SM_CSV_MID + [f"C_{e}" for e in entry_ids] + [f"C_solve_{e}" for e in entry_ids]) if sm_key else \
        (["score", "improvement", "worst", "umax", "epsmax"] + [f"C_{e}" for e in entry_ids])
    w.writerow(["id", "rank", "status"] + names + mid_h + PER_ESL_COLS + [f"ratio_{e}" for e in entry_ids]
               + (LT_CSV_COLS if lt_cols is not None else []))
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
        if sm_key:
            row = row[:3 + len(names)] + _sm_csv(rank, r, x, entry_ids, sm_key)
        else:
            row = row + [C.get(e, "") for e in entry_ids]
        w.writerow(row + extra + ((lt_cols.get(r["id"]) or [""] * len(LT_CSV_COLS)) if lt_cols is not None else []))
    return buf.getvalue()


def _view3d(c: Ctx, t, bmeta, did: str, inp: dict, res: dict) -> str | None:
    """안(또는 베이스라인)의 최악 ESL 로 view3d 파일 → post/view3d/<did>/."""
    from esl.view3d import build_view
    dd = design_dir(c, did)
    if did == BASELINE and c.scn != "compare":
        mesh, sup = dict(t.mesh), list(t.supports)
        _, loads = sc.load_loads(c.p("prep"))
    else:
        dz = ev.load_design(dd) if not (c.scn == "compare" and _lt(c) is not None) else None
        if dz is None:                           # v0.20.0 LT-1: 실행과 같은 함수(하중·지지 바이트 같음)
            mesh, sup, loads, _ = _cmp_design_mesh(c, t, did)
        elif c.scn in ("step", "compare"):
            mesh = {"node_id": dz["node_id"], "x0": dz["x"], "conn": dz["conn"], "elem_type": dz["type"],
                    "elem_pid": dz["pid"], "elem_id": np.arange(1, dz["conn"].shape[0] + 1, dtype=np.int64)}
            ne = mesh["conn"].shape[0]
            pr = bmeta["props"]
            mesh.update(thickness=np.full(ne, float(pr["t"])), E=np.full(ne, float(pr["E"])),
                        nu=np.full(ne, float(pr["nu"])))
            dt = sc.design_target(mesh, t.frame)
            mesh, sup = dt.mesh, list(dt.supports)
            if _lt(c) is not None:               # v0.20.0 ③ 실행과 같은 공용 실행기
                loads = _lt_target_loads(c, did, dt, None, _lt_h(c, bmeta, dt.mesh))
            else:
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
               u_rel=_sm_view_u(c, did, mesh, r["u"][sel[0][0]]), supports=[{"node_id": n, "dof": d} for n, d in sup],
               key=f"doe/{did}", esl_run_id=str(sel[0][0]))
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
    S_ = _sm_post(c)
    R = rk.rank(results, noise_floor=noise, tol=float(c.cfg["rank"]["ratio_tol"]),
                **({"metric": S_["metric_effective"], "lin_form": S_["lin_form"],
                    "lin_valid": float(S_["lin_valid"])} if S_ else {}))
    labels = {e["id"]: e.get("label") or e["id"][:8] for e in c.D["entries"]}
    for x in R["ranking"]:
        for p in x["per_esl"]:
            p["label"] = labels.get(p["entry_id"], p["entry_id"][:8])
    by = {x["id"]: x for x in R["ranking"]}
    best_clean = None
    if c.scn == "select":                        # v0.16.1 SR-D-11: 경고 안도 순위 그대로 + 행 warn, 경고 없는 최상위
        rw = {r["id"]: [str(w["code"]).replace("SELECT_", "", 1) for w in r.get("select_warnings") or []]
              for r in results}
        for x in R["ranking"]:
            if rw.get(x["id"]):
                x["warn"] = rw[x["id"]]
        best_clean = next((x["id"] for x in R["ranking"] if not x.get("warn")), None)
    mwn = {r["id"]: [str(w["code"]) for w in r.get("morph_warnings") or []] for r in results}
    for x in R["ranking"]:                       # v0.16.2 AD-D-8: 극단 요소 경고 안 ⚠(시나리오 무관 — 없으면 키 없음, 바이트 불변)
        if mwn.get(x["id"]):
            x["warn"] = list(x.get("warn") or []) + [k for k in mwn[x["id"]] if k not in (x.get("warn") or [])]
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
    L = _lt(c)
    lt_res = lt_cols = lt_diag = None
    lt_w: list = []
    if L is not None:                            # v0.20.0 LT-13·20 진단 모음·요약·CSV 끝 열(모든 모드)
        try:
            lt_res, lt_cols, lt_diag, lt_w = _lt_post(c, R, results)
        except (EslError, OSError, ValueError, KeyError) as exc:
            lt_w = [_cmp_text("LT_DIAG_SKIPPED", stage="post", err=getattr(exc, "code", type(exc).__name__))]
            lt_res, lt_cols = {**tp.public(L), "summary": [], "warnings_n": 1}, {}
    with open(c.writer.guard(c.p("post", "ranking.csv")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_ranking_csv(R, results, names, [e["id"] for e in c.D["entries"]], lt_cols,
                              smm.metric_key(S_["metric_effective"], S_["lin_form"]) if S_ else None))
    c.write_json(os.path.join("post", "designs.json"), {"designs": [{"id": r["id"], "status": r["status"],
                                                                    "code": r.get("code"), "score": r.get("score")}
                                                                   for r in results]})
    warns = [w["code"] for w in R["warnings"]] + lt_w + _sm_post_warn(S_)
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
    if c.scn == "select":
        out["summary"] = {"best_clean": best_clean}
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
                      **({"select_base": inp["select_base"]} if inp.get("select_base") in ("mesh", "step") else {}),
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
        ctx["selection"]["best_clean"] = best_clean
    if S_ is not None:                           # v0.20.0 SM-7 보고서 강성 지표 절·한계 안내, §6 최상위 metric·lin_form
        ctx["stiffness"] = dict(S_)
        out.update(metric=R.get("metric"), lin_form=R.get("lin_form"), C_ref_solve=R.get("C_ref_solve"),
                   metric_effective=S_["metric_effective"], cross_mesh=S_["cross_mesh"],
                   **({"n_fallback": R["n_fallback"]} if "n_fallback" in R else {}))
    if L is not None:
        out["load_transfer"] = lt_res
        ctx["load_transfer"] = {"result": lt_res, "diag": lt_diag}
        if lt_diag is not None:
            c.write_json(os.path.join("post", LT_DIAG_JSON), U.jsonable(lt_diag))
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
LT_LIMIT_MSG = ("하중은 ESL 원본 절점력을 모든 형상(기준 포함)에 같은 규칙으로 옮긴 것입니다(일 등가 = 형상 면 최근접점 형상함수, 셀 = "
                "셀 합력·합모멘트 최소노름 분배) — 하중 전달 방식·진단 요약(기준 대비 umax·C 배율, MAC)은 '하중 전달' 절")
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
        if s.get("source") == "mesh":                   # v0.16.0 메시 입력(C2-D-2·3) — 주 + include 복사·sha 재확인
            rows.append(_cmp_input_mesh(c, did, s))
            c.progress(5 + 60 * (k + 1) / max(len(shapes), 1))
            continue
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
    seen: dict = {}
    for r in rows:
        if r.get("sha256"):
            key = r["sha256"] if r.get("source") != "mesh" else (r["sha256"], r.get("part_id"))   # 메시 = (주 sha, 파트)
            if key in seen:
                warns.append(f"SHAPE_DUPLICATE_FILE: {r['id']} 와 {seen[key]} 가 같은 "
                             f"{'메시' if r.get('source') == 'mesh' else 'STEP'} 파일(sha256)")
            seen.setdefault(key, r["id"])
    if not any(r["id"] == BASELINE for r in rows):
        raise EslError("INPUT_INVALID", "④ 기준 형상(d000)이 없음")
    c.write_json(os.path.join("prep", sc.SHAPES_JSON), {"schema": "esl/doe_shapes/1", "reference_source": src,
                                                        "shapes": rows})
    inp = {"schema": "esl/doe_input/1", "scenario": "compare", "step": None, "assem": None, "reference_source": src,
           "entries": [e["id"] for e in D["entries"]], "shapes": [{k: r.get(k) for k in ("id", "rel", "sha256")}
                                                                 for r in rows],
           "case_mesh": case_info, "warnings": warns, "info": info}
    c.write_json(os.path.join("prep", "input.json"), inp)
    nm = sum(1 for r in rows if r.get("source") == "mesh")
    echo(f"[bd_input] ④ 형상 {len(rows)}개(기준 {'STEP' if src == 'step' else 'Case 메시'}"
         + (f", 메시 입력 {nm}개" if nm else "") + ") 복사·sha256 확인")
    for w in warns:
        echo(f"  경고: {w}")
    c.progress(100)
    return {"files": ["prep/input.json", f"prep/{sc.SHAPES_JSON}"], "warnings": warns, "info": info,
            "n_shapes": len(rows), "reference_source": src}


def _cmp_input_mesh(c: Ctx, did: str, s: dict) -> dict:
    """v0.16.0 메시 입력 형상(C2-D-2·3): 주 + include → input/shapes/<did>/<업로드 상대경로>(copy_mesh_upload — 업로드 폴더 안
    include 만, 링크 거부, 복사본 sha256 재확인). 스냅샷 files[].sha256 이 있으면 원본 sha 와 대조. 원본에는 쓰지 않는다."""
    root = s.get("upload_root")
    if not root or not s.get("path"):
        raise EslError("INPUT_INVALID", f"메시 형상 {did} 의 업로드 경로(upload_root·path)가 없음")
    from esl.doe import mesh_input as mi
    mcfg = mi._mcfg(c.cfg)
    rel_dir = os.path.join("input", "shapes", did)
    dest = c.p(rel_dir)
    c.writer.makedirs(dest)
    try:
        files = sc.copy_mesh_upload(s["path"], root, dest, c.writer,
                                    max_depth=int(mcfg["max_include_depth"]) if mcfg.get("include", True) else 0)
    except EslError as exc:
        code = "MESH_INPUT_INVALID" if exc.code == "MESH_INVALID" else exc.code
        raise EslError(code, f"메시 형상 {did}: {exc.message}") from None
    want = {str(f.get("rel")): f.get("sha256") for f in s.get("files") or [] if f.get("rel")}
    for f in files:
        if want.get(f["rel"]) and want[f["rel"]] != f["sha256"]:
            raise EslError("MESH_INPUT_INVALID", f"메시 형상 {did}: 업로드 파일 sha256 이 등록값과 다름({f['rel']})")
    main_rel = os.path.relpath(U.real_path(s["path"]), U.real_path(root)).replace(os.sep, "/")
    return {"id": did, "name": str(s["name"]), "file_name": s.get("file_name"), "sha256": files[0]["sha256"],
            "reference": bool(s.get("reference")), "rel": rel_dir.replace(os.sep, "/"), "source": "mesh",
            "main_rel": main_rel, "part_id": None if s.get("part_id") is None else int(s["part_id"]),
            "files": [{"rel": f["rel"], "sha256": f["sha256"], "size": f["size"]} for f in files],
            "size_mb": round(sum(f["size"] for f in files) / (1024 * 1024), 3)}


def _cmp_text(code: str, **kw) -> str:
    """'CODE: 문구'(resources/doe_messages.json 틀 — 자리 표시자 누락은 그대로 둠)."""
    from esl.doe import load_messages
    try:
        tpl = str(load_messages()["messages"].get(code) or code)
    except Exception:                                       # noqa: BLE001 - 문구 누락으로 실패하지 않음
        tpl = code

    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return f"{code}: {tpl.format_map(_D(kw))}"


def _cmp_mesh_one(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, *, fail_info: bool = False,
                  timeout_s: float | None = None, large: bool = False, mesh_dir: str | None = None) -> dict:
    """형상 1개 gmsh(spawn 격리, ④ 프로필). 반환 {id, status READY|FAILED_MESH, code, message, n_nodes, n_elems, …}.
    fail_info(v0.16.0 auto 사다리) = 실패 시 mesh_error.json 에 실패 면·넓이(세분화 입력) — 성공 결과는 같음."""
    did = row["id"]
    d = mesh_dir or _cmp_mesh_dir(c, did)                  # v0.18.0 SG-D-5 mesh_dir(③ step = prep/mesh0, ④ = None)
    c.writer.makedirs(d)
    kw = {"large": True} if large else {}                  # v0.17.4 C2-D-33(대형 모델만)
    kw.update(_cmp_beat(c, row, "cad"))
    try:
        if fail_info:
            mesh, meta = mg.run_isolated(c.p(row["rel"]), d, h, ccfg, props, opt_cfg=c.ocfg, fail_info=True,
                                         timeout_s=timeout_s, **kw)
        else:
            mesh, meta = mg.run_isolated(c.p(row["rel"]), d, h, ccfg, props, opt_cfg=c.ocfg, timeout_s=timeout_s, **kw)
    except EslError as exc:
        if exc.code == "GMSH_UNAVAILABLE":
            raise
        return {"id": did, "status": "FAILED_MESH", "code": _cad_code(d), "message": exc.message}
    return _cmp_ready(c, did, mesh, meta)


def _cmp_say(c: Ctx, text: str) -> None:
    """v0.17.4 C2-D-39 단계 로그 진행 줄(_cmp_mesh0 이 echo 를 걸어 둔 때만)."""
    echo = getattr(c, "_cmp_echo", None)
    if echo is not None:
        try:
            echo(text)
        except Exception:                                   # noqa: BLE001
            pass


def _cmp_beat(c: Ctx, row: dict, stage: str) -> dict:
    """run_isolated 진행 줄 인자: 하위 프로세스 대기 중 heartbeat_s 마다 '[d001 이름] cad 진행 중 120 s — 마지막 폴백 줄'."""
    if getattr(c, "_cmp_echo", None) is None:
        return {}

    def beat(sec: float, step: str | None) -> None:
        _cmp_say(c, f"[{row['id']} {row.get('name')}] {stage} 진행 중 {sec:.0f} s" + (f" — {step}" if step else ""))
    return {"beat": beat}


def _cad_code(d: str) -> str:
    mj = os.path.join(d, mg.MESH_JSON)
    errs = U.read_json(mj).get("errors") if os.path.isfile(mj) else []
    return "MESH_TOO_LARGE" if any(e.get("code") == "MESH_TOO_LARGE" for e in errs or []) else "MESH_FAILED"


def _cmp_ready(c: Ctx, did: str, mesh: dict, meta: dict) -> dict:
    """성공 메시 → 형상 행(v0.14.0 형식 그대로 — 정상 STEP 은 키·값 불변)."""
    dfi = meta.get("defeature") or {}
    qy = _cmp_quality(c, mesh)
    out = {"id": did, "status": "READY", "code": None, "message": None, "n_nodes": meta["n_nodes"],
           "n_elems": meta["n_elems"], "quad_ratio": meta["quad_frac"], "seconds": meta.get("wall_seconds"),
           "quality": qy, "defeature": dfi or None,
           "warnings": [w.get("message") for w in meta.get("warnings") or []] + list(dfi.get("warnings") or [])}
    fb = meta.get("mesh_fallback")
    if fb:                                               # v0.14.1 면 폴백(정상 형상은 키 없음 — 결과 바이트 불변)
        ids = [int(f["failed_id"]) for f in fb["faces"]]
        qy.update(fallback_faces=len(ids), fallback_face_ids=ids,
                  fallback_stages=[mg.fallback_label(f) for f in fb["faces"]])   # v0.15.1 면마다 쓰인 단계(편차)
        out["mesh_fallback"] = fb
    rx = meta.get("cad_relaxed")
    if rx:                                               # v0.17.4 C2-D-32(정상 형상은 키 없음 — 결과 바이트 불변)
        out["cad_relaxed"] = {k: rx.get(k) for k in ("overrides", "face", "first_error", "fidelity", "seconds",
                                                     "cad_seconds") if rx.get(k) is not None}
        out["mesh_path"] = "cad_relaxed"
    return out


def _cmp_quality(c: Ctx, mesh: dict) -> dict:
    """이슈 #53 criteria 품질 요약(bead_doe.compare.quality) — 차단 안 함."""
    from esl.doe import mesh_quality as mq
    return mq.summarize(mesh, c.cfg["compare"]["quality"])


# ---------------------------------------------------------------- v0.16.0 메시 방식(esl_compare_mesh_options.md §4A·§7)
MESH_METHODS = ("cad", "refine", "remesh", "fallback", "mesh_input", "defeature")   # v0.16.1 defeature(SR-D-20)
# v0.16.1 compare.defeature 새 키(defeature 단계에서만 읽음) — base.json profile·profile_sha256 에서 값과 무관하게 뺌(SR-D-21b)
DEFEAT_NEW_KEYS_V0161 = ("kinds", "hole_max_d_mm", "slot_max_w_mm", "slot_max_l_mm", "flange_max_h_mm", "fillet_max_r_mm",
                         "narrow_w_factor", "feature_max_mm", "plane_tol_mm", "compound", "region_pad_factor",
                         "max_features", "list_max")
TRY_PREFIX = "try_"
REFINE_NEW_KEYS_V0163 = ("stage_share", "min_attempt_s")   # C2-D-29 — 이어하기 해시에서 뺌(시간 배분만 바꿈)


def _cmp_mode(c: Ctx) -> tuple[str, list[str]]:
    """(메시 모드, 사다리). 스냅샷 doe.mesh_mode 가 없으면(v0.15.x 스터디·코어 직접 호출) cad(C2-D-15). auto 사다리 = 스냅샷
    mesh_ladder(백엔드가 '세분화 허용' 반영) → 없으면 설정 compare.mesh.ladder."""
    from esl.doe import mesh_refine as mr
    mode = str(c.D.get("mesh_mode") or "cad")
    if mode != "auto":
        return mode, mr.ladder(c.cfg, mode)
    lad = c.D.get("mesh_ladder")
    if lad is None:
        return mode, mr.ladder(c.cfg, "auto")
    lad = [str(x) for x in lad]
    if any(x not in mr.STAGES for x in lad) or len(set(lad)) != len(lad) or (lad and lad[0] != "cad"):
        raise EslError("CONFIG_INVALID", f"mesh_ladder {lad} — 단계 ⊆ {list(mr.STAGES)}, cad 맨 앞, 중복 금지")
    return mode, lad or ["cad"]


def _remesh_ready(c: Ctx) -> bool:
    """재메시 가능 = compare.remesh.enabled ∧ gmsh importStl(C2-D-16). 경고는 백엔드가 이미 냄(다시 내지 않음)."""
    from esl.doe import mesh_remesh
    if not ((c.cfg.get("compare") or {}).get("remesh") or {}).get("enabled", True):
        return False
    return bool(mesh_remesh.available()[0])


def _clear_tries(c: Ctx, d: str) -> None:
    if not os.path.isdir(d):
        return
    for x in sorted(os.listdir(d)):
        p = os.path.join(d, x)
        if x.startswith(TRY_PREFIX) and os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(c.writer.guard(p))


def _keep_tries(ccfg: dict) -> bool:
    """compare.mesh.keep_tries(기본 false): true 면 모든 시도 폴더 try_<n>/ 를 남김, false 면 실패 시 마지막 시도만 남김."""
    from esl.doe import DEFAULTS
    v = (ccfg.get("mesh") or {}).get("keep_tries")
    return bool(DEFAULTS["compare"]["mesh"]["keep_tries"] if v is None else v)


def _promote(c: Ctx, td: str, d: str, extra: dict | None = None) -> None:
    """성공한 시도 폴더 → mesh/. extra(mesh_method·cad_error 등)를 시도 폴더 mesh.json 에 먼저 합친 뒤, mesh.json 이 아닌
    파일을 atomic_replace 로 옮기고 이전 실패 기록 mesh_error.json 을 지운 다음 mesh.json 을 맨 마지막에 옮깁니다 — 중간에
    멈추면 mesh/ 에 새 mesh.json 이 없으므로 성공으로 읽히지 않습니다. 빈 시도 폴더는 삭제."""
    if extra:
        _patch_mesh_json(c, td, extra)
    names = sorted(x for x in os.listdir(td) if os.path.isfile(os.path.join(td, x))
                   and not os.path.islink(os.path.join(td, x)))
    for x in [n for n in names if n != mg.MESH_JSON]:
        atomic_replace(c.writer.guard(os.path.join(td, x)), c.writer.guard(os.path.join(d, x)))
    ep = os.path.join(d, mg.MESH_ERROR)
    if os.path.isfile(ep) and mg.MESH_ERROR not in names:
        os.remove(c.writer.guard(ep))
    if mg.MESH_JSON in names:
        atomic_replace(c.writer.guard(os.path.join(td, mg.MESH_JSON)), c.writer.guard(os.path.join(d, mg.MESH_JSON)))
    shutil.rmtree(c.writer.guard(td), ignore_errors=True)


TRY_LOGS = "attempt_logs"                                    # v0.17.4 C2-D-40 지운 시도의 로그·실패 기록 보관(keep_tries 무관)
TRY_LOG_FILES = ("mesh.log", "mesh_error.json")


def _keep_try_logs(c: Ctx, d: str, src_dir: str, label: str) -> None:
    """시도 폴더(또는 cad 의 mesh/)의 mesh.log·mesh_error.json → mesh/attempt_logs/<label>.<파일>(지우기 전에)."""
    if not os.path.isdir(src_dir):
        return
    for x in TRY_LOG_FILES:
        p = os.path.join(src_dir, x)
        if os.path.isfile(p) and not os.path.islink(p):
            dst = os.path.join(d, TRY_LOGS)
            c.writer.makedirs(dst)
            shutil.copyfile(p, c.writer.guard(os.path.join(dst, f"{label}.{x}")))


def _next_try(c: Ctx, d: str, n_try: int, keep: bool) -> str:
    """새 시도 폴더 try_<n>/ (keep_tries false 면 앞 시도 폴더를 먼저 지움 — 마지막 시도 기록만 남음).
    v0.17.4: 지우기 전에 앞 시도의 로그·실패 기록을 attempt_logs/ 에 남김(실패 원인 추적)."""
    if not keep:
        for x in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if x.startswith(TRY_PREFIX) and os.path.isdir(os.path.join(d, x)):
                _keep_try_logs(c, d, os.path.join(d, x), x)
        _clear_tries(c, d)
    td = os.path.join(d, f"{TRY_PREFIX}{n_try}")
    c.writer.fresh_dir(td, c.out)
    return td


LADDER_STAGE_LABEL = {"refine_local": "세분화", "refine_global": "세분화", "defeature": "형상 단순화", "remesh": "재메시",
                      "freeform": "freeform 재메시", "tria": "삼각형 폴백"}   # v0.16.3 += freeform·tria


def _ladder_fail_text(r: dict) -> str:
    """auto 사다리가 모두 실패한 형상의 사용자 문구(Verifier Med 2): CAD 첫 오류 → 시도한 단계의 마지막 오류.
    cad_error 가 없으면 원 message 그대로."""
    ce = r.get("cad_error")
    if not ce:
        return str(r.get("message") or r.get("code") or "")
    cad = ce.get("message") or ce.get("code") or "?"
    tried: list[str] = []
    for a in r.get("attempts") or []:
        lb = LADDER_STAGE_LABEL.get(a.get("stage"))
        if lb and not a.get("skipped") and lb not in tried:
            tried.append(lb)
    if not tried:
        why = sorted({str(a.get("reason")) for a in r.get("attempts") or [] if a.get("skipped") and a.get("reason")})
        return _cmp_text("MESH_LADDER_SKIPPED", cad=cad, reasons=", ".join(why) or "-").split(": ", 1)[1]
    last = r.get("message") or r.get("code") or "?"
    out = _cmp_text("MESH_LADDER_FAILED", cad=cad, stages="·".join(tried), last=last).split(": ", 1)[1]
    if r.get("stage_times"):                                # v0.16.3 C2-D-30 단계 → 결과 → 초(작업 실패 문구 500자 상한 → 앞에)
        from esl.doe import mesh_refine as mr
        out = "[단계별: " + mr.stage_times_text(r["stage_times"]) + "] " + out
    return out


def _bbox_str(k) -> str:
    return ",".join(f"{float(v):g}" for v in (k or []))


def _md(mesh_dir: str | None) -> dict:
    """v0.18.0 SG-D-5: mesh_dir 는 ③ step 일 때만 넘김 — ④ 호출 인자 그대로(대역 함수 시험 포함)."""
    return {"mesh_dir": mesh_dir} if mesh_dir else {}


def _cmp_mesh_shape(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, mode: str, lad: list[str],
                    remesh_ok: bool, avail: int | None, mesh_dir: str | None = None) -> dict:
    """BD_MESH0 ④ 형상 1개 분기(§7): mesh → 메시 입력(in-process), cad → 기존 그대로, remesh → 재메시, auto → cad 를 기존
    경로로 먼저(성공이면 v0.15.x 와 바이트 동일) 실패하면 사다리(C2-D-18) — 시도 폴더 mesh/try_<n>/, 성공본을 mesh/ 로."""
    if row.get("source") == "mesh":
        return _cmp_mesh_input_one(c, row, ccfg, props)
    d = mesh_dir or _cmp_mesh_dir(c, row["id"])           # v0.18.0 SG-D-5(③ step = prep/mesh0)
    _clear_tries(c, d)
    if os.path.isdir(os.path.join(d, TRY_LOGS)):          # v0.17.4 이전 실행의 시도 로그
        shutil.rmtree(c.writer.guard(os.path.join(d, TRY_LOGS)))
    if mode == "remesh":
        c.writer.makedirs(d)
        r = _cmp_remesh_one(c, row, h, ccfg, props, d)
        r["mesh_method"] = "remesh"
        return r
    if mode == "freeform":                              # v0.16.3 C2-D-26: cad 없이 freeform → tria
        c.writer.makedirs(d)
        return _cmp_ladder(c, row, h, ccfg, props, lad, None, 0.0, remesh_ok, avail, **_md(mesh_dir))
    t0 = time.monotonic()
    auto = mode == "auto" and len(lad) > 1
    lg = mg.large_model(c.p(row["rel"]), ccfg["mesh"])   # v0.17.4 C2-D-33 대형 모델(STEP 본문 세기 — 결과와 무관)
    to = None
    if auto:                                            # 사다리 시간 예산(refine.total_timeout_s)은 cad 시도부터 셈
        from esl.doe import mesh_refine as mr           # v0.16.3 C2-D-29: cad 도 자기 몫까지만(뒤 단계 몫 예약)
        to = mr.attempt_timeout(min(float(ccfg["mesh"]["timeout_s"]), mr.stage_cap("cad", lad[1:], ccfg, 0.0)), ccfg, 0.0)
        if lg["large"]:                                 # 대형 모델: cad 몫 = large.cad_share × 예산(뒤 단계로 시간 넘김)
            sh = (ccfg["mesh"].get("large") or {}).get("cad_share")
            if sh is not None:
                to = min(to, float(sh) * float(mr._rcfg(ccfg)["total_timeout_s"]))
    r = _cmp_mesh_one(c, row, h, _relaxed_defer_cfg(ccfg), props,
                      fail_info=auto and bool({"refine_local", "defeature"} & set(lad)),
                      timeout_s=to, **({"large": True} if lg["large"] else {}), **_md(mesh_dir))
    r["mesh_method"] = "cad"
    if r.get("cad_relaxed"):                            # v0.17.4 C2-D-32 cad 자식 안 ③ 옵션 재시도 성공
        _cmp_relaxed_row(r, time.monotonic() - t0, lg)
    if r["status"] == "READY" or r["code"] == "MESH_TOO_LARGE":     # cad 의 사용자 상한 초과는 폴백 없음
        return r
    if not auto:                                        # v0.18.2 C2-D-45 mode cad: 부모 cad_relaxed(자기 세션·예산)만
        return _cmp_relaxed_only(c, row, h, ccfg, props, r, time.monotonic() - t0, lg, mesh_dir)
    out = _cmp_ladder(c, row, h, ccfg, props, lad, r, time.monotonic() - t0, remesh_ok, avail, lg=lg, **_md(mesh_dir))
    if lg["large"]:                                     # v0.17.4 C2-D-33 대형 판정(사다리 행에만 — 정상 형상 키 없음)
        out["large"] = {k: lg.get(k) for k in ("reason", "n_faces", "periodic")}
    return out


def _relaxed_defer_cfg(ccfg: dict) -> dict:
    """v0.18.2 C2-D-45 cad 첫 시도 설정: cad_relaxed.enabled ∧ isolate 면 사본의 cad_relaxed.defer = true(자식은 cad_relaxed 를 돌리지
    않고 첫 실패 면만 기록 → 부모가 자기 세션·cad_relaxed.timeout_s 로). 아니면 그대로(v0.18.1)."""
    rx = (ccfg.get("mesh") or {}).get("cad_relaxed")
    if not isinstance(rx, dict) or not rx.get("enabled") or not rx.get("isolate"):
        return ccfg
    out = dict(ccfg)
    out["mesh"] = dict(ccfg["mesh"], cad_relaxed=dict(rx, defer=True))
    return out


def _relaxed_state(pm: dict) -> str | None:
    """cad 자식의 cad_relaxed 기록 → deferred(부모 몫) | interrupted(자식 안에서 끝나기 전에 끊김) | done(자식이 끝까지) | None."""
    rx = pm.get("cad_relaxed") or {}
    if rx.get("deferred"):
        return "deferred"
    if not rx.get("tried"):
        return None
    if rx.get("interrupted") or (rx.get("seconds") is None and rx.get("error") is None):
        return "interrupted"
    return "done"


def _cmp_relaxed_only(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, r0: dict, t_cad: float, lg: dict,
                      mesh_dir: str | None) -> dict:
    """v0.18.2 C2-D-45 mode cad(사다리 없음): cad 자식이 cad_relaxed 를 부모 몫으로 남겼거나(deferred) 끝내지 못했으면(interrupted)
    부모가 1회. 성공 → READY 행(mesh_method cad), 실패 → cad 실패 행(attempts·stage_times 기록)."""
    from esl.doe import mesh_refine as mr
    d = mesh_dir or _cmp_mesh_dir(c, row["id"])
    pm = mr.read_attempt(d)
    st = _relaxed_state(pm)
    if st not in ("deferred", "interrupted") or not ((ccfg.get("mesh") or {}).get("cad_relaxed") or {}).get("enabled"):
        return r0
    _keep_try_logs(c, d, d, "cad")
    attempts = _relaxed_cad_attempts(pm, r0, h, t_cad)
    infos: list[str] = []
    cad_err = {"code": r0["code"], "message": r0["message"]}
    rr = _cmp_relaxed_parent(c, row, h, ccfg, props, ["cad"], (), t_cad, attempts, infos, _keep_tries(ccfg), 0, cad_err,
                             lg or {}, **_md(mesh_dir), first=pm.get("cad_relaxed") or {})
    rr.pop("_n_try", None)
    el = rr.pop("_elapsed", t_cad)
    if rr.get("status") == "READY":
        return rr
    out = dict(r0, attempts=attempts, stage_times=mr.stage_times(attempts), info=infos, seconds=round(el, 3))
    if lg.get("large"):
        out["large"] = {k: lg.get(k) for k in ("reason", "n_faces", "periodic")}
    return out


def _relaxed_cad_attempts(pm: dict, r0: dict, h: float, t_cad: float) -> list[dict]:
    """cad 시도 행(+ 자식 안 cad_relaxed 행). interrupted = 자식 감시 타이머가 cad_relaxed 후처리 중 끊음 → 시간 초과 실패(초 =
    자식 기록, 없으면 cad 초 − 첫 세션 초) — v0.18.1 의 '0.0 s 실패' 오기록 대신(C2-D-45)."""
    from esl.doe import mesh_refine as mr
    rx0 = pm.get("cad_relaxed") or {}
    st = _relaxed_state(pm)
    t_rx0 = 0.0
    if st == "done":
        t_rx0 = float(rx0.get("seconds") or 0.0)
    elif st == "interrupted":
        if rx0.get("seconds") is not None:
            t_rx0 = float(rx0["seconds"])
        elif rx0.get("cad_seconds") is not None:
            t_rx0 = max(0.0, float(t_cad) - float(rx0["cad_seconds"]))
    out = [{"stage": "cad", "factor": None, "h_mm": h, "status": "FAILED_MESH", "code": r0["code"],
            "seconds": round(max(0.0, t_cad - t_rx0), 3),
            **({"timed_out": True} if mr.timed_out(str(r0.get("message"))) and st != "interrupted" else {})}]
    if st == "done":
        out.append({"stage": "cad_relaxed", "factor": None, "h_mm": h, "status": "FAILED_MESH", "code": "MESH_FAILED",
                    "seconds": round(t_rx0, 3)})
    elif st == "interrupted":
        out.append({"stage": "cad_relaxed", "factor": None, "h_mm": h, "status": "FAILED_MESH", "code": "MESH_FAILED",
                    "seconds": round(t_rx0, 3), "timed_out": True, "interrupted": True})
    return out


def _cmp_relaxed_row(r: dict, total_s: float, lg: dict, attempts: list | None = None) -> None:
    """v0.17.4 cad_relaxed 성공 행: stage_times(cad 실패 → cad_relaxed 성공 초)·attempts·large(대형 판정) 기록."""
    from esl.doe import mesh_refine as mr
    rx = r["cad_relaxed"]
    if attempts is None:
        t_rx = float(rx.get("seconds") or 0.0)
        t_cad = float(rx.get("cad_seconds") if rx.get("cad_seconds") is not None else max(0.0, total_s - t_rx))
        attempts = [{"stage": "cad", "factor": None, "h_mm": None, "status": "FAILED_MESH", "code": "MESH_FAILED",
                     "seconds": round(t_cad, 3)},
                    {"stage": "cad_relaxed", "factor": None, "h_mm": None, "status": "READY", "code": None,
                     "seconds": round(t_rx, 3)}]
    r["attempts"] = attempts
    r["stage_times"] = mr.stage_times(attempts)
    if lg.get("large"):
        r["large"] = {k: lg.get(k) for k in ("reason", "n_faces", "periodic")}


def _cmp_ladder(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, lad: list[str], r0: dict, t_cad: float,
                remesh_ok: bool, avail: int | None, lg: dict | None = None, mesh_dir: str | None = None) -> dict:
    """C2-D-18~22 사다리 실행기(cad 실패 뒤). 단계마다 ``mesh_refine.plan`` → 시도 직전 ``check_limits`` 재판정 →
    ``run_isolated(kind cad, size_fields·max_elems)`` 또는 재메시. 첫 성공에서 멈춤."""
    from esl.doe import mesh_refine as mr
    did = row["id"]
    d = mesh_dir or _cmp_mesh_dir(c, did)
    src = c.p(row["rel"])
    rc = mr._rcfg(ccfg)
    infos: list[str] = []
    if r0 is None:                                      # v0.16.3 mode freeform: cad 시도 없음
        cad_err = None
        attempts: list[dict] = []
        pm: dict = {}
    else:
        cad_err = {"code": r0["code"], "message": r0["message"]}
        _keep_try_logs(c, d, d, "cad")                    # v0.17.4 C2-D-40 cad 로그(성공 시도가 mesh/ 로 덮기 전)
        pm = mr.read_attempt(d)
        attempts = _relaxed_cad_attempts(pm, r0, h, t_cad)  # v0.17.4 cad 자식 안 cad_relaxed — 초를 따로(v0.18.2 끊김 기록)
    pm["wall_seconds"] = round(t_cad, 3)
    ff = mr.face_failure(dict(pm, message=pm.get("message") or (r0 or {}).get("message")), ccfg) if r0 else None
    if ff is None and r0 is not None and mr.timed_out(str(r0.get("message"))):
        ff = _cmp_timeout_face(d, pm, ccfg)            # v0.17.4 C2-D-35 시간 초과 + 로그·부분 기록이 periodic 면
    ff_skip = mr.face_fail_skips(ccfg) if ff else ()
    if ff:                                              # v0.16.3 C2-D-27 결정 기록
        pm["face_fail"] = True
        f0 = ff["face"]
        infos.append(_cmp_text("MESH_FACE_FAIL", face=f0.get("id"), type=f0.get("type"), why=ff["match"],
                               skip="·".join(ff_skip) or "-") + f" — {did} {row['name']}")
    geom0 = pm.get("geom") or {}
    area = geom0.get("area_mm2")
    e_h2 = float(rc["elem_per_h2"])
    pm["n_est"] = mr.estimate_elems(area, h, elem_per_h2=e_h2) if area else None
    faces: list[dict] = []

    def acc(meta: dict) -> bool:
        """새 실패 면 누적(≤ local.max_faces, 각 면 local_area_mm2 = 그 시도 geom.local_area_mm2)."""
        f = meta.get("face")
        if not f or f.get("key") is None:
            return False
        k = tuple(round(float(v), 6) for v in f["key"])
        if any(tuple(round(float(v), 6) for v in x["key"]) == k for x in faces):
            return False
        if len(faces) >= int(rc["local"]["max_faces"]):
            return False
        faces.append({**f, "local_area_mm2": (meta.get("geom") or {}).get("local_area_mm2")})
        return True
    acc(pm)
    pm["faces"] = list(faces)
    elapsed = float(t_cad)
    last = dict(r0 or {"id": did, "status": "FAILED_MESH", "code": None, "message": None})
    n_try = 0
    keep = _keep_tries(ccfg)
    to_cad = float(ccfg["mesh"]["timeout_s"])
    rt = ((ccfg.get("compare") or {}).get("remesh") or {}).get("timeout_s")
    to_remesh = float(rt) if rt is not None else to_cad
    cmp_ = ccfg.get("compare") or {}
    ft = (cmp_.get("freeform") or {}).get("timeout_s")
    tt = mr._tcfg_timeout(ccfg)
    lgt = ((ccfg["mesh"].get("large") or {}).get("tria_timeout_s")) if (lg or {}).get("large") else None
    if lgt is not None:                                 # v0.18.2 C2-D-46 대형 모델 tria(남은 예산 안 — attempt_timeout)
        tt = max(float(tt), float(lgt))
    to_disc = {"remesh": to_remesh, "freeform": float(ft) if ft is not None else to_remesh, "tria": tt}
    last_disc: dict = {}

    def info_skip(a: dict) -> None:
        if a.get("reason") == "no_face":
            infos.append(f"{mr.NO_FACE_INFO}: {did} {row['name']} — "
                         + _cmp_text(mr.NO_FACE_INFO).split(": ", 1)[1])
            return
        infos.append(_cmp_text(mr.SKIP_INFO, stage=a["stage"],
                               factor="—" if a.get("factor") is None else f"{float(a['factor']):g}",
                               n_est="—" if a.get("n_est") is None else a.get("n_est"), bytes_est=_gb(a.get("bytes_est")),
                               reason=a.get("reason")) + f" — {did} {row['name']}")

    def skip(stage: str, reason: str, code=None) -> None:
        attempts.append({"stage": stage, "factor": None, "h_mm": h, "status": "SKIPPED", "code": code, "seconds": None,
                         "skipped": True, "reason": reason})

    rxc = (ccfg.get("mesh") or {}).get("cad_relaxed") or {}
    rst = _relaxed_state(pm) if r0 is not None else None
    # v0.17.4 cad 시간 초과 ∧ 면 실패 → 부모 1회 / v0.18.2 C2-D-45 deferred(isolate)·interrupted(자식이 후처리 중 끊김) → 부모 1회
    if r0 is not None and rxc.get("enabled") and (rst in ("deferred", "interrupted") or (ff and rst is None)):
        rr = _cmp_relaxed_parent(c, row, h, ccfg, props, lad, ff_skip, elapsed, attempts, infos, keep, n_try, cad_err,
                                 lg or {}, **_md(mesh_dir), first=pm.get("cad_relaxed") or {})
        n_try, elapsed = rr.pop("_n_try"), rr.pop("_elapsed")
        if rr.get("status") == "READY":
            return rr
    for si, stage in enumerate(lad):
        if stage == "cad":
            continue
        _cmp_say(c, f"[{did} {row['name']}] 사다리 {stage}" + (" 건너뜀(면 실패)" if stage in ff_skip else " 시작")
                 + f" · 누적 {elapsed:.0f} s")
        if stage in ff_skip:                            # v0.16.3 C2-D-27 면 실패 → 세분화로 안 풀림
            skip(stage, "face_fail")
            continue
        later = [x for x in lad[si + 1:] if x not in ff_skip]
        cap = mr.stage_cap(stage, later, ccfg, elapsed)  # v0.16.3 C2-D-29 단계 몫
        e_start = elapsed
        if stage == "defeature" and "freeform" in lad[:si] and last_disc.get("freeform") != "REMESH_FIDELITY":
            skip(stage, "not_fidelity")                 # v0.16.3 C2-D-26: freeform 이 충실도로 실패했을 때만
            continue
        if stage != "tria" and cap < mr.min_attempt_s(ccfg) and mr.remaining_s(ccfg, elapsed) > 0:
            info_skip({"stage": stage, "factor": None, "n_est": None, "bytes_est": None, "reason": "stage_time"})
            skip(stage, "stage_time", mr.SKIP_INFO)
            continue
        if stage in ("remesh", "freeform", "tria"):     # 이산 단계(gmsh OCC 면 메싱 안 씀)
            if stage == "tria" and not mr._tcfg_enabled(ccfg):
                skip(stage, "disabled")
                continue
            if stage == "freeform" and not ((ccfg.get("compare") or {}).get("freeform") or {}).get("enabled", True):
                skip(stage, "disabled")
                continue
            if stage != "tria" and not remesh_ok:
                skip(stage, "unavailable")
                continue
            if mr.remaining_s(ccfg, elapsed) <= 0:          # 같은 형상 누적 예산(refine.total_timeout_s) 소진
                info_skip({"stage": stage, "factor": None, "n_est": None, "bytes_est": None, "reason": "time"})
                skip(stage, "time", mr.SKIP_INFO)
                continue
            n_try += 1
            td = _next_try(c, d, n_try, keep)
            t1 = time.monotonic()
            tmo = min(mr.attempt_timeout(to_disc[stage], ccfg, elapsed), cap) if stage != "tria" else \
                mr.attempt_timeout(to_disc[stage], ccfg, elapsed)
            rr = _cmp_remesh_one(c, row, h, ccfg, props, td, timeout_s=tmo, kind=stage)
            dt = time.monotonic() - t1
            elapsed += dt
            last_disc[stage] = rr.get("code")
            attempts.append({"stage": stage, "factor": None, "h_mm": h, "status": rr["status"], "code": rr["code"],
                             "seconds": round(dt, 3), **({"n_elems": rr["n_elems"]} if rr.get("n_elems") else {}),
                             **({"timed_out": True} if mr.timed_out(str(rr.get("message"))) else {})})
            if rr["status"] == "READY":
                meth = "fallback" if cad_err else "remesh"
                lw = _ladder_warns(td)
                extra = {"mesh_method": meth, "cad_error": cad_err, "attempts": attempts,
                         "stage_times": mr.stage_times(attempts)}
                _promote(c, td, d, extra)
                if not keep:
                    _clear_tries(c, d)
                rr.update(mesh_method=meth, cad_error=cad_err, attempts=attempts, info=infos, fallback_stage=stage,
                          stage_times=mr.stage_times(attempts), warn_codes=lw)
                rr["seconds"] = round(elapsed, 3)
                return rr
            last = rr
            continue
        if stage == "defeature":                        # v0.16.1 §5A.1 형상 단순화(작은 형상 억제) 단계
            rr = _cmp_defeature_stage(c, row, h, ccfg, props, pm, avail, elapsed, attempts, infos, keep, n_try, cad_err,
                                      cap=cap, **_md(mesh_dir))
            n_try, elapsed = rr.pop("_n_try"), rr.pop("_elapsed")
            if rr.get("status") == "READY":
                return rr
            if rr.get("status") == "FAILED_MESH":
                last = rr
            continue
        queue = mr.plan(stage, pm, h, ccfg, avail, elapsed_s=elapsed)
        while queue:
            a = queue.pop(0)
            if a.get("skipped"):
                info_skip(a)
                attempts.append({"stage": stage, "factor": a.get("factor"), "h_mm": a.get("h_mm"), "status": "SKIPPED",
                                 "code": a.get("info"), "seconds": None, "skipped": True, "reason": a.get("reason")})
                continue
            why = mr.check_limits(a, ccfg, avail, elapsed, pm.get("wall_seconds"), pm.get("n_est"))
            if why:
                a.update(skipped=True, reason=why, info=mr.SKIP_INFO)
                info_skip(a)
                attempts.append({"stage": stage, "factor": a.get("factor"), "h_mm": a.get("h_mm"), "status": "SKIPPED",
                                 "code": mr.SKIP_INFO, "seconds": None, "skipped": True, "reason": why})
                continue
            left = cap - (elapsed - e_start)            # v0.16.3 C2-D-29 단계 몫 안에서만
            if left < mr.min_attempt_s(ccfg):
                attempts.append({"stage": stage, "factor": a.get("factor"), "h_mm": a.get("h_mm"), "status": "SKIPPED",
                                 "code": mr.SKIP_INFO, "seconds": None, "skipped": True, "reason": "stage_time"})
                continue
            n_try += 1
            td = _next_try(c, d, n_try, keep)
            t1 = time.monotonic()
            try:
                mesh, meta = mg.run_isolated(src, td, float(a["mesh_h"]), mr.attempt_cfg(ccfg, a), props, opt_cfg=c.ocfg,
                                             max_elems=a.get("max_elems"), fail_info=True,
                                             timeout_s=min(mr.attempt_timeout(to_cad, ccfg, elapsed), left),
                                             **_cmp_beat(c, row, stage))
            except EslError as exc:
                if exc.code == "GMSH_UNAVAILABLE":
                    raise
                dt = time.monotonic() - t1
                elapsed += dt
                code = _cad_code(td)
                attempts.append({"stage": stage, "factor": a.get("factor"), "h_mm": a.get("h_mm"), "status": "FAILED_MESH",
                                 "code": code, "seconds": round(dt, 3),
                                 **({"timed_out": True} if mr.timed_out(exc.message) else {})})
                last = {"id": did, "status": "FAILED_MESH", "code": code, "message": exc.message}
                nm = mr.read_attempt(td)
                nm["wall_seconds"] = round(dt, 3)
                nm.setdefault("geom", geom0)
                nm["n_est"] = a.get("n_est")
                grew = acc(nm)
                nm["faces"] = list(faces)
                pm = nm
                if stage == "refine_local" and grew:            # 새로 실패한 면 누적 → 남은(더 작은) 배율로 다시 계획
                    f0 = float(a.get("factor") or 1.0)
                    queue = [x for x in mr.plan(stage, pm, h, ccfg, avail, elapsed_s=elapsed)
                             if x.get("factor") is not None and float(x["factor"]) < f0]
                continue
            dt = time.monotonic() - t1
            attempts.append({"stage": stage, "factor": a.get("factor"), "h_mm": a.get("h_mm"), "status": "READY",
                             "code": None, "seconds": round(dt, 3), "n_elems": int(meta["n_elems"])})
            out = _cmp_ready(c, did, mesh, meta)
            sf = meta.get("size_fields") or {}
            fr = [{"bbox_key": _bbox_str(f.get("key")), "type": f.get("type"), "center": f.get("center"),
                   "ring": f.get("ring")} for e in sf.get("entries") or [] for f in e.get("faces") or []]
            n_h = mr.estimate_elems(area, h, elem_per_h2=e_h2) if area else None
            ref = {"kind": a.get("kind"), "stage_index": si, "h_mm": float(a["h_mm"]), "factor": a.get("factor"),
                   "base_h_mm": h, "faces": fr, "n_elems": int(meta["n_elems"]), "n_est": a.get("n_est"),
                   "elem_ratio_h": round(int(meta["n_elems"]) / n_h, 4) if n_h else None, "elem_ratio_ref": None,
                   "attempts": attempts}
            out.update(mesh_method="refine", cad_error=cad_err, refine=ref, attempts=attempts, info=infos,
                       stage_times=mr.stage_times(attempts))
            out["seconds"] = round(elapsed + dt, 3)
            _promote(c, td, d, {"mesh_method": "refine", "cad_error": cad_err, "refine": ref})
            if not keep:
                _clear_tries(c, d)
            return out
    last = {k: v for k, v in last.items() if k in ("id", "status", "code", "message", "fidelity")}
    last.update(status="FAILED_MESH", mesh_method=None, cad_error=cad_err, attempts=attempts, info=infos,
                stage_times=mr.stage_times(attempts))
    if cad_err is None:                                 # mode freeform 실패: 문구는 마지막 오류 + 단계별
        last["message"] = f"[단계별: {mr.stage_times_text(last['stage_times'])}] {last.get('message')}"
    return last


def _cmp_timeout_face(d: str, pm: dict, ccfg: dict) -> dict | None:
    """v0.17.4 C2-D-35 cad 시간 초과를 면 실패로 셈: 부분 기록(mesh_error.json face·log_face) 또는 mesh.log 마지막 면의 종류가
    face_fail.types ∪ fallback.periodic_types 이거나 로그에 face_fail.patterns 문구('periodic surface' 등) → {face, reason
    timeout, match}. face_fail 이 꺼져 있거나 근거가 없으면 None(예전처럼 세분화)."""
    m = ccfg.get("mesh") or {}
    ffc = m.get("face_fail") or {}
    if not ffc.get("enabled", True):
        return None
    f = pm.get("face") or pm.get("log_face") or mg.log_face(os.path.join(d, mg.MESH_LOG))
    if not f:
        return None
    types = [str(x) for x in (ffc.get("types") or [])] + [str(x) for x in ((m.get("fallback") or {}).get("periodic_types")
                                                                          or [])]
    if f.get("type") and str(f["type"]) in types:
        return {"face": f, "reason": "timeout", "match": str(f["type"])}
    txt = f"{f.get('error') or ''} {pm.get('message') or ''}".lower()
    for p in ffc.get("patterns") or []:
        if str(p).lower() in txt:
            return {"face": f, "reason": "timeout", "match": str(p)}
    return None


def _cmp_relaxed_parent(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, lad: list[str], ff_skip, elapsed: float,
                        attempts: list, infos: list, keep: bool, n_try: int, cad_err: dict, lg: dict,
                        mesh_dir: str | None = None, first: dict | None = None) -> dict:
    """v0.17.4 C2-D-32 cad 가 시간 초과(자식 안 cad_relaxed 못 감) ∧ 면 실패 → 부모가 cad_relaxed 1회(direct — 그 세션만, 면 폴백
    없음). v0.18.2 C2-D-45: isolate(기본)면 cad 자식은 cad_relaxed 를 돌리지 않고(deferred) 늘 이 경로 — 자기 하위 프로세스·자기 제한
    = min(cad_relaxed.timeout_s(null = mesh.timeout_s), 남은 예산, 남은 예산 − 뒤 단계(면 실패로 건너뛸 단계 제외) 몫).
    first = cad 자식의 첫 실패 면 기록(first_error·face — mesh.json cad_relaxed 에 그대로). 성공 → mesh_method cad 행."""
    from esl.doe import mesh_refine as mr
    did = row["id"]
    d = mesh_dir or _cmp_mesh_dir(c, did)
    later = [x for x in lad[1:] if x not in ff_skip]
    cap = mr.stage_cap("cad_relaxed", later, ccfg, elapsed)
    rxt = ccfg["mesh"]["cad_relaxed"].get("timeout_s")
    tmo = min(mr.attempt_timeout(float(rxt if rxt is not None else ccfg["mesh"]["timeout_s"]), ccfg, elapsed), cap)
    if tmo < mr.min_attempt_s(ccfg):
        attempts.append({"stage": "cad_relaxed", "factor": None, "h_mm": h, "status": "SKIPPED", "code": mr.SKIP_INFO,
                         "seconds": None, "skipped": True, "reason": "stage_time"})
        return {"status": "SKIPPED", "_n_try": n_try, "_elapsed": elapsed}
    rx = dict(ccfg["mesh"]["cad_relaxed"], direct=True)
    rx.pop("defer", None)
    fr = {k: (first or {}).get(k) for k in ("first_error", "face") if (first or {}).get(k) is not None}
    if fr:
        rx["first"] = fr
    cfg_r = dict(ccfg)
    cfg_r["mesh"] = dict(ccfg["mesh"], cad_relaxed=rx)
    _cmp_say(c, f"[{did} {row['name']}] cad_relaxed(③ 옵션 전체) 시작 · 누적 {elapsed:.0f} s")
    n_try += 1
    td = _next_try(c, d, n_try, keep)
    t1 = time.monotonic()
    kw = {"large": True} if lg.get("large") else {}
    try:
        mesh, meta = mg.run_isolated(c.p(row["rel"]), td, h, cfg_r, props, opt_cfg=c.ocfg, timeout_s=tmo, **kw,
                                     **_cmp_beat(c, row, "cad_relaxed"))
    except EslError as exc:
        if exc.code == "GMSH_UNAVAILABLE":
            raise
        dt = time.monotonic() - t1
        attempts.append({"stage": "cad_relaxed", "factor": None, "h_mm": h, "status": "FAILED_MESH", "code": _cad_code(td),
                         "seconds": round(dt, 3), **({"timed_out": True} if mr.timed_out(exc.message) else {})})
        infos.append(f"MESH_CAD_RELAXED_FAILED: {did} {row['name']} — {exc.message[:300]}")
        return {"status": "FAILED_MESH", "_n_try": n_try, "_elapsed": elapsed + dt}
    dt = time.monotonic() - t1
    attempts.append({"stage": "cad_relaxed", "factor": None, "h_mm": h, "status": "READY", "code": None,
                     "seconds": round(dt, 3), "n_elems": int(meta["n_elems"])})
    out = _cmp_ready(c, did, mesh, meta)
    out.update(mesh_method="cad", info=infos, cad_relaxed=dict(out.get("cad_relaxed") or {},
                                                                after_timeout=bool(mr.timed_out(cad_err.get("message"))),
                                                                isolated=True, cad_error=cad_err))
    _cmp_relaxed_row(out, elapsed + dt, lg, attempts=attempts)
    out["seconds"] = round(elapsed + dt, 3)
    _promote(c, td, d, {"cad_relaxed": dict(meta.get("cad_relaxed") or {}, **out["cad_relaxed"]),   # v0.18.2 자식 기록(ok·
             "stage_times": out["stage_times"]})                                                      # overrides …) 유지
    if not keep:
        _clear_tries(c, d)
    return dict(out, _n_try=n_try, _elapsed=elapsed + dt)


def _ladder_warns(td: str) -> list[dict]:
    """v0.16.3 이산 단계 성공 시도 mesh.json 의 MESH_FREEFORM·MESH_TRIA_FALLBACK·MESH_TRIA_HOLES 경고(형상 경고로 올림)."""
    p = os.path.join(td, mg.MESH_JSON)
    if not os.path.isfile(p):
        return []
    return [{"code": w["code"], "message": w.get("message")} for w in U.read_json(p).get("warnings") or []
            if isinstance(w, dict) and w.get("code") in ("MESH_FREEFORM", "MESH_TRIA_FALLBACK", "MESH_TRIA_HOLES")]


def _defeat_summary(meta: dict) -> dict | None:
    """형상 행 defeature 요약(§5A.5 — mesh.json.defeature_stage 에서): {n, counts, skipped_n, suppressed_max_mm, outside_hausdorff_mm}."""
    ds = meta.get("defeature_stage")
    if not ds:
        return None
    fd = ds.get("fidelity") or {}
    return {"n": ds.get("n"), "counts": ds.get("counts"), "skipped_n": ds.get("skipped_n"),
            "suppressed_max_mm": fd.get("suppressed_max_mm"),
            "outside_hausdorff_mm": (fd.get("outside") or {}).get("hausdorff_mm")}


def _cmp_defeature_stage(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, pm: dict, avail, elapsed: float,
                         attempts: list, infos: list, keep: bool, n_try: int, cad_err: dict, cap: float | None = None,
                         mesh_dir: str | None = None) -> dict:
    """사다리 defeature 단계 시도(최대 2 — compound 켬 → compound 면 실패 때만 끔). 반환 성공 형상 행 | {status FAILED_MESH…}
    | {status SKIPPED} (+ _n_try·_elapsed). 억제 대상 0 = DEFEATURE_NO_FEATURE(메싱 안 함, 2번째 시도도 건너뜀)."""
    from esl.doe import mesh_refine as mr
    did = row["id"]
    d = mesh_dir or _cmp_mesh_dir(c, did)
    src = c.p(row["rel"])
    to_cad = float(ccfg["mesh"]["timeout_s"])
    first = None
    out: dict = {"status": "SKIPPED"}
    e0 = elapsed
    for a in mr.plan("defeature", pm, h, ccfg, avail, elapsed_s=elapsed):
        rec = {"stage": "defeature", "factor": None, "h_mm": h, "compound": bool(a.get("compound"))}
        if a.get("only_if") == "compound_failed" and not mr.compound_failed(first):   # 조건 먼저(한도 판정보다 앞)
            attempts.append({**rec, "status": "SKIPPED", "code": None, "seconds": None, "skipped": True,
                             "reason": "not_compound"})
            continue
        if a.get("skipped"):
            infos.append(_cmp_text(mr.SKIP_INFO, stage="defeature", factor="—", n_est=a.get("n_est") or "—",
                                   bytes_est=_gb(a.get("bytes_est")), reason=a.get("reason")) + f" — {did} {row['name']}")
            attempts.append({**rec, "status": "SKIPPED", "code": mr.SKIP_INFO, "seconds": None, "skipped": True,
                             "reason": a.get("reason")})
            continue
        why = mr.check_limits(a, ccfg, avail, elapsed, pm.get("wall_seconds"), pm.get("n_est"))
        if why:
            attempts.append({**rec, "status": "SKIPPED", "code": mr.SKIP_INFO, "seconds": None, "skipped": True,
                             "reason": why})
            continue
        tmo = mr.attempt_timeout(to_cad, ccfg, elapsed)
        if cap is not None:                             # v0.16.3 C2-D-29 단계 몫
            tmo = min(tmo, cap - (elapsed - e0))
            if tmo < mr.min_attempt_s(ccfg):
                attempts.append({**rec, "status": "SKIPPED", "code": mr.SKIP_INFO, "seconds": None, "skipped": True,
                                 "reason": "stage_time"})
                continue
        n_try += 1
        td = _next_try(c, d, n_try, keep)
        t1 = time.monotonic()
        try:
            mesh, meta = mg.run_isolated(src, td, float(a["mesh_h"]), mr.attempt_cfg(ccfg, a), props, opt_cfg=c.ocfg,
                                         fail_info=True, timeout_s=tmo)
        except EslError as exc:
            if exc.code == "GMSH_UNAVAILABLE":
                raise
            dt = time.monotonic() - t1
            elapsed += dt
            if exc.code == "DEFEATURE_NO_FEATURE":
                attempts.append({**rec, "status": "SKIPPED", "code": "DEFEATURE_NO_FEATURE", "seconds": round(dt, 3),
                                 "skipped": True, "reason": "no_feature"})
                infos.append(_cmp_text("DEFEATURE_NO_FEATURE") + f" — {did} {row['name']}")
                break
            code = exc.code if exc.code == "DEFEATURE_FIDELITY" else _cad_code(td)
            attempts.append({**rec, "status": "FAILED_MESH", "code": code, "seconds": round(dt, 3),
                             **({"timed_out": True} if mr.timed_out(exc.message) else {})})
            first = mr.read_attempt(td) if first is None else first
            out = {"id": did, "status": "FAILED_MESH", "code": code, "message": exc.message}
            continue
        dt = time.monotonic() - t1
        elapsed += dt
        attempts.append({**rec, "status": "READY", "code": None, "seconds": round(dt, 3), "n_elems": int(meta["n_elems"])})
        res = _cmp_ready(c, did, mesh, meta)
        res.update(mesh_method="defeature", cad_error=cad_err, attempts=attempts, info=infos,
                   defeature=_defeat_summary(meta), stage_times=mr.stage_times(attempts))     # §5A.5 형상 행 defeature = 단계 요약(cad 단계 holes 기록 대신)
        res["seconds"] = round(elapsed, 3)
        _promote(c, td, d, {"mesh_method": "defeature", "cad_error": cad_err, "attempts": attempts})
        if not keep:
            _clear_tries(c, d)
        res.update(_n_try=n_try, _elapsed=elapsed)
        return res
    out.update(_n_try=n_try, _elapsed=elapsed)
    return out


def _defeat_lists(c: Ctx, shapes: list[dict]) -> dict:
    """보고서 '작은 형상 억제' 절: defeature 형상의 mesh/defeature.json(없으면 빈 목록)."""
    out = {}
    for x in shapes:
        if x.get("mesh_method") == "defeature":
            p = os.path.join(_cmp_mesh_dir(c, x["id"]), mg.DEFEAT_LIST)
            out[x["id"]] = U.read_json(p) if os.path.isfile(p) else {"n": 0, "features": []}
    return out


def _gb(b) -> str:
    return "—" if b is None else f"{float(b) / 1024 ** 3:.2f} GB"


def _patch_mesh_json(c: Ctx, d: str, extra: dict) -> None:
    p = os.path.join(d, mg.MESH_JSON)
    if os.path.isfile(p):
        U.write_json(c.writer.guard(p), {**U.read_json(p), **extra})


def _cmp_remesh_one(c: Ctx, row: dict, h: float, ccfg: dict, props: dict, out_dir: str,
                    timeout_s: float | None = None, kind: str = "remesh") -> dict:
    """삼각형 재메시 1회(C2-D-11, spawn 격리 run_isolated kind remesh) → 형상 행 + fidelity. 실패 = REMESH_* 코드.
    timeout_s None = remesh.timeout_s(null 이면 mesh.timeout_s), auto 사다리는 남은 예산으로 줄여 넘김."""
    did = row["id"]
    try:
        mesh, meta = mg.run_isolated(c.p(row["rel"]), out_dir, h, ccfg, props, opt_cfg=c.ocfg, kind=kind,
                                     timeout_s=timeout_s,
                                     **({"max_elems": int(mr_max_elems(ccfg))} if kind == "tria" else {}))
    except EslError as exc:
        if exc.code == "GMSH_UNAVAILABLE":
            raise
        keep_codes = ("MESH_TOO_LARGE", "CAD_INVALID", "TRIA_FAILED")
        code = exc.code if exc.code.startswith("REMESH_") or exc.code in keep_codes else \
            ("TRIA_FAILED" if kind == "tria" else "REMESH_FAILED")
        out = {"id": did, "status": "FAILED_MESH", "code": code, "message": exc.message}
        mj = os.path.join(out_dir, mg.MESH_JSON)
        if os.path.isfile(mj) and U.read_json(mj).get("fidelity"):
            out["fidelity"] = U.read_json(mj)["fidelity"]
        return out
    out = _cmp_ready(c, did, mesh, meta)
    if meta.get("fidelity"):
        out["fidelity"] = dict(meta["fidelity"])
    return out


def mr_max_elems(ccfg: dict) -> int:
    """v0.16.3 tria 시도 요소 상한 = refine.max_elems(삼각형이라 같은 h 에서 4각의 약 2배)."""
    from esl.doe import mesh_refine as mr
    return int(mr._rcfg(ccfg)["max_elems"])


def _cmp_mesh_input_one(c: Ctx, row: dict, ccfg: dict, props: dict) -> dict:
    """메시 입력 형상(C2-D-7): read_shape_mesh(in-process, gmsh 없음) → mesh/{mesh.npz, mesh.json, id_map.npz}."""
    from esl.doe import mesh_input as mi
    did = row["id"]
    d = _cmp_mesh_dir(c, did)
    c.writer.makedirs(d)
    for name in (mg.MESH_NPZ, mg.MESH_JSON, mi.ID_MAP_NPZ):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            os.remove(c.writer.guard(p))
    t0 = time.monotonic()
    try:
        mesh, meta = mi.read_shape_mesh(c.p(row["rel"]), row["main_rel"], row.get("part_id"), props, ccfg,
                                        opt_cfg=c.ocfg, out_dir=c.writer.guard(d))
    except EslError as exc:
        return {"id": did, "status": "FAILED_MESH", "code": exc.code, "message": exc.message, "mesh_method": "mesh_input"}
    out = _cmp_ready(c, did, mesh, meta)
    out.update(seconds=round(time.monotonic() - t0, 3), mesh_method="mesh_input", part_id=meta.get("part_id"),
               edge_median_mm=meta.get("edge_median_mm"), n_components=meta.get("n_components"),
               warn_codes=[w for w in meta.get("warnings") or [] if str(w.get("code", "")).startswith("MESH_INPUT_")],
               info=[f"{x['code']}: {did} {row['name']} {x.get('message') or ''}".rstrip() for x in meta.get("infos") or []])
    if meta.get("diag"):                     # v0.16.1 SR-D-24 메시 입력 진단(보고만)
        out["diag"] = meta["diag"]
    return out


def _method_echo(r: dict, h: float) -> str:
    """준비 로그 머리(cad 는 v0.15.x 문구 그대로)."""
    m = r.get("mesh_method")
    if m == "refine":
        rf = r.get("refine") or {}
        return (f"mesh 세분화({'국부' if rf.get('kind') == 'local' else '전역'} h {float(rf.get('h_mm') or h):g} mm"
                + (f" · 면 {len(rf.get('faces') or [])}" if rf.get("kind") == "local" else "") + ")")
    if m in ("remesh", "fallback"):
        fd = r.get("fidelity") or {}
        return (f"mesh 재메시{'(폴백)' if m == 'fallback' else ''} {h:g} mm"
                + (f" · 최대 편차 {float(fd['hausdorff_mm']):.3f} mm" if fd.get("hausdorff_mm") is not None else ""))
    if m == "mesh_input":
        return f"메시 입력(파트 {r.get('part_id')} · 요소 크기 중앙값 {float(r.get('edge_median_mm') or 0):.2f} mm)"
    if m == "defeature":
        ds = r.get("defeature") or {}
        return f"mesh 형상 단순화 {h:g} mm(작은 형상 {ds.get('n', 0)}개 억제)"
    return f"mesh {h:g} mm"


def _cmp_mesh_notes(c: Ctx, shapes: list[dict], res: dict, ref_mesh: dict, h: float, warns: list) -> list[str]:
    """v0.16.0 형상 행 보강·경고(C2-D-1·8·10·13·22·23): edge_median_mm·n_components, elem_ratio_ref, 기준 대비 크기 차이,
    COMPARE_MESH_METHOD_MIXED·REMESH_USED·REMESH_FIDELITY_WARN·MESH_REFINED·MESH_INPUT_*. 반환 info 문구."""
    from esl.doe import mesh_input as mi
    infos: list[str] = []
    ref_e50 = None
    n_ref = (res.get(BASELINE) or {}).get("n_elems")
    r_warn = float(mi._mcfg(c.cfg)["size_warn_ratio"])
    for r in shapes:
        x = res[r["id"]]
        infos += list(x.pop("info", None) or [])
        wc = x.pop("warn_codes", None) or []
        if r.get("source") == "case":
            x["mesh_method"] = "mesh_input"
        if r.get("source") == "mesh":
            x["part_id"] = x.get("part_id", r.get("part_id"))
        if x.get("status") != "READY":
            continue
        if x.get("edge_median_mm") is None or x.get("n_components") is None:
            m = ref_mesh if r["id"] == BASELINE else mg.load_mesh(_cmp_mesh_dir(c, r["id"]))
            x["edge_median_mm"] = round(mi.edge_median(m), 6)
            x["n_components"] = mi.n_components(m)
        if r["id"] == BASELINE:
            ref_e50 = x["edge_median_mm"]
        for w in wc:
            warns.append(f"{w['code']}: {r['id']} {r['name']} {w.get('message') or ''}".rstrip())
    for r in shapes:
        x = res[r["id"]]
        if x.get("status") != "READY":
            continue
        nm = f"{r['id']} {r['name']}"
        m = x.get("mesh_method")
        if m == "mesh_input" and r.get("source") == "mesh" and r["id"] != BASELINE and ref_e50 and x.get("edge_median_mm"):
            e50 = float(x["edge_median_mm"])
            if max(e50 / ref_e50, ref_e50 / e50) > r_warn and not any(
                    str(w).startswith("MESH_INPUT_SIZE_DIFF") and nm in str(w) for w in warns):
                warns.append(_cmp_text("MESH_INPUT_SIZE_DIFF", name=nm, e50=f"{e50:.2f}", ref=f"{ref_e50:.2f}",
                                       ratio=f"{r_warn:g}"))
        if m == "fallback":
            warns.append(_cmp_text("REMESH_USED", first=(x.get("cad_error") or {}).get("message") or "?") + f" — {nm}")
        fd = x.get("fidelity") or {}
        if fd.get("over_warn"):
            warns.append(_cmp_text("REMESH_FIDELITY_WARN", mm=f"{float(fd['hausdorff_mm']):.3f}",
                                   warn=f"{float(fd['warn_mm']):g}") + f" — {nm}")
        if m == "defeature":                     # v0.16.1 SR-D-20 MESH_DEFEATURED
            ds = x.get("defeature") or {}
            ce = (x.get("cad_error") or {}).get("message") or "?"
            cnt = ", ".join(f"{k} {v}" for k, v in (ds.get("counts") or {}).items())
            warns.append(_cmp_text("MESH_DEFEATURED", n=ds.get("n"), counts=cnt,
                                   suppressed_max_mm=f"{float(ds.get('suppressed_max_mm') or 0):.3f}",
                                   outside_mm=f"{float(ds.get('outside_hausdorff_mm') or 0):.3f}", first=ce)
                         + f" — {nm}")
        rf = x.get("refine")
        if m == "refine" and rf:
            if n_ref:
                rf["elem_ratio_ref"] = round(int(x["n_elems"]) / int(n_ref), 4)
                _patch_mesh_json(c, _cmp_mesh_dir(c, r["id"]), {"refine": rf})
            ratio = rf.get("elem_ratio_ref") or rf.get("elem_ratio_h")
            local = rf.get("kind") == "local"
            warns.append(_cmp_text("MESH_REFINED", name=nm, h0=f"{float(rf['base_h_mm']):g}", kind="국부" if local else "전역",
                                   h=f"{float(rf['h_mm']):g}", faces=f", 면 {len(rf.get('faces') or [])}개" if local else "",
                                   r="—" if ratio is None else f"{float(ratio):.2f}"))
    kinds = _method_kinds(shapes, res)
    if mixed_methods(kinds):
        warns.append(_cmp_text("COMPARE_MESH_METHOD_MIXED") + f" ({', '.join(sorted(kinds))})")
    return infos


MIXED_TRIGGER = ("refine", "remesh", "fallback", "mesh_input", "defeature")   # C2-D-1: {cad, case} 만이면 COMPARE_REF_CASE_MESH 가 이미 알림


def _method_kinds(shapes: list[dict], res: dict) -> set:
    """READY 형상의 메시 방식 집합(Case 기준 메시 = 'case', 사용자 메시 입력 = 'mesh_input')."""
    out = set()
    for r in shapes:
        x = res[r["id"]]
        if x.get("status") != "READY":
            continue
        k = "case" if r.get("source") == "case" else x.get("mesh_method")
        if k:
            out.add(k)
    return out


def mixed_methods(kinds) -> bool:
    """C2-D-1 경고 조건: 방식이 둘 이상이고 refine·remesh·fallback·메시 입력(source mesh) 중 하나가 섞임."""
    ks = set(kinds)
    return len(ks) > 1 and bool(ks & set(MIXED_TRIGGER))


def _cmp_path_warn(r: dict, x: dict) -> str:
    """v0.17.4 C2-D-36 경고 1줄: cad_relaxed 채택(MESH_CAD_RELAXED) 또는 대형 모델 경로(MESH_LARGE_MODEL) + [단계별: …]."""
    from esl.doe import mesh_refine as mr
    nm = f"{r['id']} {r['name']}"
    st = f" [단계별: {mr.stage_times_text(x['stage_times'])}]" if x.get("stage_times") else ""
    lg = x.get("large") or {}
    lgt = (f" · 대형 모델(면 {lg.get('n_faces')}" + "".join(f", {k} {v}" for k, v in (lg.get("periodic") or {}).items())
           + ")") if lg else ""
    rx = x.get("cad_relaxed")
    if rx and x.get("status") == "READY":
        f = rx.get("face") or {}
        fd = rx.get("fidelity") or {}
        return (f"MESH_CAD_RELAXED: {nm} cad 메시가 " + (f"면 {f.get('id')}({f.get('type')})" if f else "면")
                + "에서 실패해 면 폴백 전에 모델 전체를 ③ 옵션(" + ", ".join(f"{k} {v}" for k, v in
                                                             (rx.get("overrides") or {}).items())
                + ")으로 다시 메시함" + (f" — 원 STEP 대비 최대 {float(fd['hausdorff_mm']):.3f} mm" if fd.get("hausdorff_mm")
                                       is not None else "") + lgt + st)
    path = x.get("fallback_stage") or x.get("mesh_method") or "실패"
    return f"MESH_LARGE_MODEL: {nm} 경로 {path}{lgt} — 면 폴백 세션 상한·cad 몫 줄임 적용{st}"


def _cmp_mesh0(c: Ctx, echo) -> dict:
    """BD_MESH0 ④: 모든 STEP 같은 gmsh 프로필(SC-D-5)·형상별 병렬(run.parallel, SC-D-9). 기준 실패 → 작업 실패
    (MESH_FAILED·MESH_TOO_LARGE), 기준 크기(SC-D-7a) 불일치 → SIZE_MISMATCH. 그 밖 형상 실패 → FAILED_MESH(진행)."""
    from concurrent.futures import ThreadPoolExecutor
    c.progress(0)
    shapes = _cmp_shapes(c)
    steps = [r for r in shapes if r.get("rel")]                 # gmsh 또는 메시 입력으로 메시를 만들 형상(case 제외)
    ver, gm_ok = None, False
    if any(r.get("source", "step") == "step" for r in steps):  # gmsh 확인은 STEP 형상이 있을 때만(C2-D-16)
        gm_ok, ver = mg.available()
        if not gm_ok:
            raise EslError("GMSH_UNAVAILABLE", "gmsh 가 없어 ④ 형상 메시를 만들 수 없음")
    props = _cmp_props(c)
    prof = sc.compare_profile(c.cfg)
    ccfg = sc.compare_cfg(c.cfg)
    h = mg.check_h(float(prof["size_mm"]), prof)
    mode, lad = _cmp_mode(c)
    remesh_ok = gm_ok and bool({"remesh", "freeform"} & set(lad)) and _remesh_ready(c)   # v0.16.3 freeform 도 importStl
    avail = None
    if mode == "auto" and any(s.startswith("refine_") for s in lad):
        from esl.mech.shell import available_memory_bytes
        avail = available_memory_bytes()
    par = max(1, min(int(c.cfg["run"]["parallel"]), len(steps) or 1))
    echo(f"[bd_mesh0] ④ gmsh {ver or '-'} 프로필 h {h:g} mm · 최소 {h * float(prof['min_size_factor']):g} mm · 곡률 "
         f"{int(prof['curvature_n'])} · 경계 확장 {prof.get('extend_from_boundary')} · OCC 정리 {prof.get('occ_fix_small')} — "
         f"형상 {len(steps)}개 동시 {par}")
    if mode != "cad":
        echo(f"[bd_mesh0] 메시 방식 {mode}" + (f" · 사다리 {' → '.join(lad)}" if mode == "auto" else "")
             + ("" if remesh_ok or not ({"remesh", "freeform"} & set(lad)) else " (재메시 사용 불가 — 건너뜀)"))
    res: dict[str, dict] = {}
    done = [0]
    c._cmp_echo = echo                                  # v0.17.4 C2-D-39 사다리 단계·하위 프로세스 진행 줄
    if steps:
        with ThreadPoolExecutor(max_workers=par, thread_name_prefix="esl-cmp-mesh") as pool:
            futs = {pool.submit(_cmp_mesh_shape, c, r, h, ccfg, props, mode, lad, remesh_ok, avail): r["id"]
                    for r in steps}   # 기준이 먼저(id 순)
            for f, did in futs.items():
                r = f.result()
                res[did] = r
                done[0] += 1
                nm = _cmp_name(c, did)
                if r["status"] == "READY":
                    qy = r["quality"]
                    df = r.get("defeature") or {}
                    echo(f"[{did} {nm}] {_method_echo(r, h)} {float(r.get('seconds') or 0):.0f} s {r['n_elems']} 요소 · quad "
                         f"{r['quad_ratio']:.3f} · 품질 Fail {qy['fail_elems']}({qy['fail_ratio'] * 100:.2f} %) Warn "
                         f"{qy['warn_elems']} · 구멍 메움 {df.get('filled', 0)}·둘레 조정 {df.get('hole_sized', 0)}"
                         + (f" · 폴백 면 {qy['fallback_faces']}개(id {', '.join(map(str, qy['fallback_face_ids']))})"
                            if qy.get("fallback_faces") else ""))
                    for f in (r.get("mesh_fallback") or {}).get("faces") or []:
                        cc = f.get("center") or [0, 0, 0]
                        echo(f"[{did} {nm}]   면 {f['failed_id']}({f['type']}, 중심 {cc[0]:g},{cc[1]:g},{cc[2]:g} mm) → "
                             f"{mg.fallback_label(f)} · 처음 오류: {f['errors'][0]}")
                else:
                    echo(f"[{did} {nm}] {r['status']} {r['code']}: {_ladder_fail_text(r)}")
                if r.get("cad_error"):
                    for a in r.get("attempts") or []:
                        echo(f"[{did} {nm}]   사다리 {a['stage']}" + (f" ×{a['factor']:g}" if a.get("factor") else "")
                             + (f" h {a['h_mm']:g} mm" if a.get("h_mm") else "") + f" → {a['status']}"
                             + (f" {a['code']}" if a.get("code") else "") + (f" ({a['reason']})" if a.get("reason") else ""))
                if did == BASELINE and r["status"] != "READY":
                    for g in futs:
                        g.cancel()
                    raise EslError(r["code"], f"기준 형상 메시 실패: {_ladder_fail_text(r)}")
                c.progress(5 + 75 * done[0] / len(steps))
    ref = next(r for r in shapes if r["id"] == BASELINE)
    ref_src = "case" if ref["source"] == "case" else "step"     # 기준 출처 step|case(메시 입력 기준도 step — §3 불변)
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
    prof_rec["defeature"] = {k: v for k, v in (c.cfg["compare"].get("defeature") or {}).items()
                             if k not in DEFEAT_NEW_KEYS_V0161}   # v0.16.1 새 키 제외(SR-D-21b — base.json 바이트 불변)
    bm = sc.save_base(t, c.p("prep"), "compare", c.writer,
                      extra={"props": props, "h": h, "gmsh_version": ver, "reference_source": ref_src,
                             "profile": prof_rec, "profile_sha256": ev.config_hash(prof_rec)})
    warns = list(size_info.get("warnings") or [])
    infos = _cmp_mesh_notes(c, shapes, res, ref_mesh, h, warns)
    for r in shapes:
        x = res[r["id"]]
        qy = x.get("quality")
        if qy and qy["over_limit"]:
            warns.append(f"SHAPE_QUALITY_FAIL: {r['id']} {r['name']} 품질 Fail 요소 {qy['fail_elems']}개 "
                         f"({qy['fail_ratio'] * 100:.2f} % > {qy['max_fail_ratio'] * 100:g} %) — 차단 아님")
        if x.get("cad_relaxed") or x.get("large"):        # v0.17.4 C2-D-32·33·36 고른 경로 + 단계별 초
            warns.append(_cmp_path_warn(r, x))
        if qy and qy.get("fallback_faces"):
            warns.append(f"MESH_FACE_FALLBACK: {r['id']} {r['name']} 면 {qy['fallback_faces']}개(gmsh 면 id "
                         f"{', '.join(map(str, qy['fallback_face_ids']))})를 면 폴백("
                         f"{', '.join(qy.get('fallback_stages') or []) or '다른 2D 알고리즘·제약 해제'})으로 메시 — "
                         "그 면 주변 요소 모양이 다른 형상과 다를 수 있음(mesh.json mesh_fallback)")
    doc = {"schema": "esl/doe_compare/1", "reference_source": ref_src, "profile": prof_rec, "h": h,
           "gmsh_version": ver, "frame_sha256": ev.config_hash(t.frame),
           "shapes": [{"id": r["id"], "name": r["name"], "file_name": r.get("file_name"), "reference": r["reference"],
                       "source": r["source"], **{k: v for k, v in res[r["id"]].items() if k != "id"}} for r in shapes]}
    bad = [r for r in shapes if r["id"] != BASELINE and res[r["id"]].get("status") != "READY"]
    if bad:                                             # v0.17.4 C2-D-41 형상 메시 실패 = 맨 앞 경고(차단 수준 표시)
        warns.insert(0, "COMPARE_SHAPES_FAILED: 비교 형상 " + f"{len(bad)}/{len(shapes) - 1}개 메시 실패 — 비교에서 빠짐: "
                     + "; ".join(f"{r['id']} {r['name']} {res[r['id']].get('code')}" for r in bad))
    doc["warnings"] = warns
    if mode != "cad":                                   # v0.16.0(cad = 키 없음 — v0.15.x 와 같은 문서)
        doc["mesh_mode"] = mode
        doc["mesh_ladder"] = lad
    c.write_json(os.path.join("prep", sc.COMPARE_JSON), doc)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(size=size_info, props=props, mesh_size_mm=h, gmsh_version=ver)
    inp["warnings"] = list(inp.get("warnings") or []) + warns
    if infos:
        inp["info"] = list(inp.get("info") or []) + infos
    c.write_json(os.path.join("prep", "input.json"), inp)
    nf = sum(1 for r in doc["shapes"] if r["status"] != "READY")
    echo(f"[bd_mesh0] 기준 d000 노드 {bm['n_nodes']} · 요소 {bm['n_elems']}, 형상 메시 실패 {nf}개")
    n_cmp = len(shapes) - 1
    need = int((c.cfg.get("compare") or {}).get("min_ready_shapes", 1) or 0)
    if n_cmp > 0 and need > 0 and n_cmp - len(bad) < min(need, n_cmp):   # C2-D-41 비교할 형상이 없음 → 단계 실패
        raise EslError("COMPARE_NO_SHAPES", f"비교 형상 메시 성공 {n_cmp - len(bad)}/{n_cmp}개 < 필요 {min(need, n_cmp)}개"
                                            f"(bead_doe.compare.min_ready_shapes) — " + _ladder_fail_text(res[bad[0]['id']])[:300])
    c.progress(100)
    out = {"files": [f"prep/{sc.COMPARE_JSON}", "prep/base_mesh.npz", "prep/base.json"], "warnings": warns,
           "h": h, "n_failed": nf}
    if infos:
        out["info"] = infos
    return out


def _cmp_loads(c: Ctx, echo) -> dict:
    """BD_LOADS ④: 기준 frame 고정(prep/base.json), d000 하중(셀 매핑) → loads.npz, 형상별 크기·정렬(SC-D-7b) →
    FAILED_SIZE(그 형상만), 셀당 노드 경고 → prep/compare.json. v0.20.0 스냅샷 load_transfer 있음 = ``_cmp_loads_lt``."""
    L = _lt(c)
    if L is not None:
        return _cmp_loads_lt(c, echo, L)
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
    keep = {"cfg": _cfg_hash(c), "props": bmeta.get("props"), "profile": bmeta.get("profile"),
            "step": sh.get("sha256"), "source": sh.get("source")}
    mode = str(c.D.get("mesh_mode") or "cad")
    if mode != "cad":                       # C2-D-15·25: mode ≠ cad 일 때만(v0.15.x·cad 스터디 해시 불변)
        cc = c.cfg.get("compare") or {}
        keep["mesh_mode"] = mode
        keep["remesh"] = ev.config_hash(_remesh_hash_view(cc.get("remesh") or {}))
        keep["ladder"] = list(_cmp_mode(c)[1])
        keep["refine"] = ev.config_hash({k: v for k, v in (cc.get("refine") or {}).items()
                                         if k not in REFINE_NEW_KEYS_V0163})   # v0.16.3 시간 몫 키 제외(메시 결과와 무관)
    if sh.get("source") == "mesh":          # 메시 형상 = (주·include sha256 목록, part_id, mesh_input 설정 해시)
        from esl.doe import mesh_input as mi
        keep["mesh_files"] = [f.get("sha256") for f in sh.get("files") or []]
        keep["part_id"] = sh.get("part_id")
        keep["mesh_input"] = ev.config_hash(mi.hash_view(c.cfg))      # v0.16.1: diag 절 제외(SR-D-24)
    L = _lt(c)
    if L is not None:                       # v0.20.0 LT-12: 스냅샷에 load_transfer 가 있을 때만(diag 제외 — legacy 해시 불변)
        keep["load_transfer"] = ev.config_hash(tp.hash_view(L))
    if _sm(c) is not None:                  # v0.20.0 SM-6(스냅샷 doe.rank 있을 때만 — metric 은 해시 밖)
        keep["stiffness"] = SM_SCHEMA
    if _cmp_row_method(c, did) == "defeature":   # v0.16.1 SR-D-21b: defeature 형상만 설정 해시(기준 d000 포함)
        df = (c.cfg.get("compare") or {}).get("defeature") or {}
        keep["defeature_cfg"] = ev.config_hash({k: df.get(k) for k in DEFEAT_NEW_KEYS_V0161 + ("min_bead_height_mm",)})
    cfg = ev.config_hash(keep)
    return ev.input_sha256({}, mesh_sha, ev.config_hash(bmeta["frame"]), cfg, None)


REMESH_HASH_SKIP_V0161 = ("warn_rel_cad",)    # remesh.fidelity 의 경고 전용 새 키(SR-D-27) — 메시와 무관해 해시에서 항상 제외


def _remesh_hash_view(rm: dict) -> dict:
    """keep["remesh"] 해시용 사본: fidelity 의 경고 전용 v0.16.1 키를 뺌 → v0.16.0 스냅샷·cad 형상 해시 불변(SR-D-27)."""
    out = dict(rm)
    if isinstance(out.get("fidelity"), dict):
        out["fidelity"] = {k: v for k, v in out["fidelity"].items() if k not in REMESH_HASH_SKIP_V0161}
    return out


def _cmp_row_method(c: Ctx, did: str) -> str | None:
    """prep/compare.json 형상 행의 mesh_method(없으면 None)."""
    try:
        return next((x.get("mesh_method") for x in _cmp_doc(c)["shapes"] if x.get("id") == did), None)
    except (OSError, ValueError, KeyError):
        return None


def _cmp_design_mesh(c: Ctx, t, did: str) -> tuple[dict, list, list, dict]:
    """④ 형상(기준 d000 포함 같은 규칙): 메시 → compare_target(frame 고정·auto_supports) → 셀 매핑 하중.
    v0.20.0 load_transfer 스냅샷 = 영역·이전 지지·``load_transfer.shape_loads``(실행·view3d·이어하기 같은 함수)."""
    if _lt(c) is not None:
        tgt, _reg, loads, _info = _lt_design(c, t, did)
        et = np.asarray(tgt.mesh["elem_type"]).astype(int)
        return tgt.mesh, list(tgt.supports), loads, {"n_nodes": tgt.n_nodes, "n_elems": tgt.n_elems,
                                                     "quad_frac": float(np.sum(et == 4)) / max(et.size, 1)}
    mesh = dict(t.mesh) if did == BASELINE else mg.load_mesh(_cmp_mesh_dir(c, did))
    dt = sc.compare_target(mesh, t.frame)
    loads, _ = sc.entry_loads(dt, c.entries(raw=False), c.mapping_opts())
    et = np.asarray(dt.mesh["elem_type"]).astype(int)
    return dt.mesh, list(dt.supports), loads, {"n_nodes": dt.n_nodes, "n_elems": dt.n_elems,
                                               "quad_frac": float(np.sum(et == 4)) / max(et.size, 1)}


# ---------------------------------------------------------------- v0.20.0 하중 전달 (esl_load_transfer.md — 계획 표 §13.3)
# 공용 모듈 load_transfer(모드 무관) + 계획 표 transfer_plan + ④ 전용 compare_lt. 하중 자리는 ``_plan_loads`` 하나 —
# 시나리오 이름으로 분기하지 않고 계획 필드(reuse·identity·placement·mask)만 읽는다.
LT_JSON = "load_transfer.json"
LT_DIAG_JSON = "load_transfer_diag.json"
LT_REGION_NPZ = "region.npz"
LT_TRANSFER_NPZ = "transfer.npz"
LT_LOADS_ALT = "loads_alt.npz"
LT_CSV_COLS = ["lt_method", "lt_far_frac", "lt_dM_rel", "score_alt"]
LT_SEP = "\x1f"                                 # 진단 풀이 하중 id = entry_id + LT_SEP + variant(결과 per_esl 에는 안 들어감)


def _lt(c: Ctx) -> dict | None:
    """스냅샷 doe.load_transfer(해석된 설정) — 없으면 None(legacy, 각 모드 지금 경로 그대로 LT-11·18)."""
    if c.scn not in ("same", "mesh", "step", "compare", "select"):
        return None
    if not hasattr(c, "_lt_cache"):
        c._lt_cache = tp.resolve(c.D.get("load_transfer"), c.scn)
    return c._lt_cache


def _lt_plan(c: Ctx) -> dict:
    return tp.plan_for(c.scn, select_base(c) if c.scn == "select" else None)


def _lt_ents(c: Ctx):
    if not hasattr(c, "_lt_ents_cache"):
        c._lt_ents_cache = c.entries(raw=True)
    return c._lt_ents_cache


def _lt_srcs(ents) -> list[dict]:
    return [ltm.src_load(e.meta.get("entry_id"), e.raw, e.raw["f"], e.meta.get("frame"), e.summary_for_mapping())
            for e in ents]


def _lt_h(c: Ctx, bmeta: dict, mesh: dict | None = None) -> float:
    """사영 길이 척도 h: 기준 메타 h(③④ 메시 크기) → ④ 프로필 → 대상 메시 모서리 길이 중앙값(①②)."""
    if bmeta.get("h"):
        return float(bmeta["h"])
    if _lt_plan(c)["dst"] == "shape" or mesh is None:   # 계획 열 dst shape(형상마다 메시 = ④) → 프로필 크기
        return float(sc.compare_profile(c.cfg)["size_mm"])
    from esl.opt.mesh_check import _edge_lengths
    L = _edge_lengths(np.asarray(mesh["x0"], dtype=np.float64), np.asarray(mesh["conn"], dtype=np.int64),
                      np.asarray(mesh["elem_type"]).astype(int))
    return float(np.nanmedian(L))


def _lt_inp(c: Ctx) -> dict:
    p = c.p("prep", "input.json")
    return (U.read_json(p).get("load_transfer") or {}) if os.path.isfile(p) else {}


def _lt_placement(c: Ctx, plan: dict) -> dict:
    """배치(LT-23): 계획 global = 그대로, auto = 준비(BD_LOADS)에서 베이스라인으로 1회 정한 값(prep/input.json)."""
    if plan["placement"] != "auto":
        return {"kind": "global"}
    pl = getattr(c, "_lt_place", None) or _lt_inp(c).get("placement") or {"kind": "global"}
    return {k: v for k, v in pl.items() if k in ("kind", "R", "t")}


def _lt_decide_placement(c: Ctx, plan: dict, t, region, h: float, fc: dict | None = None) -> tuple[dict, list]:
    """②③ placement auto: 구멍 특징 frame 판정(``step_graph.frame_check`` — ③ select 는 fixed_transfer 결과 재사용) ok →
    global, 강체 맞춤 ok → rigid(R, t), 아니면 frame(정규화 사상) + 정보 LT_PLACEMENT."""
    if plan["placement"] != "auto":
        return {"kind": "global"}, []
    if fc is None:
        from esl.doe import step_graph as sg
        raw = _lt_ents(c)[0].raw
        fc = sg.frame_check({k: raw[k] for k in ("x0", "conn", "elem_type", "node_id")}, t.mesh, region, c.cfg, h=h,
                            hole_min_perimeter=float(c.ocfg["keepout"]["hole_min_perimeter_mm"]))
    fit = fc.get("fit") or {}
    if fc.get("ok"):
        pl = {"kind": "global", "resid_med_mm": fc.get("resid_med_mm")}
    elif fit.get("ok"):
        pl = {"kind": "rigid", "R": fit["R"], "t": fit["t"], "resid_med_mm": fit.get("resid_med_mm")}
    else:
        pl = {"kind": "frame", "resid_med_mm": fc.get("resid_med_mm")}
    info = [] if pl["kind"] == "global" else [_cmp_text("LT_PLACEMENT", kind=pl["kind"],
                                                         resid_med_mm=pl.get("resid_med_mm"))]
    return U.jsonable(pl), info


def _lt_method(c: Ctx, variant=None) -> dict:
    return tp.method_of(_lt(c), variant, c.mapping_opts())


def _plan_loads(c: Ctx, plan: dict, did: str, dst: dict, variant=None, cache: dict | None = None) -> tuple[list, dict | None]:
    """하중 자리 하나(§13.3): reuse once 이고 안(did ≠ d000) = 베이스라인 노드 하중(prep/loads.npz) 그대로, 그 밖 = 공용 실행기
    ``run_transfer_plan``(identity 키·배치는 계획에서). variant = (method, cell_size_mm) — None = 주 방식."""
    if plan["reuse"] == "once" and did != BASELINE and variant is None:
        _, loads = sc.load_loads(c.p("prep"))
        return loads, None
    rp = {"identity": {"key": plan["identity"], "coord_tol_rel": c.coord_tol()}, "placement": _lt_placement(c, plan)}
    return ltm.run_transfer_plan(rp, _lt_srcs(_lt_ents(c)), dst, _lt_method(c, variant), cache if cache is not None else {})


def _lt_target_loads(c: Ctx, did: str, tgt, region, h: float) -> list:
    """per_target 대상(옛 ③ 안·view3d) 하중 — 계획 그대로 ``_plan_loads``, 진단 풀이용 문맥(c._lt_last) 기록."""
    plan = _lt_plan(c)
    dst = ltm.dst_mesh(tgt.mesh, tgt.frame, region if plan["mask"] != "none" else None, h)
    cache: dict = {}
    loads, info = _plan_loads(c, plan, did, dst, None, cache)
    c._lt_last = {"did": did, "dst": dst, "cache": cache, "info": info, "region": region}
    return loads


def _lt_warn_text(w: dict) -> str:
    kw = {k: (f"{v:.3g}" if isinstance(v, float) else v) for k, v in w.items() if k != "code"}
    return _cmp_text(w["code"], **kw)


def _lt_labels(c: Ctx) -> dict:
    return {e["id"]: e.get("label") or e["id"][:8] for e in c.D["entries"]}


def _lt_row(c: Ctx, did: str, info: dict, **extra) -> dict:
    """prep/load_transfer.json 형상(대상) 행(§5 형식 — register 가 lt{} 로 붙임)."""
    lab = _lt_labels(c)
    return U.jsonable({"id": did, "status": "READY", "warnings": [], **extra, "transfer": info["transfer"],
                       "fast_path": info["fast_path"],
                       "per_esl": [{"entry_id": p["entry_id"], "label": lab.get(p["entry_id"], str(p["entry_id"])[:8]),
                                    "primary": {k: v for k, v in p.items() if k != "entry_id"}}
                                   for p in info["per_esl"]]})


def _lt_far_text(L: dict, info: dict) -> tuple[str | None, str | None]:
    state, ff = ltm.far_state(info, L["work"])
    tr = info["transfer"]
    if state == "LT_TRANSFER_FAILED":
        return state, _cmp_text(state, far_frac=f"{ff:.3g}", fail=f"{float(L['work']['fail_frac']):g}",
                                dist=f"{float(L['work']['fail_dist_mm']):g}",
                                max_mm=f"{tr['max_dist_mm']:.3g}")
    if state == "LT_FAR_NODES":
        return state, _cmp_text(state, far_n=tr["far_n"], far_frac=f"{ff:.3g}", max_mm=f"{tr['max_dist_mm']:.3g}")
    return None, None


def _lt_ldoc(c: Ctx, plan: dict, placement: dict) -> dict:
    L = _lt(c)
    alt = tp.alt_variant(L)
    d = {"schema": tp.SCHEMA, "scenario": c.scn, "method": L["method"], "cell_size_mm": L.get("cell_size_mm"),
         "variant": tp.variant_label(*tp.primary_variant(L)),
         "alt": None if alt is None else {"method": alt[0], "cell_size_mm": alt[1]},
         "plan": {"id": plan["id"], "reuse": plan["reuse"], "placement": placement,
                  "alt_designs": tp.alt_designs(L, plan), "version": tp.PLAN_VERSION},
         "shapes": [], "warnings": []}
    if "support" in L:
        d.update(support=L["support"], region_mode=(L.get("region") or {}).get("mode"))
    return d


def _lt_base_loads(c: Ctx, t, bmeta: dict, ents, region=None, fc: dict | None = None) -> tuple[list, dict]:
    """①②③ 베이스라인 전달(계획 dst = baseline·design 의 베이스라인): 배치 1회 결정 → ``_plan_loads(d000)`` → 먼 노드 판정
    (BASELINE_FAILED LT_TRANSFER_FAILED) → prep/load_transfer.json(베이스라인 1행) · (alt_designs ∧ once) prep/loads_alt.npz.
    반환 (loads, linfo) — linfo 는 input.json.loads 형식, c._lt_inp_rec = input.json.load_transfer."""
    L, plan = _lt(c), _lt_plan(c)
    h = _lt_h(c, bmeta, t.mesh)
    pl, pinfo = _lt_decide_placement(c, plan, t, region, h, fc)
    c._lt_place = pl
    dst = ltm.dst_mesh(t.mesh, t.frame, region if plan["mask"] != "none" else None, h)
    cache: dict = {}
    loads, info = _plan_loads(c, plan, BASELINE, dst, None, cache)
    state, msg = _lt_far_text(L, info)
    if state == "LT_TRANSFER_FAILED":
        raise EslError("BASELINE_FAILED", f"{msg} — 셀 방식을 고르거나 기준 모델을 확인하세요")
    warns = [_lt_warn_text(w) for w in info["warnings"]] + ([msg] if msg else [])
    ldoc = _lt_ldoc(c, plan, pl)
    ldoc["warnings"] = warns + pinfo
    ldoc["shapes"].append(_lt_row(c, BASELINE, info, region=None if region is None else
                                  {"n_in": int(np.sum(region)), "n_out": int(np.size(region) - np.sum(region))}))
    if plan["reuse"] == "once" and tp.alt_designs(L, plan):          # LT-20: alt 하중도 베이스라인 1회
        al, _ = _plan_loads(c, plan, BASELINE, dst, tp.alt_variant(L), cache)
        mg.save_npz_det(c.writer.guard(c.p("prep", LT_LOADS_ALT)),
                        {"node_id": np.asarray(t.mesh["node_id"], dtype=np.int64),
                         "entry_ids": np.asarray([str(e) for e, _ in al]), "F": np.stack([f for _, f in al])})
    c.write_json(os.path.join("prep", LT_JSON), U.jsonable(ldoc))
    c._lt_inp_rec = U.jsonable({**tp.public(L), "plan": plan["id"], "placement": pl, "fast_path": info["fast_path"]})
    linfo = {"method": info["variant"], "fast_path": info["fast_path"],
             "per_entry": U.jsonable([{"entry_id": p["entry_id"], "strategy": p["strategy"], "dF_rel": p.get("dF_rel"),
                                       "dM_rel": p.get("dM_rel"), "far_frac": p.get("far_frac")}
                                      for p in info["per_esl"]]),
             "warnings": warns}
    return loads, linfo


# ---------------------------------------------------------------- ④ 전용(지지 이전·영역 — compare_lt)
def _lt_shape_dir(c: Ctx, did: str) -> str:
    return c.p("prep", "shapes", did)


def _lt_load_region(c: Ctx, did: str):
    p = os.path.join(_lt_shape_dir(c, did), LT_REGION_NPZ)
    if not os.path.isfile(p):
        return None
    return np.asarray(U.load_npz(p)["region"], bool)


def _lt_save_region(c: Ctx, did: str, region) -> None:
    d = _lt_shape_dir(c, did)
    p = os.path.join(d, LT_REGION_NPZ)
    if region is None:
        if os.path.isfile(p):
            os.remove(c.writer.guard(p))
        return
    c.writer.makedirs(d)
    mg.save_npz_det(c.writer.guard(p), {"region": np.asarray(region, bool)})


def _lt_prep_doc(c: Ctx) -> dict:
    p = c.p("prep", LT_JSON)
    return U.read_json(p) if os.path.isfile(p) else {}


def _lt_dst(c: Ctx, tgt, region, h: float) -> dict:
    return ltm.dst_mesh(tgt.mesh, tgt.frame, region, h)


def _lt_file_cache(c: Ctx, dst: dict, did: str | None) -> tuple[dict, str | None, str]:
    """④ W 파일 캐시(prep/shapes/<did>/transfer.npz, 키 = 대상 sha·work 설정) → run_transfer_plan cache dict."""
    L = _lt(c)
    key = clt.work_key(dst["mesh"], dst["elem_mask"], L["work"], dst["h"])
    path = None if did is None else os.path.join(_lt_shape_dir(c, did), LT_TRANSFER_NPZ)
    W = clt.load_work(path, key) if path else {}
    m = _lt_method(c)
    return {ltm.cache_key(sha, dst, None, m): w for sha, w in W.items()}, path, key


def _lt_save_cache(c: Ctx, cache: dict, path: str | None, key: str) -> None:
    if cache and path:
        c.writer.makedirs(os.path.dirname(path))
        clt.save_work(path, {k[0]: w for k, w in cache.items()}, key, c.writer)


def _lt_supports(c: Ctx, t, mesh: dict, did: str, region, h: float, ref_sup: list | None) -> tuple:
    """LT-7 지지 → (compare_target, 지지 정보). d000 = 영역 auto, 형상 = transfer(실패 → 영역 auto + fallback)."""
    L = _lt(c)
    if did == BASELINE or L["support"] == "auto" or not ref_sup:
        tgt = sc.compare_target(mesh, t.frame, region=region)
        return tgt, {"mode": "auto", "max_dist_mm": None}
    tol = float(L["support_tol_mm"]) if L.get("support_tol_mm") is not None else 2.0 * float(h)
    sup, info = clt.transfer_supports(ref_sup, mesh, region, tol)
    tgt = sc.compare_target(mesh, t.frame, supports=sup)
    return tgt, info


def _lt_design(c: Ctx, t, did: str, variant=None):
    """④ BD_EVAL·view3d: 형상 메시·영역(prep)·지지(prep 기록, 없으면 다시)·하중 → (Target, 영역, loads, info)."""
    bmeta = U.read_json(c.p("prep", "base.json"))
    h = _lt_h(c, bmeta)
    mesh = dict(t.mesh) if did == BASELINE else mg.load_mesh(_cmp_mesh_dir(c, did))
    reg = _lt_load_region(c, did)
    pdoc = _lt_prep_doc(c)
    row = next((x for x in pdoc.get("shapes") or [] if x.get("id") == did), None)
    nodes = ((row or {}).get("supports") or {}).get("nodes")
    if nodes:
        tgt = sc.compare_target(mesh, t.frame, supports=[(int(s["node_id"]), str(s["dof"])) for s in nodes])
    else:
        ref = next((x for x in pdoc.get("shapes") or [] if x.get("id") == BASELINE), None)
        tgt, _ = _lt_supports(c, t, mesh, did, reg, h, ((ref or {}).get("supports") or {}).get("nodes"))
    dst = _lt_dst(c, tgt, reg, h)
    cache, _p, _k = _lt_file_cache(c, dst, did)
    loads, info = _plan_loads(c, _lt_plan(c), did, dst, variant, cache)
    c._lt_last = {"did": did, "dst": dst, "cache": cache, "info": info, "region": reg}
    return tgt, reg, loads, info


def _lt_mesh_loads(c: Ctx, t, mesh: dict) -> tuple:
    """수렴 점검(C2-D-24) d000_h<h> 다시 메시: 같은 규칙(영역·d000 지지 이전·같은 계획) → (Target, 영역, loads)."""
    L = _lt(c)
    bmeta = U.read_json(c.p("prep", "base.json"))
    h = _lt_h(c, bmeta)
    ents = _lt_ents(c)
    reg, _ = clt.region_of(mesh, np.asarray(ents[0].raw["x0"], dtype=np.float64), L["region"], h)
    ref = next((x for x in _lt_prep_doc(c).get("shapes") or [] if x.get("id") == BASELINE), None)
    tgt, _ = _lt_supports(c, t, mesh, "refine", reg, h, ((ref or {}).get("supports") or {}).get("nodes"))
    loads, _ = _plan_loads(c, _lt_plan(c), "refine", _lt_dst(c, tgt, reg, h))
    return tgt, reg, loads


def _cmp_loads_lt(c: Ctx, echo, L: dict) -> dict:
    """BD_LOADS ④ v0.20.0(§2 ①~⑥): 형상마다 영역(region.npz) → 기준 frame(d000 영역) → 지지(d000 auto / 형상 이전) →
    W 연산자(transfer.npz) → 하중 지표(prep/load_transfer.json, 먼 노드 과다 → FAILED_SIZE LT_TRANSFER_FAILED) →
    d000 하중(prep/loads.npz, 스터디 방식)."""
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    ents = _lt_ents(c)
    plan = _lt_plan(c)
    h = _lt_h(c, bmeta)
    rc = L["region"]
    a_xyz = np.asarray(ents[0].raw["x0"], dtype=np.float64)
    doc = _cmp_doc(c)
    ccfg = c.cfg["compare"]
    warns, infos = [], []
    ref_mesh = mg.load_mesh(_cmp_mesh_dir(c, BASELINE))
    reg0, ri0 = clt.region_of(ref_mesh, a_xyz, rc, h)
    if reg0 is not None:                         # LT-8 ② 기준 frame·크기 = d000 영역 요소(영역 = 전체면 base 그대로)
        base_keys = {"schema", "scenario", "target", "frame", "supports", "normals", "source", "warnings",
                     "topo_sha256", "n_nodes", "n_elems", "mesh_sha256"}
        t2, _ = sc.template_base(ref_mesh, c.entries(raw=False), c.ocfg["size"], inch=c.D.get("inch"),
                                 source=t.source, region=reg0)
        sc.save_base(t2, c.p("prep"), "compare", c.writer, extra={k: v for k, v in bmeta.items() if k not in base_keys})
        t, bmeta = sc.load_base(c.p("prep"))
        doc["frame_sha256"] = ev.config_hash(t.frame)
    pl = {"kind": "global"}
    ldoc = _lt_ldoc(c, plan, pl)
    order = [r for r in doc["shapes"] if r["id"] == BASELINE] + [r for r in doc["shapes"] if r["id"] != BASELINE]
    n = len(order)
    ref_sup = None
    d0_loads, d0_info = None, None
    t_start = time.monotonic()
    for k, r in enumerate(order):
        did = r["id"]
        if did != BASELINE and r["status"] != "READY":
            continue
        mesh = dict(t.mesh) if did == BASELINE else mg.load_mesh(_cmp_mesh_dir(c, did))
        reg, ri = (reg0, ri0) if did == BASELINE else clt.region_of(mesh, a_xyz, rc, h)
        _lt_save_region(c, did, reg)
        rw, rinf = clt.region_messages(ri, rc)
        lrow = {"id": did, "status": "READY", "region": {k_: ri.get(k_) for k_ in ("mode", "rule", "n_in", "n_out")},
                "warnings": []}
        for x in rinf:
            infos.append(f"{_lt_warn_text(x)} — {did}")
            lrow["warnings"].append(infos[-1])
        for x in rw:
            warns.append(f"{_lt_warn_text(x)} — {did}")
            lrow["warnings"].append(warns[-1])
            r.setdefault("warnings", []).append(x["code"])
        if did != BASELINE:
            chk = sc.shape_check(mesh, t.frame, ents, c.ocfg["size"], ccfg, inch=c.D.get("inch"), region=reg)
            r.update(size=chk["size"], align=chk["align"])
            if not chk["ok"]:
                r.update(status="FAILED_SIZE", code=chk["code"], message=chk["message"])
                lrow.update(status="FAILED_SIZE", code=chk["code"])
                ldoc["shapes"].append(lrow)
                echo(f"[{did} {r['name']}] FAILED_SIZE {chk['code']}: {chk['message']}")
                continue
        try:
            tgt, sinfo = _lt_supports(c, t, mesh, did, reg, h, ref_sup)
            dst = _lt_dst(c, tgt, reg, h)
            cache, path, key = _lt_file_cache(c, dst, did)
            loads, info = _plan_loads(c, plan, did, dst, None, cache)
        except EslError as exc:
            if did == BASELINE:
                raise EslError("BASELINE_FAILED", f"기준 형상 하중 전달 실패 {exc.code}: {exc.message}") from None
            lrow.update(status="ERROR", code=exc.code, message=exc.message)      # 실행에서 같은 오류 → FAILED_SOLVE
            ldoc["shapes"].append(lrow)
            echo(f"[{did} {r['name']}] 하중 전달 준비 오류 {exc.code}: {exc.message}")
            continue
        _lt_save_cache(c, cache, path, key)
        sup_rec = {**sinfo, "nodes": clt.support_xyz(tgt.mesh, tgt.supports)}
        if did == BASELINE:
            ref_sup = sup_rec["nodes"]
        if sinfo["mode"] == "fallback":
            w = _cmp_text("LT_SUPPORT_FALLBACK", reason=sinfo.get("reason"))
            warns.append(f"{w} — {did}")
            lrow["warnings"].append(warns[-1])
            r.setdefault("warnings", []).append("LT_SUPPORT_FALLBACK")
        for x in info["warnings"]:
            if did == BASELINE:                  # ESL 자체 불평형 = 형상 무관(준비 전체 경고 1회)
                ldoc["warnings"].append(_lt_warn_text(x))
                warns.append(ldoc["warnings"][-1])
        row = _lt_row(c, did, info)
        lrow.update(supports=sup_rec, transfer=row["transfer"], fast_path=row["fast_path"], per_esl=row["per_esl"])
        state, msg = _lt_far_text(L, info)
        if state == "LT_TRANSFER_FAILED":
            if did == BASELINE:
                raise EslError("BASELINE_FAILED", f"기준 형상 {msg}")
            r.update(status="FAILED_SIZE", code=state, message=msg.split(": ", 1)[-1])
            lrow.update(status="FAILED_SIZE", code=state)
            lrow["warnings"].append(f"{msg} — {did}")
            echo(f"[{did} {r['name']}] FAILED_SIZE {msg}")
        elif state == "LT_FAR_NODES":
            warns.append(f"{msg} — {did}")
            lrow["warnings"].append(warns[-1])
            r.setdefault("warnings", []).append(state)
        if L["method"] == "cell" and L.get("cell_size_mm") is None and did != BASELINE:
            gw = sc.mapping_resolution(mesh, t.frame, (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]),
                                       c.ocfg["check"]["min_nodes_per_cell"])
            if gw:
                r.setdefault("warnings", []).append(gw)
                warns.append(f"{gw} — {did}")
        ldoc["shapes"].append(lrow)
        if did == BASELINE:
            d0_loads, d0_info = loads, info
        c.progress(5 + 85 * (k + 1) / max(n, 1))
    loads_sha = sc.save_loads(c.p("prep"), t.mesh["node_id"], d0_loads, c.writer)
    linfo = {"method": d0_info["variant"], "fast_path": d0_info["fast_path"],
             "per_entry": U.jsonable([{"entry_id": p["entry_id"], "dF_rel": p.get("dF_rel"), "dM_rel": p.get("dM_rel")}
                                      for p in d0_info["per_esl"]]), "warnings": []}
    ldoc["seconds"] = round(time.monotonic() - t_start, 3)
    c.write_json(os.path.join("prep", LT_JSON), U.jsonable(ldoc))
    doc["loads"] = {"sha256": loads_sha, **linfo}
    c.write_json(os.path.join("prep", sc.COMPARE_JSON), doc)
    inp = U.read_json(c.p("prep", "input.json"))
    inp.update(loads={"sha256": loads_sha, **linfo}, n_beads=0, n_params=0,
               load_transfer={**tp.public(L), "plan": plan["id"], "placement": pl, "fast_path": d0_info["fast_path"]})
    c.write_json(os.path.join("prep", "input.json"), inp)
    ready = [r["id"] for r in doc["shapes"] if r["status"] == "READY"]
    echo(f"[bd_loads] ④ 기준 frame 고정 · ESL {len(d0_loads)}개 하중 전달 {d0_info['variant']}"
         + (" (기준 = ESL 메시 — ① 과 같은 하중)" if d0_info["fast_path"] else "")
         + f" · 지지 {L['support']} · 영역 {rc['mode']} · 실행 대상 형상 {len(ready)}/{n}")
    c.progress(100)
    return {"files": ["prep/loads.npz", f"prep/{sc.COMPARE_JSON}", f"prep/{LT_JSON}"], "warnings": warns,
            "info": infos, "n_ready": len(ready), "n_shapes": n}


# ---------------------------------------------------------------- 진단 풀이(모드 무관, LT-10·20)
def _lt_truth_compare(c: Ctx, ents, props: dict, h: float, rc: dict, skip: set, warns: list) -> dict:
    """④ 참값 a_direct(LT-10): A 메시(스터디 물성)·A 영역 auto 3-2-1 직접 풀이 — ``_a_direct``(강성 지표 참조와 같은 인수분해)."""
    ad = _a_direct(c, "study", rc, h, warns, [])
    return {e: _truth_row("a_direct", a, a["f"]) for e, a in ad.items() if e not in skip}


def _truth_row(kind: str, p: dict, f) -> dict:
    a = np.linalg.norm(np.asarray(f, dtype=np.float64), axis=1)
    return {"kind": kind, "C": p["C"], "umax": p["umax"], "f": None, "u": None, "sum_abs_f": float(a.sum()),
            "max_abs_f": float(a.max()) if a.size else 0.0}


def _lt_truth_raw(c: Ctx, ents, skip: set, warns: list, infos: list) -> dict:
    """②③ 참값 a_direct(LT-20): A 메시·ESL raw 자기 물성·자기 지지(rank < 6 → A auto + LT_TRUTH_AUTO_SUPPORT) 직접 풀이 —
    ``_a_direct``(강성 지표 참조 u_ref 와 같은 인수분해·같은 해). 배율은 전달 오차 + 모델 차(A ≠ B)."""
    ad = _a_direct(c, "raw", None, 0.0, warns, infos)
    return {e: _truth_row("a_direct", a, a["f"]) for e, a in ad.items() if e not in skip}


def _ev(c: Ctx, mesh: dict, sup, loads, region=None, keep_u=(), six=False) -> dict:
    """해석 1회: 옛 스냅샷 = ``evaluate.evaluate`` 그대로, 강성 지표 스냅샷 = ``_solve6``(같은 값 + 주 하중 변위 keep_u 전체,
    six = 6 dof 해 보관 — 베이스라인 참조 변위)."""
    rkw = {"region": region} if region is not None else {}
    if _sm(c) is None:
        return ev.evaluate(mesh, sup, loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"],
                           keep_u=list(keep_u), **rkw)
    prim = [e for e, _ in loads if LT_SEP not in str(e)]
    return _solve6(mesh, sup, loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"],
                   keep_u=list(dict.fromkeys(list(keep_u) + prim)), keep6=prim if six else (), **rkw)


def _lt_eval(c: Ctx, t, did: str, mesh: dict, sup: list, loads: list, region, dd: str, h: float) -> dict:
    """BD_EVAL 하중 전달 스냅샷(모든 모드): 주 방식 하중 + 진단 variant(베이스라인 = 참값·alt·셀 훑기, 안 = alt_designs 일 때
    alt)를 인수분해 1회로 풀고 run/designs/<did>/load_transfer.json(진단)을 쓴다. 반환 = 주 방식 evaluate 결과 형식."""
    from esl.opt import target as tg
    L, plan = _lt(c), _lt_plan(c)
    ents = _lt_ents(c)
    labels = _lt_labels(c)
    dg = L.get("diag") or {}
    last = getattr(c, "_lt_last", None)
    if last is not None and last.get("did") == did:
        dst, cache, info = last["dst"], last["cache"], last["info"]
    else:
        dst, cache, info = ltm.dst_mesh(mesh, t.frame, region if plan["mask"] != "none" else None, h), {}, None
    if info is None:                             # once 의 안 = 베이스라인 하중 그대로 → 베이스라인 행
        prow = next((x for x in _lt_prep_doc(c).get("shapes") or [] if x.get("id") == BASELINE), {}) or {}
        info = {"variant": _lt_prep_doc(c).get("variant"), "fast_path": prow.get("fast_path"),
                "transfer": prow.get("transfer"),
                "per_esl": [{"entry_id": p["entry_id"], **(p.get("primary") or {})} for p in prow.get("per_esl") or []]}
    dwarn: list = []
    dinfo: list = []
    alt = tp.alt_variant(L)
    alt_label = None if alt is None else tp.variant_label(*alt)
    variants = []                                # [(label, loads, info|None)]
    if dg.get("enabled"):
        if did == BASELINE:
            vlist = tp.sweep_variants(L)[1:]
        else:
            vlist = [alt] if tp.alt_designs(L, plan) else []
        for v in vlist:
            try:
                if plan["reuse"] == "once" and did != BASELINE:
                    a = U.load_npz(c.p("prep", LT_LOADS_ALT))
                    vl = [(str(e), a["F"][k]) for k, e in enumerate(a["entry_ids"].tolist())]
                    vi = None
                else:
                    vl, vi = _plan_loads(c, plan, BASELINE if did == BASELINE else did, dst, v, cache)
                variants.append((tp.variant_label(*v), vl, vi))
            except (EslError, OSError, KeyError) as exc:
                dwarn.append({"stage": tp.variant_label(*v), "err": getattr(exc, "code", type(exc).__name__)})
    if plan["reuse"] == "once" and did != BASELINE and not variants:   # once 의 안 = 베이스라인 하중 그대로 — 진단 문서 없음
        return _ev(c, mesh, sup, loads, region)
    truth: dict = {}
    ident_ids: set = set()
    if did == BASELINE and dg.get("enabled") and plan["truth"] in ("self_direct", "compare"):
        for e in ents:                           # 같은 메시 = 원본 절점력 직접(같은 인수분해)
            key = "topo" if plan["truth"] == "self_direct" else "topo+coords"
            if dst["elem_mask"] is None and ltm.same_mesh(e.raw, mesh, key, c.coord_tol()):
                f, _ = tg.entry_load(tg.Target("S1", mesh, t.frame, []), e.raw)
                truth[e.meta["entry_id"]] = {"kind": "direct_nodal", "f": np.asarray(f, dtype=np.float64)}
                ident_ids.add(e.meta["entry_id"])
    all_loads = list(loads)
    for vname, vl, _vi in variants:
        all_loads += [(f"{eid}{LT_SEP}{vname}", f) for eid, f in vl]
    for eid, tv in truth.items():
        all_loads.append((f"{eid}{LT_SEP}truth", tv["f"]))
    keep = []
    if ident_ids:
        keep = [eid for eid, _ in loads if eid in ident_ids]
        keep += [f"{eid}{LT_SEP}{vname}" for vname, vl, _ in variants for eid, _ in vl if eid in ident_ids]
        keep += [f"{eid}{LT_SEP}truth" for eid in ident_ids]
    r = _ev(c, mesh, sup, all_loads, region, keep, six=did == BASELINE)
    prim_ids = [eid for eid, _ in loads]
    by = {p["entry_id"]: p for p in r["per_esl"]}
    rp = {"per_esl": [by[e] for e in prim_ids], "warnings": [w for w in r["warnings"] if w.get("entry_id") in prim_ids],
          "stats": r["stats"], "u": {e: r["u"][e] for e in prim_ids if e in r.get("u", {})},
          "u6": {e: r["u6"][e] for e in prim_ids if e in (r.get("u6") or {})}}
    try:
        pv = {p["entry_id"]: p for p in info["per_esl"]}
        per = []
        for eid in prim_ids:
            row = {"entry_id": eid, "label": labels.get(eid, str(eid)[:8]),
                   "primary": {**{k: v for k, v in (pv.get(eid) or {}).items() if k != "entry_id"},
                               "C": by[eid]["C"], "umax": by[eid]["umax"]}}
            for vname, vl, vi in variants:
                if vname != alt_label:
                    continue
                q = next((x for x in (vi or {}).get("per_esl") or [] if x["entry_id"] == eid), {})
                rr = by.get(f"{eid}{LT_SEP}{vname}")
                if rr is not None:
                    row["alt"] = {**{k: v for k, v in q.items() if k != "entry_id"}, "variant": vname, "C": rr["C"],
                                  "umax": rr["umax"]}
            per.append(row)
        prow = next((x for x in _lt_prep_doc(c).get("shapes") or [] if x.get("id") == did), {}) or {}
        ddoc = {"id": did, "status": "OK", "variant": info.get("variant"), "fast_path": info.get("fast_path"),
                "transfer": info.get("transfer"), "per_esl": per}
        if prow.get("supports") is not None:
            ddoc["supports"] = {k: v for k, v in prow["supports"].items() if k != "nodes"}
        if prow.get("region") is not None:
            ddoc["region"] = prow["region"]
        if did == BASELINE and dg.get("enabled"):
            if plan["truth"] == "compare":
                truth.update(_lt_truth_compare(c, ents, U.read_json(c.p("prep", "base.json"))["props"], h, L["region"],
                                               set(truth), dwarn))
            elif plan["truth"] == "a_direct":
                truth.update(_lt_truth_raw(c, ents, set(truth), dwarn, dinfo))
            for eid in ident_ids:
                q = by[f"{eid}{LT_SEP}truth"]
                truth[eid].update(C=q["C"], umax=q["umax"], u=r["u"].get(f"{eid}{LT_SEP}truth"))
            vrows = [{"variant": info.get("variant"), "entry_id": eid, "f": f, "C": by[eid]["C"],
                      "umax": by[eid]["umax"], "u": r["u"].get(eid)} for eid, f in loads]
            for vname, vl, _vi in variants:
                for eid, f in vl:
                    q = by[f"{eid}{LT_SEP}{vname}"]
                    vrows.append({"variant": vname, "entry_id": eid, "f": f, "C": q["C"], "umax": q["umax"],
                                  "u": r["u"].get(f"{eid}{LT_SEP}{vname}")})
            rows = ltm.diag_rows(vrows, truth, labels)
            kinds = {v["kind"] for v in truth.values()}
            ddoc["d000"] = {"truth": (next(iter(kinds)) if len(kinds) == 1 else ("mixed" if kinds else None)),
                            "identity": bool(ident_ids) and len(ident_ids) == len(prim_ids), "rows": rows,
                            "n_factorizations": int(r["stats"].get("n_factorizations", 0))}
            del vrows
        ddoc["warnings"] = [_cmp_text("LT_DIAG_SKIPPED", stage=w["stage"], err=w["err"]) for w in dwarn] + dinfo
        U.write_json(c.writer.guard(os.path.join(dd, LT_JSON)), U.jsonable(ddoc))
    except (EslError, KeyError, ValueError, TypeError, FloatingPointError) as exc:   # 진단 실패는 결과를 막지 않음
        code = getattr(exc, "code", type(exc).__name__)
        U.write_json(c.writer.guard(os.path.join(dd, LT_JSON)),
                     {"id": did, "status": "OK", "variant": info.get("variant"),
                      "warnings": [_cmp_text("LT_DIAG_SKIPPED", stage="diag", err=code)]})
    r.clear()
    return rp


# ---------------------------------------------------------------- 결과 모음(모드 무관, LT-13·20)
def _lt_post(c: Ctx, R: dict, results: list[dict]) -> tuple[dict, dict, dict, list]:
    """BD_POST 진단 모음(post/load_transfer_diag.json) · result 요약 · ranking.csv 끝 열 값 · 경고(모든 모드).
    반환 (result.load_transfer, csv 열 {did: [...]}, diag 문서, 경고)."""
    L, plan = _lt(c), _lt_plan(c)
    pdoc = _lt_prep_doc(c)
    prow = {x["id"]: x for x in pdoc.get("shapes") or []}
    warns: list = []
    ddocs = {}
    for r in results:
        p = os.path.join(design_dir(c, r["id"]), LT_JSON)
        if os.path.isfile(p):
            try:
                ddocs[r["id"]] = U.read_json(p)
            except (OSError, ValueError):
                pass
    d0 = ddocs.get(BASELINE) or {}

    def worst_alt(dd):
        v = [float(x["alt"]["C"]) for x in dd.get("per_esl") or [] if x.get("alt") and x["alt"].get("C") is not None]
        return max(v) if v else None
    c0 = worst_alt(d0)
    alt = tp.alt_variant(L)
    once = plan["reuse"] == "once"
    csv_cols: dict = {}
    score_alt: dict = {}
    shapes = []
    base_prim = [x.get("primary") or {} for x in (prow.get(BASELINE) or {}).get("per_esl") or []]
    for r in results:
        did = r["id"]
        dd = ddocs.get(did) or {}
        pr = prow.get(did) or {}
        sa = None
        if alt is not None and r.get("status") == "OK":
            ca = worst_alt(dd)
            sa = None if ca is None or not c0 else ca / c0
        if sa is not None:
            score_alt[did] = sa
        if not once or did == BASELINE:          # once = 베이스라인 1행(모든 안 같은 하중), per_target = 대상마다
            per = dd.get("per_esl") or [{"entry_id": x["entry_id"], "label": x.get("label"), "primary": x.get("primary")}
                                        for x in pr.get("per_esl") or []]
            row = {"id": did, "status": r.get("status"), "transfer": pr.get("transfer") or dd.get("transfer"),
                   "per_esl": per}
            for k in ("supports", "region"):
                if pr.get(k) is not None:
                    row[k] = {kk: v for kk, v in pr[k].items() if kk != "nodes"}
            if sa is not None:
                row["score_alt"] = sa
            shapes.append(row)
        prim = base_prim if once else [x.get("primary") or {} for x in (dd.get("per_esl") or pr.get("per_esl") or [])]
        ff = [float(x["far_frac"]) for x in prim if x.get("far_frac") is not None]
        dm = [float(x["dM_rel_before"]) for x in prim if x.get("dM_rel_before") is not None]
        csv_cols[did] = [dd.get("variant") or pdoc.get("variant") or "", max(ff) if ff else "", max(dm) if dm else "",
                         "" if sa is None else sa]
        for w in dd.get("warnings") or []:
            warns.append(f"{w} — {did}")
    rows = (d0.get("d000") or {}).get("rows") or []
    order = [tp.variant_label(*v) for v in tp.sweep_variants(L)]
    summ = ltm.summary(rows, order)
    rank_same = None
    if alt is not None and score_alt:
        ids = [x["id"] for x in R["ranking"] if x["id"] in score_alt]
        if ids and len(ids) == len(R["ranking"]):
            rank_same = ids == sorted(ids, key=lambda i: (score_alt[i], ids.index(i)))
    ref = d0.get("d000") or {}
    diag = {"schema": ltm.DIAG_SCHEMA, "scenario": c.scn, "method": L["method"], "cell_size_mm": L.get("cell_size_mm"),
            "alt": None if alt is None else {"method": alt[0], "cell_size_mm": alt[1]},
            "plan": pdoc.get("plan") or {"id": plan["id"], "reuse": plan["reuse"]},
            "reference": {"did": BASELINE, "source": (_cmp_doc(c).get("reference_source") if plan["truth"] == "compare" else
                                                      plan["truth"]),
                          "identity": bool(ref.get("identity")), "truth": ref.get("truth")},
            "shapes": shapes, "d000": {"truth": ref.get("truth"), "rows": rows},
            "warnings": [*(pdoc.get("warnings") or []), *warns], "seconds": pdoc.get("seconds")}
    if once and score_alt:
        diag["score_alt"] = score_alt
    out = {**tp.public(L), "plan": plan["id"], "alt": diag["alt"], "truth": ref.get("truth"), "summary": summ,
           "rank_alt_same": rank_same, "warnings_n": len(diag["warnings"])}
    if "support" not in L:                       # ①②③ 결과 요약 키도 같은 모양(지지·영역 = 해당 없음)
        out.update(support=None, region_mode=None)
    return out, csv_cols, diag, warns


def _lt_view3d_ref(c: Ctx, t, results: list[dict], shown: list[str]) -> tuple[dict, dict, list]:
    """LT-9(④ 전용): 표시 형상(상위 k)의 최악 ESL 마다 d000 view3d post/view3d/d000_e<kk>/(인수분해 1회 + keep_u).
    반환 (view3d_ref{entry_id: dir}, view3d_esl{did: entry_id}, 경고)."""
    from esl.view3d import build_view
    by = {r["id"]: r for r in results}
    v_esl = {d: by[d].get("worst_entry_id") for d in [BASELINE] + shown if by.get(d) and by[d].get("worst_entry_id")}
    eids = [e["id"] for e in c.D["entries"]]
    want = sorted({v_esl[d] for d in shown if d in v_esl and v_esl[d] in eids}, key=eids.index)
    if not want:
        return {}, v_esl, []
    try:
        tgt, _reg, loads, _ = _lt_design(c, t, BASELINE)
        sel = [(e, f) for e, f in loads if e in want]
        r = ev.evaluate(tgt.mesh, list(tgt.supports), sel, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"],
                        keep_u=[e for e, _ in sel])
        ref = {}
        for e, f in sel:
            name = f"{BASELINE}_e{eids.index(e):02d}"
            od = c.writer.fresh_dir(c.p("post", "view3d", name), c.out)
            build_view(od, node_id=tgt.mesh["node_id"], x0=tgt.mesh["x0"], conn=tgt.mesh["conn"],
                       elem_type=tgt.mesh["elem_type"], f=f, u_rel=_sm_view_u(c, BASELINE, tgt.mesh, r["u"][e]),
                       supports=[{"node_id": n, "dof": d} for n, d in tgt.supports], key=f"doe/{name}", esl_run_id=str(e))
            ref[e] = name
        return ref, v_esl, []
    except EslError as exc:
        return {}, v_esl, [f"VIEW3D_FAILED: {BASELINE}_e {exc.code}"]


# ---------------------------------------------------------------- v0.20.0 강성 지표 1차 섭동 (esl_stiffness_metric.md)
# 순수 모듈 stiffness_metric(지표·강체 제거) + load_transfer.build_disp(변위 보간 S_t) + 계획 표 열 sm_ref·sm_disp·sm_omega.
SM_REF_NPZ = "sm_ref.npz"
SM_REF_SCHEMA = "esl/doe_sm_ref/1"
SM_SCHEMA = 1
SM_ROW_KEYS = ("C_lin", "C_ritz", "rho", "imbalance_rel", "umax_def")


def _sm(c: Ctx) -> dict | None:
    """스냅샷 doe.rank(새 스터디) → {metric, lin_form, lin_valid, imbalance_warn}. 없으면 None(옛 = solve, 지표 계산 없음)."""
    r = c.D.get("rank")
    if not isinstance(r, dict) or c.scn not in ("same", "mesh", "step", "compare", "select"):
        return None
    base = settings()["rank"]
    out = {k: r.get(k, base[k]) for k in ("metric", "lin_form", "lin_valid", "imbalance_warn")}
    if out["metric"] not in smm.METRICS or out["lin_form"] not in smm.LIN_FORMS:
        raise EslError("CONFIG_INVALID", f"rank.metric {out['metric']} / lin_form {out['lin_form']}")
    return out


def _sm_post(c: Ctx) -> dict | None:
    """BD_POST 순위 지표(결정 A): 스냅샷 rank + metric_effective(계획 열 sm_rank — 다른 메시 = solve)·cross_mesh. 옛 = None."""
    S_ = _sm(c)
    if S_ is None:
        return None
    plan = _lt_plan(c)
    return {**S_, "metric_effective": tp.metric_effective(plan, S_["metric"]), "cross_mesh": tp.cross_mesh(plan)}


def _sm_post_warn(S_: dict | None) -> list:
    """다른 메시 비교 경고 SM_CROSS_MESH(결과 1개) — 같은 메시 계획·옛 스냅샷 = 없음."""
    return [_cmp_text("SM_CROSS_MESH")] if S_ and S_["cross_mesh"] else []


def _solve6(mesh: dict, supports, loads, solver_cfg: dict, *, reaction_warn: float, keep_u=(), keep6=(),
            region=None) -> dict:
    """``evaluate.evaluate`` 와 같은 계산(같은 식·같은 순서 — per_esl·warnings·stats 비트 동일) + keep6 ESL 의 6 dof 해
    (회전 포함, 강성 지표 참조 변위용). evaluate.py 는 변경하지 않는다(회전을 돌려주는 인자가 없어 여기서 같은 흐름)."""
    from esl.mech import supports as msup
    from esl.mech.shell import ShellModel, solver_check_kwargs
    from esl.mech.strain import eps_eq_max_layer
    from esl.opt.target import support_check
    sr = support_check(mesh, supports)
    if sr["rank"] < 6 or sr["sigma_ratio"] < msup.DEGENERATE_RATIO:
        raise EslError("SUPPORT_DEGENERATE", f"3-2-1 지지가 강체 6모드를 구속하지 못함: {list(supports)}")
    t0 = time.monotonic()
    sm_ = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                     drill_factor=float(solver_cfg["drill_factor"]), backend=str(solver_cfg["backend"]),
                     **solver_check_kwargs(solver_cfg))
    h = sm_.factorize(ev.spc_of(mesh, supports))
    per, warns, keep, keep_6 = [], [], {}, {}
    want, want6 = set(keep_u or ()), set(keep6 or ())
    for eid, F in loads:
        F = np.asarray(F, dtype=np.float64)
        u, R = h.solve(F)
        ut = u[:, :3]
        C = float(np.sum(F * ut))
        if region is not None:
            rn = np.zeros(ut.shape[0], bool)
            rc = np.asarray(mesh["conn"], dtype=np.int64)[np.asarray(region, bool)]
            rn[rc[rc >= 0]] = True
            umax = float(np.max(np.linalg.norm(ut[rn], axis=1))) if rn.any() else 0.0
        else:
            umax = float(np.max(np.linalg.norm(ut, axis=1))) if ut.size else 0.0
        eps = eps_eq_max_layer(sm_.strains(u))
        if region is not None:
            eps = eps[np.asarray(region, bool)]
        epsmax = float(np.max(eps)) if eps.size else 0.0
        sabs = float(np.linalg.norm(F, axis=1).sum())
        rr = float(np.linalg.norm(R.sum(axis=0)) / sabs) if sabs > 0 else 0.0
        if rr > float(reaction_warn):
            warns.append({"code": "REACTION_RESIDUAL", "entry_id": eid, "ratio": rr})
        per.append({"entry_id": eid, "C": C, "umax": umax, "epsmax": epsmax, "reaction_rel": rr})
        if eid in want:
            keep[eid] = ut.copy()
        if eid in want6:
            keep_6[eid] = np.array(u[:, :6], dtype=np.float64, copy=True)
    return {"per_esl": per, "warnings": warns, "u": keep, "u6": keep_6,
            "stats": {"n_factorizations": int(sm_.stats.get("n_factorizations", 0)), "n_solves": h.n_solves,
                      "backend": sm_.stats.get("backend"), "seconds": round(time.monotonic() - t0, 3)}}


def _a_direct(c: Ctx, kind: str, rc: dict | None, h: float, warns: list, infos: list) -> dict:
    """참값·참조 변위 a_direct(LT-10/§13.7 = SM-1 같은 인수분해 — c 에 1회 캐시): A 메시(원본 메시 sha 별) 직접 풀이.
    kind = raw(②③ — ESL raw 물성·자기 지지, rank < 6 → A auto + LT_TRUTH_AUTO_SUPPORT) | study(④ — 스터디 물성·A 영역 auto).
    반환 {entry_id: {C, umax, u6, mesh, sha}}."""
    key = ("a_direct", kind)
    cache = getattr(c, "_adirect", {})
    if key in cache:
        return cache[key]
    out: dict = {}
    groups: dict = {}
    for e in _lt_ents(c):
        groups.setdefault(ltm.mesh_sha(e.raw), []).append(e)
    for sha, es in groups.items():
        raw = es[0].raw
        try:
            ne = int(np.asarray(raw["elem_type"]).size)
            if kind == "study":
                am = clt.a_direct_mesh(raw, U.read_json(c.p("prep", "base.json"))["props"])
                reg, _ = clt.region_of(am, np.asarray(raw["x0"]), rc or {"mode": "all", "pad_mm": None, "min_frac": 0.5}, h)
                sup = clt.auto_supports(am, reg)
            else:
                am = {k: np.asarray(raw[k]) for k in ("node_id", "x0", "elem_id", "elem_type", "conn")}
                am["elem_pid"] = np.asarray(raw.get("elem_pid", np.zeros(ne, np.int64)))
                for k in ("thickness", "E", "nu"):
                    am[k] = np.broadcast_to(np.asarray(raw[k], dtype=np.float64), (ne,)).copy()
                reg = None
                sup = [(int(n), str(d)) for n, d in zip(np.asarray(raw.get("support_node_id", [])).tolist(),
                                                        np.asarray(raw.get("support_dof", [])).tolist())]
                if not sup or not clt._support_ok(am, sup):
                    from esl.opt import target as tg
                    sup = tg.auto_supports(am)
                    infos.append(_cmp_text("LT_TRUTH_AUTO_SUPPORT", sha=sha))
            ids = [e.meta["entry_id"] for e in es]
            r = _solve6(am, sup, [(e.meta["entry_id"], np.asarray(e.raw["f"], dtype=np.float64)) for e in es],
                        c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"], keep6=ids, region=reg)
            for e, p in zip(es, r["per_esl"]):
                out[e.meta["entry_id"]] = {"C": p["C"], "umax": p["umax"], "u6": r["u6"][e.meta["entry_id"]],
                                           "mesh": am, "sha": sha, "f": np.asarray(e.raw["f"], dtype=np.float64)}
        except EslError as exc:
            warns.append({"stage": f"a_direct {sha}", "err": exc.code})
    cache[key] = out
    c._adirect = cache
    return out


def _sm_placement(c: Ctx, plan: dict, e, frame: dict) -> dict:
    pl = dict(_lt_placement(c, plan))
    if pl.get("kind") == "frame":
        pl.update(src_frame=e.meta.get("frame"), dst_frame=frame)
    return pl


def _sm_omega(plan: dict, region):
    return region if plan["sm_omega"] != "all" else None


def _sm_eval(c: Ctx, t, did: str, mesh: dict, loads: list, region, h: float, u3: dict, u6: dict) -> tuple[dict, list]:
    """안(베이스라인 포함) 강성 지표(§2): K_t 조립(Ω 요소) · u_t = S u_ref(계획 sm_disp) · metrics · umax_def.
    베이스라인에서 참조 변위(sm_ref: base | a_direct)·C_ref 를 만들어 prep/sm_ref.npz 에 1회 저장(안은 읽기만).
    결정 A(2026-11-13): 계획 sm_ref = none(다른 메시 — 옛 ③·④) 이면 지표 없이 umax_def 만(순위 = 재풀이 C, post 의 sm_rank).
    반환 ({entry_id: per_esl 추가 키}, 경고 문자열)."""
    S, plan, L = _sm(c), _lt_plan(c), _lt(c)
    wcfg = (L or settings()["load_transfer"])["work"]
    om = _sm_omega(plan, region)
    om_nodes = None if om is None else ltm.active_nodes(mesh, om)
    X = np.asarray(mesh["x0"], dtype=np.float64)
    if plan["sm_ref"] == "none":
        return {eid: {"C_lin": None, "C_ritz": None, "rho": None, "imbalance_rel": None,
                      "umax_def": smm.umax_def(X, u3[eid], om_nodes) if eid in u3 else None} for eid, _F in loads}, []
    ents = {e.meta["entry_id"]: e for e in _lt_ents(c)}
    idn = {"key": plan["identity"], "coord_tol_rel": c.coord_tol()}
    disp_b, disp_d = plan["sm_disp"]
    warns: list = []
    path = c.p("prep", SM_REF_NPZ)
    if did == BASELINE:
        ref = {}
        dw, di = [], []
        ad = None
        for eid, F in loads:
            kind = plan["sm_ref"]
            if kind == "base_or_a_direct":
                kind = "base" if om is None and ltm.same_mesh(ents[eid].raw, mesh, "topo+coords", c.coord_tol()) \
                    else "a_direct"
            if kind == "base":
                u_ref = smm.remove_rigid(X, u6[eid])
                ref[eid] = {"kind": "base", "u_ref": u_ref, "K_A": None, "F_A": np.asarray(F, dtype=np.float64)}
            else:
                if ad is None:
                    ad = _a_direct(c, "study" if plan["truth"] == "compare" else "raw",
                                   (L or {}).get("region"), h, dw, di)
                a = ad.get(eid)
                if a is None:
                    raise EslError("SM_SKIPPED", f"a_direct 풀이 없음 {eid}")
                ref[eid] = {"kind": "a_direct", "u_ref": smm.remove_rigid(a["mesh"]["x0"], a["u6"]),
                            "mesh": a["mesh"], "F_A": a["f"]}
        K_t = smm.stiffness(mesh, c.solver_cfg(), elem_mask=om)
        Ks: dict = {}
        out, u_base, C_ref = {}, [], {}
        S_cache: dict = {}
        for eid, F in loads:
            rf = ref[eid]
            if rf["kind"] == "base":              # 같은 K_t(같은 Ω) → 베이스라인 ρ = 1 정확(결정 A)
                K_A = K_t
                ut6, sinfo = rf["u_ref"], {"kind": "I", "far_frac": 0.0}
            else:
                am = rf["mesh"]
                sha = ltm.mesh_sha(am)
                if sha not in Ks:
                    Ks[sha] = smm.stiffness(am, c.solver_cfg())
                K_A = Ks[sha]
                pl = _sm_placement(c, plan, ents[eid], t.frame)
                skey = (sha, json.dumps(U.jsonable({k: v for k, v in pl.items() if k in ("kind", "R", "t")}),
                                        sort_keys=True))
                if skey not in S_cache:
                    S_cache[skey] = ltm.build_disp(am, mesh, pl, wcfg, h, idn)
                Sm, sinfo = S_cache[skey]
                ut6 = smm.apply_disp(Sm, rf["u_ref"], sinfo.get("R"))
            C_ref[eid] = smm.reference(K_A, rf["u_ref"], rf["F_A"])["C_ref"]
            out[eid] = _sm_row(c, S, K_t, ut6, F, C_ref[eid], eid, X, u3, om_nodes, sinfo, warns)
            u_base.append(ut6)
        doc = {"schema": np.asarray(SM_REF_SCHEMA), "entry_ids": np.asarray([e for e, _ in loads]),
               "C_ref": np.asarray([C_ref[e] for e, _ in loads], dtype=np.float64),
               "ref_kind": np.asarray([ref[e]["kind"] for e, _ in loads])}
        if disp_d == "I":                         # once: 베이스라인 u_t 1회 → 모든 안 같은 노드
            doc.update(node_id=np.asarray(mesh["node_id"], dtype=np.int64), u=np.stack(u_base))
        else:                                     # per_target: 원본 공간 u_ref(강체 제거) — 안마다 S_t
            for k, (eid, _F) in enumerate(loads):
                doc[f"u_a_{k}"] = ref[eid]["u_ref"]
        mg.save_npz_det(c.writer.guard(path), doc)
        warns += [_cmp_text("LT_DIAG_SKIPPED", stage=w["stage"], err=w["err"]) for w in dw] + di
        return out, warns
    z = U.load_npz(path)
    eids = [str(e) for e in z["entry_ids"].tolist()]
    K_t = smm.stiffness(mesh, c.solver_cfg(), elem_mask=om)
    out = {}
    S_cache = {}
    for eid, F in loads:
        k = eids.index(eid)
        if disp_d == "I":
            nb = np.asarray(z["node_id"], dtype=np.int64)
            nm = np.asarray(mesh["node_id"], dtype=np.int64)
            ut6 = z["u"][k] if np.array_equal(nb, nm) else z["u"][k][np.searchsorted(nb, nm, sorter=np.argsort(nb))
                                                                   .clip(0, nb.size - 1)]
            sinfo = {"kind": "I", "far_frac": 0.0}
        else:
            e = ents[eid]
            am = e.raw
            pl = _sm_placement(c, plan, e, t.frame)
            skey = (ltm.mesh_sha(am), json.dumps(U.jsonable({kk: v for kk, v in pl.items() if kk in ("kind", "R", "t")}),
                                                 sort_keys=True))
            if skey not in S_cache:
                S_cache[skey] = ltm.build_disp(am, mesh, pl, wcfg, h, idn)
            Sm, sinfo = S_cache[skey]
            ut6 = smm.apply_disp(Sm, z[f"u_a_{k}"], sinfo.get("R"))
        out[eid] = _sm_row(c, S, K_t, ut6, F, float(z["C_ref"][k]), eid, X, u3, om_nodes, sinfo, warns)
    return out, warns


def _sm_row(c: Ctx, S: dict, K_t, ut6, F, C_ref: float, eid, X, u3: dict, om_nodes, sinfo: dict, warns: list) -> dict:
    m = smm.metrics(K_t, ut6, F, C_ref, lin_valid=float(S["lin_valid"]), imbalance_warn=float(S["imbalance_warn"]),
                    node_mask=om_nodes, entry_id=eid)
    for w in m["warnings"]:
        kw = {k: (f"{v:.3g}" if isinstance(v, float) else v) for k, v in w.items() if k != "code"}
        warns.append(_cmp_text(w["code"], lin_valid=S["lin_valid"], imbalance_warn=S["imbalance_warn"], **kw))
    row = {"C_lin": m["C_lin"], "C_ritz": m["C_ritz"], "rho": m["rho"], "imbalance_rel": m["imbalance_rel"],
           "umax_def": smm.umax_def(X, u3[eid], om_nodes) if eid in u3 else None, "C_ref": C_ref}
    if sinfo.get("kind") == "interp":
        row["sm_far_frac"] = sinfo.get("far_frac")
    return row


def _sm_view_u(c: Ctx, did: str, mesh: dict, u3):
    """3D 색·변형(SM-3): 강도 지표 스냅샷 = 강체 제거 u_def(Ω = 계획 sm_omega 영역 노드), 옛 = 해석값 그대로."""
    if _sm(c) is None:
        return u3
    plan = _lt_plan(c)
    reg = None
    if plan["sm_omega"] == "compare_region":
        reg = _lt_load_region(c, did)
    elif plan["sm_omega"] == "step_region":
        from esl.doe import step_graph as sg
        reg = sg.load_region(c.p("prep"))
    om = None if reg is None else ltm.active_nodes(mesh, reg)
    try:
        return smm.remove_rigid(np.asarray(mesh["x0"], dtype=np.float64), np.asarray(u3, dtype=np.float64), om)[:, :3]
    except EslError:
        return u3


def _sm_apply(c: Ctx, t, did: str, mesh: dict, loads: list, region, h: float, r: dict) -> list:
    """bd_eval 훅: per_esl 행에 SM 키(C_lin·C_ritz·rho·imbalance_rel·umax_def …)를 넣고 경고 문자열을 돌려줌. 실패 = 키 None +
    SM_SKIPPED(그 안은 lin 순위 밖 — rank)."""
    try:
        rows, warns = _sm_eval(c, t, did, mesh, loads, region, h, r.get("u") or {}, r.get("u6") or {})
    except (EslError, KeyError, ValueError, OSError) as exc:
        rows, warns = {}, [_cmp_text("SM_SKIPPED", stage="eval", err=getattr(exc, "code", type(exc).__name__))]
    for p in r["per_esl"]:
        add = rows.get(p["entry_id"]) or {k: None for k in SM_ROW_KEYS}
        p.update({k: v for k, v in add.items() if k != "C_ref"})
    c._sm_cref = {e: v.get("C_ref") for e, v in rows.items()}
    return warns


def _cmp_ranking_csv(rank: dict, results: list[dict], shapes: dict, entry_ids: list[str], lt_cols: dict | None = None,
                     sm_key: str | None = None) -> str:
    """④ ranking.csv: 변수 열 대신 name·file_name. v0.16.0 끝 열(§7·C2-D-22) = source·mesh_method·hausdorff_mm·refine_h_mm·
    elem_ratio_ref(기존 열 위치 불변). v0.20.0 LT-13 lt_cols(새 스냅샷만) = 끝 열 lt_method·lt_far_frac·lt_dM_rel·score_alt."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    mid_h = (SM_CSV_MID + [f"C_{e}" for e in entry_ids] + [f"C_solve_{e}" for e in entry_ids]) if sm_key else \
        (["score", "improvement", "worst", "umax", "epsmax"] + [f"C_{e}" for e in entry_ids])
    w.writerow(["id", "rank", "status", "name", "file_name"] + mid_h + PER_ESL_COLS + [f"ratio_{e}" for e in entry_ids]
               + MESH_CSV_COLS + (LT_CSV_COLS if lt_cols is not None else []))
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
        row = (row[:5] + _sm_csv(rank, r, x, entry_ids, sm_key)) if sm_key else (row + [C.get(e, "") for e in entry_ids])
        w.writerow(row + extra + _mesh_csv(sh)
                   + ((lt_cols.get(r["id"]) or [""] * len(LT_CSV_COLS)) if lt_cols is not None else []))
    return buf.getvalue()


MESH_CSV_COLS = ["source", "mesh_method", "hausdorff_mm", "refine_h_mm", "elem_ratio_ref"]


def _mesh_csv(sh: dict) -> list:
    fd = sh.get("fidelity") or {}
    rf = sh.get("refine") or {}
    v = [sh.get("source"), sh.get("mesh_method"), fd.get("hausdorff_mm"), rf.get("h_mm") if rf else None,
         rf.get("elem_ratio_ref") if rf else None]
    return ["" if x is None else x for x in v]


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


MESH_HEAD_CODES = ("COMPARE_MESH_METHOD_MIXED", "REMESH_USED", "REMESH_FIDELITY_WARN", "MESH_INPUT_SIZE_DIFF",
                   "MESH_INPUT_DISCONNECTED", "MESH_REFINED")


def _refine_hr(c: Ctx, row: dict) -> float:
    """수렴 점검 h_r(C2-D-24): 전역 = 세분화 h, 국부 = 그 형상의 평균 요소 크기 √(ΣA/n)(같은 면에 같은 Field 를 줄 수
    없으므로 전역 대표값). 하한 refine.min_size_mm, 1e-3 mm 반올림(캐시 키)."""
    from esl.doe import mesh_refine as mr
    rf = row.get("refine") or {}
    if rf.get("kind") != "local":
        h = float(rf["h_mm"])
    else:
        m = mg.load_mesh(_cmp_mesh_dir(c, row["id"]))
        conn = np.asarray(m["conn"])
        A = mg._elem_area(np.asarray(m["x0"]), np.where(conn >= 0, conn, conn[:, :1]), np.asarray(m["elem_type"]))
        h = float(np.sqrt(float(np.sum(A)) / max(int(A.size), 1)))
    return round(max(h, float(mr._rcfg(c.cfg)["min_size_mm"])), 3)


def _cmp_refine_bias(c: Ctx, t, doc: dict, results: list[dict], tol_rank: float, echo) -> tuple[dict, list, list]:
    """C2-D-24 수렴 점검: 세분화 형상이 쓴 h_r 마다 기준 d000 STEP 을 h_r 로 다시 메시·해석(같은 frame·하중 규칙, 캐시
    run/designs/d000_h<h>/ — done.json 해시 같으면 재사용) → δ_e = C_ref(h_r)/C_ref(h) − 1. 반환 ({id: refine_bias}, 경고, info)."""
    from esl.doe import mesh_refine as mr
    rc = mr._rcfg(c.cfg)
    conv = rc.get("convergence") or {}
    by_res = {r["id"]: r for r in results}
    refined = [s for s in doc["shapes"] if s.get("mesh_method") == "refine" and s.get("refine")
               and (by_res.get(s["id"]) or {}).get("status") == "OK" and s["id"] != BASELINE]
    if not conv.get("enabled", True) or not refined:
        return {}, [], []
    ref = next(s for s in doc["shapes"] if s["id"] == BASELINE)
    if doc.get("reference_source") == "case" or ref.get("source") != "step":
        echo("[bd_post] 수렴 점검 생략 — 기준이 Case 메시 또는 메시 입력")
        return {}, [], [_cmp_text("REFINE_CONVERGENCE_SKIPPED")]
    tol = float(conv["tol"]) if conv.get("tol") is not None else float(tol_rank)
    base = by_res[BASELINE]
    C_h = {p["entry_id"]: float(p["C"]) for p in base.get("per_esl") or []}
    row0 = _cmp_by(c).get(BASELINE) or {}
    src = c.p(row0["rel"])
    bmeta = U.read_json(c.p("prep", "base.json"))
    props = bmeta["props"]
    ccfg = sc.compare_cfg(c.cfg)
    hr_of = {s["id"]: _refine_hr(c, s) for s in refined}
    from esl.doe import mesh_remesh
    tools = mesh_remesh.build_versions()
    C_hr: dict[float, dict | None] = {}
    errs: dict[float, str] = {}
    for hr in sorted(set(hr_of.values()), reverse=True):
        dd = design_dir(c, f"{BASELINE}_h{hr:g}")
        c.writer.makedirs(dd)
        sha = ev.config_hash({"step": row0.get("sha256"), "h_r": hr, "cfg": _cfg_hash(c), "props": props,
                              "profile": bmeta.get("profile"), "frame": ev.config_hash(bmeta["frame"]),
                              "refine": ev.config_hash({k: v for k, v in rc.items() if k != "convergence"}),
                              "entries": [e["id"] for e in c.D["entries"]],
                              "tools": tools,      # 판정(tol·same_h)은 캐시 키 아님, gmsh·occ 버전은 키(메시가 바뀜)
                              **({"load_transfer": ev.config_hash(tp.hash_view(_lt(c)))} if _lt(c) else {})})
        prev = ev.reusable(dd, sha)
        if prev is not None and prev.get("status") == "OK":
            C_hr[hr] = {p["entry_id"]: float(p["C"]) for p in U.read_json(os.path.join(dd, ev.RESULT_JSON))["per_esl"]}
            echo(f"[bd_post] 수렴 점검 d000 h {hr:g} mm — 이전 결과 재사용")
            continue
        try:
            a = {"stage": "refine_global", "max_elems": int(rc["max_elems"])}
            mesh, meta = mg.run_isolated(src, os.path.join(dd, "mesh"), hr, mr.attempt_cfg(ccfg, a), props,
                                         opt_cfg=c.ocfg, max_elems=int(rc["max_elems"]))
            if _lt(c) is not None:              # v0.20.0 LT-1 같은 규칙(영역·지지 이전·하중 전달)
                dt, reg_r, loads = _lt_mesh_loads(c, t, mesh)
                rkw_r = {"region": reg_r} if reg_r is not None else {}
            else:
                dt = sc.compare_target(mesh, t.frame)
                loads, _ = sc.entry_loads(dt, c.entries(raw=False), c.mapping_opts())
                rkw_r = {}
            r = ev.evaluate(dt.mesh, list(dt.supports), loads, c.solver_cfg(), reaction_warn=c.cfg["solve"]["reaction_warn"],
                            **rkw_r)
            rd = ev.result_doc(f"{BASELINE}_h{hr:g}", "OK", {}, mesh={"n_nodes": dt.n_nodes, "n_elems": dt.n_elems, "h": hr},
                               solve=r["stats"], per_esl=r["per_esl"], warnings=r["warnings"])
            U.write_json(c.writer.guard(os.path.join(dd, ev.RESULT_JSON)), rd)
            ev.write_done(dd, sha, "OK", c.writer)
            C_hr[hr] = {p["entry_id"]: float(p["C"]) for p in r["per_esl"]}
            echo(f"[bd_post] 수렴 점검 d000 h {hr:g} mm · 요소 {dt.n_elems} · solve {r['stats']['seconds']:.1f} s")
        except EslError as exc:
            if exc.code == "GMSH_UNAVAILABLE":
                raise
            C_hr[hr] = None
            errs[hr] = f"{exc.code}: {exc.message}"
            echo(f"[bd_post] 수렴 점검 d000 h {hr:g} mm 실패 {exc.code}: {exc.message}")
    out, warns, infos = {}, [], []
    same_h = bool(conv.get("same_h_baseline", False))
    for s in refined:
        hr = hr_of[s["id"]]
        cr = C_hr.get(hr)
        if cr is None:
            out[s["id"]] = {"h_mm": hr, "delta_max": None, "tol": tol, "over_tol": False, "per_esl": [],
                            "error": errs.get(hr)}
            infos.append(f"REFINE_CONVERGENCE_SKIPPED: {s['id']} {s['name']} 기준 d000 h {hr:g} mm 해석 실패 — {errs.get(hr)}")
            continue
        per = [{"entry_id": e, "delta": cr[e] / C_h[e] - 1.0, "C_h": C_h[e], "C_hr": cr[e]}
               for e in C_h if C_h[e] > 0 and e in cr]
        dmax = max((abs(p["delta"]) for p in per), default=0.0)
        b = {"h_mm": hr, "delta_max": dmax, "tol": tol, "over_tol": bool(dmax > tol), "per_esl": per,
             "same_h_baseline": same_h}
        if same_h:
            mine = {p["entry_id"]: float(p["C"]) for p in by_res[s["id"]].get("per_esl") or []}
            for p in per:
                if p["entry_id"] in mine and p["C_hr"] > 0:
                    p["ratio_same_h"] = mine[p["entry_id"]] / p["C_hr"]
            if mine and cr:
                sc_h = max(mine.values()) / max(cr[e] for e in mine if e in cr)
                b.update(score_same_h=sc_h, improvement_same_h=1.0 - sc_h)
        out[s["id"]] = b
        if b["over_tol"]:
            warns.append(_cmp_text("MESH_REFINE_BIAS", name=f"{s['id']} {s['name']}", h=f"{hr:g}",
                                   delta=f"{dmax * 100:.2f} %", tol=f"{tol * 100:g} %"))
    return out, warns, infos


def _shape_ext(s: dict, bias: dict | None = None) -> dict:
    """v0.16.0 결과 shape 보강(§3): source·mesh_method(+ part_id, fidelity, refine, refine_bias 있을 때만)."""
    out = {"source": s.get("source") or "step", "mesh_method": s.get("mesh_method")}
    if s.get("source") == "mesh":
        out["part_id"] = s.get("part_id")
    for k in ("fidelity", "refine", "diag"):
        if s.get(k):
            out[k] = s[k]
    if s.get("mesh_method") == "defeature" and s.get("defeature"):   # v0.16.1 §5A.5(cad 형상의 holes 기록은 넣지 않음 — 바이트 불변)
        out["defeature"] = s["defeature"]
    if bias:
        out["refine_bias"] = bias
    return out


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
    S_ = _sm_post(c)
    R = rk.rank(results, noise_floor=None, tol=float(c.cfg["rank"]["ratio_tol"]), extra_failed={"FAILED_SIZE": "size"},
                **({"metric": S_["metric_effective"], "lin_form": S_["lin_form"],
                    "lin_valid": float(S_["lin_valid"])} if S_ else {}))
    rk.attach_shapes(R, shapes)
    bias, bias_w, bias_i = _cmp_refine_bias(c, t, doc, results, float(R["ratio_tol"]), echo)     # v0.16.0 C2-D-24
    for x in R["ranking"]:
        x["shape"].update(_shape_ext(shapes.get(x["id"]) or {}, bias.get(x["id"])))
        b = bias.get(x["id"]) or {}
        if b.get("improvement_same_h") is not None:            # same_h_baseline: 원래 개선율과 함께 표시
            x["improvement_same_h"] = b["improvement_same_h"]
    R["baseline"]["shape"].update(_shape_ext(shapes.get(BASELINE) or {}))
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
    L = _lt(c)
    lt_res = lt_cols = lt_diag = None
    lt_w: list = []
    if L is not None:                            # v0.20.0 LT-10·13 진단 모음·요약·CSV 끝 열
        try:
            lt_res, lt_cols, lt_diag, lt_w = _lt_post(c, R, results)
        except (EslError, OSError, ValueError, KeyError) as exc:
            lt_w = [_cmp_text("LT_DIAG_SKIPPED", stage="post", err=getattr(exc, "code", type(exc).__name__))]
            lt_res, lt_cols = {**tp.public(L), "summary": [], "warnings_n": 1}, {}
    with open(c.writer.guard(c.p("post", "ranking.csv")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_cmp_ranking_csv(R, results, shapes, eids, lt_cols,
                                  smm.metric_key(S_["metric_effective"], S_["lin_form"]) if S_ else None))

    def shp(did):
        s = shapes.get(did) or {}
        return {"name": s.get("name"), "file_name": s.get("file_name"), "reference": bool(s.get("reference")),
                **_shape_ext(s, bias.get(did))}
    c.write_json(os.path.join("post", "designs.json"), {"designs": [{"id": r["id"], "status": r["status"],
                                                                    "code": r.get("code"), "score": r.get("score"),
                                                                    "shape": shp(r["id"])} for r in results]})
    warns = [w["code"] for w in R["warnings"]]
    inp = U.read_json(c.p("prep", "input.json"))
    if doc["reference_source"] == "case":
        warns.append(f"COMPARE_REF_CASE_MESH: {REF_CASE_MSG}")
    warns += [w for w in doc.get("warnings") or [] if str(w).split(":", 1)[0] in MESH_HEAD_CODES] + bias_w + lt_w \
        + _sm_post_warn(S_)
    k = int(c.cfg["view3d"]["top_k"])
    top = [x["id"] for x in R["ranking"][:k]]
    v3 = []
    for did in [BASELINE] + top:
        res = next(r for r in results if r["id"] == did)
        try:
            v3.append(_view3d(c, t, bmeta, did, inp, res))
        except EslError as exc:
            warns.append(f"VIEW3D_FAILED: {did} {exc.code}")
    v3_ref = v3_esl = None
    if L is not None:                            # LT-9 3D 비교 같은 ESL(result.view3d 목록 불변)
        v3_ref, v3_esl, vw = _lt_view3d_ref(c, t, results, top)
        warns += vw
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
           "defeature_lists": _defeat_lists(c, doc["shapes"]),
           "esl": esl, "limits_extra": list(LIMIT_MSG) + _mesh_limits(doc["shapes"]), "warnings": warns,
           "refine_bias": bias, "mesh_mode": doc.get("mesh_mode"),
           "best": None if best_id is None else {"id": best_id, "files": best_files.get(best_id, [])}}
    if S_ is not None:                           # v0.20.0 SM-7 보고서 강성 지표 절, §6 최상위 metric·lin_form
        ctx["stiffness"] = dict(S_)
        out.update(metric=R.get("metric"), lin_form=R.get("lin_form"), C_ref_solve=R.get("C_ref_solve"),
                   metric_effective=S_["metric_effective"], cross_mesh=S_["cross_mesh"],
                   **({"n_fallback": R["n_fallback"]} if "n_fallback" in R else {}))
    if L is not None:
        out.update(load_transfer=lt_res, view3d_ref=v3_ref or {}, view3d_esl=v3_esl or {})
        ctx["load_transfer"] = {"result": lt_res, "diag": lt_diag}
        ctx["limits_extra"] = ctx["limits_extra"] + [LT_LIMIT_MSG]
        if lt_diag is not None:
            c.write_json(os.path.join("post", LT_DIAG_JSON), U.jsonable(lt_diag))
    from esl.doe import report_doe
    report_doe.write(c.writer.guard(c.p("report.html")), ctx)
    out["cleanup_bytes"] = 0
    if bias:
        out["refine_bias"] = bias
    c.write_json(os.path.join("post", "result.json"), out)
    echo(f"[bd_post] ④ 성공 {R['n_ok']} · 최적 {best_id or '-'}"
         + (f" ({_cmp_name(c, best_id)}) score {R['ranking'][0]['score']:.4f}" if best_id else ""))
    c.progress(100)
    ret = {"files": ["post/result.json", "post/ranking.csv", "post/designs.json", "post/per_esl.json", "report.html"]
           + ([f"post/{LT_DIAG_JSON}"] if L is not None and lt_diag is not None else []),
           "warnings": warns, "result": out}
    if bias_i:
        ret["info"] = bias_i
    return ret


MESH_LIMIT_MSG = {
    "refine": "세분화 형상은 요소 크기가 기준 메시와 달라 메시 의존 오차를 포함합니다 — 수렴 점검 δ 참고",
    "remesh": "재메시는 CAD 면 구조를 버린 근사입니다(단순화 후 CAD 대비 편차 표시) — 구멍 둘레 분할 미적용, 필렛이 접선으로 "
              "이어진 비드는 면 분류에 실패할 수 있음(REMESH_CLASSIFY_FAILED)",
    "mesh_input": "메시 입력은 그대로 사용합니다 — 크기·품질은 사용자 메시 책임",
    "defeature": "형상 단순화 형상은 작은 형상(구멍·낮은 딤플·버링·작은 필렛)을 억제한 메시라 강성에 억제 영향이 섞입니다 — "
                 "억제 목록·억제 영역 편차(작은 형상 억제 절) 참고"}


def _mesh_limits(rows: list[dict]) -> list[str]:
    """§9 한계 절 추가(쓰인 방식만 — 정상 STEP 만이면 없음)."""
    ms = {r.get("mesh_method") for r in rows if r.get("status") in ("READY", "OK") or r.get("mesh_method")}
    ms |= {"remesh"} if "fallback" in ms else set()
    ms.discard("mesh_input") if not any(r.get("source") == "mesh" for r in rows) else None
    return [MESH_LIMIT_MSG[k] for k in ("refine", "remesh", "mesh_input", "defeature") if k in ms]


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


def _sel_norm(c: Ctx, mesh: dict | None = None) -> tuple[dict, str]:
    from esl.doe import bead_select as bsel
    s = c.D.get("selection") or {}
    if not isinstance(s, dict) or not s.get("input"):
        raise EslError("SELECTION_MISSING", "비드 선택이 저장되지 않음")
    if isinstance(s["input"], dict) and s["input"].get("schema_version") == 2:   # v0.17.0 schema 2(그래프)
        from esl.doe import bead_graph as bgr
        if select_schema(c) != 2:
            raise EslError("SELECT_SCHEMA_MISMATCH", "schema 1 스터디에 schema 2 선택")
        graph, labels = _graph_or_none(c)                # GRAPH_FAILED: elems beads only
        norm, sha = bgr.normalize_v2(s["input"], graph, c.cfg, labels=labels, mesh=mesh)
        if mesh is not None:
            bsel.check_elems(mesh, {"fixed_user": norm["fixed_user"], "exclude": norm["exclude"],
                                    "beads": [b for b in norm["beads"] if b["src"] == "elems"]})
        if s.get("sha256") and s["sha256"] != sha:
            raise EslError("PREVIEW_STALE", f"선택 sha256 불일치(저장 {str(s['sha256'])[:12]}… ≠ 계산 {sha[:12]}…)")
        return norm, sha
    norm, sha = bsel.normalize(s["input"], c.cfg)
    if s.get("sha256") and s["sha256"] != sha:
        raise EslError("PREVIEW_STALE", f"선택 sha256 불일치(저장 {str(s['sha256'])[:12]}… ≠ 계산 {sha[:12]}…)")
    return norm, sha


def _sel_fixed_ids(c: Ctx) -> tuple[np.ndarray, str | None]:
    """paicad fixed-scan(prep/fixed — 워커 BD_GEOM, 있으면) 노드 ID. 없음/실패 → (빈, 경고 코드).
    v0.18.0 select_base step: B fixed-scan 없음 → (빈, None) — 고정은 A 이전 seed fixed_user(SG-D-14)."""
    if _is_step_base(c):
        return np.zeros(0, np.int64), None
    d = c.p("prep", "fixed")
    if not os.path.isfile(os.path.join(d, pio.SCAN_JSON)):
        return np.zeros(0, np.int64), "FIXED_INFO_MISSING"
    try:
        fx = pio.read_fixed(d, c.max_mb)
    except EslError:
        return np.zeros(0, np.int64), "FIXED_INFO_MISSING"
    return np.asarray(fx["node_id"], dtype=np.int64), None


def _sel_step(c: Ctx, inp: dict) -> None:
    """v0.16.2 auto(AD-D-2·14): STEP 이 주어지면 input/step 사본·sha(paicad extract 입력, 워커가 ``select_prep_info`` 로 읽음)
    + input.json ``bead_source: auto``. manual(STEP 없음)은 v0.16.1 input.json 그대로(키 추가 없음 — AD-D-22)."""
    st = c.D.get("step") or None
    if bead_source(c) == "auto":
        inp["bead_source"] = "auto"
    if isinstance(st, dict) and st.get("path"):
        rel = os.path.join("input", "step", os.path.basename(st.get("file_name") or st["path"]))
        sha = _copy_verified(st["path"], c.p(rel), c.writer, st.get("sha256"))
        inp["step"] = {"rel": rel.replace(os.sep, "/"), "sha256": sha}


def _sel_input(c: Ctx, echo) -> dict:
    """BD_INPUT select: ① 과 같은 기준 Case 제자리 읽기·동일성 | v0.16.2 select_base mesh = ② B 메시(``_mesh_base`` — AD-D-15)."""
    D = c.D
    inp = {"schema": "esl/doe_input/1", "scenario": "select", "step": None, "entries": [e["id"] for e in D["entries"]]}
    ents = c.entries(raw=True)
    c.progress(10)
    _sel_step(c, inp)
    if select_schema(c) == 2:                    # v0.17.0: schema 1 스터디는 키 없음(input.json 바이트 불변)
        inp["select_schema"] = 2
    if select_base(c) == "step":                 # v0.18.0 SG-D-1~3: STEP 사본(_sel_step)·물성 — 메시는 BD_MESH0
        return _sel_input_step(c, ents, inp, echo)
    if select_base(c) == "mesh":
        warns: list = []
        inp["select_base"] = "mesh"
        echo(f"[bd_input] select 기준 B 메시 사본 읽기 (파트 {D['mesh'].get('part_title') or c.cfg['part_title']})")
        meta = _mesh_base(c, ents, inp, warns, "select")
        c.progress(90)
        inp.update(warnings=warns, info=[])
        c.write_json(os.path.join("prep", "input.json"), inp)
        echo(f"[bd_input] 기준 메시 노드 {meta['n_nodes']} · 요소 {meta['n_elems']} · topo {str(meta['topo_sha256'])[:12]}…"
             " (B 메시 — 하중 셀 매핑, 지지 자동 3-2-1)")
        for w in warns:
            echo(f"  경고: {w}")
        c.progress(100)
        return {"files": ["prep/input.json", "prep/base_mesh.npz", "prep/base.json"], "warnings": warns, "info": [],
                "part_id": inp["part_id"]}
    b = D["base"]
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


def _sel_input_step(c: Ctx, ents, inp: dict, echo) -> dict:
    """BD_INPUT select_base step(SG-D-2·3): schema 2 고정, STEP 사본·sha(``_sel_step``), props(없으면 A Case 기본)·inch."""
    if select_schema(c) != 2:
        raise EslError("INVALID_PARAMS", "select_base step 은 select_schema 2 만(SG-D-2)")
    if not inp.get("step"):
        raise EslError("INPUT_INVALID", "③ STEP 입력(step)이 없음")
    props = c.D.get("props") or sc.props_default(ents[0].raw)
    props = {"t": float(props["t"]), "E": float(props["E"]), "nu": float(props["nu"])}
    inp.update(select_base="step", assem=None, part_id=None, part_title=None, props=props, inch=c.D.get("inch"),
               warnings=[], info=[])
    c.write_json(os.path.join("prep", "input.json"), inp)
    echo(f"[bd_input] select 기준 B STEP 사본 {inp['step']['rel']} · sha {inp['step']['sha256'][:12]}… · 물성 t {props['t']:g}"
         " — 기준 메시는 BD_MESH0(④ 사다리)")
    c.progress(100)
    return {"files": ["prep/input.json", inp["step"]["rel"]], "warnings": [], "info": [], "part_id": None}


def _sel_loads(c: Ctx, echo) -> dict:
    """BD_LOADS select: ① 하중(노드 직접)·지지 + 선택 보기 자료 prep/select/(part.glb·select.bin·manifest)."""
    from esl.doe import bead_select as bsel
    from esl import view3d as v3
    c.progress(0)
    t, bmeta = sc.load_base(c.p("prep"))
    ents = c.entries(raw=True)
    warns, info = [], []
    step = _is_step_base(c)
    region = None
    pre_sd = pre_xfer = None
    if step:
        from esl.doe import step_graph as sg
        region = sg.load_region(c.p("prep"))
    if _lt(c) is not None:                       # v0.20.0 하중 전달 계획(①②③ select — 베이스라인 1회, 공용 실행기)
        fc = None
        if step:                                 # ③ 배치 = fixed_transfer 의 frame 판정 재사용(추가 판정 0)
            pre_sd = c.fresh(os.path.join("prep", "select"))
            pre_xfer = _sel_fixed_transfer(c, t, bmeta, ents, region, pre_sd)
            fc = (pre_xfer[0] or {}).get("frame_check")
        loads, linfo = _lt_base_loads(c, t, bmeta, ents, region, fc)
    elif step:                                   # v0.18.0 SG-D-8·20b 하중 셀 매핑 1회, 대상 = 평가 영역 노드
        loads, linfo = sg.region_loads(t, ents, region, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"],
                                       (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]))
    else:
        loads, linfo = sc.entry_loads(t, ents, c.mapping_opts(), c.ocfg["check"]["min_nodes_per_cell"],
                                      (c.ocfg["grid"]["nx"], c.ocfg["grid"]["ny"]))
    warns += linfo["warnings"]
    loads_sha = sc.save_loads(c.p("prep"), t.mesh["node_id"], loads, c.writer)
    c.progress(50)
    params = {"beads": [], "params": [], "warnings": []}            # 변수 = 선택 저장 후(select/<sha>/params.json)
    c.write_json(os.path.join("prep", "params.json"), params)
    res = None
    if _is_mesh_base(c) or step:                 # v0.16.2 AD-D-18: ② B 메시 기준 = ② 경계 경고 그대로(BD-D-14), ③ 도
        res = _boundary(c, t, ents, info, region=region)
        warns += [f"{w['code']}: {w.get('label') or w.get('entry_id')} {w.get('d_mm')}" for w in res["warnings"]]
        c.write_json(os.path.join("prep", "boundary.json"), res)
    plan = bnd.plan(t.mesh, t.frame, c.ocfg["keepout"], int(c.ocfg["ui"]["max_preview_points"]), result=res)
    c.write_json(os.path.join("prep", "plan.json"), plan)
    fids, fw = _sel_fixed_ids(c)
    if fw:
        warns.append(fw)
    m = t.mesh
    nid = np.asarray(m["node_id"], dtype=np.int64)
    fixed = np.isin(nid, fids)
    sd = pre_sd if pre_sd is not None else c.fresh(os.path.join("prep", "select"))
    xfer, xinfo, gfids = None, [], fids
    if step:                                     # v0.18.0 SG-D-12~15 A 고정점 → B (seed fixed_user, 분류 fixed)
        xfer, xinfo = pre_xfer if pre_xfer is not None else _sel_fixed_transfer(c, t, bmeta, ents, region, sd)
        gfids = np.asarray((xfer or {}).get("node_id") or [], dtype=np.int64)
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
           "fixed": ({"scan_n": 0, "source": _xfer_source(xfer), "xfer_n": len((xfer or {}).get("node_id") or []),
                      "xfer_method": (xfer or {}).get("method") or "none"} if step else
                     {"scan_n": int(fixed.sum()), "source": "none" if fw else "scan"}),
           "glb": {"name": "part.glb", "bytes": int(gbytes)}, "bin": {"name": "select.bin", "bytes": len(blob),
                                                                      "layout": lay["layout"]}}
    c.write_json(os.path.join("prep", "select", "select_manifest.json"), man)
    files = ["prep/loads.npz", "prep/params.json", "prep/plan.json", "prep/select/part.glb", "prep/select/select.bin",
             "prep/select/select_manifest.json"]
    auto = None
    gst = None
    marks = None
    wall_isl = None
    if select_schema(c) == 2:                    # v0.17.0 BG-D-40: 분류 그래프(schema 2 만 — schema 1 은 건너뜀, 바이트 불변)
        gst = _sel_graph(c, m, gfids, sd, warns, echo, step=step)
        if gst["ok"]:
            files += [f"prep/select/{x}" for x in (bgr_files())]
            wc = _sel_w_clamp(c, m, gfids, sd, echo)    # Verifier fix(§12 BG-X-1): 첫 행렬 전에 W 기본 범위 줄임표
            if wc:
                files.append(wc)
            if step and region is not None:      # v0.18.0 SG-D-20d 영역 밖 세그먼트·섬 표지
                marks = _sel_region_marks(c, region, sd)
                files.append(f"prep/select/{sg.REGION_JSON}")
            if step:                             # v0.18.0 SG-X-2: 벽으로 분류된 걸침 보스(BG_OUTSIDE_MOVED 가 못 봄) = 경고
                wisl = _sel_wall_islands(c, m)
                if wisl:
                    wall_isl = {"code": "STEP_GRAPH_ISLAND_AS_WALL", "n": len(wisl),
                                "floors": [x["floor"] for x in wisl],
                                "segments": sorted({s for x in wisl for s in x["segments"]}),
                                "plan": [x["plan"] for x in wisl]}
                    warns.append(sg.text("STEP_GRAPH_ISLAND_AS_WALL", n=wall_isl["n"],
                                         segments=wall_isl["segments"]))
    if step:                                     # v0.18.0 SG-D-16 iii: auto·manual 모두 seed(fixed_user 포함)
        auto = _sel_auto_step(c, m, bmeta, gst, xfer, marks, warns, echo)
        if auto.get("file"):
            files.append(auto["file"])
        if xfer is not None:
            files.append(f"prep/select/{sg.XFER_JSON}")
    elif bead_source(c) == "auto":               # v0.16.2 AD-D-2·3·21: 자동 탐지 seed(실패해도 준비 계속)
        auto = _sel_auto_v2(c, m, bmeta, gst, warns, echo) if gst is not None else _sel_auto(c, m, bmeta, warns, echo)
        if auto.get("file"):
            files.append(auto["file"])
    inp = U.read_json(c.p("prep", "input.json"))
    fixed_rec = {"source": "none" if fw else "scan", "n": int(fixed.sum())}
    if step:
        fixed_rec = {"source": _xfer_source(xfer), "n": len((xfer or {}).get("node_id") or []),
                     "xfer": sg.xfer_summary(xfer)}
        inp["info"] = [x for x in inp.get("info") or []          # 다시 돌려도 중복 없음
                       if not (isinstance(x, dict) and str(x.get("code", "")).startswith("FIXED_XFER"))] + xinfo
        info += [sg.text(x["code"], **{k: v for k, v in x.items() if k != "code"}) for x in xinfo]
    inp.update(loads={"sha256": loads_sha, **linfo}, n_beads=0, n_params=0, fixed=fixed_rec)
    if getattr(c, "_lt_inp_rec", None):          # v0.20.0 LT-19 계획 id·배치·fast_path
        inp["load_transfer"] = c._lt_inp_rec
    inp["warnings"] = list(inp.get("warnings") or []) + ([fw] if fw else [])
    if step:                                     # 다시 돌려도 중복 없음
        inp["warnings"] = [x for x in inp["warnings"] if not (isinstance(x, dict) and x.get("code") ==
                                                               "STEP_GRAPH_ISLAND_AS_WALL")] + ([wall_isl] if wall_isl else [])
    if auto is not None:
        inp["auto"] = {k: v for k, v in auto.items() if k != "file"}
    if gst is not None:
        inp["graph"] = {k: v for k, v in gst.items() if k != "warnings"}
        if not gst["ok"]:                        # GRAPH_FAILED{code, message, detail} 1개(워커 준비 요약 그대로)
            inp["warnings"] += [w for w in gst.get("warnings") or [] if w.get("code") == "GRAPH_FAILED"]
    c.write_json(os.path.join("prep", "input.json"), inp)
    if step:
        echo(f"[bd_loads] ③ 고정 이전 {fixed_rec['xfer']['method']} · 노드 {fixed_rec['n']} · 맞춤 "
             f"{fixed_rec['xfer']['matched']} · 못 찾음 {fixed_rec['xfer']['unmatched']}")
    echo(f"[bd_loads] select ESL {len(loads)}개 하중({linfo['method']}), 고정 노드 {int(fixed.sum())}"
         + (" — 체결 정보 없음(FIXED_INFO_MISSING)" if fw else "")
         + (f", 경계 경고 {res['n_warn']} · 정보 {res['n_info']}" if res else ""))
    c.progress(100)
    return {"files": files + (["prep/boundary.json"] if res else []),
            "warnings": warns, "info": info,
            "boundary": None if res is None else {"n_warn": res["n_warn"], "n_info": res["n_info"]},
            "n_beads": 0, "n_params": 0, "fixed": fixed_rec,
            **({"auto": {k: v for k, v in auto.items() if k != "file"}} if auto is not None else {}),
            **({"graph": {k: v for k, v in gst.items() if k != "warnings"}} if gst is not None else {})}


def _xfer_source(xfer: dict | None) -> str:
    return "a_transfer" if xfer and xfer.get("method") not in (None, "none") else "none"


def _sel_fixed_transfer(c: Ctx, t, bmeta: dict, ents, region, sd: str) -> tuple[dict | None, list[dict]]:
    """v0.18.0 SG-D-12~15: prep/a_fixed(워커 A Case fixed-scan) → step_graph.fixed_transfer → prep/select/fixed_transfer.json.
    (문서 | None(꺼짐), 정보 dict 목록)."""
    from esl.doe import step_graph as sg
    sgc = sg.cfg_of(c.cfg)
    if not sgc["fixed_transfer"]["enabled"]:
        return None, sg.xfer_messages(None, disabled=True)
    ad = c.p("prep", "a_fixed")
    a_fx, why = None, None
    if not os.path.isfile(os.path.join(ad, pio.SCAN_JSON)):
        # 워커가 A Case fixed-scan 을 시도한 흔적(prep/a_fixed 폴더 — 실패해 보고 없음, 또는 paicad 없음) = A_SCAN_FAILED
        why = "A_SCAN_FAILED" if os.path.isdir(ad) else "A_CASE_MISSING"
    else:
        try:
            a_fx = pio.read_fixed(ad, c.max_mb)
        except EslError:
            why = "A_SCAN_FAILED"
    a = ents[0]
    a_mesh = None
    raw = getattr(a, "raw", None)
    if raw is not None and all(k in raw for k in ("x0", "conn", "elem_type")):
        a_mesh = {k: raw[k] for k in ("x0", "conn", "elem_type")}
    doc = sg.fixed_transfer(a_fx, a.meta["frame"], t, c.cfg, a_mesh=a_mesh, region=region, h=float(bmeta.get("h") or 3.0),
                            hole_min_perimeter=float(c.ocfg["keepout"]["hole_min_perimeter_mm"]),
                            snap_default=float(c.cfg["boundary"]["fastener_warn_mm"]), reason=why)
    sg.write_transfer(os.path.join(sd, sg.XFER_JSON), doc, guard=c.writer.guard)
    return doc, sg.xfer_messages(doc)


def _sel_wall_islands(c: Ctx, mesh: dict) -> list[dict]:
    """v0.18.0 SG-X-2: ``bead_graph.wall_islands`` on the saved graph (island.max_mm of the study's graph settings)."""
    from esl.doe import bead_graph as bgr
    graph, labels = bgr.load_graph(c.p("prep"))
    return bgr.wall_islands(graph, labels, mesh, float(bgr.select_cfg(c.cfg)["graph"]["island"]["max_mm"]))


def _sel_region_marks(c: Ctx, region, sd: str) -> dict:
    """v0.18.0 SG-D-20d prep/select/graph_region.json(영역 밖 > 50 % 세그먼트·섬)."""
    from esl.doe import bead_graph as bgr
    from esl.doe import step_graph as sg
    graph, labels = bgr.load_graph(c.p("prep"))
    mk = bgr.region_marks(graph, labels, region)
    doc = {"schema": sg.REGION_SCHEMA, **mk, "n_in": int(np.asarray(region).sum()),
           "n_out": int((~np.asarray(region, bool)).sum())}
    with open(c.writer.guard(os.path.join(sd, sg.REGION_JSON)), "wb") as fh:
        fh.write(sg.det_bytes(doc))
    return mk


def _sel_auto_step(c: Ctx, mesh: dict, bmeta: dict, gst: dict | None, xfer: dict | None, marks: dict | None, warns: list,
                   echo) -> dict:
    """v0.18.0 SG-D-14b·16: seed 파일은 auto·manual 모두. auto + 그래프 = 영역 안 그래프 seed + fixed_user(source graph);
    manual·그래프 실패·seed 비드 0 = 빈 비드 + fixed_user(source fixed_transfer)."""
    from esl.doe import bead_auto as ba
    from esl.doe import bead_graph as bgr
    fu = (xfer or {}).get("elems") or {"q": [], "t": []}
    frec = {"source": _xfer_source(xfer), "method": (xfer or {}).get("method") or "none",
            "n_nodes": len((xfer or {}).get("node_id") or [])}
    if bead_source(c) == "auto":
        out = _sel_auto_v2(c, mesh, bmeta, gst, warns, echo, fixed_user=fu,
                           exclude_segs=(marks or {}).get("segments"), fixed_rec=frec)
        if out.get("ok"):
            return out
    else:
        out = {"ok": False, "step": None, "code": None, "n_beads": 0, "selection_sha256": None, "warnings": []}
    graph = None
    if gst and gst.get("ok"):
        graph, _ = bgr.load_graph(c.p("prep"))
    sel, sha = bgr.fixed_seed_v2(graph, fu, c.cfg)
    doc = bgr.auto_doc_v2(sel, sha, [], [], list(out.get("warnings") or []), mesh_sha256=bmeta["mesh_sha256"],
                          graph_sha=(gst or {}).get("sha256") if gst and gst.get("ok") else None,
                          source="fixed_transfer", fixed=frec)
    bgr.write_auto_v2(c.p("prep", "select", ba.AUTO_SELECTION_JSON), doc, guard=c.writer.guard)
    out.update(ok=bead_source(c) != "auto" or out.get("ok", False), n_beads=0, selection_sha256=sha,
               source="fixed_transfer", file="prep/select/" + ba.AUTO_SELECTION_JSON)
    echo(f"[bd_loads] ③ seed(비드 없음 + 이전 고정 {frec['n_nodes']} 노드) sha {sha[:12]}…")
    return out


def bgr_files() -> tuple:
    from esl.doe import bead_graph as bgr
    return (bgr.GRAPH_JSON, bgr.GRAPH_LABELS, bgr.GRAPH_BIN)


def _sel_graph(c: Ctx, mesh: dict, fids, sd: str, warns: list, echo, step: bool = False) -> dict:
    """v0.17.0 BD_LOADS 분류(BG-D-40): ``bead_graph.prep_graph`` → prep/select/graph.json·graph_labels.npz·graph.bin.
    실패 = 준비 READY 유지 + 경고 GRAPH_FAILED{code}(수동은 src elems 비드로 계속)."""
    from esl.doe import bead_graph as bgr
    if step:                                     # v0.18.0 SG-D-16 i: step 상한 = max(graph.limits, step_graph)
        from esl.doe import step_graph as sg
        sgc = sg.cfg_of(c.cfg)
        st = bgr.prep_graph(mesh, fids, c.cfg, sd, guard=c.writer.guard,
                            limits={"max_elems": sgc["max_elems"], "timeout_s": sgc["timeout_s"]})
    else:
        st = bgr.prep_graph(mesh, fids, c.cfg, sd, guard=c.writer.guard)
    if not st["ok"]:                             # 구조화 경고 1개 {code, message, detail}(AUTO_DETECT_FAILED 와 같은 형식)
        gw = graph_failed_warning(st["code"])
        st["warnings"] = [gw]                    # inp.warnings 로(아래 bd_loads) — inp.graph 에는 code 만
        warns.append(_sel_warn_text({"code": gw["code"], "detail": gw["detail"]}))
        echo(f"[bd_loads] 자동 분류 실패({st['code']}) — 직접 칠하기(요소 비드)로 계속")
    else:
        for w in st.get("warnings") or []:
            if w.get("level") != "info":
                warns.append(_sel_warn_text(w))
        echo(f"[bd_loads] 분류 그래프 세그먼트 {st['n_segments']} · 접합 구역 {st['n_junction_zones']} · 섬 "
             f"{st['n_islands']} · {st['seconds']:.1f}s (beadgraph {st['beadgraph_version']} rules {st['rules']})")
    return st


def _sel_w_clamp(c: Ctx, mesh: dict, fids, sd: str, echo) -> str | None:
    """v0.17.0 Verifier fix(§12 BG-X-1): 그래프 W 후보(세그먼트별 + 자동 seed W 묶음)의 기본 범위 끝 뒤집힘을 BD_LOADS 에서 미리
    찾아 prep/select/w_clamp.json — derive(API·BD_MATRIX)가 이 표로 기본 범위·feasible 을 줄이므로 첫 행렬부터 뒤집히는 W 안이 없다.
    실패해도 준비는 계속(BD_MATRIX clamp_w_ranges 가 그대로 받침)."""
    from esl.doe import bead_graph as bgr
    try:
        graph, labels = bgr.load_graph(c.p("prep"))
        doc = bgr.w_clamp_table(mesh, graph, labels, fids, c.cfg)
    except EslError as exc:
        echo(f"[bd_loads] W 기본 범위 점검 건너뜀({exc.code})")
        return None
    bgr.write_w_clamp(os.path.join(sd, bgr.W_CLAMP_JSON), doc, guard=c.writer.guard)
    echo(f"[bd_loads] W 기본 범위 끝 뒤집힘 미리 점검: 줄일 변수 {len(doc['entries'])}")
    return f"prep/select/{bgr.W_CLAMP_JSON}"


def graph_failed_warning(code: str | None) -> dict:
    """v0.17.0 GRAPH_FAILED 준비 경고(BG-D-40·§6.4) — 코어·워커·화면 공통 형식 {code: "GRAPH_FAILED", message, detail}
    (detail = 안쪽 사유 ERROR|TIMEOUT|TOO_LARGE|DISABLED|NO_FLOOR, AUTO_DETECT_FAILED{detail} 과 같은 규칙)."""
    detail = str(code or "ERROR")
    tmpl = _sel_msg("GRAPH_FAILED") or "GRAPH_FAILED"
    try:
        msg = tmpl.format(detail=detail, code=detail)
    except (KeyError, IndexError, ValueError):
        msg = tmpl
    return {"code": "GRAPH_FAILED", "message": msg[:300], "detail": detail}


def _sel_auto_v2(c: Ctx, mesh: dict, bmeta: dict, gst: dict | None, warns: list, echo, *, fixed_user: dict | None = None,
                 exclude_segs=None, fixed_rec: dict | None = None) -> dict:
    """v0.17.0 BG-D-20·42 자동 seed = 그래프(paicad 는 힌트만): prep/select/auto_selection.json(schema
    esl/doe_auto_selection/2, source graph). 그래프 실패 = 파일 없음 + AUTO_DETECT_FAILED{step graph, code}."""
    from esl.doe import bead_auto as ba
    from esl.doe import bead_graph as bgr
    out = {"ok": False, "step": "graph", "code": None, "n_beads": 0, "selection_sha256": None, "warnings": [],
           "source": "graph"}
    if not gst or not gst.get("ok"):
        out["code"] = (gst or {}).get("code") or "GRAPH_FAILED"
        out["warnings"].append({"code": "AUTO_DETECT_FAILED", "step": "graph", "detail": out["code"]})
        warns.append(f"AUTO_DETECT_FAILED: step=graph code={out['code']}")
        return out
    graph, labels = bgr.load_graph(c.p("prep"))
    if exclude_segs is not None or fixed_user is not None:     # v0.18.0 step: 영역 밖 제외 + 이전 고정(SG-D-14b·20d)
        sel, sym, aw = bgr.auto_seed(graph, labels, c.cfg, exclude_segs=exclude_segs)
        if fixed_user is not None:
            sel["fixed_user"] = fixed_user
    else:
        sel, sym, aw = bgr.auto_seed(graph, labels, c.cfg)
    hints = []
    ad = pio.read_auto_detect(c.p("prep"), c.max_mb)
    if ad and ad.get("ok"):
        try:
            hints = bgr.slope_hints(graph, pio.read_features(c.p("prep", "extract"), c.max_mb), mesh, labels)
        except EslError as exc:
            aw.append({"code": "AUTO_HINT_UNAVAILABLE", "level": "info", "step": "extract", "code_": exc.code})
    else:
        aw.append({"code": "AUTO_HINT_UNAVAILABLE", "level": "info", "step": (ad or {}).get("step"),
                   "detail": (ad or {}).get("code")})
    if not sel["beads"]:
        out.update(code="AUTO_BEAD_UNMAPPED")
        out["warnings"] += aw
        warns.append("AUTO_DETECT_FAILED: step=graph code=AUTO_BEAD_UNMAPPED")
        return out
    norm, sha = bgr.normalize_v2(sel, graph, c.cfg, labels=labels, mesh=mesh)
    doc = bgr.auto_doc_v2(norm, sha, sym, hints, aw, mesh_sha256=bmeta["mesh_sha256"], graph_sha=gst["sha256"],
                          **({"fixed": fixed_rec} if fixed_rec is not None else {}))
    bgr.write_auto_v2(c.p("prep", "select", ba.AUTO_SELECTION_JSON), doc, guard=c.writer.guard)
    for w in aw:
        if w.get("level") != "info":
            warns.append(_sel_warn_text(w))
    out.update(ok=True, step=None, n_beads=len(norm["beads"]), selection_sha256=sha, warnings=aw + hints,
               file="prep/select/" + ba.AUTO_SELECTION_JSON)
    echo(f"[bd_loads] 그래프 자동 seed 비드 {len(norm['beads'])} · 대칭 제안 {len(sym)} · sha {sha[:12]}…")
    return out


def _sel_auto(c: Ctx, mesh: dict, bmeta: dict, warns: list, echo) -> dict:
    """v0.16.2 자동 탐지 seed: prep/auto_detect.json(워커) 이 OK 면 prep/extract·prep/tag → ``bead_auto.auto_selection`` →
    prep/select/auto_selection.json(결정적 바이트). 실패·비드 0 = 파일 없음 + 경고 ``AUTO_DETECT_FAILED{step, code}``(문자열은
    warns 에, 원본 dict 는 반환 warnings 에). 반환 {ok, step, code, n_beads, selection_sha256, warnings[], file?}."""
    from esl.doe import bead_auto as ba
    ad = pio.read_auto_detect(c.p("prep"), c.max_mb) or {"ok": False, "step": "version", "code": "AUTO_DETECT_MISSING",
                                                         "paicad_version": None}
    out = {"ok": False, "step": ad.get("step"), "code": ad.get("code"), "n_beads": 0, "selection_sha256": None,
           "warnings": []}

    def fail(step, code):
        w = {"code": "AUTO_DETECT_FAILED", "step": step, "detail": code}
        out.update(ok=False, step=step, code=code)
        out["warnings"].append(w)
        warns.append(f"AUTO_DETECT_FAILED: step={step} code={code}")
        echo(f"[bd_loads] 자동 탐지 실패({step} {code}) — 빈 초기 선택, 수동 선택")
    if not ad.get("ok"):
        fail(ad.get("step") or "version", ad.get("code"))
        return out
    try:
        sel, mp, aw = ba.auto_from_prep(c.p("prep"), mesh, c.cfg, c.max_mb)
    except EslError as exc:
        fail(getattr(exc, "step", None) or "tag", exc.code)
        return out
    out["warnings"] += aw
    for w in aw:
        if w.get("level") != "info":
            warns.append(_sel_warn_text(w))
    if sel is None:
        fail("tag", "AUTO_BEAD_UNMAPPED")
        return out
    sha = ba.write_auto_selection(c.p("prep", "select", ba.AUTO_SELECTION_JSON), sel, mp, aw,
                                  mesh_sha256=bmeta["mesh_sha256"], paicad_version=ad.get("paicad_version"),
                                  guard=c.writer.guard)
    out.update(ok=True, step=None, code=None, n_beads=len(sel["beads"]), selection_sha256=sha,
               file="prep/select/" + ba.AUTO_SELECTION_JSON)
    echo(f"[bd_loads] 자동 탐지 초기 선택 비드 {len(sel['beads'])} · sha {sha[:12]}…")
    return out


def _sel_prepare(c: Ctx, t, echo) -> dict:
    """BD_MATRIX select: 선택 정규화·sha 확인 → derive → 기저 → select/<sha12>/ (같은 sha 면 재사용)."""
    from esl.doe import bead_select as bsel
    norm, sha = _sel_norm(c, t.mesh)
    v2 = norm.get("schema_version") == 2
    bmeta = U.read_json(c.p("prep", "base.json"))
    d = _sel_dir(c, sha)
    pb, pj, pp = os.path.join(d, "basis.npz"), os.path.join(d, "basis.json"), os.path.join(d, "params.json")
    if all(os.path.isfile(p) for p in (pb, pj, pp, os.path.join(d, "basis.bin"))):
        bj = U.read_json(pj)
        if bj.get("selection_sha256") == sha and bj.get("mesh_sha256") == bmeta["mesh_sha256"] and \
                bj.get("basis_sha256") == U.sha256_file(pb) and bj.get("cfg_sha256") == _sel_cfg_sha(c) and \
                bj.get("algo", 1) == bsel.ALGO and \
                (not v2 or (bj.get("graph_algo") == _bgr().GRAPH_ALGO and           # v0.17.0 BG-D-39 재사용 조건
                            bj.get("morph_rules") == _bgr()._bg().MORPH_RULES)):     # 옛 규칙 기저는 1회 재계산
            echo(f"[bd_matrix] select 기저 재사용 {sha[:12]}…")
            return {"params": U.read_json(pp)["params"], "warnings": [],
                    "rev_doc": _sel_rev(c, sha, bj["basis_sha256"])}
    fids, _ = _sel_fixed_ids(c)
    ms = (c.D.get("selection") or {}).get("mesh_sha256")
    if ms and ms != bmeta["mesh_sha256"]:
        raise EslError("PREVIEW_STALE", "선택의 mesh_sha256 이 준비 기준 메시와 다름(SELECTION_DROPPED)")
    if v2:                                      # v0.17.0 schema 2: 그래프 비드(+ elems 비드는 schema 1 derive, 섬 60)
        graph, labels = _graph_or_none(c)
        D = _bgr().derive_obj_v2(t.mesh, norm, c.cfg, graph, labels, fixed_node_ids=fids, mesh_sha256=bmeta["mesh_sha256"],
                                 w_clamp=_bgr().load_w_clamp(c.p("prep")) if graph is not None else None)
    else:
        D = bsel.derive_obj(t.mesh, norm, c.cfg, fixed_node_ids=fids, mesh_sha256=bmeta["mesh_sha256"],
                            with_section=False)
    B = bsel.basis(t.mesh, D, c.cfg)
    rc_w = bsel.range_check(t.mesh, D, B, c.cfg)   # v0.16.1 SR-D-33: 기본 범위 끝 뒤집힘 → 비드 경고(범위·기저 불변)
    if v2:                                      # 통합 v0.17.0(BG-X-1): 그래프 W 기본 범위 = usable 로 줄임 + 정보 BG_RANGE_CLAMPED
        _bgr().clamp_w_ranges(D, rc_w)
    if rc_w:
        echo("[bd_matrix] 기본 범위 끝 뒤집힘: " + ", ".join(
            f"{w['var']} 기본 범위 {w['from']} → {w['to']}(뒤집힘 없는 범위로 줄임)" if w["code"] == "BG_RANGE_CLAMPED" else
            f"{w['var']} 쓸 수 있는 범위 ≈ {w['usable']}" if "var" in w else
            f"조합(표본 {w['corners']} 중 뒤집힘 {w['inverted_n']}) 함께 쓸 범위 ≈ 공칭 ± {w['scale']} 배" for w in rc_w))
    tab = bsel.params_table(D, c.cfg)
    c.writer.makedirs(d)
    bsel.save_basis(pb, B, guard=c.writer.guard)
    bsha = U.sha256_file(pb)
    blob = bsel.basis_bin(B)                    # 브라우저 3D 보기(§7.3, GET …/select/basis)
    with open(c.writer.guard(os.path.join(d, "basis.bin")), "wb") as fh:
        fh.write(blob)
    _sel_save_derived(c, os.path.join(d, "derived.npz"), D, B)
    c.write_json(os.path.relpath(os.path.join(d, "derived.json"), c.out), D.summary(with_figures=False))
    c.write_json(os.path.relpath(pp, c.out), {"beads": [{"id": b.id, "name": b.name, "kind": "select",
                                                         "n_tiers": len(b.tiers), "W_nom": b.W_nom,
                                                         "W_min": getattr(b, "W_min", None),
                                                         "W_max": getattr(b, "W_max", None), "blend_mm": b.blend_mm,
                                                         "warnings": b.warnings} for b in D.beads],
                                              "params": tab, "warnings": D.warnings})
    meta = bsel.basis_meta(B, bsha)
    import hashlib
    meta.update(sha256=hashlib.sha256(blob).hexdigest(), mesh_sha256=bmeta["mesh_sha256"], cfg_sha256=_sel_cfg_sha(c))
    if v2:                                      # v0.17.0 BG-D-39: 그래프 경로 판·패키지 판 + 램프(BG_RAMP_SHORT 판단)
        bg = _bgr()._bg()
        meta.update(graph_algo=_bgr().GRAPH_ALGO, morph_rules=bg.MORPH_RULES, rules_graph=bg.RULES,
                    beadgraph_version=bg.__version__,
                    graph_vars=[{"name": v["name"], "kind": v["kind"], "nominal": float(v["nominal"]),
                                 "ramp_mm": float(v["info"]["ramp_mm"])} for v in getattr(D, "graph_basis", [])])
    c.write_json(os.path.relpath(pj, c.out), meta)
    warns = [f"{w['code']}: {b.id}" for b in D.beads for w in b.warnings]
    echo(f"[bd_matrix] select {sha[:12]}… 비드 {len(D.beads)} · 변수 {len(B.vars)} · 기저 sha {bsha[:12]}…")
    return {"params": tab, "warnings": warns, "rev_doc": _sel_rev(c, sha, bsha)}


def _bgr():
    from esl.doe import bead_graph as bgr
    return bgr


def _graph_or_none(c: Ctx):
    """(graph, labels) of prep/select or (None, None) after GRAPH_FAILED (schema 2 continues with elems beads)."""
    try:
        return _bgr().load_graph(c.p("prep"))
    except EslError:
        return None, None


def _sel_cfg_sha(c: Ctx) -> str:
    import hashlib
    import json

    from esl.doe import bead_select as bsel
    s = json.dumps({"select": bsel.select_hash_view(c.cfg["select"], step=_is_step_base(c)),
                    "quality": c.cfg["compare"]["quality"]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sel_rev(c: Ctx, sha: str, bsha: str) -> dict:
    return {"schema": "esl/doe_selection_rev/1", "selection_sha256": sha, "basis_sha256": bsha,
            "selection_rev": (c.D.get("selection") or {}).get("rev"), "dir": f"select/{sha[:12]}"}


def _sel_save_derived(c: Ctx, path: str, D, B=None) -> None:
    from esl.doe import bead_select as bsel
    from esl.doe.mesh_gmsh import save_npz_det
    arr = {"fixed": np.asarray(D.fixed_mask, dtype=np.uint8)}
    if B is not None:                    # v0.16.1 SR-D-37·38 안 판정 보조(피처·다른 비드 침범) — 없으면 키 없음(바이트 불변)
        arr.update(bsel.checks_arrays(bsel.design_checks(D, B)))
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
            if k.endswith("_ptr") and not k.startswith("chk_"):
                bid = k[:-4]
                L, P = z[f"{bid}_loops"], z[k]
                loops += [L[P[i]:P[i + 1]] for i in range(P.size - 1)]
                nh.append(z[f"{bid}_nhat"])
        c._sel_cache = {"B": bsel.load_basis(pb), "fixed": z["fixed"].astype(bool), "loops": loops, "rev": r,
                        "n_hats": nh, "checks": bsel.checks_from_arrays(z)}
    return c._sel_cache


def _sel_design(c: Ctx, t, did: str) -> tuple[np.ndarray, dict]:
    from esl.doe import bead_select as bsel
    L = _sel_loaded(c)
    x0 = np.asarray(t.mesh["x0"], dtype=np.float64)
    vals = _design_values(c, did)
    x = bsel.morph(x0, L["B"], vals)
    return x, bsel.design_state(t.mesh, x0, x, L["fixed"], c.cfg, checks=L.get("checks"), values=vals)


def _sel_warn_text(w: dict) -> str:
    """경고 dict → 'CODE: k=v …' 한 줄(result.json warnings·보고서)."""
    return f"{w['code']}: " + " ".join(f"{k}={v}" for k, v in w.items() if k != "code")


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
        st = bsel.design_state(t.mesh, x0, xd, L["fixed"], c.cfg, checks=L.get("checks"), values=x["values"])
        states[x["id"]] = st
        if st["state"] == "READY":
            cv = sr.color_values(x0, xd, direction, has)
            vmax = max(vmax, float(np.abs(cv).max()) if cv.size else 0.0)
        c.progress(5 + 30 * (k + 1) / max(len(designs), 1))
    V = vmax if vmax > 0 else float(c.cfg["limits"]["min_disp_range_mm"])
    view = sr.view(x0, has, sr.view_normal(x0, L["n_hats"]), t.frame, tcfg)
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
        if st.get("warnings"):                   # v0.16.1 경고 안(READY — 실행·순위 대상, SR-D-1·11)
            cell["warnings"] = st["warnings"]
        if st["fixed"]["violated"]:              # v0.16.1 SR-D-3: 침범 원인 = 침범이 있는 모든 칸(상태 무관)
            cell["fixed_viol"] = bsel.fixed_violation_detail(x0, xd, L["fixed"], L["B"], x["values"],
                                                             float(bsel._cfg(c.cfg)["fixed_tol_mm"]))
        cells.append(cell)
        c.progress(35 + 60 * (k + 1) / max(len(designs), 1))
    man = {"schema_version": 1, "kind": "select", "cells": cells, "nominal": {"thumb": "cells/nominal/thumb.png"},
           "color": {"v_max": V, "unit": "mm"}, "selection_sha256": L["rev"]["selection_sha256"],
           "basis_sha256": L["rev"]["basis_sha256"], "rules": bsel.RULES,
           **({"graph_rules": _bgr().GRAPH_RULES} if L["checks"].get("outside") else {})}
    c.write_json(os.path.join(gd_rel, pio.GRID_MANIFEST), U.jsonable(man))
    cnt = {"ok": sum(x["status"] == "OK" for x in cells),
           "fixed": sum(x["code"] == "SELECT_FIXED_VIOLATION" for x in cells),
           "mesh": sum(x["code"] in ("SELECT_QUALITY_FAIL", "SELECT_MORPH_INVERTED", "SELECT_FEATURE_DISTORTED",
                                     "BG_OUTSIDE_MOVED") for x in cells),
           "warn": sum(x["status"] == "OK" and bool(x.get("warnings")) for x in cells)}
    echo(f"[bd_select_grid] rev {rev} 안 {len(cells)} · OK {cnt['ok']}(경고 {cnt['warn']}) · 고정 침범 {cnt['fixed']} · "
         f"품질 실패 {cnt['mesh']} · V {V:.3g} mm")
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
    if _is_step_base(c):                         # v0.18.0 SG-D-17: 원 rad 없음(받기 = export_mesh 만)
        c._sel_rad, c._sel_rad_source = [], "step"
        return []
    if select_base(c) == "mesh":                 # v0.16.2 AD-D-20: ② B 메시 기준 = input/mesh 사본(rel = 업로드 상대경로)
        return _sel_rad_files_mesh(c, nid)
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


def _sel_rad_files_mesh(c: Ctx, nid: np.ndarray) -> list[tuple[str, str]]:
    """AD-D-20: prep/input.json ``mesh.files``(BD_INPUT 이 복사·sha 기록한 input/mesh 사본) 중 B 파트 /NODE 를 가진 파일
    [(rel, 사본 경로)] (rel 정렬). 사본 sha 가 기록과 다르면 INPUT_CHANGED."""
    inp = U.read_json(c.p("prep", "input.json"))
    want = set(int(v) for v in nid.tolist())
    out = []
    for f in (inp.get("mesh") or {}).get("files") or []:
        rel = str(f["rel"]).replace(os.sep, "/")
        src = c.p("input", "mesh", *rel.split("/"))
        if os.path.islink(src) or os.path.splitext(src)[1].lower() not in sc.MESH_EXT or not os.path.isfile(src):
            continue
        if nd.read_nodes(src, want, c.max_line()):
            if f.get("sha256") and U.sha256_file(src) != f["sha256"]:
                raise EslError("INPUT_CHANGED", f"B 메시 사본이 준비 뒤 바뀜(sha256 불일치): {os.path.basename(src)}")
            out.append((rel, src))
    out.sort()
    c._sel_rad = out
    c._sel_rad_source = "input/mesh"
    return out


def _sel_part_title(c: Ctx) -> str:
    """받기 ch_r.rad 파트 제목: ① = 기준 Case 파트, ② select_base mesh = B 파트(AD-D-20 — inputs.part_title, 없으면 B 메시에서
    읽은 제목·설정 기본)."""
    if _is_step_base(c):                         # v0.18.0 SG-D-17: STEP 파일 이름 줄기
        inp = U.read_json(c.p("prep", "input.json"))
        return os.path.splitext(os.path.basename(inp["step"]["rel"]))[0]
    if select_base(c) == "mesh":
        inp = U.read_json(c.p("prep", "input.json"))
        return str((c.D.get("mesh") or {}).get("part_title") or c.D.get("part_title") or inp.get("part_title")
                   or c.cfg["part_title"])
    return str(c.D.get("base", {}).get("part_title") or "ch_r")


SEL_WARN_NODES_PER_LINE, SEL_WARN_NODES_MAX = 10, 50       # SR-D-12 주석 줄의 고정 노드 ID(줄당·전체 상한)
SEL_WARN_LINE_MAX = 100                                     # SR-D-43 주석 줄 길이 상한(자, Radioss 입력 줄 한도)


def _sel_fixed_comment(c: Ctx, t, did: str, x: np.ndarray) -> tuple[list[str], list[dict]]:
    """v0.16.1 SR-D-12 받기 경고: 고정 침범 안이면 ASCII 주석 줄(#ESL WARNING FIXED_MOVED … + FIXED_NODES), 그리고
    values.json warnings(고정·품질 경고 dict). 경고 없는 안 = ([], [])."""
    from esl.doe import bead_select as bsel
    L = _sel_loaded(c)
    x0 = np.asarray(t.mesh["x0"], dtype=np.float64)
    st = bsel.design_state(t.mesh, x0, x, L["fixed"], c.cfg, checks=L.get("checks"), values=_design_values(c, did))
    sw = list(st.get("warnings") or [])
    fm = next((w for w in sw if w["code"] == "SELECT_FIXED_MOVED"), None)
    if fm is None:
        return [], sw
    det = bsel.fixed_violation_detail(x0, x, L["fixed"], L["B"], _design_values(c, did),
                                      float(bsel._cfg(c.cfg)["fixed_tol_mm"]), cap=SEL_WARN_NODES_MAX)
    ids = [int(t.mesh["node_id"][i]) for i in det["node_idx"]]
    return sel_warn_lines(fm, ids), sw


def sel_warn_lines(fm: dict, ids: list[int]) -> list[str]:
    """SR-D-12·43 받기 rad 주석 줄: FIXED_MOVED 머리 + FIXED_NODES(줄당 ≤ SEL_WARN_NODES_PER_LINE 개 ∧ ≤ SEL_WARN_LINE_MAX 자 —
    머리도 넘으면 설명을 다음 줄로). 짧은 ID 면 v0.16.1 첫 판과 같은 줄."""
    head = f"#ESL WARNING FIXED_MOVED n={fm['n']} max_mm={fm['max_mm']} : fastener positions moved, check RBE2/TIE"
    if len(head) > SEL_WARN_LINE_MAX:
        lines = [f"#ESL WARNING FIXED_MOVED n={fm['n']} max_mm={fm['max_mm']}",
                 "#ESL WARNING FIXED_MOVED : fastener positions moved, check RBE2/TIE"]
    else:
        lines = [head]
    pre = "#ESL WARNING FIXED_NODES"
    cur: list[str] = []
    for v in ids:
        if cur and (len(cur) >= SEL_WARN_NODES_PER_LINE or len(pre) + sum(len(x) + 1 for x in cur) + len(str(v)) + 1
                    > SEL_WARN_LINE_MAX):
            lines.append(pre + " " + " ".join(cur))
            cur = []
        cur.append(str(v))
    if cur:
        lines.append(pre + " " + " ".join(cur))
    return lines


def _insert_after_first_line(c: Ctx, path: str, lines: list[str]) -> None:
    """파일 첫 줄 뒤에 주석 줄(첫 줄 줄바꿈 바이트 따름) — ch_r.rad 머리 주석(SR-D-12)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    k = raw.find(b"\n")
    head, rest = (raw[:k + 1], raw[k + 1:]) if k >= 0 else (raw + b"\n", b"")
    eol = b"\r\n" if head.endswith(b"\r\n") else b"\n"
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(c.writer.guard(tmp), "wb") as fh:
        fh.write(head + b"".join(x.encode("ascii") + eol for x in lines) + rest)
    atomic_replace(tmp, c.writer.guard(path))


def _sel_best(c: Ctx, did: str, bd: str) -> list[str]:
    """BS-D-14: rad/include 사본(/NODE 좌표만) + ch_r.rad·ch_r.fem + selection.json (best/<did> 상대경로).
    v0.16.1 SR-D-12: 고정 침범 경고 안은 사본 첫 /NODE 앞·ch_r.rad 머리에 ASCII 주석, values.json 에 warnings."""
    from esl.doe import export_mesh
    t, _ = sc.load_base(c.p("prep"))
    dz = ev.load_design(design_dir(c, did))
    nid = np.asarray(t.mesh["node_id"], dtype=np.int64)
    cl, sw = _sel_fixed_comment(c, t, did, np.asarray(dz["x"], dtype=np.float64))
    files = []
    for rel, src in _sel_rad_files(c, nid):
        dst = os.path.join(bd, "include", *rel.split("/"))
        c.writer.makedirs(os.path.dirname(dst))
        nd.write_morphed(src, dst, nid, dz["x"], t.mesh["x0"], max_line=c.max_line(), guard=c.writer.guard,
                         comment_lines=cl or None)
        files.append("include/" + rel)
    mesh = {k: t.mesh[k] for k in ("node_id", "elem_id", "elem_type", "conn", "elem_pid", "thickness", "E", "nu")}
    mesh["x0"] = dz["x"]
    files += export_mesh.write(bd, mesh, part_title=_sel_part_title(c),
                               header=["esl bead DOE (scenario select, base step)" if _is_step_base(c)
                                       else "esl bead DOE (scenario select)"], guard=c.writer.guard)
    if cl:
        _insert_after_first_line(c, os.path.join(bd, export_mesh.RAD_NAME), cl)
    if sw:
        vp = os.path.join(bd, "values.json")
        vd = U.read_json(vp)
        vd["warnings"] = sw
        U.write_json(c.writer.guard(vp), vd)
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
            row = {"id": x["id"], "state": x["status"], "new_fail": qq.get("new_fail"),
                   "n_affected": qq.get("n_affected"), "fixed_max_mm": mi.get("fixed_max_mm")}
            if x.get("select_warnings"):         # v0.16.1 경고 열
                row["warn"] = [str(w["code"]).replace("SELECT_", "", 1) for w in x["select_warnings"]]
            q.append(row)
    moved = [{"id": x["id"], **x["select_fixed_viol"]} for x in results if x.get("select_fixed_viol")]
    out = {"sha256": r["selection_sha256"], "beads": der.get("beads") or [], "fixed": der.get("fixed") or {},
           "quality": q}
    if moved:                                    # v0.16.1 '체결 위치 어긋남' 절(SR-D-11·§6)
        out["fixed_moved"] = moved
    return out


__all__ = ["STAGES", "run_stage", "bd_input", "bd_mesh0", "bd_loads", "bd_matrix", "bd_eval", "bd_post",
           "bd_select_grid", "SKIPPED", "FAILED"]
