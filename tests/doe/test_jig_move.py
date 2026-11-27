"""v0.24.4 P2a 지그 공용 모듈 이동(계약 docs/contracts/esl_jig_case.md §4.1·§13 V-0244-JIG-1).

골든: 코어 변경 **전**(계약 커밋 413620c1 = v0.24.3 코드)에 ``ESL_GOLDEN_RECORD=1`` 로
``tests/fixtures/jig_case/golden_v0243.json`` 에 기록했다. 다시 기록하면 안 된다: 깨지면 옛 스냅샷 지그 결과가 바뀐 것이다.

- ``study``: 합성 지그 스터디(test_jig_stages.build_same — 인접 쉘·솔리드 접촉 영역 2개, tie 8노드) 를 **옛 스냅샷**
  (rank.jig = v0.24.3 키만 — LEGACY_ABSENT = translation·fixed)으로 돌린 prep/jig.json(``seconds*`` 제외)·jig.npz(배열 해시)·
  안 result.json·design.npz·post/per_esl.json·ranking.csv·jig_view.json(rank_views jig 포함)·result.json(지그 블록 포함)·
  지그 3D·지그 진단 3D(post/view3d/*jig*).
- ``case``: 합성 Case(경계력·내력 자료 있음, stage=all) 의 03_bc·04_esl·05_val 전부·06_export·07_report — P2b(Case 지그)가
  full·bforce·fint 산출 바이트 불변을 확인할 때 쓰는 기록(P2a 는 파이프라인을 바꾸지 않으므로 전부 같아야 함).

npz 는 zip 항목 시각이 들어가 파일 sha 가 실행마다 다르므로 배열(이름·dtype·shape·바이트) 해시로 비교한다. JSON 은 시각·
시간·메모리 값(``VOLATILE``)을 빼고 임시 폴더 경로를 ``<ROOT>`` 로 바꾼 정규 JSON 의 sha256. 풀이(SuperLU) 결과에 의존하므로
같은 환경 서명(numpy·scipy·플랫폼)에서만 바이트를 비교한다(다른 환경 = skip, 파일 목록만 비교).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import platform
import re
import subprocess
import sys

import numpy as np
import pytest
import scipy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tests", "pipeline"))
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "jig_case", "golden_v0243.json")

# v0.24.3 bead_doe.rank.jig(= 옛 스냅샷 키 집합, 변경 전 DEFAULTS["rank"]["jig"] 값 — V-1 "옛 키 값 = 변경 전")
OLD_JIG = {"enabled": True, "fix_kinds": ["INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"], "contact_gap_mm": 2.0,
           "knn": 8, "chunk_nodes": 65536, "max_surf_tris": 20000000, "max_regions": 8, "min_regions": 2,
           "min_region_nodes": 3, "min_region_area_mm2": 25.0, "patch_count": 6, "body_force": True,
           "basis_tangential": True, "n_modes": 4, "rho_t_mm3": 7.85e-9, "modes_sigma": 0.0, "modes_tol": 1e-8,
           "modes_maxiter": 2000, "modes_ref321": False, "w_inplane": 0.1, "reg_force": 1e-3, "reg_modes": 0.0,
           "ridge": 1e-8, "active_tol": 1e-3, "mac_min": 0.9, "umax_err_max": 0.2, "tie_rel_warn": 0.1,
           "cancel_warn": 0.5, "work_eff_min": 0.05, "tie_spread_min": 0.02}

VOLATILE = {"created_at", "assembly_s", "tocsr_s", "factor_s", "solve_s", "eval_s", "rss_peak_mb", "mem_avail_mb",
            "mem_avail"}
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def env_sig() -> str:
    return f"{platform.system()}-{platform.machine()}-numpy{np.__version__}-scipy{scipy.__version__}"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _strip(o, root: str):
    if isinstance(o, dict):
        return {k: _strip(v, root) for k, v in o.items() if k not in VOLATILE and not k.startswith("seconds")}
    if isinstance(o, list):
        return [_strip(v, root) for v in o]
    if isinstance(o, str):
        return _TS.sub("<TS>", o.replace(root, "<ROOT>"))
    return o


def npz_hash(path: str) -> str:
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as z:
        for k in z.files:                         # 저장 순서 = 쓴 순서(키 순서도 바이트의 일부)
            a = z[k]
            h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
            h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def file_hash(path: str, root: str) -> str:
    if path.endswith(".npz"):
        return npz_hash(path)
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return _sha(json.dumps(_strip(doc, root), ensure_ascii=False, sort_keys=True).encode())
    with open(path, "rb") as fh:
        b = fh.read()
    if path.endswith((".html", ".inc", ".fem", ".csv")):
        try:
            return _sha(_TS.sub("<TS>", b.decode("utf-8").replace(root, "<ROOT>")).encode())
        except UnicodeDecodeError:
            pass
    return _sha(b)


def tree_hashes(base: str, root: str, keep=None) -> dict[str, str]:
    out = {}
    for d, _dirs, files in os.walk(base):
        for f in files:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            if keep is None or keep(rel):
                out[rel] = file_hash(p, root)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- 합성 실행
def run_study(t):
    import test_jig_stages as T
    mesh, doe = T.build_same(t)
    out, post, ids = T.run(str(t / "o"), doe, mesh, rank=T.rank_snap(jig=copy.deepcopy(OLD_JIG)))
    return out, post, ids


def study_snapshot(out: str, root: str) -> dict[str, str]:
    def keep(rel: str) -> bool:
        if rel in ("prep/jig.json", "prep/jig.npz", "post/per_esl.json", "post/ranking.csv", "post/jig_view.json",
                   "post/result.json"):
            return True
        if rel.startswith("run/designs/") and rel.endswith(("/result.json", "/design.npz")):
            return True
        return rel.startswith("post/view3d/") and "jig" in rel.split("/")[2]
    return tree_hashes(out, root, keep)


def run_case(t):
    import synth_case
    from test_bforce_stage import _add_bforce

    from esl import pipeline

    root = str(t)
    c = synth_case.build(root, source="max_strain")
    _add_bforce(c, c["csv"], fint_sign=-1.0)
    import vt_golden

    txt = vt_golden.cfg_text()      # 예시 yaml(float64) + disp_rms_rel_max 0.01(골든 기록 당시 예시 값 — v0.24.5 0.05)
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    out = os.path.join(root, "out")
    pipeline.run(config_path=cfg, rad=c["rad"], results=c["csv"], out=out, stage="all", frame=synth_case.T_STAR_FRAME,
                 echo=lambda *_: None, tag="golden-v0243-jig")
    return out, root


def case_snapshot(out: str, root: str) -> dict[str, str]:
    """v0.24.5(esl_validate_tiers.md §5-6): 05_val 문서·validation.csv·보고서는 판정 단계·MAC 의도 차이를 ``vt_compat`` 로
    v0.24.4 형식으로 되돌린 뒤 해시(보고서 = 되돌린 문서로 다시 그린 것 — 현재 VAL_PLAN 으로)."""
    import vt_compat as VC

    h = tree_hashes(out, root, lambda rel: rel.split("/")[0] in ("03_bc", "04_esl", "05_val", "06_export",
                                                                 "07_report"))
    vd = os.path.join(out, "05_val")
    for rel in list(h):
        p = os.path.join(out, rel)
        name = os.path.basename(rel)
        if rel.startswith("05_val/") and name == "validation.json":
            with open(p, encoding="utf-8") as fh:
                doc = VC.back_validation(json.load(fh))
            h[rel] = _sha(json.dumps(_strip(doc, root), ensure_ascii=False, sort_keys=True).encode())
        elif rel == "05_val/sources.json":
            with open(p, encoding="utf-8") as fh:
                doc = VC.back_sources(json.load(fh), vd)
            h[rel] = _sha(json.dumps(_strip(doc, root), ensure_ascii=False, sort_keys=True).encode())
        elif name == "validation.csv":
            with open(p, encoding="utf-8", newline="") as fh:
                t = VC.back_csv(fh.read(), p, out)
            h[rel] = _sha(_TS.sub("<TS>", t.replace(root, "<ROOT>")).encode())
        elif rel == "07_report/report.html":
            t = VC.back_report_html(out)
            if t is not None:
                h[rel] = _sha(_TS.sub("<TS>", t.replace(root, "<ROOT>")).encode())
    return h


# v0.24.4 P2b(esl_jig_case.md §12-6 의도 변경): 검증 출처 표 KEYS 6(지그 3방식 행) → 05_val/sources.json(행 목록)·07_report(출처별 판정 표)만
# 바뀜. 같은 새 코드(Case _jig_esl·검증 묶음 키·지지 집합)를 v0.24.3 출처 표(VAL_PLAN 4행·jig 이름)로 돌린 실행 = 골든 전부(아래
# old_plan_case) → 새 실행의 차이는 출처 표 행뿐임을 확인한다.
CASE_PLAN_CHANGED = ("05_val/sources.json", "07_report/report.html")
OLD_JIG_VAL_ROW = {"key": "jig", "legacy": False, "load": None, "required": False, "load_frame": None, "balance": None,
                   "support": None, "reaction_role": None, "reaction_tol_key": None, "reaction_warn_key": None,
                   "target": None, "rigid": "linear", "resp": "solve", "fallback": None, "noise_force": False,
                   "summary": None, "doc": None, "limits": None, "dir": None, "na": "V3D_STUDY_ONLY", "note": None}


def run_case_old_plan(t):
    """v0.24.3 출처 표(VAL_PLAN = 옛 jig 행 + full·bforce·fint, 보고서 이름 '지그 ESL')로 새 코드 실행 → (out, root, 스냅샷 —
    같은 옛 출처 표 안에서 계산: 보고서 되돌림 재생성도 옛 표로)."""
    from esl import val_src
    old = (OLD_JIG_VAL_ROW, *(r for r in val_src.VAL_PLAN if r["key"] in ("full", "bforce", "fint")))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(val_src, "VAL_PLAN", old)
        mp.setitem(val_src.LABEL, "jig", "지그 ESL")
        out, root = run_case(t)
        return out, root, case_snapshot(out, root)


@pytest.fixture(scope="module")
def golden_runs(tmp_path_factory):
    t = tmp_path_factory.mktemp("jigmove")
    (t / "s").mkdir()
    (t / "c").mkdir()
    (t / "o").mkdir()
    out, _post, _ids = run_study(t / "s")
    cout, croot = run_case(t / "c")
    _oout, _oroot, osnap = run_case_old_plan(t / "o")
    return {"study": study_snapshot(out, str(t)), "case": case_snapshot(cout, croot), "case_old_plan": osnap}


# v0.25.1(계약 esl_view3d_scene_legend.md V-0251-10 개정·§5.9 INT): 새로 만든 report.html 은 색·범례 문구만 바뀜 — 바이트 비교에서 뺌
# (파일 목록에는 그대로 있어야 함, 색 외 내용 = V-0251-43·44). 다른 파일 바이트 비교는 그대로.
PICTURE_V0251 = ("report.html",)


def test_v0244_jig_1_golden_bytes(golden_runs):
    """V-0244-JIG-1: 옛 스냅샷 스터디 지그 결과·Case 산출물 = v0.24.3 코드 기록값(모듈 이동·shell 추가 후에도)."""
    cur = golden_runs
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not os.path.isfile(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump({"recorded_at_commit": "413620c1 (= v0.24.3 jig·pipeline code)", "env": env_sig(),
                       "study": cur["study"], "case": cur["case"]}, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)
    for k in ("study", "case"):
        assert set(gold[k]) == set(cur[k]), k                                     # 파일 목록(새 파일 없음 — tie 준비 없는 Case)
    assert set(gold["case"]) == set(cur["case_old_plan"])
    assert {"prep/jig.json", "prep/jig.npz", "post/jig_view.json", "post/ranking.csv"} <= set(gold["study"])
    assert any("jigdiag" in k for k in gold["study"]) and any(k.endswith("_jig/values.bin") for k in gold["study"])
    assert {"04_esl/f_eq.npz", "04_esl/bforce.npz", "04_esl/fint.npz", "05_val/sources.json"} <= set(gold["case"])
    if gold["env"] != env_sig():
        pytest.skip(f"환경 서명이 골든과 다름({env_sig()} ≠ {gold['env']})")
    diff = sorted(f for f in gold["study"] if gold["study"][f] != cur["study"][f] and not f.endswith(PICTURE_V0251))
    assert not diff, ("study", diff)                                          # 옛 스냅샷 스터디(RANK_SOURCES 2행 추가 후에도)
    diff = sorted(f for f in gold["case"] if gold["case"][f] != cur["case_old_plan"][f] and not f.endswith(PICTURE_V0251))
    assert not diff, ("case_old_plan", diff)                                  # 새 코드 + 옛 출처 표 = 골든 전부
    diff = sorted(f for f in gold["case"] if gold["case"][f] != cur["case"][f])   # report.html 은 원래 의도 차이 목록에 있음
    assert diff == sorted(CASE_PLAN_CHANGED), ("case", diff)                  # 새 출처 표: 의도된 2파일만(04_esl·05_val 루트·full 등 불변)


# ---------------------------------------------------------------- V-0244-JIG-1 심·import 그래프·DEFAULTS
def _public_and_used(mod) -> list[str]:
    return [k for k, v in vars(mod).items() if not k.startswith("__")]


def test_v0244_jig_1_shims_same_objects():
    import importlib

    import esl.doe.assem_full as af
    import esl.doe.paicad_io as pio
    import esl.io.fixed_scan as fs
    import esl.mech.jig as mj
    import esl.rad.solid_faces as sf
    import esl.rad.surface as rs
    from esl.doe import jig, jig_surf

    assert jig is mj and jig_surf is rs                                       # 모듈 객체 자체(monkeypatch 포함 같은 객체)
    assert importlib.import_module("esl.doe.jig") is mj and importlib.import_module("esl.doe.jig_surf") is rs
    for k in _public_and_used(mj):
        assert getattr(jig, k) is getattr(mj, k), k
    for k in ("SCAN_JSON", "FIXED_NPZ", "FIXED_KINDS", "read_fixed", "read_json_limited"):
        assert getattr(pio, k) is getattr(fs, k), k
    for k in ("ELEM_NODES", "ELEM_TOTAL", "SHELL_KW", "SOLID_FACES", "_HEX", "_TET", "_PEN", "_lead_ints", "_faces", "_clean"):
        assert getattr(af, k) is getattr(sf, k), k
    assert rs.af is sf                                                        # 표면 읽기 = 이동한 면 계산


def test_v0244_jig_1_shim_sources_pure():
    """심 파일은 본체 import + 별칭 1줄뿐(esl.doe·파일 IO 없음 — V-JIG-15 와 같은 규칙)."""
    for rel, target in (("esl/doe/jig.py", "esl.mech.jig"), ("esl/doe/jig_surf.py", "esl.rad.surface")):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert mods == {target}, rel
        assert not any(isinstance(n, ast.Import) for n in ast.walk(tree))


def test_v0244_jig_1_import_graph_no_esl_doe():
    """esl.pipeline·esl.mech.*·esl.rad.*·esl.io.*·esl.val_src·esl.view3d_src → esl.doe 0(새 프로세스)."""
    code = ("import sys, pkgutil, importlib, esl.mech, esl.rad, esl.io\n"
            "mods = ['esl.pipeline', 'esl.val_src', 'esl.view3d_src']\n"
            "for pkg in (esl.mech, esl.rad, esl.io):\n"
            "    mods += [pkg.__name__ + '.' + m.name for m in pkgutil.iter_modules(pkg.__path__)]\n"
            "for m in mods:\n"
            "    importlib.import_module(m)\n"
            "assert 'esl.mech.jig' in mods and 'esl.rad.surface' in mods and 'esl.io.fixed_scan' in mods\n"
            "bad = [m for m in sys.modules if m.startswith('esl.doe')]\n"
            "print(','.join(bad))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False,
                       env={**os.environ, "PYTHONPATH": ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_v0244_jig_1_defaults_old_keys_unchanged():
    """DEFAULTS["rank"]["jig"] 의 옛 키 값 = 변경 전, JIG_DEFAULTS 의 같은 이름 = 같은 값(거울), 새 키 = JIG_NEW_KEYS."""
    from esl.doe import DEFAULTS
    from esl.mech import jig as mj

    dj = DEFAULTS["rank"]["jig"]
    assert {k: dj[k] for k in OLD_JIG} == OLD_JIG
    assert {k: mj.JIG_DEFAULTS[k] for k in dj} == dj                          # 거울(새 키는 B2 가 pydantic·yaml 과 함께 더함)
    assert {k: mj.JIG_DEFAULTS[k] for k in OLD_JIG} == OLD_JIG
    assert set(mj.JIG_DEFAULTS) - set(OLD_JIG) == set(mj.JIG_NEW_KEYS)
    assert mj.hash_view(OLD_JIG) == {k: v for k, v in OLD_JIG.items() if k not in mj.HASH_EXCLUDE}   # 옛 해시 불변


def test_v0244_jig_1_messages_same_source_as_study():
    from esl.doe import load_messages
    from esl.doe import stages as stg
    from esl.io import messages as msg

    assert msg.messages() == load_messages()["messages"]
    for code, kw in (("JIG_REGION_FALLBACK", {"reason": "few_contact", "n_contact": 1, "n_patch": 2}),
                     ("JIG_FAILED", {"stage": "basis"}), ("JIG_AUX_REACTION", {"aux_reaction_rel": 0.1,
                                                                              "aux_reaction_warn": 0.05}),
                     ("NO_SUCH_CODE", {})):
        assert msg.text(code, **kw) == stg._cmp_text(code, **kw)
    for code in ("JIG_DISABLED", "JIG_NOT_PREPARED", "JIG_FIXED_SKIPPED", "JIG_FIXED_FAILED", "JIG_FAILED",
                 "JIG_METHOD_NOT_RUN", "JIG_AUX_REACTION", "JIG_DISP_FROM_TARGET"):
        assert msg.template(code) != code, code
