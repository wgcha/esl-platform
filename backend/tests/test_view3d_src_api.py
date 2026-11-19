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
