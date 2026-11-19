"""v0.24.1 스터디 3D — 기존 파일 바이트 불변 + 노드 힘 출처 재현 진단(계약 esl_view3d_sources.md §5.2, V-0241-V3D-13).

골든: v0.24.0(f29eeec0) 코드로 만든 경계력·내력 스터디(test_fint_doe 합성)의 post/view3d/* 파일 sha256(manifest 는 created_at 을 뺀
정규 JSON)을 ``ESL_GOLDEN_RECORD=1`` 로 ``tests/fixtures/view3d/doe_view3d_v0240.json`` 에 기록했다. 풀이(SuperLU) 결과에 의존하므로
같은 환경 서명(numpy·scipy·플랫폼)에서만 바이트를 비교하고, 다른 환경에서는 같은 실행 안의 recon 끔/켬 대조(V-13 나머지)로 대신한다.
"""
import hashlib
import json
import os
import platform

import numpy as np
import pytest
import scipy
import test_fint_doe as FD
import test_jig_stages as T

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "view3d", "doe_view3d_v0240.json")


def env_sig() -> str:
    return f"{platform.system()}-{platform.machine()}-numpy{np.__version__}-scipy{scipy.__version__}"


def view3d_hashes(out: str, names=None) -> dict[str, str]:
    """post/view3d/<폴더>/<파일> → sha256. manifest.json 은 created_at 을 뺀 정규 JSON."""
    base = os.path.join(out, "post", "view3d")
    res = {}
    for d in sorted(os.listdir(base)):
        for f in sorted(os.listdir(os.path.join(base, d))):
            rel = f"{d}/{f}"
            if names is not None and rel not in names:
                continue
            p = os.path.join(base, d, f)
            if f == "manifest.json":
                m = json.load(open(p, encoding="utf-8"))
                m.pop("created_at", None)
                b = json.dumps(m, sort_keys=True, ensure_ascii=False).encode()
            else:
                b = open(p, "rb").read()
            res[rel] = hashlib.sha256(b).hexdigest()
    return res


def run_study(t, recon=None):
    mesh, doe = FD._setup(t)
    if recon is not None:
        bd = doe["cfg"]["bead_doe"]
        doe = {**doe, "cfg": {**doe["cfg"], "bead_doe": {**bd, "view3d": {**(bd.get("view3d") or {}), "recon": recon}}}}
    rank = T.rank_snap(eval_region=FD.EV)
    out, _post, ids = T.run(str(t / "o"), doe, mesh, rank=rank)
    return out, ids


@pytest.fixture(scope="module")
def vrun(tmp_path_factory):
    out, ids = run_study(tmp_path_factory.mktemp("v3dr"))
    return {"out": out, "ids": ids}


def test_existing_view3d_files_equal_v0240_golden(vrun):
    cur = view3d_hashes(vrun["out"])
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not os.path.isfile(GOLDEN):
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump({"recorded_at_commit": "f29eeec0 (= v0.24.0 study view3d)", "env": env_sig(), "files": cur}, fh,
                      indent=1, sort_keys=True)
            fh.write("\n")
    gold = json.load(open(GOLDEN, encoding="utf-8"))
    assert set(gold["files"]) <= set(cur)                                     # 옛 파일은 모두 그대로 있음(새 파일만 더함)
    if gold["env"] != env_sig():
        pytest.skip(f"환경 서명이 골든과 다름({env_sig()} ≠ {gold['env']}) — recon 끔/켬 대조 시험으로 대신")
    assert {k: cur[k] for k in gold["files"]} == gold["files"]
