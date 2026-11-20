"""v0.24.4 P2b B2 — Case 지그 3방식의 백엔드 설정·3D 출처 API(계약 esl_jig_case.md §5.4·§11, V-0244-JIG-12·15).

A2b(코어 Case 통합)의 행 형식(§5.4)은 계약대로 가정하고 ``esl.view3d_src`` 의 KEYS·CASE_PLAN 을 이 시험 안에서만 monkeypatch 한다
(코어에 지그 행이 들어온 뒤에도 같은 형식이면 그대로 통과).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from esl_test_support import API
from pydantic import ValidationError
from test_view3d_api import R, Seed, code, mk, world  # noqa: F401  (픽스처 재사용)
from test_view3d_src_api import _esl, _tree, set_forces

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from gen_view3d_fixture import synth_mesh

REPO = Path(__file__).resolve().parents[2]
NEW_KEYS = ("tie_dofs", "methods", "normal_kink_deg", "aux321_dup_deg", "aux_reaction_warn", "spring_k_mode", "spring_alpha",
            "spring_k_value", "spring_alpha_scan")
JIG_KEYS = ("jig", "jig_disp", "jig_spring")


# ================================================================ 설정 거울·검사 (V-0244-JIG-15)
def test_rank_jig_new_keys_defaults_and_mirror_core():
    from esl.mech import jig as core
    from esl_platform.core.config import BeadDoeCfg, BeadDoeRankJigCfg

    d = BeadDoeRankJigCfg().model_dump()
    assert set(core.JIG_NEW_KEYS) == set(NEW_KEYS)
    for k in core.JIG_DEFAULTS:                                   # 이름 일치(옛 키 + 새 키 전부)
        assert k in d, k
    assert set(d) == set(core.JIG_DEFAULTS)
    for k, v in core.JIG_DEFAULTS.items():
        if k == "spring_alpha":                                   # 메인 결정: 기본 0.01(코어 JIG_DEFAULTS 가 1.0 이면 통합 때 맞춤)
            assert d[k] == 0.01 and v in (0.01, 1.0)
        else:
            assert d[k] == v, k
    assert BeadDoeCfg().model_dump()["rank"]["jig"] == d


def test_yaml_examples_mirror_pydantic():
    from esl_platform.core.config import BeadDoeCaseJigCfg, BeadDoeRankJigCfg

    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((REPO / "config" / p).read_text(encoding="utf-8"))["bead_doe"]
        assert y["rank"]["jig"] == BeadDoeRankJigCfg().model_dump(), p
        assert y["case_jig"] == BeadDoeCaseJigCfg().model_dump() == {"enabled": True, "timeout_s": None}, p


def test_example_yaml_loads_and_settings_carry_new_keys():
    from esl_platform.core.config import bead_doe_settings, load_config

    for p in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        cfg = load_config(str(REPO / "config" / p), environ={})
        assert cfg.settings is not None, cfg.error_keys()
        d = bead_doe_settings(cfg.settings)
        assert d["case_jig"] == {"enabled": True, "timeout_s": None}
        assert {k: d["rank"]["jig"][k] for k in NEW_KEYS}["methods"] == ["fixed", "prescribed", "spring"]
    d0 = bead_doe_settings(None)                                  # 섹션 없음 = 기본값(코어 DEFAULTS 에 아직 없는 키도 채움)
    assert d0["case_jig"]["enabled"] is True and d0["rank"]["jig"]["tie_dofs"] == "normal"


@pytest.mark.parametrize("bad", [
    {"tie_dofs": "xyz"}, {"methods": []}, {"methods": ["fixed", "fixed"]}, {"methods": ["fixed", "rigid"]},
    {"methods": ["fixed", "prescribed", "spring", "fixed"]}, {"normal_kink_deg": 0}, {"normal_kink_deg": 180},
    {"aux321_dup_deg": 0}, {"aux321_dup_deg": 90}, {"aux_reaction_warn": -0.1}, {"spring_k_mode": "k"},
    {"spring_alpha": 0.0009}, {"spring_alpha": 0}, {"spring_k_value": 0}, {"spring_k_value": -1.0},
    {"spring_k_mode": "value"}, {"spring_alpha_scan": [0.0001]}, {"unknown_key": 1},
])
def test_rank_jig_new_key_validation(bad):
    from esl_platform.core.config import BeadDoeRankJigCfg

    with pytest.raises(ValidationError):
        BeadDoeRankJigCfg(**bad)


def test_rank_jig_new_key_accepted_values():
    from esl_platform.core.config import BeadDoeRankJigCfg

    ok = BeadDoeRankJigCfg(tie_dofs="translation", methods=["spring"], spring_alpha=1e-3, spring_k_mode="value",
                           spring_k_value=500.0, spring_alpha_scan=[0.01, 0.1, 1.0])
    assert ok.methods == ["spring"] and ok.spring_k_value == 500.0
    assert BeadDoeRankJigCfg(methods=["prescribed"]).methods == ["prescribed"]      # fixed 없이도 가능(§11)


def test_case_jig_cfg_validation():
    from esl_platform.core.config import BeadDoeCaseJigCfg, BeadDoeCfg

    assert BeadDoeCaseJigCfg(enabled=False, timeout_s=120).timeout_s == 120
    for bad in ({"timeout_s": 0}, {"timeout_s": -5}, {"enabled": "maybe"}, {"x": 1}):
        with pytest.raises(ValidationError):
            BeadDoeCaseJigCfg(**bad)
    assert BeadDoeCfg(case_jig={"enabled": False}).case_jig.enabled is False


# ================================================================ import 경로에 scipy 없음
def test_api_import_path_does_not_pull_scipy():
    code_ = ("import sys\n"
             "import esl_platform.api.main, esl_platform.api.services.view3d, esl_platform.core.config\n"
             "from esl_worker import core_adapter\n"
             "core_adapter.view3d_src_plan()\n"
             "bad = sorted(m for m in sys.modules if m == 'scipy' or m.startswith('scipy.'))\n"
             "print('SCIPY', bad[:3])\n")
    r = subprocess.run([sys.executable, "-c", code_], capture_output=True, text=True, timeout=120,
                       env={"PYTHONPATH": ":".join(str(REPO / p) for p in ("backend", "worker", "")), "PATH": "/usr/bin"})
    assert r.returncode == 0, r.stderr[-800:]
    assert "SCIPY []" in r.stdout, r.stdout


def test_jig_support_sample_equals_core():
    from esl.mech.jig import support_sample
    from esl_platform.api.services.view3d import jig_support_sample

    m = synth_mesh(12, 8, bend=0.3, seed=3)
    idx = np.r_[np.arange(0, 80), np.arange(10, 30)]
    for k in (0, 1, 5, 64, 80, 200):
        assert np.array_equal(jig_support_sample(m["x0"], idx, k), support_sample(m["x0"], idx, k)), k
    assert jig_support_sample(m["x0"], np.zeros(0, np.int64), 8).size == 0


# ================================================================ 3D 출처 API (계약 §5.4 행 형식을 monkeypatch)
def _jig_plan() -> tuple[tuple[str, ...], tuple[dict, ...]]:
    from esl import view3d_src as vs

    base = [r for r in vs.CASE_PLAN if r["key"] != "jig"]
    rows = []
    for k in JIG_KEYS:
        rows.append({"key": k, "legacy": False, "load": ("esl", f"{k}.npz", "f"), "target": ("esl", "u_rel.npz", "u_rel"),
                     "resp": ("esl", f"{k}.npz", "u_val"), "recon_tgt": ("esl", "u_rel.npz", "u_rel"), "rigid": "kabsch",
                     "support": "jig", "summary": k, "doc": ("esl", f"{k}.json"), "dir": f"view3d_{k}",
                     "recon_dir": f"view3d_{k}_recon", "na": "JIG_NOT_RUN", "resp_na": "V3D_RESP_SKIPPED", "fallback": False})
    plan = tuple(rows + base)
    return tuple(r["key"] for r in plan), plan


@pytest.fixture()
def jig_plan(monkeypatch):
    from esl import view3d_src as vs

    if all(k in vs.KEYS for k in JIG_KEYS):                    # v0.24.4 통합 후: 코어 CASE_PLAN 이 이미 지그 3행 — 실제 표 그대로(덮어쓰지 않음)
        return vs.KEYS
    keys, plan = _jig_plan()
    monkeypatch.setattr(vs, "KEYS", keys)
    monkeypatch.setattr(vs, "CASE_PLAN", plan)
    if "JIG_NOT_RUN" not in vs.REASON_TEXT:
        monkeypatch.setitem(vs.REASON_TEXT, "JIG_NOT_RUN", "이 ESL 결과에는 지그 ESL 이 없습니다 — ESL 을 다시 계산하면 생깁니다")
    return keys


@pytest.fixture()
def seed(world, engine):  # noqa: F811
    return Seed(world, engine, synth_mesh(12, 8, bend=0.3, tri_every=6, seed=3))


def add_jig(s: Seed, key: str, *, tie: np.ndarray, aux: np.ndarray, scale=1.1, seed_=7) -> dict:
    """04_esl/<key>.npz·.json — 계약 §5.3 의 npz(node_id·f·a·u_val·bc_*·sp_*)와 json(요약 recon)."""
    from esl.mech import bforce as bfm

    rng = np.random.default_rng(seed_)
    m = s.m
    f = m["f"] * scale + rng.normal(size=m["f"].shape)
    uv = m["u_rel"] * 0.95 + rng.normal(size=m["u_rel"].shape) * 1e-3
    bn = np.r_[tie, aux].astype(np.int64)
    bd = np.zeros((bn.size, 3))
    bd[:, 2] = 1.0
    np.savez_compressed(_esl(s) / f"{key}.npz", node_id=m["node_id"], f=f, a=np.ones(3), u_val=uv, bc_node=bn, bc_dir=bd,
                        bc_val=np.zeros(bn.size), bc_kind=np.r_[np.full(tie.size, 1), np.full(aux.size, 2)].astype(np.int8),
                        sp_node=np.zeros(0, np.int64), sp_dir=np.zeros((0, 3)), sp_k=np.zeros(0), sp_g=np.zeros(0),
                        jig_idx=tie, basis_sha=np.array("x"))
    rc = {"status": "ok", "mac": bfm.mac(m["u_rel"], uv), "umax_err": 0.1}
    (_esl(s) / f"{key}.json").write_text(json.dumps({"schema": "esl/case_jig/1", "source": key, "recon": rc}),
                                         encoding="utf-8")
    return {"f": f, "u_val": uv, "recon": rc}


def _rows(c, s: Seed) -> dict:
    r = c.get(f"{API}/esl-runs/{s.run_id}/view3d/sources", headers=R)
    assert r.status_code == 200, r.text
    return {x["key"]: x for x in r.json()["rows"]}


def test_sources_six_rows_old_case_is_jig_not_run(mk, seed, jig_plan):  # noqa: F811
    c = mk()
    before = _tree(seed.dir)
    rows = _rows(c, seed)
    assert list(rows) == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    for k in JIG_KEYS:                                              # 옛 Case(04_esl 에 jig* 없음) = 사유 JIG_NOT_RUN
        assert rows[k]["available"] is False and rows[k]["code"] == "JIG_NOT_RUN" and rows[k]["reason"], k
    assert rows["full"]["available"] is True
    r = c.get(seed.url(), params={"src": "jig_disp"}, headers=R)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "V3D_SOURCE_UNAVAILABLE" and d["src"] == "jig_disp"
    assert d["reason_code"] == "JIG_NOT_RUN"
    assert _tree(seed.dir) == before and not (_esl(seed).parent / "view3d_jig_disp").exists()   # 읽기만 — 폴더 안 만듦


def test_src_unknown_is_404_with_six_keys(mk, seed, jig_plan):  # noqa: F811
    r = mk().get(seed.url(), params={"src": "jig_x"}, headers=R)
    assert r.status_code == 404 and code(r) == "SOURCE_NOT_FOUND"
    assert r.json()["detail"]["keys"] == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]


def test_src_jig_variants_build_own_folder_and_support_markers(mk, seed, engine, jig_plan):  # noqa: F811
    c = mk()
    nid = seed.m["node_id"]
    n = nid.size
    tie = np.arange(0, 80, dtype=np.int64)                          # 80 > jig_support_max(64) → 표식 64개 샘플
    aux = np.array([90, 91, 95], dtype=np.int64)
    leg = c.get(seed.url(), headers=R)
    assert leg.status_code == 200
    legacy_tree = _tree(seed.view_dir)
    jf = {k: add_jig(seed, k, tie=tie if k != "jig_spring" else tie[:10], aux=aux, scale=1.1 + 0.1 * i, seed_=7 + i)
          for i, k in enumerate(JIG_KEYS)}
    set_forces(engine, seed, **{k: {"status": "ok", "method": k} for k in JIG_KEYS})
    rows = _rows(c, seed)
    assert all(rows[k]["available"] and rows[k]["resp"] for k in JIG_KEYS)
    keys_seen = set()
    for k in JIG_KEYS:
        r = c.get(seed.url(), params={"src": k}, headers=R)
        assert r.status_code == 200, r.text
        d = r.json()
        keys_seen.add(d["key"])
        vd = seed.dir / "runs" / seed.run_id / f"view3d_{k}"
        assert (vd / "manifest.json").is_file()
        sup = d["supports"]
        by = {}
        for s_ in sup:
            by.setdefault(s_["dof"], []).append(s_["node_id"])
        n_tie = 10 if k == "jig_spring" else 64
        assert len(by["123"]) == n_tie and sorted(by["ij"]) == sorted(int(nid[i]) for i in aux), k
        assert set(by["123"]) <= {int(nid[i]) for i in (tie[:10] if k == "jig_spring" else tie)}
        mag = np.linalg.norm(jf[k]["f"], axis=1)
        order = np.lexsort((nid, -mag))[:100]
        assert [t["node_id"] for t in d["top"]] == [int(nid[i]) for i in order]          # 행 load 의 F 로 top
        g = c.get(seed.url("/values.bin"), params={"src": k, "key": d["key"]}, headers=R)
        assert g.status_code == 200 and g.content == (vd / "values.bin").read_bytes()
    assert len(keys_seen) == 3 and leg.json()["key"] not in keys_seen                      # 출처마다 키·폴더 독립
    assert _tree(seed.view_dir) == legacy_tree and c.get(seed.url(), headers=R).content == leg.content
    assert n > 80


def test_src_jig_support_is_deterministic_and_ignores_bad_npz(mk, seed, jig_plan):  # noqa: F811
    c = mk()
    tie = np.arange(0, 70, dtype=np.int64)
    add_jig(seed, "jig", tie=tie, aux=np.array([85], dtype=np.int64))
    a = c.get(seed.url(), params={"src": "jig"}, headers=R).json()["supports"]
    shutil_dir = seed.dir / "runs" / seed.run_id / "view3d_jig"
    import shutil

    shutil.rmtree(shutil_dir)
    b = c.get(seed.url(), params={"src": "jig"}, headers=R).json()["supports"]
    assert a == b and len(a) == 65
    # 구속 배열이 범위 밖 인덱스를 담아도 표식에서만 빠지고 3D 는 계속
    z = dict(np.load(_esl(seed) / "jig.npz"))
    z["bc_node"] = np.r_[z["bc_node"], [10 ** 9, -4]].astype(np.int64)
    z["bc_kind"] = np.r_[z["bc_kind"], [1, 2]].astype(np.int8)
    z["bc_dir"] = np.r_[z["bc_dir"], [[0, 0, 1.0], [0, 0, 1.0]]]
    z["bc_val"] = np.r_[z["bc_val"], [0.0, 0.0]]
    np.savez_compressed(_esl(seed) / "jig.npz", **z)
    shutil.rmtree(shutil_dir)
    d = c.get(seed.url(), params={"src": "jig"}, headers=R).json()
    assert len(d["supports"]) == 65


def test_support_files_table_has_bc_and_jig():
    from esl_platform.api.services import view3d as v

    assert v.SUPPORT_FILES["bc"] == ("03_bc", "support.json") and "jig" in v.SUPPORT_FILES and v.SUPPORT_FILES["jig"] is None
    assert (v.JIG_KIND_TIE, v.JIG_KIND_AUX) == (1, 2)
    from esl.mech import jig_bc

    assert (jig_bc.KIND_TIE, jig_bc.KIND_AUX) == (v.JIG_KIND_TIE, v.JIG_KIND_AUX)


def test_openapi_dump_is_current():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "dump_openapi.py"), "--check"], capture_output=True, text=True,
                       timeout=300, env={"PYTHONPATH": ":".join(str(REPO / p) for p in ("backend", "worker", "")),
                                         "PATH": "/usr/bin"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_copy_independent_of_defaults():
    from esl_platform.core.config import BeadDoeRankJigCfg

    a = BeadDoeRankJigCfg()
    a.methods.append("x")                                           # 기본 목록이 인스턴스 간 공유되지 않음
    assert BeadDoeRankJigCfg().methods == ["fixed", "prescribed", "spring"]
    assert copy.deepcopy(a).methods == a.methods
