"""검증 낙하 코어 단계(계약 esl_scx_relay.md §9.2·§9.3) — 워커 자식 프로세스가 부른다(esl.pipeline.VERIFY_STAGES).

- ``vd_patch``  : 모핑 좌표(DOE ``best/<did>/include`` 사본의 대상 파트 노드 — ``esl.doe.nodes.morphed_coords``) → 원 Case 입력
  세트에 노드 ID 기준 패치(``esl.verify.patch``). 바뀐 파일만 ``spec.out``(= ``_verify/<id>/stage``)에, 결과 ``spec.result_out``
  (JSON: files·n_patched·morph{n_found, n_moved, max_disp}) + 모핑 좌표 ``spec.morph_out``(npz node_id·x — 비교의 검증 쪽 기준 좌표).
- ``vd_compare``: 두 추출 비교(``esl.verify.compare``) → ``compare.json``·``compare.csv``.
원본(Case 입력·DOE best)은 읽기만. 쓰기는 spec 의 출력 경로(호출자가 ``_verify/<id>`` 안으로 정함)만.
"""
from __future__ import annotations

import json
import os

import numpy as np

from esl.errors import EslError

STAGES = ("vd_patch", "vd_compare")


def _write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def vd_patch(spec: dict, echo=print) -> dict:
    from esl.doe import nodes as nd
    from esl.verify.patch import patch_node_files

    with np.load(spec["model_npz"], allow_pickle=False) as z:
        nid = np.asarray(z["node_id"], dtype=np.int64)
        x0 = np.asarray(z["x0"], dtype=np.float64)
    best = spec["best_dir"]
    rels = list(spec.get("best_rels") or [])
    if not rels:
        raise EslError("VD_DESIGN_NO_FILES", "안의 모핑 사본(best/<안>/include)이 없음")
    X, info = nd.morphed_coords(best, rels, nid, x0, max_line=spec.get("max_line"))
    echo(f"[vd_patch] 모핑 사본 {len(rels)}개 — 대상 파트 노드 {nid.size}, 사본에서 찾음 {info['n_found']}, "
         f"움직임 {info['n_moved']}(최대 {info['max_disp']:.4g})")
    coords = {int(nid[i]): tuple(X[i]) for i in range(nid.size)}
    os.makedirs(spec["out"], exist_ok=True)
    res = patch_node_files([(r, p) for r, p in spec["files"]], coords, spec["out"], required=nid.tolist(),
                           max_line=spec.get("max_line"))
    res["morph"] = {k: info[k] for k in ("n_found", "n_moved", "max_disp")}
    moved = np.linalg.norm(X - x0, axis=1) > 0
    np.savez_compressed(spec["morph_out"], node_id=nid[moved], x=X[moved])
    for f in res["files"]:
        if f["source"] == "patched":
            echo(f"[vd_patch] {f['rel']}: /NODE {f['n_patched']}줄 고침")
    echo(f"[vd_patch] 파일 {len(res['files'])}개(고친 파일 {sum(1 for f in res['files'] if f['source'] == 'patched')}개, "
         f"줄 {res['n_patched']})")
    _write_json(spec["result_out"], res)
    return res


def vd_compare(spec: dict, echo=print) -> dict:
    from esl.verify.compare import compare, compare_csv

    x0v = None
    mp = spec.get("morph_npz")
    if mp and os.path.isfile(mp):
        with np.load(mp, allow_pickle=False) as z:
            x0v = {int(k): tuple(v) for k, v in zip(z["node_id"].tolist(), np.asarray(z["x"], dtype=np.float64))}
    res = compare(spec["orig_out"], spec["verify_out"], tstar_time=spec.get("tstar_time"), predicted=spec.get("predicted"),
                  same_tol=float(spec.get("same_tol", 0.02)), hot_n=int(spec.get("hot_n", 20)), x0_verify=x0v)
    _write_json(spec["out_json"], res)
    tmp = spec["out_csv"] + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(compare_csv(res))
    os.replace(tmp, spec["out_csv"])
    for r in res["rows"]:
        echo(f"[vd_compare] {r['key']}: 원 {r['orig']} · 검증 {r['verify']} · 비 {r['ratio']} · 예측 {r['predicted']} "
             f"→ {r['verdict']} 일치 {r['agree']}")
    return res


def run_stage(spec: dict, echo=print) -> dict:
    st = spec.get("stage")
    if st == "vd_patch":
        return vd_patch(spec, echo)
    if st == "vd_compare":
        return vd_compare(spec, echo)
    raise EslError("INPUT_INVALID", f"검증 낙하 단계 {st} — {list(STAGES)}")


__all__ = ["STAGES", "run_stage", "vd_patch", "vd_compare"]
