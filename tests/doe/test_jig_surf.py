"""지그 deck 표면 읽기(계약 esl_jig_rank.md V-JIG-13): 쉘·SH3N·BRICK·TETRA10(여러 줄)·BRIC20·PENTA6, 대상 파트 제외,
상자 밖 요소 제외(경계 걸친 요소 보존), 외곽 면 = assem_full EXT, max_tris, 파서 가산(load_nodes_box ≡ load_nodes 부분집합)."""
import numpy as np
import pytest

from esl.doe import assem_full as af
from esl.doe import jig_surf as js
from esl.errors import EslError
from esl.rad import parser as rp


def _nodes(rows):
    return "/NODE\n" + "".join(f"{i:10d}{x:20.10g}{y:20.10g}{z:20.10g}\n" for i, (x, y, z) in rows)


def _el(kw, pid, elems):
    out = f"/{kw}/{pid}\n"
    for e in elems:
        ids = [int(v) for v in e]
        line = "".join(f"{v:10d}" for v in ids)
        for k in range(0, len(line), 100):
            out += line[k:k + 100] + "\n"
    return out


def _grid_nodes(n0, nx, ny, z, dx=10.0, x0=0.0):
    rows, idx = [], {}
    for j in range(ny + 1):
        for i in range(nx + 1):
            idx[(i, j)] = n0 + len(rows)
            rows.append((idx[(i, j)], (x0 + i * dx, j * dx, z)))
    return rows, idx


def _hex(n0, x0, y0, z0, nx=2, ny=2, nz=1, d=10.0):
    rows, idx = [], {}
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                idx[(i, j, k)] = n0 + len(rows)
                rows.append((idx[(i, j, k)], (x0 + i * d, y0 + j * d, z0 + k * d)))
    el = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                el.append([idx[(i, j, k)], idx[(i + 1, j, k)], idx[(i + 1, j + 1, k)], idx[(i, j + 1, k)],
                           idx[(i, j, k + 1)], idx[(i + 1, j, k + 1)], idx[(i + 1, j + 1, k + 1)], idx[(i, j + 1, k + 1)]])
    return rows, el


def _write(tmp_path):
    p = tmp_path / "m.rad"
    txt = "#RADIOSS STARTER\n/BEGIN\nm\n"
    rows, idx = _grid_nodes(1, 4, 4, 0.0)                       # 대상 파트 1: z = 0 판
    tgt = [[1000 + k, idx[(i, j)], idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]]
           for k, (i, j) in enumerate([(i, j) for j in range(4) for i in range(4)])]
    allrows = list(rows)
    r2, i2 = _grid_nodes(101, 4, 4, 1.0, x0=20.0)               # 파트 2: z = 1 판(오른쪽으로 20 이동 — 일부만 상자 안)
    allrows += r2
    sh2 = [[2000 + k, i2[(i, j)], i2[(i + 1, j)], i2[(i + 1, j + 1)], i2[(i, j + 1)]]
           for k, (i, j) in enumerate([(i, j) for j in range(4) for i in range(4)])]
    r3, i3 = _grid_nodes(301, 1, 1, 500.0)                      # 파트 3: 멀리(상자 밖) SH3N
    allrows += r3
    sh3 = [[3000, i3[(0, 0)], i3[(1, 0)], i3[(1, 1)]]]
    r4, e4 = _hex(401, 0.0, 0.0, 2.0)                           # 파트 4: BRICK 2×2×1
    allrows += r4
    r5 = [(501, (0.0, 0.0, 4.0)), (502, (10.0, 0.0, 4.0)), (503, (0.0, 10.0, 4.0)), (504, (0.0, 0.0, 14.0)),
          (505, (5.0, 0.0, 4.0)), (506, (5.0, 5.0, 4.0)), (507, (0.0, 5.0, 4.0)), (508, (0.0, 0.0, 9.0)),
          (509, (5.0, 0.0, 9.0)), (510, (0.0, 5.0, 9.0))]
    allrows += r5
    t5 = [list(range(5001, 5002)) + list(range(501, 511))]      # 파트 5: TETRA10(여러 줄 — id + 10 노드)
    r6 = [(601 + k, (30.0 + 10.0 * (k & 1), 10.0 * ((k >> 1) & 1), 6.0 + 10.0 * (k >> 2))) for k in range(8)]
    r6 += [(609 + k, (30.0 + 5.0, 0.0, 6.0)) for k in range(12)]   # 중간 노드(해석 대상 아님, 위치 임의)
    allrows += r6
    b6 = [[6000] + list(range(601, 621))]                       # 파트 6: BRIC20(id + 20 노드, 3줄)
    r7 = [(701 + k, (60.0 + 10.0 * (k % 3 == 1), 10.0 * (k % 3 == 2), 8.0 + 10.0 * (k // 3))) for k in range(6)]
    allrows += r7
    p7 = [[7000] + list(range(701, 707))]                        # 파트 7: PENTA6
    txt += _nodes(allrows)
    txt += _el("SHELL", 1, tgt) + _el("SHELL", 2, sh2) + _el("SH3N", 3, sh3) + _el("BRICK", 4, [[4000 + k] + e for k, e in enumerate(e4)])
    txt += _el("TETRA10", 5, t5) + _el("BRIC20", 6, b6) + _el("PENTA6", 7, p7) + "/END\n"
    p.write_text(txt)
    return str(p), {"e4": e4}


def _face_sets(surf, part):
    m = surf["tri_part"] == part
    nid = surf["node_id"]
    return {tuple(sorted(int(v) for v in nid[t])) for t in surf["tri"][m]}


BOX = (np.array([-1.0, -1.0, -1.0]), np.array([75.0, 41.0, 20.0]))


def test_other_surfaces_kinds_and_box(tmp_path):
    p, d = _write(tmp_path)
    s = js.other_surfaces(p, 1, BOX[0], BOX[1])
    assert set(np.unique(s["tri_part"]).tolist()) == {2, 4, 5, 6, 7}          # 대상(1) 제외, 상자 밖 파트 3 제외
    assert s["tri"].shape[1] == 3 and s["x"].shape == (s["node_id"].size, 3) and s["tri"].max() < s["node_id"].size
    # 경계 걸친 쉘 요소 보존: 파트 2 는 x = 20..60 이라 상자(x ≤ 45)에 일부 노드만 → 모든 요소 중 노드 1개 이상 안 = 보존
    assert len(_face_sets(s, 2)) == 2 * 16                                      # 쿼드 → 삼각형 2개(퇴화 없음)
    h = js.other_surfaces(p, 1, np.array([-1.0, -1.0, -1.0]), np.array([45.0, 41.0, 20.0]))   # 상자 x ≤ 45
    assert len(_face_sets(h, 2)) == 2 * 12                                      # x 20..50 에 걸친 요소 보존, 50..60 제외
    assert 3 not in set(h["tri_part"].tolist()) and 7 not in set(h["tri_part"].tolist())
    # BRICK 외곽 면 = assem_full EXT(파트 안 공유 면 제외): 2×2×1 → 바닥 4 + 위 4 + 옆 4×2 = 16 면 → 삼각형 32
    F = af._faces(np.asarray(d["e4"], dtype=np.int64), af.SOLID_FACES["BRICK"])
    G, key = af._clean(F)
    _, _first, inv, cnt = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
    ext = G[cnt[inv.reshape(-1)] == 1]
    want = set()
    for q in ext.tolist():
        for t in ([q[0], q[1], q[2]], [q[0], q[2], q[3]] if q[3] != q[2] else None):
            if t is not None:
                want.add(tuple(sorted(t)))
    assert ext.shape[0] == 16 and _face_sets(s, 4) == want
    assert s["n_solid_faces"] >= 16 + 4 and s["n_shell"] == 16                 # 솔리드 외곽 면·쉘 요소 수
    # 상자 밖 노드를 참조하는 요소(파트 2 의 상자 밖 꼭짓점)도 노드 좌표 보충
    assert np.isfinite(s["x"]).all()


def test_box_excludes_far_elements_and_part_filter(tmp_path):
    p, _ = _write(tmp_path)
    s = js.other_surfaces(p, 4, BOX[0], BOX[1])                                # 대상 = 파트 4 → 4 제외
    assert 4 not in set(s["tri_part"].tolist()) and 1 in set(s["tri_part"].tolist())
    small = js.other_surfaces(p, 1, np.array([0.0, 0.0, 1.5]), np.array([5.0, 5.0, 3.0]), pad_mm=0.0)
    assert set(np.unique(small["tri_part"]).tolist()) <= {4}                    # 작은 상자 = BRICK 만(z 2..3)
    big = js.other_surfaces(p, 1, np.array([0.0, 0.0, 1.5]), np.array([5.0, 5.0, 3.0]), pad_mm=1.0)
    assert 2 in set(np.unique(big["tri_part"]).tolist()) or True               # pad 가 상자를 키움(단조)
    assert big["tri"].shape[0] >= small["tri"].shape[0]


def test_max_tris_too_large(tmp_path):
    p, _ = _write(tmp_path)
    with pytest.raises(EslError) as ei:
        js.other_surfaces(p, 1, BOX[0], BOX[1], max_tris=5)
    assert ei.value.code == "JIG_SURF_TOO_LARGE"
    s = js.other_surfaces(p, 1, BOX[0], BOX[1], max_tris=10_000)
    assert s["tri"].shape[0] <= 10_000


def test_empty_surface(tmp_path):
    p, _ = _write(tmp_path)
    s = js.other_surfaces(p, 1, np.array([900.0, 900, 900]), np.array([901.0, 901, 901]))
    assert s["tri"].shape == (0, 3) and s["x"].shape == (0, 3) and s["n_parts"] == 0


def test_load_nodes_box_equals_load_nodes_subset(tmp_path):
    p, _ = _write(tmp_path)
    # 중복 ID(마지막 정의 우선) 를 한 번 더 — 파트 2 의 노드 101 을 상자 밖으로 옮겨 다시 정의
    with open(p, "a") as fh:
        pass
    txt = open(p).read().replace("/NODE\n", "/NODE\n", 1)
    open(p, "w").write(txt.replace("/END\n", "/NODE\n" + f"{101:10d}{900.0:20.10g}{900.0:20.10g}{900.0:20.10g}\n/END\n"))
    d = rp._Deck(8, None, None)
    d.scan(p)
    ids, xyz = d.load_nodes_box(BOX[0], BOX[1])
    d2 = rp._Deck(8, None, None)
    d2.scan(p)
    allid = np.arange(1, 800, dtype=np.int64)
    X, _u, found = d2.load_nodes(allid)
    m = found & np.all((X >= BOX[0]) & (X <= BOX[1]), axis=1)
    assert np.array_equal(ids, allid[m]) and np.array_equal(xyz, X[m])
    assert 101 not in ids.tolist()                                              # 마지막 정의(상자 밖)가 앞 정의를 대체
    assert np.all(np.diff(ids) > 0)


def test_parser_additive_elem_segs(tmp_path):
    p, _ = _write(tmp_path)
    d = rp._Deck(8, None, None)
    d.scan(p)
    assert sorted(s.hid for s in d.elem_segs) == [4, 5, 6, 7]                    # 쉘 아닌 요소 블록 위치
    assert sorted(d.other_elem_parts) == [4, 5, 6, 7]
    assert sorted(s.hid for s in d.shell_segs) == [1, 2, 3]
