"""v0.24.4 P2b A2b — Case ③ 지그 ESL 3방식 · ④ 지그 검증 행 · ③ 3D 지그 행 (계약 docs/contracts/esl_jig_case.md §5·§6·§11·§13
V-0244-JIG-8·9·10·12(코어)·15).

합성 Case = synth_case 판(1107 노드, 25° 대회전 + 변형) + 판 위 1 mm 이웃 쉘(파트 9 — deck 접촉 영역 1) + 경계력·내력 자료,
tie 9노드 fixed-scan 픽스처(01_extract/jig_fixed — 워커 jig_prep 출력 형식). extract·tstar 1회 → 시험마다 out 사본에서 ③·④.

기록값(이 환경, normal·α = 0.01 기본, 재현 MAC = 파트 Kabsch 제거 응답 vs u_rel):
- 고정 0.612(맞춤 0.580, JIG_FIT_POOR·JIG_TIE_RELATIVE tie_rel 0.30) · 변위 0.997(맞춤 0.996) · 스프링 0.997(맞춤 0.996).
- 3-2-1 면내 반력비(Σ‖r_aux‖/Σ‖F‖) — 면내 반력 0 등식 제약(D-0.24.4-JIG-20) 후 ≤ 2e-12(세 방식).
- ④ 분해 묶음 = bc321(full·bforce·fint) · jig(jig·jig_disp — 같은 구속 패턴) · jig(jig_spring) — 3 묶음.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil

import numpy as np
import pytest

import synth_case
from test_bforce_stage import _add_bforce

from esl import config as cfgm
from esl import pipeline, view3d, view3d_src
from esl import val_src as vs
from esl.errors import EslError
from esl.io import fixed_scan as fxs
from esl.mech import bforce as bfm
from esl.mech import jig, jig_bc, kabsch
from esl.rad import writer as rw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CFG_TEXT = open(os.path.join(ROOT, "config", "esl.example.yaml"), encoding="utf-8").read().replace(
    "disp_precision: float32", "disp_precision: float64")
TAG = "jigcase-t1"
SRCS = tuple(r["src"] for r in jig_bc.METHODS.values())
NY = 26
TIE_IJ = [(i, j) for i in (6, 20, 34) for j in (4, 13, 22)]


# ====================================================================== 픽스처
def add_neighbor(c, gap=1.0):
    """판 가운데 위 gap 떨어진 쉘 판(파트 9, 두께 1.5) — deck 접촉 영역(대상 밖 표면)."""
    X0 = c["X0"]
    idx = {(i, j): 800001 + k for k, (i, j) in enumerate((i, j) for i in range(14, 27) for j in range(8, 19))}
    rows = [rw._i10(n) + "".join(rw._r20(v) for v in X0[i * (NY + 1) + j] + np.array([0.0, 0.0, gap]))
            for (i, j), n in idx.items()]
    sh, e = [], 810001
    for i in range(14, 26):
        for j in range(8, 18):
            sh.append(rw._i10(e) + "".join(rw._i10(idx[q]) for q in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))))
            e += 1
    with open(c["rad"], encoding="utf-8") as fh:
        txt = fh.read()
    add = (["/NODE"] + rows + rw._mat_law1(990, "mat_nb", 7.85e-9, 2.1e5, 0.3) + rw._prop_shell(99, "prop_nb", 1.5)
           + rw._part(9, "neighbor", 99, 990) + ["/SHELL/9"] + sh)
    i = txt.rindex("/END")
    with open(c["rad"], "w", encoding="utf-8") as fh:
        fh.write(txt[:i] + "\n".join(add) + "\n" + txt[i:])


def tie_index():
    return np.array([i * (NY + 1) + j for i, j in TIE_IJ], dtype=np.int64)


def write_fixed(out, c, idx, kind="INTER_TYPE2_SECONDARY"):
    """워커 jig_prep 출력(paicad shell fixed-scan 형식) → 01_extract/jig_fixed/."""
    d = os.path.join(out, pipeline.D_EXTRACT, pipeline.JIG_FIXED_DIR)
    os.makedirs(d, exist_ok=True)
    n = len(idx)
    np.savez(os.path.join(d, fxs.FIXED_NPZ), node_id=c["node_id"][idx].astype(np.int64), part=np.full(n, 7, np.int32),
             kind_mask=np.full(n, 1 << fxs.FIXED_KINDS.index(kind), np.int16), cluster=np.arange(n, dtype=np.int32),
             xyz=c["X0"][idx])
    with open(os.path.join(d, fxs.SCAN_JSON), "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "kind": "shell", "status": "OK", "code": None,
                   "fixed": {"total": n, "clusters": []}, "warnings": []}, fh)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("jigcase"))
    c = synth_case.build(root, source="max_strain")
    _add_bforce(c, c["csv"], fint_sign=-1.0)
    add_neighbor(c)
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(CFG_TEXT)
    out = os.path.join(root, "tpl")
    kw = dict(config_path=cfg, rad=c["rad"], results=c["csv"], out=out, frame=synth_case.T_STAR_FRAME,
              echo=lambda *_: None, tag=TAG)
    pipeline.run(stage="extract", **kw)
    pipeline.run(stage="tstar", **kw)
    return {"root": root, "c": c, "cfg": cfg, "tpl": out}


def case_copy(base, dst, *, fixed=True, cfg_extra=""):
    out = os.path.join(str(dst), "out")
    shutil.copytree(base["tpl"], out)
    if fixed:
        write_fixed(out, base["c"], tie_index())
    cfg = base["cfg"]
    if cfg_extra:
        cfg = os.path.join(str(dst), "cfg.yaml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(CFG_TEXT + "\n" + cfg_extra)
    return {"out": out, "cfg": cfg}


def run(base, r, stage):
    return pipeline.run(config_path=r["cfg"], rad=base["c"]["rad"], results=base["c"]["csv"], out=r["out"], stage=stage,
                        frame=synth_case.T_STAR_FRAME, echo=lambda *_: None, tag=TAG)


def jload(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def npz(*p):
    with np.load(os.path.join(*p), allow_pickle=False) as z:
        return {k: np.asarray(z[k]) for k in z.files}


def esl_summary(rec):
    return rec["stages"]["esl"]["summary"]


def ctx_of(r):
    return pipeline.Context(cfg=cfgm.load_config(r["cfg"]), config_path="", rad="", results="", out=r["out"], ts="",
                            frame=None, support_nodes=None, echo=lambda *_: None, record={})


@pytest.fixture(scope="module")
def esl_run(base, tmp_path_factory):
    r = case_copy(base, tmp_path_factory.mktemp("esl"))
    rec = run(base, r, "esl")
    return {**r, "rec": rec}


# ---------------------------------------------------------------- 비교 도구(04_esl 의 지그 밖 파일 바이트)
VOLATILE = {"created_at", "assembly_s", "tocsr_s", "factor_s", "solve_s", "eval_s", "rss_peak_mb", "mem_avail_mb",
            "mem_avail"}                                  # 시각·시간·메모리(tests/doe/test_jig_move.py 와 같은 규칙)


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _h_file(p):
    if p.endswith(".npz"):
        h = hashlib.sha256()
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                a = z[k]
                h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
                h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()
    with open(p, "rb") as fh:
        b = fh.read()
    if p.endswith(".json"):
        b = json.dumps(_strip(json.loads(b.decode("utf-8"))), sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(b).hexdigest()


def non_jig_hashes(out):
    d = os.path.join(out, pipeline.D_ESL)
    jig_files = {f"{s}.{e}" for s in SRCS for e in ("json", "npz")} | {pipeline.JIG_BASIS_NPZ}
    return {f: _h_file(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f not in jig_files}


# ====================================================================== V-8 Case 3방식 산출·재현
def test_v8_three_methods_files_schema_and_recon(base, esl_run):
    out, summ = esl_run["out"], esl_summary(esl_run["rec"])
    d = os.path.join(out, pipeline.D_ESL)
    zb = npz(d, pipeline.JIG_BASIS_NPZ)
    assert str(zb["schema"]) == pipeline.CASE_JIG_BASIS_SCHEMA
    assert pipeline._arr_sha({k: v for k, v in zb.items() if k not in ("schema", "sha256")}) == str(zb["sha256"])
    J = tie_index()
    assert np.array_equal(zb["jig_idx"], J) and zb["tie_node"].size == J.size                  # 평판 근사 — 노드마다 법선 1
    assert zb["aux_node"].size == 3 and zb["mode_f"].shape[0] == 4
    model = pipeline.load_model(out)
    X0 = model.x0
    u_rel = npz(d, "u_rel.npz")["u_rel"]
    sm = pipeline._shell(ctx_of(esl_run), model)
    tie = {"node": zb["tie_node"], "dir": zb["tie_dir"]}
    mac = {}
    for m, row in jig_bc.METHODS.items():
        s = row["src"]
        doc, z, sx = jload(d, f"{s}.json"), npz(d, f"{s}.npz"), summ[s]
        assert doc["schema"] == pipeline.CASE_JIG_SCHEMA and doc["source"] == s and doc["method"] == m
        assert (doc["status"], doc["code"], doc["tie_dofs"]) == ("ok", None, "normal") and doc["rigid_free"] == 0
        assert doc["bc"] == {"tie_dofs": "normal", "tie_text": jig_bc.TIE_DOFS["normal"]["text"], "n_jig": 9,
                             "n_tie_rows": 9, "n_aux": 3}
        assert doc["n_contact"] == 1 and doc["surf"]["status"] == "ok" and doc["regions"][0]["part"] == 9
        assert set(z) == {"node_id", "f", "a", "u_val", *jig_bc.BC_KEYS, "jig_idx", "basis_sha"}
        assert str(z["basis_sha"]) == str(zb["sha256"]) and np.array_equal(z["node_id"], model.node_id)
        BC = jig_bc.load_bc(z)
        assert (np.asarray(BC["sp_node"]).size > 0) == (row["tie_stiff"] != "hard")
        # 응답 = 같은 BC 로 재풀이 → 파트 Kabsch = npz u_val, 재현 MAC·umax 오차 = 요약(bforce.recon_report 정의)
        u = jig_bc.solve(jig_bc.factorize(sm, BC), z["f"], BC)[0][:, :3]
        uv = kabsch.remove_rigid(X0, u)[0]
        assert np.abs(uv - z["u_val"]).max() <= 1e-9 * np.abs(z["u_val"]).max()
        rep = bfm.recon_report(u_rel, z["u_val"], None, z["f"])
        assert sx["mac"] == pytest.approx(rep["mac"], abs=1e-12) and sx["umax_err"] == pytest.approx(rep["umax_err"])
        assert doc["recon"]["mac"] == sx["mac"] and sx["status"] == "ok" and sx["n_jig"] == 9
        # 3-2-1 면내 반력 0 제약(D-0.24.4-JIG-20): 맞춤 하중이 면내 평형 — 반력비 ≈ 0
        assert sx["aux_reaction_rel"] < 1e-8 and doc["fit"]["aux_eq"]["applied"] is True
        assert doc["energy"]["aux_reaction_rel"] == sx["aux_reaction_rel"]
        assert sx["limits"] == list(row["limits"]) and doc["limits"] == sx["limits"]
        assert len(sx["limit_text"]) == len(sx["limits"]) and all(sx["limit_text"])
        mac[m] = sx["mac"]
    assert mac["prescribed"] >= mac["spring"] >= mac["fixed"]
    assert mac["prescribed"] > 0.99 and mac["fixed"] < 0.8                                      # 함께 휘는 tie 를 0 으로 — 재현 불가
    # spring: k = α·d̂ᵀK₀[n]d̂, α 기본 0.01(JIG_DEFAULTS 한 곳 — D-0.24.4-JIG-19)
    zs, ds = npz(d, "jig_spring.npz"), jload(d, "jig_spring.json")
    assert jig.JIG_DEFAULTS["spring_alpha"] == 0.01 and ds["spring"]["alpha"] == 0.01
    assert np.allclose(zs["sp_k"], jig_bc.spring_k(sm, tie, mode="auto", alpha=0.01), rtol=1e-12)
    assert jload(d, "jig.json")["spring"] is None
    # 경고: 고정만 JIG_TIE_RELATIVE(열 tie_rel_warn), 변위 = 한계 JIG_DISP_FROM_TARGET
    w = esl_run["rec"]["stages"]["esl"]["warnings"]
    assert any(x.startswith("JIG_TIE_RELATIVE") for x in w)
    assert jload(d, "jig.json")["fit"]["tie_rel"] > 0.1 and jload(d, "jig_disp.json")["fit"]["tie_rel"] is None
    assert summ["jig_disp"]["limits"] == ["JIG_DISP_FROM_TARGET"]


def test_v8_translation_fixed_equals_study_arithmetic(base, tmp_path):
    """translation·fixed = 스터디 _jig_baseline 의 산술 순서(target_disp → select_regions → factor(J 123) → 모드 → 기저 → fit_loads)
    를 같은 Case 입력으로 직접 돌린 a·F(1e-9). 제약 없음(3-2-1 면내 행 없음 — 옛 경로)."""
    r = case_copy(base, tmp_path, cfg_extra="jig:\n  tie_dofs: translation\n  methods: [fixed]\n")
    rec = run(base, r, "esl")
    s = esl_summary(rec)
    assert s["jig"]["status"] == "ok" and s["jig"]["tie_dofs"] == "translation"
    for k in ("jig_disp", "jig_spring"):
        assert s[k]["code"] == "JIG_DISABLED" and "jig.methods" in s[k]["reason"]
        assert not os.path.exists(os.path.join(r["out"], pipeline.D_ESL, f"{k}.npz"))
    d = os.path.join(r["out"], pipeline.D_ESL)
    z, doc = npz(d, "jig.npz"), jload(d, "jig.json")
    assert doc["fit"]["aux_eq"] is None and np.asarray(z["sp_node"]).size == 0
    model = pipeline.load_model(r["out"])
    mesh = pipeline._jig_mesh(model)
    X, N = model.x0, model.node_id.size
    Jd = jig.JIG_DEFAULTS
    J = z["jig_idx"]
    fit = np.ones(N, bool)
    fit[J] = False
    u_rel = npz(d, "u_rel.npz")["u_rel"]
    tg = jig.target_disp(X, u_rel, J, fit)
    zs = npz(r["out"], pipeline.D_EXTRACT, pipeline.JIG_SURF_NPZ)
    surf = {k: zs[k] for k in ("x", "node_id", "tri", "tri_part", "tri_thick")}
    wts = jig.node_weights(mesh)
    rs = jig.select_regions(mesh, fit, J, surf, gap_mm=Jd["contact_gap_mm"], knn=Jd["knn"], chunk_nodes=Jd["chunk_nodes"],
                            max_regions=Jd["max_regions"], min_regions=Jd["min_regions"], min_nodes=Jd["min_region_nodes"],
                            min_area_mm2=Jd["min_region_area_mm2"], patch_count=Jd["patch_count"], weights=wts)
    h = jig.factor(mesh, J, cfgm.load_config(r["cfg"])["solver"])
    m = jig.lumped_mass(wts, Jd["rho_t_mm3"])
    fixed = np.asarray([6 * int(p) + int(dd) for p, dd in h.cons], dtype=np.int64)
    md = jig.jig_modes(h.model.K(), jig.mass_diag6(m), fixed, Jd["n_modes"], Jd["modes_sigma"], opinv=jig.opinv_from(h, N),
                       tol=Jd["modes_tol"], maxiter=Jd["modes_maxiter"])
    basis = jig.load_basis(mesh, rs["regions"], wts, np.ones(N, bool), body_force=Jd["body_force"],
                           tangential=Jd["basis_tangential"], modes=jig.mode_loads(md["phi"], m))
    BR = jig.basis_response(h, basis, fit)
    area = wts["area"]
    fr = jig.fit_loads(BR["U"], tg["u_tgt"][fit], area[fit] / area[fit].mean(), wts["normal"][fit], basis,
                       ridge=Jd["ridge"], w_inplane=Jd["w_inplane"], reg_force=Jd["reg_force"], reg_modes=Jd["reg_modes"])
    F = jig.forces(basis, fr["a"], N)
    assert np.abs(z["a"] - fr["a"]).max() <= 1e-9 * np.abs(fr["a"]).max()
    assert np.abs(z["f"] - F).max() <= 1e-9 * np.abs(F).max()
    assert doc["fit"]["mac"] == pytest.approx(jig.fit_report(
        jig.respond(h, [("x", F)], keep_u=True)[0]["u"], tg["u_tgt"], fit, wts, basis, fr["a"], jig_idx=J,
        active_tol=Jd["active_tol"])["mac"], rel=1e-9)


def test_v8_surface_cache_and_include_stat(base, tmp_path, monkeypatch):
    """deck 표면 캐시: 두 번째 ESL = 다시 읽지 않음(01_extract/jig_surf.npz 키 일치), starter stat 변경 → 다시 읽음."""
    from esl.rad import surface as srf
    calls = []
    real = srf.other_surfaces

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(srf, "other_surfaces", counted)
    r = case_copy(base, tmp_path)
    run(base, r, "esl")
    assert len(calls) == 1 and os.path.isfile(os.path.join(r["out"], pipeline.D_EXTRACT, pipeline.JIG_SURF_NPZ))
    a1 = npz(r["out"], pipeline.D_ESL, "jig.npz")["a"]
    run(base, r, "esl")
    assert len(calls) == 1                                                       # 캐시
    assert jload(r["out"], pipeline.D_ESL, "jig.json")["surf"]["cached"] is True
    assert np.array_equal(npz(r["out"], pipeline.D_ESL, "jig.npz")["a"], a1)    # 캐시 표면 = 같은 결과
    rad = base["c"]["rad"]
    st = os.stat(rad)
    try:
        os.utime(rad, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        run(base, r, "esl")
        assert len(calls) == 2                                                   # include 트리 stat 변경 → 다시 읽음
    finally:
        os.utime(rad, ns=(st.st_atime_ns, st.st_mtime_ns))


# ====================================================================== V-8 실패 격리
def _prep_record(out, attempts):
    with open(os.path.join(out, pipeline.D_EXTRACT, pipeline.JIG_PREP_JSON), "w", encoding="utf-8") as fh:
        json.dump({"schema": "esl/jig_prep/1", "attempts": attempts}, fh)


@pytest.mark.parametrize("record,code,detail", [
    (None, "JIG_NOT_PREPARED", None),
    ([{"job_id": TAG, "status": "failed", "code": "JIG_FIXED_FAILED", "detail": "paicad exit 3"}], "JIG_FIXED_FAILED",
     "paicad exit 3"),
    ([{"job_id": TAG, "status": "skipped", "detail": "paicad 준비 안 됨"}], "JIG_FIXED_SKIPPED", "paicad 준비 안 됨"),
    ([{"job_id": "other-job", "status": "failed", "detail": "x"}], "JIG_NOT_PREPARED", None),
    ([{"job_id": TAG, "status": "disabled", "detail": "bead_doe.case_jig.enabled"}], "JIG_DISABLED",
     "bead_doe.case_jig.enabled"),
])
def test_v8_prep_records_three_rows_same_code(base, tmp_path, record, code, detail):
    r = case_copy(base, tmp_path, fixed=False)
    if record is not None:
        _prep_record(r["out"], record)
    s = esl_summary(run(base, r, "esl"))
    for k in SRCS:
        assert (s[k]["status"], s[k]["code"]) == ("unavailable", code), k
        assert s[k]["reason"] and (detail is None or detail in s[k]["reason"])
        assert not os.path.exists(os.path.join(r["out"], pipeline.D_ESL, f"{k}.json"))      # 산출물 집합 불변
    assert not os.path.exists(os.path.join(r["out"], pipeline.D_ESL, pipeline.JIG_BASIS_NPZ))
    st = view3d_src.case_status(view3d_src.plan("jig"), s["jig"], {"model": True, "load": False, "target": True})
    assert st["code"] == code and st["reason"] == s["jig"]["reason"]


def test_v8_isolation_exceptions_and_other_sources_bytes(base, tmp_path, monkeypatch):
    """공유 단계 예외 = 세 행 JIG_FAILED(진단 json), 스프링 단계 예외 = 그 행만, 지그 끔·정상·실패 모두 full·bforce·fint·u_rel 바이트 같음."""
    ref = case_copy(base, tmp_path / "off", cfg_extra="jig:\n  enabled: false\n")
    s0 = esl_summary(run(base, ref, "esl"))
    assert all(s0[k]["code"] == "JIG_DISABLED" for k in SRCS)
    h0 = non_jig_hashes(ref["out"])
    assert {"f_eq.npz", "u_rel.npz", "bforce.npz", "fint.npz", "esl_summary.json"} <= set(h0)
    ok = case_copy(base, tmp_path / "ok")
    run(base, ok, "esl")
    assert non_jig_hashes(ok["out"]) == h0

    def boom(*a, **k):
        raise RuntimeError("basis boom")
    with monkeypatch.context() as mp:
        mp.setattr(jig, "load_basis", boom)
        r = case_copy(base, tmp_path / "shared")
        s = esl_summary(run(base, r, "esl"))
    for k in SRCS:
        assert (s[k]["status"], s[k]["code"]) == ("unavailable", "JIG_FAILED") and "basis boom" in s[k]["reason"]
        assert jload(r["out"], pipeline.D_ESL, f"{k}.json")["code"] == "JIG_FAILED"
        assert not os.path.exists(os.path.join(r["out"], pipeline.D_ESL, f"{k}.npz"))
    assert non_jig_hashes(r["out"]) == h0

    def kboom(*a, **k):
        raise EslError("INPUT_INVALID", "k boom")
    with monkeypatch.context() as mp:
        mp.setattr(jig_bc, "spring_k", kboom)
        r = case_copy(base, tmp_path / "spring")
        s = esl_summary(run(base, r, "esl"))
    assert s["jig_spring"]["code"] == "JIG_FAILED" and "INPUT_INVALID" in s["jig_spring"]["reason"]
    assert s["jig"]["status"] == s["jig_disp"]["status"] == "ok"
    assert not os.path.exists(os.path.join(r["out"], pipeline.D_ESL, "jig_spring.npz"))
    assert os.path.isfile(os.path.join(r["out"], pipeline.D_ESL, "jig_disp.npz"))
    assert non_jig_hashes(r["out"]) == h0


# ====================================================================== V-9 ④ 검증 지그 행
def test_v9_validate_jig_rows_groups_response_and_report(base, esl_run, tmp_path):
    r = {"out": os.path.join(str(tmp_path), "out"), "cfg": esl_run["cfg"]}
    shutil.copytree(esl_run["out"], r["out"])
    rec = run(base, r, "validate")
    out = r["out"]
    sj = jload(out, pipeline.D_VAL, vs.SOURCES_JSON)
    rows = {x["key"]: x for x in sj["rows"]}
    assert [x["key"] for x in sj["rows"]] == list(vs.KEYS)
    g = sj["solve"]["groups"]
    assert [(x["support"], x["keys"]) for x in g] == [("bc321", ["full", "bforce", "fint"]), ("jig", ["jig", "jig_disp"]),
                                                      ("jig", ["jig_spring"])]
    assert g[1]["pattern"] != g[2]["pattern"] and "pattern" not in g[0]
    model = pipeline.load_model(out)
    X0 = model.x0
    sm = pipeline._shell(ctx_of(r), model)
    u_rel = npz(out, pipeline.D_ESL, "u_rel.npz")["u_rel"]
    d_rel = kabsch.remove_linear_rigid(X0, u_rel)[0]
    for k in SRCS:
        x = rows[k]
        assert x["status"] == "done" and x["dir"] == k and x["reaction_role"] == "info" and x["verdict"] in ("PASS", "FAIL")
        v = jload(out, pipeline.D_VAL, k, "validation.json")
        mm = {m["metric"]: m for m in v["metrics"]}
        assert mm["reaction_rel"]["role"] == "info" and mm["reaction_rel"]["pass"] is None
        assert v["src"]["key"] == k and v["src"]["load"] == f"04_esl/{k}.npz" and v["src"]["support"] == "jig"
        assert "지그 경계(tie 면외(법선) 9 + 3-2-1 면내 3)" in x["cond_text"] and vs.BALANCE_TEXT[k] in x["cond_text"]
        # 응답 = ESL 과 같은 경계(값·바닥·k)로 재풀이 — compare_disp d_val = 선형 강체 제거 ESL 응답(1e-9)
        z = npz(out, pipeline.D_ESL, f"{k}.npz")
        BC = jig_bc.load_bc(z)
        u = jig_bc.solve(jig_bc.factorize(sm, BC), z["f"], BC)[0][:, :3]
        cz = npz(out, pipeline.D_VAL, k, "compare_disp.npz")
        dv = kabsch.remove_linear_rigid(X0, u)[0]
        assert np.abs(cz["d_val"] - dv).max() <= 1e-9 * np.abs(dv).max()
        assert np.allclose(cz["d_rel"], d_rel, rtol=0, atol=1e-12 * np.abs(d_rel).max())
        rr = {x_["node_id"] for x_ in v["reactions"]}                          # 지지력 표시 = bc 노드(tie·3-2-1 면내)
        bn = set(model.node_id[np.r_[BC["bc_node"], BC["sp_node"]].astype(np.int64)].tolist())
        assert rr == bn
    assert rows["jig_disp"]["limits"] == ["JIG_DISP_FROM_TARGET"] and rows["jig_disp"]["comparable"] is True
    assert vs.limit_class("JIG_DISP_FROM_TARGET") == "caution"
    assert rows["jig_disp"]["limit_text"] == esl_summary(esl_run["rec"])["jig_disp"]["limit_text"]
    assert rows["jig"]["limits"] == [] and rows["full"]["verdict"] == "PASS"
    ss = rec["stages"]["validate"]["summary"]["sources"]
    assert all(ss[k]["status"] == "done" for k in SRCS)
    run(base, r, "report")
    with open(os.path.join(out, pipeline.D_REPORT, "report.html"), encoding="utf-8") as fh:
        html = fh.read()
    blk = html[html.index("<!--val-src-->"):html.index("<!--/val-src-->")]
    blk = blk[blk.index("<table"):]
    pos = [blk.index(vs.LABEL[k]) for k in vs.KEYS]
    assert pos == sorted(pos)                                                    # 출처 표 순서 = KEYS(지그 3행 포함)


def test_v9_val_failed_jig_bc_only_that_row(base, esl_run, tmp_path):
    """지그 행 지지 집합 읽기 실패(손상 bc 배열) = 그 행 VAL_SRC_FAILED, 같은 묶음의 다른 행·full 무영향."""
    r = {"out": os.path.join(str(tmp_path), "out"), "cfg": esl_run["cfg"]}
    shutil.copytree(esl_run["out"], r["out"])
    p = os.path.join(r["out"], pipeline.D_ESL, "jig_disp.npz")
    z = npz(p)
    z["node_id"] = z["node_id"][::-1].copy()                                     # 하중 준비는 통과하지 않음 → 준비 단계 failed
    np.savez(p, **z)
    run(base, r, "validate")
    rows = {x["key"]: x for x in jload(r["out"], pipeline.D_VAL, vs.SOURCES_JSON)["rows"]}
    assert rows["jig_disp"]["status"] == "failed" and rows["jig_disp"]["code"] == "VAL_SRC_FAILED"
    assert rows["jig"]["status"] == rows["jig_spring"]["status"] == rows["full"]["status"] == "done"


# ====================================================================== V-12(코어) ③ 3D CASE_PLAN 지그 행
def test_v12_case_plan_jig_rows_resolve(esl_run):
    out, summ = esl_run["out"], esl_summary(esl_run["rec"])
    loc = {"esl": os.path.join(out, pipeline.D_ESL)}
    for k in SRCS:
        row = view3d_src.plan(k)
        have = {"model": True}
        arrs = {}
        for col in view3d_src.FILE_COLS:
            f = row[col]
            zz = npz(loc[f[0]], f[1])
            have[col] = f[2] in zz
            arrs[col] = zz.get(f[2])
        st = view3d_src.case_status(row, summ[row["summary"]], have)
        assert (st["available"], st["resp"], st["code"]) == (True, True, None), k
        rf = view3d.recon_fields(arrs["recon_tgt"], arrs["resp"])
        assert rf["mac"] == pytest.approx(summ[k]["mac"], abs=1e-12)            # 3D 재현 = ESL 요약(같은 정의)
        assert os.path.isfile(os.path.join(loc[row["doc"][0]], row["doc"][1]))


# ====================================================================== V-15 설정
def test_v15_config_jig_section():
    from esl.mech import jig_bc as jb
    assert cfgm.JIG_FIXED_KINDS == fxs.FIXED_KINDS and cfgm.JIG_METHODS == tuple(jb.METHODS)
    assert cfgm.JIG_TIE_DOFS == tuple(jb.TIE_DOFS) and cfgm.JIG_SPRING_ALPHA_MIN == jb.SPRING_ALPHA_MIN
    assert set(cfgm.SCHEMA["jig"]) == set(jig.JIG_DEFAULTS) and "jig" in cfgm.OPTIONAL_SECTIONS
    assert cfgm.jig_settings(None) == jig.JIG_DEFAULTS and cfgm.jig_settings({}) is not jig.JIG_DEFAULTS
    assert cfgm.jig_settings({"jig": {"spring_alpha": 0.5}})["spring_alpha"] == 0.5
    import yaml
    base_cfg = yaml.safe_load(CFG_TEXT)
    v = cfgm.validate_settings(json.loads(json.dumps(base_cfg)))
    assert "jig" not in v                                                         # 절 없음 = cfg 주입 없음(설정 해시 불변)
    good = json.loads(json.dumps(base_cfg))
    good["jig"] = {"tie_dofs": "translation", "methods": ["spring"], "spring_k_mode": "value", "spring_k_value": 2.5e3,
                   "spring_alpha_scan": [0.1, 1.0]}
    assert cfgm.validate_settings(good)["jig"]["methods"] == ["spring"]
    for bad in ({"tie_dofs": "xyz"}, {"methods": []}, {"methods": ["fixed", "fixed"]}, {"methods": ["rigid"]},
                {"spring_alpha": 5e-4}, {"spring_k_mode": "value"}, {"spring_k_value": 0}, {"normal_kink_deg": 0},
                {"aux321_dup_deg": 90}, {"spring_alpha_scan": [1e-4]}, {"aux_reaction_warn": -1}, {"unknown": 1},
                {"min_regions": 9, "max_regions": 8}, {"fix_kinds": ["NOPE"]}, {"knn": 0}):
        c = json.loads(json.dumps(base_cfg))
        c["jig"] = bad
        with pytest.raises(EslError) as ei:
            cfgm.validate_settings(c)
        assert ei.value.code == "CONFIG_INVALID", bad


# ====================================================================== V-10 이름 분기 없음
def test_v10_no_method_or_source_name_branch_in_case_code():
    """Case 지그·검증 지지 코드에 방식·출처·구속 성분 이름 문자열 비교 없음(열 값만 — AGENTS.md)."""
    names = "|".join(list(jig_bc.METHODS) + list(jig_bc.TIE_DOFS) + list(SRCS))
    pat = re.compile(rf"""(==|!=|\bin\b)\s*\(?\s*["']({names})["']""")
    for fn in (pipeline._jig_esl, pipeline._jig_shared, pipeline._jig_method, pipeline._jig_surface, pipeline._sup_jig,
               pipeline._val_solve, pipeline._jig_prep_note, pipeline._jig_bc_text):
        assert not pat.findall(inspect.getsource(fn)), fn.__name__
    for mod in (vs, view3d_src):
        src = inspect.getsource(mod)
        assert not pat.findall(src), mod.__name__
