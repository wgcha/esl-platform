"""V-0249-PU-9·15 골든(release/v0.24.9 3609c921 = release/v0.24.8 4b9bf7e4 + v0.24.9 계약, 코드 변경 전에 기록 — 다시 기록 금지).

- cases: `pos_u` 블록 없는 스냅샷의 그래프 select 스터디 전 산출물(prep·select·doe·run·post·view3d·done.json input_sha256)
  · sel_case_jig: 새 ③ case_once(기준 Case rad + 이웃 부품 + fixed-scan tie) · 지그 순위(새 스냅샷 기본 방식 jd·js) · D 변수
  · sel_step_jig: 새 ③ step_once(gmsh 대신 합성 판, A Case fixed-scan → fixed_transfer) · 지그 순위 · D 변수
- package: 패키지 graph.json 바이트(h5·stepboss·h6) + D·W·DF·W1 기저 바이트(전 세그먼트, W1 = one_side ok 세그먼트).

v0.24.9 BM(계약 §10.2): 3D manifest.json 의 supports 행에 kind·dirs·val 이 더해진다 — 기존 키(node_id·vertex·dof·x0) 값·행 수·순서는
불변이어야 하므로 비교는 supports 행에서 그 세 키를 뺀 정규 바이트로 한다(``BM_NEW_KEYS``).

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0249_c1/golden_pu.py (3609c921 코드에서만).
JSON = 시간 키를 뺀 정규 바이트 sha256, npz = 배열(키·dtype·shape·바이트) sha256, 그 밖 원 바이트(작업 폴더 경로 = <ROOT>)."""
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
ROOT = os.path.dirname(os.path.dirname(DOE_T))
for p in (DOE_T, os.path.join(ROOT, "packages", "beadgraph", "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

VOLATILE = ("seconds", "elapsed", "created_at", "time_s", "wall_seconds")
VOLATILE_EXACT = ("at",)
BM_NEW_KEYS = ("kind", "dirs", "val")       # v0.24.9 §10.2 지지 표식 새 필드(manifest supports 행) — 비교에서 뺌


def _strip(o, sup=False):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in VOLATILE_EXACT or any(str(k).startswith(p) for p in VOLATILE):
                continue
            if sup and k in BM_NEW_KEYS:
                continue
            out[k] = _strip(v, sup=(k == "supports"))
        return out
    if isinstance(o, list):
        return [_strip(v, sup=sup) for v in o]
    return o


def _npz_sha(p: str) -> str:
    h = hashlib.sha256()
    with zipfile.ZipFile(p) as zf:
        for n in sorted(zf.namelist()):
            a = np.load(io.BytesIO(zf.read(n)), allow_pickle=False)
            if n.endswith("_meta.npy"):                          # W 캐시 meta 시간 열 제외
                a = a[:2]
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
    if p.endswith(".html"):
        b = re.sub(rb"[0-9]+\.[0-9]+ ?s\b", b"<S>", b)
    return hashlib.sha256(b).hexdigest()


def tree_sha(out: str, root: str) -> dict:
    res = {}
    for dp, dn, fns in os.walk(out):
        dn[:] = sorted(d for d in dn if d not in ("_backup", "logs"))
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            if fn.endswith((".log", ".lock", ".tmp")) or fn.startswith("."):
                continue
            res[rel] = file_sha(p, root)
    return dict(sorted(res.items()))


# ---------------------------------------------------------------- 세계
SPEC = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 3.0, "hi": 7.0}]}


def _run_select(doe: dict, out: str, before_loads=None) -> None:
    from esl.doe import bead_auto as ba
    from esl.doe import stages as stg
    from esl.library import _util as U

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, lambda s: None)
    run("bd_input")
    if doe.get("select_base") == "step":
        run("bd_mesh0")
    if before_loads is not None:
        before_loads(out)
    run("bd_loads")
    auto = U.read_json(os.path.join(out, "prep", "select", ba.AUTO_SELECTION_JSON))
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": auto["selection"]}
    run("bd_matrix", rev=1, spec=SPEC)
    for x in U.read_json(os.path.join(out, "doe", "1", "matrix.json"))["designs"]:
        r = run("bd_eval", rev=1, design=x["id"])
        assert r["status"] == "OK", (x["id"], r)
    run("bd_post", rev=1)


def sel_case_jig(tmp: str, mp, extra: dict | None = None):
    """새 ③ case_once: 구멍 판 + 리브 비드(기준 Case rad, 이웃 부품 deck), fixed-scan = 구멍 둘레 tie 6묶음."""
    import synth_doe as sd
    import test_jig_modes as JMo
    import test_jig_stages as T
    m = JMo._holed()
    cd = os.path.join(tmp, "case", "input")
    os.makedirs(cd, exist_ok=True)
    rad = sd.write_mesh_rad(os.path.join(cd, "model.rad"), m)
    T.add_neighbors(rad)
    dirs = [sd.save_entry(os.path.join(tmp, "lib"), f"E{k}", m, kind, 1.0 + k, seed=k)[0]
            for k, kind in enumerate(("bend", "dent"))]
    doe = {"id": "P1", "scenario": "select", "select_schema": 2, "bead_source": "auto", "title": "t",
           "cfg": {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}},
           "entries": [{"id": f"E{k}", "dir": d} for k, d in enumerate(dirs)],
           "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": cd},
           "rank": JMo.snap(), **(extra or {})}
    out = os.path.join(tmp, "_doe")

    def fixed(o):
        sd.write_fixed(os.path.join(o, "prep", "fixed"), m, JMo._hole_groups(m),
                       kinds=("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN"))
    _run_select(doe, out, before_loads=fixed)
    return doe, out


def sel_step_jig(tmp: str, mp, extra: dict | None = None):
    """새 ③ step_once(test_jig_modes._select_step 와 같은 세계 — gmsh 없이 합성 판)."""
    import pathlib

    import test_jig_modes as JMo
    root = pathlib.Path(tmp)
    out, doe = _step_with(root, mp, extra) if extra else JMo._select_step(root, mp)
    return doe, out


def _step_with(root, mp, extra):
    """_select_step 에 스냅샷 키 extra 를 더한 세계(V-0249 시험이 쓰는 것 — 골든 기록은 extra 없음)."""
    import test_jig_modes as JMo
    from esl.doe import stages as stg
    real = stg.run_stage

    def run_stage(spec, cb):
        if isinstance(spec.get("doe"), dict):
            spec = {**spec, "doe": {**spec["doe"], **extra}}
        return real(spec, cb)
    mp.setattr(stg, "run_stage", run_stage)
    try:
        return JMo._select_step(root, mp)
    finally:
        mp.setattr(stg, "run_stage", real)


CASES = {"sel_case_jig": sel_case_jig, "sel_step_jig": sel_step_jig}


def compute(case: str, tmp: str, mp, extra: dict | None = None) -> dict:
    _doe, out = CASES[case](tmp, mp, extra)
    return tree_sha(out, tmp)


# ---------------------------------------------------------------- 패키지 기저
def _bsha(B) -> str:
    h = hashlib.sha256()
    for b in B:
        h.update(b["name"].encode())
        h.update(np.float64(b["nominal"]).tobytes())
        h.update(np.ascontiguousarray(b["idx"], "<i8").tobytes())
        h.update(np.ascontiguousarray(b["vec"], "<f8").tobytes())
        h.update(np.ascontiguousarray(b["zone"], "<i8").tobytes())
    return h.hexdigest()


def package_bases(names=("h5", "stepboss", "h6")) -> dict:
    import beadgraph as bgp
    from beadgraph import basis
    from beadgraph.testing import conformance as cf
    out = {}
    for nm in names:
        g, lab, _ = cf.classified(nm)
        out[f"{nm}/graph.json"] = hashlib.sha256(bgp.graph_bytes(g)).hexdigest()
        fx = cf.load_fixture(nm)
        X, C, F = fx["x0"], fx["conn"], fx["fixed"]
        segs = [s for s in g["segments"] if s["type"] != "base"]
        osd = bgp.one_side(g, lab, X, C, [s["id"] for s in segs])
        for s in segs:
            kinds = ["D", "DF"] + (["W"] if s.get("entry_width") is not None else []) + \
                (["W1"] if s.get("entry_width") is None and osd[s["id"]]["ok"] else [])
            for kind in kinds:
                bl = [{"name": "v", "kind": kind, "segs": [s["id"]], "zones": [], "hold": 1}]
                if kind == "W1":
                    bl[0].update(ramp="end", min_nodes=3)
                try:
                    B = basis(g, lab, X, bl, None, fixed=F, elems=C)
                except Exception as exc:                          # noqa: BLE001 — 실패도 골든(같은 실패여야 함)
                    out[f"{nm}/s{s['id']}/{kind}"] = f"ERR {type(exc).__name__}"
                    continue
                out[f"{nm}/s{s['id']}/{kind}"] = _bsha(B)
        for n in g["networks"]:
            bl = [{"name": "n", "kind": "D", "segs": n["segments"], "zones": n["junction_zones"], "hold": 1}]
            out[f"{nm}/net{n['id']}/D"] = _bsha(basis(g, lab, X, bl, None, fixed=F, elems=C))
    return out


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _record():
    import shutil
    import tempfile

    import pytest
    got, unstable = {}, {}
    for case in CASES:
        runs = []
        for _ in range(2):                                       # 같은 코드 두 번 = 결정적인 파일만 골든에
            tmp = tempfile.mkdtemp(prefix=f"g0249_{case}_")
            with pytest.MonkeyPatch.context() as mp:
                runs.append(compute(case, tmp, mp))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = runs
        uns = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        got[case] = {k: v for k, v in a.items() if k not in uns}
        unstable[case] = uns
        print(case, len(a), "files", "unstable", uns)
    pk = package_bases()
    print("package", len(pk))
    doc = {"made_by": "tests/doe/golden_v0249_c1/golden_pu.py (release/v0.24.9 3609c921 — 코드 변경 전)",
           "cases": got, "unstable": unstable, "package": pk}
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        raise SystemExit("ESL_GOLDEN_RECORD=1 로만 기록(옛 코드에서)")
    sys.path.insert(0, ROOT)
    _record()
