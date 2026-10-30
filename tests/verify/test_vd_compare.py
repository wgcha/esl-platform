"""V-SR-11 코어 비교(계약 esl_scx_relay.md §9.3): 합성 추출 두 벌(알려진 비) → 행 값·판단·일치·t* 최근접, 위상 불일치,
결정성, CSV, vd_compare 단계(모핑 좌표 덮어쓰기)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from esl.errors import EslError
from esl.verify import compare, compare_csv


def _plate(n=4):
    xs = np.array([[x, y, 0.0] for y in range(n) for x in range(n)], float) * 10.0
    nid = np.arange(1, n * n + 1, dtype=np.int64) * 2
    conn = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            conn.append([nid[a], nid[a + 1], nid[a + n + 1], nid[a + n]])
    return nid, xs, np.array(conn, dtype=np.int64)


def write_extract(d, *, eps_scale=1.0, u_scale=1.0, shift=(0.0, 0.0, 0.0), times=(0.001, 0.002, 0.003),
                  elem_ids=None, conn=None, factor=1.0):
    d.mkdir(parents=True, exist_ok=True)
    nid, xs, cn = _plate()
    E = cn.shape[0]
    eid = np.asarray(elem_ids if elem_ids is not None else 100 + np.arange(E), dtype=np.int64)
    np.savez(d / "model.npz", node_id=nid, x0=xs, elem_id=eid, conn=conn if conn is not None else cn,
             elem_type=np.full(E, 4, np.int8))
    T = np.asarray(times, float)
    base = np.stack([np.linspace(0.001, 0.009, E) * (k + 1) for k in range(T.size)])          # (D,E) 증가
    eps = np.zeros((T.size, E, 3))
    eps[..., 0] = base * eps_scale
    np.savez(d / "strain_frames.npz", frame_index=np.arange(T.size), time=T, elem_id=eid, eps=eps,
             vm_hv=base, epsp=np.zeros_like(base))
    c = xs.mean(axis=0)
    w = ((xs[:, 0] - c[0]) ** 2 + (xs[:, 1] - c[1]) ** 2)
    w = (w - w.mean()) * 1e-3
    u = np.zeros((T.size, nid.size, 3))
    for k in range(T.size):
        u[k, :, 2] = w * (k + 1) * u_scale
        u[k] += np.asarray(shift)
    np.savez(d / "disp.npz", frame_index=np.arange(T.size), time=T, node_id=nid, u=u)
    (d / "frames.json").write_text(json.dumps({"shear": {"factor": factor}}))
    return d


def test_known_ratios_verdicts_agree_tstar(tmp_path):
    o = write_extract(tmp_path / "o" / "01_extract")
    v = write_extract(tmp_path / "v" / "01_extract", eps_scale=0.8, u_scale=1.1, shift=(5.0, -2.0, 1.0),
                      times=(0.0011, 0.0021, 0.0029))
    r = compare(str(tmp_path / "o"), str(tmp_path / "v"), tstar_time=0.002, predicted={"r_epsmax": 0.7, "r_umax": 0.9},
                same_tol=0.02, hot_n=3)
    by = {x["key"]: x for x in r["rows"]}
    assert list(by) == ["eps_peak", "eps_hot", "disp_peak", "eps_tstar", "disp_tstar"]
    for k in ("eps_peak", "eps_hot", "eps_tstar"):
        assert by[k]["ratio"] == pytest.approx(0.8, rel=1e-9) and by[k]["verdict"] == "better"
        assert by[k]["predicted"] == 0.7 and by[k]["agree"] is True
    for k in ("disp_peak", "disp_tstar"):
        assert by[k]["ratio"] == pytest.approx(1.1, rel=1e-6) and by[k]["verdict"] == "worse"
        assert by[k]["predicted"] == 0.9 and by[k]["agree"] is False
    assert by["eps_peak"]["orig_elem_id"] == by["eps_peak"]["verify_elem_id"] == 108
    assert by["eps_peak"]["orig_time"] == 0.003 and by["eps_peak"]["verify_time"] == 0.0029
    assert r["hot"]["n"] == 3 and r["hot"]["elem_ids"] == [108, 107, 106]
    assert r["hot"]["max_ratio"] == pytest.approx(0.8)
    assert r["tstar"] == {"orig_time": 0.002, "verify_time": 0.0021}
    assert by["eps_tstar"]["orig"] == pytest.approx(0.009 * 2 * 0.5773502691896258 * 2, rel=1e-6) or by["eps_tstar"]["orig"] > 0
    # 결정성 + CSV
    r2 = compare(str(tmp_path / "o"), str(tmp_path / "v"), tstar_time=0.002, predicted={"r_epsmax": 0.7, "r_umax": 0.9},
                 same_tol=0.02, hot_n=3)
    assert json.dumps(r, sort_keys=True) == json.dumps(r2, sort_keys=True)
    csv = compare_csv(r).splitlines()
    assert csv[0] == "key,label,orig,verify,ratio,predicted,verdict,agree" and len(csv) == 6
    assert csv[1].startswith("eps_peak,") and csv[1].endswith(",0.7,better,true")


def test_same_and_no_prediction_and_no_tstar(tmp_path):
    o = write_extract(tmp_path / "o")
    write_extract(tmp_path / "v", eps_scale=1.01, u_scale=0.995)
    r = compare(str(o), str(tmp_path / "v"), tstar_time=None, predicted=None)
    by = {x["key"]: x for x in r["rows"]}
    assert set(by) == {"eps_peak", "eps_hot", "disp_peak"}
    assert all(x["verdict"] == "same" and x["agree"] is None and x["predicted"] is None for x in by.values())
    assert any("t*" in w for w in r["warnings"]) and r["tstar"] == {"orig_time": None, "verify_time": None}
    # 둘 다 비슷 → 일치
    r = compare(str(o), str(tmp_path / "v"), predicted={"r_epsmax": 1.005, "r_umax": 1.0})
    assert all(x["agree"] is True for x in r["rows"])


def test_topology_mismatch(tmp_path):
    o = write_extract(tmp_path / "o")
    write_extract(tmp_path / "v", elem_ids=200 + np.arange(9))
    with pytest.raises(EslError) as ei:
        compare(str(o), str(tmp_path / "v"))
    assert ei.value.code == "VD_TOPOLOGY_MISMATCH"
    nid, _, cn = _plate()
    cn2 = cn.copy()
    cn2[0] = cn2[0][::-1]
    write_extract(tmp_path / "w", conn=cn2)
    with pytest.raises(EslError) as ei:
        compare(str(o), str(tmp_path / "w"))
    assert ei.value.code == "VD_TOPOLOGY_MISMATCH"


def test_vd_compare_stage_uses_morph_coords(tmp_path):
    from esl.verify import stages

    write_extract(tmp_path / "o" / "01_extract")
    write_extract(tmp_path / "v" / "01_extract", u_scale=1.0)
    nid, xs, _ = _plate()
    np.savez(tmp_path / "morph.npz", node_id=nid[:1], x=xs[:1] + np.array([-15.0, -15.0, 40.0]))
    res = stages.vd_compare({"orig_out": str(tmp_path / "o"), "verify_out": str(tmp_path / "v"), "tstar_time": 0.003,
                             "predicted": {"r_umax": 0.95, "r_epsmax": 0.95}, "same_tol": 0.02, "hot_n": 5,
                             "morph_npz": str(tmp_path / "morph.npz"), "out_json": str(tmp_path / "compare.json"),
                             "out_csv": str(tmp_path / "compare.csv")}, echo=lambda *_: None)
    assert json.loads((tmp_path / "compare.json").read_text())["rows"] == res["rows"]
    assert (tmp_path / "compare.csv").read_text().count("\n") == 6
    by = {x["key"]: x for x in res["rows"]}
    assert by["eps_peak"]["ratio"] == pytest.approx(1.0)
    assert by["disp_peak"]["ratio"] != pytest.approx(1.0, abs=1e-6)          # 검증 쪽 기준 좌표가 모핑 좌표로 바뀜
