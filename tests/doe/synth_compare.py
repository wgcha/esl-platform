"""④ 형상 직접 비교 시험용 합성 STEP(gmsh OCC, 시험 중 생성): XZ 평면 판(x 0..Lx, z 0..Lz, y = 0) + x 방향 직선 비드 k 개.

비드 = (z, y) 단면 사다리꼴(깊이 depth, 아래 폭 w0, 위 폭 w1)을 x 방향으로 Lx 만큼 밀어낸 면. 비드가 x 방향 굽힘(bend 하중 — ξ = x)을
막아 비드가 많을수록 컴플라이언스가 작다(순위 단조). gmsh 가 쓴 STEP 은 면 공유 정보가 없으므로 설정 mesh.occ_sew_faces 1 로 읽는다.
"""
from __future__ import annotations

import os


def bead_profile(Lz: float, n_beads: int, depth: float, w0: float = 30.0, w1: float = 14.0) -> list[tuple[float, float]]:
    pts = [(0.0, 0.0)]
    for k in range(n_beads):
        zc = Lz * (k + 1) / (n_beads + 1)
        pts += [(zc - w0 / 2, 0.0), (zc - w1 / 2, depth), (zc + w1 / 2, depth), (zc + w0 / 2, 0.0)]
    pts.append((Lz, 0.0))
    return pts


def plate_step(path, n_beads: int = 0, *, Lx: float = 400.0, Lz: float = 300.0, depth: float = 6.0,
               shift=(0.0, 0.0, 0.0), rot_deg: float = 0.0, hole: tuple | None = None) -> str:
    """판(+비드) STEP. shift = 평행 이동(mm), rot_deg = x 축 둘레 회전(법선 기울기), hole = (x, z, 지름) 작은 구멍."""
    import math

    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        if n_beads == 0 and hole is None:
            s = occ.addRectangle(0.0, 0.0, 0.0, Lx, Lz)
            occ.rotate([(2, s)], 0, 0, 0, 1, 0, 0, math.pi / 2)        # XY → XZ(y = 0, z = 0..Lz)
            dims = [(2, s)]
        elif n_beads == 0:
            s = occ.addRectangle(0.0, 0.0, 0.0, Lx, Lz)
            d = occ.addDisk(hole[0], hole[1], 0.0, hole[2] / 2, hole[2] / 2)
            out, _ = occ.cut([(2, s)], [(2, d)])
            occ.rotate(out, 0, 0, 0, 1, 0, 0, math.pi / 2)
            dims = out
        else:
            prof = bead_profile(Lz, n_beads, depth)
            p = [occ.addPoint(0.0, y, z) for z, y in prof]
            ln = [occ.addLine(p[i], p[i + 1]) for i in range(len(p) - 1)]
            ext = occ.extrude([(1, t) for t in ln], Lx, 0.0, 0.0)
            dims = [e for e in ext if e[0] == 2]
        if rot_deg:
            occ.rotate(dims, 0, 0, 0, 1, 0, 0, math.radians(rot_deg))
        if any(shift):
            occ.translate(dims, *shift)
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)
