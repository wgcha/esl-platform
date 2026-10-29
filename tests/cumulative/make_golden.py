"""V-CI-B1 골든 생성(v0.7.2 코드에서 1회 실행해 tests/fixtures/cumulative/golden_v072.json 을 만든 도구).

사용: python tests/cumulative/make_golden.py <작업 폴더> <출력 json>
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(REPO, "tests", "pipeline"), HERE, REPO]

import golden_util  # noqa: E402
import synth_case  # noqa: E402
from esl import cli  # noqa: E402

V072_YAML = os.path.join(REPO, "tests", "fixtures", "cumulative", "esl_v072.yaml")


def run_case(root: str) -> dict:
    c = synth_case.build(root)
    cfg = os.path.join(root, "esl64.yaml")
    with open(V072_YAML, encoding="utf-8") as fh:
        txt = fh.read().replace("disp_precision: float32", "disp_precision: float64")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(txt)
    out = os.path.join(root, "out")
    rc = cli.main(["run", "--config", cfg, "--rad", c["rad"], "--results", c["csv"], "--out", out, "--stage", "all"])
    assert rc == 0, rc
    return golden_util.digest(out, root)


if __name__ == "__main__":
    d = run_case(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump({"env": golden_util.env_key(), "files": d}, fh, indent=1, sort_keys=True)
