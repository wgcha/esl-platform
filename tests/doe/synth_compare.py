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


def dimple_plate_step(path, dimples, *, Lx: float = 200.0, Lz: float = 150.0, solid: float = 0.0) -> str:
    """v0.15.1 Sphere 면 재현용(이슈 #53 'Impossible to mesh periodic surface' — 중립면 STEP 의 구면 딤플·필렛 코너 패치):
    XY 판(z = 0) + 구면 딤플(원호를 z 축으로 회전 = OCC Sphere 면, u periodic·seam 있음, 극점 = 딤플 바닥이 면 안).

    dimples = [(x, y, R, d)]: 구 반지름 R, 깊이 d(< R). OCC 정리(Geometry.OCCFix*·OCCSewFaces)가 극점의 퇴화 모서리를
    지워 gmsh 2D 가 그 면에서 실패한다(알고리즘 무관). 면은 fragment 로 모서리를 공유.
    solid > 0 이면 두께 solid 판 고체에서 구를 뺀 고체 STEP(면 공유가 STEP 안에 있어 OCCSewFaces 0 으로도 붙음)."""
    import math

    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        if solid:
            v = [(3, occ.addBox(0.0, 0.0, -solid, Lx, Lz, solid))]
            v, _ = occ.cut(v, [(3, occ.addSphere(x, y, R - d, R)) for x, y, R, d in dimples])
            occ.synchronize()
            os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
            gmsh.write(str(path))
            return str(path)
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



BEAD_FEATURES = {"plate": (300.0, 200.0), "bead": (60.0, 50.0, 180.0, 100.0, 20.0), "bead_fillet": 3.0,
                 "dimples": [(100.0, 100.0, 15.0, 2.0), (150.0, 100.0, 10.0, 5.0), (200.0, 100.0, 8.0, 8.0)],   # (x, y, R, 깊이)
                 "dimple_fillet": 1.5, "holes": [(90.0, 70.0, 2.5), (210.0, 70.0, 5.0)],                        # Ø5·Ø10 관통
                 "burr": (150.0, 132.0, 4.0, 8.0)}                                                             # (x, y, r, 길이)


def fillet_corner_step(path, r: float = 5.0) -> str:
    """v0.15.1 세 필렛이 만나는 코너 구면 패치(OCC fillet 코너 = Sphere 면): 상자 100×80×20 의 한 꼭짓점 세 모서리 필렛 뒤 윗면·
    두 옆면·필렛 면만 남긴 열린 쉘. OCCSewFaces 1·정리 끔(occ_fix_small 0)으로 읽으면 코너 Sphere 면이 메시 실패(재현)."""
    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        b = occ.addBox(0.0, 0.0, -20.0, 100.0, 80.0, 20.0)
        occ.synchronize()
        es = [e for _d, e in occ.getEntities(1)
              if occ.getBoundingBox(1, e)[3] > 99.9 and occ.getBoundingBox(1, e)[4] > 79.9 and occ.getBoundingBox(1, e)[5] > -1e-6]
        (v,) = occ.fillet([b], es, [float(r)])
        occ.synchronize()
        faces = [t for _d, t in occ.getEntities(2)]
        occ.remove([v])
        occ.remove([(2, s) for s in faces if abs(occ.getBoundingBox(2, s)[5] + 20.0) < 1e-3
                    or abs(occ.getBoundingBox(2, s)[3]) < 1e-3 or abs(occ.getBoundingBox(2, s)[4]) < 1e-3], recursive=True)
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)


def bead_with_features_step(path, spec: dict | None = None) -> str:
    """v0.15.1 실제 Ch/R 비드 바닥 근사(이슈 #53 면 2824 = 비드 바닥 딤플 추정): XY 판(z = 0, 쉘) + 사각 비드(깊이 20, 사면·바닥
    모서리 필렛) 바닥(z = −20)에 구면 딤플 3개(얕은·중간·깊은 반구 — 극점이 면 안, 둘레 필렛), Ø5·Ø10 관통 구멍, 버링(바닥 구멍에서
    아래로 짧은 원통 벽, 끝 열림). v0.16.0 세분화·재메시 시험에서도 다시 씀.

    만드는 법: 두꺼운 판 고체에서 비드 포켓을 빼고 필렛 → 딤플 구·버링 원통을 빼고 딤플 둘레 필렛 → 밑면·바깥 옆면을 지운 위쪽 면
    = 중립면 쉘 근사 → 버링 벽을 길이로 자르고 바닥 면에 관통 구멍 → fragment 로 모서리 공유. gmsh 가 쓴 STEP 이라 설정
    mesh.occ_sew_faces 1 로 읽는다. spec 은 BEAD_FEATURES 를 키별 덮어씀."""
    import gmsh
    sp = dict(BEAD_FEATURES)
    sp.update(spec or {})
    Lx, Ly = sp["plate"]
    bx, by, bw, bh, bd = sp["bead"]
    T = bd + 12.0                                            # 고체 두께(버링 길이·깊은 딤플보다 깊게)
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        slab = occ.addBox(0.0, 0.0, -T, Lx, Ly, T)
        pocket = occ.addBox(bx, by, -bd, bw, bh, bd + 1.0)
        (v,), _ = occ.cut([(3, slab)], [(3, pocket)])
        occ.synchronize()
        if sp.get("bead_fillet"):                            # 비드 위 테두리·바닥 모서리(포켓 모서리 전부)
            es = [e for _d, e in occ.getEntities(1)
                  if all(bx - 1e-6 <= q <= bx + bw + 1e-6 for q in occ.getBoundingBox(1, e)[0::3])
                  and all(by - 1e-6 <= q <= by + bh + 1e-6 for q in occ.getBoundingBox(1, e)[1::3])]
            (v,) = occ.fillet([v[1]], es, [float(sp["bead_fillet"])])
            occ.synchronize()
        tools = [(3, occ.addSphere(x, y, -bd + R - d, R)) for x, y, R, d in sp["dimples"]]
        cx, cy, cr, cl = sp["burr"]
        tools.append((3, occ.addCylinder(cx, cy, -T - 1.0, 0.0, 0.0, T + 2.0 - bd, cr)))
        (v,), _ = occ.cut([v], tools)
        occ.synchronize()
        if sp.get("dimple_fillet"):                          # 딤플 둘레(바닥 면과 구면이 만나는 원)
            es = []
            for x, y, R, d in sp["dimples"]:
                a = (R * R - (R - d) ** 2) ** 0.5
                for _d, e in occ.getEntities(1):
                    b = occ.getBoundingBox(1, e)
                    if abs(b[2] + bd) < 1e-4 and abs(b[5] + bd) < 1e-4 and abs(b[3] - b[0] - 2 * a) < 1e-3 \
                            and abs(0.5 * (b[0] + b[3]) - x) < 1e-3:
                        es.append(e)
            if es:
                (v,) = occ.fillet([v[1]], es, [float(sp["dimple_fillet"])])
                occ.synchronize()
        faces = [t for _d, t in occ.getEntities(2)]
        occ.remove([v])
        drop = []
        for s in faces:
            b = occ.getBoundingBox(2, s)
            if abs(b[5] + T) < 1e-6 or abs(b[3]) < 1e-6 or abs(b[0] - Lx) < 1e-6 or abs(b[4]) < 1e-6 \
                    or abs(b[1] - Ly) < 1e-6:            # 밑면·바깥 옆면
                drop.append((2, s))
        occ.remove(drop, recursive=True)
        occ.synchronize()
        cyl = [(2, t) for _d, t in occ.getEntities(2) if gmsh.model.getType(2, t) == "Cylinder"
               and abs(0.5 * (occ.getBoundingBox(2, t)[0] + occ.getBoundingBox(2, t)[3]) - cx) < 1e-3
               and abs(0.5 * (occ.getBoundingBox(2, t)[1] + occ.getBoundingBox(2, t)[4]) - cy) < 1e-3]
        if cyl:                                              # 버링 = 바닥(−bd)에서 아래로 길이 cl 만 남김
            occ.cut(cyl, [(3, occ.addBox(cx - cr - 1, cy - cr - 1, -T - 2.0, 2 * cr + 2, 2 * cr + 2, T + 2.0 - bd - cl))])
            occ.synchronize()
        floor = [(2, t) for _d, t in occ.getEntities(2) if gmsh.model.getType(2, t) == "Plane"
                 and abs(occ.getBoundingBox(2, t)[2] + bd) < 1e-3 and abs(occ.getBoundingBox(2, t)[5] + bd) < 1e-3]
        if sp["holes"] and floor:
            occ.cut(floor, [(3, occ.addCylinder(x, y, -bd - 1.0, 0.0, 0.0, 2.0, r)) for x, y, r in sp["holes"]])
            occ.synchronize()
        occ.fragment(list(occ.getEntities(2)), [])
        occ.synchronize()
        os.makedirs(os.path.dirname(os.path.abspath(str(path))), exist_ok=True)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return str(path)
