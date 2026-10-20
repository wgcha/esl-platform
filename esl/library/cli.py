"""CLI: ``python -m esl.library <명령>`` (계약 esl_p2_library.md §1·§3·§4·§5).

  register --root R --case C [--run-id ID] [--scene-path P] [--mass M] [--confirm-fail 사유] [--supersedes EID] [--by 이름]
  retire   --root R --entry EID --reason 사유
  list     --root R [--filter k=v[,v]] [--all]
  analyze  --root R [--target EID] [--filter k=v ...] [--id AID] [--normalization none|mass|inch2]
           [--n-representative N] [--svd-energy E] [--worst-case] [--target-mass M] [--target-inch I]
           [--optdeck-cases all|representative|representative+worst] [--max-cases N]
  optdeck  --root R --analysis AID [--reference-compliance none|solve]
  report   --root R --analysis AID
  compare  --root R --model M [--base-version V] [--new-version V] [--filter k=v ...] [--id CID]
           [--cos-min C] [--n-representative N]

공통 ``--config library.yaml`` (없으면 env ESL_LIBRARY_CONFIG). 입력 Case 폴더에는 쓰지 않고(겹치면 INPUT_INVALID),
출력 파일이 이미 있으면 ``_backup/<UTC ts>/`` 로 옮긴 뒤 쓴다. 종료코드 0 성공, 1 오류(stderr ``CODE: message``).
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from esl.errors import EslError
from esl.library import _util as U
from esl.library import analysis as an
from esl.library import entry as en
from esl.library import optdeck as od
from esl.library import report_analysis as ra
from esl.library import settings as st
from esl.library import store as sto


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EslError("INPUT_INVALID", f"인자 오류: {message}")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m esl.library", description="ESL 라이브러리·종합분석·비드 최적화 덱")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

    def common(s, cfg=True):
        s.add_argument("--root", required=True, help="ESL 루트(<root>/library, <root>/_analysis)")
        if cfg:
            s.add_argument("--config", default=None, help="library.yaml (없으면 env ESL_LIBRARY_CONFIG)")

    r = sub.add_parser("register", help="Case 의 ESL 결과를 라이브러리에 등록")
    common(r)
    r.add_argument("--case", required=True)
    r.add_argument("--run-id", default=None, help="플랫폼 스냅샷 runs/<id>/ 사용")
    r.add_argument("--scene-path", default=None, help="씬 메타를 읽을 경로(h3d 경로 등)")
    r.add_argument("--mass", type=float, default=None, help="제품 질량(모델 단위). 없으면 파트 질량")
    r.add_argument("--confirm-fail", default=None, help="검증 FAIL 을 사유와 함께 확정 등록")
    r.add_argument("--supersedes", default=None, help="정정: 이전 항목 ID (retired 처리)")
    r.add_argument("--by", default=None, help="등록자")
    t = sub.add_parser("retire", help="항목 retire")
    common(t, cfg=False)
    t.add_argument("--entry", required=True)
    t.add_argument("--reason", required=True)
    ls = sub.add_parser("list", help="항목 목록")
    common(ls, cfg=False)
    ls.add_argument("--filter", action="append", default=[])
    ls.add_argument("--all", action="store_true", help="retired 포함")
    a = sub.add_parser("analyze", help="종합분석")
    common(a)
    a.add_argument("--target", default=None, help="설계 대상 항목 ID (없으면 정규화 격자 통계)")
    a.add_argument("--filter", action="append", default=[])
    a.add_argument("--id", default=None, help="분석 ID (기본 A<UTC 시각>)")
    a.add_argument("--normalization", choices=["none", "mass", "inch2"], default=None)
    a.add_argument("--n-representative", type=int, default=None)
    a.add_argument("--svd-energy", type=float, default=None)
    a.add_argument("--worst-case", action="store_true", default=None)
    a.add_argument("--target-mass", type=float, default=None)
    a.add_argument("--target-inch", type=float, default=None)
    a.add_argument("--optdeck-cases", choices=["all", "representative", "representative+worst"], default=None,
                   help="덱 subcase 구성(기본 설정 optdeck.cases)")
    a.add_argument("--max-cases", type=int, default=None, help="all 의 자동 축소 상한(기본 설정 optdeck.max_cases)")
    o = sub.add_parser("optdeck", help="OptiStruct DTPG 덱 생성")
    common(o)
    o.add_argument("--analysis", required=True)
    o.add_argument("--reference-compliance", choices=["none", "solve"], default=None)
    rp = sub.add_parser("report", help="HTML 보고서")
    common(rp, cfg=False)
    rp.add_argument("--analysis", required=True)
    c = sub.add_parser("compare", help="설계 버전 비교(ESLSO 수렴 판정)")
    common(c)
    c.add_argument("--model", required=True, help="제품명(model)")
    c.add_argument("--base-version", default=None, help="기준 버전(기본: 비교 버전 직전)")
    c.add_argument("--new-version", default=None, help="비교 버전(기본: 최신)")
    c.add_argument("--filter", action="append", default=[])
    c.add_argument("--id", default=None, help="비교 ID (기본 C<UTC 시각>)")
    c.add_argument("--cos-min", type=float, default=None, help="수렴 기준 cos 최소(기본 설정 convergence.cos_min)")
    c.add_argument("--n-representative", type=int, default=None, help="재군집 k(기본 설정 analysis.n_representative)")
    return p


# ---------------------------------------------------------------- 명령
def cmd_register(a, echo) -> dict:
    cfg = st.load(a.config)
    lib = cfg["library"]
    root = os.path.abspath(a.root)
    case = os.path.abspath(a.case)
    w = U.Writer(root, inputs=[("Case 폴더", case)])
    e = en.build(case, a.run_id, scene_path=a.scene_path, rules=st.scene_rules(cfg), nx=lib["grid"]["nx"],
                 ny=lib["grid"]["ny"], axis_ref=lib["axis_ref"], top_n=lib["top_nodes"], mass=a.mass,
                 registered_by=a.by)
    q = e.meta["quality"]
    if q["verdict"] != "PASS":
        if a.confirm_fail:
            q["confirmed_fail"] = {"reason": a.confirm_fail, "by": a.by, "at": U.utcnow()}
        elif lib["require_pass"]:
            raise EslError("VALIDATION_NOT_PASS",
                           f"검증 {q['verdict']} — PASS 가 아닌 결과는 --confirm-fail \"사유\" 로만 등록")
    b = sto.register(root, e, w, supersedes=a.supersedes, reason=f"정정: {a.confirm_fail or ''}".strip())
    echo(f"[register] {b['entry_id']} {b['product']} {b['inch']}\" {b['scenario']} {b['drop_class']}{b['orient'] or ''} "
         f"scene {b['scene']} 검증 {b['verdict']} → {sto.entry_dir(root, b['entry_id'])}")
    for x in e.meta["warnings"]:
        echo(f"  경고: {x}")
    return b


def cmd_list(a, echo) -> list:
    rows = sto.query(os.path.abspath(a.root), sto.parse_filters(a.filter), include_retired=a.all)
    for r in rows:
        echo(f"{r['entry_id']}  {r['status']:<7} {r['product']} {r['inch']}\" {r['scenario']} {r['drop_class']}"
             f"{r['orient'] or ''} S{r['scene']} {r['verdict']}")
    echo(f"{len(rows)}개")
    return rows


def cmd_analyze(a, echo) -> dict:
    cfg = st.load(a.config)
    root = os.path.abspath(a.root)
    filters = sto.parse_filters(a.filter)
    rows = sto.query(root, filters)
    if not rows:
        raise EslError("INPUT_INVALID", f"필터에 맞는 활성 항목이 없음: {filters}")
    target = sto.load_entry(root, a.target, raw=True) if a.target else None
    if target is not None and target.meta.get("status") == "retired":
        raise EslError("INPUT_INVALID", f"대상 {a.target} 는 retired")
    entries = []
    for r in rows:
        same = target is not None and r.get("mesh_sha256") == target.meta.get("mesh_sha256")
        entries.append(sto.load_entry(root, r["entry_id"], raw=same))
    opts = dict(cfg["analysis"])
    opts["deck_cases"] = a.optdeck_cases or cfg["optdeck"]["cases"]
    opts["max_cases"] = a.max_cases or cfg["optdeck"]["max_cases"]
    for k, v in (("normalization", a.normalization), ("n_representative", a.n_representative),
                 ("svd_energy", a.svd_energy), ("worst_case", a.worst_case), ("target_mass", a.target_mass),
                 ("target_inch", a.target_inch)):
        if v is not None:
            opts[k] = v
    res, arrays = an.run(entries, target, opts)
    aid = a.id or ("A" + U.utcstamp())
    res["analysis_id"] = aid
    res["filters"] = {k: ",".join(v) for k, v in filters.items()}
    res["library_root"] = root
    res["config_path"] = cfg["_path"]
    w = U.Writer(root)
    d = sto.analysis_dir(root, aid)
    w.makedirs(d)
    files = an.save(res, arrays, d, w)
    echo(f"[analyze] {aid}: 항목 {res['n_cases']}개, SVD r={res['svd']['n_modes']} "
         f"(누적 {res['svd']['cum_energy'][res['svd']['n_modes'] - 1]:.3f}), 대표 "
         + ", ".join(f"{lc['label']}={lc['entry_id']}" for lc in res["load_cases"])
         + f", 덱 {res['deck']['mode']} subcase {res['deck']['n_subcases']}"
         + (" (자동 축소)" if res["deck"]["reduced"] else "")
         + (f", 매핑 보존 오차 최대 {res['mapping']['conservation_rel_max']:.2e}" if res.get("mapping") else "")
         + f" → {d} ({', '.join(files)})")
    for x in res["warnings"]:
        echo(f"  경고: {x}")
    return res


def _load_analysis(root, aid):
    d = sto.analysis_dir(root, aid)
    if not os.path.isfile(os.path.join(d, "analysis.json")):
        raise EslError("PREREQUISITE_MISSING", f"분석 결과가 없음: {d} (analyze 먼저)")
    return d, U.read_json(os.path.join(d, "analysis.json")), U.load_npz(os.path.join(d, "mapped_loads.npz"))


def reference_compliance(mesh: dict, supports, Fs, solver: dict) -> list[float]:
    """자체 쉘 솔버로 C_k = Σ F·u (3-2-1, 병진 성분). 하중별 기준 컴플라이언스."""
    from esl.mech.shell import ShellModel
    sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                    drill_factor=solver["drill_factor"], backend=solver["backend"])
    nid = np.asarray(mesh["node_id"])
    spc = [(int(np.searchsorted(nid, n)), str(dof)) for n, dof in supports]
    out = []
    for F in Fs:
        u, _ = sm.solve(np.asarray(F, dtype=np.float64), spc)
        out.append(float(np.sum(np.asarray(F) * u[:, :3])))
    return out


def cmd_optdeck(a, echo) -> dict:
    cfg = st.load(a.config)
    root = os.path.abspath(a.root)
    d, res, arrays = _load_analysis(root, a.analysis)
    if not res.get("target"):
        raise EslError("INPUT_INVALID", "대상 모델 없는 분석은 덱을 만들 수 없음(analyze --target)")
    tgt = sto.load_entry(root, res["target"]["entry_id"], raw=True)
    mesh = tgt.mesh()
    if not np.array_equal(np.asarray(arrays["node_id"]), np.asarray(mesh["node_id"])):
        raise EslError("ID_MISMATCH", "mapped_loads.npz node_id 가 대상 메시와 다름")
    sup = [(s["node_id"], s["dof"]) for s in tgt.meta["esl"]["supports"]]
    lcs = an.optdeck_load_cases(res, arrays)
    oc = dict(cfg["optdeck"])
    oc.pop("cases", None)
    oc.pop("max_cases", None)
    mode = a.reference_compliance or oc.pop("reference_compliance")
    oc.pop("reference_compliance", None)
    solver = oc.pop("solver")
    if mode == "solve":
        refs = reference_compliance(mesh, sup, [x["f"] for x in lcs], solver)
        for x, rv in zip(lcs, refs):
            x["ref"] = rv
    oc["header"] = [f"analysis {res.get('analysis_id')} target {tgt.entry_id} ({res['target']['model'].get('product')})",
                    f"load cases: {', '.join(x['label'] + '=' + x['entry_id'] for x in lcs)}",
                    f"reference compliance: {mode}"]
    w = U.Writer(root)
    out = os.path.join(d, "opt")
    w.fresh_dir(out, d)
    summ = od.write(mesh, lcs, sup, oc, out, w)
    summ["reference_compliance"] = mode
    summ["analysis_id"] = res.get("analysis_id")
    summ["deck_cases"] = _deck_brief(res)
    U.write_json(w.fresh_file(os.path.join(out, "optdeck.json"), d), summ)
    echo(f"[optdeck] {out}: {summ['deck']} subcase {summ['n_subcases']}, 설계 요소 {summ['n_design_elems']} / 비설계 "
         f"{summ['n_nondesign_elems']}, 목적 {summ['objective']}, 기준 컴플라이언스 {mode}")
    return summ


def _deck_brief(res) -> dict | None:
    d = res.get("deck")
    if not d:
        return None
    return {k: d.get(k) for k in ("requested", "mode", "reduced", "max_cases", "n_cases", "n_subcases")} | \
        {"n_excluded": len(d.get("excluded") or [])}


def cmd_compare(a, echo) -> dict:
    from esl.library import compare as cmp

    cfg = st.load(a.config)
    root = os.path.abspath(a.root)
    filters = sto.parse_filters(a.filter)
    filters.pop("version", None)
    rows = [r for r in sto.query(root, dict(filters, product=[a.model]))]
    versions = cmp.sort_versions({r.get("version") for r in rows if r.get("version") is not None})
    if not versions:
        raise EslError("NO_PAIRED_SCENES", f"모델 {a.model} 의 버전 있는 활성 항목이 없음")
    new_v = a.new_version or versions[-1]
    base_v = a.base_version or cmp.previous_version(versions, new_v)
    if base_v is None:
        raise EslError("NO_PAIRED_SCENES", f"모델 {a.model}: 버전 {new_v} 이전 버전이 없음(버전 {versions})")
    base = [sto.load_entry(root, r["entry_id"]) for r in rows if str(r.get("version")) == str(base_v)]
    new = [sto.load_entry(root, r["entry_id"]) for r in rows if str(r.get("version")) == str(new_v)]
    crit = dict(cfg["convergence"])
    if a.cos_min is not None:
        crit["cos_min"] = a.cos_min
    k = a.n_representative or cfg["analysis"]["n_representative"]
    res = cmp.compare(base, new, crit, {"n_representative": k, "seed": cfg["analysis"]["seed"],
                                        "n_init": cfg["analysis"]["n_init"]})
    cid = a.id or ("C" + U.utcstamp())
    res.update(comparison_id=cid, model=a.model, base_version=str(base_v), new_version=str(new_v),
               filters={kk: ",".join(v) for kk, v in filters.items()}, library_root=root)
    w = U.Writer(root)
    d = sto.compare_dir(root, cid)
    w.makedirs(d)
    files = cmp.save(res, d, w)
    cv = res["convergence"]
    echo(f"[compare] {cid}: {a.model} {base_v} → {new_v}, 짝 {res['n_paired']}개, cos 최소 "
         f"{res['aggregate']['cos_min']:.4f}, 대표 동일 {res['representatives']['rep_same']} → {cv['label']}"
         f" ({d}: {', '.join(files)})")
    for x in res["warnings"]:
        echo(f"  경고: {x}")
    return res


def cmd_report(a, echo) -> str:
    root = os.path.abspath(a.root)
    d, res, arrays = _load_analysis(root, a.analysis)
    op = os.path.join(d, "opt", "optdeck.json")
    opt = U.read_json(op) if os.path.isfile(op) else None
    w = U.Writer(root)
    out = w.fresh_file(os.path.join(d, "report.html"), d)
    ra.write(res, out, arrays, opt, {"analysis_id": res.get("analysis_id"), "filters": res.get("filters")})
    echo(f"[report] {out}")
    return out


_CMDS = {"register": cmd_register, "retire": None, "list": cmd_list, "analyze": cmd_analyze,
         "optdeck": cmd_optdeck, "report": cmd_report, "compare": cmd_compare}


def main(argv: list[str] | None = None, echo=print) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        a = build_parser().parse_args(argv)
        if a.cmd == "retire":
            root = os.path.abspath(a.root)
            sto.retire(root, a.entry, a.reason, U.Writer(root))
            echo(f"[retire] {a.entry}")
        else:
            _CMDS[a.cmd](a, echo)
        return 0
    except EslError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).replace("\n", " ")
        print(f"INTERNAL_ERROR: {type(exc).__name__}: {msg}", file=sys.stderr)
        return 1
