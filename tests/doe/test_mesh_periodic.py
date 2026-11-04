"""v0.14.1 ④ periodic 면(원통·원뿔) 메싱 실패 핫픽스(이슈 #53 최신 코멘트 'Impossible to mesh periodic surface').

원인: 작은 구멍 메움·구멍 둘레 분할(``mesh_gmsh.defeature``)이 면의 '내부 고리'를 모두 구멍으로 봤다.
- periodic 면은 ``getBoundary(combined=True)`` 가 seam(이음선)을 지워 원통·원뿔 양 끝 원이 따로 떨어진 고리로 보이고,
  그중 짧은 쪽을 구멍으로 메움(열린 관 끝을 막는 면 + 전체 fragment)·둘레 분할 강제,
- 판의 보스·버링 이음 원(이웃 periodic 벽과 공유하는 모서리)도 구멍으로 메움 — 평면 재구성이 공유 모서리를 지워
  벽이 떨어지거나(MESH_DISCONNECTED) periodic 면 경계가 망가짐.
수정: 구멍 = 자유 모서리만으로 된 고리이면서 seam 끝점을 지나지 않는 고리. + 면 단위 폴백(실패한 면만 다른 2D 알고리즘 →
제약 해제), 끝내 실패하면 면 id·종류·bbox 중심을 사용자 문구로.
gmsh 가 없으면 skip."""
import numpy as np
import pytest

import synth_compare as scmp
from esl.doe import mesh_gmsh as mg
from esl.doe import scenario as sc
from esl.doe import settings
from esl.errors import EslError

needs_gmsh = pytest.mark.skipif(not mg.available()[0], reason="gmsh 없음")
PROPS = {"t": 1.0, "E": 205000.0, "nu": 0.3}
# 보스: (판 구멍 r1, 벽 끝 r2, 깊이, 바닥 고리 구멍 r3, 벽 옆 구멍 r)
BOSSES = [(5.0, 5.0, 5.0, 4.5, 0.0),         # 원통 벽 + 바닥 고리(가운데 r 4.5 → 둘레 분할 대상, 면적 > 50)
          (3.0, 3.0, 1.5, 0.0, 0.0),         # 작은 버링(r 3, 끝 열림) — 판 이음 원·관 끝 원은 구멍 아님
          (6.0, 3.6, 4.0, 1.5, 0.0),         # 원뿔 벽 + 나사 자리(r 1.5 → 메움)
          (10.0, 10.0, 20.0, 0.0, 2.0)]      # 긴 관(끝 열림) + 벽 옆 작은 구멍(r 2 → 메움, periodic 면 위 진짜 구멍)
HOLES = [(270.0, 30.0, 2.0)]                 # 판의 진짜 작은 구멍(메움)


def _ccfg(**mesh):
    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    cfg["mesh"].update(mesh)
    return cfg


@needs_gmsh
def test_periodic_boss_junctions_mesh(tmp_path):
    """재현: 보스·버링·열린 관(periodic 면)이 있는 판 STEP — 고치기 전 MESH_DISCONNECTED(이음 원 메움으로 벽이 떨어짐)."""
    src = scmp.boss_plate_step(tmp_path / "boss.step", BOSSES, holes=HOLES)
    m, meta = mg.mesh_file(src, 3.0, _ccfg(), PROPS)
    df = meta["defeature"]
    assert df["filled"] == 3, df                        # 판 r 2 · 나사 자리 r 1.5 · 관 옆 r 2 만(이음 원·관 끝 원 제외)
    assert df["hole_sized"] == 1, df                    # 바닥 고리 가운데 r 4.5 만
    assert df.get("not_hole", 0) >= 6, df               # 이음 원(판·벽 양쪽)·periodic 끝 원
    assert "mesh_fallback" not in meta                  # 원인 수정만으로 메시됨(폴백 불필요)
    assert not meta["errors"]
    X = m["x0"]
    # 열린 관·버링 끝은 막히지 않음: 관 바닥(z = -20) 가운데 근처에 노드 없음, 버링 바닥(z = -1.5) 가운데도
    for (x, y, z, r) in ((220.0, 80.0, -20.0, 9.0), (100.0, 80.0, -1.5, 2.5)):
        near = (np.abs(X[:, 2] - z) < 1e-6) & (np.hypot(X[:, 0] - x, X[:, 1] - y) < r)
        assert not near.any(), (x, z)


@needs_gmsh
def test_face_fallback_only_failed_face(tmp_path):
    """면 단위 폴백: 기본 2D 알고리즘이 한 면에서 실패(BAMG 를 기본으로 둬 결정적으로 재현) → 그 면만 설정 순서 알고리즘으로
    다시 → 성공, mesh_fallback·경고 MESH_FACE_FALLBACK(면 id·종류·중심). 폴백 끔 → 사용자 문구(면 id·종류·위치)."""
    src = scmp.boss_plate_step(tmp_path / "boss.step", BOSSES[:1] + BOSSES[2:3], holes=HOLES)
    m, meta = mg.mesh_file(src, 3.0, _ccfg(algorithm=7), PROPS)
    fb = meta["mesh_fallback"]
    assert 1 <= fb["n_faces"] < 5 and all(f["algorithm"] in (6, 5, 1) for f in fb["faces"])
    f0 = fb["faces"][0]
    assert f0["type"] and len(f0["center"]) == 3 and f0["errors"] and not f0["relaxed"]
    w = [x for x in meta["warnings"] if x["code"] == "MESH_FACE_FALLBACK"]
    assert len(w) == 1 and str(f0["failed_id"]) in w[0]["message"] and "위치 x" in w[0]["message"]
    assert int(m["elem_id"].size) > 1000 and not meta["errors"]                            # (BAMG 면은 비결정적 — 바이트 비교 안 함)
    with pytest.raises(EslError) as ei:                                                    # 폴백 끔 → 면 정보 문구
        mg.mesh_file(src, 3.0, _ccfg(algorithm=7, fallback={"enabled": False}), PROPS)
    assert ei.value.code == "FAILED_MESH"
    assert f"면 {f0['failed_id']}({f0['type']}, 위치 x" in ei.value.message
    with pytest.raises(EslError) as ei:                                                    # 끝내 실패(제약 해제 후에도)
        mg.mesh_file(src, 3.0, _ccfg(algorithm=7, fallback={"enabled": True, "algorithms": [7], "relax": True}), PROPS)
    msg = ei.value.message
    assert ei.value.code == "FAILED_MESH" and f"면 {f0['failed_id']}" in msg and "메시하지 못했습니다" in msg
    assert "BAMG(제약 해제)" in msg and "위치 x" in msg


@needs_gmsh
def test_plain_plate_unchanged_by_fix(tmp_path):
    """정상 STEP(판 + 구멍·비드)은 판정이 그대로: 구멍 고리는 자유 모서리 → 예전과 같은 메움·분할, 폴백 키 없음."""
    for name, p in (("h", scmp.plate_step(tmp_path / "h.step", Lx=200.0, Lz=150.0, hole=(100.0, 75.0, 2.0))),
                    ("H", scmp.plate_step(tmp_path / "H.step", Lx=200.0, Lz=150.0, hole=(100.0, 75.0, 24.0))),
                    ("b", scmp.plate_step(tmp_path / "b.step", 2, Lx=200.0, Lz=150.0))):
        _m, meta = mg.mesh_file(p, 3.0, _ccfg(), PROPS)
        df = meta["defeature"]
        assert "mesh_fallback" not in meta and "not_hole" not in df and "relaxed" not in df
        assert (df["filled"], df["hole_sized"]) == {"h": (1, 0), "H": (0, 1), "b": (0, 0)}[name]
