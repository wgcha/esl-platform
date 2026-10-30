"""VERIFY_POST 단위(계약 esl_scx_relay.md §9.3·SR-D-16, v0.12.0 L4): 실행기 없이 가짜 ex 로 —
coord_check.max_rel 확장(기본 + 2 × 모핑 최대 이동 / 대상 파트 bbox 대각), 추출 입력 폴더 고정(_verify/<id>/h3dwork/raw 외 PATH_UNSAFE),
t* 프레임 → 시각, compare.json 없으면 등록 거부(PREREQUISITE_MISSING), 알 수 없는 step, 검증 폴더 안 링크 거부."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

from esl_worker import verify_post as vp
from esl_worker.executor import _StepFailed


def _ex(tmp_path, *, max_disp=0.0, base_rel=None, h3d_out=None, tstar=None):
    root = tmp_path / "esl_root"
    case_dir = root / "vd_case"
    (case_dir / "01_extract").mkdir(parents=True)
    xs = np.array([[0, 0, 0], [30.0, 40.0, 0.0]])                     # bbox 대각 50
    np.savez(case_dir / "01_extract" / "model.npz", node_id=np.array([1, 2]), x0=xs)
    cdir = root / "_verify" / "vd-1"
    cdir.mkdir(parents=True)
    (cdir / "stage.json").write_text(json.dumps({"morph": {"max_disp": max_disp}}), encoding="utf-8")
    settings = {} if base_rel is None else {"coord_check": {"max_rel": base_rel}}
    params = {"settings": settings, "h3d": {"out_dir": h3d_out} if h3d_out else {}}
    return SimpleNamespace(cdir=str(cdir), job={"params": params, "verify_drop_id": "vd-1", "id": "j-1"},
                           settings=SimpleNamespace(storage=SimpleNamespace(esl_root=str(root), input_roots=[], spdm_roots=[],
                                                                        upload_root=None)),
                           case={"folder_name": "vd_case", "rad_path": "/in/model_0000.rad", "tstar": tstar or {}})


def test_coord_rel_widened_by_morph(tmp_path):
    assert vp._coord_rel(_ex(tmp_path / "a")) == pytest.approx(0.005)                      # 모핑 0 → 기본값
    assert vp._coord_rel(_ex(tmp_path / "b", max_disp=1.0)) == pytest.approx(0.005 + 2 * 1.0 / 50)
    assert vp._coord_rel(_ex(tmp_path / "c", max_disp=2.5, base_rel=0.01)) == pytest.approx(0.01 + 2 * 2.5 / 50)


def test_extract_input_dir_fixed(tmp_path):
    ex = _ex(tmp_path, h3d_out=str(tmp_path / "elsewhere"))
    with pytest.raises(_StepFailed) as ei:
        vp._extract(ex, {"step_key": "VD_EXTRACT"}, str(tmp_path / "log.txt"))
    assert ei.value.code == "PATH_UNSAFE"
    ex2 = _ex(tmp_path / "n")                                                       # params.h3d 없음
    with pytest.raises(_StepFailed):
        vp._extract(ex2, {"step_key": "VD_EXTRACT"}, str(tmp_path / "log2.txt"))


def test_tstar_time_from_frames(tmp_path):
    ex = _ex(tmp_path, tstar={"frame_index": 7})
    assert vp._tstar_time(ex) is None                                               # strain_frames.npz 없음
    np.savez(os.path.join(vp._case_dir(ex), "01_extract", "strain_frames.npz"), frame_index=np.array([3, 7, 9]),
             time=np.array([0.001, 0.0124, 0.02]))
    assert vp._tstar_time(ex) == pytest.approx(0.0124)
    assert vp._tstar_time(_ex(tmp_path / "x")) is None                              # t* 미확정
    ex.case["tstar"] = {"frame_index": 99}
    assert vp._tstar_time(ex) is None                                               # 그 프레임 없음


def test_register_requires_compare_json_and_unknown_step(tmp_path):
    ex = _ex(tmp_path)
    with pytest.raises(_StepFailed) as ei:
        vp._register(ex, str(tmp_path / "log.txt"))
    assert ei.value.code == "PREREQUISITE_MISSING"
    (tmp_path / "esl_root" / "_verify" / "vd-1" / "compare.json").write_text('{"rows": "x"}', encoding="utf-8")
    with pytest.raises(_StepFailed):
        vp._register(ex, str(tmp_path / "log.txt"))                                 # rows 가 목록이 아님
    with pytest.raises(_StepFailed) as ei:
        vp.run_step(ex, {"step_key": "NOPE"}, str(tmp_path / "log.txt"))
    assert ei.value.code == "INTERNAL_ERROR"


@pytest.mark.skipif(os.name == "nt", reason="심볼릭 링크")
def test_h3d_work_rejects_link(tmp_path):
    ex = _ex(tmp_path)
    assert vp.h3d_work(ex).endswith("h3dwork") and os.path.isdir(vp.h3d_work(ex))
    ex2 = _ex(tmp_path / "l")
    os.symlink(tmp_path, os.path.join(ex2.cdir, "h3dwork"))
    with pytest.raises(_StepFailed) as ei:
        vp.h3d_work(ex2)
    assert ei.value.code == "PATH_UNSAFE"
