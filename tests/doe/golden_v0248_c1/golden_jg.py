"""V-0248-JG-11 골든(v0.24.7 머지 헤드 main 6030b213 코드로 기록 — 다시 기록 금지, 계약 esl_jig_grid_map.md §7.3·§9-11).
옛 스냅샷(rank.jig_grid 없음)의 ④ 형상 직접 비교·옛 ③(scenario step) 산출물 바이트: result.json·ranking.csv·per_esl.json·designs.json·
report.html·안 result.json·done.json(input_sha256)·prep 전부. 세계 = tests/doe/synth_jig_grid.py(④ 메시 입력 형상, 옛 ③ 가짜 gmsh).

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0248_c1/golden_jg.py (v0.24.7 머지 헤드 코드에서만).
JSON = 시간 키(seconds*·elapsed*·created_at·time_s)를 뺀 정규 바이트 sha256, npz = 배열(키·dtype·shape·바이트) sha256, 그 밖 원 바이트."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
DOE_T = os.path.dirname(HERE)
if DOE_T not in sys.path:
    sys.path.insert(0, DOE_T)

VOLATILE = ("seconds", "elapsed", "created_at", "time_s", "wall_seconds")
SKIP_DIRS = ("/view3d/",)          # 3D 폴더는 manifest 경로 외 바이트 동일 — 아래에서 따로(목록만)
TS_RE = re.compile(r"\d{8}T\d{6}")


VOLATILE_EXACT = ("at",)          # done.json 완료 시각


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items()
                if k not in VOLATILE_EXACT and not any(str(k).startswith(p) for p in VOLATILE)}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _npz_sha(p: str) -> str:
    h = hashlib.sha256()
    with zipfile.ZipFile(p) as zf:
        for n in sorted(zf.namelist()):
            if n.endswith("_meta.npy"):                          # W 캐시 meta = (최대 거리, newton 폴백 수, 시간) — 시간 제외
                a = np.load(io.BytesIO(zf.read(n)), allow_pickle=False)[:2]
                h.update(f"{n}|{a.dtype.str}|".encode())
                h.update(np.ascontiguousarray(a).tobytes())
                continue
            a = np.load(io.BytesIO(zf.read(n)), allow_pickle=False)
            h.update(f"{n}|{a.dtype.str}|{a.shape}|".encode())
            h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def file_sha(p: str, root: str) -> str:
    if p.endswith(".npz"):
        return _npz_sha(p)
    b = open(p, "rb").read()
    if p.endswith(".json"):
        try:
            b = json.dumps(_strip(json.loads(b)), sort_keys=True, ensure_ascii=True).encode()
        except ValueError:
            pass
    b = b.replace(root.encode(), b"<ROOT>")
    b = re.sub(rb"[0-9]+\.[0-9]+ ?s\b", b"<S>", b) if p.endswith(".html") else b
    return hashlib.sha256(b).hexdigest()


SCENE_NEW = ("post/view3d_scene/", "post/scene_view.json")   # v0.25.1 새 파일(계약 esl_view3d_scene_legend.md §7.2 — 옛 골든 비교 밖, V-0251-10 이 확인)


def tree_sha(out: str, root: str, scene: bool = False) -> dict:
    res = {}
    for dp, dn, fns in os.walk(out):
        dn[:] = sorted(d for d in dn if d not in ("_backup", "logs"))
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            if fn.endswith((".log", ".lock", ".tmp")) or fn.startswith(".") or (not scene and rel.startswith(SCENE_NEW)):
                continue
            res[rel] = file_sha(p, root)
    return dict(sorted(res.items()))


def compute(case: str, tmp: str, monkeypatch=None) -> dict:
    import synth_jig_grid as G
    if case == "cmp_old":
        doe, out, _A = G.cmp_world(tmp, rank=G.rank_snap())
        G.run_cmp(doe, out)
    elif case == "cmp_norank":
        doe, out, _A = G.cmp_world(tmp, rank=None)
        G.run_cmp(doe, out)
    elif case == "step_old":
        doe, out, A = G.step_world(tmp, rank=G.rank_snap())
        with G.fake_gmsh(monkeypatch):
            G.run_step(doe, out, A)
    else:
        raise KeyError(case)
    return tree_sha(out, tmp)


CASES = ("cmp_old", "cmp_norank", "step_old")


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _record():
    import shutil
    import tempfile

    import pytest
    got = {}
    for case in CASES:
        runs = []
        for _ in range(2):                                       # 같은 코드 두 번 = 결정적인 파일만 골든에
            tmp = tempfile.mkdtemp(prefix=f"g0248_{case}_")
            with pytest.MonkeyPatch.context() as mp:
                runs.append(compute(case, tmp, mp))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = runs
        unstable = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        got[case] = {k: v for k, v in a.items() if k not in unstable}
        got.setdefault("_unstable", {})[case] = unstable
        print(case, len(a), "files", "unstable", unstable)
    doc = {"made_by": "tests/doe/golden_v0248_c1/golden_jg.py (main 6030b213 + v0.24.8 계약 f0718dd9 — 코드 변경 전)",
           "cases": {k: v for k, v in got.items() if k != "_unstable"}, "unstable": got["_unstable"]}
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        raise SystemExit("ESL_GOLDEN_RECORD=1 로만 기록(옛 코드에서)")
    _record()
