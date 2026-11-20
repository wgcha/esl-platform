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
    with open(os.path.join(ROOT, "config", "esl.example.yaml"), encoding="utf-8") as fh:
        txt = fh.read().replace("disp_precision: float32", "disp_precision: float64")
    cfg = os.path.join(root, "esl64.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    out = os.path.join(root, "out")
    pipeline.run(config_path=cfg, rad=c["rad"], results=c["csv"], out=out, stage="all", frame=synth_case.T_STAR_FRAME,
                 echo=lambda *_: None, tag="golden-v0243-jig")
    return out, root


def case_snapshot(out: str, root: str) -> dict[str, str]:
    return tree_hashes(out, root, lambda rel: rel.split("/")[0] in ("03_bc", "04_esl", "05_val", "06_export",
                                                                    "07_report"))


@pytest.fixture(scope="module")
def golden_runs(tmp_path_factory):
    t = tmp_path_factory.mktemp("jigmove")
    (t / "s").mkdir()
    (t / "c").mkdir()
    out, _post, _ids = run_study(t / "s")
    cout, croot = run_case(t / "c")
    return {"study": study_snapshot(out, str(t)), "case": case_snapshot(cout, croot)}


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
        assert set(gold[k]) == set(cur[k]), k                                     # 파일 목록(새 파일 없음 — P2a)
    assert {"prep/jig.json", "prep/jig.npz", "post/jig_view.json", "post/ranking.csv"} <= set(gold["study"])
    assert any("jigdiag" in k for k in gold["study"]) and any(k.endswith("_jig/values.bin") for k in gold["study"])
    assert {"04_esl/f_eq.npz", "04_esl/bforce.npz", "04_esl/fint.npz", "05_val/sources.json"} <= set(gold["case"])
    if gold["env"] != env_sig():
        pytest.skip(f"환경 서명이 골든과 다름({env_sig()} ≠ {gold['env']})")
    for k in ("study", "case"):
        diff = sorted(f for f in gold[k] if gold[k][f] != cur[k][f])
        assert not diff, (k, diff)
