"""v0.24.6 C1 스터디 지그 변위·스프링 3D(계약 docs/contracts/esl_viewer_hv.md §8.1·§8.2·§11, V-0246-VW-17~19,
결정 D-0.24.6-VW-13·16).

골든: 코어 변경 **전**(main 8c4f3477 = v0.24.5 코드, 별도 worktree)에 ``ESL_GOLDEN_RECORD_V0246C1=1`` 로
``tests/fixtures/jig_case/golden_v0246_c1.json`` 에 기록했다(다시 기록 금지 — 깨지면 옛 스터디·고정 지그 3D 바이트가 바뀐 것).
시나리오 3개(합성 스터디 test_jig_stages.build_same — 인접 쉘·솔리드, tie 8노드):

- ``v0243``: 옛 스냅샷(rank.jig = v0.24.3 키만 — jig_bc.LEGACY_ABSENT translation·fixed, 옛 단일 경로) — v0.24.3 이전 스냅샷 해시.
- ``v0244``: v0.24.4 P2c 스냅샷(normal · [fixed, prescribed, spring]).
- ``v0245``: v0.24.5 기본 스냅샷(DEFAULTS — normal · [prescribed, spring], 지그 고정 계산 제외).

각 시나리오: BD_POST 직후(``post``) 와 3D 다시 만들기(post_mode view3d, 복사본) 뒤(``regen``)의 post/result.json·per_esl.json·
ranking.csv·designs.json·안 result.json·post/jig_view.json(새 키 ``NEW_SIDE_KEYS`` 제외 — 옛 코드에는 없음)·고정 지그 3D·진단 3D 폴더
(post/view3d/*jig*). 해시 = test_jig_move 규칙(JSON = 시간 값 뺀 정규 JSON, npz = 배열 해시). 풀이 결과에 의존하므로 같은 환경 서명
에서만 바이트 비교(다른 환경 = 파일 목록만).

샘플러 차이(V-19 — 표로 기록):

| 쓰는 곳 | 함수 | 규칙 |
|---|---|---|
| 코어 스터디 jd·js 3D | ``esl.mech.jig_bc.support_marks`` → ``esl.mech.jig.support_sample`` | 최원점, 첫 점 = 가장 작은 인덱스, 동률 = 작은 인덱스 |
| 백엔드 Case 지그 3D | ``api/services/view3d._jig_supports`` → ``jig_support_sample`` | 같은 정의(백엔드는 scipy 끄는 모듈을 import 하지 않아 사본) |
| 코어 스터디 고정 3D | ``stages._jig_view3d`` → ``jig.support_sample(jig_idx)`` | 지그 노드 전부 '123'(면내 'ij' 없음 — v0.23.2 그대로, 통일 = R-VW-3) |
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import shutil
import sys
import time
import tracemalloc
import types

import numpy as np
import pytest
import test_jig_move as G
import test_jig_stages as T

from esl.doe import DEFAULTS
from esl.doe import rank as rk
from esl.doe import stages as stg
from esl.library import _util as U

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "jig_case", "golden_v0246_c1.json")
RECORD = os.environ.get("ESL_GOLDEN_RECORD_V0246C1") == "1"
# 사이드카 새 키(옛 코드에는 없음 — 골든 비교에서 뺌). 계획 표 열과 같은지는 test_rank_sources_v3d_columns 가 확인.
NEW_SIDE_KEYS = ("view3d_jd", "view3d_jd_esl", "view3d_jd_ref", "view3d_js", "view3d_js_esl", "view3d_js_ref",
                 "view3d_src_seconds")
POST_FILES = ("post/result.json", "post/per_esl.json", "post/ranking.csv", "post/designs.json")


def _jig_v0244():
    j = copy.deepcopy(DEFAULTS["rank"]["jig"])
    j["methods"] = ["fixed", "prescribed", "spring"]
    return j


SCN = {"v0243": lambda: T.jcfg(), "v0244": _jig_v0244, "v0245": lambda: copy.deepcopy(DEFAULTS["rank"]["jig"])}


def _canon_side(path: str, root: str) -> str:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc = {k: v for k, v in doc.items() if k not in NEW_SIDE_KEYS}
    return G._sha(json.dumps(G._strip(doc, root), ensure_ascii=False, sort_keys=True).encode())


def snapshot(out: str, root: str) -> dict[str, str]:
    def keep(rel: str) -> bool:
        if rel in POST_FILES:
            return True
        if rel.startswith("run/designs/") and rel.endswith("/result.json"):
            return True
        return rel.startswith("post/view3d/") and "jig" in rel.split("/")[2]
    h = G.tree_hashes(out, root, keep)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    if os.path.isfile(sp):
        h["post/" + stg.JIG_VIEW_JSON] = _canon_side(sp, root)
    return dict(sorted(h.items()))


def _spec(out, doe, **kw):
    return {"stage": "bd_post", "out": out, "doe": {**doe, "rev": 1, **kw}}


def regen(out, doe, **kw):
    return stg.run_stage(_spec(out, doe, post_mode="view3d", **kw), lambda s: None)


def run_scn(base, name):
    """시나리오 실행 → BD_POST 스냅샷, 복사본(<base>/r)에서 다시 만들기 → regen 스냅샷. 반환 dict."""
    root = str(base)
    mesh, doe = T.build_same(base)
    rank = T.rank_snap(jig=SCN[name]())
    t0 = time.monotonic()
    out, post, ids = T.run(str(base / "o"), doe, mesh, rank=rank)
    sec = time.monotonic() - t0
    snap_post = snapshot(out, root)
    side_post = U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    outr = str(base / "r" / "_doe")
    shutil.copytree(out, outr)
    rdoc = {**doe, "rank": rank}
    regen(outr, rdoc)
    return {"root": root, "out": out, "outr": outr, "post": post, "ids": ids, "doe": rdoc, "snap_post": snap_post,
            "snap_regen": snapshot(outr, root), "side_post": side_post,
            "side_regen": U.read_json(os.path.join(outr, "post", stg.JIG_VIEW_JSON)), "seconds": sec}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return {n: run_scn(tmp_path_factory.mktemp(f"c1_{n}"), n) for n in SCN}


# ---------------------------------------------------------------- V-17·18 골든(옛 스터디·고정 지그 3D·진단 바이트 동일)
def test_golden_bytes_vs_main_8c4f3477(runs):
    """result.json·사이드카(새 키 제외)·고정 지그 3D·진단 폴더·안 result.json = main 8c4f3477 기록과 같음(BD_POST·다시 만들기 모두).
    옛 스냅샷(v0243)은 사이드카 새 키도 없음(다시 만들기 = v0.24.5 사이드카와 같음)."""
    rec = {"env": G.env_sig(), "scenarios": {n: {"post": r["snap_post"], "regen": r["snap_regen"]} for n, r in runs.items()}}
    if RECORD:
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden recorded")
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)
    assert set(gold["scenarios"]) == set(SCN)
    same_env = gold["env"] == rec["env"]
    for n, g in gold["scenarios"].items():
        for phase in ("post", "regen"):
            got = rec["scenarios"][n][phase]
            assert sorted(got) == sorted(g[phase]), (n, phase, set(got) ^ set(g[phase]))
            if same_env:
                diff = [k for k in g[phase] if got[k] != g[phase][k]]
                assert not diff, (n, phase, diff)
    old = runs["v0243"]
    for side in (old["side_post"], old["side_regen"]):
        assert not set(NEW_SIDE_KEYS) & set(side)
    assert not [d for d in os.listdir(os.path.join(old["outr"], "post", "view3d")) if d.endswith(("_jd", "_js"))]


# ---------------------------------------------------------------- V-17 _jig_view3d_src
def _row(key):
    return stg._jig_src_row(key)


def _designs(out):
    return {d: U.read_json(os.path.join(out, "run", "designs", d, "result.json"))
            for d in os.listdir(os.path.join(out, "run", "designs"))}


def _check_src_3d(out, post, side, smax=64):
    """사이드카 jd·js 키·폴더·표식·응답(저장 BC 재풀이) 확인 — 반환 {tag: 안 수}."""
    from esl.mech import jig_bc
    shown = [d for d in post["view3d"] if d != stg.BASELINE]
    res = _designs(out)
    order = [str(e) for e in ("E0", "E1")]
    mesh0 = dict(stg.sc.load_base(os.path.join(out, "prep"))[0].mesh)
    got = {}
    for key in ("jig_disp", "jig_spring"):
        row = _row(key)
        kd, ke, kr = row["v3d"]
        tag, need = row["v3d_tag"], row["need"]
        assert kd in side and ke in side and kr in side, key
        assert not {kd, ke, kr} & set(post)                                  # result.json 에는 없음(사이드카만)
        assert set(side[kd]) == set(shown) and all(side[kd][d] == f"{d}_{tag}" for d in shown)
        z = U.load_npz(os.path.join(out, "prep", f"{key}.npz"))
        zeids = [str(e) for e in z["entry_ids"].tolist()]
        basis = stg._jig_basis_of(z, int(z["a"].shape[1]))
        bc = jig_bc.load_bc({n: z[n] for n in stg.JIG_BC_PATTERN})
        tie_set = set(np.asarray(bc["bc_node"])[np.asarray(bc["bc_kind"]) == jig_bc.KIND_TIE].tolist()) | set(
            np.asarray(bc["sp_node"]).tolist())
        aux_set = set(np.asarray(bc["bc_node"])[np.asarray(bc["bc_kind"]) == jig_bc.KIND_AUX].tolist())
        assert tie_set and aux_set
        nid0 = np.asarray(mesh0["node_id"], dtype=np.int64)
        for d in shown:
            want = str(rk._agg({"id": d, "per_esl": res[d]["per_esl"]}, need)["worst"])    # 순위 행 worst 와 같은 함수
            assert side[ke][d] == want
            vd = os.path.join(out, "post", "view3d", side[kd][d])
            man = U.read_json(os.path.join(vd, "manifest.json"))
            assert man["esl_run_id"] == want
            sup = man["supports"]
            ties = [s["node_id"] for s in sup if s["dof"] == jig_bc.MARK_TIE]
            auxs = [s["node_id"] for s in sup if s["dof"] == jig_bc.MARK_AUX]
            assert {s["dof"] for s in sup} <= {jig_bc.MARK_TIE, jig_bc.MARK_AUX}
            assert 0 < len(ties) <= smax and len(ties) == min(smax, len(tie_set))
            assert {int(np.flatnonzero(nid0 == n)[0]) for n in ties} <= tie_set
            assert {int(np.flatnonzero(nid0 == n)[0]) for n in auxs} == aux_set - {
                int(np.flatnonzero(nid0 == n)[0]) for n in ties}
            mesh = dict(mesh0)
            mesh["x0"] = stg.ev.load_design(os.path.join(out, "run", "designs", d))["x"]
            k = zeids.index(want)
            from esl.doe import jig as jg
            F = jg.forces(basis, np.asarray(z["a"][k], dtype=np.float64), z["node_id"].size)
            h = jig_bc.factorize(stg._jig_sm(mesh, {"backend": "superlu"}), stg._jig_bc_of(z, None))
            u = np.asarray(jig_bc.respond(h, F, stg._jig_bc_of(z, k))["u"], dtype=np.float64)[:, :3]
            assert man["ranges"]["u_max"] == pytest.approx(float(np.linalg.norm(u, axis=1).max()), rel=1e-6)
        assert set(side[kr]) == set(side[ke].values())
        for e, nm in side[kr].items():
            assert nm == f"{stg.BASELINE}_{tag}_e{order.index(e):02d}"
            assert U.read_json(os.path.join(out, "post", "view3d", nm, "manifest.json"))["esl_run_id"] == e
        got[tag] = len(side[kd])
    assert set(side["view3d_src_seconds"]) == {"jd", "js"} and all(v >= 0 for v in side["view3d_src_seconds"].values())
    return got


@pytest.mark.parametrize("name", ["v0244", "v0245"])
def test_src_3d_sidecar_folders_marks(runs, name):
    """새 스냅샷(prescribed·spring): 지그 변위·스프링 3D = 사이드카 키·폴더 <did>_<tag>·d000_<tag>_e<kk>, 표식 tie ∪ 스프링 샘플 '123'
    ≤ smax + 면내 'ij'(겹치면 tie), 응답 = 저장 BC 재풀이. result.json 에 새 키 없음(바이트는 골든 시험). 다시 만들기 = 옮겨 적기."""
    r = runs[name]
    got = _check_src_3d(r["out"], r["post"], r["side_post"])
    assert got == {"jd": len(r["post"]["view3d"]) - 1, "js": len(r["post"]["view3d"]) - 1}
    for k in NEW_SIDE_KEYS:                                                   # 다시 만들기(같은 사이드카) = 옮겨 적기(같은 값)
        assert r["side_regen"][k] == r["side_post"][k]
    assert not r["side_post"]["warnings"]
    if name == "v0245":                                                       # 고정 지그 계산 제외 → 고정 3D 없음, jd·js 만
        assert not {"view3d_jig", "view3d_jig_esl", "view3d_jig_ref"} & (set(r["post"]) | set(r["side_post"]))
    else:
        assert set(r["post"]["view3d_jig"]) == set(r["side_post"]["view3d_jd"])


def test_src_3d_support_max_and_regen_adds_to_v0245_study(runs, tmp_path):
    """§8.2: v0.24.5 형 사이드카(새 키·jd·js 폴더 없음)를 다시 만들기 → 새로 만듦(키·폴더 = BD_POST 와 같음). smax = 3 이면 '123' ≤ 3."""
    r = runs["v0245"]
    out = str(tmp_path / "_doe")
    shutil.copytree(r["out"], out)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    side = U.read_json(sp)
    U.write_json(sp, {k: v for k, v in side.items() if k not in NEW_SIDE_KEYS})
    for d in glob.glob(os.path.join(out, "post", "view3d", "*_j[ds]")) + glob.glob(os.path.join(out, "post", "view3d", "*_j[ds]_e*")):
        shutil.rmtree(d)
    before = G.tree_hashes(out, str(tmp_path), lambda rel: rel in POST_FILES)
    res = regen(out, r["doe"])
    assert res["files"] == ["post/" + stg.JIG_VIEW_JSON] and res["result"] is None
    assert G.tree_hashes(out, str(tmp_path), lambda rel: rel in POST_FILES) == before
    s2 = U.read_json(sp)
    assert s2["source"] == "view3d_regen"
    for k in NEW_SIDE_KEYS[:-1]:
        assert s2[k] == side[k]
    for nm in list(s2["view3d_jd"].values()) + list(s2["view3d_js_ref"].values()):
        a = G.tree_hashes(os.path.join(out, "post", "view3d", nm), str(tmp_path))
        b = G.tree_hashes(os.path.join(r["out"], "post", "view3d", nm), r["root"])
        assert a == b, nm                                                     # 결정적(BD_POST 와 같은 바이트)
    # smax = 3(설정 view3d.jig_support_max) — 새로 만든 표식만 바뀜
    U.write_json(sp, {k: v for k, v in s2.items() if k not in NEW_SIDE_KEYS})
    regen(out, {**r["doe"], "cfg": {**T.CFG_FULL, "bead_doe": {"enabled": True, "view3d": {"jig_support_max": 3}}}})
    _check_src_3d(out, r["post"], U.read_json(sp), smax=3)


def test_src_3d_failure_isolated_bd_post(tmp_path, monkeypatch):
    """jd 재풀이만 예외(BD_POST): 그 안·기준만 경고 VIEW3D_FAILED: <did>_jd — 사이드카 jd 키 없음, js·고정 3D·보기 정상, result.json =
    골든과 같음(경고가 result.json 에 새지 않음)."""
    f0 = stg._jig_resp_rows

    def boom(c, mesh, z, jidx, ld):
        if "method" in z and str(np.asarray(z["method"]).ravel()[0]) == "prescribed":
            raise RuntimeError("synthetic jd 3D crash")
        return f0(c, mesh, z, jidx, ld)
    monkeypatch.setattr(stg, "_jig_resp_rows", boom)
    mesh, doe = T.build_same(tmp_path)
    out, post, ids = T.run(str(tmp_path / "o"), doe, mesh, rank=T.rank_snap(jig=_jig_v0244()))
    side = U.read_json(os.path.join(out, "post", stg.JIG_VIEW_JSON))
    shown = [d for d in post["view3d"] if d != stg.BASELINE]
    assert not {"view3d_jd", "view3d_jd_esl", "view3d_jd_ref"} & set(side)
    assert {f"VIEW3D_FAILED: {d}_jd RuntimeError" for d in shown} <= set(side["warnings"])
    assert set(side["view3d_js"]) == set(shown) and set(side["view3d_src_seconds"]) == {"js"}
    assert {"jig", "jig_disp", "jig_spring", "full"} == set(side["rank_views"]) and side.get("jig_diag")
    assert not [w for w in post["warnings"] if "_jd" in str(w)]
    with open(GOLDEN, encoding="utf-8") as fh:
        gold = json.load(fh)
    if gold["env"] == G.env_sig():
        assert G.file_hash(os.path.join(out, "post", "result.json"), str(tmp_path)) == \
            gold["scenarios"]["v0244"]["post"]["post/result.json"]


def test_src_3d_row_exception_isolated_regen(runs, tmp_path, monkeypatch):
    """행 전체 예외(다시 만들기): 경고 VIEW3D_FAILED: <tag> <code> 만 — 다른 행·보기·진단 계속, 다시 만들기 성공."""
    r = runs["v0244"]
    out = str(tmp_path / "_doe")
    shutil.copytree(r["out"], out)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    U.write_json(sp, {k: v for k, v in U.read_json(sp).items() if k not in NEW_SIDE_KEYS})
    f0 = stg._jig_view3d_src

    def boom(c, t, results, shown, row):
        if row["v3d_tag"] == "js":
            raise stg.EslError("OUTPUT_INCONSISTENT", "synthetic")
        return f0(c, t, results, shown, row)
    monkeypatch.setattr(stg, "_jig_view3d_src", boom)
    res = regen(out, r["doe"])
    s2 = U.read_json(sp)
    assert "VIEW3D_FAILED: js OUTPUT_INCONSISTENT" in res["warnings"] and "VIEW3D_FAILED: js OUTPUT_INCONSISTENT" in s2["warnings"]
    assert "view3d_js" not in s2 and s2["view3d_jd"] == r["side_post"]["view3d_jd"]
    assert s2["rank_views"] and s2["jig_diag"]


# ---------------------------------------------------------------- V-18 _post_view3d 옮겨 적기·준비 안 됨
def test_regen_carries_existing_keys_without_rebuild(runs, tmp_path, monkeypatch):
    """사이드카에 이미 jd 키 = 옮겨 적음(덮지 않음 — 값·시간 그대로, 다시 풀지 않음), 없는 js 만 새로 만듦."""
    r = runs["v0244"]
    out = str(tmp_path / "_doe")
    shutil.copytree(r["out"], out)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    side = U.read_json(sp)
    sentinel = {"view3d_jd": {"d001": "d001_jd"}, "view3d_jd_esl": {"d001": "E1"}, "view3d_jd_ref": {"E1": "d000_jd_e01"}}
    side.update(sentinel)
    side["view3d_src_seconds"] = {"jd": 9.5, "js": 1.0}
    for k in ("view3d_js", "view3d_js_esl", "view3d_js_ref"):
        side.pop(k)
    U.write_json(sp, side)
    mt = {d: os.path.getmtime(os.path.join(out, "post", "view3d", d, "manifest.json"))
          for d in r["side_post"]["view3d_jd"].values()}
    calls = []
    f0 = stg._jig_view3d_src

    def spy(c, t, results, shown, row):
        calls.append(row["v3d_tag"])
        return f0(c, t, results, shown, row)
    monkeypatch.setattr(stg, "_jig_view3d_src", spy)
    regen(out, r["doe"])
    s2 = U.read_json(sp)
    assert calls == ["js"]
    assert {k: s2[k] for k in sentinel} == sentinel and s2["view3d_src_seconds"]["jd"] == 9.5
    assert s2["view3d_js"] == r["side_post"]["view3d_js"] and s2["view3d_src_seconds"]["js"] != 1.0
    assert all(os.path.getmtime(os.path.join(out, "post", "view3d", d, "manifest.json")) == t_ for d, t_ in mt.items())
    calls.clear()
    regen(out, r["doe"])                                                     # 멱등: 둘 다 있으면 아무것도 다시 풀지 않음
    assert calls == [] and U.read_json(sp)["view3d_js"] == s2["view3d_js"]


def test_regen_unready_method_has_no_key(runs, tmp_path):
    """준비 안 된 방식(prep/<src>.json fallback ∨ npz 없음) = 키 없음(사유는 §9 — 화면), 경고 없음. 옛 단일 경로 = 새 키 0."""
    r = runs["v0244"]
    out = str(tmp_path / "_doe")
    shutil.copytree(r["out"], out)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    U.write_json(sp, {k: v for k, v in U.read_json(sp).items() if k not in NEW_SIDE_KEYS})
    jp = os.path.join(out, "prep", "jig_spring.json")
    U.write_json(jp, {**U.read_json(jp), "status": "fallback", "code": "JIG_SKIPPED"})
    os.remove(os.path.join(out, "prep", "jig_disp.npz"))
    res = regen(out, r["doe"])
    s2 = U.read_json(sp)
    assert s2["source"] == "view3d_regen" and s2["rank_views"]               # 사이드카는 다시 씀(고정 준비됨)
    assert not set(NEW_SIDE_KEYS) & set(s2) and not [w for w in res["warnings"] if "VIEW3D_FAILED" in w]
    U.write_json(jp, {**U.read_json(jp), "status": "ok", "code": None})      # 스프링만 다시 준비 → js 만
    regen(out, r["doe"])
    s3 = U.read_json(sp)
    assert "view3d_jd" not in s3 and s3["view3d_js"] == r["side_post"]["view3d_js"]
    old = runs["v0243"]
    assert not set(NEW_SIDE_KEYS) & set(old["side_regen"])


def test_view3d_off_no_src_3d(runs, tmp_path):
    """설정 view3d.jig 끔 = jd·js 3D 없음(고정 3D 와 같은 조건)."""
    r = runs["v0245"]
    out = str(tmp_path / "_doe")
    shutil.copytree(r["out"], out)
    sp = os.path.join(out, "post", stg.JIG_VIEW_JSON)
    U.write_json(sp, {k: v for k, v in U.read_json(sp).items() if k not in NEW_SIDE_KEYS})
    regen(out, {**r["doe"], "cfg": {**T.CFG_FULL, "bead_doe": {"enabled": True, "view3d": {"jig": False}}}})
    assert not set(NEW_SIDE_KEYS) & set(U.read_json(sp))


# ---------------------------------------------------------------- 계획 표 열 · 이름 분기 없음
def test_rank_sources_v3d_columns():
    """§8.1 열 v3d·v3d_tag·v3d_store — 모든 행 채움(값 또는 None), v3d = view3d_<tag>{,_esl,_ref}, result 행 1개(jig), sidecar 행 =
    사이드카 jig 행, 경계력·내력 = 노드 힘 경로 키(_ns_view3d f"view3d_{pe}")와 같음, 사이드카 새 키 = NEW_SIDE_KEYS."""
    cols = {"v3d", "v3d_tag", "v3d_store"}
    for r in stg.RANK_SOURCES:
        assert cols <= set(r), r["key"]
        assert r["v3d_store"] in ("result", "sidecar", None)
        if r["v3d"] is None:
            assert r["v3d_tag"] is None and r["v3d_store"] is None
        else:
            t = r["v3d_tag"]
            assert tuple(r["v3d"]) == (f"view3d_{t}", f"view3d_{t}_esl", f"view3d_{t}_ref")
            assert re.fullmatch(r"[0-9a-z_]{1,64}", f"d000_{t}_e00")       # 백엔드 DID_RE(api/services/doe.py) 안
    by = {r["key"]: r for r in stg.RANK_SOURCES}
    assert [k for k, r in by.items() if r["v3d_store"] == "result"] == ["jig"]
    assert [k for k, r in by.items() if r["v3d_store"] == "sidecar"] == ["jig_disp", "jig_spring"]
    assert all(by[k]["sidecar"] == "jig" for k in ("jig", "jig_disp", "jig_spring"))
    assert (by["jig"]["v3d_tag"], by["jig_disp"]["v3d_tag"], by["jig_spring"]["v3d_tag"]) == ("jig", "jd", "js")
    for ns in stg.NODAL_SOURCES:
        assert by[ns["key"]]["v3d_tag"] == ns["pe"] and by[ns["key"]]["v3d_store"] is None
    assert by["full"]["v3d"] is None
    side = [k for r in stg.RANK_SOURCES if r["v3d_store"] == "sidecar" for k in r["v3d"]] + ["view3d_src_seconds"]
    assert tuple(side) == NEW_SIDE_KEYS


def test_no_source_name_branch_in_src_3d_code():
    """새 코드(출처 3D·옮겨 적기·표식)에 방식·출처·꼬리표 이름 문자열 비교 없음(열 값만 — AGENTS.md D-0.20.0-CODE)."""
    import inspect
    import re

    from esl import view3d_src
    from esl.mech import jig_bc
    tags = [str(r["v3d_tag"]) for r in stg.RANK_SOURCES if r["v3d_tag"]]
    names = "|".join(list(jig_bc.METHODS) + list(jig_bc.TIE_DOFS) + list(view3d_src.KEYS) + tags)
    pat = re.compile(rf"""(==|!=|\bin\b)\s*\(?\s*["']({names})["']""")
    for fn in (stg._jig_view3d, stg._jig_view3d_src, stg._jig_v3d_build, stg._jig_v3d_sidecar, stg._jig_src_carry,
               stg._jig_extras, stg._post_view3d, jig_bc.support_marks):
        assert not pat.findall(inspect.getsource(fn)), fn.__name__


# ---------------------------------------------------------------- V-19 support_marks 순수 · 백엔드 _jig_supports 와 같은 노드 집합
def _backend_marks(tmp_path, bc_node, bc_kind, sp_node, x0, smax):
    from esl_platform.api.services import view3d as bv
    p = str(tmp_path / f"bc_{len(os.listdir(tmp_path))}.npz")
    np.savez(p, bc_node=np.asarray(bc_node, np.int64), bc_kind=np.asarray(bc_kind, np.int8),
             sp_node=np.asarray(sp_node, np.int64))
    inp = types.SimpleNamespace(support_npz=p, ctx=types.SimpleNamespace(settings=types.SimpleNamespace(
        bead_doe=types.SimpleNamespace(view3d=types.SimpleNamespace(jig_support_max=smax)))))
    nid = np.arange(1000, 1000 + len(x0), dtype=np.int64)
    return [(int(s["node_id"]) - 1000, s["dof"]) for s in bv._jig_supports(inp, nid, np.asarray(x0, np.float64))]


def test_support_marks_pure_and_matches_backend(tmp_path):
    from esl.doe import jig as jg
    from esl.mech import jig_bc
    from esl_platform.api.services import view3d as bv
    assert (jig_bc.MARK_TIE, jig_bc.MARK_AUX) == (bv.JIG_TIE_DOF, bv.JIG_AUX_DOF)
    assert (jig_bc.KIND_TIE, jig_bc.KIND_AUX) == (bv.JIG_KIND_TIE, bv.JIG_KIND_AUX)
    rng = np.random.default_rng(7)
    cases = []
    for k in range(12):
        n = int(rng.integers(20, 200))
        x0 = rng.normal(size=(n, 3)) * 50
        nt = int(rng.integers(0, 40))
        tie = rng.integers(0, n, size=nt)
        aux = rng.integers(0, n, size=int(rng.integers(0, 4)))
        if k % 3 == 0 and nt:                                           # 면내 노드가 tie 와 겹침
            aux = np.r_[aux, tie[:2]]
        spring = k % 2 == 1
        bn = np.r_[np.repeat(tie, 2) if not spring else [], aux].astype(np.int64)
        bk = np.r_[np.full(0 if spring else 2 * nt, jig_bc.KIND_TIE), np.full(aux.size, jig_bc.KIND_AUX)].astype(np.int8)
        sp = tie.astype(np.int64) if spring else np.zeros(0, np.int64)
        if k == 5:                                                      # 범위 밖 인덱스 무시
            bn, bk, sp = np.r_[bn, -1, n + 3], np.r_[bk, jig_bc.KIND_TIE, jig_bc.KIND_AUX].astype(np.int8), np.r_[sp, n]
        cases.append((bn, bk, sp, x0, int(rng.choice([0, 1, 3, 8, 64]))))
    for bn, bk, sp, x0, smax in cases:
        a = jig_bc.support_marks(bn, bk, sp, x0, smax)
        b = jig_bc.support_marks(bn.copy(), bk.copy(), sp.copy(), x0.copy(), smax)
        assert a == b                                                   # 순수·결정적
        assert a == _backend_marks(tmp_path, bn, bk, sp, x0, smax)      # 백엔드 Case 와 같은 노드·순서·dof
        ties = [i for i, d in a if d == jig_bc.MARK_TIE]
        assert len(ties) <= max(smax, 0) and len(set(i for i, _ in a)) == len(a)   # 노드 중복 없음(겹치면 tie)
        J = np.unique(np.r_[bn[(bk == jig_bc.KIND_TIE) & (bn >= 0) & (bn < len(x0))], sp[(sp >= 0) & (sp < len(x0))]])
        assert ties == [int(i) for i in jg.support_sample(x0, J, smax)]
        assert np.array_equal(bv.jig_support_sample(x0, J, smax), jg.support_sample(x0, J, smax))   # 샘플러 같음(표)
    assert jig_bc.support_marks([], [], [], np.zeros((3, 3)), 5) == []
    with pytest.raises(stg.EslError) as ei:
        jig_bc.support_marks([0, 1], [1], [], np.zeros((3, 3)), 5)
    assert ei.value.code == "INPUT_INVALID"


# ---------------------------------------------------------------- 비용(분해 횟수 = 고정 지그 3D 와 같음 · 시간·메모리 기록)
def _ctx_of(r):
    c = stg.Ctx(_spec(r["out"], r["doe"]))
    t = stg.sc.load_base(c.p("prep"))[0]
    results = stg._collect(c, stg._matrix(c))[0]
    shown = [str(d) for d in U.read_json(c.p("post", "result.json"))["view3d"]]
    return c, t, results, shown


def test_src_3d_cost_same_factorizations_as_fixed(runs, tmp_path, monkeypatch, capsys):
    """방식마다 고정 지그 3D 와 같은 분해 횟수(표시 안 수 + 기준 1 — 노드 순서 = 같은 _jig_sm), 시간·메모리(tracemalloc 피크) 기록."""
    from esl.mech import jig_bc
    r0 = runs["v0244"]
    r = dict(r0, out=str(tmp_path / "_doe"))
    shutil.copytree(r0["out"], r["out"])
    c, t, results, shown = _ctx_of(r)
    n = {"f": 0}
    f0 = jig_bc.factorize

    def fz(sm, BC):
        n["f"] += 1
        return f0(sm, BC)
    monkeypatch.setattr(jig_bc, "factorize", fz)
    rec = {}
    for tag, fn in (("jig", lambda: stg._jig_view3d(c, t, results, shown)),
                    ("jd", lambda: stg._jig_view3d_src(c, t, results, shown, _row("jig_disp"))),
                    ("js", lambda: stg._jig_view3d_src(c, t, results, shown, _row("jig_spring")))):
        n["f"] = 0
        tracemalloc.start()
        t0 = time.perf_counter()
        v3, w = fn()
        sec = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert v3 and not w, tag
        rec[tag] = {"factorize": n["f"], "seconds": round(sec, 4), "peak_mb": round(peak / 2 ** 20, 2),
                    "designs": len(v3[f"view3d_{tag}"]), "ref": len(v3[f"view3d_{tag}_ref"])}
    assert rec["jd"]["factorize"] == rec["js"]["factorize"] == rec["jig"]["factorize"] == rec["jig"]["designs"] + 1
    with capsys.disabled():
        print(f"\n[V-0246 C1 cost, nodes={t.mesh['node_id'].size}] {json.dumps(rec)}", file=sys.stderr)
