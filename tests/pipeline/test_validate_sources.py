"""v0.24.3 ④ 검증 출처별(계약 docs/contracts/esl_validate_sources.md §14.1 P1, V-0243-VAL-n).

V-1 골든: 합성 Case 4종(bf = 경계력·내력 자료 있음, plain = 없음, never = ``full_solve: never``, stress = 응력 대체)의
05_val 루트(validation.json — created_at·full_solve.mem_avail 제외, validation.csv·compare.csv·compare_*.npz 배열),
06_export(생성 시각 줄 제외)·07_report(생성 시각·경로 정규화, 출처 표 블록 제외)·단계 요약 기존 키 = v0.24.2 코드 기록값.
골든은 코어 변경 **전**(계약 커밋 d1eb8927 = v0.24.2 검증 코드)에 ``ESL_GOLDEN_RECORD=1`` 로
``tests/fixtures/val_src/golden_v0242.json`` 에 기록했다. 다시 기록하면 안 된다: 깨지면 full 결과가 바뀐 것이다.

npz 는 zip 항목 시각이 들어가 파일 sha 가 실행마다 다르므로 배열(이름·dtype·shape·바이트) 해시로 비교한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil

import numpy as np
import pytest

import synth_case
from esl import pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")
CFG64_TEXT = open(CFG, encoding="utf-8").read().replace("disp_precision: float32", "disp_precision: float64")
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "val_src", "golden_v0242.json")
TAG = "golden-v0243"
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
# 출처 표(v0.24.3 07_report 5절 끝 — case_report 가 이 표식으로 감쌈). 골든 비교 때 떼어 내고 기존 부분만 본다.
_SRC_BLOCK = re.compile(r"<!--val-src-->.*?<!--/val-src-->", re.S)
_VOLATILE_SOLVER = ("assembly_s", "tocsr_s", "factor_s", "rss_peak_mb", "mem_avail_mb")
VAL_FILES = ("validation.json", "validation.csv", "compare.csv", "compare_field.npz", "compare_disp.npz")


def _add_bforce(c, csv_dir, fint_sign=None):
    from test_bforce_stage import _add_bforce as add      # 같은 합성 경계력·내력 CSV(v0.24.0 시험과 같은 자료)
    return add(c, csv_dir, fint_sign=fint_sign)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _norm_text(s: str, root: str) -> str:
    return _TS.sub("<TS>", s.replace(root, "<ROOT>"))


def _npz_hash(path: str) -> str:
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as z:
        for k in z.files:                         # 저장 순서 = 쓴 순서(키 순서도 바이트의 일부)
            a = z[k]
            h.update(f"{k}|{a.dtype.str}|{a.shape}|".encode())
            h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _val_json_hash(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc.pop("created_at", None)
    (doc.get("full_solve") or {}).pop("mem_avail", None)
    return _sha(json.dumps(doc, ensure_ascii=False, indent=1).encode())


def file_hash(path: str, root: str) -> str:
    name = os.path.basename(path)
    if name.endswith(".npz"):
        return _npz_hash(path)
    if name == "validation.json" and os.path.basename(os.path.dirname(path)) == pipeline.D_VAL:
        return _val_json_hash(path)
    with open(path, "rb") as fh:
        b = fh.read()
    if name == "report.html":
        return _sha(_SRC_BLOCK.sub("", _norm_text(b.decode("utf-8"), root)).encode())
    if os.path.basename(os.path.dirname(path)) == pipeline.D_EXPORT:
        return _sha(_norm_text(b.decode("utf-8"), root).encode())
    return _sha(b)


def norm_summary(summ: dict) -> dict:
    """run.json stages.validate.summary 의 v0.24.2 키만(새 키 sources 제외), solver 의 시각·메모리 값 제외."""
    out = {k: v for k, v in summ.items() if k != "sources"}
    sol = json.loads(json.dumps(out.get("solver") or {}))
    for k in _VOLATILE_SOLVER:
        sol.pop(k, None)
    for v in sol.values():
        if isinstance(v, dict):
            for k in _VOLATILE_SOLVER:
                v.pop(k, None)
    out["solver"] = sol
    return json.loads(json.dumps(out))


def snapshot(out: str, root: str) -> dict:
    """05_val 루트 파일(디렉터리·sources.json 제외)·06_export·07_report 해시 + 단계 요약(정규화)."""
    files = {}
    vd = os.path.join(out, pipeline.D_VAL)
    for fn in sorted(os.listdir(vd)):
        p = os.path.join(vd, fn)
        if os.path.isfile(p) and fn != "sources.json":
            files[f"{pipeline.D_VAL}/{fn}"] = file_hash(p, root)
    for sub in (pipeline.D_EXPORT, pipeline.D_REPORT):
        d = os.path.join(out, sub)
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            files[f"{sub}/{fn}"] = file_hash(os.path.join(d, fn), root)
    with open(os.path.join(out, pipeline.RUN_JSON), encoding="utf-8") as fh:
        rj = json.load(fh)
    return {"files": files, "summary": norm_summary(rj["stages"]["validate"]["summary"])}


GOLDEN_CASES = ("bf", "plain", "never", "stress")


@pytest.fixture(scope="module")
def golden_runs(tmp_path_factory):
    """골든 Case 4종을 stage=all 로 실행 → {name: (out, root)}."""
    runs = {}
    for name in GOLDEN_CASES:
        root = str(tmp_path_factory.mktemp(f"vs_{name}"))
        c = synth_case.build(root, source="max_stress" if name == "stress" else "max_strain")
        if name in ("bf", "never"):
            _add_bforce(c, c["csv"], fint_sign=-1.0)
        txt = CFG64_TEXT
        if name == "never":
            assert "full_solve: auto" in txt
            txt = txt.replace("full_solve: auto", "full_solve: never")
        cfg = os.path.join(root, "esl64.yaml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(txt)
        out = os.path.join(root, "out")
        pipeline.run(config_path=cfg, rad=c["rad"], results=c["csv"], out=out, stage="all", frame=synth_case.T_STAR_FRAME,
                     echo=lambda *_: None, tag=TAG)
        runs[name] = {"out": out, "root": root, "c": c, "cfg": cfg}
    return runs


def test_v0243_val_1_golden_full_bytes(golden_runs):
    """V-0243-VAL-1: full 결과(05_val 루트·06_export·07_report 기존 부분·단계 요약 기존 키) = v0.24.2 기록값."""
    cur = {name: snapshot(r["out"], r["root"]) for name, r in golden_runs.items()}
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not os.path.isfile(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump({"recorded_at_commit": "d1eb8927 (= v0.24.2 stage_validate code)", "cases": cur}, fh,
                      ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)["cases"]
    for name in GOLDEN_CASES:
        assert cur[name]["files"] == gold[name]["files"], name
        assert cur[name]["summary"] == gold[name]["summary"], name
    assert set(gold["bf"]["files"]) >= {f"{pipeline.D_VAL}/{f}" for f in VAL_FILES}
    assert f"{pipeline.D_VAL}/compare_disp.npz" not in gold["never"]["files"]


def copy_case(golden_runs, name: str, dst: str) -> dict:
    """골든 Case 산출물 사본(검증만 다시 돌리는 시험용)."""
    r = golden_runs[name]
    out = os.path.join(dst, f"out_{name}")
    shutil.copytree(r["out"], out)
    return {**r, "out": out}
