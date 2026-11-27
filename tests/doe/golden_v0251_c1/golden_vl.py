"""V-0251-10·13 골든(release/v0.25.1 2be518f1 = main 97a0e358 v0.25.0 + v0.25.1 계약, 코드 변경 전에 기록 — 다시 기록 금지).

계약 docs/contracts/esl_view3d_scene_legend.md §7.2·§9.1-10: 같은 입력이면 result.json·ranking.csv·per_esl.json·jig_view.json·
bforce/fint 사이드카·``post/view3d/**``·report.html(·prep·run·best 전부) 바이트 동일, 새 파일은 ``post/view3d_scene/**``·
``post/scene_view.json`` 뿐.

세계(작은 합성 — 기존 시험 세계 재사용):
  · same_lt: ① same(test_jig_stages.build_same — 하중 전달 work, 순위 스냅샷 없음 = 옛 결과)
  · same_all6: ① same + 새 스냅샷 지그 3방식(fixed·prescribed·spring, tie normal) + 평가 영역 + 경계력·내력 켬 — 출처 6행 전부
  · sel_case_jig: 새 ③ case_once(select) 지그 순위(golden_v0249_c1.sel_case_jig)
  · step_old: 옛 ③ scenario step(가짜 gmsh — 안마다 다른 메시)
  · cmp_lt: ④ 형상 직접 비교(하중 전달 LT, 격자 지그 없음)
  · cmp_grid: ④ 격자 지그(rank.jig_grid)

기록: ESL_GOLDEN_RECORD=1 python tests/doe/golden_v0251_c1/golden_vl.py (2be518f1 코드에서만).
비교 규칙 = golden_v0249_c1.tree_sha(JSON 시간 키 제외 정규 바이트, npz 배열 sha, 그 밖 원 바이트 — 작업 경로 = <ROOT>)."""
from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden.json")
DOE_T = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(DOE_T))
for p in (DOE_T, os.path.join(DOE_T, "golden_v0249_c1"), os.path.join(DOE_T, "golden_v0248_c1"),
          os.path.join(ROOT, "packages", "beadgraph", "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

NEW_PREFIX = ("post/view3d_scene/", "post/scene_view.json")
EV = {"mode": "exclude_free_edges", "free_edge_mm": 15.0, "boxes": []}


def all6_rank():
    """새 스냅샷 지그 3방식(fixed 포함 — 새 경로 BC 배열) + 평가 영역(umax_ev)."""
    import test_jig_modes as JMo
    r = JMo.snap()
    r["jig"]["methods"] = ["fixed", "prescribed", "spring"]
    r["eval_region"] = dict(EV)
    return r


def same_world(tmp: str, *, kind: str, extra: dict | None = None):
    """① same 세계 → (doe, out, mesh). kind = lt(순위 스냅샷 없음) | all6(지그 3방식·경계력·내력·평가 영역) | legacy(옛 지그 고정
    translation — 옛 npz, 경계력·내력 켬)."""
    import pathlib

    import test_bforce_doe as B
    import test_fint_doe as FI
    import test_jig_stages as T
    t = pathlib.Path(tmp)
    if kind == "lt":
        mesh, doe = T.build_same(t)
        rank = None
    else:
        mesh, doe = FI._setup(t)
        rank = all6_rank() if kind == "all6" else T.rank_snap(eval_region=dict(EV))
    if extra:
        doe = {**doe, **extra}
    _ = B
    return doe, rank, mesh


def run_same(tmp: str, kind: str, extra: dict | None = None, cfg_over: dict | None = None) -> str:
    import test_jig_stages as T
    doe, rank, mesh = same_world(tmp, kind=kind, extra=extra)
    if cfg_over:
        bd = copy.deepcopy(doe["cfg"]["bead_doe"])
        for k, v in cfg_over.items():
            bd[k] = {**(bd.get(k) or {}), **v} if isinstance(v, dict) else v
        doe = {**doe, "cfg": {**doe["cfg"], "bead_doe": bd}}
    out, _post, _ids = T.run(os.path.join(tmp, "o"), doe, mesh, rank=rank)
    return out


def compute_out(case: str, tmp: str, mp, cfg_over: dict | None = None) -> str:
    """세계를 실행하고 스터디 출력 폴더를 돌려준다. cfg_over = bead_doe 설정 덮어쓰기(예: view3d.scene.enabled false)."""
    import golden_jg as GJ
    import golden_pu as GP
    import synth_jig_grid as G

    def with_cfg(doe):
        if not cfg_over:
            return doe
        bd = copy.deepcopy(doe["cfg"]["bead_doe"])
        for k, v in cfg_over.items():
            bd[k] = {**(bd.get(k) or {}), **v} if isinstance(v, dict) else v
        return {**doe, "cfg": {**doe["cfg"], "bead_doe": bd}}
    if case in ("same_lt", "same_all6"):
        return run_same(tmp, case.split("_", 1)[1], cfg_over=cfg_over)
    if case == "sel_case_jig":
        import golden_pu  # noqa: F401
        real = GP._run_select

        def _rs(doe, out, before_loads=None):
            return real(with_cfg(doe), out, before_loads)
        mp.setattr(GP, "_run_select", _rs)
        return GP.sel_case_jig(tmp, mp)[1]
    if case == "step_old":
        doe, out, A = G.step_world(tmp, rank=G.rank_snap())
        with G.fake_gmsh(mp):
            G.run_step(with_cfg(doe), out, A)
        return out
    if case == "cmp_lt":
        doe, out, _A = G.cmp_world(tmp, rank=G.rank_snap())
        G.run_cmp(with_cfg(doe), out)
        return out
    if case == "cmp_grid":
        doe, out, _A = G.cmp_world(tmp, rank=G.rank_snap(grid=True))
        G.run_cmp(with_cfg(doe), out)
        return out
    _ = GJ
    raise KeyError(case)


CASES = ("same_lt", "same_all6", "sel_case_jig", "step_old", "cmp_lt", "cmp_grid")


def compute(case: str, tmp: str, mp, cfg_over: dict | None = None) -> dict:
    from golden_pu import tree_sha
    return tree_sha(compute_out(case, tmp, mp, cfg_over), tmp, scene=True)


def split_new(got: dict) -> tuple[dict, list]:
    """(기존 파일, 새 파일 목록 — 계약 §2.2 새 경로만)."""
    old = {k: v for k, v in got.items() if not k.startswith(NEW_PREFIX)}
    return old, sorted(k for k in got if k.startswith(NEW_PREFIX))


def load() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _record():
    import shutil
    import tempfile

    import pytest
    got, unstable = {}, {}
    only = [c for c in sys.argv[1:] if c in CASES] or list(CASES)
    doc = load() if os.path.isfile(GOLDEN) else {"cases": {}, "unstable": {}}
    for case in only:
        runs = []
        for _ in range(2):                                       # 같은 코드 두 번 = 결정적인 파일만 골든에
            tmp = tempfile.mkdtemp(prefix=f"g0251_{case}_")
            with pytest.MonkeyPatch.context() as mp:
                runs.append(compute(case, tmp, mp))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = runs
        uns = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        got[case] = {k: v for k, v in a.items() if k not in uns}
        unstable[case] = uns
        print(case, len(a), "files", "unstable", uns, flush=True)
    doc["cases"].update(got)
    doc["unstable"].update(unstable)
    doc["made_by"] = "tests/doe/golden_v0251_c1/golden_vl.py (release/v0.25.1 2be518f1 = main 97a0e358 — 코드 변경 전)"
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


if __name__ == "__main__":
    if os.environ.get("ESL_GOLDEN_RECORD") != "1":
        raise SystemExit("ESL_GOLDEN_RECORD=1 로만 기록(옛 코드에서)")
    sys.path.insert(0, ROOT)
    _record()
