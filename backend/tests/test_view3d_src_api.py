"""v0.24.1 Case 3D 하중 출처 API(계약 esl_view3d_sources.md §5.1, V-0241-V3D-6~12).

V-6 골든: v0.24.0 형식 Case 고정본(실행 ID·입력 mtime 고정)의 ``GET /view3d``(src 없음) 응답 JSON·ETag·세 파일 바이트를
변경 **전**(f29eeec0 = v0.24.0 코드)에 ``ESL_GOLDEN_RECORD=1`` 로 ``backend/tests/fixtures/view3d_case_v0240.json`` 에 기록했다.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from esl_test_support import API
from test_view3d_api import R, Seed, code, mk, world  # noqa: F401  (픽스처 재사용)

sys_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
import sys

sys.path.insert(0, sys_path)
from gen_view3d_fixture import synth_mesh

GOLDEN = Path(__file__).parent / "fixtures" / "view3d_case_v0240.json"
CREATED_AT = "2026-11-19T00:00:00Z"
MTIME_NS = 1_763_500_000_000_000_000


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def fixed_build(monkeypatch):
    """생성 시각 고정(manifest·응답 JSON 바이트 비교용) — 나머지는 실제 빌더."""
    from esl_worker import core_adapter

    real = core_adapter.view3d_build

    def fixed(out_dir, **kw):
        return real(out_dir, **{**kw, "created_at": CREATED_AT})

    monkeypatch.setattr(core_adapter, "view3d_build", fixed)


def fixed_seed(world, engine, monkeypatch, mesh=None, folder="g1", base=1) -> Seed:  # noqa: F811
    """실행 ID·Case ID 결정적(uuid 고정 — base 로 Case 마다 다른 구간) + 입력 파일 mtime 고정 → 키·ETag·URL 결정적."""
    n = iter(range(base, base + 1000))
    with monkeypatch.context() as mp:
        mp.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(n)))
        s = Seed(world, engine, mesh if mesh is not None else synth_mesh(12, 8, bend=0.3, tri_every=6, seed=3),
                 folder=folder)
    for p in [s.dir / "01_extract" / "model.npz", *(s.dir / "runs" / s.run_id).rglob("*")]:
        if p.is_file():
            os.utime(p, ns=(MTIME_NS, MTIME_NS))
    return s


def _legacy_snapshot(c, s: Seed) -> dict:
    r = c.get(s.url(), headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    files = {}
    for name in ("part.glb", "part_lod.glb", "values.bin"):
        if name == "part_lod.glb" and d["lod"] is None:
            continue
        g = c.get(s.url(f"/{name}"), params={"key": d["key"]}, headers=R)
        assert g.status_code == 200, name
        files[name] = _sha(g.content)
    disk = {p.name: _sha(p.read_bytes()) for p in sorted(s.view_dir.iterdir())}
    return {"run_id": s.run_id, "etag": r.headers["etag"], "json_sha": _sha(r.content), "files": files, "disk": disk,
            "runs_dirs": sorted(p.name for p in (s.dir / "runs" / s.run_id).iterdir())}


# ---------------------------------------------------------------- V-6 legacy 바이트 골든
def test_legacy_view3d_bytes_equal_v0240_golden(mk, world, engine, monkeypatch, fixed_build):  # noqa: F811
    s1 = fixed_seed(world, engine, monkeypatch)
    cur = {"plain": _legacy_snapshot(mk(), s1)}
    s2 = fixed_seed(world, engine, monkeypatch, folder="g2", base=1001)
    cur["lod"] = _legacy_snapshot(mk(lod_min_nodes=50, lod_target_vertices=100), s2)
    if os.environ.get("ESL_GOLDEN_RECORD") == "1" and not GOLDEN.is_file():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps({"recorded_at_commit": "f29eeec0 (= v0.24.0 view3d API)", **cur}, indent=1,
                                     sort_keys=True) + "\n", encoding="utf-8")
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for k in ("plain", "lod"):
        assert cur[k] == gold[k], k
    assert gold["plain"]["runs_dirs"] == ["03_bc", "04_esl", "view3d"]                     # 새 폴더 0


# ---------------------------------------------------------------- 출처 고정본 도우미
def _esl(s: Seed) -> Path:
    return s.dir / "runs" / s.run_id / "04_esl"


def add_nodal(s: Seed, file: str, *, scale=1.3, u_val=True, recon=None, seed=5) -> dict:
    """04_esl/<file>.npz·<file>.json(경계력·내력 고정본). u_val = 같은 3-2-1 해(Kabsch 제거 — 여기선 u_rel + 작은 차이)."""
    import numpy as np

    from esl.mech import bforce as bfm

    rng = np.random.default_rng(seed)
    m = s.m
    f = m["f"] * scale + rng.normal(size=m["f"].shape)
    z = {"node_id": m["node_id"], "f": f, "f_raw": f, "m": np.zeros(m["node_id"].size)}
    uv = m["u_rel"] * 0.9 + rng.normal(size=m["u_rel"].shape) * 1e-3
    if u_val:
        z["u_val"] = uv
    np.savez_compressed(_esl(s) / f"{file}.npz", **z)
    rc = recon or ({"status": "ok", "mac": bfm.mac(m["u_rel"], uv), "umax_err": 0.1} if u_val
                   else {"status": "skipped", "reason": "MEMORY_LIMIT 5.0 GB > 2.0 GB"})
    (_esl(s) / f"{file}.json").write_text(json.dumps({"schema": "esl/bforce/1", "recon": rc}), encoding="utf-8")
    return {"f": f, "u_val": uv, "recon": rc}


def set_forces(engine, s: Seed, **summ) -> None:
    from sqlalchemy import update

    from esl_platform.core.db.tables import esl_runs

    with engine.begin() as c:
        c.execute(update(esl_runs).where(esl_runs.c.id == s.run_id).values(forces={"sum_abs_f": 123.0, **summ}))


def add_val(world, s: Seed, *, d_val=None, seed=9):
    """⑤ 검증(DB 행 + Case 05_val/compare_disp.npz — 최신 검증 = Case 05_val). d_val 기본 = d_rel + 작은 차이."""
    import numpy as np

    v = world.validate(s.case, s.run_id)
    d = s.dir / "05_val"
    d.mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    d_rel = s.m["u_rel"]
    dv = d_rel + rng.normal(size=d_rel.shape) * 2e-3 if d_val is None else d_val
    perm = rng.permutation(d_rel.shape[0])                       # 노드 순서 섞음 → 서비스가 ID 로 재정렬
    np.savez_compressed(d / "compare_disp.npz", node_id=s.m["node_id"][perm], d_rel=d_rel[perm], d_val=dv[perm],
                        e=np.linalg.norm(dv - d_rel, axis=1)[perm])
    return v, d_rel, dv


def _tree(p: Path) -> dict[str, tuple[int, int]]:
    return {str(q.relative_to(p)): (q.stat().st_mtime_ns, q.stat().st_size) for q in sorted(p.rglob("*")) if q.is_file()}


def _bin(c, url: str, **params) -> bytes:
    r = c.get(f"{API}{url}", params=params, headers=R)
    assert r.status_code == 200, r.text
    return r.content


@pytest.fixture()
def seed(world, engine):  # noqa: F811
    return Seed(world, engine, synth_mesh(12, 8, bend=0.3, tri_every=6, seed=3))


# ---------------------------------------------------------------- V-6 ?src=full = legacy
def test_src_full_equals_legacy_and_no_new_folders(mk, world, engine, monkeypatch, fixed_build):  # noqa: F811
    s = fixed_seed(world, engine, monkeypatch)
    c = mk()
    a = c.get(s.url(), headers=R)
    b = c.get(s.url(), params={"src": "full"}, headers=R)
    assert a.status_code == b.status_code == 200 and a.content == b.content and a.headers["etag"] == b.headers["etag"]
    for name in ("part.glb", "values.bin"):
        assert c.get(s.url(f"/{name}"), params={"src": "full", "key": a.json()["key"]}, headers=R).content == \
            c.get(s.url(f"/{name}"), headers=R).content
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))["plain"]
    assert a.headers["etag"] == gold["etag"] and _sha(a.content) == gold["json_sha"]
    assert sorted(p.name for p in (s.dir / "runs" / s.run_id).iterdir()) == ["03_bc", "04_esl", "view3d"]
    assert c.get(f"{API}/esl-runs/{s.run_id}/view3d/sources", headers=R).status_code == 200
    assert sorted(p.name for p in (s.dir / "runs" / s.run_id).iterdir()) == ["03_bc", "04_esl", "view3d"]


# ---------------------------------------------------------------- V-7 ?src=bforce
def test_src_bforce_folder_top_etag_urls_and_legacy_untouched(mk, seed, engine):
    import numpy as np

    c = mk()
    leg = c.get(seed.url(), headers=R)
    assert leg.status_code == 200
    before = _tree(seed.view_dir)
    bf = add_nodal(seed, "bforce")
    r = c.get(seed.url(), params={"src": "bforce"}, headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    vd = seed.dir / "runs" / seed.run_id / "view3d_bforce"
    assert (vd / "manifest.json").is_file() and d["key"] != leg.json()["key"] and r.headers["etag"] != leg.headers["etag"]
    mag = np.linalg.norm(bf["f"], axis=1)
    order = np.lexsort((seed.m["node_id"], -mag))[:100]
    assert [t["node_id"] for t in d["top"]] == [int(seed.m["node_id"][i]) for i in order]
    q = "?src=bforce"
    assert d["geometry_url"] == f"/esl-runs/{seed.run_id}/view3d/part.glb{q}"
    assert d["values_url"] == f"/esl-runs/{seed.run_id}/view3d/values.bin{q}" and d["lod_url"] is None
    g = c.get(seed.url("/values.bin"), params={"src": "bforce", "key": d["key"]}, headers=R)
    assert g.status_code == 200 and g.headers["etag"] == r.headers["etag"]
    assert g.content == (vd / "values.bin").read_bytes()
    st = c.get(seed.url("/values.bin"), params={"src": "bforce", "key": leg.json()["key"]}, headers=R)
    assert st.status_code == 409 and code(st) == "VIEW3D_STALE"
    assert c.get(seed.url(), params={"src": "bforce"}, headers={**R, "If-None-Match": r.headers["etag"]}).status_code == 304
    assert _tree(seed.view_dir) == before                                          # legacy 폴더 mtime·크기 불변
    assert c.get(seed.url(), headers=R).content == leg.content


# ---------------------------------------------------------------- V-8 오류
def test_src_errors(mk, seed, engine):
    c = mk()
    r = c.get(seed.url(), params={"src": "xyz"}, headers=R)
    assert r.status_code == 404 and code(r) == "SOURCE_NOT_FOUND" and r.json()["detail"]["keys"] == [
        "jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    r = c.get(seed.url(), params={"src": "jig"}, headers=R)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "V3D_SOURCE_UNAVAILABLE" and d["src"] == "jig"
    from esl import view3d_src as vs                                              # v0.24.4: jig = 지그 ESL 없는 Case(JIG_NOT_RUN)
    assert d["reason_code"] == "JIG_NOT_RUN" and d["reason"] == vs.REASON_TEXT["JIG_NOT_RUN"]
    r = c.get(seed.url(), params={"src": "bforce"}, headers=R)                     # 옛 실행(npz·요약 없음)
    assert r.status_code == 409 and code(r) == "V3D_SOURCE_UNAVAILABLE"
    assert r.json()["detail"]["reason_code"] == "V3D_SRC_NOT_RUN" and "v0.24.0 이전" in r.json()["detail"]["reason"]
    set_forces(engine, seed, bforce={"grade": "none", "code": "BF_NO_DATA", "reason": "접촉력 출력 없음 — /H3D/NODA/CONT"},
               fint={"grade": None, "code": "FINT_DISABLED"})
    r = c.get(seed.url(), params={"src": "bforce"}, headers=R)
    assert r.json()["detail"]["reason_code"] == "BF_NO_DATA" and r.json()["detail"]["reason"] == "접촉력 출력 없음 — /H3D/NODA/CONT"
    r = c.get(seed.url(), params={"src": "fint"}, headers=R)
    assert r.json()["detail"]["reason_code"] == "FINT_DISABLED" and r.json()["detail"]["reason"] == "설정에서 꺼짐(bforce.enabled · bforce.fint.enabled)"
    assert c.get(seed.url("/part.glb"), params={"src": "xyz"}, headers=R).status_code == 404
    assert not (seed.dir / "runs" / seed.run_id / "view3d_bforce").exists()


# ---------------------------------------------------------------- V-9 /view3d/sources
def _rows(c, s: Seed) -> dict:
    r = c.get(f"{API}/esl-runs/{s.run_id}/view3d/sources", headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["esl_run_id"] == s.run_id and [x["key"] for x in d["rows"]] == ["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]
    return d


@pytest.mark.parametrize("variant", ["old", "bforce_only", "fint_only", "with_val"])
def test_sources_variants_and_no_writes(mk, world, engine, variant):  # noqa: F811
    s = Seed(world, engine, synth_mesh(8, 6, seed=4), folder=f"s_{variant}")
    if variant == "bforce_only":
        add_nodal(s, "bforce")
        set_forces(engine, s, bforce={"grade": "contact", "recon": "ok"}, fint={"grade": "none", "code": "FINT_NO_DATA",
                                                                                 "reason": "내력 출력 없음"})
    if variant == "fint_only":
        add_nodal(s, "fint", u_val=False)
        set_forces(engine, s, bforce={"grade": None, "code": "BF_DISABLED"}, fint={"grade": "fint", "recon": "skipped"})
    if variant == "with_val":
        add_val(world, s)
    before = _tree(s.dir)
    d = _rows(mk(), s)
    rows = {x["key"]: x for x in d["rows"]}
    assert d["default"] == "full" and _tree(s.dir) == before                          # 파일 안 씀
    for k in ("jig", "jig_disp", "jig_spring"):                                       # v0.24.4: 지그 ESL 없는 Case
        assert rows[k]["available"] is False and rows[k]["code"] == "JIG_NOT_RUN", k
    assert rows["full"]["available"] is True and rows["full"]["rigid"] == "linear"
    assert rows["full"]["resp"] is (variant == "with_val")
    if variant != "with_val":
        assert rows["full"]["resp_code"] == "V3D_RESP_NEED_VAL" and "⑤ 검증" in rows["full"]["resp_reason"]
    exp = {"old": {"bforce": (False, "V3D_SRC_NOT_RUN", False), "fint": (False, "V3D_SRC_NOT_RUN", False)},
           "bforce_only": {"bforce": (True, None, True), "fint": (False, "FINT_NO_DATA", False)},
           "fint_only": {"bforce": (False, "BF_DISABLED", False), "fint": (True, None, False)},
           "with_val": {"bforce": (False, "V3D_SRC_NOT_RUN", False), "fint": (False, "V3D_SRC_NOT_RUN", False)}}[variant]
    for k, (av, cd, resp) in exp.items():
        assert (rows[k]["available"], rows[k]["code"], rows[k]["resp"]) == (av, cd, resp), k
        assert rows[k]["rigid"] == "kabsch"
    if variant == "fint_only":
        assert rows["fint"]["resp_code"] == "V3D_RESP_SKIPPED" and "(MEMORY_LIMIT 5.0 GB > 2.0 GB)" in rows["fint"]["resp_reason"]
        assert rows["bforce"]["reason"] == "설정에서 꺼짐(bforce.enabled)"
    if variant == "bforce_only":
        assert rows["fint"]["reason"] == "내력 출력 없음"


def test_sources_errors_same_as_manifest(mk, seed, engine):
    from sqlalchemy import update

    from esl_platform.core.db.tables import esl_runs

    c = mk()
    assert c.get(f"{API}/esl-runs/nope/view3d/sources", headers=R).status_code == 404
    with engine.begin() as cn:
        cn.execute(update(esl_runs).where(esl_runs.c.id == seed.run_id).values(status="FAILED"))
    r = c.get(f"{API}/esl-runs/{seed.run_id}/view3d/sources", headers=R)
    assert r.status_code == 409 and code(r) == "ESL_RUN_FAILED"
    off = mk(enabled=False)
    assert code(off.get(f"{API}/esl-runs/{seed.run_id}/view3d/sources", headers=R)) == "VIEW3D_DISABLED"


# ---------------------------------------------------------------- V-10 재현 full(⑤ compare_disp)
def _recon(c, s: Seed, src=None):
    return c.get(f"{API}/esl-runs/{s.run_id}/view3d/recon", params={} if src is None else {"src": src}, headers=R)


def test_recon_full_from_validation(mk, seed, world):
    import numpy as np

    from esl.view3d import unpack_disp

    c = mk()
    r = _recon(c, seed, "full")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "V3D_RECON_UNAVAILABLE" and d["reason_code"] == "V3D_RESP_NEED_VAL"
    assert c.get(seed.url(), headers=R).status_code == 200
    view_before = _tree(seed.view_dir)
    _, d_rel, d_val = add_val(world, seed)
    r = _recon(c, seed, "full")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["schema"] == "esl/view3d_recon/1" and j["recon_version"] == 1
    assert set(j) == {"schema", "recon_version", "key", "src", "esl_run_id", "n_nodes", "rigid", "bytes", "arrays", "ranges",
                      "mac", "umax_tgt", "umax_fit", "umax_err", "values_url"}
    assert j["rigid"] == "linear" and j["src"] == "full" and j["n_nodes"] == seed.m["node_id"].size
    assert j["values_url"] == f"/esl-runs/{seed.run_id}/view3d/recon.bin"                       # legacy 행 = ?src 없음
    assert r.headers["etag"] == f'"{j["key"]}"' and _recon(c, seed).json() == j                  # src 없음 = full
    b = _bin(c, f"/esl-runs/{seed.run_id}/view3d/recon.bin", key=j["key"])
    arr = unpack_disp(b, j["arrays"], j["n_nodes"])
    se = np.asarray(j["arrays"][2]["scale"])
    assert np.all(np.abs(arr["err"] - (d_val - d_rel)) <= se / 2 + 1e-12)                       # model 순서로 재정렬됨
    assert np.all(np.abs(arr["tgt"] - d_rel) <= np.asarray(j["arrays"][0]["scale"]) / 2 + 1e-12)
    rd = seed.dir / "runs" / seed.run_id / "view3d_recon"
    assert sorted(p.name for p in rd.iterdir()) == ["recon.bin", "recon.json"]
    assert c.get(f"{API}/esl-runs/{seed.run_id}/view3d/recon", headers={**R, "If-None-Match": r.headers["etag"]}
                 ).status_code == 304
    # 검증을 다시 하면(compare_disp 바뀜) 재현 키만 바뀌고 하중 보기 폴더 불변
    f = seed.dir / "05_val" / "compare_disp.npz"
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    j2 = _recon(c, seed, "full").json()
    assert j2["key"] != j["key"] and _tree(seed.view_dir) == view_before
    assert len(list((seed.dir / "_backup").glob(f"*/runs/{seed.run_id}/view3d_recon/recon.json"))) == 1   # 이동(삭제 아님)
    st = c.get(f"{API}/esl-runs/{seed.run_id}/view3d/recon.bin", params={"key": j["key"]}, headers=R)
    assert st.status_code == 409 and code(st) == "VIEW3D_STALE"


# ---------------------------------------------------------------- V-11 재현 bforce(ESL 단계 u_val)
def test_recon_bforce_matches_case_summary_and_skipped(mk, seed, engine):
    import numpy as np

    from esl.view3d import unpack_disp

    c = mk()
    bf = add_nodal(seed, "bforce")
    set_forces(engine, seed, bforce={"grade": "contact", "recon": "ok", "mac": bf["recon"]["mac"]})
    r = _recon(c, seed, "bforce")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["rigid"] == "kabsch" and j["values_url"] == f"/esl-runs/{seed.run_id}/view3d/recon.bin?src=bforce"
    assert abs(j["mac"] - bf["recon"]["mac"]) <= 1e-9
    b = _bin(c, f"/esl-runs/{seed.run_id}/view3d/recon.bin", src="bforce", key=j["key"])
    arr = unpack_disp(b, j["arrays"], j["n_nodes"])
    assert np.all(np.abs(arr["err"] - (bf["u_val"] - seed.m["u_rel"])) <= np.asarray(j["arrays"][2]["scale"]) / 2 + 1e-12)
    assert (seed.dir / "runs" / seed.run_id / "view3d_bforce_recon" / "recon.json").is_file()
    assert not (seed.dir / "runs" / seed.run_id / "view3d_bforce").exists()             # 재현만 — 하중 보기와 다른 폴더
    # u_val 없음(ESL 단계 재현 생략) → V3D_RESP_SKIPPED + recon.reason
    add_nodal(seed, "fint", u_val=False)
    set_forces(engine, seed, bforce={"grade": "contact", "recon": "ok"}, fint={"grade": "fint", "recon": "skipped"})
    r = _recon(c, seed, "fint")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "V3D_RECON_UNAVAILABLE" and d["reason_code"] == "V3D_RESP_SKIPPED"
    assert d["reason"].endswith("(MEMORY_LIMIT 5.0 GB > 2.0 GB)") and d["src"] == "fint"
    assert c.get(seed.url(), params={"src": "fint"}, headers=R).status_code == 200            # 하중 보기는 가능
    r = _recon(c, seed, "jig")
    assert r.status_code == 409 and code(r) == "V3D_SOURCE_UNAVAILABLE"


# ---------------------------------------------------------------- V-12 백업 이동·세마포어
def test_src_folder_backup_and_busy(mk, seed, monkeypatch):
    import shutil
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from esl_worker import core_adapter

    c = mk()
    add_nodal(seed, "bforce")
    k1 = c.get(seed.url(), params={"src": "bforce"}, headers=R).json()["key"]
    vd = seed.dir / "runs" / seed.run_id / "view3d_bforce"
    old = (vd / "manifest.json").read_text(encoding="utf-8")
    f = _esl(seed) / "bforce.npz"
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    k2 = c.get(seed.url(), params={"src": "bforce"}, headers=R).json()["key"]
    assert k2 != k1
    moved = list((seed.dir / "_backup").glob(f"*/runs/{seed.run_id}/view3d_bforce/manifest.json"))
    assert len(moved) == 1 and moved[0].read_text(encoding="utf-8") == old
    assert not list(vd.parent.glob("view3d_bforce.tmp-*"))
    # 세마포어 대기 초과 → 503 VIEW3D_BUSY(출처 무관 같은 규칙)
    real, gate = core_adapter.view3d_build, threading.Event()

    def slow(out_dir, **kw):
        gate.wait(5)
        return real(out_dir, **kw)

    monkeypatch.setattr(core_adapter, "view3d_build", slow)
    shutil.rmtree(vd)
    c = mk(build_wait_s=0.3)
    with ThreadPoolExecutor(1) as ex:
        f1 = ex.submit(c.get, seed.url(), headers=R)                                       # legacy 생성 중
        time.sleep(0.3)
        busy = c.get(seed.url(), params={"src": "bforce"}, headers=R)
        gate.set()
        assert f1.result(10).status_code == 200
    assert busy.status_code == 503 and code(busy) == "VIEW3D_BUSY" and busy.headers["retry-after"] == "5"


def test_case_src_default_setting_validated(tmp_path):
    from esl_test_support import make_settings_dict

    from esl_platform.core.config import load_config_dict

    lc = load_config_dict(make_settings_dict(tmp_path), environ={})
    assert lc.ok and lc.settings.view3d.case_src_default == "full"
    for v, ok in (("bforce", True), ("fint", True), ("jig", True), ("jig_spring", True), ("xyz", False)):
        assert load_config_dict(make_settings_dict(tmp_path, view3d={"case_src_default": v}), environ={}).ok is ok, v


def test_service_dir_constant_equals_plan_legacy_dir():
    from esl_platform.api.services import view3d as svc

    assert svc.source_row(None)["dir"] == svc.DIR and svc.source_row(None)["key"] == "full"
