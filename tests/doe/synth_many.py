"""v0.16.3 ④ 실제 Ch/R 재현용 합성 STEP(이슈 #53 2026-11-09 — 면 2824+ 개, 작은 periodic Sphere 딤플에서 'Impossible to mesh
periodic surface'): XY 판(z = 0)을 panels 칸으로 나눈 면 + nx × ny 격자 구면 딤플(원호를 z 축으로 회전한 OCC Sphere 면 — 극점이
면 안, seam 있음) + holes_every 번째 자리마다 Ø4 관통 구멍. gmsh OCC 로 시험 중 생성(면 공유 없음 → mesh.occ_sew_faces 1).
기본(20 × 12, 6 × 4 칸)은 약 230 면, ``many_dimple_step(nx=50, ny=40, Lx=1000, Ly=600, panels=(20, 10))`` 는 약 1900 면."""
from __future__ import annotations

import math
import os


def many_dimple_step(path, *, nx: int = 20, ny: int = 12, Lx: float = 400.0, Ly: float = 240.0, a: float = 5.0,
                     d: float = 2.0, panels: tuple[int, int] = (6, 4), holes_every: int = 7) -> str:
    """딤플 테두리 반지름 a·깊이 d(구 R = (a² + d²)/2d). 반환 경로."""
    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        R = (a * a + d * d) / (2 * d)
        px, py = panels
        tiles = [(2, occ.addRectangle(i * Lx / px, j * Ly / py, 0.0, Lx / px, Ly / py)) for i in range(px) for j in range(py)]
        caps, cuts = [], []
        k = 0
        for i in range(nx):
            for j in range(ny):
                x, y = (i + 0.5) * Lx / nx, (j + 0.5) * Ly / ny
                k += 1
                if holes_every and k % holes_every == 0:
                    cuts.append((2, occ.addDisk(x, y, 0.0, 2.0, 2.0)))
                    continue
                arc = occ.addCircleArc(occ.addPoint(x + a, y, 0.0), occ.addPoint(x, y, R - d), occ.addPoint(x, y, -d))
                caps += [e for e in occ.revolve([(1, arc)], x, y, 0.0, 0.0, 0.0, 1.0, 2 * math.pi) if e[0] == 2]
                cuts.append((2, occ.addDisk(x, y, 0.0, a, a)))
        top, _ = occ.cut(tiles, cuts)
        occ.fragment(top + caps, [])
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


def many_dimple_solid_step(path, *, nx: int = 6, ny: int = 4, Lx: float = 200.0, Ly: float = 150.0, R: float = 8.0,
                           d: float = 2.0, t: float = 2.0) -> str:
    """v0.17.4 면을 공유하는 다딤플 판(두께 t 고체 − nx × ny 구 → 윗면 구면 딤플 = OCC Sphere 면, 극점이 면 안). 실제 gmsh 에서
    OCC 정리(occ_fix_small 1)를 켜면 딤플 면 1D 고리가 깨져 2D 가 실패하고, 끄면(③ 옵션) 연결된 한 덩어리로 메시된다(재현 —
    synth_compare.dimple_plate_step(solid) 격자판)."""
    from synth_compare import dimple_plate_step
    dd = [((i + 0.5) * Lx / nx, (j + 0.5) * Ly / ny, R, d) for i in range(nx) for j in range(ny)]
    return dimple_plate_step(path, dd, Lx=Lx, Lz=Ly, solid=t)
