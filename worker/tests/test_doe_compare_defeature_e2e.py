"""v0.16.1 ④ 사다리 defeature 단계 워커 E2E(계약 esl_select_relax.md V-SR-24) — 실제 PG·백엔드 API·워커·코어·gmsh·자체 솔버.

실패 주입은 코어 시험에서만(D-0.16-WORKER) → 설정만으로 cad 가 실패하는 형상: 비드 바닥 구면 딤플 판(synth_compare
bead_with_features + 얕은 딤플 1.5, XZ 로 돌림)을 주기 면 형상 폴백을 끈 설정(compare.mesh.fallback.periodic_order =
[algorithms, relax] — v0.14.1 폴백)으로 읽으면 깊이 2 딤플의 Sphere 면이 메시 실패(test_mesh_sphere 와 같은 재현). 사다리 [cad, defeature] + min_bead_height_mm 9 → 구면 딤플 4개(깊이 1.5·2·5·8)
를 평탄화(bead)한 형상으로 메시 성공.
→ 형상 행 mesh_method defeature·defeature 요약·attempts(cad → defeature), 준비 요약 n_defeature, MESH_DEFEATURED·
COMPARE_MESH_METHOD_MIXED, ranking.csv mesh_method defeature, 보고서 '작은 형상 억제' 절, GET …/shapes/{did}/defeature 200.
gmsh 없으면 skip."""

from __future__ import annotations

import csv
import io
import math
import os
import sys
from pathlib import Path

import pytest
from doe_support import api
from doe_worker_support import doe_worker_settings
from esl_test_support import API, REPO
from opt_support import upload_files
from test_doe_compare_e2e import (  # noqa: F401 - 픽스처
    PROPS,
    R,
    _gmsh_ok,
    create,
    exe,
    run_job,
    steps,
    study,
    worker,
)
from test_opt_e2e import make_s1

sys.path.insert(0, str(REPO / "tests" / "doe"))
import synth_compare as scmp  # noqa: E402

pytestmark = [pytest.mark.skipif(os.name == "nt", reason="가짜 paicad 는 POSIX 실행 스크립트"),
              pytest.mark.skipif(not _gmsh_ok(), reason="gmsh 없음")]
NO_SHAPE_FB = {"periodic_order": ["algorithms", "relax"]}     # 주기 면(Sphere) 형상 폴백(nofix·split·fill·small) 끔 = v0.14.1 폴백
FEAT_SPEC = {"dimples": scmp.BEAD_FEATURES["dimples"] + [(120.0, 130.0, 10.0, 1.5)]}


@pytest.fixture()
def settings_dict(tmp_path, exe):  # noqa: F811
    d = doe_worker_settings(tmp_path, exe, mesh={"occ_sew_faces": 1})
    d["bead_doe"]["compare"] = {"mesh": {"size_mm": 3.0, "ladder": ["cad", "defeature"], "fallback": dict(NO_SHAPE_FB)},
                                "defeature": {"min_bead_height_mm": 9.0}}
    return d


def feat_step_xz(path: Path) -> bytes:
    """bead_with_features(FEAT_SPEC, XY 판 300×200) → x 축 +90° 회전(XZ 판 — make_s1 ESL 메시와 같은 평면) STEP 바이트."""
    import gmsh

    src = scmp.bead_with_features_step(str(path.with_suffix(".xy.step")), FEAT_SPEC)
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        ents = gmsh.model.occ.importShapes(src)
        gmsh.model.occ.rotate(ents, 0, 0, 0, 1, 0, 0, math.pi / 2)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()


def test_compare_defeature_stage_e2e(client, engine, worker, esl_root, inputs_root, exe, tmp_path):
    s1 = make_s1(engine, esl_root, inputs_root, kinds=(("bend", 2.0), ("twist", 1.5)))
    files = steps(tmp_path, [("flat", 0, {})])
    files["rad/feat.step"] = feat_step_xz(tmp_path / "gen" / "feat.step")
    uid = upload_files(client, files)
    s = create(client, s1["entry_ids"], [{"upload_id": uid, "rel": "rad/flat.step", "name": "기준 평판", "reference": True},
                                         {"upload_id": uid, "rel": "rad/feat.step", "name": "딤플 비드"}])
    sid = s["id"]
    run_job(client, worker, s["job"]["id"])
    g = study(client, sid)
    st = {x["id"]: x for x in g["prep"]["shapes"]}
    assert st["d000"]["mesh_method"] == "cad" and "defeature" not in st["d000"]       # cad 성공 형상 = 키 없음
    x = st["d001"]
    assert x["status"] == "READY" and x["mesh_method"] == "defeature", x
    assert x["cad_error"]["code"] and [a["stage"] for a in x["attempts"]] == ["cad", "defeature"]
    df = x["defeature"]
    assert set(df) == {"n", "counts", "skipped_n", "suppressed_max_mm", "outside_hausdorff_mm"}
    assert df["n"] >= 2 and df["counts"].get("bead", 0) == 4 and df["suppressed_max_mm"] > 0
    assert g["prep"]["n_defeature"] == 1
    codes = [w["code"] for w in g["prep"]["warnings"]]
    assert "MESH_DEFEATURED" in codes and "COMPARE_MESH_METHOD_MIXED" in codes
    r = api(client, "GET", f"/doe/studies/{sid}/shapes/d001/defeature")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["n"] >= df["n"] and sum(f["action"] == "suppressed" for f in doc["features"]) == df["n"]
    assert api(client, "GET", f"/doe/studies/{sid}/shapes/d000/defeature").status_code == 404
    # 실행 → ranking.csv mesh_method 열·보고서 절
    r = api(client, "POST", f"/doe/studies/{sid}/run", json={"version": g["version"]})
    assert r.status_code == 202, r.text
    run_job(client, worker, r.json()["job"]["id"])
    res = api(client, "GET", f"/doe/studies/{sid}/results").json()
    assert [y["id"] for y in res["ranking"]] == ["d001"] and res["ranking"][0]["shape"]["mesh_method"] == "defeature"
    assert res["ranking"][0]["shape"]["defeature"]["n"] == df["n"]
    rows = list(csv.DictReader(io.StringIO((esl_root / "_doe" / sid / "post" / "ranking.csv").read_text(encoding="utf-8"))))
    assert [y["mesh_method"] for y in rows if y["id"] == "d001"] == ["defeature"]
    rep = client.get(f"{API}/doe/studies/{sid}/report", headers=R)
    assert rep.status_code == 200 and "작은 형상 억제" in rep.text and "형상 단순화" in rep.text
