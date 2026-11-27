"""v0.25.1 B1 — 낙하 씬별 3D 조회·생성 요청 API(계약 esl_view3d_scene_legend.md §6·§7.1, V-0251-16~19).

코어(C1)의 `post/view3d_scene/**`·`post/scene_view.json` 은 계약 §2.2·§2.3 형식의 가짜 자료로 심는다(코어 함수 호출 없음).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from doe_support import api, finish_job, study_dir
from test_doe_compare_api import (  # noqa: F401  (픽스처·도우미 재사용)
    _fresh_cache,
    code,
    settings_dict,
    world,
)
from test_doe_jig_view_api import _run_job
from test_doe_rank_metric_api import _done

SIDECAR_SCHEMA = "esl/doe_scene_view/1"
ENTRIES = [{"entry_id": "e1", "kk": 0}, {"entry_id": "e2", "kk": 1}]


def _manifest_base(tmp: Path) -> tuple[dict, bytes, bytes]:
    """실제 view3d 형식의 manifest·part.glb·values.bin(합성 평판) — 씬 manifest 의 바탕."""
    import numpy as np
    from esl.view3d import build_view
    from opt_support import plate

    m = plate(nx=4, ny=3)
    f = np.zeros((m["node_id"].size, 3))
    f[:, 1] = 1.0
    build_view(str(tmp), node_id=m["node_id"], x0=m["x0"], conn=m["conn"], elem_type=m["elem_type"], f=f, u_rel=f * 0.01,
               supports=[{"node_id": int(m["node_id"][0]), "dof": "123"}], key="doe/d000", esl_run_id="e1")
    return (json.loads((tmp / "manifest.json").read_text(encoding="utf-8")),
            (tmp / "part.glb").read_bytes(), (tmp / "values.bin").read_bytes())


def seed_scene(esl_root: Path, tmp: Path, sid: str, *, src="full", tag="sv", did="d000", entries=ENTRIES, scenes=("e1", "e2"),
               skipped=None, budget=None, c_kind="fu", sidecar_extra=None) -> Path:
    """사이드카 + 씬 묶음 폴더 1개(출처 src·안 did)를 계약 §2.2 형식으로 심는다. 묶음 폴더를 돌려줌."""
    base = study_dir(esl_root, sid)
    man, glb, val = _manifest_base(tmp / f"b_{src}_{did}")
    d = base / "post" / "view3d_scene" / tag / did
    d.mkdir(parents=True, exist_ok=True)
    (d / "part.glb").write_bytes(glb)
    kk_of = {e["entry_id"]: e["kk"] for e in entries}
    pack_scenes = []
    for eid in scenes:
        kk = kk_of[eid]
        sm = {**man, "c": {"kind": c_kind, "sum": 12.5, "offset": 0.0, "value": 12.5, "parts": {"W_F": 12.5}, "unit": "N·mm"},
              "dc": None, "pins": {"umax": {"node_id": 7, "vertex": 3, "value": 0.25, "kind": "ev"}},
              "ranges": {**man["ranges"], "c": {"min": -1.0, "max": 5.0, "p01": -0.5, "p99": 4.5}, "dc": None}}
        (d / f"e{kk:02d}.json").write_text(json.dumps(sm), encoding="utf-8")
        (d / f"e{kk:02d}.bin").write_bytes(val + bytes([kk]))
        pack_scenes.append({"entry_id": eid, "kk": kk, "manifest": f"e{kk:02d}.json", "values": f"e{kk:02d}.bin"})
    (d / "pack.json").write_text(json.dumps({
        "schema": "esl/view3d_scene/1", "builder_version": 1, "key": f"doe/{did}", "src": src, "did": did,
        "geometry": {"name": "part.glb", "bytes": len(glb)}, "lod": None, "scenes": pack_scenes}), encoding="utf-8")
    side = {"schema": SIDECAR_SCHEMA, "builder_version": 1, "source": "bd_post", "created_at": "2026-11-27T00:00:00Z", "seconds": 1.5,
            "entries": entries,
            "packs": {src: {"tag": tag, "c_kind": c_kind, "designs": {did: {"dir": f"{tag}/{did}", "scenes": list(scenes)}},
                            "skipped": skipped or []}},
            "budget": budget or {"max_mb": 1024, "est_mb": 0.5, "n_scenes": len(scenes), "n_written": len(scenes)},
            "warnings": [], **(sidecar_extra or {})}
    (base / "post" / "scene_view.json").write_text(json.dumps(side), encoding="utf-8")
    return d


@pytest.fixture()
def sid(client, world, engine, esl_root):  # noqa: F811
    s = _done(client, world, engine, esl_root, {})
    _run_job(engine, s)
    return s


# ================================================================ V-0251-16 results.scene_view
def test_scene_view_none_when_no_sidecar(client, sid):
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert o["scene_view"] is None
    assert o["scene_add"] == {"ok": True, "blocked": None}
    assert "SCENE_VIEW_INVALID" not in {w.get("code") for w in o["warnings"] if isinstance(w, dict)}


def test_scene_view_summary(client, sid, esl_root, tmp_path):
    skipped = [{"did": "d001", "entry_id": "e2", "code": "SCENE_BUDGET"}, {"did": "d002", "code": "SCENE_FAILED", "detail": "NaN"}]
    seed_scene(esl_root, tmp_path, sid, skipped=skipped, budget={"max_mb": 64, "est_mb": 3.25, "n_scenes": 2, "n_written": 2})
    o = api(client, "GET", f"/doe/studies/{sid}/results").json()
    sv = o["scene_view"]
    assert sv["entries"] == ENTRIES and sv["budget"] == {"max_mb": 64.0, "est_mb": 3.25}
    assert list(sv["packs"]) == ["full"]
    pk = sv["packs"]["full"]
    assert pk["c_kind"] == "fu" and pk["designs"] == {"d000": ["e1", "e2"]}
    assert [(x["did"], x["entry_id"], x["code"]) for x in pk["skipped"]] == [("d001", "e2", "SCENE_BUDGET"), ("d002", None, "SCENE_FAILED")]
    assert "max_mb" in pk["skipped"][0]["text"] and pk["skipped"][1]["text"].endswith("(NaN)")
    assert "tag" not in pk and "dir" not in json.dumps(sv)                       # 내부 경로는 응답에 없음
    assert str(esl_root) not in json.dumps(o)


def test_scene_view_unknown_src_and_bad_did_dropped(client, sid, esl_root, tmp_path):
    base = study_dir(esl_root, sid)
    seed_scene(esl_root, tmp_path, sid)
    side = json.loads((base / "post" / "scene_view.json").read_text(encoding="utf-8"))
    side["packs"]["evil"] = side["packs"]["full"]
    side["packs"]["full"]["designs"]["../x"] = {"dir": "../x", "scenes": ["e1"]}
    (base / "post" / "scene_view.json").write_text(json.dumps(side), encoding="utf-8")
    sv = api(client, "GET", f"/doe/studies/{sid}/results").json()["scene_view"]
    assert list(sv["packs"]) == ["full"] and list(sv["packs"]["full"]["designs"]) == ["d000"]


@pytest.mark.parametrize("content", ["{not json", "[]", json.dumps({"schema": "other/1", "entries": [], "packs": {}}),
                                     json.dumps({"schema": SIDECAR_SCHEMA, "entries": [{"entry_id": "e1"}], "packs": {"full": {}}})])
def test_scene_view_broken_sidecar_is_null_with_warning(client, sid, esl_root, content):
    base = study_dir(esl_root, sid)
    (base / "post" / "scene_view.json").write_text(content, encoding="utf-8")
    r = api(client, "GET", f"/doe/studies/{sid}/results")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["scene_view"] is None
    assert "SCENE_VIEW_INVALID" in {w.get("code") for w in o["warnings"] if isinstance(w, dict)}


def test_results_existing_keys_unchanged(client, sid, esl_root, tmp_path):
    """사이드카가 있어도 기존 응답 키는 같고 새 키 scene_view·scene_add 만 늘어난다."""
    before = api(client, "GET", f"/doe/studies/{sid}/results").json()
    seed_scene(esl_root, tmp_path, sid)
    after = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert {k: v for k, v in after.items() if k not in ("scene_view", "scene_add")} == \
           {k: v for k, v in before.items() if k not in ("scene_view", "scene_add")}


# ================================================================ V-0251-17 조회
def test_scene_manifest_and_files(client, sid, esl_root, tmp_path):
    seed_scene(esl_root, tmp_path, sid)
    p = f"/doe/studies/{sid}/view3d-scene/full/d000"
    r = api(client, "GET", f"{p}/e2/manifest.json")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["geometry_url"] == f"{p}/part.glb" and m["lod_url"] is None and m["values_url"] == f"{p}/e01.bin"
    assert m["values"]["name"] == "e01.bin" and m["geometry"]["name"] == "part.glb"
    assert m["c"]["sum"] == 12.5 and m["c"]["kind"] == "fu" and m["dc"] is None
    assert m["pins"]["umax"] == {"node_id": 7, "vertex": 3, "value": 0.25, "kind": "ev"}
    assert m["ranges"]["c"]["p99"] == 4.5 and m["ranges"]["dc"] is None and m["ranges"]["u_max"] > 0   # 기존 키 + 새 키
    g = api(client, "GET", m["geometry_url"])
    assert g.status_code == 200 and g.content[:4] == b"glTF" and g.headers["content-type"].startswith("model/gltf-binary")
    assert g.headers["cache-control"] == "private, no-cache" and g.headers["x-content-type-options"] == "nosniff"
    v1, v2 = api(client, "GET", f"{p}/e00.bin"), api(client, "GET", m["values_url"])
    assert v1.status_code == v2.status_code == 200 and v1.content[-1:] == b"\x00" and v2.content[-1:] == b"\x01"
    assert v2.headers["content-type"].startswith("application/octet-stream")


def test_scene_manifest_old_view3d_unchanged(client, sid, esl_root, tmp_path):
    """기존 /view3d/{did}/manifest.json 응답에는 새 키(c·dc·pins)가 생기지 않는다(View3dOut 불변)."""
    from esl_platform.api.schemas import View3dOut

    assert not {"c", "dc", "pins"} & set(View3dOut.model_fields)
    assert "c" not in View3dOut.model_fields["ranges"].annotation.model_fields


def test_scene_lod_served(client, sid, esl_root, tmp_path):
    d = seed_scene(esl_root, tmp_path, sid)
    (d / "part_lod.glb").write_bytes(b"glTFlod")
    pk = json.loads((d / "pack.json").read_text(encoding="utf-8"))
    pk["lod"] = {"name": "part_lod.glb", "bytes": 7, "n_vertices": 4}
    (d / "pack.json").write_text(json.dumps(pk), encoding="utf-8")
    p = f"/doe/studies/{sid}/view3d-scene/full/d000"
    m = api(client, "GET", f"{p}/e1/manifest.json").json()
    assert m["lod_url"] == f"{p}/part_lod.glb" and api(client, "GET", m["lod_url"]).content == b"glTFlod"


@pytest.mark.parametrize("path", [
    "view3d-scene/nope/d000/e1/manifest.json",                 # src 화이트리스트 밖
    "view3d-scene/jig/d000/e1/manifest.json",                  # 사이드카에 없는 출처
    "view3d-scene/full/D000/e1/manifest.json",                 # did 정규식
    "view3d-scene/full/d999/e1/manifest.json",                 # 사이드카에 없는 안
    "view3d-scene/full/d000/zzz/manifest.json",                # 사이드카에 없는 엔트리
    "view3d-scene/full/d000/e1%00/manifest.json",
    "view3d-scene/full/d000/..%2f..%2fe1/manifest.json",
    "view3d-scene/full/d000/values.bin",                       # pack.json 에 없는 이름
    "view3d-scene/full/d000/pack.json",
    "view3d-scene/full/d000/e00.json",                         # manifest 는 manifest 경로로만
    "view3d-scene/full/d000/..%2fpack.json",
    "view3d-scene/full/d000/e07.bin",
    "view3d-scene/full/d000/part_lod.glb",                     # lod 없음
])
def test_scene_404s(client, sid, esl_root, tmp_path, path):
    seed_scene(esl_root, tmp_path, sid)
    r = api(client, "GET", f"/doe/studies/{sid}/{path}")
    assert r.status_code == 404 and (r.json().get("detail") or {}).get("code") in ("VIEW3D_SCENE_NOT_FOUND", "NOT_FOUND"), (path, r.text)


def test_scene_no_sidecar_404_code(client, sid):
    r = api(client, "GET", f"/doe/studies/{sid}/view3d-scene/full/d000/e1/manifest.json")
    assert r.status_code == 404 and code(r) == "VIEW3D_SCENE_NOT_FOUND"
    r = api(client, "GET", f"/doe/studies/{sid}/view3d-scene/full/d000/part.glb")
    assert r.status_code == 404 and code(r) == "VIEW3D_SCENE_NOT_FOUND"


def test_scene_entry_in_sidecar_but_not_in_pack(client, sid, esl_root, tmp_path):
    seed_scene(esl_root, tmp_path, sid, scenes=("e1",))
    r = api(client, "GET", f"/doe/studies/{sid}/view3d-scene/full/d000/e2/manifest.json")
    assert r.status_code == 404 and code(r) == "VIEW3D_SCENE_NOT_FOUND"


def test_scene_symlinks_rejected(client, sid, esl_root, tmp_path):
    d = seed_scene(esl_root, tmp_path, sid)
    p = f"/doe/studies/{sid}/view3d-scene/full/d000"
    # 파일 링크
    outside = tmp_path / "secret.bin"
    outside.write_bytes(b"SECRET")
    (d / "e00.bin").unlink()
    os.symlink(outside, d / "e00.bin")
    assert api(client, "GET", f"{p}/e00.bin").status_code == 404
    assert api(client, "GET", f"{p}/e1/manifest.json").status_code == 404           # 값 파일이 링크 → manifest 도 404
    # 폴더 링크
    moved = tmp_path / "moved_d000"
    shutil.move(str(d), str(moved))
    os.symlink(moved, d)
    assert api(client, "GET", f"{p}/part.glb").status_code == 404
    assert api(client, "GET", f"{p}/e2/manifest.json").status_code == 404


def test_scene_tag_escape_rejected(client, sid, esl_root, tmp_path):
    seed_scene(esl_root, tmp_path, sid)
    base = study_dir(esl_root, sid)
    side = json.loads((base / "post" / "scene_view.json").read_text(encoding="utf-8"))
    side["packs"]["full"]["tag"] = ".."
    (base / "post" / "scene_view.json").write_text(json.dumps(side), encoding="utf-8")
    assert api(client, "GET", f"/doe/studies/{sid}/view3d-scene/full/d000/part.glb").status_code == 404


def test_scene_permissions(client, sid, esl_root, tmp_path):
    seed_scene(esl_root, tmp_path, sid)
    for tail in ("e1/manifest.json", "part.glb"):
        u = f"/doe/studies/{sid}/view3d-scene/full/d000/{tail}"
        assert api(client, "GET", u, "tok-nonmember").status_code == 403
        assert api(client, "GET", u, "tok-general").status_code == 200                # 조회 권한만으로 읽기
    assert api(client, "GET", f"/doe/studies/{sid}/results", "tok-general").json()["scene_view"] is not None


# ================================================================ V-0251-18 POST view3d/scenes
def test_scenes_post_queues_run_from_bd_post(client, sid, engine):
    from esl_platform.core.job_types import steps_for
    from esl_platform.core.repositories import jobs as jobs_repo

    r = api(client, "POST", f"/doe/studies/{sid}/view3d/scenes")
    assert r.status_code == 202, r.text
    jid = r.json()["job"]["id"]
    with engine.connect() as c:
        job = jobs_repo.get_job(c, jid)
        steps = jobs_repo.get_steps(c, jid)
    assert job["job_type"] == "DOE_RUN"
    p = job["params"]
    assert p["kind"] == "VIEW3D" and p["doe"]["post_mode"] == "scene" and p["warnings"] == []
    assert "None_cfg" not in p["doe"]
    keys = [sd.key for sd in steps_for("DOE_RUN")]
    done = {x["step_key"] for x in steps if x["state"] == "SKIPPED" or x["state"] == "SUCCEEDED"}
    resume = keys.index("BD_POST")
    assert all(k in done for k in keys[:resume]) or all(x["state"] != "RUNNING" for x in steps)
    # 작업 중 → 409 JOB_ACTIVE
    r2 = api(client, "POST", f"/doe/studies/{sid}/view3d/scenes")
    assert r2.status_code == 409 and code(r2) == "JOB_ACTIVE"
    finish_job(engine, jid)
    assert api(client, "POST", f"/doe/studies/{sid}/view3d/scenes").status_code == 202    # 끝난 뒤 다시(멱등은 코어)


def test_scenes_post_permissions(client, sid):
    u = f"/doe/studies/{sid}/view3d/scenes"
    assert api(client, "POST", u, "tok-power2").status_code == 403                  # 실행 권한 있으나 작성자 아님
    assert api(client, "POST", u, "tok-general").status_code == 403                 # 실행 권한 없음
    assert api(client, "POST", u, "tok-nonmember").status_code == 403
    r = api(client, "GET", f"/doe/studies/{sid}/results", "tok-power2").json()
    assert r["scene_add"]["ok"] is False and "씬 3D 를 만들" in r["scene_add"]["blocked"]
    assert api(client, "POST", u, "tok-admin").status_code == 202                   # 관리자 가능


def test_scenes_post_unavailable(client, world, engine, esl_root, monkeypatch):  # noqa: F811
    from esl_platform.api.services import doe as svc

    s = _done(client, world, engine, esl_root, {})                                  # 성공한 DOE_RUN 작업 없음
    r = api(client, "POST", f"/doe/studies/{s}/view3d/scenes")
    assert r.status_code == 409 and code(r) == "VIEW3D_SCENE_UNAVAILABLE", r.text
    assert api(client, "GET", f"/doe/studies/{s}/results").json()["scene_add"]["ok"] is False
    _run_job(engine, s)
    monkeypatch.setattr(svc, "_scene_enabled", lambda c: False)                      # 설정 끔
    r = api(client, "POST", f"/doe/studies/{s}/view3d/scenes")
    assert r.status_code == 409 and code(r) == "VIEW3D_SCENE_UNAVAILABLE" and "enabled" in r.json()["detail"]["message"]
    o = api(client, "GET", f"/doe/studies/{s}/results").json()
    assert o["scene_add"]["ok"] is False and "enabled" in o["scene_add"]["blocked"]


def test_scenes_post_unfinished_study(client, world, engine, esl_root):  # noqa: F811
    from doe_support import body, update_study  # noqa: F401
    from test_doe_compare_api import cbody, shapes3

    s = api(client, "POST", "/doe/studies", json=cbody(world, shapes3(client))).json()
    r = api(client, "POST", f"/doe/studies/{s['id']}/view3d/scenes")
    assert r.status_code == 409 and code(r) in ("VIEW3D_SCENE_UNAVAILABLE", "JOB_ACTIVE")


# ================================================================ §7.1 설정
def test_scene_config_defaults_and_ranges():
    import yaml
    from esl_platform.core.config import BeadDoeView3dCfg, load_config_dict

    d = BeadDoeView3dCfg().scene.model_dump()
    assert d == {"enabled": True, "max_mb": 1024, "diff_cell_h_mult": 2.0}
    root = Path(__file__).resolve().parents[2]
    for name in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load((root / "config" / name).read_text(encoding="utf-8"))
        assert y["bead_doe"]["view3d"]["scene"] == d, name
    for bad in ({"max_mb": -1}, {"max_mb": 65537}, {"diff_cell_h_mult": 0.4}, {"diff_cell_h_mult": 8.5}, {"enabled": "maybe"}, {"x": 1}):
        with pytest.raises(Exception):
            BeadDoeView3dCfg(scene=bad)
    for ok in ({"max_mb": 0}, {"max_mb": 65536}, {"diff_cell_h_mult": 0.5}, {"diff_cell_h_mult": 8}):
        BeadDoeView3dCfg(scene=ok)


def test_scene_config_reaches_core_settings(tmp_path):
    """bead_doe_settings 가 view3d.scene 기본값(코어 DEFAULTS 병합 전에도)·설정값을 코어 dict 에 싣는다."""
    from esl_platform.core.config import bead_doe_settings, load_config_dict
    from esl_test_support import make_settings_dict

    d = make_settings_dict(tmp_path)
    d["bead_doe"] = {"enabled": True, "view3d": {"scene": {"enabled": False, "max_mb": 5}}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.errors()
    sc = bead_doe_settings(lc.settings)["view3d"]["scene"]
    assert sc == {"enabled": False, "max_mb": 5, "diff_cell_h_mult": 2.0}


# ================================================================ V-0251-19 OpenAPI·고정 필드
def test_openapi_has_scene_paths_and_schemas():
    root = Path(__file__).resolve().parents[2]
    spec = json.loads((root / "docs" / "contracts" / "openapi_p1b.json").read_text(encoding="utf-8"))
    base = "/esl/api/doe/studies/{sid}"
    paths = spec["paths"]
    assert "post" in paths[f"{base}/view3d/scenes"]
    assert "get" in paths[f"{base}/view3d-scene/{{src}}/{{did}}/{{entry_id}}/manifest.json"]
    assert "get" in paths[f"{base}/view3d-scene/{{src}}/{{did}}/{{name}}"]
    sc = spec["components"]["schemas"]
    for n in ("DoeSceneViewOut", "DoeSceneAddOut", "View3dSceneOut"):
        assert n in sc, n
    assert {"scene_view", "scene_add"} <= set(sc["DoeResultOut"]["properties"])
    assert {"c", "dc", "pins"} <= set(sc["View3dSceneOut"]["properties"])
    assert {"c", "dc"} <= set(sc["View3dSceneRanges"]["properties"])
    assert {"entries", "packs", "budget"} <= set(sc["DoeSceneViewOut"]["properties"])
    assert set(sc["DoeSceneAddOut"]["properties"]) == {"ok", "blocked"}
    assert set(sc["DoeScenePackOut"]["properties"]) == {"c_kind", "designs", "skipped"}
    assert set(sc["DoeSceneSkippedOut"]["properties"]) == {"did", "entry_id", "code", "text"}
    assert not {"c", "dc", "pins"} & set(sc["View3dOut"]["properties"])             # 기존 스키마 불변


def test_openapi_snapshot_is_current():
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, str(root / "scripts" / "dump_openapi.py"), "--check"], capture_output=True, text=True, cwd=root)
    assert r.returncode == 0, r.stdout + r.stderr


def test_scene_messages_present():
    from esl_platform.api.services import uploads as up_svc

    for k in ("SCENE_BUDGET", "SCENE_FAILED", "SCENE_NO_SOURCE", "SCENE_DIFF_NO_FRAME", "SCENE_VIEW_INVALID", "SCENE_UNAVAILABLE_DISABLED"):
        assert up_svc.doe_text(k) != k, k
