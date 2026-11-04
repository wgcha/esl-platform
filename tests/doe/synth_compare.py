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


def boss_plate_step(path, bosses, *, Lx: float = 300.0, Lz: float = 160.0, holes=()) -> str:
    """v0.14.1 periodic 면 재현용: XY 판(z = 0) + 회전체 보스(원통·원뿔 = gmsh periodic 면, seam 있음).

    bosses = [(r1, r2, d, r3, side_r)]: 판 구멍 r1 → 벽(r2 < r1 원뿔, 같으면 원통) 깊이 d → r3 > 0 이면 바닥 고리 평면(가운데 구멍
    반지름 r3, 나사 자리), 0 이면 벽 끝이 열린 버링/관. side_r > 0 이면 벽 옆에 반지름 side_r 구멍(seam 반대편 90°).
    holes = [(x, y, r)] 판의 진짜 구멍. 면은 fragment 로 모서리를 공유(봉합된 쉘)."""
    import math

    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        plate = occ.addRectangle(0.0, 0.0, 0.0, Lx, Lz)
        faces, cuts = [], []
        for i, (r1, r2, d, r3, side_r) in enumerate(bosses):
            x, y = 40.0 + 60.0 * i, Lz / 2
            p0, p1 = occ.addPoint(x + r1, y, 0.0), occ.addPoint(x + r2, y, -d)
            cs = [occ.addLine(p0, p1)]
            if r3 > 0:
                cs.append(occ.addLine(p1, occ.addPoint(x + r3, y, -d)))
            fs = [e for e in occ.revolve([(1, c) for c in cs], x, y, 0.0, 0.0, 0.0, 1.0, 2 * math.pi) if e[0] == 2]
            if side_r > 0:
                tool = occ.addCylinder(x, y, -d / 2, 0.0, r1 + 5.0, 0.0, side_r)
                fs, _ = occ.cut(fs, [(3, tool)])
            faces += fs
            cuts.append((2, occ.addDisk(x, y, 0.0, r1, r1)))
        cuts += [(2, occ.addDisk(hx, hy, 0.0, hr, hr)) for hx, hy, hr in holes]
        top, _ = occ.cut([(2, plate)], cuts)
        occ.synchronize()
        occ.fragment(top + faces, [])
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


def dimple_plate_step(path, dimples, *, Lx: float = 200.0, Lz: float = 150.0) -> str:
    """v0.15.1 Sphere 면 재현용(이슈 #53 'Impossible to mesh periodic surface' — 중립면 STEP 의 구면 딤플·필렛 코너 패치):
    XY 판(z = 0) + 구면 딤플(원호를 z 축으로 회전 = OCC Sphere 면, u periodic·seam 있음, 극점 = 딤플 바닥이 면 안).

    dimples = [(x, y, R, d)]: 구 반지름 R, 깊이 d(< R). OCC 정리(Geometry.OCCFix*·OCCSewFaces)가 극점의 퇴화 모서리를
    지워 gmsh 2D 가 그 면에서 실패한다(알고리즘 무관). 면은 fragment 로 모서리를 공유."""
    import math

    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        plate = occ.addRectangle(0.0, 0.0, 0.0, Lx, Lz)
        faces, cuts = [], []
        for x, y, R, d in dimples:
            a = math.sqrt(R * R - (R - d) ** 2)
            arc = occ.addCircleArc(occ.addPoint(x + a, y, 0.0), occ.addPoint(x, y, R - d), occ.addPoint(x, y, -d))
            faces += [e for e in occ.revolve([(1, arc)], x, y, 0.0, 0.0, 0.0, 1.0, 2 * math.pi) if e[0] == 2]
            cuts.append((2, occ.addDisk(x, y, 0.0, a, a)))
        top = occ.cut([(2, plate)], cuts)[0] if cuts else [(2, plate)]
        if faces:
            occ.fragment(top + faces, [])
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)
