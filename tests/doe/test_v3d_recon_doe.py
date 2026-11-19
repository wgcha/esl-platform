"""v0.24.1 스터디 3D — 기존 파일 바이트 불변 + 노드 힘 출처 재현 진단(계약 esl_view3d_sources.md §5.2, V-0241-V3D-13).

골든: v0.24.0(f29eeec0) 코드로 만든 경계력·내력 스터디(test_fint_doe 합성)의 post/view3d/* 파일 sha256(manifest 는 created_at 을 뺀
정규 JSON)을 ``ESL_GOLDEN_RECORD=1`` 로 ``tests/fixtures/view3d/doe_view3d_v0240.json`` 에 기록했다. 풀이(SuperLU) 결과에 의존하므로
같은 환경 서명(numpy·scipy·플랫폼)에서만 바이트를 비교하고, 다른 환경에서는 같은 실행 안의 recon 끔/켬 대조(V-13 나머지)로 대신한다.
"""
import hashlib
import json
import os
import platform
from typing import ClassVar

import numpy as np
import pytest
import scipy
import test_fint_doe as FD
import test_jig_stages as T

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(ROOT, "tests", "fixtures", "view3d", "doe_view3d_v0240.json")


def env_sig() -> str:
    return f"{platform.system()}-{platform.machine()}-numpy{np.__version__}-scipy{scipy.__version__}"


def _rb(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def _rj(p: str):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


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
                m = _rj(p)
                m.pop("created_at", None)
                b = json.dumps(m, sort_keys=True, ensure_ascii=False).encode()
            else:
                b = _rb(p)
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
    gold = _rj(GOLDEN)
    assert set(gold["files"]) <= set(cur)                                     # 옛 파일은 모두 그대로 있음(새 파일만 더함)
    if gold["env"] != env_sig():
        pytest.skip(f"환경 서명이 골든과 다름({env_sig()} ≠ {gold['env']}) — recon 끔/켬 대조 시험으로 대신")
    assert {k: cur[k] for k in gold["files"]} == gold["files"]


# ---------------------------------------------------------------- V-13 재현 진단(코어)
def test_recon_files_and_sidecar_keys(vrun):
    from esl.doe import stages as stg
    from esl.library import _util as U
    from esl.mech import bforce as bfm
    from esl.mech import kabsch
    from esl.view3d import RECON_SCHEMA, unpack_disp, unpack_values

    out = vrun["out"]
    sr = U.load_npz(os.path.join(out, "prep", stg.SM_REF_NPZ))
    eids = [str(e) for e in sr["entry_ids"].tolist()]
    for ns in stg.NODAL_SOURCES:
        side = U.read_json(os.path.join(out, "post", stg._nf(ns, "view")))
        key = f"view3d_{ns['pe']}_recon"
        assert side[key] and set(side[key]) == set(side[f"view3d_{ns['pe']}_ref"])   # 기준 폴더마다 재현
        assert not any(k.startswith("VIEW3D_FAILED") for k in side["warnings"])
        for e, nm in side[key].items():
            assert nm == side[f"view3d_{ns['pe']}_ref"][e]
            d = os.path.join(out, "post", "view3d", nm)
            rj = _rj(os.path.join(d, "recon.json"))
            man = _rj(os.path.join(d, "manifest.json"))
            assert rj["schema"] == RECON_SCHEMA and rj["src"] == ns["key"] and rj["rigid"] == "kabsch"
            assert rj["key"] == f"doe/{nm}" and rj["esl_run_id"] == e and rj["n_nodes"] == man["n_nodes"]
            n = rj["n_nodes"]
            arr = unpack_disp(_rb(os.path.join(d, "recon.bin")), rj["arrays"], n)
            # 응답 = 같은 폴더 values.bin u(Kabsch 강체 제거) — 양자화 오차 안
            vals = unpack_values(_rb(os.path.join(d, "values.bin")), man["values"]["arrays"], n)
            mesh = vrun_mesh(out)
            X = np.asarray(mesh["x0"], dtype=np.float64)
            nr = np.asarray(sr["node_id"], dtype=np.int64)
            pos = np.argsort(nr)[np.searchsorted(nr, mesh["node_id"], sorter=np.argsort(nr))]
            assert np.array_equal(nr[pos], mesh["node_id"])
            fit = kabsch.remove_rigid(X, vals["u"])[0]
            s_fit = max(rj["arrays"][1]["scale"]) + max(man["values"]["arrays"][3]["scale"])   # 회전이 성분을 섞음 → 최대 배율
            assert np.all(np.abs(arr["fit"] - fit) <= 4 * s_fit + 1e-12)
            tgt = kabsch.remove_rigid(X, np.asarray(sr["u"][eids.index(e)], dtype=np.float64)[pos][:, :3])[0]
            assert np.all(np.abs(arr["tgt"] - tgt) <= np.asarray(rj["arrays"][0]["scale"]) / 2 + 1e-12)
            assert rj["mac"] == pytest.approx(bfm.mac(tgt, arr["fit"]), abs=1e-3)


def vrun_mesh(out):
    """기준 메시(prep — 베이스라인 3D 와 같은 메시)."""
    from esl.doe import scenario as sc
    t, _ = sc.load_base(os.path.join(out, "prep"))
    return t.mesh


def test_recon_off_writes_nothing_new_and_same_bytes(tmp_path, vrun):
    """bead_doe.view3d.recon: false → 재현 파일·키 0, 기존 파일 바이트 = 켬 실행과 같음(created_at 제외)."""
    from esl.doe import stages as stg
    from esl.library import _util as U

    out, _ = run_study(tmp_path, recon=False)
    off = view3d_hashes(out)
    assert not any(k.endswith(("/recon.json", "/recon.bin")) for k in off)
    for ns in stg.NODAL_SOURCES:
        assert f"view3d_{ns['pe']}_recon" not in U.read_json(os.path.join(out, "post", stg._nf(ns, "view")))
    on = view3d_hashes(vrun["out"])
    assert {k: v for k, v in on.items() if not k.endswith(("/recon.json", "/recon.bin"))} == off


def test_recon_absent_without_once_sm_ref(tmp_path):
    """sm_ref 가 per_target 형식(u·node_id 없음) → 재현 키 없음·경고 없음."""
    from esl.doe import stages as stg

    class C:
        cfg: ClassVar[dict] = {"view3d": {"recon": True}}

        def p(self, *a):
            return os.path.join(str(tmp_path), *a)

    os.makedirs(tmp_path / "prep")
    assert stg._ns_recon_ref(C()) is None                                      # sm_ref 없음
    np.savez(tmp_path / "prep" / stg.SM_REF_NPZ, entry_ids=np.asarray(["e1"]), u_a_0=np.zeros((3, 3)))
    assert stg._ns_recon_ref(C()) is None                                      # per_target 형식
    np.savez(tmp_path / "prep" / stg.SM_REF_NPZ, entry_ids=np.asarray(["e1"]), u=np.zeros((1, 3, 6)),
             node_id=np.arange(3))
    assert stg._ns_recon_ref(C())["entry_ids"] == ["e1"]
    C.cfg = {"view3d": {"recon": False}}
    assert stg._ns_recon_ref(C()) is None
