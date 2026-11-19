"""v0.24.1 3D 하중 출처 코어(계약 esl_view3d_sources.md §2·§3, V-0241-V3D-1·2·4·5)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from esl import view3d
from esl import view3d_src as vs
from esl.errors import EslError
from esl.mech import bforce as bfm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- V-1 recon_fields
def test_recon_fields_synthetic_cases():
    rng = np.random.default_rng(3)
    t = rng.normal(size=(40, 3))
    r = view3d.recon_fields(t, t)
    assert np.all(r["err"] == 0) and r["mac"] == pytest.approx(1.0) and r["umax_err"] == 0.0 and r["err_max"] == 0.0
    r = view3d.recon_fields(t, 2 * t)
    assert r["mac"] == pytest.approx(1.0) and r["umax_err"] == pytest.approx(1.0)
    assert r["fit_max"] == pytest.approx(2 * r["tgt_max"]) and r["umax_tgt"] == r["tgt_max"]
    a = np.zeros((4, 3))
    b = np.zeros((4, 3))
    a[:, 0] = 1.0
    b[:, 1] = 1.0
    assert view3d.recon_fields(a, b)["mac"] == 0.0                                       # 직교
    z = view3d.recon_fields(np.zeros((5, 3)), t[:5])
    assert z["mac"] is None and z["umax_err"] is None                                   # 영


def test_recon_fields_equal_bforce_definitions():
    rng = np.random.default_rng(11)
    for _ in range(5):
        t, f = rng.normal(size=(200, 3)), rng.normal(size=(200, 3))
        r = view3d.recon_fields(t, f)
        rep = bfm.recon_report(t, f, None, np.ones((200, 3)))
        assert abs(r["mac"] - rep["mac"]) <= 1e-12 and abs(r["umax_err"] - rep["umax_err"]) <= 1e-12
        assert abs(r["mac"] - bfm.mac(t, f)) <= 1e-12
        assert np.array_equal(r["err"], f - t) and r["err_max"] == pytest.approx(np.linalg.norm(f - t, axis=1).max())
    with pytest.raises(EslError):
        view3d.recon_fields(np.zeros((3, 3)), np.zeros((4, 3)))


# ---------------------------------------------------------------- V-2 pack_disp·build_recon
def test_pack_disp_roundtrip_alignment_zero():
    rng = np.random.default_rng(1)
    n = 7                                                   # 7×3×2 = 42 B → 다음 배열 offset 정렬 필요
    a, b = rng.normal(size=(n, 3)) * 5, np.zeros((n, 3))
    buf, arrays = view3d.pack_disp([("tgt", a), ("fit", b), ("err", -a)])
    assert [x["key"] for x in arrays] == ["tgt", "fit", "err"] and all(x["offset"] % 4 == 0 for x in arrays)
    assert len(buf) % 4 == 0 and arrays[1]["offset"] == 44 and arrays[1]["scale"] == [0.0, 0.0, 0.0]
    back = view3d.unpack_disp(buf, arrays, n)
    s = np.asarray(arrays[0]["scale"])
    assert np.all(np.abs(back["tgt"] - a) <= s / 2 + 1e-15) and not back["fit"].any()
    assert np.allclose(back["err"], -back["tgt"])
    # u 규칙 = pack_values 의 u(같은 배율·같은 양자화)
    vb, va = view3d.pack_values(np.zeros(n), np.zeros(n), np.zeros(n), a)
    u = va[3]
    assert u["scale"] == arrays[0]["scale"]
    assert vb[u["offset"]:u["offset"] + n * 6] == buf[:n * 6]


def test_build_recon_writes_bin_then_json(tmp_path, monkeypatch):
    rng = np.random.default_rng(2)
    n = 30
    nid = np.arange(n) + 100
    t, f = rng.normal(size=(n, 3)), rng.normal(size=(n, 3))
    d = str(tmp_path / "r")
    doc = view3d.build_recon(d, node_id=nid, u_tgt=t, u_fit=f, key="k1", src="bforce", rigid="kabsch", esl_run_id="r1")
    assert sorted(os.listdir(d)) == ["recon.bin", "recon.json"]
    with open(os.path.join(d, "recon.json"), encoding="utf-8") as fh:
        js = json.load(fh)
    assert js == doc and js["schema"] == view3d.RECON_SCHEMA and js["recon_version"] == view3d.RECON_VERSION
    assert set(js) == {"schema", "recon_version", "key", "src", "esl_run_id", "n_nodes", "rigid", "bytes", "arrays",
                       "ranges", "mac", "umax_tgt", "umax_fit", "umax_err"}
    assert js["bytes"] == os.path.getsize(os.path.join(d, "recon.bin")) and js["n_nodes"] == n
    with open(os.path.join(d, "recon.bin"), "rb") as fh:
        back = view3d.unpack_disp(fh.read(), js["arrays"], n)
    for k, v in (("tgt", t), ("fit", f), ("err", f - t)):
        s = np.asarray(next(a for a in js["arrays"] if a["key"] == k)["scale"])
        assert np.all(np.abs(back[k] - v) <= s / 2 + 1e-15), k
    assert js["mac"] == pytest.approx(bfm.mac(t, f), abs=1e-14)
    # 부분 쓰기: json 쓰기 전에 실패하면 json 없음(bin 이 먼저)
    real = json.dump

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(view3d.json, "dump", boom)
    d2 = str(tmp_path / "r2")
    with pytest.raises(OSError):
        view3d.build_recon(d2, node_id=nid, u_tgt=t, u_fit=f, key="k", src="s", rigid="kabsch")
    assert os.path.isfile(os.path.join(d2, "recon.bin"))
    assert not os.path.isfile(os.path.join(d2, "recon.json")) or os.path.getsize(os.path.join(d2, "recon.json")) == 0
    monkeypatch.setattr(view3d.json, "dump", real)
    with pytest.raises(EslError) as ei:
        view3d.build_recon(d2, node_id=nid, u_tgt=t[:-1], u_fit=f, key="k", src="s", rigid="kabsch")
    assert ei.value.code == "OUTPUT_INCONSISTENT"
    bad = t.copy()
    bad[0, 0] = np.nan
    with pytest.raises(EslError) as ei:
        view3d.build_recon(d2, node_id=nid, u_tgt=bad, u_fit=f, key="k", src="s", rigid="kabsch")
    assert ei.value.code == "OUTPUT_INVALID"


# ---------------------------------------------------------------- V-4 계획 표
def test_keys_equal_rank_sources_and_plan_columns():
    from esl.doe import stages as stg

    assert vs.KEYS == tuple(r["key"] for r in stg.RANK_SOURCES)
    assert tuple(r["key"] for r in vs.CASE_PLAN) == vs.KEYS
    assert all(set(r) == set(vs.COLUMNS) for r in vs.CASE_PLAN)
    leg = [r for r in vs.CASE_PLAN if r["legacy"]]
    assert len(leg) == 1 and leg[0]["dir"] == "view3d" and vs.plan(None) is leg[0] and vs.legacy_key() == "full"
    assert [r["key"] for r in vs.CASE_PLAN if r["fallback"]] == [leg[0]["key"]]
    dirs = [d for r in vs.CASE_PLAN for d in (r["dir"], r["recon_dir"]) if d]
    assert len(dirs) == len(set(dirs))                                                   # 출처마다 다른 캐시 폴더
    with pytest.raises(EslError) as ei:
        vs.plan("xyz")
    assert ei.value.code == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize("mut", ["drop_col", "two_legacy", "order", "bad_loc"])
def test_check_plan_rejects_invalid(mut):
    rows = [dict(r) for r in vs.CASE_PLAN]
    if mut == "drop_col":
        rows[2].pop("resp_na")
    elif mut == "two_legacy":
        rows[2]["legacy"] = True
    elif mut == "order":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[2]["resp"] = ("disk", "x.npz", "u")
    with pytest.raises(EslError) as ei:
        vs.check_plan(tuple(rows))
    assert ei.value.code == "CONFIG_INVALID"


def test_import_graph_independent():
    code = ("import sys, numpy as np; import esl.view3d, esl.view3d_src as vs; "
            "esl.view3d.recon_fields(np.ones((3,3)), np.ones((3,3))); "
            "vs.case_status(vs.plan('full'), None, {}); "
            "bad = [m for m in sys.modules if m.startswith(('esl.doe', 'esl.pipeline', 'esl_platform', 'esl_worker'))]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": ROOT}, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------- V-5 case_status
HAVE_ALL = {"model": True, "load": True, "target": True, "resp": True, "recon_tgt": True}
HAVE_NO_RESP = {**HAVE_ALL, "resp": False}
HAVE_NONE = {**HAVE_ALL, "load": False, "resp": False}


@pytest.mark.parametrize("have,summ,doc_reason,exp", [
    (HAVE_ALL, {"recon": "ok"}, None, (True, None, True, None)),
    (HAVE_NO_RESP, {"recon": "skipped"}, "MEMORY", (True, None, False, "V3D_RESP_SKIPPED")),
    (HAVE_NO_RESP, None, None, (True, None, False, "V3D_RESP_SKIPPED")),
    (HAVE_NONE, None, None, (False, "V3D_SRC_NOT_RUN", False, "V3D_SRC_NOT_RUN")),
    (HAVE_NONE, {"grade": None, "code": "BF_DISABLED"}, None, (False, "BF_DISABLED", False, "BF_DISABLED")),
    (HAVE_NONE, {"grade": "none", "code": "BF_NO_DATA", "reason": "접촉력 출력 없음"}, None,
     (False, "BF_NO_DATA", False, "BF_NO_DATA")),
    (HAVE_NONE, {"grade": "contact", "code": "BF_FAILED", "reason": "SOLVER_FAILED"}, None,
     (False, "BF_FAILED", False, "BF_FAILED")),
    (HAVE_ALL, {"grade": "none", "code": "BF_NO_DATA", "reason": "x"}, None, (True, None, True, None)),
])
def test_case_status_table_bforce(have, summ, doc_reason, exp):
    st = vs.case_status(vs.plan("bforce"), summ, have, doc_reason)
    assert (st["available"], st["code"], st["resp"], st["resp_code"]) == exp
    if not st["available"]:
        assert st["reason"] and st["resp_reason"] == st["reason"]
    if summ and summ.get("reason") and not st["available"]:
        assert st["reason"] == summ["reason"]                                             # Case 요약 reason 그대로
    if exp[3] == "V3D_RESP_SKIPPED":
        assert st["resp_reason"].startswith(vs.REASON_TEXT["V3D_RESP_SKIPPED"])
        assert ("(MEMORY)" in st["resp_reason"]) == (doc_reason is not None)
    if exp[1] == "BF_DISABLED":
        assert st["reason"] == vs.REASON_TEXT["BF_DISABLED"]


def test_case_status_jig_full_and_old_run():
    j = vs.case_status(vs.plan("jig"), None, HAVE_ALL)
    assert (j["available"], j["code"], j["reason"]) == (False, "V3D_STUDY_ONLY", vs.REASON_TEXT["V3D_STUDY_ONLY"])
    f = vs.case_status(vs.plan("full"), None, {**HAVE_ALL, "resp": False, "recon_tgt": False})
    assert f["available"] and not f["resp"] and f["resp_code"] == "V3D_RESP_NEED_VAL"
    f = vs.case_status(vs.plan("full"), None, HAVE_ALL)
    assert f["available"] and f["resp"]
    f = vs.case_status(vs.plan("full"), None, {**HAVE_ALL, "load": False})
    assert not f["available"] and f["code"] == "PREREQUISITE_MISSING"
    old = vs.case_status(vs.plan("fint"), None, {"model": True, "load": False, "target": True})
    assert old["code"] == "V3D_SRC_NOT_RUN" and old["reason"] == vs.REASON_TEXT["V3D_SRC_NOT_RUN"]
    assert vs.reason_text("FINT_DISABLED") == "설정에서 꺼짐(bforce.fint.enabled)"
