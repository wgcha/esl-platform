"""v0.24.4 P2c 강성 스터디 지그 3방식(계약 docs/contracts/esl_jig_case.md §7·§3.7·§3.8, V-0244-JIG-6·11 스터디 부분) +
P3 A3 스터디 load_source → 순위 지표(§9).

합성 스터디(이 파일): 판(300×200, 24×16, XZ 평면 — 법선 Y)에 x 방향 리브 비드 2줄(z = 70·130, 양 끝 30 mm 완화)을 기준 깊이
D0 로 넣은 기준 형상 + 이웃 쉘·솔리드(접촉 영역) + 양 짧은 변(x = 0·300) tie 각 5노드. 설계안 = 비드 깊이 ×0.5·×1·×1.5
(변수 CHASSIS_REAR_BEAD_D_1 = 2·6 → 깊이 D0·D/4, ×1 = 기준 d000 — 공칭 4 는 행렬이 기준 중복으로 뺌).

기록값(이 환경, normal·α 0.01): 아래 test_three_methods_* 머리말 참고(시험이 단언하는 것은 방향·같음뿐).
"""
from __future__ import annotations

import copy
import csv
import json
import os
import time

import numpy as np
import pytest
import synth_doe as sd
import test_jig_stages as T

from esl.doe import DEFAULTS
from esl.doe import stages as stg
from esl.library import _util as U
from esl.mech import jig_bc

NX, NY = 24, 16
D0 = 6.0
SP3 = {"method": "fullfact", "levels": 3, "params": [{"name": "CHASSIS_REAR_BEAD_D_1", "lo": 2.0, "hi": 6.0}]}
FACTOR = {2.0: 0.5, 4.0: 1.0, 6.0: 1.5}
PLATE0 = sd.plate                                              # 원본(시험마다 덮어쓰기 전) — 비드 중복 적용 금지


def bead(X, depth):
    """x 방향 리브 2줄(z = 70·130, 폭 15 mm 가우스, x 30..270 밖으로 완화) — 깊이 증가 = x 방향 굽힘 강성 증가."""
    Y = np.array(X, dtype=float, copy=True)
    ramp = np.clip((X[:, 0] - 30.0) / 20.0, 0, 1) * np.clip((270.0 - X[:, 0]) / 20.0, 0, 1)
    Y[:, 1] += depth * sum(np.exp(-((X[:, 2] - c) / 15.0) ** 2) for c in (70.0, 130.0)) * ramp
    return np.round(Y, 9)


def tie_groups():
    n = NY + 1
    js = (2, 5, 8, 11, 14)
    return [[0 * n + j for j in js], [NX * n + j for j in js]]


@pytest.fixture(scope="module")
def mp_mod():
    m = pytest.MonkeyPatch()
    yield m
    m.undo()


def _bead_world(mp):
    """비드 기준 판 + 가짜 모핑(값 D → 깊이 D0·D/4) + 3수준 행렬."""
    flat = {}

    def plate(**kw):
        m = PLATE0(**kw)
        flat["x"] = np.array(m["x0"], dtype=float, copy=True)
        m["x0"] = bead(flat["x"], D0)
        return m

    def morph(mesh, values, comp="CHASSIS_REAR"):
        D = float(values.get(f"{comp}_BEAD_D_1", 4.0))
        return bead(flat["x"], D0 * D / 4.0)
    mp.setattr(T, "NX", NX)
    mp.setattr(T, "NY", NY)
    mp.setattr(T, "SP", SP3)
    mp.setattr(sd, "plate", plate)
    mp.setattr(sd, "morph_x", morph)


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def new_jig(**over):
    j = copy.deepcopy(DEFAULTS["rank"]["jig"])                # 지금 DEFAULTS = 새 스냅샷(normal·두 방식 — v0.24.5 §12 fixed 제외)
    j["methods"] = ["fixed", "prescribed", "spring"]          # 이 시험 = v0.24.4 세 방식(fixed 다시 켬)
    j.update(over)
    return j


def run_study(root, mp, *, jig=None, metric="jig", doe_extra=None):
    _bead_world(mp)
    mesh, doe = T.build_same(root)
    if doe_extra:
        doe = {**doe, **doe_extra}
    t0 = time.monotonic()
    out, post, ids = T.run(str(root / "o"), doe, mesh, rank=T.rank_snap(metric=metric, jig=jig if jig is not None else new_jig()),
                           groups=tie_groups())
    return {"out": out, "post": post, "ids": ids, "seconds": time.monotonic() - t0, "mesh": mesh, "doe": doe}


def designs(out):
    res = {}
    for d in os.listdir(os.path.join(out, "run", "designs")):
        res[d] = U.read_json(os.path.join(out, "run", "designs", d, "result.json"))
    return res


def worst(per, k):
    return max(float(p[k]) for p in per)


@pytest.fixture(scope="module")
def study(tmp_path_factory, mp_mod):
    calls = {"factorize": 0, "spring_k": 0}
    f0, k0 = jig_bc.factorize, jig_bc.spring_k

    def fz(sm, BC):
        calls["factorize"] += 1
        return f0(sm, BC)

    def sk(*a, **kw):
        calls["spring_k"] += 1
        return k0(*a, **kw)
    mp_mod.setattr(jig_bc, "factorize", fz)
    mp_mod.setattr(jig_bc, "spring_k", sk)
    r = run_study(tmp_path_factory.mktemp("jm"), mp_mod)
    mp_mod.setattr(jig_bc, "factorize", f0)
    mp_mod.setattr(jig_bc, "spring_k", k0)
    r["calls"] = calls
    return r


# ---------------------------------------------------------------- V-0244-JIG-6(스터디) Π 단조성
def test_three_methods_monotone_bead_depth(study):
    """비드 깊이 ×0.5·1·1.5: 세 방식(normal tie) 모두 s = max_i C_<pe>(안) / max_i C_<pe>(기준) 가 엄격 감소, ×1 = 1(1e-9).
    C_<pe> = E_0 + ΔC_mix(기준 per_esl = E_0 = npz E_ref)."""
    res = designs(study["out"])
    b = res["d000"]
    by_f = {FACTOR[float(r["values"]["CHASSIS_REAR_BEAD_D_1"])]: r for d, r in res.items() if d != "d000"}
    assert sorted(by_f) == [0.5, 1.5] and all(r["status"] == "OK" for r in by_f.values())
    by_f[1.0] = b
    rec = {}
    for m, row in jig_bc.METHODS.items():
        pe = stg._jig_pe(row["src"])
        z = U.load_npz(os.path.join(study["out"], "prep", f"{row['src']}.npz"))
        eids = [str(e) for e in z["entry_ids"].tolist()]
        for p in b["per_esl"]:                                  # 기준 C_<pe> = E_0
            assert p[f"C_{pe}"] == pytest.approx(float(z["E_ref"][eids.index(p["entry_id"])]), rel=1e-12)
        s = [worst(by_f[f]["per_esl"], f"C_{pe}") / worst(b["per_esl"], f"C_{pe}") for f in (0.5, 1.0, 1.5)]
        rec[m] = s
        assert s[0] > s[1] > s[2], (m, s)
        assert s[1] == pytest.approx(1.0, abs=1e-9), (m, s)
        for p in by_f[0.5]["per_esl"]:                          # 정보 열 존재(WF·Wg·umax)
            assert {f"WF_{pe}", f"Wg_{pe}", f"umax_{pe}"} <= set(p)
    print("Pi monotone s(x0.5, x1, x1.5):", json.dumps(rec), "study seconds", round(study["seconds"], 2))


def test_files_blocks_views_csv(study):
    out, post = study["out"], study["post"]
    for m, row in jig_bc.METHODS.items():
        jd = U.read_json(os.path.join(out, "prep", f"{row['src']}.json"))
        assert jd["status"] == "ok" and jd["method"] == m and jd["tie_dofs"] == "normal"
        assert jd["rigid_free"] == 0 and jd["bc"]["n_aux"] >= 2 and jd["fix"]["n_jig"] == 10
        assert all(e["energy"]["E"] > 0 for e in jd["entries"])
        z = U.load_npz(os.path.join(out, "prep", f"{row['src']}.npz"))
        assert {"a", "entry_ids", "C_ref", "E_ref", "Cmix_ref", "bc_node", "bc_val", "sp_k", "sp_g", "pattern_sha"} <= set(z)
        assert z["bc_val"].shape[0] == z["a"].shape[0]          # 엔트리마다 값(기준 목표 고정)
        assert (jd["spring"] is not None) == (row["tie_stiff"] != "hard")
    sh = {jig_bc.METHODS[m]["src"]: U.load_npz(os.path.join(out, "prep", f"{jig_bc.METHODS[m]['src']}.npz"))["pattern_sha"]
          for m in jig_bc.METHODS}
    groups = jig_bc.factor_groups(tuple(jig_bc.METHODS))
    for mem in groups.values():                          # 같은 분해 묶음 = 같은 구속 패턴, 다른 묶음 = 다른 패턴
        assert len({str(sh[jig_bc.METHODS[m]["src"]]) for m in mem}) == 1
    assert len({str(v) for v in sh.values()}) == len(groups)
    b = U.read_json(os.path.join(out, "run", "designs", "d000", "result.json"))
    assert b["sm"]["jig"]["status"] == "ok" and set(b["sm"]["jig"]["methods"]) == {r["src"] for r in jig_bc.METHODS.values()}
    jb = post["jig"]
    assert jb["tie_dofs"] == "normal" and set(jb["methods"]) == {r["src"] for r in jig_bc.METHODS.values()}
    assert all(v["status"] == "ok" for v in jb["methods"].values())
    side = U.read_json(os.path.join(out, "post", "jig_view.json"))
    assert set(side["rank_views"]) == {"jig", "full", "jig_disp", "jig_spring"}
    for src in ("jig_disp", "jig_spring"):
        v = side["rank_views"][src]
        assert v["metric"] == stg._jig_src_row(src)["metric"] and v["ranking"]
        assert "C_jig" not in v["ranking"][0] and v["ranking"][0]["umax"] is not None
    rows = list(csv.reader(_read(os.path.join(out, "post", "ranking.csv")).splitlines()))
    head = rows[0]
    assert head[-8:] == stg.JIG_CSV_COLS + ["C_jd", "umax_jd", "C_js", "umax_js"]
    base = next(r for r in rows[1:] if r[0] == "d000")
    assert [float(v) for v in base[-4:]] == pytest.approx([1.0, 1.0, 1.0, 1.0])
    res = designs(out)
    for r in rows[1:]:
        if r[0] == "d000":
            continue
        per, bp = res[r[0]]["per_esl"], res["d000"]["per_esl"]
        assert float(r[-4]) == pytest.approx(worst(per, "C_jd") / worst(bp, "C_jd"), rel=1e-12)
        assert float(r[-2]) == pytest.approx(worst(per, "C_js") / worst(bp, "C_js"), rel=1e-12)
    assert jb["status"] in ("ok", "poor") and post["metric_effective"] == "jig"


def test_factor_sharing_and_spring_k_reuse(study):
    """분해 = 베이스라인 공유 1(fixed·prescribed) + spring 1, 안마다 패턴 묶음 2 — spring k 는 베이스라인 1회(안은 npz sp_k)."""
    n_designs = len(study["ids"]) - 1
    groups = len(jig_bc.factor_groups(tuple(jig_bc.METHODS)))
    diag = 1                                                    # 지그 진단 3D(_jig_diag — 고정 npz 의 BC 로 1회)
    v3 = len(study["post"].get("view3d_jig") or {}) + (1 if study["post"].get("view3d_jig_ref") else 0)
    side = U.read_json(os.path.join(study["out"], "post", "jig_view.json"))     # v0.24.6 §8.1 지그 변위·스프링 3D(사이드카) — 방식마다
    for row in [r_ for r_ in stg.RANK_SOURCES if r_["v3d_store"] == "sidecar"]:   # 고정 3D 와 같은 분해 횟수(표시 안 + 기준 1)
        v3 += len(side.get(row["v3d"][0]) or {}) + (1 if side.get(row["v3d"][2]) else 0)
    assert study["calls"]["spring_k"] == 1
    assert study["calls"]["factorize"] == groups * (1 + n_designs) + diag + v3, study["calls"]
    z = U.load_npz(os.path.join(study["out"], "prep", "jig_spring.npz"))
    assert np.all(z["sp_k"] > 0) and z["sp_k"].ndim == 1


# ---------------------------------------------------------------- V-0244-JIG-11 옛 경로 바이트(새 스냅샷 translation)
def _hash_tree(out):
    import test_jig_move as G
    return G.tree_hashes(out, os.path.dirname(out), lambda rel: rel in ("prep/jig.npz",) or (
        rel.startswith("run/designs/") and rel.endswith("/design.npz")))


def test_translation_new_snapshot_fixed_is_old_path(tmp_path, mp_mod):
    """새 스냅샷 translation: fixed 결과 = 옛 스냅샷과 같은 바이트(prep/jig.npz·jig.json(시간 제외)·per_esl C_jig),
    세 방식이면 prescribed·spring 이 더해질 뿐(옛 경로 fixed 그대로)."""
    import test_jig_move as G
    old = run_study(tmp_path / "a", mp_mod, jig=T.jcfg())
    new3 = run_study(tmp_path / "b", mp_mod, jig=new_jig(tie_dofs="translation"))
    one = run_study(tmp_path / "c", mp_mod, jig=new_jig(tie_dofs="translation", methods=["fixed"]))
    for r in (new3, one):
        assert G.npz_hash(os.path.join(r["out"], "prep", "jig.npz")) == G.npz_hash(os.path.join(old["out"], "prep", "jig.npz"))
        assert G.file_hash(os.path.join(r["out"], "prep", "jig.json"), str(tmp_path)) == \
            G.file_hash(os.path.join(old["out"], "prep", "jig.json"), str(tmp_path))
        ro, rn = designs(old["out"]), designs(r["out"])
        for d in ro:
            assert [p["C_jig"] for p in rn[d]["per_esl"]] == [p["C_jig"] for p in ro[d]["per_esl"]]
    for f in ("post/per_esl.json", "post/ranking.csv"):
        assert G.file_hash(os.path.join(one["out"], f), str(tmp_path / "c")) == \
            G.file_hash(os.path.join(old["out"], f), str(tmp_path / "a")), f
    jd = U.read_json(os.path.join(new3["out"], "prep", "jig_disp.json"))
    assert jd["status"] == "ok" and jd["tie_dofs"] == "translation" and jd["bc"]["shared_factor"] is True
    assert not os.path.exists(os.path.join(one["out"], "prep", "jig_disp.json"))
    s = [worst(designs(new3["out"])[d]["per_esl"], "C_jd") for d in sorted(designs(new3["out"]))]
    assert all(v > 0 for v in s)


# ---------------------------------------------------------------- 실패 격리
def test_spring_failure_isolated(tmp_path, mp_mod):
    """spring 만 베이스라인 예외 → jig_spring fallback(그 방식만), jig·jig_disp 정상·보기 있음, C_js 만 null."""
    k0 = jig_bc.spring_k

    def boom(*a, **kw):
        raise RuntimeError("synthetic spring crash")
    mp_mod.setattr(jig_bc, "spring_k", boom)
    try:
        r = run_study(tmp_path / "a", mp_mod)
    finally:
        mp_mod.setattr(jig_bc, "spring_k", k0)
    out = r["out"]
    js = U.read_json(os.path.join(out, "prep", "jig_spring.json"))
    assert js["status"] == "fallback" and js["code"] == "JIG_SKIPPED" and "synthetic spring crash" in js["detail"]
    for src in ("jig", "jig_disp"):
        assert U.read_json(os.path.join(out, "prep", f"{src}.json"))["status"] == "ok"
    res = designs(out)
    assert all(rr["status"] == "OK" for rr in res.values())
    for rr in res.values():
        assert all(p["C_js"] is None and p["C_jd"] is not None and p["C_jig"] is not None for p in rr["per_esl"])
    side = U.read_json(os.path.join(out, "post", "jig_view.json"))
    assert set(side["rank_views"]) == {"jig", "full", "jig_disp"}
    assert r["post"]["jig"]["methods"]["jig_spring"]["status"] == "fallback"
    assert any("JIG_SKIPPED" in str(w) for w in res["d000"]["warnings"])


def test_design_spring_group_failure_isolated(tmp_path, mp_mod):
    """안 단계에서 spring 묶음(스프링 행이 있는 BC) 분해만 예외 → 그 안 C_js 만 null + JIG_DESIGN_FAILED(다른 묶음·출처 무영향)."""
    f0 = jig_bc.factorize
    state = {"base_done": False}

    def fz(sm, BC):
        if state["base_done"] and np.asarray(BC["sp_node"]).size:
            raise RuntimeError("synthetic design spring crash")
        return f0(sm, BC)
    b0 = stg._jig_methods_base

    def base(*a, **kw):
        out = b0(*a, **kw)
        state["base_done"] = True
        return out
    mp_mod.setattr(jig_bc, "factorize", fz)
    mp_mod.setattr(stg, "_jig_methods_base", base)
    try:
        r = run_study(tmp_path, mp_mod)
    finally:
        mp_mod.setattr(jig_bc, "factorize", f0)
        mp_mod.setattr(stg, "_jig_methods_base", b0)
    res = designs(r["out"])
    assert all(p["C_js"] is not None for p in res["d000"]["per_esl"])
    for d, rr in res.items():
        if d == "d000":
            continue
        assert rr["status"] == "OK"
        assert all(p["C_js"] is None and p["C_jd"] is not None and p["C_jig"] is not None for p in rr["per_esl"])
        assert any("JIG_DESIGN_FAILED" in str(w) and "jig_spring" in str(w) for w in rr["warnings"])
    side = U.read_json(os.path.join(r["out"], "post", "jig_view.json"))
    assert {"jig", "jig_disp"} <= set(side["rank_views"])
    assert side["rank_views"]["jig_spring"]["n_ok"] == 0 and side["rank_views"]["jig_spring"]["n_failed"]["js"] == len(res) - 1


# ---------------------------------------------------------------- P3 A3 스터디 load_source → 순위 지표(§9)
def test_load_source_sets_rank_metric(tmp_path, mp_mod):
    """load_source = jig_disp(스냅샷 methods 에 prescribed 없음 → 코어가 보장): 순위·ranking.csv·보고서 기준 = jd(RANK_SOURCES 열),
    순위 = 사이드카 jig_disp 보기와 같은 순서. 없음 = 지금 동작(metric_effective = rank.metric)."""
    r = run_study(tmp_path, mp_mod, jig=new_jig(methods=["fixed"]), doe_extra={"load_source": "jig_disp"})
    post, out = r["post"], r["out"]
    assert os.path.isfile(os.path.join(out, "prep", "jig_disp.json"))
    assert post["load_source"] == "jig_disp" and post["metric_effective"] == "jd"
    side = U.read_json(os.path.join(out, "post", "jig_view.json"))
    assert [x["id"] for x in post["ranking"]] == [x["id"] for x in side["rank_views"]["jig_disp"]["ranking"]]
    assert [x["score"] for x in post["ranking"]] == pytest.approx([x["score"] for x in side["rank_views"]["jig_disp"]["ranking"]])
    rows = list(csv.reader(_read(os.path.join(out, "post", "ranking.csv")).splitlines()))
    assert "C_E0" in rows[0]
    res = designs(out)
    ci = rows[0].index("C_E0")
    for row in rows[1:]:
        if res[row[0]]["status"] == "OK":
            want = next(p["C_jd"] for p in res[row[0]]["per_esl"] if p["entry_id"] == "E0")
            assert float(row[ci]) == pytest.approx(want, rel=1e-12)
    assert "지그 변위" in _read(os.path.join(out, "report.html"))


def test_load_source_bforce_unready_falls_back(tmp_path, mp_mod):
    """load_source 출처 값이 베이스라인에 없으면(경계력 미계산) 순위 = 기본 지표 + 경고 LOAD_SOURCE_FALLBACK(스터디 실패 아님)."""
    r = run_study(tmp_path, mp_mod, doe_extra={"load_source": "bforce"})
    post = r["post"]
    assert post["load_source"] == "bforce" and post["metric_effective"] == "jig"
    assert any(str(w).startswith("LOAD_SOURCE_FALLBACK") for w in post["warnings"])


# ---------------------------------------------------------------- V-0244-JIG-10 이름 분기 없음(스터디·A3 코드)
def test_no_method_or_source_name_branch_in_study_and_a3_code():
    """스터디 지그 3방식·load_source·source_load·opt 지그 지지 코드에 방식·출처·구속 성분 이름 문자열 비교 없음(열 값만)."""
    import inspect
    import re

    from esl import view3d_src
    from esl.library import source_load as srcl
    from esl.opt import target as tg
    names = "|".join(list(jig_bc.METHODS) + list(jig_bc.TIE_DOFS) + list(view3d_src.KEYS))
    pat = re.compile(rf"""(==|!=|\bin\b)\s*\(?\s*["']({names})["']""")
    for fn in (stg._jig_plan, stg._jig_single_legacy, stg._jig_legacy, stg._jig_tie_legacy, stg._jig_stage,
               stg._jig_method_base, stg._jig_methods_base, stg._jig_design_multi, stg._jig_apply_multi, stg._jig_apply,
               stg._jig_post, stg._jig_csv_arg, stg._jig_resp_rows, stg._jig_any_ready, stg._jig_extras,
               stg._ls_rank_input, stg._ns_merge, tg.jig_support_reason, tg.jig_supports, tg.source_supports):
        assert not pat.findall(inspect.getsource(fn)), fn.__name__
    src = inspect.getsource(srcl)
    assert not pat.findall(src)


# ---------------------------------------------------------------- v0.24.5 §12 출처 계산 제외(V-0245-VT-16 스터디)
def test_v0245_default_snapshot_excludes_fixed_bforce_fint(study, tmp_path_factory, mp_mod, capsys):
    """새 기본 스냅샷(rank.jig = DEFAULTS — methods [prescribed, spring], bead_doe bforce·fint 기본 끔): 지그 고정(C_jig·prep/jig.json)·
    경계력·내력 사이드카 계산 없음, 기본 순위 metric jig = 첫 계산 방식 jig_disp(jd). 세 방식 실행(fixed 다시 켬)과 jd 값 같음."""
    r = run_study(tmp_path_factory.mktemp("jm_def"), mp_mod, jig=copy.deepcopy(DEFAULTS["rank"]["jig"]))
    out, post = r["out"], r["post"]
    assert not os.path.exists(os.path.join(out, "prep", "jig.json")) and not os.path.exists(os.path.join(out, "prep", "jig.npz"))
    for src in ("jig_disp", "jig_spring"):
        assert U.read_json(os.path.join(out, "prep", f"{src}.json"))["status"] == "ok"
    for ns in stg.NODAL_SOURCES:
        assert not os.path.exists(os.path.join(out, "post", stg._nf(ns, "view")))
        assert not os.path.exists(os.path.join(out, "prep", stg._nf(ns, "prep")))
    assert post["metric_effective"] == "jd" and post["metric"] == "jd"               # 순위 = C_jd
    b = designs(out)["d000"]
    assert all(p.get("C_jig") is None and p.get("C_jd") is not None for p in b["per_esl"])
    b3 = designs(study["out"])["d000"]
    assert [p["C_jd"] for p in b["per_esl"]] == pytest.approx([p["C_jd"] for p in b3["per_esl"]], rel=1e-12)
    assert study["post"]["metric_effective"] == "jig"                       # fixed 가 첫째 = 옛 동작 그대로
    with capsys.disabled():
        print(f"\n[VT-16 study time] default(2 methods) {r['seconds']:.2f}s vs 3 methods {study['seconds']:.2f}s")
