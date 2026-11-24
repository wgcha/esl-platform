"""v0.24.3 ④ 검증 출처별(계약 docs/contracts/esl_validate_sources.md §14.1 P1, V-0243-VAL-n).

V-1 골든: 합성 Case 4종(bf = 경계력·내력 자료 있음, plain = 없음, never = ``full_solve: never``, stress = 응력 대체)의
05_val 루트(validation.json — created_at·full_solve.mem_avail 제외, validation.csv·compare.csv·compare_*.npz 배열),
06_export(생성 시각 줄 제외)·07_report(생성 시각·경로 정규화, 출처 표 블록 제외)·단계 요약 기존 키 = v0.24.2 코드 기록값.
골든은 코어 변경 **전**(계약 커밋 d1eb8927 = v0.24.2 검증 코드)에 ``ESL_GOLDEN_RECORD=1`` 로
``tests/fixtures/val_src/golden_v0242.json`` 에 기록했다. 다시 기록하면 안 된다: 깨지면 full 결과가 바뀐 것이다.

npz 는 zip 항목 시각이 들어가 파일 sha 가 실행마다 다르므로 배열(이름·dtype·shape·바이트) 해시로 비교한다.

v0.24.5(esl_validate_tiers.md §5-6): 판정 단계·MAC 의 의도 차이(validation.json·validation.csv·단계 요약 새 키·옛 단일 기준 판정,
보고서 5절 판정 머리)는 ``vt_compat`` 로 v0.24.4 형식으로 되돌린 뒤 같은 골든과 비교한다(보고서 = 되돌린 문서로 다시 그린 것).
설정은 골든 기록 당시 예시 값 ``disp_rms_rel_max: 0.01`` 을 명시(``vt_golden.cfg_text``).
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
import vt_compat as VC
import vt_golden as VG
from esl import pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(ROOT, "config", "esl.example.yaml")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


CFG64_TEXT = VG.cfg_text()          # 예시 yaml(float64) + disp_rms_rel_max 0.01(골든 기록 당시 예시 값 — v0.24.5 0.05)
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "val_src", "golden_v0242.json")
TAG = "golden-v0243"
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
# 출처 표(v0.24.3 07_report 5절 끝 — case_report 가 이 표식으로 감쌈). 골든 비교 때 떼어 내고 기존 부분만 본다.
_SRC_BLOCK = re.compile(r"<!--val-src-->.*?<!--/val-src-->", re.DOTALL)
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
        doc = VC.back_validation(json.load(fh))                 # v0.24.5 의도 차이 되돌림
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
    out = os.path.dirname(os.path.dirname(path))
    if name == "validation.csv":                                # v0.24.5 의도 차이 되돌림(같은 쓰기 함수로 다시 씀)
        b = VC.back_csv(b.decode("utf-8"), path, out).encode()
    if name == "report.html":
        html = VC.back_report_html(out)                         # 되돌린 문서로 다시 그린 보고서(새 형식일 때)
        return _sha(_SRC_BLOCK.sub("", _norm_text(b.decode("utf-8") if html is None else html, root)).encode())
    if os.path.basename(os.path.dirname(path)) == pipeline.D_EXPORT:
        return _sha(_norm_text(b.decode("utf-8"), root).encode())
    return _sha(b)


def norm_summary(summ: dict, val_dir: str | None = None) -> dict:
    """run.json stages.validate.summary 의 v0.24.2 키만(새 키 sources 제외 — v0.24.5 mac·cond_reasons 는 되돌림), solver 의
    시각·메모리 값 제외."""
    if val_dir is not None:
        summ = VC.back_summary(summ, val_dir)
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
    return {"files": files, "summary": norm_summary(rj["stages"]["validate"]["summary"], vd)}


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


# ====================================================================== 공통 도구(검증만 다시 돌리기)
def _j(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return json.load(fh)


def _wj(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


def _revalidate(r, *, cfg_text=None, tmp=None):
    cfg = r["cfg"]
    if cfg_text is not None:
        cfg = os.path.join(tmp, "cfg_v.yaml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(cfg_text)
    return pipeline.run(config_path=cfg, rad=r["c"]["rad"], results=r["c"]["csv"], out=r["out"], stage="validate",
                        echo=lambda *_: None)


def _rows(out):
    return {x["key"]: x for x in _j(out, pipeline.D_VAL, "sources.json")["rows"]}


def _root_hashes(out, root):
    return {k: v for k, v in snapshot(out, root)["files"].items() if k.startswith(pipeline.D_VAL + "/")}


def _gold(name):
    with open(GOLDEN, encoding="utf-8") as fh:
        g = json.load(fh)["cases"][name]
    return {k: v for k, v in g["files"].items() if k.startswith(pipeline.D_VAL + "/")}


class _Capture:
    """FactorizedSolve.solve(출처 해)·ShellModel.solve(legacy 해) 호출 기록 — 응답 독립 재계산용."""

    def __init__(self, monkeypatch, fail_at=None):
        from esl.mech import shell as _shell
        self.fs, self.leg, self.fail_at = [], [], fail_at
        orig_fs, orig_leg = _shell.FactorizedSolve.solve, _shell.ShellModel.solve
        self.n_factor = 0
        orig_fac = _shell._factorize

        def fs_solve(h, F):
            if self.fail_at is not None and len(self.fs) == self.fail_at:
                self.fs.append(None)
                raise RuntimeError("주입된 출처 해 예외")
            u, R = orig_fs(h, F)
            self.fs.append((np.array(F), u.copy(), R.copy()))
            return u, R

        def leg_solve(sm, F, spc):
            u, R = orig_leg(sm, F, spc)
            self.leg.append((np.array(F), u.copy(), R.copy()))
            return u, R

        def fac(A, *a, **k):
            if k.get("label", a[2] if len(a) > 2 else None) == "K_ff":
                self.n_factor += 1
            return orig_fac(A, *a, **k)

        monkeypatch.setattr(_shell.FactorizedSolve, "solve", fs_solve)
        monkeypatch.setattr(_shell.ShellModel, "solve", leg_solve)
        monkeypatch.setattr(_shell, "_factorize", fac)


# ====================================================================== V-3·V-7 정의·분해
def test_v0243_val_3_7_source_metrics_independent_and_one_factorization(golden_runs, tmp_path, monkeypatch):
    """출처 지표 = 같은 정의로 독립 재계산(bforce·fint), ESL 재현 정의 일치, 3-2-1 분해 1회, legacy = sm.solve 그대로."""
    from esl.mech import kabsch

    r = copy_case(golden_runs, "bf", str(tmp_path))
    cap = _Capture(monkeypatch)
    rec = _revalidate(r)
    out = r["out"]
    assert _root_hashes(out, golden_runs["bf"]["root"]) == _gold("bf")             # full 바이트 동일
    assert cap.n_factor == 1 and len(cap.leg) == 1 and len(cap.fs) == 2            # 분해 1회·legacy 해 1·출처 해 2
    sj = _j(out, pipeline.D_VAL, "sources.json")
    assert sj["schema"] == "esl/val_sources/1" and sj["default"] == "full" and sj["enabled"] is True
    assert sj["esl_ref"] == TAG and [x["key"] for x in sj["rows"]] == list(pipeline._vs.KEYS)   # v0.24.4 KEYS 6(의도 변경)
    g = sj["solve"]["groups"]
    assert len(g) == 1 and g[0]["support"] == "bc321" and g[0]["keys"] == ["full", "bforce", "fint"]
    assert set(g[0]["solve_s"]) == {"full", "bforce", "fint"} and g[0]["factor_s"] >= 0
    assert set(sj["solve"]["eval_s"]) == {"full", "bforce", "fint"} and sj["solve"]["decision"]["run"] is True
    summ = rec["stages"]["validate"]["summary"]
    assert "n_factorizations" not in summ["solver"]
    assert set(summ["sources"]) == {"jig", "jig_disp", "jig_spring", "bforce", "fint"}
    root = _j(out, pipeline.D_VAL, "validation.json")
    model = np.load(os.path.join(out, pipeline.D_EXTRACT, "model.npz"), allow_pickle=False)
    X0, nid = model["x0"], model["node_id"]
    u_rel = np.load(os.path.join(out, pipeline.D_ESL, "u_rel.npz"))["u_rel"]
    U = float(np.max(np.linalg.norm(u_rel, axis=1)))
    d_rel, _, _ = kabsch.remove_linear_rigid(X0, u_rel)
    sm = pipeline._shell(pipeline.Context(cfg=pipeline._config.load_config(r["cfg"]), config_path="", rad="",
                                          results="", out=out, ts="", frame=None, support_nodes=None,
                                          echo=lambda *_: None, record={}), pipeline.load_model(out))
    for key, (F_cap, u6, R) in zip(("bforce", "fint"), cap.fs):
        z = np.load(os.path.join(out, pipeline.D_ESL, f"{key}.npz"), allow_pickle=False)
        F = z["f"]
        assert np.array_equal(F_cap, F)
        v = _j(out, pipeline.D_VAL, key, "validation.json")
        m = {x["metric"]: x for x in v["metrics"]}
        d_val, _, _ = kabsch.remove_linear_rigid(X0, u6[:, :3])
        e = np.linalg.norm(d_val - d_rel, axis=1)
        sF = np.linalg.norm(F, axis=1).sum()
        assert m["disp_rms_rel"]["value"] == pytest.approx(np.sqrt(np.mean(e ** 2)) / U, rel=1e-12)
        assert m["disp_max_rel"]["value"] == pytest.approx(e.max() / U, rel=1e-12)
        assert m["reaction_rel"]["value"] == pytest.approx(np.linalg.norm(R, axis=1).sum() / sF, rel=1e-12)
        assert m["reaction_sum_rel"]["value"] == pytest.approx(np.linalg.norm(R.sum(axis=0)) / sF, rel=1e-12)
        assert m["reaction_rel"]["role"] == "judge" and v["criteria"]["reaction_role"] == "judge"
        # ESL 재현 정의와 일치: 검증 reaction_sum_rel = <src>.json recon.reaction_rel, Kabsch 제거 응답 = npz u_val
        diag = _j(out, pipeline.D_ESL, f"{key}.json")
        assert m["reaction_sum_rel"]["value"] == pytest.approx(diag["recon"]["reaction_rel"], rel=1e-9)
        uk, _, _, _ = kabsch.remove_rigid(X0, u6[:, :3])
        assert np.max(np.abs(uk - z["u_val"])) <= 1e-12 * max(np.abs(z["u_val"]).max(), 1e-300)
        # 같은 분해 재사용 해 = 따로 푼 sm.solve(같은 산술 — 비트 동일)
        u_ref, R_ref = sm.solve(F, pipeline._spc_bc321(_Ctx(out), pipeline.load_model(out)))
        assert np.array_equal(u_ref, u6) and np.array_equal(R_ref, R)
        # 출처 공통 값 = full 과 같음
        mr = {x["metric"]: x for x in root["metrics"]}
        for k in ("disp_noise_rel", "u_rel_linear_rigid_rel"):
            assert m[k]["value"] == mr[k]["value"], k
        assert m["noise_force_rel"]["value"] is None and mr["noise_force_rel"]["value"] is not None
        assert v["disp"]["U"] == root["disp"]["U"] == pytest.approx(U)
        assert [(h["rank"], h["elem_id"], h["reason"], h["eps_rad"]) for h in v["hotspots_excluded"]] == \
            [(h["rank"], h["elem_id"], h["reason"], h["eps_rad"]) for h in root["hotspots_excluded"]]
        for k in ("esl_ref", "frame", "noise", "noise_source", "full_solve", "strain_source", "verdict_scheme", "schema"):
            assert v[k] == root[k], k
        tolk = ("reaction_role", "reaction_rel_max", "reaction_warn_rel")        # 출처별 반력 허용치만 다름(D-0.24.3-VAL-18)
        assert {k: x for k, x in v["criteria"].items() if k not in tolk} == {k: x for k, x in root["criteria"].items() if k not in tolk}
        assert root["criteria"]["reaction_rel_max"] == 1e-6 and "reaction_warn_rel" not in root["criteria"]
        # 변형률 참고: ε_val = 이 응답의 막 변형률(extract.layers) — 전 요소 배열·hotspot 값
        fz = np.load(os.path.join(out, pipeline.D_VAL, key, "compare_field.npz"), allow_pickle=False)
        eps = pipeline._solver_eq(sm.strains(u6), v["criteria"]["layers"])
        assert np.allclose(fz["eps_esl"], eps, rtol=1e-12, atol=0)
        assert v["hotspots"] and [h["eps_val"] for h in v["hotspots"]] == \
            [float(eps[int(np.flatnonzero(model["elem_id"] == h["elem_id"])[0])]) for h in v["hotspots"]]
        cz = np.load(os.path.join(out, pipeline.D_VAL, key, "compare_disp.npz"), allow_pickle=False)
        assert np.allclose(cz["d_val"], d_val, rtol=0, atol=1e-15 * U) and np.array_equal(cz["node_id"], nid)
        assert sorted(os.listdir(os.path.join(out, pipeline.D_VAL, key))) == sorted(VAL_FILES)
        assert list(v)[-1] == "src" and v["src"]["key"] == key and v["src"]["load"] == f"04_esl/{key}.npz"
        assert v["src"]["sum_abs_f"] == pytest.approx(sF)
    rows = _rows(out)
    assert rows["full"]["dir"] == "" and rows["full"]["verdict"] == root["verdict"]
    assert rows["full"]["metrics"]["disp_rms_rel"] == {x["metric"]: x for x in root["metrics"]}["disp_rms_rel"]["value"]
    assert rows["bforce"]["comparable"] is False and rows["bforce"]["limits"] == ["BF_TIE_MISSING"]
    assert rows["fint"]["comparable"] is True and rows["fint"]["cond"]["balance"] == "none"
    for k in ("jig", "jig_disp", "jig_spring"):                    # v0.24.4: tie 준비 없는 Case = JIG_NOT_PREPARED(요약 code)
        assert rows[k]["status"] == "unavailable" and rows[k]["code"] == "JIG_NOT_PREPARED" and rows[k]["dir"] is None


def _Ctx(out):
    return pipeline.Context(cfg={}, config_path="", rad="", results="", out=out, ts="", frame=None, support_nodes=None,
                            echo=lambda *_: None, record={})


# ====================================================================== V-5 사유
def _mut_drop_src(out, keys=("bforce", "fint")):
    for k in keys:
        for ext in ("npz", "json"):
            p = os.path.join(out, pipeline.D_ESL, f"{k}.{ext}")
            if os.path.exists(p):
                os.remove(p)


def _mut_summary(out, **sub):
    p = os.path.join(out, pipeline.RUN_JSON)
    rj = _j(p)
    s = rj["stages"]["esl"]["summary"]
    for k, v in sub.items():
        if v is None:
            s.pop(k, None)
        else:
            s[k] = v
    _wj(p, rj)


@pytest.mark.parametrize("case,exp", [
    ("disabled", {"bforce": ("unavailable", "BF_DISABLED", "설정에서 꺼짐(bforce.enabled)"),
                  "fint": ("unavailable", "FINT_DISABLED", "설정에서 꺼짐(bforce.fint.enabled)")}),
    ("extract_failed", {"bforce": ("unavailable", "BF_EXTRACT_FAILED", "보충 실패 — 프레임 6: x"),
                        "fint": ("unavailable", "BF_EXTRACT_SKIPPED", "보충 생략 — 프레임 6: y")}),
    ("diag_failed", {"bforce": ("unavailable", "BF_FAILED", "ValueError: boom"),
                     "fint": ("unavailable", "FINT_NO_DATA", "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가")}),
    ("old_esl", {"bforce": ("unavailable", "V3D_SRC_NOT_RUN", None), "fint": ("unavailable", "V3D_SRC_NOT_RUN", None)}),
])
def test_v0243_val_5_reasons_from_summary_and_diag(golden_runs, tmp_path, case, exp):
    from esl import view3d_src
    r = copy_case(golden_runs, "bf", str(tmp_path))
    out = r["out"]
    _mut_drop_src(out)
    if case == "disabled":
        _mut_summary(out, bforce={"grade": None, "code": "BF_DISABLED"}, fint={"grade": None, "code": "FINT_DISABLED"})
    elif case == "extract_failed":
        _mut_summary(out, bforce={"grade": "none", "code": "BF_EXTRACT_FAILED", "reason": "보충 실패 — 프레임 6: x"},
                     fint={"grade": "none", "code": "BF_EXTRACT_SKIPPED", "reason": "보충 생략 — 프레임 6: y"})
    elif case == "diag_failed":
        _wj(os.path.join(out, pipeline.D_ESL, "bforce.json"), {"schema": "esl/bforce/1", "code": "BF_FAILED",
                                                              "reason": "ValueError: boom"})
        _wj(os.path.join(out, pipeline.D_ESL, "fint.json"), {"schema": "esl/bforce/1", "code": "FINT_NO_DATA",
                                                            "reason": pipeline.FINT_NO_DATA_TEXT})
    else:
        _mut_summary(out, bforce=None, fint=None)
    rec = _revalidate(r)
    rows = _rows(out)
    for key, (st, code, reason) in exp.items():
        reason = reason or view3d_src.REASON_TEXT["V3D_SRC_NOT_RUN"]
        assert (rows[key]["status"], rows[key]["code"], rows[key]["reason"]) == (st, code, reason), key
        assert rows[key]["verdict"] is None and rows[key]["metrics"] is None and rows[key]["dir"] is None
        assert not os.path.exists(os.path.join(out, pipeline.D_VAL, key))
        assert rec["stages"]["validate"]["summary"]["sources"][key]["code"] == code
    assert rows["jig"]["code"] == "JIG_NOT_PREPARED" and rows["jig"]["reason"]
    assert _root_hashes(out, golden_runs["bf"]["root"]) == _gold("bf")
    assert _j(out, pipeline.D_VAL, "sources.json")["solve"]["groups"][0]["keys"] == ["full"]


def test_v0243_val_5_plain_case_no_data(golden_runs):
    """경계력 자료 없는 추출(plain) = ESL 요약 BF_NO_DATA·FINT_NO_DATA 사유, 출처 폴더 없음."""
    out = golden_runs["plain"]["out"]
    rows = _rows(out)
    rj = _j(out, pipeline.RUN_JSON)["stages"]["esl"]["summary"]
    assert rows["bforce"]["status"] == "unavailable" and rows["bforce"]["code"] == "BF_NO_DATA"
    assert rows["bforce"]["reason"] == rj["bforce"]["reason"]
    assert rows["fint"]["code"] == "FINT_NO_DATA" and rows["fint"]["reason"] == rj["fint"]["reason"]
    assert sorted(x for x in os.listdir(os.path.join(out, pipeline.D_VAL))
                  if os.path.isdir(os.path.join(out, pipeline.D_VAL, x))) == []


# ====================================================================== V-6 실패 격리
@pytest.mark.parametrize("how", ["id_mismatch", "nan_load", "solve_exc_first", "solve_exc_second", "write_exc",
                                 "diag_corrupt"])
def test_v0243_val_6_failure_isolation(golden_runs, tmp_path, monkeypatch, how):
    r = copy_case(golden_runs, "bf", str(tmp_path))
    out = r["out"]
    bad = "fint" if how == "solve_exc_second" else "bforce"
    p = os.path.join(out, pipeline.D_ESL, "bforce.npz")
    if how in ("id_mismatch", "nan_load"):
        z = dict(np.load(p, allow_pickle=False))
        if how == "id_mismatch":
            z["node_id"] = z["node_id"][::-1].copy()
        else:
            z["f"] = z["f"].copy()
            z["f"][10, 1] = np.nan
        np.savez_compressed(p, **z)
    elif how in ("solve_exc_first", "solve_exc_second"):
        _Capture(monkeypatch, fail_at=0 if how == "solve_exc_first" else 1)
    elif how == "write_exc":
        orig = pipeline._write_val_files

        def wr(ctx, d, ev, nid):
            if d.endswith("bforce.tmp"):
                with open(os.path.join(d, "validation.json"), "w", encoding="utf-8") as fh:
                    fh.write("{partial")
                raise OSError("디스크 가득(주입)")
            return orig(ctx, d, ev, nid)
        monkeypatch.setattr(pipeline, "_write_val_files", wr)
    else:
        with open(os.path.join(out, pipeline.D_ESL, "bforce.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
    rec = _revalidate(r)
    st = rec["stages"]["validate"]
    assert st["status"] == "done" and st["summary"]["verdict"] == "PASS"
    assert _root_hashes(out, golden_runs["bf"]["root"]) == _gold("bf")             # full 바이트·판정 그대로
    rows = _rows(out)
    other = "bforce" if bad == "fint" else "fint"
    assert rows[bad]["status"] == "failed" and rows[bad]["code"] == "VAL_SRC_FAILED"
    assert rows[bad]["reason"].startswith("출처 검증 계산 실패(") and rows[bad]["dir"] is None
    if how == "nan_load":
        assert "비유한값" in rows[bad]["reason"] and "SOLVER_SINGULAR" not in rows[bad]["reason"]
    assert rows[other]["status"] == "done" and rows[other]["verdict"] == "PASS"
    assert os.path.isfile(os.path.join(out, pipeline.D_VAL, other, "validation.json"))
    assert sorted(os.listdir(os.path.join(out, pipeline.D_VAL))) == sorted(
        ["validation.json", "validation.csv", "compare.csv", "compare_field.npz", "compare_disp.npz", "sources.json",
         other])                                                                    # <bad>·<bad>.tmp 없음
    w = [x for x in st["warnings"] if x.startswith("VAL_SRC_FAILED:")]
    assert len(w) == 1 and w[0].startswith(f"VAL_SRC_FAILED: {bad} ")
    assert st["summary"]["sources"][bad]["status"] == "failed"


@pytest.mark.parametrize("scale,band", [(1e-4, "pass"), (4e-2, "pass"), (1e-1, "warn"), (2.5e-1, "fail")])
def test_v0243_val_q1_fint_reaction_two_stage(golden_runs, tmp_path, scale, band):
    """Q1 수정(D-0.24.3-VAL 출처별 반력 허용치 — fint 주의 5 %·불합격 10 %): 불평형 하중 주입 → 반력 ≤5 % PASS,
    5~10 % PASS + 주의 표식, >10 % REACTION FAIL. full 은 공통 기준 1e-6 그대로(바이트 불변).
    v0.24.5 개정(esl_validate_tiers.md §1.4 — D-0.24.5-VT-4, 의도 변경): 5~10 % = 조건부 PASS(cond_reasons REACTION),
    reaction_warned 유지·REACTION_ABOVE_WARN 은 limits 에 붙이지 않음."""
    r = copy_case(golden_runs, "bf", str(tmp_path))
    out = r["out"]
    p = os.path.join(out, pipeline.D_ESL, "fint.npz")
    z = dict(np.load(p, allow_pickle=False))
    z["f"] = z["f"].copy()
    z["f"][100] += scale * np.abs(z["f"]).max()
    np.savez_compressed(p, **z)
    _revalidate(r)
    v = _j(out, pipeline.D_VAL, "fint", "validation.json")
    reac = next(m["value"] for m in v["metrics"] if m["metric"] == "reaction_rel")
    row = _rows(out)["fint"]
    assert v["criteria"]["reaction_rel_max"] == 0.10 and v["criteria"]["reaction_warn_rel"] == 0.05
    assert row["reaction_tol"] == 0.10 and row["reaction_warn"] == 0.05
    assert (reac > 0.10, 0.05 < reac <= 0.10) == (band == "fail", band == "warn"), reac      # 주입 크기 → 구간(반력 ≈ 0.7·scale)
    if reac > 0.10:
        assert v["verdict"] == "FAIL" and "REACTION" in v["fail_reasons"] and not row["reaction_warned"]
    else:
        assert "REACTION" not in v["fail_reasons"]
        assert row["reaction_warned"] is (reac > 0.05)
        assert ("REACTION" in v["cond_reasons"]) is (reac > 0.05)
        assert "REACTION_ABOVE_WARN" not in row["limits"]
    assert row["fail_reasons"] == v["fail_reasons"] and row["cond_reasons"] == v["cond_reasons"]
    assert _root_hashes(out, golden_runs["bf"]["root"]) == _gold("bf")
    full = _j(out, pipeline.D_VAL, "validation.json")["criteria"]
    assert full["reaction_rel_max"] == 1e-6 and "reaction_warn_rel" not in full


# ====================================================================== V-8 설정
def test_v0243_val_8_settings(golden_runs, tmp_path, monkeypatch):
    from esl import config as cfgm

    rj = _j(golden_runs["bf"]["out"], pipeline.RUN_JSON)
    assert "sources" not in rj["config"]["snapshot"]["validation"]                # 키 없음 = 주입 없음(해시 불변)
    c0 = cfgm.load_config(golden_runs["bf"]["cfg"])
    assert "sources" not in c0["validation"] and cfgm.validation_sources_settings(c0) == {"enabled": True, "reaction_tol": {"fint": 0.10}, "reaction_warn": {"fint": 0.05}}
    base_txt = _read(golden_runs["bf"]["cfg"])
    anchor = "  noise_strain_rel_max: 0.05"
    assert anchor in base_txt
    for extra, ok in (("  sources: {}\n", True), ("  sources: {enabled: false}\n", True),
                      ("  sources: {enabled: 1}\n", False), ("  sources: {foo: true}\n", False)):
        p = str(tmp_path / f"c_{abs(hash(extra))}.yaml")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(base_txt.replace(anchor, extra + anchor, 1))
        if ok:
            cfgm.load_config(p)
        else:
            with pytest.raises(pipeline.EslError) as ei:
                cfgm.load_config(p)
            assert ei.value.code == "CONFIG_INVALID"
    # enabled: false → 출처 풀이 0·행 disabled·full 그대로
    r = copy_case(golden_runs, "bf", str(tmp_path))
    cap = _Capture(monkeypatch)
    rec = _revalidate(r, cfg_text=base_txt.replace(anchor, "  sources: {enabled: false}\n" + anchor, 1),
                      tmp=str(tmp_path))
    assert cap.n_factor == 1 and len(cap.fs) == 0 and len(cap.leg) == 1
    sj = _j(r["out"], pipeline.D_VAL, "sources.json")
    assert sj["enabled"] is False and sj["solve"]["groups"][0]["keys"] == ["full"]
    rows = {x["key"]: x for x in sj["rows"]}
    for k in ("jig", "jig_disp", "jig_spring", "bforce", "fint"):
        assert (rows[k]["status"], rows[k]["code"]) == ("disabled", "VAL_SRC_DISABLED"), k
    assert rows["full"]["status"] == "done"
    assert _root_hashes(r["out"], golden_runs["bf"]["root"]) == _gold("bf")
    assert rec["config"]["snapshot"]["validation"]["sources"] == {"enabled": False}


# ====================================================================== V-9 판정 불가
def test_v0243_val_9_undetermined_never(golden_runs):
    out = golden_runs["never"]["out"]
    sj = _j(out, pipeline.D_VAL, "sources.json")
    assert sj["solve"]["groups"] == [] and sj["solve"]["decision"]["run"] is False
    root = _j(out, pipeline.D_VAL, "validation.json")
    for key in ("bforce", "fint"):
        row = {x["key"]: x for x in sj["rows"]}[key]
        assert row["status"] == "done" and row["verdict"] == "UNDETERMINED" and row["undetermined_reason"] == "NO_FULL_SOLVE"
        v = _j(out, pipeline.D_VAL, key, "validation.json")
        assert v["verdict"] == "UNDETERMINED" and v["undetermined_reason"] == root["undetermined_reason"]
        assert v["field"] is None and v["strain_ref"] is None and v["disp"] is None and v["hotspots"] == []
        assert v["hotspots_excluded"] == [] and v["reactions"] == [] and v["reaction_sum"] is None
        m = {x["metric"]: x for x in v["metrics"]}
        assert m["disp_noise_rel"]["value"] == {x["metric"]: x for x in root["metrics"]}["disp_noise_rel"]["value"]
        assert m["disp_noise_rel"]["value"] is not None
        assert all(m[k]["value"] is None for k in ("disp_rms_rel", "disp_max_rel", "reaction_rel",
                                                     "hotspot1_strain_rel_err", "field_max_err_pct", "field_p90_err_pct"))
        assert sorted(os.listdir(os.path.join(out, pipeline.D_VAL, key))) == ["validation.csv", "validation.json"]


def test_v0243_val_9_zero_disp(golden_runs, tmp_path):
    r = copy_case(golden_runs, "bf", str(tmp_path))
    p = os.path.join(r["out"], pipeline.D_ESL, "u_rel.npz")
    z = dict(np.load(p, allow_pickle=False))
    z["u_rel"] = np.zeros_like(z["u_rel"])
    np.savez_compressed(p, **z)
    _revalidate(r)
    rows = _rows(r["out"])
    assert rows["full"]["undetermined_reason"] == "ZERO_DISP"
    for key in ("bforce", "fint"):
        assert rows[key]["verdict"] == "UNDETERMINED" and rows[key]["undetermined_reason"] == "ZERO_DISP"
        assert sorted(os.listdir(os.path.join(r["out"], pipeline.D_VAL, key))) == ["validation.csv", "validation.json"]


def test_v0243_val_stress_substitute_sources_skip_strain(golden_runs, tmp_path):
    """응력 대체: 출처도 같은 규칙(변형률 참고 전부 생략)."""
    r = copy_case(golden_runs, "stress", str(tmp_path))
    _add_bforce(r["c"], r["c"]["csv"], fint_sign=-1.0)
    pipeline.run(config_path=r["cfg"], rad=r["c"]["rad"], results=r["c"]["csv"], out=r["out"], stage="extract",
                 echo=lambda *_: None)
    for st in ("tstar", "esl", "validate"):
        pipeline.run(config_path=r["cfg"], rad=r["c"]["rad"], results=r["c"]["csv"], out=r["out"], stage=st,
                     frame=synth_case.T_STAR_FRAME, echo=lambda *_: None, tag=TAG)
    for key in ("bforce", "fint"):
        v = _j(r["out"], pipeline.D_VAL, key, "validation.json")
        assert v["strain_source"] == "max_stress" and v["field"]["skipped"] == "STRAIN_FROM_STRESS"
        assert v["strain_ref"]["skipped"] == "STRAIN_FROM_STRESS"
        assert all(x["value"] is None for x in v["metrics"] if x["role"] == "reference")
        assert all(h["rel_err"] is None for h in v["hotspots"] + v["hotspots_excluded"])


# ====================================================================== V-11 내보내기·소요 시간
def test_v0243_val_11_export_unchanged_and_timing(golden_runs):
    out = golden_runs["bf"]["out"]
    gold = json.loads(_read(GOLDEN))["cases"]["bf"]["files"]
    exp = sorted(k[len(pipeline.D_EXPORT) + 1:] for k in gold if k.startswith(pipeline.D_EXPORT + "/"))
    assert sorted(os.listdir(os.path.join(out, pipeline.D_EXPORT))) == exp           # 출처 하중 내보내기 없음(R-VAL-1)
    sj = _j(out, pipeline.D_VAL, "sources.json")
    g = sj["solve"]["groups"][0]
    assert all(isinstance(v, float) and v >= 0 for v in [g["factor_s"], *g["solve_s"].values(),
                                                         *sj["solve"]["eval_s"].values()])
    assert _j(out, pipeline.RUN_JSON)["stages"]["validate"]["elapsed_s"] > 0
