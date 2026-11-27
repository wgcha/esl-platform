"""V-0252-2·10 골든(계약 esl_tstar_manual_jig_force.md §8.2·§10 — release/v0.25.1 393789a8 코드, 코드 변경 전에 기록 — 다시 기록 금지).

A 불변(V-0252-2): 합성 Case(tests/pipeline/synth_case) 를 자동 t*(pipe_auto)·후보 선택 --frame 3(pipe_cand)으로 끝까지 →
02_tstar·03_bc·04_esl·05_val·06_export·07_report 파일 해시(vt_golden.file_hash — JSON 시각·시간 키 제외 정규, npz 배열, 텍스트 루트·
시각 치환) 가 기록과 같음.
B·C 불변(V-0252-10·19): golden_v0251_c1 세계 6개(① same·지그 3방식, ③ case_once, 옛 ③, ④ LT·격자 지그 — 스냅샷에 tie_force 없음)
를 끝까지 → 스터디 출력 전부(golden_pu.tree_sha — report.html·그림 포함, 씬 포함) 가 기록과 같음.

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0252_c1/golden_tm.py [사례…] (393789a8 코드에서만 — git archive 로 푼 트리).
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
DOE_T = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(DOE_T))
PIPE_T = os.path.join(ROOT, "tests", "pipeline")
for p in (DOE_T, os.path.join(DOE_T, "golden_v0251_c1"), os.path.join(DOE_T, "golden_v0249_c1"),
          os.path.join(DOE_T, "golden_v0248_c1"), PIPE_T, os.path.join(ROOT, "packages", "beadgraph", "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

PIPE_CASES = ("pipe_auto", "pipe_cand")
DOE_CASES = ("same_lt", "same_all6", "sel_case_jig", "step_old", "cmp_lt", "cmp_grid")
CASES = PIPE_CASES + DOE_CASES
PIPE_DIRS = ("02_tstar", "03_bc", "04_esl", "05_val", "06_export", "07_report")
CAND_FRAME = 3                         # synth_case.SECOND_PEAK_FRAME — 두 번째 후보(D 안)


def pipe_cfg_text() -> str:
    """예시 yaml(float64) — v0.25.2 새 선택 키(tstar.manual_ratio_warn) 줄은 뺀다(기록 때 없던 키 → 설정 같음)."""
    with open(os.path.join(ROOT, "config", "esl.example.yaml"), encoding="utf-8") as fh:
        t = fh.read()
    t = t.replace("disp_precision: float32", "disp_precision: float64")
    return "".join(ln for ln in t.splitlines(keepends=True) if "manual_ratio_warn" not in ln)


def run_pipe(tmp: str, frame: int | None) -> str:
    import synth_case

    from esl import pipeline
    ex = synth_case.build(tmp)
    cfgp = os.path.join(tmp, "cfg.yaml")
    with open(cfgp, "w", encoding="utf-8") as fh:
        fh.write(pipe_cfg_text())
    out = os.path.join(tmp, "case")
    pipeline.run(config_path=cfgp, rad=ex["rad"], results=ex["csv"], out=out, stage="all", frame=frame,
                 echo=lambda s: None, tag="golden-v0252")
    return out


def pipe_sha(out: str, root: str) -> dict:
    import vt_golden as VG
    res = {}
    for sub in PIPE_DIRS:
        base = os.path.join(out, sub)
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(d for d in dns if d not in ("_backup",))
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                res[os.path.relpath(p, out).replace(os.sep, "/")] = VG.file_hash(p, root)
    return dict(sorted(res.items()))


def compute(case: str, tmp: str, mp) -> dict:
    if case in PIPE_CASES:
        out = run_pipe(tmp, None if case == "pipe_auto" else CAND_FRAME)
        return pipe_sha(out, tmp)
    import golden_vl as GV
    from golden_pu import tree_sha
    return tree_sha(GV.compute_out(case, tmp, mp), tmp, scene=True)


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _record():
    import shutil
    import tempfile

    import pytest
    only = [c for c in sys.argv[1:] if c in CASES] or list(CASES)
    doc = load() if os.path.isfile(GOLDEN) else {"cases": {}, "unstable": {}}
    for case in only:
        runs = []
        for _ in range(2):                                       # 같은 코드 두 번 = 결정적인 파일만 골든에
            tmp = tempfile.mkdtemp(prefix=f"g0252_{case}_")
            with pytest.MonkeyPatch.context() as mp:
                runs.append(compute(case, tmp, mp))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = runs
        uns = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        doc["cases"][case] = {k: v for k, v in a.items() if k not in uns}
        doc["unstable"][case] = uns
        print(case, len(a), "files", "unstable", uns, flush=True)
        doc["made_by"] = "tests/doe/golden_v0252_c1/golden_tm.py (release/v0.25.1 393789a8 — v0.25.2 코드 변경 전)"
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    _ = re


if __name__ == "__main__":
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        raise SystemExit("ESL_GOLDEN_RECORD=1 로만 기록(옛 코드에서)")
    sys.path.insert(0, ROOT)
    _record()
