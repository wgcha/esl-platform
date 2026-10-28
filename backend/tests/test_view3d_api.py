"""④ 3D 하중 보기 API 시험(계약 esl_3d_load.md §4, V-L3-2·7·8·9 의 API 부분).

Case·ESL 실행은 DB 에 직접 심고(계산 없음), 산출물(model.npz·f_eq.npz·u_rel.npz·support.json)은 합성 판 메시로 파일에 쓴다.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pytest
from esl_test_support import API, H, make_settings_dict
from sqlalchemy import update
from test_p3_history import World

sys_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
import sys  # noqa: E402

sys.path.insert(0, sys_path)
from gen_view3d_fixture import synth_mesh  # noqa: E402

from esl_platform.core.db.tables import esl_runs  # noqa: E402

R = H("tok-general")


def code(r) -> str:
    return r.json()["detail"]["code"]


@pytest.fixture()
def mk(engine, tmp_path, fake_dashboard, clock):
    """mk(**view3d 설정) → 클라이언트. 같은 esl_root(tmp_path/esl_root)를 공유한다."""
    from fastapi.testclient import TestClient

    from esl_platform.api.context import build_context
    from esl_platform.api.main import create_app
    from esl_platform.core.config import load_config_dict

    stack = contextlib.ExitStack()

    def make(**view3d):
        d = make_settings_dict(tmp_path, **({"view3d": view3d} if view3d else {}))
        lc = load_config_dict(d, environ={})
        assert lc.ok, lc.errors()
        ctx = build_context(lc, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock)
        return stack.enter_context(TestClient(create_app(ctx), base_url="http://127.0.0.1"))

    with stack:
        yield make


@pytest.fixture()
def world(engine, tmp_path):
    return World(engine, tmp_path / "esl_root")


class Seed:
    """Case 하나 + ESL 실행 하나(+ 산출물). 파일은 runs/<id>/ 스냅샷에 둔다."""

    def __init__(self, world: World, engine, mesh: dict, *, folder="c1", snapshot=True, make_current=True,
                 supports_in_db=True) -> None:
        self.world, self.engine, self.m = world, engine, mesh
        self.case = world.case(folder)
        sid = world.support(self.case["id"])
        e1 = world.extract(self.case)
        self.esl = world.esl(self.case, e1, sid, make_current=make_current)
        self.run_id, self.job_id = self.esl["run_id"], self.esl["job_id"]
        self.dir: Path = self.case["dir"]
        nid = mesh["node_id"]
        self.sup = [{"node_id": int(nid[0]), "dof": "123"}, {"node_id": int(nid[5]), "dof": "13"},
                    {"node_id": int(nid[9]), "dof": "3"}]
        self.write_model()
        if snapshot:
            self.write_run(self.dir / "runs" / self.run_id)
        if supports_in_db:
            with engine.begin() as c:
                c.execute(update(esl_runs).where(esl_runs.c.id == self.run_id).values(supports=self.sup))

    def write_model(self) -> None:
        d = self.dir / "01_extract"
        d.mkdir(parents=True, exist_ok=True)
        m = self.m
        np.savez(d / "model.npz", node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"],
                 elem_id=np.arange(m["conn"].shape[0]) + 1)

    def write_run(self, base: Path, nid_f=None) -> None:
        m = self.m
        e = base / "04_esl"
        b = base / "03_bc"
        e.mkdir(parents=True, exist_ok=True)
        b.mkdir(parents=True, exist_ok=True)
        np.savez(e / "f_eq.npz", node_id=m["node_id"] if nid_f is None else nid_f, f=m["f"],
                 is_bc=np.zeros(m["node_id"].size, bool))
        np.savez(e / "u_rel.npz", node_id=m["node_id"], u_rel=m["u_rel"], u_total=m["u_rel"])
        (e / "esl_summary.json").write_text(json.dumps({"tag": self.job_id}), encoding="utf-8")
        (b / "support.json").write_text(json.dumps({"supports": [dict(s, x0=[0, 0, 0], flags={}) for s in self.sup]}),
                                        encoding="utf-8")

    @property
    def view_dir(self) -> Path:
        return self.dir / "runs" / self.run_id / "view3d"

    def url(self, tail="") -> str:
        return f"{API}/esl-runs/{self.run_id}/view3d{tail}"


@pytest.fixture()
def seed(world, engine):
    return Seed(world, engine, synth_mesh(12, 8, bend=0.3, tri_every=6, seed=3))


@pytest.fixture()
def count_builds(monkeypatch):
    from esl_worker import core_adapter

    calls = []
    real = core_adapter.view3d_build

    def counted(out_dir, **kw):
        calls.append(out_dir)
        return real(out_dir, **kw)

    monkeypatch.setattr(core_adapter, "view3d_build", counted)
    return calls


# ---------------------------------------------------------------- 응답·파일
def test_manifest_keys_headers_and_files(mk, seed):
    c = mk()
    r = c.get(seed.url(), headers=R)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["schema"] == "esl/view3d/1" and d["builder_version"] == 1 and d["esl_run_id"] == seed.run_id
    assert set(d) >= {"key", "n_nodes", "n_elems", "n_tris", "units", "force_unit", "pressure_unit", "up", "bbox",
                      "plate_normal", "geometry", "lod", "values", "ranges", "sum_f", "sum_m", "moment_center",
                      "supports", "top", "clusters", "created_at", "geometry_url", "lod_url", "values_url"}
    assert d["n_nodes"] == seed.m["node_id"].size and d["lod"] is None and d["lod_url"] is None
    assert d["pressure_unit"] == "MPa" and d["up"] == "Z" and d["units"] == "mm"
    assert d["geometry_url"] == f"/esl-runs/{seed.run_id}/view3d/part.glb"
    assert d["values_url"] == f"/esl-runs/{seed.run_id}/view3d/values.bin"
    assert r.headers["etag"] == f'"{d["key"]}"' and r.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert set(d["clusters"]) == {"2", "3", "4", "5"} and len(d["top"]) == 100
    assert {"pa", "fn", "rank", "vertex", "is_support"} <= set(d["top"][0])
    assert [s["dof"] for s in d["supports"]] == ["123", "13", "3"] and d["ranges"]["pa"]["p99"] > 0
    assert (seed.view_dir / "manifest.json").is_file() and not list(seed.view_dir.parent.glob("view3d.tmp-*"))
    g = c.get(seed.url("/part.glb"), headers=R)
    assert g.status_code == 200 and g.headers["content-type"] == "model/gltf-binary"
    assert g.content[:4] == b"glTF" and len(g.content) == d["geometry"]["bytes"]
    v = c.get(seed.url("/values.bin"), headers=R)
    assert v.status_code == 200 and v.headers["content-type"] == "application/octet-stream"
    assert len(v.content) == d["values"]["bytes"] and v.headers["etag"] == r.headers["etag"]
    assert c.get(seed.url("/values.bin"), params={"key": d["key"]}, headers=R).status_code == 200
    ln = c.get(seed.url("/part_lod.glb"), headers=R)
    assert ln.status_code == 404 and code(ln) == "VIEW3D_LOD_NONE"


def test_top_rows_equal_forces_endpoint(mk, seed):
    c = mk()
    top = c.get(seed.url(), headers=R).json()["top"]
    fr = c.get(f"{API}/esl-runs/{seed.run_id}/forces", params={"top": 100}, headers=R)
    assert fr.status_code == 200, fr.text
    rows = fr.json()["rows"]
    assert len(rows) == len(top) == 100
    for t, f in zip(top, rows):
        assert t["node_id"] == f["node_id"] and t["is_support"] == f["is_support"]
        assert (t["x"], t["y"], t["z"], t["fx"], t["fy"], t["fz"], t["mag"]) == \
               (f["x"], f["y"], f["z"], f["fx"], f["fy"], f["fz"], f["mag"])


def test_lod_served_when_threshold_lowered(mk, seed):
    c = mk(lod_min_nodes=50, lod_target_vertices=100)
    d = c.get(seed.url(), headers=R).json()
    assert d["lod"]["name"] == "part_lod.glb" and d["lod_url"] == f"/esl-runs/{seed.run_id}/view3d/part_lod.glb"
    g = c.get(seed.url("/part_lod.glb"), headers=R)
    assert g.status_code == 200 and g.content[:4] == b"glTF" and len(g.content) == d["lod"]["bytes"]
    assert d["lod"]["n_vertices"] <= 1.2 * 100


# ---------------------------------------------------------------- V-L3-8 캐시
def test_cache_hit_etag_304_and_no_second_build(mk, seed, count_builds):
    c = mk()
    r1 = c.get(seed.url(), headers=R)
    r2 = c.get(seed.url(), headers=R)
    assert len(count_builds) == 1 and r1.json() == r2.json()
    etag = r1.headers["etag"]
    n = c.get(seed.url(), headers={**R, "If-None-Match": etag})
    assert n.status_code == 304 and n.content == b"" and n.headers["etag"] == etag
    assert c.get(seed.url(), headers={**R, "If-None-Match": f'W/{etag}, "other"'}).status_code == 304
    assert c.get(seed.url(), headers={**R, "If-None-Match": '"zzz"'}).status_code == 200
    for tail in ("/part.glb", "/values.bin"):
        assert c.get(seed.url(tail), headers={**R, "If-None-Match": etag}).status_code == 304
        assert c.get(seed.url(tail), headers=R).status_code == 200
    assert len(count_builds) == 1


def test_input_change_rebuilds_and_moves_old_to_backup(mk, seed, count_builds):
    c = mk()
    k1 = c.get(seed.url(), headers=R).json()["key"]
    old_manifest = (seed.view_dir / "manifest.json").read_text(encoding="utf-8")
    f = seed.dir / "runs" / seed.run_id / "04_esl" / "f_eq.npz"
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))      # 입력 mtime 변경
    r = c.get(seed.url(), headers=R)
    assert r.status_code == 200 and r.json()["key"] != k1 and len(count_builds) == 2
    moved = list((seed.dir / "_backup").glob(f"*/runs/{seed.run_id}/view3d/manifest.json"))
    assert len(moved) == 1 and moved[0].read_text(encoding="utf-8") == old_manifest      # 이동(삭제 아님)
    assert (seed.view_dir / "manifest.json").is_file()
    assert c.get(seed.url("/part.glb"), params={"key": k1}, headers=R).status_code == 409          # 이전 키 → STALE
    assert c.get(seed.url("/part.glb"), params={"key": r.json()["key"]}, headers=R).status_code == 200


def test_builder_version_and_settings_change_rebuild(mk, seed, count_builds, monkeypatch):
    from esl_platform.api.services import view3d as svc

    c = mk()
    k1 = c.get(seed.url(), headers=R).json()["key"]
    monkeypatch.setattr(svc, "BUILDER_VERSION", 2)
    k2 = c.get(seed.url(), headers=R).json()["key"]
    assert k2 != k1 and len(count_builds) == 2
    monkeypatch.setattr(svc, "BUILDER_VERSION", 1)
    c2 = mk(top_max=10)                                                        # view3d 설정 변경
    d3 = c2.get(seed.url(), headers=R).json()
    assert d3["key"] not in (k1, k2) and len(d3["top"]) == 10 and len(count_builds) == 3
    assert len(list((seed.dir / "_backup").glob(f"*/runs/{seed.run_id}/view3d"))) == 2


def test_concurrent_requests_build_once_and_busy_503(mk, seed, monkeypatch):
    from esl_worker import core_adapter

    real = core_adapter.view3d_build
    calls, gate = [], threading.Event()

    def slow(out_dir, **kw):
        calls.append(1)
        gate.wait(5)
        return real(out_dir, **kw)

    monkeypatch.setattr(core_adapter, "view3d_build", slow)
    c = mk()
    with ThreadPoolExecutor(2) as ex:
        f1 = ex.submit(c.get, seed.url(), headers=R)
        f2 = ex.submit(c.get, seed.url(), headers=R)
        time.sleep(0.5)
        gate.set()
        r1, r2 = f1.result(10), f2.result(10)
    assert r1.status_code == r2.status_code == 200 and len(calls) == 1 and r1.json()["key"] == r2.json()["key"]
    # 대기 초과 → 503 + Retry-After
    import shutil

    shutil.rmtree(seed.view_dir)
    calls.clear()
    gate.clear()
    c = mk(build_wait_s=0.3)
    with ThreadPoolExecutor(2) as ex:
        f1 = ex.submit(c.get, seed.url(), headers=R)
        time.sleep(0.3)
        busy = c.get(seed.url(), headers=R)
        gate.set()
        ok = f1.result(10)
    assert busy.status_code == 503 and code(busy) == "VIEW3D_BUSY" and busy.headers["retry-after"] == "5"
    assert ok.status_code == 200 and len(calls) == 1


# ---------------------------------------------------------------- V-L3-9 오류
def test_error_codes(mk, seed, engine, world):
    c = mk()
    assert c.get(seed.url()).status_code == 401
    assert c.get(f"{API}/esl-runs/nope/view3d", headers=R).status_code == 404
    # 파일 엔드포인트는 생성하지 않음: 캐시 없음 → 409 VIEW3D_STALE
    r = c.get(seed.url("/part.glb"), headers=R)
    assert r.status_code == 409 and code(r) == "VIEW3D_STALE" and not seed.view_dir.exists()
    assert c.get(seed.url("/values.bin"), headers=R).status_code == 409
    assert c.get(seed.url(), headers=R).status_code == 200
    r = c.get(seed.url("/part.glb"), params={"key": "0000000000000000"}, headers=R)
    assert r.status_code == 409 and code(r) == "VIEW3D_STALE"
    # run FAILED
    with engine.begin() as cn:
        cn.execute(update(esl_runs).where(esl_runs.c.id == seed.run_id).values(status="FAILED"))
    r = c.get(seed.url(), headers=R)
    assert r.status_code == 409 and code(r) == "ESL_RUN_FAILED"
    assert code(c.get(seed.url("/part.glb"), headers=R)) == "ESL_RUN_FAILED"
    # 산출물 없음
    s2 = Seed(world, engine, synth_mesh(4, 4), folder="c2", snapshot=False)
    r = c.get(s2.url(), headers=R)
    assert r.status_code == 409 and code(r) == "PREREQUISITE_MISSING" and r.json()["detail"]["missing"] == ["esl"]
    # 다른 실행으로 바뀜(스냅샷 없음 + 현재 아님)
    s3 = Seed(world, engine, synth_mesh(4, 4), folder="c3", snapshot=False, make_current=False)
    r = c.get(s3.url(), headers=R)
    assert r.status_code == 409 and code(r) == "ESL_RUN_NOT_CURRENT"


def test_node_mismatch_500_and_disabled_404(mk, seed):
    c = mk()
    bad = seed.m["node_id"].copy()
    bad[0] += 1000
    seed.write_run(seed.dir / "runs" / seed.run_id, nid_f=bad)
    r = c.get(seed.url(), headers=R)
    assert r.status_code == 500 and code(r) == "OUTPUT_INCONSISTENT" and not seed.view_dir.exists()
    off = mk(enabled=False)
    r = off.get(seed.url(), headers=R)
    assert r.status_code == 404 and code(r) == "VIEW3D_DISABLED"
    assert code(off.get(seed.url("/part.glb"), headers=R)) == "VIEW3D_DISABLED"


def test_too_large_413_not_cached_and_retry_after_raising_limit(mk, seed):
    n = int(seed.m["node_id"].size)
    c = mk(max_nodes=n - 1)
    r = c.get(seed.url(), headers=R)
    d = r.json()["detail"]
    assert r.status_code == 413 and d["code"] == "VIEW3D_TOO_LARGE" and d["limits"]["max_nodes"] == n - 1
    assert d["n_nodes"] == n and not seed.view_dir.exists() and not list(seed.view_dir.parent.glob("view3d.tmp-*"))
    c = mk(max_glb_bytes=1000)                                                   # 파일 크기 상한
    r = c.get(seed.url(), headers=R)
    assert r.status_code == 413 and r.json()["detail"]["glb_bytes"] > 1000 and not seed.view_dir.exists()
    assert not list(seed.view_dir.parent.glob("view3d.tmp-*"))
    c = mk()                                                                     # 설정을 올리면 바로 다시 시도
    assert c.get(seed.url(), headers=R).status_code == 200


def test_past_run_from_snapshot_is_served(mk, world, engine):
    """현재 Case 산출물이 다른 실행으로 바뀌어도 runs/<id> 스냅샷이 있으면 200."""
    s = Seed(world, engine, synth_mesh(6, 5, seed=1), folder="c9", make_current=False)
    c = mk()
    assert c.get(s.url(), headers=R).status_code == 200
    assert (s.dir / "runs" / s.run_id / "view3d" / "manifest.json").is_file()
    assert not (s.dir / "04_esl").exists()                                       # 코어 04_esl 에는 쓰지 않음


def test_view3d_settings_default_when_section_missing_and_validated(tmp_path):
    from esl_platform.core.config import load_config_dict

    d = make_settings_dict(tmp_path)
    d.pop("view3d")
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    v = lc.settings.view3d
    assert (v.enabled, v.max_nodes, v.max_glb_bytes, v.lod_min_nodes, v.lod_target_vertices, v.top_max,
            v.cluster_k_max, v.kmeans_max_iter, v.build_wait_s) == (True, 2_000_000, 64 * 1024 ** 2, 500_000, 100_000,
                                                                      100, 5, 50, 60.0)
    d2 = make_settings_dict(tmp_path, view3d={"max_nodes": 0})
    assert not load_config_dict(d2, environ={}).ok                       # 범위 검증
    d3 = make_settings_dict(tmp_path, view3d={"bogus": 1})
    assert not load_config_dict(d3, environ={}).ok                       # 알 수 없는 키 거부
