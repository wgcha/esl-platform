"""V-0240-F-b(deck): 공유 노드·회전 연결 노드 진단 esl.rad.shared.node_links (esl_fint.md §2)."""
from __future__ import annotations

import numpy as np

from esl.rad.shared import node_links, safe_node_links
from tests.rad import synth_mesh_rad as sr


def _deck(tmp_path):
    # 대상 파트 1: 4×2 격자(노드 1..15), 다른 파트 2: x = 4..6 격자 — x = 4 열 노드(13,14,15)를 공유
    ids1, X1, e1, c1 = sr.grid(4, 2, 10.0, 10.0, nid0=1, eid0=1)
    ids2, X2, e2, c2 = sr.grid(2, 2, 10.0, 10.0, x0=40.0, nid0=101, eid0=101)
    shared = {101: 13, 102: 14, 103: 15}                      # 파트 2 의 x = 40 열을 파트 1 노드로 바꿈
    c2 = np.vectorize(lambda n: shared.get(int(n), int(n)))(c2)
    keep = ~np.isin(ids2, list(shared))
    lines = sr.begin() + sr.part(1, "chassis_rear") + sr.part(2, "plate_led") + sr.nodes(ids1, X1) \
        + sr.nodes(ids2[keep], X2[keep]) + sr.nodes([900], [(0.0, 0.0, 50.0)]) + sr.shells(1, e1, c1) + sr.shells(2, e2, c2)
    lines += ["/SPRING/3", f"{501:10d}{1:10d}{900:10d}"]          # 노드 1 ↔ 자유 노드 900 스프링(회전 연결)
    lines += ["/RBODY/7", "rb", f"{900:10d}{0:10d}{0:10d}{0:10d}{0.0:20.4f}{55:10d}",
              "/GRNOD/NODE/55", "grp", f"{5:10d}{6:10d}{999:10d}"]
    lines += ["/RBODY/8", "rb2", f"{900:10d}{0:10d}{0:10d}{0:10d}{0.0:20.4f}{56:10d}", "/GRNOD/PART/56", "gp", f"{1:10d}"]
    lines += ["/END"]
    return sr.write(tmp_path / "m.rad", lines), ids1, X1


def test_node_links_shared_and_rot(tmp_path):
    p, ids1, X1 = _deck(tmp_path)
    r = node_links(p, 1, ids1)
    assert r["status"] == "ok"
    assert r["n_shared"] == 4                                 # 13·14·15(파트 2 쉘) + 1(스프링)
    assert r["by_part"] == {"2": 3, "3": 1}
    assert r["by_kw"] == {"SHELL": 3, "SPRING": 1}
    assert r["rot"]["spring"] == 1 and r["rot"]["rbody_secondary"] == 2 and r["rot"]["rbody_main"] == 0
    assert r["n_rot"] == 3 and r["rot_node_ids"] == [1, 5, 6]
    assert r["rbody_unresolved"] == 1                         # /GRNOD/PART 는 해석 안 함(수만)
    s = safe_node_links(p, 1, ids1, X1)
    assert s["bbox"]["lo"][0] == 0.0 and s["bbox"]["hi"][0] == 40.0 and "_all" not in s


def test_node_links_failed_is_status(tmp_path):
    s = safe_node_links(tmp_path / "none.rad", 1, [1, 2])
    assert s["status"] == "failed" and s["reason"]
